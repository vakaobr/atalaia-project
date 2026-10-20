<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# A field's public page and feeds

A field that runs a site server can publish its games on a public page and in two open
feeds that any calendar app, club website or platform can read with no agreement and no
account (ADR-P4-11, ADR-P4-12; plan phase 15). Everything here is off until the field's
`admin` turns it on:

```sh
curl -X PATCH https://<site>/api/v1/fields/<field_id> -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"public_page": true, "description": "...", "address_text": "...", "federation_label": "FPA"}'
```

| Address | What |
| --- | --- |
| `/f/<slug>/` | The field page: name, description, address and the upcoming games (pt-PT or English) |
| `/f/<slug>/games/<id>` | One game: when (in the field's time zone), where, mode, teams, places, registration window, federation requirement; schema.org `Event` JSON-LD; a *Register* button only while registration is open and places are left |
| `/f/<slug>/games/<id>/register` | How to register: with an account on the site, in the Atalaia app (plan phase 16) |
| `/f/<slug>/games.ics` | iCalendar of the field's games |
| `/f/<slug>/games/<id>.ics` | iCalendar of one game |
| `/f/<slug>/games.json` | The JSON feed, `atalaia.games` version 1 |

A field with its page off, an unknown slug, a draft or another field's game all answer
404, the same as a page that never existed. Every address answers `HEAD` too, with the
headers a `GET` would have (`ETag`, `Last-Modified`, `Content-Length`) and no body, and a
conditional `HEAD` or `GET` gets `304` when nothing changed.

**No personal data.** The pages and feeds never show who registered, how many did, or any
account: only the places left. Drafts never appear.

**Which games.** The field page lists the games that have not ended, cancelled ones
marked as such with their reason. The feeds hold every published game that has not ended or
ended less than 30 days ago, cancelled ones included (`STATUS:CANCELLED`), so a calendar
keeps a just-played or just-cancelled game for a while.

**Links and the site's address.** Links, game URLs and iCalendar UIDs use
`ATALAIA_PUBLIC_URL` (for example `https://campo.example.pt`). Set it on a real deployment:
a calendar knows a game by its UID, and without the setting the UID follows whatever
address the request used.

**Polling.** Every answer has an `ETag` and a `Last-Modified`; send `If-None-Match` (or
`If-Modified-Since`) and an unchanged feed answers `304 Not Modified` with no body. The feeds
say `Cache-Control: public, max-age=300` and `Access-Control-Allow-Origin: *` (read-only, no
cookies), so a club's own website can read them from the browser. The site server's
per-address limit (100 requests a minute) covers the pages and feeds too.

## Language

The pages are in European Portuguese or English: `?lang=pt` or `?lang=en` in the address,
otherwise the reader's `Accept-Language`, otherwise Portuguese. The feeds carry the texts as
the field wrote them.

## iCalendar

RFC 5545, one `VCALENDAR` per answer:

```text
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Atalaia//Site server//EN
NAME:Campo Tejo
X-WR-CALNAME:Campo Tejo
BEGIN:VEVENT
UID:0192f6a0-0000-7000-8000-000000000001@campo.example.pt
DTSTAMP:20261020T103015Z
DTSTART:20261108T090000Z
DTEND:20261108T130000Z
SUMMARY:Domingo no bosque
DESCRIPTION:Jogo de domínio.\n\nhttps://campo.example.pt/f/campo-tejo/game
 s/0192f6a0-0000-7000-8000-000000000001
LOCATION:Estrada da Mata\, Lisboa
URL:https://campo.example.pt/f/campo-tejo/games/0192f6a0-0000-7000-8000-000
 000000001
STATUS:CONFIRMED
SEQUENCE:0
LAST-MODIFIED:20261020T103015Z
END:VEVENT
END:VCALENDAR
```

- Times are UTC (`...Z`), so no `VTIMEZONE` is needed; calendar apps show them in the
  reader's own zone.
- `UID` is the scheduled game's id `@` the site's host name and is never reused.
- `DTSTAMP` and `LAST-MODIFIED` are when the game was last changed (with no `METHOD`
  property, RFC 5545 section 3.8.7.2), so an unchanged game gives the same bytes.
- `SEQUENCE` goes up by one when a published game's start, end or place changes, when it is
  cancelled, and when the field's address changes for a game that shows it; calendars that
  subscribed then update the event. A new title or description does not raise it.
- `DESCRIPTION` is the game's description, the reason when it was cancelled, and the game
  page's address. `LOCATION` is the game's own place, else the field's address.
- Lines end in CRLF and are folded at 75 octets (never inside a UTF-8 character); text
  escapes `\`, `;`, `,` and line breaks.

## JSON feed

`server/schemas/games-feed-v1.schema.json` is the format (JSON Schema 2020-12):

```json
{
  "format": "atalaia.games",
  "version": 1,
  "field": {"slug": "campo-tejo", "name": "Campo Tejo", "timezone": "Europe/Lisbon",
            "url": "https://campo.example.pt/f/campo-tejo/", "description": "...", "address": "Estrada da Mata, Lisboa"},
  "games": [
    {
      "id": "0192f6a0-0000-7000-8000-000000000001", "title": "Domingo no bosque", "description": "...",
      "starts_at": "2026-11-08T09:00:00Z", "ends_at": "2026-11-08T13:00:00Z",
      "status": "published", "cancelled_reason": null, "mode": "org.atalaia.domination",
      "teams": ["red", "blue"], "location": "Estrada da Mata, Lisboa",
      "registration": {"opens_at": "2026-10-25T09:00:00Z", "closes_at": "2026-11-07T20:00:00Z",
                       "open": true, "max_players": 60, "places_left": 48},
      "requirements": {"federation": "required", "federation_label": "FPA"},
      "url": "https://campo.example.pt/f/campo-tejo/games/0192f6a0-0000-7000-8000-000000000001",
      "ics": "https://campo.example.pt/f/campo-tejo/games/0192f6a0-0000-7000-8000-000000000001.ics",
      "updated_at": "2026-10-20T10:30:15Z"
    }
  ]
}
```

| Member | Meaning |
| --- | --- |
| `starts_at`, `ends_at`, `updated_at`, `registration.opens_at`, `closes_at` | RFC 3339 in UTC, to the second; `field.timezone` (IANA) is the field's local time for showing them |
| `status` | `published`, `in_progress`, `completed` or `cancelled` (with `cancelled_reason`); never `draft` |
| `mode` | The Atalaia mode id, or `null` while the GM has not chosen one |
| `registration.open` | Whether a player can register on the site server now: the window is open and places are left (from plan phase 16; before it, always `false`) |
| `registration.max_players`, `places_left` | `null` with no limit; `places_left` never counts below 0 |
| `requirements.federation` | `off`, `optional` or `required`: the player's federation number (the field's `federation_label`, e.g. FPA), checked by hand at the field, never automatically |

Version 1 may gain optional members; a reader ignores members it does not know. Anything
that a version 1 reader could misread gets a new `version` and a new address.

## Scheduling (staff)

The games come from `POST /api/v1/fields/<field_id>/scheduled-games` (the field's `admin`
or `gm`, in a TOTP session): a draft, seen by staff only; then `.../publish` (the `admin`)
puts it on the page and in the feeds, `PATCH` edits it, `.../cancel` with a reason (the
`admin`) keeps it visible as cancelled, and `DELETE` removes a draft (a published game is
cancelled instead, since it may already be on someone's calendar). See
[`../README.md`](../README.md) for the full API.
