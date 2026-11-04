<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Module core

The module's side of the expansion port: portable C that answers a box over I2C as [protocol/expansion-port.md](../../protocol/expansion-port.md) ("expansion protocol v1") says, for every module that plugs into a box's M12 port. The target module (increment 8 of the draft RFC "The expansion port", on an RP2040 with pico-sdk), the I2C output module (increment 11) and a community module all build their firmware on it, so the register map, the event queue, the lease and the hard limits are written and tested once (decision EXP-15).

**Status:** built and host-tested (increment 7, decisions EXPI7-1 to EXPI7-20). The target module's firmware ([`firmware/target-module/`](../target-module/README.md), increment 8) is built on it, and the box's host tests and host box run it as their simulated modules (`firmware/esp32/test/module_sim.c`); nothing has run on an RP2040 or against a real box yet.

## What it does

| Part | What the core does |
| --- | --- |
| I2C target | Four calls from the module's I2C peripheral: an address match (`mc_i2c_start`, read or write, after a start or a repeated start), a byte received (`mc_i2c_receive`), a byte requested (`mc_i2c_request`), a stop (`mc_i2c_stop`). A register pointer (`0x00`, `0x02`, or `0x01` and a channel) picks what the next read answers; a write that is not a pointer is a `COMMAND`, taken or refused when the stop or the repeated start ends it; an address with no byte (the box's probe) changes nothing |
| `IDENT` | Written from the module's `mc_config_t`: the model, hardware revision, firmware version and unique id the module gives, the classes and channel count from its channels |
| `CHANNEL` | Each channel's descriptor from the same table; a channel the module does not have reads as 0xFF (the box refuses it on its CRC) |
| `STATUS` | Made at the read's address match, so its bytes hold together and the event's age is the read's: the oldest event (sequence, channel, kind, value, age saturating at 65535 ms), `MORE`, `OVERFLOW`, `SUPPLY_OK`, `LEASE_EXPIRED`, `FRESH`, `CMD_ERROR`, the outputs and the armed inputs |
| `COMMAND` | Every op of the protocol; refused, with `CMD_ERROR` and nothing changed, for a bad CRC (over the address byte first), a register it does not take, a wrong length, an unknown op, an argument out of range, an on during the min off, or a relay turned on within 100 ms of turning off |
| Events | `mc_event` queues the module's input events (16 by default, `MC_EVENT_QUEUE_LEN`), each with a sequence number; only an armed channel's events are kept; `ACK` of the shown event's sequence moves on, any other `ACK` changes nothing; disarming drops that channel's held events; a full queue drops the newest and sets `OVERFLOW` until a `STATUS` that carries it is read in full |
| Outputs | `OUTPUT` on, off and patterns, with their durations, run on the module's own clock (`mc_tick`); every output off when the lease runs out while one is on (`LEASE_EXPIRED`, cleared by the next `OUTPUT` or `LEASE`); each channel's max on and min off; patterns at least 100 ms on and off on a relay, 10 ms on a solid-state channel; every output off at power-up (`mc_init`), switched through the module's `set_output` |
| Inputs' tuning | `CONFIG`'s threshold, hold-off and debounce kept per input for the firmware (`mc_config_value`); `LOCATE` for the status LED (`mc_locating`) |

What it leaves to the module's firmware: the I2C peripheral and its address jumpers, the clock, the pins and the sensors (a hit's peak detection, a contact's debounce), the watchdog and the brown-out reset (call `mc_init` again after either: the outputs come back off and `FRESH`), and a `mc_tick` at least every 10 ms (better every 1 ms; a pattern's edges and a lease's end are as late as the tick).

The core is not reentrant: on the RP2040 the I2C callbacks run in its interrupt, so the main loop calls `mc_tick` and `mc_event` with that interrupt masked. It allocates nothing; `mc_module_t` (under 700 bytes) is the whole state.

## Using it from a module's firmware

```cmake
add_subdirectory(${ATALAIA_REPO}/firmware/module-core module-core)
target_link_libraries(my_module PRIVATE atalaia_module_core)
```

```c
#include "module_core.h"

static mc_module_t core;

static void set_output(void *ctx, uint8_t channel, bool on) { gpio_put(relay_pin[channel], on); }

void module_start(uint32_t now_ms)
{
    mc_config_t cfg = {.address = 0x5C + jumpers(), .model = 0x0002, .hw_rev = 1, .fw = {1, 0, 0},
                       .channel_count = 1,
                       .channels = {{.kind = MC_KIND_OUTPUT, .flags = MC_CH_RELAY, .hint = 1,
                                     .max_on_s = 60}}};
    read_unique_id(cfg.uid);
    mc_ops_t ops = {.set_output = set_output};
    mc_init(&core, &cfg, &ops, now_ms); /* every output off */
}
/* In the I2C target's interrupt: mc_i2c_start / _receive / _request / _stop.
 * In the main loop, with that interrupt masked: mc_tick(&core, now_ms), mc_event(...). */
```

## Tests

```sh
cmake -S firmware/module-core -B build/module-core -DCMAKE_BUILD_TYPE=Debug
cmake --build build/module-core
ctest --test-dir build/module-core --output-on-failure
```

`test/test_module_core.c` runs every vector of [protocol/vectors/expansion.json](../../protocol/vectors/expansion.json) against the core, through `test/module_core_vectors.h` (written by `python3 tools/protogen.py`, never by hand): each reference module's `IDENT` and `CHANNEL`s read over the I2C calls; each `STATUS` through the encoder and, for the seven a module can come to, through the protocol itself; each `COMMAND` taken or refused with the file's reason; and each step of the lease's seven timelines, with the pins the module drives. Then the state machine's edges: power-up, bad configurations, pointers and repeated starts, overlong writes, the queue's overflow and wrap, the lease and limits at their exact milliseconds, and a clock that wraps. CI's **Expansion module core host tests** job builds it with warnings as errors (`-Wconversion` included) and again under AddressSanitizer and UBSan; `tools/check.sh` runs it too.
