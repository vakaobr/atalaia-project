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
| [`template/`](template/) | The `atalaia-modes` repository's files, from which the maintainer creates it: an empty `index.json`, `keys/` with `revoked.json`, `modes/`, `REUSE.toml`, the CI workflow (`registry-lint`, `registry-test`, `sandbox-escape`, then publishing to GitHub Pages), CODEOWNERS, the pull request and issue templates (plan phase 8) |
| [`examples/org.example.hill/`](examples/org.example.hill/) | A sample community submission (MIT) and the template authors copy: King of the Hill, its script, its own screens (`assets/screens/`: the free hill, the owner in its colour with its points, a bar while a team holds, the final score; Portuguese, English, German and Traditional Chinese), the LED ring and a sound when the box has them, and three tests |
| [`tests/`](tests/) | Runs the template workflow's checks on the sample, signed with throwaway keys made at run time, and the refusals (`tools/check.sh`, CI job `registry-template`) |

The package format, the signed manifest and the checks are
[protocol/mode-packages.md](../protocol/mode-packages.md). The tools:
`tools/mode_package.py` (`pack`, `keygen`, `sign`, `verify`, `index`) and
`tools/registry_check.py` (a registry's `lint`, `test`, `key`, `add`, `badge`,
`site`). How the registry works, its review checklist and verified badge, keys
and moderation: [docs/community/](../docs/community/README.md). A field
controller imports signed packages from an index with its own trusted mode keys
(plan phase 6, `controller/README.md`, "Signed mode packages").

The registry repository itself waits for the maintainer (decisions P5-3, P5R-9;
`docs/community/registry.md`, "Creating the repository").
