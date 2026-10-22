<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Keys

Public mode keys only. A private key never comes here, nor into any repository.

| Path | What |
| --- | --- |
| `authors/<key id>.json` | An author's key: `{"key_id", "public_key", "owner", "name"?, "added"?}`; `owner` is the GitHub handle of who holds it. It signs that author's packages (`packages/*.release.json`) |
| `project/<key id>.json` | The project's registry key: it signs the verified badge (`packages/*.verified.json`). The same key is built into the Field Box firmware. Only maintainers change this folder |
| `revoked.json` | Keys that no longer count: `{"schema_version": 1, "keys": [{"key_id", "reason"?, "date"?}]}`. Nothing they signed may stay listed |

`python3 tools/registry_check.py key` (in the Atalaia repository) writes a key
file. A key is never deleted, only revoked. Making, keeping, rotating and
revoking keys: [docs/community/keys.md](https://github.com/vakaobr/atalaia-project/blob/main/docs/community/keys.md).
