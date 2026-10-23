<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# ESP32 Firmware

ESP-IDF firmware for Atalaia Field Boxes running on ESP32-S3, and two more
images from the same project: the field controller's USB radio modem and
the I/O pod that lends its hardware to an Android phone.

## Default Board

**Heltec WiFi LoRa 32 V4.3** (bare board, 863-928 MHz).
ESP32-S3R2 with 2 MB PSRAM, 16 MB flash, SX1262 LoRa radio.

The Heltec V3 (8 MB flash, no PSRAM) is also supported as a
Reduced-tier option.

## Architecture

The firmware is structured as a shell around the shared C core (`core/`):

```
app_main
  +-- game_task (core 1, priority 5, 100 Hz, 12 KB stack)
  |     +-- radio RX -> box_game (field games: join, CMD, TIME, ACK)
  |     +-- poll buttons/keypad/serial console
  |     +-- NFC: join cards when idle, player tags during a game (nfc.tag)
  |     +-- atalaia_node_advance()
  |     +-- game_timer_tick()
  |     +-- state_persist_save() (every 1 s)
  |     +-- command_dispatch()
  +-- lvgl_task (core 1, priority 4, 5 ms)
  |     +-- display_port_init() (LVGL 9.2, DMA flush)
  |     +-- screen_render() (the mode's YAML template, else the C screen)
  |     +-- lv_timer_handler()
  +-- radio_task (core 0, priority 3)
  |     +-- TX queue drain (radio_task_send)
  |     +-- RX poll (50 ms timeout via DIO1 ISR)
  |     +-- single shared game channel (default 869.525 MHz, g2)
  +-- audio_task (core 0, priority 3)
  +-- wifi_task  (core 0, priority 2)
  +-- mem_monitor (core 0, priority 1, 10 s)
```

### HAL Abstraction

Every hardware subsystem is behind a function-pointer ops struct
(`hal_button_ops_t`, `hal_keypad_ops_t`, `hal_radio_ops_t`, etc.).
ESP-IDF drivers live in `main/hal/esp/`; stubs for Linux testing in
`main/hal/stub/`.  The shell holds a `hal_t` aggregate initialised by
`hal_esp_init()` or `hal_stub_init()`.

### Radio HAL

The SX1262 LoRa radio driver (`main/hal/esp/hal_esp_radio.c`) uses
SPI3_HOST (GPIO 8-14: NSS, SCK, MOSI, MISO, RST, BUSY, DIO1).
EU868 band, SF7/BW125, single shared game channel: the field's channel,
which a box gets in its join payload and the modem with CONFIGURE or
SET_CHANNEL (`CONFIG_ATALAIA_RADIO_DEFAULT_CHANNEL_HZ` in Kconfig until
then). The default, 869.525 MHz, is the centre of 869.4-869.65 MHz, the
only EU868 sub-band with 10% duty cycle and 500 mW ERP; the GM can choose
another one in the controller's console (RFC 0001 Amendment 3). The whole
125 kHz channel must fit in one sub-band, so `set_channel()` refuses a
centre such as 869.40 MHz whose channel spills over an edge.

The duty-cycle budget and the TX power follow the channel's sub-band
(`main/radio/radio_limits.c`): 10% of a sliding hour and 500 mW ERP on
869.4-869.65 MHz, 1% (0.1% on 868.7-869.2 MHz) and 25 mW ERP elsewhere,
counted per sub-band with the LoRa time on air of each packet; a packet
that does not fit in what is left is not sent. The FEM (front-end module)
on the Heltec V4.3 provides ~14 dB of gain; `radio_power.h` turns the
sub-band's ERP limit into the SX1262's conducted power, accounting for
the FEM and antenna gain (Kconfig `ATALAIA_RADIO_FEM_GAIN_DB` and
`ATALAIA_RADIO_ANTENNA_GAIN_DBI`): 13 dBm on 869.4-869.65 MHz and 0 dBm
elsewhere with the defaults. The LoRa sync word is the private-network
value 0x1424.

`measure()` listens to a channel without transmitting, reading the
instantaneous RSSI about once a millisecond and running a LoRa
channel-activity detection every 100 ms, and returns the summary of
`main/radio/noise_stats.c`: the USB modem's MEASURE command, which the
controller's "find a quiet channel" uses. Not yet checked on a real board.

DIO1 drives an ISR-based semaphore for TX_DONE/RX_DONE/TIMEOUT.
The init function probes the SX1262 before configuring FEM GPIOs; if
the chip is absent (Wokwi emulator), init returns -1 and the firmware
boots without radio. Every SPI command first waits for BUSY to drop
(at most ~200 ms); a BUSY timeout or an SPI error is returned to the
caller, so a missing chip is reported as "SX1262 not detected (BUSY
stuck high after reset)" or "(no answer on SPI)" and the hardware is
released, and a failed send returns -1 (or -2 on a TX timeout). The
per-step messages of `CONFIG_ATALAIA_RADIO_DEBUG_STEP` are debug-level
logs.

## Device Tiers

| Tier | Board | Lua heap | Display |
|------|-------|----------|---------|
| Full | Heltec V4.3 (2 MB PSRAM) | 256 KB | Colour TFT |
| Reduced | Heltec V3 (no PSRAM) | 64 KB | Monochrome OLED |
| Proxy | Cannot run scripts | -- | Thin node on controller |

A mode that uses 85% or more of the box's script memory right after it loads
logs a warning (`the mode uses N KB of this box's M KB script memory ...`):
it may run out during the game. On a Reduced box (Heltec V3) the Hacking
Terminal with the Codes modifier comes close (about 57 KB of 64 KB, decision
M4-8): it is offered, with that warning; prefer a lighter combination or a V4.

## Build

Everything builds in Docker (Docker Desktop must be running); no compiler is
needed on the host. `tools/docker_fw.py` works from `cmd`, PowerShell or
bash, from the repository folder:

```
python tools/docker_fw.py build                   firmware for the Field Box -> firmware/esp32/build/
python tools/docker_fw.py wokwi                   Wokwi emulator variant -> firmware/esp32/build-wokwi/
python tools/docker_fw.py modem                   USB radio modem variant -> firmware/esp32/build-modem/
python tools/docker_fw.py pod                     I/O pod variant -> firmware/esp32/build-pod/
python tools/docker_fw.py bench                   bare board on the desk -> firmware/esp32/build-bench/
python tools/docker_fw.py test                    host tests and screen reference images
python tools/docker_fw.py test --update-screens   accept changed screens as the new references
```

Every image carries the commit it was built from in its version (`PROJECT_VER`, which the
boot log, HELLO's `fw_version`, the modem's and the pod's IDENT and the console show, and a
firmware update compares; decisions FV-1 to FV-6): the core's version
(`core/include/atalaia/version.h`, `0.3.0-dev` while 0.3.0 is developed), the commits since
the last release tag `vX.Y.Z` (or since the first commit) and the commit's first 7 hex
digits, `0.3.0-dev.412+g8560d54`, with `.dirty` when tracked files have uncommitted changes.
`docker_fw.py` works it out on the host (the build runs in Docker) and prints it;
`python tools/docker_fw.py version` prints it without building. A copy with no commit (a
tarball, a fresh `git init`) or a plain `idf.py build` gets the core's version alone
(`0.3.0-dev`). Every development build of 0.3.0 is newer than 0.2.0 and older than 0.3.0;
`dev.N` compares as a number, and the `+...` build metadata never counts, so a box refuses an
update to another commit with the same count (`not_newer`).

`build`, `bench` and `wokwi` also take `--fw-version=0.3.0-rc.1` (the exact version instead,
for a release candidate or a bench test of an update; `+build` allowed, at most 31 characters)
and `--release-keys=<hex or base64>[,...]` (the release public keys the box accepts
updates from, `CONFIG_ATALAIA_OTA_RELEASE_KEYS`); both apply to that build folder only and
are reset when left out. See [Firmware updates](#firmware-updates-over-the-air).

The bench variant (`sdkconfig.bench`) is the Field Box firmware for a bare
Heltec V4 on the desk, with no keypad and no TFT: keys typed on the USB serial
console (`0`-`9`, `*`, `#`) drive the PIN screen and the picker, the Wi-Fi
setup portal is skipped (admin PIN `1234`), and the board's own OLED shows
the game. Never flash it to a box for a game.

`build`, `wokwi`, `modem`, `pod` and `bench` use the `espressif/idf:v5.3.2` image, like CI's
`esp32-build`, `esp32-modem-build` and `esp32-pod-build` jobs. `test` runs CI's `firmware-test` commands in the
`atalaia-dev` image. With a toolchain of your own, the same commands are:

```sh
cd firmware/esp32 && idf.py set-target esp32s3 && idf.py build
cmake -S firmware/esp32/test -B /tmp/fw-test -DCMAKE_BUILD_TYPE=Debug
cmake --build /tmp/fw-test && ctest --test-dir /tmp/fw-test --output-on-failure
```

## Screens

Since phase 3 a mode can ship its screens as YAML templates
(`modes/<mode>/assets/screens/`, ADR-P3-4; the format is in
[modes/README.md](../../modes/README.md#screens)). They are compiled into the
image at build time (`main/builtin_screens.cmake` writes `builtin_screens.c`,
like the mode scripts), parsed by the core (`core/src/screen_template.c`)
and drawn by `main/screen_template.c`: LVGL widgets are built once per
template and then only the widgets whose text, colour, value or visibility
changed are patched. The node runner tells the display which mode runs with
a `@mode <mode id> <params>` message in the screen queue, so a name resolves
to the running mode's template (main mode first, then its modifiers). Bomb
and Domination use templates; when a mode has no template of a name, the C
screens below are drawn. Templates come from the image only: there is no
upload path yet, so LittleFS is not read for them (decision K10).

The C screen templates (`main/screen_renderer.c`, ADR-P1-2) are C functions
that build LVGL 9.2 widget trees for the 320x240 TFT: `standby`,
`countdown`, `defused`, `exploded`, `final_score`, `paused`, `code_entry`
(a code typed on the keypad: title, dots, an optional clock and a message;
Bomb's team codes and the Codes modifier use it), `status`, the
preset picker (`pin_entry`, `preset_select`, `timer_adjust`,
`start_confirm`) and `wifi_setup`. Each template is built once and then
patched with new data, so a countdown only changes one label per second.

The host tests build the same code against the same LVGL release (9.2.2,
fetched from its GitHub tag and checked against `dependencies.lock`) and the
same `lvgl_conf/lv_conf.h`, render every template into memory, and compare
the result pixel by pixel with the PNG files in
[`test/screens/`](test/screens/). They also fail when a widget is clipped by
the screen or two labels overlap. The YAML templates of the modes have
their own reference images (`test/screens/yaml_*.png`), and
`test/test_screen_template.c` checks that every built-in template parses,
that the running mode picks them, that a patch changes only the widgets it
must, and the fallback to the C screens. After changing a screen on purpose, run
`python tools/docker_fw.py test --update-screens` (or set
`ATALAIA_UPDATE_SCREENS=1` for `ctest`), look at every changed PNG, and
commit them with the change. Rendered images land in
`firmware/esp32/build-test/screens/` (or `<build>/screens/` with `ctest`),
next to a `.diff.png` for each mismatch.

### The on-board OLED

The Heltec V4's own 0.96" OLED (SSD1306, 128x64, I2C 0x3C on the shared bus,
reset on GPIO 21) mirrors every screen as a compact status
(`main/oled_view.c`, driver `main/hal/esp/hal_esp_oled.c`): a header bar (the
running mode, or the picker's step), one big value (the PIN dots, the chosen
game, the timer, the countdown, the phase) and a footer (a team, a hint or a
message). While a team holds its button the footer turns into a progress bar
(the data's `progress`, or Bomb's `defuse` on the countdown). A mode's own
templates map too: a countdown when the data has `left`, else the screen's
name, with a team, owner or message below. The TFT keeps the full screen; a
bare board without one can be set up and played on the OLED alone, and on a
full box it is a status line for staff.

It is a second LVGL display, rendered in RGB565 and packed to one bit per
pixel on flush (`oled_pack`); only the 128-byte pages that changed go over
the 100 kHz bus, so a countdown tick costs one or two pages and a full frame
about 100 ms. At boot it shows a splash for 2 s (the tower from
`site/favicon.svg`, drawn by `tools/oled_logo.py` into `main/oled_logo.c`,
with the name and the version; the same file has the USB radio modem's
small header tower). Kconfig: `ATALAIA_OLED_STATUS` (on by
default), `ATALAIA_OLED_ADDR`, `ATALAIA_OLED_RST_PIN`, `ATALAIA_OLED_FLIP`
and `ATALAIA_OLED_SPLASH_MS`. Without an OLED at the address the box logs a
warning and runs without it. The host tests render the view through the
same LVGL build and compare it with [`test/screens/oled/`](test/screens/oled/)
(`test/test_oled_screens.c`, 1 bit per pixel as the panel shows it), and
`test/test_oled_view.c` checks the mapping.

## Wokwi emulator

[`docs/WOKWI.md`](docs/WOKWI.md) explains how to run the firmware in the
Wokwi emulator in VS Code (`wokwi.toml`, `diagram.json`) and play a Bomb
game on the simulated display, buttons, LED ring and keypad, before the
hardware arrives.

## USB radio modem variant

The same project builds the field controller's radio: a Heltec V4.3
plugged into the Raspberry Pi over USB (ADR-P2-4). `sdkconfig.modem`
sets `CONFIG_ATALAIA_MODEM_MODE`, which builds `main/modem/` instead of
the Field Box shell: the radio HAL and radio task, plus a serial task
that moves the frames of [protocol/usb-modem.md](../../protocol/usb-modem.md)
between the USB-Serial-JTAG port and the radio. The modem encrypts and
decrypts with AES-CCM (mbedtls, hardware AES), dedupes flood copies,
enforces the duty cycle of the channel's sub-band, measures the noise on
a channel when asked (MEASURE, only while no game is configured), carries
field frames as they are, with or without a game (FIELD_TX, FIELD_RX,
FIELD_ACK: it never holds the field join key), and
keeps the game key in RAM only; it has no
Lua, game screens or presets (~480 KB image, ~190 KB of it LVGL and the
fonts for its own OLED). The log console stays on UART0
only, so it never mixes with the frames, and the task watchdog reboots a
hung modem. `CONFIG_ATALAIA_MODEM_LINK_UART0` switches the link to UART0
for boards with a USB-UART bridge.

### The modem's OLED

The board's own OLED tells a GM whether the modem works, without a laptop
(`main/modem/modem_screen.c`, task `main/modem/modem_display.c`). At boot,
for 2 s, the splash: the tower, "ATALAIA", "MODEM MODE" and the version (as much of it
as the line holds: the boot log and the IDENT have all of it, FV-6).
Then the status screen, under a header bar with a small tower and
"MODEM MODE":

```
LINK          OK     the controller: OK, DOWN (inverted) or waiting
GAME        4660     the game id, or IDLE  no game / IDLE  measuring
CH   869.525 MHz     the channel the radio is on
TX 1234   fail 3     packets sent, and TX failures
RX 56k    auth 1     packets passed to the controller, and MIC failures
DUTY 341.2s left     the duty-cycle budget left (inverted at 0.0s)
```

- **LINK OK**: a frame from the controller arrived in the last 12 s (it
  pings every 5 s, `ping_interval_s`). **waiting**: none since the modem
  started: the controller is not running, or the modem is on the wrong USB
  port. **DOWN**: frames came, then stopped for 12 s: the controller
  stopped or lost the port (it reconnects by itself after three missed
  pings; check the controller before rebooting the modem).
- **GAME n**: the controller sent CONFIGURE for game n; the modem passes
  that game's packets. **IDLE no game**: no game yet, or the game was
  cleared; nothing is passed on. **IDLE measuring**: a noise measurement
  (MEASURE) is running.
- **CH**: the radio's channel, the build's default until the controller
  sets one.
- **TX / fail, RX / auth**: the same counters as the controller's
  `/api/v1/controller` (`tx`, `tx_fail`, `rx`, `rx_auth_fail`); above 9999
  they shorten to 12k, 4M. Climbing `auth` means packets of the game that do
  not decrypt (a box on an old key, or another game on the same id).
- **DUTY**: the airtime left in the sub-band's duty-cycle budget
  (`duty_ms`). At 0.0s the line turns inverted and TX waits for budget.
- **RADIO FAULT** (inverted, in place of the last four lines): the SX1262
  did not come up at boot, with the reason from `hal_esp_radio.c`
  ("SX1262 not found (BUSY stuck)", "SX1262 errors 0x0020 (TCXO)", ...).
  The modem still talks to the controller but cannot send or receive: the
  board needs a look (or another board).

The modem task publishes a copy of its state five times a second; the
display task (priority 1, below the radio's 3 and the modem's 4) reads it
twice a second and redraws only when a line changed, and only the changed
128-byte pages go over the I2C bus, which carries nothing else on a modem.
It never blocks the USB link or the radio; without an OLED it logs one
warning and the modem runs as before. Kconfig: the "On-board OLED" options
(`ATALAIA_OLED_STATUS`, `_ADDR`, `_RST_PIN`, `_FLIP`, `_SPLASH_MS`) and
`ATALAIA_MODEM_LINK_TIMEOUT_S` (default 12). The host tests compare the
modem screens with `test/screens/oled/modem_*.png` and check the lines in
`test/test_modem_screen.c`.

`main/modem/modem.c` and `modem_framing.c` are plain C: the host tests
(`test/test_modem.c`, `test/test_modem_framing.c`) run them with the
stub crypto, and `test/modem_host/` builds them with real AES-CCM into a
Linux program that the field controller's tests talk to over TCP, with
UDP standing in for the radio.

Not yet tested on a board: the USB-Serial-JTAG link, the TX power and
the radio timing need the parts (plan phase F).

## The I/O pod (phase 3, plan phase F)

The third image of the same project: a Heltec WiFi LoRa 32 V4 that lends
its hardware to an Android phone running a prop (ADR-P3-3). The phone runs
the mode; the pod has no Lua, screens, presets or Wi-Fi. It speaks the
capability proxy protocol v1 ([protocol/capability-proxy.md](../../protocol/capability-proxy.md))
on two links at once:

- **USB** -- the board's USB-C port, which is the ESP32-S3's own
  USB-Serial-JTAG controller: a phone sees a CDC ACM serial device, as the
  controller sees the USB modem. TinyUSB would need an extra component and
  would take the port away from flashing; the modem already proves this
  path (decision PF3). The log console stays on UART0.
- **Bluetooth LE** -- a NimBLE GATT server (part of ESP-IDF): the service
  `4174616c-6169-6100-0000-000000000000` with Pod TX (notify), Pod RX
  (write without response) and Pod Status (read, notify), advertised as
  `atalaia-pod-XXXX`, one phone at a time, a 247-byte MTU. The pod asks the
  phone to pair (LE Secure Connections, Just Works, bonded): frames go out
  and Pod RX writes are taken only on an encrypted link, so the game key
  in RADIO_CMD CONFIGURE never crosses the air in the clear (decision PF4).

What it lends (only what is fitted is in IDENT; decision PF6):

| Capability | Events | Commands |
| --- | --- | --- |
| `btn.1`-`btn.4` (button) | `press`, `hold` {"ms"} every 250 ms, `release` {"ms"} | |
| `keypad` (PCF8574) | `key` {"key"} | `clear` |
| `ring` (led, WS2812) | | `fill` {"team"} or {"r","g","b"}, `color`, `off`, `set_brightness`, `progress` |
| `audio` (MAX98357A) | | `tone` {"freq","ms"}, `play` (the mode's clips as tones), `stop`, `set_volume` |
| `nfc` (PN532) | `tag` {"uid", "tag"}: a player tag's record; join cards are not forwarded | |
| `case` (tamper) | `opened`, `closed` | |

Button N stands for the game's N-th team, as on a Field Box; a colour set
in Kconfig goes into its descriptor. The enclosure switch (GPIO 47 by
default, to GND, closed while the lid is shut) is armed once it has read
closed, so a pod without one never alarms; the phone reports an opening as
`node.tamper` (reason `pod_opened`). The battery gauge's level is in IDENT
and in Pod Status.

The radio is the USB modem's own code (`main/modem/modem.c`, frames
shifted by 3): the phone sends plaintext packets with RADIO_TX, the pod
encrypts them with the game key, keeps the duty cycle and the TX power of
the channel's EU868 sub-band (`radio/radio_limits.c`), refuses a channel
that does not fit in one sub-band, dedupes and decrypts what it hears
(RADIO_RX), and measures noise when asked (MEASURE, answered by RADIO_NOISE
`0x0B`, decision PF2). The game key lives in RAM only and is forgotten
when the link that configured the radio goes (decision PF5). The board
revision (V4.3 KCT8103L by default, V4.2 GC1109) and Vext are the Field
Box's settings; the GNSS connector is not used (E21).

```
python tools/docker_fw.py pod      -> firmware/esp32/build-pod/atalaia_esp32.bin (~650 KB)
```

`sdkconfig.pod` selects `CONFIG_ATALAIA_POD_MODE` and NimBLE; CI's
`esp32-pod-build` job builds it and fails on any warning. Flash it like
the Field Box (docs/BRING_UP.md, "The I/O pod"); the pod section there
lists the checks that need the board and a phone. Code:

- `main/pod/pod.c` -- the proxy: IDENT (its `fw_version`, at most 23 bytes, is the image's
  version with the build metadata shortened when it does not fit: `pod_fw_version`, FV-5),
  EVT with ACKs and resends, CMD acted on once, the radio passthrough, Pod Status (plain C);
- `main/pod/pod_caps.c` -- the capabilities on the HAL ops (plain C);
- `main/pod/pod_ble.c` -- the GATT service's logic, UUIDs and advertising
  data (plain C); `pod_ble_nimble.c` puts it on NimBLE;
- `main/pod/pod_task.c`, `pod_main.c` -- the ESP-IDF task, USB, audio queue,
  enclosure switch, and the boot.

Tests: `test/test_pod.c` (the proxy and the capabilities, against the
shared vectors), `test/test_ble_gatt_stub.c` (`ctest -R ble_gatt_stub`: the
GATT service with the Bluetooth stack stubbed), `test/test_proxy_codec.c`
(the frames). `test/pod_host/` builds the pod's code with real AES-CCM into
a Linux program (USB and Bluetooth links as TCP sockets, the radio as UDP,
the hardware on stdin) that the app's Dart tests
(`app/test/pod/pod_host_test.dart`, `app/test/radio/pod_radio_link_test.dart`)
and the controller's end-to-end test (`controller/tests/test_pod_e2e.py`)
drive.

Not tested on a board yet (plan phase G): the USB and Bluetooth links to a
real phone, pairing, the radio on air, NFC with real cards, the keypad,
the ring, the amplifier and the enclosure switch.

## Kconfig

All pin assignments, memory tier, keypad interface, display controller
and radio settings are in `main/Kconfig.projbuild`.  Change with
`idf.py menuconfig`.  `sdkconfig.wokwi` holds the emulator's overrides;
the Field Box uses `sdkconfig.defaults` alone.

Radio-specific Kconfig options (under "Atalaia Field Box Configuration > Radio"):
- `ATALAIA_RADIO_NSS_PIN` .. `ATALAIA_RADIO_DIO1_PIN` -- SX1262 SPI and control pins
- `ATALAIA_BOARD_REV` -- Heltec V4.3 (KCT8103L FEM, default) or V4.2 (GC1109 FEM); read the chip next to the LoRa connector (BRING_UP.md)
- `ATALAIA_RADIO_FEM_EN_PIN` (2, chip enable), `ATALAIA_RADIO_VFEM_CTL_PIN` (7, the FEM's LDO, driven high), `ATALAIA_RADIO_FEM_CTX_PIN` (5, V4.3, low = LNA), `ATALAIA_RADIO_FEM_PA_PIN` (46, V4.2, high = PA) -- driven only after the SX1262 answers (`main/hal/board_fem.c`)
- `ATALAIA_VEXT_CTL_PIN` -- Vext, active low, driven low at boot (under "Board power")
- `ATALAIA_RADIO_FEM_GAIN_DB` -- FEM gain for TX power calculation (default 14)
- `ATALAIA_RADIO_ANTENNA_GAIN_DBI` -- antenna gain in dBi (default 2)
- `ATALAIA_RADIO_REGION` -- regulatory region (EU868)
- `ATALAIA_RADIO_DISABLE` -- skip radio init (kept for debugging; the Wokwi build runs with the radio enabled)

Field game options (under "Field network games"):
- `ATALAIA_STATE_INTERVAL_S` -- seconds between STATE packets in a joined game (default 15)
- `ATALAIA_BATTERY_LOW_PCT` -- send `battery.low` below this battery level (default 20; 0 = never; only with a MAX17048 gauge)
- `ATALAIA_SERIAL_JOIN` -- accept `@join`, `@joinkey`, `@tag`, `@wifi`, `@update`, `@modes`, `@forgetmodes` and `@lobby` lines on the serial console (default on)
- `ATALAIA_SERIAL_ADOPT` -- accept `@adopt-info` and `@adopt` on the serial console: USB adoption by the field controller (default on; protocol/adoption.md)
- `ATALAIA_CONSOLE_USB_INPUT` -- read the console input from the USB-C port (USB-Serial-JTAG, the Heltec V4's only USB) as well as UART0 (default on; off in the Wokwi build)
- `ATALAIA_LED_BRIGHTNESS_PCT` -- LED ring brightness at boot (default 40%; under "LEDs")
- `ATALAIA_DEV_JOIN_KEY` -- a development field join key, used only when none is stored (set in `sdkconfig.wokwi` only); a box with only this key counts as unadopted

Firmware update options (under "Firmware updates (OTA)", the Field Box only):
- `ATALAIA_OTA_RELEASE_KEYS` -- the Ed25519 public keys (64 hex digits each, up to 4) whose releases the box installs; empty (the default until the project's release key exists): every update is refused
- `ATALAIA_OTA_VARIANT` -- the variant written into the image (`box`, `box-bench`, `box-dev`); a box installs only its own variant and board
- `ATALAIA_OTA_MIN_BATTERY_PCT` -- refuse an update below this level (default 30; with a MAX17048 only)

Mode package options (under "Mode packages", the Field Box only):
- `ATALAIA_MODE_KEYS` -- the Ed25519 public keys (64 hex digits each, up to 4) that sign the mode packages a box fetches for a game; empty (the default): a join asking to fetch a missing mode is answered *no mode*, as before (`tools/mode_package.py keygen` prints the line)
- `ATALAIA_OTA_WIFI_TIMEOUT_S` -- how long to wait for the field Wi-Fi (default 20)

The firmware variant is a choice at the top of the menu: `ATALAIA_NODE_MODE`
(the Field Box, default), `ATALAIA_MODEM_MODE` (`sdkconfig.modem`) or
`ATALAIA_POD_MODE` (`sdkconfig.pod`).

USB radio modem options (under "USB radio modem"):
`ATALAIA_MODEM_LINK_USB_SERIAL_JTAG` / `ATALAIA_MODEM_LINK_UART0`,
`ATALAIA_MODEM_UART_BAUD`, `ATALAIA_MODEM_LINK_TIMEOUT_S` (default 12: the
OLED's LINK DOWN); `ATALAIA_MODEM_EPOCH_WINDOW` (default 16) for
the modem and the pod. The "On-board OLED" options apply to the modem too.

I/O pod options (under "I/O pod"): `ATALAIA_POD_BTN1_TEAM` ..
`ATALAIA_POD_BTN4_TEAM` (a button's colour; empty, the default: button N is
the game's N-th team), `ATALAIA_POD_TAMPER_PIN` (the enclosure switch,
default 47, -1 = none) and `ATALAIA_POD_TAMPER_OPEN_HIGH`,
`ATALAIA_POD_BLE` (the Bluetooth link, default on) and
`ATALAIA_POD_BLE_ENCRYPTED` (frames only on an encrypted link, default on).

GNSS options (under "GNSS"): `ATALAIA_GNSS_PWR_PIN` (34, VGNSS_Ctrl,
active low; driven high, module off, at boot), `ATALAIA_GNSS_POWER_ON`
(default off), `ATALAIA_GNSS_TX_PIN` / `ATALAIA_GNSS_RX_PIN` (38 / 39, the
ESP32's UART side), `ATALAIA_GNSS_WAKE_PIN` (40), `ATALAIA_GNSS_PPS_PIN`
(41), `ATALAIA_GNSS_RST_PIN` (42), `ATALAIA_GNSS_BAUD` (9600). Pins only:
no driver reads the module yet.

### Default pin map (Heltec V4.2 / V4.3)

Revised on 2026-10-21 so the GNSS module that comes with the V4 can use its
connector (decisions PIN-1 to PIN-8 in `docs/review/decisions-to-review.md`;
pins from Heltec's V4 pin map and V4.3.1 datasheet, cross-checked with
Meshtastic's Heltec V4 variant). The ESP32-S3R2 has only 8 GPIOs free of any
board part (3, 4, 6, 15, 16, 33, 47, 48) for 12 signals, so three board pins
are shared on purpose and button 4 is read through the keypad expander.

| Function | Before | Now | Notes |
| --- | --- | --- | --- |
| Button 1 | 4 | 4 | |
| Button 2 | 39 | 48 | 39 is the GNSS module's TX line |
| Button 3 | 33 | 44 | UART0's RX: no console input on UART0 then (USB is unaffected) |
| Button 4 | 34 | PCF8574 P7 | `ATALAIA_KP_P7_BUTTON`, read with every keypad scan |
| LED ring data | 48 | 35 | Also the board's white LED, which flickers with it |
| Display MOSI / SCK | 40 / 41 | 33 / 47 | SPI2 |
| Display CS | 42 | 1 | The board's battery-voltage ADC input, used as an output |
| Display DC | 3 | 3 | Strapping pin (JTAG source select), ignored |
| Display RST | 38 | -1 (3V3) | SWRESET command at start-up |
| Display backlight | 47 | -1 (3V3) | Always on |
| I2C SDA / SCL | 17 / 18 | 17 / 18 | OLED, PCF8574, PN532, MAX17048 |
| I2S BCLK / LRCLK / DOUT | 6 / 15 / 16 | 6 / 15 / 16 | |
| GNSS power, TX, RX, wake-up, PPS, reset | (display, buttons) | 34, 38, 39, 40, 41, 42 | The module keeps its connector; off at boot |

`sdkconfig.wokwi` keeps the emulator's own display and ring pins (its
`diagram.json`). The full list with the board-internal pins is in the
`Kconfig.projbuild` header and `hardware/field-box/README.md`;
`tools/check_wiring.py` checks the wiring diagrams against these defaults.

## Partition Table

Custom layout for 16 MB flash (`partitions.csv`):

| Partition | Size | Purpose |
|-----------|------|---------|
| nvs | 24 KB | Configuration key-value store |
| otadata | 8 KB | A/B OTA bookkeeping: which slot boots, and whether a new image has confirmed itself |
| phy_init | 4 KB | PHY calibration data |
| nvs_keys | 4 KB | Encryption keys for NVS (Phase 2; see BRING_UP.md step 0) |
| ota_0 | 2 MB | Application slot A (the USB flash writes this one) |
| ota_1 | 2 MB | Application slot B (a firmware update writes the slot not running) |
| storage | 2 MB | LittleFS: presets, modes, state, audio |

The Field Box image is 1,735,824 bytes (17% of its slot free) since firmware updates
brought the Wi-Fi station, the HTTPS client and Monocypher in (+153 KB).

## Firmware updates over the air

A field controller updates a Field Box's firmware over the field's Wi-Fi, between games
([protocol/firmware-update.md](../../protocol/firmware-update.md), decisions FU3-*). In
software and in host tests; not yet run on a real board ([BRING_UP.md](docs/BRING_UP.md),
step 10c).

- **The box decides.** `main/fw_update.c` (platform-free, run by the host tests with fakes)
  checks the offer (no game played, release keys built in, the join's field CA and addresses,
  a higher version, the battery), the release text (its exact form, the Ed25519 signature over
  the manifest with a key of `CONFIG_ATALAIA_OTA_RELEASE_KEYS`, checked with
  [Monocypher](components/monocypher/README.md) 4.0.2, the platform, the version, the size),
  the image's first bytes (`esp_app_desc_t` and the Atalaia descriptor of `main/fw_desc.c`:
  version, project, variant, board) before it opens the slot, and the size and SHA-256 of
  everything written before it sets the boot partition. Anything else aborts the slot's write.
- **Versions** compare as Semantic Versioning orders them, build metadata ignored (FV-2, FV-4):
  `0.2.0` < `0.3.0-dev` < `0.3.0-dev.9+g...` < `0.3.0-dev.10+g...` < `0.3.0-rc.1` < `0.3.0`;
  two builds of the same commit count are equal, so neither updates the other (flash by USB).
  A development build can be signed with a bench key and installed like a release
  (BRING_UP.md step 10c); its release text and image say the version with its `+g...`.
- **The ESP32 side** (`main/fw_update_esp.c`): the Wi-Fi station (`wifi_ssid`/`wifi_pass` in
  NVS: the setup portal's "Field Wi-Fi" fields, or `@wifi <ssid> <password>`), `esp_http_client`
  over HTTPS trusting only the field CA whose SHA-256 is key 13 of the box's join, `esp_ota_*`
  into the inactive slot, on its own task while the game task and the radio carry on.
- **Rollback.** `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` (`sdkconfig.defaults`, a new bootloader:
  flash it once by USB). After an update the new image runs its self-test once the radio and the
  storage are up (`fw_update_self_test`: SHA-256 and Ed25519 known answers, a release key,
  a join round trip, a Lua node) and only then confirms itself; otherwise, or if it crashes
  first, the previous image boots again.
- **Starting one:** the controller's CMD update (opcode 9) from the GM console, or
  `@update <version> <release id>` on the serial console (the same checks). Signing releases:
  [docs/RELEASE_SIGNING.md](docs/RELEASE_SIGNING.md) and `tools/firmware_release.py`.

## Mode packages fetched for a game

A Field Box that lacks a part of a game's mode gets it from its field controller, between
games, as a signed package ([protocol/mode-packages.md](../../protocol/mode-packages.md),
"Fetching missing modes"; phase 5 plan phase 13b, decisions P5E-*). In software and in host
tests; not yet run on a real board.

- **When.** A join with key 16 (`fetch_modes`) and keys 13 and 14, on a box with a mode key
  built in (`CONFIG_ATALAIA_MODE_KEYS`) and no game being played: the box takes the join as
  *fetching* (`BOX_FETCHING`), gets each missing part, then says HELLO as after any join.
  Key 17 (`forget_modes`) first forgets every package it fetched.
- **The checks** (`main/mode_package.c`, `main/mode_fetch.c`, platform-free, run by the host
  tests against `protocol/vectors/mode_package.json` and fakes): the release text's exact form
  and id, its Ed25519 signature with a mode key (then a release key) of this firmware, its kind
  and tier, never a built-in id, at most 256 KiB, room among the kept packages; the archive
  streamed into a file and hashed before any of it is read, then its canonical ustar form;
  the script loaded in a fresh sandbox with the box's Lua heap, its screens parsed, the
  composed game within the 16 KB preset buffer.
- **Storage** (`main/mode_store.c`): `/littlefs/modes/<id>/` (`node.lua`, `assets/screens/`,
  the signed `release`, the slot `fetched`), at most 8 packages and 512 KiB of archives, the
  least recently used dropped for room (never one of the joined game's parts), committed by
  renames so a failed or interrupted fetch leaves the box as it was; at boot every kept
  release is verified again with this firmware's keys. Their screens come from storage
  (`screen_template_set_fetched`).
- **Reports**: `POST /api/v1/mode-packages/report` after each part (HMAC with the game key);
  without HTTPS, `node.modes_failed` over LoRa in the game's link, which the box then leaves.
- **Console** (`ATALAIA_SERIAL_JOIN`): `@modes` lists the kept packages, `@forgetmodes`
  forgets them between games.

## IDF Component Dependencies

Listed in `main/idf_component.yml`:

- `espressif/esp_lvgl_port` -- listed but not used: the display port in
  `main/display_port.c` drives LVGL through the HAL display driver
- `lvgl/lvgl` -- v9.2 display toolkit, configured by `lvgl_conf/lv_conf.h`
- `espressif/led_strip` -- WS2812B RMT driver
- `joltwallet/littlefs` -- LittleFS VFS

Vendored in `components/`: `monocypher` (Monocypher 4.0.2, CC0-1.0 or BSD-2-Clause, for the
Ed25519 check of firmware releases; ESP-IDF 5.3's mbedTLS has no Ed25519).

The I/O pod's Bluetooth stack, NimBLE, is ESP-IDF's own `bt` component
(v5.3.2, the image's version): no managed component, nothing new in
`dependencies.lock`. Without `CONFIG_BT_ENABLED` (the Field Box, the modem)
it builds nothing.

## Built-in presets

Every mode in `modes/` but Target Windows is built into the image (`main/CMakeLists.txt`):
Bomb, Domination, Hold-All Domination, Last Stand, the Codes modifier,
the phase 3 modes Kill Confirmed, Respawn and Lives and Player Check-in, and
the Medic Kit (a role package: the controller joins a kit with the kit's id
alone, so the box loads it like any preset), and phase 4's Master and
Satellites, Hacking Terminal and VIP / Payload (a box is one of its
checkpoints; the payload is an Android prop with GPS, decision M5-6), and the
objectives package (a role package for custom scenarios, decision P4R7: a
scenario's `field.lua` on the controller sets the box up with the mode command
`setup`, so the box side never changes per scenario; picked on its own, a box
waits for a scenario), and Money Factory (a box is a factory, or a bank once
the controller's `field.lua` says so; picked on its own a factory captures and
makes money, but tags need a controller's game, decision MF-A8).
At boot the firmware stores a preset, with the defaults from its
`mode.yaml`, for each built-in mode that no stored preset uses yet (a new
or erased box and every Wokwi run get all fourteen, in that order; a box
updated to a firmware with more modes gets the new ones in free slots), and
replaces the stored script of a built-in mode when the image has a
different one (`main/builtin_presets.c`). A Field Box has no default admin
PIN: the setup portal sets it and refuses 1234 and other easy ones; bench
and Wokwi builds use 1234 when none is stored (`main/admin_pin.c`, decisions
AD-28 to AD-31: wrong PINs counted in NVS, waits of 1, 2, 4 ... 60 minutes
after five in a row, `@admin-pin` on the USB console). The keypad picker shows nine presets a
page (keys 1-9 on every page); with more than nine, `0` turns to the next
page, and the header shows the page (`CHOOSE A GAME 1/2`), so the tenth,
Master and Satellites, is the first entry of the second page (decision
M2-1), the Hacking Terminal the second, VIP / Payload ("VIP") the
third, Objectives the fourth and Money Factory the fifth. A game picked on the box gets a
new seed for the scripts' `rand()` (`esp_random()`), as every field game
does from the controller, so a Hacking Terminal sets a different puzzle each
game (decision M4-6). Target Windows is the one mode in `modes/` that is not built in: it
needs the target addon and its driver (decision P4R23, phase 4 HW2); its
screen templates are in the image, as every mode's are.

A game picked on the box ends when its timer runs out (or its mode ends it):
the box stops the script, forgets the saved state so a reboot does not
resume a finished game, shows the final screen when the mode drew none of
its own, and the next key brings the picker back, as after a field game
(`end_standalone_game()` in `main/shell.c`). Until then a reboot resumes the
game where it was (decision HB-7): `state_persist.c` writes the game's time,
timer, scores, seed and the mode's `state.node` (as JSON, up to 1 KB) to
`/state/current.bin` every second, through a temporary file renamed over it
so a power loss mid-write keeps the previous second's state, and
`node_runner_resume()` gives them back without replaying the time between
(`atalaia_node_resume_at`); an armed Bomb comes back armed with the fuse it
had left (modes/README.md, "After a power loss"). A field game resumes its
time only; its controller sets the mode up again.

A join may name a main mode with modifiers (`org.atalaia.domination+org.atalaia.codes`,
see [modes/README.md](../../modes/README.md#main-modes-modifiers-role-packages-and-scenarios)): the box
composes the stored scripts into one chunk, as the controller and the
simulator do (`main/box_game.c`). A preset holds up to 16 KB of script
(`PRESET_SOURCE_MAX`) for that; Hold-All and Last Stand boxes play their part
with no field-specific firmware code, while their `field.lua` runs on the
controller.

## Player tags (phase 3)

While a game runs, the shell polls the PN532 every 300 ms and reads each card
once per tap. A card with a player tag ([protocol/nfc-tag.md](../../protocol/nfc-tag.md))
is checked with the joined game's id and key (`box_game_tag`, through
`atalaia_tag_event_json` in the core) and reaches the mode as `nfc.tag`;
a card without one arrives as `nfc.tag` with `valid: false, reason:
"unsigned"`; a join card is still handled as a join. A game picked from the
box's own list has no game key, so its tags are refused (`no_game`).
`@tag <uid hex> [<tag payload hex>]` on the serial console does the same
without a reader (bring-up, Wokwi; `CONFIG_ATALAIA_SERIAL_JOIN`). Team
buttons now also send `team_input.press` when they go down (Kill Confirmed
and Respawn count presses).

## Phase 2: the radio and field games

Implemented in plan phase C:

- **SX1262 LoRa radio driver** -- `main/hal/esp/hal_esp_radio.c`, SPI3_HOST,
  EU868 SF7/BW125, single shared game channel (RFC 0001 Amendment 1), FEM gain
  accounting, duty-cycle tracking.
- **Radio task** -- FreeRTOS core 0 priority 3, TX/RX queues, DIO1 ISR.
- **Radio protocol** -- `main/radio/radio_protocol.c`, packet encrypt/decrypt
  with epoch persistence via NVS, per game key (RFC 0001 Amendment 9,
  proposed: the last 16 keys by an HMAC tag and 48 older ones retired, one
  atomic blob; a new game starts at epoch 1, a retired key is refused),
  per-source epoch trial on receive (HELLO and TIME searched 256 epochs up,
  within a budget; a new source's epoch provisional), nonce safety invariant with `tx_blocked` on NVS
  failure or epoch exhaustion.
- **Event log** -- `main/radio/event_log.c`, flash-backed append-only log.
- **Time sync** -- `main/radio/time_sync.c`, slew/step from TIME beacons.
- **NVS key storage** -- `main/radio/radio_nvs_esp.c`, game key and the
  epochs ("epochs"; the single "epoch" of older firmware is only read, for a
  game resumed after the update) in the "radio" NVS namespace. On production boards with an eFuse HMAC key
  burned, NVS encryption protects the key at rest; otherwise the box logs a
  warning at boot that the key is in plain NVS.

Implemented in plan phase E (decision D18): a box takes part in a field
controller's game.

- **Joining** -- `main/box_game.c`. A join payload
  ([protocol/join.md](../../protocol/join.md)) arrives on an NFC card (the
  PN532 reads the NTAG215/216 user memory: `hal_esp_nfc.c`) or as a line on
  the serial console, `@join atalaia:join:...`. Its tag is checked with the
  **field join key**, which the box gets once, when the field adopts it (next
  item). The verified payload (game key included)
  is stored in NVS, the radio tunes to the game's channel, and the box sends
  HELLO and shows "Joined game N" until the controller starts the game.
- **Adoption** -- `main/adoption.c` ([protocol/adoption.md](../../protocol/adoption.md),
  decisions AD-*): how the box gets the field join key. An **NFC field card**
  (MIME type `application/vnd.atalaia.field`: the key, the field's name and
  an 8-byte check; the console's *Adopt* tab makes it) tapped between games,
  or the **USB cable** from the field controller, which sends `@adopt-info`
  (one `ATALAIA-ADOPT {json}` line: name, MAC, state) and `@adopt <64 hex>
  [<admin PIN>|-] [<field name>]`; `@joinkey <64 hex>` and the setup
  portal's field follow the same rules. An unadopted box (none stored; a
  development key does not count) takes the first field; an adopted box takes
  the same field again and another field's key only with its admin PIN (on
  the keypad after the card, or in `@adopt`; after five wrong ones in a row
  each try waits 1, 2, 4 ... 60 minutes, counted in NVS across restarts; a
  Field Box with no admin PIN set moves nowhere: `no_pin`); nothing while a game is joined or played, and a field card tapped
  during a game is ignored, never a player tag. The screen shows ADOPTED with
  the field's name and its key's fingerprint (`XXXX-XXXX`), or asks for the
  PIN. The key stays in the "radio" NVS namespace, the name in `field_name`;
  production boxes need NVS and flash encryption and secure boot (the
  protocol document, section 2). Host tests: `test/test_adoption.c` against
  `protocol/vectors/field_card.json`. In software; the field card not yet
  read by a real PN532, the cable not yet used from a real controller.
- **Pairing by code** -- `main/box_pair.c`, `main/cpace.c` (protocol/adoption.md
  section 7, RFC 0001 Amendment 8, decisions AD-15 to AD-27): an unadopted box
  with a radio shows a 6-digit code at start ("PAIR THIS BOX", `Code: 042 137`;
  `*` gives the picker back, `#` a new code, `@pair` on the console another
  one) and offers itself in pair frames (type 10, in the clear) on
  `CONFIG_ATALAIA_RADIO_DEFAULT_CHANNEL_HZ` (869.525 MHz) every 15 s or more for
  5 minutes. A controller that the GM gives the code runs CPace
  (CPACE-X25519-SHA512 on Monocypher's X25519, Elligator 2 and SHA-512) with
  it; the box checks the controller's confirmation, opens the join key sealed
  under the run's key and adopts the field through `adoption.c`, then its field
  frames start. A failed run burns the code; three in a row make it wait a
  minute, ten stop pairing until a restart; a sid runs once; a run's secrets
  are wiped on every outcome; the box encrypts nothing itself. Host tests:
  `test/test_box_pair.c` (the CPace draft's vectors, the vectors' whole run
  byte for byte, the limits). In software and with the host box through the
  host modem; not yet on the air.
- **The game** -- on the controller's CMD start (or a TIME beacon that shows
  the game running), the box loads the mode for its role with the join's
  teams, parameters, node id and seed; CMD pause, resume and end, TIME, and
  the buttons drive it. `set_owner` and `message` reach the mode as the input
  events `cmd.set_owner` and `gm.message`, and a mode command (opcode 8: a
  medic kit's refill, the controller's count of a player's heals) as
  `cmd.mode`. At the end the stored join is
  erased, and the key in RAM once the last events are acknowledged.
- **The radio link** -- `main/radio/field_link.c` sends every event the mode
  emits (normal and critical ones wait for an ACK, are resent every 3 s in a
  new packet, and are written to the flash log first), STATE every
  `CONFIG_ATALAIA_STATE_INTERVAL_S` seconds and after a capture (owner, game
  state, game time, points gained per team, epoch), follows the controller
  with the highest term, applies the time sync (slew, or a step ahead, or
  holding the clock), and relays every authenticated packet once.
- **Battery** -- with a MAX17048 gauge, HELLO and STATE carry its level, and
  in a joined game the box reads it every 10 s and sends one `battery.low`
  (telemetry: one packet, no ACK, the level in `percent`) when it falls below
  `CONFIG_ATALAIA_BATTERY_LOW_PCT`, again only after it has come 5 points
  back above it (`main/box_game.c`, decision FU1-6). A box without a gauge
  sends neither. The controller logs `battery.low` from the STATE level too
  if the box's own does not arrive. In software and on the host box only:
  the bench board has no gauge fitted.
- **After a reboot** -- the stored join brings the box back: a new epoch
  (that game's last + 1), HELLO, the saved game state, `node.rebooted`, and
  the unacknowledged events from the flash log.
- **Screens through a game** -- (decisions BN-6, BN-10 to BN-14) a free
  adopted box shows "Ready / next game" from boot (a key brings the game
  picker); joined or invited, "Waiting: the game hasn't started"; at the start
  "Game on" until the mode draws (a zone: "Neutral: hold to capture", in
  Portuguese "Livre: mantém premido", or the
  team holding it, never the Bomb's "standby"); the mode's game over; then
  "Ready" again. In the field's language, English, European Portuguese, German or
  Traditional Chinese as written in Taiwan (join key 15 `zh-tw` or `zh-hant`, kept between
  games; `main/box_text.c`, fonts with the Portuguese and German letters and the Chinese
  letters the box's texts use, from Noto Sans TC, in `main/fonts/`, `tools/gen_box_fonts.py`,
  whose `--check` fails when a text uses a letter the fonts lack; decision P5K-3). Chinese
  names in a game's data (teams, objectives, presets typed in Chinese) are not in the fonts:
  the box's own screens draw them as empty boxes, the modes' templates as `?` (P5K-5).
- **Between games** -- `main/box_lobby.c` ([protocol/field-frames.md](../../protocol/field-frames.md),
  RFC 0001 Amendment 7, proposed). A box with a field join key has an 8-byte
  random **device id**, made once and kept in NVS (`device_id`), which its
  HELLO carries (key 10). With no game, or once its game is over, it
  announces itself in **field frames** (type 9, game id 0, sealed with
  AES-CCM under HKDF-SHA256 of the join key) on its last game's channel: 2-20 s
  after the game ends, then about every 72 s on 869.525 MHz (2 % of the
  sub-band's duty cycle, at least a minute apart), and within 3 s of a
  controller's DISCOVER. Its announcements carry a token that changes every
  10 minutes and whenever it accepts an invite. An INVITE for its device id
  and its current or previous token, in 1-3 parts, brings a join payload,
  which goes through the card's checks; a box in a game answers "busy", an
  old token gets no answer, a game it played to the end is refused. The box
  answers how it went, and joins: "Invited / game: role" on its screen. In a
  game it takes a **GAME_OVER** (kind 4) for its game id and its game key's
  tag, which a controller sends when a game ends, also one whose key it lost in
  a restart: the box ends the game as on CMD end; another game's, or one for
  its game id under another key (played back), changes nothing (decisions
  OT-7, OT-13; no timeout ever ends a game on the box). 30 s
  after a game ends the final screen gives way to "Ready / next game". `@lobby`
  on the serial console prints the device id, whether the box is free, its
  channel and its invites. A field frame's nonce is the device id's pseudonym,
  a boot count kept in NVS (`ff_boot`, raised and stored before the first
  frame of every run) and a frame count: never random (decision RJ-15). The
  device id and tokens come from a generator seeded at boot with true entropy
  (`bootloader_random_enable()`, before any ADC or I2S driver starts) and the
  board's MAC.
- **Tests** -- the host tests (`test/test_field_link.c`,
  `test/test_box_game.c`, `test/test_serial_console.c`) run this code with
  the stub HAL; `test/box_host/` builds it into a Linux program on a UDP
  "air" (team buttons, keypad presses, `@tag` player tags and the battery
  gauge's reading on its stdin), which the controller's end-to-end tests
  (`controller/tests/test_box_e2e.py`) play whole games with, through the
  host modem. `wokwi/join.scenario.yaml` joins a game in the emulator.
  `test/test_box_game.c` also runs the box between games (announcements, an
  invite in two parts, DISCOVER, the ready screen, every refusal, a replayed
  invite), and the host box (`--announce-ms N` for quick announcements) is
  invited into a second game by the controller in `test_box_e2e.py`.

Still pending:

- Running any of it on the radio boards (plan phase F): the SX1262 link,
  the PN532 reading real join cards, NVS encryption on a provisioned box,
  an invite between games over the air (BRING_UP.md, step 3b).
- Joining over Wi-Fi from the GM console (decision E3).
- Running a firmware update over the air on a real board (built and host-tested:
  [Firmware updates](#firmware-updates-over-the-air)).
- A GNSS driver for the module on the board's connector (its pins and power
  control are in Kconfig; it stays off until a mode needs a position)

## Radio Region

The firmware refuses to transmit until a region is set (EU868 for
Europe, US915 for the Americas) and enforces power and duty-cycle
limits.
