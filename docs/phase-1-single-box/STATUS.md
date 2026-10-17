<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 1 -- Single Box: Status

**Date:** 2026-10-17
**Board:** Heltec WiFi LoRa 32 V4.3

The phase 1 software is done, screens included. The firmware runs a Bomb
game end to end in the Wokwi emulator. The phase gate (one box runs a
2-hour club game with no restarts) needs the hardware and stays open.

## Verified (exit 0 from a clean copy of the committed files)

- **ESP-IDF cross-compile**, Field Box (`idf.py set-target esp32s3 &&
  idf.py build` in `espressif/idf:v5.3.2`): no warnings. Image 1,366,128
  bytes (0x14d870) in the 1.5 MB OTA slot, 13% free. DIRAM 205,456 bytes
  (60.1%).
- **ESP-IDF cross-compile**, Wokwi variant (`sdkconfig.wokwi`): no
  warnings. Image 907,440 bytes (0xdd8b0), 42% free (no Wi-Fi stack: the
  variant skips the setup portal, so the linker drops it).
- **Firmware host tests** (CI's `firmware-test` commands, `atalaia-dev`):
  `firmware` (14 suites, about 70 test functions) and `screens` (20
  reference renders, pixel-exact) pass; no warnings. Also clean under
  AddressSanitizer and UBSan.
- **Existing checks**: `sh tools/check.sh`, `python3 tools/build_site.py
  --check`, `sh tools/format.sh --check`, `reuse lint`.
- **Wokwi emulator** (wokwi-cli 0.28.1, `wokwi/bomb.scenario.yaml`): boot,
  admin PIN, pick Bomb, start, red holds 5 s to arm, countdown, blue holds
  10 s to defuse, defused screen. Scenario completed; the emulated display
  matched the host reference PNGs to within RGB565 rounding (0 pixels off
  by more than 4%).

## Done (software, does not need the board)

- ESP-IDF project skeleton (16 MB flash, custom partitions, Kconfig).
- IDF component wrapper for the C core (64-bit Lua, no LUA_32BITS).
- HAL abstraction: 7 subsystems with ESP drivers and Linux stubs. Every
  part is brought up at boot; a missing PN532, MAX17048, keypad expander,
  LED ring, amplifier or display is logged and skipped, and the box boots.
- One shared I2C bus (port 0, GPIO 17/18) for the PCF8574 keypad, PN532
  and MAX17048 (the battery gauge used to claim a second port on the
  same pins).
- Game loop: game_task (buttons, debounced keypad, picker, node runner),
  lvgl_task (display, screens), audio_task, wifi_task.
- **Screens**: 12 LVGL 9.2 templates for the 320x240 TFT, built on the
  device and on the host from the same code and `lvgl_conf/lv_conf.h`:
  `standby`, `countdown`, `defused`, `exploded`, `final_score`, `paused`,
  `status`, `pin_entry`, `preset_select`, `timer_adjust`, `start_confirm`,
  `wifi_setup`. Templates are built once and patched with new data.
- **Preset picker on screen**: PIN, game list (the former TODO),
  timer and confirmation each draw their screen.
- **Display port**: LVGL draws into two DMA buffers of 1/10 screen, flushed
  through the HAL driver; the DMA-done interrupt releases LVGL. The SPI
  flush keeps its transaction alive until it completes, and the panel is
  set to landscape (MADCTL).
- **Reference images**: `firmware/esp32/test/screens/*.png`, compared
  pixel by pixel; widgets outside the screen and overlapping labels fail.
- **Built-in presets**: Bomb and Domination are compiled in from `modes/`
  and stored on an empty box.
- LittleFS is mounted (`/littlefs`, formatted on first boot); the state
  directory is created.
- **Wokwi emulator**: `wokwi.toml`, `diagram.json`, `sdkconfig.wokwi`,
  `wokwi/bomb.scenario.yaml`, `docs/WOKWI.md`.
- `tools/docker_fw.py` builds, emulates and tests from `cmd`.
- Bugs found and fixed: the memory monitor task overflowed its 2 KB stack
  on its first log line (a crash loop on every box, found in Wokwi); the
  Wi-Fi setup never called `esp_wifi_init`; the keypad reported a held key
  at every 10 ms scan.
- Preset store, state persistence, resume after reboot, config store,
  Wi-Fi captive portal (form and NVS), game timer, command dispatch,
  memory monitor, CI jobs, BRING_UP.md, BOM.

## Not done (software)

- The persistent game-timer bar from ADR-P1-3: during Domination the
  screen shows the `status` screen (game, timer length) until the game
  ends.
- A DNS server for the captive portal: phones may not open the setup page
  by themselves; `http://192.168.4.1` works.
- `espressif/esp_lvgl_port` is still a dependency but unused.
- The firmware image fills 87% of its 1.5 MB OTA slot (mostly the Wi-Fi
  stack, LVGL and its fonts). Before phase 2 adds LoRa and crypto, grow the
  OTA slots (the 16 MB flash has about 10 MB unpartitioned; see ADR-P1-4)
  or trim fonts.

## Blocked on hardware

- The Phase 1 gate: "one box runs a 2-hour club game with no restarts."
- Everything Wokwi does not simulate: the PCF8574 keypad expander (Wokwi
  uses a GPIO keypad), PN532 read distance, MAX17048, I2S audio, the
  SX1262 (phase 2), the Heltec V4.3's Vext rail (the firmware does not
  switch it yet; polarity to check), the real panel's orientation and
  colours, power, the captive portal on real phones. See BRING_UP.md.
