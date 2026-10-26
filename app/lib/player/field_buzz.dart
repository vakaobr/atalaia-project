// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The player's phone buzzes on key game events (decisions VB-1 to VB-9, the
/// maintainer's answer of 2026-10-26): a message from the GM, a box of the
/// player's team captured or lost, the game starting and ending, and (PD-MODE-21)
/// Progressive Domination's next box becoming active. Short
/// patterns, no sound (MF-33: a tone could give a player's place away),
/// through the same device channel as the squad orders' buzz (SQ-5) and the
/// boundary warning.
///
/// The decision of whether an event buzzes lives here, free of widgets: the
/// player view feeds it the live events of [FieldFeed.liveEvents].
library;

import 'field_feed.dart';

/// What a buzz announces; each has its own pattern.
enum Buzz {
  /// A message from the GM: the longest single pulse.
  gmMessage([0, 350]),

  /// A box of the player's team was captured (by the team: nothing the
  /// player's phone did, boxes are captured at the box).
  captured([0, 150]),

  /// A box of the player's team was taken by another team, or freed.
  lost([0, 90, 70, 90]),

  /// The game starts: three quick ticks.
  gameStart([0, 70, 60, 70, 60, 70]),

  /// The game ends: two medium pulses.
  gameEnd([0, 180, 100, 180]),

  /// Progressive Domination: a box became the active one, for both teams
  /// (PD-MODE-21): a long pulse then a short one, unlike every other pattern.
  boxActivated([0, 300, 80, 100]);

  const Buzz(this.pattern);

  /// Android's waveform pattern: wait, buzz, pause, buzz... in milliseconds
  /// (iOS plays a tap or a buzz at each "on" start, VB-6).
  final List<int> pattern;

  /// Within the rate limit window, a buzz replaces a weaker one's silence.
  int get rank => this == gmMessage ? 1 : 0;
}

/// Decides which live events buzz, once in a [window] at most.
final class FieldBuzzer {
  FieldBuzzer({
    required this.vibrate,
    required this.enabled,
    required this.team,
    this.role,
    DateTime Function()? now,
    this.window = const Duration(seconds: 1),
  }) : _now = now ?? DateTime.now;

  /// Plays a pattern (the device channel's `vibrate`).
  final void Function(List<int> pattern) vibrate;

  /// The "vibrate on game events" setting, read at each event.
  final bool Function() enabled;

  /// The player's team, read at each event: from the check-in, else the
  /// team the player chose to follow; null: none known.
  final String? Function() team;

  /// The player's role, read at each event (a spectator is not buzzed).
  final String? Function()? role;

  /// Several events in one window give one buzz (VB-5).
  final Duration window;
  final DateTime Function() _now;

  DateTime? _last;
  Buzz? _lastBuzz;

  /// What [e] announces to this player, or null: nothing.
  Buzz? classify(FeedEvent e) {
    final mine = team();
    switch (e.type) {
      case 'gm.message':
        return Buzz.gmMessage;
      case 'game.start':
        return Buzz.gameStart;
      case 'game.end':
        return Buzz.gameEnd;
      case 'zone.captured':
        if (mine == null) return null;
        final previous = e.data['previous_team'];
        if (e.team == mine) return previous == mine ? null : Buzz.captured;
        return previous == mine ? Buzz.lost : null;
      case 'zone.neutralized':
        return mine != null && e.data['previous_team'] == mine
            ? Buzz.lost
            : null;
      case 'progressive.activated':
        // both teams are told, whoever the player is
        return Buzz.boxActivated;
      case 'progressive.completed':
        // the player's team completed it: as a capture; another team did: as
        // a loss (PD-MODE-21)
        if (mine == null || e.team == null) return null;
        return e.team == mine ? Buzz.captured : Buzz.lost;
    }
    return null;
  }

  /// One live event: buzzes if it should (the setting on, not a spectator,
  /// not within the window of a buzz of the same or higher rank).
  /// Returns what it played.
  Buzz? onEvent(FeedEvent e) {
    if (!enabled() || role?.call() == 'spectator') return null;
    final buzz = classify(e);
    if (buzz == null) return null;
    final now = _now();
    final last = _last;
    if (last != null &&
        now.difference(last) < window &&
        buzz.rank <= (_lastBuzz?.rank ?? 0)) {
      return null;
    }
    _last = now;
    _lastBuzz = buzz;
    vibrate(buzz.pattern);
    return buzz;
  }
}
