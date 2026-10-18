// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Player tags (ADR-P3-9, protocol/nfc-tag.md): the Dart side of
/// `core/src/tag.c` and `simulator/atalaia_sim/tag.py`.
///
/// ```
/// version (1, = 1) | player (1-32 bytes) | team (1) | game_id (2, BE) | mac (16)
/// ```
///
/// `mac` is HMAC-SHA256 over everything before it, keyed with the game's
/// 16-byte key and truncated to 16 bytes. All three implementations check
/// protocol/vectors/tag.json byte for byte.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import 'bytes.dart';
import 'ndef.dart';

const int tagVersion = 1;
const int tagMacSize = 16;
const int tagKeySize = 16;
const int tagPlayerMax = 32;
const int tagMinLength = 1 + 1 + 1 + 2 + tagMacSize;
const int tagMaxLength = 1 + tagPlayerMax + 1 + 2 + tagMacSize;
const String tagNdefType = 'application/vnd.atalaia.tag';

final _player = RegExp(r'^[A-Za-z0-9._-]{1,32}$');

/// Why a tag was refused; [name] is the protocol's reason string.
enum TagFailure { format, version, game, mac, team }

class TagException implements Exception {
  TagException(this.reason, this.message);

  final TagFailure reason;
  final String message;

  @override
  String toString() => 'TagException(${reason.name}): $message';
}

/// What a player tag says: who, which team (1-based, 0 for none), which game.
class PlayerTag {
  const PlayerTag({
    required this.player,
    required this.team,
    required this.gameId,
  });

  final String player;
  final int team;
  final int gameId;

  @override
  bool operator ==(Object other) =>
      other is PlayerTag &&
      other.player == player &&
      other.team == team &&
      other.gameId == gameId;

  @override
  int get hashCode => Object.hash(player, team, gameId);

  @override
  String toString() => 'PlayerTag($player, team $team, game $gameId)';
}

/// Whether [player] is a valid player id: 1-32 ASCII letters, digits, `.`, `_`, `-`.
bool isPlayerId(String player) => _player.hasMatch(player);

Uint8List _mac(List<int> gameKey, List<int> body) => Uint8List.fromList(
  Hmac(sha256, gameKey).convert(body).bytes.sublist(0, tagMacSize),
);

/// The payload of [tag], signed with the 16-byte [gameKey].
Uint8List encodeTag(PlayerTag tag, List<int> gameKey) {
  if (gameKey.length != tagKeySize) {
    throw ArgumentError('the game key is $tagKeySize bytes');
  }
  if (!isPlayerId(tag.player)) {
    throw ArgumentError.value(
      tag.player,
      'player',
      "1-32 letters, digits, '-', '_' or '.'",
    );
  }
  if (tag.team < 0 || tag.team > 255 || tag.gameId < 0 || tag.gameId > 0xffff) {
    throw ArgumentError('team is 0-255 and gameId 0-65535');
  }
  final body = BytesBuilder()
    ..addByte(tagVersion)
    ..add(ascii.encode(tag.player))
    ..addByte(tag.team)
    ..add([tag.gameId >> 8, tag.gameId & 0xff]);
  final b = body.toBytes();
  return Uint8List.fromList([...b, ..._mac(gameKey, b)]);
}

/// The tag in [data], checked for the game [gameId] with [gameKey] and
/// [teamCount] teams. Throws [TagException]; the checks and their order are
/// those of protocol/nfc-tag.md: length, version, game, MAC (constant time),
/// player id, team.
PlayerTag decodeTag(
  List<int> data, {
  required int gameId,
  required List<int> gameKey,
  required int teamCount,
}) {
  if (data.length < tagMinLength || data.length > tagMaxLength) {
    throw TagException(
      TagFailure.format,
      'a tag is $tagMinLength to $tagMaxLength bytes, not ${data.length}',
    );
  }
  if (data[0] != tagVersion) {
    throw TagException(TagFailure.version, 'unknown tag version ${data[0]}');
  }
  final body = data.sublist(0, data.length - tagMacSize);
  final mac = data.sublist(data.length - tagMacSize);
  final gid = (body[body.length - 2] << 8) | body[body.length - 1];
  if (gid != gameId) {
    throw TagException(
      TagFailure.game,
      'the tag is for game $gid, not $gameId',
    );
  }
  if (!constantTimeEquals(_mac(gameKey, body), mac)) {
    throw TagException(TagFailure.mac, 'the signature does not match');
  }
  final rawPlayer = body.sublist(1, body.length - 3);
  final player = rawPlayer.every((b) => b < 0x80)
      ? ascii.decode(rawPlayer)
      : '';
  if (!isPlayerId(player)) {
    throw TagException(TagFailure.format, 'malformed player id');
  }
  final team = body[body.length - 3];
  if (team > teamCount) {
    throw TagException(
      TagFailure.team,
      "team $team is not one of the game's $teamCount",
    );
  }
  return PlayerTag(player: player, team: team, gameId: gid);
}

/// A Type 2 tag's user memory (page 4 on) holding the tag's NDEF record.
Uint8List tagToNdefMemory(List<int> payload) =>
    type2Memory(payload, tagNdefType);

/// The player-tag record's payload in a Type 2 tag's user memory, or null.
Uint8List? tagFromNdefMemory(List<int> mem) =>
    payloadFromType2Memory(mem, tagNdefType);

/// The data of the `nfc.tag` input event a host gives the node for a read
/// of [uid] ([payload] null: the card has no player-tag record; [gameKey]
/// null: no game with a key), as `atalaia_tag_event_json()` writes it.
Map<String, Object> tagEventData({
  required List<int> uid,
  required List<int>? payload,
  required int gameId,
  required List<int>? gameKey,
  required List<String> teams,
}) {
  final data = <String, Object>{
    'uid': hexEncode(uid.length > 10 ? uid.sublist(0, 10) : uid),
    'valid': false,
  };
  if (payload == null) {
    data['reason'] = 'unsigned';
    return data;
  }
  if (gameKey == null) {
    data['reason'] = 'no_game';
    return data;
  }
  final PlayerTag tag;
  try {
    tag = decodeTag(
      payload,
      gameId: gameId,
      gameKey: gameKey,
      teamCount: teams.length,
    );
  } on TagException catch (e) {
    data['reason'] = e.reason.name;
    return data;
  }
  data['valid'] = true;
  data['player'] = tag.player;
  if (tag.team != 0) data['team'] = teams[tag.team - 1];
  return data;
}

/// [tagEventData] as JSON text, keys in the C core's order.
String tagEventJson({
  required List<int> uid,
  required List<int>? payload,
  required int gameId,
  required List<int>? gameKey,
  required List<String> teams,
}) => jsonEncode(
  tagEventData(
    uid: uid,
    payload: payload,
    gameId: gameId,
    gameKey: gameKey,
    teams: teams,
  ),
);
