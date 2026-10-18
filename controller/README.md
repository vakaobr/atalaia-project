# Field controller

Runs on a Raspberry Pi (or any Linux machine) next to the field. It:

- keeps the official game: creates games from mode packages and presets, starts, pauses, resumes and ends them, merges every box's scores and keeps the event log,
- talks to the boxes over LoRa through a **USB radio modem** (a second Heltec V4.3 running the modem firmware),
- sends the TIME beacons that keep every box's clock in step and double as its heartbeat,
- takes part in **controller failover** (the CLAIM election, ADR-P2-8),
- runs a mode's `field.lua`, the script for logic that spans several boxes,
- serves the REST and WebSocket API, the GM console and a scoreboard page, and publishes to MQTT.

Licence: AGPL-3.0-or-later. Running a modified controller for other people means sharing your changes.

Status: phase 2, plan phases D and E. Built and tested in Docker against the modem's real C code, the Field Box's real game and radio code (the host box), a real Mosquitto broker and, for the GM console, headless Chromium; not yet run on a Raspberry Pi with a real modem board and real boxes (that is plan phase F, when the boards arrive).

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
| `atalaia_controller/engine.py` | Games, the radio side, `field.lua`, restart recovery |
| `atalaia_controller/store.py` | SQLite: the events table's UNIQUE key makes replays and flood copies harmless |
| `atalaia_controller/api.py`, `ws.py` | REST and WebSocket API v1 |
| `atalaia_controller/mqtt.py` | MQTT topics of spec section 11 |
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

## Joining boxes and a standby controller

A box joins a game with a **join payload** ([protocol/join.md](../protocol/join.md)): the game's id and key, the box's node id and role, the teams, the channel and the relay clamp, signed with the **field join key**. Every box of the field gets that key once: on its setup page (the optional "field join key"), or with `@joinkey <64 hex digits>` on its serial console. `join-key` above prints it; `[join] key` in the TOML sets it, so two controllers can share one field.

In the GM console's *Join* tab (or `POST /api/v1/join`), pick the role: the controller gives the box the next free node id, records its role, and shows the payload as a QR code, as text (`atalaia:join:...`) and as the bytes to write on an NTAG215/216 card. A box reads the card with its NFC reader, or takes the text on its serial console (`@join atalaia:join:...`). The payload holds the game key: show it only to the people setting up the field.

A second controller (another Pi with its own modem) stands by for the game: ask the primary for a payload of kind *standby controller*, and paste its text into the standby's console (*Join* tab) or `POST /api/v1/controller/join`. The standby then hears the game, logs its events and follows its clock and scores without acknowledging anything; if the primary fails, *Promote* on the standby makes it take over (manual failover, ADR-P2-8). It leaves the game when the TIME beacons say it ended.

The game key never touches the Pi's disk by default (ADR-P2-4): if the controller restarts during a game, that game can only be ended. With `persist_game_key = true` the key is kept in the SQLite file (mode 0600) and the game continues after a restart, from its last saved game time, scores and adjustments.

## REST API v1

Reading needs the read or GM token, changing anything the GM token: `Authorization: Bearer <token>` (the WebSocket also takes `?token=`).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/nodes` | Nodes of the live game (or `?game=`): owner, battery, RSSI, epoch, firmware, capabilities |
| GET / POST | `/api/v1/modes` | Installed modes and their parameters / upload `{"files": {"mode.yaml": ..., "node.lua": ..., "field.lua": ...}}` |
| GET / POST | `/api/v1/presets` | List / save `{"name", "mode_id", "params"}` |
| GET / POST | `/api/v1/games` | List / create `{"name", "mode_id" or "preset_id", "teams", "params", "duration_ms", "assignments": {"7": "zone"}}` |
| GET | `/api/v1/games/{id}` | One game |
| POST | `/api/v1/games/{id}/start` · `/pause` · `/resume` · `/end` | Lifecycle (`{"reason"}` for pause and end) |
| GET / POST | `/api/v1/games/{id}/score` | Totals / GM adjustment `{"team", "amount", "reason"}`, logged as `score.delta` |
| POST | `/api/v1/nodes/{id}/cmd` | `{"cmd": "message" \| "set_owner" \| "reset" \| "reboot", "params": {...}}`; node 65535 = every node |
| GET | `/api/v1/games/{id}/log` | The merged event log, in game-time order (`?since_ms=`) |
| WS | `/api/v1/stream` | A snapshot, then every event, score, node update, game change and alert (`radio.down`, `tx.failed`, role changes) |
| GET | `/api/v1/controller` | Role, term, radio state, modem identity and counters |
| POST | `/api/v1/controller/promote` | Manual failover: stand for election |
| GET | `/api/v1/whoami` | Which token this is: `{"role": "gm" \| "read"}` (the console hides GM controls for `read`) |
| POST | `/api/v1/join` · `/api/v1/nodes/{id}/join` | A join payload ([protocol/join.md](../protocol/join.md)) for a box `{"role"}` or a standby controller `{"kind": "controller"}`, optional `node_id`: QR/serial text, NFC tag bytes. GM only, `Cache-Control: no-store` (it carries the game key) |
| POST | `/api/v1/controller/join` | This controller takes a game as standby: `{"text": "atalaia:join:..."}` |
| GET | `/api/v1/field` | Whether a field image is uploaded: `{"image": {"content_type", "bytes", "updated_at"} \| null}` |
| GET / PUT / DELETE | `/api/v1/field/image` | The field image of the console's field view: raw PNG, JPEG or WebP body, up to 4 MB |
| GET / PUT | `/api/v1/games/{id}/positions` · `/positions/{node}` | Where each node sits on the field image: `{"x", "y"}` as fractions 0-1 |
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

`sh tools/check.sh` in the dev container runs everything, the controller included. From `cmd`, in the repository: `docker run --rm -v "%cd%:/src" atalaia-dev sh tools/check.sh` (the first `python tools/docker_sim.py test` builds the `atalaia-dev` image). The controller's tests (`controller/tests/`, unittest) need the core library (`ATALAIA_CORE_LIB`), the host modem (`ATALAIA_MODEM_HOST`, built from `firmware/esp32/test/modem_host/`) and `mosquitto`; with `ATALAIA_REQUIRE_ALL=1`, as in `check.sh` and CI, a missing one is an error, not a skip. They cover the framing against the C modem, AES-CCM in both directions, the watchdog and reconnect, the engine and restart recovery, every API endpoint, MQTT against a real broker, a `field.lua`, and the app served by uvicorn on a real port. They also check the GM console's files as served (`test_console.py`), run the example MQTT scoreboard against a private broker (`test_scoreboard_example.py`), issue and refuse join payloads, make a second controller stand by, follow and take over a game over the air with two host modems (`test_join.py`), and play whole games with the host box (`ATALAIA_BOX_HOST`, built from `firmware/esp32/test/box_host/`): a join from the controller's payload, captures and scores over the radio, a battery pull, the end of the game, and a box heard only through another box's relay (`test_box_e2e.py`).

The console's browser tests (headless Chromium, `controller/console/tests/`) need a browser, so they run separately: `python tools/docker_console.py`, and CI's `console` job.
