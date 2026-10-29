<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Runbook: a channel change and a game start, on the two boards

RFC 0001 **Amendment 19** (decisions RB-1 to RB-12 in the report of that work; the two findings of the bench of 2026-10-29). This runbook checks, on the two real Heltec V4.3 boards, that:

1. **a change of the field's channel does not lose a free box** (part 1: MOVE): a box idle between games follows the controller to the new channel, keeps it over a reboot, and a box that was away is found again by *Find boxes*;
2. **a started, paused or resumed game reaches a joined box in about a second** (part 2: the state is repeated as TIME at +1, +2.5, +5 and +10 s), also when the first frames are lost.

Status: built and tested in software (the core, the box's own code in the host box, both controllers, the shared vectors); **not yet run on air**. Nothing here is transmitted by the build or the tools: the run is the coordinator's, on the bench, with the antennas fitted. The agent that built this did not touch the boards.

## What you need

- The two boards of the other bench runs ([lbt-bench-gate.md](lbt-bench-gate.md), [projected-score-bench.md](projected-score-bench.md)): board 1 (COM3) a **Field Box**, board 2 (COM4) the **USB radio modem**, both with their LoRa antennas fitted, 1-2 m apart. Never transmit without an antenna.
- **The box needs this commit's image** (the MOVE and the reconcile are firmware); the modem needs nothing new (it carries MOVE as it carries any field frame; `IDENT` says `"field": true`). Build the bench image, which has the serial keys and `@hold <button> <ms>`:

  ```sh
  python3 tools/docker_fw.py bench      # -> firmware/esp32/build-bench/  (board 1, EU868)
  ```

  then copy `flash_args`, `atalaia_esp32.bin`, `ota_data_initial.bin`, `bootloader` and `partition_table` to the Windows bench folder and flash with `esptool ... write_flash @flash_args` as in [lbt-bench-gate.md](lbt-bench-gate.md) step 1. Flash **without erasing** (the box keeps its adoption and join key). Use `--region=eu868` (the default).
- **The bench controller running this commit's code** (`atalaia-controller-bench`, config in `~/atalaia-bench-ctl/`; restart the container: it serves the repository from `/src`) and the Windows `com_bridge.py COM4 7600` path to the modem. `python3 ~/atalaia-bench-ctl/bench.py get /controller` must say `radio: up`; its `modem.ident` must have `"field": true`.
- The GM token in `~/atalaia-bench-ctl/.gm_token`; `bench.py get|post|put <path> [json]` talks to the controller with it. The box on its USB serial console (the Windows COM3 terminal): it prints its log lines and takes `@lobby`, `@join <text>`, `@hold <button 1-4> <ms>`.
- A box that is already adopted to the field (it has the field join key) and has **played one game to its end** (so its last game's channel is 869.525 MHz and it is free). Any bench game will do: make one with the box as its only node, start it, end it.

## Duty cycle

The whole of part 1 costs 0.27 s of air on the old channel (three MOVEs) and 0.18 s on each remembered channel of a sweep: under 0.01 % of an hour on 869.525 MHz (10 %) and 0.75 % of the budget of 869.925 MHz (1 %, 25 mW). Part 2 adds four TIMEs (0.36 s) per start, pause or resume. Nothing in this runbook comes near a limit; the modem's duty-cycle guard still applies (a refused frame shows as `duty_cycle` in `bench.py get /controller` `tx_status`).

## Part 1: a change of channel with a box idle

Channel 869.925 MHz (the one the scan chose on 2026-10-29) is in the 1 %, 25 mW sub-band; the boards' power cap for it is set by the firmware for that sub-band as for any channel.

1. **Before.** On the box: `@lobby`. It must say `free for an invite`, `channel 869525000 Hz`, `field move revision 0 (0 taken, 0 refused)` (or a revision from an earlier try). On the controller: `bench.py get /boxes` lists the box within about a minute of its last announcement (`bench.py post /boxes/discover` makes it answer at once).
2. **Change the channel** (no game may be live; end any game first):

   ```sh
   cd ~/atalaia-bench-ctl
   python3 bench.py put /radio/channel '{"channel_hz": 869925000, "source": "manual"}'
   ```

   The answer has `"previous_channels_hz": [869525000]`. The controller log (`docker logs -f atalaia-controller-bench`) says `the field moves from 869525000 to 869925000 Hz (revision N): MOVE on the old channel`. The modem stays on 869.525 MHz for about 5 s (its screen shows the channel), then moves to 869.925 MHz and a DISCOVER goes out there.
3. **The box follows**, within about 5 s of the change: its serial log says `the field moved to 869925000 Hz (revision N)`, and `@lobby` now says `channel 869925000 Hz` and `field move revision N (1 taken, 0 refused)`. Within 15 s of the MOVEs it announces itself again (it answers the DISCOVER on the new channel at once): `bench.py get /boxes` lists it again.
   - **FAIL if** the box stays on 869.525 MHz: check the box runs this commit's image (`@lobby` has the `field move revision` text), the modem IDENT has `field: true`, and the controller log has the `MOVE on the old channel` line.
4. **The finding itself.** Make a game on the new channel (`bench.py post /games ...` as in [projected-score-bench.md](projected-score-bench.md) step 1) and **invite the box from the console's box list** (or `bench.py post /games/<id>/invites '{"boxes": [{"device_id": "<hex from /boxes>", "role": "zone"}]}'`). It must join ("Invited / game: role" on its screen; `joined` in `bench.py get /games/<id>/invites`). Before this fix the invite was never heard. Start the game, end it.
5. **A reboot keeps the channel.** With the box idle on 869.925 MHz, reset it (the RST button, or unplug and plug the USB cable). `@lobby` after the boot: `channel 869925000 Hz` (not 869525000) after the first second, and `bench.py post /boxes/discover` brings it back into the list.
6. **The scan case.** Set the channel back (`... {"channel_hz": 869525000, "source": "manual"}`), wait for the box to follow, then start a scan from the console (*Definições / Settings*, "Find a quiet channel") and accept whatever it suggests: the box follows the accepted channel as in step 3. (The scan itself does not move the field: only accepting does.)
7. **A box that was away.** With the box on the field's channel, **switch the box off** (unplug its USB power). Change the channel (step 2, to a channel the box is not on). Switch the box on: its `@lobby` says the old channel (it never heard the MOVE). On the controller: `bench.py post /boxes/discover`. The answer must be `{"sent": true, "sweep": [<the old channel>]}`: four seconds later a MOVE goes out twice on the old channel (the modem retunes there and back), then a DISCOVER on the field's channel. The box's log says `the field moved to ...` and it is listed again within about 20 s. A second *Find boxes* within a minute answers `"sweep": []`.
8. **Leave the bench as it was**: set the channel back to 869.525 MHz and let the box follow.

Record: the box's `@lobby` before and after, the time from the `put` to the box's `the field moved` line, and the `sweep` answer of step 7.

## Part 2: a game start (and pause, resume) with the first frames lost

The finding: the box logged `game N started` about 21 s after the GM pressed Start (box log time 58516 ms against a serial command at 37380 ms right after the press). The cause is that the start went out as one CMD and one TIME, each once, and the next TIME is 30 s away in manual failover; now the state is repeated as TIME after 1.0, 2.5, 5.0 and 10.0 s.

1. **Normal start.** Make a game with the box as its only zone, join the box (`@join` or an invite), then start it from the console and watch the box's serial log: `game N started (node M, zone)` must appear **within about 0.5 s** of the press (the CMD and the TIME arrive at once). Note both times.
2. **With the first frames lost.** The box must not hear the start's first two frames and must hear the repeats. Put the **box** (board 1) inside a closed metal tin, or wrap it in kitchen foil, **with its antenna**, press Start in the console, and take the foil off after one second. (Do not disconnect the modem's antenna: transmitting without one can damage the radio; hiding the *box* is safe.) The box must log `game N started` **about 1.0-2.5 s after the press** (the +1.0 s or the +2.5 s TIME), not 30 s. Repeat three times; with the foil off after 3 s the start comes at the +5 s repeat.
   - The box's `radio_stats` line (every report period, in a game) counts `rx`: it rises by one for every frame heard, so the repeats show as extra frames.
   - **FAIL if** the start comes at about 30 s: the controller is not running this commit (`bench.py get /controller` should show the controller restarted after the merge; the repeats are in `simulator/atalaia_sim/field_controller.py`, `STATE_REPEAT_GAPS_MS`).
3. **Pause and resume the same way.** Press Pause in the console with the box covered for one second: the box's screen shows the paused state within about 1-2.5 s; then Resume with the box covered for one second: it resumes within the same time. A start's repeats must **never** undo a pause: press Pause 2 s after Start, and the box must stay paused (the later TIMEs say `paused`).
4. **A fetching box** (optional, needs a box without a mode of the game: [mode-packages.md](../../protocol/mode-packages.md)): invite it with *fetch missing modes* and start the game while it is still fetching; when its fetch ends it must start the game by itself (the box's tick: `the game is already running: starting`), where before it stayed on its waiting screen until the end.

Record: the time from the press to `game N started` in steps 1 and 2 (three runs each), and whether a pause held.

## Expected results (software)

| Check | Expected |
| --- | --- |
| Step 3 of part 1 | The box on the new channel within about 5 s, listed again within 15 s |
| Step 4 of part 1 | The invite is heard and the box joins |
| Step 5 of part 1 | The idle channel is the new one after a reboot |
| Step 7 of part 1 | The sweep brings an away box back, once a minute at most |
| Step 1 of part 2 | Started in under 0.5 s |
| Step 2 of part 2 | Started in 1-2.5 s with the first frames lost (30 s before) |

The same checks run in software: `python3 tools/docker_fw.py test` (`test_lobby_move`, `test_state_change_by_time_alone`), the controller's `tests/test_reinvite.py` (`MoveTests`), `tests/test_box_e2e.py` (a start, a pause and a resume with the first CMD and TIME dropped, under two seconds) and the simulator's `tests/test_move_sim.py`.
