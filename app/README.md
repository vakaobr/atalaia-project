<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Atalaia app

One Flutter app for Android and iOS.

| Role | Platforms |
| --- | --- |
| Player, squad leader, VIP, marshal, GM, spectator | Android and iOS |
| Prop (kiosk mode, with optional ESP32 I/O pod) | Android only |
| Field controller | Android only |

The app calls the shared C core through `dart:ffi`. Android-only features (kiosk mode, foreground service, USB and BLE pod links) are small Kotlin plugins. Minimum Android version: 8.0 (API 26).

Licence: GPL-3.0-or-later with the [app-store permission](APP-STORE-PERMISSION.md).

## Status

Phase 3, plan phases B and C: the app's logic for chrono check-in, player tags and player tokens, and the engine layer that runs the shared C core on Android: the `dart:ffi` bridge, the game loop isolate, and the core built for Android by Gradle and the NDK. There is no user interface yet (plan phase D): the APK opens on a placeholder screen that shows the version of the core it carries. Nothing has run on a phone or an emulator yet.

### The core on Android (plan phase C)

| Code | What it does |
| --- | --- |
| [`lib/ffi/native_types.dart`](lib/ffi/native_types.dart) | The core's C structs (`atalaia_event_t`, the callbacks, the node config, field operations, scores, the template scope) as `dart:ffi` structs. A test compares every size and offset with what the C compiler makes of the real headers |
| [`lib/ffi/bindings.dart`](lib/ffi/bindings.dart) | Every function of `atalaia/node.h`, plus the version, screen templates, player-tag checks and the event codec. The library is `libatalaia_core.so` from the APK, or `$ATALAIA_CORE_LIB` on a computer |
| [`lib/ffi/callbacks.dart`](lib/ffi/callbacks.dart) | The core's callbacks (events, commands, log lines, field state, field operations) as isolate-local native callables: the core calls them during its own call, while its pointers are valid (decision PC1) |
| [`lib/ffi/core_node.dart`](lib/ffi/core_node.dart) | `CoreNode`: one node, created, loaded, given inputs and time, read and destroyed; the Dart twin of the simulator's `Node` |
| [`lib/core/game_loop_isolate.dart`](lib/core/game_loop_isolate.dart) | `GameLoopIsolate`: each node in its own isolate, which alone calls into the core (ADR-P3-1). With the real-time clock, inputs wait for the next 10 ms tick and game time follows the wall clock from `game.start`, standing still while paused; with the manual clock (tests, replays) time moves only when told |
| [`lib/core/node_runner.dart`](lib/core/node_runner.dart), [`node_runner_android.dart`](lib/core/node_runner_android.dart), [`node_runner_stub.dart`](lib/core/node_runner_stub.dart), [`node_types.dart`](lib/core/node_types.dart) | What the rest of the app uses: a node runner picked by a conditional import, the FFI one where Dart has `dart:ffi` (unsupported on iOS, which ships no core: ADR-P3-10) and one that starts nothing on the web; the node's outputs and state, with no `dart:ffi` in them |
| [`android/`](android/) | The Android project (`org.atalaia.app`, Android 8.0 / API 26 and up). [`app/build.gradle.kts`](android/app/build.gradle.kts) builds the core from `../core` with CMake for arm64-v8a, armeabi-v7a and x86_64 and packs it into the APK |
| [`lib/main.dart`](lib/main.dart) | The placeholder screen: the app's name and the core's version |

The core's FFI stub ([`core/tests/stub.c`](../core/tests/stub.c), built with `-DATALAIA_STUB=ON`) implements `node.h` with fixed, simple behaviour and reports the C struct layouts; the bridge tests run against it. The mode tests run on the real core.

Pinned build tools: Gradle 9.1.0 (with its SHA-256 in [`gradle-wrapper.properties`](android/gradle/wrapper/gradle-wrapper.properties)), Android Gradle plugin 9.0.1, Kotlin 2.3.20, NDK 28.2.13676358, CMake 3.22.1, compile and target SDK 36: Flutter 3.44.0's own choices, written out so they cannot move. The core is compiled with 64-bit Lua numbers, as on the ESP32 and in the simulator, without mbedtls (a node does not need the radio's AES-CCM), and with 16 KB pages on the 64-bit ABIs.

### Chrono check-in, player tags and tokens (plan phase B)

| Code | What it does |
| --- | --- |
| [`lib/chrono/energy.dart`](lib/chrono/energy.dart) | Muzzle energy `E = 0.5 * m * v²` (0.20 g at 100 m/s is 1.0 J), fps and m/s (1 ft = 0.3048 m), the velocity for an energy, rounding |
| [`lib/chrono/reading.dart`](lib/chrono/reading.dart) | `ChronoReading`: one shot, with every field of ADR-P3-7, strict JSON in and out, the canonical bytes that are signed |
| [`lib/chrono/record_signer.dart`](lib/chrono/record_signer.dart) | The marshal's Ed25519 key, signing and verifying readings ([protocol/chrono-record.md](../protocol/chrono-record.md)) |
| [`lib/chrono/replica.dart`](lib/chrono/replica.dart) | `Replica`: the field's registry entry for a replica and its NFC sticker or QR label |
| [`lib/chrono/limit_template.dart`](lib/chrono/limit_template.dart) | Limit templates (YAML) and their loader; a field's own limits on top of one |
| [`lib/chrono/limit_templates/`](lib/chrono/limit_templates/) | Portugal, United Kingdom, Germany and generic CQB. **Unverified**: the figures come from the project's research, not from an official source; check them against current national and association rules before use (decision P3-5). They are not the law |
| [`lib/chrono/spot_check.dart`](lib/chrono/spot_check.dart) | Check-in (PASS or FAIL) and spot check (PASS, WARN or FAIL against the limit and the check-in plus 5%) |
| [`lib/chrono/retention.dart`](lib/chrono/retention.dart) | How long readings are kept (365 days by default) and erasing a player's readings |
| [`lib/security/nfc_tag_signer.dart`](lib/security/nfc_tag_signer.dart) | Player tags ([protocol/nfc-tag.md](../protocol/nfc-tag.md)): write, check, the NFC record, the `nfc.tag` data a prop gives its mode |
| [`lib/security/player_token.dart`](lib/security/player_token.dart) | Player tokens ([protocol/player-token.md](../protocol/player-token.md)): issue, check, read |
| [`lib/security/canonical_json.dart`](lib/security/canonical_json.dart), [`ndef.dart`](lib/security/ndef.dart), [`bytes.dart`](lib/security/bytes.dart) | The canonical JSON both signatures use, NFC Type 2 tag memory, hex and base64 |

Everything signed is checked against shared vectors that other implementations check too: [`tag.json`](../protocol/vectors/tag.json) (the C core and the simulator), [`chrono_record.json`](../protocol/vectors/chrono_record.json) and [`player_token.json`](../protocol/vectors/player_token.json) (the field controller's Python, `controller/atalaia_controller/chrono.py` and `player_token.py`, which the site server can reuse).

## Tests

Everything runs in Docker, from the repository root, in any shell (cmd, PowerShell, bash):

```sh
python tools/docker_app.py                    # check, ndk and apk below, one after the other
python tools/docker_app.py check              # the core for the tests, flutter analyze, dart format check, flutter test
python tools/docker_app.py test test/ffi      # only some tests (any flutter test arguments)
python tools/docker_app.py ndk                # the core cross-compiled for the three Android ABIs, and checked
python tools/docker_app.py apk                # flutter build apk --debug (Gradle builds the core), and the APK checked
python tools/docker_app.py format             # format lib/ and test/ in place
python tools/docker_app.py lock               # after changing a version in pubspec.yaml
```

The Dart side runs in the image CI uses (`ghcr.io/cirruslabs/flutter:3.44.0`, pinned by digest, about 2.3 GB on the first run). That image has a C compiler but no CMake, so `docker_app.py` first builds the core and the FFI stub as shared libraries in the `atalaia-dev` image (`tools/dev/Dockerfile`; both are Ubuntu 24.04) and hands them to the tests through `ATALAIA_CORE_LIB` and `ATALAIA_CORE_STUB_LIB`. `ndk` and `apk` install the pinned NDK and CMake with the Android SDK manager on first use (about 1 GB) and keep them, with Gradle's downloads, in Docker volumes.

What the tests cover:

- `test/ffi/`: the struct layouts against the C compiler's (`layout_test.dart`); every binding against the stub (`bindings_test.dart`: strings both ways, every callback, field operations, errors in handlers); the real core (`core_test.dart`: the shared event vectors through the C codec, the player-tag vectors, screen templates, a Domination node).
- `test/core/`: the game loop isolate on the stub and on the real core, with the manual and the real-time clock (order of outputs and replies, pause, status changes, load failures, shutdown), and the node runners.
- `test/modes/`: every mode's tests in `modes/*/tests/*.yaml` (Domination, Bomb, the Codes modifier, Hold-All, Last Stand, Kill Confirmed, Respawn and Lives, Player Check-in) on the real core through the Dart bridge, each once with the nodes called directly and once with each node in its own game loop isolate. They are the same files the simulator runs (`python -m atalaia_sim test`), with the same steps and expectations; [`test/support/mode_runner.dart`](test/support/mode_runner.dart) is the Dart port of the simulator's runner. As in the simulator, every event must match `protocol/schema/events.yaml` and fit a LoRa payload (through the core's codec), and each mode's screen templates must pass the core's parser.
- `test/chrono/`, `test/security/`: plan phase B, against the shared vectors.

With Flutter 3.44 installed locally and the core built (`cmake -S core -B build -DATALAIA_SHARED=ON -DATALAIA_STUB=ON -DATALAIA_MBEDTLS=OFF && cmake --build build`), `flutter test` in `app/` does the same; the tests find the libraries in `../build/` when the variables are not set. A missing library fails the tests that need it: nothing is skipped. `tools/check.sh` does not run the Dart tests (its image has no Dart); it does run the controller's side of the shared chrono and token vectors, and checks the simulator's ctypes structs against the stub's layout report.

Not run yet: the APK on an emulator or a phone. The emulator job comes with plan phase D; a phone needs hardware.

Dependencies are pinned to exact versions in [`pubspec.yaml`](pubspec.yaml), and [`pubspec.lock`](pubspec.lock) is committed: `crypto` 3.0.7 (HMAC-SHA256, from the Dart team), `cryptography` 2.9.0 (its pure-Dart Ed25519, checked against RFC 8032's known answers), `ffi` 2.2.0 (native memory and strings for the bridge, from the Dart team), `yaml` 3.1.4, and `flutter_lints` 6.0.0 for the analyzer.

## Next

- Plan phase D: the user interface (role selector, prop shell, player views, the marshal's chrono keypad and the replica registry on top of `lib/chrono/`), the screen-template renderer in Flutter, the Kotlin plugins (kiosk, foreground service, BLE and USB pod, NFC: a tag read becomes `nfc.tag` data through `lib/security/nfc_tag_signer.dart` and goes to the node with `GameLoopIsolate.input`), the iOS build and the emulator job.
- Plan phase E: the controller issues player tokens at join and checks them, and receives signed chrono readings; the Android controller role runs a mode's `field.lua` with `CoreNode`'s field operations.
