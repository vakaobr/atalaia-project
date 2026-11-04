<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Expansion port build guide

Portuguese (pt-PT): [BUILD.pt.md](BUILD.pt.md).

How to fit a box with the **expansion port**: the waterproof 5-pin M12 socket
that modules plug into from outside (the [target addon](../target-addon/BUILD.md)
now, contacts and other sensors later), and the small **port board** behind it
that keeps a wet, shorted or static-charged cable from taking the box down.
Written for a club member who can solder header pins and wires and use a
multimeter, like the [Field Box build manual](../field-box/BUILD.md), which
this guide follows and refers to for every step the builds share.

> **Status: designed, not yet built.** The port, its pin-out, its protection
> and its addresses are decided (draft RFC "The expansion port",
> [`docs/rfcs/0000-expansion-port.md`](../../docs/rfcs/0000-expansion-port.md),
> decisions EXP-1 to EXP-15, approved by the maintainer on 2026-11-03); the
> register protocol modules speak is
> [`protocol/expansion-port.md`](../../protocol/expansion-port.md). **No port
> has been built from this guide**. The box's firmware uses the port since
> increment 8 of the RFC's plan: the port driver (`firmware/esp32/main/expansion.c`,
> increment 6) runs in the box's game task, finds modules at 0x58-0x5F within
> 2 s of being plugged in and reads them; the target module's firmware is
> built too ([target addon guide](../target-addon/BUILD.md)). Both are tested
> on a computer only, not yet on a real port ([section 8](#8-checks-and-tests)). The pin table is checked automatically against the
> firmware's defaults (`python3 tools/check_wiring.py`). Steps marked
> **Verify at the first build** are open questions; please report what you
> find in an issue. Photos will be added after the first build (plan phase
> HW2); this guide never uses mock-up or generated photos.

**Not for outputs, as a rule.** A siren, a strobe or a smoke machine's remote
takes the **simple output** (one GPIO, an RC relay switch, an M8 socket:
[Field Box manual, section 9.10](../field-box/BUILD.md#910-simple-output-optional)),
the preferred output path (EXP-31). The port is for **inputs**, and later for
an I2C output module on a box that needs more channels or feedback.

## Contents

1. [What you are building](#1-what-you-are-building)
2. [What is decided and what is not](#2-what-is-decided-and-what-is-not)
3. [Parts, and what each protects against](#3-parts-and-what-each-protects-against)
4. [Tools and safety](#4-tools-and-safety)
5. [The port's pins](#5-the-ports-pins)
6. [Addresses on the bus](#6-addresses-on-the-bus)
7. [Assembly, step by step](#7-assembly-step-by-step)
8. [Checks and tests](#8-checks-and-tests)
9. [Troubleshooting](#9-troubleshooting)

## 1. What you are building

The port is the box's own I2C bus (the bus of the keypad expander, the NFC
reader, the battery gauge and the board's OLED, on GPIO 17 and 18) taken out
of the enclosure through an M12 socket. It uses **no GPIO**, so no pin table
of any box changes (EXP-2). Between the bus and the socket sits the port
board:

```
box's I2C bus (hub rails)          port board                                  M12 socket (panel)
  3V3 ──── Schottky diode ── PTC fuse 50 mA ────────────────┬── TVS (VBUS) ──── pin 1  3.3 V (about 3.0 V)
  SDA ──── buffer SDAIN │ SDAOUT ── 2.2 kohm to port 3.3 V ─┴─ 100 ohm ── TVS ── pin 2  SDA
  SCL ──── buffer SCLIN │ SCLOUT ── 2.2 kohm to port 3.3 V ─── 100 ohm ── TVS ── pin 4  SCL
  GND ──────────────────┴─────────────────────────────────────────── TVS GND ── pin 3  GND
                                                                                 pin 5  not connected
```

- The **hot-swap buffer** (TCA4307) joins the port to the box's bus only when
  both are idle, and cuts the port off when something on the cable holds SDA
  or SCL low, clocking the stuck module free. The box's keypad, NFC reader,
  gauge and OLED carry on.
- The **TVS array** and the **100 ohm series resistors** take static from a
  hand or a cable at the socket.
- The **PTC fuse** limits a short between pins 1 and 3; the **Schottky diode**
  stops anything on the cable feeding the box's 3.3 V rail backwards.

Fitted on the **Field Box, the Satellite and the I/O pod**, each optional: only
a box that carries a target or a sensor needs one (EXP-2). Approximate cost:
socket €3-6, buffer €2-6 (a breakout), the TVS, fuse, diode and resistors
€1-2, plus a perfboard and wire (RFC section 1; hobby-market prices, not a
quote).

## 2. What is decided and what is not

Decided (with where each decision comes from):

| What | Decided | Where |
| --- | --- | --- |
| Connector | M12 A-coded 5-pin (IEC 61076-2-101). Pin-out: 1 brown 3.3 V, 2 white SDA, 3 blue GND, 4 black SCL, 5 grey reserved, **not connected** | EXP-1; P5J-20 |
| Socket gender | A **female** panel socket on the box (its contacts are recessed, and pin 1 is live); a male panel connector on the module; between them a ready-made **male-to-female** M12 A-coded 5-pole sensor extension cable | This guide (EXPI10-2) |
| Supply | 3.3 V for a module's **logic only**, at most **25 mA**; loads never take power from the box | EXP-3; P5J-16 |
| Protection | Hot-swap buffer with stuck-bus recovery, low-capacitance TVS array, 100 ohm series resistors, PTC fuse (about 50 mA hold), back-feed Schottky diode; 2.2 kohm pull-ups on the port side | EXP-4 |
| Exact parts | TCA4307 buffer, a USBLC6-2SC6-class TVS array, a 50 mA-hold radial PTC, a BAT85-class Schottky diode ([section 3](#3-parts-and-what-each-protects-against)) | This guide (EXPI10-3 to EXPI10-6) |
| Bus | I2C at **100 kHz** (set by the PN532), polled, no interrupt line | EXP-5, EXP-6, EXP-8; P5J-17, P5J-18 |
| Cable | At most **2 m** of 5-core M12 sensor cable. Further away: a Satellite next to the target | EXP-5; P5J-17 |
| Pull-ups in modules | **None.** The port board has them | EXP-4; P5J-17 |
| Addresses | Modules answer at **0x58-0x5F**; inputs (the target module) default to 0x58, outputs to 0x5C; at most 4 modules on a box | EXP-7 ([section 6](#6-addresses-on-the-bus)) |
| What may plug in | Modules with a processor that speaks the expansion protocol v1. **Not** bare PCF8574 or MCP23017 relay boards | EXP-9, EXP-15 |

Not decided, or not built yet:

- **The box's firmware for the port on real hardware** (increments 6 and 8 of
  the RFC's plan): built and tested on a computer, not yet against a real port
  and module.
- **A carrier PCB** with the port board on it (phase 5's later carrier board);
  until then, perfboard.
- **The bench results** of [section 8](#8-checks-and-tests): rise times, the
  buffer's recovery, the fuse, static, hot-plug. Values that the first build
  may change are marked **Verify at the first build**.
- **A wiring diagram**: the port is not in the Field Box's WireViz diagrams
  yet; one may follow its first build.

## 3. Parts, and what each protects against

One set per port. Each part is named by type and by an example part number
that fits; an equivalent with the same ratings works.

| # | Part | Qty | What it is for, and what it protects against | What to check |
| --- | --- | --- | --- | --- |
| 1 | M12 A-coded 5-pin **female** panel socket, IP67, front-mounted, with pre-wired leads or solder cups | 1 | The port itself. A sealed, keyed connector: the A-coding stops a cable going in rotated | **A-coded**, **5-pin** (not 4, not 8, not B- or D-coded); IP67 with its cap and when mated. Its thread (often PG9 or M16) gives the hole size |
| 2 | Dust cap for the socket, on a lanyard | 1 | Keeps water and grit out while nothing is plugged in | Fits the socket's thread |
| 3 | M12 A-coded 5-pole sensor extension cable, **male to female**, 1-2 m | 1 per module | Carries the bus to the module. The usual colours match the pin-out (brown, white, blue, black, grey) | **Shielded is not needed**; check the colours with a meter (pin to wire) before trusting them |
| 4 | **TCA4307** hot-swap I2C buffer with stuck-bus recovery, on a breakout | 1 | **A shorted or wet cable holding SDA or SCL low** would stop the keypad, NFC reader, gauge and OLED: the buffer connects the port only when both sides are idle, cuts it off when a port line stays low (about 30 ms), and clocks the stuck module free. It also keeps the cable's capacitance off the box's bus | Its labels: VCC, GND, SDAIN, SCLIN, SDAOUT, SCLOUT, EN, READY. Note any pull-up resistors on the breakout ([step 3](#7-assembly-step-by-step)). The LTC4307 does the same job; its pins differ |
| 5 | Low-capacitance TVS (ESD) array with a supply-rail pin, **USBLC6-2SC6** class (SOT-23-6), on a SOT-23-6 to DIP adapter | 1 | **Static from a hand, or a cable rubbing on clothes**, at the socket: clamps SDA, SCL and pin 1's 3.3 V to GND before the charge reaches the buffer | Working voltage at least 3.3 V and at most 5.5 V; a few pF per line (a through-hole power TVS of several nF would slow the bus down) |
| 6 | 100 ohm resistors, 1/4 W | 2 | With the TVS: **limit the current of a static discharge** into the buffer's port pins, on SDA and SCL | |
| 7 | 2.2 kohm resistors, 1/4 W | 2 | The port side's **pull-ups** to the port's 3.3 V; modules carry none | Less if the breakout already has pull-ups on its OUT side ([step 3](#7-assembly-step-by-step)) |
| 8 | Resettable fuse (PTC), **50 mA hold**, radial (MF-R005 class) | 1 | **A short between pins 1 and 3** (a crushed cable, water in the plug): it heats up and limits the current, so the box does not brown out, and resets when the short is gone | Hold current about 50 mA (trip about 100 mA), rated for at least 6 V |
| 9 | Small Schottky diode, **BAT85** class (or 1N5817) | 1 | **Something on the cable feeding pin 1** (a miswired module with a supply of its own): nothing can feed the box's 3.3 V rail backwards. The module sees about 3.0 V | Low forward voltage (about 0.3 V at 25 mA) |
| 10 | 100 nF ceramic capacitor | 1 | Decouples the buffer's VCC | Often already on the breakout |
| 11 | Perfboard, about 3 x 4 cm, pin headers, 0.25 mm² stranded wire in the colours below, heat-shrink | 1 set | The port board, wired to the hub's rails | |
| 12 | Label "EXPANSION 3.3 V" | 1 | Says what the socket is | Not to be confused with the simple output's "OUTPUT 1" M8 socket |

## 4. Tools and safety

The tools are the Field Box's ([manual, section 3](../field-box/BUILD.md#3-tools-and-consumables)),
plus a fine-tipped iron for the SOT-23-6 adapter (or buy the TVS already on
one). Read its [safety rules](../field-box/BUILD.md#4-safety-rules); they all
apply. For the port in particular:

1. **Battery out, fuse out, switch off, USB unplugged** while you solder or
   wire the port board.
2. **3.3 V only, on every pin, always.** The port is the box's 3.3 V bus: no
   5 V, no battery voltage, nothing from a module's own supply ever reaches it
   (EXP-3, P5J-15). A module that pulls SDA or SCL above 3.3 V can damage the
   box's board.
3. **Pin 5 stays not connected** at both ends: never a supply, never a signal
   (EXP-1).
4. **Never power a load from the port.** Its 25 mA are for a module's
   processor and sensor. Lights, relays, sirens and smoke machines bring their
   own supply; a single WS2812 LED already draws up to 60 mA.
5. **Never plug a bare PCF8574 or MCP23017 relay board (or any "I2C relay
   board" without a processor of its own) into the port.** It has no lease, so
   a relay stays on if the box crashes; it answers where the box looks for its
   keypad expander, so a box without a keypad would click its relays every
   10 ms; its relays may all switch on at power-up; and its coils would run
   from the port's 3.3 V (EXP-15).
6. **Never mains.** Nothing on either side of the port ever touches mains
   wiring (EXP-17).
7. **Static.** Touch the box's GND (or wear a strap) before handling the port
   board, and before plugging a module in at the bench.
8. **Cap the socket** when nothing is plugged in; the port is only waterproof
   capped or mated. Route the cable on the ground away from players' feet and
   **never in the line of fire**: only a target's plate is shot at.
9. **A game prop**: the box keeps its bright colour and "GAME PROP" labels.

## 5. The port's pins

The port uses no GPIO of its own: its SDA and SCL are the box's I2C bus, behind
the buffer. The GPIO numbers are the defaults in
[`firmware/esp32/main/Kconfig.projbuild`](../../firmware/esp32/main/Kconfig.projbuild);
`python3 tools/check_wiring.py` fails if this table disagrees with them or with
the pin-out of EXP-1 (each pin's colour, signal and number, the bus's GPIOs and
options, nothing on pin 5).

<!-- check_wiring: expansion-port-pins -->
| M12 pin | Wire colour | Signal | Bus GPIO | Firmware option | On the port board | Level |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | brown | 3.3 V | -- | -- | hub 3V3 rail, Schottky diode (band towards the port), PTC fuse, TVS VBUS pin, socket pin 1 | about 3.0 V, at most 25 mA |
| 2 | white | SDA | 17 | `ATALAIA_NFC_SDA_PIN` | hub SDA rail to the buffer's SDAIN; SDAOUT with 2.2 kohm to the port's 3.3 V, then 100 ohm and a TVS line to socket pin 2 | 3.3 V, 100 kHz |
| 3 | blue | GND | -- | -- | hub GND rail, the buffer's GND, the TVS GND, socket pin 3 | 0 V |
| 4 | black | SCL | 18 | `ATALAIA_NFC_SCL_PIN` | hub SCL rail to the buffer's SCLIN; SCLOUT with 2.2 kohm to the port's 3.3 V, then 100 ohm and a TVS line to socket pin 4 | 3.3 V |
| 5 | grey | not connected | -- | -- | nothing: cut the lead short and insulate it | reserved |

On a Satellite the same bus's option is called `ATALAIA_BATT_SDA_PIN` /
`ATALAIA_BATT_SCL_PIN` (the gauge's name for it): the same GPIO 17 and 18.

**The buffer's own pins:** VCC to the hub's 3V3 rail (the box's side, before
the diode), GND to the GND rail, **EN to VCC** (always enabled; the port has
no GPIO to switch it), READY not connected.

SDA and SCL are on pins 2 and 4, across the connector from each other rather
than side by side (P5J-20). Looking at the box's female socket from outside,
pins 1-4 go round the edge and pin 5 is in the middle; check the numbers
printed on your socket's datasheet before soldering.

## 6. Addresses on the bus

Every module answers at an address of its own in **0x58-0x5F** (EXP-7), clear
of every address the box uses or looks at:

| Address | What | Notes |
| --- | --- | --- |
| 0x00-0x07, 0x78-0x7F | I2C reserved ranges | Never used |
| 0x20-0x27, 0x38-0x3F | Where the box looks for its keypad expander (PCF8574 / PCF8574A) | The reason bare PCF8574 relay boards are refused (EXP-15) |
| 0x24 | PN532 NFC reader | Inside 0x20-0x27: the keypad search skips it |
| 0x36 | MAX17048 battery gauge | |
| 0x3C | The board's OLED | |
| **0x58-0x5B** | **Input modules**: the target module at **0x58**; its two solder jumpers add 1-3 for a second, third or fourth | |
| **0x5C-0x5F** | **Output modules** (the later I2C output module) at **0x5C**, jumpers 0x5D-0x5F | |

**At most 4 modules on one box**: the bus's time (each input module's poll is
about 5 % of the bus) and the 25 mA each takes from the same 3.3 V rail are
the limits. The port takes **one cable**: more than one module on one box
needs a splitter, which is **not designed yet**; one module per box is what
this guide builds.

## 7. Assembly, step by step

<!-- PHOTO: expansion-port-board.jpg | the finished port board, both sides, with the buffer breakout, the TVS on its adapter, the fuse and the diode -->
> **Photo to be added after the first build:** the finished port board, both
> sides.

1. **Where the socket goes.** On the enclosure's side or bottom, away from the
   antennas and the simple output's M8 socket, where a cable on the ground
   comes in without a sharp bend, and **not facing the shooters** when the box
   stands on the field. Drill the hole its datasheet gives (often PG9 or M16),
   deburr it, fit the socket with its O-ring on the outside and tighten the
   nut by hand plus a quarter turn. Fit the cap's lanyard.
2. **Lay out the port board.** On a perfboard of about 3 x 4 cm: a 4-pin
   header "BUS IN" (3V3, GND, SDA, SCL) at one edge, the buffer breakout, the
   TVS on its adapter as close as possible to a 5-pin header "SOCKET" at the
   other edge, and between them the diode, the fuse, the two 100 ohm and the
   two 2.2 kohm resistors. Keep the "BUS IN" side and the "SOCKET" side apart:
   the buffer stands between them.
3. **The breakout's own resistors.** Many TCA4307 breakouts carry pull-ups
   (often 10 kohm) on one or both sides. With the breakout unpowered, measure
   SDAIN to VCC, SCLIN to VCC, SDAOUT to VCC and SCLOUT to VCC. Pull-ups on the
   **IN** side add to the box's bus pull-ups: the box's bus must still read
   between **1 kohm and 3.9 kohm** to 3V3 with every part of the box fitted
   (P5J-17: fast enough edges, and under 3 mA for a part to pull low).
   On the **OUT** side the port wants about **2.2 kohm in total**: if the
   breakout has its own there, choose the added resistor so the two in
   parallel come to about 2.2 kohm, or cut the breakout's jumper if it has
   one. Note what you found in the issue for your build.
4. **Supply path.** Hub 3V3 to "BUS IN" 3V3, to the buffer's VCC (with the
   100 nF to GND if the breakout has none) and to the diode's **anode**; the
   diode's **cathode** (the band) to the fuse; the fuse's other leg is the
   **port's 3.3 V** node: to the TVS's VBUS pin, to the two 2.2 kohm
   resistors and to "SOCKET" pin 1. The buffer's **EN** to its VCC.
5. **Signals.** "BUS IN" SDA to SDAIN, SCL to SCLIN. SDAOUT to one 2.2 kohm
   (to the port's 3.3 V) and to one 100 ohm; the 100 ohm's other end to a TVS
   I/O line and to "SOCKET" pin 2. The same for SCLOUT, the second 2.2 kohm
   and 100 ohm, the other TVS I/O line and "SOCKET" pin 4. On a USBLC6-2SC6
   each line has two pins (1 and 6 are I/O 1, 3 and 4 are I/O 2): join each
   pair, as its datasheet shows.
6. **Ground.** "BUS IN" GND to the buffer's GND, the TVS's GND pin and
   "SOCKET" pin 3, by short, direct wires: the TVS is only as good as its
   path to GND.
7. **Socket leads.** From the "SOCKET" header to the socket's pins, under
   10 cm, in the cable's colours: pin 1 brown, 2 white, 3 blue, 4 black.
   **Pin 5's lead is cut short and insulated** with heat-shrink: it goes
   nowhere. Heat-shrink every solder cup.
8. **To the box.** Four wires, under 15 cm, from "BUS IN" to the hub's 3V3,
   GND, SDA and SCL rails ([Field Box manual, section 8](../field-box/BUILD.md#8-the-interconnect-board);
   the Satellite and the I/O pod have the same rails). Fix the port board on
   standoffs or with double-sided foam tape, away from the 5 V and battery
   wiring, and tie the wires so nothing pulls on a joint.
9. **Label** the socket "EXPANSION 3.3 V" on the outside.

## 8. Checks and tests

### 8.1 Before any power (meter, battery out, USB unplugged)

- [ ] Socket pin 1 to pin 3: **no continuity** (a reading of some kohm is
      the TVS and pull-ups; a beep is a short).
- [ ] Socket pin 5 to every other pin and to the enclosure's metal parts:
      **open**.
- [ ] Diode test from the hub's 3V3 (red probe) to the fuse's diode leg: about
      0.2-0.4 V; reversed: open. The band points towards the port.
- [ ] Socket pin 2 to SDAOUT and pin 4 to SCLOUT: about **100 ohm** each.
- [ ] SDAOUT and SCLOUT to the port's 3.3 V node: about **2.2 kohm** each
      (the breakout's own included).
- [ ] The hub's SDA to 3V3 and SCL to 3V3: between **1 kohm and 3.9 kohm**,
      every module of the box fitted ([step 3](#7-assembly-step-by-step)).
- [ ] No continuity from any socket pin to the 5 V rail or to BAT+.

### 8.2 First power, nothing plugged in

1. Power the box from USB (switch off, as in the
   [Field Box manual, section 10](../field-box/BUILD.md#10-first-power-on)).
   Measure socket pin 1 to pin 3: about **3.0 V** (the 3.3 V rail less the
   diode). Pins 2 and 4 to pin 3: the same, idle high.
2. The box boots as before; in the [bring-up checklist](../../firmware/esp32/docs/BRING_UP.md)
   the keypad (step 5), the NFC reader (step 7) and the gauge (step 9) still
   work. Repeat with the 2 m cable plugged into the socket and nothing on its
   far end.

### 8.3 Bench tests

The RFC's bench list (section 7, "Bench tests"), for the port; each needs the
box's firmware and, where it says so, a module. Report the results in an
issue: they settle the **Verify at the first build** items.

| RFC test | What | Needs | When |
| --- | --- | --- | --- |
| 1 | Rise time of SDA and SCL at the cable's far end, 2 m of cable, 100 kHz: **under 1 µs** (a scope). The estimate: 2.2 kohm and about 250 pF give about 0.5 µs. The keypad, NFC reader and gauge still work with a module plugged in | Scope; a target module | Now |
| 2 | Short SDA to GND at the cable's far end: the box's keypad keeps working; the port is back within a second of removing the short, and the module with it | The box's firmware (the keypad); a target module | Now |
| 4 | Short pins 1 and 3 at the cable's far end: the box does not reset; the fuse warms and recovers when the short goes. The target module's current under 25 mA | A target module for the current | Now |
| 9 | Touch the socket's pins and the cable's shell after walking on a carpet or a dry field: the box carries on | -- | Now |
| 3 | 100 plug and unplug cycles during a running game: no box reset, no stuck bus, each plug-in found within 2 s | A target module | Now (the log line below for each plug-in) |
| 6 | Noise: a target module next to a switching 12 V siren and strobe for 30 minutes; count CRC errors and missed polls | A target module | Now (`@modules` before and after: its `polls`, and the log's lost and found lines) |

What the box says about the port, on its serial log (USB, 115200 baud;
[BRING_UP.md](../../firmware/esp32/docs/BRING_UP.md), the port's step):

| Line | When |
| --- | --- |
| `expansion: 0x58 added: 58:target/1.0.0:hit` | A module found, at boot or within 2 s of being plugged in |
| `expansion: 0x58 lost (no_answer)` | A module that stopped answering (25 failed reads: 0.5 s for a target) |
| `expansion: 0x58 lost (bad_ident)` | Another module plugged in at the same address |
| `expansion: hit hit, strength 180` | A hit taken during a game (the plate armed by the mode) |
| `expansion: 0x58 dropped events (its queue was full)` | The module held more than 16 hits before the box read them |

`@modules` on the serial console lists the modules
(`[{"address":"58","model":"target","fw":"1.0.0","caps":["hit"],"armed":0,"events":0,"polls":1234}]`),
and in a game the GM console shows each module as a chip under its box.

## 9. Troubleshooting

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| Keypad, NFC reader or gauge stop working once the port board is fitted | A short on the "BUS IN" side, or too strong pull-ups (the breakout's IN side added to the box's own) | Check 8.1 again; measure the hub's SDA and SCL to 3V3 (1-3.9 kohm) |
| Pin 1 reads 0 V | The diode the wrong way round, the fuse tripped (a short on the cable or the socket), or a broken joint | Unplug the cable, wait a minute for the fuse to cool, measure again; check the diode's band |
| Pin 1 reads 3.3 V or more | The diode is bridged or missing | Fix the supply path: pin 1 must come through the diode |
| SDA or SCL read 0 V at the socket with nothing plugged in | A short to GND at the socket or the TVS; or the buffer is holding the port off because a line is low | Check for a solder bridge at the TVS adapter and the socket's cups |
| The box resets when a cable is plugged in | A short between pins 1 and 3 in the cable, too much capacitance on pin 1, or the fuse missing | Check the cable pin to pin; there must be no capacitor larger than 100 nF on the port's 3.3 V |
| A module is not found (no `expansion: ... added` line within 2 s) | Its address (0x58-0x5F; the keypad's own expander sits at 0x20-0x27), its cable, its supply (about 3.0 V at its end), its firmware (flashed?) | Measure pin 1 at the module's end; reflash the module; `@modules` on the box's console |
| A module comes and goes (`added`, `lost (no_answer)` again and again) | A loose connector, a long or unshielded cable, the fuse tripping | Check the cable pin to pin, and pin 1's voltage while it happens |

---

Licence: this guide is CC-BY-SA-4.0; the port's design is CERN-OHL-S-2.0, like
the rest of the hardware ([LICENSING.md](../../LICENSING.md)).
