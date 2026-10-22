<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Contributing a mode

The full guide is [Submitting a community mode](https://github.com/vakaobr/atalaia-project/blob/main/CONTRIBUTING.md#submitting-a-community-mode)
in the Atalaia repository. The commands below run from a checkout of Atalaia
(its dev container has everything), with this repository next to it in
`../atalaia-modes`.

1. **The mode.** Put its folder in `modes/<id>/`: `mode.yaml`, `node.lua`,
   `field.lua` if it has one, `assets/`, and `tests/` with at least one test.
   Every file starts with SPDX lines naming you and the licence in `mode.yaml`.
   Check it: `python3 -m atalaia_sim test ../atalaia-modes/modes/<id>`.
2. **Your key** (once): `python3 tools/mode_package.py keygen --out ~/atalaia-keys/modes.pem`,
   then `python3 tools/registry_check.py key ../atalaia-modes --public <base64> --owner <your GitHub handle>`.
3. **The package**: `python3 tools/registry_check.py add ../atalaia-modes <id> --key ~/atalaia-keys/modes.pem --name "..." --description "..." --author "..."`.
   It packs `modes/<id>`, signs it, writes `packages/` and adds the version to
   `index.json`, not reviewed.
4. **Check**: `python3 tools/registry_check.py lint ../atalaia-modes`.
5. **Pull request**, every commit signed off (`git commit -s`), filling in the
   template. A maintainer reviews it against the checklist; the verified badge
   is a second step that a maintainer takes with the project's key.

A new version: change the source, raise `version` in `mode.yaml`, run `add`
again. A published version never changes.

Everyone taking part follows the Atalaia [Code of Conduct](https://github.com/vakaobr/atalaia-project/blob/main/CODE_OF_CONDUCT.md).
