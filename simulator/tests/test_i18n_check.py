# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/i18n_check.py (plan phase 10, decisions P5H-1, P5H-2): every domain's languages against
English; a draft language may lack keys (a warning), never have one English lacks or another
placeholder; a complete one, or one checked with --strict, may lack none."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("i18n_check", REPO / "tools" / "i18n_check.py")
i18n_check = importlib.util.module_from_spec(SPEC)
sys.modules["i18n_check"] = i18n_check  # dataclasses look their module up
SPEC.loader.exec_module(i18n_check)

FILES = ("site/i18n", "controller/console/src/i18n", "simulator/atalaia_sim/editor/i18n", "app/lib/l10n",
         "firmware/esp32/main/box_text.c", "firmware/esp32/main/box_text.h",
         "server/atalaia_server/web/i18n.py", "server/atalaia_server/web/staff_i18n.py",
         "docs/translations/status.yaml")


class I18nCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in FILES:
            src, dst = REPO / name, self.root / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy(src, dst)
        for path in (REPO / "modes").glob("*/mode.yaml"):
            dst = self.root / "modes" / path.parent.name / "mode.yaml"
            dst.parent.mkdir(parents=True)
            shutil.copy(path, dst)

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            code = i18n_check.run(self.root, set(), set(), out=out) if not args else \
                i18n_check.main([*args, "--root", str(self.root)])
        return code, out.getvalue(), err.getvalue()

    def console(self, lang):
        path = self.root / "controller/console/src/i18n" / f"{lang}.json"
        return path, json.loads(path.read_text(encoding="utf-8"))

    def test_the_repository_passes(self):
        out = io.StringIO()
        with redirect_stderr(io.StringIO()) as err:
            code = i18n_check.run(REPO, set(), set(), out=out)
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("console", out.getvalue())
        self.assertIn("de: draft", out.getvalue())

    def test_every_domain_is_read(self):
        status = i18n_check.load_status(self.root)
        self.assertEqual(status["de"]["status"], "draft")
        box = i18n_check.read_box(self.root)
        self.assertEqual(set(box.tables), {"en", "pt", "de"})
        self.assertEqual(box.tables["de"]["TX_NEUTRAL_UP"], "FREI")
        self.assertEqual(box.tables["pt"]["TX_WAITING_UP"], "À ESPERA")
        self.assertEqual(box.tables["en"].keys(), box.tables["de"].keys())
        app = i18n_check.read_app(self.root)
        self.assertEqual(app.tables["de"]["settings.lang_de"], "Deutsch")
        self.assertEqual(app.tables["en"].keys(), app.tables["pt"].keys())

    def test_a_missing_german_key_is_a_warning(self):
        path, de = self.console("de")
        del de["game"]
        path.write_text(json.dumps(de), encoding="utf-8")
        code, out, _ = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("warning: controller/console/src/i18n/de.json", out)
        code, out, err = self.run_check("--missing", "de")
        self.assertEqual(code, 0)
        self.assertIn("missing in de (console)", out)
        # Before calling German complete: --strict, or status complete, make it an error.
        code, _, err = self.run_check("--strict", "de")
        self.assertEqual(code, 1)
        self.assertIn("missing", err)
        status = self.root / "docs/translations/status.yaml"
        status.write_text(status.read_text(encoding="utf-8").replace("status: draft", "status: complete"),
                          encoding="utf-8")
        self.assertEqual(self.run_check()[0], 1)

    def test_a_key_english_lacks_a_placeholder_or_an_empty_text_fails(self):
        path, de = self.console("de")
        de["app"]["no_such_key"] = "x"
        path.write_text(json.dumps(de), encoding="utf-8")
        code, _, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("app.no_such_key is not in English", err)
        de["app"].pop("no_such_key")
        de["app"]["lang_de"] = ""
        de["box_language"]["live"] = "Die Boxen: {sprache}"
        path.write_text(json.dumps(de), encoding="utf-8")
        code, _, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("app.lang_de is empty", err)
        self.assertIn("box_language.live has the placeholders", err)

    def test_portuguese_must_stay_complete(self):
        path, pt = self.console("pt")
        del pt["app"]["lang_de"]
        path.write_text(json.dumps(pt), encoding="utf-8")
        code, _, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("pt.json: 1 key(s) missing", err)

    def test_the_box_and_the_app(self):
        box = self.root / "firmware/esp32/main/box_text.c"
        text = box.read_text(encoding="utf-8")
        # A German column cell given back to English (NULL): a warning, as the box shows English.
        box.write_text(text.replace('"FREI"', "NULL"), encoding="utf-8")
        code, out, _ = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("warning: firmware/esp32/main/box_text.c: 1 key(s)", out)
        box.write_text(text.replace('"Spiel %u"', '"Spiel %s"'), encoding="utf-8")
        code, _, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("TX_GAME_N has the placeholders", err)
        box.write_text(text, encoding="utf-8")
        dart = self.root / "app/lib/l10n/strings_de.dart"
        dart.write_text(dart.read_text(encoding="utf-8").replace("'settings.lang_de': 'Deutsch',",
                                                                 "'settings.lang_de': 'Deutsch {x}',"),
                        encoding="utf-8")
        code, _, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("settings.lang_de has the placeholders", err)

    def test_a_language_not_in_the_status_file_fails(self):
        shutil.copy(self.root / "simulator/atalaia_sim/editor/i18n/en.json",
                    self.root / "simulator/atalaia_sim/editor/i18n/fr.json")
        code, _, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("'fr' is not in docs/translations/status.yaml", err)


if __name__ == "__main__":
    unittest.main()
