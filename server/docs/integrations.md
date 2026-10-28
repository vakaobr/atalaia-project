<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Registration import and platform adapters

For fields that take registrations somewhere else, and for whoever writes an adapter for a platform.
ADR-P4-12 (`docs/phase-4-site-server/ADR.md`), plan phase 17, decisions F20-F23 and S17-* in
`docs/review/decisions-to-review.md`. Built in software and tested against PostgreSQL 16 in Docker; no
real platform has been connected.

## The registration import

A field's `admin` or `gm` (in a TOTP session) imports a list into one scheduled game:

```
POST /api/v1/fields/{field_id}/scheduled-games/{id}/registrations/import?source=<label>&dry_run=true
Content-Type: text/csv            (or application/json)
```

1. **Preview first** with `dry_run=true`: nothing is written, and the answer says what would happen to each row.
2. **Import** with `dry_run=false&basis_confirmed=true`. The field is the data controller for what it imports
   and must have its own basis for having that list (consent, a contract with the players, ...); the server
   asks the staff to say so (`basis_confirmed`), and refuses the import without it (`400 basis_not_confirmed`).

`source` names where the list came from: 1-32 of `a-z 0-9 . _ -`, not `site` (the site's own registrations).
Rows update by **(source, external_ref)**, so importing an updated export again changes the same
registrations instead of adding them twice.

### What is read

| Column | Rule |
| --- | --- |
| `display_name` | required, 1-32 characters, one line |
| `external_ref` | the other platform's registration id, 1-128 characters; recommended (rows without it are added on every import, and the preview warns: `no_external_ref`) |
| `team_preference` | one of the game's teams, or empty |
| `federation_number` | 1-32 characters; required when the game says so (`federation_number_required`), dropped with a warning when the game asks for none (`federation_number_dropped`) |
| `apd_id` | the membership body's id (`[a-z0-9][a-z0-9-]{0,31}`, for example `x-mylabel`) or empty (`apd_id_invalid`); optional, dropped with a warning when the game asks for no membership (`apd_id_dropped`); [protocol/apd.md](../../protocol/apd.md) |
| `membership_expires` | `YYYY-MM-DD`, a real date in 2000-2100, or empty (`membership_expires_invalid`; a JSON integer is refused); optional, dropped as `apd_id` is (`membership_expires_dropped`) |
| `replicas` | CSV: entries separated by `\|`, each `type:class[:make_model]` (`aeg:rifle:Tokyo Marui M4\|sniper:sniper`); JSON: an array of `{"type", "class", "make_model"}`. Types are the check-in's (`aeg`, `gbb`, `hpa`, `bolt_action`, `dmr`, `sniper`, `pistol`, `shotgun`), classes the field's limit template's, at most the field's `max_replicas`, and only when the game takes pre-declared replicas |

**Nothing else is read.** Any other column (an email, a phone number, a birth date) is listed in the
answer's `not_imported_columns` and its values are never stored or logged. Header names are matched without
case or surrounding spaces.

**CSV**: RFC 4180, UTF-8 (a byte order mark is fine; a `charset` other than UTF-8 is refused), a header row,
CRLF or LF line ends, quoted fields with commas, line breaks and doubled quotes. **JSON**: an array of
objects with the same names; `external_ref` and `federation_number` may be JSON integers; `NaN`, a name
twice in one object, or anything but an array is refused.

**Limits**: 1 MiB and 5,000 rows (`413 too_large`, `413 too_many_rows`).

### What happens to each row

| `result` | When |
| --- | --- |
| `created` | a new registration: no account, the import's `source`, a new player id, **no ticket** (the marshal ticks the player by name at the field) |
| `updated` | the same (source, external_ref) is already registered and something differs (`changed` names what); columns the file does not have stay as they are, an empty cell clears the value |
| `unchanged` | the same, nothing differs |
| `skipped` | the field cancelled that registration (`code: cancelled`): an import never brings it back |
| `refused` | with a `code`: `display_name_invalid`, `external_ref_invalid`, `external_ref_twice` (the same reference earlier in the file), `team_preference_invalid`, `federation_number_invalid`, `federation_number_required`, `apd_id_invalid`, `membership_expires_invalid`, `replicas_invalid`, `replica_type_invalid`, `replica_class_invalid`, `too_many_replicas`, `replicas_not_asked`, `make_model_invalid`, `row_length` (a CSV record with more or fewer fields than the header), `row_not_object` (a JSON item), `column_twice`, `game_full` |

A refused row does not stop the others. Warnings: `no_external_ref`, `federation_number_dropped`, `apd_id_dropped`, `membership_expires_dropped`,
`same_name` (someone with that name is already registered: perhaps on the site too). Registrations of the
same source that are not in the file are listed in `missing`, never cancelled.

The whole file is refused (`400` with `detail`, and `line` for CSV) when it is not UTF-8
(`encoding_invalid`), badly quoted (`csv_invalid`), not a JSON array (`json_invalid`), has a column twice
(`column_twice`), no `display_name` column (`display_name_column_missing`) or no rows at all (`empty`).

The game must be published and not started (`409 game_started`, `409 game_cancelled`; drafts are `404`).
The registration window does not apply (this is the field's staff), but `max_players` does: imported
registrations count toward it, go in the controller's roster as expected check-ins and come back with their
outcome after the game, like any other.

### Personal data

Imported registrations belong to no account, so they are in nobody's access or export and nobody can erase
them through the site: the field answers a person's request itself. They are **guests** (ADR-P4-8): the
whole registration, with its replicas, is deleted 30 days after its game by the daily purge. The audit log
records a real import with its source, the counts and the names of the columns not imported, never a value.

### The CSV export

```
GET /api/v1/fields/{field_id}/scheduled-games/{id}/registrations.csv     admin or gm
```

The game's registrations in the import's columns, then `registration_id`, `player_id`, `status`, `source`;
UTF-8 with a byte order mark, CRLF. A cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return is
written with a leading `'`, so a spreadsheet never reads it as a formula (the controller's check-in export
does the same); the import takes that `'` off again, so an export imports back unchanged (the extra columns
are ignored). Every export is in the audit log.

## Platform adapters

An adapter connects one field's site server to one external platform. The interface is
`atalaia_server/integrations/base.py` (`PlatformAdapter`): an `id`, a `name`, `capabilities` (a subset of
`publish`, `update`, `cancel`, `registrations`), the `basis` it works on, its configuration's names
(`config_keys`, with the secret ones in `secret_keys`), `check_config`, and the calls `publish`, `update`,
`cancel` and `fetch_registrations`.

### Rules (F21)

- **Only a documented API or a written agreement.** An adapter uses the platform's published API, or an
  interface the platform has agreed to in writing, and says which in `basis`; the registry refuses an adapter
  without one. No scraping of web pages, no automated form posting, no use of a person's login beyond what
  the platform's API offers. An adapter that does any of these is not accepted.
- **What goes out** is what the public JSON feed already shows (`PublishedGame`): no registrant, no count of
  them beyond the places left. **What comes back** is a list of `ImportedRegistration` with only the
  import's columns, and goes through the import's rules above, preview included.
- **Off by default**, per field: the field's `admin` turns a link on. Its configuration (credentials
  included) is stored encrypted with Fernet under a key derived from `ATALAIA_SECRET_KEY`, sealed together
  with the field and the adapter so it cannot be copied to another field's row; secret values are never shown
  again (the API says only `"set"`). Changing `ATALAIA_SECRET_KEY` makes the stored configurations unreadable:
  enter them again.
- **Every call is in the audit log** (`integration_call`: the adapter, the operation, `ok` or an error code;
  never a credential). Calls go out from the site server only, never from a field controller, and only when
  the staff ask (no call is made by scheduling, publishing, registering or the sync).
- **A failing platform fails only its call**: an error or 20 seconds without an answer gives `502` with the
  code, kept in `external_game_links.last_error`; scheduling, publication, registration and check-in never
  wait for a platform.

### The API

| Method | Path | Who | What |
| --- | --- | --- | --- |
| GET | `/api/v1/integrations/adapters` | any account | the adapters this server offers |
| GET | `/api/v1/fields/{field}/integrations` | admin | the field's links: `enabled`, `configured`, the configuration's non-secret values |
| PUT | `/api/v1/fields/{field}/integrations/{adapter}` | admin | `{"enabled": bool, "config": {...}}`, either or both; turning on needs a configuration (`409 config_missing`) |
| DELETE | `/api/v1/fields/{field}/integrations/{adapter}` | admin | the link and its configuration |
| GET | `/api/v1/fields/{field}/scheduled-games/{id}/integrations` | admin, gm | the game's references on the platforms, the last send and its error |
| POST | `/api/v1/fields/{field}/scheduled-games/{id}/integrations/{adapter}/push` | admin | publishes the game there the first time, updates it after, cancels it once it is cancelled here; drafts never leave the server |
| POST | `/api/v1/fields/{field}/scheduled-games/{id}/integrations/{adapter}/registrations?dry_run=&basis_confirmed=` | admin, gm | the platform's registrations through the import, with `source` the adapter's id |

### What ships

- The interface, the registry with its rules, and the encrypted configuration.
- A **test adapter** (`id` `test`, `integrations/testing.py`): an in-memory stand-in for a platform, with
  no network, so the whole path can be tried and tested. A server offers it only with
  `ATALAIA_TEST_ADAPTER=on`; it is off by default.
- **No adapter for a named platform.** No platform's API documentation or agreement is known to the
  project. **jogarairsoft.pt**: no public information or API was found (web search, 2026-10-19), so nothing
  about it is designed or assumed (F22); a field that uses it can link the iCalendar and JSON feeds
  ([feeds.md](feeds.md)) where the platform allows, and import a registration list if the platform lets it
  export one. Nothing is scraped.

### Writing an adapter

Implement `PlatformAdapter` in a module of its own under `atalaia_server/integrations/`, with the platform's
API documentation or agreement named in `basis`, register it in `default_registry`, and add tests against a
stand-in of that API (never the real platform in CI). Use the platform's own API client rules (rate limits,
authentication) and nothing more than its documented calls.
