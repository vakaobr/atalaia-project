<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# How the registry works

The registry is a Git repository of signed mode packages, reviewed through
pull requests and published as static files. Design: ADR-P5-3, P5-4 and P5-8
as amended (`docs/phase-5-community/ADR.md`), decisions P5C-8 to P5C-13 (the
package format) and P5G-1 onwards (the registry itself).

## Its files

```
index.json                       the registry index (registry/schema/index.schema.json)
keys/authors/<key id>.json       an author's public mode key
keys/project/<key id>.json       the project's registry key(s): the verified badge
keys/revoked.json                revoked keys (registry/schema/revoked.schema.json)
modes/<id>/                      the source of each mode's newest version, with its tests/
packages/<id>-<version>.tar                the package archive (protocol/mode-packages.md)
packages/<id>-<version>.tar.release.json   the author's signature
packages/<id>-<version>.tar.verified.json  the project's signature (verified versions only)
packages/<id>-<version>.tar.license        the archive's licence (REUSE)
.github/workflows/registry.yml   the CI: registry-lint, registry-test, sandbox-escape, publish
```

A key file says whose key it is:

```json
{"key_id": "21fe31dfa154a261", "public_key": "<44 characters of base64>",
 "owner": "github-handle", "name": "Example Club", "added": "2026-10-22"}
```

The file is named after the key's id (the first 16 hex digits of the SHA-256 of
its 32 public bytes, as a firmware release key's). `owner` is the GitHub handle
of whoever holds the private half. `tools/registry_check.py key` writes it.

Packages live in the repository itself, next to the index, and the index names
them by a relative path (`packages/<id>-<version>.tar`): a field without
internet copies the published folder to a USB stick and points its controller's
`[modes] index` at it (decision P5C-19). A package is at most 1 MB (P5-6), so the
repository stays small (P5G-1).

## Two signatures

Every version carries the **author's signature** (`.release.json`): who made it.
A version the project reviewed also carries the **project's signature**
(`.verified.json`), made by a key in `keys/project/` over the *same* archive:
that is the **verified badge** (decision P5G-2). The index lists the project's
signature and key id for a verified version, the author's otherwise, and
`verified` says which.

What that means where the packages are used:

| Who | Trusts | Gets |
| --- | --- | --- |
| A field controller with only the project's key in `[modes] keys` | the badge | verified versions only |
| A field controller that also lists some authors' keys | the badge and those authors | verified versions and those authors' others, shown as *not reviewed by the project* |
| A Field Box (phase 5 plan phase 13) | the mode keys built into its firmware (`CONFIG_ATALAIA_MODE_KEYS`, the maintainer's P5B-9) | the project's key is one of them, so a box takes verified versions only |

A field never needs to trust the registry's index: a controller checks every
package with its own keys (`protocol/mode-packages.md`, "Trust"). The published
`keys.json` lists the registry's keys for a field that wants to copy them into
its controller's configuration.

## What the CI checks

`registry.yml` runs on every pull request and every push, with this
repository's tools checked out at a pinned ref (`ATALAIA_REF`, decision P5G-4):

**registry-lint**

- `index.json` and `keys/revoked.json` against the JSON Schemas
  (`check-jsonschema`), then `python3 tools/registry_check.py lint .`:
- every key file: its form, its id, an owner; no key both an author's and the
  project's;
- every version in the index: its archive at `packages/<id>-<version>.tar`, the
  author's signature by an author key that is not revoked, every check of a
  package (size, SHA-256, canonical archive, `mode.yaml` agreeing with the
  manifest, an approved licence: `protocol/mode-packages.md`, "Checking a
  package"), the index's fields being the release's, the licence file; for a
  verified version, the project's signature by a project key that is not
  revoked;
- the review checklist's automated items on the package's files
  ([`review.md`](review.md)): SPDX headers naming the package's licence (item
  3), none of the names the sandbox removes in its Lua (item 5), `assets/` at
  most 512 KiB (item 9), the same keys in every language of `i18n:` (item 11);
- `modes/<id>/` packs to exactly the newest version's archive (what the review
  reads is what is signed) and has `tests/*.yaml` (item 4); no source without an
  index entry, no file in `packages/` that no version names;
- ids starting `org.atalaia.` are refused (the project's built-in modes); every
  version of an id is signed by keys of one owner (P5G-6);
- on a pull request, against the base branch (`--base`): a published version
  never changes (a new version instead); an id changing owner or a version
  removed is reported for the reviewer;
- `reuse lint`.

**registry-test**: the core built from the pinned ref, then
`python3 tools/registry_check.py test .`, which runs each mode's own tests in
the simulator (`python3 -m atalaia_sim test modes/<id>`).

**sandbox-escape**: the same battery as this repository's CI job of that name
(`core/tests/test_sandbox_escape.c` under ASan and UBSan, and
`simulator/tests/test_sandbox_escape.py`), on the core the registry relies on.

Pull requests run with `pull_request`, never `pull_request_target`, so they have
no secrets; submitted Lua runs only inside the sandbox of the simulator.

**publish** (a push to `main` that passed all three):
`python3 tools/registry_check.py site . ../_site` builds what GitHub Pages
serves: `index.json`, `revoked.json` (beside the index, where a controller looks
for it), `keys.json`, `packages/` and `badges/<id>.svg` (the newest version,
*verified* or *not reviewed*, for an author's own pages). It refuses to publish
a registry that does not pass `lint`.

## Trying it locally

From this repository, with a registry checked out (or a copy of
`registry/template/`) in `../atalaia-modes`, in the dev container:

```sh
python3 tools/registry_check.py lint ../atalaia-modes
python3 tools/registry_check.py test ../atalaia-modes   # needs the shared core (tools/check.sh builds it)
python3 tools/registry_check.py site ../atalaia-modes /tmp/registry-site
```

This repository's own CI runs the template's checks on a sample submission
(`registry/examples/org.example.hill/`, King of the Hill with its own screens,
the mode to copy when starting one; throwaway keys made at run time):
`python3 -m unittest discover -s registry/tests`, CI job `registry-template`
(decision P5G-11).

## Creating the repository (the maintainer)

Not done yet (P5-3, P5R-9). When the maintainer decides to:

1. Create `atalaia-modes` (public) and copy the contents of
   `registry/template/` into it, `.github/` included.
2. Set `ATALAIA_REF` in `.github/workflows/registry.yml` to a release tag or
   commit of this repository; replace the owner in `.github/CODEOWNERS` if it
   is not `@vakaobr`.
3. `reuse download --all`, so `LICENSES/` holds the texts REUSE needs.
4. Make the project's registry key offline ([`keys.md`](keys.md)) and add its
   public half with `registry_check.py key ... --project`; the same public key
   goes into the Field Box firmware's `CONFIG_ATALAIA_MODE_KEYS` in a signed
   release.
5. Turn on GitHub Pages with *GitHub Actions* as its source, and branch
   protection on `main` requiring the three checks and a code owner's review.
6. Point the project page and `controller.toml.example` at the published index
   (`https://<owner>.github.io/atalaia-modes/index.json`).
