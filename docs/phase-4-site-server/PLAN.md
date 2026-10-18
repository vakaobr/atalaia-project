<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 4 -- Site Server and Advanced Play: Implementation Plan

Gate: **A weekend milsim runs on the platform end to end.**

Constraint: Phase 2D (Python controller) and Phase 3 (Android shell,
player app, GPS, chrono) are not yet complete. All builds run in
Docker. What can be built and tested without those phases (site server
skeleton, auth, GDPR, scenario DSL, modes that depend only on Phase 2C,
ATAK/CoT) is separated from what depends on Phase 2D (sync protocol)
or Phase 3 (VIP, Hacking Terminal, chrono end-to-end). Phase 3's
design is not available -- its interfaces are derived from the spec
and marked for re-checking when Phase 3 design completes.

---

## Scope

### In scope (software -- buildable and testable without extra hardware)

- Site server application (FastAPI + PostgreSQL + Alembic).
- Account model with Argon2id passwords, JWT sessions, TOTP 2FA.
- Role-based access control (player, squad_leader, vip, marshal, gm,
  spectator, admin) with per-field and per-game granularity.
- GDPR compliance endpoints (access, export, erasure, rectification),
  retention purge job, privacy notice and DPA templates.
- Multi-tenant hosted mode (schema-per-field, RLS defence-in-depth).
- Chrono registry: replica registration, marshal Ed25519 signing keys,
  check-in records, spot checks, cross-field sharing with double
  opt-in, violation tracking.
- Controller-to-site-server sync protocol: event batch push, score
  merge (GREATEST), chrono sync, roster pull, offline buffering,
  WebSocket live stream.
- Game scheduling, player registration, scheduled game lifecycle.
- Device health dashboard, firmware catalog, remote GM console relay.
- Master and Satellites mode (`field.lua` + `node.lua`; depends on
  Phase 2C only).
- Target Windows mode (`node.lua`; depends on Phase 2C only).
- VIP / Payload mode (`field.lua` + `node.lua`; depends on Phase 3
  GPS and player app).
- Hacking Terminal mode (`node.lua`; depends on Phase 3 Android shell).
- ATAK / CoT emitter on the controller (UDP multicast + TCP;
  `controller/src/atak.py`).
- `geo.distance()` and `geo.in_zone()` in the core Lua API
  (`core/src/script_api.c`).
- Custom scenario DSL: YAML manifest schema, Python compiler to
  `field.lua`, validation (DAG check, parameter check, zone geometry),
  CLI tool.
- New events in `protocol/schema/events.yaml`: `satellite.captured`,
  `satellite.neutralized`, `vip.extracted`, `hacking.solved`,
  `scenario.objective.completed`, `scenario.objective.failed`,
  `scenario.objective.revealed`, `scenario.started`.
- Site server Docker image and docker-compose with PostgreSQL.
- Backup and restore scripts.
- Setup script for first-time deployment.

### In scope (needs hardware or real deployment)

- End-to-end sync testing with a real Pi controller and 4G bridge.
- Target Windows mode hardware testing (piezo sensor calibration and
  debounce tuning on the target addon).
- ATAK field testing (real ATAK app on an Android phone on the field
  Wi-Fi network).
- Master and Satellites hardware testing with ESP32 Satellite builds.
- Chrono end-to-end testing with a real chronograph and NFC tags.
- Weekend milsim gate (10-20 ESP32 boxes, Pi controller, repeaters,
  4G bridge, site server, 20+ player phones, ATAK devices).

### Out of scope (later phases)

- Visual scenario editor / Blockly (Phase 5).
- TAK Server integration (Phase 5+).
- Carrier PCB (Phase 5).
- BLE room beacons for indoor positioning (Phase 3/5).
- Meshtastic as alternate transport (Phase 3+).
- DIY chronograph addon firmware (Phase 5).
- Community hub public directory and mode registry browser (Phase 5).
- Additional mode translations beyond en and pt (Phase 5).
- iOS player app (Phase 3; the site server API serves it, but the
  app is not a Phase 4 deliverable).

---

## Constraints from ADR.md (all 15 respected)

| # | Constraint | How the plan respects it |
|---|------------|--------------------------|
| 1 | PostgreSQL 16+ with SQLAlchemy 2.0 async + asyncpg; UUID PKs, `created_at` and `updated_at` timestamps | Phase A creates the schema from ADR-P4-1 via Alembic; the CI docker-compose starts PostgreSQL 16-alpine; every model carries UUID PK and timestamp columns |
| 2 | Alembic for all schema changes; every migration reversible; CI runs upgrade-downgrade-upgrade | Phase A creates the Alembic scaffold; AC-2 validates reversibility with the three-step migration test in CI |
| 3 | Argon2id for passwords, PyJWT for tokens, pyotp for TOTP; TOTP mandatory for admin/GM/marshal | Phase A implements auth; tests assert TOTP enforcement for privileged roles; the breached-password list ships as a static file |
| 4 | API-key authentication for controller sync; 256-bit key hashed with Argon2id; SHA-256 cache for fast lookup | Phase C implements the sync service; tests use a test API key; the cache is validated by a concurrency test |
| 5 | Events are append-only; scores merge by GREATEST; `UNIQUE(game_id, node_id, seq)` enforces idempotent sync | Phase C sync endpoints enforce the unique constraint; score merge uses the `GREATEST` SQL function; tests replay duplicate batches |
| 6 | Schema-per-field in hosted mode; single schema in self-hosted; Alembic iterates over tenant schemas | Phase A creates the tenant routing middleware; self-hosted tests use the public schema; hosted-mode tests create and tear down a test schema |
| 7 | Ed25519 for chrono record signing; per-marshal keypairs independent of passwords; encrypted private key recovery | Phase A creates the `marshal_signing_keys` table; Phase C implements the signing/verification flow; tests verify signature stability across password changes |
| 8 | Scenario manifests are YAML; compiler runs on the site server (Python); validation includes DAG check, parameter validation and zone geometry checks | Phase E implements the compiler with Jinja2 templates; tests compile each of the 7 objective types and run the generated Lua in the simulator |
| 9 | CoT emission via UDP multicast (primary) and TCP (secondary); `geo.distance` and `geo.in_zone` registered in the core for all scripts; zone types: circle and polygon | Phase D adds `geo.*` to the core (C); Phase D adds `atak.py` to the controller; CoT XML tests verify against known-good samples |
| 10 | GDPR: anonymise on erasure, retain for integrity; retention purge daily; privacy notice and DPA templates shipped but require legal review | Phase A implements GDPR endpoints; tests verify anonymisation preserves marshal signatures; templates ship in `docs/templates/` |
| 11 | docker-compose with Caddy or nginx for TLS; setup script generates secrets; backups use `pg_dump -Fc` with 30-day retention | Phase A creates the docker-compose and setup script; Phase H documentation includes deployment and backup runbooks |
| 12 | New events in `events.yaml`: 8 new event types for scenarios, satellites, VIP and hacking | Phase B and Phase F add events; tests validate the new events round-trip through the simulator event bus |
| 13 | SPDX headers on every file; AGPL-3.0-or-later for server; GPL-3.0-or-later for controller additions and modes; CC-BY-SA-4.0 for docs | Every phase's file lists specify the licence; a CI grep check validates headers |
| 14 | No C compiler on host; site server is pure Python; `libatalaia_core.so` cross-compiled in Docker; `cryptography` ships pre-built wheels | All validation commands use Docker; the site server Dockerfile uses `python:3.11-slim`; the core builds inside `atalaia-dev` |
| 15 | Phase 3 interfaces are assumptions; `gps.fix` events, player app role model, Android shell are assumed but must be re-verified when Phase 3 design completes | Phase F (Phase-3-dependent modes) is explicitly gated; every Phase 3 assumption is marked in the Assumptions table |

---

## Phase A: Site server skeleton (auth, DB, GDPR, deploy)

### Goal

Stand up the site server application: FastAPI with PostgreSQL,
Alembic migrations for the full ADR-P4-1 schema, Argon2id
authentication with JWT sessions and TOTP, role-based access control,
GDPR endpoints (access, export, erasure, rectification), the
retention purge job, privacy notice and DPA templates, the
docker-compose deployment, and the setup script. This phase has no
dependency on Phase 2D, Phase 3 or any hardware. Everything runs in
Docker.

### Files to create

| File | Licence | Purpose |
|------|---------|---------|
| `server/src/__init__.py` | AGPL-3.0-or-later | Package init |
| `server/src/main.py` | AGPL-3.0-or-later | FastAPI application factory, middleware, lifespan |
| `server/src/config.py` | AGPL-3.0-or-later | Configuration from env vars (DATABASE_URL, SECRET_KEY, REFRESH_SECRET, HOSTED_MODE, etc.) |
| `server/src/models.py` | AGPL-3.0-or-later | SQLAlchemy 2.0 async models for all ADR-P4-1 tables (users, fields, games, events, chrono, etc.) |
| `server/src/schemas.py` | AGPL-3.0-or-later | Pydantic v2 request/response schemas |
| `server/src/database.py` | AGPL-3.0-or-later | Async engine, session factory, tenant routing middleware |
| `server/src/auth.py` | AGPL-3.0-or-later | Argon2id hashing, JWT encode/decode, TOTP enrollment/verification, refresh token rotation, replay detection, breached-password check |
| `server/src/api/__init__.py` | AGPL-3.0-or-later | API router aggregation |
| `server/src/api/accounts.py` | AGPL-3.0-or-later | Registration, login, login/totp, refresh, logout, TOTP enrollment |
| `server/src/api/fields.py` | AGPL-3.0-or-later | Field CRUD, joule limits, field settings |
| `server/src/api/roles.py` | AGPL-3.0-or-later | Role assignment (per-field, per-game), marshal key generation |
| `server/src/api/gdpr.py` | AGPL-3.0-or-later | `GET /me/data`, `GET /me/export`, `DELETE /me`, `PATCH /me` |
| `server/src/api/health.py` | AGPL-3.0-or-later | `GET /health`, `GET /metrics` |
| `server/src/middleware/__init__.py` | AGPL-3.0-or-later | Package init |
| `server/src/middleware/auth_middleware.py` | AGPL-3.0-or-later | JWT verification dependency, role injection, `get_current_user` |
| `server/src/middleware/rate_limit.py` | AGPL-3.0-or-later | Sliding-window rate limiter (in-memory; Redis optional) |
| `server/src/middleware/security_headers.py` | AGPL-3.0-or-later | HSTS, CSP, X-Frame-Options, X-Content-Type-Options |
| `server/src/services/__init__.py` | AGPL-3.0-or-later | Package init |
| `server/src/services/gdpr_service.py` | AGPL-3.0-or-later | Anonymisation, export ZIP generation, retention purge job |
| `server/src/services/tenant_service.py` | AGPL-3.0-or-later | Create/delete tenant schema, Alembic per-tenant migration runner |
| `server/src/cli.py` | AGPL-3.0-or-later | CLI: `create-admin`, `rotate-secrets`, `purge-retention` |
| `server/src/data/breached_passwords.txt` | AGPL-3.0-or-later | Top 100k breached passwords (static, no API call) |
| `server/migrations/alembic.ini` | AGPL-3.0-or-later | Alembic config |
| `server/migrations/env.py` | AGPL-3.0-or-later | Async Alembic runner with multi-tenant schema iteration |
| `server/migrations/versions/0001_initial_schema.py` | AGPL-3.0-or-later | Full ADR-P4-1 schema: accounts, fields, devices, games, chrono, players, scheduling, scenarios, audit log, marshal signing keys |
| `server/requirements.txt` | AGPL-3.0-or-later | fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, alembic, argon2-cffi, pyjwt, pyotp, cryptography, pydantic, httpx |
| `server/pyproject.toml` | AGPL-3.0-or-later | Project metadata, pytest config, ruff config |
| `server/Dockerfile` | AGPL-3.0-or-later | python:3.11-slim, pip install, alembic upgrade head + uvicorn |
| `server/docker-compose.yml` | AGPL-3.0-or-later | atalaia-server + postgres:16-alpine + optional caddy |
| `server/docker-compose.test.yml` | AGPL-3.0-or-later | Test variant: ephemeral PostgreSQL, pytest runner |
| `server/setup.sh` | AGPL-3.0-or-later | First-time setup: generate secrets, create .env, `docker compose up` |
| `server/backup.sh` | AGPL-3.0-or-later | Daily backup: pg_dump -Fc + app-data tar.gz, 30-day retention |
| `server/tests/__init__.py` | AGPL-3.0-or-later | Package init |
| `server/tests/conftest.py` | AGPL-3.0-or-later | Fixtures: async test client, test database, test user, test field |
| `server/tests/test_auth.py` | AGPL-3.0-or-later | Registration, login, TOTP, refresh rotation, replay detection, rate limiting, breached password rejection |
| `server/tests/test_roles.py` | AGPL-3.0-or-later | Role assignment, TOTP enforcement for privileged roles, role-based endpoint access |
| `server/tests/test_gdpr.py` | AGPL-3.0-or-later | Data access, export ZIP contents, erasure anonymisation (verify marshal signatures survive), retention purge |
| `server/tests/test_models.py` | AGPL-3.0-or-later | Model creation, constraints, indexes |
| `server/tests/test_health.py` | AGPL-3.0-or-later | Health and metrics endpoints |
| `server/tests/test_tenant.py` | AGPL-3.0-or-later | Schema creation, tenant routing, RLS isolation, tenant deletion |
| `server/tests/test_migration.py` | AGPL-3.0-or-later | Alembic upgrade-downgrade-upgrade round-trip |
| `docs/templates/privacy-notice-pt.md` | CC-BY-SA-4.0 | GDPR privacy notice template (Portuguese) |
| `docs/templates/privacy-notice-en.md` | CC-BY-SA-4.0 | GDPR privacy notice template (English) |
| `docs/templates/dpa-template.md` | CC-BY-SA-4.0 | Data Processing Agreement template (hosted mode) |

### Files to modify

| File | Change |
|------|--------|
| `server/README.md` | Replace placeholder with real documentation: architecture, setup, API summary |

### Tests to create

| File | What it tests |
|------|---------------|
| `server/tests/test_auth.py` | Password hashing (Argon2id params match OWASP), login flow (username+password), TOTP flow (enrollment, verify, reject bad code), JWT access token (encode, decode, expiry), refresh token (rotation, replay detection, session revocation), rate limiting (5 attempts -> lockout), breached password rejection |
| `server/tests/test_roles.py` | Per-field role assignment, per-game role assignment, TOTP required for admin/GM/marshal, role-gated endpoints (marshal-only, admin-only, GM-only), role inheritance (admin has GM permissions) |
| `server/tests/test_gdpr.py` | `GET /me/data` returns all personal data, `GET /me/export` returns ZIP with correct files, `DELETE /me` anonymises user (username randomised, email NULL, password_hash DELETED), anonymised user's chrono records retain marshal signature and readings, retention purge deletes records past field default, guest cleanup after 30 days |
| `server/tests/test_models.py` | All ADR-P4-1 tables create successfully, UUID PKs are unique, `created_at`/`updated_at` default to now(), foreign key cascades work, UNIQUE constraints reject duplicates |
| `server/tests/test_health.py` | `/health` returns 200 with database status, `/metrics` requires admin auth |
| `server/tests/test_tenant.py` | Create tenant schema, verify tables exist, route request to tenant, verify RLS prevents cross-tenant access, delete tenant drops schema |
| `server/tests/test_migration.py` | `alembic upgrade head` succeeds, `alembic downgrade base` succeeds, second `alembic upgrade head` succeeds (idempotent) |

### Validation commands

**Site server tests (PostgreSQL in docker-compose):**

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && python -m pytest tests/ -v --tb=short"
```

**Migration reversibility test:**

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && alembic downgrade base && alembic upgrade head && echo 'Migration round-trip OK'"
```

**Docker image builds:**

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.yml build
```

---

## Phase B: Advanced modes -- no Phase 3 dependencies (Master and Satellites, Target Windows)

### Goal

Implement the two advanced game modes that depend only on Phase 2C
(`field.*` API, which is complete): Master and Satellites
(`field.lua` + `node.lua`) and Target Windows (`node.lua`). Add the
new events to `protocol/schema/events.yaml`. Write YAML event-sequence
tests that run in the simulator. No Phase 3 dependency for basic
functionality. Engineer-only satellite capture is deferred to Phase F
(requires Phase 3 NFC squad identification). Target Windows hardware
testing (piezo sensor) is deferred to Phase H.

### Files to create

| File | Licence | Purpose |
|------|---------|---------|
| `modes/master-and-satellites/mode.yaml` | GPL-3.0-or-later | Mode manifest: roles (master, satellite), capabilities, parameters (tick_s, points_per_tick, satellite_multiplier) |
| `modes/master-and-satellites/node.lua` | GPL-3.0-or-later | Satellite node script: team_input capture, emit `satellite.captured` / `satellite.neutralized` |
| `modes/master-and-satellites/field.lua` | GPL-3.0-or-later | Controller field script: multiplier tracking, master hand-change resets satellites, periodic scoring with multiplier |
| `modes/master-and-satellites/tests/test_basic.yaml` | GPL-3.0-or-later | Basic scenario: master capture, satellite capture, multiplier applied |
| `modes/master-and-satellites/tests/test_master_change.yaml` | GPL-3.0-or-later | Master changes hands: all satellites reset to neutral, multiplier resets to 1 |
| `modes/master-and-satellites/tests/test_multi_satellite.yaml` | GPL-3.0-or-later | 3 satellites: multiplier increases with each capture (x1.5, x2.0, x2.5) |
| `modes/master-and-satellites/tests/test_satellite_recapture.yaml` | GPL-3.0-or-later | Satellite recaptured by opposing team: multiplier adjusts |
| `modes/master-and-satellites/i18n/en.yaml` | GPL-3.0-or-later | English strings |
| `modes/master-and-satellites/i18n/pt.yaml` | GPL-3.0-or-later | Portuguese strings |
| `modes/target-windows/mode.yaml` | GPL-3.0-or-later | Mode manifest: roles (target), capabilities (hit, led), parameters (interval_s, window_s, hit_points) |
| `modes/target-windows/node.lua` | GPL-3.0-or-later | Target node script: random team-colour window, hit scoring, arm/disarm |
| `modes/target-windows/tests/test_hit_in_window.yaml` | GPL-3.0-or-later | Hit during open window: score awarded |
| `modes/target-windows/tests/test_hit_outside_window.yaml` | GPL-3.0-or-later | Hit outside window: no score |
| `modes/target-windows/tests/test_window_cycle.yaml` | GPL-3.0-or-later | Multiple window cycles: correct team colours, timing |
| `modes/target-windows/i18n/en.yaml` | GPL-3.0-or-later | English strings |
| `modes/target-windows/i18n/pt.yaml` | GPL-3.0-or-later | Portuguese strings |

### Files to modify

| File | Change |
|------|--------|
| `protocol/schema/events.yaml` | Add `satellite.captured`, `satellite.neutralized`, `target.hit` with data schemas |

### Tests to create

| File | What it tests |
|------|---------------|
| `modes/master-and-satellites/tests/test_basic.yaml` | Master capture by red, satellite capture by red, verify multiplier x1.5 applied to scoring tick |
| `modes/master-and-satellites/tests/test_master_change.yaml` | Red captures master, red captures 2 satellites, blue captures master: verify all satellites reset to neutral, multiplier resets to 1 |
| `modes/master-and-satellites/tests/test_multi_satellite.yaml` | Red captures master and 3 satellites sequentially: verify multiplier increases to x2.5 |
| `modes/master-and-satellites/tests/test_satellite_recapture.yaml` | Red captures master and satellite, blue recaptures satellite: verify multiplier drops back to x1.0 |
| `modes/target-windows/tests/test_hit_in_window.yaml` | Window opens for red, hit arrives: verify `target.hit` event with window=true, score added for red |
| `modes/target-windows/tests/test_hit_outside_window.yaml` | No window open, hit arrives: verify `target.hit` event with window=false, no score |
| `modes/target-windows/tests/test_window_cycle.yaml` | Run 3 complete window cycles: verify random team selection, correct timing, window opens and closes |

### Validation commands

**Master and Satellites tests:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest modes/master-and-satellites/tests/ -v"
```

**Target Windows tests:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest modes/target-windows/tests/ -v"
```

**All mode tests still pass (no regressions):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest modes/ -v"
```

---

## Phase C: Sync protocol + chrono registry (depends on Phase 2D)

### Goal

Implement the controller-to-site-server sync protocol (ADR-P4-3):
event batch push with idempotent deduplication, score snapshot merge
by GREATEST, chrono record sync, roster/preset/field pull, offline
buffering with batch replay, and the optional WebSocket live stream.
Implement the chrono registry: replica registration, marshal Ed25519
keypair management, check-in records, spot checks, cross-field sharing
with double opt-in, violation tracking and marshal signature
verification. This phase depends on Phase 2D (the controller REST API
and SQLite store must be available for the sync client). The site
server side can be built and tested independently using a mock
controller.

### Files to create

| File | Licence | Purpose |
|------|---------|---------|
| `server/src/api/sync.py` | AGPL-3.0-or-later | Sync endpoints: `GET /sync/roster`, `GET /sync/presets`, `GET /sync/chrono`, `GET /sync/field`, `POST /sync/events`, `POST /sync/scores`, `POST /sync/chrono`, `POST /sync/game`, `WS /sync/stream` |
| `server/src/api/chrono.py` | AGPL-3.0-or-later | Chrono endpoints: replica CRUD, check-in records, spot checks, violation tracking, cross-field history query |
| `server/src/api/games.py` | AGPL-3.0-or-later | Game history endpoints: list, detail, event log query, score timeline |
| `server/src/services/sync_service.py` | AGPL-3.0-or-later | Event dedup, score merge (GREATEST), batch acknowledgement, offline buffer tracking |
| `server/src/services/chrono_service.py` | AGPL-3.0-or-later | Marshal key generation (Ed25519), signing, verification, cross-field sharing consent, violation detection |
| `controller/src/sync_client.py` | GPL-3.0-or-later | Site server sync client: pull roster/presets/chrono before game, push events/scores/chrono during/after, offline buffer, batch replay, backoff (30s during game, 5min between, double on failure, cap 5min) |
| `server/tests/test_sync.py` | AGPL-3.0-or-later | Sync endpoint tests |
| `server/tests/test_chrono.py` | AGPL-3.0-or-later | Chrono registry tests |
| `server/tests/test_games.py` | AGPL-3.0-or-later | Game history tests |
| `controller/tests/test_sync_client.py` | GPL-3.0-or-later | Sync client tests |

### Files to modify

| File | Change |
|------|--------|
| `server/src/api/__init__.py` | Register sync, chrono, and games routers |
| `server/src/models.py` | Verify all sync-related models are present (game_events unique constraint, game_scores upsert) |

### Tests to create

| File | What it tests |
|------|---------------|
| `server/tests/test_sync.py` | API-key auth (valid key accepted, invalid rejected, missing rejected), event batch push (insert 10 events, verify all persisted), duplicate batch replay (same batch_seq, verify events_duplicate count), score merge (push {red: 100}, push {red: 150}, verify stored value is 150), game lifecycle (create, start, end, verify timestamps), roster pull (register 3 players, pull roster, verify 3 returned), chrono sync (push 2 records, pull for registered players, verify 2 returned), WebSocket auth and event streaming |
| `server/tests/test_chrono.py` | Replica registration (create, read, update), marshal key generation (Ed25519 keypair, public key stored, encrypted private key stored), record creation (marshal signs, server stores, verify signature), spot check vs check-in comparison, violation detection (reading > limit, reading > check-in + tolerance%), cross-field sharing (field A shares, field B queries, consent required at both levels), signature verification across password change (re-encrypt private key, new signature verifiable, old signatures still valid) |
| `server/tests/test_games.py` | Game list (filter by field, status), game detail (scores, events count), event log query (filter by type, time range), score timeline (verify snapshots ordered by time) |
| `controller/tests/test_sync_client.py` | Pull roster (mock server, verify deserialization), push events (mock server, verify batch_seq tracking), offline buffer (mock server unreachable, verify events buffered in SQLite, mock server restored, verify replay), backoff (verify interval doubles on failure, caps at 5 min) |

### Validation commands

**Sync and chrono tests (site server):**

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && python -m pytest tests/test_sync.py tests/test_chrono.py tests/test_games.py -v"
```

**Sync client tests (controller, mock server):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src/controller && pip install -r requirements.txt && \
         python3 -m pytest tests/test_sync_client.py -v"
```

---

## Phase D: ATAK/CoT + geo utilities (depends on Phase 2D)

### Goal

Add `geo.distance()` and `geo.in_zone()` to the core Lua API
(ADR-P4-9) -- Haversine distance and circle/polygon zone checks
implemented in C, registered unconditionally so both `node.lua` and
`field.lua` can use them. Build the ATAK / CoT emitter as a Python
module on the controller (ADR-P4-7): subscribe to game events and
node STATE messages, generate CoT XML, send via UDP multicast on
the field Wi-Fi and optionally via TCP to the site server for remote
ATAK relay. This phase depends on Phase 2D (the controller must be
running to emit CoT). The core geo functions can be built and tested
independently.

### Files to create

| File | Licence | Purpose |
|------|---------|---------|
| `core/include/atalaia/geo.h` | GPL-3.0-or-later | `haversine_m()`, `in_zone_circle()`, `in_zone_polygon()` function declarations |
| `core/src/geo.c` | GPL-3.0-or-later | C implementations of Haversine and ray-casting point-in-polygon |
| `core/tests/test_geo.c` | GPL-3.0-or-later | Geo function tests |
| `controller/src/atak.py` | GPL-3.0-or-later | CoT emitter: `CotEmitter` class, `generate_cot()`, UDP multicast sender, optional TCP sender, CoT type mapping, staleness, UID format |
| `controller/src/atak_config.py` | GPL-3.0-or-later | ATAK configuration: env vars for multicast group, port, intervals, enable/disable |
| `controller/tests/test_atak.py` | GPL-3.0-or-later | CoT emitter tests |
| `controller/tests/test_geo_lua.py` | GPL-3.0-or-later | Lua-level geo API tests via simulator |

### Files to modify

| File | Change |
|------|--------|
| `core/src/script_api.c` | Register `geo` table with `distance` and `in_zone` functions |
| `core/CMakeLists.txt` | Add `geo.c` to source list |
| `core/tests/CMakeLists.txt` | Add `test_geo` executable, link math library |

### Tests to create

| File | What it tests |
|------|---------------|
| `core/tests/test_geo.c` | Haversine: Lisbon-to-Porto ~274 km, same point = 0, antipodal = ~20015 km; in_zone_circle: point at centre (inside), point at edge (inside), point outside; in_zone_polygon: point inside square, point outside, point on edge, concave polygon |
| `controller/tests/test_atak.py` | CoT XML generation (parse XML, verify `event` root, `point` lat/lon, `__group` name, `status` battery), CoT type mapping (uncaptured prop -> `a-n-G-E-X`, team-owned -> `a-f-G-E-X`), UID format (`atalaia-{node_name}-{node_id}`), staleness (`stale = start + 2 * interval`), UDP emission (mock socket, verify `sendto` called with correct multicast address) |
| `controller/tests/test_geo_lua.py` | Lua `geo.distance()` round-trip via simulator (inject two coordinates, verify result matches C implementation), Lua `geo.in_zone()` with circle zone, Lua `geo.in_zone()` with polygon zone |

### Validation commands

**Core geo tests:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**ATAK emitter tests:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src/controller && pip install -r requirements.txt && \
         python3 -m pytest tests/test_atak.py -v"
```

**Lua geo API tests:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest controller/tests/test_geo_lua.py -v"
```

---

## Phase E: Custom scenario DSL and compiler

### Goal

Implement the YAML-based custom scenario DSL (ADR-P4-6): the
manifest schema with all 7 objective block types (capture_and_hold,
enter_code, scan_tags, escort, destroy, defend, survive), the Python
compiler that transforms manifests into `field.lua` scripts, manifest
validation (DAG check, parameter validation, zone geometry), and a
CLI tool for offline compilation. Add the scenario events to
`events.yaml`. The compiler runs on the site server. Escort
objectives (which require GPS) are compiled but cannot be fully
tested until Phase 3; their generated Lua is validated syntactically.

### Files to create

| File | Licence | Purpose |
|------|---------|---------|
| `server/src/services/scenario_compiler.py` | AGPL-3.0-or-later | Manifest parser, DAG validator, per-objective-type Lua templates, dependency wiring, visibility management, zone geometry check, `compile_scenario()` entry point |
| `server/src/services/scenario_validator.py` | AGPL-3.0-or-later | YAML schema validation (unique IDs, valid depends_on refs, DAG cycle check via topological sort, required params per type, time_window logic, radius_m >= 10 warning, non-self-intersecting polygons) |
| `server/src/services/scenario_templates.py` | AGPL-3.0-or-later | Lua code templates for each of the 7 objective types, preamble, state init, dependency wiring, visibility handlers |
| `server/src/api/scenarios.py` | AGPL-3.0-or-later | Scenario CRUD: `POST /scenarios` (validate + compile + store), `GET /scenarios`, `GET /scenarios/{id}`, `PUT /scenarios/{id}`, `DELETE /scenarios/{id}`, `GET /scenarios/{id}/lua` |
| `server/src/cli_scenario.py` | AGPL-3.0-or-later | CLI: `atalaia-scenario compile scenario.yaml [-o output.lua]` |
| `server/tests/test_scenario_compiler.py` | AGPL-3.0-or-later | Compiler tests |
| `server/tests/test_scenario_validator.py` | AGPL-3.0-or-later | Validator tests |
| `server/tests/test_scenario_api.py` | AGPL-3.0-or-later | Scenario API tests |
| `server/tests/test_scenarios/simple_capture.yaml` | AGPL-3.0-or-later | Test scenario: single capture_and_hold objective |
| `server/tests/test_scenarios/multi_objective.yaml` | AGPL-3.0-or-later | Test scenario: 4 objectives with dependencies (intel -> rescue + sabotage, defend_hq) |
| `server/tests/test_scenarios/all_types.yaml` | AGPL-3.0-or-later | Test scenario: one of each objective type |
| `server/tests/test_scenarios/cyclic_deps.yaml` | AGPL-3.0-or-later | Invalid scenario: cyclic dependency (A -> B -> A) |
| `server/tests/test_scenarios/bad_params.yaml` | AGPL-3.0-or-later | Invalid scenario: missing required params |

### Files to modify

| File | Change |
|------|--------|
| `protocol/schema/events.yaml` | Add `scenario.objective.completed`, `scenario.objective.failed`, `scenario.objective.revealed`, `scenario.started` |
| `server/src/api/__init__.py` | Register scenarios router |

### Tests to create

| File | What it tests |
|------|---------------|
| `server/tests/test_scenario_compiler.py` | Compile `simple_capture.yaml`: output is valid Lua (syntax check), contains the objective handler, contains scoring; compile `multi_objective.yaml`: dependency wiring (intel completion activates rescue and sabotage), visibility handlers (hidden objectives become visible on dependency completion); compile `all_types.yaml`: each type generates the correct Lua pattern; compile each type individually and run generated Lua in the simulator: verify objective completion emits `scenario.objective.completed` |
| `server/tests/test_scenario_validator.py` | Valid scenario passes; `cyclic_deps.yaml` rejected with cycle error; `bad_params.yaml` rejected with missing param error; duplicate objective IDs rejected; non-existent depends_on reference rejected; invalid time_window (start > end) rejected; escort with radius_m < 10 produces warning; self-intersecting polygon rejected |
| `server/tests/test_scenario_api.py` | `POST /scenarios` with valid YAML: 201, compiled Lua stored; `POST /scenarios` with invalid YAML: 422 with validation errors; `GET /scenarios/{id}/lua` returns compiled Lua; `PUT /scenarios/{id}` recompiles; `DELETE /scenarios/{id}` removes |

### Validation commands

**Scenario compiler and validator tests:**

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && python -m pytest tests/test_scenario_compiler.py tests/test_scenario_validator.py tests/test_scenario_api.py -v"
```

**CLI compile test:**

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "python -m src.cli_scenario compile tests/test_scenarios/multi_objective.yaml && echo 'CLI compile OK'"
```

**Generated Lua runs in the simulator (multi-objective scenario):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest server/tests/test_scenario_compiler.py::test_multi_objective_simulation -v"
```

---

## Phase F: Advanced modes -- Phase 3 dependencies (VIP/Payload, Hacking Terminal)

### Goal

Implement the two advanced game modes that depend on Phase 3
deliverables: VIP / Payload (`field.lua` + `node.lua`; requires GPS
reporting from the player app) and Hacking Terminal (`node.lua`;
requires the Phase 3 Android shell with Flutter touch UI). Add the
engineer-only satellite capture variant to Master and Satellites
(requires Phase 3 NFC squad identification). Add `vip.extracted` and
`hacking.solved` events to `events.yaml`. Write simulator tests with
injected `gps.fix` and `display.touch` events. Full hardware testing
is deferred to Phase H.

**This phase is blocked until Phase 3 design completes.** The
interfaces below are derived from the spec and marked for re-checking.

### Files to create

| File | Licence | Purpose |
|------|---------|---------|
| `modes/vip-payload/mode.yaml` | GPL-3.0-or-later | Mode manifest: roles (escort_prop, checkpoint), capabilities (gps or player-app GPS), parameters (vip_team, extract_lat, extract_lon, extract_radius_m, checkpoint_points) |
| `modes/vip-payload/node.lua` | GPL-3.0-or-later | Checkpoint node script: Domination-like capture for escort route checkpoints |
| `modes/vip-payload/field.lua` | GPL-3.0-or-later | Controller field script: listen for `gps.fix` from VIP, check extraction zone via `geo.in_zone()`, emit `vip.extracted` on arrival, call `game.win()` |
| `modes/vip-payload/tests/test_extraction.yaml` | GPL-3.0-or-later | VIP enters extraction zone: verify `vip.extracted` emitted, team wins |
| `modes/vip-payload/tests/test_outside_zone.yaml` | GPL-3.0-or-later | VIP moves but stays outside zone: no extraction event |
| `modes/vip-payload/tests/test_checkpoint_scoring.yaml` | GPL-3.0-or-later | VIP team captures checkpoints along route: verify scoring |
| `modes/vip-payload/i18n/en.yaml` | GPL-3.0-or-later | English strings |
| `modes/vip-payload/i18n/pt.yaml` | GPL-3.0-or-later | Portuguese strings |
| `modes/hacking-terminal/mode.yaml` | GPL-3.0-or-later | Mode manifest: roles (terminal), capabilities (display with touch), parameters (puzzle_type, difficulty, lockout_s), min_tier: full, platform: android |
| `modes/hacking-terminal/node.lua` | GPL-3.0-or-later | Terminal node script: puzzle generation, touch input handling, solve/fail/lockout logic, emit `hacking.solved` |
| `modes/hacking-terminal/tests/test_solve.yaml` | GPL-3.0-or-later | Correct input sequence: verify `hacking.solved` emitted |
| `modes/hacking-terminal/tests/test_fail_lockout.yaml` | GPL-3.0-or-later | Incorrect input: verify lockout timer, puzzle regeneration |
| `modes/hacking-terminal/tests/test_puzzle_types.yaml` | GPL-3.0-or-later | Each puzzle type (wires, code, pattern) generates solvable state |
| `modes/hacking-terminal/i18n/en.yaml` | GPL-3.0-or-later | English strings |
| `modes/hacking-terminal/i18n/pt.yaml` | GPL-3.0-or-later | Portuguese strings |

### Files to modify

| File | Change |
|------|--------|
| `protocol/schema/events.yaml` | Add `vip.extracted`, `hacking.solved` with data schemas |
| `modes/master-and-satellites/node.lua` | Add engineer-only capture check: if `params.engineer_only` and `e.squad ~= "engineer"`, ignore input. **Maintainer review recommended: depends on Phase 3 NFC squad identification format.** |
| `modes/master-and-satellites/mode.yaml` | Add `engineer_only` parameter (bool, default false) |

### Tests to create

| File | What it tests |
|------|---------------|
| `modes/vip-payload/tests/test_extraction.yaml` | Inject `gps.fix` at extraction zone coordinates: verify `vip.extracted` event with correct team, verify `game.win()` called |
| `modes/vip-payload/tests/test_outside_zone.yaml` | Inject `gps.fix` outside extraction zone: verify no extraction event |
| `modes/vip-payload/tests/test_checkpoint_scoring.yaml` | VIP team captures 3 checkpoints: verify score increments |
| `modes/hacking-terminal/tests/test_solve.yaml` | Inject `display.touch` sequence matching solution: verify `hacking.solved` event |
| `modes/hacking-terminal/tests/test_fail_lockout.yaml` | Inject wrong `display.touch`: verify phase changes to `locked_out`, verify after `lockout_s` puzzle regenerates |
| `modes/hacking-terminal/tests/test_puzzle_types.yaml` | Generate puzzle for each type, verify solution exists, verify check function works |

### Validation commands

**VIP / Payload tests:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest modes/vip-payload/tests/ -v"
```

**Hacking Terminal tests:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest modes/hacking-terminal/tests/ -v"
```

**All mode tests (regression):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest modes/ -v"
```

---

## Phase G: Remote setup (health dashboard, scheduling, remote GM)

### Goal

Implement the site server's remote management features: device health
dashboard (battery, firmware, RSSI, last seen), game scheduling with
player registration, and the remote GM console relay. The health
dashboard consumes device data pushed via the sync protocol (Phase C).
The remote GM console proxies commands to the controller via the sync
WebSocket. Game scheduling provides a calendar with registration and
roster management.

### Files to create

| File | Licence | Purpose |
|------|---------|---------|
| `server/src/api/devices.py` | AGPL-3.0-or-later | Device health endpoints: list devices, device detail (battery, fw_version, rssi, last_seen), firmware catalog |
| `server/src/api/scheduling.py` | AGPL-3.0-or-later | Game scheduling: CRUD for scheduled games, player registration/unregistration, team assignment, roster query |
| `server/src/api/remote_gm.py` | AGPL-3.0-or-later | Remote GM: proxy WS connection to controller, forward commands (start, pause, override) with GM token validation, relay live events/scores |
| `server/src/services/device_service.py` | AGPL-3.0-or-later | Device health tracking: update from sync data, firmware version comparison, battery trend |
| `server/src/services/scheduling_service.py` | AGPL-3.0-or-later | Scheduling logic: registration limits, team balancing, status transitions (draft -> published -> registering -> in_progress -> completed) |
| `server/tests/test_devices.py` | AGPL-3.0-or-later | Device health tests |
| `server/tests/test_scheduling.py` | AGPL-3.0-or-later | Scheduling tests |
| `server/tests/test_remote_gm.py` | AGPL-3.0-or-later | Remote GM tests |

### Files to modify

| File | Change |
|------|--------|
| `server/src/api/__init__.py` | Register devices, scheduling, and remote_gm routers |
| `server/src/services/sync_service.py` | Update device health data when sync pushes node STATE messages |

### Tests to create

| File | What it tests |
|------|---------------|
| `server/tests/test_devices.py` | Device list (filter by field), device detail (battery, fw_version, rssi), device update via sync (push STATE, verify device record updated), firmware catalog (list available versions) |
| `server/tests/test_scheduling.py` | Create scheduled game, publish (status transition), register player (verify roster count), register beyond max_players (rejected), unregister player, team assignment, pull roster (verify format matches sync protocol) |
| `server/tests/test_remote_gm.py` | WebSocket connection with GM token (accepted), WebSocket without token (rejected), forward start command to mock controller, receive live event from mock controller, command forwarded only if user has GM role |

### Validation commands

**Remote setup tests:**

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && python -m pytest tests/test_devices.py tests/test_scheduling.py tests/test_remote_gm.py -v"
```

**All site server tests (regression):**

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && python -m pytest tests/ -v"
```

---

## Phase H: Integration, weekend milsim gate, documentation

### Goal

Bring all pieces together end-to-end. Update documentation (README,
ARCHITECTURE, deployment guides). Run the staged gate test plan (desk
test, small game, scale test, weekend gate). This phase depends on
all preceding phases and on Phase 2F (hardware integration) and
Phase 3 (player app, Android shell, GPS). The gate cannot be
completed without real hardware and real players.

### Files to create

| File | Licence | Purpose |
|------|---------|---------|
| `docs/phase-4-site-server/FIELD_TEST.md` | CC-BY-SA-4.0 | Weekend milsim gate test runbook: equipment checklist, staging procedures, per-stage pass criteria, post-test analysis |
| `server/docs/DEPLOY.md` | CC-BY-SA-4.0 | Site server deployment guide: docker-compose setup, Caddy/nginx TLS, DNS, first admin user, backup cron, restore |
| `server/docs/API.md` | CC-BY-SA-4.0 | Site server REST API reference (generated from OpenAPI) |
| `docs/phase-4-site-server/ARCHITECTURE.md` | CC-BY-SA-4.0 | Phase 4 architecture overview: component diagram, data flow, sync model, security model |

### Files to modify

| File | Change |
|------|--------|
| `server/README.md` | Final documentation: architecture summary, setup quickstart, API reference link, deployment link |
| `README.md` (project root) | Update project status: Phase 4 deliverables, site server, advanced modes, ATAK, custom scenarios |
| `docs/phase-4-site-server/STATUS.md` | Mark Planning complete; mark implementation paused |

### Validation commands

**Full site server test suite:**

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && python -m pytest tests/ -v --tb=short"
```

**Full mode test suite:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest modes/ -v"
```

**Full core test suite (including geo):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**SPDX header check (all new files):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && grep -rL 'SPDX-License-Identifier' server/src/ server/tests/ modes/master-and-satellites/ modes/target-windows/ modes/vip-payload/ modes/hacking-terminal/ controller/src/atak.py controller/src/sync_client.py core/src/geo.c core/include/atalaia/geo.h && echo 'FAIL: missing SPDX headers' || echo 'All SPDX headers present'"
```

---

## Assumptions about earlier phases

| # | Assumption | Source | Plan phases that depend on it | What to do if wrong |
|---|-----------|--------|-------------------------------|---------------------|
| A1 | Phase 2D delivers a working Python controller with FastAPI REST API, SQLite store, MQTT publisher, and WebSocket stream | RESEARCH.md section 15; ADR-P2-5 | C (sync client), D (ATAK emitter), G (remote GM relay), H (integration) | **Critical.** If the controller API differs, adapt the sync client and ATAK module. The site server side (Phase A, B, E) is independent. |
| A2 | Phase 2D delivers the GM console as a Preact+HTM PWA served by FastAPI | RESEARCH.md section 15 | G (remote GM console), H (integration) | **Moderate.** The site server serves the same console files. If the framework changes, the static file mount adapts trivially. |
| A3 | Phase 2C delivers `field.*` API and `state.field{}` in the core (confirmed complete per STATUS.md) | Phase 2 STATUS.md | B (Master and Satellites), E (scenario compiler generates field.lua), F (VIP, Hacking Terminal) | **Low.** Already verified complete. |
| A4 | Phase 3 delivers the Android shell (Flutter + dart:ffi) with kiosk mode | Spec section 5, 12. **Derived from the spec, not from Phase 3 design -- re-check when Phase 3 design completes.** | F (Hacking Terminal mode) | **High.** Hacking Terminal cannot function without it. If the Android shell differs from the spec, adapt the `display.touch` event handling in `node.lua`. The mode's logic (puzzle generation, solve/fail) is pure Lua and unaffected. |
| A5 | Phase 3 delivers the player app with role-based views on Android and iOS | Spec section 12. **Derived from the spec, not from Phase 3 design -- re-check when Phase 3 design completes.** | C (chrono check-in flow consumes player app records), G (scheduling shows in player app), H (weekend gate needs 20+ players on the app) | **High.** Without the player app, chrono check-in must use the GM console or a separate marshal tool. The site server API is the same either way. |
| A6 | Phase 3 delivers GPS reporting from the player app to the controller as `gps.fix` events | Spec section 12. **Derived from the spec, not from Phase 3 design -- re-check when Phase 3 design completes.** | D (ATAK CoT for player positions), F (VIP / Payload mode) | **High.** VIP mode cannot function without GPS. If the event format changes from `gps.fix`, adapt `field.lua` and the ATAK emitter. The `geo.*` functions are unaffected (they take raw lat/lon). |
| A7 | Phase 3 delivers NFC squad identification (team + squad from NFC tags) | Spec section 12. **Derived from the spec, not from Phase 3 design -- re-check when Phase 3 design completes.** | F (engineer-only satellite capture in Master and Satellites) | **Moderate.** Without squad ID, the `engineer_only` parameter is non-functional. The mode works without it (any team member can capture satellites). |
| A8 | Phase 3 delivers the chrono check-in flow in the player app (marshal scans tag, enters readings, app signs and uploads) | Spec section 12. **Derived from the spec, not from Phase 3 design -- re-check when Phase 3 design completes.** | C (chrono registry receives records from the check-in flow), H (weekend gate chrono check-in) | **Moderate.** Without the player app flow, chrono records must be entered via the site server web UI or API. The site server chrono API (Phase C) is independent of the input method. |
| A9 | Phase 3 delivers BLE join for Android devices | Spec section 10 | H (weekend gate, players joining via phone) | **Low.** Players can join via QR over Wi-Fi. The site server does not depend on BLE join. |
| A10 | Phase 3 delivers Hold-All Domination, Last Stand, Kill Confirmed and other multi-node modes that validate the `field.lua` API under real game conditions | Spec section 15 | B (Master and Satellites uses the same field.lua API), E (scenario compiler generates field.lua) | **Moderate.** If Phase 3 modes reveal field API issues, Phase 4 modes and the scenario compiler must adapt. The API is already complete per Phase 2C. |
| A11 | Phase 1 delivers the target addon hardware (piezo sensor + MCU + LED ring on the addon bus) | Spec section 6 | B (Target Windows mode logic), H (Target Windows hardware testing) | **High for hardware testing.** The `hit` capability type is defined in the spec. Target Windows mode logic can be tested in the simulator with virtual `hit` events. Hardware calibration (piezo threshold, debounce) is deferred to Phase H. |
| A12 | The controller's WiFi network supports UDP multicast for ATAK CoT | Spec section 10 | D (ATAK CoT multicast) | **Low.** Standard on most WiFi APs. If multicast is blocked, fall back to TCP unicast. The emitter supports both transports. |
| A13 | The site server can reach the controller via HTTPS through the 4G bridge | Spec section 11 | G (remote GM console), H (live sync during weekend gate) | **Moderate.** Without 4G, the site server works in batch mode (post-game upload). Remote GM console is unavailable. Sync client handles offline buffering transparently. |

---

## Acceptance criteria

### AC-1: Site server starts and passes health check

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.yml up -d
sleep 10
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.yml exec atalaia-server \
  python -c "import httpx; r = httpx.get('http://localhost:8000/api/v1/health'); print(r.json()); assert r.status_code == 200"
docker compose -f server/docker-compose.yml down
```

**Expected:** `{"status": "healthy", "database": "connected", ...}` with exit 0.

### AC-2: Alembic migration round-trip succeeds

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && alembic downgrade base && alembic upgrade head && echo OK"
```

**Expected:** exit 0, "OK" printed.

### AC-3: Auth flow (registration, login, TOTP, refresh)

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && python -m pytest tests/test_auth.py -v"
```

**Expected:** exit 0. Tests cover registration, login, TOTP enrollment
and verification, refresh token rotation, replay detection, rate
limiting, and breached password rejection.

### AC-4: GDPR endpoints work correctly

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && python -m pytest tests/test_gdpr.py -v"
```

**Expected:** exit 0. Export ZIP contains profile.json, games.json,
chrono_records.json, events.json, consents.json, README.txt. Erasure
anonymises the user but preserves marshal signatures on chrono records.

### AC-5: Sync protocol is idempotent and conflict-free

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && python -m pytest tests/test_sync.py -v"
```

**Expected:** exit 0. Duplicate event batches report `events_duplicate`
count. Score merge uses GREATEST. Event unique constraint
`(game_id, node_id, seq)` prevents duplicates.

### AC-6: Chrono records are signed and verifiable

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && python -m pytest tests/test_chrono.py -v"
```

**Expected:** exit 0. Marshal Ed25519 signature is created during
record creation, verifiable with the stored public key, and survives
password changes (key is independent of password).

### AC-7: Master and Satellites mode passes simulator tests

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest modes/master-and-satellites/tests/ -v"
```

**Expected:** exit 0. Multiplier tracks correctly, master hand-change
resets satellites, scoring ticks apply multiplier.

### AC-8: Target Windows mode passes simulator tests

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest modes/target-windows/tests/ -v"
```

**Expected:** exit 0. Hit in window scores, hit outside window does
not, window cycles correctly.

### AC-9: Geo functions are correct

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**Expected:** exit 0. `test_geo.c` tests pass: Haversine Lisbon-Porto
within 1 km of 274 km, circle and polygon zone checks are correct.

### AC-10: ATAK CoT XML is valid and correctly typed

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src/controller && pip install -r requirements.txt && \
         python3 -m pytest tests/test_atak.py -v"
```

**Expected:** exit 0. CoT XML parses as valid XML, `event` root
element has correct `type` and `uid`, `point` has lat/lon, `__group`
has team name, staleness is set correctly.

### AC-11: Scenario compiler produces valid, runnable Lua

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && python -m pytest tests/test_scenario_compiler.py -v"
```

**Expected:** exit 0. Each of the 7 objective types compiles to valid
Lua. The multi-objective scenario runs in the simulator: dependency
chains activate correctly, objectives complete and fail correctly,
visibility events fire.

### AC-12: Scenario validator rejects invalid manifests

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && python -m pytest tests/test_scenario_validator.py -v"
```

**Expected:** exit 0. Cyclic dependencies, missing parameters,
duplicate IDs, non-existent references, invalid time windows and
self-intersecting polygons are all rejected with descriptive errors.

### AC-13: VIP / Payload mode passes simulator tests

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest modes/vip-payload/tests/ -v"
```

**Expected:** exit 0. VIP extraction zone entry triggers
`vip.extracted`. Outside-zone GPS fixes do not trigger extraction.

### AC-14: Hacking Terminal mode passes simulator tests

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest modes/hacking-terminal/tests/ -v"
```

**Expected:** exit 0. Correct input triggers `hacking.solved`. Wrong
input triggers lockout and puzzle regeneration.

### AC-15: Remote GM console relays commands and events

```sh
MSYS_NO_PATHCONV=1 docker compose -f server/docker-compose.test.yml \
  run --rm test \
  sh -c "alembic upgrade head && python -m pytest tests/test_remote_gm.py -v"
```

**Expected:** exit 0. GM-authenticated WebSocket connects, commands
forward to mock controller, events relay back.

### AC-16: Weekend milsim gate (hardware required)

Execute the Weekend Milsim Gate Test Plan below. All functional
requirements pass, all quantitative criteria met. Gate decision made.

---

## Weekend milsim gate test plan

### What "a weekend milsim runs on the platform end to end" means

The gate is met when all functional requirements and quantitative
criteria below are demonstrated in a single weekend event (two days,
8-16 hours of active play per day).

### Equipment list

| Item | Quantity | Purpose |
|------|----------|---------|
| Heltec WiFi LoRa 32 V4.3 (ESP32-S3 + SX1262) | 10-20 | Field Boxes and Satellites |
| Heltec WiFi LoRa 32 V4.3 (modem variant) | 1 | USB radio modem for the controller |
| Raspberry Pi 4 or 5 | 1 | Field controller |
| Dedicated repeater nodes (Heltec V4.3) | 1-3 | Range extension for large outdoor areas |
| Android phone with 4G SIM | 1 | Internet bridge (controller to site server) |
| VPS or mini PC | 1 | Site server (PostgreSQL + FastAPI) |
| Player phones (Android and iOS) | 20+ | Player app |
| Android phones with ATAK installed | 1-2 | Marshal/GM ATAK devices |
| Target addon (piezo + MCU + LED ring) | 1-2 | Target Windows mode hardware |
| NFC tags (NTAG215/216) | 50+ | Player/replica/squad identification |
| Commercial chronograph | 1 | Chrono check-in |
| Arcade buttons per box | 2-4 | Team input |
| 18650 battery packs per box | 1 | Full-day power |
| Power banks for controller and bridge | 2 | Full-day power |
| USB-A to USB-C cable | 1 | Pi to modem board |
| Laptop | 1 | Serial monitoring and data collection |

### Staging approach

#### Stage 1: Desk test

**Setup:** 5 boxes + controller + site server on a desk. No players.

**Procedure:**
1. Start the site server (docker-compose).
2. Start the controller with the USB modem.
3. Join 5 boxes via NFC.
4. Create a scheduled game on the site server. Pull roster.
5. Start a Domination game. Press buttons to generate 20+ captures.
6. Verify sync: events appear on the site server within 30 seconds.
7. Start a Master and Satellites game. Verify multiplier logic.
8. Open the remote GM console via the site server. Verify live scores.
9. Verify chrono: create a replica, create a check-in record with
   marshal signature, verify signature on the site server.
10. Compile a custom scenario (3 objectives) and run it.

**Pass criteria:**
- All events sync to site server.
- Remote GM console shows live scores and events.
- Chrono record is signed and verifiable.
- Custom scenario objectives complete correctly.
- Zero errors in controller and site server logs.

#### Stage 2: Small game test

**Setup:** 5 boxes, 5 players with the player app, chrono check-in.
Half-day (4 hours).

**Procedure:**
1. Register 5 players on the site server.
2. Schedule a game. Players register via the app.
3. Chrono check-in: each player registers their replica, marshal
   records readings, verify pass/fail.
4. Run one Domination game (30 min).
5. Run one Master and Satellites game (30 min).
6. Verify player app shows role-appropriate views.
7. Run a spot check during game 2: compare with check-in reading.
8. End games. Verify site server has full history.

**Pass criteria:**
- All 5 players join via the app.
- Chrono check-in records are signed and stored.
- Spot check comparison works.
- Event sync latency < 5 s (95th percentile).
- Zero lost captures.

#### Stage 3: Scale test

**Setup:** 10-15 boxes, 10+ players, multiple modes, ATAK, custom
scenario. Full day (8 hours).

**Procedure:**
1. Run at least 4 different modes: Domination, Bomb, Master and
   Satellites, and a custom scenario with 3+ objectives.
2. Enable ATAK CoT. Verify props appear on ATAK maps on marshal
   phones within 30 seconds of game start.
3. Test controller failover: kill the Pi mid-game, verify backup
   election completes within 40 seconds, verify zero lost events.
4. Test offline sync: disconnect the 4G bridge for 10 minutes,
   reconnect, verify all events sync.
5. Monitor battery levels on all boxes. Record start and end
   percentages.
6. Test the remote GM console throughout the day.

**Pass criteria:**
- All modes run without errors.
- ATAK shows > 80% of GPS-equipped props within 30 s.
- Controller failover: zero lost captures.
- Offline sync: all events sync after reconnect.
- Battery: zero props die before end of the scheduled game.
- Zero lost captures across all games.

#### Stage 4: Weekend gate

**Setup:** Full setup as specified in the equipment list. Two days,
20+ players.

**Procedure:**
1. Day 1 (8-16 hours):
   - Chrono check-in for all players.
   - Run at least 4 games: Domination, Bomb, Master and Satellites,
     custom scenario.
   - Use ATAK throughout.
   - Remote GM observes from off-site.
   - Planned controller failover test.
   - At least one Target Windows game (if addon hardware available).
2. Day 2 (8-16 hours):
   - Repeat chrono check-in (or verify Day 1 records persist).
   - Run at least 3 more games, including a custom scenario with
     4+ objectives and dependency chains.
   - VIP / Payload game (if Phase 3 GPS is available).
   - Hacking Terminal game (if Phase 3 Android shell is available).
   - Final data collection: full event logs, chrono records, player
     stats.

**Pass criteria (quantitative):**
- Zero lost captures across all games.
- Event sync latency: 95th percentile < 5 s from event generation
  to site server persistence.
- Chrono registry: 100% of check-in records are signed and stored.
- Player app: > 90% of registered players successfully join at
  least one game via the app.
- ATAK: > 80% of GPS-equipped props visible on ATAK within 30 s
  of game start.
- Battery: zero props die before end of the scheduled game.
- Site server: complete game history, scores, and chrono records
  for the entire weekend.
- Custom scenario: at least one game uses a custom scenario with
  3+ objectives and all objectives complete or fail correctly.

### Post-test analysis procedure

After each test stage:

1. **Export data:**
   - Controller event log: `GET /api/v1/games/{id}/log > game_log.json`
   - Site server event log: `GET /api/v1/games/{id}/events`
   - Each box's serial log (captured during the test).
   - Site server chrono records: `GET /api/v1/chrono/records?field_id=...`

2. **Cross-reference events:**
   For each `zone.captured` in the serial logs, verify it exists in
   the controller's log and the site server's log with matching
   `(node_id, seq)`.

3. **Compute metrics:**
   - Delivery latency distribution (median, P95, P99) from the
     controller log.
   - Sync latency distribution (median, P95, P99) from the site
     server `received_at` vs `game_time_ms`.
   - Time sync accuracy: max |node_game_time - controller_game_time|.
   - Duty-cycle usage per node from radio HAL logs.
   - Battery drain per box (start vs end percentage).

4. **Verify chrono integrity:**
   For each chrono record on the site server, verify the marshal
   signature using the stored public key.

5. **Check scenario completion:**
   For each custom scenario game, verify all objectives reached
   their expected terminal state (completed or failed).

6. **Root-cause any failures:**
   If any captures are lost or any metric misses its target, identify
   root cause from serial logs, controller logs, site server logs and
   radio HAL counters.

### Gate decision

The Phase 4 gate is met when the Stage 4 weekend test passes all
quantitative criteria. If VIP / Payload or Hacking Terminal cannot
be tested because Phase 3 is incomplete, the gate can pass with
those modes excluded, provided they have passed simulator tests
(AC-13, AC-14) and the remaining criteria are all met. The missing
modes must be field-tested as a follow-up within 30 days of Phase 3
completion.

---

## Phase dependency graph

```
Phase A ─────────────────────────────────────> Phase H
  │                                              ^
  ├──> Phase B ──────────────────────────────────┤
  │      (no Phase 2D/3 deps)                    │
  │                                              │
  ├──> Phase E ──────────────────────────────────┤
  │      (no Phase 2D/3 deps for compiler;       │
  │       escort objectives need Phase 3 GPS     │
  │       for full testing)                      │
  │                                              │
  │   [Phase 2D lands]                           │
  │      │                                       │
  ├──> Phase C ──────────────────────────────────┤
  │      (sync + chrono; depends on Phase 2D)    │
  │      │                                       │
  ├──> Phase D ──────────────────────────────────┤
  │      (ATAK/CoT; depends on Phase 2D          │
  │       for controller integration;            │
  │       geo functions independent)             │
  │                                              │
  │   [Phase 3 lands]                            │
  │      │                                       │
  ├──> Phase F ──────────────────────────────────┤
  │      (VIP, Hacking Terminal;                 │
  │       depends on Phase 3)                    │
  │                                              │
  │   [Phase C lands]                            │
  │      │                                       │
  └──> Phase G ──────────────────────────────────┘
         (remote setup; depends on Phase C
          for device health data)
```

**Parallelism:**

- Phases A, B, and E can run in parallel from the start (no
  inter-dependencies, no Phase 2D/3 dependency).
- Phase D's geo functions (core C code) can start immediately;
  the ATAK emitter (controller Python) waits for Phase 2D.
- Phases C and D can run in parallel once Phase 2D lands.
- Phase F is blocked until Phase 3 lands.
- Phase G is blocked until Phase C lands (sync data feeds devices).
- Phase H is the final integration and depends on all other phases.

---

## Summary of new files by directory

```
server/
    src/
        __init__.py
        main.py
        config.py
        models.py
        schemas.py
        database.py
        auth.py
        cli.py
        cli_scenario.py
        data/
            breached_passwords.txt
        api/
            __init__.py
            accounts.py
            fields.py
            roles.py
            gdpr.py
            health.py
            sync.py
            chrono.py
            games.py
            scenarios.py
            devices.py
            scheduling.py
            remote_gm.py
        services/
            __init__.py
            sync_service.py
            chrono_service.py
            gdpr_service.py
            tenant_service.py
            device_service.py
            scheduling_service.py
            scenario_compiler.py
            scenario_validator.py
            scenario_templates.py
        middleware/
            __init__.py
            auth_middleware.py
            rate_limit.py
            security_headers.py
    migrations/
        alembic.ini
        env.py
        versions/
            0001_initial_schema.py
    tests/
        __init__.py
        conftest.py
        test_auth.py
        test_roles.py
        test_gdpr.py
        test_models.py
        test_health.py
        test_tenant.py
        test_migration.py
        test_sync.py
        test_chrono.py
        test_games.py
        test_scenario_compiler.py
        test_scenario_validator.py
        test_scenario_api.py
        test_devices.py
        test_scheduling.py
        test_remote_gm.py
        test_scenarios/
            simple_capture.yaml
            multi_objective.yaml
            all_types.yaml
            cyclic_deps.yaml
            bad_params.yaml
    requirements.txt
    pyproject.toml
    Dockerfile
    docker-compose.yml
    docker-compose.test.yml
    setup.sh
    backup.sh
    docs/
        DEPLOY.md
        API.md

controller/src/
    atak.py
    atak_config.py
    sync_client.py

controller/tests/
    test_atak.py
    test_geo_lua.py
    test_sync_client.py

core/
    include/atalaia/
        geo.h
    src/
        geo.c
    tests/
        test_geo.c

modes/
    master-and-satellites/
        mode.yaml
        node.lua
        field.lua
        i18n/
            en.yaml
            pt.yaml
        tests/
            test_basic.yaml
            test_master_change.yaml
            test_multi_satellite.yaml
            test_satellite_recapture.yaml
    target-windows/
        mode.yaml
        node.lua
        i18n/
            en.yaml
            pt.yaml
        tests/
            test_hit_in_window.yaml
            test_hit_outside_window.yaml
            test_window_cycle.yaml
    vip-payload/
        mode.yaml
        node.lua
        field.lua
        i18n/
            en.yaml
            pt.yaml
        tests/
            test_extraction.yaml
            test_outside_zone.yaml
            test_checkpoint_scoring.yaml
    hacking-terminal/
        mode.yaml
        node.lua
        i18n/
            en.yaml
            pt.yaml
        tests/
            test_solve.yaml
            test_fail_lockout.yaml
            test_puzzle_types.yaml

docs/
    phase-4-site-server/
        PLAN.md             (this file)
        FIELD_TEST.md
        ARCHITECTURE.md
    templates/
        privacy-notice-pt.md
        privacy-notice-en.md
        dpa-template.md
```

Total: ~100 new files across server, controller, core, modes and
docs. Modified files: ~10 (events.yaml, server README, project
README, STATUS.md, core CMakeLists, script_api.c, master-and-
satellites node.lua and mode.yaml, server api __init__.py).
