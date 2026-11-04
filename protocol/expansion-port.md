# The expansion port: protocol v1

What plugs into a box from outside: **inputs** (a target plate's hits now, contacts and other sensors later) and, where a box needs several output channels or wants to know its relays are there, **outputs**. Each module has a small processor of its own that answers the fixed register map below on the box's I2C bus, behind the 5-pin M12 socket of decisions P5J-15 to P5J-21. This file is the specification of the register protocol, "expansion protocol v1", and of the texts, events and command that tell the rest of the field what a box has plugged in (the draft RFC "The expansion port", decisions EXP-7 to EXP-14, EXP-18 to EXP-23 and EXP-36; its open questions Q1 to Q16 were answered with their recommendations on 2026-11-03).

Most outputs take the other, simpler path that the RFC prefers (EXP-31): the **simple output**, one GPIO sending an RC-servo signal to an off-the-shelf RC relay switch. It has no frames, so this file only says how a simple output is reported (section 7); its signal, pins and wiring are still open questions of the RFC (Q17 to Q21) and are specified when they are decided.

**Status:** specified, partly built. The protocol, its vectors and the capability type ids are increment 1 of the RFC's plan; the box's output layer (increment 2) and the module core, the modules' side of this protocol (increment 7, [`firmware/module-core/`](../firmware/module-core/README.md)), are built; the port driver (replacing the stub `firmware/esp32/main/target_addon.c` and its draft report format of P5J-19, which no addon was ever built against) and the modules come in later increments.

Shared vectors: [`vectors/expansion.json`](vectors/expansion.json) (written by `tools/expansion_vectors.py`, from the tables of this file alone): the CRC-8, the IDENT, CHANNEL and STATUS frames a box reads (good ones and the ones it refuses, with the reason), the COMMAND frames it writes (the ones a module takes and the ones it refuses), the lease's timelines, and `node.modules`' text. Checked today by the Python reference (`simulator/atalaia_sim/expansion.py`: `simulator/tests/test_expansion.py`, every case) and by the box's C CRC-8 (`firmware/esp32/test/test_target_addon.c`, every frame, through the generated `firmware/esp32/test/expansion_vectors.h`); the module core (`firmware/module-core/`, increment 7) every IDENT, CHANNEL, STATUS and COMMAND and every step of the timelines (`firmware/module-core/test/test_module_core.c`, through the generated `module_core_vectors.h`); the box's port driver checks the rest when it is built. CMD opcode 12's params are in [`vectors/cmd.json`](vectors/cmd.json) (`output_params`), the capability descriptors and commands in [`vectors/capability_proxy.yaml`](vectors/capability_proxy.yaml), the events in [`vectors/events.yaml`](vectors/events.yaml).

## 1. The bus

| | |
| --- | --- |
| Bus | The box's I2C bus at **100 kHz** (EXP-5, EXP-6), behind a hot-swap buffer with stuck-bus recovery on the box's side (EXP-4) |
| Connector | M12 A-coded 5-pin: 1 brown 3.3 V, 2 white SDA, 3 blue GND, 4 black SCL, 5 grey reserved and not connected (EXP-1) |
| Supply | 3.3 V, at most 25 mA, for a module's logic only; loads never take power from the box (EXP-3) |
| Pull-ups | On the box's side of the buffer; modules carry none |
| Addresses | **0x58-0x5F** (EXP-7). Input modules (the target module) default to **0x58**, output modules to **0x5C**; two solder jumpers on a module add 0 to 3 |
| Modules per box | At most **4** |

The range is clear of every address a box uses or probes: the keypad expander (0x20-0x27, 0x38-0x3F), the PN532 (0x24), the fuel gauge (0x36), the board's OLED (0x3C), and the I2C reserved ranges (0x00-0x07, 0x78-0x7F).

**Polling, no interrupt line** (EXP-8, P5J-18): the box reads an input module's `STATUS` every **20 ms** and an output-only module's every **250 ms**. A module keeps each input event with its age until the box takes it.

## 2. Frames

All multi-byte numbers are **little-endian**. Every frame ends with a **CRC-8**: polynomial 0x07, initial value 0x00, no reflection, no final XOR (CRC-8/SMBUS; `crc("123456789") = 0xF4`).

- **Read.** The box writes the register number (for `CHANNEL`, the register number and the channel index: a "pointer write", no CRC), then a repeated start, and reads the register's length. The CRC covers the bytes read before it.
- **Write.** The box writes the register number, the payload and the CRC in one transaction. The CRC covers **the address byte as sent** (the 7-bit address shifted left, the write bit 0) and then the register number and the payload, so a frame that reaches the wrong module because a bit of the address flipped is refused.

| Register | Name | Access | Length | What |
| --- | --- | --- | --- | --- |
| 0x00 | `IDENT` | read | 16 | Who the module is |
| 0x01 | `CHANNEL` | write the index, read | 8 | One channel's descriptor |
| 0x02 | `STATUS` | read | 9 | The oldest input event and the outputs' state: the one read the box polls |
| 0x10 | `COMMAND` | write | 3-11 after the address byte (register, op, arguments, CRC) | Acknowledge, arm, output, lease, all off, clear fresh, locate, configure |

A write to 0x00 or 0x02 longer than the register byte, a write to 0x01 longer than the register and the index, and a write to any other register is refused (reason `register`).

### IDENT (0x00, 16 bytes)

| Byte | Field | Notes |
| --- | --- | --- |
| 0-1 | magic | `0x41 0x58` ("AX") |
| 2 | protocol version | 1 |
| 3 | classes | bit 0: has inputs; bit 1: has outputs; bits 2-7 reserved (0, ignored) |
| 4 | channel count | 1-8 |
| 5-6 | model | 0x0001 target module (`target`), 0x0002 4-channel output module (`out4`); 0x0003-0x7FFF for the project's later models; **0x8000-0xFFFF for community models**, listed in the table below |
| 7 | hardware revision | |
| 8-10 | firmware version | major, minor, patch |
| 11-14 | unique id | from the processor's own unique id, so the console tells two modules apart |
| 15 | CRC-8 | of bytes 0-14 |

A box refuses an IDENT (and does not add the module) when it is not 16 bytes (`length`), its CRC fails (`crc`), the magic is wrong (`magic`), the version is not 1 (`version`), it has neither class (`classes`), or the channel count is not 1-8 (`channels`). Such a module is retried at the next probe of its address.

**Model names.** `node.modules` and the controllers name a model `target`, `out4`, or, for any other model, `m` and its four lower-case hex digits (`m8001`). Community models (a builder's own module that speaks this protocol) take an id from 0x8000 by a pull request adding a row here:

| Model | Name | Module | By |
| --- | --- | --- | --- |
| 0x0001 | `target` | The target module (the target addon): a piezo plate, one `hit` channel | The project |
| 0x0002 | `out4` | The 4-channel I2C output module (later, optional: EXP-31) | The project |

### CHANNEL (0x01, 8 bytes)

The box writes `0x01, index`, then reads:

| Byte | Field | Notes |
| --- | --- | --- |
| 0 | index | 0-7, the one asked for |
| 1 | kind | 0x01 hit (strength 0-255); 0x02 contact (closed / opened; reserved for its first module); 0x10 switched output |
| 2 | flags | bit 0: relay contacts (switching no faster than every 100 ms); bit 1: solid-state (faster patterns allowed); bit 2: the module senses its load supply; bits 3-7 reserved |
| 3 | hint | what the builder fitted: 0 generic, 1 siren, 2 strobe, 3 smoke, 4 light, 5 horn; a value above 5 counts as generic |
| 4 | max on | outputs: the module's own hard limit in seconds, 1-255; inputs: 0 |
| 5 | min off | outputs: the least seconds off after the max on was reached, 0-255 |
| 6 | reserved | 0 |
| 7 | CRC-8 | of bytes 0-6 |

A box refuses a descriptor that is not 8 bytes (`length`), fails its CRC (`crc`), answers for another index or an index above 7 (`index`), has a kind it does not use (`kind`: a v1 box uses hit and switched output; contact waits for its own RFC amendment), or is an output with a max on of 0 (`max_on`). A refused channel is not used; the module's other channels are.

### STATUS (0x02, 9 bytes): the box's only regular read

| Byte | Field | Notes |
| --- | --- | --- |
| 0 | flags | bit 0 `EVENT` (bytes 1-5 hold one); bit 1 `MORE` (more wait behind it); bit 2 `OVERFLOW` (events were dropped since the last report); bit 3 `SUPPLY_OK` (the load supply is present, when sensed); bit 4 `LEASE_EXPIRED` (outputs were turned off because the lease ran out); bit 5 `FRESH` (the module started and has not been told `CLEAR_FRESH`); bit 6 `CMD_ERROR` (the last write was refused); bit 7 reserved |
| 1 | event sequence | counts the module's events, wrapping |
| 2 | event channel and kind | bits 0-2 the channel; bits 4-7 the kind: 1 hit, 2 closed, 3 opened |
| 3 | event value | a hit's strength 0-255; 0 for contacts |
| 4-5 | event age | milliseconds from the event to this read, saturating at 65535 |
| 6 | outputs | bit n: channel n's output is on now |
| 7 | armed | bit n: channel n's input is armed |
| 8 | CRC-8 | of bytes 0-7 |

Bytes 1-5 mean nothing without `EVENT`. A box refuses a STATUS that is not 9 bytes (`length`), fails its CRC (`crc`), or has `EVENT` with a channel the module does not have (`channel`) or a kind other than 1-3 (`event_kind`); it reads again at the next poll. The box times an event on its own game clock: **`t_event = t_read - age`** (EXP-10), so no clock sync is needed.

`LEASE_EXPIRED` stays set until the next accepted `OUTPUT` or `LEASE`; `FRESH` until `CLEAR_FRESH`; `CMD_ERROR` until the next accepted write.

### COMMAND (0x10)

The box writes `0x10`, the op, its arguments and the CRC (over the address byte first):

| Op | Name | Arguments (bytes) | Effect |
| --- | --- | --- | --- |
| 0x01 | `ACK` | seq (1) | The box took that event; the module shows the next |
| 0x02 | `ARM` | bitmap (1) | Inputs armed exactly as the bitmap says (a set, not a toggle); disarming drops held events of those channels |
| 0x03 | `OUTPUT` | channel (1), mode (1), duration (u16, 100 ms units, 0 = until `off` or the lease), on time (u16, 10 ms units), off time (u16, 10 ms units) | mode 0 off, 1 on, 2 pattern (on time, off time, repeated, starting with on). Refreshes the lease |
| 0x04 | `LEASE` | lease (1: 100 ms units, 5-50) | Sets and refreshes the lease of every output |
| 0x05 | `ALL_OFF` | none | Every output off now |
| 0x06 | `CLEAR_FRESH` | none | The box has seen the module's restart |
| 0x07 | `LOCATE` | seconds (1) | The module's own status LED blinks, to find it on the field (0 stops it) |
| 0x08 | `CONFIG` | channel (1), parameter (1), value (u16) | Input tuning: parameter 1 threshold, 2 hold-off in ms (a ringing steel plate), 3 debounce in ms |

So a write is 3 bytes after the address byte (`ALL_OFF`, `CLEAR_FRESH`), 4 (`ACK`, `ARM`, `LEASE`, `LOCATE`), 7 (`CONFIG`) or 11 (`OUTPUT`). The RFC's table said "4-11"; it counted the ops with arguments only.

A module **refuses** a write, sets `CMD_ERROR` and changes nothing when: its CRC fails, the address byte included (`crc`); the register is not one it takes (`register`); the op is missing or the length is not the op's (`length`); the op is unknown (`op`); or an argument is out of range (`range`): `ARM` or `CONFIG` naming a channel that is not an input, `CONFIG` with a parameter other than 1-3, `OUTPUT` on a channel that is not an output or with a mode above 2, a pattern with an on or off time under the channel's floor (**10, i.e. 100 ms, on a relay channel; 1, i.e. 10 ms, on a solid-state one**), or a `LEASE` outside 5-50. It also refuses, at that moment, an `OUTPUT` on or pattern during the channel's min off time, and on a relay channel one less than 100 ms after the channel last turned off (an `off` is never refused). The box's reconciliation (EXP-12) sends a refused write again at a later poll.

## 3. Inputs

Inputs are filtered **in the module** (EXP-10): a hit is the peak of the piezo's signal over a short window, scaled to 0-255, with a hold-off after it and a threshold, both set with `CONFIG`. The module queues at least 16 events and shows the oldest in `STATUS` until the box acknowledges its sequence number with `ACK`; a report lost on the cable is read again, and a lost `ACK` only makes the box see the same sequence number again (it acknowledges it once more and reports nothing). A box reads up to 4 `STATUS` in one poll while `MORE` is set. Events of a disarmed channel are acknowledged and dropped. To a script a hit is `hit.hit` with `strength` (draft RFC 0000 Amendment 1); a box with more than one hit channel adds `channel` (1 for `hit`, 2 for `hit.2`, ...) to the event's data (Amendment 5).

## 4. Outputs and the lease

**Every output is leased** (EXP-11). A module keeps an output on only while the box keeps writing to it: an `OUTPUT` or `LEASE` at least once per lease. The box refreshes every **500 ms** with a lease of **1.5 s** (`LEASE 15`, three chances before the module gives up); a module refuses leases under 0.5 s or over 5 s, and starts with 1.5 s. When the lease runs out while an output is on, the module turns **every** output off and sets `LEASE_EXPIRED`. Whatever stops the box (a crash, a brown-out, a reboot, the I2C driver suspending the module for 30 s, a cut cable, the game task held up), the output is off within 1.5 s.

**The module's own timers.** A duration, a pattern and the max on run on the module's clock, so an output ends on time between polls and even when the box has stopped. When a duration or a max on ends at the same moment as the lease, the output has ended by its duration (no `LEASE_EXPIRED`).

**Desired state, reconciled** (EXP-12, the box's side, built in a later increment): the box holds what each output should be and compares it with the `outputs` bitmap of each `STATUS`; when they differ it sends the command again with what is left of the duration, rounded up to 100 ms. A module that restarted (`FRESH`) gets `CLEAR_FRESH` and its state again, or `ALL_OFF` if the game is not running.

**Hard limits at three levels** (EXP-13), the lowest winning: the module's (`max on` and `min off` per channel, relays no faster than every 100 ms, outputs off at power-up, after its watchdog and on brown-out), the box's (outputs enabled by its admin, a function and a max on per channel never above the module's, the game-state rules), and the call's (its duration; remote commands always carry one).

| Timeline in the vectors | What it fixes |
| --- | --- |
| `lease_runs_out` | refreshes stop: off 1.5 s after the last one, `LEASE_EXPIRED` until the box writes again |
| `lost_write_repaired` | a lost `OUTPUT` is sent again at the next poll with what is left |
| `module_restart` | a module that restarts comes back off and `FRESH`; the box clears it and sends the rest |
| `pulse_spanning_missed_polls` | a pulse ends on the module's timer though polls and a refresh were missed |
| `max_on_and_min_off` | the module's max on ends an output that is still leased, and min off refuses it until it has passed |
| `relay_pattern_floor` | a 50 ms pattern is refused on a relay and runs on a solid-state channel; a relay takes 100 ms |
| `relay_switches_at_most_every_100_ms` | a relay turned off refuses to turn on again within 100 ms; off is never refused |

## 5. Errors and hot-plug

(EXP-14.) A refused `STATUS` is read again at the next poll; a refused write shows as `CMD_ERROR` and is sent again by the reconciliation. A module that fails **25 reads in a row** (0.5 s for an input module, 6 s for an output-only one) is **gone**: its capabilities leave the box's list, the controller is told (`node.modules`, and `node.module_lost` during a running game), and its outputs count as off (its lease has long run out). Every **2 s** the box probes one empty address of 0x58-0x5F with a one-byte address write; a module that answers is read (`IDENT`, every `CHANNEL`), sent `ALL_OFF` and `CLEAR_FRESH`, and added. The box sends `ALL_OFF` to every module it finds at boot, before anything else. The bus's health records (`firmware/esp32/main/i2c_health.h`: a device suspended after 3 failures, with a back-off up to 30 s) apply to modules too; a suspended module's skipped polls count as failed reads.

## 6. Capabilities

A box offers what its modules and simple outputs carry as capabilities of the standard types (design specification section 7; ids in [`schema/capabilities.yaml`](schema/capabilities.yaml), which HELLO's key 6 lists: `hit` is 10, `output` is 11):

| Type | Events | Commands (script / capability proxy) | From |
| --- | --- | --- | --- |
| `hit` | `hit` `{"strength": 0-255}`, plus `"channel"` on a box with more than one | `arm`, `disarm` | A channel of kind hit |
| `output` | none | `on` `{"ms"}` (at most that long), `off`, `pulse` `{"ms"}`, `pattern` `{"on_ms", "off_ms", "ms"}` | A channel of kind switched output, or a simple output |

**Capability ids** (EXP-19): an output's id is its function, `siren`, `strobe`, `smoke`, `light` or `horn` (the channel's hint unless the box's admin sets another), else `out.<n>` with n the channel number from 1; a second channel with the same function is `siren.2`. A hit channel is `hit`, then `hit.2`. Ids are 1-23 bytes of `a-z 0-9 . _ -`. A script's call to a capability the box does not have does nothing.

**Feedback** (EXP-36): a simple output cannot tell whether anything is plugged in. Its capability descriptor says `"feedback": false` (left out, meaning true, for a module's channel), the controllers' node list gives it `"feedback": false`, the console marks it "not checked", and it never raises `node.module_lost`. A pattern on a simple output has on and off times of at least 500 ms.

## 7. What the field learns: `node.modules`, `node.module_lost`, `output.switched`

Three standard events ([`schema/events.yaml`](schema/events.yaml), ids 57-59; data keys 42-45):

| Event | Priority | Data | When |
| --- | --- | --- | --- |
| `node.modules` | normal | `modules`: the compact text below | After the box's HELLO is acknowledged, whenever a module comes or goes, and when its admin changes a simple output's settings |
| `node.module_lost` | critical | `modules` (the module that went, in the same text), `reason` (`no_answer`, `bad_ident`) | A module the box had during a running game stops answering |
| `output.switched` | normal | `capability` (the function), `ms` (how long; 0 = turned off), `source` (`script`, `field`, `gm`, `box_admin`) | Each time an output turns on, and when one is turned off before its time: the game's record of who fired what |

**The compact text** is at most **100 bytes**: entries joined by `;` (none: the empty text), each either

- a module: `<address>:<model>/<version>:<capability ids joined by ,>`, the address as two lower-case hex digits `58`-`5f`, the model name of section 2, the firmware version `major.minor.patch`; for example `5c:out4/1.0.0:strobe,smoke,out.3,out.4`;
- or a simple output: `g<gpio>:servo:<function>`, the GPIO 0-48, exactly one function and no version; for example `g46:servo:siren`.

An address appears once. The controllers turn it into the node list's `modules`, a list of `{"address", "model", "fw", "caps", "feedback"}` (`fw` null and `feedback` false for a simple output), served the same by both controllers (contract cases in `controller_api.json` come with the controllers' increment).

## 8. Switching an output from the field: CMD opcode 12

[RFC 0001 Amendment 26](../docs/rfcs/0001-skirmesh-rf-wire-format.md) (EXP-23). `params`:

| Key | Value |
| --- | --- |
| `capability` | the function: `siren`, `smoke`, `out.2`, ...; or `*` with `act` `off` (every output of the box) |
| `act` | `on`, `off`, `pulse`, `pattern` |
| `ms` | required for `on`, `pulse` and `pattern`: 1 to 600000; the box also caps it at the channel's max on |
| `on_ms`, `off_ms` | required for `pattern`: 10 to 10000 (a box raises the floor to 100 on a relay channel and to 500 on a simple output) |
| `src` | `field` or `gm`, set by the controller, never by a client |

Unknown keys are ignored. The box's firmware handles it (not the mode script), whatever mode or scenario it runs; an `on` without `ms` is refused, so a box that loses the controller keeps an output on for that time at most. The controller sends it to a node at most once per 2 s (`off` is never held back). Over Wi-Fi it is a `cmd` message with `cmd: "output"` and `opcode: 12` ([prop-link.md](prop-link.md)). A box from before the amendment logs the opcode as unknown and ignores it. As for every CMD, the compact JSON form stays within the 127 bytes a box takes (a 20 s pattern of `strobe` to one box: 118 bytes); a controller refuses to send a longer one.

## 9. Safety

Off is the safe state everywhere (EXP-29): relays normally open, modules off at power-up, after their watchdog and on brown-out, `ALL_OFF` at boot and discovery, every output off when a game pauses, ends (after a 10 s grace for an end-of-game horn) or its script is halted. Outputs are disabled on a box until its admin enables them at the box (EXP-28); a remote GM may only switch outputs off, players never (EXP-27). Loads are SELV only (24 V DC, 2 A per channel in the guides), mains is out of scope, smoke machines only through a documented low-voltage input, never pyrotechnics (EXP-17).
