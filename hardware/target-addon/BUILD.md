<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Target addon build guide

Portuguese (pt-PT): [BUILD.pt.md](BUILD.pt.md).

The target addon (the **target module**) is a plate that players shoot at,
with a piezo sensor that feels each hit and a small RP2040 board of its own,
which plugs into a box's [expansion port](../expansion-port/BUILD.md) and turns
it into a scoring target: the hardware of the *Target Windows* mode, where a
hit while the target shows a team's colour scores for that team. Written for a
club member who can solder header pins and wires and use a multimeter.

> **Status: the hardware is decided and can be built; it cannot be used
> yet.** The draft RFC "The expansion port"
> ([`docs/rfcs/0000-expansion-port.md`](../../docs/rfcs/0000-expansion-port.md),
> approved by the maintainer on 2026-11-03) decided what this guide used to
> list as open: the processor (an RP2040 board, EXP-15), the address (0x58,
> EXP-7), the "identify" answer and the hit report (the expansion protocol v1,
> [`protocol/expansion-port.md`](../../protocol/expansion-port.md), EXP-9), the
> sensor's circuit in outline and the port's protection (EXP-4). **What is not
> there yet is the firmware**: the module's own firmware (on pico-sdk, with its
> UF2 file), the box's port driver called from its game task, and *Target
> Windows* as a box preset all come with **increment 8** of the RFC's plan. So
> a builder can make the plate, the sensor's front end, the module's enclosure
> and cable, and the box's port now, and check them with a meter; the module
> cannot be flashed, and no box reads it, until then. Every step that depends
> on increment 8 says so (**after increment 8**), and
> [section 10](#10-what-waits-for-increment-8) lists them. **No target has been
> built from this guide yet.** Steps marked **Verify at the first build** are
> open questions; please report what you find in an issue. Photos will be
> added after the first build (plan phase HW2); this guide never uses mock-up
> or generated photos.

## Contents

1. [What you are building](#1-what-you-are-building)
2. [What is decided and what is not](#2-what-is-decided-and-what-is-not)
3. [Parts](#3-parts)
4. [Tools and safety](#4-tools-and-safety)
5. [The box's side: the expansion port](#5-the-boxs-side-the-expansion-port)
6. [The module, step by step](#6-the-module-step-by-step)
7. [Checks at the build](#7-checks-at-the-build)
8. [Plate, stand and enclosure](#8-plate-stand-and-enclosure)
9. [How the box reads hits](#9-how-the-box-reads-hits)
10. [What waits for increment 8](#10-what-waits-for-increment-8)
11. [Photos](#11-photos)
12. [Helping](#12-helping)

## 1. What you are building

```
plate ── rubber pad ── piezo disc ── front end ── RP2040 board ── M12 (male) ═══ 2 m cable ═══ M12 (female) ── port board ── box
         (steel or polycarbonate)    (divider, bleed,   (ADC, I2C target   pin 1 3.3 V, 2 SDA,                 (buffer, TVS,
                                      clamps)            at 0x58)          3 GND, 4 SCL, 5 n.c.                 fuse, diode)
```

- The **piezo disc**, bonded through a rubber pad to the back of the plate,
  turns each hit into a short voltage spike.
- The **front end** (a resistor divider, a 1 Mohm bleed, two Schottky clamps)
  scales the spike into the RP2040's ADC range and keeps it between GND and
  3.3 V.
- The **RP2040 board** samples the piezo continuously, finds each hit's peak
  (its strength, 0-255) with a hold-off against a ringing plate, keeps it with
  its age until the box takes it, and answers the box's I2C reads at address
  **0x58** (EXP-10, EXP-15).
- The **box** reads the module's `STATUS` every 20 ms through its expansion
  port, and passes each hit to the mode's script as `hit.hit` with its
  `strength` (**after increment 8**).

*Target Windows* lights the **box's own LED ring**, so the module needs no
lights (P5J-16). Approximate cost: €10-15 for the module without the plate and
cable (RFC section 3), plus the plate, the cable and the box's port
([port guide](../expansion-port/BUILD.md), €6-14); hobby-market prices, not a
quote.

## 2. What is decided and what is not

| What | Decided | Where |
| --- | --- | --- |
| Purpose | A hit-scoring target for any box (Field Box, Satellite, I/O pod) | [Design specification](../../docs/design-spec.md), section 6; EXP-2 |
| How it connects | The box's **expansion port**: an M12 A-coded 5-pin socket, 3.3 V only (1 brown 3.3 V, 2 white SDA, 3 blue GND, 4 black SCL, 5 grey not connected), behind the box's port board | EXP-1, EXP-4; [port guide](../expansion-port/BUILD.md) |
| Processor | An **RP2040 board** (RP2040-Zero class, or a Pico), run at a reduced clock (48 MHz) to stay within the port's current | EXP-15; RFC section 3 (a) |
| Power from the box | At most **25 mA** from the port's 3.3 V (about 3.0 V at the module), for the processor and the sensor's front end; **measured** at the first build | EXP-3; P5J-16 |
| Pull-ups | **None** in the module: the box's port board has them | EXP-4; P5J-17 |
| Reverse polarity | The module protects itself against a hand-made cable wired wrongly: a P-channel MOSFET in its supply ([section 6.1](#61-supply-entry)) | RFC section 1 ("Plugging in reversed"); this guide (EXPI10-8) |
| Address | **0x58**; two solder jumpers add 1-3 (0x59-0x5B) for a second target on the same box | EXP-7 |
| "Identify" and the hit report | The expansion protocol v1: `IDENT` (model 0x0001 `target`, one channel), `CHANNEL` (kind hit), `STATUS` (the oldest hit with its sequence, strength and age), `COMMAND` (`ACK`, `ARM`, `CONFIG` for the threshold, the hold-off and the debounce, `LOCATE`). It replaces the 5-byte draft of P5J-19, which nothing was built against | EXP-9, EXP-10; [protocol/expansion-port.md](../../protocol/expansion-port.md) |
| Sensor | A piezo disc of 27-35 mm, bonded to the back of the plate through a rubber pad; a resistor divider and a 1 Mohm bleed to set the level, Schottky clamps to 3.3 V and GND, into an ADC pin | RFC section 3 (a) |
| Hit detection | In the module: a peak above the threshold, scaled to 0-255, a hold-off (default 50 ms) against ringing; at least 16 hits queued, each with its age | EXP-10 |
| Plate | Steel or polycarbonate, angled down, the electronics behind it | RFC section 3 (a); [section 8](#8-plate-stand-and-enclosure) |
| What the box's game scripts see | The `hit` capability: an event `hit` with a `strength` from 0 to 255 (scripts get `hit.hit`), and the commands `arm` and `disarm` | Design specification, section 7; draft RFC 0000 Amendment 1; EXP-18 |
| The game mode | *Target Windows* (`modes/target_windows/`): the role `target` needs `hit` and `led`. The target is dark for `interval_s`, then lights a random team's colour for `window_s`; a hit of at least `min_strength` in the window scores `hit_points` for that team. Built and tested in the simulator; a Field Box preset once the target is bench-tested | [Phase 4 plan](../../docs/phase-4-site-server/PLAN.md), plan phase 2; M2-1 to M2-5; RFC increment 8 |

Not decided, or not built yet:

1. **The module's firmware** (pico-sdk, on the portable module core of
   increment 7) and its UF2 file from CI and the releases: **after increment
   8**. With it come the module's pin table (which RP2040 pins carry the I2C
   target, the ADC input and the address jumpers), how its board LED shows
   `LOCATE`, and how it takes 3.3 V on its 3V3 pin.
2. **The strength scale, the threshold and the hold-off** on real steel and
   polycarbonate plates (bench test 8, HW2), and with them the front end's
   two divider resistors.
3. **The plate's size and thickness, its stand and its angle** (HW2).
4. **A carrier PCB** for the module: later; perfboard until then.

## 3. Parts

One target. The box's port is a separate set of parts
([port guide, section 3](../expansion-port/BUILD.md#3-parts-and-what-each-protects-against)).

| # | Part | Qty | What it is for | What to check |
| --- | --- | --- | --- | --- |
| 1 | RP2040 board: **RP2040-Zero** class (or a Raspberry Pi Pico) | 1 | Samples the piezo, finds the hits, answers the box at 0x58 | A genuine RP2040 with its USB-C (or micro-USB) for flashing by UF2 |
| 2 | Piezo disc, **27-35 mm**, with leads | 1 (2 spare) | Feels each hit through the plate | Bare brass disc with a ceramic centre; buy spares, they crack |
| 3 | Rubber pad (2-3 mm, neoprene or EPDM) and contact adhesive | 1 | Bonds the piezo to the plate and spreads the shock, so a direct hit does not crack it | Covers the whole disc |
| 4 | 1 Mohm resistor, 1/4 W | 1 | The **bleed** across the piezo: drains its charge, so the ADC sees a spike, not a slowly drifting level | |
| 5 | Two resistors for the divider (values chosen on real plates) and a 2-pin socket strip for each | 2 | Scale the spike into the ADC's range | Fit them in sockets, so they can be swapped at bench test 8 |
| 6 | Small Schottky diodes, **BAT85** class | 2 | **Clamps**: keep the ADC pin between GND and 3.3 V whatever the plate does | Low forward voltage |
| 7 | P-channel MOSFET for a low gate voltage, **AO3401** or SI2301 class (SOT-23), on a SOT-23 adapter; a 10 kohm resistor | 1 each | **Reverse-polarity protection** of the module's supply, with almost no voltage drop (a diode would drop 0.3 V more, and the bus's high level would then sit above the module's supply) | Rated for a gate voltage of -2.5 V or less |
| 8 | Solder jumpers or a 2-position DIP switch | 1 | The address: open-open is 0x58; the others 0x59-0x5B | Which RP2040 pins they go to: **after increment 8** |
| 9 | M12 A-coded 5-pin **male** panel connector, IP67 | 1 | The module's end of the cable | A-coded, 5-pin |
| 10 | M12 A-coded 5-pole sensor extension cable, male to female, 1-2 m | 1 | Box to module, at most 2 m | Check the colours with a meter |
| 11 | Small IP65 enclosure, cable gland or the M12 connector through its wall, perfboard, 0.25 mm² wire, heat-shrink | 1 set | Holds the RP2040 board and the front end behind the plate | Not metal if it can be avoided; out of the line of fire |
| 12 | Steel plate or polycarbonate sheet, and a stand | 1 | What players shoot at | Size, thickness and stand: HW2 ([section 8](#8-plate-stand-and-enclosure)) |

## 4. Tools and safety

The tools are the Field Box's ([manual, section 3](../field-box/BUILD.md#3-tools-and-consumables)).
At the bench:

1. **Never connect the module's USB cable and the port cable at the same
   time.** Flash the module (after increment 8) with the port unplugged.
2. **3.3 V only** on every pin of the module's connector; **pin 5 not
   connected**; **no pull-ups** in the module; **at most 25 mA** (P5J-16,
   P5J-17).
3. **No lights on the port's supply.** A module with lights of its own needs a
   cell of its own, its own fuse and charging, its GND joined to the port's,
   its supply never reaching the port.
4. **Static**: touch the box's GND before plugging a module in.

Whenever anyone shoots at the target, at the bench too:

- **Eye and face protection** for everyone within range of the target,
  including while the sensor is tuned.
- **Ricochets.** BBs bounce off a hard plate, and some come back. Set a steel
  plate at an angle that sends them down to the ground, never flat towards the
  shooter. Never shoot at the box, the cable, the connector or the module's
  enclosure, only at the plate.
- **Shield the electronics.** The module, its wiring and the cable sit behind
  the plate or in their own enclosure, out of the line of fire.
- **The field's power limits** (the chrono, the joule limit) apply to shooting
  at targets as to shooting at players; the target is not a reason to raise
  them.
- **A game prop**: bright colours and a "GAME PROP" label, like every Atalaia
  device; the box it plugs into follows its own build guide's battery rules
  ([Field Box](../field-box/BUILD.md#4-safety-rules),
  [Satellite](../satellite/BUILD.md#4-tools-and-safety)).

## 5. The box's side: the expansion port

The box needs an expansion port: the M12 socket and its port board (the
hot-swap buffer, the TVS array, the 100 ohm resistors, the 50 mA fuse and the
back-feed diode). Build and check it from the
[expansion port build guide](../expansion-port/BUILD.md); it is the same on
the Field Box, the Satellite and the I/O pod, and uses no GPIO. Its pin table
is checked against the firmware by `tools/check_wiring.py`
([port guide, section 5](../expansion-port/BUILD.md#5-the-ports-pins)).

The rules the module follows, from the same decisions:

- **Nothing above 3.3 V on any pin.** The module runs from the port's 3.3 V
  (about 3.0 V after the box's diode); a part that needs more makes it from a
  supply of its own, which never connects to the port.
- **No pull-up resistors on SDA or SCL** in the module (P5J-17). If the RP2040
  board you use has any on the pins you choose, remove them.
- **At most 25 mA** from pin 1 (P5J-16). An RP2040 at 48 MHz and the front end
  are expected to stay under it; **to be measured** (bench test 4).

### Why 25 mA

The board's 3.3 V regulator already feeds the board (the ESP32-S3 and the
radio: about 80-150 mA, with peaks of 400-500 mA while Wi-Fi or the radio
transmits), the TFT with its backlight (40-100 mA), the PN532 (50-150 mA with
its field on), and the keypad expander and the gauge (under 1 mA): roughly
170-400 mA in a game, with peaks near 750 mA
([Field Box power budget](../field-box/BUILD.md#power-budget-estimates-not-measurements),
estimates, not measurements). The port promises only a small, fixed share:
25 mA is about 3 % of those peaks, and the fuse keeps a short in the cable or
the connector from browning the box out. A single WS2812 LED draws up to
60 mA, so lights on the port are out of the question.

## 6. The module, step by step

Lay the module out on a small perfboard: the RP2040 board on header pins, the
front end next to its ADC pin, the MOSFET next to its 3V3 pin, and the M12
connector's leads to one edge.

### 6.1 Supply entry

1. M12 **pin 1** (brown) to the MOSFET's **drain**; its **source** to the RP2040
   board's **3V3** pin; its **gate** through 10 kohm to GND. With the right
   polarity the MOSFET turns fully on; with pins 1 and 3 swapped in a
   hand-made cable it stays off.
2. M12 **pin 3** (blue) to the board's **GND**.
3. **Never** to the board's 5V / VBUS / VSYS pin: that is the USB side.
4. M12 **pin 5** (grey): cut short and insulated, not connected.
5. **Verify at the first build:** how the chosen board takes 3.3 V on its 3V3
   pin with its own regulator unpowered, and the voltage at the 3V3 pin with
   the module running (about 3.0 V expected); the module firmware's
   documentation fixes this with increment 8.

### 6.2 The piezo and its front end

```
piezo + ──┬── R1 ──┬──────────────── ADC pin
          │        ├── R2 ── GND
        1 Mohm     ├── BAT85 (cathode to 3V3)
          │        └── BAT85 (anode to GND, cathode to the ADC node)
piezo − ──┴── GND
```

1. Bond the piezo disc to the rubber pad and the pad to the back of the plate,
   in the plate's centre, brass side towards the pad. Let the adhesive cure as
   its maker says.
2. The **1 Mohm** bleed across the piezo's leads, at the module.
3. **R1** from the piezo's + lead to the ADC node; **R2** from the ADC node to
   GND (both in sockets: their values come from bench test 8).
4. The two **BAT85** clamps on the ADC node: one with its cathode (band) to
   3V3, its anode to the node; the other with its cathode to the node, its
   anode to GND.
5. The ADC node to one of the RP2040's ADC pins (GPIO 26-28); which one: the
   module firmware's pin table, **after increment 8**.
6. Run the piezo's leads as a twisted pair, tied down, behind the plate.

### 6.3 Bus and address

1. M12 **pin 2** (white, SDA) and **pin 4** (black, SCL) to the RP2040's I2C
   target pins: which pins, **after increment 8**. Short wires; no pull-ups.
2. The two address jumpers between the RP2040 pins the firmware names and
   GND: both open is **0x58**, the address every box looks at first. Leave
   them open unless the box carries a second target.

### 6.4 The connector and the enclosure

The M12 male connector through the enclosure's wall, its O-ring outside, the
enclosure behind the plate with the connector facing away from the shooters
([section 8](#8-plate-stand-and-enclosure)). Heat-shrink every solder cup.

## 7. Checks at the build

With a meter, the module unpowered:

- [ ] M12 pin 1 to pin 3: no short.
- [ ] M12 pin 5: open to every other pin.
- [ ] M12 pins 2 and 4 to pin 1: **no pull-up** (open, or above 100 kohm).
- [ ] The ADC node to GND: R2 in parallel with the rest; to 3V3 and to GND,
      the clamps read as diodes (about 0.2-0.4 V one way, open the other).
- [ ] The piezo's leads: about 1 Mohm (the bleed).

**After increment 8** (the module firmware and the box's port driver):

1. **Flash the module**: hold its BOOT button while plugging its USB cable into
   a computer, and drag the target module's UF2 file onto the drive that
   appears (the port unplugged). The UF2 files come from CI and the releases
   with increment 8.
2. **Current** (bench test 4): a meter in series with pin 1, the module
   sampling: **under 25 mA**.
3. **Found by the box**: plug the module into a box's port; the box finds it
   within 2 s (the log and the box's module list, with increment 8).
4. **Tuning** (bench test 8): threshold, hold-off and strength scale on steel
   and polycarbonate plates, at the field's joule limit, with eye protection;
   swap R1 and R2 until a hit at range reads clearly above the threshold and a
   hit right over the piezo does not reach the clamps (it would saturate).

## 8. Plate, stand and enclosure

Decided: a **steel or polycarbonate** plate, **angled down** so BBs go to the
ground, the **electronics behind the plate** or in their own enclosure, out of
the line of fire (RFC section 3 (a)). Not decided yet (HW2): the plate's
material grade, thickness and size, the stand, and the exact angle; the first
builds settle them and this section gains them, with photos. Until then:

- the piezo bonded through its pad to the plate's back, the module's enclosure
  fixed to the stand, not to the plate (so the plate's shock does not shake
  the electronics);
- the cable leaves the enclosure downwards and runs along the ground, behind
  the plate, to the box, which stands out of the line of fire.

## 9. How the box reads hits

The Field Box uses all eight of the board's GPIOs that are free of any board
part, and the GNSS connector keeps 34 and 38-42, so there is no pin for an
interrupt line. It does not need one (P5J-18, EXP-8):

- All of the box's I2C traffic, the keypad's included, runs in its game loop
  every 10 ms; an interrupt would be noticed only at the next tick. The box
  reads the module's 9-byte `STATUS` every **20 ms**: a pointer write, a
  repeated start and 9 bytes, about 12 bytes on the wire (1.1 ms), about
  **5 %** of the bus. The keypad's scan already uses about 18 %.
- **Latency.** A hit reaches the script within about 21 ms of the module
  feeling it, against a target of 50 ms: a window is open for at least 1 s
  (5 s by default), and a BB takes 0.2-0.3 s to cross 20-30 m anyway. When the
  game loop is slow (an NFC read can hold it for 200 ms), hits are not lost:
  the module keeps at least 16, with their age, and the box dates each one on
  its own clock (`t_event = t_read - age`).
- The box acknowledges each hit by its sequence number, so a lost
  acknowledge never counts a hit twice; it arms and disarms the module as the
  mode asks; a module that fails 25 reads in a row (0.5 s) is gone, and the
  controller is told (`node.module_lost` during a game).

The box's port driver (`firmware/esp32/main/expansion.c`, replacing the stub
`target_addon.c`) is written (increment 6, 2026-11-04), with host tests against
the protocol's shared vectors; it is called from the game task, and hits reach the
script, **after increment 8**.

## 10. What waits for increment 8

Written from what the RFC fixes; the rest comes with the firmware:

- the module's firmware (pico-sdk, ADC with DMA at about 20 ksample/s, peak
  detection, the protocol core of increment 7), built in Docker
  (`tools/docker_module.py`), and its **UF2 file** from CI and the releases;
- the module's pin table: the I2C target pins, the ADC pin, the address
  jumpers, the board LED for `LOCATE`;
- how the chosen RP2040 board takes 3.3 V on its 3V3 pin;
- the box calling its port driver, adding `hit` to its capabilities and to
  `node.modules` (`58:target/<version>:hit`), and passing hits to the script;
- the box's log lines and console view for the module, and BRING_UP's step for
  the port (`firmware/esp32/docs/BRING_UP.md`);
- *Target Windows* as a Field Box preset, once bench-tested (P4R23);
- the I/O pod lending `hit` to a phone (increment 9, on the port driver of 8).

## 11. Photos

<!-- PHOTO: target-addon-plate.jpg | the finished target: plate and sensor mounting, front and back -->
> **Photo to be added after the first build:** the finished target, plate and
> sensor mounting, front and back.

<!-- PHOTO: target-addon-port.jpg | the M12 expansion port on a box, and the module's cable plugged in -->
> **Photo to be added after the first build:** the M12 expansion port on a
> box, with the module's cable plugged in.

## 12. Helping

Build one and report what you measured (the current, the voltage at the
module, the rise time, the tuning on your plates) in an issue; the
**Verify at the first build** items and the plate's dimensions come from
those reports. Designs are CERN-OHL-S-2.0, like the rest of the hardware
([LICENSING.md](../../LICENSING.md)).

---

Licence: this guide is CC-BY-SA-4.0.
