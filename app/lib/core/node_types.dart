// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// What the UI and the rest of the app see of a running node, with no
/// `dart:ffi` in it: the same types on Android (the core through
/// lib/ffi/) and on iOS and the web (no core, node_runner_stub.dart).
library;

import 'dart:convert';

/// atalaia_node_status_t, in its C order.
enum NodeStatus { empty, running, ended, halted }

/// atalaia_prio_t: the names are the protocol schema's.
const List<String> prioNames = ['telemetry', 'normal', 'critical'];

/// What a node is set up with before its script is loaded.
final class NodeSpec {
  const NodeSpec({
    required this.source,
    required this.chunkName,
    this.nodeId = 1,
    this.gameSeed = 1,
    this.gameKey,
    this.teams = const ['red', 'blue'],
    this.params = const {},
    this.memLimit = 0,
    this.instrLimit = 0,
  });

  /// The script's source text (never bytecode) and its name in error
  /// messages, e.g. "@bomb/node.lua".
  final String source;
  final String chunkName;
  final int nodeId;

  /// Seeds rand(): the same seed replays the same game.
  final int gameSeed;

  /// The game's key (16 bytes): rand() is seeded from it as well as the seed
  /// and the node id, so players who see those cannot predict it (LIVE2-2).
  /// Null (a test, a load check) seeds from the seed and node id alone.
  final List<int>? gameKey;

  /// The game's teams, ids 1..n in this order.
  final List<String> teams;

  /// The preset's parameters, exposed to the script as `params`.
  final Map<String, Object?> params;

  /// Script memory cap in bytes and instructions per callback; 0 for the
  /// core's defaults (256 KB, the Full tier, as ADR-P3-1 asks for Android).
  final int memLimit;
  final int instrLimit;
}

/// An event a node emitted, as the host receives it.
final class EmittedEvent {
  const EmittedEvent({
    required this.node,
    required this.seq,
    required this.tMs,
    required this.team,
    required this.squad,
    required this.prio,
    required this.type,
    required this.dataJson,
  });

  final int node;
  final int seq;
  final int tMs;

  /// Team and squad ids (0: none); team id i is the game's team i - 1.
  final int team;
  final int squad;

  /// atalaia_prio_t: 0 telemetry, 1 normal, 2 critical.
  final int prio;
  final String type;

  /// The event's data, a JSON object as the core wrote it.
  final String dataJson;

  Map<String, Object?> get data => dataJson.isEmpty
      ? const {}
      : (jsonDecode(dataJson) as Map<String, Object?>);

  String get prioName =>
      prio >= 0 && prio < prioNames.length ? prioNames[prio] : '$prio';

  @override
  String toString() => '${tMs}ms node $node #$seq $type $dataJson';
}

/// A hardware command: target "ring", method "fill", args ["red"]. Targets
/// are capability ids, or "ui" and "audio".
final class NodeCommand {
  const NodeCommand({
    required this.tMs,
    required this.target,
    required this.method,
    required this.argsJson,
  });

  /// The node's game time when the script gave the command.
  final int tMs;
  final String target;
  final String method;
  final String argsJson;

  List<Object?> get args => jsonDecode(argsJson) as List<Object?>;

  @override
  String toString() => '${tMs}ms $target.$method $argsJson';
}

/// A node's state at one moment.
final class NodeSnapshot {
  const NodeSnapshot({
    required this.status,
    required this.paused,
    required this.timeMs,
    required this.memUsed,
    required this.lastError,
    required this.scores,
    Map<String, int>? gained,
    this.lost = const {},
  }) : gained = gained ?? scores;

  final NodeStatus status;
  final bool paused;

  /// Game time in milliseconds since the game started.
  final int timeMs;

  /// Bytes of script memory in use.
  final int memUsed;
  final String lastError;

  /// Net points per team name on this node.
  final Map<String, int> scores;

  /// Points gained per team name (never decreases: what STATE's counters
  /// carry); [scores] when the runner does not tell (no penalties then).
  final Map<String, int> gained;

  /// Points lost to penalties per team name (STATE key 9, RFC 0001
  /// Amendment 18); a team with none is absent.
  final Map<String, int> lost;

  @override
  String toString() =>
      'NodeSnapshot(${status.name}${paused ? ', paused' : ''}, ${timeMs}ms, $scores)';
}

/// What a running node sends the UI, in the order it happened.
sealed class NodeOutput {
  const NodeOutput();
}

final class NodeEventOutput extends NodeOutput {
  const NodeEventOutput(this.event);
  final EmittedEvent event;
}

final class NodeCommandOutput extends NodeOutput {
  const NodeCommandOutput(this.command);
  final NodeCommand command;
}

final class NodeLogOutput extends NodeOutput {
  const NodeLogOutput(this.line);
  final String line;
}

/// The status or the pause state changed (the game ended, the sandbox
/// halted the script, a game.pause arrived).
final class NodeStatusOutput extends NodeOutput {
  const NodeStatusOutput(this.snapshot);
  final NodeSnapshot snapshot;
}

/// Something went wrong on the host side (a handler threw); the node runs on.
final class NodeErrorOutput extends NodeOutput {
  const NodeErrorOutput(this.message);
  final String message;
}

/// How game time moves.
enum GameClock {
  /// The wall clock, at 100 Hz, as on a Field Box (ADR-P3-1): the app.
  realTime,

  /// Only when the host says so ([RunningNode.advanceTo]): tests and replays.
  manual,
}

/// A node running off the UI isolate.
abstract interface class RunningNode {
  /// Whether the script loaded; if not, [NodeSnapshot.lastError] says why.
  bool get loaded;

  /// Everything the node emits, in order, delivered synchronously as each
  /// message arrives (so it is all there when a call's future completes).
  Stream<NodeOutput> get outputs;

  /// What the script's top level emitted while the node was loading, before
  /// anyone could listen to [outputs] (a first ui.screen, say).
  List<NodeOutput> get startupOutputs;

  /// An input event. With [GameClock.realTime] it waits for the next tick,
  /// as hardware events on a box do; the result is whether the node took it.
  Future<bool> input(String type, [Map<String, Object?>? data]);

  /// Moves game time to [timeMs] ([GameClock.manual] only).
  Future<void> advanceTo(int timeMs);

  Future<NodeSnapshot> snapshot();

  /// Stops the clock, destroys the node and ends its isolate.
  Future<void> close();
}

/// Starts nodes where the platform can run the core.
abstract interface class NodeRunner {
  /// False on iOS and the web: no core there (ADR-P3-10).
  bool get supported;

  /// The core's version, or null when there is no core to load.
  String? get coreVersion;

  Future<RunningNode> start(NodeSpec spec, {GameClock clock});
}
