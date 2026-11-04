// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The player's chrono records and the consent, per field, to share them
// (lib/site/chrono_screens.dart, the SiteApi calls; decisions S14-5, LEG-20,
// APPS-1 to APPS-8) against the fake site server (test/support/
// fake_site.dart): the fields from GET /me/chrono and the page's own field,
// every switch off until the person turns it on and confirms, a cancelled
// confirmation changing nothing, withdrawing after a confirmation, one
// field's records newest first, the site out of reach, a consent for a field
// with no records, the hub screen's way in, and the calls' refusals.

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/site/site_api.dart';
import 'package:atalaia_app/site/site_client.dart';
import 'package:atalaia_app/site/site_link.dart';
import 'package:atalaia_app/site/site_screens.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_site.dart';
import 'site_screens_test.dart' show back, reveal, tapKey;

final _link = SiteGameLink(
  Uri.parse('https://campo.example.pt'),
  'campo-norte',
);
const north = '0192f3a0-0000-7000-8000-00000000f1e1';
const south = '0192f3a0-0000-7000-8000-00000000f2e2';

/// The field's page, logged in, then the chrono screen.
Future<Harness> openChrono(
  WidgetTester tester,
  FakeSite site, {
  AppLanguage language = AppLanguage.en,
}) async {
  final h = harness(language: language, siteHttp: site.http);
  await h.services.sites.of(_link.site).login(site.username, site.password);
  await tester.pumpWidget(h.app(home: SiteScreen(link: _link)));
  await tester.pumpAndSettle();
  await tapKey(tester, 'site-my-chrono');
  return h;
}

Future<bool> switchOn(WidgetTester tester, String field) async => tester
    .widget<SwitchListTile>(
      await reveal(tester, find.byKey(Key('mychrono-consent-$field'))),
    )
    .value;

Future<void> inDialog(WidgetTester tester, String text) async {
  await tester.tap(
    find.descendant(of: find.byType(AlertDialog), matching: find.text(text)),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('every switch is off; consent needs a confirmation, and is '
      'withdrawn after one', (tester) async {
    final site = FakeSite();
    await openChrono(tester, site);
    expect(site.requests, containsAll(['GET /me/chrono', 'GET /me/data']));
    expect(await reveal(tester, find.text('Campo Norte')), findsOneWidget);
    expect(await reveal(tester, find.text('Campo Sul')), findsOneWidget);
    expect(await switchOn(tester, north), isFalse);
    expect(await switchOn(tester, south), isFalse);
    expect(
      find.textContaining('Player id p-sitemade2345 · 2 readings · 1 replica'),
      findsOneWidget,
    );

    // Turning the switch on asks first; cancelling records nothing.
    await tapKey(tester, 'mychrono-consent-$north');
    expect(find.text('Consent at Campo Norte?'), findsOneWidget);
    expect(find.textContaining('I can withdraw this consent'), findsOneWidget);
    await inDialog(tester, 'Cancel');
    expect(site.requests.where((r) => r.startsWith('PUT')), isEmpty);
    expect(await switchOn(tester, north), isFalse);

    await tapKey(tester, 'mychrono-consent-$north');
    await inDialog(tester, 'I consent');
    expect(site.requests, contains('PUT /me/consents/chrono-sharing/$north'));
    expect(site.liveConsents, {north});
    expect(await switchOn(tester, north), isTrue);
    expect(
      await switchOn(tester, south),
      isFalse,
      reason: 'one field at a time',
    );
    expect(find.byKey(const Key('mychrono-ok')), findsOneWidget);
    expect(find.text('Consent recorded.'), findsOneWidget);

    // Withdrawing asks too.
    await tapKey(tester, 'mychrono-consent-$north');
    expect(find.text('Withdraw your consent at Campo Norte?'), findsOneWidget);
    await inDialog(tester, 'Withdraw');
    expect(
      site.requests,
      contains('DELETE /me/consents/chrono-sharing/$north'),
    );
    expect(site.liveConsents, isEmpty);
    expect(await switchOn(tester, north), isFalse);
    expect(find.text('Consent withdrawn.'), findsOneWidget);
    // The withdrawn record stays on the server, with its time.
    expect(site.consentRecords.single['withdrawn_at'], isNotNull);
  });

  testWidgets('a consent already given shows on; one field\'s records, newest '
      'first', (tester) async {
    final site = FakeSite();
    site.consentRecords.add({
      'purpose': 'chrono_sharing',
      'field_id': south,
      'withdrawn_at': null,
    });
    await openChrono(tester, site);
    expect(await switchOn(tester, south), isTrue);
    expect(await switchOn(tester, north), isFalse);

    await tester.tap(await reveal(tester, find.text('Campo Norte')));
    await tester.pumpAndSettle();
    expect(find.text('Player id p-sitemade2345'), findsOneWidget);
    expect(
      find.text('AEG · Rifle · Tokyo Marui M4'),
      findsOneWidget,
      reason: 'the replica',
    );
    final newer = find.byKey(const Key('mychrono-reading-r-2'));
    final older = find.byKey(const Key('mychrono-reading-r-1'));
    expect(tester.getTopLeft(newer).dy, lessThan(tester.getTopLeft(older).dy));
    expect(
      find.descendant(of: newer, matching: find.text('Failed')),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: older,
        matching: find.text('1.21 J · 98.5 m/s · 0.25 g BB'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(of: older, matching: find.textContaining('Check-in')),
      findsOneWidget,
    );
    expect(
      await reveal(tester, find.text('Over the limit: 1.51 J (limit 1.49 J)')),
      findsOneWidget,
    );
    expect(find.textContaining('Warning'), findsOneWidget);
    expect(
      await reveal(tester, find.byKey(const Key('mychrono-refused'))),
      findsOneWidget,
    );
    expect(find.textContaining('refused 2 readings'), findsOneWidget);
    await back(tester);

    await tester.tap(await reveal(tester, find.text('Campo Sul')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('mychrono-no-readings')), findsOneWidget);
    expect(find.byKey(const Key('mychrono-no-violations')), findsOneWidget);
  });

  testWidgets('the page\'s field with no records, and a consent for a field '
      'not listed, in Portuguese', (tester) async {
    final site = FakeSite()..chronoFields.clear();
    site.consentRecords.add({
      'purpose': 'chrono_sharing',
      'field_id': '0192f3a0-0000-7000-8000-00000000f3e3',
      'withdrawn_at': null,
    });
    await openChrono(tester, site, language: AppLanguage.pt);
    expect(find.text('As minhas cronografagens'), findsOneWidget);
    expect(await reveal(tester, find.text('Campo Norte')), findsOneWidget);
    expect(
      find.textContaining('nenhum ID de participante ligado'),
      findsOneWidget,
    );
    expect(await reveal(tester, find.text('Outro campo')), findsOneWidget);
    // Consent before a first chrono check at the field.
    await tapKey(tester, 'mychrono-consent-$north');
    await inDialog(tester, 'Consinto');
    expect(site.liveConsents, contains(north));
    expect(await switchOn(tester, north), isTrue);
  });

  testWidgets('the site out of reach: said so, and nothing changes', (
    tester,
  ) async {
    final site = FakeSite();
    await openChrono(tester, site);
    site.offline = true;
    await tapKey(tester, 'mychrono-consent-$north');
    await inDialog(tester, 'I consent');
    expect(find.byKey(const Key('mychrono-error')), findsOneWidget);
    expect(await switchOn(tester, north), isFalse);
    expect(site.liveConsents, isEmpty);

    await tester.tap(find.byKey(const Key('mychrono-reload')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('mychrono-error')), findsOneWidget);
    expect(find.byKey(Key('mychrono-field-$north')), findsNothing);

    site.offline = false;
    await tester.tap(find.byKey(const Key('mychrono-reload')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('mychrono-error')), findsNothing);
    expect(find.byKey(Key('mychrono-field-$north')), findsOneWidget);
  });

  testWidgets('a hosted hub\'s screen opens the consent switch', (
    tester,
  ) async {
    final site = FakeSite()..hosted = true;
    final h = harness(language: AppLanguage.en, siteHttp: site.http);
    await h.services.sites.of(_link.site).login(site.username, site.password);
    await tester.pumpWidget(h.app(home: SiteScreen(link: _link)));
    await tester.pumpAndSettle();
    await tapKey(tester, 'site-hub-share');
    await tapKey(tester, 'hub-consent');
    expect(find.text('My chrono checks'), findsOneWidget);
    expect(find.byKey(Key('mychrono-consent-$north')), findsOneWidget);
  });

  test('the calls: a withdrawn consent counts as done, an unknown field is '
      'refused', () async {
    final site = FakeSite();
    final origin = Uri.parse('https://campo.example.pt');
    final session = SiteSession(
      origin,
      site.http(origin),
      SiteAccounts(MemoryAppStore()),
    );
    await session.login(site.username, site.password);
    final api = SiteApi(session);
    final fields = await api.myChrono();
    expect(fields.map((f) => f.field), ['Campo Norte', 'Campo Sul']);
    expect(fields.first.readings.first.energyJ, 1.21);
    expect(fields.first.violations.single.limitJ, 1.49);
    expect(await api.chronoSharingConsents(), isEmpty);

    await api.giveChronoSharing(north);
    await api.giveChronoSharing(north); // again: one consent
    expect(site.consentRecords, hasLength(1));
    expect(await api.chronoSharingConsents(), {north});
    await api.withdrawChronoSharing(north);
    await api.withdrawChronoSharing(north); // 404 consent_not_found: done
    expect(await api.chronoSharingConsents(), isEmpty);
    await expectLater(
      api.giveChronoSharing('0192f3a0-0000-7000-8000-0000000000ff'),
      throwsA(
        isA<SiteException>().having((e) => e.code, 'code', 'field_not_found'),
      ),
    );
  });
}
