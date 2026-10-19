// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The game's length, kept by the shell (ADR-P1-3, decision PC6), as the
/// Field Box's firmware/esp32/main/game_timer.c: when the game time reaches
/// the length, the shell sends game.end to the node, once. Game time is the
/// node's own (it stands still while the game is paused), so the timer only
/// compares; the prop session reads the node's time and feeds it in.
library;

class GameTimer {
  GameTimer(this.durationMs);

  /// 0: no limit.
  final int durationMs;
  var _expired = false;

  bool get unlimited => durationMs <= 0;
  bool get expired => _expired;

  /// True exactly once: when [gameTimeMs] first reaches the length. The
  /// caller then sends game.end.
  bool update(int gameTimeMs) {
    if (_expired || unlimited) return false;
    if (gameTimeMs >= durationMs) {
      _expired = true;
      return true;
    }
    return false;
  }

  /// Milliseconds left, 0 once expired, null without a limit.
  int? remainingMs(int gameTimeMs) {
    if (unlimited) return null;
    if (_expired) return 0;
    final left = durationMs - gameTimeMs;
    return left < 0 ? 0 : left;
  }
}

/// A duration as M:SS, or H:MM:SS from an hour (the templates' |clock).
String clockText(int ms) {
  final s = (ms + 999) ~/ 1000;
  String two(int n) => n.toString().padLeft(2, '0');
  if (s >= 3600) return '${s ~/ 3600}:${two((s ~/ 60) % 60)}:${two(s % 60)}';
  return '${s ~/ 60}:${two(s % 60)}';
}
