<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Target module firmware

The firmware of the target module (the target addon): an RP2040 board behind a plate that players shoot at, plugged into a box's M12 expansion port. It feels each hit through a piezo disc, finds its peak and strength, and answers the box over I2C with the expansion protocol v1 ([protocol/expansion-port.md](../../protocol/expansion-port.md)), through the portable [module core](../module-core/README.md). Increment 8 of the draft RFC "The expansion port" ([docs/rfcs/0000-expansion-port.md](../../docs/rfcs/0000-expansion-port.md), section 3 (a)); the build guide is [hardware/target-addon/BUILD.md](../../hardware/target-addon/BUILD.md).

**Status:** built, and its portable parts tested on a computer (decisions EXPI8-8 to EXPI8-13). **Not yet run on an RP2040**, nor against a real box: its current, the strength scale, the threshold and the hold-off wait for the bench (the RFC's bench tests 4 and 8, HW2).

## What it does

| Part | What | Where |
| --- | --- | --- |
| Protocol | Model 0x0001 `target`, firmware 1.0.0, hardware revision 1, one hit channel (two with `TARGET_PLATES=2`); `IDENT`, `CHANNEL`, `STATUS`, every `COMMAND`, the 16-event queue: the module core's | `../module-core/` |
| I2C target | i2c0 at 100 kHz on GP4 (SDA) and GP5 (SCL), the RP2040's pull-ups off (the box's port board has them); pico-sdk's `pico_i2c_slave` events (a byte received, a byte requested, a stop or a repeated start) turned into the core's four calls in the I2C interrupt | `src/target.c`, `src/main.c` |
| Address | 0x58, plus the jumpers on GP2 (+1) and GP3 (+2) closed to GND: 0x58-0x5B; read once at power-up | `src/main.c` |
| Sampling | ADC0 on GP26 (a second plate on GP27, ADC1, round robin) at 20 ksample/s per plate, by DMA into two buffers of 128 samples per plate in turn (6.4 ms each) | `src/main.c` |
| Hits | A sample above the threshold starts a hit; its peak is the highest sample in the next 2 ms; its strength the peak scaled from the threshold (1) to full scale (255); a hold-off follows (50 ms by default), which lasts while the plate rings (until 5 ms under the threshold); each hit is queued with its time, so the box reads its age. The box's `CONFIG` sets the threshold (parameter 1, ADC counts of 4095, default 300) and the hold-off (parameter 2, ms) | `src/peak.c` |
| `LOCATE` | An LED on GP14 (through 1 kohm to GND; a Pico's own LED on GP25 too) blinks, 250 ms on and off, for the seconds the box asks; off otherwise, and at power-up | `src/target.c` |
| Power | The system clock at 48 MHz, no USB or UART stdio, the CPU asleep between interrupts, to stay within the port's 25 mA (to be measured) | `src/main.c` |
| Watchdog | 1 s: a hung loop restarts the module, which comes up `FRESH` with nothing armed, as at power-up; the box reads it again | `src/main.c` |

The core is not reentrant: the main loop calls `mc_tick`, `mc_event` and `mc_config_value` with the I2C interrupt masked.

## Pins

| RP2040 pin | What |
| --- | --- |
| 3V3 | Supply from the port (about 3.0 V), through the module's reverse-polarity MOSFET. A Pico: 3V3_EN tied to GND |
| GND | Ground (M12 pin 3) |
| GP4 / GP5 | I2C0 SDA / SCL, the I2C target (M12 pins 2 and 4) |
| GP26 | ADC0, the piezo's front end |
| GP27 | ADC1, the second plate (`TARGET_PLATES=2`) |
| GP2 / GP3 | Address jumpers to GND (+1 / +2) |
| GP14 | `LOCATE` LED |

The same GPIO numbers on an RP2040-Zero and on a Raspberry Pi Pico (decision EXPI8-9).

## Build

In Docker (Ubuntu 24.04 pinned by digest, GCC for Arm, pico-sdk 2.2.0 and picotool 2.2.0 pinned by commit: [tools/dev/module/Dockerfile](../../tools/dev/module/Dockerfile)):

```sh
python3 tools/docker_module.py build   # firmware/target-module/build/atalaia_target_module.uf2 (and _2: two plates)
python3 tools/docker_module.py test    # the host tests below, and the module core's
```

Without Docker, with pico-sdk 2.2.0 and picotool installed:

```sh
PICO_SDK_PATH=/path/to/pico-sdk cmake -S firmware/target-module -B build/target-module
cmake --build build/target-module
```

CI builds the UF2 files in every pull request that touches `firmware/target-module/` or `firmware/module-core/` (job **Target module**), and a release publishes them as `atalaia-target-module-<version>.uf2` and `atalaia-target-module-2-<version>.uf2`, covered by `SHA256SUMS`. They are not signed: a module is flashed over USB by hand, never updated over the air.

## Flash

The module unplugged from the box. Hold the board's BOOT (BOOTSEL) button, plug its USB cable into a computer, release the button, and copy the UF2 file onto the drive that appears (`RPI-RP2`); the board restarts into the firmware. **Never connect the USB cable and the port cable at the same time.** The module then reports firmware 1.0.0 in its `IDENT` (`58:target/1.0.0:hit` in the box's `node.modules`).

## Tests

`test/test_target_module.c`, on the host (`-DTARGET_MODULE_HOST_TESTS=ON`): the peak detector on made-up plates (one strike, a long ring, two strikes inside and outside the hold-off, the box's `CONFIG`, the strength scale, a block's split), the configuration and the address jumpers, and the I2C target's events driving the module core as a box does (the probe, `IDENT` with and without a reported repeated start, `CLEAR_FRESH`, `ARM`, a hit in `STATUS` with its age, `ACK`, a bad CRC, `CONFIG`, `LOCATE` and the LED, another module's address). The box's side runs the same module core in its host tests and its host box (`firmware/esp32/test/module_sim.c`, `box_host --module target`).
