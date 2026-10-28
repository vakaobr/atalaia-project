// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The marshal role needs the field controller's yes (decisions MR-1 to MR-14,
// lib/marshal/marshal_access.dart), against a fake field controller
// (test/support/fake_field.dart) that keeps the GM's marshal list as the
// Pi's does: a listed player is told the id the GM gave and registers a key
// for it; anyone else is refused. The marshal flow in the app: validated,
// refused, offline with a confirmation made earlier, offline never
// confirmed, offline past the day, removed from the list with readings not
// yet sent, and put back.

import 'package:atalaia_app/storage/app_store.dart';
import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/checkin/my_replicas.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/chrono/reading.dart';
import 'package:atalaia_app/chrono/replica.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/marshal/chrono_queue.dart';
import 'package:atalaia_app/marshal/marshal_access.dart';
import 'package:atalaia_app/marshal/marshal_home.dart';
import 'package:atalaia_app/marshal/marshal_records.dart';
import 'package:atalaia_app/protocol/checkin_poster.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_field.dart';
import '../support/marshal_trust.dart';

const _pid = 'p-marshalmarsh';

const _notListed =
    'The field controller does not have you on its marshal list. '
    'Ask the GM to add you as a marshal.';

void main() {
  late FakeField field;
  late Harness h;
  late PinnedField pinned;
  late FieldCheckin checkin;
  late MarshalRecords records;

  /// A phone whose player checked in at the field; [role] is what the GM
  /// had given when the token was made (the phone is told the current one).
  Future<void> boot(WidgetTester tester) async {
    field = FakeField();
    h = harness(
      language: AppLanguage.en,
      fieldHttp: field.http,
      caFetch: field.fetchCa,
    );
    pinned = await h.services.trust.pin(parsePoster(field.posterText()));
    final t = field.handle('POST', '/checkin', {
      'game_id': 42,
      'player_id': _pid,
      'player_secret': 'y',
      'display_name': 'Rui',
      'notice_version': 1,
    }, null);
    checkin = FieldCheckin(
      fieldId: field.fieldId,
      gameId: 42,
      gameName: 'Domingo de manhã',
      playerId: _pid,
      token: t.json['token']! as String,
      exp: 4102444800,
      status: 'checked_in',
      role: 'player',
    );
    await h.services.checkins.saveCheckin(checkin);
    records = MarshalRecords(h.store, h.settings);
    await tester.runAsync(() async {
      await records.load();
      await records.newKey();
    });
  }

  Future<void> open(WidgetTester tester) async {
    await tester.pumpWidget(h.app(home: MarshalHomeScreen(records: records)));
    await tester.pumpAndSettle();
  }

  Future<void> reopen(WidgetTester tester) async {
    await tester.pumpWidget(const SizedBox());
    await open(tester);
  }

  bool toolsShown() =>
      find.byKey(const Key('marshal-chrono')).evaluate().isNotEmpty;

  /// A reading taken now: null when it was recorded, else why not.
  Future<Object?> shoot(WidgetTester tester) async =>
      tester.runAsync<Object?>(() async {
        try {
          await records.record(
            replica: Replica(
              replicaId: newUuid(),
              ownerPlayerId: 'p-abcdefgh2345',
              type: ReplicaType.aeg,
              replicaClass: 'rifle',
              makeModel: 'M4',
              registeredAt: '2026-10-19T09:00:00Z',
              tagType: TagType.qr,
              tagUid: 'ATL-1',
            ),
            type: ReadingType.checkin,
            velocityMps: 90,
            bbWeightG: 0.2,
            gameId: '42',
          );
          return null;
        } on MarshalNotAuthorised catch (e) {
          return e;
        }
      });

  testWidgets('listed: the id comes from the controller, the key goes there', (
    tester,
  ) async {
    await boot(tester);
    field.listMarshal(_pid, id: 'M-03');
    // What a marshal might type is not what counts.
    h.settings
      ..marshalId = 'whoever'
      ..marshalName = 'Whoever';
    await open(tester);
    expect(find.text('You are marshal M-03 (Rui)'), findsOneWidget);
    expect(toolsShown(), isTrue);
    expect(find.byKey(const Key('marshal-id')), findsNothing);
    expect(find.byKey(const Key('marshal-name')), findsNothing);
    expect(h.settings.marshalId, 'M-03');
    expect(h.settings.marshalName, 'Rui');
    expect(h.settings.fieldId, field.fieldId);
    expect(field.marshalKeys['M-03'], records.publicKeyBase64);
    expect(records.hasIdentity, isTrue);
    // The token's role was stale: the phone learned it.
    expect(h.services.checkins.checkins.single.role, 'marshal');
    final v = h.settings.marshalValidation!;
    expect(v.validUntilMs - v.validatedAtMs, 2 * 3600 * 1000);
    expect(await shoot(tester), isNull);
    expect(records.readings.single.marshalId, 'M-03');
  });

  testWidgets('confirmed as a marshal: no join key is kept (APX-1)', (
    tester,
  ) async {
    await boot(tester);
    h.settings
      ..joinKeyHex = 'ab' * 32
      ..joinKeyUse = AppSettings.joinKeyForProp;
    field.listMarshal(_pid, id: 'M-03');
    await open(tester);
    expect(h.settings.marshalValidation, isNotNull);
    expect(h.settings.joinKeyHex, isNull);
    expect(h.settings.joinKeyUse, isNull);
  });

  testWidgets('a phone controller keeps its key as a marshal too', (
    tester,
  ) async {
    await boot(tester);
    h.settings
      ..joinKeyHex = 'ab' * 32
      ..joinKeyUse = AppSettings.joinKeyForController;
    field.listMarshal(_pid, id: 'M-03');
    await open(tester);
    expect(h.settings.joinKeyHex, 'ab' * 32);
  });

  testWidgets('not on the list: refused, with the words, nothing recorded', (
    tester,
  ) async {
    await boot(tester);
    // The role by hand is not the list (MR-5); a typed id is nothing.
    field.assign(_pid, role: 'marshal');
    h.settings
      ..marshalId = 'M-01'
      ..marshalName = 'Rui';
    await open(tester);
    expect(find.text(_notListed), findsOneWidget);
    expect(toolsShown(), isFalse);
    expect(find.byKey(const Key('marshal-id')), findsNothing);
    expect(field.marshalKeys, isEmpty);
    expect(h.settings.marshalId, isEmpty);
    expect(records.hasIdentity, isFalse);
    expect(await shoot(tester), isA<MarshalNotAuthorised>());
    // The GM adds the player; asking again is enough.
    field.listMarshal(_pid);
    await tester.tap(find.byKey(const Key('marshal-retry')));
    await tester.pumpAndSettle();
    expect(find.text('You are marshal M-01 (Rui)'), findsOneWidget);
    expect(toolsShown(), isTrue);
  });

  testWidgets('a player who is not a marshal is refused the same way', (
    tester,
  ) async {
    await boot(tester);
    await open(tester);
    expect(find.text(_notListed), findsOneWidget);
    expect(toolsShown(), isFalse);
  });

  testWidgets('offline after a confirmation: allowed for two hours', (
    tester,
  ) async {
    await boot(tester);
    field.listMarshal(_pid, id: 'M-03');
    await open(tester);
    expect(toolsShown(), isTrue);
    field.offline = true;
    await reopen(tester);
    expect(
      find.textContaining('Offline: the field controller confirmed you'),
      findsOneWidget,
    );
    expect(find.textContaining('marshal M-03'), findsWidgets);
    expect(toolsShown(), isTrue);
    expect(records.hasIdentity, isTrue);
    await shoot(tester);
    expect(records.readings, hasLength(1));
    expect(records.unsentSeries(), hasLength(1)); // sent when the field is back
  });

  testWidgets('offline, never confirmed here: not a marshal', (tester) async {
    await boot(tester);
    field.listMarshal(_pid, id: 'M-03');
    field.offline = true;
    h.settings
      ..marshalId = 'M-03'
      ..marshalName = 'Rui';
    await open(tester);
    expect(
      find.textContaining('has not been confirmed as a marshal here yet'),
      findsOneWidget,
    );
    expect(toolsShown(), isFalse);
    expect(records.hasIdentity, isFalse);
    expect(await shoot(tester), isA<MarshalNotAuthorised>());
    // Back on the field's network, one ask is enough.
    field.offline = false;
    await tester.tap(find.byKey(const Key('marshal-retry')));
    await tester.pumpAndSettle();
    expect(toolsShown(), isTrue);
  });

  testWidgets('offline past two hours: the confirmation has run out', (
    tester,
  ) async {
    await boot(tester);
    field.listMarshal(_pid, id: 'M-03');
    h.settings
      ..marshalId = 'M-03'
      ..marshalName = 'Rui'
      ..fieldId = field.fieldId;
    trustMarshal(
      records,
      at: DateTime.now().subtract(const Duration(hours: 25)),
    );
    field.offline = true;
    await open(tester);
    expect(find.textContaining('has run out'), findsOneWidget);
    expect(toolsShown(), isFalse);
    expect(records.hasIdentity, isFalse);
    expect(await shoot(tester), isA<MarshalNotAuthorised>());
  });

  testWidgets('a confirmation for another field is not this field\'s', (
    tester,
  ) async {
    await boot(tester);
    field.listMarshal(_pid, id: 'M-03');
    h.settings
      ..marshalId = 'M-03'
      ..marshalName = 'Rui';
    trustMarshal(records, fieldId: 'campo-sul');
    field.offline = true;
    await open(tester);
    expect(toolsShown(), isFalse);
    expect(
      find.textContaining('has not been confirmed as a marshal here yet'),
      findsOneWidget,
    );
  });

  testWidgets('the open screens ask again every 10 minutes (MR-4)', (
    tester,
  ) async {
    await boot(tester);
    field.listMarshal(_pid, id: 'M-03');
    await open(tester);
    expect(toolsShown(), isTrue);
    // The GM takes the marshal off the list while the screen stays open: the
    // renewal finds out without the marshal reopening anything.
    field.unlistMarshal(_pid);
    await tester.pump(renewEvery);
    await tester.pumpAndSettle();
    expect(
      find.textContaining('took you off the marshal list'),
      findsOneWidget,
    );
    expect(toolsShown(), isFalse);
  });

  testWidgets('removed from the list: revoked, readings kept, then held', (
    tester,
  ) async {
    await boot(tester);
    field.listMarshal(_pid, id: 'M-03');
    await open(tester);
    await shoot(tester);
    expect(records.unsentSeries(), hasLength(1));
    // The GM takes the marshal off the list.
    field.unlistMarshal(_pid);
    await reopen(tester);
    expect(
      find.textContaining('took you off the marshal list'),
      findsOneWidget,
    );
    expect(
      find.textContaining('The 1 series not yet sent stay'),
      findsOneWidget,
    );
    expect(toolsShown(), isFalse);
    expect(h.settings.marshalValidation, isNull);
    expect(h.settings.marshalId, isEmpty);
    expect(records.hasIdentity, isFalse);
    expect(records.readings, hasLength(1)); // kept
    expect(h.services.checkins.checkins.single.role, 'player');
    // Sending them is refused, and they are not given up on.
    await tester.pumpWidget(
      h.app(
        home: ChronoQueueScreen(
          checkin: h.services.checkins.checkins.single,
          field: pinned,
          records: records,
          templates: const [],
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('queue-send-pending')));
    await tester.pumpAndSettle();
    expect(
      find.textContaining('does not have you on its marshal list'),
      findsOneWidget,
    );
    expect(records.unsentSeries(), hasLength(1));
    expect(field.readings, isEmpty);
    // The GM puts the marshal back: confirmed again, and the series go.
    field.listMarshal(_pid, id: 'M-03');
    await reopen(tester);
    expect(find.text('You are marshal M-03 (Rui)'), findsOneWidget);
    expect(toolsShown(), isTrue);
    await tester.pumpWidget(
      h.app(
        home: ChronoQueueScreen(
          checkin: h.services.checkins.checkins.single,
          field: pinned,
          records: records,
          templates: const [],
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('queue-send-pending')));
    await tester.pumpAndSettle();
    expect(records.unsentSeries(), isEmpty);
    expect(field.readings, hasLength(1));
  });

  testWidgets('a new key is told to the controller before the next reading', (
    tester,
  ) async {
    await boot(tester);
    field.listMarshal(_pid, id: 'M-03');
    await open(tester);
    final first = records.publicKeyBase64;
    expect(field.marshalKeys['M-03'], first);
    await tester.runAsync(records.newKey);
    expect(records.hasIdentity, isFalse); // not the key the controller holds
    await reopen(tester);
    expect(field.marshalKeys['M-03'], records.publicKeyBase64);
    expect(field.marshalKeys['M-03'], isNot(first));
    expect(records.hasIdentity, isTrue);
  });

  testWidgets('an expired check-in is not a "no": the confirmation stays', (
    tester,
  ) async {
    await boot(tester);
    field.listMarshal(_pid, id: 'M-03');
    await open(tester);
    final access = MarshalAccess(
      settings: h.settings,
      records: records,
      persist: () async {},
    );
    checkin.token = 'not a token';
    final status = await access.validate(
      CheckinClient(field.http(pinned)),
      checkin,
    );
    expect(status, MarshalStatus.sessionExpired);
    expect(h.settings.marshalValidation, isNotNull);
    expect(h.settings.marshalId, 'M-03');
  });
}
