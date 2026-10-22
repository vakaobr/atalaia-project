<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Satellite build guide

From a bag of parts to a flashed Satellite: a small secondary box with two
team buttons and an LED ring, for the satellites of *Master and Satellites*,
a beacon or a second capture point. Written for a club member who can solder
header pins and wires and use a multimeter, like the
[Field Box build manual](../field-box/BUILD.md), which this guide follows and
refers to for every step the two builds share.

> **Status: not yet built.** No Satellite has been built from this guide. It
> runs the Field Box's own firmware with fewer parts fitted, so every pin
> below is a Field Box pin, checked automatically against the firmware's
> defaults (`python3 tools/check_wiring.py`, see
> [Regenerating the diagrams](../field-box/BUILD.md#14-regenerating-the-diagrams)).
> Every physical step (enclosure, power path, current, runtime, radio range)
> is **untested**. Steps marked **Verify at the first build** are open
> questions; please report what you find in an issue. Photos will be added
> after the first build (plan phase HW2); this guide never uses mock-up or
> generated photos.

## Contents

1. [What you are building](#1-what-you-are-building)
2. [What is decided and what is not](#2-what-is-decided-and-what-is-not)
3. [Parts](#3-parts)
4. [Tools and safety](#4-tools-and-safety)
5. [Pins](#5-pins)
6. [Enclosure](#6-enclosure)
7. [Board revision and antennas](#7-board-revision-and-antennas)
8. [Power](#8-power)
9. [Wiring, step by step](#9-wiring-step-by-step)
10. [First power-on and first flash](#10-first-power-on-and-first-flash)
11. [Setting it up for the field](#11-setting-it-up-for-the-field)
12. [Troubleshooting](#12-troubleshooting)

## 1. What you are building

A weatherproof box, smaller than a Field Box, with two big team buttons (a
third is possible), an LED ring that shows which team holds it, and the
board's own small screen for its status, around the same ESP32-S3 board as the
Field Box (Heltec WiFi LoRa 32 V4, revision V4.2 or V4.3). It runs on one
protected 18650 Li-ion cell and charges over USB-C. Approximate cost: €30–40
at hobby-market prices ([design specification](../../docs/design-spec.md),
section 6); not a quote, and not checked against a real build.

```
18650 (1S) --fuse--+--switch--+-- board battery socket --> main board --> 3.3 V rail
              diode-+          +-- MAX17048 (battery sense)      |           |
                               +-- 5 V boost --> LED ring,       |     MAX17048 logic
                                                 button LEDs     +--> GPIOs: buttons, LED data
```

It has **no colour screen, keypad, NFC reader or speaker** (a speaker can be
added, [section 3](#3-parts)). So it:

- plays the games a **field controller** runs: it is invited into a game over
  the radio and given its role (`satellite`, `master`, or a zone of any mode
  that needs only team buttons) by the controller. Without a keypad it cannot
  choose a game on its own;
- shows its state on the LED ring (the holding team's colour) and on the
  board's small OLED screen (the game, the box's status, a pairing code);
- is adopted into a field by USB cable or by its pairing code over the radio
  (no field card: it has no NFC reader).

## 2. What is decided and what is not

Decided (in the firmware and the design documents):

- **One firmware.** A Satellite runs the Field Box image
  (`python tools/docker_fw.py build`). There is no separate satellite
  firmware: a box's role in a game comes from the controller when it joins
  (`modes/master_satellites/mode.yaml`: the roles `master` and `satellite`
  need only `team_input`, which two team buttons give). The firmware reports
  each missing part once at boot and carries on without it.
- **The same pins as the Field Box** for the parts it has ([section 5](#5-pins)).
- **One Li-ion cell (1S)** with the Field Box's protection: fuse, Schottky
  diode, main switch, 5 V boost converter for the LED ring.

Not decided, or not supported yet:

- **The piezo buzzer** that the design specification lists for the Satellite
  is **not supported by the firmware**: the firmware makes sound only through
  the MAX98357A I2S amplifier. Fit the amplifier and a small speaker if you want
  sound, or build it silent. A piezo driver would be a firmware change
  (decision P5J-4, for the maintainer).
- **The enclosure size and layout**: no Satellite enclosure has been chosen;
  [section 6](#6-enclosure) says what it must do.
- **Runtime on one cell**: not measured.
- **A wiring diagram of its own**: the Satellite's wiring is a subset of the
  Field Box's diagrams ([section 9](#9-wiring-step-by-step)); a diagram of its
  own may follow its first build (P5J-12).

## 3. Parts

Generic descriptions and the specs to check; [Field Box manual, section
2](../field-box/BUILD.md#2-parts-and-sourcing) has the same parts with their
pitfalls. No shop is recommended.

| # | Part | Qty | What to check |
| --- | --- | --- | --- |
| 1 | Heltec WiFi LoRa 32 V4 (V4.2 or V4.3), bare board, 863-928 MHz | 1 | The 863-928 MHz version, not 433/470 MHz. Its own 0.96" OLED is the Satellite's only screen |
| 2 | 868 MHz antenna, 2 dBi or less | 1 | The board kit's antenna works behind the plastic wall; for more range, an SMA bulkhead and pigtail as on the Field Box. More gain needs the firmware setting changed ([Field Box manual, section 6](../field-box/BUILD.md#6-board-revision-and-antennas)) |
| 3 | 2.4 GHz FPC antenna with IPEX 1.0 lead | 1 | **Required**: the first setup, mode downloads and firmware updates use Wi-Fi |
| 4 | 60 mm arcade button with a 5 V LED | 2 (or 3) | Microswitch with COM, NO and NC; LED rated 5 V (optional) |
| 5 | WS2812B LED ring, 5 V | 1 | 24 LEDs is the firmware's default; a 12- or 16-LED ring works with one setting (`LED_COUNT`) |
| 6 | 74AHCT125 (or 74HCT125), DIP-14, with socket; 100 nF ceramic capacitor; 330 ohm resistor; 1000 µF 10 V+ electrolytic capacitor | 1 each | The level shifter for the ring's data, as on the Field Box. **Not** 74HC125 or 74AHC125 |
| 7 | Perfboard, about 5 x 5 cm, and pin headers | 1 | The interconnect board |
| 8 | MAX17048 fuel gauge module | 1 | Recommended. Without it the firmware does not know the battery level and never sends `battery.low` |
| 9 | Protected 18650 Li-ion cell, and a single-slot holder with leads | 1 | **Protected** (built-in protection circuit), from a reputable brand. Or a ready-made 1S pack with a protection board (BMS) and a keyed lead |
| 10 | 5 V boost converter, 3.0-4.2 V in | 1 | The Field Box's part (5 V, 2.5 A or more out) is a safe choice; how much a smaller ring needs is **to verify at the first build** |
| 11 | Inline fuse holder and 5 A fuse; Schottky diode 3 A+, 20 V+ (e.g. 1N5822); main switch, SPST, 5 A DC, covered or recessed | 1 each | As the Field Box ([manual, section 7](../field-box/BUILD.md#7-power-and-battery-safety)) |
| 12 | Lever splice connectors, 3- and 4-way | 2 + 1 | Battery, ground and 5 V distribution |
| 13 | Panel-mount USB-C extension with cap, USB 2.0 data | 1 | Optional: charging and flashing without opening the box |
| 14 | IP65 junction box, bright colour, **not metal**; cable glands and a pressure-equalising vent | 1 | Big enough for the parts above with the lid closed ([section 6](#6-enclosure)) |
| 15 | MAX98357A I2S amplifier and a 4-8 ohm speaker | 1 | Optional: the only way to give a Satellite sound |
| 16 | Labels: "GAME PROP" and the box name | 2+ | Required |

## 4. Tools and safety

The tools are the Field Box's ([manual, section 3](../field-box/BUILD.md#3-tools-and-consumables)):
a temperature-controlled soldering iron, a multimeter with continuity beep,
wire strippers, crimp tool or solder, heat-shrink, a drill with a step bit, and
a fire-safe Li-ion bag for the cell while you work. Read the Field Box's
[safety rules](../field-box/BUILD.md#4-safety-rules); they all apply. The
ones that matter most here:

1. **Never power the board without the LoRa antenna connected**, not even
   from USB: transmitting into an open antenna port can destroy the radio's
   front-end amplifier.
2. **One Li-ion cell in series only (1S, 3.0-4.2 V).** The board's battery
   socket, its charger and the MAX17048 are single-cell parts.
3. **Check polarity with a meter before every battery connection**: small
   two-pin battery plugs have no standard polarity.
4. **Protected cell, fuse close to the cell, supervised charging**, never
   in a closed case, and only between about 0 and 45 °C. Never use a cell that
   is dented, swollen, hot or below 2.5 V. Work with the cell out.
5. **3.3 V signals only** into the board: the ring is driven through the level
   shifter, and the gauge must pull SDA and SCL up to 3.3 V, never 5 V.
6. **Never wire GPIO 5 or 46** (the radio's front-end module), **nor GPIO 34 or
   38-42** (the board's GNSS connector).
7. **No game before the transmit-power check** (BRING_UP.md step 10): the
   firmware caps the power with an assumed amplifier gain that has not been
   measured yet.
8. **It must look like a game prop and stand up to hits.** Bright colour,
   "GAME PROP" on the lid and a side, nothing that looks like an explosive
   device. Satellites stand where players fight, so BBs and paintballs will
   hit them: mount the board and the cell on the backplate, away from the walls,
   keep the cell out of the line of fire behind the box's thickest wall, and
   never place a box where players must shoot at it.

## 5. Pins

The Field Box's pins, for the parts a Satellite has. These are the defaults in
[`firmware/esp32/main/Kconfig.projbuild`](../../firmware/esp32/main/Kconfig.projbuild),
the reference if the two ever disagree; `python3 tools/check_wiring.py` fails
if this table does.

| Function | GPIO | Kconfig symbol | Notes |
| --- | --- | --- | --- |
| Button 1 (first team) | 4 | `ATALAIA_BTN1_PIN` | Active low, internal pull-up: microswitch NO to the pin, COM to GND |
| Button 2 (second team) | 48 | `ATALAIA_BTN2_PIN` | |
| Button 3 (optional) | 44 | `ATALAIA_BTN3_PIN` | UART0's receive line: no console input on UART0 with it (the USB-C console is unaffected). Unwired, it reads as never pressed |
| LED ring data | 35 | `ATALAIA_LED_PIN` | Through the 74AHCT125. Also the board's white LED, which flickers with it |
| I2C SDA (gauge) | 17 | `ATALAIA_BATT_SDA_PIN` | The board's own I2C bus, shared with its OLED |
| I2C SCL (gauge) | 18 | `ATALAIA_BATT_SCL_PIN` | |
| I2S BCLK (optional amplifier) | 6 | `ATALAIA_AUDIO_BCLK_PIN` | |
| I2S LRCLK | 15 | `ATALAIA_AUDIO_LRCLK_PIN` | |
| I2S DOUT | 16 | `ATALAIA_AUDIO_DOUT_PIN` | |

Leave every other board pin unconnected. The firmware still drives the Field
Box's display pins (GPIO 1, 3, 33, 47) as outputs, so nothing else may be wired
to them; GPIO 0, 45 and 46 are boot straps; the board-internal pins are listed
in the [Field Box pin map](../field-box/README.md#pin-assignments-default-kconfig----heltec-v43).

## 6. Enclosure

<!-- PHOTO: satellite-enclosure.jpg | the drilled enclosure, lid and side views, with the layout marked -->
> **Photo to be added after the first build:** the drilled enclosure, lid and
> side views, with the layout marked.

No enclosure has been chosen. It must:

- be **plastic** (ABS or polycarbonate), never metal or metallised paint: the
  radio must get out;
- be IP65 or better, with a gasketed lid, in a bright colour;
- hold the board, the interconnect board, the boost converter, the cell holder
  (strapped down, away from the boost converter and the antennas) and the
  optional gauge and amplifier, with the lid closed and the cables bent;
- carry the buttons on the lid, spread out so two players do not collide, the
  LED ring under a translucent lid or a diffuser window, the main switch
  recessed or covered on the side away from the players, a pressure-equalising
  vent low down, and a lanyard point or a mount for a stake or a strap.

Prepare it as the Field Box ([manual, section 5](../field-box/BUILD.md#5-enclosure-preparation)):
plan on paper, measure each hole from your parts, drill before any electronics
go in, seal unused holes, a sachet of silica gel inside. Arcade buttons are not
waterproof: keep the electronics below them so drips cannot fall onto a board.

**Verify at the first build:** the smallest box that fits; LoRa and 2.4 GHz
signal through its wall; that the board's OLED can be read (through a clear lid
or a window) where it is mounted.

## 7. Board revision and antennas

<!-- PHOTO: satellite-board-antennas.jpg | the board with both antenna leads fitted and labelled -->
> **Photo to be added after the first build:** the board with both antenna
> leads fitted and labelled.

Exactly as the Field Box ([manual, section 6](../field-box/BUILD.md#6-board-revision-and-antennas)):

1. Read the chip next to the LoRa antenna connector: **KCT8103L** is a V4.3
   (the firmware's default), **GC1109** a V4.2. Write the revision on the
   backplate; the firmware must be built for it.
2. Fit **both antennas before the board is ever powered**, and label each lead
   ("LoRa 868", "2.4 GHz"). Do not guess which connector is which: use the
   board's silkscreen and its documentation.
3. The LoRa antenna inside the box, upright and away from the cell and wires,
   or outside on an SMA bulkhead; the 2.4 GHz FPC antenna flat on the inside of
   the lid or a side wall.
4. An antenna of more than 2 dBi needs `CONFIG_ATALAIA_RADIO_ANTENNA_GAIN_DBI`
   set to its gain; never lower it or the front-end gain setting.

## 8. Power

<!-- PHOTO: satellite-power.jpg | the power path (holder, fuse, diode, switch, splices, boost converter) as built -->
> **Photo to be added after the first build:** the power path as built.

The Field Box's power path ([manual, section 7](../field-box/BUILD.md#7-power-and-battery-safety)
and [diagram 2/2](../field-box/wiring/field-box-power.svg)) with one cell
instead of two in parallel:

1. **Cell.** Charge it to full in a standalone Li-ion charger first. Insert it
   only with the switch off and the fuse out. Measure the holder's leads:
   3.0-4.2 V, red positive.
2. **Fuse and diode.** The fuse holder in the red lead, close to the holder; the
   Schottky diode from the fuse holder's output (band, cathode) to the black
   lead (anode), under heat-shrink. A cell connected the wrong way round then
   blows the fuse instead of the board.
3. **Switch** from the fuse's output to the BAT+ splice; the black lead to the
   battery GND splice.
4. **Boost converter, alone first.** Its input to BAT+ and GND; fuse in, switch
   on, **set the output to 5.0-5.2 V** before anything is connected to it.
   Switch off. Its output feeds a 5 V splice (LED ring, button LEDs, amplifier,
   the level shifter's supply).
5. **Board battery lead last** ([section 9](#9-wiring-step-by-step), step 6),
   after a polarity check.

The board makes its own 3.3 V and charges the cell from USB-C with the main
switch **on** (switch off: the cell is disconnected and does not charge). The
3.3 V parts (the gauge's logic) take their power from the board's 3V3 pin, not
from its switchable Vext rail.

**Verify at the first build:** the current at rest and with the ring lit, the
runtime of a game on one cell (the firmware lights the ring at 40% by default,
`CONFIG_ATALAIA_LED_BRIGHTNESS_PCT`), and the charge time.

## 9. Wiring, step by step

<!-- PHOTO: satellite-inside.jpg | the inside of the finished box, with the wiring routed -->
> **Photo to be added after the first build:** the inside of the finished box,
> with the wiring routed.

Cell out, fuse out, switch off, for the whole section. The Field Box's
[signals diagram](../field-box/wiring/field-box-wiring.svg) shows every wire
below; a Satellite leaves out the display, the keypad and its PCF8574, the NFC
reader and (unless you want sound) the amplifier. Label both ends of every
wire; stranded wire only.

1. **Interconnect board.** As the Field Box's
   ([manual, section 8](../field-box/BUILD.md#8-the-interconnect-board)), with
   fewer pins: rails 3V3, GND and 5V (and SDA and SCL if you fit the gauge),
   the 74AHCT125 in its socket with pin 1 (1OE) to GND, pin 2 (1A) to the "LED
   data in" pin, pin 3 (1Y) through the 330 ohm resistor to the "LED data out"
   pin, pins 4, 5, 7, 9, 10, 12 and 13 to GND, pin 14 to 5V with the 100 nF
   capacitor from pin 14 to pin 7. Keep the 5V and 3V3 rails on opposite
   edges. Check with the meter, chip out: no continuity between rails.
2. **Board and rails.** Mount the board on standoffs, antennas fitted, USB-C
   reachable. Wire board 3V3 and GND to the hub (and GPIO 17 and 18 to SDA and
   SCL for the gauge). Check: no beep between 3V3 and GND.
3. **Team buttons.** Each microswitch: COM to a hub GND pin, NO to its GPIO:
   button 1 to GPIO 4, button 2 to GPIO 48, an optional button 3 to GPIO 44.
   NC stays free. Button LEDs (optional): LED+ to the 5 V rail, LED- to COM.
   Check: each signal wire beeps to GND only while its button is pressed.
4. **LED ring.** The 1000 µF capacitor across the ring's 5V and GND pads
   (stripe to GND); ring **DIN** (not DOUT) to "LED data out"; ring 5V and GND
   to the 5 V splices (0.5 mm²); board GPIO 35 to "LED data in". Data wire
   under about 30 cm.
5. **Gauge (recommended).** VCC (logic) to 3V3, GND, SDA, SCL from the hub;
   before connecting it to the hub, check that its SDA and SCL read 3.3 V or
   less when it is powered alone. Its battery-sense input (CELL+) to the BAT+
   splice.
6. **Amplifier (optional).** BCLK to GPIO 6, LRC to GPIO 15, DIN to GPIO 16;
   VIN and GND to the 5 V splices; the speaker to SPK+ and SPK-, neither
   touching GND.
7. **Board battery lead.** The hub's "5V in" to the 5 V splice. Make the lead
   for the board's battery socket from BAT+ and the battery GND splice, then
   **measure its polarity** (cell in, fuse in, switch on, plug not in the
   board) against the + and - marks next to the socket. Switch off, then plug
   it in.

Final inspection, before any power: both antennas fitted and labelled; no
continuity BAT+ to GND, 5 V to GND, 3V3 to GND; the diode's band towards BAT+,
the ring capacitor's stripe towards GND; the 74AHCT125 the right way round
(notch to pin 1); nothing wired to the pins [section 5](#5-pins) says to leave
free.

## 10. First power-on and first flash

1. **Power path.** Board battery lead unplugged, cell in, fuse in, switch on:
   BAT+ splice 3.0-4.2 V, 5 V splice 5.0-5.2 V, nothing warm. Switch off, plug
   the board's battery lead in.
2. **USB only**, switch off: plug the computer into the USB-C port; the board
   starts; 3.3 V on the hub's 3V3 rail.
3. **Flash the Field Box firmware** exactly as the
   [Field Box manual, section 11](../field-box/BUILD.md#11-first-flash) says:
   `python tools\docker_fw.py build`, then esptool from your computer (Docker
   on Windows cannot reach USB ports). Build it for your board revision
   (V4.3 by default; V4.2 needs the change described there).
4. **Settings for a Satellite** (optional; in `firmware\esp32\sdkconfig` after
   one build, then build again, as the
   [manual, section 12](../field-box/BUILD.md#12-hand-off-to-bring-up) says):

   | Your build | Line in `sdkconfig` |
   | --- | --- |
   | 12- or 16-LED ring | `CONFIG_ATALAIA_LED_COUNT=12` (or 16) |
   | No third button | `CONFIG_ATALAIA_BTN3_PIN=-1` |
   | No keypad expander (and so no button 4) | `CONFIG_ATALAIA_KP_P7_BUTTON=0` |
   | No amplifier | `CONFIG_ATALAIA_AUDIO_BCLK_PIN=-1` (audio off) |
   | Antenna with more than 2 dBi | `CONFIG_ATALAIA_RADIO_ANTENNA_GAIN_DBI=` its gain, rounded up |

5. **Boot log.** In a serial monitor on the USB port: expect one warning per
   part a Satellite does not have (`PCF8574 keypad not found`,
   `PN532 NFC reader not found`, and the gauge's if you left it out). That is
   normal. Then switch on and unplug USB: it boots from the cell.
6. **Bring-up.** Do the steps of
   [`BRING_UP.md`](../../firmware/esp32/docs/BRING_UP.md) that apply: 1 (first
   boot), 2 (Vext: the on-board OLED), 4 (buttons), 6 (LEDs), 8 (audio, if
   fitted), 9 (battery), **10 (radio, transmit power: no game before it)**, 10a
   (adoption), 10b and 10b2 (joining a controller's game). Skip the eFuse step
   (step 0) on a first box: burning an eFuse cannot be undone.

## 11. Setting it up for the field

1. **First setup.** A new box opens its Wi-Fi setup portal: join
   `atalaia-XXXX` with a phone and set the box's name, the radio region and an
   admin PIN (no default PIN; easy ones such as 1234 are refused). Write the
   name on the box.
2. **Adoption into your field**, by one of the two ways a Satellite has
   (BRING_UP.md step 10a): the USB cable to the field controller (the console's
   *Adopt* tab), or the **pairing code** that an unadopted box shows on its
   OLED, typed into the console's *Pair by code (radio)*. A field card needs an
   NFC reader, which a Satellite does not have.
3. **In a game.** In the GM console, create a game of a mode whose role needs
   only team buttons (*Master and Satellites*, Domination, Hold-All
   Domination, Last Stand...), invite the box and
   give it its role (`satellite` for a satellite). Holding a team button
   captures it; the ring shows the holding team.
4. **Moving it to another field** needs its admin PIN, which the console asks
   for when it adopts a box of another field by cable.

## 12. Troubleshooting

The [Field Box manual, section 13](../field-box/BUILD.md#13-troubleshooting)
covers the board, the buttons, the ring, the gauge, the amplifier and the
power. For a Satellite in particular:

| Symptom | Likely cause and fix |
| --- | --- |
| The log warns that the keypad or the NFC reader is not found | Expected: a Satellite has neither |
| It never shows a game menu | Expected: without a keypad it plays only the games a field controller invites it into |
| The OLED stays dark | The log says `SSD1306 OLED not found`: Vext (BRING_UP.md step 2) |
| No pairing code on the OLED | The box is already adopted, or a game is joined; a box shows its code only when unadopted |
| LED ring dark | Switch off (no 5 V on USB alone); DIN and DOUT swapped; the 74AHCT125 missing or reversed; its pin 1 not at GND |
| Battery level unknown, no low-battery warning in the console | No MAX17048 fitted, or its battery-sense wire is missing |
| Anything hot, a smell, smoke | Switch off at once, take the fuse out, take the cell out into a fire-safe bag |

If you find a fault that is not here, or a step that is wrong, please open an
issue (photos welcome): this guide is corrected from the first builds.

---

Licence: this guide is CC-BY-SA-4.0; the hardware designs it refers to are
CERN-OHL-S-2.0 ([LICENSING.md](../../LICENSING.md)).
