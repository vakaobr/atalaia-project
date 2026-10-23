<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# RFC 0000: Phase 3 events, player tags and the capability proxy

- **Author(s):** The Atalaia contributors
- **Status:** Draft (written with phase 3 plan phase A, 2026-10-18; a number is given on acceptance)
- **Discussion:** to be opened with the pull request

## Summary

Three protocol additions for phase 3 (Android and players), each already specified and implemented with shared test vectors: twelve standard events and two data fields (ADR-P3-8), the player tag (ADR-P3-9), and version 1 of the capability proxy protocol between an I/O pod and a phone (ADR-P3-2). Protocol changes go through an RFC (CONTRIBUTING.md); this one records them for review.

## Motivation

Kill Confirmed, Respawn and Lives and Player Check-in need to know which player is at a prop, and the game master needs their events in the log. Android props borrow physical buttons, LEDs, NFC and LoRa from an ESP32 I/O pod, whose link must be frozen before the pod firmware and the app are written (the research named it the highest-risk item of phase 3).

## Design

**Events** (`protocol/schema/events.yaml`; the phase 2 mode pack holds 28-32; phase 4 starts at 42):

| Id | Event | Data (besides `team` and `squad`) |
| --- | --- | --- |
| 25 | `kill.confirmed` | `player`, `owner` (the tag's team); `team` is the team credited |
| 26 | `kill.denied` | `player`, `owner`; a team recovered its own player's tag |
| 27 | `team.eliminated` | (`team`: the team out of lives) |
| 33 | `money.collected` | `player`, `amount` |
| 34 | `money.deposited` | `player`, `amount` |
| 35 | `chrono.checkin` | `replica`, `player`, `reading_mps`, `bb_g` |
| 36 | `chrono.spotcheck` | `replica`, `player`, `reading_mps`, `bb_g`, `tolerance_pct` |
| 37 | `visibility.granted` | `see_team`, `duration_s`, `text` (`team`: who sees) |
| 38 | `visibility.expired` | `see_team`, `text` |
| 39 | `node.tamper` (critical) | `reason` |
| 40 | `pod.connected` (telemetry) | `fw`, `tier` |
| 41 | `pod.disconnected` (telemetry) | `reason` |

New data fields: `see_team` (key 29, string) and `tolerance_pct` (key 30, number). ADR-P3-8 listed `[player, team]` for the kill events and `[team, text]` for visibility; `owner` and `see_team`/`duration_s` say whose tag and whose positions without overloading `team`.

**Player tags** ([protocol/nfc-tag.md](../../protocol/nfc-tag.md)): `version (1) | player (1-32) | team (1) | game_id (2) | HMAC-SHA256(game key)[:16]`, as an NDEF MIME record `application/vnd.atalaia.tag`. The node's host checks a tag and gives the mode `nfc.tag` with `valid`, `player` and `team`, or `reason`; scripts never see the key.

**Capability proxy v1** ([protocol/capability-proxy.md](../../protocol/capability-proxy.md)): the USB modem's framing (sync, type, length, payload, CRC-16) on USB-OTG and BLE; IDENT, EVT, CMD (CBOR maps with integer keys) and ACK; the modem's RX, TX, TX_ACK, CMD, STATUS and ERROR shifted by 3; GATT service `4174616c-6169-6100-0000-000000000000` with three characteristics.

Added with the pod firmware (plan phase F, 2026-10-19): the modem's NOISE as RADIO_NOISE (`0x0B`, the answer to MEASURE, which the modem gained with RFC 0001 Amendment 3; decision PF2), and a capability type `tamper` (events `opened`, `closed`) for a pod's enclosure switch, which the phone reports as `node.tamper` with `reason: pod_opened` (decision PF8). The standard capability types of the design specification (section 7) gain `tamper`.

Added for the phone as field controller (2026-10-23, decisions PE24-100 to PE24-103): the modem's FIELD_TX, FIELD_RX and FIELD_ACK as RADIO_FIELD_TX, RADIO_FIELD_RX and RADIO_FIELD_ACK (`0x0C`-`0x0E`, plus 3 as the other radio frames), which carry field frames (type 9) and pair frames (type 10) as they are, and three optional IDENT bools, keys 6 `field_frames`, 7 `pair_frames` and 8 `measure`, within version 1 (readers skipped keys 6-23; an older pod leaves them out, so the phone knows what it can ask).

## Compatibility

Older nodes pass unknown event ids through as raw CBOR (ADR-P3-8); the JSON Schema of the game log gains the new events. The tag and the proxy are new formats with version bytes or fields of their own. The capability proxy skips unknown keys 6-23, so a later pod can add optional fields.

## Alternatives

- Tags keyed with a key derived from the game key (HKDF) rather than the game key itself, which also keys AES-CCM: the HMAC and the cipher are separate primitives and no attack is known, but a derived key would keep the two uses apart. Kept as ADR-P3-9 says; open question below.
- A separate framing for the pod: rejected, the pod reuses the modem's code (ADR-P3-2).

## Open questions

1. Should tags use a key derived from the game key (decision A3 in `docs/review/decisions-to-review.md`)?
2. Should the game master be able to write tags from the console (the controller holds the game key)?
3. Should `tamper` be a capability type of its own, or an `imu`-like `moved` event of an `enclosure` type, once IMU-based tamper detection exists (decision PF8)?

## Amendment 1 (2026-10-19): the `hit` capability (phase 4 plan phase 2)

**Adds** the details of the design specification's `hit` capability type (section 7: events `hit(strength)`, commands `arm` and `disarm`, the target addon) that a script and the capability proxy need, so that the addon, or a pod or thin node that has a hit sensor, can lend it later. Decision P4R4; Target Windows (`modes/target_windows/`) is its first user.

- **To a script,** a hit is the input event `hit.hit` with `strength`, an integer 0-255 (how hard the plate was hit, as the addon's piezo measures it; the addon decides the scale). `cap("hit"):arm()` makes the sensor report hits, `cap("hit"):disarm()` stops it; a sensor reports nothing until it is armed.
- **On the capability proxy** (`protocol/capability-proxy.md`, version 1 unchanged): a descriptor `{"id": "hit", "type": "hit"}` in IDENT; EVT `{cap_id: "hit", event: "hit", data: {"strength": n}}`; CMD `arm` and `disarm`, without arguments. The phone turns the EVT into `hit.hit`, as it turns a button's `hold` into `team_input.hold`. Shared vectors: `ident` `target_addon`, `evt` `target_hit`, `cmd` `target_arm` in `protocol/vectors/capability_proxy.yaml`, checked by the C, Python and Dart codecs.
- **Events:** none new. A scoring hit uses `target.hit` (16), already in the schema, with `window_open` and the team in the envelope.
- **Not yet:** the addon's own firmware and the Field Box's addon port driver (phase 4 HW2). Until they exist, Target Windows is not a Field Box built-in preset, and Android props do not offer `hit` (a phone has no hit sensor; a pod that one day lists one would lend it as above).

Compatibility: no new frame, key or event; a receiver that does not know the type `hit` ignores the descriptor, as for any capability type it does not use.

## Amendment 2 (2026-10-20): the `hacking.solved` event (phase 4 plan phase 4)

**Adds** the first of the phase 4 events (decision P4R1), with the Hacking Terminal (`modes/hacking_terminal/`, decision P4R5), its first user.

| Id | Event | Data (besides `team` and `squad`) |
| --- | --- | --- |
| 47 | `hacking.solved` (critical) | `puzzle` (`code`, `wires` or `sequence`), `code` (the code the terminal reveals, when the game sets one); `team`: who solved it, left out when nobody known did |

- **New data field:** `puzzle` (key 36, string). Keys 34 and 35 stay for `objective` and `scenario` (plan phase 6), and events 42-46 for the scenario events and `vip.extracted` (plan phases 5 and 6), each added with the code that first emits it (46: Amendment 3).
- `code` (key 10) is reused: here it is the code itself, which the GM console shows; the players' feed shows only who hacked a terminal. Wrong answers are not events.
- **Vector:** `protocol/vectors/events.yaml`, "Red solves a hacking terminal's wires and it reveals code 4711", bytes built by hand from RFC 8949's encoding rules (CBOR major types 0, 3 and 5, the shortest forms) and the schema's keys, checked by the C, Python and Dart codecs. JSON Schema: `protocol/json/event.schema.json` and the example `protocol/json/examples/hacking-solved.json`.

Compatibility: as for the events of the design above, an older node passes the unknown id through as raw CBOR and an older controller logs it by its number; nothing else changes.

## Amendment 3 (2026-10-20): the `vip.extracted` event and staff-only data (phase 4 plan phase 5)

**Adds** the event of VIP / Payload (`modes/vip_payload/`, decision P4R6), and a mark in the schema for data that only staff may read (decision M5-1).

| Id | Event | Data (besides `team` and `squad`) |
| --- | --- | --- |
| 46 | `vip.extracted` (critical) | `player` (key 14): the VIP, when the controller extracted them; left out when a payload prop did; `team`: the escorting team |

- **Positions never travel.** A VIP's position reaches the controller's `field.lua` only, as the input `position.fix` (`player`, `team`, `role`, `lat`, `lon`, `acc`, `src`); a payload prop's GPS reaches its own `node.lua` only, as the input `gps.fix` (`lat`, `lon`, `acc`; empty before the phone's first fix). Neither is an event, and no event has a position data field; the simulator and the Dart test runner report any event whose data carries a key such as `lat`, `lon`, `position` or `gps`.
- **Staff-only data.** An event may list some of its data fields as `gm_only` in `protocol/schema/events.yaml` (today `hacking.solved`'s `code`). On the radio, in the controller's log and in the sync to the site server the event is whole; on the controller's stream, its REST views and MQTT, only staff (the GM token, marshals, gm player tokens) get those fields. A mode's parameters may be marked `gm_only: true` in its manifest with the same effect on a game's parameters.
- **Vectors:** `protocol/vectors/events.yaml`, "The controller logs red's VIP extracted" and "Blue's payload prop reaches the extraction zone", bytes built by hand from RFC 8949's encoding rules and the schema's keys, checked by the C, Python and Dart codecs. JSON Schema: `protocol/json/event.schema.json` (a `$comment` names the staff-only fields) and the example `protocol/json/examples/vip-extracted.json`.

Compatibility: an older node or controller treats id 46 as it treats any id it does not know; `gm_only` changes nothing on the wire.


## Amendment 4 (2026-10-20): the scenario events (phase 4 plan phase 6)

**Adds** the events of custom scenarios (decisions P4R1, P4R7): a scenario package's `field.lua` on the field controller logs them, over the nodes of the built-in role package `org.atalaia.objectives`, which report the standard `zone.captured`, `code.used`, `tag.scanned` and `bomb.*` events and never score on their own.

| Id | Event | Data (besides `team` and `squad`) |
| --- | --- | --- |
| 42 | `scenario.objective.completed` (critical) | `objective` (key 34): the objective's id; `team`: the team that completed it |
| 43 | `scenario.objective.failed` (critical) | `objective`; `reason` (key 3), such as `time` or `exploded`; `team`: the team that failed it, if one |
| 44 | `scenario.objective.revealed` (critical) | `objective`; `team`: the team it is revealed to, none for every team |
| 45 | `scenario.started` (critical) | `scenario` (key 35): the scenario package's id |

- **New data fields:** `objective` (key 34, string: an objective id, `[a-z][a-z0-9_]{0,23}`, decision P4R8) and `scenario` (key 35, string). Texts (an objective's name and description) never travel: they are in the scenario package, in English and `i18n.pt`.
- **Who learns which objective:** `objective` is `gm_only` on events 42-44 (decision M6-5): MQTT and anyone the controller cannot place learn that a team completed, failed or was shown an objective, not which one. Since plan phase 8 the controller's stream and REST also give it to the players the objective is for, by the visibility in the scenario package (`public`: everyone; `team`, `squad`: the assignee's; `hidden`: the assignee's once revealed, and nothing is sent before; decisions P4R24, M8-4). The radio carries the whole event, as before.
- **Vectors:** `protocol/vectors/events.yaml`, "A scenario starts", "An objective is revealed to every team", "Red completes an objective", "Blue fails an objective with a reason", bytes built by hand from RFC 8949's encoding rules and the schema's keys, checked by the C, Python and Dart codecs. JSON Schema: `protocol/json/event.schema.json` and the example `protocol/json/examples/scenario-objective-completed.json`.

Compatibility: an older node or controller treats ids 42-45 as it treats any id it does not know; the nodes' own events are the standard ones.
