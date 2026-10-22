<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Moderation

The registry is curated: nothing is listed without a reviewed pull request
(ADR-P5-8). This page says what happens when something listed should not be,
and who decides. Decisions P5G-6 and P5G-8, **for the maintainer**: the
maintainer decides every moderation case until the project has more maintainers.

Everyone taking part follows the [Code of Conduct](../../CODE_OF_CONDUCT.md).

## Reporting a mode

Open an issue in the registry with the *Flag a mode* template: which mode and
version, and what is wrong. Report privately instead (`SECURITY.md`, GitHub's
private vulnerability reporting) when it is a security problem: a script that
gets around the sandbox, a stolen key, a package that is not what its source
says.

Reasons a mode is acted on:

- it breaks the rules of the [Code of Conduct](../../CODE_OF_CONDUCT.md) or the
  safety section of the design specification (props meant to look like real
  weapons or explosives, getting around radio rules, hiding chrono tampering);
- it is not the author's to share: someone else's mode, or content from a
  commercial product (the clean-room policy in `CONTRIBUTING.md`), or a licence
  the author cannot give;
- it misleads: a name or id imitating another mode, or a description that does
  not match the game;
- it is malicious or broken on the field (a script that tries to escape the
  sandbox, exhausts a box, or ends games wrongly).

## What can be done

From the lightest:

| Action | How | Effect |
| --- | --- | --- |
| Ask for a fix | a comment on the issue | the author publishes a new version |
| Take the badge away | `registry_check.py badge <id> <version> --remove` in a pull request | the version is listed *not reviewed*; boxes and project-only fields no longer take it from the index (installed copies stay) |
| Take a version down | remove it from `index.json` and its files from `packages/` (and `modes/<id>/` if it was the newest) | it is no longer offered; Git history keeps it, as the licence allows |
| Revoke the author's key | [`keys.md`](keys.md), "Revoking a key" | nothing that key signed installs anywhere that reads `revoked.json` |

A takedown for a security problem happens at once, before discussion; any other
gives the author 14 days to answer first. Every action is a pull request that
says why, so it can be read later; for a private report it says only "a
security report" until the problem is fixed.

## Ids and owners

- An id belongs to the owner of the key that first listed it (the `owner` of
  its key file, a GitHub handle). Every version of an id is signed by keys of
  that owner; the CI refuses anything else.
- Ids starting `org.atalaia.` are the project's built-in modes and are never
  listed (a controller refuses to install them anyway).
- An id changes owner only by a maintainer's decision: the old owner agrees, or
  is gone for a year and the mode needs a new keeper. The CI reports the change
  in the pull request; the maintainer says why in it.

## Appeals

An author who disagrees with a decision replies on the issue or the pull
request, or writes to the maintainers privately. A different maintainer looks at
it when there is one; until then the maintainer answers within 14 days.
