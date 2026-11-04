<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# I2C output module

The later, optional output path on a box's expansion port (draft RFC "The expansion port", section 3 (b), EXP-16,
EXP-17, EXP-31): an RP2040 board behind an **I2C isolator** switches up to four relays or MOSFETs from **a supply of
its own** (9-15 V DC, a fuse, reverse-polarity protection, a 5 V buck converter), so the box and the loads never share
a ground. Dry contacts for sirens, strobes, horns and a smoke machine's **documented low-voltage remote input**;
**SELV only (at most 24 V DC, 2 A per channel), never mains**. Address 0x5C (jumpers 0x5D-0x5F), model `out4`. For one
or two loads the simple output (one GPIO and an RC relay switch) stays the preferred path.

[BUILD.md](BUILD.md) ([pt](BUILD.pt.md)): the two sides of the isolator, the module's own supply, relay or
solid-state, loads with their fuses and flyback diodes, the pin table (checked against the firmware by
`tools/check_wiring.py`), assembly, meter checks, flashing, first power-up and what waits for the bench. The firmware is
[firmware/output-module/](../../firmware/output-module/README.md).

Status: designed, not yet built; the firmware is host-tested and builds its UF2 in CI, but has never run on a board.
