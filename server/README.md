# Site server (optional)

A self-hosted server for fields with internet: accounts, field setup, remote management, the player app backend, game history and the chrono registry. It never runs game logic; games keep working without it.

Clubs without IT support will be able to use hosted site servers run by the community hub.

Licence: AGPL-3.0-or-later.

## Status

Phase 4 plan phases 10, 11, 12 and 13 are built, and tested on a computer only. Plan phase 10 is the skeleton every later plan phase builds on: the application factory, its settings, the async database layer on PostgreSQL 16, the first migration (the base tables), `GET /api/v1/health` and `GET /api/v1/metrics`, security headers on every response, the server's own image, and the tests with their tooling. Plan phase 11 adds accounts, sessions and roles: registration, login with a TOTP step, rotating refresh tokens, lockouts and rate limits, per-field roles, the audit log and `python -m atalaia_server create-admin`. Plan phase 12 adds the personal data rights: access, export, rectification and erasure of one's own account, consent records, the daily retention purge, and privacy notice and DPA templates. Plan phase 13 adds the controller sync: field controllers push their games, event logs, score counters and nodes with a field API key, offline first and replay-safe, and the site server keeps them with per-game roles and a small games API; it has run against the real controller in tests, not yet over a real 4G link (HW1). Not yet: the chrono registry (plan phase 14), scheduling and registration (15-17), game history views (20), deployment with HTTPS (Caddy, setup and backups) in plan phase 22. See [docs/phase-4-site-server/PLAN.md](../docs/phase-4-site-server/PLAN.md).

## Layout

| Path | What it is |
| --- | --- |
| [`atalaia_server/app.py`](atalaia_server/app.py) | `create_app()`: the FastAPI app; the engine is made when it starts and disposed when it stops |
| [`atalaia_server/config.py`](atalaia_server/config.py) | Settings from `ATALAIA_*` environment variables (below); plain Python |
| [`atalaia_server/db.py`](atalaia_server/db.py) | SQLAlchemy 2's async engine on asyncpg, sessions per request, the health ping |
| [`atalaia_server/models.py`](atalaia_server/models.py) | The ORM models: `fields`, `users`, `roles` (seeded with ADR-P4-1's seven), `user_field_roles`, `sessions`, `audit_log`, `refresh_tokens`, `consents`; the sync's `field_api_keys`, `controllers`, `games`, `game_events`, `game_node_scores`, `game_nodes`, `user_game_roles` |
| [`atalaia_server/ids.py`](atalaia_server/ids.py) | UUIDv7 keys (RFC 9562), time-ordered; the database's `gen_random_uuid()` is the fallback |
| [`atalaia_server/security_headers.py`](atalaia_server/security_headers.py) | HSTS, `nosniff`, `X-Frame-Options`, the content security policy, the referrer policy |
| [`atalaia_server/api/health.py`](atalaia_server/api/health.py) | Health and metrics |
| [`atalaia_server/api/auth.py`](atalaia_server/api/auth.py) | Register, login, the TOTP step, refresh, logout, `GET /api/v1/me`, TOTP enrolment |
| [`atalaia_server/api/fields.py`](atalaia_server/api/fields.py) | Fields and per-field roles |
| [`atalaia_server/passwords.py`](atalaia_server/passwords.py) | Argon2id hashes and the password policy, with the breached list in [`data/`](atalaia_server/data/) |
| [`atalaia_server/totp.py`](atalaia_server/totp.py) | TOTP (RFC 6238) and the encrypted seeds |
| [`atalaia_server/tokens.py`](atalaia_server/tokens.py) | Keys derived from the secret key, access tokens, the TOTP login step, refresh tokens |
| [`atalaia_server/auth.py`](atalaia_server/auth.py) | Who is calling and which roles count (re-read from the database on every request) |
| [`atalaia_server/ratelimit.py`](atalaia_server/ratelimit.py) | Lockouts and the per-address request limit |
| [`atalaia_server/audit.py`](atalaia_server/audit.py) | Audit log rows |
| [`atalaia_server/api/me.py`](atalaia_server/api/me.py) | A person's rights on their own account: access, export, rectification, a new password, erasure |
| [`atalaia_server/personal_data.py`](atalaia_server/personal_data.py) | Every table with personal data, for access, export, erasure and the retention purge; consent records |
| [`atalaia_server/sync.py`](atalaia_server/sync.py), [`api/sync.py`](atalaia_server/api/sync.py) | The controller sync: API keys, the merge rules, the endpoints and the stream ([protocol/sync.md](../protocol/sync.md)); bodies are checked by the controller's own `atalaia_controller/sync_format.py` |
| [`atalaia_server/api/games.py`](atalaia_server/api/games.py) | Synced games (their totals, counters, nodes and events) and per-game roles |
| [`atalaia_server/cli.py`](atalaia_server/cli.py) | `python -m atalaia_server create-admin` and `purge` |
| [`migrations/`](migrations/), [`alembic.ini`](alembic.ini) | Alembic, async; one reversible migration per plan phase (`0001_base`, `0002_accounts`, `0003_personal_data`, `0004_sync`) |
| [`requirements.in`](requirements.in), [`requirements.txt`](requirements.txt) | Dependencies; the `.txt` pins every package with its PyPI hashes (`requirements-test.*`: the tests' extras) |
| [`Dockerfile`](Dockerfile) | The image: the core built in its own stage, then `python:3.12-slim` (pinned by digest) with the requirements and the Python shared with the controller; target `test` adds the tests |
| [`docker-compose.yml`](docker-compose.yml) | The server and `postgres:16-alpine`, for a local trial (Caddy comes in plan phase 22) |
| [`docker-compose.test.yml`](docker-compose.test.yml) | The test image next to an ephemeral PostgreSQL in a tmpfs |
| [`tests/`](tests/) | `unittest` against PostgreSQL 16 (`run.sh` runs them in the image) |

The site server imports the Python it shares with the field controller (the chrono verifier, the player-token codec, the image checks, the mode loader and its bindings to the C core) from `controller/atalaia_controller/` and `simulator/atalaia_sim/`. That code stays free of FastAPI, pydantic and SQLAlchemy (decision P4R16), because the controller runs on Raspberry Pi OS's own packages; `tests/test_shared_imports.py` checks it.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `ATALAIA_DATABASE_URL` | (required) | `postgresql+asyncpg://user:password@host:5432/database`; no other database is supported |
| `ATALAIA_SECRET_KEY` | (required) | At least 32 characters (`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`). The keys of the access tokens, the TOTP login step and the encrypted TOTP seeds are derived from it; changing it logs everyone out and makes every TOTP enrolment unreadable. Migrations do not need it |
| `ATALAIA_DB_POOL_SIZE` | 5 | Connections kept open (1-100) |
| `ATALAIA_DB_MAX_OVERFLOW` | 5 | Extra connections under load (0-100) |
| `ATALAIA_DB_TIMEOUT_S` | 5 | Connect and health-check timeout, seconds |
| `ATALAIA_METRICS_TOKEN` | (empty) | Optional bearer token for `/api/v1/metrics`, at least 32 characters, for a monitoring system; server administrators can always read the metrics |
| `ATALAIA_LOG_LEVEL` | `info` | `debug`, `info`, `warning` or `error` |
| `ATALAIA_PURGE_HOUR` | 3 | The hour (UTC, 0-23) at which the server runs the retention purge every day; `off` when something else runs `python -m atalaia_server purge` |
| `ATALAIA_PRIVACY_NOTICE_VERSION` | `template-2026-10-19` | The version of the privacy notice the field shows, stored with every consent; raise it when the notice changes (1-64 of letters, digits and `. _ : + -`) |

A setting that is present but not valid stops the server at start-up with a message; it is never replaced by its default. The database password never appears in logs.

## API so far

| Method | Path | Auth | Answer |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | none | 200 `{"status": "healthy", "database": "connected", "version", "uptime_s"}`, or 503 with `"unhealthy"` and `"unreachable"` when PostgreSQL does not answer |
| GET | `/api/v1/metrics` | a server administrator, or the metrics token | Uptime, version, the connection pool, the number of fields, users, active sessions, games, game events and controllers; 503 when the database is down |
| POST | `/api/v1/auth/register` | none | `{username, password, email?, consent: true}`: 201 with the account |
| POST | `/api/v1/auth/login` | none | `{username, password}`: a session (below), or `{"totp_required": true, "totp_session"}` for an account with TOTP |
| POST | `/api/v1/auth/login/totp` | none | `{totp_session, code}`: a session |
| POST | `/api/v1/auth/refresh` | the refresh cookie and `X-Atalaia-Refresh: 1` | A new session body and a new refresh cookie; the old one is spent |
| POST | `/api/v1/auth/logout` | Bearer | 204; the session ends and the cookie is cleared |
| GET | `/api/v1/me` | Bearer | The account, its roles per field, and whether this session passed TOTP |
| POST | `/api/v1/auth/totp/enrol` | Bearer | `{password}`: a new secret and its `otpauth://` URI, shown once |
| POST | `/api/v1/auth/totp/confirm` | Bearer | `{code}`: TOTP is on |
| POST | `/api/v1/auth/totp/disable` | Bearer | `{password, code}`: TOTP is off (refused while the account holds `admin`, `gm` or `marshal`) |
| GET | `/api/v1/me/data` | Bearer | Everything the server holds about the account, as JSON (below) |
| GET | `/api/v1/me/export` | Bearer | The same as a ZIP of JSON files with a README (`atalaia-export-<username>-<date>.zip`) |
| PATCH | `/api/v1/me` | Bearer | `{password, username?, email?}` (`email: null` removes it): the account |
| POST | `/api/v1/me/password` | Bearer | `{password, new_password}`: 204; every other session of the account ends |
| DELETE | `/api/v1/me` | Bearer | `{password, code?}` (the code when the account has TOTP): 204; the account is anonymised and logged out everywhere |
| POST | `/api/v1/fields` | a server administrator | `{name, slug, field_type?, timezone?}`: 201 with the field |
| GET | `/api/v1/fields` | Bearer | The fields the caller has a role on (every field for a server administrator) |
| GET | `/api/v1/fields/{field_id}/roles` | the field's `admin` or `gm` | Who holds which role |
| PUT | `/api/v1/fields/{field_id}/roles` | the field's `admin` (any role) or `gm` (`player`, `squad_leader`, `vip`, `spectator`) | `{username, role}`: 201 granted, 200 already held |
| DELETE | `/api/v1/fields/{field_id}/roles/{user_id}/{role}` | as for granting | 204 |
| POST | `/api/v1/fields/{field_id}/sync-keys` | the field's `admin` | `{label?}`: 201 with a new controller API key, shown once, and its fingerprint; 409 `too_many_keys` with two live |
| GET | `/api/v1/fields/{field_id}/sync-keys` | the field's `admin` | The keys: id, fingerprint, label, created, last used, revoked (never the key) |
| DELETE | `/api/v1/fields/{field_id}/sync-keys/{key_id}` | the field's `admin` | 204: revoked |
| POST | `/api/v1/sync/games`, `events`, `scores`, `nodes` | a field API key | The controller sync ([protocol/sync.md](../protocol/sync.md)) |
| WS | `/api/v1/sync/stream` | a field API key (on the upgrade) | The same four on one socket |
| GET | `/api/v1/fields/{field_id}/games` | any role on the field | The field's games, newest first |
| GET | `/api/v1/games/{game}` | a role on the field or the game | The game with its totals, counters and nodes (`params` for the field's `admin` and `gm` only) |
| GET | `/api/v1/games/{game}/events?after=&limit=` | the field's `admin`, `gm` or `marshal`, or the game's `gm` or `marshal` | The log in pages of up to 1,000 |
| GET, PUT, DELETE | `/api/v1/games/{game}/roles[/{user_id}/{role}]` | as for field roles | Per-game roles |
| GET | `/api/v1/openapi.json` | none | The OpenAPI document (the interactive pages are off: they load scripts from a CDN, which the content security policy forbids) |

A session body is `{access_token, token_type: "bearer", expires_in: 900, mfa, user}`, with the refresh token in a cookie. Errors are `{"detail": "<code>"}`, a code a client translates (`invalid_credentials`, `password_breached`, `totp_required`, `role_required`, `too_many_attempts`, ...).

## Accounts, sessions and roles

ADR-P4-2, with decisions S11-1 to S11-15:

- **Passwords:** Argon2id with 3 passes over 64 MiB, 4 lanes, a 16-byte salt and a 32-byte tag; an older hash is replaced at the next login. The policy is NIST SP 800-63B's: 10 to 1024 characters (after Unicode NFKC normalisation), no character-class rules, not the username, and not one of the 100,000 passwords seen most often in breaches (the UK NCSC's list, [`data/breached-passwords.txt`](atalaia_server/data/breached-passwords.txt): SecLists' `Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt` at commit `1a7bb9127eca9e6ff2fc0301c597fe6e16a0cb56`, unmodified, SHA-256 `c2e5696882c603b76bb67a47ee970897e5a76fc4c3f5547abe3d0ca340c576e0`, MIT as part of SecLists), compared whatever the case. An unknown username takes as long to refuse as a wrong password.
- **TOTP** (RFC 6238): 6 digits every 30 seconds, as authenticator apps do by default; one step of clock drift either side; each code is accepted once. Seeds are stored encrypted (Fernet). Accounts with `admin`, `gm` or `marshal` on any field, and server administrators, must have it, and those roles count only in a session that passed it.
- **Sessions:** a 15-minute access token (`Authorization: Bearer`; the server re-reads the session and the roles on every request, so a logout or a removed role counts at once) and a refresh token in the cookie `__Secure-atalaia_refresh` (HttpOnly, Secure, SameSite=Strict, sent only to `/api/v1/auth/refresh`). Each refresh spends the token and issues a new one; a spent token presented again ends the whole session. A session ends after 7 days without a refresh, and after 30 days in any case. The database keeps only SHA-256 hashes of refresh tokens.
- **Limits:** 5 failed logins for one username from one address lock that username at that address for 15 minutes, and 50 failed logins from one address, whatever the usernames, lock the address for 15 minutes (so one player's typos do not lock out a whole field behind one 4G address; decision S12-1); 5 wrong codes lock an account's TOTP for 15 minutes; 10 registrations an hour and 100 API requests a minute per address. The state is in memory, for the one worker process the image runs.
- **Roles** are per field: `player`, `squad_leader`, `vip`, `marshal`, `gm`, `spectator`, `admin`. A field's `admin` grants and revokes any of them; its `gm` the four player roles. The same roles can be granted on one synced game (plan phase 13), by the same people, with the same TOTP rule.
- **The audit log** records registrations, logins, failures and lockouts, refresh replays, logouts, TOTP changes, new fields and every role change, with the address; never a password, a code, a token or a username typed for an account that does not exist.

## Controller sync

ADR-P4-3 as amended, decisions P4R10-P4R13 and S13-1 to S13-12; the wire format is [protocol/sync.md](../protocol/sync.md), with shared vectors in [protocol/vectors/sync.json](../protocol/vectors/sync.json).

- **The controller opens every connection** (it sits behind a phone's 4G link): HTTPS requests and, optionally, one WebSocket. The site server never connects to a controller and holds none of its tokens.
- **API keys:** a field's admin makes one (`POST /api/v1/fields/{field}/sync-keys`, shown once) and sets it on the controller (`python3 -m atalaia_controller sync-key`, or `[sync] api_key`). Only its SHA-256 is stored; a field has at most two live keys, so a new key can be installed before the old one is revoked. Both sides show the first 8 hex digits of the key's SHA-256 as its fingerprint.
- **Games** are `(field, game_id, game_seed)`: the radio's 16-bit id comes round again, the seed does not, and a standby controller has the same seed, so its pushes land in the same game. The state only moves forward; a standby's "ended" does not end the game, a `game.end` event does.
- **Events** are unique on the controller's own key `(game, node, seq, game time, type)`: a replayed, duplicated or out-of-order batch is counted as duplicates and changes nothing. The answer's `acked_id` is the controller's cursor.
- **Scores** are counters per source (`node-3`, or `field-1@0` for a run of a controller's field script) and team, merged by `GREATEST`; totals are derived as the controller derives them: the counters' sum plus every `score.delta` amount, so a GM's negative adjustment lowers the total (P4R10).
- **Never received:** positions (an event whose data has a coordinate is refused), tokens and keys, check-in names.

## Personal data

ADR-P4-8, with decisions S12-1 to S12-8. The field operator is the data controller; `personal_data.py` lists every table that holds personal data, and each later plan phase adds its tables there (access, export, erasure, purge) in the same change.

- **Access and export:** `GET /api/v1/me/data` answers `{format, generated_at, user, field_roles, sessions, audit_log, audit_log_about_you, consents}`: the account (never the password hash or the TOTP secret), roles per field, sessions with their addresses and user agents, the person's own audit entries with addresses, entries others made about the account (a role granted: what and when, not who) and the consent records. `GET /api/v1/me/export` puts the same data in a ZIP: `export/profile.json`, `field_roles.json`, `sessions.json`, `audit_log.json`, `audit_log_about_you.json`, `consents.json` and a `README.txt` in English and Portuguese.
- **Rectification:** the username and email (`PATCH /api/v1/me`) and the password (`POST /api/v1/me/password`), each with the current password, under the same lockouts as a login. The audit log names the fields changed, never their values.
- **Erasure** (`DELETE /api/v1/me`, with the password and, for an account with TOTP, a code) anonymises: the account becomes `deleted-` and 16 random hex characters with no email, no password, no TOTP and no consent; its roles, sessions and consents are deleted; its audit entries stay without their addresses; the erasure is logged with no account and no address. Names starting with `deleted-` are reserved. The last server administrator cannot be erased.
- **Consents:** each one recorded in `consents` with its purpose (`account` for now) and `ATALAIA_PRIVACY_NOTICE_VERSION`; registration and `create-admin` record the account consent.
- **Retention:** every day at `ATALAIA_PURGE_HOUR` (03:00 UTC) the server deletes sessions 30 days after they expired or ended (with their refresh tokens) and audit entries older than 36 months, and logs what it deleted. `python -m atalaia_server purge [--dry-run]` runs it once (`docker compose exec server python -m atalaia_server purge`).
- **Templates** for the operator to fill in, to be reviewed by a lawyer before use: [`docs/templates/privacy-notice-pt.md`](../docs/templates/privacy-notice-pt.md), [`privacy-notice-en.md`](../docs/templates/privacy-notice-en.md) and the hosted service's data processing agreement [`dpa-template.md`](../docs/templates/dpa-template.md).

The synced games (plan phase 13) name players only by the field's pseudonymous player ids, linked to no account until plan phase 16; until then a person's games are the ones they hold a per-game role on (`games` in the access answer, `games.json` in the export; erasure deletes the roles). A game, with its events, counters, nodes and roles, is deleted 24 months after it ended.

Positions never reach the site server (decision P4R25).

## The first administrator

The first administrator is made from the command line, in the server's container: `docker compose exec server python -m atalaia_server create-admin --username NAME [--email ADDRESS]` asks for the password twice, shows a TOTP secret and its `otpauth://` URI for an authenticator app, and creates the account once a code from the app is typed back (`--password-stdin` reads the password, then the code, from standard input).

## Tests

From the repository root, with Docker and its Compose plugin (works from any shell):

```sh
python3 tools/docker_server.py test                      # every test, against an ephemeral postgres:16-alpine
python3 tools/docker_server.py test tests.test_health    # some (unittest names)
python3 tools/docker_server.py migrations                # upgrade head, downgrade base, upgrade head, alembic check
```

Each test class gets a fresh database, migrated to head, on the test PostgreSQL; there is no SQLite stand-in (decision P4R17). `tests.test_migrations` also steps through every revision, checks that each downgrade restores the schema exactly, and that the migrations build exactly the ORM models. The tests that need no database and nothing beyond the controller's Ubuntu packages (`test_config`, `test_ids`, `test_shared_imports`, which also imports the sync's shared checker and client) also run in `tools/check.sh` and in CI's `controller` job; `test_passwords`, `test_totp` (with RFC 6238's and RFC 4226's own test vectors), `test_tokens` and `test_ratelimit` need no database but need argon2-cffi, PyJWT and pyotp, so they run in the server's image only. `test_personal_data` covers access, the export's ZIP, rectification, password changes, erasure (with TOTP, and the last administrator) and the retention purge, its command and its daily task. `test_sync` covers the API keys and their rotation, replays, duplicates, out-of-order batches, a standby controller's copy, the score merge with a negative adjustment, game identity, the shared vectors, per-game roles and the games API; `test_sync_stream` the WebSocket; `test_sync_e2e` runs the real controller engine and its sync client against the site server served by uvicorn on a loopback port in the same container, on the test PostgreSQL (`python3 tools/docker_server.py test tests.test_sync_e2e`). CI's `server` job builds the same test image and runs the same `sh tests/run.sh test` and `sh tests/run.sh migrations` against a `postgres:16-alpine` service container.

## Trying it locally

```sh
python3 tools/docker_server.py up      # builds the image, starts PostgreSQL and the server on 127.0.0.1:8000
curl -fsS http://127.0.0.1:8000/api/v1/health
docker compose -p atalaia-server-trial exec server python -m atalaia_server create-admin --username admin
python3 tools/docker_server.py down    # stops it and deletes its database
```

`ATALAIA_PORT` picks another port. `up` makes a random database password and secret key each time, which is why `down` deletes the data: this is a trial, not a deployment. The image runs `alembic upgrade head`, then `uvicorn --factory atalaia_server.app:create_app` on port 8000, as an unprivileged user; it has no compiler.

## Dependencies

Plan phase 12 added none (the export's ZIP is the standard library's `zipfile`). Plan phase 11 added argon2-cffi 25.1.0 (with argon2-cffi-bindings 26.1.0), PyJWT 2.15.1 and pyotp 2.10.0, pinned the same way (`--exclude-newer 2026-10-05`, every hash checked against PyPI). Only `requirements.txt` goes into the image, installed with `pip --require-hashes --no-deps --only-binary=:all:` and checked with `pip check`. Every version is a release at least two weeks old when it was pinned; `requirements.in` has the command that refreshes the pins (uv's `pip compile --generate-hashes --exclude-newer`). The base images are pinned by digest: `python:3.12.14-slim` and `postgres:16.15-alpine`.
