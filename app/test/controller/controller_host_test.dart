// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The phone controller put together (slice S6 of PE24,
// lib/controller/controller_host.dart), on the real core and real sockets:
// HTTP on the loopback address with the GM console, HTTPS with the field CA
// once opened to the field's Wi-Fi, a game run from creation to its end
// over HTTPS trusting that CA alone, the check-in poster and join payloads
// naming the CA and the addresses, the broker's opening, a new address
// taken up with a new certificate, a restart keeping the game, the tokens
// and the CA, and an I/O pod (the pod firmware's own code) as the radio.

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_host.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/protocol/checkin_poster.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/pod_host.dart';

final joinKey = Uint8List.fromList(List.generate(32, (i) => 100 + i));
final limits = File(
  'lib/chrono/limit_templates/portugal.yaml',
).readAsStringSync();

Future<bool> waitFor(
  FutureOr<bool> Function() ok, {
  Duration timeout = const Duration(seconds: 8),
}) async {
  final end = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(end)) {
    if (await ok()) return true;
    await Future<void>.delayed(const Duration(milliseconds: 25));
  }
  return ok();
}

/// A request's status, headers and body (JSON when it is).
Future<(int, HttpHeaders, Object?)> call(
  HttpClient c,
  String method,
  Uri u, {
  String? token,
  Object? body,
}) async {
  final req = await c.openUrl(method, u);
  if (token != null) req.headers.set('Authorization', 'Bearer $token');
  if (body != null) {
    req.headers.contentType = ContentType.json;
    req.write(jsonEncode(body));
  }
  final res = await req.close();
  final text = await utf8.decodeStream(res);
  Object? json;
  try {
    json = jsonDecode(text);
  } on FormatException {
    json = text;
  }
  return (res.statusCode, res.headers, json);
}

void main() {
  late AtalaiaCore core;
  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  late Directory tmp;
  final hosts = <ControllerHost>[];
  setUp(() => tmp = Directory.systemTemp.createTempSync('atalaia-host-'));
  tearDown(() async {
    for (final h in hosts) {
      await h.stop();
    }
    hosts.clear();
    tmp.deleteSync(recursive: true);
  });

  ControllerBoot boot({
    bool open = true,
    List<String>? addresses = const ['127.0.0.1'],
    Map<String, Uint8List> console = const {},
    bool pod = false,
  }) => ControllerBoot(
    dir: '${tmp.path}/controller',
    joinKey: joinKey,
    limitsYaml: limits,
    noticePt: 'Aviso: {operator}, {retention_days} dias.',
    noticeEn: 'Notice: {operator}, {retention_days} days.',
    console: console,
    open: open,
    pod: pod,
    httpPort: 0,
    httpsPort: 0,
    mqttPort: 0,
    mqttTlsPort: 0,
    openAddress: '127.0.0.1',
    addresses: addresses,
  );

  Future<ControllerHost> start(
    ControllerBoot b, {
    Future<List<String>> Function()? addresses,
    PodTransport? pod,
  }) async {
    final h = ControllerHost(
      b,
      core: core,
      addresses: addresses,
      podTransport: pod,
    );
    await h.start();
    hosts.add(h);
    return h;
  }

  test('opened: a game run over HTTPS trusting the field CA alone', () async {
    final h = await start(
      boot(
        console: {
          'index.html': Uint8List.fromList(utf8.encode('<!DOCTYPE html>')),
        },
      ),
    );
    final st = h.status();
    expect(st['open'], isTrue);
    final http = HttpClient();
    addTearDown(http.close);
    final local = Uri.parse('http://127.0.0.1:${st['http_port']}');

    // The console on the loopback address, with the Pi's headers.
    final (cs, ch, _) = await call(http, 'GET', local.resolve('/console/'));
    expect(cs, 200);
    expect(ch.value('content-security-policy'), contains("default-src 'self'"));

    // The CA as phones fetch it, its fingerprint the status's and the header's.
    final (s1, h1, pem) = await call(
      http,
      'GET',
      local.resolve('/api/v1/controller/ca'),
    );
    expect(s1, 200);
    final der = base64.decode(
      (pem! as String)
          .replaceAll(RegExp(r'-----[A-Z ]+-----'), '')
          .replaceAll(RegExp(r'\s'), ''),
    );
    expect(hexEncode(sha256.convert(der).bytes), st['ca_sha256']);
    expect(h1.value('x-atalaia-ca-sha256'), st['ca_sha256']);

    // HTTPS at the open address, trusting that CA and nothing else.
    final urls = (st['urls']! as List).cast<String>();
    expect(urls, ['https://127.0.0.1:${st['https_port']}']);
    final https = HttpClient(
      context: SecurityContext(withTrustedRoots: false)
        ..setTrustedCertificatesBytes(utf8.encode(pem as String)),
    );
    addTearDown(https.close);
    final base = Uri.parse(urls.first);
    final gm = st['gm_token']! as String;
    final (w, _, who) = await call(
      https,
      'GET',
      base.resolve('/api/v1/whoami'),
      token: gm,
    );
    expect(w, 200);
    expect((who! as Map)['role'], 'gm');
    final (ws, _, me) = await call(
      https,
      'GET',
      base.resolve('/api/v1/whoami'),
      token: st['read_token']! as String,
    );
    expect(ws, 200);
    expect((me! as Map)['role'], 'read');

    // A game from creation to its end.
    final (c, _, game) = await call(
      https,
      'POST',
      base.resolve('/api/v1/games'),
      token: gm,
      body: {'name': 'Domingo', 'mode_id': 'org.atalaia.domination'},
    );
    expect(c, 201, reason: '$game');
    final id = (game! as Map)['id'];
    final (j, _, join) = await call(
      https,
      'POST',
      base.resolve('/api/v1/join'),
      token: gm,
      body: {'role': 'zone'},
    );
    expect(j, 200, reason: '$join');
    // Join keys 13 and 14: an Android prop links over Wi-Fi with them.
    final joined = join! as Map;
    expect(joined['wifi_link'], isTrue);
    final payload = decodeJoin(
      joinFromText(joined['text']! as String),
      joinKey,
    );
    expect(hexEncode(payload.caSha256!), st['ca_sha256']);
    expect(payload.urls, urls);
    final (s, _, started) = await call(
      https,
      'POST',
      base.resolve('/api/v1/games/$id/start'),
      token: gm,
      body: {'force': true},
    );
    expect(s, 200, reason: '$started');
    expect(
      await waitFor(() => (h.status()['game']! as Map)['state'] == 'running'),
      isTrue,
    );
    final (e, _, ended) = await call(
      https,
      'POST',
      base.resolve('/api/v1/games/$id/end'),
      token: gm,
    );
    expect(e, 200, reason: '$ended');
    expect(h.status()['game'], isNull);

    // The check-in poster names the CA and the addresses.
    final (p, _, poster) = await call(
      https,
      'GET',
      base.resolve('/api/v1/checkin/poster'),
      token: gm,
    );
    expect(p, 200);
    final text = (poster! as Map)['text'] as String?;
    expect(text, isNotNull, reason: '$poster');
    final parsed = parsePoster(text!);
    expect(hexEncode(parsed.caSha256), st['ca_sha256']);
    expect(parsed.urls, urls);

    // The scoreboard's QR link (decision PD13): https, the read code and
    // the CA's fingerprint; the app checks the CA against it and follows the
    // stream with that CA alone, which default trust would refuse.
    final (l, lh, sb) = await call(
      https,
      'GET',
      base.resolve('/api/v1/scoreboard-link'),
      token: gm,
    );
    expect(l, 200);
    expect(lh.value('cache-control'), 'no-store');
    final links = ((sb! as Map)['links']! as List).cast<String>();
    expect(links, [
      '${urls.first}/scoreboard#token=${st['read_token']}'
          '&ca=${st['ca_sha256']}',
    ]);
    final link = FieldLink.parse(links.first)!;
    expect(hexEncode(link.caSha256!), st['ca_sha256']);
    await expectLater(
      WebSocket.connect(link.stream.toString()),
      throwsA(isA<HandshakeException>()),
    );
    final trust = FieldTrust(MemoryAppStore());
    final pinned = await link.trusted(trust);
    final socket = await pinnedConnect(pinned.stream, pinned.field!);
    addTearDown(socket.close);
    final first = await socket.messages.first.timeout(
      const Duration(seconds: 10),
    );
    expect(jsonDecode(first), containsPair('type', 'hello'));
    final forged = FieldLink.parse(
      '${urls.first}/scoreboard#token=x&ca=${'ab' * 32}',
    )!;
    await expectLater(
      forged.trusted(trust),
      throwsA(
        isA<TrustException>().having(
          (e) => e.reason,
          'reason',
          TrustFailure.mismatch,
        ),
      ),
    );
  });

  test(
    'closed: only the loopback address, no poster, no Wi-Fi joins',
    () async {
      final h = await start(boot(open: false));
      final st = h.status();
      expect(st['https_port'], isNull);
      expect(st['urls'], isEmpty);
      expect(h.broker.address.isLoopback, isTrue);
      final http = HttpClient();
      addTearDown(http.close);
      final local = Uri.parse('http://127.0.0.1:${st['http_port']}');
      final gm = st['gm_token']! as String;
      final (_, _, poster) = await call(
        http,
        'GET',
        local.resolve('/api/v1/checkin/poster'),
        token: gm,
      );
      expect((poster! as Map)['problem_code'], 'no_address');
      await call(
        http,
        'POST',
        local.resolve('/api/v1/games'),
        token: gm,
        body: {'name': 'Domingo', 'mode_id': 'org.atalaia.domination'},
      );
      final (_, _, join) = await call(
        http,
        'POST',
        local.resolve('/api/v1/join'),
        token: gm,
        body: {'role': 'zone'},
      );
      expect((join! as Map)['wifi_link'], isFalse);
    },
  );

  test(
    'a new address: a new certificate for it, the same CA and port',
    () async {
      var now = ['127.0.0.1'];
      final h = await start(boot(addresses: null), addresses: () async => now);
      final before = h.status();
      expect(before['cert_names'], ['localhost', '127.0.0.1']);
      await h.check();
      expect(
        h.status()['cert_names'],
        before['cert_names'],
        reason: 'no change',
      );
      now = ['127.0.0.1', '192.168.43.1'];
      await h.check();
      final after = h.status();
      expect(after['cert_names'], ['localhost', '127.0.0.1', '192.168.43.1']);
      expect(after['ca_sha256'], before['ca_sha256']);
      expect(after['https_port'], before['https_port']);
      expect(after['urls'], [
        'https://127.0.0.1:${before['https_port']}',
        'https://192.168.43.1:${before['https_port']}',
      ]);
      // The listener took the new certificate.
      final pem = h.tls.caPem;
      final https = HttpClient(
        context: SecurityContext(withTrustedRoots: false)
          ..setTrustedCertificatesBytes(utf8.encode(pem)),
      );
      addTearDown(https.close);
      final (s, _, _) = await call(
        https,
        'GET',
        Uri.parse('https://127.0.0.1:${after['https_port']}/healthz'),
      );
      expect(s, 200);
    },
  );

  test(
    'the poster and the certificate follow the addresses (check-R8, R9)',
    () async {
      var now = ['127.0.0.1', '10.42.0.1'];
      final h = await start(boot(addresses: null), addresses: () async => now);
      final port = h.status()['https_port'];
      h.checkin.warn = (_) {};
      // The GM pins the poster to a name and to an address of this phone.
      h.checkin.setPoster({
        'urls': ['https://campo.lan:$port', 'https://10.42.0.1:$port'],
      });
      await h.check();
      expect(h.status()['cert_names'], contains('campo.lan'));
      expect(h.checkin.posterFields()['urls'], [
        'https://campo.lan:$port',
        'https://10.42.0.1:$port',
      ]);
      // The address goes away: the poster loses it, the name stays, and the
      // certificate no longer covers the address.
      final warned = <String>[];
      h.checkin.warn = warned.add;
      now = ['127.0.0.1', '192.168.43.1'];
      await h.check();
      expect(warned.single, contains('10.42.0.1'));
      expect(h.checkin.posterFields()['urls'], ['https://campo.lan:$port']);
      expect(h.status()['cert_names'], [
        'localhost',
        '127.0.0.1',
        'campo.lan',
        '192.168.43.1',
      ]);
    },
  );

  test('a restart keeps the live game, the tokens and the CA', () async {
    final a = await start(boot());
    final first = a.status();
    final gm = first['gm_token']! as String;
    final game = a.engine.createGame({
      'name': 'Domingo',
      'mode_id': 'org.atalaia.domination',
    });
    a.engine.startGame(game['id']! as int, force: true);
    await a.stop();
    hosts.remove(a);
    final b = await start(boot());
    final second = b.status();
    expect(second['gm_token'], gm);
    expect(second['read_token'], first['read_token']);
    expect(second['ca_sha256'], first['ca_sha256']);
    expect((second['game']! as Map)['state'], 'running');
    expect((second['game']! as Map)['key_lost'], isFalse);
    expect(gm, startsWith('gm-'));
    expect(gm.length, greaterThan(20));
  });

  test(
    'an I/O pod as the radio, through the relay',
    skip: hostSkip(['ATALAIA_POD_HOST']),
    () async {
      final hub = await AirHub.start();
      addTearDown(hub.close);
      final pod = await HostPod.start(airPeer: hub.port);
      addTearDown(pod.stop);
      hub.members.add(pod.airPort);
      final link = await SocketPodTransport.usb(pod);
      // The relay as the controller's isolate has it: the UI isolate's link
      // on the other side.
      late RelayPodTransport relay;
      relay = RelayPodTransport('relay', (b) => unawaited(link.send(b)));
      link.incoming.listen(relay.receive, onDone: () => relay.linkClosed());
      final h = await start(boot(pod: true), pod: relay);
      expect(await waitFor(() => h.status()['radio'] == 'up'), isTrue);
      expect(h.status()['pod'], isTrue);
      await link.close();
      expect(await waitFor(() => h.status()['radio'] == 'down'), isTrue);
    },
  );

  test(
    'a USB radio modem as the radio, through the relay (slice S7c)',
    skip: hostSkip(['ATALAIA_MODEM_HOST']),
    () async {
      final hub = await AirHub.start();
      addTearDown(hub.close);
      final modem = await HostModem.start(airPeer: hub.port);
      addTearDown(modem.stop);
      hub.members.add(modem.airPort);
      final link = await SocketPodTransport.modem(modem);
      late RelayPodTransport relay;
      relay = RelayPodTransport('relay', (b) => unawaited(link.send(b)));
      link.incoming.listen(relay.receive, onDone: () => relay.linkClosed());
      final h = await start(boot(pod: true), pod: relay);
      expect(await waitFor(() => h.status()['radio'] == 'up'), isTrue);
      expect(h.status()['radio_kind'], 'modem');
      expect(h.status()['field_frames'], isTrue);
      expect(h.engine.boxes, isNotNull);
      expect(h.engine.pairing, isNotNull);
      expect(h.engine.adoption, isNotNull);
      expect(h.engine.firmware, isNotNull);
    },
  );
}
