<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Project page

nothing loaded from other sites, and two small inline scripts, the header menus' Escape and click-outside (the menus are `<details>` and work without it) and the main page's screenshot viewer
nothing loaded from other sites, and one small inline script, the main page's screenshot viewer
(see [Screenshots](#screenshots)), without which every page still works. The
[Pages workflow](../.github/workflows/pages.yml) publishes this folder on every push to `main`
that changes it, leaving out `src/`, `i18n/` and this README.

## Pages

A short main page, and a page of its own for each long section. Portuguese (pt-PT) is the default
language, at the site root; English is under `/en/`, German under `/de/` (decision P5H-3) and
Traditional Chinese as written in Taiwan under `/zh-tw/` (plan phase 11); both drafted by an AI model
and waiting for a native speaker's review ([docs/translations/](../docs/translations/README.md)).
Every page exists in every language, and its folder is named in its language, except in Chinese,
which keeps English's ASCII folders (Han letters in an address are percent-encoded when shared):

| Page | Portuguese | English | German | Chinese | Template | What it holds |
| --- | --- | --- | --- | --- | --- | --- |
| Main page | `/` | `/en/` | `/de/` | `/zh-tw/` | `src/index.html` | The hero, how a game works, why Atalaia, how it fits together, a short radio section, three game modes, the screenshots, try it, the roadmap in one line per phase, the community hub, getting involved, the name and field safety |
| Game modes | `/modos/` | `/en/modes/` | `/de/modi/` | `/zh-tw/modes/` | `src/modes.html` | Every mode, the Codes modifier, the Medic Kit and "your mode" |
| Radio | `/radio/` | `/en/radio/` | `/de/funk/` | `/zh-tw/radio/` | `src/radio.html` | How the radio works: both diagrams with their lead-ins, and the channel |
| Roadmap | `/roadmap/` | `/en/roadmap/` | `/de/roadmap/` | `/zh-tw/roadmap/` | `src/roadmap.html` | The six phases, each as a one-line summary, bullets of what is done (the long lists fold into a `<details>`), bullets of what is next or waiting, and its gate, with a link to the phase's `STATUS.md`. "Roadmap" stays in English in Portuguese too |
| Build guides | `/montagem/` | `/en/build-guides/` | `/de/bauen/` | `/zh-tw/build-guides/` | `src/build.html` | Safety rules for every build; the Satellite, the I/O pod and the target addon shortened from `hardware/<node>/BUILD.md` (the full guides, in English), with their pin tables and photo placeholders; a pointer to the Field Box's build manual (phase 5 plan phase 12, decisions P5J-1 to P5J-13) |
| How it fits together | `/como-se-liga/` | `/en/how-it-fits/` | `/de/zusammenspiel/` | `/zh-tw/how-it-fits/` | `src/architecture.html` | The seven architecture diagrams of `docs/architecture.md` as SVG, each with a short "what flows / what does not" text and a link to the doc (decision SITEARCH-1). Linked from the navigation, the roadmap and the build guides |
| Glossary | `/glossario/` | `/en/glossary/` | `/de/glossar/` | `/zh-tw/glossary/` | `src/glossary.html` | Every glossary entry; the glossary links of every page lead here |

| Path | What it is |
| --- | --- |
| `index.html`, `<folder>/index.html` | The Portuguese pages. Generated |
| `en/index.html`, `en/<folder>/index.html` | The English pages. Generated |
| `de/index.html`, `de/<folder>/index.html` | The German pages. Generated |
| `zh-tw/index.html`, `zh-tw/<folder>/index.html` | The Traditional Chinese (Taiwan) pages. Generated |
| `sitemap.xml` | Every page in every language, each with its translations (`hreflang`). Generated |
| `style.css`, `favicon.svg` | Shared by every page |
| `img/` | The badge and illustrations (see [Images](#images)) |
| `img/wiring/` | The Field Box's two wiring drawings, copied from `hardware/field-box/wiring/` by `tools/build_site.py` (see [The build guides page](#the-build-guides-page)). Generated |
| `img/diagrams/` | The two radio diagrams in each language and layout. Generated (see [Diagrams](#diagrams)) |
| `fonts/` | Barlow and Barlow Condensed (latin subset, WOFF2; SIL OFL 1.1, see [LICENSES/OFL-1.1.txt](../LICENSES/OFL-1.1.txt)) and a four-flag subset of Twemoji Country Flags for the language switcher (CC BY 4.0, credited in the footer), all self-hosted so the page loads nothing from other sites; see [fonts/README.md](fonts/README.md) |
| `style.css` | The look: slate, sand and signal orange taken from the badge, with the hero's hills and tower drawn in inline SVG (the subpages' heads reuse the hills) |
| `src/<page>.html` | The template of each page, built in every language |
| `src/partials/` | The parts every page shares: `head.html` (title, description, canonical and `hreflang` addresses, social preview tags), `header.html` (navigation and language switcher) and `footer.html` |
| `src/diagrams/` | The templates of the radio diagrams |
| `i18n/pt.yaml`, `i18n/en.yaml`, `i18n/de.yaml`, `i18n/zh-tw.yaml` | The text of every page, one file per language |

### Old links and anchors

The main page used to hold the whole site, so other sites may link to its anchors. GitHub Pages
has no server-side redirects, and the pages do not redirect with JavaScript, so old anchors are kept where a
short version of their section stays: `/#roadmap`, `/#modes` and `/#radio` (and their `/en/`
twins) still land on the main page's short sections, each with a link to its page. The old
glossary anchors (`/#glossario-lora`, `/en/#glossary-lora`) now only open the main page; the
glossary page keeps the same ids (`/glossario/#glossario-lora`), so a link moves to the new page
and keeps its id. Keep these ids, the page folders in `PAGES` and the glossary ids stable.

## Architecture diagrams (Mermaid)

The diagrams on the "How it fits together" page are the Mermaid diagrams of `docs/architecture.md`,
drawn once per language:

- `src/diagrams/arch-<n>-<name>.mmd` is the diagram with every label a `{{ arch.tNNN }}` key of
  `i18n/*.yaml`. Filled in with the English texts it is the doc's block exactly, and `build_site.py --check`
  fails if it is not, so the doc (for GitHub) and the page cannot show different diagrams. To change a
  diagram, change the doc block, the template and the labels together.
- Mermaid cannot run in CI, so `python3 tools/render_diagrams.py` (Docker, the Mermaid CLI image) draws
  `img/diagrams/arch-<n>-<name>-<language>.svg` and the SVGs are committed. Each holds a fingerprint (the
  SHA-256 of the filled source and of `render_diagrams.py`'s own text); `build_site.py --check` fails, and
  names the tool, when a template, a label or the tool changed and the SVGs were not drawn again.
  `--png DIR` writes light and dark PNGs to look at (do not commit them).
- The SVGs are plain: text as `<text>`, no script, no outside address, no font loaded. Colours are CSS
  variables with a `prefers-color-scheme: dark` override inside the SVG, from the site's palette
  (`PALETTE` in the tool), so each follows the reader's light or dark setting when shown in an `<img>`.
- A label may not hold `"`, a backtick, `;` or `#` (Mermaid reads them as syntax).

## Images

The Atalaia badge and the two illustrations were made by the project maintainer with Google
Gemini image generation. `img/` holds web-optimized copies, under the same CC BY-SA 4.0 licence as
the rest of this folder (see [REUSE.toml](../REUSE.toml)); the top-level README uses them too.

| Files | What they are | Where they appear |
| --- | --- | --- |
| `logo-1024.png`, `logo-512.png`, `logo-192.png` | The round badge: watchtowers with signal fires on dunes | The Name section of both main pages, the apple-touch-icon (192), the top of the README. The header keeps the small SVG mark and `favicon.svg`, as the badge is too detailed at that size |
| `watchtower-night-960/1600` (`.jpg`, `.webp`) | Night scene: a hilltop watchtower linked to GAME PROP boxes across a valley, with the English text "Open-source project ATALAIA" painted in | Hero of the English, German and Chinese main pages; the README banner |
| `watchtower-night-pt-960/1600` (`.jpg`, `.webp`) | The same night scene with its text in Portuguese, "Projeto de código aberto ATALAIA" | Hero of the Portuguese main page |
| `field-isometric-960/1600` (`.jpg`, `.webp`) | Isometric stone tower ringed by GAME PROP cases | "How it fits together" on the English, German and Chinese main pages |
| `og-pt.jpg`, `og-en.jpg` | 1200 × 630 social previews (`og:image`) | Link previews of every page in that language; the German and Chinese pages use `og-en.jpg` (`og_image` in `LANGUAGES`) until one is drawn with their text |
| `screens/` | Screenshots (see [Screenshots](#screenshots)) | "What it looks like" on the main page; some in the top-level README |
| `modes/` | The modes page's animated pictures, 56 GIFs and 56 stills (see [Game-mode animations](#game-mode-animations)) | The cards of the modes page; one in the top-level README |

Each main page loads only its own hero image (WebP, with JPEG for older browsers, at 960 or 1600
pixels wide as the screen needs) and lazy-loads everything below it.

### Screenshots

`img/screens/` holds the screenshots of "What it looks like", shown at their own size:

| Files | What they are |
| --- | --- |
| `bomb-*.png`, `join-joined.png`, `codes-entry.png` | The Field Box firmware (320 × 240) in the Wokwi emulator |
| `app-<screen>-pt.png`, `-en.png`, `-de.png`, `-zh-tw.png` | The app's golden test images (360 × 780), copied from `app/test/goldens/images/screens/` (`home` as `app-roles`, `prop_game` as `app-prop-game`, `player`, `chrono`) and `branding/` (`player` as `app-player-branded`); each language's page shows its own (`app-<screen>-zh-tw.png` from the `_zh-tw` goldens; `screenshots` in `LANGUAGES` can point a new language at English's until its goldens exist) |
| `app-medic-*.png` | The Medic Kit's screens (320 × 240) as the app draws them, from `app/test/goldens/images/templates/medic_*.png`; the kit's screens are Portuguese by default, so every language shows the same copies |

When the app's golden images change (`python tools/docker_app.py goldens`), copy them again.
Each screenshot is a link to its own image. A small inline script at the end of
`src/index.html` opens the link in a `<dialog>` on the page instead: the image as large as the
screen allows (up to three times its size, in whole steps when small, so its pixels stay sharp),
its alt text as the caption, previous and next (buttons or the arrow keys), closed with Esc, the
close button or a click outside the image, with the focus back on the screenshot. Without
JavaScript, or in a browser without `<dialog>`, the link opens the image itself. The viewer
needs each `<img>` to keep its `width` and `height`, and the link the class `zoom`. In the
script, never write two braces together: the build reads them as a placeholder.

### Game-mode animations

`img/modes/<mode>-<language>.gif` (360 × 444, with `-still.gif`, one frame, beside it) are made by
`python3 tools/gen_mode_gifs.py`, never by hand: the Field Box's firmware code (the screen renderer
with the modes' templates, and the OLED view, in a host program,
`firmware/esp32/test/mode_gif_frames.c`) draws the screens of a scripted game on the TFT and the
OLED, and the script frames them in the box's body and writes the GIFs. `tools/mode_gifs.yaml`
holds the scripts (what each mode's script sends, step by step, and how long each step stays).
`python3 tools/gen_mode_gifs.py --check` (CI's firmware-test job runs it) fails if a file is not
what the code draws now. Adding a mode takes four steps: an entry in `tools/mode_gifs.yaml`
(its header explains the keys), `python3 tools/gen_mode_gifs.py --only <id>`, a `<figure
class="modegif">` in the mode's card in `src/modes.html` (copy a neighbour's) and its `alt` and
`caption` under `gifs.<id>` in the four language files.

A card's picture is a `<picture>` whose `<source>` for `prefers-reduced-motion: reduce` is the still
frame, with `loading="lazy"` and the alt text and caption of `gifs.<id>`; a small inline script at
the end of `src/modes.html` adds a pause button under each (play, for someone who asked for less
motion; clicking it swaps the image for the animated GIF). Every mode has a picture in each of the
four languages (the box's templates are in all four; the messages a mode's script writes, such as
"Kill confirmed: b1", stay English); a `languages: [en]` entry in the script would make one `-en`
picture that the four pages share. Decisions GIF-1 to GIF-12 in `docs/review/decisions-to-review.md`.

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
- Every key must be in every language's file (`pt.yaml`, `en.yaml`, `de.yaml`), and every key must be used by some template,
  partial or diagram, apart from the keys of single-language parts (next point).
  Every language's version of a page must link to the same external addresses.
- Each page's `<title>` and description are `meta.<page>.title` and `meta.<page>.description`
  (and optionally `meta.<page>.og_description` for link previews); `meta.og_image_alt` is shared.
- Links between the pages are relative, so the site works on GitHub Pages and from a local
  server. A template writes `{{ page.to.<page> }}` (`{{ page.to.glossary }}`,
  `{{ page.to.index }}#try`); a text in the YAML files can hold the same values, which the build
  fills in for the page that shows it. Write a page link with its trailing `/`.
- A part that only one language shows, such as the night scene with English text in it, goes
  between `{% if lang en %}` and `{% endif %}` lines in the template. Its keys then live only in
  that language's file.
- Links to the repository's documents point at the English documents in every language; the
  Portuguese page says "(em inglês)" next to them, the German one "(auf Englisch)".
- The header menu is three `<details>` menus (Learn: modes, radio, how it fits, glossary; Build: build guides, try it, roadmap; Community: community hub, registry) and GitHub; `name="nav"` closes the others, `data-current` marks the menu that holds the page being read and `aria-current` its link (`NAV_GROUPS` in `tools/build_site.py`).
- The language switcher is four emoji flags at the top right of every page; each link names its language in its own language (`aria-label`, `title`) and leads to the
  same page in the other languages. Try the site with a local server
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
   lowercase ASCII slug in that language, ending in `/`; `"roadmap/"` in all three).
2. Write `src/<name>.html`. Copy an existing subpage such as `src/roadmap.html`: it includes
   `head`, `header` and `footer`, and opens with a `page-head` section (its `h1` and lead) and a
   `content` block whose headings are `h2`.
3. Add `meta.<name>.title` and `meta.<name>.description`, and the page's text, to both
   `pt.yaml` and `en.yaml`.
4. Link to it: from the header (`src/partials/header.html`, with `{{ page.nav.<name> }}` to mark
   it as the current page) and wherever the main page shortens its section.
5. Run `python3 tools/build_site.py`: it writes every language and adds the page to
   `sitemap.xml`. Renaming or removing a page leaves its old files behind; the build names them,
   and you delete them.

### The build guides page

`src/build.html` keeps the pin tables in the template, since their GPIO numbers are the same in
every language: each GPIO cell names its Kconfig symbol (`<td data-kconfig="ATALAIA_BTN1_PIN">4</td>`),
and `tools/check_wiring.py` (in `tools/check.sh`) fails if a number is not that symbol's default
in `firmware/esp32/main/Kconfig.projbuild`. When a pin default changes, change the number here,
in `hardware/satellite/BUILD.md` and in `hardware/io-pod/BUILD.md` together. The dashed
`figure.photo` boxes mark where the first builds' photos go (plan phase HW2); never a mock-up or
generated picture. Portuguese words: guia de montagem, caixa satélite, módulo de E/S, módulo de
alvo; German: Bauanleitung, Satellit, I/O-Pod, Ziel-Addon.

The Field Box's section has a pin table of the same kind and its two WireViz wiring drawings
(2026-10-26, the maintainer's request). The SVGs have one source, `hardware/field-box/wiring/*.svg`
(rendered by `python tools/docker_hw.py render`): `tools/build_site.py` copies them to
`img/wiring/` (`WIRING` there), adding a font stack with fallbacks and a "do not edit" note, and
`--check` fails when a copy is stale. **They are not translated**: WireViz bakes the labels into the
SVG, and they are pin names, GPIO numbers, wire colours and part numbers, which wiring keeps in
one language; the captions, the alt text and the note saying so are translated. Each is shown scaled
to the column inside a link to the SVG itself, so a tap opens it at full size to zoom and pan (the
page never scrolls sideways), on a white sheet in the dark theme too (a black wire must stay
black). The Satellite and the I/O pod point at the Field Box's drawings, as their BUILD.md files do.

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
`<text>`, and for `{{ key|wrap }}` also `data-lines`. The build wraps the text at spaces (and between
Han letters, never before closing or after opening punctuation, a Han letter counting as 1 em) and fails
if a line would be too wide in the widest common fallback font (DejaVu Sans), naming the key and
the line: shorten the translation, or give it more room in the template. Each diagram has an
opaque light background, so it reads on dark pages too, and its colours are the page's.

### Plain words and the glossary

The pages are written for players, field owners and GMs who are not engineers. When a technical
term first appears, say what it is in a few plain words ("LoRa mesh (long-range, low-power
radio...)"), and link the harder ones to the glossary page:
`<a href="{{ page.to.glossary }}#glossary-lora">`.

- Each glossary entry has `id`, `term` and `text` keys under `glossary` in every file. The ids
  are ASCII and differ by language (`glossario-lora` on the Portuguese glossary page,
  `glossary-lora` on the English and Chinese ones, `glossar-lora` on the German one); keep them stable, since other sites may link to them, and
  change a link whenever you change an id.
- A glossary text is one to three sentences: what the thing is, and why Atalaia uses it.
- Check each claim against the [design specification](../docs/design-spec.md). Prices are the
  spec's approximate figures, and anything not built yet (the site server, the phone as field
  controller, the iOS app, the thin nodes) is written as "will" or "still to come". What is built
  but has not run on real hardware (the firmware, the controller, the app, the I/O pod) says so.
  The roadmap's status tags and the hero's status line follow `docs/phase-*/STATUS.md`.

### Portuguese terms

The Portuguese text is European Portuguese, written the way Portuguese airsoft and paintball
players write. Keep these choices consistent when you edit it:

| English | Portuguese |
| --- | --- |
| props | dispositivos (de jogo); caixas for the boxes. "Props" appears only in the introduction and in the glossary term |
| GM, organisers | organização; GM console is "consola da organização" |
| field | campo |
| site server | servidor do site |
| field controller | controlador de campo |
| chrono, chrono check-in | cronografagem, cronografagem à entrada |
| milsim, CQB, respawn, makers, copyleft, squad | unchanged ("esquadra" is a police station) |
| team | equipa (the side, always there); a squad is a group within a team |
| presets | predefinições |
| Domination, Bomb | Domínio, Bomba |
| roadmap | Roadmap, unchanged, as it is known in Portugal (never "Roteiro"); its page is `/roadmap/` |
| gate (of a roadmap phase) | prova |
| roadmap status tags: done, software done, in progress, designed | concluída, software pronto, em curso, planeada ("desenhada" reads as drawn) |
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

### Traditional Chinese

The Chinese text is Traditional Chinese as Taiwanese airsoft (生存遊戲) players write it, with the
words of the zh-tw column of [docs/translations/glossary.md](../docs/translations/glossary.md):
"你", full-width punctuation (，。：「」), a half-width space between Han letters and Latin letters
or digits ("GM 控制台", "第 2 階段"), a decimal point. YAML folds a broken line into a space, which a
browser would show between two Han letters: `build_site.py` drops such spaces (and those beside
full-width punctuation) in the Chinese texts, so a line of `zh-tw.yaml` may break anywhere. The
pages use the system's Traditional Chinese fonts (PingFang TC, Noto Sans TC, Microsoft JhengHei;
`:lang(zh)` in `style.css`), never a web font, and break lines with `line-break: strict`.
