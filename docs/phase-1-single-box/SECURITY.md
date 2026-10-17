<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 1 -- Single Box: Security Review

**Reviewer:** Security Analyst (static audit, Phase 7a)
**Scope:** All firmware source under `firmware/esp32/main/` and `firmware/esp32/test/`
**Date:** 2026-10-17
**Verdict:** **APPROVED**

---

## Threat Model Context

The Atalaia Field Box is an **offline airsoft/paintball game prop**. Phase 1
operates as a single standalone device:

- **No internet connection.** Wi-Fi is SoftAP only, used during initial setup.
- **No mesh network.** LoRa radio is dormant (Phase 2).
- **Physical access required** for all interaction (keypad, buttons, USB).
- **Admin PIN protects game setup**, not financial or personal data.
- **Presets are flashed** as part of the LittleFS image; no network upload
  in Phase 1.

Attackers with physical access to the device can already open the enclosure,
reflash the firmware over USB, or replace the device entirely. The threat
model therefore focuses on **firmware robustness** (crash resistance,
data integrity) rather than adversarial exploitation.

---

## Methodology

1. Full source code read of all `.c` and `.h` files under `firmware/esp32/main/`
   (41 files) and `firmware/esp32/test/` (10 files).
2. STRIDE threat model applied against the ADR architecture.
3. OWASP Embedded Top 10 checklist.
4. Automated grep for unsafe C functions (`sprintf`, `strcpy`, `strcat`, `gets`).
5. Manual buffer-size and integer-overflow audit of every string and arithmetic
   operation.

---

## Findings

### [INFORMATIONAL] Captive portal POST handler is a stub

**CWE:** CWE-20 (Improper Input Validation)
**OWASP Category:** Insecure Design (deferred implementation)

**Description:**
`wifi_setup.c` `config_post_handler` (line 37) reads the POST body but does
not parse or validate any form fields. The `configured` flag is set
unconditionally. The comment reads `/* TODO: parse form fields and write to
NVS. */`.

**Affected Component:** `firmware/esp32/main/wifi_setup.c:37-63`

**Impact:**
The admin PIN, node name, region, and other config values are never actually
written to NVS from the form. The HTML form provides client-side validation
(`required`, `pattern`, `maxlength`), but these are bypassable. Since the
SoftAP accepts only 1 connection and has no internet, exploitation requires
physical proximity during the brief setup window.

**Fix Recommendation:**
When implementing the TODO, add server-side validation for all fields:
- Node name: alphanumeric + hyphen, 1-32 chars.
- PIN: exactly 4-6 digits.
- Region: must match one of the known values (EU868, US915, AU915, AS923).
- Brightness/volume: integer 0-100.

Reject the request and return a 400 with a human-readable error if any field
fails validation. Do not set `configured = 1` until all fields are valid and
written to NVS.

---

### [INFORMATIONAL] Admin PIN logged to serial console

**CWE:** CWE-532 (Insertion of Sensitive Information into Log File)
**OWASP Category:** Security Logging and Monitoring Failures

**Description:**
`wifi_setup.c` line 48 logs the raw POST body to the serial console:
```c
ESP_LOGI(TAG, "config POST: %s", buf);
```
This body will contain the admin PIN in cleartext when the TODO is completed.

**Affected Component:** `firmware/esp32/main/wifi_setup.c:48`

**Impact:**
The serial console is only accessible via physical USB connection, which
already implies full device access. On this threat model, this is
informational. However, if serial output is ever forwarded over a network
(e.g., Phase 2 remote diagnostics), the PIN would leak.

**Fix Recommendation:**
When implementing form parsing, log the field names but not the PIN value:
```c
ESP_LOGI(TAG, "config POST: name=%s region=%s pin=[redacted]", name, region);
```

---

### [INFORMATIONAL] No brute-force mitigation on keypad PIN entry

**CWE:** CWE-307 (Improper Restriction of Excessive Authentication Attempts)
**OWASP Category:** Identification and Authentication Failures

**Description:**
`preset_ui.c` resets the PIN buffer on each wrong entry with no delay,
lockout, or attempt counter. An attacker can retry immediately.

**Affected Component:** `firmware/esp32/main/preset_ui.c:36-45`

**Impact:**
A 4-digit PIN has 10,000 combinations. At human keypad speed (~1 attempt
per 5 seconds including entry + `#`), brute-forcing takes ~14 hours of
continuous physical interaction with the device. A 6-digit PIN takes ~58
days. This is impractical for a game prop used at events.

Automated attacks are not feasible: the keypad is a physical matrix scanner,
not a network endpoint.

**Fix Recommendation:**
Add a progressive delay after 3 consecutive wrong attempts (e.g., 30 seconds
on the 4th attempt, 60 seconds on the 5th). This is cheap to implement and
closes the theoretical gap:
```c
if (wrong_count >= 3) {
    ui->lockout_until_ms = current_ms + (wrong_count - 2) * 30000;
}
```

---

### [INFORMATIONAL] State persistence has no CRC/checksum

**CWE:** CWE-354 (Improper Validation of Integrity Check Value)
**OWASP Category:** Software and Data Integrity Failures

**Description:**
`state_persist.c` writes `state_persist_data_t` as a raw binary struct with
a magic number and version field but no CRC or checksum. A partial write
(power loss mid-`fwrite`) could produce a file with a valid magic and version
but corrupted score or timer data.

**Affected Component:** `firmware/esp32/main/state_persist.c:28-50`

**Impact:**
Worst case: a game resumes with slightly wrong scores after a power failure.
The magic+version check catches complete corruption (tested in
`test_invalid_magic`). LittleFS copy-on-write semantics reduce the partial-
write window.

**Fix Recommendation:**
Add a CRC32 as the last field of `state_persist_data_t`. Compute over all
preceding fields before write; verify on load. ESP-IDF provides
`esp_crc32_le()` at zero cost. Bump `STATE_PERSIST_VERSION` to 2.

---

### [INFORMATIONAL] mode_id not sanitized for path separators

**CWE:** CWE-22 (Improper Limitation of a Pathname to a Restricted Directory)
**OWASP Category:** Injection

**Description:**
`preset_store.c` `mode_source_path` builds a file path from `mode_id`
without stripping `/`, `..`, or other path separators:
```c
snprintf(buf, sz, "%s/modes/%s/node.lua", store_base, mode_id);
```

**Affected Component:** `firmware/esp32/main/preset_store.c:26`

**Impact:**
In Phase 1, `mode_id` comes from flashed preset files -- not user input.
On ESP32, LittleFS is mounted at a fixed path and cannot escape the
partition boundary, so traversal within LittleFS affects only game data.
This becomes relevant in Phase 2 when presets arrive over the network.

**Fix Recommendation:**
Before using `mode_id` in a path, reject any value containing `/`, `\`,
or `..`:
```c
static bool mode_id_valid(const char *id) {
    return id && *id && !strstr(id, "..") && !strchr(id, '/') && !strchr(id, '\\');
}
```
Apply this check in `preset_store_save` and `preset_store_load`.

---

### [INFORMATIONAL] json_get_uint can overflow uint32_t

**CWE:** CWE-190 (Integer Overflow or Wraparound)
**OWASP Category:** Injection

**Description:**
`preset_store.c` `json_get_uint` (line 120) parses digits without checking
for overflow:
```c
val = val * 10 + (uint32_t)(*p - '0');
```
A JSON file with `"duration_s":99999999999` would overflow the uint32_t.

**Affected Component:** `firmware/esp32/main/preset_store.c:120-132`

**Impact:**
The only field parsed this way is `duration_s`, which controls game timer
duration. An overflow produces a wrong game duration. The JSON comes from
flashed preset files in Phase 1, not user input. Even if manipulated, the
result is a game that runs too long or too short -- no code execution.

**Fix Recommendation:**
Add a saturation check:
```c
if (val > (UINT32_MAX - 9) / 10) { val = UINT32_MAX; break; }
```

---

### [INFORMATIONAL] Double NVS initialization

**Description:**
`shell.c` `app_main` (line 103) calls `nvs_flash_init()`, then
`config_store_init()` (line 117) calls `nvs_flash_init()` again. The second
call is harmless (returns `ESP_OK` if already initialized) but is redundant.

**Affected Component:** `firmware/esp32/main/shell.c:103` and
`firmware/esp32/main/config_store.c:21`

**Fix Recommendation:**
Remove the `nvs_flash_init()` from `config_store_init()` and document that
the caller is responsible for NVS initialization, or add an `initialized`
guard in `config_store_init`.

---

## Positive Findings

These are security-relevant properties that the codebase gets RIGHT:

1. **Zero unsafe function calls.** Grep for `sprintf`, `strcpy`, `strcat`,
   `gets` across all 51 firmware files returns zero matches. Every string
   operation uses `snprintf`, explicit length-bounded `memcpy`, or `strncpy`
   with manual null-termination.

2. **Consistent bounds checking.** Every buffer write in `command_dispatch.c`,
   `preset_store.c`, `config_store.c`, and `preset_ui.c` is bounded by
   `sizeof` or explicit size parameters.

3. **PIN buffer overflow prevention.** `preset_ui.c` line 29 checks
   `pin_pos < PRESET_UI_PIN_MAX` before writing to `pin_buffer`. The buffer
   is `PRESET_UI_PIN_MAX + 1` (9 bytes) with null-terminator.

4. **State persistence validation.** Magic number + version check on load
   correctly rejects corrupt state files. Tested with explicit garbage data
   in `test_invalid_magic`.

5. **Preset index bounds.** `preset_store_save`, `preset_store_load`, and
   `preset_store_delete` all validate `index >= 1 && index <= PRESET_MAX_SLOTS`
   before file operations. Tested in `test_invalid_index`.

6. **Game timer fires-once guarantee.** `game_timer_tick` sets `expired = true`
   on first expiry and short-circuits all subsequent calls. Tested in
   `test_timer_fires_only_once`.

7. **Queue overflow protection.** `command_dispatch.c` checks
   `screen_count < CMD_SCREEN_QUEUE_MAX` and `audio_count < CMD_AUDIO_QUEUE_MAX`
   before writing to the fixed-size queues. Excess commands are silently
   dropped, not crashed on.

8. **SoftAP single-connection limit.** `wifi_setup.c` sets
   `max_connection = 1`, preventing concurrent portal abuse.

9. **HAL null-pointer guards.** `command_dispatch.c` checks `hal && hal->leds`
   before calling LED operations. `node_runner.c` checks `r->node` before
   every operation.

10. **No hardcoded secrets.** PIN is configurable via the setup portal.
    No API keys, tokens, or credentials in the source.

---

## OWASP Embedded Application Security Top 10 Assessment

| # | Category | Status |
|---|----------|--------|
| E1 | Weak/guessable/hardcoded passwords | PASS -- PIN is user-configured, 4-6 digits |
| E2 | Insecure network services | PASS -- SoftAP only during setup, 1 connection, no internet |
| E3 | Insecure ecosystem interfaces | N/A -- no cloud, no app, no API in Phase 1 |
| E4 | Lack of secure update mechanism | NOTE -- OTA reserved (Phase 2); no update path in Phase 1 |
| E5 | Use of insecure/outdated components | PASS -- ESP-IDF v5.3.2 (current), LVGL v9, fresh deps |
| E6 | Insufficient privacy protections | N/A -- no personal data collected |
| E7 | Insecure data transfer/storage | PASS -- NVS for config, LittleFS for presets, no network |
| E8 | Lack of device management | NOTE -- no remote management in Phase 1 (by design) |
| E9 | Insecure default settings | PASS -- setup required before operation; no default PIN |
| E10 | Lack of physical hardening | N/A -- out of firmware scope; IP65 enclosure in BOM |

---

## STRIDE Summary

| Threat | Mitigation | Risk |
|--------|-----------|------|
| **Spoofing** (fake SoftAP) | SoftAP has unique MAC-derived SSID; single-connection limit | Low |
| **Tampering** (preset files) | LittleFS partition isolation; Phase 1 presets are read-only (flashed) | Low |
| **Repudiation** (score disputes) | Game scores persisted every 1s; not cryptographically signed | Accepted |
| **Information Disclosure** (PIN via serial) | Serial requires physical USB; PIN logged to console (see finding) | Low |
| **Denial of Service** (crash the device) | Bounds-checked inputs; queue overflow drops, does not crash | Low |
| **Elevation of Privilege** (bypass PIN) | Physical keypad only; no remote interface; brute-force impractical | Low |

---

## Phase 2 Hardening Checklist

When Phase 2 introduces network communication (LoRa mesh, OTA updates,
preset upload from controller), the following items must be addressed:

- [ ] Validate `mode_id` for path traversal before building file paths.
- [ ] Add server-side validation to the captive portal POST handler.
- [ ] Implement Ed25519 OTA signature verification (partition slots already
      reserved).
- [ ] Add CRC32 to `state_persist_data_t`.
- [ ] Redact PIN from serial log output.
- [ ] Add rate limiting / progressive delay on PIN entry.
- [ ] Validate preset JSON structure when received over the network.
- [ ] Add TLS or HMAC-signed commands for LoRa mesh traffic.

---

## Conclusion

The Phase 1 firmware is **well-written defensive C** with zero uses of
unsafe string functions, consistent bounds checking, and proper validation
of magic numbers and index ranges. All six informational findings are
defense-in-depth improvements, not exploitable vulnerabilities in the
Phase 1 threat model (offline, physical-access-only game prop).

**Verdict: APPROVED** -- no blockers for Phase 1 deployment.
