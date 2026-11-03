<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# RFC 0000: The expansion port, its protocol and its first modules

- **Author(s):** The Atalaia contributors (design requested by the maintainer on 2026-11-03)
- **Status:** Draft (2026-11-03): a design for the maintainer to approve; nothing in it is built yet. Decisions are numbered **EXP-1** to **EXP-30** in this file
- **Discussion:** the pull request that adds this file
- **Replaces, once accepted:** the target addon's open items (P5J-9, P5J-21) and the draft report format of P5J-19; revisits P5J-7 (no outputs on the pod)

## Summary

One port and one protocol for everything that plugs into a box from outside:
**inputs** (a target plate's hits now, contacts and other sensors later) and
**outputs** (relays for sirens, strobes, lights and smoke machines). The port
stays the 5-pin M12 socket of P5J-15 to P5J-21 (3.3 V, GND, SDA, SCL, pin 5
free). A hot-swap buffer and ESD protection on the box keep a wet or shorted
cable from taking the box's own bus down. Each module has a small processor of
its own that answers a fixed register map at an address in **0x58-0x5F**: who
it is, its channels, and one status read that carries both its oldest input
event and the state of its outputs. The box polls (no interrupt line: P5J-18
stands). Every output works on a **lease**: the module turns it off by itself
when the box stops refreshing it, so a crashed box, a cut cable or a lost radio
can never leave a smoke machine running. Loads never take power from the box:
an output module has its own supply and its own isolated side.

Game logic sees capabilities, as today: `hit` (already specified) and
`output` (in the design specification since phase 1, never built), with ids
that name the function (`cap("siren"):pulse(10000)`). Field scripts and
scenarios switch a box's output with a new CMD opcode; the GM can switch
outputs off from the console at any time, and on only with a confirmation;
players never can.

The first increment builds two modules on the same processor (an RP2040
board): the **target module** (the target addon) and a **4-channel output
module** that drives an off-the-shelf opto-isolated relay board.

## Motivation

- The target addon has been "not buildable" since 2026-10-22: its processor,
  address, identify answer and firmware were never decided
  ([hardware/target-addon/BUILD.md](../../hardware/target-addon/BUILD.md),
  section 5). The box side has a tested polling stub
  ([firmware/esp32/main/target_addon.c](../../firmware/esp32/main/target_addon.c))
  that nothing calls.
- No node can switch anything. The design specification lists an `output`
  capability ("siren, smoke relay, strobe", section 7) and "smoke, sirens,
  lights: a relay node driven by events such as `bomb.exploded`" (section 11),
  and the I/O pod was meant to have a siren (section 6); P5J-7 recorded that
  none of it exists. The maintainer's examples: an outdoor Bomb game that fires
  a smoke machine when the bomb explodes, and a Master box that sounds a siren
  when one team holds every Satellite.
- Two one-off designs (a hit bus and a relay bus) would mean two connectors,
  two drivers and two sets of rules. The box has no GPIO to spare for either
  (all eight board-free GPIOs of a Field Box are used:
  [hardware/field-box/README.md](../../hardware/field-box/README.md#peripheral-pins)),
  so both must live on the one I2C bus anyway.

### What was checked in the code (2026-11-03)

| Finding | Where | What this design does about it |
| --- | --- | --- |
| `cap(id):method(args)` forwards any method to the host, so new capability types need **no core change** for node scripts | `core/src/script_api.c`, "Hardware: cap(id), ui and audio" | Outputs and hits are reached through `cap()`; the work is in the firmware's dispatch |
| HELLO's `capabilities` (key 6, "capability type ids") is **sent empty** by the Field Box and the host box, and **no table of type ids exists** | `firmware/esp32/main/shell.c` (`memset(&hello, 0, ...)`), `test/box_host/box_host.c`, `protocol/schema/messages.yaml` | EXP-20 defines the table and has the box fill it, modules included |
| The start check counts **roles** that have a joined node; it never looks at capabilities | `controller/atalaia_controller/engine.py`, `start_check` | EXP-21: capability checks, only for nodes that report capabilities |
| The keypad driver probes **0x20-0x27 and 0x38-0x3F** for its PCF8574 when it is not at its default address, then drives its pins every 10 ms | `firmware/esp32/main/hal/esp/hal_esp_keypad.c` | A PCF8574 relay board on the box's bus could be taken for the keypad, and its relays clicked by the keypad scan: EXP-15 |
| The bus is 100 kHz because of the PN532 | `firmware/esp32/main/hal/esp/hal_esp_i2c.c` (`BUS_HZ`) | The port stays at 100 kHz (EXP-6) |
| A device that fails 3 transactions in a row is suspended, with a back-off up to 30 s | `firmware/esp32/main/i2c_health.h` | A suspended output module must still turn its outputs off: the lease does it (EXP-11) |
| Field scripts command boxes with `field.send(node, cmd, params)`; the scenario runtime uses it for CMD `mode` (opcode 8) | `core/include/atalaia/field_ops.h`, `core/scenario/runtime.lua` | A new opcode 12 `output`, handled by the box's firmware, not by the mode script (EXP-23) |
| A scenario objective's `effect` takes `points`, `win`, `reveal` | `core/scenario/validator.lua`, `check_effect` | Scenarios gain `triggers` with an `output` action (EXP-25) |
| CMD opcodes 0-11 are taken; the last RFC 0001 amendment is 25 | `docs/rfcs/0001-skirmesh-rf-wire-format.md` | Opcode 12 by a new amendment |
| Free GPIOs: Field Box none; Satellite 1, 3, 33, 47; I/O pod 1, 3, 33 | the three build guides' pin tables, `tools/check_wiring.py` | No design depends on a GPIO (EXP-8), so every node type gets the same port |

## Design

### 1. The physical port

| | Recommendation | Alternatives considered |
| --- | --- | --- |
| Connector | **Keep the M12 A-coded 5-pin socket** (IEC 61076-2-101) and its pin-out (P5J-20) | GX12/GX16 aviation plugs: cheaper, but not sealed, and a 5-pin GX16 also fits other gear's cables. RJ45: not waterproof, and it fits Ethernet. USB-C: confused with charging. Screw terminals through a gland: not pluggable on the field |
| Pins | 1 brown 3.3 V, 2 white SDA, 3 blue GND, 4 black SCL, **5 grey reserved, not connected** | Pin 5 as an interrupt line: no GPIO on a Field Box (P5J-18); as 5 V: refused by P5J-15 |
| Logic and supply | 3.3 V only, at most **25 mA** for the module's logic (P5J-16) | -- |
| Power for loads | **Never from the box.** An output module brings its own supply (EXP-3) | A 5 V or battery pin on the port: refused, it would put the box's cell behind a cable on the field |
| Cable | At most **2 m**, ready-made 5-core M12 sensor cable (P5J-17) | Longer runs: a Satellite next to the target, or later an RS-485 extender module (section 2) |
| Who gets it | **Field Box, Satellite and I/O pod**, each optional (fitted when wanted) | The field controller (a Pi): not in v1 (open question 9) |

**EXP-1.** The port stays the M12 A-coded 5-pin socket with the P5J-20 pin-out;
pin 5 stays not connected and reserved, never a supply.

**EXP-2.** The Field Box, the Satellite and the I/O pod all get the same port,
as an option. The port uses no GPIO (it is the board's I2C bus on GPIO 17/18),
so their pin tables do not change.

**EXP-3. Loads are powered from their own supply, never from the box.** The
25 mA from pin 1 feed a module's logic only (the target module's processor and
sensor; the output module's isolator, section 3). An output module has its own
power input (for example a 12 V lead-acid or LiFePO4 battery, or the siren's
own pack), its own fuse, and its own regulator for its processor and relay
coils. Its supply never connects to the port's pins (P5J-16's rule, kept).

**EXP-4. Protection on the box's side of the port** (on the interconnect board
or a small port board):

| Threat | Part (class; exact part chosen at the port board's design) |
| --- | --- |
| A shorted or wet cable holding SDA or SCL low, which would stop the keypad, NFC reader, gauge and OLED | A **hot-swap I2C buffer with stuck-bus recovery** (TCA4307 / LTC4307 class) between the box's bus and the port: it connects the port only when both sides are idle, and cuts it off if the port holds a line low (about 30 ms), clocking the stuck module free. It also keeps the cable's capacitance off the box's bus |
| Static from a hand, a cable rubbing on clothes | A low-capacitance TVS array on SDA, SCL and 3.3 V at the socket, and 100 ohm series resistors on SDA and SCL |
| A short between pins 1 and 3 | The resettable fuse (PTC, about 50 mA hold) of P5J-16 |
| Something on the cable feeding the port's pin 1 (a miswired module) | A Schottky diode from the box's 3V3 to pin 1, so nothing can feed the box's rail backwards (the module sees about 3.0 V) |
| Plugging in reversed | Prevented by the A-coding; a hand-made cable wired wrongly is caught by the module's own reverse-polarity protection (section 3) |

The buffer's port side gets its own pull-ups (2.2 kohm to the port's 3.3 V);
modules still carry **no pull-ups** (P5J-17). Approximate cost of a port: socket
€3-6, buffer €2-6 (a breakout), TVS, fuse, diode and resistors €1-2.

### 2. Bus and protocol

#### Which bus

| Option | For | Against | Verdict |
| --- | --- | --- | --- |
| **I2C, 100 kHz, through the hot-swap buffer** | Uses the existing bus: **no GPIO**; every module processor has an I2C target; the stub and its tests exist | 2 m at most; one bus shared with the box's own parts | **Chosen (EXP-5)** |
| I2C with a differential extender (PCA9615) | Tens of metres on twisted pairs | Needs 2 pairs + power + GND: 6 pins, not the M12 5-pin; a chip at both ends | Later, as an extender module if ever needed |
| RS-485 / UART | Sturdy, long cables, multi-drop | Needs a UART: 2-3 GPIOs a Field Box does not have (UART0's pins are button 3 and the log) | Later, behind the port: an "extender" module with an I2C-UART bridge (SC16IS740 class) and an RS-485 transceiver |
| 1-Wire | One data wire | Needs a GPIO (or a DS2482 bridge, which is I2C again); slow (about 16 kbit/s); made for sensors, not for switching | No |
| CAN | Robust, multi-drop | GPIOs and a transceiver at both ends | No |
| A second ESP32-S3 I2C controller | Separates the port from the box's parts | Two GPIOs: none on a Field Box | No (the buffer gives the separation instead) |

**EXP-5.** The port is the box's I2C bus behind the hot-swap buffer (EXP-4).
Longer distances are not the port's job: a Satellite near the target, or a
future extender module.

**EXP-6.** 100 kHz, as the bus already runs (the PN532 sets it, P5J-17). The
budget below fits at 100 kHz, so there is no reason to raise it.

#### Addresses: several modules on one box

**EXP-7.** Expansion modules answer at **0x58-0x5F** (8 addresses), clear of
every address the box uses or probes: the keypad expander (0x20-0x27,
0x38-0x3F), the PN532 (0x24), the gauge (0x36), the board's OLED (0x3C), and
the I2C reserved ranges (0x00-0x07, 0x78-0x7F). Each module type has a default
address so that one of each works without setting anything: **input modules
(the target module) 0x58, output modules 0x5C**; two solder jumpers on a module
add 0 to 3, for a second module of the same type. A box takes **at most 4
modules** (bus time and the 25 mA each would draw from the same rail are the
limits; 8 addresses leave room for jumper mistakes).

Alternatives: one fixed address per type (two targets on one box would clash);
addresses assigned at run time (SMBus ARP style: a lot of protocol for 4
devices); an I2C mux (another chip, and its own address).

#### Polling, not interrupts

**EXP-8. Keep polling every 20 ms; no interrupt line** (P5J-18 stands). The box's
game task runs every 10 ms and already does all its I2C work there, so an
interrupt would only be seen at the next tick: it could save at most about
10 ms against a 50 ms target. Modules keep every input event with its age
until the box takes it, so a slow moment (an NFC read holding the game task
for 200 ms) loses nothing. A module with only outputs is read every 250 ms.

Bus budget at 100 kHz (90 µs per byte with its acknowledge):

| Traffic | Bytes on the wire | Every | Share of the bus |
| --- | --- | --- | --- |
| Keypad scan (today) | about 20 | 10 ms | about 18 % |
| Input module status poll (pointer write, repeated start, 9-byte read) | 12 | 20 ms | about 5.4 % per module |
| Output module status poll | 12 | 250 ms | about 0.4 % |
| Lease refresh while any output is on | 5 | 500 ms | about 0.1 % |
| Looking for new modules (one address byte at each empty address) | 1 per address | 2 s per address | negligible |
| Worst case: 4 input modules, keypad, gauge, NFC | -- | -- | about 40 %, about 4 ms of each 10 ms tick spent waiting on the bus at most |

#### Frames

All multi-byte numbers are little-endian. Every frame ends with a **CRC-8**
(polynomial 0x07, initial value 0x00, no reflection: the stub's
`target_addon_crc8`). A write's CRC covers the address byte as sent (address
shifted left, write bit 0), so a frame that reaches the wrong module because a
bit of the address flipped is refused. A read's CRC covers the bytes read.

- **Read:** the box writes the register number (and for `CHANNEL` the channel
  index), then a repeated start and reads the register's length.
- **Write:** the box writes the register number, the payload and the CRC in
  one transaction.

| Register | Name | Access | Length | What |
| --- | --- | --- | --- | --- |
| 0x00 | `IDENT` | read | 16 | Who the module is |
| 0x01 | `CHANNEL` | write index, read | 8 | One channel's descriptor |
| 0x02 | `STATUS` | read | 9 | The oldest input event and the outputs' state: the one read the box polls |
| 0x10 | `COMMAND` | write | 4-11 with the register number and the CRC | Acknowledge, arm, output, lease, all off, locate, configure |

`IDENT` (16 bytes):

| Byte | Field | Notes |
| --- | --- | --- |
| 0-1 | magic | `0x41 0x58` ("AX") |
| 2 | protocol version | 1 |
| 3 | classes | bit 0: has inputs, bit 1: has outputs |
| 4 | channel count | 1-8 |
| 5-6 | model | 0x0001 target module, 0x0002 4-channel output module; 0x8000-0xFFFF for community models, listed in `protocol/expansion-port.md` |
| 7 | hardware revision | |
| 8-10 | firmware version | major, minor, patch |
| 11-14 | unique id | from the processor's unique id (so the console tells two modules apart) |
| 15 | CRC-8 | of bytes 0-14 |

`CHANNEL` (the box writes `0x01, index`, then reads 8 bytes):

| Byte | Field | Notes |
| --- | --- | --- |
| 0 | index | 0-7 |
| 1 | kind | 0x01 hit (strength 0-255), 0x02 contact (closed / opened; reserved for later), 0x10 switched output |
| 2 | flags | bit 0: relay contacts (switching no faster than every 100 ms); bit 1: solid-state (faster patterns allowed); bit 2: the module senses its load supply |
| 3 | hint | what the builder fitted: 0 generic, 1 siren, 2 strobe, 3 smoke, 4 light, 5 horn |
| 4 | max on | outputs: the module's own hard limit in seconds (1-255); inputs: 0 |
| 5 | min off | outputs: the least seconds off after the max on was reached (0-255) |
| 6 | reserved | 0 |
| 7 | CRC-8 | |

`STATUS` (9 bytes; the box's only regular read):

| Byte | Field | Notes |
| --- | --- | --- |
| 0 | flags | bit 0 `EVENT` (bytes 1-5 hold one), bit 1 `MORE` (more wait behind it), bit 2 `OVERFLOW` (events were dropped since the last report), bit 3 `SUPPLY_OK` (the load supply is present, when sensed), bit 4 `LEASE_EXPIRED` (outputs were turned off because the lease ran out), bit 5 `FRESH` (the module started and has not been told `CLEAR_FRESH`), bit 6 `CMD_ERROR` (the last write was refused: bad CRC, unknown command, out of range), bit 7 reserved |
| 1 | event sequence | counts the module's events, wrapping |
| 2 | event channel and kind | bits 0-2 channel; bits 4-7: 1 hit, 2 closed, 3 opened |
| 3 | event value | a hit's strength 0-255; 0 for contacts |
| 4-5 | event age | milliseconds from the event to this read, saturating at 65535 |
| 6 | outputs | bit n: channel n's output is on now |
| 7 | armed | bit n: channel n's input is armed |
| 8 | CRC-8 | |

`COMMAND` (the box writes `0x10`, then these, then the CRC):

| Op | Name | Arguments | Effect |
| --- | --- | --- | --- |
| 0x01 | `ACK` | seq | The box took that event; the module shows the next |
| 0x02 | `ARM` | bitmap | Inputs armed exactly as the bitmap says (a set, not a toggle); disarming drops held events of those channels |
| 0x03 | `OUTPUT` | channel, mode, duration (u16, 100 ms units, 0 = until `off` or the lease), on time (u16, 10 ms units), off time (u16, 10 ms units) | mode 0 off, 1 on, 2 pattern (on time, off time, repeated). Refreshes the lease |
| 0x04 | `LEASE` | lease (u8, 100 ms units, 5-50) | Sets and refreshes the lease of every output |
| 0x05 | `ALL_OFF` | -- | Every output off now |
| 0x06 | `CLEAR_FRESH` | -- | The box has seen the module's restart |
| 0x07 | `LOCATE` | seconds | The module's own status LED blinks, to find it on the field |
| 0x08 | `CONFIG` | channel, parameter, value (u16) | Input tuning: 1 threshold, 2 hold-off ms (a ringing steel plate), 3 debounce ms |

The draft report of P5J-19 (5 bytes, read with no register) is replaced:
no addon was ever built against it, and it had no channel and no output state.
Its ideas stay: an event is shown until it is acknowledged, a lost report is
read again, a lost acknowledge only repeats a sequence number the box takes
once.

**EXP-9.** The register map above, "expansion protocol v1", lives in a new
`protocol/expansion-port.md` with shared vectors (section 6). The box reads
`IDENT` and every `CHANNEL` once when it finds a module, then only `STATUS`.

#### Inputs

**EXP-10.** Inputs are filtered **in the module**: a hit is the peak of the
piezo's signal over a short window, scaled to 0-255, with a hold-off after it
(steel plates ring) and a threshold, both settable with `CONFIG` and tuned at
the first build (HW2). The module queues at least 16 events. The box turns the
event's **age** into its own clock: `t_event = t_read - age`, so events are
timed on the box's game clock with no clock sync. Events of a disarmed channel
are acknowledged and dropped (as in the stub).

#### Outputs and the lease

**EXP-11. Every output is leased.** The module keeps an output on only while
the box keeps writing to it: an `OUTPUT` or `LEASE` command at least once per
lease. The box refreshes every **500 ms** with a lease of **1.5 s** (three
chances before the module gives up); the module refuses leases over 5 s. When
the lease runs out, the module turns every output off and sets
`LEASE_EXPIRED`. So whatever stops the box (a crash, a brown-out, a reboot, the
I2C driver suspending the module for 30 s, a cut cable, the box's game task
held up), the output is off within 1.5 s.

**EXP-12. Desired state, reconciled.** The box holds what each output should
be (off, on until a time, a pattern until a time) and compares it with the
`outputs` bitmap of each `STATUS` read; when they differ it sends the command
again with what is left of the duration. A lost write is repaired at the next
poll, and a module that restarted (`FRESH`) gets its state again, or `ALL_OFF`
if the game is not running. Pulses and patterns also run on the module's own
timer, so the output ends on time even between polls.

**EXP-13. Hard limits at three levels**, the lowest winning:

| Level | Limit | Set by |
| --- | --- | --- |
| Module | `max on` and `min off` per channel (in `CHANNEL`), relays no faster than every 100 ms, outputs off at power-up, after its watchdog resets it, and on brown-out | Its firmware's build settings, chosen by the builder for what is fitted (a smoke machine: for example 30 s on, 30 s off) |
| Box | Outputs enabled or not (off by default, EXP-28), a function name and a max on per channel (never above the module's), and the game-state rules of section 5 | The field's admin, at the box (admin PIN) |
| Game | The duration in each call; remote commands always carry one (EXP-23) | The mode, scenario or GM |

#### Errors and hot-plug

**EXP-14.**

- A `STATUS` with a bad CRC is refused and read again at the next poll; a
  refused write shows as `CMD_ERROR` and is sent again by the reconciliation
  (EXP-12).
- A module that fails 25 reads in a row (0.5 s for an input module; 6 s for an
  output-only one) is **gone**: its capabilities leave the box's list, the
  controller is told (section 4), and its outputs count as off (its lease has
  long run out by then).
- **Hot-plug:** the buffer connects a module only when the bus is idle. Every
  2 s the box probes one empty address of 0x58-0x5F with a one-byte address
  write; a module that answers is read (`IDENT`, `CHANNEL`s), sent `ALL_OFF`
  and `CLEAR_FRESH`, and added. A module plugged in during a game is usable at
  once by a mode that already calls its capability (calls before that were
  ignored).
- The box sends `ALL_OFF` to every module it finds at boot, before anything
  else.
- The bus's health records (`i2c_health.h`: a device suspended after 3
  failures, with a back-off up to 30 s) apply to modules too; the driver counts
  a suspended module's skipped polls as failed reads, so "gone" still comes on
  time, and the lease has turned its outputs off long before.

### 3. Modules for the first increment

#### One processor for both: an RP2040 board

| Processor | Cost (approx., hobby market) | Toolchain and flashing | Power at 3.3 V | Fit |
| --- | --- | --- | --- | --- |
| **RP2040** (RP2040-Zero, Pico and clones) | €3-5 a board | pico-sdk, C and CMake (like the rest of the firmware), GCC for Arm, builds in Docker; **flashing by dragging a UF2 file over USB**, no programmer | Under 25 mA at a reduced clock (48 MHz): **to be measured** at the first build | 12-bit ADC at up to 500 ksample/s for the piezo; an I2C target in the SDK; plenty of room |
| CH32V003 | €0.20 a chip, about €1-2 a board | ch32fun or MounRiver; needs a WCH-LinkE programmer (about €5) | A few mA | Very cheap, built-in op-amp and comparator; a later cost-down for a carrier PCB |
| ATtiny 2-series (ATtiny1616 class) | About €1 a chip | megaTinyCore (Arduino) or avr-gcc; needs a UPDI adapter | A few mA | Small, low power; fewer ready-made boards |
| ESP32-C3 (Super Mini) | €2-3 | ESP-IDF, the box's own toolchain; USB flashing | 20-80 mA: **over the 25 mA** unless its radio stays off and it is measured | Overkill; its radio is a temptation the port does not need |
| STM32C0 / G0 | €0.50-1 a chip | STM32Cube or libopencm3; needs an ST-Link | A few mA | Good, but boards are less common in the hobby market |

**EXP-15. The RP2040 is the reference processor** for both first modules: a
builder flashes it with a USB cable and a file, the build fits the project's
Docker and C conventions, and its ADC handles the piezo. The module's protocol
code is written as **portable C** (the register map, the lease, the event
queue; no SDK calls), so a CH32V003 or ATtiny port later is a new hardware
layer, not a new protocol. **Bare PCF8574 or MCP23017 relay boards are not
supported on the port**, even though they need no module firmware:

- they have no lease: a relay stays on for as long as the board has power if
  the box crashes with it on;
- they answer in 0x20-0x27 or 0x38-0x3F, where the box looks for its keypad
  expander; on a box without a keypad (every Satellite) the keypad driver
  would take the relay board for the keypad and click its relays every 10 ms;
- their state at power-up depends on the board (a PCF8574's pins come up high;
  an active-high relay board turns every relay on);
- their relay coils usually run from the board's VCC, which would be the
  port's 3.3 V.

The guide will say so, in bold, next to the output module.

#### (a) The target module (the target addon)

| Part | What |
| --- | --- |
| Processor | RP2040 board, powered from the port's 3.3 V (at most 25 mA, measured; run at 48 MHz) |
| Sensor | A piezo disc (27-35 mm) bonded to the back of the plate through a rubber pad; a resistor divider and a 1 Mohm bleed to set the level, Schottky clamps to 3.3 V and GND, into an ADC pin |
| Firmware | The ADC sampled continuously (DMA, about 20 ksample/s); a hit is a peak above the threshold, its strength the peak scaled to 0-255 (scale to be fixed on real plates); a hold-off (default 50 ms) against ringing; the event queued with its timestamp; the expansion protocol on the I2C target |
| Channels | 1 (`kind` hit). A two-plate module is the same firmware with 2 channels |
| Address | 0x58 (jumpers: 0x59-0x5B) |
| Plate, stand, enclosure | As listed in the target addon guide's section 5 (still HW2): steel or polycarbonate, angled down, electronics behind the plate |
| Own lights | None needed: *Target Windows* lights the box's ring (P5J-16) |

#### (b) The output module

**EXP-16. A small custom module drives an off-the-shelf relay board**, rather
than the box driving a relay board directly:

```
box port (M12) ── I2C isolator ── RP2040 board ── opto-isolated 4-relay board ── dry contacts ── siren, strobe, smoke remote
   3.3 V, ≤ 5 mA ─┘ (box side)      └── powered from the module's own supply (buck 5 V) ──┘
```

| Part | What |
| --- | --- |
| Box side | An **I2C isolator** (ISO1540 / ADuM1250 class, ready-made breakouts exist); its box side is the only load on the port's 3.3 V (a few mA). The box and the loads share no ground |
| Supply | The module's own input, 9-15 V DC (a 12 V battery is typical), through a fuse and a reverse-polarity diode or MOSFET, to a buck converter for 5 V (relay coils, the RP2040 board) |
| Relays | A common 4-channel opto-isolated relay board, coils from the module's 5 V; or a MOSFET board for DC loads that are switched often (strobes) |
| Firmware | The same portable protocol core: 4 channels of `kind` switched output, the lease, the hard limits, patterns run in the module, outputs off at power-up and after the watchdog |
| Address | 0x5C (jumpers: 0x5D-0x5F) |
| Enclosure | IP65 with cable glands; the supply and the loads on their own connectors, never the port's |

**How loads attach.** The module's relays give **dry contacts** (they close a
circuit; they carry no power of their own):

- **Sirens, horns, strobes, beacons on 12 V DC:** the load's own battery
  through the relay contacts, with a fuse sized for the load. A diode across
  any DC motor or coil load.
- **Smoke machines:** only through a **documented low-voltage remote input**
  (a contact input, 0-5 V or a 12 V trigger in the maker's manual), or a
  battery smoke device made to be triggered by a contact. **Many cheap mains
  fog machines carry mains voltage on their wired remote's cable: never wire a
  relay into one.** DMX is out of scope for v1.
- **Pyrotechnics, igniters and smoke grenades are out of scope**, always.

**EXP-17. Mains wiring is out of scope.** The project's modules switch
**SELV loads only (at most 24 V DC, 2 A per channel recommended)**. A field
that wants to switch a mains device uses a commercially made, CE-marked (or
locally certified), enclosed switching unit with a low-voltage control input,
installed as its maker says, and drives that input from a dry contact. The
guides never show mains wiring. This adds to the design specification's
section 17 ("the relay output is for commercial game smoke, strobes and sirens
only, used within local law").

Approximate parts: target module €10-15 without the plate and cable; output
module €25-35 without the supply and loads (RP2040 board €4, isolator €4-6,
relay board €3-5, buck converter €2, fuse and protection €2, enclosure and
glands €8, M12 socket €4).

### 4. The capability model

#### Capabilities and their ids on a box

**EXP-18. Two capability types are used, both already in the design
specification's section 7:**

| Type | Events | Commands | From |
| --- | --- | --- | --- |
| `hit` | `hit` with `strength` 0-255 (scripts get `hit.hit`) | `arm`, `disarm` | A channel of `kind` hit (draft RFC 0000 Amendment 1, unchanged; a second hit channel adds `channel` to the event's data) |
| `output` | -- | `on(max_ms)`, `off()`, `pulse(ms)`, `pattern(on_ms, off_ms, ms)` | A channel of `kind` switched output |

`contact` (a tripwire, a pressure mat, a door: events `closed` and `opened`)
is reserved in the frame format and added by its own RFC amendment with its
first module.

**EXP-19. Output capability ids name the function**, so a script says what it
wants and the box finds the channel: `siren`, `strobe`, `smoke`, `light`,
`horn`, else `out.<n>`. Each output channel's function is the module's `hint`
unless the field's admin set another at the box (EXP-28); a second channel
with the same function is `siren.2`. A hit channel is `hit` (then `hit.2`). A
script's call to a capability the box does not have does nothing (the core's
`cap()` proxy forwards it, and the box ignores an unknown target), so a mode
written for a box with a siren still runs on one without.

**EXP-20. Capability type ids for HELLO.** HELLO's key 6 has always been
"capability type ids" with no table; the box sends it empty. A table in a new
`protocol/schema/capabilities.yaml`, generated into the C, Python and Dart
codecs like the other tables:

| Id | Type | Id | Type |
| --- | --- | --- | --- |
| 1 | `button` | 8 | `gps` |
| 2 | `keypad` | 9 | `imu` |
| 3 | `display` | 10 | `hit` |
| 4 | `led` | 11 | `output` |
| 5 | `audio` | 12 | `battery` |
| 6 | `nfc` | 13 | `tamper` |
| 7 | `qr` | 14 | `contact` (reserved) |

The box fills key 6 with the types it has, modules included.

#### How the controller and the console learn which modules a box has

**EXP-21. Three new events** (their ids and new data keys are the next free
ones when built; today events 57, 58 and 59, data keys from 42):

| Event | Priority | Data | When |
| --- | --- | --- | --- |
| `node.modules` | normal | `modules`: a compact text, for example `58:target/1.0.0:hit;5c:out4/1.0.0:siren,strobe,smoke,out.4`, at most 100 bytes | After HELLO is acknowledged, and whenever a module comes or goes |
| `node.module_lost` | critical | `modules` (the module that went), `reason` (`no_answer`, `bad_ident`) | A module the box had during a running game stops answering |
| `output.switched` | normal | `capability` (the function), `ms` (0 = off), `source` (`script`, `field`, `gm`, `box_admin`) | Each time an output turns on, and when one is turned off before its time: the game's record of who fired what |

The controller keeps the last `node.modules` per node; `GET /api/v1/nodes`
adds `modules` (a list of `{address, model, fw, caps}`), and both controllers
(the Pi's and the phone's) serve the same answer, checked by
`protocol/vectors/controller_api.json`. The console's box list shows each
module as a chip under the box (a target, an output with its functions), and
an "outputs disabled on this box" note when the box says so.

**The start check** gains capabilities: for each node that joined in a role,
the role's `requires:` capabilities it lacks are **missing**, like a missing
role (Start refuses unless forced); `optional:` ones it lacks are a warning.
Nodes whose HELLO lists no capability (firmware from before this change) are
not checked, so nothing that starts today stops starting.

#### How a mode or scenario says it uses an output

**EXP-22.** A role lists `output` (and `hit`) in `requires:` or `optional:`, as
it lists `led` today, and may name the functions it calls in a new optional
list, `outputs: [siren, smoke]`, which the console shows ("Bomb would use:
smoke, siren") and the start check warns about when a box of that role has
none of them. The mode validators (the simulator's, both controllers') accept
the new key; an older controller ignores unknown role keys.

#### How game logic switches an output

| Who | How | Example |
| --- | --- | --- |
| A node script (`node.lua`) on the box itself | `cap("<function>")` | `cap("smoke"):pulse(params.smoke_s * 1000)` in Bomb's explosion handler |
| A field script (`field.lua`) on the controller, a mode's or a scenario's | `field.send(node_id, "output", {capability = "siren", act = "pulse", ms = 10000})`: CMD opcode 12 (EXP-23) | Master and Satellites: one team holds every satellite |
| A scenario's manifest | `triggers` (EXP-25), compiled into `field.lua` | "When `sat_a`, `sat_b` and `sat_c` are completed: `siren` on `master` for 10 s" |
| The GM | The console's output controls (section 5) | "All outputs off" |

**EXP-23. CMD opcode 12, `output`** (an RFC 0001 amendment). Its `params`:

| Key | Value |
| --- | --- |
| `capability` | the function: `siren`, `smoke`, `out.2`, ...; or `*` with `act` `off` (every output of the box) |
| `act` | `on`, `off`, `pulse`, `pattern` |
| `ms` | required for `on`, `pulse`, `pattern`: 1 to 600000; the box also caps it at the channel's max on |
| `on_ms`, `off_ms` | for `pattern`: 100 to 10000 for a relay channel (10 to 10000 for a solid-state one) |
| `src` | `field` or `gm` (set by the controller, never by a client) |

The firmware handles it (not the mode script), so it works whatever mode or
scenario the box runs. An `on` without `ms` from the radio is refused: a box
that loses the controller then keeps the output on for that time at most. Over
Wi-Fi it is a `cmd` message with `cmd: "output"`, `opcode: 12`
([protocol/prop-link.md](../../protocol/prop-link.md)). A box from before the
amendment logs the opcode as unknown and ignores it.

**EXP-24. Node scripts' output calls**, handled by the box's command dispatch:

| Call | Meaning |
| --- | --- |
| `cap("siren"):pulse(ms)` | On for `ms`, then off |
| `cap("siren"):on()` / `:on(max_ms)` | On until `:off()`, for at most `max_ms` or the channel's max on |
| `cap("siren"):off()` | Off now |
| `cap("strobe"):pattern(on_ms, off_ms, ms)` | Blinks for `ms` (the module runs the pattern; a script never toggles a relay itself) |

**EXP-25. Scenario triggers.** A manifest gains an optional top-level
`triggers:` list, compiled into `field.lua` by the core's scenario compiler
(so both controllers get it at once):

```yaml
triggers:
  - when: { completed: [sat_a, sat_b, sat_c] }   # all of them; or { any_completed: [...] }, { failed: x }, { game: start }, { game: end }
    output: { node: master, capability: siren, act: pulse, seconds: 10 }
```

The validator checks the references (objectives, `nodes`), the capability
name, and `seconds` (1-600). The console's scenario blocks get a **Triggers**
category: a "when" block (all completed, any completed, failed, game start,
game end) holding an "output" block (box, function, how long). Shared cases go
in `protocol/vectors/scenario.json` and `scenario_compile.json`.

#### The phone and the I/O pod

**EXP-26.** The I/O pod gets the same port and runs the box's expansion
driver, so a phone prop gains a target or outputs through its pod:

- the pod lists the modules' capabilities in its IDENT
  ([protocol/capability-proxy.md](../../protocol/capability-proxy.md)): `hit`
  as Amendment 1 already says, and `{"id": "siren", "type": "output"}` with
  CMD `on {"ms"}`, `off`, `pulse {"ms"}`, `pattern {"on_ms","off_ms","ms"}`;
- **the pod holds the lease**, not the phone: when the phone's USB or
  Bluetooth link drops, the pod turns every output off within 2 s, and at the
  game's end, as a box does;
- the app's prop shell passes the mode's `cap("siren")` calls to the pod, and
  handles CMD 12 from the controller like a box.

The phone as field controller (Android) serves the same output API and CMD 12
as the Pi (contract vectors). An iPhone is not a prop or a controller (those roles
are Android-only, design specification section 5), but its browser runs the
GM console, outputs panel included.

### 5. Security and safety

**EXP-27. Who may switch an output:**

| Source | On | Off |
| --- | --- | --- |
| The box's own mode script | Yes, within the limits | Yes |
| A field script or scenario trigger (CMD 12, `src: field`) | Yes, always with a duration | Yes |
| The GM in the console, on the field (gm token) | Yes, after a confirmation, with a duration (default 5 s, at most the channel's max on) | Yes, one tap; and **All outputs off** for the whole game |
| A remote GM through the site server | **No** | Yes |
| Readers, players, marshals, scoreboards (any other token, MQTT login or the player app) | No | No |
| The field's admin at the box (admin PIN menu) | Only a 1 s test, and only while no game runs | Yes |

A player can still *cause* an output through the game (failing to defuse the
bomb fires the smoke): that is the mode's logic, not a player's control.

**EXP-29. Fail-safe states.** Off is the safe state everywhere: relays normally open,
modules off at power-up, after their watchdog and on brown-out.

| Moment | What happens to outputs |
| --- | --- |
| Box boots, or finds a module | `ALL_OFF` before anything else |
| Game paused | All off; a resumed game does not turn them back on (the mode may) |
| Game ends | All off, then for **10 s** the mode's own `game.end` handler and `game: end` triggers may pulse an output (an end-of-game horn), for at most 10 s |
| Script halted by the sandbox | All off |
| Box loses the controller (radio or Wi-Fi) | The box's own outputs carry on (the box plays on its own, as today); remote ones end at their duration |
| Box crashes, reboots, browns out, or its I2C driver suspends the module | The module's lease ends them within 1.5 s |
| Cable cut or module unplugged | The same, on the module; the box reports `node.module_lost` |
| Phone link to a pod drops | The pod turns them off within 2 s |
| Controller crashes | As radio loss |

**EXP-28. Outputs are off on a box until the field's admin enables them at
the box** (admin PIN), with each channel's function and max on. The setting is
kept on the box, shown on its admin screen and in the console's box list. A
box someone borrows from another field, or a module plugged into a box at the
safe zone, can never fire until a person at that box says so.

**EXP-30. Rate limits.** The box accepts at most 2 output starts per second per
channel from a script (more are dropped and logged once as `script.error`);
patterns run in the module, so nothing needs more. The controller sends CMD 12
to a node at most once per 2 s (the radio's airtime is shared and
duty-cycled); `off` is never held back. Relay channels switch no faster than
every 100 ms (the module enforces it).

**Sound and law.** The specification's rule stays: siren and speaker levels
capped by default, louder only with the admin PIN; outputs used within local
law. The guide adds: hearing protection near sirens and horns, smoke never in
enclosed rooms without the venue's approval, nothing that looks like an
explosive (section 17's prop appearance).

### 6. Testing

| Level | What | Where |
| --- | --- | --- |
| Shared vectors | `protocol/vectors/expansion.json`: CRC cases (address included); `IDENT`, `CHANNEL`, `STATUS` frames, good and bad (magic, version, CRC, lengths); `COMMAND` frames with their bytes; **timelines**: a list of (time, box action, module action) steps with the outputs expected after each, covering the lease running out, a lost write repaired, a module restart (`FRESH`), a pulse spanning a missed poll, `max on` and `min off`, a relay pattern below 100 ms refused | Checked by the box driver's tests (C), the module core's tests (C) and the simulator's model (Python) |
| CMD and proxy vectors | CMD 12 params in `protocol/vectors/cmd.json`; the `output` descriptor, CMD and EVT in `capability_proxy.yaml`; `node.modules`, `node.module_lost`, `output.switched` in `events.yaml` vectors | C, Python and Dart codecs, as every vector today |
| Box driver host tests | `firmware/esp32/test/test_expansion.c` (replacing `test_target_addon.c`): discovery, hot-plug, the reconciliation, the lease refresh schedule, game-state rules (pause, end with its 10 s grace, halt), rate limits, at most 4 modules | `python3 tools/docker_fw.py test` |
| Module core host tests | The portable protocol core with a fake clock, fake ADC and fake relays: event queue, overflow, ack, arm, lease expiry, hard limits, power-up off | A new `firmware/expansion/` (or `modules/`) test target in the same Docker image |
| Box and module together, no hardware | **The host box with simulated modules**: `box_host --module target@58 --module out4@5c` links the real module core on a fake I2C bus inside the host box; its output states go to its log and to a small status file for the tests; hits are injected from the test | `firmware/esp32/test/box_host/`, as `pod_host` and `modem_host` are built today |
| End to end | `controller/tests/test_expansion_e2e.py`: a game with the C host box and simulated modules; a scenario trigger fires `siren` (CMD 12 over the C host modem); the GM's "All outputs off"; killing the host box turns the simulated output off within 1.5 s; the start check with and without the required `hit`. The phone controller runs the same cases (`app/test/controller/`) | `tools/check.sh`, CI |
| Simulator | The web simulator draws a box's outputs (a siren icon on, a smoke icon on) and lets a user fire hits; modes' tests can assert outputs (`expect_output`) | `simulator/` |

**Bench tests, when the hardware arrives (HW2):**

1. The port: rise time of SDA and SCL with 2 m of cable at 100 kHz (under
   1 µs); the keypad, NFC reader and gauge still work with a module plugged in.
2. The buffer: short SDA to GND on the cable; the box's keypad keeps working;
   the module is back within a second of removing the short.
3. Hot-plug: 100 plug and unplug cycles during a running game; no box reset,
   no stuck bus, every plug-in found within 2 s.
4. Port supply: a short between pins 1 and 3 does not reset the box; the target
   module's current under 25 mA (at 48 MHz and while sampling).
5. The lease: with a relay on, pull the box's power, reset the box, cut the
   cable, unplug the module: off within 1.5 s each time (a stopwatch on video).
6. Noise: switch a 12 V siren and a strobe for 30 minutes while the box polls a
   target module next to them: count CRC errors and missed polls.
7. Isolation: no continuity between the port's GND and the output module's
   supply ground.
8. The piezo: thresholds, hold-off and the strength scale on steel and
   polycarbonate plates, at the field's joule limit, with eye protection.
9. Static: touch the port's pins and the cable's shell after walking on a
   carpet or a dry field; the box carries on.
10. Smoke: a battery smoke device or a fog machine with a documented
    low-voltage input, fired by Bomb's explosion, stopped by the GM's "All
    outputs off" and by the end of the game.

### 7. Implementation plan

Increments in order; those on the same line of the "after" column can run in
parallel. Sizes: S about a day of agent work, M two to four, L more.

| # | Increment | Changes | After | Size |
| --- | --- | --- | --- | --- |
| 1 | **Protocol** | `protocol/expansion-port.md` (the register map, models, addresses); `protocol/vectors/expansion.json`; `protocol/schema/capabilities.yaml` (EXP-20) and the generator; RFC 0001 amendment for CMD 12; draft RFC 0000 amendment for `output` (and the `channel` of a second hit); events and data key in `events.yaml`; `capability_proxy.yaml` and `cmd.json` vectors; design specification sections 6, 7 and 17 | this RFC accepted | M |
| 2 | **Box driver** | `firmware/esp32/main/expansion.c/.h` (replaces `target_addon.c/.h`): discovery, ident, polling, reconciliation, lease, limits; host tests against the vectors and a C model; still not called | 1 | M |
| 3 | **Module core** | Portable C protocol core for modules (I2C target state machine, registers, event queue, lease, limits) with host tests; the C model of 2 replaced by it | 1 | M |
| 4 | **Box integration** | Called from the game task; `command_dispatch.c` for `output` and `hit`; hits to the script as `hit.hit`; game-state rules (pause, end with grace, halt, boot); HELLO capabilities filled; `node.modules`, `node.module_lost`, `output.switched`; CMD 12 in `box_game.c`; admin settings (outputs enabled, functions, max on) in the admin PIN menu and the serial console, pt/en/de/zh-tw screen texts; `box_host --module` | 2, 3 | L |
| 5 | **Controllers and console** | Pi and phone: CMD 12 for `field.send(..., "output", ...)`, the rate limit, `modules` in the node list, capability start check (EXP-21), the GM output API (`POST /api/v1/games/{id}/nodes/{node}/output`, `POST /api/v1/games/{id}/outputs/off`, gm token only; the remote GM's off only); contract cases in `controller_api.json`; the console's module chips and outputs panel in four languages; e2e test | 1 (4 for the e2e test) | M |
| 6 | **Modes** | Validators accept a role's `outputs:` (simulator, both controllers); Bomb: optional `smoke_s` and `siren_s` on explosion; Master and Satellites: optional `siren_all_s` when one team holds every satellite (in `field.lua`); Target Windows a Field Box preset once 8 is built; simulator drawing outputs; mode tests | 4, 5 | S-M |
| 7 | **Scenario triggers** | `triggers:` in `core/scenario/` (validator, compiler, runtime), `scenario.json` and `scenario_compile.json`, the console's Triggers blocks in four languages | 5 | M |
| 8 | **Module firmware** | `firmware/expansion/` on pico-sdk: the target module (ADC, DMA, peak detection) and the output module (relays, watchdog, power-up off) on the module core; `tools/docker_module.py`; CI builds the UF2 files; release attaches them | 3 | M |
| 9 | **I/O pod** | The pod runs the expansion driver, lends `hit` and `output` over the proxy, holds the lease, turns outputs off on link loss; the app's prop shell maps them and handles CMD 12; vectors | 4 | M |
| 10 | **Guides** | `hardware/expansion-port/BUILD.md` (the port board: socket, buffer, TVS, fuse, diode), the target addon guide made buildable, `hardware/output-module/BUILD.md` with the mains and smoke warnings, both in en and pt; `tools/check_wiring.py` for the port's table; the build page (by the coordinator) | 8 (text can start after 1) | M |
| 11 | **Bench (HW2)** | Section 6's bench list on real boards; thresholds and limits tuned; photos | 4, 8, 10 and the parts | -- |

Each increment updates its component's README, the phase's STATUS.md and the
CHANGELOG, and runs the component's tests, as every change does.

## Compatibility

- **Boxes without a port, or with nothing plugged in:** no change. The driver
  finds no module, the box lists no `hit` or `output`.
- **Older firmware:** ignores CMD 12 (unknown opcode, logged). Its HELLO lists
  no capability, so the new start check skips it.
- **Older controllers** check events against their schema and would refuse
  the three new ones, so both controllers must know them before a box sends
  them (increments 1 and 5 are released before 4). They ignore unknown role
  keys (`outputs:`).
- **Modes:** `cap("siren")` on a box without one does nothing, so modes can
  call outputs unconditionally.
- **The draft target report of P5J-19** is replaced; nothing was built against
  it. `target_addon.c` and its test go when the new driver comes (increment 2).
- **The M12 port's wiring** (P5J-15 to P5J-21) is unchanged; the box gains the
  buffer and the protection on its side (EXP-4).

## Alternatives

Each section above lists its own; the main ones:

- **Two designs** (a hit bus and a relay output): two connectors and drivers
  for the same box with no GPIO for either.
- **Off-the-shelf PCF8574 relay boards on the box's bus** with no module
  firmware: no lease, an address clash with the keypad's probe, undefined
  power-up states (EXP-15).
- **RS-485 or CAN for sturdiness:** needs GPIOs the Field Box lacks; kept as a
  possible extender module behind the I2C port.
- **An interrupt line:** no GPIO, and the game task's 10 ms tick limits what it
  could gain (EXP-8).
- **Outputs only through the radio** (a separate "relay node" box that listens
  for events, the specification's section 11 sketch): still possible with this
  design (a Satellite with an output module is exactly that), but every box
  that wants a siren would need a second node; the port lets the box that
  knows the game state switch its own siren.
- **The GM free to switch outputs remotely without limits:** a remote person
  cannot see who stands next to a smoke machine (EXP-27).

## Open questions

Each with the recommended answer.

1. **Add the hot-swap buffer, the TVS and the back-feed diode to every port**
   (about €3-8 more per port)? *Recommended: yes.* A wet M12 socket is the most
   likely field failure, and without the buffer it takes the keypad and NFC
   reader with it.
2. **The RP2040 as the reference processor** for both first modules (over the
   CH32V003, the ATtiny 2-series and the ESP32-C3)? *Recommended: yes*, with the
   protocol core in portable C so a cheaper processor can follow on a carrier
   PCB.
3. **An I2C isolator required in every output module** (no shared ground with
   the loads)? *Recommended: yes.* The alternative (a common ground for loads
   up to 12 V) saves about €5 and invites ground loops and relay noise into
   the box's bus.
4. **Addresses 0x58-0x5F, input modules default 0x58, output modules 0x5C, at
   most 4 modules a box?** *Recommended: yes.*
5. **Outputs at the end of a game:** all off, with a 10 s grace for the mode's
   end handler and `game: end` triggers (an end horn)? *Recommended: yes.*
6. **Outputs on pause:** all off, not restored on resume? *Recommended: yes*:
   a paused game is often a safety stop.
7. **A remote GM (through the site server) may only switch outputs off?**
   *Recommended: yes.*
8. **Enabling outputs only at the box (admin PIN), not from the console,** in
   v1? *Recommended: yes*: someone has to be at the box and see what is wired
   to it. A console switch for the field's admin can come later.
9. **A port on the field controller (a Pi siren at the safe zone)?**
   *Recommended: not in v1*: a Satellite with an output module next to the
   controller does it with nothing new.
10. **Not supporting bare PCF8574 relay boards on the port** (EXP-15)?
    *Recommended: confirm*; the guide says it in bold.
11. **The start check refuses a start when a joined node lacks a role's
    `requires:` capability** (force overrides), for nodes that report their
    capabilities? *Recommended: yes*: a target with no plate makes the game
    pointless, and older nodes are not checked.
12. **The `output.switched` event on the radio** (a few per game) as the record
    of who fired what? *Recommended: yes*, normal priority.
13. **The lease: 1.5 s, refreshed every 500 ms, at most 5 s?** *Recommended:
    yes.* Shorter costs bus time for nothing; longer leaves a smoke machine on
    longer after a crash.
14. **Replace the P5J-19 draft report** with `STATUS` (not compatible)?
    *Recommended: yes*, no addon was built against the draft.
15. **SELV only (24 V DC, 2 A per channel) in the guides, mains out of scope,
    pyrotechnics never** (EXP-17)? *Recommended: yes.*
16. **This as its own RFC** (numbered by the maintainer on acceptance), with
    the CMD opcode as an RFC 0001 amendment and `output` as an amendment of the
    phase 3 draft RFC? *Recommended: yes.*

## Decisions in this RFC

| # | Decision |
| --- | --- |
| EXP-1 | M12 A-coded 5-pin, P5J-20 pin-out; pin 5 reserved, not connected |
| EXP-2 | The port on the Field Box, the Satellite and the I/O pod, optional; no GPIO, no pin change |
| EXP-3 | Loads from their own supply, never from the box; 25 mA on pin 1 for module logic only |
| EXP-4 | Hot-swap buffer with stuck-bus recovery, TVS, series resistors, PTC, back-feed diode on the box's side |
| EXP-5 | I2C behind the buffer; longer distances through a Satellite or a later extender module |
| EXP-6 | 100 kHz |
| EXP-7 | Addresses 0x58-0x5F; defaults 0x58 (inputs), 0x5C (outputs); jumpers add 0-3; at most 4 modules |
| EXP-8 | Polled: input modules every 20 ms, output-only every 250 ms; no interrupt line |
| EXP-9 | Expansion protocol v1: `IDENT`, `CHANNEL`, `STATUS`, `COMMAND`, CRC-8 (the write's covering the address) |
| EXP-10 | Inputs filtered in the module; events timed by their age on the box's clock |
| EXP-11 | Every output leased: 1.5 s, refreshed every 500 ms, at most 5 s |
| EXP-12 | Desired state on the box, reconciled with each `STATUS` |
| EXP-13 | Hard limits in the module, the box and the call; the lowest wins |
| EXP-14 | Errors, gone after 25 failed reads, hot-plug by probing one empty address every 2 s, `ALL_OFF` at discovery and boot |
| EXP-15 | RP2040 reference processor, portable protocol core; bare PCF8574/MCP23017 relay boards not supported |
| EXP-16 | Output module: I2C isolator, own supply, RP2040, off-the-shelf opto-isolated relay board |
| EXP-17 | SELV loads only; mains out of scope; smoke machines only through documented low-voltage inputs; no pyrotechnics |
| EXP-18 | Capability types `hit` (unchanged) and `output` (on, off, pulse, pattern); `contact` reserved |
| EXP-19 | Output ids name the function (`siren`, `smoke`, ... else `out.N`); calls to missing capabilities do nothing |
| EXP-20 | A capability type id table for HELLO key 6, filled by the box |
| EXP-21 | Events `node.modules`, `node.module_lost`, `output.switched`; modules in the node list; capability start check for nodes that report capabilities |
| EXP-22 | A role's optional `outputs:` list of functions |
| EXP-23 | CMD opcode 12 `output`, handled by the firmware; remote `on` always with a duration |
| EXP-24 | Node scripts: `cap(fn):pulse`, `:on`, `:off`, `:pattern` |
| EXP-25 | Scenario `triggers:` with an `output` action, and console blocks |
| EXP-26 | The I/O pod gets the port, lends `hit` and `output` over the proxy and holds the lease |
| EXP-27 | Who may switch: game logic and the GM on the field; the remote GM off only; never players |
| EXP-28 | Outputs disabled on a box until its admin enables them at the box |
| EXP-29 | Fail-safe table: off at boot, discovery, pause, end (10 s grace), halt; leases end the rest |
| EXP-30 | Rate limits: 2 starts/s per channel from scripts, CMD 12 once per 2 s per node (off never held), relays every 100 ms at most |
