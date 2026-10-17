<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 1 -- Single Box: Implementation

## Board Choice

**Heltec WiFi LoRa 32 V4.3** (bare board, standard power 863-928 MHz):
ESP32-S3R2 with 2 MB PSRAM, 16 MB flash, SX1262 LoRa radio, 0.96"
OLED, USB-C, battery connector.  The bare board (no shell) is
recommended because the Field Box has its own IP65 enclosure.

Standard-power (not high-power 28 dBm FEM) variant is recommended for
EU868, which caps most channels at 25 mW ERP.  The high-power V4.3.1
is also compatible; its FEM_EN (GPIO 2) and VFEM_Ctrl (GPIO 7) remain
unused in Phase 1 and are reserved for Phase 2.

The Heltec V3 (ESP32-S3FN8, 8 MB flash, no PSRAM) remains supported
as a Reduced-tier option by changing `sdkconfig.defaults` (4 MB flash,
no SPIRAM) and Kconfig `ATALAIA_MEMORY_TIER_REDUCED`.

## Phases Completed

### Phase A: Build system, HAL layer, ESP-IDF project skeleton

**Files created:**

| Category | Files |
|----------|-------|
| Project root | `firmware/esp32/CMakeLists.txt`, `sdkconfig.defaults`, `partitions.csv` |
| Main component | `main/CMakeLists.txt`, `Kconfig.projbuild`, `idf_component.yml`, `shell.c` |
| Core wrapper | `components/atalaia_core/CMakeLists.txt` |
| HAL headers | `hal/hal.h`, `hal_buttons.h`, `hal_keypad.h`, `hal_leds.h`, `hal_display.h`, `hal_nfc.h`, `hal_audio.h`, `hal_battery.h` |
| HAL ESP drivers | `hal/esp/hal_esp.c`, `hal_esp_buttons.c`, `hal_esp_keypad.c`, `hal_esp_leds.c`, `hal_esp_display.c`, `hal_esp_nfc.c`, `hal_esp_audio.c`, `hal_esp_battery.c` |
| HAL stubs | `hal/stub/hal_stub.c`, `hal_stub.h` |
| Docker | `tools/dev/Dockerfile.esp32` |

**Key decisions and deviations:**

- **CMake path fix:** The original `components/atalaia_core/CMakeLists.txt`
  used `../../../core` (3 levels up from `components/atalaia_core/`), which
  resolved to `firmware/core/` instead of the repo root `core/`.  Fixed to
  `get_filename_component(... "../../../../core" ABSOLUTE)`.

- **Heltec V4.3 pin map:** Default pin assignments in Kconfig avoid all
  board-internal pins (SX1262 SPI on GPIO 8-14, OLED I2C on GPIO 17-18,
  USB on GPIO 19-20, OLED RST on GPIO 21, on-board LED on GPIO 35, Vext
  on GPIO 36, ADC_Ctrl on GPIO 37, UART0 console on GPIO 43-44).  The
  GNSS header pins (GPIO 38-42) are used for external peripherals; this
  is documented and must be revisited when GNSS support is added.

- **Shared I2C bus:** NFC (PN532, addr 0x24), battery gauge (MAX17048,
  addr 0x36) and the on-board OLED (SSD1306, addr 0x3C) share the
  board's I2C bus on GPIO 17/18.

- **2 default team buttons:** GPIO pin constraints on the V4.3 allow 2
  team buttons at the default pin map.  Kconfig supports up to 4 buttons
  by reassigning pins (e.g. from the GNSS header or dropping audio).

- **Display RST tied to Vext:** Default RST pin is 0 (disabled).  The
  display resets via the Vext power rail (GPIO 36).  Software handles
  RST_PIN=0 with a compile-time `#if` guard.

- **Partition table:** 16 MB flash.  OTA slots: 2 x 1.5 MB.  LittleFS
  storage: 2 MB.  Leaves ~10 MB unpartitioned for future use.

- **PSRAM mode:** Quad (not octal) per the ESP32-S3R2 on the V4.3.

- **`espressif/led_strip` added** to `idf_component.yml` for the WS2812
  RMT driver.

- **Kconfig symbol mismatches fixed:** keypad (`_ROW0` -> `_ROW0_PIN`),
  audio (`_I2S_BCK_PIN` -> `_AUDIO_BCLK_PIN`), battery (`_BAT_` ->
  `_BATT_`).

- **`hal_esp.c` added:** Assembles all ESP driver ops structs into the
  `hal_t` aggregate.  The original code had `hal_esp_init()` declared in
  `hal_esp.h` but never defined.

- **`format.sh` updated** to exclude `build/` and `managed_components/`
  under `firmware/`.

### Phase B: Game timer, preset storage, command dispatch, state persistence

**Files created:** `game_timer.c/h`, `command_dispatch.c/h`,
`preset_store.c/h`, `state_persist.c/h`, `node_runner.c/h`,
`screen_types.h`.

All modules compile and link on Linux with HAL stubs.  The game timer
fires `game.end` exactly at the configured duration.  Command dispatch
routes `ui/screen`, `audio/play`, `ring/fill` and `team_display/show`
correctly.  Preset store round-trips save/list/load/delete using POSIX
file I/O (LittleFS on ESP32).  State persistence saves the binary
`state_persist_data_t` struct and validates magic/version on load.  The
node runner owns the `atalaia_node_t`, wires core callbacks to the
command dispatcher, manages the game timer, and persists state every
second.

### Phase C: Screen templates, Wi-Fi captive portal, on-device setup flow

**Files created:** `screen_renderer.c/h`, `preset_ui.c/h`,
`wifi_setup.c/h`, `wifi_setup.html`, `config_store.c/h`.

The screen renderer in stub builds records template names and data for
test inspection.  Nine templates are recognised (`standby`, `countdown`,
`defused`, `exploded`, `final_score`, `paused`, `status`,
`preset_select`, `wifi_setup`).  The LVGL rendering path is compiled
only under `ESP_PLATFORM` and is deferred until hardware testing.

The preset UI implements the full keypad-driven flow: PIN entry ->
preset selection -> timer adjustment -> confirmation -> start.  Wrong
PINs are rejected and the buffer is cleared.

The config store uses NVS on ESP32 and an in-memory table on Linux.
The Wi-Fi setup module starts a SoftAP captive portal on ESP32 and is
a no-op on Linux.

### Phase D: Integration, CI, hardware bring-up, documentation

**Files created:** `mem_monitor.c/h`, `docs/BRING_UP.md`.

The memory monitor logs DRAM and PSRAM heap stats every 10 s on ESP32
(no-op on Linux).  The bring-up runbook documents the first-boot smoke
test through the 2-hour stability gate.

CI jobs added to `.github/workflows/ci.yml`:
- `esp32-build`: cross-compiles in `espressif/idf:v5.3.2` container.
- `firmware-test`: builds and runs HAL stub tests on `ubuntu-latest`.

## Test Results (round 3, verified)

### Firmware host tests (atalaia-dev, no extra -D flags)

```
$ cmake -S firmware/esp32/test -B /tmp/fw-test -DCMAKE_BUILD_TYPE=Debug
$ cmake --build /tmp/fw-test
$ ctest --test-dir /tmp/fw-test --output-on-failure
1/1 Test #1: firmware .........................   Passed    0.06 sec
```

**12 test suites, 59 test functions, ~300 CHECK assertions**, all pass:

| Suite | Tests | What it covers |
|-------|-------|----------------|
| game_timer | 4 | expiry, unlimited, remaining, fire-once |
| command_dispatch | 5 | screen, audio play/stop, LED fill, team_display |
| preset_store | 4 | save/load round-trip, list, delete, bounds |
| state_persist | 4 | round-trip, clear, invalid magic, reboot resume |
| node_runner | 4 | load+start, events, timer expiry, screen updates |
| preset_ui | 6 | PIN accept/reject, selection, timer adjust, full flow, back |
| config_store | 4 | configured flag, strings, uints, reset |
| integration | 5 | 120 s domination, 5 s timed game, score freeze |
| game_loop | 3 | domination with real node.lua, bomb arm+explode, arm+defuse |
| wifi_setup | 11 | form parser, URL decode, oversized, malformed, validation |
| reboot_resume | 2 | bomb resume after reboot, node.rebooted event |
| screen_renderer | 12 | all 9 templates, unknown reject, NULL data, multi-render |

### ESP-IDF cross-compilation (clean copy, exit 0)

```
Total image size: 716438 bytes (700 KB)
atalaia_esp32.bin: 0xaef00 bytes. OTA partition 1.5 MB. 54% free.
DRAM:  99,744 bytes (29.19%), 242,016 bytes free
Flash code: 498,428 bytes
IRAM:  16,383 bytes (99.99%)
```

Components: esp_lvgl_port 2.4.4, led_strip 2.5.5, lvgl 9.2.2,
littlefs 1.14.8 (all pinned, dependencies.lock committed).

### Existing CI (no regressions)

```
$ sh tools/check.sh   # core tests + 24 Python tests + 12 mode tests
```

### Formatting and licensing

```
$ sh tools/format.sh --check   # exit 0
$ reuse lint                   # compliant
```

### Phase E: Reboot resume and screen templates

**Files created:** `test/test_reboot_resume.c`, `test/test_screen_renderer.c`.

**Files modified:** `node_runner.h/c`, `shell.c`, `screen_renderer.c`,
`test/CMakeLists.txt`, `test/check.h`, `test/test_main.c`.

#### Reboot resume (`node_runner_resume`)

`node_runner_resume()` restores a game from `state_persist_data_t`:
creates a fresh node, loads the mode source, calls `game.start`, fast-
forwards game time to `saved->game_time_ms`, restores the game timer
elapsed counter, and sends `node.rebooted`. `shell.c` checks for saved
state at boot before falling through to the preset UI.

#### Wear-levelling analysis (LittleFS state persistence)

State is persisted once per second during gameplay. A 2-hour game =
7,200 writes. Each write is ~100 bytes of `state_persist_data_t`.
LittleFS uses copy-on-write (CoW) wear levelling.

With a 2 MB partition and 4,096-byte erase blocks, the partition has
512 blocks. 7,200 writes of ~100 bytes each consume ~176 blocks per
game, distributed across the full partition by CoW allocation.

At 100,000 erase cycles per NOR flash block (conservative for ESP32
flash), each block tolerates 100,000 games worth of writes before
wearing out:

    lifetime_games = 100,000 * (512 / 176) = ~290,000 games

Even at 10 games per day, this is >79 years. **State persistence at
1 write/second is safe for the lifetime of the hardware.**

#### Screen templates (LVGL rendering)

`screen_renderer.c` now contains LVGL widget-building functions for all
9 templates, guarded by `#if ATALAIA_SCREEN_LVGL`:

| Template        | Title label   | Data fields parsed           |
|-----------------|---------------|------------------------------|
| standby         | STANDBY       | arm (team name)              |
| countdown       | (seconds)     | left (integer), team         |
| defused         | DEFUSED       | team                         |
| exploded        | EXPLODED      | team                         |
| final_score     | FINAL SCORE   | owner                        |
| paused          | PAUSED        | (none)                       |
| status          | STATUS        | battery (int), version (str) |
| preset_select   | SELECT PRESET | (TODO: presets array)        |
| wifi_setup      | WI-FI SETUP   | ssid                         |

Testing approach:
- **Host-tested:** Template routing and data recording (12 test
  functions covering all 9 templates + unknown rejection + NULL data +
  sequential calls).
- **ESP32-only:** LVGL widget trees are compiled but not host-tested
  for rendering (LVGL is not linked in the host build).
- **Follow-up:** Visual verification via the LVGL SDL simulator or
  hardware is a Phase 2 task.

## Deviations from PLAN.md

| # | Deviation | Reason |
|---|-----------|--------|
| 1 | 4 buttons (via PCF8574) instead of GPIO | I2C expander frees 7 GPIO pins for audio and buttons 3-4 |
| 2 | Keypad on PCF8574 I2C expander (addr 0x20) | Frees GPIO pins; same HAL interface |
| 3 | NFC + battery + keypad share OLED I2C bus | Different I2C addresses (0x20, 0x24, 0x36, 0x3C) |
| 4 | Display RST on GPIO 38 (was tied to Vext) | Freed by keypad-to-I2C move |
| 5 | 16 MB flash / 2 MB PSRAM (was 4 MB) | Board choice: Heltec V4.3 |
| 6 | No LUA_32BITS | 64-bit Lua matches desktop; scripts behave identically |
| 7 | LVGL host rendering not done | Building LVGL 9.2 in the host test build was not completed |
| 8 | preset_select screen template has TODO | Presets array parsing not implemented |

## Files Modified Outside firmware/

| File | Change |
|------|--------|
| `.github/workflows/ci.yml` | Added `esp32-build` and `firmware-test` jobs |
| `tools/format.sh` | Added `firmware/` to clang-format search; excluded `build/` and `managed_components/` |
| `firmware/esp32/README.md` | Updated with build instructions and architecture |
| `hardware/field-box/README.md` | Updated with Heltec V4.3 BOM and wiring reference |
| `tools/dev/Dockerfile.esp32` | Created (single FROM line) |
