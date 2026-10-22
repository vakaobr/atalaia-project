<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Reviewing a community mode

Every change to the registry is a pull request. The CI does the mechanical
checks ([`registry.md`](registry.md), "What the CI checks"); a reviewer reads
the mode itself. This is ADR-P5-8's process with its 2026-10-22 amendment
(P5R-12) and decisions P5G-2, P5G-5 and P5G-14.

## Who reviews

- **Listing** a mode (merging it *not reviewed*): any maintainer, once the CI
  passes and the checklist's manual items hold. A listed mode is installable by
  fields that trust its author's key; the console marks it *not reviewed by the
  project*.
- **The verified badge**: a maintainer who holds the project's registry key and
  is not the mode's author. With it, the version is signed by the project and
  reaches every field that trusts the project's key, and Field Boxes
  ([`registry.md`](registry.md), "Two signatures").
- The first answer to a submission within **14 days**, even if it is "not yet"
  (P5G-14). A pull request that waits more than 30 days for its author is closed;
  it can be reopened.

## The checklist

| # | Check | How |
| --- | --- | --- |
| 1 | `mode.yaml` is valid (id, version, licence, roles, parameters) | CI: `lint` (the manifest) and `test` (the simulator loads the mode) |
| 2 | `license` is one of the approved seven (ADR-P5-5) | CI: `lint` |
| 3 | Every script and YAML file has SPDX headers naming that licence; the repository passes REUSE | CI: `lint`, `reuse lint` |
| 4 | `tests/` exist and pass in the simulator | CI: `lint` (they exist), `test` (they pass) |
| 5 | No `io`, `os`, `require`, `load`, `loadfile`, `dofile`, `loadstring`, `debug`, `package`, `_G`, `_ENV`, `collectgarbage` or `string.dump` in the Lua | CI: `lint` (names in the code, outside comments and strings); the sandbox removes them anyway, and `sandbox-escape` proves it |
| 6 | No hard-coded team names, node counts or language strings: texts for players come from `mode.yaml` and its `i18n:` | Manual |
| 7 | `params` have sensible defaults, `min`/`max` and labels | Manual |
| 8 | Events: standard events for standard things, `x.<author>.<name>` for custom ones | Manual |
| 9 | `assets/` at most 512 KiB | CI: `lint` |
| 10 | Nothing offensive, misleading or trademarked in the name, description or assets; nothing taken from a commercial product (the clean-room policy in `CONTRIBUTING.md`) | Manual |
| 11 | If `i18n:` is present, every language has the same keys, all of them declared | CI: `lint` |
| 12 | The author's signature is valid and the key is not revoked; a verified version is also signed by the project's key | CI: `lint` |

Also manual, for every pull request: the source in `modes/<id>/` is what the
pull request says it is (the CI proves it is what was signed); a new author key
belongs to the person opening the pull request (they say so in it, from the
account named as `owner`); a new id does not imitate another mode's id or name.

## The verified badge

A version gets the badge when all of these hold (ADR-P5-8, as amended):

1. All 12 checklist items pass.
2. Its tests show the mode working, not just loading: at least the ways a game
   is won, scored or ended, and a setting that changes the play.
3. A maintainer read its Lua and found it uses the script API as documented
   (`modes/README.md`, `docs/design-spec.md` section 9), within the sandbox's
   limits on a Reduced box when it says `min_tier: reduced`.
4. It is signed by the author's key **and** by the project's registry key,
   over the same archive, neither key revoked.

The badge belongs to one version. A new version is listed *not reviewed* until
it is reviewed again; a reviewer may look only at what changed
(`git diff` of `modes/<id>/`).

## Doing it

The reviewer checks out the pull request, in the dev container of the Atalaia
repository:

```sh
python3 tools/registry_check.py lint ../atalaia-modes --base ../atalaia-modes-main
python3 tools/registry_check.py test ../atalaia-modes
python3 -m atalaia_sim serve ../atalaia-modes/modes/<id> --node box1=<role>   # play it
```

To give the badge (the project's key never leaves the maintainer's offline
copy, [`keys.md`](keys.md)):

```sh
python3 tools/registry_check.py badge ../atalaia-modes <id> <version> --key /media/offline/atalaia-registry.pem
```

It signs the archive with the project's key into
`packages/<id>-<version>.tar.verified.json` and lists that signature in the
index with `verified: true`; the maintainer commits it to the pull request
(`git commit -s`), or in a pull request of its own for a version already listed.
`badge ... --remove` takes the badge away (a version found wanting after it was
given, [`moderation.md`](moderation.md)).

## What needs an RFC

As ADR-P5-8 says: a new index `schema_version`, a new signing algorithm, a
change to the approved licences, or to the sandbox's limits. New checks, new
checklist items, new editor blocks and Blockly upgrades do not.
