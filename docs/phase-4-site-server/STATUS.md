<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 4 -- Site Server and Advanced Play: Status

**Current phase:** Implementation (plan phases 1, 10 and 11 built in software, 2026-10-19)
**Phase status:** In progress
**Risk level:** High
**Last verified:** 2026-10-19 (plan phase 11, full clean-copy check)
**Next step:** plan phase 2 (Target Windows, logic) on the modes chain; plan phase 12 (personal data) on the site server chain

## Completed

- [x] Research phase: `RESEARCH.md`
- [x] Architecture decisions: `ADR.md` (ADR-P4-1 to ADR-P4-10; ADR-P4-11 and ADR-P4-12 added 2026-10-19, proposed)
- [x] Implementation plan: `PLAN.md`
- [x] Phase 2 and 3 design handoff (2026-10-18)
- [x] **Refresh after phase 3 software (2026-10-19):** every ADR re-checked against the built code, with dated amendments; RESEARCH and PLAN corrected in place, each with a "Refresh 2026-10-19" section; the plan re-sequenced into 22 software plan phases and 4 hardware ones; decisions P4R1-P4R26 in `docs/review/decisions-to-review.md` (all open)

## Refresh 2026-10-19: what changed

| Change | Why | Decisions | Files |
|--------|-----|-----------|-------|
| Plan re-cut and re-ordered: modes and core first (1-9), then the site server (10-22); hardware last (HW1-HW4) | The maintainer wants code while waiting for the Heltec V4 boards; every plan phase is small enough to be verified from a clean copy and committed alone | P4R20 | PLAN.md |
| Event ids 42-47, data keys 34-36; no `satellite.*`; `target.hit` already 16 | Satellites send `zone.captured` (spec section 15); the Medic Kit took 50-51 | P4R1, P4R2 | ADR.md (P4-6), PLAN.md |
| Custom scenarios as a `kind: scenario` package over a built-in `org.atalaia.objectives` role package | Boxes run built-in scripts only; a new mode needs a flash (K10) | P4R7-P4R9, P4R24 | ADR.md (P4-6), PLAN.md 6-8 |
| The controller opens every connection; no controller tokens on the site server; SHA-256 API keys; games as `(field, game_id, game_seed)`; per-node score merge | 4G NAT; a GM's adjustment can be negative; the 16-bit game id repeats | P4R10-P4R13 | ADR.md (P4-1, P4-3), PLAN.md 13 |
| Chrono registry stores the signed readings verbatim and public keys only | Phase 3 built per-reading Ed25519 records signed on the phone | P4R14, P4R15 | ADR.md (P4-1, P4-5), PLAN.md 14 |
| Positions never as events or on the site server; `position.fix` for `field.lua`, `gps.fix` on Android props | Phase 3 keeps positions on the controller, filtered by role | P4R6, P4R25 | ADR.md (P4-8, P4-9), PLAN.md 5 |
| Hacking Terminal on the keypad; Target Windows' `hit` input and `game.teams()`; engineer-only deferred | No touch input or team list exists; player tags carry no squad | P4R3-P4R5, P4R26 | PLAN.md 2, 4 |
| ATAK: props and zones only on multicast, a georeferenced field image | Field Boxes have no GPS; multicast cannot filter by role | P4R18 | ADR.md (P4-7), PLAN.md 9 |
| Club profiles and branding sync | Phase 3 built branding per controller | P4R19 | PLAN.md 18 |
| Site server image `python:3.12-slim` with pinned deps, package `atalaia_server`, `unittest` on PostgreSQL 16 (CI service container, local ephemeral container) | The dev image's packages are FastAPI 0.101 with pydantic 1.10; one test runner in the repository | P4R16, P4R17, P4R9 | ADR.md (P4-10), PLAN.md 10 |
| Controller additions AGPL-3.0-or-later; mode folders with underscores, translations in `mode.yaml` | REUSE.toml and the repository's conventions | P4R21, P4R22, P4R23 | PLAN.md |

## Plan summary (order to implement)

| # | Plan phase | Software now / hardware | Depends on | Status |
|---|------------|-------------------------|------------|--------|
| 1 | Master and Satellites | Software, now | -- | Done in software (2026-10-19; not on radio hardware) |
| 2 | Target Windows (logic), `game.teams()`, `hit` input | Software, now | -- | **Next** |
| 3 | Geo utilities in the core | Software, now | -- | Pending |
| 4 | Hacking Terminal | Software, now | -- | Pending |
| 5 | VIP / Payload | Software, now | 3 | Pending |
| 6 | Scenario packages and the objectives role package | Software, now | -- | Pending |
| 7 | Scenario compiler and validator | Software, now | 3, 6 | Pending |
| 8 | Scenarios in the controller, console and app | Software, now | 7 | Pending |
| 9 | ATAK / CoT emitter | Software, now | 3 | Pending |
| 10 | Site server skeleton and test tooling | Software, now | -- | **Done in software** (2026-10-19) |
| 11 | Accounts, sessions and roles | Software, now | 10 | **Done in software** (2026-10-19) |
| 12 | Personal data | Software, now | 11 | **Next** (site server chain) |
| 13 | Controller sync | Software, now | 10, 11 | Pending |
| 14 | Chrono registry | Software, now | 13 | Pending |
| 15 | Scheduling, field pages and feeds | Software, now | 11 | Pending |
| 16 | Registration and game-day sync | Software, now | 13, 15 | Pending |
| 17 | Registration import and adapters | Software, now | 16 | Pending |
| 18 | Club profiles and branding sync | Software, now | 13 | Pending |
| 19 | Device health, firmware catalogue, remote GM | Software, now | 13 | Pending |
| 20 | Game history and the scenario library | Software, now | 13, 7 | Pending |
| 21 | Hosted multi-tenant mode | Software, now | 10-20 | Pending |
| 22 | Deployment (Caddy, setup, backup, restore) | Software, now | 10 | Pending |
| HW1 | Sync over a real 4G link | Hardware and a deployment | 13, phase 2 F | Waiting for boards |
| HW2 | Target addon | Hardware | 2 | Waiting for the addon |
| HW3 | Phones in the field (VIP, payload, terminal, ATAK) | Hardware | 4, 5, 9, phase 3 G | Waiting for boards and phones |
| HW4 | Chrono end to end, weekend milsim gate | Hardware and players | all, phase 2 F, phase 3 G | Waiting |

Plan phases 1-9 and 10-22 are two independent chains; they can run in
parallel worktrees.

## Plan phase 1: Master and Satellites (built 2026-10-19)

`modes/master_satellites` (`org.atalaia.master_satellites`, "Mestre e
Satélites"): `master` and `satellite` boxes capture as in Domination
and do not score; `field.lua` scores the master's holder every
`tick_s` with `points_per_tick` plus `satellite_bonus_pct` % of it per
satellite held (whole points, rounded down), nothing below
`min_satellites`, and frees every satellite with
`field.send(id, "set_owner", { team = "none" })` when the master
leaves a team's hands. Screens `standby`, `captured`, `master_status`
(told by `field.lua` with the mode command `status`). No new events.
A built-in Field Box preset (the tenth; the box's own picker shows
nine, M1-4) and the app's generated catalogue.

Tested: 8 YAML tests in the simulator and in Dart through the core,
the controller with two host boxes on the host modem
(`test_box_e2e.py`, the satellite freed over the radio), the Field Box
host tests (the preset seeded and run, the templates found) and 4
reference images, 4 app goldens. Not run: Wokwi (R7), radio boards.
Decisions M1-1 to M1-6 (open).

## Plan phase 10: site server skeleton (built 2026-10-19, in software)

What exists: `server/atalaia_server/` (app factory, `ATALAIA_*` settings,
the async database layer on PostgreSQL 16, the base models and UUIDv7 keys,
security headers, `GET /api/v1/health` and the token-guarded
`GET /api/v1/metrics`), Alembic with `0001_base` (fields, users, roles
seeded, user_field_roles, sessions, audit_log), the server's image
(`server/Dockerfile`: the core built in its own stage, `python:3.12.14-slim`
by digest, hash-pinned requirements, an unprivileged user, a `test` target),
`server/docker-compose.yml` (local trial) and `docker-compose.test.yml`,
`tools/docker_server.py` (`test`, `migrations`, `build`, `up`, `down`) and
CI's `server` job with a `postgres:16-alpine` service container.

Tests: 34 in the test image against PostgreSQL 16 (health and its 503,
metrics and their token, security headers, the served app over real HTTP,
model defaults, the migration round trip per revision, migrations equal to
the models, the roles seed; settings, UUIDv7 with RFC 9562's example, the
shared modules importing without the web stack, every built-in mode loading
in the image's core). 19 of them (no database) also run in tools/check.sh.
Not yet: accounts and anything with personal data (plan phases 11, 12), the
controller sync (13), deployment with HTTPS and backups (22). Not run here:
the CI job itself (its commands were run by hand against a container started
the same way). Decisions S10-1 to S10-12, all open.

## Plan phase 11: accounts, sessions and roles (built 2026-10-19, in software)

What exists: registration with consent and the password policy (NIST SP
800-63B, the NCSC's 100,000 breached passwords), Argon2id hashes with
ADR-P4-2's parameters; login, the TOTP step (RFC 6238, each code once,
seeds encrypted), 15-minute access tokens checked against the session and
the roles in the database on every request, refresh tokens in a
SameSite=Strict cookie stored as SHA-256 and rotated, a replay ending the
session; logout; TOTP enrolment, confirmation and removal; lockouts and
rate limits (in memory); fields and per-field roles with TOTP required for
admin, gm and marshal; the audit log; `python -m atalaia_server
create-admin`; metrics for server administrators; migration
`0002_accounts`; argon2-cffi, PyJWT and pyotp pinned by hash.

Tests: 124 in the test image against PostgreSQL 16 (90 new: passwords,
TOTP with the RFC 6238 and RFC 4226 vectors, tokens, rate limits, accounts
and sessions, roles, `create-admin` run as a command, 0002 with data); 21
(no database, no server dependencies) also run in tools/check.sh. Not yet:
per-game roles (with `games`, plan phase 13), personal data rights (12),
deployment behind Caddy with the client address from the proxy (22).
Decisions S11-1 to S11-15, all open; S11-4 (the breached list's licence)
and S11-12 (lockouts per address behind a field's shared 4G address) want
the maintainer's eye.

## Dependencies

| Dependency | Status (2026-10-19) | Impact on Phase 4 |
|------------|---------------------|-------------------|
| Phase 2 A-E and mode pack | Done in software | None |
| Phase 2 F (hardware, field test) | Pending, needs the boards | HW1, HW4 |
| Phase 3 A-F, the Medic Kit, branding | Done in software | Old plan phase F's dependencies are met; plan phases 4, 5, 8, 16, 18 build on them |
| Phase 3 PE24 (Android controller shell), iOS | Not built | None for phase 4's software |
| Phase 3 G (field test with phones and pods) | Pending, needs the hardware | HW3, HW4 |
| Target addon (hardware/target-addon) | Design phase | HW2 |
| Wokwi CI quota (decision R7) | Used up | Firmware changes verified with host tests and ESP-IDF builds only |

## Maintainer request: scheduling, registration, publishing (2026-10-19, design only)

The maintainer asked that a field admin can schedule games, publish
them on the field's site-server page or on shared or third-party
platforms (naming jogarairsoft.pt in Portugal), and let players
register; on game day players check in at the field with a printed QR
code and declare their replicas for the chronograph (phase 3,
ADR-P3-13, now built).

| What | Where |
| --- | --- |
| Scheduling, field page, registration with pre-declared replicas, game-day sync (schedule and roster pulls, check-in push; the controller stays the authority) | `ADR.md` ADR-P4-11 (proposed; amended 2026-10-19 against the built check-in) |
| iCalendar (RFC 5545) and JSON feeds, registration import (CSV, JSON), platform adapter interface and its rules | `ADR.md` ADR-P4-12 (proposed) |
| Plan | `PLAN.md` plan phases 15, 16 and 17; constraints 16-18; AC-17 to AC-19 |
| Open questions | F13-F23 in `docs/review/decisions-to-review.md` |

**jogarairsoft.pt:** no public information or API about it was found
(web search, 2026-10-19). No adapter is designed: it needs the
platform's API documentation or an agreement, which needs the
maintainer to contact its operators (F22). No scraping.

## Key findings from research

1. Python / FastAPI + PostgreSQL for the site server, in its own image
   with its own pinned versions (P4R16).
2. Sync is conflict-free by design (append-only events, per-node
   grow-only counters); the controller opens every connection (P4R12).
3. GDPR compliance is scoped but needs a legal review for hosted mode
   (P4-6).
4. All four advanced modes and custom scenarios work through
   `field.lua` and built-in node scripts; none needs a per-game script
   on a box.
5. Phase 3's dependencies of the advanced modes are built in software;
   what waits is hardware (the target addon, real phones).
6. ATAK / CoT is an open format; no SDK licence is needed; player
   positions stay off multicast.
7. The weekend milsim gate is staged (desk, small, scale, weekend) and
   needs phase 2 F and phase 3 G.

## How to resume

Run `/sdlc phase-4-site-server --implement`. STATE.json records
`current_phase: "implementation"`, `phase_status: "in_progress"`,
`resume_with: "--implement"`, the plan phases done and the next one. Each plan phase
is verified from a clean copy (PLAN.md, "How each plan phase is
verified") and committed by the coordinator; agents do not commit.
