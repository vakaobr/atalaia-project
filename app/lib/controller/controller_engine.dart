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
/// commands. Slice S3: an engine on a store that holds a live game (a
/// [FileControllerStore] after a restart) takes the game up again as the Pi
/// does (engine.py `_restore`): its clock, scores, nodes, health and
/// field.lua; without its key (persist_game_key off) the game can only be
/// ended (`key_lost`). Slice S4: the radio ([modem], an I/O pod through
/// pod_modem.dart: CONFIGURE, the controller's packets with a TX epoch per
/// game key, what it hears, TX_ACKs, peer epochs), join payloads sealed with
/// the field join key ([issueJoin]) and the Android props on Wi-Fi
/// (controller_props.dart, through [wifiForward]). Slice S5: field check-in,
/// player tokens and the chrono list ([checkin], controller_checkin.dart),
/// player positions ([positions], controller_positions.dart), with the
/// engine's hooks the Pi's engine has for them: the controller's own events
/// ([logControllerEvent]), a VIP's position for field.lua
/// ([fieldPosition]), the retention purge and the grants' expiry on [tick],
/// positions deleted when a game ends. Not yet: presets, mode uploads,
/// scenarios, role packages, branding, the channel choice and scans,
/// re-invites, failover (S7). Slice S6: the shell runs the engine on the
/// controller's own isolate (controller_host.dart) and gives it the field
/// CA and the phone's addresses for join keys 13 and 14 ([caSha256],
/// [linkUrls]).
library;

import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import '../core/node_types.dart';
import '../ffi/bindings.dart';
import '../ffi/callbacks.dart';
import '../ffi/core_node.dart';
import '../modes/mode_catalog.dart';
import '../protocol/join_payload.dart';
import '../radio/rf_codec.dart';
import '../security/ndef.dart';
import 'controller_checkin.dart';
import 'controller_positions.dart';
import 'controller_radio.dart';
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
    this.persistGameKey = true,
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

  /// Keep the live game's key in the store, so that the game survives a
  /// restart (ADR-P2-4; decision OT-7: on by default, as on the Pi).
  final bool persistGameKey;

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

/// How often a running game's clock is written to the store (the Pi's
/// GAME_TIME_SAVE_MS): a crash loses at most this much of the game time.
const gameTimeSaveMs = 5000;
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
    this.modem,
    this.transport,
    int Function()? clockMs,
    double Function()? wallSeconds,
    Random? random,
  }) : store = store ?? MemoryControllerStore(wallSeconds: wallSeconds),
       modes = modes ?? ModeCatalog.builtin(),
       _wall =
           wallSeconds ?? (() => DateTime.now().microsecondsSinceEpoch / 1e6),
       _random = random ?? Random.secure() {
    final watch = Stopwatch()..start();
    _clock = clockMs ?? () => watch.elapsedMilliseconds;
    _t0 = _clock();
    final m = modem;
    if (m != null) {
      m
        ..onRx = _onRx
        ..onTxAck = _onTxAck
        ..onState = _onModemState
        ..onError = (code, message) => _emit({
          'type': 'system',
          'kind': 'modem.error',
          'code': code,
          'message': message,
        });
    }
    _restore();
  }

  final ControllerConfig config;
  final ControllerStore store;
  final ModeCatalog modes;

  /// The core: field.lua and the EVENT codec need it (null: modes with a
  /// field.lua are refused, box events are not decoded).
  final AtalaiaCore? core;

  /// The radio (slice S4): an I/O pod (pod_modem.dart), or a test's. Each
  /// game gets a [RadioTransport] on it, with its own TX epoch.
  final ControllerModem? modem;

  /// A test's transport for every game's packets (tests of the radio
  /// side): then neither the modem nor the Wi-Fi props are used. Null: a
  /// [RadioTransport] per game, on the [modem] and the Wi-Fi props (only on
  /// the props without a modem, as on a Pi without one).
  final FieldTransport? transport;
  RadioTransport? _radio;
  final _txStatus = <String, int>{};
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

  /// Field check-in (slice S5): set by [ControllerCheckin]'s constructor.
  ControllerCheckin? checkin;

  /// Player positions (slice S5): set by [ControllerPositions]'s
  /// constructor.
  ControllerPositions? positions;

  /// The live game came back after a restart without its key: it can only
  /// be ended (ADR-P2-4).
  bool _keyLost = false;
  int _lastTimeSave = 0;

  int nowMs() => _clock() - _t0;

  /// The live game's key (ADR-P2-2): for join payloads (slice S4); never on
  /// the API. Empty with no live game, or when it was lost in a restart.
  Uint8List get gameKey => _key;

  bool get keyLost => _keyLost;

  int get nodeId => (_game?['node_id'] as int?) ?? config.nodeId;

  /// The live game, or null.
  Map<String, Object?>? get liveGame => _game;

  /// "up", "down", "connecting", or "none" without a radio.
  String get radioState => modem?.state ?? transport?.state ?? 'none';

  /// The channel new games use: the GM's choice, else the configured one
  /// (engine.py `field_channel`).
  int get fieldChannel =>
      int.tryParse(store.getSetting('radio.channel_hz') ?? '') ??
      config.channelHz;

  /// The wall clock, in seconds since 1970 (what the MQTT topics' `at` and
  /// `last_seen` give).
  double wallSeconds() => _wall();

  /// [fn] gets every message of the live feed (the stream, MQTT), in order.
  void addListener(void Function(Map<String, Object?>) fn) =>
      _listeners.add(fn);

  void removeListener(void Function(Map<String, Object?>) fn) =>
      _listeners.remove(fn);

  void _emit(Map<String, Object?> msg) {
    for (final fn in List.of(_listeners)) {
      fn(msg);
    }
  }

  /// Sends [msg] to the live feed (the check-in and positions services;
  /// keys starting with "_" are routing marks, controller_stream.dart).
  void emit(Map<String, Object?> msg) => _emit(msg);

  /// Logs an event of the controller's own (player.checkin, chrono.*,
  /// visibility.expired) in [gameId] when it is the live game with its key,
  /// as the Pi's `fc.controller_event`; false when it was not logged.
  bool logControllerEvent(
    int gameId,
    String type,
    Map<String, Object?> data, {
    String? team,
    String prio = 'normal',
  }) {
    final fc = _fc;
    if (fc == null || _game == null || _game!['id'] != gameId) return false;
    fc.controllerEvent(type, data, team, prio);
    return true;
  }

  /// A VIP's position report for the game's field.lua, as the input
  /// position.fix (decision P4R6; engine.py `field_position`). Only the
  /// script gets it. True when the script got it (a running game).
  bool fieldPosition(int gameId, Map<String, Object?> fix) {
    final fc = _fc, field = _field, game = _game;
    if (fc == null ||
        field == null ||
        game == null ||
        game['id'] != gameId ||
        fc.gameState != gameRunning) {
      return false;
    }
    field
      ..advance(fc.gameTimeMs)
      ..input('position.fix', fix);
    _afterField();
    return true;
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
    if (live && _keyLost) out['key_lost'] = true;
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
    final boxLang = _boxLangFor(spec['console_lang']);
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
      'channel_hz': fieldChannel,
      'max_hops': config.maxHops,
      'joined': false,
      'squads': squads,
      'team_info': <String, Object?>{},
    };
    store.createGame(game, key: config.persistGameKey ? key : null);
    if (boxLang != null) store.setSetting('box_lang:$id', boxLang);
    _activate(store.game(id)!, key);
    final out = getGame(id);
    _emit({'type': 'game', 'game': out});
    return out;
  }

  void _activate(Map<String, Object?> game, Uint8List key) {
    final gameNode = (game['node_id'] as int?) ?? config.nodeId;
    final hops = (game['max_hops'] as int?) ?? config.maxHops;
    _radio = transport != null
        ? null
        : RadioTransport(
            modem: modem,
            store: store,
            gameId: game['id']! as int,
            nodeId: gameNode,
            maxHops: hops,
            channelHz: (game['channel_hz'] as int?) ?? fieldChannel,
            key: key,
            wifi: _toWifi,
          );
    // The key's tag (not secret) outlives the key, so a GAME_OVER can still
    // name this game after a restart without the key (decision OT-13; sent
    // by the re-invites, slice S7).
    store.setSetting('key_tag:${game['id']}', epochTag(key));
    final fc =
        FieldController(
            transport: _radio ?? transport!,
            gameId: game['id']! as int,
            teams: (game['teams']! as List).cast<String>(),
            nodeId: gameNode,
            maxHops: hops,
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
    modem?.clear(); // the modem forgets the key
    _radio = null;
    _fc = null;
    _key = Uint8List(0);
    _game = null;
    _keyLost = false;
  }

  /// Ends the controller (the app stops it, or a test's restart): the game
  /// time is saved as the tick saves it and the field script's node is
  /// freed. A new engine on the same store takes the live game up again.
  void close() {
    _saveGameTime();
    _field?.close();
    _field = null;
  }

  /// After a restart: the live game in the store, taken up again as the Pi
  /// does (engine.py `_restore`).
  void _restore() {
    final game = store.liveGame();
    if (game == null) return;
    final id = game['id']! as int;
    final key = store.gameKey(id);
    if (key == null) {
      // ADR-P2-4: the key was never written (persist_game_key off).
      _game = game;
      _keyLost = true;
      return;
    }
    _activate(game, key);
    final fc = _fc!;
    fc.restoreAdjustments(_adjustments(id));
    for (final node in store.nodes(id)) {
      // Each box's counters as last reported: merging by maximum goes on
      // from them.
      final nodeId = node['node_id']! as int;
      final score = node['score'];
      if (score is Map) {
        fc.mergeCounters('node-$nodeId', {
          for (final e in score.entries)
            if (e.value is int) '${e.key}': e.value as int,
        });
      }
      final known = fc.registerNode(
        nodeId,
        '${node['name'] ?? 'node-$nodeId'}',
        '${node['role'] ?? ''}',
      );
      known.epoch = (node['epoch'] as int?) ?? 0;
      final battery = node['battery_pct'];
      if (battery is int) known.batteryPct = battery;
    }
    _restoreHealth(fc, id);
    // The controller's own events go on from their stored seq (PE24-42).
    var own = 0;
    for (final e in store.events(id)) {
      if (e['node'] == fc.nodeId && e['epoch'] == null) {
        own = max(own, e['seq']! as int);
      }
    }
    fc.restoreEventSeq(own);
    final saved = int.tryParse(store.getSetting('game_time:$id') ?? '') ?? 0;
    fc.restoreClock(
      switch (game['state']) {
        'running' => gameRunning,
        'paused' => gamePaused,
        _ => gameWaiting,
      },
      saved,
      nowMs(),
    );
    // The field script's points from earlier runs, and the script again.
    final runs = store.getSetting('field_scores:$id');
    _fieldScores = {};
    if (runs != null) {
      (jsonDecode(runs) as Map).forEach((k, v) {
        _fieldScores['$k'] = {
          for (final e in (v as Map).entries)
            if (e.value is int) '${e.key}': e.value as int,
        };
      });
    }
    _fieldScores.forEach(fc.mergeCounters);
    if (fc.gameState == gameRunning || fc.gameState == gamePaused) {
      try {
        _startField();
      } on ControllerError {
        // As the Pi: the game goes on without its field script (logged by
        // the shell, which sees no field_state from it).
      }
    }
  }

  /// After a restart: the health events' seq goes on from the stored ones,
  /// each box's link is what its last link event said (one that was online
  /// has node_offline_s from now to be heard again) and a battery.low
  /// already logged is not repeated (engine.py `_restore_health`).
  void _restoreHealth(FieldController fc, int gameId) {
    final health = [
      for (final t in healthEvents) ...store.events(gameId, type: t),
    ];
    fc.healthSeq = 0;
    for (final e in health) {
      if (e['epoch'] == null) {
        fc.healthSeq = max(fc.healthSeq, e['seq']! as int);
      }
    }
    final now = nowMs();
    for (final node in fc.nodes.values) {
      final mine = [
        for (final e in health)
          if (e['node'] == node.nodeId) e,
      ];
      Map<String, Object?>? last;
      for (final e in mine) {
        if (e['type'] == 'battery.low') continue;
        if (last == null ||
            (e['t']! as int) > (last['t']! as int) ||
            (e['t'] == last['t'] &&
                (e['seq']! as int) > (last['seq']! as int))) {
          last = e;
        }
      }
      if (last != null) {
        node
          ..link = (last['type']! as String).split('.')[1]
          ..linkChangedMs = node.link == 'online' ? now : null;
      }
      node.batteryLow = mine.any((e) => e['type'] == 'battery.low');
    }
  }

  /// The GM's adjustments per team, from the log (engine.py
  /// `_adjustments`).
  Map<String, int> _adjustments(int gameId) {
    final out = <String, int>{};
    for (final e in store.events(gameId, type: 'score.delta')) {
      final team = e['team'];
      final amount = (e['data'] as Map?)?['amount'];
      if (e['node'] == nodeId && team is String && amount is int) {
        out[team] = (out[team] ?? 0) + amount;
      }
    }
    return out;
  }

  void _saveGameTime({bool force = false}) {
    final fc = _fc;
    final game = _game;
    if (fc == null || game == null) return;
    final now = nowMs();
    if (force || now - _lastTimeSave >= gameTimeSaveMs) {
      _lastTimeSave = now;
      store.setSetting('game_time:${game['id']}', '${fc.gameTimeMs}');
    }
  }

  // --- the lifecycle ------------------------------------------------------

  FieldController _live(int id) {
    final game = store.game(id);
    if (game == null) throw ControllerError.notFound('no game $id');
    if (_game == null || _game!['id'] != id) {
      throw ControllerError.conflict('game $id is ${game['state']}, not live');
    }
    final fc = _fc;
    if (_keyLost || fc == null) {
      throw ControllerError.conflict(
        "this game's key was lost when the controller restarted; end it",
      );
    }
    return fc;
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
    _saveGameTime(force: true);
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
    _saveGameTime(force: true);
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

  /// Ends the live game; also one whose key was lost in a restart (its boxes
  /// are not told: a GAME_OVER over the field radio needs the field join
  /// key and the radio, slice S4, so `game_over_frame` is "no_join_key", as
  /// on a Pi without a join key).
  Map<String, Object?> endGame(int id, [String reason = '', String? winner]) {
    final game = store.game(id);
    if (game == null) throw ControllerError.notFound('no game $id');
    if (_game == null || _game!['id'] != id) {
      throw ControllerError.conflict('game $id is ${game['state']}, not live');
    }
    if (!_keyLost) {
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
      _saveGameTime(force: true);
    }
    store
      ..forgetGameKey(id) // the key does not outlive the game
      ..deleteSetting('key_tag:$id');
    positions?.endGame(id); // ADR-P3-6: positions last as long as the game
    _setState(id, 'ended', {'ended_at': _wall()});
    _deactivate();
    return {...publicGame(store.game(id)!), 'game_over_frame': 'no_join_key'};
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

  // --- the boxes' language (join key 15) -----------------------------------

  /// GET /api/v1/settings/box-language: the field setting ("auto": the
  /// language of the console that creates the game) and the live game's.
  Map<String, Object?> boxLanguage() {
    final g = _game;
    final live = g == null ? null : store.getSetting('box_lang:${g['id']}');
    return {
      'box_language': store.getSetting('box_language') ?? 'auto',
      'choices': boxLanguages,
      'game_box_language': live ?? (g == null ? null : 'en'),
    };
  }

  Map<String, Object?> setBoxLanguage(Object? value) {
    if (value is! String || !boxLanguages.contains(value)) {
      throw ControllerError('box_language: one of ${boxLanguages.join(', ')}');
    }
    store.setSetting('box_language', value);
    return boxLanguage();
  }

  String? _boxLangFor(Object? consoleLang) {
    final setting = store.getSetting('box_language') ?? 'auto';
    if (setting != 'auto') return setting;
    if (consoleLang == null) return null;
    if (consoleLang is! String ||
        !boxLanguages.contains(consoleLang) ||
        consoleLang == 'auto') {
      throw ControllerError('console_lang: pt, en or de');
    }
    return consoleLang;
  }

  // --- joins (ADR-P2-12, protocol/join.md) ---------------------------------

  /// The field join key (32 bytes; never on the API): join payloads are
  /// sealed with it. Empty: no joins (503), as on a Pi without one.
  Uint8List joinKey = Uint8List(0);

  /// The field CA's SHA-256 and the phone's https addresses, once it serves
  /// HTTPS (slice S6, field_tls.dart): join payload keys 13 and 14 for a
  /// box or an Android prop (the Pi's `ca_sha256` and `link_urls`). Null:
  /// no HTTPS, joins without them.
  Uint8List? caSha256;
  List<String> linkUrls = const [];

  Set<int> _issuedIds() {
    final saved = store.getSetting('issued_nodes:${_game!['id']}');
    return saved == null
        ? {}
        : {for (final n in jsonDecode(saved) as List) n as int};
  }

  Set<int> _usedIds(FieldController fc) {
    final g = _game!;
    return {
      nodeId,
      config.nodeId,
      broadcastNode,
      for (final n in (g['assignments']! as Map).keys) int.parse('$n'),
      ..._issuedIds(),
      ...fc.nodes.keys,
      if (g['controller_id'] is int) g['controller_id']! as int,
    };
  }

  /// A join payload for a box (kind "node") or a standby controller (kind
  /// "controller"), as the Pi's `issue_join`: the node id given or the
  /// lowest free one, never one a join was issued for or a box was heard on
  /// in this game (decision BN-18: two devices on one node id would reuse
  /// each other's nonces). A box's role goes into the game's assignments.
  /// The answer holds the game key (in the payload): the GM token only.
  Map<String, Object?> issueJoin(
    Map<String, Object?> spec, {
    Object? nodeIdValue,
    bool sameDevice = false,
  }) {
    final g = _game;
    if (g == null) {
      throw ControllerError.conflict('no live game: create a game first');
    }
    final id = g['id']! as int;
    final fc = _live(id);
    if (joinKey.isEmpty) {
      throw ControllerError.unavailable('no join key configured');
    }
    final kind = spec['kind'] ?? 'node';
    if (kind != 'node' && kind != 'controller') {
      throw ControllerError('kind: controller, node');
    }
    if (spec['name'] != null) {
      // Scenarios come with slice S7: no scenario node names here.
      throw ControllerError(
        "name: only a box of a scenario's game takes a scenario node's name",
      );
    }
    final mode = _mode(g['mode_id']);
    String role;
    if (kind == 'node') {
      final roles = [for (final r in mode?.main.roles ?? const []) r.name]
        ..sort();
      var asked = spec['role'];
      if (asked == null && roles.length == 1) asked = roles.single;
      if (asked is! String || !roles.contains(asked)) {
        throw ControllerError('role: one of $roles');
      }
      role = asked;
    } else {
      role = 'controller';
    }
    nodeIdValue ??= spec['node_id'];
    final int node;
    if (nodeIdValue == null) {
      final used = _usedIds(fc);
      node = [
        for (var i = 1; i < 0xffff; i++) i,
      ].firstWhere((i) => !used.contains(i));
    } else {
      node = _int(nodeIdValue, 'node_id');
    }
    if (node < 1 || node > 0xfffe || node == nodeId) {
      throw ControllerError("node id $node: 1-65534, not the controller's");
    }
    final assignments = Map<String, Object?>.of(
      (g['assignments']! as Map).cast<String, Object?>(),
    );
    final assigned = assignments['$node'];
    if (kind == 'controller' &&
        (assigned != null || fc.nodes.containsKey(node))) {
      throw ControllerError.conflict('node id $node is a box in this game');
    }
    final issued = _issuedIds();
    final known = fc.nodes[node];
    if (!sameDevice &&
        (issued.contains(node) || (known != null && known.heard))) {
      throw ControllerError.conflict(
        'node id $node already has a box in this game: two boxes on one '
        "node id would reuse each other's radio nonces. A replacement box "
        'gets a new node id (Join).',
      );
    }
    final params = (g['params'] as Map?)?.cast<String, Object?>() ?? {};
    // Android props link over Wi-Fi with the field CA and the phone's
    // addresses (keys 13 and 14, RFC 0001 Amendment 4, proposed), as the
    // Pi's issue_join: a payload too long with them is made without them.
    final ca = caSha256;
    final withLink = kind == 'node' && ca != null;
    JoinPayload joinWith({required bool link}) => JoinPayload(
      gameId: id,
      gameKey: _key,
      nodeId: node,
      controllerId: nodeId,
      channelHz: (g['channel_hz'] as int?) ?? config.channelHz,
      maxHops: (g['max_hops'] as int?) ?? config.maxHops,
      teams: (g['teams']! as List).cast<String>(),
      modeId: g['mode_id']! as String,
      role: role,
      gameSeed: (g['game_seed']! as int) & 0xffffffff,
      params: params.isEmpty ? null : params,
      kind: kind == 'node' ? JoinKind.node : JoinKind.controller,
      lang: store.getSetting('box_lang:$id'),
      caSha256: link ? ca : null,
      urls: link && linkUrls.isNotEmpty ? linkUrls.take(3).toList() : null,
    );
    var join = joinWith(link: withLink);
    var linked = withLink;
    Uint8List payload;
    try {
      try {
        payload = encodeJoin(join, joinKey);
      } on JoinException catch (e) {
        if (!withLink || e.reason != JoinFailure.length) rethrow;
        join = joinWith(link: false);
        linked = false;
        payload = encodeJoin(join, joinKey);
      }
    } on JoinException catch (e) {
      throw ControllerError.conflict(
        'this game does not fit in a join payload: ${e.message}',
      );
    }
    if (!issued.contains(node)) {
      store.setSetting(
        'issued_nodes:$id',
        jsonEncode((issued..add(node)).toList()..sort()),
      );
    }
    if (kind == 'node' && assigned != role) {
      assignments['$node'] = role;
      g['assignments'] = assignments;
      store.updateGame(id, {'assignments': assignments});
      fc.registerNode(node, 'node-$node', role);
    }
    final out = <String, Object?>{
      'game': id,
      'node_id': node,
      'kind': kind,
      'role': role,
      'name': null,
      'controller_id': nodeId,
      'channel_hz': join.channelHz,
      'max_hops': join.maxHops,
      'bytes': payload.length,
      'text': joinToText(payload),
      'payload_hex': _hexOf(payload),
      'ndef_tag_hex': _hexOf(type2Memory(payload, joinNdefType)),
      'wifi_link': linked,
    };
    _emit({
      'type': 'join',
      'game': id,
      'node_id': node,
      'kind': kind,
      'role': role,
      'name': null,
    });
    return out;
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
      'key_lost': _keyLost,
      'radio': radioState,
      'modem': {
        'ident': modem?.ident,
        'status': modem?.status,
        'reconnects': modem?.reconnects ?? 0,
      },
      'tx_epoch': _radio?.epoch,
      'tx_status': Map.of(_txStatus),
      'field_channel_hz': fieldChannel,
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
    checkin?.purge(); // retention (ADR-P3-13), at most every 10 minutes
    final fc = _fc;
    if (fc == null) return;
    fc.tick(nowMs());
    positions?.tick();
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
      return;
    }
    _saveGameTime();
  }

  // --- the radio ------------------------------------------------------------

  /// Android props on Wi-Fi (prop links): set by their server; true when one
  /// of them took the message.
  bool Function(int type, Uint8List payload)? wifiForward;

  bool _toWifi(int type, Uint8List payload) =>
      wifiForward?.call(type, payload) ?? false;

  /// A packet the radio heard and authenticated.
  void _onRx(RadioRx rx) {
    onPacket(
      rx.header,
      rx.payload,
      epoch: rx.epoch,
      rssi: rx.rssi,
      snr: rx.snr,
    );
  }

  void _onTxAck(int seq, String status) {
    _txStatus[status] = (_txStatus[status] ?? 0) + 1;
    if (status != 'ok') {
      _emit({
        'type': 'system',
        'kind': 'tx.failed',
        'seq': seq,
        'status': status,
      });
    }
  }

  void _onModemState(String state) {
    final m = modem;
    if (m == null) return;
    if (state == ModemState.up) {
      _emit({'type': 'system', 'kind': 'radio.up'});
      final fc = _fc;
      if (fc == null) {
        m.setChannel(fieldChannel); // no game: listen on the field's channel
      } else {
        final known = {
          for (final n in fc.nodes.values)
            if (n.epoch != 0) n.nodeId: n.epoch,
        };
        if (known.isNotEmpty) m.setPeerEpochs(known);
      }
    } else if (state == ModemState.down) {
      _emit({'type': 'system', 'kind': 'radio.down'});
    }
  }

  // --- FieldController hooks ----------------------------------------------

  void _onEvent(Map<String, Object?> record) {
    final game = _game;
    if (game == null) return;
    final id = game['id']! as int;
    if (!store.insertEvent(id, record)) return;
    _emit({'type': 'event', 'game': id, 'event': logRecord(record)});
    positions?.onEvent(id, record);
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

String _hexOf(List<int> b) =>
    [for (final x in b) x.toRadixString(16).padLeft(2, '0')].join();

/// The boxes' screen languages (join key 15): "auto" is the console's.
const boxLanguages = ['auto', 'pt', 'en', 'de'];

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
