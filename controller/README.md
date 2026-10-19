# Field controller

Runs on a Raspberry Pi (or any Linux machine) next to the field. It:

- keeps the official game: creates games from mode packages and presets, starts, pauses, resumes and ends them, merges every box's scores and keeps the event log,
- talks to the boxes over LoRa through a **USB radio modem** (a second Heltec V4.3 running the modem firmware),
- sends the TIME beacons that keep every box's clock in step and double as its heartbeat,
- takes part in **controller failover** (the CLAIM election, ADR-P2-8),
- runs a mode's `field.lua`, the script for logic that spans several boxes,
- serves the REST and WebSocket API, the GM console and a scoreboard page, and publishes to MQTT.

Licence: AGPL-3.0-or-later. Running a modified controller for other people means sharing your changes.

Status: phase 2, plan phases D and E; phase 3, plan phase E (field check-in, player tokens, chrono readings, player positions, Android props on Wi-Fi, HTTPS with the field's own CA). Built and tested in Docker against the modem's real C code, the Field Box's real game and radio code (the host box), a real Mosquitto broker and, for the GM console, headless Chromium; not yet run on a Raspberry Pi with a real modem board and real boxes (that is plan phase F, when the boards arrive).

## How it is built

```
 boxes ))) LoRa ((( modem board ==USB== atalaia_controller ── REST, WebSocket ── GM console, apps
                    radio, AES-CCM,     │                └─ MQTT (Mosquitto) ── scoreboards
                    dedupe, duty cycle  └─ SQLite (games, presets, modes, nodes, event log)
```

| Module | What it does |
| --- | --- |
| `atalaia_controller/radio_modem.py` | The serial link: frames, a ping every 5 s, reconnect after 3 missed pings, `radio.down` after 3 failed reconnects |
| `atalaia_controller/modem_framing.py` | The frames of [protocol/usb-modem.md](../protocol/usb-modem.md) |
| `atalaia_controller/engine.py` | Games, the radio side, `field.lua`, restart recovery, the field's radio channel |
| `atalaia_controller/channels.py` | The candidate channels, the noise scan with the modem, its ranking and suggestion, the random pick |
| `atalaia_controller/store.py` | SQLite: the events table's UNIQUE key makes replays and flood copies harmless |
| `atalaia_controller/api.py`, `ws.py` | REST and WebSocket API v1 |
| `atalaia_controller/mqtt.py` | MQTT topics of spec section 11 |
| `atalaia_controller/tls.py` | The field's own CA and the controller's HTTPS certificate (ADR-P3-9) |
| `atalaia_controller/checkin.py`, `checkin_poster.py` | Field check-in, player tokens, declarations, the "replicas to chrono" list, signed readings ([protocol/checkin.md](../protocol/checkin.md)) |
| `atalaia_controller/positions.py` | Player positions and who may see them (ADR-P3-6) |
| `atalaia_controller/prop_link.py` | Android props on the field's Wi-Fi ([protocol/prop-link.md](../protocol/prop-link.md)) |
| `atalaia_controller/modes.py` | Built-in and uploaded mode packages, checked in the core before they are stored |
| `console/src/` | The GM console and the scoreboard page (static files) |

The join payloads come from the simulator's `atalaia_sim/join.py`, the Python side of [protocol/join.md](../protocol/join.md).

The radio side is not written twice: the TIME beacons, ACKs, score merge, event decoding and CLAIM election are the simulator's `FieldController` and `election` modules (`simulator/atalaia_sim/`), which the simulator tests over its radio model, failover included. The controller sends their packets through the modem instead of the simulated radio. Scripts run in the C core through the simulator's ctypes bindings.

## Running it

On a Raspberry Pi OS or Ubuntu machine:

```sh
sudo apt install python3-fastapi python3-uvicorn python3-websockets python3-paho-mqtt \
     python3-serial python3-yaml python3-cryptography libmbedtls-dev mosquitto cmake build-essential
cmake -S core -B build -DATALAIA_SHARED=ON && cmake --build build   # the core, for field.lua
cp controller/controller.example.toml controller.toml                 # then edit it
cd controller
ATALAIA_CORE_LIB=../build/libatalaia_core.so python3 -m atalaia_controller run --config ../controller.toml
python3 -m atalaia_controller tokens --config ../controller.toml     # the GM and read tokens
python3 -m atalaia_controller join-key --config ../controller.toml   # the field join key
```

Flash the modem board with the modem firmware first (`python tools/docker_fw.py modem`, then the `esptool` command it prints, or `idf.py -B build-modem flash`). [`deploy/`](deploy/) has a systemd unit and a Mosquitto configuration with users and topic permissions.

Without a modem (`[modem] port = ""`) the controller still runs: games can be created and the API works, but nothing reaches the boxes.

Settings come from a TOML file and `ATALAIA_<SECTION>_<KEY>` environment variables; see [controller.example.toml](controller.example.toml).

## The field's radio channel

All of a game's traffic uses one shared LoRa channel (RFC 0001 Amendments 1 and 3). The default, and the recommendation, is **869.525 MHz**: the centre of 869.4-869.65 MHz, the only part of the European 868 MHz band where a device may transmit up to 10% of the time at up to 500 mW ERP. Elsewhere in 868-870 MHz the rules allow 1% of the time (0.1% on 868.7-869.2 MHz) at 25 mW: about a tenth of the airtime and much less range. 868.1, 868.3 and 868.5 MHz are LoRaWAN's default channels, which every LoRaWAN device in Europe uses, so they are often busy. The recommended channel is shared too: LoRaWAN gateways use 869.525 MHz for some downlinks, and Meshtastic's European default is the same frequency. The game's packets are encrypted and use their own sync word, so nobody's traffic is mistaken for anyone else's, but everyone nearby shares the airtime. (Figures and sources: ERC Recommendation 70-03 Annex 1, ETSI EN 300 220-2, LoRaWAN Regional Parameters RP002-1.0.4; RFC 0001 Amendment 3.)

The channel is a **field setting**, chosen in the GM console under *Definições / Settings* (or the API below) while no game is live:

- **keep 869.525 MHz** (recommended);
- **find a quiet channel**: the controller asks the USB modem to listen to each candidate channel for an equal share of `[radio] scan_dwell_s` (60 s by default, at most 10 s per channel), without transmitting (the modem's MEASURE command, [protocol/usb-modem.md](../protocol/usb-modem.md)), and lists them quietest first with each one's power and duty-cycle limits. It suggests the quietest 500 mW channel if its 90th-percentile noise is at or below `[radio] quiet_threshold_dbm` (-105 dBm by default) and little LoRa activity was detected on it, otherwise the quietest channel of all;
- **random channel**: one of the candidates drawn at random; it is usually a 1%, 25 mW channel (8 of the 11), since only 869.475, 869.525 and 869.575 MHz give 10% and 500 mW;
- **pick one from the list** (the 0.1% channels are listed with a warning, but never scanned, drawn or suggested).

A scan or a random draw only suggests: nothing changes until the GM accepts one. The controller keeps the choice in its store (it survives a restart; `[radio] channel_hz` is only the default until the first choice), tunes the modem to it (SET_CHANNEL), and every new game takes it: the modem gets it with the game (CONFIGURE) and the boxes in their join payloads. A game keeps its channel until it ends, so the channel and the scan are locked while a game exists. Until the channel has been chosen once, the console's game tab shows a reminder. Without a modem, or with a modem that has no radio chip, the scan is unavailable (the console says why) and the channel stays as it is.

Every channel must fit inside one EU868 sub-band as a whole: centre ± 62.5 kHz (the game's 125 kHz LoRa channel). 869.40 MHz, at the sub-band's lower edge, is refused because its channel starts at 869.3375 MHz; the legal centres in 869.4-869.65 MHz are 869.4625-869.5875 MHz. The config, the API, the modem and the boxes all apply this rule, and the boxes and the modem take their duty-cycle budget and TX power from the chosen channel's sub-band. The candidates, the thresholds and the other choices are decisions CH1-CH13 in `docs/review/decisions-to-review.md`. The noise readings have not been compared with a real SX1262 yet (plan phase F); calibrate the quiet threshold at bring-up.

## Joining boxes and a standby controller

A box joins a game with a **join payload** ([protocol/join.md](../protocol/join.md)): the game's id and key, the box's node id and role, the teams, the channel and the relay clamp, signed with the **field join key**. Every box of the field gets that key once: on its setup page (the optional "field join key"), or with `@joinkey <64 hex digits>` on its serial console. `join-key` above prints it; `[join] key` in the TOML sets it, so two controllers can share one field.

In the GM console's *Join* tab (or `POST /api/v1/join`), pick the role: the controller gives the box the next free node id, records its role, and shows the payload as a QR code, as text (`atalaia:join:...`) and as the bytes to write on an NTAG215/216 card. A box reads the card with its NFC reader, or takes the text on its serial console (`@join atalaia:join:...`). The payload holds the game key: show it only to the people setting up the field.

A second controller (another Pi with its own modem) stands by for the game: ask the primary for a payload of kind *standby controller*, and paste its text into the standby's console (*Join* tab) or `POST /api/v1/controller/join`. The standby then hears the game, logs its events and follows its clock and scores without acknowledging anything; if the primary fails, *Promote* on the standby makes it take over (manual failover, ADR-P2-8). It leaves the game when the TIME beacons say it ended.

A mode's `field.lua` (Hold-All Domination, Last Stand) runs in the core on the controller from the game's start. Its `score.add()` points are the controller's own counters: they are merged into the totals (by maximum, like a box's) under one key per run of the script, and kept with the game, so they survive a controller restart, after which the script runs again and its new points add to the earlier ones. A standby controller that is promoted starts its own run; the points of the old controller's runs are not known to it (they never travel on the radio; decision K5 in `docs/review/decisions-to-review.md`). A `game.win()` or `game.finish()` from the script ends the game with that winner on the next tick.

The game key never touches the Pi's disk by default (ADR-P2-4): if the controller restarts during a game, that game can only be ended. With `persist_game_key = true` the key is kept in the SQLite file (mode 0600) and the game continues after a restart, from its last saved game time, scores and adjustments.

## HTTPS and the field CA

On first start the controller makes the field's own certificate authority and a server certificate for its names and addresses in `tls/` next to the database (`[api] tls_dir`), keys with mode 0600, and serves the same API with HTTPS on `[api] tls_port` (8443) next to plain HTTP on `[api] port` (8080). `python3 -m atalaia_controller ca` prints the CA's fingerprint, which the check-in poster and the join payloads for Android props carry; phones fetch the certificate from `GET /api/v1/controller/ca` (no token, both ports), check it and trust only it for this field. Put the names and addresses phones use in `[api] tls_names` (the controller adds `localhost`, its host name, `name.local` and the addresses it finds; the server certificate is made again when the list changes or it has under 30 days left). The CA itself is never replaced on its own: deleting the folder makes a new one, and every player then has to remove the field in the app. The CA is ECDSA P-256 so that browsers accept it too (decision PE2). The GM console and the scoreboard still work on plain HTTP.

## Field check-in

Players check in at the field with the app ([protocol/checkin.md](../protocol/checkin.md), ADR-P3-13). In the GM console's *Check-in* tab, *Print the poster* opens an A4 page with the field's QR code: print it once and put it up in the check-in area. The poster carries no secret: the field's id and name, the controller's https addresses (`[checkin] urls`, else from `tls_names` and the host), the CA's fingerprint and optionally the Wi-Fi network's name (`[checkin] wifi_ssid`; the poster page can draw a Wi-Fi code from a password typed there, which is never stored).

A player who scans it checks in with a display name (and the federation number if `[checkin] federation` asks for it; never verified automatically: staff tick "card seen"), and gets a **player token** keyed with the game's own token key, made by this controller and kept only in its SQLite file. The token's role, team and squad are checked against the player's check-in on every request, so the GM's changes and removals take effect at once. Check-in is open from a game's creation until it ends (*Close check-in* stops it); with `[checkin] confirm = "staff"` check-ins wait for a marshal or the GM to confirm them. The controller logs `player.checkin` with the player's id, never the name. A team always exists; squads, sub-groups inside a team, only in a game created with `squads` (decision PE25): there the GM gives a squad (team › squad) and the squad-leader role, elsewhere both are refused.

Players declare the replicas they will use; marshals see the **replicas to chrono** list in their app and in the console, and their phones send each signed series of readings (`POST /api/v1/chrono/readings`): the controller verifies them with the marshal's registered Ed25519 key, judges the series against the class limit of `[checkin] limit_template` (one of `app/lib/chrono/limit_templates/`, unverified research figures: decision P3-5) and marks the replica passed or refused. A pass counts for the rest of the field's day (`chrono_valid_for`). A marshal is a checked-in person to whom the GM gave the marshal role; the marshal's app then registers its key itself, or the GM registers one with `POST /api/v1/marshals`.

Personal data stays on the controller: names and federation numbers are shown to staff (the GM token, marshals) only, never in events, MQTT, logs or the read token's views, and are erased `[checkin] retention_days` (30) days after the game; a field identity unused for a year is deleted. The default privacy notice is `templates/checkin-notice-pt.md` and `-en.md` (`[checkin] notice_pt`, `notice_en`; raise `notice_version` when it changes). Everything works without internet.

## Player positions

A checked-in player may share their position during a running game (`POST /api/v1/positions`, up to 5 reports). The controller keeps the latest per player for that game only and deletes them when it ends; it sends a position only to those who may see it (ADR-P3-6): a player sees their own (and their squad's with the game parameter `squad_visible`), a squad leader their squad, a VIP their team, marshals and the GM everyone, the read token nobody. A mode's `visibility.granted` event (team, `see_team`, `duration_s`) lets a team see another for a while; the controller logs `visibility.expired` when the time is up. Positions never go on the radio or MQTT.

## Android props on Wi-Fi

An Android phone running a prop that joined with a join payload links to the controller over the field's Wi-Fi ([protocol/prop-link.md](../protocol/prop-link.md)): `WS /api/v1/prop`, an HMAC proof of the game key, then its HELLO, STATE and events as JSON, which the controller encodes with the radio's codecs and hands to the same FieldController as a box's packets. TIME beacons and commands reach the linked props too; without a modem, commands reach the Wi-Fi props and are reported as sent. The join payload for a box carries the CA's fingerprint and the https addresses (keys 13 and 14) when HTTPS is on; boxes skip them.

## REST API v1

Reading needs the read or GM token, changing anything the GM token: `Authorization: Bearer <token>` (the WebSocket also takes `?token=`). A player token (field check-in) reads what the read token reads about games, its own check-in and what its role allows; it cannot read modes, presets, the controller's or the radio's state.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/nodes` | Nodes of the live game (or `?game=`): owner, battery, RSSI, epoch, firmware, capabilities |
| GET / POST | `/api/v1/modes` | Installed modes and modifiers (`kind`), their parameters and translations (`i18n`) / upload `{"files": {"mode.yaml": ..., "node.lua": ..., "field.lua": ...}}` |
| GET / POST | `/api/v1/presets` | List / save `{"name", "mode_id", "params"}` |
| GET / POST | `/api/v1/games` | List / create `{"name", "mode_id" or "preset_id", "modifiers": [...], "teams", "squads", "params", "duration_ms", "assignments": {"7": "zone"}}`; a game with modifiers gets the mode id `main+modifier`; `squads` (0-16 per team, 0 by default) only for games whose teams split into squads (milsims, big games) |
| GET | `/api/v1/games/{id}` | One game |
| POST | `/api/v1/games/{id}/start` · `/pause` · `/resume` · `/end` | Lifecycle (`{"reason"}` for pause and end) |
| GET / POST | `/api/v1/games/{id}/score` | Totals / GM adjustment `{"team", "amount", "reason"}`, logged as `score.delta` |
| POST | `/api/v1/nodes/{id}/cmd` | `{"cmd": "message" \| "set_owner" \| "reset" \| "reboot" \| "mode", "params": {...}}`; node 65535 = every node. `mode` is a mode command (CMD opcode 8): `params.name` must be one of the game's manifests' `commands` for the node's role, such as a medic kit's `{"name": "refill"}` |
| GET | `/api/v1/games/{id}/log` | The merged event log, in game-time order (`?since_ms=`) |
| WS | `/api/v1/stream` | A snapshot (with the live game's latest 100 events), then every event, score, node update, game change and alert (`radio.down`, `tx.failed`, role changes), the field channel (`radio`) and scan progress (`radio_scan`); for staff also `checkin` and `chrono_list`; for a player token only the game's public messages, its own check-in and the positions it may see (code 4409: fetch a new token) |
| GET | `/api/v1/controller` | Role, term, radio state, modem identity and counters, the field channel and whether it was chosen |
| GET | `/api/v1/radio` | The field's channel with its sub-band limits, where it came from, the candidates, whether it is locked (a live game or a scan), why a scan is unavailable, the last scan |
| PUT | `/api/v1/radio/channel` | Set it `{"channel_hz", "source": "default" \| "scan" \| "random" \| "manual"}`; 409 while a game exists or a scan runs, 400 for a channel that does not fit in a sub-band |
| POST / GET / DELETE | `/api/v1/radio/scan` | Start "find a quiet channel" `{"dwell_s"}` (202; 503 without a modem with a radio) / its progress, results and suggestion / cancel it |
| POST | `/api/v1/radio/random` | A random candidate as `{"suggestion": ...}`; nothing changes |
| POST | `/api/v1/controller/promote` | Manual failover: stand for election |
| GET | `/api/v1/whoami` | Which token this is: `{"role": "gm" \| "read"}` (the console hides GM controls for `read`) |
| POST | `/api/v1/join` · `/api/v1/nodes/{id}/join` | A join payload ([protocol/join.md](../protocol/join.md)) for a box `{"role"}` or a standby controller `{"kind": "controller"}`, optional `node_id`: QR/serial text, NFC tag bytes. GM only, `Cache-Control: no-store` (it carries the game key) |
| POST | `/api/v1/controller/join` | This controller takes a game as standby: `{"text": "atalaia:join:..."}` |
| GET | `/api/v1/field` | Whether a field image is uploaded: `{"image": {"content_type", "bytes", "updated_at"} \| null}` |
| GET / PUT / DELETE | `/api/v1/field/image` | The field image of the console's field view: raw PNG, JPEG or WebP body, up to 4 MB |
| GET / PUT | `/api/v1/games/{id}/positions` · `/positions/{node}` | Where each node sits on the field image: `{"x", "y"}` as fractions 0-1 |
| GET | `/api/v1/controller/ca` | The field CA's certificate (PEM; header `X-Atalaia-CA-SHA256`), no token |
| GET / POST | `/api/v1/checkin` | No token, rate-limited: the field, the privacy notice, the settings, the limit classes, the open games / check in `{"game_id", "player_id", "player_secret", "display_name", "notice_version", "federation_number"?, "team_preference"?, "replicas"?}` → a player token |
| POST | `/api/v1/checkin/token` | A new player token (player token) |
| GET / DELETE | `/api/v1/checkin/me` | The player's own check-in and declaration / leave the game (personal fields erased) |
| PUT | `/api/v1/checkin/me/replicas` | `{"replicas": [...]}`: the declaration |
| PUT | `/api/v1/checkin/me/marshal-key` | A marshal registers `{"marshal_id", "name", "public_key"}` |
| GET / POST | `/api/v1/games/{id}/checkins` | Staff (GM token, marshal or gm player token): the list with names / a hand check-in |
| PATCH / DELETE | `/api/v1/games/{id}/checkins/{player}` | GM token: `team`, `squad`, `role`, removal; staff: confirm (`status: "checked_in"`), `federation_seen`, `replicas` |
| GET | `/api/v1/games/{id}/checkins.csv` | GM token: the list as CSV |
| GET | `/api/v1/games/{id}/chrono-list` | Staff: the "replicas to chrono" list, pending first, with counts |
| POST | `/api/v1/games/{id}/checkin/open` · `/close` | GM token |
| POST | `/api/v1/chrono/readings` | A marshal's (or the GM's) series of signed readings `{"readings": [...], "declaration_id"?, "replica"?}`; 422 with each record's reason, 409 for a partly stored series |
| GET / POST | `/api/v1/marshals` | GM token: marshals' public keys / register one |
| GET / PUT | `/api/v1/checkin/settings` | GM token: `confirm`, `federation`, `federation_label`, `max_replicas`, `max_players`, `chrono_valid_for` |
| GET / PUT | `/api/v1/checkin/poster` | GM token: the poster's text, fields and fingerprint / `urls`, `wifi_ssid`, `game_id`, `field_name` |
| GET / DELETE | `/api/v1/players/{player}/chrono` | GM token or the player's own token: their readings / erase them |
| DELETE | `/api/v1/players/{player}` | GM token: erase a field identity with its check-ins and declarations (`?chrono=true`: readings too) |
| GET / POST | `/api/v1/positions` | The positions the caller may see / a player's reports (player token) |
| WS | `/api/v1/prop` | An Android prop's Wi-Fi link |
| GET | `/healthz` | Liveness, no token |

FastAPI also serves the generated OpenAPI description at `/openapi.json` and `/docs`.

## GM console and scoreboard

The controller serves the GM console at `http://<controller>:8080/console/` (`/` redirects there) and a read-only scoreboard page at `/scoreboard#token=<read token>`: plain files from [`console/src/`](console/src/), no build step, with a strict Content-Security-Policy. The console asks for the GM or the read token; European Portuguese by default, English too. See [console/README.md](console/README.md). An example scoreboard that follows the game over MQTT is in [`examples/scoreboard/`](../examples/scoreboard/).

## MQTT

```
field/v1/{game}/events/{type}          every game event, JSON
field/v1/{game}/score                  totals per team (retained)
field/v1/{game}/nodes/{node}/state     owner, phase, game time, counters (retained)
field/v1/{game}/nodes/{node}/health    battery, RSSI, SNR, last seen (retained)
field/v1/{game}/cmd/{node}             {"cmd": "message", "params": {"text": "..."}} (GM only)
field/v1/{game}/cmd/all                the same, to every node
```

Who may publish commands is Mosquitto's job: [`deploy/mosquitto.conf`](deploy/mosquitto.conf) and [`deploy/atalaia.acl`](deploy/atalaia.acl) give the controller, a GM user and a read-only user. Retained topics are published again after the broker restarts; events published while the broker is down are not queued (they are in the log).

## Tests

`sh tools/check.sh` in the dev container runs everything, the controller included. From `cmd`, in the repository: `docker run --rm -v "%cd%:/src" atalaia-dev sh tools/check.sh` (the first `python tools/docker_sim.py test` builds the `atalaia-dev` image). The controller's tests (`controller/tests/`, unittest) need the core library (`ATALAIA_CORE_LIB`), the host modem (`ATALAIA_MODEM_HOST`, built from `firmware/esp32/test/modem_host/`) and `mosquitto`; with `ATALAIA_REQUIRE_ALL=1`, as in `check.sh` and CI, a missing one is an error, not a skip. They cover the framing against the C modem, AES-CCM in both directions, the watchdog and reconnect, the engine and restart recovery, every API endpoint, MQTT against a real broker, a `field.lua`, and the app served by uvicorn on a real port. They also check the GM console's files as served (`test_console.py`), run the example MQTT scoreboard against a private broker (`test_scoreboard_example.py`), choose the field's channel, scan for a quiet one over a recording modem and over the C host modem (simulated noise levels per channel, `test_channels.py`, `test_modem_host.py`), issue and refuse join payloads, make a second controller stand by, follow and take over a game over the air with two host modems (`test_join.py`), and play whole games with the host box (`ATALAIA_BOX_HOST`, built from `firmware/esp32/test/box_host/`): a join from the controller's payload, captures and scores over the radio, a battery pull, the end of the game, and a box heard only through another box's relay (`test_box_e2e.py`), Hold-All Domination scored by the controller from two boxes' captures, and the Codes modifier composed with Domination on a box, with a keypad code reaching the log. `test_mode_pack.py` runs the built-in `field.lua` scripts through the real engine: Hold-All scoring and its points across a restart, Last Stand ending the game with the attackers as winners, the script starting again after a takeover, and modifiers composed with a main mode.

The phase 3 tests (`test_checkin.py`, `test_chrono_list.py`, `test_checkin_poster.py`, `test_positions.py`, `test_prop_link.py`, `test_tls.py`) run the whole controller from `main.build()` without a radio: the poster codec against `protocol/vectors/checkin.json`, check-in and its rules, player tokens and the role re-check, the role-filtered stream, the "replicas to chrono" list with readings signed in the test and the shared chrono vectors, the retention purge, the privacy rules (no names in events, MQTT, logs or read views), the visibility table, an Android prop's Wi-Fi link, and a real TLS connection that trusts only the field CA.

The console's browser tests (headless Chromium, `controller/console/tests/`) need a browser, so they run separately: `python tools/docker_console.py`, and CI's `console` job.
