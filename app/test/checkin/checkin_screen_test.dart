// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Checking in at the field in the app (lib/checkin/), against a fake field
// controller (test/support/fake_field.dart), in both languages: the poster
// scanned, the notice once per field and version, the form, the check-in's
// page, the replicas declared and their chrono state, the field asking for
// a federation number, a poster with another certificate, leaving.

import 'dart:typed_data';

import 'package:atalaia_app/checkin/checkin_screen.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/checkin/my_replicas.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/protocol/checkin_poster.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_field.dart';
import '../support/fakes.dart';

/// The app bar's back button (pageBack() looks for the English tooltip).
Future<void> back(WidgetTester tester) async {
  await tester.tap(find.byType(BackButton));
  await tester.pumpAndSettle();
}

Future<void> tapKey(WidgetTester tester, String key) async {
  final f = find.byKey(Key(key));
  if (f.evaluate().isEmpty) {
    // Lists build only what is near the screen.
    await tester.scrollUntilVisible(
      f,
      300,
      scrollable: find.byType(Scrollable).first,
    );
  }
  await tester.ensureVisible(f);
  await tester.pumpAndSettle();
  await tester.tap(f);
  await tester.pumpAndSettle();
}

void main() {
  Future<(Harness, FakeField)> start(
    WidgetTester tester, {
    AppLanguage language = AppLanguage.pt,
    FakeField? field,
  }) async {
    final f = field ?? FakeField();
    final h = harness(
      language: language,
      qr: FakeQr(f.posterText()),
      fieldHttp: f.http,
      caFetch: f.fetchCa,
    );
    await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
    await tester.pumpAndSettle();
    await tapKey(tester, 'player-checkin');
    return (h, f);
  }

  testWidgets('scan, notice, check in, declare replicas, see their state', (
    tester,
  ) async {
    final (h, field) = await start(tester);
    await tapKey(tester, 'checkin-scan');
    expect(find.text('Os teus dados em Campo Norte'), findsOneWidget);
    expect(find.textContaining('O nome fica 30 dias'), findsOneWidget);
    await tapKey(tester, 'checkin-notice-ok');
    expect(find.text('Jogo: Domingo de manhã'), findsOneWidget);
    expect(
      find.byKey(const Key('checkin-federation')),
      findsNothing,
    ); // the field does not ask
    await tester.enterText(find.byKey(const Key('checkin-name')), 'Falcão');
    await tapKey(tester, 'checkin-submit');
    expect(find.text('Check-in feito.'), findsOneWidget);
    expect(find.text('Jogador/a'), findsOneWidget);
    final pid = field.rows.keys.single;
    expect(field.rows[pid]!['display_name'], 'Falcão');
    expect(h.settings.noticeSeen, {'campo-norte': 1});
    expect(h.settings.displayName, 'Falcão');
    expect(
      h.settings.fieldId,
      'campo-norte',
    ); // the marshal's records name this field

    // Declare a new replica.
    await tapKey(tester, 'checkin-declare');
    await tapKey(tester, 'declare-add');
    await tester.enterText(
      find.byKey(const Key('replica-make')),
      'Tokyo Marui AK',
    );
    await tapKey(tester, 'replica-save');
    await tapKey(tester, 'declare-save');
    expect(find.byKey(const Key('declare-saved')), findsOneWidget);
    expect(find.text('por cronografar'), findsOneWidget);
    final decl = (field.rows[pid]!['declarations']! as List).single as Map;
    expect(
      (decl['type'], decl['class'], decl['make_model']),
      ('aeg', 'cqb', 'Tokyo Marui AK'),
    );

    // A marshal passes it; the page shows it after a refresh.
    field.judge('${decl['declaration_id']}', 'passed');
    await back(tester);
    expect(find.text('aprovada'), findsOneWidget);
    // Chronographed: it stays declared (the checkbox is off-limits).
    await tapKey(tester, 'checkin-declare');
    final box = tester.widget<CheckboxListTile>(find.byType(CheckboxListTile));
    expect((box.value, box.onChanged), (true, null));
    await back(tester);

    // The next visit to the player screen offers to continue.
    await back(tester);
    expect(find.byKey(const Key('player-continue')), findsOneWidget);
  });

  testWidgets('in English, with a federation number the field requires', (
    tester,
  ) async {
    final field = FakeField()..federation = 'required';
    await start(tester, language: AppLanguage.en, field: field);
    await tapKey(tester, 'checkin-scan');
    expect(find.text('Your data at Campo Norte'), findsOneWidget);
    await tapKey(tester, 'checkin-notice-ok');
    expect(find.text('Federation number (FPA)'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('checkin-name')), 'Hawk');
    await tapKey(tester, 'checkin-submit');
    expect(
      find.text('This field asks for your federation number (FPA).'),
      findsOneWidget,
    );
    expect(field.rows, isEmpty);
    await tester.enterText(
      find.byKey(const Key('checkin-federation')),
      '12345',
    );
    await tapKey(tester, 'checkin-submit');
    expect(find.text('Checked in.'), findsOneWidget);
    expect(field.rows.values.single['federation_number'], '12345');
    // Leaving erases it there.
    await tapKey(tester, 'checkin-leave');
    await tester.tap(find.widgetWithText(FilledButton, 'Leave the game'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('checkin-left')), findsOneWidget);
    expect(field.rows.values.single['status'], 'left');
  });

  testWidgets('with an APD rule: the picker, the number, the expiry, sent', (
    tester,
  ) async {
    final field = FakeField()
      ..apd = {
        'accepted': ['apd-a'],
        'register': false,
        'checkin': true,
        'expiry': true,
        'custom': <Object?>[],
      }
      ..apds = [
        {'id': 'apd-a', 'name': 'APD Alfa', 'short_name': 'Alfa'},
        {'id': 'apd-b', 'name': 'APD Beta', 'short_name': 'Beta'},
      ]
      ..verdict = 'expired';
    await start(tester, language: AppLanguage.en, field: field);
    await tapKey(tester, 'checkin-scan');
    await tapKey(tester, 'checkin-notice-ok');
    expect(find.text('APD membership'), findsOneWidget);
    expect(find.text('Accepted APDs: Alfa'), findsOneWidget);
    expect(find.byKey(const Key('checkin-federation')), findsNothing);
    await tester.enterText(find.byKey(const Key('checkin-name')), 'Hawk');
    await tester.enterText(find.byKey(const Key('checkin-apd-number')), 'A-77');
    await tester.enterText(
      find.byKey(const Key('checkin-apd-expires')),
      '31/01/2027',
    );
    await tapKey(tester, 'checkin-submit');
    await tester.scrollUntilVisible(
      find.text('Write the date as YYYY-MM-DD, for instance 2027-01-31.'),
      -300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(field.rows, isEmpty);
    await tester.enterText(
      find.byKey(const Key('checkin-apd-expires')),
      '2026-12-31',
    );
    await tapKey(tester, 'checkin-apd-pick');
    await tester.tap(find.text('APD Alfa').last);
    await tester.pumpAndSettle();
    await tapKey(tester, 'checkin-submit');
    final row = field.rows.values.single;
    expect(row['apd_id'], 'apd-a');
    expect(row['federation_number'], 'A-77');
    expect(row['membership_expires'], '2026-12-31');
    // The verdict the controller gave, and what happens next.
    expect(find.byKey(const Key('apd-badge-expired')), findsOneWidget);
    expect(find.byKey(const Key('checkin-apd-hint')), findsOneWidget);
  });

  testWidgets('the notice is shown again only when its version changes', (
    tester,
  ) async {
    final field = FakeField();
    final h = harness(
      qr: FakeQr(field.posterText()),
      fieldHttp: field.http,
      caFetch: field.fetchCa,
      settings: AppSettings()..noticeSeen = {'campo-norte': 1},
    );
    await tester.pumpWidget(h.app(home: const CheckinScreen()));
    await tester.pumpAndSettle();
    await tapKey(tester, 'checkin-scan');
    expect(find.byKey(const Key('checkin-name')), findsOneWidget);
    field.notice = 2;
    final h2 = harness(
      settings: h.settings,
      fieldHttp: field.http,
      caFetch: field.fetchCa,
    );
    await tester.pumpWidget(
      h2.app(home: CheckinScreen(posterText: field.posterText())),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('checkin-notice')), findsOneWidget);
  });

  testWidgets(
    'a poster with another certificate for a known field is refused',
    (tester) async {
      final field = FakeField();
      final h = harness(fieldHttp: field.http, caFetch: field.fetchCa);
      await FieldTrust(
        h.store,
        fetch: field.fetchCa,
      ).pin(parsePoster(field.posterText()));
      final forged = field.posterText(
        ca: Uint8List.fromList([for (final b in field.sha256Bytes) b ^ 1]),
      );
      await tester.pumpWidget(h.app(home: CheckinScreen(posterText: forged)));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('checkin-changed')), findsOneWidget);
      expect(
        find.textContaining(shortFingerprint(field.sha256Bytes)),
        findsOneWidget,
      );
      expect(field.rows, isEmpty);
    },
  );

  testWidgets(
    'other codes are not posters; an unreachable field names its Wi-Fi',
    (tester) async {
      final field = FakeField()..offline = true;
      final h = harness(fieldHttp: field.http, caFetch: field.fetchCa);
      await tester.pumpWidget(h.app(home: const CheckinScreen()));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('checkin-text')),
        'atalaia:join:AQID',
      );
      await tapKey(tester, 'checkin-use-text');
      expect(
        find.textContaining('Isto é um código de entrada para um dispositivo'),
        findsOneWidget,
      );
      await tester.enterText(find.byKey(const Key('checkin-text')), 'ola');
      await tapKey(tester, 'checkin-use-text');
      expect(
        find.text('Isto não é um cartaz de check-in do Atalaia.'),
        findsOneWidget,
      );
      await tester.enterText(
        find.byKey(const Key('checkin-text')),
        field.posterText(),
      );
      await tapKey(tester, 'checkin-use-text');
      expect(find.textContaining('«Atalaia»'), findsOneWidget);
    },
  );

  for (final squads in [false, true]) {
    testWidgets(
      squads
          ? 'in a game with squads: team › squad'
          : 'in a game without squads: the team alone',
      (tester) async {
        final field = FakeField();
        field.handle('POST', '/checkin', {
          'game_id': 42,
          'player_id': 'p-abcdefgh2345',
          'player_secret': 's',
          'display_name': 'Lince',
          'notice_version': 1,
        }, null);
        field.assign(
          'p-abcdefgh2345',
          team: 'red',
          squad: squads ? 2 : 0,
          role: squads ? 'squad_leader' : 'player',
        );
        // Checking in again keeps the GM's assignment and gives a token.
        final t = field.handle('POST', '/checkin', {
          'game_id': 42,
          'player_id': 'p-abcdefgh2345',
          'player_secret': 's',
          'display_name': 'Lince',
          'notice_version': 1,
        }, null).json;
        final h = harness(fieldHttp: field.http, caFetch: field.fetchCa);
        final pinned = await h.services.trust.pin(
          parsePoster(field.posterText()),
        );
        final c = FieldCheckin(
          fieldId: field.fieldId,
          gameId: 42,
          gameName: 'Domingo de manhã',
          playerId: 'p-abcdefgh2345',
          token: t['token']! as String,
          exp: 4102444800,
          status: 'checked_in',
          role: 'player',
        );
        await tester.pumpWidget(
          h.app(
            home: CheckinStatusScreen(checkin: c, field: pinned),
          ),
        );
        await tester.pumpAndSettle();
        final chip = tester.widget<Chip>(find.byKey(const Key('checkin-team')));
        expect(
          (chip.label as Text).data,
          squads ? 'vermelha › squad 2' : 'vermelha',
        );
        expect(
          find.text(squads ? 'Líder de squad' : 'Jogador/a'),
          findsOneWidget,
        );
        expect(find.textContaining('esquadra'), findsNothing);
      },
    );
  }
}
