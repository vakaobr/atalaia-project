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

## First board on the bench (2026-10-20)

The first board, a Heltec WiFi LoRa 32 V4.3 (HTIT-WB32LAF V4.3, ESP32-S3
rev 0.2, 2 MB PSRAM, 16 MB flash), with two buttons on GPIO 4 and 39 and no
TFT, keypad, NFC, LED ring or battery gauge, flashed from Windows over its
own USB port (BUILD.md section 11) with the bench variant. Seen on it:

- Boot: PSRAM found, full tier, no reboot loop; each missing part logs a
  warning and the box goes on (BRING_UP.md step 1).
- Radio: SX1262 found, the KCT8103L front end powered (the V4.3 pin fixes
  of 2026-10-18 hold). Nothing transmitted: the radio step (10) needs a
  second board and the power check.
- The on-board OLED (new, decisions HB-1 to HB-3): splash, the picker and
  the game, upright.
- Picker over serial keys, a Bomb game: arming by a 5 s hold, defusing by a
  10 s hold, the hold bars filling, the game ending when its timer runs out
  and the picker coming back (the stand-alone game-end bug found and fixed
  here, HB-5); power-loss resume of the game time (the mode's own state is
  not kept yet, HB-7).
- The buttons' unsoldered Dupont pins lost contact during holds: solder
  them (BUILD.md troubleshooting).

Still open for the gate: a built box (TFT, keypad, NFC, ring, battery),
BRING_UP.md steps 2-14, and the 2-hour game.

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

- The firmware image fills 93% of its 2 MB OTA slot (the Field Box build
  with the radio; mostly the Wi-Fi stack, LVGL and its fonts). The slots were
  already grown from 1.5 MB to 2 MB (`partitions.csv`); the 16 MB flash
  still has about 10 MB unpartitioned (ADR-P1-4), so a further growth is a
  partition-table change, which a box takes by USB only (the OTA slots move).

Done since this list was written (2026-10-27):

- The persistent game-timer bar from ADR-P1-3: a stand-alone game with a
  time limit shows a 6 px bar along the bottom of the TFT on every screen
  (red in the last minute) and the time left in the OLED's header. A field
  game is ended by its controller, so it has no bar.
- The DNS server for the captive portal (decision WS-3): a DNS responder
  and the HTTP redirects were built after this list was written.
- The unused `espressif/esp_lvgl_port` dependency is removed.

## Blocked on hardware

- The Phase 1 gate: "one box runs a 2-hour club game with no restarts."
- Everything Wokwi does not simulate: the PCF8574 keypad expander (Wokwi
  uses a GPIO keypad), PN532 read distance, MAX17048, I2S audio, the
  SX1262 (phase 2), the Heltec V4.3's Vext rail (the firmware does not
  switch it yet; polarity to check), the real panel's orientation and
  colours, power, the captive portal on real phones. See BRING_UP.md.
