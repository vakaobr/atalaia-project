<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Target addon build guide (not buildable yet)

The target addon is a plate that players shoot at, with a sensor that feels
each hit and a ring of lights, which plugs into a box and turns it into a
scoring target: the hardware of the *Target Windows* mode, where a hit while
the target shows a team's colour scores for that team.

> **Status: designed only, not buildable yet.** The target addon is **not
> built**, and the parts that would let you build one are **not decided**: no
> firmware for its own small processor exists, the Field Box's firmware has no
> driver for its port, and no part numbers, pin order or wiring have been
> chosen (phase 4, plan phase HW2). This guide says what is decided, with
> where each decision comes from, and lists what is not, so nobody builds
> something the firmware will not support. **Do not wire a plate to a Field
> Box from this page.** When the addon is designed, this page becomes its
> build guide, with photos (plan phase HW2); this guide never uses mock-up or
> generated photos.

## 1. What is decided

| What | Decided | Where |
| --- | --- | --- |
| Purpose | A hit-scoring target for any box | [Design specification](../../docs/design-spec.md), section 6 |
| Parts, in outline | A steel or polycarbonate plate, a piezo sensor, a small processor (RP2040 or ATtiny class) for hit detection, a WS2812 LED ring | Design specification, section 6 |
| Approximate cost | €20–30 in parts at hobby-market prices (not a quote) | Design specification, section 6 |
| How it connects | A waterproof **5-pin M12 connector** on the box: GND, 5 V, SDA, SCL and an interrupt line. The addon carries its own small processor, which answers an "identify" request with a capability descriptor, so the box needs no new driver for each addon | Design specification, section 6, "Addon bus" |
| Cable length | I2C is reliable to about 1–2 m; a target further away uses a Satellite or a thin node over the radio instead | Design specification, section 6 |
| What the box's game scripts see | The `hit` capability: an event `hit` with a `strength` from 0 to 255 (scripts get `hit.hit`), and the commands `arm` and `disarm` (it reports hits only while armed) | Design specification, section 7; draft RFC 0000 Amendment 1; decision P4R4 |
| On a phone's I/O pod | The same `hit` capability in the capability proxy protocol (`{"id": "hit", "type": "hit"}`), with shared test vectors `target_addon`, `target_hit` and `target_arm`, so a pod could lend one to a phone. No pod built so far has one | [protocol/capability-proxy.md](../../protocol/capability-proxy.md), "A hit sensor" |
| The game mode | *Target Windows* (`modes/target_windows/`): the role `target` needs `hit` and `led`. The target is dark for `interval_s`, then lights a random team's colour for `window_s`; a hit of at least `min_strength` in the window scores `hit_points` for that team. Built and tested in the simulator; not a Field Box preset until the addon exists | [Phase 4 plan](../../docs/phase-4-site-server/PLAN.md), plan phase 2; decisions M2-1 to M2-5 |
| What comes next | The addon's processor firmware, its link to the Field Box's port, the `hit` capability in the Field Box's firmware, the sensor's threshold and debounce tuned on steel and on polycarbonate plates; then *Target Windows* becomes a built-in preset | Phase 4 plan, HW2 |

## 2. What is not decided

Each of these needs a decision before anyone wires a plate (decision P5J-9,
for the maintainer):

1. **The processor**: RP2040 or ATtiny (the specification names both), and the
   firmware it runs.
2. **The "identify" request and the hit report on I2C**: the addon's I2C
   address, how it answers with its capability descriptor, how the box reads a
   hit and its strength, and how it sends `arm` and `disarm`. Nothing of this
   is specified yet; the capability proxy protocol defines what the phone's
   side sees, not the wire between a box and an addon.
3. **The M12 connector's pin order**, its coding, and the cable.
4. **Voltage on SDA and SCL.** The box's I2C bus is 3.3 V (the ESP32-S3 is a
   3.3 V part, and the Field Box's I2C modules must pull up to 3.3 V), while the
   connector also carries 5 V for the addon. Which side pulls the bus up, and
   to what, is not decided; a 5 V pull-up on the box's bus could damage the
   board.
5. **The interrupt line's GPIO on the Field Box.** The Field Box uses all eight
   of the board's GPIOs that are free of any board part (3, 4, 6, 15, 16, 33, 47,
   48; [pin table](../field-box/README.md#peripheral-pins)), and the GNSS
   connector keeps 34 and 38-42. So a Field Box has **no free GPIO** for the
   addon's interrupt line today: it would need a pin given up (for example the
   optional audio, or button 3), the keypad expander, or polling over I2C
   without an interrupt. (On an I/O pod the display's GPIO 1, 3 and 33 are
   unused.)
6. **Which LED ring shows the window**: the addon's own WS2812 ring, driven by
   its processor, or the box's ring. *Target Windows* needs an `led`
   capability; the specification gives the addon a ring.
7. **The sensor circuit**: the piezo element, how it is mounted on the plate
   (and isolated from it), its protection and the analogue front end; the
   threshold and debounce are to be tuned on real plates (HW2).
8. **The plate**: material and thickness, size, its stand and the angle it is
   set at, and the enclosure that protects the processor and the cable.

## 3. Safety, once there is something to build

These hold for any target used with airsoft or paintball, whatever the
design:

- **Eye and face protection** for everyone within range of the target while
  anyone shoots at it, including at the bench while the sensor is tuned.
- **Ricochets.** BBs bounce off a hard plate, and some come back. Set a steel
  plate at an angle that sends them down to the ground, never flat towards the
  shooter. Never shoot at the box, the cable or the
  connector, only at the plate.
- **Shield the electronics.** The processor, the LED ring's wiring and the
  cable sit behind the plate or in their own enclosure, out of the line of fire.
- **The field's power limits** (the chrono, the joule limit) apply to shooting
  at targets as to shooting at players; the target is not a reason to raise
  them.
- **A game prop**: bright colours and a "GAME PROP" label, like every Atalaia
  device; and the box it plugs into follows its own build guide's battery
  rules ([Field Box](../field-box/BUILD.md#4-safety-rules),
  [Satellite](../satellite/BUILD.md#4-tools-and-safety)).

## 4. Photos

<!-- PHOTO: target-addon-plate.jpg | the finished target: plate, sensor mounting and LED ring, front and back -->
> **Photo to be added after the first build:** the finished target, plate,
> sensor mounting and LED ring, front and back.

<!-- PHOTO: target-addon-port.jpg | the M12 addon port on a box, and the addon's cable plugged in -->
> **Photo to be added after the first build:** the M12 addon port on a box,
> with the addon's cable plugged in.

## 5. Helping

If you want to design the addon, open an issue or a discussion first: the
decisions above come before any wiring, and the firmware side (the port's
driver and the `hit` capability on a box) has to be written with it. Designs
are CERN-OHL-S-2.0, like the rest of the hardware
([LICENSING.md](../../LICENSING.md)).

---

Licence: this guide is CC-BY-SA-4.0.
