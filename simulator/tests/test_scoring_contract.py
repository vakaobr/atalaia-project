# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The optional `scoring` block of a mode's manifest (decision BSC-2, modes/README.md "Projected
score") and the controller's projection of a held box's points between two STATEs.

    cd simulator && python -m unittest discover -s tests
"""

from __future__ import annotations

import unittest
from pathlib import Path

from atalaia_sim import codec
from atalaia_sim.field_controller import GAME_RUNNING, FieldController
from atalaia_sim.mode import ModeError, check_manifest, compose, hold_scoring, load_mode
from atalaia_sim.packet import Header, state_encode, vf_make
from atalaia_sim.protocol import MESSAGE_TYPES

MODES = Path(__file__).resolve().parents[2] / "modes"

PARAMS = {"tick_s": {"type": "int", "min": 1, "max": 600, "default": 10},
          "points": {"type": "int", "min": 1, "max": 100, "default": 1},
          "zero": {"type": "int", "min": 0, "max": 5, "default": 0},
          "label": {"type": "text"}}


def manifest(scoring, **extra):
    return {"id": "org.x.y", "version": "1", "roles": {"r": {}}, "params": PARAMS, "scoring": scoring, **extra}


class ScoringManifestTests(unittest.TestCase):
    def test_valid_blocks(self):
        for scoring in ({"hold": {"every": "tick_s", "points": "points"}},
                        {"hold": {"every": 5, "points": 1}},
                        {"hold": {"every": "tick_s", "points": 3}}):
            with self.subTest(scoring):
                check_manifest(manifest(scoring), "m")

    def test_invalid_blocks(self):
        bad = [
            "hold", [], {}, {"hold": {}}, {"other": {}},
            {"hold": {"every": "tick_s"}},
            {"hold": {"every": "tick_s", "points": "points", "extra": 1}},
            {"hold": {"every": 0, "points": 1}},          # a whole number from 1
            {"hold": {"every": True, "points": 1}},
            {"hold": {"every": 1.5, "points": 1}},
            {"hold": {"every": "nope", "points": 1}},     # not a parameter
            {"hold": {"every": "label", "points": 1}},    # not an int parameter
            {"hold": {"every": "zero", "points": 1}},     # min 0: a game could set 0
        ]
        for scoring in bad:
            with self.subTest(scoring), self.assertRaises(ModeError):
                check_manifest(manifest(scoring), "m")
        with self.assertRaises(ModeError):  # only a mode scores
            check_manifest(manifest({"hold": {"every": 5, "points": 1}}, kind="role"), "m")

    def test_the_games_own_values(self):
        scoring = {"hold": {"every": "tick_s", "points": "points"}}
        self.assertEqual(hold_scoring(scoring, {"tick_s": 10, "points": 2}), (10_000, 2))
        self.assertEqual(hold_scoring({"hold": {"every": 5, "points": 1}}, {}), (5_000, 1))
        self.assertIsNone(hold_scoring(scoring, {"tick_s": 10}))   # a value the game does not give
        self.assertIsNone(hold_scoring(scoring, {"tick_s": 0, "points": 1}))
        self.assertIsNone(hold_scoring(None, {}))

    def test_domination_opts_in_and_a_composed_game_does_not(self):
        dom = load_mode(MODES / "domination")
        self.assertEqual(dom.scoring, {"hold": {"every": "tick_s", "points": "points_per_tick"}})
        self.assertIsNone(load_mode(MODES / "holdall").scoring)
        self.assertIsNone(compose(dom, [load_mode(MODES / "codes")]).scoring)


def header(source: int, seq: int) -> Header:
    return Header(version_flags=vf_make(1, 1, False, True), game_id=1, source=source, seq=seq,
                  hop_limit=2, type=MESSAGE_TYPES["STATE"])


class NullTx:
    seq = 0

    def send(self, msg_type, payload, *, priority, ack_req, hop_limit, now_ms):
        self.seq += 1
        return self.seq


class ProjectionTests(unittest.TestCase):
    """A Domination-like game: 2 points every 10 s for the owner of a box."""

    def setUp(self):
        self.fc = FieldController(transport=NullTx(), teams=["red", "blue"], node_id=0)
        self.fc.scoring_hold = (10_000, 2)
        self.drifts: list[dict] = []
        self.fc.on_drift = self.drifts.append
        self.fc.start_game(now_ms=0)

    def state(self, node, seq, owner, counters, game_ms, **extra):
        payload = state_encode({"owner_team": owner, "phase": 1, "game_time_ms": game_ms,
                                "counters": counters, "epoch": 0, **extra})
        self.fc.on_packet(node, header(node, seq), payload, {"epoch": 0})

    def test_ticks_since_the_report_are_added_and_the_next_state_replaces_them(self):
        self.state(4, 0, 1, {}, 0)
        self.fc.tick(25_000)
        self.assertEqual(self.fc.projected_scores(), {"red": 4, "blue": 0})
        self.assertEqual(self.fc.total_scores, {"red": 0, "blue": 0})  # reports only
        self.state(4, 1, 1, {1: 4}, 20_000)
        self.assertEqual(self.fc.projected_scores(), {"red": 4, "blue": 0})
        self.assertEqual(self.drifts[-1]["drift"], 0)
        self.fc.tick(35_000)
        self.assertEqual(self.fc.projected_scores()["red"], 6)
        self.state(4, 2, 1, {1: 4}, 35_000)  # the box missed a tick: the drift is one tick
        self.assertEqual(self.fc.projected_scores()["red"], 4)
        stats = self.fc.projection_stats
        self.assertEqual((stats["samples"], stats["off"], stats["max_abs"]), (2, 1, 2))

    def test_two_boxes_and_a_capture_between_reports(self):
        self.state(4, 0, 1, {}, 0)
        self.state(5, 0, 2, {}, 0)
        self.fc.tick(10_000)
        self.assertEqual(self.fc.projected_scores(), {"red": 2, "blue": 2})
        self.fc.tick(20_000)
        # Box 4 was captured by blue before its next report: the projection credited red one tick
        # too many (drift +2), the report corrects it.
        self.state(4, 1, 2, {1: 2}, 20_000)
        self.assertEqual(self.drifts[-1]["drift"], 2)
        self.assertEqual(self.fc.projected_scores(), {"red": 2, "blue": 4})

    def captured(self, node, seq, team, t, previous=None, type_="zone.captured"):
        data = {"previous_team": previous} if previous else {}
        payload = codec.encode_event({"node": node, "seq": seq, "t": t, "type": type_, "team": team,
                                      "data": data})
        hdr = Header(version_flags=vf_make(1, 1, False, True), game_id=1, source=node, seq=100 + seq,
                     hop_limit=2, type=MESSAGE_TYPES["EVENT"])
        self.fc.on_packet(node, hdr, payload, {"epoch": 0})

    def test_a_capture_then_a_lost_state_counts_for_the_new_owner(self):
        """The bench case (BSC-4): the capture was sent and ACKed, the STATE after it was lost."""
        self.state(4, 0, 1, {1: 4}, 20_000)
        self.fc.tick(33_000)
        self.assertEqual(self.fc.projected_scores(), {"red": 4 + 2, "blue": 0})
        self.captured(4, 1, 2, 33_000, previous="red")
        self.assertEqual(self.fc.projected_scores(), {"red": 4 + 2, "blue": 0})
        # Red kept the tick of 30 s (before the capture); from 33 s the ticks are blue's.
        self.fc.tick(60_000)
        self.assertEqual(self.fc.projected_scores(), {"red": 4 + 2, "blue": 2 * 3})
        self.assertEqual(self.fc.total_scores, {"red": 4, "blue": 0})  # reports only
        self.state(4, 1, 2, {1: 6, 2: 6}, 60_000)  # the next STATE that got through is the truth
        self.assertEqual(self.fc.projected_scores(), {"red": 6, "blue": 6})
        self.assertEqual(self.fc.nodes[4].changes, [])
        self.assertEqual((self.drifts[-1]["team"], self.drifts[-1]["drift"]), ("red", 0))

    def test_a_capture_then_its_state_leaves_nothing_of_the_event(self):
        self.state(4, 0, 1, {1: 2}, 10_000)
        self.fc.tick(24_000)
        self.captured(4, 1, 2, 22_000)
        self.assertEqual(self.fc.projected_scores(), {"red": 2 + 2, "blue": 0})
        self.state(4, 1, 2, {1: 4, 2: 0}, 24_000)
        self.assertEqual(self.fc.projected_scores(), {"red": 4, "blue": 0})
        self.fc.tick(30_000)
        self.assertEqual(self.fc.projected_scores(), {"red": 4, "blue": 2})
        # A copy of the event arriving after the STATE (reordered) is not newer: no double count.
        self.captured(4, 2, 2, 22_000)
        self.assertEqual(self.fc.nodes[4].changes, [])
        self.assertEqual(self.fc.projected_scores(), {"red": 4, "blue": 2})

    def test_two_captures_and_a_neutralization_between_states(self):
        self.state(4, 0, 1, {}, 0)
        self.fc.tick(50_000)
        self.captured(4, 1, 2, 12_000)
        self.captured(4, 2, 1, 31_000)
        self.captured(4, 3, 0, 41_000, type_="zone.neutralized")
        # red holds 0-12 s (the tick at 10 s), blue 12-31 s (20 s, 30 s), red 31-41 s (40 s),
        # nobody after 41 s.
        self.assertEqual(self.fc.projected_scores(), {"red": 2 + 2, "blue": 4})

    def test_a_capture_during_a_pause(self):
        self.state(4, 0, 1, {}, 0)
        self.fc.tick(14_000)
        self.fc.pause_game(now_ms=14_000)
        self.captured(4, 1, 2, 13_000)  # sent before the pause, heard during it
        self.assertEqual(self.fc.projected_scores(), {"red": 0, "blue": 0})  # nothing while paused
        self.fc.tick(40_000)  # the game clock does not move
        self.assertEqual(self.fc.projected_scores(), {"red": 0, "blue": 0})
        self.fc.resume_game(now_ms=40_000)
        self.fc.tick(56_000)  # game time 30 s
        # Red had the tick at 10 s; blue holds from 13 s: the ticks at 20 s and 30 s.
        self.assertEqual(self.fc.game_time_ms, 30_000)
        self.assertEqual(self.fc.projected_scores(), {"red": 2, "blue": 4})

    def test_events_that_say_nothing_new_are_ignored(self):
        self.captured(4, 1, 2, 5_000)  # the box never reported: nothing to follow
        self.assertEqual(self.fc.nodes[4].changes, [])
        self.state(4, 0, 1, {}, 8_000)
        self.fc.tick(12_000)
        self.captured(4, 2, 2, 8_000)  # not after the STATE it should follow
        self.captured(4, 3, 9, 11_000)  # a team the game does not have
        self.assertEqual(self.fc.nodes[4].changes, [])
        self.captured(4, 4, 2, 99_000)  # dated in the controller's future: counts from now
        self.assertEqual(self.fc.nodes[4].changes, [(12_000, 2)])

    def test_nothing_projected_when_paused_offline_unowned_or_not_opted_in(self):
        self.state(4, 0, 1, {}, 0)
        self.state(5, 0, 0, {}, 0)  # nobody holds box 5
        self.fc.tick(15_000)
        self.assertEqual(self.fc.projected_scores(), {"red": 2, "blue": 0})
        self.fc.nodes[4].link = "offline"
        self.assertEqual(self.fc.projected_scores(), {"red": 0, "blue": 0})
        self.fc.nodes[4].link = "online"
        self.fc.pause_game(now_ms=15_000)
        self.assertEqual(self.fc.projected_scores(), {"red": 0, "blue": 0})
        self.fc.resume_game(now_ms=15_000)
        self.fc.scoring_hold = None
        self.assertIsNone(self.fc.projected_scores())

    def test_a_box_that_never_reported_is_not_projected(self):
        self.fc.register_node(4, "node-4", "zone")
        self.fc.nodes[4].owner_team = 1
        self.fc.tick(30_000)
        self.assertEqual(self.fc.projected_scores(), {"red": 0, "blue": 0})
        self.assertEqual(self.fc.game_state, GAME_RUNNING)


if __name__ == "__main__":
    unittest.main()
