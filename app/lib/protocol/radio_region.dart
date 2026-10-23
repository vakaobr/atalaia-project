// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The radio regions a field can be in: one table, the Dart side of
/// simulator/atalaia_sim/regions.py and core/src/duty_cycle.c (RFC 0001
/// Amendment 12, decisions RF-AS923-1 onward). A region gives the LoRa
/// settings every game packet uses (spreading factor, bandwidth: the
/// channel's width), its sub-bands with their power limit and airtime
/// budget, the default channel and the channels a GM can pick from. The
/// join codec (key 18) and the phone controller ask the region, never an
/// if/else on a frequency.
///
/// EU868: ERC/REC 70-03 Annex 1, limits in ERP, SF7 at 125 kHz.
/// AS923-TW: NCC LP0002 (2020) 5.8.1, 920-925 MHz, LoRa at 500 kHz
/// ("digital modulation") with SF9, 0.5 W peak at the antenna port less the
/// antenna gain above 6 dBi; the 10 % budget is this project's own.
library;

const String limitErp = 'erp';
const String limitEirp = 'eirp';
const String limitConducted = 'conducted';

/// A sub-band and its limits.
final class SubBand {
  const SubBand(
    this.name,
    this.ref,
    this.loHz,
    this.hiHz,
    this.duty,
    this.limitDbm,
    this.limitMw, {
    this.limitRef = limitErp,
    this.freeGainDbi = 0,
    this.fullPower = false,
  });

  /// This project's label (RFC 0001 section 8; "tw" for 920-925 MHz).
  final String name;

  /// The regulation's band (ERC/REC 70-03 Annex 1, NCC LP0002).
  final String ref;
  final int loHz;
  final int hiHz;

  /// Airtime budget as a fraction of the hour.
  final double duty;
  final int limitDbm;
  final int limitMw;

  /// What the limit is measured as: [limitErp], [limitEirp] or
  /// [limitConducted] (at the antenna port).
  final String limitRef;

  /// Conducted limits: antenna gain allowed before it lowers the power.
  final int freeGainDbi;

  /// The region's highest power: the one a scan prefers.
  final bool fullPower;

  double get dutyPct => duty * 100;

  // The EU868 names, kept for the code that used them.
  String get erc => ref;
  int get erpDbm => limitDbm;
  int get erpMw => limitMw;
}

/// Python's round(x, digits) for the values the API gives.
double _round(double x, int digits) => double.parse(x.toStringAsFixed(digits));

final class Region {
  const Region({
    required this.code,
    required this.number,
    required this.name,
    required this.sf,
    required this.bwHz,
    required this.defaultChannelHz,
    required this.subBands,
    required this.candidates,
    this.busyHz = const {},
    this.maxDwellMs = 0,
  });

  /// "eu868", "as923-tw": the config's, the API's and the console's name.
  final String code;

  /// The join payload's key 18 (0: EU868, the key left out).
  final int number;
  final String name;
  final int sf;
  final int bwHz;
  final int defaultChannelHz;
  final List<SubBand> subBands;
  final List<int> candidates;

  /// Channels others crowd (LoRaWAN's defaults, Meshtastic's).
  final Set<int> busyHz;

  /// The longest single transmission (0: no rule).
  final int maxDwellMs;

  int get loHz => subBands.map((b) => b.loHz).reduce((a, b) => a < b ? a : b);
  int get hiHz => subBands.map((b) => b.hiHz).reduce((a, b) => a > b ? a : b);

  /// The sub-band that holds the whole channel, or null (edges included).
  SubBand? bandOf(Object? centreHz, [int? bwHz]) {
    if (centreHz is! int) return null;
    final bw = bwHz ?? this.bwHz;
    final lo = centreHz - bw ~/ 2, hi = centreHz + bw ~/ 2;
    for (final b in subBands) {
      if (b.loHz <= lo && hi <= b.hiHz) return b;
    }
    return null;
  }

  bool channelOk(Object? centreHz) => bandOf(centreHz) != null;

  /// Legal and with enough airtime for a game: not in a 0.1 % sub-band.
  bool usableForGames(int centreHz) {
    final b = bandOf(centreHz);
    return b != null && b.duty >= 0.01;
  }

  /// The candidates a scan measures and a random pick draws from.
  List<int> scanCandidates() => [
    for (final hz in candidates)
      if (usableForGames(hz)) hz,
  ];

  bool overlapsBusy(int centreHz) {
    final half = bwHz ~/ 2;
    return busyHz.any(
      (hz) => (centreHz - half < hz && hz < centreHz + half) || hz == centreHz,
    );
  }

  /// A channel and its limits, for the API and the console (regions.py's
  /// `describe`, the same keys and values).
  Map<String, Object?> describe(int centreHz) {
    final b = bandOf(centreHz);
    if (b == null) {
      throw ArgumentError('$centreHz Hz is not a legal $code game channel');
    }
    return {
      'channel_hz': centreHz,
      'band': b.name,
      'erc_band': b.ref,
      'band_lo_hz': b.loHz,
      'band_hi_hz': b.hiHz,
      'duty_pct': _round(b.dutyPct, 3),
      if (b.limitRef == limitErp) 'erp_mw': b.limitMw,
      if (b.limitRef == limitErp) 'erp_dbm': b.limitDbm,
      'limit_mw': b.limitMw,
      'limit_dbm': b.limitDbm,
      'limit_ref': b.limitRef,
      'full_power': b.fullPower,
      'usable': usableForGames(centreHz),
      'region': code,
      'bw_khz': bwHz ~/ 1000,
      'sf': sf,
      'notes': [
        if (centreHz == defaultChannelHz) 'default',
        if (overlapsBusy(centreHz)) 'lorawan_default',
        if (b.duty < 0.01) 'low_airtime',
      ],
    };
  }

  /// The region for the API and the console (regions.py's `public`).
  Map<String, Object?> public() => {
    'code': code,
    'name': name,
    'sf': sf,
    'bw_khz': bwHz ~/ 1000,
    'lo_hz': loHz,
    'hi_hz': hiHz,
    'default_channel_hz': defaultChannelHz,
    'max_dwell_ms': maxDwellMs,
    'sub_bands': [
      for (final b in subBands)
        {
          'name': b.name,
          'ref': b.ref,
          'lo_hz': b.loHz,
          'hi_hz': b.hiHz,
          'duty_pct': _round(b.dutyPct, 3),
          'limit_mw': b.limitMw,
          'limit_dbm': b.limitDbm,
          'limit_ref': b.limitRef,
        },
    ],
  };
}

const eu868 = Region(
  code: 'eu868',
  number: 0,
  name: 'EU868 (Europe, 868 MHz)',
  sf: 7,
  bwHz: 125000,
  defaultChannelHz: 869525000,
  subBands: [
    SubBand('g', 'h1.5', 868000000, 868600000, 0.01, 14, 25),
    SubBand('g1', 'h1.6', 868700000, 869200000, 0.001, 14, 25),
    SubBand('g2', 'h1.7', 869400000, 869650000, 0.10, 27, 500, fullPower: true),
    SubBand('g3', 'h1.9', 869700000, 870000000, 0.01, 14, 25),
  ],
  // Decision CH1.
  candidates: [
    868100000, 868200000, 868300000, 868400000, 868500000, // g, 1 %, 25 mW
    868800000, 868950000, 869100000, // g1, 0.1 %, 25 mW
    869475000, 869525000, 869575000, // g2, 10 %, 500 mW
    869775000, 869850000, 869925000, // g3, 1 %, 25 mW
  ],
  // LoRaWAN's three default channels (RP002-1.0.4): often busy.
  busyHz: {868100000, 868300000, 868500000},
);

const as923Tw = Region(
  code: 'as923-tw',
  number: 1,
  name: 'AS923 Taiwan (920-925 MHz)',
  sf: 9,
  bwHz: 500000,
  defaultChannelHz: 921500000,
  subBands: [
    SubBand(
      'tw',
      'LP0002 5.8.1',
      920000000,
      925000000,
      0.10,
      27,
      500,
      limitRef: limitConducted,
      freeGainDbi: 6,
      fullPower: true,
    ),
  ],
  // 500 kHz apart, the whole channel inside 920-925 MHz (RF-AS923-5).
  candidates: [
    920500000, 921000000, 921500000, 922000000, 922500000, //
    923000000, 923500000, 924000000, 924500000,
  ],
  // LoRaWAN AS923-1's default channels and Meshtastic's TW default.
  busyHz: {923200000, 923400000, 923875000},
);

const regions = [eu868, as923Tw];
final Map<String, Region> regionsByCode = {for (final r in regions) r.code: r};
final Map<int, Region> regionsByNumber = {for (final r in regions) r.number: r};
const defaultRegion = eu868;

/// The region named [code]; throws [ArgumentError] for anything else.
Region regionFor(Object? code) {
  final r = code is String ? regionsByCode[code] : null;
  if (r == null) {
    throw ArgumentError('region: one of ${regionsByCode.keys.join(', ')}');
  }
  return r;
}
