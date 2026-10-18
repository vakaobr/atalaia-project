<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Decisions to review

The maintainer asked the work to go on without waiting for answers: "if anything depends on my answers, put it per your recommendation and generate a report which we can revisit later". This file lists every question that came up and the answer chosen in the meantime. Change any answer, and the affected work is adjusted.

Status: **open** means not yet reviewed by the maintainer; **confirmed** and **changed** record the review.

## How the work is run

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| R1 | What counts as "phase 2 finished" before its report goes to the phase 3 agent? | Plan phases A to E (protocol, simulator, firmware radio, controller, GM console). Phase F needs the radio boards, so it waits for the parts. | A to E can be built and tested without hardware; F is the field test itself. | open |
| R2 | When is work committed and pushed? | After each plan phase, once the main session has verified it independently from a clean copy (builds, the CI test commands, sanitizers, a Wokwi run for firmware). | The maintainer asked for a commit and push after each phase; independent checks have caught several false "done" reports. | open |
| R4 | Documentation | The README, the per-folder docs and the bilingual project page (site/i18n/pt.yaml and en.yaml, rebuilt with tools/build_site.py) are updated in every phase, as part of that phase (maintainer's instruction). | Docs kept drifting behind the work. | confirmed |
| R3 | Phases 3, 4 and 5 are being designed in parallel. When are they implemented? | Each stays design-only until the phase before it is implemented. Its design is updated with the earlier phase's report first, and committed as documentation as soon as it is reviewed. | Their plans depend on interfaces that are still being built. | open |

## Phase 2, plan phase C (firmware radio)

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| C1 | How large should the OTA slots be? | 2 MB each (was 1.5 MB), plus a 4 KB nvs_keys partition; 9.9 MB of the 16 MB flash stays free. | The image was at 87% of 1.5 MB before the radio code. The agent reports that 3 MB slots broke LittleFS in Wokwi; that needs a root cause before going further. | open |
| C2 | Which antenna gain does the EU868 power cap assume? | A conservative Kconfig default for the stock antenna, to be measured at bring-up. Conducted power = the limit minus the FEM gain minus the antenna gain, never above 25 mW ERP on the g bands and 500 mW ERP on 869.4-869.65 MHz. | The first version ignored the antenna gain and could exceed the legal limit. | open |
| C3 | How is the game key protected at rest? | NVS encryption with the ESP32-S3 HMAC (eFuse) scheme in production, and a clearly marked fallback for development boards without a burned eFuse key. The eFuse burn is a one-time provisioning step, documented in BRING_UP.md. | ADR-P2-12. Burning an eFuse cannot be undone, so it must not happen by accident on a dev board. | open |
| C4 | The radio is disabled in the Wokwi build because probing it reportedly corrupted the emulated flash. Is that acceptable? | No (maintainer's answer). It must be fixed: the Wokwi build runs with the radio enabled, the probe finds no chip and carries on, and the root cause is found. A disable is only allowed with proof of an emulator defect and the maintainer's agreement. | The radio code has never run in a runtime test, and a real driver bug could look the same. | confirmed |
| C5 | How do boxes choose radio channels? | **Changed from the accepted design.** ADR-P2-13 and RFC 0001 had boxes rotate their transmissions across three 1% channels (868.1, 868.3 and 868.5 MHz), with time and commands on 869.525 MHz, but never said where a box listens. The SX1262 hears one channel at a time, so most packets would be missed. Chosen: one shared channel per game, by default 869.525 MHz (the 869.4-869.65 MHz sub-band: 10% duty cycle and up to 500 mW ERP), for everything; configurable per game to separate neighbouring games. RFC 0001 gets a dated amendment. | The standard approach for single-radio LoRa meshes (Meshtastic's EU868 default uses the same frequency). It gives more airtime than the three 1% channels together, and every box hears every packet. | open |

## Phase 2, plan phase D (field controller and USB modem)

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| D1 | ADR-P2-4's modem frames are type + length + payload. How does a receiver find frame boundaries after junk? | Each frame starts with a sync byte `0xA5` and ends with a CRC-16/CCITT-FALSE over type, length and payload; the decoder resynchronises byte by byte. Specified in protocol/usb-modem.md. | The serial line carries the ESP32-S3 boot text, and the Pi may open the port in the middle of a frame; with a bare length prefix one lost byte desynchronises the link for good. | open |
| D2 | The RX frame (header + payload + RSSI + SNR) does not say which nonce epoch authenticated the packet. | It carries the epoch too (2 bytes after RSSI and SNR). | A box restarts its seq at 0 after every reboot, so the controller needs the epoch to tell new packets from old ones and to ACK per epoch. | open |
| D3 | ADR-P2-4 lists three TX_ACK statuses and no CMD opcodes. | TX_ACK statuses 3-7 added (not configured, invalid, nonce reuse, queue full, no radio); CMD opcodes PING, CONFIGURE, SET_CHANNEL, STATUS, SET_PEER_EPOCH, CLEAR, IDENT; every command answered by STATUS or ERROR. | The controller must know why a packet was not sent, and every command needs a reply for the watchdog. | open |
| D4 | ADR-P2-2's receiver tries only the last epoch and the next one. A box that reboots twice out of range, or joins with an epoch above 1, is never decrypted again. | The modem tries up to 16 epochs above the last known one (never below), and the controller can set a box's epoch (SET_PEER_EPOCH). The boxes' own receive code (`radio_protocol.c`) still tries one; a window function is ready for them. Recommend an RFC 0001 amendment. | Without it a twice-rebooted box is silently lost: the opposite of "zero lost captures". 16 extra AES-CCM checks per unknown packet are cheap on the ESP32-S3's AES hardware. | open |
| D5 | Who owns the controller's nonce counter, the Pi or the modem? | The Pi: it stores its epoch +1 in SQLite before the first packet of every run and at seq wrap, and sends the epoch with CONFIGURE. The modem refuses any (epoch, seq) not above the last one it sent. | The Pi has the persistent storage and outlives modem reboots; the modem's check stops a Pi bug from reusing a nonce. | open |
| D6 | ADR-P2-9's events table is UNIQUE on (game, node, seq). A box's event seq restarts at 1 after a reboot, so its new events would be dropped as duplicates. | UNIQUE on (game, node, seq, game time, type). Replays still match exactly. | A battery pull would otherwise lose every capture after it: the phase 2 gate. | open |
| D7 | ACK `ack_seq` is "highest contiguous seq", but a box's STATE and telemetry packets share the seq space and are never resent, so one lost STATE leaves a gap for ever. | Implemented as specified, per (box, epoch), with `ack_seq = 0xFFFF` meaning "seq 0 not received" and the bitmap for the next 256 seqs. Boxes must treat bitmap bits as ACKs. Recommend an RFC change (separate seq spaces for reliable traffic, or per-packet ACKs). | Fails safe (events are resent, never lost) but wastes airtime after a lost STATE. A protocol change needs an RFC. | open |
| D8 | The core's C payload codec disagreed with the schema, RFC 0001 and the shared vectors (HELLO capabilities as bytes, STATE counters and CLAIM acks as arrays, CMD params as text, required fields dropped when zero), and its vector tests skipped every vector it could not decode. | **Fixed in the core** to match the schema exactly; required fields and value ranges are now checked; the vector tests in C and Python are strict and also check the invalid vectors. | The controller (Python, schema-exact) could not have read a box's HELLO or STATE. The RFC is the accepted specification, so the C code was the bug. | open |
| D9 | CMD `params` is a "map"; the C struct keeps it as 128 bytes of JSON. | A CBOR map with text keys whose JSON form fits 127 bytes; the controller refuses bigger ones. | Matches the schema and what a box can hold. | open |
| D10 | Where does the controller keep the game key? (ADR-P2-4: never on the Pi's disk.) | In memory only by default; `persist_game_key = true` keeps it in the SQLite file (mode 0600) so a game survives a controller restart. Without it, a game whose controller restarted can only be ended. | Follows the ADR by default; a field owner who prefers continuity over at-rest secrecy can choose it. | open |
| D11 | Which REST endpoints make up "17"? | Spec section 11's 15 plus `GET /api/v1/games` and `GET /api/v1/games/{id}`; also `GET /api/v1/controller`, `POST /api/v1/controller/promote` (manual failover) and `GET /healthz`. Mode upload is JSON `{"files": {...}}` (1 MB cap, P5-6), not a zip. The node command endpoint takes `set_owner`, `message`, `reset` and `reboot`; the lifecycle goes through the game endpoints. | No multipart dependency; scripts are checked in the core before they are stored. | open |
| D12 | How do REST tokens work? | Read token for reading and the WebSocket, GM token for changes, as `Authorization: Bearer` (or `?token=` for the WebSocket). Unset tokens are generated on first start and kept in the store; `python -m atalaia_controller tokens` prints them. | Spec section 11's read and GM tokens; nothing to configure for a first run. | open |
| D13 | How are MQTT commands authorised? | By Mosquitto users and an ACL (`controller/deploy/`), not by a token inside the message. Events published while the broker is down are not queued; retained topics are republished on reconnect. | The broker already does authentication; the SQLite log is the record. | open |
| D14 | How many games can be live at once? | One per controller: the modem holds one game key. Other games can be listed and exported. | One radio channel and one key per game. | open |
| D15 | Plan names: `controller/src/` and pytest. | Package `controller/atalaia_controller/` (like `atalaia_sim`), unittest like the simulator; dependencies from Ubuntu's packages in the dev image and CI (FastAPI 0.101, pydantic 1, paho-mqtt 1.6), with `requirements.txt` for pip. | `src` makes a poor import name; Raspberry Pi OS ships the same generation of packages. | open |
| D16 | Which serial port does the modem use? | The ESP32-S3's built-in USB-Serial-JTAG by default; UART0 as a Kconfig option. To be confirmed at bring-up: BRING_UP.md mentions `/dev/ttyUSB0`, which suggests a USB-UART bridge on the board. | The Kconfig comments list GPIO 19/20 as USB; both paths are compiled in every build. | open |
| D17 | Can a second Pi stand by as a backup controller in phase 2? | Not until the join flow (plan phase E) can give it the game key. The election code is shared and tested in the simulator (two and three controllers, priority, ties, manual promote, step-down); the real controller steps down on a higher term and can be promoted. | A standby needs the key to hear the game. | open |
| D18 | The node firmware starts the radio task but does not yet send its events and STATE or act on TIME, CMD and ACK (found while building the controller; plan phase C left it unwired). | To be wired before plan phase F, as a phase C follow-up; nothing on the controller side depends on it. | The controller and modem are tested against the protocol, but no box talks it yet. | open |

## Phase 3, 4 and 5 designs

The open questions from those design runs are added here as each run reports, with the recommended answer used for now.

### Phase 5, community (design: docs/phase-5-community/)

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| P5-1 | Which third language comes first, after Portuguese and English? | Spanish (es). | The largest neighbouring airsoft community, and close to Portuguese for translators. | open |
| P5-2 | Is the visual mode editor a tab in the simulator or a separate page? | A separate page at `/editor/` that uses the simulator to test a mode (ADR-P5-2). | Keeps the editor and the simulator independent while reusing the simulator to run the blocks. | open |
| P5-3 | Create the separate `atalaia-modes` registry repository now, or later? | **Not yet.** The design recommends creating it now with a placeholder index, but creating a GitHub repository changes the maintainer's account, so it waits for the maintainer's go-ahead. | Outward-facing action; the rest of the registry work (schema, signing tools, tests) can proceed in this repository first. | open |
| P5-4 | Do mode packages live in the registry repository or in authors' own repositories? | Both; the registry hosts packages for authors without their own repository. | Lowers the barrier for first-time mode authors. | open |
| P5-5 | Is a partial translation acceptable? | Yes for modes and the editor, with English as the fallback; the project page must stay 100% translated (its build check enforces it). | Community translations arrive gradually. | open |
| P5-6 | Maximum size of a mode package? | 1 MB per package. | Modes are scripts and small assets; a cap limits abuse of the registry. | open |
| P5-7 | The carrier PCB: when? | Deferred until at least three perfboard prototypes work (ADR-P5-6); KiCad 8, CERN-OHL-S-2.0. | A PCB before the hand-wired boxes are proven would likely need a respin. | open |

### Phase 3, Android and players (design: docs/phase-3-android-players/)

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| P3-1 | How are chrono readings signed? | **Changed from the design's choice.** Phase 3 chose HMAC-SHA256 (ADR-P3-7), phase 4 chose an Ed25519 key per marshal (ADR-P4-5). Chosen: Ed25519 in both, so phase 4 needs no migration. To be fixed in ADR-P3-7 before phase 3 is implemented. | Ed25519 survives password changes and lets other fields verify records without a shared secret. | open |
| P3-2 | Screen templates: code or data? | Declarative YAML templates in each mode's `assets/screens/` (ADR-P3-4), as spec section 12 describes, with a minimal YAML parser on the ESP32. The firmware's current C-function templates (ADR-P1-2) get rewritten to read them. | Modes can ship their own screens and look the same on the box and the app. It costs a firmware parser and a renderer change. | open |
| P3-3 | New standard events (ids 25-39: kill.confirmed, team.eliminated, holdall.*, laststand.*, chrono.checkin and spotcheck, visibility.*, node.tamper, pod.*)? | Added through protocol/schema/events.yaml as the design lists (ADR-P3-8). With no other contributors yet, recorded here instead of a two-week RFC review. | Events are protocol changes (CONTRIBUTING.md). | open |
| P3-4 | MQTT on an Android controller? | A minimal embedded Dart MQTT 3.1.1 broker, QoS 0 and 1 only (ADR-P3-12); the Pi keeps Mosquitto. | No external broker on a phone. Worth checking whether a maintained Dart broker exists before writing one. | open |
| P3-5 | Chrono limit templates (Portugal, UK, Germany, generic CQB)? | Ship inside the app; Portuguese values to be checked against the current national rules before release. | Props may be offline. The figures came from research, not an official source. | open |
| P3-6 | Smaller choices: the yaml package in Flutter (custom parser only on the ESP32), no dormant FFI bridge on iOS, cirruslabs/flutter:stable for CI, pod firmware sharing the modem framing, a 247-byte minimum BLE MTU, and plan phase A first. | As the design chose (M-1 to M-8 in its report). | Standard tooling, code reuse, no BLE fragmentation. | open |
| P3-7 | The design lists phase 2's USB modem framing and join format as "complete and stable". | They are designed (ADR-P2-5, ADR-P2-12) but built only in phase 2 plan phases D and E. Phase 3 re-checks its assumptions B4 and B10 when phase 2's report arrives. | Avoids building on interfaces that may still change. | open |

### Phase 4, site server and advanced play (design: docs/phase-4-site-server/)

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| P4-1 | Where does the custom-scenario compiler (YAML objectives to field.lua) run? | **Changed from the design's choice.** The design puts it on the site server with a CLI fallback (ADR-P4-6). Chosen instead: a shared Python library that runs on the field controller (the GM console calls it there), and the site server reuses the same library. To be fixed in ADR-P4-6 before phase 4 is implemented. | The site server is optional and the platform is local-first (spec sections 3 and 11); a field without a site server must still build custom scenarios. | open |
| P4-2 | How are chrono records signed? | Ed25519 key per marshal (ADR-P4-5), not HMAC. | Survives password changes and lets other fields verify a record without a shared secret. | open |
| P4-3 | How are clubs isolated in hosted mode? | A PostgreSQL schema per field, with row-level security as defence in depth (ADR-P4-4). | Export and deletion are a single schema dump or drop; RLS catches query mistakes. | open |
| P4-4 | Where do geo functions (distance, inside-zone) live? | In the C core (geo.c), exposed to node and field scripts (ADR-P4-9). | Trigonometry in Lua is slow on the ESP32, and one implementation keeps every platform identical. | open |
| P4-5 | Is two-factor login mandatory? | TOTP is mandatory for admin, GM and marshal accounts, optional for players (ADR-P4-2). | These roles can change games and penalties. Field staff may find TOTP awkward on game day, so worth confirming. | open |
| P4-6 | GDPR: is a legal review needed? | Yes, before hosted mode goes live. The design ships templates and defaults (anonymise on erasure, keep chrono signatures, retention 12 and 24 months, daily purge, PT/EN notices) that a Portuguese lawyer should review. | Hosting other clubs' player data makes the project a data processor. | open |
| P4-7 | Which database for the site server? | PostgreSQL 16 in docker-compose with Caddy for TLS and daily pg_dump backups (ADR-P4-1, ADR-P4-10). | Multi-tenant hosting and JSONB event data; it runs on a mini PC or a small VPS. | open |

### Spec questions found along the way

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| S1 | The spec (section 13) says ESP32 firmware images are "signed with Ed25519", and phase 5 signs modes with Ed25519 to match. The ESP32-S3's hardware secure boot only supports RSA-3072 or ECDSA. | Keep Ed25519 for modes and for an application-level check of OTA images, and decide separately whether to also enable hardware secure boot (RSA-3072 or ECDSA) when the firmware update path is built. | Ed25519 in software is fine for modes and update packages; hardware secure boot is a separate, one-time eFuse decision. | open |
