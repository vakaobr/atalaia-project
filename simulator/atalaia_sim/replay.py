# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The per-source replay window (RFC 0001 Amendment 23, decision SR-20).

A port of core/src/replay.c (the Field Box and the USB modem use that one); the Dart port is
app/lib/radio/replay.dart. All three are tested against protocol/vectors/replay_window.json.

A window keeps the highest nonce counter (epoch << 16 | seq) of an authenticated packet of one
source and a bitmap of the 64 counters up to it. A counter above the highest is fresh; one inside
the window is fresh once; one 64 or more below is too old. Only ``accept`` a packet that has
authenticated.
"""

from __future__ import annotations

WIDTH = 64
_MASK = (1 << WIDTH) - 1

FRESH = "fresh"
DUPLICATE = "duplicate"
TOO_OLD = "too_old"


def counter(epoch: int, seq: int) -> int:
    """The nonce counter of a packet: epoch << 16 | seq."""
    return (epoch << 16) | seq


class ReplayWindow:
    __slots__ = ("high", "seen", "have")

    def __init__(self) -> None:
        self.high = 0  # the highest counter accepted
        self.seen = 0  # bit i: counter (high - i) was accepted; bit 0 is high itself
        self.have = False

    def check(self, ctr: int) -> str:
        """The verdict for ctr; changes nothing."""
        if not self.have or ctr > self.high:
            return FRESH
        back = self.high - ctr
        if back >= WIDTH:
            return TOO_OLD
        return DUPLICATE if (self.seen >> back) & 1 else FRESH

    def accept(self, ctr: int) -> str:
        """Check ctr and, when fresh, record it."""
        verdict = self.check(ctr)
        if verdict != FRESH:
            return verdict
        if not self.have:
            self.have = True
            self.high = ctr
            self.seen = 1
        elif ctr > self.high:
            ahead = ctr - self.high
            self.seen = 0 if ahead >= WIDTH else (self.seen << ahead) & _MASK
            self.seen |= 1
            self.high = ctr
        else:
            self.seen |= 1 << (self.high - ctr)
        return verdict
