// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The field's own certificate authority and the phone controller's HTTPS
/// certificate (ADR-P3-9, P3-8; slice S6 of PE24): what the Pi controller's
/// controller/atalaia_controller/tls.py makes, made on the phone. On the
/// controller's first start, in its folder of the app's private storage:
///
///     ca.pem, ca.key           the field CA: ECDSA P-256, valid 10 years
///     server.pem, server.key   the phone's certificate, signed by the CA,
///                              valid 1 year, for its names and addresses
///                              (subject alternative names), then the CA
///     server.json              the names and the end of validity it was made for
///
/// The CA's fingerprint (SHA-256 of its DER) goes on the check-in poster and
/// into join payloads (key 13); phones fetch the certificate itself from
/// `GET /api/v1/controller/ca` and pin it per field (protocol/checkin.md).
/// As on the Pi, the server certificate is made again when it has less than
/// 30 days left or when the names it must cover change (the phone joined
/// another network, its hotspot took another address); the CA is never
/// replaced on its own, which would break every pinned phone: only by
/// forgetting the controller's folder. ECDSA P-256 as on the Pi (decision
/// PE2: browsers do not take Ed25519 in TLS); signatures are RFC 6979's
/// deterministic ECDSA with SHA-256 (pointycastle), the DER the app's own
/// (security/der.dart). Keys are PKCS #8, which Dart's TLS (BoringSSL)
/// reads.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:pointycastle/export.dart' as pc;

import '../protocol/checkin_poster.dart' show shortFingerprint;
import '../security/bytes.dart';
import '../security/der.dart';

const caDays = 3653;
const serverDays = 365;
const renewDays = 30;

const _oidEcPublicKey = '1.2.840.10045.2.1';
const _oidP256 = '1.2.840.10045.3.1.7';
const _oidEcdsaSha256 = '1.2.840.10045.4.3.2';
const _oidOrganization = '2.5.4.10';
const _oidCommonName = '2.5.4.3';
const _oidSubjectKeyId = '2.5.29.14';
const _oidKeyUsage = '2.5.29.15';
const _oidSubjectAltName = '2.5.29.17';
const _oidBasicConstraints = '2.5.29.19';
const _oidAuthorityKeyId = '2.5.29.35';
const _oidExtKeyUsage = '2.5.29.37';
const _oidServerAuth = '1.3.6.1.5.5.7.3.1';

final _curve = pc.ECCurve_secp256r1();

/// An ECDSA P-256 key pair.
final class EcKey {
  EcKey._(this.d) : publicPoint = (_curve.G * d)!.getEncoded(false);

  /// A new key from [random] (a secure one unless a test says otherwise).
  factory EcKey.generate([Random? random]) {
    final r = random ?? Random.secure();
    final n = _curve.n;
    while (true) {
      final d = bigIntOf(List<int>.generate(32, (_) => r.nextInt(256)));
      if (d > BigInt.zero && d < n) return EcKey._(d);
    }
  }

  /// The key in a PKCS #8 PEM this file wrote.
  factory EcKey.fromPem(String pem) {
    final der = fromPem(pem, 'PRIVATE KEY');
    if (der.isEmpty) throw const FormatException('no PRIVATE KEY block');
    final pkcs8 = Der.parse(der.first).children;
    final ec = Der.parse(pkcs8[2].contents).children;
    final d = bigIntOf(ec[1].contents);
    if (d <= BigInt.zero || d >= _curve.n) {
      throw const FormatException('not a P-256 private key');
    }
    return EcKey._(d);
  }

  final BigInt d;

  /// The public key, uncompressed (0x04, X, Y).
  final Uint8List publicPoint;

  /// SubjectPublicKeyInfo.
  Der get spki => Der.sequence([
    Der.sequence([Der.oid(_oidEcPublicKey), Der.oid(_oidP256)]),
    Der.bitString(publicPoint),
  ]);

  /// RFC 5280's key identifier: SHA-1 of the public key's bits.
  Uint8List get keyId => Uint8List.fromList(sha1.convert(publicPoint).bytes);

  /// PKCS #8 with the SEC 1 ECPrivateKey inside (RFC 5915).
  String toPkcs8Pem() {
    final ec = Der.sequence([
      Der.smallInteger(1),
      Der.octetString(fixedBytes(d, 32)),
      Der.explicit(1, Der.bitString(publicPoint)),
    ]);
    final pkcs8 = Der.sequence([
      Der.smallInteger(0),
      Der.sequence([Der.oid(_oidEcPublicKey), Der.oid(_oidP256)]),
      Der.octetString(ec.bytes),
    ]);
    return toPem('PRIVATE KEY', pkcs8.bytes);
  }

  /// ECDSA with SHA-256, k from RFC 6979, as DER (r, s).
  Uint8List sign(List<int> message) {
    final signer = pc.ECDSASigner(
      pc.SHA256Digest(),
      pc.HMac(pc.SHA256Digest(), 64),
    )..init(true, pc.PrivateKeyParameter(pc.ECPrivateKey(d, _curve)));
    final sig =
        signer.generateSignature(Uint8List.fromList(message)) as pc.ECSignature;
    return Der.sequence([Der.integer(sig.r), Der.integer(sig.s)]).bytes;
  }
}

/// A certificate's Name: O and CN as the Pi writes them.
Der _name({String? organization, required String commonName}) => Der.sequence([
  if (organization != null)
    Der.set([
      Der.sequence([Der.oid(_oidOrganization), Der.utf8String(organization)]),
    ]),
  Der.set([
    Der.sequence([Der.oid(_oidCommonName), Der.utf8String(commonName)]),
  ]),
]);

Der _extension(String oid, Der value, {bool critical = false}) => Der.sequence([
  Der.oid(oid),
  if (critical) Der.boolean(true),
  Der.octetString(value.bytes),
]);

/// A name as a GeneralName: an IP address when it is one, else a DNS name.
Der _generalName(String name) {
  final ip = InternetAddress.tryParse(name.replaceAll(RegExp(r'^\[|\]$'), ''));
  if (ip != null) return Der.implicit(7, ip.rawAddress);
  return Der.implicit(2, ascii.encode(name));
}

/// A positive serial of up to 16 bytes (RFC 5280: at most 20).
Der _serial(Random random) {
  final b = List<int>.generate(16, (_) => random.nextInt(256));
  b[0] = (b[0] & 0x7f) | 0x01;
  return Der.integer(bigIntOf(b));
}

Uint8List _certificate(Der tbs, EcKey signer) => Der.sequence([
  tbs,
  Der.sequence([Der.oid(_oidEcdsaSha256)]),
  Der.bitString(signer.sign(tbs.bytes)),
]).bytes;

/// The field CA's certificate (self-signed), as the Pi's tls.ensure makes it.
Uint8List makeCaCertificate(
  EcKey key, {
  required String fieldName,
  required DateTime now,
  Random? random,
}) {
  final subject = _name(
    organization: 'Atalaia field',
    commonName:
        '${fieldName.length > 40 ? fieldName.substring(0, 40) : fieldName} field CA',
  );
  final tbs = Der.sequence([
    Der.explicit(0, Der.smallInteger(2)),
    _serial(random ?? Random.secure()),
    Der.sequence([Der.oid(_oidEcdsaSha256)]),
    subject,
    Der.sequence([
      Der.time(now.subtract(const Duration(hours: 1))),
      Der.time(now.add(const Duration(days: caDays))),
    ]),
    subject,
    key.spki,
    Der.explicit(
      3,
      Der.sequence([
        _extension(
          _oidBasicConstraints,
          Der.sequence([Der.boolean(true), Der.smallInteger(0)]),
          critical: true,
        ),
        // keyCertSign and cRLSign (bits 5 and 6).
        _extension(
          _oidKeyUsage,
          Der.bitString([0x06], unused: 1),
          critical: true,
        ),
        _extension(_oidSubjectKeyId, Der.octetString(key.keyId)),
      ]),
    ),
  ]);
  return _certificate(tbs, key);
}

/// The phone's server certificate for [names], signed by the CA.
Uint8List makeServerCertificate(
  EcKey key, {
  required EcKey caKey,
  required Uint8List caDer,
  required List<String> names,
  required DateTime now,
  Random? random,
}) {
  final issuer = Der.parse(caDer).children[0].children[5];
  final tbs = Der.sequence([
    Der.explicit(0, Der.smallInteger(2)),
    _serial(random ?? Random.secure()),
    Der.sequence([Der.oid(_oidEcdsaSha256)]),
    issuer,
    Der.sequence([
      Der.time(now.subtract(const Duration(hours: 1))),
      Der.time(now.add(const Duration(days: serverDays))),
    ]),
    _name(commonName: names.isEmpty ? 'atalaia' : names.first),
    key.spki,
    Der.explicit(
      3,
      Der.sequence([
        _extension(_oidBasicConstraints, Der.sequence([]), critical: true),
        _extension(
          _oidSubjectAltName,
          Der.sequence([for (final n in names) _generalName(n)]),
        ),
        _extension(_oidExtKeyUsage, Der.sequence([Der.oid(_oidServerAuth)])),
        _extension(
          _oidAuthorityKeyId,
          Der.sequence([Der.implicit(0, caKey.keyId)]),
        ),
      ]),
    ),
  ]);
  return _certificate(tbs, caKey);
}

/// The field CA and the server certificate in use.
final class FieldTls {
  FieldTls._({
    required this.dir,
    required this.caPem,
    required this.caDer,
    required this.serverChainPem,
    required this.serverKeyPem,
    required this.names,
    required this.notAfter,
  }) : caSha256 = Uint8List.fromList(sha256.convert(caDer).bytes);

  final String dir;
  final String caPem;
  final Uint8List caDer;

  /// SHA-256 of the CA's DER: the poster's and join key 13's fingerprint.
  final Uint8List caSha256;

  /// The server certificate, then the CA (what the TLS server sends).
  final String serverChainPem;
  final String serverKeyPem;

  /// The names and addresses the server certificate covers.
  final List<String> names;
  final DateTime notAfter;

  String get caHex => hexEncode(caSha256);
  String get caShort => shortFingerprint(caSha256);

  /// For HttpServer.bindSecure and the broker's TLS listener.
  SecurityContext context() => SecurityContext(withTrustedRoots: false)
    ..useCertificateChainBytes(utf8.encode(serverChainPem))
    ..usePrivateKeyBytes(utf8.encode(serverKeyPem));

  /// The CA and a current server certificate for [names] in [dir], made or
  /// renewed as needed (tls.py `ensure`).
  static FieldTls ensure(
    String dir,
    List<String> names, {
    String fieldName = 'Atalaia',
    DateTime? now,
    Random? random,
  }) {
    final d = Directory(dir)..createSync(recursive: true);
    final t = (now ?? DateTime.now()).toUtc();
    final caKeyFile = File('${d.path}/ca.key');
    final caFile = File('${d.path}/ca.pem');
    final keyFile = File('${d.path}/server.key');
    final certFile = File('${d.path}/server.pem');
    final infoFile = File('${d.path}/server.json');

    EcKey caKey;
    Uint8List caDer;
    var newCa = false;
    if (caKeyFile.existsSync() && caFile.existsSync()) {
      caKey = EcKey.fromPem(caKeyFile.readAsStringSync());
      final ders = fromPem(caFile.readAsStringSync(), 'CERTIFICATE');
      if (ders.isEmpty) {
        throw const FormatException('ca.pem has no certificate');
      }
      caDer = ders.first;
    } else {
      caKey = EcKey.generate(random);
      caDer = makeCaCertificate(
        caKey,
        fieldName: fieldName,
        now: t,
        random: random,
      );
      _write(caKeyFile, caKey.toPkcs8Pem());
      _write(caFile, toPem('CERTIFICATE', caDer));
      newCa = true;
    }
    final caPem = toPem('CERTIFICATE', caDer);
    final caHex = hexEncode(sha256.convert(caDer).bytes);

    var renew = true;
    DateTime? notAfter;
    if (!newCa &&
        keyFile.existsSync() &&
        certFile.existsSync() &&
        infoFile.existsSync()) {
      try {
        final info = jsonDecode(infoFile.readAsStringSync()) as Map;
        notAfter = DateTime.fromMillisecondsSinceEpoch(
          (info['not_after'] as int) * 1000,
          isUtc: true,
        );
        final had = (info['names'] as List).cast<String>();
        renew =
            info['ca_sha256'] != caHex ||
            !_sameList(had, names) ||
            notAfter.difference(t) < const Duration(days: renewDays);
      } on Object {
        renew = true;
      }
    }
    if (renew) {
      final key = EcKey.generate(random);
      final der = makeServerCertificate(
        key,
        caKey: caKey,
        caDer: caDer,
        names: names,
        now: t,
        random: random,
      );
      notAfter = DateTime.fromMillisecondsSinceEpoch(
        t.add(const Duration(days: serverDays)).millisecondsSinceEpoch ~/
            1000 *
            1000,
        isUtc: true,
      );
      _write(keyFile, key.toPkcs8Pem());
      _write(certFile, toPem('CERTIFICATE', der) + caPem);
      _write(
        infoFile,
        jsonEncode({
          'names': names,
          'not_after': notAfter.millisecondsSinceEpoch ~/ 1000,
          'ca_sha256': caHex,
        }),
      );
    }
    return FieldTls._(
      dir: d.path,
      caPem: caPem,
      caDer: caDer,
      serverChainPem: certFile.readAsStringSync(),
      serverKeyPem: keyFile.readAsStringSync(),
      names: List.unmodifiable(names),
      notAfter: notAfter!,
    );
  }

  static bool _sameList(List<String> a, List<String> b) =>
      a.length == b.length &&
      [for (var i = 0; i < a.length; i++) a[i] == b[i]].every((x) => x);

  /// Whole files replaced by rename, so a crash leaves the old one or the
  /// new one. The folder is the app's private storage (Android keeps it
  /// from other apps: decisions PE24-44, PE24-60).
  static void _write(File f, String text) {
    final tmp = File('${f.path}.tmp');
    tmp.writeAsStringSync(text, flush: true);
    tmp.renameSync(f.path);
  }
}

/// The names the server certificate covers: localhost, the loopback
/// address and [addresses] (the phone's own, from [localAddresses]).
List<String> certificateNames(List<String> addresses) {
  final out = <String>['localhost', '127.0.0.1'];
  for (final a in addresses) {
    if (!out.contains(a)) out.add(a);
  }
  return out;
}

/// The phone's IPv4 addresses another device could reach it at, best
/// first: no loopback or link-local ones; a hotspot's (an access point
/// interface: ap, swlan, softap) before a Wi-Fi client's (wlan), then the
/// rest (a USB or Ethernet link), each kind in the interfaces' order. Mobile
/// data (rmnet, ccmni, pdp) is left out: the field's devices are not there.
Future<List<String>> localAddresses() async {
  final List<NetworkInterface> list;
  try {
    list = await NetworkInterface.list(type: InternetAddressType.IPv4);
  } on Object {
    return const [];
  }
  return orderAddresses([
    for (final i in list)
      for (final a in i.addresses) (i.name, a.address),
  ]);
}

/// [localAddresses]' rule on (interface name, address) pairs.
List<String> orderAddresses(List<(String, String)> found) {
  int rank(String iface) {
    final n = iface.toLowerCase();
    if (RegExp(r'^(ap|swlan|softap|wlan1)').hasMatch(n)) return 0;
    if (n.startsWith('wlan')) return 1;
    if (RegExp(r'^(rmnet|ccmni|pdp|v4-rmnet|dummy|tun|ppp)').hasMatch(n)) {
      return 9;
    }
    return 2;
  }

  final out = <(int, int, String)>[];
  var i = 0;
  for (final (iface, addr) in found) {
    final ip = InternetAddress.tryParse(addr);
    i++;
    if (ip == null || ip.type != InternetAddressType.IPv4) continue;
    if (ip.isLoopback || ip.isLinkLocal || addr == '0.0.0.0') continue;
    final r = rank(iface);
    if (r == 9) continue;
    out.add((r, i, addr));
  }
  out.sort((a, b) => a.$1 != b.$1 ? a.$1 - b.$1 : a.$2 - b.$2);
  final seen = <String>{};
  return [
    for (final (_, _, a) in out)
      if (seen.add(a)) a,
  ];
}
