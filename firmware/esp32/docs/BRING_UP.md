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

## Prerequisites

- Assembled Field Box (see `hardware/field-box/README.md` for BOM
  and wiring).
- Both antennas connected (LoRa + 2.4 GHz Wi-Fi).
- USB-C cable for programming.
- ESP-IDF v5.3+ installed, or Docker with `espressif/idf:v5.3.2`.
- Serial terminal (115200 baud).

## Step 1: First Boot Smoke Test

1. Flash the firmware:
   ```
   idf.py flash -p /dev/ttyUSB0
   ```
2. Open serial monitor:
   ```
   idf.py monitor -p /dev/ttyUSB0
   ```
3. Verify: boot log shows firmware version, PSRAM detection (2 MB on
   V4.3), tier selection (should be "full").
4. Verify: no crash loops (watchdog resets).
5. Verify: on-board LED (GPIO 35) blinks briefly during init.

## Step 2: Vext and External Peripherals

1. The Vext rail (GPIO 36) must be driven high to power external
   peripherals (NFC reader, display, etc.).
2. Verify: `shell.c` drives GPIO 36 high early in `app_main`.
3. If external peripherals do not respond, check Vext first.

## Step 3: Display

1. Check display initialisation in the log (ILI9341 or ST7789).
2. Verify: setup page or preset picker visible on the external TFT.
3. Note: the on-board 0.96" OLED (GPIO 17/18) shares the I2C bus
   with the NFC reader and battery gauge.  It can show status while
   the external TFT shows the game UI.
4. If the display does not init, toggle Vext (GPIO 36) -- the display
   RST is tied to Vext in the default wiring.

## Step 4: Buttons

1. Press each team button (GPIO 4, 5).
2. Serial log should show: `team_input.press` / `team_input.release`.
3. Hold a button for > 250 ms: verify `team_input.hold` events at
   250 ms intervals.

## Step 5: Keypad

1. Press each key (0-9, *, #).
2. Serial log should show: `keypad.key` events.
3. Enter a multi-digit code + #: verify `keypad.code` event.

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
2. Verify: audio plays through the speaker (I2S on GPIO 0/46/47).
3. Check volume control via serial command.

## Step 9: Battery

1. The Heltec V4.3 has a built-in voltage divider on GPIO 1 (Vbat)
   gated by ADC_Ctrl (GPIO 37).  Drive GPIO 37 high, then read
   ADC on GPIO 1.
2. If an external MAX17048 gauge is wired (I2C bus, addr 0x36):
   verify serial log shows voltage and SoC%.
3. Disconnect USB-C; run on battery.  Verify readings update.
4. Reconnect USB-C: verify charging behaviour.

## Step 10: Wi-Fi Setup Portal

1. Reset configuration: hold reset during boot or enter admin PIN
   and select "Setup" from the admin menu.
2. Connect to `atalaia-XXXX` AP from a phone (the 2.4 GHz antenna
   must be connected).
3. Verify: captive portal page loads automatically.
4. Fill in config and submit.
5. Verify: node reboots into normal mode.

## Step 11: Full Game Test (2 Hours) -- Phase 1 Gate

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

## Step 12: Power Loss Recovery

1. Start a new game.
2. After 5 minutes, disconnect the battery.
3. Reconnect the battery.
4. Verify: game resumes from persisted state (`/state/current.bin`).
5. Verify: `node.rebooted` event emitted.
6. Verify: timer continues from where it left off.

## Step 13: Environmental

1. Test in direct sunlight: display readability.
2. Test at operating temperature extremes (0-45 C).
3. Verify IP65 seal: no moisture after light rain test.

## Notes for Phase 2

- The SX1262 radio (GPIO 8-14) is unused in Phase 1.  Keep its pins
  free and the LoRa antenna connected.
- GNSS header pins (GPIO 38-42) are used for external peripherals in
  the default pin map.  If GNSS support is added, these peripherals
  must be moved to an I2C I/O expander or alternative pins.
- TX power for the FEM variant must account for the FEM's gain.
