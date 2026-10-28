// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The marshal's "replicas to chrono" list (lib/marshal/chrono_queue.dart)
// against a fake field controller: the counts and the players with pending
// replicas, a declaration with no registered replica chronographed from the
// list (registered and linked by the upload), the signed series sent and
// the list updated, a series kept on the phone while the controller is out
// of reach and sent later, a hand check-in.

import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/checkin/checkin_screen.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/checkin/my_replicas.dart';
import 'package:atalaia_app/chrono/chrono_ui.dart' show ChronoScreen;
import 'package:atalaia_app/chrono/limit_template.dart';
import 'package:atalaia_app/chrono/record_signer.dart';
import 'package:atalaia_app/chrono/replica.dart';
import 'package:atalaia_app/chrono/reading.dart' show newUuid;
import 'package:atalaia_app/platform/services.dart' show NfcRead, NfcState;
import 'package:atalaia_app/l10n/strings_pt.dart';
import 'package:atalaia_app/marshal/chrono_queue.dart';
import 'package:atalaia_app/marshal/marshal_records.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:atalaia_app/ui/code_kind.dart';
import 'package:atalaia_app/ui/qr_painter.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_field.dart';
import '../support/fakes.dart';
import '../support/marshal_trust.dart';

final templates = [
  LimitTemplate.parse(
    File('lib/chrono/limit_templates/portugal.yaml').readAsStringSync(),
  ),
];

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
  late FakeField field;
  late PinnedField pinned;
  late FieldCheckin marshal;
  late String playerDecl;

  setUp(() {
    field = FakeField();
    pinned = PinnedField(
      fieldId: field.fieldId,
      fieldName: field.fieldName,
      caPem: field.pem,
      caSha256: field.sha256Bytes,
      urls: field.urls,
    );
    playerDecl = '6f1d2a3b-4c5d-4e6f-8a9b-0c1d2e3f4a5b';
    field.handle('POST', '/checkin', {
      'game_id': 42,
      'player_id': 'p-abcdefgh2345',
      'player_secret': 'x',
      'display_name': 'Coruja',
      'notice_version': 1,
      'replicas': [
        {'declaration_id': playerDecl, 'type': 'aeg', 'class': 'rifle'},
      ],
    }, null);
    final t = field.handle('POST', '/checkin', {
      'game_id': 42,
      'player_id': 'p-marshalmarsh',
      'player_secret': 'y',
      'display_name': 'Rui',
      'notice_version': 1,
    }, null);
    field.listMarshal('p-marshalmarsh', id: 'm-rui', name: 'Rui');
    final marshalToken =
        field
                .handle(
                  'POST',
                  '/checkin/token',
                  null,
                  t.json['token'] as String,
                )
                .json['token']!
            as String;
    marshal = FieldCheckin(
      fieldId: field.fieldId,
      gameId: 42,
      gameName: 'Domingo de manhã',
      playerId: 'p-marshalmarsh',
      token: marshalToken,
      exp: 4102444800,
      status: 'checked_in',
      role: 'marshal',
    );
  });

  Future<MarshalRecords> records(AppStore store, AppSettings settings) async {
    settings
      ..marshalName = 'Rui'
      ..marshalId = 'm-rui'
      ..fieldId = field.fieldId;
    final r = MarshalRecords(store, settings);
    await r.load();
    await r.newKey();
    trustMarshal(r);
    // The controller holds the key it was told (MR-5).
    field.marshalKeys['m-rui'] = r.publicKeyBase64!;
    return r;
  }

  testWidgets('from the list to the chronograph and back, signed', (
    tester,
  ) async {
    final h = harness(fieldHttp: field.http);
    final r = await records(h.store, h.settings);
    await tester.pumpWidget(
      h.app(
        home: ChronoQueueScreen(
          checkin: marshal,
          field: pinned,
          records: r,
          templates: templates,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      find.text('Por cronografar: 1 · aprovadas: 0 · recusadas: 0'),
      findsOneWidget,
    );
    expect(find.text('Coruja'), findsOneWidget);
    expect(find.textContaining('ainda sem registo'), findsOneWidget);

    await tapKey(tester, 'queue-decl-$playerDecl');
    await tapKey(tester, 'queue-sticker-qr'); // no sticker: the printed label
    for (final k in ['1', '0', '0']) {
      await tapKey(tester, 'chrono-key-$k');
    }
    await tapKey(tester, 'chrono-record');
    await tapKey(tester, 'chrono-send');
    expect(find.text('Enviado: aprovada.'), findsOneWidget);
    final sent = field.readings.single;
    expect(
      (sent['player_id'], sent['game_id'], sent['field_id']),
      ('p-abcdefgh2345', '42', field.fieldId),
    );
    // The signature is the marshal's Ed25519 over the record.
    final reading = await verifyRecordJson(sent, r.publicKey!);
    expect(r.uploaded, contains(reading.readingId));
    expect(
      r.replicas.single.replicaId,
      sent['replica_id'],
    ); // registered on the phone
    // The upload linked the declaration to the new replica.
    final decl =
        (field.rows['p-abcdefgh2345']!['declarations']! as List).single as Map;
    expect((decl['replica_id'], decl['state']), (sent['replica_id'], 'passed'));

    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    expect(
      find.text('Por cronografar: 0 · aprovadas: 1 · recusadas: 0'),
      findsOneWidget,
    );
    expect(find.byType(ChronoStateChip), findsOneWidget);
    expect(find.text('aprovada'), findsOneWidget);
  });

  testWidgets('a poster scanned in the list is not a replica label', (
    tester,
  ) async {
    final h = harness(fieldHttp: field.http, qr: FakeQr(field.posterText()));
    final r = await records(h.store, h.settings);
    await tester.pumpWidget(
      h.app(
        home: ChronoQueueScreen(
          checkin: marshal,
          field: pinned,
          records: r,
          templates: templates,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tapKey(tester, 'queue-scan');
    expect(find.text(ptStrings['code.is_poster']!), findsOneWidget);
    expect(find.text(ptStrings['queue.not_found']!), findsNothing);
  });

  testWidgets("a player's printed label finds the declaration, and is shown", (
    tester,
  ) async {
    // The label a player's app (or the console) makes for a declaration
    // nobody has registered yet: the scan finds it on any marshal's phone.
    final label = Replica.labelFor(playerDecl);
    expect(label, 'ATL-6F1D2A3B');
    final h = harness(fieldHttp: field.http, qr: FakeQr(label));
    final r = await records(h.store, h.settings);
    await tester.pumpWidget(
      h.app(
        home: ChronoQueueScreen(
          checkin: marshal,
          field: pinned,
          records: r,
          templates: templates,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(r.replicas, isEmpty);
    await tapKey(tester, 'queue-scan');
    expect(find.text(ptStrings['queue.not_found']!), findsNothing);
    expect(
      tester
          .widget<ListTile>(find.byKey(Key('queue-decl-$playerDecl')))
          .selected,
      isTrue,
    );
    // Another code is not it.
    h.qr.next = 'ATL-00000000';
    await tapKey(tester, 'queue-scan');
    expect(find.text(ptStrings['queue.not_found']!), findsOneWidget);

    // The marshal can show it too; it holds the same text.
    await tapKey(tester, 'label-show-$playerDecl');
    expect(tester.widget<QrCodeView>(find.byType(QrCodeView)).data, label);
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();

    // Chronographed from the queue, the replica is registered under that
    // label, which the registry's own scan then matches.
    await tapKey(tester, 'queue-decl-$playerDecl');
    await tapKey(tester, 'queue-sticker-qr'); // no sticker: the printed label
    expect(r.replicas.single.replicaId, playerDecl);
    expect(r.replicas.single.tagUid, label);
    expect(r.byTag(label)?.replicaId, playerDecl);
    expect(classifyCode(label), isNull);
  });

  testWidgets('the marshal sees the APD verdict and lets a pending player in', (
    tester,
  ) async {
    field
      ..confirm = 'staff'
      ..verdict = 'expired';
    field.handle('POST', '/checkin', {
      'game_id': 42,
      'player_id': 'p-lapsedlapsed',
      'player_secret': 'z',
      'display_name': 'Gaio',
      'notice_version': 1,
      'apd_id': 'apd-a',
      'membership_number': 'A-1',
      'membership_expires': '2026-01-01',
      'replicas': [
        {
          'declaration_id': '7a1d2a3b-4c5d-4e6f-8a9b-0c1d2e3f4a5b',
          'type': 'aeg',
          'class': 'rifle',
        },
      ],
    }, null);
    final h = harness(fieldHttp: field.http);
    final r = await records(h.store, h.settings);
    await tester.pumpWidget(
      h.app(
        home: ChronoQueueScreen(
          checkin: marshal,
          field: pinned,
          records: r,
          templates: templates,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('queue-apd-p-lapsedlapsed')), findsOneWidget);
    expect(find.byKey(const Key('apd-badge-expired')), findsOneWidget);
    expect(find.textContaining('A-1'), findsOneWidget);
    expect(find.textContaining('2026-01-01'), findsOneWidget);
    // Never blocked: a marshal lets the player in, the verdict notwithstanding.
    await tapKey(tester, 'queue-confirm-p-lapsedlapsed');
    final row = field.rows['p-lapsedlapsed']!;
    expect(row['status'], 'checked_in');
    expect(row['apd_override'], true);
    expect(find.byKey(const Key('queue-confirm-p-lapsedlapsed')), findsNothing);
    expect(find.textContaining('admitido por um marshal'), findsOneWidget);
  });

  testWidgets('out of reach: the series waits on the phone, then goes', (
    tester,
  ) async {
    final h = harness(fieldHttp: field.http);
    final r = await records(h.store, h.settings);
    await tester.pumpWidget(
      h.app(
        home: ChronoQueueScreen(
          checkin: marshal,
          field: pinned,
          records: r,
          templates: templates,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tapKey(tester, 'queue-decl-$playerDecl');
    await tapKey(tester, 'queue-sticker-qr'); // no sticker: the printed label
    field.offline = true;
    for (final k in ['1', '1', '0']) {
      await tapKey(tester, 'chrono-key-$k');
    }
    await tapKey(tester, 'chrono-record');
    await tapKey(tester, 'chrono-send');
    expect(find.textContaining('Não foi enviado'), findsOneWidget);
    expect(r.unsentSeries(), hasLength(1));
    field.offline = false;
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    await tapKey(tester, 'queue-send-pending');
    expect(field.readings, hasLength(1));
    expect(r.unsentSeries(), isEmpty);
    expect(
      find.text('Por cronografar: 0 · aprovadas: 0 · recusadas: 1'),
      findsOneWidget,
    ); // 1.21 J
  });

  testWidgets(
    'an NFC sticker held to the phone is the replica\'s tag (PKA-3)',
    (tester) async {
      final h = harness(fieldHttp: field.http);
      final r = await records(h.store, h.settings);
      await tester.pumpWidget(
        h.app(
          home: ChronoQueueScreen(
            checkin: marshal,
            field: pinned,
            records: r,
            templates: templates,
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tapKey(tester, 'queue-decl-$playerDecl');
      expect(find.byKey(const Key('queue-sticker-qr')), findsOneWidget);
      expect(h.nfc.calls, contains('start'));
      h.nfc.tap(
        NfcRead(
          uid: Uint8List.fromList([0x04, 0xA2, 0xB3, 0xC4, 0xD5, 0xE6, 0xF7]),
        ),
      );
      await tester.pumpAndSettle();
      expect(h.nfc.calls.last, 'stop');
      final rep = r.replicas.single;
      expect((rep.tagType, rep.tagUid), (TagType.nfc, '04:A2:B3:C4:D5:E6:F7'));
      expect(find.byType(ChronoScreen), findsOneWidget);
    },
  );

  testWidgets('a sticker already on another replica is refused; cancel '
      'registers nothing; no NFC goes straight to the label', (tester) async {
    final h = harness(fieldHttp: field.http);
    final r = await records(h.store, h.settings);
    await r.addReplica(
      Replica(
        replicaId: newUuid(),
        ownerPlayerId: 'p-other',
        type: ReplicaType.aeg,
        replicaClass: 'rifle',
        registeredAt: '2026-01-01T00:00:00Z',
        tagType: TagType.nfc,
        tagUid: '04:A2:B3:C4:D5:E6:F7',
      ),
    );
    await tester.pumpWidget(
      h.app(
        home: ChronoQueueScreen(
          checkin: marshal,
          field: pinned,
          records: r,
          templates: templates,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tapKey(tester, 'queue-decl-$playerDecl');
    h.nfc.tap(
      NfcRead(
        uid: Uint8List.fromList([0x04, 0xA2, 0xB3, 0xC4, 0xD5, 0xE6, 0xF7]),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('queue-sticker-taken')), findsOneWidget);
    await tapKey(tester, 'queue-sticker-cancel');
    expect(r.replicas, hasLength(1)); // nothing registered
    expect(find.byType(ChronoScreen), findsNothing);
    // Without NFC on the phone the printed label is used at once.
    h.nfc.current = NfcState.unavailable;
    await tapKey(tester, 'queue-decl-$playerDecl');
    expect(find.byKey(const Key('queue-sticker-qr')), findsNothing);
    expect(r.replicas.last.tagType, TagType.qr);
  });

  testWidgets('a player without the app, checked in by hand', (tester) async {
    final h = harness(fieldHttp: field.http);
    final r = await records(h.store, h.settings);
    await tester.pumpWidget(
      h.app(
        home: ChronoQueueScreen(
          checkin: marshal,
          field: pinned,
          records: r,
          templates: templates,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tapKey(tester, 'queue-manual');
    await tester.enterText(find.byType(TextField).last, 'Sem Telemóvel');
    await tester.tap(find.text('Fazer o check-in'));
    await tester.pumpAndSettle();
    expect(
      field.rows.values.where((x) => x['display_name'] == 'Sem Telemóvel'),
      hasLength(1),
    );
  });

  testWidgets('a player token is refused: not a marshal', (tester) async {
    field.assign('p-marshalmarsh', role: 'player');
    final h = harness(fieldHttp: field.http);
    final r = await records(h.store, h.settings);
    await tester.pumpWidget(
      h.app(
        home: ChronoQueueScreen(
          checkin: marshal,
          field: pinned,
          records: r,
          templates: templates,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      find.text('Esta lista é só para marshals e para a organização.'),
      findsOneWidget,
    );
    expect(hexEncode(r.publicKey!), hasLength(64));
  });
}
