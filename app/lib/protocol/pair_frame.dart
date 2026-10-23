// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Pair frames (protocol/adoption.md section 7, RFC 0001 Amendment 8):
/// adopting a box over the radio with the 6-digit code it shows, for the
/// Android field controller (slice S7c of PE24). The Dart twin of
/// simulator/atalaia_sim/pair_frame.py and core/src/pair_frame.c; all check
/// protocol/vectors/pairing.json.
///
/// Message type 10, game id 0, hop_limit 0, never relayed, in the clear;
/// the security is CPace's (security/cpace.dart) run with the code:
///
///     OFFER   box -> controllers   pair id, name, tier
///     START   controller -> box    pair id, sid, Ya
///     REPLY   box -> controller    pair id, sid, Yb, tag_b
///     KEY     controller -> box    pair id, sid, tag_a, nonce, sealed join key and field name
///     DONE    box -> controller    pair id, sid, result, fingerprint, tag
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import '../security/aes_ccm.dart';
import '../security/cpace.dart';
import 'cbor.dart';
import 'field_frame.dart';

const pairFrameType = 10;
const pfBodyMax = 200;
const pfFrameMin = rfHeaderSize + 1;
const pfFrameMax = rfHeaderSize + pfBodyMax;
const pfPairIdSize = 8;
const pfSidSize = 16;
const pfPointSize = 32;
const pfTagSize = 16;
const pfNonceSize = 13;
const pfFpSize = 4;
const pfKeySize = 32;
const pfNameMax = 24;
const pfFieldNameMax = 48;
const pfSealedMin = pfKeySize + 1 + ccmMicSize;
const pfSealedMax = pfSealedMin + pfFieldNameMax;

/// DONE's result: adoption.c's order.
const pfResults = [
  'adopted',
  'same',
  'readopted',
  'need_pin',
  'bad_pin',
  'locked',
  'busy',
  'bad_key',
  'bad_card',
  'store_failed',
];
const pfOkResults = ['adopted', 'same', 'readopted'];

const _kinds = {'offer': 1, 'start': 2, 'reply': 3, 'key': 4, 'done': 5};
final _kindNames = {for (final e in _kinds.entries) e.value: e.key};

const _fields = <String, List<(int, String)>>{
  'offer': [(2, 'pair_id'), (3, 'name'), (4, 'tier')],
  'start': [(2, 'pair_id'), (5, 'sid'), (6, 'point')],
  'reply': [(2, 'pair_id'), (5, 'sid'), (6, 'point'), (7, 'tag')],
  'key': [(2, 'pair_id'), (5, 'sid'), (7, 'tag'), (8, 'nonce'), (9, 'sealed')],
  'done': [
    (2, 'pair_id'),
    (5, 'sid'),
    (10, 'result'),
    (11, 'fingerprint'),
    (7, 'tag'),
  ],
};
const _sizes = {
  'pair_id': pfPairIdSize,
  'sid': pfSidSize,
  'point': pfPointSize,
  'tag': pfTagSize,
  'nonce': pfNonceSize,
  'fingerprint': pfFpSize,
};

/// version 1, normal priority, no ACK, not encrypted (0x28), game 0, type 10.
final pairFrameHeader = Uint8List.fromList([0x28, 0, 0, 0, 0, 0, 0, 0, 10]);

class PairFrameException implements Exception {
  PairFrameException(this.message);
  final String message;
  @override
  String toString() => 'PairFrameException: $message';
}

Map<String, Object?> validatePairMessage(Map<String, Object?> msg) {
  final fields = _fields[msg['kind']];
  if (fields == null) {
    throw PairFrameException('kind: one of ${_kinds.keys.join(', ')}');
  }
  for (final (_, name) in fields) {
    final v = msg[name];
    final size = _sizes[name];
    if (size != null) {
      if (v is! List<int> || v.length != size) {
        throw PairFrameException('$name: $size bytes');
      }
    } else if (name == 'name') {
      if (v is! String ||
          v.contains('\x00') ||
          utf8.encode(v).isEmpty ||
          utf8.encode(v).length > pfNameMax) {
        throw PairFrameException('name: 1-$pfNameMax bytes of text');
      }
    } else if (name == 'tier') {
      if (v is! int || v < 0 || v > 2) throw PairFrameException('tier: 0-2');
    } else if (name == 'sealed') {
      if (v is! List<int> || v.length < pfSealedMin || v.length > pfSealedMax) {
        throw PairFrameException('sealed: $pfSealedMin-$pfSealedMax bytes');
      }
    } else if (name == 'result') {
      if (!pfResults.contains(v)) throw PairFrameException('result: unknown');
    }
  }
  return msg;
}

Uint8List encodePairBody(Map<String, Object?> msg) {
  validatePairMessage(msg);
  final kind = msg['kind']! as String;
  final out = <Object, Object?>{1: _kinds[kind]};
  for (final (key, name) in _fields[kind]!) {
    final v = msg[name];
    out[key] = name == 'result'
        ? pfResults.indexOf(v! as String)
        : v is List<int>
        ? Uint8List.fromList(v)
        : v;
  }
  final body = cborEncode(out);
  if (body.length > pfBodyMax) {
    throw PairFrameException(
      'body of ${body.length} bytes; at most $pfBodyMax',
    );
  }
  return body;
}

Map<String, Object?> decodePairBody(List<int> data) {
  if (data.isEmpty || data.length > pfBodyMax) {
    throw PairFrameException('body length');
  }
  final Object? raw;
  try {
    raw = cborDecode(data, allowBytes: true);
  } on CborException catch (e) {
    throw PairFrameException('not CBOR: ${e.message}');
  } on FormatException catch (e) {
    throw PairFrameException('not CBOR: ${e.message}');
  }
  bool uint(Object? k, int hi) => k is int && k >= 0 && k <= hi;
  if (raw is! Map ||
      raw.isEmpty ||
      !raw.keys.every((k) => uint(k, 0xffffffff))) {
    throw PairFrameException('a body is a map with integer keys');
  }
  if (raw.keys.first != 1 || !uint(raw[1], 255)) {
    throw PairFrameException('the kind comes first');
  }
  final kind = _kindNames[raw[1]];
  if (kind == null) throw PairFrameException('unknown kind ${raw[1]}');
  final own = {for (final (k, _) in _fields[kind]!) k};
  for (final k in raw.keys) {
    final key = k as int;
    if (key >= 32) throw PairFrameException('key $key: from 32 up refused');
    if (key != 1 && key <= 11 && !own.contains(key)) {
      throw PairFrameException("key $key is not a $kind's");
    }
  }
  final msg = <String, Object?>{'kind': kind};
  for (final (key, name) in _fields[kind]!) {
    if (!raw.containsKey(key)) throw PairFrameException('missing key $key');
    var v = raw[key];
    if (name == 'result') {
      if (!uint(v, pfResults.length - 1)) {
        throw PairFrameException('result out of range');
      }
      v = pfResults[v! as int];
    }
    msg[name] = v;
  }
  return validatePairMessage(msg);
}

/// A pair frame's header and length: version 1, not encrypted, game 0, type 10.
bool isPairFrame(List<int> pkt) {
  if (pkt.length < pfFrameMin || pkt.length > pfFrameMax) return false;
  final vf = pkt[0];
  return pkt[1] == 0 &&
      pkt[2] == 0 &&
      pkt[8] == pairFrameType &&
      vf & 2 == 0 &&
      vf >> 5 & 7 == 1;
}

Uint8List encodePairFrame(Map<String, Object?> msg) =>
    Uint8List.fromList([...pairFrameHeader, ...encodePairBody(msg)]);

Map<String, Object?> decodePairFrame(List<int> pkt) {
  if (!isPairFrame(pkt)) throw PairFrameException('not a pair frame');
  return decodePairBody(pkt.sublist(rfHeaderSize));
}

// --- the exchange's keys --------------------------------------------------------

/// CPace's CI: lv_cat("atalaia pair v1", pair id).
Uint8List pairChannelId(List<int> pairId) =>
    lvCat([utf8.encode('atalaia pair v1'), pairId]);

bool pairCodeOk(Object? code) =>
    code is String && RegExp(r'^[0-9]{6}$').hasMatch(code);

Uint8List pairGenerator(String code, List<int> pairId, List<int> sid) {
  if (!pairCodeOk(code)) throw PairFrameException('the code is 6 digits');
  return cpaceGenerator(ascii.encode(code), pairChannelId(pairId), sid);
}

Uint8List pairIsk(List<int> sid, List<int> k, List<int> ya, List<int> yb) =>
    cpaceIskIr(
      sid,
      k,
      ya,
      utf8.encode('atalaia controller'),
      yb,
      utf8.encode('atalaia box'),
    );

/// A run's keys from CPace's ISK: HKDF-SHA256 with the sid as salt.
class PairKeys {
  PairKeys(List<int> isk, List<int> sid)
    : confirmA = hkdfSha256(
        isk,
        32,
        salt: sid,
        info: utf8.encode('atalaia pair confirm a v1'),
      ),
      confirmB = hkdfSha256(
        isk,
        32,
        salt: sid,
        info: utf8.encode('atalaia pair confirm b v1'),
      ),
      seal = hkdfSha256(
        isk,
        16,
        salt: sid,
        info: utf8.encode('atalaia pair seal v1'),
      ),
      nonce = hkdfSha256(
        isk,
        32,
        salt: sid,
        info: utf8.encode('atalaia pair nonce v1'),
      );

  final Uint8List confirmA, confirmB, seal, nonce;

  Uint8List _tag(List<int> key, List<int> msg) => Uint8List.fromList(
    Hmac(sha256, key).convert(msg).bytes.sublist(0, pfTagSize),
  );

  Uint8List get tagReply => _tag(confirmB, utf8.encode('atalaia pair reply'));
  Uint8List get tagKey => _tag(confirmA, utf8.encode('atalaia pair key'));
  Uint8List tagDone(String result, List<int> fingerprint) => _tag(confirmB, [
    ...utf8.encode('atalaia pair done'),
    pfResults.indexOf(result),
    ...fingerprint,
  ]);

  /// KEY's nonce: the run's sender id's pseudonym, boot 1, count 0.
  Uint8List keyNonce(List<int> sender) => fieldNonce(nonce, sender, 1, 0);

  void wipe() {
    for (final b in [confirmA, confirmB, seal, nonce]) {
      b.fillRange(0, b.length, 0);
    }
  }
}

Uint8List _keyAad(List<int> pairId, List<int> sid) => Uint8List.fromList([
  ...utf8.encode('atalaia pair key v1'),
  ...pairId,
  ...sid,
]);

Uint8List sealPairKey(
  PairKeys ks,
  List<int> nonce,
  List<int> pairId,
  List<int> sid,
  List<int> joinKey,
  String name,
) {
  final raw = utf8.encode(name);
  if (joinKey.length != pfKeySize || raw.length > pfFieldNameMax) {
    throw PairFrameException('a 32-byte key and a name of at most 48 bytes');
  }
  return ccmSeal(ks.seal, nonce, [
    ...joinKey,
    raw.length,
    ...raw,
  ], _keyAad(pairId, sid));
}

/// The join key and the field's name in KEY's sealed bytes (the box's side).
(Uint8List, String) openPairKey(
  PairKeys ks,
  List<int> nonce,
  List<int> pairId,
  List<int> sid,
  List<int> sealed,
) {
  final Uint8List plain;
  try {
    plain = ccmOpen(ks.seal, nonce, sealed, _keyAad(pairId, sid));
  } on CcmException {
    throw PairFrameException('the sealed key does not authenticate');
  }
  if (plain.length < pfKeySize + 1 ||
      plain[pfKeySize] != plain.length - pfKeySize - 1) {
    throw PairFrameException("the sealed key's name length");
  }
  return (
    Uint8List.sublistView(plain, 0, pfKeySize),
    utf8.decode(plain.sublist(pfKeySize + 1)),
  );
}

/// The field's fingerprint (adoption.md) as its 4 bytes.
Uint8List fieldFingerprintBytes(List<int> joinKey) => Uint8List.fromList(
  Hmac(sha256, joinKey)
      .convert(utf8.encode('atalaia-field-fingerprint'))
      .bytes
      .sublist(0, pfFpSize),
);
