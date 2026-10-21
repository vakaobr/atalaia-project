<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Field Box

The main Atalaia prop.  Status: firmware done, hardware pending: no box has
been built from this design yet.

**To build one, follow the [build manual](BUILD.md).** It has the tools,
sourcing notes, enclosure preparation, step-by-step wiring, battery safety,
the first flash and troubleshooting. The wiring diagrams are generated from
text sources in [`wiring/`](wiring/) and checked against the firmware's pin
defaults:

- [Signals and 3.3 V](wiring/field-box-wiring.svg) ([PNG](wiring/field-box-wiring.png))
- [Power](wiring/field-box-power.svg) ([PNG](wiring/field-box-power.png))

## Main Board

**Heltec WiFi LoRa 32 V4** (bare board, 863-928 MHz), revision **V4.2 or
V4.3**.

- ESP32-S3R2: dual-core Xtensa LX7, 240 MHz, 2 MB PSRAM, 16 MB flash.
- SX1262 LoRa radio behind a front-end module (FEM) with a power amplifier
  and receive amplifier: GC1109 on the V4.2, KCT8103L on the V4.3. The two
  are driven differently, so the firmware must know which one the board has
  (`ATALAIA_BOARD_REV`, see [BUILD.md](BUILD.md#6-board-revision-and-antennas)).
- 0.96" OLED, 128x64 (SSD1306, I2C on GPIO 17/18).
- Native USB-C (the ESP32-S3's own USB serial port; no USB-serial bridge
  chip): power, charging, flashing and the log.
- Single-cell LiPo socket, solar input (4.4-6 V), GNSS connector.
- Two IPEX 1.0 (U.FL) antenna connectors: one for LoRa, one for 2.4 GHz.
- About 52 x 25 mm.

Buy the bare board (no shell) -- the Field Box has its own enclosure.
Kits may include an 868 MHz antenna, a 1S LiPo and a GNSS module: the GNSS
module plugs into the board's GNSS connector, which keeps all its pins
(GPIO 34 and 38-42) in this pin map. The firmware keeps it switched off until
a mode needs a box's position (no GNSS driver yet).

The high-power board's rated output (about 27-28 dBm conducted) is more than
the EU868 limits allow with an antenna. The firmware caps it using an
assumed FEM gain of 14 dB (`ATALAIA_RADIO_FEM_GAIN_DB`) and the antenna gain
(`ATALAIA_RADIO_ANTENNA_GAIN_DBI`); that assumption is checked with a
measurement at bring-up (BRING_UP.md step 10). Never lower either setting,
and do not use a box in a game before that check has been done.

> **Warning:** Never power up or transmit without the LoRa antenna
> connected.  The FEM's power amplifier can be damaged by an open antenna
> port.

The Heltec V3 (ESP32-S3FN8, 8 MB flash, no PSRAM) works as a
Reduced-tier option with smaller Lua heap and a monochrome OLED.

## Bill of Materials (per box)

Generic descriptions; [BUILD.md](BUILD.md#2-parts-and-sourcing) has the specs
to check, alternatives and what to avoid.

| Part | Recommended | Notes |
|------|-------------|-------|
| Main board | Heltec WiFi LoRa 32 V4 (V4.2 or V4.3) bare board, 863-928 MHz | Identify the revision before wiring (BUILD.md, section 6) |
| 2.4 GHz antenna | IPEX 1.0 (U.FL) FPC antenna, 2.4 GHz | **Required.** The bare board kit includes only the LoRa antenna; Wi-Fi and BLE (captive-portal setup) will barely work without this. |
| LoRa antenna | 868 MHz antenna, 2 dBi or less | The kit antenna (IPEX lead) is fine behind the plastic wall of the box. For more range: an SMA bulkhead with an IPEX-to-SMA pigtail and an outside antenna. A higher-gain antenna needs `ATALAIA_RADIO_ANTENNA_GAIN_DBI` changed to stay legal |
| Team buttons | 2 (up to 4) x 60 mm arcade buttons, 5 V LED versions | Active-low, common ground; buttons 1-3 on GPIOs, button 4 on the keypad expander's spare pin P7. The firmware does not drive the button LEDs: they light from the 5 V rail whenever the box is on |
| Keypad | 3x4 matrix membrane keypad | Codes, arming, admin PIN |
| Keypad expander | PCF8574 (or PCF8574A) I2C I/O expander module | Addr 0x20-0x27 (a PCF8574A: 0x38-0x3F), found by the firmware; reads the keypad (P0-P6) and team button 4 (P7) over the board I2C bus, which frees 8 GPIOs. Powered from 3V3, never 5V (its pull-ups would put 5 V on the bus) |
| Display | 2.8" ILI9341 or ST7789 SPI TFT (320x240) | Kconfig selects the controller. Its RESET and backlight (LED) pins go to 3V3 |
| LED ring | WS2812B ring, 24 LEDs, 5 V | Data through the level shifter below; 1000 uF capacitor at the ring |
| Level shifter | 74AHCT125 (or 74HCT125), DIP-14, with socket | 3.3 V data to 5 V for the LED ring. Not 74HC125 (needs a higher input voltage) |
| Interconnect board | Perfboard about 5 x 7 cm, pin headers, 330 ohm resistor | Carries the 3V3, GND, SDA, SCL and 5 V rails and the level shifter |
| NFC reader | PN532 breakout (I2C mode) | Addr 0x24; shares the board I2C bus |
| Audio amp | MAX98357A I2S breakout + 4-8 ohm 3 W speaker | Optional; drop to free 3 GPIOs |
| Battery | 1S Li-ion: 2 x protected 18650 in parallel (or a 1S2P pack with BMS), 3.0-4.2 V | **One cell in series only.** The board's battery socket, its charger and the MAX17048 are single-cell parts: a 2S (7.4 V) pack destroys them. The kit's 3000 mAh LiPo is also 1S and can serve a first prototype (BUILD.md, section 7) |
| Battery gauge | MAX17048 I2C breakout | Addr 0x36; shares the board I2C bus. The firmware reads battery level only from this gauge (not from the board's own ADC divider) |
| 5 V supply | Boost converter, 3.0-4.2 V in, 5 V at 2.5 A or more out | Feeds the LED ring, the amplifier and the button LEDs |
| Power protection | Inline fuse holder with 5 A fuse; Schottky diode 3 A+ (e.g. 1N5822); main switch SPST 5 A DC, covered or recessed | See [BUILD.md](BUILD.md#7-power-and-battery-safety) |
| Splices | Lever splice connectors, 3- and 4-way | Battery and 5 V distribution, no soldering |
| USB | Panel-mount USB-C extension with cap, USB 2.0 data | Charging, flashing and the serial console without opening the box |
| Enclosure | IP65 junction box (~200x150x100 mm), bright colour | Cable glands, pressure-equalising vent, "GAME PROP" label |
| GNSS (optional) | The GNSS module that comes in Heltec's V4 kits, with its SH1.25 8-pin cable | Plugs into the board's GNSS connector (GPIO 34, 38-42). Kept off by the firmware until a GPS-based mode uses it; no driver yet |

## Pin Assignments (Default Kconfig -- Heltec V4.3)

These are the defaults in `firmware/esp32/main/Kconfig.projbuild`; that file
is the reference if the two ever disagree.

Board-internal pins (do not reassign): GPIO 0, 2, 7, 8-14, 17-18,
19-20, 21, 26-32, 36, 37, 43; also GPIO 5 (front-end module on the V4.3)
and GPIO 46 (front-end module on the V4.2): wire neither, whichever
revision you have. GPIO 34 and 38-42 belong to the GNSS connector and its
module: wire nothing else to them.

Three board pins are shared on purpose, each for one use only (the wiring
check refuses any other): GPIO 1, the board's battery-voltage input, is the
display's CS (an output; the firmware reads the battery from the MAX17048);
GPIO 35, the board's white LED, carries the LED ring's data (the white LED
flickers faintly with it); GPIO 44, UART0's receive line, is button 3 (the
box then takes no console input on UART0; the USB console is unaffected).
The ESP32-S3R2 has 8 GPIOs free of any board part (3, 4, 6, 15, 16, 33, 47,
48) for 12 signals, hence these and button 4 on the keypad expander
(decisions PIN-1 to PIN-5 in `docs/review/decisions-to-review.md`).

### SX1262 Radio Pins (Board-Internal)

| Function   | GPIO | Notes |
|------------|------|-------|
| SPI NSS    | 8    | SPI3_HOST chip select |
| SPI SCK    | 9    | SPI3_HOST clock |
| SPI MOSI   | 10   | SPI3_HOST data out |
| SPI MISO   | 11   | SPI3_HOST data in |
| RST        | 12   | Radio reset (active low pulse) |
| BUSY       | 13   | SX1262 busy indicator (input) |
| DIO1       | 14   | ISR: TX_DONE / RX_DONE / TIMEOUT |
| FEM_EN     | 2    | Front-end module enable (board-internal) |
| VFEM_Ctrl  | 7    | FEM voltage rail control (board-internal) |

> **Antenna note:** The LoRa antenna MUST be connected to the LoRa
> IPEX connector before power-on. The 28 dBm FEM on the high-power
> V4.3.1 variant can be permanently damaged by transmitting into an
> open antenna port. Standard-power boards tolerate it, but the
> antenna should still be connected for correct radio operation.

### Peripheral Pins

| Function       | GPIO | Notes |
|----------------|------|-------|
| Button 1       | 4    | Active low, internal pull-up |
| Button 2       | 48   | Moved from GPIO 39 (the GNSS module's TX line) on 2026-10-21 |
| Button 3       | 44   | Optional. UART0's RX pin: no console input on UART0 with it. Unwired, it reads as never pressed (internal pull-up) |
| Button 4       | PCF8574 P7 | Optional. On the keypad expander's spare pin (`ATALAIA_KP_P7_BUTTON`), read with every keypad scan |
| Keypad         | I2C  | PCF8574 at 0x20 on the board bus: rows on P0-P3, columns on P4-P6 |
| LED Data       | 35   | WS2812B, single wire (RMT), through the 74AHCT125 level shifter. Also the board's white LED, which flickers with it |
| Display MOSI   | 33   | SPI2 |
| Display CLK    | 47   | |
| Display CS     | 1    | The board's battery-voltage input, used as an output |
| Display DC     | 3    | Data/Command (strapping pin, safe: JTAG source select, ignored) |
| Display RST    | -1   | Wired to 3V3; the firmware resets the panel with a command |
| Display BL     | -1   | Wired to 3V3: on whenever the box is (it draws more than a GPIO should give) |
| I2C SDA        | 17   | Shared bus: on-board OLED, PCF8574, PN532, MAX17048 |
| I2C SCL        | 18   | |
| I2S BCLK       | 6    | MAX98357A |
| I2S LRCLK      | 15   | |
| I2S DOUT       | 16   | |
| GNSS power     | 34   | Board-internal (VGNSS_Ctrl, low = on). The firmware drives it high (module off) at boot |
| GNSS TX        | 38   | Board-internal: the ESP32's UART TX to the module's RX |
| GNSS RX        | 39   | Board-internal: the module's TX to the ESP32's UART RX |
| GNSS wake-up   | 40   | Board-internal |
| GNSS PPS       | 41   | Board-internal: one pulse per second once the module has a fix |
| GNSS reset     | 42   | Board-internal, active low |
| Vext Ctrl      | 36   | Board-internal. The firmware switches Vext on at boot (on-board OLED, LoRa front end); the standard build powers its peripherals from the board's 3V3 pin |
| ADC Ctrl       | 37   | Board-internal; gates the board's Vbat divider on GPIO 1, which the Field Box uses as the display's CS: the firmware leaves it alone |

The Wokwi emulator wires the same display, two buttons and the LED ring on
pins of its own development board (`sdkconfig.wokwi`), and puts the keypad on
GPIOs instead of the PCF8574 (`firmware/esp32/docs/WOKWI.md`).

## Assembly Sequence

The full sequence, with checks after each step, is in [BUILD.md](BUILD.md).
In short:

1. Identify the board revision (V4.2 or V4.3), then fit both antennas
   (LoRa first) before anything is ever powered.
2. Build the interconnect board (rails, 74AHCT125, 330 ohm resistor).
3. Wire the power path without the board: battery, fuse, diode, switch,
   splices, boost converter set to 5.0-5.2 V.
4. Wire the buttons (GPIO 4, 48 and 44; button 4 on the PCF8574's P7), the
   keypad through the PCF8574 (rows P0-P3, columns P4-P6), the display
   (MOSI 33, CLK 47, CS 1, DC 3; RESET and LED to 3V3), the I2C devices on
   SDA 17 / SCL 18, the LED data (GPIO 35) through the level shifter, and the
   I2S amplifier (BCLK 6, LRCLK 15, DOUT 16). The GNSS module, if you fit
   it, plugs into the board's GNSS connector.
5. Check the polarity of the board's battery lead with a meter, then
   connect it.
6. Flash the firmware and continue with
   [`firmware/esp32/docs/BRING_UP.md`](../../firmware/esp32/docs/BRING_UP.md).
