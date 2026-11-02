// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Making an account from the app (LEG-*; the site server's decision S17-16
// unblocked): the account rests on the contract, not on consent, so the
// sign-up shows the privacy notice first, asks the person to say they read it
// and that they are 16 or older (no date of birth), and records both with the
// sign-up. Younger players check in at the field without an account, and the
// refusal says so. Against the fake site server (api/auth.py's register and
// the social sign-up).

import 'package:atalaia_app/l10n/strings.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_site.dart';
import '../support/fakes.dart';
import 'site_screens_test.dart' show FakeLinks, back, enter, reveal, tapKey;

/// The text in the page's error banner (the same words are on the boxes).
Finder inError(String text) => find.descendant(
  of: find.byKey(const Key('site-error')),
  matching: find.textContaining(text),
);

const appLink =
    'atalaia://register?site=https%3A%2F%2Fcampo.example.pt&field=campo-norte';

void main() {
  late FakeSite site;
  late FakeAuthBrowser browser;
  late FakeLinks links;

  Future<void> open(
    WidgetTester tester, {
    bool published = true,
    AppLanguage language = AppLanguage.pt,
  }) async {
    site = FakeSite();
    if (!published) site.noticeTexts = {};
    browser = FakeAuthBrowser();
    links = FakeLinks(appLink);
    final h = harness(
      language: language,
      siteHttp: site.http,
      links: links,
      authBrowser: browser,
      passkeys: FakePasskeys(),
    );
    await tester.pumpWidget(h.app());
    await tester.pumpAndSettle();
    await tapKey(tester, 'site-confirm');
    await tapKey(tester, 'site-signup-open');
  }

  Future<void> fill(WidgetTester tester) async {
    await enter(tester, 'site-signup-user', 'rita');
    await enter(tester, 'site-signup-password', 'a long enough password 1');
  }

  Future<void> readNotice(WidgetTester tester) async {
    await tapKey(tester, 'site-login-privacy');
    expect(find.byKey(const Key('privacy-text')), findsOneWidget);
    await back(tester);
    await tester.pumpAndSettle();
  }

  testWidgets('the notice first, then both boxes: the account is made with '
      'what was shown and a login follows', (tester) async {
    await open(tester);
    await fill(tester);
    // Not read yet: refused in words, nothing sent.
    await tapKey(tester, 'site-signup-create');
    expect(inError('lê o aviso de privacidade'), findsOneWidget);
    expect(site.lastRegister, isNull);
    await readNotice(tester);
    await tapKey(tester, 'site-login-notice');
    await tapKey(tester, 'site-signup-create');
    // Read, but the age is not confirmed: the refusal names the check-in.
    expect(inError('16 anos'), findsOneWidget);
    expect(inError('check-in no campo sem conta'), findsOneWidget);
    expect(site.lastRegister, isNull);
    await tapKey(tester, 'site-login-age');
    await tapKey(tester, 'site-signup-create');
    expect(site.lastRegister, {
      'username': 'rita',
      'password': 'a long enough password 1',
      'notice_seen': true,
      'age_confirmed': true,
      'notice_version': '2026-11',
    });
    expect(site.requests, contains('POST /auth/login'));
    expect(find.text('Jogos'), findsOneWidget); // signed in, on the field
  });

  testWidgets('the version on the screen is the one sent, and a notice that '
      'changed since is read again', (tester) async {
    await open(tester);
    await fill(tester);
    await readNotice(tester);
    await tapKey(tester, 'site-login-notice');
    await tapKey(tester, 'site-login-age');
    site.noticeVersion = '2026-12'; // published after it was read
    await tapKey(tester, 'site-signup-create');
    expect(inError('O aviso de privacidade mudou'), findsOneWidget);
    expect(site.registered, isEmpty);
    // The box is closed again until the new text is opened.
    await reveal(tester, find.byKey(const Key('site-login-notice')));
    expect(
      tester
          .widget<CheckboxListTile>(find.byKey(const Key('site-login-notice')))
          .onChanged,
      isNull,
    );
    await readNotice(tester);
    await tapKey(tester, 'site-login-notice');
    await tapKey(tester, 'site-signup-create');
    expect(site.lastRegister, containsPair('notice_version', '2026-12'));
    expect(find.text('Jogos'), findsOneWidget);
  });

  testWidgets('a name already taken is said, and the form stays', (
    tester,
  ) async {
    await open(tester);
    await enter(tester, 'site-signup-user', site.username);
    await enter(tester, 'site-signup-password', 'a long enough password 1');
    await readNotice(tester);
    await tapKey(tester, 'site-login-notice');
    await tapKey(tester, 'site-login-age');
    await tapKey(tester, 'site-signup-create');
    expect(inError('já está em uso'), findsOneWidget);
    expect(find.byKey(const Key('site-signup-create')), findsOneWidget);
  });

  testWidgets('no notice published: no account can be made here yet', (
    tester,
  ) async {
    await open(tester, published: false);
    expect(find.byKey(const Key('site-signup-no-notice')), findsOneWidget);
    await reveal(tester, find.byKey(const Key('site-signup-create')));
    final create = tester.widget<FilledButton>(
      find.byKey(const Key('site-signup-create')),
    );
    expect(create.onPressed, isNull);
  });

  testWidgets('back to the login without making anything', (tester) async {
    await open(tester);
    await tapKey(tester, 'site-signup-back');
    expect(find.byKey(const Key('site-login')), findsOneWidget);
    expect(site.lastRegister, isNull);
  });

  testWidgets('a social sign-up refused for the age says where to check in', (
    tester,
  ) async {
    await open(tester);
    await tapKey(tester, 'site-signup-back');
    browser.onOpen = (_) {
      final s = Uri.parse(site.lastReturnTo!).queryParameters['s']!;
      links.send(
        'https://campo.example.pt/app/oidc?s=$s&oidc_error=age_confirmation_required',
      );
    };
    await tapKey(tester, 'site-login-google');
    expect(inError('16 anos'), findsOneWidget);
    expect(inError('check-in no campo sem conta'), findsOneWidget);
  });
}
