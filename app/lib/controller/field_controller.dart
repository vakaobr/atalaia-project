// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The radio side of a game on the Android field controller (ADR-P3-12,
/// decision PE24): the Dart counterpart of the simulator's FieldController
/// (simulator/atalaia_sim/field_controller.py), which the Pi controller runs.
///
/// It keeps what the controller decides about a game, whatever carries the
/// packets: the game state and clock, TIME beacons, commands, the nodes heard
/// (HELLO, STATE), their events with replays dropped, ACKs, scores merged by
/// maximum per node, the controller's own events (GM adjustments, field.lua)
/// and node health (node.online, node.offline, battery.low). Packets reach it
/// decrypted ([onPacket]); what it sends goes to a [FieldTransport] (the I/O
/// pod's radio and the Wi-Fi props, slice S4 of PE24).
///
/// The CLAIM election (ADR-P2-8; PE24 slice S7, controller_failover.dart):
/// TIME and CLAIM from another controller go to the [Election]; a standby
/// mirrors the leader's game clock from its TIME beacons, so a takeover
/// continues it; only the leader sends TIME, commands and ACKs and logs
/// node health. Without an election given, this controller leads from the
/// start with [term] (a lone controller, as the Python one).
library;

import 'dart:convert';
import 'dart:math' show max, min;
import 'dart:typed_data';

import '../core/node_types.dart';
import 'controller_failover.dart';
import 'peer_epoch.dart';
import '../radio/replay.dart';
import '../radio/rf_codec.dart';

/// TIME key 2.
const gameWaiting = 0;
const gameRunning = 1;
const gamePaused = 2;
const gameEnded = 3;

/// CMD opcodes (ADR-P2-3, RFC 0001); 9 (update) is the GM's alone and not
/// sent by this controller.
const cmdOpcodes = {
  'start': 0,
  'pause': 1,
  'resume': 2,
  'end': 3,
  'set_owner': 4,
  'message': 5,
  'reset': 6,
  'reboot': 7,
  'mode': 8,
};

/// CMD update's opcode (firmware updates, slice S7c).
const cmdUpdate = 9;

/// CMD pod's opcode (an I/O pod's settings, RFC 0001 Amendment 17,
/// protocol/pod-config.md): the GM's alone, like [cmdUpdate].
const cmdPod = 10;

const broadcastNode = 0xffff;

/// A box's C decoder turns CMD params into JSON in a 128-byte buffer.
const cmdParamsMax = 127;

// Flood copies and replays are refused by the per-source replay window
// (lib/radio/replay.dart, RFC 0001 Amendment 23): a packet already seen, or 64
// or more counters below the source's highest, however long ago (this was a
// 60 s table; a recording played back after a minute got through).

/// TIME every 30 s (spec section 11; 10 s with automatic failover:
/// [beaconIntervalFor]).
const beaconIntervalMs = beaconIntervalManualMs;

/// A state change (start, pause, resume) goes out as CMD + TIME at once and then as TIME
/// alone again after each of these gaps (RFC 0001 Amendment 19, part 2): a TIME carries the
/// game state and a box acts on it as on the CMD, so a frame lost in a quiet field is repaired
/// in a second or two, not at the next 30 s beacon. A new state change replaces the repeats
/// still due.
const stateRepeatGapsMs = [1000, 1500, 2500, 5000]; // +1.0, +2.5, +5.0, +10.0 s

/// Node health (decisions FU1-1 to FU1-3).
const healthEvents = ['node.online', 'node.offline', 'battery.low'];
const linkGapMs = 60000;
const batteryGraceMs = 30000;
const batteryHysteresis = 5;
const tierNames = {0: 'full', 1: 'reduced', 2: 'proxy'};

class FieldControllerException implements Exception {
  FieldControllerException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// What carries the controller's packets: [send] gives the packet's seq, or
/// null when nothing could send it (no radio, the pod unplugged).
abstract interface class FieldTransport {
  /// "up", "down" or "none" (no radio at all), as the Pi's radio_state.
  String get state;

  int? send(
    int type,
    Uint8List payload, {
    required int prio,
    required bool ack,
    required int hopLimit,
  });
}

/// No radio: nothing is sent (the API answers 503 for node commands).
class NoRadio implements FieldTransport {
  const NoRadio();
  @override
  String get state => 'none';
  @override
  int? send(
    int type,
    Uint8List payload, {
    required int prio,
    required bool ack,
    required int hopLimit,
  }) => null;
}

/// A node the controller knows about.
class FieldNode {
  FieldNode(this.nodeId, this.name, this.role);

  final int nodeId;
  String name;
  String role;
  int lastSeenMs = 0;
  int lastSeq = 0;
  int epoch = 0;
  int ownerTeam = 0;
  int phase = 0;
  int gameTimeMs = 0;
  int? batteryPct;
  int? rssi;
  int? snr;
  RfHello? hello;

  /// Health: heard in this run, the game time of the last packet, the link
  /// as the last node.online/node.offline said it (null: neither yet) and
  /// when that was logged, and whether battery.low is logged for this
  /// crossing.
  bool heard = false;
  int lastSeenGameMs = 0;
  String? link;
  int? linkChangedMs;
  bool batteryLow = false;
  int? batteryLowSince;

  /// Projected score (decision BSC-2): a STATE from this box was heard in this
  /// run.
  bool reported = false;

  /// Ownership changes the box's own events announced since its last STATE:
  /// (game ms, team id, 0 = nobody) in the box's game time. The projection
  /// follows them; every STATE clears them (decision BSC-4).
  final List<(int, int)> changes = [];

  String? ownerName(List<String> teams) =>
      ownerTeam >= 1 && ownerTeam <= teams.length ? teams[ownerTeam - 1] : null;
}

/// Which seqs arrived from each (node, epoch), as ACK payloads.
///
/// A packet lost for good would hold the base back for ever and 256 packets
/// later the box's newest seq would be outside the bitmap (decision SL-8),
/// so every seq more than [gapWindow] below the highest received counts as
/// received. Same rule as AckTracker in simulator/atalaia_sim/
/// field_controller.py; protocol/vectors/ack_tracker.json pins both.
class AckTracker {
  /// The box's outbox holds 32 entries resent every 3 s at most (the
  /// shortest gap of RFC 0001 Amendment 13's backoff), so one still waiting
  /// is never this old; 128 is half the bitmap.
  static const gapWindow = 128;

  final _contig = <(int, int), int>{};
  final _above = <(int, int), Set<int>>{};

  void record(int node, int epoch, int seq) {
    final key = (node, epoch);
    var contig = _contig[key] ?? -1;
    if (seq <= contig) return;
    final above = _above.putIfAbsent(key, () => <int>{})..add(seq);
    final floor = above.reduce((a, b) => a > b ? a : b) - gapWindow - 1;
    if (floor > contig) {
      contig = floor;
      above.removeWhere((x) => x <= contig);
    }
    while (above.remove(contig + 1)) {
      contig += 1;
    }
    _contig[key] = contig;
  }

  /// Highest contiguous seq from 0, or -1.
  int contiguous(int node, int epoch) => _contig[(node, epoch)] ?? -1;

  /// The latest epoch heard from [node], or null.
  int? latestEpoch(int node) {
    int? out;
    for (final (n, e) in _contig.keys) {
      if (n == node && (out == null || e > out)) out = e;
    }
    return out;
  }

  RfAck ack(int node, int epoch) {
    final contig = contiguous(node, epoch);
    final bits = Uint8List(32);
    for (final seq in _above[(node, epoch)] ?? const <int>{}) {
      final n = seq - contig - 1;
      if (n >= 0 && n < 256) bits[n ~/ 8] |= 1 << (n % 8);
    }
    var used = 32;
    while (used > 0 && bits[used - 1] == 0) {
      used--;
    }
    return RfAck(
      node: node,
      seq: contig & 0xffff,
      bitmap: used == 0 ? null : Uint8List.sublistView(bits, 0, used),
    );
  }
}

/// Decodes a box's EVENT payload (the core's codec through dart:ffi).
typedef EventDecoder = EmittedEvent Function(Uint8List payload);

class FieldController {
  FieldController({
    required this.transport,
    required this.gameId,
    required List<String> teams,
    this.nodeId = 0,
    this.maxHops = 2,
    int term = 1,
    Election? election,
    int? beaconInterval,
    this.decodeEvent,
    int Function()? wallSeconds,
  }) : teams = List.unmodifiable(teams),
       election = election ?? (Election(nodeId, 0)..lead(term, 0)),
       _wall =
           wallSeconds ??
           (() => DateTime.now().millisecondsSinceEpoch ~/ 1000) {
    this.beaconInterval = beaconInterval ?? this.election.beaconInterval;
    _roleSeen = this.election.role;
    for (final t in teams) {
      _scores[t] = {};
    }
  }

  final FieldTransport transport;
  final int gameId;
  final List<String> teams;
  final int nodeId;
  final int maxHops;

  /// The controller election (controller_failover.dart).
  final Election election;

  /// TIME every [beaconInterval] ms while leading (10 s with automatic
  /// failover, else 30 s).
  late final int beaconInterval;
  late String _roleSeen;

  /// The term: the highest seen, ours when leading.
  int get term => election.term;
  final EventDecoder? decodeEvent;
  final int Function() _wall;

  int gameState = gameWaiting;
  int gameTimeMs = 0;
  int durationMs = 0;
  int lastBeaconMs = 0;
  List<int> stateRepeatGapsMsList = List.of(stateRepeatGapsMs);
  List<int> _repeats =
      []; // when the TIMEs repeating the last state change are due
  int stateRepeatsSent = 0;
  int _now = 0;
  int? _lastTick;
  int _eventSeq = 0;

  /// The seq of the health events this controller logs about boxes.
  int healthSeq = 0;
  int nodeOfflineMs = 0;
  int linkGapMsSetting = linkGapMs;
  int batteryLowPct = 0;

  final nodes = <int, FieldNode>{};

  /// Packets and events the controller did not log as events (errors).
  final List<Map<String, Object?>> problems = [];

  /// team -> node key ("node-4", "field-1") -> highest value reported.
  final _scores = <String, Map<String, int>>{};

  /// team -> node key ("node-4") -> highest penalty total reported (STATE key
  /// 9, RFC 0001 Amendment 18); [totalScores] subtracts it.
  final _lost = <String, Map<String, int>>{};
  final _adjust = <String, int>{};
  final acks = AckTracker();
  final _replay = <int, ReplayWindow>{}; // source -> its replay window

  /// Authenticated packets the windows refused (flood copies and replays).
  int replaysRefused = 0;
  final _eventsSeen = <(int, int, int, String)>{};

  /// The epochs this controller named to the receivers (peer_epoch.dart, RFC
  /// 0001 Amendment 24, decision SR-110).
  final _peerEpochs = PeerEpochs();

  /// A box was heard at an epoch the receivers may not follow: (node, epoch),
  /// for the host to tell its modem (SET_PEER_EPOCH); the controller has sent
  /// the boxes their CMD itself.
  void Function(int node, int epoch)? onPeerEpoch;

  /// The node ids of other controllers heard on the air (their TIME or CLAIM
  /// authenticated): they have used epochs under this key, so no new device
  /// is given the id (decision EP-3; the engine's `issueJoin`).
  final controllersHeard = <int>{};

  /// Called once for each controller id added to [controllersHeard].
  void Function(int node)? onControllerHeard;

  void Function(Map<String, Object?> record)? onEvent;
  void Function(FieldNode node, String kind)? onNode;
  void Function(Map<String, int> totals)? onScores;

  /// The mode's optional scoring contract (modes/README.md "Projected
  /// score", decision BSC-2): (every in game ms, points) for the team that
  /// owns a box, or null = no projection.
  (int, int)? scoringHold;

  /// How far the projection was from each box's next STATE (the bench's
  /// drift measure; the Python controller's `projection_stats`).
  final projectionStats = <String, Object?>{
    'samples': 0,
    'off': 0,
    'max_abs': 0,
    'sum_abs': 0,
    'last': null,
  };

  /// One box's projection against its next STATE.
  void Function(Map<String, Object?> sample)? onDrift;

  /// The role changed ([electionLeader], [electionCandidate],
  /// [electionFollower]) with the term.
  void Function(String role, int term)? onRole;

  /// The election's own log: CLAIMs sent and heard, role changes (the
  /// Python FieldController's `event_log` entries for them).
  final List<Map<String, Object?>> electionLog = [];

  /// True while this controller leads the game.
  bool get isController => election.isLeader;

  void _requireController() {
    if (!election.isLeader) {
      throw FieldControllerException(
        'node $nodeId is not the controller (role ${election.role})',
      );
    }
  }

  FieldNode registerNode(int id, String name, String role) {
    final node = nodes[id];
    if (node == null) return nodes[id] = FieldNode(id, name, role);
    node
      ..name = name
      ..role = role;
    return node;
  }

  FieldNode _node(int id) =>
      nodes[id] ?? registerNode(id, 'node-$id', 'unknown');

  String? teamName(int teamId) =>
      teamId >= 1 && teamId <= teams.length ? teams[teamId - 1] : null;

  void _advanceTime(int nowMs) {
    final last = _lastTick;
    if (gameState == gameRunning && last != null && nowMs > last) {
      gameTimeMs += nowMs - last;
    }
    _lastTick = nowMs;
    if (nowMs > _now) _now = nowMs;
  }

  /// Puts back the game clock after a restart (PE24 slice S3).
  void restoreClock(int state, int timeMs, int nowMs) {
    gameState = state;
    gameTimeMs = timeMs;
    _lastTick = nowMs;
  }

  // --- the game -------------------------------------------------------------

  void startGame({int durationMs = 0, required int nowMs}) {
    _requireController();
    gameState = gameRunning;
    this.durationMs = durationMs;
    gameTimeMs = 0;
    _lastTick = nowMs;
    if (nowMs > _now) _now = nowMs;
    lastBeaconMs = nowMs;
    _sendCmd(cmdOpcodes['start']!);
    sendTimeBeacon(nowMs);
    _repeatState(nowMs);
  }

  void pauseGame({required int nowMs, String? reason}) {
    _requireController();
    _advanceTime(nowMs);
    gameState = gamePaused;
    _sendCmd(cmdOpcodes['pause']!, reason == null ? null : {'reason': reason});
    sendTimeBeacon(nowMs);
    _repeatState(nowMs);
  }

  void resumeGame({required int nowMs}) {
    _requireController();
    _advanceTime(nowMs);
    gameState = gameRunning;
    _sendCmd(cmdOpcodes['resume']!);
    sendTimeBeacon(nowMs);
    _repeatState(nowMs);
  }

  void endGame({required int nowMs, String? reason}) {
    _requireController();
    _advanceTime(nowMs);
    gameState = gameEnded;
    _sendCmd(cmdOpcodes['end']!, reason == null ? null : {'reason': reason});
    sendTimeBeacon(nowMs);
    _repeats =
        []; // the end is repeated by GAME_OVER (field frames), not by TIME
  }

  void _repeatState(int nowMs) {
    var at = nowMs;
    _repeats = [for (final gap in stateRepeatGapsMsList) at += gap];
  }

  // --- sending --------------------------------------------------------------

  int? _send(int type, Uint8List payload, int prio, {bool ack = false}) =>
      transport.send(type, payload, prio: prio, ack: ack, hopLimit: maxHops);

  int? sendTimeBeacon(int nowMs) {
    lastBeaconMs = nowMs;
    return _send(
      RfType.time,
      RfTime(
        gameTimeMs: gameTimeMs & 0xffffffff,
        gameState: gameState,
        durationMs: durationMs & 0xffffffff,
        wallS: _wall() & 0xffffffff,
        term: election.term & 0xffffffff,
      ).encode(),
      RfPrio.critical,
    );
  }

  /// A command by name to [dest] (null: every node); its packet's seq, or
  /// null when nothing sent it. Throws [FieldControllerException] for an
  /// unknown command or parameters that do not fit a CMD.
  int? sendCmd(String cmd, Map<String, Object?>? params, {int? dest}) {
    _requireController();
    final opcode = cmdOpcodes[cmd];
    if (opcode == null) {
      throw FieldControllerException('unknown command $cmd');
    }
    return _sendCmd(opcode, params, dest);
  }

  int? _sendCmd(int cmd, [Map<String, Object?>? params, int? dest]) {
    if (params != null && params.isNotEmpty) {
      final size = utf8.encode(jsonEncode(params)).length;
      if (size > cmdParamsMax) {
        throw FieldControllerException(
          'command parameters are $size bytes; at most $cmdParamsMax fit in a CMD',
        );
      }
    }
    return _send(
      RfType.cmd,
      RfCmd(
        cmd: cmd,
        params: params == null || params.isEmpty ? null : params,
        dest: dest == null || dest == broadcastNode ? null : dest,
      ).encode(),
      RfPrio.critical,
    );
  }

  /// A box was heard at an epoch the receivers may not follow (peer_epoch.dart,
  /// SR-110): the host tells its modem, and the leader tells every box (CMD
  /// peer, flooded; it only moves a table up).
  void _announcePeerEpoch(int nodeId, int epoch) {
    onPeerEpoch?.call(nodeId, epoch);
    if (election.isLeader) {
      _sendCmd(cmdPeerEpoch, {'src': nodeId, 'epoch': epoch});
    }
  }

  /// CMD update (opcode 9, RFC 0001 Amendment 6) to [dest]: the GM's alone
  /// (controller_firmware.dart), never a mode's field.lua, so not in
  /// [cmdOpcodes].
  int? sendUpdateCmd(Map<String, Object?> params, {required int dest}) {
    _requireController();
    return _sendCmd(cmdUpdate, params, dest);
  }

  /// CMD pod (opcode 10, RFC 0001 Amendment 17) to [dest], the node id of
  /// the phone an I/O pod serves: the GM's alone (controller_pod_config.dart),
  /// never a mode's field.lua, so not in [cmdOpcodes].
  int? sendPodCmd(Map<String, Object?> params, {required int dest}) {
    _requireController();
    return _sendCmd(cmdPod, params, dest);
  }

  // --- receiving ------------------------------------------------------------

  /// One decrypted packet; [epoch], [rssi] and [snr] as the radio gave them.
  void onPacket(
    RfHeader header,
    Uint8List payload, {
    int epoch = 0,
    int? rssi,
    int? snr,
  }) {
    final window = _replay.putIfAbsent(header.source, ReplayWindow.new);
    if (window.accept(ReplayWindow.counter(epoch, header.seq)) !=
        ReplayVerdict.fresh) {
      replaysRefused++;
      return; // a flood copy, or a recording played back
    }
    if ((header.type == RfType.time || header.type == RfType.claim) &&
        header.source != nodeId &&
        controllersHeard.add(header.source)) {
      onControllerHeard?.call(header.source);
    }
    if (header.type == RfType.time) {
      _onTime(header.source, payload);
      return;
    }
    if (header.type == RfType.claim) {
      _onClaim(header.source, payload);
      return;
    }
    acks.record(header.source, epoch, header.seq);
    final node = _node(header.source);
    final priorEpoch = node.epoch;
    node
      ..lastSeenMs = _now
      ..lastSeenGameMs = gameTimeMs
      ..heard = true
      ..lastSeq = header.seq
      ..epoch = epoch;
    if (rssi != null) node.rssi = rssi;
    if (snr != null) node.snr = snr;
    switch (header.type) {
      case RfType.state:
        _onState(node, payload);
      case RfType.hello:
        _onHello(node, payload);
      case RfType.event:
        _onEvent(node, header, payload, epoch);
    }
    if (header.ackRequested && election.isLeader) {
      _send(RfType.ack, acks.ack(header.source, epoch).encode(), RfPrio.normal);
    }
    if (_peerEpochs.heard(
      header.source,
      priorEpoch,
      epoch,
      header.type == RfType.hello,
      _now,
    )) {
      _announcePeerEpoch(header.source, epoch);
    }
    _checkHealth(node, _now);
  }

  // --- the election (controller_failover.dart) ----------------------------

  void _sendClaim(Claim claim, int nowMs) {
    final lastAck = <int, int>{};
    for (final id in nodes.keys) {
      final epoch = acks.latestEpoch(id);
      if (epoch != null && acks.contiguous(id, epoch) >= 0) {
        lastAck[id] = acks.contiguous(id, epoch);
      }
    }
    electionLog.add({
      't_ms': nowMs,
      'type': 'claim_sent',
      'term': claim.term,
      'priority': claim.priority,
    });
    _send(
      RfType.claim,
      RfClaim(
        term: claim.term,
        priority: claim.priority,
        nodeId: claim.nodeId,
        lastAckSeq: lastAck.isEmpty ? null : lastAck,
      ).encode(),
      RfPrio.critical,
    );
  }

  /// Manual failover: stand for election now (the GM's "promote"). Throws
  /// [ElectionException] for a node that cannot lead.
  void promote(int nowMs) {
    if (nowMs > _now) _now = nowMs;
    _sendClaim(election.promote(nowMs), nowMs);
    _checkRole(nowMs);
  }

  /// TIME from another controller: followed when its term is current; on
  /// standby the game clock mirrors it, so a takeover continues it.
  void _onTime(int source, Uint8List payload) {
    final RfTime beacon;
    try {
      beacon = RfTime.decode(payload);
    } on Object {
      return;
    }
    if (!election.onTime(beacon.term, source, _now)) return;
    gameState = beacon.gameState;
    gameTimeMs = beacon.gameTimeMs;
    _lastTick = _now;
    durationMs = beacon.durationMs;
    _checkRole(_now);
  }

  /// CLAIM from a candidate.
  void _onClaim(int source, Uint8List payload) {
    final RfClaim claim;
    try {
      claim = RfClaim.decode(payload);
    } on Object {
      return;
    }
    electionLog.add({
      't_ms': _now,
      'type': 'claim',
      'source': source,
      'term': claim.term,
      'priority': claim.priority,
      'node_id': claim.nodeId,
    });
    election.onClaim(claim.term, claim.priority, claim.nodeId, _now);
    _checkRole(_now);
  }

  void _checkRole(int nowMs) {
    final role = election.role;
    if (role == _roleSeen) return;
    _roleSeen = role;
    electionLog.add({
      't_ms': nowMs,
      'type': 'role',
      'role': role,
      'term': election.term,
    });
    if (role == electionLeader) {
      // Took over: announce the new term at once (nodes follow the highest
      // term).
      _lastTick = nowMs;
      sendTimeBeacon(nowMs);
    }
    onRole?.call(role, election.term);
  }

  void _onState(FieldNode node, Uint8List payload) {
    final RfState state;
    try {
      state = RfState.decode(payload);
    } on Object {
      return;
    }
    final driftBefore = scoringHold == null ? null : _projectionBefore(node);
    node
      ..ownerTeam = state.ownerTeam
      ..phase = state.phase
      ..gameTimeMs = state.gameTimeMs
      ..reported = true;
    // The STATE is the authority: it replaces what the events said.
    node.changes.clear();
    if (state.batteryPct != null) node.batteryPct = state.batteryPct;
    if (state.rssi != null) node.rssi = state.rssi;
    mergeCounters('node-${node.nodeId}', {
      for (final e in state.counters.entries)
        teamName(e.key) ?? '${e.key}': e.value,
    });
    if (state.lost.isNotEmpty) {
      mergeLost('node-${node.nodeId}', {
        for (final e in state.lost.entries)
          teamName(e.key) ?? '${e.key}': e.value,
      });
    }
    if (driftBefore != null) _recordDrift(node, driftBefore);
    onNode?.call(node, 'state');
  }

  void _onHello(FieldNode node, Uint8List payload) {
    final RfHello hello;
    try {
      hello = RfHello.decode(payload);
    } on Object {
      return;
    }
    node
      ..hello = hello
      ..name = hello.nodeName;
    if (hello.batteryPct != null) node.batteryPct = hello.batteryPct;
    onNode?.call(node, 'hello');
  }

  void _onEvent(FieldNode node, RfHeader header, Uint8List payload, int epoch) {
    final EmittedEvent ev;
    try {
      final decode = decodeEvent;
      if (decode == null) throw FieldControllerException('no event codec');
      ev = decode(payload);
    } on Object catch (e) {
      problems.add({
        't_ms': _now,
        'type': 'event',
        'source': node.nodeId,
        'seq': header.seq,
        'error': '$e',
      });
      return;
    }
    // A box's event seq restarts at 1 after a reboot: the event's identity
    // is (node, seq, game time, type), and replays match it exactly.
    if (!_eventsSeen.add((node.nodeId, ev.seq, ev.tMs, ev.type))) return;
    final record = <String, Object?>{
      'node': node.nodeId,
      'seq': ev.seq,
      't': ev.tMs,
      'type': ev.type,
      'team': teamName(ev.team),
      'team_id': ev.team,
      'squad': ev.squad,
      'prio': ev.prioName,
      'data': ev.data,
      'epoch': epoch,
      'pkt_seq': header.seq,
      'received_ms': _now,
    };
    if (ev.type == 'zone.captured' || ev.type == 'zone.neutralized') {
      _noteOwnerChange(node, ev.type, ev.tMs, ev.team);
    }
    if (ev.type == 'battery.low') {
      node
        ..batteryLow = true
        ..batteryLowSince = null;
    }
    onEvent?.call(record);
  }

  // --- tick -----------------------------------------------------------------

  /// Moves to [nowMs]: the game clock, the election, due TIME beacons (the
  /// leader's), node health.
  void tick(int nowMs) {
    _advanceTime(nowMs);
    final claim = election.tick(nowMs);
    if (claim != null) _sendClaim(claim, nowMs);
    _checkRole(nowMs);
    if (election.isLeader &&
        (gameState == gameRunning || gameState == gamePaused)) {
      if (_repeats.isNotEmpty && nowMs >= _repeats.first) {
        // One TIME for every repeat that is due (a late tick does not send a burst).
        _repeats = [
          for (final t in _repeats)
            if (t > nowMs) t,
        ];
        stateRepeatsSent++;
        sendTimeBeacon(nowMs);
      } else if (nowMs - lastBeaconMs >= beaconInterval) {
        sendTimeBeacon(nowMs);
      }
    } else {
      _repeats = [];
    }
    if (election.isLeader) {
      for (final (node, epoch) in _peerEpochs.due(nowMs)) {
        _sendCmd(cmdPeerEpoch, {'src': node, 'epoch': epoch});
      }
    }
    for (final node in nodes.values.toList()) {
      _checkHealth(node, nowMs);
    }
  }

  // --- scores ---------------------------------------------------------------

  /// Merges counters by maximum, per source: a node ("node-ID") or a run of
  /// the field script ("field-N"), whose points never travel in STATE.
  void mergeCounters(String nodeKey, Map<String, int> counters) {
    var changed = false;
    counters.forEach((team, value) {
      final perNode = _scores.putIfAbsent(team, () => {});
      if (value > (perNode[nodeKey] ?? 0)) {
        perNode[nodeKey] = value;
        changed = true;
      }
    });
    if (changed) onScores?.call(totalScores);
  }

  // --- projected score (decision BSC-2) -------------------------------------

  /// A zone.captured (or zone.neutralized) from a box: the projection follows
  /// it until the box's next STATE (decision BSC-4). Its game time [tMs] is the
  /// box's own, like the STATE's. An event not newer than the box's last STATE
  /// is already in that STATE and changes nothing; one dated after the
  /// controller's own game time counts from now. `previous_team` is not used:
  /// the old owner is whoever the last STATE (or the event before) said.
  void _noteOwnerChange(FieldNode node, String type, int tMs, int teamId) {
    if (!node.reported || scoringHold == null) return;
    if (tMs <= node.gameTimeMs) return;
    final team = type == 'zone.captured' ? teamId : 0;
    if (team < 0 || team > teams.length) return;
    final changes = node.changes;
    if (changes.isNotEmpty && tMs < changes.last.$1) return;
    changes.add((min(tMs, max(gameTimeMs, node.gameTimeMs)), team));
    if (changes.length > 8) changes.removeRange(0, changes.length - 8);
  }

  /// Scoring ticks of the mode that happened on this box since its last
  /// STATE, by game time, per owner (team id): the boundaries k x every
  /// between the box's own report time and the controller's game time, split
  /// at the ownership changes its events announced since (the old owner's
  /// ticks up to the change, the new owner's after it). Empty unless the game
  /// runs, the box is online, it reported and it is running.
  Map<int, int> _projectedTicks(FieldNode node) {
    final hold = scoringHold;
    if (hold == null ||
        gameState != gameRunning ||
        !node.reported ||
        node.phase != gameRunning ||
        node.link == 'offline') {
      return const {};
    }
    final every = hold.$1;
    final out = <int, int>{};
    var start = node.gameTimeMs;
    var owner = node.ownerTeam;
    for (final (when0, team) in [...node.changes, (gameTimeMs, 0)]) {
      final when = max(start, min(when0, gameTimeMs));
      final ticks = when ~/ every - start ~/ every;
      if (ticks > 0 && owner >= 1 && owner <= teams.length) {
        out[owner] = (out[owner] ?? 0) + ticks;
      }
      start = when;
      owner = team;
    }
    return out;
  }

  /// The ticks the box's owner at its last STATE made since it (the drift
  /// measure's side).
  int _ticksSinceReport(FieldNode node) =>
      _projectedTicks(node)[node.ownerTeam] ?? 0;

  /// Points each team has probably made since its boxes' last STATEs, to
  /// whoever held the box at the time. Display only.
  Map<String, int> projectedGains() {
    final out = <String, int>{};
    final hold = scoringHold;
    if (hold == null) return out;
    for (final node in nodes.values) {
      _projectedTicks(node).forEach((teamId, ticks) {
        final team = teams[teamId - 1];
        out[team] = (out[team] ?? 0) + ticks * hold.$2;
      });
    }
    return out;
  }

  /// The totals with the projection added, or null when the mode does not opt
  /// in. The stored totals, score.delta and the final result never use it:
  /// every STATE replaces it.
  Map<String, int>? projectedScores() {
    if (scoringHold == null) return null;
    final totals = totalScores;
    projectedGains().forEach(
      (team, gain) => totals[team] = (totals[team] ?? 0) + gain,
    );
    return totals;
  }

  ({String team, int reported, int ticks, int ageMs})? _projectionBefore(
    FieldNode node,
  ) {
    if (!node.reported || gameState != gameRunning) return null;
    final team = node.ownerName(teams);
    if (team == null) return null;
    final age = gameTimeMs - node.gameTimeMs;
    return (
      team: team,
      reported: _scores[team]?['node-${node.nodeId}'] ?? 0,
      ticks: _ticksSinceReport(node),
      ageMs: age < 0 ? 0 : age,
    );
  }

  void _recordDrift(
    FieldNode node,
    ({String team, int reported, int ticks, int ageMs}) before,
  ) {
    final hold = scoringHold;
    if (hold == null) return;
    final projected = before.reported + before.ticks * hold.$2;
    final reported = _scores[before.team]?['node-${node.nodeId}'] ?? 0;
    final drift = projected - reported;
    final stats = projectionStats;
    stats['samples'] = (stats['samples']! as int) + 1;
    stats['off'] = (stats['off']! as int) + (drift != 0 ? 1 : 0);
    stats['max_abs'] = max(stats['max_abs']! as int, drift.abs());
    stats['sum_abs'] = (stats['sum_abs']! as int) + drift.abs();
    final sample = <String, Object?>{
      'node': node.nodeId,
      'team': before.team,
      'projected': projected,
      'reported': reported,
      'drift': drift,
      'age_ms': before.ageMs,
    };
    stats['last'] = sample;
    onDrift?.call(Map.of(sample));
  }

  /// The points a node lost to penalties (STATE key 9), merged by maximum like
  /// the gains and subtracted in [totalScores]. A box that never sends the key
  /// (an older firmware) loses none.
  void mergeLost(String nodeKey, Map<String, int> lost) {
    var changed = false;
    lost.forEach((team, value) {
      final perNode = _lost.putIfAbsent(team, () => {});
      if (value > (perNode[nodeKey] ?? 0)) {
        perNode[nodeKey] = value;
        changed = true;
      }
    });
    if (changed) onScores?.call(totalScores);
  }

  /// What one node reported lost to penalties for [team].
  int lostOf(String team, String nodeKey) => _lost[team]?[nodeKey] ?? 0;

  /// [team]'s points from one source ("node-4").
  int counter(String team, String nodeKey) => _scores[team]?[nodeKey] ?? 0;

  /// An event the controller itself originates (GM actions, field scripts).
  Map<String, Object?> controllerEvent(
    String type, [
    Map<String, Object?> data = const {},
    String? team,
    String prio = 'normal',
  ]) {
    _eventSeq = (_eventSeq % 0xffff) + 1;
    final teamId = team == null ? 0 : teams.indexOf(team) + 1;
    final record = <String, Object?>{
      'node': nodeId,
      'seq': _eventSeq,
      't': gameTimeMs,
      'type': type,
      'team': teamId > 0 ? team : null,
      'team_id': teamId,
      'squad': 0,
      'prio': prio,
      'data': Map<String, Object?>.of(data),
      'epoch': null,
      'pkt_seq': null,
      'received_ms': _now,
    };
    onEvent?.call(record);
    return record;
  }

  /// Puts back the seq of the controller's own events (after a restart).
  void restoreEventSeq(int seq) => _eventSeq = seq;

  /// An event the controller logs about a box: its node is the box's id.
  Map<String, Object?> nodeEvent(
    int id,
    String type, [
    Map<String, Object?> data = const {},
  ]) {
    healthSeq = (healthSeq % 0xffff) + 1;
    final record = <String, Object?>{
      'node': id,
      'seq': healthSeq,
      't': gameTimeMs,
      'type': type,
      'team': null,
      'team_id': 0,
      'squad': 0,
      'prio': 'telemetry',
      'data': Map<String, Object?>.of(data),
      'epoch': null,
      'pkt_seq': null,
      'received_ms': _now,
      'origin': 'controller',
    };
    onEvent?.call(record);
    return record;
  }

  void _checkHealth(FieldNode node, int nowMs) {
    if (!election.isLeader || gameState == gameEnded) return;
    final since = node.heard
        ? node.lastSeenMs
        : node.link == 'online'
        ? node.linkChangedMs
        : null;
    if (nodeOfflineMs > 0 && since != null) {
      final want = nowMs - since < nodeOfflineMs ? 'online' : 'offline';
      final changed = node.linkChangedMs;
      if (want != node.link &&
          (changed == null || nowMs - changed >= linkGapMsSetting)) {
        final data = <String, Object?>{};
        if (want == 'online') {
          final hello = node.hello;
          if (hello != null) {
            data['fw'] = hello.fwVersion;
            final tier = tierNames[hello.tier];
            if (tier != null) data['tier'] = tier;
          }
        } else {
          data['last_seen'] = node.lastSeenGameMs;
        }
        node
          ..link = want
          ..linkChangedMs = nowMs;
        nodeEvent(node.nodeId, 'node.$want', data);
        onNode?.call(node, want);
      }
    }
    final pct = node.batteryPct;
    if (batteryLowPct > 0 && pct != null && pct >= 0 && pct <= 100) {
      if (pct >= batteryLowPct + batteryHysteresis) {
        node
          ..batteryLow = false
          ..batteryLowSince = null;
      } else if (pct >= batteryLowPct || node.batteryLow) {
        node.batteryLowSince = null;
      } else if (node.batteryLowSince == null) {
        node.batteryLowSince = nowMs;
      } else if (nowMs - node.batteryLowSince! >= batteryGraceMs) {
        node
          ..batteryLow = true
          ..batteryLowSince = null;
        nodeEvent(node.nodeId, 'battery.low', {'percent': pct});
      }
    }
  }

  /// A GM's adjustment, logged as score.delta from the controller.
  Map<String, Object?> adjustScore(
    String team,
    int amount,
    String reason, {
    int? nowMs,
  }) {
    if (nowMs != null) _advanceTime(nowMs);
    _adjust[team] = (_adjust[team] ?? 0) + amount;
    final record = controllerEvent('score.delta', {
      'team': team,
      'amount': amount,
      'reason': reason,
    }, team);
    onScores?.call(totalScores);
    return record;
  }

  void restoreAdjustments(Map<String, int> adjustments) {
    _adjust
      ..clear()
      ..addAll(adjustments);
  }

  /// Per team: the highest value each source reported, summed, minus the
  /// highest penalties the boxes reported, plus the GM's adjustments.
  Map<String, int> get totalScores {
    final out = <String, int>{};
    _scores.forEach((team, perNode) {
      out[team] = perNode.values.fold(0, (a, b) => a + b);
    });
    _lost.forEach((team, perNode) {
      out[team] = (out[team] ?? 0) - perNode.values.fold(0, (a, b) => a + b);
    });
    _adjust.forEach((team, amount) => out[team] = (out[team] ?? 0) + amount);
    return out;
  }
}
