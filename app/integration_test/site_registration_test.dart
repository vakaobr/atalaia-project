// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// On an Android device or emulator: online registration on a field's site
// server (decision S16-13) with the app's real dart:io client. The phone
// serves a stand-in site server on http://127.0.0.1 (the only plain-http
// sites the app accepts are this phone's and the emulator host's); its
// answers and refresh-token cookie come from test/support/fake_site.dart.
// The player opens the field's page address, confirms the site, logs in,
// registers for a game and gets the ticket, kept on the phone.

import 'package:atalaia_app/site/site_screens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import '../test/support/fake_site.dart';
import 'support.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('log in to the site, register, keep the ticket', (tester) async {
    final site = FakeSite();
    final server = await serveFakeSite(site);
    addTearDown(() => server.close(force: true));
    await tester.pumpWidget(deviceApp(home: const SiteScreen()));
    await waitFor(tester, find.byKey(const Key('site-address')));
    await tester.enterText(
      find.byKey(const Key('site-address')),
      'http://127.0.0.1:${server.port}/f/campo-norte',
    );
    await tapVisible(tester, find.byKey(const Key('site-open')));
    await waitFor(tester, find.byKey(const Key('site-confirm')));
    await tapVisible(tester, find.byKey(const Key('site-confirm')));
    await waitFor(tester, find.byKey(const Key('site-user')));
    await tester.enterText(find.byKey(const Key('site-user')), site.username);
    await tester.enterText(
      find.byKey(const Key('site-password')),
      site.password,
    );
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    await tapVisible(tester, find.byKey(const Key('site-login')));
    const game = 'site-game-0192f3a0-0000-7000-8000-000000000001';
    await waitFor(tester, find.byKey(const Key(game)));
    await tapVisible(tester, find.byKey(const Key(game)));
    await waitFor(tester, find.byKey(const Key('reg-federation')));
    await reveal(tester, find.byKey(const Key('reg-federation')));
    await tester.enterText(find.byKey(const Key('reg-federation')), 'FPA-1');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    await tapVisible(tester, find.byKey(const Key('reg-submit')));
    await waitFor(tester, find.byKey(const Key('ticket-qr')));
    expect(site.regs.values.single['federation_number'], 'FPA-1');
    await goBack(tester);
    await waitFor(tester, find.text('Tens inscrição neste jogo.'));
  });
}
