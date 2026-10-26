<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 4 -- Site Server and Advanced Play: Status

**Current phase:** Implementation (plan phases 1 to 22 built in software, 2026-10-21; sync over 4G: HW1; a real ATAK device: HW3; a real deployment with a real domain, and a real hosted deployment: HW1)
**Phase status:** Software done (every software plan phase built; the gate waits for hardware and real deployments)
**Risk level:** High
**Last verified:** 2026-10-21 (follow-up: the remote ATAK relay; full clean check, the site server's tests, migrations, deploy, deploy-hosted and browser tests)
**Next step:** the hardware phases HW1-HW4 (the boards); hosted mode waits for the legal review (P4-6) before going live

## Completed

- [x] Research phase: `RESEARCH.md`
- [x] Architecture decisions: `ADR.md` (ADR-P4-1 to ADR-P4-10; ADR-P4-11 and ADR-P4-12 added 2026-10-19, proposed)
- [x] Implementation plan: `PLAN.md`
- [x] Phase 2 and 3 design handoff (2026-10-18)
- [x] **Refresh after phase 3 software (2026-10-19):** every ADR re-checked against the built code, with dated amendments; RESEARCH and PLAN corrected in place, each with a "Refresh 2026-10-19" section; the plan re-sequenced into 22 software plan phases and 4 hardware ones; decisions P4R1-P4R26 in `docs/review/decisions-to-review.md` (all open)

## Refresh 2026-10-19: what changed

| Change | Why | Decisions | Files |
|--------|-----|-----------|-------|
| Plan re-cut and re-ordered: modes and core first (1-9), then the site server (10-22); hardware last (HW1-HW4) | The maintainer wants code while waiting for the Heltec V4 boards; every plan phase is small enough to be verified from a clean copy and committed alone | P4R20 | PLAN.md |
| Event ids 42-47, data keys 34-36; no `satellite.*`; `target.hit` already 16 | Satellites send `zone.captured` (spec section 15); the Medic Kit took 50-51 | P4R1, P4R2 | ADR.md (P4-6), PLAN.md |
| Custom scenarios as a `kind: scenario` package over a built-in `org.atalaia.objectives` role package | Boxes run built-in scripts only; a new mode needs a flash (K10) | P4R7-P4R9, P4R24 | ADR.md (P4-6), PLAN.md 6-8 |
| The controller opens every connection; no controller tokens on the site server; SHA-256 API keys; games as `(field, game_id, game_seed)`; per-node score merge | 4G NAT; a GM's adjustment can be negative; the 16-bit game id repeats | P4R10-P4R13 | ADR.md (P4-1, P4-3), PLAN.md 13 |
| Chrono registry stores the signed readings verbatim and public keys only | Phase 3 built per-reading Ed25519 records signed on the phone | P4R14, P4R15 | ADR.md (P4-1, P4-5), PLAN.md 14 |
| Positions never as events or on the site server; `position.fix` for `field.lua`, `gps.fix` on Android props | Phase 3 keeps positions on the controller, filtered by role | P4R6, P4R25 | ADR.md (P4-8, P4-9), PLAN.md 5 |
| Hacking Terminal on the keypad; Target Windows' `hit` input and `game.teams()`; engineer-only deferred | No touch input or team list exists; player tags carry no squad | P4R3-P4R5, P4R26 | PLAN.md 2, 4 |
| ATAK: props and zones only on multicast, a georeferenced field image | Field Boxes have no GPS; multicast cannot filter by role | P4R18 | ADR.md (P4-7), PLAN.md 9 |
| Club profiles and branding sync | Phase 3 built branding per controller | P4R19 | PLAN.md 18 |
| Site server image `python:3.12-slim` with pinned deps, package `atalaia_server`, `unittest` on PostgreSQL 16 (CI service container, local ephemeral container) | The dev image's packages are FastAPI 0.101 with pydantic 1.10; one test runner in the repository | P4R16, P4R17, P4R9 | ADR.md (P4-10), PLAN.md 10 |
| Controller additions AGPL-3.0-or-later; mode folders with underscores, translations in `mode.yaml` | REUSE.toml and the repository's conventions | P4R21, P4R22, P4R23 | PLAN.md |

## Plan summary (order to implement)

| # | Plan phase | Software now / hardware | Depends on | Status |
|---|------------|-------------------------|------------|--------|
| 1 | Master and Satellites | Software, now | -- | Done in software (2026-10-19; not on radio hardware) |
| 2 | Target Windows (logic), `game.teams()`, `hit` input | Software, now | -- | Done in software (2026-10-19; the addon: HW2) |
| 3 | Geo utilities in the core | Software, now | -- | Done in software (2026-10-20) |
| 4 | Hacking Terminal | Software, now | -- | Done in software (2026-10-20; on a phone in the field: HW3) |
| 5 | VIP / Payload | Software, now | 3 | Done in software (2026-10-20; real GPS in the field: HW3) |
| 6 | Scenario packages and the objectives role package | Software, now | -- | Done in software (2026-10-20; not on radio hardware) |
| 7 | Scenario compiler and validator | Software, now | 3, 6 | Done in software (2026-10-20; not on radio hardware) |
| 8 | Scenarios in the controller, console and app | Software, now | 7 | Done in software (2026-10-20; not on radio hardware or a real phone) |
| 9 | ATAK / CoT emitter | Software, now | 3 | Done in software (2026-10-20; a real ATAK device: HW3) |
| 10 | Site server skeleton and test tooling | Software, now | -- | **Done in software** (2026-10-19) |
| 11 | Accounts, sessions and roles | Software, now | 10 | **Done in software** (2026-10-19) |
| 12 | Personal data | Software, now | 11 | **Done in software** (2026-10-19) |
| 13 | Controller sync | Software, now | 10, 11 | **Done in software** (2026-10-20; over 4G: HW1) |
| 14 | Chrono registry | Software, now | 13 | **Done in software** (2026-10-20; a real chronograph: HW4) |
| 15 | Scheduling, field pages and feeds | Software, now | 11 | **Done in software** (2026-10-20) |
| 16 | Registration and game-day sync | Software, now | 13, 15 | **Done in software** (2026-10-20; the app's screens with 17, a real game day: HW1) |
| 17 | Registration import and adapters | Software, now | 16 | **Done in software** (2026-10-20, with the app's registration screens; no real platform) |
| 18 | Club profiles and branding sync | Software, now | 13 | **Done in software** (2026-10-20; not yet on a real deployment) |
| 19 | Device health, firmware catalogue, remote GM | Software, now | 13 | **Done in software** (2026-10-20; not yet on a real deployment or over 4G) |
| 20 | Game history and the scenario library | Software, now | 13, 7 | **Done in software** (2026-10-20; not yet on a real deployment) |
| 21 | Hosted multi-tenant mode | Software, now | 10-20 | **Done in software** (2026-10-20; tested against PostgreSQL in Docker, not yet on a real hosted deployment; not live before P4-6) |
| 22 | Deployment (Caddy, setup, backup, restore) | Software, now | 10 | **Done in software** (2026-10-20; tested in Docker with Caddy's own CA, not yet on a real server with a real domain and certificate) |
| HW1 | Sync over a real 4G link | Hardware and a deployment | 13, phase 2 F | Waiting for boards |
| HW2 | Target addon | Hardware | 2 | Waiting for the addon |
| HW3 | Phones in the field (VIP, payload, terminal, ATAK) | Hardware | 4, 5, 9, phase 3 G | Waiting for boards and phones |
| HW4 | Chrono end to end, weekend milsim gate | Hardware and players | all, phase 2 F, phase 3 G | Waiting |

Plan phases 1-9 and 10-22 are two independent chains; they can run in
parallel worktrees.

## Plan phase 1: Master and Satellites (built 2026-10-19)

`modes/master_satellites` (`org.atalaia.master_satellites`, "Mestre e
Satélites"): `master` and `satellite` boxes capture as in Domination
and do not score; `field.lua` scores the master's holder every
`tick_s` with `points_per_tick` plus `satellite_bonus_pct` % of it per
satellite held (whole points, rounded down), nothing below
`min_satellites`, and frees every satellite with
`field.send(id, "set_owner", { team = "none" })` when the master
leaves a team's hands. Screens `standby`, `captured`, `master_status`
(told by `field.lua` with the mode command `status`). No new events.
A built-in Field Box preset (the tenth, on the picker's second page
since plan phase 2: M1-4, M2-1) and the app's generated catalogue.

Tested: 8 YAML tests in the simulator and in Dart through the core,
the controller with two host boxes on the host modem
(`test_box_e2e.py`, the satellite freed over the radio), the Field Box
host tests (the preset seeded and run, the templates found) and 4
reference images, 4 app goldens. Not run: Wokwi (R7), radio boards.
Decisions M1-1 to M1-6 (open).

## Plan phase 2: Target Windows, logic (built 2026-10-19, in software)

`modes/target_windows` (`org.atalaia.target_windows`, "Janelas de
Alvo"): a `target` (requires `hit` and `led`) is dark for `interval_s`,
then shows a random team's colour (`game.teams()` and the seeded
`rand()`) for `window_s`; a hit of at least `min_strength` in the window
scores `hit_points` for that team and logs `target.hit`
(`window_open: true`), the first one closing the window unless
`multi_hit`; a hit while dark logs `window_open: false`. Screens
`standby` and `window`. The core gained `game.teams()` (P4R26); the `hit`
capability is draft RFC 0000 Amendment 1 and a refinement of
`protocol/capability-proxy.md`, with three shared vectors; the app's pod
client maps a lent hit sensor. Not a Field Box preset and not offered by
Android props until the addon exists (P4R4, P4R23; HW2).

Done first in the same plan phase: the Field Box keypad picker's pages
(`0` turns to the next nine), so all ten built-in presets can be picked
on the box (M2-1, closing M1-4).

Tested: 7 YAML tests in the simulator and in Dart through the core,
`game.teams()` in C (a node and the controller) and through the
simulator's bindings, the three new vectors through the C, Python and
Dart codecs, the picker's pages in the firmware host tests with two
reference images, three reference images and three app goldens of the
mode's screens. Not run: Wokwi (R7), any hardware (there is no addon
yet). Decisions M2-1 to M2-5 (open).

## Plan phase 3: geo utilities in the core (built 2026-10-20, in software)

`geo.distance(lat1, lon1, lat2, lon2)` (metres, haversine on 6,371 km)
and `geo.in_zone(lat, lon, zone)` (a circle, or a polygon of 3 to 32
points; the edge is inside) for node and field scripts, in
`core/src/geo.c` (ADR-P4-9). Argument errors are `script.error`.
Results are the same to the bit on every platform (M3-1): only
`+ - * /` and `sqrt`, its own sine, cosine and arc tangent, and
`-ffp-contract=off` in the core's, the Field Box's and the firmware host
tests' builds. The Field Box image grew by 5.4 KB (`0x1710c0`, 28 % of
the 2 MB OTA slot free).

Tested: `protocol/vectors/geo.json` (27 distances, of which 11 known
answers from Rosetta Code, GeographicLib and arc identities and 16
determinism pins; 24 zone cases; 18 argument errors) in C
(`core/tests/test_geo.c`, through the C functions and from Lua; a
`field.lua` check in `test_field_api.c`) and from Lua through the shared
library (`simulator/tests/test_geo.py`); ASan/UBSan; firmware host tests
and the Field Box, modem and pod builds. Checked once by hand: the
core's `ctest` on arm64 and armv7 with gcc and clang (Alpine in QEMU)
and the vectors' exact bits in an ESP-IDF app on the ESP32 and ESP32-S3
in Espressif's QEMU. Not run: Wokwi (R7), real boards, Dart (no mode
used `geo` yet; VIP / Payload, plan phase 5, now does). Decisions M3-1 to
M3-3 (open).

## Plan phase 4: Hacking Terminal (built 2026-10-20, in software)

`modes/hacking_terminal` (`org.atalaia.hacking_terminal`, "Terminal de
Hacking"): a box or an Android prop with a keypad sets a puzzle of
`digits` (3-6): crack a code of different digits from the right-place
and wrong-place counts of the last three guesses (`code`), cut numbered
wires in the right order (`wires`) or type back a sequence of keys shown
one a second (`sequence`). A wrong answer locks it for `lockout_s` and
the puzzle stays. Puzzles come from `rand()` (the game's seed and the
node's id), so replays agree. The last team to press its button, or the
terminal's `team`, solves it: `hacking.solved` (47, critical; `puzzle`,
key 36; `code`, the `reveal_code`), `points` for the team, and with
`capture` the terminal becomes the team's zone and sets a new puzzle for
the other teams. The GM's "New puzzle" command (`reset`). Screens in
Portuguese and English; the eleventh Field Box preset; on an Android
prop the keypad shows from the start. A game picked on a Field Box now
gets a random seed (it had 42). Field Box image: `0x175f70` (19.7 KB more; 27 % of the 2 MB OTA slot free).

Tested: 13 YAML event sequences (in Python and in Dart through the
core); the event vector (bytes built by hand from RFC 8949) through the
C, Python and Dart codecs, the JSON Schema and an example; the Field Box
host tests (the preset picked on the box, a wrong guess, the lock, seed
2's code 8517 as in the simulator) and ten reference images; five app
goldens, the players' feed text, the prop keypad; the controller end to
end with a host box over the host modem (the sequence read off the box's
screen and typed back, the capture, the points, the GM's reset over the
radio); the console in Chromium (the game form, the feed with the
revealed code in both languages, the command). Not run: Wokwi (R7), a
real box, a phone in the field (HW3). Decisions M4-1 to M4-9 (open).

## Plan phase 5: VIP / Payload (built 2026-10-20, in software)

`modes/vip_payload` (`org.atalaia.vip_payload`, "VIP / Carga"): the
`vip_team` escorts its VIP, a checked-in player with the role `vip` who
shares their position, or a payload, an Android prop with GPS, to a circle
of `radius_m` around `extraction` (`latitude,longitude`, one text
parameter: M5-3). The controller's `positions.py` hands a VIP's GPS reports
to the game's `field.lua` only, as the input `position.fix` (P4R6): never
an event, the radio, MQTT, the stream or `state.field`. The payload's
script gets `gps.fix` from the phone (`PropSession.location`) and checks
the zone itself (`geo.in_zone`; `geo.distance` for the metres on its
screen). The extraction, once: `vip.extracted` (46, critical; `player`),
`vip_points`, and with `end_on_extract` `game.win`. Checkpoints capture as
in Domination; `field.lua` scores a checkpoint's holder every `tick_s`
seconds held. The twelfth Field Box preset, for checkpoints (M5-6). Field
Box image: `0x1787f0` (10.1 KB more; 26 % of the 2 MB OTA slot free).

Done first in the same plan phase (M4-7, M5-1): data that only staff may
read is marked in the schema (`gm_only` on `hacking.solved`'s `code` in
`events.yaml`, `gm_only: true` on Bomb's `team_codes`, Codes' `codes` and
the terminal's `reveal_code`), and the controller strips it from players'
connections, the read token and MQTT (`visibility.py`). The site server's
synced events and parameters are staff-only already (M5-2, for plan
phase 20).

Tested: 8 YAML event sequences (in Python and in Dart through the core:
the first mode to run `geo` in Dart), the two event vectors through the
C, Python and Dart codecs, simulator tests (no event may carry a
position, a malformed zone, the join's 200 bytes), the controller (a VIP
token's report ends the game; no coordinate on the stream, MQTT or the
log; a player, the read token and MQTT never see the code; marshals and
the GM do), a prop session with fake fixes, the Field Box host tests (the
preset picked, a checkpoint captured) and five reference images, four app
goldens, the console in Chromium. Not run: Wokwi (R7), a real box, real
GPS on phones in the field (HW3). Decisions M5-1 to M5-7 (open).

## Plan phase 6: scenario packages and the objectives role package (built 2026-10-20, in software)

The runtime that compiled scenarios need (P4R7). A new manifest kind,
`scenario`: a `mode.yaml` and a `field.lua`, no `node.lua`, no roles, no
commands; uploaded to a controller (`POST /api/v1/modes`), never built in
(the controller refuses one in its mode folders). It leads a game's id over
at least one role package, optionally with one main mode right after it
(`org.club.foxhound+org.atalaia.objectives`,
`org.club.foxhound+org.atalaia.respawn+org.atalaia.objectives`); its
`field.lua` runs first and its parameters are its own (no join carries
them); no node runs it and no join names it (M6-1). The rules changed in
the simulator's `atalaia_sim.mode` (which the controller uses), the app's
catalogue (a join never names a scenario) and the Dart test runner, all
checked against the new shared vectors `protocol/vectors/composition.yaml`.

`modes/objectives` (`org.atalaia.objectives`, "Objetivos", a role package
with no parameters; roles `objective` and `bomb_site`): a node waits for the
scenario's mode command `setup` and is then a point to capture, a code to
type, player tags or any cards to scan, or a bomb site; it reports the
standard events and never scores (M6-3, M6-4). The scenario sets every node
up at the start, any node it has not set up yet every second, and a node
again after `node.rebooted` (an armed bomb goes on with the fuse it had
left). Events 42-45 and data keys 34 (`objective`) and 35 (`scenario`), with
four hand-made vectors and draft RFC 0000 Amendment 4; `objective` is
`gm_only` on 42-44 until the player view routes objectives per team (M6-5,
P4R24, plan phase 8). The thirteenth Field Box preset (M6-8). A
hand-written example scenario, `modes/objectives/tests/fixtures/foxhound`,
stands in for the compiler (plan phase 7).

Tested: 9 YAML event sequences (in Python and in Dart through the core,
each node directly and in a game loop isolate): capture, code, player tags,
intel cards, a bomb defused and one exploded, reboots, a node with no
scenario; `simulator/tests/test_scenario.py` (the shared vectors, the
example's setups, a too-large command, the Reduced box's heap: about 40 KB
loaded); `app/test/modes/composition_vectors_test.dart` and the catalogue;
`controller/tests/test_scenario.py` (the upload, the joins, the setups over
the radio, the scores, a reboot, staff-only objectives on REST) and
`test_box_e2e.py` (the scenario on two host boxes over the host modem: the
setups reach the boxes, red's capture completes the bridge, a box that
loses power is set up again); the console in Chromium (a game of the
scenario from the form, the feed in words); the Field Box host tests (the
preset picked, set up, a capture and a bomb) and fifteen reference images;
five app goldens. Not run: Wokwi (R7), a real box on the radio. Decisions
M6-1 to M6-9 (open).

## Plan phase 7: scenario compiler and validator (built 2026-10-20, in software)

ADR-P4-6 as amended (P4-1, P4R7, P4R8): `controller/atalaia_controller/scenarios/`,
plain Python (PyYAML only) that the site server can import without its web
stack. A YAML (or JSON) manifest, with nodes the GM names, the game's team
names, numbered squads and seven objective types (`capture_and_hold`,
`defend`, `enter_code`, `scan_tags`, `destroy`, `escort` by `position.fix`,
`survive` against Respawn's lives), compiles to a `kind: scenario` package
over `org.atalaia.objectives`: `mode.yaml` (names in English and
Portuguese, parameters, and a `scenario:` block with each objective's
assignee, visibility and dependencies for plan phase 8) and `field.lua`
(a data table followed by the one scenario runtime, `runtime.lua`). The
validator returns every problem with its path, a code and a reason (unique
ids, references, a dependency graph without cycles, targets and roles,
parameters, teams and squads, time windows, destinations, setup and event
sizes). No manifest text is ever Lua code: each value is an escaped Lua
literal. Command line: `python3 -m atalaia_controller.scenarios
validate|check|compile` (also `python3 -m atalaia_controller scenario`);
`check` and `compile` load the Lua in the core as an upload does (P4R9).
Shared vectors `protocol/vectors/scenario.json` (5 valid, 54 invalid).

Tested: `controller/tests/test_scenarios.py` (29 tests): the vectors, and 3,000 mutated manifests that must give problems, never a crash; every
type compiled and played in the simulator over the objectives package
(completion, failure, reveals, `scenario.started`, the multi-objective
example's dependency chain with squads, time windows, `survive` with
Respawn, `escort` in a circle and a polygon, dependents blocked by a
failure, a team the game lacks, English screens); hostile names, nodes and
teams (quotes, `]]`, backslashes, control characters) round-tripped through
the core byte for byte; the core's load check and an install on the
controller; the command line; the import with FastAPI and pydantic blocked.
The hand-written Foxhound, recompiled from
`controller/tests/scenarios/foxhound.yaml`, passes the objectives package's
six YAML tests that play the hand-written package. Not run: a real box on
the radio, Wokwi (R7). The site server's own import check
(`server/tests/test_shared_imports.py`) does not list the package yet
(plan phase 20). Decisions M7-1 to M7-9 (open).

## Plan phase 8: scenarios in the controller, console and app (built 2026-10-20, in software)

ADR-P4-6 as amended (P4-1, P4R8, P4R24): the controller's scenario
endpoints (`scenario_service.py`): `POST /api/v1/scenarios/check` (GM or
read token: every problem of a manifest with its place, then the compiled
`field.lua`'s load in the core), `POST /api/v1/scenarios` (GM: compile and
install as a mode package, the manifest kept next to it), `GET
/api/v1/scenarios` and `GET /api/v1/scenarios/{id}` (GM: the manifest and
the generated files). In the Join tab the GM gives each box one of the
scenario's names; `field.nodes()` returns it. The routing of P4R24
(`visibility.py`, `engine.event_for`, `api.make_route`): staff see every
objective; players see an objective by its visibility (`public`, the
assignee team's, its squad's, a hidden one only once revealed) on the
stream, its first message, the log and the game, which carries the
scenario's names and only the objectives each viewer may know; the game is
sent again at a hidden objective's reveal; anyone else (MQTT, other teams,
the read token for a team's objective) learns only that a team completed,
failed or was shown an objective. The GM console's *Cenários* / *Scenarios*
tab (`components/scenario-builder.js`): a YAML editor checked by the
controller as it is typed, with an example, the problems, the boxes to name
and the installed scenarios. The app's player view: "Objetivos do cenário"
with the names in the app's language, the state (waiting, in progress,
completed by a team, failed and why), the assignee and the points; the
events name them. M6-1: a standby controller that lacks the scenario refuses
its join with what to install, and takes it once the same manifest is
installed (not carried automatically: plan phase 20). A game id over 63
bytes is refused at creation.

Tested: `controller/tests/test_scenario_api.py` (10 tests: each endpoint
and token, refusals, the live game keeping its scenario, the 63-byte id,
the join's names and `field.nodes()`, the routing of a three-objective
scenario to staff, team, squad, other teams and the read token on the
stream, the log and the first message, a hidden objective before and after
its reveal, a standby without and with the scenario); the console's browser
tests (2 new: the builder from the example through a located mistake to an
install, a game of it, two C host boxes named in the Join tab, the bridge
held on one box and the vault's code typed on the other's keypad, 150
points; the read token checks only); the app: `field_feed_test.dart` (2
new), `player_objectives_test.dart` (3, both languages), two new golden
images (`player_scenario_pt`, `_en`) and one new on-device case in
`integration_test/game_flow_test.dart` (a hidden objective appearing once
revealed; not run here: it needs the emulator, CI's `flutter-integration`).
Not run: a real box on the radio, a real phone in the field, Wokwi (R7).
Decisions M8-1 to M8-9 (open).

## Plan phase 9: ATAK / CoT emitter (built 2026-10-20, in software)

ADR-P4-7 as amended (P4R18): `controller/atalaia_controller/atak.py`, off
by default (`[atak] enabled = false`). The controller in charge of the
live game sends every box placed on the field image as a coloured spot
marker (`b-m-p-s-m`: name, owner, the owner's colour as `<color>` and,
for a team named after an ATAK team colour, `<__group>`, battery) and a
VIP / Payload extraction zone, every `interval_s` (30 s) and at once on a
capture, a neutralisation, a move or a game change; `stale` is twice the
interval, and every marker is dropped when the game ends. Over UDP to
`[atak] multicast` (`239.2.3.1:6969`, TTL 1), one event per datagram (TAK
Protocol version 0). **Player positions are never multicast**: only with
`players = true`, and only to the staff ATAK devices of `staff_endpoints`
(TCP), by pseudonymous player id. XML built with ElementTree (escaped,
characters XML forbids dropped, texts capped). The field image's
georeference (`georef.py`, `GET`/`PUT`/`DELETE /api/v1/field/georef`): two
opposite corners of a north-up image, or 3-8 points for a rotated one,
kept in the store's settings and cleared by a new image; the console's
*Campo / Field* tab takes the two corners as pasted `latitude, longitude`
and shows the four corners back (`georef-panel.js`). `GET /api/v1/atak`
gives the feed's counters. Shared vectors `protocol/vectors/cot.json`:
the CoT rules and two TAK example events' values, each from its cited
source.

Tested: `controller/tests/test_atak.py` (35 tests): every event checked
against cot.json; the two TAK examples rebuilt; hostile names escaped and the largest event within one datagram; an
image position of 0.5, 0.5 in the middle of the two corners; the world
file worked example and an affine map's parallelograms for 3-4 points;
degenerate points refused; `__group` from the owner's colour; a capture
sent at once (directly and through the worker thread); markers dropped at
the end and without a georeference; nothing sent while disabled; players
only to a staff TCP receiver and never on UDP, and not at all with
`players = false`; a loopback receiver for UDP and a multicast group
member on the loopback; the API, the stream and the configuration; the
socket closed on stop. The console: `test_field_georeference_two_corners`
(Chromium). Not run: a real ATAK device on the field Wi-Fi (HW3), the
remote relay through the site server (not built, M9-10). Decisions M9-1
to M9-10 (open).

## Plan phase 10: site server skeleton (built 2026-10-19, in software)

What exists: `server/atalaia_server/` (app factory, `ATALAIA_*` settings,
the async database layer on PostgreSQL 16, the base models and UUIDv7 keys,
security headers, `GET /api/v1/health` and the token-guarded
`GET /api/v1/metrics`), Alembic with `0001_base` (fields, users, roles
seeded, user_field_roles, sessions, audit_log), the server's image
(`server/Dockerfile`: the core built in its own stage, `python:3.12.14-slim`
by digest, hash-pinned requirements, an unprivileged user, a `test` target),
`server/docker-compose.yml` (local trial) and `docker-compose.test.yml`,
`tools/docker_server.py` (`test`, `migrations`, `build`, `up`, `down`) and
CI's `server` job with a `postgres:16-alpine` service container.

Tests: 34 in the test image against PostgreSQL 16 (health and its 503,
metrics and their token, security headers, the served app over real HTTP,
model defaults, the migration round trip per revision, migrations equal to
the models, the roles seed; settings, UUIDv7 with RFC 9562's example, the
shared modules importing without the web stack, every built-in mode loading
in the image's core). 19 of them (no database) also run in tools/check.sh.
Not yet: accounts and anything with personal data (plan phases 11, 12), the
controller sync (13), deployment with HTTPS and backups (22). Not run here:
the CI job itself (its commands were run by hand against a container started
the same way). Decisions S10-1 to S10-12, all open.

## Plan phase 11: accounts, sessions and roles (built 2026-10-19, in software)

What exists: registration with consent and the password policy (NIST SP
800-63B, the NCSC's 100,000 breached passwords), Argon2id hashes with
ADR-P4-2's parameters; login, the TOTP step (RFC 6238, each code once,
seeds encrypted), 15-minute access tokens checked against the session and
the roles in the database on every request, refresh tokens in a
SameSite=Strict cookie stored as SHA-256 and rotated, a replay ending the
session; logout; TOTP enrolment, confirmation and removal; lockouts and
rate limits (in memory); fields and per-field roles with TOTP required for
admin, gm and marshal; the audit log; `python -m atalaia_server
create-admin`; metrics for server administrators; migration
`0002_accounts`; argon2-cffi, PyJWT and pyotp pinned by hash.

Tests: 124 in the test image against PostgreSQL 16 (90 new: passwords,
TOTP with the RFC 6238 and RFC 4226 vectors, tokens, rate limits, accounts
and sessions, roles, `create-admin` run as a command, 0002 with data); 21
(no database, no server dependencies) also run in tools/check.sh. Not yet:
per-game roles (with `games`, plan phase 13), personal data rights (12),
deployment behind Caddy with the client address from the proxy (22).
Decisions S11-1 to S11-15, all open; S11-4 (the breached list's licence)
and S11-12 (lockouts per address behind a field's shared 4G address) want
the maintainer's eye.

## Plan phase 12: personal data (built 2026-10-19, in software)

What exists: `GET /api/v1/me/data` (everything held about the account:
profile, roles per field, sessions, the person's audit entries and those
about them, consents) and `GET /api/v1/me/export` (the same as a ZIP of JSON
files with a bilingual README); rectification with `PATCH /api/v1/me`
(username, email) and `POST /api/v1/me/password` (ends the other sessions),
both behind the current password; erasure with `DELETE /api/v1/me`
(password, and a TOTP code where the account has it): the account
anonymised as a `deleted-...` tombstone, its roles, sessions and consents
deleted, its audit rows kept without addresses, the erasure logged with no
account, the last server administrator refused; consent records with the
privacy notice's version (`consents`, migration `0003_personal_data`); the
daily retention purge inside the server (`ATALAIA_PURGE_HOUR`, 03:00 UTC)
and `python -m atalaia_server purge [--dry-run]`: sessions 30 days after
they end, the audit log after 36 months; `docs/templates/` with the privacy
notice in pt-PT and English and a DPA template, marked for legal review
(P4-6). Also: the login lockout is per (address, username), 5 failures, with
a ceiling of 50 failures per address (S11-12 changed, S12-1). No new
dependency.

Tests: 151 in the test image against PostgreSQL 16 (27 new: access, export,
rectification, password change, erasure with and without TOTP, the last
administrator, the purge's periods, its command and its daily task, 0003
with data, the new lockouts); 22 (no database, no server dependencies) also
run in tools/check.sh. Not yet: the tables of later plan phases (games,
chrono, registrations), each added to `personal_data.py` with its plan
phase; a flow asking existing accounts to consent to a changed notice; the
legal review of the templates. Decisions S12-1 to S12-8, all open.

## Plan phase 13: controller sync (built 2026-10-20, in software)

What exists: the site server's `POST /api/v1/sync/games`, `events`, `scores`
and `nodes` and `WS /api/v1/sync/stream`, with a field API key (SHA-256 only,
two live during a rotation, made and revoked by the field's admin at
`/api/v1/fields/{field}/sync-keys`); games identified by `(field, game_id,
game_seed)`, events unique on the controller's own key (replays, duplicates,
out-of-order batches and a standby's copy change nothing), score counters per
source merged by `GREATEST` with totals derived from them and every
`score.delta` (a negative GM adjustment lowers them); per-game roles
(`user_game_roles`) and a small games API; migration `0004_sync`; per-game
roles in access, export and erasure, games purged after 24 months. On the
controller: `sync_client.py` (offline first: a thread that only reads the
store; 30 s in a game, 5 min between, doubling on failure up to 5 min,
`Retry-After`; the cursor per game in `sync_state`, store schema 5), `[sync]`
settings (off by default), `sync-key` (store, `--status`, `--clear`,
`--resend`), `sync` in `GET /api/v1/controller`. One format, one checker:
`protocol/sync.md`, `controller/atalaia_controller/sync_format.py` and the
shared vectors `protocol/vectors/sync.json`. No new dependency on either
side (the client is the standard library's urllib).

Tests: 187 in the site server's image against PostgreSQL 16 (36 new: API
keys and rotation, batches replayed, duplicated, out of order and from a
standby, the merge vectors and a negative adjustment, game identity, the
shared vectors through the endpoints, the stream, per-game roles, the games
API, 0004 with data, and `test_sync_e2e.py`: the real controller engine and
client against the site server under uvicorn in the same container, on the
test PostgreSQL, including a replay of everything and an offline
controller catching up); 258 controller tests in tools/check.sh (30 new:
the client against a small in-process site server, privacy checked field by
field over a game with check-ins, positions and tokens, TLS with a pinned
CA, redirects refused, backoff; the shared checker against the vectors).
Not yet: over a real 4G link with a VPS (HW1); the controller's stream
client and the remote GM (plan phase 19); the other sync endpoints with
their plan phases (chrono 14, check-ins and roster 16, field and branding
18, presets 20); the history views (20). Decisions S13-1 to S13-12, all
open; S13-8 (no controller stream client yet) and S13-12 (the request limit
shared with sync) want the maintainer's eye.

## Plan phase 14: chrono registry (built 2026-10-20, in software)

What exists: the controller pushes the field's chrono registry after its
games, each item once and again only when it changed: `POST
/api/v1/sync/marshals` (the marshals' Ed25519 public keys with the period
each was the marshal's key; the controller now keeps earlier keys after a
rotation, `marshal_key_history`, and what it sent, `sync_items`: store schema
6), `POST /api/v1/sync/replicas` and `POST /api/v1/sync/chrono` (every signed
reading as the text the controller stored, with its series and outcome);
also on the stream. The site server verifies each reading with the
controller's own `chrono.py` against the keys of its marshal valid when the
controller received it (`chrono_verify.py`), stores it verbatim, keeps the
ones that do not verify apart with their reason (named in the answer,
rechecked when the marshal's key arrives, never silently dropped), counts
resends as duplicates and another record under a stored id as a conflict,
and makes failed or warned spot checks into violations. Public keys only:
no private key exists on the site server (P4R14), and
`protocol/chrono-record.md` now says so. Views for the field's admin, gm and
marshal (readings, rejects for admin and gm, violations and their outcome,
replicas, keys, a player's history), a marshal's own key registration, key
revocation, the person's own history (`GET /api/v1/me/chrono`), sharing
between fields only with both fields switched on and the person's consent
for each, a field's erasure of a player's chrono data; the registry in
access, export, erasure (the signed records stay, the link to the person
goes) and the purge (365 days, per field); migration `0005_chrono` with
`field_player_ids` and per-field consents. No new dependency.

Tests: 226 in the site server's image against PostgreSQL 16 (39 new: the
shared chrono vectors through `POST /api/v1/sync/chrono`, every valid one
accepted verbatim and every invalid one refused with its reason and kept
apart; tampered records; a reading sent twice and a conflicting one; a
rotated and a revoked key; violations; the views and their roles; sharing
with consent; access, export, erasure and the purge; 0005 with data; the
chrono part of `test_sync_e2e.py`, the real controller client with a key
rotation against the site server under uvicorn); 37 of the server's tests
(15 new, `test_chrono_verify.py`: the vectors, tampered records, key periods)
run in tools/check.sh with no database; 270 controller tests (12 new: the
registry's sync against the in-process site server, privacy with signed
readings, the new shared vectors). Not yet: a real chronograph and phones
(HW4); the account's adoption of a phone's player id (plan phase 16), so the
own history and sharing have no real links yet; the controller pulling other
fields' records (`GET /api/v1/sync/chrono`, with plan phase 16's roster); a
controller's erasure reaching the site server by itself (S14-10). Decisions
S14-1 to S14-12, all open; S14-5 (sharing consent per field) and S14-10
(erasure propagation) want the maintainer's eye.

## Plan phase 15: scheduling, field pages and feeds (built 2026-10-20, in software)

What exists: scheduled games on the site server (`api/scheduling.py`,
`services/scheduling.py`, migration `0006_scheduling`): the field's admin and
gm, in a TOTP session, make drafts and edit them; the admin publishes and
cancels (with a reason, still shown); drafts can be deleted, published games
only cancelled. Times are kept in UTC and shown in the field's time zone; the
registration window is checked against the start. A field's admin turns on
its public page and sets its description, address and federation label
(`PATCH /api/v1/fields/{field}`). The public side (`web/field_pages.py`):
`/f/<slug>/` and `/f/<slug>/games/<id>`, server-rendered HTML in pt-PT and
English with no JavaScript and nothing from other sites (the security headers
unchanged), schema.org `Event` JSON-LD on game pages; `/f/<slug>/games.ics`
and `/f/<slug>/games/<id>.ics` (RFC 5545: CRLF, folding at 75 octets without
splitting UTF-8, TEXT escaping, UTC times, stable UIDs, `SEQUENCE` raised on
changes of time, place or status) and `/f/<slug>/games.json` (`atalaia.games`
version 1, `server/schemas/games-feed-v1.schema.json`, documented in
`server/docs/feeds.md`), with ETags, `304`s and `Access-Control-Allow-Origin:
*`. No personal data on any of them; drafts never. The schedule joins
access, export, erasure and the purge (`created_by`). New setting
`ATALAIA_PUBLIC_URL`. No new dependency.

Tests: 282 in the site server's image against PostgreSQL 16 (56 new:
`test_scheduling.py`, 15, roles, rules, the lifecycle and `SEQUENCE`, the
field page's settings, the schedule's personal data; `test_field_pages.py`,
20, what the public sees and never sees, languages, escaping, the security
headers, the feeds' content and caching, the per-address limit; `test_feeds.py`,
19, the iCalendar writer against RFC 5545's own examples copied from the RFC
and the JSON feed against its schema; 0006 with data; a setting); 57 of the
server's tests (20 new) run in tools/check.sh with no database. Not yet:
online registration, the roster and the check-in sync (plan phase 16), so the
feed's `registration.open` stays false; the registration import (17); a
deployment with its public address (22). Decisions S15-1 to S15-15, all
open; S15-10 (the public address) and S15-11 (the limit for calendar
services) want the maintainer's eye.

## Plan phase 16: registration and game-day sync (built 2026-10-20, in software)

What exists: on the site server (`services/registration.py`,
`api/registrations.py`, migration `0007_registration`), an account registers
for a published game while its window is open and places are left: a display
name, a team preference, the federation number when asked, pre-declared
replicas (one of theirs in the field's registry, or a type and a class of the
field's limit template, at most the field's `max_replicas`), and a check-in
ticket shown once (`ticket`, and `ticket_text`, a printable `atalaia:ticket:`
code; only its SHA-256 is kept). The player changes or cancels until the
window closes, staff until the start. The account's player id at the field is
made on its first registration, or adopted from the phone: a claim with the
phone's secret's SHA-256 that the field's controller confirms (the controller's
hashes never leave it). The controller (`sync_client.py`, `schedule.py`,
`checkin.py`, store schema 7) pulls the schedule, makes a game from a scheduled
game, pulls its roster until the game starts as **expected** check-ins with
their replicas pending in the chrono list, takes arrivals with the ticket (the
app, a marshal's scan, a tick by name), keeps the app's registration id for a
walk-in when it had no roster, and after the game pushes each registration's
outcome and its declarations' states (no names) and the walk-ins as a count;
the scheduled game follows its game to `in_progress` and `completed`. The
public game page shows *Register* only while registration is open and places
are left; the feed's `registration.open` follows. The pages and feeds answer
`HEAD`. Registrations and claims join access, export, erasure and the purge.
The console's *Check-in* tab has *From the schedule*, expected rows,
*Arrived*, a ticket box and the counts. Shared: `checkin_ticket.py` and
`app/lib/protocol/checkin_ticket.dart` with 30 ticket vectors in
`checkin.json`; 4 + 15 new sync body vectors and 4 + 14 answer vectors in
`sync.json`.

Tests: 303 in the site server's image against PostgreSQL 16 (21 new:
`test_registrations.py`, 14, registering, the window and places, replica
rules, changes, the staff list, claims, the schedule, the roster, the link and
the outcomes, personal data; `test_field_pages.py`, 5, `HEAD` like `GET` and
the register button; 0007 with data; `test_sync_e2e.py`'s game day, the real
controller client and engine against the site server under uvicorn: a claim
confirmed, three registrations, the roster, arrivals by ticket and by scan,
a chrono pass, the outcomes); 296 controller tests (18 new:
`test_sync_schedule.py`, 11; `test_checkin_ticket.py`, 6; the answer vectors);
the console's browser tests (1 new: a game from the schedule, expected players,
*Arrived*, a scanned ticket, the counts); the Dart ticket tests against the
same vectors. Not yet: the app's screens for logging in, registering and
sending the ticket; a real game day (HW1); `[sync] push_walkins`; the
registration import (17). Decisions S16-1 to S16-14, all open; S16-4 (claims
confirmed by the controller), S16-6 (the field's limit template set on both
sides) and S16-9 (no registration form on the public pages) want the
maintainer's eye.

## Plan phase 17: registration import and platform adapters, and the app's registration screens (built 2026-10-20, in software)

What exists: on the site server, a field's `admin` or `gm` imports a
registration list exported from another platform into a scheduled game
(`POST .../registrations/import`, CSV per RFC 4180 or JSON, at most 1 MiB and
5,000 rows, only the listed columns read, a dry run that writes nothing,
upsert by `(source, external_ref)`, a real import only after the staff confirm
the field's basis for the list); imported registrations are guests (no account,
no ticket, in the roster, deleted 30 days after their game). A game's list
exports as a formula-safe CSV that imports back unchanged. Platform adapters
(`atalaia_server/integrations/`): the `PlatformAdapter` interface, per-field
links off by default, configuration encrypted at rest, calls only when the
staff ask, 20 s each, every call audited; only an in-memory test adapter
(`ATALAIA_TEST_ADAPTER=on`), no adapter for a named platform (F22). Migration
`0008_integrations`; `server/docs/integrations.md`. In the app (S16-13):
*Participante › Inscrições online* logs in to a field's site server
(password, then TOTP), lists its games, registers with pre-declared replicas,
keeps the check-in ticket (QR and text) and sends it with the check-in,
changes and cancels, and claims the phone's player id; the public register
page opens it with an `atalaia://register` link.

Tests: `test_import_format.py` (also in tools/check.sh), `test_integrations.py`,
the import's endpoint tests and the migration's; the app's site client and
screens against a stand-in site server, their goldens and an integration test.
Verified 2026-10-20 from a clean copy rebased on main (check, ASan, firmware
host tests, 936 Dart tests, NDK, APK, REUSE). Not yet: a real platform, a real
deployment, a phone. Decisions S17-1 to S17-17, all open.

## Plan phase 18: club profiles and branding sync (built 2026-10-20, in software)

What exists: on the site server, clubs (`/api/v1/clubs`: a name, a short name
for its teams on controllers, a slug, a description, a colour, a logo and a
crest; members invited by the club's admins, who accept, the last admin kept)
with a public page off by default (`/c/<slug>/`, pt-PT and English, no
JavaScript, no member named), a report button (a plain form, no address kept,
5 an hour per address) and a server administrator who sees the reports and can
hide a page. A field's staff edit its branding (name, accent, logo, wallpaper)
and its saved teams (a club's team carries the club's short name and crest
unless it sets its own; a club that is not public only by its members). Every
image is checked with the controller's own `images.py` (the same limits,
metadata stripped), stored once by SHA-256, each upload with the rights
reminder (`rights_confirmed=true`). `GET /api/v1/sync/field` carries the
branding and the saved teams with their images' SHA-256s and `GET
/api/v1/sync/images/{sha256}` the field's own images. On the controller,
`[sync] branding = "site"` (default `"local"`) pulls them, fetches the
images it lacks, checks each again and applies them; the console then gets
409 for what the site sets, its own presets stay the GM's. Club membership is
personal data (access, export, erasure, the purge). Migration `0009_clubs`;
`protocol/sync.md`; the privacy notice templates.

Tests: `test_clubs.py`, `test_branding_sync.py` (with the real controller: a
club's crest follows its team to a second field's controller, each controller
checking it again; a team the site drops leaves the controller), the
migration's data test, and the controller's `test_sync_branding.py` against an
in-memory site server; the shared vectors gain 2 valid and 9 invalid field
answers. Not yet: a real deployment, the console's "from the site server"
label. Decisions S18-1 to S18-12, all open.

## Plan phase 19: device health, firmware catalogue and remote GM (built 2026-10-20, in software)

What exists: on the site server, **device health** read from what the
controllers already sync (each game's nodes: battery, RSSI, SNR, platform,
firmware and core versions, tier, last seen; and the `node.online`,
`node.offline`, `battery.low` and `node.tamper` events): `GET
/api/v1/fields/{field}/devices` lists each device by its name with its latest
game, `GET /api/v1/games/{game}/devices` one game's nodes, for the field's admin
and gm, with battery-low, offline, silent, tampered and outdated-firmware flags.
A **firmware catalogue** (`/api/v1/firmware`, migration `0010_firmware`): a list
only, no image stored or sent (OTA is not built); a server administrator adds a
release only when a key in `ATALAIA_FIRMWARE_KEYS` signed it with Ed25519 (no key:
no entries), every listing checks the signatures again, a withdrawn release stays
marked, a pre-release is never the latest. The **remote GM**: a controller with
`[sync] remote_gm = true` (off by default) opens `WS /api/v1/sync/stream` itself
and keeps it open (`remote_gm.py`, `ws_client.py`, a small RFC 6455 client on the
standard library); it sends its live game (state, totals, the nodes' health, the
latest events; never positions) and takes commands. A user with the `gm` role on
the field, in a TOTP session, sees it (`GET /api/v1/fields/{field}/remote-gm`) and
sends `start`, `pause`, `resume`, `end`, a GM message or a declared mode command
(`POST .../remote-gm/commands`), nothing else. The controller checks every command
again with the shared `sync_format.check_command`, refuses all of them while its
setting is off, refuses another game, a stale or a repeated command, and logs each
one in `remote_commands` (store schema 8, `GET /api/v1/remote-gm`); the site server
logs every attempt in its audit log (`remote_gm_command`, `remote_gm_denied`, `GET
.../remote-gm/log`). The site server gained `wsproto`, so uvicorn serves the stream
in the image (it could not before, S19-1). `protocol/sync.md` describes the
messages; 13 valid and 24 invalid shared vectors.

Tests: `test_devices.py`, `test_firmware.py` (RFC 8032's own vectors; also in
tools/check.sh), `test_remote_gm.py` (a command refused while `remote_gm` is off,
refused outside the list, refused for a user without `gm` on that field; the
controller's refusals and timeouts; a revoked key; the live view; the audit log),
`test_remote_gm_e2e.py` (a GM runs the real controller's game over a real socket
under uvicorn), the migration's data test, and the controller's
`test_remote_gm.py` (its checks, its log, the live view, the stream against a
raw-socket server, RFC 6455's own examples). Not built: the remote ATAK relay that
M9-10 had deferred here (it needs an authenticated endpoint, S19-10), positions in
the remote view, a GM page on the site server and the console's screen for the log.
Not yet: a real deployment, over 4G (HW1). Decisions S19-1 to S19-11, all open.

## Follow-up: device health events (2026-10-21, in software)

The controller in charge now logs `node.online`, `node.offline` (after `[health] node_offline_s`, 120 s of silence; at most one link event per box a minute) and `battery.low` (from a box's reported level under `[health] battery_low_pct`, 20 %, unless the box sent its own) about each box. The Field Box firmware sends its own `battery.low` from its MAX17048 gauge (`CONFIG_ATALAIA_BATTERY_LOW_PCT`, once per crossing, 5 points of hysteresis). The sync carries them to the site server's device health, tested end to end (host box -> controller; controller -> site server on PostgreSQL). The console's Boxes list marks a box offline and its battery low. The poster QR browser test is made robust (zbarimg QR decoder only). Not yet on real boards: the bench board has no gauge. Decisions FU1-1 to FU1-9, all open.

## Follow-up: over-the-air firmware updates (2026-10-21, in software)

The GM uploads a signed release (image and `.release.json` from `tools/firmware_release.py`) to the field controller (`[firmware] release_keys`, at most 4 releases) and updates one box or all while the live game has not started; the controller sends CMD update (opcode 9, RFC 0001 Amendment 6, proposed); the box fetches the release over the field Wi-Fi by HTTPS pinned to its join's field CA (keys 13 and 14, now read by the C core), verifies the Ed25519 signature (Monocypher 4.0.2) with keys built into its firmware, refuses a lower version or another board or variant, streams into the inactive OTA slot checking size and SHA-256, and only then sets the boot partition; a new image that fails its self-test or crashes is rolled back by the bootloader. Reports carry an HMAC with the game key; the box's HELLO shows the result. Shared vectors in C and Python (RFC 8032 among them), the update job tested with fakes, the controller's API, a host-box end to end and the console in Chromium. No release key exists yet (every update is refused until the key ceremony, RELEASE_SIGNING.md). Not yet on a real board (BRING_UP step 10c). Decisions FU3-1 to FU3-14, all open.

## Plan phase 20: game history and the scenario library (built 2026-10-20, in software)

What exists: on the site server, the history of a field's synced games
(`GET /api/v1/fields/{id}/history`: newest first, by state, mode and time,
with teams, totals and the winner), each game's score timeline derived from
the per-node counters (every rise of a counter is kept with its arrival
time, `game_score_samples`; the totals at each arrival follow the
controller's rule, GM adjustments included) and its event log by type, team
and game time with the count of each type. Staff see everything; anyone else
with a role on the field or the game sees a live game 60 s behind (the
field's `spectator_delay_s`, 0-3,600) and a log without secrets, telemetry
or player ids. A public scoreboard per field (`/f/<slug>/scoreboard` and
`.json`, off by default, refreshed every 30 s, no JavaScript) shows the live
game's teams and delayed scores, nothing else. The field's scenario library
(`/api/v1/fields/{id}/scenarios`): a manifest is checked with the
controller's own compiler and validator and its `field.lua` loaded in the
image's core (P4R9), each save a revision, archived ones no longer pushed;
the field's game presets beside it. Every controller of the field pulls them
(`GET /api/v1/sync/presets`, then `GET /api/v1/sync/scenarios/{id}` for a
manifest that changed) with `[sync] library = true` (the default) and
installs them through the console's own install, checking again; so a
standby has the scenario a join names (M8-3). The person's game history (the
games their player ids appear in, with those events) is in access and export;
erasure removes the link as before. ADR-P4-8's per-field history retention:
`retention_days` (30-730, 730 by default). Migration `0011_history` (after
plan phase 19's `0010_firmware`); `protocol/sync.md`.

Tests: `test_games.py` (list and filters, timeline, spectator delay and
redaction, a game role, the log's filters, settings, the public scoreboard,
per-field retention, the person's game history in access, export and
erasure), `test_scenarios_api.py` (check, the core missing, revisions,
archive and restore, who may use it, the sync answers, presets, and the
real controller: a primary and a standby install the same library and its
next revision), the migration's data test, and the controller's
`test_sync_library.py` (both controllers, a standby's join for a scenario
game after one sync, fetch only on change, a refused manifest, a live game
keeping its scenario, presets waiting for their mode, off, an older site
server, a corrupt answer); the shared vectors gain 3 valid and 9 invalid
answers. Not yet: a real deployment, a console or web page for the history
and the library. Decisions S20-1 to S20-8, all open.

## Plan phase 21: hosted multi-tenant mode (built 2026-10-20, in software)

What exists: with `ATALAIA_HOSTED=on` and `ATALAIA_HOSTED_DOMAIN` one site
server serves many fields from one PostgreSQL database (ADR-P4-4 as built).
Each field is a schema `field_<slug>` holding every table a single-field
server has, at the same revision, accounts and clubs included; `public` holds
only the registry (`atalaia_tenants`, read-only for the server) and the hub's
audit log (unreadable by the server). The field comes from the host name
(`<slug>.<domain>`), any other name gets 404 and a suspended field 403, and a
controller's API key is checked inside the field its host chose. Every
transaction sets `search_path` and `atalaia.tenant` with `set_config(...,
true)` (transaction-local), connections start with only `pg_catalog` on their
path, and under that every table of a field has `FORCE ROW LEVEL SECURITY`
and one policy on the schema's own name; the server's role owns nothing, has
no `BYPASSRLS` or `TRUNCATE`, and the server refuses to start otherwise.
Access tokens carry their field; lockouts and the remote GM's links are per
field; one field per tenant. The operator's commands (`hosted.py`, the owner
role): `hosted init|create|list|migrate|suspend|resume|export|delete`, each in
the hub's audit log; the export is a ZIP of every table as CSV with a
manifest (mode 0600), which `import-field` loads into a single-field server;
deletion drops the schema in one transaction and keeps only counts;
`create-admin --field` and the purge per field. Off (the default), nothing of
it runs and the single-field server is unchanged. `server/docs/DEPLOY.md`,
"Hosted mode", is the procedure by hand.

Tests: `test_tenants.py` (27 tests), each class on a hub of its own with an
owner role, a server role and two fields made by the operator's commands:
field A's credentials and ids against field B on every surface (host
routing, accounts, tokens and refresh tokens, lockouts, field and game ids,
lists, the sync over HTTP and the WebSocket, the remote GM's links, history,
the public pages, feeds, scoreboard and club pages, personal-data exports and
erasure, metrics); the row-level security as the server's own role (no setting
reads nothing, another field's setting reads and writes nothing, the setting
ends with its transaction, one pooled connection shared by both fields
carries nothing on, `TRUNCATE`, `SET row_security = off`, dropping a policy,
`SET ROLE` and writing the registry all refused, every table covered); the
server refusing the owner and a superuser; the export (everything of A,
nothing of B), its import into a single-field server, suspension, migration
and deletion (B untouched); plus `test_config`'s hosted settings. The rest of
the suite runs unchanged in single-field mode. Not yet: a real hosted
deployment (wildcard names and certificates), restoring a hosted hub's backup,
the legal review (P4-6). Decisions S21-1 to S21-12, all open.

## Plan phase 22: deployment (built 2026-10-20, in software)

What exists: `server/docker-compose.yml` is now the deployment: **Caddy**
(`caddy:2.11.7-alpine`, pinned by digest; `server/Caddyfile`) terminates TLS
with a certificate it gets and renews by itself, redirects HTTP to HTTPS,
proxies everything to the server, the controllers' WebSocket included, adds
`Permissions-Policy`, `Cross-Origin-Opener-Policy` and
`X-Permitted-Cross-Domain-Policies`, removes `Server` and `Via`, and is the
only container with published ports. The server and PostgreSQL sit on
internal networks (`app`, `db`): neither the database nor the server's port can
be reached from outside, and the server has no way out to the internet. The
image always runs one worker (`--workers 1`, ADR-P4-2, S19-4) with
`--proxy-headers`, so the rate limits and the audit log see the client's
address. **`server/setup.sh DOMAIN`** writes `server/.env` (mode 0600) with the
domain, `ATALAIA_PUBLIC_URL` and four secrets of 32 random bytes (database
password, secret key, metrics token, backup key), never printed, keeps every
existing value when run again, then builds and starts the stack.
**`server/backup.sh`** pipes `pg_dump -Fc` through `backup-crypt seal`
(AES-256-GCM in the STREAM construction, the server's image with no network,
`atalaia_server/backup_crypt.py`), so the dump is never on disk in clear, opens
the new backup in full before naming it, keeps 30 days; **`server/restore.sh
FILE --yes`** opens the whole backup first, then drops and recreates the
database, restores it in one transaction and starts the server (migrations
included). **`server/docs/DEPLOY.md`** is the operator's guide (install, `.env`
and what to keep safe, the network layout, a field server with no public name,
cron, restore on a new machine, erasures after a backup, updates, monitoring).
`python3 tools/docker_server.py up` now runs the same file behind Caddy on
`https://localhost:8443`.

Tests: `test_backup_crypt.py` (11; McGrew and Viega's GCM test cases, round
trips at the chunk boundaries, every kind of damage; also in tools/check.sh),
and the deployment test, `python3 tools/docker_server.py deploy`
(`tools/server_deploy.py`, `server/tests/deploy_probe.py`, new CI job
`server-deploy`): `setup.sh` and its re-run, the stack behind Caddy with its
own CA under the name `atalaia.test`, HTTPS, the headers, the redirect, the
closed ports, the sync over the WebSocket through Caddy with the controller's
own client, the client's address in the audit log, one server process; an
encrypted backup, pruning, a damaged backup refused with nothing changed; then
everything deleted, a fresh stack, the restore into a fresh database with every
table's rows compared by digest, and the restored API key and events used
through Caddy. Not yet: a real server with a real domain and a public
certificate (HW1). Decisions S22-1 to S22-10, all open.

## Follow-up: the site server's staff pages (built 2026-10-21, in software)

Web pages for the APIs that had none (S19-11, S20-8): `/staff/` login (password, then TOTP), the field's game history (filters, settings), a game (score timeline as chart and table, event log, its boxes), the scenario library (check with every problem, save as revisions, archive), presets, device health and the remote GM (live view polled every 5 s, the commands, the log). Server-rendered in pt-PT and English with no data in the page; same-origin ES modules call the API with the bearer token, so each page has its API's role rules; CSP unchanged; no cookie authorises a request (CSRF); `textContent` only. Tests: `server/tests/test_staff_pages.py` (13), `server/tests_browser/` (10, headless Chromium over HTTPS, `python3 tools/docker_server.py browser`, CI job `server-browser`). Decisions FU2-1 to FU2-12. Not yet on a real deployment or phone.

## Follow-up: hosted mode's deployment (2026-10-21, in software)

`server/docker-compose.hosted.yml` + `Caddyfile.hosted` (Caddy on-demand TLS for `*.<domain>`, asked of `atalaia_server/tls_ask.py`: yes only for an active field's name, 5/s bursts of 20, 429 before the database), `setup.sh DOMAIN --hosted` (owner and server roles via `hosted-roles.sh`, `hosted init`), the `hub` service (`hosted migrate` before each start; `docker compose run --rm hub hosted ...`), `backup.sh`/`restore.sh` for a hub (owners and grants kept, modes never mixed, `hosted check` before and after the migrations), new `hosted check`. Tests: `test_tls_ask`, `test_tenants.HubCheckTests`, `python3 tools/docker_server.py deploy-hosted` (CI `server-deploy-hosted`, with ShellCheck): two fields at their own names over HTTPS, unknown/suspended/apex names refused a certificate, isolation as the server role in all 114 tables, a backup restored into a fresh hub with row digests, ownership, ACLs, policies and roles equal. Tested in Docker on one computer, not yet on a real hosted server with a real domain; not live before P4-6. Decisions FU4-1 to FU4-10, all open.

## Follow-up: the remote ATAK relay (2026-10-21, in software)

The relay that M9-10 deferred and S19-10 declined, built with client-certificate enrolment. The controller's `[atak] remote = true` (off by default; `remote_players` for positions) pushes its CoT events as `cot` messages on the sync stream it opens. The site server (`ATALAIA_ATAK_RELAY=on`, off by default) relays them from an asyncio TLS listener in its process on port 8089, published straight from the server's container: TLS 1.2+, a client certificate required, checked as directly issued by the field's own CA and against the `atak_certs` allow-list (same field, not revoked, not expired, holder still on the field), the certificate's field picking the tenant in hosted mode, positions only to a gm's or a marshal's certificate issued with them (P4R18). Enrolment through `/api/v1/fields/{id}/atak`, the staff page `/staff/fields/{id}/atak` and `python -m atalaia_server atak issue|list|revoke`: a per-field CA whose key is sealed under the server secret and never exported; certificates valid 7 days by default (30 at most), handed out as a TAK data package with a password shown once; revocation closes connections at once; issue, revoke, connect and refusals are audited. Migration `0012_atak`. An independent review's fixes (FU5-13 to FU5-20): a certificate with positions also needs an issuer with gm or marshal; the issuer in every `atak_connect` row (FU5-14, accepted by the maintainer); the pictures bounded (1,024 uids a field, 2 h at most) and 120 `cot` messages a minute per field; handshakes capped apart from enrolled devices (64, 4 per address, IPv6 by /64); the event's details only in the emitter's attributes and forms (8 more shared vectors); erasure scrubbing the ATAK audit details; a CA's rotation and an erasure closing connections at once; the 30 s check independent of loading CAs (and per tenant); concurrent first issues sharing one CA. Tested in Docker (`server/tests/test_atak.py`, 26), not yet with a real ATAK device (HW3) or a real deployment. Decisions FU5-1 to FU5-20, FU5-14 accepted by the maintainer, the others open.

## Follow-up: per-squad objective chains and who of a squad is told (2026-10-26, in software)

The maintainer's request of 2026-10-26 (decisions SQ-1 to SQ-10, open): a squad gets only its active objective and the next when it is completed (`reveal: active` in the manifest; nothing about a later objective reaches a player's phone), and the objective goes to the whole squad or to the squad leader alone (`disclosure: members | leader`, the GM's choice per game in the console and the API; the members of a leader-only squad hear that their leader has new orders). The compiler, the Pi's controller, the phone's controller (which also now gives a scenario's script the Join tab's box names), the player app (pt, en, de, zh-tw; a short vibration on new orders) and the console follow; the leader-absent case and the boxes' screens are for the maintainer.

## Dependencies

| Dependency | Status (2026-10-19) | Impact on Phase 4 |
|------------|---------------------|-------------------|
| Phase 2 A-E and mode pack | Done in software | None |
| Phase 2 F (hardware, field test) | Pending, needs the boards | HW1, HW4 |
| Phase 3 A-F, the Medic Kit, branding | Done in software | Old plan phase F's dependencies are met; plan phases 4, 5, 8, 16, 18 build on them |
| Phase 3 PE24 (Android controller shell), iOS | Not built | None for phase 4's software |
| Phase 3 G (field test with phones and pods) | Pending, needs the hardware | HW3, HW4 |
| Target addon (hardware/target-addon) | Design phase | HW2 |
| Wokwi CI quota (decision R7) | Used up | Firmware changes verified with host tests and ESP-IDF builds only |

## Maintainer request: scheduling, registration, publishing (2026-10-19, design only)

The maintainer asked that a field admin can schedule games, publish
them on the field's site-server page or on shared or third-party
platforms (naming jogarairsoft.pt in Portugal), and let players
register; on game day players check in at the field with a printed QR
code and declare their replicas for the chronograph (phase 3,
ADR-P3-13, now built).

| What | Where |
| --- | --- |
| Scheduling, field page, registration with pre-declared replicas, game-day sync (schedule and roster pulls, check-in push; the controller stays the authority) | `ADR.md` ADR-P4-11 (proposed; amended 2026-10-19 against the built check-in) |
| iCalendar (RFC 5545) and JSON feeds, registration import (CSV, JSON), platform adapter interface and its rules | `ADR.md` ADR-P4-12 (proposed) |
| Plan | `PLAN.md` plan phases 15, 16 and 17; constraints 16-18; AC-17 to AC-19 |
| Open questions | F13-F23 in `docs/review/decisions-to-review.md` |

**jogarairsoft.pt:** no public information or API about it was found
(web search, 2026-10-19). No adapter is designed: it needs the
platform's API documentation or an agreement, which needs the
maintainer to contact its operators (F22). No scraping.

## Key findings from research

1. Python / FastAPI + PostgreSQL for the site server, in its own image
   with its own pinned versions (P4R16).
2. Sync is conflict-free by design (append-only events, per-node
   grow-only counters); the controller opens every connection (P4R12).
3. GDPR compliance is scoped but needs a legal review for hosted mode
   (P4-6).
4. All four advanced modes and custom scenarios work through
   `field.lua` and built-in node scripts; none needs a per-game script
   on a box.
5. Phase 3's dependencies of the advanced modes are built in software;
   what waits is hardware (the target addon, real phones).
6. ATAK / CoT is an open format; no SDK licence is needed; player
   positions stay off multicast.
7. The weekend milsim gate is staged (desk, small, scale, weekend) and
   needs phase 2 F and phase 3 G.

## How to resume

Run `/sdlc phase-4-site-server --implement`. STATE.json records
`current_phase: "implementation"`, `phase_status: "in_progress"`,
`resume_with: "--implement"`, the plan phases done and the next one. Each plan phase
is verified from a clean copy (PLAN.md, "How each plan phase is
verified") and committed by the coordinator; agents do not commit.
