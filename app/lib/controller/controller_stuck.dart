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
/// forged from a header in the clear can cost some air, never a game; that
/// air is bounded (decisions SRB-1 to SRB-6): no automatic burst while a game
/// is started (running or paused), so its TIME and CMD keep the radio's duty
/// budget (the GM's Release still works); otherwise one automatic burst for
/// all games together in [stuckAutoResendMs], one at a time, the game served
/// longest ago first, and one that takes the radio off the field's channel in
/// [stuckAutoRetuneMs]. Each game keeps the [stuckSourcesKept] node ids heard
/// most recently, with a count. An I/O
/// pod passes no OTHER_GAME on: with it (or an older modem) `stuck_watch` is
/// false, and the console's hint fits the radio (`radio_kind`, STUCK-64):
/// update an older modem's firmware, or use a USB radio modem for a pod.
///
/// A standby never sends it (its games run on the primary). What was heard is
/// kept for the console (`stuck` in GET /api/v1/boxes, and the stream's
/// `boxes` message): per game, when a box in it was last heard, from which
/// node ids, and how many times its GAME_OVER went again. The GM's console
/// lists the games heard within [stuckShownMs] (STUCK-71) and can say a
/// game's GAME_OVER at once ([release], the Release button, POST
/// /api/v1/boxes/stuck/{game}/release) within a short rate limit, and can tell every box of the field on this channel that is in a
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

/// The console lists a game heard within this time (STUCK-71): a box in a
/// game sends STATE every 15 s and the modem reports a game at most every
/// 10 s, so a box still in it is heard well within two minutes; a freed box,
/// or one switched off, is silent and leaves the list.
const stuckShownMs = 120000;

/// A game not heard of for this long is forgotten: until then a box heard
/// again keeps its game's resend count and once-a-minute limit.
const stuckForgetMs = 2 * 3600000;

/// The ended games whose key tag the controller keeps.
const keyTagsKept = 50;

/// One automatic burst for all games together in this time at most (SRB-2).
const stuckAutoResendMs = 60000;

/// One automatic burst off the field's channel in this time at most (SRB-3).
const stuckAutoRetuneMs = 300000;

/// The node ids a game keeps (the most recently heard), with a count (SRB-4).
const stuckSourcesKept = 32;

/// A started game: no automatic burst (SRB-1).
const stuckLiveStates = {'running', 'paused'};

/// A game a box was heard still in.
class StuckGame {
  StuckGame(this.gameId, this.heardMs);
  final int gameId;
  int heardMs;

  /// The node ids heard, the most recently heard last (a LinkedHashSet).
  final sources = <int>{};
  int sourcesDropped = 0;
  int? rssi;
  int resent = 0;
  int? resentMs;

  /// A node id heard: kept among the [stuckSourcesKept] most recent (SRB-4).
  void hear(int source) {
    sources
      ..remove(source)
      ..add(source);
    while (sources.length > stuckSourcesKept) {
      sources.remove(sources.first);
      sourcesDropped++;
    }
  }

  Map<String, Object?> public(int nowMs, String? name) => {
    'game': gameId,
    'name': name,
    'last_heard_s': max(0, (nowMs - heardMs) ~/ 1000),
    'nodes': sources.toList()..sort(),
    'nodes_count': sources.length + sourcesDropped,
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

  var autoResendMs = stuckAutoResendMs;
  var autoRetuneMs = stuckAutoRetuneMs;

  /// When the last burst (automatic or released) went, and the last
  /// automatic one off the field's channel.
  int? autoMs;
  int? retuneMs;

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
      ..hear(other.source);
    // The consoles' list carries the stuck games: told of a new one, and of
    // each resend (decision STUCK-63).
    if (_resendNext(now) || fresh) boxes.refreshBoxes();
  }

  /// One automatic GAME_OVER burst, if the air budget allows (decisions
  /// SRB-1 to SRB-3): none while a game is started on this controller, none
  /// while any GAME_OVER is still being said, one for all games together in
  /// [autoResendMs], and one that takes the radio off the field's channel in
  /// [autoRetuneMs]. Of the games heard within [stuckShownMs] that may go
  /// (each at most once in [resendMs]), the one served longest ago goes, so
  /// forged reports for many games cannot keep a real one waiting for ever.
  /// True when a burst went.
  bool _resendNext(int now) {
    final live = engine.liveGame;
    // Its TIME and CMD keep the duty budget; the GM can still Release.
    if (live != null && stuckLiveStates.contains(live['state'])) return false;
    // One burst at a time (the end's own three included).
    if (boxes.inviter.gamesOverPending) return false;
    final lastAuto = autoMs;
    if (lastAuto != null && now - lastAuto < autoResendMs) return false;
    final field = engine.fieldChannel;
    final liveHz = live == null
        ? null
        : ((live['channel_hz'] as int?) ?? field);
    final lastRetune = retuneMs;
    final retuneOk = lastRetune == null || now - lastRetune >= autoRetuneMs;
    StuckGame? best;
    (int, int)? bestOrder;
    int? bestChannel;
    String? bestTag;
    for (final s in games.values) {
      if (now - s.heardMs > stuckShownMs) continue;
      final last = s.resentMs;
      if (last != null && now - last < resendMs) continue;
      final game = _store.game(s.gameId);
      final tag = _store.getSetting('key_tag:${s.gameId}');
      if (game == null || game['state'] != 'ended' || tag == null) continue;
      final channel = _channelOf(game);
      if (liveHz != null) {
        // A game made on another channel: the burst would be dropped.
        if (liveHz != channel) continue;
      } else if (channel != field && !retuneOk) {
        continue;
      }
      final order = (last ?? -1, -s.heardMs);
      if (bestOrder == null ||
          order.$1 < bestOrder.$1 ||
          (order.$1 == bestOrder.$1 && order.$2 < bestOrder.$2)) {
        best = s;
        bestOrder = order;
        bestChannel = channel;
        bestTag = tag;
      }
    }
    if (best == null) return false;
    if (!boxes.gameOver(best.gameId, hexDecode(bestTag!), bestChannel)) {
      return false;
    }
    best
      ..resent += 1
      ..resentMs = now;
    autoMs = now;
    if (liveHz == null && bestChannel != field) retuneMs = now;
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
    autoMs = now; // the automatic minute starts again (SRB-2)
    boxes.refreshBoxes();
    return {'game': gameId, 'game_over_frame': 'sent'};
  }

  /// The field-wide RELEASE (POST /api/v1/boxes/release, RFC 0001
  /// Amendment 28, decisions STUCK-50 to STUCK-59), for a controller that
  /// lost the game a box is stuck in (a new install: no key tag, so no
  /// GAME_OVER can name it): every box in a game other than the live one (or
  /// any game, with none live) that it joined before now leaves it, on the
  /// radio's channel, which the frame names (the addendum of 2026-11-06).
  /// `release_frame`: "sent" or "no_radio". Refused: a standby (409), a wall
  /// clock that is not plausible or is ahead of what the controller can
  /// vouch for (409, [ClockGuard.releaseCheck]: the GM's device's
  /// [deviceTime], else the uncorrected system clock; decision RLB-4), and
  /// while one is being said or within [releaseFieldMs] of the last (429).
  Map<String, Object?> releaseField([Object? deviceTime]) {
    final live = engine.liveGame;
    if (_standby) {
      throw ControllerError.conflict(
        'this controller follows a game as a standby: a RELEASE would take the '
        "primary's boxes out of its game",
      );
    }
    // The engine's clock guard (controller_clock.dart, the Pi's
    // wallclock.py; decision STUCK-62 as changed by the maintainer, RLB-4).
    engine.clock.releaseCheck(deviceTime);
    final liveId = (live?['id'] as int?) ?? 0;
    final now = engine.nowMs();
    if (boxes.inviter.releasing) throw _tooSoon('a RELEASE is being sent now');
    final last = fieldReleasedMs;
    if (last != null && now - last < releaseFieldMs) {
      final wait = (releaseFieldMs - (now - last) + 999) ~/ 1000;
      throw _tooSoon('a RELEASE was sent a moment ago; try again in $wait s');
    }
    final timeS = min(0xffffffff, engine.wallSeconds().floor());
    final (sent, channel) = boxes.release(liveId, timeS);
    final out = {'live_game': liveId, 'time': timeS, 'channel_hz': channel};
    if (!sent) return {...out, 'release_frame': 'no_radio'};
    fieldReleasedMs = now;
    return {...out, 'release_frame': 'sent'};
  }

  /// The games a box was heard still in within [stuckShownMs], the most
  /// recent first, with their names (STUCK-71: a game whose boxes went
  /// silent, freed or switched off, is not shown).
  List<Map<String, Object?>> public() {
    final now = engine.nowMs();
    games.removeWhere((_, s) => now - s.heardMs > stuckForgetMs);
    _released.removeWhere((_, t) => now - t > releaseMs);
    final list =
        games.values.where((s) => now - s.heardMs <= stuckShownMs).toList()
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
