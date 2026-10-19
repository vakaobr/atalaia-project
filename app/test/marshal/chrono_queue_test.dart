// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The marshal's "replicas to chrono" list (lib/marshal/chrono_queue.dart)
// against a fake field controller: the counts and the players with pending
// replicas, a declaration with no registered replica chronographed from the
// list (registered and linked by the upload), the signed series sent and
// the list updated, a series kept on the phone while the controller is out
// of reach and sent later, a hand check-in.

import 'dart:io';

import 'package:atalaia_app/checkin/checkin_screen.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/checkin/my_replicas.dart';
import 'package:atalaia_app/chrono/limit_template.dart';
import 'package:atalaia_app/chrono/record_signer.dart';
import 'package:atalaia_app/marshal/chrono_queue.dart';
import 'package:atalaia_app/marshal/marshal_records.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_field.dart';

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
    field.assign('p-marshalmarsh', role: 'marshal');
    marshal = FieldCheckin(
      fieldId: field.fieldId,
      gameId: 42,
      gameName: 'Domingo de manhã',
      playerId: 'p-marshalmarsh',
      token: t.json['token']! as String,
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
