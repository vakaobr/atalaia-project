// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A replica's QR label (lib/ui/replica_label.dart): what the QR holds is
// what the marshal's chrono queue scanner accepts and matches (the same
// classifyCode and byTag it uses), the PNG sticker and the A4 sheet draw
// exactly that QR (read back from the pixels), the label screen keeps the
// screen on and bright, and the player's and the marshal's lists offer it.

import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/checkin/declare_replicas_screen.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/checkin/my_replicas.dart';
import 'package:atalaia_app/chrono/replica.dart';
import 'package:atalaia_app/chrono/replica_registry_ui.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/l10n/strings_en.dart';
import 'package:atalaia_app/l10n/strings_pt.dart';
import 'package:atalaia_app/marshal/marshal_records.dart';
import 'package:atalaia_app/ui/code_kind.dart';
import 'package:atalaia_app/ui/qr_painter.dart';
import 'package:atalaia_app/ui/replica_label.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_field.dart';
import '../support/fakes.dart';

const rid1 = '6f1d2a3b-4c5d-4e6f-8a9b-0c1d2e3f4a5b';
const rid2 = 'a0b1c2d3-e4f5-4a6b-8c7d-9e0f1a2b3c4d';
const rid3 = 'b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5e';
const rid4 = 'c2d3e4f5-a6b7-4c8d-9e0f-1a2b3c4d5e6f';

/// A PNG's size and RGBA pixels.
Future<(int, int, ByteData)> decode(Uint8List png) async {
  final codec = await ui.instantiateImageCodec(png);
  final image = (await codec.getNextFrame()).image;
  final data = (await image.toByteData())!;
  return (image.width, image.height, data);
}

/// The QR modules drawn for a label whose top-left corner is ([ox], [oy]) in
/// the image, read back from the pixels at the middle of each module.
List<List<bool>> readModules(
  (int, int, ByteData) img,
  int n, {
  int ox = 0,
  int oy = 0,
}) {
  final m = labelModulePx(n);
  final o = labelQrOrigin(n);
  return [
    for (var r = 0; r < n; r++)
      [
        for (var c = 0; c < n; c++)
          img.$3.getUint8(
                ((oy + o.dy.toInt() + r * m + m ~/ 2) * img.$1 +
                        ox +
                        o.dx.toInt() +
                        c * m +
                        m ~/ 2) *
                    4,
              ) <
              128,
      ],
  ];
}

List<List<bool>> expectedModules(String text) {
  final q = labelMatrix(text)!;
  return [
    for (var r = 0; r < q.moduleCount; r++)
      [for (var c = 0; c < q.moduleCount; c++) q.isDark(r, c)],
  ];
}

Replica replica(
  String id, {
  String tag = 'x',
  TagType type = TagType.qr,
  String cls = 'rifle',
}) => Replica(
  replicaId: id,
  ownerPlayerId: 'p-abcdefgh2345',
  type: ReplicaType.aeg,
  replicaClass: cls,
  registeredAt: '2026-05-01T10:00:00Z',
  tagType: type,
  tagUid: tag,
);

void main() {
  test('the label text is ATL- and the first eight characters, upper case', () {
    expect(Replica.labelFor(rid1), 'ATL-6F1D2A3B');
    expect(Replica.labelFor(rid2), 'ATL-A0B1C2D3');
    // A label is a QR tag the registry accepts, and no other Atalaia code.
    expect(
      replica(rid1, tag: Replica.labelFor(rid1)).labelText,
      'ATL-6F1D2A3B',
    );
    expect(classifyCode(Replica.labelFor(rid1)), isNull);
    expect(
      replica(rid1, tag: '04:A2:B3:C4', type: TagType.nfc).labelText,
      isNull,
    );
  });

  testWidgets('the sticker PNG is 30 x 30 mm and its QR is the label text', (
    tester,
  ) async {
    await tester.runAsync(() async {
      final png = await renderLabelPng('ATL-6F1D2A3B');
      expect(png.sublist(0, 4), [0x89, 0x50, 0x4e, 0x47]);
      final img = await decode(png);
      expect((img.$1, img.$2), (354, 354)); // 30 mm at 300 dpi
      final n = labelMatrix('ATL-6F1D2A3B')!.moduleCount;
      expect(readModules(img, n), expectedModules('ATL-6F1D2A3B'));
      // The quiet zone is white all round.
      expect(img.$3.getUint8(0), 255);
    });
  });

  testWidgets('what the label holds is what the marshal scanner accepts', (
    tester,
  ) async {
    await tester.runAsync(() async {
      final h = harness();
      final records = MarshalRecords(h.store, h.settings);
      await records.load();
      // The queue registers a declared replica with this tag...
      final registered = replica(rid1, tag: Replica.labelFor(rid1));
      await records.addReplica(registered);
      // ...and a player's phone makes the same text from the registry id.
      final text = Replica.labelFor(rid1);
      final img = await decode(await renderLabelPng(text));
      final n = labelMatrix(text)!.moduleCount;
      expect(readModules(img, n), expectedModules(text));
      // The scanner's own steps: not another Atalaia code, then the tag.
      expect(classifyCode(text), isNull);
      expect(records.byTag(text.trim())?.replicaId, rid1);
      // And nothing personal: only the label text is in the matrix, which
      // is the same QR whoever owns the replica.
      expect(text, isNot(contains('p-abcdefgh2345')));
    });
  });

  testWidgets('a sheet puts the labels in rows, 54 to a page, with guides', (
    tester,
  ) async {
    await tester.runAsync(() async {
      expect((sheetColumns, sheetRows, labelsPerSheet), (6, 9, 54));
      final codes = [for (var i = 0; i < 55; i++) 'ATL-${1000 + i}'];
      final pages = await renderLabelSheets(codes);
      expect(pages.length, 2);
      final first = await decode(pages[0]);
      expect((first.$1, first.$2), (2480, 3508));
      final left = (2480 - 6 * 354) ~/ 2;
      for (final i in [0, 5, 6, 7, 53]) {
        final n = labelMatrix(codes[i])!.moduleCount;
        expect(
          readModules(
            first,
            n,
            ox: left + (i % 6) * 354,
            oy: 118 + (i ~/ 6) * 354,
          ),
          expectedModules(codes[i]),
          reason: 'label $i',
        );
      }
      final second = await decode(pages[1]);
      final n = labelMatrix(codes[54])!.moduleCount;
      expect(
        readModules(second, n, ox: left, oy: 118),
        expectedModules(codes[54]),
      );
    });
  });

  testWidgets('the label screen shows the QR big, bright and awake', (
    tester,
  ) async {
    final sharer = FakeSharer();
    final h2 = harness(share: sharer);
    await tester.pumpWidget(
      h2.app(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              key: const Key('open'),
              onPressed: () =>
                  showLabel(context, 'ATL-6F1D2A3B', subtitle: 'AEG'),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.byKey(const Key('open')));
    await tester.pumpAndSettle();
    expect(
      tester.widget<QrCodeView>(find.byType(QrCodeView)).data,
      'ATL-6F1D2A3B',
    );
    expect(find.text('ATL-6F1D2A3B'), findsOneWidget);
    expect(find.text(ptStrings['label.hint']!), findsOneWidget);
    expect(
      h2.device.calls,
      containsAllInOrder(['keepScreenOn true', startsWith('brightness')]),
    );
    expect(h2.device.calls.any((c) => c.contains('1.0')), isTrue);

    await tester.scrollUntilVisible(
      find.byKey(const Key('label-share')),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.runAsync(() async {
      await tester.tap(find.byKey(const Key('label-share')));
      await Future<void>.delayed(const Duration(milliseconds: 500));
    });
    await tester.pumpAndSettle();
    expect(sharer.shared.single.single.name, 'atalaia-label-ATL-6F1D2A3B.png');
    expect(sharer.shared.single.single.bytes.sublist(1, 4), [0x50, 0x4e, 0x47]);

    h2.device.calls.clear();
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    expect(
      h2.device.calls,
      containsAll(['keepScreenOn false', startsWith('brightness')]),
    );
  });

  testWidgets('a phone that cannot share says so, in the language of the app', (
    tester,
  ) async {
    final h = harness(
      language: AppLanguage.en,
      share: FakeSharer(isAvailable: false),
    );
    await tester.pumpWidget(
      h.app(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () => shareLabels(context, ['ATL-6F1D2A3B']),
              child: const Text('go'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();
    expect(find.text(enStrings['label.share_unavailable']!), findsOneWidget);
  });

  testWidgets("the marshal's registry offers the label of QR tags only", (
    tester,
  ) async {
    final sharer = FakeSharer();
    final h = harness(share: sharer);
    final records = MarshalRecords(h.store, h.settings);
    await records.load();
    await records.addReplica(replica(rid1, tag: Replica.labelFor(rid1)));
    await records.addReplica(
      replica(rid2, tag: '04:A2:B3:C4', type: TagType.nfc),
    );
    await tester.pumpWidget(
      h.app(home: ReplicaRegistryScreen(records: records)),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('label-show-$rid1')), findsOneWidget);
    expect(find.byKey(const Key('label-share-$rid1')), findsOneWidget);
    expect(find.byKey(const Key('label-show-$rid2')), findsNothing);

    await tester.tap(find.byKey(const Key('label-show-$rid1')));
    await tester.pumpAndSettle();
    expect(find.text('ATL-6F1D2A3B'), findsOneWidget);
    expect(
      tester.widget<QrCodeView>(find.byType(QrCodeView)).data,
      records.replicas.first.tagUid,
    );
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();

    await tester.runAsync(() async {
      await tester.tap(find.byKey(const Key('labels-all')));
      await Future<void>.delayed(const Duration(milliseconds: 500));
    });
    await tester.pumpAndSettle();
    // One QR label: a single sticker, not a sheet.
    expect(sharer.shared.single.single.name, startsWith('atalaia-label-'));
  });

  testWidgets("the player's list offers the label once a field registered it", (
    tester,
  ) async {
    final field = FakeField();
    final sharer = FakeSharer();
    final h = harness(share: sharer, fieldHttp: field.http);
    final pinned = PinnedField(
      fieldId: field.fieldId,
      fieldName: field.fieldName,
      caPem: field.pem,
      caSha256: field.sha256Bytes,
      urls: field.urls,
    );
    await h.services.checkins.load();
    await h.services.checkins.saveReplica(
      MyReplica(
        id: 'mine-1',
        type: 'aeg',
        replicaClass: 'rifle',
        replicaIds: {field.fieldId: rid1, 'outro-campo': rid2},
      ),
    );
    await h.services.checkins.saveReplica(
      MyReplica(id: 'mine-2', type: 'gbb', replicaClass: 'cqb'),
    );
    // Declared for this game, not registered by a marshal yet: its label
    // is made from its declaration's id (what a marshal's phone registers
    // it under); another, whose declaration the field has linked to its own
    // id, from that id, which is kept for the next game.
    await h.services.checkins.saveReplica(
      MyReplica(id: 'mine-3', type: 'pistol', replicaClass: 'cqb'),
    );
    await h.services.checkins.saveReplica(
      MyReplica(id: 'mine-4', type: 'dmr', replicaClass: 'dmr'),
    );
    final checkin = FieldCheckin(
      fieldId: field.fieldId,
      gameId: 42,
      gameName: 'Domingo',
      playerId: 'p-abcdefgh2345',
      token: 'x',
      exp: 4102444800,
      status: 'checked_in',
      role: 'player',
      declarations: {'mine-3': rid2, 'mine-4': rid3},
    );
    await tester.pumpWidget(
      h.app(
        home: DeclareReplicasScreen(
          checkin: checkin,
          client: CheckinClient(h.services.fieldHttp(pinned)),
          declared: [
            Declaration(
              declarationId: rid3,
              replicaId: rid4,
              type: 'dmr',
              replicaClass: 'dmr',
            ),
          ],
        ),
      ),
    );
    await tester.pumpAndSettle();
    // Only this field's id counts, and only the registered replica has one.
    expect(find.byKey(const Key('label-show-mine-1')), findsOneWidget);
    expect(find.byKey(const Key('label-share-mine-1')), findsOneWidget);
    expect(find.byKey(const Key('label-show-mine-2')), findsNothing);
    expect(find.byKey(const Key('label-none-mine-2')), findsOneWidget);
    final store = h.services.checkins;
    expect(
      store.labelIdFor(
        checkin,
        store.replicas.firstWhere((r) => r.id == 'mine-3'),
      ),
      rid2,
    );
    // The field's own id, learnt from the declaration the controller gave.
    final mine4 = store.replicas.firstWhere((r) => r.id == 'mine-4');
    expect(mine4.replicaIds[field.fieldId], rid4);
    expect(store.labelIdFor(checkin, mine4), rid4);

    await tester.tap(find.byKey(const Key('label-show-mine-1')));
    await tester.pumpAndSettle();
    expect(
      tester.widget<QrCodeView>(find.byType(QrCodeView)).data,
      'ATL-6F1D2A3B',
    );
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();

    await tester.runAsync(() async {
      await tester.tap(find.byKey(const Key('label-share-mine-1')));
      await Future<void>.delayed(const Duration(milliseconds: 500));
    });
    await tester.pumpAndSettle();
    expect(sharer.shared.single.single.name, 'atalaia-label-ATL-6F1D2A3B.png');
  });
}
