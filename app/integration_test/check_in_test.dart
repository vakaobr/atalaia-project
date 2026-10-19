// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// On an Android device or emulator: checking in at the field with its
// poster, over real HTTPS. The phone serves a stand-in field controller on
// 127.0.0.1 with a test-only CA (test_certs.dart; the API's answers come
// from test/support/fake_field.dart, the shapes controller/atalaia_controller
// sends). The app pins that CA from the poster's fingerprint, checks in,
// declares a replica, and follows the game over WSS, where the snapshot's
// history shows what happened before it connected.

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/checkin/checkin_screen.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import '../test/support/fake_field.dart';
import 'support.dart';
import 'test_certs.dart';

/// The stand-in controller: HTTPS on a free port, the check-in API from
/// [FakeField], the CA endpoint, and the live stream.
class DeviceField {
  DeviceField._(this.server, this.field);

  final HttpServer server;
  final FakeField field;
  final streams = <WebSocket>[];
  final streamTokens = <String>[];

  static Future<DeviceField> start() async {
    final ctx = SecurityContext()
      ..useCertificateChainBytes(utf8.encode(testServerCertPem))
      ..usePrivateKeyBytes(utf8.encode(testServerKeyPem));
    final server = await HttpServer.bindSecure(
      InternetAddress.loopbackIPv4,
      0,
      ctx,
    );
    final field = FakeField(der: pemToDer(testCaPem)!, pem: testCaPem)
      ..wifiSsid = 'Atalaia';
    field.urls
      ..clear()
      ..add('https://127.0.0.1:${server.port}');
    final f = DeviceField._(server, field);
    server.listen(f._serve);
    return f;
  }

  Future<void> _serve(HttpRequest req) async {
    final path = req.uri.path;
    if (path == '/api/v1/controller/ca') {
      req.response.headers.contentType = ContentType(
        'application',
        'x-pem-file',
      );
      req.response.write(testCaPem);
      await req.response.close();
      return;
    }
    if (path == '/api/v1/stream') {
      streamTokens.add(req.uri.queryParameters['token'] ?? '');
      final ws = await WebSocketTransformer.upgrade(req);
      streams.add(ws);
      ws.add(
        jsonEncode({
          'type': 'hello',
          'game': {
            'id': 42,
            'name': 'Domingo de manhã',
            'teams': ['red', 'blue'],
            'state': 'running',
            'game_time_ms': 60000,
            'live': true,
          },
          'score': {
            'game': 42,
            'teams': {'red': 5, 'blue': 0},
          },
          'nodes': [
            {'node_id': 2, 'name': 'Moinho', 'owner': 'red'},
          ],
          // What happened before the phone connected.
          'events': [
            {
              'node': 0,
              't': 0,
              'type': 'game.start',
              'data': {'preset': 'Domínio'},
            },
            {
              'node': 2,
              't': 30000,
              'type': 'zone.captured',
              'team': 'red',
              'data': {'zone': 'Moinho'},
            },
          ],
          'me': {'player_id': 'x', 'role': 'player', 'team': 'red'},
        }),
      );
      return;
    }
    final auth = req.headers.value('authorization');
    final text = await utf8.decodeStream(req);
    final body = text.isEmpty ? null : jsonDecode(text);
    final r = field.handle(
      req.method,
      path.replaceFirst('/api/v1', ''),
      body,
      auth?.startsWith('Bearer ') == true ? auth!.substring(7) : null,
    );
    req.response
      ..statusCode = r.status
      ..headers.contentType = ContentType.json
      ..write(jsonEncode(r.body));
    await req.response.close();
  }

  Future<void> close() async {
    for (final ws in streams) {
      await ws.close();
    }
    await server.close(force: true);
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('check in with the poster over HTTPS, declare, follow the game', (
    tester,
  ) async {
    final f = await DeviceField.start();
    addTearDown(f.close);
    await tester.pumpWidget(
      deviceApp(home: CheckinScreen(posterText: f.field.posterText())),
    );
    await waitFor(tester, find.byKey(const Key('checkin-notice-ok')));
    await tapVisible(tester, find.byKey(const Key('checkin-notice-ok')));
    await waitFor(tester, find.byKey(const Key('checkin-name')));
    expect(find.textContaining('Certificado do campo'), findsOneWidget);
    await reveal(tester, find.byKey(const Key('checkin-name')));
    await tester.enterText(find.byKey(const Key('checkin-name')), 'Falcão');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    await tapVisible(tester, find.byKey(const Key('checkin-submit')));
    await waitFor(tester, find.text('Check-in feito.'));
    expect(f.field.rows.values.single['display_name'], 'Falcão');

    // A replica for this game.
    await tapVisible(tester, find.byKey(const Key('checkin-declare')));
    await waitFor(tester, find.byKey(const Key('declare-add')));
    await tapVisible(tester, find.byKey(const Key('declare-add')));
    await waitFor(tester, find.byKey(const Key('replica-save')));
    await tester.tap(find.byKey(const Key('replica-save')));
    await tester.pumpAndSettle();
    await tapVisible(tester, find.byKey(const Key('declare-save')));
    await waitFor(tester, find.byKey(const Key('declare-saved')));
    expect((f.field.rows.values.single['declarations']! as List), hasLength(1));
    await goBack(tester);
    await waitFor(tester, find.text('por cronografar'));

    // Following the game: WSS with the pinned CA and the player token; the
    // history from before the phone connected is on the screen.
    await tapVisible(tester, find.byKey(const Key('checkin-follow')));
    await waitFor(tester, find.text('Domingo de manhã'));
    // On a small screen the events are below the fold: scroll to them.
    await reveal(tester, find.text('A equipa vermelha capturou Moinho'));
    expect(find.text('A equipa vermelha capturou Moinho'), findsOneWidget);
    expect(f.streamTokens.single, startsWith('apt1.'));
  });

  testWidgets("a poster whose fingerprint is not the controller's is refused", (
    tester,
  ) async {
    final f = await DeviceField.start();
    addTearDown(f.close);
    final forged = f.field.posterText(
      ca: Uint8List.fromList([for (final b in f.field.sha256Bytes) b ^ 0xff]),
    );
    await tester.pumpWidget(deviceApp(home: CheckinScreen(posterText: forged)));
    await waitFor(tester, find.byKey(const Key('checkin-error')));
    expect(find.textContaining('não é o do cartaz'), findsOneWidget);
    expect(f.field.rows, isEmpty);
  });
}
