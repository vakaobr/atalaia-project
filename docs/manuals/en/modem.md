<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Set up the radio modem

The **radio modem** is the controller's radio: a Heltec WiFi LoRa 32 V4 board, flashed with the modem image, plugged into the controller's USB port. The controller (a Raspberry Pi) has no radio of its own. Without the modem it runs and the console opens, but nothing reaches the boxes and nothing is heard from them.

This page is the whole path, from a bare board to a box joining a game through the modem. The other guides link here: the [firmware guide](firmware.md#9-the-modem-board), the [controller setup guide](controller-setup.md#3-prepare-the-modem-board) and the [Game master manual](game-master.md#on-a-raspberry-pi-or-another-linux-computer).

> **What was tested, and what was not.** A modem flashed like this ran with the controller and real boxes on a bench (2026-10-21): the controller in Docker on Windows (WSL2), the modem on a Windows COM port, which the container reached through a small COM-to-TCP bridge (see the advanced note in section 7). **Not yet run on a Raspberry Pi**: the Linux port names, the `dialout` group and the `systemd` steps below follow the project's files and the controller guide, and no Pi has run them. On macOS (2026-11-02, a Mac mini with Apple silicon, macOS 27) the modem image and box images were flashed as in section 4, and the controller in Docker reached the modem through a bridge on the Mac (section 7) and logged `modem link up`; a controller run natively on macOS is not tried. The browser flasher is not tried with a real board. Not tested on a field.

## 1. The path in short

1. Get the parts and fit the **LoRa antenna** (section 2).
2. Get the modem image: download it, or build it (section 3).
3. Flash the board (section 4).
4. Check the board's screen (section 5).
5. Plug it into the controller and find its port (section 6).
6. Put the port in the controller's settings and restart the controller (section 7).
7. Check that the controller and the modem talk (section 8).
8. Join a box to a game through it (section 9).

If something fails, go to the table in [section 10](#10-troubleshooting).

## 2. Before you start

| You need | Notes |
| --- | --- |
| A **Heltec WiFi LoRa 32 V4**, for the modem only | The same revision (V4.3 or V4.2) as your boxes. V4.2 has the chip GC1109 next to the LoRa connector. Use a board you do not need as a box: a board that is a modem is not a box |
| A **LoRa antenna** for your band | 868 MHz for Europe (2 dBi or less), 915-925 MHz for Taiwan. **Fit it before the board has any power**, also for flashing. Powering the board without it can destroy the radio. The modem has no Wi-Fi, so it needs no 2.4 GHz antenna |
| A USB-C **data** cable | A charge-only cable shows no port. Keep it short. Use the computer's own USB port for flashing, not a hub |
| A computer to flash with | Windows 10 or 11, Linux (the Raspberry Pi itself will do) or macOS, with [Python 3](https://www.python.org/downloads/) (macOS's own `python3` will do) |
| The same **radio region** as the boxes | EU868 (the default) or AS923-TW. A modem and a box built for different regions never talk. Decide this before section 3 |

## 3. Get the modem image

Two ways, as for the boxes ([firmware guide, section 2](firmware.md#2-get-the-firmware-download-a-release-or-build-it)).

### 3.1 Download a release (the easy way)

1. Open [the Releases page](https://github.com/vakaobr/atalaia-project/releases) and take the newest release. Each one is marked **pre-release**: pre-alpha, not field-tested.
2. Download two files: **`atalaia-modem-<version>-usb.zip`** and **`SHA256SUMS`**. (`atalaia-modem-<version>-merged.bin` is the same image as one file, for a browser flasher: [firmware guide](firmware.md#21-download-a-release-the-easy-way).) The modem has no over-the-air update: it is always flashed over USB.
3. Check the download. On Linux, in the folder of the files (files you did not download are reported missing: ignore them):

   ```
   sha256sum -c --ignore-missing SHA256SUMS
   ```

   On macOS: `shasum -a 256 -c SHA256SUMS`. On Windows `cmd`: `certutil -hashfile atalaia-modem-0.6.1-usb.zip SHA256`, then compare the line with the one in `SHA256SUMS`.
4. Unzip it into a folder of its own. It holds the bootloader, the partition table, the program, a `flash_args` file and a `README.txt` that repeats the commands below.

   Windows `cmd`: `mkdir atalaia-modem` then `tar -xf atalaia-modem-0.6.1-usb.zip -C atalaia-modem` (or right-click, *Extract All*). Linux and macOS: `unzip atalaia-modem-0.6.1-usb.zip -d atalaia-modem`.

**What the released modem is:** the Heltec **V4.3**, the **EU868** region (868 MHz), listen before talk on, an antenna of 2 dBi assumed, the project's keys built in, the screen in English until the controller tells it the boxes' language. **For a V4.2, for Taiwan (AS923), for an antenna of more than 2 dBi or for a screen that starts in another language, build it yourself.**

### 3.2 Build it yourself

You need [Docker](https://docs.docker.com/get-docker/) (running), Python 3 and git. In a terminal:

```
git clone https://github.com/vakaobr/atalaia-project
cd atalaia-project
python tools/docker_fw.py modem
```

On macOS and Linux use `python3` if `python` is not found. The first build takes several minutes. It ends with `Modem firmware: firmware/esp32/build-modem/atalaia_esp32.bin`. The folder to flash from is **`firmware/esp32/build-modem`**: it holds `flash_args` and the files it names.

Options, all for the modem's build folder only (the full list is in [firmware guide, section 4](firmware.md#4-the-options-a-builder-sets)):

| What | How |
| --- | --- |
| Taiwan | `python tools/docker_fw.py modem --region=as923-tw` (and an antenna for 915-925 MHz) |
| An antenna of more than 2 dBi | `--antenna-dbi=N`, its rated gain. Never lower it below the real value: it keeps the radiated power legal |
| Board revision V4.2 | Build once, then in `firmware/esp32/build-modem/sdkconfig` set `CONFIG_ATALAIA_BOARD_HELTEC_V4_2=y` and `# CONFIG_ATALAIA_BOARD_HELTEC_V4_3 is not set`, and build again. Changing `--region` or the antenna later can make that file again from the defaults: check the lines |
| The screen's language before the controller talks | `CONFIG_ATALAIA_MODEM_LANG="pt"` (or `de`, `zh-tw`) in the same file, then build again. The controller sets the language every time it connects, so this only matters for the first seconds |

Give a modem and its boxes the same options. **Windows and Docker:** Docker cannot see USB ports. Build in Docker, then flash from Windows itself; if you build inside WSL, copy `build-modem` to a Windows folder first.

## 4. Flash the board

Fit the antenna first. Plug the board into the computer with the data cable. If the controller is running with this board plugged in, **stop it first** (`sudo systemctl stop atalaia-controller`): it holds the port.

### 4.1 Install esptool once

esptool is Espressif's free flashing tool. Use this version (4.8.1), in a Python environment of its own.

Windows (`cmd`):

```
python -m venv %USERPROFILE%\atalaia-flash
%USERPROFILE%\atalaia-flash\Scripts\python -m pip install esptool==4.8.1
```

Linux and macOS:

```
python3 -m venv ~/atalaia-flash
~/atalaia-flash/bin/python -m pip install esptool==4.8.1
```

On a Raspberry Pi OS or Ubuntu that says `ensurepip is not available`, first run `sudo apt install python3-venv`. The macOS test used esptool 4.12.0 with pyserial 3.5 (`~/atalaia-flash/bin/pip install esptool pyserial`), and it wrote the images as well.

### 4.2 Find the board's port

| System | Where the port appears | How to see it |
| --- | --- | --- |
| Windows 10 and 11 | A new **COM** port, USB ID 303A:1001. No driver is needed | Device Manager, *Ports (COM & LPT)*; or `%USERPROFILE%\atalaia-flash\Scripts\python -m serial.tools.list_ports -v` |
| Linux | `/dev/ttyACM0`, or `ttyACM1`... | `ls /dev/ttyACM*`, or `dmesg \| tail` right after plugging |
| macOS | `/dev/cu.usbmodem...` (for example `/dev/cu.usbmodem31101`). No driver is needed. Use the `cu.` name, not the `tty.` one | `ls /dev/cu.usbmodem*` |

If you are unsure which port is the board, unplug it, list the ports, plug it back and list again: the new one is the board. On macOS, with several boards plugged in, `ioreg -p IOUSB -l -w0 | grep -E '"USB Serial Number" = "[0-9A-F]{2}:'` shows each board's MAC (its USB serial number), and `~/atalaia-flash/bin/python -m esptool --chip esp32s3 -p /dev/cu.usbmodem31101 read_mac` prints the MAC of the board on that port (it restarts the board).

**Linux only: the `dialout` group.** Your user needs it to open the port. Check with `groups`; if `dialout` is missing, run `sudo usermod -aG dialout $USER`, then **log out and in again**. Without it esptool says `Permission denied`.

If no port appears: another cable, the computer's own USB port, no hub. Then enter download mode by hand: hold **PRG**, press and release **RST**, release **PRG**. The port may vanish and come back when the board restarts. That is normal.

### 4.3 Write the image

Go into the folder with the `flash_args` file: the unzipped folder (3.1) or `firmware/esp32/build-modem` (3.2). Then run the commands for your system, with **your own port** in place of the one shown. Keep the quotes round `@flash_args`.

**Erase first or not?** A **new board**, or one that was a box or anything else before: erase it first. That also clears the box settings, keys and adoption it may hold, which a modem must not carry. Re-flashing a modem that already runs the modem image: no need.

Windows (`cmd`, port `COM5` as an example):

```
cd atalaia-modem
%USERPROFILE%\atalaia-flash\Scripts\python -m esptool --chip esp32s3 -p COM5 erase_flash
%USERPROFILE%\atalaia-flash\Scripts\python -m esptool --chip esp32s3 -p COM5 -b 921600 write_flash "@flash_args"
```

In PowerShell write the Python as `& "$env:USERPROFILE\atalaia-flash\Scripts\python"`.

Linux (a Raspberry Pi too):

```
cd atalaia-modem
~/atalaia-flash/bin/python -m esptool --chip esp32s3 -p /dev/ttyACM0 erase_flash
~/atalaia-flash/bin/python -m esptool --chip esp32s3 -p /dev/ttyACM0 -b 921600 write_flash "@flash_args"
```

macOS (the write was done this way on a Mac, for the modem and for boxes):

```
cd atalaia-modem
~/atalaia-flash/bin/python -m esptool --chip esp32s3 -p /dev/cu.usbmodem31101 erase_flash
~/atalaia-flash/bin/python -m esptool --chip esp32s3 -p /dev/cu.usbmodem31101 -b 921600 write_flash "@flash_args"
```

For a build, replace `cd atalaia-modem` with `cd firmware/esp32/build-modem` (from the repository's folder). Skip the `erase_flash` line when you do not erase.

The write ends with `Hash of data verified.` for each file and `Hard resetting via RTS pin...`. If the connection fails: download mode by hand (above), or `-b 460800` or `-b 115200`.

**Coming from v0.4.0 or earlier?** A modem flashed with v0.4.0 or earlier has the old partition table (2 MB program slots). From v0.5.0 the slots are 4 MB. The old table only makes the new modem log `WRONG PARTITION TABLE` and it keeps working, but flash it once over USB as above, **without** `erase_flash`, so it has the new layout. The modem shows nothing about this on its screen, and its log is not on USB: see the table in section 10.

**Do not open the modem's USB port with a serial monitor** (miniterm, PuTTY, the Arduino monitor) to look at a log, as the box guide does for a box. On the modem that port carries the controller's data frames, not text. The modem's log is on UART0 (GPIO 43 and 44) and needs a 3.3 V USB-serial adapter. You rarely need it: the screen tells you what matters.

## 5. Check the board's screen

The modem restarts by itself after the write. If the screen stays dark, unplug the board and plug it in again. The small screen then shows:

1. For about 2 seconds, the splash: the Atalaia tower, **ATALAIA**, **MODEM MODE** and the version.
2. The status screen, under a bar with **MODEM MODE**:

```
LINK       waiting     the controller: OK, DOWN, or waiting
IDLE     no game       the game's number (GAME 4660), or IDLE no game
CH   869.525 MHz       the channel the radio is on (921.500 MHz in Taiwan)
TX 0         fail 0    packets sent, and failures
RX 0         auth 0    packets passed to the controller, and failures to decrypt
DUTY  ...    left      the airtime left
```

With no controller yet, **`LINK waiting`** is right. That is a flashed, healthy modem. Anything else:

- **RADIO FAULT** in place of the last lines: the radio chip did not start. Section 10.
- The tower and the words of a Field Box (a setup or a READY screen): you flashed the box image. Flash again from the `modem` files.
- Nothing, at all: section 10.

Now unplug the board and carry it to the controller, or leave it plugged in if you flashed on the Pi.

## 6. Plug it into the controller and find its port

Plug the modem into one of the Raspberry Pi's USB ports, with the antenna on and a short data cable. Prefer a port of the Pi itself to a hub. On the Pi:

```
ls /dev/ttyACM*
```

One name (usually `/dev/ttyACM0`) is the modem. If a Field Box is also plugged in (to adopt it by USB), there are two, and the number depends on which came first. For a name that does not change, use the `by-id` one:

```
ls -l /dev/serial/by-id/
```

It lists names such as `usb-Espressif_USB_JTAG_serial_debug_unit_<the board's MAC>-if00`, each pointing to a `ttyACM`. Unplug the modem and run it again to see which one goes. The by-id name works as the `[modem] port` and the controller compares it with the adoption's USB ports by the real device behind it, so adoption never touches the modem. The by-id name is the project's advice from reading the code; it has not been run on a Pi.

## 7. Put the port in the controller's settings and restart it

If the controller is not installed yet, do [controller setup guide, section 4](controller-setup.md#4-install-the-controller) first and come back: step 4 there is this one.

1. Edit the settings file: `sudo nano /etc/atalaia/controller.toml`.
2. In the `[modem]` section, set the port you found:

   ```
   [modem]
   port = "/dev/ttyACM0"
   baudrate = 921600
   ping_interval_s = 5.0
   ```

   Leave `baudrate` and `ping_interval_s` as they are. A `port` that is empty, or no `[modem]` section, means **no radio**: the controller says `no modem port configured: the controller runs without a radio` in its log. The same setting can be given as the environment variable `ATALAIA_MODEM_PORT`.
3. In `[radio]`, `region` must be the region the modem and the boxes were built for (`eu868` or `as923-tw`).
4. Save, then restart the controller. It reads the file only when it starts:

   ```
   sudo systemctl restart atalaia-controller
   sudo systemctl status atalaia-controller
   ```

   It should say `active (running)`. The `systemd` file lets the service open `/dev/ttyACM*` and `/dev/ttyUSB*`, and the `atalaia` user is in `dialout` (controller setup guide, section 4, step 3), so no more setup is needed for the port.

On another computer, `port` is what the system calls it: `COM5` on Windows, `/dev/cu.usbmodem31101` on macOS (a controller run natively on macOS is not tried).

**Controller in Docker on Windows or macOS (advanced).** Docker Desktop and WSL cannot pass a USB serial port into a container. The supported way is to run the controller natively. If you must use Docker, bridge the port to TCP on the host (a small program that serves the COM port on a local TCP port: the repository's `tools/serial_bridge.py`, plus a relay if the container cannot reach the host's loopback) and give the container a pyserial URL as the port: `port = "socket://host.docker.internal:7601"` (the number is only an example). The controller opens its port with pyserial's `serial_for_url`, so `socket://` URLs work, and this is how the bench ran. The bridge runs outside the controller (start it before the controller, and keep it running), and the modem's screen and the checks in section 8 apply as before.

On macOS (Colima or Docker Desktop alike) the bench did the same: the repository's `tools/serial_bridge.py` run natively on the Mac with `~/atalaia-flash/bin/python` (`python tools/serial_bridge.py /dev/cu.usbmodem... 7600 --baud 921600`), serving `/dev/cu.usbmodem...` on TCP port 7600, the setting `port = "socket://host.docker.internal:7600"`, and the container started with `--add-host host.docker.internal:host-gateway`. The controller logged `modem link up` (2026-11-02). **One program per serial port, ever**: one bridge, and no esptool or serial monitor on the port while it runs. Opening the port on macOS can restart the board, so the modem's splash may show again: that is harmless.

## 8. Check that the controller and the modem talk

**On the modem's screen**, within about 5 seconds of the controller starting: `LINK waiting` becomes **`LINK OK`**. If your boxes' language (the **box language** setting in the console) is not English, the screen changes to it as well: `LINK aguarda`, `LINK wartet`, or `等待`/`正常`/`離線` in the bar.

**In the controller's log:**

```
sudo journalctl -u atalaia-controller -n 50 | grep -i modem
```

You should see `atalaia.modem INFO modem link up` and, just before it, `atalaia.modem INFO modem: {...}`: the modem's identity, with its `fw_version` and its `region`. A failure shows as `cannot open the modem at /dev/ttyACM0: ...`, `modem missed ping 1 of 3` or `modem link lost; reconnecting`.

The identity of a modem built from this release on also says `"games": true`: the modem then tells the controller when it hears a box still in a game that is over (one that was switched off when its game ended), and the controller frees it by telling it again that the game is over. An older modem logs `the radio modem's firmware cannot report boxes still in an ended game` once; flash this image to get the automatic recovery, or take such a box out at the box (its admin menu's **Leave the game**, or `@leave` over USB: [Field Box manual](field-box.md#d-take-a-box-out-of-its-game)).

**In the GM console** ([Game master manual, section 3](game-master.md#3-open-the-gm-console)): the pill at the top right says **Radio: up**. `connecting` and `down` are not yet working, and **no modem** means the setting is empty. If the modem drops, an alert says **Radio down: the USB modem does not answer.**, and **Radio back.** when it returns. The **Controller** tab lists **Radio**, **Modem** (the modem's firmware and version) and **Modem reconnects**: a count that keeps rising means a bad cable, port or power.

**Two more checks, in the console's Settings:**

- **Region.** Under **Radio region**, no red message about the modem. If it says *The USB modem is built for …, but the field is in …*, the modem and the field disagree on the region and no game can start (section 10).
- **Scan.** Under **Field radio channel**, tap **Scan**. The modem listens to each channel for about a minute and lists them quietest first. It transmits nothing, and it only works with a radio that started: the console says *The USB modem has no radio chip* if it did not.

## 9. A box joins a game through the modem

This is the real test: a box and the modem hear each other. You need an adopted box (it shows **READY** after you switch it on) in the same region, with its antenna fitted, within a few metres of the modem.

1. If the box is new, adopt it: **Adopt** tab, by USB cable, a card, or **Pair by code (radio)** ([Game master manual, Adopt the boxes](game-master.md#adopt-the-boxes)). Pairing by code uses the modem's radio.
2. Make a game (**Game** tab, **Create game**). The **Boxes for this game** dialog opens.
3. Switch the box on. Within about 20 seconds it appears in the list. Tap **Look for boxes** to ask now. A box that does not appear does not hear or is not heard: section 10.
4. Tick the box, pick its **Role**, tap **Invite**. **Progress** goes **sending**, **invited**, **accepted, joining**, **joined**.
5. On the modem's screen, **GAME** now shows the game's number and **TX** and **RX** count up. On the box's screen it says it is in the game.

If **joined** appears, the radio path works in both directions. End the game from the **Game** tab when you are done (nothing starts until you start it). The rest is the [Game master manual](game-master.md#6-assign-boxes).

## 10. Troubleshooting

| What you see | Likely cause and what to do |
| --- | --- |
| No port appears when the board is plugged in | **Charge-only cable**: try another, a data one. Then the computer's own USB port, not a hub. Then download mode by hand: hold **PRG**, tap **RST**, release **PRG**. Windows: the port is under *Ports (COM & LPT)* with ID 303A:1001 |
| esptool: `Permission denied` (Linux) | Your user is not in `dialout`: `sudo usermod -aG dialout $USER`, then log out and in |
| esptool: `could not open port`, `Access is denied` (Windows), `Resource busy` | **Another program holds the port**: a serial monitor, a second esptool, the Arduino IDE, or the controller. Close it, stop the controller (`sudo systemctl stop atalaia-controller`), unplug and plug the board, try again |
| esptool: `Failed to connect`, `No serial data received` | Wrong port (check section 4.2), no data cable, or the chip is not in download mode: do it by hand. Try `-b 460800`, then `-b 115200` |
| On Ubuntu desktop the port is busy for some seconds after plugging | ModemManager probes new serial ports. Wait, or, if you use no mobile broadband, `sudo systemctl disable --now ModemManager`. Not seen by the project |
| The screen is dark after flashing | Unplug and plug again. Check the cable. If the screen is upside down, build with `CONFIG_ATALAIA_OLED_FLIP=y`. A dark screen does not stop the modem: the controller's log and the console are the check |
| The screen shows a box's screens | You flashed the Field Box image. Flash `modem` again |
| **`LINK waiting`** stays | The controller does not talk to this board: it is not running (`systemctl status atalaia-controller`), `[modem] port` is empty or names another port, the controller was not restarted after the edit, or another program holds the port. Check the log (section 8) and `ls /dev/ttyACM*` |
| Log: `cannot open the modem at ...: No such file or directory` | The port name is wrong, or the board is not plugged in. Section 6; the name can change if you plug the board into another USB port or reboot with two boards (use the `by-id` name) |
| Log: `cannot open the modem ...: Permission denied` | The `atalaia` user is not in `dialout` (controller setup guide, section 4, step 3): `sudo usermod -aG dialout atalaia`, restart the service |
| `LINK` flips between OK and DOWN, the log is full of `modem missed ping`, with no open error | **Another program has the same port open.** On Linux a second opener is not refused: the two share the bytes. `sudo fuser -v /dev/ttyACM0` shows it. Close it |
| **`LINK DOWN`** or **Radio down: the USB modem does not answer.**, **Modem reconnects** keeps rising | The modem answered, then stopped for 12 seconds: the controller stopped or lost the port. Check `systemctl status`, the cable (short, data, firmly in), the USB port's power (a weak port, a cheap hub or a low power bank), and whether the board restarted (its splash shows again). It reconnects by itself |
| **`RADIO FAULT`** | The radio chip did not start. The screen gives the reason (for example `SX1262 not found (BUSY stuck)`): write it down. Check the revision you built for (V4.2 and V4.3 differ: section 3.2), then the cable, then try another board. The modem still talks to the controller, so the console says **Radio: up** and the **Scan** says there is no radio chip |
| Log: `WRONG PARTITION TABLE` | The modem has the old table (v0.4.0 or earlier). It works, and says so only on UART0, so you may not see it. Flash it once over USB without `erase_flash` (section 4.3). The `README.txt` in the zip says the same |
| Console, Settings: **The USB modem is built for …, but the field is in …** | The modem's region and the field's region differ. No game can start. Build the modem for the field's region (`--region=`) and flash again, or put the field back in the modem's region |
| The console header says **Radio: no modem** | `[modem] port` is empty, or the section is missing: section 7 |
| The modem is **OK** but no box appears under **Look for boxes** | The box and the modem are not on the same region or channel; the box is not adopted; the box is in another game (**refused: in another game**: power-cycle it); an antenna is missing or the box is too far. [Game master manual, Troubleshooting](game-master.md#troubleshooting) |
| `Radio: up` but **fail** (the TX line) keeps rising | Transmissions fail. Look at the **DUTY** line: at `0.0s` the airtime budget is spent, so wait. If not, check the antenna and the radio fault state |
| **RX auth** keeps rising | Packets of the game that do not decrypt: a box with an old key, or another game on the same id nearby |
| It worked, then after a reboot of the Pi it does not | The port name changed. Use the `by-id` name (section 6). Make sure the service is enabled: `sudo systemctl enable atalaia-controller` |

Not in the table? Ask in [Discussions](https://github.com/vakaobr/atalaia-project/discussions) or open an issue, with the controller's log lines about the modem, what the screen says and your system. The details of the modem's firmware and its screen are in the [firmware README](../../../firmware/esp32/README.md#usb-radio-modem-variant); the frames on the cable are in [protocol/usb-modem.md](../../../protocol/usb-modem.md).
