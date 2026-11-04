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

## Amendment 5 (2026-11-03): the `output` capability, its no-feedback flag, and a second hit sensor

**Adds** the details of the design specification's `output` capability type (section 7: "siren, smoke relay, strobe", specified since phase 1 and never built) that a script and the capability proxy need, and a second `hit` channel on one node. From the draft RFC "The expansion port" (decisions EXP-18, EXP-19, EXP-24, EXP-26, EXP-36; increment 1 of its plan, whose open questions Q1 to Q16 the maintainer answered with the RFC's recommendations on 2026-11-03), where both output paths are specified: the **simple output** (one GPIO, an RC relay switch, the maintainer's preferred path, EXP-31) and a switched-output channel of an expansion module ([protocol/expansion-port.md](../../protocol/expansion-port.md)). A mode does not know which path an output takes.

- **To a script,** an output is reached by its function: `cap("siren"):pulse(ms)` (on for `ms`, then off), `cap("siren"):on()` or `:on(max_ms)` (on until `:off()`, for at most `max_ms` or the channel's max on), `cap("siren"):off()`, `cap("strobe"):pattern(on_ms, off_ms, ms)` (blinks for `ms`; the module or the box runs the pattern, a script never toggles a relay itself). The id is the function, `siren`, `strobe`, `smoke`, `light` or `horn`, else `out.<n>`; a second one of the same function is `siren.2`. A call to a capability the node does not have does nothing (the core's `cap()` already forwards any method), so a mode written for a box with a siren still runs on one without. An output emits no events.
- **The no-feedback flag.** A simple output cannot tell whether anything is plugged into it. Its descriptor says so: `{"id": "siren", "type": "output", "feedback": false}`; an expansion module's channel leaves the key out (true). A controller shows such an output as "not checked" and counts it as present for a role's `requires:` once the box's admin enabled it.
- **On the capability proxy** (`protocol/capability-proxy.md`, version 1 unchanged): the descriptor above in IDENT; CMD `on` `{"ms"}`, `off`, `pulse` `{"ms"}` and `pattern` `{"on_ms", "off_ms", "ms"}`. The I/O pod holds an output's lease (or its simple output's signal), not the phone: when the phone's link drops, the pod turns its outputs off within 2 s.
- **A second hit sensor.** A node with more than one hit channel names them `hit`, `hit.2`, ... and adds `channel` (1, 2, ..., the number in the id) to each hit's data, the script's `hit.hit` and the proxy's EVT alike (`{"strength": 90, "channel": 2}`); its descriptor carries `channel` too. A node with one hit sensor sends exactly what Amendment 1 says.
- **Capability type ids.** HELLO's key 6 lists the node's capability types by number (RFC 0001 section 4, "capability type ids", sent empty until now): the table is `protocol/schema/capabilities.yaml`, generated into the C (`core/include/atalaia/protocol.h`, `core/src/protocol.c`), Python (`simulator/atalaia_sim/protocol.py`) and Dart (`app/lib/protocol/capability_types.g.dart`) tables; `hit` is 10, `output` 11, and `contact` 14 is reserved for its first module. A receiver ignores an id it does not know. Boxes fill the list when their output layer is built (the RFC's increment 2).
- **Events:** three new ones, specified with the expansion port: `node.modules` (57), `node.module_lost` (58, critical) and `output.switched` (59), with the data fields `modules` (42), `capability` (43), `ms` (44) and `source` (45).
- **Vectors:** `protocol/vectors/capability_proxy.yaml` (`ident` `pod_outputs_and_two_targets`, `evt` `second_target_hit`, `cmd` `siren_pulse`, `strobe_pattern`, `siren_on_for_at_most_30_s`, `siren_off`), `protocol/vectors/hello.json` (`hello_box_capability_ids`, `hello_unknown_capability_id`) and `protocol/vectors/events.yaml` (the three events), checked by the C, Python and Dart codecs.
- **Not yet:** the box's output layer and the simple output, the controllers and the console, the port driver and the modules: the RFC's later increments.

Compatibility: no new frame or key. A receiver that does not know the type `output` ignores the descriptor, as for any capability type it does not use; an older codec skips the unknown descriptor key `feedback` and data key `channel` (descriptor and data values are JSON); an older controller does not know events 57-59, so both controllers must run a release that knows them before a box sends them (the RFC's increments 1 and 3 come before 2).

## Amendment 6 (2026-11-04): the `node.outputs_disabled` event

**Adds** one event for the "outputs disabled on this box" note of the draft RFC "The expansion port" (EXP-21, EXP-28), which the maintainer decided on 2026-11-04 to build (decision EXPL-12; the choices are EXPL-13 to EXPL-19). A box leaves an output its admin has not enabled out of both its HELLO's capability types and its `node.modules`, so "outputs fitted, not enabled" looked like "no outputs fitted".

- **Event:** `node.outputs_disabled` (60, normal), data `modules` (key 42, unchanged): the outputs fitted that the box's admin has not enabled, in `node.modules`' compact text (`g45:servo:horn`; a module's channels not enabled as its entry with only those ids, `5c:out4/1.0.0:siren.2,smoke`: EXPL-20), the empty text when every one is enabled. A box with an output fitted sends it with each `node.modules` (and at the same moment when no output is enabled and it sends no `node.modules`), and again if its text changes while `node.modules` does not (EXPL-21); a box without outputs never does. Its meaning is the box's whole list at that moment: a controller replaces what it kept.
- **Why an event and not a data key of `node.modules`:** decoders refuse an unknown data key (protocol/README.md), so a `node.modules` with a new key would be lost whole on an older controller, its enabled outputs with it; a marker inside an entry (`g45:servo:horn!off`) would fail the older controller's parse of the text the same way. An unknown event is refused alone.
- **The controllers** keep the last one per node as the node list's `outputs_disabled` (null until the box says); the start check's new `outputs_disabled` list is a note, never a refusal or a warning, for each joined box whose role's `outputs:` (or its scenario's) names one of them. The console shows it on the box's chips and in the start panel.
- **Vectors:** `protocol/vectors/events.yaml` (one with a horn, one with the empty text), checked by the C, Python and Dart codecs; a contract case in `protocol/vectors/controller_api.json`.

Compatibility: no new frame or data key. An older controller (0.7.0) refuses event 60 as an unknown event id: it logs the packet as undecodable and keeps the box's `node.modules`, so nothing it did before changes; it shows no note. A box from before never sends it: both controllers give `outputs_disabled` null and no note, as before.

## Amendment 7 (2026-11-04): a phone prop tells its pod's outputs and modules

**Adds** what an I/O pod says about its simple outputs and its expansion port, so that a phone prop is no longer invisible to the console's outputs (draft RFC "The expansion port", increment 9, its port half; decisions EXPI9-19 and EXPI9-21; the gap EXPI9-12 named).

- **On the capability proxy** (`protocol/capability-proxy.md`, "The pod's expansion port"; version 1 unchanged): two EVTs of the pseudo-capability `pod` (as `pod.config`, decision PODC). `modules` `{"modules": text, "max_on_s": {id: seconds}}`, after every IDENT and whenever it changes: the `node.modules` text a box would send for the pod's enabled simple outputs and modules (`g33:servo:siren;58:target/1.0.0:hit`), and each lent output's longest on, 1-600 s; since decision PROPC-6 (2026-11-04) also `"withheld": text` from a pod with an output fitted, the outputs it has and does not lend in `node.outputs_disabled`'s text (Amendment 6), which the phone sends as that event; `module_lost` `{"modules": entry, "reason"}`, a module that stops answering while a phone is on a link. A module's hit channels and output channels are lent as Amendments 1 and 5 describe; the pod holds a module's lease.
- **On the game protocol: no change.** The phone sends `node.modules` (when the text changed) and, during a game, `node.module_lost`, the existing events 57 and 58 with the existing data keys, over the field's Wi-Fi or the pod's radio; the controllers take them as a box's (node list, console chips, **Outputs** panel). A prop's HELLO still lists no capability type, so the start check does not check props (unchanged). *Updated 2026-11-04 (decisions PROPC-1 to PROPC-5):* a prop's HELLO now lists the capability types of its phone's parts and of what its pod lends, and the start check takes it as a box ([prop-link.md](../../protocol/prop-link.md), "A prop's capability types"); no game-protocol change either.
- **The `g<gpio>:servo:<function>` entry needs no other form:** the pod knows its own GPIO and builds the text itself; the phone passes it on unparsed.
- **Longest on:** the `max_on_s` map lets the phone use the pod's longest on (a simple output's build setting, a module channel's) instead of 30 s.
- **Vectors:** `protocol/vectors/capability_proxy.yaml` (`evt` `pod_modules`, `pod_module_lost`; `pod_relay` `ident` `pod_port_modules`); `protocol/vectors/controller_api.json` (the case `EXPI9 a phone prop on Wi-Fi`).

Compatibility: an older phone drops both EVTs (they name no capability of the pod's IDENT: `PodInputs` maps nothing for them), and an older pod never sends them (the phone then says nothing, as before). A new data key in `node.modules` was ruled out: an older controller's decoder refuses an unknown data key and would drop the whole event (`protocol/README.md`, "Events on LoRa"; EXPL-13's reasoning); this amendment adds no key to any game event.
