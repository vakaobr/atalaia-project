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

Whoever holds the game key can write tags: the field controller, or the GM's phone. The app's marshal role writes them for a game picked with its join card or code (`app/lib/marshal/tag_writer.dart`, `lib/security/nfc_tag_signer.dart`); writing them from the GM console is not built yet (a follow-up for the controller); `atalaia_tag_encode()` and `atalaia_tag_to_ndef_tag()` (C), and `tag.encode()` and `tag.to_ndef_tag()` (Python), make the bytes.
