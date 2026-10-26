// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// An I/O pod as the Android field controller's radio (slice S4 of PE24,
/// decision PE24-45): the pod runs the USB radio modem's code behind the
/// capability proxy's RADIO_* frames (protocol/capability-proxy.md, types
/// 0x05-0x0B = the modem's 0x02-0x08 + 3), so the phone does with them what
/// the Pi controller's radio_modem.py does with a USB modem
/// (protocol/usb-modem.md):
///
///   - IDENT on every new link (PodClient.start), then a PING whose STATUS
///     answer brings the radio up; the game's CONFIGURE and the boxes' peer
///     epochs again on every new link and after a pod that says who it is
///     again (it forgets the key when a link goes, as a modem that reboots);
///   - a PING every [pingInterval]; after [maxMissed] unanswered the radio
///     is down until a STATUS comes back (a link that breaks is down at
///     once);
///   - RADIO_RX to [onRx] (header, plaintext, RSSI, SNR, the sender's epoch),
///     RADIO_TX_ACK to [onTxAck], RADIO_ERROR to [onError].
///
/// Field and pair frames (re-invites, GAME_OVER, pairing by code; slice
/// S7c) go as RADIO_FIELD_TX and come as RADIO_FIELD_RX / RADIO_FIELD_ACK
/// (the modem's FIELD_* plus 3), only with a pod whose IDENT says it relays
/// them (keys 6 and 7, PE24-100 and PE24-101); with an older pod
/// [hasFieldFrames] is false and the controller says so, as a Pi does with
/// an old modem. A firmware update's offer (CMD update) and the boxes'
/// answers (HELLO, node.update_failed) are ordinary game packets, RADIO_TX
/// and RADIO_RX, which every pod relays: no IDENT key tells of them
/// (decision PE24-130); [cannotCarry] says why a pod cannot, a pod with no
/// radio chip or a radio that is down.
///
/// A pod with no radio chip is never up. Checked against the pod
/// firmware's own code (the host pod) and the Field Box's (the host box)
/// over a shared UDP air in test/controller/pod_controller_test.dart; not
/// run on a real pod yet (plan phase G).
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import '../pod/pod_client.dart';
import '../pod/pod_codec.dart';
import '../radio/rf_codec.dart';
import 'controller_radio.dart';

/// The modem's ERROR codes (modem_framing.py `ERRORS`).
const modemErrorNames = {
  1: 'bad_frame',
  2: 'unknown_type',
  3: 'unknown_cmd',
  4: 'not_configured',
  5: 'radio',
  6: 'bad_params',
  7: 'busy',
  8: 'no_radio',
};

class PodModem extends ControllerModem {
  PodModem(
    this.pod, {
    this.pingInterval = const Duration(seconds: 5),
    this.maxMissed = 3,
  });

  final PodClient pod;
  final Duration pingInterval;
  final int maxMissed;

  String _state = ModemState.connecting;
  Map<String, Object?>? _ident;
  Map<String, Object?>? _status;
  var _reconnects = 0;
  Uint8List? _config;
  final _peers = <int, int>{};
  StreamSubscription<PodEvent>? _sub;
  Timer? _pinger;
  _Measure? _measuring;
  var _token = 0;
  int? _pendingPing;
  var _missed = 0;
  var _closed = false;
  var _fieldFrames = false;
  var _pairFrames = false;
  var _fieldId = 0;

  @override
  String get kind => 'pod';

  @override
  String get state => _state;

  @override
  Map<String, Object?>? get ident => _ident;

  @override
  Map<String, Object?>? get status => _status;

  @override
  int get reconnects => _reconnects;

  @override
  bool get hasFieldFrames => _fieldFrames;

  @override
  bool get hasPairFrames => _pairFrames;

  /// Starts on a pod client that is not started yet: its IDENT comes first.
  Future<void> start() async {
    _sub = pod.events.listen(_onPod);
    _pinger = Timer.periodic(pingInterval, (_) => _ping());
    await pod.start();
  }

  Future<void> close() async {
    _closed = true;
    _pinger?.cancel();
    _measureFailed('link', 'the pod link was closed');
    await _sub?.cancel();
    if (_config != null && !pod.broken) {
      await pod.sendRadio(FrameType.radioCmd, [RadioOp.clear]);
    }
    _config = null;
  }

  void _setState(String s) {
    if (s == _state) return;
    _state = s;
    onState?.call(s);
  }

  void _send(List<int> cmd) {
    if (!pod.broken) unawaited(pod.sendRadio(FrameType.radioCmd, cmd));
  }

  void _ping() {
    if (_closed || pod.broken) return;
    if (_pendingPing != null) {
      _missed++;
      if (_missed >= maxMissed && _state == ModemState.up) {
        _setState(ModemState.down);
      }
    }
    _token = (_token + 1) & 0xffffffff;
    _pendingPing = _token;
    _send([
      RadioOp.ping,
      _token >> 24 & 0xff,
      _token >> 16 & 0xff,
      _token >> 8 & 0xff,
      _token & 0xff,
    ]);
  }

  /// What a new link (or a pod that lost its RAM) needs again.
  void _resend() {
    final c = _config;
    if (c != null) {
      _send(c);
      _sendPeers(_peers);
    }
  }

  void _onPod(PodEvent e) {
    switch (e) {
      case PodIdentified(:final ident):
        if (_ident != null) _reconnects++;
        _ident = ident.toJson()..remove('capabilities');
        _fieldFrames = ident.fieldFrames;
        _pairFrames = ident.pairFrames;
        if (!ident.hasRadio) {
          _setState(ModemState.down);
          return;
        }
        _resend();
        _missed = 0;
        _ping();
      case PodLinkBroken():
        _setState(ModemState.down);
        _measureFailed('link', 'the pod link broke');
      case PodRadioFrame(:final type, :final payload):
        _onRadio(type, payload);
      case PodCapabilityEvent():
        break;
    }
  }

  void _onRadio(int type, Uint8List p) {
    switch (type) {
      case FrameType.radioRx:
        if (p.length < 9 + 4) return;
        final RfHeader header;
        try {
          header = RfHeader.decode(p);
        } on RfException {
          return;
        }
        final n = p.length;
        onRx?.call(
          RadioRx(
            header,
            Uint8List.fromList(p.sublist(9, n - 4)),
            rssi: p[n - 4] >= 128 ? p[n - 4] - 256 : p[n - 4],
            snr: p[n - 3] >= 128 ? p[n - 3] - 256 : p[n - 3],
            epoch: p[n - 2] << 8 | p[n - 1],
          ),
        );
      case FrameType.radioTxAck:
        if (p.length != 3) return;
        onTxAck?.call(
          p[0] << 8 | p[1],
          txStatusNames[p[2]] ?? 'status_${p[2]}',
        );
      case FrameType.radioStatus:
        Object? s;
        try {
          s = jsonDecode(utf8.decode(p));
        } on FormatException {
          return;
        }
        if (s is! Map) return;
        _status = s.cast<String, Object?>();
        if (_pendingPing != null && s['ping'] == _pendingPing) {
          _pendingPing = null;
          _missed = 0;
          _setState(ModemState.up);
        }
      case FrameType.radioNoise:
        final m = _measuring;
        if (m == null) return;
        try {
          final noise = RadioNoise.decode(p);
          if (noise.channelHz != m.channelHz) {
            _measureFailed('bad_frame', 'the pod answered for another channel');
            return;
          }
          _measuring = null;
          m.timer.cancel();
          m.done.complete(noise);
        } on ProxyException catch (e) {
          _measureFailed('bad_frame', e.message);
        }
      case FrameType.radioFieldRx:
        if (p.length < 3) return;
        final n = p.length;
        onFieldRx?.call(
          Uint8List.fromList(p.sublist(0, n - 2)),
          p[n - 2] >= 128 ? p[n - 2] - 256 : p[n - 2],
          p[n - 1] >= 128 ? p[n - 1] - 256 : p[n - 1],
        );
      case FrameType.radioFieldAck:
        if (p.length != 3) return;
        onFieldAck?.call(
          p[0] << 8 | p[1],
          txStatusNames[p[2]] ?? 'status_${p[2]}',
        );
      case FrameType.radioError:
        if (p.isEmpty) return;
        final message = utf8.decode(p.sublist(1), allowMalformed: true);
        if (_measuring != null && message.startsWith('MEASURE')) {
          // The answer to a MEASURE (protocol/usb-modem.md): not an alert.
          _measureFailed(modemErrorNames[p[0]] ?? 'error_${p[0]}', message);
          return;
        }
        onError?.call(modemErrorNames[p[0]] ?? 'error_${p[0]}', message);
    }
  }

  @override
  void configure({
    required int gameId,
    required int nodeId,
    required int epoch,
    required int maxHops,
    required int channelHz,
    required Uint8List key,
  }) {
    _config = radioConfigure(
      gameId: gameId,
      nodeId: nodeId,
      epoch: epoch,
      maxHops: maxHops,
      channelHz: channelHz,
      key: key,
    );
    _peers.clear();
    _send(_config!);
  }

  @override
  void clear() {
    _config = null;
    _peers.clear();
    _send([RadioOp.clear]);
  }

  @override
  void setPeerEpochs(Map<int, int> epochs) {
    _peers.addAll(epochs);
    _sendPeers(epochs);
  }

  void _sendPeers(Map<int, int> epochs) {
    final pairs = epochs.entries.toList()
      ..sort((a, b) => a.key.compareTo(b.key));
    // 60 pairs = 241 bytes, under the frame's limit (radio_modem.py).
    for (var i = 0; i < pairs.length; i += 60) {
      _send([
        RadioOp.setPeerEpoch,
        for (final e in pairs.skip(i).take(60)) ...[
          e.key >> 8 & 0xff,
          e.key & 0xff,
          e.value >> 8 & 0xff,
          e.value & 0xff,
        ],
      ]);
    }
  }

  @override
  bool setChannel(int channelHz) {
    if (pod.broken) return false;
    _send([
      RadioOp.setChannel,
      channelHz >> 24 & 0xff,
      channelHz >> 16 & 0xff,
      channelHz >> 8 & 0xff,
      channelHz & 0xff,
    ]);
    return true;
  }

  /// A pod with a radio chip measures: its firmware runs the modem's code,
  /// MEASURE included (protocol/capability-proxy.md, RADIO_NOISE; decision
  /// PE24-77). Its IDENT says so with key 8 `measure` (PE24-101, read here
  /// since PE24-105): false makes the scan refuse up front with
  /// `old_firmware`, as the Pi does for a modem without `measure`; a pod
  /// older than the flag leaves it out and is taken to measure (every pod
  /// firmware so far does), as before.
  @override
  bool get hasRadioChip => _ident?['has_radio'] == true;

  @override
  bool get canMeasure => hasRadioChip && _ident?['measure'] != false;

  /// MEASURE through the pod (RADIO_CMD opcode 8), answered by RADIO_NOISE
  /// or a RADIO_ERROR whose message starts with "MEASURE"; one at a time,
  /// given up after the dwell plus 3 s (radio_modem.py `measure`).
  @override
  Future<RadioNoise> measure(int channelHz, int dwellMs, {bool cad = true}) {
    if (_measuring != null) {
      return Future.error(
        MeasureException('busy', 'a measurement is already running'),
      );
    }
    if (dwellMs < 10 || dwellMs > 10000) {
      return Future.error(
        MeasureException('bad_params', 'dwell of $dwellMs ms; 10-10000'),
      );
    }
    if (!isUp || pod.broken) {
      return Future.error(MeasureException('link', 'the pod radio is $state'));
    }
    final m = _Measure(channelHz);
    _measuring = m;
    m.timer = Timer(Duration(milliseconds: dwellMs + 3000), () {
      _measureFailed(
        'timeout',
        'no answer to MEASURE within ${(dwellMs / 1000 + 3).toStringAsFixed(1)} s',
      );
    });
    _send([
      RadioOp.measure,
      channelHz >> 24 & 0xff,
      channelHz >> 16 & 0xff,
      channelHz >> 8 & 0xff,
      channelHz & 0xff,
      dwellMs >> 8 & 0xff,
      dwellMs & 0xff,
      cad ? 1 : 0,
    ]);
    return m.done.future;
  }

  void _measureFailed(String code, String message) {
    final m = _measuring;
    if (m == null) return;
    _measuring = null;
    m.timer.cancel();
    m.done.completeError(MeasureException(code, message));
  }

  @override
  bool sendPacket(RfHeader header, Uint8List payload) {
    if (!isUp || pod.broken) return false;
    unawaited(
      pod.sendRadio(FrameType.radioTx, radioTx(header.encode(), payload)),
    );
    return true;
  }

  @override
  int? sendField(Uint8List frame) {
    if (!isUp || pod.broken || !_fieldFrames) return null;
    _fieldId = (_fieldId + 1) & 0xffff;
    final id = _fieldId;
    unawaited(pod.sendRadio(FrameType.radioFieldTx, radioFieldTx(id, frame)));
    return id;
  }
}

/// A MEASURE waiting for its answer.
final class _Measure {
  _Measure(this.channelHz);
  final int channelHz;
  final done = Completer<RadioNoise>();
  late Timer timer;
}
