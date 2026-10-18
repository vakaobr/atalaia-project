<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Core 0.2.0: `state.field{}` read-write/read-only field-level state, `field.nodes`, `field.owner`, `field.send`, `field.score`, `field.common_owner` script API functions (phase-2-field-network, Phase C)
- Radio HAL: SX1262 LoRa driver on SPI3_HOST (GPIO 8-14), EU868 SF7/BW125 with 3-channel hopping, FEM gain accounting via `radio_power.h`, duty-cycle tracking, DIO1 ISR, stub for Linux tests (phase-2-field-network, Phase C)
- Radio task: FreeRTOS core 0 priority 3, TX/RX queues with 8-slot depth (phase-2-field-network, Phase C)
- Flash event log: append-only on LittleFS, immediate flush for normal/critical events, telemetry cache with explicit flush, compaction after ACK (phase-2-field-network, Phase C)
- Time sync: slew adjustment (max 5%/tick, step above 500 ms offset), EMA-smoothed offset from TIME beacons (phase-2-field-network, Phase C)
- Radio protocol: Skirmesh-RF packet encode/decode with epoch persistence via NVS, per-source epoch trial on receive (tries stored epoch then epoch+1, never lower), `tx_blocked` on NVS failure or epoch exhaustion, nonce counter = (epoch << 16) | seq (phase-2-field-network, Phase C)
- NVS key storage: game key and epoch in "radio" NVS namespace, function-pointer abstraction for testability (`atalaia_radio_nvs_ops_t`), ESP-IDF backend with optional eFuse HMAC encryption (phase-2-field-network, Phase C)
- Partition table grown: OTA slots 1.5 MB to 2 MB, `nvs_keys` partition added for encrypted NVS (phase-2-field-network, Phase C)
- EU868 TX power calculation: centi-dBm integer arithmetic accounting for FEM gain and antenna gain, clamped to SX1262 range [-9, +22] dBm (phase-2-field-network, Phase C)
- Firmware test suite: 10 radio protocol tests (boot epoch, NVS failure, seq wrap, epoch exhaustion, receiver epoch trial with known/rebooted/lower/unknown sources), 6 TX power calculation tests (phase-2-field-network, Phase C)
- ESP32-S3 firmware shell for the Atalaia Field Box (Heltec WiFi LoRa 32 V4.3): HAL abstraction layer with ESP-IDF and Linux stub implementations for buttons, keypad, LEDs, display, NFC, audio, and battery (phase-1-single-box)
- Game timer with configurable countdown and score freeze: sends `game.end` at expiry, compatible with all existing modes (phase-1-single-box)
- Preset storage on LittleFS: save, list, load, and delete up to 32 presets with associated mode source files (phase-1-single-box)
- State persistence to LittleFS: Lua state table, game time, and scores written every second and resumed after a reboot (phase-1-single-box)
- Keypad-driven preset picker with admin PIN entry, preset selection, timer adjustment, and start confirmation (phase-1-single-box)
- Screen renderer for nine templates (`standby`, `countdown`, `defused`, `exploded`, `final_score`, `paused`, `status`, `preset_select`, `wifi_setup`) backed by LVGL v9 on ESP32 (phase-1-single-box)
- Wi-Fi captive-portal first-time setup: SoftAP, DNS redirect, and embedded HTML configuration page that writes to NVS (phase-1-single-box)
- Memory monitor that logs DRAM and PSRAM heap stats every 10 s on ESP32 (phase-1-single-box)
- HAL stub integration test suite: 32 assertions across 8 test suites (game timer, command dispatch, preset store, state persistence, node runner, preset UI, config store, integration), all runnable on Linux in the existing `atalaia-dev` container (phase-1-single-box)
- ESP-IDF cross-compile CI gate (`esp32-build` job) and firmware stub test CI gate (`firmware-test` job) added to `.github/workflows/ci.yml` (phase-1-single-box)
- Dockerfile for ESP-IDF cross-compilation at `tools/dev/Dockerfile.esp32` (phase-1-single-box)
- Hardware bring-up runbook at `firmware/esp32/docs/BRING_UP.md`: first-boot smoke test through the 2-hour stability gate (phase-1-single-box)
- Field Box screens drawn with LVGL 9.2 on the device: 12 templates for the 320x240 TFT (`standby`, `countdown`, `defused`, `exploded`, `final_score`, `paused`, `status`, `wifi_setup` and the preset picker's `pin_entry`, `preset_select`, `timer_adjust`, `start_confirm`), team screens in the team's colour, built once and patched with new data; a display port with two DMA draw buffers (phase-1-single-box)
- Screen reference images: the host tests build the same screen code against LVGL 9.2.2 (fetched from its GitHub tag, checked against `dependencies.lock`) with the device's `lvgl_conf/lv_conf.h`, render every template headless and compare it pixel by pixel with `firmware/esp32/test/screens/*.png`; `ATALAIA_UPDATE_SCREENS=1` updates them (phase-1-single-box)
- Wokwi emulator setup for VS Code: `firmware/esp32/wokwi.toml`, `diagram.json` (ESP32-S3, ILI9341, team buttons, WS2812 ring, keypad), `sdkconfig.wokwi` (GPIO keypad instead of the PCF8574, no audio, setup skipped, keys from the serial console), a Bomb automation scenario and `firmware/esp32/docs/WOKWI.md` (phase-1-single-box)
- `tools/docker_fw.py` builds the firmware, builds the Wokwi variant and runs the firmware tests in Docker from any shell, including `cmd` (phase-1-single-box)
- Built-in Bomb and Domination presets, stored on a box with an empty preset store; keypad debouncing with one press per key stroke (phase-1-single-box)

### Fixed
- Firmware: the memory monitor task overflowed its stack and crash-looped the box; the HAL drivers were never initialised; LittleFS was never mounted; the battery gauge and NFC reader claimed two I2C drivers on the same pins; the display flush queued an SPI transaction from the stack; the Wi-Fi setup never initialised Wi-Fi. Missing parts are now logged and skipped at boot (phase-1-single-box)
- `hardware/field-box/README.md` pin table now matches the Kconfig defaults (PCF8574 keypad, I2S on GPIO 6/15/16, backlight on GPIO 47, display RST on GPIO 38) (phase-1-single-box)
