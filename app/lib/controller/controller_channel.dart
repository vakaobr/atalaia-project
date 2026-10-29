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
import '../protocol/radio_region.dart';
import 'controller_engine.dart';

export '../protocol/radio_region.dart' show Region, SubBand;

// --- EU868 game channels (simulator/atalaia_sim/eu868.py) -----------------
//
// The regions' table is radio_region.dart (RFC 0001 Amendment 12); these
// keep the EU868 names. Everything the field does goes through its region
// ([ControllerEngine.fieldRegion]).

const loraBwHz = 125000;
const defaultChannelHz = 869525000;

/// LoRaWAN's three default channels: often busy.
Set<int> get lorawanDefaults => eu868.busyHz;

/// The channels a GM can pick from in EU868 (decision CH1).
List<int> get channelCandidates => eu868.candidates;

/// The EU868 sub-band that holds the whole 125 kHz channel, or null.
SubBand? bandOf(int centreHz) => eu868.bandOf(centreHz);

bool channelOk(int centreHz) => eu868.channelOk(centreHz);

/// Legal and with enough airtime for a game: not in the 0.1 % sub-band.
bool usableForGames(int centreHz) => eu868.usableForGames(centreHz);

/// The candidates a scan measures and a random pick draws from.
List<int> scanCandidates([Region region = eu868]) => region.scanCandidates();

/// A channel and its limits, for the API and the console (regions.py
/// `describe`).
Map<String, Object?> describeChannel(int centreHz, [Region region = eu868]) =>
    region.describe(centreHz);

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
Map<String, Object?>? suggestChannel(
  List<RadioNoise> results,
  int threshold, [
  Region region = eu868,
]) {
  if (results.isEmpty) return null;
  final ranked = List.of(results)..sort(_compareNoise);
  final full = [
    for (final n in ranked)
      if (region.bandOf(n.channelHz)?.fullPower ?? false) n,
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

/// A random legal channel of the region with enough airtime for a game
/// (decision CH5).
Map<String, Object?> randomChannel([Random? random, Region region = eu868]) {
  final pool = region.scanCandidates();
  final hz = pool[(random ?? Random.secure()).nextInt(pool.length)];
  return {
    ...region.describe(hz),
    'pool': pool.length,
    'pool_full_power': pool.where((c) => region.bandOf(c)!.fullPower).length,
  };
}

double perChannelDwellS(double totalS, int count) =>
    max(perChannelMinS, min(perChannelMaxS, totalS / max(1, count)));

Map<String, Object?> resultRow(
  RadioNoise n,
  int threshold, [
  Region region = eu868,
]) => {
  ...region.describe(n.channelHz),
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
    this.region = eu868,
  }) : channels = channels ?? region.scanCandidates(),
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

  /// The field's region: its channels' limits in the results.
  final Region region;
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
      'region': region.code,
      'results': [for (final n in ranked) resultRow(n, thresholdDbm, region)],
      'suggestion': state == 'done'
          ? suggestChannel(results, thresholdDbm, region)
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
    final region = engine.fieldRegion;
    if (stored != null &&
        (hz == null ||
            !RegExp(r'^\d+$').hasMatch(stored) ||
            !region.channelOk(hz))) {
      // A stored channel that is not a legal one: the configured default
      // (the region's, when the configured one is another region's).
      store
        ..setSetting('radio.channel_source', 'default')
        ..setSetting('radio.channel_hz', '${_defaultHz(region)}');
    }
  }

  final ControllerEngine engine;

  /// The Pi's `radio.scan_dwell_s` and `radio.quiet_threshold_dbm`.
  final double scanDwellS;
  final int quietThresholdDbm;

  ChannelScan? scan;
  Map<String, Object?>? _lastScan;

  bool get scanRunning => scan?.running ?? false;

  /// The engine's (engine.py `_channel_lock_reason`): a live game or a
  /// running scan; pairing asks the same (slice S7c).
  String? _lockReason() => engine.channelLockReason();

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

  /// The configured channel, or the region's default when it is another
  /// region's (engine.py `radio_settings`' default).
  int _defaultHz(Region region) => region.channelOk(engine.config.channelHz)
      ? engine.config.channelHz
      : region.defaultChannelHz;

  /// GET /api/v1/radio.
  Map<String, Object?> settings() {
    final s = _settings;
    final setAt = double.tryParse(s['radio.channel_set_at'] ?? '') ?? 0;
    final game = engine.liveGame;
    final region = engine.fieldRegion;
    final modemRegion = engine.modem?.radioRegion;
    return {
      'channel': region.describe(engine.fieldChannel),
      'source': s['radio.channel_source'] ?? 'default',
      'confirmed': s['radio.channel_confirmed'] == '1',
      'set_at': setAt == 0 ? null : setAt,
      'default': region.describe(_defaultHz(region)),
      'recommended_hz': region.defaultChannelHz,
      'candidates': [for (final hz in region.candidates) region.describe(hz)],
      // The region (radio_region.py `public`, RFC 0001 Amendment 12).
      'region': region.public(),
      'region_source':
          engine.store.getSetting('radio.region') != null &&
              regionsByCode.containsKey(engine.store.getSetting('radio.region'))
          ? 'console'
          : 'config',
      'regions': [for (final r in regions) r.public()],
      'modem_region': modemRegion,
      'region_mismatch': modemRegion != null && modemRegion != region.code,
      'locked': _lockReason(),
      'scan_unavailable': _scanUnavailable(),
      'scan_dwell_s': scanDwellS,
      'quiet_threshold_dbm': quietThresholdDbm,
      'scan': scanStatus(),
      'game_channel_hz': game?['channel_hz'],
      'previous_channels_hz': history(),
    };
  }

  /// Earlier field channels remembered for the sweep (RFC 0001 Amendment 19).
  static const historyMax = 4;

  /// The field's earlier channels, newest first, never the current one:
  /// where boxes that missed a MOVE may still listen (engine.py
  /// `channel_history`).
  List<int> history() {
    final now = engine.fieldChannel;
    final out = <int>[];
    try {
      final v = jsonDecode(
        engine.store.getSetting('radio.channel_history') ?? '[]',
      );
      if (v is List) {
        for (final h in v) {
          if (h is int && h != now) out.add(h);
        }
      }
    } on FormatException {
      return [];
    }
    return out.take(historyMax).toList();
  }

  /// The revision of the field's last change of channel (MOVE key 5): it
  /// only rises.
  int moveRev() =>
      int.tryParse(engine.store.getSetting('radio.move_rev') ?? '') ?? 0;

  /// A revision above every earlier one, and at least the wall clock in
  /// seconds, so a restored backup (an older counter) still gives boxes a
  /// number above what they hold.
  int _nextMoveRev() =>
      min(0xffffffff, max(moveRev() + 1, engine.wallSeconds().toInt()));

  /// PUT /api/v1/radio/channel: the GM's choice (accepting the default
  /// counts), stored and sent to an idle radio. A new channel is first said
  /// on the old one (MOVE), so the free boxes follow it.
  Map<String, Object?> setChannel(Object? channelHz, Object? source) {
    final reason = _lockReason();
    if (reason != null) {
      throw ControllerError.conflict('the channel cannot change now: $reason');
    }
    final hz = _int(channelHz, 'channel_hz');
    final region = engine.fieldRegion;
    if (!region.channelOk(hz)) {
      throw ControllerError(
        'channel_hz $hz: the ${region.bwHz ~/ 1000} kHz channel must fit '
        'inside one ${region.code} sub-band',
      );
    }
    if (!channelSources.contains(source)) {
      throw ControllerError('source: one of ${channelSources.join(', ')}');
    }
    final old = engine.fieldChannel;
    engine.store
      ..setSetting('radio.channel_hz', '$hz')
      ..setSetting('radio.channel_source', '$source')
      ..setSetting('radio.channel_confirmed', '1')
      ..setSetting('radio.channel_set_at', '${engine.wallSeconds()}');
    var moved = false;
    if (hz != old) {
      final earlier = [
        old,
        for (final h in history())
          if (h != old && h != hz) h,
      ].take(historyMax).toList();
      final rev = _nextMoveRev();
      engine.store
        ..setSetting('radio.channel_history', jsonEncode(earlier))
        ..setSetting('radio.move_rev', '$rev');
      moved = engine.boxes?.fieldMoved(old, hz, rev) ?? false;
    }
    final m = engine.modem;
    if (m != null && m.isUp && !moved) {
      m.setChannel(hz);
      engine.modemMoved("the field's channel changed");
    }
    final out = settings();
    engine.emit({'type': 'radio', 'radio': out});
    return out;
  }

  /// PUT /api/v1/radio/region: the GM's choice of the field's radio region
  /// (engine.py `set_field_region`): only with no live game and no scan; the
  /// field moves to the region's default channel, to be confirmed, and the
  /// last scan (the old region's channels) is forgotten. The radio is tuned
  /// only when its firmware is built for the new region.
  Map<String, Object?> setRegion(Object? code) {
    final reason = _lockReason();
    if (reason != null) {
      throw ControllerError.conflict('the region cannot change now: $reason');
    }
    final region = code is String ? regionsByCode[code] : null;
    if (region == null) {
      throw ControllerError('region: one of ${regionsByCode.keys.join(', ')}');
    }
    final changed = region.code != engine.fieldRegion.code;
    engine.store.setSetting('radio.region', region.code);
    if (changed) {
      engine.store
        ..setSetting('radio.channel_hz', '${region.defaultChannelHz}')
        ..setSetting('radio.channel_source', 'default')
        ..setSetting('radio.channel_confirmed', '0')
        ..setSetting('radio.channel_set_at', '${engine.wallSeconds()}')
        ..setSetting('radio.last_scan', '')
        ..setSetting(
          'radio.channel_history',
          '[]',
        ); // another region's channels
      _lastScan = null;
      scan = null;
      final m = engine.modem;
      if (m != null && m.isUp && m.radioRegion == region.code) {
        m.setChannel(region.defaultChannelHz);
        engine.modemMoved("the field's region changed");
      }
    }
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
      region: engine.fieldRegion,
    );
    engine.modemMoved('a channel scan started');
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
        engine.modemMoved('a channel scan ended');
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
