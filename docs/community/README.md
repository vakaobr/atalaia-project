<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# The community mode registry

Community game modes are shared through a registry: a Git repository,
`atalaia-modes`, whose index a field controller imports signed packages from
(ADR-P5-3 and P5-8 as amended, phase 5 plan phases 8 and 9, decisions P5G-1
onwards in [`../review/decisions-to-review.md`](../review/decisions-to-review.md)).
The repository is live at
[github.com/vakaobr/atalaia-modes](https://github.com/vakaobr/atalaia-modes),
created from [`registry/template/`](../../registry/template/) (decision P5R-9),
and its page and `index.json` are at
[vakaobr.github.io/atalaia-modes](https://vakaobr.github.io/atalaia-modes/). It
has no modes yet, and the project's signing key is still to be added; everything
below can also be tried locally against the template.

| Document | For | What |
| --- | --- | --- |
| [`../../CONTRIBUTING.md`](../../CONTRIBUTING.md#submitting-a-community-mode) | Authors | Submitting a community mode, step by step |
| [`registry.md`](registry.md) | Everyone | How the registry works: its files, the two signatures, what its CI checks, what it publishes, creating the repository |
| [`review.md`](review.md) | Reviewers, maintainers | The review checklist and the verified badge |
| [`keys.md`](keys.md) | Authors, maintainers, fields | Mode keys: making, keeping, rotating and revoking them |
| [`moderation.md`](moderation.md) | Everyone | Reports, taking a mode down, ownership of ids, appeals |
| [`../rfcs/0000-mode-packages-and-registry.md`](../rfcs/0000-mode-packages-and-registry.md) | Implementers | The RFC for the package format, the manifest and the index (draft) |

The package format itself is [`protocol/mode-packages.md`](../../protocol/mode-packages.md);
the tools are [`tools/mode_package.py`](../../tools/mode_package.py) (pack, keys,
sign, verify) and [`tools/registry_check.py`](../../tools/registry_check.py)
(the registry's checks and chores).
