// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The modes built into the app (lib/modes/builtin_modes.g.dart) are the
// files in modes/, and the catalogue reads them as the simulator does.

import 'dart:io';

import 'package:atalaia_app/modes/builtin_modes.g.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../tool/gen_modes.dart';

void main() {
  test('builtin_modes.g.dart is up to date with modes/ '
      '(python tools/docker_app.py gen)', () {
    final root = Directory('../modes');
    final folders = modeFolders(root);
    expect(builtinModeFiles.keys.toList(), [
      for (final d in folders) d.uri.pathSegments.lastWhere((s) => s != ''),
    ]);
    for (final d in folders) {
      final folder = d.uri.pathSegments.lastWhere((s) => s.isNotEmpty);
      final files = builtinModeFiles[folder]!;
      expect(files.keys.toList(), modeFiles(d), reason: folder);
      for (final f in modeFiles(d)) {
        expect(
          files[f],
          File('${d.path}/$f').readAsStringSync(),
          reason: '$folder/$f',
        );
      }
    }
  });

  final catalog = ModeCatalog.builtin();

  test('every built-in manifest reads; main modes and modifiers', () {
    expect(catalog.modes.length, builtinModeFiles.length);
    expect(
      catalog.mainModes.map((m) => m.id),
      containsAll([
        'org.atalaia.bomb',
        'org.atalaia.domination',
        'org.atalaia.respawn',
        'org.atalaia.kill_confirmed',
        'org.atalaia.player_checkin',
      ]),
    );
    expect(catalog.modifiers.map((m) => m.id), ['org.atalaia.codes']);
    final bomb = catalog.byId('org.atalaia.bomb')!;
    expect(bomb.name('pt'), 'Bomba / Rush');
    expect(bomb.name('en'), 'Bomb / Rush');
    expect(bomb.roles.single.name, 'bomb');
    expect(bomb.roles.single.requires, ['team_input']);
    expect(bomb.role('bomb')!.uses('keypad'), isTrue);
    expect(bomb.screens.keys, containsAll(['countdown', 'standby']));
    final fuse = bomb.params.firstWhere((p) => p.name == 'fuse_s');
    expect(fuse.label('pt'), 'Rastilho (s)');
    expect(fuse.label('en'), 'Fuse (s)');
    expect(catalog.byId('org.atalaia.holdall')!.needsController, isTrue);
    final ms = catalog.byId('org.atalaia.master_satellites')!;
    expect(ms.needsController, isTrue);
    expect(ms.name('pt'), 'Mestre e Satélites');
    expect(ms.name('en'), 'Master and Satellites');
    expect(ms.roles.map((r) => r.name), ['master', 'satellite']);
    expect(
      ms.screens.keys,
      containsAll(['standby', 'captured', 'master_status']),
    );
    expect(catalog.byId('org.atalaia.respawn')!.needsController, isFalse);
  });

  test('every screen template of every mode parses', () {
    final problems = catalog.screenProblems();
    expect(problems, isNotEmpty);
    expect(problems.values.whereType<String>(), isEmpty, reason: '$problems');
  });

  test('parameters: defaults, overrides and their checks', () {
    final bomb = catalog.compose('org.atalaia.bomb');
    final p = bomb.resolveParams({'fuse_s': 60}, const ['red', 'blue']);
    expect(p['fuse_s'], 60);
    expect(p['attackers'], 'red');
    expect(p.containsKey('auto_arm_after_s'), isFalse); // optional, no default
    expect(
      () => bomb.resolveParams({'fuse_s': 5}, const ['red', 'blue']),
      throwsA(isA<ModeException>()),
    );
    expect(
      () => bomb.resolveParams({'attackers': 'green'}, const ['red', 'blue']),
      throwsA(isA<ModeException>()),
    );
    expect(
      () => bomb.resolveParams({'nope': 1}, const ['red', 'blue']),
      throwsA(isA<ModeException>()),
    );
  });

  test('a main mode with a modifier', () {
    final g = catalog.compose('org.atalaia.domination+org.atalaia.codes');
    expect(g.id, 'org.atalaia.domination+org.atalaia.codes');
    expect(g.nodeScript, startsWith('do\n'));
    expect(g.params.map((p) => p.name), contains('codes'));
    expect(g.screen('captured'), isNotNull);
    expect(g.name('pt'), contains(' + '));
    expect(catalog.compose('org.atalaia.codes').id, 'org.atalaia.codes');
    for (final bad in [
      'org.atalaia.codes+org.atalaia.codes',
      'org.atalaia.nope',
      'org.atalaia.bomb+org.atalaia.domination',
      'org.atalaia.bomb+org.atalaia.codes+org.atalaia.codes',
    ]) {
      expect(() => catalog.compose(bad), throwsA(isA<ModeException>()));
    }
  });

  test('the Medic Kit is a role package a prop runs alone', () {
    final medic = catalog.byId('org.atalaia.medic')!;
    expect(medic.kind, 'role');
    expect(medic.isRolePackage, isTrue);
    expect(medic.isModifier, isFalse);
    expect(catalog.mainModes, contains(medic)); // a kit on its own
    expect(medic.name('pt'), 'Ligaduras');
    expect(medic.name('en'), 'Medic Kit');
    expect(medic.role('medic')!.requires, ['nfc', 'team_input']);
    expect(
      medic.screens.keys,
      containsAll([
        'medic_idle',
        'medic_hold',
        'medic_healed',
        'medic_refused',
        'medic_empty',
      ]),
    );
    final kit = catalog.compose('org.atalaia.medic');
    final p = kit.resolveParams(const {}, const ['red', 'blue']);
    expect(p, {
      'heal_hold_s': 10,
      'charges': 5,
      'max_heals_per_player': 2,
      'cooldown_s': 0,
      'lang': 'pt',
    });
    expect(
      kit.resolveParams({'team': 'blue'}, const ['red', 'blue'])['team'],
      'blue',
    );
    // A controller joins a kit with the kit's id alone (modes/README.md).
    expect(
      () => catalog.compose('org.atalaia.domination+org.atalaia.medic'),
      throwsA(
        isA<ModeException>().having(
          (e) => e.message,
          'message',
          contains('role package'),
        ),
      ),
    );
  });
}
