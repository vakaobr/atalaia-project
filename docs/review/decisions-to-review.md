

## Association membership for any country (MEM-1 to MEM-6, 2026-10-28)

The maintainer asked whether the APD check should apply outside Portugal and chose (2026-10-28) a general association membership: the field's country picks the words and the list; APD wording and the Portuguese list only for fields in Portugal; the rule stays off by default. Not done: a staff page for the field's settings (the country is set through the API, like the rule).

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| MEM-1 | What do the list file, schema and wire names become? | They keep their "apd" names (`apds.json`, `apd_id`, `settings.apd`, codes), documented as historical; each list entry gets a required `country` (ISO 3166-1 alpha-2); a field's own entries have none. | A rename would break peers and files for no gain. | built (2026-10-28); open for the maintainer's review |
| MEM-2 | Where does the field's country live and what is its default? | A field setting, not part of the rule: nullable `fields.country` on the site server; `[checkin] country` / console / phone setting on controllers. Default PT for Europe/Lisbon, Atlantic/Azores, Atlantic/Madeira, otherwise unset (migration sets existing fields; controllers derive it from their time zone until set). | The rule's shape and vectors stay untouched; PT fields lose nothing. | built (2026-10-28); open for the maintainer's review |
| MEM-3 | Which list does a field offer? | The shipped entries of its country, then its own custom entries; no country, only its own. Accepted-list rule unchanged. | The country only filters choices; no verdict changes. | confirmed by the maintainer (2026-10-28) |
| MEM-4 | How is the wording chosen? | PT shows the existing "APD" texts; any other or no country shows "association membership" / "membership number" (four languages), as twin `_m` keys chosen from the country. | Words change, codes do not. | confirmed by the maintainer (2026-10-28) |
| MEM-5 | Older peers and the list endpoint? | `settings.country` optional and additive; an answer with no `country` key means PT (older peers only knew Portugal), an explicit null means unset; `GET /apds` returns every country, `?country=` filters. | Existing deployments keep their wording; nothing is refused. | built (2026-10-28); open for the maintainer's review |
| MEM-6 | How do the verdict screens know the country? | Staff rows, `/checkin/me` and chrono-list carry `country` beside `apd_status`. | Those screens have no field info of their own. | built (2026-10-28); open for the maintainer's review |
