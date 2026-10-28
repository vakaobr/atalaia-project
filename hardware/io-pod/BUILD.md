<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# I/O pod build guide

Portuguese (pt-PT): [BUILD.pt.md](BUILD.pt.md).

From a bag of parts to a flashed I/O pod: a box that lends an Android phone or
tablet running an Atalaia prop the things a phone lacks: big team buttons, a
keypad, an LED ring, sound, an NFC reader, an enclosure switch and a LoRa
radio. The phone runs the game mode; the pod is its hands and its radio, over
a USB cable or Bluetooth LE. Written for a club member who can solder header
pins and wires and use a multimeter, like the
[Field Box build manual](../field-box/BUILD.md), which this guide follows and
refers to for every step the two builds share.

> **Status: not yet built.** No pod has been built from this guide, and the
> pod firmware has **not yet been tested on a real board**: it is built and
> tested on a computer, against the app and the field controller (phase 3 plan phase F).
> The pod uses the Field Box's pins, checked automatically against the
> firmware's defaults (`python3 tools/check_wiring.py`). Every physical step,
> the links to a real phone, pairing and the radio on air are **untested**
> ([BRING_UP.md, "The I/O pod"](../../firmware/esp32/docs/BRING_UP.md#the-io-pod-phase-3-plan-phase-f)
> lists the checks still to run). Steps marked **Verify at the first build**
> are open questions; please report what you find in an issue. Photos will be
> added after the first build (plan phase HW2); this guide never uses mock-up
> or generated photos.

## Contents

1. [What you are building](#1-what-you-are-building)
2. [What is decided and what is not](#2-what-is-decided-and-what-is-not)
3. [Parts](#3-parts)
4. [Tools and safety](#4-tools-and-safety)
5. [Pins](#5-pins)
6. [Enclosure and the enclosure switch](#6-enclosure-and-the-enclosure-switch)
7. [Board revision, antennas and power](#7-board-revision-antennas-and-power)
8. [Wiring, step by step](#8-wiring-step-by-step)
9. [First flash](#9-first-flash)
10. [Linking it to a phone](#10-linking-it-to-a-phone)
11. [Troubleshooting](#11-troubleshooting)

## 1. What you are building

The Field Box's hardware **without its colour screen**: the same ESP32-S3
board (Heltec WiFi LoRa 32 V4, revision V4.2 or V4.3), up to four team
buttons, a keypad through its PCF8574 expander, an LED ring, an NFC reader, an
amplifier and speaker, a battery gauge, one Li-ion cell, plus a switch that
tells when the enclosure is opened. Every part but the board is optional: the
pod tells the phone what it has (its IDENT), and the phone uses only that.
Approximate cost: about €35 for the pod's parts at hobby-market prices
([design specification](../../docs/design-spec.md), section 6); not a quote,
and not checked against a real build.

```
phone or tablet  <-- USB-C OTG cable, or Bluetooth LE -->  pod board  --> LoRa radio
(runs the mode)                                              |
                                  team buttons, keypad (PCF8574), LED ring,
                                  NFC reader, amplifier, battery gauge,
                                  enclosure switch
```

What the pod lends, from the pod firmware
([firmware/esp32/README.md, "The I/O pod"](../../firmware/esp32/README.md#the-io-pod-phase-3-plan-phase-f)):

| Part | What the phone gets |
| --- | --- |
| Team buttons 1-4 | press, hold (every 250 ms), release. Button N is the game's N-th team, as on a Field Box, unless a colour is set in the firmware |
| Keypad (3x4, through a PCF8574) | each key |
| LED ring (WS2812B) | fill with a team colour, one colour, off, brightness, a progress bar |
| Amplifier and speaker (MAX98357A) | tones, and the mode's sounds played as tones; volume |
| NFC reader (PN532) | a player tag's record (join cards are not passed on: a phone joins by QR code or text) |
| Enclosure switch | opened, closed: the phone reports an opening to the GM console as `node.tamper` |
| LoRa radio | the field's radio: the phone talks to the field controller through it, encrypted by the pod with the game key |
| Battery gauge (MAX17048) | the pod's battery level |

## 2. What is decided and what is not

Decided (in the firmware and the design documents):

- **The pod firmware** is the third image of the Field Box's firmware project
  (`python tools/docker_fw.py pod`, ADR-P3-3), with **the Field Box's pins** for
  every part it shares ([section 5](#5-pins)). It has no Lua, screens, presets
  or Wi-Fi.
- **The enclosure switch** on GPIO 47 (the Field Box's display clock; a pod has
  no display), to GND, closed while the lid is shut (decision PF8).
- **Two links to the phone at once**: USB (the board's USB-C port, which the
  phone sees as a serial device) and Bluetooth LE (`atalaia-pod-XXXX`, one
  phone at a time, paired and encrypted; decisions PF3, PF4).
- **The log** goes to UART0's transmit pin, GPIO 43, not to the USB-C port,
  which carries the pod's frames.

Not decided, or not supported yet:

- **The siren** in the design specification: the pod's sound is the amplifier
  and speaker. A separate siren, relay or strobe (the specification's `output`
  capability) is not in the pod firmware (decision P5J-7).
- **Power from the phone.** On USB, the phone powers the board; with the pod's
  main switch on, the board's charger may then charge the pod's cell from the
  phone, as a Field Box charges from any USB charger. Whether a pod should do
  that, and how much current a phone's OTG port gives, are **to verify at the
  first build** (decision P5J-8, for the maintainer).
- **The enclosure**, and how the phone and the pod are carried together (one
  case, or two linked by the cable): not chosen.
- **Settings that are not in the radio command**: the LED count, the pins, the
  radio and the Bluetooth security come from the firmware build only; a pod has
  no admin menu, so no admin PIN (decision PODC-2). The button colours, the
  ring's brightness, the volume and the enclosure switch can be set over the
  radio ([section 9, "Settings over the radio"](#settings-over-the-radio)).
- **A wiring diagram of its own**: the pod's wiring is the Field Box's without
  the display ([section 8](#8-wiring-step-by-step)); one may follow its first
  build (P5J-12).

## 3. Parts

The Field Box's parts ([manual, section 2](../field-box/BUILD.md#2-parts-and-sourcing),
where each one's pitfalls are), less the display and its window, plus:

| # | Part | Qty | What to check |
| --- | --- | --- | --- |
| 1 | Heltec WiFi LoRa 32 V4 (V4.2 or V4.3), bare board, 863-928 MHz | 1 | As the Field Box |
| 2 | 868 MHz antenna, 2 dBi or less | 1 | As the Field Box |
| 3 | 2.4 GHz FPC antenna with IPEX 1.0 lead | 1 | **Required for Bluetooth** (the pod has no Wi-Fi) |
| 4 | 60 mm arcade buttons, 5 V LED | 0-4 | As the Field Box; button 4 needs the keypad expander |
| 5 | 3x4 membrane keypad and a PCF8574 (or PCF8574A) module | 0-1 | As the Field Box: the PCF8574 powered from 3V3; not an "LCD I2C backpack" |
| 6 | WS2812B LED ring, 5 V, with the 74AHCT125 level shifter, its socket, 100 nF, 330 ohm and 1000 µF | 0-1 | As the Field Box |
| 7 | PN532 NFC module (I2C) | 0-1 | As the Field Box |
| 8 | MAX98357A I2S amplifier and a 4-8 ohm, 3 W speaker | 0-1 | As the Field Box; the pod's only sound |
| 9 | MAX17048 fuel gauge | 1 | Recommended: the phone shows the pod's battery level |
| 10 | Protected 18650 cells (one, or two in a **parallel** holder) or a 1S pack with BMS | 1S | **One cell in series only** |
| 11 | 5 V boost converter (5 V, 2.5 A or more out), fuse holder and 5 A fuse, Schottky diode (e.g. 1N5822), covered main switch, lever splices | 1 each | As the Field Box ([manual, section 7](../field-box/BUILD.md#7-power-and-battery-safety)) |
| 12 | Microswitch (snap-action, lever or plunger) for the enclosure switch | 1 | Normally open or with COM/NO/NC terminals; the lid must hold it **closed** when shut |
| 13 | Panel-mount USB-C extension with cap, USB 2.0 **data** | 1 | The phone's cable plugs in here; a "charge-only" extension breaks the USB link |
| 14 | USB-C OTG cable or adapter for the phone | 1 | The phone must support USB host (OTG) |
| 15 | 3.3 V USB-UART adapter | 1 (for the bench) | Only to read the pod's log on GPIO 43 while building it; **3.3 V** logic, never 5 V |
| 16 | IP65 enclosure, bright colour, not metal; cable glands, vent; perfboard; "GAME PROP" labels | 1 set | [Section 6](#6-enclosure-and-the-enclosure-switch) |

## 4. Tools and safety

The tools are the Field Box's ([manual, section 3](../field-box/BUILD.md#3-tools-and-consumables)).
Read its [safety rules](../field-box/BUILD.md#4-safety-rules); they all apply.
For a pod in particular:

1. **Never power the board without the LoRa antenna connected**, not even from
   the phone's cable: transmitting into an open antenna port can destroy the
   radio's front-end amplifier.
2. **One Li-ion cell in series only (1S)**; protected cells, a fuse close to the
   cell, polarity checked with a meter before every connection, charging only
   under supervision, never in a closed case, only between about 0 and 45 °C;
   cells out while you work.
3. **3.3 V signals only** into the board: I2C modules pull up to 3.3 V, the ring
   is driven through the level shifter, and the USB-UART adapter is a 3.3 V one.
4. **Never wire GPIO 5 or 46, nor GPIO 34 or 38-42**, nor anything else to GPIO
   43 than the adapter's receive line while you read the log.
5. **No game before the transmit-power check** (BRING_UP.md step 10, then the
   pod's own steps).
6. **A game prop, with a phone inside.** Bright colour, "GAME PROP" labels,
   nothing that looks like an explosive device. A phone's screen and a pod's
   buttons will be hit by BBs and paintballs: behind a clear polycarbonate
   cover, never glass, in a rugged case; the cable fixed so a player cannot
   pull it out of the phone or the box.

## 5. Pins

The Field Box's pins, for the parts a pod has, and the enclosure switch. These
are the defaults in
[`firmware/esp32/main/Kconfig.projbuild`](../../firmware/esp32/main/Kconfig.projbuild),
the reference if the two ever disagree; `python3 tools/check_wiring.py` fails
if this table does.

| Function | GPIO | Kconfig symbol | Wire colour | Goes to | Level | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Button 1 | 4 | `ATALAIA_BTN1_PIN` | green | microswitch NO; COM to GND | 3.3 V | Active low, internal pull-up |
| Button 2 | 48 | `ATALAIA_BTN2_PIN` | green | microswitch NO; COM to GND | 3.3 V | |
| Button 3 | 44 | `ATALAIA_BTN3_PIN` | green | microswitch NO; COM to GND | 3.3 V | UART0's receive line: the log adapter's TX must stay off it |
| Button 4 | PCF8574 P7 | `ATALAIA_KP_P7_BUTTON` | green | microswitch NO; COM to GND | 3.3 V | On the keypad expander's spare pin; works only when the expander is fitted |
| Keypad | I2C | -- | brown, red, orange, yellow (rows R1-R4), green, blue, violet (columns C1-C3) | PCF8574 P0-P3 and P4-P6 | 3.3 V | PCF8574 at 0x20 (a PCF8574A at 0x38 is found too) |
| LED ring data | 35 | `ATALAIA_LED_PIN` | white | hub "LED data in", then the 74AHCT125 and 330 ohm to ring DIN | 3.3 V in, 5 V out | |
| I2C SDA | 17 | `ATALAIA_NFC_SDA_PIN` | blue | hub SDA rail: PCF8574, PN532 (0x24), MAX17048 (0x36) | 3.3 V | The board's bus (its OLED is not used by a pod) |
| I2C SCL | 18 | `ATALAIA_NFC_SCL_PIN` | yellow | hub SCL rail | 3.3 V | |
| I2S BCLK | 6 | `ATALAIA_AUDIO_BCLK_PIN` | grey | amplifier BCLK | 3.3 V | MAX98357A |
| I2S LRCLK | 15 | `ATALAIA_AUDIO_LRCLK_PIN` | pink | amplifier LRC | 3.3 V | |
| I2S DOUT | 16 | `ATALAIA_AUDIO_DOUT_PIN` | brown | amplifier DIN | 3.3 V | |
| Enclosure switch | 47 | `ATALAIA_POD_TAMPER_PIN` | any (not in the Field Box diagram) | microswitch COM to GND, NO to the pin | 3.3 V, internal pull-up | Closed while the lid is shut |
| Log (UART0 TX) | 43 | -- | any | A 3.3 V USB-UART adapter's RX, with its GND | 3.3 V | Board-internal: only while you read the log |

Rails, not GPIOs: 3V3 (violet) to the I2C parts and the keypad expander; GND
(black); the 5 V rail (orange) to the ring, the amplifier and the button
LEDs. The full list of pins you must never wire is in the
[Field Box pin reference](../field-box/BUILD.md#15-pin-reference).

The display's other pins on a Field Box (GPIO 1, 3, 33) are not used by the pod:
leave them unconnected. GPIO 0, 45 and 46 are boot straps; the board-internal
pins are listed in the [Field Box pin map](../field-box/README.md#pin-assignments-default-kconfig----heltec-v43).

## 6. Enclosure and the enclosure switch

<!-- PHOTO: io-pod-enclosure.jpg | the pod's enclosure, with the enclosure switch and the lid's tab that presses it -->
> **Photo to be added after the first build:** the enclosure, with the
> enclosure switch and the part of the lid that presses it.

No enclosure has been chosen. Prepare it as the Field Box's
([manual, section 5](../field-box/BUILD.md#5-enclosure-preparation)): plastic,
never metal (the radio and Bluetooth must get out), IP65, bright, buttons on
the lid, the main switch recessed or covered, a vent, the panel USB-C socket
where the phone's cable reaches it, every unused hole sealed.

**The enclosure switch.** Mount a microswitch inside so that the closed lid
presses it, and wire it between **GPIO 47** and **GND**: closed (pressed)
while the lid is shut, open when the lid is lifted. The firmware arms it only
after it has read closed once, so a pod built without a switch never reports
an opening. A switch wired the other way round (open while shut) needs
`CONFIG_ATALAIA_POD_TAMPER_OPEN_HIGH` turned off.

**Verify at the first build:** the lid presses the switch reliably on every
closing, and does not let go when the box is knocked; the Bluetooth range
through the wall.

## 7. Board revision, antennas and power

<!-- PHOTO: io-pod-board-power.jpg | the board with both antennas fitted and labelled, and the power path as built -->
> **Photo to be added after the first build:** the board with both antennas
> fitted and labelled, and the power path as built.

Exactly as the Field Box:

1. **Board revision** ([manual, section 6](../field-box/BUILD.md#6-board-revision-and-antennas)):
   **KCT8103L** next to the LoRa connector is a V4.3 (the default), **GC1109**
   a V4.2. Write it on the backplate; the pod firmware must be built for it.
2. **Antennas before any power**, both labelled: LoRa (868 MHz, 2 dBi or less,
   or set the firmware's antenna gain) and the 2.4 GHz FPC antenna (Bluetooth).
3. **Power path** ([manual, section 7](../field-box/BUILD.md#7-power-and-battery-safety)
   and [diagram 2/2](../field-box/wiring/field-box-power.svg)): cell(s), fuse,
   Schottky diode, main switch, BAT+ splice; the boost converter set to
   5.0-5.2 V on its own first; then the 5 V loads (ring, amplifier, button LEDs,
   level shifter); the gauge's battery-sense input on BAT+; the board's battery
   lead last, after a polarity check.

**Verify at the first build:** what the board draws from the phone's USB-C OTG
port with the switch off and with it on (charging), the runtime of a 2-hour
game on Bluetooth (BRING_UP.md, "The I/O pod", step 10).

## 8. Wiring, step by step

<!-- PHOTO: io-pod-inside.jpg | the inside of the finished pod, with the wiring routed -->
> **Photo to be added after the first build:** the inside of the finished pod,
> with the wiring routed.

Cell out, fuse out, switch off. Follow the Field Box's
[wiring, step by step](../field-box/BUILD.md#9-wiring-step-by-step) and its
[signals diagram](../field-box/wiring/field-box-wiring.svg), **leaving out the
display** ([9.4](../field-box/BUILD.md#94-display)) and its wires to GPIO 1, 3,
33 and 47, then add the enclosure switch:

1. **Interconnect board** ([manual, section 8](../field-box/BUILD.md#8-the-interconnect-board)):
   rails 3V3, GND, SDA, SCL and 5V, and the 74AHCT125. Without the display, its
   3V3 and GND pins for the display stay free.
2. **Board and rails**: 3V3, GND, GPIO 17 (SDA) and GPIO 18 (SCL) to the hub.
3. **I2C modules** you fit: PCF8574 (address jumpers all to GND: 0x20), PN532
   (mode switches on I2C), MAX17048, each with 3V3, GND, SDA, SCL from the hub,
   each checked to pull SDA and SCL up to 3.3 V or less before it goes on the bus.
4. **Keypad** on the PCF8574: rows R1-R4 on P0-P3, columns C1-C3 on P4-P6,
   identified with the meter first.
5. **LED ring**: capacitor at the ring, DIN to the hub's "LED data out", 5 V and
   GND to the 5 V splices, GPIO 35 to "LED data in".
6. **Team buttons**: NO to GPIO 4, 48 and 44, and button 4 to the PCF8574's P7;
   COM to GND.
7. **Amplifier**: BCLK GPIO 6, LRC GPIO 15, DIN GPIO 16; VIN and GND to 5 V; the
   speaker's wires never to GND.
8. **Enclosure switch**: COM to a hub GND pin, NO to **GPIO 47**
   ([section 6](#6-enclosure-and-the-enclosure-switch)). Check with the meter:
   the switch's wire beeps to GND while the lid is shut, and not when it is open.
9. **USB.** The panel USB-C extension to the board's USB-C port.
10. **Board battery lead**, after its polarity check
    ([manual, 9.8](../field-box/BUILD.md#98-board-battery-lead)).

Then the Field Box's [final inspection](../field-box/BUILD.md#99-final-inspection-before-any-power),
less its display line.

## 9. First flash

The pod firmware is flashed from your computer, like the Field Box's
([manual, section 11](../field-box/BUILD.md#11-first-flash)). **Easiest:
download `atalaia-io-pod-<version>-usb.zip` from
[GitHub's Releases page](https://github.com/vakaobr/atalaia-project/releases)** (pre-alpha, not field-tested; V4.3, EU868; check
`SHA256SUMS`), unzip it and flash from that folder as steps 2 onward say. Or
build it in Docker, with two differences from the Field Box: the build command
and the build folder.

1. **Build** (add `--region=as923-tw` for Taiwan: the pod, the modem, the
   boxes and the controller must share one region):

   ```
   python tools\docker_fw.py pod
   ```

   It ends with `I/O pod firmware: firmware/esp32/build-pod/atalaia_esp32.bin`.
   It is built for a **V4.3** board by default. The pod's settings file is
   `firmware\esp32\build-pod\sdkconfig` (not the Field Box's
   `firmware\esp32\sdkconfig`): for a **V4.2**, change its two board lines as
   the [manual, section 11](../field-box/BUILD.md#11-first-flash), step 2,
   says, and build again. The build makes a fresh settings file whenever
   `sdkconfig.defaults` or `sdkconfig.pod` change, so keep a note of what you
   changed.
2. **Flash** with esptool as the manual's steps 3-6 say, from
   `firmware\esp32\build-pod` instead of `firmware\esp32\build`:

   ```
   cd firmware\esp32\build-pod
   %FLASH% -m esptool --chip esp32s3 -p COM5 -b 921600 write_flash "@flash_args"
   cd ..\..\..
   ```
   Restart it with `%FLASH% -m esptool --chip esp32s3 -p COM5 --after hard_reset chip_id`.
   The [firmware guide](../../docs/manuals/en/firmware.md#10-the-io-pod-variants)
   has the steps for macOS and Linux and what else is different for a pod.
3. **Read the log** on GPIO 43 with the 3.3 V USB-UART adapter (its RX to GPIO
   43, its GND to GND, its TX unconnected), at 115200 baud. Expect
   `Atalaia I/O pod`, `Vext on`, a line for each part that is missing, the
   radio's lines, `advertising as atalaia-pod-XXXX` and the list of the
   capabilities it lends.

**Settings** (lines in `firmware\esp32\build-pod\sdkconfig`, then build again;
the Kconfig menu "I/O pod", listed in firmware/esp32/README.md):

| Your build | Line in `build-pod\sdkconfig` |
| --- | --- |
| A button stands for a fixed team colour | `CONFIG_ATALAIA_POD_BTN1_TEAM="red"` (to `BTN4`; empty: the game's N-th team) |
| No enclosure switch | `CONFIG_ATALAIA_POD_TAMPER_PIN=-1` (optional: an unwired switch never reports) |
| Switch open while the lid is shut | `# CONFIG_ATALAIA_POD_TAMPER_OPEN_HIGH is not set` |
| USB only, no Bluetooth | `# CONFIG_ATALAIA_POD_BLE is not set` |
| 12- or 16-LED ring | `CONFIG_ATALAIA_LED_COUNT=12` (or 16) |
| Antenna with more than 2 dBi | `CONFIG_ATALAIA_RADIO_ANTENNA_GAIN_DBI=` its gain, rounded up |

Leave `CONFIG_ATALAIA_POD_BLE_ENCRYPTED` on: it keeps the game key off an
unencrypted Bluetooth link.

### Settings over the radio

Four of the pod's settings can be changed without a cable and without building
again: **the buttons' colours, the ring's default brightness, the volume and
whether the enclosure switch reports**. The field controller pushes them over
the radio from the GM console (decision PODC; the format is
[protocol/pod-config.md](../../protocol/pod-config.md)). The `build-pod\sdkconfig` lines above are the values the pod has until
something is pushed; what is pushed is kept in the pod's flash and wins over them,
also after a restart, until it is reset.

1. **The pod must be linked to a phone that has joined the game** ([section 10](#10-linking-it-to-a-phone)):
   the pod's radio is the phone's node in the game, and it opens the command
   with the game key. A pod not linked, or a phone not in the game, cannot be
   reached.
2. In the GM console (the Pi's or the phone's), tab *Boxes*, panel *I/O pods'
   settings*: the phones of the game are listed. For the phone with the pod,
   tick *Set the colours* and choose a colour for each button (*the game's team*
   is the default: button N is the game's N-th team), and/or the ring's
   brightness and the volume in percent, and the enclosure switch (*reports a
   tamper* or *ignored*; a switch the build did not fit stays off). Fill in only
   what you want to change. *Back to the build's settings first* drops
   everything pushed so far.
3. Press *Send to the pod*. The controller sends it over the radio and shows
   *sent (1), waiting*; the pod keeps it, shows its new colours to the phone at
   once and says so through its phone: the page shows *taken by the pod*. If the
   answer does not come, the controller sends it again after 8, 16, 32, 64 and
   128 seconds, then shows *no answer*.
4. **No answer** means one of: the phone has no I/O pod (the console cannot
   tell), the pod's firmware is older than this feature (flash a newer one), the pod is
   not linked or out of radio reach, or it is out of battery.

Only **before a game starts or after it ended**; during a game the panel is
disabled. A **new pod firmware** is needed once (this feature is in the
firmware); until then a pod keeps working with its build's settings and the
console shows *no answer*.

## 10. Linking it to a phone

Then follow [BRING_UP.md, "The I/O pod"](../../firmware/esp32/docs/BRING_UP.md#the-io-pod-phase-3-plan-phase-f),
with the board steps of BRING_UP.md that apply first (revision, antenna,
**transmit power: no game before it**, NFC, keypad, LEDs, audio). In short:

1. **USB.** A USB-C OTG cable from the phone to the pod. In the app:
   *Prop > I/O pod > Find pods*, open it, allow USB access: "Pod linked over USB".
2. **Bluetooth.** Unplugged: *Find pods* lists `atalaia-pod-XXXX`; open it and
   confirm Android's pairing question once: "Pod linked over BLE".
3. **A game.** A prop game on the phone with the pod linked: its buttons are the
   game's teams by number, its ring shows the team, its reader checks player
   tags, and the phone's radio link to the field controller goes through the
   pod.

## 11. Troubleshooting

The [Field Box manual, section 13](../field-box/BUILD.md#13-troubleshooting)
covers the board, the I2C modules, the keypad, the ring, the buttons, the
amplifier and the power. For a pod in particular:

| Symptom | Likely cause and fix |
| --- | --- |
| No log at all | The log is on GPIO 43 (UART0), not on the USB-C port: the adapter's RX to GPIO 43, GND to GND, 115200 baud |
| The phone does not find the pod over USB | A charge-only cable or panel extension; the phone has no USB host (OTG) |
| Opening the USB port resets the pod | The app sets DTR and RTS together; another serial app may not: use the Atalaia app |
| `atalaia-pod-XXXX` not listed | The 2.4 GHz antenna missing or on the wrong connector; another phone is linked (one at a time); Bluetooth turned off in the build |
| The phone never shows "Someone opened the I/O pod" | No switch on GPIO 47, or it never read closed (the lid does not press it); a switch wired the other way round needs `POD_TAMPER_OPEN_HIGH` off |
| The pod reports an opening by itself | The switch lets go when the box is knocked: mount it firmer, or use a lever switch |
| Button 4 never registers | It is on the PCF8574's P7: the expander must be fitted and found at boot |
| Anything hot, a smell, smoke | Unplug the phone, switch off, take the fuse out, take the cells out into a fire-safe bag |

If you find a fault that is not here, or a step that is wrong, please open an
issue (photos welcome): this guide is corrected from the first builds.

---

Licence: this guide is CC-BY-SA-4.0; the hardware designs it refers to are
CERN-OHL-S-2.0 ([LICENSING.md](../../LICENSING.md)).
