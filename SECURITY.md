# Security policy

Atalaia is pre-alpha and not ready for production use.

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's private vulnerability reporting ("Report a vulnerability" under the repository's Security tab), or contact the maintainers privately.

Useful reports include:

- the affected component (core, firmware, app, controller, site server, protocol),
- steps to reproduce,
- the impact you expect, for example spoofed captures, leaked positions or edited chrono records.

We aim to acknowledge reports within 7 days.

## Community modes and mode keys

Report privately, as above, a community mode whose script gets around the sandbox, a mode key that may be known to someone else, or a registry package that is not what its source says. A key is revoked and the packages it signed are taken down as [docs/community/keys.md](docs/community/keys.md) and [docs/community/moderation.md](docs/community/moderation.md) describe. The project's registry key, which gives the verified badge and is built into the Field Box firmware, is kept offline by the maintainer and never in CI.

## Player tags can be copied

A player's NFC tag (the tag of Kill Confirmed, Respawn and Lives, Player Check-in, Medic Kit, Money Factory; [protocol/nfc-tag.md](protocol/nfc-tag.md)) is a **bearer token**. Its signature covers the format version, the player id, the team and the game id with the game's key, and **not the chip's UID**. Anyone who can read the tag with a phone can write the same bytes to a blank tag, and a box cannot tell the copy from the original: the copy works as that player, in that game, for that team. What limits this is that the key is new for every game, so a copy works only until the game ends, and that a player cannot make a tag for another player, team or game without the game key.

What to do about it today, by risk:

- Treat a tag like a name badge, not a credential: do not let it carry value outside a game (no prize, no bar tab, no access to anything), and expect that someone can lend theirs to a friend. Modes where this matters (Money Factory, the Medic Kit) are only as honest as the players.
- Write the tags yourself, hand them out at the briefing and do not leave them lying about between games; write new ones for every game (the game key changes, so the old ones stop working anyway).
- **Locking a tag read-only does not stop copying**: a locked tag can still be read. It stops a player overwriting or blanking a tag, so it is worth doing for tags that will not be rewritten (a lock cannot be undone, so not for tags you reuse from game to game). The Atalaia tag writer does not lock tags yet: it writes a tag for each game, and a lock would make the tag a one-game item. Lock them with an NFC app if you want it.
- **Binding a tag to its chip** is the real fix: an NTAG 424 DNA chip signs each read with a counter and its own key (secure unique NFC messages), so a copy of the bytes is useless. It needs those chips (about three times the price of an NTAG213), a reader that can talk to them (the PN532 can, with more firmware work) and a way to provision per-tag keys. That is a design decision for the maintainer (FLD-6, decision SR-44), not built.

## In scope

Game integrity matters as much as data security. Issues such as forged Skirmesh-RF packets, replayed events, players seeing enemy positions, or editable chrono records are all in scope.

## The field join key is a field secret

Every controller and box of a field shares one 32-byte **field join key** ([protocol/join.md](protocol/join.md)). It authenticates join cards and QR codes, and since boxes can be invited into the next game over the radio it also keys the **field frames** ([protocol/field-frames.md](protocol/field-frames.md)): an invite carries the game's key, encrypted under a key derived from the join key. Whoever holds the join key and records the field's radio can therefore read the keys of the games joined by invite, and with them those games' traffic. The maintainer accepted this trade-off (decision RJ-2 in `docs/review/decisions-to-review.md`). Keep the join key only on the controllers (their store, `controller.toml`) and in the boxes' NVS (**not encrypted in the images the project builds today**, see the next section), never in logs, screenshots or tickets, and change it on every controller and box if one is lost or leaves the field.

The controller also keeps the live game's key in its store by default (`persist_game_key = true` since decision OT-7, 2026-10-22), so a game survives a restart; the key is erased when the game ends. This adds little to what is already at rest there: the field join key, from which every game invited over the radio can be read. A field that turns it off still ends its games after a restart: the controller tells the boxes over the field radio (GAME_OVER, sealed with the field key).

Boxes get the key when they are adopted ([protocol/adoption.md](protocol/adoption.md)): an **NFC field card** holds it (keep field cards locked away, like the key itself), the **USB cable** writes it from the controller, and the **pairing code** sends it over the radio sealed under a key that only a box showing the code the GM typed can derive (CPace). A lost card or box means `python3 -m atalaia_controller join-key --rotate` and adopting every box again.

### What a lost or stolen Field Box exposes today

The firmware images the project builds and releases **do not use NVS encryption, flash encryption or secure boot**: `firmware/esp32/sdkconfig.defaults` sets none of them, and the eFuses of a box flashed from a release are all unburnt. (Earlier versions of this page and of the protocol documents spoke of "encrypted NVS"; that is the design for a production box, not what the images do yet. [protocol/adoption.md](protocol/adoption.md) section 2 lists what a production box needs, and [firmware/esp32/docs/RELEASE_HARDENING.md](firmware/esp32/docs/RELEASE_HARDENING.md) is the plan to get there.) The box logs `NVS encryption is off` at every boot to say so.

So anyone who holds a box and a USB cable can read its whole flash with `esptool read_flash` and take from it, without the admin PIN:

- the **field join key** (and so the keys of every game invited over the radio from now on, and the ability to forge join cards and QR codes for the field);
- the **game key** of a game the box has joined and not finished, the admin PIN (stored in NVS), the field's Wi-Fi password if one was set for firmware updates, and the box's device id;
- the firmware, which holds no secret of the project: the public release and mode keys are built in, the private halves are not.

The admin PIN protects the box's own menus and its serial commands; it does not stop a flash dump, a re-flash with another image, or erasing the box.

If a box is lost, stolen or leaves the field with someone you do not trust: **rotate the join key** (`python3 -m atalaia_controller join-key --rotate`, then restart the controller and adopt every remaining box again, by card, cable or pairing code; destroy the old field cards). Until you do, the finder of the box can join the field's games and read the radio. A rotation also ends a game's key only when that game ends, so do it between games. The lost box itself cannot be adopted by the new key without its admin PIN; with the PIN gone from view (it is in the flash) assume the box is the thief's.

**Serial commands.** The USB console of a box also takes `@joinkey <hex>` and `@update <version> <release id>`. In a **release build** both now need the admin PIN as their last word (`@joinkey <hex> <PIN>`, `@update <version> <id> <PIN>`; checked like every PIN, with its counted failures and waits; refused while no PIN is set). A **bench build** (`CONFIG_ATALAIA_SERIAL_KEYS`, which also carries `@hold`) takes them without a PIN, because the bench scripts and the Wokwi scenarios drive them; never put a bench image on a box that plays at a field. Over USB, `@adopt` was always PIN-gated for a box adopted to another field, and a firmware update must still be signed by a release key.
