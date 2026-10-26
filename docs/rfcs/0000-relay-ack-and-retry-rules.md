<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# RFC 0000: Relay, ACK and retry rules for a field of 20-30 boxes

- **Author(s):** The Atalaia contributors (the relay study, decisions SL-7 to SL-20)
- **Status:** Draft (2026-10-26): **proposed, not applied.** It amends RFC 0001 section 5 (flood routing), section 8 (duty cycle) and the ACK message of section 4, and Amendment 1's single channel. Nothing in `core/`, `firmware/`, `controller/` or the wire format implements any of it; the maintainer accepts it (or part of it) and gives it an amendment number in RFC 0001 (decision SL-17).
- **Discussion:** the pull request that adds this file

## Summary

RFC 0001's flood (every box relays every frame it hears once, after 10-50 ms) is cheap and simple for a field of a few boxes and wrong for twenty or thirty (in the model the trouble starts at five): it fills the channel with copies that collide with the frames they repeat and with the controller's ACKs, the boxes spend their duty-cycle budget on relays and on resends of events that were delivered but never acknowledged, and a box's ACKs stop for good after about an hour. This draft changes **four rules**, none of which changes a field of the wire format: (1) the controller's ACK skips a hole in a box's sequence once the box is 128 packets past it; (2) a box relays a frame that asks for an ACK only if it did not hear the controller's ACK first, relays the controller's ACK only for a box whose frame it relayed, and relays everything else with a probability that falls with the number of neighbours it hears, after a random delay (not one fixed by the frame); (3) an EVENT or HELLO that is not ACKed is resent at 3, 6, 12, 24, then every 30 seconds, not every 3; (4) optionally, the STATE period grows with the size of the field. In 90-minute simulations of 5 to 30 boxes in three layouts and both regions, rules 1-3 hold every box at about 2-4 % of airtime where the firmware runs into the 10 % ceiling (and then goes silent for a quarter of an hour), and take the share of captures the controller acknowledges from 7-30 % to 94-100 % in a mesh and in CQB (a long field of 30 boxes: 56 %, which no relay rule can fix), with the 15 s STATE kept (decisions SL-12 to SL-16, `docs/review/relay-study-results.md`).

## Motivation

Measured, not guessed (simulator: `python -m atalaia_sim.relay_report`; the model's limits are decision SL-18):

- **The relays are what saturates the channel**, before the duty-cycle budget does. A box relays every frame of any type it has not seen in 30 s: another box's STATE, EVENT and HELLO, and the controller's ACK and TIME (the controller never relays, so all N boxes repeat its frames). With the same `atalaia_flood_jitter_ms(source, seq)` in every box, all of them transmit within a few tens of milliseconds of each other, for longer than the jitter (an EU868 STATE is 103 ms on air); the radios are half duplex and there is no listen-before-talk, so the copies destroy each other and whatever else is on air, among them the controller's ACK to the box that sent the event.
- **The ACK window stalls.** An ACK carries the highest contiguous sequence number and a bitmap of the next 256. A packet lost for good (a STATE; an EVENT's resend takes a new number) leaves a hole that never closes, so after 256 more packets from that box none of its ACKs can name a new one. At a 15 s STATE that is about an hour; every event the box then sends is resent ten times (normal) or for ever (critical) and, because each resend is relayed by every other box, costs more airtime than the first send.
- **Retries cannot back off,** so an unacknowledged HELLO or critical event repeats every 3 s for ever, each time with N-1 relays: a field that gets into trouble at the start (all boxes sending HELLO in the same half minute) stays there.

## Design

Every number below is the simulation's, tuned on the models in `simulator/atalaia_sim/relay_study.py`; a field test may change them (decision SL-18 says what to measure).

### 1. ACK coverage: skip a hole (controller only)

Section 4's ACK message is unchanged. The controller's tracker of a box's received sequence numbers (`AckTracker` in `simulator/atalaia_sim/field_controller.py`, shared by the Pi's and the phone's controllers) treats every sequence number that is more than **128** below the highest one received as received: `ack_seq` is then never more than 128 behind the box's newest packet, and the bitmap always reaches it. A box's outbox holds at most 32 events and resends each at most every 3 s, so an event's latest packet is never 128 numbers old while it waits; the bound must stay above `FIELD_LINK_OUTBOX` plus the packets a box sends in one ACK round trip. The controller's `last_ack_seq` in CLAIM (section 4) follows the same tracker. Boxes and the wire format are unchanged: an older box gets ACKs that work; the first rule to adopt (decision SL-16).

### 2. Relaying (every box)

Section 5's steps 1-4 stay: check (source, epoch, seq) in the dedupe table, process, clamp `hop_limit` to `max_hops`, decrement. Step 4's rebroadcast changes to:

1. **Frames that ask for an ACK** (`ack_req`: EVENT, HELLO). The relay waits a random 350-700 ms instead of 10-50 ms. If the controller's ACK for that (source, seq) is heard first (`ack_node` = source and the sequence number covered by `ack_seq` or the bitmap), the relay is cancelled; otherwise the box relays it and remembers the source as *on its path* for 30 s.
2. **The controller's ACK** (type 3) is relayed only for an `ack_node` that is on the box's path. A box that did not relay a frame of that node has nothing to deliver.
3. **Every other frame** (STATE, TIME, CMD, CLAIM) is relayed with probability `p = min(1, 3 / n)`, `n` the number of different boxes heard in the last 600 s (at least 1; a slow memory so that a lossy minute does not shrink it and send every box back to relaying everything), after a uniform random delay of 20-600 ms. `n` is local: a box at a field's end hears few and relays always.
4. The relay table grows from 4 to **8** slots (a longer delay keeps frames pending longer; about 2 KB of RAM). The dedupe table stays at 64 entries: at 30 boxes on a clean channel it holds a little less than the 30 s it is meant to, but a relay copy arrives within a second of its original, so the simulation saw no frame processed twice because of an eviction.
5. `hop_limit`, the clamp, the 30 s dedupe life and "never relay your own frame" are unchanged. FIELD (type 9) and PAIR (type 10) frames are not relayed, as before.

The delay is drawn per box and per frame from the box's own random source (the core's `rand`), no longer from `(source, seq)`: the point of the old function was a different delay per frame, and a function of the frame cannot give different boxes different delays.

### 3. Resends back off

An unacknowledged EVENT or HELLO is resent after 3, 6, 12, 24 s and then every 30 s (each interval multiplied by a random 0.75-1.25), where today it is every 3 s. Normal priority still gives up after 10 resends; critical still resends until ACKed. A resend is a new packet (new `seq`) as today.

### 4. The STATE period grows with the field (optional; interacts with decision SL-5)

A new optional join key **19 `boxes`** (uint, 1-255, the number of boxes the controller expects) lets a box set its STATE period to `clamp(1.5 s x boxes, 15 s, 45 s)`: 15 s up to ten boxes, 30 s at twenty, 45 s from thirty. Absent: 15 s as today. An older box ignores the key and keeps 15 s. The maintainer's answer to SL-5 (keep 15 s) stands unless this part is accepted: it is the only part of this draft that makes a number on the controller older, and the simulation shows the first three parts hold 20-30 boxes inside the budget without it (decision SL-15).

### What does not change

The packet header, every message encoding, the AES-CCM scheme, the nonce, the dedupe key, `max_hops` (1-3 in the join payload) and its default of 2, the channel, the regions, the duty-cycle budgets and the rule that a frame that does not fit in the budget is dropped. Section 8's wording ("the packet is queued for retry") does not describe what the radio task does (it drops the frame; an EVENT is resent by its outbox); this draft corrects the sentence rather than the code.

## Compatibility

Rules 1 and 3 and the parts of 2 that cancel or skip a relay are taken by an old box without harm: it relays more than the new boxes do, which is today's behaviour. A mixed field is safe and gains in proportion to the boxes that have the new rules. The controller's rule (1) needs no change on the box. The relay delay of 350-700 ms for frames that ask for an ACK adds up to 0.7 s per hop to an event that the controller did not hear directly. Decision SL-9 notes the limit that stays: `hop_limit` 2 reaches three hops, so a field longer than that (a line of boxes, the controller in the middle, each hearing three on either side, is 19 boxes) is not served by any relay rule: `max_hops` 3 in the join, or a second controller.

## Alternatives

Evaluated in the same simulator and described in decision SL-14: not relaying STATE (the controller then loses every STATE it does not hear directly), a longer or a delta-suppressed STATE period alone, a counter-based relay (cancel after one copy heard: more airtime in a mesh, better in a line), an oracle that lets the controller name the relays (cheaper in a mesh, and it needs a new CMD and a topology the controller does not have), and listen-before-talk (it makes today's flood worse and helps a field that has stopped flooding; RFC 0001 section 8 chose not to use it, decision SL-19).

## Open questions

- The values (350-700 ms, `c` = 3, 600 s, 128, 30 s) come from a model whose link budget and capture effect are assumptions; a field test with the counters `field_link_stats_t` already keeps (decision SL-18) should confirm them before they are frozen.
- Whether a box's last STATE (the one that ends the game) should ask for an ACK and be resent, so that a lost one cannot cost the final score of a box (the study's STATE heard rate is 60-90 %, not 100 %).
- Whether `max_hops` 3 should be the default for fields larger than ten boxes.
