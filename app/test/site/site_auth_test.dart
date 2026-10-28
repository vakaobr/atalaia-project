// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Logging in without a password and the account's login methods (decision
// PKA-1; lib/site/site_auth.dart, account_screen.dart): the return link of a
// social login read and matched to the attempt, the whole flow with a fake
// browser and a fake Credential Manager against the fake site server, the
// login screen's buttons, and every part of the account screen.

import 'dart:async';

import 'package:atalaia_app/platform/services.dart';
import 'package:atalaia_app/site/account_screen.dart';
import 'package:atalaia_app/site/site_auth.dart';
import 'package:atalaia_app/site/site_client.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_site.dart';
import '../support/fakes.dart';
import 'site_screens_test.dart' show FakeLinks, enter, tapKey;

const _nonce = 'AbCdEfGhIjKlMnOp1234';

/// The register page's link to the field, no game: the field's own screen.
const appLink =
    'atalaia://register?site=https%3A%2F%2Fcampo.example.pt&field=campo-norte';

void main() {
  final origin = Uri.parse('https://campo.example.pt');

  group('the return link', () {
    test('a return reads as the nonce, the ticket and the outcome', () {
      final r = OidcReturn.parse(
        'https://campo.example.pt/app/oidc?s=$_nonce#oidc=tkt.abc-1',
      )!;
      expect((r.site, r.nonce, r.ticket), (origin, _nonce, 'tkt.abc-1'));
      final linked = OidcReturn.parse(
        'https://campo.example.pt:8443/app/oidc?s=$_nonce&oidc=linked',
      )!;
      expect(linked.site, Uri.parse('https://campo.example.pt:8443'));
      expect((linked.ok, linked.ticket), ('linked', null));
      final failed = OidcReturn.parse(
        'https://campo.example.pt/app/oidc?s=$_nonce&oidc_error=consent_required',
      )!;
      expect(failed.error, 'consent_required');
    });

    test('anything else is not one', () {
      for (final t in [
        'http://campo.example.pt/app/oidc?s=$_nonce',
        'atalaia://register?site=https%3A%2F%2Fcampo.example.pt',
        'https://campo.example.pt/app/other?s=$_nonce',
        'https://campo.example.pt/app/oidc',
        'https://campo.example.pt/app/oidc?s=short',
        'https://campo.example.pt/app/oidc?s=$_nonce%20x',
        'https://user@campo.example.pt/app/oidc?s=$_nonce',
        'https://campo.example.pt/app/oidc/x?s=$_nonce',
        'https://campo.example.pt/f/campo-norte',
        'nonsense',
      ]) {
        expect(OidcReturn.parse(t), isNull, reason: t);
      }
      // A code or a ticket that is not shaped like one is dropped.
      final odd = OidcReturn.parse(
        'https://campo.example.pt/app/oidc?s=$_nonce&oidc_error=<script>#oidc=a&b',
      )!;
      expect((odd.error, odd.ticket), (null, null));
    });

    test('only the attempt that waits gets its return', () async {
      final returns = AuthReturns();
      final other = Uri.parse('https://elsewhere.example');
      final w = returns.wait(origin, _nonce);
      returns
        ..add(
          OidcReturn(site: origin, nonce: 'another-nonce-1234', ticket: 'x'),
        )
        ..add(OidcReturn(site: other, nonce: _nonce, ticket: 'y'))
        ..add(OidcReturn(site: origin, nonce: _nonce, ticket: 'mine'));
      expect((await w.result)!.ticket, 'mine');
    });

    test('a wait ends on cancel and on timeout', () async {
      final returns = AuthReturns();
      final a = returns.wait(origin, _nonce)..cancel();
      expect(await a.result, isNull);
      final b = returns.wait(
        origin,
        _nonce,
        timeout: const Duration(milliseconds: 10),
      );
      expect(await b.result, isNull);
    });
  });

  group('the calls', () {
    late FakeSite site;
    late FakeAuthBrowser browser;
    late FakePasskeys passkeys;
    late AuthReturns returns;
    late SiteSession session;
    late SiteAuth auth;

    setUp(() {
      site = FakeSite();
      browser = FakeAuthBrowser();
      passkeys = FakePasskeys();
      returns = AuthReturns();
      session = SiteSession(
        origin,
        site.http(origin),
        SiteAccounts(MemoryAppStore()),
      );
      auth = SiteAuth(
        session,
        browser: browser,
        passkeys: passkeys,
        returns: returns,
      );
      // The site's redirect, as the phone opens it.
      browser.onOpen = (_) {
        final s = Uri.parse(site.lastReturnTo!).queryParameters['s'];
        scheduleMicrotask(
          () => returns.add(
            OidcReturn(site: origin, nonce: s!, ticket: site.goodTicket),
          ),
        );
      };
    });

    test('a social login: the app\'s own return link, the browser, the '
        'ticket, a session', () async {
      final name = await auth.oidc('google', consent: true);
      expect(name, 'falcao');
      final ret = Uri.parse(site.lastReturnTo!);
      expect(ret.origin, 'https://campo.example.pt');
      expect(ret.path, '/app/oidc');
      expect(ret.queryParameters['s'], hasLength(24));
      expect(site.lastStartPurpose, 'login');
      expect(site.lastStartConsent, isTrue);
      // The browser is opened at the site's own address, nothing else.
      expect(browser.opened.single.host, 'campo.example.pt');
      expect(browser.opened.single.path, contains('/auth/oidc/google/browser'));
      // The session works and its token is kept.
      expect(await session.accounts.refreshToken('$origin'), isNotNull);
      expect((await auth.mine()).identities, isEmpty);
    });

    test('the nonce is new for each attempt', () async {
      await auth.oidc('google');
      final first = site.lastReturnTo;
      await auth.oidc('google');
      expect(site.lastReturnTo, isNot(first));
    });

    test(
      'a refusal at the provider or the site is the server\'s code',
      () async {
        browser.onOpen = (_) {
          final s = Uri.parse(site.lastReturnTo!).queryParameters['s']!;
          scheduleMicrotask(
            () => returns.add(
              OidcReturn(site: origin, nonce: s, error: 'consent_required'),
            ),
          );
        };
        await expectLater(
          auth.oidc('google'),
          throwsA(
            isA<OidcFailure>().having(
              (e) => e.code,
              'code',
              'consent_required',
            ),
          ),
        );
        // A ticket the site does not take is a refusal of its own.
        browser.onOpen = (_) {
          final s = Uri.parse(site.lastReturnTo!).queryParameters['s']!;
          scheduleMicrotask(
            () =>
                returns.add(OidcReturn(site: origin, nonce: s, ticket: 'bad')),
          );
        };
        await expectLater(
          auth.oidc('google'),
          throwsA(
            isA<SiteException>().having(
              (e) => e.code,
              'code',
              'invalid_ticket',
            ),
          ),
        );
        // A return with no ticket is not a login.
        browser.onOpen = (_) {
          final s = Uri.parse(site.lastReturnTo!).queryParameters['s']!;
          scheduleMicrotask(
            () => returns.add(OidcReturn(site: origin, nonce: s)),
          );
        };
        await expectLater(
          auth.oidc('google'),
          throwsA(
            isA<OidcFailure>().having((e) => e.code, 'code', 'state_invalid'),
          ),
        );
      },
    );

    test('no browser, or the person gives up', () async {
      browser.works = false;
      await expectLater(
        auth.oidc('google'),
        throwsA(
          isA<OidcFailure>().having(
            (e) => e.code,
            'code',
            'browser_unavailable',
          ),
        ),
      );
      browser
        ..works = true
        ..onOpen = null;
      await expectLater(
        auth.oidc('google', onOpened: (w) => w.cancel()),
        throwsA(isA<OidcFailure>().having((e) => e.code, 'code', 'cancelled')),
      );
      // No browser service at all (iOS, tests).
      await expectLater(
        SiteAuth(session, returns: returns).oidc('google'),
        throwsA(
          isA<OidcFailure>().having(
            (e) => e.code,
            'code',
            'browser_unavailable',
          ),
        ),
      );
    });

    test('an address that is not the site\'s is not opened', () async {
      // A server (or someone in between) that names another host.
      final other = FakeSite()..offers = site.offers;
      final s = SiteSession(
        Uri.parse('https://evil.example'),
        _Rewriting(other.http(origin), 'https://elsewhere.example'),
        SiteAccounts(MemoryAppStore()),
      );
      await expectLater(
        SiteAuth(s, browser: browser, returns: returns).oidc('google'),
        throwsA(
          isA<OidcFailure>().having(
            (e) => e.code,
            'code',
            'browser_unavailable',
          ),
        ),
      );
      expect(browser.opened, isEmpty);
    });

    test('a passkey login needs no user name; the credential goes to the '
        'site as the phone made it', () async {
      final name = await auth.passkeyLogin();
      expect(name, 'falcao');
      expect(passkeys.requests.single, contains('"challenge":"chal"'));
      final sent = site.bodies['POST /auth/passkey/login']! as Map;
      expect(sent['challenge_token'], 'tok-login');
      expect((sent['credential'] as Map)['id'], 'cred-1');
    });

    test(
      'a passkey the site does not know, a closed sheet, no support',
      () async {
        passkeys.credentialId = 'stranger';
        await expectLater(
          auth.passkeyLogin(),
          throwsA(
            isA<SiteException>().having(
              (e) => e.code,
              'code',
              'invalid_passkey',
            ),
          ),
        );
        passkeys.failWith = 'cancelled';
        await expectLater(
          auth.passkeyLogin(),
          throwsA(
            isA<PasskeyException>().having((e) => e.cancelled, 'x', true),
          ),
        );
        await expectLater(
          SiteAuth(session).passkeyLogin(),
          throwsA(
            isA<PasskeyException>().having((e) => e.reason, 'r', 'unsupported'),
          ),
        );
        expect(await SiteAuth(session).passkeysAvailable(), isFalse);
      },
    );

    test('an older server offers the password only', () async {
      site.refusals['GET /auth/methods'] = (404, 'Not Found');
      final m = await auth.methods();
      expect((m.passwordLogin, m.passkeys, m.oidc.length), (true, false, 0));
    });
  });

  group('the login screen', () {
    late FakeSite site;
    late FakeAuthBrowser browser;
    late FakePasskeys passkeys;
    late FakeLinks links;
    late Harness h;

    Future<void> open(WidgetTester tester) async {
      site = FakeSite();
      browser = FakeAuthBrowser();
      passkeys = FakePasskeys();
      links = FakeLinks(appLink);
      h = harness(
        siteHttp: site.http,
        links: links,
        authBrowser: browser,
        passkeys: passkeys,
      );
      browser.onOpen = (_) {
        final s = Uri.parse(site.lastReturnTo!).queryParameters['s']!;
        // The phone opens the App Link: the app hears it from the activity.
        links.send('https://campo.example.pt/app/oidc?s=$s#oidc=good-ticket');
      };
      await tester.pumpWidget(h.app());
      await tester.pumpAndSettle();
      await tapKey(tester, 'site-confirm');
    }

    testWidgets('the password, a passkey and each provider the site offers', (
      tester,
    ) async {
      await open(tester);
      expect(find.byKey(const Key('site-login')), findsOneWidget);
      expect(find.byKey(const Key('site-login-passkey')), findsOneWidget);
      expect(find.byKey(const Key('site-login-google')), findsOneWidget);
      expect(find.byKey(const Key('site-login-microsoft')), findsOneWidget);
      expect(find.byKey(const Key('site-login-apple')), findsNothing);
      expect(find.text('Entrar com Google'), findsOneWidget);
    });

    testWidgets('a social login: the browser, the return, the field\'s games, '
        'and the consent box goes only when ticked', (tester) async {
      await open(tester);
      await tapKey(tester, 'site-login-google');
      expect(site.lastStartConsent, isFalse);
      expect(find.text('Jogos'), findsOneWidget); // the field's games
      expect(browser.opened, hasLength(1));
      expect(find.byKey(const Key('site-error')), findsNothing);
    });

    testWidgets('the consent box is sent when ticked', (tester) async {
      await open(tester);
      await tapKey(tester, 'site-login-consent');
      await tapKey(tester, 'site-login-google');
      expect(site.lastStartConsent, isTrue);
      expect(find.text('Jogos'), findsOneWidget); // the field's games
    });

    testWidgets('a refusal comes back in words, and the login stays', (
      tester,
    ) async {
      await open(tester);
      browser.onOpen = (_) {
        final s = Uri.parse(site.lastReturnTo!).queryParameters['s']!;
        links.send(
          'https://campo.example.pt/app/oidc?s=$s&oidc_error=consent_required',
        );
      };
      await tapKey(tester, 'site-login-google');
      expect(find.byKey(const Key('site-error')), findsOneWidget);
      expect(find.textContaining('autorização'), findsOneWidget);
      expect(find.byKey(const Key('site-login-google')), findsOneWidget);
    });

    testWidgets('while the browser is open the screen waits, and can give '
        'up', (tester) async {
      await open(tester);
      browser.onOpen = null; // the person is still at the provider
      await tester.tap(find.byKey(const Key('site-login-google')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('site-waiting')), findsOneWidget);
      // Someone else's return (another nonce) is ignored.
      links.send(
        'https://campo.example.pt/app/oidc?s=SomeoneElsesNonce123#oidc=good-ticket',
      );
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('site-waiting')), findsOneWidget);
      await tester.tap(find.byKey(const Key('site-waiting-cancel')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('site-login-google')), findsOneWidget);
      expect(find.textContaining('cancelada'), findsOneWidget);
    });

    testWidgets('a passkey logs in', (tester) async {
      await open(tester);
      await tapKey(tester, 'site-login-passkey');
      expect(find.text('Jogos'), findsOneWidget); // the field's games
      expect(passkeys.requests, hasLength(1));
    });

    testWidgets('a closed passkey sheet says so; the password still works', (
      tester,
    ) async {
      await open(tester);
      passkeys.failWith = 'cancelled';
      await tapKey(tester, 'site-login-passkey');
      expect(find.byKey(const Key('site-error')), findsOneWidget);
      expect(find.byKey(const Key('site-login')), findsOneWidget);
    });

    testWidgets('no passkeys on the phone: no passkey button; the site with '
        'the password off: no password form', (tester) async {
      site = FakeSite();
      site.offers = {
        'password_login': false,
        'passkeys': true,
        'oidc': <Object?>[],
      };
      passkeys = FakePasskeys()..present = false;
      h = harness(
        siteHttp: site.http,
        links: FakeLinks(appLink),
        authBrowser: FakeAuthBrowser(),
        passkeys: passkeys,
      );
      await tester.pumpWidget(h.app());
      await tester.pumpAndSettle();
      await tapKey(tester, 'site-confirm');
      expect(find.byKey(const Key('site-login-passkey')), findsNothing);
      expect(find.byKey(const Key('site-login')), findsNothing);
      expect(find.byKey(const Key('site-user')), findsNothing);
      expect(find.byKey(const Key('site-login-google')), findsNothing);
    });

    testWidgets('a site that says nothing of this (an older one): the '
        'password form as before', (tester) async {
      site = FakeSite();
      site.refusals['GET /auth/methods'] = (404, 'Not Found');
      h = harness(siteHttp: site.http, links: FakeLinks(appLink));
      await tester.pumpWidget(h.app());
      await tester.pumpAndSettle();
      await tapKey(tester, 'site-confirm');
      expect(find.byKey(const Key('site-login')), findsOneWidget);
      expect(find.byKey(const Key('site-login-passkey')), findsNothing);
      expect(find.byKey(const Key('site-login-google')), findsNothing);
    });
  });

  group('the account screen', () {
    late FakeSite site;
    late FakeAuthBrowser browser;
    late FakePasskeys passkeys;
    late FakeLinks links;
    late Harness h;
    late SiteSession session;

    Future<void> open(
      WidgetTester tester, {
      bool passwordSet = true,
      bool totp = false,
      List<Map<String, Object?>>? identities,
      List<Map<String, Object?>>? keys,
    }) async {
      // A tall screen: the whole long list is built.
      tester.view.physicalSize = const Size(800, 4000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      site = FakeSite();
      site.passwordSet = passwordSet;
      site.totpEnabled = totp;
      site.identities.addAll(identities ?? const []);
      site.passkeys.addAll(keys ?? const []);
      browser = FakeAuthBrowser();
      passkeys = FakePasskeys();
      links = FakeLinks();
      h = harness(
        siteHttp: site.http,
        links: links,
        authBrowser: browser,
        passkeys: passkeys,
      );
      final origin = Uri.parse('https://campo.example.pt');
      session = h.services.sites.of(origin);
      await session.login(site.username, site.password);
      await tester.pumpWidget(h.app(home: SiteAccountScreen(session: session)));
      await tester.pumpAndSettle();
    }

    final google = {
      'provider': 'google',
      'label': 'Google',
      'linked_at': '2026-10-01T10:00:00+00:00',
      'last_login_at': null,
    };
    final key1 = {
      'id': 'k-one',
      'name': 'Pixel',
      'backed_up': false,
      'created_at': '2026-10-02T10:00:00+00:00',
      'last_used_at': null,
    };

    testWidgets('what the server says: methods, passkeys, password, TOTP', (
      tester,
    ) async {
      await open(tester, identities: [google], keys: [key1]);
      expect(find.byKey(const Key('account-identity-google')), findsOneWidget);
      expect(find.byKey(const Key('account-link-microsoft')), findsOneWidget);
      expect(find.byKey(const Key('account-link-google')), findsNothing);
      expect(find.byKey(const Key('account-passkey-k-one')), findsOneWidget);
      expect(find.text('Pixel'), findsOneWidget);
      expect(find.byKey(const Key('account-confirm-password')), findsOneWidget);
      expect(find.text('Esta conta tem palavra-passe.'), findsOneWidget);
      expect(find.byKey(const Key('account-totp-enable')), findsOneWidget);
    });

    testWidgets('link a provider with the password; the return of the browser '
        'is the answer', (tester) async {
      await open(tester);
      browser.onOpen = (_) {
        final s = Uri.parse(site.lastReturnTo!).queryParameters['s']!;
        site.identities.add({...google, 'provider': 'microsoft'});
        links.send('https://campo.example.pt/app/oidc?s=$s&oidc=linked');
      };
      // Without the password the app asks for it, and does not start.
      await tapKey(tester, 'account-link-microsoft');
      expect(find.byKey(const Key('account-error')), findsOneWidget);
      expect(browser.opened, isEmpty);
      await enter(tester, 'account-confirm-password', site.password);
      await tapKey(tester, 'account-link-microsoft');
      expect(site.lastStartPurpose, 'link');
      expect(browser.opened, hasLength(1));
      expect(find.byKey(const Key('account-ok')), findsOneWidget);
      expect(
        find.byKey(const Key('account-identity-microsoft')),
        findsOneWidget,
      );
    });

    testWidgets('a wrong password is said in words', (tester) async {
      await open(tester);
      await enter(tester, 'account-confirm-password', 'wrong');
      await tapKey(tester, 'account-link-google');
      expect(find.text('Palavra-passe errada.'), findsOneWidget);
      expect(browser.opened, isEmpty);
    });

    testWidgets('unlink asks first, then sends the password', (tester) async {
      await open(
        tester,
        identities: [
          google,
          {...google, 'provider': 'microsoft'},
        ],
      );
      await enter(tester, 'account-confirm-password', site.password);
      await tapKey(tester, 'account-unlink-google');
      expect(find.byType(AlertDialog), findsOneWidget);
      await tester.tap(find.text('Cancelar').last);
      await tester.pumpAndSettle();
      expect(site.identities, hasLength(2));
      await tapKey(tester, 'account-unlink-google');
      await tester.tap(find.text('Desligar').last);
      await tester.pumpAndSettle();
      expect(site.identities.map((i) => i['provider']), ['microsoft']);
      expect(find.byKey(const Key('account-identity-google')), findsNothing);
    });

    testWidgets('the last way in is refused in words', (tester) async {
      await open(tester, passwordSet: false, identities: [google]);
      site.confirmed = true;
      await tapKey(tester, 'account-unlink-google');
      await tester.tap(find.text('Desligar').last);
      await tester.pumpAndSettle();
      expect(find.textContaining('última forma de entrar'), findsOneWidget);
      expect(site.identities, hasLength(1));
    });

    testWidgets('add a passkey with a name; rename it; remove it', (
      tester,
    ) async {
      await open(tester);
      await enter(tester, 'account-confirm-password', site.password);
      await enter(tester, 'account-passkey-name', 'Telemóvel');
      await tapKey(tester, 'account-passkey-add');
      expect(site.passkeys.single['name'], 'Telemóvel');
      expect(passkeys.requests.single, contains('chal-new'));
      expect(find.byKey(const Key('account-ok')), findsOneWidget);
      final id = '${site.passkeys.single['id']}';
      await tapKey(tester, 'account-passkey-rename-$id');
      await tester.enterText(
        find.byKey(const Key('account-rename-field')),
        'Principal',
      );
      await tester.tap(find.text('Guardar'));
      await tester.pumpAndSettle();
      expect(site.passkeys.single['name'], 'Principal');
      await enter(tester, 'account-confirm-password', site.password);
      await tapKey(tester, 'account-passkey-remove-$id');
      await tester.tap(find.text('Remover').last);
      await tester.pumpAndSettle();
      expect(site.passkeys, isEmpty);
    });

    testWidgets('a closed passkey sheet; and no passkeys on this phone', (
      tester,
    ) async {
      await open(tester);
      await enter(tester, 'account-confirm-password', site.password);
      passkeys.failWith = 'cancelled';
      await tapKey(tester, 'account-passkey-add');
      expect(find.byKey(const Key('account-error')), findsOneWidget);
      expect(site.passkeys, isEmpty);
    });

    testWidgets('no Credential Manager: the passkey form says why', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(800, 4000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      site = FakeSite();
      h = harness(
        siteHttp: site.http,
        links: FakeLinks(),
        authBrowser: FakeAuthBrowser(),
        passkeys: FakePasskeys()..present = false,
      );
      final session = h.services.sites.of(
        Uri.parse('https://campo.example.pt'),
      );
      await session.login(site.username, site.password);
      await tester.pumpWidget(h.app(home: SiteAccountScreen(session: session)));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('account-passkey-unsupported')),
        findsOneWidget,
      );
      expect(find.byKey(const Key('account-passkey-add')), findsNothing);
    });

    testWidgets('change the password; a short one is refused in words', (
      tester,
    ) async {
      await open(tester);
      await enter(tester, 'account-confirm-password', site.password);
      await enter(tester, 'account-new-password', 'short');
      await tapKey(tester, 'account-password-save');
      expect(find.text('A palavra-passe é curta demais.'), findsOneWidget);
      await enter(tester, 'account-new-password', 'a much longer password 42');
      await tapKey(tester, 'account-password-save');
      expect(site.accountPassword, 'a much longer password 42');
      expect(find.byKey(const Key('account-ok')), findsOneWidget);
    });

    testWidgets('remove the password when another way in exists', (
      tester,
    ) async {
      await open(tester, identities: [google]);
      await enter(tester, 'account-confirm-password', site.password);
      await tapKey(tester, 'account-password-remove');
      await tester.tap(find.text('Remover').last);
      await tester.pumpAndSettle();
      expect(site.passwordSet, isFalse);
      expect(find.text('Esta conta não tem palavra-passe.'), findsOneWidget);
      // The box for the password is gone; the confirmation is a recent proof.
      expect(find.byKey(const Key('account-confirm-password')), findsNothing);
    });

    testWidgets('turn TOTP on with a code, then off', (tester) async {
      await open(tester);
      await enter(tester, 'account-confirm-password', site.password);
      await tapKey(tester, 'account-totp-enable');
      expect(find.text('JBSWY3DPEHPK3PXP'), findsOneWidget);
      await enter(tester, 'account-totp-enrol-code', '000000');
      await tapKey(tester, 'account-totp-confirm');
      expect(find.text('Código errado.'), findsOneWidget);
      await enter(tester, 'account-totp-enrol-code', site.code);
      await tapKey(tester, 'account-totp-confirm');
      expect(site.totpEnabled, isTrue);
      expect(find.text('O TOTP está ativo nesta conta.'), findsOneWidget);
      await enter(tester, 'account-confirm-password', site.password);
      await enter(tester, 'account-totp-disable-code', site.code);
      await tapKey(tester, 'account-totp-disable');
      expect(site.totpEnabled, isFalse);
    });

    testWidgets('an account with no password confirms with a TOTP code, a '
        'passkey, or the provider again', (tester) async {
      await open(
        tester,
        passwordSet: false,
        totp: true,
        identities: [google],
        keys: [key1],
      );
      expect(find.byKey(const Key('account-confirm-password')), findsNothing);
      // Without the proof the server says so, in words.
      await tapKey(tester, 'account-passkey-remove-k-one');
      await tester.tap(find.text('Remover').last);
      await tester.pumpAndSettle();
      expect(find.textContaining('Confirmar primeiro'), findsOneWidget);
      expect(site.passkeys, hasLength(1));
      // With a code.
      await enter(tester, 'account-confirm-code', '000000');
      await tapKey(tester, 'account-confirm-code-button');
      expect(find.text('Código errado.'), findsOneWidget);
      expect(site.confirmed, isFalse);
      await enter(tester, 'account-confirm-code', site.code);
      await tapKey(tester, 'account-confirm-code-button');
      expect(site.confirmed, isTrue);
      // With a passkey.
      site.confirmed = false;
      await tapKey(tester, 'account-confirm-passkey');
      expect(site.confirmed, isTrue);
      // With the provider again.
      site.confirmed = false;
      browser.onOpen = (_) {
        final s = Uri.parse(site.lastReturnTo!).queryParameters['s']!;
        site.confirmed = true;
        links.send('https://campo.example.pt/app/oidc?s=$s&oidc=reauth');
      };
      await tapKey(tester, 'account-reauth-google');
      expect(site.lastStartPurpose, 'reauth');
      expect(site.confirmed, isTrue);
      // Now the removal goes through.
      await tapKey(tester, 'account-passkey-remove-k-one');
      await tester.tap(find.text('Remover').last);
      await tester.pumpAndSettle();
      expect(site.passkeys, isEmpty);
    });

    testWidgets('waiting for the browser can be given up', (tester) async {
      await open(tester);
      await enter(tester, 'account-confirm-password', site.password);
      await tester.tap(find.byKey(const Key('account-link-google')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('account-waiting')), findsOneWidget);
      await tester.tap(find.byKey(const Key('account-waiting-cancel')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('account-waiting')), findsNothing);
      expect(find.byKey(const Key('account-link-google')), findsOneWidget);
    });

    testWidgets('the account is reached from the field screen', (tester) async {
      site = FakeSite();
      h = harness(
        siteHttp: site.http,
        links: FakeLinks(appLink),
        authBrowser: FakeAuthBrowser(),
        passkeys: FakePasskeys(),
      );
      await tester.pumpWidget(h.app());
      await tester.pumpAndSettle();
      await tapKey(tester, 'site-confirm');
      await tester.enterText(find.byKey(const Key('site-user')), site.username);
      await tester.enterText(
        find.byKey(const Key('site-password')),
        site.password,
      );
      await tapKey(tester, 'site-login');
      await tapKey(tester, 'site-account');
      expect(find.byType(SiteAccountScreen), findsOneWidget);
      expect(find.byKey(const Key('account-confirm-password')), findsOneWidget);
    });
  });

  test('a nonce is url-safe and long enough for the site to keep', () {
    final n = newNonce();
    expect(n, matches(RegExp(r'^[A-Za-z0-9_-]{24}$')));
    expect(newNonce(), isNot(n));
  });
}

/// A site whose answers name another host than the one it was asked at.
class _Rewriting implements SiteHttp {
  _Rewriting(this.inner, this.host);
  final SiteHttp inner;
  final String host;

  @override
  Future<SiteResponse> send(
    String method,
    String path, {
    Object? body,
    String? bearer,
    String? refreshToken,
  }) async {
    final r = await inner.send(
      method,
      path,
      body: body,
      bearer: bearer,
      refreshToken: refreshToken,
    );
    if (r.json['browser_url'] is String) {
      final u = Uri.parse('${r.json['browser_url']}');
      return SiteResponse(r.status, {
        ...r.json,
        'browser_url': u.replace(host: Uri.parse(host).host).toString(),
      });
    }
    return r;
  }
}
