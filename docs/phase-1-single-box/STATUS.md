<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 1 -- Single Box: Status

**Date:** 2026-10-17
**Board:** Heltec WiFi LoRa 32 V4.3

## Verified (exit 0 from clean copy)

- **ESP-IDF cross-compile** (`idf.py build`, clean copy, exit 0):
  700 KB image, DRAM 29%, 54% of OTA partition free.
- **Firmware host tests** (12 suites, 59 test functions, ~300 CHECK
  assertions): all pass. No extra -D flags needed.
- **Existing CI** (`sh tools/check.sh`): 24 Python tests + 12 mode
  tests + core CTest, no regressions.
- **Formatting** (`tools/format.sh --check`): clean.
- **Licensing** (`reuse lint`): compliant.

## Done (software, does not need the board)

- ESP-IDF project skeleton (16 MB flash, custom partitions, Kconfig).
- IDF component wrapper for the C core (64-bit Lua, no LUA_32BITS).
- HAL abstraction: 7 subsystems with ESP drivers and Linux stubs.
- PCF8574 I2C keypad expander on the shared OLED bus (addr 0x20).
- Game loop wired: game_task (button hold/release, keypad, node_runner),
  lvgl_task (screen dequeue + render), audio_task (clip dequeue).
- Button tracker: hold every 250 ms, release events.
- Game timer with countdown and score freeze via game.end.
- Command dispatch routing commands to screen/audio/LED queues.
- Preset store (LittleFS-backed save/list/load/delete).
- State persistence (binary file with magic/version).
- Resume after reboot (state_persist_load at boot, node_runner_resume,
  node.rebooted emitted).
- Node runner (owns node, timer, command dispatcher, state persist).
- Preset UI (keypad-driven PIN + preset + timer + confirm flow).
- Config store (NVS on ESP32, in-memory on Linux).
- Wi-Fi captive portal with form parsing, field validation, NVS write,
  and timed reboot.
- Screen renderer: 9 templates recognised and routed. LVGL widget
  trees built on ESP32 (compiled, not host-tested).
- Memory monitor (10 s heap logging on ESP32).
- CI jobs: esp32-build (cross-compile) and firmware-test (host).
- Integration tests with real mode scripts (domination + bomb).
- CHANGELOG.md, README.md, BRING_UP.md, BOM.

## Stubbed (not done)

- **LVGL host rendering and PNG artifacts:** The coordinator asked for
  LVGL to be built on the host in firmware-test, each template rendered
  into an in-memory framebuffer, with PNG output and a hash check.
  This is not done. Building LVGL 9.2 from source in the host test
  build (hundreds of source files, its own CMake, lv_conf.h plumbing)
  is feasible but was not completed in this session. The LVGL widget
  code compiles on ESP32 (verified by idf.py build); template routing
  and data recording are tested on the host through the stub path
  (12 screen renderer tests).

- **preset_select screen template:** Contains a TODO for parsing the
  presets array and creating a list widget.

## Blocked on hardware

- The Phase 1 gate: "one box runs a 2-hour club game with no restarts."
- Display bring-up, NFC read distance, audio quality, battery gauge.
- Visual verification of LVGL output on real display.
