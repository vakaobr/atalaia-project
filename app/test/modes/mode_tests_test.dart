// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Every mode's tests (modes/*/tests/*.yaml) on the real core through the
// Dart bridge, the same files `python -m atalaia_sim test` runs: each test
// once with the nodes called directly and once with each node in its own
// game loop isolate. Each mode's screen templates are checked by the core's
// parser, as the simulator does. The schema and LoRa-size checks of every
// event use protocol/schema/events.yaml and the core's codec.

import 'dart:io';

import 'package:atalaia_app/ffi/bindings.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/event_schema.dart';
import '../support/mode_runner.dart';

void main() {
  final core = AtalaiaCore.open(coreLibraryPath());
  final schema = EventSchema.load();
  final modes = [for (final d in findModes(Directory('../modes'))) loadMode(d)];

  test('every mode and every test file is found', () {
    final ids = modes.map((m) => m.folder).toSet();
    // At least the built-in modes; a new mode folder is picked up on its own.
    expect(
      ids,
      containsAll(['bomb', 'domination', 'codes', 'holdall', 'laststand']),
    );
    final files = Directory('../modes')
        .listSync(recursive: true)
        .whereType<File>()
        .where(
          (f) => f.parent.path.endsWith('tests') && f.path.endsWith('.yaml'),
        );
    expect(modes.expand((m) => m.tests).length, files.length);
    expect(modes.firstWhere((m) => m.folder == 'domination').tests, isNotEmpty);
    expect(modes.firstWhere((m) => m.folder == 'bomb').tests, isNotEmpty);
  });

  for (final mode in modes) {
    group(mode.id, () {
      if (mode.screens.isNotEmpty) {
        test('${mode.screens.length} screen template(s)', () {
          expect(checkScreens(core, mode), isEmpty);
        });
      }
      for (final file in mode.tests) {
        for (final via in Via.values) {
          final stem = file.uri.pathSegments.last;
          test('$stem (${via.name})', () async {
            final r = await runTest(core, schema, mode, file, via);
            if (!r.passed) fail('$r');
          });
        }
      }
    });
  }
}
