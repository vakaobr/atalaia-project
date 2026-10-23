# Join payload

A box, or a second field controller standing by, joins a game with a **join payload**: everything it needs to take part, carried by an NFC card, a QR code (or its text) or the serial console (ADR-P2-12, RFC 0001 section 9), or, for a box whose last game is over, inside an INVITE over LoRa sealed with a key derived from the field join key ([field-frames.md](field-frames.md), RFC 0001 Amendment 7, proposed): never in the clear over LoRa. The field controller makes it; this file is its specification, version 1.

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
- a box gets it once, when the field **adopts** it ([adoption.md](adoption.md), decisions AD-1 to AD-14): an NFC field card (MIME type `application/vnd.atalaia.field`, written from the console's *Adopt* tab and tapped on the box), the USB cable from the controller (`@adopt` after `@adopt-info`, the GM confirming the box's name and MAC), and later a pairing code over LoRa; `@joinkey <hex>` on the console and the setup portal's field remain for bring-up. An unadopted box takes the first field's key; a box adopted to another field takes a new one only with its admin PIN. It keeps the key in NVS next to the game key (encrypted NVS on production boxes; plain on development boards, adoption.md section 2).

With the sealed radio invites the join key is the field's **master secret**: a field card holds it, so cards are kept locked away, and a lost card means `join-key --rotate` and adopting every box again (adoption.md section 5).

Game keys change with every game; the join key does not. A box with another field's join key refuses the card ("bad tag").

The join key also keys the **field frames** ([field-frames.md](field-frames.md)): HKDF-SHA256 with the label `atalaia field frame v1` gives the AES-128 key of the announcements, discoveries and invites between games. Whoever holds the join key can therefore read every invite sent over the radio, and the game key inside it: the join key is a field secret (decision RJ-2).

## Body

| Key | Field | Type | Required | Values |
| --- | --- | --- | --- | --- |
| 1 | `game_id` | uint | yes | 1-65534, the game's 16-bit id on the radio |
| 2 | `game_key` | bytes | yes | exactly 16: the game's AES-128 key (ADR-P2-2) |
| 3 | `node_id` | uint | yes | 0-65534: the short id this device takes in the game |
| 4 | `controller_id` | uint | yes | 0-65534: the controller that made the payload; differs from `node_id` |
| 5 | `channel_hz` | uint | yes | the shared game channel (RFC 0001 Amendment 1): the whole channel inside one sub-band of the join's region (key 18; Amendments 3 and 12). EU868: 125 kHz, centre ± 62.5 kHz, inside one EU868 sub-band, so 869462500-869587500 for 869.4-869.65 MHz; AS923-TW: 500 kHz, centre ± 250 kHz, inside 920-925 MHz, so 920250000-924750000 |
| 6 | `max_hops` | uint | yes | 1-3: the relay clamp (ADR-P2-6) |
| 7 | `teams` | array of text | yes | 1-8 different names, 1-23 bytes of UTF-8 each, no NUL; team ids are 1.. in this order |
| 8 | `mode_id` | text | yes | 1-63 bytes, e.g. `org.atalaia.domination`; a main mode with modifiers is joined by `+`, main mode first (`org.atalaia.domination+org.atalaia.codes`, see modes/README.md). For a node, what that node runs: in a game with a role package (`org.atalaia.domination+org.atalaia.medic`), a node with the package's role gets the package's id alone (`org.atalaia.medic`) and the other nodes the main mode with its modifiers; a standby controller gets the whole game's id |
| 9 | `role` | text | yes | 1-31 bytes: the mode role (`zone`), or `controller` for a standby controller |
| 10 | `game_seed` | uint | yes | 32-bit seed for the scripts' `rand()` |
| 11 | `params` | map | no | the preset parameters: text keys, JSON-like values (as CMD `params`); their compact JSON form is at most 200 bytes. For a node, the parameters of the parts it runs (as `mode_id`); for a standby controller, all of them. Absent: the mode's defaults |
| 12 | `kind` | uint | yes | 0 = a node (box, prop), 1 = a standby controller |
| 13 | `ca_sha256` | bytes | no | 32: SHA-256 of the field CA's DER certificate, for an Android prop's Wi-Fi link and a box's firmware updates (P3-8; RFC 0001 Amendment 4, proposed; [firmware-update.md](firmware-update.md)) |
| 14 | `urls` | array of text | no | 1-3 different `https://host[:port]` base addresses of the controller, at most 64 bytes each, for the same link ([prop-link.md](prop-link.md)) |
| 15 | `lang` | text | no | the language of a box's screens (RFC 0001 Amendment 10, proposed): 2-8 bytes of `a-z`, `0-9` and `-`, the first two `a-z` (`pt`, `en`, `pt-br`). Absent: English. A box that does not know the language uses English; the controller puts in the field's setting, or the language of the console the game was created in |
| 16 | `fetch_modes` | bool | no | only `true`, else left out (phase 5 plan phase 13, [mode-packages.md](mode-packages.md) "Fetching missing modes"): a box that lacks a part of `mode_id` accepts the join *fetching* the signed packages it lacks from the controller at key 14's addresses, pinned to key 13 (both needed), and says HELLO only once it has them; without 13 and 14, or firmware that cannot fetch: *no mode* as before |
| 17 | `forget_modes` | bool | no | only `true`, else left out (plan phase 13): before anything else, the box forgets every mode package it fetched before |
| 18 | `region` | uint | no | the field's radio region (RFC 0001 Amendment 12, proposed): 1 = AS923-TW (Taiwan, 920-925 MHz, SF9 at 500 kHz); EU868 (0) is the key left out, and 0 written, an unknown number or anything else is refused. The channel must fit in the region. A box whose firmware is built for another region (Kconfig `ATALAIA_RADIO_REGION`) refuses the join before anything changes; the codecs give it by name (`eu868`, `as923-tw`) |

Encoders write the keys in this order, integers and lengths in their shortest form, and leave `params`, `ca_sha256`, `urls` and `lang` out when there are none, `fetch_modes` and `forget_modes` unless they are `true` (`false` is refused, so a join has one encoding), and `region` for EU868 (0 is refused, for the same reason). Decoders accept the keys in any order, refuse a missing required field, a repeated key, a value of the wrong type or out of range, trailing bytes and any key of 32 or more, and skip the keys they do not know up to 31, which are kept for optional fields a newer controller may add (the tag still covers them). All three codecs (`core/src/join.c`, Python and Dart) read 13, 14 and 15 and skip 16 to 31; boxes use 13 and 14 only for firmware updates (decision FU3-5), and 15 for the language of their screens. The `controller_link` section of the vectors has payloads with keys 13 and 14, and the `box_language` section payloads with key 15 (valid ones, and invalid ones: upper case, empty, one letter, too long, a digit first, an underscore, a number, bytes, null), checked by C, Python and Dart (decision PE4). Firmware from before key 15 skips it, so its screens stay in English. Keys 16 and 17 (plan phase 13): the Python codec reads them (the `mode_fetch` section of the vectors: 4 valid payloads, 6 invalid), `core/src/join.c` from plan phase 13b; the Dart codec still skips them (Android props get modes over their own link in a later slice of PE24), as does firmware before 13b, which answers *no mode*. Key 18 (Amendment 12): all three codecs read it (the `region` section of the vectors: 3 valid payloads, 8 invalid); a reader from before skips it and checks the channel against EU868, so it refuses a Taiwanese join as well. Readers skip 19 to 31.

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

**An invite over LoRa** ([field-frames.md](field-frames.md)): the controller cuts the payload into 1-3 INVITE parts of at most 153 bytes, for a free box's device id and token, sealed with the field frames' key. The box puts the parts back together and takes the payload through exactly the checks below; a typical box's payload is one or two parts.

## What a reader does

A **box** (kind 0) checks the tag with its join key, refuses a controller payload, a mode it does not have (for `main+modifier`, any part it does not have, or parts whose scripts together exceed its 16 KB preset buffer), or a game it cannot fit, then stores the payload in encrypted NVS (ADR-P2-12: the key survives a reboot and is erased when the game ends), tunes to `channel_hz`, clamps relays to `max_hops`, sends HELLO from `node_id`, and waits for the controller's CMD start with the mode loaded for `role`, `teams`, `params` and `game_seed`.

A **standby controller** (kind 1) checks the tag with its own copy of the join key, stores the game, configures its modem with the game key, `node_id` and `channel_hz`, and follows the TIME beacons of `controller_id` (and of whoever wins a later election) until it is promoted (ADR-P2-8).

## Security notes

- **One join, one box** (RFC 0001 Amendment 9, decision BN-18): a box's nonces are its node id's in the game, so a join used on two boxes (one card tapped on two, or a node id issued again) makes them reuse each other's nonces. The controller issues a node id once per game (a replacement box gets a new one) and flags two device ids on one node id in the console. A box refuses a join of a game it played to its end, or of an old game's key it keeps only as retired. Left: a box reflashed with its NVS erased that taps the same card again; re-join it with a new join.

- The tag stops forged cards; it does not stop cloning: anyone who reads a card has that game's key until the game ends (ADR-P2-12 accepts this; a new game gets a new key).
- The QR code and the text carry the game key in clear. Show them only to the people setting up the field.
- An invite carries it encrypted under a key derived from the join key: safe from strangers, but anyone with the join key who recorded the radio can read it, for every game invited that way (decision RJ-2, accepted by the maintainer).
- The join key never leaves the controllers, the boxes' NVS and the field cards made to adopt boxes ([adoption.md](adoption.md)); it is not in a join payload, the API's other answers or the logs.
