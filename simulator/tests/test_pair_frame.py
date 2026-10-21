# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""CPace and the pair frames against protocol/vectors/pairing.json (also checked by
core/tests/test_pair_frame.c and firmware/esp32/test/test_box_pair.c). Every vector is
checked; none is skipped. The CPace cases are the draft's own (Appendix B.1, B.1.10)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from atalaia_sim import cpace
from atalaia_sim import pair_frame as pf

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "pairing.json")
                     .read_text(encoding="utf-8"))
h = bytes.fromhex


class CpaceDraftTests(unittest.TestCase):
    def test_b1(self) -> None:
        v = VECTORS["cpace_b1"]
        self.assertEqual(cpace.generator_string(h(v["prs"]), h(v["ci"]), h(v["sid"])).hex(), v["generator_string"])
        g = cpace.calculate_generator(h(v["prs"]), h(v["ci"]), h(v["sid"]))
        self.assertEqual(g.hex(), v["g"])
        ya = cpace.scalar_mult(h(v["ya"]), g)
        yb = cpace.scalar_mult(h(v["yb"]), g)
        self.assertEqual((ya.hex(), yb.hex()), (v["Ya"], v["Yb"]))
        k = cpace.scalar_mult_vfy(h(v["ya"]), yb)
        self.assertEqual(k, cpace.scalar_mult_vfy(h(v["yb"]), ya))
        self.assertEqual(k.hex(), v["K"])
        self.assertEqual(cpace.isk_ir(h(v["sid"]), k, ya, h(v["ada"]), yb, h(v["adb"])).hex(), v["isk_ir"])

    def test_low_order_points_abort(self) -> None:
        lo = VECTORS["cpace_low_order"]
        self.assertEqual(len(lo["points"]), 12)
        aborts = 0
        for p in lo["points"]:
            with self.subTest(p["u"]):
                self.assertEqual(cpace.scalar_mult(h(lo["s"]), h(p["u"])).hex(), p["q"])
                if p["q"] == "00" * 32:
                    aborts += 1
                    with self.assertRaises(cpace.CpaceError):
                        cpace.scalar_mult_vfy(h(lo["s"]), h(p["u"]))
        self.assertEqual(aborts, 7)  # u0-u5 and u7, as the draft says


class RunTests(unittest.TestCase):
    def test_the_whole_run(self) -> None:
        r = VECTORS["run"]
        pid, sid = h(r["pair_id"]), h(r["sid"])
        self.assertEqual(pf.channel_id(pid).hex(), r["ci"])
        g = pf.generator(r["code"], pid, sid)
        self.assertEqual(g.hex(), r["g"])
        ya, yb = cpace.scalar_mult(h(r["ya"]), g), cpace.scalar_mult(h(r["yb"]), g)
        self.assertEqual((ya.hex(), yb.hex()), (r["Ya"], r["Yb"]))
        k = cpace.scalar_mult_vfy(h(r["ya"]), yb)
        self.assertEqual(k.hex(), r["K"])
        isk = pf.isk(sid, k, ya, yb)
        self.assertEqual(isk.hex(), r["isk"])
        ks = pf.keys(isk, sid)
        self.assertEqual([ks[n].hex() for n in ("confirm_a", "confirm_b", "seal", "nonce")],
                         [r["confirm_a"], r["confirm_b"], r["seal"], r["nonce_key"]])
        nonce = pf.key_nonce(ks, h(r["sender"]))
        self.assertEqual(nonce.hex(), r["nonce"])
        self.assertEqual(nonce[8:], b"\x00\x00\x01\x00\x00")  # boot 1, count 0
        self.assertEqual(pf.tag_reply(ks).hex(), r["tag_reply"])
        self.assertEqual(pf.tag_key(ks).hex(), r["tag_key"])
        sealed = pf.seal_key(ks, nonce, pid, sid, h(r["join_key"]), r["field_name"])
        self.assertEqual(sealed.hex(), r["sealed"])
        self.assertEqual(pf.open_key(ks, nonce, pid, sid, sealed), (h(r["join_key"]), r["field_name"]))
        with self.assertRaises(pf.PairFrameError):
            pf.open_key(ks, nonce, pid, bytes(16), sealed)  # another run's sid
        self.assertEqual(pf.fingerprint_bytes(h(r["join_key"])).hex(), r["fingerprint"])
        self.assertEqual(pf.tag_done(ks, "adopted", h(r["fingerprint"])).hex(), r["tag_done"])

    def test_frames_round_trip(self) -> None:
        for name, frame in VECTORS["run"]["frames"].items():
            with self.subTest(name):
                msg = pf.decode(h(frame))
                self.assertEqual(msg["kind"], name)
                self.assertEqual(pf.encode(msg).hex(), frame)
                self.assertTrue(pf.is_frame(h(frame)))

    def test_a_wrong_code_shows_in_the_reply(self) -> None:
        r = VECTORS["run"]
        w = r["wrong_code"]
        pid, sid = h(r["pair_id"]), h(r["sid"])
        yb = cpace.scalar_mult(h(r["yb"]), pf.generator(w["code"], pid, sid))
        self.assertEqual(yb.hex(), w["Yb"])
        # The controller, with the right code, cannot match the box's tag.
        k = cpace.scalar_mult_vfy(h(r["ya"]), yb)
        ks = pf.keys(pf.isk(sid, k, h(r["Ya"]), yb), sid)
        self.assertNotEqual(pf.tag_reply(ks).hex(), w["tag_reply"])

    def test_generators_with_a_high_r(self) -> None:
        gens = VECTORS["generators"]
        self.assertGreaterEqual(sum(g["r_high"] for g in gens), 4)
        self.assertGreaterEqual(sum(not g["r_high"] for g in gens), 2)
        for g in gens:
            with self.subTest(g["code"]):
                self.assertEqual(pf.generator(g["code"], h(g["pair_id"]), h(g["sid"])).hex(), g["g"])

    def test_codes(self) -> None:
        self.assertTrue(pf.code_ok("000000"))
        for bad in ("12345", "1234567", "12a456", "١٢٣٤٥٦", 123456, None):
            self.assertFalse(pf.code_ok(bad))


class InvalidTests(unittest.TestCase):
    def test_bodies(self) -> None:
        self.assertGreaterEqual(len(VECTORS["invalid"]["bodies"]), 19)
        for b in VECTORS["invalid"]["bodies"]:
            with self.subTest(b["name"]):
                with self.assertRaises(pf.PairFrameError):
                    pf.body_decode(h(b["body"]))

    def test_frames(self) -> None:
        for f in VECTORS["invalid"]["frames"]:
            with self.subTest(f["name"]):
                self.assertFalse(pf.is_frame(h(f["frame"])))
                with self.assertRaises(pf.PairFrameError):
                    pf.decode(h(f["frame"]))


if __name__ == "__main__":
    unittest.main()
