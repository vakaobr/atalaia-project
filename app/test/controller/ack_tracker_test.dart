// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The phone controller's ACK base and bitmap (AckTracker in
// lib/controller/field_controller.dart) through a permanent gap, decision
// SL-8: the same cases as the Pi's AckTracker, from
// protocol/vectors/ack_tracker.json, byte for byte.

import 'package:atalaia_app/controller/field_controller.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

String hex(List<int> b) =>
    b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();

void main() {
  final v = loadVectors('ack_tracker.json');

  test('the window is the one in the vectors', () {
    expect(AckTracker.gapWindow, v['window']);
  });

  for (final c in cases(v, 'cases')) {
    test('${c['name']}', () {
      final a = AckTracker();
      for (final r in (c['received'] as List<dynamic>).cast<List<dynamic>>()) {
        for (var seq = r[0] as int; seq <= (r[1] as int); seq++) {
          a.record(5, 2, seq);
        }
      }
      final ack = a.ack(5, 2);
      expect(ack.node, 5);
      expect(ack.seq, c['ack_seq']);
      expect(ack.bitmap == null ? null : hex(ack.bitmap!), c['ack_bitmap']);
    });
  }

  test('a packet lost for good does not stall the ACKs', () {
    final a = AckTracker();
    for (var seq = 0; seq < 6; seq++) {
      a.record(7, 1, seq);
    }
    for (var seq = 7; seq < 1200; seq++) {
      a.record(7, 1, seq);
      final ack = a.ack(7, 1);
      expect(ack.seq, greaterThanOrEqualTo(seq - AckTracker.gapWindow - 1));
      if (ack.seq < seq) {
        final n = seq - ack.seq - 1;
        expect((ack.bitmap![n ~/ 8] >> (n % 8)) & 1, 1);
      }
    }
    expect(a.ack(7, 1).seq, 1199);
    expect(a.ack(7, 1).bitmap, isNull);
  });
}
