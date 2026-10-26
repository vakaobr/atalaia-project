# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/i18n_check.py (plan phase 10, decisions P5H-1, P5H-2): every domain's languages against
English; a draft language may lack keys (a warning), never have one English lacks or another
placeholder; a complete one, or one checked with --strict, may lack none."""

from __future__ import annotations

import importlib.util
import io
import json
import re
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
        self.assertIn("zh-tw: draft", out.getvalue())

    def test_every_domain_is_read(self):
        status = i18n_check.load_status(self.root)
        self.assertEqual(status["de"]["status"], "draft")
        box = i18n_check.read_box(self.root)
        self.assertEqual(set(box.tables), {"en", "pt", "de", "zh-tw"})
        self.assertEqual(box.tables["zh-tw"]["TX_NEUTRAL_UP"], "中立")
        self.assertEqual(box.tables["en"].keys(), box.tables["zh-tw"].keys())
        self.assertEqual(box.tables["de"]["TX_NEUTRAL_UP"], "FREI")
        self.assertEqual(box.tables["pt"]["TX_WAITING_UP"], "À ESPERA")
        self.assertEqual(box.tables["en"].keys(), box.tables["de"].keys())
        app = i18n_check.read_app(self.root)
        self.assertEqual(app.tables["de"]["settings.lang_de"], "Deutsch")
        # strings_zh_tw.dart's zhTwStrings is the language zh-tw (P5K-2).
        self.assertEqual(app.where["zh-tw"], "app/lib/l10n/strings_zh_tw.dart")
        self.assertEqual(app.tables["en"].keys(), app.tables["zh-tw"].keys())
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


GEN_SPEC = importlib.util.spec_from_file_location("gen_box_fonts", REPO / "tools" / "gen_box_fonts.py")
gen_box_fonts = importlib.util.module_from_spec(GEN_SPEC)
GEN_SPEC.loader.exec_module(gen_box_fonts)


class BoxFontCheckTests(unittest.TestCase):
    """tools/gen_box_fonts.py --check: the box's fonts carry exactly the Chinese letters of
    box_text.c (P5K-3), so a new text cannot use a letter the box would draw as an empty box."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in ("firmware/esp32/main/box_text.c", "firmware/esp32/main/box_text.h",
                     "firmware/esp32/main/fonts", "firmware/esp32/main/box_fonts_cjk.h"):
            src, dst = REPO / name, self.root / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy(src, dst)
        # The built-in modes' templates and scripts (P5H-12).
        for src in [*REPO.glob("modes/*/assets/screens/*.yaml"), *REPO.glob("modes/*/node.lua")]:
            dst = self.root / src.relative_to(REPO)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)
        self.box = self.root / "firmware/esp32/main/box_text.c"
        self.text = self.box.read_text(encoding="utf-8")

    def replace_in_templates(self, old: str, new: str) -> None:
        for path in self.root.glob("modes/*/assets/screens/*.yaml"):
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace(old, new), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def check(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stderr(err):
            code = gen_box_fonts.check(self.root, out=out)
        return code, out.getvalue(), err.getvalue()

    def test_the_repository_passes(self):
        code, out, err = self.check()
        self.assertEqual(code, 0, err)
        self.assertIn("48 px: ", out)

    def test_a_letter_the_fonts_lack_fails(self):
        # 閒 is in no box text: the fonts lack it at every size.
        self.box.write_text(self.text.replace('"中立"', '"閒置"'), encoding="utf-8")
        code, _, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn("lv_font_atalaia_14.c: lacks 閒", err)
        self.assertIn("lv_font_atalaia_48.c: lacks 閒", err)  # TX_NEUTRAL_UP is drawn at 48 px

    def test_a_letter_no_text_uses_any_more_fails(self):
        # 爆 is only in TX_EXPLODED_UP (48 px), TX_UNTIL_DETONATION and Bomb's and the objectives'
        # templates: without them the fonts carry it for nothing.
        text = self.text.replace('"已爆炸"', '"炸了"').replace('"後引爆"', '"後炸"')
        self.box.write_text(text, encoding="utf-8")
        self.replace_in_templates("已爆炸", "炸了")
        self.replace_in_templates("後引爆", "後炸")
        code, _, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn("has 爆 U+7206, which no box text or built-in template uses", err)

    def test_a_template_letter_the_fonts_lack_fails_at_its_size(self):
        # Domination's captured header is 20 px: 閒 would be needed there only (P5H-12).
        self.replace_in_templates("'據點已佔領'", "'閒置'")
        code, _, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn("lv_font_atalaia_20.c: lacks 閒 U+9592, which a box text or a built-in "
                      "template uses at 20 px", err)
        self.assertNotIn("lv_font_atalaia_14.c: lacks 閒", err)
        self.assertNotIn("lv_font_atalaia_48.c: lacks 閒", err)
        self.assertIn("box_fonts_cjk.h is not the fonts' Chinese letters", err)

    def test_a_letter_in_no_font_at_all_fails(self):
        # Polish l with stroke is neither in LATIN nor Chinese.
        self.box.write_text(self.text.replace('"FREI"', '"FREI\u0142"'), encoding="utf-8")
        code, _, err = self.check()
        self.assertEqual(code, 1)
        self.assertIn("add it to LATIN", err)


class OledNamesTests(unittest.TestCase):
    """The OLED's header is the mode's id and its middle line the template's name (oled_view.c):
    in German, Portuguese and Chinese every built-in mode and template has its name in the box's
    language (box_text.c's mode_names and screen_names), so a new mode or template cannot show
    the English id on the box's small screen unnoticed."""

    # The templates oled_view.c draws with a line of its own, or from its data (a countdown, the
    # zone's words, the final score), not by the template's name.
    OWN_LINE = {"countdown", "standby", "neutral", "captured", "final_score", "paused", "playing",
                "code_entry"}

    def names(self, table: str) -> set[str]:
        text = (REPO / "firmware/esp32/main/box_text.c").read_text(encoding="utf-8")
        body = text[text.index(f"{table}[] = {{"):]
        body = body[:body.index("};")]
        return set(re.findall(r'\{"([^"]+)", [A-Z_0-9]+\}', body))

    def test_every_built_in_template_has_a_name_or_its_own_line(self):
        mapped = self.names("screen_names")
        for path in sorted(REPO.glob("modes/*/assets/screens/*.yaml")):
            name = path.stem
            if name in self.OWN_LINE:
                continue
            self.assertIn(name, mapped, f"{path.relative_to(REPO)}: add '{name}' to screen_names "
                          "in firmware/esp32/main/box_text.c (the OLED shows it in English)")

    def test_every_built_in_mode_has_a_name_for_the_header(self):
        mapped = self.names("mode_names")
        for path in sorted(REPO.glob("modes/*/mode.yaml")):
            mode_id = path.read_text(encoding="utf-8").split("id: ", 1)[1].split()[0]
            # oled_mode_title(): the id's last part, capitals, "_" a space.
            key = mode_id.rsplit(".", 1)[-1].upper().replace("_", " ")
            self.assertIn(key, mapped, f"{path.relative_to(REPO)}: add '{key}' to mode_names in "
                          "firmware/esp32/main/box_text.c")


if __name__ == "__main__":
    unittest.main()
