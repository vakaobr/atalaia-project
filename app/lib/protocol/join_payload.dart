// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Join payloads (protocol/join.md, ADR-P2-12): the Dart side of
/// core/src/join.c and simulator/atalaia_sim/join.py, checked against the
/// same vectors (protocol/vectors/join.json).
///
///     version (1 byte, 1) | body (CBOR map, integer keys) | HMAC-SHA256 (32)
///
/// The tag is HMAC-SHA256 over the version byte and the body, keyed with the
/// field's 32-byte join key. An Android prop joins a game by reading one
/// (decision P3-10): the QR code's text form `atalaia:join:...`, typed or
/// scanned, or a join card over NFC (MIME record application/vnd.atalaia.join).
/// The app checks the tag with the field join key entered once in its
/// settings, then uses the game's id and key, its node id, mode, role, teams,
/// parameters and seed. Optional keys 13 (the field CA's fingerprint) and 14
/// (the controller's https addresses) let it link to the controller over
/// Wi-Fi (protocol/prop-link.md, RFC 0001 Amendment 4, proposed); boxes use
/// them only for firmware updates (protocol/firmware-update.md). Keys 16
/// (`fetch_modes`) and 17 (`forget_modes`), CBOR true when set and left out
/// otherwise, ask a box to fetch the parts of its mode it lacks from the
/// controller, or to forget those it fetched before (protocol/mode-packages.md;
/// the phone controller sends them from slice S7b of PE24). Key 18 is the
/// field's radio region (RFC 0001 Amendment 12, radio_region.dart): its
/// number, left out for EU868 (0 written is refused, so a join has one
/// encoding); the channel must fit in that region.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import '../security/bytes.dart';
import 'cbor.dart';
import 'radio_region.dart';

const int joinVersion = 1;
const int joinMaxLength = 448;
const int joinMacSize = 32;
const int joinKeySize = 32;
const int gameKeySize = 16;
const String joinTextPrefix = 'atalaia:join:';
const String joinNdefType = 'application/vnd.atalaia.join';

/// Why a payload is refused: the tag check comes before the body, so a
/// forged card says `mac`, never what is inside it.
enum JoinFailure { length, version, mac, body }

class JoinException implements Exception {
  JoinException(this.reason, this.message);
  final JoinFailure reason;
  final String message;
  @override
  String toString() => 'JoinException(${reason.name}): $message';
}

enum JoinKind { node, controller }

/// EU868 sub-bands (RFC 0001 Amendment 1 and 3): a channel's whole 125 kHz
/// must fit inside one.
bool channelOk(int hz) => eu868.channelOk(hz);

final class JoinPayload {
  JoinPayload({
    required this.gameId,
    required this.gameKey,
    required this.nodeId,
    required this.controllerId,
    required this.channelHz,
    required this.maxHops,
    required this.teams,
    required this.modeId,
    required this.role,
    required this.gameSeed,
    required this.params,
    required this.kind,
    this.caSha256,
    this.urls,
    this.lang,
    this.fetchModes = false,
    this.forgetModes = false,
    this.region = 'eu868',
  });

  final int gameId;
  final Uint8List gameKey;
  final int nodeId;
  final int controllerId;
  final int channelHz;
  final int maxHops;
  final List<String> teams;

  /// A main mode with its modifiers joined by '+', main mode first.
  final String modeId;
  final String role;
  final int gameSeed;

  /// Null: the mode's defaults.
  final Map<String, Object?>? params;
  final JoinKind kind;

  /// Key 13: SHA-256 of the field CA's DER certificate (32 bytes), or null.
  final Uint8List? caSha256;

  /// Key 14: the controller's https base addresses (1-3), or null.
  final List<String>? urls;

  /// Key 15: the language of the box screens ("pt", "en"...; RFC 0001
  /// Amendment 10), or null: English.
  final String? lang;

  /// Key 16: fetch the parts of [modeId] the box lacks (true when set).
  final bool fetchModes;

  /// Key 17: forget every package fetched before (true when set).
  final bool forgetModes;

  /// Key 18: the field's radio region's code ("eu868", "as923-tw"); a box
  /// built for another region refuses the join.
  final String region;

  /// The parts of [modeId]: the main mode, then its modifiers.
  List<String> get modeParts => modeId.split('+');

  @override
  String toString() =>
      'JoinPayload(game $gameId, node $nodeId, $modeId/$role, $teams)';
}

JoinException _body(String why) => JoinException(JoinFailure.body, why);

String _text(String name, Object? v, int maxBytes) {
  if (v is! String) throw _body('$name must be text');
  final n = utf8.encode(v).length;
  if (n < 1 || n > maxBytes || v.contains('\u0000')) {
    throw _body('$name: 1 to $maxBytes bytes of UTF-8 without NUL');
  }
  return v;
}

int _uint(String name, Object? v, int lo, int hi) {
  if (v is! int || v < lo || v > hi) {
    throw _body('$name must be an integer from $lo to $hi');
  }
  return v;
}

const _maxKeys = 128;

/// Parameter values are JSON values, with the core codec's limits.
void _checkValue(Object? v, int depth, List<int> openKeys) {
  if ((v is List || v is Map) && depth >= cborMaxDepth) {
    throw _body('params: data nested more than ${cborMaxDepth - 1} deep');
  }
  if (v == null || v is bool || v is String || v is double || v is int) {
    return;
  }
  if (v is List) {
    for (final x in v) {
      _checkValue(x, depth + 1, openKeys);
    }
    return;
  }
  if (v is Map) {
    for (final e in v.entries) {
      if (e.key is! String) throw _body('params: data keys must be text');
      openKeys[0]++;
      if (openKeys[0] > _maxKeys) {
        throw _body('params: too many keys in nested data');
      }
      _checkValue(e.value, depth + 1, openKeys);
    }
    return;
  }
  throw _body('params cannot hold byte strings');
}

/// Checks a join's fields as both codecs do.
JoinPayload _validate(Map<String, Object?> j) {
  const required = [
    'game_id', 'game_key', 'node_id', 'controller_id', 'channel_hz', //
    'max_hops', 'teams', 'mode_id', 'role', 'game_seed', 'kind',
  ];
  final missing = required.where((k) => !j.containsKey(k)).toList()..sort();
  if (missing.isNotEmpty) {
    throw _body('missing join fields: ${missing.join(', ')}');
  }
  final gameId = _uint('game_id', j['game_id'], 1, 0xfffe);
  final key = j['game_key'];
  if (key is! Uint8List || key.length != gameKeySize) {
    throw _body('game_key must be 16 bytes');
  }
  final nodeId = _uint('node_id', j['node_id'], 0, 0xfffe);
  final controllerId = _uint('controller_id', j['controller_id'], 0, 0xfffe);
  if (nodeId == controllerId) {
    throw _body('node_id and controller_id must differ');
  }
  final regionCode = j['region'] ?? defaultRegion.code;
  final region = regionCode is String ? regionsByCode[regionCode] : null;
  if (region == null) {
    throw _body('region: one of ${regionsByCode.keys.join(', ')}');
  }
  final channel = _uint('channel_hz', j['channel_hz'], 0, 0xffffffff);
  if (!region.channelOk(channel)) {
    throw _body(
      'channel_hz: the whole channel must fit inside a sub-band of '
      '${region.code}',
    );
  }
  final maxHops = _uint('max_hops', j['max_hops'], 1, 3);
  final teams = j['teams'];
  if (teams is! List || teams.isEmpty || teams.length > 8) {
    throw _body('teams: 1 to 8 names');
  }
  final names = [for (final t in teams) _text('team name', t, 23)];
  if (names.toSet().length != names.length) {
    throw _body('team names must differ');
  }
  final modeId = _text('mode_id', j['mode_id'], 63);
  final role = _text('role', j['role'], 31);
  final seed = _uint('game_seed', j['game_seed'], 0, 0xffffffff);
  final params = j['params'];
  Map<String, Object?>? p;
  if (params != null) {
    if (params is! Map || params.keys.any((k) => k is! String)) {
      throw _body('params must be a map with text keys');
    }
    p = params.cast<String, Object?>();
    _checkValue(p, 1, [0]);
    if (utf8.encode(jsonEncode(p)).length > 200) {
      throw _body('params: the JSON form is over 200 bytes');
    }
  }
  final kind = j['kind'];
  if (kind is! JoinKind) throw _body('kind must be node or controller');
  final ca = j['ca_sha256'];
  if (ca != null && (ca is! Uint8List || ca.length != 32)) {
    throw _body('ca_sha256 must be 32 bytes');
  }
  final urls = j['urls'];
  List<String>? u;
  if (urls != null) {
    if (urls is! List ||
        urls.isEmpty ||
        urls.length > 3 ||
        urls.toSet().length != urls.length) {
      throw _body('urls: 1 to 3 different addresses');
    }
    u = [
      for (final x in urls)
        if (x is String && httpsBaseUrlOk(x))
          x
        else
          throw _body(
            'urls: $x is not https://host[:port] of at most 64 bytes',
          ),
    ];
  }
  for (final flag in ['fetch_modes', 'forget_modes']) {
    final f = j[flag];
    if (f != null && f != false && f != true) {
      throw _body('$flag: true when set, else left out');
    }
  }
  final lang = j['lang'];
  if (lang != null && (lang is! String || !_lang.hasMatch(lang))) {
    throw _body(
      'lang: $lang is not 2-8 of a-z, 0-9 and -, starting with two letters',
    );
  }
  return JoinPayload(
    gameId: gameId,
    gameKey: key,
    nodeId: nodeId,
    controllerId: controllerId,
    channelHz: channel,
    maxHops: maxHops,
    teams: names,
    modeId: modeId,
    role: role,
    gameSeed: seed,
    params: p,
    kind: kind,
    caSha256: ca as Uint8List?,
    urls: u,
    lang: lang as String?,
    fetchModes: j['fetch_modes'] == true,
    forgetModes: j['forget_modes'] == true,
    region: region.code,
  );
}

/// Key 15: 2-8 bytes of a-z, 0-9 and '-', the first two a-z.
final _lang = RegExp(r'^[a-z]{2}[a-z0-9-]{0,6}$');

/// An https base address: https://host[:port] (a DNS name or IPv4 address,
/// or an IPv6 address in brackets), nothing after it, at most 64 bytes. The
/// rule of the check-in poster's and the join payload's urls.
bool httpsBaseUrlOk(String url) {
  if (url.length > 64 || url.codeUnits.any((c) => c > 0x7e)) return false;
  final m = _httpsBase.firstMatch(url);
  if (m == null) return false;
  final port = m.group(1);
  return port == null || int.parse(port) <= 65535;
}

final _httpsBase = RegExp(
  r'^https://(?:[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*'
  r'|\[[0-9A-Fa-f:.]{2,45}\])(?::([1-9][0-9]{0,4}))?$',
);

const _keys = {
  1: 'game_id', 2: 'game_key', 3: 'node_id', 4: 'controller_id', //
  5: 'channel_hz', 6: 'max_hops', 7: 'teams', 8: 'mode_id', 9: 'role',
  10: 'game_seed', 11: 'params', 12: 'kind', 13: 'ca_sha256', 14: 'urls',
  15: 'lang', 16: 'fetch_modes', 17: 'forget_modes', 18: 'region',
};

bool _hasBytes(Object? v) => switch (v) {
  Uint8List() => true,
  final List<Object?> l => l.any(_hasBytes),
  final Map<Object?, Object?> m => m.values.any(_hasBytes),
  _ => false,
};

/// Checks the tag (in constant time) with [joinKey], then the body.
/// Throws [JoinException].
JoinPayload decodeJoin(List<int> data, List<int> joinKey) {
  if (data.length < 1 + 1 + joinMacSize || data.length > joinMaxLength) {
    throw JoinException(
      JoinFailure.length,
      'a join payload is 34 to $joinMaxLength bytes, not ${data.length}',
    );
  }
  if (data[0] != joinVersion) {
    throw JoinException(
      JoinFailure.version,
      'unknown join format version ${data[0]}',
    );
  }
  final signed = data.sublist(0, data.length - joinMacSize);
  final tag = data.sublist(data.length - joinMacSize);
  final mac = Hmac(sha256, joinKey).convert(signed).bytes;
  if (!constantTimeEquals(mac, tag)) {
    throw JoinException(
      JoinFailure.mac,
      "the join payload's tag does not match this field's join key",
    );
  }
  final Object? raw;
  try {
    raw = cborDecode(signed.sublist(1), allowBytes: true);
  } on CborException catch (e) {
    throw _body('join body: ${e.message}');
  }
  if (raw is! Map) throw _body('the join body must be a map');
  final j = <String, Object?>{};
  for (final e in raw.entries) {
    final k = e.key;
    if (k is! int || k < 0 || k >= 32) {
      throw _body('join body key $k: keys are integers below 32');
    }
    final name = _keys[k];
    if (name == null) continue; // an optional field a newer controller adds
    var v = e.value;
    if (name == 'kind') {
      if (v is! int || v < 0 || v > 1) throw _body('unknown join kind $v');
      v = JoinKind.values[v];
    }
    if ((name == 'ca_sha256' || name == 'urls' || name == 'lang') &&
        v == null) {
      throw _body('$name is null: leave an optional field out instead');
    }
    if ((name == 'fetch_modes' || name == 'forget_modes') && v != true) {
      throw _body('$name: CBOR true when set, else left out');
    }
    if (name == 'region') {
      final r = v is int && v != 0 ? regionsByNumber[v] : null;
      if (r == null) {
        throw _body(
          'region $v: a known region from 1 up (EU868 leaves the key out)',
        );
      }
      v = r.code;
    }
    j[name] = v;
  }
  for (final name in ['game_key', 'ca_sha256']) {
    if (j.containsKey(name) && j[name] is! Uint8List) {
      throw _body('$name must be a byte string');
    }
  }
  for (final name in ['teams', 'mode_id', 'role', 'params', 'urls', 'lang']) {
    if (_hasBytes(j[name])) throw _body('$name must be text');
  }
  return _validate(j);
}

/// The payload for [j], tagged with [joinKey] (the controller's side; the app
/// uses it in tests and to make test cards).
Uint8List encodeJoin(JoinPayload j, List<int> joinKey) {
  if (joinKey.length != joinKeySize) {
    throw ArgumentError('the join key is $joinKeySize bytes');
  }
  final v = _validate({
    'game_id': j.gameId,
    'game_key': j.gameKey,
    'node_id': j.nodeId,
    'controller_id': j.controllerId,
    'channel_hz': j.channelHz,
    'max_hops': j.maxHops,
    'teams': j.teams,
    'mode_id': j.modeId,
    'role': j.role,
    'game_seed': j.gameSeed,
    'params': j.params,
    'kind': j.kind,
    'ca_sha256': j.caSha256,
    'urls': j.urls,
    'lang': j.lang,
    'fetch_modes': j.fetchModes,
    'forget_modes': j.forgetModes,
    'region': j.region,
  });
  final body = <int, Object?>{
    1: v.gameId,
    2: v.gameKey,
    3: v.nodeId,
    4: v.controllerId,
    5: v.channelHz,
    6: v.maxHops,
    7: v.teams,
    8: v.modeId,
    9: v.role,
    10: v.gameSeed,
    if (v.params != null) 11: v.params,
    12: v.kind.index,
    if (v.caSha256 != null) 13: v.caSha256,
    if (v.urls != null) 14: v.urls,
    if (v.lang != null) 15: v.lang,
    if (v.fetchModes) 16: true,
    if (v.forgetModes) 17: true,
    if (v.region != eu868.code) 18: regionsByCode[v.region]!.number,
  };
  final signed = Uint8List.fromList([joinVersion, ...cborEncode(body)]);
  final out = Uint8List.fromList([
    ...signed,
    ...Hmac(sha256, joinKey).convert(signed).bytes,
  ]);
  if (out.length > joinMaxLength) {
    throw JoinException(
      JoinFailure.length,
      'the join payload is ${out.length} bytes; at most $joinMaxLength fit',
    );
  }
  return out;
}

/// The QR code and console form: "atalaia:join:" + base64url, no padding.
String joinToText(List<int> payload) =>
    joinTextPrefix + base64Url.encode(payload).replaceAll('=', '');

/// The payload in a join text. Spaces and line ends around it are ignored;
/// anything not canonical base64url is refused (reason `length`).
Uint8List joinFromText(String text) {
  final t = text.trim();
  if (!t.startsWith(joinTextPrefix)) {
    throw JoinException(
      JoinFailure.length,
      'a join text starts with $joinTextPrefix',
    );
  }
  final b64 = t.substring(joinTextPrefix.length);
  if (b64.length % 4 == 1 || !RegExp(r'^[A-Za-z0-9_-]*$').hasMatch(b64)) {
    throw JoinException(JoinFailure.length, 'the join text is not base64url');
  }
  final Uint8List raw;
  try {
    raw = base64Url.decode(b64.padRight((b64.length + 3) ~/ 4 * 4, '='));
  } on FormatException {
    throw JoinException(JoinFailure.length, 'the join text is not base64url');
  }
  if (joinToText(raw) != joinTextPrefix + b64) {
    throw JoinException(
      JoinFailure.length,
      'the join text is not in canonical base64url',
    );
  }
  return raw;
}

/// Whether [text] looks like a join text (before any check).
bool isJoinText(String text) => text.trim().startsWith(joinTextPrefix);
