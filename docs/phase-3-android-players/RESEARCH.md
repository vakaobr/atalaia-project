<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 3 -- Android and Players: Research

Gate: **one game mixes ESP32 and Android props without issues.**

## Summary

**Risk:** Medium

Phase 3 adds the Flutter app (Android + iOS), the ESP32 I/O pod, five
new game modes (four requiring field scripts), chrono check-in, player
positioning, and the declarative screen template format deferred from
phase 1.  The scope is large but nearly every piece builds on APIs and
patterns that phase 2 delivers.  The highest risk is the dart:ffi
bridge to the C core on Android, which has no prior art in this project
and introduces a new toolchain (Flutter + Android NDK).  The I/O pod
hardware design also carries risk because it has not been prototyped.

---

## 1. Flutter app architecture

### dart:ffi bridge to the shared C core

The C core (`core/`) already builds as a shared library
(`libatalaia_core.so`) with CMake and `-DATALAIA_SHARED=ON`
(`core/CMakeLists.txt`).  For Android, the same sources are
cross-compiled to `libatalaia_core.so` for each ABI (arm64-v8a,
armeabi-v7a, x86_64) using the Android NDK's CMake toolchain file.
Flutter's FFI plugin mechanism (`ffigen` or manual bindings) wraps the
C API from `core/include/atalaia/node.h`.

Key integration points:

- **`atalaia_node_create` / `_destroy` / `_input` / `_advance`** are
  called from Dart through `dart:ffi` `DynamicLibrary.open` +
  `lookupFunction`.
- **Callbacks** (`event`, `command`, `log`) use `Pointer<NativeFunction>`
  with `NativeCallable.listener` (Dart 3.1+).  Because callbacks run
  synchronously in the C core and must not call back into the same node,
  the Dart callback posts events to an isolate message port; the Flutter
  UI picks them up asynchronously.
- **Memory management:** the Dart FFI layer allocates strings with
  `calloc` from `package:ffi`, passes them to C, and frees them after the
  call returns.  The core's allocator stays the default (`realloc`/`free`)
  on Android; PSRAM is irrelevant.
- **Threading:** `atalaia_node_advance` and `atalaia_node_input` must be
  called from the same thread.  On Android, a dedicated Dart isolate
  (or `compute`) runs the game loop at 100 Hz, matching the ESP32 shell's
  tick rate.  The UI isolate communicates via `SendPort`/`ReceivePort`.

The simulator's Python ctypes wrapper (`simulator/atalaia_sim/core.py`)
is the reference for the complete set of C functions to wrap.  The Dart
FFI bindings mirror it.

### Cross-compilation of the core for Android

A new CMake preset or Gradle integration builds the core for Android:

```
app/android/src/main/jniLibs/
    arm64-v8a/libatalaia_core.so
    armeabi-v7a/libatalaia_core.so
    x86_64/libatalaia_core.so    # for emulators
```

Option A (recommended): a Gradle `externalNativeBuild` block in the
app's `build.gradle.kts` that invokes CMake with the NDK toolchain.
This integrates with the standard Flutter Android build and lets CI
build everything with `flutter build apk`.

Option B: a separate CMake cross-compile step (like the ESP-IDF build)
that produces the `.so` files, copied into `jniLibs/` before the
Flutter build.  Simpler but less integrated.

### Roles within the app

The app is one Flutter codebase with a role selector at startup:

| Role | Platforms | What it runs |
|------|-----------|-------------|
| Prop | Android only | C core via FFI, kiosk mode, foreground service, pod link |
| Controller | Android only | C core for `field.lua` via FFI, embedded MQTT broker, REST API, radio modem via USB |
| GM | Android + iOS | Wraps the web-based GM console in a WebView with native push |
| Player | Android + iOS | Player views (section 4 of this document) |

Prop and controller roles are excluded from the iOS build using
conditional compilation and the `platform` checks in the manifest.

### Kotlin plugins (Android-only features)

These are implemented as Flutter platform channels (MethodChannel) with
Kotlin implementations:

| Plugin | Purpose | Android APIs |
|--------|---------|-------------|
| `atalaia_kiosk` | Lock-task / kiosk mode, device owner provisioning | `DevicePolicyManager`, `startLockTask()` |
| `atalaia_foreground` | Foreground service with persistent notification, wake lock, battery optimisation exemption | `Service`, `PowerManager`, `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` |
| `atalaia_ble_pod` | BLE GATT client for the I/O pod | `BluetoothGatt`, `BluetoothGattCallback` |
| `atalaia_usb_pod` | USB-OTG CDC serial for the I/O pod | `UsbManager`, `UsbDeviceConnection` |
| `atalaia_nfc` | NFC tag read/write (NDEF, UID) | `NfcAdapter`, `Tag`, `Ndef` |

### Files to touch

- `app/lib/ffi/` -- Dart FFI bindings to the C core
- `app/lib/core/` -- game loop isolate, node wrapper
- `app/android/app/build.gradle.kts` -- NDK cross-compile of the core
- `app/android/app/src/main/kotlin/.../` -- Kotlin plugins
- `app/lib/ui/` -- Flutter UI for all roles
- `app/pubspec.yaml` -- dependencies

### Patterns to follow

- The simulator's `core.py` ctypes wrapper is the reference for the FFI
  surface.
- The ESP32 shell's `node_runner` pattern (create node, load mode, tick
  at 100 Hz, dispatch commands) is replicated in Dart.
- Kotlin plugins follow the standard Flutter platform channel pattern.

---

## 2. Android prop shell

### Capabilities mapped from phone hardware

| Phone hardware | Capability type | Notes |
|---------------|----------------|-------|
| GPS | `gps` | `FusedLocationProviderClient`, 1-10 s interval |
| NFC | `nfc` | Android NFC is foreground-dispatch only; read tags, write NDEF |
| IMU (accelerometer + gyroscope) | `imu` | `SensorManager`, detect movement/shock/tilt |
| Camera | `qr` | `CameraX` or `mobile_scanner` for QR scanning |
| Speaker | `audio` | `MediaPlayer` or `AudioTrack` for clips and TTS |
| Touchscreen | `button`, `keypad`, `display` | Touch buttons map to `team_input`; on-screen keypad; Flutter UI as display |
| Battery | `battery` | `BatteryManager` broadcast |

### Background limits

Android kills background apps aggressively.  The prop must survive hours
of play:

1. **Foreground service** with a persistent notification.  This is the
   primary mechanism.  The service holds the game loop (the Dart
   isolate running `atalaia_node_advance` at 100 Hz).
2. **Partial wake lock** to prevent CPU sleep.  Acquired by the
   foreground service.
3. **Battery optimisation exemption** requested at setup via
   `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`.  Required for reliable
   wake locks on many OEM Android skins (Samsung, Xiaomi, Huawei).
4. **Screen management:** the prop UI dims after 30 s of inactivity and
   wakes on button press, NFC scan, or IMU movement.  Uses
   `FLAG_KEEP_SCREEN_ON` while active; releases it during dim.

### Joining the field

An Android prop joins the field in one of two ways:

- **Wi-Fi** (direct): connects to the controller's Wi-Fi AP or the
  venue network.  Receives game events over the controller's REST/WS
  API.  No LoRa radio needed.
- **LoRa via I/O pod** (section 3): the pod's SX1262 radio appears as
  a proxied transport.  The phone sends/receives Skirmesh-RF packets
  through the pod's BLE or USB-OTG link.

When joining over Wi-Fi, the phone receives the join payload via
`POST /api/v1/nodes/{id}/join` (same as QR join in phase 2).  Over an
I/O pod, the phone reads a join NFC card directly using its NFC
hardware, or receives the payload from the pod's NFC reader.

### Kiosk / lock-task mode

For dedicated props (phones screwed into enclosures), Android's
lock-task mode prevents players from leaving the app:

1. The phone is provisioned as a **device owner** using `adb dpm
   set-device-owner`.  This is a one-time setup step for dedicated
   props.
2. The app calls `startLockTask()` to enter kiosk mode: the home
   button, recent apps, and notifications are disabled.
3. Exit requires the admin PIN (entered on the keypad or a hidden
   long-press gesture).

Device owner provisioning is documented in a setup guide.  It requires a
factory-reset phone or an NFC-based device provisioning package.

### Minimum API level

API 26 (Android 8.0).  This covers most phones from 2017 onward.
Key APIs available at this level: `NotificationChannel` (required for
foreground service), `BluetoothLeScanner`, `NfcAdapter`, `UsbManager`.

### Files to touch

- `app/android/app/src/main/kotlin/.../KioskPlugin.kt`
- `app/android/app/src/main/kotlin/.../ForegroundServicePlugin.kt`
- `app/lib/prop/` -- prop role UI and logic
- `app/lib/prop/capability_mapper.dart` -- maps phone sensors to
  capabilities

---

## 3. I/O pod

### Purpose

An Android phone has no LoRa radio, no big physical buttons, no LED
ring and no siren.  The I/O pod is a small ESP32 board that lends these
capabilities to the phone over BLE or USB-OTG.  To scripts running on
the phone, the pod's buttons, LEDs, siren and radio appear as local
capabilities.

### Hardware design

**Board:** Heltec WiFi LoRa 32 V4.3 (same board as the field box and
the USB radio modem).  The SX1262 radio, BLE, and USB-C are all
on-board.  If the Heltec V4.3 is too large for a pod enclosure, a
smaller ESP32-S3 + SX1262 module (e.g., Waveshare SX1262 LoRa HAT
ESP32-S3 Mini) is an alternative.

**I/O components:**

| Component | Purpose | Interface |
|-----------|---------|----------|
| 2-4 arcade buttons (60 mm, with integrated LEDs) | Team input, capture | GPIO with debounce |
| WS2812 LED ring (12-24 LEDs) | Team colour display, progress | RMT (same driver as field box) |
| Piezo buzzer or small speaker (MAX98357A) | Audio feedback, siren | GPIO tone or I2S |
| SX1262 LoRa radio (on-board) | LoRa field mesh | SPI (same driver as field box) |
| USB-C (on-board) | USB-OTG link to phone | USB CDC serial |
| BLE (on-board) | Wireless link to phone | BLE GATT server |
| PN532 NFC reader (optional) | Tag reading at the pod | I2C |

**Approximate BOM (pod only, excl. phone):**

| Part | Est. cost |
|------|----------|
| Heltec WiFi LoRa 32 V4.3 | EUR 18 |
| 2x 60 mm arcade buttons | EUR 4 |
| WS2812 ring (12 LEDs) | EUR 3 |
| Piezo buzzer | EUR 1 |
| PN532 NFC module (optional) | EUR 5 |
| Enclosure, cable glands, wiring | EUR 5 |
| **Total** | **~EUR 31-36** |

### Capability proxy protocol

The spec (section 7) defines four frame types: IDENT, EVT, CMD, ACK.
The pod runs as a capability proxy: it does not run Lua scripts.  Its
firmware is a build variant of the node firmware (`CONFIG_ATALAIA_POD_MODE=y`),
similar to the modem mode defined in ADR-P2-4.

**Over BLE GATT:**

The pod acts as a GATT server with a custom service:

| Characteristic | UUID | Direction | Purpose |
|---------------|------|-----------|---------|
| Pod TX | `0001` | Notify (pod -> phone) | EVT frames (button press, NFC tag) and IDENT |
| Pod RX | `0002` | Write (phone -> pod) | CMD frames (LED colour, tone, radio TX) |
| Pod Status | `0003` | Read + Notify | Battery, RSSI, radio state |

BLE 4.2 MTU of 247 bytes fits all capability proxy frames.  BLE 5.0
extended MTU (512 bytes) covers radio packets (max 217 bytes) with
headroom.

**Over USB-OTG:**

Same length-prefixed binary framing as the USB radio modem (ADR-P2-4):
`type (1) + length (2) + payload (up to 256)`.  The pod appears as
`/dev/ttyUSBx` on the phone.  USB is preferred for latency (< 1 ms vs
BLE's 7.5-15 ms connection interval) and reliability.

**Radio passthrough:**

For LoRa, the pod acts as a radio modem (identical to the USB radio
modem for the Pi controller, ADR-P2-4).  The phone sends TX frames
with plaintext payloads; the pod encrypts with AES-CCM and transmits.
The pod decrypts received packets and sends RX frames to the phone.
The game key is sent to the pod over the BLE/USB link at join time.

**Firmware variant:**

A Kconfig variant (`CONFIG_ATALAIA_POD_MODE=y`) disables Lua, LVGL,
preset store, and the game loop.  It enables:

- Button/NFC/LED/audio HAL (same as node firmware)
- Radio task (same as node firmware)
- BLE GATT server task
- USB CDC serial task
- Capability proxy framing

### How pod capabilities appear to scripts

The phone's Dart FFI layer merges local capabilities (GPS, camera,
touchscreen) with proxied capabilities from the pod (buttons, LEDs,
radio, NFC).  The `atalaia_node_t` on the phone sees a unified
capability list.  When a script calls `cap("ring"):fill("red")`, the
command dispatch routes it to the pod via BLE/USB.  When the pod's
button is pressed, the EVT frame arrives and is injected into the node
via `atalaia_node_input`.

Latency budget: BLE connection interval 7.5-15 ms + frame processing
~1 ms = 8.5-16 ms.  For button press to script reaction, this is
imperceptible.  USB-OTG adds < 2 ms.

### Files to touch

- `firmware/esp32/main/Kconfig.projbuild` -- `CONFIG_ATALAIA_POD_MODE`
- `firmware/esp32/main/pod/` -- pod-specific tasks (BLE GATT, capability
  proxy)
- `app/lib/pod/` -- Dart BLE/USB client for the pod
- `app/android/app/src/main/kotlin/.../BlePodPlugin.kt`
- `app/android/app/src/main/kotlin/.../UsbPodPlugin.kt`

---

## 4. New game modes

All new modes follow the existing pattern: `modes/<mode>/mode.yaml`,
`node.lua`, optional `field.lua`, `tests/*.yaml`.

### 4.1 Hold-All Domination

**Concept:** Points only accrue while one team holds ALL boxes
simultaneously.  Encourages aggressive play across the field.

**Scripts:**
- `node.lua`: standard domination capture logic (reuse/adapt from
  `modes/domination/node.lua`); emits `zone.captured`, `zone.neutralized`.
- `field.lua`: runs on the controller; subscribes to `zone.captured`
  from all nodes; checks `field.common_owner(field.nodes("zone"))`;
  starts/stops a scoring timer based on hold-all status; emits
  `holdall.scoring_start` / `holdall.scoring_stop`.

**Capabilities:** `team_input` (required), `team_display` (optional).

**Dependencies:** `state.field{}` and `field.*` Lua API (phase 2C).

**Tests:**
- Two zones, red captures both, scores accrue; blue captures one, scoring
  stops; red recaptures, scoring resumes.
- Edge: one zone neutral, no scoring.
- Game end freezes.

### 4.2 Last Stand

**Concept:** A team holding only 1 of N flags (typically 3) enters a
"last stand" countdown.  If the countdown expires, that team loses.
Encourages recapture rather than turtling.

**Scripts:**
- `node.lua`: standard domination capture.
- `field.lua`: tracks per-team zone count via `field.nodes("zone")` and
  `field.owner(node)`; when a team holds exactly 1 zone, starts a
  configurable countdown (e.g., 120 s); if the team captures a second
  zone before the countdown expires, the countdown is cancelled; if it
  expires, emits `laststand.defeated{team}`.

**Params:** `countdown_s` (default 120), `min_zones_safe` (default 2).

**Dependencies:** `state.field{}`, `field.*` (phase 2C).

**Tests:**
- Three zones; red holds 1, countdown starts; red captures a second,
  countdown cancels.
- Countdown expires, `laststand.defeated` emitted.

### 4.3 Kill Confirmed

**Concept:** Each team scores by scanning the opposing team's NFC tags.
Scanning a tag removes one point from the tagged team.  Encourages
tagging "confirmed kills" at the prop.

**Scripts:**
- `node.lua`: on `nfc.tag`, checks the tag's team payload; if the team
  differs from the scanning team, `score.add(scanning_team, 1, "kill_confirmed")`
  and `score.add(tagged_team, -1, "kill_denied")` (negative delta via
  `score.delta` event).  Emits `kill.confirmed{scanner_team, victim_team}`.

**Capabilities:** `nfc` (required), `team_display` (optional).

**No field script needed** -- single-node logic.

**NFC tag format:** tags carry a signed payload with `{team, player_id}`.
The script verifies the signature using the game key.

**Tests:**
- Red scans blue tag: red +1, blue -1.
- Same-team scan: no effect.
- Invalid/unsigned tag: rejected.

### 4.4 Respawn and Lives

**Concept:** Each team (or player) has a limited number of lives.
Players check in at a respawn prop to use a life.  When lives run out,
the team (or player) is eliminated.

**Scripts:**
- `node.lua`: on `nfc.tag` or `qr.scan`, identifies the player/team;
  decrements the team's life counter; emits `player.respawn{player_id,
  team, lives_left}`.  If lives reach 0, emits
  `team.eliminated{team}`.
- Integration with the player app: the player's app shows their lives
  and a respawn timer (if configured).

**Params:** `lives_per_team` (default 20), `lives_per_player` (optional),
`respawn_cooldown_s` (default 30).

**Capabilities:** `nfc` or `qr` (required).

**Tests:**
- Team with 3 lives: 3 respawns, 4th rejected with `team.eliminated`.
- Per-player lives mode.
- Cooldown enforcement.

### 4.5 Player Check-in

**Concept:** Count individual players via NFC or QR at a prop.  Used
at the start of a game to register teams.

**Scripts:**
- `node.lua`: on `nfc.tag` or `qr.scan`, reads player/team info;
  emits `player.checkin{player_id, team}`.  Maintains a count per
  team and displays it.  Duplicate scans within a configurable window
  are ignored.

**Capabilities:** `nfc` or `qr` (required), `display` (optional).

**Tests:**
- Three players check in, counts correct.
- Duplicate rejected.

### Files to touch (all modes)

- `modes/hold_all_domination/` -- `mode.yaml`, `node.lua`, `field.lua`,
  `tests/`
- `modes/last_stand/` -- same structure
- `modes/kill_confirmed/` -- `mode.yaml`, `node.lua`, `tests/`
- `modes/respawn/` -- `mode.yaml`, `node.lua`, `tests/`
- `modes/player_checkin/` -- `mode.yaml`, `node.lua`, `tests/`

### Patterns to follow

- Manifest structure: copy from `modes/bomb/mode.yaml`.
- Test format: `modes/README.md`.
- `field.lua` uses the `field.*` API from phase 2C.  The simulator's
  `FieldController` class exercises field scripts.

---

## 5. Chrono check-in

### Replica registry

Each replica (airsoft gun, paintball marker) is identified by an NFC
sticker or QR label.  The registry stores:

| Field | Type | Notes |
|-------|------|-------|
| `replica_id` | string | Unique ID (UUID or serial) |
| `owner_player_id` | string | Player who owns the replica |
| `type` | enum | AEG, GBB, HPA, bolt-action, DMR, sniper |
| `class` | string | Field-defined class (e.g., "rifle", "DMR", "sniper") |
| `make_model` | string | Optional: manufacturer and model |
| `registered_at` | datetime | First registration time |

### Check-in flow

1. Marshal scans the replica's NFC tag (or QR label) using the
   marshal's phone (player app in marshal role).
2. If unregistered, the marshal registers it: enters type, class,
   optional make/model.
3. Marshal fires 3-5 shots through the chronograph using field-provided
   BBs of known weight.
4. For each shot, the marshal enters the velocity reading on a large,
   outdoor-readable keypad screen in the app.
5. The app computes energy: `E = 0.5 * m * v^2` (m in kg, v in m/s).
6. The app stores: velocity (m/s), BB weight (g), computed energy (J),
   chronograph ID, marshal ID, timestamp.
7. The app checks the highest reading against the limit for the
   replica's class and the site's field profile (CQB sites have lower
   limits).
8. Pass: a green badge appears on the player's app and on any marshal's
   scan for the rest of the day.
9. Fail: a red badge; the player must adjust the replica and re-test.

### Limit templates

The project ships templates for common national rule sets:

| Template | Source | Example limits |
|----------|--------|---------------|
| Portugal (APDA/FPA) | Portuguese Airsoft Federation rules | Rifle 1.14 J (350 fps/0.20g), DMR 1.88 J (450 fps/0.20g), Sniper 2.81 J (550 fps/0.20g), CQB 0.84 J (300 fps/0.20g) |
| UK (UKARA) | UK Airsoft Retailers Association | Rifle 1.14 J, DMR 1.64 J, Sniper 2.32 J |
| Germany | German airsoft law | 0.5 J (full-auto), 7.5 J (semi-only, above 18) |
| Generic CQB | Common CQB limits | All classes: 1.0 J max |

Each template names its source and the date it was last verified.
Fields start from a template and can adjust any value.

Limits include minimum engagement distances (MEDs) per class:

| Class | Typical MED |
|-------|------------|
| Rifle | 0 m (full auto OK) |
| DMR | 20-30 m (semi only) |
| Sniper | 30-50 m (bolt only) |

### Spot checks

- A marshal scans the replica's tag during play.
- Takes a reading with field BBs.
- The app compares with the check-in reading and the class limit.
- A reading over the limit, or above check-in by more than the
  tolerance (default 5%), raises `chrono.violation` to the GM and
  marshals.
- Penalties are decided by people; the app only records the outcome.

### GDPR implications

Chrono records contain personal data (player identity linked to
readings).  Under GDPR (the user is in Portugal, EU):

- **Lawful basis:** legitimate interest (safety) for processing during
  the game day.  Consent for longer retention.
- **Data minimisation:** store only velocity, weight, energy, marshal
  ID, timestamp.  No photos or video of the player.
- **Retention:** configurable per field (default 12 months).  Auto-delete
  after retention period.
- **Right of access/erasure:** players can view and delete their records
  through the player app or site server.
- **Data controller:** the field operator, not the Atalaia project.
- **Data processor:** for hosted site servers, the Atalaia project
  (or its legal entity) acts as processor under a written DPA.
- **Cross-field sharing:** off by default.  Each field opts in, and
  players are informed at registration.
- **Privacy notice:** template provided in the docs for field operators
  to display at registration.

### Chronograph input methods

1. **Manual entry** (v1): large keypad screen in the marshal's app.
2. **Bluetooth chronograph:** if the chrono has BLE data output and a
   documented protocol, the app can read velocity directly.
3. **DIY chronograph addon:** an ESP32 with two IR light gates,
   measuring time-of-flight.  Sends readings to the marshal's app over
   BLE.  Must be verified against a commercial chrono.

### Files to touch

- `app/lib/chrono/` -- check-in UI, registry, spot check, energy calc
- `app/lib/chrono/limit_templates/` -- YAML templates per country
- Site server schema (phase 4): `replicas`, `chrono_readings` tables
- Privacy notice template: `docs/templates/privacy-notice.md`

---

## 6. Player check-in mode

See section 4.5 above.  This is a dedicated mode (`modes/player_checkin/`)
that counts individual players at a prop via NFC or QR.  It is distinct
from chrono check-in (section 5), which is a marshal workflow for
measuring replica velocity.

Player check-in is used at the start of a game to register who is
playing and on which team.  The prop displays a per-team count and
emits `player.checkin` events to the controller.

---

## 7. Player positions and visibility

### GPS outdoors

The player app uses `FusedLocationProviderClient` (Android) or
`CLLocationManager` (iOS) to report the player's position.  Positions
are sent to the controller (over field Wi-Fi) or the site server (over
4G) at a configurable interval (default 10 s).

### BLE beacons indoors

For indoor sites (CQB, palacetes), GPS is unreliable.  Small BLE
beacons (iBeacon or Eddystone format) are placed in each room.  The
player app scans for beacons and reports room-level presence based on
the strongest beacon signal.  This gives room-level granularity, not
metre-level.

BLE beacon hardware: any iBeacon-compatible BLE broadcaster (EUR 5-10
each).  No custom firmware needed.

### Server-side filtering per role

The controller or site server filters positions before sending them to
clients.  A device NEVER receives positions its role may not see:

| Role | Sees positions of |
|------|------------------|
| Player | Own squad (if mode allows), own position |
| Squad leader | Own squad members |
| VIP | Own escort team |
| Marshal | All players |
| GM | All players |
| Spectator | None (or delayed, public) |

This is a server-side filter, not a client-side one.  A modified app
cannot reveal enemy positions because the server never sends them.

### Temporary visibility (UAV sweep)

Modes can grant temporary visibility as a game event.  For example,
using a hint code triggers a 30-second "UAV sweep" that reveals all
enemy positions to the scanning team.  This is implemented as a
time-limited flag in the controller that adjusts the position filter
for the duration.

### LoRa player tags

For fields without mobile coverage, optional LoRa player tags (small
ESP32 satellites with GPS, worn on the player's vest) pair with the
phone over BLE and relay position over LoRa.  This is a phase 4+
stretch goal.

### GDPR

Player positions are personal data:

- **Retention:** deleted when a game is archived, unless the GM
  explicitly exports them.
- **Purpose limitation:** used only for in-game visibility rules.
- **No tracking outside games.**

### Files to touch

- `app/lib/position/` -- GPS/BLE position reporting
- `app/lib/position/beacon_scanner.dart` -- BLE beacon scanning
- Controller/site server: position endpoint, role-based filter
- `controller/src/positions.py` -- position ingestion and filtering

---

## 8. Security

### API tokens

The controller's REST API uses two token types (spec section 14):

- **Read token:** grants read access to scores, events, node state.
  Can be printed as a QR code for spectators and scoreboards.
- **GM token:** grants write access to game control commands.  Required
  for start, pause, end, score adjustment, node commands.

Tokens are opaque strings generated by the controller with a CSPRNG.
They are passed in the `Authorization: Bearer <token>` header.  The
site server adds account-based authentication (phase 4).

### Kiosk mode tamper resistance

- Lock-task mode prevents leaving the app (section 2).
- Device owner provisioning prevents uninstalling the app.
- The admin PIN (4-6 digits) is required to exit kiosk mode.
- A `node.tamper` event is emitted if kiosk mode is broken (detected
  by the foreground service losing its task lock).
- Physical tamper: the enclosure should have a tamper switch or the
  IMU detects opening/movement.

### NFC tag signing

Tags carry a payload signed with the game key (HMAC-SHA256).  The UID
alone is never trusted.  This prevents tag cloning from being useful:
a cloned tag with a valid signature is still tied to the original
player/team, and the game key rotates every game.

### Modified app detection

The primary defence is server-side role filtering (section 7): a
modified app cannot see data the server does not send.  Additional
measures:

- App signing: the APK is signed with the project's release key.
  A modified APK has a different signature.
- Certificate pinning for HTTPS connections to the site server
  (not for field Wi-Fi, which uses local certs).
- SafetyNet / Play Integrity API check (optional, for competitive
  events).

### HTTPS

- **Site server:** HTTPS with Let's Encrypt certificates.  HSTS
  enforced.
- **Field controller:** HTTP on the local network (no public CA can
  issue certs for local IPs).  A self-signed CA is generated at
  controller setup and its cert is distributed during join.  For
  competitive events, the controller can use a real domain with HTTPS.
- **Two-factor authentication:** required for GM and marshal accounts
  on the site server (TOTP).

### Files to touch

- `controller/src/auth.py` -- token generation and validation
- `app/lib/security/` -- certificate pinning, integrity checks
- `controller/src/tls.py` -- self-signed CA for field controller

---

## 9. iOS constraints

iOS runs the player app and the GM console, but cannot serve as a prop
or field controller.

### What iOS CANNOT do

| Feature | Why not | Impact |
|---------|---------|--------|
| Prop role | No kiosk mode equivalent; no background NFC scanning; app review restrictions | iOS devices cannot be dedicated props |
| Controller role | No embedded MQTT broker; no USB-OTG host; App Store restrictions on server apps | iOS devices cannot be controllers |
| Background NFC | iOS only supports NFC in foreground (user must tap a button to scan) | NFC-based respawn/check-in requires user action, not passive scanning |
| BLE background | iOS limits BLE scanning in background (30-second windows) | Pod link would be unreliable in background |
| USB-OTG host | iOS (Lightning/USB-C) does not support USB host for serial devices | No USB pod link |
| Lock-task mode | No equivalent on iOS | No kiosk mode |

### What iOS CAN do

| Feature | How |
|---------|-----|
| Player views | Full Flutter UI: scores, map, messages, objectives, lives |
| QR scanning | Camera-based; works in foreground |
| NFC reading (foreground) | User taps a button, phone scans; works for player check-in and respawn (with user action) |
| GPS positioning | `CLLocationManager`; works in foreground; background location with "always" permission |
| GM console | WebView wrapping the GM console web app |
| BLE beacons (foreground) | Indoor positioning via iBeacon |
| Push notifications | APNs for GM messages and game events |

### Conditional compilation

The Flutter app uses `dart:io.Platform.isIOS` checks and build
flavors to exclude prop/controller code from the iOS build.  The
iOS `Info.plist` does not request `UIBackgroundModes` for BLE or
location unless needed for the player role.

### App Store compliance

The app uses the GPL-3.0-or-later with the app-store permission
(`app/APP-STORE-PERMISSION.md`) to comply with Apple's App Store
terms.

### Files to touch

- `app/ios/Runner/Info.plist` -- permissions
- `app/lib/platform/` -- platform-specific abstractions
- `app/ios/` -- iOS-specific build configuration

---

## 10. CI for Flutter

### Testing without devices

| Layer | Tool | What it tests | CI? |
|-------|------|--------------|-----|
| Dart unit tests | `flutter_test` | FFI bindings (against a stub `.so`), game loop logic, state management, energy calculation, mode parameter parsing | Yes |
| Widget tests | `flutter_test` | UI components render correctly, role switching, screen templates | Yes |
| Integration tests | `integration_test` package | Full-app flows with mocked FFI and services | Yes (Android emulator in CI) |
| FFI stub | A precompiled `libatalaia_core_stub.so` | Returns fixed values for all C functions; allows Dart tests without the real core | Yes |
| Core cross-compile | CMake + NDK | The real `.so` builds for Android ABIs | Yes |

### Android emulator in CI

GitHub Actions supports Android emulators via `reactivecircus/android-emulator-runner`.
The emulator runs integration tests that exercise the full Flutter app
(minus hardware: NFC, BLE, GPS are mocked).

### FFI stubs for testing

A stub shared library (`core/tests/libatalaia_core_stub.so`) implements
the same C API as the real core but returns predictable values.  This
lets Dart unit tests run on any platform (Linux, macOS, Windows)
without cross-compiling the real core.  The stub is built from
`core/tests/stub.c` with the standard CMake build.

### CI jobs

| Job | Image | Commands |
|-----|-------|---------|
| `flutter-test` | `cirruslabs/flutter` or similar | `flutter test` (unit + widget tests) |
| `flutter-build-android` | Flutter + Android SDK | `flutter build apk --debug` (verifies NDK cross-compile of core) |
| `flutter-integration` | Flutter + Android emulator | `flutter test integration_test/` |
| `core-android-ndk` | Android NDK Docker | `cmake --preset android-arm64 && cmake --build` |

### Files to touch

- `app/test/` -- Dart unit and widget tests
- `app/integration_test/` -- integration tests
- `core/tests/stub.c` -- FFI stub for Dart testing
- `.github/workflows/ci.yml` -- Flutter CI jobs

---

## 11. Screen template sharing

### Background

ADR-P1-2 says: "Screen templates are C functions... A declarative
template format is deferred to phase 3 when the Flutter renderer needs
the same templates."

Currently, each screen template (standby, countdown, defused, exploded,
final_score, paused, status, etc.) is a C function in
`firmware/esp32/main/screen_renderer.c` that builds LVGL 9.2 widget
trees.  These C functions cannot be reused in Flutter.

### Declarative template format

Phase 3 introduces a simple declarative format that both LVGL (ESP32)
and Flutter can render.  Templates live in each mode's `assets/`
directory.

**Format:** YAML or JSON, describing a layout tree:

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
  - type: icon
    id: team_icon
    icon: "{team}"
    style: { size: 32 }
```

**Supported widget types (v1):**

| Type | Properties | Notes |
|------|-----------|-------|
| `label` | `text`, `style` | Main text display; supports `{variable}` interpolation |
| `progress_bar` | `value` (0-1), `style` | Horizontal bar |
| `icon` | `icon` (name), `style` | Team icon, status icon |
| `qr_code` | `data`, `style` | QR code display |
| `spacer` | `height` | Vertical spacing |
| `row` / `column` | `children`, `style` | Layout containers |

**Interpolation:** `{variable}` is replaced with data values from
`ui.screen(template, data)`.  Simple expressions like `{left / total}`
are supported.

**Style properties:**

| Property | Values |
|----------|--------|
| `font_size` | Integer (points) |
| `align` | `left`, `center`, `right` |
| `color` | `team` (dynamic), named colour, hex |
| `background` | Same as `color` |
| `padding` | Integer or `{top, right, bottom, left}` |
| `height`, `width` | Integer or `fill` |

### Renderers

**LVGL renderer (ESP32):** a C function `screen_render_template` parses
the YAML/JSON template (loaded from LittleFS) and creates LVGL widgets.
On subsequent calls with the same template but new data, it patches
existing widgets (same pattern as the current C functions).  Templates
are parsed once at mode load time; the widget tree is cached.

**Flutter renderer (Android/iOS):** a Dart class `ScreenTemplateRenderer`
parses the same YAML/JSON and builds a Flutter widget tree.  Uses
`Text`, `LinearProgressIndicator`, `Icon`, `Row`, `Column`.  The
widget tree is rebuilt reactively when data changes (standard Flutter
`setState`).

### Migration from C functions

The existing C screen functions in `screen_renderer.c` become the
fallback: if no template file exists in `assets/screens/`, the C
function is used.  Built-in modes are migrated to the declarative
format.  Custom modes use the declarative format exclusively.

### Files to touch

- `modes/*/assets/screens/*.yaml` -- declarative templates for each mode
- `firmware/esp32/main/screen_template.c` -- LVGL template renderer
- `app/lib/ui/screen_template.dart` -- Flutter template renderer
- `core/include/atalaia/screen_template.h` -- shared template schema
  (or parsed in each platform's shell)

---

## 12. What needs real phones, pods or boards

### Cannot be tested in CI

| Item | Why | Test method |
|------|-----|------------|
| BLE pod link latency and reliability | Requires real BLE hardware | Manual: phone + pod board |
| USB-OTG pod link | Requires real USB-OTG cable and phone | Manual: phone + pod board |
| NFC read distance and speed on phone | Varies by phone model | Manual: phone + NFC tags |
| Kiosk mode on specific Android OEMs | OEM skins differ (Samsung, Xiaomi) | Manual: test on target devices |
| Battery optimisation exemption per OEM | Each OEM has different battery management | Manual: document per-OEM steps |
| GPS accuracy in the field | Depends on sky visibility and phone antenna | Manual: field test |
| BLE beacon room detection | Depends on building layout and beacon placement | Manual: indoor field test |
| Mixed ESP32 + Android prop game (the gate) | Full system integration | Manual: field test |
| I/O pod enclosure fit and waterproofing | Physical design | Manual: prototype |
| Chrono check-in with real chronographs | Hardware integration | Manual: marshal test |
| Audio output quality (siren, effects) on different phones | Varies by speaker | Manual |
| Screen brightness and readability outdoors | Varies by phone | Manual |
| Touch responsiveness with gloves | Depends on glove type and screen tech | Manual |

### Can be tested in CI

| Item | How |
|------|-----|
| dart:ffi bindings to the C core | FFI stub library |
| Game loop logic (100 Hz tick, command dispatch) | Unit tests |
| Screen template parsing and rendering | Widget tests |
| Energy calculation (chrono) | Unit tests |
| All 5 new game modes | Simulator mode tests |
| Role-based position filtering logic | Unit tests |
| API token generation and validation | Unit tests |
| Capability proxy frame encoding/decoding | Unit tests (shared vectors) |
| Flutter build for Android | `flutter build apk` |
| Core cross-compile for Android ABIs | CMake + NDK |

---

## Assumptions about phases 1 and 2

Every interface, API, protocol feature, or component that phase 3
depends on from phases 1 and 2.

### From phase 1

| # | Assumption | Where defined | Exists yet? | Impact if it changes |
|---|-----------|--------------|-------------|---------------------|
| A1 | `atalaia_node_t` API is stable: `create`, `destroy`, `input`, `advance`, `load`, `set_teams`, `set_params` | `core/include/atalaia/node.h` | Yes, implemented and tested | **High.** The Dart FFI bindings wrap every function. Any signature change requires updating the Dart layer. |
| A2 | `atalaia_node_callbacks_t` has `event`, `command`, `log` callbacks with their current signatures | `core/include/atalaia/node.h` lines 54-64 | Yes | **High.** Dart `NativeCallable` wrappers depend on exact signatures. |
| A3 | The core builds as a shared library with `-DATALAIA_SHARED=ON` | `core/CMakeLists.txt` | Yes | **Medium.** Android needs `.so` files; if the shared lib target changes, the NDK cross-compile step adapts. |
| A4 | `atalaia_score_t` and `atalaia_score_merge` are available for score display | `core/include/atalaia/score.h` | Yes | **Low.** The player app reads scores via the API, not directly from C. Only the prop role needs this. |
| A5 | `atalaia_node_status_t` enum values (EMPTY, RUNNING, ENDED, HALTED) are stable | `core/include/atalaia/node.h` lines 47-52 | Yes | **Low.** Used for status display; easy to update. |
| A6 | HAL ops struct pattern (function pointers in `hal_<name>_ops_t`) | ADR-P1-1, `firmware/esp32/main/hal/` | Yes, implemented | **Medium.** The I/O pod firmware reuses HAL modules. If the pattern changes, pod firmware adapts. |
| A7 | Screen templates are C functions (`screen_renderer.c`) with `screen_render(template, data)` | ADR-P1-2 | Yes, implemented | **Medium.** Phase 3 introduces declarative templates alongside these. The C functions remain as fallback. |
| A8 | `ui.screen(template, data)` is the script API for display | `core/src/script_api.c` | Yes | **Low.** Both the LVGL and Flutter renderers are triggered by this call. |
| A9 | LittleFS storage partition layout (`/presets/`, `/modes/`, `/state/`, `/audio/`) | ADR-P1-4 | Yes, implemented | **Low.** The pod firmware reuses LittleFS for mode storage. |
| A10 | FreeRTOS task architecture is extensible (can add tasks) | ADR-P1-7 | Yes | **Low.** The pod adds BLE GATT and USB CDC tasks. |

### From phase 2

| # | Assumption | Where defined | Exists yet? | Impact if it changes |
|---|-----------|--------------|-------------|---------------------|
| B1 | `state.field{}` and `field.*` Lua API are implemented | Phase 2 PLAN Phase C; ADR-P2-5 `field_ops` | **Pending** (Phase 2C not started) | **Critical.** Hold-All Domination and Last Stand REQUIRE `field.nodes()`, `field.owner()`, `field.common_owner()`. Without this, two of the five new modes cannot be built. |
| B2 | `atalaia_node_config_t` accepts a `field_ops` pointer | Phase 2 PLAN Phase C | **Pending** | **High.** The Android controller role needs `field_ops` to run `field.lua`. |
| B3 | Skirmesh-RF packet codec (header, AES-CCM, CBOR payloads) is stable | Phase 2 PLAN Phase A; `core/include/atalaia/packet.h` | **Yes** (Phase 2A complete) | **High.** The I/O pod and Android radio passthrough use the same codec. Changes require updating the pod firmware and Dart packet layer. |
| B4 | USB radio modem framing (IDENT, RX, TX, TX_ACK, CMD, STATUS, ERROR) | ADR-P2-4 | **Yes** (Phase 2A defined, Phase 2D implements) | **High.** The I/O pod reuses this framing for its radio passthrough. |
| B5 | USB radio modem firmware is a Kconfig build variant | ADR-P2-4 | **Pending** (Phase 2D) | **Medium.** The I/O pod firmware is modelled as another Kconfig variant. If the modem variant pattern changes, the pod variant adapts. |
| B6 | Python field controller REST API (`/api/v1/*`) is stable | Phase 2 PLAN Phase D; spec section 11 | **Pending** (Phase 2D) | **High.** The player app and GM app connect to this API. Endpoint changes require app updates. |
| B7 | WebSocket `/api/v1/stream` delivers live events | Phase 2 PLAN Phase D | **Pending** (Phase 2D) | **High.** The player app uses WebSocket for live scores and events. |
| B8 | `RadioModel` and `FieldController` in the simulator support multi-node testing | Phase 2 PLAN Phase B | **Yes** (Phase 2B complete) | **Medium.** New field-script modes (Hold-All, Last Stand) are tested in the simulator. |
| B9 | Flood/dedupe/ACK in `core/` are stable | Phase 2 PLAN Phase A; `core/include/atalaia/flood.h` | **Yes** (Phase 2A complete) | **Low.** The pod firmware links the same flood code. |
| B10 | Join flow (NFC card, QR, HMAC-SHA256 payload) is defined | ADR-P2-12 | **Yes** (defined; implementation pending Phase 2E) | **Medium.** The Android app reads join NFC cards using the same payload format. If the format changes, the app's NFC reader adapts. |
| B11 | Capability proxy protocol (IDENT, EVT, CMD, ACK frames) is defined | Spec section 7 | **Defined in spec, not implemented** | **High.** The I/O pod's entire purpose is to implement this protocol. If the frame format is not frozen by the time pod development starts, rework is likely. |
| B12 | Controller failover (CLAIM protocol) works | Phase 2 PLAN Phases D+F; ADR-P2-8 | **Pending** (Phase 2D) | **Low.** The Android controller role participates in failover but does not add new failover logic. |
| B13 | TIME beacon and time sync algorithm are stable | Phase 2 PLAN Phase C; ADR-P2-7 | **Pending** (Phase 2C) | **Medium.** The Android prop's time sync reuses the same algorithm (implemented in Dart or via the core). |
| B14 | GM console web app exists and is serveable | Phase 2 PLAN Phase E | **Pending** (Phase 2E) | **Medium.** The GM role on Android wraps it in a WebView. If the console is not ready, the GM role is deferred. |
| B15 | Event log format on ESP32 (flash-backed, LittleFS) | ADR-P2-9 | **Pending** (Phase 2C) | **Low.** The pod firmware uses the same log format. The Android prop uses SQLite. |

### Risk assessment of assumptions

**Critical dependencies (block phase 3 modes):**
- B1: `state.field{}` and `field.*` -- blocks Hold-All and Last Stand.
  **Mitigation:** these two modes can be deferred until after phase 2C
  ships.  The remaining three modes (Kill Confirmed, Respawn, Player
  Check-in) do not need field scripts.

**High dependencies (significant rework if changed):**
- A1, A2: core API stability -- mitigated by the core being "done" for
  phase 1 (ADR-P1 constraint #1).
- B3, B4: packet codec and modem framing -- mitigated by phase 2A
  being complete and the codec being tested with shared vectors.
- B6, B7: REST API and WebSocket -- mitigated by the spec defining the
  endpoints; implementation in phase 2D follows the spec.
- B11: capability proxy protocol -- the spec defines it but no
  implementation exists.  This is the highest-risk phase 3 item.

**Pending but low risk:**
- Most phase 2C/D/E items are straightforward implementations of
  already-defined designs.

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| dart:ffi callback complexity on Android | Medium | High | Prototype the FFI bridge early (phase 3A); use `NativeCallable.listener` for async callbacks; fall back to `Pointer.fromFunction` if needed |
| I/O pod BLE latency too high for real-time game input | Low | Medium | USB-OTG fallback; measure latency during pod bring-up; BLE 5.0 connection interval of 7.5 ms should be sufficient |
| Android OEM battery management kills the foreground service | Medium | High | Document per-OEM exemption steps; request `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`; test on Samsung, Xiaomi, Huawei, Pixel |
| Phase 2C (`field.*` API) delayed, blocking Hold-All and Last Stand | Medium | Medium | Implement the three single-node modes first; defer field-script modes |
| Capability proxy protocol not frozen | Medium | High | Define and freeze the frame format in phase 3 ADR before pod development |
| Flutter build times in CI (NDK cross-compile + emulator) | Low | Low | Cache Gradle and NDK downloads; use `flutter build apk --debug` for CI; full release builds on tag only |
| NFC foreground-dispatch on older Android phones unreliable | Low | Medium | Fall back to QR scanning; document minimum NFC requirements |
| LVGL declarative template renderer is complex | Medium | Medium | Keep the template format minimal (v1); support only the 6 widget types listed; defer complex layouts to phase 5 visual editor |

---

## Summary of files to touch

### New directories

| Directory | Purpose |
|-----------|---------|
| `app/lib/ffi/` | Dart FFI bindings to the C core |
| `app/lib/core/` | Game loop isolate, node wrapper |
| `app/lib/prop/` | Prop role: capability mapper, sensor drivers |
| `app/lib/pod/` | BLE/USB client for the I/O pod |
| `app/lib/player/` | Player role views |
| `app/lib/chrono/` | Chrono check-in, registry, energy calc |
| `app/lib/position/` | GPS/BLE position reporting |
| `app/lib/security/` | Certificate pinning, integrity |
| `app/lib/ui/` | Shared UI components, screen template renderer |
| `app/lib/platform/` | Platform-specific abstractions (iOS vs Android) |
| `app/android/app/src/main/kotlin/` | Kotlin plugins |
| `app/test/` | Dart unit and widget tests |
| `app/integration_test/` | Integration tests |
| `firmware/esp32/main/pod/` | Pod firmware variant |
| `modes/hold_all_domination/` | Hold-All Domination mode |
| `modes/last_stand/` | Last Stand mode |
| `modes/kill_confirmed/` | Kill Confirmed mode |
| `modes/respawn/` | Respawn and Lives mode |
| `modes/player_checkin/` | Player Check-in mode |
| `controller/src/positions.py` | Position ingestion and filtering |

### Modified files

| File | Change |
|------|--------|
| `core/CMakeLists.txt` | Add Android NDK cross-compile preset |
| `core/tests/stub.c` | FFI test stub for Dart |
| `firmware/esp32/main/Kconfig.projbuild` | Add `CONFIG_ATALAIA_POD_MODE` |
| `firmware/esp32/main/hal/hal.h` | No change expected (radio already added in phase 2) |
| `.github/workflows/ci.yml` | Add Flutter test/build jobs |
| `protocol/schema/events.yaml` | Add events: `kill.confirmed`, `player.respawn`, `player.checkin`, `team.eliminated`, `holdall.scoring_start`, `holdall.scoring_stop`, `laststand.defeated`, `chrono.violation`, `node.tamper` |
| `simulator/atalaia_sim/core.py` | Ensure `field_ops` support (may already be added in phase 2C) |

### Patterns to follow

- **Mode structure:** `modes/bomb/` and `modes/domination/` are the reference.
- **HAL abstraction:** ADR-P1-1 ops-struct pattern for pod hardware.
- **Firmware build variant:** ADR-P2-4 Kconfig modem mode for the pod.
- **Test format:** `modes/README.md` for mode tests.
- **Cross-platform test vectors:** `protocol/vectors/` for capability
  proxy frames.
- **Simulator ctypes:** `simulator/atalaia_sim/core.py` for FFI reference.
