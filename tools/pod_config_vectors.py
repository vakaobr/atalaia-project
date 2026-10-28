#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Writes protocol/vectors/pod_config.json: the I/O pod's settings pushed over the radio (decision PODC).

    python3 tools/pod_config_vectors.py           write it
    python3 tools/pod_config_vectors.py --check   fail if it is stale

A sequence of CMD pod (opcode 10) packets' payloads as one pod takes them in order, starting from a pod
that was never configured: each step has the params, the CMD's CBOR bytes (to node 7), what the pod says
(applied, same, stale, refused) and the settings it keeps after it. The answers come from
controller/atalaia_controller/pod_config.py's PodSettingsModel; the pod's C (firmware/esp32/main/pod/
pod_settings.c, through tools/protogen.py's firmware/esp32/test/pod_config_vectors.h), the Pi controller
(controller/tests/test_pod_config.py) and the Android controller (app/test/controller/
controller_pod_config_test.dart) must agree with them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "controller"))
sys.path.insert(0, str(ROOT / "simulator"))
from atalaia_controller.pod_config import CMD_PARAMS_MAX, CMD_POD, PodSettingsModel  # noqa: E402
from atalaia_sim.packet import cmd_encode  # noqa: E402

OUT = ROOT / "protocol" / "vectors" / "pod_config.json"
DEST = 7

STEPS = [
    ("first_colours", "the first push: two buttons get a colour, the others follow the game",
     {"v": 1, "rev": 1, "btn": ["red", "", "", "blue"]}),
    ("same_rev_again", "the same rev again (the pod's ACK was lost): taken before, nothing changes",
     {"v": 1, "rev": 1, "btn": ["red", "", "", "blue"]}),
    ("other_settings", "another push changes other settings and keeps the colours",
     {"v": 1, "rev": 2, "bright": 60, "vol": 80, "tamper": False}),
    ("stale_rev", "an older rev (a delayed packet): ignored", {"v": 1, "rev": 1, "btn": ["green", "", "", ""]}),
    ("unknown_key", "a key this version does not know refuses the whole command",
     {"v": 1, "rev": 3, "bright": 10, "leds": 12}),
    ("bad_colour", "a colour the pod has no name for", {"v": 1, "rev": 3, "btn": ["red", "magenta", "", ""]}),
    ("three_buttons", "btn is exactly four colours", {"v": 1, "rev": 3, "btn": ["red", "blue", "green"]}),
    ("bright_too_high", "a percentage above 100", {"v": 1, "rev": 3, "bright": 101}),
    ("negative_volume", "a negative number", {"v": 1, "rev": 3, "vol": -1}),
    ("fractional_bright", "a number with a fraction", {"v": 1, "rev": 3, "bright": 50.5}),
    ("tamper_not_bool", "tamper is true or false", {"v": 1, "rev": 3, "tamper": 1}),
    ("newer_format", "a format newer than 1 is ignored, not guessed at", {"v": 2, "rev": 3, "bright": 10}),
    ("no_version", "v is required", {"rev": 3, "bright": 10}),
    ("no_rev", "rev is required", {"v": 1, "bright": 10}),
    ("rev_zero", "rev 0 is 'nothing pushed yet', never a push", {"v": 1, "rev": 0, "bright": 10}),
    ("reset_and_set", "reset drops every setting pushed so far, then sets the volume",
     {"v": 1, "rev": 3, "reset": True, "vol": 30}),
    ("reset_only", "reset alone: back to the build's settings", {"v": 1, "rev": 4, "reset": True}),
    ("largest", "everything at once with the longest values: 99 bytes, at most 127 fit",
     {"v": 1, "rev": 4294967295, "btn": ["purple", "orange", "yellow", "purple"], "bright": 100, "vol": 100,
      "tamper": False}),
]


def build() -> dict:
    model = PodSettingsModel()
    steps = []
    for name, note, params in STEPS:
        result = model.handle(params)
        text = json.dumps(params, separators=(",", ":"))
        assert len(text.encode()) <= CMD_PARAMS_MAX, name
        steps.append({"name": name, "note": note, "params": params, "cmd_cbor": cmd_encode(
            {"cmd": CMD_POD, "params": params, "dest": DEST}).hex(), "result": result, "stored": model.stored()})
    return {
        "description": "CMD pod (opcode 10): the I/O pod's settings pushed over the radio, as one pod takes them "
                       "in order from a pod never configured (decision PODC; protocol/pod-config.md). Made by "
                       "tools/pod_config_vectors.py; checked by firmware/esp32/test/test_pod_settings.c, "
                       "controller/tests/test_pod_config.py and app/test/controller/controller_pod_config_test.dart.",
        "opcode": CMD_POD,
        "dest": DEST,
        "version": 1,
        "steps": steps,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tools/pod_config_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
