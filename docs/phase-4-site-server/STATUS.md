<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 4 -- Site Server and Advanced Play: Status

**Current phase:** Planning
**Phase status:** Complete
**Risk level:** High
**Last verified:** 2026-10-18

## Completed

- [x] Research phase: `RESEARCH.md`
- [x] Architecture decisions: `ADR.md` (10 ADRs: ADR-P4-1 through ADR-P4-10)
- [x] Implementation plan: `PLAN.md` (8 phases: A through H, 16 acceptance criteria, weekend milsim gate test plan)

## Pending

Implementation is paused until Phase 2D (Python controller) and
Phase 3 (Android shell, player app, GPS, chrono) land.

Phases A (site server skeleton), B (Master and Satellites, Target
Windows modes), and E (custom scenario DSL) can proceed immediately
-- they have no dependency on Phase 2D or Phase 3.

Phases C (sync protocol) and D (ATAK/CoT controller integration)
require Phase 2D.

Phase F (VIP/Payload, Hacking Terminal) requires Phase 3.

Phase G (remote setup) requires Phase C.

Phase H (integration and weekend milsim gate) requires all other
phases plus Phase 2F (hardware) and Phase 3.

To resume: `--implement` with Phase A as the first target.

## Plan summary

| Phase | Scope | Status |
|-------|-------|--------|
| Research | Codebase inventory, spec requirements, architecture analysis, threat model, assumptions | Complete |
| Architecture | ADR-P4-1 through ADR-P4-10 (database schema, auth, sync, multi-tenant, chrono signing, scenario DSL, ATAK, GDPR, geo utilities, deployment) | Complete |
| Planning | Implementation plan with 8 phases (A-H), 16 acceptance criteria, weekend milsim gate test plan, dependency graph | Complete |
| Implementation | Paused -- waiting for Phase 2D and Phase 3 | Pending |

## Dependencies

| Dependency | Status | Impact on Phase 4 |
|------------|--------|-------------------|
| Phase 2A: Protocol codecs | Complete | None |
| Phase 2B: Simulator (RadioModel, FieldController) | Complete | None |
| Phase 2C: Core field_ops API (state.field{}, field.*) | Complete | None -- field.lua API is available |
| Phase 2D: Python controller (FastAPI, SQLite, MQTT) | Pending | **Critical** -- site server shares framework and sync protocol |
| Phase 2E: GM console (Preact+HTM PWA) | Pending | **Moderate** -- site server serves the same console |
| Phase 2F: Hardware integration and field test | Pending | **High** -- weekend milsim gate requires working hardware |
| Phase 3: Android shell, player app, GPS, chrono | Parallel design | **High** -- VIP, Hacking Terminal, chrono registry depend on Phase 3 |
| Phase 1: Target addon hardware | Not started | **High** -- Target Windows mode requires addon |

## Key findings from research

1. Python / FastAPI + PostgreSQL is the clear choice for the site server.
2. Sync is conflict-free by design (append-only events, grow-only scores).
3. GDPR compliance is scoped but requires legal review for hosted mode.
4. All four advanced modes need field.lua (Phase 2C, complete).
5. Three of four modes depend on Phase 3 deliverables.
6. ATAK / CoT is a well-defined open standard; no SDK licence needed.
7. The weekend milsim gate should be staged (desk, small, scale, weekend).
8. 10 architecture decisions identified for the ADR phase.
9. 13 assumptions about earlier phases documented with impact levels.
10. 12 risks identified with mitigations.
