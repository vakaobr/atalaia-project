#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fails when a firmware build leaves too little static internal RAM for the heap.

    python tools/check_fw_ram.py firmware/esp32/build/atalaia_esp32.map [--min-free 122880]

Reads the linker map with ESP-IDF's esp_idf_size (run it where IDF's environment is exported: the
esp32-build job, or the espressif/idf image) and checks "diram_remain": the internal RAM the
image's static data and its RAM code leave to the heap (320 KB less .data, .bss and the code that
runs from RAM). Everything dynamic comes out of it: the task stacks (about 40 KB), the Wi-Fi driver
(about 47 KB of DMA-capable RAM at the start of a fetch), the Bluetooth controller (about 20 KB,
never together with Wi-Fi), the display's DMA draw buffers (30 KB) and the file system and
network buffers. The Field Box measured 45.7 KB left on 2026-10-29 (the box would not start its
Wi-Fi at a join) and 193.9 KB after its big buffers moved to PSRAM: the default threshold, 120 KiB,
keeps the Wi-Fi fetch and the beacon each with margin (about 70 KB of the runtime's needs above
what is measured) and fails a change that adds a 70 KB static buffer to internal RAM. Raise it when
the budget tightens; never lower it to let a change through (firmware/esp32/README.md, "Memory budget").
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("map_file")
    ap.add_argument("--min-free", type=int, default=120 * 1024, help="bytes (default 122880)")
    args = ap.parse_args()
    out = subprocess.run([sys.executable, "-m", "esp_idf_size", "--format", "json", args.map_file],
                         capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stdout + out.stderr, file=sys.stderr)
        return 2
    text = out.stdout
    sizes = json.loads(text[text.index("{"):])
    remain = int(sizes["diram_remain"])
    used = int(sizes["used_diram"])
    print(f"static internal RAM: {used} bytes used, {remain} bytes left for the heap "
          f"(at least {args.min_free} required)")
    if remain < args.min_free:
        print(f"check_fw_ram: FAILED, {args.min_free - remain} bytes short. Put big static buffers in "
              "PSRAM (ATALAIA_PSRAM_BSS, main/psram_attr.h) or shrink them; see firmware/esp32/README.md, "
              "\"Memory budget\".", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
