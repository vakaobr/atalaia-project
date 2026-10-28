<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->
# APDs recognised for airsoft

[`apds.json`](apds.json) lists the APDs (Associações Promotoras de Desporto) a Portuguese airsoft player
may belong to, so a field can say which ones it accepts and a player can pick theirs when registering or
checking in ([protocol/apd.md](../../protocol/apd.md)). Its format is [`../schema/apds.schema.json`](../schema/apds.schema.json).

**There is no national directory here and no verification of a member.** The list only names the associations;
the membership number and its expiry are what the player declares and the marshal checks against the card.

## Status of the list

Started on 2026-10-28 from the associations that jogarairsoft.pt names as partners (ALA, ADAPT, APAP, APACORP;
decision APD-1). An entry is kept only where the association's own site confirms it (`source`). Left out for
now, until its own official page can be read: **ADAPT** (Associação Desportiva de Airsoft Português; its site
answered 503 when checked) and **T13** (nothing found). **APAP**'s own site shows only "APAP-APD" and says it is
"Reconhecida no IPDJ"; its full name is in the statutes PDF it links, which has no text layer, so the entry
carries the name as the site writes it until someone supplies the full one by pull request. ALA's and APACORP's
sites show the APD designation; neither states a recognition in words (ALA shows the IPDJ's logo).
A field is never blocked by a missing entry: it adds its own (site server field settings, or the controller's
console; their ids start with `x-`).

## Adding an APD by pull request

Add one object to `apds`, in alphabetical order of `id`:

```json
{
  "id": "example-apd",
  "name": "Associação Exemplo de Airsoft, APD",
  "short_name": "Exemplo",
  "website": "https://example.pt",
  "source": "https://example.pt/estatutos"
}
```

- `id`: 1-32 characters `a-z 0-9 -`, starting with a letter or digit; it never changes once published
  (registrations keep it). An id starting with `x-` is reserved for a field's own entries.
- `name` (1-96 characters, as the association writes it), `short_name` (1-16 characters, what players say),
  `website` (`https://`, or `null` when it has none).
- `source`: the page that shows the association exists and is recognised for airsoft: its own site or a public
  register (for instance the IPDJ's). A business-register listing alone does not show recognition. Say in the
  pull request where on the page to look.
- Then copy the file to the places that ship it, byte for byte (`registry/tests/test_apds.py` and the components'
  tests fail when they differ):

  ```sh
  cp registry/apds/apds.json server/atalaia_server/data/apds.json
  cp registry/apds/apds.json controller/atalaia_controller/data/apds.json
  cp registry/apds/apds.json app/assets/apds.json
  ```

An entry is removed only when the association stops existing; a registration that names it keeps the id and
shows it as unknown.
