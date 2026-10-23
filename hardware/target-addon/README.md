# Target addon

Steel or polycarbonate plate with a piezo sensor and a small MCU (RP2040 or ATtiny) for hit detection. Connects to a
box through the M12 addon port: **3.3 V only** (the board's 3V3, GND, SDA, SCL; at most 25 mA; no 5 V, no interrupt
line: the box polls it every 20 ms). *Target Windows* lights the box's own LED ring, so the addon needs no LEDs; lights
of its own would need a cell of its own. The hardware of the Target Windows mode (built in software).

[BUILD.md](BUILD.md) lists what is decided and what is not: the box's side of the port is decided (decisions P5J-15
to P5J-21, 2026-10-23), with a polling driver in the firmware (a stub, not called yet); the addon's MCU and its
firmware, its I2C address and "identify" answer, the sensor and the plate are still open (phase 4 plan phase HW2), so
it is **not buildable yet**.

Status: design phase.
