# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the FieldController sends and how it handles what it hears.

    cd simulator && python -m unittest discover -s tests

- ACKs: highest contiguous seq per (node, epoch) plus the selective bitmap;
- EVENTs: decoded, team ids named, flood copies and replays logged once,
  a rebooted box's restarted seq not mistaken for a replay;
- CMD opcodes and parameters as ADR-P2-3 and the C codec define them;
- every message the controller sends is accepted by the C decoders of the
  core (the code the boxes run), called through ctypes.
"""

from __future__ import annotations

import ctypes
import json
import os
import random
import unittest

from atalaia_sim import codec
from atalaia_sim.core import Core, find_library
from atalaia_sim.field_controller import (
    CMD_END,
    CMD_PAUSE,
    CMD_RESUME,
    CMD_START,
    AckTracker,
    FieldController,
)
from atalaia_sim.packet import (
    Header,
    ack_decode,
    claim_encode,
    cmd_decode,
    time_decode,
    vf_make,
)
from atalaia_sim.protocol import MESSAGE_TYPES, PAYLOAD_FIELDS
from atalaia_sim.radio_model import RadioConfig, RadioModel


def _has_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESCCM  # noqa: F401
        return True
    except ImportError:
        return False


def _core():
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        return None


CORE = _core()
if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and (CORE is None or not _has_crypto()):
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but the core library or cryptography is missing")


class Recorder:
    """A transport that keeps every packet the controller sends."""

    def __init__(self) -> None:
        self.seq = 0
        self.sent: list[tuple[int, bytes, int, bool]] = []

    def send(self, msg_type, payload, *, priority, ack_req, hop_limit, now_ms):
        self.seq += 1
        self.sent.append((msg_type, payload, priority, ack_req))
        return self.seq

    def of(self, name: str) -> list[bytes]:
        return [p for t, p, _, _ in self.sent if t == MESSAGE_TYPES[name]]


def header(source: int, seq: int, msg_type: str, ack: bool = False) -> Header:
    return Header(version_flags=vf_make(1, 1, ack, True), game_id=1, source=source, seq=seq,
                  hop_limit=2, type=MESSAGE_TYPES[msg_type])


def event_payload(node: int, seq: int, t: int, type_: str, team: int = 0, **data) -> bytes:
    return codec.encode_event({"node": node, "seq": seq, "t": t, "type": type_, "team": team,
                               "data": data})


class AckTrackerTests(unittest.TestCase):
    def test_contiguous_and_bitmap(self):
        a = AckTracker()
        for seq in (0, 1, 2, 4, 6):
            a.record(7, 1, seq)
        msg = a.ack_payload(7, 1)
        self.assertEqual(msg["ack_node"], 7)
        self.assertEqual(msg["ack_seq"], 2)
        # seq 4 -> bit 1, seq 6 -> bit 3.
        self.assertEqual(msg["ack_bitmap"], bytes([0b1010]))
        a.record(7, 1, 3)
        self.assertEqual(a.ack_payload(7, 1)["ack_seq"], 4)

    def test_nothing_contiguous_yet(self):
        a = AckTracker()
        a.record(3, 0, 1)
        msg = a.ack_payload(3, 0)
        self.assertEqual(msg["ack_seq"], 0xFFFF)  # seq 0 is missing
        self.assertEqual(msg["ack_bitmap"], bytes([0b10]))

    def test_epochs_are_separate(self):
        a = AckTracker()
        for seq in range(10):
            a.record(3, 1, seq)
        a.record(3, 2, 0)  # the box rebooted: new epoch, seq from 0
        self.assertEqual(a.ack_payload(3, 1)["ack_seq"], 9)
        self.assertEqual(a.ack_payload(3, 2)["ack_seq"], 0)
        self.assertEqual(a.latest_epoch(3), 2)

    def test_bitmap_covers_the_newest_seq_after_a_jump(self):
        # A jump to 300 used to leave it outside the 256-bit bitmap; now the
        # base moves to 171 (SL-8) and seq 300 is bit 128 of the bitmap.
        a = AckTracker()
        a.record(1, 0, 300)
        msg = a.ack_payload(1, 0)
        self.assertEqual(msg["ack_seq"], 171)
        self.assertEqual(msg["ack_bitmap"], bytes(16) + b"\x01")

    def test_a_packet_lost_for_good_does_not_stall_the_acks(self):
        # SL-8: seq 6 never arrives; 256 packets later the box's newest seq
        # used to fall outside the bitmap and no ACK could name it again.
        a = AckTracker()
        for seq in range(6):
            a.record(7, 1, seq)
        for seq in range(7, 1200):
            a.record(7, 1, seq)
            msg = a.ack_payload(7, 1)
            self.assertGreaterEqual(msg["ack_seq"], seq - AckTracker.GAP_WINDOW - 1)
            # The newest seq is named: in the base or in the bitmap.
            if msg["ack_seq"] < seq:
                n = seq - msg["ack_seq"] - 1
                self.assertTrue(msg["ack_bitmap"][n // 8] >> (n % 8) & 1)
        self.assertEqual(a.ack_payload(7, 1), {"ack_node": 7, "ack_seq": 1199})

    def test_the_tracker_forgets_what_it_gave_up_on(self):
        a = AckTracker()
        a.record(7, 1, 0)
        for seq in range(2, 2000):
            a.record(7, 1, seq)
        self.assertLessEqual(len(a._above[(7, 1)]), AckTracker.GAP_WINDOW + 1)

    def test_shared_vectors(self):
        # protocol/vectors/ack_tracker.json: the phone's tracker passes the
        # same cases byte for byte.
        path = os.path.join(os.path.dirname(__file__), "..", "..", "protocol", "vectors",
                            "ack_tracker.json")
        with open(path) as f:
            vectors = json.load(f)
        self.assertEqual(vectors["window"], AckTracker.GAP_WINDOW)
        for case in vectors["cases"]:
            with self.subTest(case["name"]):
                a = AckTracker()
                for first, last in case["received"]:
                    for seq in range(first, last + 1):
                        a.record(5, 2, seq)
                msg = a.ack_payload(5, 2)
                self.assertEqual(msg["ack_seq"], case["ack_seq"])
                bitmap = case["ack_bitmap"]
                self.assertEqual(msg.get("ack_bitmap"),
                                 None if bitmap is None else bytes.fromhex(bitmap))


class EventHandlingTests(unittest.TestCase):
    def setUp(self):
        self.tx = Recorder()
        self.ctrl = FieldController(transport=self.tx, teams=["red", "blue"], node_id=0,
                                    wall_clock=lambda: 1_700_000_000.0)
        self.events: list[dict] = []
        self.ctrl.on_event = self.events.append

    def test_event_is_decoded_named_and_acked(self):
        payload = event_payload(4, 1, 5000, "zone.captured", team=2, zone="alpha")
        self.ctrl.on_packet(4, header(4, 0, "EVENT", ack=True), payload, {"epoch": 3, "rssi": -70})
        self.assertEqual(len(self.events), 1)
        ev = self.events[0]
        self.assertEqual((ev["node"], ev["seq"], ev["t"], ev["type"]), (4, 1, 5000, "zone.captured"))
        self.assertEqual(ev["team"], "blue")
        self.assertEqual(ev["data"], {"zone": "alpha"})
        self.assertEqual(ev["epoch"], 3)
        self.assertEqual(self.ctrl.nodes[4].rssi, -70)
        [ack] = self.tx.of("ACK")
        self.assertEqual(ack_decode(ack), {"ack_node": 4, "ack_seq": 0})

    def test_flood_copy_and_replay_logged_once(self):
        payload = event_payload(4, 1, 5000, "zone.captured", team=1)
        self.ctrl.on_packet(4, header(4, 0, "EVENT"), payload, {"epoch": 1})
        self.ctrl.on_packet(4, header(4, 0, "EVENT"), payload, {"epoch": 1})  # relayed copy
        self.ctrl.on_packet(4, header(4, 9, "EVENT"), payload, {"epoch": 1})  # replay, new packet
        self.assertEqual(len(self.events), 1)

    def test_reboot_restarts_seqs_without_losing_events(self):
        # Before the reboot: event seq 1 at t=5000 in packet seq 0, epoch 1.
        self.ctrl.on_packet(4, header(4, 0, "EVENT"),
                            event_payload(4, 1, 5000, "zone.captured", team=1), {"epoch": 1})
        # After it: event seq 1 again, but later in the game, packet seq 0 in epoch 2.
        self.ctrl.on_packet(4, header(4, 0, "EVENT"),
                            event_payload(4, 1, 65_000, "zone.captured", team=2), {"epoch": 2})
        self.assertEqual([e["t"] for e in self.events], [5000, 65_000])

    def test_no_ack_on_standby(self):
        from atalaia_sim.election import Election
        e = Election(9, priority=1)
        e.follow(0)
        standby = FieldController(transport=self.tx, teams=["red"], node_id=9, election=e)
        standby.on_packet(4, header(4, 0, "EVENT", ack=True),
                          event_payload(4, 1, 10, "zone.captured", team=1), {"epoch": 0})
        self.assertEqual(self.tx.of("ACK"), [])
        self.assertEqual(len(standby.event_log), 1)

    def test_undecodable_event_is_kept_as_an_error(self):
        self.ctrl.on_packet(4, header(4, 0, "EVENT"), b"\xff\x00", {"epoch": 0})
        self.assertEqual(self.events, [])
        self.assertIn("error", self.ctrl.event_log[-1])

    def test_state_counters_by_team_id(self):
        from atalaia_sim.packet import state_encode
        scores = []
        self.ctrl.on_scores = scores.append
        self.ctrl.on_packet(5, header(5, 0, "STATE"),
                            state_encode({"owner_team": 2, "phase": 1, "game_time_ms": 900,
                                          "counters": {1: 3, 2: 8}, "epoch": 0, "battery_pct": 77}))
        self.assertEqual(self.ctrl.total_scores, {"red": 3, "blue": 8})
        self.assertEqual(self.ctrl.nodes[5].owner_name(self.ctrl.teams), "blue")
        self.assertEqual(self.ctrl.nodes[5].battery_pct, 77)
        self.assertEqual(scores[-1], {"red": 3, "blue": 8})

    def test_state_lost_is_subtracted_and_merged_by_maximum(self):
        """RFC 0001 Amendment 18: key 9 is the box's penalties; an older STATE without it loses none."""
        from atalaia_sim.packet import state_encode
        scores = []
        self.ctrl.on_scores = scores.append
        base = {"owner_team": 2, "phase": 1, "game_time_ms": 900, "counters": {1: 10, 2: 8}, "epoch": 0}
        self.ctrl.on_packet(5, header(5, 0, "STATE"), state_encode(base))
        self.assertEqual(self.ctrl.total_scores, {"red": 10, "blue": 8})
        self.ctrl.on_packet(5, header(5, 1, "STATE"), state_encode({**base, "lost": {2: 3}}))
        self.assertEqual(self.ctrl.total_scores, {"red": 10, "blue": 5})
        self.assertEqual(scores[-1], {"red": 10, "blue": 5})
        # A later STATE that says less (or nothing) changes nothing: merged by maximum.
        self.ctrl.on_packet(5, header(5, 2, "STATE"), state_encode({**base, "lost": {2: 1}}))
        self.ctrl.on_packet(5, header(5, 3, "STATE"), state_encode(base))
        self.assertEqual(self.ctrl.total_scores, {"red": 10, "blue": 5})
        # Another box's penalties add, and the GM's adjustment still applies on top.
        self.ctrl.on_packet(6, header(6, 0, "STATE"), state_encode({**base, "counters": {2: 4}, "lost": {2: 2}}))
        self.ctrl.adjust_score("blue", -1)
        self.assertEqual(self.ctrl.total_scores, {"red": 10, "blue": 5 + 4 - 2 - 1})

    def test_manual_adjustment_is_a_score_delta_event(self):
        rec = self.ctrl.adjust_score("red", -2, "penalty")
        self.assertEqual(rec["type"], "score.delta")
        self.assertEqual(rec["data"], {"team": "red", "amount": -2, "reason": "penalty"})
        self.assertEqual(self.ctrl.total_scores["red"], -2)
        self.assertEqual(self.events, [rec])


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tx = Recorder()
        self.ctrl = FieldController(transport=self.tx, teams=["red", "blue"], node_id=0)

    def test_lifecycle_opcodes(self):
        self.ctrl.start_game(duration_ms=60_000, now_ms=0)
        self.ctrl.pause_game(now_ms=1000, reason="injury")
        self.ctrl.resume_game(now_ms=2000)
        self.ctrl.end_game(now_ms=3000)
        cmds = [cmd_decode(p) for p in self.tx.of("CMD")]
        self.assertEqual([c["cmd"] for c in cmds], [CMD_START, CMD_PAUSE, CMD_RESUME, CMD_END])
        self.assertEqual(cmds[1]["params"], {"reason": "injury"})
        self.assertTrue(all("dest" not in c for c in cmds))
        self.assertEqual(self.ctrl.game_time_ms, 2000)  # paused for 1 s

    def test_unicast_and_limits(self):
        self.ctrl.send_cmd("set_owner", {"team": "red"}, dest=12)
        cmd = cmd_decode(self.tx.of("CMD")[-1])
        self.assertEqual((cmd["cmd"], cmd["dest"]), (4, 12))
        with self.assertRaises(ValueError):
            self.ctrl.send_cmd("message", {"text": "x" * 200})
        with self.assertRaises(ValueError):
            self.ctrl.send_cmd("explode")

    def test_time_beacon_fields(self):
        self.ctrl.start_game(duration_ms=60_000, now_ms=0)
        self.ctrl.tick(31_000)
        beacon = time_decode(self.tx.of("TIME")[-1])
        self.assertEqual(beacon["game_state"], 1)
        self.assertEqual(beacon["term"], 1)
        self.assertEqual(beacon["duration_ms"], 60_000)
        self.assertEqual(beacon["game_time_ms"], 31_000)
        self.assertIn("wall_s", beacon)


@unittest.skipIf(CORE is None, "the shared core library is not built")
class CDecoderAcceptsControllerMessages(unittest.TestCase):
    """The payloads the controller sends decode with the boxes' C code."""

    class TimeMsg(ctypes.Structure):
        _fields_ = [("game_time_ms", ctypes.c_uint32), ("game_state", ctypes.c_uint8),
                    ("duration_ms", ctypes.c_uint32), ("wall_s", ctypes.c_uint32),
                    ("term", ctypes.c_uint32), ("tx_time_us", ctypes.c_uint16)]

    class CmdMsg(ctypes.Structure):
        _fields_ = [("cmd", ctypes.c_uint8), ("params_json", ctypes.c_char * 128),
                    ("dest", ctypes.c_uint16)]

    class AckMsg(ctypes.Structure):
        _fields_ = [("ack_node", ctypes.c_uint16), ("ack_seq", ctypes.c_uint16),
                    ("ack_bitmap", ctypes.c_uint8 * 32), ("ack_bitmap_len", ctypes.c_size_t)]

    class LastAck(ctypes.Structure):
        _fields_ = [("node", ctypes.c_uint16), ("seq", ctypes.c_uint16)]

    class ClaimMsg(ctypes.Structure):
        _fields_ = [("term", ctypes.c_uint32), ("priority", ctypes.c_uint16),
                    ("node_id", ctypes.c_uint16), ("last_ack", ctypes.c_uint8 * (4 * 32)),
                    ("last_ack_count", ctypes.c_uint8)]

    def decode(self, name: str, struct_type, payload: bytes):
        fn = getattr(CORE.lib, name)
        fn.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p]
        fn.restype = ctypes.c_bool
        out = struct_type()
        self.assertTrue(fn(payload, len(payload), ctypes.byref(out)), f"{name} rejected {payload.hex()}")
        return out

    def test_every_controller_message(self):
        tx = Recorder()
        ctrl = FieldController(transport=tx, teams=["red", "blue"], node_id=0,
                               wall_clock=lambda: 1_700_000_000.0)
        ctrl.start_game(duration_ms=90_000, now_ms=0)
        ctrl.pause_game(now_ms=500, reason="medic")
        ctrl.send_cmd("message", {"text": "10 minutes left", "audience": "all"}, dest=3)
        for seq in (0, 1, 2, 5):
            ctrl.on_packet(3, header(3, seq, "EVENT", ack=True),
                           event_payload(3, seq + 1, 100 * seq, "zone.captured", team=1), {"epoch": 2})

        t = self.decode("atalaia_time_decode", self.TimeMsg, tx.of("TIME")[-1])
        self.assertEqual((t.game_state, t.duration_ms, t.term, t.wall_s), (2, 90_000, 1, 1_700_000_000))
        self.assertEqual(t.tx_time_us, 0xFFFF)

        c = self.decode("atalaia_cmd_decode", self.CmdMsg, tx.of("CMD")[-1])
        self.assertEqual((c.cmd, c.dest), (5, 3))
        self.assertEqual(json.loads(c.params_json.decode()), {"text": "10 minutes left", "audience": "all"})
        pause = self.decode("atalaia_cmd_decode", self.CmdMsg, tx.of("CMD")[1])
        self.assertEqual((pause.cmd, pause.dest), (1, 0xFFFF))

        a = self.decode("atalaia_ack_msg_decode", self.AckMsg, tx.of("ACK")[-1])
        self.assertEqual((a.ack_node, a.ack_seq), (3, 2))
        self.assertEqual((a.ack_bitmap_len, a.ack_bitmap[0]), (1, 0b100))  # seq 5

    def test_claim(self):
        payload = claim_encode({"term": 4, "priority": 16_000, "node_id": 9, "last_ack_seq": {3: 12}})
        m = self.decode("atalaia_claim_decode", self.ClaimMsg, payload)
        self.assertEqual((m.term, m.priority, m.node_id, m.last_ack_count), (4, 16_000, 9, 1))

    def test_required_fields_present(self):
        tx = Recorder()
        ctrl = FieldController(transport=tx, teams=["red"], node_id=0)
        ctrl.start_game(now_ms=0)
        from atalaia_sim.packet import PAYLOAD_DECODERS
        for name in ("TIME", "CMD"):
            for payload in tx.of(name):
                decoded = PAYLOAD_DECODERS[name](payload)
                required = {k for k, f in PAYLOAD_FIELDS[name].items() if f.required}
                self.assertLessEqual(required, set(decoded), name)


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class OverTheRadioTests(unittest.TestCase):
    def test_box_gets_an_ack_for_its_event(self):
        radio = RadioModel(config=RadioConfig(loss_rate=0.0), rng=random.Random(3))
        ctrl = FieldController(radio=radio, teams=["red", "blue"])
        radio.add_node(4)
        radio.send(from_node=4, payload=event_payload(4, 1, 100, "bomb.armed", team=1, fuse_s=30.0),
                   msg_type=MESSAGE_TYPES["EVENT"], source=4, seq=0, priority=2, ack_req=True, now_ms=0)
        ctrl.tick(100)
        acks = [p for dest, hdr, p in ctrl.tick(300)
                if dest == 4 and hdr.type == MESSAGE_TYPES["ACK"]]
        self.assertEqual(len(acks), 1)
        self.assertEqual(ack_decode(acks[0]), {"ack_node": 4, "ack_seq": 0})
        [entry] = [e for e in ctrl.event_log if e["type"] == "event"]
        self.assertEqual(entry["event"]["type"], "bomb.armed")
        self.assertEqual(entry["event"]["data"], {"fuse_s": 30.0})


if __name__ == "__main__":
    unittest.main()
