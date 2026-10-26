<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Runbook: the radio field test (decision SL-18)

The relay study ([relay-study-results.md](../review/relay-study-results.md)) is a model; this is how to measure the real radio. A Field Box logs its radio counters once a minute on the serial port, `tools/bench_radio_log.py` turns the log into a table and a summary, and the study's numbers say what to expect. Nothing here changes what the radio does: the box only reads its counters and the duty-cycle budget and writes a line.

## What the box logs

While a game is on the box (joined, playing or paused), once a minute and once more when the game ends, one line on the serial port (USB-C, 115200 baud), tag `radio_stats`:

```
I (123456) radio_stats: {"t_s":120,"game":4243,"node":7,"sent":9,"retries":31,"acked":2,"expired":1,"relayed":140,"relay_skipped":12,"relay_cancelled":3,"relay_no_slot":4,"dup":77,"tx_refused":5,"duty_remaining_ms":359900,"neighbours":4,"rx":300,"rx_rejected":6,"states":40,"hellos":8,"lbt_cads":210,"lbt_deferrals":35,"lbt_gave_up":2,"final":0}
```

All counters are cumulative since the box joined the game. `sent`: events sent for the first time; `retries`: resends of them; `acked`: events acknowledged; `expired`: events given up; `relayed`, `relay_skipped`, `relay_cancelled`, `relay_no_slot`: Amendment 13's rules at work; `dup`: duplicates heard; `tx_refused`: frames the duty-cycle budget refused; `duty_remaining_ms`: budget left on the game channel's sub-band (-1 if unknown; a full EU868 budget at 10 % is 360 000); `neighbours`: boxes heard in the last 10 minutes; `lbt_cads`, `lbt_deferrals`, `lbt_gave_up`: listen before talk's counters ([below](#listen-before-talk-on-and-off)); `final` is 1 on the line that closes a game. The format is pinned by `firmware/esp32/test/test_radio_stats.c`.

The **USB modem** logs the same kind of line (`"role":"modem"`: `rx_ok`, `rx_dropped`, `rx_auth_fail`, `rx_dupes`, `tx_ok`, `tx_fail`, `field_rx`, `field_tx`, `duty_remaining_ms`, and the same three `lbt_` counters) once a minute while a game is configured, but on its UART0 log console only: its USB port carries the controller's frames and never logs. On the bench COM4 is owned by the bridge (`com_bridge.py`, [tools/serial_bridge.py](../../tools/serial_bridge.py)), so there is no modem line to read there; the modem's counters come from the controller's STATUS replies (`duty_ms`, `rx`, `tx`, `tx_fail`, [usb-modem.md](../../protocol/usb-modem.md)). If a UART0 adapter is on the modem, record it to a file and give that file to the tool as well.

## Bench: one box (COM3) and the modem (COM4)

1. Flash the bench box with a build that has the log (`python3 tools/docker_fw.py bench`, then flash as usual). Leave the modem as it is: the controller's bridge keeps COM4.
2. Start a game with the one box from the GM console and let it run. Record the box's port **without opening it in another program** (the monitor, `bootlog.py` and the flasher hold it) and without resetting it. In PowerShell, from the repository, with the flasher's Python (it has pyserial):

   ```
   %USERPROFILE%\atalaia-flash\Scripts\python.exe tools\bench_radio_log.py --port COM3 --minutes 90 --tee %USERPROFILE%\atalaia-bench\radio-bench-1.log
   ```

   The tool opens the port without raising DTR or RTS (which would reset the board), reads for 90 minutes (Ctrl+C stops it earlier and still prints) and saves the raw bytes. Or record with any logger and read the file afterwards:

   ```
   python tools/bench_radio_log.py radio-bench-1.log
   ```
3. Read the output: per-minute deltas, then the summary. For one box the study has no row (it starts at 5 boxes), so the tool says what to compare with: acked close to 100 %, retries per event well under 1, `tx_refused` 0, `relay_no_slot` 0, and about 0.7 % airtime (SL-4's arithmetic: 0.68 % per box). The airtime estimate comes from the duty budget's fall in the first hour (the budget is a sliding hour: after 60 minutes it stops draining). **This first run is the baseline for the field.**
4. The modem side: in the GM console's modem status, or the controller's log, note `tx_fail` and `duty_ms` at the start and the end.

## Field: 5 boxes, then 10 boxes, 90 minutes each

1. Every box is a build with the log. All boxes in range of each other and of the controller, as the study's "all in range" layout (a park of about 50 m), EU868 for the first run. Play Domination, as the study did (about 0.33 capture attempts per box per minute).
2. Plug a laptop into each box (or two or three boxes into one laptop, one process per port) and run, per box:

   ```
   python tools/bench_radio_log.py --port COM5 --minutes 90 --tee box-07.log
   ```

   Start them all before the game starts, so that the first lines are in. Leave the USB cable on for the whole 90 minutes; unplugging a box is a measurement lost, not a result.
3. After the game, read all the logs together; the tool groups by node and game, and takes the number of nodes in the logs as the field size (or give `--boxes 5`):

   ```
   python tools/bench_radio_log.py box-*.log --boxes 5
   ```

   (Several files are fine; `-` reads standard input.)
4. Compare. **What the model predicts** (EU868, all in range, Domination, 90 minutes, medians of three seeds; [study, section 6](../review/relay-study-results.md)), per box:

   | boxes | the link before Amendment 13 | the built rules (what the boxes now run) |
   | --- | --- | --- |
   | 5 | 10.4 % airtime, 18.7 % of captures ACKed, 385 frames refused | 2.9 %, 100 % ACKed, 0 refused |
   | 10 | 11.0 %, 10.3 % ACKed, 301 refused | 2.7 %, 100 % ACKed, 0 refused |

   The boxes of a field test run the built rules, so the right column is the prediction: `tx_refused` 0, `relay_no_slot` 0, acked above 90 %, retries per event low (resends are for lost frames, and back off at 3, 6, 12, 24, 30 s), the budget draining at about 1.7 s a minute (2.9 % of airtime at 5 boxes; 1.6 s at 10) until the first hour is full, then flat. A box that shows the left column (refusals, ACKs under 30 %, a budget spent by minute 40) is running the old link, or the model is wrong. **If the boxes report something else, the model is wrong in the first place to look at** (SL-18): the capture rule, the link budget and the clocks are the assumptions most worth varying.
5. Keep the logs with the date, the number of boxes, the layout and the firmware version (`fw_version` is in the boot log). They are the data for the next revision of the study.

## Listen before talk, on and off

The boxes (and the modem and the pod) listen before they talk: before every transmission the radio asks whether a frame is on air (the receiver's own preamble and header flags, then one CAD), holds the frame 20-200 ms if so, asks again, and after 8 busy answers in a row sends it anyway ([RFC 0001 Amendment 14](../rfcs/0001-skirmesh-rf-wire-format.md), decisions SL-25 to SL-37). It is on by default (Kconfig `ATALAIA_LBT`). The 20-box field test is where the model's claim is checked: **the same field, the same game, once with it on and once with it off**.

**Switching it.** Only at build time: the controller cannot push it (that would be a new join key and a wire change; decision SL-33). Build the same commit twice, into the folders the flasher uses, and flash all 20 boxes (and the modem) with one build, then all with the other:

```
python3 tools/docker_fw.py build --lbt=on     # the default
python3 tools/docker_fw.py build --lbt=off    # the same firmware, no CAD, no waiting
python3 tools/docker_fw.py modem --lbt=off    # the modem's image, if it is to match
```

A build says which it is in its first lines (`docker_fw: radio region eu868, listen before talk on`), and the log says it too: a box with it off logs `"lbt_cads":0,"lbt_deferrals":0,"lbt_gave_up":0` all game and the tool prints "no CAD, no deferral (switched off in this build, or nothing sent yet)". Mixed fields work (a box with LBT yields to a box without, not the other way round) but compare nothing: flash all 20 alike for each run. **Take the controller's modem into the same state as the boxes**: the model's controller listens before it talks too (it is a node of the model), so a run "off" has to turn it off as well.

**The two runs.** 20 boxes, all in range of each other, EU868, Domination, 90 minutes each, the same park and the same teams, on the same day if the weather allows; the order alternates between field days (on-off on one day, off-on on the next) so that neither the hour nor the battery state decides. Record, per run, every box's log (`--port` ... `--tee box-NN-on.log`) and the controller's log.

**What to read.** `tools/bench_radio_log.py box-*-on.log --boxes 20` and the same for `-off`. Per box the summary now has a line

```
listen before talk: 900 CADs, 180 deferrals, 3 frames sent after 8 tries; 0.73 waits per frame sent (248 frames)
  CADs per hour 1080 (inside the study's 850-1500 a box-hour in a field of 10-30; a CAD is 8 ms on the bench, so 0.24 % of the hour listening)
```

and the model's prediction for 20 boxes in a mesh on EU868 (study, [section 13](../review/relay-study-results.md); medians of three seeds, the built transmit path on the hardware's timing):

| | LBT off | LBT on |
| --- | --- | --- |
| STATEs the controller hears | 65 % | 89 % |
| captures ACKed | 99.7 % | 99.7 % |
| a capture's latency, p95 | 3.4 s | 1.4 s |
| airtime per box, mean | 2.6 % | 2.9 % (worst box 3.1 %) |
| CADs per box-hour | 0 | about 1 050 (one per frame sent, a few more when it finds the air busy) |
| frames sent after 8 tries, per box-hour | 0 | **84** (8 % of the frames: a frame that finds the channel busy 8 times in a row goes anyway; 15 / 254 at 10 / 30 boxes in a mesh, 35 at 20 boxes in CQB, 4 in a long field) |

What would be a result: **the STATEs the controller hears** and **the capture latency's p95** are the two numbers LBT is built to move (read them from the controller's log: STATEs per box per minute against the 4 a minute a box sends; the capture's event time against the controller's receipt). On the boxes: `lbt_deferrals` about two per frame sent in a mesh of 20 (a frame waits twice on average: about 2 000 waits a box-hour), `lbt_gave_up` about 84 a box-hour (8 % of about 1 050 frames; it is a crowded channel, 20 boxes at 2.9 % of airtime each hearing one another keep it busy more than half the time, and the frame goes anyway), airtime up by 0.3 point and `tx_refused` still 0. What would say the model is wrong: no gain in STATEs heard (hidden nodes the layouts do not have: boxes that cannot hear each other), `lbt_gave_up` several times the table's for the field's size and layout (the channel is busy for a second and a half at a time with more traffic than the boxes make: something else is on it, look at the noise scan; a field of 5 boxes should show almost none), or `lbt_cads` far above 1 500 an hour (a CAD that false-detects; a CAD is believed only when it detects a LoRa preamble, but a neighbour network on the same channel would do it).

**AS923-TW boxes.** The CAD's detection peak there (23 at SF9/500 kHz) is Semtech's figure and has not been checked on a board: run the bench gate ([lbt-bench-gate.md](lbt-bench-gate.md)) on an AS923-TW image before trusting a Taiwanese field's LBT numbers, or build that field with `--lbt=off`.

## When something looks wrong

- No `radio_stats` line after a minute in a game: the box is not in a game (a joined box that is idle still logs; a box in the lobby does not), or its firmware predates this change (check the boot log's version).
- `duty_remaining_ms` is -1 or 0 from the start: the radio task has not read the budget yet, or no radio is present.
- The tool says "no radio_stats lines": the log is another port's (the modem's COM4 carries frames), or the box was reset and the log starts after the game's first minute.
- A counter that goes down is a reboot: the tool starts a new run for it.
- `lbt_gave_up` high: frames waited 8 times and went anyway, so the channel stayed busy for 1-1.6 s each time. In a crowded field that is the game's own traffic (about 8 % of the frames at 20 boxes in a mesh, 25 % at 30: the table above); in a small one it is another network on the channel (a CAD or a header flag from a frame that is not the game's): scan the channel (the modem's MEASURE) and look at `lbt_cads` for the same box.
