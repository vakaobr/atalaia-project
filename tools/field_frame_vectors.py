#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes protocol/vectors/field_frame.json, the field frames' shared vectors.

    python3 tools/field_frame_vectors.py           write the file
    python3 tools/field_frame_vectors.py --check   fail if it is stale

The HKDF-SHA256 cases are RFC 5869's appendix A.1-A.3, copied from the RFC
(the script checks them against the cryptography library's HKDF, an
independent implementation, before writing anything). The frames are this
project's own cases: AES-128-CCM by the cryptography library under the key
derived from join.json's join key, with fixed nonces; core/tests/
test_field_frame.c checks them with mbedtls, simulator/tests/
test_field_frame.py with this codec. Needs PyYAML-free Python 3 and the
cryptography package.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "simulator"))

from atalaia_sim import cbor  # noqa: E402
from atalaia_sim import field_frame as ff  # noqa: E402

OUT = REPO / "protocol" / "vectors" / "field_frame.json"

# RFC 5869 appendix A, test cases 1-3 (SHA-256), as printed in the RFC.
RFC5869 = [
    {"name": "rfc5869_a1",
     "ikm": "0b" * 22, "salt": "000102030405060708090a0b0c", "info": "f0f1f2f3f4f5f6f7f8f9", "length": 42,
     "prk": "077709362c2e32df0ddc3f0dc47bba6390b6c73bb50f9c3122ec844ad7c2b3e5",
     "okm": "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"},
    {"name": "rfc5869_a2",
     "ikm": bytes(range(0x00, 0x50)).hex(), "salt": bytes(range(0x60, 0xb0)).hex(),
     "info": bytes(range(0xb0, 0x100)).hex(), "length": 82,
     "prk": "06a6b88c5853361a06104c9ceb35b45cef760014904671014a193f40c15fc244",
     "okm": "b11e398dc80327a1c8e7f78c596a49344f012eda2d4efad8a050cc4c19afa97c"
            "59045a99cac7827271cb41c65e590e09da3275600c2f09b8367793a9aca3db71"
            "cc30c58179ec3e87c14c01d5c1f3434f1d87"},
    {"name": "rfc5869_a3",
     "ikm": "0b" * 22, "salt": "", "info": "", "length": 42,
     "prk": "19ef24a32c717b167f33a91d6f648bdf96596776afdb6377ac434c1c293ccb04",
     "okm": "8da4e775a563c18f715f802a063c5a31b8a11f5c5ee1879ec3454e5f3c738d2d9d201395faa4b61a96c8"},
]

DEVICE = bytes.fromhex("5a17c0de0b0e1234")
TOKEN = bytes.fromhex("0123456789abcdef")


CONTROLLER = bytes.fromhex("c0c1c2c3c4c5c6c7")  # a controller's sender id


def nonces_section(join_key: bytes) -> dict:
    """The nonce rule (decision RJ-15): known pseudonym inputs and the NonceSource's sequence."""
    nk = ff.nonce_key(join_key)
    cases = []
    for name, sender, boot, ctr in (("box_first_frame", DEVICE, 1, 0), ("box_later", DEVICE, 4242, 513),
                                    ("controller_first", CONTROLLER, 1, 0), ("largest", CONTROLLER, ff.BOOT_MAX,
                                                                             ff.CTR_MAX)):
        cases.append({"name": name, "sender": sender.hex(), "boot": boot, "ctr": ctr,
                      "nonce": ff.nonce(nk, sender, boot, ctr).hex()})
    # A run after a stored boot count of 41: boot 42, ctr 0 and 1; past ctr 65535 the count
    # goes up again (43, ctr 0).
    stored = {"boot": 41}
    src = ff.NonceSource(join_key, DEVICE, lambda: stored["boot"], lambda b: stored.update(boot=b) or True)
    seq = [src.next().hex(), src.next().hex()]
    src.ctr = ff.CTR_MAX
    seq += [src.next().hex(), src.next().hex()]
    return {"nonce_key": nk.hex(), "cases": cases,
            "source": {"sender": DEVICE.hex(), "stored_boot": 41, "nonces": seq, "stored_after": stored["boot"]}}


_NK = None


def nonce(n: int) -> bytes:
    """The vectors' nonces follow the rule too: the box's device id, boot 1, frame count n."""
    return ff.nonce(_NK, DEVICE, 1, n)


def check_rfc5869() -> None:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    for v in RFC5869:
        salt = bytes.fromhex(v["salt"]) or None
        theirs = HKDF(algorithm=hashes.SHA256(), length=v["length"], salt=salt,
                      info=bytes.fromhex(v["info"])).derive(bytes.fromhex(v["ikm"]))
        ours = ff.hkdf_sha256(bytes.fromhex(v["ikm"]), v["length"], bytes.fromhex(v["salt"]), bytes.fromhex(v["info"]))
        if theirs.hex() != v["okm"] or ours.hex() != v["okm"]:
            raise SystemExit(f"{v['name']}: the RFC's OKM does not match the cryptography library's HKDF")


def fields_json(msg: dict) -> dict:
    return {k: (v.hex() if isinstance(v, (bytes, bytearray)) else v) for k, v in msg.items()}


def build() -> dict:
    check_rfc5869()
    join = json.loads((REPO / "protocol" / "vectors" / "join.json").read_text())
    join_key = bytes.fromhex(join["join_key"])
    wrong_key = bytes.fromhex(join["wrong_key"])
    key = ff.field_key(join_key)
    global _NK
    _NK = ff.nonce_key(join_key)
    payloads = {v["name"]: bytes.fromhex(v["payload"]) for v in join["valid"]}
    # GAME_OVER names a game by its key's tag: the epoch store's tags, from epoch_tag.json (computed
    # there with Python's hmac); this codec must agree before anything is written.
    tags = {v["name"]: v for v in json.loads((REPO / "protocol" / "vectors" / "epoch_tag.json").read_text())["valid"]}
    for v in tags.values():
        if ff.key_tag(bytes.fromhex(v["game_key"])).hex() != v["tag"]:
            raise SystemExit(f"epoch_tag.json {v['name']}: field_frame.key_tag disagrees")
    tag = bytes.fromhex(tags["counting_key"]["tag"])

    valid_msgs = [
        ("announce_minimal", {"kind": "announce", "device_id": DEVICE, "token": TOKEN, "name": "field-box", "tier": 0}),
        ("announce_after_a_game", {"kind": "announce", "device_id": DEVICE, "token": TOKEN, "name": "Zona Norte",
                                   "tier": 1, "last_game": 4242, "last_role": "zone", "battery_pct": 81}),
        ("announce_answer_accepted", {"kind": "announce", "device_id": DEVICE, "token": bytes(8), "name": "box-a3f1",
                                      "tier": 0, "last_game": 513, "last_role": "satellite", "answer": 7001,
                                      "result": "accepted"}),
        ("announce_answer_busy", {"kind": "announce", "device_id": DEVICE, "token": TOKEN, "name": "box-a3f1",
                                  "tier": 0, "answer": 65535, "result": "busy"}),
        ("discover", {"kind": "discover"}),
        ("invite_one_part", {"kind": "invite", "device_id": DEVICE, "token": TOKEN, "invite_id": 1, "part": 0,
                             "parts": 1, "chunk": payloads["node_domination_zone"]}),
        ("invite_largest_part", {"kind": "invite", "device_id": DEVICE, "token": TOKEN, "invite_id": 65535,
                                 "part": 2, "parts": 3, "chunk": bytes(range(ff.CHUNK_MAX))}),
        ("game_over", {"kind": "game_over", "game_id": 4242, "key_tag": tag}),
        ("game_over_last_game_id", {"kind": "game_over", "game_id": 65534,
                                    "key_tag": bytes.fromhex(tags["all_ones"]["tag"])}),
        # RFC 0001 Amendment 19: the field's channel changed. Appended, so the indexes above stay.
        ("move", {"kind": "move", "channel_hz": 869925000, "rev": 3}),
        ("move_largest", {"kind": "move", "channel_hz": 4294967295, "rev": 4294967295}),
        # RFC 0001 Amendment 28 (proposed): every box in a game other than the live one leaves it.
        # Its addendum of 2026-11-06: key 6, the channel it is sent on, required.
        ("release", {"kind": "release", "live_game": 4242, "time": 1793000000, "channel_hz": 869525000}),
        ("release_no_live_game", {"kind": "release", "live_game": 0, "time": 4294967295,
                                  "channel_hz": 4294967295}),
    ]
    valid = []
    for i, (name, msg) in enumerate(valid_msgs):
        body = ff.body_encode(msg)
        frame = ff.seal(key, body, nonce(i))
        valid.append({"name": name, "fields": fields_json(msg), "body": body.hex(), "nonce": nonce(i).hex(),
                      "frame": frame.hex()})
    # The largest body fits the modem's 200 bytes with the nonce: the frame is at most 217.
    assert max(len(v["frame"]) // 2 for v in valid) == ff.FRAME_MAX

    good = bytes.fromhex(valid[1]["frame"])
    hop = bytearray(good)
    hop[7] = 2  # hop_limit is not authenticated (as for game packets): the frame still opens
    tampered = bytearray(good)
    tampered[ff.HEADER_SIZE + ff.NONCE_SIZE + 3] ^= 0x01
    nonce_changed = bytearray(good)
    nonce_changed[ff.HEADER_SIZE] ^= 0x80
    game = bytearray(good)
    game[2] = 0x01
    type_ = bytearray(good)
    type_[8] = 5
    clear = bytearray(good)
    clear[0] &= 0xFD
    version = bytearray(good)
    version[0] = (version[0] & 0x1F) | (2 << 5)
    seq = bytearray(good)
    seq[6] = 0x01  # seq is in the AAD
    long_body = ff.seal(key, bytes(ff.BODY_MAX), nonce(100))
    frames_invalid = [
        ("wrong_field_key", ff.seal(ff.field_key(wrong_key), bytes.fromhex(valid[1]["body"]), nonce(1)), "mac"),
        ("body_altered", bytes(tampered), "mac"),
        ("nonce_altered", bytes(nonce_changed), "mac"),
        ("seq_altered", bytes(seq), "mac"),
        ("game_id_not_zero", bytes(game), "header"),
        ("not_type_field", bytes(type_), "header"),
        ("not_encrypted", bytes(clear), "header"),
        ("version_2", bytes(version), "header"),
        ("no_body", good[:ff.HEADER_SIZE + ff.NONCE_SIZE] + good[-ff.MIC_SIZE:], "length"),
        ("too_long", long_body[:ff.HEADER_SIZE + ff.NONCE_SIZE] + bytes(1) + long_body[ff.HEADER_SIZE + ff.NONCE_SIZE:],
         "length"),
    ]

    def m(d: dict) -> str:
        return cbor.encode(d).hex()

    ann = {1: 1, 2: DEVICE, 3: TOKEN, 4: "box", 5: 0}
    inv = {1: 3, 2: DEVICE, 3: TOKEN, 4: 9, 5: 0, 6: 1, 7: b"\x01\x02"}
    over = {1: 4, 4: 7, 5: tag}
    mv = {1: 5, 4: 869925000, 5: 3}
    rel = {1: 6, 4: 4242, 5: 1793000000, 6: 869525000}
    bodies_invalid = [
        ("unknown_kind", m({1: 7})),
        ("unknown_kind_7_with_release_keys", m({1: 7, 4: 4242, 5: 1793000000, 6: 869525000})),
        ("kind_not_first", m({2: DEVICE, 1: 1, 3: TOKEN, 4: "box", 5: 0})),
        ("not_a_map", m([1, 2])),
        ("announce_without_name", m({1: 1, 2: DEVICE, 3: TOKEN, 5: 0})),
        ("announce_empty_name", m({**ann, 4: ""})),
        ("announce_name_too_long", m({**ann, 4: "x" * 25})),
        ("announce_name_with_nul", m({**ann, 4: "bo\x00x"})),
        ("announce_device_id_7_bytes", m({**ann, 2: DEVICE[:7]})),
        ("announce_token_9_bytes", m({**ann, 3: TOKEN + b"\x00"})),
        ("announce_tier_3", m({**ann, 5: 3})),
        ("announce_last_game_0", m({**ann, 6: 0})),
        ("announce_last_game_65535", m({**ann, 6: 65535})),
        ("announce_role_too_long", m({**ann, 7: "r" * 32})),
        ("announce_battery_101", m({**ann, 8: 101})),
        ("announce_answer_without_result", m({**ann, 9: 5})),
        ("announce_result_without_answer", m({**ann, 10: 0})),
        ("announce_result_8", m({**ann, 9: 5, 10: 8})),
        ("announce_answer_0", m({**ann, 9: 0, 10: 0})),
        ("discover_with_a_device", m({1: 2, 2: DEVICE})),
        ("invite_without_chunk", m({k: v for k, v in inv.items() if k != 7})),
        ("invite_empty_chunk", m({**inv, 7: b""})),
        ("invite_chunk_too_long", m({**inv, 7: bytes(ff.CHUNK_MAX + 1)})),
        ("invite_part_beyond_parts", m({**inv, 5: 1, 6: 1})),
        ("invite_parts_0", m({**inv, 6: 0})),
        ("invite_parts_4", m({**inv, 5: 0, 6: 4})),
        ("invite_id_0", m({**inv, 4: 0})),
        ("invite_with_an_announce_key", m({**inv, 8: 50})),
        ("game_over_without_tag", m({1: 4, 4: 7})),
        ("game_over_without_game", m({1: 4, 5: tag})),
        ("game_over_game_0", m({**over, 4: 0})),
        ("game_over_game_65535", m({**over, 4: 65535})),
        ("game_over_tag_7_bytes", m({**over, 5: tag[:7]})),
        ("game_over_with_a_device", m({**over, 2: DEVICE})),
        ("game_over_with_an_invite_key", m({**over, 7: b"\x01"})),
        ("move_without_channel", m({1: 5, 5: 3})),
        ("move_without_rev", m({1: 5, 4: 869925000})),
        ("move_channel_0", m({**mv, 4: 0})),
        ("move_rev_0", m({**mv, 5: 0})),
        ("move_channel_too_big", m({**mv, 4: 4294967296})),
        ("move_rev_too_big", m({**mv, 5: 4294967296})),
        ("move_channel_not_a_number", m({**mv, 4: "869925000"})),
        ("move_with_a_device", m({**mv, 2: DEVICE})),
        ("move_with_a_token", m({**mv, 3: TOKEN})),
        ("move_with_an_announce_key", m({**mv, 8: 50})),
        ("move_with_an_invite_key", m({**mv, 7: b"\x01"})),
        ("release_without_time", m({1: 6, 4: 4242, 6: 869525000})),
        ("release_without_live_game", m({1: 6, 5: 1793000000, 6: 869525000})),
        # The format of before the addendum of 2026-11-06 (a v0.9.0 controller's): no channel.
        ("release_without_channel", m({1: 6, 4: 4242, 5: 1793000000})),
        ("release_channel_0", m({**rel, 6: 0})),
        ("release_channel_too_big", m({**rel, 6: 4294967296})),
        ("release_channel_as_text", m({**rel, 6: "869525000"})),
        ("release_time_0", m({**rel, 5: 0})),
        ("release_time_too_big", m({**rel, 5: 4294967296})),
        ("release_live_game_65535", m({**rel, 4: 65535})),
        ("release_time_as_bytes", m({**rel, 5: tag})),
        ("release_with_a_device", m({**rel, 2: DEVICE})),
        ("release_with_a_token", m({**rel, 3: TOKEN})),
        ("release_with_an_invite_key", m({**rel, 7: b"\x01"})),
        ("release_with_an_announce_key", m({**rel, 8: 50})),
        ("key_32", m({**ann, 32: 1})),
        ("trailing_byte", m(ann) + "00"),
        ("duplicate_key", "a6" + m(ann)[2:] + "0500"),
    ]
    skipped = m({**ann, 20: "a later field"})

    split = []
    for name in ("node_domination_zone", "node_with_params", "eight_teams_long_names"):
        p = payloads[name]
        split.append({"name": name, "payload": p.hex(), "parts": [c.hex() for c in ff.split(p)]})

    return {
        "description": ("Field frame vectors (protocol/field-frames.md, RFC 0001 Amendment 7). hkdf_sha256: RFC 5869 "
                        "appendix A.1-A.3 as printed in the RFC. field_key: HKDF-SHA256 of join.json's join_key with no "
                        "salt and the info 'atalaia field frame v1', 16 bytes. valid: each body decodes to its fields "
                        "and re-encodes byte for byte; sealed with field_key and the given nonce it is the frame, which "
                        "opens back to the body (AES-128-CCM, 8-byte MIC, AAD the header without hop_limit). "
                        "hop_limit_ignored opens to valid[1]'s body. invalid_frames do not open (reason: header, "
                        "length or mac). invalid_bodies are refused by the body decoder. optional_key_skipped decodes "
                        "like an announce without key 20. split: a join payload's invite chunks (153 bytes, the last "
                        "shorter). game_over's key_tag is epoch_tag.json's tag of its game key (counting_key, all_ones). move (RFC 0001 Amendment 19): keys 4 channel_hz and 5 rev, both 1-4294967295. release (RFC 0001 Amendment 28 and its addendum of 2026-11-06): keys 4 live_game (0-65534, 0: no game live), 5 time (1-4294967295, the sender's wall clock in Unix seconds) and 6 channel_hz (1-4294967295, the channel it is sent on), all required. release_rules: what a box in a game does with a RELEASE, given its game, its channel, its join time (0: unknown), whether it heard a TIME of its game since it started and how many seconds ago, and the newest such TIME's non-zero wall_s (0: none) with the seconds since; verdicts in this order: live (it names the box's game), other_channel, hearing (a TIME heard less than heard_s ago), no_join_time, old (time not after the join), ahead (time > newest wall_s + since + ahead_s), else taken. nonces: nonce_key is HKDF-SHA256 of the join key with the info 'atalaia field nonce v1', "
                        "32 bytes; a nonce is HMAC-SHA256(nonce_key, sender)[0..7] | boot (3 bytes) | ctr (2 bytes), "
                        "big-endian; source: a sender's run after a stored boot count of 41 (its first two nonces, then "
                        "the last of boot 42 and the first of boot 43), which leaves 43 stored. Generated by "
                        "tools/field_frame_vectors.py."),
        "hkdf_sha256": RFC5869,
        "join_key": join_key.hex(),
        "field_key": key.hex(),
        "valid": valid,
        "hop_limit_ignored": bytes(hop).hex(),
        "invalid_frames": [{"name": n, "frame": f.hex(), "reason": r} for n, f, r in frames_invalid],
        "invalid_bodies": [{"name": n, "body": b} for n, b in bodies_invalid],
        "optional_key_skipped": skipped,
        "split": split,
        "nonces": nonces_section(join_key),
        "release_rules": release_rules(),
    }


def release_rules() -> dict:
    """What a box in a game does with a RELEASE (RFC 0001 Amendment 28, addendum of 2026-11-06):
    atalaia_ff_release_verdict in C, field_frame.release_verdict in Python."""
    # A box whose controller went quiet 10 minutes ago (its last TIME), in a game joined an hour before.
    box = {"game_id": 513, "channel_hz": 869525000, "join_wall_s": 1793000100, "heard_time": True,
           "since_heard_s": 600, "time_wall_s": 1793003600, "since_time_s": 600}
    now = box["time_wall_s"] + box["since_time_s"]  # the box's estimate of its game's wall clock
    rel = {"live_game": 3328, "time": now, "channel_hz": box["channel_hz"]}
    rebooted = {**box, "heard_time": False, "since_heard_s": 0, "time_wall_s": 0, "since_time_s": 0}
    playing = {**box, "time_wall_s": 1793000100, "since_time_s": 10, "since_heard_s": 10}
    heard = ff.RELEASE_HEARD_S
    cases = [
        ("taken", box, rel, "taken"),
        ("taken_no_live_game", box, {**rel, "live_game": 0}, "taken"),
        ("live_game_is_the_box_s", box, {**rel, "live_game": 513}, "live"),
        ("another_channel", box, {**rel, "channel_hz": 868100000}, "other_channel"),
        ("another_channel_live_game_0", box, {**rel, "live_game": 0, "channel_hz": 869525001}, "other_channel"),
        # The active phase's case: a box playing a game it still hears, a RELEASE 100 s after its join.
        ("playing_a_game_it_hears", playing, {**rel, "time": 1793000200}, "hearing"),
        ("playing_a_game_it_hears_14_days_ahead", playing, {**rel, "time": 1793000100 + 14 * 86400}, "hearing"),
        ("playing_a_game_it_hears_time_max", playing, {**rel, "time": 0xFFFFFFFF}, "hearing"),
        ("heard_just_under_the_limit", {**box, "since_heard_s": heard - 1}, rel, "hearing"),
        ("heard_at_the_limit", {**box, "since_heard_s": heard}, rel, "taken"),
        ("time_without_a_wall_clock_heard", {**box, "since_heard_s": 5, "time_wall_s": 0}, rel, "hearing"),
        ("no_time_ever_heard", {**rebooted, "join_wall_s": 0}, rel, "no_join_time"),
        ("at_the_join", box, {**rel, "time": box["join_wall_s"]}, "old"),
        ("before_the_join", box, {**rel, "time": box["join_wall_s"] - 3600}, "old"),
        ("ahead_by_the_margin", box, {**rel, "time": now + ff.RELEASE_AHEAD_S}, "taken"),
        ("ahead_past_the_margin", box, {**rel, "time": now + ff.RELEASE_AHEAD_S + 1}, "ahead"),
        ("ahead_14_days", box, {**rel, "time": now + 14 * 86400}, "ahead"),
        ("ahead_time_max", box, {**rel, "time": 0xFFFFFFFF}, "ahead"),
        ("quiet_for_hours", {**box, "since_heard_s": 6 * 3600, "since_time_s": 6 * 3600},
         {**rel, "time": box["time_wall_s"] + 6 * 3600 - 60}, "taken"),
        ("time_near_the_end_of_the_clock", {**box, "time_wall_s": 0xFFFFFF00, "since_time_s": 0xFFFF},
         {**rel, "time": 0xFFFFFFFF}, "taken"),
        # Restarted into a game nobody runs any more (the bench recovery of 2026-11-06): freed at once.
        ("rebooted_into_a_lost_game", rebooted, {**rel, "time": now + 30 * 86400}, "taken"),
        ("rebooted_another_channel", rebooted, {**rel, "channel_hz": 868100000}, "other_channel"),
        ("rebooted_before_the_join", rebooted, {**rel, "time": box["join_wall_s"] - 1}, "old"),
        ("rebooted_then_heard_its_game", {**rebooted, "heard_time": True, "since_heard_s": 3}, rel, "hearing"),
    ]
    out = []
    for name, b, r, verdict in cases:
        msg = {"kind": "release", **r}
        ff.validate(msg)
        got = ff.release_verdict(b, msg)
        assert got == verdict, (name, got, verdict)
        out.append({"name": name, "box": b, "release": r, "verdict": verdict})
    return {"ahead_s": ff.RELEASE_AHEAD_S, "heard_s": ff.RELEASE_HEARD_S, "cases": out}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = ap.parse_args()
    text = json.dumps(build(), indent=2) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"{OUT.relative_to(REPO)} is stale: run python3 tools/field_frame_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
