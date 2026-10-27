# Player tags

A player tag is the NFC tag (a sticker, card, key fob or wristband) a player carries in the modes that need to know who is at a prop: Kill Confirmed, Respawn and Lives, Player Check-in (ADR-P3-9), and the Medic Kit, where the tag is required to start a heal (decision MK1). It says who the player is and which team they play for, and it is signed with the game key, so a box can tell a real tag from a forged one without asking anyone. The tag's UID is reported but never trusted: some chips let anyone set it.

Implementations: `core/src/tag.c` (`atalaia/tag.h`, used by the Field Box and, through `dart:ffi`, by Android props) and `simulator/atalaia_sim/tag.py`. Both check the shared vectors in [`vectors/tag.json`](vectors/tag.json).

## Payload

```
version (1, = 1) | player (1-32 bytes) | team (1) | game_id (2, big-endian) | mac (16)
```

| Field | |
| --- | --- |
| `version` | 1 |
| `player` | the player's id: 1-32 bytes of ASCII letters, digits, `-`, `_` and `.` (no length byte: it is everything between the version and the last 19 bytes) |
| `team` | the player's team: its 1-based id in the game's team list (the join payload's order), or 0 for none |
| `game_id` | the game the tag was written for |
| `mac` | HMAC-SHA256 over everything before it, keyed with the game's 16-byte key, truncated to the first 16 bytes |

21 to 52 bytes in all. The game key is new for every game (ADR-P2-2), so tags are written for each game: an earlier game's tag fails, and says so (`game`). On an NFC Forum Type 2 tag (NTAG213 and up) the payload is one NDEF record, TNF 2 (MIME), type `application/vnd.atalaia.tag`, like the join card's `application/vnd.atalaia.join` ([join.md](join.md)); a tag may hold other records too.

ADR-P3-9 described the payload as `player_id + team (1) + game_id (2)` and the 16-byte HMAC with the game key. The version byte in front is an addition (decision A3 in `docs/review/decisions-to-review.md`), so the format can change later without guessing.

## Checking a tag

A reader checks, in this order: the length (`format`), the version (`version`), the game id against the current game (`game`), the MAC in constant time (`mac`), the player id's characters (`format`) and the team against the game's teams (`team`). Only then is the tag valid.

## What a mode sees

The node's host (the Field Box shell, the Android prop, the simulator) reads the tag, checks it with the game's id and key, and gives the mode an `nfc.tag` input event; scripts never see the game key:

```json
{"uid": "04a1b2c3d4e5f6", "valid": true, "player": "p-17", "team": "blue"}
{"uid": "04a1b2c3d4e5f6", "valid": false, "reason": "mac"}
```

`team` is the team's name (left out for a tag without a team). `reason` is `unsigned` (the card has no player-tag record), `no_game` (the node is not in a game with a key: a stand-alone box game), or `format`, `version`, `game`, `mac`, `team` as above. `atalaia_tag_event_json()` writes this data in C; `tag.event_data()` in Python.

On a Field Box the NFC reader is polled every 300 ms while a game runs; each card is read once per tap. `@tag <uid hex> [<payload hex>]` on the serial console does the same without a reader (bring-up and the Wokwi emulator, `CONFIG_ATALAIA_SERIAL_JOIN`).

## Writing tags

Whoever holds the game key makes the bytes: the field controller (the Pi, or the phone running as the controller). It signs a tag on request and nobody else needs the key:

```
POST /api/v1/games/{id}/tags     {"player": "p-17", "team": "blue"}
{"game_id": 17, "player": "p-17", "team": "blue", "team_id": 2, "mime": "application/vnd.atalaia.tag",
 "payload": "<hex>", "ndef": "<hex>", "memory": "<hex>"}
```

`payload` is the tag above, `ndef` the one NDEF record that holds it (what a phone or Web NFC writes to a tag) and `memory` the same record as the memory of a Type 2 tag from page 4 (what a writer of raw pages writes). The request needs the GM token, or the token of a marshal checked in to that game; the read token and other games' marshals are refused (403); a bad id or a team the game does not have is 400; a game that is not live on this controller has no key (409). The answer is never cached. The shared contract cases (`protocol/vectors/controller_api.json`, "player tags") check both controllers, and the vectors above check the codecs.

Three writers ask for it (decision TW-1): the GM console's Check-in tab (Web NFC where the browser has it, otherwise the bytes as hex and a file, and which app writes them), the phone controller's own screen (its NFC, asking its own controller on the loopback address), and the app's marshal role (`app/lib/marshal/tag_writer.dart`), which asks the field controller over the field's network, so a marshal's phone holds neither the field join key nor the game key for tags and needs the controller for every tag. The app checks that what it got is the tag it asked for (the record, the id, the team, the game) before it writes it; the MAC can only be checked by whoever has the key, and the boxes do. `atalaia_tag_encode()` and `atalaia_tag_to_ndef_tag()` (C), `tag.encode()` and `tag.to_ndef_tag()` (Python) and `encodeTag()` (Dart, which a prop checks tags with) make the bytes.
