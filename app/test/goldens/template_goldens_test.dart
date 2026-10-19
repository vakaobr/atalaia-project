// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The Flutter renderer drawing the modes' YAML screens with the same data
// as the Field Box's reference images (firmware/esp32/test/test_screens.c,
// firmware/esp32/test/screens/yaml_*.png), at the box's 320x240. The
// golden images are this renderer's own; they match the firmware's
// references in layout and colour, not pixel for pixel (Roboto here,
// Montserrat on the box; Material icons here, LVGL symbols there).

import 'dart:convert';

import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/prop/shell_screens.dart';
import 'package:atalaia_app/ui/template/screen_template.dart';
import 'package:atalaia_app/ui/template/template_view.dart';
import 'package:atalaia_app/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

final catalog = ModeCatalog.builtin();

/// (golden name, mode folder or null for the shell's, screen, data JSON)
const cases = [
  ('bomb_standby', 'bomb', 'standby', '{"arm":"red"}'),
  ('bomb_countdown', 'bomb', 'countdown', '{"left":299}'),
  (
    'bomb_countdown_last_seconds',
    'bomb',
    'countdown',
    '{"left":7,"team":"red"}',
  ),
  ('bomb_defused', 'bomb', 'defused', '{"team":"blue"}'),
  ('bomb_defused_yellow', 'bomb', 'defused', '{"team":"yellow"}'),
  ('bomb_exploded', 'bomb', 'exploded', '{"team":"red"}'),
  ('domination_standby', 'domination', 'standby', '{}'),
  (
    'domination_captured',
    'domination',
    'captured',
    '{"team":"red","points":12,"since":95}',
  ),
  (
    'domination_final_score',
    'domination',
    'final_score',
    '{"owner":"blue","points":40}',
  ),
  ('domination_final_score_no_owner', 'domination', 'final_score', '{}'),
  ('kill_confirmed', 'kill_confirmed', 'tags', '{"error":false}'),
  (
    'kill_confirmed_open',
    'kill_confirmed',
    'tags',
    '{"team":"red","left":14,"message":"Kill confirmed: b1","error":false}',
  ),
  (
    'kill_confirmed_forged',
    'kill_confirmed',
    'tags',
    '{"message":"Forged tag","error":true}',
  ),
  (
    'respawn',
    'respawn',
    'respawn',
    '{"team":"blue","player":"b3","lives":17,"message":"Back in the game","error":false}',
  ),
  (
    'respawn_out',
    'respawn',
    'respawn',
    '{"team":"red","player":"r1","lives":0,"message":"No lives left: team out","error":true}',
  ),
  (
    'checkin',
    'player_checkin',
    'checkin',
    '{"total":5,"counts":"RED 3  BLUE 2","team":"red","message":"Checked in: r2","error":false}',
  ),
  // The Medic Kit's screens, in Portuguese (the default lang).
  ('medic_idle', 'medic', 'medic_idle', '{"remaining":4}'),
  (
    'medic_idle_team_one_left',
    'medic',
    'medic_idle',
    '{"remaining":1,"team":"blue"}',
  ),
  (
    'medic_hold',
    'medic',
    'medic_hold',
    '{"player":"b1","team":"blue","progress":0.6,"left":4,"remaining":4}',
  ),
  (
    'medic_healed',
    'medic',
    'medic_healed',
    '{"player":"b1","team":"blue","remaining":3,"used":1,"max":2}',
  ),
  (
    'medic_refused',
    'medic',
    'medic_refused',
    '{"reason":"limit","message":"Chegaste ao limite de tratamentos","player":"r2","team":"red","remaining":3}',
  ),
  ('medic_empty', 'medic', 'medic_empty', '{}'),
  // Master and Satellites: a free box, a satellite, the master with its status.
  ('master_satellites_standby', 'master_satellites', 'standby', '{}'),
  (
    'master_satellites_captured',
    'master_satellites',
    'captured',
    '{"team":"blue","since":95}',
  ),
  (
    'master_satellites_status',
    'master_satellites',
    'master_status',
    '{"team":"red","since":95,"held":2,"of":3,"points":4}',
  ),
  (
    'master_satellites_status_no_points',
    'master_satellites',
    'master_status',
    '{"team":"yellow","since":3700,"held":1,"of":4,"points":0}',
  ),
  (
    'code_entry',
    null,
    'code_entry',
    '{"title":"ARM","digits":0,"message":"Enter your team code"}',
  ),
  (
    'code_entry_defuse',
    null,
    'code_entry',
    '{"title":"DEFUSE","digits":3,"left":154}',
  ),
  (
    'code_entry_wrong',
    null,
    'code_entry',
    '{"title":"CODE","digits":0,"message":"Wrong code","error":true}',
  ),
  (
    'code_entry_points',
    null,
    'code_entry',
    '{"title":"CODE","digits":4,"message":"+50 points for RED","error":false}',
  ),
];

Future<void> drawAt320x240(WidgetTester tester, Widget child) async {
  tester.view.physicalSize = fieldBoxScreen;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: atalaiaTheme(Brightness.dark),
      home: child,
    ),
  );
}

void main() {
  for (final (name, folder, screen, data) in cases) {
    testWidgets('$name: as the Field Box draws it', (tester) async {
      final mode = folder == null
          ? null
          : catalog.modes.firstWhere((m) => m.folder == folder);
      final source = mode == null
          ? shellScreens[screen]!
          : mode.screens[screen]!;
      final params = mode == null
          ? const <String, Object?>{}
          : catalog.compose(mode.id).resolveParams(const {}, const [
              'red',
              'blue',
            ]);
      await drawAt320x240(
        tester,
        TemplateScreen(
          template: parseScreenTemplate(source),
          data: (jsonDecode(data) as Map).cast<String, Object?>(),
          params: params,
        ),
      );
      await expectLater(
        find.byType(TemplateScreen),
        matchesGoldenFile('images/templates/$name.png'),
      );
    });
  }
}
