# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Re-inviting boxes in the radio model (atalaia_sim.lobby, protocol/field-frames.md).

A box ends one game, announces itself on the field's radio, and a field
controller invites it into the next game with an INVITE sealed with the key
derived from the field join key: the box joins (its HELLO reaches the game's
FieldController). A box in a game answers "busy"; an invite played again is
refused (the token changed); another field's controller is not heard; the
announcements stay within their share of the duty cycle.

    cd simulator && python -m unittest tests.test_reinvite_sim
"""

from __future__ import annotations

import os
import random
import unittest

from atalaia_sim import eu868
from atalaia_sim import field_frame as ff
from atalaia_sim import join as joinfmt
from atalaia_sim import lobby
from atalaia_sim.field_controller import FieldController
from atalaia_sim.packet import hello_encode
from atalaia_sim.protocol import MESSAGE_TYPES
from atalaia_sim.radio_model import RadioConfig, RadioModel


def _has_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESCCM  # noqa: F401
        return True
    except ImportError:
        return False


if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and not _has_crypto():
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but cryptography is not available")

JOIN_KEY = bytes(range(32))
OTHER_FIELD = bytes(range(100, 132))
CTRL = 0      # the controller's node id and radio node
BOX_AIR = 900  # the box's radio node (its node id changes with every game)
STRANGER = 901


def join_payload(game_id: int, key: bytes, node_id: int, role: str = "zone", params=None,
                 mode: str = "org.atalaia.domination", **extra) -> bytes:
    return joinfmt.encode({"game_id": game_id, "game_key": key, "node_id": node_id, "controller_id": CTRL,
                           "channel_hz": eu868.DEFAULT_CHANNEL_HZ, "max_hops": 2, "teams": ["red", "blue"],
                           "mode_id": mode, "role": role, "game_seed": 7, "params": params, "kind": "node",
                           **extra}, JOIN_KEY)


LINK = {"ca_sha256": bytes(range(32)), "urls": ["https://10.42.0.1:8443"]}


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class ReinviteSimTests(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(5)
        self.key1, self.key2 = bytes([1] * 16), bytes([2] * 16)
        self.radio = RadioModel(RadioConfig(loss_rate=0.0, game_id=1, game_key=self.key1), rng=random.Random(9))
        for n in (CTRL, BOX_AIR, STRANGER):
            self.radio.add_node(n)
        self.now = 0
        self.sent: list[bytes] = []
        self.inviter = lobby.Inviter(JOIN_KEY, self._ctrl_send, rng=random.Random(3))
        self.box = lobby.IdleBox(JOIN_KEY, "Zona Norte", rng=random.Random(11), now_ms=0)
        self.fc = FieldController(radio=self.radio, game_id=1, teams=["red", "blue"], beacon_interval_ms=30_000)
        self.hello_seq = 0

    def _ctrl_send(self, frame: bytes):
        self.sent.append(frame)
        return len(self.sent) if self.radio.send_raw(CTRL, frame, self.now) else None

    def run_for(self, ms: int, step: int = 50) -> None:
        end = self.now + ms
        while self.now < end:
            self.now += step
            for frame in self.box.tick(self.now):
                self.radio.send_raw(BOX_AIR, frame, self.now)
            self.inviter.tick(self.now)
            deliveries = self.radio.tick(self.now)
            self.fc.tick(self.now, deliveries)
            for frame in self.radio.take_raw(CTRL):
                self.inviter.on_frame(frame, self.now, rssi=-70)
            for frame in self.radio.take_raw(BOX_AIR):
                self.box.on_frame(frame, self.now)
            self.radio.take_raw(STRANGER)
            if self.box.phase == "joined" and self.box.game and self.hello_seq == 0:
                self._hello()

    def _hello(self) -> None:
        """The box's HELLO in its new game (under the game key, from its node id)."""
        g = self.box.game
        self.radio.config.game_id, self.radio.config.game_key = g["game_id"], g["game_key"]
        payload = hello_encode({"node_name": self.box.name, "platform": 1, "fw_version": "0.4.0",
                                "core_version": "0.2.0", "tier": 0, "capabilities": [0], "transports": 1,
                                "epoch": 1, "device_id": self.box.device_id})
        self.radio.send(BOX_AIR, payload, MESSAGE_TYPES["HELLO"], g["node_id"], self.hello_seq, ack_req=True,
                        now_ms=self.now)
        self.hello_seq += 1

    def play_first_game(self) -> None:
        self.assertEqual(self.box.join(join_payload(1, self.key1, 4)), "accepted")
        self.box.start()
        self.run_for(1_000)
        self.box.end(self.now)
        self.hello_seq = 0

    def test_a_box_leaves_one_game_and_is_invited_into_the_next(self):
        self.play_first_game()
        self.assertTrue(self.box.available)
        self.run_for(21_000)  # its first announcement comes 2-20 s after the end
        seen = self.inviter.available(self.now)
        self.assertEqual([b.name for b in seen], ["Zona Norte"])
        self.assertEqual((seen[0].last_game, seen[0].last_role), (1, "zone"))
        self.assertEqual(seen[0].rssi, -70)

        # The next game: a new FieldController with game 2's key, and the invite.
        self.fc = FieldController(radio=self.radio, game_id=2, teams=["red", "blue"], beacon_interval_ms=30_000)
        token_before = self.box.token
        inv = self.inviter.invite(self.box.device_id, join_payload(2, self.key2, 9), game_id=2, node_id=9,
                                  role="zone", now_ms=self.now)
        self.run_for(3_000)
        self.assertEqual(inv.status, "accepted")
        self.assertEqual(self.box.game["game_id"], 2)
        self.assertEqual(self.box.game["node_id"], 9)
        self.assertNotEqual(self.box.token, token_before)
        self.assertIn("invited to game 2 as zone", self.box.log)
        # Its HELLO arrives in game 2, with its device id: the invite is done.
        node = self.fc.nodes.get(9)
        self.assertIsNotNone(node)
        self.assertEqual(node.hello.get("device_id"), self.box.device_id)
        self.assertIs(self.inviter.on_hello(9, node.hello["device_id"]), inv)
        self.assertEqual(inv.status, "joined")

    def test_an_invite_played_again_is_refused(self):
        self.play_first_game()
        self.run_for(21_000)
        self.inviter.invite(self.box.device_id, join_payload(2, self.key2, 9), game_id=2, node_id=9,
                            role="zone", now_ms=self.now)
        self.run_for(3_000)
        recorded = list(self.sent)
        self.assertEqual(self.box.game["game_id"], 2)
        self.box.end(self.now)  # game 2 is over: the box is free again
        for frame in recorded:  # someone plays the recorded invite back
            self.box.on_frame(frame, self.now)
        self.assertEqual(self.box.phase, "ended")
        self.assertIn(f"invite {self.inviter.invites[self.box.device_id.hex()].invite_id} refused: an old token",
                      self.box.log)

    def test_game_over_frees_a_box_whose_controller_lost_the_key(self):
        """Decision OT-13: a controller that restarted without the game's key still has the field
        key; its GAME_OVER (the game id and the key's tag, three times, a few seconds apart) ends the
        box's game, and the box announces itself again. Another game's, or the same id under
        another key (an old one played back), changes nothing."""
        self.assertEqual(self.box.join(join_payload(1, self.key1, 4)), "accepted")
        self.box.start()
        self.run_for(1_000)
        self.inviter.game_over(1, ff.key_tag(self.key2), self.now)  # the id, but another game's key
        self.inviter.game_over(7, ff.key_tag(self.key1), self.now)  # another game
        self.run_for(13_000)
        self.assertEqual(self.box.phase, "playing")
        tunes: list = []
        self.inviter.tune = lambda ch: tunes.append(ch) or True
        start = len(self.sent)
        go = self.inviter.game_over(1, ff.key_tag(self.key1), self.now, channel_hz=eu868.DEFAULT_CHANNEL_HZ)
        self.run_for(500)
        self.assertEqual(self.box.phase, "ended")
        self.assertIn("game 1 is over (said by a field controller)", self.box.log)
        self.run_for(12_000)
        # Bounded: three frames, about 4 s apart; then the radio goes back.
        self.assertEqual((go.sent, len(self.sent) - start), (lobby.GAME_OVER_REPEATS, 3))
        self.assertEqual(tunes[-1], None)
        self.assertEqual(self.inviter.games_over, [])
        self.run_for(21_000)
        self.assertEqual([(b.name, b.last_game) for b in self.inviter.available(self.now)], [("Zona Norte", 1)])

    def test_the_same_game_again_is_refused(self):
        """A box that played a game to its end does not join it again, even with a valid token."""
        self.play_first_game()
        self.run_for(21_000)
        inv = self.inviter.invite(self.box.device_id, join_payload(1, self.key1, 4), game_id=1, node_id=4,
                                  role="zone", now_ms=self.now)
        self.run_for(3_000)
        self.assertEqual((inv.status, inv.detail), ("refused", "ended"))
        self.assertEqual(self.box.phase, "ended")

    def test_a_card_join_drops_the_tokens(self):
        """Joined by a card meanwhile: the token the controller heard before no longer works,
        so its invite gets no answer and the game goes on (review 2026-10-21, finding 2)."""
        self.play_first_game()
        self.run_for(21_000)
        self.box.join(join_payload(3, bytes([3] * 16), 5))
        self.box.start()
        inv = self.inviter.invite(self.box.device_id, join_payload(2, self.key2, 9), game_id=2, node_id=9,
                                  role="zone", now_ms=self.now)
        self.run_for(3_000)
        self.assertEqual(inv.status, "invited")  # silence: an old token
        self.assertEqual(self.box.game["game_id"], 3)

    def test_a_box_in_a_game_answers_busy_and_that_invite_never_works_later(self):
        self.play_first_game()
        self.run_for(21_000)
        self.box.join(join_payload(3, bytes([3] * 16), 5))
        self.box.start()
        # A controller that knows the box's current token (it heard it after the card join).
        self.inviter.boxes[self.box.device_id.hex()].token = self.box.token
        self.sent.clear()
        inv = self.inviter.invite(self.box.device_id, join_payload(2, self.key2, 9), game_id=2, node_id=9,
                                  role="zone", now_ms=self.now)
        self.run_for(3_000)
        self.assertEqual((inv.status, inv.detail), ("refused", "busy"))
        recorded = list(self.sent)
        # Game 3 ends; someone plays the busy invite back: the token went with the answer.
        self.box.end(self.now)
        for frame in recorded:
            self.box.on_frame(frame, self.now)
        self.assertEqual(self.box.phase, "ended")
        self.assertTrue(any("an old token" in line for line in self.box.log))

    def test_a_refused_invite_never_works_later(self):
        """An invite answered with a refusal (the mode is not on the box) drops the tokens too."""
        self.play_first_game()
        self.run_for(21_000)
        self.box.installed = {"org.atalaia.bomb"}
        self.sent.clear()
        inv = self.inviter.invite(self.box.device_id, join_payload(2, self.key2, 9), game_id=2, node_id=9,
                                  role="zone", now_ms=self.now)
        self.run_for(3_000)
        self.assertEqual((inv.status, inv.detail), ("refused", "no_mode"))
        recorded = list(self.sent)
        self.box.installed = None  # the mode is installed now: the old invite still fails
        for frame in recorded:
            self.box.on_frame(frame, self.now)
        self.assertEqual(self.box.phase, "ended")

    def test_a_box_lacking_a_mode_fetches_it_with_key_16(self):
        """Phase 5 plan phase 13 (protocol/mode-packages.md): the same box, invited again with
        fetch_modes (key 16) and the controller's link (keys 13, 14), accepts the join fetching
        the parts it lacks; without the link it still answers no_mode. Key 17 forgets the fetched
        ones first, so the next game's join makes it fetch again."""
        self.play_first_game()
        self.run_for(21_000)
        self.box.installed = {"org.atalaia.domination"}
        mode = "org.atalaia.domination+org.club.codes"
        inv = self.inviter.invite(self.box.device_id, join_payload(2, self.key2, 9, mode=mode, fetch_modes=True),
                                  game_id=2, node_id=9, role="zone", now_ms=self.now)
        self.run_for(3_000)
        self.assertEqual((inv.status, inv.detail), ("refused", "no_mode"))  # key 16 without 13 and 14
        self.run_for(70_000)  # its next announcement, with a new token
        inv = self.inviter.invite(self.box.device_id,
                                  join_payload(2, self.key2, 9, mode=mode, fetch_modes=True, **LINK),
                                  game_id=2, node_id=9, role="zone", now_ms=self.now)
        self.run_for(3_000)
        self.assertEqual(inv.status, "accepted")
        self.assertEqual((self.box.phase, self.box.fetching), ("joined", ["org.club.codes"]))
        self.box.fetched_part("org.club.codes", "1.0.0")
        self.assertEqual(self.box.fetching, [])
        self.box.start()
        self.box.end(self.now)
        self.run_for(70_000)
        # Key 17: the fetched part goes, so a join that needs it fetches again; without key 16: no_mode.
        inv = self.inviter.invite(self.box.device_id, join_payload(3, bytes([3] * 16), 4, mode=mode,
                                                                   forget_modes=True),
                                  game_id=3, node_id=4, role="zone", now_ms=self.now)
        self.run_for(3_000)
        self.assertEqual((inv.status, inv.detail), ("refused", "no_mode"))
        self.assertEqual((self.box.fetched, self.box.installed), ({}, {"org.atalaia.domination"}))

    def test_a_failed_fetch_leaves_the_box_free(self):
        """A box whose fetch failed leaves the join, announces itself again and can be invited
        once more into the same game."""
        self.play_first_game()
        self.run_for(21_000)
        self.box.installed = {"org.atalaia.domination"}
        mode = "org.atalaia.domination+org.club.codes"
        payload = join_payload(2, self.key2, 9, mode=mode, fetch_modes=True, **LINK)
        inv = self.inviter.invite(self.box.device_id, payload, game_id=2, node_id=9, role="zone", now_ms=self.now)
        self.run_for(3_000)
        self.assertEqual(inv.status, "accepted")
        self.box.fetch_failed(self.now)
        self.assertTrue(self.box.available)
        self.assertNotIn(2, self.box.ended)
        self.run_for(21_000)
        inv = self.inviter.invite(self.box.device_id, payload, game_id=2, node_id=9, role="zone", now_ms=self.now)
        self.run_for(3_000)
        self.assertEqual(inv.status, "accepted")

    def test_alternating_replays_get_few_answers(self):
        """Two recorded invites played back in turn: one answer each in 10 s, and at most
        ANSWERS_PER_MIN answers a minute in all (review finding 3)."""
        self.play_first_game()
        self.run_for(21_000)
        frames = {}
        for invite_id in (101, 102):
            frames[invite_id] = ff.invite_frames(ff.field_key(JOIN_KEY), ff.NonceSource(JOIN_KEY, bytes(8)),
                                                 self.box.device_id, self.box.token, invite_id,
                                                 join_payload(1, self.key1, 4))  # an ended game
        answers = 0
        token = self.box.token
        for i in range(40):
            self.box.token = token  # as if the token had not moved: the worst case
            for f in frames[101 if i % 2 else 102]:
                self.box.on_frame(f, self.now)
            answers += len(self.box.tick(self.now + 1_000))
            self.now += 2_000
        self.assertLessEqual(answers, lobby.ANSWERS_PER_MIN * 2 + 2)

    def test_a_replayed_announcement_is_refused(self):
        """The controller keeps the highest (boot, count) per box: an old announcement played
        back does not bring a stale token or a box in a game back (review finding 4)."""
        self.play_first_game()
        heard = []
        for _ in range(3):
            self.run_for(80_000)
            heard.append(self.box.token)
        frames = [f for f in self.box.tick(self.now)]  # nothing due right now
        self.assertEqual(frames, [])
        old = ff.encode(self.box.key, {**self.box._announce(), "token": heard[0]},
                        ff.nonce(self.box.nonces.nkey, self.box.device_id, self.box.nonces.boot, 0))
        before = self.inviter.boxes[self.box.device_id.hex()].token
        self.assertIsNone(self.inviter.on_frame(old, self.now))
        self.assertEqual(self.inviter.boxes[self.box.device_id.hex()].token, before)
        self.assertEqual(self.inviter.stale, 1)
        # Not the box's own pseudonym (another sender's nonce with this box's id): refused too.
        forged = ff.encode(self.box.key, self.box._announce(), ff.nonce(self.box.nonces.nkey, bytes(8), 99, 0))
        self.assertIsNone(self.inviter.on_frame(forged, self.now))

    def test_hello_and_forgetting_are_per_game(self):
        """A HELLO matches only the live game's invites; a game's invites go when it ends."""
        self.play_first_game()
        self.run_for(21_000)
        inv = self.inviter.invite(self.box.device_id, join_payload(2, self.key2, 9), game_id=2, node_id=9,
                                  role="zone", now_ms=self.now)
        self.assertIsNone(self.inviter.on_hello(9, None, game_id=5))
        self.inviter.forget_game(2)
        self.assertEqual(self.inviter.invites, {})
        sent = len(self.sent)
        self.inviter.tick(self.now + 60_000)
        self.assertEqual(len(self.sent), sent)  # no retry into a game that is over
        self.assertEqual(inv.status, "sending")

    def test_a_box_playing_a_game_picked_on_it_answers_busy(self):
        self.run_for(21_000)
        self.box.standalone = True
        inv = self.inviter.invite(self.box.device_id, join_payload(2, self.key2, 9), game_id=2, node_id=9,
                                  role="zone", now_ms=self.now)
        self.run_for(3_000)
        self.assertEqual((inv.status, inv.detail), ("refused", "busy"))

    def test_another_fields_controller_is_not_heard(self):
        self.play_first_game()
        stranger = lobby.Inviter(OTHER_FIELD, lambda f: 1 if self.radio.send_raw(STRANGER, f, self.now) else None)
        self.run_for(21_000)
        for frame in self.radio.take_raw(STRANGER):
            stranger.on_frame(frame, self.now)
        self.assertEqual(self.inviter.ignored, 0)
        # It never hears the box (wrong key), so it cannot invite it; a forged invite does nothing.
        self.assertEqual(stranger.available(self.now), [])
        stranger.boxes[self.box.device_id.hex()] = lobby.BoxSeen(self.box.device_id, "x", 0, self.box.token, self.now)
        stranger.invite(self.box.device_id, join_payload(2, self.key2, 9), game_id=2, node_id=9, role="zone",
                        now_ms=self.now)
        stranger.tick(self.now)
        self.run_for(3_000)
        self.assertEqual(self.box.phase, "ended")
        self.assertGreater(self.inviter.ignored, 0)  # the stranger's frames reached our controller too

    def test_a_large_join_in_two_parts_over_a_lossy_radio(self):
        self.radio.config.loss_rate = 0.3
        self.play_first_game()
        self.run_for(80_000)
        self.assertTrue(self.inviter.available(self.now))
        params = {"capture_hold_ms": 5000, "tick_s": 20, "points_per_tick": 3, "note": "x" * 60}
        payload = join_payload(2, self.key2, 9, params=params)
        self.assertEqual(len(ff.split(payload)), 2)
        inv = None
        for _ in range(lobby.INVITE_ATTEMPTS * 3):
            inv = self.inviter.invite(self.box.device_id, payload, game_id=2, node_id=9, role="zone",
                                      now_ms=self.now)
            self.run_for(20_000)
            if inv.status == "accepted" or self.box.phase == "joined":
                break
            self.run_for(80_000)  # wait for a fresh announcement (a new token if it rotated)
        self.assertEqual(self.box.game["game_id"], 2)

    def test_discover_brings_an_answer_within_seconds(self):
        self.play_first_game()
        self.run_for(21_000)
        first = self.box.last_announce
        self.run_for(lobby.announce_interval_ms(eu868.DEFAULT_CHANNEL_HZ, 70) // 4)
        self.inviter.boxes.clear()
        self.assertTrue(self.inviter.discover(self.now))
        self.assertFalse(self.inviter.discover(self.now))  # at most one per 10 s
        self.run_for(3_500)
        self.assertEqual(len(self.inviter.available(self.now)), 1)
        self.assertGreater(self.box.last_announce, first)

    def test_announcements_keep_to_their_share_of_the_duty_cycle(self):
        for channel in (869_525_000, 868_300_000, 868_900_000):
            band = eu868.band_of(channel)
            frame = 80
            interval = lobby.announce_interval_ms(channel, frame)
            per_hour = eu868.HOUR_MS / interval * eu868.airtime_ms(frame)
            self.assertLessEqual(per_hour, lobby.ANNOUNCE_SHARE * band.duty * eu868.HOUR_MS + 1)
            self.assertGreaterEqual(interval, lobby.ANNOUNCE_MIN_MS)
        # On 869.525 MHz (10 %) an 80-byte announcement goes out about every 70 s; on 868.3 MHz (1 %)
        # about every 12 minutes.
        self.assertLess(lobby.announce_interval_ms(869_525_000, 80), 90_000)
        self.assertGreater(lobby.announce_interval_ms(868_300_000, 80), 600_000)
        # An hour of an idle box in the model: within budget.
        self.play_first_game()
        self.run_for(3_600_000, step=500)
        used = self.radio.nodes[BOX_AIR].duty.used(self.now)
        self.assertLess(used, lobby.ANNOUNCE_SHARE * 0.1 * eu868.HOUR_MS * 1.2)


if __name__ == "__main__":
    unittest.main()
