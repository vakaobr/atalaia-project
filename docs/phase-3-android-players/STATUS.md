<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 3 -- Android and Players: Status

**Current phase:** Implementation: plan phases A-D and F done in software; plan phase E done in software, with the Android controller role in slices (PE24: S1, the game engine and REST API, S2, the live stream and MQTT, S3, keeping games across a restart, S4, the pod as its radio, joins and Wi-Fi props, S5, check-in, player tokens, positions and the chrono list, and S6, the shell and its screen, done 2026-10-22, in software; S7a, the field plan and the radio channel, S7b, presets, mode packages, scenarios, role packages and branding, and S7c, boxes over the radio (re-invites, GAME_OVER, adoption, pairing, firmware updates), pulled forward and done 2026-10-23, in software; and the rest of S7, failover, the site sync, the remote GM and ATAK, pulled forward and done 2026-10-23, in software: the role is done in software); plan phase G (integration and field test) pending, it needs the hardware
**Risk level:** Medium
**Last verified:** 2026-10-23 (PE24 slices S7a, S7b, S7c and the rest of S7)

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
- [x] Money Factory (2026-10-23, the maintainer's go-ahead): the mode decision
  A1 deferred, with the state shared between boxes (what each player
  carries) in the controller's `field.lua`; in the simulator, the
  controller, the GM console, the Field Box and the app (see below)

## Plan phase A (2026-10-18)

| Deliverable | Where | State |
| --- | --- | --- |
| Events 25-27, 33-41 and data keys 29-30 | `protocol/schema/events.yaml` (C, Python and JSON Schema regenerated; three new event vectors) | Done |
| Kill Confirmed, Respawn and Lives, Player Check-in | `modes/kill_confirmed/`, `modes/respawn/`, `modes/player_checkin/` (manifests with `i18n.pt`, scripts, 7 tests, YAML screens); built into the Field Box as presets 6-8 | Done |
| Money Factory | events only (33, 34) | Mode deferred: decision A1; built on 2026-10-23 (below) |
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
| Positions (ADR-P3-6) | `controller/atalaia_controller/positions.py`, `POST`/`GET /api/v1/positions`; `app/lib/position/position_reporter.dart`, `app/lib/platform/location.dart`, `LocationPlugin.kt`, the foreground service's location type | Done for GPS; BLE beacons not built. Since 2026-10-22 the out-of-bounds warning on the player's phone (`app/lib/position/field_bounds.dart`, decisions MF-31 to MF-40): the phone's own fixes against the field boundary, with a margin, the fix's accuracy and a dwell; a banner, vibration and the notification; nothing sent |
| Teams and squads (maintainer) | games' `squads` (0 = none), squad pickers and the squad-leader role only where a game has squads (PE25) | Done in the controller, the console and the app |
| Android controller role (ADR-P3-12) | `app/lib/controller/mqtt_broker.dart`, `visibility_engine.dart`; since 2026-10-22 `field_controller.dart`, `controller_engine.dart`, `controller_store.dart`, `controller_api.dart`, `controller_stream.dart`, `controller_mqtt.dart` | **Partly**: the broker and the visibility engine are built and tested; slices S1 and S2 of PE24 (2026-10-22, below): the game engine with `field.lua` on the core, the REST API for games, scores, the log and nodes, the live stream and the MQTT topics with the Pi's ACL; slice S3 (2026-10-22): games kept in files across a restart; slice S4 (2026-10-22): an I/O pod as its radio, joins, Android props on Wi-Fi; slice S5 (2026-10-22, `controller_checkin.dart`, `controller_positions.dart`): field check-in, player tokens, the chrono list and positions; slice S6 (2026-10-22, `controller_screen.dart`, `controller_shell.dart`, `controller_isolate.dart`, `controller_host.dart`, `field_tls.dart`): the role on the home screen, its own isolate under the foreground service, the GM console from the APK, HTTPS with a field CA made on the phone, the field's Wi-Fi; slice S7a (2026-10-23, `controller_field.dart`, `controller_field_api.dart`, `controller_channel.dart`): the field plan and the radio channel with its scan; slice S7c (2026-10-23, `controller_boxes.dart`, `controller_pairing.dart`, `controller_adoption.dart`, `controller_firmware.dart`, `serial_modem.dart`): boxes over the radio, GAME_OVER, adoption by field card and pairing code, firmware updates; the rest of S7 (2026-10-23, `controller_failover.dart`, `controller_sync.dart`, `controller_sync_format.dart`, `controller_schedule.dart`, `controller_remote_gm.dart`, `controller_atak.dart`): failover with a Pi, the site sync, the remote GM and ATAK; done in software, not yet on a phone |

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

## The Android controller role, slice S1 (2026-10-22)

Decision PE24's controller role, planned in seven slices
(`PLAN.md`, "PE24 slices"; decisions PE24-1 to PE24-9). Slice S1 is
built and tested in software; the phone cannot run a field yet.

| Deliverable | Where | State |
| --- | --- | --- |
| The radio side of a game | `app/lib/controller/field_controller.dart` | Done: the simulator's FieldController in Dart (game clock, TIME beacons, commands, HELLO, STATE, events with flood copies and replays dropped, ACK bitmaps, scores merged by maximum per node and per field-script run, GM adjustments, node.online, node.offline, battery.low); no election (PE24-2) |
| The game engine | `app/lib/controller/controller_engine.dart`, `controller_store.dart` | Done: create (the Pi's checks), the start check and forced start, pause, resume, end with the winner, the time limit, `field.lua` on the core with the field operations, `game.win` ending the game at the next tick, points kept per run, node commands and mode commands, the read token's view without gm_only parameters and event data; games in memory (S3 keeps them) |
| The REST API | `app/lib/controller/controller_api.dart` | Done: healthz, whoami, nodes, modes, games, start-check, score, log, node commands, the controller's state, with the Pi's tokens, paths, bodies and status codes; loopback only (PE24-7) |
| The event decoder | `app/lib/ffi/bindings.dart` (`AtalaiaCore.decodeEvent`) | Done: the core's `atalaia_event_decode` (PE24-5) |
| Shared contract cases | `protocol/vectors/controller_api.json`; `controller/tests/test_api_contract.py`, `app/test/controller/api_contract_test.dart` | Done: 8 cases (tokens, the modes, a Domination game from creation to its end, Hold-All's and Last Stand's `field.lua`, the time limit, gm_only data, refused requests), passing against both controllers (PE24-4) |

Tests: 9 new controller tests (8 cases and the matcher), 27 new Dart tests
(9 for the contract cases and the matcher, 10 for the radio side, 8 for the
engine and the HTTP side).

### Slice S2: the live stream and MQTT (2026-10-22)

Decisions PE24-10 to PE24-15. Built and tested in software, on the loopback
address only.

| Deliverable | Where | State |
| --- | --- | --- |
| The live stream | `app/lib/controller/controller_stream.dart`, `WS /api/v1/stream` in `controller_api.dart` | Done: the GM and read tokens (`?token=` or the header; others closed with 4401), the hello snapshot (the live game, score, nodes, the latest 100 events, the controller's state), then the engine's game, event, score, node and system messages in order; gm_only parameters and event data for the GM token only, staff-marked messages to the GM only, routing marks never sent; ping and pong; a client more than 256 messages behind closed with 4408, its new hello is the catch-up (the Pi has no `since` replay: PE24-11) |
| MQTT | `app/lib/controller/controller_mqtt.dart`, `mqtt_broker.dart` | Done: the Pi bridge's topics and payloads (`field/v1/{game}/events/{type}` without gm_only data, `score` and `nodes/{id}/state`, `health` retained, QoS 1), commands from `cmd/{node}` and `cmd/all`; the broker takes logins (`gm`, `reader`: the GM and read tokens, PE24-12) and the Pi's ACL (`MqttAcl.field` = `controller/deploy/atalaia.acl`) and listens on the loopback address by default (PE24-13) |
| Shared contract cases | `protocol/vectors/controller_api.json` (new step kinds `ws_connect`, `ws`, `ws_send`, `ws_flood`, `mqtt`; the `mqtt_acl` table) | Done: 5 new cases (13 in all: the stream's tokens and hello, a game's messages in order with gm_only data by token, a client that falls behind and catches up, MQTT topics and payloads, gm_only data kept off MQTT) and 17 ACL checks, passing against both controllers (PE24-10) |

Tests: 6 new controller tests (the 5 cases and the ACL against
`atalaia.acl`; the Pi's code is unchanged), 14 new Dart tests (6 for the
cases and the ACL, 5 for the stream's routing and hello, 3 for logins, the
ACL and the bridge on a real broker).

### Slice S3: keeping games across a restart (2026-10-22)

Decisions PE24-40 to PE24-44. Built and tested in software; the store's
directory comes from the shell (S6).

| Deliverable | Where | State |
| --- | --- | --- |
| The file store | `app/lib/controller/controller_store.dart` (`FileControllerStore`) | Done: games, the event log, scores, nodes and settings in JSON files under one directory; written through, whole files replaced by rename, the log appended and flushed; a last line cut short by a crash dropped; a newer layout refused (PE24-40) |
| The restart | `app/lib/controller/controller_engine.dart` (`_restore`) | Done, as the Pi's `_restore`: the live game with its term and clock (saved every 5 s and at start, pause and end), each box's counters, the GM's adjustments, nodes, their link and battery.low, `field.lua`'s earlier points and a new run; the key kept only with `persist_game_key` (on by default), else `key_lost` and only End works (PE24-41, PE24-44) |
| A fix in both controllers | `controller/atalaia_controller/engine.py`, `controller_engine.dart` | Done: the controller's own events go on from their stored seq after a restart; from 1 again, a second GM adjustment at the same game time was dropped as a replay and its points lost at the next restart (PE24-42) |
| Shared contract cases | `protocol/vectors/controller_api.json` (new step `restart`, case setting `persist_game_key`) | Done: 4 new cases (17 in all: a live game across a restart, the GM's adjustments across two restarts, `field.lua` again with its earlier points, a game without its key), passing against both controllers (PE24-43) |

Tests: 5 new controller tests (the 4 cases; the Pi unit test for PE24-42),
13 new Dart tests (4 for the cases, 6 for the files, 3 for the node health,
the key and the game time across restarts).

### Slice S4: the pod as the radio, joins and Wi-Fi props (2026-10-22)

Decisions PE24-45 to PE24-53. Built and tested in software, with the pod's
and the Field Box's own C code on one machine; not on a real pod, box or
phone. The API stays on the loopback address (PE24-7).

| Deliverable | Where | State |
| --- | --- | --- |
| The radio | `app/lib/controller/controller_radio.dart`, `pod_modem.dart` | Done: the modem interface (the Pi's RadioModem), `RadioTransport` (the Pi's ModemTransport: the controller's packets with a TX epoch per game key, stored before use, a new one per run and when seq wraps; PE24-46), `PodModem` (an I/O pod's RADIO_* frames: IDENT, PING and STATUS, CONFIGURE and the peer epochs again on a new link, RX, TX_ACK, errors; PE24-45); `GET /api/v1/controller` has `modem`, `tx_epoch` and `tx_status`, and the radio's system messages reach the stream and MQTT (PE24-53) |
| Joins | `controller_engine.dart` (`issueJoin`), `controller_api.dart` | Done: `POST /api/v1/join`, `POST /api/v1/nodes/{id}/join` and the boxes' language (`GET/PUT /api/v1/settings/box-language`, `console_lang`) as on the Pi, sealed with the field join key; no keys 13 and 14 until HTTPS (S6); scenario names and the standby's join are S7 (PE24-48; built: PE24-84, PE24-118) |
| Android props on Wi-Fi | `app/lib/controller/controller_props.dart` | Done: `WS /api/v1/prop` as the Pi's prop_link.py, events checked against the schema with the core's tables (new bindings), TIME and commands forwarded; without a radio the props still get them (PE24-49, PE24-50) |
| The field's channel | `controller_engine.dart` (`fieldChannel`) | New games use the stored field channel and an idle radio is tuned to it; the channel choice API moves to S7 with the scan (PE24-52) |
| Shared contract cases | `protocol/vectors/controller_api.json`, `prop_link.json` | Done: radio, join and prop steps (PE24-47); 4 new cases (21 in all: the game on the modem with ACKs, CMD, TIME and TX failures; a new epoch after each restart; joins; an Android prop on Wi-Fi), passing against both controllers; the prop link's proof against 3 known answers on both sides |
| End to end on one machine | `app/test/controller/pod_controller_test.dart`; the host box for the Dart tests (`tools/docker_app.py`, CI's `flutter-test`) | Done: the phone's engine with the host pod as its radio and host boxes on a UDP air: a box joins, plays, scores and ends; the phone restarts mid-game and goes on; Hold-All's `field.lua` scores two boxes (PE24-51) |

Tests: 5 new controller tests (the 4 cases and the prop link's known
answers; the Pi's code is unchanged in S4), 16 new Dart tests (5 for the
cases and the proof, 3 end to end, 4 for the pod modem, 2 for the app's prop
client against the phone, 2 for the TX epochs).

### Slice S5: check-in, player tokens, positions and the chrono list (2026-10-22)

Decisions PE24-54 to PE24-60. Built and tested in software, on the loopback
address only (PE24-7); the shell gives the notice texts, the limit template,
and later the field CA and addresses (S6).

| Deliverable | Where | State |
| --- | --- | --- |
| Field check-in | `app/lib/controller/controller_checkin.dart` (`ControllerCheckin`) | Done, as the Pi's `checkin.py`: `GET/POST /api/v1/checkin` (open games, no names; field identities with their secret's hash; the rate limits), `/checkin/token`, `/checkin/me` (read, leave, replicas, a marshal's key), the staff list, manual check-ins, the GM's changes and removals, the CSV, open and close, the settings and the poster (`https_off` until S6); the retention purge; the check-in and chrono-list messages to staff and to the player concerned (PE24-54) |
| Player tokens | `controller_checkin.dart` (`resolve`), `controller_api.dart`, `controller_stream.dart` | Done: tokens signed with a key the phone makes per game (B8), checked against the check-in on every request (a stale token keeps the lesser role); player tokens on whoami, games, score, log and nodes, gm_only data for a game's staff; the player's stream with its own check-in and positions, 4409 after a change of team, squad or role |
| The chrono list | `controller_checkin.dart` (`uploadReadings`, `chronoList`) | Done: Ed25519-signed series verified with the marshal's registered key (refusals by reason, nothing stored), judged against the class limits (pass, fail; spot checks pass, warn, fail), `chrono_valid_for`, "refused today", `player.checkin` and `chrono.*` events, `pending_declarations` on Start |
| Positions | `app/lib/controller/controller_positions.dart`, `visibility_engine.dart` | Done, as the Pi's `positions.py`: reports checked, the level kept (ML-5), the visibility table and a team's temporary view (`visibility.granted`, `visibility.expired`), a VIP's GPS to `field.lua`, deleted when the game ends; listed by player id on both controllers (PE24-57) |
| Keeping them | `controller_store.dart` (`document`, `putDocument`) | Done: the check-in's records and the positions as two documents of the store, in files with `FileControllerStore`, so they survive a restart (PE24-56) |
| A fix in the Pi controller | `controller/atalaia_controller/checkin.py` (`set_poster`) | Done: the poster's fields are checked with HTTPS off too; a bad `game_id` closed check-in to every game without an error (PE24-58) |
| Shared contract cases | `protocol/vectors/controller_api.json` (`wall_start`, `bearer`, `ws_closed`) | Done: the Pi runner sets up check-in and positions; 7 new cases (28 in all: the poster and tokens, declarations and the GM's changes, signed readings, the player stream, positions, a VIP's extraction in VIP / Payload, restarts), passing against both controllers (PE24-55) |

Tests: 8 new controller tests (the 7 cases; the Pi unit test for PE24-58),
13 new Dart tests (7 for the cases, 6 in `controller_checkin_test.dart`: the
poster with a CA, the rate limit, the CSV, spot checks, erasing a player,
retention).

### Slice S6: the shell and its screen (2026-10-22)

Decisions PE24-61 to PE24-69. Built and tested in software, on one machine:
the controller's isolate, its servers, TLS and the pod's relay for real
(the core, sockets, Dart's TLS, the host pod), the screen with the phone's
plugins replaced by fakes; the Kotlin side compiled into the APK, not run.
The emulator test is written for CI's `flutter-integration` job (no KVM
here); a real phone is plan phase G's (PE24-69).

| Deliverable | Where | State |
| --- | --- | --- |
| The role on the home screen | `app/lib/ui/home_screen.dart`, `app/lib/platform/platform_check.dart` (`controllerRoleAvailable`) | Done: *Controlador de campo* / *Field controller*, Android only (tested on both platforms) |
| The controller's isolate (constraint 1) | `app/lib/controller/controller_isolate.dart`, `controller_host.dart` | Done: one isolate opens the core and runs the store (`FileControllerStore` in the app's private storage), the engine, check-in, positions, the API, the broker and the 100 ms tick; the UI isolate gets its status at once, every second and on a change, and sends only stop; an I/O pod's bytes relayed from the UI isolate's USB or Bluetooth link (PE24-63) |
| The foreground service and wake lock | `app/lib/controller/controller_shell.dart`; `AtalaiaForegroundService.kt`, `ForegroundServicePlugin.kt`, `MainActivity.kt` | Done: the service (notification with the live game, partial wake lock, Wi-Fi lock) before the isolate, the battery exemption asked once; the Flutter engine now outlives the activity while the service runs, so the controller (and a prop's game loop) survives the back button and a swipe away (PE24-64) |
| The GM console in the app's web view | `controller_screen.dart` (`ControllerConsoleScreen`), `console_files.dart`, `console_assets.dart`, `controller_api.dart`; `app/tool/sync_console.dart` | Done: the Pi's console files (copied in at build time, checked byte for byte, PE24-61) served as the Pi serves them, on the loopback address for the web view, which logs in once with the GM token (PE24-66) |
| HTTPS with a field CA made on the phone | `app/lib/controller/field_tls.dart`, `app/lib/security/der.dart`; `GET /api/v1/controller/ca` | Done: the Pi's CA and server certificate (ECDSA P-256, RFC 6979, pointycastle 4.0.0), renewed for a new address or near its end; the poster's `ca_sha256` and addresses, join keys 13 and 14 (`wifi_link`) (PE24-67) |
| The field's Wi-Fi | `controller_host.dart`, `FieldWifiPlugin.kt`, `lib/platform/services.dart` (`FieldWifiService`) | Done: opened (HTTPS 8443, MQTT 1883 at every address) or closed (loopback only) from the screen (PE24-62); the phone's addresses watched; the network's name, the hotspot's state, Android's settings, a local-only hotspot with a QR code to join (PE24-68) |
| The screen | `app/lib/controller/controller_screen.dart`, `lib/l10n/strings_{pt,en}.dart` | Done: start and stop, the live game, the addresses and the CA's fingerprint, the pod, the GM and read codes (hidden until asked), the console, the poster's hint, the Wi-Fi; European Portuguese and English, 320 px wide, Android's accessibility guidelines (tap targets, labels, contrast) checked |
| Tooling | `app/tool/check.sh` (the console copied in every mode, every console file checked in the APK), `.github/workflows/ci.yml` (`flutter-integration`: the copy), `app/tool/emulator_tests.{sh,ps1}`, `.gitignore` | Done |

Tests: 34 new Dart tests (1086 in all): 8 in `field_tls_test.dart` (the CA
through Dart's TLS by address and by name, the app's pinned client, another
CA and an uncovered name refused, the Pi's renewal rules, the certificates'
fields, keys and signatures, the addresses' order), 7 in
`console_bundle_test.dart` (the APK's console byte for byte with
controller/console/src, `pubspec.yaml`'s folders, the notices, the
redirects, types and headers, the field CA's endpoint), 5 in
`controller_host_test.dart` (a game over HTTPS trusting only the field CA,
the poster and joins naming it, closed to the Wi-Fi, a new address, a
restart, the host pod through the relay), 3 in
`controller_isolate_test.dart` (served from its own isolate and stopped, the
pod relayed across isolates, a start that fails), 11 in
`controller_screen_test.dart` (the role by platform, start and stop with the
foreground service in both languages, the Wi-Fi opening's restart,
failures, the field's Wi-Fi, the hotspot's QR text, 320 px and the
accessibility guidelines in both languages, the console's log-in); 2 home
golden images drawn again (the new role); 1 emulator test
(`integration_test/controller_test.dart`, not run here). The contract cases
and the Pi's code are unchanged.

**The console's follow-ups of PE24-66** (2026-10-22, decisions PE24-70 to
PE24-73), done:

| Deliverable | Where | State |
| --- | --- | --- |
| The token in the address's fragment | `controller/console/src/ui.js` (`takeHashToken`), `app.js`; the app's `consoleAddress` in `controller_screen.dart` | Done: `/console/#token=...&lang=...` logs in as a typed token (stored once `whoami` accepts it), taken out of the address at once with `history.replaceState`, never in a query or a log; the app opens its console so instead of writing the console's storage (PE24-71) |
| What the controller serves | `GET /api/v1/whoami` `features`: `api.py` `FEATURES`, `controller_api.dart` `controllerFeatures`; a shared contract case | Done: the Pi lists every console area, the phone `checkin`, `join`, `box_language`, `positions`; each side's list checked against one endpoint per area (PE24-70, an API addition for the maintainer) |
| Hiding the rest | `app.js` and the panels in `components/` | Done: the *Campo*, *Adotar*, *Predefinições* and *Cenários* tabs, the radio, branding, saved teams, invites, firmware, mode packages, standby join, *Promote*, ATAK and schedule panels and their requests; the *Controlador* tab names what is not served yet (PE24-72) |
| CSV export and printing in the web view | `components/checkin-panel.js` (`ui.js` `inWebView`) | Done: a short notice in Android's web view that they need a computer's browser (PE24-73) |

Tests: 3 browser tests (`controller/console/tests/test_browser.py`: the
`#token` flow with a tab kept, back and forward, a reload and a wrong token;
a controller whose `whoami` gives the phone's list, at 390 px in pt-PT, with
no hidden tab, panel or request and nothing refused; the web view's notice in
both languages), 1 shared contract case (passing on both controllers), 1
Python test (`test_console.py`: `FEATURES` = the console's `AREAS`, each
area's endpoint served), 1 Dart test (`console_bundle_test.dart`: the phone's
list, its areas served, the rest unknown to its router), the app's console
test changed for the fragment.

### Slice S7a: the field plan and the radio channel (2026-10-23)

Pulled forward from S7 before the field test (the maintainer's approval
of 2026-10-23). Decisions PE24-74 to PE24-79. Built and tested in
software: against the Pi controller by shared cases, with the pod
firmware's own code for the scan, not on a phone or a pod.

| Deliverable | Where | State |
| --- | --- | --- |
| The field plan | `app/lib/controller/controller_field.dart`, `controller_field_api.dart` | Done, as the Pi's `field_levels.py`, `georef.py`, `map_features.py`, `field_map.py` and api.py: a plan per level (PNG, JPEG, WebP, 4 MB), the levels (ML-0 to ML-12), each plan's map position (GR-1: two corners or 3-8 points, the same arithmetic and refusals), map features (MF-0 to MF-49, the boundary, visibility for every token on REST and the stream), the field from a map (MF-26, all or nothing), the boxes' places, and the stream's `field_image`, `field_georef`, `field_levels`, `map_features` and `position` (PE24-74) |
| Keeping it | `controller_field.dart` (`ControllerField.dir`), `controller_host.dart` | Done: one store document and each plan as a file in the controller's folder, a new plan the plan only once the document names it; leftovers removed at the start (PE24-75) |
| Plans as request bodies | `controller_api.dart` (`_Request.bytes`, `contentType`; 6 MB on the field's paths) | Done (PE24-76) |
| The channel choice and the scan | `app/lib/controller/controller_channel.dart`, `controller_radio.dart` (`measure`), `pod_modem.dart` | Done, as the Pi's `channels.py` and engine.py: the field channel's settings, the choice, a random suggestion, the noise scan through the I/O pod (MEASURE and RADIO_NOISE) with the Pi's ranking and suggestion, cancelling it, the last scan kept; no game created during a scan (PE24-74); the pod's IDENT has no `measure` flag (PE24-77, for the pod firmware) |
| The console on a phone | `controller_api.dart` (`controllerFeatures`: `radio`, `field`); `controller/console/tests/test_browser.py` | Done: the *Campo* tab, the radio panel and its first-setup reminder show on a phone controller; the out-of-bounds warning works on a phone-controlled field (PE24-78) |
| Shared contract cases | `protocol/vectors/controller_api.json` (`field_and_radio`) | Done: `raw`, `content_type`, `body_base64`, `noise`, `hold_measure`, `scan_wait`; 6 new cases (35 in all), passing against both controllers (PE24-76) |

Tests: 6 shared cases (on both controllers); 21 new Dart tests: 10 in
`controller_field_test.dart` (the map position against numbers the Pi's
georef.py printed and its refusals, a plan as a file replaced and kept
across a restart, a crash's leftovers removed, the field from a map all
or nothing when the write fails, plans in memory, at most 200 features,
who sees which feature, a whole 4 MB plan over HTTP), 10 in
`controller_channel_test.dart` (the ranking and the suggestion, the
candidates and the dwell, no pod, a failed measurement, a stored channel
that is not legal, the pod's MEASURE against a scripted link, a whole scan
through the host pod), 1 in `field_bounds_phone_test.dart` (a player
warned out of bounds on a phone controller); `console_bundle_test.dart`
and the console's browser test of a phone controller changed for the new
areas. The Pi's code is unchanged; its contract runner gained the new
steps.


### Slice S7c: boxes over the radio (2026-10-23)

Pulled forward from S7 before the field test with the maintainer's approval
(2026-10-23). Decisions PE24-90 to PE24-99. Built and tested in software on
one machine: the phone controller against the Pi's own USB radio modem and
Field Boxes running their firmware's own code (the host modem and host boxes
on a UDP air), and against the host pod; not on a phone, a modem or a pod.

| Deliverable | Where | State |
| --- | --- | --- |
| Free boxes, DISCOVER, sealed radio invites, answers | `app/lib/controller/controller_boxes.dart` (`FieldInviter`, `ControllerBoxes`), `controller_boxes_api.dart`; `lib/protocol/field_frame.dart`, `lib/security/aes_ccm.dart` | Done, as `reinvite.py` and lobby.py's `Inviter`: the boxes heard for two hours with each box's newest nonce (a replay refused), a DISCOVER at most every 10 s, invites into the live game before it starts with the join payload made as for a card, cut into one to three parts paced by their time on air (150 ms between parts, BN-2), sent again after 6 s, three times at most; the box's answer (accepted, refused with its reason) and its HELLO (joined); the previous game's boxes; `GET /api/v1/boxes`, `POST /api/v1/boxes/discover`, `GET/POST /api/v1/games/{id}/invites` (PE24-90) |
| GAME_OVER | `controller_engine.dart` (`endGame`), `controller_boxes.dart` | Done: three times 4 s apart after every game the phone ran ends, by its key's tag (kept beside the game), also after a restart without the key; the radio tuned to the game's channel and back; `game_over_frame` `sent`, `no_radio`, `no_join_key`, `no_tag` |
| The start guard | `controller_engine.dart` (`startGuards`), `controller_firmware.dart` | Done: the start check (missing roles, *Start anyway* with `force`) as since S1; an update on its way to a box blocks the start, `force` or not, until it ends or the GM cancels |
| Adoption: the field card | `controller_adoption.dart`, `controller_boxes_screen.dart` (`FieldCardTile`), `controller_screen.dart`; `lib/protocol/field_card.dart` | Done: `GET /api/v1/adopt`, `POST /api/v1/adopt/card` (never cached) and the records as the Pi's; the screen's *Cartão de campo* writes the card with the phone's NFC after the master-secret warning (PE24-93); USB adoption not offered (`usb: false`, 503, PE24-95) |
| Adoption: pairing by code | `controller_pairing.dart`; `lib/protocol/pair_frame.dart`, `lib/security/cpace.dart` | Done, as `pairing.py`: offers, one run at a time, CPace (X25519 on `BigInt`, Elligator 2, SHA-512), the join key and the field's name sealed in KEY, DONE checked with the fingerprint; the pairing channel for five minutes (`GET /api/v1/adopt/pair`, `POST .../listen`, `POST .../pair`; PE24-94) |
| Firmware updates | `controller_firmware.dart`, `controller_boxes_api.dart`, `controller_boxes_screen.dart` (`FirmwareKeysTile`), `app_store.dart`; `lib/protocol/firmware_release.dart` | Done, as `firmware_updates.py`: signed releases checked with the release keys set on the controller's screen (the app's settings) and kept in the controller's folder, CMD update over the radio only before a game starts, the release and image served without a token over the phone's HTTPS (the S6 field CA), the box's report, HELLO, `node.update_failed`, the timeout, cancel (PE24-96) |
| The radio | `controller_radio.dart` (field frames on `ControllerModem`), `serial_modem.dart`, `pod_modem.dart`, `controller_host.dart` | Done: the Pi's USB radio modem as the phone's radio (field and pair frames), told from a pod by its answer (PE24-92); the pod's side ready for RADIO_FIELD_* once its firmware relays them (PE24-91, a firmware follow-up) |
| What the console sees | `controller_api.dart` (`controllerFeatures`) | Done: `boxes`, `adoption` and `firmware` added to `whoami` (PE24-97) |

Tests: 10 new shared contract cases (45 in all; passing on both
controllers) with the new field and pair frame steps (PE24-98); 18 codec
tests (`test/protocol/field_frame_test.dart`: field frames, pair frames and
CPace, field cards, firmware releases against the shared vectors); 6
end-to-end tests (`boxes_e2e_test.dart`: a box that played a game invited
into the next one, GAME_OVER ending a key-lost game on the box, an
unadopted box paired by its code after a wrong one, a firmware offer
reaching the box and its own checks passing, a failed update coming back
over LoRa, the host pod saying it relays no field frames); 1 in
`pod_modem_test.dart`, 1 in `controller_host_test.dart` (a USB radio modem
through the relay), 7 in `boxes_screen_test.dart` (the field card in every
language at 320 px, a failed write, the release keys); the screen's
accessibility test now checks the whole screen on one tall view (a scroll
left a strip of a button under the app bar, which the contrast check read).
The Pi's contract runner sets up adoption and firmware updates as
`main.build` does; the Pi's code is otherwise unchanged.

Remaining (dated note, 2026-10-23): the rest of S7 is built too (below);
the pod firmware's relay of field frames was built as PE24-100 to PE24-104.
For the maintainer (S7c): PE24-91 (the pod's relay, a protocol and
firmware follow-up), PE24-92 (a USB radio modem on the phone), PE24-93 (the
field card written by the phone's NFC) and PE24-96 (firmware updates from a
phone, the release keys in the app).
For the maintainer: PE24-2 (a phone as the only controller, not a standby),
PE24-3 (not on plan phase G's gate), PE24-8 (the GM console's files in the
app), PE24-11, PE24-12, PE24-42, PE24-44, PE24-52 and PE24-60 (players'
personal data on a phone controller, in app-private storage with the Pi's
retention rules) are answered; PE24-51 was accepted by the coordinator;
open for the maintainer: PE24-58 (the fix in the Pi controller's poster
settings), PE24-62 (HTTPS only on the field's Wi-Fi, MQTT plain as on the
Pi), PE24-64 (the engine kept past the activity, the service's type) and
PE24-67 (the field CA on the phone, the pointycastle dependency) and PE24-70
(`features` in `whoami`, an API addition); for the
coordinator: PE24-61 (the console copied in at build time, CI's step).

### Slice S7b: presets, mode packages, scenarios and branding (2026-10-23)

Part of slice S7 pulled forward before the field test (the maintainer,
2026-10-23); decisions PE24-80 to PE24-89. Built and tested in software, on
one machine, against the real core; not on a phone. Built beside S7a (the
field plan, map features, the channel) and S7c (re-invites, adoption and
pairing, firmware updates) and rebased on them.

| Deliverable | Where | State |
| --- | --- | --- |
| Presets, mode uploads, role packages in a game | `app/lib/controller/controller_modes.dart`, `controller_engine.dart`, `controller_api_s7b.dart` | Done, as the Pi's `modes.py` and the simulator's `compose`: `GET|POST /api/v1/presets` (the read token without gm_only parameters; a game from a preset), `GET|POST /api/v1/modes` (uploads checked and loaded in the core, kept in the store), a game of a main mode with modifiers and role packages, or a scenario's; each box's join names only what it runs, with its parameters (PE24-80) |
| Signed mode packages | `mode_package.dart`, `controller_signed_modes.dart`, `controller_modes_screen.dart` | Done: the Dart port of `mode_package.py` (every group of `mode_package.json`), upload, the registry index (https or a file) with its revocations, trust shown per package; the `[modes]` settings in the app's *Definições* (PE24-81, PE24-82) |
| Modes sent to boxes | `controller_mode_fetch.dart`; join keys 16 and 17 in `app/lib/protocol/join_payload.dart` | Done, as `mode_fetch.py` with 4d0c23d's HELLO rule: the offer, the release and package without a token between games, the reports' HMAC, `hello_seen` and `report_lost`, `node.modes_failed`, the start guard, stopping the wait, boxes marked to forget; S7c's radio invites carry keys 16 and 17 and show a box fetching (PE24-83) |
| Scenarios | `app/lib/controller/scenarios/`, `controller_scenarios.dart` | Done: the validator and compiler ported to Dart (the same problems for `scenario.json`, the same field.lua and mode.yaml byte for byte for the new `scenario_compile.json`; since PE24-109 the phone only reads the manifest, and the rules and both files are the core's `core/scenario/`, which the Pi calls too), `POST /api/v1/scenarios/check`, `GET|POST /api/v1/scenarios`, `GET /api/v1/scenarios/{id}`, a scenario's game with the boxes the GM names, the staff's and the players' views, objective events by visibility (PE24-84) |
| Team branding | `controller_branding.dart`, `controller_images.dart` | Done: the field's name, accent, logo and wallpaper, crests, saved teams, a game's team names and crests, `branding` in the stream's hello; images checked and stripped as the Pi's `images.py`, byte for byte (PE24-85) |
| Shared contract cases | `protocol/vectors/controller_api.json` (`fixtures`, `mode_keys`, `mode_revoked`, `box_keys`, a raw body's `content_type`, the answer's `headers`) | Done: 11 new cases (56 in all), passing on both controllers (PE24-86) |
| What the console shows | `controller_api.dart` `controllerFeatures` | Done: `presets`, `branding`, `scenarios`, `mode_packages` added, so their tabs and panels show on a phone (PE24-89) |

Tests: 11 new shared contract cases (both controllers); new Dart tests:
16 in `mode_package_test.dart` (every vector group), 123 in
`controller_images_test.dart` (the Pi's image tests, 112 cases its checker
made, a bomb, cut zlib streams, 2,100 damaged files), 33 in
`scenarios_test.dart` (`scenario.json`, `scenario_compile.json`, the
runtime's copy), 11 in `controller_modes_test.dart` (composition, uploads
and presets across a restart, an index on the phone with its revocations,
keys 16 and 17, a crest's clean-up, the settings), 6 in
`controller_modes_screen_test.dart` (the settings' screen, the controller
started with them, 320 px and the accessibility guidelines in four
languages), 11 in `join_payload_test.dart` (join.json's `mode_fetch`);
the settings' golden images drawn again (the new tile). Python: the
contract runner's new step kinds and `test_scenario_compile_vectors.py`.
The Pi's controller code is unchanged.

Remaining of **S7** (dated note, 2026-10-23): built, below.

### Slice S7: failover, the site sync, the remote GM, ATAK (2026-10-23)

The last parts of slice S7, pulled forward before the field test (the
maintainer, 2026-10-23); decisions PE24-118 to PE24-129 (PE24-118, PE24-125,
PE24-126 and PE24-127 for the maintainer). Built and tested in software, on
one machine, against the real core; not on a phone. Each matches the Pi
controller, the reference.

| Deliverable | Where | State |
| --- | --- | --- |
| Failover | `app/lib/controller/controller_failover.dart`, `field_controller.dart`, `controller_engine.dart`, `controller_api.dart`; `RfClaim` in `app/lib/radio/rf_codec.dart` | Done: the simulator's `election.py` in Dart (TIME as the heartbeat, CLAIM, terms, priorities, manual or automatic), the FieldController following another controller's TIME and sending CLAIM, a standby joined from the leader's join of kind `controller` (`POST /api/v1/controller/join`), *Promote* (`POST /api/v1/controller/promote`), the leader's clock and state followed, `field.lua` taken over by the winner; a phone and a Pi each the other's standby (PE24-118); a Pi bug fixed in both: a restarted standby keeps its term (PE24-119) |
| The site sync | `controller_sync.dart`, `controller_sync_format.dart`, `controller_schedule.dart`; `controller_checkin.dart` (`applyRoster`, `outcomes`, a marshal's earlier keys), `controller_branding.dart` (`applySite`), `controller_store.dart` (`eventLog`) | Done, as `sync_client.py` with every body checked against `sync.json`'s rules: games, logs and scores (offline first, a cursor per game, PE24-122), the chrono registry, game day (the schedule, rosters, claims, outcomes), branding and saved teams with their images, the scenario library; the schedule's endpoints on the phone; status in `GET /api/v1/controller` (PE24-123); a Pi bug fixed in both: nodes that said HELLO were never sent (PE24-121) |
| The remote GM | `controller_remote_gm.dart` | Done, as `remote_gm.py`: the stream the phone opens, hello, the live view, commands checked and logged, `GET /api/v1/remote-gm` (PE24-128) |
| ATAK | `controller_atak.dart`; `protocol/vectors/atak_xml.json`, `tools/atak_xml_vectors.py` | Done, as `atak.py`, the XML byte for byte: multicast on the field's Wi-Fi without a multicast lock, staff devices over TCP, the relay through the remote GM's stream; `GET /api/v1/atak` (PE24-126) |
| Settings | `controller_site_screen.dart`, `app/lib/storage/app_store.dart`, `controller_host.dart` | Done: failover mode, the site server (address, the API key shown afterwards only by its fingerprint, branding, library, remote GM), ATAK, in *Definições*; the host builds each as the Pi's `main.build` (PE24-125) |
| What the console shows | `controllerFeatures` | Done: `failover`, `schedule`, `atak` added: the Pi's whole set (PE24-124) |
| Shared contract cases | `protocol/vectors/controller_api.json`, block `s7` | Done: 4 new cases (63 in all) on both controllers (PE24-120) |

Tests: 4 new shared contract cases (both controllers); new Dart tests: 20 in
`controller_failover_test.dart` (`test_election.py`'s cases, two phone
controllers failing over on a shared air), 183 in
`controller_sync_format_test.dart` (all of `sync.json`), 25 in
`controller_sync_test.dart` (the sync end to end against a site server in
the test over real HTTP), 14 in `controller_remote_gm_test.dart` (commands,
the log, the live view, the stream against a WebSocket in the test, the ATAK
relay), 35 in `controller_atak_test.dart` (`atak_xml.json`, `cot.json`,
`test_atak.py`'s cases, real UDP, multicast and TCP listeners), 6 in
`controller_site_screen_test.dart` (the settings in four languages at 320
px), 3 for CLAIM in `rf_codec_test.dart` (`claim.json`), 2 in
`field_controller_test.dart`; the settings' golden images and the test
font's Chinese subset made again. Python: the contract runner's new steps,
`test_sync_client.py` and `test_remote_gm.py` for the two fixes; the Pi's
code changed only for them (`engine.py`, `sync_client.py`, `remote_gm.py`).
Not run: the real site server against the phone (PE24-129).

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

## Money Factory (2026-10-23)

"Fábrica de Dinheiro" in Portuguese: teams capture factory boxes, which make
money while held; players collect it with their tag and bank it at a bank box
for points. Decision A1 deferred it because the money is collected at one box
and banked at another; the controller's `field.lua` now keeps what each player
carries. Decisions MF-A1 to MF-A12 in `docs/review/decisions-to-review.md`
(MF-A2, MF-A3, MF-A5 and MF-A6 for the maintainer).

| Deliverable | Where | State |
| --- | --- | --- |
| The mode | `modes/money_factory/`: `mode.yaml` (roles `factory`, requiring `nfc` and `team_input`, and `bank`, requiring `nfc`; `production` 1, `tick_s` 10, `capacity` 50, `carry_max` 20, `capture` on, `capture_hold_ms` 3000, `target` 0, `drop_on_heal` on; i18n pt), `node.lua` (capture, production, collecting, banking, every refusal with its reason), `field.lua` (the banks told what they are, each player's wallet told to the boxes, a heal at a medic kit empties it, the target), seven YAML screens in Portuguese and English | Done; 10 event-sequence tests run in the simulator and, through the core, in Dart |
| Events | `money.collected` (33) and `money.deposited` (34), unchanged since plan phase A | Done |
| GM console | the mode from the controller's catalogue; `feed.events.money_*` in four languages | Done; a browser test |
| Field Box | the fourteenth built-in preset, "Money Factory" (`builtin_presets.c`, `CMakeLists.txt`, `shell.c`, the host box); its seven screens built in; the image 18,400 bytes larger | Done; host tests, 8 reference images, the ESP-IDF Field Box build with 0 warnings |
| Android prop and app | no prop code: the catalogue reads the manifest (`builtin_modes.g.dart` regenerated); `event.money.*` in four languages | Done; catalogue, event text and 4 golden tests |
| Project page | a card on the modes page, the roadmap's phase 3, in pt, en, de and zh-tw | Done |

Tests: simulator (`test_money_factory.py`, 7: the manifest, the banks told
and reminded, wallets to banks and factories, an older word ignored, a bank
out of reach, the longest player id in a CMD, the capture bar), the 10 YAML
tests in Python and in Dart, the controller through the real engine and core
(`controller/tests/test_money_factory.py`, 2: the joins, the wallets over CMD,
the field state and the target ending the game), the Field Box's host tests
(`test_builtin_presets.c`: the preset from the picker, a tag refused without
a game, a bank; 8 reference images), the GM console in Chromium (the form,
a factory's join, both events in words in pt and en), Dart (the catalogue, the
event texts, 4 golden images).

Not run: real NFC tags on a phone or on the Field Box's PN532, real radios,
Wokwi (decision R7).

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
4. Implementation -- plan phases A-F done in software (E with the
   Android controller role's slices S1 to S6, PE24, done 2026-10-22, and
   S7a, S7b, S7c and the rest of S7, done 2026-10-23: the role is done in
   software), the Medic Kit and branding; next: plan phase G (the field
   test: the boards, the pods and real phones, with the Pi controller), with
   the phone controller's bench test (a phone, a pod, a box and a prop;
   PE24-3, PE24-69), with failover between the phone and the Pi on the
   bench

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
