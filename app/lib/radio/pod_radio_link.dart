// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// An Android prop on the field's radio through an I/O pod (decision PF9):
/// the phone does what a Field Box's field link does (firmware
/// main/radio/field_link.c), and the pod does what the controller's USB
/// modem does (protocol/usb-modem.md, through the capability proxy's RADIO_*
/// frames): the phone builds the plaintext packets, the pod encrypts them
/// with the game key, keeps the duty cycle and the channel's limits, and
/// hands back what it heard, decrypted.
///
///   - RADIO_CMD CONFIGURE with the join payload's game, node id, hops and
///     channel and a new epoch (stored before it is used: a nonce never
///     repeats under one game key, ADR-P2-2); again after the pod lost it;
///   - HELLO (critical) until the controller acknowledges it;
///   - events: normal and critical ones ask for an ACK and are sent again
///     every 3 s in a new packet (critical until acknowledged, normal up to
///     10 times), telemetry once;
///   - STATE at most every 15 s (telemetry, as a box);
///   - TIME beacons and the commands for this node from the controller it
///     follows (the highest term's) come out as [LinkTime] and [LinkCommand].
///
/// The phone does not relay other boxes' packets (the modem's code never
/// does). Checked against the pod's real C code and the controller's modem
/// (test/radio/pod_radio_link_test.dart, the host pod and the host modem);
/// not run on a real pod and radio yet (plan phase G).
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';

import '../controller/controller_link.dart';
import '../pod/pod_client.dart';
import '../pod/pod_codec.dart';
import '../protocol/join_payload.dart';
import '../storage/app_store.dart';
import 'rf_codec.dart';

/// The epoch of a node's packets in a game: one higher on every new link.
abstract interface class EpochStore {
  /// The next epoch for (game, node), stored before it is returned.
  Future<int> next(int gameId, int nodeId);
}

/// Epochs kept in the app's store (the latest 32 games).
class AppEpochStore implements EpochStore {
  AppEpochStore(this.store);

  final AppStore store;
  static const list = 'radio_epochs';

  @override
  Future<int> next(int gameId, int nodeId) async {
    final rows = await store.loadList(list);
    var epoch = 0;
    rows.removeWhere((r) {
      if (r['game_id'] != gameId || r['node_id'] != nodeId) return false;
      epoch = (r['epoch'] as int?) ?? 0;
      return true;
    });
    epoch = epoch >= 0xffff ? 0xffff : epoch + 1;
    rows.add({'game_id': gameId, 'node_id': nodeId, 'epoch': epoch});
    while (rows.length > 32) {
      rows.removeAt(0);
    }
    await store.saveList(list, rows);
    return epoch;
  }
}

class MemoryEpochStore implements EpochStore {
  final epochs = <String, int>{};

  @override
  Future<int> next(int gameId, int nodeId) async =>
      epochs['$gameId/$nodeId'] = (epochs['$gameId/$nodeId'] ?? 0) + 1;
}

enum RadioLinkState { configuring, linked, offline, closed }

/// The modem's TX_ACK statuses that RADIO_TX_ACK carries.
abstract final class RadioTxStatus {
  static const ok = 0;
  static const dutyCycle = 1;
  static const timeout = 2;
  static const notConfigured = 3;
  static const invalid = 4;
  static const nonceReuse = 5;
  static const queueFull = 6;
  static const noRadio = 7;
}

class _Out {
  _Out(this.type, this.prio, this.payload, {this.hello = false});
  final int type;
  final int prio;
  final Uint8List payload;
  final bool hello;

  /// The seqs of the packets that carried it (the latest 16): an ACK for
  /// any of them is an ACK for it (the controller may answer an earlier copy).
  final pktSeqs = <int>[];
  var tries = 0;
  var dueMs = 0;
}

class PodRadioLink extends ChangeNotifier implements ControllerLink {
  PodRadioLink({
    required this.pod,
    required this.join,
    required this.epochs,
    required this.encodeEvent,
    this.hello = const {},
    this.retryAfter = const Duration(seconds: 3),
    this.stateEvery = const Duration(seconds: 15),
    this.reconfigureAfter = const Duration(seconds: 5),
    this.tick = const Duration(milliseconds: 100),
    int Function()? nowMs,
  }) : _nowMs = nowMs ?? _monotonicMs;

  static final _clock = Stopwatch()..start();
  static int _monotonicMs() => _clock.elapsedMilliseconds;

  final PodClient pod;
  final JoinPayload join;
  final EpochStore epochs;
  final EventEncoder encodeEvent;
  final Duration retryAfter;
  final Duration stateEvery;
  final Duration reconfigureAfter;
  final Duration tick;
  final int Function() _nowMs;

  /// HELLO's fields (node name, versions, transports...).
  Map<String, Object?> hello;

  static const maxRetries = 10; // normal priority; critical: until acknowledged
  static const outboxMax = 32;

  RadioLinkState state = RadioLinkState.configuring;

  /// The epoch of the packets now, and whether the controller has answered
  /// (acknowledged HELLO).
  int epoch = 0;
  bool heard = false;

  /// Counters for the screen and the tests.
  var sent = 0, retried = 0, acked = 0, expired = 0, dutyLimited = 0;

  final _messages = StreamController<LinkMessage>.broadcast();
  final _outbox = <_Out>[];
  StreamSubscription<PodEvent>? _sub;
  Timer? _ticker;
  var _seq = 0;
  var _leader = 0;
  var _term = 0;
  var _heardTime = false;
  var _configureAtMs = -1;
  var _configuring = false;
  Map<String, Object?>? _state;
  var _stateSentMs = -1;

  @override
  Stream<LinkMessage> get messages => _messages.stream;

  /// The pod's radio is configured for the game: packets can go out.
  @override
  bool get linked => state == RadioLinkState.linked;

  int get pending => _outbox.length;

  @override
  void start() {
    _leader = join.controllerId;
    _sub = pod.events.listen(_onPod);
    _ticker = Timer.periodic(tick, (_) => _onTick());
    unawaited(_configure());
  }

  /// HELLO's fields (node name, versions...), sent again when they change.
  void updateHello(Map<String, Object?> fields) {
    hello = fields;
    if (linked) _queueHello();
  }

  Future<void> _configure() async {
    if (state == RadioLinkState.closed || pod.broken || _configuring) return;
    _configuring = true;
    try {
      await _configureOnce();
    } finally {
      _configuring = false;
    }
  }

  Future<void> _configureOnce() async {
    state = RadioLinkState.configuring;
    _configureAtMs = -1;
    notifyListeners();
    final e = await epochs.next(join.gameId, join.nodeId);
    if (state == RadioLinkState.closed) return;
    epoch = e;
    _seq = 0;
    // The answer (RADIO_STATUS, or RADIO_ERROR) comes in _onPod; without
    // one, the tick tries again.
    _configureAtMs = _nowMs() + reconfigureAfter.inMilliseconds;
    await pod.sendRadio(
      FrameType.radioCmd,
      radioConfigure(
        gameId: join.gameId,
        nodeId: join.nodeId,
        epoch: epoch,
        maxHops: join.maxHops,
        channelHz: join.channelHz,
        key: join.gameKey,
      ),
    );
  }

  void _onPod(PodEvent e) {
    switch (e) {
      case PodRadioFrame(:final type, :final payload):
        _onRadio(type, payload);
      case PodLinkBroken():
        if (state != RadioLinkState.closed) {
          state = RadioLinkState.offline;
          notifyListeners();
        }
      case PodIdentified():
        // A pod that says who it is again may have lost the game key.
        if (state == RadioLinkState.linked) unawaited(_configure());
      case PodCapabilityEvent():
        break;
    }
  }

  void _onRadio(int type, Uint8List payload) {
    switch (type) {
      case FrameType.radioStatus:
        if (state != RadioLinkState.configuring) return;
        Object? status;
        try {
          status = jsonDecode(utf8.decode(payload));
        } on FormatException {
          return;
        }
        if (status is Map &&
            status['configured'] == true &&
            status['cmd'] == 2) {
          state = RadioLinkState.linked;
          _configureAtMs = -1;
          for (final o in _outbox) {
            // A new epoch: everything waiting goes again, in new packets.
            o.dueMs = 0;
            o.pktSeqs.clear();
          }
          _queueHello();
          notifyListeners();
        }
      case FrameType.radioError:
        if (state == RadioLinkState.configuring) {
          // A channel the pod refuses, or no radio: the link stays down.
          state = RadioLinkState.offline;
          _configureAtMs = _nowMs() + reconfigureAfter.inMilliseconds;
          notifyListeners();
        }
      case FrameType.radioTxAck:
        if (payload.length != 3) return;
        switch (payload[2]) {
          case RadioTxStatus.nonceReuse || RadioTxStatus.notConfigured:
            if (state == RadioLinkState.linked) unawaited(_configure());
          case RadioTxStatus.dutyCycle:
            dutyLimited++;
        }
      case FrameType.radioRx:
        if (payload.length < 9 + 4) return;
        try {
          _onPacket(
            RfHeader.decode(payload),
            Uint8List.sublistView(payload, 9, payload.length - 4),
          );
        } on RfException {
          // Not a packet this link understands: ignored, as a box does.
        }
    }
  }

  void _onPacket(RfHeader h, Uint8List plain) {
    switch (h.type) {
      case RfType.time:
        final t = RfTime.decode(plain);
        // An old controller that has not stepped down yet: not followed.
        if (t.term < _term) return;
        _leader = h.source;
        _term = t.term;
        _heardTime = true;
        _messages.add(LinkTime(t.stateName, t.gameTimeMs, t.durationMs));
      case RfType.cmd:
        final c = RfCmd.decode(plain);
        if (!c.isFor(join.nodeId)) return;
        // From the controller this node follows (or anyone before its first TIME).
        if (_heardTime && h.source != _leader) return;
        _messages.add(LinkCommand(c.name, c.params ?? const {}));
      case RfType.ack:
        final a = RfAck.decode(plain);
        if (a.node != join.nodeId) return;
        final before = _outbox.length;
        _outbox.removeWhere((o) {
          final done = o.pktSeqs.any(a.covers);
          if (done && o.hello && !heard) heard = true;
          return done;
        });
        acked += before - _outbox.length;
        if (before != _outbox.length) notifyListeners();
    }
  }

  // ---- out -----------------------------------------------------------------------------

  void _queueHello() {
    _outbox.removeWhere((o) => o.hello);
    final h = RfHello(
      nodeName: '${hello['node_name'] ?? 'phone-${join.nodeId}'}',
      platform: (hello['platform'] as int?) ?? 3,
      fwVersion: '${hello['fw_version'] ?? 'app'}',
      coreVersion: '${hello['core_version'] ?? ''}',
      tier: (hello['tier'] as int?) ?? 0,
      capabilities: [
        for (final c in (hello['capabilities'] as List?) ?? const [])
          if (c is int) c,
      ],
      transports: (hello['transports'] as int?) ?? RfTransport.lora,
      batteryPct: hello['battery_pct'] as int?,
      epoch: epoch,
    );
    final o = _Out(RfType.hello, RfPrio.critical, h.encode(), hello: true);
    _outbox.insert(0, o);
    _transmit(o);
  }

  /// Sends [o] in a new packet; false when no packet could be sent.
  bool _transmit(_Out o) {
    if (state != RadioLinkState.linked || pod.broken) return false;
    if (_seq > 0xffff) {
      // Every seq of this epoch is spent: a new epoch, then everything again.
      unawaited(_configure());
      return false;
    }
    final seq = _seq++;
    final header = RfHeader.v1(
      gameId: join.gameId,
      source: join.nodeId,
      seq: seq,
      hopLimit: join.maxHops,
      type: o.type,
      prio: o.prio,
      ack: o.prio != RfPrio.telemetry,
    );
    unawaited(
      pod.sendRadio(FrameType.radioTx, radioTx(header.encode(), o.payload)),
    );
    if (o.tries > 0) retried++;
    o.pktSeqs.add(seq);
    if (o.pktSeqs.length > 16) o.pktSeqs.removeAt(0);
    o.tries++;
    o.dueMs = _nowMs() + retryAfter.inMilliseconds;
    return true;
  }

  @override
  void sendEvent({
    required int seq,
    required int tMs,
    required String type,
    int team = 0,
    int squad = 0,
    String? prio,
    Map<String, Object?> data = const {},
    String? dataJson,
  }) {
    final p = RfPrio.of(prio);
    final payload = encodeEvent(
      node: join.nodeId,
      seq: seq,
      tMs: tMs,
      type: type,
      team: team,
      squad: squad,
      prio: p,
      dataJson: dataJson ?? (data.isEmpty ? null : jsonEncode(data)),
    );
    if (payload == null) return;
    sent++;
    final o = _Out(RfType.event, p, payload);
    if (p == RfPrio.telemetry) {
      _transmit(o);
      return;
    }
    if (_outbox.length >= outboxMax) {
      // The oldest normal event goes first (STATE repairs the scores).
      final i = _outbox.indexWhere((x) => x.prio == RfPrio.normal);
      _outbox.removeAt(i >= 0 ? i : 0);
      expired++;
    }
    _outbox.add(o);
    _transmit(o);
  }

  @override
  void sendState(Map<String, Object?> fields) {
    _state = fields;
    if (_stateSentMs < 0 ||
        _nowMs() - _stateSentMs >= stateEvery.inMilliseconds) {
      _sendState();
    }
  }

  void _sendState() {
    final f = _state;
    if (f == null || !linked) return;
    final counters = teamPointsOf(f['counters']);
    final st = RfState(
      ownerTeam: (f['owner_team'] as int?) ?? 0,
      phase: (f['phase'] as int?) ?? 0,
      gameTimeMs: (f['game_time_ms'] as int?) ?? 0,
      counters: counters,
      lost: teamPointsOf(f['lost']),
      batteryPct: f['battery_pct'] as int?,
      flags: f['flags'] as int?,
      epoch: epoch,
    );
    if (_transmit(_Out(RfType.state, RfPrio.telemetry, st.encode()))) {
      _stateSentMs = _nowMs();
    }
  }

  void _onTick() {
    if (state == RadioLinkState.closed) return;
    final now = _nowMs();
    if (_configureAtMs >= 0 && now >= _configureAtMs && !pod.broken) {
      unawaited(_configure());
      return;
    }
    if (!linked) return;
    for (final o in List.of(_outbox)) {
      if (now < o.dueMs) continue;
      if (o.prio != RfPrio.critical && o.tries > maxRetries) {
        _outbox.remove(o);
        expired++;
        continue;
      }
      _transmit(o);
    }
    if (_state != null && now - _stateSentMs >= stateEvery.inMilliseconds) {
      _sendState();
    }
  }

  @override
  Future<void> close() async {
    if (state == RadioLinkState.closed) return;
    final wasLinked = linked;
    state = RadioLinkState.closed;
    _ticker?.cancel();
    await _sub?.cancel();
    // The pod forgets the game key now rather than when the phone goes.
    if (wasLinked && !pod.broken) {
      await pod.sendRadio(FrameType.radioCmd, [RadioOp.clear]);
    }
    if (!_messages.isClosed) await _messages.close();
  }
}
