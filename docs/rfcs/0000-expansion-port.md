<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# RFC 0000: The expansion port, the simple output, and their first modules

- **Author(s):** The Atalaia contributors (design requested by the maintainer on 2026-11-03)
- **Status:** Draft (2026-11-03): a design for the maintainer to approve; its open questions were approved on 2026-11-03, and increments 1 to 6 of section 8's plan are built (each in `docs/phase-5-community/STATUS.md`; the port driver of 6 is not yet called by the game task). Decisions are numbered **EXP-1** to **EXP-38** in this file. Updated the same day with the maintainer's decision EXP-31: two output paths, the single-GPIO simple output preferred
- **Discussion:** the pull request that adds this file
- **Replaces, once accepted:** the target addon's open items (P5J-9, P5J-21) and the draft report format of P5J-19; revisits P5J-7 (no outputs on the pod)

## Summary

One port and one protocol for what plugs into a box from outside:
**inputs** (a target plate's hits now, contacts and other sensors later) and,
where a box needs several channels or feedback, **outputs** (relays for
sirens, strobes, lights and smoke machines; most outputs take the simpler path
below). The port
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

**Outputs have a second, simpler path, and it is the preferred one**
(the maintainer's decision, EXP-31): the **simple output**, one free GPIO
sending an RC-servo signal (50 Hz, 1.0 ms off, 2.0 ms on) through a spare gate
of the level shifter every box already has, to an off-the-shelf **RC relay
switch** of the kind used in radio-controlled models. Such a switch turns its
relay off when the pulses stop, which is the lease in hardware: the box sends
the pulses in bursts of half a second that only its running game task renews.
No processor to flash, no bus, no buffer: two wires. It gives one channel per
GPIO and no feedback (the box cannot tell whether a switch is plugged in).
Inputs cannot use it, since a servo signal carries nothing back: the target
addon and every later sensor stay on the I2C port.

The first increments build the simple output, then the **target module** (the
target addon, an RP2040 board on the I2C port). A **4-channel I2C output
module** stays in the design as a later, optional increment, for a box that
needs more channels than it has free pins, or wants to know that its relays
are there.

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
| Who gets it | **Field Box, Satellite and I/O pod**, each optional (fitted when a box carries a target or a sensor; outputs usually take the simple output, section 4) | The field controller (a Pi): not in v1 (open question 9) |

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
(polynomial 0x07, initial value 0x00, no reflection: the old stub's
`target_addon_crc8`, now the driver's `expansion_crc8`). A write's CRC covers the address byte as sent (address
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
`protocol/expansion-port.md` with shared vectors (section 7). The box reads
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
| Box | Outputs enabled or not (off by default, EXP-28), a function name and a max on per channel (never above the module's), and the game-state rules of section 6 | The field's admin, at the box (admin PIN) |
| Game | The duration in each call; remote commands always carry one (EXP-23) | The mode, scenario or GM |

#### Errors and hot-plug

**EXP-14.**

- A `STATUS` with a bad CRC is refused and read again at the next poll; a
  refused write shows as `CMD_ERROR` and is sent again by the reconciliation
  (EXP-12).
- A module that fails 25 reads in a row (0.5 s for an input module; 6 s for an
  output-only one) is **gone**: its capabilities leave the box's list, the
  controller is told (section 5), and its outputs count as off (its lease has
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

### 3. Modules on the port

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

#### (b) The I2C output module (later, optional: EXP-31)

The simple output (section 4) is the default way to switch a load. This
module is for a box that needs more channels than it has free GPIOs, or
wants to know that its relays are there and powered.

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

### 4. The simple output: one GPIO, an RC relay switch

**EXP-31 (decided by the maintainer, 2026-11-03). Two output paths; the simple
output is the preferred one.** Sirens, horns, strobes and smoke-machine
remotes are switched by the **simple output** by default: one free GPIO, an
RC-servo signal, an off-the-shelf RC relay switch. The wiring is simpler and
it needs none of the protection the I2C port needs. The **I2C output module**
(section 3 (b)) stays as the option for a box that needs more channels than it
has free pins, or feedback (knowing the relays are there and powered); it is a
later, optional increment. **Inputs stay on the I2C port**: a servo signal
goes one way only and carries nothing back, so a target's hits and every later
sensor need the port.

#### What an RC relay switch is

A small board made for radio-controlled models: it plugs into a receiver's
servo socket (three wires: signal, + about 5 V, GND) and closes a relay when the
servo signal's pulse is long, opens it when the pulse is short. It needs no
programming and no firmware from us.

| Property | Typical (check each model's data) | What it means here |
| --- | --- | --- |
| Signal | 50 Hz frames (some take 40-400 Hz), pulses of 1.0-2.0 ms | The box sends 1.0 ms for off and 2.0 ms for on: the far ends, clear of any threshold |
| Threshold | Fixed near the middle (about 1.5 ms), or learned from the transmitter at set-up (a button and an LED); many have a reverse jumper | Set it up, or check it, once at the bench: 2.0 ms must be on, 1.0 ms off, with the reverse jumper (if any) in the normal position |
| Signal lost | Most go to off after some tenths of a second without valid pulses; **some hold the last state**, and some let the user choose | Only a switch that **turns off when the pulses stop** may be used (EXP-37): that is the fail-safe this path relies on |
| Supply | 4.8-6 V "receiver" supply (some take a wider range, up to 12-16 V), powering both its logic and its relay coil (about 50-100 mA with the relay on) | Powered from the **load side** through a small 5 V regulator (an RC "BEC" or a buck module), not from the box (EXP-33) |
| Signal level | Made for receivers, which give 3.3 V or 5 V servo signals; many accept 3.3 V, but not all say so | The box gives 5 V anyway through its level shifter's spare gate (EXP-33), so the switch's threshold does not matter |
| Contacts | One relay, usually 10 A at 250 V AC / 30 V DC as printed on the relay | Used for **SELV loads only** (EXP-17: at most 24 V DC, 2 A recommended), whatever the relay's print says |

Two kinds that fit, by type (no particular seller):

- **Pololu's RC switch with relay**: a documented board with a learned
  threshold and a fail-safe on loss of signal; its manual gives the input's
  logic level and the supply range. Pololu also sells versions with a MOSFET
  output instead of a relay, for DC loads switched often (strobes).
- **A generic "1-channel RC PWM relay switch" module** (sold for model lights
  and landing gear: a relay, a small processor, often a reverse jumper and an
  LED). Cheap and common; their behaviour on signal loss varies between
  batches, so each one is checked at the bench before it goes to the field
  (bench test 11).

#### The signal and the fail-safe

**EXP-32.**

- **Off is 1.0 ms, on is 2.0 ms**, at 50 Hz, while a game runs. A channel that
  is off still gets 1.0 ms pulses, so the switch sees a live "off".
- **The pulses come in bursts, not free-running.** The ESP32-S3's LEDC
  peripheral keeps a PWM going in hardware whatever the CPU does: if the game
  task hung with the output on (a hang the task watchdog only reports, as the
  firmware is configured), LEDC would hold the relay on for ever. So the box
  uses the **RMT peripheral with a loop count**: each burst is 25 frames
  (0.5 s), and the game task queues the next burst every 200 ms. If the task
  stops, the pulses stop within 0.5 s, and the switch's own signal-loss
  fail-safe opens the relay. This is the I2C path's lease (EXP-11), done by the
  pulses. The LED ring uses one of the S3's four RMT transmit channels; the
  simple outputs take one each (a box has at most two or three, below). LEDC
  with a software check was considered and refused for that reason; it stays
  the buzzer's (BZR-1).
- **Off at the fail-safe moments** (EXP-29: boot, pause, end, script halt): 1.0
  ms pulses for 0.5 s, then **no pulses at all, the pin held low**. Outside a
  game the pin stays low: the switch is in its signal-lost state, which is off.
- **At reset and boot** the pin is an input with no pulses; a 10 kohm resistor
  to GND at the level shifter's input holds it low, so the buffer's output is
  low and the switch sees no signal. A static level, or a single glitch while
  the board starts, is not a train of 2 ms pulses at 50 Hz, so it cannot turn a
  switch on. The pins below were chosen for their reset state (next table).

#### Wiring on the box

**EXP-33.**

- The GPIO goes to a **spare gate of the 74AHCT125** that every Field Box,
  Satellite and I/O pod already has for the LED ring: today gate 2 has 2OE and
  2A tied to GND and 2Y not connected (Field Box guide, section 8). For the
  simple output: 2A from the GPIO, with **10 kohm from 2A to GND**; 2OE stays on
  GND; 2Y through **330 ohm** to the output socket. The signal leaves the box
  at 5 V, buffered: a fault on the cable reaches the 74AHCT125 (a socketed chip
  that costs cents), not the ESP32. A second channel uses gate 3, a third gate
  4.
- **Connector:** an **M8 3-pin socket** (A-coded), different from the I2C
  port's M12 so the two cannot be swapped: pin 1 not connected (no power from
  the box), pin 3 GND, pin 4 signal. The RC switch's own servo plug goes on the
  module's side of the cable.
- **The switch's power comes from the load side**: the siren's or strobe's
  12 V battery through a fuse to a 5 V regulator, into the switch's + and GND.
  The box gives only the signal and GND. GND is shared with the box (no
  isolation on this path); this is acceptable for SELV loads on their own
  battery, and the reason a mains device is never wired to it (EXP-17).
- **Cable:** up to **2 m** of 3-core cable, signal and GND twisted. A 50 Hz
  signal with 1 ms pulses is slow (the edges need not be sharp: servo leads of
  a metre or more are common in models), and 5 V with 330 ohm in series makes
  it tolerant of pick-up. Keep it away from the load's own wires. Longer: a
  Satellite next to the load.

#### Which GPIOs are free

From the Kconfig defaults (`firmware/esp32/main/Kconfig.projbuild`), the
pin tables of the three build guides, `tools/check_wiring.py` (its strapping
pins 0, 45, 46, the Heltec V4's front-end-module pins 5 on the V4.3 and 46 on
the V4.2, the GNSS connector's 34 and 38-42), and, for the buzzer, branch
`feat-firmware-piezo-buzzer` as it stood on 2026-11-03 (not merged:
`ATALAIA_BUZZER_PIN`, default **GPIO 45**, decision BZR-1).

| Board | GPIOs it uses | Free today | Notes |
| --- | --- | --- | --- |
| **Field Box** (full) | 4, 48, 44 (buttons 1-3), 35 (LED ring), 33, 47, 1, 3 (display), 6, 15, 16 (I2S), 17, 18 (I2C) | **46 on a V4.3**, **5 on a V4.2**; 45 (taken by the buzzer when fitted) | The two revisions swap pins 5 and 46: each is the other revision's front-end-module line. `check_wiring.py` reserves both today because either board may be fitted; the build's board-revision choice (`Radio > Board revision`) knows which one is free |
| **Satellite** | 4, 48, 44 (optional), 35, 17, 18, 6, 15, 16 (optional amplifier) | **46 on a V4.3, 5 on a V4.2**; 45 (buzzer) | It runs the Field Box's firmware (P5J-2), which still drives the display pins **1, 3, 33, 47** although no display is fitted: they become free only for a build with the display pins set to -1 (to be checked: the display driver must then stay off). Without the optional amplifier, 6, 15 and 16 are free too |
| **I/O pod** | 4, 48, 44, 35, 17, 18, 6, 15, 16, 47 (enclosure switch) | **1, 3, 33**, and **46 on a V4.3, 5 on a V4.2**; 45 (buzzer) | The pod firmware has no display, so its guide already leaves 1, 3 and 33 unconnected. GPIO 1 has the board's battery divider (100 kohm to GND) on it: harmless for an output, and it holds the pin low at reset |
| **Board 5** (bench, for reference: `b5-bench.patch` on main) | Buttons and I2S off (-1); display moved to 48, 44, 6, 16; LED ring 35; keypad and OLED on 17, 18 | 1, 3, 15, 33, 47, 46 (a V4.3), 45 | GPIO 4 is dead (bad joint), and 33 and 47 had doubtful joints on 2026-10-31: use **15** for a bench test of the simple output |

Reset behaviour of the candidate pins (ESP32-S3):

| GPIO | At reset | For the simple output |
| --- | --- | --- |
| 46 | Strapping pin (with GPIO 0 in download mode, and the ROM log's verbosity); internal pull-down, so low | Good: low at reset is "no pulses". A switch input that pulled it up would not stop the board booting normally (it only matters with GPIO 0 low) |
| 5 | Ordinary GPIO, no strapping role | Good, with the 10 kohm pull-down |
| 45 | Strapping pin: VDD_SPI voltage; must be **low** at reset, or the board selects 1.8 V flash and does not boot | Usable only with a circuit that keeps it low (the buzzer's rule, BZR-1). The simple output's 10 kohm pull-down at the 74AHCT125's input does keep it low |
| 1, 3, 33 (pod) | 1: the battery divider holds it low; 3: JTAG source strap, ignored (no eFuse burnt); 33: ordinary | Good |
| 15 (board 5) | Ordinary (the 32 kHz crystal pin, not fitted on the V4) | Good on the bench |

#### The pin plan

**EXP-34.** A Kconfig option `ATALAIA_SIMPLE_OUT_PIN` (off by default, -1),
its default following the board revision:

| Board | Simple output 1 | More channels | With the buzzer |
| --- | --- | --- | --- |
| Field Box | **46** (V4.3), **5** (V4.2) | None | No clash: the buzzer has 45. A box without a buzzer could put a second simple output on 45 (`ATALAIA_SIMPLE_OUT2_PIN`, Kconfig refuses 45 when `ATALAIA_BUZZER=y`: buzzer **or** a second output) |
| Satellite | **46** (V4.3), **5** (V4.2) | 33 and 47, only in a build with the display pins set to -1 | As the Field Box |
| I/O pod | **33** | 1, 3, and 46 or 5 | No clash |
| Board 5 (bench) | **15** | -- | -- |

`tools/check_wiring.py` learns that GPIO 46 is allowed for this pin on a V4.3
build and GPIO 5 on a V4.2 build (as it allows 45 for the buzzer only), and the
guides gain a row each.

#### Limits, said plainly

**EXP-35.**

- **One channel per GPIO.** Carrying several channels on one pin by pulse width
  (1.2 ms for the siren, 1.4 ms for the strobe...) or as RC "PPM" frames would
  need a decoder at the far end (a processor, or an RC PPM decoder board): that
  is the I2C output module again, without its lease, its checks or its feedback,
  and one corrupted pulse would switch the wrong load (smoke instead of a
  strobe). Not recommended.
- **No feedback.** The box cannot tell whether a switch is plugged in, powered,
  or what it is wired to. So there is **no "module missing" warning**, no
  `node.module_lost`, and the start check cannot confirm a simple output (it
  counts one the admin configured, marked "not checked", section 5).
- **Outputs only.** Nothing comes back on the wire.
- **The fail-safe is the switch's.** If a switch holds its last state on signal
  loss, a hung box would leave it on: hence EXP-37 and bench test 11.
- **The same safety rules as the I2C path** (section 6): SELV loads only,
  outputs enabled at the box by its admin (admin PIN), function names and
  limits set there, off at boot, pause, end and halt, the same rate limits.
  The box enforces the max on per channel itself (there is no module to do it).

**EXP-37. Which RC switches may be used:** ones that **turn the output off
when the servo signal stops** (documented by the maker, or checked on the bench
with the box: unplug the signal with the relay on, it must open within a
second), with a threshold between 1.0 and 2.0 ms (2.0 ms on, 1.0 ms off after
any set-up), powered from the load side. The guide lists the check.

### 5. The capability model

#### Capabilities and their ids on a box

**EXP-18. Two capability types are used, both already in the design
specification's section 7:**

| Type | Events | Commands | From |
| --- | --- | --- | --- |
| `hit` | `hit` with `strength` 0-255 (scripts get `hit.hit`) | `arm`, `disarm` | A channel of `kind` hit (draft RFC 0000 Amendment 1, unchanged; a second hit channel adds `channel` to the event's data) |
| `output` | -- | `on(max_ms)`, `off()`, `pulse(ms)`, `pattern(on_ms, off_ms, ms)` | A simple output (section 4), or a channel of `kind` switched output of an I2C module |

`contact` (a tripwire, a pressure mat, a door: events `closed` and `opened`)
is reserved in the frame format and added by its own RFC amendment with its
first module.

**EXP-36. One capability, two paths; the simple output says it has no
feedback.** A mode does not know or care which path an output takes:
`cap("siren"):pulse(10000)` is the same call for a simple output and for an
I2C module's channel, and the box's output layer (desired state, limits,
game-state rules, rate limits, CMD 12, `output.switched`) is shared; only the
last step differs (RMT bursts, or `OUTPUT` and `LEASE` commands). The box
reports a simple output as an `output` channel with a **no-feedback flag**: in
`node.modules` its entry is `g<gpio>:servo:<function>` with no version (for
example `g46:servo:siren`), and `GET /api/v1/nodes` gives it `"feedback":
false`. The console shows it with a "not checked" mark, and it never raises
`node.module_lost`. `pattern` on a simple output is limited to on and off times
of at least 500 ms (an RC switch needs a few frames to change state, and a relay
should not chatter).

**EXP-19. Output capability ids name the function**, so a script says what it
wants and the box finds the channel: `siren`, `strobe`, `smoke`, `light`,
`horn`, else `out.<n>`. Each output channel's function is the module's `hint`
unless the field's admin set another at the box (EXP-28); a simple output has
no hint, so its function is whatever the admin sets (by default `out.1`, ...,
in pin order); a second channel
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
| `node.modules` | normal | `modules`: a compact text, for example `g46:servo:siren;58:target/1.0.0:hit;5c:out4/1.0.0:strobe,smoke,out.3,out.4`, at most 100 bytes | After HELLO is acknowledged, whenever a module comes or goes, and when the admin changes a simple output's settings |
| `node.module_lost` | critical | `modules` (the module that went), `reason` (`no_answer`, `bad_ident`) | A module the box had during a running game stops answering |
| `output.switched` | normal | `capability` (the function), `ms` (0 = off), `source` (`script`, `field`, `gm`, `box_admin`) | Each time an output turns on, and when one is turned off before its time: the game's record of who fired what |

The controller keeps the last `node.modules` per node; `GET /api/v1/nodes`
adds `modules` (a list of `{address, model, fw, caps}`), and both controllers
(the Pi's and the phone's) serve the same answer, checked by
`protocol/vectors/controller_api.json`. The console's box list shows each
module as a chip under the box (a target, an output with its functions), and
an "outputs disabled on this box" note when the box says so.

*Amended 2026-11-04 (EXPL-12, EXPL-13; draft RFC 0000 "Phase 3 events, tags and
pods", Amendment 6):* the note travels as a **fourth event**,
`node.outputs_disabled` (60, normal, data `modules`: the outputs fitted that the
box's admin has not enabled, in the same compact text, the empty text when
every one is), sent with `node.modules` by a box that has an output fitted. Not
a key of `node.modules`: the decoders refuse an unknown data key, so an older
controller would lose the whole `node.modules`; it refuses an unknown event
alone. The controllers give it as the node list's `outputs_disabled`, and the
start check adds a note (never a refusal or a warning) for a box whose role's
`outputs:` would switch one of them.

**The start check** gains capabilities: for each node that joined in a role,
the role's `requires:` capabilities it lacks are **missing**, like a missing
role (Start refuses unless forced); `optional:` ones it lacks are a warning.
Nodes whose HELLO lists no capability (firmware from before this change) are
not checked, so nothing that starts today stops starting. A simple output the
admin enabled counts as present (the box cannot check it): the console's start
panel says "siren on Master: not checked (simple output)", so the GM looks.

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
| The GM | The console's output controls (section 6) | "All outputs off" |

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
driver, and its free GPIOs (1, 3, 33) can carry simple outputs, so a phone prop
gains a target or outputs through its pod:

- the pod lists the modules' capabilities in its IDENT
  ([protocol/capability-proxy.md](../../protocol/capability-proxy.md)): `hit`
  as Amendment 1 already says, and `{"id": "siren", "type": "output"}` with
  CMD `on {"ms"}`, `off`, `pulse {"ms"}`, `pattern {"on_ms","off_ms","ms"}`;
- **the pod holds the lease** (or sends the RMT bursts), not the phone: when
  the phone's USB or Bluetooth link drops, the pod turns every output off
  within 2 s, and at the game's end, as a box does;
- the app's prop shell passes the mode's `cap("siren")` calls to the pod, and
  handles CMD 12 from the controller like a box.

The phone as field controller (Android) serves the same output API and CMD 12
as the Pi (contract vectors). An iPhone is not a prop or a controller (those roles
are Android-only, design specification section 5), but its browser runs the
GM console, outputs panel included.

### 6. Security and safety

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
| Box boots, or finds a module | `ALL_OFF` before anything else; simple outputs' pins held low (no pulses) |
| Game paused | All off; a resumed game does not turn them back on (the mode may) |
| Game ends | All off, then for **10 s** the mode's own `game.end` handler and `game: end` triggers may pulse an output (an end-of-game horn), for at most 10 s |
| Script halted by the sandbox | All off |
| Box loses the controller (radio or Wi-Fi) | The box's own outputs carry on (the box plays on its own, as today); remote ones end at their duration |
| Box crashes, reboots, browns out, or its I2C driver suspends the module | The module's lease ends them within 1.5 s; a simple output's bursts stop within 0.5 s and the RC switch opens on signal loss (EXP-32, EXP-37) |
| Cable cut or module unplugged | The same, on the module; the box reports `node.module_lost`. A simple output's switch loses its signal and opens; the box cannot tell |
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
duty-cycled); `off` is never held back. A simple output changes state no
faster than every 500 ms (EXP-36). Relay channels switch no faster than
every 100 ms (the module enforces it).

**Sound and law.** The specification's rule stays: siren and speaker levels
capped by default, louder only with the admin PIN; outputs used within local
law. The guide adds: hearing protection near sirens and horns, smoke never in
enclosed rooms without the venue's approval, nothing that looks like an
explosive (section 17's prop appearance).

### 7. Testing

| Level | What | Where |
| --- | --- | --- |
| Shared vectors | `protocol/vectors/expansion.json`: CRC cases (address included); `IDENT`, `CHANNEL`, `STATUS` frames, good and bad (magic, version, CRC, lengths); `COMMAND` frames with their bytes; **timelines**: a list of (time, box action, module action) steps with the outputs expected after each, covering the lease running out, a lost write repaired, a module restart (`FRESH`), a pulse spanning a missed poll, `max on` and `min off`, a relay pattern below 100 ms refused | Checked by the box driver's tests (C), the module core's tests (C) and the simulator's model (Python) |
| CMD and proxy vectors | CMD 12 params in `protocol/vectors/cmd.json`; the `output` descriptor, CMD and EVT in `capability_proxy.yaml`; `node.modules`, `node.module_lost`, `output.switched` in `events.yaml` vectors | C, Python and Dart codecs, as every vector today |
| Box driver host tests | `firmware/esp32/test/test_expansion.c` (replacing `test_target_addon.c`): discovery, hot-plug, the reconciliation, the lease refresh schedule, game-state rules (pause, end with its 10 s grace, halt), rate limits, at most 4 modules | `python3 tools/docker_fw.py test` |
| Simple output host tests | `firmware/esp32/test/test_simple_out.c`: the burst scheduler against a fake RMT (bursts of 25 frames queued every 200 ms; widths 1.0 and 2.0 ms; no burst queued when the game task stops; 1.0 ms then a low pin at pause, end, halt and boot; the max on; the 500 ms pattern floor; refused pins: 45 with the buzzer, 46 on a V4.2, 5 on a V4.3) | `python3 tools/docker_fw.py test` |
| Module core host tests | The portable protocol core with a fake clock, fake ADC and fake relays: event queue, overflow, ack, arm, lease expiry, hard limits, power-up off | A new `firmware/expansion/` (or `modules/`) test target in the same Docker image |
| Box and module together, no hardware | **The host box with simulated modules**: `box_host --module target@58 --module out4@5c --simple-out siren` links the real module core on a fake I2C bus inside the host box, and records the simple output's pulse trains; its output states go to its log and to a small status file for the tests; hits are injected from the test | `firmware/esp32/test/box_host/`, as `pod_host` and `modem_host` are built today |
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
11. Each RC relay switch before its first game: 2.0 ms closes it, 1.0 ms opens
    it; with the relay closed, unplug the signal: it opens within a second. A
    switch that holds its state is not used (EXP-37).
12. The simple output's fail-safe: with the relay on, stop the game task (a
    bench build's hang command), reset the box, pull its power: the relay
    opens within about a second each time; the relay does not click while the
    box boots (20 power cycles, watched on video).
13. The signal at the far end of 2 m of cable, on a scope, next to a switching
    12 V siren: clean 5 V pulses, widths within 50 µs.

### 8. Implementation plan

Increments in order (EXP-38, following EXP-31: the simple output first among the output work,
the I2C output module last and optional). Sizes: S about a day of agent work,
M two to four, L more.

| # | Increment | Changes | After | Size |
| --- | --- | --- | --- | --- |
| 1 | **Protocol** (both paths and the target need it) | `protocol/schema/capabilities.yaml` (EXP-20) and the generator; draft RFC 0000 amendment for `output` (with the no-feedback flag, EXP-36, and the `channel` of a second hit); RFC 0001 amendment for CMD 12; events and data keys in `events.yaml`; `capability_proxy.yaml` and `cmd.json` vectors; `protocol/expansion-port.md` (the register map, models, addresses) and `protocol/vectors/expansion.json`; design specification sections 6, 7 and 17 | this RFC accepted | M |
| 2 | **Simple output and the box's output layer** | The shared output layer (`firmware/esp32/main/outputs.c/.h`: desired state, max on, game-state rules with the end grace, rate limits, `output.switched`); the RMT burst back-end (`simple_out.c`, EXP-32) and `ATALAIA_SIMPLE_OUT_PIN` (and `_OUT2_PIN`) in Kconfig, defaults by board revision, 45 refused with the buzzer (coordinated with BZR-1); `command_dispatch.c` for `output`; CMD 12 in `box_game.c`; HELLO capabilities filled; `node.modules` with the simple outputs; admin settings (outputs enabled, function, max on) in the admin PIN menu and the serial console, screen texts in pt, en, de and zh-tw; `box_host --simple-out`; host tests; `tools/check_wiring.py` (46 on a V4.3 build, 5 on a V4.2 build, for this pin only); the guides' simple-output section (spare 74AHCT125 gate, 10 kohm, 330 ohm, M8 socket, RC switch from the load side, the switch check) in the Field Box, Satellite and I/O pod guides, en and pt | 1 | M |
| 3 | **Controllers and console** | Pi and phone: CMD 12 for `field.send(..., "output", ...)`, the rate limit, `modules` in the node list (with `feedback`), the capability start check (EXP-21, "not checked" for simple outputs), the GM output API (`POST /api/v1/games/{id}/nodes/{node}/output`, `POST /api/v1/games/{id}/outputs/off`, gm token only; the remote GM's off only); contract cases in `controller_api.json`; the console's output chips and outputs panel in four languages; e2e test with `box_host --simple-out` | 1 (2 for the e2e test) | M |
| 4 | **Modes** | Validators accept a role's `outputs:` (simulator, both controllers); Bomb: optional `smoke_s` and `siren_s` on explosion; Master and Satellites: optional `siren_all_s` when one team holds every satellite (in `field.lua`); simulator drawing outputs; mode tests | 2, 3 | S-M |
| 5 | **Scenario triggers** | `triggers:` in `core/scenario/` (validator, compiler, runtime), `scenario.json` and `scenario_compile.json`, the console's Triggers blocks in four languages | 3 | M |
| 6 | **Port driver (box side, inputs first)** | `firmware/esp32/main/expansion.c/.h` (replaces `target_addon.c/.h`): discovery, ident, polling, events; the reconciliation and lease for output channels behind the output layer of 2; host tests against the vectors and a C model; still not called | 1, 2 | M |
| 7 | **Module core** | Portable C protocol core for modules (I2C target state machine, registers, event queue, lease, limits) with host tests; the C model of 6 replaced by it | 1 | M |
| 8 | **Port integration and the target module** | The driver called from the game task; hits to the script as `hit.hit`; `node.modules` and `node.module_lost` for modules; `box_host --module`; the target module's firmware on pico-sdk (ADC, DMA, peak detection) on the module core, `tools/docker_module.py`, UF2 files from CI and releases; Target Windows a Field Box preset once bench-tested | 6, 7 | L |
| 9 | **I/O pod** | Simple outputs on GPIO 33 (1, 3); the port driver; `hit` and `output` lent over the proxy; the pod holds the lease or the bursts and turns outputs off on link loss; the app's prop shell maps them and handles CMD 12; vectors | 2 (8 for the port) | M |
| 10 | **Port guides** | `hardware/expansion-port/BUILD.md` (the port board: socket, buffer, TVS, fuse, diode) and the target addon guide made buildable, en and pt; `tools/check_wiring.py` for the port's table; the build page (by the coordinator) | 8 (text can start after 1) | M |
| 11 | **I2C output module (later, optional)** | Its firmware on the module core (relays, watchdog, power-up off, hard limits), `hardware/output-module/BUILD.md` with the isolator, the own supply and the mains and smoke warnings, en and pt | 8 | M |
| 12 | **Bench (HW2)** | Section 7's bench list on real boards: tests 11-13 as soon as 2 is built (a bare board and an RC switch are enough; board 5 on GPIO 15), the port's tests after 8 and 10; thresholds and limits tuned; photos | 2; 8, 10 and the parts | -- |

Each increment updates its component's README, the phase's STATUS.md and the
CHANGELOG, and runs the component's tests, as every change does.

## Compatibility

- **Boxes without a port or a simple output, or with nothing plugged in:** no
  change. The driver finds no module, no simple output pin is set (the Kconfig
  default is -1), the box lists no `hit` or `output`.
- **The simple output's pins:** GPIO 46 (V4.3) and 5 (V4.2) are reserved by
  `tools/check_wiring.py` today; the check allows them for the simple output
  only, on the matching board revision. Builds with the buzzer keep GPIO 45 for
  it.
- **Older firmware:** ignores CMD 12 (unknown opcode, logged). Its HELLO lists
  no capability, so the new start check skips it.
- **Older controllers** check events against their schema and would refuse
  the three new ones, so both controllers must know them before a box sends
  them (increments 1 and 3 are released before 2). They ignore unknown role
  keys (`outputs:`).
- **Modes:** `cap("siren")` on a box without one does nothing, so modes can
  call outputs unconditionally.
- **The draft target report of P5J-19** is replaced; nothing was built against
  it. `target_addon.c` and its test went with increment 6, the new driver
  (`firmware/esp32/main/expansion.c`).
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
- **Only the I2C output module for outputs** (this RFC's first version): a
  processor to flash, an isolator, the port's protection, for what is most often
  one siren or one smoke remote. The maintainer chose the simple output as the
  default (EXP-31); the module stays for more channels or feedback.
- **The simple output on LEDC, free-running:** keeps pulsing after a hang, so
  it would hold a relay on (EXP-32).
- **Several channels on one GPIO** by pulse width or PPM: needs a decoder at
  the far end, and one bad pulse switches the wrong load (EXP-35).
- **A bare 3.3 V GPIO straight to the RC switch:** many accept 3.3 V, not all,
  and the cable would reach the ESP32's pin; the spare level-shifter gate costs
  nothing (EXP-33).
- **The GM free to switch outputs remotely without limits:** a remote person
  cannot see who stands next to a smoke machine (EXP-27).

## Open questions

Each with the recommended answer. The question "offer the single-GPIO servo
output where a pin is free, in addition to the I2C port?" was decided by the
maintainer on 2026-11-03 (EXP-31: yes, and it is the preferred output path).
The questions of the first version were checked again against that decision;
where a recommendation changes, it says so.

1. **Add the hot-swap buffer, the TVS and the back-feed diode to every port**
   (about €3-8 more per port)? *Recommended: yes, unchanged.* The port is now
   mainly for inputs, so it is fitted only on boxes that carry a target or a
   sensor, and fewer boxes pay for it; but a target's cable lies on the ground
   in the line of fire, the most exposed cable on the field, and a fault on it
   would still take the keypad and NFC reader down with it. What changes: no box
   needs the port just to switch a siren.
2. **The RP2040 as the reference processor** for the target module (and the
   later output module), over the CH32V003, the ATtiny 2-series and the
   ESP32-C3? *Recommended: yes, unchanged*, with the protocol core in portable
   C so a cheaper processor can follow on a carrier PCB.
3. **An I2C isolator required in every I2C output module** (no shared ground
   with the loads)? *Recommended: yes, but no longer urgent*: the module is a
   later, optional increment (11), so this can be confirmed when it is built.
4. **Addresses 0x58-0x5F, input modules default 0x58, output modules 0x5C, at
   most 4 modules a box?** *Recommended: yes, unchanged.*
5. **Outputs at the end of a game:** all off, with a 10 s grace for the mode's
   end handler and `game: end` triggers (an end horn)? *Recommended: yes*, for
   both paths.
6. **Outputs on pause:** all off, not restored on resume? *Recommended: yes*,
   for both paths: a paused game is often a safety stop.
7. **A remote GM (through the site server) may only switch outputs off?**
   *Recommended: yes, unchanged.*
8. **Enabling outputs only at the box (admin PIN), not from the console,** in
   v1? *Recommended: yes, and more so*: a simple output cannot even tell the box
   what is plugged into it, so the person enabling it has to be there and look.
9. **A port on the field controller (a Pi siren at the safe zone)?**
   *Recommended: not in v1, changed reason*: a Satellite with a simple output
   next to the controller does it with nothing new.
10. **Not supporting bare PCF8574 relay boards on the port** (EXP-15)?
    *Recommended: confirm, unchanged*; the simple output now covers the wish
    for an output with no firmware to flash.
11. **The start check refuses a start when a joined node lacks a role's
    `requires:` capability** (force overrides), for nodes that report their
    capabilities? *Recommended: yes, adjusted*: an enabled simple output counts
    as present, marked "not checked" (EXP-36).
12. **The `output.switched` event on the radio** (a few per game) as the record
    of who fired what? *Recommended: yes, unchanged*, normal priority.
13. **The lease: 1.5 s, refreshed every 500 ms, at most 5 s?** *Recommended:
    yes, unchanged* for the I2C path; the simple output's equivalent is the 0.5 s
    burst (EXP-32) plus the switch's own signal-loss time.
14. **Replace the P5J-19 draft report** with `STATUS` (not compatible)?
    *Recommended: yes, unchanged.*
15. **SELV only (24 V DC, 2 A per channel) in the guides, mains out of scope,
    pyrotechnics never** (EXP-17)? *Recommended: yes*, for both paths.
16. **This as its own RFC** (numbered by the maintainer on acceptance), with
    the CMD opcode as an RFC 0001 amendment and `output` as an amendment of the
    phase 3 draft RFC? *Recommended: yes, unchanged.*
17. **RMT bursts instead of LEDC for the simple output** (the request said
    LEDC)? *Recommended: RMT* (EXP-32): LEDC keeps pulsing in hardware after the
    firmware hangs, which would hold a relay on; RMT with a loop count stops by
    itself unless the game task renews it.
18. **The simple output's pin: GPIO 46 on a V4.3, GPIO 5 on a V4.2** (Field Box
    and Satellite; 33 on the pod), with `check_wiring.py` allowing the other
    revision's front-end pin for it, and GPIO 45 for the buzzer **or** a second
    simple output? *Recommended: yes* (EXP-34). To check at the first build:
    that 46 and 5 are on the V4's header pins as on the V3's.
19. **An M8 3-pin socket for the simple output** (distinct from the port's
    M12)? *Recommended: yes* (EXP-33).
20. **The RC switch powered from the load's supply, with a shared GND and no
    isolation?** *Recommended: yes*, acceptable for SELV loads on their own
    battery (EXP-33).
21. **Generic RC switches allowed only after the box's bench check of their
    signal-loss behaviour** (EXP-37)? *Recommended: yes.*

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
| EXP-16 | I2C output module (later, optional since EXP-31): I2C isolator, own supply, RP2040, off-the-shelf opto-isolated relay board |
| EXP-17 | SELV loads only; mains out of scope; smoke machines only through documented low-voltage inputs; no pyrotechnics |
| EXP-18 | Capability types `hit` (unchanged) and `output` (on, off, pulse, pattern), from either output path; `contact` reserved |
| EXP-19 | Output ids name the function (`siren`, `smoke`, ... else `out.N`; a simple output's set by the admin); calls to missing capabilities do nothing |
| EXP-20 | A capability type id table for HELLO key 6, filled by the box |
| EXP-21 | Events `node.modules`, `node.module_lost`, `output.switched`; modules in the node list; capability start check for nodes that report capabilities |
| EXP-22 | A role's optional `outputs:` list of functions |
| EXP-23 | CMD opcode 12 `output`, handled by the firmware; remote `on` always with a duration |
| EXP-24 | Node scripts: `cap(fn):pulse`, `:on`, `:off`, `:pattern` |
| EXP-25 | Scenario `triggers:` with an `output` action, and console blocks |
| EXP-26 | The I/O pod gets the port and simple outputs (GPIO 33, 1, 3), lends `hit` and `output` over the proxy and holds the lease or the bursts |
| EXP-27 | Who may switch: game logic and the GM on the field; the remote GM off only; never players |
| EXP-28 | Outputs disabled on a box until its admin enables them at the box |
| EXP-29 | Fail-safe table: off at boot, discovery, pause, end (10 s grace), halt; leases (I2C) and stopped bursts (simple output) end the rest |
| EXP-30 | Rate limits: 2 starts/s per channel from scripts, CMD 12 once per 2 s per node (off never held), relays every 100 ms at most, a simple output every 500 ms at most |
| EXP-31 | **Decided by the maintainer (2026-11-03):** two output paths; the single-GPIO RC-servo simple output is the preferred one for sirens, strobes and smoke remotes; the I2C output module is the later, optional path for more channels or feedback; inputs stay on the I2C port (a servo signal carries nothing back) |
| EXP-32 | Simple output signal: 50 Hz, 1.0 ms off, 2.0 ms on; RMT bursts of 25 frames renewed every 200 ms by the game task (not free-running LEDC); 1.0 ms then a low pin at boot, pause, end, halt |
| EXP-33 | Simple output wiring: a spare 74AHCT125 gate to 5 V, 10 kohm pull-down at its input, 330 ohm series; M8 3-pin socket (1 NC, 3 GND, 4 signal); the RC switch powered from the load side; up to 2 m |
| EXP-34 | Pins: `ATALAIA_SIMPLE_OUT_PIN` 46 (V4.3) or 5 (V4.2) on the Field Box and Satellite, 33 (then 1, 3) on the pod, 15 on board 5; 45 for the buzzer or a second simple output |
| EXP-35 | One channel per GPIO, no multiplexing by pulse width; no feedback, no presence check; outputs only |
| EXP-36 | One `output` capability over both paths through a shared output layer; a simple output reported with a no-feedback flag (`g46:servo:siren`, `"feedback": false`), "not checked" in the console and start check; patterns at least 500 ms on and off |
| EXP-37 | Only RC switches that open on signal loss (documented or bench-checked), threshold between 1.0 and 2.0 ms |
| EXP-38 | Increments reordered: protocol first, then the simple output with the shared output layer, controllers, modes, triggers; the port (inputs and the target module) after; the I2C output module last and optional |

