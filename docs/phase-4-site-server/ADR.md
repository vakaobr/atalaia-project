<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 4 -- Site Server and Advanced Play: Architecture Decisions

Ten decisions settle the structure of the site server, its database,
authentication, sync protocol, multi-tenant isolation, chrono record
integrity, custom scenarios, ATAK integration, GDPR compliance, geo
utilities and deployment before implementation begins. Each one answers
a question the research phase identified and creates a constraint that
the planning phase must respect.

Two more, ADR-P4-11 (game scheduling, publication and registration)
and ADR-P4-12 (open feeds, registration import and platform adapters),
were added on 2026-10-19 at the maintainer's request; both are
proposed, with their open questions in `docs/review/decisions-to-review.md`
(F13-F23). ADR-P4-13 (the hub-level OIDC callback relay for hosted mode) was added on 2026-10-28 as a
design only: nothing is built.

---

## Refresh 2026-10-19 (after phase 3 software)

Every ADR below was re-checked against the code phase 2 and phase 3
built (the controller in `controller/atalaia_controller/`, the app, the
modes, `protocol/`). Where the code and an ADR disagree, the code is the
fact and the ADR gets a dated **Amendment 2026-10-19** at its end; the
original text stays, with a short "superseded" note where it is now
wrong, so the history can be read. The amendments are proposals:
decisions P4R1-P4R26 in `docs/review/decisions-to-review.md`, all open.

| ADR | Re-check 2026-10-19 | Amendment |
|-----|---------------------|-----------|
| P4-1 Database schema | Partly wrong: chrono tables, game identity, scores, player tokens | Yes: chrono as signed readings, `(field, game_id, game_seed)`, per-node scores, `sniper`, per-field player ids (P4R10, P4R11, P4R15) |
| P4-2 Authentication | Holds; site-server accounts are independent of the controller's tokens | Note only |
| P4-3 Sync | Wrong on direction and auth, scores and batches | Yes: the controller opens every connection, no controller tokens on the site server, SHA-256 API keys, the controller's event ids as the cursor, per-node score counters (P4R10-P4R13) |
| P4-4 Multi-tenant | Holds | Note: built last (plan phase 21) |
| P4-5 Chrono signing | Ed25519 holds; key handling and record shape differ | Yes: keys made on the marshal's phone, public keys only on the site server, records verbatim (P4R14, P4R15) |
| P4-6 Scenario DSL | The runtime cannot work on boxes that run built-in scripts only | Yes: `kind: scenario` and `org.atalaia.objectives`, names, ids, Lua as the core takes it (P4R7, P4R8, P4R9, P4R24) |
| P4-7 ATAK / CoT | `gps.fix` does not exist; props have no coordinates; multicast cannot filter | Yes: props and zones only on multicast, a georeferenced field image, staff endpoints for players (P4R18) |
| P4-8 Personal data | Holds; positions and check-in data as phase 3 built them | Yes: positions never on the site server, retention aligned (P4R25) |
| P4-9 Geo utilities | Holds; its `gps.fix` example does not | Yes: `position.fix` (controller-only) and `gps.fix` on Android props (P4R6) |
| P4-10 Deployment | Image and package names | Yes: `python:3.12-slim`, hash-pinned dependencies, a build stage for the core, package `atalaia_server` (P4R9, P4R16) |
| P4-11 Scheduling and registration | Holds against phase 3's check-in | Small: expected check-ins and the ticket on the built `POST /api/v1/checkin` |
| P4-12 Feeds and adapters | Holds | None |

Facts the amendments rely on (all built, 2026-10-19):

- **Controller API and auth:** routes in `controller/atalaia_controller/api.py`;
  `Authorization: Bearer` with the GM token (writes), the read token
  (reads, the scoreboard) or a player token (`require_player`, some
  read routes); `?token=` only on `WS /api/v1/stream`; tokens are
  `secrets.token_urlsafe(24)` kept in the `settings` table or set in
  `[api]`; branding and the check-in poster's endpoints need none.
- **Player tokens:** `apt1.<payload>.<mac>`, HMAC-SHA256 with the
  controller's own per-game token key (`token_keys`, decision B8), not
  the game key; fields `exp, game_id, player_id, role, squad, team`;
  role, team and squad re-checked against the check-in on every request.
- **Players:** per-field ids `p-` + 12 base32 characters with a
  32-byte secret on the phone (the controller keeps its SHA-256); check-ins
  per game; declarations per game (`aeg, gbb, hpa, bolt_action, dmr,
  sniper, pistol, shotgun`; classes from the limit template).
- **Chrono:** one record per reading, signed on the marshal's phone
  with Ed25519 over canonical JSON (`protocol/chrono-record.md`,
  `protocol/vectors/chrono_record.json`), uploaded in series to
  `POST /api/v1/chrono/readings`, verified with `chrono.verify`, the
  record kept as received (`chrono_readings.record_json`); marshal
  public keys registered from the phone (`marshal_keys`).
- **Store:** SQLite schema 4; events unique on
  `(game_id, node_id, seq, game_time, type)`, INSERT OR IGNORE;
  `games.id` is the 16-bit radio game id; `game_seed` is random per game
  and travels in the join; scores per team and node, GM adjustments as
  `score.delta` events from the controller.
- **Modes:** `kind` `mode`, `modifier` or `role`, composed with `+`;
  translations in `mode.yaml` `i18n.pt`; mode commands (CMD opcode 8);
  boxes run built-in presets only and refuse a join for a mode they do
  not have.
- **Event ids:** 1-41 and 50-51 taken; 42-49 free and planned for
  phase 4; data keys 1-33 taken (P4R1).
- **Positions:** `POST /api/v1/positions`, kept on the controller for
  the live game, filtered by role, never on the radio or MQTT.
- **Branding:** per controller (`branding.py`, `images.py`), public
  reads with ETags.

---

### ADR-P4-1: Site server database schema

**Status:** Accepted

**Context:** The site server persists accounts, games, events, chrono
records, scenarios, devices and field configuration across games. The
research phase selected PostgreSQL 16+ with SQLAlchemy 2.0 async +
asyncpg (RESEARCH.md section 4). This ADR defines the concrete tables,
indexes, constraints and migration strategy.

**Decision:**

**ORM and migrations:** SQLAlchemy 2.0 with the async extension
(`sqlalchemy.ext.asyncio`) and asyncpg as the driver. Alembic manages
schema migrations. All migrations must be reversible (provide both
`upgrade()` and `downgrade()`) for rollback safety.

**Naming conventions:** snake_case for tables and columns. All tables
carry `created_at` and `updated_at` timestamps (UTC, `TIMESTAMP WITH
TIME ZONE`). UUIDs use `uuid7` (time-ordered) for primary keys on
user-facing entities; integer sequences for internal-only tables
(events, scores).

**Schema families and table definitions:**

#### Accounts

```sql
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(64) NOT NULL UNIQUE,
    email           VARCHAR(320) UNIQUE,          -- optional; can register with username only
    password_hash   VARCHAR(256) NOT NULL,         -- argon2id (ADR-P4-2)
    totp_secret_enc BYTEA,                         -- encrypted TOTP seed, NULL if not enrolled
    totp_enabled    BOOLEAN NOT NULL DEFAULT FALSE,
    gdpr_consent_at TIMESTAMPTZ,
    data_retention_days INTEGER,                   -- NULL = use field default
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE roles (
    id   SMALLINT PRIMARY KEY,
    name VARCHAR(32) NOT NULL UNIQUE
);
-- Seed: 1=player, 2=squad_leader, 3=vip, 4=marshal, 5=gm, 6=spectator, 7=admin

CREATE TABLE user_field_roles (
    id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    field_id UUID NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    role_id  SMALLINT NOT NULL REFERENCES roles(id),
    granted_by UUID REFERENCES users(id),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, field_id, role_id)
);

CREATE TABLE user_game_roles (
    id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    game_id  UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    role_id  SMALLINT NOT NULL REFERENCES roles(id),
    squad_id UUID REFERENCES squads(id),
    UNIQUE(user_id, game_id, role_id)
);

CREATE TABLE sessions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    refresh_token  VARCHAR(512) NOT NULL UNIQUE,
    user_agent     VARCHAR(512),
    ip_address     INET,
    expires_at     TIMESTAMPTZ NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at     TIMESTAMPTZ
);
CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_expires ON sessions(expires_at) WHERE revoked_at IS NULL;
```

#### Fields

```sql
CREATE TABLE fields (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              VARCHAR(128) NOT NULL,
    slug              VARCHAR(128) NOT NULL UNIQUE,
    field_type        VARCHAR(32) NOT NULL DEFAULT 'outdoor',  -- outdoor, cqb, indoor
    timezone          VARCHAR(64) NOT NULL DEFAULT 'Europe/Lisbon',
    default_retention_days INTEGER NOT NULL DEFAULT 365,
    chrono_sharing_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    public_scoreboard BOOLEAN NOT NULL DEFAULT FALSE,
    api_key_hash      VARCHAR(256),                -- hashed controller API key (ADR-P4-3)
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE field_joule_limits (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    field_id       UUID NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    replica_class  VARCHAR(32) NOT NULL,  -- aeg, gbb, hpa, bolt_action, dmr, pistol, shotgun
    max_energy_j   REAL NOT NULL,
    med_m          REAL,                  -- minimum engagement distance, metres
    UNIQUE(field_id, replica_class)
);
```

#### Devices

```sql
CREATE TABLE devices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    field_id        UUID NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    node_name       VARCHAR(64) NOT NULL,
    platform        SMALLINT NOT NULL,     -- 0=esp32, 1=esp32s3, 2=linux, 3=android
    fw_version      VARCHAR(32),
    core_version    VARCHAR(32),
    last_seen_at    TIMESTAMPTZ,
    battery_pct     SMALLINT,
    rssi            SMALLINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_devices_field ON devices(field_id);
```

#### Games

```sql
CREATE TABLE games (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    field_id        UUID NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    title           VARCHAR(256),
    mode_id         VARCHAR(128) NOT NULL,
    preset_id       UUID REFERENCES presets(id),
    scenario_id     UUID REFERENCES scenarios(id),
    teams           JSONB NOT NULL DEFAULT '[]',
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    duration_s      INTEGER,
    final_scores    JSONB,                 -- {team_name: total, ...}
    status          VARCHAR(16) NOT NULL DEFAULT 'created',
                    -- created, scheduled, in_progress, paused, completed, cancelled
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_games_field ON games(field_id);
CREATE INDEX idx_games_status ON games(field_id, status);

CREATE TABLE game_events (
    id           BIGSERIAL PRIMARY KEY,
    game_id      UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    node_id      INTEGER NOT NULL,
    seq          INTEGER NOT NULL,
    game_time_ms INTEGER NOT NULL,
    event_type   VARCHAR(64) NOT NULL,
    team         SMALLINT,
    squad        SMALLINT,
    priority     SMALLINT NOT NULL DEFAULT 1,
    data         JSONB,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(game_id, node_id, seq, game_time_ms, event_type)
);
CREATE INDEX idx_game_events_time ON game_events(game_id, game_time_ms);
CREATE INDEX idx_game_events_type ON game_events(game_id, event_type);

CREATE TABLE game_scores (
    id       BIGSERIAL PRIMARY KEY,
    game_id  UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    team     SMALLINT NOT NULL,
    counter  VARCHAR(64) NOT NULL DEFAULT 'total',
    value    INTEGER NOT NULL DEFAULT 0,
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(game_id, team, counter)
);
CREATE INDEX idx_game_scores_game ON game_scores(game_id);

CREATE TABLE presets (
    id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    field_id  UUID NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    mode_id   VARCHAR(128) NOT NULL,
    label     VARCHAR(128) NOT NULL,
    params    JSONB NOT NULL DEFAULT '{}',
    version   INTEGER NOT NULL DEFAULT 1,
    is_shared BOOLEAN NOT NULL DEFAULT FALSE,  -- shared via site server
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_presets_field ON presets(field_id);
```

#### Teams and squads

```sql
CREATE TABLE squads (
    id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    field_id  UUID NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    team_name VARCHAR(64) NOT NULL,
    name      VARCHAR(64) NOT NULL,
    max_size  INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### Chrono

```sql
CREATE TABLE replicas (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id    UUID REFERENCES users(id) ON DELETE SET NULL,
    tag_uid     VARCHAR(64),               -- NFC sticker UID
    replica_type VARCHAR(32) NOT NULL,      -- aeg, gbb, hpa, bolt_action, dmr, pistol, shotgun
    brand       VARCHAR(128),
    model       VARCHAR(128),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_replicas_owner ON replicas(owner_id);
CREATE INDEX idx_replicas_tag ON replicas(tag_uid);

CREATE TABLE chrono_records (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    replica_id          UUID NOT NULL REFERENCES replicas(id) ON DELETE CASCADE,
    field_id            UUID NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    game_id             UUID REFERENCES games(id),   -- NULL for pre-game check-in
    marshal_id          UUID NOT NULL REFERENCES users(id),
    chronograph_id      VARCHAR(64),
    readings            JSONB NOT NULL,
                        -- [{ velocity_mps, bb_weight_g, energy_j }, ...]
    highest_energy_j    REAL NOT NULL,
    limit_j             REAL NOT NULL,
    tolerance_pct       REAL NOT NULL DEFAULT 5.0,
    result              VARCHAR(8) NOT NULL,        -- pass, fail, warning
    is_spot_check       BOOLEAN NOT NULL DEFAULT FALSE,
    check_in_record_id  UUID REFERENCES chrono_records(id),
    marshal_signature   VARCHAR(512) NOT NULL,       -- Ed25519 signature (ADR-P4-5)
    notes               TEXT,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_chrono_records_replica ON chrono_records(replica_id);
CREATE INDEX idx_chrono_records_field ON chrono_records(field_id);
CREATE INDEX idx_chrono_records_marshal ON chrono_records(marshal_id);
CREATE INDEX idx_chrono_records_game ON chrono_records(game_id);

CREATE TABLE chrono_violations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chrono_record_id UUID NOT NULL REFERENCES chrono_records(id) ON DELETE CASCADE,
    game_id          UUID REFERENCES games(id),
    violation_type   VARCHAR(32) NOT NULL,  -- over_limit, over_tolerance, repeat_offender
    delta_j          REAL,
    outcome          VARCHAR(32),           -- warning, pulled, ban
    resolved_by      UUID REFERENCES users(id),
    resolved_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### Players

```sql
CREATE TABLE player_profiles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    field_id    UUID NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    callsign    VARCHAR(64),
    team_preference VARCHAR(64),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, field_id)
);

CREATE TABLE player_stats (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    field_id    UUID NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    games_played INTEGER NOT NULL DEFAULT 0,
    total_score  INTEGER NOT NULL DEFAULT 0,
    last_game_at TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, field_id)
);
```

#### Scheduling

```sql
CREATE TABLE scheduled_games (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    field_id         UUID NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    title            VARCHAR(256) NOT NULL,
    description      TEXT,
    scheduled_at     TIMESTAMPTZ NOT NULL,
    duration_estimate INTERVAL,
    mode_id          VARCHAR(128),
    preset_id        UUID REFERENCES presets(id),
    scenario_id      UUID REFERENCES scenarios(id),
    max_players      INTEGER,
    teams            JSONB NOT NULL DEFAULT '[]',
    status           VARCHAR(16) NOT NULL DEFAULT 'draft',
                     -- draft, published, registering, in_progress, completed, cancelled
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE game_registrations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scheduled_game_id UUID NOT NULL REFERENCES scheduled_games(id) ON DELETE CASCADE,
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    team_preference  VARCHAR(64),
    registered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(scheduled_game_id, user_id)
);
```

**Updated 2026-10-19 (ADR-P4-11, maintainer request):** both tables gain
columns for the registration window, publication, the federation
requirement, imported registrations without an account, pre-declared
replicas (`registration_replicas`) and per-field player ids
(`field_player_ids`).

#### Scenarios

```sql
CREATE TABLE scenarios (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    field_id    UUID NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    name        VARCHAR(256) NOT NULL,
    manifest    JSONB NOT NULL,            -- the YAML manifest stored as JSON
    compiled_lua TEXT,                      -- compiled field.lua output (ADR-P4-6)
    author_id   UUID REFERENCES users(id),
    version     INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_scenarios_field ON scenarios(field_id);
```

#### Audit log

```sql
CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID REFERENCES users(id),
    action      VARCHAR(64) NOT NULL,       -- login, logout, role_change, score_adjust, ...
    resource    VARCHAR(64),
    resource_id UUID,
    details     JSONB,
    ip_address  INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_log_user ON audit_log(user_id);
CREATE INDEX idx_audit_log_action ON audit_log(action);
CREATE INDEX idx_audit_log_created ON audit_log(created_at);
```

**GDPR-related columns:**

- `users.gdpr_consent_at`: explicit consent timestamp; NULL = not
  consented.
- `users.data_retention_days`: per-user override; NULL = field default.
- The retention purge job (ADR-P4-8) uses `fields.default_retention_days`
  and per-user overrides.

**Migration strategy (Alembic):**

```ini
# alembic.ini (key settings)
[alembic]
script_location = server/migrations
sqlalchemy.url = driver://...  # overridden by env var
```

```python
# server/migrations/env.py
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context

def run_migrations_online():
    connectable = create_async_engine(settings.database_url)
    # ... standard async Alembic runner
```

Rules:
1. Every migration has both `upgrade()` and `downgrade()`.
2. Destructive operations (DROP COLUMN, DROP TABLE) are two-step: first
   migration marks the column unused; second migration (after one
   release) drops it.
3. Data migrations (backfills) run in batches of 1000 rows with
   `COMMIT` between batches to avoid long-running transactions.
4. The CI pipeline runs `alembic upgrade head` + `alembic downgrade
   base` + `alembic upgrade head` against a test database to verify
   reversibility.

**Consequences:**
- The schema supports both self-hosted (single field) and hosted
  (multi-tenant, ADR-P4-4) deployments.
- UUID primary keys avoid sequential enumeration attacks on API
  endpoints.
- JSONB columns (`readings`, `data`, `teams`, `params`, `manifest`)
  provide flexibility for semi-structured data while keeping the
  relational structure for queryable fields.
- The `UNIQUE(game_id, node_id, seq, game_time_ms, event_type)`
  constraint on `game_events` mirrors the controller's SQLite dedupe
  (widened from ADR-P2-9's original `(game_id, node_id, seq)` to
  handle seq restarts after a box reboot -- see decision D6) and
  enforces idempotent event sync.
- **Player tokens** (Phase 3): the controller issues HMAC-SHA256-
  signed JSON player tokens (not JWT) with `player_id`, `team`,
  `squad`, `role`, `game_id`, `exp`, signed with the controller's own
  per-game token key (decision B8; corrected 2026-10-19: not the game
  key). The site server does not issue player tokens and, since it
  never receives positions (P4R25), does not verify them either.
  *(The earlier "`player_tokens` cache" is superseded 2026-10-19.)*
- Alembic's reversibility requirement means any deployment can be
  rolled back within one release window.

**Amendment 2026-10-19 (after phase 3 software; decisions P4R10,
P4R11, P4R15, proposed):**

- **Built in steps.** The schema above is the target; each plan phase
  adds its own reversible migration (`0001_base`: fields, users, roles,
  sessions, audit log; then accounts, sync, chrono, scheduling,
  registration, clubs), instead of one `0001_initial_schema`.
- **Games from controllers.** A synced game is identified by
  `(field_id, game_id, game_seed)`: `game_id` is the controller's 16-bit
  radio id, which repeats over months, and `game_seed` (32-bit, random
  per game, in the join) is shared with a standby controller. `games`
  gains `game_id INTEGER`, `game_seed BIGINT`, `team_info JSONB`
  (display names and crests), `params JSONB`, `squads SMALLINT`, with
  `UNIQUE(field_id, game_id, game_seed)`; teams are the controller's
  team names (colours).
- **Events** also keep `epoch`, `pkt_seq` and the controller's own
  event id (`source_id`) for the push cursor; the unique key above
  stays.
- **Scores.** `game_scores` (per team and counter) is replaced by
  `game_node_scores (game_id, node_id, team, value)`, merged by
  `GREATEST`; totals are derived as the controller derives them (the
  sum of node counters plus the controller's `score.delta` events),
  because a GM's adjustment can be negative.
- **Chrono.** `replicas` uses the app's `replica_id` (UUID) as its key,
  `owner_player_id` (the per-field id) next to `owner_id` (an account,
  when one adopted the id), `replica_type` including `sniper`, `class`
  (from the field's limit template), `make_model`. `chrono_records` is
  replaced by `chrono_readings`: one row per signed reading, keyed by
  the record's `reading_id`, with `record_json` exactly as received,
  the record's fields as columns for queries (`replica_id`, `player_id`,
  `type`, `velocity_mps`, `bb_weight_g`, `energy_j`, `chrono_id`,
  `marshal_id`, `field_id` as the controller's `[checkin] field_id`
  string, `game_id` optional, `timestamp`, `ref_reading_id`), the
  controller's `series_id` and `outcome`, and `verified_at`.
  `marshal_signing_keys` keeps public keys only (ADR-P4-5's amendment).
  `field_joule_limits` follows the limit templates (`max_energy_j`,
  `max_fps_020`, `med_m`, `fire_mode`).
- **Players.** `field_player_ids` (ADR-P4-11) holds the phase 3 form of
  id (`p-` + 12 base32); an account adopts a phone's id only with its
  secret (SHA-256 compared).

---

### ADR-P4-2: Authentication and session management

**Status:** Accepted

**Context:** The site server manages user accounts with role-based access
control. The spec (section 14) requires HTTPS, 2FA for GM/marshal/admin,
append-only chrono, and signed records. The research selected Argon2id
for passwords and JWT + TOTP for sessions (RESEARCH.md section 5).

**Decision:**

**Password hashing: Argon2id.**

Library: `argon2-cffi` (uses the reference C implementation via cffi;
no C compiler needed at runtime -- the wheel ships pre-built binaries,
and the Docker image uses pip install).

Parameters (OWASP 2024 recommendations):

```python
from argon2 import PasswordHasher

ph = PasswordHasher(
    time_cost=3,        # iterations
    memory_cost=65536,  # 64 MB
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=argon2.Type.ID,  # argon2id
)

hash = ph.hash(password)
# Returns: $argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>
```

Password policy (enforced at registration and change):
- Minimum 10 characters.
- Checked against the top 100,000 breached passwords (a static list
  shipped with the server, not an external API call).
- No character-class requirements (per NIST 800-63B).

**Session management: JWT access tokens + HTTP-only refresh tokens.**

Library: `PyJWT` (pure Python, maintained, supports RS256 and HS256).

```python
# Access token (short-lived, stateless)
access_payload = {
    "sub": str(user.id),           # user UUID
    "username": user.username,
    "roles": {"field-uuid": ["gm", "admin"]},  # per-field roles
    "iat": int(time.time()),
    "exp": int(time.time()) + 900,  # 15 minutes
    "jti": str(uuid.uuid4()),       # unique token id
}
access_token = jwt.encode(access_payload, SECRET_KEY, algorithm="HS256")

# Refresh token (long-lived, stored in DB)
refresh_payload = {
    "sub": str(user.id),
    "sid": str(session.id),         # session UUID in DB
    "exp": int(time.time()) + 604800,  # 7 days
    "jti": str(uuid.uuid4()),
}
refresh_token = jwt.encode(refresh_payload, REFRESH_SECRET, algorithm="HS256")
```

Token transport:
- Access token: `Authorization: Bearer <token>` header (not in cookies,
  to avoid CSRF on the API).
- Refresh token: HTTP-only, Secure, SameSite=Strict cookie. Path
  restricted to `/api/v1/auth/refresh`.

Refresh flow:
1. Client sends the refresh cookie to `POST /api/v1/auth/refresh`.
2. Server verifies the JWT signature and checks the session in the DB
   (not revoked, not expired).
3. Server issues a new access token and rotates the refresh token
   (old refresh token is revoked, new one issued).
4. If the old refresh token has already been used (replay detection),
   the server revokes the entire session.

**Two-factor authentication: TOTP (RFC 6238).**

Library: `pyotp`.

```python
import pyotp

# Enrollment
totp_secret = pyotp.random_base32()
# Store encrypted: Fernet(SECRET_KEY).encrypt(totp_secret.encode())
provisioning_uri = pyotp.totp.TOTP(totp_secret).provisioning_uri(
    name=user.email or user.username,
    issuer_name="Atalaia",
)
# Return provisioning_uri as QR code for the authenticator app

# Verification
totp = pyotp.TOTP(decrypted_secret)
is_valid = totp.verify(user_code, valid_window=1)  # +/- 30 seconds
```

TOTP enforcement:
- **Mandatory** for admin, GM and marshal roles. Role assignment fails
  if TOTP is not enrolled.
- **Optional** for player, squad_leader, vip and spectator roles.
- TOTP secrets are encrypted at rest with Fernet (symmetric, using the
  server's `SECRET_KEY`). The `totp_secret_enc` column in `users`
  stores the ciphertext.

**Rate limiting:**

```python
# FastAPI dependency using an in-memory sliding window (or Redis for multi-worker)
from fastapi import Depends, HTTPException

async def rate_limit_login(request: Request):
    key = f"login:{request.client.host}"
    attempts = await rate_store.get(key, 0)
    if attempts >= 5:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again in 15 minutes.",
            headers={"Retry-After": "900"},
        )
    await rate_store.increment(key, ttl=900)  # 15-minute window
```

- 5 failed logins per IP: 15-minute lockout.
- 5 failed TOTP attempts per user: 15-minute lockout.
- 100 requests per minute per IP for general API endpoints.
- Rate state stored in-process (dict with TTL) for single-worker
  deployments. Redis is optional for multi-worker.

**Login flow:**

```
POST /api/v1/auth/login
  Body: { username, password }
  Response (no TOTP):
    { access_token, user: {...} }
    + Set-Cookie: refresh_token=...

  Response (TOTP required):
    { totp_required: true, totp_session: "<short-lived-token>" }

POST /api/v1/auth/login/totp
  Body: { totp_session, code }
  Response:
    { access_token, user: {...} }
    + Set-Cookie: refresh_token=...
```

The `totp_session` token is a short-lived JWT (5 minutes) that proves
the password was verified. It is single-use (tracked in memory).

**FastAPI dependency injection for role checks:**

```python
from fastapi import Depends, Security

async def require_role(*required_roles: str, field_id: UUID = None):
    async def check(user = Depends(get_current_user)):
        if field_id:
            user_roles = user.roles.get(str(field_id), [])
        else:
            user_roles = [r for roles in user.roles.values() for r in roles]
        if not any(r in user_roles for r in required_roles):
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user
    return check

# Usage:
@app.post("/api/v1/chrono/records")
async def create_chrono_record(
    record: ChronoRecordCreate,
    user = Security(require_role("marshal", "admin"), scopes=["field"]),
):
    ...
```

**Consequences:**
- Argon2id with 64 MB memory cost makes offline brute-force
  expensive (each guess costs ~64 MB x 3 iterations). The Docker
  image must have sufficient memory (minimum 256 MB for the app).
- JWT access tokens are stateless; the server does not need a database
  lookup on every API call. Only refresh token validation hits the DB.
- Refresh token rotation detects replay attacks. A stolen refresh
  token can be used at most once before the session is revoked.
- TOTP is mandatory for privileged roles, matching the spec's
  requirement (section 14: "two-factor login required for these
  roles").
- Rate limiting at the application layer is sufficient for single-site
  deployments. A reverse proxy (Caddy/nginx) adds a second layer
  (ADR-P4-10).

**Re-check 2026-10-19:** holds. Site-server accounts and sessions are
independent of the controller's GM, read and player tokens; the role
names match the controller's player-token roles (`player`,
`squad_leader`, `vip`, `marshal`, `gm`, `spectator`) plus `admin`. The
code goes in `server/atalaia_server/` (not `server/src/`, as decision
D15 did for the controller).

*Built 2026-10-19 (plan phase 11; decisions S11-1 to S11-15, proposed):*
as above, except: refresh tokens are 256-bit random values stored only as
SHA-256 in `refresh_tokens` (every token a session was given, so a replay
is recognised), not JWTs with a `REFRESH_SECRET`; access tokens are still
JWTs, but each request re-reads the session and the roles from the
database, so a logout or a removed role counts at once; the keys are
derived from one `ATALAIA_SECRET_KEY` with HKDF; a TOTP code is accepted
once (RFC 6238 section 5.2); the refresh endpoint also needs the header
`X-Atalaia-Refresh: 1`; a site-wide `users.server_admin`, made by
`python -m atalaia_server create-admin`, administers fields; per-game roles
come with `games` in plan phase 13.
*Changed 2026-10-19 (plan phase 12; decision S12-1):* the login lockout is
per (address, username), 5 failures in 15 minutes, with a ceiling of 50
failures in 15 minutes per address, so one player's typos no longer lock out
everyone behind a field's shared 4G address.

---

### ADR-P4-3: Sync protocol between controller and site server

**Status:** Accepted

**Context:** The controller is authoritative during a game; the site
server is authoritative for accounts and historical data. The sync must
handle offline operation (the controller buffers everything and uploads
later). Events are append-only and scores are grow-only, so the sync
is conflict-free by design (RESEARCH.md section 6).

**Decision:**

**Transport:** HTTPS (TLS 1.3).

**Authentication (asymmetric, updated 2026-10-18):**

The controller and site server authenticate to each other with
different mechanisms:

- **Controller to site server (API key):** Each field has a long-lived
  API key generated during field registration on the site server. The
  key is a 256-bit random value, base64url-encoded (43 characters).
  The site server stores the Argon2id hash of the key in
  `fields.api_key_hash`. The controller stores the plaintext key in
  its local config file (protected by filesystem permissions).

- **Site server to controller (bearer tokens):** The site server
  authenticates to the controller using the controller's existing
  bearer token auth (decision D12): the GM token for write operations
  (game state, score push, commands) and the read token for read
  operations (event log, device health, roster). This reuses the
  controller's auth model without adding a separate API-key path on
  the controller side. *(Superseded 2026-10-19: the site server never
  connects to the controller and holds none of its tokens; see the
  amendment at the end of this ADR, decision P4R12.)*

**Controller API key (controller to site server):**

```python
# Key generation (on the site server during field registration)
import secrets
api_key = secrets.token_urlsafe(32)  # 256 bits, 43 chars
api_key_hash = ph.hash(api_key)
# Store api_key_hash in fields table
# Return api_key to the admin (shown once, never stored in plaintext on the server)
```

The controller authenticates every request with:
```
Authorization: Bearer <api_key>
```

The site server verifies by hashing the presented key and comparing
with the stored hash. To avoid hashing on every request (Argon2id is
intentionally slow), the server caches a (hash_of_key -> field_id)
mapping in memory after the first successful verification, keyed by
SHA-256 of the presented key (fast lookup, no timing attack on the
cache key). *(Superseded 2026-10-19: the key is stored as its SHA-256
only, decision P4R13; see the amendment.)*

**Controller REST API endpoints (from Phase 2, for reference):**

*(2026-10-19: a small subset of what the controller now serves; the
full list as built is in `controller/atalaia_controller/api.py`'s
docstring and `controller/README.md`. Phase 3 added a third kind of
token, the player token, and routes that need no token at all:
`/healthz`, the CA, branding, the check-in poster's `GET` and the
check-in itself. The site server uses none of these routes, P4R12.)*

The controller serves these endpoints (bearer token auth: read token
for GET, GM token for state changes):

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/v1/games` | read | List games |
| GET | `/api/v1/games/{id}` | read | Game detail with events and scores |
| POST | `/api/v1/games` | GM | Create game |
| POST | `/api/v1/games/{id}/start` | GM | Start game |
| POST | `/api/v1/games/{id}/pause` | GM | Pause game |
| POST | `/api/v1/games/{id}/end` | GM | End game |
| GET | `/api/v1/controller` | read | Controller status |
| GET | `/healthz` | none | Health check |

The sync client on the controller side uses the site server's sync
endpoints below with the API key. The site server uses the
controller's endpoints above with the GM/read tokens.

**Sync endpoints (site server):**

| Method | Path | Direction | Purpose |
|--------|------|-----------|---------|
| GET | `/api/v1/sync/roster?game_id=` | Controller pulls | Players registered for upcoming game (payload defined in ADR-P4-11: registrations with pre-declared replicas and check-in ticket hashes) |
| GET | `/api/v1/sync/schedule?days=` | Controller pulls | Published scheduled games (added by ADR-P4-11) |
| POST | `/api/v1/sync/checkins` | Controller pushes | Check-in outcomes and declaration states after the game (added by ADR-P4-11) |
| GET | `/api/v1/sync/presets` | Controller pulls | Shared presets (version > controller's version) |
| GET | `/api/v1/sync/chrono?player_ids=` | Controller pulls | Chrono records for registered players |
| GET | `/api/v1/sync/field` | Controller pulls | Field config, joule limits, house rules |
| POST | `/api/v1/sync/events` | Controller pushes | Event batch |
| POST | `/api/v1/sync/scores` | Controller pushes | Score snapshot (grow-only merge) |
| POST | `/api/v1/sync/chrono` | Controller pushes | New chrono records created during game |
| POST | `/api/v1/sync/game` | Controller pushes | Game metadata (create, start, end, final scores) |
| WS | `/api/v1/sync/stream` | Controller pushes | Live event stream (optional, for live scoreboard) |

**Event batch format:**

```json
{
  "sync_version": 1,
  "field_id": "550e8400-e29b-41d4-a716-446655440000",
  "game_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "batch_seq": 7,
  "events": [
    {
      "node_id": 3,
      "seq": 141,
      "game_time_ms": 734210,
      "type": "zone.captured",
      "team": 1,
      "priority": 1,
      "data": {"zone": "alpha"}
    }
  ]
}
```

**Batch response:**

```json
{
  "ack_batch_seq": 7,
  "events_inserted": 12,
  "events_duplicate": 0,
  "server_time": "2026-10-17T14:30:00Z"
}
```

The `ack_batch_seq` tells the controller which batches have been
persisted. The controller frees its upload buffer for acknowledged
batches.

**Score snapshot format:**

```json
{
  "game_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "scores": {
    "red": {"total": 1250, "zone_hold": 800, "code_used": 450},
    "blue": {"total": 1100, "zone_hold": 900, "code_used": 200}
  },
  "snapshot_at": "2026-10-17T14:30:00Z"
}
```

The site server merges scores by taking the maximum of each counter:

```python
async def merge_scores(game_id: UUID, incoming: dict):
    for team, counters in incoming.items():
        for counter_name, value in counters.items():
            await db.execute(
                """INSERT INTO game_scores (game_id, team, counter, value, snapshot_at)
                   VALUES (:game_id, :team, :counter, :value, now())
                   ON CONFLICT (game_id, team, counter)
                   DO UPDATE SET value = GREATEST(game_scores.value, :value),
                                 snapshot_at = now()""",
                {"game_id": game_id, "team": team_id,
                 "counter": counter_name, "value": value},
            )
```

**Offline buffering (controller side):**

When the site server is unreachable:

1. Events are buffered in the controller's SQLite database (existing
   `events` table, ADR-P2-9).
2. The controller tracks the last acknowledged `batch_seq` per game.
3. On reconnect, the controller replays all unacknowledged batches in
   order.
4. Batch replay is idempotent: the
   `UNIQUE(game_id, node_id, seq, game_time_ms, event_type)`
   constraint on the site server silently drops duplicates.

The controller attempts a sync every 30 seconds during a game and
every 5 minutes between games. Backoff doubles on consecutive failures,
capped at 5 minutes.

**WebSocket live stream (optional):**

```python
# Controller connects to ws://site-server/api/v1/sync/stream
# Authenticates with the API key in the first message:
{"type": "auth", "api_key": "<key>", "field_id": "<uuid>"}

# Then pushes events as they happen:
{"type": "event", "game_id": "...", "event": {...}}
{"type": "score", "game_id": "...", "scores": {...}}
```

The WebSocket is optional. If the controller cannot establish a WS
connection, it falls back to HTTP batch POST. The site server uses the
WS stream to update live scoreboards and the remote GM console in
real time.

**Consequences:**
- The sync is one-way during games (controller -> site server). The
  site server never pushes game state to the controller during a game.
- Auth is asymmetric: the controller authenticates to the site server
  with an API key; the site server authenticates to the controller
  with bearer tokens (GM/read). This avoids adding a second auth
  mechanism to the controller and reuses the existing token model
  (decision D12).
- Offline buffering is transparent: the controller works identically
  whether the site server is reachable or not.
- The grow-only score merge (`GREATEST`) is the same algorithm as the
  controller's internal score merge (ADR-P2-9), proven correct.
- Batch replay with deduplication means the controller never needs to
  track exactly which events the site server has -- it can replay
  conservatively.

**Amendment 2026-10-19 (after phase 3 software; decisions P4R10-P4R13,
P4R25, proposed):**

1. **The controller opens every connection.** A field controller sits
   behind a phone's 4G link, usually behind carrier-grade NAT, so the
   site server cannot reach it. The controller makes HTTPS requests to
   the site server and keeps one WebSocket open to it
   (`WS /api/v1/sync/stream`); anything the site server sends to the
   controller (remote GM commands, plan phase 19) travels back on that
   WebSocket. The site server never stores the controller's GM, read or
   player-token keys; this changes the answer to decision P4-8.
2. **API key.** A 256-bit random key per field (more than one during a
   rotation), stored on the site server as its SHA-256 and compared in
   constant time; Argon2id and the cache above are dropped (a random
   key cannot be guessed, so a slow hash adds nothing). On the
   controller: `[sync] api_key`, `ATALAIA_SYNC_API_KEY`, or stored in
   its settings with `python3 -m atalaia_controller sync-key`.
3. **Game identity.** `(field, game_id, game_seed)` (ADR-P4-1's
   amendment); the batch carries `game_id` and `game_seed`, never a
   site-server UUID the controller would have to learn first.
4. **Cursor.** The controller pushes its own `events` rows in id order
   and keeps, per game, the last id the site server acknowledged
   (`sync_state`, controller store schema 5); the site server answers
   `acked_id`. The unique key still drops replays. `batch_seq` is
   dropped.
5. **Scores.** The snapshot carries per node counters
   (`{node_id: {team: value}}`) merged by `GREATEST`; GM adjustments
   arrive as the controller's `score.delta` events; per-reason counters
   are dropped (the controller has none).
6. **Endpoints** (site server; all with the API key):
   `POST /api/v1/sync/games` (game metadata, replacing
   `POST /api/v1/sync/game`), `POST /api/v1/sync/events`,
   `POST /api/v1/sync/scores`, `POST /api/v1/sync/nodes` (names, roles,
   health), `POST /api/v1/sync/marshals`, `POST /api/v1/sync/replicas`,
   `POST /api/v1/sync/chrono` (signed readings with the controller's
   series outcomes), `POST /api/v1/sync/checkins` (ADR-P4-11),
   `GET /api/v1/sync/field` (field settings, limit template, branding
   and saved teams, P4R19), `GET /api/v1/sync/presets` (presets and
   scenarios), `GET /api/v1/sync/schedule` and `GET /api/v1/sync/roster`
   (ADR-P4-11), `WS /api/v1/sync/stream`. `GET /api/v1/sync/chrono`
   (pulling other fields' records for registered players) waits for
   the sharing consent rules (ADR-P4-5) and is not in the first version.
7. **Never sent:** positions (P4R25), tokens and keys, check-in names
   and federation numbers beyond what ADR-P4-11 sends back.
8. **One format, two implementations.** The batch formats go into
   `protocol/sync.md` with shared vectors (`protocol/vectors/sync.json`)
   read by the controller's client and the site server.

*Built 2026-10-20 (plan phase 13; decisions S13-1 to S13-12, proposed):*
`POST /api/v1/sync/games`, `events`, `scores` and `nodes` and
`WS /api/v1/sync/stream` (the key on the upgrade, not in a first message) on
the site server; the controller's `sync_client.py` over HTTPS with the
standard library, offline first, its cursor in `sync_state` (store schema 5);
both check bodies with `controller/atalaia_controller/sync_format.py` against
`protocol/vectors/sync.json`. A joined controller's "ended" does not end a
game; a `game.end` event does. The other endpoints of item 6 come with
their plan phases. *(2026-10-20, plan phase 14: `POST /api/v1/sync/marshals`,
`replicas` and `chrono` are built, field-level bodies without a `game`;
`GET /api/v1/sync/chrono` still waits, see ADR-P4-5; built 2026-10-27 as
`GET /api/v1/sync/chrono?scheduled_game_id=`, the roster's players only, decision S14-5.)* *(2026-10-20, plan phase 18: `GET
/api/v1/sync/field` carries the field's branding and saved teams, with
`GET /api/v1/sync/images/{sha256}` for their images, pulled only with
`[sync] branding = "site"`; the field settings and limit template are not
in it yet, decision S18-1.)* *(2026-10-20, plan phase 19: with `[sync]
remote_gm = true` the controller opens `WS /api/v1/sync/stream` itself and
sends `hello`, `live` and `command.result` on it; the site server sends
`command` back, for a user with the `gm` role on the field in a TOTP
session, from a list of six (start, pause, resume, end, a GM message, a
declared mode command); both sides check every message with
`sync_format.STREAM` and log every command; decisions S19-1 to S19-11.)*

---

### ADR-P4-4: Multi-tenant isolation

**Status:** Accepted

**Context:** The community hub offers hosted site servers for clubs
without IT support. Multiple fields share one PostgreSQL instance. Data
must be isolated, exportable and independently deletable (spec section
13, RESEARCH.md section 4).

**Decision:** **Schema-per-field in hosted mode; single schema in
self-hosted mode.**

**Hosted mode (multi-tenant):**

Each hosted field gets its own PostgreSQL schema within the shared
database. The schema name is derived from the field's slug:
`field_<slug>` (e.g., `field_paintball_lisboa`).

```sql
-- Create a new tenant schema
CREATE SCHEMA field_paintball_lisboa;

-- All tables from ADR-P4-1 are created within this schema
SET search_path TO field_paintball_lisboa;
CREATE TABLE users (...);
CREATE TABLE fields (...);
-- etc.
```

A shared `public` schema holds:
- The `tenants` table (field_id, slug, schema_name, created_at,
  plan, status).
- Cross-field lookup tables (e.g., for chrono sharing between fields
  that opt in).

**Tenant routing (SQLAlchemy):**

```python
from sqlalchemy.ext.asyncio import AsyncSession

class TenantMiddleware:
    """Sets the PostgreSQL search_path per request."""

    async def __call__(self, request: Request, call_next):
        field_slug = extract_tenant(request)  # from subdomain or API key
        if field_slug:
            schema = f"field_{field_slug}"
            request.state.schema = schema
        else:
            request.state.schema = "public"
        return await call_next(request)

async def get_db(request: Request) -> AsyncSession:
    schema = getattr(request.state, "schema", "public")
    async with async_session() as session:
        await session.execute(text(f"SET search_path TO {schema}, public"))
        yield session
```

Tenant identification:
- **API requests from controllers**: the API key maps to a field, which
  maps to a schema.
- **Web/app requests from users**: subdomain routing
  (`paintball-lisboa.atalaia.example.com`) or a field selector in the
  UI that sets a cookie/header.

**Self-hosted mode (single tenant):**

All tables live in the `public` schema. No `tenants` table, no
schema routing. The `field_id` column exists in all tables for forward
compatibility but always contains the single field's UUID.

**Export (data portability):**

```bash
# Export one field's entire dataset for migration to self-hosted
pg_dump --schema=field_paintball_lisboa \
        --no-owner --no-privileges \
        -f paintball_lisboa_export.sql \
        atalaia_hosted

# The field operator can import this into their self-hosted PostgreSQL
psql -d atalaia_self_hosted -f paintball_lisboa_export.sql
# Then rename the schema to public:
ALTER SCHEMA field_paintball_lisboa RENAME TO public;
```

The site server also provides an API endpoint for export:
```
GET /api/v1/admin/export
  Authorization: Bearer <admin_token>
  Response: application/sql (pg_dump output)
```

**Deletion:**

```sql
-- Hosted mode: drop the entire schema
DROP SCHEMA field_paintball_lisboa CASCADE;
DELETE FROM public.tenants WHERE slug = 'paintball_lisboa';
```

This is atomic: all the field's data is removed in one operation.

**Alembic with multi-tenant:**

Alembic migrations run against every tenant schema:

```python
# migrations/env.py
async def run_migrations_online():
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        # Migrate the public schema first
        await conn.execute(text("SET search_path TO public"))
        await context.run_migrations()

        # Then migrate each tenant schema
        if settings.hosted_mode:
            tenants = await conn.execute(
                text("SELECT schema_name FROM public.tenants WHERE status = 'active'")
            )
            for row in tenants:
                await conn.execute(text(f"SET search_path TO {row.schema_name}"))
                await context.run_migrations()
```

**Row-level security (defense in depth):**

In addition to schema isolation, RLS policies prevent cross-tenant
data access even if the application has a bug in schema routing:

```sql
-- Applied to each tenant schema's tables
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON users
    USING (current_setting('app.current_field_id') = field_id::text);
```

The application sets `app.current_field_id` at the start of each
request. RLS is a safety net; schema isolation is the primary
mechanism.

**Consequences:**
- Schema-per-field gives strong isolation: a `pg_dump --schema` exports
  one field cleanly, and `DROP SCHEMA CASCADE` deletes everything.
- Schema routing in SQLAlchemy uses `SET search_path`, which is a
  session-level setting. Each database session (connection from the
  pool) is configured per request.
- Self-hosted deployments have zero multi-tenant overhead: no schema
  routing, no RLS policies, no `tenants` table.
- Alembic must iterate over tenant schemas during migration. This adds
  time proportional to the number of tenants, but migrations are
  infrequent and run during maintenance windows.
- The schema approach limits the number of tenants to ~1,000 per
  PostgreSQL instance (each schema creates catalog entries). This is
  sufficient for the community hub's expected scale (tens to low
  hundreds of fields). Beyond that, a second PostgreSQL instance is
  the scaling path.

**Re-check 2026-10-19:** holds. Hosted mode is built last (plan phase
21), once every table exists, and does not go live before the legal
review (decision P4-6). With the controller-initiated link (ADR-P4-3's
amendment) the API key also selects the tenant on the sync WebSocket.

**As built 2026-10-20 (plan phase 21; decisions S21-1 to S21-12, open):**
schema per field as decided, each schema a whole single-field database (its
own `users`, its own `alembic_version`), `public` holding only
`atalaia_tenants` and the hub's audit log. Three changes from the text above:
the tenant comes from the host name only and the API key is checked inside
that tenant, so a key never selects one (S21-3); the search path and the
tenant setting are set per transaction with `set_config(..., true)`, never per
session, and a connection's own path is `pg_catalog` (S21-5); the RLS policy
compares the setting with the schema's own name, so it covers every table
(the `field_id` policy above fits only the tables that have that column), with
`FORCE ROW LEVEL SECURITY` and a server role that owns nothing and has no
`BYPASSRLS` (S21-1). The export is a ZIP of CSV files with a manifest made by
the operator's command, with an import into a single-field server, instead of
`pg_dump` and an admin endpoint (S21-8).

---

### ADR-P4-5: Chrono record signing

**Status:** Accepted

**Context:** Chrono records must be tamper-evident. The spec (section 14)
says "records are append-only and signed by the marshal's account."
The research identified two options: HMAC-SHA256 derived from the
marshal's password, or Ed25519 keypairs per marshal (RESEARCH.md
section 7). HMAC-SHA256 has a key lifecycle problem: password changes
invalidate the signing key, making future signatures incompatible with
past ones if the key derivation uses the password.

**Decision:** **Ed25519 per-marshal keypairs.**

**Key lifecycle:**

*(Steps 1, 3 and 4 and the `encrypted_private_key` column are
superseded 2026-10-19: phase 3 makes the key on the marshal's phone and
the site server keeps public keys only; see the amendment at the end of
this ADR, decision P4R14.)*

1. When a user is assigned the marshal role (`user_field_roles`),
   the server generates an Ed25519 keypair.
2. The public key is stored in the database (`marshal_signing_keys`
   table).
3. The private key is returned to the marshal once (during enrollment)
   and stored in the marshal's app or browser secure storage. It is
   never stored on the server.
4. The private key is also encrypted with the marshal's password
   (using Fernet with HKDF-SHA256 key derivation from the password)
   and stored as `encrypted_private_key` for recovery.

```sql
CREATE TABLE marshal_signing_keys (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    field_id               UUID NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    public_key             BYTEA NOT NULL,           -- 32 bytes Ed25519 public key
    encrypted_private_key  BYTEA NOT NULL,           -- Fernet-encrypted private key
    key_version            INTEGER NOT NULL DEFAULT 1,
    active                 BOOLEAN NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at             TIMESTAMPTZ
);
CREATE INDEX idx_marshal_keys_user ON marshal_signing_keys(user_id, field_id);
```

**Signing a chrono record:**

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import json

def sign_chrono_record(record: dict, private_key_bytes: bytes) -> str:
    """Sign a chrono record and return the base64-encoded signature."""
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)

    # Canonical JSON: sorted keys, no whitespace, UTF-8
    canonical = json.dumps(
        {k: v for k, v in record.items() if k != "marshal_signature"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    signature = private_key.sign(canonical)
    return base64.b64encode(signature).decode("ascii")
```

**Verification:**

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

def verify_chrono_record(record: dict, signature_b64: str,
                          public_key_bytes: bytes) -> bool:
    """Verify a chrono record's signature."""
    public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    canonical = json.dumps(
        {k: v for k, v in record.items() if k != "marshal_signature"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    signature = base64.b64decode(signature_b64)
    try:
        public_key.verify(signature, canonical)
        return True
    except InvalidSignature:
        return False
```

**Key rotation:**

- Password changes do NOT invalidate the signing key (unlike the
  HMAC approach). The Ed25519 key is independent of the password.
- If a marshal's key is compromised, an admin revokes it
  (`revoked_at` timestamp) and generates a new keypair. Past records
  signed with the old key remain verifiable (the old public key is
  retained with `active=FALSE`).
- The `encrypted_private_key` must be re-encrypted when the password
  changes: the server decrypts with the old password-derived key and
  re-encrypts with the new one during the password-change flow.

**Cross-field chrono sharing:**

When a field queries another field's chrono records for a player
(with consent, per RESEARCH.md section 7), the response includes the
marshal's public key and the signature. The querying field can verify
the record's integrity without trusting the originating field's
database.

**Why Ed25519 over HMAC-SHA256:**

| Criterion | Ed25519 | HMAC-SHA256 (password-derived) |
|-----------|---------|-------------------------------|
| Key lifecycle | Independent of password | Broken by password change |
| Cross-field verification | Public key shareable | Requires shared secret |
| Non-repudiation | Marshal cannot deny signing | Server also knows the key |
| Complexity | Keypair management | Simpler but fragile |

Ed25519 is the better fit because chrono records are legal evidence
(a player caught with a hot gun) and must be independently verifiable.

Library: `cryptography` (already a dependency via `argon2-cffi`).
Ed25519 is in the `cryptography.hazmat.primitives.asymmetric.ed25519`
module.

**Consequences:**
- Marshal enrollment is a one-time step that produces a keypair. The
  private key must be stored securely on the marshal's device.
- Password changes do not affect past or future signatures.
- Cross-field verification works without shared secrets.
- Key revocation is explicit and auditable.
- The `encrypted_private_key` recovery path means a marshal who loses
  their device can recover their signing key by logging in with their
  password. This is a trade-off: the server holds encrypted private
  keys, which are recoverable by anyone who knows the password. For the
  threat model (game integrity, not national security), this is
  acceptable.

**Amendment 2026-10-19 (after phase 3 software; decisions P4R14, P4R15,
proposed):**

- **Ed25519 per marshal holds** (decision P3-1), with the record
  format of `protocol/chrono-record.md` version 1: one record per shot,
  canonical JSON (sorted keys, no spaces, UTF-8, the three numbers as
  floats), the signature in `signature` (standard base64, 88
  characters), RFC 8032's pure Ed25519 with non-canonical signatures
  refused. The signing and verifying snippets above use
  `marshal_signature`; the built format names the field `signature`,
  and the shared vectors (`protocol/vectors/chrono_record.json`) are the
  reference.
- **Keys are made on the marshal's phone** (`app/lib/chrono/record_signer.dart`)
  and only the public key leaves it: to the controller with
  `PUT /api/v1/checkin/me/marshal-key` or `POST /api/v1/marshals`
  (`{marshal_id, name, public_key}`), and from the controller to the
  site server (`POST /api/v1/sync/marshals`). A marshal with an account
  can also register the key on the site server, which links it to the
  account.
- **No private key on the site server**, encrypted or not: a server
  that can sign as a marshal undoes the non-repudiation this ADR chose
  Ed25519 for. A lost phone means a new key; old keys stay with their
  validity period, so old records still verify. `protocol/chrono-record.md`
  still mentions the recovery copy; it is to be corrected when P4R14 is
  confirmed.
- **Storage and verification:** the site server keeps each reading
  verbatim (`chrono_readings.record_json`, ADR-P4-1's amendment) and
  verifies it on arrival with the controller's own verifier
  (`atalaia_controller.chrono.verify`, imported, not rewritten); a
  record that fails is kept apart and reported, never dropped
  silently.
- **Cross-field sharing** uses accounts: per-field player ids are
  pseudonymous on purpose (decision F3), so records of two fields are
  linked only through an account that adopted both ids and consented.

*Built 2026-10-20 (plan phase 14; decisions S14-1 to S14-12, proposed):*
the controller pushes `POST /api/v1/sync/marshals` (public keys with the
period each was the marshal's key: the controller now keeps earlier keys in
`marshal_key_history`, store schema 6), `POST /api/v1/sync/replicas` and
`POST /api/v1/sync/chrono` (each record as the JSON text it stored, with the
series, its outcome and when the controller received it). The site server
verifies each reading with `atalaia_controller.chrono` against the keys of
its marshal valid when the controller received it
(`server/atalaia_server/chrono_verify.py`), stores it verbatim
(`chrono_readings.record_json`), keeps the ones that fail apart
(`chrono_rejects`, with the reason, rechecked when the marshal's keys
arrive) and turns failed or warned spot checks into `chrono_violations`. A
marshal can register their phone's public key from their account; a field's
admin can revoke a key. No private key exists on the site server, and
`protocol/chrono-record.md` now says so. Sharing between fields needs both
fields' `chrono_sharing_enabled` and the person's consent for each of the two
fields; the shared records carry the marshal's public key so that the other
field can check them itself.

---

### ADR-P4-6: Custom scenario DSL

**Status:** Accepted

**Context:** The spec (section 15) defines a scenario builder with
seven objective block types. Phase 4 uses a YAML-based manifest
(the visual editor is Phase 5). The compiler transforms the manifest
into a `field.lua` script that runs on the controller (RESEARCH.md
section 11).

**Decision:**

**Scenario manifest schema (YAML):**

```yaml
# scenario.yaml
id: "org.atalaia.scenario.operation-foxhound"
name: "Operation Foxhound"
version: 1
author: "gm@field.local"

teams:
  - name: alpha
    color: "#FF0000"
  - name: bravo
    color: "#0000FF"

squads:
  alpha:
    - alpha-1
    - alpha-2
  bravo:
    - bravo-1
    - bravo-2

# Node-to-role mapping (the GM assigns physical nodes to roles in the console)
nodes:
  box-a: { role: objective }
  box-b: { role: objective }
  box-c: { role: master }
  vip-phone: { role: vip, player: true }

objectives:
  - id: intel
    type: scan_tags
    assignee:
      team: alpha
      squad: alpha-1
    target: box-a
    params:
      tag_count: 3
    visibility: squad         # only alpha-1 sees this
    time_window:
      start_min: 0
      end_min: 90
    effect:
      points: 50
      reveal: [rescue]        # completing this reveals the 'rescue' objective

  - id: rescue
    type: escort
    assignee:
      team: alpha
      squad: alpha-2
    target: vip-phone
    params:
      destination:
        lat: 38.7223
        lon: -9.1393
        radius_m: 15
    visibility: hidden         # hidden until 'intel' is complete
    depends_on: [intel]
    effect:
      win: true

  - id: defend_hq
    type: defend
    assignee:
      team: bravo
    target: box-b
    params:
      duration_s: 2700          # 45 minutes
    visibility: team
    effect:
      points: 100

  - id: sabotage
    type: destroy
    assignee:
      team: alpha
      squad: alpha-1
    target: box-c
    params: {}
    visibility: squad
    depends_on: [intel]
    effect:
      points: 75
```

**Objective block types:**

| Type | Required params | Completion condition |
|------|----------------|---------------------|
| `capture_and_hold` | `target` (node), `duration_s` | Team holds the target for the specified duration |
| `enter_code` | `target` (node), `code` (string) | The correct code is entered on the target node |
| `scan_tags` | `target` (node), `tag_count` (int) | N tags scanned at the target node |
| `escort` | `target` (node/player), `destination` ({lat, lon, radius_m}) | VIP reaches the destination zone |
| `destroy` | `target` (node, bomb role) | Bomb explodes on the target node |
| `defend` | `target` (node), `duration_s` | Team prevents enemy capture for the duration |
| `survive` | `minimum_lives` (int) | Team has at least N lives remaining at game end |

**Validation rules (compile-time):**

1. All `id` values are unique within the scenario.
2. All `depends_on` references point to existing objective IDs.
3. The dependency graph is a DAG (no cycles). Validated with a
   topological sort.
4. All `target` nodes exist in the `nodes` map.
5. `time_window.start_min < time_window.end_min` when both are set.
6. `escort` objectives require a `destination` with valid coordinates
   and positive `radius_m`.
7. Each objective type's required params are present.

**Compilation to field.lua:**

The compiler is a Python package at
`controller/atalaia_controller/scenarios/` that generates Lua code
from templates. The site server imports and reuses this package.

```python
def compile_scenario(manifest: dict) -> str:
    """Compile a scenario manifest into a field.lua script."""
    validate_manifest(manifest)  # raises on error

    lua_parts = [LUA_PREAMBLE]

    # Generate state initialization
    lua_parts.append(generate_state_init(manifest))

    # Generate objective handlers in topological order
    for obj in topological_sort(manifest["objectives"]):
        template = OBJECTIVE_TEMPLATES[obj["type"]]
        lua_parts.append(template.render(obj=obj, manifest=manifest))

    # Generate dependency wiring
    lua_parts.append(generate_dependency_wiring(manifest))

    # Generate visibility management
    lua_parts.append(generate_visibility_handlers(manifest))

    return "\n".join(lua_parts)
```

**Example generated Lua for a `capture_and_hold` objective:**

```lua
-- Objective: defend_hq (defend, bravo, box-b, 2700s)
local obj_defend_hq = {
  id = "defend_hq",
  active = true,      -- no dependencies
  completed = false,
  hold_start = nil,
}

on("zone.captured", function(e)
  if not obj_defend_hq.active or obj_defend_hq.completed then return end
  if e.node == nodes["box-b"] then
    -- Enemy captured the target: defender failed
    if e.team ~= teams["bravo"] then
      obj_defend_hq.completed = true
      emit("scenario.objective.failed", {
        objective = "defend_hq", team = "bravo"
      })
    end
  end
end)

after(2700, function()
  if obj_defend_hq.active and not obj_defend_hq.completed then
    obj_defend_hq.completed = true
    score.add(teams["bravo"], 100, "objective:defend_hq")
    emit("scenario.objective.completed", {
      objective = "defend_hq", team = "bravo"
    })
  end
end)
```

**Dependency wiring:**

```lua
-- When 'intel' completes, activate 'rescue' and 'sabotage'
on("scenario.objective.completed", function(e)
  if e.data.objective == "intel" then
    obj_rescue.active = true
    emit("scenario.objective.revealed", {
      objective = "rescue", team = "alpha", squad = "alpha-2"
    }, { prio = "normal" })
    obj_sabotage.active = true
    emit("scenario.objective.revealed", {
      objective = "sabotage", team = "alpha", squad = "alpha-1"
    }, { prio = "normal" })
  end
end)
```

**New events** (added to `protocol/schema/events.yaml`):

| Event | Priority | Data |
|-------|----------|------|
| `scenario.objective.completed` | normal | `{objective, team, squad?}` |
| `scenario.objective.failed` | normal | `{objective, team, squad?}` |
| `scenario.objective.revealed` | normal | `{objective, team, squad?}` |
| `scenario.started` | critical | `{scenario_id, name}` |

**Where the compiler runs:**

On the field controller as a shared Python library at
`controller/atalaia_controller/scenarios/` (maintainer decision P4-1).
The GM console's scenario builder UI lives at
`controller/console/src/components/scenario-builder.js` and calls the
controller's compile endpoint. The controller validates and compiles
the scenario locally, stores both the manifest and the compiled
`field.lua`, and returns the result. A field without a site server
can still build custom scenarios (local-first, per spec sections 3
and 11).

The site server imports the same Python package for its own
`POST /api/v1/scenarios` endpoint, so compilation logic is never
duplicated. Scenarios compiled on the site server are pushed to the
controller via the normal preset sync (ADR-P4-3).

A CLI tool (`python -m atalaia_controller.scenarios.cli compile
scenario.yaml`) is also provided for offline use.

**New events** (phase 4 IDs start at 42):

| Event | ID | Priority | Data |
|-------|----|----------|------|
| `scenario.objective.completed` | 42 | normal | `{objective, team, squad?}` |
| `scenario.objective.failed` | 43 | normal | `{objective, team, squad?}` |
| `scenario.objective.revealed` | 44 | normal | `{objective, team, squad?}` |
| `scenario.started` | 45 | critical | `{scenario_id, name}` |

(IDs 46-49 are reserved for `satellite.captured`,
`satellite.neutralized`, `vip.extracted`, `hacking.solved` -- see
Phase B and Phase F of the plan. *Changed 2026-10-19, decision P4R1:
46 `vip.extracted`, 47 `hacking.solved`; satellites send
`zone.captured`, so no `satellite.*` events; 48-49 stay free; the
`objective` and `scenario` data keys are 34 and 35.*)

**Consequences:**
- The YAML manifest is human-readable and version-controllable. GMs
  can share scenarios as files.
- The compiled `field.lua` runs identically to hand-written field
  scripts: same API, same replay semantics, same failover behaviour.
- Validation catches errors at compile time, not at game time.
- The dependency graph (DAG) enables arbitrarily complex multi-
  objective scenarios without runtime complexity.
- The visual editor (Phase 5) will generate the same YAML manifest;
  the compiler is reused.
- Generated Lua is human-readable for debugging. The GM can inspect
  it in the console.
- The compiler lives on the controller
  (`controller/atalaia_controller/scenarios/`), so a field without a
  site server can still build custom scenarios. The site server
  imports the same package, avoiding code duplication.

**Amendment 2026-10-19 (after phase 3 software; decisions P4R1, P4R7,
P4R8, P4R9, P4R24, proposed):**

1. **What the nodes run.** A Field Box runs built-in presets only: a
   join for a mode it lacks is refused (`BOX_JOIN_NO_MODE`), and a new
   mode needs a firmware flash (decision K10). A scenario therefore
   cannot ship node scripts. The compiler emits a package of a new
   kind, **`kind: scenario`**: `mode.yaml` and `field.lua`, no
   `node.lua`, no roles of its own. It leads the composed id and is
   followed by a new **built-in role package, `org.atalaia.objectives`**
   (`objective`: capture and hold without local scoring, a keypad code,
   tags to scan; `bomb_site`: arm, defuse and explode without local
   scoring), e.g. `org.club.foxhound+org.atalaia.objectives`. The
   controller's joins already name "what that box runs", so a box's
   join names only `org.atalaia.objectives`. The scenario's `field.lua`
   tells each node what it is for at the start with a mode command
   (`field.send(id, "mode", { name = "setup", ... })`), and again when
   the node reboots, as the Medic Kit's `heals` does. The example
   generated Lua above (`on(...)` with `nodes["box-b"]`,
   `teams["bravo"]`, `e.data.objective`) is replaced by code against the
   real field API (`field.nodes(role)` returns `{id, ...}` tables,
   `field.owner(id)` a team name, events carry `node` and `team`).
2. **Names** (P4R8). Teams are the game's team names (the colours the
   boxes and the radio use); squads are numbers, 1 to the game's
   `squads`; nodes are names the GM assigns in the console's Join tab,
   mapped to node ids at join time; objective ids are
   `[a-z][a-z0-9_]{0,23}`; texts (objective names and descriptions) are
   in the package in English with `i18n.pt`, never in events.
3. **Events and data.** Scenario events carry `objective` (key 34)
   and the team and squad in the envelope; `scenario.started` carries
   `scenario` (key 35, the package id). Points are whole numbers
   (`score.add` refuses fractions), and generated Lua escapes every
   string it embeds.
4. **Visibility** (P4R24). The controller routes objective events on
   the stream to the assigned team and squad, all of them to staff; a
   hidden objective is never sent before its reveal. The app shows the
   translated names from the package.
5. **Validation** (P4R9). Structural checks (unique ids, references, a
   DAG, required parameters, time windows, zone geometry, teams and
   squads that exist, every event under 200 bytes) in the shared
   library; the generated `field.lua` loaded in the C core, as the
   controller's `modes.install()` does, on the controller and on the
   site server (whose image builds the core in a build stage). The
   controller checks again when it installs a scenario and stays the
   authority.
6. **Escort and survive** use what phase 3 built: `escort` takes the
   VIP's `position.fix` (ADR-P4-9's amendment) or a payload prop's
   `vip.extracted`; `survive` reads Respawn and Lives' `player.respawn`
   (`lives_left`) and `team.eliminated`.
7. **Library layout:** `controller/atalaia_controller/scenarios/`
   (`manifest.py`, `validator.py`, `lua.py`, `package.py`,
   `__main__.py` for `python3 -m atalaia_controller.scenarios`), pure
   Python (standard library and PyYAML), AGPL-3.0-or-later like the rest
   of `controller/`.

*Built 2026-10-20 (plan phase 20; decisions S20-1 to S20-8, proposed):* the
site server's scenario library (`/api/v1/fields/{field}/scenarios`) checks a
manifest with this library and the core's load check (P4R9) and keeps every
save as a revision; `GET /api/v1/sync/presets` gives every controller of the
field the library (and the field's game presets), and `GET
/api/v1/sync/scenarios/{id}` one manifest. The controller installs what
changed with its own install, checking it again (it stays the authority), so a
standby has the scenario too (M8-3).

---

### ADR-P4-7: ATAK / CoT integration

**Status:** Accepted

**Context:** The spec (section 11) says "the controller emits Cursor-
on-Target messages so props and zone owners appear on ATAK maps." ATAK
uses the CoT XML format (MIL-STD-2045 origin). Phase 4 builds a CoT
emitter on the controller; no ATAK SDK licence is required for CoT
emission (RESEARCH.md section 10).

**Decision:**

**CoT emitter:** A Python module on the controller
(`controller/atalaia_controller/atak.py`) that subscribes to game
events and node STATE messages and emits CoT XML.

**CoT message template:**

```python
COT_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0"
       uid="{uid}"
       type="{cot_type}"
       time="{time}"
       start="{start}"
       stale="{stale}"
       how="{how}">
  <point lat="{lat}" lon="{lon}" hae="{hae}" ce="{ce}" le="{le}"/>
  <detail>
    <contact callsign="{callsign}"/>
    <remarks>{remarks}</remarks>
    <__group name="{group_name}" role="{group_role}"/>
    <status battery="{battery}"/>
    <track course="{course}" speed="{speed}"/>
  </detail>
</event>"""
```

**CoT type mapping:**

| Entity | CoT type | how | Description |
|--------|----------|-----|-------------|
| Prop (uncaptured) | `a-n-G-E-X` | `m-g` | Neutral ground equipment |
| Prop (team-owned) | `a-f-G-E-X` | `m-g` | Friendly ground equipment (coloured by team) |
| Player (own team) | `a-f-G-U-C` | `h-g-i-g-o` | Friendly ground unit (GPS from app) |
| VIP | `a-f-G-U-C-V` | `h-g-i-g-o` | Friendly ground unit, VIP marker |
| Zone boundary | `u-d-f` | `h-e` | Drawing / feature (polygon) |
| Extraction point | `b-m-p-s-p-i` | `h-e` | Point of interest |
| Spawn point | `b-m-p-s-p-i` | `h-e` | Point of interest |

The `__group` element sets the team colour in ATAK:

| Team colour | `__group name` |
|-------------|---------------|
| Red | `Red` |
| Blue | `Blue` |
| Green | `Green` |
| Yellow | `Yellow` |
| Custom | Hex colour in `remarks` |

**UID format:** `atalaia-{node_name}-{node_id}` for props,
`atalaia-player-{user_id_short}` for players. The UID is stable across
game restarts so ATAK tracks the same marker.

**Staleness:** Each CoT message has a `stale` time set to `start + 2 *
update_interval`. If no update arrives before the stale time, ATAK
dims the marker. Default update interval: 30 seconds for props, 10
seconds for VIP players.

**Transport:**

| Transport | Port | When |
|-----------|------|------|
| UDP multicast | `239.2.3.1:6969` | Primary; ATAK default; field Wi-Fi |
| TCP unicast | `4242` | Secondary; for remote ATAK clients via site server |

```python
import socket

class CotEmitter:
    def __init__(self, multicast_group="239.2.3.1", port=6969,
                 tcp_host=None, tcp_port=4242):
        # UDP multicast
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                       socket.IPPROTO_UDP)
        self.udp_sock.setsockopt(socket.IPPROTO_IP,
                                  socket.IP_MULTICAST_TTL, 2)
        self.multicast_addr = (multicast_group, port)

        # Optional TCP for remote
        self.tcp_sock = None
        if tcp_host:
            self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_sock.connect((tcp_host, tcp_port))

    def emit(self, cot_xml: str):
        """Send a CoT message via UDP multicast and optionally TCP."""
        data = cot_xml.encode("utf-8")
        self.udp_sock.sendto(data, self.multicast_addr)
        if self.tcp_sock:
            # TAK Server protocol: 4-byte length prefix
            self.tcp_sock.sendall(len(data).to_bytes(4, "big") + data)
```

**Update frequency:**

| Entity | Interval | Triggered by |
|--------|----------|-------------|
| Props (static) | 30 s | STATE message or timer |
| Props (owner change) | Immediate | `zone.captured` event |
| VIP player | 10 s | `gps.fix` event from player app |
| Zone boundaries | Once at game start | Game configuration |
| Extraction points | Once at game start | Scenario definition |

**Configuration:**

The CoT emitter is enabled via environment variable or controller
config:

```python
# controller config
ATAK_ENABLED = True
ATAK_MULTICAST_GROUP = "239.2.3.1"
ATAK_MULTICAST_PORT = 6969
ATAK_TCP_HOST = None  # set for remote relay via site server
ATAK_TCP_PORT = 4242
ATAK_UPDATE_INTERVAL_S = 30
ATAK_VIP_UPDATE_INTERVAL_S = 10
```

**Site server relay for remote ATAK:**

The site server can relay CoT messages to remote ATAK clients via TCP.
The controller pushes CoT XML to the site server via the sync WebSocket
(tagged as `type: "cot"`), and the site server forwards to connected
ATAK clients on TCP port 4242. This enables marshals or command staff
off-site to see the game on ATAK.

**TAK Server compatibility (future):**

A full TAK Server integration is out of scope for Phase 4. The TCP
transport uses the same framing as TAK Server's raw CoT input, so a
field that runs TAK Server can point the controller at it. This is
documented but not tested in Phase 4.

**Consequences:**
- CoT emission is a consumer of existing data. It adds no new protocol
  messages and does not modify game logic.
- UDP multicast works on any standard Wi-Fi network. No ATAK plugin or
  SDK is needed.
- The 30-second update interval for static props is low-bandwidth
  (~200 bytes/message * 20 props * 2/min = ~8 KB/min).
- Remote ATAK via the site server adds latency (4G round-trip) but
  is acceptable for situational awareness (not real-time game control).
- TAK Server compatibility is a future extension, not a Phase 4
  requirement.

**Amendment 2026-10-19 (after phase 3 software; decision P4R18,
proposed):**

- **No `gps.fix` events exist** (the table's "VIP player ... `gps.fix`
  event" row is superseded). Player positions arrive at the controller
  with `POST /api/v1/positions` and are kept there, filtered by role
  (ADR-P3-6, phase 3 constraint 9).
- **Multicast carries props and zones only.** Anyone on the field
  Wi-Fi can read a multicast group, so player positions are never
  multicast. They go only to staff ATAK endpoints the GM lists
  (`[atak] staff_endpoints`, TCP, off by default with `players =
  false`), and only positions the staff roles may see.
- **Where props are.** Field Boxes have no GPS (E21); the GM places
  nodes on the field image (positions 0-1, `PUT /api/v1/games/{id}/positions/{node}`).
  The GM georeferences the image by giving two of its corners a
  latitude and longitude (`PUT /api/v1/field/georef`, store schema 5);
  the emitter converts image positions to coordinates. An Android
  prop with GPS may give its own.
- **Remote ATAK through the site server** forwards props and zones
  only, over the controller's sync WebSocket (ADR-P4-3's amendment).
  *(2026-10-20, plan phase 19: not built. The stream exists, but the
  relay needs an internet-facing endpoint for ATAK clients, and raw
  CoT on TCP 4242 has no authentication; it waits for a design with
  client certificates, as TAK's TLS streaming has, decision S19-10,
  which answers M9-10.)* *(2026-10-21, Phase 4 follow-up, decisions
  FU5-1 to FU5-12: built that way. The controller pushes its events
  on the stream it opens (`[atak] remote = true`, off by default),
  the site server relays them over TLS on port 8089 with a client
  certificate per device, issued by the field's admin or gm from a
  per-field CA whose key is kept sealed; never raw CoT on 4242.
  Props and zones to every enrolled device of the field; player
  positions only with `remote_players = true` on the controller and
  only to a certificate of a gm or a marshal issued with positions,
  which amends "props and zones only" above.)*
- **Configuration** is the controller's TOML (`[atak] enabled = false`,
  `multicast = "239.2.3.1:6969"`, `interval_s = 30`,
  `staff_endpoints = []`, `players = false`), overridable as
  `ATALAIA_ATAK_*`, not module constants.
- CoT XML text is escaped (team display names and node names come from
  users), and the samples in the tests are taken from the CoT
  documentation, not from the emitter's own output.

---

### ADR-P4-8: GDPR implementation

**Status:** Accepted

**Context:** The field operator is the data controller; the hosted hub
is a data processor. Portugal's CNPD is the supervisory authority.
GDPR and Lei 58/2019 apply. The spec (section 14) requires export,
delete and retention. The research (section 5) identified the specific
rights and implementation needs.

**Decision:**

**Lawful basis:**

| Data category | Lawful basis | Notes |
|--------------|-------------|-------|
| Account (email, username) | Consent (Art. 6(1)(a)) | Explicit at registration |
| Game events and scores | Legitimate interest (Art. 6(1)(f)) | Necessary for game operation |
| Positions (GPS) | Consent (Art. 6(1)(a)) | Separate consent; deleted after game archive |
| Chrono records | Legitimate interest (Art. 6(1)(f)) | Safety enforcement |
| Chrono cross-field sharing | Consent (Art. 6(1)(a)) | Separate, granular consent |

**Data subject rights -- API endpoints:**

| GDPR right | Endpoint | Behaviour |
|------------|----------|-----------|
| Access (Art. 15) | `GET /api/v1/me/data` | Returns all personal data as JSON |
| Erasure (Art. 17) | `DELETE /api/v1/me` | Anonymises; see below |
| Portability (Art. 20) | `GET /api/v1/me/export` | Returns ZIP file |
| Rectification (Art. 16) | `PATCH /api/v1/me` | Update profile fields |

**Access response (`GET /api/v1/me/data`):**

```json
{
  "user": {
    "id": "...",
    "username": "player42",
    "email": "player@example.com",
    "created_at": "2026-01-15T10:00:00Z",
    "gdpr_consent_at": "2026-01-15T10:00:05Z"
  },
  "games": [
    {
      "game_id": "...",
      "field": "Campo Tejo",
      "date": "2026-03-01",
      "mode": "Domination",
      "team": "red",
      "score": 450
    }
  ],
  "chrono_records": [
    {
      "replica": "AEG M4 #TAG-A1B2",
      "field": "Campo Tejo",
      "date": "2026-03-01",
      "readings": [{"velocity_mps": 98.2, "bb_weight_g": 0.20, "energy_j": 0.96}],
      "result": "pass"
    }
  ],
  "consents": {
    "account": { "given_at": "2026-01-15T10:00:05Z" },
    "chrono_sharing": {
      "given_at": "2026-02-01T09:00:00Z",
      "fields": ["Campo Tejo", "Arena Norte"]
    }
  }
}
```

**Export format (`GET /api/v1/me/export`):**

A ZIP file containing:
```
export/
    profile.json          # user data
    games.json            # game history with scores
    chrono_records.json   # all chrono records
    events.json           # game events the user was involved in
    consents.json         # consent records
    README.txt            # explains the format and how to import
```

All files are JSON (machine-readable, per Art. 20). The README.txt
explains each file's schema.

**Erasure (`DELETE /api/v1/me`):**

Erasure is anonymisation, not physical deletion, because some data
must be retained for game integrity:

```python
async def anonymise_user(user_id: UUID, db: AsyncSession):
    # 1. Anonymise the user record
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            username=f"deleted-{uuid4().hex[:8]}",
            email=None,
            password_hash="DELETED",
            totp_secret_enc=None,
            totp_enabled=False,
            gdpr_consent_at=None,
        )
    )

    # 2. Anonymise chrono records (retain marshal signature and readings
    #    for game integrity, but remove player identity)
    await db.execute(
        update(Replica)
        .where(Replica.owner_id == user_id)
        .values(owner_id=None, brand=None, model=None)
    )

    # 3. Anonymise game participation
    await db.execute(
        update(UserGameRole)
        .where(UserGameRole.user_id == user_id)
        .values(user_id=ANONYMOUS_USER_ID)  # a sentinel UUID
    )

    # 4. Delete sessions
    await db.execute(
        delete(Session).where(Session.user_id == user_id)
    )

    # 5. Delete player profiles and stats
    await db.execute(
        delete(PlayerProfile).where(PlayerProfile.user_id == user_id)
    )
    await db.execute(
        delete(PlayerStats).where(PlayerStats.user_id == user_id)
    )

    # 6. Log the deletion in the audit log
    await db.execute(
        insert(AuditLog).values(
            user_id=None,  # anonymised
            action="gdpr_erasure",
            resource="user",
            resource_id=user_id,
            details={"reason": "user_request"},
        )
    )
```

**Retention policies:**

| Data | Default retention | Configurable | Purge mechanism |
|------|-------------------|-------------|----------------|
| Chrono records | 12 months | Per field (`fields.default_retention_days`) | Cron job |
| Positions (GPS) | Deleted on game archive | Per game | Game archive process |
| Game history | 24 months | Per field | Cron job |
| Guest player data | 30 days after game | Fixed | Cron job |
| Audit log | 36 months | Per field | Cron job |
| Sessions (expired) | 30 days after expiry | Fixed | Cron job |

**Retention purge job:**

```python
# Runs daily at 03:00 UTC (configurable)
async def retention_purge():
    now = datetime.utcnow()

    # Chrono records past retention
    await db.execute(
        delete(ChronoRecord)
        .where(
            ChronoRecord.recorded_at < now - timedelta(
                days=field.default_retention_days
            )
        )
    )

    # Guest players (no account) past 30 days
    await db.execute(
        text("""
            DELETE FROM user_game_roles ugr
            USING users u
            WHERE ugr.user_id = u.id
              AND u.password_hash = 'GUEST'
              AND ugr.created_at < :cutoff
        """),
        {"cutoff": now - timedelta(days=30)},
    )

    # Expired sessions
    await db.execute(
        delete(Session)
        .where(Session.expires_at < now - timedelta(days=30))
    )
```

**Privacy notice template:**

Shipped in `docs/templates/privacy-notice-pt.md` (Portuguese) and
`docs/templates/privacy-notice-en.md` (English). Covers:

1. Identity of the data controller (field operator -- placeholder for
   the operator to fill).
2. Categories of data collected.
3. Legal basis per category.
4. Retention periods.
5. Rights (access, rectification, erasure, portability, objection).
6. Contact for the field's DPO (if appointed).
7. Right to lodge a complaint with the CNPD (Comissao Nacional de
   Proteccao de Dados, Av. D. Carlos I 134, 1200-651 Lisboa).
8. Cross-field chrono sharing: which fields, and how to withdraw
   consent.

**Data Processing Agreement (hosted mode):**

A template DPA is shipped in `docs/templates/dpa-template.md`. It
establishes:

- The field operator as data controller, the project as data processor.
- The processor processes data only on documented instructions.
- Sub-processors (hosting provider) are listed.
- Security measures (encryption at rest and in transit, access
  controls).
- Breach notification within 48 hours to the controller (who then
  notifies the CNPD within 72 hours per Art. 33).
- Data return and deletion on contract end.

**Maintainer review recommended:** The privacy notice and DPA templates
should be reviewed by a Portuguese lawyer familiar with GDPR/Lei
58/2019 before the hosted service goes live. The templates are
functional drafts based on standard GDPR processor agreements.

**Consequences:**
- Erasure is anonymisation: chrono records and game events retain their
  integrity (marshal signatures remain valid) but lose the link to the
  individual.
- Retention is configurable per field, with sensible defaults. The
  daily purge job runs at low-traffic hours.
- The export ZIP is self-contained and machine-readable, satisfying
  Art. 20's portability requirement.
- The DPA template makes the hosted service GDPR-ready from launch,
  though legal review is recommended.
- Guest players are automatically cleaned up after 30 days.

**Amendment 2026-10-19 (after phase 3 software; decision P4R25,
proposed):**

- **Positions never reach the site server.** The controller keeps
  them for the live game only and deletes them when it ends; the sync
  carries none. The "Positions (GPS)" rows above (consent, "deleted on
  game archive", in the access response) are superseded: there is
  nothing to export or delete on the site server. A remote GM sees
  positions live through the controller's link only when the field
  turns `remote_gm` on.
- **Data that arrives from controllers** is per-field and
  pseudonymous: `player_id` (`p-` + 12 base32), replicas, signed chrono
  readings, check-in outcomes. Names and federation numbers stay on the
  controller (30 days, decision F11) except what ADR-P4-11 sends back
  for registered players. Chrono records keep their signature on
  erasure; the link to the person (the account and the adopted
  `player_id`) is what erasure removes.
- **Retention aligned with the controller:** chrono and field
  identities 365 days (the controller's `CHRONO_RETENTION_DAYS` and
  `IDENTITY_DAYS`, decision B12), check-in data 30 days after the game.
- **Rule for the implementation:** each plan phase that adds a table
  with personal data adds it to access, export, erasure and the purge
  in the same commit.

*Built 2026-10-19 (plan phase 12; decisions S12-1 to S12-8, proposed):*
the four endpoints as above, plus `POST /api/v1/me/password`; changes and
erasure need the current password (and a TOTP code to erase an account that
has TOTP). Erasure is the anonymisation above for the tables that exist
(the `users` row as a `deleted-...` tombstone; field roles, sessions and
consent records deleted; the person's audit rows kept without their
addresses; the erasure logged with no account and no address).
Consents are records in a `consents` table with the privacy notice's
version, not only `users.gdpr_consent_at`. The purge (sessions 30 days after
they end, the audit log after 36 months, server-wide) runs inside the
server daily at `ATALAIA_PURGE_HOUR` (03:00 UTC) and as `python -m
atalaia_server purge`. The templates are in `docs/templates/`. The list of
personal data tables lives in `server/atalaia_server/personal_data.py`.
*(2026-10-20, plan phase 14, S14-8: the chrono registry joined it. Access
and export add `player_ids.json`, `chrono_records.json` (each record as
signed, with the marshal's public key) and `marshal_keys.json`; erasure keeps
the signed records and deletes the account's links to its per-field player
ids (`field_player_ids`), clears the make, model and tag of its replicas and
unlinks its marshal keys; the purge removes readings after the field's
`default_retention_days` (365).)*

---

### ADR-P4-9: Geo utilities in the script API

**Status:** Accepted

**Context:** The VIP / Payload mode (RESEARCH.md section 9.3) needs
`geo.distance()` and `geo.in_zone()` in the Lua script API. These are
general-purpose geo functions useful for any mode that works with GPS
coordinates (extraction zones, geofencing, area-based scoring).

**Decision:**

**Two new functions in the `geo` table, registered in `script_api.c`:**

```c
/* geo.distance(lat1, lon1, lat2, lon2) -> metres */
static int l_geo_distance(lua_State *L) {
    double lat1 = luaL_checknumber(L, 1) * DEG_TO_RAD;
    double lon1 = luaL_checknumber(L, 2) * DEG_TO_RAD;
    double lat2 = luaL_checknumber(L, 3) * DEG_TO_RAD;
    double lon2 = luaL_checknumber(L, 4) * DEG_TO_RAD;

    /* Haversine formula */
    double dlat = lat2 - lat1;
    double dlon = lon2 - lon1;
    double a = sin(dlat / 2) * sin(dlat / 2)
             + cos(lat1) * cos(lat2) * sin(dlon / 2) * sin(dlon / 2);
    double c = 2 * atan2(sqrt(a), sqrt(1 - a));
    double d = 6371000.0 * c;  /* Earth radius in metres */

    lua_pushnumber(L, d);
    return 1;
}

/* geo.in_zone(lat, lon, zone) -> boolean
 * zone is a table: { type = "circle", lat, lon, radius_m }
 *                   or { type = "polygon", points = {{lat, lon}, ...} }
 */
static int l_geo_in_zone(lua_State *L) {
    double lat = luaL_checknumber(L, 1);
    double lon = luaL_checknumber(L, 2);
    luaL_checktype(L, 3, LUA_TTABLE);

    lua_getfield(L, 3, "type");
    const char *zone_type = luaL_checkstring(L, -1);
    lua_pop(L, 1);

    if (strcmp(zone_type, "circle") == 0) {
        lua_getfield(L, 3, "lat");
        double clat = luaL_checknumber(L, -1);
        lua_getfield(L, 3, "lon");
        double clon = luaL_checknumber(L, -1);
        lua_getfield(L, 3, "radius_m");
        double radius = luaL_checknumber(L, -1);
        lua_pop(L, 3);

        /* Reuse Haversine */
        double dist = haversine_m(lat, lon, clat, clon);
        lua_pushboolean(L, dist <= radius);
    } else if (strcmp(zone_type, "polygon") == 0) {
        lua_getfield(L, 3, "points");
        int n = luaL_len(L, -1);
        /* Ray-casting point-in-polygon */
        int inside = 0;
        for (int i = 1; i <= n; i++) {
            lua_rawgeti(L, -1, i);
            lua_rawgeti(L, -1, 1); double yi = lua_tonumber(L, -1);
            lua_rawgeti(L, -2, 2); double xi = lua_tonumber(L, -1);
            lua_pop(L, 3);

            int j = (i % n) + 1;
            lua_rawgeti(L, -1, j);
            lua_rawgeti(L, -1, 1); double yj = lua_tonumber(L, -1);
            lua_rawgeti(L, -2, 2); double xj = lua_tonumber(L, -1);
            lua_pop(L, 3);

            if (((yi > lat) != (yj > lat)) &&
                (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi)) {
                inside = !inside;
            }
        }
        lua_pop(L, 1); /* pop points table */
        lua_pushboolean(L, inside);
    } else {
        return luaL_error(L, "geo.in_zone: unknown zone type '%s'", zone_type);
    }

    return 1;
}
```

**Registration in `script_api.c`:**

```c
static const luaL_Reg geo_funcs[] = {
    {"distance", l_geo_distance},
    {"in_zone",  l_geo_in_zone},
    {NULL, NULL}
};

/* In atalaia_script_api_register(): */
luaL_newlib(L, geo_funcs);
lua_setglobal(L, "geo");
```

**Zone definition format:**

Zones are defined in mode parameters or scenario manifests and passed
to `geo.in_zone()` as Lua tables:

```lua
-- Circle zone (extraction point with 15 m radius)
local extraction = {
    type = "circle",
    lat = 38.7223,
    lon = -9.1393,
    radius_m = 15,
}

-- Polygon zone (irregular area defined by vertices)
local safe_zone = {
    type = "polygon",
    points = {
        {38.7220, -9.1400},
        {38.7225, -9.1395},
        {38.7228, -9.1398},
        {38.7224, -9.1405},
    },
}

-- Usage in field.lua:
on("gps.fix", function(e)
    if geo.in_zone(e.lat, e.lon, extraction) then
        emit("vip.extracted", { team = "alpha" })
    end
end)
```

**Accuracy considerations:**

- Haversine is accurate to within ~0.5% for distances under 20 km.
  Game distances are typically 10-500 m; Haversine is exact for these.
- The ray-casting algorithm works for simple (non-self-intersecting)
  polygons. Self-intersecting polygons produce undefined results. The
  scenario validator (ADR-P4-6) rejects self-intersecting polygons.
- GPS accuracy outdoors is typically 3-10 m. Circle zones should have
  a minimum radius of 10 m to avoid false negatives. The scenario
  compiler warns if `radius_m < 10`.

**Availability:**

The `geo` table is always registered (not gated by `field_ops`). Both
`node.lua` and `field.lua` scripts can use `geo.distance()` and
`geo.in_zone()`. This enables node-level modes like "proximity alert
when two nodes are within 50 m."

**Tests:**

```c
/* test_geo.c */
void test_haversine_lisbon_to_porto(void) {
    /* Lisbon (38.7223, -9.1393) to Porto (41.1579, -8.6291) */
    double d = haversine_m(38.7223, -9.1393, 41.1579, -8.6291);
    assert(fabs(d - 274000.0) < 1000.0);  /* ~274 km +/- 1 km */
}

void test_in_zone_circle(void) {
    /* Point inside a 15 m circle */
    assert(in_zone_circle(38.7223, -9.1393, 38.7223, -9.1393, 15.0));
    /* Point outside */
    assert(!in_zone_circle(38.7230, -9.1393, 38.7223, -9.1393, 15.0));
}

void test_in_zone_polygon_square(void) {
    /* Point inside a square */
    double points[][2] = {{0,0}, {0,1}, {1,1}, {1,0}};
    assert(in_zone_polygon(0.5, 0.5, points, 4));
    /* Point outside */
    assert(!in_zone_polygon(1.5, 0.5, points, 4));
}
```

**Core version:** The `geo` table is a minor addition. The core version
remains at the Phase 2 bump (0.2.x) if no other changes warrant a new
minor version; otherwise it is included in the next minor bump.

**Consequences:**
- `geo.distance()` and `geo.in_zone()` are available in all scripts,
  enabling location-aware modes beyond VIP / Payload.
- The functions are implemented in C (in the core) for performance,
  but the math is simple enough that a pure-Lua fallback would also
  work.
- Circle zones are the common case and are cheap (one Haversine call).
  Polygon zones are O(n) in vertices.
- The `geo` table is stateless and has no sandbox implications (no
  I/O, no memory allocation beyond the stack).

**Amendment 2026-10-19 (after phase 3 software; decision P4R6,
proposed):**

- **Where coordinates come from.** The usage example's
  `on("gps.fix", ...)` in `field.lua` is superseded: no such event
  exists, and an event would put a player's position on the radio. The
  controller hands its field script a controller-only input,
  `position.fix` (`player`, `team`, `role`, `lat`, `lon`, `acc`, `src`),
  for the reports of players whose role the mode asks for (the VIP).
  It is never logged, emitted, sent on the radio, MQTT or the stream,
  or kept in `state.field` (which a standby controller receives). On an
  Android prop with a `gps` capability, the app's location service gives
  `node.lua` the input `gps.fix` (`lat`, `lon`, `acc`), so a payload
  prop checks its own zone and emits only the outcome.
- **No coordinates in events:** no event has `lat` or `lon` data keys,
  so the simulator's schema checks refuse a script that tries.
- **Polygons** take at most 32 vertices; the functions raise a Lua
  error (reported as `script.error`) on bad arguments.
- **Vectors:** `protocol/vectors/geo.json` (distances computed with an
  independent tool, zone cases) are checked by the C tests and the
  simulator; the Dart side uses the core, so it gets the same results.

---

### ADR-P4-10: Site server deployment

**Status:** Accepted

**Context:** The site server ships as a container setup. It must be
deployable by a field operator with basic Docker knowledge (spec section
11: "one container setup, application plus PostgreSQL"). The research
identified docker-compose with two services as the deployment model
(RESEARCH.md section 4).

**Decision:**

**docker-compose.yml:**

```yaml
version: "3.8"

services:
  atalaia-server:
    image: atalaia/site-server:${ATALAIA_VERSION:-latest}
    build:
      context: .
      dockerfile: server/Dockerfile
    ports:
      - "${ATALAIA_PORT:-8443}:8000"
    environment:
      DATABASE_URL: "postgresql+asyncpg://atalaia:${POSTGRES_PASSWORD}@postgres:5432/atalaia"
      SECRET_KEY: "${SECRET_KEY}"
      REFRESH_SECRET: "${REFRESH_SECRET}"
      HOSTED_MODE: "${HOSTED_MODE:-false}"
      ALLOWED_ORIGINS: "${ALLOWED_ORIGINS:-*}"
      LOG_LEVEL: "${LOG_LEVEL:-info}"
    volumes:
      - app-data:/app/data      # uploads, maps, mode packages
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://localhost:8000/api/v1/health')"]
      interval: 30s
      timeout: 5s
      retries: 3

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: atalaia
      POSTGRES_PASSWORD: "${POSTGRES_PASSWORD}"
      POSTGRES_DB: atalaia
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U atalaia"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
  app-data:
```

**Dockerfile (server/Dockerfile):**

```dockerfile
FROM python:3.11-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/src/ ./src/
COPY server/migrations/ ./migrations/
COPY server/alembic.ini .

EXPOSE 8000

# Run migrations then start the server
CMD ["sh", "-c", "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port 8000"]
```

**Reverse proxy and TLS:**

The docker-compose setup listens on port 8000 (HTTP) internally. TLS
termination is handled by a reverse proxy in front of it. Two supported
options:

**Option A: Caddy (recommended for simplicity):**

```
# Caddyfile
atalaia.example.com {
    reverse_proxy atalaia-server:8000
    # Automatic HTTPS with Let's Encrypt
}
```

Add Caddy to docker-compose:

```yaml
  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy-data:/data
      - caddy-config:/config
    depends_on:
      - atalaia-server
```

**Option B: nginx (for operators already using it):**

```nginx
server {
    listen 443 ssl http2;
    server_name atalaia.example.com;

    ssl_certificate /etc/letsencrypt/live/atalaia.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/atalaia.example.com/privkey.pem;
    ssl_protocols TLSv1.3;

    location / {
        proxy_pass http://atalaia-server:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/v1/sync/stream {
        proxy_pass http://atalaia-server:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

**Security headers (applied by FastAPI middleware):**

```python
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self' wss://*"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
```

**Backup strategy:**

```bash
#!/bin/bash
# backup.sh -- run daily via cron
set -euo pipefail

BACKUP_DIR="/backups/atalaia"
DATE=$(date +%Y%m%d_%H%M%S)
RETAIN_DAYS=30

mkdir -p "$BACKUP_DIR"

# Database backup
docker exec atalaia-postgres-1 \
    pg_dump -U atalaia -Fc atalaia \
    > "$BACKUP_DIR/db_${DATE}.dump"

# Application data backup
tar czf "$BACKUP_DIR/data_${DATE}.tar.gz" \
    -C /var/lib/docker/volumes/atalaia_app-data/_data .

# Prune old backups
find "$BACKUP_DIR" -name "*.dump" -mtime +${RETAIN_DAYS} -delete
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +${RETAIN_DAYS} -delete

echo "Backup complete: db_${DATE}.dump + data_${DATE}.tar.gz"
```

**Restore:**

```bash
# Stop the server
docker compose stop atalaia-server

# Restore database
docker exec -i atalaia-postgres-1 \
    pg_restore -U atalaia -d atalaia --clean --if-exists \
    < /backups/atalaia/db_20261017_030000.dump

# Restore application data
tar xzf /backups/atalaia/data_20261017_030000.tar.gz \
    -C /var/lib/docker/volumes/atalaia_app-data/_data

# Run migrations (in case the backup is from an older version)
docker compose run --rm atalaia-server alembic upgrade head

# Start the server
docker compose up -d
```

**Environment file (.env):**

```bash
# .env (NOT committed to the repo; generated during setup)
POSTGRES_PASSWORD=<generated-by-setup-script>
SECRET_KEY=<generated-by-setup-script>
REFRESH_SECRET=<generated-by-setup-script>
ATALAIA_VERSION=latest
ATALAIA_PORT=8443
HOSTED_MODE=false
ALLOWED_ORIGINS=https://atalaia.example.com
LOG_LEVEL=info
```

**Setup script:**

```bash
#!/bin/bash
# setup.sh -- first-time site server setup
set -euo pipefail

echo "Atalaia Site Server Setup"
echo "========================"

# Generate secrets
POSTGRES_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
REFRESH_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

cat > .env <<EOF
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
SECRET_KEY=${SECRET_KEY}
REFRESH_SECRET=${REFRESH_SECRET}
ATALAIA_VERSION=latest
ATALAIA_PORT=8443
HOSTED_MODE=false
ALLOWED_ORIGINS=*
LOG_LEVEL=info
EOF

echo "Secrets generated and saved to .env"
echo "Starting services..."

docker compose up -d

echo ""
echo "Site server is starting. Check status with: docker compose ps"
echo "Create the first admin user with:"
echo "  docker compose exec atalaia-server python -m src.cli create-admin"
```

**Resource requirements:**

| Deployment | RAM | CPU | Disk |
|-----------|-----|-----|------|
| Single field (self-hosted, mini PC) | 512 MB | 1 vCPU | 5 GB |
| Single field (VPS) | 1 GB | 1 vCPU | 10 GB |
| Hosted hub (10 fields) | 2 GB | 2 vCPU | 20 GB |
| Hosted hub (100 fields) | 4 GB | 4 vCPU | 100 GB |

**Monitoring:**

The site server exposes `/api/v1/health` (public, no auth) and
`/api/v1/metrics` (admin auth) for monitoring:

```json
// GET /api/v1/health
{
  "status": "healthy",
  "database": "connected",
  "version": "0.1.0",
  "uptime_s": 86400
}

// GET /api/v1/metrics
{
  "active_users_24h": 42,
  "games_today": 3,
  "events_total": 12500,
  "sync_last_success": "2026-10-17T14:30:00Z",
  "db_pool_size": 5,
  "db_pool_available": 3
}
```

**Consequences:**
- A field operator with Docker experience can deploy the site server
  in under 15 minutes (clone, run setup.sh, configure DNS).
- Caddy provides automatic HTTPS with zero configuration beyond a
  domain name.
- The backup script runs `pg_dump` in custom format, which supports
  selective restore and is more robust than SQL dumps.
- The .env file contains all secrets. It is generated by the setup
  script and never committed to version control.
- Resource requirements are modest: a $5/month VPS can run a single-
  field site server.
- The health endpoint enables uptime monitoring with any standard
  tool (UptimeRobot, cron+curl, Prometheus blackbox exporter).

**Amendment 2026-10-19 (after phase 3 software; decisions P4R9, P4R16,
P4R17, proposed):**

- **Image:** `python:3.12-slim` (CI and Ubuntu 24.04 use 3.12), with
  `server/requirements.txt` pinned with hashes (made from
  `server/requirements.in`); a first build stage compiles the core
  (`libatalaia_core.so`) so the site server can load a scenario's
  `field.lua` as the controller does; the final image has no compiler.
  The image also copies the shared pure-Python code it imports
  (`controller/atalaia_controller/` and `simulator/atalaia_sim/`), so
  the build context is the repository root.
- **Package:** `server/atalaia_server/` (not `server/src/`), started as
  `uvicorn atalaia_server.app:app`; the CLI is `python -m
  atalaia_server` (`create-admin`, `purge`, `rotate-secrets`).
- **Not the atalaia-dev stack.** The dev image's Ubuntu packages are
  FastAPI 0.101 with pydantic 1.10 and no SQLAlchemy 2; the site server
  pins its own versions. The controller keeps the Raspberry Pi OS
  generation (decision D15).
- **Tests** use `unittest` against PostgreSQL 16: a `postgres:16-alpine`
  service container in a new CI job `server`, and locally an ephemeral
  container from `server/docker-compose.test.yml`, driven by a new
  `tools/docker_server.py` (P4R17).
- The Compose file's obsolete `version:` key is dropped, and the health
  check uses the standard library (`python -c "import urllib.request
  ..."`) so the image does not need httpx.
- *Built 2026-10-19 (plan phase 10):* the server starts with
  `uvicorn --factory atalaia_server.app:create_app` rather than
  `atalaia_server.app:app`, and the settings are `ATALAIA_*` variables
  (`ATALAIA_DATABASE_URL`, ...) rather than this ADR's `DATABASE_URL`;
  decisions S10-1 and S10-7, proposed.
- *Built 2026-10-20 (plan phase 22; decisions S22-1 to S22-10, proposed):*
  Caddy is in `server/docker-compose.yml` (not an option) and the only
  container with published ports; the server and PostgreSQL are on internal
  networks; nginx (option B) is not provided. `server/setup.sh` makes the
  real `ATALAIA_*` settings (no `REFRESH_SECRET`, `HOSTED_MODE`,
  `ALLOWED_ORIGINS`); backups are encrypted (AES-256-GCM, the key in `.env`)
  and there is no `app-data` volume (everything is in the database); the
  restore is `server/restore.sh`, into a freshly created database. The
  operator's guide is `server/docs/DEPLOY.md`.

---

### ADR-P4-11: Game scheduling, publication and registration

**Status:** Proposed (2026-10-19, maintainer request; decisions
F13-F17 in `docs/review/decisions-to-review.md`, all open)

**Context:** The maintainer asked that a "field admin can schedule
games (and it may be published to the field server page - if they have
one) or shared/third-party platforms ... which would allow players to
register to the games".  ADR-P4-1 already has `scheduled_games` and
`game_registrations` tables, and ADR-P4-3 a roster pull
(`GET /api/v1/sync/roster`), but nothing says how a game is published,
who may register, what a registration holds, or how it reaches the
field controller.  Phase 3's ADR-P3-13 designs the game-day part: the
check-in poster, check-in at the controller, the per-game replica
declaration and the "replicas to chrono" list.  This ADR feeds that list
from the site server.  The field controller stays the authority during
the game, and a field without a site server loses nothing it had.

**Decision:**

#### Scheduling

A user with the `admin` or `gm` role on a field creates a scheduled
game: title, description, start and estimated end (stored in UTC,
shown in the field's time zone, `fields.timezone`), mode or preset or
scenario (optional: many games are announced before the GM picks one),
teams, `max_players`, registration window (`registration_opens_at`,
`registration_closes_at`), the federation requirement (`off`,
`optional`, `required`, with the field's label, as ADR-P3-13), and
whether replicas are pre-declared at registration (default on).

Statuses stay ADR-P4-1's: `draft` (only staff see it), `published`
(on the field page and the feeds), `registering` (published with the
window open; computed from the window rather than set by hand),
`in_progress` (when the controller reports the start through
`POST /api/v1/sync/game`), `completed`, `cancelled` (stays visible as
cancelled, with a reason).  Only `admin` may publish or cancel.

#### Publication on the field page

The site server serves a public page per field,
`https://<site>/f/<slug>/`, rendered on the server (it works without
JavaScript): the field's name, an optional description and address,
and its upcoming published games; each game has its own page,
`/f/<slug>/games/<id>`, with the details, the places left, the
requirements and a *Register* button.  The pages show no registered
player's name or count beyond "places left".  A field turns its page
on or off (`fields.public_page`, default off).  In hosted mode each
field's page reads only its own schema (ADR-P4-4).  The open feeds
(ADR-P4-12) list the same games.

#### Registration

Online registration needs an account (ADR-P4-2): a player logs in on
the site server's web pages or in the app, opens a published game in
its window, and registers with:

- a display name for that game (from the profile's callsign by default);
- a team preference, if the game allows it;
- the federation number, if the game asks for one (never verified
  automatically, as ADR-P3-13);
- **pre-declared replicas**: picked from the player's replicas on the
  site server (`replicas`, ADR-P4-1) or described anew (type, class
  from the field's limit template, make and model), at most the field's
  `max_replicas`.  They become the game's declaration on the controller.

`max_players` is enforced; when the game is full, registration closes
(no waiting list in this version).  A player can change the
declaration or cancel until the window closes; staff can at any time.

**The player's id at the field.**  Each account has one pseudonymous
`player_id` per field (`field_player_ids`: user, field, `player_id`
of the ADR-P3-13 form), made on first registration there.  When a
player who already checked in at that field without an account (a
phase 3 field identity on the phone) links the account, the app sends
that id and its secret once and the site server adopts the id, so the
replica and chrono history continue.

**The check-in ticket.**  A registration gets a random 32-byte ticket
secret.  The site server stores its SHA-256, shows the secret once to
the player's app (and as a printable ticket: a QR code of
`atalaia:ticket:` with the base64url CBOR of
`{1: registration_id, 2: player_id, 3: secret}`), and sends the hash
in the roster.  It is not a game credential: it only lets the
controller match an arrival to a registration.

**Data:** ADR-P4-1's tables gain columns (one reversible Alembic
migration):

- `scheduled_games`: `ends_at`, `registration_opens_at`,
  `registration_closes_at`, `federation` (`off`/`optional`/`required`),
  `predeclare_replicas`, `location_text`, `published_at`,
  `cancelled_reason`, `ical_sequence` (ADR-P4-12), `controller_game_id`
  (filled when the controller links its game);
- `game_registrations`: `user_id` becomes nullable (imported
  registrations, ADR-P4-12); `player_id`, `display_name`, `status`
  (`registered`, `cancelled`, `checked_in`, `no_show`),
  `federation_number`, `ticket_hash`, `source` (`site`, `import`,
  `adapter:<id>`), `external_ref`, `updated_at`;
  `UNIQUE(scheduled_game_id, source, external_ref)`;
- new `registration_replicas` (`registration_id`, `declaration_id`,
  `replica_id` nullable, `type`, `class`, `make_model`);
- new `field_player_ids` (`user_id`, `field_id`, `player_id`,
  `UNIQUE(field_id, player_id)`);
- `fields`: `public_page`, `description`, `address_text`,
  `federation_label`.

#### Sync with the controller on game day

The controller pulls, as ADR-P4-3 says (the site server never pushes
game state):

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/sync/schedule?days=14` | New: the field's published games for the next days, so the GM can create the controller game "from the schedule" (the controller game then records `scheduled_game_id`, and the site server's `controller_game_id`) |
| GET | `/api/v1/sync/roster?game_id=` | ADR-P4-3's pull, now defined: per registration `registration_id`, `player_id`, `display_name`, `team_preference`, `federation_number` (when the game asks), `ticket_hash`, `status`, and the pre-declared replicas with their `declaration_id` |
| POST | `/api/v1/sync/checkins` | New: after the game (or in batches during it, when a link exists), each registration's outcome (`checked_in` or `no_show`), its declaration's final states and the deciding `reading_id`s; the readings themselves go through ADR-P4-3's `POST /api/v1/sync/chrono` |

On the controller the roster becomes **expected** check-ins, with
their declarations already in the "replicas to chrono" list as
`pending`, so marshals can prepare before anyone arrives.  At the
field a registered player scans the poster; the app sends the
registration id and ticket secret with the check-in (ADR-P3-13's
`POST /api/v1/checkin`), and the controller marks the expected
check-in as arrived.  A registered player without the app is ticked
by a marshal by name, or shows the printed ticket to the marshal's
scanner.

**Authority.**  The controller pulls the roster again until the game
starts: new registrations are added, cancelled ones that have not
checked in are removed, everything already checked in stays as the
controller has it.  Once the game starts the controller stops applying
roster changes for it; staff changes on the day (a walk-in, a team
change, a refusal) are the controller's and win.  Without internet on
the day the controller uses its last pull; with no pull at all, every
player is a walk-in (ADR-P3-13), and the app adds its registration id
to the check-in so the site server can match it when the controller
pushes later.

**Walk-ins** (checked in at the field, not registered) are pushed as a
count only, unless the field turns on `[sync] push_walkins`; then they
are stored as guest registrations under ADR-P4-8's 30-day guest rule.

#### Personal data

Registration data is part of the account's data: it appears in
`GET /api/v1/me/data` and the export, and erasure anonymises it
(ADR-P4-8).  The federation number on a registration is erased 30 days
after the game (it is kept on the profile only if the player saves it
there).  Registrations themselves follow the game history retention
(24 months, ADR-P4-8).  The roster sent to a controller holds only
what ADR-P3-13's check-in holds; the controller's 30-day rule then
applies to it.  The registration form states which data the field
gets and for how long; the notice is in the P4-6 legal review.

**Consequences:**
- A field can announce games on its own page and take registrations
  with pre-declared replicas, and marshals see the expected replicas
  before the gate opens.
- The controller remains the authority on the day and works from its
  last pull when the internet is gone; the site server never pushes
  into a running game.
- The roster carries only what the check-in list needs; walk-ins stay
  on the controller unless the field opts in.
- ADR-P4-1 gains one reversible migration and two small tables; ADR-
  P4-3 gains two endpoints and a defined roster payload.

**Amendment 2026-10-19 (re-checked against phase 3's check-in as built,
proposed):**

- The check-in this ADR feeds is built (`protocol/checkin.md`,
  `controller/atalaia_controller/checkin.py`, store schema 3-4). Its
  `player_id` form, the per-field secret (SHA-256 on the controller),
  the declarations (types including `sniper`, classes from the limit
  template, `max_replicas`, a lowercase-UUID `declaration_id`), the
  federation setting, the 30-day retention and `player.checkin` with
  the id only all match what this ADR assumed.
- What the controller gains: a check-in `status` of `expected` (next to
  `pending`, `checked_in`, `left`, `removed`), `registration_id` and
  `ticket` fields on `POST /api/v1/checkin`, and the `atalaia:ticket:`
  code, specified next to the poster in `protocol/checkin.md` with
  shared vectors for Python and Dart (plan phase 16).
- The roster and the check-in push follow ADR-P4-3's amendment: the
  controller pulls and pushes over its own connection; the site server
  never sends anything into a running game.

**Amendment 2026-10-20 (plan phase 16, as built; decisions S16-1 to
S16-14, open):**

- **Adopting a phone's id.** The site server cannot compare the phone's
  secret with the controller's SHA-256: it never receives the controller's
  hashes (protocol/sync.md's never-sent list). An account's claim keeps the
  SHA-256 of the secret the phone sends once; the controller pulls the
  field's claims (`GET /api/v1/sync/claims`), compares each with its own hash
  and answers `confirmed`, `refused` or `unknown` (`POST
  /api/v1/sync/claims`); only a confirmed claim becomes a
  `field_player_ids` link (S16-4).
- **The roster** is `GET /api/v1/sync/roster?scheduled_game_id=` and the
  schedule's horizon is `days` 1-60; both answers, and the claims', are
  checked on both sides by the shared `sync_format.ANSWERS` (S16-3).
  The link to the controller's game is `scheduled_games.controller_game`
  (a `games.id`), set from the game's metadata (`meta.scheduled_game_id`).
- **The replicas' classes** come from the field's `limit_template` and
  `max_replicas` on the site server, the same names as the controller's
  `[checkin]` settings; a pre-declared replica the controller would refuse
  is dropped from its expected check-in (S16-6, S16-14).
- **Outcomes** go back once the game has ended (not in batches during it);
  walk-ins as a count only; `[sync] push_walkins` is not built (S16-11,
  S16-13).
- **Registering on the web pages**: the public pages have no login and no
  JavaScript, so their *Register* button leads to a page that says how to
  register in the app with an account (S16-9).

---

### ADR-P4-12: Open feeds, registration import and platform adapters

**Status:** Proposed (2026-10-19, maintainer request; decisions
F18-F23 in `docs/review/decisions-to-review.md`, all open)

**Context:** The maintainer also asked for publication on "shared/
third-party platforms like the jogarairsoft.pt we have here in
portugal".  A web search (2026-10-19) found no public information or
API documentation for jogarairsoft.pt, so no integration with it can be
designed from facts.  The project is clean-room (spec section 17) and
will not scrape a third party's pages.  What can be built without any
platform's cooperation is open, standard output that any calendar or
platform can read, and an import of a registration list that a field
exports from wherever it takes registrations.

**Decision:**

#### iCalendar feed (RFC 5545)

`GET /f/<slug>/games.ics` (public when the field page is on; also a
per-game `/f/<slug>/games/<id>.ics`), media type `text/calendar`:

- one `VCALENDAR` with `VERSION:2.0` and
  `PRODID:-//Atalaia//Site server//EN`, one `VEVENT` per published game,
  including cancelled ones for 30 days after their date;
- per event: `UID` (the scheduled game's UUID `@` the site's host name,
  never reused), `DTSTAMP`, `DTSTART` and `DTEND` in UTC (the `Z` form,
  so no `VTIMEZONE` is needed), `SUMMARY`, `DESCRIPTION` (plain text,
  with the game page's address), `LOCATION` (the field's address text,
  if set), `URL`, `STATUS` (`CONFIRMED`, or `CANCELLED`), `SEQUENCE`
  (raised on every change to time, place or status, so subscribed
  calendars update), `LAST-MODIFIED`;
- CRLF line ends, lines folded at 75 octets, text values escaped as RFC
  5545 requires (backslash, semicolon, comma, newline);
- `ETag` and `Last-Modified` headers so calendar apps can poll cheaply.

Drafts never appear.  No personal data: no registrant names or counts.

#### JSON feed

`GET /f/<slug>/games.json`, the same games as data, for a club's own
website or a platform willing to read it:

```json
{
  "format": "atalaia.games",
  "version": 1,
  "field": {"slug": "campo-exemplo", "name": "Campo Exemplo", "timezone": "Europe/Lisbon", "url": "https://..."},
  "games": [
    {
      "id": "0192...", "title": "...", "description": "...",
      "starts_at": "2026-11-08T09:00:00Z", "ends_at": "2026-11-08T13:00:00Z",
      "status": "published", "mode": "org.atalaia.domination",
      "registration": {"opens_at": "...", "closes_at": "...", "open": true, "max_players": 60, "places_left": 12},
      "requirements": {"federation": "required", "federation_label": "FPA"},
      "url": "https://.../f/campo-exemplo/games/0192...", "ics": "https://.../games/0192....ics",
      "updated_at": "..."
    }
  ]
}
```

Times are RFC 3339 in UTC.  The schema is a JSON Schema file in the
repository (`server/schemas/games-feed-v1.schema.json`) and the format
is documented in `server/docs/feeds.md`; a new major version gets a new
`version` and a new path.  Both feeds send
`Access-Control-Allow-Origin: *` (read-only, no cookies), so other
sites can show them.  The game page also embeds the game as
schema.org `Event` JSON-LD, a common vocabulary that search engines
read.

#### Registration import

`POST /api/v1/fields/{field_id}/scheduled-games/{id}/registrations/import`
(`admin` or `gm`), with `?dry_run=true` to preview:

- **CSV** (RFC 4180, UTF-8, a header row) or a **JSON** array of
  objects with the same names;
- columns: `display_name` (required), `external_ref` (the other
  platform's registration id; recommended), `team_preference`,
  `federation_number`, `replicas` (JSON: an array of `{type, class,
  make_model}`; CSV: entries separated by `|`, each
  `type:class[:make_model]`);
- **only those columns are read**: any other column (an email, a phone
  number, a birth date) is ignored and named in the preview as "not
  imported", so the import never takes more than the check-in needs;
- rows upsert by `(source, external_ref)`, so importing an updated
  export again changes the same registrations; rows without
  `external_ref` are added each time (the preview warns);
- the preview lists, per row, created, updated or refused with the
  reason; nothing is written in a dry run;
- imported registrations have no account (`user_id` null, `source`
  `import` with the label the admin gives, e.g. the platform's name),
  get a `player_id` but no ticket (the marshal ticks them by name), and
  follow ADR-P4-8's 30-day guest rule.  The field is the data
  controller for what it imports and must have its own basis for having
  that list; the import screen says so.

#### Platform adapters

An adapter connects one field's site server to one external platform
through that platform's own interface.  The interface
(`server/src/integrations/base.py`):

```python
class PlatformAdapter(Protocol):
    id: str                        # stable, e.g. "csv", "example"
    name: str
    capabilities: frozenset[str]   # subset of {"publish", "update", "cancel", "registrations"}

    async def publish(self, game: PublishedGame, cfg: AdapterConfig) -> ExternalRef: ...
    async def update(self, ref: ExternalRef, game: PublishedGame, cfg: AdapterConfig) -> None: ...
    async def cancel(self, ref: ExternalRef, cfg: AdapterConfig) -> None: ...
    async def fetch_registrations(self, ref: ExternalRef, cfg: AdapterConfig) -> list[ImportedRegistration]: ...
```

Rules:

- **Only a documented API or a written agreement.**  An adapter uses
  the platform's published API, or an interface the platform has agreed
  to in writing.  No scraping of web pages, no automated form posting,
  no use of a person's login on their behalf beyond what the platform's
  API offers.  An adapter that does any of these is not accepted.
- Registrations from an adapter go through the import path above (same
  columns, same minimisation, same preview rules when run by hand).
- Off by default, enabled per field by an `admin`; credentials are
  stored encrypted (Fernet, as TOTP secrets, ADR-P4-2); every call is in
  the audit log; calls go out from the site server only, never from the
  field controller; a failing platform never blocks scheduling,
  publication or check-in.
- New table `platform_links` (`field_id`, `adapter_id`, `config_enc`,
  `enabled`) and `external_game_links` (`scheduled_game_id`,
  `adapter_id`, `external_ref`, `last_synced_at`, `last_error`).
- Shipped: the interface, a test adapter, and the CSV and JSON import as
  the reference "registrations" source.  No adapter for a named
  platform ships without that platform's API documentation or
  agreement.

**jogarairsoft.pt.**  No adapter is designed.  No public information or
API about it was found (web search, 2026-10-19).  An adapter needs the
platform's API documentation or an agreement with its operators, which
the maintainer would have to request by contacting them (F22).  Until
then, a field that uses it can link its feeds where the platform
allows, and import a registration list if the platform lets the field
export one (unknown).  Nothing will be scraped.

**Consequences:**
- Any calendar app can subscribe to a field's games, and any site or
  platform can read them, with no agreement needed.
- Fields that take registrations elsewhere can still bring them to the
  controller's check-in list, with only the data the check-in needs.
- Specific platforms are an extension point with clear rules, not a
  promise; nothing is said about a third party that is not known.
- The feeds are public and hold no personal data.

---

### ADR-P4-13: The hub-level OIDC callback relay (design only, not built)

**Date:** 2026-10-28. **Status:** proposed, to be built with the legal review of hosted mode (P4-6); no code yet.
**Decided by the maintainer** (S21-12's follow-up, 2026-10-28): hosted mode gets one callback address for social login
(Google, Microsoft, Apple) instead of one per field.

**Problem.** A social-login provider only redirects the browser to addresses registered in advance, one by one
(no wildcards for Google or Apple; Microsoft allows few). Hosted mode today builds the redirect URI from the
field's own address (`<slug>.<hub domain>`, or its custom host name since PKC-6), so every new field, and every custom
name, needs its address registered at three providers by the operator before its members can use social login. That
does not scale to the hundreds of fields ADR-P4-4 plans for.

**Decision.** One callback on the hub, `https://<hub domain>/api/v1/auth/oidc/callback`, registered once per provider,
and a relay that sends the browser on to the field that started the login.

1. *Start (at the field, as today).* `POST /api/v1/auth/oidc/{provider}/start` is served at the field's own host. It
   makes the login row in the field's schema (state hash, binding hash, nonce, PKCE verifier, purpose, return path)
   and sets the HttpOnly binding cookie **on the field's host**. The redirect URI it sends to the provider is the
   hub's, and the `state` it sends is **signed state** instead of a bare random value:
   `state = base64url(slug ‖ host ‖ nonce) ‖ "." ‖ HMAC-SHA256(relay key, slug ‖ host ‖ nonce ‖ provider ‖ expiry)`,
   where `nonce` is today's random state, `host` is the exact name the login started on (the field's own or its custom
   host name) and `expiry` is the login's expiry (10 minutes). The relay key is derived from `ATALAIA_SECRET_KEY`
   with HKDF and its own label (never the key itself, never shared with another use).
2. *Relay (at the hub, no tenant).* The hub's callback runs outside any tenant (like the health check) and reads
   nothing from a database. It checks the signature and the expiry, that the slug is syntactically valid and that
   the provider matches, and answers `303` to
   `https://<host>/api/v1/auth/oidc/{provider}/callback?code=…&state=<nonce>` (or the provider's `error` and
   `error_description`), with no body and no cookie. It never sees a token: the authorisation code is single use, bound
   to the PKCE challenge the field made, and only the field holds the verifier.
3. *Completion (at the field, as today).* The field's existing callback checks the binding cookie (present, because the
   browser is back at the host that set it), finds the login row by the state, exchanges the code (with the hub's
   redirect URI, which the provider insists on matching), checks the ID token and nonce, and signs the person in.
   Nothing about accounts, linking, consent or reauthentication changes.

Hosted fields keep working without the relay while it is off (a per-hub setting): the per-field redirect URI is used.

**Threats and mitigations.**

| Threat | Mitigation |
| --- | --- |
| Open redirect: the relay sends a browser to an attacker's host | The target host is not in the query: it is inside the signed state. The relay redirects only to a host it signed itself, 10 minutes earlier, and (belt and braces) only to a name under the hub domain or a registered, verified custom host name (one registry read of a name, not of data). |
| Forged or altered state (a login for another field, another host) | HMAC over the slug, host, nonce, provider and expiry; constant-time compare; the nonce is also the login row's key at the field, which checks its own state hash, so a state the field did not make finds no row. |
| Replay of a state or a code | Single use: the field deletes the login row when it completes (as today); the code is single use at the provider; the signature carries an expiry. The relay is stateless, so a replay reaches the field, which refuses it. |
| Login CSRF / a victim logged in as the attacker | The binding cookie stays at the field's host and must match the login row (as today); the relay sets and reads no cookie. A callback that does not come back to the browser that started it is refused at the field. |
| The relay as an oracle or a way to probe fields | The answer is the same for a field that does not exist, is suspended or has no login: a `303` to the signed host, or a plain `400` for a bad signature; it makes no registry lookup of the slug. The hub-level callback is rate limited per address like the other login endpoints. |
| Cross-field substitution (a code meant for field A delivered to field B) | The host in the state is where the browser goes; the code is bound to A's PKCE verifier, which B does not have: B's exchange fails. A field's login row also holds its own provider and redirect URI. |
| Leaking the code in a `Referer` or logs | The code is in the redirect's query, so the relay answers `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, and never logs the query string; the hub's reverse proxy must not either (deployment note). The field's callback removes it from the address with a redirect to the page (as today). |
| Compromise of the relay key | The relay key only signs routing information, not sessions or tokens, and is derived with its own label; rotating `ATALAIA_SECRET_KEY` invalidates logins in flight (10 minutes) and nothing else. |
| Custom host names | The relay sends to the custom host the state names, but only if the registry still holds it as that field's active name; a removed name falls back to the field's own host. The provider sees one redirect URI whatever the name. |
| A provider that checks the redirect URI per tenant (Microsoft work accounts) | The hub's single URI is registered once on the hub's own application; the per-field Microsoft tenant setting is unchanged. |

**What this does not change.** Passkeys stay per host (the relying-party id is the host the person is at), so a custom
host name has its own passkeys; sessions, tokens and the per-field accounts (a person at two fields has two accounts)
are untouched; the relay holds no data and adds no table.

**Consequences.** One registration per provider for the whole hub, whatever the number of fields and custom names.
One more public endpoint, outside the tenant routing, with a small, testable surface: the signature check, the expiry
and the redirect. The legal review has to cover that the hub operator now sees, in transit, the provider's code and
the field's name for each social login (not the person's identity: the code is useless without the field's verifier).
Build it after the legal review (P4-6) and test it with the provider's sandbox clients.

---

## Phase 2 and 3 handoff (2026-10-18)

Phase 2 implementation (A-E) is complete and Phase 3 design is
complete (not yet built). The following changes affect the ADRs above:

### What changed

1. **Controller package path** (ADR-P4-3, ADR-P4-6, ADR-P4-7):
   `controller/atalaia_controller/`, not `controller/src/`.

2. **Controller auth model** (ADR-P4-3): the controller uses bearer
   tokens (read token for reads, GM token for writes), not the
   API-key auth originally designed for both directions. Auth is now
   asymmetric: controller-to-site-server uses a 256-bit API key;
   site-server-to-controller uses bearer tokens.

3. **Event unique constraint** (ADR-P4-1): widened from
   `(game_id, node_id, seq)` to
   `(game_id, node_id, seq, game_time_ms, event_type)` to handle
   seq restarts after a box reboot (decision D6).

4. **Scenario compiler location** (ADR-P4-6): moved from the site
   server to the field controller as a shared Python library at
   `controller/atalaia_controller/scenarios/`. The site server imports
   it. Maintainer decision P4-1.

5. **Event ID allocation**: Phase 3 uses IDs 25-27 and 33-41; Phase 2
   mode pack uses 28-32. Phase 4 events start at ID 42.

6. **Player tokens** (ADR-P4-1 note): HMAC-SHA256-signed JSON (not
   JWT) with player_id, team, squad, role, game_id, exp; signed with
   the game key. The controller issues them; the site server must
   understand them for position filtering. *(Corrected 2026-10-19: as
   built they are signed with the controller's own per-game token key,
   decision B8, and the site server neither issues nor verifies them,
   P4R25.)*

### What was confirmed

- **Chrono signing** (ADR-P4-5): Ed25519 per marshal, confirmed by
  Phase 3 design (ADR-P3-7). No change needed. *(2026-10-19: the
  algorithm holds; key handling changed, see ADR-P4-5's amendment.)*
- **PostgreSQL + SQLAlchemy** (ADR-P4-1): unchanged.
- **Multi-tenant schema isolation** (ADR-P4-4): unchanged.
- **GDPR implementation** (ADR-P4-8): unchanged.
- **Geo utilities** (ADR-P4-9): unchanged.
- **ATAK / CoT** (ADR-P4-7): unchanged in protocol; module path
  updated.
- **Deployment** (ADR-P4-10): unchanged.

*(2026-10-19: this handoff was written from phase 3's design; the
"Refresh 2026-10-19" section at the top of this file and the dated
amendments re-check every ADR against what phase 3 built.)*

---

## Constraints for Planning

The planning phase must respect the following constraints derived from
the decisions above:

1. **PostgreSQL 16+ with SQLAlchemy 2.0 async + asyncpg.** The schema
   from ADR-P4-1 is the source of truth. All tables carry UUID primary
   keys, `created_at` and `updated_at` timestamps.

2. **Alembic for all schema changes.** Every migration must be
   reversible. CI runs upgrade-downgrade-upgrade against a test
   database.

3. **Argon2id for passwords, PyJWT for tokens, pyotp for TOTP.**
   Access tokens are 15-minute JWTs. Refresh tokens are 7-day JWTs in
   HTTP-only cookies. TOTP is mandatory for admin, GM and marshal
   roles.

4. **API-key authentication for controller sync.** The key is a
   256-bit random value, stored as an Argon2id hash on the server.
   The controller stores the plaintext key locally. *Amended
   2026-10-19:* stored as its SHA-256; the controller opens every
   connection and the site server holds none of the controller's
   tokens (ADR-P4-3's amendment).

5. **Events are append-only; scores merge by GREATEST.** The
   `UNIQUE(game_id, node_id, seq, game_time_ms, event_type)` constraint
   enforces idempotent sync (widened from the original `(game_id,
   node_id, seq)` to handle seq restarts after a box reboot -- see
   decision D6). The controller can replay conservatively. *Amended
   2026-10-19:* a game is `(field, game_id, game_seed)`; scores merge
   per node counter, GM adjustments come as `score.delta` events.

6. **Schema-per-field in hosted mode.** Self-hosted uses the public
   schema with no multi-tenant overhead. Migration must iterate over
   tenant schemas.

7. **Ed25519 for chrono record signing.** Keypairs are per-marshal,
   independent of passwords. The private key is stored encrypted on
   the server for recovery and in the marshal's app for signing.
   *Amended 2026-10-19:* the key is made on the marshal's phone and
   never leaves it; the site server keeps public keys with their
   history and the records verbatim.

8. **Scenario manifests are YAML.** The compiler is a shared Python
   library at `controller/atalaia_controller/scenarios/` (maintainer
   decision P4-1); the site server imports it. Validation includes
   DAG check, parameter validation and zone geometry checks.
   *Amended 2026-10-19:* it emits a `kind: scenario` package
   (`field.lua` only) over the built-in `org.atalaia.objectives` role
   package; the Lua is load-checked in the core on both sides.

9. **CoT emission via UDP multicast (primary) and TCP (secondary).**
   The `geo` table (`geo.distance`, `geo.in_zone`) is registered in
   the core for all scripts. Zone types: circle and polygon.

10. **GDPR: anonymise on erasure, retain for integrity.** The
    retention purge job runs daily. Privacy notice and DPA templates
    are shipped but require legal review before hosted mode goes live.

11. **docker-compose with Caddy or nginx for TLS.** The setup script
    generates secrets. Backups use `pg_dump -Fc` daily with 30-day
    retention.

12. **New events in `protocol/schema/events.yaml`:** `scenario.
    objective.completed`, `scenario.objective.failed`, `scenario.
    objective.revealed`, `scenario.started`, `satellite.captured`,
    `satellite.neutralized`, `vip.extracted`, `hacking.solved`.
    *Amended 2026-10-19 (P4R1):* 42-45 the scenario events, 46
    `vip.extracted`, 47 `hacking.solved`, no `satellite.*`; data keys
    34 `objective`, 35 `scenario`, 36 `puzzle`; each added with the
    code that first emits it.

13. **SPDX headers on every file.** `AGPL-3.0-or-later` for server
    code. `GPL-3.0-or-later` for controller additions (atak.py,
    sync_client.py). `CC-BY-SA-4.0` for docs and templates.
    *Corrected 2026-10-19 (P4R21):* controller additions are
    AGPL-3.0-or-later like all of `controller/` (REUSE.toml); modes,
    core and tools GPL-3.0-or-later.

14. **No C compiler on host.** The site server is pure Python. The
    controller's `libatalaia_core.so` (for geo functions) is cross-
    compiled in Docker. The `cryptography` library ships pre-built
    wheels. *Amended 2026-10-19:* the site server image builds the core
    in a build stage (scenario load checks) and runs `python:3.12-slim`
    with hash-pinned dependencies.

15. **Phase 3 interfaces are assumptions.** ADR-P4-7 (ATAK) assumes
    `gps.fix` events from the player app. ADR-P4-6 (`escort` objective)
    assumes GPS reporting. ADR-P4-1 (game roles) assumes the player
    app role model. These interfaces must be re-verified when Phase 3
    design completes. *Superseded 2026-10-19:* phase 3's interfaces are
    built and are the source of truth; there are no `gps.fix` events
    (positions stay on the controller), the role model is the player
    token's.

16. **Scheduling and registration feed the controller; they never drive
    it** (ADR-P4-11, 2026-10-19).  The controller pulls the schedule and
    the roster; roster changes stop applying once the game starts; the
    roster carries only what ADR-P3-13's check-in holds; walk-ins are
    pushed as counts unless the field opts in.

17. **Open feeds hold no personal data** (ADR-P4-12).  iCalendar (RFC
    5545, UTC times) and the versioned JSON feed list published games
    only; drafts never, registrant names never.

18. **Third-party platforms only through a documented API or a written
    agreement** (ADR-P4-12).  No scraping or automated form posting;
    adapters are off by default, per field, audited, outbound from the
    site server only; imports read only the listed columns.

19. **Boxes run built-in scripts only** (added 2026-10-19, ADR-P4-6's
    amendment). Anything particular to one game lives in `field.lua`
    and reaches the nodes as mode commands.

20. **Positions never travel as events**, on the radio, MQTT, the
    stream's public messages or to the site server (added 2026-10-19,
    ADR-P4-8 and ADR-P4-9 amendments). Scripts get them as
    controller-only inputs.

21. **Shared Python stays framework-free** (added 2026-10-19): the
    scenario library, the chrono verifier, the player-token codec, the
    image checks and `atalaia_sim.mode` import without FastAPI or
    pydantic, so the controller and the site server both use them.

22. **Scripts' limits as built** (added 2026-10-19): `score.add` takes
    integers; events carry ids, never texts or coordinates; every event
    fits 200 bytes (the simulator's checks).

23. **Verification** (added 2026-10-19): each plan phase is verified
    from a clean copy and committed on its own; firmware changes are
    verified without Wokwi while decision R7 stands.
