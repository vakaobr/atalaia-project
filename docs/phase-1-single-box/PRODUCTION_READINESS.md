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

## ESP-IDF Build (clean copy, exit 0, no warnings)

```
Field Box (sdkconfig.defaults):
atalaia_esp32.bin: 0x14d870 bytes (1,366,128). OTA partition 1.5 MB. 13% free.
DIRAM: 205,456 bytes (60.12%), 136,304 free
Flash code: 897,036 bytes   Flash data: 345,756 bytes
IRAM:  16,383 bytes (99.99%)

Wokwi variant (sdkconfig.defaults + sdkconfig.wokwi):
atalaia_esp32.bin: 0xdd8b0 bytes (907,440). 42% free.
```

Components: esp_lvgl_port 2.4.4 (unused), led_strip 2.5.5, lvgl 9.2.2,
littlefs 1.14.8. The earlier 700 KB image did not link LVGL (the screen
code was never compiled) or initialise Wi-Fi.

## Screens

- [x] 12 templates render on the device and the host from the same code
  and `lv_conf.h`
- [x] 20 reference PNGs in `firmware/esp32/test/screens/`, compared pixel
  by pixel in CI's `firmware-test` job; clipping and overlap checks
- [x] Wokwi emulator plays a Bomb game; its display matches the references

## Open items

- **Image size:** 13% of the OTA slot is left. Grow the OTA slots
  (ADR-P1-4) or trim fonts before phase 2 adds code.
- **Game-timer bar (ADR-P1-3)** and the captive portal's DNS redirect are
  not implemented.
- **Vext (GPIO 36)** is not switched by the firmware; check the polarity
  at bring-up.

## Documentation

- [x] CHANGELOG updated
- [x] README updated
- [x] ADR written (P1-1 through P1-9)
- [x] Runbook written (BRING_UP.md, with a Wokwi step before hardware)
- [x] Emulator guide written (firmware/esp32/docs/WOKWI.md)

## Breaking Changes

None.

## Rollback

**Complexity:** Low
**Plan:** Re-flash via USB-C.

---

## Final Verdict

**Status:** SOFTWARE GATE PASSED, HARDWARE GATE OPEN

The ESP-IDF build passes from a clean copy for the Field Box and the
Wokwi variant, with no warnings. All host tests pass, including the
screen reference images. The firmware plays a Bomb game in the Wokwi
emulator. The Phase 1 gate (a 2-hour club game on a real box) is blocked
on hardware; BRING_UP.md lists what only the hardware can show.
