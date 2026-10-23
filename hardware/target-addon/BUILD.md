<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Target addon build guide (not buildable yet)

The target addon is a plate that players shoot at, with a sensor that feels
each hit, which plugs into a box and turns it into a scoring target: the
hardware of the *Target Windows* mode, where a hit while the target shows a
team's colour scores for that team.

> **Status: the box's side is decided; the addon is not.** Since 2026-10-23
> the port on the box is specified (3.3 V only, four wires, no interrupt
> line: the box polls the addon; decisions P5J-15 to P5J-21), and the Field
> Box's firmware has a tested polling driver for it (a stub, not called yet).
> The addon itself is **not buildable yet**: its processor is not chosen, no
> firmware for it exists, its I2C address and "identify" answer are not
> decided, and the sensor and the plate are not designed (phase 4, plan phase
> HW2; [section 5](#5-what-is-not-decided)). This guide says what is decided,
> with where each decision comes from, and lists exactly what is not, so
> nobody builds something the firmware will not support. **Do not wire a
> plate to a Field Box from this page.** When the addon is designed, this page
> becomes its build guide, with photos (plan phase HW2); this guide never uses
> mock-up or generated photos.

## 1. What is decided

| What | Decided | Where |
| --- | --- | --- |
| Purpose | A hit-scoring target for any box | [Design specification](../../docs/design-spec.md), section 6 |
| Parts, in outline | A steel or polycarbonate plate, a piezo sensor, a small processor (RP2040 or ATtiny class) for hit detection. LEDs of its own only with a supply of its own ([section 2](#2-the-port-on-the-box)) | Design specification, section 6; P5J-16 |
| Approximate cost | €20–30 in parts at hobby-market prices (not a quote) | Design specification, section 6 |
| How it connects | A waterproof **5-pin M12 connector** on the box carrying **3.3 V only**: the board's 3V3 rail, GND, and the box's I2C bus (SDA, SCL) at 3.3 V. **No 5 V on the port.** The fifth pin is not connected. The addon carries its own small processor, which answers an "identify" request with a capability descriptor, so the box needs no new driver for each addon | Design specification, section 6, "Addon bus" (corrected 2026-10-23); P5J-15, following M3 |
| Power from the box | At most **25 mA** from the port's 3.3 V, for the processor and the sensor's circuit, through a resettable fuse in the box | P5J-16 |
| The window's lights | *Target Windows* lights the **box's own LED ring** (`cap("ring")` in `modes/target_windows/node.lua`), so an addon needs no LEDs. An addon with lights of its own powers them from its own cell, never from the port | P5J-16 |
| No interrupt line | The box **polls** the addon over I2C every 20 ms; a hit reaches the game within about 21 ms ([section 4](#4-how-the-box-reads-hits-no-interrupt-line)). No GPIO is needed, so the Field Box's pin map does not change | P5J-18 |
| Cable | I2C at 100 kHz over at most **2 m** of 5-core M12 cable; a target further away uses a Satellite or a thin node over the radio instead | Design specification, section 6; P5J-17 |
| What the box's game scripts see | The `hit` capability: an event `hit` with a `strength` from 0 to 255 (scripts get `hit.hit`), and the commands `arm` and `disarm` (it reports hits only while armed) | Design specification, section 7; draft RFC 0000 Amendment 1; decision P4R4 |
| How a hit crosses the wire (draft) | A 5-byte report the box reads (flags, the hit's sequence number, its strength, its age, a CRC-8) and three commands it writes (acknowledge a hit, arm, disarm). The addon holds each hit until the box acknowledges it, so none is lost to a busy bus | [`firmware/esp32/main/target_addon.h`](../../firmware/esp32/main/target_addon.h); P5J-19 |
| On a phone's I/O pod | The same `hit` capability in the capability proxy protocol (`{"id": "hit", "type": "hit"}`), with shared test vectors `target_addon`, `target_hit` and `target_arm`, so a pod could lend one to a phone. No pod built so far has one | [protocol/capability-proxy.md](../../protocol/capability-proxy.md), "A hit sensor" |
| The game mode | *Target Windows* (`modes/target_windows/`): the role `target` needs `hit` and `led`. The target is dark for `interval_s`, then lights a random team's colour for `window_s`; a hit of at least `min_strength` in the window scores `hit_points` for that team. Built and tested in the simulator; not a Field Box preset until the addon exists | [Phase 4 plan](../../docs/phase-4-site-server/PLAN.md), plan phase 2; decisions M2-1 to M2-5 |
| What comes next | The addon's processor and its firmware, the polling driver called from the box's game loop, the `hit` capability in the Field Box's firmware, the sensor's threshold and debounce tuned on steel and on polycarbonate plates; then *Target Windows* becomes a built-in preset | Phase 4 plan, HW2 |

## 2. The port on the box

The port is the box's I2C bus taken out through a connector, so it follows the
rules every I2C module in the Field Box already follows: powered from the
board's 3V3, never from 5 V, and nothing pulls SDA or SCL above 3.3 V
(decision M3, confirmed by the maintainer on 2026-10-21; the
[Field Box build manual, section 9.2](../field-box/BUILD.md#92-i2c-modules);
the keypad expander's "powered from 3V3, never 5V" in the
[parts list](../field-box/README.md#bill-of-materials-per-box)).

| M12 pin (A-coded, 5-pin) | Usual wire colour | Signal | On the box |
| --- | --- | --- | --- |
| 1 | brown | 3.3 V | The interconnect board's 3V3 rail, through a resettable fuse (PTC, about 50 mA hold) |
| 2 | white | SDA | The SDA rail (board GPIO 17) |
| 3 | blue | GND | The GND rail |
| 4 | black | SCL | The SCL rail (board GPIO 18) |
| 5 | grey | not connected | Free at both ends, and never 5 V. A later box with a GPIO to spare could make it an interrupt line |

SDA and SCL are on pins 2 and 4, across the connector from each other rather
than side by side (decision P5J-20). The port waits for the first addon: a
Field Box built today does not need it.

The addon's side, from the same decisions:

- **Nothing above 3.3 V on any pin.** The addon's processor runs from the
  port's 3.3 V; a part on its side that needs more makes it from its own
  supply, which never connects to the port.
- **No pull-up resistors on SDA or SCL in the addon**: the box's bus has them
  (P5J-17).
- **At most 25 mA** from pin 1 (P5J-16). An ATtiny-class processor and the
  piezo's circuit draw a few milliamperes; an RP2040 at full speed comes close
  to the limit, so it must be measured, or run slower.
- **Its own lights, if any, from its own cell**: a protected 1S cell with its
  own fuse and boost converter, as in the Satellite's power path, its GND
  joined to the port's GND; its supply never reaches the port (P5J-16).

### Why 25 mA

The board's 3.3 V regulator already feeds the board (the ESP32-S3 and the
radio: about 80-150 mA, with peaks of 400-500 mA while Wi-Fi or the radio
transmits), the TFT with its backlight (40-100 mA), the PN532 (50-150 mA with
its field on), and the keypad expander and the gauge (under 1 mA): roughly
170-400 mA in a game, with peaks near 750 mA
([Field Box power budget](../field-box/BUILD.md#power-budget-estimates-not-measurements),
estimates, not measurements). The LED ring, the amplifier and the button LEDs
are on the 5 V boost converter, not on 3.3 V. The regulator's own limit is not
documented here, and whether it copes with the TFT and the NFC reader is still
a **Verify at the first build** item of the Field Box. So the port promises
only a small, fixed share: 25 mA is about 3 % of those peaks, and the fuse
keeps a short in the cable or the connector from browning the box out. A
single WS2812 LED draws up to 60 mA, so lights on the port are out of the
question.

## 3. Checks at the first build (to verify)

- **Pull-ups and cable.** At 100 kHz the bus must rise within 1 µs. At about
  100 pF per metre of cable, 2 m of cable and the box's own modules come to
  roughly 300 pF, which needs the pull-ups on the box's bus, all in parallel,
  between about **1 kΩ and 3.9 kΩ** (1 kΩ keeps the current a device must
  sink under 3 mA). Measure it with the box unpowered and every module
  fitted: SDA to 3V3 and SCL to 3V3, on the meter's resistance range. Above
  3.9 kΩ, fit a 2.2 kΩ pair from SDA and SCL to the 3V3 rail on the
  interconnect board. Then check that the keypad, the NFC reader and the gauge
  still work with the cable and an addon plugged in.
- **The fuse.** A short between pins 1 and 3 of the port must not reset the
  box.
- **Protecting the bus on an outside connector** (static from a hand, water in
  the connector): small series resistors and protection diodes at the port are
  likely; their values are not chosen.
- **The addon's current**, against the 25 mA.

## 4. How the box reads hits (no interrupt line)

The Field Box uses all eight of the board's GPIOs that are free of any board
part (3, 4, 6, 15, 16, 33, 47, 48;
[pin table](../field-box/README.md#peripheral-pins)), and the GNSS connector
keeps 34 and 38-42, so there is no pin for an interrupt line. It does not need
one (decision P5J-18):

- All of the box's I2C traffic, the keypad's included, already runs in its game
  loop, every 10 ms. An interrupt would be noticed only at the next tick, so
  the best it could give is a hit within 10 ms; polling every 20 ms gives it
  within 20 ms, plus 0.56 ms to read the report.
- **Bus time.** At 100 kHz a byte with its acknowledge takes 90 µs. A poll (the
  address and 5 bytes) takes about **0.56 ms**: every 20 ms, about **3 %** of
  the bus. Taking a hit adds a 2-byte acknowledge (0.28 ms). The keypad's scan,
  every 10 ms, already uses about 18 %; the gauge (every 10 s) next to nothing;
  the board's OLED a few milliseconds when its picture changes.
- **Latency.** A hit reaches the script about 10 ms after the addon felt it on
  average, and within about 21 ms, against a target of 50 ms: a hit's light and
  sound feel immediate, and a window is open for at least 1 s (5 s by
  default), so 20 ms is at most 2 % of it; a BB takes 0.2-0.3 s to cross
  20-30 m anyway. Slower moments: an NFC poll (every 300 ms in a game) can hold
  the loop for up to about 200 ms when the reader is slow to answer, and
  reading a player's tag for longer. Hits are not lost then: the addon keeps
  them, with their age, until the box takes them.
- The options left aside: sharing the keypad expander's INT line (it is not
  wired, `ATALAIA_KP_INT_PIN` is -1, wiring it would take a GPIO too, and all
  eight of the expander's pins are in use), or freeing a GPIO by giving up the
  sound or button 3, which would cost every box a feature for 10 ms.

The driver (`firmware/esp32/main/target_addon.c`, host tests in
`firmware/esp32/test/test_target_addon.c`) polls, takes each hit once (a lost
acknowledge does not count a hit twice), sends `arm` and `disarm` again until
the addon's report agrees, refuses reports with a bad CRC, and counts the addon
as gone after 25 failed reads in a row (0.5 s). **Not done yet**, for when the
addon's address is decided: the I2C reads and writes at that address
(`hal_esp_i2c`), finding the addon at start and adding `hit` to the box's
capabilities, calling the driver from the game loop and passing each hit to the
script as `hit.hit` with its `strength`, sending the script's
`cap("hit"):arm()` and `:disarm()` to it (`command_dispatch.c`), and making
*Target Windows* a preset (P4R23).

## 5. What is not decided

Each of these needs a decision before anyone builds an addon:

1. **The processor**: RP2040 or ATtiny (the specification names both),
   within the 25 mA, and the firmware it runs.
2. **The addon's I2C address and its "identify" answer** (the capability
   descriptor). The address must keep clear of the box's devices: 0x20-0x27
   and 0x38-0x3F (where the box looks for its keypad expander), 0x24 (NFC),
   0x36 (gauge) and 0x3C (OLED). The hit report and the commands have a
   **draft** ([section 1](#1-what-is-decided)) that both firmwares can be
   written against; it becomes final with the first addon.
3. **The connector's parts and the cable's maker**, and the protection at the
   port ([section 3](#3-checks-at-the-first-build-to-verify)).
4. **The sensor circuit**: the piezo element, how it is mounted on the plate
   (and isolated from it), its protection and the analogue front end; the
   threshold and debounce are to be tuned on real plates (HW2).
5. **The plate**: material and thickness, size, its stand and the angle it is
   set at, and the enclosure that protects the processor and the cable.
6. **Lights on the addon itself**: not needed for *Target Windows*; if a later
   design wants them, its own cell, charging and enclosure.

## 6. Safety, once there is something to build

These hold for any target used with airsoft or paintball, whatever the
design:

- **Eye and face protection** for everyone within range of the target while
  anyone shoots at it, including at the bench while the sensor is tuned.
- **Ricochets.** BBs bounce off a hard plate, and some come back. Set a steel
  plate at an angle that sends them down to the ground, never flat towards the
  shooter. Never shoot at the box, the cable or the
  connector, only at the plate.
- **Shield the electronics.** The processor, its wiring and the cable sit
  behind the plate or in their own enclosure, out of the line of fire.
- **The field's power limits** (the chrono, the joule limit) apply to shooting
  at targets as to shooting at players; the target is not a reason to raise
  them.
- **A game prop**: bright colours and a "GAME PROP" label, like every Atalaia
  device; and the box it plugs into follows its own build guide's battery
  rules ([Field Box](../field-box/BUILD.md#4-safety-rules),
  [Satellite](../satellite/BUILD.md#4-tools-and-safety)), as does an addon's
  own cell, if it has one.

## 7. Photos

<!-- PHOTO: target-addon-plate.jpg | the finished target: plate and sensor mounting, front and back -->
> **Photo to be added after the first build:** the finished target, plate and
> sensor mounting, front and back.

<!-- PHOTO: target-addon-port.jpg | the M12 addon port on a box, and the addon's cable plugged in -->
> **Photo to be added after the first build:** the M12 addon port on a box,
> with the addon's cable plugged in.

## 8. Helping

If you want to design the addon, open an issue or a discussion first: the
decisions above come before any wiring, and the rest of the firmware side
(calling the port's driver, and the `hit` capability on a box) has to be
written with it. Designs are CERN-OHL-S-2.0, like the rest of the hardware
([LICENSING.md](../../LICENSING.md)).

---

Licence: this guide is CC-BY-SA-4.0.
