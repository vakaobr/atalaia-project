// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Field frames (protocol/field-frames.md, RFC 0001 Amendment 7): the radio
/// outside any game, for the Android field controller (slice S7c of PE24).
/// The Dart twin of simulator/atalaia_sim/field_frame.py and
/// core/src/field_frame.c; all three check protocol/vectors/field_frame.json.
///
/// A free box announces itself (ANNOUNCE), a controller asks who is free
/// (DISCOVER), invites a free box into its next game (INVITE: a join payload
/// in one to three parts, for the box's device id and the token of its last
/// announcement) and says that a game is over (GAME_OVER: the game id and its
/// key's tag). On air:
///
///     header (9: game 0, source 0, seq 0, hop_limit 0, type 9) | nonce (13) | body | MIC (8)
///
/// sealed with AES-128-CCM under [fieldKey] (HKDF-SHA256 of the field join
/// key). The nonce never comes from a random number generator (decision
/// RJ-15): the sender's pseudonym, its boot count and a frame count
/// ([FieldNonceSource]).
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import '../security/aes_ccm.dart';
import '../security/bytes.dart';
import 'cbor.dart';

const fieldFrameType = 9;
const rfHeaderSize = 9;
const ffNonceSize = 13;
const ffMicSize = 8;
const ffBodyMax = 200 - ffNonceSize; // 187
const ffFrameMin = rfHeaderSize + ffNonceSize + 1 + ffMicSize; // 31
const ffFrameMax = rfHeaderSize + 200 + ffMicSize; // 217
const ffDeviceSize = 8;
const ffTokenSize = 8;
const ffNameMax = 24;
const ffRoleMax = 31;
const ffPartsMax = 3;
const ffChunkMax = 153;
const ffJoinMax = 448;
const ffSenderSize = 8;
const ffTagSize = 8;
const ffBootMax = 0xffffff;
const ffCtrMax = 0xffff;

/// What a box answers to an invite (ANNOUNCE key 10), in their order.
const ffResults = [
  'accepted',
  'busy',
  'refused',
  'no_mode',
  'not_box',
  'storage',
  'radio',
  'ended',
];

const _kinds = {
  'announce': 1,
  'discover': 2,
  'invite': 3,
  'game_over': 4,
  'move': 5,
};
final _kindNames = {for (final e in _kinds.entries) e.value: e.key};

// Body keys.
const _kKind = 1, _kDevice = 2, _kToken = 3;
const _kName = 4, _kTier = 5, _kLastGame = 6, _kLastRole = 7;
const _kBattery = 8, _kAnswer = 9, _kResult = 10;
const _kInvite = 4, _kPart = 5, _kParts = 6, _kChunk = 7;
const _kGame = 4, _kKeyTag = 5;
// MOVE (RFC 0001 Amendment 19): the field's new channel (Hz) and a revision.
const _kChannel = 4, _kRev = 5;

/// The header every field frame carries: version 1, normal priority, no
/// ACK, encrypted (0x2A), game 0, source 0, seq 0, hop_limit 0, type 9.
final fieldFrameHeader = Uint8List.fromList([0x2A, 0, 0, 0, 0, 0, 0, 0, 9]);

class FieldFrameException implements Exception {
  FieldFrameException(this.message);
  final String message;
  @override
  String toString() => 'FieldFrameException: $message';
}

// --- keys ---------------------------------------------------------------------

/// HKDF-SHA256 (RFC 5869): extract (no salt: 32 zero bytes), then expand.
Uint8List hkdfSha256(
  List<int> ikm,
  int length, {
  List<int> salt = const [],
  List<int> info = const [],
}) {
  if (length > 255 * 32) throw ArgumentError('at most 8160 bytes');
  final prk = Hmac(
    sha256,
    salt.isEmpty ? Uint8List(32) : salt,
  ).convert(ikm).bytes;
  final out = BytesBuilder();
  var t = <int>[];
  for (var i = 1; out.length < length; i++) {
    t = Hmac(sha256, prk).convert([...t, ...info, i]).bytes;
    out.add(t);
  }
  return Uint8List.sublistView(out.toBytes(), 0, length);
}

/// A game key's tag (8 bytes), the boxes' epoch store's name for the key.
Uint8List gameKeyTag(List<int> gameKey) {
  if (gameKey.length != 16) throw ArgumentError('a game key is 16 bytes');
  return Uint8List.fromList(
    Hmac(
      sha256,
      gameKey,
    ).convert(utf8.encode('atalaia epoch tag')).bytes.sublist(0, ffTagSize),
  );
}

/// The field frames' AES-128 key from the 32-byte field join key.
Uint8List fieldKey(List<int> joinKey) {
  if (joinKey.length != 32) throw ArgumentError('the join key is 32 bytes');
  return hkdfSha256(joinKey, 16, info: utf8.encode('atalaia field frame v1'));
}

/// The key of the nonces' sender pseudonyms (32 bytes).
Uint8List fieldNonceKey(List<int> joinKey) {
  if (joinKey.length != 32) throw ArgumentError('the join key is 32 bytes');
  return hkdfSha256(joinKey, 32, info: utf8.encode('atalaia field nonce v1'));
}

/// HMAC-SHA256(nkey, sender)[:8] | boot (3 bytes) | ctr (2 bytes).
Uint8List fieldNonce(List<int> nkey, List<int> sender, int boot, int ctr) {
  if (sender.length != ffSenderSize ||
      boot < 0 ||
      boot > ffBootMax ||
      ctr < 0 ||
      ctr > ffCtrMax) {
    throw ArgumentError('sender: 8 bytes; boot: 0-16777215; ctr: 0-65535');
  }
  return Uint8List.fromList([
    ...Hmac(sha256, nkey).convert(sender).bytes.take(8),
    boot >> 16 & 0xff,
    boot >> 8 & 0xff,
    boot & 0xff,
    ctr >> 8 & 0xff,
    ctr & 0xff,
  ]);
}

/// A sender's nonces: its boot count is raised and stored ([saveBoot])
/// before the first nonce of a run and whenever the frame count would wrap,
/// so none ever repeats (field_frame.py `NonceSource`). A controller keeps
/// its boot count only in memory, with a sender id drawn fresh for every
/// run (decision RJ-15).
class FieldNonceSource {
  FieldNonceSource(
    List<int> joinKey,
    List<int> sender, {
    int Function()? loadBoot,
    bool Function(int boot)? saveBoot,
  }) : nkey = fieldNonceKey(joinKey),
       sender = Uint8List.fromList(sender) {
    if (sender.length != ffSenderSize) {
      throw ArgumentError('the sender id is 8 bytes');
    }
    _load = loadBoot ?? () => _stored;
    _save =
        saveBoot ??
        (b) {
          _stored = b;
          return true;
        };
  }

  final Uint8List nkey;
  final Uint8List sender;
  var _stored = 0;
  late final int Function() _load;
  late final bool Function(int) _save;
  int? boot;
  var ctr = 0;

  Uint8List next() {
    if (boot == null || ctr > ffCtrMax) {
      final b = _load() + 1;
      if (b > ffBootMax || !_save(b)) {
        throw FieldFrameException(
          'the boot count cannot be raised: no more field frames',
        );
      }
      boot = b;
      ctr = 0;
    }
    return fieldNonce(nkey, sender, boot!, ctr++);
  }
}

// --- bodies -------------------------------------------------------------------

bool _textOk(Object? v, int max) {
  if (v is! String || v.contains('\x00')) return false;
  final n = utf8.encode(v).length;
  return n >= 1 && n <= max;
}

bool _uint(Object? v, int lo, int hi) => v is int && v >= lo && v <= hi;

bool _fixed(Object? v, int size) => v is List<int> && v.length == size;

/// Checks a message (`kind` and its fields, bytes as `List<int>`).
Map<String, Object?> validateFieldMessage(Map<String, Object?> msg) {
  switch (msg['kind']) {
    case 'announce':
      if (!_fixed(msg['device_id'], ffDeviceSize) ||
          !_fixed(msg['token'], ffTokenSize)) {
        throw FieldFrameException('device_id and token are 8 bytes each');
      }
      if (!_textOk(msg['name'], ffNameMax)) {
        throw FieldFrameException('name: 1-$ffNameMax bytes of text');
      }
      if (!_uint(msg['tier'], 0, 2)) throw FieldFrameException('tier: 0-2');
      if (msg['last_game'] != null && !_uint(msg['last_game'], 1, 0xfffe)) {
        throw FieldFrameException('last_game: 1-65534');
      }
      if (msg['last_role'] != null && !_textOk(msg['last_role'], ffRoleMax)) {
        throw FieldFrameException('last_role: 1-$ffRoleMax bytes of text');
      }
      if (msg['battery_pct'] != null && !_uint(msg['battery_pct'], 0, 100)) {
        throw FieldFrameException('battery_pct: 0-100');
      }
      if ((msg['answer'] == null) != (msg['result'] == null)) {
        throw FieldFrameException(
          'an answer says its result, and only an answer has one',
        );
      }
      if (msg['answer'] != null &&
          (!_uint(msg['answer'], 1, 0xffff) ||
              !ffResults.contains(msg['result']))) {
        throw FieldFrameException('answer: 1-65535 with a known result');
      }
    case 'discover':
      break;
    case 'game_over':
      if (!_uint(msg['game_id'], 1, 0xfffe)) {
        throw FieldFrameException('game_id: 1-65534');
      }
      if (!_fixed(msg['key_tag'], ffTagSize)) {
        throw FieldFrameException('key_tag: 8 bytes');
      }
    case 'move':
      if (!_uint(msg['channel_hz'], 1, 0xffffffff)) {
        throw FieldFrameException('channel_hz: 1-4294967295');
      }
      if (!_uint(msg['rev'], 1, 0xffffffff)) {
        throw FieldFrameException('rev: 1-4294967295');
      }
    case 'invite':
      if (!_fixed(msg['device_id'], ffDeviceSize) ||
          !_fixed(msg['token'], ffTokenSize)) {
        throw FieldFrameException('device_id and token are 8 bytes each');
      }
      if (!_uint(msg['invite_id'], 1, 0xffff)) {
        throw FieldFrameException('invite_id: 1-65535');
      }
      final parts = msg['parts'];
      if (!_uint(parts, 1, ffPartsMax) ||
          !_uint(msg['part'], 0, (parts! as int) - 1)) {
        throw FieldFrameException('parts: 1-$ffPartsMax, part: 0 to parts - 1');
      }
      final chunk = msg['chunk'];
      if (chunk is! List<int> || chunk.isEmpty || chunk.length > ffChunkMax) {
        throw FieldFrameException('chunk: 1-$ffChunkMax bytes');
      }
    default:
      throw FieldFrameException('kind: one of ${_kinds.keys.join(', ')}');
  }
  return msg;
}

/// The CBOR body: integer keys in order, optional fields left out.
Uint8List encodeFieldBody(Map<String, Object?> msg) {
  validateFieldMessage(msg);
  final kind = msg['kind']! as String;
  final out = <Object, Object?>{_kKind: _kinds[kind]};
  Uint8List b(Object? v) => Uint8List.fromList(v! as List<int>);
  switch (kind) {
    case 'announce':
      out[_kDevice] = b(msg['device_id']);
      out[_kToken] = b(msg['token']);
      out[_kName] = msg['name'];
      out[_kTier] = msg['tier'];
      for (final (k, name) in [
        (_kLastGame, 'last_game'),
        (_kLastRole, 'last_role'),
        (_kBattery, 'battery_pct'),
      ]) {
        if (msg[name] != null) out[k] = msg[name];
      }
      if (msg['answer'] != null) {
        out[_kAnswer] = msg['answer'];
        out[_kResult] = ffResults.indexOf(msg['result']! as String);
      }
    case 'invite':
      out[_kDevice] = b(msg['device_id']);
      out[_kToken] = b(msg['token']);
      out[_kInvite] = msg['invite_id'];
      out[_kPart] = msg['part'];
      out[_kParts] = msg['parts'];
      out[_kChunk] = b(msg['chunk']);
    case 'game_over':
      out[_kGame] = msg['game_id'];
      out[_kKeyTag] = b(msg['key_tag']);
    case 'move':
      out[_kChannel] = msg['channel_hz'];
      out[_kRev] = msg['rev'];
  }
  final body = cborEncode(out);
  if (body.length > ffBodyMax) {
    throw FieldFrameException(
      'body of ${body.length} bytes; at most $ffBodyMax',
    );
  }
  return body;
}

const _announceKeys = {
  _kKind,
  _kDevice,
  _kToken,
  _kName,
  _kTier,
  _kLastGame,
  _kLastRole,
  _kBattery,
  _kAnswer,
  _kResult,
};
const _inviteKeys = {
  _kKind,
  _kDevice,
  _kToken,
  _kInvite,
  _kPart,
  _kParts,
  _kChunk,
};
const _gameOverKeys = {_kKind, _kGame, _kKeyTag};
const _moveKeys = {_kKind, _kChannel, _kRev};

/// Reads a body as the C decoder does (refusing what it refuses).
Map<String, Object?> decodeFieldBody(List<int> data) {
  if (data.isEmpty || data.length > ffBodyMax) {
    throw FieldFrameException('body length');
  }
  final Object? raw;
  try {
    raw = cborDecode(data, allowBytes: true);
  } on CborException catch (e) {
    throw FieldFrameException('not CBOR: ${e.message}');
  } on FormatException catch (e) {
    throw FieldFrameException('not CBOR: ${e.message}');
  }
  if (raw is! Map ||
      raw.isEmpty ||
      !raw.keys.every((k) => _uint(k, 0, 0xffffffff))) {
    throw FieldFrameException('a body is a map with integer keys');
  }
  if (raw.keys.first != _kKind || !_uint(raw[_kKind], 0, 255)) {
    throw FieldFrameException('the kind comes first');
  }
  final kind = _kindNames[raw[_kKind]];
  final allowed = switch (kind) {
    'announce' => _announceKeys,
    'discover' => const {_kKind},
    'invite' => _inviteKeys,
    'game_over' => _gameOverKeys,
    'move' => _moveKeys,
    _ => null,
  };
  if (allowed == null) throw FieldFrameException('unknown kind ${raw[_kKind]}');
  for (final k in raw.keys) {
    final key = k as int;
    if (key >= 32) throw FieldFrameException('key $key: from 32 up refused');
    if (!allowed.contains(key) && key >= 1 && key <= 10) {
      throw FieldFrameException("key $key is not a $kind's");
    }
  }
  final msg = <String, Object?>{'kind': kind};
  final Map<Object?, Object?> fields = raw;
  void need(int key, String name) {
    if (!fields.containsKey(key)) {
      throw FieldFrameException('missing key $key');
    }
    msg[name] = fields[key];
  }

  switch (kind) {
    case 'announce':
      need(_kDevice, 'device_id');
      need(_kToken, 'token');
      need(_kName, 'name');
      need(_kTier, 'tier');
      for (final (k, name) in [
        (_kLastGame, 'last_game'),
        (_kLastRole, 'last_role'),
        (_kBattery, 'battery_pct'),
        (_kAnswer, 'answer'),
      ]) {
        if (raw.containsKey(k)) msg[name] = raw[k];
      }
      if (raw.containsKey(_kResult)) {
        if (!_uint(raw[_kResult], 0, ffResults.length - 1)) {
          throw FieldFrameException('result out of range');
        }
        msg['result'] = ffResults[raw[_kResult]! as int];
      }
    case 'invite':
      need(_kDevice, 'device_id');
      need(_kToken, 'token');
      need(_kInvite, 'invite_id');
      need(_kPart, 'part');
      need(_kParts, 'parts');
      need(_kChunk, 'chunk');
    case 'game_over':
      need(_kGame, 'game_id');
      need(_kKeyTag, 'key_tag');
    case 'move':
      need(_kChannel, 'channel_hz');
      need(_kRev, 'rev');
  }
  return validateFieldMessage(msg);
}

// --- frames ---------------------------------------------------------------------

Uint8List _aad(List<int> header) =>
    Uint8List.fromList([...header.take(7), header[8]]);

/// A field frame's header and length (before any crypto).
bool isFieldFrame(List<int> pkt) {
  if (pkt.length < ffFrameMin || pkt.length > ffFrameMax) return false;
  final vf = pkt[0];
  final gameId = pkt[1] << 8 | pkt[2];
  return gameId == 0 &&
      pkt[8] == fieldFrameType &&
      vf & 2 != 0 &&
      vf >> 5 & 7 == 1;
}

/// A whole frame for [body], with the sender's next [nonce].
Uint8List sealFieldBody(List<int> key, List<int> body, List<int> nonce) {
  if (body.isEmpty || body.length > ffBodyMax) {
    throw FieldFrameException('body: 1-$ffBodyMax bytes');
  }
  if (nonce.length != ffNonceSize) {
    throw FieldFrameException('the nonce is 13 bytes');
  }
  return Uint8List.fromList([
    ...fieldFrameHeader,
    ...nonce,
    ...ccmSeal(key, nonce, body, _aad(fieldFrameHeader)),
  ]);
}

/// The body of [pkt]; [FieldFrameException] if it is not a field frame or
/// does not authenticate.
Uint8List openFieldFrame(List<int> key, List<int> pkt) {
  if (!isFieldFrame(pkt)) throw FieldFrameException('not a field frame');
  final nonce = pkt.sublist(rfHeaderSize, rfHeaderSize + ffNonceSize);
  try {
    return ccmOpen(
      key,
      nonce,
      pkt.sublist(rfHeaderSize + ffNonceSize),
      _aad(pkt.sublist(0, rfHeaderSize)),
    );
  } on CcmException {
    throw FieldFrameException(
      "does not authenticate (another field's key, or altered)",
    );
  }
}

Uint8List encodeFieldFrame(
  List<int> key,
  Map<String, Object?> msg,
  List<int> nonce,
) => sealFieldBody(key, encodeFieldBody(msg), nonce);

Map<String, Object?> decodeFieldFrame(List<int> key, List<int> pkt) =>
    decodeFieldBody(openFieldFrame(key, pkt));

// --- invite parts -----------------------------------------------------------------

/// A join payload as an invite's chunks: 153 bytes each, the last shorter.
List<Uint8List> splitJoin(List<int> payload) {
  if (payload.isEmpty || payload.length > ffJoinMax) {
    throw FieldFrameException('a join payload is 1-$ffJoinMax bytes');
  }
  return [
    for (var i = 0; i < payload.length; i += ffChunkMax)
      Uint8List.fromList(
        payload.sublist(
          i,
          i + ffChunkMax < payload.length ? i + ffChunkMax : payload.length,
        ),
      ),
  ];
}

/// An invite's frames, one per part, each with the next nonce.
List<Uint8List> inviteFrames(
  List<int> key,
  FieldNonceSource nonces,
  List<int> deviceId,
  List<int> token,
  int inviteId,
  List<int> payload,
) {
  final chunks = splitJoin(payload);
  return [
    for (var i = 0; i < chunks.length; i++)
      encodeFieldFrame(key, {
        'kind': 'invite',
        'device_id': deviceId,
        'token': token,
        'invite_id': inviteId,
        'part': i,
        'parts': chunks.length,
        'chunk': chunks[i],
      }, nonces.next()),
  ];
}

/// An invite's parts put back together (as the box does).
class FieldReassembly {
  String? _key;
  final _chunks = <int, Uint8List>{};

  Uint8List? add(Map<String, Object?> msg) {
    final parts = msg['parts']! as int;
    final key =
        '${msg['invite_id']}/${hexEncode(msg['token']! as List<int>)}/$parts';
    if (key != _key) {
      _key = key;
      _chunks.clear();
    }
    _chunks[msg['part']! as int] = Uint8List.fromList(
      msg['chunk']! as List<int>,
    );
    if (_chunks.length < parts) return null;
    final out = BytesBuilder();
    for (var i = 0; i < parts; i++) {
      out.add(_chunks[i]!);
    }
    _key = null;
    _chunks.clear();
    final payload = out.toBytes();
    if (payload.length > ffJoinMax) {
      throw FieldFrameException('the parts make more than a join payload');
    }
    return payload;
  }
}
