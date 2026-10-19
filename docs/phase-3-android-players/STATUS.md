<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 3 -- Android and Players: Status

**Current phase:** Implementation: plan phases A-D and F done in software; plan phase E done in software except the Android controller role's shell (PE24); plan phase G (integration and field test) pending, it needs the hardware
**Risk level:** Medium
**Last verified:** 2026-10-19 (plan phase F)

## Completed

- [x] Research phase: `RESEARCH.md`
- [x] Architecture phase: `ADR.md` (12 ADRs, 24 constraints; ADR-P3-13 and constraints 25-27 added 2026-10-19, proposed)
- [x] Planning phase: `PLAN.md` (7 phases A-G, 12 AC, field test plan)
- [x] Phase 2 handoff (2026-10-18): design updated to match phase 2
  A-E implementation (commit `771fd90`)
- [x] Plan phase A (2026-10-18): event schema, three single-node modes,
  player tags, capability proxy protocol v1, declarative screen templates
  (see below)
- [x] Plan phase B (2026-10-19): chrono data model, energy, limit
  templates, spot checks, Ed25519-signed records, player tags and player
  tokens in Dart, with shared vectors checked by Dart and Python (see below)
- [x] Plan phase C (2026-10-19): the `dart:ffi` bridge to the core, the game
  loop isolate, the FFI stub, every mode's tests through the Dart bridge, the
  core built for Android by the NDK and Gradle (see below)
- [x] Plan phase D (2026-10-19): the app's screens (prop shell, player, marshal,
  GM), the Flutter screen-template renderer, join by QR/NFC/text, European
  Portuguese and English, the Kotlin plugins, the emulator CI job; iOS not
  built (see below)
- [x] Plan phase E (2026-10-19): field check-in with the printed poster,
  player tokens and the role-filtered stream, signed chrono readings and the
  "replicas to chrono" list, HTTPS with the field CA, Android props on Wi-Fi,
  player positions, the stream's history; the Android controller role only in
  part (see below)
- [x] Medic Kit (2026-10-19, maintainer request, after plan phase E): the
  `modes/medic` role package, mode commands (CMD opcode 8), events 50-51, in
  the simulator, the controller, the GM console, the Field Box and the app
  (see below)
- [x] Branding (2026-10-19, maintainer request): field branding (name, logo,
  wallpaper, accent) on the controller, team names and crests per game and
  saved teams, in the app, the GM console, the scoreboard and the check-in
  poster (see below)
- [x] Plan phase F (2026-10-19): the I/O pod's firmware (USB, Bluetooth LE,
  the Field Box's HAL as capabilities, the radio passthrough, node.tamper),
  the host pod, and the phone's radio link through a pod next to its Wi-Fi
  link; nothing run on a board or a phone (see below)

## Plan phase A (2026-10-18)

| Deliverable | Where | State |
| --- | --- | --- |
| Events 25-27, 33-41 and data keys 29-30 | `protocol/schema/events.yaml` (C, Python and JSON Schema regenerated; three new event vectors) | Done |
| Kill Confirmed, Respawn and Lives, Player Check-in | `modes/kill_confirmed/`, `modes/respawn/`, `modes/player_checkin/` (manifests with `i18n.pt`, scripts, 7 tests, YAML screens); built into the Field Box as presets 6-8 | Done |
| Money Factory | events only (33, 34) | Mode deferred: decision A1 |
| Player tags (ADR-P3-9) | `protocol/nfc-tag.md`, `core/src/tag.c`, `simulator/atalaia_sim/tag.py`, `protocol/vectors/tag.json`; the Field Box reads tags during games (`box_game_tag`, `@tag` on the console) | Done; tag writing from the console is a follow-up |
| Capability proxy protocol v1 (ADR-P3-2) | `protocol/capability-proxy.md`, `protocol/vectors/capability_proxy.yaml`, `core/src/proxy.c`, `firmware/esp32/test/test_proxy_codec.c`, `simulator/atalaia_sim/capability_proxy.py` | Done (C and Python); the Dart codec is plan phase D, the pod firmware plan phase F |
| Declarative screen templates (ADR-P3-4) | `core/src/screen_template.c` (parser, checks, expressions), `firmware/esp32/main/screen_template.c` (LVGL renderer, C fallback), templates for Bomb, Domination and the three new modes, 16 new reference images | Done on the Field Box; the Flutter renderer is plan phase D |
| Chrono data model and energy | | Plan phase B, as the plan's file list says (done 2026-10-19, below) |

Deviations and choices: decisions A1-A13 in `docs/review/decisions-to-review.md`
(a draft RFC, `docs/rfcs/0000-phase-3-events-tags-and-pods.md`, records the
protocol additions). A core bug found by Kill Confirmed was fixed: a penalty
`score.add(team, -n, reason)` without a squad could not be encoded.

## Plan phase B (2026-10-19)

Pure Dart in `app/` (a Flutter project with no UI or platform folders yet),
run with `python tools/docker_app.py` and CI's "Player app logic (Dart)" job
(since plan phase C: `flutter-test`) in `ghcr.io/cirruslabs/flutter:3.44.0`
(pinned by digest).

| Deliverable | Where | State |
| --- | --- | --- |
| Energy, fps/m/s | `app/lib/chrono/energy.dart` | Done |
| `ChronoReading`, `Replica` (ADR-P3-7) | `app/lib/chrono/reading.dart`, `replica.dart` | Done; `ref_reading_id` added, `game_id` optional (B5) |
| Limit templates and loader | `app/lib/chrono/limit_template.dart`, `limit_templates/{portugal,uk,germany,generic_cqb}.yaml` | Done; every template marked unverified (P3-5, B10) |
| Check-in and spot check (PASS/WARN/FAIL) | `app/lib/chrono/spot_check.dart` | Done |
| Ed25519-signed records, canonical form | `protocol/chrono-record.md`, `app/lib/chrono/record_signer.dart`, `app/lib/security/canonical_json.dart`; Python verifier `controller/atalaia_controller/chrono.py` | Done; shared vectors `protocol/vectors/chrono_record.json` (4 valid, 28 invalid, RFC 8032) |
| Retention and erasure rules | `app/lib/chrono/retention.dart` | Done (rules only; storage comes with phases D/E) |
| Player tags in Dart | `app/lib/security/nfc_tag_signer.dart`, `ndef.dart` | Done; byte for byte against `protocol/vectors/tag.json`, `nfc.tag` event data included |
| Player tokens (ADR-P3-9) | `protocol/player-token.md`, `app/lib/security/player_token.dart`; Python `controller/atalaia_controller/player_token.py` | Done; shared vectors `protocol/vectors/player_token.json` (3 valid, 22 invalid); not wired into the API (phase E) |
| Tooling | `tools/docker_app.py`, `app/tool/check.sh`, `.github/workflows/ci.yml` (job `app`) | Done |

Tests: 153 Dart tests (`flutter test`), 18 new Python tests in the
controller. Deviations and choices: decisions B1-B13 in
`docs/review/decisions-to-review.md`: Ed25519 instead of the file list's
HMAC signer (B1), the canonical form made precise (B3), and a controller-only
token key instead of the game key (B8) are the ones to look at first.

## Plan phase C (2026-10-19)

The engine layer of the app, still without a user interface. Run with
`python tools/docker_app.py` (from any shell; Docker only) and CI's jobs
`flutter-test`, `core-android-ndk` and `flutter-build-android`.

| Deliverable | Where | State |
| --- | --- | --- |
| Dart FFI bindings | `app/lib/ffi/native_types.dart`, `bindings.dart`, `core_node.dart` | Done: all of `node.h`, plus version, templates, tag checks and the event codec |
| Callbacks | `app/lib/ffi/callbacks.dart` | Done, as `NativeCallable.isolateLocal` (decision PC1), with field operations for a controller node |
| Game loop isolate | `app/lib/core/game_loop_isolate.dart` | Done: 100 Hz real-time clock or manual clock; ordered outputs; pause, status and errors reported |
| Node runners (conditional import) | `app/lib/core/node_runner.dart`, `node_runner_android.dart`, `node_runner_stub.dart`, `node_types.dart` | Done; iOS reports unsupported at run time, leaving it out of the build is plan phase D (PC7) |
| FFI stub | `core/tests/stub.c`, `-DATALAIA_STUB=ON` in `core/CMakeLists.txt` | Done, with a struct layout report checked by Dart and by the simulator's ctypes (PC4, PC5) |
| Mode tests through the bridge | `app/test/modes/mode_tests_test.dart`, `app/test/support/mode_runner.dart` | Done: all 36 YAML test files of the 8 mode folders, each directly and in game loop isolates, and the 5 modes' screen templates (PC3) |
| NDK cross-compile | `core/CMakePresets.json`, `app/tool/check.sh ndk` | Done: arm64-v8a, armeabi-v7a, x86_64, NDK 28.2.13676358, CMake 3.22.1, no warnings, 16 KB pages, 64-bit Lua numbers (PC10) |
| Gradle build | `app/android/` (`org.atalaia.app`, min SDK 26) | Done: `flutter build apk --debug` builds the core for the three ABIs into the APK (PC8); not run on an emulator or phone |
| Tooling and CI | `tools/docker_app.py` (`check`, `test`, `ndk`, `apk`, all by default), `app/tool/check.sh`, `.github/workflows/ci.yml` | Done; `flutter-build-android` moved up from plan phase D (PC11) |

Tests: 298 Dart tests (`flutter test`), 145 of them new: 78 mode tests on
the real core (36 YAML files, each directly and through game loop isolates,
5 screen-template checks, 1 that every file is found), 28 for the real core
through the bindings (the 17 shared event vectors through the C codec, the
5 tag event vectors, templates, a Domination node), 20 for the bindings and
struct layouts against the stub, 15 for the game loop isolate, 4 for the
node runners and the placeholder screen. Python: 2 new simulator tests
(ctypes layouts against the stub); C: 1 new core test. A core bug found by
the Dart mode tests was fixed:
`field.common_owner()` compared against a string the host may already have
freed (core `script_api.c`, with a regression test in `test_field_api.c`).

Not run: the APK on an Android emulator or a phone (plan phase D's
`flutter-integration` job and plan phase G's devices), and Wokwi (its CI
quota is used up, decision R7).

## Plan phase D (2026-10-19)

The app's screens, the Android prop shell and the Kotlin plugins. Run with
`python tools/docker_app.py` (check, ndk, apk, plus `gen` and `goldens`)
and CI's `flutter-test`, `core-android-ndk`, `flutter-build-android` and the
new `flutter-integration` (an Android emulator).

| Deliverable | Where | State |
| --- | --- | --- |
| Screen-template renderer (ADR-P3-4) | `app/lib/ui/template/` | Done: a Dart port of the core's YAML-subset parser and evaluator, compared with the core through `dart:ffi` (every shipped template, 2,500 mutated templates with the same messages, 4,000 expressions, 4,000 texts, 3,000 visibilities and progress values); a Flutter renderer with the LVGL renderer's layout rules on a 320x240 canvas; golden images with the firmware references' data (decision PD2) |
| Android prop shell | `app/lib/prop/` | Done: any built-in mode (and Codes as a modifier) on the real core in a game loop isolate; team buttons (press, hold every 250 ms, release), keypad, NFC tags checked with the game key, a pod's events; the mode's screens (and the Field Box's C-only `code_entry` and `final_score` as templates); sounds as tones and vibration; the game's length sending `game.end` (PC6); admin PIN for start, pause, end, leave; screen manager (ADR-P3-5); kiosk mode and its loss (ADR-P3-9); capability mapper; battery guide by maker |
| Join (P3-10) | `app/lib/protocol/`, `app/lib/prop/join_screen.dart` | Done: the join payload's Dart codec against `join.json`; QR code (camera), join card (NFC) or pasted text, checked with the field join key from the settings; the joined game's setup. The prop starts locally: the link to the controller is plan phase E (PD12) |
| Player and GM roles | `app/lib/player/` | Done: the player's view on the controller's `WS /api/v1/stream` with the read code (from the scoreboard's address): time, points, objectives, lives, eliminations, GM messages, events in words; the GM console in a web view. Player tokens with roles and positions: plan phase E (PD13) |
| Marshal | `app/lib/marshal/`, `app/lib/chrono/chrono_ui.dart`, `replica_registry_ui.dart` | Done: identity and Ed25519 key, chrono check-in and spot check (keypad, m/s or fps, BB weight, PASS/WARN/FAIL against the unverified limit templates), replica registry by NFC sticker or QR label, players' tags written for a game (PD14), retention and erasure |
| Kotlin plugins | `app/android/app/src/main/kotlin/org/atalaia/app/` | Done and compiled into the APK: device (vibration, tones, screen, battery exemption, permissions, features), kiosk (lock task, device-owner receiver), foreground service (wake lock, Wi-Fi lock, notification), NFC (reader mode, writing), QR scanner (CameraX, ZXing: no Google Play services, PD5), USB pod (CDC ACM) and BLE pod (GATT). Run on the CI emulator (device, foreground service, the core); NFC, camera, USB and BLE not run on hardware |
| Capability proxy codec and pod client | `app/lib/pod/` | Done: the Dart codec against `capability_proxy.yaml`; the client (IDENT, ACK, 3 retries, dedupe) against a simulated pod; pod events as inputs; since plan phase F also against the pod firmware's own code (the host pod, `app/test/pod/pod_host_test.dart`) |
| Languages | `app/lib/l10n/` | Done: European Portuguese by default (as players say it, "tu", inclusive), English; Material's own texts through `flutter_localizations`; decimal comma in Portuguese; team colours named in the language (PD20) |
| iOS build | | **Not built**: no macOS in the toolchain. Code kept iOS-tolerant (PC7): no prop role on iOS (tested), no core, channels answer "not available". Steps for a Mac in `app/README.md` (PD10) |
| CI | `.github/workflows/ci.yml` `flutter-integration` | Added: Android 11 x86_64 AOSP emulator (`reactivecircus/android-emulator-runner` v2.38.0 and `subosito/flutter-action` v2.23.0, pinned by commit), `flutter test integration_test`: 5 tests on the real APK (PD17). **Not run locally** (no KVM in Docker on Windows) |
| Install guide | `app/README.md` | Done: `python tools/docker_app.py apk` puts `app/build/atalaia-debug.apk` on the host; adb or file copy |

Tests: 520 Dart tests (`flutter test`), 222 of them new: the template engine
against the core (18), golden images (20 of mode and shell templates; 12 of
six screens in both languages), the prop on the real core and its screens,
joining, the player's feed, the marshal's records, storage, translations,
CBOR and the join vectors, the capability proxy vectors and the pod client;
plus 5 integration tests for the emulator. C: one new core test (`{x|clock}` on
values beyond a 64-bit integer, PD3). The APK check now also proves the APK
holds no Google Play services or ML Kit classes.

A core bug found by the differential tests was fixed: `{x|clock}` converted
a double beyond `long long`'s range (undefined behaviour in C: x86 and ARM
gave different texts); the core now clamps at 1e15 s (`core/src/screen_template.c`,
test in `core/tests/test_screen_template.c`; firmware host tests and both
ESP-IDF builds rerun, no warnings).

Not run: the app on a real phone (NFC tags, the camera, USB and Bluetooth
pods, kiosk mode as device owner, hours on battery), iOS (not built), the
emulator tests outside CI, Wokwi (its CI quota is used up, decision R7).
Deviations and choices: decisions PD1-PD24 in `docs/review/decisions-to-review.md`.

## Plan phase E (2026-10-19)

Field check-in and everything the phone needs from the field controller.
Run with `sh tools/check.sh` (the controller's tests), `python
tools/docker_console.py` (the console in Chromium), `python
tools/docker_app.py` (Dart, NDK, APK) and `app\tool\emulator_tests.ps1`
(on-device).

| Deliverable | Where | State |
| --- | --- | --- |
| Check-in poster (ADR-P3-13) | `protocol/checkin.md`, `protocol/vectors/checkin.json` (3 valid, 47 invalid, 8 invalid texts, declarations, identities); `controller/atalaia_controller/checkin_poster.py`, `app/lib/protocol/checkin_poster.dart` | Done; both codecs check the vectors |
| HTTPS with the field CA (P3-8, ADR-P3-9) | `controller/atalaia_controller/tls.py` (ECDSA P-256, decision PE2), HTTPS on 8443 next to HTTP, `GET /api/v1/controller/ca`, `python -m atalaia_controller ca`; `app/lib/checkin/field_trust.dart` (pinned per field on first use, a changed one refused) | Done; a real TLS connection trusting only the CA is tested |
| Check-in at the controller | `controller/atalaia_controller/checkin.py`, `store.py` (schema 3), `api.py`; `[checkin]` settings | Done: identities, check-in, staff confirmation, federation number (never verified), hand check-in, removal, leaving, CSV, settings, open and close, retention purge, `player.checkin` with the id only |
| Player tokens (ADR-P3-9, B8) | issued at check-in with the controller's own per-game key (SQLite 0600, WAL and shm too), verified on REST and the stream, role, team and squad re-checked against the row (decision PE7) | Done |
| Role-filtered stream | `ws.py`, `api.py` `make_route` (decision PE6) | Done: names to staff only, players their own rows, positions by visibility, a player's `hello` with its row; the GM's change closes the player's stream with 4409 |
| Replicas to chrono | declarations, `POST /api/v1/chrono/readings` (Ed25519 with `chrono.py`, judged with the limit template), `GET .../chrono-list`; `chrono.checkin`, `chrono.spotcheck`, `chrono.violation` | Done; the shared chrono vectors go through the API |
| GM console | `controller/console/src/components/checkin-panel.js`, `poster.html`/`poster.js`/`poster.css`, i18n pt and en | Done: the Check-in tab (live), the A4 poster with its QR code and an optional Wi-Fi code, the start warning |
| App: check-in, declaration, marshal list | `app/lib/checkin/`, `app/lib/marshal/chrono_queue.dart`, `chrono_ui.dart` (send a series), `marshal_records.dart` (unsent series, pending links) | Done |
| Player view history (the empty feed seen on the emulator) | the stream's `hello` carries the latest 100 events (PE13); `field_feed.dart` | Done |
| Prop on Wi-Fi (PD12) | `protocol/prop-link.md`, `controller/atalaia_controller/prop_link.py`, `app/lib/controller/prop_link.dart`, `prop_session.dart`; join keys 13 and 14 (RFC 0001 Amendment 4, proposed) | Done: HELLO, STATE, events with ACK and resend, commands and TIME, `node.tamper` |
| Positions (ADR-P3-6) | `controller/atalaia_controller/positions.py`, `POST`/`GET /api/v1/positions`; `app/lib/position/position_reporter.dart`, `app/lib/platform/location.dart`, `LocationPlugin.kt`, the foreground service's location type | Done for GPS; BLE beacons not built |
| Teams and squads (maintainer) | games' `squads` (0 = none), squad pickers and the squad-leader role only where a game has squads (PE25) | Done in the controller, the console and the app |
| Android controller role (ADR-P3-12) | `app/lib/controller/mqtt_broker.dart`, `visibility_engine.dart` | **Partly**: the broker and the visibility engine are built and tested; the controller shell (`field.lua` and the API on the phone) is not (PE24) |

Tests: controller 201 (60 new: check-in, chrono list with the shared
vectors, poster vectors, positions, prop link, TLS); console browser tests
(3 new: the Check-in tab live, with squads, the poster's QR code read back
with `zbarimg`); 626 Dart tests (106 new); 7 on-device tests (2 new, check-in
over real HTTPS), run on a local Android 16 emulator at the Pixel 7's size and
at CI's 320x640. A fix found on the way: `PropSession.advance` threw when the
session closed while the core was answering (decision PE23, with the
coordinator's notify fix and a test that fails without it).

Not run: real phones (GPS, background positions, the Wi-Fi link to a real
controller on a field network), a controller on a Raspberry Pi serving HTTPS
to phones, Wokwi (decision R7). Deviations and choices: decisions PE1-PE25 in
`docs/review/decisions-to-review.md`.

## Medic Kit (2026-10-19)

"Ligaduras" in Portuguese: a hit player scans their signed tag (required,
MK1) and holds a button to be healed, with heals limited per kit and per
player, next to any game. Decisions MK1-MK8 (the request) and MK9-MK20 (how
it was built) in `docs/review/decisions-to-review.md`.

| Deliverable | Where | State |
| --- | --- | --- |
| The mode | `modes/medic/`: `mode.yaml` (`kind: role`; `heal_hold_s` 10, `charges` 5, `max_heals_per_player` 2, `cooldown_s` 0, `team` optional, `lang` pt; the GM command `refill`; i18n pt "Ligaduras"), `node.lua` (scan, hold, heal, every refusal with its reason), `field.lua` (each player's heals at every kit, told to the kits; a rebooted kit told again), five YAML screens in Portuguese and English | Done; 7 event-sequence tests (every refusal, the limit and the cooldown, empty and refill, two kits through the controller, next to Domination, English) run in the simulator and, through the core, in Dart |
| Role per node (MK6, MK9) | `kind: role` in `simulator/atalaia_sim/mode.py` (`compose`, `node_script_for`, `node_mode_id`, `params_for`), the controller's joins (`engine.py`: what each box runs, with its parameters), the Dart test runner; `modes/README.md`, `protocol/join.md` | Done; join encoding, the Field Box's and the app's composition unchanged |
| Events and keys | `medic.heal` (50), `medic.empty` (51), data keys `remaining` (32) and `player_heals_used` (33) in `protocol/schema/events.yaml`; C, Python and JSON Schema generated by `tools/protogen.py`; two event vectors, a JSON example | Done |
| Mode commands (MK11) | CMD opcode 8 (`mode`, RFC 0001 Amendment 5, proposed): `field_controller.py`, the controller's `send_node_cmd` (declared names only, for the node's role), the manifest's `commands`, `box_game.c` (`FIELD_CMD_MODE`), the app's prop session (radio and Wi-Fi link), the simulator's `field.send(node, "mode", ...)`; a CMD vector | Done |
| GM console | `node-list.js` (a button per mode command of a box's role: *Repor as ligaduras*), `preset-builder.js` and `game-control.js` (role packages listed apart from the modifiers, an optional team left as every team), `join-panel.js` (the game's roles include the kit's), `live-feed.js` (events in words, `feed.events` in pt and en) | Done; a browser test |
| Field Box | built-in preset `Medic Kit` (`builtin_presets.c`, `CMakeLists.txt`, `shell.c`); screens built in; accents folded for its ASCII fonts (MK16, `screen_template_fold_text`); `box_host` takes `@tag` | Done; host tests and 7 reference images; three ESP-IDF builds with 0 warnings |
| Android prop | the kit runs on the phone like any mode (its own NFC reads tags); `cmd.mode` from the Wi-Fi link; the setup form's optional team; the player view's texts for both events | Done; widget, golden and session tests, an on-device test |

Tests: simulator (`test_medic.py`, 10: role packages composed, two kits
sharing the limit, a kit out of reach with `Simulation.set_reachable`, a
rebooted kit, mode command names), 7 YAML tests in Python and in Dart (14 in
Dart: direct and isolate), the controller through the real engine and core
(`controller/tests/test_medic.py`, 4: the joins by role, field.lua's CMD to
the other kit, the GM's refill and its refusals), end to end with the C host
modem and two host boxes (`test_box_e2e.py`: a player healed at one kit is
refused at the other over the radio, the GM's refill), the Field Box's host
tests (`test_box_game.c`: a joined kit, tags, holds, mode commands;
`test_screen_template.c`: the text fold, the kit's screens; 7 new reference
images), the GM console in Chromium (the form, the kit's join, the heal in
words in pt and en, the refill on air), Dart (the catalogue, the prop
session with real tags signed for a joined game, the Wi-Fi link's mode
command, the event texts, 6 golden images), and on an Android 16 emulator
(`integration_test/medic_kit_test.dart`).

Not run: real NFC tags on a phone or on the Field Box's PN532, real radios,
Wokwi (decision R7). A kit's own charges do not survive its reboot (MK15).

## Branding (2026-10-19)

Maintainer request: "each field (or team) running it at their own server be
able to set a logo and/or a wallpaper to identify them". Decisions BR1-BR24
in `docs/review/decisions-to-review.md`.

| Deliverable | Where | State |
| --- | --- | --- |
| Field branding on the controller | `controller/atalaia_controller/branding.py`: the field's name (the poster's), logo, wallpaper and accent colour, kept in SQLite (schema 4), public without a token (`GET /api/v1/field/branding` with an ETag, the images with their SHA-256 as ETag and 304s), changed with the GM token, announced on the stream (`branding`, also in the snapshot) | Done |
| Image checks | `controller/atalaia_controller/images.py`: PNG, JPEG or WebP only (from the file's signature; SVG and GIF refused), logo 1 MiB and 16-2048 px, wallpaper 4 MiB and 320-4096 px, crest 512 KiB and 16-1024 px, animated images refused; structure checked and metadata stripped with the standard library (no Pillow, BR7) | Done |
| Team branding | per game `team_info` (display name and crest next to the colour, which stays the team's name for the boxes and the radio), changed until the game ends; crests stored once by their hash (`POST /api/v1/crests`, `GET /api/v1/crests/{id}`, immutable); saved teams (`/api/v1/team-presets`); `GET /api/v1/games/{id}/teams` for Android props | Done |
| GM console | `components/branding-settings.js`: the field's branding and the saved teams in *Settings*, team names and crests in the game form and on the game card; the logo and name on the accent colour in the header and on the login page; crests and names in the scores; the rights reminder at every upload | Done; 3 browser tests |
| Scoreboard and poster | `scoreboard.js`: the logo and name above the game, the wallpaper behind a veil, crests and names; `poster.js`: the logo above the field's name, outside the QR code | Done; the QR code reads back with `zbarimg` with the logo on the poster |
| The app | `app/lib/branding/`: fetched after a check-in or a join and kept per field id; the logo in the header, the wallpaper dimmed behind the check-in's page and the player's view, the accent on the primary colour (made readable at 4.5:1); team crests and names in the player's view; an Android prop's top-bar logo, its idle screens with the wallpaper (never behind the mode's screen, BR19) and crests on its team buttons; the default look without branding | Done; unit, widget and golden tests, the on-device check-in test |
| Docs | `controller/README.md`, `controller/console/README.md`, `app/README.md`, `protocol/checkin.md` (where the app finds the branding; no protocol change), phase 4 `PLAN.md` (club profiles), `CHANGELOG.md` | Done |

Tests: the controller (`controller/tests/test_branding.py`, 19: the image
rules against real PNG, JPEG and WebP files and broken ones, the metadata
stripping, every endpoint, ETags and 304s, persistence across a restart,
crests per game, team presets, the clean-up, the rate limit), the GM console
in Chromium (3: the settings to the header, scoreboard and poster with the QR
code read back; saved teams and a game with crests on the scores and the
scoreboard; the read token), Dart (`test/branding/`, 13, and 4 golden images
in `test/goldens/images/branding/`; every earlier golden image unchanged), and
`integration_test/check_in_test.dart` on the Android emulator (the logo,
wallpaper and a crest over the pinned HTTPS).

Not done: the field's logo on the Field Box's TFT (BR24), club profiles with
accounts (phase 4), team names in MQTT and on the boxes' screens, branding on
a standby controller (each controller has its own). Not run: real phones,
real field images from a club.

## Plan phase F (2026-10-19)

The I/O pod's firmware, and the phone's side of it. Run with `python
tools/docker_fw.py pod` (the image), `python tools/docker_fw.py test` (the
firmware's host tests), `sh tools/check.sh` (the controller's end-to-end test
with the host pod) and `python tools/docker_app.py` (the Dart tests against
the host pod and the host modem). Decisions PF1-PF15 in
`docs/review/decisions-to-review.md`.

| Deliverable | Where | State |
| --- | --- | --- |
| Pod variant (ADR-P3-3) | `CONFIG_ATALAIA_POD_MODE` in a three-way firmware-variant choice (`Kconfig.projbuild`), `sdkconfig.pod`, `main/CMakeLists.txt`, `main/pod/pod_main.c`; `python tools/docker_fw.py pod`; CI `esp32-pod-build` | Done: no Lua, screens, presets or Wi-Fi; about 650 KB in a 2 MB OTA slot; V4.3 (KCT8103L) by default, V4.2 (GC1109) in menuconfig, Vext on, no GPS (E21) |
| Proxy (ADR-P3-2) | `main/pod/pod.c` (plain C), `pod_task.c` (the FreeRTOS task, core 1, priority 5) | Done: IDENT (asked, and unasked on a ready Bluetooth link), EVT with ACKs and 3 resends then broken links, CMD acknowledged and acted on once per link, unknown types ignored (PF5) |
| USB link | `pod_task.c`: the ESP32-S3's USB-Serial-JTAG (CDC ACM to the phone), the console on UART0 | Done (PF3); not run with a phone |
| Bluetooth LE GATT server | `main/pod/pod_ble.c` (UUIDs, advertising data, the link's states, notifications cut to the MTU), `pod_ble_nimble.c` (NimBLE, ESP-IDF's own) | Done: one phone, MTU 247, Pod TX / Pod RX / Pod Status, LE Secure Connections Just Works with bonds, frames only on an encrypted link (PF4); not run with a phone |
| Capabilities on the HAL | `main/pod/pod_caps.c`, `pod_json.c`, `pod_config.h` | Done: buttons (by number, optional colour), PCF8574 keypad, LED ring, amplifier (clips as tones), PN532 player tags, enclosure switch; only what is fitted in IDENT (PF6, PF7) |
| Radio passthrough | `main/pod/pod.c` with `main/modem/modem.c` (a `frame_out` hook) | Done: RADIO_TX/RX/TX_ACK/CMD/STATUS/ERROR and RADIO_NOISE `0x0B` (PF2), the channel's sub-band limits and the edge rule of the modem, the key forgotten when its link goes (PF5) |
| `node.tamper` | the `case` capability (type `tamper`, draft RFC 0000); `PropSession` reports `opened` as `node.tamper` (`pod_opened`) | Done (PF8); no IMU in the HAL |
| PD16's command shapes | `app/lib/pod/pod_client.dart` (`PodInputs.command`, semantic targets by type) | Confirmed (PF7) |
| The phone on the radio, and Wi-Fi or LoRa | `app/lib/radio/rf_codec.dart`, `pod_radio_link.dart`, `app/lib/controller/dual_link.dart`, `controller_link.dart`; `PropSession` (`radioLinkFor`), the prop screen's radio state | Done (PF9): HELLO `transports` bit 0 with a pod; Wi-Fi first, the radio while it is down |
| Host pod | `firmware/esp32/test/pod_host` (USB and Bluetooth as TCP, the radio as UDP, the hardware on stdin); built by `tools/check.sh`, `tools/docker_app.py`, CI | Done (PF10) |
| Docs | `firmware/esp32/README.md`, `docs/BRING_UP.md` (the pod's hardware checks), `protocol/capability-proxy.md` and `prop-link.md` (dated refinements), the draft RFC, the design specification's capability types, `CHANGELOG.md`, `README.md`, the project page | Done |

Tests: the firmware's host tests (`test/test_pod.c` in `firmware_test`: IDENT
and its 256-byte budget, CMD and its ACK from the shared vectors, the once-only
action and the per-link seqs, EVT resends and broken links, the radio
passthrough with the modem's logic, the key cleared with its link, every
capability; `test_ble_gatt_stub.c`, its own `ctest` entry: UUIDs, advertising,
the ready link, MTU pieces, a CMD written in two pieces reaching the hardware
stub, a press reaching the phone, a busy stack, Pod Status), the Python and
Dart codecs with the two new vectors, the controller end to end with the host
modem and the host pod (`controller/tests/test_pod_e2e.py`, 2), Dart against
the host pod and the host modem (`app/test/pod/pod_host_test.dart` 4,
`app/test/radio/pod_radio_link_test.dart` 4, `app/test/prop/prop_pod_session_test.dart` 2)
and the Dart RF codecs against the shared vectors (`app/test/radio/rf_codec_test.dart`).
Found and fixed on the way: a pod client closed from one of its own event
listeners threw (PF13); the radio link took only the last copy's ACK (PF12).

Not run: anything on a pod board or with a phone (USB, pairing and
Bluetooth, the radio on air and its conducted power, NFC with real cards,
the keypad, the ring, the amplifier, the enclosure switch, hours on battery:
BRING_UP.md, "The I/O pod", and plan phase G), the APK's Kotlin plugins
against a pod, Wokwi (it has no pod; its CI quota is used up, decision R7).

## Maintainer request: field check-in (2026-10-19, design only)

The maintainer asked for players to check in at the field by scanning a
printed QR code, pick the replicas they will use in that game, and for
marshals to see in advance which replicas are not chronographed yet.
The local part is designed and added to plan phase E; scheduling,
registration and publishing go to phase 4 (ADR-P4-11, ADR-P4-12).

| What | Where |
| --- | --- |
| Design | `ADR.md` ADR-P3-13 (proposed): the check-in poster (`atalaia:checkin:`, per field, no secret, CA pinned per field on first use), check-in at the controller with a player token (role `player` only; the controller's own per-game token key, B8, kept across restarts), the per-game declaration, the "replicas to chrono" list driven by signed readings, manual check-in, the optional federation number (never verified automatically), personal data and retention (30 days, ADR-P4-8's guest rule), offline behaviour; constraints 25-27 |
| Plan | `PLAN.md` plan phase E, subsection "Field check-in and per-game replica declaration": files, tests, AC-13; field test 5 |
| Open questions | F1-F12 in `docs/review/decisions-to-review.md` ("Field check-in, registration and scheduling") |

Built in plan phase E (above).  No new event ids: the controller emits the
existing `player.checkin` (15).

## Phase 2 handoff changes (2026-10-18)

| Change | Impact | Files updated |
|--------|--------|---------------|
| P3-1: Chrono signing is Ed25519, not HMAC | ADR-P3-7 rewritten; reading schema uses `signature` field | ADR.md, PLAN.md |
| R6: Hold-All and Last Stand moved to phase 2 mode pack | Phase 3 modes now: Kill Confirmed, Respawn, Player Check-in, Money Factory | ADR.md (P3-8), PLAN.md (scope, AC-2, AC-3), RESEARCH.md |
| C5: Single shared game channel (no hopping) | Pod CONFIGURE uses `channel_hz` | RESEARCH.md handoff section |
| B4: Modem framing now has sync+CRC | Pod framing updated to match | ADR.md (P3-2) |
| B10: Join payload max 448 bytes, CBOR+HMAC, field join key | CA cert replaced by fingerprint + Wi-Fi fetch | ADR.md (P3-9), PLAN.md |
| D8: Codec corrections | Dart codecs must match schema-exact C payloads | PLAN.md assumptions |
| E21: GPS not on Field Box | I/O pod or phone GPS only | RESEARCH.md handoff |

## Phase 2 dependency check (updated)

| Dependency | Status | Blocks |
|-----------|--------|--------|
| Phase 2A: protocol codecs, AES-CCM, flood | **Complete** | Pod firmware, Android radio passthrough |
| Phase 2B: simulator RadioModel, FieldController | **Complete** | Multi-node mode testing |
| Phase 2C: `field.*` Lua API, radio HAL, time sync | **Complete** | No longer blocks phase 3 (Hold-All/Last Stand moved to phase 2) |
| Phase 2D: Python controller, REST API, WebSocket | **Complete** | Player app, GM app (phase 3 extends the API) |
| Phase 2E: GM console, join flow, scoreboard | **Complete** | GM role on Android |
| Phase 2F: Field test, documentation | Pending | Gate: field-tested protocol before Android integration |
| Phase 2 mode pack: Hold-All, Last Stand, Bomb codes, Codes modifier | Done in software | Holds event IDs 28-32 and data keys 28 and 31 |

**No critical phase 2 blockers remain.** Phase 3 implementation can
start immediately for phases A-D.  Phase E needs the REST API
extensions (player tokens, position endpoint, role-filtered WS).
Phase G needs hardware.

## Next steps

1. ~~Research~~ -- Complete
2. ~~Architecture~~ -- Complete
3. ~~Planning~~ -- Complete
4. Implementation -- plan phases A-F done in software (E without the
   Android controller role's shell, PE24), the Medic Kit and branding; next:
   the controller shell, then plan phase G (the field test: the boards, the
   pods and real phones)

## How to resume with implementation

Run `/sdlc phase-3-android-players --resume`.  STATE.json records
`current_phase: "implementation"`, `phase_status: "in_progress"` (plan phases A, B, C and D done).

**What can start now (no hardware, no phase 2 blockers):**
- Phase E (positions, controller integration, player tokens) depends on D (done) and phase 2D (done)

**What needs hardware:**
- Phase F's checks on a board (firmware/esp32/docs/BRING_UP.md, "The I/O pod")
- Phase G (field test) needs all previous phases and devices

## Gate

**One game mixes ESP32 and Android props without issues.**

## Phase 3 handoff for phase 4 (interfaces the site server will consume)

Phase 4's site server builds on these phase 3 interfaces:

| Interface | Where | What phase 4 consumes |
|-----------|-------|----------------------|
| Chrono reading record | `protocol/chrono-record.md`, `app/lib/chrono/reading.dart`, Python verifier `controller/atalaia_controller/chrono.py`, vectors `protocol/vectors/chrono_record.json` | Schema, canonical form, Ed25519 signature verification |
| Limit templates | `app/lib/chrono/limit_templates/*.yaml` | Template format, per-field overrides |
| Player token format | `protocol/player-token.md`, `app/lib/security/player_token.dart`, `controller/atalaia_controller/player_token.py`, vectors `protocol/vectors/player_token.json` | Token schema for account-based auth upgrade; the token key is the controller's own (decision B8) |
| Position reports | `POST /api/v1/positions`, `controller/atalaia_controller/positions.py` | Position data model, visibility rules |
| Replica registry | `app/lib/chrono/replica.dart` | Replica schema for the site-server database |
| NFC tag format | `protocol/nfc-tag.md` (HMAC-SHA256 with game key, truncated 16 bytes; vectors `protocol/vectors/tag.json`) | Tag verification for site-server-managed games |
| GM console extensions | `controller/console/src/` | Chrono view, position view, new mode UIs |
| Mode events (IDs 25-27, 33-41) | `protocol/schema/events.yaml` | Event log storage, statistics, replays |
| Field join key distribution | `protocol/join.md`, key 13 (CA fingerprint) | Site server join flow |
| Capability proxy protocol | `protocol/capability-proxy.md`, `protocol/vectors/capability_proxy.yaml` | Pod management in the site-server inventory |
| Field check-in and declarations (ADR-P3-13, built in plan phase E) | `protocol/checkin.md`, `controller/atalaia_controller/checkin.py`, store schema 3 | Roster sync fills the check-in list with registrations and pre-declared replicas; check-ins and chrono outcomes pushed back after the game (ADR-P4-11) |
