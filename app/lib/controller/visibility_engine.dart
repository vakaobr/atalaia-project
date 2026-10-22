// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Who may see whose position (ADR-P3-6), for the Android controller role:
/// the same table as the Pi controller's
/// controller/atalaia_controller/positions.py, applied on the controller
/// before anything is sent (constraint 9: never on the viewer's phone).
///
///     player        their own; their squad's when the game says squad_visible
///     squad_leader  their squad
///     vip           their team
///     marshal, gm   everyone
///     spectator     nobody
///
/// plus temporary grants (a UAV sweep): a team sees another team until the
/// grant expires. Since slice S5 of PE24 the phone controller's positions
/// (controller_positions.dart) use it, one engine per game.
library;

final class Viewer {
  const Viewer({
    required this.role,
    this.playerId,
    this.team = 0,
    this.squad = 0,
    this.gameId,
  });

  /// The GM token: sees everything.
  static const gmToken = Viewer(role: 'gm');

  final String role;
  final String? playerId;
  final int team;
  final int squad;
  final int? gameId;
}

final class PlayerPosition {
  const PlayerPosition({
    required this.gameId,
    required this.playerId,
    required this.team,
    required this.squad,
    this.report = const {},
  });

  final int gameId;
  final String playerId;
  final int team;
  final int squad;
  final Map<String, Object?> report;
}

class VisibilityEngine {
  VisibilityEngine({DateTime Function()? now}) : _now = now ?? DateTime.now;

  final DateTime Function() _now;
  bool squadVisible = false;

  /// (team that sees, team seen) -> expiry.
  final _grants = <(int, int), DateTime>{};

  void grant(int team, int seeTeam, Duration duration) =>
      _grants[(team, seeTeam)] = _now().add(duration);

  /// The grants whose time is up, removed (each becomes visibility.expired).
  List<(int, int)> expire() {
    final now = _now();
    final done = [
      for (final e in _grants.entries)
        if (!e.value.isAfter(now)) e.key,
    ];
    done.forEach(_grants.remove);
    return done;
  }

  bool canSee(Viewer v, PlayerPosition p) {
    if (v.role == 'gm' && v.playerId == null) return true;
    if (v.gameId != null && v.gameId != p.gameId) return false;
    switch (v.role) {
      case 'marshal' || 'gm':
        return true;
      case 'spectator':
        return false;
    }
    if (p.playerId == v.playerId) return true;
    final sameTeam = v.team != 0 && p.team == v.team;
    final sameSquad = sameTeam && v.squad != 0 && p.squad == v.squad;
    if (v.role == 'squad_leader' && sameSquad) return true;
    if (v.role == 'vip' && sameTeam) return true;
    if (v.role == 'player' && sameSquad && squadVisible) return true;
    final exp = _grants[(v.team, p.team)];
    return v.team != 0 && p.team != 0 && exp != null && exp.isAfter(_now());
  }

  List<PlayerPosition> visible(Viewer v, Iterable<PlayerPosition> all) => [
    for (final p in all)
      if (canSee(v, p)) p,
  ];
}
