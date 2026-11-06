<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 5 -- Community: Status

**Current phase:** Implementation (plan phases 1-13 built in software 2026-10-22: the visual mode editor complete, its link to the simulator, signed mode packages, the sandbox-escape battery, signed packages in the controller, scenario blocks in the GM console, missing modes sent to boxes (controller and box), the registry repository's template and the community processes, German, Traditional Chinese (Taiwan), the build guides for the other node types)
**Phase status:** Software done (every software plan phase built; the gate waits for hardware and real deployments)
**Risk level:** Medium
**Last updated:** 2026-11-04 (a pod's withheld outputs shown as a box's outputs fitted but not enabled, PROPC-6 to PROPC-12; a phone prop's capability types in the start check, PROPC-1 to PROPC-6; the I/O pod, increment 9 of the draft RFC "The expansion port", EXPI9-1 to EXPI9-33; the I2C output module, increment 11 of the draft RFC "The expansion port", EXPI11-1 to EXPI11-19; port integration and the target module, increment 8 of the draft RFC "The expansion port", EXPI8-1 to EXPI8-19; the port driver, the box's side, increment 6 of the draft RFC "The expansion port", EXPI6-1 to EXPI6-19; the module core, increment 7 of the draft RFC "The expansion port", EXPI7-1 to EXPI7-20; the port guides, increment 10 of the draft RFC "The expansion port", EXPI10-1 to EXPI10-14; the leftovers of increments 3-5 of the draft RFC "The expansion port", EXPL-1 to EXPL-12; the "outputs fitted, not enabled" note, EXPL-13 to EXPL-22); 2026-11-03 (the modes, increment 4 of the draft RFC "The expansion port", EXPI4-1 to EXPI4-13; scenario triggers, increment 5 of the draft RFC "The expansion port", EXPI5-1 to EXPI5-15; the controllers and the console, increment 3 of the draft RFC "The expansion port", EXPI3-1 to EXPI3-14; the simple output and the box's output layer, increment 2 of the draft RFC "The expansion port", EXPI2-1 to EXPI2-16; the expansion port's protocol, increment 1, EXPI1-1 to EXPI1-12); 2026-11-02 (plan phase 13b tested end to end against the real controller over HTTPS, MFH-1 to MFH-7); 2026-10-22 (plan phase 11 built, P5K-1 to P5K-12; plan phase 12 built; the editor makes the package itself, P5I-1 to P5I-6; plan phases 8 and 9 built; plan phase 7 built; plan phase 13b built; plan phase 13a built; plan phases 3-6 built, P5B-9 answered; plan phase 2 built, plan phase 13 planned from P5R-8 and built as 13a and 13b; refreshed after phases 2-4 software; first written 2026-10-18)
**Next step:** the review of the German and the Traditional Chinese by native-speaking players (P5H-5, P5K-11), and the maintainer's P5K-3, P5K-4, P5K-5, P5K-7 and P5K-12 (box flash and fonts, OLED readability, typed Chinese names, the app's font, the radio band on the Chinese page); P5I-1 and P5I-3 (the editor's package: made in the page, signed offline) for the maintainer; creating the registry repository waits for the maintainer; plan phase 13's test on real boxes is HW3; every software plan phase is built; the build guides wait for their first builds and photos (HW2) and the maintainer's P5J decisions

Phase 5 is the community layer: visual mode editor (Blockly), mode
registry with signing and a verified badge, carrier PCB, translations,
and build guides. It is ongoing after the first release (design-spec.md
section 16).

## Completed

- [x] Research phase: `RESEARCH.md`
- [x] Architecture decisions: `ADR.md` (8 ADRs: P5-1 through P5-8)
- [x] Implementation plan: `PLAN.md`
- [x] **Refresh after phases 2-4 software (2026-10-22):** every ADR re-checked
  against the built code, with dated amendments (P5-1, P5-2, P5-3, P5-4,
  P5-7, P5-8) and notes (P5-5, P5-6); the plan re-cut into 12 software plan
  phases and 3 hardware ones in build order; decisions P5R-1 to P5R-14 in
  `docs/review/decisions-to-review.md` (all open; P5R-8 and P5R-10 are for
  the maintainer)
- [x] **Plan phase 1, the visual mode editor (2026-10-22), in software:**
  Blockly 13.3.0 (vendored, checksummed) served by the simulator at
  `/editor/`; 37 blocks for the node and field script API; a Lua generator
  with the project's style and a `mode.yaml` generator; English and
  Portuguese; Domination and Hold-All Domination as example projects whose
  generated files pass every YAML test of the hand-written modes and give
  the same manifests; 15 browser tests (`python3 tools/docker_editor.py`, CI
  job `editor`) and 6 plain tests in `tools/check.sh`. Decisions P5A-1 to
  P5A-7. AC-1, AC-2, AC-3 met.
- [x] **Plan phase 2, the editor and the simulator (2026-10-22), in software:**
  the editor's *Test in the simulator* (with a number of boxes) sends the
  generated files to the simulator's new `POST /api/reload`, which loads them
  in the core first (on an error the running game goes on) and starts the
  game; the simulator's page, in its own tab, shows it, now with a *Field
  controller* panel for `field.lua` (which the web view already ran, but did
  not show); errors on loading and while the game runs come back to the
  editor's problems list and onto the blocks they come from (a line-to-block
  map from Blockly's statement prefix). Same server rules (local Host, JSON
  only, CSP `'self'`), 1 MB at most. 7 new simulator tests, 3 new browser
  tests (18 in all). Decisions P5B-1 to P5B-7.
- [x] **Plan phase 3, the editor's remaining blocks (2026-10-22), in software:**
  *Places* (geo distances and zones, a position's values), *GM commands*
  (`commands:` and a `cmd.mode` handler per name), the controller sending a
  mode command, several roles with their own inputs and `needed`, the kinds
  modifier and role package, the mode's screen files offered in the toolbox;
  a third example, Master and Satellites, passing all 8 of its mode's tests;
  24 browser tests. Decisions P5C-1 to P5C-7.
- [x] **Plan phase 4, mode packages and signing (2026-10-22), in software:** a
  canonical ustar archive of a mode folder, the manifest
  `atalaia-mode-package-v1` (id, version, kind, minimum tier, size, SHA-256)
  signed with Ed25519 as firmware releases, checks that fail closed,
  `tools/mode_package.py`, the registry index's JSON Schema, shared vectors;
  17 tests. AC-4 and AC-5 met. Decisions P5C-8 to P5C-13.
- [x] **Plan phase 5, the sandbox-escape battery (2026-10-22):** 43 escape
  attempts as box and controller scripts under ASan and UBSan (CI job
  `sandbox-escape`) and through the simulator; it found and closed two ways to
  run with the watchdog off (`__gc` finalizers, `xpcall`'s handler after the
  watchdog's error). AC-12 met. Decisions P5C-14 to P5C-16.
- [x] **Plan phase 6, signed packages in the controller (2026-10-22), in
  software:** upload a signed package or install one from the registry index
  (https, or a file for an offline field), verified with the controller's own
  mode keys and revocations, failing closed; kept with its archive and release
  (store schema 10); the console's *Presets* tab shows who signed each package,
  *not reviewed by the project*, revoked or untrusted keys. Decisions P5C-17 to
  P5C-21.
- [x] **The maintainer's P5R-8 planned (2026-10-22):** plan phase 13, *Missing
  modes from the GM console*: in the invite dialog, *Send missing modes*
  re-invites boxes that answered "no mode" with join key 16; each fetches the
  signed packages it lacks over Wi-Fi HTTPS pinned to the field CA (never
  LoRa), checks them with mode keys built into its firmware and the sandbox,
  keeps them on LittleFS (limits, the Reduced tier, rollback, removal), only
  between games. K10 amended for that path (ADR.md, "Note 2026-10-22: P5R-8").
  Design choices P5B-8 to P5B-17 (open; P5B-9, which keys a box trusts, is for
  the maintainer). Built since as 13a and 13b (below); on real boxes: HW3.
- [x] **Plan phase 13a, missing modes from the GM console: the controller,
  console and protocol (2026-10-22), in software:** join keys 16
  (`fetch_modes`) and 17 (`forget_modes`) in the Python codec and the shared
  vectors; the endpoints a box fetches a signed package from (no token, only a
  part of the live game's mode, only while it is ready) and reports to (an HMAC
  with the game key); what the controller offers boxes (`[modes] box_keys`, the
  keys built into their firmware) and why not; the start guard waiting while
  boxes fetch (`[modes] fetch_timeout_s`, *Stop waiting*); in the console,
  *Send missing modes* under a box that answered *no mode*, its progress, and
  the Boxes tab's *Modes fetched by boxes* with *Forget at its next invite*;
  the wire contract for the box (check order, refusal codes, the report,
  `node.modes_failed`, storage) in `protocol/mode-packages.md` with shared
  vectors for 13b's C (`box_checks`, `reports`). 13 controller tests, 1 browser
  test. Decisions P5D-1 to P5D-12 (open; P5D-3, P5D-6, P5D-11 for the
  maintainer). Bench fix (2026-10-23): a HELLO ends a fetch only with the
  reports that the box keeps every part; the HELLO a box says before
  `node.modes_failed` (P5E-8) no longer counts as success (P5D-14 to P5D-18,
  P5D-14 for the maintainer; 9 more controller tests, 1 more browser test).
- [x] **Plan phase 7, scenario blocks in the GM console (2026-10-22), in
  software:** the *Scenarios* tab's editor has a *Blocks* view beside its
  YAML: 30 blocks (the scenario, its texts, teams, parameters, boxes and
  players, objectives with who, when, how and what they give), in European
  Portuguese and English, by mouse, touch or keyboard, at phone width. The
  YAML stays the editor's text: the blocks write it on each change and the
  controller reads it for them (`manifest` in the check's answer), checks,
  compiles and installs it as before; its problems are outlined on their
  blocks, with *Show*. The blocks refuse a manifest they cannot hold as it is
  rather than rewrite it. Blockly 13.3.0 vendored in the console (the mode
  editor's bytes), loaded on demand and precached for offline use; the CSP
  allows only the SHA-256 of Blockly's two stylesheets, no `'unsafe-inline'`.
  The round trip of every scenario example (2 hand-written manifests, the
  console's example, 5 valid vectors) compiles to the hand-written packages
  byte for byte. 7 browser tests, 3 plain ones. Decisions P5F-1 to P5F-12
  (open; P5F-2, P5F-4, P5F-5 for the maintainer).

- [x] **Plan phase 13b, the box's side of missing modes (2026-10-22), in
  software (host-tested; on real boxes in HW3):** a join with key 16 whose
  mode the box lacks (with keys 13 and 14 and a mode key built in,
  `CONFIG_ATALAIA_MODE_KEYS`) makes the Field Box fetch each missing part over
  the field Wi-Fi and HTTPS pinned to the field CA, check it in the contract's
  order (release, Ed25519 with its own keys, kind, tier, built-in, 256 KiB,
  room, the archive hashed before it is read and in its canonical form, the
  script and screens in the sandbox, the composed game), keep it on LittleFS
  (8 packages, 512 KiB, least recently used dropped, commits by renames,
  re-verified at boot), report each part (HMAC) and only then say HELLO; a
  failure without HTTPS goes over LoRa as `node.modes_failed` (id 53) and the
  box is free again; key 17 forgets. The core's join codec reads keys 16 and
  17. Decisions P5E-1 to P5E-14. Binary +16 KB (0.9 %), static RAM +1 KB.
- [x] **Plan phase 13b end to end against the real controller (2026-11-02),
  in software:** the field CA pin moved out of `fw_update_esp.c` into the
  platform-free `main/field_ca_pin.c` (mbedTLS 2.28 or 3.x), which the Field
  Box's HTTPS and the C host box's (`test/box_host/box_host_https.c`, mbedTLS
  sockets standing for esp_http_client) both attach. `box_host --mode-source
  https` runs the firmware's own `mode_fetch.c` over it to the join's address
  (key 14), trusting only the join's field CA (key 13), and posts the reports
  to the controller; `--mode-source DIR` is unchanged.
  `controller/tests/test_box_mode_fetch_e2e.py` starts the controller as `run`
  builds it (the field CA made on first start, uvicorn on its TLS port, the C
  host modem), uploads a package signed with the test registry key, and the
  box fetches, verifies, keeps and reports it, then plays; refused: a join
  pinning another CA (`unreachable`, said over LoRa), a package signed by a key
  the box lacks (`bad_signature`), an archive changed after signing
  (`bad_hash`). Decisions MFH-1 to MFH-7.
- [x] **Plan phase 8, the registry repository's template (2026-10-22), in
  software:** `registry/template/`, the `atalaia-modes` repository's files
  (an empty index, keys and revocations, sources in `modes/`, REUSE, CODEOWNERS,
  pull request and issue templates) with its CI (`registry-lint`: the JSON
  Schemas, `tools/registry_check.py lint` and REUSE; `registry-test`: each
  mode's tests in the simulator; `sandbox-escape`: the core's battery; then
  publishing to GitHub Pages), on this repository's tools at a pinned ref.
  Packages live beside the index; each mode's newest source must pack to
  exactly its signed archive; the verified badge is a second signature, by the
  project's registry key, over the same archive. `registry/tests/` runs every
  check step of that workflow on a sample submission signed with throwaway keys
  (CI job `registry-template`, `tools/check.sh`): 18 tests. AC-6 met in this
  repository's template. Decisions P5G-1 to P5G-11.
- [x] **Plan phase 9, the community processes (2026-10-22):**
  `CONTRIBUTING.md` "Submitting a community mode"; `docs/community/` (how the
  registry works, the review checklist as amended and the badge's criteria,
  mode keys and their revocation, moderation); the draft RFC
  `docs/rfcs/0000-mode-packages-and-registry.md` for version 1 of the package
  format, the manifest and the index. AC-11 met. Decisions P5G-12 to P5G-14
  (open; P5G-2, P5G-3, P5G-8, P5G-9, P5G-12, P5G-13 and P5G-14 for the
  maintainer: governance, who holds the keys, moderation, licensing).
- [x] **Leftover of plan phases 3-6: the editor makes the package (2026-10-22),
  in software:** *Make the package* in the mode editor downloads the canonical,
  unsigned archive of the mode it edits (`<id>-<version>.tar`: `mode.yaml`,
  `node.lua`, `field.lua` when there is one, the Mode tab's screens), made in
  the page by `editor/package.js` and byte for byte what `tools/mode_package.py
  pack` makes of the same files (proved in Chromium against the Python packer
  for the shared vectors, all 14 built-in modes, the three examples and 18 edge
  cases); it shows the manifest a mode key will sign (size, SHA-256) and the
  exact `sign` and `verify` commands. Signing stays offline on the command line;
  no key reaches the page or the simulator; the CSP is unchanged. Refused, with
  the reason, while the generator lists problems or for a bad version, licence
  or size. 5 new browser tests (30 in all). Decisions P5I-1 to P5I-6 (open;
  P5I-1, where the archive is made, and P5I-3, how to sign, for the maintainer).
- [x] **Plan phase 10, German (2026-10-22), in software:** German in the
  project page (`/de/`), the GM console, the mode editor (with Blockly's own
  German), the app and the Field Box's screens (join key 15 `de`; the fonts
  gain Ä Ö Ü ä ö ü ß, +9.2 KB; older firmware shows English);
  `tools/i18n_check.py` checks every part against English in `tools/check.sh`
  (a missing German key shows English and is only a warning; the project page
  must stay complete); `docs/translations/` (process, glossary, status).
  Drafted by an AI model, **not yet reviewed by a native-speaking player**
  (`docs/translations/status.yaml`). AC-7 met in software. Decisions P5H-1 to
  P5H-11 (open; P5H-5, P5H-10 and P5H-11 for the maintainer).
- [x] **Plan phase 12, build guides for the other node types (2026-10-22), as
  text:** `hardware/satellite/BUILD.md` (the Field Box's board and firmware
  with two or three team buttons, the LED ring and the board's OLED; plays the
  games a field controller invites it into), `hardware/io-pod/BUILD.md` (the
  Field Box's parts without the TFT, plus the enclosure switch on GPIO 47; the
  pod firmware from `build-pod`) and `hardware/target-addon/BUILD.md` (what is
  decided and what is not: **not buildable yet**), with photo placeholders and
  safety notes (cells, enclosures, hits); the project page's new build page
  (`/montagem/`, `/en/build-guides/`, `/de/bauen/`), in the header; every pin of the
  guides and the page checked against the Kconfig defaults by
  `tools/check_wiring.py`. No guide followed on real hardware yet. AC-10 met in
  text. Decisions P5J-1 to P5J-14 (open; P5J-2, P5J-4, P5J-7, P5J-8, P5J-9 and
  P5J-11 for the maintainer).
- [x] **Plan phase 11, Traditional Chinese as written in Taiwan (2026-10-22), in
  software:** `zh-tw` in the project page (`/zh-tw/`), the GM console, the mode
  editor (with Blockly's own `zh-hant`), the app (Android's CJK font; test fonts
  for the goldens) and the Field Box's screens (join key 15 `zh-tw`, no
  protocol change; older firmware shows English). The box's fonts carry exactly
  the 153 letters of its Chinese texts (17 at 48 px), from Noto Sans TC, checked
  by `tools/gen_box_fonts.py --check` and by every reference screen's letters
  against their own font; the fonts are now compressed, so the Field Box image
  is 0x1bf220, 1 KB more than before (13 % free; uncompressed the letters cost
  117 KB). 43 `_zh-tw` reference images, each looked at; the 14 px OLED lines
  are dense (P5K-4). Drafted by an AI model, **not yet reviewed by a
  native-speaking player**. Decisions P5K-1 to P5K-12 (open; P5K-3, P5K-4,
  P5K-5, P5K-7, P5K-11 and P5K-12 for the maintainer).

## Refresh 2026-10-22: what changed

| Change | Why | Decisions | Files |
|--------|-----|-----------|-------|
| Plan re-cut into small plan phases in build order (1-12, HW1-HW3) | Old phases A-D were large and partly blocked; phases 2-4 removed most blocks | P5R-1 | PLAN.md |
| The mode editor is a page of the simulator; the console gets a block view of its scenario builder later | A box runs only built-in scripts (K10): what a GM can install at the field is a scenario | P5R-2 | ADR.md (P5-2), PLAN.md 1, 7 |
| Field-script blocks now, with today's API; Blockly 13.3.0 vendored; one blocks file and one generator file | The field API shipped in phase 2; Blockly 13 is current and drops jsdom; no build step | P5R-3, P5R-4 | ADR.md (P5-1), PLAN.md 1 |
| `POST /api/reload` needs `field.lua` in the web view | The web view runs node scripts only | P5R-5 | ADR.md (P5-2), PLAN.md 2 |
| Editor tests in Chromium (the generator is JavaScript) | The dev image has no JavaScript runtime; the console's image has Playwright | P5R-6 | PLAN.md |
| Mode packages signed like firmware releases (text manifest with id and version, Ed25519, release-style key ids, shared vectors) | One scheme and one set of tools instead of two | P5R-7 | ADR.md (P5-4), PLAN.md 4 |
| Registry packages are controller packages (scenarios, field scripts) or proposals for `modes/` | K10; boxes do not load scripts at run time | P5R-8 (for the maintainer) | ADR.md (P5-3) |
| Registry tools in this repository first; the repository from a template, with the maintainer | P5-3 (confirmed: not yet) | P5R-9 | ADR.md (P5-3), PLAN.md 8 |
| German first, then Traditional Chinese (Taiwan) | The maintainer's choice (P5-1); German needs no new glyphs on the box | P5R-10 (for the maintainer) | ADR.md (P5-7), PLAN.md 10, 11 |
| Each language domain keeps its format; modes translate in `mode.yaml`; the box's texts are a runtime table | As built (P4R22, BN-14) | P5R-11 | ADR.md (P5-7) |
| Review checklist and sandbox battery as built | `i18n:` in `mode.yaml`; the core already tests its sandbox | P5R-12, P5R-13 | ADR.md (P5-8), PLAN.md 5 |
| Build guides: the Field Box's exists; the others remain | `hardware/field-box/BUILD.md` | P5R-14 | PLAN.md 12 |

## Plan summary (order to implement)

| # | Plan phase | Software now / hardware | Status |
|---|------------|-------------------------|--------|
| 1 | Visual mode editor | Software | **Built 2026-10-22** |
| 2 | Editor and simulator (`field.lua` in the web view, reload, Test) | Software | **Built 2026-10-22** |
| 3 | Editor completeness (geo, commands, roles, kinds) | Software | **Built 2026-10-22** |
| 4 | Mode packages and signing | Software | **Built 2026-10-22** |
| 5 | Sandbox-escape battery | Software | **Built 2026-10-22** |
| 6 | Signed packages in the controller | Software | **Built 2026-10-22** |
| 13 | Missing modes from the GM console (P5R-8; built after 6) | Software (box side host-tested); real boxes: HW3 | **Built in software 2026-10-22** (13a the controller, 13b the box; real boxes: HW3) |
| 7 | Scenario blocks in the console | Software | **Built 2026-10-22** |
| 8 | Registry repository template | Software; publishing needs the maintainer | **Built 2026-10-22**; the repository `atalaia-modes` was created 2026-10-26 (with its public page); the project's registry key is still the maintainer's |
| 9 | Community processes | Software | **Built 2026-10-22** |
| 10 | German | Software (after P5R-10) | **Built 2026-10-22** (AI-drafted, review pending) |
| 11 | Traditional Chinese (Taiwan) | Software | **Built 2026-10-22** (AI-drafted, review pending) |
| 12 | Build guides for other node types | Software | **Built 2026-10-22** (text; photos: HW2) |
| HW1 | Carrier PCB | Needs hardware | |
| HW2 | Build guide photos | Needs hardware | |
| HW3 | Community content on the field | Needs hardware | |

## Dependencies

| Dependency | Phase | Status | Impact |
|-----------|-------|--------|--------|
| Script API (`script_api.c`) | 0, 2, 4 | Done | The editor's blocks map to it |
| Field API (`state.field{}`, `field.*`) | 2 | Done | Field blocks built in plan phase 1 |
| Simulator web view | 0 | Done; `field.lua` shown and reloads from the editor (plan phase 2) | -- |
| Mode uploads on the controller | 2 | Done (`POST /api/v1/modes`) | Plan phase 6 |
| Scenario compiler and console builder | 4 | Done | Plan phase 7 |
| Firmware release signing | 4 | Done | Plan phase 4 reuses it; plan phase 13 reuses its trust and HTTPS path |
| Re-invites and the invite dialog | 4 | Done | Plan phase 13's *Send missing modes* step |
| Field Box hardware | 1 | Boards on the bench; no built box | HW1-HW3 |

## Risks

| Risk | Level | Mitigation |
|------|-------|------------|
| A Blockly upgrade breaks blocks or output | Medium | Pinned and vendored with checksums; the round trip and unit tests in CI (`editor`) |
| A script API change breaks the editor | Medium | The round trip runs the examples against the hand-written modes' tests |
| Registry signing key compromise | Low | Revocation list; one scheme with the firmware's, reviewed once |
| Sandbox escape via a community script | Low (Medium once plan phase 13 ships) | Plan phase 5's battery in the core's CI (built; it closed two watchdog escapes, P5C-15); boxes run built-in scripts and only signed packages checked with keys in their firmware (P5B-9, P5B-14) |
| Carrier PCB layout errors | Medium | Perfboard first, KiCad DRC/ERC in CI |
| Language key drift | Medium | A parity test per domain; `tools/i18n_check.py` in plan phase 10 |

## Acceptance criteria

| # | Criterion | Status |
|---|-----------|--------|
| AC-1 | The editor generates `node.lua` (and `field.lua`) that passes simulator tests | **Met in software (2026-10-22)** |
| AC-2 | Generated Lua is readable and hand-editable | **Met (2026-10-22)** |
| AC-3 | The editor ships in English and Portuguese | **Met (2026-10-22)** |
| AC-4 | Registry index format defined and documented | **Met in software (2026-10-22)**: `registry/schema/index.schema.json`, `protocol/mode-packages.md` |
| AC-5 | Mode packages are Ed25519-signed and verifiable | **Met in software (2026-10-22)**: `tools/mode_package.py`, `protocol/vectors/mode_package.json` |
| AC-6 | Registry CI runs mode tests and checks licences | **Met in this repository's template (2026-10-22)**: CI job `registry-template` runs the template's workflow on a sample submission; in `atalaia-modes` once the maintainer creates it |
| AC-7 | A language beyond en/pt on the site | **Met in software (2026-10-22)**: `/de/`, review pending (P5H-5) |
| AC-8 | Built-in modes carry en and pt texts | **Met differently**: `mode.yaml` `i18n:` (P4R22) |
| AC-9 | Carrier PCB schematic passes KiCad ERC | Pending (needs hardware) |
| AC-10 | Build guides for the Field Box and the Satellite | **Met in text (2026-10-22)**: the Satellite's (and the I/O pod's and target addon's) beside the Field Box's, on the project page in pt, en, de; photos with HW2 |
| AC-11 | CONTRIBUTING.md documents mode submission | **Met (2026-10-22)**: "Submitting a community mode", `docs/community/` |
| AC-12 | CI includes a sandbox-escape job | **Met (2026-10-22)**: CI job `sandbox-escape`, `core/tests/test_sandbox_escape.c` under ASan and UBSan |
| AC-13 | (new, P5R-8) A box gets a signed mode it lacks from its controller between games, checks and plays it | Pending (plan phase 13, HW3) |

## Verification of plan phase 1 (2026-10-22)

| Command | Result |
|---------|--------|
| `docker run --rm -v "$PWD:/src" atalaia-dev sh -c "BUILD=/tmp/c sh tools/check.sh"` (clean build folder) | See the coordinator's commit for the final run |
| `python3 tools/docker_editor.py` | 15 browser tests, OK |
| `reuse lint` | See the commit |

## Verification of plan phase 2 (2026-10-22)

| Command | Result |
|---------|--------|
| `docker run --rm -v "$PWD:/src" atalaia-dev sh -c "BUILD=/tmp/c sh tools/check.sh"` (clean build folder) | See the coordinator's commit for the final run |
| `python3 tools/docker_editor.py` | 18 browser tests, OK |
| `python3 -m unittest tests.test_live` (in `simulator/`, also in `check.sh`) | 18 tests, OK |

## Verification of plan phase 7 (2026-10-22)

| Command | Result |
|---------|--------|
| `docker run --rm -v "$PWD:/src" -w /src -e BUILD=/tmp/c atalaia-dev sh tools/check.sh` | exit 0 (simulator 337, controller 611, server's shared tests 92, OK) |
| `python3 tools/docker_console.py` | 54 browser tests, OK (7 new in `test_scenario_blocks.py`) |
| `python3 tools/docker_editor.py` | 24 browser tests, OK (the mode editor unchanged) |
| `reuse lint` (a copy without build output) | compliant |

## Verification of the editor's package (2026-10-22)

| Command | Result |
|---------|--------|
| `python3 tools/docker_editor.py` | 30 browser tests, OK (5 new: the shared vectors, every built-in mode, refusals alike, the three examples through the button with `sign` and `verify` run as shown, refusals in the page); a mutation of the header (mode `0640`) fails 25 subtests |
| `docker run --rm -v "$PWD:/src" -w /src -e BUILD=/tmp/c atalaia-dev sh tools/check.sh` | exit 0 (simulator 344, controller 629, server's shared tests 92, registry template 18, OK; `i18n_check`: editor 241/241 in en, pt and de; `build_site --check` OK) |
| `reuse lint` (a copy without build output) | compliant (1854 files) |

## Verification of the fetch over HTTPS (2026-11-02)

| Command | Result |
|---------|--------|
| `docker run --rm -v "$PWD:/src" -w /src atalaia-dev:verify sh -c "BUILD=/tmp/c sh tools/check.sh"` | exit 0, 0 compiler warnings (controller 1143 tests, 1 skipped, OK; the 4 new in `test_box_mode_fetch_e2e.py`) |
| `test_box_mode_fetch_e2e` alone, 25 times in a row | 25 of 25 OK (about 3.3 s a run) |
| `python3 tools/docker_fw.py test` | 5 of 5 OK, 0 warnings |
| `python3 tools/docker_fw.py build` (clean) | exit 0, 0 warnings; 0x20fa10 bytes, 48 % of the slot free |

## Next steps

For the maintainer first: the expansion port design ([draft RFC](../rfcs/0000-expansion-port.md), decisions EXP-1 to EXP-38): the I2C port and protocol for the target addon and other inputs, and a single-GPIO RC-servo "simple output" as the preferred way to switch sirens, strobes and smoke remotes (EXP-31, decided by the maintainer), with its increments and open questions; implementation starts once it is approved.

1. Plan phase 13 on real boxes (HW3): a Field Box with a mode key built in
   fetching from the bench controller over the field Wi-Fi, by the controller's
   IP address (the firmware's mbedTLS 3.6.2 checks the certificate's address
   names; the host test uses `localhost`, MFH-4). The software half is done
   (2026-11-02, MFH-1 to MFH-7): the C host box fetches from the real
   controller over HTTPS (`box_host --mode-keys HEX --mode-source https`),
   with the firmware's own fetch and field CA pin
   (`controller/tests/test_box_mode_fetch_e2e.py`).
2. The review of the German by German-speaking players (P5H-5); mode names and
   screens in German (P5H-7). Plan phase 7 is built;
   its P5F-2 (the CSP's two style hashes instead of `'unsafe-inline'`), P5F-4
   (refuse rather than rewrite; comments go once the blocks change the YAML)
   and P5F-5 (the block set, typed references) are for the maintainer. Plan
   phases 8 and 9 are built: creating `atalaia-modes` from
   `registry/template/` was done on 2026-10-26 (P5-3, P5R-9; steps 1 to 3 and 5
   of `docs/community/registry.md`, "Creating the repository"; step 4, the
   project's registry keys, is done too: root d9521a79030ce544 kept offline by
   the maintainer and CI 7275108d2e3fe583, both in `atalaia-modes`'s
   `keys/project/`). Still waiting for the maintainer: P5G-2,
   P5G-3, P5G-8, P5G-9, P5G-12 (accepting the RFC), P5G-13 and P5G-14.
3. Left from plan phases 3-6, small (the editor making the package itself is
   built, P5I-1 to P5I-6, signing staying offline):
   `protocol/vectors/controller_api.json`
   has contract cases for the mode-package endpoints (`/api/v1/mode-packages`,
   `/api/v1/mode-fetch`, `/api/v1/mode-packages/report`); P5C-15 (the two sandbox
   fixes) and P5C-18 (packages stay installed when their key is revoked) were
   accepted by the maintainer; the other decisions of P5C-1 to P5C-21 are open
   for the maintainer's review.
4. Plan phase 12 is built as text: the first Satellite and the first I/O pod
   built from their guides (photos in place of the placeholders, the
   **Verify at the first build** items answered: runtime, the pod's current from
   a phone, the enclosures) are HW2. For the maintainer: P5J-2 (the Satellite is
   the Field Box's firmware with fewer parts), P5J-4 (no piezo buzzer without a
   firmware change), P5J-7 (no separate siren on the pod), P5J-8 (a phone
   charging the pod's cell), P5J-9 (the target addon's open questions: the bus
   voltage, and no free GPIO on a Field Box for its interrupt line) and P5J-11
   (the page's address and words). P5J-9 was answered on 2026-10-23 ("fix in
   3.3 V"): built as P5J-15 to P5J-21 (open): the port is 3.3 V only, polled
   every 20 ms with no interrupt line and no pin change, with a polling driver
   (a stub with host tests, not called yet) in the firmware; the addon itself
   is still not buildable (its processor, firmware, address and sensor: HW2).

## Verification of plan phase 12 (2026-10-22)

| Command | Result |
|---------|--------|
| `docker run --rm -v "$PWD:/src" -w /src -e BUILD=/tmp/c atalaia-dev sh tools/check.sh` | see the report of the commit |
| `python3 tools/check_wiring.py` | OK; mutated pins in each guide and in the page fail as expected |
| `python3 tools/build_site.py --check` | OK (18 pages, the new page in three languages) |
| Every page in Chromium at 320, 360 and 1200 px | no horizontal scroll (the German main page's hero fixed, P5J-14) |

## A scenario's `lang`: German and Traditional Chinese (2026-10-28, decision PKB-9)

`core/scenario/manifest.lua` lists `pt`, `en`, `de` and `zh-tw` for a scenario's `lang` (the objectives package's templates have had `de` and `zh-tw` since P5H-12); the validator, the compiler, the shared vectors (`scenario.json`: two new valid cases; `scenario_compile.json` regenerated), the console's scenario blocks (a four-language dropdown and the four consoles' texts), `controller/README.md` and `modes/README.md` follow. Old manifests are unchanged. Not done: texts of a scenario in German or Chinese (`i18n.de`, `i18n.zh-tw`: the block editor has no blocks for them, so the format keeps `i18n.pt` only and a German or Chinese box shows the objective's English name), and the box shows a Chinese name only with letters its font has.

Update (2026-10-28, decision SCL-1, software and browser tests): the "not done" above is done. A manifest's `i18n` takes `pt`, `de` and `zh-tw` (the validator no longer answers `bad_lang`), the scenario blocks in the GM console have a *name in German* and *in Traditional Chinese* field for the scenario and each objective, and a scenario whose `lang` is `de` or `zh-tw` sends the boxes those names. The box still draws only letters its font has (the console warns, GLY-1). Also built for the community layer: the architecture diagrams as a project-page section in four languages (SITEARCH-1 to SITEARCH-6) and releases prepared by a pull request (PREP-1 to PREP-8).

## The box's boot splash is a build asset (2026-10-29, decisions LOGO-5 to LOGO-7)

The Field Box shows only the Atalaia tower (no field logo is fetched). A builder who wants another splash replaces `firmware/esp32/assets/splash.pgm` or points `CONFIG_ATALAIA_SPLASH_LOGO` at their own file (steps in the firmware guide, section 4, English and Portuguese); the project's release images always carry the tower and the release build checks it. Built and host-tested, not flashed on a board.

## CI and release hardening from the security review (2026-10-30, SR-60 to SR-69, SR-90 to SR-94)

Every action pinned by commit SHA (version in a comment), the ESP-IDF image by digest (also in `tools/docker_fw.py` and the registry template), every `pip install` in CI from a requirements file compiled with hashes and installed with `--require-hashes --no-deps --only-binary :all:` (`reuse` from its source archive), `controller/requirements.txt` a hash-pinned lock, Dependabot weekly for actions, pip and pub, `persist-credentials: false` on checkouts, `permissions: contents: read` on `ci.yml`, and the release workflow's signing job in the environment `release`, failing unless the tag's commit is on `origin/main`. The CBOR decoders' limits are tested on hostile input. The maintainer still has to create the protected `release` environment, move the two signing secrets into it, add a `v*` tag ruleset and review the "create and approve pull requests" setting (steps in `firmware/esp32/docs/RELEASE_SIGNING.md`); the workflows were not run on a hosted runner here.

## The project page, 2026-10-31 to 2026-11-01 (FB-1 to FB-8, FBM-1 to FBM-4, MSC-1 to MSC-5, MSF-1 to MSF-3, TI-1 to TI-6)

- **Real Field Box footage.** The build page and the main page show the first bench build (2026-10-31 photo) and an 11 s muted clip from 2026-11-01 with the new TFT screens (hold bar, live held time, corner points), plus a second photo of the "PRONTA" screen with the tower. The modes page has a 17.8 s clip of a Master and Satellites test game on four boxes; its caption says the run found three screen problems, that they are fixed in the firmware, and that the clip still shows the old screens. In pt, en, de and zh-tw; the clips honour reduced motion (a pause button).
- **Roadmap texts** (phases 1 and 2, in the four languages) now list the big screen's hold bar, held time and corner points, the screens of the three other modes, the boot splash, the I2C fix (host tests; bench test still to do), the screen-text size check, the singular counts, the radio modem guide and the controllers' lost-epoch draw, each with what has and has not been tried.
- **The site browser test cannot skip silently any more (TI-1 to TI-6).** `python3 tools/docker_site_browser.py` runs `tools/site_browser_test.py` in an image with Playwright 1.49.0 pinned by hash; a missing Playwright is a failure, and only `ATALAIA_SKIP_SITE_BROWSER=1` skips. The old route had printed "OK (skipped=1)".

## The documentation's front door (2026-11-06)

README, manuals index, quick start, player and marshal manuals (en, pt) and the project page (five languages) brought up to date with v0.8.0 (the release-key change) and with what is on `main` for v0.9.0 (stuck-box recovery, `@wifi` quoting, the setup page's Wi-Fi rules), marked as not released and not yet on hardware. The README's long status text now lives only in each phase's STATUS.md. Part of the documentation pass of 2026-11-06 (four parallel changes; this one owns the front door).

## The expansion port, increment 1: the protocol (2026-11-03, EXPI1-1 to EXPI1-12)

The draft RFC "The expansion port" (on its own pull request; the maintainer took its recommended answers to Q1-Q16 and decided EXP-31, two output paths with the single-GPIO simple output preferred, on 2026-11-03) replaces the target addon's open items (P5J-9, P5J-21) and the draft report of P5J-19. Its increment 1 is built: the capability type ids (`protocol/schema/capabilities.yaml`, generated into C, Python and Dart; `hit` 10, `output` 11), the register protocol (`protocol/expansion-port.md`: addresses 0x58-0x5F, IDENT, CHANNEL, STATUS, COMMAND, CRC-8 over the address byte, the 1.5 s output lease), its vectors (`protocol/vectors/expansion.json`, written by `tools/expansion_vectors.py`, checked by the Python reference model and the box's C CRC-8), CMD output (opcode 12, RFC 0001 Amendment 26, `cmd.json`), the `output` capability with the simple output's no-feedback flag and a second `hit` channel (draft RFC 0000 Amendment 5, `capability_proxy.yaml`, `hello.json`), the events `node.modules`, `node.module_lost` and `output.switched` (57-59), and the design specification's sections 6, 7 and 17. Nothing sends or handles any of it yet: the simple output and the box's output layer (increment 2), the controllers and console (3) and the port driver and modules (6-8) come next; the simple output's signal, pins and socket wait for the maintainer's Q17-Q21.

## The expansion port, increment 2: the simple output and the box's output layer (2026-11-03, EXPI2-1 to EXPI2-16)

The maintainer approved the RFC's open questions Q1-Q21 on 2026-11-03 (the simple output's RMT bursts, its pins, the M8 socket, the switch powered from the load's side, generic switches only after their bench check). Increment 2 is built in the firmware: the platform-free output layer (`firmware/esp32/main/outputs.c`: settings enabled at the box with the admin PIN, max on, the 500 ms floor, the game-state rules with the end's 10 s grace, a script's 2 starts a second, `output.switched`), the simple output's burst scheduler (`simple_out.c`, RMT on the ESP32 in `simple_out_esp.c`: 25 frames queued at most, renewed every 200 ms), `CONFIG_ATALAIA_SIMPLE_OUT` / `_PIN` / `_OUT2` / `_OUT2_PIN` (46 on a V4.3, 5 on a V4.2, 45 only without the buzzer), CMD 12 handled by the box, scripts' `cap(fn)` calls, HELLO's capabilities filled, `node.modules` with the simple outputs, the picker's **Outputs** screen (four languages) and the serial console's `@output`, `box_host --simple-out`, `check_wiring.py`, the build guides' section, BRING_UP's bench tests 11-13 and the manuals. Next: the controllers and the console (increment 3: CMD 12 from field scripts and the GM, `modules` in the node list, the capability start check, the outputs panel), then the modes (4) and scenario triggers (5). Not tried on hardware.

## The expansion port, increment 3: the controllers and the console (2026-11-03, EXPI3-1 to EXPI3-14)

Increment 3 is built on both controllers (the Pi's and the phone's, the same answers checked by a new contract case in `protocol/vectors/controller_api.json`) and the GM console: each box's last `node.modules` in `GET /api/v1/nodes` as `modules` (each with `feedback`; a module `node.module_lost` names marked lost); the capability start check (`missing_caps` blocks the start unless forced, optional capabilities lacking are warnings, each simple output "not checked"; the role names `team_input` and `team_display` met by the types `protocol/schema/capabilities.yaml` now lists under `role_names`; boxes whose HELLO lists no known type not checked); the GM output API (`POST /api/v1/games/{id}/nodes/{node}/output`, `POST /api/v1/games/{id}/outputs/off`, GM token only, on only while the game runs, 5 s by default) and `field.send(node, "output", {...})`, both CMD 12 with the controller's own `src`, at most one start a box every 2 s and off never held back; the remote GM's `outputs_off` (off only, `protocol/sync.md`); the console's module chips, the start panel's messages and the **Outputs** panel, and the three events in words, in pt, en, de and zh-TW; the app's player feed hides the three events. End to end: `controller/tests/test_box_e2e.py` drives `box_host --simple-out` through the GM's output API. Not done here: the "outputs disabled on this box" note (it needs a field the RFC does not put in increment 3), a role's `outputs:` list (increment 4), the site server page's button for `outputs_off`. Next: the modes (4) and scenario triggers (5). Not tried on hardware.

## The expansion port, increment 4: the modes (2026-11-03, EXPI4-1 to EXPI4-12)

Increment 4 is built: a role may name the output functions it switches in `outputs:` (1-8 of `siren`, `strobe`, `smoke`, `light`, `horn`, `out.1`-`out.9`, `siren.2` for a second; `output` must be in its `requires:` or `optional:`), checked by the simulator's validator (which the Pi uses for uploads) and the phone's (`controller_modes.dart`); the start check on both controllers adds the warning `outputs` for a box with outputs but none of those functions (a new contract case in `controller_api.json`), and the console's game form says which outputs a mode would switch (four languages). The first modes that use outputs: Bomb's optional `smoke_s` and `siren_s` (0-10 s) fire the box's `smoke` and `siren` from its `game.end` handler when the bomb exploded (the explosion ends the game, and the box allows outputs for 10 s after the end), and Master and Satellites' optional `siren_all_s` (1-600 s) pulses the master's `siren` from `field.lua` (CMD 12) when one team comes to hold every satellite. Both are off when left empty, so existing games, presets and joins are unchanged. The simulator models a box's outputs (`simulator/atalaia_sim/box_outputs.py`: on only while running, off at start, pause, end, halt and boot, the end's grace, max on, the 500 ms floor; `output.switched`; `field.send(node, "output", ...)` with the controller's 2 s gap), its tests take `outputs:` and `expect_output`, its web view draws each box's outputs, and the app's Dart mode runner does the same (`app/test/support/box_outputs.dart`), so the 9 new mode tests run on the real core in Python and in Dart. Not done here: the mode editor's blocks for outputs, the phone prop's outputs through the I/O pod (increment 9). Next: scenario triggers (5). Not tried on hardware.

## The expansion port, increment 5: scenario triggers (2026-11-03, EXPI5-1 to EXPI5-15)

A scenario manifest's optional `triggers:` list (EXP-25) is built in the core's scenario compiler (`core/scenario/`, so the Pi and the phone get it at once): each trigger's `when` (`completed`, every objective listed; `any_completed`, the first; `failed`; `game: start`; `game: end`) and `output` (a box of `nodes`, the output's function, `on`, `pulse`, `pattern` or `off`, `seconds` 1-600, at most 10 at the end, a pattern's `on_ms` and `off_ms` 500-10000) are checked with their own codes (`bad_when`, `bad_output`, `bad_capability`, `bad_act`, `bad_seconds`, `bad_pattern`, ...); the compiler writes `SCENARIO.triggers` only when there are some, so every other package is unchanged but for the runtime's new text; the runtime fires each trigger once a game through `field.send(node, "output", ...)` (CMD 12, `src: field`), tries again for 10 s what the controller's 2 s limit holds back, drops it on a pause, and leaves the start's outputs alone after a restart mid-game. Both controllers hold the outputs a field script switches after its own `game.end` (an objective with `effect.win`) until the end's CMD has gone, so they run within the box's 10 s grace. Shared cases in `protocol/vectors/scenario.json` and `scenario_compile.json` (checked by the Pi, the phone and the console's blocks); the GM console's **Triggers** blocks in pt, en, de and zh-TW, YAML round trip included. Not done here: the console's "Bomb would use" list and the start check's warning for a scenario's outputs (a role's `outputs:` is increment 4; a scenario's boxes run the objectives package's roles), the simulator's drawing of outputs (increment 4). Not tried on hardware.

## The expansion port, increment 9: the I/O pod (2026-11-04, EXPI9-1 to EXPI9-33)

The first half of increment 9 is built: the I/O pod's simple outputs and the phone prop that uses them. The pod firmware drives an RC relay switch's signal on **GPIO 33** (a second on **GPIO 1**, with or without the buzzer) with the Field Box's output layer and RMT bursts (`firmware/esp32/main/pod/pod_outputs.c` on `outputs.c`, `simple_out.c`, `simple_out_esp.c`; `CONFIG_ATALAIA_SIMPLE_OUT` and the new `ATALAIA_POD_OUT<n>_FUNCTION` / `_MAX_ON_S`, since a pod has no admin PIN: building the output in enables it; `python tools/docker_fw.py pod --simple-out=on|on2`). It lends each output over the capability proxy as `{"id": "siren", "type": "output", "feedback": false}` (CMDs `on`, `off`, `pulse`, `pattern`; IDENT still fits in 256 bytes by leaving out, in turn, the buttons' colours and the `feedback` flags, the version's build metadata, then the outputs one at a time, the last first: EXPI9-27), keeps the output layer's limits whatever the phone asks (the build's longest on, a change at most every 500 ms), switches only while a phone is on a link, and turns every output off at once when its last link goes and after 1.5 s without a frame from the phone while one is on (the phone pings the pod twice a second then). The app's prop shell maps a mode's `cap("siren")` calls and the controller's CMD 12 (`output`, now named so on the radio link too) to the pod's outputs with a box's rules (`app/lib/prop/prop_outputs.dart` on `box_outputs.dart`, moved from the tests into `lib/prop/` and shared with the mode runner): on only while the game runs and in the end's 10 s grace, off at its start, pause, end and a halted script, 30 s at most, a script's two starts a second; it sends `output.switched` (and `script.error` for the dropped starts) as a box does. New vectors: the pod's IDENT with a simple output (`pod_simple_output`) and the keepalive PING (`cmd_ping`) in `capability_proxy.yaml`. Host tests in `test_pod.c`; `pod_host --simple-out`; Dart tests on the model and against the host pod and modem (the mode's pulse, CMD 12 over the radio, a pause, the session's end, the lease); `check_wiring.py` checks the pod build's pins and the pod guide's table with the pod's defaults; the I/O pod build guide's new section 8.1 (en, pt) and the manuals (firmware, Field Box section 11, GM outputs; en, pt).

**The port half** (EXPI9-18 to EXPI9-26) is built too: the pod runs the box's port driver and its game glue (`expansion.c`, `expansion_box.c`) on its I2C bus, GPIO 17/18 (`firmware/esp32/main/pod/pod_port.c`, `CONFIG_ATALAIA_POD_PORT`, on by default), with a phone on a link in the game's place. A target module's hit channels are lent as `hit` (and `hit.2`, with their `channel`), armed by the phone (`app/lib/prop/prop_hits.dart`: a script's arm told to the pod only while the game runs, again after a new link) and forgotten by the pod when its last link goes; a hit reaches the mode only while the game runs. An output module's channels are lent as `output` without the `feedback` flag, only on a build with `CONFIG_ATALAIA_POD_MODULE_OUTPUTS` (`docker_fw.py pod --module-outputs=on`; a pod has no admin PIN), each at most `CONFIG_ATALAIA_POD_MODULE_MAX_ON_S` (30 s) and the module's own; the pod's driver holds the module's lease and its output layer turns them off when the phone's link goes or falls silent. **The gaps the first half found are closed**: the pod tells the phone a box's `node.modules` text and each output's longest on (the EVT `pod.modules`, draft RFC 0000 Amendment 7), which the phone sends to the controller as `node.modules` (and `node.module_lost` during a game), so a prop's outputs and modules show in the console's chips and **Outputs** panel, and the phone uses the pod's longest on instead of 30 s (EXPI9-19, EXPI9-21); both controllers relay a CMD naming `dest` 65535 to every Wi-Fi prop (EXPI9-20: they already sent every-node CMDs without `dest`, so **All outputs off** reached a Wi-Fi prop; a packet naming 65535 did not). IDENT keeps within 256 bytes with a new stage (the hit sensors after the outputs). **The outputs are trimmed one at a time** (EXPI9-23 answered, the coordinator's call; EXPI9-27 to EXPI9-33): when they do not all fit the pod leaves out the last first, logs which, and keeps each one it left out off and refused, out of `pod.modules`, until an IDENT lists it again (a target plugged in can take a lent output's room: it goes off at once). A pod with every part and an out4 module now lends one of the four channels (vector `pod_full_out4_trimmed`); with a target as well none fits (236 bytes before the outputs, 22 each), so a pod built for a module still leaves out parts it does not use (EXPI9-31, open: a protocol change for the fullest pod?). New vectors: IDENT `pod_port_modules`, EVT `pod_modules`, `pod_module_lost`; contract case `EXPI9 a phone prop on Wi-Fi` in `controller_api.json`. Tests: `test_pod.c` on the module core behind a fake bus, `pod_host --module`, Dart `prop_hits_test.dart` and `prop_pod_port_test.dart` against the host pod, the relay's 65535 in `test_prop_link.py` and `controller_props_test.dart`; the pod build 710,096 bytes with an output and the module outputs on, 0 warnings. The prop's HELLO, which listed no capability type (EXPI9-12, EXPI9-19), lists them since PROPC-1 (below). Not tried on hardware: the pod's port, a module on it and a phone together wait for the bench (the RFC's increment 12).

**The prop's capability types in the start check** (2026-11-04, PROPC-1 to PROPC-6, closing EXPI9-12): a phone prop's HELLO lists the capability type ids of what it gives a mode (`CapabilityMap.helloTypes` in `app/lib/prop/capability_mapper.dart`): the phone's screen (button, keypad, display, led), speaker, NFC and GPS, then what its pod lends in IDENT (its parts by type, `hit` while it lends a target, `output` while it lends an output); never the vibrator, the camera, the accelerometer or the pod's case and gauge. `PropSession` says them before its first HELLO and again, through `DualLink.updateCapabilities`, whenever they change: a pod's IDENT (a target plugged in or out), its link breaking, the person unlinking it; a radio through a pod linked again starts with them. Neither controller changed: their start check already takes any node whose HELLO lists a type, so a prop's required type it lacks blocks Start and an optional one or a role's `outputs:` warns, as for a box (contract cases `PROPC` in `controller_api.json`, on both). Tests: Dart `prop_hello_caps_test.dart` (a pod simulated at the transport, and the host pod with a target unplugged and plugged in again), `prop_logic_test.dart`, the radio HELLO's list in `prop_pod_session_test.dart`.

## The expansion port, increment 6: the port driver, the box's side (2026-11-04, EXPI6-1 to EXPI6-19)

Increment 6 is built in the firmware and tested on the host: the expansion port's driver (`firmware/esp32/main/expansion.c`, platform-free; the ESP32's bus in `expansion_esp.c` over `hal_esp_i2c`, so modules share the bus's health records and back-off) replaces the target addon's stub `target_addon.c` and its draft report (removed with its test). It finds modules at 0x58-0x5F (at boot `ALL_OFF` to every module before anything else; then each empty address probed every 2 s, one every 250 ms, so a module plugged in is found within 2 s; at most 4), reads and checks IDENT and every CHANNEL (a refused IDENT keeps the module out until its address's next probe, a refused channel is left unused), polls STATUS every 20 ms for a module with inputs and 250 ms for an output-only one (up to 4 reads while MORE), reports each event once with its time on the box's clock and acknowledges it (a lost ACK is acknowledged again, an event of a channel the box has not armed dropped), counts OVERFLOW, CMD_ERROR and LEASE_EXPIRED, handles FRESH (the IDENT read again: a different module is the old one lost, `bad_ident`, and the new one added), and drops a module after 25 failed reads in a row (a refused STATUS and a skipped poll count). Output channels keep a desired state reconciled with each STATUS (sent again with what is left, rounded up to 100 ms), the 1.5 s lease refreshed every 500 ms while one should be on, the module's max on, min off and a relay's 100 ms respected on the box's side, `ALL_OFF` for everything; an `out_backend_t` adapter lets the output layer of increment 2 drive a module's channel. Capability ids (`hit`, `hit.2`, the hint's function or `out.<n>`) and `node.modules`' entries are made by the driver. `firmware/esp32/test/test_expansion.c` checks every case of `protocol/vectors/expansion.json` (through `expansion_vectors.h` and the new generated `expansion_cases.h`), a C model of a module (`test/expansion_model.c`, which increment 7's module core replaces) against every command case and all seven timelines, and the driver against the model on a fake bus, including four timelines the driver writes byte for byte. Not done here: the game task calling the driver, hits to the script, `node.modules` and `node.module_lost` for modules, module channels in the output layer, `box_host --module` (increment 8). Not tried on hardware.

## The expansion port, increments 3-5: the leftovers (2026-11-04, EXPL-1 to EXPL-22)

Three of the four "Not done here" items of increments 3, 4 and 5 are built; the fourth needed a protocol change, was left open and is now built too (next paragraph). **Increment 4's mode editor blocks for outputs** (EXPL-1 to EXPL-4): *Box hardware* gets "switch output … pulse/on/off for … ms" (`cap("siren"):pulse(ms)`, `:on()`, `:on(ms)`, `:off()`) and "flash output …" (`:pattern(on_ms, off_ms, ms)`), and *Field* the same for one box from the controller (`field.send(node, "output", {...})`, `*` only with off), in pt, en, de and zh-TW; a function no role lists in its `outputs:` is a problem, so the Mode tab stays the one list. The Master and Satellites example now switches its siren with the field block, and its round trip passes the hand-written mode's siren tests. **Increment 5's "would use" list and start check for a scenario's outputs** (EXPL-5 to EXPL-8): the core's scenario compiler writes the functions the triggers switch on each box into the compiled `mode.yaml` (`scenario.outputs`, only with triggers), `GET /api/v1/modes` gives them as the scenario's `outputs`, the console's game form names them box by box, and both controllers' start checks treat them as the role's `outputs:` of the box named that way in the Join tab, with `output` optional (a new contract case in `controller_api.json`; the compiler's vectors changed only for the two trigger cases). **Increment 3's site server button for `outputs_off`** (EXPL-9 to EXPL-11): the Remote GM page's **All outputs off**, the field's GM only, in any state of the live game until it has ended, four languages. **Increment 3's "outputs disabled on this box" note is not built** (EXPL-12, open): a box leaves an output its admin has not enabled out of both its HELLO's capability types and its `node.modules` (`outputs_modules_text` skips it, HELLO lists `output` only while one is enabled), so a box with outputs fitted but none enabled looks like a box with none; carrying it needs a new field in `node.modules` or HELLO and the firmware to fill it, which was the maintainer's call (answered 2026-11-04: build it). Still not done: the phone prop's outputs through the I/O pod (increment 9), the simulator's drawing of a scenario's outputs. Not tried on hardware.

**The "outputs fitted, not enabled" note** (2026-11-04, EXPL-12 answered by the maintainer: "build it"; EXPL-13 to EXPL-19). A new standard event, `node.outputs_disabled` (60, normal; draft RFC 0000 "Phase 3 events, tags and pods" Amendment 6, `protocol/expansion-port.md` section 7): with each `node.modules` telling, a box with an output fitted names the ones its admin has not enabled, in `node.modules`' compact text (`g45:servo:horn`, the empty text when every one is enabled). It is an event of its own and not a key of `node.modules` because the decoders refuse an unknown data key: a 0.7.0 controller refuses event 60 alone and keeps the box's `node.modules`. The firmware's change is local (`outputs_disabled_text` in `outputs.c`, one `tell_outputs_disabled` call in `box_game.c`'s `tell_modules`, `box_host --simple-out FUNCTION[@GPIO],disabled`), so increment 8's rework of `node.modules` merges past it. Both controllers keep it as the node list's `outputs_disabled` (null until the box says) and add a start-check note, `outputs_disabled`, never a refusal or a warning, for a joined box whose role's `outputs:` (or its scenario's triggers) would switch one of them; a GM's output request for it is refused as before, with the reason (a new contract case in `controller_api.json`, an end-to-end test with the C host box). The console shows *horn · fitted, not enabled by the box's admin* under the box, the note in the start panel and the event in the feed, in pt, en, de and zh-TW; the GM and Field Box manuals (en, pt) say what to do. The simulator's `box_outputs.py` is unchanged: it models neither HELLO nor `node.modules`. Not tried on hardware. **Merged after increment 8** (EXPL-20 to EXPL-22): a module's output channels, disabled until the admin enables them (EXPI8-7), are in `node.outputs_disabled` too, as the module's entry with only those ids (`5c:out4/1.0.0:siren.2,smoke`), after the simple outputs and whole entries only within the 100 bytes (`expansion_box_disabled_text`, `box_game_disabled_text`); the event goes with each `node.modules` telling and again if its own text changes while `node.modules` does not (EXPL-21; the admin's settings are refused while the box is in a game, so a change arrives with the next game's HELLO). Tested on the host (`test_expansion_box.c`), end to end with `box_host --simple-out siren --module out4`, and in the shared contract case.

## The expansion port, increment 7: the module core (2026-11-04, EXPI7-1 to EXPI7-20)

The modules' side of the expansion protocol v1 is built as portable C in `firmware/module-core/` (a CMake library, `atalaia_module_core`, with no platform calls and no allocation), for the target module on pico-sdk (increment 8), the I2C output module (increment 11) and community modules. A module's firmware gives it the I2C target's four moments (address match, byte received, byte requested, stop), its millisecond clock, its input events and a regular tick; the core answers `IDENT`, `CHANNEL` and `STATUS`, takes or refuses each `COMMAND` (`CMD_ERROR`, the protocol's reasons; register pointers leave it alone), queues 16 events with a sequence number (`MORE`, `OVERFLOW`), keeps `FRESH` until `CLEAR_FRESH`, and switches the outputs under the lease (every output off and `LEASE_EXPIRED` when it runs out), each channel's max on and min off, the relay's 100 ms and the pattern floors, with every output off at power-up. Its host tests run every vector of `protocol/vectors/expansion.json` (through `module_core_vectors.h`, written by `tools/protogen.py`) and the state machine's edges, 915 checks, in a new CI job (warnings as errors, then ASan and UBSan) and in `tools/check.sh`. A relay is also refused within 100 ms of a pattern's on time ending, a little stricter than the Python reference model (no vector differs; the model can follow). Not done here: the box's port driver (increment 6, built alongside; its tests' C model of a module is to be replaced by this core once both are on `main`), any module's firmware on the core (increment 8). Not tried on hardware.

## The expansion port, increment 8: port integration and the target module (2026-11-04, EXPI8-1 to EXPI8-19)

The box runs its expansion port: `firmware/esp32/main/expansion_box.c` (platform-free) starts increment 6's driver at boot after the outputs and ticks it in the game task. Hits reach the mode's script as `hit.hit` while a game runs (with `channel` on a box with two hit channels), the script's `arm`/`disarm` are kept by capability id and applied only during a game, HELLO lists `hit`, `node.modules` joins the simple outputs' entries and the modules' and is resent whenever it changes, and a module lost during a game is `node.module_lost`. A module's output channels join the output layer after the simple outputs, disabled until enabled at the box (RAM only), named beside them (`siren.2`), and take their durations and patterns whole. `@modules` on the serial console; the Outputs screen names a module's channel `I2C 5c/2`. The port driver's tests run on increment 7's module core (`test/module_sim.c`, replacing the C model); `box_host --module` simulates modules on it, and `controller/tests/test_box_e2e.py` plays *Target Windows* with a target module end to end.

The target module's firmware is `firmware/target-module/` on pico-sdk 2.2.0 and the module core: the I2C target on GP4/GP5, the piezo on GP26 (a second plate on GP27) by DMA at 20 ksample/s, a peak detector with the box's `CONFIG` threshold and hold-off, address jumpers on GP2/GP3, `LOCATE` on an LED on GP14, 48 MHz, a watchdog. `tools/docker_module.py` builds its two UF2 files (one and two plates) and runs its host tests in a pinned image; CI's **Target module** job does the same, and releases carry the UF2 files as assets covered by `SHA256SUMS`, unsigned (a module is flashed over USB). The target addon and port guides (en, pt) now give the pins, the power entry, flashing and the box's log; BRING_UP has step 8c; the GM and Field Box manuals (en, pt) say how a GM uses targets. The simulator's model follows the core's stricter relay rule (EXPI7-11). EXP-14 now says each empty address is probed every 2 s, as the maintainer answered EXPI6-4.

Checked: the firmware host tests (with the new `test_expansion_box.c`), the Field Box build (2,187,200 bytes, 48 % of the slot free, no warnings), the module core's and the target module's host tests, both UF2 builds, the box end-to-end tests, the simulator's expansion tests, `protogen.py --check`, `check_wiring.py`, `i18n_check.py`, clang-format, `actionlint`. **Not yet on hardware**: the module's current and 3V3, the strength scale, threshold and hold-off on real plates (bench tests 4 and 8), the port's tests 3 and 6. *Target Windows* becomes a Field Box preset once bench-tested (EXPI8-14). Still open for the next increments: the I/O pod's port (9), the I2C output module (11).

## The expansion port, increment 10: the port guides (2026-11-04, EXPI10-1 to EXPI10-14)

The expansion port's build guide is written, in English and Portuguese (`hardware/expansion-port/BUILD.md`, `BUILD.pt.md`, and a folder README): the port board between the box's I2C rails and a **female** M12 A-coded panel socket (a TCA4307 hot-swap buffer with its EN tied high, a USBLC6-2SC6-class TVS array on SDA, SCL and the port's 3.3 V, 100 ohm series resistors, 2.2 kohm port-side pull-ups, a 50 mA-hold PTC and a BAT85-class back-feed diode, so a module sees about 3.0 V), each part with what it protects against (EXP-4), the pin table, the bus's addresses (0x58-0x5F; one module per socket until a splitter is designed), assembly, meter checks, the first power-up and the RFC's port bench tests (1, 2, 4 and 9 now; 3, 6 and the module's parts after increment 8), troubleshooting and the safety rules (3.3 V only, pin 5 never connected, no loads from the port, **no bare PCF8574/MCP23017 relay boards**, never mains). The target addon guide is rewritten in both languages: no longer "not buildable", it builds the target module from what the RFC fixed (an RP2040 board at 48 MHz, address 0x58 with two jumpers, the expansion protocol v1, the piezo on a rubber pad with its divider, 1 Mohm bleed and BAT85 clamps, a P-channel MOSFET against a reversed hand-made cable, a male M12 connector), and marks **after increment 8** what the firmware will fix: the module's pin table and how its board takes 3.3 V, the UF2 file, the box's driver in its game loop, BRING_UP's port step, Target Windows as a preset; the divider's values wait for bench test 8. `tools/check_wiring.py` checks the port's pin table in both languages (the M12 pin-out of EXP-1: colours, signals, the bus's GPIO 17/18 and options, nothing in pins 1, 3 and 5's GPIO cells) and that the keypad's Kconfig address stays out of 0x58-0x5F; `hardware/README.md`, the folder READMEs and the manuals index link the new guide. The project page's build page is left to the coordinator, as the RFC's row 10 says: its target section still says "not buildable" and lists the questions the RFC answered, in pt, en, de and zh-TW. Nothing is built on hardware.

## The expansion port, increment 11: the I2C output module (2026-11-04, EXPI11-1 to EXPI11-19)

The I2C output module's firmware is `firmware/output-module/`, on the module core, laid out as increment 8's target module: a portable part with host tests (the channel list set at build time with `OUTPUT_CHANNELS`, the I2C events, a guard that turns every channel off for good if one stays on past its max on plus 500 ms, the watchdog's policy, the supply sense with hysteresis, the LED) and a thin pico-sdk layer (channels on GP6-GP9 driven low before anything else, the I2C0 target on GP4/GP5 at 0x5C plus jumpers on GP2/GP3, the LED on GP14, the supply sense on ADC0, a 500 ms hardware watchdog fed only while the core's tick is on time). Its 277 host checks read the `out4` reference module of `expansion.json` back byte for byte and run the whole module through power-up, the lease, the max on and min off and a restart; a new CI job runs them with warnings as errors and under ASan and UBSan. Increment 8 was merged into this branch when it was pushed (PR #62): `tools/docker_module.py` now tests and builds the output module too, increment 8's CI job is **Target and output modules (host tests and UF2)**, and the release adds `atalaia-output-module-<version>.uf2` (the default channel list: four generic relays, 30 s at most). The UF2 builds on pico-sdk 2.2.0 with no warnings; it has never run on a board. `hardware/output-module/BUILD.md` and `BUILD.pt.md` build the module: the isolator (ISO1540 / ADuM1250 class, its box side from the port through a P-MOSFET, no side-1 pull-ups), the module's own 9-15 V supply (fuse, series Schottky, 5 V buck), relay boards with high-level trigger only (with pull-downs) or a MOSFET board, dry contacts with one fuse per load and flyback diodes, bold warnings against mains and against any smoke machine without a documented low-voltage remote input, the pin table (checked by `tools/check_wiring.py` against `board.h`, in both languages), assembly, meter checks, flashing and first power-up. Waiting for the bench (HW2), with no values invented: the isolator at the port's 3.0 V (the bottom of its range) and the bus's low level through it and the port's buffer, the relays at 3.3 V and their coil current, the module's current from the port, the input fuse's rating, the supply sense against a meter, the RFC's tests 5, 6 and 10 (7, isolation, is a meter check now). The project page's build page is not changed (EXPI11-16, with EXPI10-14, for the coordinator).

**A pod's withheld outputs in the console** (2026-11-04, PROPC-6 to PROPC-12, closing EXPI9-29, now that `node.outputs_disabled` is on `main`): the pod's EVT `pod.modules` adds `withheld`, the outputs it has but does not lend (left out of IDENT for want of room, or a module's channels on a pod built without `--module-outputs`), in `node.outputs_disabled`'s text, built by the box's own `outputs_disabled_text` and `expansion_box_disabled_text` (which now count a withheld channel as not enabled; a box never sets it); the phone (`PropSession`) sends it as `node.outputs_disabled` just before each `node.modules` and when it changes, the empty text when every output is lent, so the console shows them as a box's outputs fitted but not enabled and the start check adds its note. No IDENT change and no controller change (contract case `PROPC a phone prop whose I/O pod withholds its siren`, on both). Tests: `test_pod.c` (`test_port_withheld`, `test_port_ident_trim`, `test_port_outputs`), Dart `prop_hello_caps_test.dart` and `prop_pod_port_test.dart` against the host pod. Open for review: the console's wording names the box's admin (PROPC-11).

## A box still in an ended game is freed by the controller (2026-11-05, STUCK-1 to STUCK-17)

The bench finding of 2026-11-05: a box switched off when its game ended never heard the three GAME_OVERs and came back still in the game, refusing every join; its packets never reached the controller, because the USB modem dropped them (no game configured, or another game's id). RFC 0001 Amendment 27 (proposed): the modem now reports another game's packets when asked (CMD WATCH_GAMES `0x0A`, frame OTHER_GAME `0x0C`: the header's game id and source, RSSI, SNR; once per game id in 10 s, 8 ids remembered; IDENT `"games": true`). The Raspberry Pi controller asks after every IDENT that says so (an older modem is logged once), keeps `key_tag:<game>` after a game ends (the last 50 ended games), and for a reported game it ran and ended says that game's GAME_OVER again through the existing path and channel rules, at most once a minute per game; a standby never does (`controller/atalaia_controller/stuck_games.py`). `GET /api/v1/boxes` adds `stuck`, `stuck_reports` and `stuck_watch` for part 2's console (no UI yet). Tested in C (`test_modem.c`), against the C host modem, in the engine, and end to end with the C host box and host modem (`test_box_e2e.py`: killed in a game, the game ended, started again, freed and announcing itself). Open: a stuck box on another channel than the modem's is not heard; the Android controller and the I/O pod do not take part yet (STUCK-15); not tried on hardware (STUCK-17). The box side's own way out is STUCK-20 to STUCK-33.

**Part 2: the GM console** (2026-11-05, STUCK-40 to STUCK-47): the *Boxes* tab lists **Stuck in an ended game** (also in the invite dialog when it has one): the game and its name, the nodes heard, how long ago, the signal and the resends, live from the stream's `boxes` message (which now carries `stuck`). **Release** sends the game's GAME_OVER at once (`POST /api/v1/boxes/stuck/{game}/release`: the usual path and channel rules, 409 with a game live on another channel, 429 within 10 s of the last burst; `game_over_frame` as End). A modem that cannot report gets a hint to update its firmware and use *Leave the game* or `@leave`. Strings in the four languages. Tested in the engine and in Chromium against the C host modem; not on hardware.

**RELEASE, for a controller that lost the game** (2026-11-05, STUCK-50 to STUCK-59, RFC 0001 Amendment 28, confirmed by the maintainer on 2026-11-05): field frame kind 6, sealed with the field join key: the live game (or 0) and the controller's wall clock. A box in another game ends it as on GAME_OVER only if it joined that game before that time, the join's time being the wall clock of the first TIME it took in the game, kept in NVS with the game key's tag (so a recording played back after the box joined a newer game is refused). The GM sends it from *Settings* (*Release every box not in this game*, behind a confirmation; `POST /api/v1/boxes/release`), never from a standby or with an implausible clock, at most once in 30 s. Codecs in C, Python and Dart on the shared vectors; the box in `box_lobby.c`/`box_game.c`; the modem unchanged. Tested in C, Python, Dart, Chromium and end to end (`test_box_e2e.py`: a new database, the C host box restarted into the lost game, freed; the live game's box plays on). Not on hardware (STUCK-59); open for review: the replay rule and the clock caveats (STUCK-52, STUCK-56).

**The Android controller** (2026-11-05, STUCK-60 to STUCK-67): the phone controller does what the Raspberry Pi does for a stuck box. It sends WATCH_GAMES to a USB radio modem whose IDENT says `games` (`app/lib/controller/serial_modem.dart`). It keeps the last 50 ended games' key tags. When the modem reports one of them it resends that game's GAME_OVER, once a minute per game and never from a standby (`app/lib/controller/controller_stuck.dart`). It serves `stuck`, `stuck_reports` and `stuck_watch`, the GM's Release and the field-wide RELEASE (kind 6) with the Pi's answers, rate limits and refusals; the clock check is the Pi's whole clock guard since the maintainer's review (STUCK-62: release date, high-water mark, the store's newest record, the GM's forward-only offset through `PUT /api/v1/clock`). The console it serves therefore shows the list and both Release actions. An I/O pod passes no OTHER_GAME on, so with a pod or an older modem the phone's screen says under *Radio* that it cannot report such boxes, and the console's hint tells the two apart from `radio_kind` (STUCK-64). Tested in Dart and end to end with the C host modem and boxes (freed after a restart into the ended game; RELEASE after a reinstall). Not on a real phone (STUCK-67).

**The maintainer's review** (2026-11-05, STUCK-68 to STUCK-70): every open STUCK-* decision confirmed, RFC 0001 Amendment 28 no longer proposed. Changed: the phone controller has the Pi's clock guard (`app/lib/controller/controller_clock.dart`, STUCK-62); the console's "cannot report" hint says to use a USB radio modem for an I/O pod and to update the firmware for a modem (`radio_kind` in `GET /api/v1/boxes` and the stream's `boxes` message, STUCK-64); the Pi's TIME carries the GM-corrected clock as RELEASE does (STUCK-68).

**The Android controller** (2026-11-05, STUCK-60 to STUCK-67): the phone controller does what the Raspberry Pi does for a stuck box. It sends WATCH_GAMES to a USB radio modem whose IDENT says `games` (`app/lib/controller/serial_modem.dart`). It keeps the last 50 ended games' key tags. When the modem reports one of them it resends that game's GAME_OVER, once a minute per game and never from a standby (`app/lib/controller/controller_stuck.dart`). It serves `stuck`, `stuck_reports` and `stuck_watch`, the GM's Release and the field-wide RELEASE (kind 6) with the Pi's answers, rate limits and refusals; the clock check uses the Pi's release date and the newest game in the phone's store (STUCK-62). The console it serves therefore shows the list and both Release actions. An I/O pod passes no OTHER_GAME on, so with a pod or an older modem the phone's screen says under *Radio* that it cannot report such boxes. Tested in Dart and end to end with the C host modem and boxes (freed after a restart into the ended game; RELEASE after a reinstall). Not on a real phone (STUCK-67).

**Wi-Fi names and passwords with spaces on the USB console** (2026-11-05, WIFI-1 to WIFI-9): a bench board could not store the SSID "My Field", since `@wifi` took the first word as the name. `@wifi` now also takes double-quoted arguments, `\"` and `\\` inside: `@wifi "My Field" "pass word"` (`firmware/esp32/main/wifi_args.c`, platform-free). The unquoted form works as before. An unclosed quote, an unknown escape or text after a closing quote is refused with its reason and nothing is stored; the SSID is 1-32 bytes, the password none, 8-63 characters or 64 hex digits. No host tool sends `@wifi`, so none changed. Tested on a computer (`test_wifi_args.c`); not yet typed on a real box (WIFI-9).

**The setup portal takes the console's Wi-Fi password rule** (2026-11-05, WIFI-7 changed by the maintainer; WIFI-1 to WIFI-9 confirmed): the portal's field Wi-Fi password is none, 8-63 characters or exactly 64 hex digits, checked with the console's `wifi_pass_valid` (`wifi_setup_wifi_pass_problem_in`); before, it took any 8-64 characters, and a 65th was cut off unseen. The page's label, its `pattern` and the refusal say so in en, pt-PT, de and zh-TW. Tested on a computer only.

**The Field Box, firmware and phone prop manuals by task** (2026-11-06, documentation pass): `docs/manuals/{en,pt}/field-box.md` and `firmware.md` rewritten against the code and the CHANGELOG, and the phone prop and I/O pod moved into a new `phone-prop.md` (en and pt, section for section). Corrected: the newest release (v0.8.0), the release keys' build default (the project's two keys), the field logo boxes no longer fetch, the buildable target, and what is v0.9.0 and not released yet (stuck-box recovery, `@leave`, quoted `@wifi`, the portal's Wi-Fi rules). Added: the output module on a box's expansion port, the Medic Kit at the box, a numbered v0.8.0 key-rotation procedure, and flashing the RP2040 modules. Shared anchors: `field-box.md#take-a-box-out-of-its-game` and `#update-the-boxes`.

**The project page in Polish** (2026-11-06, SITE-PL-1 to SITE-PL-9, open): a fifth language for Polish airsoft (ASG) players, the project page only: `site/i18n/pl.yaml` and the pages under `/pl/` (`tryby/`, `radio/`, `roadmap/`, `budowa/`, `jak-to-dziala/`, `slownik/`), the flag in the switcher, `hreflang` and the sitemap, Barlow's latin-ext files for ą ć ę ł ń ś ź ż. An AI draft, not yet reviewed by a native-speaking player (`docs/translations/status.yaml`, `draft`); the pictures with text, the app screenshots and the mode animations stay English.

**The setup portal takes the console's Wi-Fi name rule** (2026-11-06, WIFI-10 confirmed by the maintainer): the portal's field Wi-Fi name is 1-32 bytes after URL decoding, UTF-8 counted in bytes, checked with `wifi_ssid_valid` (`wifi_args.h`, now also used by `fw_update_esp_set_wifi`) through `wifi_setup_wifi_ssid_problem_in`; before, a longer name was cut to 32 bytes unseen. The form reads one byte more than the limit so an overflow is seen; the refusal is in en, pt-PT, de and zh-TW. The page keeps `maxlength="32"`, which counts characters. Tested on a computer only.
