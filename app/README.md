# Atalaia app

One Flutter app for Android and iOS.

| Role | Platforms |
| --- | --- |
| Player, squad leader, VIP, marshal, GM, spectator | Android and iOS |
| Prop (kiosk mode, with optional ESP32 I/O pod) | Android only |
| Field controller | Android only |

The app calls the shared C core through `dart:ffi`. Android-only features (kiosk mode, foreground service, USB and BLE pod links) are small Kotlin plugins. Minimum Android version: 8.0 (API 26).

Licence: GPL-3.0-or-later with the [app-store permission](APP-STORE-PERMISSION.md).

Status: planned for phase 3.
