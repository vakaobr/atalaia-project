# Site server (optional)

A self-hosted server for fields with internet: accounts, field setup, remote management, the player app backend, game history and the chrono registry. It never runs game logic; games keep working without it.

Clubs without IT support will be able to use hosted site servers run by the community hub.

Licence: AGPL-3.0-or-later.

## Status

Phase 4 plan phase 10 is built, and tested on a computer only: the skeleton every later plan phase builds on. That is the application factory, its settings, the async database layer on PostgreSQL 16, the first migration (the base tables), `GET /api/v1/health` and `GET /api/v1/metrics`, security headers on every response, the server's own image, and the tests with their tooling. There are no accounts, logins or game data yet: accounts and roles come in plan phase 11, the controller sync in plan phase 13, deployment with HTTPS (Caddy, setup and backups) in plan phase 22. See [docs/phase-4-site-server/PLAN.md](../docs/phase-4-site-server/PLAN.md).

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
| [`migrations/`](migrations/), [`alembic.ini`](alembic.ini) | Alembic, async; one reversible migration per plan phase (`0001_base` now) |
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
| `ATALAIA_DB_POOL_SIZE` | 5 | Connections kept open (1-100) |
| `ATALAIA_DB_MAX_OVERFLOW` | 5 | Extra connections under load (0-100) |
| `ATALAIA_DB_TIMEOUT_S` | 5 | Connect and health-check timeout, seconds |
| `ATALAIA_METRICS_TOKEN` | (empty) | Bearer token for `/api/v1/metrics`, at least 32 characters; empty: the endpoint answers 404. Admin accounts replace it in plan phase 11 |
| `ATALAIA_LOG_LEVEL` | `info` | `debug`, `info`, `warning` or `error` |

A setting that is present but not valid stops the server at start-up with a message; it is never replaced by its default. The database password never appears in logs.

## API so far

| Method | Path | Auth | Answer |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | none | 200 `{"status": "healthy", "database": "connected", "version", "uptime_s"}`, or 503 with `"unhealthy"` and `"unreachable"` when PostgreSQL does not answer |
| GET | `/api/v1/metrics` | `Bearer` metrics token | Uptime, version, the connection pool, the number of fields and users; 503 when the database is down |
| GET | `/api/v1/openapi.json` | none | The OpenAPI document (the interactive pages are off: they load scripts from a CDN, which the content security policy forbids) |

## Tests

From the repository root, with Docker and its Compose plugin (works from any shell):

```sh
python3 tools/docker_server.py test                      # every test, against an ephemeral postgres:16-alpine
python3 tools/docker_server.py test tests.test_health    # some (unittest names)
python3 tools/docker_server.py migrations                # upgrade head, downgrade base, upgrade head, alembic check
```

Each test class gets a fresh database, migrated to head, on the test PostgreSQL; there is no SQLite stand-in (decision P4R17). `tests.test_migrations` also steps through every revision, checks that each downgrade restores the schema exactly, and that the migrations build exactly the ORM models. The tests that need no database (`test_config`, `test_ids`, `test_shared_imports`) also run in `tools/check.sh` and in CI's `controller` job, on the controller's Ubuntu packages. CI's `server` job builds the same test image and runs the same `sh tests/run.sh test` and `sh tests/run.sh migrations` against a `postgres:16-alpine` service container.

## Trying it locally

```sh
python3 tools/docker_server.py up      # builds the image, starts PostgreSQL and the server on 127.0.0.1:8000
curl -fsS http://127.0.0.1:8000/api/v1/health
python3 tools/docker_server.py down    # stops it and deletes its database
```

`ATALAIA_PORT` picks another port. `up` makes a random database password each time, which is why `down` deletes the data: this is a trial, not a deployment. The image runs `alembic upgrade head`, then `uvicorn --factory atalaia_server.app:create_app` on port 8000, as an unprivileged user; it has no compiler.

## Dependencies

Only `requirements.txt` goes into the image, installed with `pip --require-hashes --no-deps --only-binary=:all:` and checked with `pip check`. Every version is a release at least two weeks old when it was pinned; `requirements.in` has the command that refreshes the pins (uv's `pip compile --generate-hashes --exclude-newer`). The base images are pinned by digest: `python:3.12.14-slim` and `postgres:16.15-alpine`.
