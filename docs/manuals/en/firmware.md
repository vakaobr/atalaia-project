<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Firmware guide for builders

For the person who builds a box or a prop and has to put the software on it. You do not need to write code. You need a computer, a USB-C data cable and the board. The steps are the same for every kind of board in the project: the Field Box, the Satellite, the I/O pod and the controller's modem board.

> **Not field-ready yet.** The firmware releases on GitHub are marked pre-release for that reason. Atalaia is pre-alpha. Real Heltec V4.3 boards have been flashed and used on a bench with the field controller: boot, radio, buttons, the board's own OLED, adoption by USB cable and by code, and an update over the air. Nothing else in this guide has run on a real board. Steps that depend on hardware that was not tried say **Not yet tested on a real board**.

The hardware is in the build manuals: [Field Box](../../../hardware/field-box/BUILD.md), [Satellite](../../../hardware/satellite/BUILD.md), [I/O pod](../../../hardware/io-pod/BUILD.md). The controller is in the [controller setup guide](controller-setup.md).

## Contents

1. [What you flash](#1-what-you-flash)
2. [Get the firmware: download a release, or build it](#2-get-the-firmware-download-a-release-or-build-it)
3. [Flash it](#3-flash-it)
4. [The options a builder sets](#4-the-options-a-builder-sets)
5. [First boot and setup](#5-first-boot-and-setup)
6. [Adoption](#6-adoption)
7. [Updates over the air, and what else uses the field Wi-Fi](#7-updates-over-the-air-and-what-else-uses-the-field-wi-fi)
8. [A box that does not boot](#8-a-box-that-does-not-boot)
9. [The modem board](#9-the-modem-board)
10. [The I/O pod variants](#10-the-io-pod-variants)

## 1. What you flash

There is one firmware project and four images you can build from it.

| Image | Build command | Output folder | For | Use in a game |
| --- | --- | --- | --- | --- |
| Field Box | `python tools/docker_fw.py build` | `firmware/esp32/build/` | A Field Box, and also a Satellite (same image, fewer parts) | Yes |
| USB radio modem | `python tools/docker_fw.py modem` | `firmware/esp32/build-modem/` | The second board, plugged into the controller | Yes |
| I/O pod | `python tools/docker_fw.py pod` | `firmware/esp32/build-pod/` | A board that lends its buttons and radio to an Android phone | Yes |
| Bench | `python tools/docker_fw.py bench` | `firmware/esp32/build-bench/` | A bare board on your desk: keys typed on the USB console, no setup page, admin PIN 1234 | **Never** |

All of them are made for the **Heltec WiFi LoRa 32 V4** (revision V4.3 by default, V4.2 with one change, see [section 4](#4-the-options-a-builder-sets)). Do not flash a build for one kind of board onto another. A box will refuse an update made for another variant or board anyway.

## 2. Get the firmware: download a release, or build it

Two ways. Download a release if you only want to put the project's firmware on a board. Build it yourself if you changed the code, or want to choose build options (the radio region, the board revision, your own keys).

### 2.1 Download a release (the easy way)

The project publishes firmware on GitHub: [the Releases page](https://github.com/vakaobr/atalaia-project/releases). The first one is **v0.4.0**, marked **pre-release**: pre-alpha and **not field-tested**. Read its notes first.

Pick the files for your board:

| You are building | Download | Notes |
| --- | --- | --- |
| A Field Box, or a Satellite (same image) | `atalaia-field-box-<version>-usb.zip` (esptool over USB) or `atalaia-field-box-<version>-merged.bin` (browser flasher) | The plain `atalaia-field-box-<version>.bin` and its `.bin.release.json` are for updates over the air ([section 7](#7-updates-over-the-air-and-what-else-uses-the-field-wi-fi)); you do not need them to flash |
| The controller's USB radio modem | `atalaia-modem-<version>-usb.zip` or `-merged.bin` | The second board, plugged into the controller |
| An I/O pod | `atalaia-io-pod-<version>-usb.zip` or `-merged.bin` | |
| Never for a game | (the bench image is not released) | Build it yourself if you need it |

All of them are for the Heltec WiFi LoRa 32 V4.3, European radio region (EU868), listen before talk on, with the project's keys built in. For V4.2, for Taiwan (AS923) or for your own keys, build it yourself ([2.2](#22-build-it-yourself)).

**Check what you downloaded.** Download `SHA256SUMS` too, and compare. On Linux and macOS, in the folder of the files (`shasum -a 256 -c SHA256SUMS` on macOS; files you did not download are reported missing, ignore them):

```
sha256sum -c --ignore-missing SHA256SUMS
```

On Windows `cmd`: `certutil -hashfile atalaia-field-box-0.4.0-usb.zip SHA256` and compare the line with the one in `SHA256SUMS`. The sums prove the file is the one the release page lists. The signature proves who made a Field Box image: the `.release.json` is signed with the project's CI release key, which every box trusts by default (`firmware/esp32/docs/RELEASE_SIGNING.md`). A box and a controller check it for you before they install an update.

**Flash the zip.** Unzip it. In that folder follow [section 3](#3-flash-it) from 3.1 on: the commands are the same, and the `README.txt` inside the zip repeats them. The folder has the `flash_args` file the command uses, so skip the build and the `cd firmware/esp32/build` step.

**Flash the merged file from a browser** (Chrome or Edge, no Python): open Espressif's web flasher, [https://espressif.github.io/esptool-js/](https://espressif.github.io/esptool-js/), connect the board (download mode if it does not appear, [3.2](#32-find-the-boards-port)), set the flash address to `0x0`, choose the `-merged.bin` file and program. Not tried by the project with a real board yet; the file is the same one the esptool command produces from the zip.

The version on the release is the version the box shows at boot (`0.4.0`).

### 2.2 Build it yourself

You need:

- [Docker](https://docs.docker.com/get-docker/) (Docker Desktop on Windows and macOS). Start it.
- [Python 3](https://www.python.org/downloads/) and [git](https://git-scm.com/downloads).

Then, in a terminal (`cmd`, PowerShell, Terminal, any shell):

```
git clone https://github.com/vakaobr/atalaia-project
cd atalaia-project
python tools/docker_fw.py build
```

On macOS and Linux, use `python3` if `python` is not found. The first build downloads the build tools and takes several minutes (about ten the first time). It ends with a line that names the file `firmware/esp32/build/atalaia_esp32.bin`. The other files you need are in the same folder. You do not need to read them.

A build from a checkout prints a version such as `0.4.0+12.g1a2b3c4` (or `0.5.0-dev.12+g1a2b3c4` between releases): the release's number, the number of changes since, and the code's identifier. It is also on the board's small screen at boot. Keep a note of it with the box. To get exactly a release's firmware, check out its tag (`git checkout v0.4.0`) and build there: a clean checkout of a tag says plain `0.4.0`.

**Keys.** A build you make trusts the project's two release keys and two mode keys by default, the same as the released files, so a controller you run accepts the project's signed releases. Your own builds are not signed by the project: sign them with your own key and give the boxes its public half (`--release-keys=`, [section 7](#7-updates-over-the-air-and-what-else-uses-the-field-wi-fi)).

## 3. Flash it

Flashing writes the image to the board. You do it with **esptool**, a free tool from Espressif. The board's USB-C port is the chip's own USB port, so there is no USB-serial chip to install a driver for.

**Windows and Docker.** Docker on Windows cannot see USB ports. Build in Docker, then flash from Windows itself. If you build inside WSL, copy the build folder to a Windows folder and flash from there.

### 3.1 Install esptool once

Use a separate Python environment and this version (4.8.1, the one the build uses).

Windows (`cmd`):

```
python -m venv %USERPROFILE%\atalaia-flash
%USERPROFILE%\atalaia-flash\Scripts\python -m pip install esptool==4.8.1
```

macOS and Linux:

```
python3 -m venv ~/atalaia-flash
~/atalaia-flash/bin/python -m pip install esptool==4.8.1
```

Below, `PY` means that Python: `%USERPROFILE%\atalaia-flash\Scripts\python` on Windows, `~/atalaia-flash/bin/python` on macOS and Linux. In PowerShell write it as `& "$env:USERPROFILE\atalaia-flash\Scripts\python"`.

### 3.2 Find the board's port

Fit the antennas first. **Never power the board without the LoRa antenna.** Plug the board in with a USB-C **data** cable. A charge-only cable shows nothing.

| System | Where the port appears | Notes |
| --- | --- | --- |
| Windows 10 and 11 | A new `COM` port (Device Manager, *Ports (COM & LPT)*; USB ID 303A:1001) | No driver is needed. On the first board tested, the port appeared only on the PC's own USB-C port, not through a hub |
| Linux | `/dev/ttyACM0` (or `ttyACM1`...) | Add yourself to the `dialout` group once (`sudo usermod -aG dialout $USER`), then log in again |
| macOS | `/dev/cu.usbmodem...` (list them with `ls /dev/cu.usbmodem*`) | Not tested by the project on macOS |

To list ports with the tool: `PY -m serial.tools.list_ports -v`.

If no port appears, hold the board's **PRG** button, press and release **RST**, then release PRG. That is download mode. The port may disappear and come back when the board restarts. That is normal.

### 3.3 Write the image

Go to the build folder and write all the files with one command. The examples use `COM5`. Use your own port, for example `/dev/ttyACM0`.

First flash of a new board only, erase it. This also erases the settings and any adoption:

```
PY -m esptool --chip esp32s3 -p COM5 erase_flash
```

Then write:

```
cd firmware/esp32/build
PY -m esptool --chip esp32s3 -p COM5 -b 921600 write_flash "@flash_args"
```

Keep the quotes: PowerShell reads a bare `@` differently. `flash_args` is a file the build made. It lists the files and where they go. If the connection fails, use download mode, or try `-b 460800` or `-b 115200`.

For the modem and the pod, go to `build-modem` or `build-pod` instead.

**USB flash required once, from v0.5.** A box flashed with v0.4.0 or earlier has the old partition table (2 MB program slots). From v0.5 the program slots are 4 MB, and an update over the air cannot change the partition table, so flash such a box over USB once, with the command above and **without** `erase_flash`: the settings, the keys and the adoption stay where they are (the table's first four partitions did not move). What is lost is the storage partition, which moved: the box formats it on the first start and fetches the game modes and the field's logo again at the next join. A box still on the old table refuses to run the new firmware: its screen says *Flash over USB* and the log says `WRONG PARTITION TABLE`. A box that was offered the new image over the air by an older firmware goes back to its old one by itself. After the one USB flash, updates over the air work as before. The USB radio modem and the I/O pod share the table: one already flashed with v0.4.0 or earlier only logs `WRONG PARTITION TABLE` and keeps working, but flash it over USB once as well (without `erase_flash`) so it has the new layout.

### 3.4 Restart and watch

Restart the board with this command. It is the reliable way. A serial program's own reset is not:

```
PY -m esptool --chip esp32s3 -p COM5 --after hard_reset chip_id
```

Open the log and press `Ctrl+]` to leave:

```
PY -m serial.tools.miniterm COM5 115200
```

You should see the firmware's version, the memory, and one line for each part found. A part that is not fitted gives a warning and the box goes on. The log may warn about GPIO 33 to 37: the project's bench notes call that cosmetic.

**Without Python, in Chrome or Edge.** Make one image file, then flash it at address `0x0` with Espressif's web page. In a bash shell:

```
docker run --rm -v "$PWD/firmware/esp32/build:/b" -w /b espressif/idf:v5.3.2 bash -c '. $IDF_PATH/export.sh > /dev/null && esptool.py --chip esp32s3 merge_bin -o atalaia-merged.bin @flash_args'
```

On Windows `cmd`, use the command in the [Field Box manual](../../../hardware/field-box/BUILD.md#11-first-flash). The merge step works; the web page was not tried.

## 4. The options a builder sets

Most options are build options. Give them to `docker_fw.py`:

| What | How | Default |
| --- | --- | --- |
| Radio region | `--region=eu868` or `--region=as923-tw` (Taiwan, 920-925 MHz) | EU868 |
| Listen before talk | `--lbt=on` or `--lbt=off` | on |
| Mode keys | `--mode-keys=<key>[,<key>...]` (up to 4, hex or base64) | The project's two keys |
| Release keys | `--release-keys=<key>[,<key>...]` (up to 4) | None: every update is refused |
| Version | `--fw-version=0.4.1` | From the code |

Example for a Taiwanese field: `python tools/docker_fw.py build --region=as923-tw`. Build the modem and the pod with the same `--region`. A box refuses a game from another region. Use an antenna for the band: an 868 MHz antenna is wrong at 920 MHz.

**Mode keys.** A box fetches a game mode it lacks from the controller, as a signed package. It accepts only packages signed by a key built into its firmware. The default is the project's two registry keys (root `d9521a79030ce544`, CI `7275108d2e3fe583`), listed in [docs/community/keys.md](../../community/keys.md). Do not change this unless you run your own mode registry. `--mode-keys` replaces the list, so add the project's keys again if you still want them.

**Settings you edit in a file.** A few settings have no command-line option. After one build, open `firmware/esp32/build/sdkconfig` (for the modem `build-modem/sdkconfig`, for the pod `build-pod/sdkconfig`), change the line, save, and build again.

| What | Line |
| --- | --- |
| Board revision V4.2 (chip GC1109 next to the LoRa connector) | `CONFIG_ATALAIA_BOARD_HELTEC_V4_2=y` and `# CONFIG_ATALAIA_BOARD_HELTEC_V4_3 is not set` |
| Antenna of more than 2 dBi | `CONFIG_ATALAIA_RADIO_ANTENNA_GAIN_DBI=` its gain, rounded up |
| Display chip ST7789 | `CONFIG_ATALAIA_DISP_ST7789=y` and `# CONFIG_ATALAIA_DISP_ILI9341 is not set` |
| 12 or 16 LEDs in the ring | `CONFIG_ATALAIA_LED_COUNT=12` (or 16) |
| Board's small screen upside down | `CONFIG_ATALAIA_OLED_FLIP=y` |
| No iBeacon on the Field Box (it is on by default) | `# CONFIG_ATALAIA_BOX_BEACON is not set` |
| The beacon's interval, power | `CONFIG_ATALAIA_BOX_BEACON_INTERVAL_MS=500` (100 to 10000), `CONFIG_ATALAIA_BOX_BEACON_TX_DBM=0` |

Never lower `CONFIG_ATALAIA_RADIO_FEM_GAIN_DB` or the antenna gain below the real values. That would break the legal power limit.

If you change `--region`, `--lbt`, a key option, or update the repository, the build may make the settings file again from the defaults and your edits are lost. Do the edit again. Keep a note of your edits.

**Settings you do not set at build time.**

- **The admin PIN** has no default. You choose it on the setup page ([section 5](#5-first-boot-and-setup)). Easy PINs such as 1234 are refused.
- **The field Wi-Fi** name and password are set on the setup page too.
- **The field join key** is given to the box when it is adopted ([section 6](#6-adoption)).
- **The box's Bluetooth beacon.** A Field Box joined to a game advertises an iBeacon so that a phone that hears it is placed where the box is (the beacon's UUID comes from the join key, its major is 45253 and its minor is the box's node id). Nothing to set on the box: the GM turns it off for the whole field at the console (**Field**, **Indoor beacons**, **Field Boxes as beacons**), and the next game's join tells the boxes. It uses the Bluetooth stack in the image (about 160 KB more flash and 25 KB more RAM than a build without it) and is off between games. The Wokwi variant and the modem have no beacon.

## 5. First boot and setup

A new Field Box or Satellite does this on its first start. The 2.4 GHz antenna must be fitted for the setup page.

1. The board's small screen shows the tower and the version for 2 seconds. The big screen (if fitted) and the small one then show **FIRST-TIME SETUP** and a Wi-Fi name such as `atalaia-1A2B`.
2. On your phone, join that Wi-Fi. **It has no password**, so do the setup away from the players.
3. The setup page opens by itself on most phones. If it does not, open `http://192.168.4.1` in the browser. The page is in the language of the box, else of the phone: English, Portuguese, German or Traditional Chinese.
4. Fill in the page:
   - **Node Name**: a name for the box.
   - **Radio Region**: it must be the region the firmware was built for.
   - **Number of Teams**: 2, 3 or 4.
   - **Admin PIN**: 4 to 8 digits. Write it down. 1234, 0000, a sequence such as 9876 and a repeated pair such as 1212 are refused.
   - **Display Brightness** and **Audio Volume**.
   - **Field join key** (optional): the 64 digits from the organisers. You can add it later by adoption.
   - **Field Wi-Fi name** and **password** (optional, but needed for updates, the field's logo and fetched game modes: [section 7](#7-updates-over-the-air-and-what-else-uses-the-field-wi-fi)). The field Wi-Fi must be 2.4 GHz.
5. Tap **Save & Reboot**. The box restarts.

Then a box with no field shows **PAIR THIS BOX** and a 6-digit code ([section 6](#6-adoption)). A box that is already adopted shows **READY**, with the field's logo if it has one.

**Open the setup page again.** On a box that was set up, there are two ways. Neither works during a game.

- On the keypad: press a key, type the admin PIN and `#`, go to the entry **Wi-Fi setup** (after the games), press `#`, then `#` again to confirm.
- On the USB console (a serial monitor on the box's port, 115200): type `@setup` and the admin PIN, then Enter.

The box keeps its adoption and its field key. It replaces what the page asks for. The bench build has no setup page.

**Forgotten PIN.** After five wrong PINs the box makes you wait 1, 2, 4... up to 60 minutes. The wait survives a restart. If you really lost the PIN, erase the settings ([section 8](#8-a-box-that-does-not-boot)).

Not yet tested on a real board: the setup page and the screens above. The page was tested on a computer and in the emulator.

## 6. Adoption

A box plays only in the field that **adopted** it. Adopting gives it the field's join key, once. The organisers do it from the controller's console, in the **Adopt** tab. There are three ways. Details for the organisers are in the [Game master manual](game-master.md) and the [Field Box operator manual](field-box.md).

- **By code, over the radio** (no cable, no card). A box with no field shows **PAIR THIS BOX** and a 6-digit code, on its screen and on its small screen. In the console, **Pair by code (radio)**, look for boxes on the radio, pick the box by name and type the code. The box then shows **ADOPTED** and the field's name. A wrong code gives a new code. Three wrong codes make the box wait a minute. Ten stop pairing until it restarts. Done on two real boards on a bench. Not yet tested on a field.
- **By USB cable.** Plug the box into the computer that runs the controller. In the console, look for boxes and press **Adopt**. The box's USB port must be reachable by the controller. Done on a real board on a bench.
- **By NFC field card.** Tap the field card on the box's NFC reader. The card is the field's master secret: lock it away. Not yet tested on a real board (no NFC reader has been fitted on a real board).

A box of another field asks for its **admin PIN**. **Change field** moves a box on purpose: on the keypad press a key, type the PIN and `#`, pick **Change field** (the entry after the games and **Wi-Fi setup**), confirm. The box shows a pairing code and keeps its old field until the new field has paired it. A Satellite has no keypad: use the USB cable.

## 7. Updates over the air, and what else uses the field Wi-Fi

Three things use the field's Wi-Fi, and only between games: **firmware updates**, **game modes the box does not have** (fetched from the controller as signed packages) and **the field's logo** (one small picture, fetched once for each joined game). For all three the box needs the **field Wi-Fi name and password** from the setup page. You can also set them on the USB console: `@wifi <name> <password>`. The controller must be running with HTTPS on.

**The rules for firmware updates.** The box installs an update only if all of these are true:

- No game is being played.
- The update is signed by a **release key built into the box's own firmware** (`--release-keys`). By default that is the project's two release keys, so the Field Box files from a GitHub release can be installed as updates; a box built with `--release-keys=` your own key trusts only that. The project's keys and what happens if one leaks are in [RELEASE_SIGNING.md](../../../firmware/esp32/docs/RELEASE_SIGNING.md).
- The version is higher than the one it runs.
- It is the same variant and board (a V4.2 image never goes on a V4.3).
- The battery is at 30 % or more, if the box has a gauge.

**The short path.**

**With the project's releases:** flash a box once over USB with a release, then upload a later release's `atalaia-field-box-<version>.bin` and its `.bin.release.json` in the console's **Boxes** tab. The controller's `[firmware] release_keys` already holds the project's keys by default. Press **Update to** (step 5). **With your own key:**

1. Make a key with `tools/firmware_release.py keygen`. Keep the private file safe and out of the repository.
2. Build the boxes with `--release-keys=<the public key>`. Flash them over USB, once. Updates cannot install a new bootloader.
3. Put the key's public half in the controller's `[firmware] release_keys` setting.
4. For an update, build a higher version (`--fw-version=0.4.1`), sign it with `tools/firmware_release.py sign`, and upload the image and its `.release.json` in the console's **Boxes** tab. Press **Update to**.
5. The box downloads it, checks it again, installs it and restarts. If the new image fails its self-test, the box goes back to the old one by itself.

Done once on a real board on a bench, with a throw-away key, sent by the controller over the radio, on a home Wi-Fi network (about 11 seconds). Not yet tested on a field. A box flashed with firmware from before updates over the air existed needs one USB flash first, and so does a box on the old partition table (v0.4.0 or earlier) before it takes v0.5 ([section 3.3](#33-write-the-image)).

## 8. A box that does not boot

Go down the list. Stop when the box works.

1. **The cable and the port.** Use a data cable, a PC's own USB-C port, no hub. Close any other program that holds the port (a serial monitor, esptool).
2. **Power.** A weak port or a low battery gives restarts and `brownout` in the log. Try another port, with the switch off.
3. **Download mode by hand.** Hold **PRG**, press and release **RST**, release PRG. Flash again ([section 3](#3-flash-it)).
4. **Wrong partition table.** A screen that says *Flash over USB* (log: `WRONG PARTITION TABLE`) means the box has the old table: flash it over USB once ([section 3.3](#33-write-the-image)).
5. **Wrong build.** Check you flashed `build`, not `build-bench`, `build-modem` or `build-pod`.
6. **Update that went wrong.** A new image that cannot confirm itself is replaced by the old one at the next restart. You need do nothing. If it keeps looping, flash over USB.
7. **Erase the settings** (name, PIN, adoption, Wi-Fi) and keep the program:

   ```
   PY -m esptool --chip esp32s3 -p COM5 erase_region 0x9000 0x6000
   ```

8. **Erase everything and flash again.** `erase_flash`, then write ([section 3.3](#33-write-the-image)). The box is then new: set it up and adopt it again.

If the radio does not work, check the board revision first ([section 4](#4-the-options-a-builder-sets)), then the antenna. The [Field Box manual](../../../hardware/field-box/BUILD.md#13-troubleshooting) has a table of faults for each part.

## 9. The modem board

The controller's radio is a second Heltec V4 plugged into its USB port. It runs the modem image.

1. Fit the **LoRa antenna**. The modem has no Wi-Fi, so it needs no 2.4 GHz antenna.
2. Build it for the same board revision and the same region as the boxes: `python tools/docker_fw.py modem` (with `--region=as923-tw` for Taiwan). For a V4.2, edit `firmware/esp32/build-modem/sdkconfig` as in [section 4](#4-the-options-a-builder-sets).
3. Flash from `firmware/esp32/build-modem` as in [section 3](#3-flash-it). If the board is already plugged into a running controller, stop the controller first: it holds the port.
4. Plug it into the controller. Its small screen shows the tower and **MODEM MODE**, then the status:
   - **LINK**: `waiting` (the controller has not talked to it yet: it is not running, or the modem is on another port), `OK`, or `DOWN` (it talked, then stopped for 12 seconds).
   - The game number, the channel, the packets sent and received with their failures, and the airtime left.
   - **RADIO FAULT** if the radio chip did not start.

   The screen is in the language of your boxes (English, Portuguese, German or Traditional Chinese). The controller tells the modem which one every time it connects: the **box language** setting in the GM console, or with `auto` the language of the console that created the game. Before the controller has talked to it, and on the first splash, the modem uses its build's language, `en` by default. To make it another one, set `CONFIG_ATALAIA_MODEM_LANG="pt"` (or `de`, `zh-tw`) in `firmware/esp32/build-modem/sdkconfig` and build again, as in [section 4](#4-the-options-a-builder-sets). In Portuguese the words are `aguarda`, `OK`, `PERDIDO` and `FALHA NO LORA` (the small font has no accents); in German `wartet`, `OK`, `GETRENNT` and `FUNKFEHLER`; in Chinese the link is in the top bar (`等待`, `正常`, `離線`) and a radio fault is `無線電錯誤`. An older modem image, built before this, stays in English.
5. Put its port into the controller's `[modem] port` setting. On Linux it is usually `/dev/ttyACM0`. The [controller setup guide](controller-setup.md) shows how.

The modem is the only image whose USB port carries data frames, so its log is on UART0, not on USB. A modem like this has run with the controller and real boxes on a bench (2026-10-21). Not yet tested on a Raspberry Pi.

## 10. The I/O pod variants

An I/O pod lends its buttons, keypad, ring, sound, NFC reader and radio to an Android phone. Its parts are in the [I/O pod build guide](../../../hardware/io-pod/BUILD.md).

- Build: `python tools/docker_fw.py pod` (`--region` as above). Flash from `firmware/esp32/build-pod`. Edit `build-pod/sdkconfig` for a V4.2.
- A pod has no setup page, no Wi-Fi and no admin PIN. It has the 2.4 GHz antenna for **Bluetooth** (`atalaia-pod-XXXX`), which is paired and encrypted.
- Its USB port carries the frames to the phone, so the log is on **GPIO 43** (UART0 transmit), read with a 3.3 V USB-serial adapter at 115200 baud. It is not on the USB port.
- Build options for the pod, in `build-pod/sdkconfig`: a colour for each button (`CONFIG_ATALAIA_POD_BTN1_TEAM="red"` and so on), the enclosure switch pin (`CONFIG_ATALAIA_POD_TAMPER_PIN`), Bluetooth on or off. Leave `CONFIG_ATALAIA_POD_BLE_ENCRYPTED` on.
- The buttons' colours, the ring's brightness, the volume and the enclosure switch can also be set **over the radio** from the GM console, with no cable ([I/O pod build guide, "Settings over the radio"](../../../hardware/io-pod/BUILD.md#settings-over-the-radio)); they are kept in the pod's flash. The LED count, the pins and the radio stay in `build-pod/sdkconfig`.
- It does not use the board's small screen.

Not yet tested on a real board: all of it. The pod firmware has run on a computer, against the app and the controller. The Satellite is not a variant: it is the Field Box image with fewer parts fitted ([Satellite build guide](../../../hardware/satellite/BUILD.md)). The target addon cannot be built yet ([its page](../../../hardware/target-addon/BUILD.md)).

Found a step that does not match what you see? Open an issue or tell us in [Discussions](https://github.com/vakaobr/atalaia-project/discussions).
