<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Field Box build manual

From a bag of parts to a flashed box that is ready for the hardware
bring-up checklist ([`BRING_UP.md`](../../firmware/esp32/docs/BRING_UP.md)).
Written for a club member who can solder header pins and wires and use a
multimeter. You do not need to write code.

> **Status: not yet built.** This manual describes the standard build, but
> no Field Box has been built from it yet. The pin assignments are checked
> automatically against the firmware (see
> [Regenerating the diagrams](#14-regenerating-the-diagrams)) and the
> firmware runs in the Wokwi emulator, but every physical step below
> (enclosure, power path, currents, charging, radio range) is **untested**.
> Steps marked **Verify at the first build** are open questions; please
> report what you find in an issue so the manual can be corrected.
> Photos will be added after the first prototype build; this manual never
> uses mock-up or generated photos.

> **Pins still moving.** The firmware's button pins are being adapted to the
> Heltec V4 board revisions: button 2 has moved from GPIO 5 to GPIO 39, and
> button 4 (GPIO 34, the GNSS connector's power control) may still move. The
> diagrams are always drawn from the firmware's current defaults; the GPIO
> numbers in this text are those at the time of writing. **If the text and a
> diagram disagree, the diagram wins**; check the
> [pin table](README.md#peripheral-pins) too before you solder the buttons.

## Contents

1. [What you are building](#1-what-you-are-building)
2. [Parts and sourcing](#2-parts-and-sourcing)
3. [Tools and consumables](#3-tools-and-consumables)
4. [Safety rules](#4-safety-rules)
5. [Enclosure preparation](#5-enclosure-preparation)
6. [Board revision and antennas](#6-board-revision-and-antennas)
7. [Power and battery safety](#7-power-and-battery-safety)
8. [The interconnect board](#8-the-interconnect-board)
9. [Wiring, step by step](#9-wiring-step-by-step)
10. [First power-on](#10-first-power-on)
11. [First flash](#11-first-flash)
12. [Hand-off to bring-up](#12-hand-off-to-bring-up)
13. [Troubleshooting](#13-troubleshooting)
14. [Regenerating the diagrams](#14-regenerating-the-diagrams)

## 1. What you are building

A weatherproof box with two to four big team buttons, a keypad, a 2.8-inch
colour screen, an LED ring, an NFC reader, an optional speaker and a LoRa
radio, all around one ESP32-S3 board (Heltec WiFi LoRa 32 V4, revision V4.2
or V4.3). It runs on one Li-ion cell (two 18650 cells in parallel) and
charges over USB-C.

```
battery 1S --fuse--+--switch--+-- board battery socket --> main board --> 3.3 V rail
              diode-+          +-- MAX17048 (battery sense)       |          |
                               +-- 5 V boost --> LED ring,        |    keypad (via PCF8574),
                                                 amplifier,       |    NFC, gauge, display
                                                 button LEDs      +--> GPIOs: buttons, display,
                                                                       LED data, audio
```

The wiring is drawn in two diagrams, generated from text files in
[`wiring/`](wiring/):

- **Diagram 1/2, signals and 3.3 V:** [SVG](wiring/field-box-wiring.svg)
  (zoomable), [PNG](wiring/field-box-wiring.png). Every wire from the main
  board's GPIOs, the interconnect board, the I2C devices, keypad, display,
  buttons, LED data, audio, antennas and USB.
- **Diagram 2/2, power:** [SVG](wiring/field-box-power.svg),
  [PNG](wiring/field-box-power.png). Battery, fuse, diode, switch, splices,
  5 V boost converter, and the power pins of the ring, amplifier, gauge and
  interconnect board.

![Field Box wiring, signals and 3.3 V](wiring/field-box-wiring.png)

![Field Box wiring, power](wiring/field-box-power.png)

How to read them: each box is a part, with its pins listed; each dashed box
is a cable or bundle, with one row per wire (`from`, colour, `to`). Main
board pins are named **by GPIO number** (`GPIO4`), never by header
position: find each one by the GPIO number printed next to the header pin on
your board, and check it against the pin map for your board revision. On
the modules, the small numbers are only the order of the pins in the
drawing; go by the pin names printed on each module.

The GPIO numbers are filled in from the firmware's defaults in
[`firmware/esp32/main/Kconfig.projbuild`](../../firmware/esp32/main/Kconfig.projbuild)
and are summarised in the [pin table](README.md#peripheral-pins). If you
wire a pin differently, the firmware must be configured to match
([section 12](#12-hand-off-to-bring-up)).

### Wire colours

The colours in the diagrams are a suggestion; what matters is that you use
one convention throughout and **label both ends of every wire** (heat-shrink
markers or a fine permanent pen on tape).

| Colour | Use |
| --- | --- |
| Red | Battery + (after the fuse), 0.5 mm² |
| Black | Ground (GND), everywhere |
| Orange | 5 V rail; button LED + |
| Violet | 3.3 V (3V3) |
| Blue / yellow | I2C SDA / SCL |
| Green | Button signals |
| White | LED ring data |
| Grey, pink, brown, turquoise, light blue | Display and audio signals |

Wire sizes: 0.5 mm² (AWG 20) for battery and 5 V power, 0.25 mm² (AWG 24)
for signals and low-current power, 0.14 mm² (AWG 26) or ribbon for the
keypad and display. Use stranded (flexible) wire everywhere: solid wire
breaks under vibration.

## 2. Parts and sourcing

Generic descriptions and the specs to check. No shop is recommended: buy
from any supplier that states the specs below, and prefer listings with a
real datasheet. Approximate total for one box: €70–110 at hobby-market
prices ([hardware overview](../README.md)).

| # | Part | Qty | What to check | Alternatives and pitfalls |
| --- | --- | --- | --- | --- |
| 1 | Heltec WiFi LoRa 32 V4 (revision V4.2 or V4.3), bare board, 863-928 MHz | 1 | The 863-928 MHz version, **not** 433/470 MHz; bare board without the plastic shell | Either revision works once the firmware is told which ([section 6](#6-board-revision-and-antennas)). Kits may add an 868 MHz antenna, a 3000 mAh 1S LiPo, pin headers and a GNSS module: the antenna and LiPo are usable (rows 2 and 14), the **GNSS module is not** (its connector's pins carry the display and button 4 here; keep it for the later GPS-based modes). The Heltec V3 works in the reduced memory tier |
| 2 | 868 MHz antenna, 2 dBi or less | 1 | Gain stated in dBi; tuned for 868 MHz | The kit antenna (an IPEX lead of about 120 mm with a short whip, or a small spring antenna) works behind the box's plastic wall. For more range: an SMA antenna outside, on row 3's pigtail. A higher-gain antenna needs the firmware setting changed ([section 6](#6-board-revision-and-antennas)) |
| 3 | U.FL (IPEX 1.0) to SMA bulkhead pigtail, about 10-15 cm | 1 | **Female** SMA bulkhead (or matching your antenna's plug), with O-ring and nut, IPEX **1.0** (not IPEX 4 / MHF4) | Only needed for an antenna outside the box |
| 4 | 2.4 GHz FPC antenna with IPEX 1.0 lead | 1 | IPEX 1.0 connector, 2.4 GHz | Required: the kit has only the LoRa antenna |
| 5 | 60 mm arcade button with LED | 2 (up to 4) | Microswitch with COM, NO and NC terminals; LED rated **5 V** | 12 V LED versions will be dim on 5 V; the LED is optional. Not waterproof: see [section 5](#5-enclosure-preparation). Industrial IP65 mushroom buttons are a sturdier alternative |
| 6 | 3x4 membrane keypad, 7-pin | 1 | 12 keys (1-9, *, 0, #), 7-pin ribbon, self-adhesive back | Pin order varies by maker: you will identify it with a meter |
| 7 | PCF8574 I/O expander module | 1 | Chip marked **PCF8574** (address 0x20-0x27), address jumpers A0-A2 | A **PCF8574A** answers at 0x38-0x3F and needs a firmware setting. Do **not** use an "LCD I2C backpack": its pins are wired to an LCD connector and a transistor |
| 8 | 2.8" SPI TFT, 320x240, ILI9341 (or ST7789) | 1 | SPI interface (pins CS, RESET, DC, SDI/MOSI, SCK, LED); 3.3 V logic | Touch pins can stay unconnected. Note which controller it has: ST7789 needs a firmware setting |
| 9 | WS2812B LED ring, 24 LEDs | 1 | 5 V, pads DIN / DOUT / 5V / GND | 12- or 16-LED rings work with a firmware setting (`LED_COUNT`) |
| 10 | 74AHCT125 (or 74HCT125), DIP-14, plus a 14-pin socket | 1 | The letters **AHCT** or **HCT** | **Not** 74HC125 or 74AHC125: those need more than 3.3 V at the input when powered from 5 V |
| 11 | PN532 NFC module (I2C capable) | 1 | Mode switches or jumpers for HSU / I2C / SPI | NTAG215 or NTAG216 cards for join cards |
| 12 | MAX17048 fuel gauge module | 1 | Single-cell Li-ion gauge, I2C | Not a MAX17049 (two cells) |
| 13 | MAX98357A I2S amplifier module + speaker 4-8 ohm, 3 W | 1 | I2S input (BCLK, LRC, DIN) | Optional. A weather-resistant (mylar cone) speaker survives damp better |
| 14 | Protected 18650 Li-ion cells | 2 | **Protected** (built-in protection circuit, usually button-top and ~69 mm long), same model, bought together, from a reputable brand | Avoid unbranded cells with absurd capacities ("9900 mAh"). A ready-made 1S2P pack with protection board (BMS) and a keyed lead is an alternative. The kit's 3000 mAh LiPo (about 58 x 39 mm) can stand in for a first prototype ([section 7](#7-power-and-battery-safety)) |
| 15 | 2-slot 18650 holder, **parallel** wiring, with leads | 1 | Fits protected (longer) cells; parallel (3.7 V), not series (7.4 V) | Measure: a parallel holder reads one cell's voltage |
| 16 | 5 V boost converter module | 1 | Input range covers 3.0-4.2 V; 5 V output at **2.5 A or more**; adjustable or fixed 5 V | Small "1 A" boost modules will brown out under the LED ring |
| 17 | Inline fuse holder + 5 A fuse (and a spare) | 1 | Blade (mini/standard) or 5x20 mm, with 0.5 mm² leads | |
| 18 | Schottky diode, 3 A or more, 20 V or more (e.g. 1N5822) | 1 | Through-hole | Reverse-polarity protection, see [section 7](#7-power-and-battery-safety) |
| 19 | Main power switch, SPST | 1 | Rated 5 A DC or more; covered toggle, rocker with cover, or key switch; waterproof boot | Must be hard for players to reach |
| 20 | Lever splice connectors, 3- and 4-way | 2 + 2 | For 0.2-4 mm² wire | Or a small screw terminal block |
| 21 | Panel-mount USB-C extension, with cap | 1 | **Data** lines connected (USB 2.0), not "charge-only"; IP65 or capped | You can also open the box to plug into the board directly |
| 22 | Perfboard about 5 x 7 cm, 2.54 mm pitch | 1 | Plain or stripboard | |
| 23 | Electrolytic capacitor 1000 µF, 10 V or more | 1 | For the LED ring | |
| 24 | Ceramic capacitor 100 nF | 1 | For the 74AHCT125 | |
| 25 | Resistor 330 ohm, 1/4 W | 1 | LED data line | |
| 26 | IP65 junction box, about 200 x 150 x 100 mm, bright colour | 1 | ABS or polycarbonate (**not metal**: the radio must get out); gasketed lid | A clear or translucent lid lets the LED ring and screen show through |
| 27 | Cable glands (M12/M16), pressure-equalising vent (M12) | as needed | IP65 or better | The vent stops condensation and pressure pumping |
| 28 | M3 nylon standoffs and screws, backplate (plastic or plywood) | 1 set | | Keeps the electronics off the box floor |
| 29 | Clear window, 2-3 mm acrylic or polycarbonate | 1 | Bigger than the display's active area | Only if the lid is opaque |
| 30 | Labels: "GAME PROP" and the box name | 2+ | Weatherproof | Required, see [section 4](#4-safety-rules) |

## 3. Tools and consumables

- Temperature-controlled soldering iron, fine chisel tip; solder (lead-free
  or leaded, with flux core); flux pen; desoldering braid.
- Multimeter with continuity beep, DC voltage and a 200 mA (or 10 A) current
  range. **Essential**: most steps end with a meter check.
- Wire stripper, flush cutters, small pliers.
- Crimp tool and 2.54 mm housings (Dupont-style), or solder everything:
  **no loose jumper wires** in a field prop.
- Heat-shrink tubing (assorted) and a heat gun or lighter; wire labels.
- Drill with step drill bit (4-20 mm) and/or hole saws, deburring tool, file,
  coping saw or rotary tool for the display window.
- Hot glue gun, cable ties and adhesive tie mounts, double-sided foam tape,
  Kapton tape.
- Neutral-cure silicone sealant (for the keypad ribbon slot and window).
- Safety glasses; a fire-safe Li-ion bag (or a metal tin with sand) for the
  cells while you work.
- A computer with Docker Desktop and Python 3 for the firmware
  ([section 11](#11-first-flash)), and a USB-C data cable.

## 4. Safety rules

Read these before you start, and keep them in mind at every step.

1. **Never power the board without the LoRa antenna connected**, not even
   from USB. Transmitting into an open antenna port can damage the radio,
   and the high-power variant's front-end amplifier can be destroyed. Fit the
   antennas first ([section 6](#6-board-revision-and-antennas)) and leave them on.
2. **One Li-ion cell in series only (1S, 3.0-4.2 V).** The board's battery
   socket, its charger and the MAX17048 gauge are single-cell parts. A 2S
   (7.4 V) pack destroys them.
3. **Check polarity with a meter** before every battery connection,
   including the LiPo that comes in the board's kit. The small two-pin
   battery plugs used by hobby boards (JST-type and SH1.25-type) have no
   standard polarity; a plug that fits can still be reversed.
4. **Protected cells, a fuse close to the battery, supervised charging.**
   Store and charge the cells in a fire-safe bag; never leave a charging
   box unattended; never use a cell that is dented, swollen, hot or below
   2.5 V.
5. **Work with the battery out** whenever you solder or rewire.
6. **The ESP32-S3 is a 3.3 V part.** No signal wire to the board may ever
   carry more than 3.3 V: the I2C modules must pull up to 3.3 V
   ([section 9.2](#92-i2c-modules)), and the LED ring is driven through the
   level shifter.
7. **Never wire GPIO 5 or GPIO 46, and leave the GNSS connector empty.**
   They drive the radio's front-end module on one board revision or the
   other; the GNSS connector's pins carry the display and button 4 in this
   pin map.
8. **No game before the transmit-power check.** The high-power board can
   put out more than the EU868 limits allow; the firmware caps it with an
   assumed amplifier gain that has not been measured yet. Do not use a box
   in a game until BRING_UP.md step 10 (radio, transmit power) has been
   done for that box.
9. **It must look like a game prop.** Bright colours, a printed "GAME PROP"
   label, no taped pipes, no visible wire bundles, nothing resembling an
   explosive device. Transport it in a labelled case and never leave it
   unattended outside the field (design spec, section 17).

## 5. Enclosure preparation

> **Photo to be added after the first prototype build:** the drilled
> enclosure, lid and side views, with the layout marked.

Do all the drilling **before** any electronics go in, and blow out the
plastic swarf afterwards.

1. **Plan the layout on paper first.** Put the parts on the lid and in the
   box and check they fit with the lid closed, cables included:
   - **Lid (top):** display window, LED ring (under a translucent lid or a
     diffuser window), team buttons (spread out so two players do not
     collide), keypad (on the outside), NFC "tap here" zone (the reader
     mounted under the lid, 1-3 mm of plastic between card and reader, no
     metal).
   - **Side wall:** main switch (recessed or covered, on the side facing
     away from the players), USB-C panel socket with cap, SMA antenna
     bulkhead (on the top of a side wall, so the antenna stands upright),
     pressure-equalising vent (low down, on a side that does not face rain).
   - **Inside:** a backplate on standoffs for the board, interconnect board,
     boost converter and modules; the battery holder secured with a strap
     or bracket, away from the boost converter and the antennas.
   - Space to allow, from the board's published dimensions: the board is
     about 52 x 25 mm and about 9 mm tall with its OLED; leave room above
     its USB-C end for the cable bend and above its two antenna connectors
     for the leads. The kit LiPo, if you use it, is about 58 x 39 mm; the
     kit's LoRa antenna lead is about 120 mm long plus the antenna itself.
   - Keep the board's antenna connectors and the 2.4 GHz antenna away from
     the battery, the boost converter and any metal. An antenna inside the
     box must sit behind plastic (radio-transparent), never inside or behind
     metal; a metal box or a metallised paint finish is not usable.
2. **Measure every hole from your parts, not from a listing.** Typical
   sizes, to confirm with your parts: SMA bulkhead 6.5 mm; M12 vent or
   gland 12 mm; M16 gland 16 mm; arcade buttons and the USB-C panel socket
   vary (measure the threaded body); switch per its datasheet. Drill a small
   pilot hole first, then the step drill; deburr every hole.
3. **Display window.** If the lid is opaque, cut a window slightly smaller
   than the panel's frame but larger than its active area, and glue a clear
   acrylic or polycarbonate pane over it from the inside with neutral-cure
   silicone. Mount the display behind it on standoffs or a printed bracket.
4. **Keypad.** Membrane keypads stick on the outside. Cut a narrow slot for
   the ribbon, stick the keypad over it, and seal the slot from inside with
   silicone. Do not bend the ribbon sharply where it enters.
5. **Speaker (optional).** Drill a grid of small holes (2-3 mm) and glue a
   piece of acoustic mesh or a breathable waterproof membrane behind them,
   then the speaker.
6. **Buttons.** Arcade buttons are **not** waterproof. Mount them with
   their sealing ring (or a rubber washer) on the outside, and keep the
   electronics below them on the backplate so drips cannot fall onto a
   board. Industrial IP65 buttons are the alternative for wet sites.
7. **Weatherproofing.** Seal every unused hole. Route each cable that
   leaves the box through a cable gland. Fit the vent. Put a sachet of
   silica gel inside. Optionally coat the finished interconnect board with
   conformal coating, keeping it off connectors.
8. **Appearance.** Bright enclosure colour (orange, yellow, green), the
   "GAME PROP" label on the lid and on one side, and the box name or number.

**Verify at the first build:** that the board's 2.4 GHz and LoRa signals
are good enough through the chosen enclosure wall (a plastic box is
normally fine), and that the speaker is loud enough behind the membrane.

## 6. Board revision and antennas

> **Photo to be added after the first prototype build:** the board with
> both antenna leads fitted and labelled, and the bulkhead from outside.

### Identify the board revision

The Heltec V4 comes in two revisions with different radio front-end modules
(FEM), and the firmware drives them differently: with the wrong setting the
receiver is deaf or the transmitter weak. Before wiring anything:

1. Find the small chip next to the LoRa antenna connector and read its
   marking with a magnifier (a phone camera's zoom works):
   - **KCT8103L**: revision **V4.3**, the firmware's default;
   - **GC1109**: revision **V4.2**.
   If the marking is unreadable, look for the revision printed on the
   board's silkscreen.
2. Write the revision on the board's backplate, and select it in the
   firmware before flashing ([section 11](#11-first-flash), step 1, and
   [section 12](#12-hand-off-to-bring-up)).
3. On either revision, never wire **GPIO 5** (front-end control on the V4.3)
   or **GPIO 46** (front-end control on the V4.2).

### Antennas

**Fit both antennas now, before the board is ever powered, and leave them
fitted for good.**

1. Identify the board's two IPEX (U.FL) connectors: one is LoRa, the other
   2.4 GHz (Wi-Fi/BLE). Use the silkscreen on the board and its documentation
   for your board revision. **Do not guess**: an 868 MHz antenna on the
   2.4 GHz connector leaves the LoRa output open.
2. Put a label (tape flag) on each lead right away: "LoRa 868" and "2.4 GHz".
3. IPEX connectors are fragile and rated for few matings (tens, not
   hundreds). Press the plug on straight with a fingertip or the flat of a
   tool until it clicks; to remove it, lift straight up with a proper
   extraction tool or a fingernail under the plug body, never by the cable.
   Secure each mated plug with a small strip of Kapton tape (not glue).
4. **LoRa antenna**, either:
   - **prototype:** the antenna from the board's kit (on its IPEX lead),
     inside the box behind the plastic wall, upright if possible, as far
     from the battery and other wires as possible; or
   - **standard:** the IPEX-to-SMA pigtail to the SMA bulkhead on the box
     wall (O-ring outside), and an 868 MHz antenna screwed on outside.
5. **2.4 GHz antenna:** stick the FPC antenna to the inside of the lid or a
   side wall, flat, away from the battery, the boost converter and metal.
6. **Antenna gain and the law.** The firmware calculates the radio's
   transmit power so the box stays within the EU868 limits, assuming a
   **2 dBi** antenna (`CONFIG_ATALAIA_RADIO_ANTENNA_GAIN_DBI`) and, by
   default, the high-power board's front-end gain of 14 dB
   (`CONFIG_ATALAIA_RADIO_FEM_GAIN_DB`). If your antenna has more gain,
   set its gain in the firmware ([section 12](#12-hand-off-to-bring-up)).
   Never lower either value to get more range: that breaks the legal limit.
   The 14 dB is an assumption until it is measured (BRING_UP.md step 10):
   no game use before that check.

## 7. Power and battery safety

> **Photo to be added after the first prototype build:** the power path
> (holder, fuse, diode, switch, splices, boost converter) as built.

Follow [diagram 2/2](wiring/field-box-power.svg).

### How the power is arranged

- The cells (two protected 18650s in **parallel**: still one cell's voltage,
  3.0-4.2 V, double the capacity) go through the **fuse**, then the **main
  switch**, to a **BAT+ splice**. From there:
  - the **board's battery socket** (the board makes its own 3.3 V and
    charges the cells from USB-C);
  - the **5 V boost converter**, which feeds the LED ring, the amplifier and
    the button LEDs (on the 5 V splice and the interconnect board);
  - the **MAX17048 gauge's battery-sense input**.
- A **Schottky diode** sits across the battery right after the fuse, band
  (cathode) to the + side. In normal use it does nothing. If the battery is
  ever connected the wrong way round, it conducts and the fuse blows before
  anything else is damaged.
- The 3.3 V parts (display, NFC, keypad expander, gauge logic) take their
  power from the board's **3V3** pin through the interconnect board. The
  board's switchable "Vext" rail (GPIO 36, active low) is **not** used for
  them: the firmware does not switch it yet, and it also feeds parts of the
  board itself (the OLED, among others).
- The board's solar input (4.4-6 V) and GNSS connector stay unconnected.

Why not a 2S (7.4 V) pack? Because the board's battery input, its charger
and the gauge only handle one cell. One cell plus a boost converter keeps
every part within its ratings.

### Steps

1. **Cells.** Charge both new cells to full in a standalone Li-ion charger
   and check they read within 0.05 V of each other before putting them in a
   parallel holder. Always replace both cells together, with the same
   model. **Insert cells only with the switch off and the fuse out.**
2. **Holder check.** With both cells in, measure the holder leads: one
   cell's voltage (3.0-4.2 V), red lead positive. If you read about 7-8 V,
   it is a **series** holder: do not use it.
3. **Fuse and diode.** Solder or crimp the fuse holder into the red lead,
   close to the holder. Solder the diode between the fuse holder's output
   side (band/cathode) and the battery's black lead (anode), with
   heat-shrink over both joints. Remove the fuse while you continue.
4. **Switch.** Wire fuse output to one switch terminal, the other terminal
   to the 4-way BAT+ splice (0.5 mm² red). The battery's black lead goes to
   the 4-way battery GND splice.
5. **Boost converter, alone first.** Connect only the boost converter's
   input to the splices (IN+ to BAT+, IN- to GND). Fit the fuse, switch on,
   and measure the output: **set it to 5.0-5.2 V** (adjustable modules have
   a trimmer; turn slowly). Switch off. Never connect loads before this.
6. **5 V splices.** Boost OUT+ to the 4-way 5 V splice, OUT- to the 3-way
   5 V GND splice (0.5 mm²). The ring, amplifier and interconnect board are
   connected in [section 9](#9-wiring-step-by-step).
7. **Board battery lead (do this last, in [section 9.8](#98-board-battery-lead)).**

### Using the kit's LiPo instead (first prototype)

Board kits may include a 1S LiPo pouch (3000 mAh, about 58 x 39 mm, with a
small two-pin plug). It is a single cell, so it fits this design, with some
care:

- Use it in place of the 18650 holder, through the **same fuse, diode and
  switch**. Do not cut its lead: plug it into a matching socket with leads
  (a "pigtail") and wire that to the fuse and the battery GND splice.
  **Check the polarity at the pigtail with a meter** before anything else.
- Look for a protection circuit (a small board under the tape at the lead
  end). Without one, do not use it unattended.
- A pouch cell has no hard case: mount it flat in a rigid tray or bracket
  where nothing can press, bend or puncture it, away from screws, the boost
  converter and sharp edges. Retire it if it swells.
- It holds about half the energy of two 18650s; fine for bench work and
  short games.
### Power budget (estimates, not measurements)

| Load | Rail | Typical | Peak |
| --- | --- | --- | --- |
| Main board (ESP32-S3, LoRa receive) | battery, via the board | 80-150 mA | 400-500 mA (Wi-Fi or LoRa transmit) |
| Display incl. backlight | 3V3 | 40-100 mA | |
| PN532 NFC (field on) | 3V3 | 50-150 mA | |
| PCF8574, MAX17048 | 3V3 | under 1 mA | |
| LED ring, 24 LEDs | 5 V | ~25 mA (all off) to ~0.5 A (one full team colour) | ~1.4 A (all white, full brightness) |
| Amplifier and speaker | 5 V | a few mA | 0.6-0.8 A (loud) |
| Button LEDs (4) | 5 V | 40-80 mA | |

Current drawn from the cells for the 5 V loads is roughly 1.6 times the 5 V
current (voltage ratio plus converter losses). With two ~3000 mAh cells and
a typical game load the box should last well beyond the 2-hour gate of
phase 1, but **this has not been measured**: BRING_UP.md step 12 runs a
2-hour game and is where the real figure will come from. The firmware does
not dim the LED ring yet, so budget for full-colour LEDs.

**Verify at the first build:** the board's charge current and how long a
full charge takes; that the board's 3.3 V regulator copes with the display
and NFC reader on top of the board itself (watch for brown-out resets when
the screen and NFC are active during Wi-Fi setup); the real runtime.

### Charging, storage and transport

- **Charging:** plug USB-C (the panel socket) into a 5 V USB charger
  (the board is listed for 5 V / 1 A charging) with the **main switch on**:
  the board charges the cells, and the box runs meanwhile. With the switch
  off the cells are disconnected and do not charge. Charge in a supervised
  place, not in a closed transport case, and only between about 0 and
  45 °C: never charge a cold box straight from a winter field. Alternatively
  take the cells out and charge them in a standalone Li-ion charger.
- **Storage** for more than a few weeks: cells at about 3.7-3.8 V (half
  charged), switch off, fuse out, in a cool dry place.
- **Transport:** switch off; for flights and shipping, follow the carrier's
  Li-ion rules.

## 8. The interconnect board

> **Photo to be added after the first prototype build:** both sides of the
> finished interconnect board.

A small perfboard that gives every module short, labelled connections to
the shared rails, and holds the LED ring's level shifter. In the diagram it
is the `HUB` box.

**Rails.** Make five rails, each a row of male 2.54 mm header pins joined
underneath with tinned wire or solder bridges, and label them on the top:

| Rail | Fed from | Pins needed |
| --- | --- | --- |
| 3V3 | board 3V3 pin | in, PCF8574, PN532, gauge, display |
| GND | board GND pin | in, PCF8574, PN532, gauge, display, 4 buttons, 74AHCT125 |
| SDA | board GPIO 17 | in, PCF8574, PN532, gauge |
| SCL | board GPIO 18 | in, PCF8574, PN532, gauge |
| 5V | 5 V splice | in, 4 button LEDs, 74AHCT125 |

Keep the 5V rail physically apart from the 3V3 rail (opposite edges of the
board), so a slip of the soldering iron or a stray strand cannot join them.

**Level shifter.** Solder a 14-pin DIP socket and wire it as follows, then
fit the 74AHCT125 (notch towards pin 1) only after the board has passed the
continuity checks:

| 74AHCT125 pin | Name | Connect to |
| --- | --- | --- |
| 1 | 1OE (output enable, active low) | GND rail |
| 2 | 1A (input) | "LED data in" pin, wired to board GPIO 48 |
| 3 | 1Y (output) | 330 ohm resistor, then the "LED data out" pin |
| 4, 5 | 2OE, 2A | GND rail |
| 6 | 2Y | not connected |
| 7 | GND | GND rail |
| 8 | 3Y | not connected |
| 9, 10 | 3A, 3OE | GND rail |
| 11 | 4Y | not connected |
| 12, 13 | 4A, 4OE | GND rail |
| 14 | VCC | 5V rail, and a 100 nF ceramic capacitor from pin 14 to pin 7, as close as possible |

**Checks before going on** (no power, chip out of its socket): no
continuity between any two rails; pin 14 to the 5V rail and pin 7 to GND
beep; pin 2 beeps to the "LED data in" pin; the "LED data out" pin reads
330 ohm to pin 3.

## 9. Wiring, step by step

Battery out, fuse out, switch off, for the whole section. After each
subsystem, do its check. Keep signal wires away from the battery and 5 V
power wires where you can, and secure every bundle with ties so nothing
pulls on a solder joint.

> **Photo to be added after the first prototype build:** the inside of the
> finished box, with the wiring routed.

### 9.1 Main board and rails

1. Solder header pins to the board if it came without them, or solder
   wires straight to the pads you need (only the pins in diagram 1/2).
   Mount the board on standoffs on the backplate, antennas already fitted
   ([section 6](#6-board-revision-and-antennas)), USB-C connector reachable.
2. Mount the interconnect board next to it. Wire board **3V3**, **GND**,
   **GPIO 17** (SDA) and **GPIO 18** (SCL) to the hub's 3V3, GND, SDA and
   SCL "in" pins: four short wires, under 15 cm.
3. **Leave every other board pin unconnected.** In particular never wire
   GPIO 0, 45 or 46 (boot straps; 46 also drives the V4.2's front-end
   module), GPIO 5 (the V4.3's front-end module), or the board-internal
   GPIO 1, 2, 7, 8-14, 19-21, 35-37, 43-44. Leave the board's GNSS
   connector empty: its pins (GPIO 34, 38-42) carry the display and
   button 4 in this pin map, so the GNSS module from the kit must not be
   plugged in.
4. **Check:** no continuity between 3V3 and GND at the hub (a reading of a
   few hundred ohms or more is normal; a beep is a short).

### 9.2 I2C modules

The keypad expander (PCF8574), NFC reader (PN532) and battery gauge
(MAX17048) share the board's I2C bus with the board's own small OLED
(GPIO 17/18). Each module gets four wires from its own group of hub pins:
3V3, GND, SDA, SCL.

1. **PCF8574:** set the address jumpers A0, A1 and A2 all to GND, which
   gives address 0x20. Leave its INT pin and P7 unconnected.
2. **PN532:** set the mode switches (or jumpers) to **I2C**, following the
   table printed on the module. Use its 4-pin I2C header.
3. **MAX17048:** connect its logic supply pin (if it has a separate one,
   marked VIN, VCC or VDD for the I2C side) to 3V3, plus GND, SDA, SCL. Its
   battery-sense input (CELL+ or BAT+) goes to the BAT+ splice in
   [section 9.8](#98-board-battery-lead).
4. **Pull-up voltage check (important).** Many modules have their own
   pull-up resistors on SDA and SCL. They must pull up to 3.3 V, never to 5 V
   or to the battery. Before connecting a module to the hub, power it alone
   the way it will be powered (3.3 V on VCC from a bench supply or, later,
   from the board), and measure SDA and SCL to GND: both must read **3.3 V
   or less**. For the gauge, also measure with the battery connected to its
   sense input. A module that reads higher must not go on the bus until its
   pull-ups are removed.

### 9.3 Keypad

1. **Identify the keypad's pins with the meter** (continuity mode), because
   the order differs between makers. Press and hold a key and find the two
   ribbon pins that beep:
   - the pin that beeps for 1, 2 and 3 is **R1**; for 4, 5, 6: **R2**;
     for 7, 8, 9: **R3**; for *, 0, #: **R4**;
   - the pin that beeps for 1, 4, 7, * is **C1**; for 2, 5, 8, 0: **C2**;
     for 3, 6, 9, #: **C3**.
   Write the order down (for example on tape on the ribbon).
2. Wire **R1-R4 to P0-P3** and **C1-C3 to P4-P6** of the PCF8574, exactly as
   in the diagram (`W_KEYPAD`). The firmware drives the rows on P0-P3 and
   reads the columns on P4-P6; a swap shows up as wrong digits.
3. Use a 7-way crimped housing on the ribbon, or solder, and secure it so
   the ribbon cannot be pulled.

### 9.4 Display

1. **Backlight current check.** Power the display from 3.3 V (VCC and GND),
   then measure the current into its LED pin from 3.3 V (meter in series, mA
   range). Most modules switch the backlight with a small transistor and draw
   only a few mA here.
   - **Under 10 mA:** wire LED to GPIO 47, as in the diagram (the firmware
     turns the backlight on and off).
   - **More than 10 mA:** do not drive it from a GPIO. Wire LED straight to
     the 3V3 rail and set `CONFIG_ATALAIA_DISP_BL_PIN=-1` in the firmware
     ([section 12](#12-hand-off-to-bring-up)); the backlight then stays on.
2. Wire VCC and GND to the hub's display pins, then the six signals
   straight from the board: CS to GPIO 42, RESET to GPIO 38, DC to GPIO 3,
   SDI (MOSI) to GPIO 40, SCK to GPIO 41, LED to GPIO 47. SDO (MISO) and any
   touch-panel pins stay unconnected.
3. **Keep these wires 15 cm or shorter** and bundle them together: the
   display bus runs at 40 MHz, and long wires show up as a garbled or white
   screen.

### 9.5 LED ring

1. Solder the 1000 µF capacitor across the ring's 5V and GND pads (or at
   the end of its power wires, right at the ring): **stripe (negative) to
   GND**.
2. Ring **DIN** (not DOUT: check the arrow or label) to the hub's "LED
   data out" pin. Ring **5V** to the 5 V splice and **GND** to the 5 V GND
   splice, both 0.5 mm².
3. Board **GPIO 48** to the hub's "LED data in" pin.
4. Keep the data wire under about 30 cm.

### 9.6 Team buttons

1. Each button: microswitch **COM** to a hub GND pin, the **NO** (normally
   open) terminal to its GPIO: button 1 (red team) GPIO 4, button 2 (blue)
   GPIO 39, button 3 GPIO 33, button 4 GPIO 34. The NC terminal stays
   unconnected.

   > **Pending:** button 2 moved from GPIO 5 (now forbidden: the V4.3's
   > front-end module) to GPIO 39, and button 4's GPIO 34 (the GNSS
   > connector's power control; harmless with the connector empty) is under
   > review and may move. Take the pins from the current diagram and
   > [pin table](README.md#peripheral-pins), not from a printout. **Never
   > use GPIO 5**, even if an older copy of this manual says so.
2. Button LED (optional): LED+ to the hub's 5 V pin for that button, LED-
   joined to COM at the button. Check the LED's polarity marking.
3. Two-team boxes simply leave buttons 3 and 4 out; an unwired button input
   reads as "not pressed".
4. **Check:** with the meter between each GPIO wire end and GND, the
   reading must beep only while that button is pressed.

### 9.7 Audio (optional)

1. Amplifier BCLK to GPIO 6, LRC to GPIO 15, DIN to GPIO 16.
2. VIN to the 5 V splice, GND to the 5 V GND splice.
3. Speaker to SPK+ and SPK-. **Neither speaker wire may touch GND**: the
   amplifier's outputs are both driven.
4. Leave GAIN and SD unconnected (default gain, both channels mixed).

### 9.8 Board battery lead

1. Connect the gauge's battery-sense input (CELL+) to the BAT+ splice.
2. Connect the hub's "5V in" pin to the 5 V splice (0.25 mm² is enough).
3. Make the lead for the board's battery socket: the matching plug with
   two wires, to the BAT+ splice and the battery GND splice.
4. **Polarity check, before plugging it in:** cells in, fuse in, switch on,
   plug **not** in the board. Measure at the plug's contacts and compare with
   the + and - markings next to the board's battery socket. Wrong way round:
   swap the wires in the plug (or at the splices). Switch off.
5. Plug the lead into the board.

### 9.9 Final inspection before any power

- [ ] Both antennas fitted and labelled; the right one on each connector.
- [ ] Battery out or switch off; fuse out.
- [ ] No continuity BAT+ splice to GND, 5 V splice to GND, 3V3 to GND.
- [ ] The diode's band towards BAT+; the ring capacitor's stripe towards GND.
- [ ] 74AHCT125 in its socket the right way round (notch to pin 1).
- [ ] No module pulls SDA or SCL above 3.3 V ([section 9.2](#92-i2c-modules)).
- [ ] Every wire labelled at both ends, no bare copper, bundles tied, no
      wire pinched by the lid.
- [ ] Nothing wired to the board pins listed in [section 9.1](#91-main-board-and-rails).

## 10. First power-on

Power the box up in stages, with a hand on the switch. At the first sign of
heat, smell or smoke: switch off and take the fuse out.

1. **Power path.** Board battery lead **unplugged**. Cells in, fuse in,
   switch on. Measure: BAT+ splice 3.0-4.2 V; 5 V splice 5.0-5.2 V. The
   button LEDs light; the ring may stay dark or flash briefly (it has no
   data yet). Nothing gets warm. Switch off; plug the board's battery lead
   in.
2. **USB only.** Switch **off**. Plug the computer into the USB-C socket. The
   board powers up from USB; the 3.3 V parts power up with it; the 5 V parts
   (ring, amplifier, button LEDs) stay off because the switch is off. Measure
   3.3 V on the hub's 3V3 rail. Now flash the firmware
   ([section 11](#11-first-flash)).
3. **Battery.** After flashing, unplug USB and switch on: the box boots from
   the battery. Continue with bring-up ([section 12](#12-hand-off-to-bring-up)).

## 11. First flash

The firmware is built in Docker; flashing runs on your computer, because
Docker Desktop on Windows cannot reach USB serial ports. The commands below
are for **Windows `cmd`**, run from the repository folder. Docker Desktop
must be running.

The V4's USB-C port is the ESP32-S3's own USB serial port (no USB-serial
bridge chip): Windows 10 and 11 need no driver, and flashing and the boot
log both go over it.

1. **Check the firmware configuration.** The build uses
   `firmware\esp32\sdkconfig` if it exists, and that file keeps the values
   of the last build, whatever they were. Open it in Notepad (or run
   `findstr /B "CONFIG_ATALAIA_KP_ CONFIG_ATALAIA_SKIP_SETUP CONFIG_ATALAIA_MODEM_MODE CONFIG_ATALAIA_BOARD_" firmware\esp32\sdkconfig`)
   and check that it has `CONFIG_ATALAIA_KP_PCF8574=y` and the line for
   your board revision (`CONFIG_ATALAIA_BOARD_HELTEC_V4_3=y` or
   `CONFIG_ATALAIA_BOARD_HELTEC_V4_2=y`), and none of
   `CONFIG_ATALAIA_KP_GPIO_MATRIX=y`, `CONFIG_ATALAIA_SKIP_SETUP=y` or
   `CONFIG_ATALAIA_MODEM_MODE=y`. If it does not, or if you are not sure,
   start from the defaults:

   ```
   del firmware\esp32\sdkconfig
   python tools\docker_fw.py clean
   ```

   A checkout that was never built has no `sdkconfig` and gets the
   defaults automatically.
2. **Build:**

   ```
   python tools\docker_fw.py build
   ```

   The first build takes several minutes. It ends with
   `Firmware: firmware/esp32/build/atalaia_esp32.bin`.

   The defaults are for a **V4.3** board. For a **V4.2** board
   ([section 6](#6-board-revision-and-antennas)), open
   `firmware\esp32\sdkconfig`, replace the line
   `CONFIG_ATALAIA_BOARD_HELTEC_V4_3=y` with
   `# CONFIG_ATALAIA_BOARD_HELTEC_V4_3 is not set` and the line
   `# CONFIG_ATALAIA_BOARD_HELTEC_V4_2 is not set` with
   `CONFIG_ATALAIA_BOARD_HELTEC_V4_2=y`, save, and build again.
3. **Install the flasher once,** in its own Python environment (esptool
   4.8.1, the version in the ESP-IDF build image):

   ```
   python -m venv %USERPROFILE%\atalaia-flash
   %USERPROFILE%\atalaia-flash\Scripts\python -m pip install esptool==4.8.1
   set FLASH=%USERPROFILE%\atalaia-flash\Scripts\python
   ```

   (`set FLASH=...` lasts only for this `cmd` window; repeat it in a new
   one.)
4. **Find the port.** Antennas on, switch off, plug in the USB-C cable, then:

   ```
   %FLASH% -m serial.tools.list_ports -v
   ```

   Note the new `COM` port (also in Device Manager, under *Ports (COM &
   LPT)*, usually as a "USB Serial Device"). The examples use `COM5`. No
   new port: see [troubleshooting](#13-troubleshooting).
5. **Erase the board** (first flash of a new board only: it removes the
   factory firmware and any old settings):

   ```
   %FLASH% -m esptool --chip esp32s3 -p COM5 erase_flash
   ```

6. **Write the firmware:**

   ```
   cd firmware\esp32\build
   %FLASH% -m esptool --chip esp32s3 -p COM5 -b 460800 --before default_reset --after hard_reset write_flash "@flash_args"
   cd ..\..\..
   ```

   `flash_args` (written by the build) lists the bootloader, partition
   table and application with their addresses. If the connection fails,
   put the board in download mode by hand (hold its PRG/BOOT button, press
   and release RST, release PRG; or hold PRG while plugging the cable in)
   and run the command again, or try `-b 115200`. The COM port can
   disappear and come back while the board resets; that is normal with the
   built-in USB port.
7. **Watch the boot log:**

   ```
   %FLASH% -m serial.tools.miniterm COM5 115200
   ```

   Press `Ctrl+]` to quit. You should see the boot messages described in
   BRING_UP.md step 1, with a warning for each part that is not found.

**Alternative without Python, in Chrome or Edge:** make a single image
file, then flash it with Espressif's browser-based esptool page at address
`0x0`:

```
docker run --rm -v "%cd%\firmware\esp32\build:/b" -w /b espressif/idf:v5.3.2 bash -c ". $IDF_PATH/export.sh > /dev/null && esptool.py --chip esp32s3 merge_bin -o atalaia-merged.bin @flash_args"
```

The image is `firmware\esp32\build\atalaia-merged.bin`.

**Linux and macOS:** the same steps, with `python3`, `rm` instead of `del`,
`~/atalaia-flash/bin/python` instead of `%FLASH%`, and `/dev/ttyACM0`
(Linux) or `/dev/cu.usbmodem*` (macOS) instead of `COM5`.

**Known limitation: typing into the console.** The firmware reads console
input from UART0 (GPIO 43/44), which on the V4 is not connected to the USB
port; only the log is copied to USB. So the boot log shows in miniterm,
but lines you type there (`@joinkey`, `@join`, keypad keys over serial) do
not reach the box. Until the firmware reads input from the USB port too,
enter the field join key in the setup portal's "Field join key" field
instead (BRING_UP.md step 10b).

## 12. Hand-off to bring-up

Continue with [`firmware/esp32/docs/BRING_UP.md`](../../firmware/esp32/docs/BRING_UP.md),
from step 1. Things to know first:

- **Skip the eFuse key provisioning** (the "production only" step) on your
  first box. Burning an eFuse cannot be undone.
- **Board revision:** the firmware must match the chip you read in
  [section 6](#6-board-revision-and-antennas). With the wrong one the radio
  hears little or transmits weakly; if BRING_UP.md's radio step looks
  wrong, check this first.
- **No game use before the transmit-power check** of BRING_UP.md (radio
  step): the 14 dB front-end gain the firmware assumes has not been
  measured yet.
- **Vext:** the standard build does not power its parts from it; check the
  hub's 3V3 rail where BRING_UP.md says "check Vext" for an external part.
- **The board's own small OLED** stays dark: the firmware does not use it
  yet.
- On USB with the switch off, the gauge reports "not found" and the ring and
  amplifier are unpowered. That is expected; switch on to test them.

**Changing a firmware setting** (for a part that differs from the standard
build): after one build, open `firmware\esp32\sdkconfig` (not tracked by
git), change the line, save, and run `python tools\docker_fw.py build`
again, then flash. Common changes:

| Your build | Line in `sdkconfig` |
| --- | --- |
| V4.2 board | `CONFIG_ATALAIA_BOARD_HELTEC_V4_2=y` and `# CONFIG_ATALAIA_BOARD_HELTEC_V4_3 is not set` |
| ST7789 display | `CONFIG_ATALAIA_DISP_ST7789=y` and `# CONFIG_ATALAIA_DISP_ILI9341 is not set` |
| Backlight wired to 3V3 | `CONFIG_ATALAIA_DISP_BL_PIN=-1` |
| PCF8574A expander | `CONFIG_ATALAIA_KP_I2C_ADDR=0x38` (or the address its jumpers give) |
| 12- or 16-LED ring | `CONFIG_ATALAIA_LED_COUNT=12` (or 16) |
| Antenna with more than 2 dBi | `CONFIG_ATALAIA_RADIO_ANTENNA_GAIN_DBI=` its gain, rounded **up** |
| Two-team box, free the pins | `CONFIG_ATALAIA_BTN3_PIN=-1` and `CONFIG_ATALAIA_BTN4_PIN=-1` (optional) |

Never lower `CONFIG_ATALAIA_RADIO_FEM_GAIN_DB` or the antenna gain below the
real values. Anything you change by hand is lost when you delete
`sdkconfig`; keep a note of it inside the box lid.

## 13. Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| No COM port appears | Charge-only USB cable or panel extension: try a known data cable straight into the board, and another USB port. Firmware that crashes very early can hide the built-in USB port: put the board in download mode by hand (hold PRG, tap RST, release PRG) and flash again |
| Typed console commands do nothing | Known limitation on the V4: console input is read from UART0, not USB ([section 11](#11-first-flash)) |
| esptool: "Failed to connect" | Put the board in download mode by hand (hold PRG, tap RST, release PRG); use `-b 115200`; close miniterm or any other program holding the port |
| Boot loop, "brownout" in the log | Weak USB port or cable; low battery; a short on 3V3. If it happens when the screen and NFC start, the board's 3.3 V supply may be overloaded: report it ([section 7](#7-power-and-battery-safety)) |
| Log shows the Wokwi settings (GPIO keypad, setup skipped) | `firmware\esp32\sdkconfig` was from a Wokwi or modem build: [section 11](#11-first-flash), step 1 |
| `PCF8574 keypad not found at 0x20` | SDA/SCL swapped or not on the hub; module not powered; address jumpers not all at GND; a PCF8574**A** (set `CONFIG_ATALAIA_KP_I2C_ADDR=0x38`) |
| Wrong digits, or a whole row or column dead | Rows and columns swapped or misidentified: redo [section 9.3](#93-keypad) |
| `PN532 NFC reader not found at 0x24` | Mode switches not on I2C (power-cycle after changing them); SDA/SCL swapped |
| `MAX17048 battery gauge not found` | Switch off (the gauge is powered from the battery); battery-sense wire missing |
| No I2C device found at all | SDA and SCL swapped or shorted at the hub; a module dragging the bus (unplug them one by one); 3V3 missing |
| Display white or garbled | Wires too long or loose (keep under 15 cm); CS/DC/RESET swapped; wrong controller selected (ILI9341 vs ST7789) |
| Display mirrored, upside down or wrong colours | Not a wiring fault: BRING_UP.md step 3 |
| Display dark but the log says it initialised | Backlight: LED pin wiring, or the backlight check in [section 9.4](#94-display) |
| LED ring dark | Switch off (no 5 V on USB alone); DOUT used instead of DIN; 74AHCT125 missing, reversed or a 74HC part; pin 1 not at GND |
| LED ring flickers or shows wrong colours | Missing capacitor; long data wire; no common GND between the hub and the ring's power |
| A team button "presses" by itself | Long button wires picking up noise: add a 10 kohm resistor from the button's GPIO wire to 3V3 at the hub, and route the wires away from the LED ring and speaker wires |
| No sound | Switch off (amplifier on 5 V); BCLK/LRC/DIN swapped; speaker wire touching GND |
| Phone cannot see the `atalaia-XXXX` Wi-Fi | 2.4 GHz antenna missing or on the wrong connector; phone too far |
| Fuse blows at switch-on | Battery reversed (the diode did its job: fix the battery wiring) or a short on BAT+ or 5 V |
| Box does not charge | Switch off: charging needs the switch on ([section 7](#7-power-and-battery-safety)) |
| Anything hot, a smell, smoke | Switch off at once, take the fuse out, take the cells out into a fire-safe bag. Look for reversed polarity or a short before powering again |

If you find a fault that is not in this table, or a step that is wrong,
please open an issue with what you saw (photos welcome): this manual is
corrected from the first builds.

## 14. Regenerating the diagrams

For contributors who change the wiring. The diagrams are generated with
[WireViz](https://github.com/wireviz/WireViz) 0.4.1 and Graphviz 2.42 in
Docker, from the YAML files in [`wiring/`](wiring/):

```
python tools/docker_hw.py render
python tools/docker_hw.py check
```

The YAML never spells out a board GPIO number: it writes
`GPIO<ATALAIA_BTN1_PIN>`, and `render` fills in that symbol's default from
`firmware/esp32/main/Kconfig.projbuild`. So when a pin default changes in
the firmware, run `render` again (and update the
[pin table](README.md#peripheral-pins)); nothing in the YAML changes.

`render` rewrites the SVG and PNG of both diagrams; commit them with the
YAML. `check` (or `python3 tools/check_wiring.py` with PyYAML installed)
fails if a Kconfig pin is not wired where the firmware expects it, if a
board-internal, front-end-module (GPIO 5, 46) or boot-strap pin is wired,
if two pins share a GPIO, if the keypad is not wired the way the firmware
scans it, if the pin table disagrees with Kconfig, or if an SVG was not
rendered from the current YAML and Kconfig defaults. It warns, without
failing, about the pins on the board's GNSS connector.

---

Licence: this manual is CC-BY-SA-4.0; the wiring diagrams and their sources
are CERN-OHL-S-2.0, like the rest of the hardware designs
([LICENSING.md](../../LICENSING.md)).
