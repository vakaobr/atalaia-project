// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A USB radio modem as the Android field controller's radio (slice S7c of
/// PE24, decision PE24-92): the Pi controller's own modem
/// (protocol/usb-modem.md, firmware/esp32/main/modem/), spoken to as the
/// Pi's controller/atalaia_controller/radio_modem.py does, over any byte
/// link (a USB-OTG CDC ACM link through the app's USB plugin, or a test's
/// socket to the host modem). Like an I/O pod whose firmware relays them
/// (pod_modem.dart, decisions PE24-100 and PE24-101; an older pod does not)
/// it carries field and pair frames (FIELD_TX, FIELD_RX, FIELD_ACK):
/// re-invites, GAME_OVER and pairing by code.
///
///   - IDENT at once (a JSON answer: `field`, `pair`, `radio`...), then a
///     PING whose STATUS brings the radio up; the game's CONFIGURE and the
///     boxes' peer epochs again on every [linkRestarted] (a modem that
///     rebooted forgot them);
///   - a PING every [pingInterval]; after [maxMissed] unanswered the radio
///     is down until a STATUS comes back;
///   - RX, TX_ACK, FIELD_RX, FIELD_ACK and ERROR to the callbacks;
///   - MEASURE for the channel scan (slice S7a's controller_channel.dart),
///     answered by NOISE or an ERROR whose message starts with "MEASURE",
///     as radio_modem.py `measure`; the modem's IDENT says `measure`.
///
/// Reconnecting the port itself is the link's (the shell's) job, as the
/// pod's: a new link is a new [SerialModem.start] on it.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import '../pod/pod_client.dart' show PodTransport;
import '../pod/pod_codec.dart';
import '../radio/rf_codec.dart';
import 'controller_radio.dart';
import 'pod_modem.dart' show modemErrorNames;

/// The modem's frame types (protocol/usb-modem.md).
abstract final class ModemFrame {
  static const ident = 0x01;
  static const rx = 0x02;
  static const tx = 0x03;
  static const txAck = 0x04;
  static const cmd = 0x05;
  static const status = 0x06;
  static const error = 0x07;
  static const noise = 0x08;
  static const fieldTx = 0x09;
  static const fieldRx = 0x0a;
  static const fieldAck = 0x0b;
}

/// FIELD_ACK's statuses (the modem's TX statuses, 8 busy while a MEASURE runs).
String fieldAckStatus(int s) => txStatusNames[s] ?? 'status_$s';

class SerialModem extends ControllerModem {
  SerialModem(
    this.link, {
    this.pingInterval = const Duration(seconds: 5),
    this.maxMissed = 3,
  });

  final PodTransport link;
  final Duration pingInterval;
  final int maxMissed;

  String _state = ModemState.connecting;
  Map<String, Object?>? _ident;
  Map<String, Object?>? _status;
  var _reconnects = 0;
  Uint8List? _config;
  final _peers = <int, int>{};
  final _decoder = FrameDecoder();
  StreamSubscription<Uint8List>? _sub;
  Timer? _pinger;
  var _token = 0;
  int? _pendingPing;
  var _missed = 0;
  var _fieldId = 0;
  var _closed = false;
  _Measure? _measuring;
  String? _lang; // the screen language to give the modem (setLanguage)
  var _langSent = false; // the modem holds a language of ours

  @override
  String get state => _state;

  @override
  Map<String, Object?>? get ident => _ident;

  @override
  Map<String, Object?>? get status => _status;

  @override
  int get reconnects => _reconnects;

  @override
  bool get hasFieldFrames => _ident?['field'] == true;

  @override
  bool get hasPairFrames => _ident?['pair'] == true;

  /// The firmware takes a screen language (IDENT `lang`, SET_LANG).
  bool get hasLanguage => _ident?['lang'] == true;

  /// SET_LANG (opcode 9): the modem's OLED in [code], sent when IDENT says
  /// the firmware knows it, and again on every IDENT (a rebooted modem forgot
  /// it); null sends the modem back to its build's language.
  @override
  void setLanguage(String? code) {
    if (code != null && !_langCode.hasMatch(code)) {
      throw ArgumentError.value(code, 'code', 'a language code');
    }
    _lang = code == null || code.isEmpty ? null : code.toLowerCase();
    if (isUp && hasLanguage) _sendLanguage();
  }

  static final _langCode = RegExp(r'^[A-Za-z0-9-]{0,8}$');

  void _sendLanguage() {
    if (_lang == null && !_langSent) return;
    _write(ModemFrame.cmd, [RadioOp.setLang, ...ascii.encode(_lang ?? '')]);
    _langSent = _lang != null;
  }

  Future<void> start() async {
    _sub = link.incoming.listen(
      _onBytes,
      onDone: () {
        _setState(ModemState.down);
        _measureFailed('link', 'the modem link was closed');
      },
      onError: (Object _) {
        _setState(ModemState.down);
        _measureFailed('link', 'the modem link broke');
      },
    );
    _pinger = Timer.periodic(pingInterval, (_) => _ping());
    _write(ModemFrame.cmd, const [RadioOp.ident]);
    _ping();
  }

  /// The modem answered IDENT again after a reboot: what it forgot goes again.
  void linkRestarted() {
    _reconnects++;
    _resend();
  }

  Future<void> close() async {
    _closed = true;
    _pinger?.cancel();
    if (_config != null) _write(ModemFrame.cmd, const [RadioOp.clear]);
    await _sub?.cancel();
    _config = null;
  }

  void _setState(String s) {
    if (s == _state) return;
    _state = s;
    onState?.call(s);
  }

  bool _write(int type, List<int> payload) {
    if (_closed) return false;
    unawaited(link.send(encodeFrame(type, payload)));
    return true;
  }

  void _ping() {
    if (_closed) return;
    if (_pendingPing != null) {
      _missed++;
      if (_missed >= maxMissed && _state == ModemState.up) {
        _setState(ModemState.down);
      }
    }
    _token = (_token + 1) & 0xffffffff;
    _pendingPing = _token;
    _write(ModemFrame.cmd, [
      RadioOp.ping,
      _token >> 24 & 0xff,
      _token >> 16 & 0xff,
      _token >> 8 & 0xff,
      _token & 0xff,
    ]);
  }

  void _resend() {
    final c = _config;
    if (c == null) return;
    _write(ModemFrame.cmd, c);
    _sendPeers(_peers);
  }

  void _onBytes(Uint8List data) {
    for (final f in _decoder.feed(data)) {
      _dispatch(f.type, f.payload);
    }
  }

  void _dispatch(int type, Uint8List p) {
    switch (type) {
      case ModemFrame.ident:
        final Object? id;
        try {
          id = jsonDecode(utf8.decode(p));
        } on FormatException {
          return;
        }
        if (id is! Map) return;
        final again = _ident != null;
        _ident = id.cast<String, Object?>();
        if (again) linkRestarted();
        // A modem that identifies itself shows its build's language until told.
        _langSent = false;
        if (hasLanguage && _lang != null) _sendLanguage();
      case ModemFrame.rx:
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
            rssi: _i8(p[n - 4]),
            snr: _i8(p[n - 3]),
            epoch: p[n - 2] << 8 | p[n - 1],
          ),
        );
      case ModemFrame.txAck:
        if (p.length != 3) return;
        onTxAck?.call(
          p[0] << 8 | p[1],
          txStatusNames[p[2]] ?? 'status_${p[2]}',
        );
      case ModemFrame.fieldRx:
        if (p.length < 3) return;
        final n = p.length;
        onFieldRx?.call(
          Uint8List.fromList(p.sublist(0, n - 2)),
          _i8(p[n - 2]),
          _i8(p[n - 1]),
        );
      case ModemFrame.fieldAck:
        if (p.length != 3) return;
        onFieldAck?.call(p[0] << 8 | p[1], fieldAckStatus(p[2]));
      case ModemFrame.status:
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
      case ModemFrame.noise:
        final m = _measuring;
        if (m == null) return;
        try {
          final noise = RadioNoise.decode(p);
          if (noise.channelHz != m.channelHz) {
            _measureFailed(
              'bad_frame',
              'the modem answered for another channel',
            );
            return;
          }
          _measuring = null;
          m.timer.cancel();
          m.done.complete(noise);
        } on ProxyException catch (e) {
          _measureFailed('bad_frame', e.message);
        }
      case ModemFrame.error:
        if (p.isEmpty) return;
        final code = modemErrorNames[p[0]] ?? 'error_${p[0]}';
        final message = utf8.decode(p.sublist(1), allowMalformed: true);
        if (_measuring != null && message.startsWith('MEASURE')) {
          // The answer to a MEASURE (protocol/usb-modem.md): not an alert.
          _measureFailed(code, message);
          return;
        }
        onError?.call(code, message);
    }
  }

  static int _i8(int b) => b >= 128 ? b - 256 : b;

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
    _write(ModemFrame.cmd, _config!);
  }

  @override
  void clear() {
    _config = null;
    _peers.clear();
    _write(ModemFrame.cmd, const [RadioOp.clear]);
  }

  @override
  void setPeerEpochs(Map<int, int> epochs) {
    // Never backwards (SR-111): what is sent again after a reconnect is the highest.
    epochs.forEach((node, epoch) {
      if (epoch > (_peers[node] ?? 0)) _peers[node] = epoch;
    });
    _sendPeers(epochs);
  }

  void _sendPeers(Map<int, int> epochs) {
    final pairs = epochs.entries.toList()
      ..sort((a, b) => a.key.compareTo(b.key));
    for (var i = 0; i < pairs.length; i += 60) {
      _write(ModemFrame.cmd, [
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
  bool setChannel(int channelHz) => _write(ModemFrame.cmd, [
    RadioOp.setChannel,
    channelHz >> 24 & 0xff,
    channelHz >> 16 & 0xff,
    channelHz >> 8 & 0xff,
    channelHz & 0xff,
  ]);

  /// MEASURE (opcode 8), one at a time, given up after the dwell plus 3 s.
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
    if (!isUp) {
      return Future.error(
        MeasureException('link', 'the radio modem is $state'),
      );
    }
    final m = _Measure(channelHz);
    _measuring = m;
    m.timer = Timer(Duration(milliseconds: dwellMs + 3000), () {
      _measureFailed(
        'timeout',
        'no answer to MEASURE within ${(dwellMs / 1000 + 3).toStringAsFixed(1)} s',
      );
    });
    _write(ModemFrame.cmd, [
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
    if (!isUp) return false;
    return _write(ModemFrame.tx, radioTx(header.encode(), payload));
  }

  @override
  int? sendField(Uint8List frame) {
    if (!isUp) return null;
    _fieldId = (_fieldId + 1) & 0xffff;
    final id = _fieldId;
    return _write(ModemFrame.fieldTx, [id >> 8, id & 0xff, ...frame])
        ? id
        : null;
  }
}

/// A MEASURE waiting for its answer.
final class _Measure {
  _Measure(this.channelHz);
  final int channelHz;
  final done = Completer<RadioNoise>();
  late Timer timer;
}

/// What answers on a USB or Bluetooth radio link (decision PE24-92): an I/O
/// pod (its IDENT is CBOR, the capability proxy's) or the Pi's USB radio
/// modem (its IDENT is JSON). Both are asked at once, each in its own
/// protocol, which the other ignores; "pod" when nothing answers within
/// [timeout] (the link of earlier slices, which a later IDENT still takes).
Future<String> probeRadioLink(
  PodTransport link, {
  Duration timeout = const Duration(milliseconds: 1500),
}) async {
  final decoder = FrameDecoder();
  final found = Completer<String>();
  final sub = link.incoming.listen((data) {
    for (final f in decoder.feed(data)) {
      if (f.type == ModemFrame.ident &&
          f.payload.isNotEmpty &&
          !found.isCompleted) {
        found.complete(f.payload.first == 0x7b ? 'modem' : 'pod'); // '{'
      }
    }
  }, onError: (Object _) {});
  try {
    await link.send(encodeFrame(ModemFrame.cmd, const [RadioOp.ident]));
    await link.send(encodeFrame(FrameType.radioCmd, const [RadioOp.ident]));
    return await found.future.timeout(timeout, onTimeout: () => 'pod');
  } finally {
    await sub.cancel();
  }
}
