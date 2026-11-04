# Hardware

Reference builds made from off-the-shelf parts, with no custom PCB required. A carrier PCB will follow later.

| Build | Purpose | Approx. cost | Build guide |
| --- | --- | --- | --- |
| [Field Box](field-box/) | Main prop: domination, bomb, codes, tags | €70–110 | [BUILD.md](field-box/BUILD.md) ([pt](field-box/BUILD.pt.md)), with wiring diagrams |
| [Satellite](satellite/) | Small secondary point or beacon | €30–40 | [BUILD.md](satellite/BUILD.md) ([pt](satellite/BUILD.pt.md)): the Field Box's firmware with fewer parts |
| [I/O pod](io-pod/) | Gives an Android prop LoRa, big buttons, LEDs and sound | about €35 | [BUILD.md](io-pod/BUILD.md) ([pt](io-pod/BUILD.pt.md)): the Field Box's parts without the screen, the pod firmware |
| [Target addon](target-addon/) | Hit-scoring target for any box | €10–15 plus the plate and cable | [BUILD.md](target-addon/BUILD.md) ([pt](target-addon/BUILD.pt.md)): an RP2040 board and a piezo on the expansion port, at address 0x58; the hardware and its firmware (a UF2 file) can be built, and the box reads it (draft RFC "The expansion port", increment 8); not yet tried on hardware |
| [Expansion port](expansion-port/) | The M12 socket and port board (hot-swap buffer, TVS, fuse, diode) that modules plug into, on a Field Box, Satellite or I/O pod | €6–14 | [BUILD.md](expansion-port/BUILD.md) ([pt](expansion-port/BUILD.pt.md)): parts and what each protects against, the pin table checked against the firmware, assembly and tests |
| [I2C output module](output-module/) | Later, optional: up to 4 relays or MOSFETs on the expansion port, behind an I2C isolator, from a supply of its own (sirens, strobes, a smoke machine's low-voltage remote; SELV only, never mains) | €25–35 plus the supply and loads | [BUILD.md](output-module/BUILD.md) ([pt](output-module/BUILD.pt.md)): the isolator, the own supply, relay or solid-state, flyback diodes and fuses, the pin table checked against the firmware; firmware host-tested, never run on a board |

Costs are approximate hobby-market prices, not quotes. No box of any kind has been built from these guides yet: each says
what is untested, and photos come with the first builds (phase 5 plan phase HW2). The guides are also on the project page,
in Portuguese, English and German (`/montagem/`, `/en/build-guides/`, `/de/bauen/`).

The firmware for every build is covered by the [firmware guide](../docs/manuals/en/firmware.md) ([pt](../docs/manuals/pt/firmware.md)); the field controller by the [controller setup guide](../docs/manuals/en/controller-setup.md), and its radio modem board, from flashing to a box joining a game, by [Set up the radio modem](../docs/manuals/en/modem.md) ([pt](../docs/manuals/pt/modem.md)).

Licence: CERN-OHL-S-2.0. Improved designs you distribute must stay open. The build guides themselves are CC-BY-SA-4.0.

Each build folder will hold: a bill of materials, wiring diagram, enclosure files (STL/STEP), assembly guide and photos.

## Safety

Bright colours, "GAME PROP" labels, nothing resembling a real explosive device. Use protected Li-ion cells with a BMS and charge under supervision.
