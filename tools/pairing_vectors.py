#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes protocol/vectors/pairing.json, the pairing code's shared vectors (protocol/adoption.md).

    python3 tools/pairing_vectors.py           write the file
    python3 tools/pairing_vectors.py --check   fail if it is stale

The CPace cases are draft-irtf-cfrg-cpace-14's Appendix B.1 (CPACE-X25519-SHA512)
and B.1.10 (the low-order points), copied from the draft; the script checks them
against atalaia_sim.cpace (the cryptography library's X25519) before writing
anything. The run and the frames are this project's own cases: a whole pairing
with fixed scalars, sid and pair id, its keys, tags and frames, the sealed key by
the cryptography library's AES-CCM; then bodies and frames that must be refused.
core/tests/test_pair_frame.c and firmware/esp32/test/test_box_pair.c check them in
C (Monocypher's X25519 and Elligator 2, mbedtls's AES-CCM), simulator/tests/
test_pair_frame.py in Python.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "simulator"))

from atalaia_sim import cbor, cpace  # noqa: E402
from atalaia_sim import pair_frame as pf  # noqa: E402

OUT = REPO / "protocol" / "vectors" / "pairing.json"

# draft-irtf-cfrg-cpace-14, B.1 (X25519, SHA-512), as printed in the draft.
B1 = {
    "prs": "50617373776f7264",
    "ci": "6f630b425f726573706f6e6465720b415f696e69746961746f72",
    "sid": "7e4b4791d6a8ef019b936c79fb7f2c57",
    "generator_string": (
        "0843506163653235350850617373776f72646d000000000000000000"
        "00000000000000000000000000000000000000000000000000000000"
        "00000000000000000000000000000000000000000000000000000000"
        "00000000000000000000000000000000000000000000000000000000"
        "000000000000000000000000000000001a6f630b425f726573706f6e"
        "6465720b415f696e69746961746f72107e4b4791d6a8ef019b936c79"
        "fb7f2c57"),
    "hash_generator_string": "92806dc608984dbf4e4aae478c6ec453ae979cc01ecc1a2a7cf49f5cee56551b",
    "g": "64e8099e3ea682cfdc5cb665c057ebb514d06bf23ebc9f743b51b82242327074",
    "ya": "21b4f4bd9e64ed355c3eb676a28ebedaf6d8f17bdc365995b319097153044080",
    "ada": "414461",
    "Ya": "1b02dad6dbd29a07b6d28c9e04cb2f184f0734350e32bb7e62ff9dbcfdb63d15",
    "yb": "848b0779ff415f0af4ea14df9dd1d3c29ac41d836c7808896c4eba19c51ac40a",
    "adb": "414462",
    "Yb": "20cda5955f82c4931545bcbf40758ce1010d7db4db2a907013d79c7a8fcf957f",
    "K": "f97fdfcfff1c983ed6283856a401de3191ca919902b323c5f950c9703df7297a",
    "isk_ir": ("a051ee5ee2499d16da3f69f430218b8ea94a18a45b67f9e86495b382c33d14a5"
               "c38cecc0cc834f960e39e0d1bf7d76b9ef5d54eecc5e0f386c97ad12da8c3d5f"),
}
# B.1.10: scalar_mult_vfy(s, u) = q (all zeros: the abort case).
B1_LOW_S = "af46e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449aff"
B1_LOW = [
    ("0000000000000000000000000000000000000000000000000000000000000000", "00" * 32),
    ("0100000000000000000000000000000000000000000000000000000000000000", "00" * 32),
    ("ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f", "00" * 32),
    ("e0eb7a7c3b41b8ae1656e3faf19fc46ada098deb9c32b1fd866205165f49b800", "00" * 32),
    ("5f9c95bca3508c24b1d0b1559c83ef5b04445cc4581c8e86d8224eddd09f1157", "00" * 32),
    ("edffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f", "00" * 32),
    ("daffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
     "d8e2c776bbacd510d09fd9278b7edcd25fc5ae9adfba3b6e040e8d3b71b21806"),
    ("eeffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f", "00" * 32),
    ("dbffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
     "c85c655ebe8be44ba9c0ffde69f2fe10194458d137f09bbff725ce58803cdb38"),
    ("d9ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
     "db64dafa9b8fdd136914e61461935fe92aa372cb056314e1231bc4ec12417456"),
    ("cdeb7a7c3b41b8ae1656e3faf19fc46ada098deb9c32b1fd866205165f49b880",
     "e062dcd5376d58297be2618c7498f55baa07d7e03184e8aada20bca28888bf7a"),
    ("4c9c95bca3508c24b1d0b1559c83ef5b04445cc4581c8e86d8224eddd09f11d7",
     "993c6ad11c4c29da9a56f7691fd0ff8d732e49de6250b6c2e80003ff4629a175"),
]


def check_draft() -> None:
    """The draft's values against this implementation: nothing is written if one differs."""
    h = bytes.fromhex
    gs = cpace.generator_string(h(B1["prs"]), h(B1["ci"]), h(B1["sid"]))
    assert gs.hex() == B1["generator_string"], "generator string"
    g = cpace.calculate_generator(h(B1["prs"]), h(B1["ci"]), h(B1["sid"]))
    assert g.hex() == B1["g"], "g"
    ya = cpace.scalar_mult(h(B1["ya"]), g)
    yb = cpace.scalar_mult(h(B1["yb"]), g)
    assert ya.hex() == B1["Ya"] and yb.hex() == B1["Yb"], "Ya, Yb"
    k = cpace.scalar_mult_vfy(h(B1["ya"]), yb)
    assert k == cpace.scalar_mult_vfy(h(B1["yb"]), ya) and k.hex() == B1["K"], "K"
    isk = cpace.isk_ir(h(B1["sid"]), k, ya, h(B1["ada"]), yb, h(B1["adb"]))
    assert isk.hex() == B1["isk_ir"], "ISK"
    for u, q in B1_LOW:
        assert cpace.scalar_mult(h(B1_LOW_S), h(u)).hex() == q, f"low order {u}"


# This project's run (fixed values; on air they come from the RNG, never stored).
JOIN_KEY = bytes(range(32))  # join.json's and field_card.json's key
FIELD_NAME = "Campo da Atalaia"
CODE = "042137"
PAIR_ID = bytes.fromhex("b0c5b0c5a1a2a3a4")
SID = bytes.fromhex("5e55105e55105e55105e55105e551001")
YA = bytes.fromhex("6a" * 32)
YB = bytes.fromhex("6b" * 32)
SENDER = bytes.fromhex("c0ffee00c0ffee01")  # the controller's sender id for this run


def run_section() -> dict:
    g = pf.generator(CODE, PAIR_ID, SID)
    ya = cpace.scalar_mult(YA, g)
    yb = cpace.scalar_mult(YB, g)
    k = cpace.scalar_mult_vfy(YA, yb)
    assert k == cpace.scalar_mult_vfy(YB, ya)
    isk = pf.isk(SID, k, ya, yb)
    ks = pf.keys(isk, SID)
    nonce = pf.key_nonce(ks, SENDER)
    sealed = pf.seal_key(ks, nonce, PAIR_ID, SID, JOIN_KEY, FIELD_NAME)
    fp = pf.fingerprint_bytes(JOIN_KEY)
    frames = {
        "offer": {"kind": "offer", "pair_id": PAIR_ID, "name": "porta-norte", "tier": 0},
        "start": {"kind": "start", "pair_id": PAIR_ID, "sid": SID, "point": ya},
        "reply": {"kind": "reply", "pair_id": PAIR_ID, "sid": SID, "point": yb, "tag": pf.tag_reply(ks)},
        "key": {"kind": "key", "pair_id": PAIR_ID, "sid": SID, "tag": pf.tag_key(ks), "nonce": nonce,
                "sealed": sealed},
        "done": {"kind": "done", "pair_id": PAIR_ID, "sid": SID, "result": "adopted", "fingerprint": fp,
                 "tag": pf.tag_done(ks, "adopted", fp)},
    }
    # The same run with a wrong code: the box's answer gives itself away (tag_b differs).
    g2 = pf.generator("042138", PAIR_ID, SID)
    yb2 = cpace.scalar_mult(YB, g2)
    k2 = cpace.scalar_mult_vfy(YB, ya)  # the box computes with its own (wrong-code) generator
    ks2 = pf.keys(pf.isk(SID, k2, ya, yb2), SID)
    return {
        "join_key": JOIN_KEY.hex(), "field_name": FIELD_NAME, "code": CODE, "pair_id": PAIR_ID.hex(),
        "sid": SID.hex(), "ci": pf.channel_id(PAIR_ID).hex(), "ada": pf.AD_CONTROLLER.hex(),
        "adb": pf.AD_BOX.hex(), "ya": YA.hex(), "yb": YB.hex(), "g": g.hex(), "Ya": ya.hex(), "Yb": yb.hex(),
        "K": k.hex(), "isk": isk.hex(), "confirm_a": ks["confirm_a"].hex(), "confirm_b": ks["confirm_b"].hex(),
        "seal": ks["seal"].hex(), "nonce_key": ks["nonce"].hex(), "sender": SENDER.hex(), "nonce": nonce.hex(),
        "tag_reply": pf.tag_reply(ks).hex(), "tag_key": pf.tag_key(ks).hex(), "sealed": sealed.hex(),
        "fingerprint": fp.hex(), "tag_done": pf.tag_done(ks, "adopted", fp).hex(),
        "frames": {name: pf.encode(msg).hex() for name, msg in frames.items()},
        "wrong_code": {"code": "042138", "Yb": yb2.hex(), "tag_reply": pf.tag_reply(ks2).hex()},
    }


def generators_section() -> list[dict]:
    """Generators for codes, pair ids and sids found by a fixed search so that half of them hash
    to an r of 2^254 or more: the branch where the box gives Monocypher's Elligator 2 p - r."""
    import hashlib  # noqa: PLC0415
    out: list[dict] = []
    high = low = 0
    i = 0
    while high < 4 or low < 2:
        sid = hashlib.sha256(b"atalaia pairing generator %d" % i).digest()[:16]
        code = f"{i * 7919 % 1000000:06d}"
        pid = hashlib.sha256(b"pair id %d" % i).digest()[:8]
        gs = cpace.generator_string(code.encode(), pf.channel_id(pid), sid)
        h = hashlib.sha512(gs).digest()[:32]
        r = (int.from_bytes(h, "little") & ((1 << 255) - 1)) % cpace.P
        is_high = r >= 1 << 254
        i += 1
        if (is_high and high >= 4) or (not is_high and low >= 2):
            continue
        # Elligator 2 depends on r only through r^2: the same point for p - r.
        assert cpace._elligator2(r) == cpace._elligator2(cpace.P - r)
        g = pf.generator(code, pid, sid)
        out.append({"code": code, "pair_id": pid.hex(), "sid": sid.hex(), "r_high": is_high, "g": g.hex()})
        high += is_high
        low += not is_high
    return out


def invalid_section(run: dict) -> dict:
    h = bytes.fromhex
    start = h(run["frames"]["start"])
    body = start[9:]
    bodies = []

    def add(name: str, data: bytes) -> None:
        bodies.append({"name": name, "body": data.hex()})

    ya = h(run["Ya"])
    pid = h(run["pair_id"])
    sid = h(run["sid"])
    add("empty", b"")
    add("not_a_map", cbor.encode([1, 2]))
    add("kind_not_first", cbor.encode({2: pid, 1: 2, 5: sid, 6: ya}))
    add("unknown_kind", cbor.encode({1: 9, 2: pid}))
    add("kind_0", cbor.encode({1: 0, 2: pid}))
    add("missing_point", cbor.encode({1: 2, 2: pid, 5: sid}))
    add("short_pair_id", cbor.encode({1: 2, 2: pid[:7], 5: sid, 6: ya}))
    add("short_sid", cbor.encode({1: 2, 2: pid, 5: sid[:15], 6: ya}))
    add("long_point", cbor.encode({1: 2, 2: pid, 5: sid, 6: ya + b"\x00"}))
    add("point_as_text", cbor.encode({1: 2, 2: pid, 5: sid, 6: "x" * 32}))
    add("another_kinds_key", cbor.encode({1: 2, 2: pid, 5: sid, 6: ya, 7: bytes(16)}))
    add("key_32", cbor.encode({1: 2, 2: pid, 5: sid, 6: ya, 32: 0}))
    add("trailing_byte", body + b"\x00")
    add("offer_tier_3", cbor.encode({1: 1, 2: pid, 3: "box", 4: 3}))
    add("offer_empty_name", cbor.encode({1: 1, 2: pid, 3: "", 4: 0}))
    add("offer_long_name", cbor.encode({1: 1, 2: pid, 3: "x" * 25, 4: 0}))
    add("done_result_10", cbor.encode({1: 5, 2: pid, 5: sid, 10: 10, 11: bytes(4), 7: bytes(16)}))
    add("key_short_sealed", cbor.encode({1: 4, 2: pid, 5: sid, 7: bytes(16), 8: bytes(13), 9: bytes(40)}))
    add("key_long_sealed", cbor.encode({1: 4, 2: pid, 5: sid, 7: bytes(16), 8: bytes(13), 9: bytes(90)}))
    for b in bodies:
        try:
            pf.body_decode(h(b["body"]))
        except pf.PairFrameError:
            continue
        raise AssertionError(f"the codec takes {b['name']}")
    frames = []

    def addf(name: str, data: bytes) -> None:
        assert not pf.is_frame(data), name
        frames.append({"name": name, "frame": data.hex()})

    addf("header_only", start[:9])
    addf("encrypted_flag", bytes([0x2A]) + start[1:])
    addf("game_id_1", start[:1] + b"\x00\x01" + start[3:])
    addf("type_9", start[:8] + b"\x09" + start[9:])
    addf("version_2", bytes([(start[0] & 0x3F) | 0x80]) + start[1:])
    addf("too_long", start[:9] + bytes(201))
    return {"bodies": bodies, "frames": frames}


def build() -> dict:
    check_draft()
    run = run_section()
    return {
        "description": "Pairing a box by the code it shows (protocol/adoption.md section 7, RFC 0001 Amendment 8). "
                       "cpace_b1 and cpace_low_order are draft-irtf-cfrg-cpace-14's Appendix B.1 and B.1.10 "
                       "(CPACE-X25519-SHA512), copied from the draft: generator, Ya, Yb, K and ISK must come out "
                       "as printed, and every low-order u-coordinate must give its q (all zeros: abort). run is "
                       "this project's whole exchange with fixed scalars, sid and pair id: the generator from the "
                       "code and CI = lv_cat(\"atalaia pair v1\", pair id), ADa \"atalaia controller\", ADb "
                       "\"atalaia box\", the keys from the ISK (HKDF-SHA256, salt = sid), the tags, the join key "
                       "sealed with AES-128-CCM (8-byte MIC) and the five frames; wrong_code is the box's answer "
                       "when it shows another code. generators are codes, pair ids and sids whose hashed generator string "
                       "is 2^254 or more (r_high) or below, with their generator g. invalid lists bodies and frames "
                       "every codec must refuse.",
        "cpace_b1": B1,
        "cpace_low_order": {"s": B1_LOW_S, "points": [{"u": u, "q": q} for u, q in B1_LOW]},
        "run": run,
        "generators": generators_section(),
        "invalid": invalid_section(run),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = ap.parse_args()
    text = json.dumps(build(), indent=2) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("pairing_vectors: protocol/vectors/pairing.json is stale; run python3 tools/pairing_vectors.py",
                  file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
