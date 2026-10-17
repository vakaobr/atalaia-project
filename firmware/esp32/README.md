<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# ESP32 Firmware

ESP-IDF firmware for Atalaia Field Boxes running on ESP32-S3.

## Default Board

**Heltec WiFi LoRa 32 V4.3** (bare board, 863-928 MHz).
ESP32-S3R2 with 2 MB PSRAM, 16 MB flash, SX1262 LoRa radio.

The Heltec V3 (8 MB flash, no PSRAM) is also supported as a
Reduced-tier option.

## Architecture

The firmware is structured as a shell around the shared C core (`core/`):

```
app_main
  +-- game_task (core 1, priority 5, 100 Hz)
  |     +-- poll buttons/keypad/NFC
  |     +-- atalaia_node_advance()
  |     +-- game_timer_tick()
  |     +-- state_persist_save() (every 1 s)
  |     +-- command_dispatch()
  +-- lvgl_task (core 1, priority 4, 5 ms)
  |     +-- lv_timer_handler()
  |     +-- screen_render()
  +-- audio_task (core 0, priority 3)
  +-- wifi_task  (core 0, priority 2)
  +-- mem_monitor (core 0, priority 1, 10 s)
```

### HAL Abstraction

Every hardware subsystem is behind a function-pointer ops struct
(`hal_button_ops_t`, `hal_keypad_ops_t`, etc.).  ESP-IDF drivers
live in `main/hal/esp/`; stubs for Linux testing in `main/hal/stub/`.
The shell holds a `hal_t` aggregate initialised by `hal_esp_init()`
or `hal_stub_init()`.

## Device Tiers

| Tier | Board | Lua heap | Display |
|------|-------|----------|---------|
| Full | Heltec V4.3 (2 MB PSRAM) | 256 KB | Colour TFT |
| Reduced | Heltec V3 (no PSRAM) | 64 KB | Monochrome OLED |
| Proxy | Cannot run scripts | -- | Thin node on controller |

## Build

Cross-compile for ESP32-S3 (requires Docker):

```sh
# From Git Bash on Windows:
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/project" -w /project/firmware/esp32 \
  espressif/idf:v5.3.2 \
  bash -c "idf.py set-target esp32s3 && idf.py build"
```

Run HAL stub tests on Linux:

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cmake -S /src/firmware/esp32/test -B /tmp/fw-test \
         -DCORE_DIR=/src/core -DCMAKE_BUILD_TYPE=Debug && \
         cmake --build /tmp/fw-test && \
         ctest --test-dir /tmp/fw-test --output-on-failure"
```

## Kconfig

All pin assignments, memory tier and display controller are in
`main/Kconfig.projbuild`.  Change with `idf.py menuconfig`.

Default pin map avoids all Heltec V4.3 board-internal pins.
See `Kconfig.projbuild` header and `hardware/field-box/README.md`.

## Partition Table

Custom layout for 16 MB flash (`partitions.csv`):

| Partition | Size | Purpose |
|-----------|------|---------|
| nvs | 24 KB | Configuration key-value store |
| otadata | 8 KB | A/B OTA bookkeeping |
| ota_0 | 1.5 MB | Application slot A |
| ota_1 | 1.5 MB | Application slot B |
| storage | 2 MB | LittleFS: presets, modes, state, audio |

## IDF Component Dependencies

Listed in `main/idf_component.yml`:

- `espressif/esp_lvgl_port` -- FreeRTOS integration for LVGL
- `lvgl/lvgl` -- v9.x display toolkit
- `espressif/led_strip` -- WS2812B RMT driver
- `joltwallet/littlefs` -- LittleFS VFS

## Phase 2 (not yet)

- SX1262 LoRa radio driver (Phase 2, field mesh)
- A/B OTA updates with Ed25519 signatures
- GNSS module support (GPIO 38-42 currently used for peripherals)

## Radio Region

The firmware refuses to transmit until a region is set (EU868 for
Europe, US915 for the Americas) and enforces power and duty-cycle
limits.  The SX1262 radio is unused in Phase 1.
