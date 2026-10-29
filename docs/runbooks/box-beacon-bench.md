<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Runbook: the Field Box as an iBeacon, on the bench

Decisions **BBC-1 to BBC-12**, [protocol/box-beacon.md](../../protocol/box-beacon.md), RFC 0001 Amendment 20. A Field Box joined to a game advertises a standard iBeacon; the controller registers it from the box's place on the field view; a phone that hears it is placed there. **Built and host-tested; nothing here has run on a board or a phone yet.** This runbook is the check to run on the Heltec V4.3 boards and an Android phone, in order, and what to write down. Do the steps in order: each one needs the one before.

What the host tests already cover (do not repeat): the advertisement bytes and the UUID against vectors made from `hashlib`, the phases in which a box advertises (join, play, pause, end, reboot, key 19), the join's key 19 in the three codecs, the controller's registration, moves, level changes, disabling and the field switch, both controllers against one contract case, and the phone's filter and parse of a box's real bytes. What only a board can say: that the Bluetooth stack **starts in the memory that is left**, **advertises what the tests say**, **stops again**, **does not disturb the LoRa link**, and **is heard by a phone often enough**.

## What you need

- A Field Box board (Heltec V4.3) with its **LoRa antenna fitted**, adopted to the bench controller's field; a second box and the USB modem if you want the radio check in step 7.
- The controller of this branch (the bench controller in `~/atalaia-bench-ctl`, rebuilt from the branch: restart it after updating, it serves the console from the repository), with the field's join key as the boxes hold it.
- An Android phone with **nRF Connect** (Nordic's free scanner) and, for step 6, the Atalaia app built from the branch, joined to the same game as a player.
- The image: `python3 tools/docker_fw.py build` (a Field Box; `--region` as the bench's). `docker_fw.py bench` has the beacon too (it is built on the same defaults). The serial console at 115200 baud (the box's USB port) for the log lines below.

Not on the list, on purpose: do **not** use the Wokwi build (no Bluetooth radio, the beacon is built out) or the USB modem (it never advertises).

## 1. The box starts the Bluetooth stack

1. Flash the image, restart the box, join a game from the console (an invite, a card or `@join ...`). If the box has the field Wi-Fi set (for the logo), it fetches the logo first; **the beacon starts after the fetch** (the Wi-Fi driver and the Bluetooth controller share the internal RAM), up to about the Wi-Fi timeout after the join, and at once if there is no Wi-Fi or no logo.
2. On the serial console read, in this order:

   ```
   box-beacon: Bluetooth controller up: internal RAM <A> bytes free (took <B>)
   box-beacon: advertising as iBeacon <UUID> 45253:<node> every 500 ms
   ```

   **Write down A and B.** B is what the controller takes of the internal RAM while it runs (released when it stops); A is what is left. The Wi-Fi driver logged "DMA-capable RAM ... free" before it started in the same run: **a logo that does not appear, or "Wi-Fi driver did not start" after a beacon, is a RAM failure** (the Wi-Fi driver once needed all of 47 KB of it): write the numbers down and report it. `Bluetooth controller failed to start (...)` is the same kind of failure for the beacon: the box plays on without it.
3. Static internal RAM grew by about 25 KB in the image (`idf.py size`: DIRAM 270,880 to 296,024 bytes, 45,736 left); the memory monitor logs the heap every 10 s: note whether the lowest free internal RAM in a game with the beacon on is below the same game with it off (the field's switch, step 5).

## 2. A phone sees what the tests say

1. In nRF Connect scan; find the box (an unnamed device whose advertising data is the manufacturer data of **Apple, 0x004C**, `02 15 ...`; nRF Connect shows it as an iBeacon with UUID, Major and Minor).
2. Check against the controller: **UUID** is the one the console shows (`GET /api/v1/beacons`, GM token: `box_beacons.uuid`), **Major 45253** (`0xB0C5`), **Minor** the box's node id in the game (the Join tab / `GET /api/v1/nodes`). The raw advertisement is 30 bytes: compare with `python3 -c "from atalaia_controller.box_beacons import adv_bytes; print(adv_bytes(bytes.fromhex('<join key>'), <node>).hex())"` from `controller/`.
3. Advertising details: **non-connectable**, **interval about 500 ms** (nRF Connect shows the interval; the advertisement arrives twice a second), signal about -40 to -50 dBm at 1 m at 0 dBm. Write the RSSI at 1 m, 5 m and through one wall.

## 3. When it advertises, and when it stops

With nRF Connect scanning all the time, and the serial log open:

| Do | Expect |
| --- | --- |
| The box joins (before the game starts) | Advertising starts (after the logo's fetch, if any). |
| The game starts, pauses, resumes | Advertising goes on all through. |
| The game ends (CMD end) and the last events are acknowledged | `box-beacon: iBeacon stopped`; the box vanishes from the scan within a second. |
| Between games (the box is idle, "Ready") | Nothing advertised. |
| The box reboots in a running game | It comes back into the game and advertises again. |
| An update is offered while the box is joined, not playing (`@update` or the console) | The beacon stops while the Wi-Fi is in use and starts after it (or the box reboots into the new image). |

## 4. The console registers it by itself

1. Open the console, **Field** tab: under **Indoor beacons**, **Field Boxes as beacons**: *no box is placed on a plan yet* (a box not placed has no level or place).
2. Place the box on the field view (drag its marker, or the level select under the plan on a multi-story field). It appears at once as a **Field Box** with id `45253:<node>`, its room (the box's name, or the scenario's name for it), its level. No pin on the plan: the box's own marker is its place.
3. Move it: the beacon follows (`GET /api/v1/beacons`, GM). Change its level: so does the beacon's level.
4. **Room**: give it "Cave"; the list says Cave; clear it and the box's name is back. **Disable** it: a phone's report of it is refused (step 6) and every other token's list (`GET /api/v1/beacons` with the read token) no longer has it. Enable it again.

## 5. The field's switch (join key 19)

1. Untick **The Field Boxes advertise as beacons**. The registry stops listing the boxes at once (read token). The box in the live game **keeps advertising** (it was told at its join): that is expected.
2. End the game and make the next one (a new join for the box): the join now carries key 19 = false; the box joins and **does not advertise** (nothing in nRF Connect, no `box-beacon:` line).
3. Tick it again, make another game: the beacon is back.

## 6. A phone is placed by it, with the app

1. Game running, the box placed (step 4), the app joined as a player and sharing its position (it asks for Bluetooth scanning first: agree).
2. Stand at the box: the app shows **Your position: <room>**, the console's positions (`GET /api/v1/positions`, GM) say the room, level and place (`x`, `y`) of the box, and ATAK (if on) puts the player at the box's place on its level's plan.
3. Walk away out of range for two beacon intervals: the position goes back to GPS. Come back: the box again.
4. **The hit rate, the number to write down**: stand 1 m, then 5 m from the box for 5 minutes each; the app's beacon reading (the reporter's log, or the positions' timestamps every 5 s) is expected in nearly every window. A box at 500 ms was chosen so an Android low-power scan (about 0.5 s listening in every 5 s) holds an advertisement in nearly every window: write down the fraction of 5 s windows with a reading. If it is well under 90 % at 1 m, say so: the interval (Kconfig `ATALAIA_BOX_BEACON_INTERVAL_MS`) is the thing to change.
5. Put a tag (an iBeacon the GM registered) in another room: both are beacons of the registry, the strongest wins.
6. **Disable the box** in the console: the app's next reading is refused (the controller answers 400; the phone drops back to GPS or the tag). Enable it: it works again.

## 7. The LoRa link is not disturbed

This is the coexistence check. Two boxes in a game with the controller's modem, the same game twice, ten minutes each, **beacon on** (the default) and **beacon off** (switch off as in step 5, new game): compare the controller's heard-STATE rate per box, the ACK latency and the missed-frame counts (`GET /api/v1/nodes`, the radio stats: `docs/runbooks/radio-field-test.md` has the method) and the box's `radio_stats` line. Expected: no difference. The two radios are different (868 or 920-925 MHz, and 2.4 GHz), so a difference would mean the Bluetooth host's CPU load or an interrupt: write it down.

## 8. Power

Optional: the same box, the same game, on a USB power meter or the battery gauge (`battery_pct` over an hour), beacon on and off. Two short advertisements a second at 0 dBm are expected to cost very little; the Bluetooth controller's idle current while it runs is the number to learn.

## What to send back

The A and B of step 1 (internal RAM free and taken), whether the logo and the beacon both came up in a game with the field Wi-Fi set, the RSSI figures of step 2, the interval nRF Connect shows, the hit rate of step 6, the radio comparison of step 7, and anything that surprised you. If the box could not start the Bluetooth controller in a game with the Wi-Fi in use, the way out is Kconfig `ATALAIA_BOX_BEACON=n` (and `CONFIG_BT_ENABLED=n`): tell the maintainer before building that.
