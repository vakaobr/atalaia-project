<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Atalaia community modes

Game modes for [Atalaia](https://github.com/vakaobr/atalaia-project), the open
airsoft and milsim game system, shared by the people who wrote them. Each mode
is a signed package; modes the project has reviewed carry the **verified**
badge, and only those reach Field Boxes.

## Using these modes on a field

Point your field controller at this registry's index, in `controller.toml`:

```toml
[modes]
index = "https://<owner>.github.io/atalaia-modes/index.json"
keys = ["<the project's registry key, from keys.json>"]
```

With only the project's key, the controller offers verified modes only. Add an
author's key (also in the published `keys.json`) to install that author's modes
that are not reviewed yet; the GM console marks them *not reviewed by the
project*. A field without internet copies the published folder to a USB stick
and sets `index` to the path of its `index.json`.

## Sharing a mode

Read [Submitting a community mode](https://github.com/vakaobr/atalaia-project/blob/main/CONTRIBUTING.md#submitting-a-community-mode)
and [CONTRIBUTING.md](CONTRIBUTING.md). In short: build the mode in the visual
editor (or by hand), write its tests, make your mode key, then open a pull
request adding `modes/<id>/`, its signed package in `packages/` and its line in
`index.json`. The CI checks it; a maintainer reviews it.

## What is here

| Path | What |
| --- | --- |
| `index.json` | Every version of every mode: its archive, signature, licence and whether it is verified |
| `keys/` | Authors' and the project's public mode keys, and the revoked ones ([keys/README.md](keys/README.md)) |
| `modes/<id>/` | The source of each mode's newest version, with its tests |
| `packages/` | The signed archives, the authors' and the project's signatures |
| `.github/workflows/registry.yml` | The checks every pull request must pass, and publishing |

How it all works, the review checklist, keys and moderation:
[docs/community/](https://github.com/vakaobr/atalaia-project/tree/main/docs/community)
in the Atalaia repository.

## Licences

Each mode has its own licence, one of the approved seven (`GPL-3.0-or-later`,
`LGPL-3.0-or-later`, `MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`,
`CC0-1.0`), named in its `mode.yaml` and in every file. The registry's data
(`index.json`, `keys/`, the signature files) is `CC0-1.0`; its documents are
`CC-BY-SA-4.0`; its workflow is `GPL-3.0-or-later`. See `REUSE.toml`.
