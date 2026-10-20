// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The account session on a site server (lib/site/site_client.dart): the
// login and its TOTP step, the refresh token kept in the app's store and
// rotated one refresh at a time, a replayed or refused token, an access
// token the server no longer takes, logging out; and the tickets kept.

import 'package:atalaia_app/site/site_api.dart';
import 'package:atalaia_app/site/site_client.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_site.dart';

void main() {
  final origin = Uri.parse('https://campo.example.pt');
  late FakeSite site;
  late MemoryAppStore store;
  late SiteAccounts accounts;
  late DateTime now;

  SiteSession session() =>
      SiteSession(origin, site.http(origin), accounts, now: () => now);

  setUp(() {
    site = FakeSite();
    store = MemoryAppStore();
    accounts = SiteAccounts(store);
    now = DateTime.utc(2026, 11, 1, 10);
  });

  test(
    'a password login keeps the refresh token, never the password',
    () async {
      final s = session();
      final step = await s.login('falcao', 'correct horse battery');
      expect(step, isA<LoggedIn>());
      expect(await accounts.refreshToken('$origin'), 'rt-2');
      expect(await accounts.username('$origin'), 'falcao');
      expect(await accounts.confirmed('$origin'), isTrue);
      final saved = (await store.loadList('site_accounts')).single;
      expect(saved.keys.toSet(), {'site', 'username', 'refresh', 'confirmed'});
      expect(saved.values, isNot(contains('correct horse battery')));
      final games = await SiteApi(s).fieldGames('campo-norte');
      expect(games.field.classes, contains('dmr'));
      expect(games.games.first.registrationOpen, isTrue);
      expect(site.refreshes, 0); // the login's access token was used
    },
  );

  test('wrong password, then the TOTP step', () async {
    site.totp = true;
    final s = session();
    await expectLater(
      s.login('falcao', 'nope'),
      throwsA(
        isA<SiteException>().having(
          (e) => e.code,
          'code',
          'invalid_credentials',
        ),
      ),
    );
    final step = await s.login('falcao', 'correct horse battery');
    expect(step, isA<TotpNeeded>());
    expect(await accounts.refreshToken('$origin'), isNull); // no session yet
    await expectLater(
      s.loginTotp(step as TotpNeeded, '000000'),
      throwsA(
        isA<SiteException>().having((e) => e.code, 'code', 'invalid_code'),
      ),
    );
    await s.loginTotp(step, ' 123456 ');
    expect(await accounts.refreshToken('$origin'), isNotNull);
  });

  test(
    'a new app start refreshes with the stored token, rotating it',
    () async {
      await session().login('falcao', 'correct horse battery');
      final first = await accounts.refreshToken('$origin');
      final later = session(); // the app again: no access token in memory
      await SiteApi(later).mine();
      expect(site.refreshes, 1);
      final second = await accounts.refreshToken('$origin');
      expect(second, isNot(first));
      // An expired access token is refreshed before the request.
      now = now.add(const Duration(hours: 1));
      await SiteApi(later).mine();
      expect(site.refreshes, 2);
      expect(await accounts.refreshToken('$origin'), isNot(second));
    },
  );

  test('refreshes at the same time share one request', () async {
    await session().login('falcao', 'correct horse battery');
    final s = session();
    await Future.wait([
      SiteApi(s).mine(),
      SiteApi(s).fieldGames('campo-norte'),
      SiteApi(s).playerIds(),
    ]);
    expect(site.refreshes, 1);
    expect(site.sessionEnded, isFalse);
  });

  test('an access token the server refuses is refreshed once', () async {
    final s = session();
    await s.login('falcao', 'correct horse battery');
    site.expireAccess();
    await SiteApi(s).mine();
    expect(site.refreshes, 1);
    expect(
      site.requests.where((r) => r == 'GET /me/registrations'),
      hasLength(2),
    );
  });

  test(
    'a spent token that comes back ends the session: log in again',
    () async {
      final s = session();
      await s.login('falcao', 'correct horse battery');
      final copy = (await accounts.refreshToken('$origin'))!;
      await s.refresh(); // spends `copy`
      // Someone kept the old token (a restored copy of the app's files).
      await accounts.setRefresh('$origin', copy);
      final other = session();
      await expectLater(
        SiteApi(other).mine(),
        throwsA(
          isA<SiteException>().having((e) => e.loginRequired, 'login', isTrue),
        ),
      );
      expect(site.sessionEnded, isTrue);
      expect(await accounts.refreshToken('$origin'), isNull);
      expect(await accounts.username('$origin'), 'falcao'); // to log in again
      // The first session's access token is gone too.
      site.expireAccess();
      await expectLater(s.refresh(), throwsA(isA<SiteException>()));
    },
  );

  test('offline is not a logout', () async {
    final s = session();
    await s.login('falcao', 'correct horse battery');
    site.offline = true;
    final again = session();
    await expectLater(
      SiteApi(again).mine(),
      throwsA(isA<SiteException>().having((e) => e.offline, 'offline', isTrue)),
    );
    expect(await accounts.refreshToken('$origin'), isNotNull);
  });

  test('logging out forgets the token', () async {
    final s = session();
    await s.login('falcao', 'correct horse battery');
    await s.logout();
    expect(await accounts.refreshToken('$origin'), isNull);
    expect(await s.hasAccount, isFalse);
    expect(site.requests, contains('POST /auth/logout'));
  });

  test('over real HTTP: the cookie is read, rotated and sent back', () async {
    final server = await serveFakeSite(site);
    addTearDown(() => server.close(force: true));
    final at = Uri.parse('http://127.0.0.1:${server.port}');
    final http = IoSiteHttp(at);
    addTearDown(http.close);
    final s = SiteSession(at, http, accounts);
    await s.login('falcao', 'correct horse battery');
    final first = await accounts.refreshToken('$at');
    expect(first, startsWith('rt-'));
    await s.refresh();
    expect(site.refreshes, 1);
    expect(await accounts.refreshToken('$at'), isNot(first));
    final games = await SiteApi(s).fieldGames('campo-norte');
    expect(games.games, hasLength(2));
    final off = IoSiteHttp(Uri.parse('http://127.0.0.1:1'));
    addTearDown(off.close);
    await expectLater(
      off.send('GET', '/health'),
      throwsA(isA<SiteException>().having((e) => e.offline, 'offline', isTrue)),
    );
  });

  test('tickets are kept per registration, the newest replacing', () async {
    final t = TicketStore(store);
    KeptTicket k(String reg, String ticket) => KeptTicket(
      site: '$origin',
      registrationId: reg,
      playerId: 'p-abcdefghijkl',
      ticket: ticket,
      ticketText: 'atalaia:ticket:$ticket',
      gameTitle: 'Jogo',
      fieldName: 'Campo',
      startsAt: DateTime.utc(2026, 11, 8, 9),
    );
    await t.keep(k('r1', 'a'));
    await t.keep(k('r2', 'b'));
    await t.keep(k('r1', 'c'));
    final all = await t.all();
    expect(all.map((x) => x.ticket), ['b', 'c']);
    expect(
      (await t.forRegistration('r1'))!.startsAt,
      DateTime.utc(2026, 11, 8, 9),
    );
    await t.remove('r2');
    expect((await t.all()).single.registrationId, 'r1');
    for (var i = 0; i < 60; i++) {
      await t.keep(k('x$i', '$i'));
    }
    expect(await t.all(), hasLength(50));
  });
}
