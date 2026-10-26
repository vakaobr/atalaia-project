# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/bench_radio_log.py reads the line firmware/esp32/main/radio/radio_stats.c writes (decision SL-18).

The line below is the one test_radio_stats.c pins byte for byte; if the firmware's format changes,
both change together.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / "tools" / "bench_radio_log.py"
spec = importlib.util.spec_from_file_location("bench_radio_log", TOOL)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

FIRMWARE_LINE = (
    '{"t_s":120,"game":4243,"node":7,"sent":9,"retries":31,"acked":2,'
    '"expired":1,"relayed":140,"relay_skipped":12,"relay_cancelled":3,'
    '"relay_no_slot":4,"dup":77,"tx_refused":5,"duty_remaining_ms":359900,'
    '"neighbours":4,"rx":300,"rx_rejected":6,"states":40,"hellos":8,'
    '"final":0}'
)


def line(minute: int, **over) -> str:
    rec = json.loads(FIRMWARE_LINE)
    rec.update(t_s=minute * 60, sent=minute, acked=minute, retries=0, duty_remaining_ms=360000 - 500 * minute)
    rec.update(over)
    return f"I ({minute * 60000 + 5}) radio_stats: {json.dumps(rec, separators=(',', ':'))}\n"


class BenchRadioLogTest(unittest.TestCase):
    def test_parses_the_firmware_line(self):
        recs = tool.parse("\x1b[0;32mI (123456) radio_stats: " + FIRMWARE_LINE + "\x1b[0m\n")
        self.assertEqual(len(recs), 1)
        self.assertEqual((recs[0]["node"], recs[0]["tx_refused"], recs[0]["duty_remaining_ms"]), (7, 5, 359900))

    def test_skips_noise_and_torn_lines(self):
        text = "boot\n\x00\x01binary radio_stats: {\"t_s\":1,\"sent\n" + line(1) + "I (9) field: x\n"
        self.assertEqual(len(tool.parse(text)), 1)

    def test_summary_numbers(self):
        text = "".join(line(m, retries=m // 2, acked=m - 1 if m == 6 else m) for m in range(1, 7))
        out = tool.report(text)
        self.assertIn("retries per event 0.50", out)
        self.assertIn("acked 83.3 %", out)
        self.assertIn("slope -0.50 s/min", out)
        self.assertIn("empty in", out)
        self.assertIn("no row for 1 box", out)  # the study starts at 5

    def test_a_field_of_five_gets_the_models_row(self):
        text = "".join(line(m) for m in range(1, 4))
        out = tool.report(text, boxes=5)
        self.assertIn("5 boxes, EU868", out)
        self.assertIn("looks like the built rules", out)

    def test_a_reboot_starts_a_new_run(self):
        text = line(1) + line(2) + line(1) + line(2)
        runs = tool.split(tool.parse(text))
        self.assertEqual(sorted(len(v) for v in runs.values()), [2, 2])

    def test_modem_line(self):
        modem = (
            'I (5) radio_stats: {"role":"modem","t_s":60,"game":4243,"node":0,"rx_ok":50,'
            '"rx_dropped":4,"rx_auth_fail":1,"rx_dupes":30,"tx_ok":20,"tx_fail":2,'
            '"field_rx":45,"field_tx":19,"duty_remaining_ms":300000}\n'
        )
        out = tool.report(modem + line(1))
        self.assertIn("== modem", out)
        self.assertIn("tx 20 ok / 2 failed", out)

    def test_no_lines(self):
        self.assertIn("no radio_stats lines", tool.report("nothing\n"))


if __name__ == "__main__":
    unittest.main()
