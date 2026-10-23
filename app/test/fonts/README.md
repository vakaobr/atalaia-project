<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Test fonts

`NotoSansTC-Regular-subset.otf` and `NotoSansTC-Bold-subset.otf` draw the app's Traditional
Chinese (zh-tw) texts in the golden images. They are for the tests only: the app bundles no CJK
font, and on a phone Android's own CJK font draws Han characters, in its Traditional (Taiwan)
forms because the app's locale is `zh-Hant-TW`. A widget test has no system fonts, so
`test/support/fonts.dart` loads these under the name the theme falls back on
(`cjkFontFallback` in `lib/ui/theme.dart`).

They are subsets of Noto Sans TC 2.004 from
[notofonts/noto-cjk](https://github.com/notofonts/noto-cjk) (`Sans/SubsetOTF/TC/`, tag
`Sans2.004`), © 2014-2021 Adobe, under the SIL Open Font License 1.1
([`LICENSES/OFL-1.1.txt`](../../../LICENSES/OFL-1.1.txt); `REUSE.toml`). The originals' SHA-256:

| File | SHA-256 |
|---|---|
| `NotoSansTC-Regular.otf` | `5bab0cb3c1cf89dde07c4a95a4054b195afbcfe784d69d75c340780712237537` |
| `NotoSansTC-Bold.otf` | `55420b259eb119bf5f2a0aadba10cf9d736c12d64ab93e78546d69ef5f43558b` |

Each subset has the characters of `lib/l10n/strings_zh_tw.dart` and of the built-in modes'
files, `lib/modes/builtin_modes.g.dart` (their zh-tw names, labels and screens, which the prop
and setup goldens show; decision P5H-12). When a Chinese text gains a character they lack, `test/l10n/cjk_font_test.dart` names it; make them again from `app/` with
fontTools 4.55 (`pip install fonttools==4.55.3`):

```sh
cat lib/l10n/strings_zh_tw.dart lib/modes/builtin_modes.g.dart > /tmp/zh-tw-chars.txt
for w in Regular Bold; do
  pyftsubset NotoSansTC-$w.otf --text-file=/tmp/zh-tw-chars.txt \
    --layout-features='*' --no-hinting --desubroutinize \
    --output-file=test/fonts/NotoSansTC-$w-subset.otf
done
```

then draw the golden images again (`python3 tools/docker_app.py goldens`) and look at them.
