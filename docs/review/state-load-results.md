<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# What a state change, a channel change and a sweep cost in air time (decisions RL-1 to RL-9)

[RFC 0001 Amendment 19](../rfcs/0001-skirmesh-rf-wire-format.md) (decisions RB-1 to RB-12, 2026-10-29) added frames that
the [relay study](relay-study-results.md) (decisions SL-7 to SL-37) never had: a start, pause or resume is repeated as TIME at
+1, +2.5, +5 and +10 s, a channel change sends MOVE three times, *Find boxes* sweeps the last four channels with two MOVEs
each (and, since RL-9, within an hourly air cap on small sub-bands). The Amendment said the study "does not model them". It does now: `simulator/atalaia_sim/relay_study.py` takes a
list of state changes (`Engine(state_changes=...)`, `Policy.time_repeat_gaps_ms`) and `simulator/atalaia_sim/state_load.py`
runs the same field and seeds with and without the repeats; `simulator/tests/test_state_load.py` pins the schedule and the
arithmetic. Every number below is the model's (the study's caveats, decision SL-18, apply); regenerate with

```sh
cd simulator && python -m atalaia_sim.state_load --sizes 5,10,20,30 --seeds 1,2,3,4,5     # a typical hour
cd simulator && python -m atalaia_sim.state_load --sizes 20 --seeds 1,2,3,4,5 --pause-pairs 10   # the stress hour
```

(in the dev container; about two minutes a size)

## 1. The frames (SF7 / 125 kHz, the project's own `airtime_ms`)

| frame | bytes on air | air |
| --- | --- | --- |
| TIME | 40 | 82 ms |
| CMD start / pause / resume (broadcast) | 24 | 62 ms |
| MOVE | 45 | 92 ms |
| **a state change as built**: CMD + TIME + 4 TIME | | **473 ms** (before Amendment 19: 144 ms) |
| of which the four repeats | | 329 ms (the RFC rounds a TIME to 90 ms: 0.36 s) |
| a channel change: 3 MOVEs | | 277 ms |
| a sweep: 2 MOVEs on each remembered channel | | 185 ms a channel, 739 ms for four |

Every box also relays each TIME with probability min(1, 3 / neighbours) (Amendment 13), so a field of N boxes puts
about 5 x 82 ms x min(N, 3) more frames on the channel for each change, spread over the boxes.

## 2. Per state change, for the 20-box field (all in range, EU868, the built transmit path `A_backoff_core_lbt_hw`)

* **The controller (the modem)**: 473 ms of its own air for each start, pause or resume. 329 ms of it is new.
* **A box**: it relays each of the five TIMEs with probability 3 / 20, so **about 0.04 s** of air per box and change (0.03 s
  at 30 boxes, 0.11 s at 10, 0.22 s at 5, where every box relays every TIME; the CMD's relay is in the baseline).
* **The channel** carries the 5 TIMEs, the CMD and their relays (about 20 x 0.15 x 5 = 15 relay frames): about 1.7 s of
  channel time for a change, spread over 10 s.

## 3. Per hour of a typical game

"Typical": a start and three pause / resume pairs in the hour (briefing, medic, break) = 7 state changes. "Stress": ten pairs
= 21 changes. Means of five seeds, 60-minute Domination, 20 boxes unless it says otherwise; "without" is the same field,
seeds and rules with the repeats off.

| | without | with the repeats | added |
| --- | --- | --- | --- |
| controller, TIME on air, s / hour (typical, 20 boxes) | 10.0 | 12.2 | **+2.2** |
| controller, share of the hour | 0.89 % | 0.96 % | +0.06 point |
| a box, mean airtime | 2.99 % | 3.00 % | +0.01 point (inside the seeds' noise) |
| a box, its TIME relays, s / hour | 1.44 | 1.75 | +0.31 |
| frames refused by a budget | 0 | 0 | |
| captures ACKed | 99.9 % | 99.8 % | noise |
| *stress, 21 changes:* controller | 0.92 % | 1.12 % | **+0.20 point, +6.7 s / hour** |
| *stress:* a box, its TIME relays | 1.47 | 2.37 | +0.90 s / hour |

Other field sizes, 7 changes an hour (what the repeats add):

| boxes | a box: TIME relays, s / hour | a box: points of the hour | controller: s / hour |
| --- | --- | --- | --- |
| 5 | +1.56 | +0.04 | +2.2 (controller 0.42 -> 0.48 % of the hour) |
| 10 | +0.78 | +0.02 | +2.2 (0.56 -> 0.62 %) |
| 20 | +0.31 | +0.01 | +2.2 (0.89 -> 0.96 %) |
| 30 | +0.20 | +0.01 | +2.2 (1.45 -> 1.53 %) |

The 30-box controller's 1.5 % is the ACKs of a crowded field (section 6 of the relay study), not the repeats; the repeats are
+0.08 point of it.

## 4. Against the EU868 limits the project uses

The budget is per sub-band and per transmitter (ERC REC 70-03 Annex 1; `core/src/duty_cycle.c`): 360 s an hour on 869.4-869.65
MHz (10 %, the default 869.525 MHz, the band the relay study and Amendment 13's 2.6-2.9 % per box are for), 36 s on 1 %
(868.0-868.6 and 869.7-870.0 MHz; the console warns), 3.6 s on 0.1 % (868.7-869.2 MHz; not recommended).

| what | air | on 10 % (360 s) | on 1 % (36 s) | on 0.1 % (3.6 s) |
| --- | --- | --- | --- | --- |
| one state change, the controller | 0.47 s | 0.13 % | 1.3 % | 13 % |
| the repeats of a typical hour (7 changes), the controller | 2.3 s | 0.64 % | 6.4 % | 64 % |
| all state changes of a typical hour, the controller | 3.3 s | 0.92 % | 9.2 % | 92 % |
| the repeats of a stress hour (21 changes), the controller | 6.9 s | 1.9 % | 19 % | 190 % |
| a box's TIME relays added, 20 boxes, typical | 0.31 s | 0.09 % | 0.9 % | 8.6 % |
| a channel change (3 MOVEs), on the old channel's sub-band | 0.28 s | 0.08 % | 0.77 % | 7.7 % |
| a sweep of four channels, on each one's sub-band | 0.18 s each | 0.05 % | 0.51 % | 5.1 % |
| *worst case without the cap*: Find boxes once a minute for an hour (60 sweeps, no game live), all four channels in one sub-band | 44 s | 12 % | 123 % | 1230 % |
| *worst case with the cap* (RL-9): 2 sweeps of four channels in a sub-band under 10 % (none on 0.1 %); 60 on the 10 % one, unchanged | 1.5 s | (44 s, 12 %, no cap) | 4.1 % | 0 |

What follows from it:

* **On the default 10 % sub-band every limit and margin the documents state still holds.** The boxes' 3.0 % is a third of
  the 10 %; the repeats do not move it (+0.01 point). The controller's own budget use rises from 8.9 % to 9.6 % of its 360 s
  (20 boxes) and from 14.5 % to 15.3 % (30 boxes); nothing is refused in any run.
* **On a 1 % sub-band the limit was already missed without the repeats**: a box in a relayed field uses about 3 % of the hour
  (relay study section 2; one box alone about 0.7 %), three times the 36 s, which is why the console warns and the game
  master's manual calls the channel a bad choice for more than a handful of boxes. The repeats add 0.01 point to that and,
  for the controller (0.9 % of the hour at 20 boxes, against 1 %), take the margin from 0.11 to 0.04 point (a typical hour)
  and past the limit with about ten pauses an hour. The modem's own guard refuses the frame that would cross the limit
  (`tx_status duty_cycle`), so the law is kept; what is lost is the last repeat or an ACK. Fields on 1 % channels should be
  small and still.
* **On a 0.1 % sub-band** the repeats alone are 64 % of the hour's 3.6 s, and a typical game's change frames 92 %. The channel
  was never usable for a game's controller (its 120 TIME beacons an hour are 9.9 s); `usable_for_games` and the scan already
  exclude it.
* **The sweep was the one rate in this family that could spend a small sub-band**: the once-a-minute limit protects a 0.1 %
  band only as long as nobody presses *Find boxes* five times in an hour, and it did not stop 49 sweeps an hour from
  spending a 1 % band's 36 s when the remembered channels share it. A sweep runs only while no game is live, so a run of
  sweeps cannot take air from a game in progress, but the sliding hour carries over: a game started right after a run of
  sweeps on the field's own sub-band starts with less budget left. The maintainer approved the cap on 2026-10-30 (RL-9, section 6).
  On the 10 % default the worst case is 12 % of the budget and the once-a-minute limit stays.

## 5. Mitigations considered

* **Stop the repeats once each box's ACK or STATE shows the new state.** Not built, and not worth it. A box sends no ACK for
  a TIME (it would be a new frame and a wire change), and the STATE that carries the state (`flags` bit 0 running, bit 1
  paused) comes every 15 s while the repeats end at +10 s: the first repeat leaves at +1 s, before about 93 % of the boxes
  have said anything, and the controller hears only 65-91 % of the STATEs of a 20-box field anyway, so "every box has
  shown it" would almost never be true before the last repeat. The most it could save is the +10 s frame (82 ms of 473)
  in a quiet field.
* **Fewer repeats when the field has many relays.** The relay rule already does this: a box relays a TIME with probability
  min(1, 3 / neighbours), so the relay cost of a change falls with the field (0.22 s a box at 5 boxes, 0.04 s at 20, 0.03 s
  at 30), and the controller's own 329 ms does not depend on the field. Cutting repeats for big fields would take
  away the repair where lost frames are most likely (the more boxes, the more hidden pairs) to save under 0.1 % of a
  10 % budget.
* **Cap *Find boxes* sweeps per rolling hour.** First left as a follow-up (a cap of six, 4.4 s, was suggested); built
  as RL-9 once the maintainer approved it (section 6), with a different number.

**Result: the repeats stay as built (RB-8), and the sweep gets an hourly air cap (RL-9, section 6).** the numbers above are locked by tests, and the
trigger for revisiting is a field-test measurement (the runbook) showing the modem refusing frames on the default
sub-band, or a game running on a 1 % channel with more than a handful of pauses.

## 6. The hourly cap on sweeps (decision RL-9, built 2026-10-30)

**The rule.** A sweep's MOVEs (two on each remembered channel, 185 ms a channel) are charged to the sub-band each channel is
in. Over a rolling hour (not a clock hour: each sweep leaves the window exactly 3600 s after it started) the sweeps may use
**5 % of that sub-band's duty-cycle budget**, and only sub-bands under 10 % are capped. The region tables (`regions.py`,
`radio_region.dart`) give the duty cycle; `lobby.Inviter.sweep_refusal` (Python) and `FieldInviter.sweepRefusal` (Dart) do the
sum, in integer microseconds, so both controllers refuse the same sweep (shared case *S7c Find boxes: the hourly cap ...*
in `protocol/vectors/controller_api.json`). A sweep is all or nothing; when more than one sub-band is over, the one that
waits longest is named. A channel outside the region's table counts as 1 %. The history lives in the controller's memory
(a restart forgets it, as it forgets invites; the modem's own duty-cycle guard still refuses frames over the limit).

| sub-band | budget an hour | 5 % for sweeps | sweeps of four channels an hour (all four in it) | worst case |
| --- | --- | --- | --- | --- |
| 10 % (g2, the default) | 360 s | no cap | 60 (once a minute) | 44 s = 12 % |
| 1 % (g, g3, AS923-TW) | 36 s | 1.8 s | 2 (a sweep of one channel: 9) | 1.5 s = 4.1 % |
| 0.1 % (g1) | 3.6 s | 0.18 s | 0 (one channel is 0.185 s) | none |

(`python -m atalaia_sim.state_load` prints it; `test_state_load.py` locks it.)

**Why 5 %.** The relay model puts the controller on a 1 % channel at about 0.9 % of the hour with 20 boxes, 0.04 point
below the limit once a typical hour's repeats are in (section 4); the repeats of the 7 changes of a typical hour cost it
2.3 s, 6.4 % of the budget, and all its state-change frames 3.3 s, 9 %. A sweep that comes right before a game spends air
the game then lacks, so the sweeps should stay clearly below what one typical hour's changes already take: 5 % (1.8 s) is
under the repeats alone (2.3 s), enough for the two or three sweeps a GM needs after a channel change (a sweep repairs
boxes that were away; one or two settle it) and low enough that the hour's other traffic is not moved by more than 0.05
point. The suggested 12 % (six sweeps, 4.4 s) was weighed and dropped: it is more than the repeats and more than the
controller's whole margin. 10 % would allow four sweeps of four channels; a field that needs more sweeps than two an hour on a 1 %
channel has a channel problem, and the console's warning on 1 % channels already says so. On 0.1 % no sweep ever fits: the
channel is already unusable for games (`usable_for_games`).

**Why 10 % keeps only the minute.** The worst case there is 44 s of 360 s (12 %), only between games, and the modem's guard
refuses a frame that would cross the limit anyway; a cap of 5 % there (18 s, 24 sweeps) would only change a worst case that
a GM pressing a button once a minute for an hour would hit. Left alone, as the maintainer said it could be.

**What the GM sees.** `POST /api/v1/boxes/discover` answers `{"sent", "sweep", "sweep_refused"}`: `sweep_refused` is null,
or `{"reason": "cap", "band", "duty_pct", "share_pct", "limit_ms", "used_ms", "cost_ms", "retry_after_s"}`; `retry_after_s`
(seconds until a sweep fits again, counted from the request) is null when a sweep never fits that sub-band. The console
says so under the button, in four languages, with the minutes to the next sweep. A second press inside the minute is still
the quiet empty sweep of RB-16 (the first sweep did happen); a refusal by the cap is never quiet.
