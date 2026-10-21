<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Adopting boxes

Before a Field Box can join a field's games it must be **adopted** by the field: it must get the field's 32-byte **field join key** ([join.md](join.md)), which authenticates every join payload. With the sealed radio re-invites ([field-frames.md](field-frames.md), RJ decisions) the join key also becomes the field's **master secret**: the keys that seal a game's invite are derived from it, so whoever holds it and records the radio can read later games' keys (accepted by the maintainer). Adoption is how that secret reaches a box, once, and how the box refuses to give itself to anyone else.

The maintainer chose three ways (decision AD-1, 2026-10-21):

| # | Method | Status |
| --- | --- | --- |
| 1 | **Pairing code over LoRa**: the box shows a short code, the GM types it in the console, a code-authenticated key exchange (CPace) runs over the radio and the join key is sent sealed under the agreed key | Built (section 7): firmware, controller, console; in software and host tests (the C host box through the C host modem), not yet on the boards |
| 2 | **NFC field card**: an NTAG215/216 holding the join key, written from the console, tapped once on each new box | Built: firmware, controller, console; in software and host tests, not yet on a reader (no PN532 fitted on the bench board) |
| 3 | **USB cable**: the new box plugged into the controller once; the controller finds it and writes the key with a serial command after the GM confirms which box | Built: firmware, controller, console; tested with the C host box through a TCP bridge, not yet with a real board on the controller's USB |

The earlier ways stay, under the same rules: `@joinkey <64 hex>` on the serial console and the setup portal's optional "field join key" field (decision AD-7).

Implementations: [`firmware/esp32/main/adoption.c`](../firmware/esp32/main/adoption.c) (the box: the field card, the rules, the console commands; platform-free, also run by the host box [`box_host`](../firmware/esp32/test/box_host/box_host.c)), [`simulator/atalaia_sim/field_card.py`](../simulator/atalaia_sim/field_card.py) (the card's Python codec), [`controller/atalaia_controller/adoption.py`](../controller/atalaia_controller/adoption.py) (the controller: field cards, USB adoption, records) and the console's *Adotar / Adopt* tab ([`adopt-panel.js`](../controller/console/src/components/adopt-panel.js)). Shared vectors: [`vectors/field_card.json`](vectors/field_card.json) (4 valid cards, 18 invalid ones), checked by C and Python.

## 1. The box's adoption state

```
                 field card / @adopt / @joinkey / portal          (no PIN needed)
   UNADOPTED  ─────────────────────────────────────────────▶  ADOPTED (field F)
   (no key stored;                                              │  ▲   key K_F, name, fingerprint
    a development key                                           │  │   same field again: "same" (the name may change)
    counts as none)                                             │  │
        ▲                                                       │  └── another field G's card or @adopt,
        │  factory reset: erase the flash                       │      WITH the box's admin PIN: "readopted"
        └───────────────────────────────────────────────────────┘      (without it: "need_pin"; wrong: "bad_pin";
                                                                        5 wrong since the box started: "locked")
```

- **Unadopted**: no join key in NVS. A key set only for this boot by `CONFIG_ATALAIA_DEV_JOIN_KEY` (Wokwi, the bench) does not count (decision AD-3). The first field to offer itself adopts the box: whoever has the box in their hands (to tap a card or plug it in) or, with method 1, can read its screen. This is trust on first use, as a new phone or router is set up.
- **Adopted to field F**: the box holds F's key, F's name (to show) and the key's **fingerprint** `HMAC-SHA256(key, "atalaia-field-fingerprint")[:4]` written `XXXX-XXXX` (`604A-0A95` for the vectors' key), which the box, the console and `python3 -m atalaia_controller join-key --fingerprint` show so they can be compared. The fingerprint is no secret and tells nothing of the key.
- **Re-adoption** to another field G (or to F's new key after a rotation, section 5) needs the box's **admin PIN** (the one the setup portal sets, `config_store` `admin_pin`; 1234 until set): typed on the box's keypad after G's card, or given to `@adopt` over the cable (the console asks the GM for it). Five wrong PINs lock re-adoption until the box restarts (decision AD-2). So a stranger can neither steal a field's boxes with their own card nor "adopt them away" from the radio: they need the PIN or a factory reset.
- **Factory reset** is erasing the flash (`idf.py erase-flash`, or `esptool.py erase_flash`): physical access, a USB cable and the tools, and the box loses everything (presets, Wi-Fi, PIN). With flash encryption and secure boot on (section 2) this is the only way past the PIN, and it leaves nothing of the old field to read.
- **Busy**: nothing is adopted while a field game is joined or a game is being played (`busy`); a field card tapped during a game is logged and ignored, never passed to the mode as a tag (decision AD-9).

The rules are the box's own (`adoption_offer()` in `adoption.c`); the controller only asks.

## 2. Where the key is kept

- The join key: NVS namespace `radio`, blob `join_key` (`radio/radio_nvs_esp.c`), next to the game key and the stored join, as before; the field's name: NVS namespace `atalaia`, string `field_name` (`config_store`). The host box keeps both as files in its state directory.
- **Development builds run with NVS encryption off**: the key is in plain flash, readable by anyone who dumps it over USB (the box logs `NVS encryption is off` at boot). That is acceptable on the bench only.
- **Production Field Boxes need** (decision AD-12): NVS encryption with the HMAC-based scheme and an eFuse key ([BRING_UP.md step 0](../firmware/esp32/docs/BRING_UP.md#step-0-efuse-hmac-key-provisioning-production-only)); flash encryption (release mode), so the NVS and the image cannot be read from the flash chip; secure boot v2 with the release key, so a modified image cannot be flashed to print the key; the JTAG part of USB-Serial-JTAG disabled by eFuse (`DIS_USB_JTAG`), the serial part kept for USB adoption; and the admin PIN changed from 1234 at setup, else the PIN protects nothing. None of these is set in the repository's sdkconfig files yet; they are one-way eFuse operations for a release process.
- The controller keeps the key in its store (`join_key` setting, or `[join] key`), never in the API, the logs or the adoption records.

## 3. What the box shows

| When | TFT (`status` / `pin_entry` templates) | On-board OLED |
| --- | --- | --- |
| Adopted (card or cable) | ADOPTED, Field: the name, Key: the fingerprint (4 s, or until a key) | the name, the fingerprint below |
| The same field again | ALREADY ADOPTED, the same rows | as above |
| Another field's card | GAME MASTER, "PIN to change field", the PIN's dots; `#` enters, `*` deletes, `*` on nothing cancels; a minute without a key cancels | ADMIN PIN, dots |
| Wrong PIN | the same, "Wrong PIN, try again" | "Wrong PIN" |
| Locked, bad card, not stored | ADOPTION LOCKED / BAD FIELD CARD / NOT STORED with the field the box keeps | the same title |
| Unadopted, at start | PAIR THIS BOX, Code: the 6 digits, Id: the pair id's start (TRY AGAIN after a failed run; PAIR PAUSED for a minute after three; PAIR LOCKED, restart the box, after ten) | the code, "id b0c5 console"; paused or locked in the footer |
| A game joined | nothing changes; the log says why | |

The serial console logs every attempt (`adoption (card|usb|joinkey): adopted, field 604A-0A95 "Campo"` or `refused, need_pin`), never the key or the PIN. An unadopted box logs it at boot and shows its pairing code (section 7).

## 4. The NFC field card (method 2)

### Format

The user memory of an NTAG215 or NTAG216 (an NTAG213 holds it too) from page 4: an NDEF message TLV (`0x03`, length, message) with one MIME record (TNF 2, MB, ME, SR) of type **`application/vnd.atalaia.field`**, then the terminator TLV (`0xFE`), exactly as a join card but with its own type, so a join card reader never takes a field card and the other way round. The record's payload, 42-90 bytes:

```
version (1) = 1 | name_len (1) = 0-48 | name (name_len bytes) | join_key (32) | check (8)
check = HMAC-SHA256(join_key, "atalaia-field-card" | version | name_len | name)[:8]
```

- `name` is the field's display name (the console's branding name, or `[checkin] field_name`), UTF-8 in shortest form without surrogates, control characters, `"` or `\`; the controller drops what a card refuses and cuts it to 48 bytes on a character boundary.
- `check` catches a card written wrong or damaged and ties the name to the key. **It is not a signature**: anyone can make a card of their own key. That is why an adopted box takes another field's card only with its PIN.
- A reader refuses (reasons as in the vectors): `length` (not 42-90 bytes, or `name_len` not matching), `version`, `name`, `check`.

### Flow

1. In the console's *Adotar / Adopt* tab the GM presses **Make the field card**, after the warning: *this card is the field's master secret* (it holds the join key; whoever has it can make join cards for the field's boxes and read later games' invites). `POST /api/v1/adopt/card` (GM token, `Cache-Control: no-store`) answers the bytes; the controller logs `a field card was made` and records it.
2. The GM writes the bytes to a card with any NFC writer that writes raw NDEF memory from page 4, as for join cards (the console's NDEF bytes; the Android app's tag writer does not know this type yet).
3. The GM taps the card on each new box between games: an unadopted box is adopted at once; a box of this field says *already adopted*; a box of another field asks for its admin PIN on the keypad.

### Threat model

| Threat | Outcome |
| --- | --- |
| Someone reads or copies the card (an NFC phone at 2 cm) | They have the field's master secret: they can make join cards the field's boxes take, adopt *unadopted* boxes to this field, and with a radio recording read later invites' game keys. Cards are kept locked away; a lost or copied card means rotating the key (section 5). The console says so. No NTAG password: the PN532 would need it too, and its 32 bits stop no determined copier. |
| A stranger taps their own field card on our box | Refused without our box's admin PIN (`need_pin`); five tries per boot. |
| A stranger taps their card on our *unadopted* box | Adopted to their field: trust on first use. Keep new boxes in hand until adopted. |
| A damaged or half-written card | `bad_card` (the check), nothing stored. |
| A field card tapped during a game | Ignored and logged; never handed to the mode as a player tag. |
| Our card tapped on a stranger's box | Their box needs its PIN; if it is unadopted it now holds our key, which is the same as the card being copied: rotate. |

## 5. Rotating the join key

When a field card is lost or copied, a box is stolen (it holds the key in its NVS), or a GM leaves: `python3 -m atalaia_controller join-key --rotate` makes a new key, keeps the old key's fingerprint as the **previous** one, and prints both fingerprints (never the key). It refuses when `[join] key` is set in the settings: change it there. Then:

1. restart the controller (it reads the key at start);
2. adopt every box again: by cable or with a new field card; each box still on the old key is listed as *adopted to this field's old key* and asks for its admin PIN, like any other field's box (the old key may be in the wrong hands, so it proves nothing);
3. write new field cards and destroy the old ones; join cards made before stop working ("bad tag");
4. give a standby controller the new key (`[join] key`).

There is no remote revocation: a box that cannot be reached keeps the old key until it is adopted again or erased. With the sealed invites, the invites of games after the rotation are sealed under keys derived from the new key, so a recording plus the old key no longer reads them.

## 6. USB adoption (method 3)

### The serial commands

On the box's USB-Serial-JTAG console (and UART0), with `CONFIG_ATALAIA_SERIAL_ADOPT` (on in every Field Box build). Each reply is one line beginning `ATALAIA-ADOPT ` followed by a JSON object; log lines around it are ignored by the controller.

```
@adopt-info
ATALAIA-ADOPT {"v":1,"kind":"info","name":"porta-norte","mac":"24:58:7C:DA:11:F0","fw":"0.4.0",
               "state":"unadopted","field":"","field_name":"","busy":false,"locked":false}

@adopt <64 hex digits> [<admin PIN>|-] [<field name, the rest of the line>]
ATALAIA-ADOPT {"v":1,"kind":"result","result":"adopted","state":"adopted","field":"604A-0A95",
               "field_name":"Campo da Atalaia"}
```

`result` is one of `adopted`, `same`, `readopted`, `need_pin`, `bad_pin`, `locked`, `busy`, `bad_key`, `store_failed`. `mac` is the chip's factory MAC (`esp_efuse_mac_get_default`), in the form the ESP32-S3's USB-Serial-JTAG gives as its USB serial number, so the GM can match the port to the box (the scan's answer has both; that they agree on a real board is to be checked on the bench). `@joinkey <64 hex>` is `@adopt <key>` without a PIN or a name and answers a log line (`join key: stored`, or `refused (...)`).

### Flow

1. The GM plugs the new box into the controller (the Pi) with a data cable and presses **Look for boxes** in the *Adopt* tab. `POST /api/v1/adopt/usb/scan` opens every Espressif USB-Serial-JTAG port (USB 303a:1001) except the radio modem's own port (`[modem] port`, compared after resolving `/dev/serial/by-id` links), and every port in `[adopt] usb_ports` (e.g. `socket://host.docker.internal:7001`), without toggling DTR or RTS (which would reset an ESP32-S3), sends `@adopt-info` (again after 1.5 s, for a box that restarted when the port opened) and lists each box that answers: name, MAC, port, its state as seen from this field (*not adopted*, *adopted by this field*, *adopted to this field's old key*, *adopted by another field: name (fingerprint)*), busy or locked. Ports that did not answer are listed apart.
2. The GM checks the name and MAC (the box logs both; the MAC is also the port's USB serial number) and presses **Adopt**; for another field's box the console asks for that box's admin PIN.
3. `POST /api/v1/adopt/usb {"port", "mac", "pin"?}` opens the port again, asks `@adopt-info` and goes on only if the MAC is the one the GM confirmed (another box plugged into the same port in between is refused, `409`), then sends `@adopt <key> <PIN|-> <field name>` and returns the box's result. The controller logs `adoption: box porta-norte (24:58:...) on /dev/ttyACM1, field 604A-0A95: adopted` and records it (`GET /api/v1/adopt`: the last 20 of 100 kept; method, box, MAC, port, result, whether a PIN was given; never the key or the PIN).

### Threat model

| Threat | Outcome |
| --- | --- |
| A stranger with a laptop and a cable on our box | `@adopt` of their key is refused without the admin PIN; `@adopt-info` tells them only the box's name, MAC and our fingerprint. With physical access they can erase the flash (a factory reset), which takes our key away with everything else; with flash encryption on they cannot read it out. |
| A box plugged into our controller that we did not mean | The GM confirms the name and MAC; the controller writes only to the box it showed (MAC checked again on the same port). |
| The modem's port | Never opened by adoption. |
| Eavesdropping on the cable | The key crosses a USB cable inside the controller's case: out of scope. |
| The GM token stolen | The holder can adopt boxes plugged into the controller and make field cards (the master secret): the GM token already controls the field. Every card and adoption is logged. |

### The controller in Docker on Windows / WSL

Docker on Windows does not see COM ports. Two ways:

- **A COM-to-TCP bridge** on Windows: `python tools/serial_bridge.py COM3 7001` (needs only `pip install pyserial`; it opens the port without raising DTR or RTS, and serves the radio modem the same way with `--baud 921600`), then `[adopt] usb_ports = ["socket://host.docker.internal:7001"]` (or `ATALAIA_ADOPT_USB_PORTS`). Close any serial monitor on that COM port first.
- **usbipd-win**: `usbipd bind --busid <id>` and `usbipd attach --wsl --busid <id>`; the board appears in WSL as `/dev/ttyACM0`; run the controller's container with `--device /dev/ttyACM0` (and the modem's device as before). The scan then finds it by its USB ids, which `usbipd` passes through.

## 7. The pairing code over the radio (method 1)

For a box with a screen and no cable or card at hand (decisions AD-15 to AD-27). Built on the re-invite work: the same header rules as field frames (game id 0, `hop_limit` 0, never relayed, [field-frames.md](field-frames.md)), carried by the USB modem in FIELD_TX / FIELD_RX, its nonce rule (RJ-15), its HKDF-SHA256 (`atalaia_hkdf_sha256` / `hkdf_sha256`) and AES-128-CCM.

Implementations: [`core/src/pair_frame.c`](../core/src/pair_frame.c) and [`simulator/atalaia_sim/pair_frame.py`](../simulator/atalaia_sim/pair_frame.py) (the frames, the keys, the tags, the sealed key), [`firmware/esp32/main/cpace.c`](../firmware/esp32/main/cpace.c) and [`simulator/atalaia_sim/cpace.py`](../simulator/atalaia_sim/cpace.py) (CPace), [`firmware/esp32/main/box_pair.c`](../firmware/esp32/main/box_pair.c) (the box), [`controller/atalaia_controller/pairing.py`](../controller/atalaia_controller/pairing.py) (the controller) and the *Adopt* tab's *Pair by code*. Shared vectors: [`vectors/pairing.json`](vectors/pairing.json) (`tools/pairing_vectors.py` writes and `--check`s it): the CPace draft's Appendix B.1 and B.1.10, a whole run of this exchange, 19 bodies and 6 frames that must be refused; checked by C (`core/tests/test_pair_frame.c`, `firmware/esp32/test/test_box_pair.c`, which also plays the run against the box and compares its REPLY and DONE byte for byte) and Python (`simulator/tests/test_pair_frame.py`).

### The PAKE: CPace on X25519 with SHA-512

**CPace**, `CPACE-X25519-SHA512` (draft-irtf-cfrg-cpace-14, the CFRG's recommended balanced PAKE), rather than SPAKE2 (RFC 9382) (decision AD-10):

- Both sides have it from libraries already in the project. **The box**: Monocypher 4.0.2 (vendored for firmware updates) `crypto_x25519`, `crypto_elligator_map` and its optional `crypto_sha512`. **The controller**: `cryptography`'s X25519 (`exchange` is the scalar multiplication on any u-coordinate) and `hashlib`; Elligator 2 (RFC 9380 6.7.1) is a dozen lines of Python integers.
- SPAKE2's RFC vectors are P-256 only and `cryptography` has no P-256 point addition; SPAKE2 also needs fixed M and N points. CPace's generator comes from the code by hashing, and its messages are 32-byte u-coordinates.
- Monocypher's `crypto_elligator_map` reads 254 bits and CPace decodes 255 (then reduces modulo p); the map depends only on r², so the box gives it `min(r, p - r)`, always below 2^254. Both sides reproduce the draft's `g`, `Ya`, `Yb`, `K` and `ISK` (B.1) and the low-order points' results (B.1.10, the abort case for u0-u5 and u7).

The controller is CPace's initiator (A), the box its responder (B). `PRS` = the code's 6 ASCII digits; `CI` = `lv_cat("atalaia pair v1", pair id)`; `sid` = 16 bytes the controller draws for the run; `ADa` = `"atalaia controller"`, `ADb` = `"atalaia box"`; `ISK = SHA-512(lv_cat("CPace255_ISK", sid, K) || lv_cat(Ya, ADa) || lv_cat(Yb, ADb))`. A `K` of all zeros (a low-order point) aborts the run.

### Frames (message type 10, PAIR)

```
header (9) | body (CBOR, 1-200 bytes)        10-209 bytes, in the clear
```

The header: `version_flags` 0x28 (version 1, normal priority, no ACK, **not encrypted**), game id 0, source 0, seq 0, `hop_limit` 0, type 10. The body is a CBOR map with integer keys, the kind (key 1) first; decoders refuse an unknown kind, a missing or repeated field, a value of the wrong type or size, a key of another kind, keys from 32 up and trailing bytes, and skip unknown keys up to 31.

| Key | Field | Type | In |
| --- | --- | --- | --- |
| 1 | `kind` | uint | all: 1 OFFER, 2 START, 3 REPLY, 4 KEY, 5 DONE |
| 2 | `pair_id` | bytes (8) | all: a random id the box draws for each pairing (not its MAC or device id) |
| 3 | `name` | text (1-24) | OFFER: the box's name |
| 4 | `tier` | uint (0-2) | OFFER |
| 5 | `sid` | bytes (16) | START, REPLY, KEY, DONE |
| 6 | `point` | bytes (32) | START: Ya; REPLY: Yb |
| 7 | `tag` | bytes (16) | REPLY, KEY, DONE |
| 8 | `nonce` | bytes (13) | KEY |
| 9 | `sealed` | bytes (41-89) | KEY: the join key (32), the name's length (1), the field's name (0-48 bytes), the MIC (8) |
| 10 | `result` | uint (0-9) | DONE: `adopted`, `same`, `readopted`, `need_pin`, `bad_pin`, `locked`, `busy`, `bad_key`, `bad_card`, `store_failed` (adoption.c's order) |
| 11 | `fingerprint` | bytes (4) | DONE: the field fingerprint of the key the box now holds (zeros if it holds none) |

From the ISK, `HKDF-SHA256(salt = sid, IKM = ISK)` with the labels `atalaia pair confirm a v1` (32 bytes, the controller's tag key), `atalaia pair confirm b v1` (32, the box's), `atalaia pair seal v1` (16, AES-128-CCM) and `atalaia pair nonce v1` (32, the nonce pseudonym's key). The tags are the first 16 bytes of HMAC-SHA256: REPLY's `(confirm_b, "atalaia pair reply")`, KEY's `(confirm_a, "atalaia pair key")`, DONE's `(confirm_b, "atalaia pair done" | result | fingerprint)`. KEY's sealed key: AES-128-CCM, 8-byte MIC, AAD `"atalaia pair key v1" | pair id | sid`, under the nonce **`HMAC-SHA256(nonce key, sender id)[0..7] | boot 1 | count 0`** with a sender id the controller draws with `os.urandom` for every run and never stores (field-frames.md's rule, decision RJ-15): a key new to every run and a nonce from no generator of the box's. **Only the controller encrypts**; the box seals nothing (decision AD-17).

### The exchange

| # | From | Frame | What |
| --- | --- | --- | --- |
| 0 | box | OFFER | while its code is on the screen: 1-3 s after it starts, then every max(15 s, its time on air / (5 % x the sub-band's duty cycle)) ± 10 % (about every 15 s on 869.525 MHz: 0.48 % of the hour's budget for 5 minutes) |
| 1 | controller | START | the GM picked the box and typed its code: a fresh sid and scalar, Ya; sent again after 3 s, three times at most |
| 2 | box | REPLY | Yb and the box's confirmation; computed once per sid, sent at most twice (a repeated START), then the box waits 10 s for KEY |
| 3 | controller | KEY | only if the box's confirmation matches (else: `wrong_code`, nothing more is sent); the controller's confirmation, the nonce, the sealed join key and field name; again after 3 s, three times at most |
| 4 | box | DONE | the box checks the controller's confirmation (else that KEY is ignored and the run keeps waiting), opens the key, adopts the field through `adoption_offer()` exactly as by a card or the cable, and answers with its result and the key's fingerprint, authenticated; a repeated KEY gets the same DONE again, twice at most |

The controller then checks DONE's tag and that the fingerprint is this field's; the run is `done`, or `failed` with its reason (`wrong_code`, `no_answer`, `no_done`, `bad_answer`, `fingerprint`, `box_refused`, `channel_changed`). The adopted box's field frames start at once under the new key (box_lobby.c): it announces itself as a free box.

### The box

- **When**: an unadopted box with a radio shows its code at start (over the preset picker; `*` gives the picker back, `#` shows a new code) and on `@pair` on the serial console; not during the setup portal, not on an adopted box (decision AD-16: an adopted box moves to another field by card or cable with its admin PIN; re-pairing it over the radio is left for later), not while a game is joined or played. The TFT shows *PAIR THIS BOX* with the code (`Code: 042 137`), the on-board OLED the code in large type; the log `pairing: code 042 137 on 869525000 Hz, for 5 minutes`.
- **Where**: on `CONFIG_ATALAIA_RADIO_DEFAULT_CHANNEL_HZ`, 869.525 MHz by default, where the radio listens until a game sets a channel (decision AD-18); the box logs it at start (`pairing: listening on 869525000 Hz`).
- **Limits** (decision AD-19): the code stays 5 minutes; one run per START's sid, a sid never runs twice (the last eight are remembered: a recorded START played back gets nothing); a failed run (a low-order point, or no KEY with the controller's confirmation within 10 s: the code was wrong, or the START was not our controller's) burns the code and shows a new one; a START that got a REPLY always burns it, since the REPLY's tag is one guess. A KEY whose confirmation does not match, or whose sealed key does not open, ends nothing: it is counted and ignored and the run keeps waiting for the controller's own (decision AD-25), since anyone who heard the sid could send one. A START while a run is on is refused, not a replacement. After three failed runs in a row the screen says *PAIR PAUSED, for 1 minute* (no code, no runs, no offers); after ten, *PAIR LOCKED, restart the box* until a key, and no pairing until the box restarts. A run's scalar, ISK and keys are wiped as soon as they are no longer needed and on every outcome. So without the code an attacker gets one guess per run (one in a million), three a minute, ten in all, and can make the box transmit at most two REPLYs per run.
- **The code**: 6 digits from the box's seeded generator (RJ-15's), uniform (rejection sampling), never stored; the pair id likewise, new at every pairing. The screen also shows the pair id's first two bytes (`Id: b0c5`), which the console shows beside the box's offer (decision AD-26).

### The controller

- Hears OFFERs through FIELD_RX (pair frames are told from field frames by their type), lists the boxes offering for a minute after the last one, and runs one pairing at a time; `GET /api/v1/adopt/pair`, `POST /api/v1/adopt/pair/listen`, `POST /api/v1/adopt/pair {"pair_id", "code"}`, GM token only (decision AD-20). Every run's outcome is logged (`atalaia.adoption`) and kept with the other adoption records (method `radio`), never the code, the key or a secret of the run.
- **The channel** (decision AD-18): when the field's channel is not 869.525 MHz and no game is live, *Look for boxes on the radio* tunes the modem there for five minutes and back to the field's channel afterwards (or as soon as a game is created); with a game live on another channel it refuses until the game ends. Whenever the engine tunes the modem back to the field's channel (the channel set, a scan, the modem reconnecting), pairing stops saying it listens and a run under way there fails (`channel_changed`, decision AD-27). A modem whose firmware does not say `"pair": true` in IDENT is refused (update it).

### Threat model

| Threat | Outcome |
| --- | --- |
| Passive recording of the whole exchange | Nothing: CPace gives an eavesdropper no offline test of the code, and the key travels sealed under a key derived from the ISK. |
| Man in the middle on the air, or a fake controller | One guess of the code per run; a wrong guess shows on the box (a new code) and in the console (the run failed). The box adopts only after the controller's confirmation, so a fake controller without the code gets nothing and gives nothing. |
| A fake box answering for ours | Without the box's code its REPLY fails the confirmation (`wrong_code`) and the join key is never sent. |
| A neighbour field's controller adopting our new box | Needs the code from our box's screen: sight of the box. Keep new boxes in hand until adopted, as for the card and the cable. |
| Replays (START, KEY, REPLY, DONE) | A START's sid runs once; a KEY or DONE of another run does not authenticate; the controller ignores frames of runs that are over. |
| Making a box transmit | Offers only while the code shows (5 minutes, about 20), at most two REPLYs a run, three runs a minute, ten in all: well under the sub-band's budget. |
| Denial of service on the air (jamming; STARTs answering every OFFER; forged KEYs) | A radio attacker can always keep a box from being paired: by jamming, or by taking its run with a START of its own (the GM's START then gets no answer: "another pairing under way, or interference; try again"), and its failed runs pause the box and, after ten, lock it until a restart, which the box's screen says. It cannot adopt the box, read the key, or end a real run with a forged KEY (ignored). Pair where the field is quiet, or use the cable or the card. |
| A fake box offering under a real box's name | The console shows each offer's short id, RSSI and when it was last heard, flags two offers under one name and an OFFER that reuses a pair id under another name; the GM types the code into the entry whose id is on the box's screen. A wrong code into a fake entry gives the fake one guess per run, never the key, and the console says to read the box's screen again: a real box shows a new code after any failed run (if its code did not change, the entry was not that box). |

### RFC 0001

Amendment 8 (2026-10-21, proposed) in [docs/rfcs/0001-skirmesh-rf-wire-format.md](../docs/rfcs/0001-skirmesh-rf-wire-format.md#amendment-8-2026-10-21-proposed-pair-frames-adopting-a-box-by-its-code): message type 10.

## Decisions

AD-1 to AD-14 in [docs/review/decisions-to-review.md](../docs/review/decisions-to-review.md#adopting-boxes-2026-10-21), AD-15 to AD-27 in its section on the pairing code.
