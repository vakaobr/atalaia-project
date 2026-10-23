<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Controller sync

How a field controller pushes its games to a site server: the games' metadata, their event logs, their score counters and their nodes; the field's chrono registry: the marshals' public keys, the replica registry and the signed chrono readings (plan phase 14); game day (plan phase 16): the schedule and rosters it pulls, the registrations' outcomes and the claims' verdicts it pushes; branding (plan phase 18): the field's branding and saved teams it pulls with `[sync] branding = "site"`; the remote GM (plan phase 19): with `[sync] remote_gm = true`, its live game on the stream and the commands of the field's GMs back; and the remote ATAK relay (Phase 4 follow-up FU5): with `[atak] remote = true`, its CoT events on the stream for the field's enrolled ATAK devices. Design: ADR-P4-3 and ADR-P4-5 with their 2026-10-19 amendments in `docs/phase-4-site-server/ADR.md`; decisions P4R10-P4R15, S13-1 onwards, S14-1 onwards, S16-1 onwards and S18-1 onwards in `docs/review/decisions-to-review.md`.

Implementations: `controller/atalaia_controller/sync_client.py` (the controller's client), the Android field controller's port of it (`app/lib/controller/controller_sync.dart`, with `controller_remote_gm.dart`; PE24 slice S7) and `server/atalaia_server/sync.py` with `api/sync.py` (the site server). Both Python sides check bodies with the same plain-Python module, `controller/atalaia_controller/sync_format.py` (the phone with its Dart port, `controller_sync_format.dart`), and all three are tested against the shared vectors in [`vectors/sync.json`](vectors/sync.json): 14 valid bodies, 65 invalid ones with the error code and path they must fail with, 3 score merges worked out by hand, under `answers` 9 valid and 32 invalid answers of the endpoints the controller pulls (`sync_format.ANSWERS`), and under `stream` 15 valid and 43 invalid messages of the remote GM and the remote ATAK relay (`sync_format.STREAM`, plan phase 19, Phase 4 follow-up FU5). The site server verifies each chrono reading with the controller's own `controller/atalaia_controller/chrono.py` (`server/atalaia_server/chrono_verify.py`), against [`vectors/chrono_record.json`](vectors/chrono_record.json) too.

## The link

- **The controller opens every connection** (P4R12). A field controller sits behind a phone's 4G link and usually carrier-grade NAT; the site server never connects to it and holds none of its tokens.
- **HTTPS**, the site server's certificate checked against the system's CAs or a CA file in the controller's settings (`[sync] ca_file`). `http://` only to the same machine (tests, a local trial). The client follows no redirect, so the key never goes to another address.
- **The field's API key** in every request: `Authorization: Bearer <key>`. A key is 32 random bytes, base64url without padding (43 characters), made by the site server for one field (`POST /api/v1/fields/{field}/sync-keys`, shown once). The site server keeps only its SHA-256 and compares it in constant time; a field has at most two live keys, so a new one can be installed before the old one is revoked (P4R13). Both sides show a key's **fingerprint**: the first 8 hex digits of the SHA-256 of the key's text.
- **Offline first.** The controller's game never waits for the network: everything is in its SQLite store first, and the client sends from there, in its own thread, every 30 s while a game runs and every 5 min between games, doubling the wait after a failure up to 5 min and respecting `Retry-After`.

## The common part of every body

| Field | Type | Values |
| --- | --- | --- |
| `sync_version` | integer | `1` |
| `controller.id` | text | a UUID in its canonical lower-case form: the controller's own id, made once and kept in its store. A standby controller has its own. |
| `controller.version` | text | the controller's version, 1-32 of `A-Za-z0-9.+_-` |
| `game.game_id` | integer | 0-65535: the game's id on the radio |
| `game.game_seed` | integer | 0-4294967295: the game's random seed (in the join, so a standby controller has the same) |

The chrono registry's three bodies (`marshals`, `replicas`, `chrono`) belong to the field, not to a game: they have `sync_version` and `controller` and **no `game`** (one is an error).

A game is **`(field, game_id, game_seed)`** (P4R11): the field comes from the API key, the 16-bit `game_id` repeats over the months, the seed does not. The controller never needs to learn a site server id first. Unknown fields anywhere (except a node's `info`) are an error: a body carries what this page lists and nothing else.

Errors are `400 {"detail": "invalid_body", "error": "<code>", "path": "<where>"}` with the first problem found; `401 {"detail": "invalid_api_key"}` for a missing, wrong or revoked key; `404 {"detail": "game_not_found"}` for events, scores or nodes of a game the site server does not have yet (the client then sends the game first and tries again); `413` for a body over 1 MiB; `429` with `Retry-After`.

## POST /api/v1/sync/games

Creates the game or updates its metadata. `meta`:

| Field | Type | Required | Values |
| --- | --- | --- | --- |
| `name` | text | yes | 1-64 characters, no control characters |
| `mode_id` | text | yes | the mode's id, `[a-z0-9][a-z0-9._+-]*`, at most 128 |
| `teams` | array of text | yes | 1-8 different team names of 1-23 bytes |
| `state` | text | yes | `ready`, `running`, `paused` or `ended` |
| `created_at` | number | yes | seconds since 1970 (UTC), the controller's clock |
| `team_info` | object | no | `{team: {display_name?, crest_id?}}`: display names (1-32 characters) and crest ids (64 hex digits) of the game's teams |
| `params` | object | no | the mode's parameters, at most 8,192 bytes of JSON |
| `squads` | integer | no | 0-16 |
| `duration_ms` | integer | no | 0 (no limit) to 4294967295 |
| `node_id` | integer or null | no | the sending controller's node id in the game |
| `joined` | boolean | no | the sending controller joined as a standby |
| `started_at`, `ended_at` | number or null | no | seconds since 1970 |
| `scheduled_game_id` | text or null | no | the site server's scheduled game this game was made from (a lowercase UUID; plan phase 16) |

Never in `meta`: the game key, the node assignments, check-ins.

Answer: `200 {"game": "<the site server's id>", "created": true|false, "state": "<the stored state>"}`, and with a `scheduled_game_id` also `"scheduled": true|false`: whether that scheduled game is this field's and was linked. A linked scheduled game follows the game: `in_progress` once it runs, `completed` once it ended (never back); a scheduled game made into a game again is linked to the last one.

**Merging two controllers' metadata** (a primary and its standby push the same game): the state only moves forward (`ready` < `running` = `paused` < `ended`; between `running` and `paused` the last one wins; `ended` stays), `started_at` keeps the earliest time and `ended_at` the latest, and everything else is the last one sent. A standby controller (`joined: true`) that says `ended` may only have left the game, so its `ended` counts as `running` (or `ready` if the game never started); a `game.end` event, which only the controller that ends the game logs, ends it on the site server too (decision S13-5).

## POST /api/v1/sync/events

A batch of the game's events, as the controller's log holds them:

| Field | Type | Values |
| --- | --- | --- |
| `after_id` | integer | the controller's cursor: the last event id the site server acknowledged for this game (0 at first) |
| `events` | array | 1-500 events, their `id`s strictly increasing and above `after_id` |

An event:

| Field | Type | Required | Values |
| --- | --- | --- | --- |
| `id` | integer | yes | the event's id in the sending controller's log (`events.id`) |
| `node` | integer | yes | 0-65535: the node that made it |
| `seq` | integer | yes | 0-65535: the node's event sequence number |
| `t` | integer | yes | 0-4294967295: game time in ms |
| `type` | text | yes | an event name, standard (`zone.captured`) or custom (`x.club.name`), under 48 bytes; checked by its form, not against today's list, so a newer controller's events reach an older site server |
| `prio` | text | yes | `telemetry`, `normal` or `critical` |
| `team` | text or null | no | a team name |
| `squad` | integer or null | no | 0-255 |
| `data` | object | no | the event's data, at most 1,024 bytes of JSON, keys `[a-z][a-z0-9_]*`, at most two levels deep; **no position**: a key `lat`, `lon`, `lng`, `latitude`, `longitude`, `alt`, `altitude`, `position`, `positions`, `gps`, `coords`, `coordinates`, `x` or `y` anywhere is an error (P4R25) |
| `epoch`, `pkt_seq` | integer or null | no | 0-65535: the radio packet's epoch and sequence number |

A `score.delta` event (a GM's adjustment, or one from a field script) needs `data.amount` (an integer, -1,000,000 to 1,000,000, **negative allowed**) and a team (`data.team`, or `team`; both, if given, the same).

Answer: `200 {"acked_id": <the last id of the batch>, "inserted": n, "duplicates": n}`. The controller moves its cursor to `acked_id`.

**Idempotent.** Events are unique on the site server on `(game, node, seq, t, type)`, the controller's own key (a box restarts its `seq` at 1 after a reboot, so `seq` alone is not enough). A batch sent again, an older batch arriving after a newer one, or a standby controller's copy of the same events (with ids from its own log) are counted as `duplicates` and change nothing. The cursor is only an optimisation; the key is what makes replays safe.

## POST /api/v1/sync/scores

The game's score counters, per source:

| Field | Type | Values |
| --- | --- | --- |
| `counters` | object | `{source: {team: value}}`, at most 1,024 sources |

A source is `node-<node id>` (a node's counters, as it last reported them in STATE) or `field-<run>@<controller node id>` (one run of a controller's field script: its `score.add` points never travel on the radio; the controller's node id keeps two controllers' runs apart, decision S13-3). A value is an integer 0 to 2^31-1; teams must be the game's.

**The merge (P4R10).** The site server keeps, per (game, source, team), the largest value it was ever sent (`GREATEST`). A total is never merged: a game's totals are **the sum of its counters per team, plus the amounts of its `score.delta` events**, as the controller's `FieldController.total_scores` makes them. A GM's -50 therefore lowers the total, and a late, older snapshot changes nothing. Example (the first of the vectors' merges):

| Snapshot, in arrival order | `node-3` red | `node-3` blue | `node-4` blue | `field-1@0` red |
| --- | --- | --- | --- | --- |
| 1 | 10 | | | |
| 2 | 40 | 5 | | |
| 3 (an older one, late) | 25 | | | |
| 4 | | | 20 | 7 |
| **kept** | **40** | **5** | **20** | **7** |

With adjustments red -30 and blue +15: red = 40 + 7 - 30 = 17, blue = 5 + 20 + 15 = 40.

Answer: `200 {"totals": {team: value}, "updated": n}`.

## POST /api/v1/sync/nodes

The game's nodes:

| Field | Type | Values |
| --- | --- | --- |
| `nodes` | array | at most 512 of `{node_id, name, role, last_seen, info?}`: node id 0-65535 (each once), name and role 1-32 characters, `last_seen` seconds since 1970 |

`info` may carry `owner` (a team), `phase`, `battery_pct`, `rssi`, `epoch`, `game_time_ms` (integers), `snr` (a number), `platform`, `fw_version`, `core_version`, `tier` (texts up to 32) and `capabilities` (up to 32 texts); anything else in `info` is dropped, not refused. The site server keeps the entry with the latest `last_seen`.

Answer: `200 {"nodes": n}`.

## The chrono registry (plan phase 14)

The controller sends these after its games, in this order, each item once and again only when it changed (the controller's `sync_items`, store schema 6): the marshals' keys first, so that the site server can verify every reading it then gets.

### POST /api/v1/sync/marshals

The marshals' Ed25519 **public** keys, each with the period it was the marshal's key on the sending controller (decision P4R14):

| Field | Type | Values |
| --- | --- | --- |
| `marshals` | array | 1-512 keys |

A key:

| Field | Type | Required | Values |
| --- | --- | --- | --- |
| `marshal_id` | text | yes | 1-64 of `A-Za-z0-9._:-` (the records' `marshal_id`) |
| `name` | text | yes | the marshal's name as shown: 1-64 characters, no control characters (the records' `marshal_name` rule) |
| `public_key` | text | yes | the 32-byte public key in standard base64 with padding (44 characters) |
| `registered_at` | number | yes | seconds since 1970: when the controller first registered this key |
| `replaced_at` | number or null | no | when the controller replaced it with the marshal's next key; null (or absent): the marshal's current key |
| `player_id` | text or null | no | the marshal's own player id at the field, when the marshal registered the key from the app |

Each (marshal, key) once per body, and at most one current key per marshal. **Never a private key**: there is no field for it, and the marshals' phones never send one (P4R14). The site server keeps every key with its period (its earliest `registered_at`, the last `replaced_at` sent), so the records an earlier key signed still verify after a rotation; a field's admin can also revoke a key there as compromised.

Answer: `200 {"marshals": n, "added": n, "resolved": n}`: `resolved` counts readings kept apart earlier for want of a key of their marshal (`marshal`, below) that verify now and are stored.

### POST /api/v1/sync/replicas

The field's replica registry, as the app makes it (`app/lib/chrono/replica.dart`):

| Field | Type | Required | Values |
| --- | --- | --- | --- |
| `replicas` | array | yes | 1-500 replicas, each `replica_id` once |
| `replica_id` | text | yes | a lowercase UUID |
| `owner_player_id` | text | yes | the owner's player id at the field (1-64 of `A-Za-z0-9._:-`) |
| `type` | text | yes | `aeg`, `gbb`, `hpa`, `bolt_action`, `dmr`, `sniper`, `pistol` or `shotgun` |
| `class` | text | yes | the class of the field's limit template, 1-32 of `a-z0-9_` |
| `make_model` | text | no | 1-64 characters, no control characters |
| `registered_at` | text | no | `YYYY-MM-DDTHH:MM:SSZ` |
| `tag_type`, `tag_uid` | text | no, both or neither | `nfc` with a UID of 4, 7 or 10 bytes (`04:A2:B3:C4`, upper-case hex), or `qr` with 1-64 printable ASCII characters |

Answer: `200 {"replicas": n}`. The site server keeps the last one sent per `replica_id`.

### POST /api/v1/sync/chrono

The signed chrono readings ([`chrono-record.md`](chrono-record.md)), with the controller's series and its outcome (decision P4R15):

| Field | Type | Required | Values |
| --- | --- | --- | --- |
| `readings` | array | yes | 1-500 readings |
| `record` | text | yes | the signed record's JSON **text**, exactly as the controller stored it, at most 4,096 bytes of UTF-8 |
| `series_id` | text | yes | the controller's series (a lowercase UUID): the readings of one upload |
| `outcome` | text or null | yes | the series' result on the controller: `pass`, `fail`, `warn` or `unjudged` |
| `received_at` | number | yes | seconds since 1970: when the controller received and verified the reading |
| `game_seed` | integer | no | 0-4294967295: the seed of the record's `game_id` on the controller, so the site server can link the reading to that game |

The record travels as text so that the site server can keep it **verbatim**. This page checks only that it is a text of at most 4,096 bytes; its content is the site server's to check, reading by reading, with `chrono.py`: the fields (`format`), the signature's presence (`unsigned`), a key of its `marshal_id` that was valid at `received_at` on the controller's clock, not replaced before then and not revoked (`marshal`), and the Ed25519 signature with each such key (`signature`). A reading under a stored `reading_id` with the same record (in any text) is a **duplicate**; with a different record it is a `conflict`. A reading that fails is **kept apart** (the site server's `chrono_rejects`, with its reason, for the field's staff) and named in the answer; it never refuses the batch, and the controller does not send it again (it logs it). A spot check whose series failed or warned becomes a violation on the site server. The field is the API key's: a record's own `field_id` is the controller's `[checkin] field_id` text and is kept as it is.

Answer: `200 {"accepted": n, "duplicates": n, "refused": [{"index", "reading_id", "reason", "detail"}], "violations": n}`.

## Game day (plan phase 16)

ADR-P4-11 as amended. The controller pulls with `GET` (the same key; answers are checked by both sides with `sync_format.ANSWERS`) and pushes with `POST`, in each cycle after its games and the chrono registry. A site server without these endpoints (a `404` or `405` from an older one) is skipped. **The site server never sends anything into a running game**: a roster is applied only while its game has not started.

### GET /api/v1/sync/schedule?days=14

The field's `published` and `in_progress` scheduled games that have not ended and start within `days` (1-60): `200 {"sync_version": 1, "games": [...]}`, at most 200, by start. A game: `scheduled_game_id` (UUID), `title` (1-256), `starts_at`, `ends_at` (seconds since 1970), `status`, `teams` (up to 16 names of 1-32 characters: a controller game's names must fit the radio, 23 bytes), `federation` (`off`, `optional`, `required`), `predeclare_replicas`, `registered` (the live registrations' count), and if set `mode_id`, `max_players`, `location`. The controller keeps the last one for the GM.

### GET /api/v1/sync/roster?scheduled_game_id=

One scheduled game's live registrations (`404 {"detail": "scheduled_game_not_found"}` for another field's or none): `200 {"sync_version": 1, "scheduled_game_id", "status", "federation", "registrations": [...]}`, at most 5,000. A registration: `registration_id` (UUID), `player_id` (`p-` and 12 base32), `display_name` (1-32), `replicas` (up to 20 declarations of [checkin.md](checkin.md): `declaration_id`, `type`, `class`, `replica_id`?, `make_model`?; no state), and if set `team_preference`, `federation_number` (only when `federation` is not `off`), `ticket_sha256` (64 lowercase hex). Only what the check-in holds: no account, no email. Each registration and each player id once; each declaration id once in the roster.

### GET /api/v1/sync/claims

Accounts' claims of a player id of this field, waiting for its verdict: `200 {"sync_version": 1, "claims": [{"claim_id", "player_id", "secret_sha256"}]}`, at most 500. `secret_sha256` is the SHA-256 of the secret the claiming phone holds for that id.

### POST /api/v1/sync/claims

The controller's verdicts, a body of the field (no `game`): `results`: 1-500 `{claim_id, result}`, `result` one of `confirmed` (it knows the id with that secret's hash, compared in constant time), `refused` (with another, or with none: an id made for a hand check-in) or `unknown` (the claim waits). The controller's own hashes are never sent. Answer: `200 {"confirmed": n, "refused": n, "pending": n}`; a confirmed claim links the id to the account unless another account holds it already.

### POST /api/v1/sync/checkins

Once a game made from a scheduled game has ended (and again only if it changes): the common part with `game`, and

| Field | Type | Values |
| --- | --- | --- |
| `scheduled_game_id` | text | the scheduled game (UUID) |
| `walkins` | integer | 0-100,000: players at the field without a registration, a count only |
| `registrations` | array | at most 5,000 of `{registration_id, player_id, outcome, declarations, ticket_sha256?}` |

`outcome` is `checked_in` (the player came) or `no_show`; `declarations` are up to 20 `{declaration_id, state, reading_id?}` with the final states of [checkin.md](checkin.md) (`pending`, `passed`, `refused`, `withdrawn`). `ticket_sha256` only for a registration the controller had from the app and not from a roster: the site server applies it only if it is that registration's ticket. Never a name, a team preference or a federation number. Answer: `200 {"linked": true|false, "applied": n, "ignored": n, "declarations": n}`; an unknown scheduled game is `linked: false`, not an error.

## Branding and saved teams (plan phase 18)

P4R19. Only a controller with `[sync] branding = "site"` pulls these (the default, `"local"`, keeps the console's branding); it does so after game day in each cycle, and skips a site server without them (`404`, `405`). The field's branding and saved teams are edited on the site server by the field's staff; a saved team is a club's team (the club's short name and crest unless the team sets its own) or one of the field's own.

### GET /api/v1/sync/field

`200 {"sync_version": 1, "field": {...}, "teams": [...]}`, checked on both sides with `sync_format.check_field`:

| Field | Type | Values |
| --- | --- | --- |
| `field.field_name` | text or null | 1-48 characters, no control characters, no space at either end: the controller's field name (its check-in poster's); null keeps the controller's own |
| `field.accent` | text or null | `#rrggbb`, lower-case |
| `field.logo`, `field.wallpaper` | image or null | see below |
| `teams` | array | at most 200 `{team_id, name, colour, crest, club}`; each `team_id` (UUID) and each `name` once |
| `teams[].name` | text | 1-32 characters: the team preset's display name |
| `teams[].colour` | text or null | the colour the team usually plays, a team name as games use it (1-23 bytes, no spaces) |
| `teams[].crest` | image or null | a crest |
| `teams[].club` | object or null | `{slug, name}` of the club whose team it is |

An image is `{sha256, content_type, width, height, bytes}`: the SHA-256 (64 lower-case hex) of the image as the site server stores it (checked by `controller/atalaia_controller/images.py`, metadata stripped), `image/png`, `image/jpeg` or `image/webp`, and its size within the limits of its kind (logo: 16-2048 px, 1 MiB; wallpaper: 320-4096 px, 4 MiB; crest: 16-1024 px, 512 KiB).

### GET /api/v1/sync/images/{sha256}

The image's bytes with its `Content-Type`, for an image the field's branding or one of its saved teams uses (any other: `404 {"detail": "image_not_found"}`, whatever another field uses). The controller fetches only images it does not have, at most 50 a cycle, and stores one only if its bytes hash to the SHA-256 asked for and `images.check` accepts them with the limits of their kind without changing them; otherwise it keeps what it had and tries again in the next cycle. It then makes its field branding and its site-made team presets match the answer: a preset made on the controller with a site team's name becomes that team's; a team gone from the answer loses its preset. With `"site"` the console cannot change the field's branding nor those presets (`409`); the GM's own presets stay the GM's.

## The scenario library and game presets (plan phase 20)

ADR-P4-6 as amended (P4R7, P4R9). The field's staff keep scenarios (manifests, each save a revision) and game presets on the site server; every controller with the field's key pulls them with `[sync] library = true` (the default), after branding in each cycle, so a standby has the same scenarios as the primary (decision M8-3). A site server without these endpoints (`404`, `405`) is skipped. Both answers are checked on both sides with `sync_format.ANSWERS`.

### GET /api/v1/sync/presets

`200 {"sync_version": 1, "scenarios": [...], "presets": [...]}`:

| Field | Type | Values |
| --- | --- | --- |
| `scenarios` | array | at most 200 `{scenario_id, revision, version, name, sha256}`, each `scenario_id` once: the field's scenarios that are not archived |
| `scenarios[].scenario_id` | text | the package id (`org.club.foxhound`: dotted, lower case, at most 40 characters, no `+`) |
| `scenarios[].revision` | integer | 1 and up: the site server's count of saves |
| `scenarios[].version`, `name` | text | the manifest's (1-32 and 1-128 characters) |
| `scenarios[].sha256` | text | 64 lower-case hex: the SHA-256 of the manifest's UTF-8 text |
| `presets` | array | at most 200 `{preset_id, name, mode_id, params}`, each `preset_id` (UUID) and `name` (1-64 characters, no space at either end) once |
| `presets[].mode_id` | text | a game's mode id, a scenario's with its parts (`org.club.foxhound+org.atalaia.objectives`) |
| `presets[].params` | object | the mode's parameters, at most 8 KiB as JSON; they may hold the game's codes, like a game's `params` |

### GET /api/v1/sync/scenarios/{scenario_id}

One scenario's current revision: `200 {"sync_version": 1, "scenario_id", "revision", "sha256", "manifest"}`, `manifest` being the text as it was saved (YAML or JSON, at most 256 KiB) whose UTF-8 bytes must hash to `sha256` (`sha256_mismatch` otherwise). An archived scenario or another field's is `404 {"detail": "scenario_not_found"}`.

The controller fetches a scenario only when the SHA-256 differs from the one it last installed from the site (kept in its setting `sync.site_library`), compiles the manifest and loads its `field.lua` in its core again (`scenario_service.install`, the GM console's install), and stays the authority: a manifest it refuses is not fetched again until the site changes it, and one the live game runs waits until the game ends. A preset is saved by its name once its mode is installed on the controller and its parameters fit that mode (a site preset replaces a GM preset with the same name). Scenarios and presets the site no longer lists stay on the controller. `sync` in the controller's `GET /api/v1/controller` has `library`: whether it is on and supported, the last pull, what came from the site and the last problems.

## WS /api/v1/sync/stream

One WebSocket the controller opens (the `Authorization: Bearer` header on the upgrade; close code 4401 for a wrong key). Each message is a JSON object with `type` `games`, `events`, `scores`, `nodes`, `marshals`, `replicas`, `chrono`, `checkins` or `claims` and otherwise the same body as the POST of that name; the answer is `{"type": "<type>.ack", ...the POST's answer}`, or `{"type": "error", "detail", "error", "path"}` (the socket stays open). `{"type": "ping"}` gets `{"type": "pong"}`. The controller's client sends its sync bodies over HTTP (decision S13-8); it opens this socket only for the remote GM and the remote ATAK relay, below.

## The remote GM (plan phase 19)

Off by default (P4R12). Only with `[sync] remote_gm = true` does the controller open the stream above and keep it open, reconnecting after a failure (5 s, doubling up to 5 min; 5 min at once when the key is refused). The controller opens the connection; the site server never connects to it and never holds its GM or read token. On the socket, besides the sync bodies:

| Message | From | Body (besides `type`) |
| --- | --- | --- |
| `hello` | controller, first | `sync_version`, `controller`, `remote_gm` (boolean: whether it takes commands), and `atak: true` only when it will push CoT for the remote ATAK relay (below; absent means false). Answered `{"type": "hello.ack", "remote_gm", "atak_relay"}`, `atak_relay` true only when the controller asked and the site server's relay is on. Anything else of this section before it: `{"type": "error", "detail": "hello_first"}`. |
| `live` | controller | `sync_version`, `controller`, `live`: null (no live game) or `{game: {game_id, game_seed}, name, mode_id, teams, state, in_charge, totals: {team: integer, may be negative}, game_time_ms?, duration_ms?, nodes: [as POST /sync/nodes], events: [at most 50, as POST /sync/events], mode_commands?: [{name, roles}]}`. Sent at most every 2 s when something changed and every 30 s anyway; not answered. **Never** a position (an event whose data has one is refused, as in the sync), a token, a key or a check-in. |
| `command` | site server | `id` (a UUID), `game` `{game_id, game_seed}`, `command`, `params`, `user` `{id, username}` (the site server's account), `sent_at` (the site server's clock). |
| `command.result` | controller | `sync_version`, `controller`, `id` (the command's), `code`, `detail` (null or up to 200 characters). Not answered. |

Commands and their `params`, nothing else (`sync_format.REMOTE_COMMANDS`): `start` and `resume` (none), `pause` and `end` (`reason`, up to 64 characters, optional), `message` (`text`, 1-100 characters, to every node), `mode` (`name`, one of the game's declared mode commands, `[a-z][a-z0-9_]{0,23}`, and optionally `node`, 1-65535, 65535 every node, the default).

Result codes: `done`, `remote_gm_off` (the controller's setting is off), `invalid` (not in this form, or the engine refused it: an undeclared mode command), `stale` (`sent_at` more than 60 s from the controller's clock), `not_live` (not the controller's live game), `not_found`, `conflict` (the game's state does not allow it, or the controller is on standby), `unavailable` (the radio is down), `failed`.

The site server sends a command only for a user with the `gm` role on the field in a TOTP session, only to a controller that said `remote_gm: true`, and waits 10 s for its result. The controller checks every command again with the same function, refuses any while its `remote_gm` is off, carries out a command id at most once, and logs each one in its store (`remote_commands`, store schema 8); the site server logs each attempt in its audit log (`remote_gm_command`, `remote_gm_denied`). The user's API is `/api/v1/fields/{field}/remote-gm` (the live views), `.../remote-gm/commands` and `.../remote-gm/log` (`server/README.md`). Decisions S19-1 to S19-11.

## The remote ATAK relay (Phase 4 follow-up FU5)

Off by default on both sides: the controller's `[atak] remote = true` (it then opens the stream even with `remote_gm` off, and sends no `live` and refuses every `command`) and the site server's `ATALAIA_ATAK_RELAY=on`. After a `hello` with `atak: true` answered `atak_relay: true`, the controller sends:

| Message | From | Body (besides `type`) |
| --- | --- | --- |
| `cot` | controller | `sync_version`, `controller`, `events`: 1-100 CoT events as its ATAK emitter makes them (`controller/atalaia_controller/atak.py`), each a string: the XML declaration `<?xml version='1.0' encoding='UTF-8' standalone='yes'?>`, a newline and one `<event version="2.0">` (TAK Protocol version 0), at most 2,048 bytes. Not answered; refused whole (`{"type": "error", ...}`) if one event does not pass. |

Each event is checked by `sync_format.cot_event` on both sides: the declaration, then no `<!` (DOCTYPE, entity, comment, CDATA), no second processing instruction, no character reference; `event` with `version="2.0"` and no attributes beyond `uid`, `type`, `how`, `time`, `start`, `stale` (the emitter's); `uid` `atalaia.` and 1-120 of `A-Z a-z 0-9 . _ : -`; `type` one of `b-m-p-s-m` (a box, the extraction zone) and `a-f-G-U-C` (a player); `how` like `h-e`; the three times in CoT's format; exactly a `point` (`lat`, `lon`, `hae`, `ce`, `le`, numbers, in range) and a `detail` whose children are only `contact`, `remarks`, `color`, `usericon`, `__group`, `status` (a player's only `contact`, `__group`, `remarks`), each at most once, with no children of their own and only the emitter's attributes in the emitter's forms (decision FU5-17): `contact` only `callsign` (1-48 characters, whitespace folded), `remarks` no attribute and a text of at most 160 characters starting `Atalaia: `, `color` only `argb` (a signed 32-bit integer), `usericon` only `iconsetpath` = `COT_MAPPING_SPOTMAP/b-m-p-s-m/` and such an integer, `__group` only `name` (one of ATAK's 14 team colours) and `role` = `Team Member`, `status` only `battery` (0-100); no text but the remarks'. A `b-m-p-s-m` placed by hand (`how` `h-e` or `h-p`) is the field's map and goes to every enrolled device of the field; anything else (a player, its drop) only to a certificate allowed to see positions (P4R18). The site server relays its own serialisation of each event, never the controller's bytes, keeps the field's current picture in memory until each event is stale (a drop, stale before start, goes out and is forgotten), and stores nothing. The controller sends player positions here only with `[atak] remote_players = true`. Its devices' side (TLS with client certificates on port 8089, the enrolment) is in `server/README.md`, "Remote ATAK". Shared vectors: under `stream`, `hello_atak_relay`, `cot_box_player_and_drop` and 19 invalid messages.

## Never sent

Positions (they stay on the controller and are deleted when the game ends, P4R25; the one exception is opt-in on both sides: the remote ATAK relay's player events with `[atak] remote_players = true`, relayed in memory to the certificates allowed them and never stored), tokens and keys (the game key, the join key, player-token keys, the GM and read tokens, marshals' private keys), check-in names and federation numbers (what goes back for registered players is their outcome and declarations' states, plan phase 16), the players' field secrets and their hashes (a claim's verdict is computed on the controller). Player ids in event data (`player`) are the field's pseudonymous ids (`p-` and 12 base32 characters). What the chrono registry carries is what a signed record already holds (the player id, the replica, the marshal's id and name as signed) and the replica registry's own fields.
