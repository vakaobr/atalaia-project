<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->
# Mode registry

The files of the community mode registry that live in this repository until the
maintainer creates `atalaia-modes` (ADR-P5-3, decision P5R-9).

| Path | What |
|------|------|
| [`schema/index.schema.json`](schema/index.schema.json) | JSON Schema of a registry index: each mode's signed versions, where to fetch them, their licence and whether the project reviewed them (the verified badge) |
| [`schema/revoked.schema.json`](schema/revoked.schema.json) | JSON Schema of the list of revoked mode keys |
| [`schema/examples/`](schema/examples/) | A valid index and revocation list (the shared vectors' own) and invalid ones; CI's protocol job checks them with `check-jsonschema` |

The package format, the signed manifest and the checks are
[protocol/mode-packages.md](../protocol/mode-packages.md). The tools:
`tools/mode_package.py` (`pack`, `keygen`, `sign`, `verify`, `index`). A field
controller imports signed packages from an index with its own trusted mode keys
(plan phase 6, `controller/README.md`, "Signed mode packages").

Still to come (`docs/phase-5-community/PLAN.md`): the registry repository's
template with its CI (plan phase 8) and the submission process (plan phase 9).
