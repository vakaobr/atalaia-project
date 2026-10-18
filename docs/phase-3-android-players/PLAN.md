<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 3 -- Android and Players: Implementation Plan

Gate: **one game mixes ESP32 and Android props without issues.**

Constraint: Phase 2 plan phases A-E are complete (commit `771fd90`,
2026-10-18); phase F (hardware field test) is pending.  All builds run
in Docker.  What can be built and tested without hardware is separated
from what needs real devices.  With phase 2 A-E done, roughly 85% of
phase 3 software can proceed immediately.

---

## 1. Scope

### In scope (what phase 3 delivers)

- Four new game modes (all single-node): Kill Confirmed, Respawn/Lives,
  Player Check-in, Money Factory.  (Hold-All Domination and Last Stand
  moved to the phase 2 mode pack per decision R6.)
- Event schema additions (`events.yaml`) for phase 3 events (IDs 25-26,
  33-41; IDs 27-32 owned by the phase 2 mode pack) plus `protogen.py`
  regeneration.
- Capability proxy protocol v1: frame format, CBOR payloads, test
  vectors shared by Dart and C.
- Declarative screen template format (YAML): parser, interpolation
  engine, LVGL renderer (ESP32), Flutter renderer (Android/iOS),
  migration of built-in modes (Domination, Bomb), CI validation.
- Flutter app (`app/`): dart:ffi bridge, game loop isolate, NDK
  cross-compile via Gradle, role selector (prop, controller, GM,
  player), Kotlin plugins (kiosk, foreground service, BLE pod, USB
  pod, NFC).
- Chrono check-in: data model, energy calculation, limit templates
  (Portugal APDA, UK UKARA, Germany, Generic CQB), spot-check
  comparison, marshal keypad UI, Ed25519-signed records (P3-1).
- Player positions and visibility: GPS and BLE beacon reporting,
  server-side role-based filtering, temporary visibility (UAV sweep).
- I/O pod firmware: `CONFIG_ATALAIA_POD_MODE` Kconfig variant, BLE
  GATT server, USB CDC serial, capability proxy, radio passthrough.
- Embedded MQTT broker (Dart) for the Android controller role.
- Security: player tokens (HMAC-SHA256), NFC tag signing, self-signed
  CA fingerprint in join + cert fetch over Wi-Fi, kiosk tamper detection.
- iOS build: player and GM roles only, conditional imports, App Store
  permission file.
- CI: four new jobs (`flutter-test`, `flutter-build-android`,
  `flutter-integration`, `core-android-ndk`), FFI stub library,
  template validation.

### Out of scope (deferred to phase 4+)

- Site server (accounts, history, chrono registry, remote setup).
- Master and Satellites, Target Windows, VIP/Payload, Hacking Terminal
  modes.
- ATAK / CoT integration.
- Visual editor / Blockly (phase 5).
- BLE chronograph integration (v1 is manual entry only).
- DIY chronograph addon hardware.
- LoRa player tags for fields without mobile coverage.
- Play Integrity / SafetyNet enforcement (optional, not default).
- Per-node session keys via HKDF.
- Cross-field chrono record sharing.
- Metre-level indoor positioning (BLE triangulation).
- iOS prop or controller roles.
- Hold-All Domination and Last Stand (moved to the phase 2 mode pack).

---

## 2. Constraints from ADR.md (all 24 respected)

| # | Constraint | How the plan respects it |
|---|------------|--------------------------|
| 1 | Game loop on a dedicated isolate | Phase C creates `GameLoopIsolate` in `app/lib/core/`; the UI isolate never calls `atalaia_node_*` functions; communication via `SendPort`/`ReceivePort` |
| 2 | `NativeCallable.listener` for all callbacks | Phase C uses `NativeCallable<T>.listener` for event, command and log callbacks; `Pointer.fromFunction` is never used |
| 3 | Gradle-integrated NDK build | Phase C adds `externalNativeBuild` to `app/android/app/build.gradle.kts`; CI verifies with `flutter build apk --debug` |
| 4 | Capability proxy protocol v1 is frozen | Phase A defines frame format, GATT UUIDs and characteristic layout per ADR-P3-2; shared test vectors in `protocol/vectors/capability_proxy.yaml` |
| 5 | Pod firmware is a Kconfig variant | Phase F adds `CONFIG_ATALAIA_POD_MODE` to the existing device-mode choice in `Kconfig.projbuild`; disables Lua, LVGL, preset store |
| 6 | Declarative templates are YAML | Phase B creates templates in `modes/*/assets/screens/*.yaml`; both LVGL (minimal YAML parser) and Flutter (`yaml` package) render the same files |
| 7 | Foreground service for Android props | Phase D implements `AtalaiaForegroundService` with a partial wake lock, persistent notification and Wi-Fi lock |
| 8 | Screen dimming, not sleeping | Phase D screen manager dims to 10% after 30 s, never calls `goToSleep` in kiosk mode; the game loop runs regardless |
| 9 | Server-side position filtering only | Phase E positions module sends only filtered positions per viewer role; the controller NEVER sends positions a client may not see |
| 10 | Positions over Wi-Fi or 4G, never LoRa | Phase E position reports go to `POST /api/v1/positions`; no LoRa path for positions |
| 11 | Ed25519 for chrono records; HMAC for NFC tags | Phase B chrono module signs readings with marshal's Ed25519 key (P3-1); NFC tags signed with game key (truncated 16-byte HMAC) |
| 12 | Event IDs 25-26 and 33-41 for phase 3 | Phase A adds phase 3 IDs; IDs 27-32 owned by phase 2 mode pack; phase 4 starts at ID 42 |
| 13 | iOS excludes prop and controller roles | Phase D uses conditional imports (`node_runner_stub.dart` on iOS); role selector hides prop/controller on iOS |
| 14 | FFI stub library for Dart tests | Phase C creates `core/tests/stub.c` with `ATALAIA_STUB=ON`; CI sets `ATALAIA_CORE_LIB` to the stub path |
| 15 | Four new CI jobs | Phase C adds `flutter-test` and `core-android-ndk`; Phase D adds `flutter-build-android` and `flutter-integration` |
| 16 | Embedded MQTT broker on Android only | Phase E creates a minimal Dart MQTT 3.1.1 broker (~500-800 LOC) for the controller role; Pi uses Mosquitto unchanged |
| 17 | Shared capability proxy test vectors | Phase A creates `protocol/vectors/capability_proxy.yaml` tested in both Dart and C |
| 18 | GDPR retention for chrono records | Phase B implements configurable retention (default 12 months) with auto-delete and right of erasure via API |
| 19 | Limit templates are YAML files | Phase B ships four templates in `app/lib/chrono/limit_templates/` with source and verification date |
| 20 | All phase 3 modes are single-node | Phase A implements Kill Confirmed, Respawn, Player Check-in and Money Factory as single-node modes; Hold-All and Last Stand moved to phase 2 mode pack (R6) |
| 21 | BLE beacons are standard iBeacon hardware | Phase E position scanner uses standard iBeacon format; no custom beacon firmware |
| 22 | Self-signed CA fingerprint in join, cert over Wi-Fi | Phase E uses join payload key 13 for SHA-256 fingerprint; app fetches full cert from `GET /api/v1/controller/ca` and verifies fingerprint; needs RFC amendment |
| 23 | SPDX headers on every file | `app/` uses `GPL-3.0-or-later`; `controller/` uses `AGPL-3.0-or-later`; docs use `CC-BY-SA-4.0` |
| 24 | Minimum Android API 26 | Phase C sets `minSdkVersion 26` in `build.gradle.kts` |

---

## Phase A: Event schema, single-node game modes, capability proxy protocol, screen template format

### Goal

Deliver everything that needs NO hardware, NO phase 2 completion, and
NO Flutter. This means the three single-node game modes (Kill
Confirmed, Respawn/Lives, Player Check-in), the capability proxy
protocol definition with shared test vectors, the declarative screen
template format with both renderers, the chrono data model and energy
calculation, and the event schema additions. Everything runs in Docker
on the desktop using the existing `atalaia-dev` image and ESP-IDF
cross-compile image.

**Dependencies:** Phase 1 (complete), Phase 2A and 2B (complete). No
phase 2C/D/E dependency. No hardware dependency.

### Files to create

| File | Purpose |
|------|---------|
| `modes/kill_confirmed/mode.yaml` | Kill Confirmed manifest: requires `nfc`, optional `display` |
| `modes/kill_confirmed/node.lua` | NFC tag scan, team scoring (+1/-1), HMAC verification |
| `modes/kill_confirmed/tests/basic.yaml` | Red scans blue tag (+1/-1), same-team rejected, invalid tag rejected |
| `modes/respawn/mode.yaml` | Respawn manifest: requires `nfc` or `qr`, params `lives_per_team`, `respawn_cooldown_s` |
| `modes/respawn/node.lua` | Life counter, cooldown enforcement, `team.eliminated` |
| `modes/respawn/tests/basic.yaml` | 3 lives, 4th rejected; per-player mode; cooldown test |
| `modes/player_checkin/mode.yaml` | Player Check-in manifest: requires `nfc` or `qr`, optional `display` |
| `modes/player_checkin/node.lua` | Per-team player count, duplicate rejection |
| `modes/player_checkin/tests/basic.yaml` | 3 players, counts correct; duplicate rejected |
| `protocol/vectors/capability_proxy.yaml` | Shared test vectors for IDENT, EVT, CMD, ACK frames |
| `core/include/atalaia/screen_template.h` | Template node struct, parse and interpolation API (C) |
| `core/src/screen_template.c` | Minimal YAML subset parser (~3 KB), expression evaluator (~100 LOC), template cache |
| `core/tests/test_screen_template.c` | Parse valid/invalid templates; interpolate variables; expression evaluation |
| `firmware/esp32/main/screen_template.c` | LVGL renderer: create LVGL widgets from template tree; patch on data change |
| `firmware/esp32/test/test_screen_template.c` | LVGL renderer tests: widget creation, data patching, fallback to C functions |
| `modes/domination/assets/screens/standby.yaml` | Declarative template: team icon, "HOLD TO CAPTURE" label |
| `modes/domination/assets/screens/captured.yaml` | Declarative template: team colour, score, capture time |
| `modes/domination/assets/screens/final_score.yaml` | Declarative template: per-team scores |
| `modes/bomb/assets/screens/standby.yaml` | Declarative template: "STANDBY" label |
| `modes/bomb/assets/screens/countdown.yaml` | Declarative template: time_left label, progress bar, "ARMED" |
| `modes/bomb/assets/screens/defused.yaml` | Declarative template: "DEFUSED" with team colour |
| `modes/bomb/assets/screens/exploded.yaml` | Declarative template: "EXPLODED" with team colour |
| `modes/bomb/assets/screens/final_score.yaml` | Declarative template: per-team scores |

### Files to modify

| File | Change |
|------|--------|
| `protocol/schema/events.yaml` | Add 15 events (IDs 25-39): `kill.confirmed`, `kill.denied`, `team.eliminated`, `holdall.scoring_start`, `holdall.scoring_stop`, `laststand.countdown_start`, `laststand.countdown_cancel`, `laststand.defeated`, `chrono.checkin`, `chrono.spotcheck`, `visibility.granted`, `visibility.expired`, `node.tamper`, `pod.connected`, `pod.disconnected`; add 3 data fields (keys 28-30): `duration_s`, `see_team`, `tolerance_pct` |
| `core/CMakeLists.txt` | Add `screen_template.c` to the source list |
| `core/tests/CMakeLists.txt` | Add `test_screen_template` executable |
| `firmware/esp32/main/CMakeLists.txt` | Add `screen_template.c` |
| `firmware/esp32/main/screen_renderer.c` | Add fallback: if YAML template exists, call `screen_render_template`; otherwise use existing C function |
| `firmware/esp32/test/CMakeLists.txt` | Add `test_screen_template` executable |

### Tests to create

| File | What it tests |
|------|---------------|
| `modes/kill_confirmed/tests/basic.yaml` | Red scans blue NFC tag: red +1, blue -1; same-team scan: no effect; unsigned tag: rejected |
| `modes/respawn/tests/basic.yaml` | Team with 3 lives: 3 respawns succeed, 4th emits `team.eliminated`; cooldown enforced (scan during cooldown rejected) |
| `modes/player_checkin/tests/basic.yaml` | 3 players check in from 2 teams; counts correct; duplicate scan within 10 s rejected |
| `core/tests/test_screen_template.c` | Parse countdown template; interpolate `{left}`, `{left / params.fuse_s}`; invalid YAML rejected; unknown widget type rejected; expression edge cases (division by zero = 0) |
| `firmware/esp32/test/test_screen_template.c` | LVGL renderer creates correct widgets; data patch updates only changed widgets; fallback to C screen function when no template file |

### Validation (Phase A)

**Event schema generation:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" atalaia-dev ^
  python3 tools/protogen.py --check
```

**Core tests with screen template parser:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" atalaia-dev ^
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**New mode tests pass:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" atalaia-dev ^
  sh -c "cd /src && python3 -m pytest modes/ -v"
```

**ESP32 cross-compile with screen template renderer:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/project" -w /project/firmware/esp32 ^
  espressif/idf:v5.3.2 ^
  bash -c "idf.py set-target esp32s3 && idf.py build"
```

**Firmware host tests with screen template renderer:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" atalaia-dev ^
  sh -c "cmake -S /src/firmware/esp32/test -B /tmp/fw-test \
         -DCORE_DIR=/src/core \
         -DCMAKE_BUILD_TYPE=Debug && \
         cmake --build /tmp/fw-test && \
         ctest --test-dir /tmp/fw-test --output-on-failure"
```

---

## Phase B: Chrono data model, energy calculation, limit templates

### Goal

Implement the chrono check-in data model, energy calculation library,
limit templates, spot-check comparison algorithm, and the HMAC-signed
record format. This is pure Dart/data logic with no Flutter UI yet
(that comes in Phase D). Tests run against Dart's test framework on
the desktop. The limit templates are YAML files shipped with the app.

**Dependencies:** None. No phase 2 dependency. No hardware dependency.
No Flutter UI dependency (this is the logic/data layer).

### Files to create

| File | Purpose |
|------|---------|
| `app/lib/chrono/energy.dart` | Energy calculation: `E = 0.5 * (bb_weight_g / 1000) * velocity_mps^2`; FPS/MPS conversion utilities |
| `app/lib/chrono/reading.dart` | `ChronoReading` data class with all fields from ADR-P3-7 |
| `app/lib/chrono/replica.dart` | `Replica` data class: id, owner, type enum, class, make_model, tag_type, tag_uid |
| `app/lib/chrono/limit_template.dart` | `LimitTemplate` and `ClassLimit` data classes; YAML loader |
| `app/lib/chrono/spot_check.dart` | Spot-check comparison: PASS/WARN/FAIL logic per ADR-P3-7 |
| `app/lib/chrono/hmac_signer.dart` | HMAC-SHA256 signing and verification of chrono records; canonical JSON serialisation |
| `app/lib/chrono/limit_templates/portugal_apda.yaml` | Portugal APDA/FPA limits: rifle 1.14J, DMR 1.88J, sniper 2.81J, CQB 0.84J |
| `app/lib/chrono/limit_templates/uk_ukara.yaml` | UK UKARA limits: rifle 1.14J, DMR 1.64J, sniper 2.32J |
| `app/lib/chrono/limit_templates/germany.yaml` | Germany limits: 0.5J full-auto, 7.5J semi-only (18+) |
| `app/lib/chrono/limit_templates/generic_cqb.yaml` | Generic CQB: all classes 1.0J max |
| `app/lib/security/nfc_tag_signer.dart` | NFC tag payload signing (HMAC-SHA256, truncated to 16 bytes) and verification |
| `app/lib/security/player_token.dart` | Player token: HMAC-SHA256-signed JSON with player_id, team, squad, role, game_id, exp |
| `app/test/chrono/energy_test.dart` | Energy calculation: 0.20g at 100 m/s = 1.0J; 0.25g at 90 m/s; edge cases (0 velocity, 0 weight) |
| `app/test/chrono/spot_check_test.dart` | PASS: under limit and within 5% of check-in; WARN: under limit but >5% above check-in; FAIL: over limit |
| `app/test/chrono/hmac_signer_test.dart` | Sign then verify round-trip; tampered record fails verification; canonical JSON is deterministic |
| `app/test/chrono/limit_template_test.dart` | Load Portugal template; look up rifle limit; unknown class returns null |
| `app/test/security/nfc_tag_signer_test.dart` | Sign and verify tag payload; wrong game key fails; truncation to 16 bytes |
| `app/test/security/player_token_test.dart` | Create token, verify signature; expired token rejected; wrong game key rejected |
| `app/pubspec.yaml` | Flutter project definition with dependencies: `yaml`, `crypto`, `ffi`, `pointycastle` |

### Files to modify

| File | Change |
|------|--------|
| (none -- all new files) | |

### Tests to create

| File | What it tests |
|------|---------------|
| `app/test/chrono/energy_test.dart` | Energy formula accuracy; FPS/MPS conversion; edge cases |
| `app/test/chrono/spot_check_test.dart` | Three outcomes: PASS, WARN, FAIL with concrete numbers; configurable tolerance |
| `app/test/chrono/hmac_signer_test.dart` | Sign-verify round-trip; tamper detection; canonical JSON key ordering |
| `app/test/chrono/limit_template_test.dart` | Load all 4 templates; class lookup; MED values |
| `app/test/security/nfc_tag_signer_test.dart` | Sign-verify with known key; cross-game rejection; 16-byte truncation |
| `app/test/security/player_token_test.dart` | Token creation and verification; expiry; role extraction |

### Validation (Phase B)

**Dart unit tests (chrono + security):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" -w /src/app ^
  cirruslabs/flutter:stable ^
  flutter test test/chrono/ test/security/ -v
```

---

## Phase C: dart:ffi bridge, game loop isolate, FFI stub, NDK cross-compile, CI

### Goal

Build the core Dart FFI bridge to `libatalaia_core.so`, the game loop
isolate, the FFI stub library for testing, the Gradle NDK
cross-compile integration, and the first two CI jobs (`flutter-test`,
`core-android-ndk`). After this phase, `flutter test` passes on
desktop and the core cross-compiles for Android ABIs. No Flutter UI
yet -- only the engine layer.

**Dependencies:** Phase A (screen template parser in core). No phase 2
dependency. No hardware dependency.

### Files to create

| File | Purpose |
|------|---------|
| `app/lib/ffi/bindings.dart` | Dart FFI bindings mirroring `core.py`: `atalaia_node_create`, `_destroy`, `_load`, `_set_teams`, `_set_params`, `_input`, `_advance`, `_status`, `_mem_used` |
| `app/lib/ffi/callbacks.dart` | `NativeCallable.listener` wrappers for event, command, log callbacks; posts to `SendPort` |
| `app/lib/ffi/native_types.dart` | Dart FFI struct definitions: `NodeConfig`, `NodeCallbacks`, `ScoreT` |
| `app/lib/core/game_loop_isolate.dart` | `GameLoopIsolate`: owns node pointer, 100 Hz `Timer.periodic`, drains input queue, dispatches callbacks to UI via `SendPort` |
| `app/lib/core/node_runner_android.dart` | Android implementation: loads `libatalaia_core.so`, creates `GameLoopIsolate` |
| `app/lib/core/node_runner_stub.dart` | No-op implementation for iOS and web (no dart:ffi) |
| `app/lib/core/node_runner.dart` | Conditional import: `node_runner_android.dart` on Android, `node_runner_stub.dart` elsewhere |
| `core/tests/stub.c` | FFI stub implementing all `node.h` functions with predictable return values |
| `app/android/app/build.gradle.kts` | Android build config with `externalNativeBuild` for CMake NDK cross-compile; `minSdkVersion 26`; ABI filters: arm64-v8a, armeabi-v7a, x86_64 |
| `app/test/ffi/bindings_test.dart` | Load stub library, call every binding, verify return values |
| `app/test/core/game_loop_isolate_test.dart` | Create isolate with stub, send input, verify callback via `ReceivePort` |

### Files to modify

| File | Change |
|------|--------|
| `core/CMakeLists.txt` | Add `ATALAIA_STUB` option; when ON, build `stub.c` as `libatalaia_core_stub` shared library |
| `core/tests/CMakeLists.txt` | Add stub library target |
| `.github/workflows/ci.yml` | Add `flutter-test` job (build stub .so, `flutter test`) and `core-android-ndk` job (CMake + NDK cross-compile for ARM64) |

### Tests to create

| File | What it tests |
|------|---------------|
| `app/test/ffi/bindings_test.dart` | Load stub, call `atalaia_node_create` (returns non-null), `_load` (returns 0), `_status` (returns EMPTY), `_destroy` (no crash) |
| `app/test/core/game_loop_isolate_test.dart` | Start isolate, send `game.start` input, receive event callback message on `ReceivePort`; stop isolate cleanly |

### Validation (Phase C)

**Build FFI stub library:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" atalaia-dev ^
  sh -c "cmake -S /src/core -B /tmp/stub-build \
         -DATALAIA_SHARED=ON -DATALAIA_STUB=ON && \
         cmake --build /tmp/stub-build"
```

**Dart unit tests with stub:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" -w /src/app ^
  -e ATALAIA_CORE_LIB=/tmp/stub-build/libatalaia_core_stub.so ^
  cirruslabs/flutter:stable ^
  flutter test -v
```

**Core cross-compile for Android ARM64 (NDK):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" ^
  cirruslabs/flutter:stable ^
  sh -c "cd /src/app && flutter build apk --debug 2>&1 | tail -20"
```

---

## Phase D: Flutter UI, Kotlin plugins, Android prop shell, iOS build

### Goal

Build the Flutter UI for all four roles (prop, controller, GM, player),
the five Kotlin plugins (kiosk, foreground service, BLE pod, USB pod,
NFC), the Android prop shell (capability mapping, screen management,
battery exemption guide), the screen template Flutter renderer, the
iOS conditional build, and the two remaining CI jobs
(`flutter-build-android`, `flutter-integration`). After this phase,
the app compiles for Android and iOS, renders all templates, and
passes integration tests on an emulator.

**Dependencies:** Phase B (chrono logic), Phase C (FFI bridge). No
phase 2 dependency (app connects to mock APIs in tests). No hardware
dependency (NFC, BLE, GPS mocked in integration tests).

### Files to create

| File | Purpose |
|------|---------|
| `app/lib/ui/screen_template.dart` | Flutter template renderer: parse YAML, build widget tree, reactive rebuild on data change |
| `app/lib/ui/role_selector.dart` | Role selection screen; hides prop/controller on iOS |
| `app/lib/ui/theme.dart` | Team colours, dark/light mode, outdoor-readable fonts |
| `app/lib/prop/capability_mapper.dart` | Maps phone sensors (GPS, NFC, IMU, camera, speaker, touch) to capability types |
| `app/lib/prop/screen_manager.dart` | Active/dimmed/off transitions; `FLAG_KEEP_SCREEN_ON`; brightness control |
| `app/lib/prop/prop_shell.dart` | Prop role entry point: start foreground service, create node runner, map capabilities |
| `app/lib/player/player_views.dart` | Player role views: scores, objectives, lives, respawn timer, messages |
| `app/lib/player/gm_webview.dart` | GM role: WebView wrapping the GM console URL |
| `app/lib/chrono/chrono_ui.dart` | Marshal chrono check-in UI: large keypad, pass/fail badge, spot-check comparison |
| `app/lib/chrono/replica_registry_ui.dart` | Replica registration form: type, class, make/model, NFC/QR tag |
| `app/lib/pod/pod_client.dart` | Dart client for the I/O pod: BLE GATT + USB CDC transport abstraction; frame codec |
| `app/lib/pod/pod_codec.dart` | Capability proxy frame encode/decode (mirrors `protocol/vectors/capability_proxy.yaml`) |
| `app/lib/platform/platform_check.dart` | Platform detection: `isAndroid`, `isIOS`; conditional feature gating |
| `app/android/app/src/main/kotlin/org/atalaia/app/KioskPlugin.kt` | Lock-task mode: `startLockTask`, `stopLockTask`, admin PIN verification |
| `app/android/app/src/main/kotlin/org/atalaia/app/ForegroundServicePlugin.kt` | Foreground service: partial wake lock, persistent notification, Wi-Fi lock |
| `app/android/app/src/main/kotlin/org/atalaia/app/BlePodPlugin.kt` | BLE GATT client for I/O pod: scan, connect, notify/write characteristics |
| `app/android/app/src/main/kotlin/org/atalaia/app/UsbPodPlugin.kt` | USB-OTG CDC serial for I/O pod: open device, read/write frames |
| `app/android/app/src/main/kotlin/org/atalaia/app/NfcPlugin.kt` | NFC foreground dispatch: read tag UID + NDEF data |
| `app/lib/prop/battery_exemption_guide.dart` | OEM-specific battery exemption instructions (Samsung, Xiaomi, Huawei, OnePlus, generic) |
| `app/android/app/src/main/AndroidManifest.xml` | Permissions: FOREGROUND_SERVICE, WAKE_LOCK, NFC, BLUETOOTH, USB_HOST, CAMERA, ACCESS_FINE_LOCATION |
| `app/ios/Runner/Info.plist` | iOS permissions: camera (QR), NFC, location |
| `app/APP-STORE-PERMISSION.md` | GPL section 7 additional permission for Apple App Store |
| `app/test/ui/screen_template_test.dart` | Widget tests: parse and render countdown template; interpolation; unknown widget type |
| `app/test/pod/codec_test.dart` | Encode/decode all frame types against shared vectors in `protocol/vectors/capability_proxy.yaml` |
| `app/test/prop/capability_mapper_test.dart` | Phone with GPS+NFC+IMU maps to expected capability list |
| `app/integration_test/role_switching_test.dart` | Start app, switch roles, verify correct screens |
| `app/integration_test/game_flow_test.dart` | Join game (mocked), receive events, display scores |

### Files to modify

| File | Change |
|------|--------|
| `app/pubspec.yaml` | Add dependencies: `yaml`, `mobile_scanner`, `geolocator`, `flutter_blue_plus`, `usb_serial`, `nfc_manager`, `qr_flutter`, `webview_flutter` |
| `.github/workflows/ci.yml` | Add `flutter-build-android` job (Flutter SDK + Android SDK + NDK, `flutter build apk --debug`) and `flutter-integration` job (emulator + `flutter test integration_test/`) |

### Tests to create

| File | What it tests |
|------|---------------|
| `app/test/ui/screen_template_test.dart` | Parse countdown YAML; render to Flutter widgets; interpolation of `{left}`, `{left / params.fuse_s}`; `team` colour resolution |
| `app/test/pod/codec_test.dart` | IDENT frame encode/decode; EVT frame; CMD frame; ACK frame; RADIO_RX/TX frames; all against shared vectors |
| `app/test/prop/capability_mapper_test.dart` | Phone with GPS+NFC+IMU produces correct capability descriptors |
| `app/integration_test/role_switching_test.dart` | App starts, role selector visible, switching to player shows player views |
| `app/integration_test/game_flow_test.dart` | Mock API: join game, receive `zone.captured` via WebSocket, score updates on screen |

### Validation (Phase D)

**Flutter widget and unit tests:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" -w /src/app ^
  -e ATALAIA_CORE_LIB=/tmp/stub-build/libatalaia_core_stub.so ^
  cirruslabs/flutter:stable ^
  flutter test -v
```

**Android APK builds with NDK cross-compile:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" -w /src/app ^
  cirruslabs/flutter:stable ^
  flutter build apk --debug
```

**iOS build (on macOS CI runner, or skip if unavailable):**

```sh
flutter build ios --no-codesign --debug
```

**Integration tests on Android emulator (CI):**

The `flutter-integration` CI job uses
`reactivecircus/android-emulator-runner@v2` with API 30 x86_64 and
runs `flutter test integration_test/`.

---

## Phase E: Player positions, embedded MQTT, controller integration

### Goal

Implement the features that depend on the phase 2 controller: player
position reporting and server-side filtering, the embedded MQTT broker
for the Android controller role, the player app connection to the
controller REST/WebSocket API, the position module (GPS outdoors, BLE
beacons indoors, temporary visibility), player token issuance, and
the CA fingerprint distribution (`GET /api/v1/controller/ca`).  After
this phase, the Flutter app connects to a real controller and all 4
phase 3 game modes are testable end-to-end.  (Hold-All Domination and
Last Stand are delivered by the phase 2 mode pack, not this phase.)

**Dependencies:** Phase 2D (Python controller REST/WS API) for
app-to-controller integration. Phase D (Flutter UI).

### Files to create

| File | Purpose |
|------|---------|
| ~~`modes/hold_all_domination/`~~ | **Moved to the phase 2 mode pack (R6)** |
| ~~`modes/last_stand/`~~ | **Moved to the phase 2 mode pack (R6)** |
| `modes/last_stand/field.lua` | Per-team zone count; countdown when holding exactly 1; cancel on recapture; `laststand.defeated` |
| `modes/last_stand/tests/basic.yaml` | 3 zones: red holds 1 (countdown); captures 2nd (cancel); countdown expires (defeated) |
| `app/lib/position/position_reporter.dart` | GPS reporter via `FusedLocationProviderClient`; configurable interval (5-60 s) |
| `app/lib/position/beacon_scanner.dart` | BLE iBeacon scanner; reports strongest beacon_id |
| `app/lib/position/position_report.dart` | Position report data class: player_id, team, lat, lon, accuracy, source, beacon_id, t |
| `app/lib/controller/api_client.dart` | REST client for the controller API: join, scores, log, positions |
| `app/lib/controller/ws_client.dart` | WebSocket client for `/api/v1/stream`: live events, scores, positions |
| `app/lib/controller/mqtt_broker.dart` | Embedded MQTT 3.1.1 broker (~500-800 LOC Dart): CONNECT/PUBLISH/SUBSCRIBE/PING/DISCONNECT, QoS 0-1 |
| `app/lib/controller/visibility_engine.dart` | Server-side position filtering by role (player, squad leader, VIP, marshal, GM, spectator) |
| `app/lib/controller/controller_shell.dart` | Android controller role: start MQTT broker, create node runner for `field.lua`, REST API |
| `app/test/position/visibility_engine_test.dart` | Player sees own position only; marshal sees all; squad leader sees squad; GM sees all |
| `app/test/controller/mqtt_broker_test.dart` | Connect, subscribe, publish, receive; QoS 1 PUBACK; 20 concurrent connections |
| `app/test/controller/api_client_test.dart` | Mock HTTP: join game, get scores, get log |

### Files to modify

| File | Change |
|------|--------|
| `simulator/atalaia_sim/core.py` | Verify `field_ops` support (should already exist from phase 2C); if not, add it |
| `controller/src/api.py` | Add `POST /api/v1/positions` endpoint and `GET /api/v1/positions` with role-based filtering (if not done in phase 2D) |

### Tests to create

| File | What it tests |
|------|---------------|
| ~~`modes/hold_all_domination/tests/`~~ | **Moved to the phase 2 mode pack (R6)** |
| ~~`modes/last_stand/tests/`~~ | **Moved to the phase 2 mode pack (R6)** |
| `app/test/position/visibility_engine_test.dart` | All role/visibility combinations from ADR-P3-6 table |
| `app/test/controller/mqtt_broker_test.dart` | Connect/subscribe/publish round-trip; QoS 1; max connections |
| `app/test/controller/api_client_test.dart` | Join, scores, log via mock HTTP |

### Validation (Phase E)

**All mode tests pass (including new single-node modes from Phase A
and Hold-All/Last Stand from the phase 2 mode pack):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" atalaia-dev ^
  sh -c "cd /src && python3 -m pytest modes/ -v"
```

**Position visibility and MQTT tests:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" -w /src/app ^
  cirruslabs/flutter:stable ^
  flutter test test/position/ test/controller/ -v
```

---

## Phase F: I/O pod firmware

### Goal

Build the I/O pod firmware variant (`CONFIG_ATALAIA_POD_MODE`): BLE
GATT server, USB CDC serial, capability proxy protocol, radio
passthrough, and all HAL modules reused from node firmware. The pod
firmware cross-compiles in the ESP-IDF Docker image. BLE and USB
integration with the phone requires real hardware.

**Dependencies:** Phase A (capability proxy protocol definition and
test vectors). Phase 2A (packet codec, AES-CCM, flood -- complete).
**Hardware required** for BLE/USB link testing.

### Files to create

| File | Purpose |
|------|---------|
| `firmware/esp32/main/pod/proxy_task.h` | Proxy task API: `proxy_task_start()` |
| `firmware/esp32/main/pod/proxy_task.c` | FreeRTOS task (core 1, priority 5): read EVTs from HAL queues, send to phone; receive CMDs from phone, dispatch to HAL; frame encode/decode |
| `firmware/esp32/main/pod/ble_gatt_task.h` | BLE GATT server API: `ble_gatt_task_start()` |
| `firmware/esp32/main/pod/ble_gatt_task.c` | GATT server with custom service UUID from ADR-P3-2; Pod TX (notify), Pod RX (write), Pod Status (read+notify); one connection at a time |
| `firmware/esp32/main/pod/usb_cdc_task.h` | USB CDC serial API: `usb_cdc_task_start()` |
| `firmware/esp32/main/pod/usb_cdc_task.c` | USB CDC ACM device at 921600 baud; frame read/write; same framing as radio modem |
| `firmware/esp32/main/pod/pod_config.h` | Pod NVS configuration: radio region, button pins, LED count, admin PIN |
| `firmware/esp32/main/pod/pod_shell.c` | `app_main` for pod mode: init HAL, start proxy, BLE, USB, radio, audio, mem_monitor tasks |
| `firmware/esp32/test/test_proxy_codec.c` | Encode/decode all capability proxy frame types against shared vectors in `protocol/vectors/capability_proxy.yaml` |
| `firmware/esp32/test/test_ble_gatt_stub.c` | BLE GATT stub tests: IDENT response, EVT notification, CMD reception |

### Files to modify

| File | Change |
|------|--------|
| `firmware/esp32/main/Kconfig.projbuild` | Add `CONFIG_ATALAIA_POD_MODE` to device-mode choice alongside NODE and MODEM |
| `firmware/esp32/main/CMakeLists.txt` | Conditionally include `pod/` sources when `CONFIG_ATALAIA_POD_MODE` is set; exclude Lua, LVGL, preset store, game loop |
| `firmware/esp32/main/shell.c` | Dispatch to `pod_shell_main()` when pod mode is active |
| `firmware/esp32/test/CMakeLists.txt` | Add `test_proxy_codec` and `test_ble_gatt_stub` executables |

### Tests to create

| File | What it tests |
|------|---------------|
| `firmware/esp32/test/test_proxy_codec.c` | Encode IDENT, EVT, CMD, ACK, RADIO_RX, RADIO_TX frames; decode and compare against shared vectors; round-trip for each frame type |
| `firmware/esp32/test/test_ble_gatt_stub.c` | GATT server stub: advertise service UUID; send IDENT on connection; receive CMD frame and dispatch to HAL stub; EVT from HAL stub reaches phone |

### Validation (Phase F)

**Pod firmware cross-compile:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/project" -w /project/firmware/esp32 ^
  espressif/idf:v5.3.2 ^
  bash -c "idf.py set-target esp32s3 && \
           idf.py -DCONFIG_ATALAIA_POD_MODE=y build"
```

**Node firmware still builds (regression check):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/project" -w /project/firmware/esp32 ^
  espressif/idf:v5.3.2 ^
  bash -c "idf.py set-target esp32s3 && idf.py build"
```

**Pod firmware host tests (codec):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" atalaia-dev ^
  sh -c "cmake -S /src/firmware/esp32/test -B /tmp/fw-test \
         -DCORE_DIR=/src/core \
         -DCMAKE_BUILD_TYPE=Debug && \
         cmake --build /tmp/fw-test && \
         ctest --test-dir /tmp/fw-test --output-on-failure"
```

---

## Phase G: Integration, field test, documentation

### Goal

Bring all pieces together end-to-end on real hardware: flash node
firmware to at least one ESP32 board, flash pod firmware to a second
board, pair the pod with an Android phone running the app, deploy the
Python controller on the Pi, and execute the mixed-device field test
(the Phase 3 gate). Update all documentation. This phase cannot be
completed without hardware.

**Dependencies:** ALL previous phases. Phase 2D (Python controller).
Phase 2F (field-tested LoRa protocol). **Hardware required:**
ESP32 LoRa boards, Android phone(s), Raspberry Pi, I/O pod
components.

### Files to create

| File | Purpose |
|------|---------|
| `docs/phase-3-android-players/FIELD_TEST.md` | Field test runbook: mixed ESP32 + Android game scenarios, metrics, pass criteria |
| `docs/guides/android-prop-setup.md` | Android prop setup guide: device owner provisioning, battery exemption, kiosk mode |
| `docs/guides/io-pod-build.md` | I/O pod build guide: wiring, enclosure, firmware flash |
| `docs/templates/privacy-notice.md` | GDPR privacy notice template for field operators |

### Files to modify

| File | Change |
|------|--------|
| `firmware/esp32/README.md` | Add I/O pod firmware variant section, pod build instructions, pod pin assignments |
| `README.md` (project root) | Update project status: Phase 3 deliverables, Flutter app, player roles, game modes |
| `app/README.md` | Full documentation: architecture, roles, build instructions, dependencies |
| `core/README.md` | Add dart:ffi section, Android cross-compile instructions, stub library usage |
| `modes/README.md` | Add new modes, declarative template format documentation |

### Validation (Phase G)

**Full CI pipeline passes:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" atalaia-dev ^
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**All mode tests pass:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" atalaia-dev ^
  sh -c "cd /src && python3 -m pytest modes/ -v"
```

**All Flutter tests pass:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" -w /src/app ^
  cirruslabs/flutter:stable ^
  flutter test -v
```

**Mixed-device field test:**

Execute the Field Test Plan below.

---

## 4. Assumptions about phases 1 and 2

**Updated 2026-10-18 (phase 2 handoff).** Phase 2 A-E are now
complete.  All assumptions are re-checked against the implemented code.

| # | Assumption | Source | Status | Phases that depend on it | Impact if wrong |
|---|-----------|--------|--------|--------------------------|-----------------|
| A1 | `atalaia_node_t` API is stable | `core/include/atalaia/node.h` | **Holds** | C, D | **High.** Dart FFI wraps every function. |
| A2 | `atalaia_node_callbacks_t` signatures stable | `core/include/atalaia/node.h` | **Holds** | C | **High.** Dart `NativeCallable` depends on exact signatures. |
| A3 | Core builds as shared library | `core/CMakeLists.txt` | **Holds** | C | **Medium.** |
| A4 | `atalaia_score_t` and merge available | `core/include/atalaia/score.h` | **Holds** | D | **Low.** |
| A5 | `atalaia_node_status_t` enum stable | `core/include/atalaia/node.h` | **Holds** | C, D | **Low.** |
| A6 | HAL ops struct pattern | `firmware/esp32/main/hal/` | **Holds** | F | **Medium.** |
| A7 | Screen templates are C functions | `screen_renderer.c` | **Holds** | A | **Medium.** Declarative templates added alongside. |
| A8 | `ui.screen(template, data)` script API | `core/src/script_api.c` | **Holds** | A, D | **Low.** |
| A9 | LittleFS partition layout | ADR-P1-4 | **Holds** | F | **Low.** |
| A10 | FreeRTOS extensible | ADR-P1-7 | **Holds** | F | **Low.** |
| B1 | `state.field{}` and `field.*` Lua API | Phase 2C | **Done** | -- | Hold-All and Last Stand moved to phase 2 mode pack (R6). No phase 3 mode needs `field.*`. |
| B2 | `field_ops` pointer in `atalaia_node_config_t` | Phase 2C | **Done** | E (Android controller) | Exists; runs on the controller via ctypes. |
| B3 | Packet codec stable | Phase 2A; `core/include/atalaia/packet.h` | **Holds** | F | **High.** Codecs are schema-exact (D8). |
| B4 | USB modem framing stable | `protocol/usb-modem.md` | **Changed** (D1) | F | **High.** Now 0xA5 sync + type + len + payload + CRC-16. RADIO_RX carries epoch (D2). Pod framing updated in ADR-P3-2 to match. |
| B5 | Modem firmware is a Kconfig variant | `sdkconfig.modem` | **Done** | F | **Medium.** Pod modelled as a third variant. |
| B6 | REST API stable | `controller/README.md` | **Done, additions needed** | E | **High.** 17+ endpoints exist. Phase 3 must add: `POST /api/v1/positions`, player tokens, role-filtered WS streams. |
| B7 | WebSocket delivers live events | `controller/atalaia_controller/ws.py` | **Done, additions needed** | E | **High.** WS snapshot + events + score + node + game + system. Phase 3 adds position and role-filtered streams. |
| B8 | Simulator RadioModel + FieldController | Phase 2B | **Done** | -- | Hold-All/Last Stand tested in phase 2. |
| B9 | Flood/dedupe/ACK stable | Phase 2A | **Holds** | F | **Low.** |
| B10 | Join payload format | `protocol/join.md` | **Changed** (E1, E2) | D, E | **Medium.** Version byte + CBOR + HMAC-SHA256 with field join key. Max 448 bytes. Keys 13-31 reserved. NFC MIME `application/vnd.atalaia.join`. Text `atalaia:join:` + base64url. QR pushes nothing to boxes (E3). CA cert cannot fit; use fingerprint. |
| B11 | Capability proxy protocol frozen | ADR-P3-2 | **Updated** | D, F | **High.** Frame format now includes sync+CRC per modem. |
| B12 | GM console exists | `controller/console/src/` | **Done** | D (GM WebView) | Served at `/console/`, pt-PT/en. |
| B13 | Time sync stable | Phase 2C; `field_link.c` | **Done** | E | Slew <=5%, step >=500 ms, hold when ahead, follow highest-term TIME. Android can reuse logic. |

### Risk assessment (updated)

**No critical phase 2 blockers remain.** All phase 3 modes are
single-node (Hold-All and Last Stand moved to phase 2).  The REST API
and WebSocket exist; phase 3 extends them.

**Changes requiring attention:**
- B4: pod framing must use sync+CRC and RADIO_RX must carry epoch.
  ADR-P3-2 updated.
- B10: join payload is CBOR with integer keys, max 448 bytes. CA cert
  does not fit; ADR-P3-9 updated to use fingerprint + Wi-Fi fetch.
- D8: Dart codecs must match schema-exact C payloads (HELLO caps as
  array, STATE counters as map, CMD params as text-keyed map <=127
  bytes JSON, required fields always encoded).

---

## 5. Acceptance criteria

### AC-1: Event schema includes all phase 3 events

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" atalaia-dev ^
  python3 tools/protogen.py --check
```

**Expected:** exit 0. `events.yaml` contains phase 3 event IDs
(25-26, 33-41). Codec tables regenerate cleanly.

### AC-2: Four single-node modes pass all tests

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" atalaia-dev ^
  sh -c "cd /src && python3 -m pytest modes/kill_confirmed/ modes/respawn/ modes/player_checkin/ modes/money_factory/ -v"
```

**Expected:** exit 0. Kill Confirmed scores correctly, Respawn
enforces life limits and cooldowns, Player Check-in counts and
deduplicates, Money Factory collects and deposits.

### AC-3: Hold-All and Last Stand pass (phase 2 mode pack, not phase 3)

**Removed.** Hold-All Domination and Last Stand moved to the phase 2
mode pack (decision R6).  Their tests are owned by that pack.

### AC-4: Declarative templates parse and render on both platforms

**Core (C LVGL renderer):**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" atalaia-dev ^
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**Flutter renderer:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" -w /src/app ^
  cirruslabs/flutter:stable ^
  flutter test test/ui/screen_template_test.dart -v
```

**Expected:** both exit 0. Countdown template interpolates `{left}`
and `{left / params.fuse_s}` correctly on both platforms.

### AC-5: dart:ffi bridge works with stub library

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" -w /src/app ^
  -e ATALAIA_CORE_LIB=/tmp/stub-build/libatalaia_core_stub.so ^
  cirruslabs/flutter:stable ^
  flutter test test/ffi/ test/core/ -v
```

**Expected:** exit 0. All bindings load, all calls return expected
values, game loop isolate sends and receives messages.

### AC-6: Android APK builds with NDK cross-compile of the core

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" -w /src/app ^
  cirruslabs/flutter:stable ^
  flutter build apk --debug
```

**Expected:** exit 0. Produces APK with `libatalaia_core.so` for
arm64-v8a, armeabi-v7a, x86_64.

### AC-7: Chrono energy calculation is accurate

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" -w /src/app ^
  cirruslabs/flutter:stable ^
  flutter test test/chrono/ -v
```

**Expected:** exit 0. 0.20g at 100 m/s = 1.0 J. Spot check correctly
returns PASS, WARN, FAIL. HMAC signing round-trips.

### AC-8: Capability proxy codec agreement (Dart and C)

**Dart:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" -w /src/app ^
  cirruslabs/flutter:stable ^
  flutter test test/pod/codec_test.dart -v
```

**C:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" atalaia-dev ^
  sh -c "cmake -S /src/firmware/esp32/test -B /tmp/fw-test \
         -DCORE_DIR=/src/core -DCMAKE_BUILD_TYPE=Debug && \
         cmake --build /tmp/fw-test && \
         ctest --test-dir /tmp/fw-test -R proxy_codec --output-on-failure"
```

**Expected:** both exit 0. Both Dart and C produce identical bytes
for all frame types against the shared test vectors.

### AC-9: Pod firmware cross-compiles

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/project" -w /project/firmware/esp32 ^
  espressif/idf:v5.3.2 ^
  bash -c "idf.py set-target esp32s3 && \
           idf.py -DCONFIG_ATALAIA_POD_MODE=y build"
```

**Expected:** exit 0. Produces pod firmware binary without Lua or
LVGL; image size ~300 KB.

### AC-10: Server-side position filtering is correct

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" -w /src/app ^
  cirruslabs/flutter:stable ^
  flutter test test/position/visibility_engine_test.dart -v
```

**Expected:** exit 0. Player sees only own position; marshal sees all;
squad leader sees own squad; temporary visibility grants and expires
correctly.

### AC-11: Existing modes and core tests still pass (no regressions)

```sh
MSYS_NO_PATHCONV=1 docker run --rm ^
  -v "%cd%:/src" atalaia-dev ^
  sh -c "BUILD=/tmp/c sh tools/check.sh"
```

**Expected:** exit 0. All existing tests plus new tests pass.

### AC-12: Field test gate -- one game mixes ESP32 and Android props (hardware required)

Execute the Field Test Plan below. A mixed-device Domination game with
at least one ESP32 box and one Android phone (with or without I/O pod)
completes with zero lost events, correct scores, and no crashes.

---

## 6. Field Test Plan

### Objective

Validate the Phase 3 gate: "one game mixes ESP32 and Android props
without issues."

### Equipment

- 2x Heltec WiFi LoRa 32 V4.3: 1 as a field box (node firmware), 1
  as the controller's USB radio modem
- 1x Raspberry Pi 4/5 with a power bank
- 1x USB-A to USB-C cable (Pi to modem board)
- 1x Android phone running the Atalaia app (prop role)
- 1x Android phone running the Atalaia app (player role, optional)
- 1x phone/tablet for GM console
- 1x I/O pod (optional): Heltec V4.3 with pod firmware, arcade
  buttons, LED ring, wired to the Android prop phone via USB-C or
  paired over BLE
- NFC tags: NTAG213/215/216, pre-written with join payloads
- Wi-Fi access point (venue network or controller AP)

### Setup procedure

1. Flash node firmware to the field box ESP32 board.
2. Flash modem firmware to the USB modem board.
3. (Optional) Flash pod firmware to the I/O pod board; connect
   buttons and LED ring per `docs/guides/io-pod-build.md`.
4. Connect the modem to the Pi via USB.
5. Start the Python controller on the Pi.
6. Install the Atalaia APK on the Android prop phone.
7. On the Android prop phone: select "Prop" role, configure battery
   exemption if prompted.
8. (Optional) Pair the I/O pod with the Android phone over BLE or
   USB-OTG.
9. Join the ESP32 field box to the game via NFC card.
10. Join the Android prop to the game via QR code on the GM console
    (over Wi-Fi) or NFC card (if pod has NFC reader).
11. Open the GM console on the GM phone/tablet.
12. Create a Domination game with both devices assigned.

### Test procedure

#### Test 1: Basic mixed-device Domination (10 minutes)

1. Start a 10-minute Domination game with the ESP32 box and the
   Android prop.
2. Press the red button on the ESP32 box. Verify `zone.captured`
   appears in the GM console and on the Android player app.
3. Press the red touch button on the Android prop (or the I/O pod's
   physical button). Verify `zone.captured` appears in the GM
   console.
4. Switch teams by pressing the blue button on both devices.
5. Generate at least 10 captures across both devices.
6. Let the game run to completion.
7. Verify final scores match on: GM console, ESP32 display, Android
   prop display.

#### Test 2: Network partition and recovery (if using I/O pod with LoRa)

1. Move the Android prop with I/O pod out of Wi-Fi range (but within
   LoRa range via the pod).
2. Generate 3 captures on the Android prop.
3. Verify captures propagate via LoRa through the pod to the
   controller.
4. If the pod loses LoRa contact, verify the Android prop continues
   scoring locally.
5. Return to Wi-Fi range. Verify buffered events replay.

#### Test 3: Kill Confirmed mode with NFC (requires NFC on phone)

1. Start a Kill Confirmed game.
2. Write team NFC tags with the correct HMAC signature.
3. Scan a blue tag with the Android phone (red team): verify red +1,
   blue -1.
4. Scan a red tag (same team): verify no scoring change.
5. Verify scores in the GM console.

#### Test 4: Chrono check-in (marshal workflow)

1. Switch one phone to marshal role.
2. Register a replica by entering type and class.
3. Enter 3 velocity readings on the large keypad.
4. Verify energy calculation and pass/fail badge.
5. Re-scan the replica: verify green pass badge appears.

### Metrics to collect

- Total events generated on each device (from device logs).
- Total events received by the controller (from SQLite).
- Delivery rate: received / generated (target: 100%).
- Per-event latency: `received_at - game_time` for each capture.
- Score agreement: final scores on ESP32, Android and GM console all
  match.
- Android battery drain during the 10-minute game (% dropped).
- Android app stability: no crashes, no ANRs.
- Pod BLE/USB link reliability: no disconnects during the game
  (if pod used).
- NFC scan success rate (if Kill Confirmed test run).

### Pass criteria

- **Zero lost events:** every event generated by any device is in the
  controller's event log.
- **Score agreement:** final scores match on all devices and the GM
  console.
- **No crashes:** neither the ESP32 firmware, the Android app, nor the
  controller crashed during any test.
- **Android prop survived 10 minutes:** the foreground service stayed
  alive, the game loop ran continuously, no ANR.
- **Latency under 2 seconds:** 95th percentile event delivery latency
  is under 2 seconds (over Wi-Fi).
- **NFC scanning works** (if tested): at least 90% of NFC scans on
  the Android phone succeed on first tap.

### Gate decision

The Phase 3 gate is met when Test 1 passes with zero lost events and
score agreement. Tests 2-4 are supplementary validation. If the I/O
pod is not assembled, Test 1 runs with the Android prop over Wi-Fi
only (no LoRa from the phone), which is still a valid mixed-device
game.

---

## Phase dependency graph

```
Phase A ──────────────────────────────────────────────> Phase G
  │                                                       ^
  ├─> Phase B ──> Phase D ──> Phase E ────────────────────┤
  │                 ^           ^                          │
  ├─> Phase C ──────┘           │                         │
  │                             │                         │
  ├─> Phase F ──────────────────┼─────────────────────────┘
  │                             │
  │                     [Phase 2C/D/E]
  │                     (external dep)
  └─────────────────────────────┘
```

**Phase A** (no dependencies) can start immediately. It delivers the
event schema, single-node modes, capability proxy protocol, and
screen templates.

**Phase B** (no dependencies beyond pubspec.yaml setup) runs in
parallel with Phase A: chrono data model, energy calculation, security
primitives.

**Phase C** (depends on Phase A for screen template parser) follows
Phase A: dart:ffi bridge, game loop isolate, FFI stub, NDK
cross-compile, first CI jobs.

**Phase D** (depends on Phase B and C) builds the Flutter UI, Kotlin
plugins, and remaining CI jobs.

**Phase E** (depends on Phase D and phase 2C/D) adds field-script
modes, positions, MQTT broker, and controller integration.

**Phase F** (depends on Phase A for protocol definition; needs
hardware) builds the I/O pod firmware. Can proceed in parallel with
Phases D and E.

**Phase G** (depends on all previous phases) ties everything together
on real hardware for the field test.

---

## Summary of new files by directory

```
modes/
    kill_confirmed/
        mode.yaml  node.lua  tests/basic.yaml
    respawn/
        mode.yaml  node.lua  tests/basic.yaml
    player_checkin/
        mode.yaml  node.lua  tests/basic.yaml
    hold_all_domination/
        mode.yaml  node.lua  field.lua  tests/basic.yaml  tests/edge_neutral.yaml
    last_stand/
        mode.yaml  node.lua  field.lua  tests/basic.yaml
    domination/assets/screens/
        standby.yaml  captured.yaml  final_score.yaml
    bomb/assets/screens/
        standby.yaml  countdown.yaml  defused.yaml  exploded.yaml  final_score.yaml

protocol/
    vectors/
        capability_proxy.yaml

core/
    include/atalaia/
        screen_template.h
    src/
        screen_template.c
    tests/
        test_screen_template.c
        stub.c

firmware/esp32/
    main/
        screen_template.c
        pod/
            proxy_task.h    proxy_task.c
            ble_gatt_task.h ble_gatt_task.c
            usb_cdc_task.h  usb_cdc_task.c
            pod_config.h
            pod_shell.c
    test/
        test_screen_template.c
        test_proxy_codec.c
        test_ble_gatt_stub.c

app/
    pubspec.yaml
    APP-STORE-PERMISSION.md
    android/app/
        build.gradle.kts
        src/main/
            AndroidManifest.xml
            kotlin/org/atalaia/app/
                KioskPlugin.kt
                ForegroundServicePlugin.kt
                BlePodPlugin.kt
                UsbPodPlugin.kt
                NfcPlugin.kt
    ios/Runner/
        Info.plist
    lib/
        ffi/
            bindings.dart  callbacks.dart  native_types.dart
        core/
            game_loop_isolate.dart
            node_runner.dart  node_runner_android.dart  node_runner_stub.dart
        prop/
            capability_mapper.dart  screen_manager.dart
            prop_shell.dart  battery_exemption_guide.dart
        pod/
            pod_client.dart  pod_codec.dart
        player/
            player_views.dart  gm_webview.dart
        chrono/
            energy.dart  reading.dart  replica.dart
            limit_template.dart  spot_check.dart  hmac_signer.dart
            chrono_ui.dart  replica_registry_ui.dart
            limit_templates/
                portugal_apda.yaml  uk_ukara.yaml
                germany.yaml  generic_cqb.yaml
        position/
            position_reporter.dart  beacon_scanner.dart
            position_report.dart
        controller/
            api_client.dart  ws_client.dart
            mqtt_broker.dart  visibility_engine.dart
            controller_shell.dart
        security/
            nfc_tag_signer.dart  player_token.dart
        ui/
            screen_template.dart  role_selector.dart  theme.dart
        platform/
            platform_check.dart
    test/
        ffi/
            bindings_test.dart
        core/
            game_loop_isolate_test.dart
        chrono/
            energy_test.dart  spot_check_test.dart
            hmac_signer_test.dart  limit_template_test.dart
        security/
            nfc_tag_signer_test.dart  player_token_test.dart
        ui/
            screen_template_test.dart
        pod/
            codec_test.dart
        prop/
            capability_mapper_test.dart
        position/
            visibility_engine_test.dart
        controller/
            mqtt_broker_test.dart  api_client_test.dart
    integration_test/
        role_switching_test.dart
        game_flow_test.dart

docs/
    phase-3-android-players/
        FIELD_TEST.md
    guides/
        android-prop-setup.md
        io-pod-build.md
    templates/
        privacy-notice.md
```

Total: ~100 new files across modes, protocol, core, firmware, app,
and docs. Modified files: ~15 (events.yaml, CMakeLists files, ci.yml,
Kconfig, shell.c, screen_renderer.c, pubspec.yaml, READMEs).

---

## Maintainer decisions (recommended, for review)

The following decisions were made by the planner where the maintainer's
answer was needed. Each uses the recommended option and is recorded
here for later review.

| # | Question | Recommended decision | Rationale |
|---|----------|---------------------|-----------|
| M-1 | Should the Flutter app use the `yaml` package or a custom parser for screen templates? | Use the `yaml` Dart package | Standard, well-maintained, handles all YAML features we need; the custom parser is only for ESP32 (size constraint) |
| M-2 | Should the chrono limit templates ship inside the APK or be downloaded? | Ship inside the APK in `lib/chrono/limit_templates/` | The prop may be offline; templates are small YAML files (~1 KB each); updates come with app updates |
| M-3 | Should the embedded MQTT broker support QoS 2? | No, QoS 0 and 1 only | Atalaia needs at most QoS 1; QoS 2 adds ~200 LOC of complexity with no benefit |
| M-4 | Should iOS get the dart:ffi bridge as a dormant feature? | No; use conditional imports to exclude it entirely | Smaller iOS binary, no dead code, no maintenance burden for a role iOS cannot use |
| M-5 | What Docker image for Flutter CI? | `cirruslabs/flutter:stable` | Well-maintained, includes Android SDK+NDK, used by many Flutter projects |
| M-6 | Should the pod firmware share `modem_framing.c` or have its own proxy framing? | Share `modem_framing.c` for radio frames (0x05-0x09); add proxy-specific code for IDENT/EVT/CMD/ACK (0x01-0x04) | Maximises code reuse; the radio passthrough is identical to the modem |
| M-7 | Should Phase A or Phase B come first? | Phase A (event schema + modes + protocol + templates) before Phase B (chrono) | Phase A has more downstream dependents (Phases C, D, F all need it); Phase B is self-contained |
| M-8 | What minimum BLE MTU should the pod require? | 247 bytes (BLE 4.2 minimum for DLE) | All capability proxy frames fit; radio packets (max 217 bytes + 3-byte header) fit; no fragmentation needed at the app layer |
