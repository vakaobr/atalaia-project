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

## Commit messages

Start with the area, then a short summary in the imperative:

```
core: add Lua memory limit
modes/bomb: return to standby after defuse
docs: explain CQB field profile
```

## Cutting a release

For the maintainer. A release is a pull request and a merge; the tag and the build follow by themselves.

1. Check that CHANGELOG.md's `## [Unreleased]` section says what the release contains (an empty one is refused).
2. **Actions > Prepare release > Run workflow**, on `main`: choose `bump` (patch, minor or major, counted from the newest released CHANGELOG section) or give an explicit `version`, and a `prerelease` label such as `rc.1` if it is one. It runs `tools/prepare_release.py` and opens the pull request **Release vX.Y.Z** from `release/vX.Y.Z`: the Unreleased section moved under the new version, `core/include/atalaia/version.h` (pre-release emptied), `core/CMakeLists.txt`, `app/pubspec.yaml`, `app/lib/version.dart` and the controller's and the server's `__init__.py` bumped (what `controller/tests/test_versions.py` checks), the release notes as the description.
3. Review it, let CI pass, merge it. Merging is the go-ahead: `tag-release.yml` creates the annotated tag `vX.Y.Z` on the merge commit and starts `release.yml` for it (builds the images, signs the Field Box image with the CI key, publishes a GitHub pre-release; see [firmware/esp32/docs/RELEASE_SIGNING.md](firmware/esp32/docs/RELEASE_SIGNING.md)). A second pull request, **Open X.Y.Z-dev after the vX.Y.Z release**, sets the core's next development version; merge it too, so that later builds sort above the release.
   The signing job runs in the protected environment `release` and only for a tag on `main`: the first release after this change waits for the maintainer's approval in the Actions run, and the repository settings that make it a real gate (environment, secrets moved into it, tag ruleset) are listed in [firmware/esp32/docs/RELEASE_SIGNING.md](firmware/esp32/docs/RELEASE_SIGNING.md#repository-settings-the-release-needs-the-maintainer-does-these-no-workflow-can).
4. Closing the pull request without merging releases nothing: delete its branch. A release that went wrong is deleted by hand (the GitHub release, then the tag) before trying again; `release.yml` refuses to publish a tag that already has a release.

The release build refuses an image whose boot splash is not the Atalaia tower (decision LOGO-7): `tools/release_package.py package` checks that `firmware/esp32/assets/splash.pgm` matches the SHA-256 pinned in the tool, that the build's `sdkconfig` has no other `CONFIG_ATALAIA_SPLASH_LOGO`, and that the generated `splash_logo.c` holds that file's pixels, and fails the job otherwise (a dry run from a branch fails the same way). A builder's own splash is for local builds only. To change the project's tower on purpose, redraw it (`tools/oled_logo.py`) and update `SPLASH_SHA256` in `tools/release_package.py` in the same commit.

By hand, the same: `python3 tools/prepare_release.py prepare --bump minor`, commit, tag `vX.Y.Z` on the commit that passes `prepare_release.py check --version X.Y.Z`, push the tag. "Run workflow" on `release.yml` from a branch is a dry run that publishes nothing.

## Code style

- **C**: C11, 4-space indentation, `snake_case`, public symbols prefixed `atalaia_`. Builds must pass with `-Wall -Wextra -Wpedantic` and no warnings.
- **Lua**: 2-space indentation; no globals except the sandbox API.
- **Dart**: the standard `dart format` style.

Formatting is automatic: run `sh tools/format.sh` before committing (in the [dev container](tools/README.md) if you do not have clang-format 18 and StyLua), and CI fails if anything is left unformatted. The rules live in [`.clang-format`](.clang-format) and [`stylua.toml`](stylua.toml), and [`.editorconfig`](.editorconfig) sets up most editors to match. Vendored Lua and generated files are left alone.

## Safety

Never contribute features meant to make props look like real weapons or explosive devices, to bypass radio regulations, or to hide chrono tampering. See the safety section of the design specification.

## Code of conduct

Everyone taking part follows our [Code of Conduct](CODE_OF_CONDUCT.md).
