// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The per-source replay window (RFC 0001 Amendment 23, decision SR-20).
///
/// A port of core/src/replay.c (the Field Box and the USB modem run that one)
/// and of simulator/atalaia_sim/replay.py (the Pi controller); all three pass
/// protocol/vectors/replay_window.json.
///
/// A window keeps the highest nonce counter (epoch << 16 | seq) of an
/// authenticated packet of one source and a bitmap of the 64 counters up to
/// it. A counter above the highest is fresh; one inside the window is fresh
/// once; one 64 or more below is too old. Only [accept] a packet that has
/// authenticated. The bitmap is a 64-bit int: the app runs on the Dart VM
/// (Android), where ints wrap at 64 bits.
library;

enum ReplayVerdict { fresh, duplicate, tooOld }

class ReplayWindow {
  static const width = 64;

  int _high = 0; // the highest counter accepted
  int _seen = 0; // bit i: counter (high - i) was accepted; bit 0 is high itself
  bool _have = false;

  /// The nonce counter of a packet: epoch << 16 | seq.
  static int counter(int epoch, int seq) => (epoch << 16) | seq;

  int get high => _high;

  /// The verdict for [ctr]; changes nothing.
  ReplayVerdict check(int ctr) {
    if (!_have || ctr > _high) return ReplayVerdict.fresh;
    final back = _high - ctr;
    if (back >= width) return ReplayVerdict.tooOld;
    return (_seen >> back) & 1 == 1
        ? ReplayVerdict.duplicate
        : ReplayVerdict.fresh;
  }

  /// Checks [ctr] and, when fresh, records it.
  ReplayVerdict accept(int ctr) {
    final verdict = check(ctr);
    if (verdict != ReplayVerdict.fresh) return verdict;
    if (!_have) {
      _have = true;
      _high = ctr;
      _seen = 1;
    } else if (ctr > _high) {
      final ahead = ctr - _high;
      _seen = ahead >= width ? 0 : _seen << ahead;
      _seen |= 1;
      _high = ctr;
    } else {
      _seen |= 1 << (_high - ctr);
    }
    return verdict;
  }
}
