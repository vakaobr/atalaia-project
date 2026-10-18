<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 1 -- Single Box: Research

## Summary

Phase 1 builds the ESP-IDF shell that runs the shared C core on an
ESP32-S3 Field Box. The core (event bus, Lua sandbox, script API, event
codec) is done and working in the simulator. What phase 1 adds is the
platform shell: hardware drivers for buttons, LEDs, buzzer, display
(LVGL), NFC, audio; a Wi-Fi captive-portal for first-time setup;
on-device preset selection via keypad; the game timer with score-freeze
behaviour; and a state-persistence layer that resumes after a reboot.
The gate is "one box runs a 2-hour club game with no restarts".

Hardware has not arrived. This machine has no C compiler. All builds and
tests run in Docker, and all ESP-IDF cross-compilation runs in the
official Espressif Docker image.

**Risk:** Medium -- the core is solid and the API boundary between core
and shell is clean, but ESP-IDF integration, LVGL rendering on a real
display, memory budgeting with/without PSRAM, and testing without
hardware are non-trivial. Each risk has a known mitigation documented
below.

---

## 1. Current codebase inventory

### core/

The shared C11 core. Fully working, tested in CI.

| File | Purpose |
|------|---------|
| `include/atalaia/node.h` | Public API: create, configure, load, input, advance, query |
| `include/atalaia/event.h` | Event struct (node, seq, t_ms, type, team, squad, prio) |
| `include/atalaia/score.h` | Per-node, per-team grow-only counters with conflict-free merge |
| `include/atalaia/codec.h` | CBOR event codec (encode/decode, no allocation) |
| `include/atalaia/protocol.h` | Generated: message types, event ids/keys, data field defs |
| `include/atalaia/version.h` | Core version (0.1.0) and protocol version (1) |
| `src/node.c` | Node lifecycle, event bus, timer dispatch |
| `src/sandbox.c` | Lua 5.4 state: memory-capped allocator, instruction watchdog |
| `src/script_api.c` | All functions modes call: on, emit, every, after, cancel, game.*, score.*, state.node, cap, ui, audio, rand, log |
| `src/codec.c` | Hand-written CBOR codec for EVENT payloads |
| `src/protocol.c` | Generated lookup tables |
| `src/event.c` | Event init, compare, identity |
| `src/score.c` | Score counters |
| `src/json.c` | Minimal JSON encoder for Lua tables |
| `src/rand.c` | Seeded PRNG |
| `src/lua_lstate.c` | Fixed hash seed (deterministic `pairs()` order) |
| `src/node_internal.h` | Internal struct: timers, queue, state, error buffer |
| `third_party/lua/` | Vendored Lua 5.4.9 (MIT) |
| `CMakeLists.txt` | Static + optional shared lib, CTest |
| `tests/test_core.c` | Entry point |
| `tests/test_node.c` | Node lifecycle and script API tests |
| `tests/test_codec.c` | Event codec tests using shared vectors |
| `tests/protocol_vectors.h` | Generated test vectors |
| `tests/check.h` | Minimal test macros |

### firmware/

Placeholder READMEs only.

| Path | Contents |
|------|----------|
| `firmware/esp32/README.md` | Planned ESP-IDF component list; device tiers; radio region enforcement |
| `firmware/thin-node/README.md` | One-line stub -- planned for phase 2 |

### hardware/

Reference build documentation stubs. No schematics, BOMs, or STLs yet.

| Path | Contents |
|------|----------|
| `hardware/README.md` | Overview of 4 builds, costs, safety notes |
| `hardware/field-box/README.md` | Parts table for the Field Box |
| `hardware/satellite/README.md` | Stub |
| `hardware/io-pod/README.md` | Stub |
| `hardware/target-addon/README.md` | Stub |

### modes/

Two modes, both working in the simulator.

| Path | Contents |
|------|----------|
| `modes/domination/node.lua` | Zone ownership by team_input.hold; tick-based scoring; game.end shows final_score screen |
| `modes/domination/mode.yaml` | Manifest: `org.atalaia.domination`, min_tier reduced, role `zone` |
| `modes/domination/tests/` | 5 YAML test files |
| `modes/bomb/node.lua` | Arm/defuse/explode; auto-arm; reset_after_defuse; screens for each phase |
| `modes/bomb/mode.yaml` | Manifest: `org.atalaia.bomb`, min_tier reduced, role `bomb` |
| `modes/bomb/tests/` | 7 YAML test files (including screens.yaml) |
| `modes/README.md` | Mode package format, inputs from hardware, test format with all step types |

### simulator/

Python package `atalaia_sim`: ctypes FFI to the core shared lib, mode
loader, simulation engine, test runner, web view.

| Path | Purpose |
|------|---------|
| `atalaia_sim/core.py` | ctypes bindings to `libatalaia_core.so` |
| `atalaia_sim/sim.py` | Simulation: virtual nodes on a virtual clock |
| `atalaia_sim/mode.py` | Mode loader from YAML manifest |
| `atalaia_sim/testing.py` | Test runner: steps, expects, schema checks |
| `atalaia_sim/codec.py` | Python event codec (mirrors `core/src/codec.c`) |
| `atalaia_sim/cbor.py` | Minimal CBOR encoder/decoder |
| `atalaia_sim/protocol.py` | Generated protocol tables |
| `atalaia_sim/live.py` | Interactive simulation with real-time clock |
| `atalaia_sim/web.py` | HTTP server for the web view |
| `atalaia_sim/web/` | HTML, CSS, JS for the browser UI |
| `atalaia_sim/__main__.py` | CLI entry: `test`, `serve` |
| `tests/test_codec.py` | Codec tests against shared vectors |
| `tests/test_live.py` | Web view and live-game tests |

### protocol/

Schema source of truth and test vectors.

| Path | Purpose |
|------|---------|
| `protocol/schema/events.yaml` | 24 standard events with ids, priorities, CBOR keys, data fields |
| `protocol/schema/messages.yaml` | 8 message types (HELLO through CLAIM) |
| `protocol/vectors/events.yaml` | 14 valid + 39 invalid shared codec test vectors |
| `protocol/json/event.schema.json` | Generated JSON Schema |
| `protocol/json/examples/` | Valid + invalid JSON examples for CI |
| `protocol/README.md` | Codec format, encoding rules, LoRa budget |

### tools/

| Path | Purpose |
|------|---------|
| `tools/check.sh` | Everything CI runs (minus JSON Schema and REUSE lint) |
| `tools/protogen.py` | Schema codegen: C tables, Python tables, JSON Schema |
| `tools/format.sh` | clang-format + StyLua |
| `tools/docker_sim.py` | Run the simulator in the dev container from Windows |
| `tools/dev/Dockerfile` | Ubuntu 24.04, build-essential, cmake, ninja, python3, clang-format-18, StyLua 2.6.0 |

### Other top-level files

`.github/workflows/ci.yml`, `CONTRIBUTING.md`, `.clang-format`,
`stylua.toml`, `.editorconfig`, `REUSE.toml`, `LICENSING.md`,
`CODE_OF_CONDUCT.md`, `.gitattributes`, `.gitignore`, `HANDOVER.md`
(gitignored), `site/` (project page for GitHub Pages).

---

## 2. C core API

The host (ESP-IDF shell, simulator, etc.) interacts with the core
through a small surface in `node.h`:

```
atalaia_node_create(cfg)        -- allocate a node
atalaia_node_set_teams(node, names, count)
atalaia_node_set_params(node, json)
atalaia_node_load(node, source, len, chunk_name)  -- compile+run Lua
atalaia_node_input(node, type, data_json)          -- feed an event
atalaia_node_advance(node, now_ms)                 -- move game clock
atalaia_node_status / paused / time / mem_used / score / last_error
atalaia_node_destroy(node)
```

**Callbacks** (host implements):
- `event(user, ev, data_json)` -- emitted events
- `command(user, target, method, args_json)` -- hardware commands from scripts
- `log(user, message)` -- script log output

**Key design points:**
- The core never blocks, never reads a real clock, never allocates
  outside the configured allocator.
- The host owns the clock: it calls `atalaia_node_advance(node, now_ms)`
  with game time in milliseconds. The core fires due timers internally.
- All Lua calls run in protected mode. A runaway script halts the node
  (status = HALTED, emits `script.halted`) and shows a paused screen.
- The allocator function has the same signature as `lua_Alloc`, so on
  ESP32 it can point at PSRAM.

---

## 3. Design spec requirements for the Field Box (phase 1)

### 3.1 Hardware (spec sections 5-7)

The Field Box is the main prop. Reference parts:

| Component | Spec | Interface |
|-----------|------|-----------|
| ESP32-S3 LoRa board | Heltec LoRa 32 V3 class, with PSRAM for Full tier | SPI/I2C |
| Team buttons | 2-4 x 60 mm arcade buttons with built-in LEDs | GPIO |
| Keypad | 3x4 matrix | GPIO matrix scan |
| Display | 2.8" TFT (or monochrome OLED for Reduced tier) | SPI (ILI9341 / ST7789) |
| LEDs | WS2812 ring (24 LEDs typical) | single-wire (RMT peripheral) |
| NFC reader | PN532 | I2C or SPI |
| Audio | MAX98357A I2S amp + speaker + microSD for clips | I2S + SPI (SD) |
| Battery | 1S: two protected 18650 in parallel (the board and the MAX17048 are single-cell parts; corrected 2026-10-18, see hardware/field-box/BUILD.md) + MAX17048 fuel gauge | I2C |
| Enclosure | IP65 box, cable glands, recessed power switch | -- |

### 3.2 Device tiers (spec section 6)

PSRAM detected at boot:
- **Full** (with PSRAM): 256 KB script memory, colour TFT, cached audio.
- **Reduced** (no PSRAM): ~64 KB script memory, precompiled bytecode, monochrome OLED, audio streamed from microSD.
- **Proxy** (cannot run scripts): thin node, logic on controller.

The firmware must detect PSRAM and set `mem_limit` accordingly when
calling `atalaia_node_create`.

### 3.3 Capability model (spec section 7)

Each node announces a descriptor (JSON) listing its capabilities. The
standard types relevant to phase 1 are:

- `button` -- emits press/release/hold, accepts led(on/off/blink)
- `keypad` -- emits key/code, accepts clear
- `display` -- accepts screen(template, data), brightness
- `led` -- accepts color, fill(team), progress(0-1), pattern
- `audio` -- accepts tone(freq, ms), play(clip)
- `nfc` -- emits tag(uid, data)
- `battery` -- emits level(%), low

Scripts use `cap("ring"):fill(team)` and `ui.screen(template, data)`.
The shell maps these commands to driver calls.

### 3.4 Semantic capabilities

- `team_input`: "a team is claiming this node". The shell maps arcade
  buttons to `team_input.press / .hold / .release` events with the
  team name. The `.hold` event fires every 250 ms with `ms` held so
  far.
- `team_display`: show owner colour and score, mapped to LEDs + screen.
- `code_input`: from keypad or NFC.

### 3.5 Wi-Fi setup flow (spec section 13)

First-time setup: the ESP32 opens its own Wi-Fi access point with a
captive-portal configuration page. The page sets:
- Node name
- Radio region (mandatory before any LoRa transmission)
- Team colours
- Admin PIN
- Brightness, volume

After setup, the node stores config in NVS and boots into normal mode.

### 3.6 On-device presets (spec section 13)

A node with no controller runs any cached preset that only needs
`node.lua`. The GM enters the admin PIN on the keypad (or long-press),
picks a preset from a list (at least 10 cached), adjusts the timer, and
starts. This is the "quick single-box game" deployment (spec section 4):
one Field Box, no controller, preset picked on the keypad.

### 3.7 Game timer with score freeze (spec section 15)

A core feature every mode gets: when `game.end` arrives, the core
freezes scores (`atalaia_node_status` becomes `ENDED`; `score.add` is
a no-op). Modes already handle this -- see `domination/node.lua`
line 26: `on("game.end", function() ui.screen("final_score", ...) end)`.

The timer itself runs in the shell: a configurable game duration
(default 0 = unlimited), countdown on the display, freeze at zero.

### 3.8 Freeze logic

When the game timer expires, the shell sends `game.end` to the node.
The core transitions to `ATALAIA_NODE_ENDED`. After that:
- `atalaia_node_input` rejects all events except `game.*`.
- `score.add` does nothing (scores are frozen, line 239 of script_api.c).
- The node's last screen stays on display.
- Timers stop firing.

---

## 4. Screen templates

Scripts call `ui.screen(template, data)` which arrives at the host
as a command callback: `command(user, "ui", "screen", "[\"template_name\", {data}]")`.

Templates used by existing modes:
- `standby` -- bomb standby screen (data: `{arm: team_name}`)
- `countdown` -- bomb countdown (data: `{left: seconds}`)
- `defused` -- bomb defused (data: `{team: name}`)
- `exploded` -- bomb exploded (data: `{team: name}`)
- `final_score` -- domination end (data: `{owner: team_name}`)

The spec (section 12) says templates are "a small declarative layout
format (big number, label, progress bar, team colour, QR code, icon)
shipped in each mode's assets/". ESP32 renders them with LVGL.

**Phase 1 must define and implement at least:**
- A template renderer backed by LVGL
- The 5 templates above (standby, countdown, defused, exploded, final_score)
- A `paused` template (shown when the sandbox halts)
- A `setup` / `preset_select` template for on-device preset selection
- A `status` template showing battery, signal, firmware version
- A `wifi_setup` template for the captive-portal

---

## 5. Lua sandbox API exposed to modes

Implemented in `core/src/script_api.c` and registered as globals:

| Category | Functions |
|----------|-----------|
| Events | `on(type, fn)`, `emit(type, data, opts)` |
| Time | `every(s, fn)` -> id, `after(s, fn)` -> id, `cancel(id)` |
| Game | `game.time()` (seconds), `game.start()`, `game.finish(reason)`, `game.win(team)` |
| Score | `score.add(team, n, reason, squad)`, `score.get(team)` |
| State | `state.node{defaults}` (returns the persistent table) |
| Hardware | `cap(id)` -> proxy (any method becomes a command), `ui.screen(t, d)`, `audio.play(clip)` |
| Utility | `params` (table), `rand(a, b)` (seeded), `log(...)`, `print(...)` -> log |
| Not yet | `state.field{}` (phase 2), `field.*` (phase 2) |

Standard libs available: base (minus dofile/loadfile/load/collectgarbage),
coroutine, table, string, math (minus random/randomseed), utf8.

---

## 6. Protocol messages and events

### Standard events (24 defined in events.yaml)

Game lifecycle: game.start (1), game.pause (2), game.resume (3), game.end (4)
Zone: zone.captured (5), zone.neutralized (6)
Bomb: bomb.armed (7), bomb.defused (8), bomb.exploded (9), bomb.reset (10)
Score: score.delta (11)
Interaction: code.used (12), tag.scanned (13)
Player: player.respawn (14), player.checkin (15)
Target: target.hit (16)
Chrono: chrono.violation (17)
GM: gm.message (18)
System: node.online (19), node.offline (20), node.rebooted (21), battery.low (22)
Script: script.error (23), script.halted (24)

### Message types (8 in messages.yaml)

HELLO (1), EVENT (2), ACK (3), STATE (4), CMD (5), TIME (6), CONFIG (7), CLAIM (8)

### Codec

- C: `core/src/codec.c` (encode/decode, no alloc, CBOR map with int keys)
- Python: `simulator/atalaia_sim/codec.py`
- Shared test vectors: `protocol/vectors/events.yaml` (14 valid + 39 invalid)
- Payload limit: 200 bytes (LoRa)

---

## 7. CI pipeline

File: `.github/workflows/ci.yml`

| Job | What it does |
|-----|-------------|
| `core` | CMake debug build + CTest + simulator unittest + mode tests |
| `protocol` | `protogen.py --check` + JSON Schema meta-check + valid/invalid examples |
| `sanitizers` | Core under ASan + UBSan |
| `format` | clang-format-18 + StyLua 2.6.0 via `tools/format.sh --check` |
| `licensing` | `reuse lint` |
| `dco` | Signed-off-by on every PR commit |

All jobs run on `ubuntu-latest` (except format on `ubuntu-24.04`).

---

## 8. Docker development environment

`tools/dev/Dockerfile`: Ubuntu 24.04 with:
- build-essential, cmake, ninja-build, python3, python3-yaml
- clang-format-18 (symlinked to /usr/local/bin/clang-format)
- StyLua 2.6.0 (pinned with SHA256)

Build + test:
```
docker build -t atalaia-dev tools/dev
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/src" atalaia-dev \
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**Phase 1 needs a second Dockerfile** based on `espressif/idf:v5.x` for
ESP-IDF cross-compilation. The existing `atalaia-dev` image does not
have the Xtensa/RISC-V toolchain.

---

## 9. Codebase patterns and conventions

### Naming
- C: `snake_case`, public symbols prefixed `atalaia_`, private symbols
  have no prefix.
- Lua: `snake_case`, 2-space indent, no globals except the sandbox API.
- YAML: `snake_case` keys.
- Files: lowercase with hyphens for docs, underscores for code.

### Headers
- Every source file has SPDX headers:
  `SPDX-FileCopyrightText: 2026 The Atalaia contributors`
  and the licence from `REUSE.toml` (GPL-3.0-or-later for code,
  CC-BY-SA-4.0 for docs, CERN-OHL-S-2.0 for hardware).

### Formatting
- C: `.clang-format` (100 columns, 4-space indent)
- Lua: `stylua.toml` (keeps `state.node { }` without parens)
- `.editorconfig` for everything else
- `tools/format.sh` runs both formatters; CI checks with `--check`.

### Build
- C11, no extensions, `-Wall -Wextra -Wpedantic -Werror`.
- All allocation through the configured allocator (host can point at PSRAM).
- Every Lua call from C in protected mode.
- Tests: `core/tests/check.h` minimal macros; modes tested as YAML
  event sequences via `simulator/atalaia_sim/testing.py`.

### Git
- Every commit signed off (DCO), ends with `Co-Authored-By:` line.
- Commit messages: `area: imperative summary`.
- LF line endings (`.gitattributes`).

### Clean-room
- No commercial vendor names, protocols, code, or UI layouts.

---

## 10. Files to create or modify in phase 1

### New files (ESP-IDF shell)

| Path | Purpose |
|------|---------|
| `firmware/esp32/CMakeLists.txt` | ESP-IDF project root |
| `firmware/esp32/main/CMakeLists.txt` | Main component |
| `firmware/esp32/main/shell.c` | Entry point: init drivers, create node, run loop |
| `firmware/esp32/main/hal_buttons.c/h` | GPIO button driver with debounce and hold detection |
| `firmware/esp32/main/hal_keypad.c/h` | 3x4 matrix keypad scanner |
| `firmware/esp32/main/hal_leds.c/h` | WS2812 via RMT peripheral |
| `firmware/esp32/main/hal_display.c/h` | SPI TFT init + LVGL integration |
| `firmware/esp32/main/hal_audio.c/h` | I2S output + microSD clip playback |
| `firmware/esp32/main/hal_nfc.c/h` | PN532 I2C/SPI driver |
| `firmware/esp32/main/hal_battery.c/h` | MAX17048 fuel gauge over I2C |
| `firmware/esp32/main/screen_renderer.c/h` | LVGL template renderer: maps ui.screen(template, data) to LVGL widgets |
| `firmware/esp32/main/preset_store.c/h` | NVS-backed preset storage (at least 10 presets) |
| `firmware/esp32/main/preset_ui.c/h` | Keypad-driven preset picker (admin PIN, list, adjust timer, start) |
| `firmware/esp32/main/wifi_setup.c/h` | Captive-portal AP for first-time config |
| `firmware/esp32/main/game_timer.c/h` | Configurable countdown; sends game.end on expiry |
| `firmware/esp32/main/state_persist.c/h` | NVS-backed state save every 1 s; resume on reboot |
| `firmware/esp32/main/Kconfig.projbuild` | ESP-IDF menuconfig entries |
| `firmware/esp32/sdkconfig.defaults` | Default IDF config (PSRAM, flash, partitions) |
| `firmware/esp32/partitions.csv` | Custom partition table (app A/B, NVS, storage) |
| `tools/dev/Dockerfile.esp32` | ESP-IDF build environment for CI and local use |

### New files (core changes)

| Path | Purpose |
|------|---------|
| `core/CMakeLists.txt` | Add an ESP-IDF component target (conditional on `IDF_TARGET`) |

### New CI

| Path | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | Add job: ESP-IDF cross-compile check (build, not flash) |

### Modified files

| Path | Change |
|------|--------|
| `firmware/esp32/README.md` | Replace placeholder with real documentation |
| `hardware/field-box/README.md` | Expand with wiring diagram, assembly notes |

---

## 11. Risks and mitigations

### R1: ESP-IDF integration complexity (Medium)

ESP-IDF has its own build system (CMake + Kconfig + component manager).
The core must build as an ESP-IDF component while still building
standalone for desktop. The CMakeLists.txt needs a conditional path.

**Mitigation:** Use `if(IDF_TARGET)` in CMakeLists.txt to register the
core as an IDF component. The vendored Lua builds with `-DLUA_32BITS`
on ESP32. Test the cross-compilation in CI using the official
`espressif/idf` Docker image.

### R2: Memory budget on Reduced tier (Medium)

Without PSRAM, the ESP32-S3 has ~320 KB of DRAM. Lua + the core +
LVGL frame buffer must fit. At 64 KB script memory + LVGL at
~40-80 KB (monochrome OLED) + core overhead, this is tight but
feasible.

**Mitigation:** Use monochrome OLED on Reduced tier (smaller frame
buffer). LVGL's `LV_MEM_SIZE` can be tuned. Profile memory early
using `heap_caps_get_info`. If still tight, fall back to Proxy tier
(no local scripts).

### R3: Lua 5.4 on ESP32 without PSRAM (Low-Medium)

Lua 5.4.9 compiles for Xtensa with `-DLUA_32BITS`. The vendored
copy already excludes io/os/loadlib. The 64 KB memory cap enforced
by the sandbox allocator is the real constraint.

**Mitigation:** Precompile Lua to bytecode for Reduced tier (saves
~30% memory vs source parsing). The `luac` output avoids the
parser's temporary allocations.

### R4: Display driver selection (Low)

The spec says "2.8 TFT" but does not name a controller. Common
choices: ILI9341 (320x240), ST7789 (240x240 or 320x240). LVGL has
mature drivers for both.

**Mitigation:** Write the display HAL against a generic SPI+command
interface. Use LVGL's existing ILI9341/ST7789 drivers. Abstract
behind `hal_display.h` so switching controllers is a config change.

### R5: No-hardware testing strategy (Medium)

The parts have not arrived. We cannot flash or test on real hardware.

**Mitigation:**
1. **Cross-compile check in CI**: the `espressif/idf` Docker image
   compiles the entire firmware. A successful build catches API
   mismatches, missing includes, and linker errors.
2. **LVGL simulator**: LVGL provides a Linux/SDL simulator. We can
   render screen templates in it and screenshot-test them.
3. **Core tests unchanged**: all mode tests and core tests keep
   running on desktop (the core is platform-independent).
4. **HAL stubs**: each `hal_*.c` can be compiled with a `STUB` flag
   that provides no-op implementations. The shell then runs on Linux
   in "headless" mode for integration testing.
5. **Bring-up when parts arrive**: a documented first-boot checklist
   and a minimal "blink + serial" test program.

### R6: State persistence across reboots (Low)

The spec says "node state is persisted every second; after a reboot
the node resumes the countdown and emits `node.rebooted`". NVS on
ESP32 has limited write endurance (~100k cycles per page). Writing
every second for a 2-hour game = 7,200 writes -- well within limits
for a single game, but needs wear-levelling for years of use.

**Mitigation:** Persist only the Lua state table (small), the game
time, and the score counters. Use NVS with the default wear-levelling.
Consider a small SPIFFS/LittleFS partition for the state blob if
NVS entry size is a concern.

### R7: Audio playback (Low)

I2S + microSD clip playback is well-documented in ESP-IDF examples.
WAV (PCM, 16-bit, 22050 Hz mono) is simple to stream.

**Mitigation:** Start with a minimal WAV player. Clip caching
(Full tier with PSRAM) is a nice-to-have, not a gate requirement.

### R8: LoRa not in phase 1 scope (non-risk)

Phase 1 is single-box only. LoRa integration arrives in phase 2.
The SX1262 radio hardware is on the board but the driver is not
needed yet. The firmware initialises the radio in standby/sleep
to avoid wasting power.

---

## 12. Dependencies and tooling needed

| Dependency | Version | Purpose |
|------------|---------|---------|
| ESP-IDF | v5.3+ (latest stable) | Xtensa toolchain, FreeRTOS, NVS, I2C/SPI/I2S/RMT drivers |
| LVGL | v9.x (via ESP component registry) | Display rendering, widget toolkit |
| Docker image `espressif/idf` | v5.3 | Cross-compilation in CI and locally |
| Existing `atalaia-dev` | as-is | Desktop builds and mode tests (unchanged) |

No new Python or npm dependencies. The ESP-IDF component manager
handles LVGL.

---

## 13. Patterns to follow

1. **HAL abstraction**: each hardware driver behind a clean header
   (`hal_buttons.h`). The shell calls HAL functions; HAL functions
   call ESP-IDF APIs. This isolates the core from IDF specifics.

2. **Command dispatch**: the `command` callback from the core delivers
   `(target, method, args_json)`. The shell parses target and method
   and dispatches: `"ui"/"screen"` -> screen renderer,
   `"audio"/"play"` -> audio player, `"ring"/"fill"` -> LED driver.

3. **Event injection**: hardware events from button/keypad/NFC drivers
   are fed into the node with `atalaia_node_input(node, type, json)`.

4. **Main loop**: FreeRTOS task that:
   - Polls hardware drivers (buttons at 10 ms, keypad at 50 ms)
   - Calls `atalaia_node_advance(node, now_ms)` with game time
   - Handles the game timer countdown
   - Persists state every second

5. **SPDX headers** on every new file, matching `REUSE.toml`
   (GPL-3.0-or-later for firmware/).

6. **Commit messages**: `firmware/esp32: add button driver with debounce`.

7. **Formatting**: C files under `firmware/` should follow
   `.clang-format` (same as core/).

---

## 14. Open questions for architecture/planning

1. **LVGL version**: v8 or v9? v9 has a different API but better
   ESP32 support. Recommend v9 via the ESP component registry.

2. **Display controller**: ILI9341 vs ST7789 for the 2.8" TFT?
   Both are well-supported. Defer to the actual board purchased.

3. **Pin assignments**: depend on the specific ESP32-S3 board
   (Heltec LoRa 32 V3 or similar). Document a reference pinout
   and make it configurable via Kconfig.

4. **Preset file format**: Lua source in NVS? Or mode.yaml +
   node.lua stored in a SPIFFS/LittleFS partition? The latter
   scales better.

5. **Game timer ownership**: should the shell own the timer (simpler,
   the core does not need changes) or should it be a core feature?
   Recommend shell-owned: the core already handles `game.end`
   correctly; the shell just needs to send it at the right time.
