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

**Why the card is checked, and on what basis** (decisions LEG-1 to LEG-3). The field **must check the physical
membership card at check-in against the data the player typed in advance**. The legal basis is **Art. 6(1)(c) GDPR**
(a legal obligation of the field operator) for fields in Portugal, where airsoft membership of a recognised APD is a
condition of practising the sport, and **Art. 6(1)(f)** (the field's legitimate interest: its insurance and rules)
everywhere else; the notice and the player-facing texts say so in the four languages. Atalaia still **never
verifies** anything with anyone: the check is a person comparing a card with what was typed ([The card
check](#the-card-check)).

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
`rule.register`. When nothing asks, the verdict is null and the data is only shown. **Until the card is checked the
verdict is not stored**: it is worked out when shown, so a changed rule or a new day changes it. **When a marshal or
the GM confirms the card, the verdict as it stood that day is stored** (`apd_verdict` and `apd_verdict_on`, "valid
on 2027-01-15") because the number it was worked out from is erased then ([The card check](#the-card-check)); from
then on `apd_status` is that stored verdict, whatever the rule or the date does later (decision LEG-6, which changes
what this page said before: "the verdict is never stored").

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
| controller `GET /api/v1/games/{id}/chrono-list`, per player | `apd_id`, `membership_number`, `membership_expires`, `apd_override` and `apd_status` (null when no rule asks), as in the staff rows, for the marshal's queue (decision APDF-4); the Pi and the phone controller both send them, held to the `chrono-list: a pending player without replicas...` case of [`vectors/controller_api.json`](vectors/controller_api.json). A player who has **no declared replica** is listed too while their check-in is `pending` (a marshal has to let them in: decision APDF-3), with `pending: 0` and `declarations: []`; the counts stay the replicas' |
| a check-in row (staff views, `GET /api/v1/checkin/me`, chrono-list) after the card check | `federation_seen` true, `card_checked_by` (the marshal's player id, or `"gm"` for the GM token), `card_checked_at` (Unix seconds), `apd_verdict_on` (`YYYY-MM-DD`, the local day of the stored verdict; null until the card is confirmed), `apd_status` (the stored verdict), and `membership_number` / `federation_number` **null** (erased). Before the check these are false / null and the number is there |
| `PATCH /api/v1/games/{id}/checkins/{player}` (staff) | `federation_seen: true`: **card seen, matches** (see below); a body that changes the APD, number or expiry replaces an earlier check |
| `POST /api/v1/games/{id}/checkins` (hand check-in, staff) | optional `federation_seen`: the card was in the marshal's hand |
| registration import and export (CSV or JSON) | the columns `apd_id` and `membership_expires` beside `federation_number` (the membership number), optional: see "The import and the exports" below |

Entries in a check-in's or registration's `apd_id` are not validated against any list (an older build or a
removed entry must not lose a player), only against the id syntax.

## Registering (site server)

When the rule has `register`, a registration without a number, with an APD the list does not accept, or with an
expired membership (`expires < the game's date`, only with `expiry`) is refused with 400 `membership_missing`,
`apd_not_accepted` or `membership_expired`. Without `register` the registration is kept and the verdict shows to
staff and, through the roster, to the marshal. The game's own `federation` rule is unchanged (`required` still
needs a number); `register` with a game whose `federation` is `off` asks for the number anyway.

## Checking in (controller)

With `rule.checkin`, a **self check-in is always recorded as `pending`**, whatever the verdict and even when
`confirm = "auto"` (before decision LEG-1 only a verdict other than `valid` waited): the staff rows show the verdict
and a marshal or the GM checks the card ([The card check](#the-card-check)). The same holds for a registered player
the marshal scans by ticket (the ticket is not the card): `pending`, not `checked_in`. A **marshal's confirmation or
hand check-in is never refused**: without the card, or when the verdict is not `valid`, the controller logs it
(`apd override`: the player id, the **reason** (`no_card` or the verdict) and the verdict, never the number) and keeps
`apd_override: true` on the row. A check-in without a rule behaves as before.

## The card check

The rule's `checkin` makes the card check mandatory (decisions LEG-1 to LEG-11):

1. **Pending until the card is seen.** A self check-in (and a ticket scan) stays `pending` until a marshal or the GM
   ticks **"card seen, matches"**: `PATCH .../checkins/{player}` with `federation_seen: true` (the console and the
   app's marshal queue send it). The tick is the confirmation: the row becomes `checked_in` and `player.checkin` is
   logged as for any confirmation. This holds **even with a valid verdict and `confirm = "auto"`**.
2. **Who and when.** The tick records `card_checked_by` (the marshal's player id, or `"gm"` for the GM token) and
   `card_checked_at`. A staff id is not a membership number; **the number is never put in a log, an audit line, an
   event or a metric** (the log line is `card check: game, player, staff id, verdict`).
3. **The verdict is stored.** `apd_verdict` and `apd_verdict_on` keep the verdict on that day ("valid on
   2027-01-15"; `apd_status` shows it from then on).
4. **The number is erased on the controller.** `membership_number` / `federation_number` become null the moment the
   card check is confirmed. **Kept**, for the normal check-in retention (30 days after the game, `retention_days`): the
   `apd_id`, `membership_expires`, the stored verdict and who checked it. All of them go with the rest of the
   check-in when it is erased (leaving, removal, retention).
5. **An override without the card stays possible.** A marshal may still let a player in without seeing a card
   (PATCH `status: "checked_in"`, the queue's **Let in without the card**, a hand check-in with `federation_seen`
   absent or false): never refused, `apd_override: true`, logged with the reason (`no_card`), no card fields, and the
   number is **not** erased (nobody compared it with anything); it goes with the retention like any check-in.
6. **Correcting data restarts the check.** A PATCH that changes the APD, the number or the expiry clears an earlier
   card check (who, when, the stored verdict) and puts the new data back; tick again. Ticking off a recorded check
   (`federation_seen: false` without new data) is 409. The player's app (`POST /api/v1/checkin` again) and an import
   never put a number back over a recorded card check.
7. **The site server.** It erases its copy of the number (`game_registrations.federation_number`) when the game's
   outcome arrives (`POST /api/v1/sync/checkins`) or the game ends; the `apd_id` and the expiry stay to the same
   30 days as before. The controller's outcome never carried a number.

Without `rule.checkin` nothing here applies: `federation_seen` is the old optional tick and the number stays to the
retention.

## The import and the exports

The registration list the site server and the controllers import ([`vectors/registration_import.json`](vectors/registration_import.json); `import_format.py` and its Dart port) has two more optional columns, **`apd_id`** (the id syntax above, or empty: `apd_id_invalid`) and **`membership_expires`** (`YYYY-MM-DD`, a real date in 2000-2100, or empty: `membership_expires_invalid`), beside `federation_number`, which stays the membership number (decision APDF-1). A file without them imports as before; a column the file lacks is left as it is on an update, and an empty cell clears the value. When the game (or the controller's `federation` setting with no rule asking at check-in) asks for no membership, all three are dropped with a warning (`federation_number_dropped`, `apd_id_dropped`, `membership_expires_dropped`); an import never makes a number required for a rule (the importing side only relaxes `federation: off` to `optional` when the rule asks). The vectors' results carry `apd_id` and `membership_expires`; a case may leave them out (null).

The exports write the same two columns right after `federation_number`: the site server's registration export (`display_name, external_ref, team_preference, federation_number, apd_id, membership_expires, replicas, ...`, so an export imports back) and the check-in CSV of the Pi and of the phone controller, which already had `apd_id`, `membership_expires` and `apd_status` and now also `card_checked_by` and `card_checked_at` (an ISO time) right after `card_seen` (decision LEG-11; the number column is empty once the card was checked, `apd_status` is the stored verdict); their columns are ignored by the import except those two, so the check-in CSV imports back too.

## Personal data

The membership number and expiry are personal data with the same life as the federation number: erased by the same
retention (30 days after the game on the server, the controller's `retention_days`), the same erasure and leaving,
and the same export; never in a log, an audit line or a Prometheus label; never sent back from a controller to the
site server (the outcomes carry none). The APD id goes with them: which association a person belongs to is theirs too.
**The number itself lives shorter** when the rule checks the card: it is erased on the controller when the card check
is confirmed and on the site server when the outcome arrives or the game ends ([The card check](#the-card-check)),
which is the approved minimisation (the number is not kept as evidence; the association, the expiry, the stored
verdict and who checked it are). What stays for the retention: `card_checked_by` (a staff id) and `card_checked_at`.
