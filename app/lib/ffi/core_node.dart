// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// One node runtime in the core (atalaia/node.h), driven synchronously: the
/// Dart counterpart of `Node` in simulator/atalaia_sim/core.py.
///
/// A CoreNode belongs to the isolate that created it: its callbacks are
/// isolate-local (callbacks.dart). In the app only the game loop isolate
/// creates one (lib/core/game_loop_isolate.dart, ADR-P3-1); tests and the
/// mode-test runner also use it directly.
library;

import 'dart:convert';
import 'dart:ffi';

import 'package:ffi/ffi.dart';

import '../core/node_types.dart';
import 'bindings.dart';
import 'callbacks.dart';
import 'native_types.dart';

/// The core refused the node's setup (bad teams or parameters, no memory).
class NodeSetupException implements Exception {
  NodeSetupException(this.message);

  final String message;

  @override
  String toString() => 'NodeSetupException: $message';
}

final class CoreNode {
  CoreNode._(this._b, this._config, this._callbacks, this._node, this.teams);

  /// Creates the node, sets its teams and parameters and loads its script.
  /// Throws [NodeSetupException] if the core refuses the teams or
  /// parameters; a script that fails to load leaves the node halted, with
  /// [loaded] false and [lastError] saying why.
  factory CoreNode.create(
    AtalaiaCore core,
    NodeSpec spec, {
    NodeHandlers handlers = const NodeHandlers(),
    FieldOperations? fieldOps,
  }) {
    final b = core.bindings;
    late final CoreNode self;
    final callbacks = NativeCallbacks(
      handlers,
      fieldOps: fieldOps,
      clock: () => self._alive ? b.nodeTime(self._node) : 0,
    );
    final config = calloc<NodeConfig>();
    config.ref
      ..nodeId = spec.nodeId & 0xffff
      ..gameSeed = spec.gameSeed & 0xffffffff
      ..memLimit = spec.memLimit
      ..instrLimit = spec.instrLimit
      ..alloc = nullptr
      ..allocUd = nullptr;
    callbacks.fill(config);
    final node = b.nodeCreate(config);
    if (node == nullptr) {
      callbacks.close();
      calloc.free(config);
      throw NodeSetupException('atalaia_node_create failed (out of memory)');
    }
    self = CoreNode._(
      b,
      config,
      callbacks,
      node,
      List.unmodifiable(spec.teams),
    );
    try {
      self._setTeams(spec.teams);
      self._setParams(spec.params);
    } catch (_) {
      self.close();
      rethrow;
    }
    self.loaded = self._load(spec.source, spec.chunkName);
    return self;
  }

  final AtalaiaBindings _b;
  final Pointer<NodeConfig> _config;
  final NativeCallbacks _callbacks;
  final Pointer<AtalaiaNode> _node;

  /// The game's team names; team id i is teams[i - 1].
  final List<String> teams;

  /// Whether the script compiled and its top level ran.
  bool loaded = false;
  bool _alive = true;

  /// Exceptions thrown by this node's handlers (they cannot cross into C).
  List<Object> get callbackErrors => _callbacks.errors;

  void _setTeams(List<String> names) {
    final arr = calloc<Pointer<Utf8>>(names.isEmpty ? 1 : names.length);
    for (var i = 0; i < names.length; i++) {
      arr[i] = names[i].toNativeUtf8(allocator: calloc);
    }
    try {
      if (!_b.nodeSetTeams(_node, arr, names.length)) {
        throw NodeSetupException('bad teams $names: $lastError');
      }
    } finally {
      for (var i = 0; i < names.length; i++) {
        calloc.free(arr[i]);
      }
      calloc.free(arr);
    }
  }

  void _setParams(Map<String, Object?> params) {
    final json = jsonEncode(params).toNativeUtf8(allocator: calloc);
    try {
      if (!_b.nodeSetParams(_node, json)) {
        throw NodeSetupException('bad params: $lastError');
      }
    } finally {
      calloc.free(json);
    }
  }

  bool _load(String source, String chunkName) {
    final bytes = utf8.encode(source);
    final src = calloc<Uint8>(bytes.length + 1);
    src.asTypedList(bytes.length + 1)
      ..setAll(0, bytes)
      ..[bytes.length] = 0;
    final name = chunkName.toNativeUtf8(allocator: calloc);
    try {
      return _b.nodeLoad(_node, src.cast(), bytes.length, name);
    } finally {
      calloc
        ..free(src)
        ..free(name);
    }
  }

  void _check() {
    if (!_alive) throw StateError('the node is closed');
  }

  /// Dispatches an input event at the current game time. False when the node
  /// is not running, paused (for non-game.* events) or the data is not a
  /// JSON object.
  bool input(String type, [Map<String, Object?>? data]) =>
      inputJson(type, data == null ? null : jsonEncode(data));

  /// [input] with the data already as JSON text.
  bool inputJson(String type, String? dataJson) {
    _check();
    final t = type.toNativeUtf8(allocator: calloc);
    final d = dataJson == null
        ? nullptr
        : dataJson.toNativeUtf8(allocator: calloc);
    try {
      return _b.nodeInput(_node, t, d);
    } finally {
      calloc.free(t);
      if (d != nullptr) calloc.free(d);
    }
  }

  /// Moves game time forward to [nowMs], firing due timers in order.
  void advance(int nowMs) {
    _check();
    _b.nodeAdvance(_node, nowMs & 0xffffffff);
  }

  NodeStatus get status {
    _check();
    final s = _b.nodeStatus(_node);
    return s >= 0 && s < NodeStatus.values.length
        ? NodeStatus.values[s]
        : NodeStatus.halted;
  }

  /// The status as the core names it ("running", ...).
  String get statusName {
    _check();
    return _b.nodeStatusName(_b.nodeStatus(_node)).toDartString();
  }

  bool get paused {
    _check();
    return _b.nodePaused(_node);
  }

  int get timeMs {
    _check();
    return _b.nodeTime(_node);
  }

  String get lastError {
    _check();
    return _b.nodeLastError(_node).toDartString();
  }

  int get memUsed {
    _check();
    return _b.nodeMemUsed(_node);
  }

  /// The team id the core gives [name] (0 if unknown).
  int teamId(String name) {
    _check();
    final n = name.toNativeUtf8(allocator: calloc);
    try {
      return _b.nodeTeamId(_node, n);
    } finally {
      calloc.free(n);
    }
  }

  /// The core's name for team id [team], or null.
  String? teamName(int team) {
    _check();
    final p = _b.nodeTeamName(_node, team);
    return p == nullptr ? null : p.toDartString();
  }

  int _teamIndex(String team) {
    final i = teams.indexOf(team);
    if (i < 0) throw ArgumentError.value(team, 'team', 'not in $teams');
    return i + 1;
  }

  /// Net points of [team] on this node: gained minus lost.
  int score(String team) {
    _check();
    return _b.scoreNet(_b.nodeScore(_node), _teamIndex(team));
  }

  /// Points [team] gained on this node (never decreases; what STATE carries).
  int gained(String team) {
    _check();
    return _b.nodeScore(_node).ref.gained[_teamIndex(team)];
  }

  /// Points [team] lost to penalties on this node.
  int lost(String team) {
    _check();
    return _b.nodeScore(_node).ref.lost[_teamIndex(team)];
  }

  /// Destroys the node, then frees its callbacks and config.
  void close() {
    if (!_alive) return;
    _alive = false;
    _b.nodeDestroy(_node);
    _callbacks.close();
    calloc.free(_config);
  }
}
