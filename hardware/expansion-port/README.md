# Expansion port

The waterproof 5-pin M12 socket that modules plug into from outside a box (the target addon now, contacts and other
sensors later), and the small port board behind it: a hot-swap I2C buffer with stuck-bus recovery (TCA4307), a
low-capacitance TVS array, 100 ohm series resistors, a 50 mA resettable fuse and a back-feed Schottky diode, so a wet,
shorted or static-charged cable cannot take the box's own I2C bus down. **3.3 V only**: 1 brown 3.3 V (at most 25 mA,
for a module's logic), 2 white SDA, 3 blue GND, 4 black SCL, 5 grey not connected. It uses no GPIO, so the Field Box,
the Satellite and the I/O pod can each have one, as an option. Modules answer at 0x58-0x5F (draft RFC "The expansion
port", decisions EXP-1 to EXP-15; the protocol is [protocol/expansion-port.md](../../protocol/expansion-port.md)).

[BUILD.md](BUILD.md) ([pt](BUILD.pt.md)): parts and what each protects against, the pin table (checked against the
firmware by `tools/check_wiring.py`), assembly, checks and the bench tests, safety.

Status: designed, not yet built; the box's firmware reads the port from increment 8 of the RFC's plan.
