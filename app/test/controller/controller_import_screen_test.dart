// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The registration import on the phone controller's own screen (decision
// PIM-1; lib/controller/controller_import_screen.dart) against the real
// controller API (the same endpoint and rules as the GM console's import
// panel): pick a file, name the source, confirm the basis, check it (nothing
// changes), then import; a file or row the controller refuses is told in
// words, in every language, at 320 px; the HTTP request to the running
// controller is the one the tags' request makes.

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_checkin.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_import_screen.dart';
import 'package:atalaia_app/controller/controller_positions.dart';
import 'package:atalaia_app/controller/controller_screen.dart';
import 'package:atalaia_app/controller/registration_import.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/l10n/strings_de.dart';
import 'package:atalaia_app/l10n/strings_en.dart';
import 'package:atalaia_app/l10n/strings_pt.dart';
import 'package:atalaia_app/l10n/strings_zh_tw.dart';
import 'package:atalaia_app/platform/services.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fakes.dart';
import '../support/recording_radio.dart';
import 'controller_screen_test.dart' show phone, tapKey, onAndroid;

const _csv =
    'display_name,external_ref,team_preference,email\n'
    'Ana,a1,red,ana@example.org\n'
    ',b2,blue,x@example.org\n'
    'Rui,c3,green,rui@example.org\n';

PickedFile _file(String name, String text) =>
    PickedFile(name, Uint8List.fromList(utf8.encode(text)));

void main() {
  late ControllerEngine engine;
  late ControllerApi api;
  late int gameId;
  final calls = <Map<String, Object?>>[];
  final limits = File(
    'lib/chrono/limit_templates/portugal.yaml',
  ).readAsStringSync();

  setUp(() {
    engine = ControllerEngine(
      transport: RecordingRadio(),
      wallSeconds: () => 1800007200.0,
    );
    ControllerCheckin(engine, CheckinConfig(limitsYaml: limits, utcDay: true));
    ControllerPositions(engine);
    api = ControllerApi(engine, gmToken: 'g', readToken: 'r');
    final r = api.handle(
      'POST',
      Uri.parse('/api/v1/games'),
      authorization: 'Bearer g',
      body: jsonEncode({
        'name': 'Domingo',
        'mode_id': 'org.atalaia.domination',
        'teams': ['red', 'blue'],
      }),
      client: 'local',
    );
    gameId = (r.body! as Map)['id']! as int;
    calls.clear();
  });

  /// The request the screen makes, answered by the real API (as the HTTP
  /// request to the running controller is).
  Future<Map<String, Object?>> request(Map<String, Object?> body) async {
    calls.add(body);
    final r = api.handle(
      'POST',
      Uri.parse('/api/v1/games/$gameId/checkins/import'),
      authorization: 'Bearer g',
      body: jsonEncode(body),
      client: 'local',
    );
    final json = (r.body! as Map).cast<String, Object?>();
    if (r.status == 200) return json;
    throw ImportRequestError(
      json['detail']! as String,
      line: json['line'] as int?,
    );
  }

  Future<void> open(WidgetTester tester, Harness h) async {
    await tester.pumpWidget(
      h.app(
        home: ControllerImportScreen(
          gameId: gameId,
          gameName: 'Domingo',
          request: request,
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  Future<void> tapKeyHere(WidgetTester tester, String key) async {
    final f = find.byKey(Key(key));
    await tester.ensureVisible(f);
    await tester.pumpAndSettle();
    await tester.tap(f);
    await tester.pumpAndSettle();
  }

  bool enabled(WidgetTester tester, String key) =>
      tester.widget<FilledButton>(find.byKey(Key(key))).onPressed != null;

  for (final lang in AppLanguage.values) {
    testWidgets('pick, check, import, with the refusals in words '
        '(${lang.code})', (tester) async {
      // 320 px wide, and tall enough for the whole list to be built.
      tester.view.physicalSize = const Size(320, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final s = Strings(lang);
      final picker = FakePicker(_file('inscricoes.csv', _csv));
      final h = harness(language: lang, picker: picker);
      await open(tester, h);
      // Nothing to check before a file is picked.
      expect(enabled(tester, 'import-check'), isFalse);
      expect(enabled(tester, 'import-run'), isFalse);
      expect(find.text(s.t('ctl_import.no_file')), findsOneWidget);

      await tapKeyHere(tester, 'import-pick');
      expect(picker.asked.single.$2, importMaxBytes);
      expect(
        find.text(s.t('ctl_import.picked', {'name': 'inscricoes.csv'})),
        findsOneWidget,
      );
      expect(enabled(tester, 'import-check'), isTrue);
      // The check comes first, and the basis must be confirmed.
      expect(enabled(tester, 'import-run'), isFalse);

      await tapKeyHere(tester, 'import-check');
      expect(calls.single, {
        'format': 'csv',
        'data': _csv,
        'source': 'csv',
        'dry_run': true,
        'basis_confirmed': false,
      });
      expect(
        find.textContaining(s.t('ctl_import.checked')),
        findsOneWidget,
        reason: 'the dry run says nothing was imported yet',
      );
      // The per-row result (a CSV's rows count from its header, line 1): one
      // new, two refused with their reasons.
      expect(find.byKey(const Key('import-row-2')), findsOneWidget);
      expect(
        find.descendant(
          of: find.byKey(const Key('import-row-3')),
          matching: find.text(s.t('ctl_import.codes.display_name_invalid')),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: find.byKey(const Key('import-row-4')),
          matching: find.text(s.t('ctl_import.codes.team_preference_invalid')),
        ),
        findsOneWidget,
      );
      expect(
        find.text(s.t('ctl_import.ignored', {'names': 'email'})),
        findsOneWidget,
        reason: 'the other column is only named',
      );
      expect(find.textContaining('ana@example.org'), findsNothing);
      expect(
        find.textContaining(
          s.t('ctl_import.counts', {
            'rows': 3,
            'created': 1,
            'updated': 0,
            'unchanged': 0,
            'skipped': 0,
            'refused': 2,
          }),
        ),
        findsOneWidget,
      );
      // Still not importable: the basis is not confirmed.
      expect(enabled(tester, 'import-run'), isFalse);
      await tapKeyHere(tester, 'import-basis');
      expect(enabled(tester, 'import-run'), isTrue);
      // Another source is another list: checked again first.
      await tester.enterText(find.byKey(const Key('import-source')), 'other');
      await tester.pumpAndSettle();
      expect(enabled(tester, 'import-run'), isFalse);
      await tapKeyHere(tester, 'import-check');
      expect(calls.last['source'], 'other');
      expect(calls.last['basis_confirmed'], isTrue);
      expect(enabled(tester, 'import-run'), isTrue);

      await tapKeyHere(tester, 'import-run');
      expect(calls.last['dry_run'], isFalse);
      expect(calls.last['basis_confirmed'], isTrue);
      expect(calls, hasLength(3));
      expect(
        find.text(s.t('ctl_import.done', {'created': 1, 'updated': 0})),
        findsOneWidget,
      );
      expect(find.textContaining(s.t('ctl_import.imported')), findsOneWidget);
      // Once imported, a second import needs a new check.
      expect(enabled(tester, 'import-run'), isFalse);
      expect(tester.takeException(), isNull);
    });
  }

  for (final lang in AppLanguage.values) {
    testWidgets('320 px wide and the accessibility guidelines (${lang.code})', (
      tester,
    ) async {
      // 320 px wide; tall, so that the whole list is built.
      tester.view.physicalSize = const Size(320, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final handle = tester.ensureSemantics();
      final h = harness(
        language: lang,
        picker: FakePicker(_file('inscricoes.csv', _csv)),
      );
      await open(tester, h);
      await tapKeyHere(tester, 'import-pick');
      await tapKeyHere(tester, 'import-basis');
      await tapKeyHere(tester, 'import-check');
      expect(tester.takeException(), isNull);
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      handle.dispose();
    });
  }

  testWidgets('a file the controller refuses is told in words, with its line', (
    tester,
  ) async {
    await phone(tester);
    final s = Strings(AppLanguage.en);
    final h = harness(
      language: AppLanguage.en,
      picker: FakePicker(
        _file('x.csv', 'display_name,external_ref\n"Ana,a1\n'),
      ),
    );
    await open(tester, h);
    await tapKeyHere(tester, 'import-pick');
    await tapKeyHere(tester, 'import-check');
    expect(find.byKey(const Key('import-error')), findsOneWidget);
    expect(
      find.textContaining(s.t('ctl_import.codes.csv_invalid')),
      findsOneWidget,
    );

    // A list without the name column.
    (h.picker! as FakePicker).next = _file('y.csv', 'external_ref\na1\n');
    await tapKeyHere(tester, 'import-pick');
    await tapKeyHere(tester, 'import-check');
    expect(
      find.text(s.t('ctl_import.codes.display_name_column_missing')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('import-result')), findsNothing);
  });

  testWidgets(
    'a file that is not UTF-8, or too large, never leaves the phone',
    (tester) async {
      await phone(tester);
      final s = Strings(AppLanguage.en);
      final picker = FakePicker(
        PickedFile('latin.csv', Uint8List.fromList([0x41, 0xe7, 0xff, 0x0a])),
      );
      final h = harness(language: AppLanguage.en, picker: picker);
      await open(tester, h);
      await tapKeyHere(tester, 'import-pick');
      expect(
        find.text(s.t('ctl_import.codes.encoding_invalid')),
        findsOneWidget,
      );
      expect(enabled(tester, 'import-check'), isFalse);
      picker.next = PickedFile('big.csv', Uint8List(importMaxBytes + 1));
      await tapKeyHere(tester, 'import-pick');
      expect(find.text(s.t('ctl_import.codes.too_large')), findsOneWidget);
      expect(enabled(tester, 'import-check'), isFalse);
      expect(calls, isEmpty);
    },
  );

  testWidgets(
    'a JSON file is read as JSON; a cancelled chooser changes nothing',
    (tester) async {
      await phone(tester);
      final picker = FakePicker(null);
      final h = harness(language: AppLanguage.en, picker: picker);
      await open(tester, h);
      await tapKeyHere(tester, 'import-pick');
      expect(enabled(tester, 'import-check'), isFalse);
      picker.next = _file('List.JSON', '[{"display_name":"Ana"}]');
      await tapKeyHere(tester, 'import-pick');
      await tapKeyHere(tester, 'import-check');
      expect(calls.single['format'], 'json');
      expect(find.byKey(const Key('import-row-1')), findsOneWidget);
    },
  );

  testWidgets('a phone with no file chooser says so', (tester) async {
    await phone(tester);
    final h = harness(language: AppLanguage.en);
    await open(tester, h);
    await tapKeyHere(tester, 'import-pick');
    expect(find.byKey(const Key('import-no-picker')), findsOneWidget);
    expect(enabled(tester, 'import-check'), isFalse);
  });

  testWidgets('a controller out of reach is said', (tester) async {
    await phone(tester);
    final s = Strings(AppLanguage.en);
    final h = harness(
      language: AppLanguage.en,
      picker: FakePicker(_file('a.csv', _csv)),
    );
    await tester.pumpWidget(
      h.app(
        home: ControllerImportScreen(
          gameId: 1,
          gameName: 'Domingo',
          request: (_) async => throw ImportRequestError('offline'),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tapKeyHere(tester, 'import-pick');
    await tapKeyHere(tester, 'import-check');
    expect(find.text(s.t('ctl_import.offline')), findsOneWidget);
  });

  testWidgets('the controller screen opens it for the live game', (
    tester,
  ) async {
    await phone(tester);
    final h = harness(
      language: AppLanguage.en,
      picker: FakePicker(_file('a.csv', _csv)),
    );
    final s = Strings(AppLanguage.en);
    await tester.pumpWidget(h.app(home: const ControllerScreen()));
    await tester.pumpAndSettle();
    await tapKey(tester, 'ctl-start');
    expect(find.byKey(const Key('ctl-import')), findsNothing);
    h.controllerRuns.single.emit({
      'game': {'id': 1, 'name': 'Domingo', 'state': 'running'},
    });
    await tester.pumpAndSettle();
    await tapKey(tester, 'ctl-import');
    expect(find.byType(ControllerImportScreen), findsOneWidget);
    expect(find.text(s.t('ctl_import.title')), findsWidgets);
    await h.services.controller.stop();
  }, variant: onAndroid);

  test('the console texts for files, rows and results are all here', () {
    final console = <String, Map<String, dynamic>>{
      for (final (code, _) in [
        ('en', enStrings),
        ('pt', ptStrings),
        ('de', deStrings),
        ('zh-tw', zhTwStrings),
      ])
        code:
            (jsonDecode(
                      File(
                        '../controller/console/src/i18n/$code.json',
                      ).readAsStringSync(),
                    )
                    as Map<String, dynamic>)['checkin_import']
                as Map<String, dynamic>,
    };
    final tables = {
      'en': enStrings,
      'pt': ptStrings,
      'de': deStrings,
      'zh-tw': zhTwStrings,
    };
    for (final lang in tables.keys) {
      for (final group in ['codes', 'results']) {
        for (final k in (console['en']![group] as Map).keys) {
          expect(
            tables[lang]!['ctl_import.$group.$k'],
            (console[lang]![group] as Map)[k],
            reason: '$lang $group $k',
          );
        }
      }
    }
    // And every other key of the screen exists in the four languages.
    for (final k in enStrings.keys.where(
      (k) => k.startsWith('ctl_import.') || k.startsWith('ctl.import'),
    )) {
      for (final lang in tables.keys) {
        expect(tables[lang]!.containsKey(k), isTrue, reason: '$lang $k');
      }
    }
  });
}
