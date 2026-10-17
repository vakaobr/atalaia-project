<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 1 -- Single Box: Architecture Decisions

Nine decisions settle the structure of the ESP-IDF firmware shell before
implementation begins. Each one answers a question the research phase
identified and creates a constraint that the planning phase must respect.

---

### ADR-P1-1: HAL abstraction layer

**Status:** Accepted

**Context:** The firmware must drive GPIO buttons, a 3x4 matrix keypad,
WS2812 LEDs (RMT), an SPI TFT display, a PN532 NFC reader (I2C), an
I2S audio amplifier, a MAX17048 fuel gauge (I2C), and later LoRa and
GPS. Testing without hardware requires stub implementations. The core
already isolates all hardware behind the `command` callback, so the
shell is the only code that touches ESP-IDF peripherals.

**Decision:** Each hardware subsystem gets a pair of files
(`hal_<name>.h` / `hal_<name>.c`) that exposes a function-pointer
struct (`hal_<name>_ops_t`) plus a concrete ESP-IDF implementation
and a stub implementation selected at compile time.

The HAL headers live in `firmware/esp32/main/hal/` and depend only on
standard C types and project-level types (`atalaia_team_color_t`,
etc.), never on ESP-IDF headers. The implementations in
`firmware/esp32/main/hal/esp/` include ESP-IDF headers. Stubs in
`firmware/esp32/main/hal/stub/` return success / fixed values and
record calls for test assertions.

The shell holds a `hal_t` aggregate that owns one ops pointer per
subsystem, initialised at boot by either `hal_esp_init()` or
`hal_stub_init()`. Every shell module receives this aggregate by
pointer; no module calls `gpio_set_level` or any IDF function directly.

Function-pointer dispatch costs one indirect call per HAL invocation.
On a 240 MHz Xtensa core this is negligible compared to the SPI and
I2C transactions underneath.

Concrete ops structs for phase 1:

| Struct | Functions |
|--------|-----------|
| `hal_button_ops_t` | `init`, `poll` (returns bitmask of pressed buttons) |
| `hal_keypad_ops_t` | `init`, `scan` (returns key or KEY_NONE) |
| `hal_led_ops_t` | `init`, `fill(r,g,b)`, `set(index,r,g,b)`, `show`, `set_brightness` |
| `hal_display_ops_t` | `init`, `flush(area, color_p, ready_cb)`, `set_brightness` |
| `hal_nfc_ops_t` | `init`, `poll` (returns uid+data or NFC_NONE) |
| `hal_audio_ops_t` | `init`, `play_wav(path)`, `tone(freq_hz, duration_ms)`, `set_volume` |
| `hal_battery_ops_t` | `init`, `read` (returns voltage_mv, percent, charging) |

The `init` functions receive a `hal_pin_config_t` read from Kconfig, so
pin assignments are never hardcoded. Buttons and the keypad are polled;
the display flush is called by LVGL; NFC is polled at a lower rate; the
battery is read on a slow timer (30 s).

**Consequences:**
- Every HAL module can be tested on Linux without ESP-IDF by linking the
  stub implementation.
- Adding a new peripheral (GPS, IMU, LoRa) follows the same pattern:
  add an ops struct, an ESP implementation and a stub.
- Pin assignments live in Kconfig, not in code, so different boards
  need only a different `sdkconfig.defaults`.
- The indirection prevents the compiler from inlining HAL calls, but
  the overhead is irrelevant for I/O-bound operations.

---

### ADR-P1-2: LVGL version and display architecture

**Status:** Accepted

**Context:** The firmware renders screen templates (`ui.screen`) and
system UI (preset picker, Wi-Fi setup, status) on a small TFT or OLED.
LVGL v8 (8.4.x) has a large installed base and stable API. LVGL v9
(9.2.x) redesigned its driver model (removing `lv_disp_drv_t` in
favour of `lv_display_create`), added draw units for GPU offload,
simplified memory management, and is the version the ESP component
registry (`espressif/lvgl`) tracks for ESP-IDF v5.3+. The existing
ESP-IDF LVGL port (`esp_lvgl_port`) targets v9.

**Decision:** Use LVGL v9 (latest 9.2.x) via the ESP component
registry, with `esp_lvgl_port` for FreeRTOS integration.

Display driver architecture:

1. `hal_display_ops_t.flush(area, color_p, ready_cb)` pushes pixels
   over SPI using ESP-IDF's `spi_device_queue_trans` (DMA). When the
   DMA transfer finishes, the ISR calls `ready_cb`, which calls
   `lv_display_flush_ready` to let LVGL proceed. This gives full
   double-buffering with no CPU copy.

2. Two LVGL draw buffers in PSRAM (Full tier) or internal SRAM (Reduced
   tier), each sized to 1/10 of the screen (320x240x2 = 153,600 bytes
   total; 1/10 = ~15 KB per buffer). On the Reduced tier with a
   monochrome OLED, the buffers are much smaller (~1 KB each for
   128x64x1).

3. LVGL tick: `esp_lvgl_port` registers a 2 ms `esp_timer` that calls
   `lv_tick_inc(2)`. `lv_timer_handler()` runs on the LVGL task (see
   ADR-P1-7).

4. Screen templates: a `screen_renderer` module maps `(template_name,
   data_json)` to LVGL widget trees. Templates are built in C as
   functions (`screen_render_countdown`, `screen_render_standby`, etc.)
   that create and update widgets. Data values (seconds left, team name,
   score) are patched into existing label/bar widgets on each call, not
   rebuilt from scratch.

5. Display controller selection (ILI9341 vs ST7789) is a Kconfig choice
   that picks the initialisation command sequence. The flush path is
   identical because both controllers accept raw pixel data over SPI
   after the correct init.

**Consequences:**
- LVGL v9 is the version ESP-IDF tracks, so component updates come
  through `idf.py add-dependency` with no manual patching.
- The DMA flush path uses zero CPU time for pixel transfer.
- Switching from TFT to monochrome OLED requires only a different
  Kconfig selection and a smaller buffer.
- Screen templates are C functions, not a data format, which keeps
  phase 1 simple. A declarative template format (mode `assets/`
  directory) is deferred to phase 3 when the Flutter renderer needs
  the same templates.
- LVGL v9 drops some v8 widget names (`lv_btn_create` stays, but
  `lv_page` is gone). Existing LVGL v8 tutorials and examples do not
  apply directly; the v9 migration guide covers the differences.

---

### ADR-P1-3: Game timer ownership

**Status:** Accepted

**Context:** Every mode can set a game duration. When the timer expires,
scores freeze and the last screen stays on display. The core already
handles `game.end` correctly: it transitions the node to `ENDED` status,
`score.add` becomes a no-op, `atalaia_node_input` rejects non-game
events, and timers stop firing (`node.c` lines handling
`ATALAIA_NODE_ENDED`). The question is whether the countdown timer
should live inside the core (so the simulator and every platform gets
it) or in the ESP-IDF shell.

**Decision:** The game timer lives in the shell, not in the core.

The shell maintains a `game_timer_t` with `duration_ms` (0 = unlimited)
and `elapsed_ms`. On each tick of the main loop:

1. If the game is running and `duration_ms > 0`, the shell increments
   `elapsed_ms` by the wall-clock delta since the last tick.
2. If `elapsed_ms >= duration_ms`, the shell calls
   `atalaia_node_input(node, "game.end", NULL)`.
3. The shell calls `atalaia_node_advance(node, elapsed_ms)` to move
   game time forward.

The remaining time is displayed on a persistent status bar (not managed
by mode scripts) that the shell renders in LVGL below or above the
mode's screen area.

**Rationale for shell-owned, not core-owned:**

- The core's contract is "the host owns the clock". Adding a timer to
  the core would require the core to know wall-clock time, breaking
  this contract and the replay guarantee.
- The simulator already has `LiveGame` (in `live.py`) which manages
  game time externally. Adding a core timer would duplicate this and
  create two sources of truth.
- The shell is the right place because it already manages the
  relationship between wall-clock time and game time (pause, speed).
- Modes that want their own internal timers (bomb fuse) already use
  `after(fuse_s, fn)`, which runs on game time. The game-level
  countdown is a different concern.

**Consequences:**
- The core remains clock-agnostic. No core changes needed.
- Every platform shell (ESP32, Linux, Android) must implement its own
  game timer. This is three lines of code per platform.
- The simulator's `LiveGame` already does this; it just needs to also
  call `atalaia_node_input(node, "game.end", NULL)` when the timer
  expires, which it likely already does or trivially can.
- The game duration is a preset parameter, not a core concept. The
  shell reads it from the preset and configures the timer before
  starting the game.

---

### ADR-P1-4: Preset storage format

**Status:** Accepted

**Context:** A node must cache at least 10 presets for stand-alone
operation (spec section 13). A preset consists of:

- Mode identity (`org.atalaia.domination`, version)
- Parameter values (JSON, typically < 1 KB)
- The mode's `node.lua` source (typically 1--5 KB)
- The mode's `mode.yaml` manifest (< 1 KB)
- Optionally: audio clips and screen assets (phase 3)

Three storage options exist on ESP32:

| Option | Max entry size | Wear levelling | File-like access |
|--------|---------------|----------------|------------------|
| NVS | 4000 bytes per blob | Built-in | No (key-value) |
| SPIFFS | Partition size | Poor (no dirs) | Yes |
| LittleFS | Partition size | Good (CoW) | Yes (with dirs) |

**Decision:** Use LittleFS for preset and mode storage, on a dedicated
data partition. NVS is reserved for small configuration values only
(node name, radio region, admin PIN, Wi-Fi credentials, brightness,
volume).

Partition layout:

| Name | Type | Size | Purpose |
|------|------|------|---------|
| nvs | data/nvs | 24 KB | Key-value config |
| otadata | data/ota | 8 KB | A/B OTA bookkeeping |
| phy_init | data/phy | 4 KB | RF calibration |
| ota_0 | app/ota_0 | 1.5 MB | Application slot A |
| ota_1 | app/ota_1 | 1.5 MB | Application slot B |
| storage | data/littlefs | 1 MB | Presets, modes, state, audio clips |

The storage partition holds:

```
/presets/
    001.json          -- preset metadata: mode_id, version, params, label
    002.json
    ...
/modes/
    org.atalaia.domination/
        mode.yaml
        node.lua
    org.atalaia.bomb/
        mode.yaml
        node.lua
/state/
    current.bin       -- persisted game state (see ADR-P1-6 note on state)
/audio/
    captured.wav
    armed.wav
    ...
```

The `preset_store` module provides:

- `preset_store_list()` -> array of `{index, label, mode_id}`
- `preset_store_load(index)` -> `{mode_id, params_json, source, source_len}`
- `preset_store_save(index, preset)` -> bool
- `preset_store_delete(index)` -> bool

A maximum of 32 preset slots is enough. Each preset JSON is < 2 KB; the
mode source is shared across presets that use the same mode.

**Rationale for LittleFS over NVS:**

- NVS entries are capped at ~4000 bytes, which is tight for a `node.lua`
  with comments. Splitting across multiple NVS entries adds complexity.
- LittleFS supports directories, which map naturally to the mode
  package structure.
- LittleFS has better wear levelling than SPIFFS (copy-on-write) and
  supports directories (SPIFFS does not).
- NVS remains appropriate for the ~20 small config values that rarely
  change.

**Rationale for NVS for config (not LittleFS):**

- NVS is transactional and crash-safe for single key updates.
- Config values (node name, PIN, region) are small strings or integers.
- ESP-IDF's Wi-Fi and Bluetooth stacks expect NVS for credentials.

**Consequences:**
- The partition table is custom (`partitions.csv`), not the default.
- LittleFS must be added as an ESP-IDF component (`joltwallet/littlefs`
  via the component registry).
- Preset upload (from the controller over Wi-Fi or BLE) writes files to
  LittleFS. This is a phase 2 concern; in phase 1 presets are flashed
  as part of the LittleFS image.
- The 1 MB storage partition holds roughly 50 mode+preset combinations
  (at ~5 KB per mode + ~2 KB per preset) with room for audio clips.

---

### ADR-P1-5: Wi-Fi captive-portal setup flow

**Status:** Accepted

**Context:** On first boot, the node has no configuration (no name, no
radio region, no teams). The spec (section 13) requires a setup page.
Three approaches:

| Approach | Pros | Cons |
|----------|------|------|
| Captive portal (SoftAP + HTTP) | Works with any phone or laptop; no app needed; standard ESP-IDF APIs | User must connect to the node's AP |
| WPS | One-button pairing | Only for Wi-Fi credential transfer, not config; many routers disable it |
| Bluetooth provisioning | Cleaner UX with a companion app | Requires a companion app that does not exist yet |

**Decision:** Use captive portal over SoftAP. The node opens an AP named
`atalaia-XXXX` (last 4 hex digits of the MAC) with no password. A
connected device is redirected to a configuration page served by the
node's HTTP server.

Implementation:

1. On boot, if NVS key `configured` is not set, enter setup mode.
2. Start SoftAP with SSID `atalaia-XXXX`, no password, channel 1,
   max 1 connection.
3. Start a DNS server that resolves all domains to the node's IP
   (192.168.4.1). This triggers the captive-portal detection on
   Android, iOS and desktop browsers.
4. Start an HTTP server (ESP-IDF `httpd`) serving a single-page
   configuration form. The page is a static HTML file stored in the
   firmware binary (embedded via `EMBED_FILES` in CMakeLists.txt).
5. The form collects: node name, radio region (dropdown), team count
   and colours, admin PIN (4-6 digits), brightness, volume.
6. On submit, the server validates the input, writes each value to NVS,
   sets `configured = 1`, and reboots into normal mode.
7. Re-entering setup: the admin enters the PIN on the keypad and selects
   "Setup" from the admin menu, or a hardware reset button is held
   during boot.

The HTML page is minimal (< 15 KB), uses no JavaScript framework, and
works on any mobile browser. Form validation is server-side; the page
shows success or an error message after POST.

**Consequences:**
- No companion app is needed for setup. Any phone or laptop works.
- The setup AP is unauthenticated, but it is only active during setup
  and accepts only one connection. The admin PIN protects re-entry.
- The node cannot connect to an existing Wi-Fi network and serve
  the portal at the same time (SoftAP and station mode together is
  possible on ESP32 but adds complexity). In phase 1 the node uses
  Wi-Fi only for setup; game communication is local (no Wi-Fi mesh
  until phase 2).
- The embedded HTML file increases the firmware binary by ~15 KB,
  which is negligible in a 1.5 MB app partition.

---

### ADR-P1-6: Memory budget

**Status:** Accepted

**Context:** The ESP32-S3 has ~320 KB of usable DRAM (after the IDF
runtime, Wi-Fi and BLE stacks take their share) and optionally 2-8 MB
of PSRAM. The firmware must fit: LVGL draw buffers, the Lua heap (via
the core's allocator), core state (`atalaia_node_t` + timers + score),
FreeRTOS task stacks, HAL driver state, and the HTTP server for setup.

**Decision:** Define two memory profiles, selected at boot based on
PSRAM detection (`esp_psram_get_size()`):

#### Full tier (PSRAM present)

| Consumer | Location | Budget |
|----------|----------|--------|
| LVGL draw buffers (2 x 15 KB) | PSRAM | 30 KB |
| LVGL widget heap (`LV_MEM_SIZE`) | PSRAM | 48 KB |
| Lua heap (`mem_limit`) | PSRAM | 256 KB |
| Audio clip cache | PSRAM | 128 KB |
| Core node struct + timers | DRAM | ~2 KB |
| FreeRTOS stacks (see ADR-P1-7) | DRAM | ~24 KB |
| HAL driver buffers (SPI DMA, I2S) | DRAM (DMA-capable) | ~16 KB |
| Wi-Fi/BLE stack | DRAM | ~60 KB |
| ESP-IDF runtime | DRAM | ~50 KB |
| Headroom | DRAM | ~100 KB |

Total DRAM: ~252 KB of ~320 KB. Total PSRAM: ~462 KB (well within 2 MB).

#### Reduced tier (no PSRAM)

| Consumer | Location | Budget |
|----------|----------|--------|
| LVGL draw buffers (2 x 1 KB for 128x64 mono OLED) | DRAM | 2 KB |
| LVGL widget heap | DRAM | 16 KB |
| Lua heap (`mem_limit` = 64 KB) | DRAM | 64 KB |
| Audio: streamed from SD, no cache | DRAM | 4 KB (stream buffer) |
| Core node struct + timers | DRAM | ~2 KB |
| FreeRTOS stacks | DRAM | ~20 KB |
| HAL driver buffers | DRAM | ~8 KB |
| Wi-Fi/BLE stack | DRAM | ~60 KB |
| ESP-IDF runtime | DRAM | ~50 KB |
| Headroom | DRAM | ~94 KB |

Total DRAM: ~226 KB of ~320 KB.

The Lua allocator (`atalaia_alloc_fn`) on the Full tier points at a
PSRAM-backed allocator (`heap_caps_malloc` with `MALLOC_CAP_SPIRAM`).
On the Reduced tier it points at a standard DRAM allocator.

The core's `atalaia_node_create` receives `mem_limit` set by the shell
based on the detected tier. The core enforces the cap; the shell does
not need to track it.

A `mem_monitor` task (low priority, 10 s interval) logs
`heap_caps_get_info` for DRAM and PSRAM to the serial console. In
debug builds it also reports LVGL memory and Lua memory via
`atalaia_node_mem_used`. This is the primary tool for catching memory
issues before hardware arrives.

**Consequences:**
- The Full tier has generous headroom. Adding modifiers (phase 3) may
  raise the Lua heap to 384 KB without pressure.
- The Reduced tier is tight but feasible. The 94 KB headroom absorbs
  stack high-water-mark surprises. If a specific mode cannot fit in
  64 KB of Lua memory, the manifest's `min_tier: full` prevents it
  from loading on a Reduced-tier device.
- DMA buffers (SPI, I2S) must be in internal DRAM, not PSRAM, because
  the DMA controller on ESP32-S3 cannot access PSRAM directly for all
  peripherals. The HAL implementations allocate these with
  `MALLOC_CAP_DMA`.
- The Wi-Fi stack's ~60 KB is a fixed cost even in phase 1 (setup
  portal). In phase 2, running SoftAP + station simultaneously may
  increase this to ~80 KB.

---

### ADR-P1-7: FreeRTOS task architecture

**Status:** Accepted

**Context:** The ESP32-S3 is a dual-core Xtensa LX7 at 240 MHz. FreeRTOS
runs on both cores. ESP-IDF pins the Wi-Fi and protocol stacks to
core 0 by default. The firmware has several concurrent concerns: the
game loop (hardware polling, node advance, timer management), the LVGL
rendering pipeline, audio playback, and HTTP serving during setup.

**Decision:** Four tasks, with fixed core affinity:

| Task | Core | Priority | Stack | Purpose |
|------|------|----------|-------|---------|
| `game_task` | 1 | 5 (above normal) | 6 KB | Main game loop: poll buttons/keypad/NFC (10 ms tick), advance game time, dispatch commands, manage game timer, persist state |
| `lvgl_task` | 1 | 4 (normal) | 6 KB | Calls `lv_timer_handler()` every 5 ms; handles display flush via DMA (non-blocking); manages screen template updates |
| `audio_task` | 0 | 3 (below normal) | 4 KB | Reads WAV data from LittleFS or SD, feeds I2S DMA buffer; tone generation; wakes on command from game_task |
| `wifi_task` | 0 | 2 (low) | 4 KB | Runs only during setup: HTTP server and DNS captive-portal; sleeps in normal mode |

ESP-IDF's internal tasks (Wi-Fi, lwIP, timer) run on core 0 at their
default priorities.

**Communication between tasks:**

- `game_task` -> `lvgl_task`: a FreeRTOS queue of `screen_update_t`
  messages (template name + data). The LVGL task dequeues and renders.
  LVGL is single-threaded; all LVGL API calls happen on `lvgl_task`.
- `game_task` -> `audio_task`: a FreeRTOS queue of `audio_cmd_t`
  messages (play clip, tone, stop).
- `wifi_task` -> `game_task`: an event group bit signals "config saved,
  reboot requested".

The game loop tick rate is 100 Hz (10 ms period). At each tick:

1. Poll buttons (GPIO read, debounce with 30 ms window, hold detection
   at 250 ms intervals). Feed `team_input.press`, `.hold`, `.release`
   to the node.
2. Poll keypad (matrix scan). Feed `keypad.key` or `keypad.code` when
   a complete code is entered (terminated by `#`).
3. Poll NFC (every 100 ms, i.e. every 10th tick). Feed `nfc.tag`.
4. Read battery (every 30 s). Emit `battery.low` if below threshold.
5. Advance game time: `atalaia_node_advance(node, elapsed_ms)`.
6. Check game timer: if expired, send `game.end`.
7. Persist state: if 1 second has passed since last persist, write to
   LittleFS.
8. Process any command callbacks from the core: parse target/method,
   send screen updates to LVGL queue, audio commands to audio queue,
   LED updates directly (LED strip update is fast enough for the game
   task).

**Rationale for pinning game_task to core 1:**

- Core 0 is shared with Wi-Fi, lwIP and Bluetooth. Pinning the
  latency-sensitive game loop to core 1 avoids jitter from Wi-Fi
  interrupts and stack processing.
- LVGL runs on the same core as the game loop to avoid synchronisation
  overhead (the queue is the only sync point).
- Audio and Wi-Fi tolerate jitter and run on core 0.

**Consequences:**
- Button debounce at 100 Hz poll rate gives 10 ms resolution, which is
  well within the 250 ms hold detection window.
- The 10 ms game tick means `atalaia_node_advance` is called at most
  10 ms late, which is within the spec's timing tolerance.
- LVGL's `lv_timer_handler` at 5 ms means smooth animations (the v9
  default is 5 ms).
- The audio task can stream WAV from LittleFS without blocking the
  game loop.
- Adding LoRa in phase 2 will require a fifth task (`radio_task`) on
  core 0, receiving and transmitting packets.

---

### ADR-P1-8: Build system integration

**Status:** Accepted

**Context:** The core (`core/`) builds standalone with CMake for desktop
testing and the simulator. ESP-IDF uses its own CMake-based build
system where each component has a `CMakeLists.txt` that calls
`idf_component_register`. The firmware project at `firmware/esp32/`
must use the core as an IDF component while keeping the standalone
build working.

**Decision:** The core builds as an ESP-IDF component via a thin
wrapper CMakeLists.txt. The standalone build is unchanged.

Directory structure:

```
firmware/esp32/
    CMakeLists.txt              # IDF project root
    sdkconfig.defaults          # Default Kconfig values
    partitions.csv              # Custom partition table (ADR-P1-4)
    main/
        CMakeLists.txt          # Main component: shell, HAL, etc.
        idf_component.yml       # Dependencies: lvgl, esp_lvgl_port, littlefs
        shell.c                 # Entry point (app_main)
        hal/                    # HAL headers and implementations
        ...
    components/
        atalaia_core/
            CMakeLists.txt      # Wrapper that calls idf_component_register
                                # with the sources from ../../core/
```

The wrapper `components/atalaia_core/CMakeLists.txt` does:

```cmake
set(CORE_DIR ${CMAKE_CURRENT_LIST_DIR}/../../../core)
idf_component_register(
    SRCS
        ${CORE_DIR}/src/node.c
        ${CORE_DIR}/src/sandbox.c
        ${CORE_DIR}/src/script_api.c
        ${CORE_DIR}/src/codec.c
        ${CORE_DIR}/src/protocol.c
        ${CORE_DIR}/src/event.c
        ${CORE_DIR}/src/score.c
        ${CORE_DIR}/src/json.c
        ${CORE_DIR}/src/rand.c
        ${CORE_DIR}/src/lua_lstate.c
        # Vendored Lua sources (same list as core/CMakeLists.txt)
        ...
    INCLUDE_DIRS
        ${CORE_DIR}/include
        ${CORE_DIR}/third_party/lua
    PRIV_INCLUDE_DIRS
        ${CORE_DIR}/src
)
# Lua on ESP32: 32-bit integers and floats to save memory
target_compile_definitions(${COMPONENT_LIB} PRIVATE LUA_32BITS)
```

The project-level `CMakeLists.txt` is the standard IDF boilerplate:

```cmake
cmake_minimum_required(VERSION 3.16)
set(EXTRA_COMPONENT_DIRS components)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(atalaia_esp32)
```

The standalone `core/CMakeLists.txt` is **not modified**. It remains
the authority for desktop builds. The IDF wrapper is a parallel entry
point that references the same source files.

**ESP-IDF Docker image for CI:**

A `tools/dev/Dockerfile.esp32` extends `espressif/idf:v5.3.2`:

```dockerfile
FROM espressif/idf:v5.3.2
# No additions needed; the image includes the full Xtensa + RISC-V
# toolchain, CMake, Ninja and Python. idf.py handles component
# downloads at build time.
```

CI adds a job that runs:

```sh
docker run --rm -v $(pwd):/project -w /project/firmware/esp32 \
    espressif/idf:v5.3.2 \
    idf.py build
```

This verifies that the firmware cross-compiles. It does not flash.

**Consequences:**
- The core's standalone CMakeLists.txt and CI jobs are unchanged.
  Desktop builds and mode tests are unaffected.
- The IDF wrapper duplicates the source file list from
  `core/CMakeLists.txt`. If a new core source file is added, both
  lists must be updated. This is acceptable because core source files
  change rarely (the core is done for phase 1). A comment in the
  wrapper cross-references the standalone CMakeLists.txt.
- `LUA_32BITS` on ESP32 makes `lua_Integer` a 32-bit int and
  `lua_Number` a float. This saves memory and matches the core's
  `uint32_t` game time. Mode scripts must not assume 64-bit integers
  (none of the existing modes do).
- The firmware binary size should be under 1 MB (well within the
  1.5 MB OTA partition).

---

### ADR-P1-9: Testing strategy without hardware

**Status:** Accepted

**Context:** Hardware has not arrived. This machine has no C compiler.
All builds run in Docker. The phase 1 gate ("one box runs a 2-hour
club game with no restarts") cannot be closed until hardware arrives,
but all software must be buildable and testable before that.

**Decision:** Three testing tiers, each catching a different class of
defect:

#### Tier 1: Desktop (existing CI, unchanged)

- Core unit tests (`core/tests/`): node lifecycle, sandbox limits,
  timer behaviour, event codec with shared vectors.
- Mode tests (`modes/*/tests/`): YAML event sequences via the
  simulator.
- Simulator tests (`simulator/tests/`): web view, live game.
- Protocol checks (`protogen.py --check`, JSON Schema examples).
- Formatting, REUSE lint, DCO.

These run in the existing `atalaia-dev` Docker image and are not
affected by phase 1 changes.

#### Tier 2: Cross-compilation (new CI job)

A new CI job cross-compiles the entire firmware for ESP32-S3 using the
`espressif/idf:v5.3.2` Docker image:

```sh
cd firmware/esp32 && idf.py set-target esp32s3 && idf.py build
```

This catches:
- Missing or mismatched includes between core and IDF.
- Linker errors (undefined symbols, missing IDF components).
- Compiler warnings treated as errors (`-Werror`).
- Kconfig and partition table syntax errors.
- Component dependency resolution failures.

The job does **not** flash or run the binary. It produces a `.bin` file
that can be flashed manually when hardware arrives.

#### Tier 3: HAL stub integration tests (new, runs on Linux)

A `firmware/esp32/test/` directory contains integration tests that link
the shell code against HAL stubs. These tests run on Linux in the
`atalaia-dev` Docker image (not the IDF image):

- **Shell lifecycle test**: create a node, load a mode, advance time,
  verify that command callbacks produce the expected screen update
  queue entries and LED commands.
- **Game timer test**: start a game with a 10-second duration, advance
  time, verify `game.end` is sent at the right moment.
- **Preset store test**: save, list, load and delete presets on a
  temporary LittleFS image (the `littlefs-fuse` tool or a RAM-backed
  test double).
- **State persistence test**: persist state, simulate a "reboot"
  (destroy and recreate the node), verify the game resumes.
- **Command dispatch test**: verify that `command("ui", "screen",
  "[\"countdown\", {\"left\": 42}]")` results in the correct
  `screen_update_t` on the LVGL queue.

These tests do **not** test LVGL rendering, SPI transfers, or GPIO
state. They test the shell's logic: the glue between the core and the
HAL.

#### What is NOT tested until hardware arrives

- Actual display output (colours, layout, refresh rate).
- Button debounce timing on real switches.
- NFC read distance and reliability.
- Audio volume and quality.
- Battery gauge accuracy.
- Total power consumption and runtime.
- Wi-Fi captive-portal redirect on specific phone models.
- The 2-hour stability gate.

A documented bring-up checklist (`firmware/esp32/docs/BRING_UP.md`)
lists these items as manual tests for the first hardware session.

#### Optional: LVGL SDL simulator

LVGL provides an SDL-based simulator that renders to a desktop window.
If time permits, the screen templates can be tested visually by running
the LVGL simulator with the same `screen_renderer` code linked against
SDL instead of the SPI display driver. This is a nice-to-have, not a
gate.

**Consequences:**
- Every code change is verified by cross-compilation before it reaches
  hardware.
- The shell's business logic (timer, presets, command dispatch) is
  tested on every CI run without the ESP-IDF toolchain.
- The HAL stub tests give confidence that the shell integrates
  correctly with the core without needing real hardware.
- The bring-up checklist ensures nothing is forgotten when parts arrive.
- QEMU is not used: ESP32-S3 QEMU support is experimental and does not
  emulate SPI peripherals, so it adds complexity without covering the
  hardware gaps.

---

## Constraints for Planning

The planning phase must respect the following constraints derived from
the decisions above:

1. **No core changes.** The core is done for phase 1. The only
   core-related work is the IDF component wrapper
   (`components/atalaia_core/CMakeLists.txt`).

2. **HAL-first implementation order.** Each HAL module (header + ESP
   impl + stub) must land before the shell code that uses it. This
   unblocks integration testing without hardware.

3. **LVGL v9 only.** Do not use LVGL v8 APIs. Follow the v9 migration
   guide for any code adapted from v8 examples.

4. **LittleFS, not SPIFFS.** The preset store, state persistence and
   mode storage all use LittleFS. NVS is only for small config values
   and Wi-Fi credentials.

5. **Game timer in the shell.** Do not add timer logic to the core.
   The shell sends `game.end` via `atalaia_node_input`.

6. **Two Docker images.** The existing `atalaia-dev` builds and tests
   the core and simulator. The new `espressif/idf:v5.3.2` image
   cross-compiles the firmware. Do not merge them.

7. **Pin assignments via Kconfig.** No GPIO numbers hardcoded in C
   source files. Every pin is a Kconfig symbol read at compile time.

8. **Screen templates are C functions.** No declarative template format
   in phase 1. Each template is a C function that builds and patches
   LVGL widgets.

9. **Single task for LVGL.** All LVGL API calls happen on `lvgl_task`.
   The game task communicates screen updates via a FreeRTOS queue.

10. **State persistence to LittleFS.** Write the Lua state table,
    game time and scores to `/state/current.bin` every second. On boot,
    if the file exists, resume from it.

11. **Captive portal for setup.** No companion app, no BLE provisioning
    in phase 1. Wi-Fi setup is a SoftAP with an embedded HTML page.

12. **Cross-compile CI must pass before any merge.** The new
    `esp32-build` CI job is required, not optional.

13. **`LUA_32BITS` on ESP32.** All mode scripts must work with 32-bit
    integers and single-precision floats. The existing modes do; new
    ones must be tested accordingly.

14. **Bring-up checklist before hardware testing.** The planning phase
    must include a task for writing `BRING_UP.md` with manual test
    steps for the first prototype.

15. **SPDX headers on every file.** All new files under `firmware/`
    use `GPL-3.0-or-later` per `REUSE.toml`.

16. **Format with `.clang-format`.** All C files under `firmware/`
    follow the same formatting rules as `core/`. `tools/format.sh`
    must be extended to cover `firmware/`.
