# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""MOVE: a field's boxes follow its channel (RFC 0001 Amendment 19; atalaia_sim.lobby).

The 2026-10-29 bench finding: a radio scan moved the controller's field channel and the idle boxes,
listening on their last game's channel, heard neither DISCOVER nor invites. The controller says on
the old channel where the field is now (MOVE, three times) and a sweep says it again on each earlier
channel for boxes that were away. The model has one air per channel: a frame reaches the boxes
tuned to the channel the controller's modem is on.

    cd simulator && python -m unittest tests.test_move_sim
"""

from __future__ import annotations

import os
import random
import unittest

from atalaia_sim import eu868, lobby
from atalaia_sim import field_frame as ff


def _has_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESCCM  # noqa: F401
        return True
    except ImportError:
        return False


if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and not _has_crypto():
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but cryptography is not available")

JOIN_KEY = bytes(range(32))
OTHER = bytes(range(100, 132))
OLD, NEW, OLDER = 869_525_000, 869_925_000, 868_100_000  # g2 (default), g3 (the bench's scan), g
AS923_DEFAULT = 921_500_000


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class MoveSim(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.modem = OLD            # the channel the controller's modem is tuned to
        self.tuned: list = []       # every tune the inviter asked for, in order
        self.sent: list = []        # (ms, channel, kind)
        self.inviter = lobby.Inviter(JOIN_KEY, self._send, rng=random.Random(3))
        self.inviter.tune = self._tune
        self.field = OLD            # the controller's "field channel" setting
        self.done = 0
        self.inviter.on_orders_done = self._done  # as the controller does: a DISCOVER on the new channel
        self.boxes = [lobby.IdleBox(JOIN_KEY, f"box-{i}", rng=random.Random(i), channel_hz=OLD, now_ms=0)
                      for i in range(3)]
        self.asleep: set[int] = set()  # boxes (by index) that hear nothing

    def _tune(self, channel_hz):
        self.tuned.append(channel_hz)
        self.modem = self.field if channel_hz is None else channel_hz
        return True

    def _done(self):
        self.done += 1
        self.inviter.discover(self.now, force=True)

    def _send(self, frame):
        self.sent.append((self.now, self.modem, ff.decode(ff.field_key(JOIN_KEY), frame)["kind"]))
        for i, box in enumerate(self.boxes):
            if i not in self.asleep and box.channel_hz == self.modem:
                box.on_frame(frame, self.now)
        return len(self.sent)

    def run_for(self, ms, step=50):
        end = self.now + ms
        while self.now < end:
            self.now += step
            self.inviter.tick(self.now)
            for box in self.boxes:
                for frame in box.tick(self.now):
                    if box.channel_hz == self.modem:  # the controller hears it only on its channel
                        self.inviter.on_frame(frame, self.now, rssi=-70)

    def heard(self):
        return sorted(b.name for b in self.inviter.available(self.now))

    # --- the controller moves the field -----------------------------------------------------

    def test_the_boxes_follow_a_move_said_on_the_old_channel(self):
        self.run_for(25_000)
        self.assertEqual(self.heard(), ["box-0", "box-1", "box-2"])  # all heard on OLD
        self.inviter.boxes.clear()
        self.field = NEW
        self.inviter.move(OLD, NEW, rev=1, now_ms=self.now)
        self.run_for(1_000)
        self.assertEqual([b.channel_hz for b in self.boxes], [NEW] * 3)
        self.assertEqual(set(self.tuned), {OLD})     # still on the old channel while it was said
        self.run_for(8_000)
        self.assertEqual(self.tuned, [OLD, OLD, OLD, None])  # then the modem goes to the field's channel: NEW
        self.assertEqual(self.modem, NEW)
        self.assertEqual(self.done, 1)
        # Three MOVE frames, 2.5 s apart, all on the old channel, about 90 ms of air each.
        moves = [(ms, ch) for ms, ch, kind in self.sent if kind == "move"]
        self.assertEqual([ch for _, ch in moves], [OLD] * 3)
        gaps = [b[0] - a[0] for a, b in zip(moves, moves[1:])]
        self.assertTrue(all(2_500 <= g <= 2_700 for g in gaps), gaps)
        # The DISCOVER on the new channel, as the burst ends, brings every box's answer at once.
        self.assertEqual(self.sent[-1][1:], (NEW, "discover"))
        self.run_for(4_000)
        self.assertEqual(self.heard(), ["box-0", "box-1", "box-2"])
        self.assertTrue(all("the field moved to" in " ".join(b.log) for b in self.boxes))

    def test_a_discover_on_the_new_channel_is_answered_at_once_after_a_move(self):
        self.run_for(25_000)
        self.field = NEW
        self.inviter.move(OLD, NEW, rev=1, now_ms=self.now)
        self.run_for(300)
        self.assertEqual([b.channel_hz for b in self.boxes], [NEW] * 3)
        self.inviter.boxes.clear()
        self.run_for(10_000)  # the modem is on NEW now, and the DISCOVER went
        self.assertEqual(self.modem, NEW)
        self.assertEqual(self.heard(), ["box-0", "box-1", "box-2"])

    def test_a_box_that_missed_the_move_is_found_by_the_sweep(self):
        self.run_for(25_000)
        self.asleep = {1}                              # box-1 hears nothing while the field moves
        self.field = NEW
        self.inviter.move(OLD, NEW, rev=1, now_ms=self.now)
        self.run_for(10_000)
        self.assertEqual([b.channel_hz for b in self.boxes], [NEW, OLD, NEW])
        self.asleep = set()
        self.assertTrue(self.inviter.sweep([OLD, OLDER], NEW, 1, self.now))
        self.tuned.clear()
        self.sent.clear()
        self.run_for(20_000)
        self.assertEqual([b.channel_hz for b in self.boxes], [NEW] * 3)
        # One MOVE pair per earlier channel, one channel after the other, then back on the field's.
        self.assertEqual([ch for _, ch, kind in self.sent if kind == "move"], [OLD, OLD, OLDER, OLDER])
        self.assertEqual(self.tuned, [OLD, OLD, OLDER, OLDER, None])
        self.assertEqual(self.modem, NEW)
        self.assertEqual(self.done, 2)
        self.assertEqual(self.sent[-1][1:], (NEW, "discover"))

    def test_the_sweep_waits_for_the_discovers_answers_and_is_rate_limited(self):
        self.assertTrue(self.inviter.sweep([OLD], NEW, 1, 1_000))
        self.assertEqual(self.inviter.moves[0].next_ms, 1_000 + lobby.SWEEP_AFTER_DISCOVER_MS)
        self.inviter.moves.clear()
        self.assertFalse(self.inviter.sweep([OLD], NEW, 1, 1_000 + lobby.SWEEP_MIN_MS - 1))
        self.assertTrue(self.inviter.sweep([OLD], NEW, 1, 1_000 + lobby.SWEEP_MIN_MS))
        self.inviter.moves.clear()
        self.assertFalse(self.inviter.sweep([NEW], NEW, 1, 10 ** 7), "nothing earlier than the field's channel")
        self.assertFalse(self.inviter.sweep([], NEW, 1, 10 ** 7))

    def test_the_air_used_is_small(self):
        self.inviter.move(OLD, NEW, rev=1, now_ms=0)
        self.run_for(9_000)
        moves = [s for s in self.sent if s[2] == "move"]
        self.assertEqual(len(moves), 3)
        frame = ff.encode(ff.field_key(JOIN_KEY), {"kind": "move", "channel_hz": NEW, "rev": 1}, bytes(13))
        air = len(moves) * eu868.airtime_ms(len(frame))
        self.assertLess(len(frame), 45)
        self.assertLess(air, 300)  # about 0.25 s of air in all: 0.7 % of an hour's budget on a 1 % sub-band

    # --- what a box refuses -------------------------------------------------------------------

    def box(self, **kw):
        return lobby.IdleBox(JOIN_KEY, "box", rng=random.Random(1), channel_hz=OLD, now_ms=0, **kw)

    def test_a_box_takes_only_a_higher_revision(self):
        box = self.box()
        self.assertTrue(box.on_move({"channel_hz": NEW, "rev": 5}, 0))
        self.assertEqual((box.channel_hz, box.move_rev), (NEW, 5))
        for rev in (5, 4, 1):  # a repeat, and a recording played back later
            self.assertFalse(box.on_move({"channel_hz": OLD, "rev": rev}, 0))
        self.assertEqual(box.channel_hz, NEW)
        self.assertTrue(box.on_move({"channel_hz": OLD, "rev": 6}, 0))
        self.assertEqual(box.channel_hz, OLD)
        box.move_rev = 0xFFFFFFFF  # serial arithmetic: after the wrap, 1 is newer
        self.assertTrue(box.on_move({"channel_hz": NEW, "rev": 1}, 0))
        self.assertFalse(box.on_move({"channel_hz": OLD, "rev": 0xFFFFFFFF}, 0))

    def test_a_box_refuses_another_regions_channel_and_a_game(self):
        box = self.box()
        self.assertFalse(box.on_move({"channel_hz": AS923_DEFAULT, "rev": 9}, 0))
        self.assertEqual((box.channel_hz, box.move_rev), (OLD, 0))
        self.assertFalse(box.on_move({"channel_hz": 868_000_000, "rev": 9}, 0), "a channel that spills over a sub-band")
        box.phase = "playing"
        self.assertFalse(box.on_move({"channel_hz": NEW, "rev": 9}, 0))
        self.assertEqual(box.channel_hz, OLD)

    def test_another_fields_move_is_not_heard(self):
        box = self.box()
        frame = ff.encode(ff.field_key(OTHER), {"kind": "move", "channel_hz": NEW, "rev": 9}, bytes(13))
        box.on_frame(frame, 0)
        self.assertEqual(box.channel_hz, OLD)

    def test_a_box_that_stays_announces_again_only_on_a_new_channel(self):
        box = self.box()
        box.on_move({"channel_hz": OLD, "rev": 2}, 0)  # the field did not change channel: nothing to say
        self.assertEqual(box.move_rev, 2)
        self.assertNotIn("the field moved", " ".join(box.log))


class MoveCodecTests(unittest.TestCase):
    def test_round_trip_and_limits(self):
        msg = {"kind": "move", "channel_hz": NEW, "rev": 7}
        body = ff.body_encode(msg)
        self.assertEqual(ff.body_decode(body), msg)
        self.assertEqual(len(body), 1 + 1 + 1 + 1 + 5 + 1 + 1)  # map, 1:5, 4:uint32, 5:uint8
        for bad in ({"channel_hz": 0}, {"rev": 0}, {"channel_hz": 2 ** 32}, {"rev": -1}, {"channel_hz": "x"}):
            with self.assertRaises(ff.FieldFrameError):
                ff.body_encode({**msg, **bad})

    def test_kind_6_is_still_unknown(self):
        from atalaia_sim import cbor
        with self.assertRaises(ff.FieldFrameError):
            ff.body_decode(cbor.encode({1: 6, 4: NEW, 5: 1}))


if __name__ == "__main__":
    unittest.main()
