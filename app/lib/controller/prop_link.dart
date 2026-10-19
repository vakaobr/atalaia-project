// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// An Android prop's link to the field controller over Wi-Fi
/// (protocol/prop-link.md, decision PD12): `wss://` to the join payload's
/// addresses (key 14), trusting the field CA it names (key 13), an HMAC
/// proof that the phone holds the game key, then HELLO, STATE and EVENT as
/// JSON up and TIME beacons and commands down, as a box does over the radio.
/// Events are resent until the controller acknowledges them, across
/// reconnects (it drops duplicates as the radio's log does).
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';

import '../checkin/field_trust.dart';
import '../protocol/join_payload.dart';

const _domain = 'atalaia-prop-link-v1';

/// The link's proof: HMAC-SHA256(game key, domain 0x00 | nonce | game id | node id).
Uint8List propLinkProof(
  List<int> gameKey,
  List<int> nonce,
  int gameId,
  int nodeId,
) {
  final msg = <int>[
    ...utf8.encode(_domain),
    0,
    ...nonce,
    gameId >> 8 & 0xff,
    gameId & 0xff,
    nodeId >> 8 & 0xff,
    nodeId & 0xff,
  ];
  return Uint8List.fromList(Hmac(sha256, gameKey).convert(msg).bytes);
}

String _b64(List<int> b) => base64Url.encode(b).replaceAll('=', '');
Uint8List _unb64(String s) =>
    base64Url.decode(s.padRight((s.length + 3) ~/ 4 * 4, '='));

/// One connection's text frames.
abstract interface class LinkSocket {
  Stream<String> get messages;
  void send(String text);
  int? get closeCode;
  Future<void> close();
}

class _IoLinkSocket implements LinkSocket {
  _IoLinkSocket(this.ws);
  final WebSocket ws;
  @override
  Stream<String> get messages => ws.where((m) => m is String).cast<String>();
  @override
  void send(String text) => ws.add(text);
  @override
  int? get closeCode => ws.closeCode;
  @override
  Future<void> close() => ws.close();
}

typedef LinkConnect = Future<LinkSocket> Function(Uri uri);

/// [LinkConnect] over dart:io, trusting only [field]'s CA when given.
LinkConnect ioLinkConnect(PinnedField? field) =>
    (uri) async => _IoLinkSocket(
      await WebSocket.connect(uri.toString(), customClient: field?.client()),
    );

/// What the controller sends: a TIME beacon or a command.
sealed class LinkMessage {
  const LinkMessage();
}

final class LinkTime extends LinkMessage {
  const LinkTime(this.state, this.gameTimeMs, this.durationMs);

  /// waiting, running, paused, ended
  final String state;
  final int gameTimeMs;
  final int durationMs;
}

final class LinkCommand extends LinkMessage {
  const LinkCommand(this.cmd, this.params);

  /// start, pause, resume, end, set_owner, message, reset, reboot
  final String cmd;
  final Map<String, Object?> params;
}

enum LinkState { connecting, linked, refused, offline, closed }

class PropLink extends ChangeNotifier {
  PropLink({
    required this.join,
    required this.connect,
    required this.urls,
    this.hello = const {},
  });

  /// The link for [join], if its payload names the controller (keys 13, 14):
  /// [trust] fetches the CA and checks it against key 13 (for this game only).
  static Future<PropLink?> forJoin(
    JoinPayload join, {
    required Future<PinnedField> Function(List<String> urls, Uint8List ca)
    trust,
    LinkConnect? connect,
    Map<String, Object?> hello = const {},
  }) async {
    final urls = join.urls;
    final ca = join.caSha256;
    if (urls == null || urls.isEmpty || ca == null) return null;
    final field = await trust(urls, ca);
    return PropLink(
      join: join,
      connect: connect ?? ioLinkConnect(field),
      urls: urls,
      hello: hello,
    );
  }

  final JoinPayload join;
  final LinkConnect connect;
  final List<String> urls;

  /// HELLO's fields (node name, versions, capabilities...).
  Map<String, Object?> hello;

  LinkState state = LinkState.connecting;
  final _messages = StreamController<LinkMessage>.broadcast();
  Stream<LinkMessage> get messages => _messages.stream;

  /// Events sent and not acknowledged yet, by "type/seq".
  final _unacked = <String, Map<String, Object?>>{};
  Map<String, Object?>? _lastState;
  LinkSocket? _socket;
  Timer? _retry;
  var _delay = const Duration(seconds: 1);
  var _stopped = false;
  var _url = 0;

  int get unacked => _unacked.length;

  void start() => unawaited(_open());

  Future<void> _open() async {
    if (_stopped) return;
    state = LinkState.connecting;
    notifyListeners();
    final base = urls[_url % urls.length];
    final uri = Uri.parse(base).replace(scheme: 'wss', path: '/api/v1/prop');
    try {
      final s = await connect(uri);
      if (_stopped) {
        await s.close();
        return;
      }
      _socket = s;
      await for (final text in s.messages) {
        final Object? m;
        try {
          m = jsonDecode(text);
        } on FormatException {
          continue;
        }
        if (m is Map<String, Object?>) _onMessage(m);
      }
      if (s.closeCode == 4401) {
        state = LinkState.refused;
        _socket = null;
        notifyListeners();
        return;
      }
    } on Object {
      _url++; // the next address next time
    }
    _socket = null;
    if (_stopped) return;
    state = LinkState.offline;
    notifyListeners();
    _retry = Timer(_delay, _open);
    _delay = _delay * 2 > const Duration(seconds: 15)
        ? const Duration(seconds: 15)
        : _delay * 2;
  }

  void _send(Map<String, Object?> m) => _socket?.send(jsonEncode(m));

  void _onMessage(Map<String, Object?> m) {
    switch (m['type']) {
      case 'challenge':
        final nonce = _unb64('${m['nonce']}');
        _send({
          'type': 'auth',
          'game_id': join.gameId,
          'node_id': join.nodeId,
          'proof': _b64(
            propLinkProof(join.gameKey, nonce, join.gameId, join.nodeId),
          ),
        });
      case 'welcome':
        state = LinkState.linked;
        _delay = const Duration(seconds: 1);
        _send({'type': 'hello', ...hello});
        if (_lastState != null) _send({'type': 'state', ..._lastState!});
        for (final e in _unacked.values) {
          _send({'type': 'event', 'event': e});
        }
        final t = m['time'];
        if (t is Map) _time(t.cast<String, Object?>());
        notifyListeners();
      case 'refused':
        state = LinkState.refused;
        notifyListeners();
      case 'replaced':
        _stopped = true; // another link for this node took over
        state = LinkState.closed;
        notifyListeners();
      case 'ack' || 'error':
        _unacked.remove('${m['event_type']}/${m['seq']}');
        // An event the controller refused for good is not sent again.
        if (m['type'] == 'error') {
          _unacked.removeWhere((k, _) => k.endsWith('/${m['seq']}'));
        }
        notifyListeners();
      case 'time':
        _time(m);
      case 'cmd':
        final params = m['params'];
        _messages.add(
          LinkCommand(
            '${m['cmd']}',
            params is Map ? params.cast<String, Object?>() : const {},
          ),
        );
    }
  }

  void _time(Map<String, Object?> m) => _messages.add(
    LinkTime(
      '${m['state']}',
      (m['game_time_ms'] as int?) ?? 0,
      (m['duration_ms'] as int?) ?? 0,
    ),
  );

  /// An event of the prop's mode (or the shell's own, such as node.tamper).
  void sendEvent({
    required int seq,
    required int tMs,
    required String type,
    int team = 0,
    int squad = 0,
    String? prio,
    Map<String, Object?> data = const {},
  }) {
    final e = <String, Object?>{
      'seq': seq,
      't': tMs,
      'type': type,
      if (team != 0) 'team': team,
      if (squad != 0) 'squad': squad,
      'prio': ?prio,
      'data': data,
    };
    _unacked['$type/$seq'] = e;
    while (_unacked.length > 500) {
      _unacked.remove(_unacked.keys.first);
    }
    if (state == LinkState.linked) _send({'type': 'event', 'event': e});
  }

  /// The prop's STATE: owner, phase, game time, counters by team id.
  void sendState(Map<String, Object?> fields) {
    _lastState = fields;
    if (state == LinkState.linked) _send({'type': 'state', ...fields});
  }

  Future<void> close() async {
    _stopped = true;
    _retry?.cancel();
    final s = _socket;
    _socket = null;
    await s?.close();
    state = LinkState.closed;
    if (!_messages.isClosed) await _messages.close();
  }
}
