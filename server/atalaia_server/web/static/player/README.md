<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# The web registration page's files

`register.js` and `player.css` are the project's (`player_pages.py`, decisions WREG-*). `qrcode.module.js` draws the
check-in ticket's QR code in the browser, so the ticket's secret never goes back to the server to be drawn. It is a
byte-for-byte copy of the GM console's vendored generator, `controller/console/src/lib/qrcode.module.js`, whose
README has the npm tarball it was checked against:

| File | Package | From the tarball | Licence | SHA-256 |
| --- | --- | --- | --- | --- |
| `qrcode.module.js` | qrcode-generator 2.0.4 | `dist/qrcode.mjs` (renamed: `.js` is served as JavaScript everywhere) | MIT, © 2009 Kazuhiko Arase | `ea91d7118a5395289170da848b7c6758b996163bfbccf312591ab65a4911b7c0` |

The server serves only the three names listed in `player_pages.STATIC_TYPES`; this README is not served. A test
(`tests/test_web_registration.py`) checks that the two copies stay the same.
