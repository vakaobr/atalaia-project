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
/// positions deleted when a game ends. Slice S7b: presets, mode uploads and
/// signed packages ([modes], controller_modes.dart; [signedModes]), the
/// modes sent to boxes ([modeFetch]), scenarios ([scenarios]), role
/// packages in a game and team branding ([branding]). Slice S7c: the hooks of the boxes over the radio ([boxes],
/// [pairing], [adoption], [firmware]): field and pair frames routed to
/// them, GAME_OVER when a game ends, [startGuards], [sendUpdate]. Slice S6:
/// the shell runs the engine on the
/// controller's own isolate (controller_host.dart) and gives it the field
/// CA and the phone's addresses for join keys 13 and 14 ([caSha256],
/// [linkUrls]).
///
/// Slice S7a (PE24-74): the field plan ([field], controller_field.dart) and
/// the channel choice and noise scan ([channel], controller_channel.dart).
///
/// Slice S7 (PE24-118 onward): failover (controller_failover.dart): the
/// CLAIM election on every game ([promote]; `failover_mode` manual or
/// auto), a game joined as a standby controller from a join payload of
/// kind "controller" ([joinAsStandby]), the standby following the leader's
/// TIME beacons and taking over its field.lua when it wins, so a phone and
/// a Pi can be each other's standby (PE24-2).
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
import '../protocol/radio_region.dart';
import '../radio/rf_codec.dart';
import '../security/bytes.dart' show hexDecode;
import '../security/ndef.dart';
import 'controller_adoption.dart';
import 'controller_boxes.dart';
import 'controller_branding.dart';
import 'controller_channel.dart';
import 'controller_failover.dart';
import 'controller_checkin.dart';
import 'controller_field.dart';
import 'controller_firmware.dart';
import 'controller_mode_fetch.dart';
import 'controller_modes.dart';
import 'controller_pairing.dart';
import 'controller_pod_config.dart';
import 'controller_positions.dart';
import 'controller_radio.dart';
import 'controller_scenarios.dart';
import 'controller_schedule.dart';
import 'controller_signed_modes.dart';
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
    this.region = 'eu868',
    this.maxHops = 2,
    this.failoverMode = 'manual',
    this.powerSource = 1,
    this.batteryPct = 100,
    this.storageOk = true,
    this.healthNodeOfflineS = 120,
    this.healthBatteryLowPct = 20,
    this.persistGameKey = true,
    this.controllerPaceMs = 0,
  });

  /// This controller's short id on the radio.
  final int nodeId;
  final int channelHz;

  /// The field's radio region until the GM picks one (`[radio] region`,
  /// radio_region.dart): "eu868" or "as923-tw".
  final String region;
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

  /// The gap the controller leaves between its own frames (ACKs, TIME, CMDs),
  /// after the previous one was on the air; 0 (the default until the field
  /// test decides): no pacing; 800 is the relay study's H_paced (decision
  /// SL-13; the Pi's `[radio] controller_pace_ms`).
  final int controllerPaceMs;

  /// ADR-P2-8's priority score, as the Pi computes it (a link of 100).
  int get priority => priorityScore(powerSource, batteryPct, storageOk, 100);
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
    // A scenario's node names, as the GM gave them to the boxes in the Join tab
    // (M6-7, P4R8); else the box's own name (engine.py `_nodes`).
    final gameId = engine._game?['id'];
    final names = gameId is int
        ? engine.scenarios?.nodeNames(gameId) ?? const <int, String>{}
        : const <int, String>{};
    return [
      for (final n in all)
        if (role == null || n.role == role)
          {
            'id': n.nodeId,
            'name': names[n.nodeId] ?? n.name,
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
       _wall =
           wallSeconds ?? (() => DateTime.now().microsecondsSinceEpoch / 1e6),
       _random = random ?? Random.secure() {
    this.modes = ControllerModes(
      this.store,
      core: core,
      catalog: modes,
      wallSeconds: _wall,
    );
    final watch = Stopwatch()..start();
    _clock = clockMs ?? () => watch.elapsedMilliseconds;
    _t0 = _clock();
    final m = modem;
    if (m != null) {
      m
        ..onRx = _onRx
        ..onTxAck = _onTxAck
        ..onState = _onModemState
        // Field and pair frames (slice S7c): pairing's, else the invites'.
        ..onFieldRx = _onFieldRx
        ..onFieldAck = _onFieldAck
        ..onError = (code, message) => _emit({
          'type': 'system',
          'kind': 'modem.error',
          'code': code,
          'message': message,
        });
    }
    _restore();
    _tellModemLanguage();
  }

  final ControllerConfig config;
  final ControllerStore store;

  /// The built-in and uploaded packages and the presets (slice S7b).
  late final ControllerModes modes;

  /// Signed mode packages (slice S7b): set by [ControllerSignedModes]'s
  /// user (the host); null: 503, as on a Pi without them.
  ControllerSignedModes? signedModes;

  /// The modes sent to boxes (slice S7b): set by [ControllerModeFetch].
  ControllerModeFetch? modeFetch;

  /// Scenarios (slice S7b): set by [ControllerScenarios].
  ControllerScenarios? scenarios;

  /// Field and team branding (slice S7b): set by [ControllerBranding].
  ControllerBranding? branding;

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

  /// The live game's radio transport (null without a game, or with a test's
  /// [transport]): its queue, for the status and the tests.
  RadioTransport? get radioTransport => _radio;
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

  /// The field's channel and its noise scan (slice S7a): set by
  /// [ControllerChannel]'s constructor.
  ControllerChannel? channel;

  /// The field plan: images, levels, map positions, map features and the
  /// boxes' places (slice S7a): set by [ControllerField]'s constructor.
  ControllerField? field;

  /// Slice S7c (controller_boxes.dart, controller_pairing.dart,
  /// controller_adoption.dart, controller_firmware.dart): the free boxes
  /// and invites over the radio, GAME_OVER, pairing by code, field cards
  /// and firmware updates; each set by its constructor (the first two only
  /// with a field join key, as the Pi's reinvite and pairing).
  ControllerBoxes? boxes;
  ControllerPairing? pairing;
  ControllerAdoption? adoption;
  ControllerFirmware? firmware;

  /// The I/O pods' settings over the radio (controller_pod_config.dart).
  ControllerPodConfig? podConfig;

  /// Slice S7: the schedule pulled from the site server
  /// (controller_schedule.dart), the site sync (controller_sync.dart) and
  /// its status for `GET /api/v1/controller`, and the remote GM
  /// (controller_remote_gm.dart); each set by its constructor.
  ControllerSchedule? schedule;
  Map<String, Object?> Function()? syncStatus;

  /// `GET /api/v1/remote-gm`'s view (set by controller_remote_gm.dart) and
  /// `GET /api/v1/atak`'s status (set by the host with
  /// controller_atak.dart's emitter); null: off.
  Map<String, Object?> Function(int limit)? remoteGmView;
  Map<String, Object?> Function()? atakStatus;

  /// Why the live game may not start now (firmware updates on their way,
  /// slice S7c; boxes still fetching its modes, slice S7b; engine.py
  /// `start_guards`), or null: checked by [startGame] before the
  /// start check, never overridden by `force`.
  final startGuards = <String? Function()>[];

  /// The live game came back after a restart without its key: it can only
  /// be ended (ADR-P2-4).
  bool _keyLost = false;
  int _lastTimeSave = 0;

  int nowMs() => _clock() - _t0;

  /// The live game's key (ADR-P2-2): for join payloads (slice S4); never on
  /// the API. Empty with no live game, or when it was lost in a restart.
  Uint8List get gameKey => _key;

  bool get keyLost => _keyLost;

  /// Whether this controller is in charge of the live game: it leads the
  /// election and has the game's key (slice S7: the remote GM's
  /// `in_charge`, the ATAK feed).
  bool get inCharge => _fc?.isController == true && !_keyLost;

  int get nodeId => (_game?['node_id'] as int?) ?? config.nodeId;

  /// The live game, or null.
  Map<String, Object?>? get liveGame => _game;

  /// "up", "down", "connecting", or "none" without a radio.
  String get radioState => modem?.state ?? transport?.state ?? 'none';

  /// The channel new games use: the GM's choice, else the configured one
  /// (engine.py `field_channel`).
  int get fieldChannel {
    final stored = int.tryParse(store.getSetting('radio.channel_hz') ?? '');
    if (stored != null) return stored;
    final region = fieldRegion;
    return region.channelOk(config.channelHz)
        ? config.channelHz
        : region.defaultChannelHz;
  }

  /// The field's radio region (engine.py `field_region`, radio_region.py):
  /// the GM's choice in the store, else the configured one.
  Region get fieldRegion =>
      regionsByCode[store.getSetting('radio.region')] ??
      regionsByCode[config.region] ??
      defaultRegion;

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
        !fc.isController ||
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

  /// The game's mode, composed with its other parts (controller_modes.dart),
  /// or null.
  ControllerMode? _mode(Object? modeId) => modes.modeOf(modeId);

  /// The scenario a game's id leads with, or null.
  ScenarioMeta? scenarioMeta(Object? modeId) => scenarios?.meta(modeId);

  Map<String, Object?> publicGame(Map<String, Object?> game) {
    final out = Map<String, Object?>.of(game);
    final live = _game != null && _game!['id'] == game['id'];
    out['live'] = live;
    final meta = scenarioMeta(game['mode_id']);
    final svc = scenarios;
    if (meta != null && svc != null) {
      // The staff's view: every objective, and the boxes the GM named.
      out['scenario'] = meta.staffView(
        svc.disclosure(game['id']! as int, meta),
      );
      final names = svc.nodeNames(game['id']! as int);
      final ids = names.keys.toList()..sort();
      out['scenario_nodes'] = {for (final k in ids) '$k': names[k]};
    }
    final fc = _fc;
    if (live && fc != null) {
      out['game_time_ms'] = fc.gameTimeMs;
      out['term'] = fc.term;
    }
    if (live && _keyLost) out['key_lost'] = true;
    if (live &&
        fc != null &&
        game['state'] == 'ready' &&
        game['joined'] != true) {
      out['start_check'] = startCheck();
    }
    return out;
  }

  /// A game as players and the read token see it: without its gm_only
  /// parameters (decision M5-1), and of its scenario only the objectives
  /// [viewer] may know (P4R24; engine.py `players_game`).
  Map<String, Object?> playersGame(
    Map<String, Object?> game, [
    ApiViewer? viewer,
  ]) {
    final mode = _mode(game['mode_id']);
    final params = game['params'];
    final out = <String, Object?>{
      ...game,
      'params': mode == null || params is! Map
          ? <String, Object?>{}
          : mode.publicParams(params.cast<String, Object?>()),
    }..remove('scenario_nodes');
    final meta = scenarioMeta(game['mode_id']);
    final svc = scenarios;
    if (meta != null && svc != null) {
      out['scenario'] = meta.playerView(
        viewer,
        game,
        svc.revealed(game['id']! as int),
        svc.disclosure(game['id']! as int, meta),
      );
    }
    return out;
  }

  /// An event as [viewer] may see it: gm_only data for staff, and a
  /// scenario objective's event for the players it is for (engine.py
  /// `event_for`).
  Map<String, Object?> eventFor(
    ApiViewer viewer,
    Object? gameId,
    Map<String, Object?> ev,
  ) {
    if (viewer.isStaffOf(gameId is int ? gameId : null)) return ev;
    if (!objectiveEvents.contains(ev['type']) || gameId is! int) {
      return publicEvent(ev);
    }
    final game = _game != null && _game!['id'] == gameId
        ? _game
        : store.game(gameId);
    final meta = game == null ? null : scenarioMeta(game['mode_id']);
    return scenarioEvent(
      viewer,
      ev,
      game,
      meta?.objectives,
      scenarios?.disclosure(gameId, meta) ?? 'members',
    );
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
    if (channel?.scanRunning ?? false) {
      throw ControllerError.conflict(
        'a channel scan is running; wait for it or cancel it first',
      );
    }
    final name = spec['name'] ?? '';
    if (name is! String || name.isEmpty || name.length > 64) {
      throw ControllerError('name: 1 to 64 characters');
    }
    Map<String, Object?>? preset;
    if (spec['preset_id'] != null) {
      preset = modes.preset(_int(spec['preset_id'], 'preset_id'));
      if (preset == null) {
        throw ControllerError.notFound('no preset ${spec['preset_id']}');
      }
    }
    var modeId = _truthy(spec['mode_id'])
        ? spec['mode_id']
        : preset?['mode_id'];
    final modifiers = _truthy(spec['modifiers'])
        ? spec['modifiers']
        : const <Object?>[];
    if (modifiers is! List || modifiers.any((m) => m is! String)) {
      throw ControllerError('modifiers: a list of modifier ids');
    }
    if (modifiers.isNotEmpty && modeId is String) {
      modeId = [modeId, ...modifiers].join(modeSeparator);
    }
    final ControllerMode mode;
    try {
      final pkg = modes.get(modeId);
      if (pkg == null) throw ControllerError('unknown mode $modeId');
      mode = pkg.mode;
    } on ModeException catch (e) {
      throw ControllerError('$e');
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
    final overrides = <String, Object?>{
      ...?(preset?['params'] as Map?)?.cast<String, Object?>(),
    };
    if (spec['params'] != null) {
      final given = spec['params'];
      if (given is! Map) throw ControllerError('params must be a map');
      overrides.addAll(given.cast<String, Object?>());
    }
    final Map<String, Object?> params;
    try {
      params = mode.resolveParams(overrides, teams);
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
    final roles = mode.roles.keys.toSet();
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
    // Who of a squad is told its scenario objectives: the GM's choice, else
    // the scenario's (SQ-4).
    final disclosure = ControllerScenarios.checkDisclosure(
      spec['objective_disclosure'],
    );
    if (disclosure != null && scenarioMeta(mode.id) == null) {
      throw ControllerError(
        'objective_disclosure: only a scenario\'s game has objectives to disclose',
      );
    }
    // Team branding (decisions BR12-BR15): display names and crests next to
    // the colours, which stay the team names the boxes and the radio know.
    final b = branding;
    final teamInfo = b != null
        ? b.teamInfoFor(spec['team_info'], teams)
        : <String, Object?>{};
    if (b == null && _truthy(spec['team_info'])) {
      throw ControllerError(
        'team_info: team branding is not set up on this controller',
      );
    }
    final boxLang = _boxLangFor(spec['console_lang']);
    // A `lang` parameter left empty (Medic Kit, Hacking Terminal, VIP /
    // Payload) is the game's language, English when it has none (as the
    // Pi controller does: a script cannot read the box's language, P5H-23).
    fillLangParam(mode.params['lang']?['type'] == 'string', params, boxLang);
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
      'preset_id': preset?['id'],
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
      'team_info': teamInfo,
    };
    store.createGame(game, key: config.persistGameKey ? key : null);
    if (boxLang != null) {
      store.setSetting('box_lang:$id', boxLang);
      _tellModemLanguage(boxLang);
    }
    if (disclosure != null) scenarios?.storeDisclosure(id, disclosure);
    _activate(store.game(id)!, key);
    final out = getGame(id);
    _emit({'type': 'game', 'game': out});
    return out;
  }

  /// Puts a game on the radio (engine.py `_activate`): [lead] false for a
  /// game joined as a standby controller, which follows the TIME beacons
  /// until it is promoted (ADR-P2-8; PE24 slice S7).
  void _activate(Map<String, Object?> game, Uint8List key, {bool lead = true}) {
    final gameNode = (game['node_id'] as int?) ?? config.nodeId;
    final election = Election(
      gameNode,
      config.priority,
      mode: config.failoverMode,
    );
    if (lead) {
      election.lead((game['term'] as int?) ?? 1, nowMs());
    } else {
      // A joined standby restarted: the term it knew, so a claim after the
      // restart is higher than the leader's and the boxes follow it
      // (decision PE24-119; a new join's term is 0).
      election
        ..term = max(election.term, (game['term'] as int?) ?? 0)
        ..follow(nowMs());
    }
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
            paceMs: config.controllerPaceMs,
            nowMs: nowMs,
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
            election: election,
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
      ..onScores = _onScores
      ..onRole = _onRole;
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
    _radio
        ?.flush(); // frames still waiting for their gap go now: the key goes next
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
    // A joined standby restarts as a follower; the GM promotes it again if
    // needed.
    _activate(game, key, lead: game['joined'] != true);
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
    if (fc.isController &&
        (fc.gameState == gameRunning || fc.gameState == gamePaused)) {
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
    if (!fc.isController) {
      throw ControllerError.conflict(
        'this controller is on standby (term ${fc.term}); promote it first',
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
    // A box still fetching the game's modes (or whose fetch failed) has not
    // joined until its HELLO (controller_mode_fetch.dart).
    final fetch = modeFetch;
    if (fetch != null) out.removeWhere((n, _) => fetch.holds(n));
    final ids = out.keys.toList()..sort();
    return [for (final id in ids) (id, out[id]!)];
  }

  /// The roles that must each have a joined node before the game starts: a
  /// scenario's boxes' roles, else every role of the game's mode and role
  /// packages unless its manifest says `needed: false` (engine.py
  /// `_needed_roles`).
  List<String> _neededRoles() {
    final meta = scenarioMeta(_game!['mode_id']);
    if (meta != null) {
      final boxes = meta.boxNodes().values.toSet().toList()..sort();
      if (boxes.isNotEmpty) return boxes;
    }
    final mode = _mode(_game!['mode_id']);
    if (mode == null) return [];
    return [
      for (final e in mode.roles.entries)
        if (!(e.value is Map && (e.value! as Map)['needed'] == false)) e.key,
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
    for (final guard in startGuards) {
      final reason = guard();
      if (reason != null) throw ControllerError.conflict(reason);
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
    final presetId = _game!['preset_id'];
    final preset = presetId is int ? modes.preset(presetId) : null;
    fc
      ..startGame(durationMs: _game!['duration_ms']! as int, nowMs: nowMs())
      ..controllerEvent(
        'game.start',
        {'preset': preset?['name'] ?? _game!['mode_id']},
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

  /// Ends the live game; also one whose key was lost in a restart. Its
  /// boxes are told over the field radio too (GAME_OVER, decisions OT-7 and
  /// OT-13; slice S7c), by its key's tag, so also after a restart without
  /// the key: `game_over_frame` says whether it went (engine.py
  /// `_tell_game_over`).
  Map<String, Object?> endGame(int id, [String reason = '', String? winner]) {
    final game = store.game(id);
    if (game == null) throw ControllerError.notFound('no game $id');
    if (_game == null || _game!['id'] != id) {
      throw ControllerError.conflict('game $id is ${game['state']}, not live');
    }
    final standby = _fc;
    if (standby != null && !standby.isController && _game!['joined'] == true) {
      return _leaveStandby(id, reason.isEmpty ? 'left' : reason);
    }
    if (!_keyLost) {
      final fc = _live(id);
      _radio
        ?..discard() // stale CMDs and TIMEs go; the ACKs stay (boxes leave on them)
        ..flush(); // and go now, so a full queue cannot take the end's CMD and TIME
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
    final tag = _key.isNotEmpty
        ? epochTag(_key)
        : store.getSetting('key_tag:$id');
    store.forgetGameKey(id); // the key does not outlive the game
    positions?.endGame(id); // ADR-P3-6: positions last as long as the game
    _setState(id, 'ended', {'ended_at': _wall()});
    _deactivate();
    boxes?.forgetGame(id); // no invite into a game that is over
    final told = _tellGameOver(game, tag);
    return {...publicGame(store.game(id)!), 'game_over_frame': told};
  }

  /// GAME_OVER to the game's boxes over the field radio (engine.py
  /// `_tell_game_over`): "sent", "no_tag" (no key tag kept), "no_join_key"
  /// or "no_radio" (no radio, or one that carries no field frames).
  String _tellGameOver(Map<String, Object?> game, String? tag) {
    final id = game['id']! as int;
    store.deleteSetting('key_tag:$id');
    if (game['joined'] == true) return 'standby';
    final b = boxes;
    final String told;
    if (tag == null) {
      told = 'no_tag';
    } else if (b == null) {
      told = 'no_join_key';
    } else if (b.gameOver(
      id,
      hexDecode(tag),
      (game['channel_hz'] as int?) ?? config.channelHz,
    )) {
      told = 'sent';
    } else {
      told = 'no_radio';
    }
    // A game ended without its key reaches its boxes only this way (the
    // Pi logs it; the result is in the answer, nothing more on the stream).
    return told;
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
    final commands = _mode(_game!['mode_id'])?.commands ?? const {};
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

  /// A game's team display names and crests changed (controller_branding.dart).
  void updateTeamInfo(int gameId, Map<String, Object?> info) {
    store.updateGame(gameId, {'team_info': info});
    if (_game != null && _game!['id'] == gameId) _game!['team_info'] = info;
  }

  /// PUT /api/v1/games/{id}/objective-disclosure {"disclosure": "members" |
  /// "leader" | null}: who of a squad is told its scenario objectives, until
  /// the game ends (SQ-4; engine.py `set_objective_disclosure`). The players'
  /// apps get the game again, so a change shows at once.
  Map<String, Object?> setObjectiveDisclosure(int gameId, Object? spec) {
    final game = store.game(gameId);
    if (game == null) throw ControllerError.notFound('no game $gameId');
    if (game['state'] == 'ended') {
      throw ControllerError.conflict('game $gameId has ended');
    }
    final svc = scenarios;
    if (svc == null || scenarioMeta(game['mode_id']) == null) {
      throw ControllerError(
        'this game has no scenario, so no objectives to disclose',
      );
    }
    if (spec is! Map || spec.length != 1 || !spec.containsKey('disclosure')) {
      throw ControllerError(
        'the body is {"disclosure": "members" | "leader" | null}',
      );
    }
    svc.storeDisclosure(
      gameId,
      ControllerScenarios.checkDisclosure(spec['disclosure']),
    );
    final out = getGame(gameId);
    _emit({'type': 'game', 'game': out});
    return out;
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
    _tellModemLanguage();
    return boxLanguage();
  }

  /// The language of the USB modem's own OLED (decision MOD-2; the Pi's
  /// `_tell_modem_language`): the field's setting, with "auto" the live
  /// game's boxes' language, and nothing while no game says one.
  void _tellModemLanguage([String? lang]) {
    final m = modem;
    if (m == null) return;
    if (lang == null) {
      final setting = store.getSetting('box_language') ?? 'auto';
      if (setting != 'auto') {
        lang = setting;
      } else if (_game == null) {
        return;
      } else {
        lang = store.getSetting('box_lang:${_game!['id']}');
      }
    }
    m.setLanguage(lang);
  }

  String? _boxLangFor(Object? consoleLang) {
    final setting = store.getSetting('box_language') ?? 'auto';
    if (setting != 'auto') return setting;
    if (consoleLang == null) return null;
    if (consoleLang is! String ||
        !boxLanguages.contains(consoleLang) ||
        consoleLang == 'auto') {
      throw ControllerError('console_lang: pt, en, de or zh-tw');
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
    String? device,
    int? tier,
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
    final fetch = spec['fetch_modes'] ?? false;
    final forget = spec['forget_modes'] ?? false;
    if (fetch is! bool || forget is! bool) {
      throw ControllerError('fetch_modes and forget_modes: true or false');
    }
    if ((fetch || forget) && kind != 'node') {
      throw ControllerError('fetch_modes and forget_modes are for boxes');
    }
    final fetcher = modeFetch;
    if ((fetch || forget) && fetcher == null) {
      throw ControllerError.unavailable(
        'sending modes to boxes is not set up on this controller',
      );
    }
    // A scenario's box: the name the GM gives it (P4R8, M6-7), whose role is
    // the scenario's.
    final scenarioName = spec['name'];
    if (scenarioName != null) {
      final meta = scenarioMeta(g['mode_id']);
      final boxes = meta?.boxNodes() ?? const <String, String>{};
      if (kind != 'node' || meta == null) {
        throw ControllerError(
          "name: only a box of a scenario's game takes a scenario node's name",
        );
      }
      if (scenarioName is! String || !boxes.containsKey(scenarioName)) {
        throw ControllerError(
          "name: one of the scenario's boxes ${boxes.keys.toList()..sort()}",
        );
      }
      if (spec['role'] != null && spec['role'] != boxes[scenarioName]) {
        throw ControllerError(
          '$scenarioName is a ${boxes[scenarioName]} in the scenario, not a '
          '${spec['role']}',
        );
      }
      spec = {...spec, 'role': boxes[scenarioName]};
    }
    final mode = _mode(g['mode_id']);
    String role;
    if (kind == 'node') {
      final roles = mode?.roles.keys.toList() ?? <String>[]
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
    // A box's join names what it runs, with that part's parameters: for a
    // role of a role package, the package alone; else the main mode and its
    // modifiers. A standby controller gets the whole game.
    var modeId = g['mode_id']! as String;
    var params = (g['params'] as Map?)?.cast<String, Object?>() ?? {};
    if (kind == 'node' && mode != null) {
      modeId = mode.nodeModeId(role);
      params = mode.paramsFor(role, params);
    }
    if (fetch) {
      final why = fetcher!.refusal(modeId, tier);
      if (why != null) throw ControllerError.conflict(why);
    }
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
      modeId: modeId,
      role: role,
      gameSeed: (g['game_seed']! as int) & 0xffffffff,
      params: params.isEmpty ? null : params,
      kind: kind == 'node' ? JoinKind.node : JoinKind.controller,
      lang: store.getSetting('box_lang:$id'),
      caSha256: link ? ca : null,
      urls: link && linkUrls.isNotEmpty ? linkUrls.take(3).toList() : null,
      fetchModes: fetch,
      forgetModes: forget,
      region: fieldRegion.code, // key 18: a box refuses another region's game
    );
    var join = joinWith(link: withLink);
    var linked = withLink;
    Uint8List payload;
    try {
      try {
        payload = encodeJoin(join, joinKey);
      } on JoinException catch (e) {
        if (!withLink || e.reason != JoinFailure.length) rethrow;
        if (fetch) {
          // A box fetches over that link: without it the join is no use.
          throw ControllerError.conflict(
            "this game's join with the field CA and the controller's "
            'addresses is too long: the box could not fetch its modes',
          );
        }
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
    if (scenarioName is String) scenarios?.nameNode(id, node, scenarioName);
    final out = <String, Object?>{
      'game': id,
      'node_id': node,
      'kind': kind,
      'role': role,
      'name': scenarioName,
      'controller_id': nodeId,
      'channel_hz': join.channelHz,
      'max_hops': join.maxHops,
      'bytes': payload.length,
      'text': joinToText(payload),
      'payload_hex': _hexOf(payload),
      'ndef_tag_hex': _hexOf(type2Memory(payload, joinNdefType)),
      'wifi_link': linked,
      if (fetch || forget) ...{'fetch_modes': fetch, 'forget_modes': forget},
    };
    // Also a plain join: it ends a fetch made for that node before (P5D-18).
    fetcher?.track(
      id,
      node,
      role,
      modeId,
      device,
      fetch: fetch,
      forget: forget,
    );
    _emit({
      'type': 'join',
      'game': id,
      'node_id': node,
      'kind': kind,
      'role': role,
      'name': scenarioName,
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
      'leader': fc?.election.leader,
      'priority': config.priority,
      'role': fc?.election.role,
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
      'tx_queue': _radio == null
          ? null
          : {
              'queued': _radio!.queued,
              'dropped': _radio!.queueDropped,
              'pace_ms': _radio!.paceMs,
            },
      'tx_status': Map.of(_txStatus),
      'field_channel_hz': fieldChannel,
      'channel_confirmed': store.getSetting('radio.channel_confirmed') == '1',
      'sync': syncStatus?.call() ?? {'enabled': false},
    };
  }

  // --- failover (PE24 slice S7, controller_failover.dart) -----------------

  /// Manual failover (ADR-P2-8; engine.py `promote`): stand for election on
  /// the live game; the CLAIM goes out now, and with no better claim heard
  /// this controller leads 5 s later.
  Map<String, Object?> promote() {
    final fc = _fc;
    if (fc == null) throw ControllerError.conflict('no live game');
    if (fc.isController) {
      throw ControllerError.conflict(
        'already the controller (term ${fc.term})',
      );
    }
    try {
      fc.promote(nowMs());
    } on ElectionException catch (e) {
      throw ControllerError.conflict(e.message);
    }
    return status();
  }

  /// Takes a game as a standby controller from a join text of kind
  /// "controller" (engine.py `join_as_standby`): the game is stored and put
  /// on the radio with the payload's key, node id and channel, and this
  /// controller follows the TIME beacons until the GM promotes it (or, with
  /// `failover_mode = auto`, until the leader falls silent). Answers with
  /// the game.
  Map<String, Object?> joinAsStandby(Object? text) {
    if (_game != null) {
      throw ControllerError.conflict(
        'game ${_game!['id']} is still live here; end it first',
      );
    }
    if (joinKey.isEmpty) {
      throw ControllerError.unavailable('no join key configured');
    }
    if (text is! String) {
      throw ControllerError('text: the join text (atalaia:join:...)');
    }
    final JoinPayload j;
    try {
      j = decodeJoin(joinFromText(text), joinKey);
    } on JoinException catch (e) {
      throw ControllerError(
        'join payload refused (${e.reason.name}): ${e.message}',
      );
    }
    if (j.kind != JoinKind.controller) {
      throw ControllerError(
        'this join payload is for a box, not a standby controller',
      );
    }
    // The standby keeps to its field's radio region (RF-AS923, as the Pi).
    if (j.region != fieldRegion.code) {
      throw ControllerError.conflict(
        'this game is in the ${j.region} radio region and this '
        "controller's field in ${fieldRegion.code}; change the region in "
        'the radio settings first',
      );
    }
    final ModePackage? pkg;
    try {
      pkg = modes.get(j.modeId);
    } on ModeException catch (e) {
      throw ControllerError.conflict('mode ${j.modeId}: $e');
    }
    if (pkg == null) {
      // A scenario is an upload: the standby needs it too (decisions M6-1,
      // M8-3).
      final have = {for (final p in modes.all()) p.mode.id};
      final missing = [
        for (final m in j.modeId.split(modeSeparator))
          if (!have.contains(m)) m,
      ];
      throw ControllerError.conflict(
        'mode ${j.modeId} is not installed on this controller (missing: '
        '${missing.join(', ')}); install a scenario here first, with the '
        "same manifest (the leading controller's GET /api/v1/scenarios/{id} "
        'gives it)',
      );
    }
    if (pkg.mode.fieldScript != null && core == null) {
      throw ControllerError.unavailable(
        'this mode has a field.lua and the core library is not loaded',
      );
    }
    final existing = store.game(j.gameId);
    if (existing != null) {
      throw ControllerError.conflict(
        'this controller already has a game ${j.gameId} '
        '(${existing['state']})',
      );
    }
    final Map<String, Object?> params;
    try {
      params = pkg.mode.resolveParams(j.params ?? const {}, j.teams);
    } on ModeException catch (e) {
      throw ControllerError('$e');
    }
    final game = <String, Object?>{
      'id': j.gameId,
      'name': 'Game ${j.gameId} (standby)',
      'mode_id': pkg.mode.id,
      'preset_id': null,
      'teams': j.teams,
      'params': params,
      'assignments': <String, Object?>{},
      'duration_ms': 0,
      'game_seed': j.gameSeed,
      'state': 'ready',
      'term': 0,
      'created_at': _wall(),
      'node_id': j.nodeId,
      'channel_hz': j.channelHz,
      'max_hops': j.maxHops,
      'joined': true,
      'controller_id': j.controllerId,
      'squads': 0,
      'team_info': <String, Object?>{},
    };
    store.createGame(game, key: config.persistGameKey ? j.gameKey : null);
    // Promoted, it issues joins in the same language.
    final lang = j.lang;
    if (lang != null) store.setSetting('box_lang:${j.gameId}', lang);
    _activate(store.game(j.gameId) ?? game, j.gameKey, lead: false);
    final out = getGame(j.gameId);
    _emit({'type': 'game', 'game': out});
    return out;
  }

  /// A standby controller stops following a game (the GM left it, or it
  /// ended; engine.py `_leave_standby`).
  Map<String, Object?> _leaveStandby(int id, String reason) {
    final fc = _fc;
    if (fc != null) {
      store.saveScores(id, fc.totalScores);
      _saveGameTime(force: true);
    }
    store
      ..forgetGameKey(id)
      ..deleteSetting('key_tag:$id');
    final out = _setState(id, 'ended', {'ended_at': _wall()});
    _deactivate();
    return publicGame(store.game(id) ?? out);
  }

  /// On standby: the stored game follows the leader's TIME beacons
  /// (engine.py `_follow_state`).
  void _followState(FieldController fc) {
    final game = _game!;
    final id = game['id']! as int;
    final state = switch (fc.gameState) {
      gameRunning => 'running',
      gamePaused => 'paused',
      gameEnded => 'ended',
      _ => 'ready',
    };
    if (fc.durationMs != game['duration_ms']) {
      game['duration_ms'] = fc.durationMs;
      store.updateGame(id, {'duration_ms': fc.durationMs});
    }
    if (state == game['state']) return;
    if (state == 'ended') {
      _leaveStandby(id, 'the game ended');
      return;
    }
    final times = <String, Object?>{};
    if (state == 'running' && game['started_at'] == null) {
      times['started_at'] = _wall();
      game['started_at'] = times['started_at'];
    }
    _setState(id, state, times);
  }

  /// The election's role changed (engine.py `_on_role`): the term is kept
  /// with the game, the consoles are told, and a takeover runs the game's
  /// field.lua here from now on (a new run; the old controller's runs'
  /// points are not known here, decision K5).
  void _onRole(String role, int term) {
    final game = _game;
    if (game != null) store.updateGame(game['id']! as int, {'term': term});
    _emit({'type': 'system', 'kind': 'role', 'role': role, 'term': term});
    final fc = _fc;
    if (role == electionLeader &&
        game != null &&
        fc != null &&
        (fc.gameState == gameRunning || fc.gameState == gamePaused)) {
      try {
        _startField();
      } on ControllerError {
        // As the Pi (logged there): the game goes on without its field.lua.
      }
    }
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
    // Slice S7c: invites and their retries, GAME_OVERs, pairing runs, with
    // or without a game.
    boxes?.tick(nowMs());
    pairing?.tick(nowMs());
    podConfig
        ?.tick(); // pod settings sent again until the pod says it took them
    branding?.purge(); // crests nothing refers to, at most every 10 minutes
    final fc = _fc;
    if (fc == null) return;
    _radio?.pump(nowMs()); // the next paced frame, if its gap has passed
    fc.tick(nowMs());
    positions?.tick();
    final field = _field;
    if (field != null && fc.gameState == gameRunning) {
      field.advance(fc.gameTimeMs);
      if (_afterField()) return;
    }
    final game = _game;
    if (game != null &&
        fc.isController &&
        fc.gameState == gameRunning &&
        fc.durationMs > 0 &&
        fc.gameTimeMs >= fc.durationMs) {
      endGame(game['id']! as int, 'time');
      return;
    }
    if (game != null && !fc.isController) {
      _followState(fc);
      if (_game == null) return;
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
    _radio?.txDone(seq, nowMs());
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
        // No game: listen on the field's channel (not during a scan, which
        // tunes the radio itself); pairing no longer listens on its own.
        if (!(channel?.scanRunning ?? false)) {
          m.setChannel(fieldChannel);
          modemMoved('the modem came back');
        }
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

  /// The modem was tuned to the field's channel (engine.py `_modem_moved`):
  /// pairing no longer listens on its own channel (slice S7c).
  void modemMoved(String why) => pairing?.channelMoved(why);

  /// Why the radio's channel may not move now (engine.py
  /// `_channel_lock_reason`): a live game, or a running noise scan (slice
  /// S7a's [channel]).
  String? channelLockReason() {
    final g = _game;
    if (g != null) {
      return "game ${g['id']} is live (${g['state']}); end it first";
    }
    if (channel?.scanRunning ?? false) return 'a channel scan is running';
    return null;
  }

  void _onFieldRx(Uint8List frame, int rssi, int snr) {
    final p = pairing;
    if (p != null && p.isOurs(frame)) {
      p.onFrame(frame, rssi, snr);
    } else {
      boxes?.onFieldRx(frame, rssi, snr);
    }
  }

  void _onFieldAck(int id, String status) {
    final p = pairing;
    if (p != null && p.ownsTx(id)) {
      p.onAck(id, status);
    } else {
      boxes?.onFieldAck(id, status);
    }
  }

  /// CMD update (RFC 0001 Amendment 6) to one box, only while the live game
  /// has not started (engine.py `send_update`; controller_firmware.dart
  /// checks the release and the box first): the packet's seq.
  int sendUpdate(int nodeId, Map<String, Object?> params) {
    final g = _game;
    if (g == null) {
      throw ControllerError.conflict(
        'no live game: the boxes to update must be joined to one',
      );
    }
    final fc = _live(g['id']! as int);
    if (g['state'] != 'ready') {
      throw ControllerError.conflict(
        "game ${g['id']} is ${g['state']}: firmware updates only before a "
        'game starts, never during one',
      );
    }
    final int? seq;
    try {
      seq = fc.sendUpdateCmd(params, dest: nodeId);
    } on FieldControllerException catch (e) {
      throw ControllerError(e.message);
    }
    if (seq == null) {
      throw ControllerError.unavailable(
        '${radioProblem() ?? 'the radio is $radioState'}; command not sent',
      );
    }
    return seq;
  }

  /// CMD pod (RFC 0001 Amendment 17) to the node id of the phone an I/O pod
  /// serves, only while the live game has not started or after it ended
  /// (engine.py `send_pod_config`; controller_pod_config.dart checks the
  /// settings and the node first): the packet's seq.
  int sendPodConfig(int nodeId, Map<String, Object?> params) {
    final g = _game;
    if (g == null) {
      throw ControllerError.conflict(
        "no live game: the pod's phone must be joined to one",
      );
    }
    final fc = _live(g['id']! as int);
    if (g['state'] != 'ready' && g['state'] != 'ended') {
      throw ControllerError.conflict(
        "game ${g['id']} is ${g['state']}: pod settings only before a game "
        'starts or after it ended',
      );
    }
    final int? seq;
    try {
      seq = fc.sendPodCmd(params, dest: nodeId);
    } on FieldControllerException catch (e) {
      throw ControllerError(e.message);
    }
    if (seq == null) {
      throw ControllerError.unavailable(
        '${radioProblem() ?? 'the radio is $radioState'}; command not sent',
      );
    }
    return seq;
  }

  /// "pod", "modem", or "none" without a radio (a test's transport is a
  /// "modem").
  String get radioKind => modem?.kind ?? (transport != null ? 'modem' : 'none');

  /// Why the radio cannot carry a packet now, in words (a pod with no radio
  /// chip, a link that is down, no radio linked at all), or null when it can
  /// (decision PE24-130): what the GM reads when an update's offer cannot go.
  String? radioProblem() {
    final m = modem;
    if (m == null) {
      if (transport == null) {
        return 'no radio is linked: plug an I/O pod with a radio, or a USB '
            'radio modem, into the phone';
      }
      return transport!.state == ModemState.up
          ? null
          : 'the radio is ${transport!.state}';
    }
    return m.cannotCarry;
  }

  // --- FieldController hooks ----------------------------------------------

  void _onEvent(Map<String, Object?> record) {
    final game = _game;
    if (game == null) return;
    final id = game['id']! as int;
    if (!store.insertEvent(id, record)) return;
    _emit({'type': 'event', 'game': id, 'event': logRecord(record)});
    if (record['type'] == objectiveRevealed) {
      // A hidden objective's names reach its players with the game (P4R24).
      final meta = scenarioMeta(game['mode_id']);
      final o = meta?.objectives[(record['data'] as Map?)?['objective']];
      if (o != null && o['visibility'] == 'hidden') {
        _emit({'type': 'game', 'game': publicGame(game)});
      }
    }
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
    if (kind == 'hello') {
      boxes?.onHello(node.nodeId, info['device_id'] as String?);
    }
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
    final fc = _fc;
    if (!mayEnd || end == null || fc == null || !fc.isController) return false;
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
const boxLanguages = ['auto', 'pt', 'en', 'de', 'zh-tw'];

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

/// Python's truth of a JSON value (None, False, 0, "", [] and {} are false).
bool _truthy(Object? v) => switch (v) {
  null || false || 0 || '' => false,
  final double d => d != 0,
  final List<Object?> l => l.isNotEmpty,
  final Map<Object?, Object?> m => m.isNotEmpty,
  _ => true,
};
