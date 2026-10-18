<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 5 -- Community: Status

**Current phase:** Planning complete -- ready for implementation
**Risk level:** Medium
**Last updated:** 2026-10-18

Phase 5 is the community layer: visual mode editor (Blockly), mode
registry with signing and a verified badge, carrier PCB, translations,
and build guides. It is ongoing after the first release (design-spec.md
section 16). This is the last designed phase; future work resumes with
`--implement`.

## Completed

- [x] Research phase: `RESEARCH.md`
- [x] Architecture decisions: `ADR.md` (8 ADRs: P5-1 through P5-8)
- [x] Implementation plan: `PLAN.md` (4 phases: A through D)

## Ready for implementation

The plan is complete and thorough enough that an implementer can start
from `PLAN.md` without re-reading the research or ADRs (though it
references them). Implementation begins with Phase A (visual mode
editor), which can start immediately -- it depends only on the phase 0
script API and existing mode patterns.

## Work streams

| Stream | Scope | Can start now | Blocked on |
|--------|-------|---------------|------------|
| Visual editor (node scripts) | Blockly block definitions, Lua code generator, editor UI | Yes -- script API is stable | -- |
| Visual editor (field scripts) | `state.field{}`, `field.*` blocks | No | Phase 2C: field API implementation |
| Editor-simulator integration | Hot-reload endpoint, editor tab in web view | Yes (after Phase A) | Phase A: editor generates valid Lua |
| Mode registry | Index format, signing tooling, submission process, CI | Yes -- independent of platform | -- |
| Registry deployment | Live index on GitHub Pages, controller sync | No | Phase 2D: controller REST API |
| Carrier PCB | KiCad schematic and layout | No | Phase 1 hardware: validated pin assignments |
| Build guides (text) | BOM, assembly steps, firmware flashing, config | Yes -- existing docs cover this | -- |
| Build guides (photos) | Step-by-step photos | No | Phase 1 hardware: physical prototypes |
| i18n expansion (site + editor) | Additional language YAML files, site template updates | Yes -- workflow established | -- |
| i18n expansion (modes) | `i18n/` folders in built-in modes | Yes -- format defined | -- |
| i18n expansion (firmware) | Extract screen strings to locale table | Partially | Phase 1 hardware for testing |
| Community processes | Mode submission docs, review checklist, CONTRIBUTING.md update | Yes | -- |
| CI additions | editor-test, sandbox-escape, i18n-check, pcb-check | Yes (except pcb-check) | -- |

## Plan phases

| Phase | Focus | Can start now | Key deliverables |
|-------|-------|---------------|-----------------|
| A | Visual mode editor | Yes | Block definitions, Lua generator, editor UI, i18n, CI round-trip test |
| B | Editor-simulator integration + Mode registry | Yes (registry); after Phase A (integration) | POST /api/reload, signing tooling, registry repo + CI, sandbox-escape tests |
| C | i18n expansion, build guides, community processes | Yes (in parallel with B) | Unified i18n across 4 domains, third locale, build guide text, CONTRIBUTING.md update |
| D | Carrier PCB + blocked items | No (blocked) | KiCad PCB, field-script blocks, build guide photos |

## Dependencies

| Dependency | Phase | Status | Impact |
|-----------|-------|--------|--------|
| Script API (`script_api.c`) | 0 | Done | Editor blocks map 1:1 to this API |
| Field API (`state.field{}`, `field.*`) | 2C | Pending | Field-script editor blocks wait on this |
| Simulator web view | 0 | Done | Editor integrates with existing web view |
| Mode push over Wi-Fi/BLE | 2D | Pending | Registry-to-node delivery |
| Controller REST API | 2D | Pending | Mode upload endpoint |
| Field Box hardware | 1 | Blocked on parts | Carrier PCB, build guide photos |
| Firmware Ed25519 signing | 1-2 | Designed | Registry uses same scheme |

## Risks

| Risk | Level | Mitigation |
|------|-------|------------|
| Blockly version breaks block definitions | Medium | Pin version, vendor or integrity hash, test on upgrade |
| Script API changes break editor | Medium | CI: generate Lua from all example blocks, run in simulator |
| Registry signing key compromise | Low | Key revocation list, incident response doc |
| Sandbox escape via community mode | Low | Fuzz testing, CI escape-pattern job, maintainer review |
| Carrier PCB layout errors | Medium | Perfboard first, KiCad DRC/ERC in CI |
| i18n key drift across locales | Medium | CI completeness check (existing for en/pt, extended to all) |

## Acceptance criteria

| # | Criterion | Status |
|---|-----------|--------|
| AC-1 | Blockly editor generates valid `node.lua` that passes simulator tests | Pending |
| AC-2 | Generated Lua is readable and hand-editable | Pending |
| AC-3 | Editor ships in English and Portuguese | Pending |
| AC-4 | Mode registry index format is defined and documented | Pending |
| AC-5 | Mode packages are Ed25519-signed and verifiable | Pending |
| AC-6 | Registry CI runs mode tests and checks licences | Pending |
| AC-7 | At least one additional language beyond en/pt is supported on the site | Pending |
| AC-8 | Built-in modes have `i18n/` with en and pt translations | Pending |
| AC-9 | Carrier PCB schematic passes KiCad ERC | Pending (blocked on hardware) |
| AC-10 | Build guides exist for Field Box and Satellite | Pending (text can start; photos blocked) |
| AC-11 | CONTRIBUTING.md documents mode submission process | Pending |
| AC-12 | CI includes sandbox-escape test job | Pending |

## Next steps

1. Begin implementation with Phase A: Blockly block definitions for node-script API
2. In parallel, start Phase B2: registry index schema, signing tooling, `atalaia-modes` repo setup
3. In parallel, start Phase C streams that need no Phase A output: mode i18n, build guide text, community docs
