<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 5 -- Community: Implementation Plan

Gate: **A community author creates a mode in the visual editor, signs
and submits it to the registry, and the registry CI verifies the
package and publishes a verified badge -- all without touching Lua by
hand.**

Constraint: Phase 5 is ongoing after the first release (design-spec.md
section 16). Several deliverables are blocked on earlier phases
(field API, controller REST API, hardware prototypes). This plan
separates what can start immediately from what must wait, and marks
every dependency gate explicitly.

---

## Scope

### In scope

- **Visual mode editor**: Blockly v11.x block definitions for all 8
  script API categories, custom Lua `CodeGenerator`, editor UI
  skeleton (HTML page, workspace, palette, Lua preview), `mode.yaml`
  generation from workspace, editor i18n (en + pt), CI round-trip
  test.
- **Editor-simulator integration**: `POST /api/reload` endpoint on
  the simulator, hot-reload workflow, editor page served from the
  simulator's `WebServer`, "Test" button workflow, CI integration
  test.
- **Mode registry**: `atalaia-modes` repository setup, `index.json`
  schema with `schema_version`, `keys/` directory, `keys/revoked.json`,
  `keygen.py` and `sign.py` tooling, package format (tarball, SHA-256,
  Ed25519 signature), `registry-lint` CI job, `registry-test` CI job,
  `sandbox-escape` CI job, approved licence list validation, review
  checklist documentation, mode submission process in CONTRIBUTING.md,
  verified badge workflow, revocation list.
- **i18n expansion**: unified YAML architecture across 4 domains (site,
  editor, modes, firmware), `build_editor_i18n.py` (YAML to JSON),
  `build_firmware_i18n.py` design (YAML to C header), `i18n-check`
  CI job, at least one additional locale beyond en/pt to prove the
  workflow, built-in modes `i18n/` folders with en and pt translations.
- **Build guides**: Markdown in `docs/build-guides/`, rendered to the
  site by `tools/build_site.py`, Field Box and Satellite text guides.
- **Carrier PCB**: KiCad 8.x schematic and layout in
  `hardware/field-box/pcb/`, CERN-OHL-S-2.0, `pcb-check` CI job.
- **Community processes**: GitHub Discussions category structure,
  contributor onboarding docs, CONTRIBUTING.md update for mode
  submission, RFC for registry format changes.

### Out of scope

- Mode delivery to nodes (controller fetches from registry and pushes
  over Wi-Fi/BLE): phase 2D.
- `field.lua` editor blocks for `state.field{}` and `field.*` API:
  deferred until phase 2C ships the field API.
- Android/iOS player app: phase 3.
- Site server and community hub backend: phase 4.
- BLE join flow: phase 3.
- Hosted site servers: phase 4+.
- Community hub web features beyond the registry and Discussions
  (ratings, usage statistics, hosted servers): post-v1.
- Hit-scoring target addon PCB: tracked separately if needed.

### Dependency gates on earlier phases

| Gate | Phase | Status | What it unblocks in phase 5 |
|------|-------|--------|-----------------------------|
| Script API stable (`script_api.c`) | 0 | Done | Editor blocks for node scripts (Phase A) |
| Simulator web view | 0 | Done | Editor-simulator integration (Phase B) |
| `state.field{}` and `field.*` API | 2C | Pending | Field-script editor blocks (deferred) |
| Controller REST API (`POST /api/v1/modes`) | 2D | Pending | Registry live deployment to controllers |
| Mode push over Wi-Fi/BLE | 2D | Pending | Registry packages delivered to nodes |
| Field Box hardware prototypes (3+) | 1 | Blocked on parts | Carrier PCB layout, build guide photos |
| Firmware Ed25519 signing | 1-2 | Designed | Registry signing consistency (not blocking -- Ed25519 chosen on its own merits) |

---

## Constraints from the ADRs (all 8 respected)

| ADR | Constraint | How the plan respects it |
|-----|-----------|--------------------------|
| P5-1 | Blockly `CodeGenerator` class, not templates; vendored v11.x; CI round-trip test; named functions, 2-space indent, no boilerplate | Phase A implements a `CodeGenerator` subclass; Blockly vendored in `editor/vendor/blockly/`; CI round-trip test generates Lua from example workspaces and runs them through `atalaia_sim test` |
| P5-2 | `POST /api/reload`, same-origin static serving, error in response body | Phase B adds the endpoint to `web.py`; the editor is served as a static page from the simulator alongside the existing web view; Lua errors are returned in the JSON response, never as HTTP 4xx/5xx |
| P5-3 | Separate `atalaia-modes` repo, GitHub Releases + Pages, `schema_version` in index | Phase C creates the repository; `index.json` published to GitHub Pages; mode tarballs hosted as GitHub Release assets; `schema_version` is an integer in the index root |
| P5-4 | Ed25519, sha256 of tarball, revocation list in `keys/revoked.json` | Phase C implements `keygen.py` and `sign.py`; signature covers hex-encoded SHA-256 of tarball; revocation list is a JSON array in `keys/revoked.json`; controller checks revocation on sync |
| P5-5 | 7 approved SPDX identifiers; RFC to add more | Phase C `registry-lint` validates `license` against the 7-identifier list: GPL-3.0-or-later, LGPL-3.0-or-later, MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, CC0-1.0; CONTRIBUTING.md documents the RFC path for additions |
| P5-6 | Deferred until 3+ perfboard prototypes; KiCad 8.x; CERN-OHL-S-2.0 | Phase D PCB work is explicitly gated on phase 1 hardware validation; design files use KiCad 8.x under CERN-OHL-S-2.0 |
| P5-7 | Unified YAML-keyed across 4 domains; firmware i18n is compile-time | Phase D implements YAML source files for all 4 domains (site, editor, modes, firmware); `build_editor_i18n.py` converts YAML to JSON; `build_firmware_i18n.py` converts YAML to C header; firmware locale is selected at boot, compiled into the image |
| P5-8 | PR-based curation; 12-item review checklist; verified badge = all checks + coverage + maintainer review | Phase C implements the fork-and-PR workflow; CI automates items 1-5, 9, 11-12 of the checklist; maintainer reviews items 6-8, 10; verified badge requires all 12 items + meaningful test coverage + maintainer sign-off |

---

## Phase A: Visual mode editor

### Goal

Build the Blockly-based visual editor that generates readable
`node.lua` and `mode.yaml` from blocks. The editor works standalone
in a browser, ships in English and Portuguese, and produces Lua that
passes the simulator's mode tests. No server-side component is
required -- this phase builds the editor as a static HTML/JS/CSS
application.

This phase can start immediately: it depends only on the script API
(phase 0, done) and the existing mode patterns (domination, bomb).

### Depends on

- A1 (script API stable) -- HIGH confidence
- A3 (mode package format stable) -- HIGH confidence
- A7 (Blockly v11.x `CodeGenerator` adaptable for Lua) -- MEDIUM confidence

### Files to create

| File | Purpose | Licence |
|------|---------|---------|
| `editor/index.html` | Editor page: Blockly workspace, block palette, Lua preview pane, mode.yaml preview | GPL-3.0-or-later |
| `editor/editor.js` | Main editor logic: init Blockly, wire palette, generate Lua on change, generate mode.yaml | GPL-3.0-or-later |
| `editor/style.css` | Editor stylesheet | GPL-3.0-or-later |
| `editor/vendor/blockly/` | Vendored Blockly v11.x (pinned minor, e.g. `11.2.1`) | Apache-2.0 (Blockly's licence) |
| `editor/blocks/events.js` | Block definitions: "when [event] happens", "send event [type] with [data]" | GPL-3.0-or-later |
| `editor/blocks/timers.js` | Block definitions: "every [N] seconds do", "after [N] seconds do", "cancel timer [id]" | GPL-3.0-or-later |
| `editor/blocks/state.js` | Block definitions: "set state [key] to [value]", "get state [key]", state initializer | GPL-3.0-or-later |
| `editor/blocks/game.js` | Block definitions: "end game", "team [team] wins", "get game time" | GPL-3.0-or-later |
| `editor/blocks/scoring.js` | Block definitions: "add [N] points to [team] for [reason]", "get score for [team]" | GPL-3.0-or-later |
| `editor/blocks/hardware.js` | Block definitions: "show screen [template] with [data]", "play sound [clip]", "show team color [team]" | GPL-3.0-or-later |
| `editor/blocks/utilities.js` | Block definitions: "parameter [name]", "random between [a] and [b]", "log [msg]" | GPL-3.0-or-later |
| `editor/blocks/index.js` | Registers all block categories with the Blockly toolbox | GPL-3.0-or-later |
| `editor/generators/lua.js` | Custom `CodeGenerator` subclass for Lua: 2-space indent, named local functions, `state.node{}` at top, no boilerplate comments, blank lines between top-level blocks | GPL-3.0-or-later |
| `editor/generators/events.js` | Code generator functions for event blocks | GPL-3.0-or-later |
| `editor/generators/timers.js` | Code generator functions for timer blocks | GPL-3.0-or-later |
| `editor/generators/state.js` | Code generator functions for state blocks | GPL-3.0-or-later |
| `editor/generators/game.js` | Code generator functions for game control blocks | GPL-3.0-or-later |
| `editor/generators/scoring.js` | Code generator functions for scoring blocks | GPL-3.0-or-later |
| `editor/generators/hardware.js` | Code generator functions for hardware blocks | GPL-3.0-or-later |
| `editor/generators/utilities.js` | Code generator functions for utility blocks | GPL-3.0-or-later |
| `editor/generators/manifest.js` | `mode.yaml` generator: infers `requires`/`optional` from blocks used, collects parameter declarations | GPL-3.0-or-later |
| `editor/i18n/en.yaml` | English block labels, tooltips, category names, error messages | CC-BY-SA-4.0 |
| `editor/i18n/pt.yaml` | Portuguese translations (same keys as en.yaml) | CC-BY-SA-4.0 |
| `editor/examples/domination.json` | Blockly workspace XML/JSON that generates the domination `node.lua` pattern | GPL-3.0-or-later |
| `editor/examples/bomb.json` | Blockly workspace XML/JSON that generates the bomb `node.lua` pattern | GPL-3.0-or-later |
| `editor/tests/test_generator.js` | Unit tests: each block category generates expected Lua fragments | GPL-3.0-or-later |
| `editor/tests/test_manifest.js` | Unit tests: workspace with team_display implies `requires: [team_input]`; nfc adds to `optional` | GPL-3.0-or-later |
| `editor/tests/test_roundtrip.py` | CI test: load example workspace, generate Lua, write to temp mode dir, run `python -m atalaia_sim test` | GPL-3.0-or-later |
| `tools/build_editor_i18n.py` | Converts `editor/i18n/<lang>.yaml` to `editor/i18n/<lang>.json` for Blockly `Msg` overrides | GPL-3.0-or-later |

### Files to modify

| File | Change |
|------|--------|
| `.github/workflows/ci.yml` | Add `editor-test` job: build editor i18n, run `editor/tests/test_roundtrip.py` |
| `REUSE.toml` | Add `editor/` licence mapping (GPL-3.0-or-later for code, CC-BY-SA-4.0 for i18n, Apache-2.0 for vendored Blockly) |

### Note on field-script blocks

The Field block category (`state.field{}`, `field.nodes(role)`,
`field.owner(node)`, `field.send(node, cmd)`) is NOT included in
this phase. These blocks depend on the field API from phase 2C, which
has not shipped. When phase 2C delivers the `field.*` API, a follow-up
adds the Field block category and code generators. The block category
is reserved in the toolbox definition with a "Coming soon" label.

### Validation (Phase A)

**Editor i18n builds cleanly:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  python3 tools/build_editor_i18n.py --check
```

**Editor round-trip test (blocks to Lua to simulator):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh && \
         ATALAIA_CORE_LIB=/tmp/c/libatalaia_core.so \
         python3 editor/tests/test_roundtrip.py"
```

**Expected:** exit 0. The domination and bomb example workspaces each
generate Lua that passes all existing mode tests in the simulator.
The generated Lua uses 2-space indentation, named local functions,
and `state.node{}` at the top.

**Existing CI still passes (no regressions):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

---

## Phase B: Editor-simulator integration and mode registry

### Goal

Wire the editor to the simulator for live testing, and build the
mode registry infrastructure (separate repository, signing tooling,
CI, submission process). These two streams are independent of each
other and can be implemented in parallel within this phase.

Both streams can start immediately: the editor integration depends
on the simulator (phase 0, done) and the editor (Phase A), while the
registry is entirely independent of the platform.

### Depends on

- Phase A (editor generates valid Lua) -- for integration testing
- A6 (simulator supports one mode at a time) -- HIGH confidence

### Stream B1: Editor-simulator integration

#### Files to create

| File | Purpose | Licence |
|------|---------|---------|
| `editor/tests/test_integration.py` | CI test: start simulator, POST generated Lua to `/api/reload`, verify `/api/state` | GPL-3.0-or-later |

#### Files to modify

| File | Change |
|------|--------|
| `simulator/atalaia_sim/web.py` | Add `POST /api/reload` handler: accepts JSON body with `node_lua`, optional `field_lua`, `mode_yaml`, `params`; returns `{"status": "ok", "errors": []}` or `{"status": "error", "errors": [...]}` |
| `simulator/atalaia_sim/live.py` | Add `reload(node_lua, field_lua, mode_yaml, params)` method to `LiveGame`: stop simulation, create new `Simulation`, load scripts, start game; on failure return errors and keep previous simulation |
| `simulator/atalaia_sim/web.py` | Extend `WebServer` to serve files from `editor/` at `/editor/` alongside existing `atalaia_sim/web/` at `/` |
| `editor/editor.js` | Add "Test" button: generate Lua, POST to `/api/reload`, open/refresh simulator tab; display errors inline if POST reports them |

#### Endpoint specification (ADR-P5-2)

```
POST /api/reload
Content-Type: application/json

{
  "node_lua": "-- generated node.lua content",
  "field_lua": null,
  "mode_yaml": "id: org.atalaia.custom\n...",
  "params": { "fuse_s": 300 }
}

Response: 200 OK
{ "status": "ok", "errors": [] }

Response: 200 OK (on Lua error)
{ "status": "error", "errors": ["line 12: attempt to index a nil value"] }
```

The endpoint never returns 4xx/5xx for Lua errors; it always reports
them in the JSON response body so the editor can display them inline.

#### URL structure

| Path | Serves |
|------|--------|
| `/` | Simulator web view (existing) |
| `/editor/` | Blockly editor page |
| `/api/state` | Existing game state API |
| `/api/action` | Existing action API |
| `/api/reload` | New: reload mode from posted Lua |

### Stream B2: Mode registry

#### Files to create (in a new `atalaia-project/atalaia-modes` repository)

| File | Purpose | Licence |
|------|---------|---------|
| `index.json` | Mode index: `schema_version`, `generated_at`, `modes[]` | CC-BY-SA-4.0 |
| `schema/index.schema.json` | JSON Schema for `index.json` validation | GPL-3.0-or-later |
| `keys/README.md` | Instructions for author key submission | CC-BY-SA-4.0 |
| `keys/revoked.json` | Revocation list: `[{"fingerprint", "author", "revoked_at", "reason"}]` | CC-BY-SA-4.0 |
| `.github/workflows/registry.yml` | CI: `registry-lint`, `registry-test`, `sandbox-escape` jobs | GPL-3.0-or-later |
| `README.md` | Registry overview, submission process, signing workflow | CC-BY-SA-4.0 |
| `CONTRIBUTING.md` | Mode submission guide with checklist | CC-BY-SA-4.0 |

#### Files to create (in the main atalaia-project repository)

| File | Purpose | Licence |
|------|---------|---------|
| `registry/tools/keygen.py` | Generate Ed25519 keypair: `<author>.key` (private, never committed) and `<author>.pub` (submit to `keys/`) | GPL-3.0-or-later |
| `registry/tools/sign.py` | Sign a mode tarball: compute SHA-256, sign with Ed25519 private key, output signature | GPL-3.0-or-later |
| `registry/tools/verify.py` | Verify a mode package: check SHA-256, verify Ed25519 signature against public key, check revocation list | GPL-3.0-or-later |
| `registry/tools/package.py` | Build a mode tarball from a mode directory: `tar czf <id>-<version>.tar.gz <id>/` | GPL-3.0-or-later |
| `registry/schema/index.schema.json` | JSON Schema for `index.json` (shared with the registry repo) | GPL-3.0-or-later |
| `registry/tests/test_keygen.py` | Test key generation: valid Ed25519 keypair, fingerprint format | GPL-3.0-or-later |
| `registry/tests/test_sign_verify.py` | Test sign/verify round-trip: sign a test tarball, verify succeeds; tamper, verify fails; revoke key, verify fails | GPL-3.0-or-later |
| `registry/tests/test_package.py` | Test packaging: tarball root is mode id, contains mode.yaml + node.lua | GPL-3.0-or-later |
| `registry/tests/sandbox_escape_patterns.lua` | Battery of Lua scripts that attempt sandbox escapes: `io.open`, `os.execute`, `require("os")`, `load`, `loadfile`, `dofile`, `debug.getinfo`, `rawget(_G, "io")`, `getmetatable` tricks | GPL-3.0-or-later |
| `registry/tests/test_sandbox_escape.py` | Run each escape pattern through the simulator; all must fail with sandbox errors | GPL-3.0-or-later |

#### Registry CI jobs (in atalaia-modes `.github/workflows/registry.yml`)

| Job | What it does |
|-----|-------------|
| `registry-lint` | Validate `index.json` against schema; check every mode entry: `license` in approved list (7 SPDX ids), tarball size under 1 MB, SHA-256 matches, Ed25519 signature valid, key not in `revoked.json`, SPDX headers on source files |
| `registry-test` | For each mode: unpack tarball, run `python -m atalaia_sim test <mode>` |
| `sandbox-escape` | Run `registry/tests/sandbox_escape_patterns.lua` patterns against the core; all must raise sandbox errors |

#### Files to modify (main repository)

| File | Change |
|------|--------|
| `CONTRIBUTING.md` | Add "Submitting a community mode" section: link to `atalaia-modes` repo, signing workflow, review checklist, verified badge criteria |
| `.github/workflows/ci.yml` | Add `sandbox-escape` job that runs `registry/tests/test_sandbox_escape.py` |

### Validation (Phase B)

**Editor-simulator integration:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh && \
         ATALAIA_CORE_LIB=/tmp/c/libatalaia_core.so \
         python3 editor/tests/test_integration.py"
```

**Expected:** exit 0. The test starts the simulator, POSTs generated
Lua from an example workspace to `/api/reload`, verifies the response
is `{"status": "ok", ...}`, then GETs `/api/state` and confirms the
game is running.

**Registry signing round-trip:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest registry/tests/ -v"
```

**Expected:** exit 0. `keygen.py` produces valid Ed25519 keys;
`sign.py` signs a test tarball; `verify.py` accepts the valid
signature and rejects a tampered one and a revoked key.

**Sandbox escape test:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh && \
         ATALAIA_CORE_LIB=/tmp/c/libatalaia_core.so \
         python3 registry/tests/test_sandbox_escape.py"
```

**Expected:** exit 0. Every escape pattern raises a sandbox error or
halts the node. None gains access to `io`, `os`, `require`, `load`,
`debug` or any other disallowed functionality.

---

## Phase C: i18n expansion, build guides, and community processes

### Goal

Extend the i18n workflow to cover all 4 domains (site, editor, modes,
firmware), add at least one locale beyond en/pt to prove the workflow,
write build guide text, update community governance documents, and
land all remaining CI jobs. This phase can start in parallel with
Phase B for the i18n and community-process streams.

### Depends on

- Phase A (editor i18n files exist) -- for editor domain
- A8 (CI runs in GitHub Actions) -- HIGH confidence

### Stream C1: i18n expansion

#### Files to create

| File | Purpose | Licence |
|------|---------|---------|
| `modes/domination/i18n/en.yaml` | English strings for Domination mode: name, description, parameter labels | CC-BY-SA-4.0 |
| `modes/domination/i18n/pt.yaml` | Portuguese strings for Domination mode | CC-BY-SA-4.0 |
| `modes/bomb/i18n/en.yaml` | English strings for Bomb mode | CC-BY-SA-4.0 |
| `modes/bomb/i18n/pt.yaml` | Portuguese strings for Bomb mode | CC-BY-SA-4.0 |
| `firmware/esp32/i18n/en.yaml` | English firmware screen strings (12 templates) | CC-BY-SA-4.0 |
| `firmware/esp32/i18n/pt.yaml` | Portuguese firmware screen strings | CC-BY-SA-4.0 |
| `tools/build_firmware_i18n.py` | Converts `firmware/esp32/i18n/<lang>.yaml` to C header `firmware/esp32/main/i18n/strings_<lang>.h` | GPL-3.0-or-later |
| `tools/i18n_check.py` | Cross-domain i18n completeness checker: validates all 4 domains (site, editor, modes, firmware); verifies key parity across locales; detects orphaned keys | GPL-3.0-or-later |
| `site/i18n/es.yaml` | Spanish locale for the site (or `fr.yaml` -- proving the workflow matters more than the specific language) | CC-BY-SA-4.0 |
| `editor/i18n/es.yaml` | Spanish locale for the editor (same third language as site) | CC-BY-SA-4.0 |

#### Files to modify

| File | Change |
|------|--------|
| `tools/build_site.py` | Accept additional language YAML files beyond en/pt; generate additional language pages |
| `site/src/index.html` | Add language switcher entry for the third language |
| `.github/workflows/ci.yml` | Add `i18n-check` job: run `python3 tools/i18n_check.py` across all 4 domains |

#### Firmware i18n design note

The `build_firmware_i18n.py` script can be designed and tested now
(YAML parsing, C header generation, key completeness validation).
The generated headers cannot be tested in actual firmware until phase 1
hardware is available, but the generator itself is testable by
verifying the output is valid C with the expected `#define` entries.
Only one locale is compiled into each firmware image (ADR-P5-7);
the active locale is selected at boot from node config.

### Stream C2: Build guides

#### Files to create

| File | Purpose | Licence |
|------|---------|---------|
| `docs/build-guides/field-box.md` | Field Box build guide: BOM with supplier links, tools needed, step-by-step assembly (from `hardware/field-box/README.md` assembly sequence), firmware flashing, first-boot config, troubleshooting | CC-BY-SA-4.0 |
| `docs/build-guides/satellite.md` | Satellite build guide: same structure, simpler BOM | CC-BY-SA-4.0 |
| `docs/build-guides/README.md` | Build guide index, links to each guide | CC-BY-SA-4.0 |

#### Files to modify

| File | Change |
|------|--------|
| `tools/build_site.py` | Render `docs/build-guides/*.md` to the site as additional pages |

#### Note on photos

Step-by-step assembly photos are blocked on phase 1 hardware
prototypes. The text guides can be written now from existing
documentation (`hardware/field-box/README.md`, `firmware/esp32/docs/BRING_UP.md`).
Photo placeholders should be marked with `<!-- PHOTO: description -->`
for later replacement.

### Stream C3: Community processes

#### Files to create

| File | Purpose | Licence |
|------|---------|---------|
| `docs/community/mode-review-checklist.md` | The 12-item review checklist from ADR-P5-8 in a standalone document for maintainers | CC-BY-SA-4.0 |
| `docs/community/verified-badge.md` | Verified badge criteria and process documentation | CC-BY-SA-4.0 |
| `docs/rfcs/0000-mode-registry-format.md` | RFC for the registry index format, signing scheme, and approved licence list (documenting what ADR-P5-3 through P5-5 decided) | CC-BY-SA-4.0 |

#### Files to modify

| File | Change |
|------|--------|
| `CONTRIBUTING.md` | Add sections: "Submitting a community mode" (full workflow), "Review checklist for modes" (summary, link to full checklist), "Verified badge" (criteria), "Adding a new licence" (RFC requirement) |

### Validation (Phase C)

**i18n completeness across all domains:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  python3 tools/i18n_check.py
```

**Expected:** exit 0. Every key in English exists in Portuguese and
the third language for the site and editor domains. Mode and firmware
domains require en and pt only. No orphaned keys.

**Build guides render to the site:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  python3 tools/build_site.py --check
```

**Expected:** exit 0. Site pages are up to date, including the new
build guide pages.

**Firmware i18n generator produces valid C:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "python3 tools/build_firmware_i18n.py && \
         gcc -fsyntax-only firmware/esp32/main/i18n/strings_en.h && \
         gcc -fsyntax-only firmware/esp32/main/i18n/strings_pt.h"
```

**Expected:** exit 0. Generated C headers are syntactically valid.

---

## Phase D: Carrier PCB and remaining blocked items

### Goal

Design the carrier PCB for the Field Box, and complete any items
that were blocked on earlier phases. This phase cannot begin PCB
layout until the phase 1 hardware gate is met (3+ perfboard
prototypes built and tested).

### Depends on

- Phase 1 hardware: validated pin assignments (GPIO, I2C, SPI, I2S)
- Phase 1 hardware: I2C bus stability with 4 devices on one bus
- Phase 1 hardware: physical fit inside IP65 enclosure
- Phase 2C: `state.field{}` and `field.*` API (for field-script editor blocks)

### Stream D1: Carrier PCB (BLOCKED on phase 1 hardware)

#### Files to create

| File | Purpose | Licence |
|------|---------|---------|
| `hardware/field-box/pcb/field-box-carrier.kicad_sch` | KiCad 8.x schematic: Heltec V4.3 headers, I2C/SPI/I2S/GPIO routing, WS2812B level shifter, M12 addon bus, power management | CERN-OHL-S-2.0 |
| `hardware/field-box/pcb/field-box-carrier.kicad_pcb` | PCB layout: fits inside 200x150x100 mm enclosure, 4x M3 mounting holes | CERN-OHL-S-2.0 |
| `hardware/field-box/pcb/field-box-carrier.kicad_pro` | KiCad project file | CERN-OHL-S-2.0 |
| `hardware/field-box/pcb/bom.csv` | Bill of materials for the carrier PCB | CERN-OHL-S-2.0 |
| `hardware/field-box/pcb/gerber/` | Gerber output files for fabrication | CERN-OHL-S-2.0 |
| `hardware/field-box/pcb/README.md` | PCB documentation: design decisions, connector pinouts, ordering instructions | CC-BY-SA-4.0 |

#### Files to modify

| File | Change |
|------|--------|
| `.github/workflows/ci.yml` | Add `pcb-check` job: run KiCad DRC and ERC on `hardware/field-box/pcb/` using `kicad/kicad:8.0` Docker image |
| `hardware/field-box/README.md` | Reference the carrier PCB as an alternative to perfboard assembly |

#### PCB scope (from ADR-P5-6)

**On-board:** Heltec V4.3 header sockets, I2C bus routing (JST connectors for PCF8574, PN532, MAX17048, OLED), SPI bus routing (display connector), I2S routing (MAX98357A connector), GPIO breakout (screw terminals for team buttons), WS2812B 3.3V-to-5V level shifter, M12 addon bus (GND, 5V, SDA, SCL, INT), power management (USB-C PD input, BMS connector, power switch), 4x M3 mounting holes.

**Off-board (separate modules):** Heltec V4.3 itself, PN532 NFC reader, MAX98357A + speaker, team buttons, keypad, display, LED ring, battery pack.

#### Phasing note

The schematic can be drafted from the current BOM and pin assignments
before physical prototypes exist. The layout (PCB routing and
placement) must wait for physical fit validation. CI DRC/ERC can run
on the schematic-only phase.

### Stream D2: Field-script editor blocks (BLOCKED on phase 2C)

When phase 2C ships `state.field{}` and `field.*`, add:

| File | Purpose |
|------|---------|
| `editor/blocks/field.js` | Block definitions: "for each node with role [role]", "send [cmd] to [node]", "get field owner of [node]", "nodes with common owner [list]" |
| `editor/generators/field.js` | Code generator functions for field blocks |
| `editor/examples/hold-all.json` | Example workspace for a multi-node hold-all mode using field blocks |

### Stream D3: Build guide photos (BLOCKED on phase 1 hardware)

Replace `<!-- PHOTO: description -->` placeholders in
`docs/build-guides/field-box.md` and `docs/build-guides/satellite.md`
with actual assembly photos once hardware prototypes are available.

### Validation (Phase D)

**PCB passes KiCad DRC and ERC (when design exists):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" kicad/kicad:8.0 \
  sh -c "kicad-cli sch erc /src/hardware/field-box/pcb/field-box-carrier.kicad_sch && \
         kicad-cli pcb drc /src/hardware/field-box/pcb/field-box-carrier.kicad_pcb"
```

**Expected:** exit 0. No ERC or DRC violations.

**Field-script editor round-trip (when phase 2C ships):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh && \
         ATALAIA_CORE_LIB=/tmp/c/libatalaia_core.so \
         python3 editor/tests/test_roundtrip.py --include-field"
```

**Expected:** exit 0. The hold-all example workspace generates
`field.lua` that passes simulator tests.

---

## Acceptance criteria

### AC-1: Blockly editor generates valid `node.lua` that passes simulator tests

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh && \
         ATALAIA_CORE_LIB=/tmp/c/libatalaia_core.so \
         python3 editor/tests/test_roundtrip.py"
```

**Expected:** exit 0. Domination and bomb example workspaces generate
Lua that passes all mode tests.

### AC-2: Generated Lua is readable and hand-editable

Manual review of the generated Lua for both example modes confirms:
2-space indentation, named local functions (not anonymous), `state.node{}`
at the top, blank lines between top-level blocks, no Blockly boilerplate
comments.

### AC-3: Editor ships in English and Portuguese

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  python3 tools/build_editor_i18n.py --check
```

**Expected:** exit 0. Both locale JSON files are generated from YAML
and contain all required keys.

### AC-4: Mode registry index format is defined and documented

`registry/schema/index.schema.json` validates the `index.json` format.
The schema includes `schema_version` (integer), `modes[]` with
`id`, `author`, `author_key_fingerprint`, `versions[]` with `version`,
`min_core`, `license`, `sha256`, `signature`, `url`, `size_bytes`,
`verified`.

### AC-5: Mode packages are Ed25519-signed and verifiable

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest registry/tests/ -v"
```

**Expected:** exit 0. Sign-verify round-trip succeeds. Tampered
packages are rejected. Revoked keys are rejected.

### AC-6: Registry CI runs mode tests and checks licences

The `atalaia-modes` repository's `.github/workflows/registry.yml`
contains `registry-lint`, `registry-test`, and `sandbox-escape` jobs
that validate all submissions.

### AC-7: At least one additional language beyond en/pt is supported

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  python3 tools/i18n_check.py
```

**Expected:** exit 0. Three locales (en, pt, es or fr) pass
completeness checks for the site and editor domains.

### AC-8: Built-in modes have `i18n/` with en and pt translations

`modes/domination/i18n/en.yaml`, `modes/domination/i18n/pt.yaml`,
`modes/bomb/i18n/en.yaml`, `modes/bomb/i18n/pt.yaml` all exist with
matching keys.

### AC-9: Carrier PCB schematic passes KiCad ERC (blocked on hardware)

When the PCB design exists:

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" kicad/kicad:8.0 \
  kicad-cli sch erc /src/hardware/field-box/pcb/field-box-carrier.kicad_sch
```

**Expected:** exit 0. No ERC violations.

### AC-10: Build guides exist for Field Box and Satellite

`docs/build-guides/field-box.md` and `docs/build-guides/satellite.md`
exist, contain BOM, assembly steps, firmware flashing, and
troubleshooting sections. Photos may be placeholder-marked.

### AC-11: CONTRIBUTING.md documents mode submission process

CONTRIBUTING.md contains a "Submitting a community mode" section
with the fork-and-PR workflow, signing instructions, review checklist
summary, verified badge criteria, and a link to the `atalaia-modes`
repository.

### AC-12: CI includes sandbox-escape test job

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh && \
         ATALAIA_CORE_LIB=/tmp/c/libatalaia_core.so \
         python3 registry/tests/test_sandbox_escape.py"
```

**Expected:** exit 0. Every known escape pattern fails safely.

---

## Assumptions about earlier phases

| # | Assumption | Phase | Confidence | Phases that depend on it | Fallback |
|---|-----------|-------|------------|--------------------------|----------|
| A1 | The script API surface is final for node scripts: `on`, `emit`, `every`, `after`, `cancel`, `game.*`, `score.*`, `state.node`, `cap`, `ui`, `audio`, `rand`, `log`, `params` | 0 | High | A, B1 | If a function is renamed or removed, update the corresponding Blockly block definition and code generator. The mapping is 1:1, so changes are mechanical. |
| A2 | `state.field{}` and `field.*` will follow the design in section 9: `field.nodes(role)`, `field.owner(node)`, `field.common_owner(list)`, `field.send(node, cmd)` | 2 | Medium | D2 | Defer field-script blocks until the API ships. Node-script blocks cover most community modes. |
| A3 | The mode package format (`mode.yaml` + `node.lua` + optional `field.lua`, `assets/`, `i18n/`, `tests/`) is stable | 0 | High | A, B2 | If the format changes, update the editor's manifest generator and the registry schema. |
| A4 | Ed25519 is the signing algorithm for firmware images | 1 | High | B2 | Use Ed25519 for mode signing regardless; it is a sound choice on its own merits. |
| A5 | The Heltec WiFi LoRa 32 V4.3 pin assignments in `hardware/field-box/README.md` are correct | 1 | Medium | D1 | The carrier PCB design waits for hardware validation. If pins change, the PCB layout changes too. The schematic uses Kconfig as the single source of truth. |
| A6 | The simulator's web view supports only one mode at a time | 0 | High | B1 | The editor needs a reload mechanism, not multi-mode support. `POST /api/reload` suffices. |
| A7 | Blockly v11.x `CodeGenerator` can be adapted for Lua output | External | Medium | A | Write a custom Lua generator subclass. Python and Dart generators exist as reference implementations. If the `CodeGenerator` API changes in a future Blockly release, the vendored version isolates the editor. |
| A8 | CI runs in GitHub Actions with the existing runner matrix | 0 | High | A, B, C | No change needed for editor, registry, or i18n CI. |
| A9 | The sandbox prevents all `io`, `os`, `require` access | 0 | High | B2 | Add a CI job that attempts known escape patterns as a regression net. |
| A10 | Community modes will be from the approved licence list | Design | High | B2 | The registry CI enforces this at submission time. |

---

## Parts that can start early

The following work streams depend only on the existing phase 0 APIs
(the script API and the simulator) and can begin immediately, before
any other phase 5 work completes:

| Work | Why it can start now | Depends on |
|------|---------------------|------------|
| **Blockly block definitions for node scripts** (Phase A) | The script API is stable and tested by 2 modes with 12 test files | A1 |
| **Custom Lua code generator** (Phase A) | Target Lua patterns are known from `modes/domination/node.lua` and `modes/bomb/node.lua` | A1, A7 |
| **Editor UI skeleton** (Phase A) | Static HTML/JS/CSS, no server component needed | -- |
| **Editor i18n YAML files** (Phase A) | Block labels and tooltips are known from the API surface | -- |
| **`build_editor_i18n.py`** (Phase A) | Thin YAML-to-JSON converter, same pattern as `build_site.py` | -- |
| **Registry index format and schema** (Phase B2) | Entirely independent of the platform code | -- |
| **Registry signing tooling** (Phase B2) | `keygen.py`, `sign.py`, `verify.py` use standard Ed25519 libraries | A4 |
| **Sandbox escape test battery** (Phase B2) | Tests the existing sandbox in `core/src/sandbox.c` | A9 |
| **Mode i18n YAML files for domination/bomb** (Phase C1) | Mode names, descriptions, and parameter labels are known | -- |
| **i18n completeness checker** (Phase C1) | Extends the existing `build_site.py --check` pattern | -- |
| **Build guide text** (Phase C2) | BOM, assembly steps, and firmware docs already exist | -- |
| **Community governance docs** (Phase C3) | Review checklist and badge criteria are defined in ADR-P5-8 | -- |
| **CONTRIBUTING.md update** (Phase C3) | Mode submission process documentation | -- |
| **PCB schematic draft** (Phase D1) | Pin assignments and BOM are documented; schematic can be drawn before physical validation | A5 (medium confidence) |

---

## Open questions for the maintainer

| # | Question | Recommended option chosen | Can be reviewed later? |
|---|----------|--------------------------|------------------------|
| Q1 | Which third language to add first (es, fr, de, other)? | **Spanish (es)**: largest overlap with the Portuguese-speaking airsoft community in Iberia and Latin America. | Yes. The choice of third language does not affect the i18n architecture. Any language can be added or swapped. |
| Q2 | Should the editor be a tab inside the simulator's web view or a separate page at `/editor/`? | **Separate page at `/editor/`** (per ADR-P5-2): simpler to develop and test independently; the editor and simulator share the same origin for API calls; a "Test" button opens/refreshes the simulator in a new tab. | Yes. Could be changed to a tabbed UI later without changing the API integration. |
| Q3 | Should the `atalaia-modes` registry repo be created immediately or wait until the signing tooling is ready? | **Create immediately** with a placeholder `index.json` (empty `modes[]`, `schema_version: 1`) and the CI skeleton. This lets contributors start submitting keys and sets up the PR workflow before any modes are submitted. | Yes. The repo can be created at any time. |
| Q4 | Should mode tarballs be hosted on the registry repo's GitHub Releases or on each author's own repo? | **Both options supported** (per ADR-P5-3): the `url` field in the index entry can point to any HTTPS location. The registry's own Releases are the default for authors who do not maintain a separate repo. | Yes. The URL is a field in the index entry; changing the hosting location is a metadata update. |
| Q5 | Should partial i18n translations be accepted for modes and the editor? | **Yes** (per ADR-P5-7): untranslated keys fall back to English. The site domain requires 100% completeness (existing CI enforcement). | Yes. The CI policy is configurable per domain. |
| Q6 | Maximum mode package size? | **1 MB** (per ADR-P5-3): large enough for sound clips and screen templates, small enough to prevent the registry from becoming a file-hosting service. Modes with larger assets may reference external downloads. | Yes. The limit is a CI configuration, not a protocol constraint. |

---

## Phase dependency graph

```
Phase A ──────> Phase B ──────> Phase D
  │            ╱      ╲          (blocked items)
  │     B1 (editor    B2 (registry)
  │     integration)     │
  │           │          │
  └───> Phase C ─────────┘
      (i18n, guides,
       community)
```

Phase A (editor) must complete first; its output (generated Lua and
the editor page) is a prerequisite for both Phase B streams. Phase B1
(editor-simulator integration) and Phase B2 (registry) are
independent and can proceed in parallel. Phase C (i18n, build guides,
community processes) can start in parallel with Phase B for streams
that do not depend on the editor (mode i18n, build guides, community
docs) and completes the remaining CI jobs. Phase D contains only
items blocked on earlier phases (carrier PCB on phase 1, field-script
blocks on phase 2C, build guide photos on phase 1 hardware).

Within each phase, the streams listed above can proceed in parallel
where no dependency exists between them.

---

## Summary of new files by directory

```
editor/
    index.html   editor.js   style.css
    vendor/blockly/           (vendored, ~2 MB)
    blocks/
        events.js  timers.js  state.js  game.js
        scoring.js  hardware.js  utilities.js  index.js
    generators/
        lua.js  events.js  timers.js  state.js  game.js
        scoring.js  hardware.js  utilities.js  manifest.js
    i18n/
        en.yaml  pt.yaml  es.yaml
    examples/
        domination.json  bomb.json
    tests/
        test_generator.js  test_manifest.js  test_roundtrip.py
        test_integration.py

registry/
    tools/
        keygen.py  sign.py  verify.py  package.py
    schema/
        index.schema.json
    tests/
        test_keygen.py  test_sign_verify.py  test_package.py
        sandbox_escape_patterns.lua  test_sandbox_escape.py

tools/
    build_editor_i18n.py
    build_firmware_i18n.py
    i18n_check.py

modes/
    domination/i18n/  en.yaml  pt.yaml
    bomb/i18n/        en.yaml  pt.yaml

firmware/esp32/
    i18n/  en.yaml  pt.yaml

docs/
    build-guides/
        README.md  field-box.md  satellite.md
    community/
        mode-review-checklist.md  verified-badge.md
    rfcs/
        0000-mode-registry-format.md

hardware/field-box/pcb/       (Phase D, blocked)
    field-box-carrier.kicad_sch
    field-box-carrier.kicad_pcb
    field-box-carrier.kicad_pro
    bom.csv  gerber/  README.md

atalaia-modes/ (separate repository)
    index.json
    schema/index.schema.json
    keys/  README.md  revoked.json
    .github/workflows/registry.yml
    README.md  CONTRIBUTING.md
```

Total: ~55 new files in the main repository + ~7 in the registry
repository. Modified files: ~6 (ci.yml, CONTRIBUTING.md, REUSE.toml,
web.py, live.py, build_site.py).
