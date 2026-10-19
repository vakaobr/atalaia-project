// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The phone's side of the capability proxy (protocol/capability-proxy.md):
/// an I/O pod over USB-OTG or Bluetooth LE ([PodTransport]), its IDENT, its
/// events (acknowledged, each acted on once) and the phone's commands
/// (retried after 500 ms, up to 3 times, then the link counts as broken).
/// [PodInputs] turns a pod's events into the inputs the core expects, as a
/// box's shell does.
///
/// No pod exists yet (its firmware is plan phase F): this is checked with a
/// pod simulated in the tests (test/pod/pod_client_test.dart), not with
/// hardware.
library;

import 'dart:async';
import 'dart:typed_data';

import '../security/bytes.dart';
import '../security/nfc_tag_signer.dart';
import 'pod_codec.dart';

/// A link to a pod: bytes in, bytes out. Frames may arrive split or joined.
abstract interface class PodTransport {
  /// "usb" or "ble".
  String get kind;
  Stream<Uint8List> get incoming;
  Future<void> send(Uint8List bytes);
  Future<void> close();
}

sealed class PodEvent {
  const PodEvent();
}

final class PodIdentified extends PodEvent {
  const PodIdentified(this.ident);
  final PodIdent ident;
}

final class PodCapabilityEvent extends PodEvent {
  const PodCapabilityEvent(this.message);
  final ProxyMessage message;
}

/// RADIO_RX, RADIO_TX_ACK, RADIO_STATUS or RADIO_ERROR, untouched (the
/// phone's radio code reads them: plan phase E).
final class PodRadioFrame extends PodEvent {
  const PodRadioFrame(this.type, this.payload);
  final int type;
  final Uint8List payload;
}

final class PodLinkBroken extends PodEvent {
  const PodLinkBroken(this.why);
  final String why;
}

class PodClient {
  PodClient(
    this.transport, {
    this.retryAfter = const Duration(milliseconds: 500),
    this.retries = 3,
  });

  final PodTransport transport;
  final Duration retryAfter;
  final int retries;

  final _events = StreamController<PodEvent>.broadcast(sync: true);
  final _decoder = FrameDecoder();
  final _pending = <int, _Pending>{};
  final _recent = <int>[]; // the last 16 EVT seqs acted on
  StreamSubscription<Uint8List>? _sub;
  var _seq = 0;
  var _broken = false;
  PodIdent? ident;

  Stream<PodEvent> get events => _events.stream;
  bool get broken => _broken;

  /// Starts listening and asks the pod who it is (RADIO_CMD IDENT, answered
  /// with IDENT: the phone sends it first on every new link).
  Future<void> start() async {
    _sub = transport.incoming.listen(
      _onBytes,
      onDone: () => _break('the link closed'),
      onError: (Object e) => _break('$e'),
    );
    await _send(FrameType.radioCmd, [RadioOp.ident]);
  }

  /// Sends a command to one of the pod's capabilities; true once the pod
  /// acknowledges it, false if the link broke first.
  Future<bool> command(
    String capId,
    String method, [
    Map<String, Object?> args = const {},
  ]) {
    if (_broken) return Future.value(false);
    final seq = _seq;
    _seq = (_seq + 1) & 0xffff;
    final frame = encodeFrame(
      FrameType.cmd,
      encodeMessage(
        ProxyMessage(capId: capId, name: method, data: args, seq: seq),
      ),
    );
    final p = _Pending(frame);
    _pending[seq] = p;
    unawaited(transport.send(frame));
    p.timer = Timer.periodic(retryAfter, (t) {
      if (p.tries >= retries) {
        t.cancel();
        _pending.remove(seq);
        p.done.complete(false);
        _break('command $seq was not acknowledged');
        return;
      }
      p.tries++;
      unawaited(transport.send(frame));
    });
    return p.done.future;
  }

  /// Sends a radio frame (RADIO_TX or RADIO_CMD); not acknowledged here.
  Future<void> sendRadio(int type, List<int> payload) => _send(type, payload);

  Future<void> _send(int type, List<int> payload) =>
      transport.send(encodeFrame(type, payload));

  void _onBytes(Uint8List data) {
    for (final f in _decoder.feed(data)) {
      try {
        _onFrame(f);
      } on ProxyException {
        // An invalid payload is dropped (an EVT is then not acknowledged).
      }
    }
  }

  void _onFrame(Frame f) {
    switch (f.type) {
      case FrameType.ident:
        ident = decodeIdent(f.payload);
        _events.add(PodIdentified(ident!));
      case FrameType.evt:
        final msg = decodeMessage(f.payload);
        unawaited(_send(FrameType.ack, encodeAck(msg.seq)));
        if (_recent.contains(msg.seq)) return; // a repeat: acted on once
        _recent.add(msg.seq);
        if (_recent.length > 16) _recent.removeAt(0);
        _events.add(PodCapabilityEvent(msg));
      case FrameType.ack:
        final p = _pending.remove(decodeAck(f.payload));
        if (p != null) {
          p.timer?.cancel();
          p.done.complete(true);
        }
      case FrameType.radioRx ||
          FrameType.radioTxAck ||
          FrameType.radioStatus ||
          FrameType.radioError:
        _events.add(PodRadioFrame(f.type, f.payload));
      default:
        break; // other types are ignored: a later version may add frames
    }
  }

  void _break(String why) {
    if (_broken) return;
    _broken = true;
    for (final p in _pending.values) {
      p.timer?.cancel();
      if (!p.done.isCompleted) p.done.complete(false);
    }
    _pending.clear();
    _events.add(PodLinkBroken(why));
  }

  Future<void> close() async {
    _break('closed');
    await _sub?.cancel();
    await transport.close();
    await _events.close();
  }
}

class _Pending {
  _Pending(this.frame);
  final Uint8List frame;
  final done = Completer<bool>();
  Timer? timer;
  var tries = 0;
}

/// A pod's events as the inputs a mode expects (modes/README.md "Inputs
/// from the hardware"), given the pod's capability descriptors.
class PodInputs {
  PodInputs(this.ident);

  final PodIdent ident;

  Map<String, Object?>? _descriptor(String capId) {
    for (final c in ident.capabilities) {
      if (c['id'] == capId) return c;
    }
    return null;
  }

  /// The input event for [msg], or null if it maps to none. [tagData] makes
  /// the nfc.tag data for a card's player-tag record (the game's key checks
  /// it: tagEventData in lib/security/nfc_tag_signer.dart).
  (String, Map<String, Object?>)? input(
    ProxyMessage msg, {
    required Map<String, Object?> Function(List<int> uid, List<int>? tag)
    tagData,
  }) {
    final cap = _descriptor(msg.capId);
    final type = cap?['type'];
    if (type == 'button') {
      final team = cap!['team'];
      if (team is! String) return null;
      final ms = msg.data['ms'];
      return switch (msg.name) {
        'press' => ('team_input.press', {'team': team}),
        'hold' => ('team_input.hold', {'team': team, 'ms': ?ms}),
        'release' => ('team_input.release', {'team': team, 'ms': ?ms}),
        _ => null,
      };
    }
    if (type == 'nfc' && msg.name == 'tag') {
      final uid = msg.data['uid'];
      if (uid is! String) return null;
      final tag = msg.data['tag'];
      return (
        'nfc.tag',
        tagData(hexDecode(uid), tag is String ? hexDecode(tag) : null),
      );
    }
    if (type == 'keypad' && msg.name == 'key') {
      final key = msg.data['key'];
      if (key is! String) return null;
      return ('keypad.key', {'key': key});
    }
    return null;
  }

  /// The pod command for a script's hardware command, or null: a ring's
  /// fill and a team display's show take {"team": name}, a speaker's tone
  /// {"freq", "ms"}; other commands pass their arguments as {"args": [...]}.
  (String, String, Map<String, Object?>)? command(
    String target,
    String method,
    List<Object?> args,
  ) {
    if (_descriptor(target) == null) return null;
    if ((method == 'fill' || method == 'show') &&
        args.length == 1 &&
        args.single is String) {
      return (target, method, {'team': args.single});
    }
    if (method == 'tone' && args.length == 2) {
      return (target, method, {'freq': args[0], 'ms': args[1]});
    }
    return (target, method, args.isEmpty ? const {} : {'args': args});
  }
}

/// The nfc.tag data for a pod's card read, as a box would give it.
Map<String, Object?> podTagData(
  List<int> uid,
  List<int>? tag, {
  required int gameId,
  required List<int>? gameKey,
  required List<String> teams,
}) => tagEventData(
  uid: uid,
  payload: tag,
  gameId: gameId,
  gameKey: gameKey,
  teams: teams,
);
