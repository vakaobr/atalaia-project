<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Firmware guide for builders

For the person who builds a box or a prop and has to put the software on it. You do not need to write code. You need a computer, a USB-C data cable and the board. The steps are the same for the project's ESP32 boards: the Field Box, the Satellite, the I/O pod and the controller's modem board. The two small RP2040 boards on the expansion port (the target and the output module) are flashed another, simpler way: [section 11](#11-the-expansion-modules-target-and-output-module).

> **Not field-ready yet.** The firmware releases on GitHub are marked pre-release for that reason. Atalaia is pre-alpha. Real Heltec V4.3 boards have been flashed and used on a bench with the field controller: boot, radio, buttons, the board's own OLED, adoption by USB cable and by code, and an update over the air. Nothing else in this guide has run on a real board. Steps that depend on hardware that was not tried say **Not yet tested on a real board**.

The hardware is in the build manuals: [Field Box](../../../hardware/field-box/BUILD.md), [Satellite](../../../hardware/satellite/BUILD.md), [I/O pod](../../../hardware/io-pod/BUILD.md), [expansion port](../../../hardware/expansion-port/BUILD.md), [target](../../../hardware/target-addon/BUILD.md), [output module](../../../hardware/output-module/BUILD.md). Using the boxes on a field (setup, outputs, taking a box out of its game, updates) is in the [Field Box operator manual](field-box.md). The controller is in the [controller setup guide](controller-setup.md), and its radio modem board in [Set up the radio modem](modem.md).

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
11. [The expansion modules: target and output module](#11-the-expansion-modules-target-and-output-module)

## 1. What you flash

There is one ESP32 firmware project and four images you can build from it, plus the firmware of the two expansion modules.

| Image | Build command | Output folder | For | Use in a game |
| --- | --- | --- | --- | --- |
| Field Box | `python tools/docker_fw.py build` | `firmware/esp32/build/` | A Field Box, and also a Satellite (same image, fewer parts) | Yes |
| USB radio modem | `python tools/docker_fw.py modem` | `firmware/esp32/build-modem/` | The second board, plugged into the controller | Yes |
| I/O pod | `python tools/docker_fw.py pod` | `firmware/esp32/build-pod/` | A board that lends its buttons and radio to an Android phone | Yes |
| Bench | `python tools/docker_fw.py bench` | `firmware/esp32/build-bench/` | A bare board on your desk: keys typed on the USB console, no setup page, admin PIN 1234 | **Never** |
| Target and output module (RP2040, UF2 files) | `python tools/docker_module.py build` | `firmware/target-module/build/`, `firmware/output-module/build/` | The boards on a box's or a pod's expansion port | Yes ([section 11](#11-the-expansion-modules-target-and-output-module)) |

The four ESP32 images are made for the **Heltec WiFi LoRa 32 V4** (revision V4.3 by default, V4.2 with one change, see [section 4](#4-the-options-a-builder-sets)). Do not flash a build for one kind of board onto another. A box will refuse an update made for another variant or board anyway.

## 2. Get the firmware: download a release, or build it

Two ways. Download a release if you only want to put the project's firmware on a board. Build it yourself if you changed the code, or want to choose build options (the radio region, the board revision, your own keys).

### 2.1 Download a release (the easy way)

The project publishes firmware on GitHub: [the Releases page](https://github.com/vakaobr/atalaia-project/releases). Take the newest one: **v0.11.0**, 2026-11-07 (before it v0.10.0, 2026-11-07, v0.9.0, 2026-11-06, v0.8.0, 2026-11-04, v0.7.0, 2026-11-03, and v0.6.1, 2026-11-02; the first was v0.4.0; v0.6.0 has no files, its build failed). Each is marked **pre-release**: pre-alpha and **not field-tested**. Read its notes first.

**v0.8.0 changed the release keys.** It is signed with the project's new CI key, which boxes on v0.6.1 or older do not trust. Flash such a box over USB, or take it through v0.7.0 first: [section 7.1](#71-with-the-projects-releases). A few things in this guide need v0.9.0 or later; they say so. The USB radio modem has no update over the air: for the controller to free boxes left in an ended game, flash the v0.9.0 modem image over USB ([modem guide](modem.md)).

**v0.11.0: nothing has to be updated together.** Coming from v0.10.0, update the controllers, the boxes, the site server and the players' app when it suits you: older apps, rosters and controllers keep working with newer ones. The Field Box firmware changed only in code that the hardened image uses, and no box runs that image, so updating the boxes over the air is optional; the USB radio modem needs no new image. For an app check-in to show the marshal that it came from the **registering phone**, update the site server, the controller and the players' app; until then app check-ins show **phone not proved** and still go through ([marshal manual](marshal.md#printed-tickets-and-registered-players)). Coming from v0.9.0 or earlier, the v0.10.0 rule below still applies.

**v0.10.0: update the controllers and the boxes together.** From v0.10.0, **Release every box not in this game** names its channel: a v0.9.0 box refuses a v0.10.0 controller's, and a v0.10.0 box refuses a v0.9.0 controller's. Update the controller (Raspberry Pi or phone) and every Field Box to v0.10.0 on the same day, and reflash the USB radio modem with the v0.10.0 image over USB (it has no update over the air). Until both are updated, a stuck box still leaves its game with **Leave the game** at the box, `@leave` on its USB console, or the controller's automatic resend.

Pick the files for your board:

| You are building | Download | Notes |
| --- | --- | --- |
| A Field Box, or a Satellite (same image) | `atalaia-field-box-<version>-usb.zip` (esptool over USB) or `atalaia-field-box-<version>-merged.bin` (browser flasher) | The plain `atalaia-field-box-<version>.bin` and its `.bin.release.json` are for updates over the air ([section 7](#7-updates-over-the-air-and-what-else-uses-the-field-wi-fi)); you do not need them to flash |
| The controller's USB radio modem | `atalaia-modem-<version>-usb.zip` or `-merged.bin` | The second board, plugged into the controller |
| An I/O pod | `atalaia-io-pod-<version>-usb.zip` or `-merged.bin` | |
| A target (from v0.8.0) | `atalaia-target-module-<version>.uf2` (one plate) or `atalaia-target-module-2-<version>.uf2` (two plates) | [Section 11](#11-the-expansion-modules-target-and-output-module) |
| An output module (from v0.8.0) | `atalaia-output-module-<version>.uf2` | Four relays, 30 s at most each; other loads need a build of your own ([section 11](#11-the-expansion-modules-target-and-output-module)) |
| Never for a game | (the bench image is not released) | Build it yourself if you need it |

The ESP32 files are for the Heltec WiFi LoRa 32 V4.3, European radio region (EU868), listen before talk on, with the project's keys built in. For V4.2, for Taiwan (AS923) or for your own keys, build it yourself ([2.2](#22-build-it-yourself)).

**Check what you downloaded.** Download `SHA256SUMS` too, and compare. On Linux and macOS, in the folder of the files (`shasum -a 256 -c SHA256SUMS` on macOS; files you did not download are reported missing, ignore them):

```
sha256sum -c --ignore-missing SHA256SUMS
```

On Windows `cmd`: `certutil -hashfile atalaia-field-box-0.8.0-usb.zip SHA256` and compare the line with the one in `SHA256SUMS`. The sums prove the file is the one the release page lists. The signature proves who made a Field Box image: the `.release.json` is signed with one of the project's CI release keys, which every box trusts by default (`firmware/esp32/docs/RELEASE_SIGNING.md`). A box and a controller check it for you before they install an update.

**Flash the zip.** Unzip it. In that folder follow [section 3](#3-flash-it) from 3.1 on: the commands are the same, and the `README.txt` inside the zip repeats them. The folder has the `flash_args` file the command uses, so skip the build and the `cd firmware/esp32/build` step.

**Flash the merged file from a browser** (Chrome or Edge, no Python): open Espressif's web flasher, [https://espressif.github.io/esptool-js/](https://espressif.github.io/esptool-js/), connect the board (download mode if it does not appear, [3.2](#32-find-the-boards-port)), set the flash address to `0x0`, choose the `-merged.bin` file and program. Not tried by the project with a real board yet; the file is the same one the esptool command produces from the zip.

The version on the release is the version the box shows at boot (`0.8.0`).

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

A build from a checkout prints a version such as `0.11.0+12.g1a2b3c4` (or `0.12.0-dev.12+g1a2b3c4` between releases): the release's number, the number of changes since, and the code's identifier. It is also on the board's small screen at boot. Keep a note of it with the box. To get exactly a release's firmware, check out its tag (`git checkout v0.11.0`) and build there: a clean checkout of a tag says plain `0.11.0`.

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
| macOS | `/dev/cu.usbmodem...` (list them with `ls /dev/cu.usbmodem*`) | No driver is needed. Use the `cu.` name, not the `tty.` one. Box and modem images were written this way on a Mac (2026-11-02, Apple silicon, macOS 27); with several boards, see the [modem guide, section 4.2](modem.md#42-find-the-boards-port) to tell them apart |

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

For the modem and the pod, go to `build-modem` or `build-pod` instead. The modem has its own page, with these commands for each system: [Set up the radio modem](modem.md).

**USB flash required once, from v0.5.** A box flashed with v0.4.0 or earlier has the old partition table (2 MB program slots). From v0.5 the program slots are 4 MB, and an update over the air cannot change the partition table, so flash such a box over USB once, with the command above and **without** `erase_flash`: the settings, the keys and the adoption stay where they are (the table's first four partitions did not move). What is lost is the storage partition, which moved: the box formats it on the first start and fetches the game modes it lacks again at the next join. A box still on the old table refuses to run the new firmware: its screen says *Flash over USB* and the log says `WRONG PARTITION TABLE`. A box that was offered the new image over the air by an older firmware goes back to its old one by itself. After the one USB flash, updates over the air work as before. The USB radio modem and the I/O pod share the table: one already flashed with v0.4.0 or earlier only logs `WRONG PARTITION TABLE` and keeps working, but flash it over USB once as well (without `erase_flash`) so it has the new layout.

### 3.4 Restart and watch

Restart the board with this command. It is the reliable way. A serial program's own reset is not:

```
PY -m esptool --chip esp32s3 -p COM5 --after hard_reset chip_id
```

Open the log and press `Ctrl+]` to leave:

```
PY -m serial.tools.miniterm COM5 115200
```

You should see the firmware's version, the memory, and one line for each part found. A part that is not fitted gives a warning and the box goes on. The log may warn about GPIO 33 to 37: the project's bench notes call that cosmetic. On macOS, opening the port can restart the board: wait for the boot log to end before you type a console command (a script that sends one right after opening the port must wait too).

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
| Antenna gain | `--antenna-dbi=10` (the fitted antenna's rated gain, 0 to 20 dBi): the firmware lowers the transmit power by it, so a higher-gain antenna stays within the legal radiated power | 2 dBi |
| Mode keys | `--mode-keys=<key>[,<key>...]` (up to 4, hex or base64) | The project's two keys |
| Release keys | `--release-keys=<key>[,<key>...]` (up to 4, hex or base64) | The project's two release keys: root `424d053af5cdbc35` and CI `a4f6002b0122b131` ([section 7](#7-updates-over-the-air-and-what-else-uses-the-field-wi-fi)) |
| Version | `--fw-version=0.4.1` | From the code |
| Piezo buzzer (on GPIO 45) | `--buzzer=on` | off |
| Simple output: an RC relay switch for a siren, strobe or smoke remote (GPIO 46 on a V4.3, 5 on a V4.2; not yet tried on hardware) | `--simple-out=on`; `--simple-out=on2` adds a second one on GPIO 45 (not with the buzzer); a number picks another free GPIO (a bench board) | off |

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
| A passive piezo buzzer is fitted (on GPIO 45; not yet tried on hardware; or `--buzzer=on`) | `CONFIG_ATALAIA_BUZZER=y` |
| A simple output is fitted (or `--simple-out=on`); its outputs stay off until enabled at the box with the admin PIN | `CONFIG_ATALAIA_SIMPLE_OUT=y` |

Never lower `CONFIG_ATALAIA_RADIO_FEM_GAIN_DB` or the antenna gain below the real values. That would break the legal power limit.

If you change `--region`, `--lbt`, `--antenna-dbi`, a key option, or update the repository, the build may make the settings file again from the defaults and your edits are lost. Do the edit again. Keep a note of your edits.

**Settings you do not set at build time.**

- **The admin PIN** has no default. You choose it on the setup page ([section 5](#5-first-boot-and-setup)). Easy PINs such as 1234 are refused.
- **The field Wi-Fi** name and password are set on the setup page too.
- **The field join key** is given to the box when it is adopted ([section 6](#6-adoption)).
- **Your own splash logo.** The image on the box's boot screens (the OLED's and the big screen's) and on its *ready* screens is a build asset, `firmware/esp32/assets/splash.pgm` (the Atalaia tower). To build a box with another one, make a **plain-text PGM** (the first line `P2`, then `30 60`, then the maximum value, then 1,800 numbers, one per pixel, row by row; `assets/splash.pgm` is an example you can open in a text editor, and GIMP and ImageMagick write the format: `convert logo.png -resize 30x60! -depth 8 -compress none logo.pgm`) **of exactly 30 x 60 pixels**. A pixel is lit from half the maximum value up and dark below: the image is one colour, drawn white on the small OLED and in the accent colour, scaled up to 96 pixels tall, on the big screen; make it tall and narrow, like the tower. Then either replace `assets/splash.pgm`, or point the build at your file (`CONFIG_ATALAIA_SPLASH_LOGO` in menuconfig, *Boot splash*, a path relative to `firmware/esp32/` or absolute; for `docker_fw.py` put a line `CONFIG_ATALAIA_SPLASH_LOGO="assets/mine.pgm"` in `firmware/esp32/sdkconfig.defaults`, and keep the file inside the repository so the build container sees it). The build turns the file into a C array and stops with a message if the file is not a 30 x 60 plain-text PGM. Only the Field Box and the modem have a splash. **The project's release images always carry the Atalaia tower**; a box with your image is your own build and gets no release update that you did not build yourself ([section 7](#7-updates-over-the-air-and-what-else-uses-the-field-wi-fi)).
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
   - **Field Wi-Fi name** and **password** (optional, but needed for updates and fetched game modes: [section 7](#7-updates-over-the-air-and-what-else-uses-the-field-wi-fi)). The field Wi-Fi must be 2.4 GHz. The name is 1 to 32 bytes: an accented letter takes 2 and a Chinese character 3, so a name with them can be refused under 32 characters. The password is none (an open network), 8 to 63 characters, or exactly 64 hex digits. From v0.9.0 the page refuses anything else and says why, as the USB console does; v0.8.0 and older cut a longer name or password without saying so.
5. Tap **Save & Reboot**. The box restarts.

Then a box with no field shows **PAIR THIS BOX** and a 6-digit code ([section 6](#6-adoption)). A box that is already adopted shows **READY**.

**Open the setup page again.** On a box that was set up, there are two ways. Neither works during a game.

- On the keypad: press a key, type the admin PIN and `#`, go to the entry **Wi-Fi setup** (after the games), press `#`, then `#` again to confirm.
- On the USB console (a serial monitor on the box's port, 115200): type `@setup` and the admin PIN, then Enter.

The box keeps its adoption and its field key. It replaces what the page asks for. The bench build has no setup page.

**Take a box out of its game.** A box that was switched off when its game ended comes back in that game: its log refuses every join (`join: a game is being played`) and USB adoption (`busy`). Do not erase it. From v0.9.0, type `@leave` and the admin PIN on the USB console, then Enter. The box answers `leave: game N is over on this box; it is free for the next game`, and keeps its adoption, its join key, its Wi-Fi, its admin PIN and its modes. A wrong PIN counts toward the waits below. The bench build takes `@leave` alone. The other ways out (the box's admin menu, and the controller freeing it by itself with a v0.9.0 modem) are in the [Field Box manual](field-box.md#take-a-box-out-of-its-game).

**Forgotten PIN.** After five wrong PINs the box makes you wait 1, 2, 4... up to 60 minutes. The wait survives a restart. If you really lost the PIN, erase the settings ([section 8](#8-a-box-that-does-not-boot)).

Not yet tested on a real board: the setup page and the screens above. The page was tested on a computer and in the emulator.

## 6. Adoption

A box plays only in the field that **adopted** it. Adopting gives it the field's join key, once. The organisers do it from the controller's console, in the **Adopt** tab. There are three ways. Details for the organisers are in the [Game master manual](game-master.md) and the [Field Box operator manual](field-box.md).

- **By code, over the radio** (no cable, no card). A box with no field shows **PAIR THIS BOX** and a 6-digit code, on its screen and on its small screen. In the console, **Pair by code (radio)**, look for boxes on the radio, pick the box by name and type the code. The box then shows **ADOPTED** and the field's name. A wrong code gives a new code. Three wrong codes make the box wait a minute. Ten stop pairing until it restarts. Done on two real boards on a bench. Not yet tested on a field.
- **By USB cable.** Plug the box into the computer that runs the controller. In the console, look for boxes and press **Adopt**. The box's USB port must be reachable by the controller. Done on a real board on a bench.
- **By NFC field card.** Tap the field card on the box's NFC reader. The card is the field's master secret: lock it away. Not yet tested on a real board (no NFC reader has been fitted on a real board).

A box of another field asks for its **admin PIN**. **Change field** moves a box on purpose: on the keypad press a key, type the PIN and `#`, pick **Change field** (the entry after the games and **Wi-Fi setup**), confirm. The box shows a pairing code and keeps its old field until the new field has paired it. A Satellite has no keypad: use the USB cable.

## 7. Updates over the air, and what else uses the field Wi-Fi

Two things use the field's Wi-Fi, and only between games: **firmware updates** and **game modes the box does not have** (fetched from the controller as signed packages). For both the box needs the **field Wi-Fi name and password** from the setup page, and the controller must be running with HTTPS on.

You can also set the Wi-Fi on the USB console: `@wifi <name> <password>`, or `@wifi <name>` for an open network. From v0.9.0, a name or password with spaces goes in double quotes: `@wifi "My Field" "pass word"` (inside the quotes, `\"` is a quote and `\\` a backslash). The rules are the setup page's ([section 5](#5-first-boot-and-setup)). The box answers `field Wi-Fi: stored (network "My Field")`, or `field Wi-Fi: refused:` and why (a quote left open, for example), and then stores nothing. On v0.8.0, `@wifi` takes no spaces in the name.

**The rules for firmware updates.** The box installs an update only if all of these are true:

- No game is being played.
- The update is signed by a **release key built into the box's own firmware** (`--release-keys`, [section 4](#4-the-options-a-builder-sets)). By default that is the project's two release keys, so the Field Box files from a GitHub release can be installed as updates; a box built with `--release-keys=` your own key trusts only that.
- The version is higher than the one it runs.
- It is the same variant and board (a V4.2 image never goes on a V4.3).
- The battery is at 30 % or more, if the box has a gauge.

The controller checks the signature too, when the release is uploaded, against its own `[firmware] release_keys`: a release signed by a key it does not list is refused. How the organisers run an update from the console: [Field Box manual, Update the boxes](field-box.md#update-the-boxes).

### 7.1 With the project's releases

The project has two release keys, listed in [docs/community/keys.md](../../community/keys.md) and [RELEASE_SIGNING.md](../../../firmware/esp32/docs/RELEASE_SIGNING.md):

| Key | Key id | Public key (base64, for `controller.toml`) |
| --- | --- | --- |
| Root | `424d053af5cdbc35` | `5tzPkN0AJSn+g34CP59linCRf/fcaWFc7GAAg7qzYNc=` |
| CI (signs the releases from v0.8.0) | `a4f6002b0122b131` | `76eY5BoMQ4RHohhX/8iSUlIUA5o5Entfk7EFBUxpbSY=` |
| Old CI, **retired** (signed the releases up to v0.7.0) | `32b3c815ac30ad43` | `rIO8ogMU3LRLLtnt6Rys+URdKYfmNv5mxvuRJQsX9Tw=` |

Firmware up to v0.6.1 trusts root and the old CI key; v0.7.0 trusts all three; v0.8.0 and later trust root and the new CI key only. To bring a field onto v0.8.0 or later:

1. **Flash each box once over USB** with a release, if it has never been ([section 3](#3-flash-it)).
2. **Set the controller's keys.** A Raspberry Pi whose `controller.toml` has no `release_keys` takes the project's current two keys when it starts. If `controller.toml` lists them by hand (the example file did), make the list exactly the root key and the new CI key from the table, and drop the old one. Nothing removes it for you. Restart the controller. A phone controller that kept the app's default takes the new list by itself; an edited list is kept as it is. A site server's `ATALAIA_FIRMWARE_KEYS`, if you set it, drops the old key too.
3. **Boxes on v0.7.0 or later:** upload the newest release's `atalaia-field-box-<version>.bin` and its `.bin.release.json` in the console's **Boxes** tab, and press **Update to**.
4. **Boxes on v0.6.1 or older** refuse v0.8.0 and later. Either flash the newest release over USB, without `erase_flash` (the settings, the keys and the adoption stay), or update them to **v0.7.0** first over the air and then to the newest. v0.7.0 is signed with the old key, so the controller accepts its upload only while its `release_keys` also lists the old key: add it for that step and drop it again afterwards.
5. **Check** that every box reports the new version, and delete any release the console marks **key no longer trusted**.

### 7.2 With your own key

1. Make a key with `tools/firmware_release.py keygen`. Keep the private file safe and out of the repository.
2. Build the boxes with `--release-keys=<the public key>` (add the project's keys again if you still want its releases). Flash them over USB, once. Updates cannot install a new bootloader.
3. Put the key's public half in the controller's `[firmware] release_keys` setting.
4. For an update, build a higher version (`--fw-version=0.8.1`), sign it with `tools/firmware_release.py sign`, and upload the image and its `.release.json` in the console's **Boxes** tab. Press **Update to**.
5. The box downloads it, checks it again, installs it and restarts. If the new image fails its self-test, the box goes back to the old one by itself.

Done once on a real board on a bench, with a throw-away key, sent by the controller over the radio, on a home Wi-Fi network (about 11 seconds). Not yet tested on a field. A box flashed with firmware from before updates over the air existed needs one USB flash first, and so does a box on the old partition table (v0.4.0 or earlier) before it takes v0.5 or later ([section 3.3](#33-write-the-image)).

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

The controller's radio is a second Heltec V4 plugged into its USB port. It runs the modem image. **The whole path, with the flash commands for Windows, Linux and macOS, the port, the controller's `[modem]` setting, the checks and a troubleshooting table, is in [Set up the radio modem](modem.md).** What a builder needs to know about the image itself:

- **Download it** (`atalaia-modem-<version>-usb.zip`, section 2.1) or **build it** with `python tools/docker_fw.py modem` into `firmware/esp32/build-modem/`. The released one is V4.3, EU868, English until the controller connects. Build the modem for the same board revision and the same region as the boxes (`--region=as923-tw` for Taiwan; for a V4.2, edit `build-modem/sdkconfig` as in [section 4](#4-the-options-a-builder-sets)).
- **Flash it** like any board ([section 3](#3-flash-it)), from the unzipped folder or from `firmware/esp32/build-modem`. If the board is plugged into a running controller, stop the controller first: it holds the port. The modem has no over-the-air update.
- **Fit the LoRa antenna before power.** The modem has no Wi-Fi, so it needs no 2.4 GHz antenna.
- **Its small screen** shows the tower and **MODEM MODE** for about two seconds, then the status: **LINK** `waiting` (the controller has not talked to it: it is not running, or the modem is on another port), `OK`, or `DOWN` (it talked, then stopped for 12 seconds); the game number, the channel, the packets sent and received with their failures, and the airtime left; **RADIO FAULT** if the radio chip did not start.
- **The screen's language** is the boxes' (English, Portuguese, German or Traditional Chinese). The controller tells the modem which one every time it connects: the **box language** setting in the GM console, or with `auto` the language of the console that created the game. Before that, and on the first splash, the modem uses its build's language, `en` by default. To make it another one, set `CONFIG_ATALAIA_MODEM_LANG="pt"` (or `de`, `zh-tw`) in `firmware/esp32/build-modem/sdkconfig` and build again, as in [section 4](#4-the-options-a-builder-sets). In Portuguese the words are `aguarda`, `OK`, `PERDIDO` and `FALHA NO LORA` (the small font has no accents); in German `wartet`, `OK`, `GETRENNT` and `FUNKFEHLER`; in Chinese the link is in the top bar (`等待`, `正常`, `離線`) and a radio fault is `無線電錯誤`. An older modem image, built before this, stays in English.
- **Its port** goes into the controller's `[modem] port` setting: [Set up the radio modem, section 7](modem.md#7-put-the-port-in-the-controllers-settings-and-restart-it).

The modem is the only image whose USB port carries data frames, so its log is on UART0 (GPIO 43 and 44), not on USB: do not open its USB port with a serial monitor, and expect no log from [section 3.4](#34-restart-and-watch). A modem like this has run with the controller and real boxes on a bench (2026-10-21). Not yet tested on a Raspberry Pi.

## 10. The I/O pod variants

An I/O pod lends its buttons, keypad, ring, sound, NFC reader and radio to an Android phone. Its parts are in the [I/O pod build guide](../../../hardware/io-pod/BUILD.md).

- Build: `python tools/docker_fw.py pod` (`--region` as above). Flash from `firmware/esp32/build-pod`. Edit `build-pod/sdkconfig` for a V4.2.
- A pod has no setup page, no Wi-Fi and no admin PIN. It has the 2.4 GHz antenna for **Bluetooth** (`atalaia-pod-XXXX`), which is paired and encrypted. The phone pairs with a **6-digit code** that the board's small screen shows while it pairs; Android's dialog asks for it. Hold the board's **PRG** button 5 seconds to make the pod forget every phone ([I/O pod build guide, section 10](../../../hardware/io-pod/BUILD.md#10-linking-it-to-a-phone)).
- Its USB port carries the frames to the phone, so the log is on **GPIO 43** (UART0 transmit), read with a 3.3 V USB-serial adapter at 115200 baud. It is not on the USB port.
- Build options for the pod, in `build-pod/sdkconfig`: a colour for each button (`CONFIG_ATALAIA_POD_BTN1_TEAM="red"` and so on), the enclosure switch pin (`CONFIG_ATALAIA_POD_TAMPER_PIN`), Bluetooth on or off. Leave `CONFIG_ATALAIA_POD_BLE_ENCRYPTED` and `CONFIG_ATALAIA_POD_BLE_PASSKEY` on.
- The buttons' colours, the ring's brightness, the volume and the enclosure switch can also be set **over the radio** from the GM console, with no cable ([I/O pod build guide, "Settings over the radio"](../../../hardware/io-pod/BUILD.md#settings-over-the-radio)); they are kept in the pod's flash. The LED count, the pins and the radio stay in `build-pod/sdkconfig`.
- **Simple outputs** (optional): `python tools/docker_fw.py pod --simple-out=on` builds a pod with an RC relay switch's signal on **GPIO 33** (`on2`: a second one on **GPIO 1**; the piezo buzzer may stay). A pod has no admin PIN, so building the output in enables it: set its use, the name the games call it by, in `build-pod/sdkconfig` with `CONFIG_ATALAIA_POD_OUT1_FUNCTION="siren"` (or `strobe`, `smoke`, `light`, `horn`; `out.1` by default) and its longest on with `CONFIG_ATALAIA_POD_OUT1_MAX_ON_S` (30 s by default). The phone's game switches it; the pod turns it off when the phone's link drops or the phone stops talking for 1.5 s. Wiring: [I/O pod build guide, section 8.1](../../../hardware/io-pod/BUILD.md#81-simple-outputs-optional).
- **Expansion port** (optional): every pod build looks for modules on its expansion port (the M12 socket on the board's I2C bus, GPIO 17 and 18): a target module's hits reach the phone's game. `--module-outputs=on` also lends an output module's relays to the phone (`CONFIG_ATALAIA_POD_MODULE_OUTPUTS`; their longest on `CONFIG_ATALAIA_POD_MODULE_MAX_ON_S`, 30 s by default, never more than the module's own); the pod turns them off when the phone goes. `# CONFIG_ATALAIA_POD_PORT is not set` leaves the port out. Wiring: [I/O pod build guide, section 8.2](../../../hardware/io-pod/BUILD.md#82-expansion-port-optional).
- The board's small screen stays dark, except while a phone pairs: the code, then **PAIRED**, **FAILED**, **TOO SLOW** or **PAIR AGAIN** (in English: the pod has no language). Pairing with the code is not yet tried on a real board.

Not yet tested on a real board: all of it. The pod firmware has run on a computer, against the app and the controller. The Satellite is not a variant: it is the Field Box image with fewer parts fitted ([Satellite build guide](../../../hardware/satellite/BUILD.md)). The modules a pod or a box takes on its expansion port are in [section 11](#11-the-expansion-modules-target-and-output-module).

## 11. The expansion modules: target and output module

A Field Box or an I/O pod with an **expansion port** (an M12 socket on the board's I2C bus) takes small modules, each with an RP2040 board and firmware of its own. Every Field Box image and every pod image looks for them; there is nothing to set on the box. What they do on a field is in the [Field Box manual, section 8](field-box.md#8-outputs-and-modules).

| Module | What it is | Address | Build guide |
| --- | --- | --- | --- |
| **Target** | A plate players shoot at, with a piezo sensor; one plate, or two with the second firmware file | 0x58, up to 0x5B with the address jumpers | [hardware/target-addon/BUILD.md](../../../hardware/target-addon/BUILD.md) |
| **Output module** | Up to 4 relays or MOSFETs on a supply of its own, behind an I2C isolator; SELV loads only, at most 24 V DC and 2 A per channel | 0x5C, up to 0x5F with the address jumpers | [hardware/output-module/BUILD.md](../../../hardware/output-module/BUILD.md) |

Both firmwares are written and tested on a computer; **neither has run on a board yet**, and no module has been built from its guide.

**Get the UF2 file.** Download it from a release (v0.8.0 or later; [section 2.1](#21-download-a-release-the-easy-way)), checked against `SHA256SUMS`, or build both with Docker:

```
python tools/docker_module.py build
```

The files land in `firmware/target-module/build/` (`atalaia_target_module.uf2`, and `atalaia_target_module_2.uf2` for two plates) and `firmware/output-module/build/` (`atalaia_output_module.uf2`). The UF2 files are not signed: a module is flashed by hand and never updated over the air.

**The output module's channels.** The released file has four relays, 30 seconds at most each. For other loads, set each channel's type, use, longest time on and rest time at build time (`OUTPUT_CHANNELS`, for example `relay:siren:60:0,relay:strobe:120:0,relay:smoke:30:30:sense`) as in [firmware/output-module/README.md](../../../firmware/output-module/README.md). These are the module's own limits: the box's admin can only lower them.

**Flash a module:**

1. **Unplug the module from the box's port.** Never connect its USB cable and the port cable at the same time. For the output module, switch its own supply off too: its RP2040 board joins USB 5 V to its 5 V pin.
2. Hold the board's **BOOT** (BOOTSEL) button and plug its USB cable into a computer. Release the button.
3. A drive called `RPI-RP2` appears. Copy the UF2 file onto it.
4. The board restarts into the firmware by itself.
5. Unplug the USB cable, plug the module into the box's port, and check: the box's USB log says `expansion: 0x58 added: ...` (the module's address), and `@modules` on its USB console lists it (a target as `58:target/1.0.0:hit`).

More, with the pins and the host tests: [firmware/target-module/README.md](../../../firmware/target-module/README.md), [firmware/output-module/README.md](../../../firmware/output-module/README.md).

Found a step that does not match what you see? Open an issue or tell us in [Discussions](https://github.com/vakaobr/atalaia-project/discussions).
