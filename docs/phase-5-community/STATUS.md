<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 5 -- Community: Status

**Current phase:** Implementation (plan phases 1-10, 12 and 13 built in software 2026-10-22: the visual mode editor complete, its link to the simulator, signed mode packages, the sandbox-escape battery, signed packages in the controller, scenario blocks in the GM console, missing modes sent to boxes (controller and box), the registry repository's template and the community processes, German, the build guides for the other node types)
**Phase status:** In progress
**Risk level:** Medium
**Last updated:** 2026-10-22 (plan phase 12 built; the editor makes the package itself, P5I-1 to P5I-6; plan phases 8 and 9 built; plan phase 7 built; plan phase 13b built; plan phase 13a built; plan phases 3-6 built, P5B-9 answered; plan phase 2 built, plan phase 13 planned from P5R-8; refreshed after phases 2-4 software; first written 2026-10-18)
**Next step:** the review of the German (P5H-5); P5I-1 and P5I-3 (the editor's package: made in the page, signed offline) for the maintainer; creating the registry repository waits for the maintainer; plan phase 13's test on real boxes is HW3; plan phase 11 (Traditional Chinese) is the last software plan phase; the build guides wait for their first builds and photos (HW2) and the maintainer's P5J decisions

Phase 5 is the community layer: visual mode editor (Blockly), mode
registry with signing and a verified badge, carrier PCB, translations,
and build guides. It is ongoing after the first release (design-spec.md
section 16).

## Completed

- [x] Research phase: `RESEARCH.md`
- [x] Architecture decisions: `ADR.md` (8 ADRs: P5-1 through P5-8)
- [x] Implementation plan: `PLAN.md`
- [x] **Refresh after phases 2-4 software (2026-10-22):** every ADR re-checked
  against the built code, with dated amendments (P5-1, P5-2, P5-3, P5-4,
  P5-7, P5-8) and notes (P5-5, P5-6); the plan re-cut into 12 software plan
  phases and 3 hardware ones in build order; decisions P5R-1 to P5R-14 in
  `docs/review/decisions-to-review.md` (all open; P5R-8 and P5R-10 are for
  the maintainer)
- [x] **Plan phase 1, the visual mode editor (2026-10-22), in software:**
  Blockly 13.3.0 (vendored, checksummed) served by the simulator at
  `/editor/`; 37 blocks for the node and field script API; a Lua generator
  with the project's style and a `mode.yaml` generator; English and
  Portuguese; Domination and Hold-All Domination as example projects whose
  generated files pass every YAML test of the hand-written modes and give
  the same manifests; 15 browser tests (`python3 tools/docker_editor.py`, CI
  job `editor`) and 6 plain tests in `tools/check.sh`. Decisions P5A-1 to
  P5A-7. AC-1, AC-2, AC-3 met.
- [x] **Plan phase 2, the editor and the simulator (2026-10-22), in software:**
  the editor's *Test in the simulator* (with a number of boxes) sends the
  generated files to the simulator's new `POST /api/reload`, which loads them
  in the core first (on an error the running game goes on) and starts the
  game; the simulator's page, in its own tab, shows it, now with a *Field
  controller* panel for `field.lua` (which the web view already ran, but did
  not show); errors on loading and while the game runs come back to the
  editor's problems list and onto the blocks they come from (a line-to-block
  map from Blockly's statement prefix). Same server rules (local Host, JSON
  only, CSP `'self'`), 1 MB at most. 7 new simulator tests, 3 new browser
  tests (18 in all). Decisions P5B-1 to P5B-7.
- [x] **Plan phase 3, the editor's remaining blocks (2026-10-22), in software:**
  *Places* (geo distances and zones, a position's values), *GM commands*
  (`commands:` and a `cmd.mode` handler per name), the controller sending a
  mode command, several roles with their own inputs and `needed`, the kinds
  modifier and role package, the mode's screen files offered in the toolbox;
  a third example, Master and Satellites, passing all 8 of its mode's tests;
  24 browser tests. Decisions P5C-1 to P5C-7.
- [x] **Plan phase 4, mode packages and signing (2026-10-22), in software:** a
  canonical ustar archive of a mode folder, the manifest
  `atalaia-mode-package-v1` (id, version, kind, minimum tier, size, SHA-256)
  signed with Ed25519 as firmware releases, checks that fail closed,
  `tools/mode_package.py`, the registry index's JSON Schema, shared vectors;
  17 tests. AC-4 and AC-5 met. Decisions P5C-8 to P5C-13.
- [x] **Plan phase 5, the sandbox-escape battery (2026-10-22):** 43 escape
  attempts as box and controller scripts under ASan and UBSan (CI job
  `sandbox-escape`) and through the simulator; it found and closed two ways to
  run with the watchdog off (`__gc` finalizers, `xpcall`'s handler after the
  watchdog's error). AC-12 met. Decisions P5C-14 to P5C-16.
- [x] **Plan phase 6, signed packages in the controller (2026-10-22), in
  software:** upload a signed package or install one from the registry index
  (https, or a file for an offline field), verified with the controller's own
  mode keys and revocations, failing closed; kept with its archive and release
  (store schema 10); the console's *Presets* tab shows who signed each package,
  *not reviewed by the project*, revoked or untrusted keys. Decisions P5C-17 to
  P5C-21.
- [x] **The maintainer's P5R-8 planned (2026-10-22):** plan phase 13, *Missing
  modes from the GM console*: in the invite dialog, *Send missing modes*
  re-invites boxes that answered "no mode" with join key 16; each fetches the
  signed packages it lacks over Wi-Fi HTTPS pinned to the field CA (never
  LoRa), checks them with mode keys built into its firmware and the sandbox,
  keeps them on LittleFS (limits, the Reduced tier, rollback, removal), only
  between games. K10 amended for that path (ADR.md, "Note 2026-10-22: P5R-8").
  Design choices P5B-8 to P5B-17 (open; P5B-9, which keys a box trusts, is for
  the maintainer). Not built.
- [x] **Plan phase 13a, missing modes from the GM console: the controller,
  console and protocol (2026-10-22), in software:** join keys 16
  (`fetch_modes`) and 17 (`forget_modes`) in the Python codec and the shared
  vectors; the endpoints a box fetches a signed package from (no token, only a
  part of the live game's mode, only while it is ready) and reports to (an HMAC
  with the game key); what the controller offers boxes (`[modes] box_keys`, the
  keys built into their firmware) and why not; the start guard waiting while
  boxes fetch (`[modes] fetch_timeout_s`, *Stop waiting*); in the console,
  *Send missing modes* under a box that answered *no mode*, its progress, and
  the Boxes tab's *Modes fetched by boxes* with *Forget at its next invite*;
  the wire contract for the box (check order, refusal codes, the report,
  `node.modes_failed`, storage) in `protocol/mode-packages.md` with shared
  vectors for 13b's C (`box_checks`, `reports`). 13 controller tests, 1 browser
  test. Decisions P5D-1 to P5D-12 (open; P5D-3, P5D-6, P5D-11 for the
  maintainer).
- [x] **Plan phase 7, scenario blocks in the GM console (2026-10-22), in
  software:** the *Scenarios* tab's editor has a *Blocks* view beside its
  YAML: 30 blocks (the scenario, its texts, teams, parameters, boxes and
  players, objectives with who, when, how and what they give), in European
  Portuguese and English, by mouse, touch or keyboard, at phone width. The
  YAML stays the editor's text: the blocks write it on each change and the
  controller reads it for them (`manifest` in the check's answer), checks,
  compiles and installs it as before; its problems are outlined on their
  blocks, with *Show*. The blocks refuse a manifest they cannot hold as it is
  rather than rewrite it. Blockly 13.3.0 vendored in the console (the mode
  editor's bytes), loaded on demand and precached for offline use; the CSP
  allows only the SHA-256 of Blockly's two stylesheets, no `'unsafe-inline'`.
  The round trip of every scenario example (2 hand-written manifests, the
  console's example, 5 valid vectors) compiles to the hand-written packages
  byte for byte. 7 browser tests, 3 plain ones. Decisions P5F-1 to P5F-12
  (open; P5F-2, P5F-4, P5F-5 for the maintainer).

- [x] **Plan phase 13b, the box's side of missing modes (2026-10-22), in
  software (host-tested; on real boxes in HW3):** a join with key 16 whose
  mode the box lacks (with keys 13 and 14 and a mode key built in,
  `CONFIG_ATALAIA_MODE_KEYS`) makes the Field Box fetch each missing part over
  the field Wi-Fi and HTTPS pinned to the field CA, check it in the contract's
  order (release, Ed25519 with its own keys, kind, tier, built-in, 256 KiB,
  room, the archive hashed before it is read and in its canonical form, the
  script and screens in the sandbox, the composed game), keep it on LittleFS
  (8 packages, 512 KiB, least recently used dropped, commits by renames,
  re-verified at boot), report each part (HMAC) and only then say HELLO; a
  failure without HTTPS goes over LoRa as `node.modes_failed` (id 53) and the
  box is free again; key 17 forgets. The core's join codec reads keys 16 and
  17. Decisions P5E-1 to P5E-14. Binary +16 KB (0.9 %), static RAM +1 KB.
- [x] **Plan phase 8, the registry repository's template (2026-10-22), in
  software:** `registry/template/`, the `atalaia-modes` repository's files
  (an empty index, keys and revocations, sources in `modes/`, REUSE, CODEOWNERS,
  pull request and issue templates) with its CI (`registry-lint`: the JSON
  Schemas, `tools/registry_check.py lint` and REUSE; `registry-test`: each
  mode's tests in the simulator; `sandbox-escape`: the core's battery; then
  publishing to GitHub Pages), on this repository's tools at a pinned ref.
  Packages live beside the index; each mode's newest source must pack to
  exactly its signed archive; the verified badge is a second signature, by the
  project's registry key, over the same archive. `registry/tests/` runs every
  check step of that workflow on a sample submission signed with throwaway keys
  (CI job `registry-template`, `tools/check.sh`): 18 tests. AC-6 met in this
  repository's template. Decisions P5G-1 to P5G-11.
- [x] **Plan phase 9, the community processes (2026-10-22):**
  `CONTRIBUTING.md` "Submitting a community mode"; `docs/community/` (how the
  registry works, the review checklist as amended and the badge's criteria,
  mode keys and their revocation, moderation); the draft RFC
  `docs/rfcs/0000-mode-packages-and-registry.md` for version 1 of the package
  format, the manifest and the index. AC-11 met. Decisions P5G-12 to P5G-14
  (open; P5G-2, P5G-3, P5G-8, P5G-9, P5G-12, P5G-13 and P5G-14 for the
  maintainer: governance, who holds the keys, moderation, licensing).
- [x] **Leftover of plan phases 3-6: the editor makes the package (2026-10-22),
  in software:** *Make the package* in the mode editor downloads the canonical,
  unsigned archive of the mode it edits (`<id>-<version>.tar`: `mode.yaml`,
  `node.lua`, `field.lua` when there is one, the Mode tab's screens), made in
  the page by `editor/package.js` and byte for byte what `tools/mode_package.py
  pack` makes of the same files (proved in Chromium against the Python packer
  for the shared vectors, all 14 built-in modes, the three examples and 18 edge
  cases); it shows the manifest a mode key will sign (size, SHA-256) and the
  exact `sign` and `verify` commands. Signing stays offline on the command line;
  no key reaches the page or the simulator; the CSP is unchanged. Refused, with
  the reason, while the generator lists problems or for a bad version, licence
  or size. 5 new browser tests (30 in all). Decisions P5I-1 to P5I-6 (open;
  P5I-1, where the archive is made, and P5I-3, how to sign, for the maintainer).
- [x] **Plan phase 10, German (2026-10-22), in software:** German in the
  project page (`/de/`), the GM console, the mode editor (with Blockly's own
  German), the app and the Field Box's screens (join key 15 `de`; the fonts
  gain Ä Ö Ü ä ö ü ß, +9.2 KB; older firmware shows English);
  `tools/i18n_check.py` checks every part against English in `tools/check.sh`
  (a missing German key shows English and is only a warning; the project page
  must stay complete); `docs/translations/` (process, glossary, status).
  Drafted by an AI model, **not yet reviewed by a native-speaking player**
  (`docs/translations/status.yaml`). AC-7 met in software. Decisions P5H-1 to
  P5H-11 (open; P5H-5, P5H-10 and P5H-11 for the maintainer).
- [x] **Plan phase 12, build guides for the other node types (2026-10-22), as
  text:** `hardware/satellite/BUILD.md` (the Field Box's board and firmware
  with two or three team buttons, the LED ring and the board's OLED; plays the
  games a field controller invites it into), `hardware/io-pod/BUILD.md` (the
  Field Box's parts without the TFT, plus the enclosure switch on GPIO 47; the
  pod firmware from `build-pod`) and `hardware/target-addon/BUILD.md` (what is
  decided and what is not: **not buildable yet**), with photo placeholders and
  safety notes (cells, enclosures, hits); the project page's new build page
  (`/montagem/`, `/en/build-guides/`, `/de/bauen/`), in the header; every pin of the
  guides and the page checked against the Kconfig defaults by
  `tools/check_wiring.py`. No guide followed on real hardware yet. AC-10 met in
  text. Decisions P5J-1 to P5J-14 (open; P5J-2, P5J-4, P5J-7, P5J-8, P5J-9 and
  P5J-11 for the maintainer).

## Refresh 2026-10-22: what changed

| Change | Why | Decisions | Files |
|--------|-----|-----------|-------|
| Plan re-cut into small plan phases in build order (1-12, HW1-HW3) | Old phases A-D were large and partly blocked; phases 2-4 removed most blocks | P5R-1 | PLAN.md |
| The mode editor is a page of the simulator; the console gets a block view of its scenario builder later | A box runs only built-in scripts (K10): what a GM can install at the field is a scenario | P5R-2 | ADR.md (P5-2), PLAN.md 1, 7 |
| Field-script blocks now, with today's API; Blockly 13.3.0 vendored; one blocks file and one generator file | The field API shipped in phase 2; Blockly 13 is current and drops jsdom; no build step | P5R-3, P5R-4 | ADR.md (P5-1), PLAN.md 1 |
| `POST /api/reload` needs `field.lua` in the web view | The web view runs node scripts only | P5R-5 | ADR.md (P5-2), PLAN.md 2 |
| Editor tests in Chromium (the generator is JavaScript) | The dev image has no JavaScript runtime; the console's image has Playwright | P5R-6 | PLAN.md |
| Mode packages signed like firmware releases (text manifest with id and version, Ed25519, release-style key ids, shared vectors) | One scheme and one set of tools instead of two | P5R-7 | ADR.md (P5-4), PLAN.md 4 |
| Registry packages are controller packages (scenarios, field scripts) or proposals for `modes/` | K10; boxes do not load scripts at run time | P5R-8 (for the maintainer) | ADR.md (P5-3) |
| Registry tools in this repository first; the repository from a template, with the maintainer | P5-3 (confirmed: not yet) | P5R-9 | ADR.md (P5-3), PLAN.md 8 |
| German first, then Traditional Chinese (Taiwan) | The maintainer's choice (P5-1); German needs no new glyphs on the box | P5R-10 (for the maintainer) | ADR.md (P5-7), PLAN.md 10, 11 |
| Each language domain keeps its format; modes translate in `mode.yaml`; the box's texts are a runtime table | As built (P4R22, BN-14) | P5R-11 | ADR.md (P5-7) |
| Review checklist and sandbox battery as built | `i18n:` in `mode.yaml`; the core already tests its sandbox | P5R-12, P5R-13 | ADR.md (P5-8), PLAN.md 5 |
| Build guides: the Field Box's exists; the others remain | `hardware/field-box/BUILD.md` | P5R-14 | PLAN.md 12 |

## Plan summary (order to implement)

| # | Plan phase | Software now / hardware | Status |
|---|------------|-------------------------|--------|
| 1 | Visual mode editor | Software | **Built 2026-10-22** |
| 2 | Editor and simulator (`field.lua` in the web view, reload, Test) | Software | **Built 2026-10-22** |
| 3 | Editor completeness (geo, commands, roles, kinds) | Software | **Built 2026-10-22** |
| 4 | Mode packages and signing | Software | **Built 2026-10-22** |
| 5 | Sandbox-escape battery | Software | **Built 2026-10-22** |
| 6 | Signed packages in the controller | Software | **Built 2026-10-22** |
| 13 | Missing modes from the GM console (P5R-8; built after 6) | Software (box side host-tested); real boxes: HW3 | Planned 2026-10-22 |
| 7 | Scenario blocks in the console | Software | **Built 2026-10-22** |
| 8 | Registry repository template | Software; publishing needs the maintainer | **Built 2026-10-22** (the repository itself waits for the maintainer) |
| 9 | Community processes | Software | **Built 2026-10-22** |
| 10 | German | Software (after P5R-10) | **Built 2026-10-22** (AI-drafted, review pending) |
| 11 | Traditional Chinese (Taiwan) | Software | |
| 12 | Build guides for other node types | Software | **Built 2026-10-22** (text; photos: HW2) |
| HW1 | Carrier PCB | Needs hardware | |
| HW2 | Build guide photos | Needs hardware | |
| HW3 | Community content on the field | Needs hardware | |

## Dependencies

| Dependency | Phase | Status | Impact |
|-----------|-------|--------|--------|
| Script API (`script_api.c`) | 0, 2, 4 | Done | The editor's blocks map to it |
| Field API (`state.field{}`, `field.*`) | 2 | Done | Field blocks built in plan phase 1 |
| Simulator web view | 0 | Done; `field.lua` shown and reloads from the editor (plan phase 2) | -- |
| Mode uploads on the controller | 2 | Done (`POST /api/v1/modes`) | Plan phase 6 |
| Scenario compiler and console builder | 4 | Done | Plan phase 7 |
| Firmware release signing | 4 | Done | Plan phase 4 reuses it; plan phase 13 reuses its trust and HTTPS path |
| Re-invites and the invite dialog | 4 | Done | Plan phase 13's *Send missing modes* step |
| Field Box hardware | 1 | Boards on the bench; no built box | HW1-HW3 |

## Risks

| Risk | Level | Mitigation |
|------|-------|------------|
| A Blockly upgrade breaks blocks or output | Medium | Pinned and vendored with checksums; the round trip and unit tests in CI (`editor`) |
| A script API change breaks the editor | Medium | The round trip runs the examples against the hand-written modes' tests |
| Registry signing key compromise | Low | Revocation list; one scheme with the firmware's, reviewed once |
| Sandbox escape via a community script | Low (Medium once plan phase 13 ships) | Plan phase 5's battery in the core's CI (built; it closed two watchdog escapes, P5C-15); boxes run built-in scripts and only signed packages checked with keys in their firmware (P5B-9, P5B-14) |
| Carrier PCB layout errors | Medium | Perfboard first, KiCad DRC/ERC in CI |
| Language key drift | Medium | A parity test per domain; `tools/i18n_check.py` in plan phase 10 |

## Acceptance criteria

| # | Criterion | Status |
|---|-----------|--------|
| AC-1 | The editor generates `node.lua` (and `field.lua`) that passes simulator tests | **Met in software (2026-10-22)** |
| AC-2 | Generated Lua is readable and hand-editable | **Met (2026-10-22)** |
| AC-3 | The editor ships in English and Portuguese | **Met (2026-10-22)** |
| AC-4 | Registry index format defined and documented | **Met in software (2026-10-22)**: `registry/schema/index.schema.json`, `protocol/mode-packages.md` |
| AC-5 | Mode packages are Ed25519-signed and verifiable | **Met in software (2026-10-22)**: `tools/mode_package.py`, `protocol/vectors/mode_package.json` |
| AC-6 | Registry CI runs mode tests and checks licences | **Met in this repository's template (2026-10-22)**: CI job `registry-template` runs the template's workflow on a sample submission; in `atalaia-modes` once the maintainer creates it |
| AC-7 | A language beyond en/pt on the site | **Met in software (2026-10-22)**: `/de/`, review pending (P5H-5) |
| AC-8 | Built-in modes carry en and pt texts | **Met differently**: `mode.yaml` `i18n:` (P4R22) |
| AC-9 | Carrier PCB schematic passes KiCad ERC | Pending (needs hardware) |
| AC-10 | Build guides for the Field Box and the Satellite | **Met in text (2026-10-22)**: the Satellite's (and the I/O pod's and target addon's) beside the Field Box's, on the project page in pt, en, de; photos with HW2 |
| AC-11 | CONTRIBUTING.md documents mode submission | **Met (2026-10-22)**: "Submitting a community mode", `docs/community/` |
| AC-12 | CI includes a sandbox-escape job | **Met (2026-10-22)**: CI job `sandbox-escape`, `core/tests/test_sandbox_escape.c` under ASan and UBSan |
| AC-13 | (new, P5R-8) A box gets a signed mode it lacks from its controller between games, checks and plays it | Pending (plan phase 13, HW3) |

## Verification of plan phase 1 (2026-10-22)

| Command | Result |
|---------|--------|
| `docker run --rm -v "$PWD:/src" atalaia-dev sh -c "BUILD=/tmp/c sh tools/check.sh"` (clean build folder) | See the coordinator's commit for the final run |
| `python3 tools/docker_editor.py` | 15 browser tests, OK |
| `reuse lint` | See the commit |

## Verification of plan phase 2 (2026-10-22)

| Command | Result |
|---------|--------|
| `docker run --rm -v "$PWD:/src" atalaia-dev sh -c "BUILD=/tmp/c sh tools/check.sh"` (clean build folder) | See the coordinator's commit for the final run |
| `python3 tools/docker_editor.py` | 18 browser tests, OK |
| `python3 -m unittest tests.test_live` (in `simulator/`, also in `check.sh`) | 18 tests, OK |

## Verification of plan phase 7 (2026-10-22)

| Command | Result |
|---------|--------|
| `docker run --rm -v "$PWD:/src" -w /src -e BUILD=/tmp/c atalaia-dev sh tools/check.sh` | exit 0 (simulator 337, controller 611, server's shared tests 92, OK) |
| `python3 tools/docker_console.py` | 54 browser tests, OK (7 new in `test_scenario_blocks.py`) |
| `python3 tools/docker_editor.py` | 24 browser tests, OK (the mode editor unchanged) |
| `reuse lint` (a copy without build output) | compliant |

## Verification of the editor's package (2026-10-22)

| Command | Result |
|---------|--------|
| `python3 tools/docker_editor.py` | 30 browser tests, OK (5 new: the shared vectors, every built-in mode, refusals alike, the three examples through the button with `sign` and `verify` run as shown, refusals in the page); a mutation of the header (mode `0640`) fails 25 subtests |
| `docker run --rm -v "$PWD:/src" -w /src -e BUILD=/tmp/c atalaia-dev sh tools/check.sh` | exit 0 (simulator 344, controller 629, server's shared tests 92, registry template 18, OK; `i18n_check`: editor 241/241 in en, pt and de; `build_site --check` OK) |
| `reuse lint` (a copy without build output) | compliant (1854 files) |

## Next steps

1. Plan phase 13 on real boxes (HW3): a Field Box with a mode key built in
   fetching from the bench controller; and the end-to-end test of the C host
   box (`box_host --mode-keys --mode-source`) against the real controller
   over HTTPS, which the host tests only model with files.
2. The review of the German by German-speaking players (P5H-5); mode names and
   screens in German (P5H-7). Plan phase 7 is built;
   its P5F-2 (the CSP's two style hashes instead of `'unsafe-inline'`), P5F-4
   (refuse rather than rewrite; comments go once the blocks change the YAML)
   and P5F-5 (the block set, typed references) are for the maintainer. Plan
   phases 8 and 9 are built: creating `atalaia-modes` from
   `registry/template/` waits for the maintainer (P5-3, P5R-9;
   `docs/community/registry.md`, "Creating the repository"), as do P5G-2,
   P5G-3, P5G-8, P5G-9, P5G-12 (accepting the RFC), P5G-13 and P5G-14.
3. Left from plan phases 3-6, small (the editor making the package itself is
   built, P5I-1 to P5I-6, signing staying offline):
   `protocol/vectors/controller_api.json`
   has no contract cases for the new `/api/v1/mode-packages` endpoints yet
   (the Android controller role does not serve them); P5C-15 (the two sandbox
   fixes) and P5C-18 (packages stay installed when their key is revoked) were
   accepted by the maintainer; the other decisions of P5C-1 to P5C-21 are open
   for the maintainer's review.
4. Plan phase 12 is built as text: the first Satellite and the first I/O pod
   built from their guides (photos in place of the placeholders, the
   **Verify at the first build** items answered: runtime, the pod's current from
   a phone, the enclosures) are HW2. For the maintainer: P5J-2 (the Satellite is
   the Field Box's firmware with fewer parts), P5J-4 (no piezo buzzer without a
   firmware change), P5J-7 (no separate siren on the pod), P5J-8 (a phone
   charging the pod's cell), P5J-9 (the target addon's open questions: the bus
   voltage, and no free GPIO on a Field Box for its interrupt line) and P5J-11
   (the page's address and words).

## Verification of plan phase 12 (2026-10-22)

| Command | Result |
|---------|--------|
| `docker run --rm -v "$PWD:/src" -w /src -e BUILD=/tmp/c atalaia-dev sh tools/check.sh` | see the report of the commit |
| `python3 tools/check_wiring.py` | OK; mutated pins in each guide and in the page fail as expected |
| `python3 tools/build_site.py --check` | OK (18 pages, the new page in three languages) |
| Every page in Chromium at 320, 360 and 1200 px | no horizontal scroll (the German main page's hero fixed, P5J-14) |
