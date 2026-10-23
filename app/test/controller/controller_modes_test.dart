// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Slice S7b of PE24 beyond the shared contract cases: the mode registry and
// its composition (controller_modes.dart, the simulator's compose), uploads
// and presets kept across a restart, signed packages from a registry index
// on the phone with its revocations (controller_signed_modes.dart), the
// branding images' clean-up, the [modes] settings' checks and JSON, and
// the join's keys 16 and 17 from the engine.

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_branding.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_mode_fetch.dart';
import 'package:atalaia_app/controller/controller_modes.dart';
import 'package:atalaia_app/controller/controller_modes_screen.dart';
import 'package:atalaia_app/controller/controller_scenarios.dart';
import 'package:atalaia_app/controller/controller_signed_modes.dart';
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/recording_radio.dart';
import '../support/vectors.dart';

const _runner = {
  'mode.yaml':
      'id: org.test.runner\nversion: 0.1.0\nkind: role\nname: Runner\n'
      'roles:\n  runner: { requires: [team_input] }\n'
      'params:\n  laps: { type: int, min: 1, max: 9, default: 3, label: Laps }\n',
  'node.lua': 'on("team_input.press", function(e) end)\n',
};

ControllerMode _mode(String id, String kind, {Map<String, Object?>? roles}) =>
    modeFromManifest(
      {
        'id': id,
        'version': '1.0.0',
        'kind': kind,
        'roles': ?roles,
        'params': {
          '${id.split('.').last}_p': {'type': 'int', 'default': 1},
        },
      },
      id.split('.').last,
      nodeScript: '-- $id\n',
    );

void main() {
  late AtalaiaCore core;
  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  group('composition (atalaia_sim.mode compose)', () {
    final main = _mode(
      'org.t.main',
      'mode',
      roles: {
        'zone': {'requires': <Object?>[]},
      },
    );
    final mod = _mode('org.t.mod', 'modifier');
    final role = _mode(
      'org.t.medic',
      'role',
      roles: {
        'medic': {'requires': <Object?>[]},
      },
    );
    final scen = modeFromManifest(
      {'id': 'org.t.scen', 'version': '1', 'kind': 'scenario'},
      'scen',
      fieldScript: '-- scenario\n',
    );

    test('a main mode, a modifier and a role package', () {
      final m = composeModes(main, [mod, role]);
      expect(m.id, 'org.t.main+org.t.mod+org.t.medic');
      expect(m.parts, ['org.t.main', 'org.t.mod', 'org.t.medic']);
      expect(m.roles.keys, containsAll(['zone', 'medic']));
      expect(m.nodeModeId('zone'), 'org.t.main+org.t.mod');
      expect(m.nodeModeId('medic'), 'org.t.medic');
      final params = m.resolveParams({}, ['red', 'blue']);
      expect(m.paramsFor('medic', params), {'medic_p': 1});
      expect(m.paramsFor('zone', params), {'main_p': 1, 'mod_p': 1});
      expect(m.nodeScript, contains('do\n-- org.t.main'));
    });

    test(
      'a scenario leads, before an optional main mode and role packages',
      () {
        final m = composeModes(scen, [main, role]);
        expect(m.id, 'org.t.scen+org.t.main+org.t.medic');
        expect(m.fieldScript, '-- scenario\n');
        expect(m.nodeModeId('zone'), 'org.t.main');
        expect(composeModes(scen, [role]).mainId, '');
        expect(
          () => composeModes(scen, const []),
          throwsA(isA<ModeException>()),
        );
        expect(() => composeModes(scen, [main]), throwsA(isA<ModeException>()));
        expect(
          () => composeModes(scen, [mod, role]),
          throwsA(isA<ModeException>()),
        );
      },
    );

    test('what does not compose', () {
      expect(() => composeModes(role, [mod]), throwsA(isA<ModeException>()));
      expect(() => composeModes(main, [main]), throwsA(isA<ModeException>()));
      expect(() => composeModes(main, [scen]), throwsA(isA<ModeException>()));
      expect(
        () => composeModes(main, [mod, mod]),
        throwsA(isA<ModeException>()),
      );
    });

    test(
      'parameters as Python checks them: a value given is checked, null too',
      () {
        expect(
          () => main.resolveParams({'main_p': null}, const []),
          throwsA(isA<ModeException>()),
        );
        expect(
          () => main.resolveParams({'main_p': true}, const []),
          throwsA(isA<ModeException>()),
        );
        expect(
          () => main.resolveParams({'main_p': 1.0}, const []),
          throwsA(isA<ModeException>()),
        );
      },
    );
  });

  test('uploads and presets outlive a restart; a broken upload is refused', () {
    final dir = Directory.systemTemp.createTempSync('atalaia-modes-');
    addTearDown(() => dir.deleteSync(recursive: true));
    var engine = ControllerEngine(
      store: FileControllerStore(dir),
      core: core,
      transport: RecordingRadio(),
    );
    engine.modes.install(_runner);
    engine.modes.savePreset('Run', 'org.test.runner', {'laps': 4});
    expect(
      () => engine.modes.install({..._runner, 'node.lua': 'on(('}),
      throwsA(isA<ModeException>()),
    );
    expect(
      () => ControllerModes(MemoryControllerStore()).install(_runner),
      throwsA(isA<ModeException>()), // no core: scripts cannot be checked
    );
    engine.close();
    engine = ControllerEngine(
      store: FileControllerStore(dir),
      core: core,
      transport: RecordingRadio(),
    );
    expect(engine.modes.package('org.test.runner')?.builtin, isFalse);
    expect(engine.modes.presets().single['params'], {'laps': 4});
    final game = engine.createGame({
      'name': 'x',
      'mode_id': 'org.atalaia.domination+org.test.runner',
      'preset_id': null,
    });
    expect(game['params'], containsPair('laps', 3));
    engine.close();
  });

  group('signed packages from a registry index on the phone', () {
    final v = loadVectors('mode_package.json');
    final key = (v['signing_key'] as Map)['public_key_b64'] as String;
    final archive = hexDecode((v['archive'] as Map)['hex'] as String);

    (ControllerSignedModes, ControllerEngine) setUp(
      Directory dir, {
      List<String> revoked = const [],
      bool revokedFile = false,
    }) {
      File('${dir.path}/index.json').writeAsStringSync(jsonEncode(v['index']));
      Directory('${dir.path}/packages').createSync();
      File(
        '${dir.path}/packages/org.example.relay-1.2.0-rc.1.tar',
      ).writeAsBytesSync(archive);
      if (revokedFile) {
        File(
          '${dir.path}/revoked.json',
        ).writeAsStringSync(jsonEncode(v['revoked']));
      }
      final engine = ControllerEngine(core: core, transport: RecordingRadio());
      final signed = ControllerSignedModes(
        engine.modes,
        ModesConfig(
          keys: [key],
          revoked: revoked,
          index: '${dir.path}/index.json',
        ),
      );
      engine.signedModes = signed;
      return (signed, engine);
    }

    test('listed, installed, then shown as installed and trusted', () async {
      final dir = Directory.systemTemp.createTempSync('atalaia-index-');
      addTearDown(() => dir.deleteSync(recursive: true));
      final (signed, engine) = setUp(dir);
      var status = await signed.status();
      final entry = (((status['index']! as Map)['entries']) as List).single;
      expect((entry as Map)['state'], 'available');
      expect(entry['verified'], isTrue);
      final out = await signed.installFromIndex(
        'org.example.relay',
        '1.2.0-rc.1',
      );
      expect((out['signed']! as Map)['source'], 'index');
      expect((out['signed']! as Map)['verified'], isTrue);
      expect(engine.modes.archive('org.example.relay'), archive);
      status = await signed.status();
      expect(
        (((status['index']! as Map)['entries']! as List).single
            as Map)['state'],
        'installed',
      );
      expect(
        () => signed.installFromIndex('org.example.relay', '9.9.9'),
        throwsA(isA<ModeException>()),
      );
    });

    test("the index's revoked.json revokes its key", () async {
      final dir = Directory.systemTemp.createTempSync('atalaia-index-');
      addTearDown(() => dir.deleteSync(recursive: true));
      final (signed, _) = setUp(dir, revokedFile: true);
      final status = await signed.status();
      expect(status['revoked'], ['21fe31dfa154a261']);
      expect(
        (((status['index']! as Map)['entries']! as List).single
            as Map)['state'],
        'revoked',
      );
      await expectLater(
        signed.installFromIndex('org.example.relay', '1.2.0-rc.1'),
        throwsA(isA<ModeException>()),
      );
    });

    test('an index that cannot be read offers nothing', () async {
      final engine = ControllerEngine(core: core, transport: RecordingRadio());
      final signed = ControllerSignedModes(
        engine.modes,
        const ModesConfig(index: 'https://registry.example/index.json'),
        fetch: (url, limit) async => throw FetchError('offline'),
      );
      final status = await signed.status(refresh: true);
      expect((status['index']! as Map)['error'], 'offline');
      expect((status['index']! as Map)['entries'], isEmpty);
    });
  });

  test('join keys 16 and 17 from the engine, and the mode fetch it tracks', () {
    final v = loadVectors('mode_package.json');
    final key = (v['signing_key'] as Map)['public_key_b64'] as String;
    final engine = ControllerEngine(core: core, transport: RecordingRadio())
      ..joinKey = Uint8List(32)
      ..caSha256 = Uint8List(32)
      ..linkUrls = const ['https://192.0.2.1:8443'];
    ControllerScenarios(engine);
    final fetch = ControllerModeFetch(engine, [key]);
    engine.createGame({'name': 'g', 'mode_id': 'org.atalaia.domination'});
    expect(fetch.offer('org.atalaia.domination')['why'], 'firmware');
    final out = engine.issueJoin({'role': 'zone', 'forget_modes': true});
    final j = decodeJoin(
      hexDecode(out['payload_hex']! as String),
      Uint8List(32),
    );
    expect((j.fetchModes, j.forgetModes), (false, true));
    expect(fetch.fetches().single['state'], 'forget');
  });

  test('branding: an unused crest goes a day after its upload', () {
    var wall = 1800000000.0;
    final engine = ControllerEngine(
      transport: RecordingRadio(),
      wallSeconds: () => wall,
    );
    final branding = ControllerBranding(engine);
    final png = File(
      '../controller/tests/fixtures/branding/crest-red.png',
    ).existsSync();
    if (!png) return; // the Pi's fixtures are not in this checkout
    final data = File(
      '../controller/tests/fixtures/branding/crest-red.png',
    ).readAsBytesSync();
    final (ref, created) = branding.addCrest(data, 'image/png');
    expect(created, isTrue);
    expect(branding.purge(force: true), 0);
    wall += crestGraceS + 1;
    expect(branding.purge(force: true), 1);
    expect(branding.crest(ref['crest_id']! as String), isNull);
  });

  test('the [modes] settings: their checks and JSON', () {
    final v = loadVectors('mode_package.json');
    final key = (v['signing_key'] as Map)['public_key_b64'] as String;
    final good = ModesConfig(
      keys: [key],
      boxKeys: [key],
      revoked: const ['21fe31dfa154a261'],
      index: 'https://registry.example/index.json',
    );
    expect(modesConfigProblem(good), isNull);
    expect(ModesConfig.fromJson(good.toJson()).toJson(), good.toJson());
    expect(modesConfigProblem(const ModesConfig(keys: ['nope'])), (
      'ctl_modes.bad_key',
      1,
    ));
    expect(modesConfigProblem(ModesConfig(boxKeys: [key, 'x'])), (
      'ctl_modes.bad_key',
      2,
    ));
    expect(modesConfigProblem(const ModesConfig(revoked: ['ABC'])), (
      'ctl_modes.bad_id',
      1,
    ));
    expect(
      modesConfigProblem(const ModesConfig(index: 'http://x/index.json')),
      ('ctl_modes.bad_index', 0),
    );
    final settings = AppSettings()..controllerModes = good.toJson();
    expect(
      AppSettings.fromJson(
        jsonDecode(jsonEncode(settings.toJson())) as Map<String, Object?>,
      ).controllerModes,
      good.toJson(),
    );
  });
}
