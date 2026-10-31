<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Fonts of the project page

- `barlow-*.woff2`: Barlow and Barlow Condensed, latin subset; SIL OFL 1.1 ([LICENSES/OFL-1.1.txt](../../LICENSES/OFL-1.1.txt)).
- `twemoji-country-flags-subset.woff2`: the four language flags (🇵🇹 🇬🇧 🇩🇪 🇹🇼), because Chrome and Edge on
  Windows draw a flag emoji as two letters. The flag art is Twemoji's, **CC BY 4.0**
  ([LICENSES/CC-BY-4.0.txt](../../LICENSES/CC-BY-4.0.txt)), credited in every page's footer. The font is
  `dist/TwemojiCountryFlags.woff2` of npm `country-flag-emoji-polyfill` 0.1.10 (talkjs, MIT code; itself a
  subset of Mozilla's Twemoji Mozilla), subset by us (changed, as CC BY asks us to say) with
  `pyftsubset --text="🇵🇹🇬🇧🇩🇪🇹🇼" --layout-features="*" --flavor=woff2 --no-hinting` (fontTools, 78 KB to 7.8 KB).
  It is loaded by `style.css` with `unicode-range: U+1F1E6-1F1FF` (the regional-indicator letters), so no other text
  uses it, and is first in the font stack of `.lang .flag` only. To add a language, subset again with its flag.
