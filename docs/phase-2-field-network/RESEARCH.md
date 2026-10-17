<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 2 -- Field Network: Research

## Summary

Phase 2 adds the LoRa field network, the Raspberry Pi field controller,
and the GM console web app. The gate is "5 boxes on a CQB site and an
outdoor field, with zero lost captures."

Phase 2 is the largest phase in the project because it turns standalone
boxes into a coordinated game system. It spans three new software
domains (radio protocol, controller daemon, web application) across two
programming languages (C on ESP32, a language TBD on Pi) and introduces
the first real-time distributed-systems challenges (time sync, log
merge, partition tolerance, controller failover).

**Risk:** High -- the radio protocol, AES-CCM security layer, time
synchronisation, controller failover, and multi-node state merge are all
new, non-trivial, and depend on each other. EU868 duty-cycle limits
constrain the protocol design tightly. Real LoRa hardware testing is
required to validate range, timing and airtime budget assumptions.
Each risk has a known mitigation documented in section 9.

---

## 1. Current codebase inventory relevant to Phase 2

### What exists (merged on main, in the worktree)

| Path | Contents | Phase 2 relevance |
|------|----------|--------------------|
| `core/include/atalaia/node.h` | Node runtime API: create, input, advance, score | Phase 2 extends this with radio send/receive; the API itself does not change |
| `core/include/atalaia/event.h` | Event struct: node, seq, t_ms, type, team, squad, prio | Directly maps to the LoRa EVENT message payload |
| `core/include/atalaia/score.h` | Grow-only per-node per-team counters with conflict-free merge | The controller uses `atalaia_score_merge` to reconcile partitions |
| `core/include/atalaia/codec.h` | CBOR event codec (encode/decode) | Used by the radio gateway to pack/unpack EVENT payloads |
| `core/src/script_api.c` | Lua API: `on`, `emit`, `every`, `after`, `state.node`, `score.*` | Phase 2 adds `state.field{}` and `field.*` (controller-only Lua API) |
| `protocol/schema/messages.yaml` | 8 message types: HELLO(1), EVENT(2), ACK(3), STATE(4), CMD(5), TIME(6), CONFIG(7), CLAIM(8) | Payload schemas for all 8 types must be defined |
| `protocol/schema/events.yaml` | 24 standard events with ids, priorities, CBOR keys | Used as-is; no new events needed for Phase 2 networking |
| `protocol/README.md` | Codec format, "Not defined yet" section | Explicitly lists what Phase 2 must define |
| `simulator/atalaia_sim/sim.py` | Simulation engine with virtual nodes | Needs multi-node delivery with simulated lossy radio |
| `simulator/atalaia_sim/live.py` | Interactive game with real-time clock | Needs cross-node event delivery |
| `modes/domination/`, `modes/bomb/` | Two working modes with tests | Used to validate the network end-to-end |
| `tools/protogen.py` | Schema codegen: C tables, Python tables, JSON Schema | Must be extended to generate message payload schemas |
| `controller/README.md` | Placeholder: "planned for phase 2" | Phase 2 fills this |
| `controller/console/README.md` | Stub: GM console description only | Phase 2 fills this |

### What Phase 1 is building (uncommitted, in the main checkout)

Phase 1 firmware files exist at `C:\Users\Anderson Leite\code\atalaia-project\firmware\esp32\main\`. The following interfaces are directly relevant to Phase 2:

| File | Interface | Phase 2 dependency |
|------|-----------|-------------------|
| `hal/hal.h` | `hal_t` struct aggregating button/keypad/led/display/nfc/audio/battery ops | Phase 2 adds `hal_radio_ops_t` here |
| `node_runner.h` | `node_runner_t`: owns `atalaia_node_t`, game timer, HAL pointer | Phase 2 extends with radio send/receive callbacks |
| `command_dispatch.h` | Routes core `command()` callbacks to hardware | No change needed; radio commands go through a different path |
| `game_timer.h` | Shell-owned countdown timer | Phase 2 syncs this to the controller's TIME beacons |
| `preset_store.h` | LittleFS-backed preset storage | Phase 2 adds CONFIG message to push presets over the air |
| `state_persist.h` | LittleFS-backed state save/resume | Used as-is; the radio layer sits above state persistence |
| `config_store.h` | NVS-backed node config (name, region, PIN) | Phase 2 reads radio region from here |
| `hal/stub/hal_stub.h` | Stub implementations for testing without hardware | Phase 2 adds `hal_radio_stub` |

### Placeholders that Phase 2 fills

| Path | Current state | Phase 2 deliverable |
|------|---------------|---------------------|
| `controller/` | README only | Full field controller: daemon, radio gateway, MQTT broker, REST API, store |
| `controller/console/` | Stub | GM console web app (PWA) |
| `firmware/thin-node/README.md` | "planned for phase 2" | Thin node / proxy tier support (stretch goal) |
| `protocol/schema/messages.yaml` | Types listed but payloads undefined | Full payload schemas for all 8 message types |
| `protocol/README.md` "Not defined yet" section | Listed as phase 2 work | Header bit layout, AES-CCM MIC, key exchange, message payloads |

---

## 2. Design spec requirements for Phase 2

### 2.1 LoRa protocol -- Skirmesh-RF (spec section 10)

**Packet format** (9 bytes header + up to 200 bytes payload + 8 bytes MIC):

| Field | Bytes | Purpose |
|-------|-------|---------|
| version_flags | 1 | Protocol version (3 bits), priority (2 bits), ACK requested (1 bit), 2 reserved |
| game_id | 2 | Ignore traffic from other games |
| source | 2 | Node short id within this game |
| seq | 2 | Per-node sequence number for dedupe and ACKs |
| hop_limit | 1 | Flood control, default 2 |
| type | 1 | Message type id (1-8) |
| payload | 0-200 | CBOR with integer keys |
| MIC | 8 | AES-CCM message integrity code with the per-game key |

Total maximum packet size: 9 + 200 + 8 = 217 bytes.

**Topology**: star centred on the controller, extended by TTL-limited flood (hop_limit default 2). Every node rebroadcasts a packet once if it has not seen its (source, seq) before. Specific nodes can be marked as dedicated repeaters.

**Airtime budget (EU868)**:
- Most channels: 1% duty cycle = 36 seconds of airtime per device per hour
- At SF7/125 kHz, a 30-byte packet takes ~60-70 ms => ~500 packets/hour
- At SF9/125 kHz, a 30-byte packet takes ~180 ms => ~180 packets/hour
- 869.4-869.65 MHz sub-band: 10% duty cycle (for controller TIME beacons and commands)

**Budget rules**:
- Send state changes, never clock ticks
- Hardware events stay local; only game events and periodic snapshots go on air
- Snapshots every 30-60 s by default, configurable per field profile
- Controller TIME beacons and commands use the 10% sub-band
- Scripts, assets and firmware never travel over LoRa

**Field profiles**:

| Profile | LoRa settings | Snapshot interval |
|---------|---------------|-------------------|
| CQB / indoor | SF7, or Wi-Fi only | 10 s |
| Small outdoor | SF7-SF9 | 30 s |
| Large outdoor | SF9-SF10, dedicated repeaters | 60 s |

### 2.2 Message types (spec section 10, messages.yaml)

All 8 message payloads must be defined as CBOR maps with integer keys:

| Type | Id | Purpose | Key payload fields (from spec) |
|------|----|---------|-------------------------------|
| HELLO | 1 | Node announces itself + capability summary | Node descriptor (capabilities, fw version, tier, transports) |
| EVENT | 2 | One game or system event | Already defined in codec.c (events.yaml) |
| ACK | 3 | Confirms receipt of a sequence number | Acknowledged node id + seq |
| STATE | 4 | Periodic snapshot of local state + per-team counters | Node state (owner, phase, timers), score counters |
| CMD | 5 | Controller/GM instruction | Command type (start/pause/reset/set_owner/message), parameters |
| TIME | 6 | Game-clock beacon; also controller heartbeat | Game time_ms, game state (running/paused), game duration, wall_clock |
| CONFIG | 7 | Assigns a preset and role; parameters only | Mode id, role, params JSON, team names |
| CLAIM | 8 | Controller election with term number | Candidate node id, term, priority score |

### 2.3 Security -- AES-CCM and replay protection (spec section 14)

- **Per-game 128-bit key**: generated by the controller when a game is created
- **AES-CCM**: authenticates and encrypts every LoRa packet (8-byte MIC = MAC tag)
- **Replay protection**: game_id (2B) + source (2B) + seq (2B); nodes reject already-seen or other-game packets
- **Key distribution**: during join only, via NFC card, QR code, or BLE pairing -- never over LoRa
- **NFC tag payloads**: signed with the game key, not UID-only

### 2.4 Time sync (spec section 10)

- Controller broadcasts TIME beacon every 30 s (10 s with failover enabled)
- Nodes slew their game clocks towards the beacon
- Target accuracy: +/-250 ms (human-scale game timing)
- Nodes with GPS may use GPS time instead
- TIME uses the 869.4-869.65 MHz 10% duty-cycle sub-band

### 2.5 State, scores and partitions (spec section 10)

- Each node is authoritative for its own local state
- The controller is authoritative for field state and official totals
- Scores: per-node per-team grow-only counters, merged by maximum (already implemented in `score.h`)
- Reconnect replay: a node that loses its link keeps playing; on reconnect it sends every event after its last acknowledged sequence
- STATE messages carry periodic snapshots of each node's counters

### 2.6 Joining a game (spec section 10)

Three join methods:
1. **NFC join card**: tapping a card prepared by the GM; carries game_id, key, teams, role
2. **QR code**: displayed on the GM console; scanned by the node's camera or the GM's phone
3. **BLE pairing**: from the GM's phone to the node

Joining pushes scripts and assets over Wi-Fi or BLE (never LoRa). A new game always gets a new key.

### 2.7 Field controller (spec section 11)

**Components**:
- Core runtime running `field.lua` for each active mode
- Radio gateway for LoRa, plus Wi-Fi and BLE transports
- MQTT broker (Mosquitto on Pi; embedded on Android)
- Web server: REST + WebSocket API + GM console web app
- SQLite store: games, presets, event logs, mode packages, node registry
- Optional site server link (MQTT/HTTPS)

**MQTT topics**:
```
field/v1/{game}/events/{type}
field/v1/{game}/score                 (retained)
field/v1/{game}/nodes/{node}/state    (retained)
field/v1/{game}/nodes/{node}/health   (retained)
field/v1/{game}/cmd/{node}            (GM token required)
field/v1/{game}/cmd/all               (broadcast, GM token required)
```

**REST endpoints** (17 defined in spec):
- GET/POST `/api/v1/nodes`, `/api/v1/modes`, `/api/v1/presets`
- POST `/api/v1/games`, `/api/v1/games/{id}/start|pause|resume|end`
- GET/POST `/api/v1/games/{id}/score`
- POST `/api/v1/nodes/{id}/cmd`
- GET `/api/v1/games/{id}/log`
- WS `/api/v1/stream`

**Failover** (spec section 11):
- Candidates announce priority (power source, battery, storage, link quality)
- TIME doubles as heartbeat (10 s with failover); three missed beacons start election
- CLAIM message with term number; highest priority wins, lowest node_id breaks ties
- Recovery: new controller asks every node for events after last ACK'd seq; replays them
- Former controller steps down on seeing a higher term, merges its log
- Field scripts must be replayable (state from events + params + seeded rand only)

### 2.8 GM console web app (spec section 12)

PWA served by the controller:
- **Field view**: nodes on a map (GPS or dragged onto field image), owner colour, battery, link quality
- **Preset builder**: forms from mode parameter schemas; save/copy/share
- **Game control**: start, pause, end; broadcast messages; override zone owner; adjust score
- **Live feed**: every event, filterable, with alert rules
- **After-action report**: score timeline, captures per zone, event log export

### 2.9 Scoreboard example (spec section 11)

A Pi or ESP32 with a big LED display subscribes to the MQTT `score` topic and renders live scores. This is explicitly listed as a Phase 2 deliverable and covers the forum request "read points from a Pi or Arduino."

---

## 3. Protocol details still "not defined yet"

From `protocol/README.md` "Not defined yet" section:

### 3.1 Header `version_flags` bit layout

The 1-byte `version_flags` field needs a defined bit layout. Proposed:

```
Bits 7-5: protocol version (0-7; v1 = 0b001)
Bits 4-3: priority (0 = telemetry, 1 = normal, 2 = critical)
Bit    2: ACK requested
Bit    1: encrypted (always 1 on LoRa)
Bit    0: reserved (0)
```

This gives 3 bits for version (room for 7 protocol revisions), 2 bits for priority (matching the 3 priority levels), and 1 bit each for ACK-request and encryption flags.

### 3.2 Header byte order

The spec lists game_id (2B), source (2B), and seq (2B) but does not specify endianness. Network byte order (big-endian) is the standard convention. LoRa and CBOR both use big-endian for multi-byte integers.

### 3.3 AES-CCM with the game key

- **Key**: 128-bit, generated by the controller at game creation
- **Nonce**: 13 bytes constructed from game_id (2B) + source (2B) + seq (2B) + padding (7 bytes zeroed) -- ensures uniqueness per packet per game
- **AAD** (additional authenticated data): the 9-byte header (version_flags through type) -- authenticated but not encrypted, so nodes can read the header before decrypting
- **Plaintext**: the payload (up to 200 bytes)
- **Tag length**: 8 bytes (the MIC at the end of the packet)

The nonce must be unique per (key, message). Since (game_id, source, seq) is unique per game, the nonce is naturally unique without state.

### 3.4 Key exchange during join

The game key is transferred during the join flow (NFC / QR / BLE), never over LoRa. The join message also carries: game_id, team names, the node's assigned short id, and the node's role. After join, the node sends HELLO over LoRa to announce itself to the network.

### 3.5 Message payloads (CBOR maps with integer keys)

Each message type needs a defined payload schema. These must be added to `protocol/schema/messages.yaml` (or a companion file) and processed by `tools/protogen.py`.

**HELLO (id 1)**:
```
{ 1: node_name,       // string
  2: platform,        // string ("esp32s3", "linux", "android")
  3: fw_version,      // string
  4: core_version,    // string
  5: tier,            // string ("full", "reduced", "proxy")
  6: capabilities,    // array of capability type strings
  7: transports }     // array of transport strings
```

**ACK (id 3)**:
```
{ 1: ack_node,  // uint16 -- the source node being acknowledged
  2: ack_seq }  // uint16 -- the sequence number being acknowledged
```

**STATE (id 4)**:
```
{ 1: owner_team,    // uint8
  2: phase,         // string (mode-specific: "armed", "standby", etc.)
  3: game_time_ms,  // uint32
  4: gained,        // map { team_id: uint32 } -- score counters
  5: lost }         // map { team_id: uint32 } -- penalty counters
```

**CMD (id 5)**:
```
{ 1: cmd_type,   // string ("start", "pause", "resume", "end", "set_owner", "message", "reset")
  2: params }    // map -- varies by cmd_type
```

**TIME (id 6)**:
```
{ 1: game_time_ms,   // uint32
  2: game_state,     // uint8 (0=waiting, 1=running, 2=paused, 3=ended)
  3: duration_ms,    // uint32 (0=unlimited)
  4: wall_clock_s }  // uint32 (Unix epoch seconds, for GPS-less sync)
```

**CONFIG (id 7)**:
```
{ 1: mode_id,     // string
  2: role,         // string
  3: params_json,  // string (the preset parameters as JSON)
  4: teams }       // array of team name strings
```

**CLAIM (id 8)**:
```
{ 1: term,       // uint32 -- election term number
  2: priority,   // uint16 -- candidate priority score
  3: node_id }   // uint16 -- candidate node short id
```

### 3.6 Redundant team name in EVENT data

The protocol README notes: "Sending a team's name in data.team as well as its id in the envelope is redundant on LoRa. Dropping the name needs the receiver to know the game's teams, so it waits for the join flow."

After Phase 2 join is implemented, the EVENT codec on LoRa should drop `data.team` (key 1) when the team id is already in the envelope's `team` field (key 5). This saves 4-8 bytes per event. The receiver reconstructs the team name from the game's team list received during join.

---

## 4. LoRa radio and module selection

### 4.1 ESP32 side (Field Box and USB radio modem)

**Board: Heltec WiFi LoRa 32 V4.3 high-power (863-928 MHz).**
ESP32-S3R2, 2 MB PSRAM, 16 MB flash, SX1262 with front-end module
(FEM) for 28 +/- 1 dBm TX output and -137 dBm RX sensitivity at
SF12/125 kHz. FEM is controlled by GPIO2 (FEM_EN) and GPIO7
(VFEM_Control). The same board serves as the controller's USB radio
modem (connected to the Pi over USB, running modem firmware).

The SX1262 supports:
- EU868, US915, AS923, AU915 (all Atalaia regions)
- LoRa modulation: SF5-SF12, BW 125-500 kHz
- Output power: up to +22 dBm from SX1262, boosted to 28 dBm by the
  FEM. EU868 limit is +14 dBm ERP (25 mW) on g bands, so the SX1262
  must be set to ~0 dBm to account for 14 dB FEM gain.
- Receive sensitivity: -137 dBm at SF12/125 kHz (with FEM LNA)
- Packet engine with CRC, header mode, sync word

**Driver options for ESP-IDF**:

| Library | Licence | Notes |
|---------|---------|-------|
| [RadioLib](https://github.com/jgromes/RadioLib) | MIT | C++ library; supports SX1261/62/68, SX1276/77/78/79; well-maintained; Arduino-focused but has a plain HAL layer that can be adapted for ESP-IDF |
| [esp-idf-sx126x](https://github.com/nopnop2002/esp-idf-sx126x) | MIT | Plain C ESP-IDF component for SX126x; thin wrapper over Semtech's reference driver |
| Semtech reference driver | BSD | Official C driver for SX126x; bare-metal HAL, needs SPI and GPIO callbacks; well-documented |
| [LoRa-E5 / SX126xDrivers](https://github.com/Lora-net/sx126x_driver) | BSD-3-Clause | Semtech's standalone driver library; C99; minimal dependencies |

**Recommendation**: Use the **Semtech reference SX126x driver** (BSD) wrapped in an `hal_radio_ops_t` module. This follows the same HAL pattern as Phase 1 (ADR-P1-1) and avoids C++ dependencies in a C11 codebase. The driver is thin, well-tested, and the exact code Semtech ships for their own evaluation boards.

### 4.2 Raspberry Pi side (field controller)

**Decision: USB radio modem, not an SPI LoRa HAT.**

A second Heltec V4.3 board connected to the Pi over USB runs the same
SX1262 driver, AES-CCM, flood/dedupe, and duty-cycle code as the
nodes. The Python controller communicates with it over USB serial
using a binary framing protocol.

Advantages over an SPI HAT:
- Same radio code on nodes and the modem -- one implementation.
- AES-CCM, dedupe, duty-cycle run on the ESP32, not on the Pi.
- No spidev, libgpiod, or kernel SPI driver needed on the Pi.
- A spare node board doubles as the controller's radio.

No Pi-side radio driver libraries are needed. The only Pi dependency
for radio communication is `pyserial`.

---

## 5. Field controller technology

### 5.1 Language and runtime options

The field controller is a new software component that must:
- Run the shared C core (for `field.lua` scripts)
- Drive the LoRa radio
- Run an MQTT broker
- Serve REST + WebSocket API + the GM console web app
- Store games, presets, logs in SQLite
- Handle controller failover (CLAIM election)
- Manage node joins (NFC, QR, BLE)

| Option | Pros | Cons |
|--------|------|------|
| **C with the existing core** | Zero FFI overhead; same radio driver as ESP32; direct access to core internals; single language across the whole stack | Web server and REST API in C is verbose; MQTT broker integration harder; longer development time |
| **Python (CPython 3.11+)** | Rapid development; excellent libraries for HTTP (Flask/FastAPI), WebSocket, MQTT (paho-mqtt), SQLite; ctypes FFI to the core already exists in the simulator | GIL limits concurrency; ctypes has overhead per call; not ideal for real-time radio handling; Mosquitto still needed as a separate process |
| **Go** | Fast, compiled, excellent concurrency (goroutines); strong HTTP/WebSocket stdlib; embedded MQTT brokers exist (mochi-mqtt); cgo can call the C core; good cross-compilation for ARM | cgo has overhead and complicates builds; the C core must be compiled as a shared library; Go SPI drivers exist but are less mature |
| **Rust** | Memory safety; excellent concurrency; can call C directly via FFI; growing embedded ecosystem | Steep learning curve; smaller library ecosystem for MQTT brokers; longer development time |
| **Node.js** | Fast prototyping; good WebSocket/HTTP support; npm ecosystem | N-API/NAPI for the C core is complex; not great for low-level SPI radio; Mosquitto still separate |

**Analysis**:

The strongest argument for **Python** is that the simulator (which already wraps the C core via ctypes) proves the FFI works. The controller would reuse `atalaia_sim/core.py` bindings, and the web/API layer is fast to build with Flask or FastAPI. Mosquitto runs as a separate process on the Pi, which is the standard Debian deployment. The main risk is ctypes call overhead for time-critical radio operations; this can be mitigated by writing the radio gateway layer in C as a small daemon that communicates with the Python controller via a Unix socket or shared memory.

The strongest argument for **C** is code sharing with the ESP32 side: the same packet encoder/decoder, the same SX126x driver, and the same core -- no FFI boundary. But writing a web server and REST API in C is a significant effort.

A **hybrid approach** is the pragmatic middle ground:
1. A small C daemon (`atalaia-radio`) that owns the SPI radio, encodes/decodes packets, and exposes a local Unix-domain socket or ZeroMQ interface
2. A Python application that runs the core (via ctypes), the REST/WebSocket API, MQTT integration, SQLite store, and the GM console

This keeps the time-critical radio code in C (sharing code with ESP32) and the application logic in Python (fast to develop, easy to extend).

### 5.2 Recommended approach

**Python with a USB radio modem** (revised from the original C radio
gateway recommendation). The modem is a Heltec V4.3 board running
modem firmware over USB. The original research proposed a C daemon that:
- Initialises the SX1262 via SPI
- Encodes/decodes Skirmesh-RF packets (header + CBOR payload + AES-CCM)
- Enforces duty-cycle limits
- Communicates with the Python controller via a Unix socket (JSON-framed messages)

The Python controller:
- Runs the `atalaia_node_t` (for `field.lua`) via ctypes (reusing simulator bindings)
- Manages the game lifecycle, node registry, join flow
- Runs Mosquitto via subprocess or connects to a system Mosquitto
- Serves the REST API (FastAPI + uvicorn) and WebSocket stream
- Stores data in SQLite
- Serves the GM console web app (static files + API)

---

## 6. Simulator extension

### 6.1 Current state

The simulator (`simulator/atalaia_sim/sim.py`) runs any number of virtual nodes on a virtual clock. Cross-node delivery does NOT exist: each node runs independently and only sees events it emits or that the controller broadcasts to all nodes via `sim.broadcast()`. The `Simulation.broadcast()` method feeds events to every node simultaneously with no network model.

### 6.2 What Phase 2 needs

The spec says "simulator extended to multi-node delivery with simulated lossy radio." This requires:

1. **A network model** between virtual nodes:
   - Each node has a simulated radio
   - Messages are delivered to other nodes with configurable latency and packet loss
   - The TTL-limited flood is simulated (hop_limit, dedupe by (source, seq))
   - Nodes can be placed at virtual positions with distance-based loss

2. **A virtual field controller**:
   - One virtual node acts as the controller
   - It runs `field.lua` (Phase 2 adds field script support to the simulator)
   - It merges event logs, maintains official scores, sends TIME beacons

3. **Partition simulation**:
   - Virtual nodes can be disconnected from the controller
   - They keep running and scoring locally
   - When reconnected, they replay missed events
   - The merge-by-maximum score reconciliation is exercised

4. **Duty-cycle tracking**:
   - The simulator tracks each node's airtime
   - It warns or errors when a node exceeds the configured duty-cycle limit
   - This catches protocol designs that would violate EU868 rules

### 6.3 Implementation approach

Add a `RadioModel` class to the simulator:

```python
class RadioModel:
    def __init__(self, loss_rate=0.0, latency_ms=0, duty_cycle=0.01):
        ...

    def transmit(self, sender, packet_bytes, recipients):
        """Returns list of (recipient, delay_ms) for nodes that receive the packet."""
        ...

    def airtime_ok(self, sender, packet_bytes):
        """Returns True if the sender has enough duty-cycle budget."""
        ...
```

The `Simulation` class gains:
- A `RadioModel` instance
- A pending delivery queue (packets in flight)
- A `deliver_pending()` method called during `advance_to()` that delivers packets after their delay
- Flood logic: each receiving node rebroadcasts once if hop_limit > 0 and (source, seq) not seen

Mode tests that test single-node logic do not change. New tests exercise multi-node scenarios: partition, reconnect, score merge, TIME sync.

---

## 7. Assumptions about Phase 1

Every interface Phase 2 depends on, with references to Phase 1 ADR and PLAN:

### 7.1 HAL abstraction (ADR-P1-1)

Phase 2 assumes the `hal_t` struct in `firmware/esp32/main/hal/hal.h` is extensible by adding a new `hal_radio_ops_t *radio` pointer. ADR-P1-1 explicitly says: "Adding a new peripheral (GPS, IMU, LoRa) follows the same pattern: add an ops struct, an ESP implementation and a stub."

Required `hal_radio_ops_t` functions:
- `init(region, tx_power, sf, bw)` -- configure the SX1262
- `send(buf, len)` -- transmit a packet (blocks until TX complete or timeout)
- `recv(buf, cap, timeout_ms)` -- receive a packet (blocks until RX or timeout)
- `set_channel(freq_hz)` -- change frequency
- `set_mode(rx_continuous | sleep | standby)` -- power management
- `rssi()` -- current RSSI
- `duty_cycle_remaining_ms()` -- how much airtime budget remains

### 7.2 Node runner (Phase 1 PLAN Phase B)

Phase 2 assumes `node_runner_t` in `firmware/esp32/main/node_runner.h`:
- Owns the `atalaia_node_t` and game timer
- Provides `node_runner_input()` for feeding events from the radio
- Provides `node_runner_tick()` for advancing game time
- Exposes `node_runner_status()` and the underlying node's score

Phase 2 extends `node_runner_t` with:
- A radio send callback: when the core emits an event, the runner passes it to the radio layer
- A TIME sync handler: adjusts the game timer based on received TIME beacons
- A STATE sender: periodically sends the node's score counters as a STATE message

### 7.3 Game timer (ADR-P1-3)

Phase 2 assumes the game timer lives in the shell (not the core), which is correct per ADR-P1-3. Phase 2 adds time synchronisation: the shell slews the game timer towards the controller's TIME beacon value.

### 7.4 Config store (Phase 1 PLAN Phase C)

Phase 2 reads the radio region from `config_store` (set during Wi-Fi captive-portal setup). The radio region determines: frequency band, max TX power, duty-cycle limits, and channel plan.

### 7.5 Core API stability

Phase 2 depends on the following core APIs remaining stable:
- `atalaia_node_create/destroy/input/advance/score` (node.h)
- `atalaia_event_init/compare` (event.h)
- `atalaia_score_merge` (score.h)
- `atalaia_event_encode/decode` (codec.h)
- `atalaia_prio_t` enum values (protocol.h)
- `ATALAIA_PROTOCOL_VERSION` (version.h)

The core is at v0.1.0; Phase 2 may require a minor version bump if `state.field{}` and `field.*` APIs are added to `script_api.c`.

### 7.6 Lua API additions (Phase 2 scope, not Phase 1)

Phase 1 `script_api.c` lists these as "Not yet":
- `state.field{}` -- replicated state via the controller
- `field.*` -- field script API (controller-only: `field.nodes`, `field.owner`, `field.common_owner`, `field.send`)

These are Phase 2 additions to the core, needed for `field.lua` scripts.

---

## 8. Risks and mitigations

### R1: LoRa range in buildings (High)

Sub-GHz LoRa penetrates walls better than 2.4 GHz Wi-Fi, but thick stone/brick buildings (common in Portuguese palacetes and warehouses used for CQB) still attenuate the signal significantly. Range inside a CQB building may be under 100 m.

**Mitigation**: The protocol supports dedicated repeater nodes (any spare ESP32 with LoRa). CQB field profile defaults to SF7 (faster, more packets, but shorter range). For difficult layouts, the GM places one or two repeaters. Phase 2 testing must include range measurements in a real CQB building.

### R2: EU868 duty-cycle compliance (High)

The 1% duty-cycle limit is legally binding in EU868. At SF7/125 kHz, a 30-byte packet = ~67 ms of airtime. 500 packets/hour per device sounds like a lot, but a 5-box game with 30-second snapshots and event traffic can approach the limit, especially with retries.

**Mitigation**:
- The controller's TIME beacons and commands use the 10% sub-band (869.4-869.65 MHz)
- Events stay local unless they are game events
- Snapshot interval is configurable (longer interval = less airtime)
- The radio HAL tracks duty cycle and refuses to transmit when the budget is exhausted
- The simulator tracks airtime and fails tests that exceed the budget
- The node logs a `battery.low`-style system event when airtime budget drops below 20%

### R3: Time sync accuracy (Medium)

The target is +/-250 ms. LoRa packet transmission time varies with spreading factor (67 ms at SF7, 180 ms at SF9), and processing delays add jitter. A node that receives a TIME beacon must account for the transmission delay.

**Mitigation**:
- Include the transmission timestamp in the TIME payload (the controller records when it starts sending)
- The node measures the RSSI and the known airtime of the TIME packet to estimate one-way delay
- Use a slew algorithm (not a step): adjust the local clock gradually over several beacons
- The 250 ms target is generous for human-scale timing; even a simple approach should meet it
- GPS-equipped nodes bypass LoRa time sync entirely

### R4: Controller failover correctness (High)

The CLAIM election protocol must guarantee that exactly one controller is active at any time. Split-brain (two controllers both accepting commands) would corrupt the game log.

**Mitigation**:
- Term numbers are monotonically increasing; every node follows the highest term it has seen
- A node only accepts commands from the controller with the highest term
- The former controller steps down immediately on seeing a higher term
- Field scripts are replayable (state from events only), so the new controller can reconstruct state
- Scores are conflict-free (merge by maximum), so no score is lost or double-counted
- Phase 2 implements failover as a stretch goal; the minimum viable controller is a single Pi with no failover

### R5: Game key security (Medium)

The 128-bit AES key protects against casual cheating with an SDR. A determined attacker with physical access to a node could extract the key from RAM or flash.

**Mitigation**:
- The key is per-game and ephemeral; extracting it after the game is useless
- The key never travels over LoRa; it is distributed via NFC/QR/BLE during join
- The threat model is "hard to cheat casually, obvious when someone tries" -- not bank-grade
- A dedicated attacker with an SDR and the key can inject fake packets, but the GM sees anomalous events in the console feed
- Future improvement: per-node session keys derived from the game key (HKDF), so compromising one node does not compromise all traffic

### R6: AES-CCM library availability (Low)

AES-CCM is needed on both ESP32 and Pi.

**Mitigation**:
- ESP-IDF includes `mbedtls` with AES-CCM support (hardware-accelerated on ESP32-S3)
- On Pi/Linux: OpenSSL or mbedtls (both have AES-CCM)
- The nonce construction (game_id + source + seq) is deterministic and does not require a random number generator

### R7: Multi-node state merge after partition (Medium)

When a node reconnects after being out of range, the controller must merge its events and scores without duplication or loss.

**Mitigation**:
- (source, seq) uniquely identifies every event; the controller's dedupe table rejects duplicates
- Scores merge by maximum per counter (already proven in `score.h` unit tests)
- The reconnecting node sends events starting from its last ACK'd sequence number
- The controller can request specific sequence ranges if gaps are detected

---

## 9. Dependencies and tooling

### 9.1 ESP32 firmware additions

| Dependency | Purpose | Source |
|------------|---------|--------|
| Semtech SX126x C driver | LoRa radio control | Semtech/sx126x_driver (BSD-3-Clause) |
| mbedtls (bundled in ESP-IDF) | AES-CCM for packet MIC + encryption | Already in ESP-IDF |

### 9.2 Field controller (Raspberry Pi)

| Dependency | Purpose | Source |
|------------|---------|--------|
| Python 3.11+ | Controller application language | System package |
| FastAPI + uvicorn | REST API and WebSocket server | pip |
| paho-mqtt | MQTT client (connects to Mosquitto) | pip |
| Mosquitto | MQTT broker | Debian package (`apt install mosquitto`) |
| SQLite 3 | Game, preset, log storage | System (Python stdlib `sqlite3`) |
| ctypes | FFI to the shared C core | Python stdlib |
| libatalaia_core.so | Shared C core library | Built from `core/` |
| Semtech SX126x C driver | Radio gateway daemon | Same as ESP32 |
| spidev | SPI access from C/Python | Linux kernel module |
| libgpiod | GPIO access from C | Debian package |

### 9.3 GM console web app

| Dependency | Purpose |
|------------|---------|
| HTML + CSS + vanilla JS (or a light framework: Preact, Alpine.js) | GM console frontend |
| Leaflet or OpenLayers | Map for node positions |
| WebSocket API | Live event stream |

The GM console should be a PWA (Progressive Web App) with minimal dependencies, served as static files by the controller. No Node.js build step at runtime.

### 9.4 Protocol tooling

| Dependency | Purpose |
|------------|---------|
| `tools/protogen.py` (existing) | Must be extended to generate message payload schemas |
| PyYAML (existing) | YAML parsing for schema files |

### 9.5 Testing

| Dependency | Purpose |
|------------|---------|
| `atalaia-dev` Docker image (existing) | Desktop builds and simulator tests |
| `espressif/idf:v5.3.2` Docker image (Phase 1) | ESP32 cross-compilation |
| pytest | Controller tests |
| Playwright or Cypress | GM console end-to-end tests (optional, stretch) |

---

## 10. What can be built without hardware vs what needs LoRa hardware

### Can be built and tested without LoRa hardware

| Component | How it is tested |
|-----------|------------------|
| Protocol: message payload schemas and CBOR codegen | Schema validation, encode/decode roundtrip tests |
| Protocol: AES-CCM encrypt/decrypt | Unit tests with known test vectors (RFC 3610) |
| Protocol: header parsing, version_flags layout | Unit tests |
| Protocol: dedupe logic, ACK tracking, retry state machine | Unit tests |
| Protocol: duty-cycle tracking algorithm | Unit tests with simulated time |
| Simulator: multi-node delivery with lossy radio model | Simulator tests |
| Simulator: partition and reconnect scenarios | Simulator tests |
| Simulator: TIME sync algorithm | Simulator tests |
| Core: `state.field{}` and `field.*` API additions | Core unit tests + simulator mode tests |
| Controller: REST API, MQTT integration, SQLite store | pytest with mocked radio |
| Controller: game lifecycle, node registry, join flow | pytest with mocked radio |
| Controller: failover election (CLAIM protocol) | pytest with simulated nodes |
| GM console: web app UI, preset builder, live feed | Browser tests against mock API |
| Scoreboard example: MQTT subscriber | Unit tests against mock broker |
| ESP32 radio HAL: stub implementation | Stub tests on Linux |

### Needs LoRa hardware

| Component | Why |
|-----------|-----|
| ESP32 radio HAL: real SX1262 driver | SPI timing, register configuration, interrupt handling |
| Range and signal measurements | Real RF propagation in buildings and outdoors |
| Duty-cycle validation under real conditions | Actual airtime measurements vs theoretical calculations |
| Time sync accuracy | Real packet transmission delays and jitter |
| End-to-end 5-box field test (the Phase 2 gate) | Real devices, real radio, real field |
| Power consumption with LoRa active | Battery life under real radio duty cycles |

**Key insight**: roughly 80% of Phase 2 software can be built and tested without LoRa hardware. The protocol, controller, GM console, and simulator extension are all testable on desktop. Hardware is needed for radio driver bring-up, range testing, and the final field gate test.

---

## 11. Files to create or modify

### New directories

| Path | Purpose |
|------|---------|
| `controller/src/` | Field controller Python application |
| `controller/radio/` | C radio gateway daemon |
| `controller/console/src/` | GM console web app source |
| `controller/tests/` | Controller test suite |
| `firmware/esp32/main/hal/hal_radio.h` | Radio HAL header |
| `firmware/esp32/main/hal/esp/hal_esp_radio.c` | SX1262 ESP-IDF driver |
| `firmware/esp32/main/hal/stub/hal_radio_stub.c` | Radio stub |
| `firmware/esp32/main/radio/` | Radio protocol layer (packet encode/decode, ACK, retry, flood, dedupe, duty cycle) |

### New files (protocol)

| Path | Purpose |
|------|---------|
| `protocol/schema/messages_payload.yaml` | Payload schemas for all 8 message types |
| `core/include/atalaia/packet.h` | Packet header struct, encode/decode, AES-CCM |
| `core/src/packet.c` | Implementation |
| `core/include/atalaia/radio.h` | Radio protocol: ACK tracking, retry, flood, dedupe, duty cycle |
| `core/src/radio.c` | Implementation |
| `core/tests/test_packet.c` | Packet codec tests |
| `core/tests/test_radio.c` | Radio protocol logic tests |

### New files (controller)

| Path | Purpose |
|------|---------|
| `controller/src/main.py` | Controller entry point |
| `controller/src/game.py` | Game lifecycle, node registry, score merge |
| `controller/src/api.py` | FastAPI REST endpoints |
| `controller/src/ws.py` | WebSocket live event stream |
| `controller/src/mqtt.py` | MQTT topic publisher |
| `controller/src/store.py` | SQLite store for games, presets, logs |
| `controller/src/radio_bridge.py` | Communicates with the C radio gateway |
| `controller/src/time_sync.py` | TIME beacon generation |
| `controller/src/failover.py` | CLAIM election protocol |
| `controller/src/join.py` | Node join flow (NFC, QR, BLE key distribution) |
| `controller/radio/main.c` | C radio gateway daemon |
| `controller/radio/CMakeLists.txt` | Build system |
| `controller/console/src/index.html` | GM console PWA shell |
| `controller/console/src/app.js` | GM console application logic |
| `controller/console/src/style.css` | GM console styles |

### New files (simulator)

| Path | Purpose |
|------|---------|
| `simulator/atalaia_sim/radio_model.py` | Simulated lossy radio with delivery queue |
| `simulator/atalaia_sim/field_controller.py` | Virtual field controller for multi-node tests |
| `simulator/tests/test_radio_model.py` | Radio model unit tests |
| `simulator/tests/test_multi_node.py` | Multi-node delivery, partition, reconnect tests |

### Modified files

| Path | Change |
|------|--------|
| `firmware/esp32/main/hal/hal.h` | Add `const hal_radio_ops_t *radio` to `hal_t` |
| `firmware/esp32/main/node_runner.h` | Add radio send callback, TIME sync handler, STATE sender |
| `firmware/esp32/main/node_runner.c` | Wire radio events into the node |
| `firmware/esp32/main/shell.c` | Init radio HAL, start radio task |
| `core/src/script_api.c` | Add `state.field{}` and `field.*` functions |
| `core/include/atalaia/node.h` | Add field-script node type (if needed) or keep as a separate `field_node` |
| `simulator/atalaia_sim/sim.py` | Integrate `RadioModel`, add multi-node delivery |
| `simulator/atalaia_sim/live.py` | Add field controller to the live web view |
| `tools/protogen.py` | Generate message payload schemas |
| `protocol/schema/messages.yaml` | Add payload field definitions |
| `protocol/README.md` | Document the now-defined protocol details |
| `controller/README.md` | Replace placeholder with real documentation |
| `controller/console/README.md` | Replace stub with real documentation |

---

## 12. Open questions for architecture/planning

### Q1: Controller language -- final decision

Python with a C radio gateway is the recommended approach (section 5.2), but this is a significant architectural decision. Alternatives (pure C, Go, Rust) should be evaluated in the ADR phase.

Key factors:
- Development speed (the project has one contributor)
- Code sharing with the existing simulator
- FFI overhead for time-critical radio operations
- Long-term maintainability

### Q2: Radio module for the Pi controller

The Waveshare SX1262 LoRa HAT is recommended (section 4.2), but availability and pricing vary by region. The architecture should support any SPI-connected SX126x module.

### Q3: Default regulatory region

The spec says "EU868 in Portugal and the rest of Europe". Should the firmware default to EU868 and require explicit opt-in for other regions? Or should it refuse to transmit until a region is explicitly set (current spec behaviour)?

**Recommendation**: refuse to transmit until a region is set, as the spec requires. The captive-portal setup page (Phase 1) already collects the radio region.

### Q4: Packet encryption: mandatory or optional?

The spec says "payloads are encrypted by default so bomb codes are not visible on air." Should encryption be mandatory on LoRa, or should there be a plaintext mode for debugging?

**Recommendation**: mandatory on LoRa (the `encrypted` bit in version_flags is always 1). A debug/monitor mode can decrypt packets using the game key but should never send unencrypted.

### Q5: MQTT broker: Mosquitto or embedded?

The spec says "Mosquitto on Pi; an embedded broker on Android." For Phase 2 (Pi only), Mosquitto as a system service is the simplest approach. An embedded MQTT broker in the controller process would reduce operational complexity but adds code.

**Recommendation**: system Mosquitto for Phase 2. The controller connects as a client and publishes/subscribes. Evaluate embedded brokers (like `hbmqtt` or `mochi-mqtt` if using Go) for Phase 3 Android support.

### Q6: GM console framework

The GM console is a web app served as static files. Options:
- Vanilla HTML/CSS/JS: zero build step, simple, but hard to maintain as complexity grows
- Preact + HTM: ~3 KB, JSX-like syntax, no build step needed (importable from CDN)
- Alpine.js: reactive bindings without a build step
- Svelte or React: requires a build step (npm)

**Recommendation**: Preact + HTM (no build step). Small enough to serve from the Pi, reactive enough for a live event feed, and can grow without a toolchain change. The decision belongs in the ADR phase.

### Q7: Scope of field scripts (`field.lua`) in Phase 2

Phase 2 needs `field.lua` support for cross-node modes, but the spec's Hold-All Domination and other multi-node modes are Phase 3. Should Phase 2 implement the full `field.*` Lua API, or just enough for the GM console's game control (start/pause/end, score merge)?

**Recommendation**: implement the full `field.*` API in Phase 2 (it is small: `field.nodes`, `field.owner`, `field.common_owner`, `field.send`). The simulator and controller both need it, and deferring it to Phase 3 means the controller cannot run field scripts, which is a core spec requirement.

### Q8: Failover scope in Phase 2

Controller failover (CLAIM election) is specified in the design but adds significant complexity. Should Phase 2 implement full automatic failover, or defer it to a follow-up?

**Recommendation**: implement the CLAIM protocol and election logic in Phase 2 but mark automatic failover as a "tested in simulator, manual activation" feature. The GM can manually promote a backup controller from the console. Full automatic failover becomes default in Phase 3 after field testing.

### Q9: Scoreboard -- separate project or example in this repo?

The spec calls for a "scoreboard example." Should this be:
- A Python script in `examples/scoreboard/` that subscribes to MQTT
- A small ESP32 firmware for a 7-segment or LED-matrix display
- Both

**Recommendation**: a Python script in `examples/scoreboard/` that prints scores to stdout and optionally drives a web page or display. ESP32 scoreboard firmware is a Phase 4 concern.

### Q10: How to test LoRa without a field

Before the 5-box field test gate, the protocol and radio code need some form of hardware-in-the-loop testing.

**Options**:
- Two ESP32 LoRa boards on a desk (minimal range, no obstacles)
- ESP32 + Pi with LoRa HAT on a desk (tests the full stack)
- A walk-around test with two battery-powered boards

**Recommendation**: start with two ESP32 boards on a desk for protocol bring-up, then ESP32 + Pi for full-stack testing. The 5-box field test is the gate and needs real field conditions.
