<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Field check-in

A player arrives at the field, scans the **check-in poster** with the Atalaia app, checks in at the field controller and gets a player token, then declares the replicas they will use in that game. The controller keeps, per game, the **"replicas to chrono" list** that marshals work from; a signed chrono check-in series marks each declared replica passed or refused. Design: ADR-P3-13 in `docs/phase-3-android-players/ADR.md`; decisions F1-F12 and PE1 onwards in `docs/review/decisions-to-review.md`. Everything works with no internet and no site server.

Implementations: `controller/atalaia_controller/checkin_poster.py` (the poster codec), `checkin_ticket.py` (the ticket codec) and `checkin.py` (the rules, Python: the field controller), `app/lib/protocol/checkin_poster.dart`, `app/lib/protocol/checkin_ticket.dart` and `app/lib/checkin/` (Dart: the app), and `app/lib/controller/controller_checkin.dart` (the rules on the Android controller, decision PE24's slice S5, checked against the Pi's by the shared cases in [`vectors/controller_api.json`](vectors/controller_api.json)). Both check the shared vectors in [`vectors/checkin.json`](vectors/checkin.json): 3 valid posters (decode, re-encode byte for byte, text form), 47 invalid ones with the reason they must fail, 8 invalid texts, a poster with keys to skip, the rules for declarations and field identities, and under `tickets` 2 valid tickets, 22 invalid ones, 6 invalid texts and a ticket with keys to skip (built byte by byte from RFC 8949's rules, not by the codecs).

With a site server, players can register for a scheduled game beforehand (ADR-P4-11, phase 4 plan phase 16): the controller then knows them as **expected** check-ins before they arrive ([Registered players](#registered-players) below). Nothing else here changes, and a field without a site server loses nothing.

## The poster

The GM console prints the poster (*Check-in* tab, *Print the poster*): an A4 page with a QR code, the field's name, three steps in European Portuguese and English, and the short form of the field CA's fingerprint so staff can compare it with the console. It is **per field**, printed once, and leads to whichever games are open for check-in; the GM may pin it to one game.

The QR code holds a text:

```
atalaia:checkin:<base64url without padding of: version (1 byte) | body (CBOR map)>
```

| Key | Field | Type | Required | Values |
| --- | --- | --- | --- | --- |
| 1 | `field_id` | text | yes | the field's id, as in chrono records: 1-64 of `A-Za-z0-9._:-` |
| 2 | `field_name` | text | yes | 1-48 characters (not bytes), no control characters, no spaces at the ends |
| 3 | `urls` | array of text | yes | 1-3 different base addresses of the controller's API, raced by the app (the first at once, the next after about 250 ms or when the one before fails; the first that completes TLS with the field CA wins), best first: `https://host[:port]`, a DNS name, an IPv4 address or an IPv6 address in brackets, nothing after it, at most 64 bytes each |
| 4 | `ca_sha256` | bytes | yes | 32 bytes: SHA-256 of the field CA's DER certificate (the join payload's key 13 holds the same value) |
| 5 | `wifi_ssid` | text | no | 1-32 bytes of UTF-8 without NUL: the field network's name, shown as "join this Wi-Fi" |
| 6 | `game_id` | uint | no | 1-65534: this game only (a pinned poster) |

Version 1. The version byte and the body are at most 192 bytes. Encoders write the keys in this order, integers and lengths in their shortest form, and leave out an absent optional field. Decoders refuse a missing required field, a repeated key, a value of the wrong type or out of range, a `null` (an absent field is left out), trailing bytes, any key of 32 or more, a negative or text key, and skip keys 0 and 7-31, which are kept for later optional fields. The reasons in the vectors are `text` (the prefix or the base64url), `length`, `version` and `body`. Readers ignore spaces and line ends around the text.

Only `https://` addresses are allowed: the app trusts the field's CA for those addresses and nothing else.

**The poster carries no secret.** There is no join key, game key, token key or Wi-Fi password in it, and no MAC: a player's app holds no key that could check one, and anyone may photograph the poster. A field whose Wi-Fi has a password can print a standard Wi-Fi QR code beside it (`WIFI:T:WPA;S:<ssid>;P:<password>;;`, with `\ ; , : "` escaped by a backslash); the poster page asks for the password only to draw that code and keeps it nowhere.

### Trust: the CA, pinned per field on first use

On the first scan of a `field_id`, the app fetches `GET /api/v1/controller/ca` (no token; the CA certificate in PEM, also on the plain HTTP port) from the poster's addresses, checks the SHA-256 of its DER form against `ca_sha256`, and keeps the certificate for that field. From then on it talks to that field only over HTTPS, trusting that CA alone, and only for the poster's addresses; never through the phone's own trust store. A later poster for the same `field_id` with another fingerprint is refused with a warning that names both short forms (the first 8 bytes as `XXXX XXXX XXXX XXXX`); the player can accept it only by removing the field first. A forged poster can only fool a phone that never saw the real one, and a check-in asks for nothing worth stealing.

The controller makes the CA on first start (`controller/atalaia_controller/tls.py`): ECDSA P-256 (decision PE2), valid 10 years, and a server certificate for its names and addresses (`[api] tls_names` and the ones it finds), valid one year and made again when it has under 30 days left or the names change. `python -m atalaia_controller ca` prints the fingerprint. HTTPS is served on `[api] tls_port` (8443 by default) next to plain HTTP on `[api] port` (8080).

### The field's branding

The poster carries no branding, and nothing in this protocol changes for it. Once the CA is pinned, the app asks the poster's addresses for `GET /api/v1/field/branding` (no token; the field's id and name, a logo, a wallpaper and an accent colour, with an ETag) and keeps it per `field_id`; a game's teams carry their display names and crests in the game (`team_info`). The endpoints and limits are in [controller/README.md](../controller/README.md#field-and-team-branding) (decisions BR1-BR24).

## Who the player is

Playing never needs an account. For each field the app makes a **field identity** on its first check-in there: a `player_id` of `p-` and 12 characters of `a-z2-7` (lowercase base32), and a 32-byte random `player_secret`, sent as 43 characters of base64url without padding. The controller keeps the id and the SHA-256 of the secret. The same id comes back on every game day at that field; a known id with another secret is refused (409), so nobody can take over a known id. Two fields cannot link a player's ids. A player checked in by hand has an id made by the controller and no secret, so no app can claim it.

## Checking in

`GET /api/v1/checkin` (no token, rate-limited per address) answers:

```json
{"version": 1,
 "field": {"id": "campo-norte", "name": "Campo Norte", "operator": "Clube X"},
 "notice": {"version": 1, "pt": "...", "en": "..."},
 "settings": {"confirm": "auto", "federation": "off", "federation_label": "FPA",
              "max_replicas": 5, "chrono_valid_for": "day"},
 "limits": {"id": "portugal", "name": "Portugal", "status": "unverified", "classes": ["cqb", "dmr", "rifle", "sniper"]},
 "replica_types": ["aeg", "gbb", "hpa", "bolt_action", "dmr", "sniper", "pistol", "shotgun"],
 "games": [{"game_id": 4242, "name": "Domingo", "state": "ready", "teams": ["red", "blue"], "squads": 0}]}
```

`squads` is how many squads each team has in that game: 0 for a game with teams only (decision PE25). Squads, and the squad-leader role, exist only in games that define them; the controller refuses a squad or a squad leader in a game without squads, and a squad without a team.

No names are ever in it. The app shows the notice once per field and version, then the form.

`POST /api/v1/checkin` (no token; 10 a minute per address by default, at most `[checkin] max_players` per game):

```json
{"game_id": 4242, "player_id": "p-abcdefgh2345", "player_secret": "<43 characters>",
 "display_name": "Falcão", "federation_number": "12345", "team_preference": "red",
 "notice_version": 1, "replicas": [ <declarations> ]}
```

`federation_number`, `team_preference` and `replicas` are optional. A registered player's app adds `"registration_id"` (the site server's registration, a lowercase UUID) and `"ticket"` (the ticket secret, 43 characters of base64url without padding), always together ([Registered players](#registered-players)). Answers 201 (a new check-in) or 200 (the same identity again), with no caching:

```json
{"game_id": 4242, "player_id": "p-abcdefgh2345", "token": "apt1....", "exp": 1792339200,
 "status": "checked_in", "team": null, "team_id": 0, "squad": 0, "role": "player"}
```

Errors: 400 (a field out of its rules), 403 (check-in closed, the game full, a poster pinned to another game, or staff removed this check-in), 404 (no such game), 409 (a known id with another secret, or `notice_version` is not the current one: read the notice again), 429 (too many from this address).

- `display_name`: 1-32 characters, no control characters (a callsign or a first name; what the player wants).
- `federation_number`: 1-32 printable characters, **never verified automatically**. With `federation = "off"` it is dropped; with `"required"` the check-in is refused without one. Staff tick "card seen" (`federation_seen`).
- `team_preference`: one of the game's team names.

A self check-in only ever gives the role `player`. With `[checkin] confirm = "staff"` the status stays `pending` until a marshal or the GM confirms it; a pending player already has a token and can declare replicas. When a check-in becomes `checked_in`, the controller logs **`player.checkin` (15)** as its own node with `{"player": "<player_id>"}` and the envelope's team once assigned: never the name, never again for a token refresh.

The **player token** is `protocol/player-token.md`'s, keyed with the controller's own per-game token key (decision B8): 32 random bytes made when the game's first token is issued, kept in the controller's SQLite file (mode 0600, and its WAL and shared-memory files too) and never sent anywhere, so tokens survive a restart. `exp` is the game's planned end plus 2 hours (when it has started with a length) or the end of the field's local day, whichever comes first, and at least a minute away. `POST /api/v1/checkin/token` with the token gives a new one.

**The row is the authority.** On every request the controller checks a token against the player's check-in: a `left` or `removed` check-in refuses it (401); the team and squad are the row's; the role is the token's only if the row still says it, otherwise the lesser of the two (spectator < player < squad leader = VIP < marshal < GM; squad leader against VIP gives player). When the GM changes a player's team, squad or role, that player's stream connections get a `checkin` message with `"assignment": true` and are closed with code 4409: the app fetches a new token and reconnects.

### The player's own check-in

| Method | Path | |
| --- | --- | --- |
| GET | `/api/v1/checkin/me` | The check-in with its fields and the declaration with states; `stale_token` when the token no longer matches the row; for the role `marshal`, also `marshal` (below) |
| PUT | `/api/v1/checkin/me/replicas` | `{"replicas": [ <declarations> ]}` replaces the declaration |
| DELETE | `/api/v1/checkin/me` | Leave the game: status `left`, the name, federation number and team preference erased, pending declarations withdrawn |
| PUT | `/api/v1/checkin/me/marshal-key` | A marshal on the GM's list registers `{"public_key", "marshal_id"?}`, the Ed25519 key that signs their readings, for the id the list gave them (`marshal_id`, if sent, must be that one: 409; not on the list: 403) |
| POST | `/api/v1/positions` | Player positions (ADR-P3-6), not check-in data |

## Marshals: only from the GM's list

A marshal is someone on **the marshal list**, which only the GM edits (decisions MR-1 to MR-14); the app never has a marshal type an id. Everything the controller already checked still holds (the GM token for `POST /api/v1/marshals`, the `marshal` role for the key, a registered key for every reading); the list adds who may register one and tells the app before it acts.

- **Adding** (`POST /api/v1/marshals`): `player_id` is a player who has checked in at this field (404 otherwise) and gets the `marshal` role in every check-in that still counts; `marshal_id` is the controller's (the lowest free `M-01`, `M-02`...) unless the GM gives one (`A-Z a-z 0-9 . _ : -`, 1 to 64); `name` is the player's own display name unless given. A player is on the list once (409 for a second id). With no `player_id` the entry waits (a name for a phone that comes later, bound with PATCH); `public_key` (the GM registering a key for them) is still accepted. Answer: `{marshal_id, name, player_id, public_key, key_registered, registered_at, created_at}` (`public_key` and `registered_at` null until a key is registered).
- **The app asks** (`GET /api/v1/checkin/me`): for a check-in with the role `marshal` the answer has `marshal`: `{"marshal_id", "name", "public_key", "valid_for_s"}`, or `null` when the player is not on the list (a role given by hand is not the list). `public_key` is the key the controller holds for the id (null before the app registered one); `valid_for_s` (86400) is how long the app may go on acting as this marshal offline after this answer (MR-4). The app takes its id and name from here, registers its key (`PUT .../me/marshal-key`) when `public_key` is not its own, and is a marshal only on a yes; a role other than `marshal`, or `marshal: null`, is a no, and what it had before is gone.
- **Taking off** (`DELETE /api/v1/marshals/{id}`) and **rebinding** (`PATCH` with another `player_id`): the id's key stops verifying at once (it moves to the key history, so what it signed before still verifies on the site server), the player is a `player` again and their token loses the staff rights on its next request. Readings the removed marshal's phone had not sent are refused (`reason: "marshal"`, or 403 for the token) and stay on the phone; the GM adding the same player again (the same id when it is free, the same key) lets them go.

## Declarations

One declared replica, as the app (or staff) sends it:

| Field | Required | Value |
| --- | --- | --- |
| `declaration_id` | yes | a lowercase UUID, made by the app (or the console for a hand check-in) |
| `replica_id` | no | the field registry's id (ADR-P3-7) once a marshal has registered the replica; a lowercase UUID |
| `type` | yes | `aeg`, `gbb`, `hpa`, `bolt_action`, `dmr`, `sniper`, `pistol` or `shotgun` |
| `class` | yes | a class of the field's limit template (`GET /api/v1/checkin` lists them): 1-32 of `a-z0-9_` |
| `make_model` | no | 1-64 characters, no control characters |

Nothing else: the `state` and `reading_id` are the controller's. At most `max_replicas` per player and game (1-20, default 5), each `declaration_id` and each `replica_id` once. A declaration id another player or game holds is refused (409).

The controller keeps a **state** for each: `pending` (not chronographed yet), `passed`, `refused` or `withdrawn`, and the `reading_id` that decided it. Replacing the declaration withdraws the pending ones left out. A player cannot withdraw or change a replica once it is `passed` or `refused` (409); staff can (`PATCH .../checkins/{player}` with `replicas`).

## The "replicas to chrono" list

- A declaration is `pending` until a check-in or retest **series** for its replica arrives. A series that passes makes it `passed`, one that fails `refused`; a later passing retest makes it `passed` again. The failed records stay: readings are append-only.
- A reading is matched to the declarations of its `player_id` with its `replica_id`, in the game its `game_id` names (the live game when it has none).
- With `chrono_valid_for = "day"` (the default), a replica whose latest check-in series at this field passed earlier the same field-local day is `passed` at once when it is declared again (in a later game). With `"game"`, every game asks again. A replica refused earlier that day is shown to staff with `refused_today`.
- Only readings verified with a registered marshal's key change the list. Spot checks never change it.

`POST /api/v1/chrono/readings` (a marshal's player token, or the GM token): one series per request.

```json
{"readings": [ <signed records, protocol/chrono-record.md> ],
 "declaration_id": "<optional: link this declaration, which had no replica_id yet>",
 "replica": {<optional: the registry record of the readings' replica, ADR-P3-7>}}
```

Every record is checked (`chrono.py`, the shared vectors) and verified with the key registered for its `marshal_id`, and must be for this field (`field_id`); otherwise nothing at all is stored and the answer is 422 with each record's reason: `format`, `unsigned`, `signature`, `marshal` (no key registered for that id) or `field`. All the records of one request have the same replica, player and type. A request whose readings are all stored already changes nothing (`"duplicate": true`); one that mixes stored and new readings is refused (409).

The series is judged by its highest energy against the class of the matching declaration (else of the registry's replica) in the field's limit template (`[checkin] limit_template`, the app's `limit_templates/`): a check-in or retest passes at or below the limit (decision B11); a spot check fails above the limit and warns above the replica's last passing check-in plus 5%. Without a known class the readings are stored and nothing is judged (`"unjudged"`). The answer:

```json
{"series_id": "...", "outcome": "pass", "stored": 3, "highest_energy_j": 1.103, "limit_j": 1.14,
 "class": "rifle", "duplicate": false, "changed": ["<declaration ids>"], "declarations": [...]}
```

Events: **`chrono.checkin` (35)** once per passing check-in or retest series, with its highest reading; a refusal adds no event (it is in the list, which only staff see). Spot checks log **`chrono.spotcheck` (36)**, and **`chrono.violation` (17)** on WARN or FAIL. Events carry ids, never names.

## Registered players

A site server (phase 4, plan phase 16; ADR-P4-11 and decisions S16-*) takes registrations for its field's scheduled games. Each registration has the player's id at the field, a display name for that game, a team preference, the federation number when the game asks for one, pre-declared replicas (declarations as above, each with its `declaration_id`) and a **ticket**: 32 random bytes, shown once to the player; the site server keeps only its SHA-256.

**The roster.** When the GM makes a game from a scheduled game (`POST /api/v1/schedule/{scheduled_game_id}/game`), the controller's sync client pulls that game's roster (`GET /api/v1/sync/roster`, [sync.md](sync.md)) at every cycle **until the game starts**. Each registration becomes a check-in with status **`expected`**, its name, federation number and team preference, the ticket's SHA-256, and its declarations already `pending` in the "replicas to chrono" list, so marshals can prepare before the gate opens. A newer roster changes an expected check-in, and one whose registration was cancelled goes; anyone already at the field stays as the controller has them. A declaration this field's check-in would refuse (a class of another limit template, more than `max_replicas`, a declaration id another player holds) is dropped. After the start, nothing from the site server changes the game: staff changes on the day win.

**Arriving.** An expected check-in becomes `checked_in` (or `pending` with `confirm = "staff"`) in one of three ways:

- the app checks in with the registration's `registration_id` and `ticket` (`POST /api/v1/checkin`): the ticket's SHA-256 must be the roster's (403 otherwise), and the check-in's `player_id` the registration's (409 otherwise). A player id the roster brought and this controller never saw (the site server made it) is refused without the ticket (403); once the phone has checked in, its secret is the identity as for anyone;
- a marshal scans the printed ticket (`POST /api/v1/games/{id}/checkins/ticket` with `{"ticket": "atalaia:ticket:..."}`): the registration must be in this game's roster and the ticket its own;
- staff tick the player by name (`PATCH .../checkins/{player}` with `status: "checked_in"`).

Without a roster (no internet, or no pull yet) a registered player is a walk-in; the app's `registration_id` and the ticket's SHA-256 are kept with the check-in, so the site server can match them when the controller reports back.

**What goes back.** After the game (`POST /api/v1/sync/checkins`, [sync.md](sync.md)): per registration its outcome (`checked_in`: the player came, or `no_show`), its declarations' final states and deciding `reading_id`s, and the walk-ins as a count. Never a name or a federation number. A registration known only from the app carries its ticket's SHA-256, which the site server compares with its own.

**Claims of a phone's id.** A player whose phone checked in at this field without an account can link that id to their account on the site server: the site server keeps the SHA-256 of the phone's secret in a claim, and the controller, which compares it with the hash it kept at the phone's first check-in, answers `confirmed`, `refused` (another secret, or an id checked in by hand) or `unknown` (`GET`/`POST /api/v1/sync/claims`). The controller's own hashes never leave it.

### The ticket

The printed ticket is a QR code of a text, the poster's sibling:

```
atalaia:ticket:<base64url without padding of: version (1 byte) | body (CBOR map)>
```

| Key | Field | Type | Values |
| --- | --- | --- | --- |
| 1 | `registration_id` | text | the registration, a lowercase UUID |
| 2 | `player_id` | text | the player's id at the field, `p-` and 12 of `a-z2-7` |
| 3 | `secret` | bytes | the 32-byte ticket secret |

Version 1, at most 128 bytes with the version byte. All three keys are required. The decoding rules are the poster's: a missing key, a repeated key, a wrong type, a `null`, trailing bytes, a key of 32 or more, a negative or text key are refused; keys 0 and 4-31 are skipped. The reasons in the vectors are `text`, `length`, `version` and `body`. The ticket only matches an arrival to a registration, offline: it opens nothing on the radio and is no game credential.

## Staff

| Method | Path | Who | |
| --- | --- | --- | --- |
| GET | `/api/v1/games/{id}/checkins` | GM token, marshal or gm player token | The check-ins with names, counts, settings, whether check-in is open; each row's `registration_id` and `registered`, and `registrations: {expected, arrived, walkins}` |
| POST | `/api/v1/games/{id}/checkins` | the same | A hand check-in `{"display_name", "federation_number"?, "team_preference"?, "replicas"?}`: checked in at once; the answer has the controller's new `player_id` |
| PATCH | `/api/v1/games/{id}/checkins/{player}` | GM token: `team`, `squad`, `role`; staff: `status: "checked_in"` (confirm), `federation_seen`, `replicas` | |
| DELETE | `/api/v1/games/{id}/checkins/{player}` | GM token | Remove: status `removed`, personal fields erased, the player's tokens refused |
| POST | `/api/v1/games/{id}/checkins/ticket` | the same | `{"ticket": "atalaia:ticket:..."}`: a registered player's printed ticket, scanned; checked in at once |
| GET | `/api/v1/games/{id}/chrono-list` | GM token, marshal or gm player token | Players with declarations, pending first in check-in order; counts |
| GET | `/api/v1/games/{id}/checkins.csv` | GM token | The list as CSV for the field's own records (cells that a spreadsheet would read as a formula start with `'`) |
| POST | `/api/v1/games/{id}/checkin/open` · `/close` | GM token | Check-in is open from a game's creation until it ends, unless closed |
| GET / PUT | `/api/v1/checkin/settings` | GM token | `confirm`, `federation`, `federation_label`, `max_replicas`, `max_players`, `chrono_valid_for` |
| GET / PUT | `/api/v1/checkin/poster` | GM token | The poster's fields and text, `ca_short`, and why it cannot be made (`problem` in English, `problem_code` for the console: `https_off`, `no_address`, `too_long`, `invalid`); PUT `urls`, `wifi_ssid`, `game_id`, `field_name` |
| GET / POST | `/api/v1/marshals` | GM token | The marshal list / add to it `{"player_id"?, "name"?, "marshal_id"?, "public_key"?}` (below) |
| PATCH / DELETE | `/api/v1/marshals/{id}` | GM token | Rename (`name`) or rebind (`player_id`, null unbinds) / take a marshal off the list |
| GET / DELETE | `/api/v1/players/{player}/chrono` | GM token or the player's token | Their readings / erase them |
| DELETE | `/api/v1/players/{player}` | GM token | Erase the field identity, check-ins and declarations (`?chrono=true`: the readings too) |

`POST /api/v1/games/{id}/start` answers with `pending_declarations`: a warning, never a block; the console asks before it starts.

## The stream

On `WS /api/v1/stream` a player token may connect too. Every message is routed by who is connected:

- `checkin` (one check-in changed, names included) and `chrono_list` (a player's declarations and the counts) go to the GM token and to marshal and gm player tokens of that game, and to the player whose row it is; never to the read token or other players.
- `player_position` goes only to those who may see that position (ADR-P3-6); `positions` refreshes the visible ones after a visibility change.
- A player's connection gets the game's public messages (`game`, `score`, `node`, `event`, `field_state`), its own `checkin` and `chrono_list`, and no radio or controller internals; its `hello` holds its own check-in (`me`) and the positions it may see.
- Every `hello` holds the live game's latest 100 events (`events`, oldest first), so an app that connects mid-game shows what already happened.

## Personal data

Kept: the field identity (id, hash of the secret), per check-in the display name, the federation number if given, the team preference, the time and the state, the declarations, and for a registered player the registration's id and its ticket's SHA-256. Nothing else. Names and federation numbers never reach events, MQTT, the radio, the controller's log lines or the read token's views (the tests check all four). The display name, federation number, team preference and declarations are erased `[checkin] retention_days` (30) days after the game; a field identity not seen for 365 days is deleted; chrono readings older than 365 days are deleted (decision B12). The default privacy notice is `controller/templates/checkin-notice-pt.md` and `-en.md` (`{operator}` and `{retention_days}` are filled in), for the legal review of decision P4-6.

## Offline

Nothing needs the internet. When the controller is out of reach, the app keeps its token and declaration and tries again; the marshal's app keeps signing readings for as long as the controller's last yes holds (`valid_for_s`, two hours; no yes yet, or an old one, and it records nothing: MR-4) and uploads them later. A standby controller that takes over has none of this (it never travels on the radio) and another token key: the apps check in again with their field identities and resend, and the marshals resend their readings (decision F9).
