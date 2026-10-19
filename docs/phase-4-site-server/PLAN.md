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
| 19 | Device health, firmware catalogue, remote GM | health from sync, remote GM over the controller's WebSocket | Software, now | 13 | M |
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
  and 6 add more presets).
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

### Validation

```sh
python3 tools/docker_sim.py test modes/vip_payload
python3 tools/docker_app.py
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

### Validation

```sh
docker run --rm -v "$PWD:/src" atalaia-dev sh -c "BUILD=/tmp/c sh tools/check.sh"
docker run --rm -v "$PWD:/src" atalaia-dev sh -c "cd controller && python3 -m atalaia_controller.scenarios check tests/scenarios/multi_objective.yaml"
```

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

---

## Plan phase 13: Controller sync

*Software, can be done now; over a real 4G link: HW1. Depends on plan phases 10 and 11. Size L.*

### Goal

ADR-P4-3 as amended: the controller opens the link and pushes its
games; the site server stores them. Decisions P4R10-P4R13.

### Site server

- Migration `0003_sync`: `field_api_keys` (SHA-256, two active during a
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

---

## Plan phase 14: Chrono registry

*Software, can be done now; with a real chronograph: HW4. Depends on plan phase 13. Size M.*

ADR-P4-5 as amended (P4R14, P4R15). Migration `0004_chrono`:
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
  controller does), ticket secrets (SHA-256 kept), `GET
  /api/v1/sync/schedule`, `GET /api/v1/sync/roster`, `POST
  /api/v1/sync/checkins`; migration `0006_registration`.
- Controller: `sync_client.py` pulls the schedule and roster until the
  game starts; `checkin.py` gets **expected** check-ins (a new
  `status = 'expected'`, store schema 6) with their declarations
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

---

## Plan phase 17: Registration import and platform adapters

*Software, can be done now. Depends on plan phase 16. Size S.*

ADR-P4-12's import (CSV per RFC 4180 and JSON, only the listed columns,
dry run, upsert by `(source, external_ref)`) and the `PlatformAdapter`
interface with a test adapter, off by default, encrypted configuration,
every call audited; `server/docs/integrations.md`. No adapter for a
named platform (F22). Tests: `test_registration_import.py`,
`test_integrations.py`.

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
    sync.md, vectors/{sync.json, geo.json, scenario.json, cot.xml}
    schema/events.yaml (events 42-47, data keys 34-36), capability-proxy.md (hit)

tools/docker_server.py

docs/templates/privacy-notice-pt.md, privacy-notice-en.md, dpa-template.md
docs/phase-4-site-server/FIELD_TEST.md (with HW4)
```
