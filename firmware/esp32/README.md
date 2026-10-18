<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# ESP32 Firmware

ESP-IDF firmware for Atalaia Field Boxes running on ESP32-S3.

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
  |     +-- poll buttons/keypad/serial console; NFC join cards when idle
  |     +-- atalaia_node_advance()
  |     +-- game_timer_tick()
  |     +-- state_persist_save() (every 1 s)
  |     +-- command_dispatch()
  +-- lvgl_task (core 1, priority 4, 5 ms)
  |     +-- display_port_init() (LVGL 9.2, DMA flush)
  |     +-- screen_render()
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
EU868 band, SF7/BW125, single shared game channel (default 869.525 MHz
in the g2 sub-band, 10% duty cycle, 500 mW ERP).  The channel is
configurable per game via CONFIG message
(`CONFIG_ATALAIA_RADIO_DEFAULT_CHANNEL_HZ` in Kconfig).  Neighbouring
games use different channels within the sub-band or in other sub-bands.

The FEM (front-end module) on the Heltec V4.3 provides ~14 dB of gain.
TX power is calculated by `radio_power.h` to comply with EU868 g2 ERP
limits (27 dBm ERP), accounting for FEM and antenna gain (Kconfig
`ATALAIA_RADIO_FEM_GAIN_DB` and `ATALAIA_RADIO_ANTENNA_GAIN_DBI`).

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

## Build

Everything builds in Docker (Docker Desktop must be running); no compiler is
needed on the host. `tools/docker_fw.py` works from `cmd`, PowerShell or
bash, from the repository folder:

```
python tools/docker_fw.py build                   firmware for the Field Box -> firmware/esp32/build/
python tools/docker_fw.py wokwi                   Wokwi emulator variant -> firmware/esp32/build-wokwi/
python tools/docker_fw.py modem                   USB radio modem variant -> firmware/esp32/build-modem/
python tools/docker_fw.py test                    host tests and screen reference images
python tools/docker_fw.py test --update-screens   accept changed screens as the new references
```

`build`, `wokwi` and `modem` use the `espressif/idf:v5.3.2` image, like CI's
`esp32-build` and `esp32-modem-build` jobs. `test` runs CI's `firmware-test` commands in the
`atalaia-dev` image. With a toolchain of your own, the same commands are:

```sh
cd firmware/esp32 && idf.py set-target esp32s3 && idf.py build
cmake -S firmware/esp32/test -B /tmp/fw-test -DCMAKE_BUILD_TYPE=Debug
cmake --build /tmp/fw-test && ctest --test-dir /tmp/fw-test --output-on-failure
```

## Screens

The screen templates (`main/screen_renderer.c`, ADR-P1-2) are C functions
that build LVGL 9.2 widget trees for the 320x240 TFT: `standby`,
`countdown`, `defused`, `exploded`, `final_score`, `paused`, `status`, the
preset picker (`pin_entry`, `preset_select`, `timer_adjust`,
`start_confirm`) and `wifi_setup`. Each template is built once and then
patched with new data, so a countdown only changes one label per second.

The host tests build the same code against the same LVGL release (9.2.2,
fetched from its GitHub tag and checked against `dependencies.lock`) and the
same `lvgl_conf/lv_conf.h`, render every template into memory, and compare
the result pixel by pixel with the PNG files in
[`test/screens/`](test/screens/). They also fail when a widget is clipped by
the screen or two labels overlap. After changing a screen on purpose, run
`python tools/docker_fw.py test --update-screens` (or set
`ATALAIA_UPDATE_SCREENS=1` for `ctest`), look at every changed PNG, and
commit them with the change. Rendered images land in
`firmware/esp32/build-test/screens/` (or `<build>/screens/` with `ctest`),
next to a `.diff.png` for each mismatch.

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
enforces the duty cycle, and keeps the game key in RAM only; it has no
Lua, screens or presets (~280 KB image). The log console stays on UART0
only, so it never mixes with the frames, and the task watchdog reboots a
hung modem. `CONFIG_ATALAIA_MODEM_LINK_UART0` switches the link to UART0
for boards with a USB-UART bridge.

`main/modem/modem.c` and `modem_framing.c` are plain C: the host tests
(`test/test_modem.c`, `test/test_modem_framing.c`) run them with the
stub crypto, and `test/modem_host/` builds them with real AES-CCM into a
Linux program that the field controller's tests talk to over TCP, with
UDP standing in for the radio.

Not yet tested on a board: the USB-Serial-JTAG link, the TX power and
the radio timing need the parts (plan phase F).

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
- `ATALAIA_SERIAL_JOIN` -- accept `@join` and `@joinkey` lines on the serial console (default on)
- `ATALAIA_CONSOLE_USB_INPUT` -- read the console input from the USB-C port (USB-Serial-JTAG, the Heltec V4's only USB) as well as UART0 (default on; off in the Wokwi build)
- `ATALAIA_LED_BRIGHTNESS_PCT` -- LED ring brightness at boot (default 40%; under "LEDs")
- `ATALAIA_DEV_JOIN_KEY` -- a development field join key, used only when none is stored (set in `sdkconfig.wokwi` only)

USB radio modem options (under "USB radio modem"): `ATALAIA_MODEM_MODE`,
`ATALAIA_MODEM_LINK_USB_SERIAL_JTAG` / `ATALAIA_MODEM_LINK_UART0`,
`ATALAIA_MODEM_UART_BAUD`, `ATALAIA_MODEM_EPOCH_WINDOW` (default 16).

Default pin map avoids all Heltec V4.3 board-internal pins.
See `Kconfig.projbuild` header and `hardware/field-box/README.md`.

## Partition Table

Custom layout for 16 MB flash (`partitions.csv`):

| Partition | Size | Purpose |
|-----------|------|---------|
| nvs | 24 KB | Configuration key-value store |
| otadata | 8 KB | A/B OTA bookkeeping |
| phy_init | 4 KB | PHY calibration data |
| nvs_keys | 4 KB | Encryption keys for NVS (Phase 2; see BRING_UP.md step 0) |
| ota_0 | 2 MB | Application slot A |
| ota_1 | 2 MB | Application slot B |
| storage | 2 MB | LittleFS: presets, modes, state, audio |

## IDF Component Dependencies

Listed in `main/idf_component.yml`:

- `espressif/esp_lvgl_port` -- listed but not used: the display port in
  `main/display_port.c` drives LVGL through the HAL display driver
- `lvgl/lvgl` -- v9.2 display toolkit, configured by `lvgl_conf/lv_conf.h`
- `espressif/led_strip` -- WS2812B RMT driver
- `joltwallet/littlefs` -- LittleFS VFS

## Built-in presets

On a box with an empty preset store (a new or erased box, and every Wokwi
run), the firmware stores two presets: Bomb and Domination, with the
defaults from their `mode.yaml`. The mode scripts come from `modes/` at
build time. The default admin PIN is 1234 until the setup portal sets one.

## Phase 2: the radio and field games

Implemented in plan phase C:

- **SX1262 LoRa radio driver** -- `main/hal/esp/hal_esp_radio.c`, SPI3_HOST,
  EU868 SF7/BW125, single shared game channel (RFC 0001 Amendment 1), FEM gain
  accounting, duty-cycle tracking.
- **Radio task** -- FreeRTOS core 0 priority 3, TX/RX queues, DIO1 ISR.
- **Radio protocol** -- `main/radio/radio_protocol.c`, packet encrypt/decrypt
  with epoch persistence via NVS, per-source epoch trial on receive, nonce
  safety invariant with `tx_blocked` on NVS failure or epoch exhaustion.
- **Event log** -- `main/radio/event_log.c`, flash-backed append-only log.
- **Time sync** -- `main/radio/time_sync.c`, slew/step from TIME beacons.
- **NVS key storage** -- `main/radio/radio_nvs_esp.c`, game key and epoch
  in the "radio" NVS namespace. On production boards with an eFuse HMAC key
  burned, NVS encryption protects the key at rest; otherwise the box logs a
  warning at boot that the key is in plain NVS.

Implemented in plan phase E (decision D18): a box takes part in a field
controller's game.

- **Joining** -- `main/box_game.c`. A join payload
  ([protocol/join.md](../../protocol/join.md)) arrives on an NFC card (the
  PN532 reads the NTAG215/216 user memory: `hal_esp_nfc.c`) or as a line on
  the serial console, `@join atalaia:join:...`. Its tag is checked with the
  **field join key**, which the box gets once: on the setup portal's optional
  "field join key" field, or with `@joinkey <64 hex digits>` on the serial
  console while no game is joined. The verified payload (game key included)
  is stored in NVS, the radio tunes to the game's channel, and the box sends
  HELLO and shows "Joined game N" until the controller starts the game.
- **The game** -- on the controller's CMD start (or a TIME beacon that shows
  the game running), the box loads the mode for its role with the join's
  teams, parameters, node id and seed; CMD pause, resume and end, TIME, and
  the buttons drive it. `set_owner` and `message` reach the mode as the input
  events `cmd.set_owner` and `gm.message`. At the end the stored join is
  erased, and the key in RAM once the last events are acknowledged.
- **The radio link** -- `main/radio/field_link.c` sends every event the mode
  emits (normal and critical ones wait for an ACK, are resent every 3 s in a
  new packet, and are written to the flash log first), STATE every
  `CONFIG_ATALAIA_STATE_INTERVAL_S` seconds and after a capture (owner, game
  state, game time, points gained per team, epoch), follows the controller
  with the highest term, applies the time sync (slew, or a step ahead, or
  holding the clock), and relays every authenticated packet once.
- **After a reboot** -- the stored join brings the box back: a new epoch,
  HELLO, the saved game state, `node.rebooted`, and the unacknowledged events
  from the flash log.
- **Tests** -- the host tests (`test/test_field_link.c`,
  `test/test_box_game.c`, `test/test_serial_console.c`) run this code with
  the stub HAL; `test/box_host/` builds it into a Linux program on a UDP
  "air", which the controller's end-to-end tests
  (`controller/tests/test_box_e2e.py`) play whole games with, through the
  host modem. `wokwi/join.scenario.yaml` joins a game in the emulator.

Still pending:

- Running any of it on the radio boards (plan phase F): the SX1262 link,
  the PN532 reading real join cards, NVS encryption on a provisioned box.
- Joining over Wi-Fi from the GM console (decision E3).
- A/B OTA updates with Ed25519 signatures
- GNSS module support (GPIO 38-42 currently used for peripherals)

## Radio Region

The firmware refuses to transmit until a region is set (EU868 for
Europe, US915 for the Americas) and enforces power and duty-cycle
limits.
