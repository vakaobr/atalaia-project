# Contributing to Atalaia

Thanks for helping build Atalaia. Players, field owners, GMs, makers and developers are all welcome: you do not need to write code to contribute.

## Ways to help

- **Review the design.** Read the [design specification](docs/design-spec.md) and open an issue for anything unclear, missing or wrong.
- **Propose game modes.** Use the *Game mode idea* issue template. Describe the game the way you would explain it to players.
- **Share field experience.** How big is your site? How many teams and squads? What breaks in real games? This shapes the defaults.
- **Write code, build hardware, write docs.** Pick an issue labelled `phase-0` or `good first issue`, or open one to discuss your idea first.

## Clean-room policy

Atalaia is an independent, clean-room project. To keep it legally safe:

- Do **not** contribute code, firmware dumps, decompiled code, manuals, UI layouts, sounds, images or protocol details taken from any commercial product.
- Do **not** work towards compatibility with any commercial prop system's radio protocol or hardware.
- Do **not** use commercial product or company names in code, branding or marketing. Factual comparisons in discussions are fine.

If you are unsure whether something is allowed, ask in an issue before contributing it.

## Developer Certificate of Origin

Every commit must be signed off, certifying that you wrote the change or have the right to submit it under the project's licences, as described in the [Developer Certificate of Origin](https://developercertificate.org/):

```sh
git commit -s -m "core: add event ring buffer"
```

This adds a line like `Signed-off-by: Your Name <you@example.com>` to the commit. Pull requests with unsigned commits cannot be merged.

## Licences of contributions

Your contribution is licensed under the licence of the folder it lands in (see [LICENSING.md](LICENSING.md)). Contributions to `app/` are additionally covered by the [app-store permission](app/APP-STORE-PERMISSION.md).

## Changing the protocol or API

New capability types, standard events, protocol fields and API endpoints go through a short RFC:

1. Copy [`docs/rfcs/0000-template.md`](docs/rfcs/0000-template.md) to `docs/rfcs/0000-your-title.md`.
2. Open a pull request. Discussion runs for at least two weeks.
3. A maintainer records the decision; accepted RFCs get a number.

Protocol changes are made in `protocol/schema/*.yaml`; then run `python3 tools/protogen.py` and commit the generated files too (see [protocol/README.md](protocol/README.md#changing-the-schema)).

Bug fixes, refactors, new modes and documentation do not need an RFC.

## Submitting a community mode

A game mode you wrote can be shared through the community mode registry, the
`atalaia-modes` repository, without changing this one. Fields install it from
the registry's index; once the project has reviewed it, it carries the
**verified** badge and Field Boxes can fetch it from their field controller.
How the registry works, its review checklist, keys and moderation:
[`docs/community/`](docs/community/README.md).

> The registry is live: [github.com/vakaobr/atalaia-modes](https://github.com/vakaobr/atalaia-modes),
> with its page at [vakaobr.github.io/atalaia-modes](https://vakaobr.github.io/atalaia-modes/).
> It has no modes yet: yours can be the first. You can also run every step below
> against a copy of [`registry/template/`](registry/template/), and share ideas
> with the *Game mode idea* issue template.

1. **Write the mode.** Build it in the visual mode editor (in `simulator/`: `python3 -m atalaia_sim serve ../modes/domination`,
   then `http://localhost:8000/editor/`; *Test in the simulator* plays it, and
   *Make the package* downloads its unsigned archive and the commands that sign
   it, for a field controller of your own; the registry packs from the source),
   or by hand as [`modes/README.md`](modes/README.md) describes; the sample
   [`registry/examples/org.example.hill/`](registry/examples/org.example.hill/)
   (King of the Hill: a script, its own screens in Portuguese and English, the
   LED ring and a sound, tests) is a small one to copy. Pick its id
   (`org.yourclub.name`; `org.atalaia.` is the project's own) and a licence
   from the approved seven (`GPL-3.0-or-later`, `LGPL-3.0-or-later`, `MIT`,
   `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `CC0-1.0`); every file starts
   with SPDX lines naming you and that licence.
2. **Test it.** Write `tests/*.yaml` that show the game being won, scored and
   ended (`modes/README.md`, "Tests"), and run them:
   `python3 -m atalaia_sim test path/to/your-mode` (in `simulator/`).
3. **Make your mode key**, once, outside every repository:
   `python3 tools/mode_package.py keygen --out ~/atalaia-keys/modes.pem`. Keep
   it and a backup offline ([`docs/community/keys.md`](docs/community/keys.md)).
4. **Fork the registry** and put your mode's folder in `modes/<id>/`. Add your
   public key once, then pack, sign and list the mode (from this repository,
   with the registry checked out next to it):

   ```sh
   python3 tools/mode_package.py pubkey --key ~/atalaia-keys/modes.pem
   python3 tools/registry_check.py key ../atalaia-modes --public <base64 key> --owner <your GitHub handle>
   python3 tools/registry_check.py add ../atalaia-modes <id> --key ~/atalaia-keys/modes.pem \
       --name "Name" --description "One line" --author "You or your club"
   python3 tools/registry_check.py lint ../atalaia-modes
   ```

5. **Open a pull request** to the registry (commits signed off), filling in its
   template. The CI checks the signatures, that the source is exactly what you
   signed, the licence headers, the sandbox's rules, the size and the
   translations, and runs your tests in the simulator.
6. **Review.** A maintainer goes through the [review checklist](docs/community/review.md)
   and merges it: your mode is listed, *not reviewed by the project*. The
   **verified badge** follows when a maintainer has read your Lua and the tests
   show the game working: they sign the same archive with the project's key.

A new version: change the source, raise `version` in `mode.yaml`, run `add`
again and open a pull request; a published version never changes. A mode's
badge belongs to one version, so a new version is reviewed again.

## Pull requests

- Keep each pull request focused on one change.
- Describe what you changed, why, and how you tested it.
- Add or update tests: C code in `core/tests/`, modes in `modes/<mode>/tests/`, the app's Dart in `app/test/` (`python tools/docker_app.py`).
- Add an `SPDX-License-Identifier` header to new source files.
- Write code, comments, commit messages and docs in English. Translations of user-facing text are welcome: see [docs/translations/](docs/translations/README.md) for where each part's texts are, the glossary and how a translation is reviewed.

### What CI runs

On a pull request, each job of [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs only when a part of the repository it builds, tests or copies in has changed: its first job, **Which parts changed**, matches the pull request's files against one filter per job (dorny/paths-filter), and the others show as skipped when theirs does not match. A skipped job blocks nothing; only the title check is required.

- **Pushes to `main` run everything**, and so do release-please's pull requests (`release-please--*`) and a pull request whose filter step fails.
- **Always run**: the protocol and generated-files check (it also checks the project page and the wiring diagrams), formatting, REUSE and the DCO sign-off.
- **In every filter**: `ci.yml` itself, `core/` and the folders of `protocol/` (schema, vectors). A change to one of them runs the whole workflow.
- **The rest by part**, for example: the GM console (`controller/console/`) runs the controller jobs, the console's browser tests and the app's jobs, the Android emulator included, since the app bundles the console; `modes/` runs nearly everything (the app, the firmware, the simulator, the controller and the server all load the modes); `firmware/` runs the firmware jobs, the controller's and the app's (they drive the host box, pod and modem), and `firmware/module-core/` the expansion module core's host tests as well, and with `firmware/target-module/` the target module's (its host tests and its UF2 files); `server/` runs the four site server jobs; a change only to docs (`docs/`, except `docs/translations/` and `docs/manuals/en/`, which tests read), `hardware/` or Markdown at the top level runs none of them.

A new test that reads a file from another part of the repository needs that path in its job's filter (the `changes` job in `ci.yml`). When unsure, add it: a needless run costs minutes, a missing path lets a break through to `main`, where everything runs.

## Pull request titles and commit messages

Every change reaches `main` as a **squash-merged** pull request, and the pull request's **title** becomes that commit's message. release-please reads those commits to choose the next version and to write the release's section of [CHANGELOG.md](CHANGELOG.md), so the title must be a [Conventional Commit](https://www.conventionalcommits.org/): `type(scope): summary`, the summary in the imperative. The check **Pull request title** (`.github/workflows/pr-title.yml`) fails until it is; editing the title re-runs it.

```
feat(controller): add short-lived access tokens
fix(firmware): keep the backlight off while the radio sends
docs: explain the CQB field profile
ci: pin release-please by commit SHA
feat(protocol)!: drop the v1 beacon
```

- **Types.** `feat` (a new feature: the next release raises the minor version while the project is 0.x), `fix` (a bug fix: the patch version), `perf`, `revert`, `docs`; these five are listed in the CHANGELOG. `refactor`, `test`, `build`, `ci`, `style` and `chore` are accepted and left out of it, and raise no version on their own. A breaking change adds `!` after the type or scope, or a `BREAKING CHANGE: ...` paragraph to the description; while the project is 0.x it raises the minor version (`bump-minor-pre-major`).
- **Scopes** (optional): the area changed, `core`, `firmware`, `modem`, `pod`, `controller`, `console`, `server`, `app`, `preview`, `site`, `docs`, `ci`, `modes` (or `modes/<mode>`), `protocol`, `tools`, `hardware`, `simulator`, `registry`, `examples`, `i18n`, `security`, `deps`, `release`. A new area is added to the list in `pr-title.yml`.
- **Write the title for the reader of the CHANGELOG**, and the details (what, why, how it was tested, decisions) in the description: the squash commit keeps it in the history. The commits inside the pull request can be worded freely; each still needs its `Signed-off-by` line.
- Dependabot's pull requests are titled `ci: bump ...` and `chore(<scope>): bump ...` (`.github/dependabot.yml`); retitle one as `fix(<scope>): ...` when the update fixes something users see.

### CHANGELOG.md

release-please writes each release's section of CHANGELOG.md from the titles, at the top, as `## [X.Y.Z](compare link) (date)` with Features, Bug Fixes, Performance, Reverts and Documentation. Do not edit those sections. The `## [Unreleased]` section above them is for optional, longer **hand-written notes** in the file's older style (one bullet per change, what a builder or a field needs to know: migrations, settings, decisions): when the release pull request is made, they move under the release's section as `### Details` (`tools/prepare_release.py release-pr`), and the GitHub release shows both. The sections up to 0.5.0 were written by hand before release-please and stay as they are.

## Releases

For the maintainer. There is one way to release: merge release-please's pull request. The tag, the GitHub release and the firmware follow by themselves (`.github/workflows/release-please.yml`).

1. **The release pull request keeps itself up to date.** On every push to `main`, release-please (`release-please-config.json`, `.release-please-manifest.json`) opens or updates the pull request **chore(release): vX.Y.Z** from the branch `release-please--branches--main`, once there is a `feat`, `fix`, `perf`, `revert`, `docs` or breaking change since the last release: the next version, the CHANGELOG section, and the version files `app/pubspec.yaml`, `app/lib/version.dart` and the controller's and the server's `__init__.py` (their `x-release-please-version` markers). A second job then commits what release-please cannot do on that branch (`tools/prepare_release.py release-pr`): the core's version, `core/include/atalaia/version.h` with its pre-release (`dev`) emptied and `core/CMakeLists.txt`, the hand-written Unreleased notes as the section's Details, and the check that every version file agrees (what `controller/tests/test_versions.py` and `app/test/version_test.dart` check).
2. **CI on it.** A pull request opened by the workflow token starts no workflow, so CI does not run on the release pull request by itself: close it and reopen it (a person's action), and CI and the title check run.
3. **Merge it** (squash) when the release should happen. release-please tags the merge commit `vX.Y.Z` and makes the GitHub pre-release with the CHANGELOG section; the next job turns that release back into a draft and starts `release.yml` on the tag (a tag made by the workflow token starts no workflow of its own; a dispatch is the exception). `release.yml` builds the Field Box, modem and I/O pod images, and its **Sign and publish** job runs in the environment `release` (if the environment has required reviewers, it first waits for their approval in the Actions run; it has none for now, the maintainer's choice while the only developer, so merging the release pull request is the human gate), signs the Field Box image with the CI key that the variable `ATALAIA_RELEASE_SIGNING_KEY` chooses (unset: the CI key; `next`: the next CI key, during the [rotation](firmware/esp32/docs/RELEASE_SIGNING.md#rotating-the-ci-key-2026-11)), checks the signature against every trusted key, attaches the nine files (`SHA256SUMS` included), writes the release notes (the pre-alpha warning, the guides and the CHANGELOG section) and publishes the pre-release: [firmware/esp32/docs/RELEASE_SIGNING.md](firmware/esp32/docs/RELEASE_SIGNING.md). The settings that guard the signing (environment, required reviewers, signing secrets in it only, tag ruleset) are listed [there](firmware/esp32/docs/RELEASE_SIGNING.md#repository-settings-the-release-needs-the-maintainer-does-these-no-workflow-can).
4. **Then merge the pull request "chore(core): open X.Y+1.0-dev after the vX.Y.Z release"** that the same run opens: it sets the core's next development version (decision FV-1), so later builds sort above the release. Close and reopen it too if CI should run on it.
5. **Pre-releases** (a release candidate, `v0.7.0-rc.1`). Every GitHub release is marked a pre-release while the project is pre-alpha (`"prerelease": true`). For a version with a pre-release label, merge a pull request whose description ends with the line `Release-As: 0.7.0-rc.1` (the squash commit must keep the description: Settings > General > Pull Requests, squash merging's default message "Pull request title and description"), or set `"release-as": "0.7.0-rc.1"` in the package of `release-please-config.json` for that one release and remove it afterwards. The label goes into every version file, version.h's `ATALAIA_VERSION_PRERELEASE` included; the next development version after it is the same X.Y.Z with `dev`. The same footer forces any other version, for example the first one after this change (below).
6. **Something went wrong.** Closing the release pull request releases nothing; release-please opens it again on the next releasable change. A failed firmware run leaves the release a draft: re-run the failed job (the upload replaces what a half-done run attached), or delete the draft release and the tag to start again. `release.yml` refuses a tag whose release is already published. "Run workflow" on `release.yml` from a branch is a dry run that publishes nothing; a tag `vX.Y.Z` pushed by hand by the maintainer still releases through `release.yml` (it creates the release itself), for when Actions cannot tag.

The first release-please release was v0.6.0 (it started from v0.5.0, the last one made by hand); its firmware build failed (the I/O pod's boot-splash check, #26), so it has no files and only the tag remains. v0.6.1 (2026-11-02) was the first release made through release-please with the signed firmware attached.

The release build refuses an image whose boot splash is not the Atalaia tower (decision LOGO-7): `tools/release_package.py package` checks that `firmware/esp32/assets/splash.pgm` matches the SHA-256 pinned in the tool, that the build's `sdkconfig` has no other `CONFIG_ATALAIA_SPLASH_LOGO`, and that the generated `splash_logo.c` holds that file's pixels, and fails the job otherwise (a dry run from a branch fails the same way). A builder's own splash is for local builds only. To change the project's tower on purpose, redraw it (`tools/oled_logo.py`) and update `SPLASH_SHA256` in `tools/release_package.py` in the same commit.

## Code style

- **C**: C11, 4-space indentation, `snake_case`, public symbols prefixed `atalaia_`. Builds must pass with `-Wall -Wextra -Wpedantic` and no warnings.
- **Lua**: 2-space indentation; no globals except the sandbox API.
- **Dart**: the standard `dart format` style.

Formatting is automatic: run `sh tools/format.sh` before committing (in the [dev container](tools/README.md) if you do not have clang-format 18 and StyLua), and CI fails if anything is left unformatted. The rules live in [`.clang-format`](.clang-format) and [`stylua.toml`](stylua.toml), and [`.editorconfig`](.editorconfig) sets up most editors to match. Vendored Lua and generated files are left alone.

## Safety

Never contribute features meant to make props look like real weapons or explosive devices, to bypass radio regulations, or to hide chrono tampering. See the safety section of the design specification.

## Code of conduct

Everyone taking part follows our [Code of Conduct](CODE_OF_CONDUCT.md).
