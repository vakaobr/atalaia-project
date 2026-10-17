<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 2 -- Field Network: Status

**Current phase:** Planning (complete, revised)
**Risk level:** High
**Mode:** Design only -- run stopped after planning on purpose

## Completed

- [x] Research phase: `RESEARCH.md` written (revised for Heltec V4.3 + USB modem)
- [x] Architecture decisions: `ADR.md` written (15 ADRs, 29 planning constraints)
- [x] Implementation plan: `PLAN.md` written (6 phases, 10 acceptance criteria, field test plan with calibration + failover test)

## Revisions applied (2026-10-17)

Five design fixes (revised twice), six open-question decisions applied:

### Fixes
1. **Nonce reuse after reboot** (ADR-P2-2, revised twice): nonce_ctr = (epoch << 16) | seq. Epoch persisted in NVS at boot and at seq wrap (no per-packet writes, no SKIP_GAP). If NVS write fails, radio halts (nonce.nvs_fail). Receivers discover epoch transitions via AES-CCM trial (try current, then epoch+1 on auth failure). HELLO/STATE carry epoch for resync.
2. **Events lost on reboot** (ADR-P2-9, revised twice): flash-backed append log on LittleFS (`/log/game.bin`, 256 KB). Normal and critical events flushed immediately (zone.captured is normal priority). Only telemetry buffered (8-entry cache, 5 s). Worst-case power-cut loss: at most 7 telemetry events. Zero game events lost. Replay from flash after reboot.
3. **Rejoin after reboot** (ADR-P2-12): game key in encrypted NVS (ESP32-S3 eFuse HMAC). Rebooted node rejoins automatically with epoch+1 and persisted key. Key zeroed on game end. eFuse key burn is a one-time provisioning step.
4. **hop_limit AAD contradiction** (ADR-P2-2/ADR-P2-6): consistently 8-byte AAD (header minus hop_limit). Relay clamp added: incoming hop_limit capped to game's configured maximum before rebroadcast.
5. **Offline maps** (ADR-P2-10): uploaded field image/floor plan is the primary map. OSM tiles are secondary, online-only, with required attribution. No bulk prefetch.

### Open question decisions
1. **Hardware**: Heltec WiFi LoRa 32 V4.3 high-power (ESP32-S3R2, 2 MB PSRAM, 16 MB flash, SX1262 + FEM, 28 dBm). Controller radio: USB modem (same board), not SPI HAT. FEM GPIO2 (FEM_EN) + GPIO7 (VFEM_Control). EU868 power cap accounts for FEM gain.
2. **Region**: EU868 (Portugal). Other regions remain a config change.
3. **Controller language**: Python. No C daemon on the Pi; all radio/crypto code is in the modem firmware.
4. **Failover**: manual by default. Automatic CLAIM election tested after initial field tests (named step in field-test plan).
5. **RFC**: accepted by maintainer (2026-10-17). No 2-week review wait. Normal RFC process for future protocol changes.
6. **MQTT**: Mosquitto as system service on the Pi.

## Deliberately stopped

This run was design only. No code has been written. Phase 2
implementation starts now that Phase 1's software has landed (commit
74acd38), after re-checking the 12 Phase 1 assumptions in PLAN.md
against the merged firmware. The plan is ready to execute.

## Plan summary

| Phase | Scope | Hardware needed | Depends on |
|-------|-------|-----------------|------------|
| A | Protocol codecs, RFC-0001 (accepted), protogen extension, test vectors | No | -- |
| B | Simulator extension: RadioModel, multi-node tests, FieldController | No | A |
| C | Core API (state.field, field.*), radio HAL + FEM control, ESP32 radio task, modem firmware, time sync, flash event log | Cross-compile: no; radio testing: yes | A |
| D | Python field controller + modem serial framing, REST, MQTT, SQLite, failover | No | A, C (core API) |
| E | GM console (Preact+HTM PWA), join flow (NFC+QR), example scoreboard | No | D |
| F | Integration on hardware, calibration, field test, auto-failover test, documentation | Yes (6 Heltec V4.3 + Pi) | A-E |

## Acceptance criteria (10 total)

| # | Criterion | Hardware |
|---|-----------|----------|
| AC-1 | Protocol codec round-trips all 8 message types | No |
| AC-2 | AES-CCM encrypt/decrypt with epoch-based nonce passes vectors | No |
| AC-3 | Simulator multi-node Domination game correct scores | No |
| AC-4 | Duty-cycle compliance in 5-node 20-min sim game | No |
| AC-5 | Controller REST API serves all 17 endpoints | No |
| AC-6 | GM console serves and renders without errors | No |
| AC-7 | ESP32 firmware + modem firmware cross-compile | No |
| AC-8 | Partition recovery + power-loss replay -- zero lost captures in sim | No |
| AC-9 | Failover election completes in simulator | No |
| AC-10 | Field test gate: 5 boxes + modem + Pi, zero lost captures | Yes |

## Architecture decisions summary

| ADR | Decision | Key constraint |
|-----|----------|----------------|
| ADR-P2-1 | Header bit layout + big-endian | version(3) + priority(2) + ack(1) + encrypted(1) + reserved(1) |
| ADR-P2-2 | AES-CCM with epoch-based nonce | nonce_ctr = (epoch << 16) or seq; epoch persisted at boot + seq wrap; receiver trial epoch+1; 8-byte AAD; game key in encrypted NVS |
| ADR-P2-3 | Message payload schemas | CBOR integer keys for all 8 types; epoch field in HELLO/STATE; protogen extension required |
| ADR-P2-4 | Radio HAL + SX1262 + FEM + USB modem | `hal_radio_ops_t` with FEM GPIO control; modem firmware is Kconfig variant; EU868 power cap with FEM gain |
| ADR-P2-5 | Python controller + USB modem | No C daemon on Pi; Python talks to modem over USB serial; pyserial |
| ADR-P2-6 | TTL flood + dedupe + relay clamp | 64-entry dedupe; hop_limit excluded from AAD; relay clamps to game max |
| ADR-P2-7 | Time sync: linear slew | Slew at max 5%/s; step only if offset >500ms; TIME on g2 sub-band |
| ADR-P2-8 | CLAIM failover protocol | Priority score formula; term-based election; manual default; auto-failover test in field plan |
| ADR-P2-9 | Flash-backed event log + log merge | LittleFS `/log/game.bin` (256 KB); normal+critical flush immediately; only telemetry buffered; survives reboot |
| ADR-P2-10 | GM console: Preact+HTM | No build step; uploaded field image primary; OSM tiles online-only |
| ADR-P2-11 | Simulator RadioModel | Lossy radio model, partition sim, duty-cycle tracking |
| ADR-P2-12 | Join flow: NFC + QR + auto-rejoin | Game key in encrypted NVS (eFuse HMAC); rebooted node rejoins with epoch+1 |
| ADR-P2-13 | Duty-cycle enforcement + FEM power cap | Per-sub-band tracking; 3-channel hopping; SX1262 output set to ERP - FEM gain |
| ADR-P2-14 | state.field{} + field.* API | Core changes gated by field_ops pointer; core bump to 0.2.0 |
| ADR-P2-15 | RFC-0001 (accepted) | Normative spec at `docs/rfcs/0001-skirmesh-rf-wire-format.md`; ADRs document rationale |

## Dependencies on Phase 1

Phase 2 depends on Phase 1 shipping these interfaces:
- `hal_t` struct (`firmware/esp32/main/hal/hal.h`) -- extensible with `hal_radio_ops_t`
- `node_runner_t` (`firmware/esp32/main/node_runner.h`) -- extensible with radio callbacks
- `config_store` with radio region setting
- Game timer in the shell (ADR-P1-3)
- LittleFS preset store (ADR-P1-4)
- Core API stability (`node.h`, `event.h`, `score.h`, `codec.h`)
- NVS encryption support in sdkconfig.defaults

Phase 1 status: software merged in 74acd38 (firmware shell, HAL, game
loop, presets, resume after reboot, Wi-Fi setup). Still open: LVGL host
rendering, the preset-list screen, and the 2-hour hardware gate.

## Key risks

| Risk | Level | Mitigation |
|------|-------|------------|
| LoRa range in CQB buildings | High | FEM improves sensitivity; repeater nodes; SF7 default; field testing |
| EU868 duty-cycle compliance | High | Duty-cycle tracking in HAL and simulator; 10% sub-band for controller; 3-channel hopping |
| Controller failover split-brain | High | Term-based election, scores conflict-free, manual default |
| Nonce reuse after reboot | Resolved | nonce_ctr = (epoch << 16) or seq; epoch persisted at boot + seq wrap; NVS failure halts radio |
| Events lost on power cut | Resolved | Normal+critical events flushed immediately; only telemetry buffered; zero game events lost |
| Time sync accuracy | Medium | Slew algorithm, airtime-compensated timestamps, step for large offsets |
| FEM power calibration | Medium | Calibration step in field-test plan; Kconfig-adjustable FEM gain |
| USB modem disconnect | Low | Watchdog ping, auto-reconnect, `radio.down` system event |

## How to resume

After Phase 1 merges:
1. Re-check the 12 Phase 1 assumptions in PLAN.md against what was actually built.
2. Resume with: `/sdlc phase-2-field-network --resume`
3. Or start Phase A directly (protocol codecs, RFC -- no Phase 1 dependency).
