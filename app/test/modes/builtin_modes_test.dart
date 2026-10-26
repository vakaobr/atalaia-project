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
      containsAll(['neutral', 'captured', 'master_status']),
    );
    final hack = catalog.byId('org.atalaia.hacking_terminal')!;
    expect(hack.needsController, isFalse);
    expect(hack.name('pt'), 'Hackeia o terminal');
    expect(hack.name('en'), 'Hacking Terminal');
    expect(hack.roles.single.name, 'terminal');
    expect(hack.roles.single.requires, ['keypad']);
    expect(hack.role('terminal')!.uses('team_input'), isTrue);
    expect(
      hack.screens.keys,
      containsAll(['hack_code', 'hack_wires', 'hack_sequence', 'hack_solved']),
    );
    expect(
      hack.params.firstWhere((p) => p.name == 'lockout_s').label('pt'),
      'Segundos de bloqueio depois de uma resposta errada (0: sem bloqueio)',
    );
    final vip = catalog.byId('org.atalaia.vip_payload')!;
    expect(vip.needsController, isTrue);
    expect(vip.name('pt'), 'VIP / Carga');
    expect(vip.roles.map((r) => r.name), ['checkpoint', 'payload']);
    expect(vip.role('payload')!.requires, ['gps']);
    expect(vip.role('payload')!.uses('team_input'), isFalse);
    expect(
      vip.screens.keys,
      containsAll(['checkpoint_free', 'checkpoint_held', 'payload']),
    );
    // Money Factory: factories and banks with NFC; an Android prop with NFC
    // can be either (a bank needs no team buttons).
    final money = catalog.byId('org.atalaia.money_factory')!;
    expect(money.needsController, isTrue);
    expect(money.name('pt'), 'Fábrica de Dinheiro');
    expect(money.name('en'), 'Money Factory');
    expect(money.roles.map((r) => r.name), ['factory', 'bank']);
    expect(money.role('factory')!.requires, ['nfc', 'team_input']);
    expect(money.role('bank')!.requires, ['nfc']);
    expect(money.role('bank')!.uses('team_input'), isFalse);
    expect(
      money.screens.keys,
      containsAll([
        'neutral',
        'captured',
        'factory',
        'collected',
        'bank',
        'deposited',
        'refused',
      ]),
    );
    // Progressive Domination: any box of the game is a zone; the controller
    // picks the active one (a game with it needs a controller).
    final pd = catalog.byId('org.atalaia.progressive_domination')!;
    expect(pd.needsController, isTrue);
    expect(pd.name('pt'), 'Domínio Progressivo');
    expect(pd.name('en'), 'Progressive Domination');
    expect(pd.name('de'), 'Progressive Domination');
    expect(pd.name('zh-tw'), '漸進佔點');
    expect(pd.roles.map((r) => r.name), ['zone']);
    expect(pd.role('zone')!.requires, ['team_input']);
    expect(
      pd.screens.keys,
      containsAll(['inactive', 'neutral', 'captured', 'completed']),
    );
    expect(
      pd.params.firstWhere((p) => p.name == 'complete_min').label('pt'),
      'Minutos que uma equipa mantém a caixa ativa para a completar',
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
      'lang': '',
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

  test(
    'the objectives package runs alone; a scenario never runs on a prop',
    () {
      final objectives = catalog.byId('org.atalaia.objectives')!;
      expect(objectives.isRolePackage, isTrue);
      expect(objectives.name('pt'), 'Objetivos');
      expect(objectives.roles.map((r) => r.name), ['objective', 'bomb_site']);
      expect(objectives.role('objective')!.uses('keypad'), isTrue);
      expect(objectives.params, isEmpty);
      expect(
        objectives.screens.keys,
        containsAll([
          'obj_status',
          'obj_capture',
          'obj_code',
          'obj_tags',
          'obj_bomb',
        ]),
      );
      // A join names the objectives package alone: what the node runs.
      final node = catalog.compose('org.atalaia.objectives');
      expect(node.nodeScript, objectives.nodeScript);
      expect(node.resolveParams(const {}, const ['red', 'blue']), isEmpty);
      // A scenario package (uploaded to a controller, never built in) reads,
      // but is no game for a prop.
      final dir = Directory('../modes/objectives/tests/fixtures/foxhound');
      final foxhound = ModeManifest.parse('foxhound', {
        for (final f in ['mode.yaml', 'field.lua'])
          f: File('${dir.path}/$f').readAsStringSync(),
      });
      expect(foxhound.isScenario, isTrue);
      expect(foxhound.roles, isEmpty);
      expect(foxhound.nodeScript, '');
      expect(catalog.modes.where((m) => m.isScenario), isEmpty);
      final withIt = ModeCatalog([...catalog.modes, foxhound]);
      expect(withIt.mainModes, isNot(contains(foxhound)));
      for (final id in [
        'org.club.foxhound',
        'org.club.foxhound+org.atalaia.objectives',
      ]) {
        expect(
          () => withIt.compose(id),
          throwsA(
            isA<ModeException>().having(
              (e) => e.message,
              'message',
              contains('runs on the field controller'),
            ),
          ),
        );
      }
      expect(
        () => ModeManifest.parse('bad', {
          'mode.yaml': 'id: org.t.bad\nversion: 1\nkind: scenario\n',
          'node.lua': '-- no',
          'field.lua': '-- ok',
        }),
        throwsA(isA<ModeException>()),
      );
    },
  );
}
