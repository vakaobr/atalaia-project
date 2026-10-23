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
   **Later on 2026-10-22 the maintainer decided P5R-8:** a box may get,
   from its field controller and only between games, the signed modes a
   game needs that it lacks (plan phase 13, P5B-8 to P5B-17).
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
| (new, P5R-8) | Missing modes sent to boxes from the GM console | 13 |

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
  from an index (6); boxes getting the signed modes a game needs that
  they lack, from the GM console, between games (13, the maintainer's
  P5R-8).
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
- Signed modes sent to boxes from the GM console (P5R-8, decided by the
  maintainer 2026-10-22): plan phase 13 in software; on real boxes in
  HW3; a box trusts mode keys built into its firmware only (P5B-9, the
  maintainer's answer of 2026-10-22).

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
| 3 | **Amended 2026-10-22:** boxes run built-in scripts only (K10); registry packages reach the field as controller packages (scenarios, field scripts); node scripts reach boxes through `modes/` and a signed firmware release (P5R-8). **Amended again 2026-10-22 (the maintainer's P5R-8):** a box may also run a signed mode package it fetched from its controller for a game, checked with keys built into its firmware (P5B-8 to P5B-17) | Plan phases 4, 6, 8, 13 |
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
| 2 | Editor and simulator | `field.lua` in the web view, `POST /api/reload`, the editor's "Test" button | Software, now | 1 | M | **Built 2026-10-22** |
| 3 | Editor completeness | geo blocks (zones, distances, `position.fix`), GM commands, several roles, modifiers and role packages, screen names from `assets/screens/` | Software, now | 1 | M | **Built 2026-10-22** |
| 4 | Mode packages and signing | archive format, `tools/mode_package.py` (pack, keygen, sign, verify), `registry/schema/index.schema.json`, shared vectors, licence check (AC-4, AC-5) | Software, now | -- | M | **Built 2026-10-22** |
| 5 | Sandbox-escape battery | escape patterns as core C tests and through the simulator, in CI (AC-12) | Software, now | -- | S | **Built 2026-10-22** |
| 6 | Signed packages in the controller | import from an index (signature, revocation, size, licence), the author and an "unverified" warning in the console | Software, now | 4 | M | **Built 2026-10-22** |
| 13 | Missing modes from the GM console | P5R-8: the console's *Send missing modes* in the invite dialog; join key 16; a box fetches the signed packages it lacks over Wi-Fi HTTPS, checks them with its firmware's mode keys and the sandbox, keeps them on LittleFS (numbered 13 so the other numbers stay as P5R-1 has them; built here, after 6) | Software, now (box side host-tested); on real boxes: HW3 | 4, 5, 6 | L | 13a **built 2026-10-22** (P5D-1 to P5D-12); 13b (the box) **built 2026-10-22** (P5E-1 to P5E-14) |
| 7 | Scenario blocks in the console | a block view of the scenario builder writing the same YAML, en + pt, console browser tests | Software, now | 1 | M | **Built 2026-10-22** (P5F-1 to P5F-12) |
| 8 | Registry repository template | `index.json`, `keys/`, `revoked.json`, the registry CI workflow as files under `registry/template/` (AC-6 in this repository) | Software, now; publishing needs the maintainer | 4, 5 | S | **Built 2026-10-22** (P5G-1 to P5G-11) |
| 9 | Community processes | CONTRIBUTING.md "Submitting a community mode", review checklist, verified badge, RFC for the package format (AC-11) | Software, now | 4, 8 | S | **Built 2026-10-22** (P5G-12 to P5G-14) |
| 10 | German | site, console, editor, app and box texts in German; `tools/i18n_check.py` across domains (AC-7) | Software, now (on a real box: with the boards) | -- | M | **Built 2026-10-22** (P5H-1 to P5H-11; German drafted by an AI model, native review pending) |
| 11 | Traditional Chinese (Taiwan) | the same, with CJK glyphs in the box's fonts and the app | Software, now; flash budget on the box to check | 10 | M | |
| 12 | Build guides for other node types | satellite, I/O pod, target addon as text, rendered on the project page (AC-10 text) | Software, now | -- | S | **Built 2026-10-22** (P5J-1 to P5J-14; photos: HW2) |
| HW1 | Carrier PCB | KiCad schematic and layout, ERC/DRC in CI (AC-9) | Needs hardware (3 perfboard boxes) | phase 1 | -- | |
| HW2 | Build guide photos | photos in place of the placeholders | Needs hardware | 12 | -- | |
| HW3 | Community content on the field | a registry scenario on a real field; a community mode merged into `modes/` and shipped in a signed release; a signed mode a box lacked, sent from the GM console (plan phase 13) | Needs hardware | 6, 13, phase 2 F | -- | |

Sizes as phase 4's: S about a day of agent work, M two to three days.
Plan phases 4-6 and 7 can run in parallel worktrees with 2-3; 10-12 are
independent of the rest; 13 needs 4, 5 and 6 (its 13a and 13b can then
run in parallel). Sizes: L about a week of agent work.

**Next (2026-10-22, plan phases 1-10, 12 and 13 built in software): the review of the
German by German-speaking players (P5H-5); the leftover contract cases for the
mode-package endpoints (the editor making packages is built, P5I-1 to P5I-6); plan phase 13
on real boxes in HW3.**

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

*Software, can be done now. Depends on 1. Size M. **Built 2026-10-22**
(decisions P5B-1 to P5B-7).*

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

**Note 2026-10-22 (as built).** The web view already ran a mode's
`field.lua`: `LiveGame` drives a `Simulation`, which has run it since
phase 2 (`serve ../modes/holdall --node ...` scored through the
controller's script). What was missing was seeing it, so the view now
shows the controller (P5B-1). The reload's errors are objects, not
strings, so the editor can place them (P5B-2).

### Built

| File | What |
|------|------|
| `simulator/atalaia_sim/mode.py` | `mode_from_text`: a mode from its files' text (`load_mode` reads a folder through it); YAML that does not parse is a `ModeError` |
| `simulator/atalaia_sim/live.py` | `LiveGame.reload` (the same core, teams, seed and sandbox limits; the given boxes, else those whose role the mode has, else one; parameters checked; the scripts load first, and on an error the running game is untouched; the new game starts with its clock running; a reset replays the reloaded mode); `script_errors` (script.error and script.halted with the script and line they name); the snapshot's `controller` (status, error, memory, points, the commands it sent, its log), `reloads` and `script_errors` |
| `simulator/atalaia_sim/web.py` | `POST /api/reload`: the Host check and JSON only as for actions, 1 000 000 bytes at most (`413` above), a body of the wrong shape `400`, a mode that does not load `200 {"status": "error", "errors": [...]}`, else `200 {"status": "ok", "errors": [errors on game.start], "reloads", "generation", "mode", "nodes"}` |
| `simulator/atalaia_sim/web/index.html`, `app.js` | The *Field controller* panel: `field.lua`'s state, points, the commands it sent to boxes, its log |
| `simulator/atalaia_sim/editor/generator.js` | `lineBlocks`: which block each generated line comes from (Blockly's statement prefix as marker lines, used only when the output without them is the real one) |
| `simulator/atalaia_sim/editor/editor.js`, `index.html`, `editor.css`, `i18n/*.json` | *Test in the simulator* with a *Boxes* count; a status line with *Open the game* (a tab named `atalaia-sim`, which the *Simulator* link uses too); the simulator's errors in the problems list, grouped by message with the boxes named, on their blocks as warnings, polled each second while the tested mode runs and cleared when the generated files change |
| `simulator/tests/test_live.py` | 7 new tests: Hold-All live with its controller, reload (ok, kept boxes, errors with script and line, the running game kept, errors on game.start), the server's rules for reload (403, 415, 400, 413, 404) |
| `simulator/editor_tests/test_editor.py` | 3 new browser tests: the Test button playing Hold-All in the simulator's page with its controller scoring; errors back on their blocks (on loading and while running) and cleared by an edit; every line of both examples mapped to its block |

### Validation

```sh
docker run --rm -v "$PWD:/src" atalaia-dev sh -c "BUILD=/tmp/c sh tools/check.sh"
python3 tools/docker_editor.py
```

A mode author now: builds the mode from blocks at `/editor/`, sets how
many boxes to try it with, presses *Test in the simulator*, and plays it
in the simulator's tab (holding the boxes' buttons, watching the
controller's script); an error the scripts hit, on loading or while the
game runs, appears in the editor's problems list and on the block that
caused it.

## Plan phase 3: Editor completeness

*Software, can be done now. Depends on 1. Size M.*

- Geo blocks (`geo.distance`, `geo.in_zone` with a circle or polygon,
  the `position.fix` data), GM commands (`commands:` in `mode.yaml` and
  their `cmd.<name>` handlers), several roles per mode (a role per node
  workspace or a role block), `kind: modifier` and `role`, screen names
  offered from a mode folder's `assets/screens/`.
- A third example (Master and Satellites or Last Stand) in the round
  trip; the editor's problems for a role without its inputs.

**Built 2026-10-22** (decisions P5C-1 to P5C-7). Code beats the plan in
one place: a GM command reaches a box as `cmd.mode` with its name (RFC
0001 Amendment 5, the Medic Kit's `refill`), not as `cmd.<name>`, so the
handler block is "when the mode command *name* arrives" (P5C-2).

| File | What |
|------|------|
| `simulator/atalaia_sim/editor/blocks.js` | 10 new blocks: *Places* (`geo.distance`, `geo.in_zone`, a circle, an area and its corners, "the event has a position"), *GM commands* (the declaration, "when the mode command ... arrives"), the controller's "send the mode command ..."; event values `lat`, `lon`, `acc`, `player`, `role`, `strength`; a list's item; the box's built-in screens and the mode's own as screen blocks in the toolbox |
| `simulator/atalaia_sim/editor/generator.js` | Their Lua; `mode.yaml` with `kind`, several roles (`requires` from the script or the role's own, `optional`, `needed: false`), `commands:` and their Portuguese labels; `modeRoles`, `testNodes`; problems: `problem_no_role`, `problem_bad_role`, `problem_role_twice`, `problem_role_input_unhandled`, `problem_role_no_input`, `problem_role_unknown`, `problem_command_twice`, `problem_command_unhandled`, `problem_screen_unknown`, `problem_polygon_points`; a for-each loop's variable is no longer declared at the top |
| `simulator/atalaia_sim/editor/editor.js`, `index.html`, `editor.css`, `i18n/*.json` | The *Mode* tab's kind, roles (a row each: name, inputs, *needed to start*) and screens (*Add screens…*, checked: a template name, at most 4096 bytes, `template:` naming the file); the screens in the saved project (`screens`, optional) and as preview tabs; *Test* starts a box per role |
| `simulator/atalaia_sim/editor/examples/master_satellites.json` | Master and Satellites as blocks, with its three screen files |
| `simulator/editor_tests/test_editor.py` | 6 new browser tests (geo, GM commands, roles and kinds, the Mode tab, the third round trip, Test with two roles); the line map checked on the third example |
| `simulator/tests/test_editor_files.py` | The third example: its roles and screens are the mode's |

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

**Built 2026-10-22** (decisions P5C-8 to P5C-13; the format is
`protocol/mode-packages.md`). The archive is an uncompressed ustar tar in
one canonical form that readers enforce by packing again (P5C-8); the
manifest has P5B-10's `kind` and `min_tier` lines (P5C-9).

| File | What |
|------|------|
| `controller/atalaia_controller/mode_package.py` | The shared code: `pack`, `unpack` (strict), the manifest, the release text, `verify` (fails closed, in a fixed order), `sign_release`, `parse_index`, `parse_revoked` |
| `tools/mode_package.py` | `pack`, `keygen`, `pubkey`, `sign`, `verify`, `index` |
| `tools/mode_package_vectors.py`, `protocol/vectors/mode_package.json` | The shared vectors (`--check` in `check.sh` and CI's protocol job) |
| `registry/schema/index.schema.json`, `revoked.schema.json`, `examples/` | The index's and revocation list's JSON Schemas, a valid and 10 invalid examples (CI's protocol job, `check-jsonschema`) |
| `protocol/mode-packages.md` | The format and the checks |
| `controller/tests/test_mode_package.py` | 17 tests: the vectors, every built-in mode as a package the controller takes, licence, size, names, manifests that are not the archive's, the tool's commands |

**Leftover built 2026-10-22** (decisions P5I-1 to P5I-6): the mode editor makes
the package itself. *Make the package* downloads the canonical, unsigned archive
of the mode it edits, made in the page and byte for byte what `pack` makes of the
same files, and shows the manifest a mode key will sign with the exact `sign` and
`verify` commands; signing stays offline on the command line.

| File | What |
|------|------|
| `simulator/atalaia_sim/editor/package.js` | The canonical ustar writer (as `mode_package.pack`, with its refusal codes), the manifest, SHA-256 (FIPS 180-4), the editor's package of its generated files |
| `simulator/atalaia_sim/editor/editor.js`, `index.html`, `editor.css`, `i18n/*.json` | *Make the package* and its panel (the manifest, size, SHA-256, the commands; refusals with the reason), in English, Portuguese and German |
| `simulator/editor_tests/test_editor.py` | 5 browser tests: the shared vectors, every built-in mode, refusals alike, the three examples through the button with `sign` and `verify` run as shown, refusals in the page |
| `simulator/tests/test_editor_files.py` | `package.js` served as JavaScript, naming no network address |

## Plan phase 5: Sandbox-escape battery

*Software, can be done now. Size S.*

Escape patterns (`io`, `os`, `require`, `load`, `loadfile`, `dofile`,
`debug`, `string.dump`, `rawget(_G, ...)`, metatables of strings and
the API tables, `coroutine` tricks, `collectgarbage`, bytecode, the
instruction and memory limits) as C tests next to `test_sandbox` in
`core/tests/test_node.c` and a Python test through the ctypes bindings
for node and field scripts; ASan/UBSan.

**Built 2026-10-22** (decisions P5C-14 to P5C-16). The battery is its own
program (`core/tests/test_sandbox_escape.c`, ctest `sandbox_escape`, CI job
`sandbox-escape` under ASan and UBSan) rather than part of `test_node.c`, so
CI and the registry's CI can run it alone; `test_sandbox` stays. It found two
real escapes from the instruction watchdog, both closed in `core/src/sandbox.c`
(P5C-15): `__gc` finalizers, which Lua runs with hooks off, and `xpcall`'s
message handler after the watchdog's own error. 43 cases x 2 heaps x box and
controller; `simulator/tests/test_sandbox_escape.py` (4 tests: the cases
through ctypes, odd host answers and a host that raises, bytecode, a mode in
the simulator whose box trips the sandbox while the game plays on).

## Plan phase 6: Signed packages in the controller

*Software, can be done now. Depends on 4. Size M.*

The controller fetches an index (a URL, or a file for an offline
field), verifies each package (signature, key not revoked, size,
licence) and installs scenarios and field-script packages through the
existing upload checks; the console shows who signed a package and
"not reviewed by the project" for unverified ones. Store schema bump,
controller tests, console browser tests.

**Built 2026-10-22** (decisions P5C-17 to P5C-21): the GM also uploads a
signed package directly (as a firmware release); every kind installs through
`ModeRegistry.install` (scenarios, field scripts, and modes, which boxes get
from plan phase 13).

| File | What |
|------|------|
| `controller/atalaia_controller/signed_modes.py` | Trusted keys and revocations, the index (https or a file, `revoked.json` beside it, fail closed), upload and install from the index, each package's trust today |
| `controller/atalaia_controller/api.py` | `GET|POST /api/v1/mode-packages`, `POST /api/v1/mode-packages/install`; `signed` in `GET /api/v1/modes`; the stream's `modes` after any install |
| `controller/atalaia_controller/modes.py`, `store.py` (schema 10), `config.py` (`[modes] keys`, `revoked`, `index`), `main.py`, `engine.py` | The signed release and archive kept with the package |
| `controller/console/src/components/mode-packages.js`, `app.js`, `sw.js`, `style.css`, `i18n/*.json` | The *Signed mode packages* panel in the *Presets* tab, en + pt |
| `controller/tests/test_signed_modes.py`, `controller/console/tests/test_browser.py` | 9 controller tests (upload, refusals, revoked and removed keys, index on disk and over https, bad indexes, the stream, config, the schema 9 upgrade), 1 browser test |

## Plan phase 13: Missing modes from the GM console

*Software, can be done now (the box's side host-tested; on real boxes in
HW3). Depends on 4, 5, 6. Size L (two parts: 13a the controller, the
console and the protocol; 13b the box). Planned 2026-10-22 from the
maintainer's decision on P5R-8; design choices P5B-8 to P5B-17, all
open.*

The maintainer (P5R-8, 2026-10-22): *"we should have a way to sync only
new modes as needed from the GM console"*. A box gets from its field
controller only the modes a game needs that it lacks, as signed
packages, instead of every new mode waiting for a firmware release. K10
is amended, not dropped: a box still runs only code it can check with
keys built into its firmware (ADR.md, "Note 2026-10-22: P5R-8").

**Where packages come from** (P5B-8). Only the field controller's mode
store: a signed package the GM uploads in the console (made and signed
with `tools/mode_package.py`, plan phase 4, from the editor's files) or
one imported from a registry index (plan phase 6; later the site
server's library). The editor never sends anything to a box, and a box
never reaches the internet: it downloads from its controller.

**The signature** (P5B-9, P5B-10). The mode package's signed manifest
of P5R-7, with two more lines so that a box can decide without reading
YAML: `atalaia-mode-package-v1`, `id=`, `version=`, `kind=` (`mode`,
`modifier` or `role`; a scenario runs on the controller only and is
never sent), `min_tier=` (`reduced` or `full`), `size=`, `sha256=` (of
the archive). Ed25519, base64, key ids as release keys'. A box checks
it with **mode keys built into its firmware** (`CONFIG_ATALAIA_MODE_KEYS`,
up to 4, next to `CONFIG_ATALAIA_OTA_RELEASE_KEYS`; the release keys may
sign modes too); the controller checks with the same list
(`[modes] box_keys`) only to offer what a box will take. So a community
mode reaches boxes once the project has signed it (the registry's
verified badge, plan phase 8, becomes that signature); whether a field
may add its own key for its club's modes was for the maintainer (P5B-9).
**The maintainer, 2026-10-22: accepted as recommended, mode keys built into
the box's firmware only.** (The controller's own `[modes] keys` of plan
phase 6 decide what it installs; `[modes] box_keys` lists the boxes' keys.)

**How a box receives it** (P5B-11). The trigger stays on the radio and
small; the scripts never go over LoRa. In the invite dialog, a box that
answered *no mode* (field-frame result 3) can be invited again with a
join that carries a new optional key, **16 `fetch_modes`** (true). A box
with that key takes the join as *fetching* instead of refusing it: for
each part of its `mode_id` it lacks, it joins the field Wi-Fi and, over
HTTPS pinned to the field CA (join keys 13 and 14, as a firmware update),
`GET <url>/api/v1/mode-packages/<id>/release` (the manifest and
signature) and `.../<id>/package` (the archive), then checks and installs
it, and only then sends its HELLO as a joined box. A card or a QR code
with key 16 does the same. Firmware without it skips key 16 (keys 16-31
are skipped by every reader) and answers *no mode* as today.

**Storage and limits** (P5B-12). On the box's `storage` LittleFS
partition (2 MiB; presets already live there): `/littlefs/modes/<id>/`
with `node.lua`, the screen templates (`assets/screens/*.yaml`, read by
the core's parser as built-in ones are) and the signed release; its
preset slot is marked *fetched* with the version, key id and SHA-256. A
box takes an archive of at most 256 KiB (the controller takes 1 MB; the
box hashes the whole archive as it streams and keeps only `node.lua` and
`assets/screens/`), at most 8 fetched packages and 512 KiB in all,
and a composed game within its 16 KB preset buffer, as today. A Reduced
box (no PSRAM, 64 KB of Lua heap) uses the same storage, refuses
`min_tier=full` (`tier`) and checks a script with its own heap.

**When** (P5B-13). Only between games: a box fetches while it is
joining (never while a game is running or paused; a game starting stops
a fetch, `cancelled`), and the controller's start guard waits while a
fetch is on its way (`[modes] fetch_timeout_s`, 300 s; the GM can stop
waiting), as it does for firmware updates.

**How the box checks and loads it** (P5B-14). In order, refusing with a
reason at the first failure: the release text has exactly the
manifest's lines and a signature; the id is the part it asked for; the
signature with one of its mode keys; the kind (not `scenario`), the tier;
the id is not one of its built-in ones (the firmware owns those, K10;
`builtin`); the archive's size and SHA-256 as signed while it is
streamed, before anything is kept; then the script loads in a fresh
sandbox with the box's tier limits (the same `node_runner` load as a
game, no game started) and the composed game still fits; only then is it
written to storage and the slot marked. The sandbox (plan phase 5's
battery) is what limits a signed script; the signature says who vouches
for it.

**Rollback and removal** (P5B-15). A newer version of a fetched id
replaces the older one only after it has passed its checks; the older
one stays until then, so a failed fetch leaves the box as it was. When
space is needed, the box drops the fetched package least recently used
by a game, never one the joined game needs and never a built-in one. The
console's *Boxes* tab can tell a box to forget its fetched modes (in its
next join, key 17 `forget_modes`); a factory reset forgets them too. A
key that is revoked is taken out of the controller's list at once (it
offers nothing signed by it) and out of boxes by a firmware release.

**What the console shows** (P5B-16). In the invite dialog, next to the
boxes that answered *no mode*: which parts the game needs that the
controller holds as signed packages a box will take, *Send missing
modes* (re-invites those boxes with key 16), and per box its progress:
fetching, installed, refused with the reason (`no_wifi`, `unreachable`,
`bad_signature`, `no_key`, `tier`, `builtin`, `too_big`, `no_space`,
`bad_hash`, `load`, `cancelled`), failed. A part the controller does not
hold, or holds unsigned, is named with what to do (upload a signed
package). The box reports over HTTPS (`POST /api/v1/mode-packages/report`,
an HMAC with the game key, as the firmware report) and, when HTTPS cannot
carry it, with a new standard event `node.modes_failed` (critical, the
reason and the part) over LoRa. The *Boxes* tab lists each box's fetched
modes from its last report.

**Work.** 13a: the manifest's lines in `tools/mode_package.py` and the
shared vectors (plan phase 4), join key 16 and 17 in the three join
codecs and `protocol/vectors/join.json`, `protocol/mode-packages.md`,
the controller's endpoints and start guard, the console's step (en, pt),
contract cases in `protocol/vectors/controller_api.json` for the Android
controller role. 13b: `firmware/esp32/main/mode_fetch.c` (platform-free,
host-tested with fakes, as `fw_update.c`) and its ESP-IDF side, the
preset store's fetched slots, the box's screens from storage, the
`node.modes_failed` event in `protocol/schema/events.yaml`. Android
props get the same packages through their own Wi-Fi link in a later
slice of PE24.

**Tests.** The C codecs and checks against the shared vectors (a valid
release, every refusal above, a tampered archive, a revoked or unknown
key, the reduced tier); `box_host` runs a fetch from a fake controller;
the controller's tests (offer, report, start guard, the console's
browser tests); the simulator's join codec with keys 16 and 17. On real
boxes: HW3.

**13a built 2026-10-22** (decisions P5D-1 to P5D-12; the contract for 13b is
`protocol/mode-packages.md`, "Fetching missing modes"). Differences from the
plan above: a box that cannot fetch (no keys 13/14, no mode key, old firmware)
answers *no mode* as today, and one whose fetch fails leaves the join (P5D-2,
P5D-3); the reason list gained `not_offered`, `download`, `bad_archive` and
`storage` (P5D-5); `node.modes_failed` is proposed as event id 53 with data
`mode` (key 38), added to `events.yaml` by 13b (P5D-6); no contract case in
`controller_api.json` and no Dart codec change, since the Android controller
role serves no mode packages yet (P5D-1).

| File | What |
|------|------|
| `simulator/atalaia_sim/join.py`, `protocol/vectors/join.json` (`mode_fetch`), `protocol/join.md` | Join keys 16 `fetch_modes` and 17 `forget_modes` |
| `simulator/atalaia_sim/lobby.py` | The model of a free box: accepts a join with key 16 fetching, forgets with key 17, leaves the join when a fetch fails |
| `controller/atalaia_controller/mode_package.py`, `tools/mode_package_vectors.py`, `protocol/vectors/mode_package.json` (`box_limits`, `box_checks`, `reports`) | The box's checks in order and its report, the reference for 13b's C |
| `controller/atalaia_controller/mode_fetch.py`, `engine.py`, `reinvite.py`, `api.py`, `config.py` (`[modes] box_keys`, `fetch_timeout_s`), `main.py` | The offer, the endpoints boxes fetch from, the report, `node.modes_failed`, the start guard, keys 16 and 17 in invites and card joins |
| `controller/console/src/components/box-invites.js`, `fetched-modes.js`, `app.js`, `sw.js`, `i18n/*.json` | *Send missing modes* in the invite dialog, the fetch's progress, *Stop waiting*; *Modes fetched by boxes* in the Boxes tab |
| `controller/tests/test_mode_fetch.py`, `test_mode_package.py`, `simulator/tests/test_join.py`, `test_reinvite_sim.py`, `controller/console/tests/test_browser.py` | 13 + 2 + 3 + 2 tests and 1 browser test |

**13b built 2026-10-22** (the box; decisions P5E-1 to P5E-14, against 13a's contract in
`protocol/mode-packages.md`, "Fetching missing modes"). Host-tested; on real boxes in HW3.

| File | What |
|------|------|
| `firmware/esp32/main/mode_package.c` | The release text, its Ed25519 check, a streaming reader of the canonical archive (every refusal of the vectors, fed in pieces of any size) |
| `firmware/esp32/main/mode_fetch.c` | The fetch in the contract's order: release, signature (mode keys, then release keys), kind, tier, built-in, size, room, download hashed into a file, archive, load and screens in the sandbox, the composed game, the commit; the reports (HMAC) |
| `firmware/esp32/main/mode_store.c` | `/littlefs/modes/<id>/` with its slot, commits by renames finished or forgotten at boot, 8 packages and 512 KiB, least recently used dropped, boot re-verification, forgetting, the screens from storage |
| `firmware/esp32/main/mode_fetch_esp.c`, `Kconfig.projbuild` | The task over the firmware update's Wi-Fi and pinned HTTPS, `CONFIG_ATALAIA_MODE_KEYS` |
| `firmware/esp32/main/box_game.c`, `box_lobby.c` | `BOX_FETCHING`: a key-16 join taken as fetching, HELLO once the packages are in, key 17, `node.modes_failed` over LoRa when HTTPS cannot carry the failure, free again (not an ended game), cancelled by the game's end or another card |
| `core/src/join.c` | Join keys 16 and 17 (true only), against `join.json`'s `mode_fetch` |
| `protocol/schema/events.yaml` | `node.modes_failed` (id 53) and the data field `mode` (key 38) |
| `firmware/esp32/test/test_mode_package.c`, `test_mode_fetch.c`, `test_box_game.c`, `box_host` | The vectors (`box_checks`, `reports`, the archives), a fake controller, the box's join and fetch; `box_host --mode-keys --mode-source` |

## Plan phase 7: Scenario blocks in the console

*Software, can be done now. Depends on 1. Size M.*

A block view of the scenario builder (objectives, their types,
dependencies, reveals and effects, the boxes they name) that writes the
same YAML manifest, checked by the same `POST /api/v1/scenarios/check`;
Blockly vendored for the console as its other libraries
(`controller/console/src/lib/`), the console's CSP adjusted for its
styles only; en + pt; console browser tests.

**Built 2026-10-22** (decisions P5F-1 to P5F-12; P5F-2, P5F-4 and P5F-5 for
the maintainer). The block view is a second view of the *Scenarios* tab's one
editor: the YAML stays its text, the blocks write it on every change, and the
controller reads it for the blocks (the check's new `manifest`, P5F-3), so no
rule or reader is repeated in the browser. The CSP is adjusted for styles by
two SHA-256 hashes (Blockly's two stylesheets), not `'unsafe-inline'`
(P5F-2). The round trip of all 8 scenario examples gives the hand-written
packages byte for byte (P5F-9).

| File | What |
|------|------|
| `controller/console/src/components/scenario-blocks.js` | 30 blocks (the scenario, texts, teams, parameters, boxes and players, objectives and their rules) and the toolbox; `manifestToState` (a manifest to Blockly's state, naming what the blocks cannot hold), `workspaceToManifest` (the blocks to the manifest, the block of each value, the blocks' own problems), `toYaml`; Blockly loaded on demand |
| `controller/console/src/components/scenario-block-view.js` | The workspace: Blockly injected with the console's texts and theme, the YAML handed to the builder on every change, problems outlined on their blocks, *Show* |
| `controller/console/src/components/scenario-builder.js` | *YAML* / *Blocks* views of one editor, the view remembered; the blocks' problems in the list; *Install* off while the blocks have an error |
| `controller/console/src/lib/blockly/`, `lib/README.md`, `REUSE.toml` | Blockly 13.3.0 (the core, en and pt texts, 7 media files), the mode editor's bytes, Apache-2.0 |
| `controller/atalaia_controller/api.py` (`BLOCKLY_STYLES`), `scenario_service.py` | The CSP's two style hashes; `manifest` in the check's answer |
| `controller/console/src/i18n/*.json`, `style.css`, `sw.js` | `scenario_blocks` texts (en, pt-PT); the view's styles; Blockly precached |
| `controller/console/tests/test_scenario_blocks.py` | 7 browser tests and 1 plain one: the round trip of every example, edit and install in pt then en, the keyboard, the read token on a phone, refusals, the stylesheets against the CSP in light and dark, offline |
| `controller/tests/test_console.py`, `test_scenario_api.py` | The vendored files and the blocks' texts; the check's `manifest` |

## Plan phase 8: Registry repository template

*Software, can be done now; publishing needs the maintainer. Depends on
4, 5. Size S.*

`registry/template/`: `index.json` (empty, `schema_version: 1`),
`keys/README.md`, `keys/revoked.json`, the registry CI workflow
(`registry-lint`, `registry-test`, `sandbox-escape`) using this
repository's tools, and a test that runs that workflow's commands on a
sample submission. The maintainer creates `atalaia-modes` from it.

**Built 2026-10-22** (decisions P5G-1 to P5G-11; how it works:
`docs/community/registry.md`). Beyond the plan: the registry keeps its packages
beside its index (not as GitHub Release assets) with each mode's newest source,
which must pack to exactly the signed archive; the verified badge is a second
signature by the project's registry key over the same archive (P5G-2), the key
Field Boxes have built in; a fourth job publishes to GitHub Pages.

| File | What |
|------|------|
| `registry/template/` | `index.json` (empty, `schema_version: 1`), `keys/README.md`, `keys/revoked.json`, `modes/README.md`, `README.md`, `CONTRIBUTING.md`, `REUSE.toml`, `.github/workflows/registry.yml` (`registry-lint`, `registry-test`, `sandbox-escape`, `publish`, with this repository's tools at `ATALAIA_REF`), `.github/CODEOWNERS`, the pull request template and the *Flag a mode* and *Revoke a key* issue templates |
| `tools/registry_check.py` | `lint` (with `--base`), `test`, `key`, `add`, `badge` (`--remove`), `site` |
| `registry/examples/org.example.hill/` | A sample community submission (MIT) with two tests (since 2026-10-23 its own screens and a third test) |
| `registry/tests/test_registry_template.py` | 18 tests: the workflow's shape; the sample listed and verified with throwaway keys, every `check-` step of the workflow run as written, the published package verified as a controller does; the refusals |
| `tools/check.sh`, `.github/workflows/ci.yml` (job `registry-template`) | The test in this repository's checks |

## Plan phase 9: Community processes

*Software, can be done now. Size S.*

CONTRIBUTING.md "Submitting a community mode" (the editor, the
package, signing, the PR, the checklist, the badge), the review
checklist and badge criteria as amended, and an RFC for the package
format, the manifest and the index.

**Built 2026-10-22** (decisions P5G-12 to P5G-14; P5G-2, P5G-3, P5G-8, P5G-9,
P5G-12, P5G-13 and P5G-14 for the maintainer).

| File | What |
|------|------|
| `CONTRIBUTING.md` | "Submitting a community mode": the editor, tests, the key, `registry_check.py key` and `add`, the pull request, review and the badge |
| `docs/community/README.md`, `registry.md`, `review.md`, `keys.md`, `moderation.md` | How the registry works and what its CI checks; the review checklist as amended and the badge's criteria and commands; making, keeping, rotating and revoking keys; reports, takedowns, ids and owners, appeals |
| `docs/rfcs/0000-mode-packages-and-registry.md` | The RFC for the package format, the manifest and the index (draft, version 1 as built) |
| `SECURITY.md`, `LICENSING.md`, `docs/README.md`, `docs/rfcs/README.md`, `registry/README.md`, `protocol/mode-packages.md` | Pointers to the above |

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

**Built 2026-10-22** (decisions P5K-1 to P5K-12; P5K-3, P5K-4, P5K-5,
P5K-7, P5K-11 and P5K-12 for the maintainer). One code, `zh-tw`, in every
part and in join key 15 (no protocol change; older boxes show English).
Drafted by an AI model, **not yet reviewed by a native-speaking player**
(`docs/translations/status.yaml`). The box's fonts carry exactly the 153
letters of its Chinese texts (17 at 48 px), from Noto Sans TC, and are now
compressed: the Field Box image is 0x1bf220, 1 KB more than before, 13 % of
its slot free (uncompressed the letters cost 117 KB, 7 % free). The app
uses Android's CJK font; the console, editor and page the system's.

| File | What |
|------|------|
| `site/i18n/zh-tw.yaml`, `site/zh-tw/`, `site/img/diagrams/*-zh-tw.svg`, `site/img/screens/app-*-zh-tw.png`, `tools/build_site.py`, `site/src/`, `site/style.css`, `site/README.md` | The project page at `/zh-tw/` (P5K-9), CJK wrapping and fonts (P5K-6, P5K-8) |
| `controller/console/src/i18n/zh-tw.json`, `ui.js`, `sw.js`, `components/radio-settings.js`, `components/scenario-blocks.js`, `*.css`, `controller/atalaia_controller/engine.py`, `api.py`, `protocol/vectors/controller_api.json` | The GM console and the box-language setting (P5K-2, P5K-10) |
| `simulator/atalaia_sim/editor/i18n/zh-tw.json`, `vendor/blockly/msg/zh-hant.js`, `editor.js`, `index.html`, `editor.css` | The mode editor with Blockly's own Traditional Chinese |
| `app/lib/l10n/strings_zh_tw.dart`, `strings.dart`, `ui/theme.dart`, `ui/settings_screen.dart`, `controller/controller_engine.dart`, `app/test/fonts/`, `app/test/l10n/cjk_font_test.dart` | The app, its font fallback and test fonts (P5K-7) |
| `firmware/esp32/main/box_text.{c,h}`, `main/fonts/`, `lvgl_conf/lv_conf.h`, `tools/gen_box_fonts.py`, `firmware/esp32/test/font_check.h`, `test_box_text.c`, `test_screens.c`, `test_oled_screens.c`, 43 `_zh-tw` reference images | The box's Chinese column, the subset fonts and their checks (P5K-3 to P5K-5) |
| `tools/i18n_check.py`, `tools/check.sh`, `docs/translations/` | The checks; the zh-tw status, glossary column and process |

## Plan phase 12: Build guides for other node types

*Software, can be done now. Size S.*

Text guides for the Satellite, the I/O pod and the target addon in the
manner of `hardware/field-box/BUILD.md`, with `<!-- PHOTO: ... -->`
placeholders, linked and rendered on the project page.

**Built 2026-10-22** (decisions P5J-1 to P5J-14; P5J-2, P5J-4, P5J-7, P5J-8,
P5J-9 and P5J-11 for the maintainer). The Satellite is the Field Box's board
and firmware with two or three buttons, the LED ring and the board's OLED (no
variant, P5J-2); the I/O pod is the Field Box's parts without the TFT, plus the
enclosure switch on GPIO 47 (P5J-6); the target addon's guide lists what is
decided and what is not, with no wiring: it is not buildable yet, and a Field
Box has no free GPIO for its interrupt line (P5J-9). No guide has been followed
on real hardware; photos are HW2.

**Follow-up 2026-10-23** (the maintainer's answer to P5J-9, "fix in 3.3 V";
decisions P5J-15 to P5J-21, open): the M12 port carries 3.3 V only (the
board's 3V3 through a resettable fuse, at most 25 mA for the addon; SDA, GND,
SCL on A-coded pins 2, 3, 4, 3.3 V on 1, pin 5 not connected), *Target
Windows* lights the box's own ring, and there is no interrupt line: the box
polls the addon every 20 ms (about 3 % of the 100 kHz bus; a hit reaches the
script within about 21 ms). No pin changes. A polling driver with a draft
report format (`firmware/esp32/main/target_addon.c`, host tests in
`test_target_addon.c`) is in the firmware, not called yet; the design
specification, ADR-P5-6's table, the guide and the build page in four
languages say 3.3 V. The addon stays not buildable: its processor, firmware,
I2C address, "identify" answer, sensor and plate are open (HW2).

| File | What |
|------|------|
| `hardware/satellite/BUILD.md`, `hardware/io-pod/BUILD.md`, `hardware/target-addon/BUILD.md` | The guides, in the Field Box manual's manner, with `<!-- PHOTO: ... -->` placeholders (P5J-10) |
| `hardware/README.md`, `hardware/{satellite,io-pod,target-addon}/README.md`, `README.md` | Pointers to the guides |
| `site/src/build.html`, `site/i18n/{pt,en,de}.yaml`, `site/style.css`, `site/src/partials/header.html`, `tools/build_site.py` | The build page: `/montagem/`, `/en/build-guides/`, `/de/bauen/`, in the header (P5J-11) |
| `tools/check_wiring.py` | The guides' and the page's pin tables checked against the Kconfig defaults (P5J-13) |
| `docs/translations/glossary.md`, `site/README.md`, `tools/README.md` | The new words; how the page and its pin tables work |

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
| AC-4 | The registry index format is defined and documented | 4 | **Met in software (2026-10-22)**: `registry/schema/index.schema.json`, `protocol/mode-packages.md` |
| AC-5 | Mode packages are Ed25519-signed and verifiable | 4 | **Met in software (2026-10-22)**: `tools/mode_package.py`, the shared vectors |
| AC-6 | Registry CI runs mode tests and checks licences | 8 | **Met in this repository's template (2026-10-22)**: `registry/template/.github/workflows/registry.yml` run on a sample submission by CI's `registry-template` job; in `atalaia-modes` once the maintainer creates it |
| AC-7 | At least one language beyond en/pt on the site | 10 | **Met in software (2026-10-22)**: `/de/` built and checked by `build_site.py --check`; review pending (P5H-5) |
| AC-8 | Built-in modes carry English and Portuguese texts | -- | **Met differently**: in `mode.yaml`'s `i18n:` (P4R22), every built-in mode |
| AC-9 | The carrier PCB schematic passes KiCad ERC | HW1 | Pending (needs hardware) |
| AC-10 | Build guides exist for the Field Box and the Satellite | 12, HW2 | **Met in text (2026-10-22)**: `hardware/field-box/BUILD.md`, `hardware/satellite/BUILD.md` (and the I/O pod's and the target addon's), on the project page in three languages; photos with HW2 |
| AC-11 | CONTRIBUTING.md documents mode submission | 9 | **Met (2026-10-22)**: "Submitting a community mode", `docs/community/` |
| AC-12 | CI includes a sandbox-escape test job | 5 | **Met (2026-10-22)**: CI job `sandbox-escape` |
| AC-13 | (new, P5R-8) A box gets a signed mode it lacks from its field controller between games, checks it and plays it; it refuses an unsigned or tampered one | 13, HW3 | Pending (planned 2026-10-22) |

---

## Assumptions about earlier phases (re-checked 2026-10-22)

| # | Assumption | Status 2026-10-22 |
|---|-----------|-------------------|
| A1 | The node script API is final | Built and stable; grown since with `game.teams()` and `geo.*` (plan phase 3 adds geo blocks) |
| A2 | `state.field{}` and `field.*` follow spec section 9 | Built (phase 2); the editor has them |
| A3 | The mode package format is stable | Built, with kinds, roles, `needed`, commands and `i18n:` |
| A4 | Ed25519 for firmware images | Built (`protocol/firmware-update.md`); mode packages reuse it (P5R-7) |
| A5 | The Heltec V4.3 pin map | Re-done with GNSS (2026-10-21); still to be proved in a built box |
| A6 | The simulator's web view runs one mode at a time | Holds; it ran `field.lua` already (through `Simulation`); plan phase 2 shows the controller and reloads the mode from the editor |
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
| P5R-8 | May boxes ever load signed community node scripts at run time? | **Decided by the maintainer (2026-10-22):** yes, only what a game needs, as signed packages from the GM console: plan phase 13 (P5B-8 to P5B-17; P5B-9, which keys a box trusts, answered by the maintainer 2026-10-22: firmware-built mode keys only) |
| P5R-9 | When to create `atalaia-modes`? | After plan phase 8, from its template |
| P5R-10 | Third language: German first, then Traditional Chinese? | Yes, German first (no new glyphs on the box) |
