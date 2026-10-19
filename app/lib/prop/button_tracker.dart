// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Team buttons on the touchscreen as the inputs modes expect
/// (modes/README.md "Inputs from the hardware"), the Dart twin of the Field
/// Box's firmware/esp32/main/button_tracker.c: team_input.press when a
/// button goes down, team_input.hold every 250 ms while it is held (with the
/// time held so far), team_input.release when it is let go.
library;

typedef InputSink = void Function(String type, Map<String, Object?> data);

const int holdIntervalMs = 250;

class ButtonTracker {
  ButtonTracker(this.sink);

  final InputSink sink;
  final _held = <String, int>{}; // team -> ms held
  final _accum = <String, int>{}; // team -> ms since the last hold event

  bool isDown(String team) => _held.containsKey(team);

  /// The teams whose buttons are down.
  Iterable<String> get down => _held.keys;

  void press(String team) {
    if (_held.containsKey(team)) return;
    _held[team] = 0;
    _accum[team] = 0;
    sink('team_input.press', {'team': team});
  }

  void release(String team) {
    final ms = _held.remove(team);
    _accum.remove(team);
    if (ms == null) return;
    sink('team_input.release', {'team': team, 'ms': ms});
  }

  /// Lets every button that is down go (the screen lost focus, the game ended).
  void releaseAll() {
    for (final t in _held.keys.toList()) {
      release(t);
    }
  }

  /// Time passes: hold events for every button that is down.
  void tick(int deltaMs) {
    for (final team in _held.keys.toList()) {
      final held = _held[team]! + deltaMs;
      var accum = _accum[team]! + deltaMs;
      _held[team] = held;
      while (accum >= holdIntervalMs) {
        accum -= holdIntervalMs;
        sink('team_input.hold', {'team': team, 'ms': held});
      }
      _accum[team] = accum;
    }
  }
}
