<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Controller sync

How a field controller pushes its games to a site server: the games' metadata, their event logs, their score counters and their nodes; the field's chrono registry: the marshals' public keys, the replica registry and the signed chrono readings (plan phase 14); game day (plan phase 16): the schedule and rosters it pulls (and with them other fields' chrono records of the roster's players that their person shared), the registrations' outcomes and the claims' verdicts it pushes; branding (plan phase 18): the field's branding and saved teams it pulls with `[sync] branding = "site"`, with, since BR24, the field's check-in settings and limit template in the same answer and a `field.changed` note on the stream when any of them change; the remote GM (plan phase 19): with `[sync] remote_gm = true`, its live game on the stream and the commands of the field's GMs back; and the remote ATAK relay (Phase 4 follow-up FU5): with `[atak] remote = true`, its CoT events on the stream for the field's enrolled ATAK devices. Design: ADR-P4-3 and ADR-P4-5 with their 2026-10-19 amendments in `docs/phase-4-site-server/ADR.md`; decisions P4R10-P4R15, S13-1 onwards, S14-1 onwards, S16-1 onwards and S18-1 onwards in `docs/review/decisions-to-review.md`.

Implementations: `controller/atalaia_controller/sync_client.py` (the controller's client), the Android field controller's port of it (`app/lib/controller/controller_sync.dart`, with `controller_remote_gm.dart`; PE24 slice S7) and `server/atalaia_server/sync.py` with `api/sync.py` (the site server). Both Python sides check bodies with the same plain-Python module, `controller/atalaia_controller/sync_format.py` (the phone with its Dart port, `controller_sync_format.dart`), and all three are tested against the shared vectors in [`vectors/sync.json`](vectors/sync.json): 15 valid bodies, 76 invalid ones with the error code and path they must fail with, 3 score merges worked out by hand, under `answers` 23 valid and 82 invalid answers of the endpoints the controller pulls (`sync_format.ANSWERS`), under `shared_chrono_apply` 2 cases of what a controller keeps of a shared-chrono answer (decision S14-5), and under `stream` 23 valid and 67 invalid messages of the remote GM, the remote ATAK relay and the site server's `field.changed` note (`sync_format.STREAM`, plan phase 19, Phase 4 follow-up FU5, BR24). The site server verifies each chrono reading with the controller's own `controller/atalaia_controller/chrono.py` (`server/atalaia_server/chrono_verify.py`), against [`vectors/chrono_record.json`](vectors/chrono_record.json) too.

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

A game is **`(field, game_id, game_seed)`** (P4R11): the field comes from the API key, the 16-bit `game_id` repeats over the months, the seed does not. The seed is an identifier, not a secret that protects anything (`rand()` is seeded from the game key as well, `protocol/vectors/rand.json`), but players have no use for it: the controllers' game views for players and the scoreboard, and the site server's game lists for anyone but staff, leave it out. The controller never needs to learn a site server id first. Unknown fields anywhere (except a node's `info`) are an error: a body carries what this page lists and nothing else.

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

The controller sends these after its games, in this order, each item once and again only when it changed (the controller's `sync_items`, store schema 6): the marshals' keys first, so that the site server can verify every reading it then gets, and last the erasures (below).

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
| `limit_j` | number | no | 0.001-100: the class energy limit in joules the controller judged the series against (PKD-3), sent only when it knew the class; absent for an `unjudged` series. The site server works out `delta_j` from it (below). |

The record travels as text so that the site server can keep it **verbatim**. This page checks only that it is a text of at most 4,096 bytes; its content is the site server's to check, reading by reading, with `chrono.py`: the fields (`format`), the signature's presence (`unsigned`), a key of its `marshal_id` that was valid at `received_at` on the controller's clock, not replaced before then and not revoked (`marshal`), and the Ed25519 signature with each such key (`signature`). A reading under a stored `reading_id` with the same record (in any text) is a **duplicate**; with a different record it is a `conflict`. A reading that fails is **kept apart** (the site server's `chrono_rejects`, with its reason, for the field's staff) and named in the answer; it never refuses the batch, and the controller does not send it again (it logs it). A spot check whose series failed or warned becomes a violation on the site server, with `limit_j` (the series' limit, from the deciding reading's entry), `delta_j` (the deciding reading's energy minus that limit, null without a limit) and `repeat_offender` (the player has an earlier violation at the field, by the deciding readings' times: worked out again whenever one arrives, so one that arrives late puts the flags right; decision PKD-3, closing S14-7's gap) in the staff's violations list, the player's own history and the field export. `limit_j` is **additive and sent only when known**: a site server from before PKD-3 refuses the key (`unknown_field` at `readings[i].limit_j`), on which the controller sends that batch and every later one without it, so no reading is lost; a controller that does not send it leaves `limit_j` and `delta_j` null. The field is the API key's: a record's own `field_id` is the controller's `[checkin] field_id` text and is kept as it is.

Answer: `200 {"accepted": n, "duplicates": n, "refused": [{"index", "reading_id", "reason", "detail"}], "violations": n}`.

### POST /api/v1/sync/erasures

A controller's erasure reaches the site server by itself (S14-10, decision RET-4). When the field's controller erases a player's data on request (the GM's `DELETE /api/v1/players/{player}`, with or without `?chrono=1`, or the player's own `DELETE /api/v1/players/{player}/chrono`) and a sync is set up, it keeps an **erasure record** (`erasures`, store schema 17 on the Pi; `erasures` in the phone's check-in document) and sends it here in the next cycle, after the readings, until the site server acknowledges it. A body of the field (no `game`):

| Field | Type | Values |
| --- | --- | --- |
| `erasures` | array | 1-500, each `player_id` once |
| `erasures[].player_id` | text | the player's id at the field (1-64 of `A-Za-z0-9._:-`; a phone's id is `p-` and 12 base32 characters) |
| `erasures[].chrono` | boolean | the controller erased the player's chrono readings (and other fields' copies of them) |
| `erasures[].identity` | boolean | the controller erased the player's field identity, check-ins and declarations |
| `erasures[].erased_at` | number | seconds since 1970, 0 to 4102444800: when the controller did it |

At least one of `chrono` and `identity` is true (`bad_value` at `erasures[i]`); no name or other data about the person is ever sent. The site server applies what each says: `chrono` removes the player id's readings (with their violations), refused readings and replicas at this field (`chrono_registry.erase_player`, what `DELETE /api/v1/fields/{field}/chrono/players/{player_id}` does); `identity` removes the link of that player id to an account (`field_player_ids`) and the claims of it, so the game history's events no longer name a person. The same player id at another field is another person's and is not touched. Applying is idempotent: a player the site server has nothing of counts nothing, and sending again after a lost answer does no harm. Not refused by a hosted field's storage limit (an erasure only frees data). Answer: `200 {"players": n, "chrono_readings": n, "chrono_rejects": n, "replicas": n, "identities": n, "claims": n}`; the audit log has the counts (`chrono_player_erasure`, `by: controller`), never whose. The controller forgets a record once it is acknowledged (and only as it was sent: an erasure added to since stays); a record the site server never acknowledged goes with the chrono retention. A `404` or `405` (an older site server) is skipped: the controller does not ask again until it restarts, and the records wait for the retention.

## Game day (plan phase 16)

ADR-P4-11 as amended. The controller pulls with `GET` (the same key; answers are checked by both sides with `sync_format.ANSWERS`) and pushes with `POST`, in each cycle after its games and the chrono registry. A site server without these endpoints (a `404` or `405` from an older one) is skipped. **The site server never sends anything into a running game**: a roster is applied only while its game has not started.

### GET /api/v1/sync/schedule?days=14

The field's `published` and `in_progress` scheduled games that have not ended and start within `days` (1-60): `200 {"sync_version": 1, "games": [...]}`, at most 200, by start. A game: `scheduled_game_id` (UUID), `title` (1-256), `starts_at`, `ends_at` (seconds since 1970), `status`, `teams` (up to 16 names of 1-32 characters: a controller game's names must fit the radio, 23 bytes), `federation` (`off`, `optional`, `required`), `predeclare_replicas`, `registered` (the live registrations' count), and if set `mode_id`, `max_players`, `location`. The controller keeps the last one for the GM.

With `?revocations=1` (a controller of PRIV-5 onwards; an older one checks the answer strictly and does not ask) the answer may also carry `copies_revoked`, at most 1,000: `[{"player_id", "reason", "at"}]`, the players **of this field** whose pulled copies of other fields' chrono records (below) the controller must drop at once, game started or not: `reason` is `erasure` (the person erased their account, or this field's chrono data of them) or `withdrawn` (they withdrew a field's chrono-sharing consent); `at` seconds since 1970. The site server carries each for the field's chrono retention period; the controller does nothing for a player it has no copies of, so repeating it every cycle is harmless. Left out when there are none. The field's own readings are never touched.

### GET /api/v1/sync/roster?scheduled_game_id=

One scheduled game's live registrations (`404 {"detail": "scheduled_game_not_found"}` for another field's or none): `200 {"sync_version": 1, "scheduled_game_id", "status", "federation", "registrations": [...]}`, at most 5,000. A registration: `registration_id` (UUID), `player_id` (`p-` and 12 base32), `display_name` (1-32), `replicas` (up to 20 declarations of [checkin.md](checkin.md): `declaration_id`, `type`, `class`, `replica_id`?, `make_model`?; no state), and if set `team_preference`, `federation_number` (only when `federation` is not `off`, or the roster's `apd` rule has `checkin` or `register`), `apd_id` and `membership_expires` with it (APD membership, [apd.md](apd.md); the roster has a top-level `apd`, the rule, when it has `checkin` or `register`), `ticket_sha256` (64 lowercase hex). Only what the check-in holds: no account, no email. Each registration and each player id once; each declaration id once in the roster. The site server notes each successful pull on the scheduled game, for its staff (decision FU7-8): when, the label and fingerprint of the field API key used and the request's `User-Agent`; a GET carries no controller id, so nothing more is known, and the answer does not change.

### GET /api/v1/sync/chrono?scheduled_game_id=

Other fields' signed chrono records of the players on one scheduled game's roster (decision S14-5; `404 {"detail": "scheduled_game_not_found"}` for another field's or none). The controller asks right after it pulls that roster, for the same game and only while the game has not started: `200 {"sync_version": 1, "scheduled_game_id", "players": [...]}`, at most 5,000 players. A player: `player_id` (the id **at this field**, one of the roster's, each once) and `readings`, 1 to 100 (the newest), each `{field, record, public_key}`: `field` the name of the field where the record was made (1-128), `record` the record exactly as the marshal signed it ([chrono-record.md](chrono-record.md), as text, at most 4,096 bytes) and `public_key` the marshal's Ed25519 key (32 bytes, standard base64). A record appears once in an answer. A player with nothing to show is left out.

**What the site server gives** is what the staff's lookup (`GET /api/v1/fields/{field}/chrono/players/{player_id}`) gives, no more: only when this field and the other both have `chrono_sharing_enabled` **and the current sharing terms accepted** (`sharing_live`; decision LEG-41), only through the account that holds the player id at this field and at the other (per-field ids are never matched), and only with that person's live `chrono_sharing` consent **for each of the two fields**. A guest, a cancelled registration, a person with no account or no consent: nothing. The audit log has that a controller pulled and how many players and records (`chrono_shared_pull`), never whose.

**What the controller keeps**, per player of the roster it just pulled (`Checkin.apply_shared_chrono` in Python, `applySharedChrono` on the phone): a record only if the key given verifies its signature (`chrono.py`), it is not older than the retention period (the field's `chrono_retention_days`, 365 by default, by the record's `timestamp`) and its `reading_id` is not already a measurement of this field; players not on the roster are dropped; and a roster player the answer leaves out has none kept (a consent withdrawn, a field that stopped sharing). They are stored apart from the field's own readings (`shared_readings`, schema 13 on the Pi; `shared_readings` in the phone's check-in document): never judged, never counted in the "replicas to chrono" list's states, never sent back by `POST /api/v1/sync/chrono`, and a local measurement is never replaced. The chrono list's players (and the staff's check-in rows) carry `shared_readings`: `{reading_id, field, from_other_field: true, type, timestamp, velocity_mps, bb_weight_g, energy_j, marshal_name}`, so a marshal sees "Spot check 1.35 J at Arena Norte, 2026-10-18" and still has to chrono the replica here. They are deleted with the retention purge of readings, with the player's erasure and with `DELETE /api/v1/players/{player}/chrono`. A `404` or `405` (an older site server) is skipped quietly.

[`vectors/sync.json`](vectors/sync.json) has the answer's valid and invalid cases under `answers` (kind `shared_chrono`) and, under `shared_chrono_apply`, what both controllers must keep of an answer: the roster, the readings already stored as local ones, the answer, the stored ids per player and how many were dropped.

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

Every controller with the field's key does this by itself, **a standby controller too** (BR24; decision S18-11): a controller that joined a game as a standby (`POST /api/v1/controller/join`) needs its own `[sync]` with `branding = "site"`, and pulls the field's branding, saved teams and settings like the primary, in its own cycle, with or without a game. Nothing is copied from the primary.

### GET /api/v1/sync/field

`200 {"sync_version": 1, "field": {...}, "teams": [...]}`, and, **only when the request has `?settings=1`** and the site server knows them (BR24), `"settings": {...}`; checked on both sides with `sync_format.check_field`:

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
| `settings` | object, only with `?settings=1` | the field's check-in rules, below; absent from the answer to a request without the query |
| `settings.federation_label` | text or null | 1-16 characters, no space at either end: what the field calls its federation number; null (the field has none set) keeps the controller's own |
| `settings.max_replicas` | integer | 1-20: the replicas a player may declare per game |
| `settings.apd` | object, optional | the field's APD membership rule ([apd.md](apd.md)): `{accepted, register, checkin, expiry, custom}`, always sent by a site server that knows it (the default rule when none is set); an older site server sends none and the controller keeps its own rule. Error `bad_apd_rule` |
| `settings.country` | string or null, optional | the field's country ([apd.md](apd.md)): two capitals (ISO 3166-1 alpha-2) or null for "unset", always sent by a site server that knows it; it picks the controller's wording ("APD" for `PT`, "association membership" otherwise) and which entries of the shipped list it offers. An older site server sends none and the controller keeps its own. Error `bad_value` at `settings.country` |
| `settings.chrono_retention_days` | integer, optional | 30-3653: how many days the controller keeps chrono readings (its own, other fields' copies pulled for a roster, and a marshal's earlier keys), and this server its chrono registry; the field's `default_retention_days`, 365 by default (decision RET-2). An older site server sends none and the controller keeps its own. Error `out_of_range` or `not_an_integer` at `settings.chrono_retention_days` |
| `settings.game_retention_days` | integer, optional | 30-3653: how many days after it ended the controller keeps an ended game's events, scores, nodes and check-in rows, **90 by default** (decision RET-1; 90 days by the maintainer's decision of 2026-10-30, it was 365; chrono records keep their own 365). With a sync set up the controller deletes a game only once the site server has all of it (`sync_state.final`: ended, every event acknowledged), whatever its age (decision RET-3); without one, age alone decides. Same rules as the one above, at `settings.game_retention_days` |
| `settings.limit_template` | object | `{id, name, classes, status?, verified_date?}`: `id` (`[a-z0-9_]{1,32}`, the template's file name in `app/lib/chrono/limit_templates/`) and `name` (1-64), `status` null, `unverified` or `verified` (`verified` needs `verified_date`, `YYYY-MM-DD`), and 1-64 `classes`, each `class name` (`[a-z0-9_]{1,32}`) with `{max_energy_j, med_m, fire_mode}`: the energy limit in joules (above 0, up to 100), the minimum engagement distance in metres (integer 0-500, or null) and `full_auto`, `semi_only` or `bolt_only` |

The settings are the field's own on the site server (`limit_template`, `max_replicas` and `federation_label`, set by the field's admin with `PATCH /api/v1/fields/{field}`, decision S16-6), so what a player registers for on the site is what the controller's check-in accepts. The template travels whole, so a controller needs no copy of its file and a template the controller's build lacks still works. A controller with `[sync] branding = "site"` that gets them makes its check-in match: it sets its `max_replicas` and (when the site has one) its federation label as the GM's check-in settings, and uses the template's classes for declarations and for judging chrono readings; the limit template is kept in its store, so a restart (offline too) keeps the field's rules. With `"local"` it never asks, so nothing changes. The GM console's check-in settings are not locked: a console change lasts until the next pull, which puts the site's values back.

**Compatibility (BR24; additive only).** The answer to a request without `?settings=1` is byte for byte what it was before, because an older controller checks the answer strictly (`unknown_field`) and would refuse a key it does not know; so the site server adds `settings` only for a controller that asks. A newer controller against an older site server gets the old answer (the server ignores the query), treats `settings` as absent and keeps its own settings. A site server whose limit template file is missing or does not pass the check leaves `settings` out.

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

The controller fetches a scenario only when the SHA-256 differs from the one it last installed from the site (kept in its setting `sync.site_library`), compiles the manifest and loads its `field.lua` in its core again (`scenario_service.install`, the GM console's install), and stays the authority: a manifest it refuses is not fetched again until the site changes it, and one the live game runs waits until the game ends. A preset is saved by its name once its mode is installed on the controller and its parameters fit that mode (a site preset replaces a GM preset with the same name). What the site no longer lists is removed (below). `sync` in the controller's `GET /api/v1/controller` has `library`: whether it is on and supported, the last pull, what came from the site and the last problems.

### Removing what the site archived or deleted (decision S20-9, built from S20-8)

No wire change, no `sync_version` bump, no tombstones and no new field: a `presets` answer is the field's **whole** live library (a scenario's archive and a preset's deletion take it out of the answer; one with more than 200 of either is no valid answer, never a part of one), so an old controller keeps working as it did and a new one reads the absence. Against an older site server the rule is the same, since that server also lists only what is live.

A controller keeps in `sync.site_library` what it installed from the site (`scenarios`: id to SHA-256, `presets`: name to digest) and removes, in the cycle after the answer, each scenario and preset it names that the answer does not (`sync_format.library_removals`, shared vectors in `library_removal` of `vectors/sync.json`: state and answer give the sorted ids and names). Only what came from the site is ever a candidate: a preset or scenario the GM made is never touched. The controller then **keeps**, and asks again next cycle:

- a scenario the game that is not ended runs (`created`, `running` or `paused`): it goes in the cycle after the game ends;
- a scenario a scheduled game of the last schedule pulled names in its `mode_id` (the GM can still make a game from it): it goes once that scheduled game has left the schedule (started, ended or cancelled);
- and drops only the site's claim on a scenario whose kept manifest is no longer the one it installed from the site (the GM installed their own under that id): it stays as the GM's.

A removed scenario loses its package and its kept manifest; a preset made from it that the site still lists stays, waiting for the mode as before. A scenario saved again on the site (restored) is installed again, being absent from the state. A refused manifest the site archived is forgotten. The controller's `sync.library` status counts `scenarios_removed` and `presets_removed`. Games already played keep their history; a built-in mode is never removed.

## WS /api/v1/sync/stream

One WebSocket the controller opens (the `Authorization: Bearer` header on the upgrade; close code 4401 for a wrong key). Each message is a JSON object with `type` `games`, `events`, `scores`, `nodes`, `marshals`, `replicas`, `chrono`, `checkins` or `claims` and otherwise the same body as the POST of that name; the answer is `{"type": "<type>.ack", ...the POST's answer}`, or `{"type": "error", "detail", "error", "path"}` (the socket stays open). `{"type": "ping"}` gets `{"type": "pong"}`. The controller's client sends its sync bodies over HTTP (decision S13-8); it opens this socket only for the remote GM, the remote ATAK relay and, since BR24, the field's branding notes (below).

### `field.changed` (BR24, PKD-1)

The site server sends `{"type": "field.changed", "sync_version": 1}` (and, since PKD-1, optionally `what`, below: `sync_format.check_field_changed`) to every controller of the field that is connected, whenever the field's branding (name, accent, logo, wallpaper), a saved team (added, changed, its crest, removed; also a club's name, short name or crest, for each field that has a team of that club) or the check-in settings (`limit_template`, `max_replicas`, `federation_label`, `apd`) are changed and committed. It is sent in the background, once per connection, and is not answered; a change that changes nothing sends nothing. A controller with `[sync] branding = "site"` then pulls `GET /api/v1/sync/field?settings=1` (and the images it lacks) **at once** instead of at its next cycle (30 s or 5 min), unless it is backing off after a failure; one with `"local"` ignores it. The note is a hint, not the data: a missed one (the socket was down) costs only the wait for the next cycle, which pulls anyway.

**`what` (PKD-1; additive).** Besides the branding, the note says that the field's **scenario library** or **schedule** changed: `{"type": "field.changed", "sync_version": 1, "what": ["library"]}`, `what` being 1-3 distinct texts of `branding`, `library` (a scenario saved with a changed manifest or archived, a game preset made, replaced or deleted) and `schedule` (a scheduled game created, changed, published, cancelled or deleted); a note without `what` means `branding`, as before, and the site server still sends the branding's note exactly as in BR24 (so a controller before PKD-1 pulls it as it did), while a note with `what` is one a controller before PKD-1 ignores (it logs a form it does not know) and pulls at its next cycle, as it did. A controller then pulls at once what it takes from the site: `branding` only with `[sync] branding = "site"`, `library` only with `[sync] library` on (the default), `schedule` always (the game-day pull has no setting); the cycle that runs pulls everything due. A roster (the registrations of a scheduled game) is not announced: it comes with the next cycle.

A controller with `[sync] branding = "site"` or `[sync] library` on (the default since PKD-1) therefore opens the stream even with `remote_gm` and `[atak] remote` off: it then sends only `hello` (`remote_gm: false`, no `atak`) and pings, never a `live` view, a position, a token or CoT, and refuses every command as before (with `[sync] library = false` and `branding = "local"` the stream stays closed unless the remote GM or the ATAK relay is on, and the schedule is pulled at the cycle).

**Compatibility.** The note is a new message type from the site server: a controller before BR24 ignores a message type it does not know (so it needs no opt-in on the `hello`, which an older site server would refuse), and a site server before BR24 never sends it, leaving the pull to the cycle. The `hello` and `hello.ack` are unchanged.

## The remote GM (plan phase 19)

Off by default (P4R12). Only with `[sync] remote_gm = true` does the controller open the stream above and keep it open, reconnecting after a failure (5 s, doubling up to 5 min; 5 min at once when the key is refused). The controller opens the connection; the site server never connects to it and never holds its GM or read token. On the socket, besides the sync bodies:

| Message | From | Body (besides `type`) |
| --- | --- | --- |
| `hello` | controller, first | `sync_version`, `controller`, `remote_gm` (boolean: whether it takes commands), and `atak: true` only when it will push CoT for the remote ATAK relay (below; absent means false). Answered `{"type": "hello.ack", "remote_gm", "atak_relay"}`, `atak_relay` true only when the controller asked and the site server's relay is on. Anything else of this section before it: `{"type": "error", "detail": "hello_first"}`. |
| `live` | controller | `sync_version`, `controller`, `live`: null (no live game) or `{game: {game_id, game_seed}, name, mode_id, teams, state, in_charge, totals: {team: integer, may be negative}, game_time_ms?, duration_ms?, nodes: [as POST /sync/nodes], events: [at most 50, as POST /sync/events], mode_commands?: [{name, roles}]}`. Sent at most every 2 s when something changed and every 30 s anyway; not answered. **Never** a position (an event whose data has one is refused, as in the sync; positions have their own message, below), a token, a key or a check-in. |
| `positions` | controller | `sync_version`, `controller`, `game` (null, or `{game_id, game_seed}`), `positions`: at most 500 `{player_id, source, age_s, ...}` (PKD-5, below). Only with `remote_gm: true` in the `hello`. Not answered. |
| `command` | site server | `id` (a UUID), `game` `{game_id, game_seed}`, `command`, `params`, `user` `{id, username}` (the site server's account), `sent_at` (the site server's clock). |
| `command.result` | controller | `sync_version`, `controller`, `id` (the command's), `code`, `detail` (null or up to 200 characters), and optionally `missing` (only with `conflict`: 1-16 role names of up to 32 characters, the roles of the game with no joined node when a `start` was refused for that; decision RG-3). Not answered. |

Commands and their `params`, nothing else (`sync_format.REMOTE_COMMANDS`): `start` (optionally `force`, a boolean: the console's *Start anyway*, which starts the game although a role it needs has no joined node; decisions RG-1, RG-2) and `resume` (none), `pause` and `end` (`reason`, up to 64 characters, optional), `message` (`text`, 1-100 characters, to every node), `mode` (`name`, one of the game's declared mode commands, `[a-z][a-z0-9_]{0,23}`, and optionally `node`, 1-65535, 65535 every node, the default).

Result codes: `done`, `remote_gm_off` (the controller's setting is off), `invalid` (not in this form, or the engine refused it: an undeclared mode command), `stale` (`sent_at` more than 60 s from the controller's clock), `not_live` (not the controller's live game), `not_found`, `conflict` (the game's state does not allow it, or the controller is on standby), `unavailable` (the radio is down), `failed`.

**Positions for the remote GM (PKD-5; the maintainer's decision of 2026-10-28: "yes, always").** Whenever players share their position with the field controller and the controller's `[sync] remote_gm` is on, the controller sends the live game's positions on this socket, in their own `positions` message, so that a remote GM (a user with the `gm` role on the field in a TOTP session, as for the live view) sees them on the remote GM page. They are what a GM of the game sees on the controller (a GM sees every player), the latest of each player and none older than three reporting intervals (`position_interval_s`, 10 s by default). The message goes when the positions changed (at most every 5 s) and, while there are any, at least every 30 s so their ages stay fresh; one empty message (`game` null when no game is live) clears the page's list when the last one is gone or the game ends. A player: `player_id` (the field's pseudonymous id, never a name), `source` (`gps` or `ble`), `age_s` (seconds since the controller received it, 0-3600) and, optionally, `team` (the team's name), `squad` (1-255), `role`, `level` (0-9) and, for `gps`, `lat`, `lon` (WGS 84) and `accuracy_m`; for `ble` (the beacon's room, never the beacon's id), `room`, `zone`, and `x`, `y` (0-1, the beacon's place on its level's plan) when the GM placed it. `sync_format.check_positions` checks it on both sides (the shared vectors `positions_*` in `vectors/sync.json`); a message out of form is refused whole with `{"type": "error", ...}` and the last good one stays. The site server **relays them in memory only**: it keeps the last message of a link (replaced whole each time, dropped with the live game or after 90 s without news) and shows it in `GET /api/v1/fields/{field}/remote-gm` and its server-sent stream as each controller's `positions` (the players, each with its age now) and `positions_at`; it **never stores and never logs** a position, and drops those of a link that did not say `remote_gm: true`. The remote GM page lists them (the page has no field plan). The live view still carries no position. With `remote_gm` off nothing leaves, as before; the app's position-sharing notice tells the player that a remote GM may see their position.

The site server sends a command only for a user with the `gm` role on the field in a TOTP session, only to a controller that said `remote_gm: true`, and waits 10 s for its result. The controller checks every command again with the same function, refuses any while its `remote_gm` is off, carries out a command id at most once, and logs each one in its store (`remote_commands`, store schema 8); the site server logs each attempt in its audit log (`remote_gm_command`, `remote_gm_denied`). The user's API is `/api/v1/fields/{field}/remote-gm` (the live views), `.../remote-gm/commands` and `.../remote-gm/log` (`server/README.md`). Decisions S19-1 to S19-11.

## The remote ATAK relay (Phase 4 follow-up FU5)

Off by default on both sides: the controller's `[atak] remote = true` (it then opens the stream even with `remote_gm` off, and sends no `live` and refuses every `command`) and the site server's `ATALAIA_ATAK_RELAY=on`. After a `hello` with `atak: true` answered `atak_relay: true`, the controller sends:

| Message | From | Body (besides `type`) |
| --- | --- | --- |
| `cot` | controller | `sync_version`, `controller`, `events`: 1-100 CoT events as its ATAK emitter makes them (`controller/atalaia_controller/atak.py`), each a string: the XML declaration `<?xml version='1.0' encoding='UTF-8' standalone='yes'?>`, a newline and one `<event version="2.0">` (TAK Protocol version 0), at most 2,048 bytes. Not answered; refused whole (`{"type": "error", ...}`) if one event does not pass. |

Each event is checked by `sync_format.cot_event` on both sides: the declaration, then no `<!` (DOCTYPE, entity, comment, CDATA), no second processing instruction, no character reference; `event` with `version="2.0"` and no attributes beyond `uid`, `type`, `how`, `time`, `start`, `stale` (the emitter's); `uid` `atalaia.` and 1-120 of `A-Z a-z 0-9 . _ : -`; `type` one of `b-m-p-s-m` (a box, the extraction zone) and `a-f-G-U-C` (a player); `how` like `h-e`; the three times in CoT's format; exactly a `point` (`lat`, `lon`, `hae`, `ce`, `le`, numbers, in range) and a `detail` whose children are only `contact`, `remarks`, `color`, `usericon`, `__group`, `status` (a player's only `contact`, `__group`, `remarks`), each at most once, with no children of their own and only the emitter's attributes in the emitter's forms (decision FU5-17): `contact` only `callsign` (1-48 characters, whitespace folded), `remarks` no attribute and a text of at most 160 characters starting `Atalaia: `, `color` only `argb` (a signed 32-bit integer), `usericon` only `iconsetpath` = `COT_MAPPING_SPOTMAP/b-m-p-s-m/` and such an integer, `__group` only `name` (one of ATAK's 14 team colours) and `role` = `Team Member`, `status` only `battery` (0-100); no text but the remarks'. A `b-m-p-s-m` placed by hand (`how` `h-e` or `h-p`) is the field's map and goes to every enrolled device of the field; anything else (a player, its drop) only to a certificate allowed to see positions (P4R18). The site server relays its own serialisation of each event, never the controller's bytes, keeps the field's current picture in memory until each event is stale (a drop, stale before start, goes out and is forgotten), and stores nothing. The controller sends player positions here only with `[atak] remote_players = true`. Its devices' side (TLS with client certificates on port 8089, the enrolment) is in `server/README.md`, "Remote ATAK". Shared vectors: under `stream`, `hello_atak_relay`, `cot_box_player_and_drop` and 19 invalid messages.

## Never sent

Positions (they stay on the controller and are deleted when the game ends, P4R25; the exceptions: the remote GM's `positions` message, with `[sync] remote_gm` on, relayed in memory and never stored (PKD-5, above), and the opt-in remote ATAK relay's player events with `[atak] remote_players = true`, relayed in memory to the certificates allowed them and never stored), tokens and keys (the game key, the join key, player-token keys, the GM and read tokens, marshals' private keys), check-in names and federation numbers (what goes back for registered players is their outcome and declarations' states, plan phase 16), the players' field secrets and their hashes (a claim's verdict is computed on the controller). Player ids in event data (`player`) are the field's pseudonymous ids (`p-` and 12 base32 characters). What the chrono registry carries is what a signed record already holds (the player id, the replica, the marshal's id and name as signed) and the replica registry's own fields.
