<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 2 -- Field Network: Implementation Plan

Gate: **5 boxes on a CQB site and an outdoor field, with zero lost
captures.**

Constraint: Phase 1 is still in progress; hardware has not arrived for
Phase 2 radio testing. All builds run in Docker. What can be verified
now (protocol codecs, simulator, controller, GM console) is separated
from what needs LoRa hardware (radio HAL bring-up, range testing, the
field gate). Roughly 80% of Phase 2 software can be built and tested
without LoRa hardware.

---

## Scope

### In scope (software -- buildable and testable without LoRa hardware)

- RFC-0001 draft: Skirmesh-RF v1 wire format specification.
- `protogen.py` extension: generate message payload codec tables (C
  structs + encode/decode functions, Python dicts) from a new `payload`
  section in `messages.yaml`.
- Shared packet codec in `core/`: header encode/decode, AES-CCM
  encrypt/decrypt wrapper, CBOR payload codecs for all 8 message types.
  Test vectors for every codec path.
- Flood/dedupe logic in `core/`: 64-entry dedupe table, rebroadcast
  with 10-50 ms jitter, hop_limit decrement.
- ACK tracking and retry state machine in `core/`: per-priority
  behaviour (critical retried until ACK, normal ACK once, telemetry
  best-effort).
- Time sync algorithm: slew module with capped rate, airtime
  compensation, step threshold.
- Duty-cycle tracker: per-sub-band sliding-window airtime accounting,
  single shared game channel on the g2 sub-band (10% duty cycle).
- `state.field{}` and `field.*` Lua API additions to `core/script_api.c`
  (guarded by `field_ops` pointer); core version bump to 0.2.0.
- Event buffer: 128-entry DRAM ring buffer on ESP32; replay protocol
  after reconnect.
- Simulator extension: `RadioModel` class, multi-node delivery with
  lossy radio, `FieldController` class, partition/heal simulation,
  duty-cycle tracking in the simulator.
- Field controller (Python + USB radio modem architecture): game
  lifecycle, node registry, REST API (FastAPI), WebSocket stream, MQTT
  publishing (paho-mqtt to system Mosquitto), SQLite store, TIME beacon
  generation, CLAIM election protocol, join flow (NFC + QR).
- Radio HAL stub (`hal_radio_stub.c`): records calls, injects packets,
  simulates duty-cycle tracking.
- GM console web app: Preact + HTM, no build step; field view, game
  control, preset builder, live feed, node list, score panel; PWA
  with service worker.
- Join flow: NFC card write/read (NTAG215/216 NDEF), QR code generation
  and Wi-Fi-based push to node. HMAC-SHA256 authenticated payload.
- Controller failover: CLAIM protocol fully implemented and tested in
  the simulator; defaults to manual activation.
- Example scoreboard: Python MQTT subscriber in `examples/scoreboard/`.
- ESP32 radio task scaffolding: FreeRTOS task, TX/RX queues, interrupt
  handler (compiles in IDF cross-build; logic testable with stubs).

### In scope (needs LoRa hardware)

- Radio HAL ESP-IDF implementation: SX1262 driver (Semtech BSD
  reference) wrapped in `hal_radio_ops_t`, SPI + GPIO + DIO1 interrupt.
- USB radio modem firmware: Kconfig build variant of the node firmware
  for the Heltec V4.3 board connected to the Pi over USB.
- Desk-top radio bring-up: two ESP32 LoRa boards, then ESP32 + Pi HAT.
- Range and signal measurements in a real CQB building and outdoor field.
- Duty-cycle validation under real RF conditions.
- Time sync accuracy measurement on real hardware.
- Power consumption measurement with LoRa active.
- End-to-end 5-box field test (the Phase 2 gate).

### Out of scope (later phases)

- BLE join (Phase 3: Android app and BLE provisioning).
- Android shell and Flutter player app (Phase 3).
- A/B OTA updates over LoRa (Phase 3; never over LoRa per spec).
- Meshtastic as alternate transport (Phase 3+).
- Site server (Phase 3+).
- Visual mode editor / Blockly (Phase 5).
- Thin-node / proxy tier (Phase 3).
- Per-node session keys via HKDF (future improvement).
- Embedded MQTT broker (Phase 3, for Android controller).
- Hold-All Domination and other multi-node modes (Phase 3; Phase 2
  delivers the `field.*` API they need).
- ATAK / CoT integration (Phase 3+).
- Arista EOS / PAN-OS vendor support (N/A -- wrong project context).

---

## Constraints from ADR.md (all 23 respected)

| # | Constraint | How the plan respects it |
|---|------------|--------------------------|
| 1 | AAD is 8 bytes (header minus hop_limit) | Phase A packet codec uses 8-byte AAD (bytes 0-6 + byte 8); test vectors verify hop_limit exclusion |
| 2 | Radio HAL before protocol code | Phase C lands `hal_radio_ops_t` (header, ESP impl, stub) before wiring the packet codec and flood logic into ESP32 firmware |
| 3 | Packet codec is shared C in `core/` | Phase A creates `core/include/atalaia/packet.h` and `core/src/packet.c`; the Pi radio gateway and ESP32 firmware both link against the same source |
| 4 | USB radio modem, not C daemon | Phase C builds the modem firmware (Kconfig variant of the node firmware); Phase D Python controller communicates via USB serial (`pyserial`); no C process on the Pi |
| 5 | Python reuses simulator bindings | Phase D imports `simulator/atalaia_sim/core.py` ctypes wrapper; no second set of bindings |
| 6 | No build step for GM console | Phase E serves plain HTML/CSS/JS; Preact, HTM and Leaflet are vendored ESM bundles checked into the repo |
| 7 | NFC and QR join only (no BLE) | Phase E implements NFC card join and QR-over-Wi-Fi join; BLE deferred to Phase 3 |
| 8 | Game key in encrypted NVS | Phase E join flow stores the AES-128 key in the ESP32-S3 encrypted NVS partition (eFuse HMAC-derived key); survives reboots; zeroed and deleted on game end |
| 9 | Event log: flash-backed on LittleFS | Phase C creates the append log at `/log/game.bin` on LittleFS (up to 256 KB); normal and critical events flushed immediately; only telemetry buffered (8-entry cache, 5 s) |
| 10 | Dedupe: 64 entries on ESP32 | Phase A creates `core/src/flood.c` with a 64-entry fixed array; controller uses Python dict with no limit |
| 11 | Duty-cycle enforcement in HAL | Phase C implements duty-cycle tracking inside `hal_esp_radio.c`; `send()` returns `-1` on budget exhaustion |
| 12 | TIME beacons on 869.525 MHz (g2) | Phase C radio task sends TIME on 869.525 MHz; Phase D TIME beacon generator targets the g2 sub-band |
| 13 | Failover defaults to manual | Phase D implements the full CLAIM protocol; the default field profile sets `failover_mode = manual` |
| 14 | Core version bump to 0.2.0 | Phase C bumps `ATALAIA_CORE_VERSION` in `core/include/atalaia/version.h` after adding `field_ops` to `atalaia_node_config_t` |
| 15 | Slew not step for time sync | Phase C `time_sync.c` uses linear slew at max 5%/s; steps only when offset exceeds 500 ms |
| 16 | protogen.py extension required | Phase A extends `tools/protogen.py` before any codec implementation |
| 17 | RFC-0001 accepted | RFC accepted by maintainer (2026-10-17); no review wait; implementation begins immediately in Phase A |
| 18 | Scoreboard example in `examples/` | Phase E creates `examples/scoreboard/scoreboard.py` |
| 19 | SQLite for controller storage | Phase D creates `controller/src/store.py` with SQLite tables; events table has UNIQUE on `(game_id, node_id, seq)` |
| 20 | Mosquitto as system service | Phase D documents `apt install mosquitto`; the controller connects via `paho-mqtt` as a client |
| 21 | SPDX headers on every file | `controller/` files use `AGPL-3.0-or-later`; `firmware/` and `core/` files use `GPL-3.0-or-later`; docs use `CC-BY-SA-4.0` |
| 22 | Rebroadcast jitter 10-50 ms | Phase A `core/src/flood.c` draws jitter from `atalaia_rand` seeded with source + seq; Phase B simulator uses the same formula |
| 23 | ~~Three-channel hopping on g sub-band~~ **Superseded by Amendment 1 of RFC 0001 (2026-10-18):** single shared game channel, default 869.525 MHz (g2 sub-band, 10% duty cycle) | Phase C radio HAL uses one channel per game; no hopping |
| 24 | Nonce = (epoch << 16) or seq | Phase A nonce construction uses the epoch and header seq; Phase C persists epoch in NVS at boot and seq wrap |
| 25 | Epoch persisted at boot and seq wrap only | Phase C writes epoch to NVS before first TX after boot and when seq wraps 65535 to 0; if NVS write fails, radio halts |
| 26 | eFuse HMAC key for production | Phase F bring-up checklist includes one-time eFuse key burn; `sdkconfig.defaults` enables `CONFIG_NVS_ENCRYPTION` |
| 27 | Relay clamp | Phase A `core/src/flood.c` clamps incoming hop_limit to game max before rebroadcast; Phase B simulator enforces the same clamp |
| 28 | Uploaded field image is primary map | Phase E field-view component uses uploaded image as default; OSM tiles are online-only with attribution; no bulk prefetch |
| 29 | Power-loss tests | Phase C adds battery-pull test (simulated via destroy+recreate with persisted state); Phase F field test includes a battery-pull scenario |

---

## Phase A: Protocol, RFC, protogen, shared codecs

### Goal

Write RFC-0001 (accepted by maintainer), extend `protogen.py` to
generate message payload codecs, and implement the shared C packet
codec (header, AES-CCM with epoch-based nonce, CBOR payloads,
flood/dedupe with relay clamp, ACK tracker, duty-cycle algorithm)
with comprehensive test vectors. Everything in this phase runs in
Docker on the desktop -- no hardware and no ESP-IDF cross-compilation
required. The RFC is already accepted; implementation proceeds
immediately.

### Files to create

| File | Purpose |
|------|---------|
| `docs/rfcs/0001-skirmesh-rf-wire-format.md` | Already written: accepted RFC for Skirmesh-RF v1 wire format. Phase A adds the test vectors it references. |
| `protocol/vectors/` | Directory for cross-platform test vectors |
| `protocol/vectors/header.json` | Header encode/decode test vectors (min 3: normal, critical, edge) |
| `protocol/vectors/aes_ccm.json` | AES-CCM encrypt/decrypt test vectors with known keys (RFC 3610 parity) |
| `protocol/vectors/hello.json` | HELLO payload encode/decode vectors |
| `protocol/vectors/ack.json` | ACK payload vectors (with and without selective bitmap) |
| `protocol/vectors/state.json` | STATE payload vectors |
| `protocol/vectors/cmd.json` | CMD payload vectors |
| `protocol/vectors/time.json` | TIME payload vectors |
| `protocol/vectors/config.json` | CONFIG payload vectors |
| `protocol/vectors/claim.json` | CLAIM payload vectors |
| `core/include/atalaia/packet.h` | Packet header struct, encode/decode, AES-CCM encrypt/decrypt, `SKMESH_VF_*` macros |
| `core/src/packet.c` | Header byte-swap, nonce construction, AAD extraction, mbedtls AES-CCM wrapper |
| `core/include/atalaia/flood.h` | Dedupe table, rebroadcast decision, jitter calculation |
| `core/src/flood.c` | 64-entry fixed-array dedupe with 30 s expiry and LRU eviction |
| `core/include/atalaia/ack.h` | ACK tracker: per-node last-ACK'd seq, retry queue, priority-based policy |
| `core/src/ack.c` | Implementation |
| `core/include/atalaia/duty_cycle.h` | Per-sub-band airtime tracker, airtime formula, budget check |
| `core/src/duty_cycle.c` | 60-bucket sliding window per sub-band; EU868 band definitions |
| `core/include/atalaia/msg_codec.h` | CBOR payload encode/decode for all 8 message types |
| `core/src/msg_codec.c` | Implementation using integer-key CBOR maps |
| `core/tests/test_packet.c` | Header encode/decode, byte-order, version_flags construction/extraction |
| `core/tests/test_aes_ccm.c` | AES-CCM encrypt/decrypt with known vectors; nonce uniqueness; AAD coverage |
| `core/tests/test_flood.c` | Dedupe insert/lookup/expire/evict; jitter range; hop_limit decrement |
| `core/tests/test_ack.c` | ACK tracking: critical retry, normal single-ACK, telemetry drop; selective ACK bitmap |
| `core/tests/test_duty_cycle.c` | Budget tracking, window slide, multi-band, budget exhaustion |
| `core/tests/test_msg_codec.c` | Round-trip encode/decode for all 8 message types against test vectors |

### Files to modify

| File | Change |
|------|--------|
| `protocol/schema/messages.yaml` | Add `payload` section with field definitions for all 8 types (keys, types, required flags) |
| `protocol/README.md` | Replace "Not defined yet" section with a link to `docs/rfcs/0001-skirmesh-rf-wire-format.md` and the payload schemas |
| `docs/rfcs/README.md` | Already updated: index entry for RFC-0001 |
| `tools/protogen.py` | Add payload codec generation: C structs + encode/decode functions, Python dict schemas, test vector loading |
| `core/CMakeLists.txt` | Add `packet.c`, `flood.c`, `ack.c`, `duty_cycle.c`, `msg_codec.c` to the source list |
| `core/tests/CMakeLists.txt` | Add test executables; link mbedtls for AES-CCM tests |

### Tests to create

| File | What it tests |
|------|---------------|
| `core/tests/test_packet.c` | Header round-trip on little-endian host; big-endian wire bytes match vectors; `SKMESH_VF_MAKE` / `SKMESH_VF_VERSION` etc. |
| `core/tests/test_aes_ccm.c` | Encrypt then decrypt round-trip; known ciphertext from vectors; MIC failure on tampered payload; MIC failure on tampered AAD (8 bytes, excludes hop_limit); nonce construction nonce_ctr = (epoch << 16) or seq; seq wrap triggers epoch increment; NVS write failure halts radio (nonce.nvs_fail); receiver trial: auth with current epoch, fallback to epoch+1; reject lower epoch; hop_limit change does NOT invalidate MIC; type change DOES invalidate MIC |
| `core/tests/test_flood.c` | Insert 64 entries, verify lookup; insert 65th, verify LRU eviction; advance time 30 s, verify expiry; rebroadcast decision with hop_limit 0, 1, 2; jitter in [10, 50] ms range |
| `core/tests/test_ack.c` | Critical event: retry count increments until ACK; normal event: single ACK clears; telemetry: no ACK expected; selective ACK bitmap: set bit N, verify seq N+1+ack_seq acknowledged |
| `core/tests/test_duty_cycle.c` | Use 36,000 ms on g band, verify next send rejected; window slides after 1 hour, budget restored; three-channel independent tracking |
| `core/tests/test_msg_codec.c` | For each of the 8 message types: encode with required fields only, decode and compare; encode with all fields, decode and compare; decode from vector bytes, verify fields |

### Validation (Phase A)

**Core tests including new protocol tests:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**Protogen generates cleanly:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  python3 tools/protogen.py --check
```

**Test vectors round-trip (C and Python agree):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest protocol/tests/ -v"
```

---

## Phase B: Simulator extension

### Goal

Extend the simulator with a `RadioModel` for multi-node delivery,
a `FieldController` class, partition/heal simulation, and duty-cycle
tracking. Write end-to-end multi-node tests for Domination and Bomb
that exercise the flood protocol, TIME sync, score merge after
partition, and reconnect replay. No hardware needed -- everything runs
in the `atalaia-dev` Docker image.

### Files to create

| File | Purpose |
|------|---------|
| `simulator/atalaia_sim/radio_model.py` | `RadioModel`: lossy delivery, airtime calculation, per-node duty-cycle budget, distance-based loss |
| `simulator/atalaia_sim/field_controller.py` | `FieldController`: wraps a virtual node for `field.lua`, TIME beacon sender, score merger, event log, CLAIM election |
| `simulator/atalaia_sim/packet.py` | Python packet codec: header encode/decode, AES-CCM via `cryptography` library, CBOR payloads (uses protogen-generated schemas) |
| `simulator/tests/test_radio_model.py` | RadioModel unit tests: delivery with loss, airtime calculation matches formula, duty-cycle tracking, budget exhaustion |
| `simulator/tests/test_field_controller.py` | FieldController: TIME beacon timing, score merge by maximum, event log ordering, CLAIM election resolution |
| `simulator/tests/test_multi_node.py` | Multi-node Domination: 3 nodes + controller, captures propagate, scores merge correctly |
| `simulator/tests/test_partition.py` | Partition: disconnect node 2, capture continues locally, reconnect, replay events, scores agree |
| `simulator/tests/test_time_sync.py` | TIME beacon reception, slew algorithm converges within 250 ms, step on large offset |
| `simulator/tests/test_duty_cycle_sim.py` | Run a 20-minute 5-node game, verify no node exceeds 1% budget on the g sub-band |
| `simulator/tests/test_flood_sim.py` | Flood delivery: 3-hop chain, dedupe prevents loops, hop_limit=0 stops rebroadcast |
| `simulator/tests/test_failover_sim.py` | CLAIM election: controller goes down, backup elected by priority, new controller sends TIME with higher term, former controller steps down |

### Files to modify

| File | Change |
|------|--------|
| `simulator/atalaia_sim/sim.py` | Add optional `RadioModel`; add `_pending` delivery queue; add `_deliver_pending()` called by `advance_to()`; add `send_packet()` method; add `partition()` / `heal()` / `link()` methods |
| `simulator/atalaia_sim/live.py` | Add `FieldController` to the live web view; show multi-node event propagation |
| `simulator/requirements.txt` | Add `cryptography` (for AES-CCM in Python packet codec) |

### Tests to create

See table above -- 8 new test files exercising multi-node scenarios.

### Validation (Phase B)

**Simulator tests including multi-node:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest simulator/tests/ -v"
```

**Existing mode tests still pass (no regressions):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest modes/ -v"
```

**Duty-cycle compliance test (5-node 20-minute game):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest simulator/tests/test_duty_cycle_sim.py -v"
```

---

## Phase C: Core API additions + ESP32 radio integration

### Goal

Add `state.field{}` and `field.*` to the core Lua API (core version
bump to 0.2.0). Implement the radio HAL (`hal_radio_ops_t` with SX1262
driver, ESP-IDF implementation, stub, and Linux/Pi implementation),
the FreeRTOS radio task, the event buffer, the time sync module, and
wire the packet codec and flood logic into the ESP32 firmware. The HAL
header and stub compile and test on Linux in Docker; the ESP-IDF
implementation cross-compiles in Docker; actual radio testing requires
hardware.

### Files to create

| File | Purpose |
|------|---------|
| `core/include/atalaia/field_ops.h` | `atalaia_field_ops_t` struct: `nodes`, `owner`, `send` callbacks; `atalaia_field_state_t` |
| `core/tests/test_field_api.c` | Tests for `state.field{}` read/write, `field.nodes()`, `field.owner()`, `field.send()` with mock `field_ops` |
| `firmware/esp32/main/hal/hal_radio.h` | `hal_radio_ops_t`, `hal_radio_config_t`, `hal_radio_mode_t` enum |
| `firmware/esp32/main/hal/esp/hal_esp_radio.c` | SX1262 driver via SPI; DIO1 ISR; duty-cycle tracker; channel hopping |
| `firmware/esp32/main/hal/stub/hal_radio_stub.c` | Stub: records send calls, allows injecting received packets, simulates duty-cycle |
| `firmware/esp32/main/radio/radio_task.h` | Radio task API: `radio_task_start()`, TX/RX queue handles |
| `firmware/esp32/main/radio/radio_task.c` | FreeRTOS task on core 0 at priority 3; TX queue drain, RX with DIO1 semaphore, flood rebroadcast |
| `firmware/esp32/main/radio/event_log.h` | Flash-backed append log: `event_log_init()`, `event_log_append()`, `event_log_replay_from()`, `event_log_ack()`, `event_log_compact()` |
| `firmware/esp32/main/radio/event_log.c` | LittleFS `/log/game.bin`; normal and critical events flushed immediately; telemetry buffered in 8-entry DRAM cache (5 s flush); 256 KB limit; compaction of ACK'd entries; `event_log.full` system event |
| `firmware/esp32/main/radio/time_sync.h` | `time_sync_t` struct, `time_sync_on_beacon()`, `time_sync_adjust()` |
| `firmware/esp32/main/radio/time_sync.c` | Linear slew at max 5%/s; step if offset > 500 ms; EMA of last 4 offsets; airtime compensation |
| `firmware/esp32/main/radio/radio_protocol.h` | Glue: packs core events into radio TX queue; unpacks RX packets into `node_runner_input()` |
| `firmware/esp32/main/radio/radio_protocol.c` | Implementation: ACK handling, retry for critical events, STATE periodic send |
| `firmware/esp32/test/test_event_log.c` | Append entries, verify persist to file; replay from seq N; compact ACK'd entries; verify critical flush; power-loss test (destroy, recreate, verify replay); 256 KB overflow test |
| `firmware/esp32/test/test_time_sync.c` | Feed TIME beacons with known offsets; verify slew converges; verify step on 600 ms offset; verify EMA |
| `firmware/esp32/test/test_radio_stub.c` | Send packet via stub, verify recorded; inject RX packet, verify delivered to game_task queue |

### Files to modify

| File | Change |
|------|--------|
| `core/src/script_api.c` | Register `state.field{}` (read-write when `field_ops` set, read-only otherwise) and `field.*` functions (`field.nodes`, `field.owner`, `field.common_owner`, `field.send`, `field.score`) |
| `core/include/atalaia/node.h` | Add `atalaia_field_ops_t *field_ops` to `atalaia_node_config_t`; add `field_state` callback to `atalaia_node_callbacks_t` |
| `core/include/atalaia/version.h` | Bump `ATALAIA_CORE_VERSION` from `"0.1.x"` to `"0.2.0"` |
| `core/CMakeLists.txt` | No new sources (field_ops is header-only + script_api changes) |
| `firmware/esp32/main/hal/hal.h` | Add `const hal_radio_ops_t *radio` pointer to `hal_t`; add `#include "hal_radio.h"` |
| `firmware/esp32/main/node_runner.h` | Add radio send callback field; add `time_sync_t` member; add STATE sender interval |
| `firmware/esp32/main/node_runner.c` | Wire radio events: on core event callback, enqueue to radio TX; on RX, call `node_runner_input()`; call `time_sync_adjust()` in tick loop; send STATE every snapshot interval |
| `firmware/esp32/main/shell.c` | Init radio HAL; start `radio_task`; wire radio RX/TX queues to `node_runner` |
| `firmware/esp32/main/CMakeLists.txt` | Add radio/ source files |
| `firmware/esp32/test/CMakeLists.txt` | Add test executables for event_buffer, time_sync, radio_stub |

### Validation (Phase C)

**Core tests with field API additions:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**ESP32 cross-compile with radio task:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/project" -w /project/firmware/esp32 \
  espressif/idf:v5.3.2 \
  bash -c "idf.py set-target esp32s3 && idf.py build"
```

**Firmware stub integration tests (including radio):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cmake -S /src/firmware/esp32/test -B /tmp/fw-test \
         -DCORE_DIR=/src/core \
         -DCMAKE_BUILD_TYPE=Debug && \
         cmake --build /tmp/fw-test && \
         ctest --test-dir /tmp/fw-test --output-on-failure"
```

---

## Phase D: Field controller

### Goal

Build the Python field controller application (`atalaia-controller`)
and the USB radio modem firmware (a Kconfig build variant of the node
firmware). The modem handles SX1262, AES-CCM, flood/dedupe, and
duty-cycle enforcement on its ESP32-S3. The Python side handles game
lifecycle, REST API, WebSocket stream, MQTT publishing, SQLite
storage, TIME beacons, CLAIM election, and join flow coordination.
The Python controller communicates with the modem over USB serial.
All tests run on Linux in Docker using a mock serial port and
simulator bindings -- no hardware required for Python tests. The
modem firmware cross-compiles in the ESP-IDF Docker image.

### Files to create

| File | Purpose |
|------|---------|
| `firmware/esp32/main/modem/modem_task.c` | USB CDC serial task: receive TX frames from Pi, send RX frames; binary framing (type + len + payload) |
| `firmware/esp32/main/modem/modem_task.h` | Modem task API: `modem_task_start()` |
| `firmware/esp32/main/modem/modem_framing.c` | Frame encode/decode: IDENT, RX, TX, TX_ACK, CMD, STATUS, ERROR |
| `firmware/esp32/main/modem/modem_framing.h` | Frame types and structs |
| `controller/src/__init__.py` | Package init |
| `controller/src/main.py` | Controller entry point: start radio gateway subprocess, connect socket, init FastAPI, start game engine |
| `controller/src/config.py` | Controller configuration: load from `controller.toml` or env vars |
| `controller/src/game.py` | Game lifecycle: create/start/pause/resume/end; node registry; score merge via `atalaia_score_merge` |
| `controller/src/radio_modem.py` | USB serial client to modem (`pyserial`): connect, send TX frames, receive RX frames, binary framing, watchdog ping, reconnect |
| `controller/src/api.py` | FastAPI REST endpoints: 17 routes per spec section 11 |
| `controller/src/ws.py` | WebSocket `/api/v1/stream`: broadcast events, scores, node state to connected GMs |
| `controller/src/mqtt.py` | MQTT publisher: connect to Mosquitto, publish to `field/v1/{game}/...` topics per spec |
| `controller/src/store.py` | SQLite store: games, presets, event log (UNIQUE on game_id+node_id+seq), node registry |
| `controller/src/time_sync.py` | TIME beacon generator: schedule every 30 s (10 s with failover), build TIME payload, send via radio bridge |
| `controller/src/failover.py` | CLAIM election: priority score calculation, term tracking, candidate announcement, step-down |
| `controller/src/join.py` | Join flow: generate game key, build join payload, HMAC-SHA256, NFC card write data, QR base64url, push to node via REST |
| `controller/src/field_node.py` | Wraps `atalaia_node_t` via ctypes for `field.lua`; provides `field_ops` callbacks |
| `controller/tests/conftest.py` | Fixtures: mock radio bridge, test SQLite database, test game |
| `controller/tests/test_game.py` | Game lifecycle: create, start, pause, end; node join; score merge; event dedupe |
| `controller/tests/test_api.py` | REST API: all 17 endpoints with FastAPI TestClient |
| `controller/tests/test_radio_modem.py` | Radio modem: binary frame encode/decode; mock serial port; watchdog ping; reconnect on port drop |
| `controller/tests/test_failover.py` | CLAIM election: two candidates, higher priority wins; term increment; step-down on higher term |
| `controller/tests/test_time_sync.py` | TIME beacon timing: interval respects failover mode; payload fields correct |
| `controller/tests/test_store.py` | SQLite store: CRUD for games, presets, events; dedupe via UNIQUE constraint; event log query by game+time |
| `controller/tests/test_join.py` | Join payload: build, HMAC, verify; NFC card data; QR base64url round-trip |
| `controller/requirements.txt` | fastapi, uvicorn, paho-mqtt, cryptography, pydantic, pyserial |
| `controller/pyproject.toml` | Project metadata, pytest config |

### Files to modify

| File | Change |
|------|--------|
| `controller/README.md` | Replace placeholder with real documentation: architecture, setup instructions, MQTT topics, REST API summary |
| `simulator/atalaia_sim/core.py` | Add `field_ops` support to the ctypes wrapper (new callback types for `nodes`, `owner`, `send`) |

### Validation (Phase D)

**Controller Python tests:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src/controller && pip install -r requirements.txt && \
         python3 -m pytest tests/ -v"
```

**Modem firmware cross-compile:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/project" -w /project/firmware/esp32 \
  espressif/idf:v5.3.2 \
  bash -c "idf.py set-target esp32s3 && \
           idf.py -DCONFIG_ATALAIA_MODEM_MODE=y build"
```

**Controller + simulator integration (multi-node game via Python):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest controller/tests/test_game.py -v"
```

---

## Phase E: GM console + join flow + scoreboard

### Goal

Build the GM console web app (Preact + HTM PWA, no build step), the
NFC/QR join flow end-to-end, and the example MQTT scoreboard. Tests
run in Docker against a mock API (no hardware). The GM console is
served as static files by FastAPI's `StaticFiles` mount.

### Files to create

| File | Purpose |
|------|---------|
| `controller/console/src/index.html` | PWA shell: viewport meta, manifest link, app.js import |
| `controller/console/src/manifest.json` | PWA manifest: name "Atalaia GM", display: standalone, icons |
| `controller/console/src/sw.js` | Service worker: cache static assets, offline fallback |
| `controller/console/src/app.js` | Main app: Preact router, WebSocket connection, global state |
| `controller/console/src/components/field-view.js` | Node map: Leaflet for GPS, draggable on floor plan image; owner colour, battery, link quality |
| `controller/console/src/components/game-control.js` | Start/pause/end buttons, broadcast message, override zone owner, adjust score |
| `controller/console/src/components/preset-builder.js` | Forms from mode parameter schemas; save/copy presets |
| `controller/console/src/components/live-feed.js` | Filterable event stream with alert rules |
| `controller/console/src/components/node-list.js` | Node health table: name, tier, battery, RSSI, last seen, firmware |
| `controller/console/src/components/score-panel.js` | Live score display: per-team totals, score timeline |
| `controller/console/src/components/join-panel.js` | Join flow UI: generate NFC card data, display QR code, push join to node |
| `controller/console/src/lib/preact.module.js` | Vendored Preact ESM bundle (pinned version) |
| `controller/console/src/lib/htm.module.js` | Vendored HTM ESM bundle |
| `controller/console/src/lib/leaflet/ ` | Vendored Leaflet (JS + CSS + images) |
| `controller/console/src/style.css` | Single stylesheet: responsive, dark/light mode |
| `controller/console/src/icons/icon-192.png` | PWA icon 192x192 |
| `controller/console/src/icons/icon-512.png` | PWA icon 512x512 |
| `examples/scoreboard/scoreboard.py` | Python MQTT subscriber: connects to Mosquitto, subscribes to `field/v1/+/score`, prints to stdout, optional curses display |
| `examples/scoreboard/README.md` | Usage: `python3 scoreboard.py --host <controller-ip>` |
| `controller/tests/test_console.py` | Basic checks: index.html parses, all JS files have valid syntax (via `py_mini_racer` or `node --check` if available), manifest.json valid |

### Files to modify

| File | Change |
|------|--------|
| `controller/src/api.py` | Mount `controller/console/src/` as static files at `/console/`; add `POST /api/v1/nodes/{id}/join` endpoint |
| `controller/src/join.py` | Wire NFC card data generation and QR code generation to the REST endpoint |
| `controller/console/README.md` | Replace stub with real documentation |

### Validation (Phase E)

**Console static files serve correctly:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src/controller && pip install -r requirements.txt && \
         python3 -c \"
from fastapi.testclient import TestClient
from src.api import app
c = TestClient(app)
r = c.get('/console/index.html')
assert r.status_code == 200
assert 'Atalaia' in r.text
print('Console serves OK')
\""
```

**Scoreboard example runs against mock broker:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src/examples/scoreboard && \
         python3 -c \"import scoreboard; print('Import OK')\""
```

**All controller tests pass (including console checks):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src/controller && pip install -r requirements.txt && \
         python3 -m pytest tests/ -v"
```

---

## Phase F: Integration, field test, documentation

### Goal

Bring all pieces together end-to-end on real hardware: flash node
firmware to 5 Heltec V4.3 boards, flash modem firmware to a 6th
board, connect it to the Raspberry Pi over USB, deploy the Python
controller, run the GM console, and execute the field test plan
(calibration, CQB, outdoor, and automatic failover). Update
documentation. This phase cannot be completed without LoRa hardware.
Equipment: 6x Heltec WiFi LoRa 32 V4.3 + 1x Raspberry Pi.

### Files to create

| File | Purpose |
|------|---------|
| `docs/phase-2-field-network/FIELD_TEST.md` | Field test runbook: CQB and outdoor test procedures, metrics collection, pass criteria |
| `controller/docs/DEPLOY.md` | Controller deployment guide: Pi setup, Mosquitto install, modem USB connection, controller start |
| `firmware/esp32/docs/RADIO_BRING_UP.md` | Radio bring-up checklist: NEVER power on without antenna; SX1262 SPI verify; FEM GPIO2/GPIO7 toggle; TX/RX loopback; two-board ping; power calibration; duty-cycle verification |

### Files to modify

| File | Change |
|------|--------|
| `firmware/esp32/README.md` | Add radio task section, radio pin assignments, LoRa configuration |
| `controller/README.md` | Final documentation: deployment, MQTT topics, REST API reference |
| `protocol/README.md` | Final documentation: wire format summary, link to RFC-0001 |
| `hardware/field-box/README.md` | Add Heltec V4.3 wiring: SX1262 SPI pins, DIO1, BUSY, RESET, FEM_EN (GPIO2), VFEM_Control (GPIO7) |
| `README.md` (project root) | Update project status: Phase 2 deliverables, field controller, GM console |

### Validation (Phase F)

**Desk-top radio loopback (2 boards):**

Flash firmware to two ESP32 LoRa boards. Board A sends a HELLO; Board
B receives and ACKs. Verify with serial console:

```
Board A serial: TX HELLO seq=1 -> OK
Board B serial: RX HELLO from A seq=1, RSSI=-45
Board B serial: TX ACK seq=1 -> OK
Board A serial: RX ACK for seq=1
```

**Controller + 1 box integration (desk-top):**

Start the Pi controller with the USB modem. Power one ESP32 box. Join via
NFC. Start a Domination game. Press the red button. Verify:

1. `zone.captured` appears in the controller's event log.
2. The GM console shows the capture in the live feed.
3. The MQTT topic `field/v1/{game}/events/zone.captured` receives the
   event.

**Full 5-box field test:**

See the Field Test Plan section below.

---

## Assumptions about Phase 1

| # | Assumption | Source | Phases that depend on it | Impact if wrong |
|---|-----------|--------|--------------------------|-----------------|
| A1 | `hal_t` struct is extensible by adding a `const hal_radio_ops_t *radio` pointer | ADR-P1-1: "Adding a new peripheral follows the same pattern" | C, F | Minor: if `hal_t` is sealed or uses a different pattern, the radio ops struct still works but the integration point changes. Likely a one-line fix. |
| A2 | `node_runner_t` provides `node_runner_input()` for feeding events from external sources | Phase 1 PLAN Phase B; `node_runner.h` line 59 | C | Moderate: if the node runner does not accept external event injection, a new function must be added. The interface is straightforward. |
| A3 | `node_runner_tick(delta_ms)` advances game time and can be intercepted for slew | Phase 1 PLAN Phase B; `node_runner.h` line 53 | C | Low: the slew module wraps the delta before passing it to `node_runner_tick`. Even if the signature changes, the wrapper adapts. |
| A4 | `game_timer_t` is shell-owned and adjustable | ADR-P1-3 | C | Low: time sync adjusts the delta fed to the game timer, not the timer itself. |
| A5 | `config_store` has a radio region setting | Phase 1 PLAN Phase C (`config_store.h`); radio region is listed as a captive-portal field | C | Low: if the config store does not have a region field, Phase 2 adds it. |
| A6 | The core's `atalaia_node_config_t` is extensible with new fields | `core/include/atalaia/node.h` | C | Moderate: adding `field_ops` requires a struct change. If the core API is frozen, Phase 2 must use a side-channel (global or user-data pointer). |
| A7 | `atalaia_node_callbacks_t` is extensible with new callbacks | `core/include/atalaia/node.h` | C | Same as A6. |
| A8 | The `command()` callback mechanism works for routing radio-related commands | ADR-P1-1; Phase 1 `command_dispatch.h` | C | Low: radio commands go through a separate path (direct queue), not through the command dispatcher. |
| A9 | LittleFS is available at `/presets/` and `/modes/` per ADR-P1-4 | ADR-P1-4 | E (CONFIG push stores modes) | Low: the path is a constant; any change is a one-line fix. |
| A10 | FreeRTOS is configured for dual-core with configurable task priorities | ADR-P1-7 | C | Very low: standard ESP-IDF configuration. |
| A11 | The existing `atalaia-dev` Docker image builds the core as a shared library | Existing CI | D (controller links `libatalaia_core.so`) | Low: if the image does not build a `.so`, Phase D adds a CMake target. |
| A12 | ESP-IDF v5.3.2 includes mbedtls with AES-CCM support | Standard ESP-IDF component | A, C | Very low: mbedtls AES-CCM has been in ESP-IDF since v4.x. |

---

## Acceptance criteria

### AC-1: Protocol codec round-trips all 8 message types

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**Expected:** exit 0. Tests in `core/tests/test_msg_codec.c` encode and
decode every message type against test vectors. C and Python codecs
produce identical bytes.

### AC-2: AES-CCM encrypt/decrypt passes known test vectors

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**Expected:** exit 0. Tests in `core/tests/test_aes_ccm.c` verify
encrypt-then-decrypt round-trip, known ciphertext, and MIC failure on
tampered payload and AAD.

### AC-3: Simulator multi-node Domination game completes with correct scores

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest simulator/tests/test_multi_node.py -v"
```

**Expected:** exit 0. A 3-node Domination game with captures,
partition, reconnect and score merge produces the expected final
scores.

### AC-4: Duty-cycle compliance in simulated 5-node 20-minute game

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest simulator/tests/test_duty_cycle_sim.py -v"
```

**Expected:** exit 0. No node exceeds the 1% duty-cycle budget on the
g sub-band. The controller stays within the 10% budget on the g2
sub-band.

### AC-5: Controller REST API serves all 17 endpoints

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src/controller && pip install -r requirements.txt && \
         python3 -m pytest tests/test_api.py -v"
```

**Expected:** exit 0. All 17 REST endpoints return correct status codes
and response shapes.

### AC-6: GM console serves and renders without errors

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src/controller && pip install -r requirements.txt && \
         python3 -m pytest tests/test_console.py -v"
```

**Expected:** exit 0. `index.html` loads, JS files parse, manifest is
valid, WebSocket endpoint connects.

### AC-7: ESP32 firmware cross-compiles with radio task

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/project" -w /project/firmware/esp32 \
  espressif/idf:v5.3.2 \
  bash -c "idf.py set-target esp32s3 && idf.py build"
```

**Expected:** exit 0. Produces `build/atalaia_esp32.bin` with radio
task, packet codec, AES-CCM, flood, time sync, event buffer.

### AC-8: Partition recovery -- zero lost captures in simulation

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest simulator/tests/test_partition.py -v"
```

**Expected:** exit 0. A node partitioned for 5 minutes replays its
buffered events on reconnect. Every `zone.captured` event reaches the
controller's event log. Scores match.

### AC-9: Failover election completes in simulator

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cd /src && python3 -m pytest simulator/tests/test_failover_sim.py -v"
```

**Expected:** exit 0. Controller goes down, backup is elected by
priority, new controller sends TIME with higher term, game continues.

### AC-10: Field test gate -- 5 boxes, zero lost captures (hardware required)

Execute the Field Test Plan below. Every `zone.captured` event
generated by any box reaches the controller's SQLite event log. Zero
lost captures across both CQB and outdoor tests.

---

## Field Test Plan

### Objective

Validate the Phase 2 gate: "5 boxes on a CQB site and an outdoor
field, with zero lost captures."

### Equipment

- 6x Heltec WiFi LoRa 32 V4.3 high-power (863-928 MHz, ESP32-S3R2,
  SX1262 + FEM): 5 as field boxes with arcade buttons and battery
  packs, 1 as the controller's USB radio modem
- 1x Raspberry Pi 4 (or Pi 5), with a power bank
- 1x USB-A to USB-C cable (Pi to modem board)
- 1x phone/tablet for GM console
- 1x laptop for serial monitoring and data collection

### Pre-test calibration

Before the first field test, measure the actual RF output power of one
board using a spectrum analyser or calibrated RF power meter:

1. Connect the board to the power meter via an SMA adapter (not an
   antenna).
2. Set SX1262 output to 0 dBm (the EU868 g-band setting with FEM).
3. Measure the total output. Expected: ~14 dBm (0 + 14 dB FEM gain).
4. If the measurement differs by more than 2 dB from the expected
   value, adjust `EU868_FEM_GAIN_DB` in Kconfig and rebuild.
5. Record the calibrated value in the test report.

If no RF power meter is available, use the default `EU868_FEM_GAIN_DB
= 14` and note "uncalibrated" in the test report. The 14 dB figure
comes from the V4.3 datasheet (28 dBm output at ~14 dBm SX1262 input).

### Test 0: Enable automatic failover

After the main field tests pass with manual failover:

1. Enable `failover_mode = auto` in the field profile.
2. Run a 10-minute Domination game.
3. At minute 5, power off the Pi (controller death).
4. Verify the modem's USB serial disconnects and the GM console shows
   `radio.down`.
5. Power on a second Pi with a second modem (or promote a node box).
6. Verify the CLAIM election completes within 35 seconds, the new
   controller sends TIME with a higher term, and the game resumes.
7. Verify zero lost captures across the failover.

**Pass criteria for automatic failover:**
- Election completes within 40 seconds of controller death.
- All nodes follow the new term.
- Zero lost captures.

### Test 1: CQB / indoor site

**Site:** An indoor CQB venue (warehouse, palacete or similar), thick
walls, 5 rooms across 2 floors. Maximum dimension ~100 m.

**Setup:**
1. Place the controller (Pi) at the staging area near the entrance.
2. Place 5 boxes in different rooms, at least 2 behind thick walls
   from the controller, at least 1 on a different floor.
3. Field profile: CQB (SF7, 10 s snapshot interval).
4. Join all 5 boxes via NFC.
5. Start a Domination game with a 15-minute timer.

**Test procedure:**
1. Walk between boxes pressing team buttons to simulate a real game.
   Generate at least 30 captures across all 5 boxes.
2. After 5 minutes, pull the battery from box 3 mid-capture (simulate
   a battery death during play), wait 2 minutes, then reconnect power
   (power-loss + rejoin + event replay test). Box 3 must rejoin
   automatically using the persisted game key and a new epoch, without
   needing a new NFC tap.
3. At minute 10, move box 5 to the farthest room from the controller
   (worst-case range test).
4. Continue capturing until the game ends.

**Metrics to collect:**
- Total captures generated (count button presses on each box via
  serial log).
- Total captures received by the controller (query
  `SELECT COUNT(*) FROM events WHERE type='zone.captured'`).
- Delivery rate: received / generated (target: 100%).
- Per-event latency: `received_at - game_time` for each capture.
- Time sync accuracy: max |node_game_time - controller_game_time|
  across all STATE messages (target: <250 ms).
- Duty-cycle usage: per-node airtime from radio HAL logs (target: <80%
  of budget).
- Battery drain: before/after battery percentage on each box.
- RSSI per box at controller (from STATE messages).
- Reconnect replay: number of events replayed by box 3 after power-on.
- Epoch change: verify box 3's HELLO after reboot shows epoch+1.
- Auto-rejoin: verify box 3 did NOT require a new NFC tap.

**Pass criteria:**
- Zero lost captures: every `zone.captured` event from every box is in
  the controller's event log, including events from box 3 that were
  in its flash log before the battery pull.
- Box 3's flash-logged events are all replayed after reconnect.
- Box 3 rejoined with epoch+1 and no NFC re-tap.
- Time sync accuracy <250 ms for all boxes that received at least 3
  TIME beacons.
- No duty-cycle violation on any node.

### Test 2: Outdoor field

**Site:** An open outdoor airsoft/paintball field, minimal cover, at
least 300 m across. Trees and brush but no thick walls.

**Setup:**
1. Place the controller (Pi) at the staging area.
2. Place 5 boxes spread across the field: 2 within 100 m of the
   controller, 2 at 150-250 m, 1 at the farthest accessible point
   (300+ m).
3. Field profile: Small outdoor (SF9, 30 s snapshot interval).
4. Join all 5 boxes via NFC.
5. Start a Domination game with a 20-minute timer.

**Test procedure:**
1. Walk between boxes pressing team buttons. Generate at least 40
   captures across all 5 boxes.
2. At minute 5, place an obstacle (body, vehicle) between the
   farthest box and the controller to test relay through intermediate
   boxes.
3. At minute 10, bring a 6th box online as a dedicated repeater between
   the controller and the farthest box (if the farthest box has
   intermittent connectivity).
4. Continue capturing until the game ends.

**Metrics to collect:**
- Same metrics as the CQB test.
- RSSI at each distance point.
- Packet loss rate at the farthest box (from radio HAL TX/RX counters).
- Relay effectiveness: how many packets reached the controller only
  via relay (hop_limit decremented).

**Pass criteria:**
- Zero lost captures: every `zone.captured` event from every box is in
  the controller's event log.
- The farthest box at 300+ m delivers all captures (directly or via
  relay).
- Time sync accuracy <250 ms for all boxes.
- No duty-cycle violation on any node.

### Post-test analysis

After each test:

1. Export the controller's event log:
   `GET /api/v1/games/{id}/log > game_log.json`

2. Export each box's serial log (captured during the test).

3. Cross-reference: for each `zone.captured` in the serial logs, verify
   it exists in `game_log.json` with a matching `(node_id, seq)`.

4. Compute delivery latency distribution (median, P95, P99).

5. Compute time sync accuracy over the game duration.

6. Record RSSI map (box position vs RSSI at controller).

7. Record duty-cycle usage per node.

8. If any captures are lost: identify root cause (radio, duty-cycle,
   dedupe, buffer overflow, ACK failure) from the serial logs and radio
   HAL counters.

### Gate decision

The Phase 2 gate is met when both tests (CQB and outdoor) pass with
zero lost captures. If the farthest outdoor box cannot deliver at
300+ m, a dedicated repeater box at the midpoint is an acceptable
solution (the protocol supports this natively).

---

## Phase dependency graph

```
Phase A ──> Phase B ──> Phase C ──> Phase F
  │           │           │
  │     (radio model)  (radio HAL + modem firmware)
  │           │           │
  │           └─> Phase D ┘
  │                 │
  │           Phase E ──> Phase F
  │             │
  └─────────────┘
       RFC accepted; no review wait
```

Phase A must complete first (protocol codecs are a prerequisite for
everything). RFC-0001 is accepted; implementation begins immediately.
Phase B (simulator) and Phase C (ESP32 radio + modem firmware) can
proceed in parallel after Phase A, but Phase B should complete first
to validate the protocol design before ESP32 integration. Phase D
(controller + modem firmware) depends on the core API additions from
Phase C and the simulator bindings. Phase E (console, join, scoreboard)
depends on Phase D's REST API. Phase F ties everything together on
hardware and executes the field test (including the calibration step
and the automatic failover test).

---

## Summary of new files by directory

```
protocol/
    rfc/
        RFC-0001.md
    vectors/
        header.json
        aes_ccm.json
        hello.json  ack.json  state.json  cmd.json
        time.json  config.json  claim.json

core/
    include/atalaia/
        packet.h
        flood.h
        ack.h
        duty_cycle.h
        msg_codec.h
        field_ops.h
    src/
        packet.c
        flood.c
        ack.c
        duty_cycle.c
        msg_codec.c
    tests/
        test_packet.c
        test_aes_ccm.c
        test_flood.c
        test_ack.c
        test_duty_cycle.c
        test_msg_codec.c
        test_field_api.c

firmware/esp32/
    main/
        hal/
            hal_radio.h
            esp/
                hal_esp_radio.c
            stub/
                hal_radio_stub.c
        radio/
            radio_task.h    radio_task.c
            event_log.h     event_log.c
            time_sync.h     time_sync.c
            radio_protocol.h  radio_protocol.c
        modem/
            modem_task.h    modem_task.c
            modem_framing.h modem_framing.c
    test/
        test_event_log.c
        test_time_sync.c
        test_radio_stub.c
    docs/
        RADIO_BRING_UP.md

controller/
    src/
        __init__.py
        main.py   config.py   game.py
        radio_modem.py   api.py   ws.py
        mqtt.py   store.py   time_sync.py
        failover.py   join.py   field_node.py
    console/
        src/
            index.html   manifest.json   sw.js
            app.js   style.css
            components/
                field-view.js   game-control.js
                preset-builder.js   live-feed.js
                node-list.js   score-panel.js
                join-panel.js
            lib/
                preact.module.js   htm.module.js
                leaflet/
            icons/
                icon-192.png   icon-512.png
    tests/
        conftest.py
        test_game.py   test_api.py
        test_radio_modem.py   test_failover.py
        test_time_sync.py   test_store.py
        test_join.py   test_console.py
    requirements.txt
    pyproject.toml
    docs/
        DEPLOY.md

simulator/
    atalaia_sim/
        radio_model.py
        field_controller.py
        packet.py
    tests/
        test_radio_model.py
        test_field_controller.py
        test_multi_node.py
        test_partition.py
        test_time_sync.py
        test_duty_cycle_sim.py
        test_flood_sim.py
        test_failover_sim.py

examples/
    scoreboard/
        scoreboard.py
        README.md

docs/
    phase-2-field-network/
        FIELD_TEST.md
```

Total: ~90 new files across protocol, core, firmware, controller,
simulator and examples. Modified files: ~15 (messages.yaml,
protogen.py, core CMakeLists, hal.h, node_runner, shell.c, sim.py,
live.py, READMEs).
