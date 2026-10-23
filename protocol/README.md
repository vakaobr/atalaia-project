# Skirmesh-RF

Skirmesh-RF is the Atalaia field protocol. The same messages travel over LoRa, Wi-Fi, BLE, USB serial and the internet; only the encoding differs:

- **LoRa**: compact CBOR with integer keys, authenticated with a per-game key.
- **Wi-Fi, BLE, API**: JSON with readable keys.

Both encodings come from the schema files in [`schema/`](schema/), so they cannot drift apart.

| Path | Contents |
| --- | --- |
| [`schema/messages.yaml`](schema/messages.yaml) | Packet header and message types (draft) |
| [`schema/events.yaml`](schema/events.yaml) | Standard events: ids, priorities, CBOR keys and data fields (draft) |
| [`vectors/events.yaml`](vectors/events.yaml) | Test vectors every event codec must pass |
| [`vectors/*.json`](vectors/) | Test vectors for header and message payload codecs, the join payload (`join.json`), field frames (`field_frame.json`: RFC 5869's HKDF-SHA256 vectors, sealed announcements, discoveries and invites, refusals, invite parts; written by `tools/field_frame_vectors.py`), the NFC field card that adopts a box (`field_card.json`), pairing a box by its code (`pairing.json`: CPace's draft vectors and the pair frames), player tags (`tag.json`), chrono records (`chrono_record.json`), player tokens (`player_token.json`), the controller sync's bodies (`sync.json`), the field controller's REST API (`controller_api.json`: contract cases run against the Pi controller and the Android controller, decision PE24-4), the Android prop link's proof (`prop_link.json`), the ATAK emitter's CoT, byte for byte on both controllers (`atak_xml.json`, written by `tools/atak_xml_vectors.py`) and firmware releases (`firmware.json`: RFC 8032's Ed25519 vectors, signed manifests, versions, image descriptors, reports) |
| [`vectors/capability_proxy.yaml`](vectors/capability_proxy.yaml) | Test vectors for the capability proxy (I/O pod) frames and payloads |
| [`vectors/geo.json`](vectors/geo.json) | Known answers (each with its source and tolerance), edge cases, argument errors and exact result bits for `geo.distance` and `geo.in_zone` (ADR-P4-9) |
| [`vectors/composition.yaml`](vectors/composition.yaml) | How a game's parts compose: main modes, modifiers, role packages and scenarios (decision P4R7), the mode id and parameters each role's join carries, the order of the `field.lua` scripts, and the ids and packages refused; read by the simulator and the app's Dart test runner |
| [`join.md`](join.md) | The join payload that brings a box or a standby controller into a game (NFC card, QR code, serial console, or an invite over the radio) |
| [`adoption.md`](adoption.md) | Adopting a box: how it gets the field join key once (the NFC field card, the USB cable, the pairing code over the radio: CPace, message type 10), its adoption state and who may move it, where the key is kept, rotating the key, threat models; vectors in `vectors/field_card.json` |
| [`field-frames.md`](field-frames.md) | Field frames, the radio outside any game (RFC 0001 Amendment 7, proposed): a free box's announcement, the controller's DISCOVER and its INVITE into the next game, and GAME_OVER for a game whose boxes must leave it (addendum of 2026-10-22), sealed with a key derived from the field join key (HKDF-SHA256); vectors in `vectors/field_frame.json` |
| [`nfc-tag.md`](nfc-tag.md) | Player tags: the signed NFC tag of a player (Kill Confirmed, Respawn, Player Check-in, the Medic Kit) |
| [`chrono-record.md`](chrono-record.md) | Chrono records: one chronograph reading signed with the marshal's Ed25519 key, and the canonical JSON that is signed |
| [`player-token.md`](player-token.md) | Player tokens: who a phone calling the controller's API is (player, team, squad, role, game), signed by the controller |
| [`checkin.md`](checkin.md) | Field check-in: the printed poster's `atalaia:checkin:` text, trusting the field's CA, the check-in endpoints, per-game replica declarations and the "replicas to chrono" list; vectors in `vectors/checkin.json` |
| [`prop-link.md`](prop-link.md) | An Android prop's link to the controller over Wi-Fi: the HMAC proof of the game key, HELLO, STATE and events up, TIME and commands down; with an I/O pod, the field's radio as well, and which one is used when |
| [`firmware-update.md`](firmware-update.md) | Firmware updates for the Field Box over the field's Wi-Fi: the signed release (Ed25519 over a fixed manifest), CMD update (opcode 9), the image's descriptors, HTTPS pinned to the field CA, the box's checks, rollback and report; vectors in `vectors/firmware.json` |
| [`mode-packages.md`](mode-packages.md) | Signed mode packages: the canonical ustar archive, the manifest a mode key signs (Ed25519, as firmware releases), the checks before a controller installs one, the registry index and revocation list (JSON Schemas in `registry/schema/`); vectors in `vectors/mode_package.json` |
| [`sync.md`](sync.md) | The controller sync: how a field controller pushes its games, event logs, score counters and nodes, and the field's chrono registry (marshals' public keys, replicas, signed readings), to a site server, the merge rules, the API key; vectors in `vectors/sync.json` |
| [`usb-modem.md`](usb-modem.md) | The serial link between the field controller and its USB radio modem |
| [`capability-proxy.md`](capability-proxy.md) | The link between an I/O pod and a phone (USB-OTG and BLE), version 1 |
| [`json/event.schema.json`](json/event.schema.json) | JSON Schema of an event in the game log and the API (generated) |
| [`json/examples/`](json/examples/) | Events that CI validates against that schema, plus invalid ones it must reject |

## Changing the schema

1. Edit `schema/*.yaml`. Changes to standard events, protocol fields or keys need an RFC (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
2. Run `python3 tools/protogen.py` (it needs only PyYAML) and commit the generated files with the schema.
3. Run `tools/check.sh`. CI fails if a generated file is out of date.

The generator writes these files; none of them should be edited by hand:

| Generated file | For |
| --- | --- |
| `core/include/atalaia/protocol.h`, `core/src/protocol.c` | C: constants, ids, keys, payload field enums and lookup tables |
| `core/tests/protocol_vectors.h` | C: event codec test vectors |
| `core/tests/packet_vectors.h` | C: header, payload, AES-CCM, join and player tag test vectors (from `vectors/*.json`) |
| `core/tests/proxy_vectors.h` | C: capability proxy test vectors (from `vectors/capability_proxy.yaml`) |
| `firmware/esp32/test/firmware_vectors.h` | C: the Field Box's firmware update vectors (from `vectors/firmware.json`) |
| `core/tests/pair_vectors.h` | C: CPace's draft vectors and the pair frames (from `vectors/pairing.json`), core and firmware tests |
| `firmware/esp32/test/field_card_vectors.h` | C: the Field Box's field card vectors (from `vectors/field_card.json`) |
| `core/tests/geo_vectors.h` | C: geo test vectors, as exact hexadecimal doubles (from `vectors/geo.json`) |
| `core/tests/field_frame_vectors.h` | C: HKDF and field frame test vectors (from `vectors/field_frame.json`) |
| `simulator/atalaia_sim/protocol.py` | Python: the same tables |
| `protocol/json/event.schema.json` | Anyone consuming events as JSON |

Ids and keys are never reused once protocol v1 is frozen. Until then they may change.

## Events on LoRa

An EVENT message carries one event as a CBOR map with integer keys. The codecs are [`core/src/codec.c`](../core/src/codec.c) (C, used on every node) and [`simulator/atalaia_sim/codec.py`](../simulator/atalaia_sim/codec.py) (Python).

| Key | Field | Value |
| --- | --- | --- |
| 1 | `node` | Source node short id, 0 to 65535 |
| 2 | `seq` | Per-node sequence number, 0 to 65535 |
| 3 | `t` | Game time in milliseconds, 0 to 2³²−1 |
| 4 | `type` | A standard event's id, or the event name as text (custom events) |
| 5 | `team` | Team id, 1 to 250; left out for none |
| 6 | `squad` | Squad id, 1 to 255; left out for none |
| 7 | `prio` | 0 telemetry, 1 normal, 2 critical; left out when it is the event's default |
| 8 | `data` | The event data as a map; left out when empty |

In `data`, the names in `data_fields` become their integer key (`team` is 1, `reason` is 3, and so on), and every other key stays text. Values are what JSON can hold: integers that fit in 64 bits, finite floats, text, booleans, null, arrays and maps with text keys.

For example, red arming the bomb (`bomb.armed`, team 1, `{"fuse_s": 300, "team": "red"}`) takes 24 bytes:

```
a6                      map of 6
   01 01                node: 1
   02 01                seq: 1
   03 19 13 88          t: 5000
   04 07                type: bomb.armed (id 7)
   05 01                team: 1
   08 a2                data: map of 2
      07 19 01 2c          fuse_s: 300
      01 63 72 65 64       team: "red"
```

Encoders write integers, lengths and floats in their shortest form (a float uses half, single or double precision, whichever keeps its exact value). They keep map entries in the order of the input; the core writes data keys in sorted order. Decoders accept only this subset of CBOR and reject anything else:

- byte strings, tags, indefinite lengths, `undefined` and other simple values, NaN and infinity;
- invalid UTF-8, duplicate keys (a field sent both by key and by name counts as a duplicate), and trailing bytes;
- unknown envelope keys, event ids and data keys;
- data nested more than 16 levels deep, or more than 128 keys in the data maps open at once.

## Events as JSON

In the game log and on the API, an event is a JSON object with readable names. Nodes still use short ids on the field, and the field controller turns them into names:

```json
{
  "id": "box-a3f1:1842", "t": 734210, "node": "box-a3f1",
  "type": "code.used", "team": "blue", "squad": "blue-2",
  "data": { "code": "HINT-07", "kind": "hint" }, "prio": "normal"
}
```

[`json/event.schema.json`](json/event.schema.json) checks the envelope, that the type is standard or named `x.<club>.<name>`, and that a standard event carries only its own data fields (plus `team` and `squad`) with the right types.

## In the simulator

Mode tests fail when a script emits an event that is not in the schema, gives it a data field it does not have or a value of the wrong type, or produces a payload larger than the 200 bytes a LoRa packet can carry. Custom events (`x.<club>.<name>`) can carry any data, but still have to fit.

## Message payloads (RFC 0001)

Every non-EVENT message carries a CBOR payload with integer keys, defined in `schema/messages.yaml` under `payloads`. The generator emits C enum constants (`ATALAIA_PL_{MSG}_{FIELD}`) and a Python `PAYLOAD_FIELDS` dict. Test vectors live in `vectors/{message}.json` and are shared by the C and Python codecs.

| Message | Required fields | Optional fields |
| --- | --- | --- |
| HELLO | node_name, platform, fw_version, core_version, tier, capabilities, transports, epoch | battery_pct |
| ACK | ack_node, ack_seq | ack_bitmap |
| STATE | owner_team, phase, game_time_ms, counters, epoch | rssi, battery_pct, flags |
| CMD | cmd | params, dest |
| TIME | game_time_ms, game_state, duration_ms, wall_s, term | tx_time_us |
| CONFIG | mode_id, role, params, teams, game_seed | |
| CLAIM | term, priority, node_id | last_ack_seq |

EVENT (type 2) payloads are defined separately in `schema/events.yaml`.

Both codecs follow the schema field for field. Encoders always write every required field, even when it is 0 or empty; `array_uint8` is a CBOR array, `map_*` types and CMD `params` are CBOR maps (`params` with text keys). The C decoders (`core/src/msg_codec.c`) reject a payload that misses a required field, repeats a key, has trailing bytes or holds a value too large for its field; the Python side reports the same problems with `atalaia_sim.packet.payload_problems`. Every valid vector must decode and re-encode byte for byte in both languages, and every invalid one must be rejected: the tests no longer skip a vector they cannot read.

### What a Field Box sends and expects

A box in a game (`firmware/esp32/main/radio/field_link.c`) sends HELLO after it joins or reboots, every game event as EVENT, and STATE every 15 seconds and after a capture. Normal and critical events and HELLO ask for an ACK and are sent again, in a new packet, every 3 seconds until one arrives (normal events give up after 10 tries). In STATE, `counters` holds the points each team **gained** on the box, `owner_team` the team of its last capture, and `phase` the box's game state (0 waiting, 1 running, 2 paused, 3 ended). It follows the TIME beacons of the controller with the highest term (and acts on a start, pause or end it missed), takes CMDs for its node id or for every node (opcode 8, a mode command, reaches the mode as `cmd.mode`: RFC 0001 Amendment 5; opcode 9 offers a firmware update, refused while a game is played: Amendment 6, [firmware-update.md](firmware-update.md)), and relays every authenticated packet once (hop_limit is the number of relays left, clamped to the join's `max_hops`). Decisions E6-E10 in `docs/review/decisions-to-review.md`.

## Joining a game

A box or a standby controller joins with a join payload: a version byte, a CBOR map with integer keys and an HMAC-SHA256 tag keyed with the field's join key, on an NFC card or as `atalaia:join:` text. See [join.md](join.md) and RFC 0001 Amendment 2.

## The USB radio modem

The field controller reaches the radio through a modem board on USB. Its framing, commands and status codes are in [usb-modem.md](usb-modem.md).

## Phase 3: player tags, I/O pods and new events

- **Player tags** ([nfc-tag.md](nfc-tag.md)): a version byte, the player id, the team, the game id and a 16-byte HMAC-SHA256 under the game key, on an NFC tag as an `application/vnd.atalaia.tag` record. The node's host checks a tag and gives the mode `nfc.tag`.
- **Capability proxy v1** ([capability-proxy.md](capability-proxy.md)): an I/O pod lends its buttons, LEDs, NFC reader and radio to a phone, with the USB modem's framing: IDENT, EVT, CMD and ACK (CBOR), and the modem's radio frames shifted by 3 (NOISE included since plan phase F). The pod's side is `firmware/esp32/main/pod/`; the refinements made while building it are dated in the file.
- **Events** 25-27 and 33-41 (ADR-P3-8): `kill.confirmed`, `kill.denied`, `team.eliminated`, `money.collected`, `money.deposited`, `chrono.checkin`, `chrono.spotcheck`, `visibility.granted`, `visibility.expired`, `node.tamper`, `pod.connected`, `pod.disconnected`; data keys 29 (`see_team`) and 30 (`tolerance_pct`). The phase 2 mode pack holds 28-32; phase 4 starts at 42. Proposed in a draft RFC ([docs/rfcs/0000-phase-3-events-tags-and-pods.md](../docs/rfcs/0000-phase-3-events-tags-and-pods.md)).

### Header `version_flags` byte

| Bits | Field | Values |
| --- | --- | --- |
| 7-5 | version | 1 (current) |
| 4-3 | priority | 0 telemetry, 1 normal, 2 critical |
| 2 | ack_req | 1 = request ACK |
| 1 | encrypted | 1 = AES-CCM MIC present |
| 0 | reserved | must be 0 |

All multi-byte header fields are big-endian.

## AES-128-CCM

Every LoRa packet is authenticated and encrypted with a per-game AES-128 key.
See [RFC 0001](../docs/rfcs/0001-skirmesh-rf-wire-format.md) for the full specification.

- **Key**: 16 bytes, generated by the controller at game creation, distributed during join.
- **Nonce** (13 bytes): `game_id(2) + source(2) + (epoch << 16 | seq)(4) + zeros(5)`. The epoch is per game key (RFC 0001 Amendment 9, proposed): a node's first start in a game is epoch 1, each restart in the same game the next; the key is named in the node's store by a tag (`vectors/epoch_tag.json`).
- **AAD** (8 bytes): header bytes 0-6 plus byte 8 (everything except `hop_limit`).
- **Tag**: 8 bytes (64-bit MIC). Forgery probability 2^-64.

Test vectors with real AES-CCM ciphertext are in `vectors/aes_ccm.json`, shared by both the C (mbedtls) and Python (`cryptography`) codecs. The C and Python tests also verify against RFC 3610 Packet Vector 1.

## Not yet defined

- Sending a team's name in `data.team` as well as its id in the envelope is redundant on LoRa. Every node now learns the game's teams from its join payload, so the name could be dropped; that change to the event encoding needs an RFC.
- Penalties: STATE carries only the points gained per team, so a box's penalties (`score.delta` events) are logged but not subtracted from the totals (decision E6).
