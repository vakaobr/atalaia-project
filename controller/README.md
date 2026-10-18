# Field controller

Runs on a Raspberry Pi (or any Linux machine) next to the field. It:

- keeps the official game: creates games from mode packages and presets, starts, pauses, resumes and ends them, merges every box's scores and keeps the event log,
- talks to the boxes over LoRa through a **USB radio modem** (a second Heltec V4.3 running the modem firmware),
- sends the TIME beacons that keep every box's clock in step and double as its heartbeat,
- takes part in **controller failover** (the CLAIM election, ADR-P2-8),
- runs a mode's `field.lua`, the script for logic that spans several boxes,
- serves the REST and WebSocket API (the GM console arrives in plan phase E) and publishes to MQTT.

Licence: AGPL-3.0-or-later. Running a modified controller for other people means sharing your changes.

Status: phase 2, plan phase D. Built and tested in Docker against the modem's real C code and a real Mosquitto broker; not yet run on a Raspberry Pi with a real modem board (that is plan phase F, when the boards arrive). The GM console, the NFC and QR join flow and the example scoreboard come in plan phase E.

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
```

Flash the modem board with the modem firmware first (`python tools/docker_fw.py modem`, then the `esptool` command it prints, or `idf.py -B build-modem flash`). [`deploy/`](deploy/) has a systemd unit and a Mosquitto configuration with users and topic permissions.

Without a modem (`[modem] port = ""`) the controller still runs: games can be created and the API works, but nothing reaches the boxes.

Settings come from a TOML file and `ATALAIA_<SECTION>_<KEY>` environment variables; see [controller.example.toml](controller.example.toml).

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
| GET | `/healthz` | Liveness, no token |

FastAPI also serves the generated OpenAPI description at `/openapi.json` and `/docs`.

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

`sh tools/check.sh` in the dev container runs everything, the controller included. From `cmd`, in the repository: `docker run --rm -v "%cd%:/src" atalaia-dev sh tools/check.sh` (the first `python tools/docker_sim.py test` builds the `atalaia-dev` image). The controller's tests (`controller/tests/`, unittest) need the core library (`ATALAIA_CORE_LIB`), the host modem (`ATALAIA_MODEM_HOST`, built from `firmware/esp32/test/modem_host/`) and `mosquitto`; with `ATALAIA_REQUIRE_ALL=1`, as in `check.sh` and CI, a missing one is an error, not a skip. They cover the framing against the C modem, AES-CCM in both directions, the watchdog and reconnect, the engine and restart recovery, every API endpoint, MQTT against a real broker, a `field.lua`, and the app served by uvicorn on a real port.
