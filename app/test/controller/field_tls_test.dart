// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The field CA a phone controller makes (slice S6 of PE24,
// lib/controller/field_tls.dart), checked by the TLS the app and the phones
// actually use (Dart's BoringSSL): an HTTPS server with the phone's
// certificate is trusted by a client that trusts that CA alone, by address
// and by name, and by the app's own pinned check-in client; the fingerprint
// is the CA's DER's SHA-256; the Pi's renewal rules (tls.py): the same CA
// and server certificate on a restart, a new server certificate for new
// names or near its end, never a new CA on its own.

import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/controller/field_tls.dart';
import 'package:atalaia_app/security/der.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pointycastle/export.dart' as pc;

/// An HTTPS server on the loopback address answering "ok".
Future<HttpServer> serve(FieldTls tls) async {
  final s = await HttpServer.bindSecure(
    InternetAddress.loopbackIPv4,
    0,
    tls.context(),
  );
  s.listen((r) {
    r.response.write('ok');
    r.response.close();
  });
  return s;
}

Future<String> get(HttpClient c, Uri u) async {
  final req = await c.getUrl(u);
  final res = await req.close();
  return utf8.decodeStream(res);
}

HttpClient trusting(String caPem) => HttpClient(
  context: SecurityContext(withTrustedRoots: false)
    ..setTrustedCertificatesBytes(utf8.encode(caPem)),
);

void main() {
  late Directory tmp;
  setUp(() => tmp = Directory.systemTemp.createTempSync('atalaia-tls-'));
  tearDown(() => tmp.deleteSync(recursive: true));

  test(
    'a client trusting only the field CA reaches the phone, by address and by name',
    () async {
      final tls = FieldTls.ensure(
        tmp.path,
        certificateNames(['192.168.43.1']),
        fieldName: 'Moinho',
      );
      final server = await serve(tls);
      addTearDown(() => server.close(force: true));
      final c = trusting(tls.caPem);
      addTearDown(c.close);
      expect(
        await get(c, Uri.parse('https://127.0.0.1:${server.port}/')),
        'ok',
      );
      expect(
        await get(c, Uri.parse('https://localhost:${server.port}/')),
        'ok',
      );
      // The fingerprint is the CA's DER's SHA-256, as the Pi's.
      expect(tls.caSha256, sha256.convert(pemToDer(tls.caPem)!).bytes);
      expect(tls.caShort, matches(RegExp(r'^[0-9A-F]{4}( [0-9A-F]{4}){3}$')));
      expect(tls.names, ['localhost', '127.0.0.1', '192.168.43.1']);
    },
  );

  test(
    "the app's pinned check-in client trusts the phone controller",
    () async {
      final tls = FieldTls.ensure(tmp.path, certificateNames(const []));
      final server = await serve(tls);
      addTearDown(() => server.close(force: true));
      final field = PinnedField(
        fieldId: 'field',
        fieldName: 'Atalaia',
        caPem: tls.caPem,
        caSha256: tls.caSha256,
        urls: ['https://127.0.0.1:${server.port}'],
      );
      final c = field.client();
      addTearDown(c.close);
      expect(
        await get(c, Uri.parse('https://127.0.0.1:${server.port}/')),
        'ok',
      );
    },
  );

  test("another field's CA is refused", () async {
    final ours = FieldTls.ensure('${tmp.path}/a', certificateNames(const []));
    final other = FieldTls.ensure('${tmp.path}/b', certificateNames(const []));
    expect(ours.caHex, isNot(other.caHex));
    final server = await serve(ours);
    addTearDown(() => server.close(force: true));
    final c = trusting(other.caPem);
    addTearDown(c.close);
    await expectLater(
      get(c, Uri.parse('https://127.0.0.1:${server.port}/')),
      throwsA(isA<HandshakeException>()),
    );
  });

  test('a name the certificate does not cover is refused', () async {
    final tls = FieldTls.ensure(tmp.path, ['localhost']);
    final server = await serve(tls);
    addTearDown(() => server.close(force: true));
    final c = trusting(tls.caPem);
    addTearDown(c.close);
    await expectLater(
      get(c, Uri.parse('https://127.0.0.1:${server.port}/')),
      throwsA(isA<HandshakeException>()),
    );
  });

  test("the Pi's renewal rules: same names, new names, near the end", () {
    final t0 = DateTime.utc(2027, 1, 15, 8);
    final a = FieldTls.ensure(tmp.path, ['localhost'], now: t0);
    // A restart with the same names: the same CA and server certificate.
    final b = FieldTls.ensure(tmp.path, ['localhost'], now: t0);
    expect(b.caHex, a.caHex);
    expect(b.serverChainPem, a.serverChainPem);
    expect(b.serverKeyPem, a.serverKeyPem);
    // New names (another network): a new server certificate, the same CA.
    final c = FieldTls.ensure(tmp.path, ['localhost', '10.0.0.9'], now: t0);
    expect(c.caHex, a.caHex);
    expect(c.serverChainPem, isNot(a.serverChainPem));
    expect(c.names, ['localhost', '10.0.0.9']);
    // 30 days before its end: renewed.
    final late = t0.add(const Duration(days: serverDays - renewDays + 1));
    final d = FieldTls.ensure(tmp.path, ['localhost', '10.0.0.9'], now: late);
    expect(d.caHex, a.caHex);
    expect(d.serverChainPem, isNot(c.serverChainPem));
    expect(d.notAfter.isAfter(c.notAfter), isTrue);
    // The CA goes only with its files.
    File('${tmp.path}/ca.key').deleteSync();
    final e = FieldTls.ensure(tmp.path, ['localhost'], now: late);
    expect(e.caHex, isNot(a.caHex));
  });

  test('the certificates say what the Pi\'s say', () {
    final tls = FieldTls.ensure(
      tmp.path,
      ['localhost', '127.0.0.1', '192.168.43.1'],
      fieldName: 'Moinho',
      now: DateTime.utc(2027, 1, 15, 8),
    );
    final ca = Der.parse(tls.caDer).children[0].children;
    // v3, ECDSA with SHA-256, the issuer and subject alike.
    expect(ca[0].tag, 0xa0);
    expect(ca[2].bytes, Der.sequence([Der.oid('1.2.840.10045.4.3.2')]).bytes);
    expect(ca[3].bytes, ca[5].bytes);
    expect(
      utf8.decode(ca[5].bytes, allowMalformed: true),
      contains('Moinho field CA'),
    );
    // Valid ten years.
    final caValid = ca[4].children;
    expect(ascii.decode(caValid[1].contents), '370115080000Z');
    final leafDer = fromPem(tls.serverChainPem, 'CERTIFICATE');
    expect(
      leafDer,
      hasLength(2),
      reason: 'the server certificate, then the CA',
    );
    expect(leafDer[1], tls.caDer);
    final leaf = Der.parse(leafDer[0]).children[0].children;
    expect(leaf[3].bytes, ca[5].bytes, reason: 'issued by the CA');
    expect(ascii.decode(leaf[4].children[1].contents), '280115080000Z');
    // The subject alternative names: DNS localhost, IP 127.0.0.1 and 192.168.43.1.
    final exts = leaf[7].children[0].children;
    final san = exts.firstWhere(
      (e) =>
          e.children[0].bytes.toString() ==
          Der.oid('2.5.29.17').bytes.toString(),
    );
    final names = Der.parse(san.children.last.contents).children;
    expect(names.map((n) => n.tag), [0x82, 0x87, 0x87]);
    expect(ascii.decode(names[0].contents), 'localhost');
    expect(names[2].contents, [192, 168, 43, 1]);
  });

  test('keys survive their PEM, and the signatures verify', () {
    final key = EcKey.generate(Random(7));
    final again = EcKey.fromPem(key.toPkcs8Pem());
    expect(again.d, key.d);
    expect(again.publicPoint, key.publicPoint);
    final msg = Uint8List.fromList(utf8.encode('atalaia'));
    final sig = Der.parse(key.sign(msg)).children;
    final curve = pc.ECCurve_secp256r1();
    final verifier = pc.ECDSASigner(pc.SHA256Digest())
      ..init(
        false,
        pc.PublicKeyParameter(
          pc.ECPublicKey(curve.curve.decodePoint(key.publicPoint), curve),
        ),
      );
    expect(
      verifier.verifySignature(
        msg,
        pc.ECSignature(sig[0].asInteger, sig[1].asInteger),
      ),
      isTrue,
    );
    // RFC 6979: the same message, the same signature.
    expect(key.sign(msg), key.sign(msg));
  });

  test('the addresses another device can reach, best first', () {
    expect(
      orderAddresses([
        ('lo', '127.0.0.1'),
        ('rmnet_data0', '10.120.4.7'),
        ('wlan0', '192.168.1.40'),
        ('swlan0', '192.168.43.1'),
        ('eth0', '10.0.2.15'),
        ('wlan0', '169.254.3.3'),
      ]),
      ['192.168.43.1', '192.168.1.40', '10.0.2.15'],
    );
    expect(certificateNames(['192.168.43.1', '127.0.0.1']), [
      'localhost',
      '127.0.0.1',
      '192.168.43.1',
    ]);
  });
}
