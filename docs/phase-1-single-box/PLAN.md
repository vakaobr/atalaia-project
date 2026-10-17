<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 1 -- Single Box: Implementation Plan

Gate: **one box runs a 2-hour club game with no restarts.**

Constraint: hardware has not arrived; this machine has no C compiler.
All builds run in Docker. What can be verified now is separated from
what needs real hardware.

---

## Scope

### In scope (software -- buildable and testable now)

- ESP-IDF project skeleton with CMake, custom partition table, Kconfig
  defaults and `sdkconfig.defaults` for ESP32-S3.
- IDF component wrapper for the existing core (no core changes).
- HAL abstraction layer: headers, ESP-IDF implementations and stub
  implementations for buttons, keypad, LEDs, display, NFC, audio and
  battery.
- Shell entry point (`app_main`): FreeRTOS task architecture (4 tasks),
  node lifecycle, command dispatch, event injection.
- Game timer with countdown and score freeze via `game.end`.
- Preset storage on LittleFS: save, list, load, delete (up to 32
  slots); mode source files stored alongside presets.
- State persistence to LittleFS: Lua state table, game time and scores
  written every second; resume on reboot.
- On-device preset picker: admin PIN on keypad, preset list, timer
  adjust, start.
- Screen templates as C functions backed by LVGL v9: standby, countdown,
  defused, exploded, final_score, paused, preset_select, status,
  wifi_setup.
- Wi-Fi captive portal: SoftAP + DNS redirect + embedded HTML config
  page for first-time setup.
- Dockerfile for ESP-IDF cross-compilation (`tools/dev/Dockerfile.esp32`).
- CI job: ESP-IDF cross-compile gate (`idf.py build`).
- HAL stub integration tests (run on Linux in `atalaia-dev` image).
- Extend `tools/format.sh` to cover `firmware/`.
- Hardware bring-up runbook (`firmware/esp32/docs/BRING_UP.md`).

### In scope (hardware -- deferred to arrival)

- First-boot smoke test (blink + serial).
- Display bring-up (ILI9341 / ST7789 colour check).
- Button debounce timing on real switches.
- NFC read distance, audio quality, battery gauge accuracy.
- The 2-hour stability gate (the phase 1 gate).

### Out of scope (later phases)

- LoRa radio and field mesh (phase 2; the SX1262 is put to sleep).
- Field controller and `field.lua` scripts (phase 2).
- Android shell and Flutter app (phase 3).
- Declarative screen template format in mode `assets/` (phase 3, when
  the Flutter renderer needs the same templates).
- A/B OTA updates with Ed25519 signature (phase 2; the partition table
  reserves the slots now).
- Companion app or BLE provisioning (post phase 1).
- Proxy tier (thin nodes run on the controller; needs phase 2).
- Precompiled Lua bytecode for Reduced tier (optimisation; deferred
  until profiling on real hardware).

---

## Constraints from ADR.md (all 16 respected)

| # | Constraint | How the plan respects it |
|---|------------|--------------------------|
| 1 | No core changes | Core is used as-is; only an IDF component wrapper is added |
| 2 | HAL-first implementation order | Phase A lands all HAL modules before phases B--D use them |
| 3 | LVGL v9 only | Screen templates in phase C use LVGL v9 API via `esp_lvgl_port` |
| 4 | LittleFS, not SPIFFS | Preset store and state persistence use LittleFS (phase B) |
| 5 | Game timer in the shell | Timer logic is in `game_timer.c` (phase B); no core changes |
| 6 | Two Docker images | `atalaia-dev` for core/sim tests; `espressif/idf:v5.3.2` for firmware |
| 7 | Pin assignments via Kconfig | `Kconfig.projbuild` defines all pin symbols (phase A) |
| 8 | Screen templates are C functions | Each template is a C function that builds LVGL widgets (phase C) |
| 9 | Single task for LVGL | All LVGL API calls happen on `lvgl_task`; game_task sends via queue |
| 10 | State persistence to LittleFS | `/state/current.bin` written every 1 s (phase B) |
| 11 | Captive portal for setup | SoftAP + DNS + HTTP with embedded HTML (phase C) |
| 12 | Cross-compile CI must pass | CI job added in phase A; required on all subsequent merges |
| 13 | `LUA_32BITS` on ESP32 | Set in the IDF component wrapper (phase A) |
| 14 | Bring-up checklist | `BRING_UP.md` written in phase D |
| 15 | SPDX headers on every file | All new files get `GPL-3.0-or-later` per `REUSE.toml` |
| 16 | Format with `.clang-format` | `tools/format.sh` extended to cover `firmware/` (phase A) |

---

## Phase A: Build system, HAL layer, ESP-IDF project skeleton

### Goal

A firmware project that cross-compiles for ESP32-S3 in Docker, with
the core linked as an IDF component, all HAL headers defined, and stub
implementations that let the shell compile on Linux for integration
testing. No game logic yet.

### Files to create

| File | Purpose |
|------|---------|
| `firmware/esp32/CMakeLists.txt` | IDF project root (standard boilerplate + `EXTRA_COMPONENT_DIRS`) |
| `firmware/esp32/sdkconfig.defaults` | ESP32-S3 target, PSRAM auto-detect, flash size, partition table path |
| `firmware/esp32/partitions.csv` | Custom partition table: nvs (24 KB), otadata (8 KB), phy_init (4 KB), ota_0 (1.5 MB), ota_1 (1.5 MB), storage/littlefs (1 MB) |
| `firmware/esp32/main/CMakeLists.txt` | Main component: lists all shell sources, `EMBED_FILES` for the setup HTML |
| `firmware/esp32/main/idf_component.yml` | Dependencies: `espressif/lvgl`, `espressif/esp_lvgl_port`, `joltwallet/littlefs` |
| `firmware/esp32/main/Kconfig.projbuild` | Pin assignment symbols for every HAL subsystem, display controller choice, tier-specific memory limits |
| `firmware/esp32/main/shell.c` | `app_main()` stub: detect PSRAM, init HAL, create tasks; empty game loop |
| `firmware/esp32/components/atalaia_core/CMakeLists.txt` | IDF component wrapper referencing `core/` sources; sets `LUA_32BITS` |
| `firmware/esp32/main/hal/hal.h` | Aggregate `hal_t` struct: one ops pointer per subsystem |
| `firmware/esp32/main/hal/hal_buttons.h` | `hal_button_ops_t`: `init`, `poll` |
| `firmware/esp32/main/hal/hal_keypad.h` | `hal_keypad_ops_t`: `init`, `scan` |
| `firmware/esp32/main/hal/hal_leds.h` | `hal_led_ops_t`: `init`, `fill`, `set`, `show`, `set_brightness` |
| `firmware/esp32/main/hal/hal_display.h` | `hal_display_ops_t`: `init`, `flush`, `set_brightness` |
| `firmware/esp32/main/hal/hal_nfc.h` | `hal_nfc_ops_t`: `init`, `poll` |
| `firmware/esp32/main/hal/hal_audio.h` | `hal_audio_ops_t`: `init`, `play_wav`, `tone`, `set_volume` |
| `firmware/esp32/main/hal/hal_battery.h` | `hal_battery_ops_t`: `init`, `read` |
| `firmware/esp32/main/hal/stub/hal_stub.c` | All stub implementations: return success, fixed values, record calls |
| `firmware/esp32/main/hal/stub/hal_stub.h` | `hal_stub_init(hal_t *)` |
| `firmware/esp32/main/hal/esp/hal_esp_buttons.c` | ESP-IDF GPIO button driver with debounce (30 ms) and hold detection (250 ms) |
| `firmware/esp32/main/hal/esp/hal_esp_keypad.c` | ESP-IDF 3x4 matrix keypad scanner |
| `firmware/esp32/main/hal/esp/hal_esp_leds.c` | ESP-IDF WS2812 via RMT peripheral |
| `firmware/esp32/main/hal/esp/hal_esp_display.c` | ESP-IDF SPI TFT init + LVGL flush (DMA, double-buffered) |
| `firmware/esp32/main/hal/esp/hal_esp_nfc.c` | ESP-IDF PN532 I2C driver |
| `firmware/esp32/main/hal/esp/hal_esp_audio.c` | ESP-IDF I2S output + WAV file playback from LittleFS/SD |
| `firmware/esp32/main/hal/esp/hal_esp_battery.c` | ESP-IDF MAX17048 I2C fuel gauge |
| `firmware/esp32/main/hal/esp/hal_esp.h` | `hal_esp_init(hal_t *, hal_pin_config_t *)` |
| `tools/dev/Dockerfile.esp32` | `FROM espressif/idf:v5.3.2` (no additions needed) |

### Files to modify

| File | Change |
|------|--------|
| `tools/format.sh` | Add `firmware/` to the clang-format search path |
| `.github/workflows/ci.yml` | Add `esp32-build` job: cross-compile using `espressif/idf:v5.3.2` |

### Validation (phase A)

**ESP-IDF cross-compile** (must produce a `.bin` with exit 0):

```sh
# From Git Bash on Windows:
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/project" -w /project/firmware/esp32 \
  espressif/idf:v5.3.2 \
  bash -c "idf.py set-target esp32s3 && idf.py build"
```

**Existing core tests still pass** (no regressions):

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**Format check covers firmware/**:

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh tools/format.sh --check
```

---

## Phase B: Game timer, preset storage, command dispatch, state persistence

### Goal

The shell can create a node, load a mode from LittleFS, run the game
loop with a countdown timer, dispatch hardware commands, persist state,
and resume after a simulated reboot. All testable on Linux with HAL
stubs.

### Files to create

| File | Purpose |
|------|---------|
| `firmware/esp32/main/game_timer.h` | `game_timer_t` struct; `game_timer_init`, `game_timer_tick` (returns true when expired), `game_timer_remaining_ms` |
| `firmware/esp32/main/game_timer.c` | Shell-owned countdown timer; sends `game.end` via `atalaia_node_input` on expiry |
| `firmware/esp32/main/command_dispatch.h` | `command_dispatch(target, method, args_json, hal, queues)` |
| `firmware/esp32/main/command_dispatch.c` | Parses target/method from the core's command callback; routes to screen queue, audio queue, LED ops |
| `firmware/esp32/main/preset_store.h` | `preset_store_init`, `preset_store_list`, `preset_store_load`, `preset_store_save`, `preset_store_delete` |
| `firmware/esp32/main/preset_store.c` | LittleFS-backed preset storage: reads `/presets/NNN.json` + `/modes/<id>/node.lua` |
| `firmware/esp32/main/state_persist.h` | `state_persist_save(node, game_timer)`, `state_persist_load(...)`, `state_persist_clear()` |
| `firmware/esp32/main/state_persist.c` | Writes `/state/current.bin` (Lua state table + game time + scores) to LittleFS; reads on boot to resume |
| `firmware/esp32/main/node_runner.h` | `node_runner_t`: owns the `atalaia_node_t`, game timer, preset ref; provides `node_runner_tick(delta_ms)` |
| `firmware/esp32/main/node_runner.c` | Glue: creates the node, loads mode source, injects hardware events, advances time, calls game_timer_tick, calls state_persist_save every 1 s |

### Files to modify

| File | Change |
|------|--------|
| `firmware/esp32/main/shell.c` | Wire up `node_runner` in `game_task`; register command callback; init LittleFS; init preset store |
| `firmware/esp32/main/CMakeLists.txt` | Add new source files |

### Tests to create (HAL stub integration tests, run on Linux)

| File | What it tests |
|------|---------------|
| `firmware/esp32/test/test_game_timer.c` | Start with 10 s duration; advance time in steps; verify `game.end` is sent exactly at expiry; verify unlimited mode (duration 0) never expires |
| `firmware/esp32/test/test_command_dispatch.c` | Feed `command("ui", "screen", "[\"countdown\", {\"left\": 42}]")` and verify the correct `screen_update_t` is produced; feed `command("ring", "fill", "[\"red\"]")` and verify LED stub records the call |
| `firmware/esp32/test/test_preset_store.c` | Save 3 presets to a temp directory; list; load by index; delete; verify round-trip |
| `firmware/esp32/test/test_state_persist.c` | Start a game, advance 5 s, persist; destroy the node; recreate and resume from persisted state; verify game time and scores match |
| `firmware/esp32/test/test_node_runner.c` | Load domination mode via preset store; send team_input.hold; advance time; verify zone.captured is emitted |
| `firmware/esp32/test/CMakeLists.txt` | Standalone CMake project that links shell sources + core + stubs (no IDF) |
| `firmware/esp32/test/check.h` | Minimal test macros (same pattern as `core/tests/check.h`) |

### Validation (phase B)

**HAL stub integration tests on Linux**:

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cmake -S /src/firmware/esp32/test -B /tmp/fw-test \
         -DCORE_DIR=/src/core \
         -DCMAKE_BUILD_TYPE=Debug && \
         cmake --build /tmp/fw-test && \
         ctest --test-dir /tmp/fw-test --output-on-failure"
```

**ESP-IDF cross-compile still passes** (with new files):

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/project" -w /project/firmware/esp32 \
  espressif/idf:v5.3.2 \
  bash -c "idf.py set-target esp32s3 && idf.py build"
```

---

## Phase C: Screen templates, Wi-Fi captive portal, on-device setup flow

### Goal

LVGL-backed screen templates render all mode screens and system UI.
The captive portal lets a new node be configured from any phone. The
preset picker lets a GM start a game from the keypad. All compile in
the IDF build; the preset picker and captive portal logic are tested
with stubs on Linux.

### Files to create

| File | Purpose |
|------|---------|
| `firmware/esp32/main/screen_renderer.h` | `screen_render(template_name, data_json, lv_obj_t *parent)`; `screen_renderer_init()` |
| `firmware/esp32/main/screen_renderer.c` | Template router + each template function: `screen_standby`, `screen_countdown`, `screen_defused`, `screen_exploded`, `screen_final_score`, `screen_paused`, `screen_status` |
| `firmware/esp32/main/screen_types.h` | `screen_update_t` struct (template name + data JSON); FreeRTOS queue typedef |
| `firmware/esp32/main/preset_ui.h` | `preset_ui_init`, `preset_ui_handle_key` |
| `firmware/esp32/main/preset_ui.c` | Keypad-driven UI: admin PIN entry, preset list navigation, timer adjust, start confirmation; sends selected preset to `node_runner` |
| `firmware/esp32/main/wifi_setup.h` | `wifi_setup_start()`, `wifi_setup_stop()` |
| `firmware/esp32/main/wifi_setup.c` | SoftAP `atalaia-XXXX` + DNS server (resolve all to 192.168.4.1) + HTTP server; serves embedded HTML form; writes config to NVS on submit; signals reboot |
| `firmware/esp32/main/wifi_setup.html` | Minimal HTML config page (< 15 KB): node name, radio region dropdown, team count/colours, admin PIN, brightness, volume; server-side validation |
| `firmware/esp32/main/config_store.h` | `config_store_get/set` for NVS-backed config: node_name, region, admin_pin, team_count, team_colors, brightness, volume, configured flag |
| `firmware/esp32/main/config_store.c` | NVS read/write wrappers |

### Files to modify

| File | Change |
|------|--------|
| `firmware/esp32/main/shell.c` | On boot: check NVS `configured` flag; if not set, start `wifi_setup`; otherwise init `preset_ui` and enter normal mode. Wire `lvgl_task` to dequeue `screen_update_t` and call `screen_render`. |
| `firmware/esp32/main/node_runner.c` | On command callback `("ui", "screen", ...)`, enqueue a `screen_update_t` |
| `firmware/esp32/main/CMakeLists.txt` | Add new sources; add `wifi_setup.html` to `EMBED_FILES` |

### Tests to create

| File | What it tests |
|------|---------------|
| `firmware/esp32/test/test_screen_renderer.c` | Call each template function with representative data; verify no crash; verify the returned LVGL object tree has the expected label text (link against LVGL stub or `lv_test` harness) |
| `firmware/esp32/test/test_preset_ui.c` | Feed keypad sequences (PIN + select + adjust + start); verify the correct preset index is loaded; verify wrong PIN is rejected |
| `firmware/esp32/test/test_config_store.c` | Set/get each config key; verify defaults; verify `configured` flag round-trip |

### Validation (phase C)

**HAL stub integration tests (all, including new)**:

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cmake -S /src/firmware/esp32/test -B /tmp/fw-test \
         -DCORE_DIR=/src/core \
         -DCMAKE_BUILD_TYPE=Debug && \
         cmake --build /tmp/fw-test && \
         ctest --test-dir /tmp/fw-test --output-on-failure"
```

**ESP-IDF cross-compile with all features**:

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/project" -w /project/firmware/esp32 \
  espressif/idf:v5.3.2 \
  bash -c "idf.py set-target esp32s3 && idf.py build"
```

**Format check**:

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh tools/format.sh --check
```

---

## Phase D: Integration, CI, hardware bring-up, documentation

### Goal

All pieces connect end-to-end: the shell boots, checks config, shows
setup or preset picker, loads a mode, runs a full game with timer and
score freeze, persists state, and can resume. CI gates the cross-compile
and stub tests. A bring-up runbook is ready for when hardware arrives.
Documentation is updated.

### Files to create

| File | Purpose |
|------|---------|
| `firmware/esp32/docs/BRING_UP.md` | Hardware bring-up checklist: first-boot smoke test (blink + serial), display init, button wiring, keypad scan, NFC read, audio output, battery gauge, Wi-Fi portal on phone, full 2-hour game test |
| `firmware/esp32/main/mem_monitor.c` | Low-priority task (10 s interval): logs `heap_caps_get_info` for DRAM and PSRAM to serial; reports LVGL and Lua memory in debug builds |
| `firmware/esp32/main/mem_monitor.h` | `mem_monitor_start()` |

### Files to modify

| File | Change |
|------|--------|
| `firmware/esp32/main/shell.c` | Start `mem_monitor`; full boot sequence: PSRAM detect -> tier select -> `mem_limit` -> HAL init -> config check -> setup or normal mode |
| `firmware/esp32/main/CMakeLists.txt` | Add `mem_monitor.c` |
| `.github/workflows/ci.yml` | Add `esp32-build` job (if not done in phase A) and `firmware-test` job for HAL stub tests |
| `firmware/esp32/README.md` | Replace placeholder with real documentation: build instructions, architecture overview, task diagram, pin table, Kconfig options, Docker commands |
| `hardware/field-box/README.md` | Expand with wiring reference, pin assignment table, assembly sequence |

### Tests to create

| File | What it tests |
|------|---------------|
| `firmware/esp32/test/test_integration.c` | End-to-end: init shell with stubs -> load domination via preset store -> send game.start -> send team_input.hold -> advance 120 s (2 min sample) -> verify zone.captured emitted + screen updates queued + timer counting down -> send game.end manually or let timer expire -> verify status is ENDED and scores are frozen |

### Validation (phase D)

**Full integration test suite**:

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cmake -S /src/firmware/esp32/test -B /tmp/fw-test \
         -DCORE_DIR=/src/core \
         -DCMAKE_BUILD_TYPE=Debug && \
         cmake --build /tmp/fw-test && \
         ctest --test-dir /tmp/fw-test --output-on-failure"
```

**ESP-IDF cross-compile (final)**:

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/project" -w /project/firmware/esp32 \
  espressif/idf:v5.3.2 \
  bash -c "idf.py set-target esp32s3 && idf.py build"
```

**All existing CI checks still pass**:

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**Format check (full repo)**:

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh tools/format.sh --check
```

---

## Acceptance criteria

All criteria are testable with the Docker commands listed above. The
first three can be verified before hardware arrives; the last one is
the phase 1 gate and requires the prototype.

### AC-1: ESP-IDF cross-compilation succeeds

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/project" -w /project/firmware/esp32 \
  espressif/idf:v5.3.2 \
  bash -c "idf.py set-target esp32s3 && idf.py build"
```

**Expected:** exit 0, produces `build/atalaia_esp32.bin`.

### AC-2: HAL stub integration tests pass

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "cmake -S /src/firmware/esp32/test -B /tmp/fw-test \
         -DCORE_DIR=/src/core \
         -DCMAKE_BUILD_TYPE=Debug && \
         cmake --build /tmp/fw-test && \
         ctest --test-dir /tmp/fw-test --output-on-failure"
```

**Expected:** exit 0, all tests pass. Tests cover:

- Game timer fires `game.end` at the correct time.
- Command dispatch routes screen and audio commands correctly.
- Preset store round-trips save/list/load/delete.
- State persistence survives a simulated reboot.
- Node runner loads a mode and processes events end-to-end.
- Preset UI accepts correct PIN and rejects wrong PIN.
- Config store reads and writes NVS values.
- Integration test runs a 2-minute simulated game with timer, scoring,
  freeze and screen updates.

### AC-3: Existing CI checks are unaffected

```sh
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**Expected:** exit 0. Core tests, simulator tests, mode tests,
protocol checks and formatting all pass unchanged.

### AC-4: 2-hour club game on real hardware (deferred to hardware arrival)

Flash the firmware to a Field Box prototype. Run through the bring-up
checklist in `BRING_UP.md`. Start a Domination or Bomb preset from the
keypad. Play for 2 hours with team button presses and keypad codes.
Verify:

- No reboots or freezes during the entire session.
- Scores update correctly on the display.
- Game timer counts down and freezes scores at zero.
- Pull the battery mid-game; reconnect; verify the game resumes from
  the persisted state and emits `node.rebooted`.
- Display, LEDs, audio and NFC all function.

This criterion closes the phase 1 gate.

---

## Phase dependency graph

```
Phase A ──> Phase B ──> Phase C ──> Phase D
  │                       │            │
  │  (cross-compile)      │  (LVGL)    │  (integration)
  └───────────────────────┴────────────┘
                 │
          CI gates all merges
```

Phase A must complete first (build system + HAL are prerequisites for
everything else). Phases B and C have a soft dependency: B lands the
game logic and preset store that C's UI drives, so B should complete
before C starts the preset picker. Phase D ties everything together and
produces the final documentation.

---

## Summary of new files by directory

```
firmware/esp32/
    CMakeLists.txt
    sdkconfig.defaults
    partitions.csv
    main/
        CMakeLists.txt
        idf_component.yml
        Kconfig.projbuild
        shell.c
        game_timer.c / .h
        command_dispatch.c / .h
        preset_store.c / .h
        state_persist.c / .h
        node_runner.c / .h
        screen_renderer.c / .h
        screen_types.h
        preset_ui.c / .h
        wifi_setup.c / .h
        wifi_setup.html
        config_store.c / .h
        mem_monitor.c / .h
        hal/
            hal.h
            hal_buttons.h
            hal_keypad.h
            hal_leds.h
            hal_display.h
            hal_nfc.h
            hal_audio.h
            hal_battery.h
            stub/
                hal_stub.c
                hal_stub.h
            esp/
                hal_esp.h
                hal_esp_buttons.c
                hal_esp_keypad.c
                hal_esp_leds.c
                hal_esp_display.c
                hal_esp_nfc.c
                hal_esp_audio.c
                hal_esp_battery.c
    components/
        atalaia_core/
            CMakeLists.txt
    test/
        CMakeLists.txt
        check.h
        test_game_timer.c
        test_command_dispatch.c
        test_preset_store.c
        test_state_persist.c
        test_node_runner.c
        test_preset_ui.c
        test_config_store.c
        test_screen_renderer.c
        test_integration.c
    docs/
        BRING_UP.md
tools/dev/
    Dockerfile.esp32
```

Total: ~50 new files. No existing core or simulator files are modified.
