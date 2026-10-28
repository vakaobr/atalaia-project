<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Runbook: the projected score on the bench

Decisions **SL-6** and **BSC-2** ([decisions-to-review.md](../review/decisions-to-review.md); contract in [modes/README.md](../../modes/README.md#projected-score-scoring-optional)). A mode that says how a box scores while it holds (`scoring.hold` in its `mode.yaml`: Domination) gets a **projected** total on the controller between two STATEs: the last reported total plus the scoring ticks a held box has made since. This runbook measures, on two real Heltec V4.3 boards, **how far the projection is from the score each box really reports in its next STATE** (the drift), and whether the console shows it as an estimate.

Status: built and tested in software (core, both controllers, shared contract case); **the bench run is pending**: nobody has run it on a board. **Nothing here is transmitted by the build or the tools**: the run is the maintainer's or the coordinator's, on the bench, with the antennas fitted.

## What you are checking

- **The projection moves between STATEs.** With one box holding for red in a Domination game (`tick_s` = 10, `points_per_tick` = 1), the console's red total shows a grey "estimated N" that goes up by 1 every 10 s, while the official number goes up only when a STATE arrives (every 15 s).
- **A STATE replaces it.** After each STATE the estimate equals the official number (or is at most one tick ahead for a moment: see "What to expect").
- **It never becomes the record.** `GET /api/v1/games/{id}/score` has `teams` (official, reports only) and `projected` (estimate); MQTT's `.../score`, the stored totals and the final result are the reports.
- **The drift is small.** The controller writes one line per STATE of a box that was holding: projected, reported, the difference. `tools/bench_projected_score.py report` turns them into a table and a PASS or FAIL.

## What you need

- The two boards of the other bench runs ([lbt-bench-gate.md](lbt-bench-gate.md), [radio-field-test.md](radio-field-test.md)): board 1 (COM3) a **Field Box**, board 2 (COM4) the **USB radio modem**, both with their LoRa antennas fitted, 1-2 m apart.
- The bench controller (`atalaia-controller-bench`, config in `~/atalaia-bench-ctl/`) **running this commit's controller code** (restart the container after the merge: it serves the repository straight from `/src`) and the Windows `com_bridge.py COM4 7600` path to the modem, as for every bench game. `python3 ~/atalaia-bench-ctl/bench.py get /controller` should answer `radio: up`.
- This commit's images are **not required for the projection itself**: a box's STATE is unchanged by it (the projection is the controller's), so the boxes you already run are fine. For the penalty check at the end (decision BSC-1) the Field Box needs this commit's image.
- A normal bench game's setup: the box adopted and joined as for any bench game, the controller's GM token in `~/atalaia-bench-ctl/.gm_token`.

If you do flash (to test the penalty counter too), as the other runbooks do, from the checkout:

```sh
python3 tools/docker_fw.py build     # -> firmware/esp32/build/       (the Field Box, EU868)
python3 tools/docker_fw.py modem     # -> firmware/esp32/build-modem/ (board 2)
```

then copy each folder's `flash_args`, `atalaia_esp32.bin`, `ota_data_initial.bin`, `bootloader` and `partition_table` to the Windows bench folder and flash with `esptool ... write_flash @flash_args` exactly as in [lbt-bench-gate.md](lbt-bench-gate.md) steps 1 and 2. Use `--region=eu868` (the default): a bench in Europe never transmits on 921.5 MHz.

## Duty cycle

The game's own traffic is a STATE every 15 s, a TIME beacon every 30 s and the ACKs: far under 1 % of the hour. Nothing in this runbook raises it.

## 1. Make the game

On the controller (a Domination game with the box as its only zone; a short tick makes the drift easier to see, so run the two settings in turn):

```sh
cd ~/atalaia-bench-ctl
python3 bench.py post /games '{"name": "projection", "mode_id": "org.atalaia.domination", "teams": ["red", "blue"], "assignments": {"<node id>": "zone"}, "params": {"tick_s": 10, "points_per_tick": 1}}'
```

Join the box as usual (the invite from the console, or `@join` on its serial console), open the GM console (`https://<pi>:8443/` or `http://127.0.0.1:8080/`), and check `GET /api/v1/games/<id>` shows `params.tick_s` 10. The mode list (`GET /api/v1/modes`) shows Domination with `scoring: {hold: {every: tick_s, points: points_per_tick}}`; if it shows `null`, the controller is not running this commit.

## 2. Run it (setting A: tick 10 s, 5 minutes)

1. Start the game from the console. Note the time.
2. On the box, hold the **red** button for the capture time (3 s): `zone.captured` goes out at once and a STATE with the new owner follows within a second.
3. In a second terminal start the recorder (it only reads the score every second; the token can be the read token):

   ```sh
   python3 tools/bench_projected_score.py poll --token "$(cat ~/atalaia-bench-ctl/.gm_token)" --seconds 300 --out projection-A.csv
   ```

4. Let it run **5 minutes with red holding** (about 20 STATEs), and watch the console's score card: the grey "estimated N" climbs by 1 every 10 s; the official number follows with each STATE. Do not touch the box.
5. Then do the **capture test**: at about 4 minutes, hold the **blue** button until the capture. The estimate may be one tick wrong for red or blue until the next STATE (a capture is sent at once, so it is usually corrected within a second): note whether it was.
6. **Pause and resume** once from the console: the estimate must disappear while paused (the score card shows no "estimated") and come back after the resume; the official number does not move.
7. End the game. The final result must equal the official number of the last STATE, never the estimate.

## 3. Measure the drift

The controller logged one line per STATE that compared the projection with the report:

```sh
docker logs atalaia-controller-bench 2>&1 | grep "projection node" > projection-A.log
python3 tools/bench_projected_score.py report projection-A.log --points 1
python3 ~/atalaia-bench-ctl/bench.py get /controller        # "projection": {samples, off, max_abs, sum_abs, last}
```

The report prints how many STATEs were compared, how many were off, the largest drift, the histogram and **PASS or FAIL**. The gate: **never more than one scoring tick (`points_per_tick`) off, and at most 20 % of the STATEs off.** The CSV (`projection-A.csv`: time, game time, team, reported, projected) is for the plot of the two curves; the staircase of the official score under the projected line is the picture to keep.

### What to expect

A box scores at game time k x `tick_s` and sends its STATE with its own game time T. The controller counts ticks up to **its** game time when the STATE arrives, which is the box's plus the air time, the relays and the clock offset between the two (the box follows the controller's TIME beacons, so a few hundred ms). A STATE sent just before a tick boundary therefore finds the projection **one tick ahead** for those few hundred ms: with `tick_s` = 10 s and about 0.3 s of offset, 3 % of the STATEs (the same fraction as offset / tick). That is the main source of nonzero drift, always +1 tick, and it is corrected by the STATE itself. A capture that the STATE has not yet carried gives at most one tick of the other sign. More than that means a STATE was lost (the next one repairs it) or the clocks are far apart.

## 4. Setting B: tick 2 s (measures the clock offset)

Repeat steps 1-3 with `"params": {"tick_s": 2, "points_per_tick": 1}` and 3 minutes. The share of STATEs that show +1 is now about offset / 2 s, so **offset = share x 2 s**: a share of 15 % is an offset of 0.3 s between the box's game time and the controller's. The gate is the same (never more than one tick off, at most 20 % off here; 20 % is an offset of 0.4 s). A larger share is a clock or a latency finding to write down, not a failure of the projection: tell the coordinator the numbers.

## 5. The penalty counter (decision BSC-1), if the box has this commit's image

With the Kill Confirmed mode and the box's `@tag` console command (no NFC reader needed: `@tag <uid hex> [<payload hex>]`, which takes a signed tag of the game as text: `firmware/esp32/test/test_box_game.c`'s `tag_text` shows how one is made), a confirmed kill penalises the tag's team by `penalty_points`:

1. Make a Kill Confirmed game with `penalty_points` 3 and join the box, start it, press red's button, then `@tag` an enemy tag of blue.
2. Within 15 s the console shows blue **3 lower** (official total, no "estimated") and `GET /api/v1/nodes` shows the box's `lost: {"red": 0, "blue": 3}`; `score.delta` is in the feed.
3. Reboot the box and wait for a STATE: blue stays 3 lower (the box's counters survive the reboot, the controller's merge is by maximum). Restart the controller container: blue stays 3 lower (the node's `lost` is stored).

## Results

Fill in (and send to the coordinator) for each setting: the date, the commit, the board and region, `tick_s`, the `report` output, the CSV, whether the console's estimate looked right at the capture, the pause and the end, and the penalty check. A copy of the log lines (`projection-A.log`) is enough to rebuild everything.

| Setting | STATEs | off | largest drift | share off | PASS/FAIL | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| A: tick 10 s | | | | | | |
| B: tick 2 s | | | | | | |
