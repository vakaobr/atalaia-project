// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The club pages in the app (lib/site/clubs.dart, club_screens.dart;
// decisions S18-5, S18-8, S18-9, S18-11 and APPS-9 to APPS-16) against the
// fake site server (test/support/fake_site.dart): the account's clubs and a
// waiting invitation, a club's page with its fields and members, an admin
// inviting, changing a role, removing and editing, accepting and declining
// invitations, leaving, the last admin refused, making and deleting a club,
// and the site out of reach.

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/site/clubs.dart';
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

Future<Harness> openClubs(
  WidgetTester tester,
  FakeSite site, {
  AppLanguage language = AppLanguage.en,
}) async {
  final h = harness(language: language, siteHttp: site.http);
  await h.services.sites.of(_link.site).login(site.username, site.password);
  await tester.pumpWidget(h.app(home: SiteScreen(link: _link)));
  await tester.pumpAndSettle();
  await tapKey(tester, 'site-clubs');
  return h;
}

Future<void> inDialog(WidgetTester tester, String text) async {
  await tester.tap(
    find.descendant(of: find.byType(AlertDialog), matching: find.text(text)),
  );
  await tester.pumpAndSettle();
}

Future<void> menu(WidgetTester tester, String user, String item) async {
  await tapKey(tester, 'club-member-menu-$user');
  await tester.tap(find.byKey(Key('club-member-$item-$user')).last);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('the clubs, a club\'s page, and what its admin does', (
    tester,
  ) async {
    final site = FakeSite();
    await openClubs(tester, site);
    expect(site.requests, containsAll(['GET /clubs', 'GET /me/clubs']));
    // Only accepted memberships are the account's clubs; the invitation waits.
    expect(find.byKey(const Key('club-club-a')), findsOneWidget);
    expect(find.byKey(const Key('club-club-b')), findsNothing);
    expect(find.text('1 club invitation is waiting for you.'), findsOneWidget);
    expect(find.text('Corvos · Admin · Public page on'), findsOneWidget);

    await tester.tap(find.byKey(const Key('club-club-a')));
    await tester.pumpAndSettle();
    expect(find.text('Corvos · corvos-da-serra · Admin'), findsOneWidget);
    expect(find.text('Airsoft ao domingo de manhã.'), findsOneWidget);
    expect(find.text('Campo Norte'), findsOneWidget);
    expect(site.requests, contains('GET /clubs/club-a/members'));
    expect(await reveal(tester, find.text('falcao (you)')), findsOneWidget);
    expect(
      await reveal(tester, find.textContaining('invitation not yet accepted')),
      findsOneWidget,
      reason: 'an admin sees the invitations',
    );

    // Inviting: an unknown username is refused in words, a known one invited.
    await tester.enterText(
      await reveal(tester, find.byKey(const Key('club-invite-user'))),
      'nobody',
    );
    await tapKey(tester, 'club-invite');
    expect(find.text('No account has that username.'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('club-invite-user')), 'joana');
    await tapKey(tester, 'club-invite');
    expect(site.bodies['PUT /clubs/club-a/members'], {
      'username': 'joana',
      'role': 'member',
    });
    expect(find.text('joana invited.'), findsOneWidget);
    expect(
      site.clubMembers['club-a']!.any((m) => m['username'] == 'joana'),
      isTrue,
    );

    // A role, then a removal (after a confirmation).
    await menu(tester, 'u-2', 'role');
    expect(site.bodies['PUT /clubs/club-a/members'], {
      'username': 'rita',
      'role': 'admin',
    });
    expect(find.text('rita now has the role Admin.'), findsOneWidget);
    await menu(tester, 'u-3', 'remove');
    expect(find.text('Remove tiago from the club?'), findsOneWidget);
    await inDialog(tester, 'Remove');
    expect(site.requests, contains('DELETE /clubs/club-a/members/u-3'));
    expect(find.text('tiago is no longer in the club.'), findsOneWidget);

    // Editing: a bad colour is refused, then saved with the page off.
    await tapKey(tester, 'club-edit');
    await tester.enterText(find.byKey(const Key('clubform-colour')), 'green');
    await tapKey(tester, 'clubform-save');
    expect(
      find.text('The colour must be #rrggbb, for example #2e7d32.'),
      findsOneWidget,
    );
    await tester.enterText(find.byKey(const Key('clubform-colour')), '#1565c0');
    await tapKey(tester, 'clubform-public');
    await tapKey(tester, 'clubform-save');
    expect(site.bodies['PATCH /clubs/club-a'], {
      'name': 'Corvos da Serra',
      'short_name': 'Corvos',
      'description': 'Airsoft ao domingo de manhã.',
      'colour': '#1565c0',
      'public_page': false,
    });
    expect(find.text('Saved.'), findsOneWidget);
    expect(await reveal(tester, find.text('Public page off')), findsOneWidget);
  });

  testWidgets('invitations: accepted, declined; leaving; the last admin', (
    tester,
  ) async {
    final site = FakeSite();
    site.clubs['club-c'] = {
      ...site.clubs['club-b']!,
      'id': 'club-c',
      'name': 'Falcões',
      'slug': 'falcoes',
    };
    site.clubMembers['club-c'] = [
      {
        'user_id': site.myUserId,
        'username': site.username,
        'role': 'member',
        'accepted': false,
        'accepted_at': null,
        'invited_at': '2026-10-04T10:00:00+00:00',
      },
    ];
    await openClubs(tester, site);
    expect(
      find.text('2 club invitations are waiting for you.'),
      findsOneWidget,
    );
    await tapKey(tester, 'clubs-mine');
    expect(find.byKey(const Key('myclubs-invite-club-b')), findsOneWidget);
    expect(find.textContaining('Invitation as Member · '), findsWidgets);

    await tapKey(tester, 'myclubs-accept-club-b');
    expect(site.requests, contains('POST /me/clubs/club-b/accept'));
    expect(find.text('You joined Lobos do Norte.'), findsOneWidget);
    expect(find.byKey(const Key('myclubs-member-club-b')), findsOneWidget);

    await tapKey(tester, 'myclubs-decline-club-c');
    expect(find.text('Decline the invitation to Falcões?'), findsOneWidget);
    await inDialog(tester, 'Decline');
    expect(
      site.requests,
      contains('DELETE /clubs/club-c/members/${site.myUserId}'),
    );
    expect(find.byKey(const Key('myclubs-no-invites')), findsOneWidget);

    // Leaving a club as a member.
    await tapKey(tester, 'myclubs-leave-club-b');
    expect(find.text('Leave Lobos do Norte?'), findsOneWidget);
    await inDialog(tester, 'Leave');
    expect(find.text('You left Lobos do Norte.'), findsOneWidget);
    expect(find.byKey(const Key('myclubs-member-club-b')), findsNothing);

    // The only admin of Corvos cannot leave.
    await tapKey(tester, 'myclubs-leave-club-a');
    await inDialog(tester, 'Leave');
    expect(
      find.text(
        'A club keeps at least one admin: make someone else admin first.',
      ),
      findsOneWidget,
    );
    expect(find.byKey(const Key('myclubs-member-club-a')), findsOneWidget);

    // Back on the list, the club joined and left is not there.
    await back(tester);
    expect(find.byKey(const Key('clubs-invites')), findsNothing);
    expect(find.byKey(const Key('club-club-b')), findsNothing);
  });

  testWidgets('making a club, then deleting it, in Portuguese', (tester) async {
    final site = FakeSite();
    await openClubs(tester, site, language: AppLanguage.pt);
    expect(find.text('Os teus clubes'), findsOneWidget);
    await tapKey(tester, 'clubs-new');
    await tapKey(tester, 'clubform-save');
    expect(
      find.text('Faltam o nome, o nome curto ou o endereço.'),
      findsOneWidget,
    );
    expect(site.requests.where((r) => r == 'POST /clubs'), isEmpty);

    await tester.enterText(find.byKey(const Key('clubform-name')), 'Javalis');
    await tester.enterText(find.byKey(const Key('clubform-short')), 'Javalis');
    await tester.enterText(find.byKey(const Key('clubform-slug')), 'Javalis!');
    await tapKey(tester, 'clubform-save');
    expect(find.textContaining('Esse endereço não é válido'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('clubform-slug')), 'javalis');
    await tapKey(tester, 'clubform-save');
    expect(site.bodies['POST /clubs'], {
      'name': 'Javalis',
      'short_name': 'Javalis',
      'slug': 'javalis',
    });
    // The new club's page, as its admin.
    expect(find.text('Javalis · javalis · Admin'), findsOneWidget);
    expect(find.text('Página pública desligada'), findsOneWidget);

    await tapKey(tester, 'club-delete');
    expect(find.text('Apagar Javalis?'), findsOneWidget);
    await inDialog(tester, 'Apagar o clube');
    expect(find.text('Javalis apagado.'), findsOneWidget);
    expect(site.clubs.containsKey('club-n1'), isFalse);
    await back(tester);
    expect(find.byKey(const Key('club-club-n1')), findsNothing);
  });

  testWidgets('a member\'s page: no admin tools, and leaving', (tester) async {
    final site = FakeSite();
    site.clubMembers['club-a']!.first['role'] = 'member';
    site.clubMembers['club-a']![1]['role'] = 'admin';
    await openClubs(tester, site);
    await tester.tap(find.byKey(const Key('club-club-a')));
    await tester.pumpAndSettle();
    expect(
      find.text('Only the club\'s members see this list.'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('club-invite')), findsNothing);
    expect(find.byKey(const Key('club-edit')), findsNothing);
    expect(find.byKey(const Key('club-member-menu-u-2')), findsNothing);
    expect(
      find.textContaining('invitation not yet accepted'),
      findsNothing,
      reason: 'invitations are the admins\' business',
    );
    await tapKey(tester, 'club-leave');
    await inDialog(tester, 'Leave');
    expect(find.text('You left Corvos da Serra.'), findsOneWidget);
    await back(tester);
    expect(find.byKey(const Key('clubs-none')), findsOneWidget);
  });

  testWidgets('the site out of reach', (tester) async {
    final site = FakeSite();
    await openClubs(tester, site);
    site.offline = true;
    await tester.tap(find.byKey(const Key('clubs-reload')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('clubs-error')), findsOneWidget);
    site.offline = false;
    await tester.tap(find.byKey(const Key('clubs-reload')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('club-club-a')), findsOneWidget);
  });

  test('the calls carry the server codes', () async {
    final site = FakeSite();
    final origin = Uri.parse('https://campo.example.pt');
    final session = SiteSession(
      origin,
      site.http(origin),
      SiteAccounts(MemoryAppStore()),
    );
    await session.login(site.username, site.password);
    final api = ClubApi(session);
    final club = await api.get('club-a');
    expect((club.admin, club.fields.single.name), (true, 'Campo Norte'));
    expect((await api.members('club-a')).map((m) => m.username), [
      'falcao',
      'rita',
      'tiago',
    ]);
    final mine = await api.mine();
    expect(mine.map((m) => (m.clubId, m.accepted)), [
      ('club-a', true),
      ('club-b', false),
    ]);
    await expectLater(
      api.get('club-x'),
      throwsA(
        isA<SiteException>().having((e) => e.code, 'code', 'club_not_found'),
      ),
    );
    await expectLater(
      api.update('club-b', const ClubForm(name: 'x')),
      throwsA(
        isA<SiteException>().having((e) => e.code, 'code', 'club_not_found'),
      ),
      reason: 'not a member, and the page is not public',
    );
    expect(const ClubForm(name: 'A', colour: '').toRequest(), {
      'name': 'A',
      'colour': '',
    });
  });
}
