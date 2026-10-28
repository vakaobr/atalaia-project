

## Build manuals, pin references, the firmware and controller setup guides (HWM-1 to HWM-3, 2026-10-28)

The maintainer asked for the builders' manuals (wiring, pins, firmware). Checked against the firmware and the bench notes: no GPIO disagreed; nine smaller errors fixed. English only; the Portuguese translation follows. Much of the hardware is still not tried on a real board (the 2.8-inch TFT, keypad, LED ring, NFC, amplifier, gauge, power path, the pod, a Pi controller).

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| HWM-1 | One pin reference per board: shared or inside each BUILD.md? | Inside each BUILD.md as columns on the existing tables (Field Box: new section 15). | tools/check_wiring.py already checks those tables against Kconfig; the Field Box guide added to its GUIDES. | built (2026-10-28); open for the maintainer's review |
| HWM-2 | Re-render the wiring diagram for a one-label fix ("not PCF8574A")? | Yes. | The label contradicted the firmware; the render is deterministic. | built (2026-10-28); open for the maintainer's review |
| HWM-3 | Where do builders get firmware? | "No ready-made file today; build with docker_fw.py", plus what a release will change. | No published release or artifact exists (checked: no GitHub releases), no release key. | built (2026-10-28); open for the maintainer's review |

## Firmware releases on GitHub, signed with two release keys; release 0.4.0 (REL-1 to REL-8, 2026-10-28)

The maintainer chose (2026-10-28) to publish firmware releases on GitHub, keep the build-it-yourself path, sign with two release keys like the mode keys (root 424d053af5cdbc35 offline, CI 32b3c815ac30ad43 as the repository's secrets), and publish v0.4.0 at once. v0.4.0 was published as a pre-release on 2026-10-28; its Field Box image verifies against the CI key.

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| REL-1 | Where are the release keys the default? | Kconfig `CONFIG_ATALAIA_OTA_RELEASE_KEYS`, `docker_fw.py --release-keys`, the Pi's `PROJECT_RELEASE_KEYS`, the phone's `projectReleaseKeys`. | Mirrors the mode keys. | confirmed by the maintainer (2026-10-28) |
| REL-2 | Which images get a signed `.release.json`? | The Field Box image only; modem and pod are covered by SHA256SUMS. | They carry no Atalaia descriptor and are not updated over the air. | built (2026-10-28); open for the maintainer's review |
| REL-3 | How is "no partial release" enforced? | fail-fast matrix; a draft published only after every asset is up; a failure deletes the draft; an existing release for the tag aborts first. | gh release create could leave a half-uploaded release. | built (2026-10-28); open for the maintainer's review |
| REL-4 | Where is the CI key used? | Only in the publish job, only on a tag, from $RUNNER_TEMP, deleted afterwards; its key id checked before signing and the signature verified against the pinned public key; a dry run uses a throw-away key. | Builds never touch the secrets; a wrong secret fails the release. | confirmed by the maintainer (2026-10-28) |
| REL-5 | Does the site server's catalogue default to the project's keys? | No; `ATALAIA_FIRMWARE_KEYS` stays opt-in. | Operator-set; a default would change existing behaviour. | built (2026-10-28); open for the maintainer's review |
| REL-6 | Notes size | The CHANGELOG section, capped at 120,000 characters with a link to the full file. | 0.4.0's section is ~118k; GitHub's limit is 125k. | built (2026-10-28); open for the maintainer's review |
| REL-7 | Tags with a pre-release (v0.5.0-rc.1)? | Allowed; the release is always a GitHub pre-release. | A plain vX.Y.Z tag must match version.h exactly. | built (2026-10-28); open for the maintainer's review |
| REL-8 | Version bump at release | version.h pre-release emptied, plus app, controller and server versions, as in 0.3.0. | The tag and the code must agree. | built (2026-10-28); open for the maintainer's review |

## Cutting a release: the Prepare release workflow (PREP-1 to PREP-8, 2026-10-28)

The maintainer chose (2026-10-28) a Prepare release pull request over release-please, keeping the curated CHANGELOG and prose commits; "Allow GitHub Actions to create and approve pull requests" was turned on by the maintainer.

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| PREP-1 | Release PR by workflow or release-please? | A "Prepare release" workflow_dispatch opening a PR from `release/vX.Y.Z`. | Maintainer's choice 2026-10-28; reuses release.yml, the CHANGELOG format and the version files. | confirmed by the maintainer (2026-10-28) |
| PREP-2 | What is `bump` counted from? | The newest released CHANGELOG section (SemVer order); an explicit `version` must be newer; after a pre-release, `patch` gives its own X.Y.Z. | version.h can be a dev or rc value; the CHANGELOG is the record of what shipped. | built (2026-10-28); open for the maintainer's review |
| PREP-3 | Where does the dev marker for the next version go? | `open-dev` after the tag, in a follow-up PR "Open X.Y.Z-dev" from `dev/open-*`; version.h and CMake only. | The tag commit must build exactly X.Y.Z (the 0.3.0 -> 0.4.0-dev convention). | built (2026-10-28); open for the maintainer's review |
| PREP-4 | Next dev version | Next minor, or the same X.Y.Z after a pre-release; `--next` overrides. | Matches 0.3.0 -> 0.4.0-dev. | built (2026-10-28); open for the maintainer's review |
| PREP-5 | Pre-release label | Goes into version.h PRERELEASE and the app, controller and server version strings; CMake keeps numbers only. | The tag vX.Y.Z-rc.1 matches release.yml. | built (2026-10-28); open for the maintainer's review |
| PREP-6 | Who starts release.yml? | tag-release.yml tags the merge commit and runs `gh workflow run release.yml --ref <tag>`; release.yml decides by ref_type, refuses non-release tags and an existing release (early and again before creating). | A tag pushed with GITHUB_TOKEN starts no workflow; no double publish. | built (2026-10-28); open for the maintainer's review |
| PREP-7 | Cap on the PR body | 60000 characters, cut at a line with a pointer to CHANGELOG.md. | GitHub rejects a PR body over 65536 characters. | built (2026-10-28); open for the maintainer's review |
| PREP-8 | Permissions and safety | Least privilege per job; dispatch only from main; tagging only for merged same-repo PRs on `release/v*`; inputs via env vars; `check` on the merge commit before tagging. | No tagging from forks or a wrong commit; no shell injection. | built (2026-10-28); open for the maintainer's review |
