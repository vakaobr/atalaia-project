

## The app logs in without a password, a grid on the player's plan, NFC replica stickers, sealed secrets (PKA-1 to PKA-6, 2026-10-28)

The survey of what the docs still listed as unbuilt (2026-10-28), package A. Not tried on a real phone, against the real providers, with a verified App Link or with the real Keystore migration. Not built: iOS login (the server serves the AASA file), passkeys before Android 14, in-app account creation (S17-16).

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| PKA-1 | How does the app log in without a password? | Social login in a Custom Tab with return_to the site's own `https://<host>/app/oidc?s=<nonce>` (an App Link) and the `#oidc=<ticket>` return; passkeys through Android Credential Manager (Android 14+, no Play services). The server serves assetlinks.json and apple-app-site-association (off when unset), accepts return_to `/app/oidc`, and accepts the origin `android:apk-key-hash:<cert>` for passkeys. | Follows STATUS "what the app will need"; Credential Manager's origin is the certificate hash. | built (2026-10-28); open for the maintainer's review |
| PKA-2 | A browser address for the app's social login? | `start` also returns `browser_url` (GET `/auth/oidc/{p}/browser?x=&s=`), which sets the binding cookie in the browser and redirects to the provider; a link or reauth shows a confirmation naming the account first. | The cookie from start's answer lands in the app's HTTP client, not the browser, so the callback would always fail; the confirmation stops an attacker-made address from linking a victim's provider account. | built (2026-10-28); open for the maintainer's review |
| PKA-3 | Which App Link hosts does the manifest declare? | One host from `-Patalaia.appLinkHost` (wildcards allowed, default `app-links.invalid`); without it a social return stays in the browser page. | Android reads App Links at install; self-hosted sites have arbitrary hosts; custom schemes rejected (another app could steal the ticket). | built (2026-10-28); open for the maintainer's review |
| PKA-4 | Which remaining secrets are sealed? | The site API key, the player's secret per field and the site refresh token, in `secrets.enc`, with a read-back before the plaintext is removed. | Closes PD6. | built (2026-10-28); open for the maintainer's review |
| PKA-5 | Grid on the player's plan | Drawn over the plan in the Field map card; the player's cell shown ("C4"); fetched on opening, level change and stream reload. | The controller already serves the grid to viewers. | built (2026-10-28); open for the maintainer's review |
| PKA-6 | NFC sticker when registering a declared replica | On NFC phones: hold a sticker (its UID becomes the tag), use the QR label, or cancel; a sticker already used is refused. | QR path unchanged; one tag, one replica. | built (2026-10-28); open for the maintainer's review |

## Scenario setup re-sent with a box ACK, Change field, scenario languages (PKB-1 to PKB-9, 2026-10-28)

Package B. The maintainer asked for the box ACK (SL-39) in this wave. Measured in the radio model only; the long field of 20-30 boxes stays poor (56 %, 11 %), for the field test.

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| PKB-1 | How does a scenario re-send setup CMDs? | After 8, 16, 32, 64 and 128 s, five repeats at most, stopping when the box's `node.setup_applied` for the same `kind` is heard; a box that never confirms gets the five and no more. | Bounded airtime; repeats alone cost 6 frames per setup, with the ACK 1.4-2.8. | built (2026-10-28); open for the maintainer's review |
| PKB-2 | Is a repeat safe for a box that already has the setup? | Yes: each repeat carries the state the runtime knows now (holder, have, armed/left, done/failed); a new setup resets the schedule. | The reboot path already sends that state; idempotent. | built (2026-10-28); open for the maintainer's review |
| PKB-3 | How does a box ACK a setup CMD? | New standard event `node.setup_applied` (id 56, normal priority, data `kind`) from the objectives package, on the existing event ACK and resend; RFC 0001 Amendment 16; no new frame or opcode. | Additive; older boxes never send it and the re-send covers them. | confirmed by the maintainer (2026-10-28) |
| PKB-4 | Adopting an adopted box to another field from the admin menu? | Last picker entry "Change field", behind the admin PIN with a confirmation, only on an adopted box with a radio and a PIN; arms one move and shows the pairing code. | Nothing is forgotten until a new key has been stored (`readopted`). | built (2026-10-28); open for the maintainer's review |
| PKB-5 | What does the arming replace? | The PIN of that one pairing-code offer only; a card or `@adopt` still asks; it ends with the code (`*`, 5 min, lock), the first success or any other adoption. | The PIN was already typed for the menu. | built (2026-10-28); open for the maintainer's review |
| PKB-6 | Old field kept if the move fails or is cancelled? | Yes: cancel, timeout, lock, refusal or a failed store leave the old key and name. | AD-16. | built (2026-10-28); open for the maintainer's review |
| PKB-7 | Texts given the box's fonts? | en "Change field", pt "Mudar de campo", de "Feld wechseln", zh-TW 綁定新場地; all glyphs already in the fonts. | Fonts cannot change offline; gen_box_fonts --check stays green. | built (2026-10-28); open for the maintainer's review |
| PKB-8 | How is the effect measured? | The relay study's radio model, cmd_mode oneshot/resend/resend_ack, 5 seeds, all layouts, 10-30 boxes; table in phase 2 STATUS. One shot 0-78 %; with ACK 100 % in meshes and CQB up to 20 boxes, 89-100 % at 30; long field 20/30 boxes 56 %/11 %. | Same model as SL-13's table 7. | built (2026-10-28); open for the maintainer's review |
| PKB-9 | Scenario `lang` and i18n texts? | `lang` takes pt, en, de, zh-tw; `i18n` stays pt only (the block editor cannot carry i18n.de/zh-tw), so a German or Chinese box shows the objective's English name. | Old manifests stay valid; follow-up. | built (2026-10-28); open for the maintainer's review |

## Site server: data and quota page, game-time timelines, club fields, hosted quotas, custom domains, the OIDC relay design (PKC-1 to PKC-8, 2026-10-28)

Package C. The maintainer chose (2026-10-28) a hub-level OIDC relay for hosted mode, designed now (ADR-P4-13) and built with the legal review, and custom domains per hosted field in this wave.

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| PKC-1 | How does a field admin see the export and quota use? | New page `/staff/fields/<field>/data`, admin only, FU2/FU9 rules; ZIP read with the bearer token, offered from a blob URL, SHA-256 shown; quota use from a new read-only `GET /api/v1/fields/{id}/quotas` (single-field: `hosted:false`, no rows). | The page stays a thin client; quota use had no read API. | built (2026-10-28); open for the maintainer's review |
| PKC-2 | What time do score timelines use? | `t` is game time in seconds, pauses not counted, never going back; a `score.delta` uses its own game time; a counter's rise is interpolated from the batches' arrival and game times; `at` stays the arrival time. | The wire carries no game time for counters, so an estimate is the most the server can offer. | built (2026-10-28); open for the maintainer's review |
| PKC-3 | How is a club's list of fields derived and who sees it? | From `field_teams`; members see every field with a team of the club, anyone else only fields with a public page (linked). | Never reveals a field that did not publish itself. | built (2026-10-28); open for the maintainer's review |
| PKC-4 | How is the staff game page tied to its own field? | The timeline answer carries `field_id`; the page shows "not found" when it differs from the address. | The API checks access per game, not per address. | built (2026-10-28); open for the maintainer's review |
| PKC-5 | Per-field quotas, stored bytes and operator alerts? | Per-field overrides in the registry's `quotas` jsonb over the environment defaults (`hosted quota SLUG NAME VALUE|off|default`); new `stored_mb` quota (default 2048); refusals leave notes in an insert-only inbox that `hosted quota-hits` moves to the hub audit log (no email). | The server's role may not touch the audit log; the inbox keeps that isolation. | built (2026-10-28); open for the maintainer's review |
| PKC-6 | How do custom domains work? | One name per field in the registry, pending until a DNS TXT challenge passes (`hosted domain set/verify/remove`); then it routes like the field's own name, and Caddy's `ask` says yes only for a registered, verified, active name. | Proof of control before routing or a certificate; a stdlib resolver avoids a new dependency. | confirmed by the maintainer (2026-10-28) |
| PKC-7 | Where do social-login redirects go on a custom name? | The request's own name; the operator registers that address at the provider until the relay exists. | One host per login keeps the binding cookie valid. | built (2026-10-28); open for the maintainer's review |
| PKC-8 | The hub-level OIDC callback relay | Design only, ADR-P4-13: one hub callback, field and host in HMAC-signed state, a 303 to the field host, the code exchange still at the field; built with the legal review. | Maintainer's choice (2026-10-28). | confirmed by the maintainer (2026-10-28) |

## Library and schedule pushed to controllers, chrono over-limit and repeat offenders, positions for the remote GM (PKD-1 to PKD-5, 2026-10-28)

Package D. The maintainer decided (2026-10-28) that the remote GM sees the players' positions whenever they share them (S19-7: "yes, always").

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| PKD-1 | How are library and schedule changes pushed on the stream (S20-8)? | `field.changed` gets an optional `what` list (`branding`, `library`, `schedule`); a note without `what` is the old branding note byte for byte. Both controllers pull at once what they take from the site and open the stream when `[sync] library` is on (the default). Rosters are not announced. | Additive: older controllers ignore a note with `what`. Opening the stream for the library by default makes push work out of the box; it carries nothing of the game. | built (2026-10-28); open for the maintainer's review |
| PKD-3 | How do `repeat_offender` and `delta_j` (S14-7) get built? | Controllers send `limit_j` per reading (optional, kept in store schema 16), omitted for a server that refuses it. The server stores `limit_j`, `delta_j`, `repeat_offender` (migration 0018); a repeat is a later violation of the same player at the field by reading time, recomputed on every arrival. | The controller judges, so the server must not guess the limit; time order makes late uploads correct; a flag, not a new violation_type. | built (2026-10-28); open for the maintainer's review |
| PKD-5 | How does the remote GM see positions (S19-7)? | A separate `positions` stream message sent only with `remote_gm` on, held in memory per link and relayed in GET .../remote-gm and its SSE stream to the field's gm (TOTP) only; never stored or logged. The page lists them (no plan). The app's sharing notice names the remote GM (4 languages). Pseudonymous ids, GM view, fresh within 3 intervals. | Maintainer's decision "yes, always" (2026-10-28); `live` stays free of positions; memory-only like the live view. | confirmed by the maintainer (2026-10-28) |

## Registration import on the controller, the grid in ATAK and on paper, letters the boxes lack, site branding in the console (PKE-1 to PKE-8, 2026-10-28)

Package E. The print layout was tested with a stubbed print dialog, never printed.

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| PKE-1 | How does an imported list reach the controller's check-in list, and who owns the format? | `POST /games/{id}/checkins/import` (JSON: format, data, source, dry_run, basis_confirmed); the format file moved to the controller package, the server re-exports it; the phone has a Dart port held to shared vectors. | One file, no drift; the envelope fits the contract vectors. | built (2026-10-28); open for the maintainer's review |
| PKE-2 | How do imported players arrive, and do they go back to a site? | `expected`, uuid5 registration id, `from_roster` false, no ticket; a marshal ticks them by name; never synced back; roster removal only touches roster-made rows. | No ticket means an app arrival would be refused; unknown registrations are not pushed to a site. | built (2026-10-28); open for the maintainer's review |
| PKE-3 | Import safety rules | Dry run first; a real import needs the field's confirmation of its basis; arrived players never changed; missing rows only counted; no names in logs. | Mirrors the site server's import; the field is the data controller. | built (2026-10-28); open for the maintainer's review |
| PKE-4 | What goes in ATAK remarks for the grid? | `, grid C4` after the level name for boxes, features and indoor players; GPS players none; a grid change resends everything. | Matches the console's wording; a GPS fix has no plan position. | built (2026-10-28); open for the maintainer's review |
| PKE-5 | How is the grid map printed? | A sheet drawn into its own root while printing, the browser's print dialog gives the poster or PDF; no new page, no server PDF. | CSP forbids inline styles; works offline. | built (2026-10-28); open for the maintainer's review |
| PKE-6 | When does the console warn about a name's letters? | The font generator emits `box-glyphs.json`; a letter in no font size gets a warning, one in only some sizes a softer one; the name is still accepted. | Cannot drift from the fonts. | built (2026-10-28); open for the maintainer's review |
| PKE-7 | How does the console know branding comes from the site? | The branding answer carries `"source": "site"` only with `[sync] branding = "site"`, on both controllers. | No new endpoint; local fields' answers unchanged. | built (2026-10-28); open for the maintainer's review |
| PKE-8 | What does the site teams view show? | A separate read-only list of the site's saved teams with a badge and no delete. | The controller already refuses to edit those (409). | built (2026-10-28); open for the maintainer's review |

## Android props fetch signed mode packages (PKF-1 to PKF-7, 2026-10-28)

Package F. No project mode key is published yet, so a build sets one or the user adds it in Settings. Not tried on a real phone.

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| PKF-1 | When does a prop fetch a mode? | Only when a part of the join's `mode_id` is neither built in nor kept and the join has keys 13, 14 and 16 (as a box); without key 16 it says it lacks the mode, as before. | Same rule as the box (P5D-2); keeps the controller's start-guard accounting. | built (2026-10-28); open for the maintainer's review |
| PKF-2 | Which keys does a prop trust? | Keys built into the build (`ATALAIA_MODE_KEYS`) plus an in-app setting of at most 4 mode keys; never a key the controller sends; no key, nothing fetched. | Counterpart of CONFIG_ATALAIA_MODE_KEYS (P5B-9); no project key is published yet. | built (2026-10-28); open for the maintainer's review |
| PKF-3 | Which checks, in which order? | The box's `boxCheckRelease` then `boxCheckArchive` (same codes), then `mode.yaml` must match the signed manifest, then the composed game must load in the core sandbox; only then kept. | The box's checks, plus what a phone actually reads and runs. | built (2026-10-28); open for the maintainer's review |
| PKF-4 | What does a prop keep, and for how long? | Signed release + archive, at most 8 packages / 512 KiB, LRU but never the game's own, re-verified with the current keys on every read; built-ins never replaced; key 17 forgets all. | Same limits and revocation as the box (P5B-12, P5B-15). | built (2026-10-28); open for the maintainer's review |
| PKF-5 | How does the controller learn the outcome? | The box's `atalaia-mode-report-v1` with the game key's HMAC after each part; no LoRa `node.modes_failed` path (the controller's `report_lost` timeout applies). | Completes the controller's fetch tracking. | built (2026-10-28); open for the maintainer's review |
| PKF-6 | What happens on a refusal? | The prop stays on setup with a message per code (4 languages), Prepare disabled; the GM can re-invite. | Never runs unverified code. | built (2026-10-28); open for the maintainer's review |
| PKF-7 | Is there a separate prop manual? | No; section 11 of the Field Box manual and app/README carry it. | No prop manual exists. | built (2026-10-28); open for the maintainer's review |

## The field's logo on the Field Box's big screen (PKG-1 to PKG-5, 2026-10-28)

Package G, the maintainer's 2026-10-28 answer to BR24's "left for later". Not yet seen on a real panel.

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| PKG-1 | How does the box get the field's logo? | The controller converts the PNG logo to 96x96 RGB565 (18,440 bytes) at `/api/v1/field/box-logo[/release]`; the box fetches it over the mode-package HTTPS path (never LoRa), keeps it in `/littlefs/logo.bin` keyed by the logo's SHA-256, and fetches again only on change. | No room for an image decoder on the box; the HTTPS path exists and is pinned to the field CA. | built (2026-10-28); open for the maintainer's review |
| PKG-2 | Which logos are converted? | PNG only, up to 1 Mpixel; JPEG/WebP get a 404 and the box keeps the Atalaia towers. | Controllers have no JPEG/WebP decoder (BR7); a follow-up could convert in the console. | built (2026-10-28); open for the maintainer's review |
| PKG-3 | Why those formats and sizes? | 96x96 RGB565, 8-byte header, alpha composited on `#101418`, integer area-average resampling. | 18 KB, no alpha blending on the box; identical bytes in Python and Dart (box_logo.json). | built (2026-10-28); open for the maintainer's review |
| PKG-4 | When does the box fetch, and where is it shown? | Once per joined game while it waits (join names the controller); on READY and on standby with no team armed; the Atalaia towers as fallback; OLED unchanged. | No new trigger or radio traffic; those screens have room. | built (2026-10-28); open for the maintainer's review |
| PKG-5 | Flash budget | +3,328 bytes to 92.95 % of the slot; partition table unchanged. | Within the 4 % margin. | built (2026-10-28); open for the maintainer's review |
