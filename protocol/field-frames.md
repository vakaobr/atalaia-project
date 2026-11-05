<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Field frames: boxes between games

A box whose game is over can be invited into the next game over the radio, without a card, a QR code or the serial console. This file specifies the **field frames** that make it possible, version 1: RFC 0001 Amendment 7 (proposed, 2026-10-21) its addendum of 2026-10-22 (GAME_OVER) Amendment 19 of 2026-10-29 (MOVE) and Amendment 28 of 2026-11-05 (RELEASE, proposed), decisions RJ-1 to RJ-15, OT-7 to OT-16, RB-1 to RB-12 and STUCK-50 to STUCK-59 in [`docs/review/decisions-to-review.md`](../docs/review/decisions-to-review.md).

Implementations: [`core/src/field_frame.c`](../core/src/field_frame.c) (the codec, C: boxes and the host test programs) and [`simulator/atalaia_sim/field_frame.py`](../simulator/atalaia_sim/field_frame.py) (Python: the field controller and the simulator); the box's behaviour is [`firmware/esp32/main/box_lobby.c`](../firmware/esp32/main/box_lobby.c), the controller's [`controller/atalaia_controller/reinvite.py`](../controller/atalaia_controller/reinvite.py), both modelled in [`simulator/atalaia_sim/lobby.py`](../simulator/atalaia_sim/lobby.py); the Android field controller's (slice S7c of PE24) are [`app/lib/protocol/field_frame.dart`](../app/lib/protocol/field_frame.dart) and [`app/lib/controller/controller_boxes.dart`](../app/lib/controller/controller_boxes.dart). All check the shared vectors in [`vectors/field_frame.json`](vectors/field_frame.json): RFC 5869's HKDF-SHA256 cases, the field key, 13 valid bodies and frames, 10 frames and 58 bodies that must be refused, the invite parts of three join payloads. `tools/field_frame_vectors.py` writes the file (and `--check`s it), with the cryptography library's AES-CCM and HKDF.

## The idea

- A box with no game, or whose game is over, **announces** itself now and then on its last channel: its device id, a fresh **token**, its name, its last game and role.
- A field controller hears the announcements through its USB modem and lists the free boxes in the GM console; it may ask "who is free?" (**DISCOVER**) and the free boxes answer at once.
- The GM picks boxes for the next game; the controller makes each one's join payload exactly as for a card ([join.md](join.md)) and sends it in an **INVITE** addressed to the box's device id and carrying the token of its last announcement.
- The box takes it only when it has no game (or its game is over), only with its current token, and puts the payload through every check a card goes through. It answers with an announcement saying how it went, changes its token, and joins: its HELLO in the new game (with its device id) closes the invite.

- When the field's channel changes, the controller says so on the old channel in a **MOVE** (the new channel and a revision), so the free boxes follow it, and a GM's *Find boxes* sweeps the earlier channels for boxes that were away (Amendment 19).
- When a game ends, the controller also says so in a **GAME_OVER** (the game id and its key's tag), so that a box still in it leaves: the only way when the controller restarted without the game's key (decision OT-7). It says it again when it hears a box still in a game that is over (one that was switched off at the end), at most once a minute (STUCK-1).
- A controller that lost a game entirely (reinstalled, its database lost) has no tag to name it: on the GM's word it says **RELEASE** (the live game, or none, and its clock), and every box in another game that it joined before then leaves it (Amendment 28).

Nothing about a game changes: the game itself still runs under its own key; field frames are the way in, and a way out for a controller that lost the game's key.

## On air

```
header (9) | nonce (13) | body (AES-128-CCM) | MIC (8)
```

| Field | Value |
| --- | --- |
| header | RFC 0001 section 2: `version_flags` 0x2A (version 1, normal priority, no ACK, encrypted), `game_id` **0**, `source` 0, `seq` 0, `hop_limit` **0**, `type` **9** (`FIELD`) |
| nonce | 13 bytes in the clear, never random: the sender's pseudonym (8), its boot count (3), its frame count (2) |
| body | a CBOR map (below), at most 187 bytes, so the whole frame is at most 217 bytes, as a game packet |
| MIC | 8 bytes |

- **Key**: `HKDF-SHA256(salt = none, IKM = the 32-byte field join key, info = "atalaia field frame v1", L = 16)` (RFC 5869; no salt is 32 zero bytes). The join payload's HMAC still uses the join key itself; the label keeps the two uses apart.
- **AAD**: the header without `hop_limit` (bytes 0-6 and 8), as for game packets. So the frame's type, its game id 0 and the zero source and seq are authenticated; `hop_limit` is not, and field frames are never relayed: a sender writes 0, the modem forces 0, a box never repeats one.
- **Nonce** (decision RJ-15): `HMAC-SHA256(nonce key, sender id)[0..7] | boot (3 bytes) | ctr (2 bytes)`, big-endian, where the nonce key is `HKDF-SHA256(join key, info = "atalaia field nonce v1", L = 32)`. The **sender id** is 8 bytes: a box's device id; a controller's is drawn fresh from `os.urandom` (Linux's CSPRNG) at every start and never stored, so nothing persisted can roll back (a restored backup or SD card image, a standby built from a copy of the primary's database) and a standby always has another. A **box's boot count** is kept in NVS (`ff_boot`), raised and stored *before* the first frame of every run, and raised again when the frame count would pass 65535; only "none stored yet" starts it at 0, any other read error, or a failed write, stops its field frames (logged once), and at 16,777,215 it stops for good. A **controller's** boot count lives only in that run (1, then 2 after 65,536 frames). **A box's NVS must never be copied to another board**: the two would share a device id and a boot count, and so nonces. The **frame count** starts at 0 with every boot count. So two frames of one sender never share a nonce, and two senders differ in their pseudonym (a 64-bit PRF of distinct ids), whatever the quality of any random number generator: a repeated nonce under the field key would break CCM's confidentiality and its MICs. A receiver does not check the layout (any 13 bytes open); the pseudonym tells strangers nothing of the device id or the hardware, but stays the same for a sender (a box can be followed as "some box" within a field).
- A receiver checks the shape first (version 1, encrypted, game 0, type 9, 31-217 bytes), then the MIC, and ignores anything else silently: another field's frames do not open, and neither do a stranger's.

## Bodies

Integer keys, in this order, in the shortest form, optional fields left out. Key 1, the **kind**, comes first in every body. Decoders refuse an unknown kind, a missing or repeated field, a value of the wrong type or out of range, a key another kind uses, keys from 32 up and trailing bytes, and skip unknown keys up to 31 (later optional fields).

**ANNOUNCE** (kind 1), box to controllers:

| Key | Field | Type | Required | Values |
| --- | --- | --- | --- | --- |
| 2 | `device_id` | bytes | yes | 8: the box's device id (below) |
| 3 | `token` | bytes | yes | 8: the box's current token |
| 4 | `name` | text | yes | 1-24 bytes: the box's name (its HELLO `node_name`) |
| 5 | `tier` | uint | yes | 0 full, 1 reduced, 2 proxy |
| 6 | `last_game` | uint | no | 1-65534: the last game it played |
| 7 | `last_role` | text | no | 1-31 bytes: its role in that game |
| 8 | `battery_pct` | uint | no | 0-100 |
| 9 | `answer` | uint | no | 1-65535: the invite this announcement answers |
| 10 | `result` | uint | with 9 | 0 accepted, 1 busy, 2 refused, 3 no mode, 4 not a box's join, 5 storage, 6 radio, 7 ended |

**DISCOVER** (kind 2), controller to every box: no other field.

**INVITE** (kind 3), controller to one box:

| Key | Field | Type | Values |
| --- | --- | --- | --- |
| 2 | `device_id` | bytes | 8: the box it is for |
| 3 | `token` | bytes | 8: the token of the box's announcement |
| 4 | `invite_id` | uint | 1-65535, random per invite |
| 5 | `part` | uint | 0 to `parts` - 1 |
| 6 | `parts` | uint | 1-3 |
| 7 | `chunk` | bytes | 1-153: this part of the join payload |

**GAME_OVER** (kind 4, RFC 0001 Amendment 7's addendum of 2026-10-22), controller to the boxes of one game:

| Key | Field | Type | Values |
| --- | --- | --- | --- |
| 4 | `game_id` | uint | 1-65534: the game that is over |
| 5 | `key_tag` | bytes | 8: its game key's tag, `HMAC-SHA256(game key, "atalaia epoch tag")[:8]`, the epoch store's name for the key ([vectors/epoch_tag.json](vectors/epoch_tag.json)) |

**MOVE** (kind 5, RFC 0001 Amendment 19), controller to every free box:

| Key | Field | Type | Values |
| --- | --- | --- | --- |
| 4 | `channel_hz` | uint | 1-4294967295: the field's new channel, in Hz |
| 5 | `rev` | uint | 1-4294967295: a revision that only rises; a box takes a MOVE only above the last it took (serial arithmetic) |

**RELEASE** (kind 6, RFC 0001 Amendment 28), controller to every box of the field:

| Key | Field | Type | Values |
| --- | --- | --- | --- |
| 4 | `live_game` | uint | 0-65534: the sender's live game, whose boxes stay; 0 when no game is live |
| 5 | `time` | uint | 1-4294967295: the sender's wall clock when it was made, in Unix seconds |

Both keys are required; keys 2 and 3 and the other kinds' keys (6-10) are refused, as are a `live_game` of 65535 and a `time` of 0 or past 32 bits.

Keys 2 and 3 (a device, a token) are refused: a MOVE is for every box of the field, not one. The decoder also refuses a missing key, a value of 0 or past 32 bits, and the other kinds' keys (6-10).

The join payload ([join.md](join.md): version, CBOR body, HMAC-SHA256 tag) is cut into chunks of 153 bytes, the last one shorter, and the parts concatenated in order give it back. Three parts hold the largest join payload (448 bytes); a typical box's join is 115-300 bytes, one or two parts (with the field CA and the controller's addresses for firmware updates, two). An INVITE's other fields take at most 34 bytes, so a part never exceeds the 187-byte body. A part of another invite, token or part count starts the reassembly over.

## The box

- **Device id**: 8 bytes made once, at the first start with a field join key, and kept in NVS (encrypted NVS only on a production-provisioned box, which no released image is yet: SECURITY.md) until NVS is erased. Not derived from the MAC address: the id travels only in sealed frames and in HELLO (under the game key), and is the same kind of id an Android prop can keep (decision RJ-6). It comes from the box's seeded generator (decision RJ-15): at boot, before any ADC or I2S driver starts, the shell collects 32 bytes with `bootloader_random_enable()` (the SAR ADC's noise feeds the RNG, which ESP-IDF otherwise calls only pseudo-random without Wi-Fi or Bluetooth), and every request is SHA-256 of that seed, the board's MAC, a counter and fresh `esp_fill_random` bytes. Tokens come from the same generator. HELLO carries the device id as key 10 (`device_id`, optional; [schema/messages.yaml](schema/messages.yaml)).
- **Token**: 8 random bytes from the box's seeded generator, new at every start and every 10 minutes (the previous one still counts until the next change), and **dropped together with the previous one** whenever the box answers an invite (accepted, busy or refused), joins a game in any way (card, QR code, serial console, invite) and when its game ends. So only the token of the box's latest announcement works, at most once, and an invite recorded and played back later never does (decision RJ-8). An invite with neither token is refused without an answer. The box answers each invite once in 10 s (it remembers its last eight) and sends at most six answers a minute in all.
- **Free** means: no game joined, or its game over (BOX_ENDED, or left), and no game picked on the box itself being played. A box in a game answers an invite with its current token "busy" and goes on playing.
- **Announcements**, on the channel of its last game, or the field's after a MOVE (the radio keeps listening there after a game; a new box listens on 869.525 MHz; the box stores that channel when a game's join or a MOVE sets it and goes back to it after a reboot): the first one 2-20 s after its game ends or after it starts (spread so that a field's boxes do not all talk at once), then every `max(60 s, airtime / (2 % x duty cycle))` with ±10 % jitter, so they take at most 2 % of the sub-band's duty-cycle budget. A DISCOVER is answered after 0-3 s, unless the box announced within the last quarter of that interval.
- **An invite**: for its device id, with its current or previous token, all parts there: refused "ended" if the join is for a game the box has played to its end (it remembers its last four), else taken through the card's path (the HMAC with the join key, a box's payload, the mode installed, stored in NVS, the channel, a new epoch, HELLO). A box whose game is over but not yet left (BOX_ENDED, waiting for the last ACKs) leaves it first. The answer goes 100-600 ms later, one per invite in 10 s.
- **Screens**: "Invited · game: role" when it joins from an invite; 30 s after a game ends the final screen gives way to "Ready · next game" (not over the preset picker), on the TFT and the on-board OLED.
- **MOVE** (Amendment 19): the field's channel changed. A free box (no game, or its game over; not one fetching its modes) takes it when `rev` is above the last revision it took (`rev - last` in 1 to 2^31 - 1, mod 2^32) and `channel_hz` is a channel of its region (the whole channel inside one sub-band): it listens there, stores the channel and the revision in NVS (`field_move`), forgets that it has announced (a DISCOVER on the new channel is answered at once) and announces itself 6-15 s later, when the controller's MOVEs are over. A repeat of the same revision, an older one, another region's channel or a box in a game changes nothing (`moves_refused`). A box from before refuses the kind as unknown and stays where it is.
- **RELEASE** (Amendment 28): a box in a game (joined or playing; not one fetching its modes, which is not on its game's link yet and keeps nothing over a reboot) ends it exactly as on a matching GAME_OVER (the mode's game over, announcing itself, "Ready", the game kept as played to its end) when **all** of these hold, and otherwise changes nothing (`releases_refused`, logged):
  1. `live_game` is 0 or is not the box's game id (the live game's boxes stay);
  2. the box knows when it joined its game: **the wall clock (`wall_s`) of the first TIME it took in that game**, a TIME that passed the game key's MIC and the replay and ordering rules (Amendment 23). The box keeps it in NVS (`join_time`: the game key's tag, 8 bytes, and the time, 4) the first time, so a box switched off and on is still in the game *and* still knows it; a new game's join starts without one. A box that never took a TIME of its game refuses every RELEASE;
  3. `time` is **greater** than that join time (plain unsigned comparison of 32-bit Unix seconds, good until 2106; not serial arithmetic).

  So a RELEASE recorded and played back once the box is in a newer game is refused: that game's first TIME came after the recording was made. It needs no counter on the box and no state on the controller, which may have lost everything. A box from before refuses kind 6 as unknown and stays in its game (`@leave` takes it out).
- **GAME_OVER** (decision OT-13): a box in a game (joined, or playing) whose game id and game key's tag both match ends it exactly as on CMD end (the mode's game over, then announcing itself and "Ready", BN-10 to BN-13). Any other GAME_OVER changes nothing: another game's, or its game id under another key (`games_over_refused`, logged). It needs no time or counter: a game's end is a fact that stays true, so one played back later can only end that same game, which the box no longer joins (played to its end, BN-19), and a later game with the same id has another key, so another tag. A box never leaves a game on its own when the controller goes silent (the maintainer's choice: a box cannot tell a controller gone from one briefly out of reach, or a failover). A box that missed its GAME_OVER (switched off when the game ended) is taken out at the box instead: its admin menu's "Leave the game" or `@leave <admin PIN>` on the USB console do exactly what a matching GAME_OVER does, with no frame on the air (decisions STUCK-20 to STUCK-33).

## The controller

- The USB modem carries field frames as they are, with or without a game configured, and never holds the field key: FIELD_TX, FIELD_RX and FIELD_ACK frames ([usb-modem.md](usb-modem.md)).
- It keeps the free boxes it hears (name, device id, RSSI and SNR, when, last game and role, token) for 2 hours, and marks the previous game's boxes: the nodes of the most recent other game whose HELLO carried a device id, with their roles. It keeps, per device id, the highest (boot, count) of the box's nonces it has heard and refuses an announcement whose nonce is not the box's own pseudonym or is not newer (a replay cannot bring back a stale token or show a box in a game as free). It forgets a game's invites when the game ends, and a HELLO closes only the live game's.
- A DISCOVER at most every 10 s. Invites one box at a time, paced by their time on air; an invite unanswered for 6 s is sent again with the box's latest token, three times in all, then it has failed ("no answer"). An answer sets it accepted or refused (with the box's reason); the box's HELLO in the game, joined.
- **MOVE**: when the GM sets a new field channel (the console already refuses it while a game is live or a scan runs), the controller keeps its modem on the old channel, sends the MOVE three times 2.5 s apart (about 90 ms of air each) and then tunes the modem to the new channel and sends a DISCOVER there. The revision is `max(last + 1, wall clock in seconds)`, kept in the store (`radio.move_rev`); the field's last four earlier channels are kept too (`radio.channel_history`, shown as `previous_channels_hz` in `GET /api/v1/radio`; a change of region forgets them). *Find boxes* (`POST /api/v1/boxes/discover`), with no game live and at most once a minute, adds a **sweep**: four seconds after its DISCOVER, a MOVE twice on each remembered channel, one after the other, then a DISCOVER on the field's channel; the answer lists the channels it swept (`{"sent": true, "sweep": [869525000], "sweep_refused": null}`). On a sub-band under 10 % duty the sweeps' MOVEs are also capped per **rolling hour** (decision RL-9): each remembered channel is charged 2 MOVEs of air (185 ms at SF7/125 kHz) to the sub-band it is in, and a sweep that would take that sub-band's sweeps past **5 % of its duty-cycle budget** (1.8 s an hour on a 1 % sub-band, 0.18 s on 0.1 %) is not sent: the answer is `"sweep": []` with `"sweep_refused": {"reason": "cap", "band", "duty_pct", "share_pct", "limit_ms", "used_ms", "cost_ms", "retry_after_s"}`, `retry_after_s` the seconds until the oldest sweep leaves the hour and this one fits (null when it never fits, as on 0.1 %). A sub-band of 10 % has no cap. Both controllers do this with the same integer arithmetic (case *S7c Find boxes: the hourly cap ...* in `protocol/vectors/controller_api.json`). With a modem that cannot carry field frames the channel changes at once and the boxes need a card. The controllers report the progress to the console (decision RB-13): `move` in the radio settings and the `radio` stream message is `{state: telling | moved, from_hz, to_hz, rev, sent, repeats}`, `telling` with `sent` rising 1 to 3 while the MOVEs repeat and `moved` once the modem is on the new channel; it is null before a change with MOVEs (`protocol/vectors/controller_api.json`, case *S7c MOVE progress*).
- Only into the live game, before it starts; only with the GM token (`POST /api/v1/games/{id}/invites`, [controller/README.md](../controller/README.md)).
- **GAME_OVER** after every game it ran ends (besides the game's own CMD end), three times, 4 s apart, on the game's channel (the modem is tuned there and back to the field's channel when they differ and no game is live; with a game live on another channel it is dropped). It names the game by its key's tag, which the controller keeps beside the game (`key_tag:<game>`, not secret) and so still has after a restart without the key (`persist_game_key = false`, a lost key): the console's End on such a game sends it and says whether it went (`game_over_frame`: `sent`, `no_radio`, `no_join_key`, `no_tag` for a game made before the tag was kept). A standby controller never sends one (its game may still run on the primary). **And again when the controller hears a box still in a game that is over, at most once a minute** (decisions STUCK-1 to STUCK-19, RFC 0001 Amendment 27): a box switched off when its game ended never heard the three, and comes back still in the game. The modem reports another game's packets (OTHER_GAME, after WATCH_GAMES: the game id and source of the header in the clear, at most once per game id in 10 s; [usb-modem.md](usb-modem.md)); when the game id is a game this controller ran and ended and still has the tag of (it keeps `key_tag:<game>` after the end, for the last 50 games, so also after a restart without the key), it sends that game's GAME_OVER again, three times, by the same rules (the game's channel; dropped with a game live on another channel), and logs `game N: a box is still in it; GAME_OVER sent again` once per burst. Nothing changes on air and in the boxes: GAME_OVER can only end a game that is over, so a forged header costs air, never a game. `GET /api/v1/boxes` lists what was heard, for the console: `stuck` (per game, the most recent first: `game`, `last_heard_s`, `nodes` (the source node ids heard), `rssi`, `game_over_resent`), `stuck_reports` (OTHER_GAME reports heard) and `stuck_watch` (the modem can report them). The GM console lists them in its *Boxes* tab, with a **Release** button that sends a game's GAME_OVER at once (`POST /api/v1/boxes/stuck/{game}/release`, the same path and channel rules, refused with a game live on another channel, at most one burst per game in 10 s; decisions STUCK-40 to STUCK-47). A modem from before (its IDENT has no `games`) reports nothing: such a box is taken out at the box, with the admin menu's *Leave the game* or `@leave` (STUCK-20 to STUCK-33). A standby never resends one.
- **RELEASE** (Amendment 28): only on the GM's word (`POST /api/v1/boxes/release`, the console's *Release every box not in this game* in *Settings*, behind a confirmation), for a controller that lost a game entirely (no record, no key tag: no GAME_OVER can name it). It names the live game (0 with none) and its wall clock in Unix seconds, and goes three times, 4 s apart, on the channel the modem is on (the field's between games, the live game's during one). Refused: by a standby (409; its game's boxes are the primary's), while the controller's wall clock is not plausible (409, CLK-2: the boxes compare its time with their join's), while one is being said or within 30 s of the last (429). The answer is `{"live_game", "time", "release_frame"}` with `sent`, `no_radio` or `no_join_key`. The boxes it frees announce themselves free as after a game over. The Android field controller sends it with the same rules and answers (decisions STUCK-60 to STUCK-66).

## Duty cycle

Time on air at SF7/125 kHz (the LoRa formula, `eu868.airtime_ms`):

| Frame | Bytes | Time on air |
| --- | --- | --- |
| DISCOVER | 33 | 72 ms |
| ANNOUNCE | 66-128 (80 typical) | 123-215 ms (144 ms) |
| INVITE part | up to 217 | up to 343 ms |
| a two-part invite (a 270-byte join) | 217 + 120 | 550 ms |
| a three-part invite (448 bytes) | 3 x 217 | 1.03 s |
| GAME_OVER | 47 | 92 ms (three: 0.28 s) |
| RELEASE | 41-43 (an 11-13-byte body with a real clock) | about 87 ms (three: 0.26 s) |
| MOVE | 41-45 (15-byte body with a wall-clock revision) | about 90 ms (three: 0.27 s; a sweep, two on each earlier channel: 0.18 s a channel) |

- A free box on 869.4-869.65 MHz (10 %, 360 s an hour) announces about every 72 s: 7.2 s an hour, 2 % of its budget; on a 1 % sub-band (36 s an hour) every 12 minutes; on 868.7-869.2 MHz (0.1 %) every 2 hours. DISCOVER answers can add at most three times as much.
- The controller: twenty boxes invited with two parts each take about 11 s of air, 3 % of the controller's hourly budget on 869.4-869.65 MHz; on a 1 % sub-band, 30 % of it, so a field on a 1 % channel should invite in smaller groups. Every attempt counts; three attempts at most.
- The modem refuses a frame its sub-band's budget cannot take (FIELD_ACK `duty_cycle`); the console shows it on the box's row.

## Security

- **The field join key is a field secret.** Whoever holds it can read every field frame, and therefore every invite's join payload, which carries the game's key: someone with the join key who records the radio can read later games' keys and join or follow those games. A card or a QR code already carries one game's key in the clear (join.md); the invites widen this from one game to every game invited over the radio. The maintainer accepted this trade-off (decision RJ-2, 2026-10-21). Keep the join key off anything but the controllers (their store and `controller.toml`) and the boxes' NVS (encrypted on production boxes), and change it (on every controller and box) if a box or a controller is lost.
- Without the join key: frames do not open, a forged invite is not accepted, and recording frames gives nothing to replay (the token).
- A box's announcements say, to whoever holds the join key, that it is free, its name, its last role and battery. The device id is not linkable to the hardware or its Wi-Fi MAC address.
- A MOVE played back later cannot move a box that has taken a higher revision, which it keeps in NVS across reboots; the controller's revision never falls below the wall clock, so a restored backup still gives boxes a number above what they hold. A box whose NVS was erased has no revision and takes the first MOVE it hears. The worst a forged or replayed MOVE can do (it needs a frame sealed with the join key, or one recorded from the air) is send free boxes to a channel the controller is not on, which *Find boxes*' sweep repairs.
- A DISCOVER played back makes the free boxes answer, limited by the 2 % share above; it costs airtime, nothing else.
- A GAME_OVER can only be made with the join key and the game key's tag (which the game key gives, so whoever reads the invites): someone with the join key can end a game's boxes, among the worse things that key already allows. Without it a GAME_OVER does not open; played back it only ends a game that is over (above).
- **RELEASE** (Amendment 28; decisions STUCK-50 to STUCK-59):
  - *Forged*: it needs a frame sealed with the join key. Whoever holds the key can end every game's boxes on a channel, among the worse things the key already allows (reading every game key sent in an invite, forging a GAME_OVER).
  - *Replayed*: a RELEASE recorded at time T can free only a box that joined its game before T (by that game's first TIME) and is in a game other than the one it names: a box that the original would have freed had it heard it. A box in any game joined after T refuses it. A box that has left its game ignores it (only boxes in a game act on it).
  - *Clocks*: the join time is the game controller's clock in TIME, the RELEASE's the releasing controller's, refused while that is not plausible (CLK-2). A game controller whose clock ran ahead makes a box refuse a RELEASE until the RELEASE's clock passes it (the box still has `@leave`); one whose clock was far behind (1970 on a Raspberry Pi with no network) makes the box's join time tiny, and any older RELEASE recorded on the field could then free it: replay protection is only as good as the game controller's clock. Both controllers put the same clock into TIME's `wall_s` and RELEASE's `time`: the wall clock with the offset the GM can set (CLK-4; the Pi's `wallclock.now()`, the phone's `ClockGuard.now()`, decisions STUCK-62 and STUCK-68), so a join time and a RELEASE from one controller are on one scale. RELEASE stays a GM action confirmed in the console, never automatic: a game a second controller runs on the same channel at the same time loses its boxes too (STUCK-70).
  - *Collateral*: a RELEASE frees every box of the field on that channel in another game, including the boxes of a game that a second controller of the same field runs at the same time on the same channel. That is why it is a GM action behind a confirmation that says so, never automatic.
  - *Air*: three frames of about 87 ms, at most once in 30 s; boxes do not answer it, but the ones it frees announce themselves.

## What is not covered

- **Adopting a box over the radio** is not a field frame: its messages run before the box holds the join key, so they are a sibling message type 10 (`PAIR`, RFC 0001 Amendment 8) with this header's rules but in the clear, secured by CPace with the code the box shows ([adoption.md](adoption.md) section 7, decisions AD-15 to AD-27). The modem carries both types in FIELD_TX / FIELD_RX; its KEY message's nonce follows this file's rule, and both use `atalaia_hkdf_sha256` / `hkdf_sha256`. Kind 4 of type 9 is GAME_OVER (addendum of 2026-10-22), kind 5 MOVE (Amendment 19) and kind 6 RELEASE (Amendment 28); kind 7 stays unused (decoders refuse it).
- Android props link over Wi-Fi ([prop-link.md](prop-link.md)), not LoRa: they are not invited over the radio yet (they count for the start guard as soon as they are linked). The app's HELLO codec reads and writes key 10.
- A box listens on its last game's channel, or the field's after a MOVE. A box from before Amendment 19 (no MOVE), one that was off while the field moved and is out of the sweep's reach (it keeps the channel of its last game, so only the earlier channels the controller remembers, four at most, are swept), and a field changed by a controller whose modem has no field frames, still need a card once.
- Field frames are not relayed: a box out of the modem's direct range is not heard between games.
