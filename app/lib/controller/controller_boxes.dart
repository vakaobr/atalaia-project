// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Re-inviting boxes into the next game over the radio, and GAME_OVER
/// (protocol/field-frames.md; decisions RJ-1 to RJ-15, OT-13 to OT-16), on
/// the Android field controller (slice S7c of PE24, decision PE24-90): the
/// Pi controller's controller/atalaia_controller/reinvite.py and the
/// controller's side of simulator/atalaia_sim/lobby.py (`Inviter`), in Dart.
///
/// A box whose game is over announces itself in field frames sealed with a
/// key derived from the field join key; the radio (an I/O pod that relays
/// them, or a USB radio modem: decisions PE24-91, PE24-92) hands them over
/// as they are. The controller keeps the free boxes it has heard for two
/// hours (with the box's newest nonce, so a replayed announcement is
/// refused), sends a DISCOVER when the GM opens the console's box picker
/// (at most every 10 s), and invites the boxes the GM picks into the live
/// game before it starts: for each, a join payload made exactly as for a
/// card ([ControllerEngine.issueJoin]), cut into one to three INVITE parts
/// for the box's device id and the token of its last announcement, paced by
/// their time on air, sent again after 6 s unanswered, three times at most.
/// The box's answer sets it accepted or refused, its HELLO in the game
/// joined. Nothing here is stored: invites last as long as the controller
/// runs.
///
/// When a game ends, GAME_OVER (its id and its key's tag) goes three times,
/// 4 s apart, on the game's channel (the radio tuned there and back to the
/// field's channel while no game is live), so its boxes leave it also when
/// the controller restarted without the game's key.
///
/// The controller's nonces (decision RJ-15): a sender id drawn from
/// Random.secure at every start and never stored, boot 1 and the frame
/// count, then boot 2 after 65,536 frames, within the run.
library;

import 'dart:math';
import 'dart:typed_data';

import '../protocol/field_frame.dart';
import '../security/bytes.dart';
import 'controller_engine.dart';

const announceMinMs = 60000;
const inviteRetryMs = 6000;
const inviteAttempts = 3;
const discoverMinMs = 10000;
const boxForgetMs = 2 * 3600000;
const _gapMs = 50; // between the controller's frames, on top of their air
const _partGapMs = 150; // between an invite's parts (the box re-arms)
const gameOverRepeats = 3;
const gameOverGapMs = 4000;

// MOVE (RFC 0001 Amendment 19, lobby.py): the field's channel changed. Said on
// the old channel three times; a sweep says it twice on each earlier channel.
const moveRepeats = 3;
const moveGapMs = 2500;
const sweepRepeats = 2;
const sweepAfterDiscoverMs = 4000;
const sweepMinMs = 60000;

/// LoRa time on air at SF7/125 kHz (explicit header, CRC, CR 4/5, an
/// 8-symbol preamble): eu868.py `airtime_ms`, core/src/duty_cycle.c.
double airtimeMs(int packetBytes, {int sf = 7, int bwHz = 125000}) {
  final tSymUs = (1 << sf) * 1000000 ~/ bwHz;
  final tPreambleUs = 1225 * tSymUs ~/ 100;
  final de = sf >= 11 ? 1 : 0;
  final num = 8 * packetBytes - 4 * sf + 28 + 16;
  final den = 4 * (sf - 2 * de);
  final symbols = num <= 0 ? 8 : 8 + (num + den - 1) ~/ den * 5;
  return (tPreambleUs + symbols * tSymUs) / 1000.0;
}

/// A free box as its last announcement told it.
class BoxSeen {
  BoxSeen({
    required this.deviceId,
    required this.name,
    required this.tier,
    required this.token,
    required this.seenMs,
    this.lastGame,
    this.lastRole,
    this.batteryPct,
    this.rssi,
    this.snr,
  });

  final Uint8List deviceId;
  final String name;
  final int tier;
  final Uint8List token;
  final int seenMs;
  final int? lastGame;
  final String? lastRole;
  final int? batteryPct;
  final int? rssi;
  final int? snr;

  Map<String, Object?> public(int nowMs) => {
    'device_id': hexEncode(deviceId),
    'name': name,
    'tier': tier,
    'last_game': lastGame,
    'last_role': lastRole,
    'battery_pct': batteryPct,
    'rssi': rssi,
    'snr': snr,
    'seen_s_ago': max(0, (nowMs - seenMs) ~/ 1000),
  };
}

/// An invite on its way: sending, invited, accepted, joined, refused, failed.
class BoxInvite {
  BoxInvite({
    required this.deviceId,
    required this.inviteId,
    required this.gameId,
    required this.nodeId,
    required this.role,
    required this.payload,
    required this.nextMs,
    this.name,
  });

  final Uint8List deviceId;
  final int inviteId;
  final int gameId;
  final int nodeId;
  final String role;
  final Uint8List payload;
  final String? name;
  String status = 'sending';
  String? detail;
  int attempts = 0;
  int nextMs;
  final tx = <int>{};
  final pending = <Uint8List>[];

  int get parts => splitJoin(payload).length;

  Map<String, Object?> public() => {
    'device_id': hexEncode(deviceId),
    'game': gameId,
    'node_id': nodeId,
    'role': role,
    'name': name,
    'status': status,
    'detail': detail,
    'attempts': attempts,
    'parts': parts,
    'bytes': payload.length,
  };
}

class _GameOver {
  _GameOver(this.gameId, this.keyTag, this.channelHz, this.nextMs);
  final int gameId;
  final Uint8List keyTag;
  final int? channelHz;
  int left = gameOverRepeats;
  int nextMs;
  int sent = 0;
}

/// A MOVE on its way: sent on [channelHz] (where the boxes still listen),
/// naming the new channel [toHz] and its revision [rev].
class _Move {
  _Move(
    this.channelHz,
    this.toHz,
    this.rev,
    this.left,
    this.nextMs,
    this.gapMs,
  );
  final int channelHz;
  final int toHz;
  final int rev;
  int left;
  int nextMs;
  final int gapMs;
  int sent = 0;
}

/// The controller's side of the field frames (lobby.py `Inviter`). [send]
/// puts a frame on air and returns an id for its outcome
/// ([onTxResult]), or null when the radio refused it at once.
class FieldInviter {
  FieldInviter(
    List<int> joinKey,
    this.send, {
    Random? random,
    FieldNonceSource? nonces,
  }) : key = fieldKey(joinKey),
       _nkey = fieldNonceKey(joinKey),
       _random = random ?? Random.secure(),
       nonces =
           nonces ??
           FieldNonceSource(
             joinKey,
             List.generate(ffSenderSize, (_) => Random.secure().nextInt(256)),
           );

  final Uint8List key;
  final Uint8List _nkey;
  final FieldNonceSource nonces;
  final int? Function(Uint8List frame) send;
  final Random _random;
  final boxes = <String, BoxSeen>{};
  final invites = <String, BoxInvite>{};
  var busyUntil = 0;
  int? lastDiscover;

  /// Frames that did not open (another field's, strangers'), and
  /// announcements older than one heard from that box (replays).
  var ignored = 0;
  var stale = 0;
  final _fresh = <String, (int, int)>{};
  final _gamesOver = <_GameOver>[];
  final _moves = <_Move>[];
  int? lastSweep;

  /// A GAME_OVER or a MOVE is still to be sent.
  bool get ordersPending => _gamesOver.isNotEmpty || _moves.isNotEmpty;

  /// Called once no GAME_OVER or MOVE is left to send (after `tune(null)`):
  /// the controller's next step, a DISCOVER on the field's channel.
  void Function()? onOrdersDone;

  /// "boxes" or "invites" changed.
  void Function(String what)? onChange;

  /// A GAME_OVER's channel before it is sent (false: drop it, the radio is
  /// busy elsewhere), and null once none is left (the radio goes back).
  bool Function(int? channelHz)? tune;

  void _changed(String what) => onChange?.call(what);

  // --- hearing ----------------------------------------------------------------

  Map<String, Object?>? onFrame(
    Uint8List raw,
    int nowMs, {
    int? rssi,
    int? snr,
  }) {
    final Map<String, Object?> msg;
    try {
      msg = decodeFieldFrame(key, raw);
    } on FieldFrameException {
      ignored++;
      return null;
    }
    if (msg['kind'] != 'announce') return msg;
    final device = msg['device_id']! as Uint8List;
    final hexid = hexEncode(device);
    // Fresh only: a box's nonces carry its pseudonym and a rising
    // (boot, ctr) (decision RJ-15).
    final nonce = raw.sublist(rfHeaderSize, rfHeaderSize + ffNonceSize);
    final seq = (
      nonce[8] << 16 | nonce[9] << 8 | nonce[10],
      nonce[11] << 8 | nonce[12],
    );
    final pseudonym = fieldNonce(_nkey, device, 0, 0).sublist(0, 8);
    final last = _fresh[hexid] ?? (0, -1);
    final newer = seq.$1 > last.$1 || (seq.$1 == last.$1 && seq.$2 > last.$2);
    if (!constantTimeEquals(nonce.sublist(0, 8), pseudonym) || !newer) {
      stale++;
      return null;
    }
    _fresh[hexid] = seq;
    boxes[hexid] = BoxSeen(
      deviceId: device,
      name: msg['name']! as String,
      tier: msg['tier']! as int,
      token: msg['token']! as Uint8List,
      seenMs: nowMs,
      lastGame: msg['last_game'] as int?,
      lastRole: msg['last_role'] as String?,
      batteryPct: msg['battery_pct'] as int?,
      rssi: rssi,
      snr: snr,
    );
    final inv = invites[hexid];
    if (inv != null &&
        msg['answer'] == inv.inviteId &&
        (inv.status == 'sending' || inv.status == 'invited')) {
      if (msg['result'] == 'accepted') {
        inv
          ..status = 'accepted'
          ..detail = null;
      } else {
        inv
          ..status = 'refused'
          ..detail = msg['result'] as String?;
      }
      _changed('invites');
    }
    _changed('boxes');
    return msg;
  }

  /// A HELLO in the game ([gameId]: the live game's; only its invites).
  BoxInvite? onHello(int nodeId, Uint8List? deviceId, {int? gameId}) {
    for (final inv in invites.values) {
      if (gameId != null && inv.gameId != gameId) continue;
      if (inv.nodeId == nodeId &&
          (deviceId == null || constantTimeEquals(deviceId, inv.deviceId)) &&
          const [
            'sending',
            'invited',
            'accepted',
            'failed',
          ].contains(inv.status)) {
        inv
          ..status = 'joined'
          ..detail = null;
        boxes.remove(hexEncode(inv.deviceId)); // in a game now
        _changed('invites');
        _changed('boxes');
        return inv;
      }
    }
    return null;
  }

  void onTxResult(int txId, String status) {
    for (final inv in invites.values) {
      if (inv.tx.remove(txId) &&
          status != 'ok' &&
          (inv.status == 'sending' || inv.status == 'invited')) {
        inv.detail = 'radio: $status';
        _changed('invites');
      }
    }
  }

  // --- sending ----------------------------------------------------------------

  List<BoxSeen> available(int nowMs) {
    boxes.removeWhere((_, b) => nowMs - b.seenMs > boxForgetMs);
    final out = boxes.values.toList()
      ..sort((a, b) {
        final c = a.name.compareTo(b.name);
        return c != 0
            ? c
            : hexEncode(a.deviceId).compareTo(hexEncode(b.deviceId));
      });
    return out;
  }

  bool discover(int nowMs, {bool force = false}) {
    final last = lastDiscover;
    if (!force && last != null && nowMs - last < discoverMinMs) return false;
    final frame = encodeFieldFrame(key, {'kind': 'discover'}, nonces.next());
    lastDiscover = nowMs;
    busyUntil =
        max(busyUntil, nowMs) + airtimeMs(frame.length).toInt() + _gapMs;
    return send(frame) != null;
  }

  BoxInvite invite(
    Uint8List deviceId,
    Uint8List payload, {
    required int gameId,
    required int nodeId,
    required String role,
    required int nowMs,
    String? name,
  }) {
    final hexid = hexEncode(deviceId);
    if (!boxes.containsKey(hexid)) {
      throw InviteException('box $hexid has not announced itself');
    }
    if (payload.isEmpty || payload.length > ffJoinMax) {
      throw InviteException(
        'a join payload of ${payload.length} bytes does not fit in '
        '$ffPartsMax parts',
      );
    }
    final inv = BoxInvite(
      deviceId: deviceId,
      inviteId: 1 + _random.nextInt(0xffff),
      gameId: gameId,
      nodeId: nodeId,
      role: role,
      payload: payload,
      nextMs: nowMs,
      name: name,
    );
    invites[hexid] = inv;
    _changed('invites');
    return inv;
  }

  /// Says [gameOverRepeats] times, [gameOverGapMs] apart, that [gameId]
  /// (its key's [keyTag]) is over.
  void gameOver(int gameId, Uint8List keyTag, int nowMs, {int? channelHz}) {
    validateFieldMessage({
      'kind': 'game_over',
      'game_id': gameId,
      'key_tag': keyTag,
    });
    _gamesOver
      ..removeWhere((g) => g.gameId == gameId)
      ..add(_GameOver(gameId, keyTag, channelHz, nowMs));
  }

  /// Says [repeats] times, [gapMs] apart, on [channelHz] (where the boxes
  /// still listen) that the field has moved to [toHz] (revision [rev]): the
  /// change itself, or one channel of a sweep.
  void move(
    int channelHz,
    int toHz,
    int rev,
    int nowMs, {
    int repeats = moveRepeats,
    int? startMs,
    int gapMs = moveGapMs,
  }) {
    validateFieldMessage({'kind': 'move', 'channel_hz': toHz, 'rev': rev});
    _moves.add(_Move(channelHz, toHz, rev, repeats, startMs ?? nowMs, gapMs));
  }

  /// MOVE on each earlier channel, one after the other (the radio is tuned
  /// once to each), for boxes that were away when the field moved: at most
  /// one sweep in [sweepMinMs]. False when there is nothing to do or it is
  /// too soon.
  bool sweep(
    List<int> channels,
    int toHz,
    int rev,
    int nowMs, {
    int delayMs = sweepAfterDiscoverMs,
  }) {
    final list = [
      for (final c in channels)
        if (c != toHz) c,
    ];
    final last = lastSweep;
    if (list.isEmpty ||
        (last != null && nowMs - last < sweepMinMs) ||
        _moves.isNotEmpty) {
      return false;
    }
    lastSweep = nowMs;
    var at = nowMs + delayMs;
    for (final ch in list) {
      move(ch, toHz, rev, nowMs, repeats: sweepRepeats, startMs: at);
      at += sweepRepeats * moveGapMs + 500;
    }
    return true;
  }

  /// Sends the next GAME_OVER or MOVE that is due; true if the radio was used.
  bool _tickGameOver(int nowMs) {
    final done = <Object>[
      for (final g in _gamesOver)
        if (g.left == 0 && nowMs >= g.nextMs) g,
      for (final m in _moves)
        if (m.left == 0 && nowMs >= m.nextMs) m,
    ];
    if (done.isNotEmpty) {
      _gamesOver.removeWhere(done.contains);
      _moves.removeWhere(done.contains);
      if (_gamesOver.isEmpty && _moves.isEmpty) {
        tune?.call(null);
        onOrdersDone?.call();
      }
    }
    final due = <Object>[
      for (final g in _gamesOver)
        if (g.left > 0 && nowMs >= g.nextMs) g,
      for (final m in _moves)
        if (m.left > 0 && nowMs >= m.nextMs) m,
    ];
    if (due.isEmpty || nowMs < busyUntil) return false;
    final order = due.first;
    final t = tune;
    final channel = order is _Move
        ? order.channelHz
        : (order as _GameOver).channelHz;
    if (t != null && !t(channel)) {
      if (order is _Move) {
        _moves.remove(order);
      } else {
        _gamesOver.remove(order as _GameOver);
      }
      return false;
    }
    final Map<String, Object?> msg;
    final int gap;
    if (order is _Move) {
      msg = {'kind': 'move', 'channel_hz': order.toHz, 'rev': order.rev};
      gap = order.gapMs;
    } else {
      final go = order as _GameOver;
      msg = {'kind': 'game_over', 'game_id': go.gameId, 'key_tag': go.keyTag};
      gap = gameOverGapMs;
    }
    final frame = encodeFieldFrame(key, msg, nonces.next());
    final sent = send(frame) != null;
    final air = airtimeMs(frame.length).toInt();
    busyUntil = nowMs + air + _gapMs;
    if (order is _Move) {
      if (sent) order.sent++;
      order.left--;
      order.nextMs = nowMs + air + (order.left > 0 ? gap : _gapMs);
    } else {
      final go = order as _GameOver;
      if (sent) go.sent++;
      go.left--;
      go.nextMs = nowMs + air + (go.left > 0 ? gap : _gapMs);
    }
    return true;
  }

  void forgetGame(int gameId) {
    invites.removeWhere((_, i) => i.gameId == gameId);
    _changed('invites');
  }

  /// Sends the next frame that is due (one at a time, paced by time on air).
  void tick(int nowMs) {
    var changed = false;
    for (final inv in invites.values) {
      if (inv.status == 'invited' &&
          nowMs >= inv.nextMs &&
          inv.attempts >= inviteAttempts) {
        inv
          ..status = 'failed'
          ..detail = inv.detail ?? 'no answer';
        changed = true;
      }
    }
    if (changed) _changed('invites');
    if (_tickGameOver(nowMs) || nowMs < busyUntil) return;
    final due = [
      for (final i in invites.values)
        if ((i.status == 'sending' || i.status == 'invited') &&
            nowMs >= i.nextMs &&
            i.attempts < inviteAttempts)
          i,
    ];
    if (due.isEmpty) return;
    due.sort((a, b) {
      final c = a.nextMs.compareTo(b.nextMs);
      return c != 0 ? c : a.inviteId.compareTo(b.inviteId);
    });
    final inv = due.first;
    final box = boxes[hexEncode(inv.deviceId)];
    if (box == null) {
      inv
        ..status = 'failed'
        ..detail = 'the box is no longer announcing itself';
      _changed('invites');
      return;
    }
    if (inv.pending.isEmpty) {
      // A new attempt: all its parts, one per tick.
      inv.pending.addAll(
        inviteFrames(
          key,
          nonces,
          inv.deviceId,
          box.token,
          inv.inviteId,
          inv.payload,
        ),
      );
      inv.detail = null;
    }
    final frame = inv.pending.removeAt(0);
    final txId = send(frame);
    if (txId != null) {
      inv.tx.add(txId);
    } else {
      inv.detail = 'radio: not sent';
    }
    final air = airtimeMs(frame.length).toInt();
    if (inv.status != 'invited') {
      inv.status = 'invited';
      _changed('invites');
    }
    if (inv.pending.isNotEmpty) {
      busyUntil = nowMs + air + _partGapMs;
      inv.nextMs = busyUntil;
      return;
    }
    inv.attempts++;
    busyUntil = nowMs + air + _gapMs;
    inv.nextMs = nowMs + air + inviteRetryMs;
    _changed('invites');
  }
}

class InviteException implements Exception {
  InviteException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// The phone controller's free boxes, invites and GAME_OVER (reinvite.py
/// `Reinvite`), on the engine's radio. Made only with a field join key.
class ControllerBoxes {
  ControllerBoxes(this.engine, {Random? random}) {
    if (engine.joinKey.length != 32) {
      throw ArgumentError('the boxes need the field join key');
    }
    inviter = FieldInviter(engine.joinKey, _send, random: random)
      ..onChange = _pending.add
      ..tune = _tune
      ..onOrdersDone = _ordersDone;
    engine.boxes = this;
  }

  final ControllerEngine engine;
  late final FieldInviter inviter;
  final _pending = <String>{};
  int? _tuned; // the channel a GAME_OVER or a MOVE took the radio to
  bool _discoverAfter = false; // a DISCOVER on the field's channel after a MOVE

  int? _send(Uint8List frame) {
    final m = engine.modem;
    if (m == null || !m.isUp) return null;
    return m.sendField(frame);
  }

  // --- the radio ------------------------------------------------------------

  void onFieldRx(Uint8List frame, int rssi, int snr) {
    inviter.onFrame(frame, engine.nowMs(), rssi: rssi, snr: snr);
    _flush();
  }

  void onFieldAck(int id, String status) {
    inviter.onTxResult(id, status);
    _flush();
  }

  void tick(int nowMs) {
    inviter.tick(nowMs);
    if (_discoverAfter && !inviter.ordersPending) {
      _discoverAfter = false; // the MOVEs were dropped (a game took the radio)
    }
    _flush();
  }

  /// A HELLO in the live game: an invite for that node is done.
  void onHello(int nodeId, String? deviceHex) {
    final g = engine.liveGame;
    inviter.onHello(
      nodeId,
      deviceHex == null ? null : hexDecode(deviceHex),
      gameId: g?['id'] as int?,
    );
    _flush();
  }

  /// Tells the game's boxes it is over (GAME_OVER, decision OT-13); false
  /// without a radio that carries field frames.
  bool gameOver(int gameId, Uint8List keyTag, int? channelHz) {
    final m = engine.modem;
    if (m == null || !m.isUp || !m.hasFieldFrames) return false;
    inviter
      ..gameOver(gameId, keyTag, engine.nowMs(), channelHz: channelHz)
      ..tick(engine.nowMs()); // the first one at once
    _flush();
    return true;
  }

  /// The field's channel changed: says so on the old one (MOVE, three times,
  /// RFC 0001 Amendment 19) before the radio goes to the new one, then asks the
  /// boxes there. False when it cannot (no radio with field frames): the caller
  /// retunes at once.
  bool fieldMoved(int oldHz, int newHz, int rev) {
    final m = engine.modem;
    if (m == null || !m.isUp || !m.hasFieldFrames) return false;
    inviter.move(oldHz, newHz, rev, engine.nowMs());
    _discoverAfter = true;
    inviter.tick(engine.nowMs()); // the first one at once
    _flush();
    return true;
  }

  /// The GAME_OVERs and MOVEs are said and the radio is back on the field's
  /// channel: after a MOVE, a DISCOVER there makes every free box announce
  /// itself.
  void _ordersDone() {
    if (!_discoverAfter) return;
    _discoverAfter = false;
    final m = engine.modem;
    if (m != null && m.isUp && engine.liveGame == null) {
      inviter.discover(engine.nowMs(), force: true);
    }
  }

  bool _tune(int? channelHz) {
    final m = engine.modem;
    final field = engine.fieldChannel;
    if (channelHz == null) {
      if (_tuned != null && engine.liveGame == null && m != null && m.isUp) {
        m.setChannel(field);
        engine.modemMoved('a game over was told on its game\'s channel');
      }
      _tuned = null;
      return true;
    }
    final g = engine.liveGame;
    if (g != null) {
      return ((g['channel_hz'] as int?) ?? field) == channelHz;
    }
    if (channelHz != field && _tuned != channelHz && m != null) {
      m.setChannel(channelHz);
      engine.modemMoved('a game over is told on its game\'s channel');
      _tuned = channelHz;
    }
    return true;
  }

  /// The game ended: its invites go (no more retries into it).
  void forgetGame(int gameId) {
    inviter.forgetGame(gameId);
    _flush();
  }

  /// Tells the consoles what changed.
  void _flush() {
    final pending = Set.of(_pending);
    _pending.clear();
    if (pending.contains('boxes')) {
      engine.emit({'type': 'boxes', 'boxes': boxes()['boxes']});
    }
    final g = engine.liveGame;
    if (pending.contains('invites') && g != null) {
      final gid = g['id']! as int;
      final list = invites(gid);
      engine.emit({'type': 'invites', 'game': gid, 'invites': list});
      // A box fetching its modes, or one that could not (slice S7b).
      engine.modeFetch?.onInvites(list);
    }
  }

  /// A box's mode fetch changed whether its HELLO joined it
  /// (controller_mode_fetch.dart): the consoles are told.
  void refreshInvites() {
    _pending.add('invites');
    _pending.add('boxes');
    _flush();
  }

  // --- what the console shows -------------------------------------------------

  /// The most recent game other than the live one with boxes that said
  /// their device id.
  Map<String, Object?>? previousGame() {
    final live = engine.liveGame?['id'];
    final games = engine.store.games();
    for (final game in games.reversed) {
      if (game['id'] == live) continue;
      final roles = <String, String>{
        for (final n in engine.store.nodes(game['id']! as int))
          if (n['device_id'] is String)
            n['device_id']! as String: '${n['role']}',
      };
      if (roles.isNotEmpty) {
        return {
          'id': game['id'],
          'name': game['name'],
          'mode_id': game['mode_id'],
          'boxes': roles,
        };
      }
    }
    return null;
  }

  /// Device id -> node id of the boxes the live game has heard: not a box
  /// whose mode fetch has not ended in its HELLO (it said HELLO only to tell
  /// that its fetch failed; the GM may invite it again, P5D-17).
  Map<String, int> _inLiveGame() {
    final g = engine.liveGame;
    if (g == null) return {};
    final mf = engine.modeFetch;
    return {
      for (final n in engine.nodes(g['id']! as int))
        if (n['device_id'] is String &&
            (mf == null || !mf.holds(n['node_id']! as int)))
          n['device_id']! as String: n['node_id']! as int,
    };
  }

  Map<String, Object?> boxes() {
    final now = engine.nowMs();
    final prev = previousGame();
    final prevBoxes = (prev?['boxes'] as Map<String, String>?) ?? const {};
    final live = _inLiveGame();
    final out = <Map<String, Object?>>[];
    for (final box in inviter.available(now)) {
      final entry = box.public(now);
      final hexid = entry['device_id']! as String;
      entry['previous'] = prevBoxes.containsKey(hexid);
      entry['previous_role'] = prevBoxes[hexid] ?? entry['last_role'];
      entry['node_id'] = live[hexid];
      entry['invite'] = inviter.invites[hexid]?.public();
      out.add(entry);
    }
    final m = engine.modem;
    return {
      'boxes': out,
      'previous_game': prev == null
          ? null
          : {
              for (final e in prev.entries)
                if (e.key != 'boxes') e.key: e.value,
            },
      'radio': m != null && m.isUp,
      'field_frames': m != null && m.hasFieldFrames,
      'ignored': inviter.ignored,
      'stale': inviter.stale,
    };
  }

  /// The live game's invites as the console shows them: not *joined* while
  /// a box's mode fetch has not ended in its HELLO (slice S7b).
  List<Map<String, Object?>> invites(int gameId) => [
    for (final i in inviter.invites.values)
      if (i.gameId == gameId) _view(i.public()),
  ];

  Map<String, Object?> _view(Map<String, Object?> inv) =>
      engine.modeFetch?.inviteView(inv) ?? inv;

  // --- what the GM does -------------------------------------------------------

  Map<String, Object?> discover() {
    final m = engine.modem;
    if (m == null || !m.isUp) {
      throw ControllerError.unavailable(
        'the radio modem is ${engine.radioState}: no DISCOVER sent',
      );
    }
    final now = engine.nowMs();
    final sent = inviter.discover(now);
    // Boxes that were away when the field's channel changed still listen on an
    // earlier one: a MOVE on each (a few seconds after the DISCOVER, so its
    // answers are heard first), then another DISCOVER here. Only between
    // games, and at most once a minute.
    final history = engine.liveGame == null
        ? (engine.channel?.history() ?? <int>[])
        : <int>[];
    final sweep =
        history.isNotEmpty &&
        inviter.sweep(
          history,
          engine.fieldChannel,
          engine.channel?.moveRev() ?? 1,
          now,
        );
    if (sweep) _discoverAfter = true;
    return {'sent': sent, 'sweep': sweep ? history : <int>[]};
  }

  /// Invites boxes into the live game: [{"device_id", "role"?, "name"?,
  /// "fetch_modes"?}, ...] (reinvite.py `invite`).
  Map<String, Object?> invite(int gameId, Object? specs) {
    final game = engine.liveGame;
    if (game == null || game['id'] != gameId) {
      throw ControllerError.conflict('game $gameId is not the live game');
    }
    if (game['state'] != 'ready') {
      throw ControllerError.conflict(
        "game $gameId is ${game['state']}: boxes are invited before it starts",
      );
    }
    final m = engine.modem;
    if (m == null || !m.isUp) {
      throw ControllerError.unavailable(
        'the radio modem is ${engine.radioState}: no invite can be sent',
      );
    }
    if (specs is! List || specs.isEmpty || specs.length > 64) {
      throw ControllerError('boxes: a list of 1-64 {device_id, role?, name?}');
    }
    final now = engine.nowMs();
    // Invites and refusals, in order; an invite's view once the first went.
    final out = <Object>[];
    for (final spec in specs) {
      final deviceHex = spec is Map ? spec['device_id'] : null;
      if (spec is! Map || deviceHex is! String || deviceHex.length != 16) {
        throw ControllerError(
          'each box: {device_id: 16 hex digits, role?, name?}',
        );
      }
      final hexid = deviceHex.toLowerCase();
      final Uint8List device;
      try {
        device = hexDecode(hexid);
      } on FormatException {
        throw ControllerError('device_id "$hexid": 16 hex digits');
      }
      if (!inviter.boxes.containsKey(hexid)) {
        out.add({
          'device_id': hexid,
          'status': 'failed',
          'detail': 'not announcing itself',
        });
        continue;
      }
      if (_inLiveGame().containsKey(hexid)) {
        out.add({
          'device_id': hexid,
          'status': 'joined',
          'detail': 'already in this game',
        });
        continue;
      }
      final existing = inviter.invites[hexid];
      final joinSpec = <String, Object?>{'kind': 'node', 'role': spec['role']};
      if (spec['name'] != null) joinSpec['name'] = spec['name'];
      final fetch = spec['fetch_modes'] ?? false;
      if (fetch is! bool) throw ControllerError('fetch_modes: true or false');
      // Join key 16: the box fetches the parts it lacks; key 17 for a box
      // the GM marked to forget its fetched modes (slice S7b).
      final mf = engine.modeFetch;
      if (fetch) joinSpec['fetch_modes'] = true;
      if (mf != null && mf.forgetMarked().contains(hexid)) {
        joinSpec['forget_modes'] = true;
      }
      // The same node id when the box is invited again into this game.
      final nodeId = existing != null && existing.gameId == gameId
          ? existing.nodeId
          : null;
      final Map<String, Object?> made;
      try {
        made = engine.issueJoin(
          joinSpec,
          nodeIdValue: nodeId,
          sameDevice: nodeId != null,
          device: hexid,
          tier: inviter.boxes[hexid]?.tier,
        );
      } on ControllerError catch (e) {
        if (!fetch || e.status != 409) rethrow;
        // This box cannot be sent the modes (a Reduced box, a part not
        // offered...): said for it alone, the others are still invited.
        out.add({
          'device_id': hexid,
          'status': 'not_sent',
          'detail': e.message,
        });
        continue;
      }
      final payload = hexDecode(made['payload_hex']! as String);
      try {
        final inv = inviter.invite(
          device,
          payload,
          gameId: gameId,
          nodeId: made['node_id']! as int,
          role: made['role']! as String,
          nowMs: now,
          name: made['name'] as String?,
        );
        out.add(inv);
      } on InviteException catch (e) {
        out.add({'device_id': hexid, 'status': 'too_big', 'detail': e.message});
      }
    }
    inviter.tick(
      now,
    ); // the first one goes at once; the others as the air allows
    _flush();
    return {
      'invites': [for (final o in out) o is BoxInvite ? _view(o.public()) : o],
    };
  }
}
