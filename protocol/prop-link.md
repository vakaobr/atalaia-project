<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Android props on Wi-Fi (the prop link)

An Android phone running a prop joins a game with a join payload ([join.md](join.md)), like a box, but it has no LoRa radio of its own (an I/O pod brings one, below). On the field's Wi-Fi it links to the controller instead and takes part as a box does over the radio: it reports its HELLO, STATE and EVENT messages and receives the controller's TIME beacons and commands (decision PD12, plan phase E). This file is the link, version 1.

Implementations: `controller/atalaia_controller/prop_link.py` (Python: the controller) and `app/lib/controller/prop_link.dart` (Dart: the phone). Tests: `controller/tests/test_prop_link.py` and `app/test/controller/prop_link_test.dart`.

## Where the controller is

A join payload for a box (kind 0) carries two optional fields when the controller serves HTTPS (RFC 0001 Amendment 4, proposed): key 13 `ca_sha256`, the SHA-256 of the field CA's DER certificate (32 bytes, decision P3-8), and key 14 `urls`, 1-3 `https://host[:port]` base addresses of the controller. A box reads them only for firmware updates over Wi-Fi ([firmware-update.md](firmware-update.md)). The phone fetches `GET /api/v1/controller/ca`, checks it against key 13 and trusts that CA for those addresses only, for the length of the game. A payload too long with them is made without them; the phone then asks for the controller's address.

## The link

`WS /api/v1/prop` (`wss://` with the pinned CA). JSON text frames. The Pi controller serves it (`controller/atalaia_controller/prop_link.py`), and so does the Android controller (`app/lib/controller/controller_props.dart`, decision PE24's slice S4), checked by the same contract case (`vectors/controller_api.json`).

1. The controller sends `{"type": "challenge", "nonce": "<32 random bytes, base64url>", "version": 1}`.
2. The prop answers within 10 s with `{"type": "auth", "game_id": G, "node_id": N, "proof": "<base64url>"}`, where
   `proof = HMAC-SHA256(game key, "atalaia-prop-link-v1" 0x00 | nonce | G (2 bytes, big-endian) | N (2 bytes, big-endian))`.
   The game key is the join payload's (16 bytes). Known answers: [vectors/prop_link.json](vectors/prop_link.json). The controller checks it in constant time and refuses (`{"type": "refused", "reason": "auth"}`, close code 4401) a wrong proof, a game that is not live here, a node id that is the controller's or not assigned to a role in the game (the join payload assigns it).
3. It sends `{"type": "welcome", "game_id", "node_id", "controller_id", "time": {<the current TIME fields>}}`.

A newer link for the same node replaces the older one, which gets `{"type": "replaced"}` and close code 4409.

### Prop to controller

| Message | Fields | As on the radio |
| --- | --- | --- |
| `hello` | `node_name`, `fw_version`, `core_version`, `tier`, `capabilities`, `battery_pct`; `platform` (default 3, android) and `transports` (default 2, Wi-Fi) | HELLO ([schema/messages.yaml](schema/messages.yaml)) |
| `state` | `owner_team`, `phase`, `game_time_ms`, `counters` (`{"<team id>": points}`), `battery_pct`, `flags` | STATE |
| `event` | `event`: `{seq, t, type, team (id), squad, prio, data}` | EVENT ([schema/events.yaml](schema/events.yaml)) |
| `ping` | | answered with `{"type": "pong"}` |

The controller encodes each with the radio's own codecs (`atalaia_sim.packet`, `atalaia_sim.codec`), checks events against the schema (unknown data fields are refused with `{"type": "error", "message", "seq"}`), and hands them to the game's FieldController as a packet from node N would be: the node list, the score merge by maximum and the event log's duplicate check (node, seq, game time, type) are the radio's. Every event is answered with `{"type": "ack", "seq", "event_type"}` once it is logged, or was logged before; the prop resends events that were not acknowledged after a reconnect. The shell's own events (`node.tamper` when kiosk mode is lost, ADR-P3-9) count their own `seq` from 1; the event type keeps them apart from the script's.

### Controller to prop

| Message | Fields |
| --- | --- |
| `time` | TIME's `game_time_ms`, `game_state` (and its name `state`: waiting, running, paused, ended), `duration_ms`, `wall_s`, `term` |
| `cmd` | `cmd` (`start`, `pause`, `resume`, `end`, `set_owner`, `message`, `reset`, `reboot`, `mode`), `opcode`, `params`, `dest` (absent: every node); a `mode` command (opcode 8, RFC 0001 Amendment 5) reaches the mode script as `cmd.mode` with its params, `name` included |
| `ack`, `error`, `pong`, `replaced` | as above |

CMD opcode 12 (`output`, RFC 0001 Amendment 26; [expansion-port.md](expansion-port.md) section 8) is a `cmd` message too: `cmd` `output`, `opcode` 12, `params` `{"capability", "act", "ms", "on_ms", "off_ms", "src"}`, `dest` the prop. The prop's shell handles it, not the mode's script, by switching the output on its I/O pod with a box's rules ([capability-proxy.md](capability-proxy.md), "The pod's simple outputs"); a prop without that output ignores it. A CMD for every node reaches every linked prop: the controllers send it without `dest`, and relay one whose packet names `dest` 65535 (every node) too, telling the prop `dest` null (decision EXPI9-20, 2026-11-04: before it, a packet naming 65535 reached no Wi-Fi prop); so the GM's **All outputs off** (CMD 12, `capability` `*`, `act` `off`) turns a Wi-Fi prop's pod outputs off as it does a box's. Contract case `EXPI9 a phone prop on Wi-Fi` in [vectors/controller_api.json](vectors/controller_api.json).

**A prop's outputs and modules** (draft RFC "The expansion port", increment 9, decision EXPI9-19; draft RFC 0000 Amendment 7; no change to this link): a prop whose I/O pod has simple outputs or modules on its expansion port sends `node.modules` as an `event`, with the text its pod gives it (the EVT `pod.modules`, [capability-proxy.md](capability-proxy.md), "The pod's expansion port": `g33:servo:siren;58:target/1.0.0:hit`), whenever it changes, and `node.module_lost` (critical) when a module of the pod stops answering during a game. The controllers take them as a box's: the node list's `modules`, the console's chips and **Outputs** panel. Its HELLO lists its capability types since 0.8.0 (below), so the start check takes a prop's modules and outputs as a box's.

**A prop's capability types** (decisions PROPC-1 to PROPC-5, 2026-11-04; closing EXPI9-12; no change to this link or the radio's): HELLO's `capabilities` lists the type ids of [schema/capabilities.yaml](schema/capabilities.yaml) for what the prop gives a mode: the phone's screen (team buttons `button` 1, its keypad `keypad` 2, `display` 3, the ring and team light `led` 4), its speaker (`audio` 5), its NFC reader (`nfc` 6) and its GPS (`gps` 8) when it has them, then what its pod lends in IDENT: its buttons, keypad, ring, buzzer and NFC reader by their types, `hit` (10) while it lends a target's hit sensor and `output` (11) while it lends an output (one IDENT leaves out for lack of room is not lent, EXPI9-28). Never listed: the vibrator, the camera, the accelerometer, the pod's case switch and battery gauge, which the prop shell gives no mode (`app/lib/prop/capability_mapper.dart`, `CapabilityMap.helloTypes`). The controllers' start check then takes a prop as a box: a required type it lacks is `missing_caps` (Start refuses unless forced), an optional one a warning, a role's `outputs:` none of whose functions its `node.modules` names the warning `outputs` (contract cases `PROPC` in [vectors/controller_api.json](vectors/controller_api.json)). Unlike a box, whose HELLO is sent once a game, a prop sends HELLO again, with the same fields and the new list, whenever the list changes: its pod's IDENT changes it (a target plugged in or out), the pod's link breaks (what it lent is not the prop's until its next IDENT) or the person unlinks the pod; nothing when the list is the same. Over Wi-Fi it goes at once; a radio through the pod goes down with the pod's link, and the radio of a pod linked again starts with the new list. A prop that loses its pod during setup is therefore checked without it, and one that gets it back with it; a prop on the pod's radio alone that loses its pod reaches the controller no more, which keeps the last HELLO it heard. An older prop sends an empty list and is never checked, as before.

**Not yet: a pod's withheld outputs** (EXPI9-29, PROPC-6, open): the outputs a pod leaves out of IDENT for lack of room (EXPI9-28) are in neither HELLO nor `node.modules`. They are to show as a box's outputs fitted but not enabled, with the event `node.outputs_disabled` of branch `feat-outputs-disabled-note` (PR #63, decisions EXPL-13 to EXPL-19), once it is on `main`.

The controller's own CMD opcode 11 (`peer`, RFC 0001 Amendments 24 and 25) is a `cmd` message too: `cmd` `peer`, `opcode` 11, `params` `{"src": node id, "epoch": epoch}`, `dest` absent (every prop). It names the epoch a node is at; a prop with an I/O pod tells its pod's receiver (never down, `src` 1 to 65534 and not its own id, `epoch` 1 to 65535); a prop with no pod ignores it, and the mode's script never sees it.

Whatever the controller sends on the radio as TIME or CMD reaches the linked props too; a command for one node reaches only that node's link. Without a radio modem a command reaches the Wi-Fi props and is reported as sent.

## Security

- The link proves the game key without sending it; every game has a new key, so a link ends with its game. Anyone who holds the game key (every box and join card has it) can link as an assigned node: as on the radio, the join payload is the credential (ADR-P2-12).
- Over `wss://` with the pinned field CA the messages are private and cannot be changed on the way. Over plain `ws://` (the controller's HTTP port) they are not; the app uses `wss://` whenever the payload has keys 13 and 14.
- Positions never travel on this link (ADR-P3-6: `POST /api/v1/positions`).

## With an I/O pod: the field's radio as well (plan phase F)

A phone with an I/O pod that has a radio ([capability-proxy.md](capability-proxy.md)) can also take part on the field's radio, as a box does: it builds the plaintext Skirmesh-RF packets (HELLO, EVENT, STATE; the EVENT payload with the core's own codec) and the pod encrypts and sends them with the USB modem's code, which keeps the channel's duty cycle and power; the phone hears the controller's TIME, CMD and ACK through the pod (`app/lib/radio/pod_radio_link.dart`; refinement of 2026-10-19, decision PF9). It configures the pod's radio with the join payload's game, node id, hops and channel and a new epoch, stored before it is used, so a nonce never repeats under one game key; HELLO goes until acknowledged; normal and critical events ask for an ACK and are sent again every 3 s in new packets; STATE goes at most every 15 s. The phone does not relay other nodes' packets.

When both links exist (`app/lib/controller/dual_link.dart`):

- while this Wi-Fi link is up, everything goes on it, the radio stays quiet (the field's airtime is shared and duty-cycled), and the controller's word is taken from Wi-Fi only;
- while it is down, events and STATE go on the radio too, and TIME and commands come from the radio;
- every event still goes to the Wi-Fi link, which keeps it until acknowledged and sends it again after a reconnect; an event heard on both arrives twice and is logged once (the log's duplicate key is node, seq, game time, type), and scores merge by maximum.

Both HELLOs then say so in `transports`: bit 0 (LoRa) is set when a pod with a radio is linked, next to bit 1 (Wi-Fi) when there is a Wi-Fi link (`hello` here carries `transports` 3; the radio's HELLO 3, or 1 at a field without Wi-Fi). A game joined without the controller's addresses (no keys 13 and 14) uses the radio alone.
