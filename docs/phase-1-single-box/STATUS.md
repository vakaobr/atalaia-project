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
  **Done (decision PART-1, built; host tests and builds only, not flashed on a
  board):** the OTA slots are 4 MB (ota_0 0x20000, ota_1 0x420000, storage 4 MB at
  0x820000; the first four partitions did not move), the Field Box image is 1,952,160
  bytes with 53 % of its slot free. **USB flash required once** for a box on the old
  table; the new firmware refuses to run on it (screen *Flash over USB*, log
  `WRONG PARTITION TABLE`), an update over the air refuses an image that needs the
  new layout (`layout`), and `release_package.py` checks the built table. Still to do on a board: the
  USB flash of a box with an adoption (it keeps it), the first mount of the new storage, and an old-table box.

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

## Admin menu: moving an adopted box to another field by code (2026-10-28, decision PKB-4)

Built (host tests only; **not flashed, no bench, no radio transmission**): the picker's last entry **Change field** (after **Wi-Fi setup**), behind the admin PIN with a confirmation, arms one move (`adoption_allow_move`) and shows the pairing code of an unadopted box; the box keeps its field until another one has paired it (decision AD-16's "left for later", `protocol/adoption.md` section 7). The entry shows only on an adopted box with a radio and an admin PIN. New `start_confirm` variant `{"adopt":true}` on the TFT and the OLED in four languages (eight reference images). Host tests: `test_preset_ui.c`, `test_adoption.c`, `test_box_pair.c` (the vectors' run moving an adopted box, its cancellation by `*`, the five minutes and another adoption), `test_screens.c`, `test_oled_screens.c`; ASan and UBSan clean. Builds (ESP-IDF v5.3.2, 0 warnings): the Field Box image is 0x1db150 bytes (1,945,936) in the 0x200000-byte OTA slot (7 %, 151,216 bytes free), the modem 0x86ba0 (74 % free) and the pod 0xa4830 (68 % free). Still to do on a board: the key sequence on the real keypad and screen, and the whole move against a real field controller (BRING_UP step 10a.5).

## The bench of 2026-10-29: memory, the iBeacon, the logo and the status screens (in software; the memory measured on the bench)

- **Internal RAM (BBC-13 to BBC-18).** At a game's join the box ran out of internal RAM (Wi-Fi `ESP_ERR_NO_MEM`, then `BLE_INIT: Malloc failed` and a watchdog reset). LVGL's 48 KB heap and about 62 KB of the game's big static buffers moved to PSRAM, the Bluetooth controller is sized for one advertiser, Wi-Fi and the beacon are never up together (the Wi-Fi start waits up to 5 s for the beacon to come down), and a gate (40 KB free plus a 12 KB block, three retries) keeps a failed Bluetooth start from panicking. Measured on the bench: static internal RAM left for the heap 45,704 to 194,049 bytes; 241 KB free at boot, 102 KB at the lowest in a game with the beacon on. `tools/check_fw_ram.py` fails CI under 120 KiB. Still to check on a board: the Wi-Fi start at a join with this budget (the next over-the-air update test).
- **The Field Box as an iBeacon (BBC-1 to BBC-12, RFC 0001 Amendment 20, `protocol/box-beacon.md`).** From the join to the end of the game, a non-connectable iBeacon every 500 ms at 0 dBm (NimBLE as a broadcaster), on in `sdkconfig.defaults`; the UUID is the field's, derived from the join key. Built and host-tested; the bench run of `docs/runbooks/box-beacon-bench.md` (a phone hearing a real box) is **not done**.
- **No field logo on the box (LOGO-5 to LOGO-8; supersedes the logo item of PKG-1).** The box no longer fetches or keeps the field's logo: only the Atalaia tower, as the boot splash, a build asset (`firmware/esp32/assets/splash.pgm`, `CONFIG_ATALAIA_SPLASH_LOGO`); `tools/release_package.py` refuses a release whose splash is not the pinned tower; a box that kept `logo.bin` removes it at its first boot. Host tests.
- **The update and mode-fetch status screens go away (`status_hold.c`).** Found on the bench (a refused `@update` stayed on the screen); a refusal, a failure or a result is shown 8 s, then the screen of the box's state comes back. Host test `test_status_hold.c`.
- **Bench builds only:** `@hold <button> <ms>` on the serial console holds a team button (used for the projected-score runbook).

## The security review of 30 October: serial commands and the release image (SR-40 to SR-44; host tests only)

- **`@joinkey` and `@update` need the admin PIN in a release build (FLD-2, SR-40).** `@joinkey <64 hex> <PIN>` and `@update <version> <release id> <PIN>`, checked like every admin PIN (counted failures, waits) and refused while none is set; a bench build (`CONFIG_ATALAIA_SERIAL_KEYS`) takes them without a PIN. Host tests only, not flashed.
- **The documents tell the truth about NVS encryption (FLD-2, SR-42).** The images the project builds do not encrypt the NVS or the flash and do not use secure boot; [SECURITY.md](../../SECURITY.md) lists what a lost box exposes. `firmware/esp32/docs/RELEASE_HARDENING.md` is the plan for a hardened release image (flash encryption, NVS encryption, secure boot v2, an anti-rollback floor) and the questions only the maintainer can answer. Nothing is built or burned (burning eFuses is irreversible).
- **Radio replay window on the box (FLD-1, FLD-10, SR-20 to SR-27).** See phase 2. The box's table grew from 32 to 64 sources and lives in RAM, so a box that just rebooted accepts the first packet of each source; a box that lost its epoch store draws a new epoch. Host tests only, not on a real board.
- **Lua string patterns and `string.rep` are metered (FLD-8, SR-41)** and skipping a nested CBOR value stops at 16 levels. Host tests (eight sandbox-escape cases).
