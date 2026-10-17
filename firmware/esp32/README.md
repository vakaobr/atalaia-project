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
  |     +-- display_port_init() (LVGL 9.2, DMA flush)
  |     +-- screen_render()
  |     +-- lv_timer_handler()
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

Everything builds in Docker (Docker Desktop must be running); no compiler is
needed on the host. `tools/docker_fw.py` works from `cmd`, PowerShell or
bash, from the repository folder:

```
python tools/docker_fw.py build                   firmware for the Field Box -> firmware/esp32/build/
python tools/docker_fw.py wokwi                   Wokwi emulator variant -> firmware/esp32/build-wokwi/
python tools/docker_fw.py test                    host tests and screen reference images
python tools/docker_fw.py test --update-screens   accept changed screens as the new references
```

`build` and `wokwi` use the `espressif/idf:v5.3.2` image, like CI's
`esp32-build` job. `test` runs CI's `firmware-test` commands in the
`atalaia-dev` image. With a toolchain of your own, the same commands are:

```sh
cd firmware/esp32 && idf.py set-target esp32s3 && idf.py build
cmake -S firmware/esp32/test -B /tmp/fw-test -DCMAKE_BUILD_TYPE=Debug
cmake --build /tmp/fw-test && ctest --test-dir /tmp/fw-test --output-on-failure
```

## Screens

The screen templates (`main/screen_renderer.c`, ADR-P1-2) are C functions
that build LVGL 9.2 widget trees for the 320x240 TFT: `standby`,
`countdown`, `defused`, `exploded`, `final_score`, `paused`, `status`, the
preset picker (`pin_entry`, `preset_select`, `timer_adjust`,
`start_confirm`) and `wifi_setup`. Each template is built once and then
patched with new data, so a countdown only changes one label per second.

The host tests build the same code against the same LVGL release (9.2.2,
fetched from its GitHub tag and checked against `dependencies.lock`) and the
same `lvgl_conf/lv_conf.h`, render every template into memory, and compare
the result pixel by pixel with the PNG files in
[`test/screens/`](test/screens/). They also fail when a widget is clipped by
the screen or two labels overlap. After changing a screen on purpose, run
`python tools/docker_fw.py test --update-screens` (or set
`ATALAIA_UPDATE_SCREENS=1` for `ctest`), look at every changed PNG, and
commit them with the change. Rendered images land in
`firmware/esp32/build-test/screens/` (or `<build>/screens/` with `ctest`),
next to a `.diff.png` for each mismatch.

## Wokwi emulator

[`docs/WOKWI.md`](docs/WOKWI.md) explains how to run the firmware in the
Wokwi emulator in VS Code (`wokwi.toml`, `diagram.json`) and play a Bomb
game on the simulated display, buttons, LED ring and keypad, before the
hardware arrives.

## Kconfig

All pin assignments, memory tier, keypad interface and display controller
are in `main/Kconfig.projbuild`.  Change with `idf.py menuconfig`.
`sdkconfig.wokwi` holds the emulator's overrides; the Field Box uses
`sdkconfig.defaults` alone.

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

- `espressif/esp_lvgl_port` -- listed but not used: the display port in
  `main/display_port.c` drives LVGL through the HAL display driver
- `lvgl/lvgl` -- v9.2 display toolkit, configured by `lvgl_conf/lv_conf.h`
- `espressif/led_strip` -- WS2812B RMT driver
- `joltwallet/littlefs` -- LittleFS VFS

## Built-in presets

On a box with an empty preset store (a new or erased box, and every Wokwi
run), the firmware stores two presets: Bomb and Domination, with the
defaults from their `mode.yaml`. The mode scripts come from `modes/` at
build time. The default admin PIN is 1234 until the setup portal sets one.

## Phase 2 (not yet)

- SX1262 LoRa radio driver (Phase 2, field mesh)
- A/B OTA updates with Ed25519 signatures
- GNSS module support (GPIO 38-42 currently used for peripherals)

## Radio Region

The firmware refuses to transmit until a region is set (EU868 for
Europe, US915 for the Americas) and enforces power and duty-cycle
limits.  The SX1262 radio is unused in Phase 1.
