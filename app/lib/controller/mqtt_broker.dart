// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A minimal embedded MQTT 3.1.1 broker for the Android controller role
/// (ADR-P3-12, decision P3-4): what local scoreboards and integrations need
/// to follow a game, with the Pi controller's topics (field/v1/{game}/...;
/// decision PE10), and nothing more:
///
/// * CONNECT/CONNACK, PUBLISH (QoS 0 and 1, PUBACK), SUBSCRIBE/SUBACK with
///   `+` and `#` filters, UNSUBSCRIBE/UNSUBACK, PINGREQ/PINGRESP, DISCONNECT;
/// * retained messages, since the Pi's bridge publishes the score and the
///   node topics retained (a scoreboard that connects late sees them);
/// * the controller itself publishes with [publish]; clients may publish
///   only where [acl] or [allowPublish] says (default: nowhere);
/// * with [users], a client must log in with a user name and its password
///   (CONNACK 5 otherwise), and [acl] says what each user may read and
///   write: [MqttAcl.field] is the Pi's controller/deploy/atalaia.acl (the
///   `gm` and `reader` users, the GM and read tokens as their passwords on
///   a phone controller; decision PE24-12), checked against the same shared
///   cases (protocol/vectors/controller_api.json, mqtt_acl);
/// * at most [maxClients] connections (20), the keep-alive enforced (1.5x),
///   packets up to 64 KB;
/// * the loopback address by default; the field's network only over TLS
///   with the field CA, on [tlsPort] (8883), when the shell opens it there
///   (decision PE24-7, slice S6; the plain port never leaves the phone:
///   security review FLD-5, SR-54).
///
/// Not supported (refused or ignored, as the ADR says): QoS 2, wills,
/// persistent sessions.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

const _connect = 1;
const _connack = 2;
const _publish = 3;
const _puback = 4;
const _subscribe = 8;
const _suback = 9;
const _unsubscribe = 10;
const _unsuback = 11;
const _pingreq = 12;
const _pingresp = 13;
const _disconnect = 14;

/// Whether [topic] matches the subscription [filter] (MQTT 3.1.1 section 4.7).
bool topicMatches(String filter, String topic) {
  final f = filter.split('/');
  final t = topic.split('/');
  for (var i = 0; i < f.length; i++) {
    if (f[i] == '#') return i < t.length || i == t.length;
    if (i >= t.length) return false;
    if (f[i] != '+' && f[i] != t[i]) return false;
  }
  return f.length == t.length;
}

bool _filterOk(String f) {
  if (f.isEmpty || f.length > 512) return false;
  final parts = f.split('/');
  for (var i = 0; i < parts.length; i++) {
    final p = parts[i];
    if (p.contains('#') && (p != '#' || i != parts.length - 1)) return false;
    if (p.contains('+') && p != '+') return false;
  }
  return true;
}

/// Who may read and write which topics, as Mosquitto's acl_file says it:
/// per user, `read`, `write` or `readwrite` topic patterns with `+` and `#`.
/// A user with no rules may do nothing.
final class MqttAcl {
  const MqttAcl(this.rules);

  /// user -> (access, pattern) rules.
  final Map<String, List<(String, String)>> rules;

  /// controller/deploy/atalaia.acl: the controller, GM tools ("the GM
  /// token") and scoreboards ("the read token").
  static const field = MqttAcl({
    'controller': [('readwrite', 'field/v1/#')],
    'gm': [('read', 'field/v1/#'), ('write', 'field/v1/+/cmd/#')],
    'reader': [
      ('read', 'field/v1/+/events/#'),
      ('read', 'field/v1/+/score'),
      ('read', 'field/v1/+/nodes/#'),
    ],
  });

  bool _may(String? user, String topic, String access) =>
      user != null &&
      (rules[user] ?? const []).any(
        (r) =>
            (r.$1 == access || r.$1 == 'readwrite') &&
            topicMatches(r.$2, topic),
      );

  bool mayRead(String? user, String topic) => _may(user, topic, 'read');

  bool mayWrite(String? user, String topic) => _may(user, topic, 'write');
}

bool _sameSecret(String a, String b) {
  final x = utf8.encode(a);
  final y = utf8.encode(b);
  var diff = x.length ^ y.length;
  for (var i = 0; i < x.length; i++) {
    diff |= x[i] ^ (i < y.length ? y[i] : 0);
  }
  return diff == 0;
}

class _Client {
  _Client(this.socket);
  final Socket socket;
  final buffer = BytesBuilder(copy: false);
  final filters = <String, int>{}; // filter -> granted QoS
  var connected = false;

  /// Refused at CONNECT: the CONNACK goes out, then the connection closes.
  var refused = false;
  String id = '';

  /// The user it logged in as (null: none).
  String? user;
  int keepAlive = 0;
  DateTime lastSeen = DateTime.now();
  var nextId = 1;
}

class MqttBroker {
  MqttBroker({
    this.port = 1883,
    InternetAddress? address,
    this.maxClients = 20,
    this.allowPublish,
    this.users,
    this.acl,
    this.tls,
    this.tlsAddress,
    this.tlsPort = 8883,
  }) : address = address ?? InternetAddress.loopbackIPv4;

  /// With a context, a second listener on [tlsAddress] and [tlsPort] speaks
  /// MQTT over TLS (the field CA's server certificate, field_tls.dart).
  final SecurityContext? tls;
  final InternetAddress? tlsAddress;

  /// 0: any free port ([boundTlsPort] tells which).
  final int tlsPort;

  /// 0: any free port ([boundPort] tells which).
  final int port;
  final InternetAddress address;
  final int maxClients;

  /// Which topics a client may publish to (null: none), besides [acl].
  final bool Function(String clientId, String topic)? allowPublish;

  /// User name -> password; null: no login (anonymous clients).
  final Map<String, String>? users;

  /// What each user may read and write; null: every client reads
  /// everything (and writes where [allowPublish] says).
  final MqttAcl? acl;

  bool _mayRead(_Client c, String topic) =>
      acl == null || acl!.mayRead(c.user, topic);

  ServerSocket? _server;
  SecureServerSocket? _secure;
  final _clients = <_Client>{};
  final _retained = <String, (Uint8List, int)>{};
  Timer? _keepAlive;
  final _received = StreamController<(String, String, Uint8List)>.broadcast();

  /// What clients published where they may: (client id, topic, payload).
  Stream<(String, String, Uint8List)> get received => _received.stream;

  int get boundPort => _server?.port ?? port;
  int? get boundTlsPort => _secure?.port;
  int get clientCount => _clients.where((c) => c.connected).length;

  Future<void> start() async {
    _server = await ServerSocket.bind(address, port);
    _server!.listen(_accept);
    final ctx = tls;
    if (ctx != null) await _bindTls(ctx, tlsPort);
    _keepAlive = Timer.periodic(
      const Duration(seconds: 1),
      (_) => _checkKeepAlive(),
    );
  }

  Future<void> _bindTls(SecurityContext ctx, int port) async {
    _secure = await SecureServerSocket.bind(
      tlsAddress ?? InternetAddress.loopbackIPv4,
      port,
      ctx,
    );
    _secure!.listen(_accept, onError: (Object _) {});
  }

  /// A new server certificate (an address changed, one near its end): the
  /// TLS listener again on the same port; connected clients stay.
  Future<void> renewTls(SecurityContext ctx) async {
    final old = _secure;
    if (old == null) return;
    final port = old.port;
    await old.close();
    await _bindTls(ctx, port);
  }

  Future<void> stop() async {
    _keepAlive?.cancel();
    for (final c in List.of(_clients)) {
      c.socket.destroy();
    }
    _clients.clear();
    await _server?.close();
    await _secure?.close();
    _server = null;
    _secure = null;
    await _received.close();
  }

  /// The controller's own message to every matching subscriber.
  void publish(
    String topic,
    Object payload, {
    int qos = 0,
    bool retain = false,
  }) {
    final bytes = payload is Uint8List
        ? payload
        : Uint8List.fromList(
            utf8.encode(payload is String ? payload : jsonEncode(payload)),
          );
    if (retain) {
      if (bytes.isEmpty) {
        _retained.remove(topic);
      } else {
        _retained[topic] = (bytes, qos.clamp(0, 1));
      }
    }
    for (final c in _clients) {
      if (!c.connected) continue;
      var best = -1;
      for (final e in c.filters.entries) {
        if (topicMatches(e.key, topic) && e.value > best) best = e.value;
      }
      if (best >= 0 && _mayRead(c, topic)) {
        _sendPublish(c, topic, bytes, qos < best ? qos : best, false);
      }
    }
  }

  void _accept(Socket s) {
    final c = _Client(s);
    if (_clients.length >= maxClients) {
      s.destroy();
      return;
    }
    _clients.add(c);
    s.listen(
      (data) => _onData(c, data),
      onDone: () => _drop(c),
      onError: (Object _) => _drop(c),
      cancelOnError: true,
    );
  }

  void _drop(_Client c) {
    _clients.remove(c);
    c.socket.destroy();
  }

  /// Closes [c] once what was sent to it is out (unlike [_drop]).
  void _refuse(_Client c) {
    c.refused = true;
    _clients.remove(c);
    c.socket.close().then((_) {}, onError: (Object _) {});
  }

  void _checkKeepAlive() {
    final now = DateTime.now();
    for (final c in List.of(_clients)) {
      final limit = c.connected
          ? (c.keepAlive == 0
                ? null
                : Duration(milliseconds: c.keepAlive * 1500))
          : const Duration(seconds: 10); // CONNECT must come first, and soon
      if (limit != null && now.difference(c.lastSeen) > limit) _drop(c);
    }
  }

  void _onData(_Client c, Uint8List data) {
    if (c.refused) return;
    c.lastSeen = DateTime.now();
    c.buffer.add(data);
    var bytes = c.buffer.takeBytes();
    while (true) {
      if (bytes.length < 2) break;
      var len = 0;
      var mult = 1;
      var i = 1;
      var complete = false;
      for (; i < 5 && i < bytes.length; i++) {
        len += (bytes[i] & 0x7f) * mult;
        mult *= 128;
        if (bytes[i] & 0x80 == 0) {
          complete = true;
          break;
        }
      }
      if (!complete) {
        if (i >= 5) {
          _drop(c);
          return;
        }
        break;
      }
      final start = i + 1;
      if (len > 65536) {
        _drop(c);
        return;
      }
      if (bytes.length < start + len) break;
      final header = bytes[0];
      final body = Uint8List.sublistView(bytes, start, start + len);
      if (!_packet(c, header >> 4, header & 0x0f, body)) {
        _drop(c);
        return;
      }
      if (c.refused) return;
      bytes = Uint8List.sublistView(bytes, start + len);
    }
    c.buffer.add(bytes);
  }

  /// One packet; false closes the connection (a protocol error).
  bool _packet(_Client c, int type, int flags, Uint8List b) {
    if (!c.connected && type != _connect) return false;
    final r = _Reader(b);
    try {
      switch (type) {
        case _connect:
          if (c.connected) return false;
          final name = r.string();
          final level = r.byte();
          final cflags = r.byte();
          c.keepAlive = r.u16();
          if (name != 'MQTT' || level != 4) {
            _send(c, _connack << 4, [0, 1]); // unacceptable protocol version
            return false;
          }
          c.id = r.string();
          if (cflags & 0x04 != 0) {
            // A will: read and ignore (not supported).
            r.string();
            r.bytes();
          }
          final user = cflags & 0x80 != 0 ? r.string() : null;
          final password = cflags & 0x40 != 0 ? utf8.decode(r.bytes()) : null;
          final known = users;
          if (known != null) {
            final want = user == null ? null : known[user];
            if (want == null ||
                password == null ||
                !_sameSecret(password, want)) {
              _send(c, _connack << 4, [0, 5]); // not authorised
              _refuse(c);
              return true;
            }
            c.user = user;
          }
          if (c.id.isEmpty) c.id = 'client-${c.hashCode}';
          for (final other in List.of(_clients)) {
            if (other != c && other.connected && other.id == c.id) _drop(other);
          }
          c.connected = true;
          _send(c, _connack << 4, [0, 0]);
        case _publish:
          final qos = (flags >> 1) & 3;
          if (qos > 1) return false; // QoS 2 is not supported
          final topic = r.string();
          final id = qos > 0 ? r.u16() : 0;
          final payload = r.rest();
          if (topic.contains('+') || topic.contains('#')) return false;
          if (qos == 1) _send(c, _puback << 4, [id >> 8, id & 0xff]);
          if ((acl?.mayWrite(c.user, topic) ?? false) ||
              (allowPublish?.call(c.id, topic) ?? false)) {
            _received.add((c.id, topic, payload));
            publish(topic, payload, qos: qos, retain: flags & 1 != 0);
          }
        case _puback:
          r.u16(); // our QoS 1 delivery acknowledged; nothing kept to resend
        case _subscribe:
          if (flags != 2) return false;
          final id = r.u16();
          final granted = <int>[];
          final added = <String>[];
          while (!r.done) {
            final f = r.string();
            final q = r.byte() & 3;
            if (!_filterOk(f) || q > 2) {
              granted.add(0x80);
              continue;
            }
            final g = q > 1 ? 1 : q;
            c.filters[f] = g;
            granted.add(g);
            added.add(f);
          }
          if (granted.isEmpty) return false;
          _send(c, _suback << 4, [id >> 8, id & 0xff, ...granted]);
          for (final f in added) {
            for (final e in _retained.entries) {
              if (topicMatches(f, e.key) && _mayRead(c, e.key)) {
                final q = e.value.$2 < c.filters[f]!
                    ? e.value.$2
                    : c.filters[f]!;
                _sendPublish(c, e.key, e.value.$1, q, true);
              }
            }
          }
        case _unsubscribe:
          if (flags != 2) return false;
          final id = r.u16();
          while (!r.done) {
            c.filters.remove(r.string());
          }
          _send(c, _unsuback << 4, [id >> 8, id & 0xff]);
        case _pingreq:
          _send(c, _pingresp << 4, const []);
        case _disconnect:
          _drop(c);
        default:
          return false;
      }
    } on RangeError {
      return false; // a packet shorter than it says
    } on FormatException {
      return false;
    }
    return true;
  }

  void _sendPublish(
    _Client c,
    String topic,
    Uint8List payload,
    int qos,
    bool retain,
  ) {
    final t = utf8.encode(topic);
    final head = <int>[t.length >> 8, t.length & 0xff, ...t];
    if (qos > 0) {
      final id = c.nextId;
      c.nextId = c.nextId == 0xffff ? 1 : c.nextId + 1;
      head.addAll([id >> 8, id & 0xff]);
    }
    _send(c, _publish << 4 | qos << 1 | (retain ? 1 : 0), [
      ...head,
      ...payload,
    ]);
  }

  void _send(_Client c, int header, List<int> body) {
    final out = BytesBuilder()..addByte(header);
    var n = body.length;
    do {
      var digit = n % 128;
      n ~/= 128;
      if (n > 0) digit |= 0x80;
      out.addByte(digit);
    } while (n > 0);
    out.add(body);
    try {
      c.socket.add(out.takeBytes());
    } on Object {
      _drop(c);
    }
  }
}

class _Reader {
  _Reader(this.b);
  final Uint8List b;
  var i = 0;

  bool get done => i >= b.length;

  int byte() {
    if (i >= b.length) throw RangeError('short packet');
    return b[i++];
  }

  int u16() => byte() << 8 | byte();

  Uint8List bytes() {
    final n = u16();
    if (i + n > b.length) throw RangeError('short packet');
    final out = Uint8List.sublistView(b, i, i + n);
    i += n;
    return out;
  }

  String string() => utf8.decode(bytes());

  Uint8List rest() {
    final out = Uint8List.fromList(Uint8List.sublistView(b, i));
    i = b.length;
    return out;
  }
}
