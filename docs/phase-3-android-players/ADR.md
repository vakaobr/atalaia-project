<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 3 -- Android and Players: Architecture Decisions

Twelve decisions settle the structure of the Flutter app, the I/O pod
firmware, the capability proxy protocol, the player-facing features and
the CI pipeline before implementation begins.  Each one answers a
question the research phase identified and creates a constraint that
the planning phase must respect.

---

### ADR-P3-1: dart:ffi bridge architecture

**Status:** Accepted

**Context:** The C core (`core/`) runs on Android via dart:ffi.  The
Dart FFI must wrap every public function in `node.h`, handle C-to-Dart
callbacks, run the 100 Hz game loop off the UI thread, manage native
memory, and integrate the NDK cross-compile into Flutter's Gradle build.
The simulator's `core.py` ctypes wrapper is the reference for the
complete C API surface.  The research identified callback wiring and
the game loop isolate as the two highest-risk items.

**Decision:**

#### Loading the library

`libatalaia_core.so` is loaded once per process via
`DynamicLibrary.open('libatalaia_core.so')`.  On Android, the `.so`
files are in `jniLibs/<abi>/` and the system linker resolves them.
All C function lookups use `lookupFunction<NativeType, DartType>`.

A single Dart file `app/lib/ffi/bindings.dart` mirrors the ctypes
wrapper in `simulator/atalaia_sim/core.py`:

| C function | Dart binding |
|-----------|-------------|
| `atalaia_node_create` | `Pointer<Void> Function(Pointer<NodeConfig>)` |
| `atalaia_node_destroy` | `void Function(Pointer<Void>)` |
| `atalaia_node_load` | `int Function(Pointer<Void>, Pointer<Utf8>, int, Pointer<Utf8>)` |
| `atalaia_node_set_teams` | `void Function(Pointer<Void>, Pointer<Pointer<Utf8>>, int)` |
| `atalaia_node_set_params` | `void Function(Pointer<Void>, Pointer<Utf8>)` |
| `atalaia_node_input` | `int Function(Pointer<Void>, Pointer<Utf8>, Pointer<Utf8>)` |
| `atalaia_node_advance` | `void Function(Pointer<Void>, int)` |
| `atalaia_node_status` | `int Function(Pointer<Void>)` |
| `atalaia_node_mem_used` | `int Function(Pointer<Void>)` |

#### Callbacks

The `atalaia_node_callbacks_t` struct has three function pointers:
`event`, `command`, `log` (plus `field_state` for controller nodes).
Dart registers these using `NativeCallable<T>.listener`, which is safe
to call from any thread and any isolate (Dart 3.1+).

Each callback does minimal work: it serialises the arguments into a
small message and posts it to the game-loop isolate's `SendPort`.  The
callback MUST NOT call back into any `atalaia_node_*` function (the
core is not re-entrant within a callback).

```
C core calls event(user, ev, data_json)
  -> NativeCallable.listener fires on the C thread
    -> copies ev fields + data_json into a Dart Map
    -> sendPort.send(map)
    -> game loop isolate receives and dispatches
```

`Pointer.fromFunction` is NOT used because it requires the callback to
be a top-level or static function with a fixed return type and no
closures.  `NativeCallable.listener` allows closures over the
`SendPort`, which is essential for isolate communication.

#### Game loop isolate

A dedicated Dart isolate (`GameLoopIsolate`) owns the `atalaia_node_t`
pointer and runs the game loop.  The UI isolate NEVER calls any
`atalaia_node_*` function directly.

```
UI isolate                     Game loop isolate
    |                                |
    |--- SendPort: input event ----->|
    |                                |-- atalaia_node_input()
    |                                |-- atalaia_node_advance()
    |<-- ReceivePort: screen cmd ----|
    |<-- ReceivePort: event ---------|
    |                                |
    |--- SendPort: start/stop ------>|
```

The game loop runs at 100 Hz using a `Timer.periodic(Duration(
milliseconds: 10), ...)` inside the isolate.  On each tick:

1. Drain the input queue (events from UI, pod, NFC, GPS).
2. Call `atalaia_node_input` for each pending input.
3. Call `atalaia_node_advance(node, elapsed_ms)`.
4. Process callback messages (screen updates, LED commands, audio).
5. Send UI updates to the UI isolate via `SendPort`.

The wall-clock delta is computed with `Stopwatch` and converted to game
time, matching the ESP32 shell's `game_timer_t` approach (ADR-P1-3).

#### Memory management

- Strings passed to C are allocated with `calloc` from `package:ffi`,
  and freed with `calloc.free` after the C call returns.
- The core uses `realloc`/`free` (the default allocator) on Android;
  PSRAM is irrelevant.
- `mem_limit` is set to 256 KB (matching the Full tier on ESP32 with
  PSRAM).  Android has ample RAM; the limit prevents runaway scripts.

#### NDK cross-compile via Gradle

The core is cross-compiled for Android ABIs using Gradle's
`externalNativeBuild` block in `app/android/app/build.gradle.kts`:

```kotlin
android {
    externalNativeBuild {
        cmake {
            path = file("../../../core/CMakeLists.txt")
        }
    }
    defaultConfig {
        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a", "x86_64")
        }
        externalNativeBuild {
            cmake {
                arguments += "-DATALAIA_SHARED=ON"
            }
        }
    }
}
```

This integrates with `flutter build apk` so the CI pipeline builds
everything in one step.  The NDK CMake toolchain is selected
automatically by Gradle.

Output location:

```
app/android/app/build/intermediates/cmake/
    debug/obj/arm64-v8a/libatalaia_core.so
    debug/obj/armeabi-v7a/libatalaia_core.so
    debug/obj/x86_64/libatalaia_core.so
```

Gradle packages these into the APK automatically.

**Consequences:**
- The Dart FFI surface mirrors the Python ctypes wrapper; both are
  maintained from the same `node.h`.
- `NativeCallable.listener` handles all callbacks safely; no
  `Pointer.fromFunction` limitations apply.
- The game loop isolate ensures thread safety: only one Dart isolate
  touches the `atalaia_node_t` pointer.
- Gradle-integrated CMake means `flutter build apk` builds the core
  for all ABIs without a separate step.
- The 100 Hz tick matches the ESP32 shell; mode timing behaviour is
  identical.

---

### ADR-P3-2: Capability proxy protocol v1

**Status:** Accepted

**Context:** The I/O pod (ESP32 board) lends capabilities (buttons,
LEDs, radio, NFC) to an Android phone over BLE GATT or USB-OTG.  The
spec (section 7) defines four frame types (IDENT, EVT, CMD, ACK) but
does not freeze the binary format, GATT UUIDs, or characteristic
layout.  The research identified this as the highest-risk item: if the
format is not frozen before pod development, rework is likely.

**Decision:** Freeze the capability proxy protocol v1 as follows.

#### Frame format (shared by BLE and USB)

**Updated 2026-10-18 (phase 2 handoff):** the USB radio modem framing
changed from bare type+length+payload to include a sync byte and CRC
(decision D1 in `docs/review/decisions-to-review.md`).  The pod adopts
the same framing so it can share `firmware/esp32/main/modem/modem_framing.c`.

All frames use the modem's binary encoding (`protocol/usb-modem.md`):

```
0xA5 | type (1) | length (2, big-endian) | payload (0-256 bytes) | CRC-16 (2, big-endian)
```

CRC-16/CCITT-FALSE (polynomial 0x1021, init 0xFFFF, no reflection,
no final XOR) over type, length and payload.  Over BLE GATT, the sync
byte and CRC are still sent: they cost only 5 bytes and keep one
parser for both transports.

Frame types:

| Type | Value | Direction | Payload |
|------|-------|-----------|---------|
| IDENT | `0x01` | pod -> phone | CBOR: capabilities, firmware version, battery |
| EVT | `0x02` | pod -> phone | CBOR: capability_id (text) + event_type (text) + data (map) |
| CMD | `0x03` | phone -> pod | CBOR: capability_id (text) + method (text) + args (map) |
| ACK | `0x04` | both | uint16 big-endian: seq of the frame being acknowledged |
| RADIO_RX | `0x05` | pod -> phone | header (9) + plaintext payload + rssi (int8) + snr (int8) + **epoch (uint16 BE)** |
| RADIO_TX | `0x06` | phone -> pod | header (9) + plaintext payload (up to 200) |
| RADIO_TX_ACK | `0x07` | pod -> phone | seq (uint16 BE) + status (1): statuses 0-7 per `protocol/usb-modem.md` |
| RADIO_CMD | `0x08` | phone -> pod | opcode (1) + params: PING, CONFIGURE(27 bytes), SET_CHANNEL, STATUS, SET_PEER_EPOCH, CLEAR, IDENT |
| RADIO_STATUS | `0x09` | pod -> phone | JSON: same fields as modem STATUS |

Frame types `0x05`-`0x09` match the modem's `0x02`-`0x06` shifted by
3.  The pod shares the modem's C framing code and acts as both a
capability proxy and a radio modem.  RADIO_RX carries the nonce epoch
(decision D2) so the phone can track rebooted boxes.  RADIO_CMD uses
the modem's opcodes and parameters (CONFIGURE is 27 bytes: game_id 2,
node_id 2, epoch 2, max_hops 1, channel_hz 4, key 16).

#### IDENT payload (CBOR map)

| Key | Field | Type | Notes |
|-----|-------|------|-------|
| 1 | `fw_version` | text | Pod firmware version |
| 2 | `capabilities` | array | Array of capability descriptors (same format as the node descriptor in spec section 7) |
| 3 | `battery_pct` | uint8 | Pod battery level 0-100 |
| 4 | `has_radio` | bool | Whether the pod has a LoRa radio |
| 5 | `protocol_version` | uint8 | Capability proxy protocol version (1) |

#### EVT payload (CBOR map)

| Key | Field | Type | Notes |
|-----|-------|------|-------|
| 1 | `cap_id` | text | Capability identifier (e.g. "btn.red", "nfc") |
| 2 | `event` | text | Event type (e.g. "press", "hold", "tag") |
| 3 | `data` | map | Event data (e.g. `{"ms": 5000}` for hold, `{"uid": "...", "data": "..."}` for NFC) |
| 4 | `seq` | uint16 | Per-pod sequence number for ACK |

#### CMD payload (CBOR map)

| Key | Field | Type | Notes |
|-----|-------|------|-------|
| 1 | `cap_id` | text | Target capability |
| 2 | `method` | text | Command method (e.g. "fill", "tone", "color") |
| 3 | `args` | map | Command arguments (e.g. `{"r": 255, "g": 0, "b": 0}`) |
| 4 | `seq` | uint16 | Per-phone sequence number for ACK |

#### BLE GATT service

Service UUID: `4174616C-6169-6100-0000-000000000001`
(derived from "Atalai\0" in ASCII, padded with zeros)

| Characteristic | Short UUID | Full UUID | Properties | Purpose |
|---------------|------------|-----------|------------|---------|
| Pod TX | `0001` | `4174616C-6169-6100-0000-000000000001` + `0001` | Notify | Pod -> phone: IDENT, EVT, RADIO_RX, RADIO_TX_ACK, RADIO_STATUS |
| Pod RX | `0002` | `...0002` | Write Without Response | Phone -> pod: CMD, RADIO_TX, RADIO_CMD |
| Pod Status | `0003` | `...0003` | Read, Notify | Battery %, RSSI, connection state (1-byte each, no framing) |

The full 128-bit UUIDs use the base
`4174616C-6169-61CC-CCCC-CCCCCCCCCCCC` where `CCCC...` is the short
characteristic id zero-padded.  This avoids collision with standard
Bluetooth SIG UUIDs.

BLE MTU: the phone requests an MTU of at least 247 bytes (BLE 4.2
minimum for data length extension).  All capability proxy frames fit
within this MTU.  Radio packets (max 217 bytes) fit within a 247-byte
MTU with the 3-byte frame header.

Long frames (> MTU - 3 ATT overhead) are fragmented at the GATT layer
by the BLE stack.  The application layer sees complete frames.

#### USB-OTG framing

Over USB CDC serial, the same `type (1) + length (2) + payload` framing
is used.  The pod appears as a USB CDC ACM device.  Baud rate: 921600
(matching the radio modem).  The phone uses `UsbManager` to open the
device and reads/writes raw bytes.

USB is preferred over BLE when both are available (lower latency,
higher throughput, no pairing needed, power from the phone).

#### Sequence numbers and ACK

EVT and CMD frames carry a `seq` field (uint16, wrapping).  The
receiver sends an ACK frame with the seq to confirm receipt.
Unacknowledged frames are retried after 500 ms, up to 3 times.
After 3 failures, the link is considered broken and a reconnection
attempt begins.

Radio frames (RADIO_RX, RADIO_TX) are NOT acknowledged at the proxy
layer; the LoRa layer handles its own reliability.

#### Test vectors

Shared test vectors for IDENT, EVT, CMD and ACK frames are defined in
`protocol/vectors/capability_proxy.yaml`.  Both the Dart client and the
ESP32 pod firmware parse these vectors in their unit tests.

**Implemented 2026-10-18 (plan phase A):** the full specification is
`protocol/capability-proxy.md`; it settles what this ADR left open
(decision A9): a RADIO_ERROR frame (`0x0A`), the proxy IDENT as the answer
to RADIO_CMD IDENT, the GATT service UUID `4174616c-6169-6100-0000-000000000000`
(above, the service had Pod TX's UUID), the Pod Status bytes, required
fields and limits, and unknown keys 6-23 skipped.

**Consequences:**
- The frame format is frozen for v1; changes require a protocol version
  bump.
- Shared framing code between the radio modem and the capability proxy
  reduces implementation effort.
- BLE and USB use the same frame encoding; the transport layer is
  swappable.
- The GATT service uses a custom 128-bit UUID base, avoiding conflicts.
- Test vectors ensure Dart and C implementations agree on encoding.

---

### ADR-P3-3: I/O pod firmware variant

**Status:** Accepted

**Context:** The I/O pod is an ESP32 board (Heltec V4.3 or smaller
module) that lends capabilities to an Android phone.  It does not run
Lua scripts.  The firmware must be a build variant of the existing node
firmware, following the Kconfig pattern established by the USB radio
modem in ADR-P2-4.

**Decision:** A new Kconfig option `CONFIG_ATALAIA_POD_MODE` creates the
third firmware variant alongside `CONFIG_ATALAIA_NODE_MODE` (default)
and `CONFIG_ATALAIA_MODEM_MODE` (ADR-P2-4).

```
choice ATALAIA_DEVICE_MODE
    prompt "Device mode"
    default ATALAIA_NODE_MODE

    config ATALAIA_NODE_MODE
        bool "Field Box node"

    config ATALAIA_MODEM_MODE
        bool "USB radio modem"

    config ATALAIA_POD_MODE
        bool "I/O pod (capability proxy)"
endchoice
```

#### What runs in pod mode

| Task | Core | Priority | Stack | Purpose |
|------|------|----------|-------|---------|
| `proxy_task` | 1 | 5 | 6 KB | Capability proxy: read EVTs from HAL, send to phone; receive CMDs from phone, dispatch to HAL |
| `ble_gatt_task` | 0 | 4 | 6 KB | BLE GATT server: advertise, handle connections, notify/write |
| `radio_task` | 0 | 3 | 6 KB | LoRa radio: same as node mode (encrypt, decrypt, flood, duty cycle) |
| `usb_cdc_task` | 0 | 3 | 4 KB | USB CDC serial: receive/send frames |
| `audio_task` | 0 | 2 | 4 KB | Audio playback: same as node mode |
| `mem_monitor` | 0 | 1 | 2 KB | Heap stats logging |

#### What is disabled in pod mode

- Lua sandbox (`sandbox.c`, `script_api.c`): not linked.
- LVGL display driver and screen renderer: not linked.
- Preset store and game logic: not linked.
- Game loop and game timer: not linked.
- Wi-Fi captive portal: not linked (the pod is configured over BLE
  or USB from the phone).

#### What is shared with node mode

- HAL modules: `hal_button_ops_t`, `hal_led_ops_t`, `hal_audio_ops_t`,
  `hal_nfc_ops_t`, `hal_radio_ops_t`, `hal_battery_ops_t`.
- Radio stack: SX1262 driver, AES-CCM, flood/dedupe, duty-cycle.
- FreeRTOS, NVS, LittleFS.

#### BLE GATT and USB CDC coexistence

Both transports are always active.  The proxy task accepts commands from
whichever transport delivers them.  If both are connected, USB takes
priority (lower latency).  EVT frames are sent to both connected
transports simultaneously.

The BLE GATT server advertises the service UUID from ADR-P3-2 with the
device name `atalaia-pod-XXXX` (last 4 hex of MAC).  It accepts one
connection at a time.  On disconnect, it returns to advertising.

The USB CDC device is always enabled.  When a phone connects over USB,
it sends an IDENT request (RADIO_CMD with opcode `ident`), and the pod
responds with an IDENT frame.

#### Pod configuration

The pod stores its configuration in NVS:
- Radio region (EU868, US915, etc.)
- Button pin assignments (from Kconfig)
- LED count and type
- Audio configuration
- Admin PIN

The pod is configured during initial setup from the phone app (sent
over BLE or USB as CMD frames with a `config` capability target).

#### Firmware size

Without Lua and LVGL, the pod firmware is significantly smaller than
the node firmware (~300 KB vs ~550 KB), fitting comfortably in the
1.5 MB OTA partition with room for future features.

**Consequences:**
- The pod firmware is a build variant, not a separate project.  One
  ESP-IDF project produces three binaries via Kconfig.
- The pod reuses all HAL modules and the full radio stack from the
  node firmware.
- BLE and USB run simultaneously; no configuration needed to switch.
- The pod never runs scripts; it is a pure proxy.
- The same OTA mechanism (A/B partitions, Ed25519) updates the pod
  firmware.

---

### ADR-P3-4: Declarative screen template format

**Status:** Accepted

**Context:** ADR-P1-2 deferred declarative screen templates to phase 3.
Currently, templates are C functions in `screen_renderer.c` that build
LVGL widget trees.  Phase 3 needs the same templates to render in
Flutter.  The research evaluated YAML vs JSON and proposed a minimal
widget type set.

**Decision:** Templates are **YAML files** in each mode's
`assets/screens/` directory, parsed by both the LVGL renderer (ESP32)
and the Flutter renderer (Android/iOS).

#### Format

```yaml
# modes/bomb/assets/screens/countdown.yaml
template: countdown
layout:
  - type: label
    id: time_left
    text: "{left}"
    style: { font_size: 72, align: center, color: team }
  - type: progress_bar
    id: fuse_bar
    value: "{left / params.fuse_s}"
    style: { height: 16, color: team }
  - type: label
    id: status_text
    text: "ARMED"
    style: { font_size: 24, align: center }
```

YAML is chosen over JSON because:
- Mode authors already write `mode.yaml`; YAML is the project's data
  format.
- YAML supports comments (useful for template documentation).
- YAML is a superset of JSON; a JSON template is valid YAML.

#### Widget types (v1)

| Type | Properties | LVGL widget | Flutter widget |
|------|-----------|-------------|----------------|
| `label` | `text`, `style` | `lv_label` | `Text` |
| `progress_bar` | `value` (0.0-1.0), `style` | `lv_bar` | `LinearProgressIndicator` |
| `icon` | `icon` (name), `style` | `lv_image` (from built-in set) | `Icon` (Material icons) |
| `qr_code` | `data`, `style` | `lv_qrcode` (LVGL extra) | `QrImageView` (qr_flutter) |
| `spacer` | `height` | `lv_obj` with fixed height | `SizedBox` |
| `row` | `children`, `style` | `lv_obj` with flex row | `Row` |
| `column` | `children`, `style` | `lv_obj` with flex column | `Column` |

No additional widget types in v1.  Complex layouts (multi-pane
dashboards, animations) are deferred to phase 5's visual editor.

#### Interpolation

`{variable}` is replaced with values from the data map passed to
`ui.screen(template, data)`.  Simple arithmetic is supported:

- `{left}` -- direct substitution
- `{left / params.fuse_s}` -- division (for progress bars)
- `{score.red + score.blue}` -- addition

The interpolation engine supports: variable lookup, `+`, `-`, `*`, `/`,
and parenthesised sub-expressions.  No function calls, no conditionals.
The expression parser is ~100 lines in both C and Dart.

The special value `team` in `color: team` is resolved to the owning
team's colour at render time.

#### Style properties

| Property | Values | Notes |
|----------|--------|-------|
| `font_size` | integer (points) | Scaled proportionally on different displays |
| `align` | `left`, `center`, `right` | Text alignment |
| `color` | `team`, named colour, hex `#RRGGBB` | `team` is dynamic |
| `background` | Same as `color` | Widget background |
| `padding` | integer or `{top, right, bottom, left}` | In logical pixels |
| `height`, `width` | integer or `fill` | `fill` = expand to parent |
| `visible` | `true`, `false`, `{expression}` | Conditional visibility |

#### LVGL renderer (ESP32)

`screen_template.c` parses YAML templates from LittleFS at mode load
time using a minimal YAML subset parser (no anchors, no multi-document,
no flow collections -- just block mappings, block sequences and
scalars).  The parser produces an in-memory tree of `template_node_t`
structs.

On `ui.screen(template, data)`:
1. If the widget tree for this template has not been built, create LVGL
   widgets from the template tree.
2. If the widget tree exists, patch data values into existing widgets
   (same approach as the current C screen functions).

Templates are cached; only data values change between calls.

The minimal YAML parser adds ~3 KB to the firmware binary.  A full YAML
library is not used (too large for ESP32).

#### Flutter renderer (Android/iOS)

`screen_template.dart` parses the same YAML files using the `yaml`
Dart package (already commonly used in Flutter).  On `ui.screen`:
1. Parse the template (cached after first parse).
2. Build a Flutter widget tree from the template nodes.
3. Rebuild reactively when data changes (`setState`).

#### Migration from C functions

The existing C screen functions in `screen_renderer.c` remain as the
fallback: if no YAML template exists in `assets/screens/` for a given
template name, the C function is called.  This allows incremental
migration.

Built-in modes (Domination, Bomb) are migrated to YAML templates.  New
modes (phase 3+) use YAML exclusively.

#### Template validation

A new CI check validates all `assets/screens/*.yaml` files:
- Valid YAML syntax.
- Only allowed widget types.
- Interpolation expressions are parseable.
- No unknown style properties.

**Implemented 2026-10-18 (plan phase A):** the format as built is in
`modes/README.md` ("Screens"): the widgets and styles above, plus
comparisons, `!`, `&&`, `||`, the text filters `|clock`, `|upper`, `|int`,
a screen background, and the colours `contrast` and `{expression}`
(decision A10).  The Field Box reads the templates from its image, not
LittleFS (decision A11).

**Consequences:**
- One template format renders on both ESP32 (LVGL) and Android/iOS
  (Flutter).  Mode authors write templates once.
- The widget set is deliberately small to keep both renderers simple.
- The YAML subset parser on ESP32 is tiny; it does not pull in a
  full YAML library.
- Existing C screen functions remain as fallback during migration.
- The template format is extensible: new widget types can be added in
  future phases without breaking existing templates.

---

### ADR-P3-5: Android background survival

**Status:** Accepted

**Context:** An Android prop must survive hours of play without the OS
killing it.  The research identified four mechanisms: foreground service,
partial wake lock, battery optimisation exemption, and screen
management.  OEM battery management (Samsung, Xiaomi, Huawei) adds
extra restrictions.

**Decision:** Concrete architecture for background survival.

#### Foreground service (`atalaia_foreground` Kotlin plugin)

The `AtalaiaForegroundService` extends `android.app.Service` and is
started with `startForegroundService()`.  It holds:

1. The Dart game loop isolate (via `FlutterEngine`).
2. A partial wake lock (`PowerManager.PARTIAL_WAKE_LOCK`) tagged
   `atalaia:game_loop`.
3. A persistent notification in channel `atalaia_game` with:
   - Title: mode name + team colours
   - Body: game time remaining, or "running" if unlimited
   - Small icon: the Atalaia logo
   - Priority: `PRIORITY_LOW` (no sound/vibration)
   - Actions: none (the user taps the notification to return to the app)

The service is started when the prop role enters a game and stopped
when the game ends or the role is switched.  It is NOT started for the
player or GM roles (they do not need background survival).

The service type is `FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE`
(for BLE/USB pod connection) and `FOREGROUND_SERVICE_TYPE_LOCATION`
(for GPS position reporting).  Both are declared in the manifest.

#### Wake lock strategy

- **Partial wake lock:** acquired by the foreground service.  Keeps the
  CPU running.  This is the primary mechanism.
- **Screen:** managed separately (see below).
- **Wi-Fi lock:** `WifiManager.WifiLock` with `WIFI_MODE_FULL_HIGH_PERF`
  acquired when the prop joins a game over Wi-Fi.  Released when the
  game ends.

#### Battery optimisation exemption

At first launch of the prop role, the app requests exemption from
battery optimisation via
`ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`.  This is critical for
reliable wake locks on OEM Android skins.

If the user declines, the app shows a persistent warning and
instructions for manually exempting the app on their specific phone.
The app does NOT repeatedly prompt (Google Play policy prohibits it).

**OEM-specific guidance:**

The app includes a `BatteryExemptionGuide` screen that detects the
device manufacturer and shows tailored instructions:

| Manufacturer | Extra steps |
|-------------|-------------|
| Samsung | Settings > Battery > App power management > Unrestricted |
| Xiaomi/Redmi | Settings > Battery > App battery saver > No restrictions |
| Huawei/Honor | Settings > Battery > App launch > Manual (toggle off) |
| OnePlus/Oppo | Settings > Battery > Battery optimization > Don't optimize |
| Others | Generic "disable battery optimization" instructions |

These instructions are stored in the app, not fetched from the
internet, because the prop may be offline.

#### Screen management

| State | Screen | Wake lock | Trigger |
|-------|--------|-----------|---------|
| Active | Full brightness | `FLAG_KEEP_SCREEN_ON` | Game start, button press, NFC scan, IMU movement |
| Dimmed | 10% brightness | No screen flag | 30 seconds of inactivity |
| Off | Screen off | Partial wake lock only | 5 minutes of inactivity (configurable) |

Transitions:
- Active -> Dimmed: `WindowManager.LayoutParams.screenBrightness = 0.1f`
  after 30 s inactivity.
- Dimmed -> Off: `PowerManager.goToSleep()` or release
  `FLAG_KEEP_SCREEN_ON` after 5 min.
- Off/Dimmed -> Active: `PowerManager.wakeUp()` + full brightness on
  any of: button press (pod EVT), NFC scan, IMU movement detection,
  or touch.

The game loop continues regardless of screen state (held by the partial
wake lock in the foreground service).

#### Kiosk mode interaction

When kiosk mode is active (device owner + lock task), the screen
management still applies.  However, `goToSleep` is not called because
it can trigger the lock screen.  Instead, the screen brightness is set
to the minimum value that keeps the screen technically on but visually
dark.

**Consequences:**
- The foreground service with a partial wake lock is the primary
  survival mechanism.  It works on all Android versions >= 8.0.
- Battery exemption is requested once and never nagged.
- OEM-specific guidance is built into the app for the common
  manufacturers used in the airsoft/paintball community.
- Screen dimming saves power during long games while the game loop
  runs at full speed.
- The wake lock is tagged, so it is visible in `dumpsys power` for
  debugging.

---

### ADR-P3-6: Player position architecture

**Status:** Accepted

**Context:** Player positions flow from phones to the controller or site
server.  The server filters positions by role before distributing them.
The research identified GPS (outdoor), BLE beacons (indoor), and
temporary visibility (UAV sweep) as the three sources.

**Decision:**

#### Position report format

A position report is a JSON object sent from the player app to the
controller over WebSocket or HTTP:

```json
{
  "player_id": "p-abc123",
  "team": 1,
  "squad": 0,
  "lat": 38.7223,
  "lon": -9.1393,
  "accuracy_m": 5.0,
  "altitude_m": 42.0,
  "heading_deg": 180.0,
  "speed_mps": 1.5,
  "source": "gps",
  "beacon_id": null,
  "t": 1234567
}
```

For indoor BLE beacons, `source` is `"ble"`, `lat`/`lon` are omitted,
and `beacon_id` identifies the nearest beacon (which maps to a room or
zone in the controller's beacon registry).

#### Reporting interval

| Source | Default interval | Configurable range | Notes |
|--------|-----------------|-------------------|-------|
| GPS (outdoor) | 10 s | 5-60 s | `FusedLocationProviderClient` priority `PRIORITY_BALANCED_POWER_ACCURACY` |
| BLE beacon (indoor) | 5 s | 3-30 s | Scan for iBeacon/Eddystone, report strongest |
| GPS (UAV sweep active) | 2 s | -- | Temporarily increased during visibility events |

The interval is set by the controller in the game configuration and
pushed to clients at join time.

#### Transport

- **Field Wi-Fi (primary):** `POST /api/v1/positions` to the controller.
  Batched: up to 5 positions per request to reduce connection overhead.
- **4G (secondary):** same endpoint on the site server, which relays to
  the controller.
- Positions are NOT sent over LoRa (too much airtime; player tags with
  their own LoRa are a phase 4+ stretch goal).

#### Server-side visibility filter

The controller maintains a `VisibilityEngine` that filters positions
before sending them to each client:

```python
class VisibilityEngine:
    def visible_positions(self, viewer_role: str, viewer_team: int,
                          viewer_squad: int, all_positions: dict,
                          temp_visibility: dict) -> list[Position]:
        ...
```

Filtering rules (enforced server-side, never client-side):

| Viewer role | Sees positions of |
|------------|-------------------|
| Player | Own position only; own squad if mode allows (`squad_visible: true` in mode params) |
| Squad leader | Own squad members |
| VIP | Own escort team |
| Marshal | All players |
| GM | All players |
| Spectator | None (or all with 60 s delay, if configured) |

The filter is applied in the WebSocket handler: each client connection
is tagged with its role, team and squad.  The server sends position
updates only for players that pass the filter.

A modified app cannot bypass this: the server never sends positions the
client is not allowed to see.

#### Temporary visibility (UAV sweep)

A mode can grant temporary visibility as a game event:

```lua
-- In field.lua or node.lua:
field.send_all("visibility.grant", {
    team = "red",
    see_team = "blue",
    duration_s = 30,
    reason = "uav_sweep"
})
```

The controller's `VisibilityEngine` adds a time-limited override:
for 30 seconds, all red-team players see all blue-team positions.
When the override expires, visibility reverts to normal.

New events for visibility:

| Event | Data | Priority |
|-------|------|----------|
| `visibility.granted` | `{team, see_team, duration_s, reason}` | normal |
| `visibility.expired` | `{team, see_team, reason}` | normal |

#### Indoor BLE beacon registry

The controller maintains a beacon registry:

```json
{
  "beacons": [
    {"uuid": "FDA50693-A4E2-4FB1-AFCF-C28847DC5D9F", "major": 1, "minor": 1,
     "room": "lobby", "floor": 0, "x": 10.0, "y": 5.0},
    {"uuid": "FDA50693-A4E2-4FB1-AFCF-C28847DC5D9F", "major": 1, "minor": 2,
     "room": "corridor-a", "floor": 0, "x": 15.0, "y": 5.0}
  ]
}
```

The player app scans for iBeacon advertisements, identifies the
strongest beacon, and reports its `beacon_id` (major:minor) in the
position report.  The controller maps this to a room and floor.

Room-level granularity is sufficient for indoor sites.  Triangulation
from multiple beacons is NOT implemented in v1 (too unreliable with
walls and people).

#### GDPR

- Positions are stored in the controller's SQLite only for the duration
  of the game.
- When the game ends or is archived, positions are deleted unless the
  GM explicitly exports them.
- No position tracking outside active games.
- The privacy notice template includes position tracking.

**Consequences:**
- Server-side filtering is the primary security mechanism.  No client
  trust is required.
- GPS and BLE beacons use the same position report format; the
  controller handles both.
- Temporary visibility is a first-class feature, not a hack.  Modes
  can use it creatively (UAV sweeps, intel codes, hacked terminals).
- BLE beacons are standard iBeacon hardware; no custom firmware.
- Indoor positioning is room-level, not metre-level.  This is honest
  and sufficient for CQB sites.

---

### ADR-P3-7: Chrono data model

**Status:** Accepted

**Context:** Chrono check-in and spot checks require a data model for
replicas, readings, limit templates, and signed records.  The research
defined the flow and GDPR requirements.  This ADR freezes the schema.

**Decision:**

#### Chrono reading record

```json
{
  "reading_id": "uuid",
  "replica_id": "uuid",
  "player_id": "p-abc123",
  "type": "checkin",
  "velocity_mps": 102.5,
  "bb_weight_g": 0.20,
  "energy_j": 1.05,
  "chrono_id": "chrono-field-1",
  "marshal_id": "m-xyz789",
  "marshal_name": "Jose",
  "game_id": "g-001",
  "field_id": "field-cqb-porto",
  "timestamp": "2026-10-18T14:30:00Z",
  "signature": "base64-encoded-ed25519-signature"
}
```

`type` is one of: `checkin` (initial check-in), `spotcheck` (during
play), `retest` (after a failed check-in, adjusted and re-tested).

#### Replica registry

```json
{
  "replica_id": "uuid",
  "owner_player_id": "p-abc123",
  "type": "aeg",
  "class": "rifle",
  "make_model": "Tokyo Marui AK47",
  "registered_at": "2026-10-18T09:00:00Z",
  "tag_type": "nfc",
  "tag_uid": "04:A2:B3:C4:D5:E6:F7"
}
```

`type` enum: `aeg`, `gbb`, `hpa`, `bolt_action`, `dmr`, `sniper`,
`pistol`, `shotgun`.

`class` is a field-defined category that maps to an energy limit in the
limit template.

#### Limit template format

```yaml
# app/lib/chrono/limit_templates/portugal_apda.yaml
name: "Portugal (APDA/FPA)"
source: "Portuguese Airsoft Federation rules"
verified_date: "2026-01-15"
classes:
  rifle:
    max_energy_j: 1.14
    max_fps_020: 350
    med_m: 0
    fire_mode: "full_auto"
  dmr:
    max_energy_j: 1.88
    max_fps_020: 450
    med_m: 20
    fire_mode: "semi_only"
  sniper:
    max_energy_j: 2.81
    max_fps_020: 550
    med_m: 30
    fire_mode: "bolt_only"
  cqb:
    max_energy_j: 0.84
    max_fps_020: 300
    med_m: 0
    fire_mode: "full_auto"
```

`max_fps_020` is the equivalent FPS with 0.20 g BBs, provided for
convenience.  The authoritative limit is `max_energy_j`.

Fields start from a template and override any value.  The field's
customised limit set is stored in the controller's config.

#### Spot-check comparison algorithm

When a marshal takes a spot-check reading:

1. Compute energy: `E = 0.5 * (bb_weight_g / 1000) * velocity_mps^2`.
2. Look up the class limit from the field's active limit template.
3. Compare the highest reading against:
   a. The class limit (`max_energy_j`).  If exceeded: FAIL (over limit).
   b. The check-in energy plus tolerance (default 5%).  If exceeded:
      WARN (significant increase from check-in).
4. Result:
   - PASS: reading <= class limit AND reading <= check-in * 1.05.
   - WARN: reading <= class limit BUT reading > check-in * 1.05.
   - FAIL: reading > class limit.
5. On FAIL or WARN, emit `chrono.violation` to GM and marshals.

The tolerance percentage is configurable per field (default 5%).

#### Signed records (marshal account + Ed25519)

**Updated 2026-10-18 (P3-1, maintainer decision):** chrono signing
uses Ed25519, not HMAC-SHA256, in both phase 3 and phase 4, so phase 4
needs no migration.  Ed25519 survives password changes and lets other
fields verify records without a shared secret.

Each marshal holds an Ed25519 key pair, generated when the marshal
account is created (phase 4 site server) or when the marshal role is
first assigned on a controller (phase 3, stored in the controller's
SQLite and synced to the marshal's phone):

```
signature = Ed25519.sign(marshal_private_key, canonical_json(reading_without_signature))
```

The canonical JSON is the reading record with the `signature` field
removed, keys sorted alphabetically, no whitespace.  The marshal's
public key is stored alongside the account; any field that trusts the
marshal's public key can verify the signature without a shared secret.

Records are append-only: updates (retest after adjustment) create a new
record referencing the original `reading_id`, never modify it.

**Implemented 2026-10-19 (plan phase B):** `protocol/chrono-record.md`
specifies the canonical form exactly (numbers, strings, ranges), adds
`ref_reading_id` and makes `game_id` optional; one record per shot; shared
vectors `protocol/vectors/chrono_record.json` checked by the app's Dart and
the controller's Python (decisions B3-B6).

**Consistency with S1:** Ed25519 is used for application-level signing
throughout (modes, chrono, OTA checks); ESP32-S3 hardware secure boot
(RSA-3072 or ECDSA) is a separate decision.

#### GDPR retention and erasure

- **Default retention:** 12 months from the reading date.
- **Configurable:** the field operator sets the retention period in the
  site server config (minimum 1 day, maximum 10 years, default 12
  months).
- **Auto-delete:** a daily job on the site server deletes readings
  older than the retention period.  The player is not notified (the
  data is no longer needed).
- **Right of access:** players can view their own readings in the
  player app or via `GET /api/v1/players/{id}/chrono`.
- **Right of erasure:** players can request deletion of their readings
  via `DELETE /api/v1/players/{id}/chrono`.  The server deletes all
  readings for that player and returns a confirmation.  The replica
  registry entry is also deleted if the player requests it.
- **Data controller:** the field operator.
- **Data processor:** for hosted site servers, the Atalaia project (or
  its legal entity) under a written DPA.
- **Cross-field sharing:** off by default.  Each field opts in.
  Players are informed during registration.

**Consequences:**
- Readings are tamper-evident via Ed25519 signatures.  A marshal
  cannot edit a reading without the signature becoming invalid.
  Other fields can verify records using the marshal's public key.
- The comparison algorithm is deterministic and auditable.
- Limit templates are versioned and sourced; fields know when a
  template was last verified.
- GDPR compliance is built in from the start, not bolted on.
- Auto-delete prevents unbounded data accumulation.

---

### ADR-P3-8: New event types

**Status:** Accepted

**Context:** Phase 3 adds game modes, chrono check-in, player
positioning, and tamper detection.  Each requires new events in
`protocol/schema/events.yaml`.  Event IDs follow the existing scheme:
sequential integers starting after the last assigned ID.

**Updated 2026-10-18 (phase 2 handoff, decision R6):** Hold-All
Domination and Last Stand moved from phase 3 into the phase 2 mode
pack.  Their events (`holdall.scoring_start/stop`,
`laststand.countdown_start/cancel/defeated`, IDs 28-32) are allocated
by the mode pack, reusing the IDs and names from this ADR.  The mode
pack did not need `team.eliminated`, so ID 27 stays with phase 3 for
Respawn and Lives (reconciled with the built mode pack, 2026-10-18).  Phase 3 modes are now: Kill Confirmed, Respawn, Player
Check-in, **Money Factory**, and chrono check-in.

**Decision:** Add the following events to `events.yaml`.  IDs 28-32
are allocated by the phase 2 mode pack (holdall/laststand); phase 3
takes 25-27 and 33-41.

#### Game mode events (phase 3 -- IDs assigned after the mode pack)

| Event | ID | Priority | Data fields | Mode |
|-------|-----|----------|-------------|------|
| `kill.confirmed` | 25 | normal | `[player, team]` | Kill Confirmed |
| `kill.denied` | 26 | normal | `[player, team]` | Kill Confirmed (same-team scan, rejected) |
| `team.eliminated` | 27 | normal | `[team]` | Respawn and Lives (a team's lives run out) |
| `money.collected` | 33 | normal | `[player, team, amount]` | Money Factory |
| `money.deposited` | 34 | normal | `[player, team, amount]` | Money Factory |

Note: `holdall.*` (28-29) and `laststand.*` (30-32) are allocated
by the phase 2 mode pack and reuse the names and IDs from the original
version of this ADR.  Money Factory reuses the existing `amount` field
(key 6, integer points).

#### Player and chrono events

| Event | ID | Priority | Data fields | Feature |
|-------|-----|----------|-------------|---------|
| `chrono.checkin` | 35 | normal | `[replica, player, reading_mps, bb_g]` | Chrono check-in |
| `chrono.spotcheck` | 36 | normal | `[replica, player, reading_mps, bb_g]` | Chrono spot check |

Note: `chrono.violation` already exists at ID 17.

#### Position events

| Event | ID | Priority | Data fields | Feature |
|-------|-----|----------|-------------|---------|
| `visibility.granted` | 37 | normal | `[team, text]` | Temporary visibility |
| `visibility.expired` | 38 | normal | `[team, text]` | Temporary visibility expiry |

#### Tamper and system events

| Event | ID | Priority | Data fields | Feature |
|-------|-----|----------|-------------|---------|
| `node.tamper` | 39 | critical | `[reason]` | Kiosk mode broken, enclosure opened |
| `pod.connected` | 40 | telemetry | `[fw, tier]` | I/O pod linked |
| `pod.disconnected` | 41 | telemetry | `[reason]` | I/O pod link lost |

#### New data fields

The following data fields are added to the `data_fields` section:

| Field | Key | Type | Doc |
|-------|-----|------|-----|
| `see_team` | 29 | string | team whose positions become visible |
| `tolerance_pct` | 30 | number | chrono comparison tolerance percentage |

`duration_s` (key 28) and `holder` (key 31, the team holding the node)
were added by the phase 2 mode pack; phase 3's temporary visibility
reuses `duration_s`.  `amount` already exists (key 6).

#### Summary

Total new events (phase 3 only): 13 (IDs 25-27, 33-41; 28-32 owned
by the phase 2 mode pack).
Total new data fields: 2 (keys 29-30).

The existing event IDs 14 (`player.respawn`), 15 (`player.checkin`)
and 17 (`chrono.violation`) are already allocated and used as-is by
the phase 3 modes.

**Consequences:**
- Event IDs 25-27 and 33-41 are phase 3's (28-32 the phase 2 mode
  pack's).  Phase 4 starts at ID 42.
- All new events follow the established conventions: CBOR integer keys,
  standard priorities, data fields from the shared table.
- `protogen.py` must be run after updating `events.yaml` to regenerate
  codec tables.
- The new events are backward-compatible: older nodes ignore unknown
  event IDs (they pass through the codec as raw CBOR).

---

### ADR-P3-9: Security model for the player app

**Status:** Accepted

**Context:** The player app connects to the field controller or site
server.  It needs authentication, role-based data filtering, NFC tag
verification, kiosk tamper detection, and HTTPS on the field network.

**Decision:**

#### Token-based API authentication

The controller issues two token types (spec section 14):

- **Read token:** grants read access to scores, events, node state,
  and public game data.  Can be embedded in a QR code for spectators
  and scoreboards.  Generated with `secrets.token_urlsafe(32)`.
- **GM token:** grants write access to game control commands (start,
  pause, end, set_owner, message, reset).  Generated with
  `secrets.token_urlsafe(48)`.  Required for all mutating endpoints.

Tokens are passed in the `Authorization: Bearer <token>` header.

**Player app tokens:**

In addition to the existing read and GM tokens, the player app needs
per-player tokens for position reporting and chrono access:

- **Player token:** issued at game join (via QR scan or manual code
  entry).  Contains the player ID, team, squad, and role.  The token
  is a HMAC-SHA256-signed JSON payload (not a JWT -- simpler, no
  library dependency):

```json
{
  "player_id": "p-abc123",
  "team": 1,
  "squad": 0,
  "role": "player",
  "game_id": "g-001",
  "exp": 1729267200
}
```

The signature uses the controller's game key (already available).
The token expires when the game ends.

**Implemented 2026-10-19 (plan phase B):** `protocol/player-token.md`:
`apt1.<base64url(canonical JSON)>.<base64url(HMAC-SHA256)>`, `game_id` the
16-bit integer, squad and team 0 for none. The controller should key it with
a per-game token key of its own rather than the game key, which every box,
prop and join card holds (decision B8).

The controller validates the token on every request and extracts the
role for server-side filtering.

#### Role-based position filtering (server-side enforcement)

As defined in ADR-P3-6, position filtering is enforced server-side.
The player token's role determines what positions the WebSocket
connection receives.  The controller NEVER sends positions that the
client's role does not permit.

There is no client-side filtering.  The server sends only what the
client may see.  A modified app gains nothing.

#### NFC tag signing

NFC tags used in game modes (Kill Confirmed, Respawn, Player Check-in)
carry a signed payload:

```
tag_payload = player_id (variable) + team (1) + game_id (2)
tag_hmac = HMAC-SHA256(game_key, tag_payload) [truncated to 16 bytes]
total = tag_payload + tag_hmac
```

The HMAC is truncated to 16 bytes (128 bits) to fit on small NFC tags
(NTAG213 has 144 bytes of user data).  128-bit HMAC provides adequate
security for the game integrity threat model.

Tag verification:
1. Read the tag payload and HMAC.
2. Recompute HMAC with the game key.
3. Compare.  Reject if mismatch.

A cloned tag with a valid HMAC is still bound to the original player
and team.  The game key rotates every game, so tags from a previous
game are invalid.

The tag UID is logged but not trusted (UIDs can be cloned on some NFC
chips).

**Implemented 2026-10-18 (plan phase A):** `protocol/nfc-tag.md`. A
version byte goes first, the team is the 1-based team id (0 for none), and
the record is an NDEF MIME record `application/vnd.atalaia.tag` (decision
A3). The host checks the tag and the script gets `nfc.tag` (decision A4).

#### Kiosk tamper detection

When the app is in kiosk mode (lock-task):

1. The foreground service periodically checks `isLockTaskModeActive()`.
2. If lock-task mode is no longer active and the game is running, the
   service emits a `node.tamper` event with reason `"kiosk_broken"`.
3. The event reaches the controller and the GM console.

Physical tamper detection (enclosure switch, IMU shock) is handled by
the I/O pod: the pod sends `imu.shock` or a dedicated EVT frame, which
the phone translates to a `node.tamper` event.

#### Certificate handling for field-local HTTPS

**Updated 2026-10-18 (phase 2 handoff):** the join payload is at most
448 bytes (`protocol/join.md`); a DER-encoded CA certificate is
~800-1200 bytes and does not fit.  Keys 13-31 are reserved for
optional fields.

**Field controller (local network):**

The controller generates a self-signed CA at first setup:

1. Generate an Ed25519 root CA key and certificate (valid 10 years).
2. Generate a server certificate signed by the CA (valid 1 year, with
   the controller's hostname and IP as SANs).
3. Store both in the controller's config directory.

The CA certificate is distributed in two steps:
- The join payload (NFC/QR) carries only the **SHA-256 fingerprint**
  of the CA certificate in a reserved key (proposed key 13, needs an
  RFC 0001 amendment).
- On first connection over Wi-Fi, the phone fetches the full CA cert
  from `GET /api/v1/controller/ca` (no token needed, served over
  plain HTTP on port 8080).  The app checks the fingerprint against
  the one in the join payload, and trusts the CA for the duration of
  the game only.
- After the game ends, the trust is removed.

This approach avoids the join payload size limit while still binding
the CA trust to the join's HMAC-verified fingerprint.

**Site server (internet-facing):**

HTTPS with Let's Encrypt certificates.  HSTS enforced.  Standard
Flutter HTTP client with system CA trust.

**Certificate pinning:**

The app pins the site server's certificate (or its public key) for
HTTPS connections to the site server.  This prevents MitM attacks
on 4G networks.

Certificate pinning is NOT used for field-local connections (the
self-signed CA already provides trust, and pinning would break
when the CA is regenerated).

#### Play Integrity / SafetyNet

Optional, disabled by default.  The controller can require a Play
Integrity attestation from Android devices before allowing them to
join as props.  This is a competitive-event feature, not a default.

When enabled:
1. The app obtains an integrity token from the Play Integrity API.
2. The app sends the token with the join request.
3. The controller verifies the token with Google's servers (requires
   internet).
4. If verification fails, the controller rejects the join with a
   reason.

This is off by default because it requires Google Play Services and
internet access, neither of which is guaranteed on the field.

**Consequences:**
- Token-based auth is simple and stateless.  No session management
  on the controller.
- HMAC-signed player tokens are lightweight; no JWT library needed.
- Server-side position filtering is the primary defence against
  modified apps.
- NFC tag signing prevents casual tag forging; the truncated HMAC
  fits on small tags.
- Self-signed CA distribution during join solves the local HTTPS
  problem cleanly.
- Play Integrity is opt-in for competitive events, not a barrier for
  casual play.

---

### ADR-P3-10: iOS exclusions

**Status:** Accepted

**Context:** iOS cannot serve as a prop or controller (no kiosk mode,
no background NFC, no USB-OTG host, App Store restrictions on server
apps).  The research listed what iOS can and cannot do.  The build
system must exclude Android-only code from the iOS build.

**Decision:**

#### What is excluded from the iOS build

| Feature | Why excluded | Mechanism |
|---------|-------------|-----------|
| Prop role | No kiosk mode, no background NFC, no USB-OTG | `dart:io.Platform.isIOS` check at role selection; prop role button hidden on iOS |
| Controller role | No embedded MQTT broker, no USB-OTG host | Same check; controller role button hidden on iOS |
| `atalaia_kiosk` plugin | No equivalent API | Plugin not registered in iOS runner |
| `atalaia_foreground` plugin | Different background model | Plugin not registered in iOS runner; iOS uses background location and push notifications |
| `atalaia_ble_pod` plugin | BLE background limits | Plugin not registered in iOS runner |
| `atalaia_usb_pod` plugin | No USB-OTG host | Plugin not registered in iOS runner |
| dart:ffi core bindings | Not needed without prop/controller | Conditionally imported; stub on iOS |
| `libatalaia_core.so` | Not needed | Not compiled for iOS; no NDK equivalent needed |

#### What iOS includes

| Feature | Implementation |
|---------|---------------|
| Player role | Full Flutter UI: scores, map, messages, objectives, lives |
| GM role | WebView wrapping the GM console web app |
| QR scanning | Camera-based via `mobile_scanner` package |
| NFC reading (foreground only) | `CoreNFC` via Flutter `nfc_manager` package; user taps a button to scan |
| GPS positioning | `CLLocationManager` via `geolocator` package |
| BLE beacon scanning (foreground) | `CoreBluetooth` for iBeacon detection |
| Push notifications | APNs for GM messages and game events |

#### Build system

The app uses **build flavors** (not runtime checks alone) to exclude
code from the iOS binary:

1. `pubspec.yaml` declares platform-specific dependencies with
   `platforms:` keys.
2. Android-only plugins (`atalaia_kiosk`, `atalaia_foreground`,
   `atalaia_ble_pod`, `atalaia_usb_pod`) are registered only in the
   Android `MainApplication.kt`, not in iOS `AppDelegate.swift`.
3. Dart code uses conditional imports:

```dart
// app/lib/core/node_runner.dart
import 'node_runner_stub.dart'
    if (dart.library.io) 'node_runner_android.dart';
```

`node_runner_android.dart` contains the dart:ffi bridge and game loop.
`node_runner_stub.dart` is a no-op implementation used on iOS and web.

4. The iOS `Info.plist` requests only the permissions needed for the
   player and GM roles: camera (QR), NFC (foreground), location
   (GPS/beacons).  It does NOT request `UIBackgroundModes` for BLE or
   continuous location.

#### App Store compliance

The GPL-3.0-or-later licence applies to the app source.  The
app-store permission (`app/APP-STORE-PERMISSION.md`) grants the
additional permission required by Apple's App Store terms, per GPL
section 7.  This follows the same pattern as other GPL-licensed iOS
apps (VLC, GNU Go, etc.).

**Consequences:**
- The iOS binary is smaller than the Android binary (no native core
  library, no Android-only plugins).
- Role selection hides prop and controller on iOS; no dead code paths.
- Conditional imports keep the Dart code clean; no `if (Platform.isIOS)`
  scattered through business logic.
- The iOS app is a first-class citizen for players and GMs, not a
  degraded version.

---

### ADR-P3-11: CI strategy for Flutter

**Status:** Accepted

**Context:** Flutter adds four concerns to CI: Dart tests, Android
APK builds (including NDK cross-compilation of the core), integration
tests on an Android emulator, and an FFI stub library for testing
without the real core.

**Decision:**

#### FFI stub library

A C file `core/tests/stub.c` implements every function in
`core/include/atalaia/node.h` with deterministic, predictable
behaviour:

```c
#include "atalaia/node.h"

static atalaia_node_t stub_node;

atalaia_node_t *atalaia_node_create(const atalaia_node_config_t *cfg) {
    (void)cfg;
    return &stub_node;
}

void atalaia_node_destroy(atalaia_node_t *node) { (void)node; }

int atalaia_node_load(atalaia_node_t *node, const char *src,
                      size_t len, const char *name) {
    (void)node; (void)src; (void)len; (void)name;
    return 0;  /* success */
}

/* ... all other functions return success/default values ... */
```

This stub is built as `libatalaia_core_stub.so` (Linux),
`libatalaia_core_stub.dylib` (macOS), or
`atalaia_core_stub.dll` (Windows) using the standard CMake build:

```sh
cmake -S core -B build-stub -DATALAIA_SHARED=ON -DATALAIA_STUB=ON
cmake --build build-stub
```

The Dart tests load the stub library via an environment variable:

```dart
final lib = DynamicLibrary.open(
    Platform.environment['ATALAIA_CORE_LIB'] ?? 'libatalaia_core.so'
);
```

CI sets `ATALAIA_CORE_LIB` to the stub path.

#### CI jobs

Four new jobs in `.github/workflows/ci.yml`:

| Job | Runner | Steps | Purpose |
|-----|--------|-------|---------|
| `flutter-test` | `ubuntu-latest` | Build stub `.so`, `flutter test` | Dart unit + widget tests against the stub |
| `flutter-build-android` | `ubuntu-latest` | Flutter SDK + Android SDK + NDK, `flutter build apk --debug` | Verify NDK cross-compile of the real core + APK assembly |
| `flutter-integration` | `ubuntu-latest` + `reactivecircus/android-emulator-runner` | Start emulator, `flutter test integration_test/` | Full-app integration tests on an emulated device |
| `core-android-ndk` | `ubuntu-latest` + Android NDK | `cmake --preset android-arm64 && cmake --build` | Verify the core cross-compiles for ARM64 (fast, no Flutter) |

#### Test layers

| Layer | Tool | What it tests | Runs in CI |
|-------|------|--------------|------------|
| Dart unit tests | `flutter test` | FFI bindings (against stub), game loop logic, energy calculation, template parsing, capability proxy codec, position filtering logic | Yes |
| Widget tests | `flutter test` | UI components render correctly, role switching, screen templates, chrono keypad | Yes |
| Integration tests | `integration_test` package + emulator | Full-app flows: join game, receive events, display scores, switch roles. Mocked FFI and services | Yes |
| Core cross-compile | CMake + NDK | The real `.so` builds for Android ABIs | Yes |
| Mode tests | Existing `atalaia-dev` image | All 5 new modes tested via the simulator | Yes (existing pipeline) |

#### Emulator configuration

The Android emulator uses `reactivecircus/android-emulator-runner@v2`
with:
- API level 30 (Android 11)
- System image `system-images;android-30;google_apis;x86_64`
- No hardware acceleration (GitHub Actions runners do not support KVM)
- Timeout: 10 minutes for the emulator to boot

Hardware features (NFC, BLE, GPS) are mocked in integration tests
using platform channel mocks.

#### Capability proxy test vectors

Shared test vectors in `protocol/vectors/capability_proxy.yaml` are
tested in both Dart (`app/test/pod/codec_test.dart`) and C
(`firmware/esp32/test/test_proxy_codec.c`) to ensure encoding
compatibility.

**Consequences:**
- The FFI stub allows Dart tests to run on any platform (Linux, macOS,
  Windows) without cross-compiling the real core.
- `flutter build apk --debug` in CI catches NDK integration issues
  on every PR.
- Integration tests on an emulator exercise the full Flutter app
  without real hardware.
- The existing core and mode test pipeline is unchanged.
- Capability proxy codec compatibility is enforced by shared vectors.

---

### ADR-P3-12: Embedded MQTT broker for the Android controller

**Status:** Accepted

**Context:** The Raspberry Pi controller uses Mosquitto as a system
service (ADR-P2-5).  On Android, installing a system service is not
possible.  The Android controller role needs an embedded MQTT broker
for local clients (scoreboards, custom integrations) to subscribe to
game events.

**Decision:** Use **HiveMQ MQTT Client for Dart** as an MQTT client
library, combined with a **minimal embedded broker implemented in
Dart** for the Android controller role.

#### Why not aedes or Mosquitto

- **aedes** (Node.js): requires Node.js on Android, which is not
  practical.  There is no Dart equivalent of aedes.
- **Mosquitto (native):** would require compiling Mosquitto for Android
  and running it as a native process.  Possible but complex, adds a
  C dependency, and may conflict with Android's process model.
- **Third-party Dart MQTT broker packages:** no mature, well-tested
  Dart MQTT broker exists as of 2026.

#### Embedded broker architecture

A minimal MQTT 3.1.1 broker written in Dart, limited to the features
Atalaia needs:

```dart
class AtalaiaEmbeddedBroker {
    final int port;  // default 1883
    final Map<String, List<SubscriptionCallback>> _subscriptions = {};

    Future<void> start();
    Future<void> stop();
    void publish(String topic, Uint8List payload, {int qos = 0});
}
```

Supported MQTT features:
- CONNECT / CONNACK
- PUBLISH / PUBACK (QoS 0 and 1)
- SUBSCRIBE / SUBACK
- UNSUBSCRIBE / UNSUBACK
- PINGREQ / PINGRESP
- DISCONNECT

NOT supported (not needed for Atalaia):
- QoS 2 (exactly once)
- Retained messages
- Last Will and Testament
- Authentication (the broker runs on localhost; access is via the local
  network only, protected by the field controller's token auth)
- TLS (localhost only; the REST API handles HTTPS)
- Persistent sessions

#### Scope and limitations

The embedded broker is minimal: it handles at most 20 concurrent
connections and publishes at most 100 messages/second.  These limits
are well above what a game needs (5-10 scoreboards, ~1 event/second).

The broker runs in the same Dart isolate as the controller logic (not
in the game loop isolate).  It listens on `localhost:1883` by default,
or on the device's Wi-Fi IP when the controller is hosting a Wi-Fi AP.

#### Topic structure

The same MQTT topic structure as the Mosquitto-based Pi controller:

```
atalaia/game/{game_id}/events        -- all game events (JSON)
atalaia/game/{game_id}/scores        -- score updates (JSON)
atalaia/game/{game_id}/nodes/{id}    -- per-node state (JSON)
atalaia/game/{game_id}/time          -- TIME beacon (JSON)
```

#### Code size

The minimal broker adds ~500-800 lines of Dart.  The MQTT 3.1.1
protocol is simple enough that a purpose-built broker is smaller and
more reliable than importing a heavyweight library.

#### Fallback for the Pi controller

On the Raspberry Pi, Mosquitto remains the broker.  The Python
controller connects to it as a client (unchanged from ADR-P2-5).
The embedded Dart broker runs ONLY on Android.

**Consequences:**
- The Android controller is self-contained: no external MQTT daemon.
- The embedded broker is intentionally minimal; it covers Atalaia's
  use case (score publishing, event streaming) without attempting to
  be a general-purpose MQTT broker.
- Scoreboards and custom integrations use the same MQTT topic
  structure on both Pi and Android controllers.
- The 500-800 lines of Dart are easy to maintain and test.
- If a mature Dart MQTT broker package emerges, the embedded broker
  can be replaced without changing the topic structure or client code.

---

## Phase 2 handoff (2026-10-18)

Phase 2 plan phases A-E are implemented and pushed (commit `771fd90`).
The following assumptions from this ADR were re-checked against the
implemented interfaces.

| Assumption | Status | Resolution |
|-----------|--------|-----------|
| B2: `field_ops` pointer in `atalaia_node_config_t` | **Holds** | Exists; runs on the controller via ctypes. |
| B4: USB modem framing = type+len+payload | **Changed** | Now 0xA5 sync + type + len + payload + CRC-16/CCITT-FALSE. Pod must adopt the same (ADR-P3-2 updated). RADIO_RX carries epoch. |
| B6/B7: REST API + WebSocket stable | **Holds with additions needed** | 17+ endpoints exist with bearer tokens. Phase 3 must add: `POST /api/v1/positions`, player tokens, role-filtered WS streams. |
| B10: Join payload format | **Changed** | Version byte + CBOR map + HMAC-SHA256, max 448 bytes. Keys 13-31 reserved. Field join key (not controller-only). NFC is NDEF MIME `application/vnd.atalaia.join`; text is `atalaia:join:` + base64url. QR pushes nothing to boxes (E3). CA cert does not fit; use fingerprint + Wi-Fi fetch (ADR-P3-9 updated). |
| B13: Time sync | **Holds** | Slew <=5%, step at >=500 ms, hold when ahead, follow highest-term TIME. Android can reuse `field_link.c` logic. |
| C5: Channel hopping | **Superseded** | One shared game channel per game (default 869.525 MHz, g2, 10% DC, 500 mW ERP), carried in join payload key 5 `channel_hz`. No channel hopping. |
| P3-1: Chrono signing | **Changed** | Ed25519 per marshal, not HMAC-SHA256 (ADR-P3-7 updated). |
| R6: Hold-All and Last Stand | **Moved** | Into the phase 2 mode pack. Phase 3 modes: Kill Confirmed, Respawn, Player Check-in, Money Factory, chrono check-in (ADR-P3-8 updated). |
| S1: Ed25519 for app signing | **Holds** | ESP32-S3 hardware secure boot is RSA-3072/ECDSA only; Ed25519 for application-level signing. |
| D8: Codec corrections | **Noted** | Dart codecs must match schema-exact C payloads: HELLO capabilities is an array, STATE counters/CLAIM acks are maps, CMD params is text-keyed map (JSON <=127 bytes), required fields always encoded. |
| E21: GPS on Field Box | **Not supported** | GNSS header pins used by display/buttons. Revisit in phase 4. I/O pod or phone GPS only. |

---

## Constraints for Planning

The planning phase must respect the following constraints derived from
the decisions above:

1. **Game loop on a dedicated isolate.** The Dart FFI game loop runs in
   its own isolate; the UI isolate never calls `atalaia_node_*`
   functions.  Communication is via `SendPort`/`ReceivePort`.

2. **`NativeCallable.listener` for all callbacks.** Do not use
   `Pointer.fromFunction`.  Callbacks post messages to the isolate.

3. **Gradle-integrated NDK build.** The core is cross-compiled via
   `externalNativeBuild` in `build.gradle.kts`.  CI verifies this
   with `flutter build apk --debug`.

4. **Capability proxy protocol v1 is frozen.** The frame format
   (0xA5 sync + type + length + payload + CRC-16, matching the modem),
   GATT UUIDs, and characteristic layout are fixed.  Changes require
   a protocol version bump.

5. **Pod firmware is a Kconfig variant.** `CONFIG_ATALAIA_POD_MODE`
   disables Lua, LVGL, preset store and game logic.  It enables BLE
   GATT server, USB CDC, capability proxy, and the radio stack.

6. **Declarative templates are YAML.** Templates live in
   `modes/*/assets/screens/*.yaml`.  Both LVGL (ESP32) and Flutter
   render the same templates.  The LVGL renderer uses a minimal YAML
   subset parser, not a full library.

7. **Foreground service for Android props.** The game loop runs inside
   a foreground service with a partial wake lock.  Battery exemption
   is requested once at setup.

8. **Screen dimming, not sleeping.** In kiosk mode, the screen dims
   but is not turned off (to avoid the lock screen).  The game loop
   runs regardless of screen state.

9. **Server-side position filtering only.** The controller NEVER sends
   positions a client is not allowed to see.  There is no client-side
   filtering.

10. **Positions over Wi-Fi or 4G, never LoRa.** Player positions are
    sent to the controller over the network, not over LoRa.

11. **Ed25519 for chrono records; HMAC for NFC tags.** Chrono readings
    are signed with the marshal's Ed25519 private key (P3-1, consistent
    with phase 4).  NFC tags are signed with the game key (truncated
    16-byte HMAC-SHA256).

12. **Event IDs 25-27 and 33-41 for phase 3.** IDs 28-32 are owned by
    the phase 2 mode pack (holdall/laststand).  Phase 4 starts at ID 42.
    Data keys 29-30 are phase 3's; 28 and 31 are the mode pack's.

13. **iOS excludes prop and controller roles.** Conditional imports
    and build flavors keep iOS clean.  No `dart:ffi` core bindings
    on iOS.

14. **FFI stub library for Dart tests.** `core/tests/stub.c` with
    `ATALAIA_STUB=ON` builds a stub `.so` for Dart testing on any
    platform.

15. **Four new CI jobs.** `flutter-test`, `flutter-build-android`,
    `flutter-integration`, `core-android-ndk`.

16. **Embedded MQTT broker on Android only.** A minimal Dart MQTT
    3.1.1 broker for the controller role.  QoS 0 and 1 only, no
    auth, localhost.  The Pi uses Mosquitto (unchanged).

17. **Shared capability proxy test vectors.** Vectors in
    `protocol/vectors/capability_proxy.yaml` tested in both Dart
    and C.

18. **GDPR retention for chrono records.** Default 12 months,
    configurable, auto-delete.  Right of access and erasure via API.

19. **Limit templates are YAML files.** Shipped in
    `app/lib/chrono/limit_templates/`, versioned, with source and
    date.

20. **All phase 3 modes are single-node.** Kill Confirmed, Respawn,
    Player Check-in and Money Factory are single-node modes with no
    `field.*` dependency.  Hold-All Domination and Last Stand moved
    to the phase 2 mode pack (decision R6).

21. **BLE beacons are standard iBeacon hardware.** No custom firmware
    for beacons.  Room-level positioning, not metre-level.

22. **Self-signed CA fingerprint in join, cert over Wi-Fi.** The join
    payload carries a SHA-256 fingerprint (proposed key 13); the app
    fetches and verifies the full cert over Wi-Fi.  Needs an RFC
    amendment for key 13.

23. **SPDX headers on every file.** Files under `app/` use
    `GPL-3.0-or-later`.  Files under `controller/` use
    `AGPL-3.0-or-later`.  Documentation uses `CC-BY-SA-4.0`.

24. **Minimum Android API 26.** All Android features require API 26
    (Android 8.0) or higher.
