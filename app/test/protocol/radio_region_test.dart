// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The radio regions (lib/protocol/radio_region.dart, RFC 0001 Amendment 12),
// the same table as simulator/atalaia_sim/regions.py and core/src/duty_cycle.c:
// EU868 and AS923 as Taiwan uses it.

import 'package:atalaia_app/protocol/radio_region.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('the table', () {
    expect([for (final r in regions) r.code], ['eu868', 'as923-tw']);
    expect([for (final r in regions) r.number], [0, 1]);
    expect(regionFor('as923-tw'), same(as923Tw));
    for (final bad in ['us915', 'AS923-TW', null, 1]) {
      expect(() => regionFor(bad), throwsArgumentError, reason: '$bad');
    }
    expect(
      (as923Tw.sf, as923Tw.bwHz, as923Tw.defaultChannelHz),
      (9, 500000, 921500000),
    );
    expect((as923Tw.loHz, as923Tw.hiHz), (920000000, 925000000));
    expect((eu868.loHz, eu868.hiHz), (868000000, 870000000));
    final b = as923Tw.bandOf(921500000)!;
    expect(
      (b.limitDbm, b.limitMw, b.limitRef, b.freeGainDbi, b.fullPower),
      (27, 500, limitConducted, 6, true),
    );
  });

  test('default channels belong to their region only', () {
    for (final r in regions) {
      for (final o in regions) {
        expect(o.channelOk(r.defaultChannelHz), identical(o, r));
      }
    }
  });

  test("Taiwan's edges at 500 kHz", () {
    for (final hz in [920250000, 921500000, 924750000]) {
      expect(as923Tw.channelOk(hz), isTrue, reason: '$hz');
    }
    for (final hz in [920249999, 924750001, 920000000, 925000000, 869525000]) {
      expect(as923Tw.channelOk(hz), isFalse, reason: '$hz');
    }
    expect(as923Tw.channelOk(921500000.0), isFalse);
    expect(eu868.channelOk(869400000), isFalse); // spills out of g2
  });

  test('candidates', () {
    expect(as923Tw.candidates, hasLength(9));
    expect(as923Tw.scanCandidates(), as923Tw.candidates);
    expect(eu868.scanCandidates(), hasLength(11));
    expect(as923Tw.overlapsBusy(as923Tw.defaultChannelHz), isFalse);
    expect(as923Tw.overlapsBusy(923000000), isTrue);
  });

  test('describe and public, as regions.py', () {
    expect(as923Tw.describe(921500000), {
      'channel_hz': 921500000,
      'band': 'tw',
      'erc_band': 'LP0002 5.8.1',
      'band_lo_hz': 920000000,
      'band_hi_hz': 925000000,
      'duty_pct': 10.0,
      'limit_mw': 500,
      'limit_dbm': 27,
      'limit_ref': 'conducted',
      'full_power': true,
      'usable': true,
      'region': 'as923-tw',
      'bw_khz': 500,
      'sf': 9,
      'notes': ['default'],
    });
    final eu = eu868.describe(869525000);
    expect(
      (eu['erp_mw'], eu['erp_dbm'], eu['limit_ref'], eu['region']),
      (500, 27, 'erp', 'eu868'),
    );
    expect(eu868.describe(868100000)['notes'], ['lorawan_default']);
    expect(eu868.describe(868950000)['notes'], ['low_airtime']);
    expect(() => as923Tw.describe(869525000), throwsArgumentError);
    final p = as923Tw.public();
    expect(p['code'], 'as923-tw');
    expect(p['max_dwell_ms'], 0);
    expect((p['sub_bands']! as List).single, {
      'name': 'tw',
      'ref': 'LP0002 5.8.1',
      'lo_hz': 920000000,
      'hi_hz': 925000000,
      'duty_pct': 10.0,
      'limit_mw': 500,
      'limit_dbm': 27,
      'limit_ref': 'conducted',
    });
  });
}
