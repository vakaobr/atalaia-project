// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The per-source replay window (RFC 0001 Amendment 23, decision SR-20): the
// same verdicts as the C core and the Pi's port, from
// protocol/vectors/replay_window.json, and the phone controller's use of it.

import 'package:atalaia_app/radio/replay.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

void main() {
  final v = loadVectors('replay_window.json');

  test('the width is the one in the vectors', () {
    expect(ReplayWindow.width, v['width']);
  });

  const names = {
    'fresh': ReplayVerdict.fresh,
    'duplicate': ReplayVerdict.duplicate,
    'too_old': ReplayVerdict.tooOld,
  };

  for (final c in cases(v, 'cases')) {
    test('${c['name']}', () {
      final w = ReplayWindow();
      var step = 0;
      for (final s in (c['steps'] as List<dynamic>).cast<List<dynamic>>()) {
        expect(
          w.accept(ReplayWindow.counter(s[0] as int, s[1] as int)),
          names[s[2]],
          reason: 'step $step',
        );
        step++;
      }
    });
  }

  test('check changes nothing', () {
    final w = ReplayWindow();
    expect(w.accept(100), ReplayVerdict.fresh);
    expect(w.check(5000), ReplayVerdict.fresh);
    expect(w.high, 100);
    expect(w.check(100), ReplayVerdict.duplicate);
    expect(w.check(36), ReplayVerdict.tooOld);
  });
}
