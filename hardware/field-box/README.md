<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Field Box

The main Atalaia prop.  Status: firmware done, hardware pending.

## Main Board

**Heltec WiFi LoRa 32 V4.3** (bare board, 863-928 MHz, standard power).

- ESP32-S3R2: dual-core Xtensa LX7, 240 MHz, 2 MB PSRAM, 16 MB flash.
- SX1262 LoRa radio (reserved for Phase 2; keep its pins free).
- 0.96" OLED (SSD1306, I2C on GPIO 17/18).
- USB-C, LiPo battery connector, solar connector.
- Two IPEX 1.0 (U.FL) antenna connectors: one for LoRa, one for 2.4 GHz.

Buy the bare board (no shell) -- the Field Box has its own enclosure.
Prefer the standard-power variant for EU868 (25 mW ERP limit on most
channels).  The high-power V4.3.1 with FEM is also compatible.

> **Warning:** Never power up or transmit without the LoRa antenna
> connected.  The 28 dBm FEM on the high-power variant can be damaged
> by an open antenna port.

The Heltec V3 (ESP32-S3FN8, 8 MB flash, no PSRAM) works as a
Reduced-tier option with smaller Lua heap and a monochrome OLED.

## Bill of Materials (per box)

| Part | Recommended | Notes |
|------|-------------|-------|
| Main board | Heltec WiFi LoRa 32 V4.3 bare board, 863-928 MHz | Standard power for EU868 |
| 2.4 GHz antenna | IPEX 1.0 (U.FL) FPC antenna, 2.4 GHz | **Required.** The bare board kit includes only the LoRa antenna; Wi-Fi and BLE (captive-portal setup) will barely work without this. |
| LoRa antenna | Included with the board (863-928 MHz) | Match the region |
| Team buttons | 2 (up to 4) x 60 mm arcade buttons with built-in LEDs | Active-low; common ground |
| Keypad | 3x4 matrix membrane keypad | Codes, arming, admin PIN |
| Keypad expander | PCF8574 I2C I/O expander module | Addr 0x20; reads the keypad over the board I2C bus, which frees 7 GPIOs |
| Display | 2.8" ILI9341 or ST7789 SPI TFT (320x240) | Kconfig selects the controller |
| LED ring | WS2812B ring (24 LEDs typical) | 5V data with 3.3V GPIO works at short distances; add a level shifter for reliability |
| NFC reader | PN532 breakout (I2C mode) | Addr 0x24; shares the board I2C bus |
| Audio amp | MAX98357A I2S breakout + 3W speaker | Optional; drop to free 3 GPIOs |
| Battery | 2S 18650 pack (7.4V nominal) with BMS | Or single 3.7V 18650 via USB-C |
| Battery gauge | MAX17048 I2C breakout | Addr 0x36; shares the board I2C bus; optional if the board's ADC divider (GPIO 1/37) is sufficient |
| Enclosure | IP65 junction box (~200x150x100 mm) | Cable glands for buttons and keypad |
| Optional | u-blox M10 GNSS module | Connects to the GNSS header (GPIO 38-42); not in Phase 1 |

## Pin Assignments (Default Kconfig -- Heltec V4.3)

These are the defaults in `firmware/esp32/main/Kconfig.projbuild`; that file
is the reference if the two ever disagree.

Board-internal pins (do not reassign): GPIO 1, 2, 7, 8-14, 17-18,
19-20, 21, 35, 36, 37, 43-44.

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
| Button 2       | 5    | |
| Button 3       | 33   | Optional; -1 in Kconfig for 2-team boxes |
| Button 4       | 34   | Optional |
| Keypad         | I2C  | PCF8574 at 0x20 on the board bus: rows on P0-P3, columns on P4-P6 |
| LED Data       | 48   | WS2812B, single wire (RMT) |
| Display MOSI   | 40   | GNSS header; SPI |
| Display CLK    | 41   | GNSS header |
| Display CS     | 42   | GNSS header |
| Display DC     | 3    | Data/Command (JTAG strapping pin; safe) |
| Display RST    | 38   | GNSS header; -1 in Kconfig if RST is tied to Vext instead |
| Display BL     | 47   | Backlight on/off |
| I2C SDA        | 17   | Shared bus: on-board OLED, PCF8574, PN532, MAX17048 |
| I2C SCL        | 18   | |
| I2S BCLK       | 6    | MAX98357A |
| I2S LRCLK      | 15   | |
| I2S DOUT       | 16   | |
| Vext Ctrl      | 36   | Board-internal; powers the external peripherals (see BRING_UP.md step 2) |
| ADC Ctrl       | 37   | Board-internal; enable before reading Vbat ADC (GPIO 1) |

The Wokwi emulator wires the same display, buttons and LED ring, and puts
the keypad on GPIOs instead of the PCF8574
(`firmware/esp32/docs/WOKWI.md`).

## Assembly Sequence

1. Solder or socket the Heltec V4.3 bare board inside the enclosure.
2. Connect the 2.4 GHz IPEX FPC antenna to the WiFi connector.
   Connect the LoRa antenna to the LoRa connector.
3. Wire team buttons to GPIO 4-5 (and 33-34 for teams 3-4; common
   ground, active-low).
4. Wire the keypad to the PCF8574 (rows to P0-P3, columns to P4-P6) and
   the PCF8574 to the I2C bus (SDA 17, SCL 18, address pins for 0x20).
5. Connect WS2812B LED ring data to GPIO 48 (add a 3.3V-to-5V
   level shifter for runs longer than ~30 cm).
6. Wire SPI display (MOSI 40, CLK 41, CS 42, DC 3, RST 38, BL 47).
7. Connect PN532 NFC reader to I2C bus (SDA 17, SCL 18).
   Set the PN532 DIP switches to I2C mode.
8. Wire MAX98357A I2S amplifier (BCLK 6, LRCLK 15, DOUT 16).
9. If using external MAX17048: connect to I2C bus (SDA 17, SCL 18).
10. Wire battery pack to the board's JST connector (observe polarity).
11. Route cables through cable glands; seal the enclosure.
