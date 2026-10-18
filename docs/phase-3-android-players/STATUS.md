<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 3 -- Android and Players: Status

**Current phase:** Planning complete; Implementation pending
**Risk level:** Medium
**Last verified:** 2026-10-18

## Completed

- [x] Architecture phase: `ADR.md`
  - [x] ADR-P3-1: dart:ffi bridge architecture (isolate, NativeCallable.listener, Gradle NDK)
  - [x] ADR-P3-2: Capability proxy protocol v1 (frame format, GATT UUIDs, test vectors)
  - [x] ADR-P3-3: I/O pod firmware variant (CONFIG_ATALAIA_POD_MODE, task layout)
  - [x] ADR-P3-4: Declarative screen template format (YAML, 7 widget types, interpolation)
  - [x] ADR-P3-5: Android background survival (foreground service, wake lock, OEM exemption)
  - [x] ADR-P3-6: Player position architecture (GPS/BLE, server-side filter, UAV sweep)
  - [x] ADR-P3-7: Chrono data model (readings, limits, spot-check algorithm, HMAC, GDPR)
  - [x] ADR-P3-8: New event types (15 events, IDs 25-39, 3 new data fields)
  - [x] ADR-P3-9: Security model for the player app (tokens, NFC signing, self-signed CA)
  - [x] ADR-P3-10: iOS exclusions (conditional imports, build flavors)
  - [x] ADR-P3-11: CI strategy for Flutter (FFI stub, 4 CI jobs, emulator integration tests)
  - [x] ADR-P3-12: Embedded MQTT broker for Android controller (minimal Dart broker)
- [x] Research phase: `RESEARCH.md`
  - [x] Flutter app architecture (dart:ffi, roles, Kotlin plugins)
  - [x] Android prop shell (capabilities, background limits, kiosk)
  - [x] I/O pod (hardware, BOM, capability proxy, firmware variant)
  - [x] New game modes (Hold-All, Last Stand, Kill Confirmed, Respawn, Player Check-in)
  - [x] Chrono check-in (registry, flow, limits, GDPR)
  - [x] Player check-in mode
  - [x] Player positions and visibility (GPS, BLE beacons, role filtering, GDPR)
  - [x] Security (tokens, kiosk tamper resistance, NFC signing, HTTPS)
  - [x] iOS constraints
  - [x] CI for Flutter (emulators, FFI stubs, integration tests)
  - [x] Screen template sharing (declarative format for LVGL + Flutter)
  - [x] What needs real phones, pods or boards
  - [x] Assumptions about phases 1 and 2 (10 from P1, 15 from P2)
  - [x] Risk assessment

## Phase 2 dependency check

| Dependency | Status | Blocks |
|-----------|--------|--------|
| Phase 2A: protocol codecs, AES-CCM, flood | Complete | Pod firmware, Android radio passthrough |
| Phase 2B: simulator RadioModel, FieldController | Complete | Multi-node mode testing |
| Phase 2C: `field.*` Lua API, radio HAL, time sync | Pending | Hold-All Domination, Last Stand modes |
| Phase 2D: Python controller, REST API, WebSocket | Pending | Player app, GM app |
| Phase 2E: GM console, join flow, scoreboard | Pending | GM role on Android |
| Phase 2F: Field test, documentation | Pending | Gate: field-tested protocol before Android integration |

**Critical blocker:** Phase 2C (`state.field{}` and `field.*` API).
Without this, Hold-All Domination and Last Stand cannot be implemented.
Kill Confirmed, Respawn, and Player Check-in are single-node modes and
do not depend on phase 2C.

## Next steps

1. ~~Architecture decisions (ADR.md)~~ -- Complete
2. ~~Implementation plan (PLAN.md)~~ -- Complete
3. Implementation (after phase 2 is complete)

## Plan summary

| Phase | Scope | Status |
|-------|-------|--------|
| Research | All 12 research areas, assumptions, risks | Complete |
| Architecture | 12 ADRs: FFI bridge, capability proxy, pod firmware, templates, background survival, positions, chrono, events, security, iOS, CI, MQTT broker | Complete |
| Planning | 7 implementation phases (A-G) with validation criteria, 12 AC, field test plan | Complete |
| Implementation | Code (after phase 2 completes) | Pending |

## How to resume with implementation

Run `/sdlc phase-3-android-players --resume` (or equivalent) once phase 2
is far enough along. The STATE.json records `current_phase: "planning"`,
`phase_status: "complete"`, which tells the orchestrator to proceed to
implementation.

**What can start before phase 2 finishes:**
- Phases A and B (event schema, single-node modes, screen templates, chrono)
  have no phase 2 dependency.
- Phase C (dart:ffi bridge) depends only on Phase A.
- Phase F (I/O pod firmware) depends on Phase A and needs hardware.

**What must wait for phase 2:**
- Phase E (field-script modes, positions, controller integration) needs
  phase 2C (field_ops API) and phase 2D (controller REST/WebSocket).
- Phase G (field test) needs all previous phases and hardware.

## Gate

**One game mixes ESP32 and Android props without issues.**

This requires:
- At least one ESP32 Field Box running a mode
- At least one Android phone running the prop role (with or without I/O pod)
- Both participating in the same game via the field controller
- Captures, scores, and events propagating correctly between both device types
- No crashes, no lost events, no timing issues
