<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Field Box in the Wokwi emulator

[Wokwi](https://wokwi.com) runs the real ESP32-S3 firmware binary with
simulated parts, inside VS Code. With it you can play a game on the Field
Box (screen, team buttons, LED ring, keypad) before any hardware arrives.
It is for local use only; CI does not run it.

The emulator runs a variant of the firmware, built from
`sdkconfig.defaults` plus [`sdkconfig.wokwi`](../sdkconfig.wokwi) into
`firmware/esp32/build-wokwi/`. The real board's defaults do not change.

## What is simulated

| Part | In Wokwi | Notes |
| --- | --- | --- |
| ESP32-S3, 16 MB flash, 2 MB PSRAM | Yes | `board-esp32-s3-devkitc-1`; the Heltec V4.3 has no Wokwi model, so the DevKitC-1 stands in |
| 2.8" ILI9341 SPI display, 320x240 | Yes | `lcd1`, on the display pins from Kconfig (MOSI 40, SCK 41, CS 42, DC 3, backlight 47) |
| Team buttons | Yes | `btn1` red on GPIO 4, `btn2` blue on GPIO 5 (the Field Box uses GPIO 39, a keypad column here; the emulator has no radio front end on GPIO 5); buttons 3 and 4 are off (GPIO 33/34 are not on the DevKitC-1) |
| WS2812 ring, 24 LEDs | Yes | `ring1` on GPIO 48 |
| 4x3 keypad | Yes, wired differently | `keypad1`; see below |
| PCF8574 keypad expander | No | Wokwi has no PCF8574 part |
| PN532 NFC, MAX17048 battery gauge | No | the firmware finds nothing on the I2C bus, logs a warning and carries on |
| I2S audio amplifier | No | audio is off in the variant |
| SX1262 LoRa radio | No | the phase 1 firmware does not use it |
| Wi-Fi setup portal | No | the variant skips setup and uses the defaults (admin PIN 1234) |

### The keypad workaround

The Field Box reads its keypad through a PCF8574 I2C expander, which Wokwi
cannot simulate. Writing a Wokwi custom chip for it would need a WebAssembly
toolchain and would only test the emulation of a chip, not the firmware.
Instead, the Wokwi variant selects a second keypad driver
(`CONFIG_ATALAIA_KP_GPIO_MATRIX`, `main/hal/esp/hal_esp_keypad_gpio.c`) that
scans the membrane keypad directly on GPIOs the emulator leaves free:

| Keypad pin | GPIO | Free because |
| --- | --- | --- |
| R1, R2, R3 | 6, 15, 16 | these are the I2S audio pins, and Wokwi does not simulate the amplifier |
| R4 | 7 | no front-end module on the DevKitC-1 |
| C1, C2, C3 | 1, 2, 39 | not used by the Field Box pin map |

Everything above the driver (debouncing, the preset picker, keypad events
to the game) is the same code as on the Field Box. The PCF8574 driver itself
can only be tested on hardware ([BRING_UP.md](BRING_UP.md), step 5).

The variant also accepts keypad keys typed on the serial console
(`CONFIG_ATALAIA_SERIAL_KEYS`), which is how the automation scenario types
them, since a scenario cannot press the membrane keypad.

## Set up VS Code (once)

1. Install the **Wokwi Simulator** extension in VS Code (Extensions view,
   search for "Wokwi", publisher Wokwi).
2. Request the free licence: press `F1`, run **Wokwi: Request a New
   License**, sign in with your free Wokwi account in the browser that
   opens, and let it send the licence back to VS Code. When it expires, run
   the same command again.

## Build and run

3. Build the Wokwi firmware. Docker Desktop must be running. From `cmd`,
   in the repository folder:

   ```
   python tools\docker_fw.py wokwi
   ```

   The first build takes several minutes; later ones only rebuild what
   changed. Run it again after every firmware change.
4. In VS Code, open the folder `firmware\esp32` (File > Open Folder), so
   that `wokwi.toml` is at the top of the workspace. (With the whole
   repository open instead, run **Wokwi: Select Config File** from `F1` and
   pick `firmware/esp32/wokwi.toml`.) Open `diagram.json`; the diagram
   appears. Press the green **Start** button above it, or run **Wokwi:
   Start Simulator** from `F1`.

The display shows **GAME MASTER - Enter the admin PIN**, and the serial
monitor below shows the boot log, including the warnings for the parts
Wokwi does not have.

## Play a Bomb game

5. On the keypad in the diagram, click:
   - `1` `2` `3` `4` `#`: the admin PIN. The screen shows **CHOOSE A GAME**.
   - `1` `#`: Bomb, then next. The screen shows **GAME TIMER, 10 min**.
     (`2` adds 5 minutes, `8` takes 5 away.)
   - `#`: the screen asks **START THE GAME?**
   - `#`: the game starts. The screen shows **STANDBY, hold the button to
     arm, RED**.
6. Press and hold the **red** button with the mouse for 5 seconds. The bomb
   arms: **ARMED, 5:00** counting down.
7. Press and hold the **blue** button for 10 seconds: **DEFUSED, BLUE team
   wins**. If nobody defuses it, after 5 minutes it shows **EXPLODED, RED
   team wins**.

Shortcuts: click the diagram once, then hold the `R` key for the red button
and the `B` key for the blue one. With the keypad focused, the number keys,
`*` and `#` on your keyboard press keypad keys; you can also type them in the
serial monitor.

For Domination, pick game `2`: hold a team button for 3 seconds to capture
the box, and the LED ring turns that team's colour.

## Run the scenario from the command line

[`wokwi/bomb.scenario.yaml`](../wokwi/bomb.scenario.yaml) plays the game
above by itself in about 30 seconds of simulated time and saves screenshots
of the display as `build-wokwi/scenario-*.png`. It needs
[wokwi-cli](https://github.com/wokwi/wokwi-cli) and a Wokwi CI token from
<https://wokwi.com/dashboard/ci> (the free plan has a monthly limit of CI
minutes). From `cmd`:

```
cd firmware\esp32
set WOKWI_CLI_TOKEN=your-token
wokwi-cli --timeout 60000 --scenario wokwi/bomb.scenario.yaml .
```

It ends with "Scenario completed successfully". `wokwi-cli lint` checks
`diagram.json` and needs no token.

[`wokwi/join.scenario.yaml`](../wokwi/join.scenario.yaml) joins a field
controller's game in about 10 seconds: it types a tampered join text on the
serial console (refused: "bad tag"), then a real one, and checks that the box
joined game 4242 as node 7 and shows the waiting screen
(`build-wokwi/join-1-waiting.png`). The payload is the shared test vector
`node_domination_zone` from `protocol/vectors/join.json`, signed with the
public test join key that `sdkconfig.wokwi` sets as
`CONFIG_ATALAIA_DEV_JOIN_KEY`. The emulator has no SX1262, so the box logs
that it cannot tune the radio and the controller is never heard; the radio
side is tested on the host instead (the host box and the controller's
end-to-end tests).

```
wokwi-cli --timeout 60000 --scenario wokwi/join.scenario.yaml .
```

## The same pixels as the host tests

The screen code and LVGL configuration are shared with the host tests
(`firmware/esp32/test/screens/`). The emulator's display matches those
reference images to within the rounding of RGB565 colours to 8 bits, so a
screen change shows up in the reference-image test first, and Wokwi shows
it running on the firmware.
