# Security policy

Atalaia is pre-alpha and not ready for production use.

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's private vulnerability reporting ("Report a vulnerability" under the repository's Security tab), or contact the maintainers privately.

Useful reports include:

- the affected component (core, firmware, app, controller, site server, protocol),
- steps to reproduce,
- the impact you expect, for example spoofed captures, leaked positions or edited chrono records.

We aim to acknowledge reports within 7 days.

## In scope

Game integrity matters as much as data security. Issues such as forged Skirmesh-RF packets, replayed events, players seeing enemy positions, or editable chrono records are all in scope.

## What has been tested where

The security review of 30 October 2026 (findings FLD-*, SRV-*, APP-*, SC-*, LIVE-*; decisions SR-1 to SR-94 in `docs/review/decisions-to-review.md`) was done on the code. Its fixes are tested in software, on a computer and in containers, and run on the preview server (tests.atalaia-project.link) since 30 October. **None of the radio, firmware, app or controller fixes has been tried on a real board, a real phone or a real field**, and no outside penetration test has been done. Read each section below with that in mind.

## Community modes and mode keys

Report privately, as above, a community mode whose script gets around the sandbox, a mode key that may be known to someone else, or a registry package that is not what its source says. A key is revoked and the packages it signed are taken down as [docs/community/keys.md](docs/community/keys.md) and [docs/community/moderation.md](docs/community/moderation.md) describe. The project's registry key, which gives the verified badge and is built into the Field Box firmware, is kept offline by the maintainer and never in CI.

## Player tags can be copied

A player's NFC tag (the tag of Kill Confirmed, Respawn and Lives, Player Check-in, Medic Kit, Money Factory; [protocol/nfc-tag.md](protocol/nfc-tag.md)) is a **bearer token**. Its signature covers the format version, the player id, the team and the game id with the game's key, and **not the chip's UID**. Anyone who can read the tag with a phone can write the same bytes to a blank tag, and a box cannot tell the copy from the original: the copy works as that player, in that game, for that team. What limits this is that the key is new for every game, so a copy works only until the game ends, and that a player cannot make a tag for another player, team or game without the game key.

What to do about it today, by risk:

- Treat a tag like a name badge, not a credential: do not let it carry value outside a game (no prize, no bar tab, no access to anything), and expect that someone can lend theirs to a friend. Modes where this matters (Money Factory, the Medic Kit) are only as honest as the players.
- Write the tags yourself, hand them out at the briefing and do not leave them lying about between games; write new ones for every game (the game key changes, so the old ones stop working anyway).
- **Locking a tag read-only does not stop copying**: a locked tag can still be read. It stops a player overwriting or blanking a tag, so it is worth doing for tags that will not be rewritten (a lock cannot be undone, so not for tags you reuse from game to game). The Atalaia tag writer does not lock tags yet: it writes a tag for each game, and a lock would make the tag a one-game item. Lock them with an NFC app if you want it.
- **Binding a tag to its chip** is the real fix: an NTAG 424 DNA chip signs each read with a counter and its own key (secure unique NFC messages), so a copy of the bytes is useless. It needs those chips (about three times the price of an NTAG213), a reader that can talk to them (the PN532 can, with more firmware work) and a way to provision per-tag keys. That is a design decision for the maintainer (FLD-6, decision SR-44), not built.

## The field controller on the network

The controller's own network surface, as hardened after a security review (decisions SR-50 to SR-59 in `docs/review/decisions-to-review.md`):

- **Tokens go over HTTPS.** With HTTPS on (the default), the GM token and players' tokens are refused on plain HTTP from any address but the controller's own loopback; the read token may read there, for the scoreboard. The check-in poster's and the CA fetch's requests carry no token and stay on HTTP. The GM console works on `https://<controller>:8443/console/`; the browser trusts the field CA once. A field on a closed network it controls can set `[api] http_tokens = true`.
- **HSTS** is sent on TLS answers only (never on the field's plain-HTTP listener); behind a TLS-ending proxy set `[api] trusted_proxy = true`.
- **Bodies are capped** before they are parsed: 64 KiB for JSON, more only on upload routes ([controller README](controller/README.md#https-and-the-field-ca)).
- **MQTT.** Plain MQTT (1883) listens on the Pi's loopback only; scoreboards and GM tools on the field's network use TLS on 8883 with the field CA. Boxes and Android props do not use MQTT.
- **ATAK.** Multicast never carries player positions. `players = true` sends every player's position to the staff devices; use `[atak] staff_tls` (or the remote relay, which is TLS with client certificates), or a wired or VPN link: without TLS they cross the field's network readable.
- **Signed modes.** Revocation fails closed and is fetched again before every install and upload; an offline field keeps the last revocation list for `[modes] revocation_max_age_days` (30) and then installs nothing signed; `[modes] min_versions` sets a floor per mode.
- **The service** runs with `NoNewPrivileges`, `ProtectSystem=strict` (only `/var/lib/atalaia` writable), `ProtectHome`, `PrivateTmp`, restricted socket families, no capabilities and only the serial devices it opens ([controller/deploy/atalaia-controller.service](controller/deploy/atalaia-controller.service)).

Not covered here yet: the phone controller's ATAK feed has no TLS option (use the remote relay or a wired link), and its signed-mode revocation (`controller_signed_modes.dart`) still behaves as the Pi's did before: a missing `revoked.json` counts as none and an upload uses the cached index.

## Recorded radio packets are refused

Every receiver (the Field Box, the USB radio modem, the Pi controller and the phone controller) keeps a **replay window per source**: the highest `epoch << 16 | seq` seen and a 64-bit bitmap, applied only to a packet that authenticated. A counter already seen, or 64 or more below the highest, is dropped however long after it was recorded. A box also refuses a game-state command (start, pause, resume, end) or a TIME older than the last of its kind it applied, which covers a recording of a frame it never heard live. A box whose epoch store was lost draws a new epoch from the hardware random generator rather than reusing nonces (RFC 0001 Amendment 23; findings FLD-1 and FLD-10; shared vectors in `protocol/vectors/replay_window.json`).

Limits: the window lives in RAM, so a box that has just rebooted accepts the first packet of each source; the change is not on the wire, so a box that has not been updated stays exposed to replay; and the radio is encrypted but not hidden (anyone can record it).

## The site server and accounts

- **Changing how an account logs in needs a second factor.** Adding, renaming or removing a passkey, starting or turning off TOTP, setting, changing or removing the password, linking or unlinking a social login and confirming an account merge are refused (403 `mfa_required`) unless the session passed a TOTP or passkey step-up. A social login alone is not one. A merge never carries passkeys into an account with a staff role (SRV-1).
- **Bodies are capped** (413 past 1 MiB, 4 MiB on image uploads and the registration import; 5 MB in the Caddyfiles). A request a proxy says came over HTTP is redirected to HTTPS. The health check answers only `ok`; the version and uptime are in the metrics, behind a token. The server will not start without `ATALAIA_PUBLIC_URL` (outside a preview), because the passkey origin and the redirect address must not come from the `Host` header.
- **Account enumeration** through the ATAK certificate form and role grants is closed (both answer the same for "no such account" and a refused grant). A single-field export holds only the field's audit rows.
- **Social login** keeps the issuer with the subject, binds the sign-in to the browser (a cookie) or, for the app, to the app instance (a PKCE-style verifier; set `ATALAIA_OIDC_APP_REQUIRE_CHALLENGE=on` once every app is updated). In a hosted hub, `ATALAIA_OIDC_RELAY=on` gives one callback address for the whole hub: the hub signs a state naming the field, looks the field up in its registry and hands over to the field's own callback; an unknown or suspended field gets a plain error and nothing is forwarded.
- **Hosted mode** keeps fields apart by a database role and a schema per field with row-level security underneath. Before any field is offered it, the operator's go-live checklist (`server/docs/DEPLOY.md`) lists six conditions, among them a signed data processing agreement per field. None has been met yet, and hosted mode is not offered.

## What the app trusts

- A pinned **field CA is exactly one certificate**: a bundle is refused, and the app keeps only the certificate it hashed (APP-1).
- **No app-wide cleartext HTTP on Android.** The network security config allows plain HTTP only to the loopback, the emulator's host, `192.168.4.1` and `atalaia.local` (the web-view console); a build with `-Patalaia.cleartextLan=true` restores the old policy for fields whose console has another address (APP-3). The app's own clients still pin the field CA.
- **The release APK is never signed with the debug key by accident**: it reads a keystore from `ATALAIA_RELEASE_*` variables or Gradle properties and stops without one. The maintainer has not yet made the release keystore (APP-2).
- **The social-login ticket is bound to the app instance**, so a ticket taken from the return link is useless (APP-4).

## Personal data at a field and on the server

What the software does about people's data, as built (the notice and DPIA templates in `docs/templates/` are the legal side, still templates for each field to fill in):

- **Accounts rest on the contract**, not on consent; sign-up records which version of the privacy notice was shown and that the person is 16 or older. No date of birth is kept. With no notice published, sign-up is closed.
- **The APD or association card is checked at check-in** by a marshal or the GM, who ticks "card seen, matches"; the membership number is then erased on the controller (the verdict, the expiry and who checked stay), and the site server erases its copy when the game's outcome arrives or the game ends.
- **A player's position is shared only by a separate, unticked choice at check-in**, which can be changed at any time; without it the controller refuses the positions.
- **Retention.** The audit log forgets network addresses after 180 days (`ATALAIA_AUDIT_IP_DAYS`, 90 to 365); an account unused for 24 months (`ATALAIA_INACTIVE_ACCOUNT_MONTHS`) is warned and anonymised 30 days later; game history keeps 90 days with player ids and team results without them 365 days; chrono records 365 days by default; a ban ends after 12 months by default; a field sets its own periods within the ranges.
- **Erasure** reaches other fields: a person's erasure or a withdrawn chrono-sharing consent tells their controllers to drop the copies they pulled. Erasures are kept as hashes in a ledger outside the database and applied again after a restore, so a restore does not bring back a person who was erased.
- **Cross-field sharing** of chrono readings needs the field's administrator to accept the sharing terms (the field is the controller, the hub operator its processor, the sharing fields joint controllers for that step only), and each player's consent.
- **Map fetching** (the console's *Load the field from a map*) reaches OpenStreetMap, Overpass, Nominatim and aerial imagery services from the browser; a field can turn it off in *Settings*, and then both controllers serve the page with headers that stop the browser reaching them.

## The build and the release

Every GitHub Action is pinned by commit, the ESP-IDF image by digest, every `pip install` in CI reads a hash-pinned file, and Dependabot proposes weekly updates. The release signing job runs in the `release` environment and fails unless the tag's commit is on `main`. The maintainer still has to create that protected environment and move the two signing secrets into it ([firmware/esp32/docs/RELEASE_SIGNING.md](firmware/esp32/docs/RELEASE_SIGNING.md)); until then a repository-level secret still reaches the job. The Lua sandbox meters string patterns and `string.rep` as well as instructions, and the CBOR decoders in C, Python and Dart refuse deep nesting and counts larger than the input.

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
