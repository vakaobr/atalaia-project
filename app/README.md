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

Phase 3, plan phase B: the app's logic for chrono check-in, player tags and player tokens, in plain Dart with tests. There is no user interface, no `dart:ffi` bridge and no Android or iOS project yet (`flutter create` comes with plan phases C and D).

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

Dart and Flutter run in Docker, in the image CI uses (`ghcr.io/cirruslabs/flutter:3.44.0`, pinned by digest, about 2.3 GB on the first run). From the repository root, in any shell:

```sh
python tools/docker_app.py                    # flutter analyze, dart format check, flutter test
python tools/docker_app.py test test/chrono   # only some tests
python tools/docker_app.py format             # format lib/ and test/ in place
python tools/docker_app.py lock               # after changing a version in pubspec.yaml
```

With Flutter 3.44 installed locally, `flutter test` in `app/` does the same (the tests read `../protocol/vectors/`). `tools/check.sh` does not run the Dart tests (its image has no Dart); it does run the controller's side of the shared vectors.

Dependencies are pinned to exact versions in [`pubspec.yaml`](pubspec.yaml), and [`pubspec.lock`](pubspec.lock) is committed: `crypto` 3.0.7 (HMAC-SHA256, from the Dart team), `cryptography` 2.9.0 (its pure-Dart Ed25519, checked against RFC 8032's known answers), `yaml` 3.1.4, and `flutter_lints` 6.0.0 for the analyzer.

## Next

- Plan phase C: the `dart:ffi` bindings to the core, the game loop isolate, the FFI stub library, the Android NDK build (`lib/ffi/`, `lib/core/`, `android/`).
- Plan phase D: the user interface, among it the marshal's chrono keypad and the replica registry on top of `lib/chrono/`, and the Kotlin plugins (NFC reading uses `lib/security/nfc_tag_signer.dart`).
- Plan phase E: the controller issues player tokens at join and checks them, and receives signed chrono readings.
