<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 5 -- Community: Status

**Current phase:** Implementation (plan phase 1, the visual mode editor, built in software 2026-10-22)
**Phase status:** In progress
**Risk level:** Medium
**Last updated:** 2026-10-22 (refreshed after phases 2-4 software; first written 2026-10-18)
**Next step:** plan phase 2 (the simulator's web view runs `field.lua`, `POST /api/reload`, the editor's "Test" button)

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
| 2 | Editor and simulator (`field.lua` in the web view, reload, Test) | Software | Next |
| 3 | Editor completeness (geo, commands, roles, kinds) | Software | |
| 4 | Mode packages and signing | Software | |
| 5 | Sandbox-escape battery | Software | |
| 6 | Signed packages in the controller | Software | |
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
| Simulator web view | 0 | Done; no `field.lua` yet | Plan phase 2 |
| Mode uploads on the controller | 2 | Done (`POST /api/v1/modes`) | Plan phase 6 |
| Scenario compiler and console builder | 4 | Done | Plan phase 7 |
| Firmware release signing | 4 | Done | Plan phase 4 reuses it |
| Field Box hardware | 1 | Boards on the bench; no built box | HW1-HW3 |

## Risks

| Risk | Level | Mitigation |
|------|-------|------------|
| A Blockly upgrade breaks blocks or output | Medium | Pinned and vendored with checksums; the round trip and unit tests in CI (`editor`) |
| A script API change breaks the editor | Medium | The round trip runs the examples against the hand-written modes' tests |
| Registry signing key compromise | Low | Revocation list; one scheme with the firmware's, reviewed once |
| Sandbox escape via a community script | Low | Plan phase 5 battery in the core's CI; boxes run built-in scripts only |
| Carrier PCB layout errors | Medium | Perfboard first, KiCad DRC/ERC in CI |
| Language key drift | Medium | A parity test per domain; `tools/i18n_check.py` in plan phase 10 |

## Acceptance criteria

| # | Criterion | Status |
|---|-----------|--------|
| AC-1 | The editor generates `node.lua` (and `field.lua`) that passes simulator tests | **Met in software (2026-10-22)** |
| AC-2 | Generated Lua is readable and hand-editable | **Met (2026-10-22)** |
| AC-3 | The editor ships in English and Portuguese | **Met (2026-10-22)** |
| AC-4 | Registry index format defined and documented | Pending (plan phase 4) |
| AC-5 | Mode packages are Ed25519-signed and verifiable | Pending (plan phase 4) |
| AC-6 | Registry CI runs mode tests and checks licences | Pending (plan phase 8; the repository needs the maintainer) |
| AC-7 | A language beyond en/pt on the site | Pending (plan phase 10) |
| AC-8 | Built-in modes carry en and pt texts | **Met differently**: `mode.yaml` `i18n:` (P4R22) |
| AC-9 | Carrier PCB schematic passes KiCad ERC | Pending (needs hardware) |
| AC-10 | Build guides for the Field Box and the Satellite | Field Box done; Satellite pending (plan phase 12) |
| AC-11 | CONTRIBUTING.md documents mode submission | Pending (plan phase 9) |
| AC-12 | CI includes a sandbox-escape job | Pending (plan phase 5) |

## Verification of plan phase 1 (2026-10-22)

| Command | Result |
|---------|--------|
| `docker run --rm -v "$PWD:/src" atalaia-dev sh -c "BUILD=/tmp/c sh tools/check.sh"` (clean build folder) | See the coordinator's commit for the final run |
| `python3 tools/docker_editor.py` | 15 browser tests, OK |
| `reuse lint` | See the commit |

## Next steps

1. Plan phase 2: `field.lua` in the simulator's web view, `POST /api/reload`,
   the editor's "Test" button.
2. In parallel: plan phase 4 (mode packages and signing) and plan phase 5
   (sandbox battery), which need nothing from the editor.
3. The maintainer: P5R-8 (community node scripts on boxes) and P5R-10 (the
   third language's order) before plan phases 6 and 10.
