<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Fonts of the project page

- `barlow-*.woff2`: Barlow and Barlow Condensed, the latin subset (`barlow-latin-*`, `barlow-condensed-latin-*`) and,
  for Polish (ą ć ę ł ń ś ź ż) and other Latin Extended letters, the latin-ext subset (`*-latin-ext-*`); SIL OFL 1.1
  ([LICENSES/OFL-1.1.txt](../../LICENSES/OFL-1.1.txt)). Unchanged `files/*.woff2` of npm `@fontsource/barlow` and
  `@fontsource/barlow-condensed` 5.2.8 (the latin files are byte-identical to that release). `style.css` gives the
  latin-ext faces Fontsource's `unicode-range`, so only a page that uses such a letter downloads them (SITE-PL-2).
- `twemoji-country-flags-subset.woff2`: the five language flags (🇵🇹 🇬🇧 🇩🇪 🇹🇼 🇵🇱), because Chrome and Edge on
  Windows draw a flag emoji as two letters. The flag art is Twemoji's, **CC BY 4.0**
  ([LICENSES/CC-BY-4.0.txt](../../LICENSES/CC-BY-4.0.txt)), credited in every page's footer. The font is
  `dist/TwemojiCountryFlags.woff2` of npm `country-flag-emoji-polyfill` 0.1.10 (talkjs, MIT code; itself a
  subset of Mozilla's Twemoji Mozilla), subset by us (changed, as CC BY asks us to say) with
  `pyftsubset --text="🇵🇹🇬🇧🇩🇪🇹🇼🇵🇱" --layout-features="*" --flavor=woff2 --no-hinting` (fontTools, 78 KB to 9.4 KB; the
  four-flag subset made this way was byte-identical to the previous file).
  It is loaded by `style.css` with `unicode-range: U+1F1E6-1F1FF` (the regional-indicator letters), so no other text
  uses it, and is first in the font stack of `.lang .flag` only. To add a language, subset again with its flag.
