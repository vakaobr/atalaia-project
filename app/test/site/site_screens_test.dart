// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Online registration in the app (lib/site/), against a fake site server
// (test/support/fake_site.dart), in both languages: the register page's
// link opening the app, the site confirmed once, the login with its TOTP
// step, the field's games, registering with replicas, the ticket kept and
// shown, changing and cancelling, claiming the phone's player id, and the
// kept ticket sent with a check-in at the field (decision S16-8).

import 'dart:async';

import 'package:atalaia_app/checkin/field_identity.dart';
import 'package:atalaia_app/checkin/my_replicas.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/platform/links.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/site/site_api.dart';
import 'package:atalaia_app/site/site_screens.dart';
import 'package:atalaia_app/l10n/strings_en.dart';
import 'package:atalaia_app/l10n/strings_pt.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_field.dart';
import '../support/fake_site.dart';
import '../support/fakes.dart';

const game1 = '0192f3a0-0000-7000-8000-000000000001';
const appLink =
    'atalaia://register?site=https%3A%2F%2Fcampo.example.pt&field=campo-norte&game=$game1';

class FakeLinks implements AppLinks {
  FakeLinks([this.first]);
  final String? first;
  final _c = StreamController<String>.broadcast();

  void send(String link) => _c.add(link);

  @override
  Future<String?> initial() async => first;

  @override
  Stream<String> get links => _c.stream;
}

Future<void> tapKey(WidgetTester tester, String key) async {
  final f = await reveal(tester, find.byKey(Key(key)));
  await tester.ensureVisible(f);
  await tester.pumpAndSettle();
  // ensureVisible can leave a button in the list's cache extent, below the
  // screen, when a form is long: scroll on until it is on the screen.
  final screen = tester.view.physicalSize / tester.view.devicePixelRatio;
  for (var i = 0; i < 10 && tester.getCenter(f).dy > screen.height - 8; i++) {
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -150));
    await tester.pumpAndSettle();
  }
  await tester.tap(f);
  await tester.pumpAndSettle();
}

/// Scrolls the screen's list until [f] is built (up or down).
Future<Finder> reveal(WidgetTester tester, Finder f) async {
  for (final delta in [-300.0, 300.0]) {
    if (f.evaluate().isNotEmpty) break;
    try {
      await tester.scrollUntilVisible(
        f,
        delta,
        scrollable: find.byType(Scrollable).first,
        maxScrolls: 20,
      );
    } on StateError {
      // not that way
    }
  }
  return f;
}

Future<void> enter(WidgetTester tester, String key, String text) async {
  final f = await reveal(tester, find.byKey(Key(key)));
  await tester.ensureVisible(f);
  await tester.pumpAndSettle();
  await tester.enterText(f, text);
}

/// The app bar's back button (pageBack() looks for the English tooltip).
Future<void> back(WidgetTester tester) async {
  await tester.tap(find.byType(BackButton));
  await tester.pumpAndSettle();
}

Future<void> login(WidgetTester tester, FakeSite site) async {
  await tester.enterText(find.byKey(const Key('site-user')), site.username);
  await tester.enterText(find.byKey(const Key('site-password')), site.password);
  await tapKey(tester, 'site-login');
}

void main() {
  testWidgets('the register page\'s link: confirm, log in with TOTP, register '
      'with replicas, keep and show the ticket, change, cancel', (
    tester,
  ) async {
    final site = FakeSite(totp: true);
    final h = harness(siteHttp: site.http, links: FakeLinks(appLink));
    await h.store.saveList('my_replicas', [
      MyReplica(
        id: 'm1',
        type: 'aeg',
        replicaClass: 'rifle',
        makeModel: 'M4',
      ).toJson(),
      MyReplica(id: 'm2', type: 'hpa', replicaClass: 'support').toJson(),
    ]);
    await tester.pumpWidget(h.app());
    await tester.pumpAndSettle();

    // The link names a site: it is shown and confirmed before any login.
    expect(find.byKey(const Key('site-host')), findsOneWidget);
    expect(find.text('campo.example.pt'), findsOneWidget);
    expect(site.requests, isEmpty);
    await tapKey(tester, 'site-confirm');
    await login(tester, site);
    expect(find.textContaining('verificação em dois passos'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('site-code')), '000000');
    await tapKey(tester, 'site-send-code');
    expect(
      find.text('Código errado. Tenta o código seguinte.'),
      findsOneWidget,
    );
    await tester.enterText(find.byKey(const Key('site-code')), site.code);
    await tapKey(tester, 'site-send-code');

    // The link's game opens at once.
    expect(find.text('Domingo de manhã'), findsWidgets);
    expect(find.textContaining('Inscrições abertas até'), findsOneWidget);
    expect(find.text('Número de federado (FPA)'), findsOneWidget);
    // A replica of a class this field has not is shown, not selectable.
    await tester.scrollUntilVisible(
      find.text('support: este campo não tem esta classe'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tapKey(tester, 'reg-replica-m1');
    await enter(tester, 'reg-name', 'Falcão');
    await tapKey(tester, 'reg-submit');
    expect(
      find.text('Este campo pede o número de federado (FPA).'),
      findsOneWidget,
    );
    await enter(tester, 'reg-federation', 'FPA-123');
    await tapKey(tester, 'reg-submit');

    // The ticket: kept before it is shown.
    final kept = await h.services.tickets.all();
    expect(kept, hasLength(1));
    expect(find.byKey(const Key('ticket-qr')), findsOneWidget);
    expect(find.text(kept.single.ticketText), findsOneWidget);
    final sent =
        site.bodies['POST /fields/${site.fieldId}/scheduled-games/$game1/registrations']!
            as Map;
    expect(sent['display_name'], 'Falcão');
    expect(sent['federation_number'], 'FPA-123');
    expect(sent['replicas'], [
      {'type': 'aeg', 'class': 'rifle', 'make_model': 'M4'},
    ]);
    expect(h.settings.displayName, 'Falcão');
    await back(tester);

    // Registered: change it, a new ticket, cancel.
    expect(
      await reveal(tester, find.text('Tens inscrição neste jogo.')),
      findsOneWidget,
    );
    await enter(tester, 'reg-name', 'Falcão Azul');
    await tapKey(tester, 'reg-submit');
    expect(site.regs.values.single['display_name'], 'Falcão Azul');
    await tester.pump(const Duration(seconds: 5)); // the snack bar goes
    await tester.pumpAndSettle();
    await tapKey(tester, 'reg-new-ticket');
    final renewed = await h.services.tickets.all();
    expect(renewed.single.ticket, isNot(kept.single.ticket));
    await back(tester);
    await tapKey(tester, 'reg-cancel');
    expect(find.byType(AlertDialog), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Cancelar a inscrição'));
    await tester.pumpAndSettle();
    expect(site.regs.values.single['status'], 'cancelled');
    expect(await h.services.tickets.all(), isEmpty);
    // Back on the field's games.
    expect(find.byKey(const Key('site-game-$game1')), findsOneWidget);
    expect(find.textContaining('As inscrições abrem a'), findsOneWidget);

    // The next time the site is not asked about again, and the session holds.
    final refreshes = site.refreshes;
    await tester.pumpWidget(const SizedBox());
    final h2 = harness(siteHttp: site.http);
    await h2.store.saveList(
      'site_accounts',
      await h.store.loadList('site_accounts'),
    );
    await tester.pumpWidget(h2.app(home: const PlayerStartScreen()));
    await tester.pumpAndSettle();
    await tapKey(tester, 'player-site');
    await tester.enterText(
      find.byKey(const Key('site-address')),
      'https://campo.example.pt/f/campo-norte',
    );
    await tapKey(tester, 'site-open');
    expect(find.byKey(const Key('site-logged-in')), findsOneWidget);
    expect(site.refreshes, refreshes + 1);
    // Logging out.
    await tapKey(tester, 'site-logout');
    expect(find.byKey(const Key('site-user')), findsOneWidget);
  });

  testWidgets('in English: a wrong address, a wrong password, claiming the '
      'phone\'s id', (tester) async {
    final site = FakeSite();
    final h = harness(language: AppLanguage.en, siteHttp: site.http);
    final id = await FieldIdentities(h.store).forField('campo-norte');
    await tester.pumpWidget(h.app(home: const SiteScreen()));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('site-address')),
      'http://campo.example.pt/f/campo-norte',
    );
    await tapKey(tester, 'site-open');
    expect(
      find.text(
        'This is not the address of a field or game page (https://…/f/…).',
      ),
      findsOneWidget,
    );
    await tester.enterText(
      find.byKey(const Key('site-address')),
      'https://campo.example.pt/f/campo-norte',
    );
    await tapKey(tester, 'site-open');
    await tapKey(tester, 'site-confirm');
    await tester.enterText(find.byKey(const Key('site-user')), 'falcao');
    await tester.enterText(find.byKey(const Key('site-password')), 'nope');
    await tapKey(tester, 'site-login');
    expect(find.text('Wrong username or password.'), findsOneWidget);
    await login(tester, site);
    expect(find.text('Games'), findsOneWidget);
    expect(find.textContaining('Registration opens'), findsOneWidget);

    await tapKey(tester, 'site-claim');
    await tapKey(tester, 'claim-id-${id.playerId}');
    await tapKey(tester, 'claim-send');
    expect(
      find.text('Sent: waiting for the field\'s controller to confirm it.'),
      findsOneWidget,
    );
    final sent = site.bodies['POST /me/player-ids']! as Map;
    expect(sent, {
      'field_id': site.fieldId,
      'player_id': id.playerId,
      'player_secret': id.secret,
    });
  });

  testWidgets('with an APD rule: the picker, the number and the expiry '
      'replace the federation field; the server\'s refusals are told', (
    tester,
  ) async {
    final site = FakeSite()
      ..apdRule = {
        'accepted': ['x-own'],
        'register': true,
        'checkin': true,
        'expiry': true,
        'custom': [
          {
            'id': 'x-own',
            'name': 'Clube Próprio, APD',
            'short_name': 'Próprio',
            'website': null,
          },
        ],
      };
    final h = harness(language: AppLanguage.en, siteHttp: site.http);
    await tester.pumpWidget(h.app(home: const SiteScreen()));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('site-address')),
      'https://campo.example.pt/f/campo-norte',
    );
    await tapKey(tester, 'site-open');
    await tapKey(tester, 'site-confirm');
    await login(tester, site);
    await tapKey(tester, 'site-game-$game1');
    expect(find.byKey(const Key('reg-federation')), findsNothing);
    expect(find.text('APD membership'), findsOneWidget);
    expect(find.text('Accepted APDs: Próprio'), findsOneWidget);
    await enter(tester, 'reg-name', 'Falcão');
    await tapKey(tester, 'reg-submit');
    expect(
      find.text('This field asks for your APD membership number.'),
      findsOneWidget,
    );
    await enter(tester, 'reg-apd-number', 'N-1');
    await enter(tester, 'reg-apd-expires', '2027-13-01');
    await tapKey(tester, 'reg-submit');
    expect(
      find.text('Write the date as YYYY-MM-DD, for instance 2027-01-31.'),
      findsOneWidget,
    );
    await enter(tester, 'reg-apd-expires', '2027-06-30');
    // An APD the field does not accept: the server says so.
    await tapKey(tester, 'reg-submit');
    expect(find.text('This field does not accept that APD.'), findsOneWidget);
    await tapKey(tester, 'reg-apd-pick');
    await tester.tap(find.text('Clube Próprio, APD').last);
    await tester.pumpAndSettle();
    await tapKey(tester, 'reg-submit');
    final sent =
        site.bodies['POST /fields/${site.fieldId}/scheduled-games/$game1/registrations']!
            as Map;
    expect(sent['apd_id'], 'x-own');
    expect(sent['membership_number'], 'N-1');
    expect(sent['federation_number'], 'N-1');
    expect(sent['membership_expires'], '2027-06-30');
    expect(site.regs.values.single['apd_id'], 'x-own');
  });

  testWidgets('a kept ticket goes with the check-in, with its player id', (
    tester,
  ) async {
    final field = FakeField();
    final h = harness(
      qr: FakeQr(field.posterText()),
      fieldHttp: field.http,
      caFetch: field.fetchCa,
    );
    const ticket = KeptTicket(
      site: 'https://campo.example.pt',
      registrationId: '0192f3a0-0000-7000-8000-0000000a0001',
      playerId: 'p-sitemade2345',
      ticket: 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ',
      ticketText: 'atalaia:ticket:x',
      gameTitle: 'Domingo de manhã',
      fieldName: 'Campo Norte',
    );
    await h.services.tickets.keep(ticket);
    await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
    await tester.pumpAndSettle();
    await tapKey(tester, 'player-checkin');
    await tapKey(tester, 'checkin-scan');
    await tapKey(tester, 'checkin-notice-ok');
    await tester.enterText(find.byKey(const Key('checkin-name')), 'Falcão');
    await tapKey(tester, 'checkin-registration');
    await tester.tap(find.text('Domingo de manhã · Campo Norte').last);
    await tester.pumpAndSettle();
    await tapKey(tester, 'checkin-submit');
    expect(find.text('Check-in feito.'), findsOneWidget);
    final row = field.rows['p-sitemade2345']!;
    expect(row['registration_id'], ticket.registrationId);
    expect(row['registration_ticket'], ticket.ticket);
    // The phone now has that id at this field.
    expect(
      (await FieldIdentities(h.store).existing('campo-norte'))!.playerId,
      'p-sitemade2345',
    );
  });

  testWidgets('a phone with another id there is told to claim it first', (
    tester,
  ) async {
    final field = FakeField();
    final h = harness(
      qr: FakeQr(field.posterText()),
      fieldHttp: field.http,
      caFetch: field.fetchCa,
    );
    await FieldIdentities(h.store).forField('campo-norte');
    await h.services.tickets.keep(
      const KeptTicket(
        site: 'https://campo.example.pt',
        registrationId: '0192f3a0-0000-7000-8000-0000000a0001',
        playerId: 'p-sitemade2345',
        ticket: 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ',
        ticketText: 'atalaia:ticket:x',
        gameTitle: 'Domingo de manhã',
        fieldName: 'Campo Norte',
      ),
    );
    await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
    await tester.pumpAndSettle();
    await tapKey(tester, 'player-checkin');
    await tapKey(tester, 'checkin-scan');
    await tapKey(tester, 'checkin-notice-ok');
    await tester.enterText(find.byKey(const Key('checkin-name')), 'Falcão');
    await tapKey(tester, 'checkin-registration');
    await tester.tap(find.text('Domingo de manhã · Campo Norte').last);
    await tester.pumpAndSettle();
    await tapKey(tester, 'checkin-submit');
    expect(find.byKey(const Key('checkin-error')), findsOneWidget);
    expect(field.rows, isEmpty);
  });

  testWidgets('a link while the app runs opens the field', (tester) async {
    final site = FakeSite();
    final links = FakeLinks();
    final h = harness(siteHttp: site.http, links: links);
    await tester.pumpWidget(h.app());
    await tester.pumpAndSettle();
    links.send(
      'atalaia://register?site=https%3A%2F%2Fevil.example%3A1&field=x',
    );
    links.send('not a link');
    await tester.pumpAndSettle();
    expect(find.byType(SiteScreen), findsOneWidget); // https, any host: asks
    expect(find.text('evil.example:1'), findsOneWidget);
    await back(tester);
    links.send('atalaia://register?site=http%3A%2F%2Fevil.example&field=x');
    await tester.pumpAndSettle();
    expect(find.byType(SiteScreen), findsNothing);
  });

  test('the keys built at run time exist in both languages', () {
    for (final k in [
      for (final st in ['registered', 'checked_in', 'no_show', 'cancelled'])
        'site.reg.$st',
      for (final c in ['pending', 'confirmed', 'refused']) 'site.claim.$c',
      for (final c in [
        'membership_missing',
        'apd_not_accepted',
        'membership_expired',
      ])
        'site.err.$c',
      for (final st in ['valid', 'expired', 'not_accepted', 'missing'])
        'apd.status.$st',
    ]) {
      expect(ptStrings.containsKey(k), isTrue, reason: k);
      expect(enStrings.containsKey(k), isTrue, reason: k);
    }
  });
}
