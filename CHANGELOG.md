<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
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
