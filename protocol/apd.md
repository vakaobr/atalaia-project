<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->
# APD membership (decisions APD-1 to APD-14)

In Portugal an airsoft player must belong to an **APD** (Associação Promotora de Desporto) recognised for
airsoft and holds a membership number with an expiry. Atalaia does **not** keep a national directory of APDs,
teams, fields or events and **never verifies** a membership: the player declares it, the field's rule says what
it needs, and the marshal sees a verdict and decides. Everything here is additive: a peer that knows nothing of
it keeps working, and `federation_number` stays.

Vectors: [`vectors/apd.json`](vectors/apd.json), run by the server, the Pi controller, the phone controller and the app.

## The list

[`registry/apds/apds.json`](../registry/apds/apds.json): `{"format": 1, "apds": [entry...]}`, copied byte for byte
to the server, the Pi controller and the app (`server/atalaia_server/data/apds.json`,
`controller/atalaia_controller/data/apds.json`, `app/assets/apds.json`; a test in each component and in
`registry/tests/test_apds.py` fails when they differ). An **entry** is `{id, name, short_name, website}` (the file
also has `source`, which no API carries):

| Field | Values |
| --- | --- |
| `id` | `[a-z0-9][a-z0-9-]{0,31}`; never changes. `x-` is reserved for a field's own entries |
| `name` | 1-96 characters, no control characters |
| `short_name` | 1-16 characters |
| `website` | `https://` URL of at most 128 characters, or null |

The shipped list may be empty (no entry without an official public source). A **field's own entry** has the same
fields and an id starting `x-`; it lives in the field's rule (`custom`) and is sent wherever the rule goes.
Wherever an API shows a list of choices it is `project list + rule.custom`, the project's first.

## The rule

An object (the field's, a controller's), always normalised to all five keys:

| Key | Values |
| --- | --- |
| `accepted` | null (any APD) or a list of 1-32 distinct ids (the project's, the field's own, or an id this build's list lacks: only the syntax is checked) |
| `register` | bool: membership (an accepted, unexpired one if `expiry`) is needed to **register** (site server only; a controller keeps it and ignores it) |
| `checkin` | bool: membership is checked at **check-in** |
| `expiry` | bool: the expiry date is required and checked |
| `custom` | 0-16 own entries, each id once |

The default is `{"accepted": null, "register": false, "checkin": false, "expiry": false, "custom": []}`. A missing
or null rule is the default; a missing key takes its default; any other key, a wrong type or a bad value is
`apd_rule_invalid` (`vectors/apd.json`, `rule_valid` and `rule_invalid`).

## The membership

`{apd, number, expires}` (wire names below): `apd` an id or null (**null is "APD unknown"**, what a legacy
`federation_number` becomes), `number` 1-32 printable characters (never verified) or null, `expires`
`YYYY-MM-DD` (a real date, 2000-2100) or null. Anything else is `apd_membership_invalid`.

## The verdict

`status(rule, membership, on)` with `on` the local date the player plays (the scheduled game's date in the field's
time zone; today's local date at check-in), the first that applies:

1. `missing`: no number; or `rule.expiry` and no expiry
2. `not_accepted`: `rule.accepted` is a list and `apd` is null or not in it
3. `expired`: `rule.expiry` and `expires < on` (an expiry on the day itself is valid)
4. `valid`

The verdict is computed only where a rule asks: at check-in when `rule.checkin`, at registration when
`rule.register`. When nothing asks, the verdict is null and the data is only shown. The verdict is never stored: it is
worked out when shown, so a changed rule or a new day changes it.

## Wire names

| Place | Keys |
| --- | --- |
| a registration or a check-in body (player to server or controller) | `apd_id`, `membership_number`, `membership_expires`; the old `federation_number` is the same value as `membership_number` (both sent: they must agree, else 400; either alone is accepted) |
| a registration or check-in row (staff views, roster, exports) | `apd_id`, `membership_expires`, `membership_number` **and** `federation_number` (same value), and `apd_status` (null when no rule asks) |
| site server: the field's rule | `apd` (the rule) in the field's settings (`apd_rule` in `PUT /api/v1/fields/{field}`), in the public game's `field` object, and in `GET /api/v1/sync/field` as `field.apd` |
| `GET /api/v1/sync/roster` | optional top-level `apd` (the rule); a registration may carry `apd_id` and `membership_expires` beside `federation_number`, when the game asks for the federation number or the rule has `checkin` or `register` |
| `GET /api/v1/apds` (site server, no token) | `{"format": 1, "apds": [entry...]}` the project list |
| controller `GET /api/v1/checkin` | `settings.apd` (the rule) and `apds` (the choices: the project's, then `custom`) |
| controller `PUT /api/v1/checkin/settings` | `apd` (a whole rule, replaces) |

Entries in a check-in's or registration's `apd_id` are not validated against any list (an older build or a
removed entry must not lose a player), only against the id syntax.

## Registering (site server)

When the rule has `register`, a registration without a number, with an APD the list does not accept, or with an
expired membership (`expires < the game's date`, only with `expiry`) is refused with 400 `membership_missing`,
`apd_not_accepted` or `membership_expired`. Without `register` the registration is kept and the verdict shows to
staff and, through the roster, to the marshal. The game's own `federation` rule is unchanged (`required` still
needs a number); `register` with a game whose `federation` is `off` asks for the number anyway.

## Checking in (controller)

With `rule.checkin`, a **self check-in** whose verdict is not `valid` is recorded as `pending` even when
`confirm = "auto"`, and the staff rows show the verdict: a marshal confirms it (PATCH `status: "checked_in"`) as
they do any pending check-in. A **marshal's confirmation or hand check-in is never refused** because of the
verdict: when it is not `valid` the controller logs it (`apd override`: the player id and the verdict, no number)
and keeps `apd_override: true` on the row. A check-in without a rule behaves as before.

## Personal data

The membership number and expiry are personal data with the same life as the federation number: erased by the same
retention (30 days after the game on the server, the controller's `retention_days`), the same erasure and leaving,
and the same export; never in a log, an audit line or a Prometheus label; never sent back from a controller to the
site server (the outcomes carry none). The APD id goes with them: which association a person belongs to is theirs too.
