<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Project page

The project page at <https://vakaobr.github.io/atalaia-project/>. It is static HTML and CSS: no
JavaScript, no cookies, nothing loaded from other sites. The
[Pages workflow](../.github/workflows/pages.yml) publishes this folder on every push to `main`
that changes it, leaving out `src/`, `i18n/` and this README.

| Path | What it is |
| --- | --- |
| `index.html` | The Portuguese (pt-PT) page, the default at the site root. Generated |
| `en/index.html` | The English page, at `/en/`. Generated |
| `style.css`, `favicon.svg` | Shared by both pages |
| `img/` | The badge and illustrations (see [Images](#images)) |
| `img/diagrams/` | The two radio diagrams in each language and layout. Generated (see [Diagrams](#diagrams)) |
| `fonts/` | Barlow and Barlow Condensed (latin subset, WOFF2), self-hosted so the page loads nothing from other sites; SIL OFL 1.1, see [LICENSES/OFL-1.1.txt](../LICENSES/OFL-1.1.txt) |
| `style.css` | The look: slate, sand and signal orange taken from the badge, with the hero's hills and tower drawn in inline SVG |
| `src/index.html` | The template both pages are built from |
| `src/diagrams/` | The templates of the radio diagrams |
| `i18n/pt.yaml`, `i18n/en.yaml` | The text of each page |

## Images

The Atalaia badge and the two illustrations were made by the project maintainer with Google
Gemini image generation. `img/` holds web-optimized copies, under the same CC BY-SA 4.0 licence as
the rest of this folder (see [REUSE.toml](../REUSE.toml)); the top-level README uses them too.

| Files | What they are | Where they appear |
| --- | --- | --- |
| `logo-1024.png`, `logo-512.png`, `logo-192.png` | The round badge: watchtowers with signal fires on dunes | The Name section of both pages, the apple-touch-icon (192), the top of the README. The header keeps the small SVG mark and `favicon.svg`, as the badge is too detailed at that size |
| `watchtower-night-960/1600` (`.jpg`, `.webp`) | Night scene: a hilltop watchtower linked to GAME PROP boxes across a valley, with the English text "Open-source project ATALAIA" painted in | Hero of the English page only, because of that text; the README banner |
| `field-isometric-960/1600` (`.jpg`, `.webp`) | Isometric stone tower ringed by GAME PROP cases | Hero of the Portuguese page; "How it fits together" on the English page |
| `og-pt.jpg`, `og-en.jpg` | 1200 × 630 social previews (`og:image`) | Link previews of each page |

Each page loads only its own hero image (WebP, with JPEG for older browsers, at 960 or 1600 pixels
wide as the screen needs) and lazy-loads everything below it.

## Translating the page

Never edit `index.html` or `en/index.html` by hand. Change the template or the text files, then
rebuild both pages from the repository root:

```sh
python3 tools/build_site.py
```

It needs Python 3 and PyYAML (the dev container has both: see [tools/README.md](../tools/README.md)).

- Text that is the same in every language, such as the code blocks, product names and links,
  stays in the template. Everything else is a key in the YAML files, and the template inserts it
  with `{{ key }}` (as HTML) or `{{ key|text }}` (escaped, for attributes and the diagram).
- Every key must be in both `pt.yaml` and `en.yaml`, and every key must be used by the template,
  apart from the keys of single-language parts (next point).
  Both pages must link to the same external addresses.
- A part that only one language shows, such as the night scene with English text in it, goes
  between `{% if lang en %}` and `{% endif %}` lines in the template. Its keys then live only in
  that language's file.
- Links to the repository's documents point at the English documents in both languages; the
  Portuguese page says "(em inglês)" next to them.
- The language switcher in the header names each language in its own language, and its links are
  relative, so the pages work both on GitHub Pages and from a local server
  (`python3 -m http.server -d site`).

CI runs `python3 tools/build_site.py --check`, which fails if a page or a diagram is out of date,
a translation is missing a key or does not fit its diagram, or a `#` link has no matching id on
its page. `tools/check.sh` runs the same check.

### Diagrams

The radio diagrams ("How the radio works": `lora` and `skirmesh`) are drawn by hand in SVG in
`src/diagrams/`, with placeholders for their text, which lives under `diagrams:` in the language
files (plain text, not HTML). `build_site.py` writes each one per language and layout to
`img/diagrams/<name>-<layout>-<language>.svg`: `wide` (two columns, for desktops and the README)
and `narrow` (one column, which the page shows on screens up to 760 px wide). Lines between
`{% if layout wide %}` and `{% endif %}` belong to one layout. The page uses each diagram's
`desc` as its alt text.

An SVG shown as an image cannot use the page's fonts, so most readers see their system's sans
serif instead of Barlow. Each translated text therefore declares its room: `data-width` on its
`<text>`, and for `{{ key|wrap }}` also `data-lines`. The build wraps the text at spaces and fails
if a line would be too wide in the widest common fallback font (DejaVu Sans), naming the key and
the line: shorten the translation, or give it more room in the template. Each diagram has an
opaque light background, so it reads on dark pages too, and its colours are the page's.

### Plain words and the glossary

The page is written for players, field owners and GMs who are not engineers. When a technical
term first appears, say what it is in a few plain words ("LoRa mesh (long-range, low-power
radio...)"), and link the harder ones to the glossary near the end of the page.

- Each glossary entry has `id`, `term` and `text` keys under `glossary` in both files. The ids
  are ASCII and differ by language (`glossario-lora` on the Portuguese page, `glossary-lora` on
  the English one); keep them stable, since other sites may link to them, and change a link
  whenever you change an id.
- A glossary text is one to three sentences: what the thing is, and why Atalaia uses it.
- Check each claim against the [design specification](../docs/design-spec.md). Prices are the
  spec's approximate figures, and anything not built yet (the field controller, the API, Android
  props, the player app, the site server) is written as "will".

### Portuguese terms

The Portuguese text is European Portuguese, written the way Portuguese airsoft and paintball
players write. Keep these choices consistent when you edit it:

| English | Portuguese |
| --- | --- |
| props | dispositivos (de jogo); caixas for the boxes. "Props" appears only in the introduction and in the glossary term |
| GM, organisers | organização; GM console is "consola da organização" |
| field | campo |
| site server | servidor do clube |
| field controller | controlador de campo |
| chrono, chrono check-in | cronografagem, cronografagem à entrada |
| milsim, CQB, respawn, makers, copyleft, squad | unchanged ("esquadra" is a police station) |
| presets | predefinições |
| Domination, Bomb | Domínio, Bomba |
| gate (of a roadmap phase) | prova |
| glossary | glossário |
| How a game works | Como funciona um jogo |
| local-first | funciona sem internet; "local-first" only in the glossary term |
| microcontroller | microcontrolador |
| firmware, flashing | firmware, gravar (o) firmware |
| I/O pod, pod | módulo de E/S (entrada e saída), módulo |
| thin node | nó simples |
| shared core | núcleo partilhado |
| mesh | rede mesh |
| simulator | simulador |
| scoreboard, stream (overlay) | marcador, transmissão em direto |
| open source, free software | código aberto, software livre |
| marshal | "marshal", as Portuguese players say it at games |

Product and technical names stay as they are: Atalaia, Skirmesh-RF, Field Box, LoRa, ESP32,
Raspberry Pi, Arduino, Android, Lua, MQTT, REST, WebSocket, ATAK, GitHub.
