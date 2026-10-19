<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Android props on Wi-Fi (the prop link)

An Android phone running a prop joins a game with a join payload ([join.md](join.md)), like a box, but it has no LoRa radio of its own (an I/O pod brings one in plan phase F). On the field's Wi-Fi it links to the controller instead and takes part as a box does over the radio: it reports its HELLO, STATE and EVENT messages and receives the controller's TIME beacons and commands (decision PD12, plan phase E). This file is the link, version 1.

Implementations: `controller/atalaia_controller/prop_link.py` (Python: the controller) and `app/lib/controller/prop_link.dart` (Dart: the phone). Tests: `controller/tests/test_prop_link.py` and `app/test/controller/prop_link_test.dart`.

## Where the controller is

A join payload for a box (kind 0) carries two optional fields when the controller serves HTTPS (RFC 0001 Amendment 4, proposed): key 13 `ca_sha256`, the SHA-256 of the field CA's DER certificate (32 bytes, decision P3-8), and key 14 `urls`, 1-3 `https://host[:port]` base addresses of the controller. Boxes skip both. The phone fetches `GET /api/v1/controller/ca`, checks it against key 13 and trusts that CA for those addresses only, for the length of the game. A payload too long with them is made without them; the phone then asks for the controller's address.

## The link

`WS /api/v1/prop` (`wss://` with the pinned CA). JSON text frames.

1. The controller sends `{"type": "challenge", "nonce": "<32 random bytes, base64url>", "version": 1}`.
2. The prop answers within 10 s with `{"type": "auth", "game_id": G, "node_id": N, "proof": "<base64url>"}`, where
   `proof = HMAC-SHA256(game key, "atalaia-prop-link-v1" 0x00 | nonce | G (2 bytes, big-endian) | N (2 bytes, big-endian))`.
   The game key is the join payload's (16 bytes). The controller checks it in constant time and refuses (`{"type": "refused", "reason": "auth"}`, close code 4401) a wrong proof, a game that is not live here, a node id that is the controller's or not assigned to a role in the game (the join payload assigns it).
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
| `cmd` | `cmd` (`start`, `pause`, `resume`, `end`, `set_owner`, `message`, `reset`, `reboot`), `opcode`, `params`, `dest` (absent: every node) |
| `ack`, `error`, `pong`, `replaced` | as above |

Whatever the controller sends on the radio as TIME or CMD reaches the linked props too; a command for one node reaches only that node's link. Without a radio modem a command reaches the Wi-Fi props and is reported as sent.

## Security

- The link proves the game key without sending it; every game has a new key, so a link ends with its game. Anyone who holds the game key (every box and join card has it) can link as an assigned node: as on the radio, the join payload is the credential (ADR-P2-12).
- Over `wss://` with the pinned field CA the messages are private and cannot be changed on the way. Over plain `ws://` (the controller's HTTP port) they are not; the app uses `wss://` whenever the payload has keys 13 and 14.
- Positions never travel on this link (ADR-P3-6: `POST /api/v1/positions`).
