<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Production Readiness: phase-1-single-box

**Date:** 2026-10-17

---

## Expert Sign-offs

- [x] Security: APPROVED (SECURITY.md)
- [x] QA: APPROVED after fix iteration 1 (QA.md)
- [x] SRE: APPROVED after fix iteration 1 (SRE.md)

## Code Quality

- [x] ESP-IDF cross-compile: exit 0 from clean copy
- [x] Firmware host tests: 59 test functions, ~300 assertions, all pass
- [x] Existing CI (check.sh): 12 mode tests + core tests, no regressions
- [x] Formatting: clean (clang-format 18 + StyLua)
- [x] Licensing: reuse lint compliant

## ESP-IDF Build (clean copy, exit 0)

```
Total image size: 716438 bytes (700 KB)
atalaia_esp32.bin: 0xaef00 bytes. OTA partition 1.5 MB. 54% free.
DRAM:  99,744 bytes (29.19%), 242,016 bytes free
Flash code: 498,428 bytes
IRAM:  16,383 bytes (99.99%)
```

Components: esp_lvgl_port 2.4.4, led_strip 2.5.5, lvgl 9.2.2, littlefs 1.14.8.

## Stubbed (not done)

- **LVGL host rendering and PNG artifacts:** LVGL widget trees compile
  on ESP32 but are not built or rendered on the host. Template routing
  is tested on the host (12 screen renderer tests). Building LVGL 9.2
  from source in the host test build was not completed.
- **preset_select screen:** TODO in the LVGL widget-building path.

## Documentation

- [x] CHANGELOG updated
- [x] README updated
- [x] ADR written (P1-1 through P1-9)
- [x] Runbook written (BRING_UP.md)

## Breaking Changes

None.

## Rollback

**Complexity:** Low
**Plan:** Re-flash via USB-C.

---

## Final Verdict

**Status:** SOFTWARE GATE PASSED, HARDWARE GATE OPEN

The ESP-IDF build passes from a clean copy. All host tests pass. All
expert reviews approved. The LVGL host rendering (PNG artifacts and
hash checks) is not done. The Phase 1 gate is blocked on hardware.
