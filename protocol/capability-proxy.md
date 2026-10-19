# Capability proxy protocol v1

An **I/O pod** is an ESP32 board (a Heltec WiFi LoRa 32 V4.3 or smaller) that lends its hardware to an Android phone: big buttons, an LED ring, a siren, an NFC reader and a LoRa radio (ADR-P3-2, ADR-P3-3). The pod runs no scripts; the phone runs the mode and talks to the pod over USB-OTG or Bluetooth Low Energy with the frames below. To a script on the phone, a pod's button is the same as a box's. Thin nodes (design specification section 7) use the same frames.

This file is the protocol's specification, version 1 (`protocol_version: 1` in IDENT). Frozen: a change needs a new version. Shared vectors: [`vectors/capability_proxy.yaml`](vectors/capability_proxy.yaml), checked by the C codec (`core/src/proxy.c` with `firmware/esp32/main/modem/modem_framing.c`: `core/tests/test_proxy.c`, `firmware/esp32/test/test_proxy_codec.c`) and the Python one (`simulator/atalaia_sim/capability_proxy.py`: `simulator/tests/test_capability_proxy.py`). The app's Dart codec passes them too (`app/lib/pod/pod_codec.dart`: `app/test/pod/codec_test.dart`), and its pod client (`app/lib/pod/pod_client.dart`) does the ACKs and retries below. The pod's side is the I/O pod firmware (`firmware/esp32/main/pod/`, plan phase F), which the app's tests and the controller's run on the host (`firmware/esp32/test/pod_host`).

## Frames

The USB radio modem's framing ([usb-modem.md](usb-modem.md)), on both transports:

```
0xA5 | type (1) | length (2, big-endian) | payload (0-256 bytes) | CRC-16 (2, big-endian)
```

The CRC is CRC-16/CCITT-FALSE (polynomial 0x1021, initial value 0xFFFF, no reflection, no final XOR; `crc("123456789") = 0x29B1`) over the type, length and payload. A receiver skips bytes until a `0xA5`, reads the length and accepts the frame only when the CRC matches; on a bad length (above 256) or CRC it drops that `0xA5` and searches again from the next byte. Over BLE the sync byte and the CRC are sent too: one parser for both transports.

| Type | Value | Direction | Payload |
| --- | --- | --- | --- |
| IDENT | `0x01` | pod → phone | CBOR map: what the pod is and has |
| EVT | `0x02` | pod → phone | CBOR map: a capability's event |
| CMD | `0x03` | phone → pod | CBOR map: a command for a capability |
| ACK | `0x04` | both | seq (uint16, big-endian) of the EVT or CMD received |
| RADIO_RX | `0x05` | pod → phone | header (9) + plaintext payload + rssi (int8) + snr (int8) + epoch (uint16 BE): the modem's RX |
| RADIO_TX | `0x06` | phone → pod | header (9) + plaintext payload (up to 200): the modem's TX |
| RADIO_TX_ACK | `0x07` | pod → phone | seq (uint16 BE) + status (1): the modem's TX_ACK, statuses 0-7 |
| RADIO_CMD | `0x08` | phone → pod | opcode (1) + parameters: the modem's CMD, opcodes 1-8 |
| RADIO_STATUS | `0x09` | pod → phone | JSON: the modem's STATUS |
| RADIO_ERROR | `0x0A` | pod → phone | code (1) + UTF-8 message: the modem's ERROR, codes 1-8 |
| RADIO_NOISE | `0x0B` | pod → phone | 17 bytes: the modem's NOISE, the answer to MEASURE (opcode 8) |

Types `0x05`-`0x0B` are the modem's `0x02`-`0x08` plus 3, with the same payloads, so the pod reuses the modem's code and the phone the controller's (the phone does what the field controller's Python does with a modem). RADIO_ERROR is an addition to ADR-P3-2, which listed no error frame although every radio command is answered by STATUS or ERROR. RADIO_NOISE, MEASURE and the modem's error codes 7 (busy) and 8 (no_radio) were added to the modem by the channel work (RFC 0001 Amendment 3) after this file was written; the pod runs the modem's code, so they reach the phone the same way (refinement of 2026-10-19, decision PF2; a phone that does not know `0x0B` ignores it, as below). A RADIO_CMD IDENT (opcode `0x07`) is answered with an IDENT frame (`0x01`), not the modem's JSON identity: the phone sends it first on every new link. Other types are ignored (counted, not answered), so a later version can add frames.

## IDENT, EVT and CMD

CBOR maps with small integer keys, written in key order and in the shortest form (as every Atalaia CBOR payload). Keys this version does not know, from 6 to 23, are skipped, so a newer pod may add optional fields; other keys, a repeated key, a missing required field, a value of the wrong type or out of range, and trailing bytes make the payload invalid (the receiver drops it; an EVT or CMD is then not acknowledged).

### IDENT (`0x01`)

| Key | Field | Type | |
| --- | --- | --- | --- |
| 1 | `fw_version` | text, 1-23 printable ASCII bytes | required |
| 2 | `capabilities` | array (0-16) of capability descriptors | required |
| 3 | `battery_pct` | uint, 0-100 | left out when unknown |
| 4 | `has_radio` | bool | required |
| 5 | `protocol_version` | uint, 1 | required |

A capability descriptor is a map with text keys, as in the node descriptor of the design specification (section 7): `{"id": "btn.red", "type": "button", "team": "red"}`, `{"id": "ring", "type": "led", "count": 24, "rgb": true}`. `id` and `type` are required; other keys carry the type's details. Values are what JSON can hold (no byte strings).

### EVT (`0x02`) and CMD (`0x03`)

| Key | EVT | CMD | Type | |
| --- | --- | --- | --- | --- |
| 1 | `cap_id` | `cap_id` | text, 1-23 bytes of `a-z 0-9 . _ -` | required |
| 2 | `event` | `method` | text, 1-23 bytes of `a-z 0-9 . _ -` | required |
| 3 | `data` | `args` | map with text keys (JSON values) | left out when empty |
| 4 | `seq` | `seq` | uint, 0-65535 | required |

Events and commands are those of the standard capability types (design specification section 7): a button's `press`, `hold` (`{"ms": 5000}`) and `release`; an NFC reader's `tag` (`{"uid": "04a1b2c3d4e5f6", "tag": "<hex of the card's player-tag record, up to 52 bytes>"}`, `tag` left out when the card has none; join cards are not forwarded, the phone joins by QR code or text); a ring's `fill` (`{"team": "red"}`); a speaker's `tone` (`{"freq": 2000, "ms": 150}`). The phone turns a pod's events into the inputs the core expects (`team_input.hold`, `nfc.tag` with the tag checked: [nfc-tag.md](nfc-tag.md)), exactly as a box's shell does.

### What the I/O pod lends (refinement of 2026-10-19, plan phase F)

The pod firmware lists only what is fitted, in this order, so that everything fits in IDENT's 256 bytes with the longest `fw_version` (decision PF6):

| `id` | `type` | Events | Commands (CMD `args`) |
| --- | --- | --- | --- |
| `btn.1`-`btn.4` | `button` | `press`, `hold` `{"ms"}` every 250 ms with the time held so far, `release` `{"ms"}` | |
| `keypad` | `keypad` | `key` `{"key": "0"-"9", "*", "#"}`, once per stroke | `clear` |
| `ring` | `led` (`count`) | | `fill` `{"team"}` (or `{"args": [team]}`, or `{"r","g","b"}`), `color` `{"r","g","b"}` or `{"args": [r, g, b]}`, `off`, `set_brightness` `{"args": [percent]}`, `progress` `{"args": [0-1]}` (the first part of the ring in the last colour) |
| `audio` | `audio` | | `tone` `{"freq","ms"}`, `play` `{"args": [clip]}` (the pod has no sound files: the mode's clips are played as tones), `stop`, `set_volume` `{"args": [percent]}` |
| `nfc` | `nfc` | `tag` as above | |
| `case` | `tamper` | `opened`, `closed`: the enclosure switch, armed once it has read closed | |

These confirm the argument shapes the app chose before the pod existed (decision PD16, confirmed in PF7): a script's `ring:fill(team)` and `team_display:show(team)` (the phone sends it to the pod's `led`) become `fill {"team"}`, `audio.play(clip)` becomes `play {"args": [clip]}`. A CMD the pod has no part or method for is still acknowledged (ACK means received) and counted.

A button without `team` stands for the game's N-th team for `btn.N`, as a Field Box's button N; a builder may give a button a colour (`"team": "red"`), which the phone uses when the game has a team of that name. `tamper` is a new capability type, in the draft RFC with the phase 3 additions (`docs/rfcs/0000-phase-3-events-tags-and-pods.md`); the phone reports `opened` during a game as `node.tamper` with `reason: pod_opened`. The battery level is in IDENT (`battery_pct`) and in Pod Status, not in events.

### ACK (`0x04`) and retries

Each side numbers its EVT (pod) or CMD (phone) frames with its own `seq` (uint16, wrapping) and the other side answers each with ACK carrying that `seq`. A frame not acknowledged within 500 ms is sent again, unchanged, up to 3 times; after that the link is considered broken and the phone reconnects (USB first, then BLE). A receiver acknowledges a repeated frame again but acts on it once (it remembers the last 16 `seq` values). Radio frames are not acknowledged at this layer: LoRa has its own ACKs.

How the pod keeps this (refinement of 2026-10-19, decision PF5): a link is active once the phone has sent a valid frame on it (or, over Bluetooth, once the link is ready, below); EVTs go to every active link, and an ACK on either clears them; replies go back on the link the request came on. The `seq` values remembered are per link and forgotten on a new connection and on every RADIO_CMD IDENT, since a new phone client numbers its CMDs from 0 again. An EVT sent 4 times without an ACK makes the pod's links inactive (the EVTs waiting are dropped) until the phone speaks again. The game key lives in the pod's RAM only, as in the modem: it is forgotten (CLEAR) when the link that sent CONFIGURE goes or breaks, so a phone that links again sends IDENT and CONFIGURE again, with a new epoch. RADIO_RX, RADIO_TX_ACK and RADIO_NOISE go to the link that configured the radio.

## USB-OTG

The pod is a USB CDC ACM device (the ESP32-S3's USB-Serial-JTAG or TinyUSB CDC); the phone opens it with Android's `UsbManager` and reads and writes raw bytes. 921600 baud where a baud rate applies. USB is preferred when both links are up: lower latency, no pairing, and the phone powers the pod.

The pod firmware uses the USB-Serial-JTAG port, as the USB radio modem does (decision PF3): the Heltec V4's only USB port, no extra component, and flashing keeps working. It ignores the baud rate. Its DTR and RTS lines can reset the chip (RTS set with DTR clear): a phone sets both together, or neither. The log console stays on UART0.

## Bluetooth Low Energy

The UUIDs start with the ASCII bytes of "Atalaia" (`41 74 61 6C 61 69 61`):

| | UUID | Properties | |
| --- | --- | --- | --- |
| Service | `4174616c-6169-6100-0000-000000000000` | | advertised; device name `atalaia-pod-XXXX` (last 4 hex digits of the MAC) |
| Pod TX | `4174616c-6169-6100-0000-000000000001` | Notify | pod → phone: IDENT, EVT, ACK, RADIO_RX, RADIO_TX_ACK, RADIO_STATUS, RADIO_ERROR |
| Pod RX | `4174616c-6169-6100-0000-000000000002` | Write Without Response | phone → pod: CMD, ACK, RADIO_TX, RADIO_CMD |
| Pod Status | `4174616c-6169-6100-0000-000000000003` | Read, Notify | 3 bytes, no framing: battery % (0xFF unknown), RSSI of the last radio packet (int8, 0x80 none), flags (bit 0 radio present, bit 1 radio configured, bit 2 USB host connected) |

(ADR-P3-2 gave the service the UUID it also gave Pod TX; the service takes `...0000`.) The phone asks for an MTU of at least 247 bytes; a frame of up to 262 bytes may span two notifications or writes, which the receiver joins (the framing finds the boundaries). One phone at a time; on disconnect the pod advertises again.

The pod firmware (refinement of 2026-10-19, decision PF4): the advertising data holds the flags and the service UUID, the scan response the name. On a connection the pod asks the phone to pair (LE Secure Connections, Just Works: the pod has no display or keys; bonded, so it is asked once); Pod RX takes only encrypted writes, and frames go out only on an encrypted link with Pod TX notifications on, because RADIO_CMD CONFIGURE carries the game key. The link is ready at that moment, and the pod then sends its IDENT unasked (the phone's own IDENT request may have been written before the link was encrypted, and is dropped). Pod Status can be read without pairing. Just Works protects against listening, not against someone who pairs first at the field: the radio key is still forgotten when that phone goes.

## Example

A pod's red button held for 5 s, the pod's 8th event: EVT `{1: "btn.red", 2: "hold", 3: {"ms": 5000}, 4: 7}`.

```
a5 02 00 15                       sync, EVT, length 21
a4                                map of 4
   01 67 62 74 6e 2e 72 65 64        cap_id: "btn.red"
   02 64 68 6f 6c 64                 event: "hold"
   03 a1 62 6d 73 19 13 88           data: {"ms": 5000}
   04 07                             seq: 7
xx xx                             CRC-16
```

The phone answers `a5 04 00 02 00 07 xx xx` (ACK, seq 7). The exact bytes, CRCs included, are in the vectors.
