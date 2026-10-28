<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->
# Association membership, historically "APD" (decisions APD-1 to APD-14, MEM-1 to MEM-6)

In Portugal an airsoft player must belong to an **APD** (Associação Promotora de Desporto) recognised for
airsoft and holds a membership number with an expiry. Players elsewhere may need a membership too (a club, a
federation, an insurance body), just not an "APD": since package H (decision MEM-1) this is **association
membership** in general, and a field says which country it is in. Atalaia does **not** keep a national directory
of associations, teams, fields or events and **never verifies** a membership: the player declares it, the field's
rule says what it needs, and the marshal sees a verdict and decides. Everything here is additive: a peer that
knows nothing of it keeps working, and `federation_number` stays.

**The names are historical.** The wire names (`apd_id`, `apd`, `apd_status`, `settings.apd`, `apds`), the error and
verdict codes (`apd_rule_invalid`, `apd_not_accepted`, ...), the files (`apds.json`, `vectors/apd.json`) and this
page keep "apd" so that nothing breaks; read "APD" in them as "the membership body" (the association, club or
federation). Only what a person reads changes with the country (below).

Vectors: [`vectors/apd.json`](vectors/apd.json), run by the server, the Pi controller, the phone controller and the app; the sync bodies that carry a rule (`settings.apd` of the field answer, the roster's `apd`) are in [`vectors/sync.json`](vectors/sync.json) (`answers`, `field_settings_*apd*` and `roster_*apd*`; error `bad_apd_rule`).

## The field's country and the wording

A field has a **country**: an ISO 3166-1 alpha-2 code in capitals (`PT`, `ES`, ...) or none. It is a setting of
the field, not a part of the rule: the site server's `country` (field settings, `PATCH /api/v1/fields/{field}`
`{"country": "ES"}`; null or `""` unsets it; anything else than two capitals, after upper-casing what the admin
typed, is 400 `country_invalid`), and on a controller `[checkin] country`, the console's field and the phone
controller's `country` check-in setting (`PUT /api/v1/checkin/settings`). Vectors: `country_valid`,
`country_invalid` and `default_country` in [`vectors/apd.json`](vectors/apd.json).

**Default** (decision MEM-2): `PT` where the field's time zone is `Europe/Lisbon`, `Atlantic/Azores` or
`Atlantic/Madeira`, otherwise unset. The site server applies it to a new field and, in migration
`0019_field_country`, to the existing ones; after that the admin's choice stands (an unset country stays unset). A
controller without a site server works it out from its own time zone while no country is configured or saved (an
empty `[checkin] country`, or the console's field left empty, means "the default"); the phone controller only
knows the abbreviation Android gives for its zone (WET and WEST count as Lisbon, AZOT and AZOST as the Azores).

**Wording** (decision MEM-4, `wording` in the vectors): a field whose country is `PT` keeps the APD texts ("APD",
"Filiação numa APD", ...). Any other country, or none, says **"association membership"** / "membership number" in
the same screens, in the four languages (pt-PT gender-neutral: "filiação numa associação"; "filiação" stays right
for pt). The screens are the app's registration, check-in and marshal views, the GM console, the phone controller's
console, the site server's staff pages and the public game page. Each client works the words out from the country
the field's answer carries; a peer from before this page, whose answer has no `country` key at all, was only ever
used in Portugal, so a **client treats an absent key as `PT`** (a `null` is "unset": association wording). The verdict
codes are not words and are never changed.

## The list

[`registry/apds/apds.json`](../registry/apds/apds.json) (the file and its schema keep their historical names,
decision MEM-1): `{"format": 1, "apds": [entry...]}`, copied byte for byte
to the server, the Pi controller and the app (`server/atalaia_server/data/apds.json`,
`controller/atalaia_controller/data/apds.json`, `app/assets/apds.json`; a test in each component and in
`registry/tests/test_apds.py` fails when they differ). An **entry** is `{id, country, name, short_name, website}`
(the file also has `source`, which no API carries):

| Field | Values |
| --- | --- |
| `id` | `[a-z0-9][a-z0-9-]{0,31}`; never changes. `x-` is reserved for a field's own entries |
| `country` | the ISO 3166-1 alpha-2 code, in capitals, of the country whose fields offer the entry (the three shipped ones are `PT`). A field's own entry has none |
| `name` | 1-96 characters, no control characters |
| `short_name` | 1-16 characters |
| `website` | `https://` URL of at most 128 characters, or null |

The shipped list may be empty (no entry without an official public source). A **field's own entry** has the same
fields but no `country`, and an id starting `x-`; it lives in the field's rule (`custom`) and is sent wherever the
rule goes. **Which list a field offers** (decision MEM-3, `choices` in the vectors): the shipped entries whose
`country` is the field's, then the field's own entries; a field with no country offers only its own. Wherever an API
shows a list of choices it is that list. The accepted-list rule (`accepted`, below) is unchanged by the country:
it names ids, and an id this build's list lacks is still only syntax-checked.

## The rule

An object (the field's, a controller's), always normalised to all five keys:

| Key | Values |
| --- | --- |
| `accepted` | null (any body) or a list of 1-32 distinct ids (the project's, the field's own, or an id this build's list lacks: only the syntax is checked) |
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
| site server: the field's country | `country` in the field's JSON (`GET /api/v1/fields`, `PATCH` answer), in `GET /api/v1/fields-by-slug/{slug}`'s `field` (with `apds`: the shipped entries of that country, to which the client adds `apd.custom`), in the staff's registration list (`country`, `apds`) and in `GET /api/v1/sync/field?settings=1` as `settings.country` (a code or null, additive: absent from an older site server, whose controller then keeps its own). `GET /api/v1/apds` stays the whole list, every country's entries (each has its `country`), or one country's with `?country=ES` (400 `country_invalid`). A change through `PATCH` sends the same `field.changed` note as the other settings |
| site server: the field's rule | `apd` (the rule): set by the field's admin with `PATCH /api/v1/fields/{field}` (`{"apd": {...}}`, a whole rule; `{}` puts the default back; 400 `apd_rule_invalid`), shown in the field's JSON, in `GET /api/v1/fields-by-slug/{slug}`'s `field`, in the staff's registration list (with `apds`, the project list) and in `GET /api/v1/sync/field?settings=1` as `settings.apd` (BR24's check-in settings: only for a request with the query, so the answer without it is unchanged; always sent there, the default rule when none is set). A change through `PATCH` sends the same `field.changed` note on the stream as the other settings |
| `GET /api/v1/sync/roster` | optional top-level `apd` (the rule); a registration may carry `apd_id` and `membership_expires` beside `federation_number`, when the game asks for the federation number or the rule has `checkin` or `register` |
| `GET /api/v1/apds` (site server, no token, cacheable) | `{"format": 1, "apds": [entry...]}` the project list |
| controller with `[sync] branding = "site"` | takes `settings.apd` as its rule with the other check-in settings (no separate switch: decision APD-50); the console's `PUT` of `apd` is then 409 once the site has sent a rule; an older site server sends none and the local rule stays |
| controller `GET /api/v1/checkin` | `settings.apd` (the rule), `settings.country` and `apds` (the choices: the country's entries, then `custom`) |
| controller `PUT /api/v1/checkin/settings` | `apd` (a whole rule, replaces) and `country` (two letters, any case; `""` or null: the configured or default one; 400 for anything else; 409 once the site has sent its country with `[sync] branding = "site"`, as for the rule) |
| controller staff rows, `GET /api/v1/checkin/me` and `GET /api/v1/games/{id}/chrono-list` | `country` (the field's, for the words of the verdict) beside `apd_status` |

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
