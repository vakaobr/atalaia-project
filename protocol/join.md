# Join payload

A box, or a second field controller standing by, joins a game with a **join payload**: everything it needs to take part, carried by an NFC card, a QR code (or its text) or the serial console, and never over LoRa (ADR-P2-12, RFC 0001 section 9). The field controller makes it; this file is its specification, version 1.

Implementations: [`core/src/join.c`](../core/src/join.c) (C: boxes, the host test programs), [`simulator/atalaia_sim/join.py`](../simulator/atalaia_sim/join.py) (Python: the field controller) and [`app/lib/protocol/join_payload.dart`](../app/lib/protocol/join_payload.dart) (Dart: Android props joining by QR code, card or text, and the marshal's tag writer). All check the shared vectors in [`vectors/join.json`](vectors/join.json): 4 valid payloads (decode, re-encode byte for byte, text form, NFC tag memory, refused under another key), 38 invalid ones that must fail with the stated reason, an optional-field case, and RFC 4231 HMAC-SHA256 known answers.

## Layout

```
version (1 byte) | body (CBOR map) | tag (32 bytes)
```

- **version** is 1. A reader refuses any other value.
- **body** is a CBOR map with integer keys (below).
- **tag** is HMAC-SHA256 over the version byte and the body, keyed with the field's **join key**.
- The whole payload is 34 to 448 bytes, so it fits an NTAG215 card (504 bytes of user memory) with its NDEF headers.

A reader checks the tag first, in constant time, and reads the body only if it matches. The game key is therefore only accepted from someone who holds the join key.

## The join key

ADR-P2-2 and ADR-P2-12 authenticate the payload with "the controller's long-term key", so every reader must hold the same key. It is a 32-byte random **field join key**, made once per field (not per game):

- the field controller generates it on first start and keeps it in its store; `python -m atalaia_controller join-key` prints it as 64 hex digits, and `[join] key = "..."` in `controller.toml` sets it (so a second controller can share it);
- a box gets it once, when the field owner sets the box up (decision E2 in `docs/review/decisions-to-review.md`), and keeps it in encrypted NVS next to the game key.

Game keys change with every game; the join key does not. A box with another field's join key refuses the card ("bad tag").

## Body

| Key | Field | Type | Required | Values |
| --- | --- | --- | --- | --- |
| 1 | `game_id` | uint | yes | 1-65534, the game's 16-bit id on the radio |
| 2 | `game_key` | bytes | yes | exactly 16: the game's AES-128 key (ADR-P2-2) |
| 3 | `node_id` | uint | yes | 0-65534: the short id this device takes in the game |
| 4 | `controller_id` | uint | yes | 0-65534: the controller that made the payload; differs from `node_id` |
| 5 | `channel_hz` | uint | yes | the shared game channel (RFC 0001 Amendment 1): the whole 125 kHz channel, centre ± 62.5 kHz, inside one EU868 sub-band (Amendment 3), so 869462500-869587500 for 869.4-869.65 MHz |
| 6 | `max_hops` | uint | yes | 1-3: the relay clamp (ADR-P2-6) |
| 7 | `teams` | array of text | yes | 1-8 different names, 1-23 bytes of UTF-8 each, no NUL; team ids are 1.. in this order |
| 8 | `mode_id` | text | yes | 1-63 bytes, e.g. `org.atalaia.domination`; a main mode with modifiers is joined by `+`, main mode first (`org.atalaia.domination+org.atalaia.codes`, see modes/README.md). For a node, what that node runs: in a game with a role package (`org.atalaia.domination+org.atalaia.medic`), a node with the package's role gets the package's id alone (`org.atalaia.medic`) and the other nodes the main mode with its modifiers; a standby controller gets the whole game's id |
| 9 | `role` | text | yes | 1-31 bytes: the mode role (`zone`), or `controller` for a standby controller |
| 10 | `game_seed` | uint | yes | 32-bit seed for the scripts' `rand()` |
| 11 | `params` | map | no | the preset parameters: text keys, JSON-like values (as CMD `params`); their compact JSON form is at most 200 bytes. For a node, the parameters of the parts it runs (as `mode_id`); for a standby controller, all of them. Absent: the mode's defaults |
| 12 | `kind` | uint | yes | 0 = a node (box, prop), 1 = a standby controller |
| 13 | `ca_sha256` | bytes | no | 32: SHA-256 of the field CA's DER certificate, for an Android prop's Wi-Fi link and a box's firmware updates (P3-8; RFC 0001 Amendment 4, proposed; [firmware-update.md](firmware-update.md)) |
| 14 | `urls` | array of text | no | 1-3 different `https://host[:port]` base addresses of the controller, at most 64 bytes each, for the same link ([prop-link.md](prop-link.md)) |

Encoders write the keys in this order, integers and lengths in their shortest form, and leave `params`, `ca_sha256` and `urls` out when there are none. Decoders accept the keys in any order, refuse a missing required field, a repeated key, a value of the wrong type or out of range, trailing bytes and any key of 32 or more, and skip the keys they do not know up to 31, which are kept for optional fields a newer controller may add (the tag still covers them). All three codecs (`core/src/join.c`, Python and Dart) read 13 and 14 and skip 15 to 31; boxes use 13 and 14 only for firmware updates (decision FU3-5). The `controller_link` section of the vectors has payloads with keys 13 and 14, checked by C, Python and Dart (decision PE4).

Role packages (the Medic Kit, modes/README.md) change no field and no encoding: the controller only chooses `mode_id` and `params` per node by its role, so a box composes what it is given exactly as before (decision MK9).

The fields beyond ADR-P2-12's first list (`controller_id`, `channel_hz`, `max_hops`, `game_seed`, `kind`) are what a box and a standby controller turned out to need: the channel to listen on, the relay clamp ADR-P2-6 says the join carries, who to follow before the first TIME beacon, and the scripts' seed. Decision E1.

## Carriers

**NFC card** (NTAG215 or NTAG216, NFC Forum Type 2): the user memory from page 4 holds an NDEF message TLV (`0x03`, length, message) and the terminator TLV (`0xFE`). The message is one MIME record (TNF 2, MB and ME set; short record when the payload is under 256 bytes) of type `application/vnd.atalaia.join` whose payload is the join payload. Readers skip NULL and lock or memory control TLVs before the message and look for the first record of that type.

**Text** (QR code, serial console, copy and paste): `atalaia:join:` followed by the payload in base64url without padding (RFC 4648 section 5), for example

```
atalaia:join:AasBGRCSAlArfhUWKK7Spqv3FYgJz088AwcEAAUaM9PmCAYC...
```

Readers ignore spaces and line ends around it and refuse anything that is not canonical base64url.

A box reads cards through its NFC reader and the text on its serial console as one line, `@join atalaia:join:...` (bring-up and the Wokwi emulator). A standby controller takes the text through `POST /api/v1/controller/join`. Boxes cannot scan QR codes; ADR-P2-12's "push over Wi-Fi" needs a box-side endpoint that does not exist yet (decision E3).

## What a reader does

A **box** (kind 0) checks the tag with its join key, refuses a controller payload, a mode it does not have (for `main+modifier`, any part it does not have, or parts whose scripts together exceed its 16 KB preset buffer), or a game it cannot fit, then stores the payload in encrypted NVS (ADR-P2-12: the key survives a reboot and is erased when the game ends), tunes to `channel_hz`, clamps relays to `max_hops`, sends HELLO from `node_id`, and waits for the controller's CMD start with the mode loaded for `role`, `teams`, `params` and `game_seed`.

A **standby controller** (kind 1) checks the tag with its own copy of the join key, stores the game, configures its modem with the game key, `node_id` and `channel_hz`, and follows the TIME beacons of `controller_id` (and of whoever wins a later election) until it is promoted (ADR-P2-8).

## Security notes

- The tag stops forged cards; it does not stop cloning: anyone who reads a card has that game's key until the game ends (ADR-P2-12 accepts this; a new game gets a new key).
- The QR code and the text carry the game key in clear. Show them only to the people setting up the field.
- The join key never leaves the controllers and the boxes' encrypted NVS; it is not in the payload, the API or the logs.
