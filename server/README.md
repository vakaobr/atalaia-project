# Site server (optional)

A self-hosted server for fields with internet: accounts, field setup, remote management, the player app backend, game history and the chrono registry. It never runs game logic; games keep working without it.

Clubs without IT support will be able to use hosted site servers run by the community hub.

Licence: AGPL-3.0-or-later.

## Status

Phase 4 plan phases 10 and 11 are built, and tested on a computer only. Plan phase 10 is the skeleton every later plan phase builds on: the application factory, its settings, the async database layer on PostgreSQL 16, the first migration (the base tables), `GET /api/v1/health` and `GET /api/v1/metrics`, security headers on every response, the server's own image, and the tests with their tooling. Plan phase 11 adds accounts, sessions and roles: registration, login with a TOTP step, rotating refresh tokens, lockouts and rate limits, per-field roles, the audit log and `python -m atalaia_server create-admin`. There is no game data yet: personal data rights come in plan phase 12, the controller sync (and per-game roles) in plan phase 13, deployment with HTTPS (Caddy, setup and backups) in plan phase 22. See [docs/phase-4-site-server/PLAN.md](../docs/phase-4-site-server/PLAN.md).

## Layout

| Path | What it is |
| --- | --- |
| [`atalaia_server/app.py`](atalaia_server/app.py) | `create_app()`: the FastAPI app; the engine is made when it starts and disposed when it stops |
| [`atalaia_server/config.py`](atalaia_server/config.py) | Settings from `ATALAIA_*` environment variables (below); plain Python |
| [`atalaia_server/db.py`](atalaia_server/db.py) | SQLAlchemy 2's async engine on asyncpg, sessions per request, the health ping |
| [`atalaia_server/models.py`](atalaia_server/models.py) | The ORM models: `fields`, `users`, `roles` (seeded with ADR-P4-1's seven), `user_field_roles`, `sessions`, `audit_log` |
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
| [`atalaia_server/cli.py`](atalaia_server/cli.py) | `python -m atalaia_server create-admin` |
| [`migrations/`](migrations/), [`alembic.ini`](alembic.ini) | Alembic, async; one reversible migration per plan phase (`0001_base`, `0002_accounts`) |
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

A setting that is present but not valid stops the server at start-up with a message; it is never replaced by its default. The database password never appears in logs.

## API so far

| Method | Path | Auth | Answer |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | none | 200 `{"status": "healthy", "database": "connected", "version", "uptime_s"}`, or 503 with `"unhealthy"` and `"unreachable"` when PostgreSQL does not answer |
| GET | `/api/v1/metrics` | a server administrator, or the metrics token | Uptime, version, the connection pool, the number of fields, users and active sessions; 503 when the database is down |
| POST | `/api/v1/auth/register` | none | `{username, password, email?, consent: true}`: 201 with the account |
| POST | `/api/v1/auth/login` | none | `{username, password}`: a session (below), or `{"totp_required": true, "totp_session"}` for an account with TOTP |
| POST | `/api/v1/auth/login/totp` | none | `{totp_session, code}`: a session |
| POST | `/api/v1/auth/refresh` | the refresh cookie and `X-Atalaia-Refresh: 1` | A new session body and a new refresh cookie; the old one is spent |
| POST | `/api/v1/auth/logout` | Bearer | 204; the session ends and the cookie is cleared |
| GET | `/api/v1/me` | Bearer | The account, its roles per field, and whether this session passed TOTP |
| POST | `/api/v1/auth/totp/enrol` | Bearer | `{password}`: a new secret and its `otpauth://` URI, shown once |
| POST | `/api/v1/auth/totp/confirm` | Bearer | `{code}`: TOTP is on |
| POST | `/api/v1/auth/totp/disable` | Bearer | `{password, code}`: TOTP is off (refused while the account holds `admin`, `gm` or `marshal`) |
| POST | `/api/v1/fields` | a server administrator | `{name, slug, field_type?, timezone?}`: 201 with the field |
| GET | `/api/v1/fields` | Bearer | The fields the caller has a role on (every field for a server administrator) |
| GET | `/api/v1/fields/{field_id}/roles` | the field's `admin` or `gm` | Who holds which role |
| PUT | `/api/v1/fields/{field_id}/roles` | the field's `admin` (any role) or `gm` (`player`, `squad_leader`, `vip`, `spectator`) | `{username, role}`: 201 granted, 200 already held |
| DELETE | `/api/v1/fields/{field_id}/roles/{user_id}/{role}` | as for granting | 204 |
| GET | `/api/v1/openapi.json` | none | The OpenAPI document (the interactive pages are off: they load scripts from a CDN, which the content security policy forbids) |

A session body is `{access_token, token_type: "bearer", expires_in: 900, mfa, user}`, with the refresh token in a cookie. Errors are `{"detail": "<code>"}`, a code a client translates (`invalid_credentials`, `password_breached`, `totp_required`, `role_required`, `too_many_attempts`, ...).

## Accounts, sessions and roles

ADR-P4-2, with decisions S11-1 to S11-15:

- **Passwords:** Argon2id with 3 passes over 64 MiB, 4 lanes, a 16-byte salt and a 32-byte tag; an older hash is replaced at the next login. The policy is NIST SP 800-63B's: 10 to 1024 characters (after Unicode NFKC normalisation), no character-class rules, not the username, and not one of the 100,000 passwords seen most often in breaches (the UK NCSC's list, [`data/breached-passwords.txt`](atalaia_server/data/breached-passwords.txt): SecLists' `Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt` at commit `1a7bb9127eca9e6ff2fc0301c597fe6e16a0cb56`, unmodified, SHA-256 `c2e5696882c603b76bb67a47ee970897e5a76fc4c3f5547abe3d0ca340c576e0`, MIT as part of SecLists), compared whatever the case. An unknown username takes as long to refuse as a wrong password.
- **TOTP** (RFC 6238): 6 digits every 30 seconds, as authenticator apps do by default; one step of clock drift either side; each code is accepted once. Seeds are stored encrypted (Fernet). Accounts with `admin`, `gm` or `marshal` on any field, and server administrators, must have it, and those roles count only in a session that passed it.
- **Sessions:** a 15-minute access token (`Authorization: Bearer`; the server re-reads the session and the roles on every request, so a logout or a removed role counts at once) and a refresh token in the cookie `__Secure-atalaia_refresh` (HttpOnly, Secure, SameSite=Strict, sent only to `/api/v1/auth/refresh`). Each refresh spends the token and issues a new one; a spent token presented again ends the whole session. A session ends after 7 days without a refresh, and after 30 days in any case. The database keeps only SHA-256 hashes of refresh tokens.
- **Limits:** 5 failed logins from one address lock that address out of logging in for 15 minutes; 5 wrong codes lock an account's TOTP for 15 minutes; 10 registrations an hour and 100 API requests a minute per address. The state is in memory, for the one worker process the image runs.
- **Roles** are per field: `player`, `squad_leader`, `vip`, `marshal`, `gm`, `spectator`, `admin`. A field's `admin` grants and revokes any of them; its `gm` the four player roles. Per-game roles come with the games themselves (plan phase 13).
- **The audit log** records registrations, logins, failures and lockouts, refresh replays, logouts, TOTP changes, new fields and every role change, with the address; never a password, a code, a token or a username typed for an account that does not exist.

The first administrator is made from the command line, in the server's container: `docker compose exec server python -m atalaia_server create-admin --username NAME [--email ADDRESS]` asks for the password twice, shows a TOTP secret and its `otpauth://` URI for an authenticator app, and creates the account once a code from the app is typed back (`--password-stdin` reads the password, then the code, from standard input).

## Tests

From the repository root, with Docker and its Compose plugin (works from any shell):

```sh
python3 tools/docker_server.py test                      # every test, against an ephemeral postgres:16-alpine
python3 tools/docker_server.py test tests.test_health    # some (unittest names)
python3 tools/docker_server.py migrations                # upgrade head, downgrade base, upgrade head, alembic check
```

Each test class gets a fresh database, migrated to head, on the test PostgreSQL; there is no SQLite stand-in (decision P4R17). `tests.test_migrations` also steps through every revision, checks that each downgrade restores the schema exactly, and that the migrations build exactly the ORM models. The tests that need no database and nothing beyond the controller's Ubuntu packages (`test_config`, `test_ids`, `test_shared_imports`) also run in `tools/check.sh` and in CI's `controller` job; `test_passwords`, `test_totp` (with RFC 6238's and RFC 4226's own test vectors), `test_tokens` and `test_ratelimit` need no database but need argon2-cffi, PyJWT and pyotp, so they run in the server's image only. CI's `server` job builds the same test image and runs the same `sh tests/run.sh test` and `sh tests/run.sh migrations` against a `postgres:16-alpine` service container.

## Trying it locally

```sh
python3 tools/docker_server.py up      # builds the image, starts PostgreSQL and the server on 127.0.0.1:8000
curl -fsS http://127.0.0.1:8000/api/v1/health
docker compose -p atalaia-server-trial exec server python -m atalaia_server create-admin --username admin
python3 tools/docker_server.py down    # stops it and deletes its database
```

`ATALAIA_PORT` picks another port. `up` makes a random database password and secret key each time, which is why `down` deletes the data: this is a trial, not a deployment. The image runs `alembic upgrade head`, then `uvicorn --factory atalaia_server.app:create_app` on port 8000, as an unprivileged user; it has no compiler.

## Dependencies

Plan phase 11 added argon2-cffi 25.1.0 (with argon2-cffi-bindings 26.1.0), PyJWT 2.15.1 and pyotp 2.10.0, pinned the same way (`--exclude-newer 2026-10-05`, every hash checked against PyPI). Only `requirements.txt` goes into the image, installed with `pip --require-hashes --no-deps --only-binary=:all:` and checked with `pip check`. Every version is a release at least two weeks old when it was pinned; `requirements.in` has the command that refreshes the pins (uv's `pip compile --generate-hashes --exclude-newer`). The base images are pinned by digest: `python:3.12.14-slim` and `postgres:16.15-alpine`.
