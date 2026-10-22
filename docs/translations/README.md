<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Translating Atalaia

Atalaia is written in English first and ships in European Portuguese, with German (plan
phase 10 of phase 5, decisions P5H-1 to P5H-11) and Traditional Chinese as written in Taiwan
(`zh-tw`, plan phase 11, decisions P5K-1 to P5K-12) being reviewed; both are in
[`docs/review/decisions-to-review.md`](../review/decisions-to-review.md). Translations are
welcome for any language people play in; you do not need to write code.

| File | What it is |
|---|---|
| [`status.yaml`](status.yaml) | Every language, its state (`complete` or `draft`) and who reviewed it |
| [`glossary.md`](glossary.md) | One word for one thing, per language: read it before translating |
| [`tools/i18n_check.py`](../../tools/i18n_check.py) | Checks every translation against English (CI runs it in `tools/check.sh`) |

## Where the texts are

Each part keeps the format it was built with (decision P5R-11); the keys are the same as
English's in every language.

| Part | English | Format | Notes |
|---|---|---|---|
| Project page | [`site/i18n/en.yaml`](../../site/i18n/en.yaml) | YAML, values are HTML | Must be complete: `tools/build_site.py` builds every page in every language and fails on a missing key. Diagram texts have a width; see [site/README.md](../../site/README.md) |
| GM console | [`controller/console/src/i18n/en.json`](../../controller/console/src/i18n/en.json) | nested JSON, `{name}` placeholders | Also the scoreboard, the poster and the field map |
| Mode editor | [`simulator/atalaia_sim/editor/i18n/en.json`](../../simulator/atalaia_sim/editor/i18n/en.json) | JSON (`ui`, `blocks`), `%1` inputs and `{name}` | A block's text is a sentence with its inputs; their order may change. Blockly's own texts come from its `msg/<lang>.js` (vendored, checksummed) |
| App | [`app/lib/l10n/strings_en.dart`](../../app/lib/l10n/strings_en.dart) | Dart map, `{name}` placeholders | Long texts are split over adjacent literals |
| Field Box screens | [`firmware/esp32/main/box_text.c`](../../firmware/esp32/main/box_text.c) | one C table, one column a language, `%s`/`%u`/`%ld` | The OLED's lines (`TXO_*`) have 16 columns, a Han letter taking two; the screens are checked by reference images. Letters outside the box's fonts need new glyphs: Latin ones in `LATIN` of `tools/gen_box_fonts.py`; Chinese ones are taken from the table itself, so after changing a Chinese text make the fonts again (`python3 tools/gen_box_fonts.py --check`, in CI, names a missing or unused letter; P5K-3) |
| Modes | `modes/<mode>/mode.yaml` | `i18n.<lang>:` name, description, parameter labels, commands | No German or Chinese yet (P5H-7, P5K-1) |
| Site server pages | `server/atalaia_server/web/i18n.py`, `staff_i18n.py` | Python dicts | Portuguese and English only (P5H-8) |

A language's code is the same everywhere (`status.yaml`, the console's `LANGS`, the join's key
15): `de`, and `zh-tw` for Traditional Chinese (Taiwan). Files carry it as they can: `zh-tw.json`,
`zh-tw.yaml`, `strings_zh_tw.dart` with the map `zhTwStrings`, `BOX_LANG_ZH_TW`; the pages say
`lang="zh-Hant-TW"`.

## Rules

- Write as players of your language speak at the field: German airsoft players say
  *Respawn*, *Medic*, *Marshal*, *Squad*, *Team*, *Domination*; Portuguese players say
  *respawn* and *marshal* too. The glossary lists them.
- Name people without a gendered form where your language has a natural neutral one
  (Portuguese "quem joga", German "Spielende", "die Orga"); keep it readable.
- Keep every placeholder exactly (`{team}`, `%1`, `%s`, `{{ page.to.glossary }}`); you may
  move it in the sentence.
- Keep texts short where the English is short: buttons, tabs, the box's screens.
- Decimal separators, quotation marks and dates as your language writes them.
- Chinese, Japanese or Korean: the box's fonts carry only the letters its texts use, the OLED
  draws them at 14 px on one bit per pixel (prefer common letters with few strokes in its
  `TXO_*` lines), and lines break between letters, never before a closing or after an opening
  full-width sign (P5K-6).

## Adding or finishing a language

1. Add the language to [`status.yaml`](status.yaml) as `draft`, with who drafted it (a person,
   or "an AI model" / "machine translation": say so, decision P5H-5).
2. Add a column to [`glossary.md`](glossary.md) and agree the words with other players of
   the language (a GitHub Discussion is a good place).
3. Copy each English file to your language's name and translate it (`de.json`,
   `strings_de.dart` with `deStrings`, a column in `box_text.c`...). A part you do not
   translate yet is simply left out: the console, the editor, the app and the box show English
   for any text a language lacks.
4. Wire the language into each part's language list (once per language, a maintainer can do
   it): `LANGS` in `controller/console/src/ui.js` and `simulator/atalaia_sim/editor/editor.js`
   (with Blockly's `msg/<lang>.js` vendored, checksum in its README; `BLOCKLY_MSG` maps a
   code Blockly names otherwise, as `zh-tw` to `zh-hant`), `AppLanguage` in
   `app/lib/l10n/strings.dart`, `LANGUAGES` and `PAGES` in `tools/build_site.py` (the pages'
   folders are named in the language, or in English where its letters would be
   percent-encoded, as Chinese's, P5K-9), `box_lang_t` and `box_lang_from_code` in
   `firmware/esp32/main/box_text.c` and `BOX_LANGUAGES` in the controller (join key 15 carries
   any 2-8 letter code; older boxes show English).
5. Run `python3 tools/i18n_check.py --missing <lang>` to see what is left, and the checks of
   each part you touched (see [CONTRIBUTING.md](../../CONTRIBUTING.md)).
6. A native speaker who plays reviews the whole language with the glossary, in the running
   app, console and box screens (the reference images under `firmware/esp32/test/screens/`,
   `*_de.png` for German, `*_zh-tw.png` for Traditional Chinese). Then `status: complete`, `reviewed_by:` and
   `python3 tools/i18n_check.py --strict <lang>` must pass: from then on a missing key fails CI.

New English texts are added with their Portuguese in the same change; other languages may
follow later (the check lists them as warnings, never failures, while a language is `draft`).
