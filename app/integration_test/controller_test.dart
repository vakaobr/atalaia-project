// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// On an Android device or emulator (CI's flutter-integration job): a game
// run from the phone as the field controller (slice S6 of PE24). The
// controller role starts from the home screen: its own isolate with the
// APK's core, the foreground service, the API on the loopback address and,
// opened to the field's Wi-Fi, HTTPS with a field CA made on the phone.
// Over that HTTPS, trusting only the CA the phone serves, a game is created,
// started and ended, and the screen follows it; the console is served from
// the APK's assets; the controller stops.

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/app.dart';
import 'package:atalaia_app/controller/controller_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'support.dart';

Future<(int, Object?)> call(
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
  try {
    return (res.statusCode, jsonDecode(text));
  } on FormatException {
    return (res.statusCode, text);
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('a game run from the phone as the field controller', (
    tester,
  ) async {
    await tester.pumpWidget(deviceApp());
    await waitFor(tester, find.byKey(const Key('role-controller')));
    await tapVisible(tester, find.byKey(const Key('role-controller')));
    await waitFor(tester, find.byKey(const Key('ctl-start')));
    await tapVisible(tester, find.byKey(const Key('ctl-start')));
    await waitFor(tester, find.byKey(const Key('ctl-stop')));

    final shell = AppScope.of(
      tester.element(find.byType(ControllerScreen)),
    ).services.controller;
    final st = shell.status!;
    expect(st.running, isTrue);
    expect(st.hasConsole, isTrue, reason: 'the APK carries the console');
    final http = HttpClient();
    addTearDown(http.close);
    final local = Uri.parse('http://127.0.0.1:${st.httpPort}');
    final (cs, _) = await call(http, 'GET', local.resolve('/console/'));
    expect(cs, 200);
    final (_, pem) = await call(
      http,
      'GET',
      local.resolve('/api/v1/controller/ca'),
    );

    // HTTPS at the phone's own address when it has one (the emulator's
    // 10.0.2.15), trusting only the field CA; else the loopback address.
    final https = HttpClient(
      context: SecurityContext(withTrustedRoots: false)
        ..setTrustedCertificatesBytes(utf8.encode(pem! as String)),
    );
    addTearDown(https.close);
    final client = st.urls.isEmpty ? http : https;
    final base = st.urls.isEmpty ? local : Uri.parse(st.urls.first);
    final gm = st.gmToken;
    final (c, game) = await call(
      client,
      'POST',
      base.resolve('/api/v1/games'),
      token: gm,
      body: {'name': 'Emulador', 'mode_id': 'org.atalaia.domination'},
    );
    expect(c, 201, reason: '$game');
    final id = (game! as Map)['id'];
    final (s, _) = await call(
      client,
      'POST',
      base.resolve('/api/v1/games/$id/start'),
      token: gm,
      body: {'force': true},
    );
    expect(s, 200);
    await waitFor(tester, find.textContaining('Emulador'));
    await waitFor(tester, find.textContaining('a decorrer'));
    final (e, _) = await call(
      client,
      'POST',
      base.resolve('/api/v1/games/$id/end'),
      token: gm,
    );
    expect(e, 200);

    await tapVisible(tester, find.byKey(const Key('ctl-stop')));
    await waitFor(tester, find.byKey(const Key('ctl-start')));
    expect(shell.running, isFalse);
  });
}
