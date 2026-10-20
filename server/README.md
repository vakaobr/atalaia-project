# Site server (optional)

A self-hosted server for fields with internet: accounts, field setup, remote management, the player app backend, game history and the chrono registry. It never runs game logic; games keep working without it.

Clubs without IT support will be able to use hosted site servers run by the community hub.

Licence: AGPL-3.0-or-later.

## Status

Phase 4 plan phases 10 to 18 are built, and tested on a computer only. Plan phase 10 is the skeleton every later plan phase builds on: the application factory, its settings, the async database layer on PostgreSQL 16, the first migration (the base tables), `GET /api/v1/health` and `GET /api/v1/metrics`, security headers on every response, the server's own image, and the tests with their tooling. Plan phase 11 adds accounts, sessions and roles: registration, login with a TOTP step, rotating refresh tokens, lockouts and rate limits, per-field roles, the audit log and `python -m atalaia_server create-admin`. Plan phase 12 adds the personal data rights: access, export, rectification and erasure of one's own account, consent records, the daily retention purge, and privacy notice and DPA templates. Plan phase 13 adds the controller sync: field controllers push their games, event logs, score counters and nodes with a field API key, offline first and replay-safe, and the site server keeps them with per-game roles and a small games API; it has run against the real controller in tests, not yet over a real 4G link (HW1). Plan phase 14 adds the chrono registry: the controller pushes the marshals' public keys with their periods, the replica registry and the signed chrono readings; the site server verifies every reading with the controller's own verifier, keeps it exactly as signed (or apart, with the reason, when it does not verify), and gives the field's staff, the players themselves and, with consent, other fields their views; tested against the controller's client and the shared vectors, not yet with a real chronograph (HW4). Plan phase 15 adds scheduling and the field's public face: the field's admin and GMs schedule games (drafts, then published by the admin, edited, cancelled with a reason), and a field that turns its page on gets a public page with its upcoming games in Portuguese and English, rendered on the server with no JavaScript, and open iCalendar (RFC 5545) and JSON feeds that calendars and other sites can read ([docs/feeds.md](docs/feeds.md)); no personal data on any of them. Not yet: game history views (20), deployment with HTTPS (Caddy, setup and backups) in plan phase 22. See [docs/phase-4-site-server/PLAN.md](../docs/phase-4-site-server/PLAN.md). Plan phase 16 adds registration and game-day sync: players register for a published game with an account, with pre-declared replicas and a check-in ticket (only its hash kept); an account can adopt the player id its phone already has at the field, once the field's controller confirms it; the controller pulls the schedule, makes its game from a scheduled game, pulls the roster as expected check-ins until the game starts, and pushes each registration's outcome back after it; tested against the real controller in Docker, not yet on a real game day; the app's screens for it (account login, the field's games, registering, the ticket) are built and tested against a stand-in server, not yet against a real deployment or on a phone. Plan phase 17 adds the registration import and platform adapters ([docs/integrations.md](docs/integrations.md)): a field's staff import a registration list exported from elsewhere (CSV or JSON, only the columns the check-in needs, a dry-run preview first, row-level errors, re-importing the same export changes the same registrations) and export the game's list as formula-safe CSV; the adapter interface for external platforms (only through a platform's documented API or a written agreement, off by default, configuration encrypted, every call audited) ships with an in-memory test adapter only, and there is no adapter for any named platform. Plan phase 18 adds club profiles and branding sync: clubs (name, short name, colour, logo, crest, members invited by their admins) with a public page off by default, a report button and a server administrator who can hide one; a field's branding (name, accent, logo, wallpaper) and saved teams (a club's team carries the club's crest) edited here, with every image checked by the controller's own `images.py`; and controllers set to `[sync] branding = "site"` pull them, so a club's crest uploaded once reaches every field that saved its team; tested against the real controller in Docker, not yet on a real deployment.

## Layout

| Path | What it is |
| --- | --- |
| [`atalaia_server/app.py`](atalaia_server/app.py) | `create_app()`: the FastAPI app; the engine is made when it starts and disposed when it stops |
| [`atalaia_server/config.py`](atalaia_server/config.py) | Settings from `ATALAIA_*` environment variables (below); plain Python |
| [`atalaia_server/db.py`](atalaia_server/db.py) | SQLAlchemy 2's async engine on asyncpg, sessions per request, the health ping |
| [`atalaia_server/models.py`](atalaia_server/models.py) | The ORM models: `fields`, `users`, `roles` (seeded with ADR-P4-1's seven), `user_field_roles`, `sessions`, `audit_log`, `refresh_tokens`, `consents`; the sync's `field_api_keys`, `controllers`, `games`, `game_events`, `game_node_scores`, `game_nodes`, `user_game_roles`; the chrono registry's `marshal_keys`, `replicas`, `chrono_readings`, `chrono_rejects`, `chrono_violations`, `field_player_ids`; the schedule's `scheduled_games`; registration's `game_registrations`, `registration_replicas`, `player_id_claims`; the adapters' `platform_links`, `external_game_links`; clubs and branding's `branding_images`, `clubs`, `club_members`, `club_reports`, `field_teams` (and the field's branding columns) |
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
| [`atalaia_server/chrono_verify.py`](atalaia_server/chrono_verify.py) | A synced reading's verdict: the controller's own `chrono.py` with the marshal's key valid then; plain Python |
| [`atalaia_server/chrono_registry.py`](atalaia_server/chrono_registry.py), [`api/chrono.py`](atalaia_server/api/chrono.py) | The chrono registry: storing the synced keys, replicas and readings, the staff views, sharing between fields |
| [`atalaia_server/services/scheduling.py`](atalaia_server/services/scheduling.py), [`api/scheduling.py`](atalaia_server/api/scheduling.py) | Scheduled games: their rules (statuses, the registration window, the iCalendar `SEQUENCE`) and the staff API |
| [`atalaia_server/services/registration.py`](atalaia_server/services/registration.py), [`api/registrations.py`](atalaia_server/api/registrations.py) | Registrations, tickets, claims of a phone's player id, and the game-day sync's answers (schedule, roster, outcomes) |
| [`atalaia_server/import_format.py`](atalaia_server/import_format.py), [`services/registration_import.py`](atalaia_server/services/registration_import.py), [`api/registration_import.py`](atalaia_server/api/registration_import.py) | The registration import: reading and checking a CSV or JSON list (plain Python), matching it to a game's registrations, the endpoint and the CSV export |
| [`atalaia_server/integrations/`](atalaia_server/integrations/), [`api/integrations.py`](atalaia_server/api/integrations.py) | Platform adapters: the interface (`base.py`), the registry and the encrypted configuration, the test adapter (`testing.py`), the per-field links and calls |
| [`atalaia_server/services/branding.py`](atalaia_server/services/branding.py), [`api/clubs.py`](atalaia_server/api/clubs.py), [`api/branding.py`](atalaia_server/api/branding.py) | Clubs, their members and the moderation of their pages; a field's branding and saved teams; images checked with the controller's `images.py`; the sync's branding answer |
| [`docs/integrations.md`](docs/integrations.md) | The import's format and rules and the adapters' rules, for fields and for whoever writes an adapter |
| [`atalaia_server/web/`](atalaia_server/web/) | The public field page and game pages (`field_pages.py`, `templates/`, `static/field.css`, texts in `i18n.py`), the routes of the feeds, and the public club pages with their report form (`club_pages.py`) |
| [`atalaia_server/feeds/`](atalaia_server/feeds/) | The iCalendar writer (`ical.py`) and the JSON feed (`json_feed.py`); plain Python, no database |
| [`schemas/games-feed-v1.schema.json`](schemas/games-feed-v1.schema.json), [`docs/feeds.md`](docs/feeds.md) | The JSON feed's schema, and the pages and feeds described for fields and for whoever reads them |
| [`atalaia_server/cli.py`](atalaia_server/cli.py) | `python -m atalaia_server create-admin` and `purge` |
| [`migrations/`](migrations/), [`alembic.ini`](alembic.ini) | Alembic, async; one reversible migration per plan phase (`0001_base`, `0002_accounts`, `0003_personal_data`, `0004_sync`, `0005_chrono`, `0006_scheduling`, `0007_registration`, `0008_integrations`, `0009_clubs`) |
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
| `ATALAIA_PUBLIC_URL` | (empty) | The site's public address, an origin such as `https://campo.example.pt` (no path): the links in the field pages and feeds and the host name in iCalendar UIDs. Set it on a real deployment; unset, they follow the address of each request (a local trial). `http://` only for `localhost` |
| `ATALAIA_TEST_ADAPTER` | `off` | `on` offers the platform adapters' test adapter, an in-memory stand-in for a platform, for trials and tests; leave it off on a real deployment |
| `ATALAIA_PRIVACY_NOTICE_VERSION` | `template-2026-10-19` | The version of the privacy notice the field shows, stored with every consent; raise it when the notice changes (1-64 of letters, digits and `. _ : + -`) |

A setting that is present but not valid stops the server at start-up with a message; it is never replaced by its default. The database password never appears in logs.

## API so far

| Method | Path | Auth | Answer |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | none | 200 `{"status": "healthy", "database": "connected", "version", "uptime_s"}`, or 503 with `"unhealthy"` and `"unreachable"` when PostgreSQL does not answer |
| GET | `/api/v1/metrics` | a server administrator, or the metrics token | Uptime, version, the connection pool, the number of fields, users, active sessions, games, game events, controllers, chrono readings and readings kept apart, scheduled games and fields with a public page; 503 when the database is down |
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
| GET | `/api/v1/me/chrono` | Bearer | The person's chrono history: per field where the account holds a player id, the readings (each as signed, with the marshal's public key), replicas, violations and refused readings |
| PUT, DELETE | `/api/v1/me/consents/chrono-sharing/{field_id}` | Bearer | Consent (201, or 200 when already given) or withdraw it (204): that field's chrono records may be shown to the other sharing fields the person also consented for, and theirs to it |
| POST | `/api/v1/fields` | a server administrator | `{name, slug, field_type?, timezone?}`: 201 with the field |
| GET | `/api/v1/fields` | Bearer | The fields the caller has a role on (every field for a server administrator) |
| PATCH | `/api/v1/fields/{field_id}` | the field's `admin` | `{chrono_sharing_enabled}`: whether the field shares chrono records with other sharing fields; `{public_page, description, address_text, federation_label}`: the public field page and feeds (off by default) and what they say about the field; `{limit_template, max_replicas}`: the controller's check-in rules for pre-declared replicas (`portugal` and 5 by default) |
| POST | `/api/v1/fields/{field_id}/scheduled-games` | the field's `admin` or `gm` | `{title, starts_at, ends_at, description?, location_text?, mode_id?, teams?, max_players?, registration_opens_at?, registration_closes_at?, federation?, predeclare_replicas?}` (times RFC 3339 with an offset): 201 with the new draft |
| GET | `/api/v1/fields/{field_id}/scheduled-games?status=&from=` | the field's `admin` or `gm` | The field's games by start, drafts included |
| GET, PATCH | `/api/v1/fields/{field_id}/scheduled-games/{id}` | the field's `admin` or `gm` | One game; `PATCH` changes the members sent (`null` clears an optional one), drafts and published games only |
| DELETE | `/api/v1/fields/{field_id}/scheduled-games/{id}` | the field's `admin` or `gm` | 204: a draft only (409 `not_a_draft`) |
| POST | `/api/v1/fields/{field_id}/scheduled-games/{id}/publish` | the field's `admin` | On the field page and in the feeds |
| POST | `/api/v1/fields/{field_id}/scheduled-games/{id}/cancel` | the field's `admin` | `{reason}`: cancelled, still shown with the reason |
| POST | `/api/v1/fields/{field_id}/scheduled-games/{id}/registrations` | Bearer (any account) | `{display_name?, team_preference?, federation_number?, replicas?: [{replica_id} or {type, class, make_model?}]}`: 201 with the registration and its ticket (`ticket`, `ticket_text`), shown this once |
| GET | `/api/v1/fields/{field_id}/scheduled-games/{id}/registrations` | the field's `admin` or `gm` | The registrations with names, counts and walk-ins |
| PATCH, DELETE | `/api/v1/fields/{field_id}/scheduled-games/{id}/registrations/{reg}` | the field's `admin` or `gm` | Change one, or cancel it (204), until the game starts |
| POST | `/api/v1/fields/{field_id}/scheduled-games/{id}/registrations/import?source=&dry_run=&basis_confirmed=` | the field's `admin` or `gm` | A CSV (`text/csv`) or JSON list, at most 1 MiB and 5,000 rows: every row created, updated, unchanged, skipped or refused with a code; `dry_run=true` writes nothing ([docs/integrations.md](docs/integrations.md)) |
| GET | `/api/v1/fields/{field_id}/scheduled-games/{id}/registrations.csv` | the field's `admin` or `gm` | The game's registrations as CSV in the import's columns, safe from spreadsheet formulas |
| GET | `/api/v1/fields-by-slug/{slug}` | Bearer (any account) | The field (its replicas' classes, `max_replicas`, federation label) and its published games that have not ended, for the app |
| GET | `/api/v1/integrations/adapters` | Bearer | The platform adapters this server offers |
| GET, PUT, DELETE | `/api/v1/fields/{field_id}/integrations[/{adapter}]` | the field's `admin` | The field's platform links: `{enabled, config}`, off by default, the configuration encrypted and never shown again |
| GET | `/api/v1/fields/{field_id}/scheduled-games/{id}/integrations` | the field's `admin` or `gm` | The game's references on the platforms |
| POST | `/api/v1/fields/{field_id}/scheduled-games/{id}/integrations/{adapter}/push` | the field's `admin` | Publish the game on the platform, update it, or cancel it there; `502` with the code when the platform fails |
| POST | `/api/v1/fields/{field_id}/scheduled-games/{id}/integrations/{adapter}/registrations?dry_run=&basis_confirmed=` | the field's `admin` or `gm` | The platform's registrations through the import's rules |
| GET | `/api/v1/me/registrations` | Bearer | The account's registrations, with their replicas and outcomes (never the ticket) |
| PATCH, DELETE | `/api/v1/me/registrations/{reg}` | Bearer | Change or cancel one while the window is open |
| POST | `/api/v1/me/registrations/{reg}/ticket` | Bearer | A new ticket (shown once) until the game starts |
| GET, POST | `/api/v1/me/player-ids` | Bearer | The account's player ids and claims; `{field_id, player_id, player_secret}` claims the id the phone already has at a field: 202 `pending` until the field's controller confirms it |
| GET, HEAD | `/f/{slug}/`, `/f/{slug}/games/{id}` | none (the field's page on) | The field page and a game's page, HTML in pt-PT or English (`?lang=`, else `Accept-Language`); a *Register* button while registration is open and places are left, leading to `/f/{slug}/games/{id}/register` (how to register, with an account) |
| GET, HEAD | `/f/{slug}/games.ics`, `/f/{slug}/games/{id}.ics`, `/f/{slug}/games.json` | none (the field's page on) | The feeds ([docs/feeds.md](docs/feeds.md)): ETag, `304` on a match, `Access-Control-Allow-Origin: *`; `HEAD` answers with the same headers and no body |
| GET | `/api/v1/fields/{field_id}/roles` | the field's `admin` or `gm` | Who holds which role |
| PUT | `/api/v1/fields/{field_id}/roles` | the field's `admin` (any role) or `gm` (`player`, `squad_leader`, `vip`, `spectator`) | `{username, role}`: 201 granted, 200 already held |
| DELETE | `/api/v1/fields/{field_id}/roles/{user_id}/{role}` | as for granting | 204 |
| POST | `/api/v1/fields/{field_id}/sync-keys` | the field's `admin` | `{label?}`: 201 with a new controller API key, shown once, and its fingerprint; 409 `too_many_keys` with two live |
| GET | `/api/v1/fields/{field_id}/sync-keys` | the field's `admin` | The keys: id, fingerprint, label, created, last used, revoked (never the key) |
| DELETE | `/api/v1/fields/{field_id}/sync-keys/{key_id}` | the field's `admin` | 204: revoked |
| POST | `/api/v1/sync/games`, `events`, `scores`, `nodes` | a field API key | The controller sync ([protocol/sync.md](../protocol/sync.md)) |
| POST | `/api/v1/sync/marshals`, `replicas`, `chrono` | a field API key | The field's chrono registry: public keys with their periods, replicas, signed readings (each verified; those that fail kept apart and named in the answer) |
| POST | `/api/v1/sync/checkins`, `claims` | a field API key | After a game made from a scheduled game, each registration's outcome and its declarations' states; the controller's verdicts on accounts' claims of player ids |
| GET | `/api/v1/sync/schedule?days=`, `roster?scheduled_game_id=`, `claims` | a field API key | What the controller pulls: the published games of the coming days, one game's registrations, accounts' claims waiting for this field's verdict |
| GET | `/api/v1/sync/field`, `images/{sha256}` | a field API key | With `[sync] branding = "site"`: the field's branding and saved teams, and their images by SHA-256 (only the field's own) |
| WS | `/api/v1/sync/stream` | a field API key (on the upgrade) | The POST bodies on one socket |
| GET | `/api/v1/fields/{field_id}/games` | any role on the field | The field's games, newest first |
| GET | `/api/v1/games/{game}` | a role on the field or the game | The game with its totals, counters and nodes (`params` for the field's `admin` and `gm` only) |
| GET | `/api/v1/games/{game}/events?after=&limit=` | the field's `admin`, `gm` or `marshal`, or the game's `gm` or `marshal` | The log in pages of up to 1,000 |
| GET, PUT, DELETE | `/api/v1/games/{game}/roles[/{user_id}/{role}]` | as for field roles | Per-game roles |
| GET | `/api/v1/fields/{field_id}/chrono/readings?player_id=&replica_id=&series_id=&marshal_id=&after=&limit=` | the field's `admin`, `gm` or `marshal` | Signed readings in pages of up to 1,000: the record as received, its fields, the series and outcome, the key that verified it |
| GET | `/api/v1/fields/{field_id}/chrono/rejects` | the field's `admin` or `gm` | Readings that did not verify, with the reason and how often they came |
| GET, PATCH | `/api/v1/fields/{field_id}/chrono/violations[/{id}]` (`?open=true`) | read: `admin`, `gm`, `marshal`; `{outcome: warning\|pulled\|ban}`: `admin`, `gm` | Failed and warned spot checks, one per series |
| GET | `/api/v1/fields/{field_id}/chrono/players/{player_id}` | the field's `admin`, `gm` or `marshal` | One player's readings here, and `shared`: other fields' readings of the same person, when both fields share and the person consented for both |
| DELETE | `/api/v1/fields/{field_id}/chrono/players/{player_id}` | the field's `admin` | A player's erasure at the field: their readings, violations, refused readings and replicas here |
| GET | `/api/v1/fields/{field_id}/replicas?owner_player_id=` | the field's `admin`, `gm` or `marshal` | The replica registry |
| GET, POST | `/api/v1/fields/{field_id}/marshal-keys` | read: `admin`, `gm`, `marshal`; register: a `marshal` | Every key with its period; `{marshal_id, name, public_key}` registers the key the marshal's phone made, linked to the account |
| DELETE | `/api/v1/fields/{field_id}/marshal-keys/{key_id}` | the field's `admin` | 204: revoked as compromised (nothing received after it verifies with it) |
| GET, PATCH | `/api/v1/fields/{field_id}/branding` | read: the field's `admin` or `gm`; change: `admin` | `{field_name, accent, logo, wallpaper}`; `field_name` (1-48) and `accent` (`#rrggbb`) change, `null` clears |
| PUT, DELETE | `/api/v1/fields/{field_id}/branding/{logo\|wallpaper}` | the field's `admin` | The raw image (`?rights_confirmed=true`), checked with the controller's limits |
| GET, POST | `/api/v1/fields/{field_id}/teams` | the field's `admin` or `gm` | Saved teams; `{name?, colour?, club_slug?}` adds one (a club's: its short name and crest unless set; a non-public club only by its members); 409 `team_name_taken` |
| PATCH, DELETE | `/api/v1/fields/{field_id}/teams/{team_id}` | the field's `admin` or `gm` | `{name, colour}`; delete |
| PUT, DELETE | `/api/v1/fields/{field_id}/teams/{team_id}/crest` | the field's `admin` or `gm` | The team's own crest (`?rights_confirmed=true`); without it, its club's |
| POST, GET | `/api/v1/clubs` | an account | `{name, short_name, slug, description?, colour?}` makes a club whose admin the caller is (10 at most); the caller's clubs |
| GET, PATCH, DELETE | `/api/v1/clubs/{club_id}` | read: a member, or anyone for a public club; change: the club's `admin` | `{name, short_name, description, colour, public_page}` |
| PUT, DELETE | `/api/v1/clubs/{club_id}/images/{logo\|crest}` | the club's `admin` | The raw image (`?rights_confirmed=true`) |
| GET, PUT | `/api/v1/clubs/{club_id}/members` | read: a member; `{username, role}`: the club's `admin` | Invite (the person accepts) or change a role; 409 `last_admin` |
| DELETE | `/api/v1/clubs/{club_id}/members/{user_id}` | the club's `admin`, or the member | Remove, leave or decline |
| GET, POST | `/api/v1/me/clubs`, `/api/v1/me/clubs/{club_id}/accept` | the account | Its memberships and invitations; accept one |
| POST | `/api/v1/club-reports` | none (an account is kept if logged in) | `{slug, reason, text?}`: report a public club page; 5 an hour per address |
| GET, PATCH | `/api/v1/admin/club-reports[/{id}]` | server administrator | The reports (`?status=open\|dismissed\|actioned\|all`); `{status: dismissed\|actioned}` |
| PUT, DELETE | `/api/v1/admin/clubs/{club_id}/hidden` | server administrator | `{reason?}`: hide a club's public page; show it again |
| GET | `/c/{slug}/`, `/c/{slug}/logo`, `/c/{slug}/crest`, `/c/{slug}/report` (GET, POST) | none | A public club page, its images and its report form (no JavaScript) |
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
- **Never received:** positions (an event whose data has a coordinate is refused), tokens and keys (marshals' private keys included), check-in names.

## Chrono registry

ADR-P4-5 as amended, decisions P4R14, P4R15 and S14-1 to S14-12; the wire format is in [protocol/sync.md](../protocol/sync.md), the records in [protocol/chrono-record.md](../protocol/chrono-record.md).

- **Public keys only.** A marshal's phone makes its Ed25519 key and keeps the private half; the site server gets public keys, from the controller with the period each was the marshal's key (the controller keeps earlier keys after a rotation) or from the marshal's own account. A lost phone means a new key; the old one keeps its period, so what it signed still verifies. A field's admin can revoke a key as compromised.
- **Verified, verbatim.** Each synced reading is verified with `atalaia_controller.chrono` (the controller's own code and the shared vectors) against the keys of its marshal that were valid when the controller received it, and stored exactly as the controller sent it. One that fails (`format`, `unsigned`, `marshal`: no key valid then, `signature`, `conflict`: another record under a stored id) is kept apart with its reason for the field's staff and named in the answer, never silently dropped; one kept apart for want of its marshal's key is checked again when the key arrives. A reading sent twice is a duplicate.
- **Violations:** a spot check the controller judged `fail` or `warn` becomes one violation per series, at its highest-energy reading; staff record what was done.
- **Sharing between fields** (ADR-P4-5): both fields switch it on, and the person consents for each of the two fields; the other field's staff then see the person's readings, each with the marshal's public key, so they can check them without trusting this server. Per-field player ids are never matched with each other: only an account that holds both links them.
- **Player ids and accounts:** `field_player_ids` says which of a field's pseudonymous player ids are an account's: made on the account's first registration at the field, or adopted from the phone (plan phase 16, below). The person's own history (`GET /api/v1/me/chrono`) follows it.

## Scheduling and the field page

ADR-P4-11 and ADR-P4-12, decisions F13, F18, F19 and S15-1 to S15-12; for readers of the pages and feeds, [docs/feeds.md](docs/feeds.md).

- **Who:** the field's `admin` and `gm` (in a TOTP session) make and edit scheduled games; only the `admin` publishes and cancels (F13). A draft is seen by staff only and can be deleted; a published game can be edited or cancelled with a reason, never deleted or made a draft again, since it may already be in someone's calendar.
- **Times** are sent as RFC 3339 with an offset, kept in UTC and shown in the field's time zone (`fields.timezone`); a game lasts at most 14 days; a registration window must close before the start.
- **Calendars:** a published game's start, end or place changing, its cancellation, or the field's address changing for a game that shows it raise its iCalendar `SEQUENCE`, so subscribed calendars update the event.
- **The public page** is off until the field's `admin` turns it on (`public_page`). It is HTML made on the server from `web/templates/` with every value escaped, no JavaScript and nothing loaded from another site, so it works under the security headers' content security policy as it is; the game pages carry schema.org `Event` JSON-LD as data. Portuguese (pt-PT) and English.
- **Registration** (plan phase 16, below): the game page shows a *Register* button and the JSON feed `"open": true` only while the window is open and places are left; the places left count the live registrations.
- **No personal data** on the pages or in the feeds: never who registered or how many, only the places left.
- **HEAD** is answered like `GET` without the body, for calendar clients (decision S16-10).

## Registration and game day

ADR-P4-11 as amended, decisions F14-F17 and S16-1 to S16-12; the sync's part is in [protocol/sync.md](../protocol/sync.md), the ticket in [protocol/checkin.md](../protocol/checkin.md).

- **Registering** needs an account (F14) and a published game whose window is open (a game with no window takes no online registration) and has places left (no waiting list, F17). The player gives a display name for the game (the username by default), a team preference, the federation number when the game asks for one, and, when the game wants them, up to the field's `max_replicas` pre-declared replicas: one of theirs in the field's registry, or a type and a class of the field's `limit_template` (the controller's own templates, `app/lib/chrono/limit_templates/`). The player changes or cancels until the window closes; the field's `admin` and `gm` until the game starts.
- **The player's id at the field** is made on the first registration there (`p-` and 12 base32 characters). A player whose phone already checked in there without an account claims that id instead (`POST /api/v1/me/player-ids` with the phone's id and secret): the site server keeps the secret's SHA-256 in a claim, and the field's controller, which holds the hash from the phone's first check-in, confirms or refuses it at its next sync. The site server never had the controller's hashes, and still has none.
- **The ticket:** 32 random bytes per registration, shown once (`ticket`, the app's, and `ticket_text`, an `atalaia:ticket:` code to print); only its SHA-256 is kept and sent in the roster. It matches an arrival to a registration; it is no game credential.
- **Game day:** the controller pulls the schedule of the next 14 days; the GM makes the game from a scheduled game (the console's *Create from the schedule*), which links the two (`scheduled_games.controller_game`) and moves the scheduled game to `in_progress` and `completed` with the game. The controller pulls the roster until the game starts: registrations become expected check-ins with their replicas already in the "replicas to chrono" list. After the game it pushes each registration's outcome (`checked_in`, `no_show`), its declarations' final states and the walk-ins as a count; a registration it had only from the app is matched by its ticket's hash. The controller is the authority: nothing from the site server changes a game that has started.
- **In the app** (decisions S16-13, S17-10 to S17-16): *Participante › Inscrições online* logs in to the site (password, then the TOTP step; the refresh token rotated as the server asks), lists the field's games (`GET /api/v1/fields-by-slug/{slug}`), registers with replicas, keeps the ticket on the phone and can send it at check-in, changes and cancels, and claims the phone's player id. The public register page opens it with an `atalaia://register?site=&field=&game=` link, or the page's address pasted into the app. The app does not make accounts (no privacy notice to show yet, S17-16).

## Registration import and platform adapters

ADR-P4-12, decisions F20-F23 and S17-1 to S17-9 (S17-10 to S17-17 are the app's); the details are in [docs/integrations.md](docs/integrations.md).

- **Only what the check-in needs:** `display_name`, `external_ref`, `team_preference`, `federation_number`, `replicas`. Any other column is named in the answer as not imported and its values are never stored or logged.
- **Preview, then import:** `dry_run=true` writes nothing; a real import needs `basis_confirmed=true` (the field is the data controller of the list it brings and must have its own basis for it). A refused row does not stop the others.
- **Idempotent:** rows upsert by `(source, external_ref)`; the same export imported again leaves everything `unchanged`, and registrations of that source missing from the file are listed, never cancelled. Imported registrations have no account and no ticket (the marshal ticks them by name), count toward `max_players` and go in the roster.
- **Guests:** imported registrations are deleted 30 days after their game (ADR-P4-8).
- **Adapters** only through a platform's documented API or a written agreement; off by default per field; configuration encrypted; every call audited; a failing or slow platform (20 s) fails only that call. Only the test adapter ships (`ATALAIA_TEST_ADAPTER=on`); no adapter for jogarairsoft.pt or any other named platform (F22).

## Club profiles and branding sync

P4R19, decisions S18-1 to S18-12; the sync's part is in [protocol/sync.md](../protocol/sync.md).

- **Clubs** are organisations' profiles: a name, a short name (the name its teams carry on controllers, 32 characters at most), a slug, a description, a colour, a logo and a crest. Any account can make one and becomes its `admin`; admins invite accounts by username and the person accepts; a club keeps at least one admin. Club roles need no TOTP.
- **Images** (club logos and crests, a field's logo and wallpaper, a saved team's crest) are checked with the controller's own `images.py`, the same limits (logo 1 MiB and 16-2048 px, wallpaper 4 MiB and 320-4096 px, crest 512 KiB and 16-1024 px; PNG, JPEG or WebP; SVG refused; metadata stripped) and stored once by the SHA-256 of the checked bytes. Every upload must say `rights_confirmed=true` and is answered with the rights reminder: upload only images you have the right to use. An image nothing uses is purged a day after its upload.
- **Public club pages** (`/c/<slug>/`) are off by default; a club's admin turns one on. Each has a report button (a plain form; a reason and a text; no address kept; 5 reports an hour per address); a server administrator sees the reports and can hide a page, which is then a 404 like a page that never existed, though fields that saved the club's team keep it.
- **A field's branding and saved teams** are edited by its staff; a club's team uses the club's short name and crest unless it sets its own; names are unique per field. Controllers with `[sync] branding = "site"` pull them (`GET /api/v1/sync/field`) and fetch the images they lack by SHA-256 (`GET /api/v1/sync/images/{sha256}`, only the field's own), check each again and apply them; with the default `"local"` nothing is pulled.

## Personal data

ADR-P4-8, with decisions S12-1 to S12-8. The field operator is the data controller; `personal_data.py` lists every table that holds personal data, and each later plan phase adds its tables there (access, export, erasure, purge) in the same change.

- **Access and export:** `GET /api/v1/me/data` answers `{format, generated_at, user, field_roles, sessions, audit_log, audit_log_about_you, consents, games, player_ids, chrono_records, marshal_keys, scheduled_games, registrations, player_id_claims, clubs, club_reports}`: the account (never the password hash or the TOTP secret), roles per field, sessions with their addresses and user agents, the person's own audit entries with addresses, entries others made about the account (a role granted: what and when, not who) the consent records, the games the person holds a role on, and the chrono registry's: the person's player id at each field, per field their readings (each as signed, with the marshal's public key), replicas, violations and refused readings, and the keys they registered as a marshal; the games they scheduled as a field's staff; their registrations with the pre-declared replicas and outcomes (never the ticket) and their claims of a phone's player id. `GET /api/v1/me/export` puts the same data in a ZIP: `export/profile.json`, `field_roles.json`, `sessions.json`, `audit_log.json`, `audit_log_about_you.json`, `consents.json`, `games.json`, `player_ids.json`, `chrono_records.json`, `marshal_keys.json`, `scheduled_games.json`, `registrations.json`, `player_id_claims.json` and a `README.txt` in English and Portuguese.
- **Rectification:** the username and email (`PATCH /api/v1/me`) and the password (`POST /api/v1/me/password`), each with the current password, under the same lockouts as a login. The audit log names the fields changed, never their values.
- **Erasure** (`DELETE /api/v1/me`, with the password and, for an account with TOTP, a code) anonymises: the account becomes `deleted-` and 16 random hex characters with no email, no password, no TOTP and no consent; its roles, sessions and consents are deleted; its links to per-field player ids go, while the signed chrono records stay exactly as signed (their replicas without make, model and tag, the person's marshal keys unlinked); the games it scheduled stay the field's, without the link to the account; its registrations for games still to come are cancelled, and every registration loses the account, the name, the team preference, the federation number and the ticket (the outcome and the declarations' states stay, the field's history); its claims are deleted; its club memberships and invitations are deleted, and the clubs it made and the reports it made or decided stay without it; its audit entries stay without their addresses; the erasure is logged with no account and no address. Names starting with `deleted-` are reserved. The last server administrator cannot be erased.
- **Consents:** each one recorded in `consents` with its purpose (`account`, or `chrono_sharing` for one field) and `ATALAIA_PRIVACY_NOTICE_VERSION`; registration and `create-admin` record the account consent.
- **Retention:** every day at `ATALAIA_PURGE_HOUR` (03:00 UTC) the server deletes sessions 30 days after they expired or ended (with their refresh tokens) and audit entries older than 36 months, games and scheduled games (with their registrations) 24 months after they ended, a registration's federation number 30 days after its game, claims of player ids 30 days after they were made, imported registrations (guests) 30 days after their game, and the chrono registry after the field's `default_retention_days` (365: readings by their time, readings kept apart by their arrival, then replicas and keys no reading needs), club invitations not accepted after 30 days, decided club page reports after 12 months and branding images nothing uses a day after their upload, and logs what it deleted. `python -m atalaia_server purge [--dry-run]` runs it once (`docker compose exec server python -m atalaia_server purge`).
- **Templates** for the operator to fill in, to be reviewed by a lawyer before use: [`docs/templates/privacy-notice-pt.md`](../docs/templates/privacy-notice-pt.md), [`privacy-notice-en.md`](../docs/templates/privacy-notice-en.md) and the hosted service's data processing agreement [`dpa-template.md`](../docs/templates/dpa-template.md).

The synced games (plan phase 13) name players only by the field's pseudonymous player ids, which an account holds from plan phase 16 (its first registration at the field, or a phone's id the controller confirmed); a person's games in the access answer are still the ones they hold a per-game role on (`games` in the access answer, `games.json` in the export; erasure deletes the roles). A game, with its events, counters, nodes and roles, is deleted 24 months after it ended.

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

Each test class gets a fresh database, migrated to head, on the test PostgreSQL; there is no SQLite stand-in (decision P4R17). `tests.test_migrations` also steps through every revision, checks that each downgrade restores the schema exactly, and that the migrations build exactly the ORM models. The tests that need no database and nothing beyond the controller's Ubuntu packages (`test_config`, `test_ids`, `test_shared_imports`, which also imports the sync's shared checker and client, `test_chrono_verify` and `test_feeds`: the iCalendar writer against RFC 5545's own examples and the JSON feed against its schema) also run in `tools/check.sh` and in CI's `controller` job; `test_passwords`, `test_totp` (with RFC 6238's and RFC 4226's own test vectors), `test_tokens` and `test_ratelimit` need no database but need argon2-cffi, PyJWT and pyotp, so they run in the server's image only. `test_personal_data` covers access, the export's ZIP, rectification, password changes, erasure (with TOTP, and the last administrator) and the retention purge, its command and its daily task. `test_sync` covers the API keys and their rotation, replays, duplicates, out-of-order batches, a standby controller's copy, the score merge with a negative adjustment, game identity, the shared vectors, per-game roles and the games API; `test_sync_stream` the WebSocket; `test_scheduling` the scheduled games, their roles, rules and `SEQUENCE`, the field page's settings and the schedule's personal data; `test_field_pages` the public pages and feeds (drafts and other fields never shown, pt-PT and English, escaping, the security headers, ETags and `304`, the per-address limit); `test_clubs` clubs, members, images, public club pages, reports and hiding, and club membership as personal data; `test_branding_sync` a field's branding and saved teams, the sync's answer and images, and (with the real controller) a club's crest following its team to a second field's controller; `test_sync_e2e` runs the real controller engine and its sync client against the site server served by uvicorn on a loopback port in the same container, on the test PostgreSQL (`python3 tools/docker_server.py test tests.test_sync_e2e`). CI's `server` job builds the same test image and runs the same `sh tests/run.sh test` and `sh tests/run.sh migrations` against a `postgres:16-alpine` service container.

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
