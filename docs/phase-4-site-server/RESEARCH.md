<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 4 -- Site Server and Advanced Play: Research

**Risk level:** High
**Last updated:** 2026-10-17

---

## 1. Summary

Phase 4 adds the optional site server (accounts, history, chrono
registry, remote setup) and four advanced game modes (Master and
Satellites, Target Windows, VIP / Payload, Hacking Terminal), plus ATAK /
Cursor-on-Target integration, custom scenarios, and the gate test for a
weekend milsim running end to end on the platform.

**Key findings:**

1. **Python / FastAPI reuse is the clear choice** for the site server.
   The controller already uses FastAPI + SQLite; the site server reuses
   the same framework with PostgreSQL (asyncpg / SQLAlchemy async) for
   multi-tenant persistence. A shared `atalaia-common` Python package
   can hold event schemas, sync protocol, and auth utilities.

2. **The sync layer is low-risk** because events are append-only and
   scores are grow-only counters. The controller pushes event batches
   to the site server over HTTPS; the site server never runs game logic.
   Conflict-free by design.

3. **GDPR compliance is non-trivial but well-scoped.** The field operator
   is the data controller; the hosted hub is a data processor. Data
   retention defaults, export endpoints, and a template privacy notice
   are required. Portugal's CNPD is the supervisory authority.

4. **All four advanced modes need `field.lua`**, which depends on the
   Phase 2C `field.*` API (complete). Three of the four also depend on
   Phase 3 deliverables (Android shell, player app, GPS). Only Master
   and Satellites can be fully tested with ESP32 hardware alone.

5. **ATAK / CoT is a well-defined protocol** (MIL-STD-2045 + CoT XML).
   A small Python emitter on the controller (UDP multicast or TCP) is
   sufficient. No ATAK SDK licence is required for CoT emission.

6. **The weekend milsim gate** is the riskiest item: it requires every
   preceding phase to work together on real hardware, in the field, over
   a full weekend. The gate definition must be concrete and testable in
   stages.

7. **Custom scenarios** are the most design-intensive feature. The
   objective-block system compiles to `field.lua` and must cover the
   spec's seven block types. A DSL (YAML-based scenario manifest) is
   more tractable than a freeform visual editor for Phase 4; the visual
   editor is Phase 5.

---

## 2. Codebase inventory relevant to Phase 4

### Directories and files

| Path | Relevance |
|------|-----------|
| `server/README.md` | Placeholder; confirms AGPL-3.0-or-later, PostgreSQL, container image |
| `controller/atalaia_controller/` | Phase 2 (A-E complete): Python controller with FastAPI, SQLite (schema 2), MQTT (Mosquitto with per-user ACLs), radio modem. Bearer token auth (read token, GM token). Phase 4 site server shares the framework. |
| `controller/console/` | Phase 2E (complete): GM console PWA (Preact 10.24.3 + HTM 3.1.1 + qrcode-generator), served at `/console/`. Phase 4 extends it with remote-setup and scenario-builder panels. |
| `core/include/atalaia/` | 11 headers. `protocol.h` contains field_ops-related declarations. `node.h` defines `atalaia_node_config_t` with `field_ops` pointer. |
| `core/src/script_api.c` | Lua API surface. `state.field{}` and `field.*` are registered when `field_ops` is non-NULL (Phase 2C, complete). |
| `modes/domination/` | Reference mode: `node.lua` only, `mode.yaml` with params. |
| `modes/bomb/` | Reference mode: `node.lua` only, `mode.yaml` with params. |
| `simulator/` | RadioModel, FieldController, packet codec. Tests cover multi-node, partition, failover, duty-cycle. |
| `protocol/schema/events.yaml` | Standard event vocabulary; Phase 4 adds new events (target.hit already listed; add satellite.*, vip.*, hacking.*, scenario.*). |
| `protocol/schema/messages.yaml` | 8 message types. No changes expected for Phase 4. |
| `docs/design-spec.md` | Sections 4, 9, 11, 12, 13, 14, 15, 16 are primary sources. |
| `docs/phase-2-field-network/ADR.md` | 15 ADRs. ADR-P2-5 (Python/FastAPI), ADR-P2-14 (field_ops API), ADR-P2-9 (event log schema) are directly relevant. |

### Patterns to follow

- **Mode package format**: `mode.yaml` + `node.lua` + optional `field.lua` + `tests/` + `assets/` + `i18n/`.
- **Test format**: YAML event sequences with `expect`, `hold`, `wait` steps; CI runs them in the simulator.
- **Protocol extension**: new events go through `events.yaml` with an RFC if they add packet fields.
- **ADR pairing**: every significant decision gets an ADR in the phase directory.
- **SPDX headers**: AGPL-3.0-or-later for controller and site server code; CC-BY-SA-4.0 for docs.

---

## 3. Design spec requirements for Phase 4

The spec (section 16) defines Phase 4's scope and gate:

> **Phase 4 -- Site server and advanced play**
> Site server: accounts, history, chrono registry, remote setup.
> Master and Satellites, Target, VIP, Hacking Terminal, ATAK.
>
> **Gate:** A weekend milsim runs on the platform end to end.

### Explicit requirements from the spec

| Spec section | Requirement | Phase 4 relevance |
|--------------|-------------|-------------------|
| 4 (architecture) | Site server is optional, self-hosted; container image + PostgreSQL | Primary deliverable |
| 11 (site server) | Accounts, field setup, remote management, player app backend, history, chrono registry, public scoreboard | Primary deliverable |
| 11 (sync) | Before: pull rosters/presets/chrono. During: stream events. After: upload log. Conflicts do not arise. | Sync protocol |
| 12 (roles) | Player, squad leader, VIP, marshal, GM, spectator | Auth model |
| 12 (chrono) | Replica registry, check-in flow, spot checks, marshal-signed records, sharing between fields opt-in | Chrono registry |
| 12 (positions) | Server filters per role; no leakage | AuthZ enforcement |
| 13 (community hub) | Hosted site servers for clubs without IT; data separate and exportable | Multi-tenant design |
| 14 (security) | HTTPS, 2FA for GM/marshal/admin, append-only chrono, signed records | Security model |
| 14 (privacy) | GDPR: export, delete, retention, privacy notice template | GDPR compliance |
| 15 (modes) | Master and Satellites, Target Windows, VIP / Payload, Hacking Terminal | Advanced modes |
| 15 (custom scenarios) | Objective blocks compiled to field.lua | Scenario builder |
| 11 (ATAK) | Controller emits CoT messages for ATAK maps | CoT integration |
| 4 (weekend milsim) | 10-20 boxes+satellites, Pi controller with repeaters, Android 4G bridge, player app, ATAK | Gate test |

---

## 4. Site server architecture analysis

### Language and runtime

**Decision: Python 3.11+ with FastAPI, matching the field controller.**

| Option | For | Against | Verdict |
|--------|-----|---------|---------|
| Python / FastAPI | Same language as controller; shared event schemas and sync code; FastAPI already chosen (ADR-P2-5); async support via Starlette | Not the fastest runtime | **Chosen** |
| Go | Fast, low memory, good for containers | Different language from controller; no code sharing | Rejected |
| Node.js / TypeScript | Good async, large ecosystem | Third language; no C core bindings needed on site server | Rejected |

The site server does not run game logic or the C core. It receives
events, stores data, serves the player app backend, and serves the
remote GM console. Python + FastAPI is the pragmatic choice.

### Database

**Decision: PostgreSQL 16+ with SQLAlchemy 2.0 (async) + asyncpg.**

| Option | For | Against | Verdict |
|--------|-----|---------|---------|
| PostgreSQL | Mature, JSONB for event data, full-text search, row-level security for multi-tenant, AGPL-compatible | Heavier than SQLite | **Chosen** |
| SQLite | Same as controller; simpler | No concurrent writers; no row-level security; no built-in replication | Rejected for site server; kept for controller |

The controller keeps SQLite (local, single-writer). The site server
uses PostgreSQL for concurrent access, multi-tenant isolation, and
durability. SQLAlchemy 2.0 async with asyncpg gives FastAPI native
async database access.

Schema families:

| Schema area | Tables |
|-------------|--------|
| Accounts | `users`, `roles`, `user_roles`, `sessions`, `totp_secrets` |
| Fields | `fields`, `field_profiles`, `field_maps`, `house_rules` |
| Devices | `devices`, `device_firmware`, `device_health` |
| Games | `games`, `game_events`, `game_scores`, `presets` |
| Chrono | `replicas`, `chrono_records`, `chrono_violations` |
| Players | `player_profiles`, `player_stats`, `squad_memberships` |
| Scenarios | `scenarios`, `scenario_objectives` |

### Deployment

**Decision: docker-compose with two services (app + PostgreSQL).**

```yaml
# docker-compose.yml (conceptual)
services:
  atalaia-server:
    image: atalaia/site-server:latest
    ports: ["8443:8443"]
    environment:
      DATABASE_URL: postgresql+asyncpg://...
      SECRET_KEY: ...
    volumes:
      - ./data:/app/data   # uploads, maps, mode packages

  postgres:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
```

Runs on:
- A mini PC at the field (same machine as the controller for small sites).
- A VPS (2 GB RAM, 1 vCPU is sufficient for a single field).
- The community hub runs one PostgreSQL instance with per-field schemas
  for the hosted mode.

### Multi-tenant hosted mode

Each hosted field gets its own PostgreSQL schema (not a separate
database) within a shared PostgreSQL instance. This gives:

- **Isolation**: row-level security + schema separation. A field's data
  is invisible to other fields.
- **Exportability**: `pg_dump --schema=field_xyz` exports one field's
  entire dataset for migration to self-hosted.
- **Cost efficiency**: one PostgreSQL instance serves many small fields.

The `field_id` column in every table (in hosted mode) drives
row-level security policies. Self-hosted deployments use a single
schema with no `field_id` overhead.

---

## 5. Accounts, auth, GDPR

### Account model

Accounts are optional. A player can join a game as a guest (scan a QR
code at the safe zone). With an account, their history and chrono
records follow them across games.

```
User
  id: UUID
  email: str (unique, optional -- can register with username only)
  username: str (unique)
  password_hash: str (argon2id)
  created_at: datetime
  last_login: datetime
  gdpr_consent_at: datetime | null
  data_retention_days: int (default from field)
```

### Roles and permissions

Roles are per-field, per-game. A user can be a player at one field and
a marshal at another.

| Role | Permissions |
|------|------------|
| player | View own scores, own chrono records, own team objectives |
| squad_leader | Player + squad positions, waypoints, hint intel for squad |
| vip | Player + own escort team positions; acts as moving objective |
| marshal | All positions, chrono check-in and spot checks, mark player out, log incidents |
| gm | Everything: game control, override, score adjustment, broadcast |
| spectator | Scores and public events only, with a delay |
| admin | Field configuration, user management, device management |

### Authentication

| Requirement | Implementation |
|-------------|---------------|
| Password storage | Argon2id (memory-hard, recommended by OWASP) |
| Session management | JWT access tokens (15 min) + HTTP-only refresh tokens (7 days) |
| Two-factor | TOTP (RFC 6238) mandatory for admin, GM, marshal roles; optional for others |
| HTTPS | Mandatory; TLS termination at reverse proxy (Caddy or nginx) or Cloudflare |
| Rate limiting | Per-IP and per-user; 5 failed logins trigger 15-minute lockout |

### GDPR compliance (Portuguese context)

Portugal's data protection is governed by GDPR (Regulation 2016/679)
and Lei 58/2019 (the national implementing law). The supervisory
authority is the CNPD (Comissao Nacional de Proteccao de Dados).

| GDPR right | Implementation |
|------------|---------------|
| Right of access (Art. 15) | `GET /api/v1/me/data` returns all personal data as JSON |
| Right to erasure (Art. 17) | `DELETE /api/v1/me` anonymises the account and deletes personal data; chrono records are anonymised (marshal signature retained, player identity removed) |
| Right to data portability (Art. 20) | `GET /api/v1/me/export` returns a ZIP with JSON files (profile, games, chrono records, scores) |
| Right to rectification (Art. 16) | `PATCH /api/v1/me` for profile data |
| Consent | Explicit consent at registration; separate consent for chrono sharing between fields |
| Data retention | Configurable per field (default 12 months for chrono, 6 months for positions, 24 months for game history); automated purge job |
| Privacy notice | Template shipped in `docs/templates/privacy-notice-pt.md` and `privacy-notice-en.md`; field operator customises and publishes |
| Data processing agreement | Template for hosted site servers; the project is data processor, the field operator is data controller |
| Breach notification | Documented procedure: field operator notifies CNPD within 72 hours (Art. 33) |

**Data minimisation:**
- Positions are deleted when a game is archived, unless the GM exports them.
- Guest players have no persistent account; their event data is anonymised after the game.
- Chrono records retain marshal signature but can have player identity removed on deletion.

### Privacy notice template

The template covers:
1. Identity of the data controller (field operator).
2. Categories of data collected (name, email, chrono readings, GPS during games, game events).
3. Legal basis (consent for registration; legitimate interest for game operation).
4. Retention periods.
5. Rights (access, rectification, erasure, portability, objection).
6. Contact for the field's data protection officer (if appointed).
7. Right to lodge a complaint with the CNPD.

---

## 6. Controller-to-site-server sync

### Sync model

The sync is asymmetric: the controller is authoritative during a game;
the site server is authoritative for accounts and historical data.

```
Before game:
  Controller ----pull----> Site server
    - Rosters (players registered for this game)
    - Presets (site-server-managed presets)
    - Chrono records (for check-in and spot-check comparison)
    - Field maps and house rules

During game:
  Controller ----push----> Site server
    - Event stream (WebSocket or HTTPS POST batches)
    - Score snapshots (periodic, every 30 s)
    - Node health (periodic)

After game:
  Controller ----push----> Site server
    - Complete event log (JSON)
    - Final scores
    - Chrono records created during the game

Offline fallback:
  If no link during game, controller buffers everything.
  On reconnect, uploads the full log.
```

### Sync protocol

**Transport:** HTTPS (TLS 1.3) with mutual authentication.

**Authentication:** The controller authenticates to the site server
with an API key (long-lived, rotatable) generated during field
registration. The site server authenticates to the controller with the
same mechanism (for push notifications and pre-game data delivery).

**Conflict resolution:** Not needed by design:

| Data type | Why conflict-free |
|-----------|-------------------|
| Events | Append-only; deduplicated by `(game_id, node_id, seq)` |
| Scores | Grow-only counters; merge by maximum |
| Chrono records | Append-only; signed by marshal; never edited |
| Presets | Versioned; site server version wins for shared presets; local presets are controller-only |
| Player profiles | Site server is authoritative; controller caches a read-only snapshot |

**Batch format:**

```json
{
  "sync_version": 1,
  "field_id": "uuid",
  "game_id": 42,
  "batch_seq": 7,
  "events": [
    {"node_id": 3, "seq": 141, "game_time_ms": 734210, "type": "zone.captured", "team": 1, "data": {...}},
    ...
  ]
}
```

The site server responds with the highest acknowledged `batch_seq`, so
the controller knows what has been persisted and can free its upload
buffer.

### Endpoints

| Method | Path | Direction | Purpose |
|--------|------|-----------|---------|
| GET | `/api/v1/sync/roster` | Controller pulls | Players registered for upcoming game |
| GET | `/api/v1/sync/presets` | Controller pulls | Shared presets |
| GET | `/api/v1/sync/chrono` | Controller pulls | Chrono records for registered players |
| POST | `/api/v1/sync/events` | Controller pushes | Event batch |
| POST | `/api/v1/sync/scores` | Controller pushes | Score snapshot |
| POST | `/api/v1/sync/chrono` | Controller pushes | New chrono records |
| POST | `/api/v1/sync/game` | Controller pushes | Game metadata (start, end, final scores) |
| WS | `/api/v1/sync/stream` | Controller pushes | Live event stream (optional, for live scoreboard) |

---

## 7. Chrono registry

### Data model

```
Replica
  id: UUID
  owner_id: UUID (user)
  tag_uid: str (NFC sticker UID)
  type: enum (aeg, gbb, hpa, bolt_action, dmr, pistol, shotgun)
  brand: str (optional)
  model: str (optional)
  created_at: datetime

ChronoRecord
  id: UUID
  replica_id: UUID
  game_id: int | null (null for pre-game check-in)
  marshal_id: UUID (user with marshal role)
  chronograph_id: str (identifier of the measuring device)
  field_id: UUID
  readings: JSONB [
    { velocity_mps: float, bb_weight_g: float, energy_j: float }
  ]
  highest_energy_j: float (computed, for quick limit check)
  limit_j: float (the field's limit for this replica class)
  result: enum (pass, fail, warning)
  tolerance_pct: float (default 5%)
  is_spot_check: bool
  check_in_record_id: UUID | null (spot checks reference the check-in)
  marshal_signature: str (HMAC-SHA256 of the record, keyed by marshal's signing key)
  recorded_at: datetime
  notes: str (optional)
```

### Cross-field sharing

Sharing chrono history between fields is opt-in at two levels:

1. **Per field**: the field operator enables sharing in field settings.
   Only fields that both opt in can see each other's records.
2. **Per player**: at registration, the player is informed which fields
   can see their chrono records and consents explicitly.

The sharing mechanism uses the site server's REST API:

```
GET /api/v1/chrono/player/{player_id}/history
  ?fields=field-a-uuid,field-b-uuid
```

Returns records only from fields the player has consented to share
with, and only to fields that have opted in to sharing. The response
is filtered at the API layer, not by the caller.

### Marshal signature

Each chrono record is signed by the marshal:

```
signature = HMAC-SHA256(
  key = marshal_signing_key,
  message = canonical_json(record_without_signature)
)
```

The marshal's signing key is derived from their password at login
(HKDF-SHA256, salt = marshal_id) and stored in the session. This means:
- The signature is verifiable by the site server (which knows the key).
- A password change invalidates future signatures but not past ones
  (past records retain the signature made with the old key).
- An alternative: the site server generates a per-marshal Ed25519
  keypair at role assignment, stores the public key, and the marshal
  app holds the private key. This is more robust but adds key
  management complexity. **Decision deferred to ADR phase.**

---

## 8. Remote setup

### Prop health and firmware

The site server provides a dashboard for prop health when props are
online (connected to the controller, which relays to the site server):

| Data | Source | Update frequency |
|------|--------|------------------|
| Battery level | `battery.low` event + STATE messages | Every STATE snapshot (10-60 s) |
| Firmware version | HELLO message | On boot / game join |
| Link quality (RSSI) | STATE messages | Every snapshot |
| Last seen | TIME beacon acknowledgement | Every beacon (10-30 s) |
| Mode installed | Node registry | On join |
| Free storage | System event | On request |

**Firmware update coordination:**
The site server holds firmware images (signed). The controller pulls
them and pushes to nodes over Wi-Fi during maintenance windows. The
site server does not push firmware directly to nodes (it has no LoRa
link). OTA is Phase 3 (A/B partitions, Ed25519 signatures).

### Game scheduling

The site server provides a game calendar:

```
ScheduledGame
  id: UUID
  field_id: UUID
  title: str
  description: str
  scheduled_at: datetime
  duration_estimate: timedelta
  mode_id: str
  preset_id: UUID | null
  max_players: int | null
  registered_players: [UUID]
  teams: [{name, color, max_size}]
  status: enum (draft, published, registering, in_progress, completed, cancelled)
```

Players register through the player app or the site server web UI.
The controller pulls the roster before the game starts.

### Remote GM console

The site server serves the same GM console web app as the controller,
but over the internet. It connects to the controller via the sync
WebSocket:

```
Browser --HTTPS--> Site server --WS/HTTPS--> Controller (via 4G bridge)
```

The remote GM console is read-only for live scores and events. Write
commands (start, pause, override) are forwarded to the controller,
which validates the GM token before executing them. The controller
remains authoritative.

Latency: the 4G bridge adds 50-200 ms. This is acceptable for GM
commands (which are human-paced) but not for time-critical game logic
(which runs locally on the controller).

---

## 9. Advanced modes analysis

All four advanced modes require the Phase 2C `field.*` API (complete).
Three also depend on Phase 3 deliverables.

### 9.1 Master and Satellites

**Concept:** Satellites are small secondary zones (ESP32 Satellite
builds) that boost the master zone's scoring rate. Holding a satellite
gives the master's owner x1.5 scoring speed per satellite. Engineer-
only satellite tags restrict who can capture them. When the master
changes hands, all satellites reset to neutral.

**Lua design:**

`node.lua` (satellite role): standard Domination-like capture logic,
but emits `satellite.captured` and `satellite.neutralized` instead of
`zone.captured`.

`field.lua` (runs on controller):
```lua
-- Pseudocode
local fs = state.field { multiplier = 1 }
local master = field.nodes("master")[1]
local sats = field.nodes("satellite")

on("satellite.captured", function(e)
  local held = 0
  for _, s in ipairs(sats) do
    if field.owner(s) == field.owner(master) then held = held + 1 end
  end
  fs.multiplier = 1 + (held * 0.5)  -- x1.5 per satellite
end)

on("zone.captured", function(e)
  if e.node == master then
    -- Master changed hands: reset all satellites
    for _, s in ipairs(sats) do
      field.send(s, "set_owner", { team = nil })
    end
    fs.multiplier = 1
  end
end)

every(params.tick_s, function()
  local owner = field.owner(master)
  if owner then
    score.add(owner, params.points_per_tick * fs.multiplier, "master_hold")
  end
end)
```

**`field.lua` needs:**
- `field.nodes(role)` -- list nodes by role (Phase 2C, done)
- `field.owner(node)` -- get current owner (Phase 2C, done)
- `field.send(node, cmd, params)` -- send command to node (Phase 2C, done)
- `state.field{}` -- replicated state (Phase 2C, done)

**New mode.yaml roles:**
```yaml
roles:
  master: { requires: [team_input], optional: [team_display, audio] }
  satellite: { requires: [team_input], optional: [led, audio] }
```

**Engineer-only satellite tags:** The satellite's `node.lua` checks
if the `team_input` event has a `squad` field matching "engineer". If
the mode parameter `engineer_only` is true, non-engineer inputs are
ignored. This relies on squad identification from NFC tags or the
player app (Phase 3).

**Test approach:** Fully testable in the simulator with virtual nodes.
No hardware dependency beyond what Phase 2 provides. Create test
scenarios: master capture, satellite capture, multiplier calculation,
master hand change resets satellites, engineer-only filter.

**Phase dependency:** Phase 2 only. No Phase 3 dependency for basic
functionality. Engineer-only tags need Phase 3 (NFC squad identification).

### 9.2 Target Windows

**Concept:** A target addon (piezo sensor + MCU + LED ring) on a
Field Box lights a random team colour for a short scoring window. A
hit during the window scores for that team. Hits outside the window
do not score.

**Lua design:**

`node.lua` (target role):
```lua
-- Pseudocode
local s = state.node { window_open = false, window_team = nil, window_end = 0 }

-- Open a random scoring window every interval_s seconds
every(params.interval_s, function()
  local teams = game.teams()
  s.window_team = teams[rand(1, #teams)]
  s.window_open = true
  s.window_end = game.time() + params.window_s
  cap("ring"):fill(s.window_team)
  cap("hit"):arm()
  after(params.window_s, function()
    s.window_open = false
    cap("ring"):fill("off")
    cap("hit"):disarm()
  end)
end)

on("hit.hit", function(e)
  if s.window_open then
    score.add(s.window_team, params.hit_points, "target_hit")
    emit("target.hit", { team = s.window_team, window = true })
  else
    emit("target.hit", { team = nil, window = false })
  end
end)
```

No `field.lua` needed -- this is a single-node mode.

**`field.lua` needs:** None.

**Hardware dependency:** Requires the target addon from Phase 1 BOM
(steel/polycarbonate plate, piezo sensor, MCU, LED ring). The `hit`
capability type is already defined in the spec (section 7).

**Test approach:** The simulator can test the logic with virtual `hit`
events. The piezo sensor threshold and debounce need hardware testing.
The target addon MCU firmware is a thin-node that exposes the `hit`
capability via the addon bus (I2C).

**Phase dependency:** Phase 1 (target addon hardware). No Phase 3
dependency.

### 9.3 VIP / Payload

**Concept:** Escort a moving prop or a VIP player tracked by GPS/IMU
via the player app. The VIP's phone reports GPS coordinates. Reaching
an extraction zone triggers a game event.

**Lua design:**

`field.lua` (runs on controller):
```lua
-- Pseudocode
local fs = state.field { vip_team = nil, extracted = false }

on("game.start", function()
  fs.vip_team = params.vip_team
end)

on("gps.fix", function(e)
  if e.node == params.vip_node or e.player_role == "vip" then
    -- Check if VIP is within extraction zone radius
    local dist = geo.distance(e.lat, e.lon, params.extract_lat, params.extract_lon)
    if dist <= params.extract_radius_m and not fs.extracted then
      fs.extracted = true
      emit("vip.extracted", { team = fs.vip_team }, { prio = "critical" })
      game.win(fs.vip_team)
    end
  end
end)
```

`node.lua` (escort prop role): standard Domination-like logic for
checkpoint props along the escort route. Each checkpoint scores when
the VIP team holds it.

**`field.lua` needs:**
- `gps.fix` events from the VIP's device (phone or GPS-equipped prop)
- `geo.distance()` utility (new addition to the script API)
- Zone boundary check (circle or polygon)

**New script API additions:**
- `geo.distance(lat1, lon1, lat2, lon2)` -- Haversine distance in
  metres. Pure Lua implementation is fine for game distances.
- `geo.in_zone(lat, lon, zone)` -- point-in-polygon check for
  extraction zones defined as coordinate lists.

**Hardware dependency:** GPS on the VIP's device (built-in on Android,
add-on on ESP32). The player app (Phase 3) must report GPS to the
controller.

**Test approach:** Simulator with injected `gps.fix` events at known
coordinates. Test extraction zone entry, exit, re-entry. Test with
both prop-based VIP (ESP32 + GPS module) and player-app VIP.

**Phase dependency:** Phase 3 (player app with GPS reporting, VIP
role). Cannot be fully tested without Android hardware and GPS.

### 9.4 Hacking Terminal

**Concept:** An Android device running in kiosk mode presents a puzzle
(wire-cutting, code-cracking, pattern-matching). Solving the puzzle
emits a `hacking.solved` event that unlocks a code, captures a zone,
or triggers a custom effect.

**Lua design:**

`node.lua` (hacking role):
```lua
-- Pseudocode
local s = state.node { phase = "locked", puzzle_type = nil, solution = nil }

on("game.start", function()
  s.puzzle_type = params.puzzle_type  -- "wires", "code", "pattern"
  s.solution = generate_puzzle(params.difficulty, rand)
  ui.screen("puzzle", { type = s.puzzle_type, state = s.solution.display })
end)

on("display.touch", function(e)
  if s.phase == "locked" then
    local result = check_puzzle_input(s.solution, e)
    if result == "solved" then
      s.phase = "solved"
      emit("hacking.solved", { team = e.team, puzzle = s.puzzle_type }, { prio = "critical" })
      ui.screen("solved", { team = e.team })
    elseif result == "failed" then
      -- Optional: lockout timer
      if params.lockout_s then
        s.phase = "locked_out"
        after(params.lockout_s, function()
          s.phase = "locked"
          s.solution = generate_puzzle(params.difficulty, rand)
          ui.screen("puzzle", { type = s.puzzle_type, state = s.solution.display })
        end)
      end
    end
  end
end)
```

**Android shell dependency:** The hacking terminal needs the Phase 3
Android shell (Flutter app with `dart:ffi` bridge to the core). The
touch display capability (`display` with touch) maps to Flutter touch
events. The puzzle UI is rendered by Flutter screen templates.

**`field.lua` needs:** Optional. A `field.lua` could react to
`hacking.solved` to trigger cross-node effects (e.g., opening a door,
disabling defences).

**Test approach:** Simulator can test the logic with injected
`display.touch` events. Puzzle generation and verification are pure Lua
functions testable in unit tests. The actual touch interaction needs
an Android device.

**Phase dependency:** Phase 3 (Android shell, Flutter touch UI, kiosk
mode).

### Mode summary

| Mode | node.lua | field.lua | Phase 2 dep | Phase 3 dep | Hardware dep |
|------|----------|-----------|-------------|-------------|--------------|
| Master & Satellites | Yes | Yes | field.* API | NFC squad ID (engineer-only) | ESP32 boxes |
| Target Windows | Yes | No | -- | -- | Target addon |
| VIP / Payload | Optional | Yes | field.* API | Player app, GPS, VIP role | GPS module or phone |
| Hacking Terminal | Yes | Optional | -- | Android shell, Flutter UI | Android device |

---

## 10. ATAK / CoT

### Cursor-on-Target protocol

ATAK (Android Team Awareness Kit) uses the Cursor-on-Target (CoT)
XML format to share position and status information. CoT messages are
defined by MIL-STD-2045 and the CoT specification from MITRE.

**CoT message structure:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0"
       uid="atalaia-box-a3f1"
       type="a-f-G-E-X"
       time="2026-10-17T14:30:00Z"
       start="2026-10-17T14:30:00Z"
       stale="2026-10-17T14:31:00Z"
       how="m-g">
  <point lat="38.7223" lon="-9.1393" hae="0" ce="10" le="0"/>
  <detail>
    <contact callsign="Alpha Box"/>
    <remarks>Owner: Red Team, Phase: active, Battery: 85%</remarks>
    <__group name="Red" role="Team Member"/>
    <status battery="85"/>
    <track course="0" speed="0"/>
  </detail>
</event>
```

### CoT type codes

| Entity | CoT type | Meaning |
|--------|----------|---------|
| Prop (box) | `a-f-G-E-X` | Friendly ground equipment |
| Prop (captured by team) | `a-f-G-E-X` with group colour | Team-coloured marker |
| Player (friendly) | `a-f-G-U-C` | Friendly ground unit |
| Zone boundary | `u-d-f` | Drawing / feature |
| Extraction point | `b-m-p-s-p-i` | Point of interest |

### Transport

| Option | For | Against | Recommendation |
|--------|-----|---------|----------------|
| UDP multicast (239.2.3.1:6969) | Standard ATAK default; zero config | Requires multicast-capable network | **Primary** (field Wi-Fi) |
| TCP (port 4242) | Works over any IP; TAK Server compatible | Needs a connection | **Secondary** (remote via site server) |
| TAK Server | Full ATAK ecosystem integration | Heavy; requires a separate server | **Future** (Phase 5+) |

### Implementation

A Python module on the controller (`controller/atalaia_controller/atak.py`) that:

1. Subscribes to game events and node STATE messages.
2. Generates CoT XML for each node with a GPS fix.
3. Sends CoT messages via UDP multicast on the field Wi-Fi network.
4. Optionally forwards to the site server, which relays to remote ATAK
   clients via TCP.

The CoT emitter is a consumer of existing data (events, STATE, GPS
fixes). It adds no new protocol messages and does not modify game logic.

**No ATAK SDK licence required.** CoT is an open standard. Emitting
CoT XML over UDP/TCP requires no licence or SDK. ATAK plugins (which
run inside the ATAK app) would require the ATAK SDK, but Phase 4
only emits CoT -- it does not build an ATAK plugin.

### Test approach

- **Unit test**: verify CoT XML generation against known-good samples.
- **Integration test**: a mock CoT receiver (Python UDP listener) in
  CI verifies that the controller emits valid CoT during a simulated
  game.
- **Field test**: connect a real ATAK device to the field Wi-Fi and
  verify props appear on the map with correct positions and team colours.

---

## 11. Custom scenarios

### Design

Custom scenarios are built in the GM console from objective blocks.
Each scenario compiles to a `field.lua` script that runs on the
controller.

### Objective blocks

| Block | Parameters | Completion condition |
|-------|-----------|---------------------|
| **Capture and hold** | target node, team/squad, duration | Team holds the target for the specified duration |
| **Enter a code** | target node, code string, team/squad | The correct code is entered on the target node |
| **Scan tags** | tag count, tag UIDs, target node, team/squad | N tags scanned at the target node |
| **Escort** | VIP node/player, destination zone, team/squad | VIP reaches the destination zone |
| **Destroy** | target node (bomb role), team/squad | Bomb explodes on the target node |
| **Defend** | target node, team/squad, duration | Team prevents enemy capture for the duration |
| **Survive** | team/squad, minimum lives | Team has at least N lives remaining at game end |

### Objective properties

Each objective has:
- **Target**: a prop, a zone, a player, or a tag set.
- **Conditions**: time windows (active from minute 10 to minute 45),
  hold durations, codes, prerequisites.
- **Effect**: points awarded, win/loss condition, reveal information
  (e.g., show the location of the next objective to one squad).
- **Visibility**: who sees it in the player app (one squad, one team,
  everyone, nobody until unlocked).
- **Dependencies**: objective B unlocks only after objective A is
  completed.

### Scenario manifest (YAML DSL)

```yaml
id: org.atalaia.scenario.custom-weekend
name: "Operation Foxhound"
teams: [alpha, bravo]
squads:
  alpha: [alpha-1, alpha-2]
  bravo: [bravo-1, bravo-2]

objectives:
  - id: intel
    type: scan_tags
    team: alpha
    squad: alpha-1
    target: box-a
    params:
      tag_count: 3
    visibility: squad  # only alpha-1 sees this
    effect:
      points: 50
      reveal: [rescue]  # completing this reveals the 'rescue' objective

  - id: rescue
    type: escort
    team: alpha
    squad: alpha-2
    target: vip-player
    params:
      destination: extraction-zone
    visibility: hidden  # hidden until 'intel' is complete
    depends_on: [intel]
    effect:
      win: true

  - id: defend_hq
    type: defend
    team: bravo
    target: box-b
    params:
      duration_s: 2700  # 45 minutes
    visibility: team
    effect:
      points: 100
```

### Compilation to field.lua

The GM console (or a CLI tool) compiles the scenario manifest into a
`field.lua` script. The compiler:

1. Parses the YAML manifest.
2. Generates Lua code for each objective block using templates.
3. Wires dependencies (objective B listens for objective A's
   completion event).
4. Handles visibility (emits `scenario.objective.revealed` events to
   the player app, filtered by squad/team).
5. Handles effects (score changes, win conditions, reveals).

The generated `field.lua` is saved as a preset and can be shared in
the mode registry.

### Test approach

- **Unit tests**: scenario compiler generates valid Lua for each block
  type.
- **Simulator tests**: compile a multi-objective scenario, run it in
  the simulator, verify objective completion, dependency chains, and
  effects.
- **No hardware dependency** for the compiler and logic tests. Field
  testing with real objectives requires the full milsim setup.

---

## 12. Weekend milsim gate

### What "a weekend milsim runs on the platform end to end" means

The gate is met when all of the following are demonstrated in a single
weekend event (two days, 8-16 hours of active play per day):

#### Equipment

- 10-20 Field Boxes and Satellites (ESP32), with batteries for a full
  day.
- 1 Raspberry Pi field controller with a LoRa radio modem.
- 1-3 dedicated repeater nodes for range extension.
- 1 Android device with 4G as the internet bridge.
- Site server running (self-hosted on a VPS or on-site mini PC).
- Player app on 20+ player phones (Android and iOS).
- 1-2 ATAK devices on marshal/GM phones.

#### Functional requirements

| Requirement | How to verify |
|-------------|---------------|
| Game modes work | Run at least 3 different modes across the weekend (Domination, Bomb, Master and Satellites) |
| Props survive a full day | Zero battery-related failures; all props report >10% at end of day |
| LoRa mesh covers the field | Zero lost captures across all games |
| Controller failover works | Planned failover test: kill the Pi, verify backup election, verify zero lost events |
| Player app works | 20+ players use the app for role-based views, respawn check-in, and chrono |
| Chrono check-in works | All replicas registered, check-in readings stored, spot checks compared |
| Site server syncs | Event logs, scores, and chrono records appear on the site server within 60 s of game end |
| ATAK integration works | Props and zone owners visible on ATAK maps on marshal phones |
| Remote GM works | A remote GM views live scores and events through the site server |
| Custom scenario runs | At least one game uses a custom scenario with 3+ objectives |
| Data survives | After the weekend, the site server has complete game history, scores, and chrono records |

#### Pass criteria (quantitative)

- Zero lost captures across all games (same as Phase 2 gate, but at
  milsim scale).
- Event sync latency: 95th percentile < 5 s from event generation to
  site server persistence.
- Chrono registry: 100% of check-in records are signed and stored.
- Player app: > 90% of registered players successfully join at least
  one game via the app.
- ATAK: > 80% of GPS-equipped props visible on ATAK within 30 s of
  game start.
- Battery: zero props die before end of the scheduled game.

#### Staging approach

The gate does not need to be tested all at once. Build up in stages:

1. **Desk test**: 5 boxes + controller + site server, no players.
   Verify sync, event persistence, remote GM.
2. **Small game test**: 5 boxes, 5 players with the app, chrono
   check-in, one mode. Half-day.
3. **Scale test**: 10-15 boxes, 10+ players, multiple modes, ATAK,
   custom scenario. Full day.
4. **Weekend gate**: full setup, two days, 20+ players, all features.

---

## 13. Security threat model

### Architecture

```
Internet
  |
  +-- Site server (HTTPS, PostgreSQL)
  |     |
  |     +-- Reverse proxy (Caddy/nginx, TLS termination)
  |     +-- FastAPI application
  |     +-- PostgreSQL
  |
  +-- 4G bridge (Android phone)
  |
Field Wi-Fi (controller network)
  |
  +-- Field controller (Raspberry Pi)
  |     |
  |     +-- USB radio modem (ESP32, AES-CCM)
  |     +-- MQTT broker (Mosquitto)
  |     +-- REST API (FastAPI)
  |     +-- WebSocket
  |
  +-- Props (ESP32, LoRa)
  +-- GM console (browser)
  +-- Player phones (Wi-Fi or 4G)
```

### Threat analysis

| Threat | Attack surface | Mitigation |
|--------|---------------|------------|
| Unauthorised access to site server | HTTPS endpoint | TLS 1.3; strong passwords + TOTP for admin/GM/marshal; rate limiting; fail2ban |
| SQL injection | REST API inputs | SQLAlchemy ORM (parameterised queries); Pydantic input validation |
| XSS on GM console / player app | Web UI | Content Security Policy; no inline scripts; Preact auto-escapes |
| CSRF | State-changing endpoints | SameSite cookies; CSRF tokens on form endpoints |
| Session hijacking | JWT tokens | HTTP-only cookies; short-lived access tokens; refresh token rotation |
| Man-in-the-middle (site server) | HTTPS | TLS 1.3 mandatory; HSTS; certificate pinning in player app |
| Man-in-the-middle (field Wi-Fi) | Controller API | WPA2/3 on field Wi-Fi; GM/read tokens for API access |
| Brute-force passwords | Login endpoint | Argon2id; rate limiting (5 attempts, 15 min lockout); TOTP for sensitive roles |
| Data exfiltration from site server | Database | Encrypted at rest (PostgreSQL TDE or volume encryption); encrypted backups |
| Rogue field controller | Sync API | Mutual authentication (API keys); field registration approval |
| Denial of service | Site server | Rate limiting; connection limits; Cloudflare or similar CDN/WAF |
| Chrono record tampering | Chrono API | Append-only records; marshal signature (HMAC-SHA256); audit log |
| Position spoofing | Player app GPS | Server-side plausibility checks (speed, distance); GPS is informational, not game-deciding for most modes |
| Modified player app | Player app | Server filters positions per role; sensitive data never sent to unauthorised roles |

### AuthZ model

```
Resource            Required role
---                 ---
Game control        gm
Score adjustment    gm
Broadcast message   gm
Chrono check-in     marshal
Chrono spot check   marshal
Player position     marshal, gm (all); squad_leader (own squad); player (own, if mode allows)
Field config        admin
User management     admin
Device management   admin, gm
Sync API            controller (API key)
Public scoreboard   spectator, anyone (if field enables public)
```

Role checks are enforced at the API layer (FastAPI dependency
injection). The player app never receives data its role may not see.

---

## 14. CI approach

### Site server testing

```yaml
# .github/workflows/server.yml (conceptual)
services:
  postgres:
    image: postgres:16-alpine
    env:
      POSTGRES_PASSWORD: test
      POSTGRES_DB: atalaia_test

steps:
  - run: pip install -r server/requirements.txt
  - run: pytest server/tests/ -v --cov=server/src
```

Tests:
- **Unit tests**: models, schemas, auth, chrono calculations, scenario
  compiler, CoT XML generation.
- **Integration tests**: full API tests with a real PostgreSQL
  database (docker-compose in CI).
- **Sync tests**: mock controller pushes events to the site server;
  verify persistence and query.
- **GDPR tests**: verify export, delete, and anonymisation endpoints.
- **Auth tests**: login, TOTP, role checks, rate limiting, session
  management.

### Advanced modes testing

```yaml
# In the existing simulator test suite
steps:
  - run: pytest modes/master-and-satellites/tests/ -v
  - run: pytest modes/target-windows/tests/ -v
  - run: pytest modes/vip-payload/tests/ -v
  - run: pytest modes/hacking-terminal/tests/ -v
```

Each mode has event-sequence tests (YAML format) that run in the
simulator. Multi-node modes (Master and Satellites, VIP) use the
Phase 2B `FieldController` and `RadioModel` in the simulator.

### ATAK testing

```python
# controller/tests/test_atak.py
def test_cot_xml_generation():
    """Verify CoT XML matches the schema and contains correct data."""
    xml = generate_cot(node_id="box-a3f1", lat=38.7223, lon=-9.1393,
                       team="red", battery=85)
    root = ET.fromstring(xml)
    assert root.tag == "event"
    assert root.get("type") == "a-f-G-E-X"
    point = root.find("point")
    assert float(point.get("lat")) == pytest.approx(38.7223)

def test_cot_udp_emission():
    """Start a mock UDP receiver, emit CoT, verify receipt."""
    ...
```

### Custom scenario testing

```python
# server/tests/test_scenario_compiler.py
def test_compile_capture_and_hold():
    """Verify the compiler generates valid field.lua for a capture objective."""
    scenario = load_yaml("test_scenarios/simple_capture.yaml")
    lua = compile_scenario(scenario)
    # Run the generated Lua in the simulator
    sim = Simulation()
    ctrl = FieldController(sim)
    ctrl.load_field_script(lua)
    # ... verify objective completion
```

---

## 15. Assumptions about earlier phases

| # | Assumption | Phase dependency | Impact if wrong |
|---|-----------|------------------|-----------------|
| A1 | Phase 2D delivers a working Python controller with FastAPI REST API, SQLite store, MQTT publisher, and WebSocket stream | Phase 2 | **Critical**: site server shares the framework and sync protocol. If the controller API differs, the sync layer must adapt. |
| A2 | Phase 2D delivers the GM console as a Preact+HTM PWA served by FastAPI | Phase 2 | **Moderate**: the site server serves the same console. If the console framework changes, the site server's static file mount adapts trivially. |
| A3 | Phase 2C delivers `field.*` API and `state.field{}` in the core (confirmed complete per STATUS.md) | Phase 2 | **Low**: already verified complete. |
| A4 | Phase 3 delivers the Android shell (Flutter + dart:ffi) with kiosk mode | Phase 3 | **High**: Hacking Terminal mode cannot function without it. VIP mode loses player-app GPS. |
| A5 | Phase 3 delivers the player app with role-based views on Android and iOS | Phase 3 | **High**: the site server's player app backend, chrono check-in, and position filtering depend on the app existing. |
| A6 | Phase 3 delivers GPS reporting from the player app to the controller | Phase 3 | **High**: VIP / Payload mode requires GPS from the VIP's phone. ATAK CoT for player positions requires GPS. |
| A7 | Phase 3 delivers NFC squad identification (team + squad from NFC tags) | Phase 3 | **Moderate**: Engineer-only satellite capture in Master and Satellites depends on squad ID. Without it, any team member can capture satellites. |
| A8 | Phase 3 delivers the chrono check-in flow in the player app | Phase 3 | **Moderate**: chrono registry on the site server consumes records from the check-in flow. Without it, chrono records must be entered via the GM console or a separate marshal tool. |
| A9 | Phase 3 delivers BLE join for Android devices | Phase 3 | **Low**: site server does not depend on BLE join directly. Players can join via QR over Wi-Fi. |
| A10 | Phase 3 delivers Hold-All Domination, Last Stand, Kill Confirmed, and other multi-node modes that validate the `field.lua` API under real game conditions | Phase 3 | **Moderate**: Phase 4 modes build on the same API. If Phase 3 modes reveal field API issues, Phase 4 modes must adapt. |
| A11 | Phase 1 delivers the target addon hardware (piezo sensor + MCU + LED ring on the addon bus) | Phase 1 | **High**: Target Windows mode cannot function without the target addon. The `hit` capability depends on hardware. |
| A12 | The controller's WiFi network supports UDP multicast for ATAK CoT | Phase 2 | **Low**: standard on most WiFi APs. If not, fall back to TCP unicast. |
| A13 | The site server can reach the controller via HTTPS through the 4G bridge | Phase 3 | **Moderate**: remote GM console and live sync depend on this link. Without it, the site server works in batch mode (post-game upload). |

---

## 16. What needs hardware or real deployment

| Feature | Hardware required | Earliest testable |
|---------|-------------------|-------------------|
| Target Windows mode | Target addon (piezo sensor + MCU + LED ring) | After Phase 1 addon build |
| VIP / Payload GPS tracking | Android phone with GPS, or ESP32 + GPS module | After Phase 3 player app |
| Hacking Terminal | Android phone or tablet in kiosk mode | After Phase 3 Android shell |
| ATAK / CoT | Real ATAK app on an Android phone; field Wi-Fi with multicast | Phase 4 field test |
| Master and Satellites (full) | ESP32 Satellite builds (2-4 units) | Phase 2 hardware (already spec'd) |
| Chrono check-in (end-to-end) | Chronograph (commercial or DIY), NFC tags, marshal phone | After Phase 3 player app |
| Site server sync (end-to-end) | Raspberry Pi controller + 4G bridge + VPS or mini PC | After Phase 2D controller |
| Weekend milsim gate | 10-20 ESP32 boxes, Pi controller, repeaters, 4G bridge, site server, 20+ player phones, ATAK devices | After all other Phase 4 work |

---

## 17. Risks and mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | Phase 2D (controller) is not complete when Phase 4 design begins | High (Phase 2 stopped before D) | High | Phase 4 is design-only; implementation depends on Phase 2D completion. Design the sync protocol abstractly enough that controller API details can be filled in later. |
| R2 | Phase 3 is not complete, blocking VIP, Hacking Terminal, and chrono | High (Phase 3 in parallel design) | High | Design Phase 4 modes with clear Phase 3 interface assumptions. Master and Satellites and Target Windows can proceed without Phase 3. |
| R3 | Multi-tenant hosted mode introduces complexity (isolation, billing, data export) | Medium | Medium | Start with single-tenant self-hosted. Add multi-tenant as a second step with PostgreSQL schema isolation. |
| R4 | GDPR compliance requires legal review | Medium | Medium | Ship templates and defaults; flag that legal review is required before production hosted service. |
| R5 | Custom scenario compiler generates incorrect Lua | Medium | Medium | Extensive test coverage with known-good scenarios. Generated Lua is human-readable for debugging. |
| R6 | Weekend milsim gate requires all phases to work together | High | High | Stage the gate test (desk, small game, scale, weekend). Accept partial passes with documented gaps. |
| R7 | CoT XML format variations across ATAK versions | Low | Low | Target ATAK 4.x CoT schema; test with the current ATAK release. |
| R8 | VIP GPS accuracy outdoors is insufficient for extraction zone detection | Medium | Medium | Use a generous extraction zone radius (10-25 m). Supplement with NFC check-in at the extraction point. |
| R9 | Target addon piezo sensor needs tuning for different impact types | Medium | Low | Configurable threshold in the target addon firmware; document calibration procedure. |
| R10 | Remote GM console latency over 4G is too high for real-time control | Low | Low | The controller runs all game logic locally. Remote GM is for observation and non-time-critical commands. |
| R11 | Controller and site server Python code duplication | Medium | Medium | Extract shared code into an `atalaia-common` package (event schemas, sync protocol, auth utilities). |
| R12 | PostgreSQL adds operational complexity for small fields | Medium | Medium | Docker-compose with PostgreSQL is the standard deployment. For single-machine setups where the site server runs alongside the controller, document the setup clearly. SQLite is not an option for the site server due to concurrent access requirements. |

---

## Phase 2 and 3 handoff (2026-10-18)

Phase 2 implementation (A-E) is complete and Phase 3 design is
complete (not yet built). This section checks the assumptions from
section 15, lists the new interfaces from Phase 3, and records the
event ID allocation.

### Assumption check

| # | Assumption | Verdict | Resolution |
|---|-----------|---------|------------|
| A1 | Phase 2D delivers a working Python controller with FastAPI REST API, SQLite store, MQTT publisher, and WebSocket stream | **HOLDS** (with differences) | Package is `controller/atalaia_controller/`, not `controller/src/`. Auth uses bearer tokens (read token, GM token), not JWT/sessions. SQLite schema 2 with events UNIQUE on `(game_id, node_id, seq, game_time, type)`. MQTT via Mosquitto with per-user ACLs (`deploy/mosquitto.conf`, `deploy/atalaia.acl`). One game per controller at a time (D14). |
| A2 | Phase 2D delivers the GM console as a Preact+HTM PWA served by FastAPI | **HOLDS** | Preact 10.24.3 + HTM 3.1.1 + qrcode-generator, served at `/console/`. Class components only (no hooks, CSP forbids inline import map). |
| A3 | Phase 2C delivers `field.*` API and `state.field{}` in the core | **HOLDS** | Confirmed complete. The controller's `field.lua` runs via ctypes to the same C core the simulator uses. |
| A4 | Phase 3 delivers the Android shell (Flutter + dart:ffi) with kiosk mode | **HOLDS** | Phase 3 design complete, not yet built. Interface assumptions unchanged. |
| A5 | Phase 3 delivers the player app with role-based views on Android and iOS | **HOLDS** | Phase 3 adds player tokens (HMAC-SHA256-signed JSON, not JWT) and position reporting (`POST /api/v1/positions`). |
| A6 | Phase 3 delivers GPS reporting from the player app to the controller | **HOLDS** | Position reports via `POST /api/v1/positions`, authenticated with player token. GPS NOT on the Field Box (E21); positions come from phones/pods only. |
| A7 | Phase 3 delivers NFC squad identification (team + squad from NFC tags) | **HOLDS** | NFC tags use HMAC-SHA256 with game key, truncated to 16 bytes. |
| A8 | Phase 3 delivers the chrono check-in flow in the player app | **CHANGED** | Chrono records are JSON with Ed25519 signature per marshal (ADR-P3-7), not HMAC-SHA256 from the password. Aligns with ADR-P4-5. Record fields: reading_id, replica_id, player_id, type, velocity_mps, bb_weight_g, energy_j, chrono_id, marshal_id, marshal_name, game_id, field_id, timestamp, signature. |
| A9 | Phase 3 delivers BLE join for Android devices | **HOLDS** | Unchanged. |
| A10 | Phase 3 delivers Hold-All Domination, Last Stand, Kill Confirmed and other modes | **CHANGED** | Hold-All Domination and Last Stand moved to the Phase 2 mode pack (decision R6). Kill Confirmed remains Phase 3. |
| A11 | Phase 1 delivers the target addon hardware | **HOLDS** | Unchanged. |
| A12 | The controller's WiFi network supports UDP multicast for ATAK CoT | **HOLDS** | Unchanged. |
| A13 | The site server can reach the controller via HTTPS through the 4G bridge | **HOLDS** (auth model changed) | The site server authenticates to the controller with bearer tokens (GM token for writes, read token for reads), not the API-key scheme the ADR designed. The controller authenticates to the site server with a 256-bit API key. Auth is asymmetric. |

### Phase 3 interfaces the site server will consume

These are concrete interfaces from the Phase 3 design that Phase 4
must integrate with. Phase 3 is designed but not yet built; these are
checked against the design documents.

1. **Chrono reading record** (ADR-P3-7): JSON with Ed25519 signature.
   Fields: `reading_id`, `replica_id`, `player_id`, `type`
   (checkin/spotcheck/retest), `velocity_mps`, `bb_weight_g`,
   `energy_j`, `chrono_id`, `marshal_id`, `marshal_name`, `game_id`,
   `field_id`, `timestamp`, `signature`. The site server's chrono
   registry (section 7, ADR-P4-5) consumes these records.

2. **Replica registry**: `replica_id`, `owner_player_id`, `type`
   (aeg/gbb/hpa/bolt_action/dmr/sniper/pistol/shotgun), `class`,
   `make_model`, `registered_at`, `tag_type`, `tag_uid`. Maps to
   the `replicas` table in ADR-P4-1 (note: Phase 3 adds `sniper`
   to the replica type enum).

3. **Limit templates**: YAML files with classes mapping to
   `max_energy_j`, `max_fps_020`, `med_m`, `fire_mode`; per-field
   overrides. The site server's `field_joule_limits` table (ADR-P4-1)
   is compatible; `max_fps_020` and `fire_mode` are new fields to add.

4. **Player tokens**: HMAC-SHA256-signed JSON (not JWT) with
   `player_id`, `team`, `squad`, `role`, `game_id`, `exp`; signed
   with the game key. The site server does not issue player tokens
   (the controller does) but must understand them for position
   filtering if it receives live position data.

5. **Position reports**: `POST /api/v1/positions` (authenticated
   with player token). The site server may proxy or relay these for
   remote GM and ATAK.

6. **Controller CA**: `GET /api/v1/controller/ca`; SHA-256 fingerprint
   in join payload key 13. The site server does not need the CA
   directly but must know about it for the sync TLS configuration.

7. **NFC tags**: HMAC-SHA256 with game key, truncated to 16 bytes.
   Relevant for the chrono check-in flow (tag UID → replica lookup).

### Event ID allocation

Phase 3 reserves event IDs 25-27 and 33-41 (kill.confirmed,
kill.denied, team.eliminated, money.collected, money.deposited,
chrono.checkin, chrono.spotcheck, visibility.granted,
visibility.expired, node.tamper, pod.connected, pod.disconnected).
The Phase 2 mode pack (R6) owns IDs 28-32 (holdall.*, laststand.*).

**Phase 4 events start at ID 42.** The eight new events
(`satellite.captured`, `satellite.neutralized`, `vip.extracted`,
`hacking.solved`, `scenario.objective.completed`,
`scenario.objective.failed`, `scenario.objective.revealed`,
`scenario.started`) will be allocated IDs 42-49.

### Codebase inventory corrections

- The controller package is `controller/atalaia_controller/`, not
  `controller/src/`. Updated in section 2.
- The ATAK emitter path is `controller/atalaia_controller/atak.py`.
  Updated in section 10.
- The scenario compiler is a shared Python library at
  `controller/atalaia_controller/scenarios/` (maintainer decision
  P4-1), not `server/src/services/scenario_compiler.py`. Updated in
  the file list below.

---

## 18. Recommendations

### Architecture decisions needed (for ADR phase)

1. **ADR-P4-1**: Site server database schema (PostgreSQL tables,
   indexes, constraints, migrations). Tool: Alembic.
2. **ADR-P4-2**: Authentication and session management (Argon2id, JWT,
   TOTP, refresh tokens). Library: `python-jose` or `PyJWT` + `pyotp`.
3. **ADR-P4-3**: Sync protocol between controller and site server
   (transport, authentication, batch format, error handling, offline
   buffering).
4. **ADR-P4-4**: Multi-tenant isolation (schema-per-field vs
   row-level security vs separate databases).
5. **ADR-P4-5**: Chrono record signing (HMAC-SHA256 vs Ed25519; key
   lifecycle; verification).
6. **ADR-P4-6**: Custom scenario DSL (YAML manifest schema, objective
   block types, compilation to field.lua, dependency graph validation).
7. **ADR-P4-7**: ATAK / CoT integration (transport, CoT type mapping,
   update frequency, TAK Server compatibility).
8. **ADR-P4-8**: GDPR implementation (retention policies, export
   format, anonymisation strategy, data processing agreement template).
9. **ADR-P4-9**: Geo utilities in the script API (Haversine,
   point-in-polygon, zone definition format).
10. **ADR-P4-10**: Site server deployment (docker-compose, reverse
    proxy, TLS, backup strategy).

### Implementation order

1. **Site server skeleton** (FastAPI + PostgreSQL + Alembic + auth).
   No Phase 3 dependency.
2. **Sync protocol** (controller pushes events/scores/chrono to site
   server). Depends on Phase 2D controller.
3. **Chrono registry** (replica registration, check-in records, spot
   checks, marshal signatures). Depends on Phase 3 chrono flow for
   end-to-end, but the API can be built and tested independently.
4. **Master and Satellites mode**. No Phase 3 dependency for basic
   functionality.
5. **Target Windows mode**. Depends on target addon hardware.
6. **ATAK / CoT emitter**. No Phase 3 dependency (uses existing node
   GPS data).
7. **Custom scenario DSL and compiler**. No Phase 3 dependency for
   the compiler; some objective types (Escort, Survive) need Phase 3
   player app.
8. **VIP / Payload mode**. Depends on Phase 3 GPS and player app.
9. **Hacking Terminal mode**. Depends on Phase 3 Android shell.
10. **Remote setup** (device health dashboard, game scheduling, remote
    GM console). Depends on site server + sync.
11. **GDPR implementation** (export, delete, retention, privacy notice).
    Can be built in parallel with the site server.
12. **Weekend milsim gate**. Last; depends on everything above.

### Files to create (Phase 4)

```
server/
    src/
        __init__.py
        main.py                 # FastAPI application
        config.py               # Configuration (env vars, secrets)
        auth.py                 # Authentication, TOTP, JWT
        models.py               # SQLAlchemy models
        schemas.py              # Pydantic schemas
        api/
            __init__.py
            accounts.py         # User CRUD, login, TOTP
            games.py            # Game history, event log queries
            chrono.py           # Chrono registry endpoints
            sync.py             # Controller sync endpoints
            devices.py          # Device health, firmware
            scheduling.py       # Game scheduling
            scenarios.py        # Custom scenario CRUD
            gdpr.py             # Data export, deletion
        services/
            __init__.py
            sync_service.py     # Sync logic
            chrono_service.py   # Chrono business logic
            scenario_compiler.py # YAML -> field.lua
            cot_emitter.py      # ATAK / CoT XML generation
        middleware/
            __init__.py
            auth_middleware.py   # JWT verification, role injection
            rate_limit.py       # Rate limiting
    migrations/
        alembic.ini
        versions/               # Database migration scripts
    tests/
        conftest.py
        test_auth.py
        test_chrono.py
        test_sync.py
        test_scenario_compiler.py
        test_cot.py
        test_gdpr.py
        test_api_*.py
    requirements.txt
    pyproject.toml
    Dockerfile
    docker-compose.yml

controller/atalaia_controller/
    atak.py                     # CoT emitter (controller-side)
    sync_client.py              # Site server sync client
    scenarios/                  # Custom scenario compiler (shared library; site server imports it)

modes/
    master-and-satellites/
        mode.yaml
        node.lua
        field.lua
        tests/
    target-windows/
        mode.yaml
        node.lua
        tests/
    vip-payload/
        mode.yaml
        node.lua
        field.lua
        tests/
    hacking-terminal/
        mode.yaml
        node.lua
        tests/

docs/
    phase-4-site-server/
        RESEARCH.md             # This file
        ADR.md                  # Architecture decisions
        PLAN.md                 # Implementation plan
        STATUS.md               # Progress tracking
    templates/
        privacy-notice-pt.md    # GDPR privacy notice (Portuguese)
        privacy-notice-en.md    # GDPR privacy notice (English)
        data-processing-agreement.md  # For hosted site servers
```

### Patterns to follow

- **Event schemas**: extend `protocol/schema/events.yaml` with new
  events (satellite.captured, satellite.neutralized, vip.extracted,
  hacking.solved, scenario.objective.completed, etc.).
- **Mode package format**: follow the existing `modes/domination/` and
  `modes/bomb/` structure.
- **Test format**: YAML event sequences for modes; pytest for the site
  server.
- **ADR pairing**: one ADR per significant design decision.
- **SPDX headers**: AGPL-3.0-or-later for server and controller code;
  GPL-3.0-or-later for modes; CC-BY-SA-4.0 for docs.
- **Docker-only builds**: no C compiler on host; all compilation in
  Docker images.

### Key design decisions to resolve early

1. **Shared Python package or monorepo?** The controller and site
   server share event schemas, sync protocol, and auth utilities.
   Options: (a) shared `atalaia-common` package installed as a
   dependency; (b) import directly from the monorepo. Recommendation:
   monorepo imports for now (simpler); extract a package if the repo
   grows.

2. **PostgreSQL migration strategy.** Alembic (the SQLAlchemy migration
   tool) is the standard choice. Migrations must be reversible for
   rollback safety.

3. **Where does the scenario compiler run?** Options: (a) in the GM
   console (JavaScript); (b) on the site server (Python); (c) on the
   controller (Python). Recommendation: site server, with the GM
   console sending the scenario YAML and receiving the compiled
   field.lua. The controller receives the compiled script via the
   normal preset push.

4. **Chrono record integrity.** Marshal signatures must survive
   password changes. An Ed25519 keypair per marshal (generated at role
   assignment, private key in the app's secure storage) is more robust
   than HMAC-SHA256 derived from the password. Decision for ADR.
