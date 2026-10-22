<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 5 -- Community: Research

## Summary

> **Refresh 2026-10-22.** This research was written on 2026-10-18, before
> phases 2-4 were built. Where it says the field API is pending, that a
> controller pushes modes to nodes, that firmware strings are compile-time
> headers, that modes get `i18n/` folders or that Blockly 11 is the target,
> the code now says otherwise: see "Refresh 2026-10-22" in `ADR.md` (the facts
> and the amendments) and `PLAN.md` (the re-cut plan), and decisions P5R-1 to
> P5R-14 in `docs/review/decisions-to-review.md`. The text below is kept as
> written.

Phase 5 adds the community layer around the platform built in phases 0-4:
a visual mode editor (Blockly), a signed mode registry with a verified
badge, the carrier PCB, translations beyond English and Portuguese, and
build guides. It is the first phase explicitly described as "ongoing after
the first release" (design-spec.md section 16), so its deliverables are
incremental rather than gated by a single field test.

This is a **design-only** research document. No production code is written
in this phase.

**Risk:** Medium -- The individual pieces (Blockly editor, GitHub-based
registry, KiCad carrier PCB, i18n expansion) are well-understood
technologies, but the Blockly-to-Lua code generation depends heavily on
the stability of the script API from phases 0-4, the registry's signing
and verification scheme has security implications, and the carrier PCB
requires hardware validation that cannot happen until Field Box prototypes
from phase 1 have been built and tested.

---

## 1. Visual Mode Editor

### 1.1 Blockly-to-Lua mapping

The editor must generate readable `node.lua` and `field.lua` scripts using
the [Blockly](https://developers.google.com/blockly) visual programming
library. The generated Lua must be indistinguishable from hand-written
mode scripts, so a GM who graduates from the editor can continue editing
the output by hand (design-spec.md section 9: "Generated code stays
readable, so a GM can graduate to editing it by hand").

The script API surface to map (from `core/src/script_api.c` and
design-spec.md section 9):

| API area | Functions | Blockly block category |
|----------|-----------|----------------------|
| Events | `on(type, fn)`, `emit(type, data, opts)` | Events |
| Time | `every(s, fn)`, `after(s, fn)`, `cancel(id)`, `game.time()` | Timers |
| State | `state.node{}`, `state.field{}` (phase 2+) | Variables / State |
| Game | `game.start()`, `game.finish(reason)`, `game.win(team)` | Game control |
| Scoring | `score.add(team, n, reason, squad)`, `score.get(team)` | Scoring |
| Hardware | `cap(id):method(...)`, `ui.screen(template, data)`, `audio.play(clip)`, `audio.say(text)` | Hardware |
| Field | `field.nodes(role)`, `field.owner(node)`, `field.common_owner(list)`, `field.send(node, cmd)` | Field (controller) |
| Utilities | `params`, `rand(a, b)`, `log(msg)` | Utilities |

### 1.2 Existing mode patterns the editor must produce

**Domination** (`modes/domination/node.lua`, 29 lines):
- `state.node { owner = nil }` -- initializes local state
- `on("team_input.hold", fn)` -- event handler with conditional logic
- `cap("team_display"):show(e.team)` -- hardware command via capability proxy
- `every(params.tick_s, fn)` -- periodic timer reading params
- `score.add(s.owner, params.points_per_tick, "hold")` -- scoring
- `on("game.end", fn)` -- game lifecycle

**Bomb** (`modes/bomb/node.lua`, 67 lines):
- `state.node { phase = "standby", explode_at = 0 }` -- multi-field state
- `after(params.fuse_s, explode)` -- one-shot timer with named function
- `cancel(fuse_timer)` -- timer cancellation
- `emit("bomb.armed", ...)` with `{ prio = "critical" }` -- priority events
- `audio.play("explosion")` -- audio playback
- `ui.screen("countdown", { left = ... })` -- parameterized screen templates
- Conditional `if params.auto_arm_after_s then` -- optional-param guard

The editor needs blocks for:
- **Event handlers**: "when [event type] happens" with access to `e.team`, `e.ms`, `e.squad`
- **State management**: "set state [key] to [value]", "get state [key]"
- **Conditionals**: team comparison, phase/state checks, parameter comparisons
- **Timers**: "every [N] seconds do", "after [N] seconds do", "cancel timer [id]"
- **Scoring**: "add [N] points to [team] for [reason]"
- **Hardware**: "show screen [template] with [data]", "play sound [clip]", "show team color [team]"
- **Events**: "emit [event type] with [data]" (with optional priority)
- **Game control**: "end game", "team [team] wins"
- **Math/logic**: standard Blockly math, logic, and text blocks

### 1.3 Simulator integration

The editor should reuse the existing simulator web view for live testing.
The simulator architecture:

- `simulator/atalaia_sim/web.py` -- HTTP server (`WebServer` on `ThreadingHTTPServer`) serving static files from `atalaia_sim/web/` and a JSON API (`GET /api/state`, `POST /api/action`)
- `simulator/atalaia_sim/live.py` -- `LiveGame` class wrapping a `Simulation` with real-time clock, thread-safe state, team-button holds, speed control (1x-60x)
- The web view shows each node's screen, outputs, sounds, scores, event log with LoRa packet sizes, and protocol problems

**Integration approach**: The editor would be a new page or tab alongside the existing simulator web view. A GM writes blocks, the editor generates `node.lua` (and optionally `field.lua`), the simulator loads and runs it with virtual nodes, and the GM tests it live in the browser. The editor page would POST the generated Lua to a new endpoint, and the simulator would hot-reload the mode.

### 1.4 Mode manifest generation

The editor must also produce `mode.yaml`. Blockly blocks for the "when
team claims this box" pattern imply `requires: [team_input]`; blocks
using `nfc` or `keypad` capabilities add those to `optional`. The
parameter definitions (`params`) come from editor-declared variables with
type, default, min/max and label.

### 1.5 i18n for the editor itself

The editor UI (block labels, tooltips, category names, help text) must
ship in English and Portuguese (pt-PT) from day one (design-spec.md
section 12). Blockly has built-in support for custom locales via JSON
message files, so the existing i18n pattern applies: one JSON locale
file per language, loaded at init.

### 1.6 Blockly version pinning

Blockly is an active Google project with breaking changes between major
versions. The editor must pin a specific Blockly version (currently v11.x)
and vendor it or load it from a CDN with an integrity hash. Updates go
through a PR with a test pass of all built-in block definitions.

---

## 2. Mode Registry

### 2.1 Existing mode package format

From `modes/README.md` and the existing modes:

```
<mode>/
  mode.yaml     id, version, licence, min_tier, roles, params
  node.lua      runs on each prop
  field.lua     optional: runs on the field controller
  assets/       optional: sound clips, screen templates
  i18n/         optional: translated strings
  tests/        event sequences with expected results
```

Manifest fields (from `modes/bomb/mode.yaml`):
- `id`: reverse-domain (`org.atalaia.bomb`)
- `version`: semver (`0.1.0`)
- `license`: SPDX identifier (`GPL-3.0-or-later`)
- `min_tier`: `reduced` or `full`
- `name`, `description`: human-readable
- `roles`: map of role-name to `{ requires: [...], optional: [...] }`
- `params`: map of parameter-name to `{ type, default, min, max, optional, label }`

### 2.2 Registry architecture

Design-spec.md section 13 describes the registry:

> Shared modes live in a Git-based registry: an index repository listing
> each mode's id, versions, hashes, licence, required capabilities and
> the author's signature.

The registry is:
- **Git-based**: an index repository (likely on GitHub) with one entry per mode
- **Author-signed**: packages carry the author's signature
- **Verified badge**: means the mode passed its own tests in CI and a maintainer review
- **Version-aware**: manifests declare minimum core API version
- **Cached offline**: the controller syncs the index when online

**Hosting options**:
- **GitHub Releases**: each mode as a release asset on the mode's own repo, with the index repo linking to them. Advantages: free, familiar, CI integration. Disadvantage: requires a GitHub account per author.
- **GitHub Pages**: the index as a static JSON file on Pages, with mode packages as tarballs. Advantages: simple, cacheable. Disadvantage: limited to the index repo's Pages quota.
- **Recommended**: GitHub Releases for packages, a JSON index file in the index repo published to Pages. The controller fetches the index, checks signatures, and downloads packages by URL.

### 2.3 Signing and verification

Design-spec.md section 14:

> Packages are signed by their author; the controller shows who signed
> a mode before installing it.

The signing scheme should use Ed25519 (already used for firmware images, section 13). Each author generates a keypair. The mode package (tarball of the mode directory) is signed with the author's private key. The index repo holds each author's public key. The controller verifies the signature before installing.

The **verified badge** means:
1. The mode's `tests/` pass in CI (the registry's CI runs `python -m atalaia_sim test <mode>`)
2. A project maintainer has reviewed the mode
3. The mode's manifest declares a valid `license` from the approved list

### 2.4 Approved licence list

Design-spec.md section 17: "Community modes: Author's choice from an
approved list." The approved list should include:
- GPL-3.0-or-later (same as built-in modes)
- MIT
- Apache-2.0
- BSD-2-Clause, BSD-3-Clause
- CC0-1.0 (for trivial modes)
- LGPL-3.0-or-later (if someone wants to allow proprietary modifications)

All must be OSI-approved or FSF-approved free licences, to keep the
registry open. The registry CI checks the `license` field against this
list.

### 2.5 How nodes and controllers fetch modes

Design-spec.md section 13:
- The controller syncs the index when it has internet and caches packages for offline use
- Scripts, assets and firmware never travel over LoRa (section 10)
- Modes are pushed to nodes over Wi-Fi or BLE when joining a game (section 10: "Joining also pushes any scripts and assets the node is missing over Wi-Fi or BLE")
- Manifests declare the minimum core API version, so old nodes never receive modes they cannot run

### 2.6 Registry index format

A JSON file listing each mode:

```json
{
  "modes": [
    {
      "id": "org.atalaia.bomb",
      "name": "Bomb / Rush",
      "author": "atalaia-project",
      "author_key": "ed25519:...",
      "versions": [
        {
          "version": "1.2.0",
          "min_core": "0.4.0",
          "min_tier": "reduced",
          "license": "GPL-3.0-or-later",
          "sha256": "...",
          "signature": "ed25519:...",
          "url": "https://github.com/.../releases/download/v1.2.0/bomb-1.2.0.tar.gz",
          "verified": true
        }
      ]
    }
  ]
}
```

---

## 3. Translations / i18n

### 3.1 Existing i18n workflow

The project page uses a template-and-YAML approach:
- `site/src/index.html` -- Jinja2-like template with `{{ key }}` placeholders
- `site/i18n/en.yaml`, `site/i18n/pt.yaml` -- translation files
- `tools/build_site.py` -- renders templates to static HTML per language
- CI runs `python3 tools/build_site.py --check` to ensure pages are up to date and every key is present in both files

The site README (`site/README.md`) documents:
- Every key must be in both YAML files
- Every key must be used by the template
- Links to the same external addresses in both languages
- A Portuguese terminology table (e.g., "props" = "dispositivos", "GM" = "organização")

### 3.2 Mode i18n

Each mode can have an `i18n/` folder (design-spec.md section 9, modes/README.md). The mode package format includes `i18n/` as optional. This folder would contain YAML or JSON files per language with translated strings for:
- Mode name and description
- Parameter labels
- Screen template text
- Sound-clip labels (for the editor)

### 3.3 Firmware screen strings

The firmware's LVGL screens (12 templates in phase 1) contain hard-coded English text. Phase 5 should extract these into an i18n table. The firmware's resource constraints (ESP32-S3, 2 MB PSRAM) limit the number of simultaneously loaded locale files, so the active locale should be selected at boot from the node config.

### 3.4 Editor i18n

The Blockly editor itself needs:
- Block labels and tooltips in each language
- Category names
- Help text and documentation links
- Error messages

Blockly supports custom locales via `Blockly.Msg` overrides. The editor should follow the same YAML-to-JSON pattern as the site, generating Blockly locale JSON from the project's YAML files.

### 3.5 Expansion beyond en/pt

Design-spec.md section 12: "English and Portuguese ship first." Phase 5
opens translation to the community. The workflow:
1. Copy the English YAML file to a new locale (e.g., `i18n/es.yaml`)
2. Translate every key
3. Run `python3 tools/build_site.py` to generate the page
4. CI validates completeness

The site template already supports a language switcher. Adding a language
means adding a YAML file, a template `{% if lang xx %}` block for
language-specific content, and a URL path (e.g., `/es/`).

---

## 4. Carrier PCB

### 4.1 Current Field Box BOM

From `hardware/field-box/README.md`:

| Part | Recommended | Bus |
|------|-------------|-----|
| Main board | Heltec WiFi LoRa 32 V4.3 | -- |
| Team buttons (2-4) | 60 mm arcade, active-low | GPIO 4, 5, 33, 34 |
| Keypad | 3x4 membrane | I2C via PCF8574 at 0x20 |
| Display | 2.8" ILI9341/ST7789 SPI TFT | SPI: MOSI 40, CLK 41, CS 42, DC 3, RST 38, BL 47 |
| LED ring | WS2812B 24-LED | GPIO 48 (RMT) |
| NFC reader | PN532 breakout (I2C) | I2C at 0x24 |
| Audio amp | MAX98357A I2S + speaker | I2S: BCLK 6, LRCLK 15, DOUT 16 |
| Battery gauge | MAX17048 (I2C) | I2C at 0x36 |
| Battery | 2S 18650 + BMS | JST connector |

All I2C devices share one bus on GPIO 17 (SDA) / 18 (SCL).

### 4.2 What the carrier PCB replaces

Today, builders wire each module to the Heltec board with jumpers or a
perfboard. The carrier PCB:
- Provides header sockets for the Heltec V4.3 board
- Routes I2C, SPI, I2S and GPIO to labelled connectors for each module
- Includes the level shifter for the WS2812B data line (3.3V to 5V)
- Adds the M12 addon bus connector (GND, 5V, SDA, SCL, INT)
- Adds battery management connectors (USB-C PD in, BMS connector, power switch)
- Fits inside the reference IP65 enclosure (~200x150x100 mm)

### 4.3 Design tool and licence

- **KiCad** (open-source EDA): schematic + PCB layout
- **CERN-OHL-S-2.0** licence (from `REUSE.toml`: `hardware/**` is CERN-OHL-S-2.0)
- Design files go in `hardware/field-box/pcb/` (schematic, PCB, BOM, Gerbers)

### 4.4 Timing

Design-spec.md section 18 (open questions): "Carrier PCB timing: deferred,
to be decided later." The PCB depends on:
- Validated pin assignments from phase 1 hardware bring-up
- Confirmed I2C bus stability with all four devices on one bus
- Physical fit inside the enclosure, verified with prototypes

The carrier PCB should not begin layout until at least 3 Field Box
prototypes have been built and tested on perfboard in phase 1.

---

## 5. Build Guides

### 5.1 Existing documentation

- `firmware/esp32/docs/BRING_UP.md` -- step-by-step hardware bring-up procedure
- `hardware/field-box/README.md` -- BOM, pin assignments, assembly sequence (11 steps)
- The site has a bilingual structure (`site/index.html` for pt-PT, `site/en/index.html` for en)

### 5.2 What build guides should cover

For each reference build (Field Box, Satellite, I/O Pod, Field Controller, Target Addon):
1. Parts list with links to common suppliers
2. Tools needed
3. Step-by-step assembly with photos
4. Wiring diagram or schematic
5. Firmware flashing instructions
6. First-boot configuration (Wi-Fi captive portal)
7. Troubleshooting / FAQ
8. Enclosure options (IP65 box modifications, 3D-printed parts)

### 5.3 Where they live

Build guides are documentation, so they fall under CC-BY-SA-4.0.
Options:
- `docs/build-guides/` in the repo (versioned with the code)
- The project site as additional pages (published via GitHub Pages)
- The community hub's build gallery (for community-contributed builds)

The recommended approach: guides in the repo as Markdown, rendered to
the site by `tools/build_site.py` with the same i18n workflow. This keeps
them versioned, translatable, and CI-checked.

---

## 6. Community Processes

### 6.1 Existing governance

- `CONTRIBUTING.md`: DCO sign-off, clean-room policy, RFC process for protocol/API changes, code style, safety
- `docs/rfcs/0000-template.md`: RFC template (Summary, Motivation, Design, Compatibility, Alternatives, Open questions)
- `docs/rfcs/0001-skirmesh-rf-wire-format.md`: accepted RFC for the wire format
- GitHub Discussions enabled (Discussion #1 exists)
- Design-spec.md section 13: governance of the protocol via RFCs, 2-week review period, maintainer decision

### 6.2 What phase 5 adds

- **Mode submission process**: fork, create mode, run tests, open PR to the registry index repo
- **Review checklist for community modes**: sandbox compliance, licence, test coverage, i18n, no unsafe patterns
- **Verified badge criteria**: tests pass in CI, maintainer review, approved licence
- **Community hub features** (design-spec.md section 13): field and team directory, build gallery, mode and scenario browser, discussion, usage statistics, hosted site servers

### 6.3 RFC requirements for phase 5

Phase 5 likely requires RFCs for:
- The mode registry format and signing scheme
- The visual editor's block-to-Lua mapping (to ensure the generated API surface is stable)
- The carrier PCB's addon bus pinout (if it differs from the design-spec.md M12 specification)

---

## 7. Security

### 7.1 Sandbox guarantees

From `core/README.md`:

| Limit | Default | Effect |
|-------|---------|--------|
| Script memory | 256 KB (64 KB on Reduced tier) | Node halts with "memory limit exceeded" |
| Instructions per callback | 1,000,000 | Node halts; `pcall` does not help |
| Events per input/timer step | 256 | Node halts (infinite emit loop) |
| Timers | 32 | `every`/`after` raise an error |

No `io`, `os`, `require` of arbitrary files, or network access. Randomness
only through seeded `rand`. The sandbox is implemented in `core/src/sandbox.c`.

### 7.2 Supply-chain risks of community modes

Design-spec.md section 14: "A malicious shared mode: Sandbox with no file,
OS or network access; author signatures; verified badge in the registry."

Threats specific to the registry:
1. **Typosquatting**: a mode with an id close to a popular one (e.g., `org.atalaia.bombb`). Mitigation: the registry index is curated (PR-based), not open-publish.
2. **Key compromise**: an author's signing key is stolen. Mitigation: key revocation list in the index repo; the controller checks it before installing.
3. **Dependency confusion**: modes do not have dependencies (no `require`), so this is not applicable.
4. **Malicious screen templates / assets**: a mode's `assets/` could contain very large files. Mitigation: the registry CI checks total package size; the controller enforces a per-mode size limit.
5. **Sandbox escape**: a bug in the Lua sandbox or the C core could let a script access `io`/`os`. Mitigation: the sandbox is already fuzz-tested (design-spec.md mentions the instruction watchdog); phase 5 should add a CI job that attempts common sandbox escapes against the core.

### 7.3 Signing and verification details

- **Algorithm**: Ed25519 (consistent with firmware signing, section 13)
- **Key management**: authors generate keypairs locally; public keys are submitted to the registry index repo via PR
- **Signature scope**: the signature covers the entire mode package tarball (sha256 of the tarball, signed with the author's Ed25519 key)
- **Verification**: the controller verifies the signature against the author's public key from the index before installing
- **Key revocation**: a key can be revoked by removing it from the index and adding it to a revocation list; the controller checks the revocation list on sync

---

## 8. CI

### 8.1 Existing CI jobs

From `.github/workflows/ci.yml`:

| Job | What it does |
|-----|-------------|
| `core` | Build core (cmake), run CTests, run simulator unit tests + mode tests |
| `protocol` | Check generated files, check site pages, validate JSON Schema |
| `sanitizers` | Core under AddressSanitizer + UBSan |
| `format` | clang-format-18 + StyLua 2.6.0 |
| `licensing` | REUSE lint (SPDX headers) |
| `esp32-build` | ESP-IDF cross-compilation in `espressif/idf:v5.3.2` |
| `firmware-test` | Firmware HAL stub tests (host build) |
| `dco` | Check DCO sign-off on PR commits |

### 8.2 CI additions for phase 5

| New job | Purpose |
|---------|---------|
| `registry-lint` | Validate mode packages: manifest schema, licence in approved list, package size, signature verification |
| `registry-test` | Run `python -m atalaia_sim test <mode>` for every mode in the registry |
| `editor-test` | Blockly editor unit tests (block definitions, Lua code generation, round-trip: blocks -> Lua -> simulator test pass) |
| `sandbox-escape` | Attempt known Lua sandbox escape patterns against the core; must all fail |
| `i18n-check` | Verify all locale YAML files have the same keys; no missing translations |
| `pcb-check` | KiCad DRC and ERC on the carrier PCB design (when it exists) |

---

## 9. Files Phase 5 will touch or create

### New files

| Path | Purpose | Licence |
|------|---------|---------|
| `editor/` | Blockly visual editor (HTML, JS, CSS) | GPL-3.0-or-later |
| `editor/blocks/` | Custom Blockly block definitions | GPL-3.0-or-later |
| `editor/generators/` | Lua code generators for each block | GPL-3.0-or-later |
| `editor/i18n/` | Editor locale files (en, pt) | CC-BY-SA-4.0 |
| `editor/tests/` | Editor unit tests | GPL-3.0-or-later |
| `registry/` | Registry tooling: index schema, signing scripts, CI | GPL-3.0-or-later |
| `registry/index.json` | Mode index (or in a separate repo) | CC-BY-SA-4.0 |
| `hardware/field-box/pcb/` | KiCad carrier PCB design files | CERN-OHL-S-2.0 |
| `docs/build-guides/` | Build guides for each reference build | CC-BY-SA-4.0 |
| `docs/phase-5-community/RESEARCH.md` | This file | CC-BY-SA-4.0 |
| `docs/phase-5-community/STATUS.md` | Phase status tracker | CC-BY-SA-4.0 |
| `.github/workflows/registry.yml` | Registry CI (lint, test, sign verify) | GPL-3.0-or-later |
| `site/i18n/<new-lang>.yaml` | Additional language files | CC-BY-SA-4.0 |

### Modified files

| Path | Change |
|------|--------|
| `simulator/atalaia_sim/web.py` | New endpoint for editor-generated Lua hot-reload |
| `simulator/atalaia_sim/live.py` | Support hot-reload of mode scripts |
| `simulator/atalaia_sim/web/` | Editor page/tab integration |
| `tools/build_site.py` | Support additional languages, build guide rendering |
| `.github/workflows/ci.yml` | Add editor-test, sandbox-escape, i18n-check jobs |
| `CONTRIBUTING.md` | Add mode submission process, registry contribution guide |
| `site/src/index.html` | Add language switcher entries for new languages |
| `modes/*/i18n/` | Add translated strings for built-in modes |

---

## 10. Patterns to follow

### 10.1 i18n pattern

Follow the existing `site/i18n/*.yaml` + `tools/build_site.py` approach:
- YAML files keyed by string id
- Template rendering with `{{ key }}` placeholders
- CI check for key completeness across all locales
- Portuguese terminology table from `site/README.md`

### 10.2 Mode package format

Follow the existing `modes/bomb/` and `modes/domination/` structure exactly.
The editor must generate the same file layout. New fields in `mode.yaml`
for registry metadata (author, signature) go at the top level, not inside
`roles` or `params`.

### 10.3 CI pattern

Follow the existing `ci.yml` pattern:
- `ubuntu-latest` runner (or `ubuntu-24.04` when pinning matters)
- `actions/checkout@v7`, `actions/setup-python@v7`
- Explicit dependency install
- Each check as a named step with a clear failure message

### 10.4 Licence headers

SPDX headers on every file, checked by `reuse lint`. Follow `REUSE.toml`
for the correct licence per directory.

### 10.5 Documentation

CC-BY-SA-4.0 for docs. Follow the existing phase RESEARCH.md / STATUS.md
pattern for structure.

---

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Blockly major version breaks block definitions | Medium | High | Pin Blockly version; vendor or use integrity hash; test all blocks on upgrade |
| Lua API changes in phases 2-4 break editor blocks | Medium | High | Editor block definitions must be updated whenever `script_api.c` changes; add CI test that generates Lua from every example block set and runs it in the simulator |
| Registry signing key compromise | Low | High | Key revocation list; re-sign affected packages; incident response documented |
| Sandbox escape via community mode | Low | Critical | Fuzz testing of sandbox; CI job with known escape patterns; verified badge requires maintainer review |
| Carrier PCB layout errors | Medium | Medium | Prototype on perfboard first; KiCad DRC/ERC in CI; community review of schematic |
| Carrier PCB timing dependency on phase 1 hardware | High | Low | PCB is explicitly deferred; no phase 5 gate depends on it |
| i18n key drift between languages | Medium | Low | CI check already exists for en/pt; extend to all locales |
| Editor-generated Lua is unreadable | Medium | Medium | Code generation tests with readability assertions (indentation, named functions, comments) |
| Registry spam / low-quality modes | Low | Low | PR-based curation; verified badge for quality signal |

---

## 12. Dependencies on earlier phases

| Dependency | Phase | Status | Impact on phase 5 |
|-----------|-------|--------|-------------------|
| Stable script API (`script_api.c`) | 0 (core) | Done | Editor blocks map directly to this API. Any API change requires editor block updates. The API is stable as of phase 0 completion. |
| `state.field{}` and `field.*` API | 2 (field network) | Phase 2C pending | The editor's "Field script" blocks cannot be finalized until this API ships. Node-script blocks can proceed now. |
| Mode push over Wi-Fi/BLE | 2 (field network) | Phase 2D pending | Registry packages need a delivery mechanism to nodes. Without this, modes can only be pre-installed. |
| Simulator web view | 0 (foundations) | Done | The editor integrates with the existing web view. No blockers. |
| Field Box hardware prototypes | 1 (single box) | Blocked on parts | Carrier PCB depends on validated pin assignments and physical fit. |
| Controller REST API (`POST /api/v1/modes`) | 2 (field network) | Phase 2D pending | Mode upload from the registry to the controller. |
| Firmware OTA with Ed25519 signing | 1 (design), 2 (impl) | Designed | Registry signing should use the same Ed25519 scheme for consistency. |

### What can start now (phase 0 complete, phase 1 software done)

1. **Blockly block definitions for node scripts** -- the script API is stable
2. **Lua code generator** -- the target Lua patterns are known from existing modes
3. **Editor UI skeleton** -- HTML/JS, can be developed standalone
4. **Registry index format and tooling** -- independent of the platform
5. **Build guide content** -- BOM and assembly sequence exist; photos wait for hardware
6. **i18n expansion** -- the site i18n workflow is established; mode i18n/ format is defined
7. **Mode submission process documentation** -- CONTRIBUTING.md extension

### What must wait

1. **Field script blocks** -- wait for `state.field{}` / `field.*` API (phase 2C)
2. **Editor-simulator integration** -- wait for simulator hot-reload support (can be built in parallel)
3. **Carrier PCB layout** -- wait for hardware prototypes (phase 1 gate)
4. **Registry live deployment** -- wait for controller REST API (phase 2D)
5. **Build guide photos** -- wait for hardware

---

## 13. Assumptions about earlier phases

| # | Assumption | Phase | Confidence | Fallback |
|---|-----------|-------|------------|----------|
| A1 | The script API surface (section 9 of design-spec.md) is final for node scripts: `on`, `emit`, `every`, `after`, `cancel`, `game.*`, `score.*`, `state.node`, `cap`, `ui`, `audio`, `rand`, `log`, `params` | 0 | High -- API is implemented, tested, and used by 2 modes with 12 test files | If a function is renamed or removed, update the corresponding Blockly block and code generator. The mapping is 1:1, so changes are mechanical. |
| A2 | `state.field{}` and `field.*` will follow the design in section 9: `field.nodes(role)`, `field.owner(node)`, `field.common_owner(list)`, `field.send(node, cmd)` | 2 | Medium -- designed but not yet implemented | Defer field-script blocks until the API ships. Node-script blocks cover most community modes. |
| A3 | The mode package format (`mode.yaml` + `node.lua` + optional `field.lua`, `assets/`, `i18n/`, `tests/`) is stable | 0 | High -- used by 2 modes and the simulator | If the format changes, update the editor's manifest generator. |
| A4 | Ed25519 is the signing algorithm for firmware images | 1 | High -- stated in design-spec.md section 13 | Use Ed25519 for mode signing regardless; it is a good choice on its own merits. |
| A5 | The Heltec WiFi LoRa 32 V4.3 pin assignments in `hardware/field-box/README.md` are correct | 1 | Medium -- not yet validated on hardware | The carrier PCB design waits for hardware validation. If pins change, the PCB layout changes too. |
| A6 | The simulator's web view (`web.py`, `live.py`) supports only one mode at a time | 0 | High -- confirmed by reading the code | The editor needs a reload mechanism, not multi-mode support. A new `POST /api/reload` endpoint suffices. |
| A7 | Blockly v11.x generates clean JavaScript AST that can be adapted for Lua output | External | Medium -- Blockly's code generation framework is language-agnostic, but Lua is not a built-in target | Write a custom Lua generator (Blockly provides `CodeGenerator` base class). Python and Dart generators exist as references. |
| A8 | CI runs in GitHub Actions with the existing runner matrix (`ubuntu-latest`, `ubuntu-24.04`, `espressif/idf:v5.3.2`) | 0 | High | No change needed for editor or registry CI. |
| A9 | The sandbox prevents all `io`, `os`, `require` access and enforces memory/instruction limits | 0 | High -- implemented in `sandbox.c`, tested | Add a CI job that attempts known escape patterns. |
| A10 | Community modes will be GPL-3.0-or-later or from the approved licence list | Design | High -- stated in design-spec.md section 17 | The registry CI enforces this at submission time. |
