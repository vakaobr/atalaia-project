<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# GM console

The organisers' web app for running a game from a phone, a tablet or a laptop. The field controller serves it; nothing is installed or built (ADR-P2-10: Preact and HTM as plain ES modules, no build step). It talks only to the controller's REST API v1 and its WebSocket stream ([controller/README.md](../README.md#rest-api-v1)).

Status: phase 2, plan phase E. Tested in headless Chromium against the real controller (with the C host modem as its radio, so box traffic arrives as encrypted packets); not yet used at a real field with real boxes (plan phase F).

## Opening it

Start the controller (see [controller/README.md](../README.md#running-it)) and open `http://<controller>:8080/` (it redirects to `/console/`). It asks for an access code:

- the **GM token** can do everything: create and run games, adjust scores, send messages, make join cards;
- the **read token** sees everything live but changes nothing (the GM controls are hidden and the API refuses them anyway).

`python3 -m atalaia_controller tokens` prints both. The code is kept in the browser (localStorage) until you sign out.

On a phone, "Add to home screen" installs it as an app (PWA, display standalone). A service worker keeps the console's own files, so it opens without a connection to the controller; live data needs the connection, and a banner shows while it reconnects (1 s, doubling to 15 s). API answers are never cached.

## Languages

European Portuguese by default, and English; the choice is remembered. The texts are in [`src/i18n/pt.json`](src/i18n/pt.json) and [`src/i18n/en.json`](src/i18n/en.json), with the project page's terms (caixa / box, equipa / team, controlador de campo / field controller, organização). Both files must have the same keys (checked by `controller/tests/test_console.py`); to add a language, copy `en.json`, translate it and add its code to `LANGS` in [`src/ui.js`](src/ui.js).

## What is in it

| Tab | Component | What it does |
| --- | --- | --- |
| Jogo / Game | `components/game-control.js`, `score-panel.js` | Create a game from a mode or a preset (teams, duration, modifiers such as Codes to run alongside the mode, parameters from the schema of the mode and its modifiers, with names and labels in the console's language from the manifests' `i18n`); start, pause, resume and end it, each confirmed in place; a message to every box; a score adjustment; live team totals and a timeline |
| Check-in | `components/checkin-panel.js` | Field check-in for the live game ([protocol/checkin.md](../../protocol/checkin.md), ADR-P3-13): open or close it, the check-ins as they arrive (names here only, for staff), confirm one when the field confirms at the desk, "card seen" for a federation number, team and role (and, only in a game created with squads, the squad inside the team and the squad-leader role, shown as team › squad; the game form's *Squads per team*, 0 by default; decision PE25) (a new token for that player), remove, a check-in by hand for a player without the app, a CSV export; the **replicas to chrono** list with each declared replica's state (the marshals' signed readings fill it in); the field's check-in rules; the poster's addresses, Wi-Fi name and whether it is for this game only, with the CA's short fingerprint; *Print the poster* opens `poster.html`. Starting a game with replicas not chronographed yet asks first, with the count |
| Campo / Field | `components/field-view.js` | The field's own image (a photo, an aerial view or a floor plan, PNG/JPEG/WebP up to 4 MB) with a marker per box showing its owner, battery and link quality; the GM drags markers into place and the controller keeps the positions. Without an image the markers sit on a grid. No map tiles are fetched (OpenStreetMap is left for later, decision E5) |
| Caixas / Boxes | `components/node-list.js` | Every box: name, role, owner (the GM can override it: CMD `set_owner`), tier, battery, RSSI/SNR, last heard, firmware, nonce epoch; boxes not heard for 90 s are flagged |
| Juntar / Join | `components/join-panel.js` | Join data for a box or a standby controller ([protocol/join.md](../../protocol/join.md)): QR code, the `atalaia:join:...` text with a copy button, and the bytes for an NFC card; and, on a second controller, a box to paste such a text and stand by |
| Predefinições / Presets | `components/preset-builder.js` | Forms drawn from each mode's parameters (`int` with min/max, `bool`, `team`, `string` with an optional byte limit, defaults, optional), with modifiers; save and copy presets |
| Registo / Log | `components/live-feed.js` | The game's events as they arrive, filterable, critical ones highlighted, and alerts: radio down, failed transmissions, modem errors, boxes gone quiet, controller role changes, critical events |
| Controlador / Controller | `components/game-control.js` | Role, term, controller in charge, radio and modem state, transmit epoch; promote a standby controller (manual failover, ADR-P2-8) |
| Definições / Settings | `components/radio-settings.js` | The field's radio channel: the current one with its sub-band's limits and why 869.525 MHz is recommended; keep it, find a quiet channel (a noise scan with the USB modem, results quietest first, a suggestion to accept), draw a random one, or pick one from the list; locked while a game exists; a reminder on the game tab until the channel has been chosen once ([controller/README.md](../README.md#the-fields-radio-channel)) |

The commands the console sends to boxes are `POST /api/v1/nodes/{id}/cmd` with `{"cmd": "message", "params": {"text": ...}}` (to node 65535: every box) and `{"cmd": "set_owner", "params": {"team": <name>}}` (an empty `params` clears the owner).

## The check-in poster

[`src/poster.html`](src/poster.html) is the A4 page the field prints once for its check-in area: the field's name, a large QR code with the `atalaia:checkin:` text (error correction M; it holds no secret), the three steps in European Portuguese and English, and the short form of the field CA's fingerprint, which staff can compare with the console's. It opens from the *Check-in* tab with the GM token the console keeps; the browser's *Print* prints the poster without the tools above it. If the field's Wi-Fi has a password, type it there to draw a standard Wi-Fi QR code beside the poster's: the password is used only to draw it, cleared from the form at once, and never stored or sent.

## The scoreboard

[`src/scoreboard.html`](src/scoreboard.html) is a read-only page for a TV or a laptop at the safe zone: the game's name, state and clock (time left when the game has a duration) and each team's score in large type, live over the WebSocket. Open

```
http://<controller>:8080/scoreboard#token=<read token>          (Portuguese)
http://<controller>:8080/scoreboard#token=<read token>&lang=en  (English)
```

The token is in the fragment, so it is not sent in the request or kept in server logs. For a scoreboard of your own over MQTT, see [examples/scoreboard/](../../examples/scoreboard/).

## Files

```
src/
  index.html  app.js  ui.js  style.css      the console (ui.js is shared with the scoreboard)
  scoreboard.html  scoreboard.js  scoreboard.css
  poster.html  poster.js  poster.css        the check-in poster
  components/                               one file per panel
  i18n/pt.json  i18n/en.json                texts
  lib/                                      vendored libraries (see lib/README.md)
  manifest.json  sw.js  icons/              PWA
tests/
  test_browser.py  run.sh                   browser tests (below)
```

Security: the controller serves `/console/` with a Content-Security-Policy that allows only its own scripts, styles and API (`default-src 'self'`, no inline scripts or styles, images also from `blob:` and `data:`), `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. The pages therefore set every style through the DOM, never in markup. The join answers carry the game key; the API sends them with `Cache-Control: no-store`, and the console shows a warning next to them.

## Vendored libraries

| Library | Version | Licence |
| --- | --- | --- |
| Preact | 10.24.3 | MIT |
| HTM | 3.1.1 | Apache-2.0 |
| qrcode-generator | 2.0.4 | MIT |

Copied unmodified from their npm tarballs, checked against the registry; versions and SHA-256 in [`src/lib/README.md`](src/lib/README.md), verified by `controller/tests/test_console.py`. Their licence texts are in [`LICENSES/`](../../LICENSES/) and [`REUSE.toml`](../../REUSE.toml) records them. `preact/hooks` is not used (its bare `preact` import would need an inline import map, which the CSP forbids), so the components are classes.

## Tests

- `controller/tests/test_console.py` (part of `tools/check.sh` and CI's controller job): the static mount and its headers, the redirects, that every file the pages, the scripts' imports, the service worker and the manifest name exists and is served, icon sizes, no inline scripts or styles, both languages with the same keys and placeholders and every `t('...')` key present, the vendored checksums, licence headers, and the `whoami` and field image endpoints.
- `controller/console/tests/test_browser.py`: headless Chromium (Playwright 1.49) against the real controller under uvicorn, with the C host modem as its radio. A GM creates a Domination game in the page, starts it, and the score and the feed update live when a box's encrypted HELLO, capture and STATE reach the modem (no reload); score adjustment and pause from the page; a preset built from the mode's form, a game from it, and the message and `set_owner` commands checked as the CMD packets that go on air; the mode pack: Hold-All and Last Stand listed under their Portuguese names, a Hold-All game created and started from the page (its `field.lua` running on the controller), Domination with the Codes modifier (the game's id, parameters and join payload), and a Bomb preset with Codes; the join QR code read back with `zbarimg` equals the join text and decodes with the field join key; the NDEF bytes; language switch remembered across a reload; a read token sees no GM controls but live data; the scoreboard page follows the score and shows the winner; no sideways scroll at 390 px wide; the field image upload and a marker dragged to a new position; reconnection after the stream drops; the service worker registers, precaches the shell and serves it offline; the field's radio channel: the first-setup reminder, keeping 869.525 MHz, a 25 mW channel picked from the list (the modem retuned, a game and its join payload on it, the settings locked until it ends), a noise scan over the host modem's simulated noise levels whose suggestion is accepted, a random draw, the scan refused without a radio, and the read token seeing no controls. Field check-in: the *Check-in* tab follows a check-in made through the API live (name, pending in staff mode, two declared replicas in the chrono list), confirm, "card seen", a role change and a hand check-in from the page, the start warning with the number of replicas still to chronograph, and a read token that sees no names; the poster page's QR code read back with `zbarimg` equals the controller's poster text and decodes to the field's CA fingerprint, the Wi-Fi code drawn from a typed password (`WIFI:T:WPA;S:...;P:...;;`, the password cleared and absent from the API), no sideways scroll at 390 px and the tools hidden when printed. Every page is checked for JavaScript errors, console errors and failed HTTP requests.

Run the browser tests with Docker from any shell:

```sh
python tools/docker_console.py              # builds tools/dev/console/Dockerfile on first use
python tools/docker_console.py -k scoreboard
```

CI's `console` job runs the same script (`controller/console/tests/run.sh`) in the same image. With `ATALAIA_REQUIRE_BROWSER=1`, as there, a missing Playwright, Chromium or `zbarimg` is an error, never a skip.

Not covered yet: real phones and tablets (only Chromium's phone-sized viewport), installing the PWA, writing an actual NFC card from the console (it shows the bytes; card writing needs a writer app or the box's reader, see protocol/join.md), and use at a real field (plan phase F).
