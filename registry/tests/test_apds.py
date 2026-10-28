# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The list of APDs (registry/apds/apds.json, protocol/apd.md): its entries follow the schema's rules, and the copies
the server, the Pi controller and the app ship are byte for byte the registry's."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "registry" / "apds" / "apds.json"
COPIES = ("server/atalaia_server/data/apds.json", "controller/atalaia_controller/data/apds.json", "app/assets/apds.json")
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
URL = re.compile(r"https://\S{1,120}")


class ApdList(unittest.TestCase):
    def test_entries(self):
        doc = json.loads(SOURCE.read_text(encoding="utf-8"))
        self.assertEqual(set(doc) - {"note"}, {"format", "apds"})
        self.assertEqual(doc["format"], 1)
        ids = []
        for e in doc["apds"]:
            self.assertEqual(set(e), {"id", "name", "short_name", "website", "source"})
            self.assertTrue(ID.fullmatch(e["id"]), e["id"])
            self.assertFalse(e["id"].startswith("x-"), "x- is reserved for a field's own entries")
            self.assertTrue(1 <= len(e["name"]) <= 96 and 1 <= len(e["short_name"]) <= 16)
            self.assertTrue(e["website"] is None or URL.fullmatch(e["website"]))
            self.assertTrue(URL.fullmatch(e["source"]), "every entry cites its official source")
            ids.append(e["id"])
        self.assertEqual(ids, sorted(ids), "alphabetical order of id")
        self.assertEqual(len(ids), len(set(ids)))

    def test_copies_are_identical(self):
        want = SOURCE.read_bytes()
        for rel in COPIES:
            self.assertEqual((ROOT / rel).read_bytes(), want, rel)


if __name__ == "__main__":
    unittest.main()
