<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Field Box Hardware Bring-Up Checklist

## Board

**Heltec WiFi LoRa 32 V4.3** (bare board, 863-928 MHz, standard power).

> **Warning:** Never power up or transmit without the LoRa antenna
> connected to the LoRa IPEX connector.  The 28 dBm FEM on the
> high-power variant can be damaged by an open antenna port.

> **Wi-Fi antenna:** The bare-board kit includes only the LoRa antenna.
> A 2.4 GHz IPEX 1.0 (U.FL) FPC antenna must be connected to the WiFi
> connector, or the captive-portal setup and any future BLE features
> will barely work.

## Before the hardware: Wokwi

Run the firmware in the Wokwi emulator first ([WOKWI.md](WOKWI.md)). It
catches crashes, stack overflows, wrong pin assignments and broken screens
without a board: the first Wokwi run found a stack overflow in the memory
monitor task that would have crash-looped every Field Box. Play one Bomb
and one Domination game there before the first hardware session, so that
any problem at bring-up is down to the hardware.

What Wokwi cannot tell you, and this checklist must: the PCF8574 keypad
expander (Wokwi uses a GPIO keypad instead), the PN532, the MAX17048, the
I2S amplifier, the Heltec V4.3's Vext rail, the real panel's orientation and
colours, power, range and the 2-hour stability gate.

## Step 0: eFuse HMAC Key Provisioning (Production Only)

**Skip this step for development boards.** Without the eFuse key, NVS
encryption is not available and the game key is stored in plaintext
NVS. The firmware logs a warning at boot.

On production Field Boxes, burn a 256-bit HMAC key into eFuse block 4
before the first boot. This key protects the NVS partition contents
(game key, epoch counter) at rest:

```
espefuse.py --port /dev/ttyUSB0 burn_key \
    BLOCK_KEY0 /path/to/hmac-key.bin HMAC_UP
```

Generate the key file with:

```
dd if=/dev/urandom of=hmac-key.bin bs=32 count=1
```

After burning, enable NVS encryption in `idf.py menuconfig`:
- Component config > NVS > NVS Encryption > Enable
- Select "HMAC-based scheme" and set the eFuse key ID to 0

**This operation is irreversible.** Keep a secure backup of the key
file; all boxes in the same fleet should use the same key to allow
NVS partition interchange.

The `radio_nvs_esp.c` code works transparently with both encrypted
and unencrypted NVS -- no firmware changes are needed.

## Prerequisites

- Assembled Field Box (see `hardware/field-box/README.md` for BOM
  and wiring).
- Both antennas connected (LoRa + 2.4 GHz Wi-Fi).
- USB-C cable for programming.
- ESP-IDF v5.3+ installed, or Docker with `espressif/idf:v5.3.2`.
- Serial terminal (115200 baud).

## Step 1: First Boot Smoke Test

1. Build it with `python tools/docker_fw.py build`, then flash it:
   ```
   idf.py flash -p /dev/ttyUSB0
   ```
   (or the `esptool.py write_flash` command the build prints, with the
   files in `firmware/esp32/build/`).
2. Open serial monitor:
   ```
   idf.py monitor -p /dev/ttyUSB0
   ```
3. Verify: boot log shows firmware version, PSRAM detection (2 MB on
   V4.3), tier selection (should be "full").
4. Verify: no crash loops (watchdog resets).
5. Verify: one line per part. A part that is not connected logs a warning
   such as `PN532 NFC reader not found at 0x24: NFC disabled` and the box
   keeps booting; every part that is connected must not log one.
6. Verify: on the very first boot, LittleFS formats the storage partition
   (`mount failed ... formatting`) and `stored 2 built-in preset(s)`.

## Step 2: Vext and External Peripherals

1. The Vext rail (GPIO 36) powers the external peripherals (NFC reader,
   display, etc.) when they are wired to it.
2. The firmware does not switch Vext yet. Check the polarity in Heltec's
   V4.3 schematic (on the V3, driving GPIO 36 LOW turns Vext on), then add
   it early in `app_main` and record it here.
3. If external peripherals do not respond, check Vext first.

## Step 3: Display

1. Check display initialisation in the log: `Display initialised
   (320x240)` and `LVGL 9.2.2 on 320x240`.
2. Verify: the setup screen (first boot) or the admin PIN screen is
   visible on the external TFT, in landscape, and looks like
   `firmware/esp32/test/screens/wifi_setup.png` or `pin_entry.png`: the
   same layout, the header bar at the top, amber and red where the
   reference has them. Mirrored or upside-down text means the MADCTL value
   in `hal_esp_display.c` needs a flip; red and blue swapped means its BGR
   bit; inverted colours on an ST7789 means the inversion command.
3. Note: the on-board 0.96" OLED (GPIO 17/18) shares the I2C bus
   with the NFC reader and battery gauge.  It can show status while
   the external TFT shows the game UI.
4. If the display does not init, toggle Vext (GPIO 36) -- the display
   RST is tied to Vext in the default wiring.

## Step 4: Buttons

1. Start a Bomb game (admin PIN, game 1, `#`, `#`). Press each team
   button (GPIO 4, 5; 33, 34 for teams 3 and 4).
2. Hold the red button for 5 s: the log shows `game: event bomb.armed`
   and the screen the countdown. Hold blue for 10 s: `bomb.defused`.
3. A short press (under 5 s) must not arm the bomb.

## Step 5: Keypad

1. Verify the log shows `PCF8574 keypad at 0x20` (not `not found`).
2. On the PIN screen, press each key: every digit adds one dot, `*`
   removes one, a wrong PIN plus `#` shows "Wrong PIN, try again".
3. Hold a key down: it must count once, not repeat.
4. During a game, key presses reach the mode as `keypad.key` events.

## Step 6: LEDs

1. Start a Domination game with two teams.
2. Press and hold a team button until the zone is captured.
3. Verify: LED ring (GPIO 48) shows the team colour.

## Step 7: NFC

1. Verify the PN532 is in I2C mode (DIP switches).
2. Hold an NFC tag near the PN532 reader.
3. Serial log should show: `nfc.tag` event with UID.
4. Verify read distance (target: > 3 cm).
5. If no response, check Vext power and I2C address (0x24).

## Step 8: Audio

1. Start a game that plays sound clips (bomb armed/defused).
2. Verify: audio plays through the speaker (I2S on GPIO 6/15/16).
3. Check volume control via serial command.

## Step 9: Battery

1. The Heltec V4.3 has a built-in voltage divider on GPIO 1 (Vbat)
   gated by ADC_Ctrl (GPIO 37).  Drive GPIO 37 high, then read
   ADC on GPIO 1.
2. If an external MAX17048 gauge is wired (I2C bus, addr 0x36):
   verify serial log shows voltage and SoC%.
3. Disconnect USB-C; run on battery.  Verify readings update.
4. Reconnect USB-C: verify charging behaviour.

## Step 10: Radio (SX1262 LoRa)

> **Warning:** Connect the LoRa antenna to the LoRa IPEX connector
> BEFORE powering on. The 28 dBm FEM on the high-power V4.3.1 can be
> damaged by transmitting into an open port.

1. Verify the serial log shows `SX1262 detected (sync_hi=0x14)` and
   `SX1262 initialised: EU868, SF7, BW125k, TX N dBm, ch 869525000 Hz`
   (where N is the calculated conducted power and 869525000 is the
   default game channel).
2. If the log shows `SX1262 not detected` or `radio SPI bus init
   failed`, check that GPIO 8-14 are not used by anything else and
   that the SX1262 is soldered (the Heltec V4.3 always has it).
3. Verify the TX power value makes sense:
   - With FEM (14 dB gain) and default 2 dBi antenna on the g2
     sub-band (default 869.525 MHz): N = 13 dBm conducted.
   - Adjust `ATALAIA_RADIO_ANTENNA_GAIN_DBI` in menuconfig if the
     actual antenna differs from the 2 dBi default.
4. All nodes in a game use the same channel (default 869.525 MHz).
   Neighbouring games should use different channels within the g2
   sub-band or in other EU868 sub-bands.  The channel is configurable
   via `ATALAIA_RADIO_DEFAULT_CHANNEL_HZ` in Kconfig.
5. The radio task starts on core 0, priority 3. Verify it does not
   affect game_task timing (check game_timer_tick jitter in the log).
6. Phase 2 radio protocol (event exchange, time sync) requires a
   controller and at least two nodes. Single-box radio health can be
   verified by monitoring `radio_task` log lines for TX/RX activity.

## Step 11: Wi-Fi Setup Portal

1. Reset configuration: hold reset during boot or enter admin PIN
   and select "Setup" from the admin menu.
2. Connect to `atalaia-XXXX` AP from a phone (the 2.4 GHz antenna
   must be connected).
3. Verify: captive portal page loads automatically.
4. Fill in config and submit.
5. Verify: node reboots into normal mode.
6. The page sets the node up, but there is no DNS redirect yet: if the
   phone does not open the page by itself, browse to
   `http://192.168.4.1`.

## Step 12: Full Game Test (2 Hours) -- Phase 1 Gate

1. Set up a Domination preset with 2 teams and 120-minute timer.
2. Start the game from the keypad (enter admin PIN, select preset,
   adjust timer, confirm).
3. Periodically press team buttons to capture the zone.
4. Monitor throughout:
   - No reboots or freezes.
   - Scores update correctly on screen.
   - Timer counts down.
   - Memory usage stable (serial log from `mem_monitor` every 10 s).
5. Let the timer expire.
6. Verify: scores frozen, `final_score` screen displayed.

## Step 13: Power Loss Recovery

1. Start a new game.
2. After 5 minutes, disconnect the battery.
3. Reconnect the battery.
4. Verify: game resumes from persisted state (`/state/current.bin`).
5. Verify: `node.rebooted` event emitted.
6. Verify: timer continues from where it left off.

## Step 14: Environmental

1. Test in direct sunlight: display readability.
2. Test at operating temperature extremes (0-45 C).
3. Verify IP65 seal: no moisture after light rain test.

## Notes for Phase 2

- The SX1262 radio (GPIO 8-14) and its driver are implemented in
  Phase C. The radio task, protocol layer, event log and time sync
  are all wired. Multi-node field testing requires a controller
  (Phase D).
- NVS encryption for the game key is supported via the eFuse HMAC
  scheme (see Step 0). On dev boards without the eFuse key, the key
  is stored in plaintext NVS.
- GNSS header pins (GPIO 38-42) are used for external peripherals in
  the default pin map. If GNSS support is added, these peripherals
  must be moved to an I2C I/O expander or alternative pins.
- TX power for the FEM variant accounts for FEM and antenna gain via
  `radio_power.h` (Kconfig tuneable).
