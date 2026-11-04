<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# I2C output module firmware

The firmware of the **I2C output module** (model `0x0002`, `out4`): an RP2040 board behind an I2C isolator on a box's expansion port, switching up to 4 relays or MOSFETs from the module's own supply (draft RFC "The expansion port", section 3 (b), increment 11; decisions EXP-16, EXP-17, EXP-13 and EXPI11-1 onwards). The protocol, the lease and the module's hard limits are the [module core](../module-core/README.md)'s; this folder adds what an output module needs around it. How to build the module itself: [hardware/output-module/BUILD.md](../../hardware/output-module/BUILD.md).

**Status:** written and host-tested; its UF2 file builds on pico-sdk 2.2.0 with no warnings, in CI's target and output modules job and in a release (`atalaia-output-module-<version>.uf2`, the default channel list), but it has **never run on a board**. The simple output (one GPIO and an RC relay switch) stays the preferred way to switch a siren, a strobe or a smoke remote (EXP-31); this module is the later, optional path for more channels or for `SUPPLY_OK`.

## What it does

| Part | Where | What |
| --- | --- | --- |
| Channel list | `src/output.c` | 1 to 4 output channels, set at build time (`OUTPUT_CHANNELS`, below); refused at build time by CMake and again at power-up |
| Address | `src/output.c`, `src/main.c` | 0x5C, plus two solder jumpers on GP2 and GP3 (closed to GND: +1 and +2): 0x5C-0x5F (EXP-7), read once at power-up |
| Protocol, lease, limits | the module core | `IDENT`, `CHANNEL`, `STATUS`, every `COMMAND`; every output off 1.5 s after the box stops writing (`LEASE_EXPIRED`); each channel's max on and min off; relays no faster than every 100 ms, patterns at least 100 ms on a relay and 10 ms on a solid-state channel |
| Power-up off | `src/main.c`, `src/output.c`, the module core | The four channel pins driven low first thing in `main`, then by the guard, then by the core's `mc_init`; the same after a watchdog restart or a brown-out reset |
| The guard | `src/output.c` | A second, independent max on under the core's: every level goes through it; a channel on for longer than its max on plus 500 ms (which the core never allows) turns every channel off, latched until the module restarts |
| Watchdog | `src/output.c` (policy), `src/main.c` | The RP2040's hardware watchdog at 500 ms, fed only while the main loop runs the core's timers on time (at most 50 ms late) and the guard has not tripped; a restart comes up with every output off and `FRESH` |
| Supply sense | `src/output.c`, `src/main.c` | Optional: a 100 kohm / 22 kohm divider from the sensed supply into ADC0 (GP26), filtered, `SUPPLY_OK` from 9.0 V up and lost below 8.5 V; only channels marked `sense` set the senses-supply flag, so a module without the divider never claims `SUPPLY_OK` |
| I2C target | `src/output.c`, `src/main.c` | i2c0 on GP4 (SDA) and GP5 (SCL), 100 kHz, pico-sdk's `i2c_slave`; its events turned into the core's four calls in the I2C interrupt |
| Status LED | `src/output.c`, `src/main.c` | GP14 (and a Pico's own LED): blinking every 250 ms while `LOCATE` asks, every 100 ms for a fault (a refused channel list, a tripped guard), off otherwise |

The pins are in [`src/board.h`](src/board.h); the build guide's pin table must say the same, and `python3 tools/check_wiring.py` fails when it does not.

## The channel list

What is fitted on each channel, chosen by the builder at build time (EXP-13: the module's own limits are "its firmware's build settings"). One entry per channel, from channel 0 (GP6) to channel 3 (GP9), joined by `,`, no spaces:

```
type:hint:max_on:min_off[:sense]
```

| Field | Values | Meaning |
| --- | --- | --- |
| `type` | `relay` or `solid` | `relay`: relay contacts, switching no faster than every 100 ms, patterns from 100 ms. `solid`: a MOSFET, patterns from 10 ms |
| `hint` | `generic`, `siren`, `strobe`, `smoke`, `light`, `horn` | What is fitted; the box and the console show it, and a mode's script can call it by name |
| `max_on` | 1-255 | The module's own hard limit in seconds: the longest the channel stays on in one go, whatever the box asks |
| `min_off` | 0-255 | Seconds the channel refuses to come on again after reaching its max on (a smoke machine's heater, a siren's duty cycle) |
| `sense` | (optional) | This channel's loads run from the supply the divider measures: the module then reports `SUPPLY_OK` |

The default, when the builder sets none: `relay:generic:30:0,relay:generic:30:0,relay:generic:30:0,relay:generic:30:0` (four relays, 30 s at most, the box's own default max on). A builder sets the module's limits for what is fitted from the device's manual; the box's admin can only lower them (EXP-13). For example, a siren, a strobe and a smoke machine's low-voltage remote with a 30 s on, 30 s off duty cycle:

```sh
cmake -S firmware/output-module -B build/output-module \
  -DOUTPUT_CHANNELS="relay:siren:60:0,relay:strobe:120:0,relay:smoke:30:30:sense"
```

## Building

The UF2 file needs pico-sdk 2.2.0 and GCC for Arm, as the target module's (increment 8). `python3 tools/docker_module.py build` builds it in Docker with the default channel list, into `firmware/output-module/build/atalaia_output_module.uf2` (with the target module's), as CI and a release do. With a channel list of your own, in that tool's image (or with a local pico-sdk):

```sh
PICO_SDK_PATH=/opt/pico-sdk cmake -S firmware/output-module -B build/output-module -G Ninja \
  -DOUTPUT_CHANNELS="relay:siren:60:0,relay:strobe:120:0,relay:smoke:30:30:sense"
cmake --build build/output-module   # -> build/output-module/atalaia_output_module.uf2
```

To flash it: hold the board's BOOTSEL button, plug it into a computer's USB, and copy the UF2 file to the drive that appears. **With the module's own supply off and its M12 cable unplugged**: an RP2040-Zero joins its USB 5 V straight to its 5 V pin, so a computer and the module's buck converter would feed each other.

## Tests

```sh
cmake -S firmware/output-module -B build/output-module-host -DOUTPUT_MODULE_HOST_TESTS=ON
cmake --build build/output-module-host
ctest --test-dir build/output-module-host --output-on-failure
```

`test/test_output_module.c` (277 checks) runs the portable part with the module core under it: the channel list (every field, 25 refused lists), the configuration and its addresses, the `out4` reference module of [protocol/vectors/expansion.json](../../protocol/vectors/expansion.json) read back byte for byte over the I2C events, the I2C events with and without a reported repeated start and the box's empty probe, the guard (its limit to the millisecond, a pattern, a clock that wraps, a core that keeps a channel on too long), the watchdog's policy, the supply sense (the divider's scale, the filter, the hysteresis, `SUPPLY_OK` only on a sensing channel), the LED, and the whole module through power-up, the lease running out, the max on and min off, and a restart. CI's **Expansion output module host tests** job builds them with warnings as errors (`-Wconversion` included) and again under AddressSanitizer and UBSan; the **Target and output modules** job runs them again in the pico-sdk image (`tools/docker_module.py test`) before building the UF2 files; `tools/check.sh` runs them too.

The pins are the target module's where both have the part (I2C0 on GP4/GP5, the address jumpers on GP2/GP3, the LED on GP14); the channels take GP6-GP9, the supply sense ADC0 (GP26). Unlike the target module, which lives on the port's 25 mA, this one keeps the RP2040's default clock (it runs from its own supply), and its watchdog is 500 ms rather than 1 s, well inside the 1.5 s lease, because a hung main loop with a live I2C interrupt could otherwise keep a relay on through the box's refreshes.
