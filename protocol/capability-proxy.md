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
| RADIO_FIELD_TX | `0x0C` | phone → pod | id (uint16 BE) + a whole field or pair frame (31-217 or 10-209 bytes): the modem's FIELD_TX |
| RADIO_FIELD_RX | `0x0D` | pod → phone | the frame heard + rssi (int8) + snr (int8): the modem's FIELD_RX |
| RADIO_FIELD_ACK | `0x0E` | pod → phone | id (uint16 BE) + status (1): the modem's FIELD_ACK, statuses 0-8 |

Types `0x05`-`0x0E` are the modem's `0x02`-`0x0B` plus 3, with the same payloads, so the pod reuses the modem's code and the phone the controller's (the phone does what the field controller's Python does with a modem). RADIO_ERROR is an addition to ADR-P3-2, which listed no error frame although every radio command is answered by STATUS or ERROR. RADIO_NOISE, MEASURE and the modem's error codes 7 (busy) and 8 (no_radio) were added to the modem by the channel work (RFC 0001 Amendment 3) after this file was written; the pod runs the modem's code, so they reach the phone the same way (refinement of 2026-10-19, decision PF2; a phone that does not know `0x0B` ignores it, as below). A RADIO_CMD IDENT (opcode `0x07`) is answered with an IDENT frame (`0x01`), not the modem's JSON identity: the phone sends it first on every new link. Other types are ignored (counted, not answered), so a later version can add frames.

**Field and pair frames** (refinement of 2026-10-23, decisions PE24-100 to PE24-103): RADIO_FIELD_TX, RADIO_FIELD_RX and RADIO_FIELD_ACK are the modem's FIELD_TX, FIELD_RX and FIELD_ACK (`0x09`-`0x0B`, [usb-modem.md](usb-modem.md)) plus 3, with the same payloads, so a phone with only a pod can do what a Pi controller does with its modem: sealed invitations and re-invites, GAME_OVER and the other field frames ([field-frames.md](field-frames.md)), and adopting a box by its code (pair frames, message type 10, [adoption.md](adoption.md) section 7), which ride the same three frames. The phone seals and opens them; the pod never holds the field's key and relays the bytes as the modem does, with the modem's code: the shape check (version 1, game 0, type 9 encrypted or type 10 in the clear, the sizes above), `hop_limit` 0 on air, with or without a game configured, refused with status 8 (busy) while a MEASURE runs and 7 (no_radio) without a radio chip, and the same duty-cycle budget as every other transmission. RADIO_FIELD_RX and RADIO_FIELD_ACK go where RADIO_RX goes: to the link that configured the radio, else to the link of the phone's last radio frame (its RADIO_CMD IDENT at least). A pod firmware older than this ignores `0x0C` (counted, unanswered) and says nothing of `field_frames` in IDENT, so the phone knows before trying.

**Firmware updates** (decision PE24-130, 2026-10-26; no change to the wire): a box's update has no frame of its own here. The offer is CMD update (opcode 9, RFC 0001 Amendment 6, [firmware-update.md](firmware-update.md)), an ordinary sealed game packet that the phone sends as RADIO_TX and the pod seals, paces and transmits like any other (the duty-cycle budget, the sub-band's power and the region's channel rule apply; a refusal comes back as RADIO_TX_ACK `duty_cycle`, `queue_full`, `timeout`... for the phone to say so). The box's HELLO (its version) and, for a failure its HTTPS report cannot carry, its `node.update_failed` event come back as RADIO_RX. The image and the signed report travel over the field's Wi-Fi, past the pod. Every pod firmware relays RADIO_TX and RADIO_RX, so IDENT has no key for updates (keys 6-8 tell of frame types an older pod ignores; there is none here): a phone refuses an offer only when the radio cannot carry packets at all, a pod with `has_radio` false or a radio that is down, and says which.

## IDENT, EVT and CMD

CBOR maps with small integer keys, written in key order and in the shortest form (as every Atalaia CBOR payload). Keys this version does not know, from 6 to 23 (from 9 in IDENT), are skipped, so a newer pod may add optional fields; other keys, a repeated key, a missing required field, a value of the wrong type or out of range, and trailing bytes make the payload invalid (the receiver drops it; an EVT or CMD is then not acknowledged).

### IDENT (`0x01`)

| Key | Field | Type | |
| --- | --- | --- | --- |
| 1 | `fw_version` | text, 1-23 printable ASCII bytes (the pod: its image's version, the build metadata shortened to fit, decision FV-5) | required |
| 2 | `capabilities` | array (0-16) of capability descriptors | required |
| 3 | `battery_pct` | uint, 0-100 | left out when unknown |
| 4 | `has_radio` | bool | required |
| 5 | `protocol_version` | uint, 1 | required |
| 6 | `field_frames` | bool: the pod relays field frames (RADIO_FIELD_TX, RX, ACK) | optional; left out by older pods |
| 7 | `pair_frames` | bool: and pair frames (type 10) in them | optional; left out by older pods |
| 8 | `measure` | bool: the pod answers RADIO_CMD MEASURE (it has a radio chip and its firmware measures) | optional; left out by older pods |

Keys 6-8 were added in version 1 (refinement of 2026-10-23, decision PE24-101): optional bools, as the modem's JSON IDENT says `field`, `pair` and `measure`. A reader that knows them refuses a value that is not a bool; a reader that does not skips them (below). The pod firmware writes all three (`field_frames` and `pair_frames` true, `measure` true when it has a radio chip); a reader takes pair frames only from a pod that also says `field_frames`, since they ride the same frames; a pod that leaves them out is older: it measures if it has a radio (every pod firmware so far does) and relays neither. With them, everything a fully fitted pod lends still fits in 256 bytes with a 23-byte `fw_version` (237 bytes); four button colours now make the pod leave the colours out (decision PF6) a few bytes sooner.

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

### The pod's settings over the radio (decision PODC, 2026-10-28; no change to this protocol's frames)

The pod's own settings (the buttons' colours, the ring's brightness, the volume, the enclosure switch) can be pushed by the field controller as CMD pod (opcode 10, a sealed game packet to the phone's node id), which the pod's radio takes itself: [pod-config.md](pod-config.md). Over this link it appears as **one more EVT**: capability `pod`, event `config`, data `{"rev": N}`, sent when the pod has taken (or already had) the settings, which the phone turns into `node.setup_applied` for the controller; and as **one more IDENT**, sent again with the buttons' new colours. A phone that does not know the `pod` capability ignores the EVT (ACK means received). `protocol_version` stays 1.

### A hit sensor (refinement of 2026-10-19, phase 4 plan phase 2)

The design specification's `hit` type (a target addon's piezo plate, decision P4R4; draft RFC 0000 Amendment 1) on this protocol: a descriptor `{"id": "hit", "type": "hit"}`, the event `hit` `{"strength": 0-255}` (the phone gives the script `hit.hit` with the same `strength`) and the commands `arm` and `disarm` without arguments (the sensor reports hits only while armed). No pod built so far has one; the vectors `target_addon`, `target_hit` and `target_arm` fix the bytes for the addon or a pod that will.

### Outputs, and a second hit sensor (refinement of 2026-11-03, draft RFC 0000 Amendment 5)

The design specification's `output` type (a siren, strobe or smoke remote on a simple output or an expansion module's channel; [expansion-port.md](expansion-port.md), decisions EXP-18 to EXP-26 and EXP-36): a descriptor `{"id": "siren", "type": "output"}`, with `"feedback": false` for a simple output, which cannot tell whether anything is plugged in (an expansion module's channel leaves the key out); no events; the commands `on` `{"ms"}` (on for at most that long), `off`, `pulse` `{"ms"}` and `pattern` `{"on_ms", "off_ms", "ms"}`. The id is the output's function (`siren`, `strobe`, `smoke`, `light`, `horn`, else `out.<n>`; a second of the same function `siren.2`). The pod, not the phone, keeps the output safe: when the phone's link drops it turns every output off within 2 s. A pod with two hit sensors names them `hit` and `hit.2`, gives each descriptor its `channel` (1, 2) and adds `channel` to each `hit` event's data. The vectors `pod_outputs_and_two_targets`, `second_target_hit`, `siren_pulse`, `strobe_pattern`, `siren_on_for_at_most_30_s` and `siren_off` fix the bytes. `protocol_version` stays 1: a phone that does not know the type ignores the descriptor.

**The pod's simple outputs** (refinement of 2026-11-04, the RFC's increment 9; no change to the frames). The pod firmware lends its simple outputs (GPIO 33, and GPIO 1 for a second; `firmware/esp32/main/pod/pod_outputs.h`) as above, after its other parts, each enabled output with `"feedback": false` (vector `pod_simple_output`); its use and longest on come from the pod's build, since a pod has no admin PIN. What the pod keeps whatever the phone asks: `ms` 1 to 600000 (required for `on`, `pulse` and `pattern`, as in CMD 12), a pattern's `on_ms` and `off_ms` 500 to 10000, at most the build's longest on, a change at most every 500 ms (a shorter pulse lasts 500 ms; an on within 500 ms of an off is refused); a refused CMD is still acknowledged. Outputs switch on only while a phone is on a link, and the pod turns every output off **at once when its last link goes** (USB unplugged, Bluetooth lost, an EVT nobody acknowledged) and **after 1.5 s without a frame from the phone while one is on**: so while one of its outputs is on, the phone sends the pod a frame at least every 500 ms, a RADIO_CMD PING (vector `cmd_ping`; its STATUS answer is ignored) when it has nothing else to say. Together with the simple output's 0.5 s bursts (a hung pod stops them), an output is off within 2 s of the phone going, in every case. The game's own rules (on only while the game runs, off at its start, pause, end and a halted script, the end's 10 s grace) are the phone's, as a box's shell keeps them (`app/lib/prop/prop_outputs.dart`); the phone also handles CMD 12 for the prop and sends `output.switched`. IDENT still fits in 256 bytes: when a pod with every part and an output does not fit, the pod leaves out, in turn, the buttons' colours and the outputs' `feedback` flags, then the build metadata of `fw_version` (`0.8.0-dev.412+g8560d54`: `0.8.0`), then the outputs (logged).

**The pod's expansion port** (refinement of 2026-11-04, the RFC's increment 9, its port half; draft RFC 0000 Amendment 7; no new frame or IDENT key; decisions EXPI9-18 to EXPI9-26). The pod runs the box's port driver (`firmware/esp32/main/expansion.c`, `expansion_box.c`) on its I2C bus (GPIO 17 and 18, the bus of its keypad's expander, NFC reader and gauge; `firmware/esp32/main/pod/pod_port.h`; `CONFIG_ATALAIA_POD_PORT`, on by default), with the phone in the game's place:

- **A module's hit channels** are lent as `{"id": "hit", "type": "hit"}` (a second `hit.2`, each descriptor then with its `channel`) after the pod's other parts and before its outputs, as Amendments 1 and 5 say. CMD `arm` and `disarm` (no arguments) set which ones report hits; the pod arms a channel only while a phone is on a link, and forgets every arming when the last link goes (the phone arms again when it links again: it tells the pod only while its game runs). A hit is the EVT `hit` `{"strength"}` (with two hit channels `{"strength", "channel"}`; vectors `target_hit`, `second_target_hit`).
- **An output module's channels** are lent as `{"id": "strobe", "type": "output"}`, after the simple outputs and without the `feedback` key (the module reports its relays' state), named as a box names them (the module's hint; a function a simple output already has becomes `siren.2`), with the CMDs and the pod's rules of the simple outputs above, but only on a pod built to lend them (`CONFIG_ATALAIA_POD_MODULE_OUTPUTS`, off by default: a pod has no admin PIN, so building it in enables them, EXP-28), each at most `CONFIG_ATALAIA_POD_MODULE_MAX_ON_S` (30 s by default) and the module's own longest on. **The pod holds the module's lease** (EXP-11): its driver refreshes it while one of the module's outputs should be on, and when the phone's link goes, or the phone falls silent for 1.5 s with an output on, the pod turns every output off and tells the module at once; a pod that stops altogether stops the lease, and the module turns its outputs off within 1.5 s.
- **What the field learns.** After every IDENT, and whenever its modules or lent outputs change while a phone is on a link, the pod sends the EVT `modules` of the pseudo-capability `pod` (as `pod.config`): `{"modules": "<text>", "max_on_s": {"<id>": seconds, ...}}`, the text the `node.modules` event of a box carries ([expansion-port.md](expansion-port.md), section 7: its enabled simple outputs `g33:servo:siren`, then its modules `58:target/1.0.0:hit`, at most 100 bytes) and each lent output's longest on (vector `pod_modules`); a pod with an output fitted (a simple output, or a module's output channel) adds `"withheld": "<text>"` (decision PROPC-6), the outputs it has but does not lend, in `node.outputs_disabled`'s text: a simple output's entry `g33:servo:siren`, then per module, in address order, its entry with only those channels `5c:out4/1.0.0:strobe,out.4` (an output IDENT left out, below, or a module's channel on a pod not built to lend them, PROPC-7), whole entries only within 100 bytes, `""` when it lends every one (vector `pod_modules_withheld`); a pod that lost its last output after naming some sends `""` once. When the three do not fit in one EVT, the two texts without `max_on_s`, then the text alone. A pod with neither outputs nor modules sends nothing. A module that stops answering while a phone is on a link is the EVT `pod` `module_lost` `{"modules": "<its entry>", "reason": "no_answer" | "bad_ident"}` (vector `pod_module_lost`). A change of the lent capabilities (a module plugged in or lost) sends IDENT again on every active link first. The phone tells the controller `node.modules` (when the text changed), `node.outputs_disabled` with `withheld` (just before each `node.modules` and when it changed) and, during a game, `node.module_lost`, and uses `max_on_s` as each output's longest on instead of 30 s ([prop-link.md](prop-link.md)). A phone from before ignores `withheld`. A phone from before ignores both EVTs: `pod` is no capability of IDENT.
- **IDENT's 256 bytes**: the hit sensors' `channel` goes with the colours and the `feedback` flags at the first compaction; after the version's build metadata the outputs go **one at a time, the last first** (the simple outputs come first, then a module's channels in the order found; `POD_IDENT_TRIM`, logged with the ones left out; decisions EXPI9-23, EXPI9-27), and after every output the hit sensors themselves (`POD_IDENT_NO_PORT`, logged). **An output IDENT left out is not lent** (EXPI9-28): the pod turns it off at once if it was on, answers its CMDs as for a capability it does not have (acknowledged, nothing done), leaves it out of `pod.modules` (the text and `max_on_s`; a module left with no channel is left out of the text) and names it in its `withheld`, so the console shows it as an output fitted but not enabled (PROPC-6), and lends it again only when an IDENT lists it; a channel found after an IDENT that left outputs out waits for the next IDENT. A pod with every part and an out4 module lends the module's first channel and leaves out the other three (vector `pod_full_out4_trimmed`); with a target as well, the hit sensor fits and no output does (236 bytes before the outputs, 22 for each), so a pod built for a module still leaves out the parts it does not use. Vector `pod_port_modules` (a button, a target, a simple siren and an out4 module's four channels).

### ACK (`0x04`) and retries

Each side numbers its EVT (pod) or CMD (phone) frames with its own `seq` (uint16, wrapping) and the other side answers each with ACK carrying that `seq`. A frame not acknowledged within 500 ms is sent again, unchanged, up to 3 times; after that the link is considered broken and the phone reconnects (USB first, then BLE). A receiver acknowledges a repeated frame again but acts on it once (it remembers the last 16 `seq` values). Radio frames are not acknowledged at this layer: LoRa has its own ACKs.

How the pod keeps this (refinement of 2026-10-19, decision PF5): a link is active once the phone has sent a valid frame on it (or, over Bluetooth, once the link is ready, below); EVTs go to every active link, and an ACK on either clears them; replies go back on the link the request came on. The `seq` values remembered are per link and forgotten on a new connection and on every RADIO_CMD IDENT, since a new phone client numbers its CMDs from 0 again. An EVT sent 4 times without an ACK makes the pod's links inactive (the EVTs waiting are dropped) until the phone speaks again. The game key lives in the pod's RAM only, as in the modem: it is forgotten (CLEAR) when the link that sent CONFIGURE goes or breaks, so a phone that links again sends IDENT and CONFIGURE again, with a new epoch. RADIO_RX, RADIO_TX_ACK, RADIO_NOISE, RADIO_FIELD_RX and RADIO_FIELD_ACK go to the link that configured the radio (without one, to the link of the phone's last radio frame).

## USB-OTG

The pod is a USB CDC ACM device (the ESP32-S3's USB-Serial-JTAG or TinyUSB CDC); the phone opens it with Android's `UsbManager` and reads and writes raw bytes. 921600 baud where a baud rate applies. USB is preferred when both links are up: lower latency, no pairing, and the phone powers the pod.

The pod firmware uses the USB-Serial-JTAG port, as the USB radio modem does (decision PF3): the Heltec V4's only USB port, no extra component, and flashing keeps working. It ignores the baud rate. Its DTR and RTS lines can reset the chip (RTS set with DTR clear): a phone sets both together, or neither. The log console stays on UART0.

## Bluetooth Low Energy

The UUIDs start with the ASCII bytes of "Atalaia" (`41 74 61 6C 61 69 61`):

| | UUID | Properties | |
| --- | --- | --- | --- |
| Service | `4174616c-6169-6100-0000-000000000000` | | advertised; device name `atalaia-pod-XXXX` (last 4 hex digits of the MAC) |
| Pod TX | `4174616c-6169-6100-0000-000000000001` | Notify | pod → phone: IDENT, EVT, ACK, RADIO_RX, RADIO_TX_ACK, RADIO_STATUS, RADIO_ERROR, RADIO_NOISE, RADIO_FIELD_RX, RADIO_FIELD_ACK |
| Pod RX | `4174616c-6169-6100-0000-000000000002` | Write Without Response | phone → pod: CMD, ACK, RADIO_TX, RADIO_CMD, RADIO_FIELD_TX |
| Pod Status | `4174616c-6169-6100-0000-000000000003` | Read, Notify | 3 bytes, no framing: battery % (0xFF unknown), RSSI of the last radio packet (int8, 0x80 none), flags (bit 0 radio present, bit 1 radio configured, bit 2 USB host connected) |

(ADR-P3-2 gave the service the UUID it also gave Pod TX; the service takes `...0000`.) The phone asks for an MTU of at least 247 bytes; a frame of up to 262 bytes may span two notifications or writes, which the receiver joins (the framing finds the boundaries). One phone at a time; on disconnect the pod advertises again.

The pod firmware (refinement of 2026-10-19, decision PF4): the advertising data holds the flags and the service UUID, the scan response the name. On a connection the pod asks the phone to pair (LE Secure Connections, Just Works: the pod has no display or keys; bonded, so it is asked once); Pod RX takes only encrypted writes, and frames go out only on an encrypted link with Pod TX notifications on, because RADIO_CMD CONFIGURE carries the game key. The link is ready at that moment, and the pod then sends its IDENT unasked (the phone's own IDENT request may have been written before the link was encrypted, and is dropped). Pod Status can be read without pairing. Just Works protects against listening, not against someone who pairs first at the field: the radio key is still forgotten when that phone goes.

Refinement of 2026-11-04 (decisions PODPK-1 to PODPK-11): pairing is by **passkey entry**, so it is protected against a man in the middle. The pod's IO capability is DisplayOnly: it shows a random 6-digit passkey on the board's OLED (and in its log) and the phone types it. The pod's Security Request asks for MITM protection and bonding; frames go out and Pod RX takes writes only on a link encrypted with a key made by passkey entry (authenticated; Pod RX is also marked for authenticated writes). A failed or timed-out pairing drops the link; a phone connected 60 s without a secure link is dropped (HCI reason 0x13). A bond that is not authenticated (made by an older pod with Just Works), or one the pod does not have, is forgotten by the pod, which drops the link with **HCI reason 0x05, Authentication Failure**: the phone removes its own bond and pairs again. The board's PRG button held 5 s clears every bond. Nothing in the framing changes.

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
