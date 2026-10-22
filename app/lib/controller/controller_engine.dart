// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The Android field controller's engine (ADR-P3-12, decision PE24): games,
/// their mode's field.lua on the shared core, the merged scores, the event
/// log and the live feed. The Dart counterpart of the Pi controller's
/// controller/atalaia_controller/engine.py, answering the same API
/// (controller_api.dart) with the same records, checked by the shared
/// contract cases in protocol/vectors/controller_api.json.
///
/// The engine is synchronous and owns a CoreNode while a game with a
/// field.lua runs, so it lives on one isolate: the controller's own isolate
/// in the app (never the UI isolate, constraint 1), or a test's. [tick] moves
/// it on (the shell calls it every 100 ms); the clock is injected.
///
/// Slice S1 of PE24 (PLAN.md): one game at a time, created, started,
/// paused, resumed and ended by the GM; field.lua with the field operations;
/// box packets (decrypted) fed to [onPacket]; GM score adjustments and node
/// commands. Not yet: keeping games across a restart (S3), the radio and the
/// Wi-Fi props (S4), check-in and player tokens (S5), presets, mode uploads,
/// scenarios, role packages, branding, channel scans, failover (S7).
library;

import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import '../core/node_types.dart';
import '../ffi/bindings.dart';
import '../ffi/callbacks.dart';
import '../ffi/core_node.dart';
import '../modes/mode_catalog.dart';
import '../radio/rf_codec.dart';
import 'controller_store.dart';
import 'field_controller.dart';

/// What the Pi controller answers with 400 (and its subclasses' codes).
class ControllerError implements Exception {
  ControllerError(this.message, {this.status = 400, this.extra = const {}});

  /// A missing game (404).
  ControllerError.notFound(this.message) : status = 404, extra = const {};

  /// The game is not in a state that allows it (409).
  ControllerError.conflict(this.message) : status = 409, extra = const {};

  /// Something this controller does not have (503).
  ControllerError.unavailable(this.message) : status = 503, extra = const {};

  final String message;
  final int status;

  /// More fields of the error's JSON body ("start_check" when Start is
  /// refused for missing roles).
  final Map<String, Object?> extra;

  @override
  String toString() => message;
}

/// Event data only staff may read (decision M5-1): the `gm_only` fields of
/// protocol/schema/events.yaml (test/controller/controller_engine_test.dart
/// checks this table against the schema).
const gmOnlyEventData = <String, Set<String>>{
  'scenario.objective.completed': {'objective'},
  'scenario.objective.failed': {'objective'},
  'scenario.objective.revealed': {'objective'},
  'hacking.solved': {'code'},
};

/// An event without the data only staff may read.
Map<String, Object?> publicEvent(Map<String, Object?> ev) {
  final hidden = gmOnlyEventData[ev['type']];
  final data = ev['data'];
  if (hidden == null || data is! Map || !data.keys.any(hidden.contains)) {
    return ev;
  }
  return {
    ...ev,
    'data': {
      for (final e in data.entries)
        if (!hidden.contains(e.key)) '${e.key}': e.value,
    },
  };
}

/// The Pi controller's settings that apply here.
class ControllerConfig {
  const ControllerConfig({
    this.nodeId = 0,
    this.channelHz = 869525000,
    this.maxHops = 2,
    this.failoverMode = 'manual',
    this.powerSource = 1,
    this.batteryPct = 100,
    this.storageOk = true,
    this.healthNodeOfflineS = 120,
    this.healthBatteryLowPct = 20,
  });

  /// This controller's short id on the radio.
  final int nodeId;
  final int channelHz;
  final int maxHops;
  final String failoverMode;

  /// ADR-P2-8: 3 mains, 2 large battery, 1 small battery (a phone).
  final int powerSource;
  final int batteryPct;
  final bool storageOk;
  final double healthNodeOfflineS;
  final int healthBatteryLowPct;

  /// ADR-P2-8's priority score, as the Pi computes it.
  int get priority {
    final score =
        powerSource.clamp(0, 3) * 4096 +
        batteryPct.clamp(0, 100) * 32 +
        (storageOk ? 512 : 0) +
        100 * 2;
    return min(score, 0xffff);
  }
}

const teamNameMax = 23;
const squadsMax = 16;
const modeIdMax = 63;
const nodeCommands = ['set_owner', 'message', 'reset', 'reboot', 'mode'];
final _commandName = RegExp(r'^[a-z][a-z0-9_]{0,23}$');

/// A mode's field.lua on the core, with field.* answered by the engine.
///
/// Its score.add() gains are the controller's own counters: they never
/// travel in a box's STATE, so they are merged under [scoreKey] (one key per
/// run). A game.end it emits ends the game once the script has returned
/// ([pendingEnd]), never from inside the core's callback.
class _FieldScript implements FieldOperations {
  _FieldScript(
    this.engine,
    AtalaiaCore core,
    String source,
    String chunk,
    Map<String, Object?> game,
    this.scoreKey,
  ) : teams = (game['teams']! as List).cast<String>() {
    node = CoreNode.create(
      core,
      NodeSpec(
        source: source,
        chunkName: chunk,
        nodeId: engine.nodeId,
        gameSeed: game['game_seed']! as int,
        teams: teams,
        params: (game['params']! as Map).cast<String, Object?>(),
      ),
      handlers: NodeHandlers(onEvent: _onEvent, onFieldState: _onFieldState),
      fieldOps: this,
    );
    if (!node.loaded) {
      final why = node.lastError;
      node.close();
      throw ControllerError('field.lua does not load: $why');
    }
  }

  final ControllerEngine engine;
  final List<String> teams;
  final String scoreKey;
  late final CoreNode node;
  final state = <String, Object?>{};
  Map<String, Object?>? pendingEnd;

  FieldController get _fc => engine._fc!;

  @override
  List<Map<String, Object?>> nodes(String? role) {
    final all = _fc.nodes.values.toList()
      ..sort((a, b) => a.nodeId.compareTo(b.nodeId));
    return [
      for (final n in all)
        if (role == null || n.role == role)
          {
            'id': n.nodeId,
            'name': n.name,
            'role': n.role,
            'owner': n.ownerName(_fc.teams),
          },
    ];
  }

  @override
  String? owner(int nodeId) => _fc.nodes[nodeId]?.ownerName(_fc.teams);

  @override
  bool send(int nodeId, String cmd, Map<String, Object?> params) {
    if (cmd == 'mode' && !_commandName.hasMatch('${params['name'] ?? ''}')) {
      return false;
    }
    if (!cmdOpcodes.containsKey(cmd)) return false; // update: the GM's alone
    try {
      return _fc.sendCmd(cmd, params.isEmpty ? null : params, dest: nodeId) !=
          null;
    } on FieldControllerException {
      return false;
    }
  }

  void _onFieldState(String key, String valueJson) {
    final value = jsonDecode(valueJson);
    state[key] = value;
    engine._emit({'type': 'field_state', 'key': key, 'value': value});
  }

  void _onEvent(EmittedEvent ev) {
    if (ev.type == 'game.end') {
      pendingEnd = ev.data;
      return;
    }
    _fc.controllerEvent(ev.type, ev.data, _fc.teamName(ev.team), ev.prioName);
  }

  void input(String type, [Map<String, Object?>? data]) {
    node.input(type, data);
    _mergeGains();
  }

  void advance(int gameTimeMs) {
    node.advance(gameTimeMs);
    _mergeGains();
  }

  Map<String, int> gains() => {
    for (final t in teams)
      if (node.gained(t) != 0) t: node.gained(t),
  };

  void _mergeGains() {
    final g = gains();
    if (g.isNotEmpty) _fc.mergeCounters(scoreKey, g);
  }

  void close() => node.close();
}

class ControllerEngine {
  ControllerEngine({
    this.config = const ControllerConfig(),
    ControllerStore? store,
    ModeCatalog? modes,
    this.core,
    FieldTransport? transport,
    int Function()? clockMs,
    double Function()? wallSeconds,
    Random? random,
  }) : store = store ?? MemoryControllerStore(wallSeconds: wallSeconds),
       modes = modes ?? ModeCatalog.builtin(),
       transport = transport ?? const NoRadio(),
       _wall =
           wallSeconds ?? (() => DateTime.now().microsecondsSinceEpoch / 1e6),
       _random = random ?? Random.secure() {
    final watch = Stopwatch()..start();
    _clock = clockMs ?? () => watch.elapsedMilliseconds;
    _t0 = _clock();
  }

  final ControllerConfig config;
  final ControllerStore store;
  final ModeCatalog modes;

  /// The core: field.lua and the EVENT codec need it (null: modes with a
  /// field.lua are refused, box events are not decoded).
  final AtalaiaCore? core;
  final FieldTransport transport;
  final double Function() _wall;
  final Random _random;
  late final int Function() _clock;
  late final int _t0;

  Map<String, Object?>? _game;
  FieldController? _fc;
  _FieldScript? _field;
  Uint8List _key = Uint8List(0);
  Map<String, Map<String, int>> _fieldScores = {};
  final _listeners = <void Function(Map<String, Object?>)>[];

  int nowMs() => _clock() - _t0;

  /// The live game's key (ADR-P2-2): for join payloads (slice S4); never on
  /// the API.
  Uint8List get gameKey => _key;

  int get nodeId => (_game?['node_id'] as int?) ?? config.nodeId;

  /// The live game, or null.
  Map<String, Object?>? get liveGame => _game;

  String get radioState => transport.state;

  void addListener(void Function(Map<String, Object?>) fn) =>
      _listeners.add(fn);

  void _emit(Map<String, Object?> msg) {
    for (final fn in List.of(_listeners)) {
      fn(msg);
    }
  }

  // --- games: what the API shows ------------------------------------------

  GameMode? _mode(Object? modeId) {
    if (modeId is! String) return null;
    try {
      return modes.compose(modeId);
    } on ModeException {
      return null;
    }
  }

  Map<String, Object?> publicGame(Map<String, Object?> game) {
    final out = Map<String, Object?>.of(game);
    final live = _game != null && _game!['id'] == game['id'];
    out['live'] = live;
    final fc = _fc;
    if (live && fc != null) {
      out['game_time_ms'] = fc.gameTimeMs;
      out['term'] = fc.term;
      if (game['state'] == 'ready' && game['joined'] != true) {
        out['start_check'] = startCheck();
      }
    }
    return out;
  }

  /// A game as players and the read token see it: without its gm_only
  /// parameters (decision M5-1).
  Map<String, Object?> playersGame(Map<String, Object?> game) {
    final mode = _mode(game['mode_id']);
    final params = game['params'];
    final hidden = <String>{
      if (mode != null)
        for (final part in mode.parts)
          for (final e
              in ((part.manifest['params'] as Map?) ?? const {}).entries)
            if ((e.value as Map?)?['gm_only'] == true) '${e.key}',
    };
    return {
      ...game,
      'params': mode == null || params is! Map
          ? <String, Object?>{}
          : {
              for (final e in params.entries)
                if (!hidden.contains(e.key)) '${e.key}': e.value,
            },
    }..remove('scenario_nodes');
  }

  List<Map<String, Object?>> listGames() => [
    for (final g in store.games()) publicGame(g),
  ];

  Map<String, Object?> getGame(int id) {
    final game = store.game(id);
    if (game == null) throw ControllerError.notFound('no game $id');
    return publicGame(game);
  }

  // --- creating a game ----------------------------------------------------

  Map<String, Object?> createGame(Map<String, Object?> spec) {
    if (_game != null) {
      throw ControllerError.conflict(
        'game ${_game!['id']} is still live; end it first',
      );
    }
    final name = spec['name'] ?? '';
    if (name is! String || name.isEmpty || name.length > 64) {
      throw ControllerError('name: 1 to 64 characters');
    }
    if (spec['preset_id'] != null) {
      // Presets come with slice S7 (PLAN.md, "PE24 slices").
      throw ControllerError.notFound('no preset ${spec['preset_id']}');
    }
    var modeId = spec['mode_id'];
    final modifiers = spec['modifiers'] ?? const <Object?>[];
    if (modifiers is! List || modifiers.any((m) => m is! String)) {
      throw ControllerError('modifiers: a list of modifier ids');
    }
    if (modifiers.isNotEmpty && modeId is String) {
      modeId = [modeId, ...modifiers].join('+');
    }
    if (modeId is! String) throw ControllerError('unknown mode $modeId');
    final GameMode mode;
    try {
      mode = modes.compose(modeId);
    } on ModeException catch (e) {
      throw ControllerError('unknown mode $modeId ($e)');
    }
    if (utf8.encode(mode.id).length > modeIdMax) {
      throw ControllerError(
        "the game's id ${mode.id} is longer than $modeIdMax bytes",
      );
    }
    final teamsSpec = spec['teams'] ?? const ['red', 'blue'];
    if (teamsSpec is! List ||
        teamsSpec.isEmpty ||
        teamsSpec.length > 8 ||
        teamsSpec.any(
          (t) =>
              t is! String || t.isEmpty || utf8.encode(t).length > teamNameMax,
        ) ||
        teamsSpec.toSet().length != teamsSpec.length) {
      throw ControllerError(
        'teams: 1 to 8 different names of 1 to $teamNameMax bytes',
      );
    }
    final teams = teamsSpec.cast<String>();
    final overrides = spec['params'] ?? const <String, Object?>{};
    if (overrides is! Map) throw ControllerError('params must be a map');
    final Map<String, Object?> params;
    try {
      params = mode.resolveParams(overrides.cast<String, Object?>(), teams);
    } on ModeException catch (e) {
      throw ControllerError('$e');
    }
    final duration = _int(spec['duration_ms'] ?? 0, 'duration_ms');
    if (duration < 0 || duration > 0xffffffff) {
      throw ControllerError('duration_ms: 0 (no limit) to 4294967295');
    }
    final assignments = spec['assignments'] ?? const <String, Object?>{};
    if (assignments is! Map) {
      throw ControllerError('assignments: a map of node id to role');
    }
    final roles = {for (final r in mode.main.roles) r.name};
    final clean = <String, String>{};
    assignments.forEach((nodeId, role) {
      final nid = _int(nodeId, 'assignments node id');
      if (nid < 1 || nid > 0xfffe || nid == config.nodeId) {
        throw ControllerError("node id $nid: 1-65534, not the controller's");
      }
      if (role is! String || !roles.contains(role)) {
        throw ControllerError(
          'role ${jsonEncode(role)} is not one of ${roles.toList()..sort()}',
        );
      }
      clean['$nid'] = role;
    });
    if (mode.fieldScript != null && core == null) {
      throw ControllerError.unavailable(
        'this mode has a field.lua and the core library is not loaded',
      );
    }
    final squads = _int(spec['squads'] ?? 0, 'squads');
    if (squads < 0 || squads > squadsMax) {
      throw ControllerError('squads: 0 (none) to $squadsMax per team');
    }
    final teamInfo = spec['team_info'];
    if (teamInfo != null && (teamInfo is! Map || teamInfo.isNotEmpty)) {
      // Team branding comes with slice S7 (PLAN.md, "PE24 slices").
      throw ControllerError(
        'team_info: team branding is not on the Android controller yet',
      );
    }
    final used = store.gameIds();
    final free = [
      for (var g = 1; g < 0xffff && g <= 4096 + used.length; g++)
        if (!used.contains(g)) g,
    ].take(4096).toList();
    final id = free[_random.nextInt(free.length)];
    final key = Uint8List.fromList(
      List.generate(16, (_) => _random.nextInt(256)),
    );
    final game = <String, Object?>{
      'id': id,
      'name': name,
      'mode_id': mode.id,
      'preset_id': null,
      'teams': teams,
      'params': params,
      'assignments': clean,
      'duration_ms': duration,
      'game_seed': 1 + _random.nextInt(0xfffffffe),
      'state': 'ready',
      'term': 1,
      'created_at': _wall(),
      'node_id': config.nodeId,
      'channel_hz': config.channelHz,
      'max_hops': config.maxHops,
      'joined': false,
      'squads': squads,
      'team_info': <String, Object?>{},
    };
    store.createGame(game);
    _activate(store.game(id)!, key);
    final out = getGame(id);
    _emit({'type': 'game', 'game': out});
    return out;
  }

  void _activate(Map<String, Object?> game, Uint8List key) {
    final fc =
        FieldController(
            transport: transport,
            gameId: game['id']! as int,
            teams: (game['teams']! as List).cast<String>(),
            nodeId: (game['node_id'] as int?) ?? config.nodeId,
            maxHops: (game['max_hops'] as int?) ?? config.maxHops,
            term: (game['term'] as int?) ?? 1,
            decodeEvent: core == null ? null : _decodeEvent,
            wallSeconds: () => _wall().floor(),
          )
          ..durationMs = game['duration_ms']! as int
          ..nodeOfflineMs = (config.healthNodeOfflineS * 1000).round()
          ..batteryLowPct = config.healthBatteryLowPct;
    fc.linkGapMsSetting = min(linkGapMs, fc.nodeOfflineMs);
    (game['assignments']! as Map).forEach((nodeId, role) {
      fc.registerNode(int.parse('$nodeId'), 'node-$nodeId', '$role');
    });
    fc
      ..onEvent = _onEvent
      ..onNode = _onNode
      ..onScores = _onScores;
    _fc = fc;
    _game = game;
    _key = key;
  }

  EmittedEvent _decodeEvent(Uint8List payload) {
    final d = core!.decodeEvent(payload);
    final ev = d.event;
    if (ev == null) throw FieldControllerException(d.error ?? 'refused');
    return ev;
  }

  void _deactivate() {
    _field?.close();
    _field = null;
    _fieldScores = {};
    _fc = null;
    _key = Uint8List(0);
    _game = null;
  }

  /// Ends the controller: the field script's node is freed.
  void close() {
    _field?.close();
    _field = null;
  }

  // --- the lifecycle ------------------------------------------------------

  FieldController _live(int id) {
    final game = store.game(id);
    if (game == null) throw ControllerError.notFound('no game $id');
    if (_game == null || _game!['id'] != id) {
      throw ControllerError.conflict('game $id is ${game['state']}, not live');
    }
    return _fc!;
  }

  Map<String, Object?> _setState(
    int id,
    String state, [
    Map<String, Object?> times = const {},
  ]) {
    store.updateGame(id, {'state': state, ...times});
    if (_game != null && _game!['id'] == id) _game!['state'] = state;
    final out = getGame(id);
    _emit({'type': 'game', 'game': out});
    return out;
  }

  List<(int, String)> _joinedNodes() {
    final out = <int, String>{
      for (final n in store.nodes(_game!['id']! as int))
        n['node_id']! as int: n['role']! as String,
    };
    for (final node in _fc?.nodes.values ?? const <FieldNode>[]) {
      if (node.heard || node.hello != null) out[node.nodeId] = node.role;
    }
    final ids = out.keys.toList()..sort();
    return [for (final id in ids) (id, out[id]!)];
  }

  List<String> _neededRoles() {
    final mode = _mode(_game!['mode_id']);
    if (mode == null) return [];
    final specs = (mode.main.manifest['roles'] as Map?) ?? const {};
    return [
      for (final r in mode.main.roles)
        if ((specs[r.name] as Map?)?['needed'] != false) r.name,
    ]..sort();
  }

  /// What Start would say now: the roles the game needs, how many nodes of
  /// each have joined, the missing ones (Start refuses unless forced) and
  /// the mode's minimums not met (warnings, decisions RJ-1 to RJ-3).
  Map<String, Object?> startCheck() {
    if (_game == null) throw ControllerError.conflict('no live game');
    final needed = _neededRoles();
    final joined = <String, int>{};
    for (final (_, role) in _joinedNodes()) {
      joined[role] = (joined[role] ?? 0) + 1;
    }
    final missing = [
      for (final r in needed)
        if ((joined[r] ?? 0) == 0) r,
    ];
    final warnings = <Map<String, Object?>>[];
    final params = (_game!['params'] as Map?) ?? const {};
    final roles = {...needed, ...joined.keys};
    params.forEach((name, value) {
      if (value is! int || name is! String) return;
      for (final prefix in ['min_', 'last_']) {
        if (!name.startsWith(prefix) || !name.endsWith('s')) continue;
        final role = name.substring(prefix.length, name.length - 1);
        if (!roles.contains(role)) continue;
        final have = joined[role] ?? 0;
        if (prefix == 'min_' && have < value) {
          warnings.add({
            'code': 'min',
            'param': name,
            'role': role,
            'value': value,
            'have': have,
            'text': '$have $role node(s) joined; $name is $value',
          });
        } else if (prefix == 'last_' && have > 0 && have <= value) {
          warnings.add({
            'code': 'last',
            'param': name,
            'role': role,
            'value': value,
            'have': have,
            'text':
                'only $have $role node(s) joined and $name is $value: '
                'the countdown can run from the start',
          });
        }
      }
    });
    final sortedJoined = joined.keys.toList()..sort();
    return {
      'needed': needed,
      'joined': {for (final r in sortedJoined) r: joined[r]},
      'missing': missing,
      'warnings': warnings,
      'ok': missing.isEmpty,
    };
  }

  Map<String, Object?> startGame(int id, {bool force = false}) {
    final fc = _live(id);
    if (_game!['state'] != 'ready') {
      throw ControllerError.conflict(
        'game $id is ${_game!['state']}; only a ready game starts',
      );
    }
    final check = startCheck();
    final missing = (check['missing']! as List).cast<String>();
    if (missing.isNotEmpty && !force) {
      throw ControllerError(
        'no box or prop has joined for: ${missing.join(', ')}; '
        'join them, or start anyway (force)',
        status: 409,
        extra: {'start_check': check},
      );
    }
    if (missing.isNotEmpty) {
      _emit({
        'type': 'system',
        'kind': 'start.forced',
        'game': id,
        'missing': missing,
      });
    }
    fc
      ..startGame(durationMs: _game!['duration_ms']! as int, nowMs: nowMs())
      ..controllerEvent(
        'game.start',
        {'preset': _game!['mode_id']},
        null,
        'critical',
      );
    _startField();
    final out = _setState(id, 'running', {'started_at': _wall()});
    _afterField();
    return out;
  }

  Map<String, Object?> pauseGame(int id, [String reason = '']) {
    final fc = _live(id);
    if (_game!['state'] != 'running') {
      throw ControllerError.conflict('only a running game pauses');
    }
    final data = reason.isEmpty
        ? const <String, Object?>{}
        : <String, Object?>{'reason': reason};
    fc
      ..pauseGame(nowMs: nowMs(), reason: reason.isEmpty ? null : reason)
      ..controllerEvent('game.pause', data, null, 'critical');
    _field?.input('game.pause', reason.isEmpty ? null : data);
    return _setState(id, 'paused');
  }

  Map<String, Object?> resumeGame(int id) {
    final fc = _live(id);
    if (_game!['state'] != 'paused') {
      throw ControllerError.conflict('only a paused game resumes');
    }
    fc
      ..resumeGame(nowMs: nowMs())
      ..controllerEvent('game.resume', const {}, null, 'critical');
    _field?.input('game.resume');
    return _setState(id, 'running');
  }

  Map<String, Object?> endGame(int id, [String reason = '', String? winner]) {
    final fc = _live(id);
    fc.endGame(nowMs: nowMs(), reason: reason.isEmpty ? null : reason);
    final data = <String, Object?>{if (reason.isNotEmpty) 'reason': reason};
    final win = fc.teams.contains(winner)
        ? winner
        : _winner(fc.totalScores, fc.teams);
    if (win != null) data['winner'] = win;
    fc.controllerEvent('game.end', data, null, 'critical');
    _field?.input('game.end', reason.isEmpty ? null : {'reason': reason});
    store.saveScores(id, fc.totalScores);
    _setState(id, 'ended', {'ended_at': _wall()});
    _deactivate();
    return publicGame(store.game(id)!);
  }

  // --- scores, log, nodes -------------------------------------------------

  Map<String, Object?> score(int id) {
    final game = store.game(id);
    if (game == null) throw ControllerError.notFound('no game $id');
    final teams = _fc != null && _game!['id'] == id
        ? _fc!.totalScores
        : store.scores(id);
    return {
      'game': id,
      'teams': {for (final t in game['teams']! as List) '$t': teams[t] ?? 0},
    };
  }

  Map<String, Object?> adjustScore(
    int id,
    Object? team,
    Object? amount,
    Object? reason,
  ) {
    final fc = _live(id);
    if (team is! String || !fc.teams.contains(team)) {
      throw ControllerError(
        'team ${jsonEncode(team)} is not one of ${fc.teams}',
      );
    }
    final n = _int(amount, 'amount');
    if (n == 0 || n.abs() > 1000000) {
      throw ControllerError('amount: a non-zero integer up to 1000000');
    }
    if (reason is! String || reason.length > 64) {
      throw ControllerError('reason: text up to 64 characters');
    }
    final event = fc.adjustScore(team, n, reason, nowMs: nowMs());
    return {'score': score(id), 'event': logRecord(event)};
  }

  List<Map<String, Object?>> log(int id, {int? sinceMs}) {
    if (store.game(id) == null) throw ControllerError.notFound('no game $id');
    return store.events(id, sinceMs: sinceMs);
  }

  List<Map<String, Object?>> nodes([int? gameId]) {
    gameId ??= _game?['id'] as int?;
    if (gameId == null) return [];
    if (store.game(gameId) == null) {
      throw ControllerError.notFound('no game $gameId');
    }
    final stored = <int, Map<String, Object?>>{
      for (final n in store.nodes(gameId)) n['node_id']! as int: n,
    };
    final fc = _fc;
    if (fc != null && _game!['id'] == gameId) {
      final now = nowMs();
      for (final node in fc.nodes.values) {
        stored[node.nodeId] = {
          ...?stored[node.nodeId],
          ..._nodeInfo(node),
          'seen_ms_ago': node.lastSeenMs != 0 ? now - node.lastSeenMs : null,
        };
      }
    }
    final ids = stored.keys.toList()..sort();
    return [for (final id in ids) stored[id]!];
  }

  Map<String, Object?> _nodeInfo(FieldNode node) {
    final fc = _fc!;
    final hello = node.hello;
    final device = hello?.deviceId;
    return {
      'node_id': node.nodeId,
      'name': node.name,
      'role': node.role,
      'owner': node.ownerName(fc.teams),
      'phase': node.phase,
      'game_time_ms': node.gameTimeMs,
      'battery_pct': node.batteryPct,
      'rssi': node.rssi,
      'snr': node.snr,
      'epoch': node.epoch,
      'platform': hello?.platform,
      'fw_version': hello?.fwVersion,
      'core_version': hello?.coreVersion,
      'tier': hello?.tier,
      'capabilities': hello?.capabilities,
      'device_id': device
          ?.map((b) => b.toRadixString(16).padLeft(2, '0'))
          .join(),
      'score': {
        for (final t in fc.teams) t: fc.counter(t, 'node-${node.nodeId}'),
      },
      'link': node.link,
      'battery_low': node.batteryLow,
      'conflict': false,
    };
  }

  /// A command to one node (65535: every node).
  Map<String, Object?> sendNodeCmd(
    Object? nodeIdValue,
    Object? cmd,
    Object? params,
  ) {
    if (_game == null) throw ControllerError.conflict('no live game');
    final fc = _live(_game!['id']! as int);
    final nodeId = _int(nodeIdValue, 'node id');
    if (nodeId < 1 || nodeId > 0xffff) {
      throw ControllerError('node id: 1-65535 (65535 = every node)');
    }
    if (cmd is! String || !nodeCommands.contains(cmd)) {
      throw ControllerError(
        'cmd: one of ${nodeCommands.join(', ')} '
        '(start, pause, resume and end go through the game)',
      );
    }
    if (params != null && params is! Map) {
      throw ControllerError('params must be a map');
    }
    final p = (params as Map?)?.cast<String, Object?>();
    if (cmd == 'mode') _checkModeCommand(fc, nodeId, p ?? const {});
    final int? seq;
    try {
      seq = fc.sendCmd(cmd, p == null || p.isEmpty ? null : p, dest: nodeId);
    } on FieldControllerException catch (e) {
      throw ControllerError(e.message);
    }
    if (seq == null) {
      throw ControllerError.unavailable(
        'the radio is $radioState; command not sent',
      );
    }
    return {'node': nodeId, 'cmd': cmd, 'opcode': cmdOpcodes[cmd], 'seq': seq};
  }

  void _checkModeCommand(
    FieldController fc,
    int nodeId,
    Map<String, Object?> params,
  ) {
    final mode = _mode(_game!['mode_id']);
    final commands = <String, Object?>{
      for (final part in mode?.parts ?? const <ModeManifest>[])
        ...?(part.manifest['commands'] as Map?)?.cast<String, Object?>(),
    };
    final name = params['name'];
    if (name is! String || !commands.containsKey(name)) {
      final known = (commands.keys.toList()..sort()).join(', ');
      throw ControllerError(
        "params.name: one of the game's mode commands "
        '(${known.isEmpty ? 'none in this game' : known})',
      );
    }
    final roles = [
      for (final r in ((commands[name] as Map?)?['roles'] as List?) ?? []) '$r',
    ];
    final node = fc.nodes[nodeId];
    if (nodeId != broadcastNode &&
        node != null &&
        node.role.isNotEmpty &&
        !roles.contains(node.role)) {
      throw ControllerError(
        '$name is a command for ${roles.join(', ')} nodes; '
        'node $nodeId is a ${node.role}',
      );
    }
  }

  Map<String, Object?> status() {
    final fc = _fc;
    return {
      'node_id': nodeId,
      'host': 'android',
      'failover_mode': config.failoverMode,
      'joined': _game?['joined'] == true,
      'leader': fc?.nodeId,
      'priority': config.priority,
      'role': fc == null ? null : 'leader',
      'term': fc?.term,
      'live_game': _game?['id'],
      'key_lost': false,
      'radio': radioState,
      'tx_status': <String, int>{},
      'field_channel_hz': config.channelHz,
      'channel_confirmed': false,
      'sync': {'enabled': false},
    };
  }

  // --- packets and the tick -----------------------------------------------

  /// A decrypted packet from a box or a prop of the live game.
  void onPacket(
    RfHeader header,
    Uint8List payload, {
    int epoch = 0,
    int? rssi,
    int? snr,
  }) {
    final fc = _fc;
    if (fc == null || header.gameId != fc.gameId) return;
    fc.onPacket(header, payload, epoch: epoch, rssi: rssi, snr: snr);
  }

  /// Moves the controller on: the game clock, TIME beacons, node health,
  /// field.lua's timers, the game's time limit.
  void tick() {
    final fc = _fc;
    if (fc == null) return;
    fc.tick(nowMs());
    final field = _field;
    if (field != null && fc.gameState == gameRunning) {
      field.advance(fc.gameTimeMs);
      if (_afterField()) return;
    }
    final game = _game;
    if (game != null &&
        fc.gameState == gameRunning &&
        fc.durationMs > 0 &&
        fc.gameTimeMs >= fc.durationMs) {
      endGame(game['id']! as int, 'time');
    }
  }

  // --- FieldController hooks ----------------------------------------------

  void _onEvent(Map<String, Object?> record) {
    final game = _game;
    if (game == null) return;
    final id = game['id']! as int;
    if (!store.insertEvent(id, record)) return;
    _emit({'type': 'event', 'game': id, 'event': logRecord(record)});
    final field = _field;
    if (field != null &&
        record['node'] != nodeId &&
        record['origin'] != 'controller') {
      // A box's events; not the health events the controller logs (FU1-4).
      final data = Map<String, Object?>.of(
        (record['data'] as Map?)?.cast<String, Object?>() ?? const {},
      );
      data.putIfAbsent('node', () => record['node']);
      if (record['team'] != null) {
        data.putIfAbsent('team', () => record['team']);
      }
      field.input(record['type']! as String, data);
      _afterField(mayEnd: false);
    }
  }

  void _onNode(FieldNode node, String kind) {
    final game = _game;
    if (game == null) return;
    final info = _nodeInfo(node);
    store.upsertNode(game['id']! as int, info);
    info['seen_ms_ago'] = node.heard ? max(0, nowMs() - node.lastSeenMs) : null;
    _emit({'type': 'node', 'game': game['id'], 'kind': kind, 'node': info});
    if (kind == 'hello' && game['state'] == 'ready' && game['joined'] != true) {
      _emit({'type': 'game', 'game': publicGame(game)});
    }
  }

  void _onScores(Map<String, int> totals) {
    final game = _game;
    if (game == null) return;
    store.saveScores(game['id']! as int, totals);
    _emit({
      'type': 'score',
      'game': game['id'],
      'teams': {for (final t in game['teams']! as List) '$t': totals[t] ?? 0},
    });
  }

  // --- the field script ---------------------------------------------------

  void _startField() {
    final game = _game;
    final fc = _fc;
    if (game == null || fc == null || _field != null) return;
    final mode = _mode(game['mode_id']);
    final source = mode?.fieldScript;
    if (mode == null || source == null) return;
    final c = core;
    if (c == null) {
      throw ControllerError.unavailable(
        'this mode has a field.lua and the core library is not loaded',
      );
    }
    final id = game['id']! as int;
    final run = int.parse(store.getSetting('field_run:$id') ?? '0') + 1;
    store.setSetting('field_run:$id', '$run');
    final field = _FieldScript(
      this,
      c,
      source,
      '${mode.id}/field.lua',
      game,
      'field-$run',
    );
    _field = field;
    if (fc.gameTimeMs > 0) field.advance(fc.gameTimeMs);
    field.input('game.start');
    if (fc.gameState == gamePaused) field.input('game.pause');
  }

  /// After field.lua ran: keeps its points with the game, and ends the game
  /// if it asked to. True when the game ended.
  bool _afterField({bool mayEnd = true}) {
    final field = _field;
    final game = _game;
    if (field == null || game == null) return false;
    final gains = field.gains();
    if (gains.isNotEmpty &&
        jsonEncode(_fieldScores[field.scoreKey]) != jsonEncode(gains)) {
      _fieldScores[field.scoreKey] = gains;
      store.setSetting('field_scores:${game['id']}', jsonEncode(_fieldScores));
    }
    final end = field.pendingEnd;
    if (!mayEnd || end == null) return false;
    field.pendingEnd = null;
    final winner = end['winner'];
    endGame(
      game['id']! as int,
      '${end['reason'] ?? ''}',
      winner is String ? winner : null,
    );
    return true;
  }
}

/// The team with the highest total, or null on a tie or when nobody scored.
String? _winner(Map<String, int> totals, List<String> teams) {
  final ranked = [for (final t in teams) (totals[t] ?? 0, t)]
    ..sort((a, b) {
      final c = b.$1.compareTo(a.$1);
      return c != 0 ? c : b.$2.compareTo(a.$2);
    });
  if (ranked.isEmpty ||
      ranked.first.$1 <= 0 ||
      (ranked.length > 1 && ranked[0].$1 == ranked[1].$1)) {
    return null;
  }
  return ranked.first.$2;
}

/// An event as the API and the stream give it.
Map<String, Object?> logRecord(Map<String, Object?> record) => {
  for (final k in [
    'node',
    'seq',
    't',
    'type',
    'team',
    'squad',
    'prio',
    'data',
    'epoch',
    'pkt_seq',
  ])
    k: record[k],
};

/// An integer from JSON, as Python's int() takes it (decision PE24-6).
int _int(Object? value, String name) {
  if (value is int) return value;
  if (value is double && value.isFinite) return value.truncate();
  if (value is String) {
    final v = int.tryParse(value.trim());
    if (v != null) return v;
  }
  throw ControllerError('$name must be an integer');
}
