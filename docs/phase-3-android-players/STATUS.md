<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 3 -- Android and Players: Status

**Current phase:** Planning complete; Implementation pending
**Risk level:** Medium
**Last verified:** 2026-10-18 (phase 2 handoff applied)

## Completed

- [x] Research phase: `RESEARCH.md`
- [x] Architecture phase: `ADR.md` (12 ADRs, 24 constraints)
- [x] Planning phase: `PLAN.md` (7 phases A-G, 12 AC, field test plan)
- [x] Phase 2 handoff (2026-10-18): design updated to match phase 2
  A-E implementation (commit `771fd90`)

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
4. Implementation -- ready to start

## How to resume with implementation

Run `/sdlc phase-3-android-players --resume`.  STATE.json records
`current_phase: "planning"`, `phase_status: "complete"`.

**What can start now (no hardware, no phase 2 blockers):**
- Phases A and B (event schema, single-node modes, screen templates, chrono)
- Phase C (dart:ffi bridge) depends only on Phase A
- Phase D (Flutter UI, Kotlin plugins) depends on B and C

**What needs hardware:**
- Phase F (I/O pod firmware) depends on Phase A and needs a Heltec board
- Phase G (field test) needs all previous phases and devices

## Gate

**One game mixes ESP32 and Android props without issues.**

## Phase 3 handoff for phase 4 (interfaces the site server will consume)

Phase 4's site server builds on these phase 3 interfaces:

| Interface | Where | What phase 4 consumes |
|-----------|-------|----------------------|
| Chrono reading record | `app/lib/chrono/reading.dart` | Schema, Ed25519 signature verification, replica registry |
| Limit templates | `app/lib/chrono/limit_templates/*.yaml` | Template format, per-field overrides |
| Player token format | `app/lib/security/player_token.dart` | Token schema for account-based auth upgrade |
| Position reports | `POST /api/v1/positions` | Position data model, visibility rules |
| Replica registry | `app/lib/chrono/replica.dart` | Replica schema for the site-server database |
| NFC tag format | HMAC-SHA256 with game key, truncated 16 bytes | Tag verification for site-server-managed games |
| GM console extensions | `controller/console/src/` | Chrono view, position view, new mode UIs |
| Mode events (IDs 25-26, 33-41) | `protocol/schema/events.yaml` | Event log storage, statistics, replays |
| Field join key distribution | `protocol/join.md`, key 13 (CA fingerprint) | Site server join flow |
| Capability proxy protocol | `protocol/vectors/capability_proxy.yaml` | Pod management in the site-server inventory |
