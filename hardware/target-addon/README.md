# Target addon

The target module: a steel or polycarbonate plate with a piezo sensor and an RP2040 board of its own that detects
each hit (its strength 0-255) and answers the box at I2C address 0x58. It plugs into a box's
[expansion port](../expansion-port/) (M12, **3.3 V only**, at most 25 mA, polled every 20 ms, no interrupt line).
*Target Windows* lights the box's own LED ring, so the module needs no LEDs. The hardware of the Target Windows mode
(built in software).

[BUILD.md](BUILD.md) ([pt](BUILD.pt.md)): parts, the module's pins, supply entry, sensor front end and connector,
flashing, checks, the plate, and what waits for the bench. The hardware is decided (draft RFC "The expansion port",
EXP-1 to EXP-15); the module's firmware ([firmware/target-module/](../../firmware/target-module/README.md), a UF2
file) and the box's port driver in its game loop came with increment 8. Target Windows becomes a box preset once
bench-tested.

Status: buildable hardware and firmware, tested on a computer only; not yet built.
