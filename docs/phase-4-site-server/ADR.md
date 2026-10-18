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
    UNIQUE(game_id, node_id, seq)
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
- The `UNIQUE(game_id, node_id, seq)` constraint on `game_events`
  mirrors the controller's SQLite dedupe (ADR-P2-9) and enforces
  idempotent event sync.
- Alembic's reversibility requirement means any deployment can be
  rolled back within one release window.

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

---

### ADR-P4-3: Sync protocol between controller and site server

**Status:** Accepted

**Context:** The controller is authoritative during a game; the site
server is authoritative for accounts and historical data. The sync must
handle offline operation (the controller buffers everything and uploads
later). Events are append-only and scores are grow-only, so the sync
is conflict-free by design (RESEARCH.md section 6).

**Decision:**

**Transport:** HTTPS (TLS 1.3) with API-key authentication.

**Controller API key:**

Each field has a long-lived API key generated during field registration
on the site server. The key is a 256-bit random value, base64url-
encoded (43 characters). The site server stores the Argon2id hash of
the key in `fields.api_key_hash`. The controller stores the plaintext
key in its local config file (protected by filesystem permissions).

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
cache key).

**Sync endpoints (site server):**

| Method | Path | Direction | Purpose |
|--------|------|-----------|---------|
| GET | `/api/v1/sync/roster?game_id=` | Controller pulls | Players registered for upcoming game |
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
4. Batch replay is idempotent: the `UNIQUE(game_id, node_id, seq)`
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
- API-key auth is simpler than mutual TLS and sufficient for the
  threat model (the key authenticates the field, not individual users).
- Offline buffering is transparent: the controller works identically
  whether the site server is reachable or not.
- The grow-only score merge (`GREATEST`) is the same algorithm as the
  controller's internal score merge (ADR-P2-9), proven correct.
- Batch replay with deduplication means the controller never needs to
  track exactly which events the site server has -- it can replay
  conservatively.

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

The compiler is a Python module (`server/src/services/scenario_compiler.py`)
that generates Lua code from templates.

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

On the site server. The GM console sends the scenario YAML via
`POST /api/v1/scenarios`, the server validates and compiles it, stores
both the manifest and the compiled `field.lua`, and returns the
compiled script. The controller receives the compiled script via the
normal preset sync (ADR-P4-3).

A CLI tool (`atalaia-scenario compile scenario.yaml`) is also
provided for offline use without a site server.

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
(`controller/src/atak.py`) that subscribes to game events and node
STATE messages and emits CoT XML.

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
   The controller stores the plaintext key locally.

5. **Events are append-only; scores merge by GREATEST.** The
   `UNIQUE(game_id, node_id, seq)` constraint enforces idempotent
   sync. The controller can replay conservatively.

6. **Schema-per-field in hosted mode.** Self-hosted uses the public
   schema with no multi-tenant overhead. Migration must iterate over
   tenant schemas.

7. **Ed25519 for chrono record signing.** Keypairs are per-marshal,
   independent of passwords. The private key is stored encrypted on
   the server for recovery and in the marshal's app for signing.

8. **Scenario manifests are YAML.** The compiler runs on the site
   server (Python) and produces `field.lua`. Validation includes DAG
   check, parameter validation and zone geometry checks.

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

13. **SPDX headers on every file.** `AGPL-3.0-or-later` for server
    code. `GPL-3.0-or-later` for controller additions (atak.py,
    sync_client.py). `CC-BY-SA-4.0` for docs and templates.

14. **No C compiler on host.** The site server is pure Python. The
    controller's `libatalaia_core.so` (for geo functions) is cross-
    compiled in Docker. The `cryptography` library ships pre-built
    wheels.

15. **Phase 3 interfaces are assumptions.** ADR-P4-7 (ATAK) assumes
    `gps.fix` events from the player app. ADR-P4-6 (`escort` objective)
    assumes GPS reporting. ADR-P4-1 (game roles) assumes the player
    app role model. These interfaces must be re-verified when Phase 3
    design completes.
