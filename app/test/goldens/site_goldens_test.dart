// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Online registration's screens (lib/site/, decision S16-13) in European
// Portuguese and English on a 360x780 phone: the login at a site, the
// field's games, the registration form with replicas, the kept ticket.

import 'package:atalaia_app/checkin/my_replicas.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/site/site_api.dart';
import 'package:atalaia_app/site/site_link.dart';
import 'package:atalaia_app/site/site_screens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_site.dart';

Future<void> phone(WidgetTester tester) async {
  tester.view.physicalSize = const Size(360, 780);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> snap(WidgetTester tester, String name, AppLanguage lang) =>
    expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('images/site/${name}_${lang.code}.png'),
    );

final link = SiteGameLink(Uri.parse('https://campo.example.pt'), 'campo-norte');

void main() {
  for (final lang in AppLanguage.values) {
    Future<Harness> start(
      WidgetTester tester,
      FakeSite site, {
      bool loggedIn = true,
    }) async {
      await phone(tester);
      final h = harness(language: lang, siteHttp: site.http);
      if (loggedIn) {
        await h.services.sites
            .of(link.site)
            .login(site.username, site.password);
      } else {
        await h.services.sites.accounts.confirm('${link.site}');
      }
      await h.store.saveList('my_replicas', [
        MyReplica(
          id: 'm1',
          type: 'aeg',
          replicaClass: 'rifle',
          makeModel: 'Tokyo Marui M4',
        ).toJson(),
        MyReplica(id: 'm2', type: 'sniper', replicaClass: 'sniper').toJson(),
      ]);
      return h;
    }

    testWidgets('login (${lang.code})', (tester) async {
      final site = FakeSite();
      final h = await start(tester, site, loggedIn: false);
      await tester.pumpWidget(h.app(home: SiteScreen(link: link)));
      await tester.pumpAndSettle();
      await snap(tester, 'login', lang);
    });

    testWidgets('the field\'s games (${lang.code})', (tester) async {
      final site = FakeSite();
      final h = await start(tester, site);
      await tester.pumpWidget(h.app(home: SiteScreen(link: link)));
      await tester.pumpAndSettle();
      await snap(tester, 'games', lang);
    });

    testWidgets('registering (${lang.code})', (tester) async {
      final site = FakeSite();
      final h = await start(tester, site);
      await tester.pumpWidget(h.app(home: SiteScreen(link: link)));
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(const Key('site-game-0192f3a0-0000-7000-8000-000000000001')),
      );
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('reg-federation')), '12345');
      await tester.tap(find.byKey(const Key('reg-replica-m1')));
      await tester.pumpAndSettle();
      await snap(tester, 'register', lang);
    });

    testWidgets('the ticket (${lang.code})', (tester) async {
      await phone(tester);
      final h = harness(language: lang);
      await tester.pumpWidget(
        h.app(
          home: TicketScreen(
            ticket: KeptTicket(
              site: 'https://campo.example.pt',
              registrationId: '0192f3a0-0000-7000-8000-0000000a0001',
              playerId: 'p-abcdefghijkl',
              ticket: 'x' * 43,
              ticketText:
                  'atalaia:ticket:oWJyaVAZJvOgAAB3AIAAAAAACgABYnBpbnAtYWJjZGVmZ2hpamts',
              gameTitle: 'Domingo de manhã',
              fieldName: 'Campo Norte',
              startsAt: DateTime.utc(2026, 11, 8, 9),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await snap(tester, 'ticket', lang);
    });
  }
}
