#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Writes protocol/vectors/box_beacon.json: the Field Box's iBeacon (decisions BBC-1 to BBC-12).

    python3 tools/box_beacon_vectors.py           write it
    python3 tools/box_beacon_vectors.py --check   fail if it is stale

The field's beacon UUID from its join key, a box's 30 advertisement bytes for a node id and a calibrated
power, the node ids that are no box's, and the 0.625 ms units of the advertising interval. Made here from
hashlib alone (not from the controller's code), so the three implementations that check the file (the
box's C, firmware/esp32/main/box_beacon.c through tools/protogen.py's firmware/esp32/test/box_beacon_vectors.h;
the Pi controller, controller/atalaia_controller/box_beacons.py; the Android controller,
app/lib/controller/controller_box_beacons.dart) are each compared with an independent computation.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "protocol" / "vectors" / "box_beacon.json"

LABEL = "atalaia box beacon uuid v1"
MAJOR = 0xB0C5
KEYS = [bytes(range(32)), bytes([0x42] * 32), bytes([0xFF] * 32)]


def uuid_of(key: bytes) -> bytes:
    u = bytearray(hmac.new(key, LABEL.encode(), hashlib.sha256).digest()[:16])
    u[6] = (u[6] & 0x0F) | 0x80
    u[8] = (u[8] & 0x3F) | 0x80
    return bytes(u)


def text_of(u: bytes) -> str:
    h = u.hex().upper()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def adv_of(u: bytes, major: int, minor: int, power: int) -> bytes:
    return (bytes([0x02, 0x01, 0x06, 0x1A, 0xFF, 0x4C, 0x00, 0x02, 0x15]) + u + major.to_bytes(2, "big")
            + minor.to_bytes(2, "big") + (power & 0xFF).to_bytes(1, "big"))


def units_of(ms: int) -> int:
    return min(max((ms * 1000 + 312) // 625, 0x20), 0x4000)


def build() -> dict:
    uuids = [{"join_key": k.hex(), "uuid": uuid_of(k).hex(), "uuid_text": text_of(uuid_of(k))} for k in KEYS]
    adv = []
    for key, node, power in [(KEYS[0], 1, -59), (KEYS[0], 7, -59), (KEYS[0], 258, -70), (KEYS[0], 65534, 0),
                             (KEYS[1], 7, -59), (KEYS[2], 300, -127)]:
        u = uuid_of(key)
        data = adv_of(u, MAJOR, node, power)
        assert len(data) == 30
        adv.append({"join_key": key.hex(), "node_id": node, "measured_power": power, "major": MAJOR, "minor": node,
                    "id": f"{MAJOR}:{node}", "adv": data.hex()})
    return {
        "description": "The Field Box as an iBeacon (decisions BBC-1 to BBC-12; protocol/box-beacon.md): the field's "
                       "proximity UUID is HMAC-SHA256(join key, label)[:16] with the version nibble 8 and the RFC 4122 "
                       "variant; the major is the constant 45253 (0xB0C5), the minor the box's node id; the 30-byte "
                       "advertisement is flags, Apple's manufacturer data (0x004C, type 0x02, length 0x15), UUID, "
                       "major, minor (big endian) and the measured power. Made by tools/box_beacon_vectors.py; "
                       "checked by firmware/esp32/test/test_box_beacon.c, controller/tests/test_box_beacons.py and "
                       "app/test/controller/controller_box_beacons_test.dart.",
        "label": LABEL,
        "major": MAJOR,
        "uuids": uuids,
        "adv": adv,
        "refused_node_ids": [0, 65535],
        "interval_units": [{"ms": ms, "units": units_of(ms)} for ms in (5, 20, 100, 500, 1000, 10240, 20000)],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tools/box_beacon_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
