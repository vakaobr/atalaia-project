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

Phase 2 A-E is complete (2026-10-18).  Phase 3 design is complete
but not yet implemented.

Phases A (site server skeleton), B (Master and Satellites, Target
Windows modes), C (sync protocol), D (ATAK/CoT), and E (custom
scenario DSL) can proceed immediately -- Phase 2D is done.

Phase F (VIP/Payload, Hacking Terminal) requires Phase 3
implementation.

Phase G (remote setup) requires Phase C.

Phase H (integration and weekend milsim gate) requires all other
phases plus Phase 2F (hardware) and Phase 3 implementation.

To resume: `--implement` with Phase A as the first target.

## Plan summary

| Phase | Scope | Status |
|-------|-------|--------|
| Research | Codebase inventory, spec requirements, architecture analysis, threat model, assumptions | Complete |
| Architecture | ADR-P4-1 through ADR-P4-10 (database schema, auth, sync, multi-tenant, chrono signing, scenario DSL, ATAK, GDPR, geo utilities, deployment) | Complete |
| Planning | Implementation plan with 8 phases (A-H), 16 acceptance criteria, weekend milsim gate test plan, dependency graph | Complete |
| Implementation | Phases A-E ready (Phase 2D done); F waits for Phase 3; H waits for all | Pending |

## Dependencies

| Dependency | Status | Impact on Phase 4 |
|------------|--------|-------------------|
| Phase 2A: Protocol codecs | Complete | None |
| Phase 2B: Simulator (RadioModel, FieldController) | Complete | None |
| Phase 2C: Core field_ops API (state.field{}, field.*) | Complete | None -- field.lua API is available |
| Phase 2D: Python controller (FastAPI, SQLite, MQTT) | **Complete** | Site server shares framework and sync protocol |
| Phase 2E: GM console (Preact+HTM PWA) | **Complete** | Site server serves the same console |
| Phase 2F: Hardware integration and field test | Pending | **High** -- weekend milsim gate requires working hardware |
| Phase 3: Android shell, player app, GPS, chrono | Design complete | **High** -- VIP, Hacking Terminal, chrono registry depend on Phase 3 |
| Phase 1: Target addon hardware | Not started | **High** -- Target Windows mode requires addon |

## Phase 2 and 3 handoff (2026-10-18)

Phase 2 implementation (A-E) is complete and Phase 3 design is
complete (not yet built). Key changes affecting Phase 4:

- **Controller package path**: `controller/atalaia_controller/`, not
  `controller/src/`.
- **Controller auth**: bearer tokens (read token, GM token), not
  JWT/sessions or API-key auth. The site server authenticates to the
  controller with the GM token (writes) and read token (reads). The
  controller authenticates to the site server with a 256-bit API key.
- **Event unique constraint**: `(game_id, node_id, seq, game_time,
  type)`, not just `(game_id, node_id, seq)`. Site server schema
  (ADR-P4-1) updated to match.
- **Scenario compiler location**: runs on the field controller as a
  shared Python library at `controller/atalaia_controller/scenarios/`.
  The site server imports and reuses it. A field without a site
  server can still build custom scenarios (local-first per spec
  sections 3 and 11). ADR-P4-6 updated.
- **Chrono signing**: Ed25519 per marshal in both Phase 3 and Phase 4,
  confirmed aligned with ADR-P4-5.
- **Event ID allocation**: Phase 3 uses IDs 25-26 and 33-41; Phase 2
  mode pack uses 27-32; Phase 4 starts at ID 42.
- **Player tokens**: HMAC-SHA256-signed JSON (not JWT), with
  player_id, team, squad, role, game_id, exp, signed with game key.
- **GPS**: NOT on the Field Box (E21); positions come from phones/pods
  only. VIP/Payload mode unaffected (uses player app GPS).
- **Hold-All Domination and Last Stand**: moved to Phase 2 mode pack
  (decision R6), no longer Phase 3.

RESEARCH.md, ADR.md and PLAN.md updated with a full handoff section.

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
