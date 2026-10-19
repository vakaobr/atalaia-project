// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The prop's screen (ADR-P3-5 "Screen management"): full brightness while
/// people use it, dimmed to 10% after 30 s without activity, "off" after 5
/// minutes. Any touch, button, tag or pod event makes it active again. The
/// game loop runs whatever the screen does (the foreground service holds a
/// partial wake lock).
///
/// "Off" depends on kiosk mode: in kiosk mode the screen is never let go to
/// sleep, which would bring up the lock screen; it stays on at the lowest
/// brightness instead (ADR-P3-5 "Kiosk mode interaction"). Outside kiosk
/// mode the keep-screen-on flag is cleared and Android turns the screen off
/// after its own timeout. While dimmed the flag stays on, so the screen
/// does not go off before the 5 minutes (decision PD8).
library;

import '../platform/services.dart';

enum ScreenState { active, dimmed, off }

class ScreenManager {
  ScreenManager(
    this.device, {
    this.kiosk = false,
    this.dimAfter = const Duration(seconds: 30),
    this.offAfter = const Duration(minutes: 5),
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now {
    _last = _now();
  }

  final DeviceServices device;
  bool kiosk;
  final Duration dimAfter;
  final Duration offAfter;
  final DateTime Function() _now;
  late DateTime _last;
  ScreenState? _state;

  ScreenState get state => _state ?? ScreenState.active;

  /// Starts managing the screen (a game is shown).
  Future<void> start() => _apply(ScreenState.active);

  /// Someone or something touched the prop.
  Future<void> activity() async {
    _last = _now();
    if (_state != ScreenState.active) await _apply(ScreenState.active);
  }

  /// Called every second or so.
  Future<void> tick() async {
    final idle = _now().difference(_last);
    final want = idle >= offAfter
        ? ScreenState.off
        : idle >= dimAfter
        ? ScreenState.dimmed
        : ScreenState.active;
    if (want != _state) await _apply(want);
  }

  /// Gives the screen back to the system (the game screen closed).
  Future<void> stop() async {
    _state = null;
    await device.setBrightness(null);
    await device.keepScreenOn(false);
  }

  Future<void> _apply(ScreenState s) async {
    _state = s;
    switch (s) {
      case ScreenState.active:
        await device.keepScreenOn(true);
        await device.setBrightness(1.0);
      case ScreenState.dimmed:
        await device.keepScreenOn(true);
        await device.setBrightness(0.1);
      case ScreenState.off:
        if (kiosk) {
          await device.keepScreenOn(true);
          await device.setBrightness(0.01);
        } else {
          await device.setBrightness(null);
          await device.keepScreenOn(false);
        }
    }
  }
}
