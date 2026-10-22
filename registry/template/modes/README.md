<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Mode sources

One folder per mode, named after its id (`modes/org.club.my-mode/`), holding the
source of its newest version: `mode.yaml`, `node.lua`, `field.lua` (if any),
`assets/` and `tests/`. The CI checks that it packs to exactly the newest
archive in `packages/`, so what reviewers read is what was signed, and runs its
tests in the simulator. Older versions' sources are in the Git history.
