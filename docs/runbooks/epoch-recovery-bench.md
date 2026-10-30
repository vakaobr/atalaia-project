<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Runbook: a node that lost its epoch store, on real boards

Decisions **SR-110 to SR-119** (RFC 0001 Amendment 24) and **EP-1 to EP-12** (Amendment 25). A node's nonce is `(epoch, seq)` under the game key; receivers never lower a source's epoch. A box that lost its epoch store takes a random epoch in 4096..61439 (Amendment 23), receivers find it by a *deep search* of its HELLO or TIME, controllers name it in CMD `peer`, a second loss draws above the box's *epoch floor* (`epfloor` in NVS), and a controller that has been on the air keeps its node id. **All of this is host-tested** (C tests with a fake NVS, Python and Dart vectors, the host pod and modem for the prop's pod). **Nothing here has run on a board.** This runbook is what only boards can say: that the deep search finds a box in the time the budget allows on the real radio, that the NVS entry survives what it should, and that a pod's receiver follows a name that arrives over Wi-Fi.

Do **not** run this on the field's real game. Use the bench: two Heltec V4.3 boards as boxes (A and B), the USB modem on the bench controller, an Android phone with an I/O pod for step 7. Nothing here flashes the field's boards; flash the bench ones as usual (`python3 tools/docker_fw.py bench`, which is a **bench build**: it has `@epochwipe`; a release image does not).

## What you need

- Two boxes (A, B) and the modem, all with the bench build of this branch, joined to one game from the bench controller (`~/atalaia-bench-ctl`, restarted after updating, with the game key kept: `persist_game_key`).
- The boxes' serial consoles (115200 baud) and the controller's log.
- `sqlite3` on the controller's host for step 5; a second controller (Pi or phone) for step 6.

The bench build adds two serial commands, for these steps only:

- `@epochwipe` removes the box's epoch store (the blob `epochs` and the old single `epoch`), keeping the game key, the stored game and the floor entry `epfloor`: the next boot finds a stored game with no record of its key, which is the *lost store* of Amendment 23.
- `@epochwipe all` removes the floor entry too: **both records lost**, the case Amendment 25 leaves.

## 1. A box that lost its store is found (SR-110, Amendment 24)

1. Play a game with A and B for a few minutes. Note A's epoch (the `radio` log line at its join says `epoch N`; or the node row in the console).
2. On A: `@epochwipe`, then restart it (reset). On its console read, at the join:

   ```
   epoch store lost: radio epoch restarted at <E1>; receivers find this box by their deep search within a minute or two, ...
   ```

   `E1` must be in 4096..61439. Write it down.
3. Watch the controller's log and the console: within **two minutes** the controller logs `node <A> is at epoch <E1>; the receivers are told`, A is online again and its HELLO is acknowledged. B's `radio_stats` / `field_link_stats` shows `peer_epochs` one higher (it took the controller's CMD `peer`).
4. Write down: time from A's reboot to the controller's log line, and from there to A's first acknowledged event. **Pass:** under 2 minutes, with no GM action. **Fail:** A offline after 3 minutes (note the modem's `rx_auth_fail` rate: the deep search costs about 60 ms of decryption per slice on the S3 and is budgeted at one search per source per 2 s; look for the modem or box missing other traffic meanwhile).
5. While A is being searched for, send it events and watch B and the modem: no dropped relays, no `tx_refused` growing (the deep search is a receiver cost; it must not starve the relay).

## 2. A second loss draws above the first (EP-2)

1. On A, after step 1, let it reboot **three times** (reset) in the game: each epoch is one above the last (`E1+1`, `E1+2`, `E1+3`), and `epfloor` follows (it is written before the epoch is used; no console line, it is read back in the next step).
2. `@epochwipe` on A again and restart. **Pass:** the log line's epoch `E2` is **greater than `E1+3`**, in `E1+4..61439`, whatever the random draw gave. Repeat the wipe three or four times: every `E` is above the last. A draw below an earlier one is a fail (and must be reported with both numbers: the draw is uniform above the floor, so a single failure is a bug, not bad luck).
3. After each wipe, A is found again as in step 1 (it may take longer when `E` is far above the controller's last name for it; the controller names a box heard more than 16 above its last epoch).

## 3. Both records lost (the case Amendment 25 leaves)

1. On A: `@epochwipe all`, restart. A draws in 4096..61439 as in Amendment 23, with nothing remembered: it may land **below** what the receivers heard (a repeat of an earlier nonce is possible in principle, at about 1 in 57000 per epoch the earlier life used).
2. Write down whether A is heard again. If it landed below the receivers' knowledge it stays silent (the console shows it offline and its HELLO unacknowledged); that is the documented outcome: join A again with a new key (a new join of the game as a different node id). **No fix is expected here.** The point of the step is to see that the box does **not** crash, does not transmit garbage and says "epoch store lost" at its join.

## 4. The floor cannot be written

The write is `nvs_set_u16` plus a commit. To see the failure handled, fill the NVS (`@epochwipe` does not do this; use the bench's usual NVS-full trick, if you have one) and restart a box that must draw a lost epoch: it must say `radio halted: the nonce epoch could not be stored` and stay silent, not transmit. If you have no way to fill the NVS, skip: the host test covers it with a failing fake.

## 5. The controller's records lost (Pi, EP-2)

1. On the bench Pi controller with a game live (`persist_game_key` on): note its epochs with `sqlite3 <db> "select key, value from settings where key like 'tx_epoch%'"` and `cat <db>.epochs`. Stop the controller.
2. **Records, one at a time.** Delete only the setting (`delete from settings where key in ('tx_epochs')`), start the controller: it goes on above the epoch file's (`<db>.epochs`), no warning. Stop it. Delete the epoch file as well but not `tx_epoch_floor`: start it: it logs `resumed with no record of its epoch: ... random epoch N (above F, the highest it ever used)`, `N` above `F`. The boxes follow its TIME within two minutes (their deep search): check the box's `times` counter moving and the node health.
3. Stop it, delete `tx_epochs`, `tx_epoch_floor` **and** `<db>.epochs`, start: the draw is from 4096 again (both lost). If `N` is below what the boxes heard, the boxes do not follow it: the GM sees every box without a TIME; end the game and start a new one (a new key). Write down what the boxes and the console showed.

## 6. A former leader joined again under its old id (EP-3)

1. Two controllers, P (the primary) and S (a standby joined from P). Promote S; P is a follower. Let S lead for a minute so P hears its TIME.
2. On P, in the console or `POST /api/v1/nodes/<S's id>/join {"kind":"controller"}`: **refused (409)**, "belongs to a controller that has been on the air". Also `<P's own old id>` from S: refused. A join with no id gets a fresh id.
3. Wipe S (new database, no `.epochs`), join it again with the join P gave in step 2 (a new id): it follows, can be promoted, and the boxes follow its TIME at once (a new source, epoch 1; no deep search needed). Write down the time from promotion to the boxes' first applied TIME.

## 7. A prop's pod is told over Wi-Fi (EP-1)

1. An Android prop (the app joined to the game as a prop) with an I/O pod that has a radio, on the field's Wi-Fi, linked to the bench Pi controller (the Wi-Fi link up, the pod's radio linked: the app's prop screen says so).
2. Do step 1 on box A (the box the pod can hear). In the app's log (the prop screen's log, or `adb logcat | grep -i "peer epoch"`) a line `peer epoch <A> at <E1> told to the pod` appears when the controller names A.
3. Pull the Wi-Fi link (the prop falls back to the radio) and repeat: the pod hands the CMD `peer` it heard on the radio to the phone, which applies it the same way (the same log line). Write down both.
4. **Pass:** the line appears within a few seconds of the controller's own log line in both cases. **Fail:** no line (the CMD `peer` is not reaching the app: check `GET /api/v1/prop` link state and the pod's `radio_stats`).

## What to send back

The numbers asked for in steps 1 to 3, 5 and 6 (E1, E2..., the times), the console lines quoted, and for any step marked "Write down" what happened. Anything that contradicts a **Pass** line is a finding; give the boards' and the controller's logs from five minutes before it.
