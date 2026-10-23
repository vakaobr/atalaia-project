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
2. **The GNSS module** that ships with the V4 may stay plugged into its
   SH1.25 connector: the pin map leaves the connector's GPIO 34 and 38-42 to
   it (decision PIN-1), and the firmware keeps it switched off (GPIO 34
   high) until a GPS-based mode uses it. No driver reads it yet.
3. Fit the LoRa antenna before the first power-on (step 10 explains why).

> **Rewire if you wired the old pin map** (before 2026-10-21): button 2
> **GPIO 39 -> 48**, button 3 **33 -> 44**, button 4 **34 -> the PCF8574's
> P7**, LED ring data **48 -> 35**, display MOSI **40 -> 33**, SCK
> **41 -> 47**, CS **42 -> 1**, display RESET and backlight (LED) **38 and
> 47 -> 3V3**. A button left on GPIO 39 pulls the GNSS module's TX line to
> ground and is no longer read; one on GPIO 34 switches the module's power.
> Button 1 (GPIO 4), display DC (3), I2C (17/18) and audio (6/15/16) stay.

Pins the firmware drives by itself: GPIO 36 (Vext) low and GPIO 34 (GNSS
power) high at boot, then GPIO 7 (FEM power) high, GPIO 2 (FEM enable) high
and GPIO 5 low (V4.3) or GPIO 46 high (V4.2) once the SX1262 answers.

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
(firmware/esp32/README.md, Build). An adopted board boots to **READY /
next game** (decision BN-10): any key brings the game picker; an unadopted
one shows its pairing code first (`*` gives the picker). In a serial monitor
type a key, then `1234#` (the bench build's admin PIN; a Field Box has none until its setup), then `1`, `#`, `#` for Bomb; the
board's own OLED shows each step. Buttons must be soldered to the header (or to pins soldered there):
a Dupont pin pushed into a bare hole loses contact while it is held, and
any release, even 0.1 s, starts a hold again (seen on the first V4.3 board,
2026-10-20). The buttons go on **GPIO 4 (red) and GPIO 48 (blue)**: a
board wired with blue on GPIO 39 (the pin map before 2026-10-21) must move
that wire to GPIO 48, since GPIO 39 is now the GNSS module's line and the
firmware no longer reads a button there.

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
   port (`@join`, `@joinkey`, `@adopt-info`) reaches the box
   (`CONFIG_ATALAIA_CONSOLE_USB_INPUT`).
3. Verify: boot log shows the firmware version with its commit (`Atalaia firmware
   v0.3.0-dev.412+g8560d54 (core v0.3.0-dev)`, the commit you built; `.dirty` if the tree
   had changes; what `python3 tools/docker_fw.py version` printed), PSRAM detection (2 MB on
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
4. The log shows `GNSS module off (GPIO 34 high)`. With the module plugged
   in, its LED (if it has one) stays dark. Optional check of the connector
   with a bench build where `CONFIG_ATALAIA_GNSS_POWER_ON=y`: the log says
   `GNSS module on (GPIO 34 low)`, the module's 3.3 V pin (or its LED)
   comes up, and outdoors its PPS (GPIO 41) starts blinking once it has a
   fix. Record what you see; nothing in the firmware reads it yet.

## Step 3: Display

1. Check display initialisation in the log: `Display initialised
   (320x240)` and `LVGL 9.2.2 on 320x240`.
2. Verify: the setup screen (first boot), the admin PIN screen (not
   adopted) or the Ready screen (adopted, no game) is visible on the
   external TFT, in landscape, and looks like
   `firmware/esp32/test/screens/wifi_setup.png`, `pin_entry.png` or
   `ready_picker.png`: the
   same layout, the header bar at the top, amber and red where the
   reference has them. Mirrored or upside-down text means the MADCTL value
   in `hal_esp_display.c` needs a flip; red and blue swapped means its BGR
   bit; inverted colours on an ST7789 means the inversion command.
3. Note: the on-board 0.96" OLED (GPIO 17/18) shares the I2C bus
   with the NFC reader and battery gauge.  It can show status while
   the external TFT shows the game UI.
4. If the display does not init, check its RESET pin: on 3V3 in the default
   wiring (`ATALAIA_DISP_RST_PIN=-1`; the driver resets the panel with the
   SWRESET command); then CS (GPIO 1), DC (3), MOSI (33), SCK (47) and its
   3V3 supply. A dark screen with a good log is the backlight: its LED pin
   goes to 3V3.

## Step 4: Buttons

1. At boot the log shows each button's state at rest (`hal_btn: button 1
   (GPIO 4) released at rest`); `reads pressed at rest` means its wire is on
   the switch's NC tab or shorted to ground. Every press and release is
   logged (`hal_btn: button 2 (GPIO 48) pressed`). Button 4 is on the
   keypad expander's P7 (`hal_btn: button 4 on the keypad expander's P7`,
   then `button 4 (P7) pressed`); it needs the keypad expander (step 5).
   With button 3 on GPIO 44 the log says `no console input on UART0`:
   expected, the USB console still takes input.
2. Start a Bomb game (a key from Ready, the admin PIN, game 1, `#`, `#`). Press each team
   button (GPIO 4, 48; GPIO 44 and P7 for teams 3 and 4). While red holds, the
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
3. Verify: LED ring (GPIO 35) shows the team colour. The board's own white
   LED, on the same pin, flickers faintly while the ring changes: expected.

## Step 7: NFC

1. Verify the PN532 is in I2C mode (DIP switches); the log shows
   `PN532 NFC reader at 0x24`, not `not found`.
2. Write a join card: in the GM console's *Join* tab, make a payload for
   this box and write its NFC bytes to an NTAG215 or NTAG216 card (any NFC
   writer that can write raw NDEF memory; the console shows the bytes for
   page 4 onwards). The box needs the field join key first: adopt it (step
   10a), by cable or with a field card, which this reader takes too.
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
   With `ATALAIA_RADIO_LOG_PACKETS` (on in the bench variant) every sent
   packet logs `TX <n> bytes, <ms> ms budget left`; a `TX timeout` on
   every packet means the chip never transmits (before RF-1 this was the
   missing TCXO), and an `SX1262 device errors` error at boot names the
   chip's own fault.
3. Check the receiver: with two boards 1-2 m apart, the RSSI of received
   packets (`RX <n> bytes, RSSI <dBm>` with `ATALAIA_RADIO_LOG_PACKETS`, or
   the controller's node list) should be roughly -30 to
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

## Step 10a: Adopting the box (USB cable, field card, pairing code)

[protocol/adoption.md](../../../protocol/adoption.md). Board 1 (the Field Box bench build) on
its USB-C port; the controller and its modem (board 2) as in step 10b.

1. **By hand first.** In a serial monitor on the box's port type `@adopt-info`. One line
   comes back, `ATALAIA-ADOPT {"v":1,"kind":"info","name":"field-box","mac":"..",...,
   "state":"unadopted",...}` (a board that was given `@joinkey` before says `adopted`).
   Check that `mac` is the port's USB serial number (Windows: Device Manager, the port's
   *Details*, *Device instance path*; Linux: `udevadm info /dev/ttyACM0 | grep SERIAL_SHORT`):
   the console relies on it to tell boxes apart.
2. **From the controller.** On the Pi, plug the box into a USB port; with the controller in
   Docker on Windows/WSL, either bridge the box's COM port to TCP on Windows
   (`python tools/serial_bridge.py COM3 7001`, with pyserial installed and the serial
   monitor closed) and start the controller with
   `ATALAIA_ADOPT_USB_PORTS=socket://host.docker.internal:7001`, or attach the board to
   WSL with `usbipd attach --wsl --busid <id>` and pass `--device /dev/ttyACM1` to the
   container. In the console's *Adotar / Adopt* tab press *Look for boxes*: the board is
   listed with its name, MAC and *not adopted*; the modem's port is not. Press *Adopt*,
   check the name and MAC, confirm. The box's screen and OLED show ADOPTED, the field's
   name and the fingerprint the tab shows (`join-key --fingerprint` prints it too); the
   log shows `adoption (usb): adopted, field XXXX-XXXX`. Adopt again: *already adopted*.
3. **Another field's box.** Give the board another key by hand (`@adopt <64 other hex
   digits> 1234`: the bench build's admin PIN), then adopt it from the console: it asks
   for the admin PIN; `9999` gives *wrong PIN*, `1234` moves it back. Five wrong PINs in a
   row start a wait of 1 minute (then 2, 4 ... 60): the screen shows *PIN locked · try
   again in N min*, a reset starts the same wait again in full (the count is in NVS), and
   the right PIN after the wait sets the count back (decision AD-28).
4. **The field card** (once a PN532 is fitted, step 7): *Make the field card*, write the
   bytes to an NTAG215 from page 4, tap it on an unadopted board (ADOPTED, the fingerprint)
   and on a board of another field (the PIN screen: type `1234#` on the keypad or the
   serial keys). A field card held on the reader during a game logs
   `field card: ignored during a game`. Keep the card locked away: it is the field's
   master secret.
5. **The pairing code over the radio** (board 1 unadopted, board 2 the controller's modem
   with this firmware: its IDENT says `"pair": true`). Erase board 1's NVS first if it was
   adopted (`idf.py -B build-bench erase-flash` and flash it again, or `esptool.py erase_region
   0x9000 0x6000`: the NVS partition, partitions.csv). At start it logs `pairing: listening on
   869525000 Hz` and `pairing: code NNN NNN ...`; the OLED shows the code (the bench build has
   no TFT). In the *Adopt* tab, *Pair by code (radio)* → *Look for boxes on the radio*: within
   about 15 s the board is listed by name with its RSSI. Type a wrong code first: the console
   says the code was not the one it shows, and after 10 s the board shows `Try again` with a
   new code. Type the new code: `adoption (radio): adopted, field XXXX-XXXX`, ADOPTED on the
   OLED, the run *adopted* in the console and in its records, then the board announces itself
   as a free box (step 10b's invites); `@pair` on it now says it is adopted. Note the RSSI
   at 1 m and how far the pairing still works.
6. After the tests, `python3 -m atalaia_controller join-key --rotate` on a test controller
   shows the boxes as *adopted to this field's old key*; adopt them again with the PIN.

## Step 10b: Joining a field controller's game

Needs the field controller with its USB radio modem (controller/README.md)
and two boards at least 1 m apart, both antennas fitted.

1. Adopt the box (step 10a). By hand still works: `python -m atalaia_controller join-key`
   on the controller prints the key; type `@joinkey <the 64 hex digits>` on the
   box's serial console (the log shows `join key: stored`; a box adopted to
   another field refuses it), or enter it in the setup portal's "Field join key" field.
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

## Step 10b2: Invited into the next game over the radio (two boards on the desk)

The box between games ([protocol/field-frames.md](../../../protocol/field-frames.md), decisions
RJ-1 to RJ-15): after a game it announces itself, and the GM invites it into the next game from
the console, with no card or text. Two Heltec V4.3 boards: **board 1** the Field Box (bench
build) on COM3, **board 2** the USB modem on COM4, behind a controller running in Docker in WSL.

1. **Flash both.** `python tools/docker_fw.py bench` and the `esptool` command it prints, with
   `-p COM3`; `python tools/docker_fw.py modem` and its command with `-p COM4`.
2. **The modem into WSL** (an administrator PowerShell; `usbipd` from the usbipd-win project):
   `usbipd list` (note board 2's BUSID), `usbipd bind --busid <BUSID>`, then
   `usbipd attach --wsl --busid <BUSID>`; in WSL it is `/dev/ttyACM0`.
3. **The controller in Docker** (WSL, in the repository; `~/atalaia-bench` keeps its database):

   ```sh
   mkdir -p ~/atalaia-bench
   docker run --rm -it --device /dev/ttyACM0 -p 8080:8080 -v "$PWD:/src" -v ~/atalaia-bench:/data \
     -w /src -e ATALAIA_MODEM_PORT=/dev/ttyACM0 -e ATALAIA_API_HOST=0.0.0.0 \
     -e ATALAIA_CONTROLLER_DB_PATH=/data/controller.db -e ATALAIA_MQTT_ENABLED=false atalaia-dev \
     sh -c 'cmake -S core -B /tmp/c -DATALAIA_SHARED=ON >/dev/null && cmake --build /tmp/c >/dev/null &&
            cd controller && ATALAIA_CORE_LIB=/tmp/c/libatalaia_core.so python3 -m atalaia_controller run'
   ```

   Expected in its log: `modem link up` and the modem's IDENT with `"field": true` (an older
   modem image lacks it: flash board 2 again). In another WSL shell,
   `docker exec <container> sh -c 'cd /src/controller && python3 -m atalaia_controller tokens'`
   and `... join-key` print the GM token and the field join key.
4. **Board 1 gets the key.** In a serial monitor on COM3: `@joinkey <the 64 hex digits>`. Expected:
   `join key: stored`; `@lobby` prints the box's device id (16 hex digits), `free for an
   invite`, the channel (869525000 Hz) and no invites yet. Within 20 s the bench log
   (`ATALAIA_RADIO_LOG_PACKETS`) shows `TX 70-90 bytes`: its first announcement.
5. **The first game, by text.** In the console (`http://localhost:8080/console/`, the GM token):
   create a Domination game. The *Boxes for this game* dialog opens with board 1 (its name,
   `field-box` by default, its RSSI and when it was heard): close it this once and join by
   text as in step 10b (*Join*, role zone, `@join atalaia:join:...` on COM3). The game tab says
   "Nenhuma caixa se juntou para: zone" until the box's HELLO, then *Começar* without
   "mesmo assim": start, capture, end.
6. **Free again.** After the end, board 1's log shows `game <id> ended`, an announcement within
   2-20 s, and 30 s after the end the OLED shows **READY / Next game** (**PRONTA / Próximo jogo**
   when the field's box language is Portuguese). `@lobby`: free, last game
   `<id>` (zone). The announcements then come about every 72 s (note the times: decision RJ-11).
7. **The invite.** Create a second game: the dialog lists board 1 ticked as *último jogo*, role
   zone. *Convidar (1)*. Expected within a second or two: on COM3 `field: invite <n>: accepted`
   and `joined game <id2> as node <n> ... epoch 1` (a new game's epochs start at 1: RFC 0001
   Amendment 9), the OLED **WAITING / Game <id2>** (**À ESPERA / Jogo <id2>**); in the dialog
   *convidada*, then *aceitou, a juntar-se*, then *juntou-se* (the box's HELLO). *Começar* starts
   the game with no confirmation about missing boxes. Note the RSSI shown, and the modem's
   `duty_ms` in the *Controlador* tab before and after.
8. **Refusals.** End game 2; on board 1 press a key and start a Bomb game from the picker; create
   game 3 and invite board 1: the row says *recusou: noutro jogo* and the Bomb game goes on.
   Stop it (power cycle board 1: it boots free). Then `@joinkey` with another key on board 1:
   it no longer appears after the dialog's *Procurar caixas*, and an invite to it fails after
   three attempts (*falhou: no answer*); `@lobby` counts the controller's frames as ignored.
   Give it the field's key again.
9. **Many games in a row (decision BN-7).** Play (or just create, invite, start and end) more
   than 16 games with board 1 without reflashing: every game it is heard (the dialog reaches
   *juntou-se*, the console shows its HELLO) and its log says `epoch 1` at each join; the modem's
   `rx_auth_fail` (its OLED and IDENT counters) does not climb. Reboot board 1 in a game: it comes
   back at epoch 2 and is heard.
10. **Record** in `docs/review/decisions-to-review.md` (RJ-11, RJ-15): the announcement interval
   seen, the time from *Convidar* to *juntou-se*, the RSSI, and any refusal that should not have
   happened.

### What the box's screens say through a game

(Decisions BN-6 and BN-10 to BN-14; the reference images are in
`firmware/esp32/test/screens/` and `screens/oled/`, `_pt` for Portuguese.)

| On the screen | English / Português | Means |
| --- | --- | --- |
| `ready` | READY · Next game / PRONTA · Próximo jogo | Adopted, in no game: it can be invited. A key brings this box's own game picker (admin PIN). Shown from boot and 30 s after a game ends |
| `waiting` | WAITING · Game N, The game hasn't started / À ESPERA · Jogo N, O jogo ainda não começou | Joined (by card, text or an invite: "Invited: zone") and waiting for the GM's Start. Nothing else is shown until then |
| `playing` | GAME ON / JOGO EM CURSO | The game has started; the mode's own screen follows as soon as it draws one |
| `neutral` | ZONE · NEUTRAL, Hold to capture / ZONA · LIVRE, Mantém premido; on the OLED, while a team holds its button, a bar that fills over the capture hold and the team's name beside it (BN-26) | A running zone that no team holds (Domination, Hold-All, Last Stand, Master and Satellites) |
| `captured` | ZONE HELD · RED / ZONA OCUPADA · RED; the OLED: RED big, the team's points on this box in the header (12 pts), how long it has held the zone below (held for 2:15 / ocupada 2:15, ticking each second; while another team holds its button, the bar and that team instead, BN-23, BN-26) | A team holds the zone |
| `standby` (Bomb) | READY · Hold to arm / PRONTA · Mantém premido para armar | The bomb is not armed yet; "standby" is never used for a zone |
| `final_score` | GAME OVER / FIM DO JOGO | The game ended; Ready follows |

The language is the game's (the console's *Língua das caixas* / *Box language*, by default the
language of the console that created the game), kept for the box's screens between games and
after a reboot; a join from an older controller gives English.

## Step 10c: Firmware update over the air (one board on the desk)

The whole update path ([protocol/firmware-update.md](../../../protocol/firmware-update.md)) with
the Heltec V4.3 alone: the controller runs on the PC without a radio, and the box is told to
update from its serial console (`@update`, the same checks as the controller's CMD update),
then downloads over the Wi-Fi from the controller, checks, installs and reboots. Done on a
Heltec V4.3 on 2026-10-22 (decisions OT-1 to OT-6), sent by the controller over LoRa from a
controller in Docker: steps 1-7 pass (download, check and install in about 11 s on a home
network, confirmed after the self-test, the controller's record `done`); step 8 passes too
(OT-6). If it fails, the log names why: `Wi-Fi starting: DMA-capable RAM ...`,
`Wi-Fi driver did not start: ...`, `the controller's certificate: ...`. The board needs its **2.4 GHz Wi-Fi antenna**, and the
PC and the board the same 2.4 GHz network (the "field Wi-Fi" here is your own). In WSL:
`python3`, in the repository; on Windows `cmd`: the flasher of `hardware/field-box/BUILD.md`
section 11 (`%FLASH%`, `COM5`).

1. **A throw-away bench key** (never used for anything else), outside the repository:

   ```sh
   python3 tools/firmware_release.py keygen --unencrypted --out ~/atalaia-bench/bench.pem
   ```

   Note its `public key (hex)` (HEX below) and `(base64)` (B64).
2. **Image A (installed by USB) and image B (the update)**, both bench builds trusting that
   key; B has a higher version. A is a development build (its version carries the commit,
   `0.3.0-dev.N+g<commit>`); B gets an exact one above every dev build of 0.3.0 (FV-4). Each
   build replaces `build-bench/`, so copy each out:

   ```sh
   python3 tools/docker_fw.py bench --release-keys=HEX
   cp -r firmware/esp32/build-bench /mnt/c/atalaia-bench-A
   python3 tools/docker_fw.py bench --release-keys=HEX --fw-version=0.3.1-bench.1
   mkdir -p ~/atalaia-bench/B && cp firmware/esp32/build-bench/atalaia_esp32.bin ~/atalaia-bench/B/
   python3 tools/firmware_release.py sign ~/atalaia-bench/B/atalaia_esp32.bin --key ~/atalaia-bench/bench.pem
   ```

   The last command prints the variant (`box-bench`), the board and the release; the
   **release id** is the first 16 hex digits of its `sha256`.
3. **Flash A by USB, all of it** (the bootloader changed: it now rolls back an image that
   does not confirm itself), from `cmd`:

   ```
   cd C:\atalaia-bench-A
   %FLASH% -m esptool --chip esp32s3 -p COM5 -b 460800 --before default_reset --after hard_reset write_flash "@flash_args"
   %FLASH% -m serial.tools.miniterm COM5 115200
   ```

   The log shows `Atalaia firmware v0.3.0-dev.N+g<commit>` and `fw_update: 1 release key(s);
   version 0.3.0-dev.N+g<commit>, variant box-bench, board heltec_v4_3`.
4. **The controller, without a radio, serving HTTPS on the PC's network address** (find it
   with `ipconfig`: 192.168.1.50 below). A `bench.toml`:

   ```toml
   [controller]
   db_path = "/home/<you>/atalaia-bench/controller.db"
   [modem]
   port = ""
   [api]
   tls_names = ["192.168.1.50"]
   [firmware]
   release_keys = ["B64"]
   variants = ["box-bench"]
   ```

   Run `python3 -m atalaia_controller --config bench.toml` (controller/README.md) and allow
   inbound TCP 8443 in the Windows firewall (with WSL's mirrored networking, the Hyper-V
   firewall too). `python3 -m atalaia_controller --config bench.toml join-key` prints the
   field join key.
5. **Join the box.** In the console (`http://localhost:8080/console/`, the GM token from
   `... tokens`): create a Domination game, *Join*: role zone, node 1, *Generate*. On the box's
   serial console, one line each:

   ```
   @joinkey <the join key>
   @join atalaia:join:...
   @wifi <your network> <its password>
   ```

   The log shows `join key: stored`, `field: joined game ...` and `field Wi-Fi: stored`.
6. **Upload B** in the console's *Boxes* tab (*Firmware updates*: the `.bin` and its
   `.release.json`). It is listed as `0.3.1-bench.1`, `heltec_v4_3`, signed by the bench key.
7. **Update:** on the serial console `@update 0.3.1-bench.1 <release id>`. Expected: the OLED
   shows `UPDATING` and the percentage, the log `update to 0.3.1-bench.1 ... started`, then
   `installed (... bytes): rebooting into it`; after the reboot `firmware 0.3.1-bench.1 confirmed
   after its self-test` and `Atalaia firmware v0.3.1-bench.1`. The controller's log shows the
   box's report (started from the console, the update was not one the controller sent: it logs
   it and keeps no record). Note the download time and the heap left (`mem_monitor`).
8. **What must be refused** (each leaves the box on the version it runs):
   - `@update 0.3.1-bench.1 <release id>` again: `update refused: not_newer`.
   - Another throw-away key K2 (step 1), its B64 added to `release_keys` (the controller
     trusts it, the box does not): build `--fw-version=0.3.2-bench.1` with `--release-keys=HEX`,
     sign it with K2, upload, `@update`: `update to 0.3.2-bench.1 failed: bad_signature`.
   - The same image signed with the bench key, and the USB cable pulled while the OLED shows
     about 50 %: after power-up the box still runs 0.3.1-bench.1.
   - **Rollback:** build `--fw-version=0.3.3-bench.1` **without** `--release-keys`, sign it with
     the bench key, upload, `@update 0.3.3-bench.1 <id>`: it installs and reboots, its self-test
     fails (`core FAILED`: an image without a release key could never be updated again), and
     the box comes back on 0.3.1-bench.1 (`rolling back`, then the old version's boot log).
9. **Afterwards:** delete `~/atalaia-bench` (the keys with it) and flash a normal build.

## Step 10d: The USB radio modem's screen

The modem board (`python tools/docker_fw.py modem`, plugged into the
controller) shows its status on its own OLED; the full reading of each line
is in [README.md](../README.md#the-modems-oled).

1. Power it from a laptop or the controller with the antenna fitted. The log
   (UART0, not the USB port) shows `SSD1306 OLED at 0x3C (128x64)` and,
   after the 2 s splash (tower, ATALAIA, MODEM MODE, version), `OLED status
   on`. The screen reads `LINK waiting`, `IDLE no game`, `CH 869.525 MHz`,
   zero counts and the full budget (`DUTY 360.0s left` on the g2 sub-band).
2. Start the controller: within a second `LINK OK` (its first ping or
   IDENT). Create and start a game in the console: `GAME <id>`, and `TX`
   climbs with the TIME beacons; `RX` climbs once a box is joined and heard.
3. Stop the controller: about 12 s later `LINK DOWN`, inverted. Start it
   again: back to `LINK OK` without touching the modem.
4. Without the SX1262 (or with a TCXO fault) the screen shows `RADIO FAULT`
   and the reason from the log (`SX1262 not found (BUSY stuck)`, `SX1262
   errors 0x0020 (TCXO)`); the controller sees `"radio": "none"`.
5. A board without an OLED (or with Vext off) logs one `SSD1306 OLED not
   found` warning and works as a modem all the same.

## Step 11: Wi-Fi Setup Portal

1. Reset configuration: hold reset during boot or enter admin PIN
   and select "Setup" from the admin menu. (A Field Box build only: bench and Wokwi
   builds skip the portal and use the admin PIN 1234, which they say in the log.)
2. Connect to `atalaia-XXXX` AP from a phone (the 2.4 GHz antenna
   must be connected).
3. Verify: captive portal page loads automatically.
4. Fill in config and submit. The admin PIN has no default (decision AD-29): 1234, 0000,
   a sequence (9876, 7890) or a repeated pair (1212) is refused with *Choose another admin
   PIN*; until a PIN is set the keypad picker shows *No admin PIN set* and adoption to
   another field answers `no_pin`. A box set up before has none if its PIN was one of those:
   type `@admin-pin <PIN>` on its USB console (`@admin-pin <PIN> <new PIN>` changes it).
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
- The GNSS connector's pins (GPIO 34, 38-42) are kept for its module
  since 2026-10-21 (decision PIN-1); a GNSS driver comes with the first
  GPS-based mode (Kconfig: the GNSS menu has its pins and its power).
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

1. **Boot.** Flash `build-pod/` as in step 1 and watch UART0 on GPIO 43
   (a 3.3 V USB-UART adapter's RX and GND only: GPIO 44 is team button 3;
   the USB-C port carries the pod's frames, not the log). Expect `Atalaia I/O pod`, `Vext on`, one line per part that is
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
