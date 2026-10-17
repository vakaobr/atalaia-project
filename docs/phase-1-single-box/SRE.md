<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# SRE Review: phase-1-single-box

**When:** 2026-10-17

---

## Verdict

**Status:** NEEDS_FIX

Four blocking issues must be resolved before the 2-hour stability gate can
meaningfully be executed. Two affect the phase 1 gate directly (state never
restored on reboot; device never reboots after setup), one is a security
defect (admin PIN in serial log), and one would cause an immediate OOM crash
on any Reduced-tier board.

---

## Operational Surface

| Category | Change | Notes |
|----------|--------|-------|
| New endpoints | No | Wi-Fi setup portal (Phase 1) is not a production endpoint; it is a one-time setup flow with no ongoing exposure |
| New env vars | No | All config is in `sdkconfig.defaults` / Kconfig; no runtime environment variables |
| External dependencies | No | Fully standalone; no cloud, no network after setup |
| Data migrations | No | Binary state format (magic + version); breaking changes require a reflash |
| Background jobs | Yes | Four FreeRTOS tasks + mem_monitor task; all permanent |
| Resource usage | Yes | 6 KB + 6 KB + 4 KB + 4 KB task stacks; Lua heap 256 KB (Full) or 64 KB (Reduced); LVGL heap 48 KB / 16 KB; state persisted to LittleFS every second |

---

## Observability

| Check | Status | Notes |
|-------|--------|-------|
| Error logging | Partial | Boot PSRAM detection, NVS errors, and Wi-Fi start are logged. HAL init result, task creation failures, and `state_persist_save` failures are not logged. |
| No sensitive data in logs | FAIL | `config_post_handler` logs the entire POST body at INFO level (`ESP_LOGI(TAG, "config POST: %s", buf)`) — this includes the admin PIN in plaintext. See Blocking Issue 1. |
| Metrics instrumented | N/A | Embedded firmware; no Prometheus or metrics pipeline. Serial log is the instrument. |
| Trace propagation | N/A | No distributed tracing. Single-device, no network in Phase 1. |
| Memory monitoring | PASS | `mem_monitor` task logs DRAM and PSRAM heap (free/min/largest) every 10 s. Sufficient for detecting slow leaks during the 2-hour gate. |
| Structured logging | N/A | ESP_LOG macros are the standard for ESP-IDF; log level + tag + message is the expected format. |

---

## Error Handling

| Check | Status | Notes |
|-------|--------|-------|
| HAL init failure | Partial | `hal_esp_init()` return value is not checked. If init fails, execution continues into `config_store_init()` and task creation. A watchdog will eventually catch the resulting crash, but the failure mode is opaque. Non-blocking for Phase 1 (serial monitor is always attached during bring-up). |
| NVS corruption | PASS | Erase + reinit path is implemented for both `ESP_ERR_NVS_NO_FREE_PAGES` and `ESP_ERR_NVS_NEW_VERSION_FOUND`. Second `nvs_flash_init()` result after erase is unchecked — unlikely corner case. |
| LittleFS mount failure | Partial | Neither `preset_store_init` nor `state_persist_init` mount LittleFS; they only configure path strings. It is assumed the LittleFS partition was mounted elsewhere (not visible in reviewed code). If LittleFS is not mounted, all `fopen` calls silently return NULL and `state_persist_save` silently returns false with no log. |
| Task creation failure | NOT CHECKED | All four `xTaskCreatePinnedToCore` calls discard the returned handle. Out-of-memory at task creation is silent. |
| HTTP status codes | PASS | Portal returns 400 on empty body; 200 on success. Appropriate. |
| Reboot after setup | FAIL | `esp_restart()` is commented out in `config_post_handler`. Portal shows "Rebooting..." but the device never reboots. See Blocking Issue 4. |

---

## Configuration

No new environment variables. All hardware configuration is Kconfig / `sdkconfig.defaults`.

| Symbol | Purpose | Default | Required |
|--------|---------|---------|---------|
| `CONFIG_IDF_TARGET` | ESP32 variant | `esp32s3` | Yes |
| `CONFIG_ESPTOOLPY_FLASHSIZE_16MB` | Flash size | 16 MB | Yes (Heltec V4.3) |
| `CONFIG_SPIRAM` | Enable PSRAM | `y` | Yes (Full tier) |
| `CONFIG_FREERTOS_HZ` | FreeRTOS tick rate | 1000 Hz | Yes |
| `CONFIG_ESP_SYSTEM_PANIC_PRINT_REBOOT` | Print panic + reboot | `y` | Yes |
| `CONFIG_ESP_MAIN_TASK_STACK_SIZE` | app_main stack | 8 KB | Yes |

Kconfig symbols for pin assignments (buttons, keypad, LEDs, display, NFC,
audio, battery) are all in `Kconfig.projbuild`. No GPIO numbers appear
hardcoded in C source. This is correct per ADR-P1-1.

---

## Rollback

**Complexity:** Low

Phase 1 has no OTA and no migration. Rolling back means re-flashing the
previous `.bin` artifact over USB-C:

```
idf.py flash -p /dev/ttyUSB0 --app-flash-address 0x20000 \
    --flash-bin path/to/previous.bin
```

The `otadata` partition is present for Phase 2. In Phase 1 it is
uninitialised and the bootloader always loads `ota_0`. Re-flashing ota_0
is sufficient. State in the LittleFS `storage` partition persists across
reflashes; if the state file from the broken firmware is incompatible,
erase it:

```
esptool.py erase_region 0x320000 0x200000
```

---

## Runbook

### What it does

The Atalaia Field Box firmware runs a standalone game prop on an
ESP32-S3 (Heltec WiFi LoRa 32 V4.3). It boots, detects PSRAM to select
a memory tier, initialises the HAL, and — if unconfigured — opens a
captive-portal Wi-Fi AP for one-time setup. In normal operation it runs
four FreeRTOS tasks: `game_task` (100 Hz game loop), `lvgl_task` (display
renderer at 200 Hz), `audio_task`, and `wifi_task` (idle in Phase 1). Game
state is persisted to LittleFS every second so a power cut does not lose
progress. Memory is reported over serial every 10 s.

### Health check

Connect a serial terminal at 115200 baud. A healthy device shows:

```
I (xxx) atalaia: PSRAM detected: 2048 KB
I (xxx) atalaia: Atalaia vX.Y.Z  tier=full
I (xxx) mem_monitor: DRAM free=NNN min=NNN largest=NNN
I (xxx) mem_monitor: PSRAM free=NNN min=NNN
```

Every 10 s the mem_monitor line repeats. Absence of this line indicates
the `mem_monitor` task has crashed or the scheduler is stalled.

For the 2-hour stability gate, watch for:
- Any `E (xxx)` error lines appearing mid-game.
- DRAM `min` trending down toward 0 (leak indicator).
- Watchdog reset messages (indicates a task has stopped yielding).

### Failure modes

| Symptom | Likely cause | Resolution |
|---------|-------------|------------|
| Device reboots repeatedly on boot | Panic in HAL init or LittleFS mount failure | Attach serial; read panic backtrace; check wiring / Vext (GPIO 36) |
| `mem_monitor` line stops appearing | `mem_monitor` task or scheduler stalled | Note timestamp; capture serial log; reflash with debug build |
| DRAM `min` drops to < 20 KB | Memory leak in Lua heap or audio buffers | Stop game; verify mode script; check `LVGL_MEM_SIZE` and Lua mem_limit |
| Game does not resume after power cut | `state_persist_load` not called (Blocking Issue 2) | Known defect — currently not implemented |
| Setup portal says "Rebooting..." but device stays up | `esp_restart()` commented out (Blocking Issue 4) | Manually power-cycle after setup |
| Serial log shows task stall / TWDT timeout | One of the four tasks is blocked on I/O | Check HAL driver (SPI, I2C, I2S) for blocking calls without timeout |

### Alerts to configure

For Phase 1 this is a single-box standalone prop; there is no
alerting infrastructure. Monitoring is manual serial-log inspection
during and after the 2-hour gate. Document any `E`-level log lines
and memory floor reached.

---

## Issues

### Blocking (must fix)

**B-1: Admin PIN logged in plaintext**
`wifi_setup.c` line 48 logs the entire POST body — which contains the
admin PIN — at INFO level:
```c
ESP_LOGI(TAG, "config POST: %s", buf);
```
Anyone with access to the serial log during setup learns the PIN. Replace
with a redacted log (e.g., log only field names and lengths, not values),
or remove the log entirely after the form parser is implemented.

**B-2: `state_persist_load` is never called**
`state_persist_save` is called every second in `node_runner_tick`, but
there is no code path in `shell.c` or `node_runner.c` that calls
`state_persist_load` at boot. The binary state is written but never
read back. Power-loss recovery (BRING_UP.md Step 12) will fail: the game
will start fresh, not resume. The load + resume path must be implemented
before the power-loss recovery test can be closed.

**B-3: `node_runner.c` hardcodes `mem_limit = 256 KB` regardless of tier**
`shell.c` detects PSRAM and sets `mem_limit = 64 KB` for Reduced-tier
boards, but this value is never passed to `node_runner_start`. The
`node_runner.c` implementation hardcodes `cfg.mem_limit = 256u * 1024u`
unconditionally. On a Heltec V3 (no PSRAM, Reduced-tier), the Lua heap
would try to allocate 256 KB of DRAM, exhausting it immediately. The
comment `(void)mem_limit; /* Used when creating nodes. */` in `shell.c`
acknowledges the variable but the wiring was never implemented. Pass
`mem_limit` through to `node_runner_start` and store it in
`node_runner_t` for use in `node_runner_start`.

**B-4: Reboot not implemented after Wi-Fi setup completes**
`config_post_handler` in `wifi_setup.c` has `esp_restart()` commented
out with a note about deferring it to a timer. The portal page sends the
response `"Saved. Rebooting..."` but the device never reboots. The
operator must manually power-cycle. This breaks the captive-portal UX
described in ADR-P1-5 step 6 and the BRING_UP.md Step 10 checklist item
5. Implement a short `esp_timer` (e.g., 500 ms) that calls
`esp_restart()` after the response is flushed.

### Non-Blocking

**N-1: `hal_esp_init` return not checked**
If HAL init fails (wiring error, I2C NACK, SPI timeout), execution
continues. The resulting crash will trigger the watchdog and print a
backtrace, so it is diagnosable, but the root cause is obscured. Add an
`ESP_ERROR_CHECK` or explicit log + halt.

**N-2: `xTaskCreatePinnedToCore` return values not checked**
All four task creation calls in `app_main` discard the `TaskHandle_t *`
parameter. On OOM during boot the failure is silent. Add a NULL check and
halt with `ESP_LOGE` + `abort()`.

**N-3: `state_persist_save` failure not logged**
When `fopen` fails (LittleFS not mounted, partition full, corrupt FS), the
function returns `false` and `node_runner_tick` ignores the return value.
A one-line `ESP_LOGW` on false return would make field debugging much
faster.

**N-4: LittleFS mount not visible in reviewed code**
Neither `preset_store_init` nor `state_persist_init` call
`esp_littlefs_mount`. If the mount happens inside HAL init or elsewhere,
confirm it is before `preset_store_init` and add an error check. If it is
missing, all file operations silently fail.

**N-5: BRING_UP.md Step 2 references Vext GPIO code not present in shell.c**
Step 2 says "Verify: `shell.c` drives GPIO 36 high early in `app_main`"
but `shell.c` has no such code. Either add the Vext drive to `app_main`
(before HAL init, since display and NFC depend on it), or correct the
checklist to say "Verify Vext is driven by `hal_esp_init`."

**N-6: No minimum heap warning threshold in mem_monitor**
The mem_monitor task logs heap stats but does not emit a warning when free
DRAM drops below a safety floor (e.g., 30 KB). Adding an
`ESP_LOGW` when `dram.total_free_bytes < 30 * 1024` would make it easier
to catch slow leaks during the 2-hour gate without watching every log line.

---

## Decision

NEEDS_FIX: See blocking issues B-1 through B-4 above. The 2-hour
stability gate should not be attempted until B-2 and B-4 are fixed (the
gate explicitly tests power-loss recovery and setup flow), B-1 is fixed
before any real admin PIN is entered into the device, and B-3 is fixed if
a Reduced-tier board is used in testing.
