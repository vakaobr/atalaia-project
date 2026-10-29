// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The Android field controller's engine and API beyond the shared contract
// cases (api_contract_test.dart): field.lua's field operations on the real
// core, what the engine tells its listeners (the stream and MQTT, slice S2),
// the gm_only table against the event schema, a controller without the core,
// and the HTTP details (loopback by default, methods, bodies).

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_modes.dart';
import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/modes/builtin_modes.g.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:yaml/yaml.dart';

import '../support/core_libs.dart';
import '../support/recording_modem.dart';
import '../support/recording_radio.dart';

const _fieldOpsMode = {
  'mode.yaml':
      'id: org.test.fieldops\nversion: 0.1.0\nroles:\n  zone: {}\n'
      'params:\n  bonus: { type: int, default: 5 }\n'
      '  secret: { type: string, optional: true, gm_only: true }\n',
  'node.lua': 'local x = 1\n',
  'field.lua': '''
local fs = state.field { zones = 0 }
on("game.start", function()
  for _, n in ipairs(field.nodes("zone")) do
    field.send(n.id, "message", { text = "go" })
  end
  field.send(4, "update", { id = "x" })
  fs.zones = #field.nodes("zone")
end)
on("zone.captured", function(e)
  score.add(e.team, params.bonus, "capture by " .. e.node)
  emit("x.test.owner", { team = field.owner(e.node) })
end)
on("zone.neutralized", function()
  game.win("blue")
end)
''',
};

ModeCatalog catalog() => ModeCatalog([
  for (final e in builtinModeFiles.entries) ModeManifest.parse(e.key, e.value),
  ModeManifest.parse('fieldops', _fieldOpsMode),
]);

void main() {
  late AtalaiaCore core;
  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  RfHeader hdr(int gameId, int source, int seq, int type) => RfHeader.v1(
    gameId: gameId,
    source: source,
    seq: seq,
    hopLimit: 2,
    type: type,
  );

  test('the gm_only table is the event schema\'s', () {
    final doc =
        loadYaml(File('../protocol/schema/events.yaml').readAsStringSync())
            as YamlMap;
    final fromSchema = <String, Set<String>>{};
    (doc['events'] as YamlMap).forEach((name, spec) {
      final gmOnly = spec is YamlMap ? spec['gm_only'] : null;
      if (gmOnly is YamlList) {
        fromSchema['$name'] = {for (final f in gmOnly) '$f'};
      }
    });
    expect(gmOnlyEventData, fromSchema);
    expect(
      publicEvent({
        'type': 'hacking.solved',
        'data': {'puzzle': 'code', 'code': '1'},
      }),
      {
        'type': 'hacking.solved',
        'data': {'puzzle': 'code'},
      },
    );
  });

  test('field.lua: field operations, points, state.field and game.win', () {
    var now = 0;
    final radio = RecordingRadio();
    final engine = ControllerEngine(
      core: core,
      modes: catalog(),
      transport: radio,
      clockMs: () => now,
    );
    final messages = <Map<String, Object?>>[];
    engine.addListener(messages.add);
    final game = engine.createGame({
      'name': 'ops',
      'mode_id': 'org.test.fieldops',
      'assignments': {'4': 'zone', '5': 'zone'},
      'params': {'secret': 'xyz'},
    });
    final id = game['id']! as int;
    expect(engine.playersGame(game)['params'], {'bonus': 5});
    engine.startGame(id, force: true);

    final cmds = [
      for (final (t, p) in radio.sent)
        if (t == RfType.cmd) RfCmd.decode(p),
    ];
    expect(cmds.map((c) => (c.name, c.dest)), [
      ('start', null),
      ('message', 4),
      ('message', 5),
    ]); // "update" is the GM's alone
    expect(messages.where((m) => m['type'] == 'field_state').last, {
      'type': 'field_state',
      'key': 'zones',
      'value': 2,
    });
    expect(messages.where((m) => m['type'] == 'system').single, {
      'type': 'system',
      'kind': 'start.forced',
      'game': id,
      'missing': ['zone'],
    });

    engine.onPacket(
      hdr(id, 4, 0, RfType.state),
      const RfState(
        ownerTeam: 1,
        phase: 1,
        gameTimeMs: 0,
        counters: {1: 2},
        epoch: 1,
      ).encode(),
      epoch: 1,
    );
    final captured = core.encodeEvent(
      node: 4,
      seq: 1,
      tMs: 10,
      type: 'zone.captured',
      team: 1,
      squad: 0,
      prio: 2,
      dataJson: null,
    );
    engine.onPacket(hdr(id, 4, 1, RfType.event), captured.bytes!, epoch: 1);
    expect(engine.score(id)['teams'], {'red': 7, 'blue': 0});
    final owner = engine.log(id).firstWhere((e) => e['type'] == 'x.test.owner');
    expect(owner['data'], {'team': 'red'});
    expect(owner['node'], 0);
    expect(messages.where((m) => m['type'] == 'score').last['teams'], {
      'red': 7,
      'blue': 0,
    });

    // game.win from a box's event waits for the tick (never inside the
    // radio's receive path), then ends the game with the script's winner.
    final neutral = core.encodeEvent(
      node: 5,
      seq: 1,
      tMs: 20,
      type: 'zone.neutralized',
      team: 0,
      squad: 0,
      prio: 1,
      dataJson: null,
    );
    engine.onPacket(hdr(id, 5, 0, RfType.event), neutral.bytes!, epoch: 1);
    expect(engine.getGame(id)['state'], 'running');
    now += 100;
    engine.tick();
    final ended = engine.getGame(id);
    expect(ended['state'], 'ended');
    expect(engine.log(id).lastWhere((e) => e['type'] == 'game.end')['data'], {
      'reason': 'win',
      'winner': 'blue',
    });
    expect(engine.liveGame, isNull);
    expect(engine.gameKey, isEmpty);
    engine.close();
  });

  test("a box's game.end ends a game without a field.lua (GE-1..GE-6)", () {
    var now = 0;
    final engine = ControllerEngine(
      core: core,
      modes: catalog(),
      transport: RecordingRadio(),
      clockMs: () => now,
    );
    final game = engine.createGame({
      'name': 'boxes',
      'mode_id': 'org.atalaia.domination',
      'teams': ['red', 'blue'],
      'assignments': {'4': 'zone', '5': 'zone'},
    });
    final id = game['id']! as int;
    var seq = 0;
    void hello(int node) => engine.onPacket(
      hdr(id, node, 0, RfType.hello),
      RfHello(
        nodeName: 'box-$node',
        platform: 1,
        fwVersion: '0.4.0',
        coreVersion: '0.2.0',
        tier: 0,
        capabilities: const [0],
        transports: 1,
        epoch: 1,
      ).encode(),
      epoch: 1,
    );
    void gameEnd(int node, int tMs, Map<String, Object?> data) {
      final ev = core.encodeEvent(
        node: node,
        seq: ++seq,
        tMs: tMs,
        type: 'game.end',
        team: 0,
        squad: 0,
        prio: 2,
        dataJson: jsonEncode(data),
      );
      engine.onPacket(
        hdr(id, node, 10 + seq, RfType.event),
        ev.bytes!,
        epoch: 1,
      );
    }

    for (final n in [4, 5, 9]) {
      hello(n);
    }
    engine.startGame(id);
    // A box nobody assigned in this game does not end it.
    gameEnd(9, 500, {'reason': 'win', 'winner': 'red'});
    now += 1000;
    engine.tick();
    expect(engine.getGame(id)['state'], 'running');
    // Paused: the event is only logged (GE-3).
    engine.pauseGame(id);
    gameEnd(4, 1500, {'reason': 'win', 'winner': 'red'});
    now += 1000;
    engine.tick();
    expect(engine.getGame(id)['state'], 'paused');
    engine.resumeGame(id);
    // Two in the same tick: the first one counts, with its winner; the end
    // waits for the tick, out of the radio's receive path.
    gameEnd(5, 3000, {'reason': 'win', 'winner': 'blue'});
    gameEnd(4, 3000, {'reason': 'win', 'winner': 'red'});
    expect(engine.getGame(id)['state'], 'running');
    now += 100;
    engine.tick();
    expect(engine.getGame(id)['state'], 'ended');
    final ends = engine
        .log(id)
        .where((e) => e['type'] == 'game.end' && e['node'] == 0)
        .toList();
    expect(ends.length, 1);
    expect(ends.single['data'], {
      'reason': 'win',
      'winner': 'blue',
      'by_node': 5,
      'by_name': 'box-5',
    });
    engine.close();
  });

  test('a box game.end with no team as winner is a draw, not the leader', () {
    var now = 0;
    final engine = ControllerEngine(
      core: core,
      modes: catalog(),
      transport: RecordingRadio(),
      clockMs: () => now,
    );
    final game = engine.createGame({
      'name': 'draw',
      'mode_id': 'org.atalaia.domination',
      'teams': ['red', 'blue'],
      'assignments': {'4': 'zone'},
    });
    final id = game['id']! as int;
    engine.startGame(id, force: true);
    engine.adjustScore(id, 'red', 9, '');
    final ev = core.encodeEvent(
      node: 4,
      seq: 1,
      tMs: 2000,
      type: 'game.end',
      team: 0,
      squad: 0,
      prio: 2,
      dataJson: jsonEncode({'reason': 'draw'}),
    );
    engine.onPacket(hdr(id, 4, 1, RfType.event), ev.bytes!, epoch: 1);
    now += 100;
    engine.tick();
    expect(engine.getGame(id)['state'], 'ended');
    final end = engine
        .log(id)
        .lastWhere((e) => e['type'] == 'game.end' && e['node'] == 0);
    expect(end['data'], {'reason': 'draw', 'by_node': 4, 'by_name': 'node-4'});
    engine.close();
  });

  test("an empty `lang` parameter is the game's language (P5H-23)", () {
    final engine = ControllerEngine(core: core);
    for (final mode in [
      'org.atalaia.medic',
      'org.atalaia.hacking_terminal',
      'org.atalaia.vip_payload',
    ]) {
      for (final (console, want) in [
        ('pt', 'pt'),
        ('de', 'de'),
        ('zh-tw', 'zh-tw'),
        ('en', 'en'),
        (null, 'en'),
      ]) {
        final game = engine.createGame({
          'name': 'x',
          'mode_id': mode,
          'console_lang': ?console,
        });
        expect((game['params'] as Map)['lang'], want, reason: '$mode $console');
        engine.endGame(game['id'] as int);
      }
      // The GM's own choice stays.
      final own = engine.createGame({
        'name': 'x',
        'mode_id': mode,
        'console_lang': 'de',
        'params': {'lang': 'pt'},
      });
      expect((own['params'] as Map)['lang'], 'pt');
      engine.endGame(own['id'] as int);
    }
    // A mode with no such parameter gets none.
    final dom = engine.createGame({
      'name': 'x',
      'mode_id': 'org.atalaia.domination',
      'console_lang': 'pt',
    });
    expect((dom['params'] as Map).containsKey('lang'), isFalse);
    engine.close();
  });

  test("the modem's own screen follows the boxes' language (MOD-2)", () {
    final modem = RecordingModem();
    final engine = ControllerEngine(core: core, modem: modem);
    expect(modem.languages, isEmpty); // "auto" and no game: the modem's build
    engine.setBoxLanguage('de');
    expect(modem.languages, ['de']);
    engine.setBoxLanguage('auto');
    expect(modem.languages, ['de']); // no game: it keeps what it has
    final game = engine.createGame({
      'name': 'x',
      'mode_id': 'org.atalaia.domination',
      'console_lang': 'pt',
    });
    expect(modem.languages, ['de', 'pt']);
    engine.endGame(game['id'] as int);
    engine.setBoxLanguage('zh-tw');
    expect(modem.languages.last, 'zh-tw');
    engine.close();
  });

  test('the language a join carries, as a game language (props)', () {
    expect(gameLangCode(null), 'en');
    expect(gameLangCode(''), 'en');
    expect(gameLangCode('pt'), 'pt');
    expect(gameLangCode('pt-BR'), 'pt');
    expect(gameLangCode('de'), 'de');
    expect(gameLangCode('zh-tw'), 'zh-tw');
    expect(gameLangCode('zh-Hant-TW'), 'zh-tw');
    expect(gameLangCode('zh-cn'), 'en');
    expect(gameLangCode('fr'), 'en');
    final p = <String, Object?>{'lang': ''};
    fillLangParam(true, p, 'de');
    expect(p['lang'], 'de');
    fillLangParam(true, p, 'pt'); // already filled: stays
    expect(p['lang'], 'de');
    final none = <String, Object?>{'x': 1};
    fillLangParam(false, none, 'pt');
    expect(none, {'x': 1});
  });

  test('the game key: 16 random bytes per game, never in the API', () {
    final engine = ControllerEngine(core: core);
    final game = engine.createGame({
      'name': 'k',
      'mode_id': 'org.atalaia.domination',
    });
    expect(engine.gameKey, hasLength(16));
    expect(jsonEncode(game), isNot(contains('key')));
    final first = List.of(engine.gameKey);
    engine.endGame(game['id']! as int);
    engine.createGame({'name': 'k2', 'mode_id': 'org.atalaia.domination'});
    expect(engine.gameKey, isNot(first));
  });

  test('without the core: no field.lua modes, box events not decoded', () {
    final engine = ControllerEngine(transport: RecordingRadio());
    expect(
      () => engine.createGame({'name': 'h', 'mode_id': 'org.atalaia.holdall'}),
      throwsA(isA<ControllerError>().having((e) => e.status, 'status', 503)),
    );
    final id =
        engine.createGame({
              'name': 'd',
              'mode_id': 'org.atalaia.domination',
            })['id']!
            as int;
    engine.startGame(id, force: true);
    engine.onPacket(
      hdr(id, 4, 0, RfType.event),
      core
          .encodeEvent(
            node: 4,
            seq: 1,
            tMs: 1,
            type: 'zone.captured',
            team: 1,
            squad: 0,
            prio: 2,
            dataJson: null,
          )
          .bytes!,
    );
    expect(
      engine.log(id).map((e) => e['type']),
      isNot(contains('zone.captured')),
    );
    // A packet of another game is not this game's.
    engine.onPacket(
      hdr(id + 1, 4, 1, RfType.state),
      const RfState(
        ownerTeam: 1,
        phase: 0,
        gameTimeMs: 0,
        counters: {1: 9},
        epoch: 1,
      ).encode(),
    );
    expect(engine.score(id)['teams'], {'red': 0, 'blue': 0});
  });

  test('without a radio, a node command is refused with 503', () {
    final engine = ControllerEngine(core: core);
    final id =
        engine.createGame({
              'name': 'd',
              'mode_id': 'org.atalaia.domination',
            })['id']!
            as int;
    expect(engine.status()['radio'], 'none');
    expect(
      () => engine.sendNodeCmd(4, 'message', {'text': 'x'}),
      throwsA(isA<ControllerError>().having((e) => e.status, 'status', 503)),
    );
    engine.endGame(id);
  });

  group('the HTTP side', () {
    late ControllerApi api;

    setUp(() {
      api = ControllerApi(
        ControllerEngine(core: core),
        gmToken: 'g',
        readToken: 'r',
      );
    });

    test('listens on the loopback address unless told otherwise', () async {
      final server = await api.serve();
      try {
        expect(server.address.isLoopback, isTrue);
        final client = HttpClient();
        final req = await client.get('127.0.0.1', server.port, '/healthz');
        final res = await req.close();
        expect(res.statusCode, 200);
        expect(res.headers.contentType?.mimeType, 'application/json');
        expect(res.headers.value('cache-control'), 'no-store');
        expect(jsonDecode(await utf8.decodeStream(res)), {
          'ok': true,
          'version': controllerApiVersion,
          'radio': 'none',
        });
        client.close();
      } finally {
        await server.close(force: true);
      }
    });

    test('methods, bodies and tokens', () {
      final games = Uri.parse('/api/v1/games');
      expect(
        api.handle('DELETE', games, authorization: 'Bearer g').status,
        405,
      );
      expect(
        api.handle('POST', games, authorization: 'bearer g', body: '{').status,
        422,
      );
      expect(
        api
            .handle('POST', games, authorization: 'Bearer g', body: '[1]')
            .status,
        400,
      );
      final unauthorized = api.handle('GET', games);
      expect(unauthorized.status, 401);
      expect(unauthorized.headers['WWW-Authenticate'], 'Bearer');
      expect(api.role('g'), 'gm');
      expect(api.role('r'), 'read');
      expect(api.role('gg'), isNull);
      expect(api.role(''), isNull);
      expect(
        api
            .handle(
              'GET',
              Uri.parse('/api/v1/games/x'),
              authorization: 'Bearer r',
            )
            .status,
        422,
      );
      expect(
        () => ControllerApi(api.engine, gmToken: '', readToken: 'r'),
        throwsArgumentError,
      );
    });
  });

  test('decodeEvent is the inverse of encodeEvent', () {
    final bytes = core
        .encodeEvent(
          node: 3,
          seq: 9,
          tMs: 1234,
          type: 'hacking.solved',
          team: 2,
          squad: 1,
          prio: 2,
          dataJson: '{"puzzle":"code","code":"77"}',
        )
        .bytes!;
    final ev = core.decodeEvent(bytes).event!;
    expect(
      (ev.node, ev.seq, ev.tMs, ev.type, ev.team, ev.squad, ev.prioName),
      (3, 9, 1234, 'hacking.solved', 2, 1, 'critical'),
    );
    expect(ev.data, {'puzzle': 'code', 'code': '77'});
    final bad = core.decodeEvent([0xff, 0x00]);
    expect(bad.event, isNull);
    expect(bad.error, isNotEmpty);
    expect(prioNames, ['telemetry', 'normal', 'critical']);
  });
}
