<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Player tokens

A player token tells the field controller who is calling its API from a player's phone: which player, team and squad, with which role, in which game, until when (ADR-P3-9). The controller issues it when the player joins and checks it on every request (position reports and chrono access, plan phase E); the phone only carries it. It sits beside the GM and read tokens, which do not change. This file is the format, version 1.

Implementations: `controller/atalaia_controller/player_token.py` (Python: the controller) and `app/lib/security/player_token.dart` (Dart: an Android controller issues and checks tokens with it; a phone may read its own token's claims for display). Both check the shared vectors in [`vectors/player_token.json`](vectors/player_token.json): valid tokens with their exact payload, MAC and text, and invalid ones with the reason they must fail.

## Format

```
apt1.<payload>.<mac>
```

- `apt1` is the version (Atalaia player token, version 1). A reader refuses `apt` followed by any other number as `version`.
- `<payload>` is base64url without padding (RFC 4648 section 5) of the claims as **canonical JSON**: one object, members sorted by key, no whitespace, integers in decimal, strings with only `"` and `\` escaped (they never occur here).
- `<mac>` is base64url without padding of the full 32-byte HMAC-SHA256, keyed with the controller's token key, over the ASCII text `apt1.<payload>`.

It goes in `Authorization: Bearer apt1....` like the other tokens. A token is at most 512 characters; a typical one is about 165.

## Claims

All six are required and no others are allowed:

| Claim | Type | Values |
| --- | --- | --- |
| `exp` | integer | when the token expires, Unix seconds, 1 to 2³²−1; refused from that second on |
| `game_id` | integer | the game's 16-bit id, 1-65534 (as on the radio and in the join payload) |
| `player_id` | string | 1-32 ASCII letters, digits, `.`, `_` or `-`: the id on the player's tag ([nfc-tag.md](nfc-tag.md)) |
| `role` | string | `player`, `squad_leader`, `vip`, `marshal`, `gm` or `spectator` (ADR-P3-6's visibility table) |
| `squad` | integer | squad 1-255, 0 for none |
| `team` | integer | the 1-based team id in the game's team list (the join payload's order), 0 for none; at most 8 |

The first vector (its key is in the vector file):

```
payload: {"exp":1792339200,"game_id":4242,"player_id":"p-17","role":"player","squad":2,"team":1}
token:   apt1.eyJleHAiOjE3OTIzMzkyMDAsImdhbWVfaWQiOjQyNDIsInBsYXllcl9pZCI6InAtMTciLCJyb2xlIjoicGxheWVyIiwic3F1YWQiOjIsInRlYW0iOjF9.XdQmSWlROlwH_tNfRw4upJMRf7F0xc-Yc3QAVGtAznA
```

ADR-P3-9's example wrote `game_id` as `"g-001"`; the controller's games have 16-bit integer ids, so the claim is that integer (decision B9). The `role` decides which positions the controller sends to that connection (ADR-P3-6); a `gm` player token does not replace the GM token for game control.

## The key

ADR-P3-9 signs tokens with "the controller's game key". Version 1 takes any 16-64-byte key, and the controller should use a **token key of its own**: 32 random bytes made for each game and never written to a join payload, a tag or the radio (decision B8). The game key is held by every box and phone prop in the game and printed in every join card and QR code ([join.md](join.md)), so anyone holding one could mint a `gm` or `marshal` token and see every position, which the server-side filtering of ADR-P3-6 exists to prevent. Only the controller issues and checks tokens, so nothing else needs the key. A new game gets a new key, which also ends every token of the old game.

## Checking a token

A reader checks, in this order:

1. the text: ASCII, 1-512 characters, three parts separated by `.` (`format`);
2. the version: `apt1`, or `version` for `apt` and another number (anything else is `format`);
3. the parts: canonical base64url without padding, a 32-byte MAC (`format`);
4. the MAC, in constant time (`mac`);
5. the payload: UTF-8 JSON with exactly the six claims, of the right types and in range, and byte for byte its own canonical form (`format`): an authentic token with spaces, unsorted keys or a duplicate is still refused;
6. `game_id` against the game it is used for (`game`);
7. `team` against the game's number of teams (`team`);
8. `exp` against the controller's clock (`expired`).

There is no clock leeway: the controller issues and checks with the same clock.

## Security notes

- A token is a bearer credential: whoever has the text is that player until it expires. Phones keep it in their secure storage and send it only to the field's controller over the field network (HTTPS with the field CA, ADR-P3-9).
- A token cannot be revoked one by one in version 1; it ends with the game (or its `exp`). The controller can refuse a player by id if it needs to.
- Reading a token's claims without the key (`PlayerToken.peek` in Dart) is for showing a player their own role; it proves nothing.
