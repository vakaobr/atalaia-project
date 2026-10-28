// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The field card written by the phone controller's own NFC (slice S7c of
// PE24, decision PE24-93): the warning first, then the card the controller
// makes (recorded with its adoptions) written as one NDEF record that reads
// back as this field's card; NFC off or a write that fails says why. In
// every language, at a phone's width.

import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_adoption.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_boxes_screen.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/platform/services.dart';
import 'package:atalaia_app/protocol/field_card.dart';
import 'package:atalaia_app/protocol/firmware_release.dart';
import 'package:atalaia_app/security/ndef.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';

final joinKey = Uint8List.fromList(List.generate(32, (i) => i));

void main() {
  late ControllerAdoption adoption;

  setUp(() {
    final engine = ControllerEngine()..joinKey = joinKey;
    adoption = ControllerAdoption(engine);
  });

  test("the controller's card becomes one NDEF record of the field's card", () {
    final message = fieldCardMessageFrom(adoption.fieldCard());
    final payload = payloadFromNdefMessage(message, fieldCardNdefType)!;
    final card = decodeFieldCard(payload);
    expect(card.joinKey, joinKey);
    expect(card.name, 'Atalaia');
    expect(card.fingerprint, '604A-0A95');
    expect(
      () => fieldCardMessageFrom({'ndef_tag_hex': '0300fe'}),
      throwsFormatException,
    );
    expect(adoption.records().single['result'], 'card_made');
  });

  for (final lang in AppLanguage.values) {
    testWidgets('the warning, then the card written (${lang.code})', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(320, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final h = harness(language: lang);
      final s = Strings(lang);
      await tester.pumpWidget(
        h.app(
          home: Scaffold(
            body: ListView(
              children: [
                FieldCardTile(makeCard: () async => adoption.fieldCard()),
              ],
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text(s.t('ctl.card_hint')), findsOneWidget);

      // Cancelled at the warning: nothing written.
      await tester.tap(find.byKey(const Key('ctl-card-write')));
      await tester.pumpAndSettle();
      expect(find.text(s.t('ctl.card_warn')), findsOneWidget);
      await tester.tap(find.text(s.t('common.cancel')));
      await tester.pumpAndSettle();
      expect(h.nfc.written, isEmpty);

      // NFC off: said, nothing written.
      h.nfc.current = NfcState.off;
      await tester.tap(find.byKey(const Key('ctl-card-write')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('ctl-card-go')));
      await tester.pumpAndSettle();
      expect(find.text(s.t('nfc.off')), findsOneWidget);
      expect(h.nfc.written, isEmpty);

      // Written: the card held to the phone.
      h.nfc.current = NfcState.ready;
      await tester.tap(find.byKey(const Key('ctl-card-write')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('ctl-card-go')));
      await tester.pump();
      expect(find.text(s.t('tags.hold')), findsOneWidget);
      h.nfc.tapToWrite(Uint8List.fromList([1, 2, 3, 4]));
      await tester.pumpAndSettle();
      expect(
        find.text(s.t('ctl.card_done', {'fingerprint': '604A-0A95'})),
        findsOneWidget,
      );
      final card = decodeFieldCard(
        payloadFromNdefMessage(h.nfc.written.single, fieldCardNdefType)!,
      );
      expect(card.joinKey, joinKey);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('a write that fails says why', (tester) async {
    final h = harness(language: AppLanguage.en);
    final s = Strings(AppLanguage.en);
    await tester.pumpWidget(
      h.app(
        home: Scaffold(
          body: FieldCardTile(makeCard: () async => throw StateError('down')),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ctl-card-write')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ctl-card-go')));
    await tester.pumpAndSettle();
    expect(find.text(s.t('ctl.card_failed')), findsOneWidget);
    expect(h.nfc.written, isEmpty);
  });

  testWidgets("the firmware release keys: kept in the app's settings", (
    tester,
  ) async {
    final h = harness(language: AppLanguage.en);
    final s = Strings(AppLanguage.en);
    final given = <List<String>>[];
    await tester.pumpWidget(
      h.app(
        home: Scaffold(
          body: FirmwareKeysTile(onChanged: (k) async => given.add(k)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    // The default is the project's two release keys (docs/community/keys.md).
    expect(h.settings.firmwareKeys, projectReleaseKeys);
    expect(find.text(s.t('ctl.fw_keys_set', {'n': 2})), findsOneWidget);
    // Not a key: refused, nothing kept.
    await tester.tap(find.byKey(const Key('ctl-fw-keys')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('ctl-fw-keys-field')),
      'not-a-key',
    );
    await tester.tap(find.text(s.t('common.save')));
    await tester.pumpAndSettle();
    expect(find.text(s.t('ctl.fw_keys_bad')), findsOneWidget);
    expect(h.settings.firmwareKeys, projectReleaseKeys);
    expect(given, isEmpty);
    // Two keys, one per line.
    const a = '11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo=';
    const b = 'PUAXw+hDiVqStwqnTRt+vJyYLM8uxJaMwM1V8Sr0Zgw=';
    await tester.tap(find.byKey(const Key('ctl-fw-keys')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('ctl-fw-keys-field')),
      '$a\n$b',
    );
    await tester.tap(find.text(s.t('common.save')));
    await tester.pumpAndSettle();
    expect(h.settings.firmwareKeys, [a, b]);
    expect(given, [
      [a, b],
    ]);
    expect(find.text(s.t('ctl.fw_keys_set', {'n': 2})), findsOneWidget);
  });
}
