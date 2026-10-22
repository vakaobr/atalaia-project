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
section 16). This plan was refreshed on 2026-10-22, after phases 2, 3
and 4 were built in software (section "Refresh 2026-10-22" below). The
plan phases are now listed **in the order to implement them**, each
marked *software, can be done now* or *needs hardware* (or *needs the
maintainer*), and small enough to be implemented, verified from a clean
copy and committed on its own. All builds and tests run in Docker; the
commands below are the repository's real ones.

---

## Refresh 2026-10-22 (after phases 2-4 software)

The 2026-10-18 plan (phases A-D) was written before the field
controller, the field scripts, the mode packages with roles, the
scenario system, the site server, firmware release signing and the
box's language tables existed. What changed, and why:

1. **Order.** The old phases were large and partly blocked on phases
   1-2. They are re-cut into 12 small software plan phases and 3
   hardware ones, the editor first (it needed nothing else), then the
   pieces each later one builds on (decision P5R-1). The mapping is in
   the table below.
2. **Field scripts are not blocked.** `state.field{}` and `field.*`
   shipped in phase 2, so the editor's field blocks are part of plan
   phase 1, not of the old phase D (P5R-3).
3. **Where the editor lives.** In the simulator, at `/editor/`, for
   whoever writes a mode; the GM console gets a block view of its
   scenario builder later (plan phase 7), because a box runs only
   built-in scripts and what a GM can install at the field is a
   scenario (P5R-2).
4. **Blockly 13.3.0, vendored**, not 11.x; one blocks file and one
   generator file in `simulator/atalaia_sim/editor/`, not sixteen files
   in `editor/` (P5R-3, P5R-4).
5. **Tests.** The generator is JavaScript and the dev image has no
   JavaScript runtime, so the generator's unit tests and the round trip
   run in Chromium (Playwright) in the GM console's test image,
   `python3 tools/docker_editor.py`, CI job `editor`; the plain checks of
   the editor's files run in `tools/check.sh` (P5R-6). Mode tests are YAML
   run by `python3 -m atalaia_sim test`; Python tests are `unittest`.
6. **Registry.** A registry package cannot reach a box's node script
   (K10); it can be a scenario or a field-script package for the
   controller, or a mode proposed for the built-in set (P5R-8). Signing
   reuses the firmware's release scheme and tooling (P5R-7). The
   `atalaia-modes` repository waits for the maintainer (P5-3, P5R-9).
7. **Languages.** Each domain keeps the format it was built with; modes
   already carry Portuguese in `mode.yaml` (AC-8 met); the box's texts
   are a runtime table; the third language is German, then Traditional
   Chinese (Taiwan), as the maintainer asked (P5-1, P5R-10, P5R-11).
8. **Sandbox battery** in this repository's CI with the core's tests,
   not only in the registry's (P5R-13).

### Old phases to new plan phases

| Old | Content | New plan phases |
|-----|---------|-----------------|
| A | Visual mode editor | 1 (built), 3 |
| B1 | Editor and simulator | 2 |
| B2 | Mode registry, signing, sandbox job | 4, 5, 6, 8 |
| C1 | i18n expansion | 10, 11 (mode i18n: met by P4R22) |
| C2 | Build guides | 12, HW2 |
| C3 | Community processes | 9 |
| D1 | Carrier PCB | HW1 |
| D2 | Field-script blocks | 1 (no longer blocked) |
| D3 | Build guide photos | HW2 |
| (new) | Block view of the console's scenario builder | 7 |
| (new) | A community scenario and a community mode on real boxes | HW3 |

---

## How each plan phase is verified

Every plan phase ends with the same check from a clean copy as phase 4
(`docs/phase-4-site-server/PLAN.md`, "How each plan phase is verified"):
a fresh clone, a freshly built `atalaia-dev` image and an empty build
folder, then

```sh
docker run --rm -v "$PWD:/src" atalaia-dev:verify sh -c "BUILD=/tmp/c sh tools/check.sh"
```

(the simulator's tests include `simulator/tests/test_editor_files.py`),
plus, depending on what the plan phase touches:

| Touches | Command | CI job |
|---------|---------|--------|
| The mode editor (`simulator/atalaia_sim/editor/`) | `python3 tools/docker_editor.py` (Chromium; the generator's unit tests and the round trip of every example) | `editor` |
| The GM console | `python3 tools/docker_console.py` | `console` |
| Modes run through the core in Dart, the app | `python3 tools/docker_app.py` | `flutter-test` and the Android builds |
| The core's C | ASan/UBSan as CI's `sanitizers` job | `sanitizers` |
| Firmware C (box texts, fonts) | `python3 tools/docker_fw.py test`, then `build`, `modem`, `pod` (0 warnings); not `wokwi` (R7) | `firmware-test`, `esp32-*` |
| The site server | `python3 tools/docker_server.py test` | `server` |
| The project page | `python3 tools/build_site.py --check` (also in `check.sh`) | `core` |
| Licences | `reuse lint` in a copy without build output | `licensing` |

---

## Scope

### In scope (software, buildable and testable now)

- The visual mode editor: blocks for the node and field script API,
  readable Lua, `mode.yaml`, English and Portuguese, the round trip
  against hand-written modes (plan phase 1, built); live testing in the
  simulator (2); geo, GM commands, more roles and kinds (3).
- Mode packages: archive format, Ed25519 signing with the firmware's
  release scheme, the registry index schema, shared vectors (4); the
  sandbox-escape battery (5); the controller installing signed packages
  from an index (6).
- A block view of the GM console's scenario builder (7).
- The registry repository's files as a template (8); the submission
  process, review checklist and verified badge in the docs (9).
- German in every domain, a cross-domain language check (10);
  Traditional Chinese (11).
- Build guides for the other node types, rendered on the project page
  (12).

### Needs hardware, or the maintainer

- Carrier PCB (HW1), after three perfboard Field Boxes work (ADR-P5-6).
- Build guide photos (HW2).
- A registry scenario and a community mode on real boxes (HW3).
- Creating the `atalaia-modes` repository and publishing its index
  (P5-3; the maintainer's account).
- Whether boxes may ever load signed community node scripts at run time
  (P5R-8, for the maintainer; not in this plan).

### Out of scope

- Ratings, usage statistics and hosted servers in the community hub
  (post-v1).
- Turning hand-written Lua back into blocks (the editor's files are the
  blocks; the Lua is generated).
- The hit-scoring target addon's PCB (tracked with phase 4 HW2).

---

## Constraints (from ADR.md, with the 2026-10-22 amendments)

| # | Constraint | How the plan respects it |
|---|------------|--------------------------|
| 1 | **Amended 2026-10-22:** a `CodeGenerator` (Blockly's `LuaGenerator` class) with the project's style; Blockly 13.3.0 vendored with checksums; the round trip against hand-written modes in CI (P5R-3, P5R-4, P5R-6) | Plan phases 1, 3, 7 |
| 2 | **Amended 2026-10-22:** the mode editor is served by the simulator at `/editor/`; `POST /api/reload` keeps ADR-P5-2's shape and needs `field.lua` in the web view; the console's scenario builder gets the block view (P5R-2, P5R-5) | Plan phases 1, 2, 7 |
| 3 | **Amended 2026-10-22:** boxes run built-in scripts only (K10); registry packages reach the field as controller packages (scenarios, field scripts); node scripts reach boxes through `modes/` and a signed firmware release (P5R-8) | Plan phases 4, 6, 8 |
| 4 | **Amended 2026-10-22:** Ed25519 over a text manifest like the firmware's (`atalaia-mode-package-v1`, id, version, size, sha256), key ids as release keys', tooling like `tools/firmware_release.py`, shared vectors (P5R-7) | Plan phase 4 |
| 5 | Seven approved SPDX identifiers; an RFC to add one (ADR-P5-5) | Plan phases 1 (the Mode tab), 4, 9 |
| 6 | Carrier PCB after 3+ perfboard boxes; KiCad 8; CERN-OHL-S-2.0 (ADR-P5-6) | HW1 |
| 7 | **Amended 2026-10-22:** each language domain keeps its built format with a parity test; modes translate in `mode.yaml`; the box's texts are a runtime table; German, then Traditional Chinese (P5R-10, P5R-11) | Plan phases 1, 10, 11 |
| 8 | PR-based curation, the 12-item checklist as amended, verified badge (ADR-P5-8) | Plan phases 8, 9 |
| 9 | SPDX headers on every file; GPL-3.0-or-later for the simulator and its editor, AGPL-3.0-or-later for the controller and console, CC-BY-SA-4.0 for docs; vendored libraries keep their licence in `REUSE.toml` | `reuse lint` in every plan phase |
| 10 | Each plan phase verified from a clean copy and committed on its own; firmware without Wokwi while R7 lasts | "How each plan phase is verified" |

---

## Implementation order

| # | Plan phase | Scope | Software now / hardware | Depends on | Size | Status |
|---|------------|-------|-------------------------|------------|------|--------|
| 1 | Visual mode editor | blocks for node and field scripts, Lua and `mode.yaml` generator, the page in the simulator, en + pt, round trip (AC-1 to AC-3) | Software, now | -- | M | **Built 2026-10-22** |
| 2 | Editor and simulator | `field.lua` in the web view, `POST /api/reload`, the editor's "Test" button | Software, now | 1 | M | Next |
| 3 | Editor completeness | geo blocks (zones, distances, `position.fix`), GM commands, several roles, modifiers and role packages, screen names from `assets/screens/` | Software, now | 1 | M | |
| 4 | Mode packages and signing | archive format, `tools/mode_package.py` (pack, keygen, sign, verify), `registry/schema/index.schema.json`, shared vectors, licence check (AC-4, AC-5) | Software, now | -- | M | |
| 5 | Sandbox-escape battery | escape patterns as core C tests and through the simulator, in CI (AC-12) | Software, now | -- | S | |
| 6 | Signed packages in the controller | import from an index (signature, revocation, size, licence), the author and an "unverified" warning in the console | Software, now | 4 | M | |
| 7 | Scenario blocks in the console | a block view of the scenario builder writing the same YAML, en + pt, console browser tests | Software, now | 1 | M | |
| 8 | Registry repository template | `index.json`, `keys/`, `revoked.json`, the registry CI workflow as files under `registry/template/` (AC-6 in this repository) | Software, now; publishing needs the maintainer | 4, 5 | S | |
| 9 | Community processes | CONTRIBUTING.md "Submitting a community mode", review checklist, verified badge, RFC for the package format (AC-11) | Software, now | 4, 8 | S | |
| 10 | German | site, console, editor, app and box texts in German; `tools/i18n_check.py` across domains (AC-7) | Software, now (on a real box: with the boards) | -- | M | After the maintainer confirms P5R-10 |
| 11 | Traditional Chinese (Taiwan) | the same, with CJK glyphs in the box's fonts and the app | Software, now; flash budget on the box to check | 10 | M | |
| 12 | Build guides for other node types | satellite, I/O pod, target addon as text, rendered on the project page (AC-10 text) | Software, now | -- | S | |
| HW1 | Carrier PCB | KiCad schematic and layout, ERC/DRC in CI (AC-9) | Needs hardware (3 perfboard boxes) | phase 1 | -- | |
| HW2 | Build guide photos | photos in place of the placeholders | Needs hardware | 12 | -- | |
| HW3 | Community content on the field | a registry scenario on a real field; a community mode merged into `modes/` and shipped in a signed release | Needs hardware | 6, phase 2 F | -- | |

Sizes as phase 4's: S about a day of agent work, M two to three days.
Plan phases 4-6 and 7 can run in parallel worktrees with 2-3; 10-12 are
independent of the rest.

**Next: plan phase 2 (editor and simulator).**

---

## Plan phase 1: Visual mode editor

*Software, can be done now. Depends on nothing. Size M. **Built
2026-10-22** (decisions P5A-1 to P5A-7).*

### Goal

The old phase A, with field scripts: a Blockly editor that writes a
readable `node.lua`, `field.lua` and `mode.yaml`, in English and
Portuguese, whose output passes the simulator's mode tests.

### Built

| File | What |
|------|------|
| `simulator/atalaia_sim/editor/index.html`, `editor.css` | The page: toolbar (new, open, save, examples, language), a tab per script (boxes, controller) and the Mode tab, the generated files with download, the problems list |
| `simulator/atalaia_sim/editor/blocks.js` | 37 block definitions (memory, events, timers, game, score, box hardware, settings, field, utilities) and the toolbox of each script kind, with Blockly's logic, numbers, text, lists, variables and functions |
| `simulator/atalaia_sim/editor/generator.js` | The Lua generator (Blockly's `LuaGenerator` class) and the `mode.yaml` generator; problems with the block they point at |
| `simulator/atalaia_sim/editor/editor.js` | Two workspaces, regeneration on every change, the draft in the browser, save and open as JSON (`atalaia-mode-editor` v1), `window.atalaiaEditor` for the tests |
| `simulator/atalaia_sim/editor/i18n/en.json`, `pt.json` | Every text of the page and the blocks (Blockly's own from its `msg/pt.js`) |
| `simulator/atalaia_sim/editor/examples/domination.json`, `holdall.json` | Domination (boxes only) and Hold-All Domination (boxes and a field script) as blocks |
| `simulator/atalaia_sim/editor/vendor/blockly/` | Blockly 13.3.0, unmodified, with its checksums (`README.md`) |
| `simulator/atalaia_sim/web.py` | Serves `/editor/` (known suffixes only, its own CSP) |
| `simulator/tests/test_editor_files.py` | Routes and headers, vendored checksums, language keys, examples (in `check.sh`) |
| `simulator/editor_tests/test_editor.py`, `run.sh` | 15 browser tests: the generator's unit tests, the two round trips, the page in both languages, examples, save, open, draft, problems |
| `tools/docker_editor.py`, CI job `editor` | The browser tests in the GM console's image |
| `REUSE.toml` | Apache-2.0 for the vendored Blockly files |

### Validation

```sh
docker run --rm -v "$PWD:/src" atalaia-dev sh -c "BUILD=/tmp/c sh tools/check.sh"
python3 tools/docker_editor.py
```

Both exit 0: the examples' generated modes pass all 6 Domination and 6
Hold-All tests and give the hand-written manifests.

---

## Plan phase 2: Editor and simulator

*Software, can be done now. Depends on 1. Size M.*

- **`field.lua` in the web view**: `LiveGame` runs the mode's field
  script as the YAML tests do (`Simulation` already can), so modes like
  Hold-All play live; several nodes from `--node` (as today).
- **`POST /api/reload`** (ADR-P5-2): JSON with `node_lua`, `field_lua`,
  `mode_yaml`, `params`; the scripts load in the core first; errors in
  the body, never as 4xx/5xx; the previous game keeps running on an
  error; the same Host and JSON checks as `/api/action`; a size limit
  (the controller's 1 MB).
- **The editor's "Test" button**: posts the generated files, opens the
  simulator's page (same origin), shows load errors in the problems list.
- Tests: `simulator/tests/test_live.py` (reload: ok, syntax error kept
  out, field script running, size limit), a browser test of the Test
  button in `simulator/editor_tests/`.

## Plan phase 3: Editor completeness

*Software, can be done now. Depends on 1. Size M.*

- Geo blocks (`geo.distance`, `geo.in_zone` with a circle or polygon,
  the `position.fix` data), GM commands (`commands:` in `mode.yaml` and
  their `cmd.<name>` handlers), several roles per mode (a role per node
  workspace or a role block), `kind: modifier` and `role`, screen names
  offered from a mode folder's `assets/screens/`.
- A third example (Master and Satellites or Last Stand) in the round
  trip; the editor's problems for a role without its inputs.

## Plan phase 4: Mode packages and signing

*Software, can be done now. Size M.* (ADR-P5-3 and P5-4 as amended.)

- The archive: a tar of the mode folder with the id as its root, made
  reproducibly (sorted, fixed times and owners) so its SHA-256 is
  stable; at most 1 MB; only the files the controller accepts.
- `tools/mode_package.py`: `pack`, `keygen`, `pubkey`, `sign`, `verify`,
  modelled on `tools/firmware_release.py`; the manifest
  `atalaia-mode-package-v1` (id, version, size, sha256) signed with
  Ed25519; shared code with `controller/atalaia_controller/firmware_release.py`.
- `registry/schema/index.schema.json` (`schema_version`, modes,
  versions, `key_id`, `signature`, `license`, `verified`); the licence
  list of ADR-P5-5; `protocol/vectors/mode_package.json` with a fixed
  test key (RFC 8032's test vector 1 key, so the signature is checkable
  from the RFC).
- Tests: `unittest` for pack, sign, verify, tampering, wrong id or
  version, revoked key, licence and size refusals.

## Plan phase 5: Sandbox-escape battery

*Software, can be done now. Size S.*

Escape patterns (`io`, `os`, `require`, `load`, `loadfile`, `dofile`,
`debug`, `string.dump`, `rawget(_G, ...)`, metatables of strings and
the API tables, `coroutine` tricks, `collectgarbage`, bytecode, the
instruction and memory limits) as C tests next to `test_sandbox` in
`core/tests/test_node.c` and a Python test through the ctypes bindings
for node and field scripts; ASan/UBSan.

## Plan phase 6: Signed packages in the controller

*Software, can be done now. Depends on 4. Size M.*

The controller fetches an index (a URL, or a file for an offline
field), verifies each package (signature, key not revoked, size,
licence) and installs scenarios and field-script packages through the
existing upload checks; the console shows who signed a package and
"not reviewed by the project" for unverified ones. Store schema bump,
controller tests, console browser tests.

## Plan phase 7: Scenario blocks in the console

*Software, can be done now. Depends on 1. Size M.*

A block view of the scenario builder (objectives, their types,
dependencies, reveals and effects, the boxes they name) that writes the
same YAML manifest, checked by the same `POST /api/v1/scenarios/check`;
Blockly vendored for the console as its other libraries
(`controller/console/src/lib/`), the console's CSP adjusted for its
styles only; en + pt; console browser tests.

## Plan phase 8: Registry repository template

*Software, can be done now; publishing needs the maintainer. Depends on
4, 5. Size S.*

`registry/template/`: `index.json` (empty, `schema_version: 1`),
`keys/README.md`, `keys/revoked.json`, the registry CI workflow
(`registry-lint`, `registry-test`, `sandbox-escape`) using this
repository's tools, and a test that runs that workflow's commands on a
sample submission. The maintainer creates `atalaia-modes` from it.

## Plan phase 9: Community processes

*Software, can be done now. Size S.*

CONTRIBUTING.md "Submitting a community mode" (the editor, the
package, signing, the PR, the checklist, the badge), the review
checklist and badge criteria as amended, and an RFC for the package
format, the manifest and the index.

## Plan phase 10: German

*Software, can be done now, after the maintainer confirms P5R-10. Size
M.*

`site/i18n/de.yaml` and the site's language switcher; the console's,
the editor's and the app's tables; a German column in `box_text.c`
(join key 15 accepts `de`); `tools/i18n_check.py` running every
domain's parity check. A native speaker reviews before release.

## Plan phase 11: Traditional Chinese (Taiwan)

*Software, can be done now; the box's flash budget to check. Depends
on 10. Size M.*

As 10 for `zh-TW`, with a CJK subset in the box's fonts
(`tools/gen_box_fonts.py`) sized against the image's free space, and a
CJK font for the app and the pages.

## Plan phase 12: Build guides for other node types

*Software, can be done now. Size S.*

Text guides for the Satellite, the I/O pod and the target addon in the
manner of `hardware/field-box/BUILD.md`, with `<!-- PHOTO: ... -->`
placeholders, linked and rendered on the project page.

## HW1-HW3

*Need hardware.* HW1 the carrier PCB (ADR-P5-6's gates, KiCad 8 ERC
and DRC in CI); HW2 the build guides' photos; HW3 a registry scenario
on a real field and a community mode shipped in a signed firmware
release.

---

## Acceptance criteria

| # | Criterion | Plan phase | Status |
|---|-----------|------------|--------|
| AC-1 | The Blockly editor generates a valid `node.lua` (and `field.lua`) that passes simulator tests | 1 | **Met in software (2026-10-22)**: `python3 tools/docker_editor.py`, the Domination and Hold-All round trips |
| AC-2 | Generated Lua is readable and hand-editable | 1 | **Met (2026-10-22)**: checked by `assertReadable` and by review of the examples' output |
| AC-3 | The editor ships in English and Portuguese | 1 | **Met (2026-10-22)**: `test_page_in_english_and_portuguese`, `test_languages_have_the_same_keys` |
| AC-4 | The registry index format is defined and documented | 4 | Pending |
| AC-5 | Mode packages are Ed25519-signed and verifiable | 4 | Pending |
| AC-6 | Registry CI runs mode tests and checks licences | 8 | Pending (the repository needs the maintainer) |
| AC-7 | At least one language beyond en/pt on the site | 10 | Pending |
| AC-8 | Built-in modes carry English and Portuguese texts | -- | **Met differently**: in `mode.yaml`'s `i18n:` (P4R22), every built-in mode |
| AC-9 | The carrier PCB schematic passes KiCad ERC | HW1 | Pending (needs hardware) |
| AC-10 | Build guides exist for the Field Box and the Satellite | 12, HW2 | Field Box done (`hardware/field-box/BUILD.md`); the rest pending |
| AC-11 | CONTRIBUTING.md documents mode submission | 9 | Pending |
| AC-12 | CI includes a sandbox-escape test job | 5 | Pending (`test_sandbox` covers the basics) |

---

## Assumptions about earlier phases (re-checked 2026-10-22)

| # | Assumption | Status 2026-10-22 |
|---|-----------|-------------------|
| A1 | The node script API is final | Built and stable; grown since with `game.teams()` and `geo.*` (plan phase 3 adds geo blocks) |
| A2 | `state.field{}` and `field.*` follow spec section 9 | Built (phase 2); the editor has them |
| A3 | The mode package format is stable | Built, with kinds, roles, `needed`, commands and `i18n:` |
| A4 | Ed25519 for firmware images | Built (`protocol/firmware-update.md`); mode packages reuse it (P5R-7) |
| A5 | The Heltec V4.3 pin map | Re-done with GNSS (2026-10-21); still to be proved in a built box |
| A6 | The simulator's web view runs one mode at a time | Holds; it does not run `field.lua` yet (plan phase 2) |
| A7 | Blockly's `CodeGenerator` can target Lua | Holds: Blockly ships a `LuaGenerator`; the editor uses its class |
| A8 | CI on GitHub Actions | Holds; a new `editor` job |
| A9 | The sandbox blocks `io`, `os`, `require` | Holds (`test_sandbox`); plan phase 5 widens the battery |
| A10 | Community modes use an approved licence | Holds; the editor offers only those |

---

## Open questions for the maintainer

The 2026-10-18 questions are answered in `docs/review/decisions-to-review.md`
(P5-1 to P5-7). New ones from this refresh, with the recommendation used
for now (all open):

| # | Question | Recommended |
|---|----------|-------------|
| P5R-8 | May boxes ever load signed community node scripts at run time? | Not in phase 5: community node scripts reach boxes by joining `modes/` and a signed firmware release |
| P5R-9 | When to create `atalaia-modes`? | After plan phase 8, from its template |
| P5R-10 | Third language: German first, then Traditional Chinese? | Yes, German first (no new glyphs on the box) |
