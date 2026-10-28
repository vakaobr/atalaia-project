<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 2 -- Field Network: Status

**Current phase:** Implementation (plan phases A to E complete in software; F needs the radio boards; a mode pack was added to phase 2 by the maintainer)
**Risk level:** High
**Last verified:** 2026-10-18

## Completed

- [x] Research phase: `RESEARCH.md`
- [x] Architecture decisions: `ADR.md` (15 ADRs, 29 planning constraints)
- [x] Implementation plan: `PLAN.md` (6 phases, 10 acceptance criteria, field test plan)
- [x] RFC-0001 accepted (2026-10-17)
- [x] Phase 1 assumption check: 11 of 12 hold; A5 uses contingency
- [x] Phase A: Protocol codecs (packet, flood, ACK, duty-cycle, msg_codec, crypto_mbedtls)
- [x] Phase A: protogen extended (payload schemas, packet vector generation)
- [x] Phase A: Shared test vectors (C and Python verify the same JSON files)
- [x] Phase A: RFC 3610 known-answer AES-CCM test (C mbedtls + Python cryptography)
- [x] Phase A: Mutation tests for all decoders (packet header, 7 payload types)
- [x] Phase B: RadioModel, FieldController, Python packet codec, sim.py integration
- [x] Phase B: 9 simulator test files (all pass, 0 skipped in CI)
- [x] No firmware regression (ESP-IDF build passes, 87% slot usage, 13% free)
- [x] No silent skips (ATALAIA_REQUIRE_ALL=1 in check.sh and CI)
- [x] Phase C: Core field_ops API (state.field{} read-write/read-only, field.nodes/owner/send/score/common_owner)
- [x] Phase C: Core version bumped to 0.2.0
- [x] Phase C: Radio HAL (hal_radio_ops_t, SX1262 driver on SPI3, stub for tests)
- [x] Phase C: FEM gain accounting (14 dB), EU868 single shared game channel (default 869.525 MHz g2), duty-cycle tracking (g2 10%)
- [x] Phase C: Radio task (FreeRTOS core 0 priority 3, TX/RX queues)
- [x] Phase C: Flash event log (LittleFS, immediate flush for normal/critical, telemetry cache)
- [x] Phase C: Time sync by slew (max 5%/s, step above 500 ms)
- [x] Phase C: Radio protocol glue (packet encode/decode, epoch/nonce safety)
- [x] Phase C: Partition table grown (OTA 1.5 -> 2 MB, nvs_keys added)
- [x] Phase C: Wokwi passes with the radio enabled. The earlier "SPI3 probe corrupts Wokwi flash" disable was a real driver bug (an unbounded BUSY wait on a floating GPIO 13), now fixed with a ~200 ms timeout
- [x] Phase C: Phase A core sources (packet, flood, ack, duty_cycle, msg_codec, crypto_mbedtls) wired into IDF component
- [x] Phase C: Radio protocol tests (10 tests: boot epoch, NVS failure, seq wrap, epoch exhaustion, receiver epoch trial)
- [x] Phase C: TX power calculation tests (6 tests: g-band, g2-band, no FEM, high-gain antenna, clamp low/high)
- [x] Phase C: NVS encryption documented (eFuse HMAC scheme; BRING_UP.md step 0)
- [x] Phase C: Documentation updated (firmware README, BRING_UP.md, hardware README, core README, CHANGELOG)
- [x] Radio channel fix (2026-10-18): replaced three-channel round-robin hopping with a single shared game channel (default 869.525 MHz, g2 sub-band, 10% DC, 500 mW ERP). RFC 0001 Amendment 1; ADR-P2-13 superseded in part.
- [x] Phase D: Python field controller `controller/atalaia_controller` (engine, SQLite store, REST API v1 with all 17 plan endpoints plus status/promote/healthz, WebSocket stream, MQTT bridge to Mosquitto, field.lua in the core, restart recovery)
- [x] Phase D: USB modem framing (sync byte + CRC-16, protocol/usb-modem.md), serial client with ping watchdog, reconnect and radio.down/radio.up
- [x] Phase D: USB radio modem firmware variant (`sdkconfig.modem`, `main/modem/`), 0 warnings; modem logic unit-tested on the host and built as a Linux host modem for the controller's integration tests
- [x] Phase D: CLAIM election shared by the simulator and the controller (`atalaia_sim/election.py`), failover tested over the radio model (detection, priority, ties, manual promote, step-down, scores across the takeover)
- [x] Phase D: core payload codec made schema-exact (it disagreed with the shared vectors for HELLO, STATE, CMD, TIME and CLAIM; the vector tests had skipped it); strict vector tests in C and Python, invalid vectors rejected
- [x] Phase D: radio HAL `sx_wait_busy()` returns an error that every caller propagates; "SX1262 not detected" reported cleanly; debug-step logs at debug level
- [x] Phase E: join payload format (`protocol/join.md`, RFC 0001 Amendment 2): version byte, CBOR body, HMAC-SHA256 with a field join key; NFC NDEF and `atalaia:join:` text forms; C codec with its own SHA-256/HMAC and Python codec, both strict against `protocol/vectors/join.json` (4 valid, 34 invalid, RFC 4231 HMAC known answers)
- [x] Phase E: controller join flow: `POST /api/v1/join`, `POST /api/v1/nodes/{id}/join`, field join key (`join-key`, `[join] key`), store schema 2
- [x] Phase E: standby controller (closes D17): `POST /api/v1/controller/join`, follows TIME, logs the game, leaves at the end, takes over when promoted; tested over the air with two C host modems
- [x] Phase E: GM console (Preact + HTM PWA, no build step, pt-PT/en, strict CSP), served at `/console/`; read-only scoreboard page at `/scoreboard`; `examples/scoreboard/scoreboard.py` (MQTT)
- [x] Phase E: Field Box on the radio (closes D18): `main/radio/field_link.c` (events with ACK and retry, HELLO, STATE, TIME with time sync and leader by term, CMD, ACK, relay) and `main/box_game.c` (join by NFC card or serial console, NVS storage, the mode run with the join's node id, seed, teams and params, end and key erase, rejoin after a reboot)
- [x] Phase E: host box (`firmware/esp32/test/box_host`): the box's code on Linux; end-to-end tests with the controller and the host modem over a shared UDP air (join, play, scores, battery pull, end, relay through another box, wrong field key)
- [x] Phase E: browser tests (Playwright, headless Chromium, Docker image `tools/dev/console/Dockerfile`, `python tools/docker_console.py`, CI job `console`)
- [x] Phase E: Wokwi join scenario (`wokwi/join.scenario.yaml`), radio enabled
- [x] Field radio channel (2026-10-18, RFC 0001 Amendment 3, decisions CH1-CH13): 869.525 MHz stays the default because it is the centre of 869.4-869.65 MHz, the only EU868 sub-band with 10% duty cycle and 500 mW ERP (elsewhere 1% or 0.1% at 25 mW; 868.1/868.3/868.5 MHz are LoRaWAN's busy default channels; LoRaWAN downlinks and Meshtastic's EU default share 869.525 MHz). The GM chooses the field's channel in the console (keep it, scan for a quiet one with the USB modem's new MEASURE command, random, or by hand), kept by the controller and sent to the modem and in join payloads; locked while a game exists. The whole 125 kHz channel must fit in one sub-band (fixes 869.40 MHz being accepted); boxes, the modem and the simulator take the duty-cycle budget and TX power from the channel's sub-band (they had g2's 10% and 500 mW fixed); LoRa time on air instead of a rough estimate; SX1262 sync word corrected to private (0x1424). Join vectors now 4 valid, 38 invalid. Not yet checked on hardware: the RSSI and CAD readings of a real SX1262, and the quiet threshold
- [x] Phase E: Heltec V4 front end fixed: the FEM's LDO (GPIO 7) was held low; now powered after the SX1262 probe, per board revision (Kconfig: V4.3 KCT8103L default, V4.2 GC1109), sequence tested on the host; button 2 moved from GPIO 5 to 39; Vext switched on at boot; GPS not supported in the pin map (decisions E17-E22)

## Verification (2026-10-18, Phase C -- final)

```
sh tools/check.sh                            exit 0
  protogen --check                           OK
  build_site.py --check                      OK
  format --check                             OK
  cmake build (core 0.2.0)                   OK (0 warnings, -Werror)
  ctest                                      1/1 passed
  simulator unittest                         108 tests, 0 skipped
  mode tests                                 12/12 passed
Core ASan+UBSan                              exit 0, 0 sanitizer errors
ESP-IDF build (Field Box)                    exit 0 (0x14f190 = 1,373 KB, 35% free in 2 MB OTA slot)
ESP-IDF build (Wokwi)                        exit 0 (0x14f190 = 1,373 KB, 35% free in 2 MB OTA slot)
firmware stub tests                          2/2 passed (incl. 10 radio protocol + 6 TX power tests)
Wokwi bomb scenario                          "Scenario completed successfully"
reuse lint                                   exit 0 (compliant)
```

## Shared test vectors

Both the C codec (via generated `core/tests/packet_vectors.h`) and the Python
codec (via `protocol/vectors/*.json` loaded at test time) verify the same
vectors for: header (4 valid + 2 invalid), HELLO (2+2), ACK (2+1), STATE
(2+1), CMD (2+1), TIME (2+1), CONFIG (2+1), CLAIM (2+1), and AES-CCM
(5 vectors with real ciphertext: basic, seq_wrap, epoch_increment,
hop_limit_one, empty_payload).

Published known-answer: RFC 3610 section 8, Packet Vector 1 (AES-128-CCM,
13-byte nonce, 8-byte tag). Tested in C (`test_crypto_mbedtls.c`) and Python
(`test_packet.py::RFC3610Tests`).

## Crypto backend

`atalaia_crypto_ops_t` function-pointer interface:
- **Test stub** (`atalaia_crypto_test_stub`): XOR + FNV-1a. Tests framing only.
- **mbedtls** (`atalaia_crypto_mbedtls`): Real AES-128-CCM. Built when
  `libmbedcrypto` found by CMake. Known-answer tested against RFC 3610.
- **ESP32**: firmware provides mbedtls via IDF component.
- **Python**: `cryptography` library (required in CI, optional locally).

## Verification (2026-10-18, Phase D)

```
sh tools/check.sh (ATALAIA_REQUIRE_ALL=1)    exit 0
  protogen --check, build_site --check       OK
  format --check (clang-format, StyLua)      OK
  core ctest                                 1/1 passed (strict payload vectors)
  simulator unittest                         153 tests, 0 skipped
  mode tests                                 12/12 passed
  controller unittest                        63 tests, 0 skipped (C host modem, mosquitto)
Core ASan+UBSan                              exit 0
firmware stub tests                          2/2 (firmware_test: 812 checks; screens)
firmware tests + host modem under ASan/UBSan clean (extra, not a CI job)
ESP-IDF build (Field Box, clean sdkconfig)   exit 0, 0 warnings, 0x14f660 bytes (34% of the 2 MB slot free)
ESP-IDF build (Wokwi)                        exit 0, 0 warnings, 0xdf6c0 bytes
ESP-IDF build (USB modem)                    exit 0, 0 warnings, 0x46560 bytes (86% of the slot free)
Wokwi bomb scenario (radio enabled)          "Scenario completed successfully";
                                             log: "SX1262 not detected (BUSY stuck high after reset)"
reuse lint                                   exit 0
```

## Verification (2026-10-18, Phase E)

```
sh tools/check.sh (ATALAIA_REQUIRE_ALL=1)    exit 0
  protogen --check, build_site --check       OK
  format --check (clang-format, StyLua)      OK
  core ctest                                 1/1 passed (incl. join vectors and HMAC)
  simulator unittest                         167 tests, 0 skipped
  mode tests                                 12/12 passed
  controller unittest                        90 tests, 0 skipped (C host modem, C host box, mosquitto)
Core ASan+UBSan                              exit 0
firmware stub tests (docker_fw.py test)      2/2 (firmware_test: 1110 checks; screens)
  under ASan/UBSan (extra)                   1110 checks; host box + host modem end-to-end 3/3, join 9/9
browser tests (docker_console.py)            10 tests, headless Chromium, 0 skipped
ESP-IDF clean builds, 0 warnings             Field Box 0x15a9a0 (32% of the 2 MB slot free),
                                             Wokwi 0xed810, USB modem 0x469e0
Wokwi bomb and join scenarios (radio on)     "Scenario completed successfully" (both)
tools/check_wiring.py, docker_hw.py check    pin table, wiring diagrams and Kconfig agree
reuse lint                                   compliant (522/522 files)
```

## What is real and what is not yet

- Real and tested: the controller end to end in Docker (engine, store, API, WebSocket, MQTT with a real Mosquitto) talking to the modem's real C code (framing, AES-CCM with mbedtls, dedupe, epoch window, nonce guard) over pyserial's socket://; the election in the simulator; the modem firmware compiles for the ESP32-S3.
- Real and tested since phase E: the box's game and radio code (`box_game.c`, `field_link.c`, the node runner, the core, mbedtls) as a Linux program playing whole games against the controller and the C modem over a shared UDP air, including a battery pull and a box heard only through another box's relay; the join payload in C and Python against shared vectors; the standby controller over the air; the GM console and scoreboard in headless Chromium against the real controller; the join from the serial console in the Wokwi emulator.
- Not run yet: any of it on the radio boards: the modem firmware on a board (USB-Serial-JTAG link, radio timing, duty cycle on air), the controller on a Raspberry Pi, the SX1262 link between boxes, the PN532 reading real NTAG cards (the code is written from the public PN532 manual, never run on a reader), NVS encryption on a provisioned box.
- Not built: joining a box over Wi-Fi from the console (decision E3: boxes join by NFC card or serial console; QR codes are for phones in phase 3), Leaflet/OSM maps (E5), penalties in the box counters (E6; built 2026-10-28 as STATE key 9, RFC 0001 Amendment 17, decision BSC-1).
- Added to phase 2 by the maintainer (2026-10-18): a mode pack (Hold-All Domination, Last Stand, per-team arming codes on Bomb, the Codes modifier), not started.

## Mode pack (decision R6)

- [x] Hold-All Domination (modes/holdall: node.lua captures; field.lua on the controller scores while one team holds every zone; min_zones)
- [x] Last Stand (modes/laststand: defenders start with every zone; countdown while they hold last_zones or fewer; reset or carry on; end_game -> attackers win)
- [x] Bomb per-team codes (team_codes; the keypad replaces the buttons; reason: code); the old Bomb behaviour is unchanged
- [x] Codes modifier (modes/codes, kind: modifier; points, hint, unlock; code.used with holder); "main+modifier" composition in the simulator, the controller and the Field Box
- [x] Events 28-32 and data fields duration_s (28) and holder (31); manifest i18n (pt); console modifier picker
- [x] Field Box: code_entry template, five built-in presets added and refreshed at boot, 16 KB preset scripts, composed joins

Not run: on radio boards; Last Stand end to end with host boxes (simulator and engine tests only); QR codes for Codes (they need the phase 3 apps). Decisions K1-K15 in docs/review/decisions-to-review.md.

## Verification (2026-10-18, mode pack, clean copy)

```
sh tools/check.sh (ATALAIA_REQUIRE_ALL=1)   exit 0: simulator 180, modes 28/28, controller 97, 0 skipped; wiring check OK
Core ASan+UBSan                              exit 0, 0 warnings
firmware host tests                          2/2 passed
GM console browser tests                     exit 0
ESP-IDF Field Box                            exit 0, 0 warnings, 0x15da90 (V4.3 default, PCF8574 keypad, no skip flags)
ESP-IDF Wokwi / modem                        exit 0, 0 warnings, 0xf08b0 / 0x469e0
Wokwi bomb, join, codes (radio enabled)      "Scenario completed successfully" x3
reuse lint                                   611/611 files compliant
```

## Next

- Phase F, when the boards arrive: flash 5 boxes and a modem, bring-up (BRING_UP.md steps 7 and 10b for NFC and field games), calibration, the CQB and outdoor field tests.

## Plan summary

| Phase | Scope | Status |
|-------|-------|--------|
| A | Protocol codecs, RFC-0001, protogen, test vectors | Complete |
| B | Simulator: RadioModel, FieldController, multi-node tests | Complete |
| C | Core API (field_ops), radio HAL, ESP32 radio task, time sync, event log | Complete |
| D | Python controller, USB modem framing, REST, MQTT, SQLite, failover | Complete (software; hardware in F) |
| E | GM console (Preact+HTM PWA), join flow (NFC+QR), scoreboard; boxes on the radio (D18) | Complete (software; NFC reader and radio in F) |
| F | Hardware integration, calibration, field test, documentation | Pending |

## Acceptance criteria

| # | Criterion | Status |
|---|-----------|--------|
| AC-1 | Protocol codec round-trips all 8 message types | Met (C + Python, shared vectors) |
| AC-2 | AES-CCM encrypt/decrypt passes known vectors | Met (RFC 3610 + 5 packet vectors) |
| AC-3 | Simulator multi-node game correct scores | Met |
| AC-4 | Duty-cycle compliance in sim | Met |
| AC-5 | Controller REST API serves all 17 endpoints | Met (`controller/tests/test_api.py`, real app, real engine) |
| AC-6 | GM console serves and renders | Met (`test_console.py`; browser tests in headless Chromium) |
| AC-7 | ESP32 firmware cross-compiles with radio | Met |
| AC-8 | Partition recovery zero lost captures in sim | Met |
| AC-9 | Failover election in simulator | Met |
| AC-10 | Field test 5 boxes zero lost captures | Phase F |

## A scenario's setup commands, sent again until the box confirms (2026-10-28, decisions PKB-1 to PKB-3)

Built (software, the simulator's radio model; **not run on the radio**): the scenario's runtime sends each box's `setup` again after 8, 16, 32, 64 and 128 s until the box says `node.setup_applied` (new standard event id 56, `kind`; RFC 0001 Amendment 16), five repeats at most, each carrying the state the runtime knows then (idempotent), and the objectives package says it each time it takes a setup. A box that never says it (an older firmware) gets the five repeats and no more. Tests: `simulator/tests/test_scenario.py` (a lost setup sent again and then stopped by the confirmation, the bounded fallback, a repeat that never takes back what happened since), `controller/tests/test_scenarios.py` (the same on the compiled Foxhound package), `firmware/esp32/test/test_builtin_presets.c`, the event's vector in C and Python.

Measured with `python -m atalaia_sim.relay_report --setup-study --seeds 1,2,3,4,5` (the Foxhound scenario, EU868, the built rules `A_backoff` and `H_paced`, 90 minutes; every cell the median over five seeds; the traffic is the real core's, the events and CMDs of `relay_traces.py`). "one shot" is the controller before this work and reproduces SL-13's table 7; "re-sent 5 times" repeats without a box ACK (what an older firmware gets); "re-sent until the box's ACK" is the built behaviour. *Reaching their box* counts each setup command once (the first time its box hears any copy of it), *known to the scenario* those whose `node.setup_applied` the controller heard.

| layout | N | rule | setup commands | reaching their box % | known to the scenario % | time to reach p50 s | p95 s | CMD frames per setup | box confirmations (events) | controller air % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all in range | 10 | A_backoff | one shot (before PKB-3) | 66.7 | 0.0 | 0.2 | 0.5 | 1.0 | 0 | 0.3 |
| all in range | 10 | A_backoff | re-sent 5 times, no box ACK | 100.0 | 0.0 | 0.5 | 57.6 | 6.0 | 0 | 0.5 |
| all in range | 10 | A_backoff | re-sent until the box's ACK | 100.0 | 100.0 | 0.5 | 57.6 | 1.8 | 9 | 0.3 |
| all in range | 10 | H_paced | one shot (before PKB-3) | 77.8 | 0.0 | 0.8 | 2.3 | 1.0 | 0 | 0.3 |
| all in range | 10 | H_paced | re-sent 5 times, no box ACK | 100.0 | 0.0 | 3.0 | 11.4 | 6.0 | 0 | 0.5 |
| all in range | 10 | H_paced | re-sent until the box's ACK | 100.0 | 100.0 | 2.8 | 57.3 | 1.7 | 9 | 0.3 |
| all in range | 20 | A_backoff | one shot (before PKB-3) | 44.4 | 0.0 | 0.2 | 0.7 | 1.0 | 0 | 0.3 |
| all in range | 20 | A_backoff | re-sent 5 times, no box ACK | 100.0 | 0.0 | 8.7 | 58.4 | 6.0 | 0 | 0.5 |
| all in range | 20 | A_backoff | re-sent until the box's ACK | 100.0 | 100.0 | 8.9 | 57.4 | 2.1 | 9 | 0.4 |
| all in range | 20 | H_paced | one shot (before PKB-3) | 44.4 | 0.0 | 0.9 | 2.1 | 1.0 | 0 | 0.3 |
| all in range | 20 | H_paced | re-sent 5 times, no box ACK | 100.0 | 0.0 | 8.6 | 60.8 | 6.0 | 0 | 0.5 |
| all in range | 20 | H_paced | re-sent until the box's ACK | 100.0 | 100.0 | 8.8 | 57.6 | 2.0 | 9 | 0.4 |
| all in range | 30 | A_backoff | one shot (before PKB-3) | 22.2 | 0.0 | 0.3 | 0.4 | 1.0 | 0 | 0.4 |
| all in range | 30 | A_backoff | re-sent 5 times, no box ACK | 88.9 | 0.0 | 25.3 | 121.9 | 6.0 | 0 | 0.5 |
| all in range | 30 | A_backoff | re-sent until the box's ACK | 88.9 | 88.9 | 9.1 | 250.4 | 2.8 | 8 | 0.4 |
| all in range | 30 | H_paced | one shot (before PKB-3) | 22.2 | 0.0 | 1.1 | 1.7 | 1.0 | 0 | 0.4 |
| all in range | 30 | H_paced | re-sent 5 times, no box ACK | 100.0 | 0.0 | 10.1 | 121.8 | 6.0 | 0 | 0.5 |
| all in range | 30 | H_paced | re-sent until the box's ACK | 100.0 | 100.0 | 10.4 | 249.9 | 2.8 | 9 | 0.5 |
| long field | 10 | A_backoff | one shot (before PKB-3) | 66.7 | 0.0 | 0.3 | 0.7 | 1.0 | 0 | 0.3 |
| long field | 10 | A_backoff | re-sent 5 times, no box ACK | 100.0 | 0.0 | 0.5 | 122.2 | 6.0 | 0 | 0.5 |
| long field | 10 | A_backoff | re-sent until the box's ACK | 100.0 | 100.0 | 9.1 | 121.9 | 2.6 | 9 | 0.4 |
| long field | 10 | H_paced | one shot (before PKB-3) | 66.7 | 0.0 | 0.9 | 3.0 | 1.0 | 0 | 0.3 |
| long field | 10 | H_paced | re-sent 5 times, no box ACK | 100.0 | 0.0 | 2.5 | 24.8 | 6.0 | 0 | 0.5 |
| long field | 10 | H_paced | re-sent until the box's ACK | 100.0 | 100.0 | 1.2 | 26.3 | 1.4 | 9 | 0.3 |
| long field | 20 | A_backoff | one shot (before PKB-3) | 0.0 | 0.0 | 0.7 | 0.9 | 1.0 | 0 | 0.5 |
| long field | 20 | A_backoff | re-sent 5 times, no box ACK | 55.6 | 0.0 | 26.4 | 251.6 | 6.0 | 0 | 0.7 |
| long field | 20 | A_backoff | re-sent until the box's ACK | 55.6 | 55.6 | 58.0 | 251.7 | 5.0 | 5 | 0.6 |
| long field | 20 | H_paced | one shot (before PKB-3) | 22.2 | 0.0 | 1.2 | 1.2 | 1.0 | 0 | 0.5 |
| long field | 20 | H_paced | re-sent 5 times, no box ACK | 66.7 | 0.0 | 26.3 | 122.5 | 6.0 | 0 | 0.6 |
| long field | 20 | H_paced | re-sent until the box's ACK | 55.6 | 55.6 | 25.9 | 251.1 | 4.7 | 5 | 0.6 |
| long field | 30 | A_backoff | one shot (before PKB-3) | 0.0 | 0.0 | - | - | 1.0 | 0 | 0.8 |
| long field | 30 | A_backoff | re-sent 5 times, no box ACK | 11.1 | 0.0 | 123.7 | 123.7 | 6.0 | 0 | 0.9 |
| long field | 30 | A_backoff | re-sent until the box's ACK | 11.1 | 11.1 | 122.3 | 123.2 | 6.0 | 1 | 0.9 |
| long field | 30 | H_paced | one shot (before PKB-3) | 0.0 | 0.0 | - | - | 1.0 | 0 | 0.7 |
| long field | 30 | H_paced | re-sent 5 times, no box ACK | 11.1 | 0.0 | 58.5 | 58.5 | 6.0 | 0 | 0.8 |
| long field | 30 | H_paced | re-sent until the box's ACK | 11.1 | 11.1 | 58.0 | 58.0 | 5.9 | 1 | 0.8 |
| CQB (walls) | 10 | A_backoff | one shot (before PKB-3) | 77.8 | 0.0 | 0.2 | 0.7 | 1.0 | 0 | 0.3 |
| CQB (walls) | 10 | A_backoff | re-sent 5 times, no box ACK | 100.0 | 0.0 | 0.9 | 57.8 | 6.0 | 0 | 0.4 |
| CQB (walls) | 10 | A_backoff | re-sent until the box's ACK | 100.0 | 100.0 | 0.5 | 56.3 | 1.7 | 9 | 0.3 |
| CQB (walls) | 10 | H_paced | one shot (before PKB-3) | 77.8 | 0.0 | 0.8 | 3.0 | 1.0 | 0 | 0.3 |
| CQB (walls) | 10 | H_paced | re-sent 5 times, no box ACK | 100.0 | 0.0 | 1.5 | 9.7 | 6.0 | 0 | 0.5 |
| CQB (walls) | 10 | H_paced | re-sent until the box's ACK | 100.0 | 100.0 | 1.5 | 27.4 | 1.4 | 9 | 0.3 |
| CQB (walls) | 20 | A_backoff | one shot (before PKB-3) | 44.4 | 0.0 | 0.3 | 0.8 | 1.0 | 0 | 0.3 |
| CQB (walls) | 20 | A_backoff | re-sent 5 times, no box ACK | 100.0 | 0.0 | 0.5 | 24.7 | 6.0 | 0 | 0.5 |
| CQB (walls) | 20 | A_backoff | re-sent until the box's ACK | 100.0 | 100.0 | 0.7 | 122.4 | 2.1 | 9 | 0.4 |
| CQB (walls) | 20 | H_paced | one shot (before PKB-3) | 66.7 | 0.0 | 1.1 | 3.0 | 1.0 | 0 | 0.3 |
| CQB (walls) | 20 | H_paced | re-sent 5 times, no box ACK | 100.0 | 0.0 | 3.5 | 58.4 | 6.0 | 0 | 0.5 |
| CQB (walls) | 20 | H_paced | re-sent until the box's ACK | 100.0 | 100.0 | 2.5 | 26.9 | 2.0 | 9 | 0.4 |
| CQB (walls) | 30 | A_backoff | one shot (before PKB-3) | 11.1 | 0.0 | 0.2 | 0.2 | 1.0 | 0 | 0.4 |
| CQB (walls) | 30 | A_backoff | re-sent 5 times, no box ACK | 88.9 | 0.0 | 25.6 | 123.3 | 6.0 | 0 | 0.6 |
| CQB (walls) | 30 | A_backoff | re-sent until the box's ACK | 88.9 | 88.9 | 57.3 | 250.3 | 3.9 | 8 | 0.5 |
| CQB (walls) | 30 | H_paced | one shot (before PKB-3) | 22.2 | 0.0 | 1.4 | 1.7 | 1.0 | 0 | 0.4 |
| CQB (walls) | 30 | H_paced | re-sent 5 times, no box ACK | 88.9 | 0.0 | 11.3 | 122.3 | 6.0 | 0 | 0.5 |
| CQB (walls) | 30 | H_paced | re-sent until the box's ACK | 88.9 | 88.9 | 9.4 | 122.8 | 2.7 | 8 | 0.5 |

Reading it: the one-shot numbers are 0-78 % (all in range 22-78 %, the long field 0-67 %); with the box ACK every setup reaches its box in the meshes and the CQB layout up to 20 boxes and in the long field of 10, and 89-100 % at 30 boxes in the meshes and CQB; the long field of 20 and 30 boxes stays poor (56 % and 11 %; the radio itself loses what the repeats resend, as it loses events there: SL-13), and there the repeats cost the full six frames. A setup that does arrive does so in a median 0.5-58 s (p95 up to about four minutes where it took the later repeats, as the waits double). The box's confirmation is a normal event (about 9 per run, one per setup that arrived) and the controller's airtime does not move (0.3-0.9 %). The frames per setup are 1.4-2.8 with the ACK where it works, against 6.0 for repeating blindly (the fallback for an older box), and 1.0 for one shot. Without the ACK the repeats reach about as many boxes but cost six frames each and the scenario never knows. Not measured: the radio on a field; the confirmation event's effect on a 30-box field's duty cycle beyond the study (it adds about one 23-byte event per setup).
