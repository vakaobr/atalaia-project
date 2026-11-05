// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A box still in a game that is over, on the Android field controller: the
/// Pi controller's controller/atalaia_controller/stuck_games.py in Dart
/// (decisions STUCK-1 to STUCK-19, STUCK-40 to STUCK-59 and STUCK-60 on;
/// RFC 0001 Amendments 27 and 28, proposed).
///
/// A box that was switched off when its game ended never heard the
/// GAME_OVERs (controller_boxes.dart). When it comes back it is still in that
/// game: it plays on and refuses every join. A USB radio modem whose IDENT
/// says `"games": true` reports the packets of other games it hears
/// (OTHER_GAME: the game id and source from the header in the clear, at most
/// once per game id in 10 s; protocol/usb-modem.md), once asked
/// (WATCH_GAMES, sent again on every IDENT by serial_modem.dart). When the
/// game id is one of the games this controller ran and ended, whose key's tag
/// it still keeps (`key_tag:<game>`, the last [keyTagsKept] games, so also
/// after a restart without the key), it says that game's GAME_OVER again,
/// through the same path and channel rules as at the end, at most once a
/// minute per game. GAME_OVER can only end a game that is over, so a report
/// forged from a header in the clear can cost some air, never a game. An I/O
/// pod passes no OTHER_GAME on: with it (or an older modem) `stuck_watch` is
/// false and the console says to update the modem's firmware.
///
/// A standby never sends it (its games run on the primary). What was heard is
/// kept for the console (`stuck` in GET /api/v1/boxes, and the stream's
/// `boxes` message): per game, when a box in it was last heard, from which
/// node ids, and how many times its GAME_OVER went again. The GM's console
/// lists them and can say a game's GAME_OVER at once ([release], the Release
/// button, POST /api/v1/boxes/stuck/{game}/release) within a short rate
/// limit, and can tell every box of the field on this channel that is in a
/// game other than the live one to leave it ([releaseField], RELEASE, POST
/// /api/v1/boxes/release), for a game this controller lost entirely.
///
/// Nothing here is stored but the key tags (the engine's settings): what was
/// heard lasts as long as the controller runs, as on the Pi.
library;

import 'dart:math';

import '../security/bytes.dart';
import 'controller_boxes.dart';
import 'controller_engine.dart';
import 'controller_radio.dart';
import 'controller_store.dart';

/// One GAME_OVER burst per game in this time at most (stuck_games.py).
const stuckResendMs = 60000;

/// The GM's Release: one burst per game in this time at most (STUCK-44).
const stuckReleaseMs = 10000;

/// The field-wide RELEASE (Amendment 28): one burst in this time at most.
const stuckReleaseFieldMs = 30000;

/// A game not heard of for this long leaves the list (as a free box).
const stuckForgetMs = 2 * 3600000;

/// The ended games whose key tag the controller keeps.
const keyTagsKept = 50;

/// The earliest wall clock a phone can honestly show (decision STUCK-62):
/// the Pi's wallclock.py `RELEASE_DATE`, 2026-11-01 00:00 UTC (a test keeps
/// the two equal). A clock under the floor less [clockToleranceS] is not
/// plausible, as the Pi's ClockGuard.
const clockFloorS = 1793491200;
const clockToleranceS = 60;

/// A game a box was heard still in.
class StuckGame {
  StuckGame(this.gameId, this.heardMs);
  final int gameId;
  int heardMs;
  final sources = <int>{};
  int? rssi;
  int resent = 0;
  int? resentMs;

  Map<String, Object?> public(int nowMs, String? name) => {
    'game': gameId,
    'name': name,
    'last_heard_s': max(0, (nowMs - heardMs) ~/ 1000),
    'nodes': sources.toList()..sort(),
    'rssi': rssi,
    'game_over_resent': resent,
  };
}

/// The phone controller's stuck boxes (stuck_games.py `StuckGames`), made by
/// [ControllerBoxes] (only with a field join key, as the Pi's).
class ControllerStuck {
  ControllerStuck(this.engine, this.boxes) {
    engine.stuck = this;
    final m = engine.modem;
    if (m != null) {
      // Another game's packets: a box still in a game that is over. A radio
      // that cannot report them (an I/O pod, an older modem) is never asked.
      m
        ..onOtherGame = onReport
        ..watchGames(true);
    }
  }

  final ControllerEngine engine;
  final ControllerBoxes boxes;
  final games = <int, StuckGame>{};

  /// OTHER_GAME reports heard; of those, for no game of this controller
  /// that is over ([unknown]: another field's, or a game with no tag).
  var reports = 0;
  var unknown = 0;
  var resendMs = stuckResendMs;
  var releaseMs = stuckReleaseMs;
  var releaseFieldMs = stuckReleaseFieldMs;

  /// Game id -> when the GM last released a game not in the list.
  final _released = <int, int>{};

  /// When the last field-wide RELEASE started.
  int? fieldReleasedMs;

  ControllerStore get _store => engine.store;

  bool get _standby => engine.liveGame?['joined'] == true;

  int _channelOf(Map<String, Object?> game) =>
      (game['channel_hz'] as int?) ?? engine.config.channelHz;

  /// OTHER_GAME from the radio.
  void onReport(OtherGame other) {
    reports++;
    final now = engine.nowMs();
    final live = engine.liveGame;
    // The live game's own (a report sent as the modem was being configured).
    if (live != null && live['id'] == other.gameId) return;
    if (_standby) return; // the primary tells its boxes
    final game = _store.game(other.gameId);
    final tag = _store.getSetting('key_tag:${other.gameId}');
    if (game == null ||
        game['state'] != 'ended' ||
        game['joined'] == true ||
        tag == null) {
      unknown++;
      return;
    }
    final fresh = !games.containsKey(other.gameId);
    final stuck = games.putIfAbsent(
      other.gameId,
      () => StuckGame(other.gameId, now),
    );
    stuck
      ..heardMs = now
      ..rssi = other.rssi
      ..sources.add(other.source);
    // The consoles' list carries the stuck games: told of a new one, and of
    // each resend (decision STUCK-63).
    if (_resend(stuck, game, tag, now) || fresh) boxes.refreshBoxes();
  }

  /// The game's GAME_OVER again, unless it is still being said or went
  /// within [resendMs]; true when it went.
  bool _resend(
    StuckGame stuck,
    Map<String, Object?> game,
    String tag,
    int now,
  ) {
    if (boxes.inviter.gameOverPending(stuck.gameId)) return false;
    final last = stuck.resentMs;
    if (last != null && now - last < resendMs) return false;
    if (!boxes.gameOver(stuck.gameId, hexDecode(tag), _channelOf(game))) {
      return false;
    }
    stuck
      ..resent += 1
      ..resentMs = now;
    return true;
  }

  /// The GM's Release (POST /api/v1/boxes/stuck/{game}/release, decisions
  /// STUCK-40 to STUCK-47): that game's GAME_OVER now, by the same path and
  /// channel rules as the resends, whether or not a box of it was heard.
  /// `game_over_frame`: "sent", "no_radio" (no radio that carries field
  /// frames) or "no_tag" (no key tag kept for it). Refused: a game that is
  /// not this controller's or not over (404, 409), a standby (409), a game
  /// live on another channel (409: the burst would be dropped), and within
  /// [releaseMs] of its last burst or while its GAME_OVERs are still being
  /// said (429).
  Map<String, Object?> release(int gameId) {
    final live = engine.liveGame;
    if (_standby) {
      throw ControllerError.conflict(
        'this controller follows a game as a standby: its primary tells the '
        'boxes',
      );
    }
    final game = _store.game(gameId);
    if (game == null) throw ControllerError.notFound('no game $gameId');
    if ((live != null && live['id'] == gameId) || game['state'] != 'ended') {
      throw ControllerError.conflict('game $gameId is not over');
    }
    if (game['joined'] == true) {
      throw ControllerError.conflict(
        'game $gameId was followed as a standby: its primary tells its boxes',
      );
    }
    final tag = _store.getSetting('key_tag:$gameId');
    if (tag == null) return {'game': gameId, 'game_over_frame': 'no_tag'};
    final now = engine.nowMs();
    if (boxes.inviter.gameOverPending(gameId)) {
      throw _tooSoon('game $gameId: its GAME_OVER is being sent now');
    }
    final stuck = games[gameId];
    final last = stuck != null ? stuck.resentMs : _released[gameId];
    if (last != null && now - last < releaseMs) {
      final wait = (releaseMs - (now - last) + 999) ~/ 1000;
      throw _tooSoon(
        'game $gameId: its GAME_OVER was sent a moment ago; try again in '
        '$wait s',
      );
    }
    final channel = _channelOf(game);
    if (live != null &&
        ((live['channel_hz'] as int?) ?? engine.fieldChannel) != channel) {
      throw ControllerError.conflict(
        "a game is live on another channel: game $gameId's GAME_OVER (on "
        '$channel Hz) would not be sent until it ends',
      );
    }
    if (!boxes.gameOver(gameId, hexDecode(tag), channel)) {
      return {'game': gameId, 'game_over_frame': 'no_radio'};
    }
    if (stuck != null) {
      stuck
        ..resent += 1
        ..resentMs = now;
    } else {
      _released[gameId] = now;
    }
    boxes.refreshBoxes();
    return {'game': gameId, 'game_over_frame': 'sent'};
  }

  /// The field-wide RELEASE (POST /api/v1/boxes/release, RFC 0001
  /// Amendment 28, decisions STUCK-50 to STUCK-59), for a controller that
  /// lost the game a box is stuck in (a new install: no key tag, so no
  /// GAME_OVER can name it): every box in a game other than the live one (or
  /// any game, with none live) that it joined before now leaves it.
  /// `release_frame`: "sent" or "no_radio". Refused: a standby (409), a wall
  /// clock that is not plausible (409: the boxes compare its time with their
  /// join's), and while one is being said or within [releaseFieldMs] of the
  /// last (429).
  Map<String, Object?> releaseField() {
    final live = engine.liveGame;
    if (_standby) {
      throw ControllerError.conflict(
        'this controller follows a game as a standby: a RELEASE would take the '
        "primary's boxes out of its game",
      );
    }
    final wall = engine.wallSeconds();
    if (!clockPlausible(wall)) {
      throw ControllerError.conflict(
        "the controller's clock is not set: set it first, so that the boxes "
        'can tell this RELEASE from an older one',
      );
    }
    final liveId = (live?['id'] as int?) ?? 0;
    final now = engine.nowMs();
    if (boxes.inviter.releasing) throw _tooSoon('a RELEASE is being sent now');
    final last = fieldReleasedMs;
    if (last != null && now - last < releaseFieldMs) {
      final wait = (releaseFieldMs - (now - last) + 999) ~/ 1000;
      throw _tooSoon('a RELEASE was sent a moment ago; try again in $wait s');
    }
    final timeS = min(0xffffffff, wall.floor());
    if (!boxes.release(liveId, timeS)) {
      return {'live_game': liveId, 'time': timeS, 'release_frame': 'no_radio'};
    }
    fieldReleasedMs = now;
    return {'live_game': liveId, 'time': timeS, 'release_frame': 'sent'};
  }

  /// Whether [wallS] can be the right time (wallclock.py `plausible`): not
  /// under [clockFloorS], nor under the newest time in the store's games,
  /// less [clockToleranceS].
  bool clockPlausible(double wallS) {
    var floor = clockFloorS.toDouble();
    for (final g in _store.games()) {
      for (final k in const ['created_at', 'started_at', 'ended_at']) {
        final v = g[k];
        if (v is num && v > floor) floor = v.toDouble();
      }
    }
    return wallS >= floor - clockToleranceS;
  }

  /// The games a box was heard still in, the most recent first, with their
  /// names.
  List<Map<String, Object?>> public() {
    final now = engine.nowMs();
    games.removeWhere((_, s) => now - s.heardMs > stuckForgetMs);
    _released.removeWhere((_, t) => now - t > releaseMs);
    final list = games.values.toList()
      ..sort((a, b) => b.heardMs.compareTo(a.heardMs));
    return [
      for (final s in list)
        s.public(now, _store.game(s.gameId)?['name'] as String?),
    ];
  }

  static ControllerError _tooSoon(String message) =>
      ControllerError(message, status: 429);
}

/// Keeps the key tags of the [keep] most recent ended games and of every
/// live one (stuck_games.py `prune_key_tags`).
void pruneKeyTags(ControllerStore store, {int keep = keyTagsKept}) {
  final ended = [
    for (final g in store.games())
      if (g['state'] == 'ended' &&
          store.getSetting('key_tag:${g['id']}') != null)
        g['id']! as int,
  ];
  final drop = ended.length - keep;
  for (final id in ended.take(drop > 0 ? drop : 0)) {
    store.deleteSetting('key_tag:$id');
  }
}
