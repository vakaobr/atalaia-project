# Target addon

The target module: a steel or polycarbonate plate with a piezo sensor and an RP2040 board of its own that detects
each hit (its strength 0-255) and answers the box at I2C address 0x58. It plugs into a box's
[expansion port](../expansion-port/) (M12, **3.3 V only**, at most 25 mA, polled every 20 ms, no interrupt line).
*Target Windows* lights the box's own LED ring, so the module needs no LEDs. The hardware of the Target Windows mode
(built in software).

[BUILD.md](BUILD.md) ([pt](BUILD.pt.md)): parts, the module's supply entry, sensor front end and connector, checks,
the plate, and what waits for the firmware. The hardware is decided (draft RFC "The expansion port", EXP-1 to EXP-15)
and can be built; the module's firmware (UF2), the box's port driver in its game loop and Target Windows as a box
preset come with increment 8 of the RFC's plan.

Status: buildable hardware, firmware pending (increment 8).
