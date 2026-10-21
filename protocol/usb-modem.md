# USB radio modem framing

The field controller (a Raspberry Pi) has no radio of its own. A second Heltec WiFi LoRa 32 V4.3 is plugged into it over USB and runs the **modem firmware**, a build variant of the box firmware (ADR-P2-4, ADR-P2-5). The modem does the radio work: SX1262, AES-128-CCM, dedupe and duty cycle. The controller sends and receives *plaintext* Skirmesh-RF payloads over the serial link. This file is the link's specification, version 1 (`"framing": 1` in IDENT).

Implementations: `firmware/esp32/main/modem/modem_framing.c` and `modem.c` (the modem), `controller/atalaia_controller/modem_framing.py` and `radio_modem.py` (the controller). The controller's tests run against the modem's C code on Linux (`firmware/esp32/test/modem_host/`).

## Frames

```
0xA5 | type (1) | length (2, big-endian) | payload (0-256 bytes) | CRC-16 (2, big-endian)
```

`type`, `length` and `payload` are the ADR-P2-4 frame. The sync byte and the CRC are additions (decision D1 in `docs/review/decisions-to-review.md`): the serial line also carries the ESP32-S3 ROM boot text, and the controller may open the port in the middle of a frame, so a receiver must be able to find the next frame. The CRC is **CRC-16/CCITT-FALSE** (polynomial 0x1021, initial value 0xFFFF, no reflection, no final XOR; `crc("123456789") = 0x29B1`) over the type, length and payload.

A receiver skips bytes until a `0xA5`, reads the length, and accepts the frame only when the CRC matches. On a bad length (above 256) or a bad CRC it drops only that `0xA5` and searches again from the next byte, so a real frame that starts inside the rejected bytes is still found.

| Type | Direction | Payload |
| --- | --- | --- |
| `0x01` IDENT | modem → controller | JSON: `fw`, `fw_version`, `core_version`, `framing`, `radio` (`"sx1262"` or `"none"`), `payload_max`, `epoch_window`, `measure` (true when the modem can answer MEASURE: it has a radio and its firmware knows the command), `field` (true: the firmware carries field frames), `pair` (true: and pair frames, type 10) |
| `0x02` RX | modem → controller | header (9) + plaintext payload + rssi (int8) + snr (int8) + epoch (uint16 BE) |
| `0x03` TX | controller → modem | header (9) + plaintext payload (up to 200) |
| `0x04` TX_ACK | modem → controller | seq (uint16 BE) + status (1) |
| `0x05` CMD | controller → modem | opcode (1) + parameters |
| `0x06` STATUS | modem → controller | JSON, the reply to every successful CMD |
| `0x07` ERROR | modem → controller | code (1) + UTF-8 message |
| `0x08` NOISE | modem → controller | the result of a MEASURE command (below), 17 bytes |
| `0x09` FIELD_TX | controller → modem | id (uint16 BE) + a whole field frame, 31-217 bytes ([field-frames.md](field-frames.md)) |
| `0x0A` FIELD_RX | modem → controller | a field frame as heard + rssi (int8) + snr (int8) |
| `0x0B` FIELD_ACK | modem → controller | id (uint16 BE) + status (1), the outcome of a FIELD_TX |

The **epoch** at the end of RX is an addition to ADR-P2-4 (decision D2): it is the nonce epoch that authenticated the packet. A box restarts its sequence numbers at 0 with every new epoch (each reboot), so the controller needs it to tell a rebooted box's new packets from old ones and to acknowledge them per epoch. `snr` is sent as 0 until the radio HAL reports it.

## TX and TX_ACK

The controller owns its own nonce counter (ADR-P2-2): it chooses `seq` and tells the modem its epoch with CONFIGURE, storing the epoch +1 in SQLite before the first packet of every run and again when `seq` wraps. The modem sets the encrypted bit, clears the reserved bit, clamps `hop_limit` to the configured maximum, encrypts with the game key and the controller's epoch, and queues the packet for the radio. As a safety net it refuses any packet whose `(epoch << 16) | seq` is not above the last one it sent. The TX_ACK comes when the radio has an outcome:

| Status | Meaning |
| --- | --- |
| 0 ok | sent |
| 1 duty_cycle | the duty-cycle budget is exhausted; not sent |
| 2 timeout | radio error or TX timeout |
| 3 not_configured | no game key yet |
| 4 invalid | bad header, another game, not the controller's source, or payload over 200 bytes |
| 5 nonce_reuse | (epoch, seq) not above the last one sent: refused |
| 6 queue_full | the radio queue is full |
| 7 no_radio | no radio chip answered at boot |
| 8 busy | (FIELD_ACK only) a MEASURE is running |

`duty_cycle` follows the channel in use: the budget is the duty cycle of the channel's EU868 sub-band (10% of a sliding hour on 869.4-869.65 MHz, 1% on 868.0-868.6 and 869.7-870.0 MHz, 0.1% on 868.7-869.2 MHz), counted per sub-band, and a packet is refused when its LoRa time on air (SF7, 125 kHz) does not fit in what is left. The TX power follows the sub-band too: 500 mW ERP on 869.4-869.65 MHz, 25 mW elsewhere, less the front-end module's and the antenna's gains (RFC 0001 Amendment 3, decision C2).

0-2 are ADR-P2-4's; 3-7 are additions (decision D3); 8 came with the field frames (decision RJ-10).

## Field frames: FIELD_TX, FIELD_RX, FIELD_ACK

Between games, boxes and controllers exchange **field frames** ([field-frames.md](field-frames.md), RFC 0001 Amendment 7, proposed): message type 9 with game id 0, sealed with a key derived from the field join key, which the modem never holds. It carries them as they are, whether a game is configured or not:

- **FIELD_TX**: the controller's id for it (its FIELD_ACK names it) and the whole frame, sealed by the controller. The modem checks only the shape (version 1, encrypted, game 0, type 9, 31-217 bytes), forces `hop_limit` to 0 (outside the MIC, so it still holds) and queues it on its current channel, the duty cycle counting as for any packet. FIELD_ACK: `ok`, `duty_cycle`, `timeout`, `invalid` (not a field frame's shape), `queue_full`, `no_radio`, or `busy` while a MEASURE runs. It never touches the game's nonce counter.
- **FIELD_RX**: every packet heard with that shape, before any game check, with its RSSI and SNR. No dedupe and no relay: field frames are not flooded.
- **Pair frames** ([adoption.md](adoption.md) section 7, RFC 0001 Amendment 8): message type 10 with game id 0, *not* encrypted (their security is CPace's, between a controller and an unadopted box), 10-209 bytes, go and come the same way, in FIELD_TX and FIELD_RX, with the same `hop_limit` 0 and duty-cycle rules; the shape check takes either type. IDENT says `"pair": true` when the firmware carries them.

## RX

The modem forwards a packet only if it belongs to the configured game, carries the encrypted bit, is not its own packet relayed back, authenticates, and has not been forwarded in the last 30 seconds (dedupe on source, epoch and seq: flood copies arrive several times). The modem never relays: the controller does not rebroadcast (ADR-P2-6).

To authenticate, the modem tries the source's last known epoch and then up to `epoch_window` epochs above it (16 by default, `CONFIG_ATALAIA_MODEM_EPOCH_WINDOW`), or epochs 0 to `epoch_window` for a source it has not heard yet; never a lower epoch, so replays stay rejected. ADR-P2-2 tries only one epoch above, which never recovers a box that rebooted twice out of range (decision D4). The controller can also tell the modem a box's epoch with SET_PEER_EPOCH; it does so after every reconnect, from the epochs it has seen.

## Commands

Every command except PING, IDENT and MEASURE is answered by a STATUS frame when it succeeds, or by an ERROR frame when it fails; MEASURE is answered by a NOISE frame when its dwell is over.

| Opcode | Command | Parameters |
| --- | --- | --- |
| `0x01` | PING | token (uint32 BE), optional; STATUS echoes it as `"ping"` |
| `0x02` | CONFIGURE | game_id (2), node_id (2), epoch (2), max_hops (1), channel_hz (4), key (16): 27 bytes, all big-endian |
| `0x03` | SET_CHANNEL | channel_hz (uint32 BE) |
| `0x04` | STATUS | none |
| `0x05` | SET_PEER_EPOCH | any number of (source uint16, epoch uint16) pairs |
| `0x06` | CLEAR | none: forget the key and the game (sent when the game ends) |
| `0x07` | IDENT | none: answered with IDENT |
| `0x08` | MEASURE | channel_hz (uint32 BE), dwell_ms (uint16 BE, 10-10000), flags (1; bit 0: also count LoRa channel-activity detections): answered with NOISE |

Field frames go and come in their own frame types (FIELD_TX, FIELD_RX, FIELD_ACK, above), not as commands.

A **channel** (CONFIGURE, SET_CHANNEL, MEASURE) is accepted only when the whole 125 kHz LoRa channel fits inside one EU868 sub-band: centre - 62.5 kHz and centre + 62.5 kHz both within 868.0-868.6, 868.7-869.2, 869.4-869.65 or 869.7-870.0 MHz (RFC 0001 Amendment 3). 869.40 MHz, for example, is refused: its channel starts at 869.3375 MHz. Anything else is ERROR `bad_params`.

The game key lives only in the modem's RAM. A modem that reboots has forgotten it; the controller notices (missed pings or a closed port), reconnects, asks for IDENT and sends CONFIGURE again.

STATUS is a JSON object with `cmd`, `configured`, `radio`, `game_id`, `channel_hz`, `duty_ms` (the duty-cycle budget left on the channel's sub-band), `uptime_s`, `rx`, `rx_auth_fail`, `tx`, `tx_fail`, `measuring` (a MEASURE is running) and, for PING, `ping`.

| Error | Meaning |
| --- | --- |
| 1 bad_frame | valid CRC but malformed content |
| 2 unknown_type | a frame type the modem does not accept |
| 3 unknown_cmd | unknown CMD opcode |
| 4 not_configured | needs CONFIGURE first |
| 5 radio | the radio refused a setting |
| 6 bad_params | a parameter out of range (a channel that does not fit in an EU868 sub-band, max_hops above 3, a MEASURE dwell outside 10-10000 ms) |
| 7 busy | MEASURE while a game is configured or another MEASURE runs; CONFIGURE or SET_CHANNEL while a MEASURE runs |
| 8 no_radio | MEASURE on a modem without a radio chip (for example the Wokwi emulator) |

## MEASURE and NOISE

The field controller's "find a quiet channel" (controller/README.md) asks the modem to listen to each candidate channel in turn. MEASURE tunes the radio to `channel_hz` and keeps it receiving for `dwell_ms`, reading the SX1262's instantaneous RSSI (GetRssiInst) about once a millisecond; with flag bit 0 it also runs a channel-activity detection (CAD: two LoRa symbols at SF7, 125 kHz) every 100 ms, which detects LoRa preambles even below the noise. Nothing is transmitted, so measuring uses no duty cycle. Then the radio goes back to its channel and the modem answers with one NOISE frame:

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 4 | channel_hz (uint32 BE) |
| 4 | 2 | dwell_ms (uint16 BE) |
| 6 | 2 | samples: RSSI readings (uint16 BE, saturating) |
| 8 | 1 | min_dbm (int8) |
| 9 | 1 | mean_dbm (int8): the mean of the dBm readings, rounded |
| 10 | 1 | p50_dbm (int8): median |
| 11 | 1 | p90_dbm (int8): 90th percentile |
| 12 | 1 | max_dbm (int8) |
| 13 | 2 | cad_tries (uint16 BE) |
| 15 | 2 | cad_detected (uint16 BE): tries that found LoRa activity |

Readings are kept in 1 dB steps from -128 to 0 dBm. The modem measures only while no game is configured (measuring takes the radio off the game channel), one MEASURE at a time; a failure is an ERROR whose message starts with `MEASURE`, so the controller can tell it from other errors. The dwell is at most 10 s per command; the controller splits a scan's total time across the channels. The RSSI statistics and the CAD settings have not been checked on a real SX1262 yet (plan phase F).

## Watchdog

The controller pings every 5 seconds. After 3 unanswered pings, or when the port fails, it closes and reopens the port and sends IDENT and CONFIGURE again; after 3 failed reconnects it reports `radio.down` to the GM console and keeps retrying every 10 seconds, reporting `radio.up` when the modem answers. On the modem, the ESP-IDF task watchdog reboots it if its loop hangs for 5 seconds.

## The link

By default the modem uses the ESP32-S3's built-in USB-Serial-JTAG port (it appears as `/dev/ttyACM0`), and its log console stays on UART0 only, so log text never mixes with frames. Boards that put a USB-UART bridge on UART0 can select `CONFIG_ATALAIA_MODEM_LINK_UART0` (921600 baud by default) and must move the console off UART0. The controller opens the port without toggling DTR and RTS, which would reset an ESP32-S3.
