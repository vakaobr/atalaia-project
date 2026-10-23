// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Adopting a box by the code it shows, over the radio (protocol/adoption.md
/// section 7; decisions AD-15 to AD-27), on the Android field controller
/// (slice S7c of PE24, decision PE24-94): the Pi controller's
/// controller/atalaia_controller/pairing.py in Dart.
///
/// An unadopted box shows a 6-digit code and sends OFFER pair frames (type
/// 10, in the clear) on the default channel, 869.525 MHz; the radio hands
/// them over as field frames' siblings (FIELD_RX). The GM picks a box and
/// types its code: a run of CPace (security/cpace.dart) follows, START (Ya),
/// the box's REPLY (Yb and its confirmation), then, only if the box's
/// confirmation matches, KEY: the controller's confirmation and the field
/// join key and name sealed under a key from the run's ISK; the box adopts
/// the field by its own rules and answers DONE (its result and the
/// fingerprint of the key it now holds, authenticated). A wrong code shows
/// in the box's confirmation and the run ends there: the join key never
/// leaves without it.
///
/// KEY's nonce is the pseudonym of a sender id drawn fresh for every run,
/// boot 1, count 0. The run's scalar, sid and keys live only in memory and
/// are wiped on every outcome. One run at a time; three STARTs and three
/// KEYs at most, ten seconds each step. Every run is recorded with the other
/// adoptions (controller_adoption.dart). GM token only.
///
/// The radio listens on the field's channel. When that is not 869.525 MHz
/// and no game is live, "listen" tunes it there for five minutes (and back
/// afterwards); with a game live on another channel pairing waits.
library;

import 'dart:math';
import 'dart:typed_data';

import '../protocol/field_card.dart' show fieldFingerprint;
import '../protocol/pair_frame.dart';
import '../security/bytes.dart';
import '../security/cpace.dart';
import 'controller_engine.dart';

/// Where an unadopted box listens (its Kconfig default).
const pairChannelHz = 869525000;
const offerTtlMs = 60000;
const pairStepMs = 10000;
const pairResendMs = 3000;
const pairSendsMax = 3;
const pairListenMs = 300000;

class _Run {
  _Run({
    required this.pairId,
    required this.name,
    required this.sid,
    required this.yaSecret,
    required this.ya,
    required this.sender,
    required this.stepMs,
  });

  final Uint8List pairId;
  final String name;
  final Uint8List sid;
  Uint8List yaSecret;
  final Uint8List ya;
  final Uint8List sender;
  String state = 'starting'; // starting -> sealing -> done | failed
  String detail = '';
  String? result;
  PairKeys? keys;
  Uint8List frame = Uint8List(0);
  int sends = 0;
  int stepMs;
  int lastSendMs = 0;
  final txIds = <int>{};

  bool get active => state == 'starting' || state == 'sealing';

  Map<String, Object?> public() => {
    'pair_id': hexEncode(pairId),
    'name': name,
    'state': state,
    'detail': detail,
    'result': result,
    'sends': sends,
  };

  void wipe() {
    yaSecret.fillRange(0, yaSecret.length, 0);
    yaSecret = Uint8List(0);
    keys?.wipe();
    keys = null;
    frame = Uint8List(0);
  }
}

class ControllerPairing {
  ControllerPairing(this.engine, {Random? random})
    : _random = random ?? Random.secure() {
    if (engine.joinKey.length != 32) {
      throw ArgumentError('pairing needs the field join key');
    }
    engine.pairing = this;
  }

  final ControllerEngine engine;
  final Random _random;
  final offers = <String, Map<String, Object?>>{};
  _Run? _run;
  var _listenUntilMs = 0;
  var _retuned = false;
  var ignored = 0;

  Uint8List _bytes(int n) =>
      Uint8List.fromList(List.generate(n, (_) => _random.nextInt(256)));

  bool _modemOk() => engine.modem?.isUp ?? false;

  int? _send(Uint8List frame) =>
      _modemOk() ? engine.modem!.sendField(frame) : null;

  bool isOurs(Uint8List frame) => isPairFrame(frame);

  bool ownsTx(int id) => _run?.txIds.contains(id) ?? false;

  /// A pair frame heard (FIELD_RX).
  void onFrame(Uint8List frame, int rssi, int snr) {
    final Map<String, Object?> msg;
    try {
      msg = decodePairFrame(frame);
    } on PairFrameException {
      ignored++;
      return;
    }
    final now = engine.nowMs();
    final pid = msg['pair_id']! as Uint8List;
    final hexid = hexEncode(pid);
    if (msg['kind'] == 'offer') {
      final known = offers[hexid];
      if (known != null && known['name'] != msg['name']) {
        // A pair id is a box's for its whole pairing: the same id under
        // another name is someone else's frame (AD-26).
        known['conflict'] = true;
        ignored++;
        return;
      }
      offers[hexid] = {
        'pair_id': hexid,
        'name': msg['name'],
        'tier': msg['tier'],
        'rssi': rssi,
        'snr': snr,
        'seen_ms': now,
        'conflict': known?['conflict'] == true,
      };
      return;
    }
    final run = _run;
    if (run == null ||
        !run.active ||
        !constantTimeEquals(pid, run.pairId) ||
        msg['sid'] is! Uint8List ||
        !constantTimeEquals(msg['sid']! as Uint8List, run.sid)) {
      ignored++; // another run's, a replay, or nobody's
      return;
    }
    if (msg['kind'] == 'reply' && run.state == 'starting') {
      _onReply(run, msg, now);
    } else if (msg['kind'] == 'done' && run.state == 'sealing') {
      _onDone(run, msg, now);
    } else {
      ignored++;
    }
  }

  void onAck(int id, String status) {
    final run = _run;
    if (run == null || !run.txIds.remove(id)) return;
    if (status == 'duty_cycle') run.detail = 'duty_cycle';
  }

  void _transmit(_Run run, int now) {
    final tx = _send(run.frame);
    run
      ..sends += 1
      ..lastSendMs = now;
    if (tx != null) run.txIds.add(tx);
  }

  void _fail(_Run run, String detail, int now) {
    run
      ..state = 'failed'
      ..detail = detail
      ..wipe();
    _record(run);
  }

  void _onReply(_Run run, Map<String, Object?> msg, int now) {
    final yb = msg['point']! as Uint8List;
    final Uint8List k;
    try {
      k = x25519Verified(run.yaSecret, yb);
    } on CpaceException {
      _fail(run, 'bad_answer', now);
      return;
    }
    final keys = PairKeys(pairIsk(run.sid, k, run.ya, yb), run.sid);
    run.yaSecret.fillRange(0, run.yaSecret.length, 0);
    if (!constantTimeEquals(keys.tagReply, msg['tag']! as Uint8List)) {
      keys.wipe();
      _fail(run, 'wrong_code', now); // the box burns that code too
      return;
    }
    final nonce = keys.keyNonce(run.sender);
    final sealed = sealPairKey(
      keys,
      nonce,
      run.pairId,
      run.sid,
      engine.joinKey,
      engine.adoption?.fieldName() ?? '',
    );
    run
      ..keys = keys
      ..frame = encodePairFrame({
        'kind': 'key',
        'pair_id': run.pairId,
        'sid': run.sid,
        'tag': keys.tagKey,
        'nonce': nonce,
        'sealed': sealed,
      })
      ..state = 'sealing'
      ..sends = 0
      ..stepMs = now;
    _transmit(run, now);
  }

  void _onDone(_Run run, Map<String, Object?> msg, int now) {
    final keys = run.keys;
    final result = msg['result']! as String;
    final fp = msg['fingerprint']! as Uint8List;
    if (keys == null ||
        !constantTimeEquals(
          keys.tagDone(result, fp),
          msg['tag']! as Uint8List,
        )) {
      ignored++;
      return;
    }
    run.result = result;
    if (pfOkResults.contains(result) &&
        !constantTimeEquals(fp, fieldFingerprintBytes(engine.joinKey))) {
      run
        ..state = 'failed'
        ..detail = 'fingerprint';
    } else if (pfOkResults.contains(result)) {
      run.state = 'done';
      offers.remove(hexEncode(run.pairId));
    } else {
      run
        ..state = 'failed'
        ..detail = 'box_refused';
    }
    run.wipe();
    _record(run);
  }

  void _record(_Run run) {
    engine.adoption?.record({
      'method': 'radio',
      'result': run.result ?? (run.detail.isNotEmpty ? run.detail : run.state),
      'field': fieldFingerprint(engine.joinKey),
      'box': run.name,
      'pair_id': hexEncode(run.pairId),
    });
  }

  void tick(int now) {
    final run = _run;
    if (run != null && run.active) {
      if (now - run.stepMs >= pairStepMs) {
        _fail(run, run.state == 'starting' ? 'no_answer' : 'no_done', now);
      } else if (run.sends < pairSendsMax &&
          now - run.lastSendMs >= pairResendMs) {
        _transmit(run, now);
      }
    }
    offers.removeWhere((_, o) => now - (o['seen_ms']! as int) > offerTtlMs);
    if (_retuned &&
        (now >= _listenUntilMs || engine.channelLockReason() != null)) {
      _tuneBack();
    }
  }

  // --- the channel ----------------------------------------------------------

  /// The engine tuned the radio to the field's channel: no longer listening
  /// for boxes unless that is the pairing channel; a run there fails.
  void channelMoved(String why) {
    final was = _retuned;
    _retuned = false;
    if (was) _listenUntilMs = 0;
    final run = _run;
    if (run != null && run.active && engine.fieldChannel != pairChannelHz) {
      _fail(run, 'channel_changed', engine.nowMs());
    }
  }

  int _currentChannel() {
    final g = engine.liveGame;
    if (g != null && engine.channelLockReason() != null) {
      return (g['channel_hz'] as int?) ?? engine.fieldChannel;
    }
    return _retuned ? pairChannelHz : engine.fieldChannel;
  }

  void _tuneBack() {
    _retuned = false;
    if (_modemOk() && engine.channelLockReason() == null) {
      engine.modem!.setChannel(engine.fieldChannel);
    }
  }

  /// Keeps the radio on the pairing channel for five minutes.
  Map<String, Object?> listen() {
    final m = engine.modem;
    if (m == null || !m.isUp) {
      throw ControllerError.unavailable(
        'the radio modem is ${engine.radioState}: no pairing',
      );
    }
    if (!m.hasPairFrames) {
      throw ControllerError.unavailable(
        "the radio's firmware does not carry pair frames: update it",
      );
    }
    final current = _currentChannel();
    if (current != pairChannelHz) {
      final reason = engine.channelLockReason();
      if (reason != null) {
        throw ControllerError.conflict(
          'new boxes listen on $pairChannelHz Hz and the radio is on '
          '$current Hz for the live game ($reason): pair them before or '
          'after it',
        );
      }
      m.setChannel(pairChannelHz);
      _retuned = true;
    }
    _listenUntilMs = engine.nowMs() + pairListenMs;
    return status();
  }

  /// Starts a run with the box offering [pairId] and the code the GM read.
  Map<String, Object?> pair(Object? pairId, Object? code) {
    if (pairId is! String || pairId.length != 2 * pfPairIdSize) {
      throw ControllerError("pair_id: the box's 16 hex digits, from the list");
    }
    final digits = code is String ? code.replaceAll(' ', '') : null;
    if (!pairCodeOk(digits)) {
      throw ControllerError('code: the 6 digits the box shows');
    }
    final offer = offers[pairId.toLowerCase()];
    if (offer == null) {
      throw ControllerError.notFound(
        'that box is not offering itself now: check its screen and look again',
      );
    }
    if (!_modemOk()) {
      throw ControllerError.unavailable(
        'the radio modem is ${engine.radioState}: no pairing',
      );
    }
    final run0 = _run;
    if (run0 != null && run0.active) {
      throw ControllerError.conflict(
        'a pairing with ${run0.name} is under way',
      );
    }
    final now = engine.nowMs();
    final pid = hexDecode(pairId);
    final sid = _bytes(pfSidSize);
    final secret = _bytes(32);
    final ya = x25519(secret, pairGenerator(digits!, pid, sid));
    final run =
        _Run(
            pairId: pid,
            name: offer['name']! as String,
            sid: sid,
            yaSecret: secret,
            ya: ya,
            sender: _bytes(8),
            stepMs: now,
          )
          ..frame = encodePairFrame({
            'kind': 'start',
            'pair_id': pid,
            'sid': sid,
            'point': ya,
          });
    _run = run;
    _listenUntilMs = max(_listenUntilMs, now + pairListenMs);
    _transmit(run, now);
    return status();
  }

  Map<String, Object?> status() {
    final now = engine.nowMs();
    final list = [
      for (final o in offers.values)
        {
          for (final e in o.entries)
            if (e.key != 'seen_ms') e.key: e.value,
          'seen_ms_ago': now - (o['seen_ms']! as int),
          'short_id': (o['pair_id']! as String).substring(0, 4),
        },
    ];
    final names = <Object?, int>{};
    for (final o in list) {
      names[o['name']] = (names[o['name']] ?? 0) + 1;
    }
    for (final o in list) {
      o['duplicate_name'] = names[o['name']]! > 1;
    }
    // By name, offers under one name in the order first heard (Python's
    // stable sort).
    final order = {for (final (i, o) in list.indexed) o: i};
    list.sort((a, b) {
      final c = '${a['name']}'.compareTo('${b['name']}');
      return c != 0 ? c : order[a]!.compareTo(order[b]!);
    });
    final current = _currentChannel();
    final m = engine.modem;
    return {
      'offers': list,
      'run': _run?.public(),
      'channel_hz': pairChannelHz,
      'radio_channel_hz': current,
      'listening': current == pairChannelHz,
      'listen_ms_left': _retuned ? max(0, _listenUntilMs - now) : null,
      'radio': _modemOk(),
      'pair_frames': _modemOk() && (m?.hasPairFrames ?? false),
      'ignored': ignored,
    };
  }
}
