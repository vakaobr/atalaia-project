// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The site server's privacy notice and "consent again" in the app, the notice
// version a social sign-up carries, and the chrono link between a hosted
// hub's fields (lib/site/privacy_notice.dart, privacy_screens.dart,
// hub_share.dart; the server's CONS-* and SVX-2 decisions), against the fake
// site server.

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/site/hub_share.dart';
import 'package:atalaia_app/site/privacy_notice.dart';
import 'package:atalaia_app/site/privacy_screens.dart';
import 'package:atalaia_app/site/site_client.dart';
import 'package:atalaia_app/site/site_link.dart';
import 'package:atalaia_app/site/site_screens.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_site.dart';
import '../support/fakes.dart';
import 'site_screens_test.dart' show FakeLinks, back, reveal, tapKey;

/// The register page's link to the field, no game: the field's own screen.
const appLink =
    'atalaia://register?site=https%3A%2F%2Fcampo.example.pt&field=campo-norte';

final _link = SiteGameLink(
  Uri.parse('https://campo.example.pt'),
  'campo-norte',
);

/// The field's screen with the account already signed in.
Future<Harness> signedIn(
  WidgetTester tester,
  FakeSite site, {
  AppLanguage language = AppLanguage.pt,
}) async {
  final h = harness(language: language, siteHttp: site.http);
  await h.services.sites.of(_link.site).login(site.username, site.password);
  await tester.pumpWidget(h.app(home: SiteScreen(link: _link)));
  await tester.pumpAndSettle();
  return h;
}

void main() {
  group('the notice and the consent calls', () {
    late FakeSite site;
    late PrivacyApi api;
    setUp(() {
      site = FakeSite();
      final origin = Uri.parse('https://campo.example.pt');
      final session = SiteSession(
        origin,
        site.http(origin),
        SiteAccounts(MemoryAppStore()),
      );
      api = PrivacyApi(session);
    });

    test(
      'the notice comes in the language asked for, or says it fell back',
      () async {
        final en = (await api.notice('en'))!;
        expect((en.version, en.lang, en.fallback), ('2026-11', 'en', false));
        expect(en.markdown, startsWith('# Privacy notice'));
        final zh = (await api.notice('zh-tw'))!;
        expect((zh.lang, zh.requestedLang, zh.fallback), ('pt', 'zh-tw', true));
        expect(zh.available, ['pt', 'en', 'de']);
        expect(site.noticeLangsAsked, ['en', 'zh-tw']);
      },
    );

    test('none published: null, not an error', () async {
      site.noticeTexts = {};
      expect(await api.notice('pt'), isNull);
    });

    test(
      'the consent states, and consenting again names the version',
      () async {
        await api.session.login(site.username, site.password);
        site
          ..consentStatus = 'outdated'
          ..consentVersion = '2026-05';
        final c = (await api.consent())!;
        expect(
          (c.status, c.version, c.currentVersion),
          ('outdated', '2026-05', '2026-11'),
        );
        expect((c.needed, c.noticePublished), (true, true));
        site.consentStatus = 'missing';
        expect((await api.consent())!.version, isNull);
        final done = await api.renew('2026-11');
        expect(done.isCurrent, isTrue);
        expect(site.bodies['POST /me/consents/account'], {
          'notice_version': '2026-11',
        });
        // A notice that changed since: refused, nothing recorded.
        site.consentStatus = 'outdated';
        await expectLater(
          api.renew('2026-05'),
          throwsA(
            isA<SiteException>().having(
              (e) => e.code,
              'code',
              'notice_version_changed',
            ),
          ),
        );
        expect(site.consentStatus, 'outdated');
        // An older server's /me says nothing about consent.
        site.consentStatus = null;
        expect(await api.consent(), isNull);
      },
    );
  });

  group('the Markdown the notice uses', () {
    test('inline marks go, a link keeps its address', () {
      expect(
        MarkdownText.plain('A **bold** and _soft_ `code`'),
        'A bold and soft code',
      );
      expect(
        MarkdownText.plain('write to [the DPO](mailto:dpo@campo.example.pt)'),
        'write to the DPO (mailto:dpo@campo.example.pt)',
      );
      expect(
        MarkdownText.plain('snake_case_name stays'),
        'snake_case_name stays',
      );
    });

    testWidgets('headings, lists, tables and rules are widgets, HTML is text', (
      tester,
    ) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: MarkdownText(
                '# Title\n\nFirst **line**\ncontinues.\n\n- one\n- two\n\n'
                '| a | b |\n|---|---|\n| 1 | 2 |\n\n---\n\n<script>x</script>',
              ),
            ),
          ),
        ),
      );
      expect(find.text('Title'), findsOneWidget);
      expect(find.text('First line continues.'), findsOneWidget);
      expect(find.text('•  one'), findsOneWidget);
      expect(find.text('a  ·  b'), findsOneWidget);
      expect(find.text('1  ·  2'), findsOneWidget);
      expect(find.byType(Divider), findsOneWidget);
      expect(find.text('<script>x</script>'), findsOneWidget);
    });
  });

  group('consent again on the signed-in field', () {
    testWidgets('a current consent asks nothing; the notice is one tap away', (
      tester,
    ) async {
      final site = FakeSite();
      await signedIn(tester, site);
      expect(find.byKey(const Key('consent-banner')), findsNothing);
      await tapKey(tester, 'site-privacy');
      expect(find.byKey(const Key('privacy-version')), findsOneWidget);
      expect(find.text('Versão 2026-11'), findsOneWidget);
      expect(find.byKey(const Key('privacy-text')), findsOneWidget);
      // only reading: no tick, no button
      expect(find.byKey(const Key('privacy-agree')), findsNothing);
      expect(site.noticeLangsAsked, ['pt']);
    });

    testWidgets('an outdated consent: banner, the notice, the tick, the '
        'version recorded', (tester) async {
      final site = FakeSite()
        ..consentStatus = 'outdated'
        ..consentVersion = '2026-05';
      await signedIn(tester, site);
      expect(find.byKey(const Key('consent-banner')), findsOneWidget);
      expect(
        find.textContaining('versão 2026-05, agora 2026-11'),
        findsOneWidget,
      );
      await tapKey(tester, 'consent-open');
      expect(find.textContaining('Tratamos o teu nome'), findsOneWidget);
      // Without the tick nothing is sent.
      await tapKey(tester, 'privacy-agree');
      expect(find.byKey(const Key('privacy-error')), findsOneWidget);
      expect(site.requests, isNot(contains('POST /me/consents/account')));
      await tapKey(tester, 'privacy-tick');
      await tapKey(tester, 'privacy-agree');
      expect(site.bodies['POST /me/consents/account'], {
        'notice_version': '2026-11',
      });
      expect(find.text('Consentimento registado.'), findsOneWidget);
      expect(find.byKey(const Key('privacy-agree')), findsNothing);
      // Back on the field the prompt has gone.
      await back(tester);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('consent-banner')), findsNothing);
    });

    testWidgets('no consent at all asks too, in the account\'s own words', (
      tester,
    ) async {
      final site = FakeSite()..consentStatus = 'missing';
      await signedIn(tester, site, language: AppLanguage.en);
      expect(
        find.textContaining('no consent recorded for the privacy notice'),
        findsOneWidget,
      );
    });

    testWidgets('a notice that changes while it is read is read again, never '
        'agreed to unseen', (tester) async {
      final site = FakeSite()..consentStatus = 'outdated';
      await signedIn(tester, site);
      await tapKey(tester, 'consent-open');
      site.changeNoticeOnConsent = '2026-12';
      await tapKey(tester, 'privacy-tick');
      await tapKey(tester, 'privacy-agree');
      expect(find.byKey(const Key('privacy-error')), findsOneWidget);
      expect(find.textContaining('O aviso mudou entretanto'), findsOneWidget);
      expect(find.text('Versão 2026-12'), findsOneWidget);
      expect(site.consentStatus, 'outdated');
      // The tick is cleared: the new text is agreed to on purpose.
      await tapKey(tester, 'privacy-agree');
      expect(find.byKey(const Key('privacy-error')), findsOneWidget);
      await tapKey(tester, 'privacy-tick');
      await tapKey(tester, 'privacy-agree');
      expect(site.bodies['POST /me/consents/account'], {
        'notice_version': '2026-12',
      });
      expect(site.consentStatus, 'current');
    });

    testWidgets('the text comes in the app\'s language, and says when the '
        'server fell back', (tester) async {
      final site = FakeSite()..consentStatus = 'outdated';
      await signedIn(tester, site, language: AppLanguage.zhTw);
      await tapKey(tester, 'consent-open');
      expect(site.noticeLangsAsked, ['zh-tw']);
      expect(find.byKey(const Key('privacy-fallback')), findsOneWidget);
      expect(find.textContaining('Português'), findsOneWidget);
      expect(find.byKey(const Key('privacy-text')), findsOneWidget);
    });

    testWidgets('a server with no notice published says so; asking is '
        'not blocked', (tester) async {
      final site = FakeSite()
        ..consentStatus = 'outdated'
        ..noticeTexts = {};
      await signedIn(tester, site);
      await tapKey(tester, 'consent-open');
      expect(find.byKey(const Key('privacy-none')), findsOneWidget);
      expect(find.byKey(const Key('privacy-agree')), findsNothing);
    });

    testWidgets('an older server without consent in /me shows no prompt', (
      tester,
    ) async {
      final site = FakeSite()..consentStatus = null;
      await signedIn(tester, site);
      expect(find.byKey(const Key('consent-banner')), findsNothing);
      expect(find.byKey(const Key('site-privacy')), findsOneWidget);
    });
  });

  group('the notice version of a social sign-up', () {
    late FakeSite site;
    late FakeLinks links;
    late FakeAuthBrowser browser;

    Future<void> open(WidgetTester tester, {bool published = true}) async {
      site = FakeSite();
      if (!published) site.noticeTexts = {};
      browser = FakeAuthBrowser();
      links = FakeLinks(appLink);
      final h = harness(
        siteHttp: site.http,
        links: links,
        authBrowser: browser,
        passkeys: FakePasskeys(),
      );
      browser.onOpen = (_) {
        final s = Uri.parse(site.lastReturnTo!).queryParameters['s']!;
        links.send('https://campo.example.pt/app/oidc?s=$s#oidc=good-ticket');
      };
      await tester.pumpWidget(h.app());
      await tester.pumpAndSettle();
      await tapKey(tester, 'site-confirm');
    }

    testWidgets('the consent goes with the version the person was offered', (
      tester,
    ) async {
      await open(tester);
      await tapKey(tester, 'site-login-consent');
      await tapKey(tester, 'site-login-google');
      expect(site.lastStartConsent, isTrue);
      expect(site.lastNoticeVersion, '2026-11');
      expect(
        site.bodies['POST /auth/oidc/google/start'],
        containsPair('notice_version', '2026-11'),
      );
      expect(find.text('Jogos'), findsOneWidget);
    });

    testWidgets('without the consent box no version is sent', (tester) async {
      await open(tester);
      await tapKey(tester, 'site-login-google');
      expect(
        site.bodies['POST /auth/oidc/google/start'],
        isNot(contains('notice_version')),
      );
    });

    testWidgets('reading the notice first: the version on the screen is the '
        'one sent', (tester) async {
      await open(tester);
      site.noticeVersion = '2026-12'; // published after the login was shown
      await tapKey(tester, 'site-login-privacy');
      expect(find.text('Versão 2026-12'), findsOneWidget);
      await back(tester);
      await tester.pumpAndSettle();
      await tapKey(tester, 'site-login-consent');
      await tapKey(tester, 'site-login-google');
      expect(site.lastNoticeVersion, '2026-12');
    });

    testWidgets('a notice that changed since it was shown: refused in words, '
        'the login stays', (tester) async {
      await open(tester);
      site.noticeVersion = '2026-12';
      await tapKey(tester, 'site-login-consent');
      await tapKey(tester, 'site-login-google');
      expect(find.byKey(const Key('site-error')), findsOneWidget);
      expect(
        find.textContaining('O aviso de privacidade mudou'),
        findsOneWidget,
      );
      expect(browser.opened, isEmpty);
    });

    testWidgets('a server that does not take the field yet: asked again '
        'without it, the sign-in goes on', (tester) async {
      await open(tester);
      site.startTakesNoticeVersion = false;
      await tapKey(tester, 'site-login-consent');
      await tapKey(tester, 'site-login-google');
      expect(
        site.requests.where((r) => r == 'POST /auth/oidc/google/start'),
        hasLength(2),
      );
      expect(site.lastNoticeVersion, isNull);
      expect(site.lastStartConsent, isTrue);
      expect(find.text('Jogos'), findsOneWidget);
    });

    testWidgets('a 422 for another reason: not asked again, shown as the '
        'refusal it is', (tester) async {
      await open(tester);
      site.startValidationError = true;
      await tapKey(tester, 'site-login-consent');
      await tapKey(tester, 'site-login-google');
      expect(
        site.requests.where((r) => r == 'POST /auth/oidc/google/start'),
        hasLength(1),
      );
      expect(find.byKey(const Key('site-error')), findsOneWidget);
      expect(browser.opened, isEmpty);
    });

    testWidgets('a server that takes the field: one request, the version '
        'sent', (tester) async {
      await open(tester);
      await tapKey(tester, 'site-login-consent');
      await tapKey(tester, 'site-login-google');
      expect(
        site.requests.where((r) => r == 'POST /auth/oidc/google/start'),
        hasLength(1),
      );
      expect(site.lastNoticeVersion, site.noticeVersion);
    });

    testWidgets('no notice published: no version, the sign-in is as before', (
      tester,
    ) async {
      await open(tester, published: false);
      await tapKey(tester, 'site-login-consent');
      await tapKey(tester, 'site-login-google');
      expect(site.lastStartConsent, isTrue);
      expect(site.lastNoticeVersion, isNull);
      expect(find.text('Jogos'), findsOneWidget);
    });
  });

  group('the chrono link between fields', () {
    testWidgets('a single-field server: no screen, no button', (tester) async {
      final site = FakeSite(); // hosted = false: 404 not_hosted
      await signedIn(tester, site);
      expect(site.requests, contains('GET /me/hub-share'));
      expect(find.byKey(const Key('site-hub-share')), findsNothing);
    });

    testWidgets('hosted: the state, a code made once, a code entered, '
        'unlinking', (tester) async {
      final site = FakeSite()..hosted = true;
      await signedIn(tester, site);
      await tapKey(tester, 'site-hub-share');
      expect(
        find.text(
          'Esta conta ainda não está ligada às tuas contas de outros campos.',
        ),
        findsOneWidget,
      );
      expect(find.byKey(const Key('hub-unlink')), findsNothing);

      // A wrong code is refused in words.
      await tester.enterText(find.byKey(const Key('hub-enter')), 'NOPE-0000');
      await tapKey(tester, 'hub-link');
      expect(find.byKey(const Key('hub-error')), findsOneWidget);
      expect(find.textContaining('já expirou'), findsOneWidget);
      expect(site.bodies['POST /me/hub-share/link'], {'code': 'NOPE-0000'});

      // The other field's code links the accounts.
      await tester.enterText(
        find.byKey(const Key('hub-enter')),
        site.otherFieldCode,
      );
      await tapKey(tester, 'hub-link');
      expect(find.byKey(const Key('hub-ok')), findsOneWidget);
      expect(
        await reveal(tester, find.textContaining('Conta ligada desde')),
        findsOneWidget,
      );
      expect(
        await reveal(tester, find.byKey(const Key('hub-unlink'))),
        findsOneWidget,
      );
      expect(
        await reveal(tester, find.textContaining('Ainda não está a partilhar')),
        findsOneWidget,
      );

      // A code is shown with its note.
      await tapKey(tester, 'hub-make');
      expect(await reveal(tester, find.text('WXYZ-2345-QRST')), findsOneWidget);
      expect(
        await reveal(tester, find.textContaining('Vale 15 minutos')),
        findsOneWidget,
      );
      expect(site.codesMade, 1);

      // Unlinking asks first.
      await tapKey(tester, 'hub-unlink');
      expect(find.text('Desligar as contas?'), findsOneWidget);
      await tester.tap(find.text('Cancelar'));
      await tester.pumpAndSettle();
      expect(site.hubLinked, isTrue);
      await tapKey(tester, 'hub-unlink');
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text('Desligar'),
        ),
      );
      await tester.pumpAndSettle();
      expect(site.hubLinked, isFalse);
      expect(find.text('Contas desligadas.'), findsOneWidget);
    });

    testWidgets('sharing on is said so; a link to someone already linked is '
        'refused in words', (tester) async {
      final site = FakeSite()
        ..hosted = true
        ..hubLinked = true
        ..hubSharing = true;
      final h = await signedIn(tester, site, language: AppLanguage.en);
      await tapKey(tester, 'site-hub-share');
      expect(
        find.text('Sharing: the other fields see your chrono checks.'),
        findsOneWidget,
      );
      await tester.enterText(
        find.byKey(const Key('hub-enter')),
        site.otherFieldCode,
      );
      await tapKey(tester, 'hub-link');
      expect(
        find.textContaining('already linked to another person'),
        findsOneWidget,
      );
      expect(h.services, isNotNull);
    });

    test('a refused call carries the server code', () async {
      final site = FakeSite()..hosted = true;
      final origin = Uri.parse('https://campo.example.pt');
      final session = SiteSession(
        origin,
        site.http(origin),
        SiteAccounts(MemoryAppStore()),
      );
      await session.login(site.username, site.password);
      final api = HubShareApi(session);
      expect((await api.state())!.linked, isFalse);
      await expectLater(
        api.unlink(),
        throwsA(
          isA<SiteException>().having((e) => e.code, 'code', 'not_linked'),
        ),
      );
      final code = await api.makeCode();
      expect((code.code, code.expiresIn), ('WXYZ-2345-QRST', 900));
      site.hosted = false;
      expect(await api.state(), isNull);
    });
  });
}
