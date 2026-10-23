// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The field's radio channel on the Android field controller (slice S7a of
/// PE24, decision PE24-52 moved it from S4): the channel choice and the
/// "find a quiet channel" noise scan, as the Pi controller's channels.py,
/// engine.py (`radio_settings`, `set_field_channel`, `start_scan`...) and
/// simulator/atalaia_sim/eu868.py, with the same endpoints and answers
/// (controller_api.dart; the shared contract cases check both):
///
///     GET  /api/v1/radio          the field channel, its limits, the candidates, the last scan
///     PUT  /api/v1/radio/channel  set it {"channel_hz", "source"} (no live game, no scan)
///     POST /api/v1/radio/scan     the noise scan with the radio {"dwell_s"?}
///     GET  /api/v1/radio/scan     its progress and results
///     DELETE /api/v1/radio/scan   cancel it
///     POST /api/v1/radio/random   a random legal channel, as a suggestion
///
/// The channel is a field setting (RFC 0001 Amendment 3, decisions CH1 to
/// CH8): the store's `radio.channel_hz`, `radio.channel_source`,
/// `radio.channel_confirmed` and `radio.channel_set_at`, as the Pi keeps
/// them; new games use it (the engine's `fieldChannel`, since S4). The scan
/// measures each candidate with the phone's radio, an I/O pod
/// (pod_modem.dart: MEASURE through RADIO_CMD, the answer in RADIO_NOISE),
/// for an equal share of the dwell, and ranks the results as the Pi does:
/// channels with LoRa preambles in more than 5 % of the tries last, the
/// rest quietest first by their 90th-percentile noise; the suggestion is
/// the quietest full-power channel if it is quiet enough, else the quietest
/// of all. The scan runs on the controller's event loop (the Pi's in a
/// thread); measuring takes the radio off the field's channel, so it runs
/// only with no live game, no game can be created while it runs, and the
/// radio goes back to the field's channel when it ends.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:math';

import '../pod/pod_codec.dart' show RadioNoise;
import 'controller_engine.dart';

// --- EU868 game channels (simulator/atalaia_sim/eu868.py) -----------------

const loraBwHz = 125000;
const defaultChannelHz = 869525000;

/// An EU868 sub-band and its limits (ERC/REC 70-03 Annex 1).
final class SubBand {
  const SubBand(
    this.name,
    this.erc,
    this.loHz,
    this.hiHz,
    this.duty,
    this.erpDbm,
    this.erpMw,
  );
  final String name;
  final String erc;
  final int loHz;
  final int hiHz;
  final double duty;
  final int erpDbm;
  final int erpMw;
  double get dutyPct => duty * 100;
  bool get fullPower => erpMw >= 500;
}

const subBands = [
  SubBand('g', 'h1.5', 868000000, 868600000, 0.01, 14, 25),
  SubBand('g1', 'h1.6', 868700000, 869200000, 0.001, 14, 25),
  SubBand('g2', 'h1.7', 869400000, 869650000, 0.10, 27, 500),
  SubBand('g3', 'h1.9', 869700000, 870000000, 0.01, 14, 25),
];

/// LoRaWAN's three default channels: often busy.
const lorawanDefaults = {868100000, 868300000, 868500000};

/// The channels a GM can pick from (decision CH1).
const channelCandidates = [
  868100000, 868200000, 868300000, 868400000, 868500000, // g, 1 %, 25 mW
  868800000, 868950000, 869100000, // g1, 0.1 %, 25 mW
  869475000, 869525000, 869575000, // g2, 10 %, 500 mW
  869775000, 869850000, 869925000, // g3, 1 %, 25 mW
];

/// The sub-band that holds the whole 125 kHz channel, or null.
SubBand? bandOf(int centreHz) {
  final lo = centreHz - loraBwHz ~/ 2, hi = centreHz + loraBwHz ~/ 2;
  for (final b in subBands) {
    if (b.loHz <= lo && hi <= b.hiHz) return b;
  }
  return null;
}

bool channelOk(int centreHz) => bandOf(centreHz) != null;

/// Legal and with enough airtime for a game: not in the 0.1 % sub-band.
bool usableForGames(int centreHz) {
  final b = bandOf(centreHz);
  return b != null && b.duty >= 0.01;
}

/// The candidates a scan measures and a random pick draws from.
List<int> scanCandidates() => [
  for (final hz in channelCandidates)
    if (usableForGames(hz)) hz,
];

/// A channel and its limits, for the API and the console (eu868.describe).
Map<String, Object?> describeChannel(int centreHz) {
  final b = bandOf(centreHz);
  if (b == null) {
    throw ArgumentError('$centreHz Hz is not a legal EU868 game channel');
  }
  return {
    'channel_hz': centreHz,
    'band': b.name,
    'erc_band': b.erc,
    'band_lo_hz': b.loHz,
    'band_hi_hz': b.hiHz,
    'duty_pct': roundTo(b.dutyPct, 3),
    'erp_mw': b.erpMw,
    'erp_dbm': b.erpDbm,
    'full_power': b.fullPower,
    'usable': usableForGames(centreHz),
    'notes': [
      if (centreHz == defaultChannelHz) 'default',
      if (lorawanDefaults.contains(centreHz)) 'lorawan_default',
      if (b.duty < 0.01) 'low_airtime',
    ],
  };
}

/// Python's round(x, digits) for the values the API gives (correctly
/// rounded decimal, as `toStringAsFixed`).
double roundTo(double x, int digits) => double.parse(x.toStringAsFixed(digits));

/// Python's round(x) to an int (ties to even).
int roundHalfEven(double x) {
  final f = x.floorToDouble();
  final d = x - f;
  if (d > 0.5) return f.toInt() + 1;
  if (d < 0.5) return f.toInt();
  final i = f.toInt();
  return i.isEven ? i : i + 1;
}

// --- ranking and the suggestion (channels.py) ------------------------------

/// The Pi's Noise's `activity` and dataclasses.asdict.
extension NoiseJson on RadioNoise {
  /// The share of channel-activity detections that found a LoRa preamble.
  double get activity => cadTries == 0 ? 0.0 : cadDetected / cadTries;

  Map<String, Object?> toJson() => {
    'channel_hz': channelHz,
    'dwell_ms': dwellMs,
    'samples': samples,
    'min_dbm': minDbm,
    'mean_dbm': meanDbm,
    'p50_dbm': p50Dbm,
    'p90_dbm': p90Dbm,
    'max_dbm': maxDbm,
    'cad_tries': cadTries,
    'cad_detected': cadDetected,
  };
}

const busyActivity = 0.05;
const perChannelMaxS = 10.0;
const perChannelMinS = 0.01;
const channelSources = ['default', 'scan', 'random', 'manual'];

int _compareNoise(RadioNoise a, RadioNoise b) {
  int c = (a.activity > busyActivity ? 1 : 0).compareTo(
    b.activity > busyActivity ? 1 : 0,
  );
  if (c != 0) return c;
  c = a.p90Dbm.compareTo(b.p90Dbm);
  if (c != 0) return c;
  c = a.activity.compareTo(b.activity);
  if (c != 0) return c;
  c = a.meanDbm.compareTo(b.meanDbm);
  if (c != 0) return c;
  return a.channelHz.compareTo(b.channelHz);
}

bool isQuiet(RadioNoise n, int thresholdDbm) =>
    n.p90Dbm <= thresholdDbm && n.activity <= busyActivity;

/// The channel to suggest after a scan, and why (decision CH3).
Map<String, Object?>? suggestChannel(List<RadioNoise> results, int threshold) {
  if (results.isEmpty) return null;
  final ranked = List.of(results)..sort(_compareNoise);
  final full = [
    for (final n in ranked)
      if (bandOf(n.channelHz)?.fullPower ?? false) n,
  ];
  if (full.isNotEmpty && isQuiet(full.first, threshold)) {
    return {'channel_hz': full.first.channelHz, 'reason': 'quiet_full_power'};
  }
  return {
    'channel_hz': ranked.first.channelHz,
    'reason': isQuiet(ranked.first, threshold)
        ? 'quietest'
        : 'quietest_but_noisy',
  };
}

/// A random legal channel with enough airtime for a game (decision CH5).
Map<String, Object?> randomChannel([Random? random]) {
  final pool = scanCandidates();
  final hz = pool[(random ?? Random.secure()).nextInt(pool.length)];
  return {
    ...describeChannel(hz),
    'pool': pool.length,
    'pool_full_power': pool.where((c) => bandOf(c)!.fullPower).length,
  };
}

double perChannelDwellS(double totalS, int count) =>
    max(perChannelMinS, min(perChannelMaxS, totalS / max(1, count)));

Map<String, Object?> resultRow(RadioNoise n, int threshold) => {
  ...describeChannel(n.channelHz),
  ...n.toJson(),
  'activity_pct': roundTo(n.activity * 100, 1),
  'quiet': isQuiet(n, threshold),
};

/// One noise scan over the candidates (channels.py `Scan`): [measure] is
/// the radio's MEASURE; [onChange] gets the public state before each
/// channel and at the end.
class ChannelScan {
  ChannelScan(
    this._measure,
    double totalS,
    this.thresholdDbm,
    this._onChange, {
    List<int>? channels,
    double Function()? wall,
  }) : channels = channels ?? scanCandidates(),
       _wall = wall ?? (() => DateTime.now().microsecondsSinceEpoch / 1e6) {
    dwellMs = roundHalfEven(
      perChannelDwellS(totalS, this.channels.length) * 1000,
    );
    startedAt = _wall();
  }

  final Future<RadioNoise> Function(int hz, int dwellMs) _measure;
  final void Function(Map<String, Object?> state) _onChange;
  final double Function() _wall;
  final List<int> channels;
  final int thresholdDbm;
  late final int dwellMs;
  late final double startedAt;
  double? finishedAt;

  /// running, done, failed, cancelled.
  String state = 'running';
  String? error;
  final results = <RadioNoise>[];
  int? current;
  var _cancel = false;
  final _done = Completer<void>();

  /// Completes when the scan has ended (done, failed or cancelled).
  Future<void> get done => _done.future;

  bool get running => state == 'running';

  void start() => unawaited(_run());

  void cancel() => _cancel = true;

  Future<void> _run() async {
    try {
      for (final hz in channels) {
        if (_cancel) {
          _finish('cancelled');
          return;
        }
        current = hz;
        _notify();
        results.add(await _measure(hz, dwellMs));
      }
      _finish('done');
    } on Object catch (e) {
      // A MeasureException, a link failure: the scan stops.
      error = '$e';
      _finish('failed');
    }
  }

  void _finish(String s) {
    state = s;
    current = null;
    finishedAt = _wall();
    _notify();
    if (!_done.isCompleted) _done.complete();
  }

  void _notify() {
    try {
      _onChange(public());
    } on Object {
      // A listener's failure does not stop the scan.
    }
  }

  Map<String, Object?> public() {
    final ranked = List.of(results)..sort(_compareNoise);
    return {
      'state': state,
      'error': error,
      'channels': channels.length,
      'measured': results.length,
      'current_hz': current,
      'dwell_ms': dwellMs,
      'total_s': roundTo(dwellMs * channels.length / 1000, 1),
      'threshold_dbm': thresholdDbm,
      'started_at': startedAt,
      'finished_at': finishedAt,
      'results': [for (final n in ranked) resultRow(n, thresholdDbm)],
      'suggestion': state == 'done'
          ? suggestChannel(results, thresholdDbm)
          : null,
    };
  }
}

/// Why a scan cannot run (engine.py `SCAN_UNAVAILABLE`), for a phone.
const scanUnavailableTexts = {
  'no_modem':
      'no I/O pod is linked as the radio, so the noise cannot be measured; '
      'the field keeps its channel',
  'modem_down': "the I/O pod's radio is not connected; the scan needs it",
  'no_radio': 'the I/O pod has no radio chip, so the noise cannot be measured',
  'old_firmware': "the I/O pod's firmware cannot measure noise (update it)",
};

/// The channel choice and the scan on a phone controller: set up once per
/// engine ([ControllerEngine.channel]; the API makes one when none is).
class ControllerChannel {
  ControllerChannel(
    this.engine, {
    this.scanDwellS = 60.0,
    this.quietThresholdDbm = -105,
  }) {
    engine.channel = this;
    final store = engine.store;
    final saved = store.getSetting('radio.last_scan');
    if (saved != null) {
      try {
        final v = jsonDecode(saved);
        if (v is Map) _lastScan = v.cast<String, Object?>();
      } on FormatException {
        _lastScan = null;
      }
    }
    final stored = store.getSetting('radio.channel_hz');
    final hz = stored == null ? null : int.tryParse(stored);
    if (stored != null &&
        (hz == null || !RegExp(r'^\d+$').hasMatch(stored) || !channelOk(hz))) {
      // A stored channel that is not a legal one: the configured default.
      store
        ..setSetting('radio.channel_source', 'default')
        ..setSetting('radio.channel_hz', '${engine.config.channelHz}');
    }
  }

  final ControllerEngine engine;

  /// The Pi's `radio.scan_dwell_s` and `radio.quiet_threshold_dbm`.
  final double scanDwellS;
  final int quietThresholdDbm;

  ChannelScan? scan;
  Map<String, Object?>? _lastScan;

  bool get scanRunning => scan?.running ?? false;

  String? _lockReason() {
    final g = engine.liveGame;
    if (g != null) {
      return 'game ${g['id']} is live (${g['state']}); end it first';
    }
    if (scanRunning) return 'a channel scan is running';
    return null;
  }

  String? _scanUnavailable() {
    final m = engine.modem;
    if (m == null) return 'no_modem';
    if (!m.isUp) return 'modem_down';
    if (!m.hasRadioChip) return 'no_radio';
    if (!m.canMeasure) return 'old_firmware';
    return null;
  }

  Map<String, String> get _settings => {
    for (final k in [
      'radio.channel_source',
      'radio.channel_confirmed',
      'radio.channel_set_at',
    ])
      if (engine.store.getSetting(k) != null) k: engine.store.getSetting(k)!,
  };

  /// GET /api/v1/radio.
  Map<String, Object?> settings() {
    final s = _settings;
    final setAt = double.tryParse(s['radio.channel_set_at'] ?? '') ?? 0;
    final game = engine.liveGame;
    return {
      'channel': describeChannel(engine.fieldChannel),
      'source': s['radio.channel_source'] ?? 'default',
      'confirmed': s['radio.channel_confirmed'] == '1',
      'set_at': setAt == 0 ? null : setAt,
      'default': describeChannel(engine.config.channelHz),
      'recommended_hz': defaultChannelHz,
      'candidates': [for (final hz in channelCandidates) describeChannel(hz)],
      'locked': _lockReason(),
      'scan_unavailable': _scanUnavailable(),
      'scan_dwell_s': scanDwellS,
      'quiet_threshold_dbm': quietThresholdDbm,
      'scan': scanStatus(),
      'game_channel_hz': game?['channel_hz'],
    };
  }

  /// PUT /api/v1/radio/channel: the GM's choice (accepting the default
  /// counts), stored and sent to an idle radio.
  Map<String, Object?> setChannel(Object? channelHz, Object? source) {
    final reason = _lockReason();
    if (reason != null) {
      throw ControllerError.conflict('the channel cannot change now: $reason');
    }
    final hz = _int(channelHz, 'channel_hz');
    if (!channelOk(hz)) {
      throw ControllerError(
        'channel_hz $hz: the 125 kHz channel (centre +-62.5 kHz) must fit '
        'inside one EU868 sub-band',
      );
    }
    if (!channelSources.contains(source)) {
      throw ControllerError('source: one of ${channelSources.join(', ')}');
    }
    engine.store
      ..setSetting('radio.channel_hz', '$hz')
      ..setSetting('radio.channel_source', '$source')
      ..setSetting('radio.channel_confirmed', '1')
      ..setSetting('radio.channel_set_at', '${engine.wallSeconds()}');
    final m = engine.modem;
    if (m != null && m.isUp) m.setChannel(hz);
    final out = settings();
    engine.emit({'type': 'radio', 'radio': out});
    return out;
  }

  /// POST /api/v1/radio/scan: starts the scan of the candidates.
  Map<String, Object?> startScan(Object? dwellS) {
    final reason = _lockReason();
    if (reason != null) throw ControllerError.conflict('no scan now: $reason');
    final unavailable = _scanUnavailable();
    if (unavailable != null) {
      throw ControllerError.unavailable(scanUnavailableTexts[unavailable]!);
    }
    var total = scanDwellS;
    if (dwellS != null) {
      if (dwellS is! num || dwellS < 1 || dwellS > 600) {
        throw ControllerError('dwell_s: 1 to 600 seconds');
      }
      total = dwellS.toDouble();
    }
    final m = engine.modem!;
    final s = scan = ChannelScan(
      (hz, ms) => m.measure(hz, ms),
      total,
      quietThresholdDbm,
      _onScan,
      wall: engine.wallSeconds,
    );
    s.start();
    return s.public();
  }

  /// DELETE /api/v1/radio/scan.
  Map<String, Object?> cancelScan() {
    final s = scan;
    if (s == null || !s.running) {
      throw ControllerError.conflict('no channel scan is running');
    }
    s.cancel();
    return s.public();
  }

  /// GET /api/v1/radio/scan's `scan`: the running or last scan, or null.
  Map<String, Object?>? scanStatus() => scan?.public() ?? _lastScan;

  void _onScan(Map<String, Object?> state) {
    if (state['state'] != 'running') {
      _lastScan = state;
      engine.store.setSetting('radio.last_scan', jsonEncode(state));
      final m = engine.modem;
      if (m != null && m.isUp) {
        m.setChannel(engine.fieldChannel); // back on the field's channel
      }
    }
    engine.emit({'type': 'radio_scan', 'scan': state});
  }
}

/// An integer from JSON, as Python's int() takes it (engine.py `_int`).
int _int(Object? value, String name) {
  if (value is int) return value;
  if (value is double && value.isFinite) return value.truncate();
  if (value is String) {
    final v = int.tryParse(value.trim());
    if (v != null) return v;
  }
  throw ControllerError('$name must be an integer');
}
