

## A staff page for the field's settings (FS-1 to FS-6, 2026-10-28)

The maintainer asked for it (2026-10-28): the field's settings (public page, check-in rules, membership with its country, chrono sharing) were reachable only through `PATCH /api/v1/fields/{id}`.

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| FS-1 | Where does the page live and who sees it? | `/staff/fields/<field>/settings`, admin only, in the field's sections and the `/staff/` list; the API still decides. | Same as the other FU9 pages. | built (2026-10-28); open for the maintainer's review |
| FS-2 | One form or one per section? | One form per section; each PATCH sends only its own members. | A refused section never blocks or half-saves another. | built (2026-10-28); open for the maintainer's review |
| FS-3 | When does the membership wording change with the country? | When a new country is saved; the draft membership rule is kept and redrawn with the new words and list. | The saved country is the field's; the draft must not be lost. | built (2026-10-28); open for the maintainer's review |
| FS-4 | How are the APD / association words switched? | The existing `_m` twins plus a reversible `membershipWording` that also restores the APD words for PT. | The page changes country in place. | built (2026-10-28); open for the maintainer's review |
| FS-5 | Refusals | One `e_<code>` text per code the PATCH or `/apds` can raise, plus `e_http_422`; a test reads the codes from the API source. | New codes cannot appear without words. | built (2026-10-28); open for the maintainer's review |
| FS-6 | The controllers' notice | A note on the page, and "the controllers get it at once" after check-in rules, membership and country; public page and chrono say only "Saved." | Matches what the API announces (`field.changed`). | built (2026-10-28); open for the maintainer's review |
