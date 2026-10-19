<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Project page

The project page at <https://atalaia-project.link/>. It is static HTML and CSS: no
JavaScript, no cookies, nothing loaded from other sites. The
[Pages workflow](../.github/workflows/pages.yml) publishes this folder on every push to `main`
that changes it, leaving out `src/`, `i18n/` and this README.

## Pages

A short main page, and a page of its own for each long section. Portuguese (pt-PT) is the default
language, at the site root; English is under `/en/`. Every page exists in both languages, and its
folder is named in its language:

| Page | Portuguese | English | Template | What it holds |
| --- | --- | --- | --- | --- |
| Main page | `/` | `/en/` | `src/index.html` | The hero, how a game works, why Atalaia, how it fits together, a short radio section, three game modes, the screenshots, try it, the roadmap in one line per phase, the community hub, getting involved, the name and field safety |
| Game modes | `/modos/` | `/en/modes/` | `src/modes.html` | Every mode, the Codes modifier, the Medic Kit and "your mode" |
| Radio | `/radio/` | `/en/radio/` | `src/radio.html` | How the radio works: both diagrams with their lead-ins, and the channel |
| Roadmap | `/roadmap/` | `/en/roadmap/` | `src/roadmap.html` | The six phases in full, with their gates. "Roadmap" stays in English in Portuguese too |
| Glossary | `/glossario/` | `/en/glossary/` | `src/glossary.html` | Every glossary entry; the glossary links of every page lead here |

| Path | What it is |
| --- | --- |
| `index.html`, `<folder>/index.html` | The Portuguese pages. Generated |
| `en/index.html`, `en/<folder>/index.html` | The English pages. Generated |
| `sitemap.xml` | Every page in both languages, each with its translations (`hreflang`). Generated |
| `style.css`, `favicon.svg` | Shared by every page |
| `img/` | The badge and illustrations (see [Images](#images)) |
| `img/diagrams/` | The two radio diagrams in each language and layout. Generated (see [Diagrams](#diagrams)) |
| `fonts/` | Barlow and Barlow Condensed (latin subset, WOFF2), self-hosted so the page loads nothing from other sites; SIL OFL 1.1, see [LICENSES/OFL-1.1.txt](../LICENSES/OFL-1.1.txt) |
| `style.css` | The look: slate, sand and signal orange taken from the badge, with the hero's hills and tower drawn in inline SVG (the subpages' heads reuse the hills) |
| `src/<page>.html` | The template of each page, built in both languages |
| `src/partials/` | The parts every page shares: `head.html` (title, description, canonical and `hreflang` addresses, social preview tags), `header.html` (navigation and language switcher) and `footer.html` |
| `src/diagrams/` | The templates of the radio diagrams |
| `i18n/pt.yaml`, `i18n/en.yaml` | The text of every page, one file per language |

### Old links and anchors

The main page used to hold the whole site, so other sites may link to its anchors. GitHub Pages
has no server-side redirects, and the pages use no JavaScript, so old anchors are kept where a
short version of their section stays: `/#roadmap`, `/#modes` and `/#radio` (and their `/en/`
twins) still land on the main page's short sections, each with a link to its page. The old
glossary anchors (`/#glossario-lora`, `/en/#glossary-lora`) now only open the main page; the
glossary page keeps the same ids (`/glossario/#glossario-lora`), so a link moves to the new page
and keeps its id. Keep these ids, the page folders in `PAGES` and the glossary ids stable.

## Images

The Atalaia badge and the two illustrations were made by the project maintainer with Google
Gemini image generation. `img/` holds web-optimized copies, under the same CC BY-SA 4.0 licence as
the rest of this folder (see [REUSE.toml](../REUSE.toml)); the top-level README uses them too.

| Files | What they are | Where they appear |
| --- | --- | --- |
| `logo-1024.png`, `logo-512.png`, `logo-192.png` | The round badge: watchtowers with signal fires on dunes | The Name section of both main pages, the apple-touch-icon (192), the top of the README. The header keeps the small SVG mark and `favicon.svg`, as the badge is too detailed at that size |
| `watchtower-night-960/1600` (`.jpg`, `.webp`) | Night scene: a hilltop watchtower linked to GAME PROP boxes across a valley, with the English text "Open-source project ATALAIA" painted in | Hero of the English main page; the README banner |
| `watchtower-night-pt-960/1600` (`.jpg`, `.webp`) | The same night scene with its text in Portuguese, "Projeto de código aberto ATALAIA" | Hero of the Portuguese main page |
| `field-isometric-960/1600` (`.jpg`, `.webp`) | Isometric stone tower ringed by GAME PROP cases | "How it fits together" on the English main page |
| `og-pt.jpg`, `og-en.jpg` | 1200 × 630 social previews (`og:image`) | Link previews of every page in that language |

Each main page loads only its own hero image (WebP, with JPEG for older browsers, at 960 or 1600
pixels wide as the screen needs) and lazy-loads everything below it.

## Translating the pages

Never edit the generated pages (`index.html`, `en/index.html`, `modos/index.html`...) or
`sitemap.xml` by hand. Change the templates or the text files, then rebuild every page from the
repository root:

```sh
python3 tools/build_site.py
```

It needs Python 3 and PyYAML (the dev container has both: see [tools/README.md](../tools/README.md)).

- Text that is the same in every language, such as the code blocks, product names and links,
  stays in the templates. Everything else is a key in the YAML files, and a template inserts it
  with `{{ key }}` (as HTML) or `{{ key|text }}` (escaped, for attributes and the diagram). One
  key can appear on several pages: the main page's three mode cards and the modes page share
  their keys.
- Every key must be in both `pt.yaml` and `en.yaml`, and every key must be used by some template,
  partial or diagram, apart from the keys of single-language parts (next point).
  Both languages' versions of a page must link to the same external addresses.
- Each page's `<title>` and description are `meta.<page>.title` and `meta.<page>.description`
  (and optionally `meta.<page>.og_description` for link previews); `meta.og_image_alt` is shared.
- Links between the pages are relative, so the site works on GitHub Pages and from a local
  server. A template writes `{{ page.to.<page> }}` (`{{ page.to.glossary }}`,
  `{{ page.to.index }}#try`); a text in the YAML files can hold the same values, which the build
  fills in for the page that shows it. Write a page link with its trailing `/`.
- A part that only one language shows, such as the night scene with English text in it, goes
  between `{% if lang en %}` and `{% endif %}` lines in the template. Its keys then live only in
  that language's file.
- Links to the repository's documents point at the English documents in both languages; the
  Portuguese page says "(em inglês)" next to them.
- The language switcher in the header names each language in its own language and leads to the
  same page in the other language. Try the site with a local server
  (`python3 -m http.server -d site`).

CI runs `python3 tools/build_site.py --check`, which fails if a page, a diagram or the sitemap is
out of date; if a translation is missing a key, has one no page uses, or does not fit its
diagram; if a link, image or address on any page leads to no page or published file, or its `#id`
is not on the page it leads to; if the two languages' versions of a page link to different
external addresses; if a page of the page table is missing in a language, or a template or
partial is unused; or if the site holds a generated page or diagram that nothing makes any more
(delete it, or restore its page). `tools/check.sh` runs the same check.

### Adding a page

1. Add it to `PAGES` in `tools/build_site.py`: its name and its folder in each language (a
   lowercase ASCII slug in that language, ending in `/`; `"roadmap/"` in both).
2. Write `src/<name>.html`. Copy an existing subpage such as `src/roadmap.html`: it includes
   `head`, `header` and `footer`, and opens with a `page-head` section (its `h1` and lead) and a
   `content` block whose headings are `h2`.
3. Add `meta.<name>.title` and `meta.<name>.description`, and the page's text, to both
   `pt.yaml` and `en.yaml`.
4. Link to it: from the header (`src/partials/header.html`, with `{{ page.nav.<name> }}` to mark
   it as the current page) and wherever the main page shortens its section.
5. Run `python3 tools/build_site.py`: it writes both languages and adds the page to
   `sitemap.xml`. Renaming or removing a page leaves its old files behind; the build names them,
   and you delete them.

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

The pages are written for players, field owners and GMs who are not engineers. When a technical
term first appears, say what it is in a few plain words ("LoRa mesh (long-range, low-power
radio...)"), and link the harder ones to the glossary page:
`<a href="{{ page.to.glossary }}#glossary-lora">`.

- Each glossary entry has `id`, `term` and `text` keys under `glossary` in both files. The ids
  are ASCII and differ by language (`glossario-lora` on the Portuguese glossary page,
  `glossary-lora` on the English one); keep them stable, since other sites may link to them, and
  change a link whenever you change an id.
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
| team | equipa (the side, always there); a squad is a group within a team |
| presets | predefinições |
| Domination, Bomb | Domínio, Bomba |
| roadmap | Roadmap, unchanged, as it is known in Portugal (never "Roteiro"); its page is `/roadmap/` |
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
