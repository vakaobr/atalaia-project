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
| Team buttons | 2 x 60 mm arcade buttons with built-in LEDs | Active-low; common ground |
| Keypad | 3x4 matrix membrane keypad | Codes, arming, admin PIN |
| Display | 2.8" ILI9341 or ST7789 SPI TFT (320x240) | Kconfig selects the controller |
| LED ring | WS2812B ring (24 LEDs typical) | 5V data with 3.3V GPIO works at short distances; add a level shifter for reliability |
| NFC reader | PN532 breakout (I2C mode) | Addr 0x24; shares the board I2C bus |
| Audio amp | MAX98357A I2S breakout + 3W speaker | Optional; drop to free 3 GPIOs |
| Battery | 2S 18650 pack (7.4V nominal) with BMS | Or single 3.7V 18650 via USB-C |
| Battery gauge | MAX17048 I2C breakout | Addr 0x36; shares the board I2C bus; optional if the board's ADC divider (GPIO 1/37) is sufficient |
| Enclosure | IP65 junction box (~200x150x100 mm) | Cable glands for buttons and keypad |
| Optional | u-blox M10 GNSS module | Connects to the GNSS header (GPIO 38-42); not in Phase 1 |

## Pin Assignments (Default Kconfig -- Heltec V4.3)

Board-internal pins (do not reassign): GPIO 1, 2, 7, 8-14, 17-18,
19-20, 21, 35, 36, 37, 43-44.

| Function       | GPIO | Notes |
|----------------|------|-------|
| Button 1       | 4    | Active low, internal pull-up |
| Button 2       | 5    | |
| Keypad Row 0   | 6    | Output, active low |
| Keypad Row 1   | 15   | |
| Keypad Row 2   | 16   | |
| Keypad Row 3   | 33   | |
| Keypad Col 0   | 34   | Input, internal pull-up |
| Keypad Col 1   | 38   | GNSS header (free when no GNSS) |
| Keypad Col 2   | 39   | GNSS header |
| LED Data       | 48   | WS2812B, single wire (RMT) |
| Display MOSI   | 40   | GNSS header; SPI |
| Display CLK    | 41   | GNSS header |
| Display CS     | 42   | GNSS header |
| Display DC     | 3    | Data/Command |
| Display RST    | --   | Tied to Vext (GPIO 36) in hardware |
| Display BL     | 45   | Backlight on/off |
| NFC SDA        | 17   | Shared I2C bus (on-board OLED + NFC + gauge) |
| NFC SCL        | 18   | |
| I2S BCLK       | 0    | Strapping pin; safe as output after boot |
| I2S LRCLK      | 46   | |
| I2S DOUT       | 47   | |
| Batt SDA       | 17   | Shared I2C bus |
| Batt SCL       | 18   | |
| Vext Ctrl      | 36   | Board-internal; drive high to power ext. peripherals |
| ADC Ctrl       | 37   | Board-internal; drive high before reading Vbat ADC (GPIO 1) |

## Assembly Sequence

1. Solder or socket the Heltec V4.3 bare board inside the enclosure.
2. Connect the 2.4 GHz IPEX FPC antenna to the WiFi connector.
   Connect the LoRa antenna to the LoRa connector.
3. Wire team buttons to GPIO 4-5 (common ground, active-low).
4. Wire keypad matrix (rows to GPIO 6/15/16/33, cols to GPIO 34/38/39).
5. Connect WS2812B LED ring data to GPIO 48 (add a 3.3V-to-5V
   level shifter for runs longer than ~30 cm).
6. Wire SPI display (MOSI 40, CLK 41, CS 42, DC 3, BL 45).
   Tie display RST to the Vext rail (GPIO 36 powers it).
7. Connect PN532 NFC reader to I2C bus (SDA 17, SCL 18).
   Set the PN532 DIP switches to I2C mode.
8. Wire MAX98357A I2S amplifier (BCLK 0, LRCLK 46, DOUT 47).
9. If using external MAX17048: connect to I2C bus (SDA 17, SCL 18).
10. Wire battery pack to the board's JST connector (observe polarity).
11. Route cables through cable glands; seal the enclosure.
