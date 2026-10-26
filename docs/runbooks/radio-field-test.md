<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Runbook: the radio field test (decision SL-18)

The relay study ([relay-study-results.md](../review/relay-study-results.md)) is a model; this is how to measure the real radio. A Field Box logs its radio counters once a minute on the serial port, `tools/bench_radio_log.py` turns the log into a table and a summary, and the study's numbers say what to expect. Nothing here changes what the radio does: the box only reads its counters and the duty-cycle budget and writes a line.

## What the box logs

While a game is on the box (joined, playing or paused), once a minute and once more when the game ends, one line on the serial port (USB-C, 115200 baud), tag `radio_stats`:

```
I (123456) radio_stats: {"t_s":120,"game":4243,"node":7,"sent":9,"retries":31,"acked":2,"expired":1,"relayed":140,"relay_skipped":12,"relay_cancelled":3,"relay_no_slot":4,"dup":77,"tx_refused":5,"duty_remaining_ms":359900,"neighbours":4,"rx":300,"rx_rejected":6,"states":40,"hellos":8,"final":0}
```

All counters are cumulative since the box joined the game. `sent`: events sent for the first time; `retries`: resends of them; `acked`: events acknowledged; `expired`: events given up; `relayed`, `relay_skipped`, `relay_cancelled`, `relay_no_slot`: Amendment 13's rules at work; `dup`: duplicates heard; `tx_refused`: frames the duty-cycle budget refused; `duty_remaining_ms`: budget left on the game channel's sub-band (-1 if unknown; a full EU868 budget at 10 % is 360 000); `neighbours`: boxes heard in the last 10 minutes; `final` is 1 on the line that closes a game. The format is pinned by `firmware/esp32/test/test_radio_stats.c`.

The **USB modem** logs the same kind of line (`"role":"modem"`: `rx_ok`, `rx_dropped`, `rx_auth_fail`, `rx_dupes`, `tx_ok`, `tx_fail`, `field_rx`, `field_tx`, `duty_remaining_ms`) once a minute while a game is configured, but on its UART0 log console only: its USB port carries the controller's frames and never logs. On the bench COM4 is owned by the bridge (`com_bridge.py`, [tools/serial_bridge.py](../../tools/serial_bridge.py)), so there is no modem line to read there; the modem's counters come from the controller's STATUS replies (`duty_ms`, `rx`, `tx`, `tx_fail`, [usb-modem.md](../../protocol/usb-modem.md)). If a UART0 adapter is on the modem, record it to a file and give that file to the tool as well.

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

## When something looks wrong

- No `radio_stats` line after a minute in a game: the box is not in a game (a joined box that is idle still logs; a box in the lobby does not), or its firmware predates this change (check the boot log's version).
- `duty_remaining_ms` is -1 or 0 from the start: the radio task has not read the budget yet, or no radio is present.
- The tool says "no radio_stats lines": the log is another port's (the modem's COM4 carries frames), or the box was reset and the log starts after the game's first minute.
- A counter that goes down is a reboot: the tool starts a new run for it.
