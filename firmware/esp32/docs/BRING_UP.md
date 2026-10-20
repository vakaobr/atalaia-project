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

## Before power-on: board revision, antenna, GNSS module

1. **Identify the revision** by the radio front-end module (FEM) chip next
   to the LoRa antenna connector (or the board's silkscreen):
   **KCT8103L = Heltec V4.3** (the default), **GC1109 = Heltec V4.2**.
   For a V4.2, set `idf.py menuconfig` > Atalaia Field Box Configuration >
   Radio > Board revision > *Heltec V4.2 (GC1109)* before building, for the
   Field Box and for the USB radio modem. The wrong choice leaves the
   receiver deaf (V4.3 LNA bypassed) or the transmitter weak (V4.2 PA
   bypassed).
2. **Do not plug in the GNSS module** that ships with the V4. Its SH1.25
   connector shares GPIO 34 and 38-42 with the Field Box's display and
   button 4, and GPS is not supported in this pin map (decision E21).
3. Fit the LoRa antenna before the first power-on (step 10 explains why).

Pins that changed in phase E (for the wiring in `hardware/field-box/`):
button 2 moved from GPIO 5 to **GPIO 39** (GPIO 5 is the V4.3 FEM's CTX
control). The firmware now drives GPIO 36 (Vext) low at boot, and GPIO 7
(FEM power) high, GPIO 2 (FEM enable) high and GPIO 5 low (V4.3) or
GPIO 46 high (V4.2) once the SX1262 answers.

## Step 0: eFuse HMAC Key Provisioning (Production Only)

**Skip this step for development boards.** Without the eFuse key, NVS
encryption is not available and the game key (inside the stored join
payload) and the field join key are stored in plaintext NVS. The firmware
logs a warning at boot: `NVS encryption is off: the game key and the field
join key are stored in plain NVS`.

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

## A bare board on the desk (bench variant)

Before the box is built, a bare board with a button or two on its header
can already run a game: `python tools/docker_fw.py bench` builds the Field
Box firmware with keys from the USB serial console and no setup portal
(firmware/esp32/README.md, Build). In a serial monitor type `1234#` (the
admin PIN), then `1`, `#`, `#` for Bomb; the board's own OLED shows each
step. Buttons must be soldered to the header (or to pins soldered there):
a Dupont pin pushed into a bare hole loses contact while it is held, and
any release, even 0.1 s, starts a hold again (seen on the first V4.3 board,
2026-10-20).

## Step 1: First Boot Smoke Test

1. Build it with `python tools/docker_fw.py build`, then flash it over the
   board's USB-C port. The Heltec V4 has no USB-UART bridge: the port is
   the ESP32-S3's own USB (USB-Serial-JTAG), `/dev/ttyACM0` on Linux and a
   `COMx` port on Windows:
   ```
   idf.py -B build flash -p /dev/ttyACM0
   ```
   (or the `esptool.py write_flash` command the build prints, with the
   files in `firmware/esp32/build/`). Flashing from Windows is described
   step by step in `hardware/field-box/BUILD.md`, section 11.
2. Open a serial monitor on the same port:
   ```
   idf.py -B build monitor -p /dev/ttyACM0
   ```
   The log goes to UART0 and to this USB port; what you type on the USB
   port (`@join`, `@joinkey`) reaches the box
   (`CONFIG_ATALAIA_CONSOLE_USB_INPUT`).
3. Verify: boot log shows firmware version, PSRAM detection (2 MB on
   V4.3), tier selection (should be "full").
4. Verify: no crash loops (watchdog resets).
5. Verify: one line per part. A part that is not connected logs a warning
   such as `PN532 NFC reader not found at 0x24: NFC disabled` and the box
   keeps booting; every part that is connected must not log one.
6. Verify: on the very first boot, LittleFS formats the storage partition
   (`mount failed ... formatting`) and `stored 2 built-in preset(s)`.
7. Verify: the board's own OLED logs `SSD1306 OLED at 0x3C (128x64)`, shows
   the tower splash with the version for 2 s, then the PIN screen (or the
   setup screen), upright with the USB port on the left
   (`CONFIG_ATALAIA_OLED_FLIP` turns it round). Two `slow redraw` warnings
   around then are the OLED's full frames on the 100 kHz bus.

## Step 2: Vext and External Peripherals

1. Vext is a switched rail on the Heltec V4 for the on-board OLED and the
   LoRa front end; in the standard Field Box wiring the external
   peripherals (NFC reader, display, keypad expander) take 3V3 instead
   (`hardware/field-box/BUILD.md`). It is active low: the firmware drives
   GPIO 36 low first thing at boot
   (`CONFIG_ATALAIA_VEXT_CTL_PIN`), before any peripheral is probed. The
   log shows `Vext on (GPIO 36 low)`.
2. Measure the Vext pin on the header: it should read about 3.3 V after
   that line. Record the measurement here.
3. If the on-board OLED stays dark or the radio is deaf, check Vext; if
   the external peripherals do not respond, check their 3V3 supply.
4. Button 4 sits on GPIO 34, which is also the GNSS power control: with no
   GNSS module plugged in, check it reads high (not pressed) at rest.

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
4. If the display does not init, check its reset line: GPIO 38 in the
   default wiring (`ATALAIA_DISP_RST_PIN`), pulsed low by the driver at
   start-up; and its 3V3 supply.

## Step 4: Buttons

1. At boot the log shows each button's state at rest (`hal_btn: button 1
   (GPIO 4) released at rest`); `reads pressed at rest` means its wire is on
   the switch's NC tab or shorted to ground. Every press and release is
   logged (`hal_btn: button 2 (GPIO 39) pressed`).
2. Start a Bomb game (admin PIN, game 1, `#`, `#`). Press each team
   button (GPIO 4, 39; 33, 34 for teams 3 and 4). While red holds, the
   screen and the OLED show the arming bar filling.
3. Hold the red button for 5 s: the log shows `game: event bomb.armed`
   and the screen the countdown. Hold blue for 10 s: `bomb.defused`.
4. A short press (under 5 s) must not arm the bomb, and letting go empties
   the bar.
5. When the game's timer runs out the box shows the final screen and logs
   `game over: press any key for the game picker`; a reboot then does not
   bring the game back.

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

1. Verify the PN532 is in I2C mode (DIP switches); the log shows
   `PN532 NFC reader at 0x24`, not `not found`.
2. Write a join card: in the GM console's *Join* tab, make a payload for
   this box and write its NFC bytes to an NTAG215 or NTAG216 card (any NFC
   writer that can write raw NDEF memory; the console shows the bytes for
   page 4 onwards). The box needs the field join key first (step 10b).
3. With no game being played, hold the card on the reader: the log shows
   `join card: joined` and the screen `JOINED GAME <id>`. A card made with
   another field's key shows `join refused: bad tag`; holding the same card
   longer does nothing more.
4. Verify read distance (target: > 3 cm).
5. Player tags (phase 3, [protocol/nfc-tag.md](../../../protocol/nfc-tag.md)):
   during a game the box polls the reader every 300 ms. Check that a
   game's buttons still respond at once while no card is near (the PN532
   is set to one activation attempt per poll; if the log warned
   `configuration not acknowledged`, polls block for 100 ms each), and that
   any card held during a Kill Confirmed game logs `field: tag {"uid":...}`.
6. If no response, check the reader's 3V3 supply and I2C address (0x24). The PN532 code
   (command, ACK, response; SAMConfiguration and RFConfiguration at init;
   NTAG READ through InDataExchange) has not run on a real reader before
   this step.

## Step 8: Audio

1. Start a game that plays sound clips (bomb armed/defused).
2. Verify: audio plays through the speaker (I2S on GPIO 6/15/16).
3. Check volume control via serial command.

## Step 9: Battery

1. The firmware reads the battery from the MAX17048 gauge (I2C, address
   0x36): verify the log shows `MAX17048 detected` and that its voltage and charge
   (%) look right against a multimeter. The board's own divider on GPIO 1
   (Vbat, gated by ADC_Ctrl on GPIO 37) is not read by the firmware.
2. Without the gauge the box runs, reports no battery level (HELLO and
   STATE leave it out), and logs `MAX17048 battery gauge not found`.
3. Disconnect USB-C; run on battery.  Verify readings update.
4. Reconnect USB-C: verify charging behaviour.

## Step 10: Radio (SX1262 LoRa)

> **Warning:** Connect the LoRa antenna to the LoRa IPEX connector
> BEFORE powering on. The 28 dBm FEM on the high-power V4.3.1 can be
> damaged by transmitting into an open port.

1. Verify the serial log shows `SX1262 detected (sync_hi=0x14)`,
   `front-end module KCT8103L (Heltec V4.3) powered` (or GC1109 (Heltec
   V4.2), matching the chip you read before power-on), and
   `SX1262 initialised: EU868, SF7, BW125k, TX N dBm, ch 869525000 Hz`
   (where N is the calculated conducted power and 869525000 is the
   default game channel). An `is both a team button and the ... front-end
   control` error means a button is on a FEM pin: move the button.
2. **Measure the conducted output power before any game transmission**
   (decision C2): an attenuator and a power meter, or a calibrated SDR, on
   the LoRa port, with a single test packet. The board's FEM can reach
   27-28 dBm; the firmware sets the SX1262 to N dBm assuming 14 dB of FEM
   gain, so the output should be about N + 14 dBm. If the measured gain is
   higher, set `ATALAIA_RADIO_FEM_GAIN_DB` to the measured value: with more
   than about 14 dB of real gain the default setting would exceed 500 mW
   ERP on the g2 sub-band with a 2 dBi antenna (13 dBm + gain + 2 dBi -
   2.15 must stay at or below 27 dBm ERP; decision E20).
3. Check the receiver: with two boards 1-2 m apart, the RSSI of received
   packets (log, or the controller's node list) should be roughly -30 to
   -50 dBm. Much weaker (-80 dBm or below at that distance) means the FEM
   is not powered or the board revision is set wrong.
4. If the log shows `SX1262 not detected` or `radio SPI bus init
   failed`, check that GPIO 8-14 are not used by anything else and
   that the SX1262 is soldered (the Heltec V4.3 always has it).
5. Verify the TX power value makes sense:
   - With FEM (14 dB gain) and default 2 dBi antenna on the g2
     sub-band (default 869.525 MHz): N = 13 dBm conducted.
   - Adjust `ATALAIA_RADIO_ANTENNA_GAIN_DBI` in menuconfig if the
     actual antenna differs from the 2 dBi default.
6. All nodes in a game use the same channel (default 869.525 MHz).
   Neighbouring games should use different channels within the g2
   sub-band or in other EU868 sub-bands.  The channel is configurable
   via `ATALAIA_RADIO_DEFAULT_CHANNEL_HZ` in Kconfig.
7. The radio task starts on core 0, priority 3. Verify it does not
   affect game_task timing (check game_timer_tick jitter in the log).
8. Phase 2 radio protocol (event exchange, time sync) requires a
   controller and at least two nodes (step 10b). Single-box radio health can be
   verified by monitoring `radio_task` log lines for TX/RX activity.

## Step 10b: Joining a field controller's game

Needs the field controller with its USB radio modem (controller/README.md)
and two boards at least 1 m apart, both antennas fitted.

1. Give the box the field join key: `python -m atalaia_controller join-key`
   on the controller prints it; type `@joinkey <the 64 hex digits>` on the
   box's serial console (the log shows `join key: stored`), or enter it in
   the setup portal's "Field join key" field.
2. Create a game in the GM console, open *Join*, choose the role, and type
   the text it shows on the box's console as one line:
   `@join atalaia:join:...`. The log shows `field: joined game <id> as node
   <n> ...` and the console's node list shows the box (its HELLO).
3. Start the game in the console: the box starts the mode. Capture with a
   team button: the capture appears in the console's feed within a second
   or two, and the scores follow the box's STATE (every 15 s, and right
   after a capture).
4. Pause, resume and end from the console: the box follows. After the end
   the log shows `left game <id>; the game key is erased`.
5. Battery pull during a game: the box comes back in the same game (`field:
   ... resumed game`), with `node.rebooted` in the console's feed and no
   capture lost.
6. Range: walk the box away until the console marks it offline; with a
   third box joined half-way, the far box's captures reach the console
   again through the middle box's relay.

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
4. Verify: game resumes from persisted state (`/state/current.bin`):
   the log shows `Resumed game from saved state`.
5. Verify: `node.rebooted` event emitted.
6. Verify: timer continues from where it left off, and the scores are the
   ones before the power loss.
7. With Bomb: arm it, cut the power for 30 s, reconnect: it comes back
   armed with the fuse it had left (the time the box was off does not
   count: game time stops with it), and explodes when that runs out.

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

## The I/O pod (phase 3, plan phase F)

The pod image (`python tools/docker_fw.py pod`, `firmware/esp32/build-pod/`)
runs on the same board with the same pins for its buttons, keypad
expander, LED ring, NFC reader, battery gauge and amplifier; the display is
not fitted (its GPIOs are free). Do the board steps above that apply
(revision and FEM, antenna before power-on, conducted power, NFC, keypad,
LEDs, audio), then these, which need the board and an Android phone with
the app (`python tools/docker_app.py apk`). None of them has been run yet.

1. **Boot.** Flash `build-pod/` as in step 1 and watch UART0 (GPIO 43/44,
   a 3.3 V USB-UART adapter: the USB-C port carries the pod's frames, not
   the log). Expect `Atalaia I/O pod`, `Vext on`, one line per part that is
   missing, the SX1262 and FEM lines of step 10, `advertising as
   atalaia-pod-XXXX` and `I/O pod ... capabilities [...]` listing what is
   fitted.
2. **USB link.** Plug the pod into the phone with a USB-C OTG cable (the
   phone powers it). In the app: Prop > I/O pod > Find pods: the pod is
   listed (CDC ACM, Espressif 303a:1001); open it and allow USB access: the
   app shows "Pod linked over USB" with the capability count. Check that
   opening the port does **not** reset the pod (the app sets DTR and RTS
   together; on the USB-Serial-JTAG only RTS with DTR low resets: the
   UART0 log must not show a new boot).
3. **Bluetooth link.** Unplug USB. Find pods again: `atalaia-pod-XXXX`
   (the last 4 hex digits of its Bluetooth address) is listed. Open it:
   Android asks to pair (Just Works: confirm); within 30 s the app shows
   "Pod linked over BLE". The UART0 log shows the connection, the MTU (247)
   and the encryption. Open it again later: no second pairing question (the
   bond is kept). With a second phone, the pod is not listed while the
   first is connected (one phone at a time) and is again once it leaves.
4. **Inputs.** Start a prop game on the phone (any mode with team buttons),
   with the pod linked: each button is the game's team by number (button 1
   = first team), holding one captures as on a Field Box; keypad keys reach
   the mode (Codes); a player tag on the pod's reader is checked by the
   phone (Kill Confirmed, Medic Kit). Time from press to the phone's
   reaction: under 100 ms over USB, under 200 ms over Bluetooth.
5. **Outputs.** The mode's team light fills the ring in the team's colour;
   its sounds play on the pod's amplifier as tones.
6. **Enclosure switch.** Fit a microswitch from GPIO 47 to GND that the
   closed lid holds closed. Open the lid during the game: the phone shows
   "Someone opened the I/O pod" and the GM console's feed shows
   `node.tamper` (`pod_opened`). Without a switch fitted, nothing is ever
   reported.
7. **Radio through the pod.** Join the phone's prop to a controller's game
   with the pod linked (a join payload; the field's Wi-Fi off, so the radio
   is the only link): the console lists the phone's node (HELLO, transports
   LoRa), the game's start reaches the phone, its captures reach the
   console within 1-2 s and are acknowledged (the phone shows "Linked to
   the controller over the pod's radio"). Turn the field's Wi-Fi on: the
   phone moves to the Wi-Fi link and the pod's radio goes quiet; turn it
   off again: the radio takes over. Measure the pod's conducted power as in
   step 10 before any of this.
8. **Losing the phone.** Unplug the USB (or walk the phone out of Bluetooth
   range): the UART0 log shows `radio cleared` (the game key is
   forgotten). Link again: the phone configures the radio again with the
   next epoch and the console keeps hearing it.
9. **Battery.** With the MAX17048 fitted, IDENT and the Pod Status
   characteristic carry its level (nRF Connect or a similar app can read
   Pod Status: battery %, the last packet's RSSI, flags).
10. **Hours.** A 2-hour game with the pod on battery and Bluetooth: no
    watchdog reset in the UART0 log, no lost link, the battery estimate on
    a 3000 mAh cell.
