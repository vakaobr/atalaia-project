<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 2 -- Field Network: Status

**Current phase:** Implementation (phases A + B complete, stopped before C)
**Risk level:** High
**Last verified:** 2026-10-17

## Completed

- [x] Research phase: `RESEARCH.md`
- [x] Architecture decisions: `ADR.md` (15 ADRs, 29 planning constraints)
- [x] Implementation plan: `PLAN.md` (6 phases, 10 acceptance criteria, field test plan)
- [x] RFC-0001 accepted (2026-10-17)
- [x] Phase 1 assumption check: 11 of 12 hold; A5 uses contingency
- [x] Phase A: Protocol codecs (packet, flood, ACK, duty-cycle, msg_codec, crypto_mbedtls)
- [x] Phase A: protogen extended (payload schemas, packet vector generation)
- [x] Phase A: Shared test vectors (C and Python verify the same JSON files)
- [x] Phase A: RFC 3610 known-answer AES-CCM test (C mbedtls + Python cryptography)
- [x] Phase A: Mutation tests for all decoders (packet header, 7 payload types)
- [x] Phase B: RadioModel, FieldController, Python packet codec, sim.py integration
- [x] Phase B: 9 simulator test files (all pass, 0 skipped in CI)
- [x] No firmware regression (ESP-IDF build passes, 87% slot usage, 13% free)
- [x] No silent skips (ATALAIA_REQUIRE_ALL=1 in check.sh and CI)

## Verification (2026-10-17)

```
docker build -t atalaia-dev tools/dev        exit 0
sh tools/check.sh                            exit 0
  protogen --check                           OK (all 6 generated files up to date)
  build_site.py --check                      OK
  format --check                             OK
  cmake build (16 core + crypto_mbedtls)     OK (0 warnings, -Werror)
  ctest                                      1/1 passed
  simulator unittest                         108 tests, 0 skipped
  mode tests                                 12/12 passed
ESP-IDF build (espressif/idf:v5.3.2)         exit 0 (binary 1,366,128 bytes)
firmware stub tests                          2/2 passed
```

## Shared test vectors

Both the C codec (via generated `core/tests/packet_vectors.h`) and the Python
codec (via `protocol/vectors/*.json` loaded at test time) verify the same
vectors for: header (4 valid + 2 invalid), HELLO (2+2), ACK (2+1), STATE
(2+1), CMD (2+1), TIME (2+1), CONFIG (2+1), CLAIM (2+1), and AES-CCM
(5 vectors with real ciphertext: basic, seq_wrap, epoch_increment,
hop_limit_one, empty_payload).

Published known-answer: RFC 3610 section 8, Packet Vector 1 (AES-128-CCM,
13-byte nonce, 8-byte tag). Tested in C (`test_crypto_mbedtls.c`) and Python
(`test_packet.py::RFC3610Tests`).

## Crypto backend

`atalaia_crypto_ops_t` function-pointer interface:
- **Test stub** (`atalaia_crypto_test_stub`): XOR + FNV-1a. Tests framing only.
- **mbedtls** (`atalaia_crypto_mbedtls`): Real AES-128-CCM. Built when
  `libmbedcrypto` found by CMake. Known-answer tested against RFC 3610.
- **ESP32**: firmware provides mbedtls via IDF component.
- **Python**: `cryptography` library (required in CI, optional locally).

## Next: Phase C

Core Lua API (`state.field{}`, `field.*`), radio HAL (`hal_radio_ops_t` +
SX1262 driver + stub), FreeRTOS radio task, flash event log, time sync.
Core version bump to 0.2.0.

## Plan summary

| Phase | Scope | Status |
|-------|-------|--------|
| A | Protocol codecs, RFC-0001, protogen, test vectors | Complete |
| B | Simulator: RadioModel, FieldController, multi-node tests | Complete |
| C | Core API (field_ops), radio HAL, ESP32 radio task, time sync, event log | Pending |
| D | Python controller, USB modem framing, REST, MQTT, SQLite, failover | Pending |
| E | GM console (Preact+HTM PWA), join flow (NFC+QR), scoreboard | Pending |
| F | Hardware integration, calibration, field test, documentation | Pending |

## Acceptance criteria

| # | Criterion | Status |
|---|-----------|--------|
| AC-1 | Protocol codec round-trips all 8 message types | Met (C + Python, shared vectors) |
| AC-2 | AES-CCM encrypt/decrypt passes known vectors | Met (RFC 3610 + 5 packet vectors) |
| AC-3 | Simulator multi-node game correct scores | Met |
| AC-4 | Duty-cycle compliance in sim | Met |
| AC-5 | Controller REST API serves all 17 endpoints | Phase D |
| AC-6 | GM console serves and renders | Phase E |
| AC-7 | ESP32 firmware cross-compiles with radio | Phase C |
| AC-8 | Partition recovery zero lost captures in sim | Met |
| AC-9 | Failover election in simulator | Met |
| AC-10 | Field test 5 boxes zero lost captures | Phase F |
