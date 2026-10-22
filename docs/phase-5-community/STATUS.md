<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 5 -- Community: Status

**Current phase:** Implementation (plan phases 1-6 and 13a built in software 2026-10-22: the visual mode editor complete, its link to the simulator, signed mode packages, the sandbox-escape battery, signed packages in the controller, and the controller, console and protocol side of missing modes sent to boxes)
**Phase status:** In progress
**Risk level:** Medium
**Last updated:** 2026-10-22 (plan phase 13a built; plan phases 3-6 built, P5B-9 answered; plan phase 2 built, plan phase 13 planned from P5R-8; refreshed after phases 2-4 software; first written 2026-10-18)
**Next step:** plan phase 13b (the box's side of missing modes, against the contract in `protocol/mode-packages.md`), then plan phase 7 (scenario blocks in the console)

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
| 7 | Scenario blocks in the console | Software | |
| 8 | Registry repository template | Software; publishing needs the maintainer | |
| 9 | Community processes | Software | |
| 10 | German | Software (after P5R-10) | |
| 11 | Traditional Chinese (Taiwan) | Software | |
| 12 | Build guides for other node types | Software | |
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
| AC-6 | Registry CI runs mode tests and checks licences | Pending (plan phase 8; the repository needs the maintainer) |
| AC-7 | A language beyond en/pt on the site | Pending (plan phase 10) |
| AC-8 | Built-in modes carry en and pt texts | **Met differently**: `mode.yaml` `i18n:` (P4R22) |
| AC-9 | Carrier PCB schematic passes KiCad ERC | Pending (needs hardware) |
| AC-10 | Build guides for the Field Box and the Satellite | Field Box done; Satellite pending (plan phase 12) |
| AC-11 | CONTRIBUTING.md documents mode submission | Pending (plan phase 9) |
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

## Next steps

1. Plan phase 13b (in progress, in parallel with 13a, which is built):
   `mode_fetch.c` with the box's C reader of the package vectors
   (`box_checks`, `reports`), keys 16 and 17 in `core/src/join.c` (the
   `mode_fetch` join vectors), `CONFIG_ATALAIA_MODE_KEYS`, fetched slots on
   LittleFS, `node.modes_failed` (id 53, data `mode` key 38) in
   `protocol/schema/events.yaml`, all as `protocol/mode-packages.md`,
   "Fetching missing modes", says. Then the end-to-end test with the C host
   box against the real controller. P5B-9 is answered: mode keys built into the
   box's firmware only.
2. Plan phase 7 (scenario blocks in the console); 8 and 9 (the registry
   template and community processes) now have the package tools and the
   battery to build on; 10 after P5R-10 (answered: German first).
3. Left from plan phases 3-6, small: the editor does not yet make a package
   itself (it downloads the files; `tools/mode_package.py pack` makes the
   archive, and signing stays offline); `protocol/vectors/controller_api.json`
   has no contract cases for the new `/api/v1/mode-packages` endpoints yet
   (the Android controller role does not serve them); P5C-15 (the two sandbox
   fixes) and P5C-18 (packages stay installed when their key is revoked) were
   accepted by the maintainer; the other decisions of P5C-1 to P5C-21 are open
   for the maintainer's review.
