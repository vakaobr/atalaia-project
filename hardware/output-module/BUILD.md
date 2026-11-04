<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# I2C output module build guide

Portuguese (pt-PT): [BUILD.pt.md](BUILD.pt.md).

The **I2C output module** plugs into a box's [expansion port](../expansion-port/BUILD.md)
and switches up to four loads (a siren, a strobe, a horn, a smoke machine's
low-voltage remote) through relays or MOSFETs, from **a supply of its own**,
behind an **I2C isolator**, so the box and the loads never share a wire. A
small RP2040 board runs its firmware: the box keeps each output on only while
it keeps writing to it (the lease), and the module holds its own hard limits.
Written for a club member who can solder header pins and wires and use a
multimeter, like the [Field Box build manual](../field-box/BUILD.md), which
this guide follows and refers to for every step the builds share.

> **Status: designed, not yet built; later and optional.** The module is
> decided in the draft RFC "The expansion port"
> ([`docs/rfcs/0000-expansion-port.md`](../../docs/rfcs/0000-expansion-port.md),
> section 3 (b), decisions EXP-16 and EXP-17, approved by the maintainer on
> 2026-11-03), and it speaks the expansion protocol v1
> ([`protocol/expansion-port.md`](../../protocol/expansion-port.md)). **Its
> firmware is written and tested on a computer only**
> ([`firmware/output-module/`](../../firmware/output-module/README.md),
> increment 11): it builds for the RP2040 and CI makes its UF2 file with the
> target module's (`tools/docker_module.py`), but **it has never run on a
> board**. **No module has been built from this guide**, and the box's side
> that finds the module and drives its outputs (increment 8) has never been
> tried with a real module. Steps marked **Verify at the first build** are
> open questions; please report what you find in an issue.
> [Section 12](#12-what-waits-for-the-bench) lists what waits.
> Photos will be added after the first build (plan phase HW2); this guide
> never uses mock-up or generated photos.

**Use the simple output first.** For one siren, one strobe or one smoke
remote, the **simple output** (one GPIO, an RC relay switch, an M8 socket:
[Field Box manual, section 9.10](../field-box/BUILD.md#910-simple-output-optional))
is the preferred path (EXP-31): cheaper, simpler, no firmware of its own. This
module is for a box that needs **more channels** than it has free GPIOs, or
wants to know that the loads' supply is there (`SUPPLY_OK`).

> **NEVER MAINS.** This module switches **SELV loads only: at most 24 V DC,
> at most 2 A per channel** (EXP-17). Nothing in it, on it or wired to it ever
> touches mains (230 V or 110 V) wiring, not even through a relay rated for it.
> A field that wants to switch a mains device uses a commercially made,
> CE-marked (or locally certified), enclosed switching unit with a
> low-voltage control input, installed as its maker says, and drives that
> input from one of this module's dry contacts.
>
> **SMOKE MACHINES: ONLY THROUGH THEIR DOCUMENTED LOW-VOLTAGE REMOTE INPUT**
> (a contact input, a 0-5 V or 12 V trigger written in the maker's manual), or
> a battery smoke device made to be triggered by a contact. **Many cheap mains
> fog machines carry mains voltage on their wired remote's cable: never wire a
> relay into one, and never open one.** If the manual does not say, in
> writing, that the remote input is low voltage, the machine is not used.
> DMX is out of scope.
>
> **Pyrotechnics, igniters and smoke grenades are out of scope, always.**

## Contents

1. [What you are building](#1-what-you-are-building)
2. [What is decided and what is not](#2-what-is-decided-and-what-is-not)
3. [Parts](#3-parts)
4. [Tools and safety](#4-tools-and-safety)
5. [The two sides: the isolator](#5-the-two-sides-the-isolator)
6. [The module's own supply](#6-the-modules-own-supply)
7. [Relays or solid-state](#7-relays-or-solid-state)
8. [Loads: dry contacts, fuses and flyback diodes](#8-loads-dry-contacts-fuses-and-flyback-diodes)
9. [The pins](#9-the-pins)
10. [Assembly, step by step](#10-assembly-step-by-step)
11. [Checks, flashing and first power-up](#11-checks-flashing-and-first-power-up)
12. [What waits for the bench](#12-what-waits-for-the-bench)
13. [Troubleshooting](#13-troubleshooting)

## 1. What you are building

```
          BOX SIDE (the port's 3.3 V, a few mA)  ║  MODULE SIDE (its own supply, its own ground)
                                                 ║
box port ── M12 cable ── M12 male ── P-MOSFET ── isolator ── RP2040 board ── relay board ── dry contacts ── loads
 (EXP-1)     ≤ 2 m       connector  (reverse    side 1 ║ side 2   GP6-GP9     (or MOSFET    (relay COM/NO)   (each on its
                                     cable)            ║          GP26 sense   board)                         own battery
                                                       ║                                                      and fuse)
                                                       ║  9-15 V in ── fuse ── reverse diode ── buck 5 V ──┬── RP2040 board (5 V / VSYS)
                                                       ║                                                    └── relay coils
```

- **The box side** is the M12 connector and the isolator's side 1, powered
  from the port's 3.3 V (pin 1). It is the only load the module puts on the
  port: a few mA, well under the port's 25 mA (EXP-3, EXP-16).
- **The isolator** (ISO1540 / ADuM1250 class) passes SDA and SCL across a
  barrier: the box's ground and the module's ground **never connect**. A
  relay's spike, a load's short or a wrong battery stays on the module side.
- **The module side** has its own supply input (9-15 V DC, a 12 V battery is
  typical, or the siren's own pack), its own fuse and reverse-polarity
  protection, and a buck converter for 5 V, which feeds the RP2040 board and
  the relay coils.
- **The RP2040 board** runs the firmware: the expansion protocol through the
  [module core](../../firmware/module-core/README.md), the lease (every output
  off 1.5 s after the box stops writing), each channel's max on and min off,
  relays no faster than every 100 ms, every output off at power-up, after its
  watchdog and on a brown-out, and a second, independent max on (the guard).
- **The relay board** gives **dry contacts**: it closes a circuit, it carries
  no power of its own. Each load runs from its own battery, through its own
  fuse, through the contacts.

Approximate cost: €25-35 without the supply and the loads (RP2040 board €4,
isolator €4-6, relay board €3-5, buck converter €2, fuse and protection €2,
enclosure and glands €8, M12 connector €4; RFC section 3 (b), hobby-market
prices, not a quote).

## 2. What is decided and what is not

Decided (with where each decision comes from):

| What | Decided | Where |
| --- | --- | --- |
| What it is for | More output channels than the simple output, or feedback (`SUPPLY_OK`); **later and optional** | EXP-31 |
| Design | A small custom module (RP2040 board, I2C isolator, own supply) driving an off-the-shelf relay board; **never a bare PCF8574 or MCP23017 relay board on the port** | EXP-15, EXP-16 |
| Port and cable | The box's female M12 A-coded 5-pin socket; a **male** panel connector on the module; a male-to-female M12 sensor cable of at most 2 m | EXP-1, EXP-5; EXPI10-2 |
| Box side | An I2C isolator, its side 1 the only load on the port's 3.3 V (a few mA); no pull-ups on the box side (the port board has them) | EXP-3, EXP-16; P5J-17 |
| Module side | Its own input, 9-15 V DC, through a fuse and reverse-polarity protection, to a 5 V buck converter for the RP2040 board and the relay coils; never connected to the port's pins | EXP-3, EXP-16 |
| Loads | Dry contacts; **SELV only, at most 24 V DC and 2 A per channel**; **never mains**; smoke machines only through a documented low-voltage remote input; never pyrotechnics | EXP-17 |
| Relay board | An opto-isolated 1-4 channel relay board with **high-level trigger** (input high = relay on), 5 V coils; or a MOSFET board for DC loads switched often (strobes) | EXP-16; this guide ([section 7](#7-relays-or-solid-state), EXPI11-5) |
| Address | 0x5C; two solder jumpers add 1-3 (0x5D-0x5F) | EXP-7 |
| Model | `0x0002`, `out4`: 1 to 4 switched output channels | `protocol/expansion-port.md`, section 2 |
| Hard limits | Each channel's max on and min off, set at build time for what is fitted; relays no faster than every 100 ms; off at power-up, after the watchdog, on brown-out; the box and the game can only lower them | EXP-13 |
| The pins | [Section 9](#9-the-pins), from the firmware's `src/board.h`, the target module's where they apply | Firmware (EXPI11-6) |
| Exact parts | ISO1540 or ADuM1250 isolator, AO3401-class P-MOSFET on the box side, 1N5819-class input diode, MP1584 or LM2596-class buck converter ([section 3](#3-parts)) | This guide (EXPI11-4 to EXPI11-8) |

Not decided, or not built yet:

- **Everything on the bench** ([section 12](#12-what-waits-for-the-bench)):
  the isolator at the port's 3.0 V, the bus's low level through the isolator
  and the port's buffer, the relays clicking from 3.3 V, the port current, the
  lease with a stopwatch, the noise next to a switching siren.
- **A real box driving the module**: the box's side (increment 8) is tested
  on a computer only, against a simulated module.
- **A carrier PCB**: perfboard until then.

## 3. Parts

One set per module. Each part is named by type and by an example that fits;
an equivalent with the same ratings works.

| # | Part | Qty | What it is for | What to check |
| --- | --- | --- | --- | --- |
| 1 | RP2040 board: **Raspberry Pi Pico** or **RP2040-Zero** | 1 | Runs the firmware | Every pin of [section 9](#9-the-pins) is on both boards' headers |
| 2 | **I2C isolator** breakout, **ISO1540** or **ADuM1250** class | 1 | **Keeps the box's ground and the module's apart**: SDA and SCL cross a barrier, nothing else does | Two separate supply pins (VCC1, VCC2) and grounds (GND1, GND2). **Pull-up resistors on side 1 must come off** ([step 4](#10-assembly-step-by-step)); side 2 needs them |
| 3 | P-channel MOSFET for a low gate voltage, **AO3401 / SI2301** class (SOT-23, on an adapter), and a 10 kohm resistor | 1 + 1 | **A reversed hand-made cable** cannot feed the isolator backwards, with almost no voltage lost (as the target module, EXPI10-8) | V(GS)th well under 2 V |
| 4 | M12 A-coded 5-pin **male** panel connector, IP67, with leads or solder cups | 1 | The module's end of the port's cable | **A-coded**, **5-pin**; a plastic body, or a metal body that touches nothing of the module side ([section 5](#5-the-two-sides-the-isolator)) |
| 5 | 4-channel **opto-isolated relay board**, **high-level trigger** (or with a high/low trigger jumper set to high), **5 V coils** | 1 | Switches the loads: dry contacts (COM, NO, NC) | **High-level trigger**; contacts rated at least 2 A at 30 V DC; a diode across each coil on the board ([section 7](#7-relays-or-solid-state)) |
| 5b | or a 1-4 channel **MOSFET board** for DC loads, low-side, made for **3.3 V logic** | 1 | Strobes and loads switched faster than a relay should | Its MOSFETs fully on at a 3.3 V gate (R(DS)on given at V(GS) 2.5 V or lower); **no flyback diode on most such boards** ([section 8](#8-loads-dry-contacts-fuses-and-flyback-diodes)) |
| 6 | 10 kohm resistors, 1/4 W | 4 | **Pull-downs** on the relay board's inputs: every relay off while the RP2040 is in reset, unflashed or being flashed | |
| 7 | Buck converter module, input up to at least 24 V, **5 V** out, at least 1 A (**MP1584** or **LM2596** class) | 1 | 5 V for the RP2040 board and the relay coils, from the module's supply | **Set it to 5.0 V before anything is connected to its output** ([step 2](#10-assembly-step-by-step)) |
| 8 | Inline fuse holder (blade or 5 x 20 mm) and a **1 A slow-blow** fuse | 1 | **A short inside the module** (a crushed wire, a failed buck converter) blows the fuse, not the battery's wiring | The module itself draws well under 0.5 A (four 5 V coils and the board): **Verify at the first build** |
| 9 | Schottky diode, **1N5819** class (1 A, 40 V) | 1 | **A battery connected the wrong way round** cannot reach the buck converter | About 0.4 V lost: no matter at 9-15 V |
| 10 | 2-pole screw terminal or a DC barrel jack, panel mount | 1 | The module's supply input: "SUPPLY 9-15 V" | Never the same connector type as the loads' outputs or the M12 |
| 11 | Inline fuse holder and fuse **sized for each load, at most 2 A** | 1 per load | **A short in a load or its cable** blows its own fuse, at its battery | Next to the load's battery's positive terminal |
| 12 | Rectifier diode, **1N4007** class (or 1N5819 for a fast MOSFET channel) | 1 per inductive load | **Flyback**: across a motor siren, a horn, a solenoid or an external relay's coil, so its spike does not arc the contacts or kill a MOSFET ([section 8](#8-loads-dry-contacts-fuses-and-flyback-diodes)) | Its band towards the load's positive side |
| 13 | Supply sense (optional): 100 kohm and 22 kohm 1 % resistors, a 100 nF capacitor, a BAT85-class Schottky diode, a 2-pole terminal "SENSE" | 1 set | `SUPPLY_OK`: the box sees whether the loads' battery is there and above 9 V ([section 6](#6-the-modules-own-supply)) | Only with a channel marked `sense` in the firmware's channel list |
| 14 | Status LED (any colour) and a 1 kohm resistor | 1 + 1 | Blinks while the box asks `LOCATE`, fast for a fault | |
| 15 | 2-pin headers and jumper caps, or two solder pads | 2 | The address jumpers (GP2, GP3 to GND) | |
| 16 | IP65 enclosure, plastic, about 150 x 110 x 70 mm, with cable glands (PG7 / PG9) | 1 | Keeps water and grit out; the loads' cables come in through their own glands | Room for the relay board, the buck converter, the RP2040 board and the isolator, with the box side kept apart ([section 5](#5-the-two-sides-the-isolator)) |
| 17 | Screw terminals for the loads (2 or 3 poles per channel), perfboard about 7 x 9 cm, 0.25 mm² and 0.75 mm² stranded wire, heat-shrink, cable ties | 1 set | The module's board and its wiring; 0.75 mm² for the supply and the loads' current | |
| 18 | Labels: "EXPANSION 3.3 V", "SUPPLY 9-15 V DC", "OUT 1" to "OUT 4", "SELV ONLY, NEVER MAINS" | 1 set | Says what each connector is | |

**Never a bare PCF8574 or MCP23017 "I2C relay board" on the port**, even
though it needs no firmware: it has no lease (a relay stays on if the box
crashes), it answers where the box looks for its keypad expander (a box with
no keypad would click its relays every 10 ms), its relays may all switch on at
power-up, and its coils would run from the port's 3.3 V (EXP-15).

## 4. Tools and safety

The tools are the Field Box's ([manual, section 3](../field-box/BUILD.md#3-tools-and-consumables)),
plus a fine-tipped iron for the SOT-23 MOSFET (or buy it on an adapter) and a
small screwdriver for the buck converter's trimmer. Read its
[safety rules](../field-box/BUILD.md#4-safety-rules); they all apply. For the
output module in particular:

1. **Never mains** ([the warning above](#i2c-output-module-build-guide)).
   SELV loads only, at most 24 V DC and 2 A per channel. A relay board printed
   "10 A 250 V AC" is still only used at SELV here.
2. **Smoke machines only through their documented low-voltage remote
   input**; never open a fog machine, never wire into a remote cable whose
   voltage the manual does not state in writing.
3. **Supply off, loads' batteries disconnected, M12 cable unplugged** while
   you solder or wire anything.
4. **Every battery behind a fuse.** The module's supply through its own fuse
   (part 8), each load through its own (part 11), each fuse next to its
   battery's positive terminal. A 12 V lead-acid or LiFePO4 battery can
   deliver hundreds of amperes into a short: enough to melt a wire and start
   a fire.
5. **Nothing from the module side ever reaches the port.** The port is the
   box's 3.3 V bus; only the isolator's side 1 is wired to it (EXP-3,
   P5J-15). The module's supply, ground and loads never touch M12 pins 1-5.
6. **Pin 5 stays not connected** (EXP-1).
7. **Flash with the supply off and the M12 cable unplugged**
   ([section 11.3](#113-flashing)): an RP2040-Zero joins its USB 5 V straight
   to its 5 V pin.
8. **Hearing protection** near sirens and horns, at the bench too; **smoke**
   never in an enclosed room without the venue's approval; a strobe can
   trigger photosensitive epilepsy: tell the players before the game.
9. **A game prop**: bright colours, "GAME PROP" labels, nothing that looks
   like an explosive (the design specification's section 17), and outputs used
   within local law.

## 5. The two sides: the isolator

The isolator is the module's border. Everything on its **side 1** belongs to
the box; everything on its **side 2** belongs to the module. Only SDA and SCL
cross it, as signals.

| | Side 1: the box side | Side 2: the module side |
| --- | --- | --- |
| Supply | M12 pin 1 (the port's 3.3 V, about 3.0 V after the box's diode), through the P-MOSFET, to VCC1 | The RP2040 board's 3V3 pin (its own regulator, from the module's 5 V) to VCC2 |
| Ground | M12 pin 3 to GND1, **and nothing else** | GND2, the RP2040 board's GND, the buck converter's output and input negative, the relay board's GND, the supply input's negative |
| SDA, SCL | M12 pins 2 and 4 to SDA1, SCL1 | SDA2, SCL2 to GP4, GP5 |
| Pull-ups | **None** in the module: the box's port board has them (P5J-17). Remove a breakout's side 1 resistors | About **4.7 kohm** each, SDA2 and SCL2 to VCC2 (often on the breakout already; fit them if not) |
| Current | A few mA from the port: **to be measured**, at most 5 mA (RFC section 3 (b)) | From the module's supply |

Rules that keep the two sides apart:

- **No wire, track, screw or metal part joins the two sides.** On the
  perfboard, leave a gap of at least 5 mm (cut the strips) between the side 1
  wiring and everything else, under the isolator itself too.
- **The M12 connector's metal body**, if it has one, touches nothing on the
  module side: mount it in the plastic enclosure's wall, away from the relay
  board's screws. A shielded cable's shield is not connected at the module.
- The isolation here is **functional, not a safety barrier**: it keeps the
  grounds and the loads' currents apart. It is never a reason to go near
  mains.

**Verify at the first build:**

- **The isolator at about 3.0 V.** The ISO1540's and the ADuM1250's side 1
  take 3.0 V to 5.5 V; the port gives about 3.0 V (less a few mV in the
  P-MOSFET), the bottom of that range. Measure VCC1 with the module plugged in
  and working. An isolator whose side 1 starts at 2.25 V (ISO1640 class) is
  the fallback if it does not work reliably.
- **The bus's low level through the isolator and the port's buffer.** These
  isolators pull their side 1 low to a slightly raised level (a few hundred
  mV, by design, to tell their own lows from the box's). Check on a scope, at
  the box's end, that a low still reads well under the TCA4307's input
  threshold and that the box reads the module's `IDENT` every time (bench
  test, [section 12](#12-what-waits-for-increment-8-and-the-bench)).

## 6. The module's own supply

**Never from the box** (EXP-3). The module brings its own:

```
SUPPLY + ── fuse 1 A ── 1N5819 (band towards the buck) ── buck IN+ ── buck OUT+ 5.0 V ──┬── RP2040 board 5 V pin (RP2040-Zero) / VSYS (Pico)
SUPPLY − ─────────────────────────────────────────────── buck IN− ── buck OUT−  GND ───┴── relay board VCC, JD-VCC and GND
```

- **Input 9-15 V DC**: a 12 V lead-acid or LiFePO4 battery, or the siren's
  own pack. The same battery may also feed the loads, each through its own
  fuse ([section 8](#8-loads-dry-contacts-fuses-and-flyback-diodes)).
- **The fuse first**, at the battery's positive terminal, then the
  **reverse-polarity diode**: a battery the wrong way round is stopped before
  the buck converter.
- **The buck converter set to 5.0 V** before anything is connected to its
  output: its trimmer often comes set to 12 V or more, which would destroy the
  RP2040 board and the relay board.
- **5 V to the RP2040 board**: on a Pico, its VSYS pin (pin 39); on an
  RP2040-Zero, its 5 V pin. The board makes its own 3.3 V, which feeds the
  isolator's side 2, the pull-ups and the supply sense's clamp.
- **5 V to the relay board's VCC**, with its JD-VCC jumper fitted (coils and
  optocouplers from the same 5 V; the I2C isolator is what keeps the box
  apart).

The RP2040's own brown-out and power-on reset restart the module when its
supply sags too far; it comes back with every output off (EXP-13).

**The supply sense (optional, `SUPPLY_OK`).** A divider from a "SENSE" input
into GP26 (ADC0) lets the box see whether the loads' battery is there:

```
SENSE + ── 100 kohm ──┬── GP26 (ADC0)
                      ├── 22 kohm ── GND
                      ├── 100 nF ─── GND
                      └── BAT85 (band towards 3V3) ── RP2040 3V3
SENSE − ── GND (the module side's)
```

Wire "SENSE +" to the positive terminal of the battery the sensed channels'
loads run from (after its fuse), and "SENSE −" to its negative; that battery's
negative then shares the module side's ground, never the box's. 15 V reads
2.7 V at GP26; the BAT85 clamps anything above 3.3 V. The firmware reports
`SUPPLY_OK` from **9.0 V** up and drops it below **8.5 V**, filtered so a
relay's spike does not flip it, and **only for channels marked `sense`** in
its channel list ([firmware README](../../firmware/output-module/README.md#the-channel-list)):
without the divider fitted, mark none. The divider's tolerance and the RP2040's
ADC reference (its 3.3 V) set how close those thresholds are: **Verify at the
first build** against a meter.

## 7. Relays or solid-state

Each channel is either a **relay** or **solid-state**, and the firmware is
told which (its channel list, set at build time: `relay` or `solid`):

| | Relay (contacts) | Solid-state (a MOSFET) |
| --- | --- | --- |
| Board | A 4-channel opto-isolated relay board, **high-level trigger**, 5 V coils | A low-side MOSFET board for **3.3 V logic** |
| Switches | DC **and** any low-voltage load, isolated from the module: dry contacts | DC only, its negative side, sharing the module side's ground |
| Speed | No faster than every **100 ms**; patterns from 100 ms on and off (the firmware refuses faster) | Patterns from **10 ms** |
| Good for | Sirens, horns, a smoke machine's remote input, anything that wants a plain contact | Strobes and LEDs blinking fast, many times a game |
| Watch out for | Its coil current from the 5 V (about 70-90 mA each: **Verify at the first build**) | A load that needs a contact rather than a switched negative (a smoke remote: use a relay) |

**High-level trigger, and the pull-downs, are what make "off at power-up"
true.** Many cheap relay boards are **low-level trigger** (a low input turns
the relay on). An RP2040's pin is low or floating while it resets, boots or
is being flashed, and its 3.3 V high cannot reliably hold a 5 V low-trigger
input off: **such a board could switch a siren or a smoke machine on by
itself. Do not use one** (or set its trigger jumper to high). With a
high-level trigger board, a 10 kohm pull-down on each input (part 6) keeps
every relay off from the moment the supply comes on until the firmware drives
the pins, and the firmware drives them low before anything else.

**Verify at the first build:** each relay pulls in reliably from the
RP2040's 3.3 V on its input (an optocoupler board with high-level trigger
draws a few mA there), and drops out at once at 0 V.

The firmware's channel list tells the box what is fitted and the module's own
limits; for example, a siren, a strobe on a MOSFET and a smoke remote with
30 s on and 30 s off:

```
relay:siren:60:0,solid:strobe:120:0,relay:smoke:30:30
```

Set each channel's max on and min off from the device's own manual (a smoke
machine's duty cycle, a siren's). The box's admin can lower them, never raise
them (EXP-13). The UF2 file from CI and the releases carries the default
list (four relays, generic, at most 30 s on each); other loads take a build of
their own ([firmware README](../../firmware/output-module/README.md#building)).

## 8. Loads: dry contacts, fuses and flyback diodes

**A relay channel** (COM and NO; NC stays unused, so a dead module is an open
circuit):

```
load battery + ── fuse (≤ 2 A, for the load) ── COM ┤relay├ NO ── load + ── load ── load − ── load battery −
                                                                └─ 1N4007, band to load + ─┘   (inductive loads)
```

**A solid-state channel** (a low-side MOSFET: the load's negative is switched,
and the load's battery negative joins the module side's ground):

```
load battery + ── fuse (≤ 2 A) ── load + ── load ── load − ── MOSFET board OUT− ── (MOSFET) ── GND ── load battery −
                                   └─ 1N5819 (or 1N4007), band to load + ─┘
```

- **One fuse per load, at most 2 A, sized for the load**, next to its
  battery's positive terminal (EXP-17). The relay's own rating does not
  replace it.
- **Flyback diodes**: a motor siren, a horn, a solenoid, a small pump or an
  external relay's coil is **inductive**: when it switches off, its current
  jumps to a high voltage that arcs a relay's contacts and kills a MOSFET.
  Fit a diode right across the load, its band towards the positive side. A
  strobe or an LED light without a motor does not need one; if in doubt, fit
  it. Most MOSFET boards have none: on a solid-state channel the diode is
  **required** for any inductive load. The relay board's own coil diodes
  (check that they are there) protect the board, not the loads.
- **A smoke machine's remote input**: a relay channel, its COM and NO wired
  straight to the two contacts the manual names, nothing else in the circuit
  (no battery, no diode), and only if the manual says in writing that the
  input is low voltage.
- **0.75 mm² wire** for the loads (2 A), on their own glands and terminals,
  never through the M12 or the module's supply connector.

## 9. The pins

The pins are the firmware's
([`firmware/output-module/src/board.h`](../../firmware/output-module/src/board.h));
`python3 tools/check_wiring.py` fails if this table disagrees with them. Every
pin is on a Raspberry Pi Pico's and an RP2040-Zero's headers.

<!-- check_wiring: output-module-pins -->
| RP2040 pin | Firmware name | What | Wired to |
| --- | --- | --- | --- |
| GP2 | `OUT_PIN_JUMPER_A0` | Address jumper A0: closed to GND adds 1 | A jumper to the module side's GND |
| GP3 | `OUT_PIN_JUMPER_A1` | Address jumper A1: closed to GND adds 2 | A jumper to the module side's GND |
| GP4 | `OUT_PIN_SDA` | I2C0 SDA, the I2C target | The isolator's SDA2 (4.7 kohm to VCC2) |
| GP5 | `OUT_PIN_SCL` | I2C0 SCL | The isolator's SCL2 (4.7 kohm to VCC2) |
| GP6 | `OUT_PIN_CH0` | Channel 0 ("OUT 1"), high: on | The relay or MOSFET board's IN1; 10 kohm to GND |
| GP7 | `OUT_PIN_CH1` | Channel 1 ("OUT 2") | IN2; 10 kohm to GND |
| GP8 | `OUT_PIN_CH2` | Channel 2 ("OUT 3") | IN3; 10 kohm to GND |
| GP9 | `OUT_PIN_CH3` | Channel 3 ("OUT 4") | IN4; 10 kohm to GND |
| GP14 | `OUT_PIN_LED` | The status LED | LED anode; its cathode through 1 kohm to GND |
| GP26 | `OUT_PIN_SUPPLY_SENSE` | ADC0: the supply sense (optional) | The divider's middle ([section 6](#6-the-modules-own-supply)) |

The address with the jumpers: none 0x5C, A0 0x5D, A1 0x5E, both 0x5F. The
firmware reads them once at power-up. A Pico's own LED (GP25) blinks with
GP14; an RP2040-Zero's RGB LED stays dark. The module's other connections:
5 V on the Pico's VSYS (pin 39) or the RP2040-Zero's 5 V pin, its 3V3 pin to
the isolator's VCC2, its GND to the module side's ground.

**The M12 connector** (the module's male panel connector, side 1 only):

| M12 pin | Wire colour | Signal | Wired to |
| --- | --- | --- | --- |
| 1 | brown | 3.3 V from the box | The P-MOSFET's drain; its source to the isolator's VCC1; its gate through 10 kohm to GND1 |
| 2 | white | SDA | The isolator's SDA1 |
| 3 | blue | GND of the box | The isolator's GND1, **and nothing else** |
| 4 | black | SCL | The isolator's SCL1 |
| 5 | grey | not connected | Nothing: cut the lead short and insulate it |

## 10. Assembly, step by step

<!-- PHOTO: output-module-inside.jpg | the finished module open: the M12 connector and isolator kept apart from the RP2040 board, the buck converter and the relay board -->
> **Photo to be added after the first build:** the finished module, open.

1. **Plan the enclosure.** The M12 connector and the isolator in one corner
   (the box side), the supply input and its fuse in another, the relay
   board's terminals towards the loads' glands. Drill the holes, fit the
   M12 connector with its O-ring outside, the glands and the supply
   connector. Label each one (part 18).
2. **Set the buck converter**, on its own: connect only its input to the
   supply (through the fuse), turn its trimmer until a meter on its output
   reads **5.0 V**, disconnect. Mark the trimmer with a drop of paint.
3. **The supply path** on the perfboard (0.75 mm²): the input connector's +
   to the fuse holder, the fuse to the 1N5819's anode, its cathode (the band)
   to the buck's IN+; the input's − to the buck's IN−. A 2-way rail from the
   buck's OUT+ (5 V) and OUT− (GND).
4. **The isolator.** With it unpowered, measure SDA1 and SCL1 to VCC1: a
   breakout's **side 1 pull-ups must come off** (cut their jumper or remove
   the two resistors), since the box's port board pulls the bus up. Measure
   SDA2 and SCL2 to VCC2: about **4.7 kohm** each; fit two resistors if there
   are none. Mount it across the gap between the two sides of the perfboard.
5. **The box side.** The M12 connector's leads, under 10 cm, in the cable's
   colours: pin 1 brown to the P-MOSFET's drain, its source to VCC1, its
   gate through 10 kohm to GND1; pin 2 white to SDA1; pin 3 blue to GND1;
   pin 4 black to SCL1; **pin 5 grey cut short and insulated**. Nothing else
   on this side.
6. **The RP2040 board.** 5 V from the rail to VSYS (Pico) or 5 V
   (RP2040-Zero), GND to the rail's GND. Its 3V3 to the isolator's VCC2, its
   GND to GND2. GP4 to SDA2, GP5 to SCL2. The address jumpers from GP2 and
   GP3 to GND; the LED and its 1 kohm on GP14. **Leave the board's USB socket
   reachable** for flashing.
7. **The relay (or MOSFET) board.** Its VCC (and JD-VCC, jumper fitted) to
   the 5 V rail, its GND to the rail's GND. GP6-GP9 to IN1-IN4, each with
   its **10 kohm pull-down to GND** at the board's input. Fewer channels
   fitted: leave the unused GP pins unconnected (the firmware holds them low).
8. **The supply sense** (optional): the divider, its capacitor and its
   BAT85 next to GP26, and the 2-pole "SENSE" terminal ([section 6](#6-the-modules-own-supply)).
9. **The loads' terminals.** From each relay's COM and NO (or each MOSFET's
   OUT terminals) to the "OUT 1"-"OUT 4" terminals at the glands, in
   0.75 mm². The loads, their fuses and their diodes are wired outside
   the module ([section 8](#8-loads-dry-contacts-fuses-and-flyback-diodes)).
10. **Tidy.** Tie every wire so nothing pulls on a joint and nothing from the
    module side can swing across to the box side. Close the enclosure only
    after [section 11](#11-checks-flashing-and-first-power-up).

## 11. Checks, flashing and first power-up

### 11.1 Before any power (meter; supply, loads and M12 cable all disconnected)

- [ ] **Isolation**: M12 pin 3 (the box's GND) to the module side's GND, to
      the supply input's −, to each relay terminal and to the RP2040 board's
      GND: **open** (no continuity, more than a few Mohm). This is RFC bench
      test 7.
- [ ] M12 pins 1, 2 and 4 to anything on the module side: **open**.
- [ ] M12 pin 5 to every other pin: **open**.
- [ ] The supply input's + to its −: no short (a few kohm or more is the
      buck converter).
- [ ] Diode test across the 1N5819: about 0.2-0.4 V towards the buck, open
      the other way.
- [ ] Each relay input (IN1-IN4) to GND: about **10 kohm** (the pull-down).
- [ ] Each relay's COM to NO: **open**; COM to NC: closed (the relay at rest).
- [ ] SDA2 and SCL2 to VCC2: about 4.7 kohm; SDA1 and SCL1 to VCC1: **open**
      (no side 1 pull-ups).

### 11.2 First power, no firmware, no box

1. Loads disconnected, M12 cable unplugged. Connect the supply.
2. The buck's output: **5.0 V**. The RP2040 board's 3V3: about 3.3 V. The
   isolator's VCC2: the same.
3. **No relay clicks**, and each relay input reads 0 V. Repeat 10 times
   (supply off and on): a relay that clicks at power-up means a low-trigger
   board or a missing pull-down: stop and fix it ([section 7](#7-relays-or-solid-state)).
4. Supply off.

### 11.3 Flashing

CI makes the UF2 file with the default channel list, with the target
module's (`python3 tools/docker_module.py build`); a release carries
`atalaia-output-module-<version>.uf2`. For other loads, build it with the
channel list for what is fitted
([firmware README](../../firmware/output-module/README.md#building)).
The default (four relays, generic, at most 30 s on each) suits a first
bench test.

1. **Supply off, M12 cable unplugged, loads disconnected.**
2. Hold the board's BOOTSEL button, plug it into a computer's USB, release
   it; copy the `.uf2` file to the drive that appears. The board
   restarts on its own.
3. Unplug the USB.

### 11.4 First power-up with the firmware

1. Loads disconnected, M12 cable unplugged. Connect the supply.
2. **No relay clicks**, at power-up or afterwards (20 power cycles, watched).
   The LED stays dark. A **fast-blinking LED** means the firmware refused its
   channel list: rebuild it with a valid one.
3. Supply off. Connect the loads (each through its fuse) but leave the M12
   unplugged: nothing switches, since no box is writing to the module.

### 11.5 On a box

1. With the box off, plug the module into its expansion port, and connect
   the module's supply.
2. Turn the box on. It sends `ALL_OFF` and reads the module: the box's
   module list shows `5c:out4/1.0.0:` and the channels' names
   (`node.modules`).
3. The module's outputs are **off on the box until its admin enables them**
   (EXP-28), at the box, with each channel's function and max on. The admin's
   1 s test then clicks each relay in turn.
4. The bench tests of [section 12](#12-what-waits-for-the-bench).

## 12. What waits for the bench

| What | Needs | When |
| --- | --- | --- |
| RFC bench test 5: with a relay on, pull the box's power, reset the box, cut the cable, unplug the module: **off within 1.5 s** each time (a stopwatch on video) | A box | Bench (HW2) |
| RFC bench test 6: noise: a 12 V siren and a strobe switching for 30 minutes next to the box and its cable; count CRC errors and missed polls | A box | Bench (HW2) |
| RFC bench test 7: isolation (no continuity from M12 pin 3 to the module side) | A meter | Now ([11.1](#111-before-any-power-meter-supply-loads-and-m12-cable-all-disconnected)) |
| RFC bench test 10: smoke: a battery smoke device or a fog machine with a documented low-voltage input, fired by Bomb's explosion, stopped by the GM's "All outputs off" and by the end of the game | A box, the device's manual | Bench (HW2) |
| The isolator's side 1 at the port's 3.0 V, and the bus's low level through the isolator and the port's buffer ([section 5](#5-the-two-sides-the-isolator)) | A box, a scope | Bench (HW2) |
| The module's current from the port's pin 1 (expected: a few mA, at most 5 mA) | A meter in series with pin 1 | Bench (HW2) |
| The relays pulling in from 3.3 V; their coil current; the module's own supply current; the input fuse's rating | A meter | Now |
| The supply sense's thresholds against a meter | A variable supply | Now; the box shows `SUPPLY_OK` |
| The watchdog and the guard on the board (a hung loop restarts the module, every relay off) | A debug build | Bench (HW2) |

## 13. Troubleshooting

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| A relay clicks at power-up or while flashing | A low-level trigger board, a trigger jumper on low, or a missing pull-down | Use a high-level trigger board; check the 10 kohm from each IN to GND ([section 7](#7-relays-or-solid-state)) |
| Nothing powers up | The input fuse, the 1N5819 the wrong way round, the battery reversed, the buck not set | Check the fuse, the diode's band (towards the buck), and the buck's 5.0 V |
| The LED blinks fast and the box never finds the module | The firmware refused its channel list | Rebuild with a valid `OUTPUT_CHANNELS` ([firmware README](../../firmware/output-module/README.md#the-channel-list)) |
| The box does not find the module | The cable, M12 pin 1 at about 3.0 V at the module, the address (0x5C-0x5F), side 1 pull-ups left on the isolator, the isolator's low level ([section 5](#5-the-two-sides-the-isolator)) | Measure VCC1; check 11.1 again |
| The box's keypad or NFC reader stops when the module is plugged in | The isolator's side 1 holding the bus, or its pull-ups added to the box's | Remove the side 1 pull-ups; report the scope trace in an issue |
| A relay's contacts stick or burn | An inductive load without a flyback diode, or a load above 2 A | Fit the diode across the load; check the load's current and fuse |
| An output turns off on its own after a while | The channel's max on (the module's, or the box's lower one), or the lease (the box stopped writing: `LEASE_EXPIRED`) | Expected: the limits are doing their job; raise the module's max on only within what the device's manual allows |
| A channel refuses to come on again | Its min off after a max on, or a relay asked to switch within 100 ms | Expected; the box's reconciliation tries again at a later poll |

---

Licence: this guide is CC-BY-SA-4.0; the module's design is CERN-OHL-S-2.0,
like the rest of the hardware ([LICENSING.md](../../LICENSING.md)).
