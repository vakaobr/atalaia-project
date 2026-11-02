<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Example scoreboard (MQTT)

A small program that follows the score of a game through the field controller's MQTT topics (spec section 11) and prints it, or shows it full screen. It is a starting point for your own scoreboard: an LED panel, a TV, a speaker that calls out captures.

```sh
sudo apt install python3-paho-mqtt          # or: pip install paho-mqtt
python3 scoreboard.py --host <controller-ip>
python3 scoreboard.py --host <controller-ip> --curses
```

```
game 4242: red 0 · blue 0
game 4242 00:04 zone.captured node 7 red
game 4242: red 30 · blue 0
```

| Option | Meaning |
| --- | --- |
| `--host`, `--port` | The controller's Mosquitto broker (default `localhost:1883`, plain MQTT, which only the controller's own machine can reach; from the field's network use port 8883 with `--cafile`) |
| `--cafile ca.pem` | Connect over TLS, trusting the field CA alone (the console's Check-in tab and `GET /api/v1/controller/ca` give it): `--host 10.42.0.1 --port 8883 --cafile ca.pem --username reader --password <read token>` |
| `--username`, `--password` | With the broker set up as in [`controller/deploy/`](../../controller/deploy/), log in as the read-only user |
| `--game ID` | Follow one game only (default: every game) |
| `--curses` | A full-screen board instead of one line per change (`q` quits) |
| `--once` | Exit after the first score (for scripts) |
| `--timeout S` | Give up after S seconds without a score |

It subscribes to `field/v1/+/score` (retained, so the current score arrives at once) and `field/v1/+/events/#`, and never publishes. It works with paho-mqtt 1.6 (Debian, Raspberry Pi OS) and 2.x.

The controller also serves a read-only scoreboard **web page** for a screen at the safe zone: `https://<controller>:8443/scoreboard#token=<read token>` (plain `http://…:8080` works for this read-only page too; see [controller/console/README.md](../../controller/console/README.md)).

Tested in `controller/tests/test_scoreboard_example.py`: the controller's MQTT bridge publishes to a private Mosquitto and this program prints what it receives.
