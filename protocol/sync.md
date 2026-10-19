<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Controller sync

How a field controller pushes its games to a site server: the games' metadata, their event logs, their score counters and their nodes. Design: ADR-P4-3 and its 2026-10-19 amendment in `docs/phase-4-site-server/ADR.md`; decisions P4R10-P4R13 and S13-1 onwards in `docs/review/decisions-to-review.md`.

Implementations: `controller/atalaia_controller/sync_client.py` (the controller's client) and `server/atalaia_server/sync.py` with `api/sync.py` (the site server). Both check bodies with the same plain-Python module, `controller/atalaia_controller/sync_format.py`, and both are tested against the shared vectors in [`vectors/sync.json`](vectors/sync.json): 7 valid bodies, 30 invalid ones with the error code and path they must fail with, and 3 score merges worked out by hand.

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

Never in `meta`: the game key, the node assignments, check-ins.

Answer: `200 {"game": "<the site server's id>", "created": true|false, "state": "<the stored state>"}`.

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

## WS /api/v1/sync/stream

One WebSocket the controller opens (the `Authorization: Bearer` header on the upgrade; close code 4401 for a wrong key). Each message is a JSON object with `type` `games`, `events`, `scores` or `nodes` and otherwise the same body as the POST of that name; the answer is `{"type": "<type>.ack", ...the POST's answer}`, or `{"type": "error", "detail", "error", "path"}` (the socket stays open). `{"type": "ping"}` gets `{"type": "pong"}`. Plan phase 19 adds the remote GM's commands, which travel the other way on this socket (off by default, P4R12). The controller's client uses the HTTP endpoints in this version (decision S13-8).

## Never sent

Positions (they stay on the controller and are deleted when the game ends, P4R25), tokens and keys (the game key, the join key, player-token keys, the GM and read tokens), check-in names and federation numbers (until plan phase 16 defines what goes back for registered players). Player ids in event data (`player`) are the field's pseudonymous ids (`p-` and 12 base32 characters).
