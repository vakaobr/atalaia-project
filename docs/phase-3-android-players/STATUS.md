<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 3 -- Android and Players: Status

**Current phase:** Implementation: plan phases A, B and C done in software; plan phases D-G pending
**Risk level:** Medium
**Last verified:** 2026-10-19 (plan phase C)

## Completed

- [x] Research phase: `RESEARCH.md`
- [x] Architecture phase: `ADR.md` (12 ADRs, 24 constraints)
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
4. Implementation -- plan phases A, B and C done; next: plan phase D
   (Flutter UI, Kotlin plugins, Android prop shell, template renderer,
   iOS build, emulator job), on top of `lib/core/node_runner.dart` and
   `GameLoopIsolate`

## How to resume with implementation

Run `/sdlc phase-3-android-players --resume`.  STATE.json records
`current_phase: "implementation"`, `phase_status: "in_progress"` (plan phases A, B and C done).

**What can start now (no hardware, no phase 2 blockers):**
- Phase D (Flutter UI, Kotlin plugins) depends on B and C (both done)

**What needs hardware:**
- Phase F (I/O pod firmware) depends on Phase A and needs a Heltec board
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
| Position reports | `POST /api/v1/positions` | Position data model, visibility rules |
| Replica registry | `app/lib/chrono/replica.dart` | Replica schema for the site-server database |
| NFC tag format | `protocol/nfc-tag.md` (HMAC-SHA256 with game key, truncated 16 bytes; vectors `protocol/vectors/tag.json`) | Tag verification for site-server-managed games |
| GM console extensions | `controller/console/src/` | Chrono view, position view, new mode UIs |
| Mode events (IDs 25-27, 33-41) | `protocol/schema/events.yaml` | Event log storage, statistics, replays |
| Field join key distribution | `protocol/join.md`, key 13 (CA fingerprint) | Site server join flow |
| Capability proxy protocol | `protocol/capability-proxy.md`, `protocol/vectors/capability_proxy.yaml` | Pod management in the site-server inventory |
