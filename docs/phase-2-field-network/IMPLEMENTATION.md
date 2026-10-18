<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 2 -- Field Network: Implementation Notes

## Wokwi Radio Init Bisection (Phase C)

**Root cause:** The original `sx_wait_busy()` helper looped
indefinitely while the BUSY pin was high.  On the Wokwi DevKitC-1
emulator, GPIO 13 (BUSY) floats and can read as permanently high,
hanging the radio init and starving LittleFS of CPU time.  The
hang caused the symptoms originally attributed to "SPI3 corrupting
flash": the LittleFS mount timeout was reached, the format did not
complete, and the preset store read returned garbage.

**Bisection evidence (2026-10-18):**

| Step | What it adds | Scenario result |
|------|-------------|-----------------|
| 1 | `spi_bus_initialize(SPI3_HOST)` only | Pass |
| 2 | + `spi_bus_add_device` | Pass |
| 3 | + GPIO config for RST, BUSY, DIO1 (no ISR) | Pass |
| 4 | + DIO1 ISR install | Pass |
| 5 | + Reset pulse + BUSY wait (with timeout) | Pass |
| 6 | + First SPI transaction (SyncWord probe) | Pass |
| 0 | Full init (all steps, no debug stop) | Pass |

All six steps pass individually and the full init (step 0) passes
after the fix.  The `CONFIG_ATALAIA_RADIO_DEBUG_STEP` Kconfig
option remains available for future bisection.

**Fix (applied):**

1. `sx_wait_busy()` now has a 200-iteration timeout instead of an
   infinite loop.
2. The step-5 BUSY wait also has a 100-iteration timeout.
3. `CONFIG_ATALAIA_RADIO_DISABLE` is no longer set in
   `sdkconfig.wokwi`.  The radio init runs, correctly logs
   "SX1262 not detected (sync_hi=0x00)", cleans up, and the game
   continues.

**Test coverage for the radio layer:**

- 10 radio protocol tests (`test_radio_protocol.c`): boot epoch,
  first boot, NVS write failure, seq wrap epoch increment, seq wrap
  NVS failure, epoch exhaustion, receiver epoch trial (known source,
  reboot, lower epoch rejection, unknown source).
- 6 TX power tests (`test_radio_power.c`): g-band default, g2-band
  default, no FEM, high-gain antenna, clamp low, clamp high.
- 4 radio HAL stub tests (`test_radio_stub.c`): send, recv,
  duty-cycle, channel set.
- All tests run on Linux with the stub HAL and test-stub crypto
  backend (XOR + FNV-1a, from `packet.c`).

## Single Shared Game Channel (Amendment 1, 2026-10-18)

The original design (ADR-P2-13, RFC 0001 section 8) specified
three-channel round-robin hopping on the g-band.  This was
incompatible with single-radio half-duplex operation: after TX on
channel N, the SX1262 listens on channel N, so nodes that last
transmitted on different channels miss each other.

Amendment 1 of RFC 0001 replaces the hopping with a single shared
game channel, by default 869.525 MHz (g2 sub-band, 10% duty cycle,
500 mW ERP).  All traffic uses the same channel.  The channel is
configurable per game via the CONFIG message and validated against
the EU868 sub-band table.

See `docs/rfcs/0001-skirmesh-rf-wire-format.md` Amendment 1 for
the full rationale.
