<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# QA Review: phase-1-single-box

**When:** 2026-10-17

---

## Verdict

**Status:** NEEDS_FIX

---

## Test Run

```
$ docker run --rm -v /src atalaia-dev sh -c \
    "cmake -S /src/firmware/esp32/test -B /tmp/fw-test \
     -DCORE_DIR=/src/core -DCMAKE_BUILD_TYPE=Debug && \
     cmake --build /tmp/fw-test && \
     ctest --test-dir /tmp/fw-test --output-on-failure"

Test project /tmp/fw-test
    Start 1: firmware
1/1 Test #1: firmware .........................   Passed    0.04 sec

100% tests passed, 0 tests failed out of 1

Total Test time (real) =   0.04 sec
```

**Result:** 1 passing, 0 failing, 0 skipped. All 32 assertions green.

---

## Acceptance Criteria Coverage

| Criterion | Tested? | Test location |
|-----------|---------|---------------|
| AC-1: ESP-IDF cross-compile produces `atalaia_esp32.bin` | Indirect | CI `esp32-build` job (not runnable in review; IMPLEMENTATION.md reports pass) |
| AC-2: Game timer fires `game.end` at the correct time | ✓ | `test_game_timer.c` — `test_timer_fires_at_expiry` |
| AC-2: Timer fires only once, unlimited mode never expires | ✓ | `test_game_timer.c` — `test_timer_fires_only_once`, `test_unlimited_timer_never_expires` |
| AC-2: Command dispatch routes screen and audio commands | ✓ | `test_command_dispatch.c` — `test_screen_command`, `test_audio_play_command`, `test_audio_stop_command` |
| AC-2: Command dispatch routes LED fill | ✓ | `test_command_dispatch.c` — `test_led_fill_command` |
| AC-2: Preset store save / list / load / delete round-trip | ✓ | `test_preset_store.c` — all four tests |
| AC-2: State persistence survives a simulated reboot | ✓ | `test_state_persist.c` — `test_resume_after_reboot` |
| AC-2: Corrupted state file is rejected | ✓ | `test_state_persist.c` — `test_invalid_magic` |
| AC-2: Node runner loads a mode and processes events end-to-end | ✓ | `test_node_runner.c` — `test_event_processing` |
| AC-2: Preset UI accepts correct PIN | ✓ | `test_preset_ui.c` — `test_correct_pin_accepted`, `test_full_flow` |
| AC-2: Preset UI rejects wrong PIN and clears buffer | ✓ | `test_preset_ui.c` — `test_wrong_pin_rejected` |
| AC-2: Config store reads / writes NVS values | ✓ | `test_config_store.c` — `test_string_values`, `test_uint_values` |
| AC-2: Config store `configured` flag round-trips | ✓ | `test_config_store.c` — `test_configured_flag` |
| AC-2: Integration — 2-minute simulated game, zone capture, scoring | ✓ | `test_integration.c` — 120-second domination scenario |
| AC-2: Integration — timer expiry ends game, final_score screen rendered | ✓ | `test_integration.c` — 5-second timed scenario |
| **AC-2: Integration — scores frozen after `game.end`** | **✗** | **No test; PLAN.md Phase D explicitly requires verification** |
| AC-3: Existing core/mode/protocol/format CI checks unaffected | Indirect | IMPLEMENTATION.md reports `tools/check.sh` passes; CI `core` job unchanged |
| AC-4: 2-hour club game on real hardware | Deferred | Hardware not arrived; `BRING_UP.md` runbook present |

---

## Case Coverage

| Case | Status | Notes |
|------|--------|-------|
| Happy path — timer fires at expiry | ✓ | Exact-boundary tick verified |
| Happy path — preset round-trip | ✓ | All fields verified including source bytes |
| Happy path — state resume after reboot | ✓ | Timer reconstructed and fires correctly |
| Happy path — full preset-UI flow | ✓ | PIN → select → adjust → confirm → started |
| Invalid input — wrong PIN | ✓ | Buffer cleared, state stays PIN_ENTRY |
| Invalid input — preset index out of range | ✓ | Index 0 and PRESET_MAX_SLOTS+1 rejected |
| Invalid input — corrupted state file | ✓ | Magic mismatch returns false |
| Error path — unknown command target/method | ✗ | No test; command_dispatch silently drops unknown targets in source but no assertion |
| Error path — `node_runner_start` with null preset | ✗ | Guard present in source; not tested |
| Edge case — timer duration 0 (unlimited) | ✓ | `game_timer_remaining_ms` returns `UINT32_MAX` |
| **Edge case — `uint32_t` elapsed_ms overflow at UINT32_MAX** | **✗** | `elapsed_ms += delta_ms` wraps silently; not tested. Not a 2-hour production risk (max ~49 days) but a latent defect if ticks are artificially large |
| Edge case — timer fires only once | ✓ | Subsequent ticks after expiry do not re-fire |
| Edge case — empty preset store list | ✗ | `preset_store_list` on an empty directory not explicitly tested; covered implicitly by list after setup |
| Score freeze — no scoring after `game.end` | ✗ | **See blocking issue below** |
| Concurrent access / FreeRTOS queue | Deferred | Requires real hardware; all tests run single-threaded |

---

## Test Quality

**DRY:** No issues. Setup helpers (`make_timer_node`, `make_sp_node`, `setup_runner_env`) are factored and reused within each file. No duplication across files.

**KISS:** Two trivially-true assertions undermine test value:

- `test_command_dispatch.c:96` — `test_team_display_command`:
  ```c
  CHECK(q.screen_count >= 0); /* at minimum, did not crash */
  ```
  `q.screen_count` is an `int` initialised to 0 and never decremented; this assertion is always true. The command actually routes through `hal->leds->fill` + `hal->leds->show` (same path as `ring/fill`), so the correct assertion is `CHECK(hal_stub_led_fill_count >= 1)`.

- `test_integration.c:99` — unlimited-timer scenario:
  ```c
  CHECK(r.queues.screen_count >= 0); /* at minimum, runner consumed them */
  ```
  Same issue — `screen_count` can never be negative. The comment acknowledges this tests only "no crash". Remove or replace with a meaningful screen-count assertion (e.g., `>= 1` for the capture command).

**YAGNI:** No out-of-scope tests found. All test files map directly to modules listed in PLAN.md.

---

## Regression Risk

| Modified / created file | Existing coverage | Risk |
|-------------------------|------------------|------|
| `firmware/esp32/main/game_timer.c` | ✓ 4 dedicated unit tests | Low |
| `firmware/esp32/main/command_dispatch.c` | ✓ 5 unit tests (1 weak) | Low-Med |
| `firmware/esp32/main/preset_store.c` | ✓ 4 unit tests | Low |
| `firmware/esp32/main/state_persist.c` | ✓ 4 unit tests including reboot simulation | Low |
| `firmware/esp32/main/node_runner.c` | ✓ 4 unit tests + integration | Low |
| `firmware/esp32/main/preset_ui.c` | ✓ 6 unit tests | Low |
| `firmware/esp32/main/config_store.c` | ✓ 4 unit tests | Low |
| `firmware/esp32/main/screen_renderer.c` | Partial — only `final_score` template path reached indirectly via integration | Med |
| `firmware/esp32/main/shell.c` | ✗ No direct test (entry point; FreeRTOS tasks not testable on Linux) | Med (accepted risk) |
| `firmware/esp32/main/wifi_setup.c` | ✗ No test (SoftAP is a no-op in stub builds) | Med (accepted risk; no-op path) |
| `.github/workflows/ci.yml` | ✓ `esp32-build` + `firmware-test` jobs added and correctly configured | Low |

---

## Issues

### Blocking (must fix)

**1. Score freeze not verified after `game.end` (AC-2 gap)**

PLAN.md Phase D integration test requirement explicitly states: "verify status is ENDED and scores are frozen." The test does verify `ATALAIA_NODE_ENDED`, but does not verify that score totals stop changing after the timer fires.

Concretely: after the 5-second scenario ends, the test should advance the runner by 2–3 more seconds and confirm `atalaia_score_net` did not increase. Without this, a regression in the core's score-freeze logic (or in `node_runner_tick` failing to stop ticking after ENDED) would be invisible.

Suggested addition at the end of the 5-second block in `test_integration.c`:

```c
/* Verify score freeze: tick 3 more seconds after ENDED. */
const atalaia_score_t *score_before = atalaia_node_score(r.node);
int64_t red_before = score_before ? atalaia_score_net(score_before, 1) : 0;
for (int i = 0; i < 3; i++) node_runner_tick(&r, 1000);
const atalaia_score_t *score_after = atalaia_node_score(r.node);
int64_t red_after = score_after ? atalaia_score_net(score_after, 1) : 0;
CHECK(red_after == red_before); /* scores must not change after game.end */
```

---

### Non-Blocking

**2. Trivially-true assertions mask test intent**

`test_command_dispatch.c:96` and `test_integration.c:99` each use `CHECK(x >= 0)` on an unsigned-or-non-negative counter. These should be replaced with meaningful lower-bound assertions. Tracking: low priority, but confusing to future maintainers.

**3. `test_screen_renderer.c` absent — 8 of 9 templates unverified**

Documented deviation #6 in IMPLEMENTATION.md. The integration test only exercises the `final_score` template routing. The other 8 templates (`standby`, `countdown`, `defused`, `exploded`, `paused`, `status`, `preset_select`, `wifi_setup`) have no test coverage — not even a "renders without crash" smoke test. In stub mode, `screen_renderer.c` is included in the build and the template-routing switch is exercised when the mode calls `ui.screen(...)`. A minimal test that calls each template function with representative JSON and asserts `screen_rendered_count == 1` would close this gap without requiring LVGL.

**4. `uint32_t` elapsed_ms overflow at UINT32_MAX not tested**

`game_timer_tick` accumulates elapsed time as `uint32_t elapsed_ms += delta_ms`. If a pathological caller passes `delta_ms = UINT32_MAX - current_elapsed + 1`, the counter wraps to a small value below `duration_ms` and the timer never fires. This is not a 2-hour production risk (UINT32_MAX ms ≈ 49 days), but a regression test that adds a single oversized tick to a short-duration timer would document the known limitation and catch any future change that widens the type.

**5. `node_runner_tick` passes cumulative time to `atalaia_node_advance`**

`node_runner.c:112`: `atalaia_node_advance(r->node, r->game_time_ms)` passes the total elapsed game time on every tick, not the delta. If the core's `advance` API expects an absolute "current time" argument this is correct; if it expects a delta this is a compounding bug. The test for timer expiry (11 ticks of 1000 ms, 10 s timer) and the integration test (120 ticks + score check) pass, which is consistent with `advance` taking an absolute timestamp. The API semantics should be verified in the core documentation or a comment added to `node_runner_tick` explaining why cumulative time is passed.

---

## Decision

NEEDS_FIX: The missing score-freeze assertion in `test_integration.c` leaves AC-2 ("scores are frozen") uncovered. Fix is a 5-line addition to the existing integration test. All other issues are non-blocking. Resubmit after the blocking fix; no other changes are required to approve.
