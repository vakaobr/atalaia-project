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
- Event schema additions (`events.yaml`) for phase 3 events (IDs 25-27,
  33-41; IDs 28-32 owned by the phase 2 mode pack) plus `protogen.py`
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
- Field check-in and per-game replica declaration (added 2026-10-19,
  maintainer request; ADR-P3-13, plan phase E): a printed check-in
  poster from the GM console, check-in from the app with a player token,
  replicas declared per game, a "replicas to chrono" list for marshals
  and the GM console, manual check-in for players without the app, an
  optional federation number that is never verified automatically.
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
- Game scheduling, publication, online registration and third-party
  platforms (phase 4, ADR-P4-11 and ADR-P4-12); linking a hand
  check-in to an app later.

---

## 2. Constraints from ADR.md (all 27 respected)

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
| 12 | Event IDs 25-27 and 33-41 for phase 3 | Phase A adds phase 3 IDs; IDs 28-32 owned by phase 2 mode pack; phase 4 starts at ID 42 |
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
| 25 | The check-in poster carries no secret (ADR-P3-13) | Phase E's poster holds field id and name, controller URLs, CA fingerprint, optional SSID and game id; vectors refuse anything else in keys 1-6; the app pins the CA per field |
| 26 | Check-in personal data minimal and off the event path (ADR-P3-13) | Phase E's tests check that events, MQTT, logs and read-token views carry no names or federation numbers, and the 30-day purge |
| 27 | Controller is the authority for check-ins and the chrono list (ADR-P3-13) | Phase E's list changes only on readings verified with the marshal's key; per-game token key kept across restarts; no internet in any test |

---

## Phase A: Event schema, single-node game modes, capability proxy protocol, screen template format

**Status (2026-10-18): done in software.** What was built, and where it
differs from this section, is in `STATUS.md` ("Plan phase A") and decisions
A1-A13 of `docs/review/decisions-to-review.md`. In short: Money Factory's
mode and the chrono code wait (A1); the C proxy codec lives in the core
(`core/src/proxy.c`) with the frames tested in `firmware/esp32/test` (A9);
templates come from the firmware image, not LittleFS (A11); no
`bomb/assets/screens/final_score.yaml` (A12); mode tests run with
`python -m atalaia_sim test`, not pytest (A13).

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
| `protocol/schema/events.yaml` | Add 13 events (IDs 25-27, 33-41): `kill.confirmed`, `kill.denied`, `team.eliminated`, `money.collected`, `money.deposited`, `chrono.checkin`, `chrono.spotcheck`, `visibility.granted`, `visibility.expired`, `node.tamper`, `pod.connected`, `pod.disconnected` (IDs 28-32 already exist from the phase 2 mode pack); add 2 data fields (keys 29-30): `see_team`, `tolerance_pct` (`duration_s` 28 and `holder` 31 exist; Money Factory reuses `amount`, key 6) |
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

**Status (2026-10-19): done in software.** What was built, and where it
differs from this section, is in `STATUS.md` ("Plan phase B") and decisions
B1-B13 of `docs/review/decisions-to-review.md`. In short: chrono records are
signed with Ed25519 per marshal as ADR-P3-7 (P3-1) says, so
`hmac_signer.dart` is `record_signer.dart` and the package is `cryptography`,
not `pointycastle` (B1); the canonical form, the record fields and the player
token format are specified in `protocol/chrono-record.md` and
`protocol/player-token.md` with shared vectors that the controller's Python
checks too (B3-B9); the player token key is the controller's own, not the
game key (B8); the templates are `portugal.yaml`, `uk.yaml`, `germany.yaml`
and `generic_cqb.yaml`, all marked unverified (B10); the image is
`ghcr.io/cirruslabs/flutter:3.44.0` pinned by digest, run by
`python tools/docker_app.py` (B2).

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

**Status (2026-10-19): done in software.** What was built, and where it
differs from this section, is in `STATUS.md` ("Plan phase C") and decisions
PC1-PC11 of `docs/review/decisions-to-review.md`. In short: callbacks are
`NativeCallable.isolateLocal`, not `.listener`, because the core's pointers
only live during its call (PC1); the Dart tests load the real core as well as
the stub, built in `atalaia-dev` or on the CI runner and passed in with
`ATALAIA_CORE_LIB` and `ATALAIA_CORE_STUB_LIB` (PC2); every mode's YAML tests
run through the bridge, directly and in game loop isolates (PC3); struct
layouts are checked against the stub's report from the real headers (PC4);
there is no `core/tests/CMakeLists.txt` (the stub is a target in
`core/CMakeLists.txt`) and the NDK presets are `core/CMakePresets.json`;
`flutter-build-android` moved up from plan phase D (PC11). A core bug found
by these tests was fixed (`field.common_owner`).

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

**Status (2026-10-19): done in software, iOS not built.** What was built, and
where it differs from this section, is in `STATUS.md` ("Plan phase D") and
decisions PD1-PD24 of `docs/review/decisions-to-review.md`. In short: the
template renderer ports the core's YAML-subset parser instead of using the
`yaml` package, checked against the core (PD2); the QR scanner is CameraX and
ZXing, not `mobile_scanner` (ML Kit needs Google Play services, PD5); no
`geolocator`, `flutter_blue_plus`, `usb_serial`, `nfc_manager` or
`qr_flutter`: the app's own Kotlin plugins and the `qr` package (PD19);
positions and the controller role stay in plan phase E (PD1); iOS cannot be
built without a Mac, so there is no `ios/` folder (PD10); the emulator runs
the AOSP image, without Google APIs (PD17). A core bug found by the
renderer's tests was fixed (`{x|clock}` beyond 64-bit integers, PD3).

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

## Phase E: Player positions, embedded MQTT, controller integration, field check-in

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

**Added 2026-10-19 (maintainer request):** field check-in by a printed
poster, per-game replica declaration and the marshals' "replicas to
chrono" list (ADR-P3-13); its files, tests and acceptance are in the
subsection at the end of this plan phase.

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

### Field check-in and per-game replica declaration (added 2026-10-19, maintainer request)

**Goal:** a player arrives at the field, scans the check-in poster with
the app, is checked in at the controller and gets a player token,
then picks the replicas they will use in that game.  The controller
keeps a per-game "replicas to chrono" list; the marshal's view and the
GM console show which declared replicas are not chronographed yet,
and a signed chrono check-in reading marks each one passed or refused.
The GM console shows the check-ins and the chrono state, and prints
the poster.  Design: ADR-P3-13; open questions F1-F12 in
`docs/review/decisions-to-review.md`.  Everything here works with no
internet and no site server; phase 4 fills the same list from
registrations (ADR-P4-11).

**Dependencies:** this plan phase's player token issuance with the
controller's own per-game token key (decision B8), the CA certificate
endpoint `GET /api/v1/controller/ca` with the fingerprint (P3-8), and
chrono readings sent to the controller.  Plan phase D's marshal
screens, replica registry and tag writer (done).

**Files to create:**

| File | Licence | Purpose |
|------|---------|---------|
| `protocol/checkin.md` | GPL-3.0-or-later | The check-in poster text `atalaia:checkin:` (version, CBOR keys 1-6), the TOFU rule, the check-in endpoints' request and response bodies, the declaration's fields and states |
| `protocol/vectors/checkin.json` | GPL-3.0-or-later | Valid posters (decode, re-encode byte for byte, text form), invalid ones with the reason they must fail, declarations valid and invalid |
| `controller/atalaia_controller/checkin.py` | AGPL-3.0-or-later | Check-in rules: field identities (id, SHA-256 of the secret), check-ins and their states, settings, declarations, the "replicas to chrono" list and its matching rules (by `replica_id` and `player_id`, valid for the day or the game), retention purge |
| `controller/atalaia_controller/checkin_poster.py` | AGPL-3.0-or-later | Poster text codec (Python side of `protocol/checkin.md`) |
| `controller/console/src/components/checkin-panel.js` | AGPL-3.0-or-later | GM console *Check-in* tab: open or close per game, settings, live check-in list (status, team and squad, federation number with "card seen", declared replicas and chrono state), "replicas to chrono" list, manual check-in, removal, CSV export |
| `controller/console/src/poster.html`, `poster.js` | AGPL-3.0-or-later | The printable A4 poster (QR code with the existing `qrcode.module.js`, field name, steps in pt and en, CA fingerprint short form, optional Wi-Fi QR code from a password typed in and never stored) |
| `controller/templates/checkin-notice-pt.md`, `checkin-notice-en.md` | CC-BY-SA-4.0 | Short default privacy notice for check-in (field operator as data controller, what is kept, 30-day retention, rights); for the P4-6 legal review |
| `app/lib/protocol/checkin_poster.dart` | GPL-3.0-or-later | Poster text codec (Dart side), against `checkin.json` |
| `app/lib/checkin/field_trust.dart` | GPL-3.0-or-later | Per-field CA pinning: fetch `GET /api/v1/controller/ca`, compare SHA-256, keep it per `field_id`, refuse a changed fingerprint; an HTTP client that trusts that CA only for the poster's URLs |
| `app/lib/checkin/field_identity.dart` | GPL-3.0-or-later | Per-field `player_id` (`p-` + 12 base32) and 32-byte secret in the app's private storage |
| `app/lib/checkin/checkin_client.dart` | GPL-3.0-or-later | The check-in endpoints: info, check in, token refresh, own check-in, declaration, leave |
| `app/lib/checkin/checkin_screen.dart` | GPL-3.0-or-later | Scan, connect (or "join Wi-Fi X"), notice, form (display name, federation number when asked, team preference), result |
| `app/lib/checkin/my_replicas.dart`, `declare_replicas_screen.dart` | GPL-3.0-or-later | The player's own replica list on the phone, and the per-game declaration with each replica's chrono state |
| `app/lib/marshal/chrono_queue.dart` | GPL-3.0-or-later | The marshal's "replicas to chrono" view: by player, pending first, counts, scan a sticker to jump to its declaration, link an unregistered replica, manual check-in |
| `controller/tests/test_checkin.py` | AGPL-3.0-or-later | Check-in endpoints and rules (below) |
| `controller/tests/test_checkin_poster.py` | AGPL-3.0-or-later | Poster codec against `checkin.json` |
| `controller/tests/test_chrono_list.py` | AGPL-3.0-or-later | Readings to list states |
| `app/test/protocol/checkin_poster_test.dart`, `app/test/checkin/*_test.dart`, `app/test/marshal/chrono_queue_test.dart` | GPL-3.0-or-later | Dart codec, trust, identity, client (mock HTTP), screens (widget tests, both languages), marshal queue |

**Files to modify:**

| File | Change |
|------|--------|
| `controller/atalaia_controller/store.py` | Next schema version: `field_players`, `checkins`, `replica_declarations`, `replicas`, `chrono_readings`, `marshal_keys`, per-game token keys (mode 0600 file, as `persist_game_key`) |
| `controller/atalaia_controller/api.py`, `ws.py` | The ADR-P3-13 endpoints; `checkin` and `chrono_list` stream messages for GM and marshal connections only; rate limit and per-game cap on the unauthenticated endpoints; the start warning when declarations are pending |
| `controller/atalaia_controller/engine.py` | Emit `player.checkin` (15) as the controller's node when a check-in becomes checked in |
| `controller/atalaia_controller/config.py`, `controller/controller.example.toml` | `[checkin]`: `confirm`, `federation`, `federation_label`, `max_replicas`, `max_players`, `chrono_valid_for`, `rate_per_minute`, `urls`, `wifi_ssid`, `field_id`, `field_name`, notice files |
| `controller/console/src/app.js`, `i18n/pt.json`, `i18n/en.json` | The *Check-in* tab and its texts |
| `app/lib/marshal/marshal_home.dart`, `marshal_records.dart` | Entry to the queue; readings sent to the controller with the game's `game_id`; marshal key registration when the role is given |
| `app/lib/player/player_screens.dart` | "Check in at the field" entry; the player's feed uses the token once checked in |
| `app/lib/l10n/strings_pt.dart`, `strings_en.dart` | New strings (European Portuguese, "tu", inclusive, PD20) |
| `app/lib/controller/controller_shell.dart` (this plan phase) | The Android controller role serves the same check-in endpoints, tested with the same contract cases |
| `controller/README.md`, `app/README.md`, `controller/console/README.md` | Check-in, the poster, the marshal queue (R4) |

**Tests to create:**

| File | What it tests |
|------|---------------|
| `controller/tests/test_checkin_poster.py`, `app/test/protocol/checkin_poster_test.dart` | Both codecs against `protocol/vectors/checkin.json`: every valid poster decodes and re-encodes byte for byte; every invalid one fails with its reason (missing key, repeated key, key 32, trailing bytes, 33-byte fingerprint, non-canonical base64url, over 192 bytes); keys 7-31 skipped |
| `controller/tests/test_checkin.py` | Info without a token lists only open games and no names; check-in issues a token that `player_token.py` accepts with role `player`; a known id with the wrong secret is 409; the same id and secret check in again; closed check-in is 403; the rate limit and the per-game cap; `staff` mode leaves it pending until confirmed; `player.checkin` emitted once, with the player id and no name; a GM role change issues a new token and the old token is refused for the new role; a removed player's token is refused; leaving erases the personal fields; the read token sees no names on REST or the stream; tokens survive a controller restart; retention purge after 30 days; federation `required` refuses an empty number, and nothing ever checks its content |
| `controller/tests/test_chrono_list.py` | A declared replica is pending; a signed check-in series that passes makes it passed, one that fails makes it refused, a retest pass after a fail makes it passed with both records kept; an unsigned record, one signed by an unregistered key and one with a changed field are refused and change nothing; a replay of the same `reading_id` changes nothing; `day` validity passes a second game's declaration at once, `game` does not; a declaration without `replica_id` is linked when the marshal registers the replica; a player cannot withdraw a replica once chronographed |
| `app/test/checkin/*_test.dart` | Trust: a matching fingerprint is kept, a changed one is refused with both short forms; the client against a mock controller; the identity is made once per field and reused; the declaration screen limits and states; screens in both languages (widget tests) |
| `app/test/marshal/chrono_queue_test.dart` | Pending first, counts, sticker scan jumps to the declaration, linking a new replica, manual check-in |
| Console browser test (`controller/console/tests/test_browser.py`) | The *Check-in* tab with a live check-in arriving on the stream; the poster page renders a QR code that decodes to the controller's poster text |

**Validation:**

```sh
MSYS_NO_PATHCONV=1 docker run --rm -v "%cd%:/src" atalaia-dev sh tools/check.sh
python tools/docker_app.py check
python tools/docker_console.py
```

**Acceptance (AC-13 in section 5):** a player's app with no internet
scans a printed poster, checks in, declares two replicas; the GM
console and the marshal's view show both as not chronographed; a
signed passing series for one and a failing series for the other mark
them passed and refused; the read token never sees the player's name;
the controller restarts and nothing is lost.

### PE24 slices: the Android controller role (added 2026-10-22)

Plan phase E built the Android controller role's broker and visibility
engine and left the rest (decision PE24): `field.lua` on the phone, the
controller's REST and WebSocket API, check-in and token issuing served
by the app, with the same contract tests as the Pi controller. The Pi
controller has grown a great deal since (about 120 endpoints, the
radio's re-invites, adoption, pairing, firmware updates, the site sync,
ATAK, the remote GM), so the role is built in slices, each one useful
and tested on its own. Decisions PE24-1 to PE24-9.

**What the field test needs.** Plan phase G's gate ("one game mixes
ESP32 and Android props") runs with the Pi controller (section 6), so
no slice is on the gate's path (PE24-3). The slices aim at a phone that
runs a small game with no Pi: boxes through an I/O pod on the phone,
Android props on the phone's Wi-Fi, players checking in. Whether a
phone may also be a Pi's standby is the maintainer's choice (PE24-2);
until slice S7 a phone and a Pi never run the same game.

**How the contract is tested (PE24-4).** The shared cases are JSON in
`protocol/vectors/controller_api.json`: requests with a token and a
body, the status and a pattern the answer must match (keys given must
match, `$absent`, `$any`, `$contains` for lists), values saved from an
answer, decrypted packets from a box (`rx`: HELLO, STATE, EVENT) and
clock steps (`advance_ms`, then one tick). The Pi controller is the
reference: `controller/tests/test_api_contract.py` runs every case
in-process (FastAPI's TestClient, a recording modem, a fake clock), and
`app/test/controller/api_contract_test.dart` runs the same cases over
HTTP on the loopback address against the Dart engine on the real core.
A case is added on the Pi's side first; a case that fails on one side is
a difference to fix, in the code or (with a dated note) in the case.
Error texts (`detail`) are not part of the contract; status codes are.
Later slices add step kinds: `ws` (stream messages, S2), `restart` (a
new controller on the same store, S3), `tx` (what went on the radio,
S4).

| Slice | What | Contract and tests | State |
| --- | --- | --- | --- |
| S1 | The game engine and the REST API: `app/lib/controller/field_controller.dart` (the simulator's FieldController in Dart: game clock, TIME beacons, commands, HELLO, STATE, events with replays dropped, ACKs, scores merged by maximum, node health; no election), `controller_engine.dart` (create, start with the start check, pause, resume, end, the time limit, `field.lua` on the core with the field operations and its points per run, `game.win`, GM adjustments, node commands, the read token's view without gm_only data), `controller_store.dart` (in memory), `controller_api.dart` (healthz, whoami, nodes, modes, games, start-check, score, log, node commands, controller state; GM and read tokens; loopback by default); the core's event decoder in the bindings (PE24-5) | `controller_api.json` (8 cases) on both sides; Dart unit tests for the radio side and the engine | **Done 2026-10-22** (in software) |
| S2 | The live stream and MQTT: `WS /api/v1/stream` for the GM and read tokens (the hello snapshot, game, event, score, node and system messages, gm_only data for staff only) and the Pi bridge's topics on the embedded broker (`field/v1/{game}/...`, score and nodes retained) | `ws` steps in the shared cases; the broker's topics against `controller/atalaia_controller/mqtt.py`'s | To do |
| S3 | Keeping games: a file store in the app's private storage (games, events, scores, nodes, settings, the field script's points per run), the live game restored after a restart with its `field.lua` run; the game key kept only with `persist_game_key` (ADR-P2-4), else the game must be ended (`key_lost`) | `restart` steps; the Pi's restart tests as cases | To do |
| S4 | The radio and the props: the I/O pod as the controller's radio (CONFIGURE with the game key, RX to the engine, TIME, CMD and ACK out, the transmit epoch stored per key), Android props on the phone's Wi-Fi (`WS /api/v1/prop`, protocol/prop-link.md, the server side), join payloads (`POST /api/v1/join`, `/nodes/{id}/join`, the field join key), the field's channel | `tx` steps; the join and prop-link vectors; the host pod and host box over a UDP air (as `test_pod_e2e.py`) | To do |
| S5 | Check-in and players: the ADR-P3-13 endpoints, player tokens with a per-game token key, the role-filtered stream, positions through `visibility_engine.dart`, chrono readings and the replicas-to-chrono list, marshal keys | `test_checkin.py` and `test_chrono_list.py` cases moved into shared cases | To do |
| S6 | The shell and its screens: the controller role on the home screen (Android only), the controller's isolate (never the UI isolate, constraint 1) with the foreground service and wake lock, the GM console in the app's web view on the phone's own API (PE24-8), HTTPS with a field CA made on the phone, opening the API and the broker to the field's Wi-Fi (PE24-7) | Widget tests; an emulator test of a game run from the phone | To do |
| S7 | After the field test, as fields ask: failover (CLAIM, a phone as a Pi's standby or the other way round, PE24-2), presets, mode uploads and scenarios, role packages in a game, team branding, the channel scan, re-invites, adoption and pairing, firmware updates, the site sync, ATAK, the remote GM | The Pi's tests for each, as shared cases where they are API | Later |

S1 to S6 make the phone a field controller for a small game; each
slice ends with `python3 tools/docker_app.py` (check, ndk, apk) and the
Pi's controller tests green, and the shared cases passing on both sides.

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

### As built (2026-10-19)

Done in software; decisions PF1-PF15 in `docs/review/decisions-to-review.md`,
status in `STATUS.md`. What differs from the lists above:

- **Files.** The proxy, capabilities and GATT logic are plain C apart from
  ESP-IDF, as the modem's (`main/pod/pod.c`, `pod_caps.c`, `pod_ble.c`,
  `pod_json.c`), with thin ESP-IDF files (`pod_task.c` for the task, the
  USB-Serial-JTAG link, the audio queue and the enclosure switch;
  `pod_ble_nimble.c`; `pod_main.c` with its own `app_main`, so `shell.c` is
  unchanged). `pod_config.h` holds Kconfig settings, not NVS ones: the
  pod's configuration over CMD (ADR-P3-3) is not built (PF15).
- **Kconfig.** The modem's bool became the three-way variant choice of
  ADR-P3-3; `sdkconfig.pod` selects the pod and NimBLE.
- **Build.** `python tools/docker_fw.py pod` (the plan's
  `-DCONFIG_ATALAIA_POD_MODE=y` is not how ESP-IDF takes Kconfig values);
  CI `esp32-pod-build`. Image about 650 KB (the plan guessed ~300 KB before
  NimBLE).
- **Protocol.** RADIO_NOISE `0x0B` and MEASURE through the pod (PF2); the
  pod's links, seqs and key rules (PF5), its Bluetooth security (PF4) and
  its capabilities (PF6-PF8) are dated refinements in
  `protocol/capability-proxy.md`.
- **The phone's side.** Beyond the plan's list: the phone's radio link
  through the pod and its choice between Wi-Fi and LoRa (PF9), which plan
  phase D left to this phase (PD12) and plan phase E's handoff named.
- **Tests.** `test_proxy_codec.c` existed (plan phase A) and checks the new
  vectors; new: `test_pod.c` (in `firmware_test`), `test_ble_gatt_stub.c`
  (`ctest -R ble_gatt_stub`), the host pod (`test/pod_host`) with Dart and
  controller tests against it (PF10).

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

**The I/O pod on hardware (added after plan phase F, 2026-10-19).** Plan
phase F built and tested the pod's firmware and the phone's side against
the pod's own code on a computer only. Before the field test, on a pod
board with a phone (the steps are `firmware/esp32/docs/BRING_UP.md`, "The
I/O pod"):

1. Read the board revision (KCT8103L = V4.3, GC1109 = V4.2) and build the
   pod for it; fit the LoRa antenna; boot it and check the UART0 log.
2. USB-OTG: the phone finds and opens the pod; opening the port does not
   reset it (DTR and RTS set together, PF3).
3. Bluetooth LE: the pod is found as `atalaia-pod-XXXX`, Android asks to
   pair once, IDENT arrives within 30 s, the bond is kept, one phone at a
   time (PF4); the MTU is 247.
4. Inputs and outputs on a prop game: buttons by number, keypad keys, a
   player tag on the pod's reader, the ring's team colour, the clips as
   tones; press-to-reaction under 100 ms on USB and 200 ms on Bluetooth.
5. The enclosure switch: `node.tamper` (`pod_opened`) in the GM console
   when the lid opens during a game; nothing without a switch (PF8).
6. The pod's conducted TX power (BRING_UP step 10) before anything is sent
   in a game.
7. The phone on the field's radio through the pod with the Wi-Fi off: the
   controller lists the node (HELLO, transports LoRa), the game's start
   reaches it, its captures are logged and acknowledged; Wi-Fi on and off
   again: it moves between the links with no capture lost or doubled
   (PF9).
8. The phone unplugged or out of Bluetooth range: the pod forgets the game
   key (`radio cleared`); linking again works with the next epoch (PF5).
9. Two hours on battery and Bluetooth: no watchdog reset, no lost link.

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

### AC-13: Field check-in and the "replicas to chrono" list (added 2026-10-19)

```sh
MSYS_NO_PATHCONV=1 docker run --rm -v "%cd%:/src" atalaia-dev sh tools/check.sh
python tools/docker_app.py check
python tools/docker_console.py
```

**Expected:** exit 0, with `test_checkin_poster.py`, `test_checkin.py`,
`test_chrono_list.py`, the Dart check-in and queue tests and the
console's *Check-in* browser test passing.  Together they show: a poster
decoded by both codecs from the shared vectors; a check-in with no
internet that returns a valid player token with role `player`; two
declared replicas listed as not chronographed for the GM and the
marshal; a signed passing series and a signed failing series marking
them passed and refused, and an unsigned one changing nothing; no name
or federation number in events, MQTT or the read token's views; nothing
lost across a controller restart.

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
6. (Added after plan phase F.) The GM console shows each capture once
   (the controller drops the copy that arrives over both links), the
   phone's screen shows which link it is on ("over the pod's radio" while
   out of Wi-Fi), and the pod's radio stays quiet once the Wi-Fi link is
   back (decision PF9).
7. Join a second phone with a pod at a spot with no Wi-Fi at all, from a
   join payload without the controller's addresses: it plays on the radio
   alone.

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

#### Test 5: Field check-in and replica declaration (added 2026-10-19)

1. Print the check-in poster from the GM console and tape it up.
2. Three players scan it with their phones on the field Wi-Fi (no
   internet), check in and declare one or two replicas each; a fourth
   player without the app is checked in by a marshal.
3. Verify the GM console and the marshal's view list every declared
   replica as not chronographed, and the poster's fingerprint matches
   the console's.
4. Chronograph the replicas; fail one on purpose, then retest it.
5. Verify the list shows passed, refused, then passed after the retest,
   and that a spectator scoreboard shows no names.

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

Field check-in (2026-10-19, plan phase E) adds `protocol/checkin.md`
and its vectors, `controller/atalaia_controller/checkin.py` and
`checkin_poster.py`, the console's *Check-in* tab and poster page, and
`app/lib/checkin/` with the marshal's `chrono_queue.dart`, plus their
tests (listed in plan phase E).

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
