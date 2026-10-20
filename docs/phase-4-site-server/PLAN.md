<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 4 -- Site Server and Advanced Play: Implementation Plan

Gate: **A weekend milsim runs on the platform end to end.**

This plan was refreshed on 2026-10-19, after phase 3's software was
built (section "Refresh 2026-10-19" below). The plan phases are now
listed **in the order to implement them**, each marked *software, can
be done now* or *needs hardware or a real deployment*, small enough to
be implemented, verified from a clean copy and committed on its own.
All builds and tests run in Docker; the commands below are the
repository's real ones.

---

## Refresh 2026-10-19 (after phase 3 software)

Phase 2 plan phases A-E and the mode pack, and phase 3 plan phases A-F,
the Medic Kit and branding are built in software (phase 3 STATUS.md).
What is left of them needs hardware: phase 2 plan phase F (the field
test), phase 3 plan phase G (the field test), the Android controller
role's shell (PE24) and iOS. The 2026-10-18 handoff had updated this
plan from phase 3's *design*; the code differs from that design in
ways that change phase 4. What changed, and why:

1. **Order.** The old phases A-I were ordered by dependency on phases
   2D and 3, which are now done. The maintainer wants as much code as
   possible before the Heltec V4 boards arrive, so the phases are
   re-cut into 22 small software plan phases and 4 hardware ones,
   modes and core first (they reuse tooling phase 3 proved), then the
   site server chain (decision P4R20). The mapping from the old letters
   is in the table below.
2. **Tests and tooling.** Mode tests are YAML run by
   `python3 -m atalaia_sim test` (and through the core in Dart), the
   controller's tests are `unittest`, not pytest (decision D15), and
   everything runs in the `atalaia-dev` image through `tools/check.sh`
   and the `tools/docker_*.py` wrappers. Commands are written for the
   WSL/Linux working copy (`$PWD`, no `MSYS_NO_PATHCONV` or `pwd -W`).
   The site server gets its own image and PostgreSQL in a service
   container in CI and an ephemeral container locally (P4R16, P4R17).
3. **Event ids.** 42-45 scenario events, 46 `vip.extracted`, 47
   `hacking.solved`; no `satellite.*` events (satellites send
   `zone.captured`, as spec section 15 says); `target.hit` already
   exists as 16; 50-51 are the Medic Kit's; data keys from 34
   (decision P4R1). Each id is added with the code that first uses it.
4. **Modes.** Folders with underscores and translations in
   `mode.yaml` (P4R22); `score.add` takes integers (P4R2); inputs that
   exist (`keypad.key`, `team_input.*`, `nfc.tag`, `cmd.mode`) instead
   of an invented `display.touch` (P4R5); positions never travel as a
   `gps.fix` event on the radio (P4R6); a `hit.hit` input for the target
   addon (P4R4); engineer-only satellites deferred (P4R3).
5. **Custom scenarios.** Boxes run only built-in scripts (a new mode
   needs a flash, K10; a join for a missing mode is refused), so a
   scenario compiles to a `kind: scenario` package with a `field.lua`
   only, and the boxes run a new built-in role package,
   `org.atalaia.objectives` (P4R7).
6. **Sync.** The controller opens every connection (it sits behind 4G
   NAT) and the site server never holds the controller's GM or read
   token (P4R12); the API key is stored as SHA-256 (P4R13); a game is
   `(field, game_id, game_seed)` (P4R11); scores merge per node, not per
   total, because a GM's adjustment can be negative (P4R10).
7. **Chrono registry.** Records are the signed per-reading JSON that
   the marshal's phone makes; the site server stores them verbatim,
   verifies them with the controller's `chrono.py` and keeps public
   keys only (P4R14, P4R15).
8. **Player identity and tokens.** Players are per-field
   pseudonymous ids (`p-` + 12 base32 characters with a secret whose
   SHA-256 the controller keeps); player tokens (`apt1.`) are signed
   with the controller's own per-game token key (B8), not the game key;
   the site server never verifies or issues them.
9. **Branding and club profiles.** Phase 3 built field and team
   branding per controller; club profiles sync it (P4R19, plan phase
   18).
10. **ATAK.** Field Boxes have no GPS and their positions are 0-1 on
    the field image, so the image is georeferenced; player positions
    are never multicast (P4R18).
11. **Licences.** Controller additions are AGPL-3.0-or-later
    (REUSE.toml), not GPL (P4R21).

### Old phases to new plan phases

| Old | Content | New plan phases |
|-----|---------|-----------------|
| A | Site server skeleton, auth, GDPR, deploy | 10, 11, 12, 21, 22 |
| B | Master and Satellites, Target Windows | 1, 2 (+ HW2) |
| C | Sync and chrono registry | 13, 14, 20 |
| D | Geo utilities, ATAK/CoT | 3, 9 (+ HW3) |
| E | Scenario DSL and compiler | 6, 7, 8 (+ the site server's library in 20) |
| F | VIP / Payload, Hacking Terminal | 4, 5 (+ HW3) |
| G | Device health, remote GM | 19 |
| I | Scheduling, registration, feeds, import | 15, 16, 17 |
| H | Integration and the weekend gate | HW1-HW4 |
| (new) | Club profiles and branding sync | 18 |

### Lessons from phases 2 and 3 that this plan applies

- **Verify from a clean copy.** Incremental builds have hidden real
  errors twice (an undefined Kconfig symbol in an ESP-IDF build, a
  build-downloaded dependency). Every plan phase is verified from a
  fresh clone with a freshly built `atalaia-dev` image and an empty
  build folder (section "How each plan phase is verified").
- **Check known-answer vectors against their source documents**, not
  against the implementation (a self-made AES-CCM vector was once
  labelled RFC 3610's). New vectors in this phase (iCalendar folding,
  CoT XML, the sync batch) cite their source; RFC test vectors are
  copied from the RFC.
- **Shared vectors for every format with two implementations.** C,
  Python and Dart all read `protocol/vectors/`; phase 4 adds vectors for
  the scenario package, the sync batch and the `hit` capability, and the
  site server reads the existing chrono and player-token vectors too.
- **Exceptions raised in ctypes callbacks are swallowed.** The
  simulator collects problems in `Simulation.problems`; new field-script
  inputs (`position.fix`, scenario mode commands) must report errors the
  same way, and tests assert that `problems` is empty.
- **Wokwi's CI quota is used up (decision R7).** Firmware changes (new
  built-in presets) are verified with the firmware host tests, the
  screen reference images and the three ESP-IDF builds with no
  warnings; each commit says that Wokwi did not run.

---

## How each plan phase is verified

Every plan phase ends with the same independent check, from a clean
copy, before its commit:

```sh
# a clean copy and a fresh image (no build/, no managed_components, no sdkconfig)
rm -rf /tmp/verify && git clone --quiet . /tmp/verify && cd /tmp/verify
docker build -t atalaia-dev:verify tools/dev
docker run --rm -v "$PWD:/src" atalaia-dev:verify sh -c "BUILD=/tmp/c sh tools/check.sh"
```

`tools/check.sh` runs protogen's check, the project page check, the
wiring check, the formatters, the core's `ctest`, the host modem, box
and pod builds, the simulator's unit tests, **every mode's YAML tests**
(`python3 -m atalaia_sim test`) and the controller's unit tests, with
`ATALAIA_REQUIRE_ALL=1` so a missing core or host binary is an error,
not a skip. Depending on what a plan phase touches, also:

| Touches | Command | CI job |
|---------|---------|--------|
| Modes run in Dart through the core, the app, the catalogue | `python3 tools/docker_app.py` (check, ndk, apk); `python3 tools/docker_app.py gen` after a new built-in mode; `goldens` for new screens | `flutter-test`, `core-android-ndk`, `flutter-build-android` |
| On-device app tests | `sh app/tool/emulator_tests.sh` (needs KVM) | `flutter-integration` |
| Field Box presets, firmware C | `python3 tools/docker_fw.py test`, then `build`, `modem` and `pod` (0 warnings); not `wokwi` (R7) | `firmware-test`, `esp32-build`, `esp32-modem-build`, `esp32-pod-build` |
| The core's C | ASan/UBSan, as CI's `sanitizers` job: `docker run --rm -v "$PWD:/src" atalaia-dev sh -c 'cmake -S core -B /tmp/s -DCMAKE_BUILD_TYPE=Debug -DCMAKE_C_FLAGS="-fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=all" && cmake --build /tmp/s && ctest --test-dir /tmp/s --output-on-failure'` | `sanitizers` |
| GM console | `python3 tools/docker_console.py` (Playwright in Chromium) | `console` |
| Licences | `reuse lint`, as CI's `licensing` job (locally: `python3 -m venv /tmp/r && /tmp/r/bin/pip install reuse && /tmp/r/bin/reuse lint`, in a copy without build output) | `licensing` |
| Site server (from plan phase 10) | `python3 tools/docker_server.py test` (new: Docker Compose with an ephemeral `postgres:16-alpine` and the server's test image); `python3 tools/docker_server.py migrations` (upgrade, downgrade, upgrade) | `server` (new, with a `postgres:16-alpine` service) |

Mode tests alone, during development:
`python3 tools/docker_sim.py test modes/master_satellites` (the core is
rebuilt incrementally in a Docker volume: fine while working, never the
final check).

The **database in tests** (decision P4R17): the site server's database
layer is tested only against PostgreSQL 16, never SQLite. Layers with no
database (feeds, the iCalendar writer, the import parser, sync batch
validation, chrono verification, the scenario compiler) are plain
Python with unit tests that also run inside `tools/check.sh`.

---

## Scope

### In scope (software, buildable and testable now)

- Four advanced modes: Master and Satellites, Target Windows (logic;
  the addon is hardware), Hacking Terminal (keypad puzzles), VIP /
  Payload (player and payload prop).
- `geo.distance()` and `geo.in_zone()` in the core for every script.
- Custom scenarios: the `kind: scenario` package, the built-in
  `org.atalaia.objectives` role package, the compiler and validator
  (`controller/atalaia_controller/scenarios/`, decision P4-1), a CLI,
  the controller's scenario endpoints, the GM console's scenario
  builder, objectives in the player view.
- The ATAK / CoT emitter on the controller, with a georeferenced field
  image.
- The site server (`server/`): FastAPI with PostgreSQL 16, Alembic,
  accounts (Argon2id, JWT, TOTP), roles, personal data rights and
  retention, the controller sync (a controller-initiated link), the
  chrono registry, scheduling, publication, registration with
  pre-declared replicas and the game-day sync into the controller's
  check-in list, iCalendar and JSON feeds, the registration import and
  the adapter interface, club profiles and branding sync, device
  health, the remote GM relay over the controller's link, game history,
  hosted multi-tenant mode, deployment (Caddy, setup, backup, restore).
- New events and data keys in `protocol/schema/events.yaml` (P4R1).

### Needs hardware or a real deployment

- Sync over a real 4G link between a Raspberry Pi controller and a
  site server on a VPS (HW1).
- The target addon and its `hit` driver on the Field Box (HW2).
- Real phones: the VIP's GPS outdoors, a Hacking Terminal and a payload
  prop on a phone, ATAK on a phone on the field Wi-Fi (HW3).
- Chrono end to end with a real chronograph and NFC tags (HW4).
- The weekend milsim gate (HW4), after phase 2 plan phase F and phase 3
  plan phase G.

### Out of scope (later phases)

- Visual scenario editor (phase 5; it will write the same manifest).
- TAK Server integration (phase 5+).
- A touch-only Hacking Terminal puzzle (needs a `display.touch` input
  and an RFC, P4R5).
- Engineer-only satellites (P4R3).
- Carrier PCB, community hub directory, mode registry browser, more
  languages (phase 5).
- The Android controller role's shell (phase 3 PE24) and iOS (phase 3).
- Money Factory (phase 3 decision A1).

---

## Constraints (from ADR.md, with the 2026-10-19 amendments)

| # | Constraint | How the plan respects it |
|---|------------|--------------------------|
| 1 | PostgreSQL 16+ with SQLAlchemy 2 async + asyncpg; UUID keys on user-facing tables; `created_at`/`updated_at` | Plan phase 10 creates the schema with Alembic; tests run on PostgreSQL 16 only (P4R17) |
| 2 | Alembic for every change; every migration reversible; CI runs upgrade-downgrade-upgrade | `tools/docker_server.py migrations` and the `server` CI job in every site-server plan phase |
| 3 | Argon2id passwords, PyJWT, pyotp; TOTP mandatory for admin, GM and marshal accounts | Plan phase 11 |
| 4 | **Amended 2026-10-19:** the controller opens every connection; the site server never stores the controller's tokens; the controller's API key is a 256-bit value stored as SHA-256 (P4R12, P4R13) | Plan phase 13; remote GM in plan phase 19 rides the controller's WebSocket |
| 5 | **Amended 2026-10-19:** events append-only, unique on `(game, node_id, seq, game_time_ms, type)`; a game is `(field, game_id, game_seed)`; scores merge per node counter by `GREATEST`, GM adjustments come as `score.delta` events (P4R10, P4R11) | Plan phase 13's tests replay batches and negative adjustments |
| 6 | Schema per field in hosted mode; one schema self-hosted | Plan phase 21 (hosted mode last) |
| 7 | **Amended 2026-10-19:** Ed25519 per marshal, keys made on the marshal's phone; the site server keeps public keys only, with history; records stored verbatim and verified with `chrono.py` (P4R14, P4R15) | Plan phase 14 |
| 8 | **Amended 2026-10-19:** scenarios are YAML; the compiler is `controller/atalaia_controller/scenarios/` (P4-1), the site server imports it; it emits a `kind: scenario` package (`field.lua` only) over the built-in `org.atalaia.objectives` role package (P4R7, P4R8) | Plan phases 6-8, 20 |
| 9 | `geo.distance`, `geo.in_zone` in the core for every script; CoT over UDP multicast (props and zones only) and TCP (staff endpoints) (P4R18) | Plan phases 3, 9 |
| 10 | Personal data: anonymise on erasure, keep signatures; daily retention purge; templates need legal review (P4-6); **positions never reach the site server** (P4R25) | Plan phase 12, extended by every later plan phase that adds personal data |
| 11 | Docker Compose with Caddy (or nginx) for TLS; setup script makes secrets; `pg_dump -Fc` backups, 30 days | Plan phase 22 |
| 12 | **Amended 2026-10-19:** new events 42-47 and data keys 34-36 (P4R1), each added with the code that first emits it | Plan phases 4, 5, 6 |
| 13 | **Amended 2026-10-19:** SPDX headers on every file; AGPL-3.0-or-later for `server/` and `controller/` (incl. `sync_client.py`, `atak.py`, `scenarios/`); GPL-3.0-or-later for modes, core and tools; CC-BY-SA-4.0 for docs (P4R21) | `reuse lint` in CI |
| 14 | **Amended 2026-10-19:** no C compiler on the host; the site server image is `python:3.12-slim` with hash-pinned pip dependencies and a build stage for `libatalaia_core.so` (P4R9, P4R16) | Plan phase 10 |
| 15 | **Amended 2026-10-19:** phase 3 interfaces are now built and are the source of truth (STATUS.md handoff), not assumptions | The assumptions table below marks each as built |
| 16 | Scheduling and registration feed the controller, never drive it (ADR-P4-11) | Plan phase 16 |
| 17 | Open feeds hold no personal data (ADR-P4-12) | Plan phase 15 |
| 18 | Third-party platforms only by documented API or written agreement (ADR-P4-12) | Plan phase 17 |
| 19 | **New 2026-10-19:** boxes run built-in scripts only; anything per game (a scenario) lives in `field.lua` and reaches nodes as mode commands (P4R7) | Plan phases 6-8 |
| 20 | **New 2026-10-19:** positions never travel as events, on the radio, MQTT or to the site server; scripts get them as controller-only inputs (P4R6, P4R25) | Plan phases 5, 9 |
| 21 | **New 2026-10-19:** shared Python (scenarios, chrono verifier, player-token codec, image checks, `atalaia_sim.mode`) stays free of FastAPI and pydantic (P4R16) | Plan phases 7, 13, 14, 18 import them from the site server |
| 22 | **New 2026-10-19:** `score.add` takes integers; events carry ids, never texts or coordinates; every event fits 200 bytes (the simulator's checks) | Mode tests |
| 23 | **New 2026-10-19:** each plan phase is verified from a clean copy and committed on its own; firmware without Wokwi until R7 ends | "How each plan phase is verified" |

---

## Implementation order

| # | Plan phase | Scope | Software now / hardware | Depends on | Size |
|---|------------|-------|-------------------------|------------|------|
| 1 | Master and Satellites | `modes/master_satellites/`, Field Box preset, app catalogue | Software, now | -- | S |
| 2 | Target Windows (logic) | `modes/target_windows/`, `game.teams()` in the core, `hit` capability in the draft RFC and the capability proxy | Software, now (the addon: HW2) | -- | S |
| 3 | Geo utilities | `core/src/geo.c`, `geo.*` in `script_api.c` | Software, now | -- | S |
| 4 | Hacking Terminal | `modes/hacking_terminal/`, event 47, Field Box preset, app | Software, now (on a phone: HW3) | -- | M |
| 5 | VIP / Payload | `modes/vip_payload/`, event 46, `position.fix` for `field.lua`, `gps.fix` on Android props | Software, now (real GPS: HW3) | 3 | M |
| 6 | Scenario packages and objectives | `kind: scenario`, `modes/objectives/` role package, events 42-45, data keys 34-35 | Software, now | -- | M |
| 7 | Scenario compiler and validator | `controller/atalaia_controller/scenarios/` and its CLI | Software, now | 3, 6 | L |
| 8 | Scenarios in the controller, console and app | `/api/v1/scenarios`, the scenario builder, objective routing, the player view | Software, now | 7 | M |
| 9 | ATAK / CoT emitter | `atak.py`, field image georeference | Software, now (a real ATAK: HW3) | 3 | M |
| 10 | Site server skeleton and test tooling | `server/` app, config, database, Alembic base, health, image, `tools/docker_server.py`, CI job | Software, now | -- | M |
| 11 | Accounts, sessions and roles | Argon2id, JWT, TOTP, refresh rotation, rate limits, per-field roles, audit log | Software, now | 10 | M |
| 12 | Personal data | access, export, erasure, rectification, retention purge, notices and DPA templates | Software, now | 11 | M |
| 13 | Controller sync | API keys, the controller-initiated link, events, per-node scores, game metadata, nodes; `sync_client.py`, store schema 5 | Software, now (over 4G: HW1) | 10, 11 | L |
| 14 | Chrono registry | marshal keys, replicas, readings with verification, violations, cross-field sharing | Software, now | 13 | M |
| 15 | Scheduling, field pages and feeds | scheduled games, publication, `.ics`, JSON feed | Software, now | 11 | M |
| 16 | Registration and game-day sync | registrations, tickets, roster pull, expected check-ins, outcomes push | Software, now | 13, 15 | L |
| 17 | Registration import and adapters | CSV/JSON import, `PlatformAdapter`, test adapter | Software, now | 16 | S |
| 18 | Club profiles and branding sync | clubs, branding and saved teams through `GET /sync/field` | Software, now | 13 | M |
| 19 | Device health, firmware catalogue, remote GM | health from sync, remote GM over the controller's WebSocket (built 2026-10-20) | Software, now | 13 | M |
| 20 | Game history and the scenario library | history views, scenario CRUD on the site server pushed with presets | Software, now | 13, 7 | M |
| 21 | Hosted multi-tenant mode | schema per field, RLS, export and deletion of a field | Software, now | 10-20 | M |
| 22 | Deployment | Caddy, `setup.sh`, `backup.sh`, restore test, `server/docs/DEPLOY.md` | Software, now | 10 | S |
| HW1 | Sync over a real link | a Pi controller with the modem, a phone's 4G, a VPS | Needs hardware and a deployment | 13, phase 2 F | -- |
| HW2 | Target addon | the addon's MCU firmware, the addon port driver, piezo tuning | Needs hardware | 2 | -- |
| HW3 | Phones in the field | VIP GPS, payload prop, Hacking Terminal and ATAK on real phones | Needs hardware | 4, 5, 9, phase 3 G | -- |
| HW4 | Chrono end to end and the weekend milsim gate | staged gate test plan below | Needs hardware and players | all, phase 2 F, phase 3 G | -- |

Sizes: S about a day of agent work and under 1,000 changed lines, M two
to three days, L up to a week. Plan phases 1-9 and 10-22 are two
independent chains and can run in parallel worktrees; within each
chain, follow the order.

**First: plan phase 1 (Master and Satellites).**

---

## Plan phase 1: Master and Satellites

*Software, can be done now. Depends on nothing. Size S.*

### Goal

The mode of spec section 15: a master zone and satellites; holding
satellites while holding the master boosts the master's scoring, and
when the master changes hands every satellite goes back to neutral.
Decisions P4R2 (events, integer points), P4R3 (no engineer-only yet),
P4R22, P4R23.

### Design

- `mode.yaml`: id `org.atalaia.master_satellites`, `kind` omitted
  (main mode), `min_tier: reduced`, roles `master` and `satellite`,
  both `{ requires: [team_input], optional: [team_display, audio,
  display] }`; params `capture_hold_ms` (3000), `tick_s` (10),
  `points_per_tick` (2, even by default so a half bonus is whole),
  `satellite_bonus_pct` (50), `min_satellites` (0); `i18n.pt` ("Mestre
  e Satélites").
- `node.lua`: capture-only, the same as Hold-All's (`zone.captured`,
  `zone.neutralized`, `cmd.set_owner`); boxes do not score.
- `field.lua`: on `zone.captured`/`zone.neutralized` and every second,
  count the satellites whose owner is the master's owner; every
  `tick_s`, `score.add(owner, points_per_tick + points_per_tick *
  held * satellite_bonus_pct // 100, "master")`; when the master's owner
  changes, `field.send(id, "set_owner", { team = "none" })` to each
  satellite. A satellite that rebooted is reset by the next master
  change, as in the field (no special case).
- Screens: the mode's own templates in `assets/screens/` (templates
  belong to their mode: Domination's `standby` and `captured` adapted,
  plus `master_status` with the satellites held and the bonus), checked
  by the simulator's template check and drawn by the Field Box and the
  app.

### Files

| File | Licence | Purpose |
|------|---------|---------|
| `modes/master_satellites/mode.yaml` | GPL-3.0-or-later | Manifest |
| `modes/master_satellites/node.lua` | GPL-3.0-or-later | Capture-only box |
| `modes/master_satellites/field.lua` | GPL-3.0-or-later | Bonus, ticks, reset on master change |
| `modes/master_satellites/assets/screens/*.yaml` | GPL-3.0-or-later | Screens (if new) |
| `modes/master_satellites/tests/basic.yaml`, `master_change.yaml`, `three_satellites.yaml`, `satellite_recapture.yaml`, `gm_override.yaml`, `no_master_owner.yaml` | GPL-3.0-or-later | Event sequences |
| `firmware/esp32/main/CMakeLists.txt`, `builtin_presets.c`, `shell.c` | (existing) | The mode as a built-in preset |
| `app/lib/modes/builtin_modes.g.dart` | (generated) | `python3 tools/docker_app.py gen` |
| `controller/console/src/i18n/{en,pt}.json` | (existing) | Event words (`feed.events`), if new texts are needed |
| `modes/README.md`, `docs/design-spec.md` (section 15 table: "built in software"), `CHANGELOG.md`, `README.md`, `site/i18n/{en,pt}.yaml` | (existing) | Docs (R4) |

### Tests

- YAML (simulator, and in Dart through the core): the bonus with 0-3
  satellites (`expect_score` at each tick), the master changing hands
  resets satellites (`zone.neutralized` from each satellite), a
  satellite recaptured by the other team drops the bonus, the GM's
  `set_owner` on the master, no score while nobody holds the master.
- The controller with the real engine: `field.send` reaches the host
  boxes (`controller/tests/test_box_e2e.py` gets one case).
- Field Box host tests: the preset loads; three ESP-IDF builds, 0
  warnings.

**Built 2026-10-19 (in software, not yet on radio hardware).** What
differs from the design above (decisions M1-1 to M1-6):

- The master box learns its satellites and bonus from `field.lua`
  through a mode command of the mode's own, `status` (`{ name, team,
  held, of, points }`), sent only when one of them changes; no box
  knows its role otherwise (M1-1).
- Satellites are freed whenever the master leaves a team's hands,
  including the GM setting it to none; the first capture of a free
  master frees nothing; a free satellite ignores `set_owner none`
  (M1-2).
- `min_satellites`: the master scores nothing while its holder has
  fewer satellites (M1-3). The bonus counts the satellites held at each
  tick.
- The Field Box's keypad picker lists nine presets and this is the
  tenth built-in one: joinable by the controller, not pickable on the
  box (M1-4; a second picker page is recommended before plan phases 4
  and 6 add more presets). Done in plan phase 2: `0` turns the page
  (M2-1).
- One master counts (the lowest node id); owners from `field.owner()`
  checked on each capture and every second, as Hold-All (M1-5).
- Tests: the six named above (`three_satellites.yaml` for 0-3
  satellites) plus `odd_points.yaml` (rounding) and
  `min_satellites.yaml`; `basic.yaml` covers a satellite alone. No console event words were
  needed (no new events).

### Validation

```sh
python3 tools/docker_sim.py test modes/master_satellites
python3 tools/docker_app.py gen && python3 tools/docker_app.py check
python3 tools/docker_fw.py test && python3 tools/docker_fw.py build
# then the clean-copy check (tools/check.sh)
```

---

## Plan phase 2: Target Windows (logic)

*Software, can be done now; the addon is HW2. Depends on nothing. Size S.*

### Goal

A target lights a random team's colour for a short window; a hit in the
window scores for that team (spec section 15). Decision P4R4.

### Design

- The `hit` capability (spec section 7) reaches scripts as `hit.hit`
  with `strength` (0-255); commands `cap("hit"):arm()` and `:disarm()`.
  Written into `docs/rfcs/0000-phase-3-events-tags-and-pods.md` (draft)
  and `protocol/capability-proxy.md` (type `hit`, a dated refinement),
  with a shared vector in `protocol/vectors/capability_proxy.yaml`, so a
  pod or the addon can lend it later.
- `modes/target_windows/`: role `target` `{ requires: [hit, led],
  optional: [display, audio] }`; params `interval_s`, `window_s`,
  `hit_points`, `min_strength`; `node.lua` opens windows with
  `rand()`, fills the ring with the team, arms the target, scores with
  `score.add`, emits `target.hit` (16) with `window_open` and the team
  in the envelope; hits below `min_strength` ignored; at most one score
  per window per target unless `multi_hit`.
- `game.teams()` in the core (decision P4R26): the game's team names
  in order, for node and field scripts (`core/src/script_api.c`, a C
  test, a simulator test; Dart gets it through the core). The window's
  team is `teams[rand(1, #teams)]`.
- Not a Field Box preset yet (P4R23), not offered by Android props.

### Files

`modes/target_windows/{mode.yaml,node.lua,tests/*.yaml,assets/screens/*.yaml}`
(GPL-3.0-or-later); `core/src/script_api.c` and `core/tests/` (`game.teams()`),
`docs/design-spec.md` (script API); the draft RFC and `protocol/capability-proxy.md`
(dated refinement); `protocol/vectors/capability_proxy.yaml` (a `hit`
IDENT entry and an EVT); the C, Python and Dart proxy codecs if they
check capability types; docs.

### Tests

YAML: hit in the window scores for the window's team; a hit outside
scores nothing and reports `window_open: false`; weak hits ignored; three
cycles with a fixed `seed` give the expected teams; `cmd.set_owner` is
ignored. The capability vector through the C, Python and Dart codecs.

**Built 2026-10-19 (in software; the addon is HW2).** What differs from
the design above, or fills what it left open (decisions M2-1 to M2-5):

- Windows: the target is dark for `interval_s` after the start and after
  each window closes (the dark time, so no rule ties it to `window_s`);
  the first scoring hit closes the window unless `multi_hit`; a hit while
  dark logs `target.hit` with `window_open: false` and no team; the sensor
  is armed from `game.start` to `game.end` (M2-2). Screens `standby` and
  `window`.
- `game.teams()` returns a new table each call; the core stays 0.2.0
  (M2-3).
- The `hit` capability is draft RFC 0000 Amendment 1 and a dated
  refinement in `protocol/capability-proxy.md`; vectors `target_addon`
  (IDENT), `target_hit` (EVT) and `target_arm` (CMD), assembled by hand
  from the tables and passed by the C, Python and Dart codecs, none of which
  checks capability types. The app's pod client maps a lent `hit` to
  `hit.hit` (M2-5).
- Not a Field Box preset (P4R23): the simulator's firmware checks name it
  as the one mode not in the image; its templates are in the image anyway,
  with three reference images and three app goldens (M2-4).
- Done first in this plan phase: the Field Box picker's pages (`0` turns
  to the next nine, M2-1, closing M1-4), with host tests and two
  reference screens.
- Tests: the five named above plus `basic.yaml` (screens, the next
  window) and `multi_hit.yaml`; seed 3 gives red, blue, yellow.

### Validation

```sh
python3 tools/docker_sim.py test modes/target_windows
python3 tools/docker_app.py test test/modes
python3 tools/docker_fw.py test && python3 tools/docker_fw.py build   # the core changed (game.teams)
# clean-copy check (tools/check.sh; the vectors run in C and Python there), ASan/UBSan
```

---

## Plan phase 3: Geo utilities in the core

*Software, can be done now. Depends on nothing. Size S.*

### Goal

ADR-P4-9: `geo.distance(lat1, lon1, lat2, lon2)` (metres, Haversine)
and `geo.in_zone(lat, lon, zone)` (circle or polygon) for every script,
in C.

### Files

| File | Licence | Purpose |
|------|---------|---------|
| `core/include/atalaia/geo.h`, `core/src/geo.c` | GPL-3.0-or-later | `atalaia_geo_distance_m()`, `atalaia_geo_in_circle()`, `atalaia_geo_in_polygon()` (at most 32 vertices) |
| `core/src/script_api.c` | (existing) | The `geo` table, registered for node and field scripts |
| `core/CMakeLists.txt` | (existing) | `geo.c`, `-lm` |
| `core/tests/test_geo.c` | GPL-3.0-or-later | C tests |
| `protocol/vectors/geo.json` | GPL-3.0-or-later | Known distances and zone cases, read by C and Python (and Dart through the core) |
| `simulator/tests/test_geo.py` | GPL-3.0-or-later | `geo.*` from Lua through ctypes against the vectors |
| `docs/design-spec.md` (script API), `modes/README.md` | (existing) | Docs |

### Tests

Distances checked against an independent source (Lisbon-Porto by the
haversine formula on a 6,371 km sphere, about 274 km; a 1 m and a
100 m case; the same point; antipodes), not against the code itself;
circle edge, polygon inside, outside, concave, on a vertex; argument
errors (`luaL_error`, reported as `script.error`). The firmware's host
tests and ESP-IDF builds rerun (the core is in the Field Box image).

**Built 2026-10-20 (in software).** What differs from the design above,
or fills what it left open (decisions M3-1 to M3-3):

- Determinism (M3-1): replays must agree between the desktop, the ESP32
  and Android, and C library sines differ in the last bit between glibc,
  musl, bionic and newlib, so `geo.c` has its own sine, cosine and arc
  tangent (Taylor polynomials on at most 45 degrees, exact hexadecimal
  coefficients), uses only `+ - * /` and `sqrt` (correctly rounded by
  IEEE 754 everywhere), subtracts coordinates in degrees before turning
  them into radians, is compiled with `-ffp-contract=off` in all three
  builds (core, Field Box component, firmware host tests) and refuses a
  build with `FLT_EVAL_METHOD != 0`. The tests check known answers
  within a tolerance and every result's exact bits.
- The vectors (M3-3) are in `protocol/vectors/geo.json`; the C tests
  read them through `core/tests/geo_vectors.h`, generated by
  `tools/protogen.py` (exact hexadecimal doubles). Known answers:
  Rosetta Code's BNA-LAX haversine on 6,371 km (1 um),
  GeographicLib's JFK-Changi geodesic on WGS 84 (the sphere within
  0.5 %), meridian and equator arcs (R x angle) for 1 m and 100 m, the
  same point, antipodes (pi R), Lisbon-Porto (274 km +/- 1 km, as the
  ADR), across the 180th meridian; Rosetta Code's ray-casting square,
  hexagon and concave "strange" polygon away from their edges. 16 more
  distances are determinism pins only.
- Boundaries and arguments (M3-2): a point on a circle's edge, a
  polygon's edge or a vertex is inside; coordinates must be Lua numbers
  in range (no numeric strings, no NaN); a zone needs its `type`;
  polygons have 3 to 32 points, are tested in plain degrees and must
  not cross the 180th meridian. All argument errors are `script.error`.
- `test_geo.c` runs inside the core's one `ctest` executable
  (`test_core`), with a `field.lua` check in `test_field_api.c`. Dart
  gets `geo` through the core with nothing to add; its first Dart test
  comes with VIP / Payload (plan phase 5).
- Checked once by hand beyond CI: the core's `ctest` on arm64 and armv7
  (gcc and clang, Alpine under QEMU), and the vectors' exact bits in an
  ESP-IDF app on the ESP32 and the ESP32-S3 in Espressif's QEMU; the
  Field Box image grew by 5.4 KB (`0x1710c0`, 28 % of the 2 MB slot
  free).

### Validation

```sh
# clean-copy check (ctest runs test_geo; the simulator runs test_geo.py)
docker run --rm -v "$PWD:/src" atalaia-dev sh -c "BUILD=/tmp/c sh tools/check.sh"
python3 tools/docker_fw.py test && python3 tools/docker_fw.py build
# ASan/UBSan as CI's sanitizers job
```

---

## Plan phase 4: Hacking Terminal

*Software, can be done now; on a phone in the field: HW3. Depends on nothing. Size M.*

### Goal

A terminal with a puzzle; solving it emits `hacking.solved` (47) and
can reveal a code or capture the terminal for the solving team.
Decision P4R5.

### Design

- `modes/hacking_terminal/`: role `terminal` `{ requires: [keypad],
  optional: [team_input, display, audio] }`; params `puzzle`
  (`code`, `wires`, `sequence`), `digits` (3-6), `lockout_s`,
  `reveal_code` (a string shown and sent on success, optional),
  `capture` (bool: the terminal becomes the solving team's zone),
  `lang`.
- The solving team: the team that pressed its input before typing
  (`team_input.press`), or the terminal's `team` param; with neither,
  `hacking.solved` has no team.
- Events: `hacking.solved` (47, critical) with data `puzzle` (key 36),
  `code` (10) and the team; the event is added to `events.yaml` here
  (protogen, a vector, the draft RFC). Wrong answers are not events
  (the screen shows them).
- Screens in Portuguese and English (`lang`), checked by the simulator
  and drawn by the Field Box and the app.
- A built-in preset on the Field Box (it has a keypad) and in the
  app's catalogue (the on-screen keypad).

### Files

`modes/hacking_terminal/{mode.yaml,node.lua,assets/screens/*.yaml,tests/*.yaml}`;
`protocol/schema/events.yaml` (+ generated files), `protocol/vectors/events.yaml`,
the draft RFC; Field Box presets; `app/lib/modes/builtin_modes.g.dart`;
the app's event texts (`app/lib/l10n/`); the console's `feed.events`
words; golden images; docs.

### Tests

YAML for each puzzle with a fixed `seed` (solved, a wrong answer and the
lockout, the code revealed, `capture`), `expect_screen` on each screen;
Dart through the core and golden images of the screens; Field Box host
tests with `keys`; three ESP-IDF builds.

**Built 2026-10-20 (in software; on a phone in the field: HW3).** What
differs from the design above, or fills what it left open (decisions M4-1
to M4-9):

- Portuguese name "Terminal de Hacking" (M4-1). The role is `terminal`
  `{ requires: [keypad], optional: [team_input, team_display, display,
  audio] }`; screens `hack_code`, `hack_wires`, `hack_sequence` and
  `hack_solved`, their texts in the templates in both languages (`lang`;
  the script sends which line, M4-8).
- Puzzle rules (M4-2): the code has different digits and the screen shows
  the last three guesses' counts; a wrong wire joins every wire again; the
  sequence (keys 1-9) is shown one a second after any key, and `*` shows
  it again. Every wrong answer locks for `lockout_s`, the puzzle stays
  (M4-3).
- The solving team is the last to press its button since the last solve,
  else `team` (M4-4). New parameter `points` (default 10); without
  `capture` the terminal stays solved; with `capture` it emits
  `zone.captured` and sets a new puzzle after 10 s that its holder cannot
  solve; the GM's owner override with `capture` only, and a mode command
  `reset` ("New puzzle") (M4-5).
- Seeded with the game's seed and the node's id; Field Box games picked on
  the box now get `esp_random()` seeds (they had 42) (M4-6).
- `hacking.solved` (47) and `puzzle` (36) in `events.yaml`, a vector built
  by hand from RFC 8949, the JSON Schema and an example, draft RFC 0000
  Amendment 2; the console's feed shows the revealed code, the players'
  feed does not (M4-7: the raw stream still carries it, for review).
- About 44 KB of a Reduced box's Lua heap loaded, and just under the
  simulator's bound composed with Codes, which it should not be combined
  with (M4-8).
- Field Box: the eleventh preset (second page, second entry), ten reference
  images, a host test that picks it, types a wrong guess, waits out the
  lock and solves it. App: the generated catalogue, five goldens, the
  players' feed text, the keypad shown from the start on a prop whose role
  requires it. Controller: an end-to-end case with a host box, which now
  prints the mode's screens (M4-9). Console: a browser test.
- Tests: 13 YAML files (each puzzle solved, wrong answers and the lock,
  `*` and short guesses, the code revealed, `capture` and a takeover, the
  GM's override and `reset`, English, three seeds, six digits, two
  terminals).

### Validation

```sh
python3 tools/docker_sim.py test modes/hacking_terminal
python3 tools/docker_app.py gen && python3 tools/docker_app.py && python3 tools/docker_app.py goldens
python3 tools/docker_fw.py test && python3 tools/docker_fw.py build
python3 tools/docker_console.py
# clean-copy check
```

---

## Plan phase 5: VIP / Payload

*Software, can be done now; real GPS: HW3. Depends on plan phase 3. Size M.*

### Goal

Escort a VIP player (tracked by the player app's position reports) or a
payload prop (an Android prop with GPS) to an extraction zone; checkpoint
boxes along the way. Decision P4R6.

### Design

- **VIP player.** The controller's `positions.py` hands each new report
  of a player whose check-in role is `vip` to the game's field script as
  the input `position.fix` (`player`, `team`, `role`, `lat`, `lon`,
  `acc`, `src`) through a new field operation; never logged as an event,
  never on the radio, MQTT or the stream, never in `state.field`. In the
  simulator, a test step `position: { player, team, role, lat, lon }`
  injects it.
- **Payload prop.** The Android prop shell delivers `gps.fix` (`lat`,
  `lon`, `acc`) from the location plugin to `node.lua` when the role
  requires `gps` (`app/lib/prop/`); the script checks the zone with
  `geo.in_zone()` and emits only `vip.extracted`.
- `modes/vip_payload/`: main mode with roles `checkpoint`
  (`team_input`: Domination-like capture, no local scoring) and
  `payload` (`requires: [gps]`, Android only); params `vip_team`,
  `extract_lat`, `extract_lon`, `extract_radius_m` (min 10),
  `checkpoint_points`, `end_on_extract`.
- `field.lua`: `position.fix` for the VIP inside the zone, or a
  `vip.extracted` from the payload, ends the game for `vip_team` with
  `game.win()` when `end_on_extract`; checkpoints score while held.
- Event `vip.extracted` (46, critical) with `player` (14) or the
  payload's node, and the team; added to `events.yaml` here.

### Files

`modes/vip_payload/*`; `core/src/script_api.c` and `node.h` only if a new
field operation is needed for inputs to the field script (otherwise the
controller delivers it as any input event to the field node);
`simulator/atalaia_sim/` (the `position` test step, checks that no event
carries coordinates); `controller/atalaia_controller/positions.py`,
`engine.py` (the hand-over); `app/lib/prop/` (`gps.fix` into the core);
`protocol/schema/events.yaml` (+ generated); docs.

### Tests

YAML: the VIP enters, leaves and re-enters the zone; a non-VIP player in
the zone does nothing; the payload's `gps.fix` inside and outside;
checkpoint scoring. Controller: a `POST /api/v1/positions` by a VIP
token ends the game; the stream and MQTT never carry the coordinates
(as the phase 3 privacy tests). Dart: a prop session with fake fixes.

**Built 2026-10-20 (in software; real GPS in the field: HW3).** What
differs from the design above, or fills what it left open (decisions M5-1
to M5-7):

- First, a fix for M4-7 (M5-1): data only staff may read is marked in the
  schema, `gm_only` on an event's data fields in `events.yaml` (generated
  by protogen) and `gm_only: true` on a mode's parameters; the controller
  (`visibility.py`) strips it from players' connections, the read token and
  MQTT. The site server's synced events and parameters are staff-only
  already (M5-2).
- The zone is one text parameter, `extraction` (`latitude,longitude`), with
  `radius_m`, `vip_points` (new: points at the extraction), `end_on_extract`,
  `checkpoint_points`, `tick_s` (new), `capture_hold_ms` and `lang`: the
  manifests have no number type and every join carries all of a main mode's
  parameters in 200 bytes (M5-3). A malformed zone stops the game from
  starting.
- No new field operation was needed: `positions.py` hands a VIP's GPS
  reports (oldest first, while the game runs on this controller) to
  `Controller.field_position`, which gives `field.lua` the input
  `position.fix`; fixes less precise than the zone do not count, nor do
  other players or another team's VIP (M5-4).
- One `node.lua` for both roles answers its own inputs (team inputs, or
  `gps.fix`); the app sends a `gps.fix` without a position when the game
  starts (M5-5). Checkpoints score in `field.lua`, counted in whole seconds
  held (M5-7).
- A Field Box preset after all, for the checkpoints (M5-6, amending P4R23):
  a box joins only modes it has as presets.
- Tests: 8 YAML files (the VIP enters; leaves and re-enters; others in the
  zone; the payload with no fix, a weak fix, the metres left and the
  extraction; once; no zone; checkpoints; the GM's override), in Python and
  in Dart through the core; `simulator/tests/test_vip_payload.py`;
  `controller/tests/test_vip_payload.py` (with the M5-1 tests);
  `app/test/prop/prop_gps_session_test.dart`; the Field Box host tests and
  reference images; app goldens; a console browser test.

### Validation

```sh
python3 tools/docker_sim.py test modes/vip_payload
python3 tools/docker_app.py
python3 tools/docker_fw.py test && python3 tools/docker_fw.py build   # the checkpoint preset (M5-6)
python3 tools/docker_console.py
# clean-copy check (the controller's tests run in tools/check.sh)
```

---

## Plan phase 6: Scenario packages and the objectives role package

*Software, can be done now. Depends on nothing (plan phase 3 for escort later). Size M.*

### Goal

The runtime that compiled scenarios need (decision P4R7): the
`kind: scenario` package and the built-in `org.atalaia.objectives`
role package, with the scenario events.

### Design

- `kind: scenario` in `simulator/atalaia_sim/mode.py`,
  `controller/atalaia_controller/modes.py` and the app's catalogue: a
  package with `mode.yaml` and `field.lua`, no `node.lua`, no roles; it
  must lead the composed id and be followed by at least one role
  package; it is never named in a box's join (the controller's joins
  already name "what that box runs"); uploads only (never built in).
- `modes/objectives/` (`org.atalaia.objectives`, `kind: role`): roles
  `objective` `{ requires: [team_input], optional: [keypad, nfc,
  display, audio, team_display] }` and `bomb_site` `{ requires:
  [team_input], optional: [keypad, display, audio, led] }`; each node
  waits for a `cmd.mode` `setup` from the field script (what it is
  for: capture with a hold time, a code, a tag count, a bomb's fuse),
  reports `zone.captured`, `code.used`, `tag.scanned`, `bomb.*` with
  no local scoring, and asks again after a reboot (`node.rebooted`
  makes the field script send `setup` again, as the Medic Kit's
  `heals`).
- Events 42-45 and data keys `objective` (34) and `scenario` (35)
  added to `events.yaml` (protogen, vectors, the draft RFC).
- A hand-written example scenario package
  (`modes/objectives/tests/fixtures/`) proves the runtime before the
  compiler exists.

### Files

`modes/objectives/*`; `simulator/atalaia_sim/mode.py`;
`controller/atalaia_controller/modes.py`, `engine.py` (joins);
`app/lib/modes/mode_catalog.dart`, `app/tool/gen_modes.dart`;
`protocol/schema/events.yaml` (+ generated), `protocol/vectors/events.yaml`;
Field Box presets (objectives); `modes/README.md`; docs.

### Tests

Simulator: composing `scenario + objectives` (and refusing a scenario
alone, a scenario after another part, a scenario with a `node.lua`);
the example scenario's YAML tests (capture, code, tags, bomb site, a
reboot and the `setup` sent again). Controller: install, the joins name
only `org.atalaia.objectives`. Dart: the catalogue and the role
package through the core. Field Box host tests and builds.

**Built 2026-10-20 (in software; not yet on radio hardware).** What
differs from the design above, or fills what it left open (decisions M6-1
to M6-9):

- Data keys 34 (`objective`) and 35 (`scenario`) as P4R1 and
  `events.yaml` had them (they were free); events 42-45 all critical;
  `objective` is `gm_only` on 42-44 (the M5-1 mechanism) until plan phase 8
  routes objectives per team (M6-2, M6-5).
- Composition (M6-1): a scenario leads the id, optionally followed by one
  main mode and its modifiers, then at least one role package; a modifier
  needs a main mode; the scenario's parameters are its `field.lua`'s and no
  join carries them; its `field.lua` runs first. The whole id still fits 63
  bytes (`org.club.foxhound+org.atalaia.objectives` is 40). Shared vectors:
  `protocol/vectors/composition.yaml` (simulator and Dart runner).
- The objectives package has no parameters: the language and the
  objective's name come in the `setup` (so it composes with the Medic
  Kit, whose `lang` would clash); `bomb_site` uses a screen and sound only
  (the plan's keypad and LED had nothing to do there) (M6-3, M6-4). `tags`
  counts players' own tags, or with `any` any card (the design
  specification's intel tags), for the team at the box. A wrong code is
  only on the screen, and `code.used` never carries the code.
- After a reboot the scenario also sends what the node lost (`holder`,
  `have`, an armed bomb's `armed` and `left`), and it sets up every second
  any node it has not set up yet (a box that joins late) (M6-3).
- No `node.role()` (M6-6): the setup's kind says what a node does.
  Objectives find their nodes by name (`field.nodes()`): the test's names in
  the simulator, a box's own name on the controller until plan phase 8
  assigns names in the console (M6-7).
- New test tooling: the `reboot` step and the `scenario:` key, in the
  simulator and the Dart runner; a `field.send` too large for a box's
  128-byte CMD buffer is now a problem in the simulator too (M6-9).
- Tests: 9 YAML files (capture, code, tags, intel cards, a bomb defused and
  one exploded, reboots, no scenario), `simulator/tests/test_scenario.py`,
  `controller/tests/test_scenario.py`, a host-box test in
  `test_box_e2e.py`, `app/test/modes/composition_vectors_test.dart`, the
  catalogue, a console browser test, the Field Box host tests and fifteen
  reference images, five app goldens.

### Validation

```sh
python3 tools/docker_sim.py test modes/objectives
python3 tools/docker_app.py gen && python3 tools/docker_app.py
python3 tools/docker_fw.py test && python3 tools/docker_fw.py build
# clean-copy check
```

---

## Plan phase 7: Scenario compiler and validator

*Software, can be done now. Depends on plan phases 3 and 6. Size L.*

### Goal

ADR-P4-6 as amended: a YAML scenario manifest compiles to a `kind:
scenario` package. The library is shared (`controller/atalaia_controller/scenarios/`,
decision P4-1), pure Python (stdlib, PyYAML), imported by the controller
and the site server.

### Files

| File | Licence | Purpose |
|------|---------|---------|
| `controller/atalaia_controller/scenarios/__init__.py` | AGPL-3.0-or-later | `compile_scenario(manifest) -> Package`, `validate(manifest) -> list[Problem]` |
| `.../scenarios/manifest.py` | AGPL-3.0-or-later | Parsing, defaults, the names of P4R8 |
| `.../scenarios/validator.py` | AGPL-3.0-or-later | Unique ids, references, DAG (topological sort), required params per type, time windows, zone geometry (radius >= 10 m warning, simple polygons), teams and squads that exist, sizes (every event under 200 bytes) |
| `.../scenarios/lua.py` | AGPL-3.0-or-later | Lua generation: string escaping, one block per objective type, dependency wiring, visibility, the `setup` commands |
| `.../scenarios/package.py` | AGPL-3.0-or-later | `mode.yaml` (kind `scenario`, `i18n.pt`) and `field.lua` of the package |
| `.../scenarios/__main__.py` | AGPL-3.0-or-later | `python3 -m atalaia_controller.scenarios compile|check scenario.yaml [-o dir]` |
| `controller/tests/test_scenarios.py` | AGPL-3.0-or-later | Unit tests |
| `controller/tests/scenarios/*.yaml` | AGPL-3.0-or-later | Valid and invalid manifests |
| `protocol/vectors/scenario.json` | GPL-3.0-or-later | Manifests with their expected problems, for any later implementation (the console's live checks, phase 5's editor) |

### Tests

Every objective type compiled and run in the simulator with the
objectives package (completion and failure emit 42/43; reveals 44;
`scenario.started` 45 at the start); the dependency chain of the
multi-objective example; time windows; `survive` against Respawn's
lives; `escort` with `position.fix`; Lua escaping of hostile texts (a
name with `]]`, quotes, newlines); every invalid manifest refused with
its reason; `Simulation.problems` empty in every run.

**Built 2026-10-20 (in software; not yet on radio hardware).** What
differs from the design above, or fills what it left open (decisions M7-1
to M7-9):

- The manifest (M7-1): ADR-P4-6's keys with P4R8's names (the game's team
  names, `squads` as a number, node names the GM gives the boxes, a player
  node `{ player: true, role: vip }` for `escort`), `lang` for the boxes'
  screens (each box shows the objective's name in that language),
  whole-number scenario `params` that an `effect.points: { param }` can
  use, and texts in English with `i18n.pt`. A key given twice is refused.
- The generated `field.lua` is a data table followed by one scenario
  runtime, `scenarios/runtime.lua` (GPL-3.0-or-later, since it is copied
  into every package, which is GPL too), instead of Lua templates per
  objective (M7-2); every manifest value reaches it as an escaped Lua
  literal and names must be one line (M7-3). `lua.py` writes the table
  and the setups; `package.py` writes `mode.yaml` with a `scenario:`
  block (names, teams, squads, nodes, each objective's assignee,
  visibility, dependencies and points, never a code or a destination)
  for plan phase 8 (M7-8).
- Semantics (M7-4, M7-5): an objective opens when revealed, its window has
  started and its dependencies are done; a hidden one is revealed when it
  could open or by another's `effect.reveal`; one still open at `end_min`
  fails (`time`); a failure fails its dependents (`blocked`); an objective
  never revealed sends nothing (P4R24); an objective of a team the game
  lacks is off. `capture_and_hold` takes `duration_s` 0 (at the capture)
  by default; `defend` starts held by the defenders; `survive` needs
  `time_window.end_min` and is judged then (scores freeze once a game has
  ended), from Respawn's per-team `lives_left` and `team.eliminated`;
  `escort` takes a circle or a polygon and `max_acc_m`. Squads travel as
  text in events (data key 2 is a string) (M7-7).
- The validator returns every problem as `(path, code, message, level)`
  (M7-6); a box serves one objective; the scenario id is at most 40
  bytes and not `org.atalaia.`. Shared vectors
  `protocol/vectors/scenario.json` (5 valid, 54 invalid), read by Python
  only: the app does not read manifests yet (M7-9).
- The command line also has `validate` (no core needed), and is reachable
  as `python3 -m atalaia_controller scenario ...`; `check` and `compile`
  need the core library unless `--no-core` (M7-9).
- Tests: `controller/tests/test_scenarios.py` (29 tests: the vectors and 3,000 mutated manifests,
  every type in the simulator, the multi-objective chain, windows,
  `survive` with Respawn, `escort` in a circle and a polygon, blocked
  dependents, hostile texts round-tripped through the core, the load
  check and an install, the command line, the import without the web
  stack) and `tests/scenarios/foxhound.yaml`, the hand-written example
  recompiled, which passes the objectives package's six YAML tests that
  play the hand-written one.

### Validation

```sh
docker run --rm -v "$PWD:/src" atalaia-dev sh -c "BUILD=/tmp/c sh tools/check.sh"
docker run --rm -v "$PWD:/src" atalaia-dev sh -c "cmake -S core -B /tmp/c -DATALAIA_SHARED=ON && cmake --build /tmp/c && cd controller && ATALAIA_CORE_LIB=/tmp/c/libatalaia_core.so python3 -m atalaia_controller.scenarios check tests/scenarios/multi_objective.yaml"
```

(2026-10-20: `check` loads the generated Lua in the core, so the second
command builds the core first; without it the command stops with exit
status 2, decision M7-9.)

---

## Plan phase 8: Scenarios in the controller, console and app

*Software, can be done now. Depends on plan phase 7. Size M.*

### Goal

A GM builds, checks and runs a scenario from the console, on a field
with no site server; players see their revealed objectives.

### Files and changes

- `controller/atalaia_controller/api.py`: `POST /api/v1/scenarios/check`
  (console token: problems for the editor), `POST /api/v1/scenarios`
  (GM: compile and install as a mode package), `GET /api/v1/scenarios`
  (console), `GET /api/v1/scenarios/{id}` (manifest and generated Lua,
  for the GM to read).
- `ws.py`, `api.py` `make_route`, `PLAYER_TYPES`: objective events to
  the assigned team and squad, all to staff, hidden ones never before
  their reveal (P4R24).
- `controller/console/src/components/scenario-builder.js`: a YAML editor
  with the problems listed, the node names to assign in the Join tab,
  pt and en.
- The app's player view: objectives with the scenario's translated
  names (from the game's setup) and their state.

### Tests

Controller unit tests for each endpoint and the routing; console browser
tests (build, check, install, run a two-objective scenario on host
boxes); Dart widget and golden tests of the objectives in the player
view; the on-device test gets one case.

**Built 2026-10-20 (in software; not yet on radio hardware or a real phone
in the field).** What differs from the design above, or fills what it left
open (decisions M8-1 to M8-9):

- The endpoints (M8-1): `check` answers every problem even for a text that
  is not a manifest (`bad_manifest`) and, without errors, loads the
  compiled Lua in the core (`lua_does_not_load`); `POST` refuses with the
  problems (400), or 409 when the live game runs the scenario or the id is
  another kind of package; `GET /api/v1/scenarios/{id}` is the GM's only
  (the Lua holds the codes). The manifest is kept in the settings table
  (`scenario.manifest:<id>`), and so are the boxes' names per game: no
  schema change (M8-2).
- The routing (M8-4, M8-5): `visibility.objective_visible` and
  `scenario_event` (`visibility.py`), read from the package's `scenario:`
  block; anyone the objective is not for gets the event without
  `objective`, as M6-5 did; MQTT is unchanged. The game carries the
  scenario's names and, for a player, only the objectives that player may
  know (a hidden one once revealed); the controller sends the game again at
  a hidden objective's reveal. The routing lives in `engine.py`
  (`event_for`, `players_game`) and `api.py` (`make_route`, the first
  message, the log); `PLAYER_TYPES` did not change.
- The Join tab (M8-6): a scenario box's name in the join sets its role;
  `field.nodes()` returns it. The console's builder asks the controller
  instead of reading `protocol/vectors/scenario.json` in JavaScript (M8-7);
  its tab is *Cenários* / *Scenarios*, between *Predefinições* and *Registo*.
- M6-1 (a standby needs the scenario): a standby that lacks it refuses the
  join with the parts to install and how (M8-3); carrying it automatically
  is left to plan phase 20. A game whose id is over 63 bytes is refused at
  creation (M8-9).
- The app (M8-8): a "Objetivos do cenário" section in the player view;
  the events name the objectives the player knows.

### Validation

```sh
python3 tools/docker_console.py
python3 tools/docker_app.py && python3 tools/docker_app.py goldens
# clean-copy check
```

---

## Plan phase 9: ATAK / CoT emitter

*Software, can be done now; a real ATAK device: HW3. Depends on plan phase 3. Size M.*

### Goal

ADR-P4-7 as amended (P4R18): props and zones on ATAK maps over the field
Wi-Fi.

### Files and changes

| File | Licence | Purpose |
|------|---------|---------|
| `controller/atalaia_controller/atak.py` | AGPL-3.0-or-later | CoT XML (escaped), type mapping, UIDs, staleness, UDP multicast sender, optional TCP senders to staff endpoints |
| `controller/atalaia_controller/config.py`, `controller.example.toml` | (existing) | `[atak] enabled = false`, `multicast`, `port`, `interval_s`, `staff_endpoints = []`, `players = false` |
| `controller/atalaia_controller/api.py`, `store.py` | (existing) | `PUT /api/v1/field/georef` (GM): two image corners with lat and lon; schema 5 |
| `controller/console/src/components/` | (existing) | Placing the two corners on the field image |
| `controller/tests/test_atak.py` | AGPL-3.0-or-later | Tests |
| `protocol/vectors/cot.xml` (or `cot.json`) | GPL-3.0-or-later | Known-good CoT samples, cited from the CoT specification's examples |

### Tests

XML parses, `uid`, `type`, `time`/`stale`, `point` from the georeference
(an image position of 0.5, 0.5 lands in the middle of the two corners),
`__group` from the owner's colour; a captured zone is sent at once;
nothing is sent while `enabled` is false; **no player position is ever
multicast**, staff endpoints only with `players = true`; a receiver on
the loopback in the test gets the datagram.

**Built 2026-10-20 (in software; a real ATAK device: HW3).** What
differs from the design above, or fills what it left open (decisions M9-1
to M9-10):

- `protocol/vectors/cot.json`, not `cot.xml`: the CoT rules the emitter
  must follow and the values of two TAK example events (`Marker -
  Spot.cot`, `Marker - 2525.cot`), each with its source (the CoT
  base-event schema, MITRE's CoT types, the TAK detail schemas and
  examples, the TAK protocol description, the Developer's Guide to CoT).
  The values only, not the files: the ATAK-CIV repository's licence is
  not a plain one (M9-1). The emitter rebuilds both examples as known
  answers.
- Types (M9-2): every box and the extraction zone are coloured spot
  markers, `b-m-p-s-m` (how `h-e` for a box placed on the image, `h-p` for
  the pasted extraction point); players `a-f-G-U-C` (`m-g`). ADR-P4-7's
  `a-n/a-f-G-E-X`, `a-f-G-U-C-V` (aviation in MITRE's list) and
  `b-m-p-s-p-i` (a sensor point of interest) are not used. UIDs are
  `atalaia.{field_id}.node.{id}`, `...game.{id}.extraction` and
  `...player.{player_id}`, never a user's name.
- The colour (M9-5): `<color argb>` with the console's team colour for
  every owned marker, and `<__group name role="Team Member">` for a team
  named after one of ATAK's 14 team colours (red, blue, green, yellow,
  orange, purple, white, in English or Portuguese); other teams have the
  colour and their display name in the remarks.
- The georeference (M9-3, M9-4): two points are opposite corners of a
  north-up image (latitude and longitude each linear in the image); 3-8
  points (API only) give a least-squares affine map; degenerate, mirrored
  and inconsistent points are refused. Kept in the store's `settings`
  table (`field.georef`), so no store schema change (the plan's "schema
  5" was taken by the sync). A new or removed image clears it.
- Configuration: `multicast = "host:port"` instead of a separate `port`;
  TTL 1, not the ADR's 2; at most 8 staff endpoints; `interval_s` 1-3600.
- Transport (M9-7): TAK Protocol version 0 on both: one event per
  datagram; on TCP one connection per endpoint and cycle, each event with
  its XML declaration and a newline, no length prefix (the ADR's sketch
  had one; TAK's raw CoT input has none).
- Staff endpoints (M9-6): every player's latest GPS fix (staff see all, as
  the GM and marshals do), callsign the pseudonymous player id (with
  "VIP"), never the name; also the boxes and the zone.
- Only the controller in charge sends (a standby does not); at a game's
  end or when the georeference goes, each marker is dropped with a stale
  time before its start (M9-8). The UDP socket is opened on the first
  send and closed when the emitter stops.
- The console (M9-9): under the field image, the GM pastes the top-left
  and bottom-right corners as `latitude, longitude`; the four corners
  come back, with a pin per point on the image, and the feed's state
  (`GET /api/v1/atak`).
- Not built (M9-10): the remote ATAK relay through the site server
  (ADR-P4-7's amendment); it belongs with the site server's work on the
  controller's link (plan phase 19).

Tested: `controller/tests/test_atak.py` (35 tests) and the console's
`test_field_georeference_two_corners`.

### Validation

```sh
docker run --rm -v "$PWD:/src" atalaia-dev sh -c "BUILD=/tmp/c sh tools/check.sh"
python3 tools/docker_console.py
```

---

## Plan phase 10: Site server skeleton and its test tooling

*Software, can be done now. Depends on nothing. Size M.*

### Goal

The `server/` application and the tooling every later plan phase uses:
FastAPI app factory, configuration, the async database layer, the first
Alembic migration (fields, users, roles, user_field_roles, sessions,
audit_log), `/api/v1/health` and `/api/v1/metrics`, security headers,
the image, the test Compose file, `tools/docker_server.py` and the CI
job. Decisions P4R9, P4R16, P4R17.

### Files

| File | Licence | Purpose |
|------|---------|---------|
| `server/atalaia_server/__init__.py`, `app.py`, `config.py`, `db.py`, `models.py`, `security_headers.py` | AGPL-3.0-or-later | The package (named like the controller's, not `src`, decision D15) |
| `server/atalaia_server/api/health.py` | AGPL-3.0-or-later | Health and metrics |
| `server/migrations/env.py`, `server/alembic.ini`, `server/migrations/versions/0001_base.py` | AGPL-3.0-or-later | Async Alembic; the base tables only (each later plan phase adds its own migration) |
| `server/requirements.in`, `server/requirements.txt` (hash-pinned) | AGPL-3.0-or-later | Dependencies (P4R16) |
| `server/Dockerfile` | AGPL-3.0-or-later | Stage 1 builds `libatalaia_core.so` (the core) with cmake; stage 2 `python:3.12-slim` with the requirements, `server/`, `controller/atalaia_controller/` and `simulator/atalaia_sim/` (the shared Python), the core library; a `test` target adds the tests |
| `server/docker-compose.yml` | AGPL-3.0-or-later | The server and `postgres:16-alpine` (Caddy in plan phase 22) |
| `server/docker-compose.test.yml` | AGPL-3.0-or-later | An ephemeral `postgres:16-alpine` (tmpfs, health check) and the test image |
| `server/tests/__init__.py`, `base.py`, `test_health.py`, `test_migrations.py`, `test_shared_imports.py` | AGPL-3.0-or-later | `unittest` base classes: a fresh database per test class, an httpx ASGI client; the shared modules import without FastAPI on the controller's side |
| `tools/docker_server.py` | GPL-3.0-or-later | `test`, `migrations`, `build`, `up`, `down` |
| `.github/workflows/ci.yml` | (existing) | New job `server`: build the test image, `services: postgres: image: postgres:16-alpine`, run the tests and the migration round trip |
| `server/README.md`, `tools/README.md`, `README.md`, `CHANGELOG.md`, site | (existing) | Docs |

### Validation

```sh
python3 tools/docker_server.py test
python3 tools/docker_server.py migrations     # upgrade head, downgrade base, upgrade head
docker run --rm -v "$PWD:/src" atalaia-dev sh -c "BUILD=/tmp/c sh tools/check.sh"   # unchanged parts still pass
```

**Built 2026-10-19** (in software; decisions S10-1 to S10-12). Differences
from the table above, as built: the tests' own dependencies are in
`server/requirements-test.in`/`.txt` (the server image has no httpx);
`atalaia_server/ids.py` makes the UUIDv7 keys; `server/tests/run.sh` is the
one entry point the tool and CI share; `test_config.py` and `test_ids.py`
join `test_shared_imports.py` as the plain-Python tests that tools/check.sh
and CI's `controller` job also run; `server/Dockerfile.dockerignore` narrows
the build context; `fields` has no `api_key_hash` (plan phase 13's
`field_api_keys`); `/api/v1/metrics` uses a token until plan phase 11; the
app starts with `uvicorn --factory atalaia_server.app:create_app`; the
migration round trip ends with `alembic check`.

---

## Plan phase 11: Accounts, sessions and roles

*Software, can be done now. Depends on plan phase 10. Size M.*

ADR-P4-2 as written: registration, login, `login/totp`, refresh with
rotation and replay detection, logout, TOTP enrolment (Fernet-encrypted
seeds), the breached-password list, rate limits, per-field and per-game
roles (player, squad_leader, vip, marshal, gm, spectator, admin) with
TOTP required for admin, gm and marshal, the audit log, `python -m
atalaia_server create-admin`. Migration `0002_accounts`. Tests:
`server/tests/test_auth.py`, `test_roles.py` (as the old phase A
listed). Validation: `python3 tools/docker_server.py test` and
`migrations`.

**Built 2026-10-19** (in software; decisions S11-1 to S11-15). Differences
from the text above, as built: **per-game roles wait for plan phase 13**
(`user_game_roles` needs its `games` table, S11-6, as S10-5 had it), so
plan phase 13 adds them; refresh tokens are opaque random values kept as
SHA-256 in a new `refresh_tokens` table, not JWTs (S11-1); every request
re-reads the session and the roles from the database (S11-2); a
`users.server_admin` flag for the site server's own administrator, made by
`create-admin`, and the smallest fields API (`POST`/`GET /api/v1/fields`)
so roles can be granted (S11-7); `GET /api/v1/metrics` is for server
administrators, with `ATALAIA_METRICS_TOKEN` kept as an optional monitoring
credential (S11-9); the new modules are `passwords.py`, `totp.py`,
`tokens.py`, `ratelimit.py`, `auth.py`, `audit.py`, `cli.py`,
`api/auth.py` and `api/fields.py`, with the breached list in
`atalaia_server/data/`; `test_passwords.py`, `test_totp.py` (the RFC 6238
and RFC 4226 vectors), `test_tokens.py` and `test_ratelimit.py` need no
database but need the server's dependencies, so they run in the server's
image only (`docker_server.py test`, CI's `server` job), not in
tools/check.sh.

---

## Plan phase 12: Personal data

*Software, can be done now. Depends on plan phase 11. Size M.*

ADR-P4-8 as amended: `GET /api/v1/me/data`, `GET /api/v1/me/export`
(ZIP of JSON), `DELETE /api/v1/me` (anonymise, keep signatures),
`PATCH /api/v1/me`; the daily retention purge (`python -m atalaia_server
purge`); `docs/templates/privacy-notice-{pt,en}.md` and
`dpa-template.md` (marked for legal review, P4-6). **Rule for every
later plan phase:** a table with personal data is added to access,
export, erasure and the purge in the same plan phase. Tests:
`test_personal_data.py`. Portuguese templates in pt-PT, inclusive.

**Built 2026-10-19** (in software; decisions S12-1 to S12-8). Differences
from the text above, as built: the module that knows every personal data
table is `atalaia_server/personal_data.py` (access, export, erasure, the
purge; later plan phases add their tables there) with the routes in
`api/me.py`; `PATCH /api/v1/me` changes the username and email and
`POST /api/v1/me/password` the password (ending the other sessions), both,
and `DELETE /api/v1/me`, only with the current password (erasure with a TOTP
code too, S12-3); erasure keeps an anonymised `deleted-...` tombstone, keeps
the person's audit rows without their addresses and logs itself with no
account (S12-4); consents get their own table, `consents`, with the privacy
notice's version (`ATALAIA_PRIVACY_NOTICE_VERSION`, S12-5) in migration
`0003_personal_data` (so sync is `0004_sync`, S12-7); the purge (sessions 30
days after they end, the audit log after 36 months) runs inside the server
every day at `ATALAIA_PURGE_HOUR` and as `python -m atalaia_server purge
[--dry-run]` (S12-6); the export's game, chrono and event files come with
their tables (S12-2); the DPA template is in English only until the legal
review (S12-8). Also in this plan phase: the login lockout is now per
(address, username), with a per-address ceiling of 50 failures (S11-12,
S12-1).

---

## Plan phase 13: Controller sync

*Software, can be done now; over a real 4G link: HW1. Depends on plan phases 10 and 11. Size L.*

### Goal

ADR-P4-3 as amended: the controller opens the link and pushes its
games; the site server stores them. Decisions P4R10-P4R13.

### Site server

- Migration `0004_sync` (*renamed 2026-10-19: plan phase 12 took `0003_personal_data`, decision S12-7*): `field_api_keys` (SHA-256, two active during a
  rotation), `controllers` (controller_id, last seen, version),
  `games` (UUID, `field_id`, `game_id`, `game_seed`, mode id, teams,
  team info, params, times, state; unique `(field_id, game_id,
  game_seed)`), `game_events` (unique `(game, node_id, seq,
  game_time_ms, event_type)`, `data` JSONB, `epoch`, `pkt_seq`,
  `received_at`), `game_node_scores` (`(game, node_id, team)`,
  `value`, merged by `GREATEST`), `nodes` (per game: name, role, info).
- `POST /api/v1/sync/games` (create or update a game's metadata),
  `POST /api/v1/sync/events` (a batch: `{game, after_id, events: [...]}`,
  the controller's own event ids; answers `acked_id`, inserted and
  duplicate counts), `POST /api/v1/sync/scores` (per node counters),
  `POST /api/v1/sync/nodes`, `WS /api/v1/sync/stream` (the controller
  connects; live events and scores one way, remote commands the other
  way from plan phase 19).
- The batch format is shared: `protocol/sync.md` and
  `protocol/vectors/sync.json` (valid and invalid batches), read by the
  controller's client and the site server.

### Controller

- `controller/atalaia_controller/sync_client.py` (AGPL): a thread with
  backoff (30 s during a game, 5 min between, doubling on failure,
  capped at 5 min), the cursor per game in a new `sync_state` table
  (store schema 5), the API key from `[sync] api_key`,
  `ATALAIA_SYNC_API_KEY` or `python3 -m atalaia_controller sync-key`,
  `[sync] url`, `enabled = false` by default; the site server's TLS
  checked against the system CAs (or a pinned CA in the config).
- Never sent: positions, check-in names (until plan phase 16 defines
  what goes back), tokens, keys.

### Tests

Site server: API key accepted, wrong or missing refused; a batch, the
same batch again (duplicates counted, nothing doubled), an out-of-order
batch; a GM's negative adjustment lowers the derived total; a standby
controller's events for the same `(game_id, game_seed)` land in the same
game; the 16-bit `game_id` reused months later is a new game; the sync
vectors. Controller: against a small in-process HTTP server (no
PostgreSQL): cursor, replay after a restart, backoff, nothing private in
any request body (checked field by field). End to end: the controller's
client against the real site server in `docker-compose.test.yml`
(`server/tests/test_sync_e2e.py`, the controller package run in the test
image).

### Validation

```sh
python3 tools/docker_server.py test && python3 tools/docker_server.py migrations
docker run --rm -v "$PWD:/src" atalaia-dev sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**Built 2026-10-20** (in software; decisions S13-1 to S13-12). Differences
from the text above, as built: the shared batch check is
`controller/atalaia_controller/sync_format.py` (plain Python; its vector tests
run in tools/check.sh) and the site server's side is `atalaia_server/sync.py`
with `api/sync.py`; `nodes` is `game_nodes`, child tables point at a game with
a `game` column, and the score counters' key is `(game, source, team)` with
sources `node-<id>` and `field-<run>@<controller node id>` (a controller's
field-script runs, S13-3); `user_game_roles` came here (S11-6) with
`/api/v1/games/{game}/roles` and a small games API (`api/games.py`); API keys
are managed by the field's admin at `/api/v1/fields/{field}/sync-keys`
(S13-7); a standby's "ended" does not end a game, a `game.end` event does
(S13-5); the WebSocket is built on the site server, authenticated on the
upgrade, but the controller's client uses HTTP only until plan phase 19
(S13-8); the client is standard-library urllib (no new controller
dependency); `sync_state` also keeps hashes of what was last sent, so a
cycle sends only what changed; `python3 -m atalaia_controller sync-key`
also has `--status`, `--clear` and `--resend`; game history is purged 24
months after a game ended (S13-10). The end-to-end test runs the real
controller engine and client against the site server under uvicorn in the
test image on the test PostgreSQL.

---

## Plan phase 14: Chrono registry

*Software, can be done now; with a real chronograph: HW4. Depends on plan phase 13. Size M.*

ADR-P4-5 as amended (P4R14, P4R15). Migration `0005_chrono` (*renamed 2026-10-19, S12-7*):
`marshal_keys` (marshal_id, public key, from/until, the account it is
linked to), `replicas` (the app's `replica_id` UUID, the per-field
owner, type including `sniper`, class, make and model), `chrono_readings`
(`reading_id` unique, `record_json` verbatim, the fields of
`protocol/chrono-record.md` as columns for queries, series and outcome,
`verified_at`), `chrono_violations`, consents for sharing. Sync:
`POST /api/v1/sync/marshals`, `POST /api/v1/sync/chrono` (readings, the
controller's series and outcomes), `POST /api/v1/sync/replicas`; each
reading verified with `atalaia_controller.chrono.verify` against the
marshal's key valid at its time; a record that fails is kept apart and
reported, never silently dropped. Queries for staff and the player's
own history; cross-field history only with both fields' and the
account's consent. Tests: the shared `protocol/vectors/chrono_record.json`
through the sync endpoint (every valid one accepted, every invalid one
refused with its reason), a rotated key, a reading uploaded twice,
erasure keeps the record and drops the link to the person.

**Built 2026-10-20** (in software; decisions S14-1 to S14-12). Differences
from the text above, as built: the three sync bodies belong to the field,
not a game (no `game` in them), with 3 valid and 20 invalid new shared
vectors in `protocol/vectors/sync.json`; a reading's record travels as the
JSON text the controller stored, verified by `atalaia_server/chrono_verify.py`
(plain Python over `atalaia_controller.chrono`, its tests in tools/check.sh)
against the keys of its marshal valid when the **controller** received it
(S14-2), and stored by `atalaia_server/chrono_registry.py`; a reading that
fails goes to `chrono_rejects` and is named in the answer, and one kept apart
for want of its marshal's key is checked again when the key arrives;
violations are failed or warned spot checks only (S14-7). On the controller,
store schema 6 adds `marshal_key_history` (a rotation keeps the old key's
period) and `sync_items` (S14-4). `field_player_ids` is made here, not in
plan phase 16 (S14-3); consents gain `field_id` for the per-field
`chrono_sharing` consent, and sharing needs both fields and the person's
consent for each (S14-5). Also: a marshal's account registers its phone's
public key (`/api/v1/fields/{field}/marshal-keys`), a field's admin revokes a
key, switches sharing (`PATCH /api/v1/fields/{field}`) and erases a player's
chrono data (S14-10); the person's history is `GET /api/v1/me/chrono`; the
staff views are `api/chrono.py` (S14-6). `GET /api/v1/sync/chrono` (the
controller pulling other fields' records) waits for plan phase 16's roster.

---

## Plan phase 15: Scheduling, field pages and feeds

*Software, can be done now. Depends on plan phase 11. Size M.*

ADR-P4-11 (scheduling and publication) and ADR-P4-12 (feeds), as
written; files as the old phase I listed, under
`server/atalaia_server/`: `api/scheduling.py`, `services/scheduling.py`,
`web/field_pages.py` and templates (pt and en, no JavaScript),
`feeds/ical.py`, `feeds/json_feed.py`, `server/schemas/games-feed-v1.schema.json`,
`server/docs/feeds.md`. Migration `0005_scheduling`. Tests:
`test_scheduling.py`, `test_field_pages.py`, `test_feeds.py`; the
iCalendar writer is checked against RFC 5545's own examples (folding,
escaping, `DTSTART` in UTC), not only against itself.

**Built 2026-10-20** (in software; decisions S15-1 to S15-15). Differences
from the text above, as built: the migration is `0006_scheduling` (0005 is
the chrono registry's) and holds only this plan phase's half of ADR-P4-11's
columns, `scheduled_games` and the field page's columns on `fields`;
registrations and `controller_game_id` are plan phase 16's (S15-1). Times are
`starts_at` and `ends_at` (S15-2); `registering` is computed, not stored
(S15-3). The pages use `string.Template` files and `html.escape`, no
template engine (S15-8), with one style sheet, `/static/field.css`; the feeds'
writers are `atalaia_server/feeds/` (plain Python, also run by tools/check.sh
in `tests.test_feeds`), the rules `services/scheduling.py`, the staff API
`api/scheduling.py`, the field page's settings on `PATCH
/api/v1/fields/{field}`. New setting `ATALAIA_PUBLIC_URL` for links and UIDs
(S15-10). Until plan phase 16 nothing can be registered for: the feed's
`registration.open` is false and the pages have no registration button
(S15-7).

---

## Plan phase 16: Registration and game-day sync

*Software, can be done now. Depends on plan phases 13 and 15. Size L.*

ADR-P4-11's registration and game-day sync, against the check-in that
phase 3 built (`protocol/checkin.md`, `controller/atalaia_controller/checkin.py`):

- Site server: registrations with pre-declared replicas (classes from
  the field's limit template: the controller's template names, as
  `app/lib/chrono/limit_templates/`), per-field `player_id` of the
  phase 3 form (`p-` + 12 base32) made once or adopted from the phone's
  field identity with its secret (the SHA-256 compared, as the
  controller does; *the `field_player_ids` table itself was made by plan
  phase 14's `0005_chrono`, decision S14-3, 2026-10-20*), ticket secrets (SHA-256 kept), `GET
  /api/v1/sync/schedule`, `GET /api/v1/sync/roster`, `POST
  /api/v1/sync/checkins`; migration `0006_registration`.
- Controller: `sync_client.py` pulls the schedule and roster until the
  game starts; `checkin.py` gets **expected** check-ins (a new
  `status = 'expected'`, store schema 6, *now the next free number: plan
  phase 14 took 6, decision S14-4, 2026-10-20*) with their declarations
  `pending` in the "replicas to chrono" list, check-in by registration
  id and ticket secret (`POST /api/v1/checkin` gains `registration_id`
  and `ticket`), a printed `atalaia:ticket:` code scanned by a marshal
  (the poster codec's sibling, with vectors in `protocol/checkin.md`
  and `protocol/vectors/checkin.json`); outcomes pushed once.
- Console: *Create from the schedule*; expected, arrived and walk-in
  columns. App: account login on the site server, the field's games,
  registering with replicas, the ticket kept and sent at check-in.
- Tests as the old phase I listed (`test_registrations.py`,
  `controller/tests/test_sync_schedule.py`), plus the ticket vectors in
  Python and Dart.

**Built 2026-10-20** (in software; decisions S16-1 to S16-14). Differences
from the text above, as built: the migration is `0007_registration` (0006 is
the schedule's) with `game_registrations`, `registration_replicas`,
`player_id_claims`, `scheduled_games.controller_game` (a `games.id`, S13-6's
rule) and `walkins`, and the field's `limit_template` and `max_replicas` for the
replicas' classes (S16-1, S16-6); the controller's store schema is 7, not 6
(S14-4), with `schedule_games`, `schedule_links` and three columns on
`checkins` (S16-2). The roster is `GET /api/v1/sync/roster?scheduled_game_id=`;
the controller also pulls `GET /api/v1/sync/claims` and pushes `POST
/api/v1/sync/claims`: an account's adoption of a phone's player id is
confirmed by the controller, which alone holds the secret's hash (S16-4). The
answers the controller pulls are checked by `sync_format.ANSWERS` on both sides,
with 4 valid and 14 invalid new vectors, and 4 valid and 15 invalid new body
vectors (S16-3). The ticket codec is `checkin_ticket.py` and
`app/lib/protocol/checkin_ticket.dart`, with its vectors in `checkin.json`
(`tickets`). Outcomes go back once the game has ended, not during it (S16-11).
The player's account API is `api/registrations.py` (`/api/v1/fields/{field}/
scheduled-games/{id}/registrations`, `/api/v1/me/registrations`,
`/api/v1/me/player-ids`); the public game page has *Register* only while the
window is open and places are left, leading to a page that says how to register
in the app (no form on the pages, S16-9); the pages and feeds answer `HEAD`
(S16-10). The console has *From the schedule*, expected rows with *Arrived*, a
ticket box and the registered and walk-in counts. Not built here: the app's
screens (account login, the field's games, registering, keeping and sending the
ticket; the app's Dart ticket codec is built), `[sync] push_walkins` and the
guest registrations it implies (S16-13).

*App screens built 2026-10-20 with plan phase 17 (decisions S17-9 to S17-16):*
*Participante › Inscrições online* logs in to the field's site server (password,
then TOTP; the refresh token rotated), lists the field's games through a new
`GET /api/v1/fields-by-slug/{slug}`, registers with replicas, keeps the ticket on
the phone (QR and text) and can send it with the app's check-in, changes and
cancels, and claims the phone's player id; the public register page links to it
with `atalaia://register?site=&field=&game=` (or its address pasted). Still not
built: making an account in the app (S17-16), `[sync] push_walkins`.

---

## Plan phase 17: Registration import and platform adapters

*Software, can be done now. Depends on plan phase 16. Size S.*

ADR-P4-12's import (CSV per RFC 4180 and JSON, only the listed columns,
dry run, upsert by `(source, external_ref)`) and the `PlatformAdapter`
interface with a test adapter, off by default, encrypted configuration,
every call audited; `server/docs/integrations.md`. No adapter for a
named platform (F22). Tests: `test_registration_import.py`,
`test_integrations.py`.

**Built 2026-10-20** (in software; decisions S17-1 to S17-17). Differences from
the text above, as built: the migration is `0008_integrations`, with the two
adapter tables only (the import's `source` and `external_ref` came with
`0007_registration`, S17-1); the code is `atalaia_server/integrations/`, not
`server/src/integrations/`. The import is
`POST .../registrations/import?source=&dry_run=&basis_confirmed=` (a real
import needs the staff to confirm the field's basis for the list, S17-4), with
the format in `import_format.py` (plain Python, also run by tools/check.sh in
`tests.test_import_format`), at most 1 MiB and 5,000 rows, row-level codes, and
the rules of S17-3 (cancelled ones skipped, missing ones listed, never
cancelled). A CSV export of a game's registrations, safe from spreadsheet
formulas and importable back, is added (S17-17). Imported registrations are
guests, deleted 30 days after their game (S17-5). Adapter calls happen only
when the staff ask (`.../integrations/{adapter}/push`, `.../registrations`),
with 20 seconds each, every call audited (S17-7); the test adapter is offered
only with `ATALAIA_TEST_ADAPTER=on` (S17-6). The app's registration screens that
plan phase 16 left out (S16-13) were built at the same time (S17-9 to S17-16).
AC-19 also runs `tests.test_import_format`.

---

## Plan phase 18: Club profiles and branding sync

*Software, can be done now. Depends on plan phase 13. Size M.*

Decision P4R19. Site server: clubs (name, slug, logo, crest, colour,
members with a club role), the field's branding and saved teams edited
there, images checked with the controller's `images.py` (imported, the
same limits: logo 1 MiB and 16-2048 px, wallpaper 4 MiB and 320-4096 px,
crest 512 KiB and 16-1024 px, PNG/JPEG/WebP, metadata stripped), the
rights reminder at every upload, public club pages off by default with
a report button and an admin who can hide them. `GET
/api/v1/sync/field` carries the branding (with image SHA-256s) and the
saved teams; the controller fetches changed images and applies them
when `[sync] branding = "site"` (default `"local"`). Tests on both sides,
including a crest that follows a team to a second field's controller.

*Built 2026-10-20 (decisions S18-1 to S18-12, open; in software, tested
against PostgreSQL in Docker and the real controller, not yet on a real
deployment):* migration `0009_clubs` (`branding_images`, `clubs`,
`club_members` with invitations the person accepts, `club_reports`,
`field_teams`, the field's branding columns); `api/clubs.py`,
`api/branding.py`, `services/branding.py`, `web/club_pages.py`; `GET
/api/v1/sync/field` and `GET /api/v1/sync/images/{sha256}` checked by
`sync_format.check_field`; the controller's `[sync] branding`,
`SyncClient._site_branding` and `Branding.apply_site`. A club's teams carry a
`short_name` (32 characters at most, what fits a controller's team name);
the field's branding name is its own setting (48, the poster's limit), not the
field's name.

---

## Plan phase 19: Device health, firmware catalogue and remote GM

*Software, can be done now. Depends on plan phase 13. Size M.*

ADR-P4-3 and RESEARCH section 8 as amended (P4R12): device health from
synced `node.online`, `battery.low`, `node.offline` events and node
STATE (battery, firmware, RSSI, last seen); a firmware catalogue (list
only: OTA is not built yet); the remote GM: a site-server user with the
`gm` role on the field sees the live game through the controller's
WebSocket and sends commands back on it, only when the controller sets
`[sync] remote_gm = true`, limited to start, pause, resume, end, GM
messages and declared mode commands, each logged on both sides (the
controller's `audit` entries, the site server's audit log). Tests:
`test_devices.py`, `test_remote_gm.py` (a command refused while
`remote_gm` is off, refused for a command outside the list, refused for
a user without `gm` on that field), and the controller's side.

*Built 2026-10-20 (decisions S19-1 to S19-11, open; in software, tested
against PostgreSQL in Docker and the real controller, not yet on a real
deployment or over 4G):* migration `0010_firmware` (`firmware_releases`; device
health needs no table); `services/devices.py` with `api/devices.py`
(`/api/v1/fields/{field}/devices`, `/api/v1/games/{game}/devices`: a device is
its node name across games, S19-9); `firmware.py` with `api/firmware.py` (a list
only, entries signed with Ed25519 by a key in `ATALAIA_FIRMWARE_KEYS`, checked
again at every listing, S19-8); `remote_gm.py` with `api/remote_gm.py`
(`/api/v1/fields/{field}/remote-gm`, `.../commands`, `.../log`) over the
stream's new `hello`, `live`, `command` and `command.result` messages, checked by
`sync_format.STREAM` with 13 valid and 24 invalid shared vectors (S19-3). Only the
field's `gm` in a TOTP session may act (S19-4); the controller checks every
command again (S19-5). The controller's "`audit` entries" are a new table,
`remote_commands` (store schema 8), with `remote_gm.py`, `ws_client.py` (its own
RFC 6455 client, S19-2), `[sync] remote_gm` and `GET /api/v1/remote-gm` (S19-6).
The site server gained `wsproto` so uvicorn serves the stream at all (S19-1).
Not built: the remote ATAK relay that decision M9-10 had deferred here (S19-10),
positions in the remote view (S19-7), a GM web page on the site server and the
console's screen for the log (S19-11). Tests: `test_devices.py`,
`test_firmware.py`, `test_remote_gm.py`, `test_remote_gm_e2e.py` (the real
controller under uvicorn) and the controller's `test_remote_gm.py`.

---

## Plan phase 20: Game history and the scenario library

*Software, can be done now. Depends on plan phases 13 and 7. Size M.*

Game history (list, detail, event log by type and time, score timeline
derived from per-node counters), spectator views with a delay, a public
scoreboard per field when the field turns it on; the scenario library
on the site server (`/api/v1/scenarios`: validate and compile with the
shared library and the core's load check, P4R9; store, version) pushed
to the controller with presets in `GET /api/v1/sync/presets`, where the
controller installs and checks it again. Tests: `test_games.py`,
`test_scenarios_api.py`.

*Built 2026-10-20 (decisions S20-1 to S20-8, open; in software, tested
against PostgreSQL in Docker and the real controller, not yet on a real
deployment):* migration `0011_history` (written beside plan phase 19's
`0010_firmware` and chained after it: `field_history_settings`,
`game_score_samples`, `field_scenarios`, `field_scenario_revisions`,
`field_presets`), models in `atalaia_server/history_models.py`;
`api/history.py` and `services/history.py` (the field's history with
filters, a game's score timeline from the per-node counters as they
arrived, its event log by type, team and game time with counts per type;
staff see everything, other roles a live game `spectator_delay_s` behind,
60 s by default, without secrets, telemetry or player ids; the field's
settings), `web/scoreboard.py` (`/f/<slug>/scoreboard` and `.json`, off
by default), `api/scenarios.py` and `services/library.py` (check, save as
revisions, read, archive; the field's game presets); `GET
/api/v1/sync/presets` and `GET /api/v1/sync/scenarios/{id}`, checked by
`sync_format.check_presets` and `check_scenario`. On the controller,
`[sync] library = true` (the default) installs what changed with
`scenario_service.install`, on every controller of the field, standby
included (M8-3, S20-1). The person's game history is in access and export;
ADR-P4-8's per-field history retention is `retention_days` (30-730).

---

## Plan phase 21: Hosted multi-tenant mode

*Software, can be done now. Depends on plan phases 10-20. Size M.*

ADR-P4-4 as written: `tenants`, schema per field, routing by API key and
by host name, RLS as defence in depth, Alembic over every tenant, export
(`pg_dump --schema`) and deletion of one field. Built last because every
earlier table must exist first; hosted mode does not go live before the
legal review (P4-6). Tests: `test_tenants.py` (no row of one field
visible from another, even with a routing bug simulated).

---

## Plan phase 22: Deployment

*Software, can be done now. Depends on plan phase 10. Size S.*

ADR-P4-10: Caddy in `server/docker-compose.yml`, `server/setup.sh`
(secrets, `.env` with mode 0600), `server/backup.sh` and a restore
procedure, tested in CI by backing up a database with data, restoring it
into a new one and running the tests' checks against it;
`server/docs/DEPLOY.md`. Validation: `python3 tools/docker_server.py
test`, plus the backup and restore test.

---

## HW1: Sync over a real link

*Needs hardware and a deployment. Depends on plan phase 13 and phase 2 plan phase F.*

A Raspberry Pi controller with the modem board, a phone as the 4G
bridge, a site server on a VPS: a game's events reach the site server
within 5 s (95th percentile) while the link is up; the link cut for 10
minutes during a game, then every event arrives once; the controller
behind carrier-grade NAT needs no inbound port.

## HW2: Target addon

*Needs hardware. Depends on plan phase 2.*

The target addon's MCU firmware (RP2040 or ATtiny) and its link to the
Field Box's addon port, the `hit` capability in the Field Box's HAL,
piezo threshold and debounce tuned on steel and polycarbonate plates;
then Target Windows becomes a built-in preset.

## HW3: Phones in the field

*Needs hardware. Depends on plan phases 4, 5 and 9, and phase 3 plan phase G.*

The VIP's GPS outdoors against the extraction radius (10-25 m, risk R8),
a payload prop on a phone, the Hacking Terminal on a phone and a Field
Box with a keypad in sunlight and gloves, ATAK on a phone on the field
Wi-Fi with the georeferenced image.

## HW4: Chrono end to end and the weekend milsim gate

*Needs hardware and players. Depends on everything above, phase 2 plan
phase F and phase 3 plan phase G.*

The staged gate test plan below.

---

## Assumptions about earlier phases (re-checked 2026-10-19)

| # | Assumption | Status 2026-10-19 | Plan phases |
|---|-----------|-------------------|-------------|
| A1 | The Python controller (FastAPI, SQLite, MQTT, WebSocket) | **Built.** `controller/atalaia_controller/`, store schema 4, routes in `api.py`, MQTT `field/v1/...` | 8, 9, 13-20 |
| A2 | The GM console (Preact + HTM, CSP, class components) | **Built.** `controller/console/src/`, Playwright tests | 8, 9, 16 |
| A3 | `field.*` and `state.field{}` in the core | **Built.** `field.nodes/owner/send/score/common_owner` | 1, 5, 6, 7 |
| A4 | The Android prop shell (Flutter, `dart:ffi`, kiosk) | **Built in software** (phase 3 D-F); not run on a phone | 4, 5 |
| A5 | The player app with role views | **Built in software** (Android; iOS not built) | 8, 16 |
| A6 | GPS reports from the app | **Built:** `POST /api/v1/positions`, kept on the controller, filtered by role; **no `gps.fix` events** | 5, 9 |
| A7 | NFC squad identification | **Changed:** player tags carry player and team, not squad (P4R3) | -- |
| A8 | Chrono check-in in the app | **Built:** signed per-reading records, `POST /api/v1/chrono/readings`, marshal keys from the phone | 14 |
| A9 | BLE join for Android | **Changed:** join by QR, NFC or text (P3-10); a pod over BLE or USB (plan phase F) | -- |
| A10 | Multi-node modes prove `field.lua` | **Built:** Hold-All, Last Stand, the Medic Kit | 1, 6 |
| A11 | The target addon | **Not built** (hardware/target-addon: design phase) | HW2 |
| A12 | Multicast on the field Wi-Fi | Unchanged; checked in HW3 | 9 |
| A13 | The site server reaches the controller over 4G | **Dropped:** the controller connects out (P4R12) | 13, 19 |
| A14 | (new) Boxes can run per-game scripts | **False:** built-in presets only; new modes need a flash (K10) | 6-8 |
| A15 | (new) Check-in, player ids, tokens, branding as phase 3 built them | **Built:** `checkin.py`, `player_token.py`, `branding.py` | 16, 18 |

---

## Acceptance criteria

Commands are run from the repository root in WSL/Linux. "Clean-copy
check" means the commands in "How each plan phase is verified".

| AC | What | Command | Expected |
|----|------|---------|----------|
| AC-1 | Site server starts and is healthy | `python3 tools/docker_server.py up` then `curl -fsS http://localhost:8000/api/v1/health` then `python3 tools/docker_server.py down` | `{"status": "healthy", "database": "connected", ...}` |
| AC-2 | Migrations round trip | `python3 tools/docker_server.py migrations` | exit 0 |
| AC-3 | Auth (registration, login, TOTP, refresh) | `python3 tools/docker_server.py test tests.test_auth tests.test_roles` | exit 0 |
| AC-4 | Personal data rights | `python3 tools/docker_server.py test tests.test_personal_data` | exit 0; erasure keeps chrono signatures valid |
| AC-5 | Sync idempotent, scores right with negative adjustments | `python3 tools/docker_server.py test tests.test_sync tests.test_sync_e2e` | exit 0 |
| AC-6 | Chrono records verified with the shared vectors | `python3 tools/docker_server.py test tests.test_chrono` | exit 0; every invalid vector refused with its reason |
| AC-7 | Master and Satellites | `python3 tools/docker_sim.py test modes/master_satellites` | all tests pass |
| AC-8 | Target Windows | `python3 tools/docker_sim.py test modes/target_windows` | all tests pass |
| AC-9 | Geo functions | clean-copy check (`ctest`: `test_geo`; simulator: `test_geo.py`) | exit 0 |
| AC-10 | CoT is valid, no player position multicast | clean-copy check (`controller/tests/test_atak.py`) | exit 0 |
| AC-11 | Scenarios compile and run | clean-copy check (`controller/tests/test_scenarios.py`) | each objective type completes and fails as specified in the simulator |
| AC-12 | Scenario validator refuses bad manifests | same | every invalid manifest refused with its reason |
| AC-13 | VIP / Payload | `python3 tools/docker_sim.py test modes/vip_payload` and the controller's positions tests | exit 0; no coordinates in events, MQTT or the stream |
| AC-14 | Hacking Terminal | `python3 tools/docker_sim.py test modes/hacking_terminal` | exit 0 |
| AC-15 | Remote GM over the controller's link | `python3 tools/docker_server.py test tests.test_remote_gm` | exit 0; refused when `remote_gm` is off |
| AC-16 | Weekend milsim gate | HW4 | all pass criteria below |
| AC-17 | Scheduling, publication, registration | `python3 tools/docker_server.py test tests.test_scheduling tests.test_registrations tests.test_field_pages` | exit 0 |
| AC-18 | Game-day sync into the check-in list | clean-copy check (`controller/tests/test_sync_schedule.py`) | exit 0 |
| AC-19 | Feeds and import | `python3 tools/docker_server.py test tests.test_feeds tests.test_registration_import tests.test_integrations` | exit 0 |
| AC-20 | (new) New built-in modes on every platform | `python3 tools/docker_app.py`, `python3 tools/docker_fw.py test`, the three ESP-IDF builds | exit 0, 0 warnings |
| AC-21 | (new) Club branding reaches a controller | `python3 tools/docker_server.py test tests.test_clubs` and the controller's sync tests | exit 0 |
| AC-22 | (new) Backup and restore | the plan phase 22 test | the restored database passes the checks |

---

## Weekend milsim gate test plan

### What "a weekend milsim runs on the platform end to end" means

The gate is met when all functional requirements and quantitative
criteria below are demonstrated in a single weekend event (two days,
8-16 hours of active play per day).

### Equipment list

| Item | Quantity | Purpose |
|------|----------|---------|
| Heltec WiFi LoRa 32 V4 (ESP32-S3 + SX1262; V4.3 by default, V4.2 in menuconfig) | 10-20 | Field Boxes, satellites, objectives, Hacking Terminals with keypads |
| Heltec V4 (modem image) | 1 | USB radio modem for the controller |
| Heltec V4 (pod image) | 2-4 | I/O pods for Android props |
| Raspberry Pi 4 or 5 | 1 (+1 standby) | Field controller |
| Repeater nodes (Heltec V4) | 1-3 | Range |
| Android phone with 4G | 1 | Internet for the controller (controller connects out) |
| VPS or mini PC | 1 | Site server |
| Player phones (Android) | 20+ | Player app, check-in, VIP |
| Android phones with ATAK | 1-2 | Marshal and GM maps |
| Target addon | 1-2 | Target Windows (if HW2 is done) |
| NFC tags (NTAG215/216) | 50+ | Player tags, replica stickers |
| Chronograph | 1 | Chrono check-in |
| Printed check-in poster | 1 | Field check-in (phase 3) |
| Batteries, power banks, cables, a laptop | as needed | Power and logs |

### Staging approach

#### Stage 1: Desk test

5 boxes, the controller, the site server on a desk, no players: a game
scheduled and published on the site server, the roster pulled, 20+
captures in Domination, events on the site server within 30 s, Master
and Satellites' bonus and reset, the remote GM's view (with
`remote_gm` on), a chrono series signed on a marshal's phone and
verified on the site server, a 3-objective custom scenario run to its
end. Pass: everything syncs once, no errors in the logs.

#### Stage 2: Small game

5 boxes, 5 players with the app, a half day: players register on the
site server with their replicas, check in with the poster, marshals
chrono the pre-declared replicas; one Domination and one Master and
Satellites game; a spot check; the full history on the site server.
Pass: all 5 check in through the app, every chrono record signed and
stored, sync latency under 5 s (95th percentile), no lost captures.

#### Stage 3: Scale test

10-15 boxes, 10+ players, a full day: Domination, Bomb, Master and
Satellites and a custom scenario with 3+ objectives; ATAK on; a
controller failover (the Pi killed mid-game, the standby takes over
within 40 s, check-ins rebuilt as F9 says); the 4G link cut for 10
minutes; batteries logged. Pass: no errors, ATAK shows over 80% of the
props within 30 s, no lost captures, every event synced after the
reconnect, no prop runs flat before its game ends.

#### Stage 4: Weekend gate

The full equipment, two days, 20+ players: day 1 chrono for everyone, 4+
games (Domination, Bomb, Master and Satellites, a custom scenario),
ATAK, a remote GM, a planned failover, Target Windows if the addon
exists; day 2 a pass valid for the day (F8) or a new chrono, 3+ more
games including a scenario with 4+ objectives and dependencies, VIP /
Payload, a Hacking Terminal, then the data collection.

**Pass criteria (quantitative):** no lost captures; sync latency under
5 s at the 95th percentile; 100% of chrono records signed and stored;
over 90% of registered players check in and join at least one game with
the app; over 80% of the props on ATAK within 30 s; no prop runs flat
before its game ends; the site server holds the whole weekend's history,
scores and chrono records; at least one custom scenario with 3+
objectives, each reaching completed or failed as it should.

### Post-test analysis

1. Export: the controller's log (`GET /api/v1/games/{id}/log`), the
   site server's events (`GET /api/v1/games/{uuid}/events`), each box's
   serial log, the site server's chrono readings for the field.
2. Cross-reference every `zone.captured` of the serial logs with the
   controller's and the site server's logs by `(node, seq, game time)`.
3. Compute delivery and sync latency (median, P95, P99), time-sync
   accuracy, duty cycle per node, battery drain per box.
4. Verify every chrono record on the site server with the marshal's
   public key valid at its time.
5. Check every scenario objective's final state.
6. Root-cause any failure from the logs and the radio counters.

### Gate decision

The gate is met when Stage 4 passes every quantitative criterion. If
Target Windows, VIP / Payload or the Hacking Terminal cannot be played
for lack of hardware or phones, the gate can pass without them provided
they pass their software acceptance criteria (AC-8, AC-13, AC-14) and
are played in the field within 30 days of the missing hardware
arriving.

---

## Dependency graph

```
Modes and core chain                      Site server chain
  1 Master and Satellites                   10 skeleton + test tooling
  2 Target Windows (logic) ----> HW2          ├─ 11 accounts ── 12 personal data
  3 Geo ─┬─ 5 VIP / Payload ───> HW3          │      ├─ 15 scheduling ── 16 registration ── 17 import
         ├─ 7 compiler                         │      └─ 13 sync ─┬─ 14 chrono
         └─ 9 ATAK ────────────> HW3          │                  ├─ 16 (also needs 15)
  4 Hacking Terminal ──────────> HW3          │                  ├─ 18 club profiles
  6 scenario runtime ── 7 ── 8 console/app    │                  ├─ 19 devices, remote GM
                         └──────────────────────────────────────> 20 history, scenario library
                                               └─ 22 deployment
                                              21 hosted mode (after 10-20)
  13 ── HW1 (with phase 2 F)
  everything ── HW4 (with phase 2 F and phase 3 G)
```

---

## Summary of new files by directory

```
server/
    atalaia_server/            app.py, config.py, db.py, models.py, security_headers.py,
                               api/ (health, accounts, roles, me, sync, chrono, games,
                               scheduling, registrations, clubs, devices, remote_gm, scenarios),
                               services/, web/ (field pages, templates), feeds/, imports/,
                               integrations/, cli
    migrations/                env.py, versions/0001_base.py ... (one per plan phase)
    schemas/games-feed-v1.schema.json
    tests/                     base.py and test_*.py (unittest, PostgreSQL 16)
    docs/                      feeds.md, integrations.md, DEPLOY.md, API.md
    Dockerfile, docker-compose.yml, docker-compose.test.yml,
    requirements.in, requirements.txt, setup.sh, backup.sh, alembic.ini

controller/atalaia_controller/
    sync_client.py, atak.py
    scenarios/                 __init__.py, manifest.py, validator.py, lua.py, package.py, __main__.py
controller/console/src/components/scenario-builder.js (+ georeference, schedule columns)
controller/tests/              test_scenarios.py, scenarios/*.yaml, test_atak.py,
                               test_sync_client.py, test_sync_schedule.py

core/include/atalaia/geo.h, core/src/geo.c, core/tests/test_geo.c

modes/master_satellites/, target_windows/, hacking_terminal/, vip_payload/, objectives/
    (mode.yaml with i18n.pt, node.lua, field.lua where needed, assets/screens/, tests/)

protocol/
    sync.md, vectors/{sync.json, geo.json, scenario.json, cot.json}
    schema/events.yaml (events 42-47, data keys 34-36), capability-proxy.md (hit)

tools/docker_server.py

docs/templates/privacy-notice-pt.md, privacy-notice-en.md, dpa-template.md
docs/phase-4-site-server/FIELD_TEST.md (with HW4)
```
