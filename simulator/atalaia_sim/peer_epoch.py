# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""When a controller names a box's epoch to the other receivers (RFC 0001 Amendment 24, decision SR-110).

A box whose epoch store was lost sends at a random epoch in [4096, 61439] (Amendment 23, SR-27), and
a box that rebooted a few times sends a little above where it was. Receivers follow a source only
within a window of epochs above the last they heard, so some of them do not hear the box until told.
The controller, which does hear it (its modem found the epoch), tells them: its own modem (SET_PEER_EPOCH)
and every box (CMD ``peer``, opcode 11, params {"src", "epoch"}, which a box applies only upwards).

The rule, and the repeats (a CMD is one shot on the air and flooded; a few repeats cover a lost one),
are this file's; the Dart port is app/lib/controller/peer_epoch.dart, and both pass
protocol/vectors/peer_epoch.json. An announcement can never move an epoch backwards: the rule needs
the heard epoch above the one known, a source is announced again only at a higher epoch than the
last announced, and the receivers (firmware set_source_epoch) refuse a lower one themselves.
"""

from __future__ import annotations

from typing import Optional

# The window above a source's epoch that a receiver follows for any packet (the modem's and the box's
# default). A heard epoch further above than this is "unexpected": some receivers would not follow it.
EPOCH_WINDOW = 16
# The announcement is sent again this long after the first (milliseconds), in case a CMD was lost.
REPEAT_AFTER_MS = (4000, 10000)

HELLO = "HELLO"


def should_announce(prior: int, heard: int, msg_type: str) -> bool:
    """Is a packet of `msg_type` heard at epoch `heard`, from a source last known at `prior` (0: not
    heard before), worth an announcement? Only an epoch above the known one ever is: a jump past the
    window, or a step up announced by a box already known (a HELLO: it has restarted). A box heard
    for the first time says HELLO at its join, and receivers new to it hear epochs 0 to the window, so
    that is announced only when it is past the window."""
    if heard <= prior or heard <= 0:
        return False
    return heard - prior > EPOCH_WINDOW or (msg_type == HELLO and prior > 0)


class PeerEpochs:
    """What a controller has announced, and the repeats that are due."""

    def __init__(self) -> None:
        self._sent: dict[int, int] = {}  # source -> the highest epoch announced
        self._repeats: dict[int, tuple[int, list[int]]] = {}  # source -> (epoch, times still due)

    def heard(self, source: int, prior: int, heard: int, msg_type: str, now_ms: int) -> bool:
        """A packet from `source` authenticated at epoch `heard`. True when it is to be announced
        now (the caller sends it and tells its modem); the repeats are then scheduled."""
        if not should_announce(prior, heard, msg_type):
            return False
        if heard <= self._sent.get(source, 0):
            return False
        self._sent[source] = heard
        self._repeats[source] = (heard, [now_ms + gap for gap in REPEAT_AFTER_MS])
        return True

    def due(self, now_ms: int) -> list[tuple[int, int]]:
        """The (source, epoch) announcements to send again at `now_ms`, each at most once per call."""
        out: list[tuple[int, int]] = []
        for source in sorted(self._repeats):
            epoch, times = self._repeats[source]
            if times and now_ms >= times[0]:
                times[:] = [t for t in times if t > now_ms]  # a late tick sends one, not a burst
                out.append((source, epoch))
            if not times:
                del self._repeats[source]
        return out

    def forget(self) -> None:
        self._sent.clear()
        self._repeats.clear()

    def last_sent(self, source: int) -> Optional[int]:
        return self._sent.get(source)
