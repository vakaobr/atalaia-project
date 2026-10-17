<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Review: phase-1-single-box

**When:** 2026-10-17
**Iteration:** 1/3

---

## Verdict

**Status:** NEEDS_FIX (fix iteration 1 applied; re-review pending)

---

## Expert Verdicts

| Expert | Status | Blocking Issues |
|--------|--------|----------------|
| Security | APPROVED | 0 |
| QA | NEEDS_FIX | 1 |
| SRE | NEEDS_FIX | 4 |

---

## Consolidated Blocking Issues

**From QA:**

- ~~Score freeze not verified after `game.end` in `test_integration.c`
  (AC-2 gap)~~ FIXED: added score snapshot before/after game end with
  equality assertion.

**From SRE:**

- ~~B-1: Admin PIN logged in plaintext (`wifi_setup.c` line 48)~~
  FIXED: replaced `ESP_LOGI(TAG, "config POST: %s", buf)` with
  `ESP_LOGI(TAG, "config POST received (%d bytes)", ret)`.

- ~~B-2: `state_persist_load` is never called at boot~~
  ACKNOWLEDGED: the resume-from-persisted-state code path is not wired
  in `shell.c` because the game loop is still a stub (empty
  `task_game`). The persist/load infrastructure is tested and working
  (4 tests pass). Full wiring requires the complete game loop, which
  depends on hardware bring-up. Documented in BRING_UP.md Step 12.

- ~~B-3: `node_runner.c` hardcodes `mem_limit = 256 KB`~~
  FIXED: `node_runner_init` now takes a `mem_limit` parameter.
  `shell.c` passes the tier-appropriate value.

- ~~B-4: `esp_restart()` commented out in Wi-Fi setup~~
  FIXED: added 500 ms `esp_timer` that calls `esp_restart()` after
  the HTTP response flushes.
