<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Adopting boxes

Before a Field Box can join a field's games it must be **adopted** by the field: it must get the field's 32-byte **field join key** ([join.md](join.md)), which authenticates every join payload. With the sealed radio re-invites (RJ decisions, built in parallel) the join key also becomes the field's **master secret**: the keys that seal a game's invite are derived from it, so whoever holds it and records the radio can read later games' keys (accepted by the maintainer). Adoption is how that secret reaches a box, once, and how the box refuses to give itself to anyone else.

The maintainer chose three ways (decision AD-1, 2026-10-21):

| # | Method | Status |
| --- | --- | --- |
| 1 | **Pairing code over LoRa**: the box shows a short code, the GM types it in the console, a code-authenticated key exchange (CPace) runs over the radio and the join key is sent sealed under the agreed key | Designed here (section 7), to be built on the re-invite work's message ids and key derivation |
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
| A game joined | nothing changes; the log says why | |

The serial console logs every attempt (`adoption (card|usb|joinkey): adopted, field 604A-0A95 "Campo"` or `refused, need_pin`), never the key or the PIN. An unadopted box logs it at boot; with method 1 an unadopted box with a screen will show its pairing code (section 7).

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

## 7. The pairing code over LoRa (method 1, designed, not built)

For a box with a screen and no cable or card at hand. It is built after the re-invite work, on its message ids, its framing of packets outside a game and its key derivation.

### Choice of PAKE: CPace on X25519 with SHA-512

**CPace** (draft-irtf-cfrg-cpace-14, the CFRG's recommended balanced PAKE), its X25519 / SHA-512 cipher suite (`CPACE-X25519-SHA512`), rather than SPAKE2 (RFC 9382) (decision AD-10):

- Both sides have it from libraries already in the project. **The box**: Monocypher 4.0.2 (vendored for firmware updates, `components/monocypher`) has `crypto_x25519` and `crypto_elligator_map` (Elligator 2 on Curve25519) and, in its optional part, `crypto_sha512`; mbedtls (ESP-IDF) has HKDF-SHA256 and AES-CCM. **The controller**: `cryptography` (already a dependency) has X25519 (its `exchange` is the scalar multiplication on any u-coordinate) and `hashlib` SHA-512; the Elligator 2 map is a dozen lines of integer arithmetic modulo 2^255 - 19 in Python.
- SPAKE2's RFC 9382 known answers are for P-256 only, and `cryptography` offers no P-256 point addition (SPAKE2 needs `x*G + w*M`): it would need hand-written curve arithmetic on the controller. SPAKE2 also needs the M and N constants and a password-to-scalar mapping; CPace has neither.
- CPace's generator comes from the code by hashing (no fixed points, no trusted setup), and its messages are plain X25519 u-coordinates (32 bytes each), small enough for LoRa.
- Checked while writing this design: Monocypher's `crypto_elligator_map` reads its input as 254 bits, while CPace decodes 255 bits; since the map depends only on r², feeding it `min(r, p - r)` gives CPace's generator. On the draft's B.1.1 vector (r < 2^254 already) Monocypher returns exactly the draft's `g`, and a Python Elligator 2 with `cryptography`'s X25519 reproduces `g`, `Ya`, `Yb`, `K` and `ISK_IR` of B.1 (both run on 2026-10-21).

### The exchange

The controller is CPace's initiator (A) and the box its responder (B). They talk over packets outside a game (no game key: their integrity comes from CPace), on the channel where idle boxes listen for invites:

| # | From | Message (proposed) | Content |
| --- | --- | --- | --- |
| 0 | box | `PAIR_OFFER` (broadcast every 10 s while the code is on the screen) | `mac` (6), `box_nonce` (8), the box's name (≤ 24 bytes) |
| 1 | controller | `PAIR_START` | `mac` (the box addressed), `sid` (16 random bytes), `Ya` (32) |
| 2 | box | `PAIR_REPLY` | `sid`, `Yb` (32), `tag_b` (16) |
| 3 | controller | `PAIR_KEY` | `sid`, `tag_a` (16), `sealed` (the join key and the field's name: 32 + ≤ 48 bytes, AES-128-CCM, 8-byte tag) |
| 4 | box | `PAIR_DONE` | `sid`, `result` (as `@adopt`'s), `fingerprint` (4), `tag` (8) |

- `PRS` = the code's ASCII digits; `CI` = `lv_cat("atalaia-pair-v1", mac, box_nonce)`; `sid` from `PAIR_START`; `ADa` = the controller's node id (2 bytes), `ADb` = the box's MAC. The generator, `Ya = ya·g`, `Yb = yb·g`, `K` and `ISK = SHA-512(lv_cat("CPace255_ISK", sid, K) || transcript_ir(Ya, ADa, Yb, ADb))` exactly as the draft (initiator-responder ordering). A `K` of all zeros (a low-order point) aborts.
- From `ISK`: `HKDF-SHA256(ikm = ISK, salt = sid, info = "atalaia pair v1 " + label)` for `confirm_a`, `confirm_b` (32 bytes each) and `seal` (16 bytes + 13-byte nonce). `tag_b = HMAC-SHA256(confirm_b, transcript)[:16]` and `tag_a` likewise: explicit key confirmation both ways; the box checks `tag_a` before it opens `sealed`, the controller checks `tag_b` before it sends `sealed`. Labels are registered next to the re-invite labels so no two derivations share one.
- The box then stores the key under the same rules (`adoption_offer()`): an unadopted box offers a code by itself; a box adopted to another field offers one only after its admin PIN was typed on the keypad (an "Adopt to another field" entry in the admin menu), and that PIN is what lets the run replace its key.

### Limits

- The code: 6 random digits (about 20 bits), new at every run and after every failed one; on the screen with the box's name, for 5 minutes, then only after a key press.
- One code, one run: a run that fails its confirmation burns the code; after 3 failed runs the box waits 60 s, after 10 it stops offering until restarted. The controller allows one run per code the GM types, 10 s per message and 30 s per run.
- An active attacker on the air therefore gets **one guess per run** (one chance in a million) and few runs; a passive eavesdropper, even with every packet, learns nothing about the code or the key (CPace's security: no offline dictionary attack).

### Threat model

| Threat | Outcome |
| --- | --- |
| Passive recording of the exchange | Nothing: the key travels sealed under a key only the two ends with the code can derive. |
| Man in the middle on the air | One guess of the code per run, then the code changes; a failed run is visible on both ends. |
| A neighbour field's controller adopting our new box | Needs the code from our box's screen: sight of the box. |
| Our controller adopting the wrong unadopted box | The console shows the box's name and MAC from `PAIR_OFFER` before the GM types the code; the code binds the run to the box showing it. |
| Jamming | Adoption fails; use the cable or the card. |

### Known answers (from draft-irtf-cfrg-cpace-14, Appendix B.1, X25519 / SHA-512)

Copied from the draft (to go into `protocol/vectors/pairing.json` when this is built; both codecs must reproduce them before anything else):

```
PRS  = 50617373776f7264                                   ("Password")
CI   = 6f630b425f726573706f6e6465720b415f696e69746961746f72
sid  = 7e4b4791d6a8ef019b936c79fb7f2c57
hash generator string (first 32 bytes of SHA-512, = the 255-bit field element)
     = 92806dc608984dbf4e4aae478c6ec453ae979cc01ecc1a2a7cf49f5cee56551b
g    = 64e8099e3ea682cfdc5cb665c057ebb514d06bf23ebc9f743b51b82242327074
ya   = 21b4f4bd9e64ed355c3eb676a28ebedaf6d8f17bdc365995b319097153044080   ADa = 414461 ("ADa")
Ya   = 1b02dad6dbd29a07b6d28c9e04cb2f184f0734350e32bb7e62ff9dbcfdb63d15
yb   = 848b0779ff415f0af4ea14df9dd1d3c29ac41d836c7808896c4eba19c51ac40a   ADb = 414462 ("ADb")
Yb   = 20cda5955f82c4931545bcbf40758ce1010d7db4db2a907013d79c7a8fcf957f
K    = f97fdfcfff1c983ed6283856a401de3191ca919902b323c5f950c9703df7297a
ISK_IR = a051ee5ee2499d16da3f69f430218b8ea94a18a45b67f9e86495b382c33d14a5
         c38cecc0cc834f960e39e0d1bf7d76b9ef5d54eecc5e0f386c97ad12da8c3d5f
```

The draft's B.1.10 low-order points for `scalar_mult_vfy` (every one must give the all-zero `K` and abort) go into the same file.

### Hooks needed from the re-invite work

1. Message ids for the five `PAIR_*` messages (and their CBOR keys) in `protocol/schema/messages.yaml`, from the range the re-invites allocate.
2. The framing of a packet **outside a game**: the header's game id (0?) and how the security layer is skipped for these ids only, with the receive path dropping them unless adoption is listening.
3. The channel and schedule on which an idle box listens (the invites' idle channel), and the duty-cycle budget an unadopted box may spend on `PAIR_OFFER`.
4. A single HKDF-SHA256 helper on both sides (core C with mbedtls, Python with `cryptography`) and one table of labels.
5. In `field_link.c`'s idle receive, a dispatch of `PAIR_*` to `adoption.c` (a new `adoption_pair_*()` API there), and in the controller a pairing service next to the invite flow, under the GM token.
6. The `PAIR_KEY` seal reuses the invites' AES-CCM construction (nonce layout, tag length) if it fits 80 bytes of plaintext.

### RFC 0001 amendment (proposal text only; not applied to messages.yaml)

> **Amendment N (proposed, numbered after the re-invite amendment): Adopting a box over the radio.** Five message types travel outside any game, between an unadopted (or PIN-unlocked) box and a field controller, on the idle-box channel defined by the re-invite amendment: `PAIR_OFFER` (box, broadcast, at most every 10 s and within the sub-band's duty cycle), `PAIR_START`, `PAIR_REPLY`, `PAIR_KEY`, `PAIR_DONE`. They carry no game id and no AES-CCM layer; their payloads are CBOR maps with integer keys as in section 7 of `protocol/adoption.md`, at most 120 bytes. Their security is CPace (draft-irtf-cfrg-cpace, `CPACE-X25519-SHA512`) with the code the box shows as its password, explicit key confirmation both ways, and the field join key sealed with AES-128-CCM under a key derived from CPace's ISK with HKDF-SHA256. A node that is not adopting drops them; a node relays none of them (hop limit 0). Known answers: the draft's Appendix B.1.

## Decisions

AD-1 to AD-14 in [docs/review/decisions-to-review.md](../docs/review/decisions-to-review.md#adopting-boxes-2026-10-21).
