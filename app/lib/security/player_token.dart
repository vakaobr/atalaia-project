// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Player tokens (ADR-P3-9, protocol/player-token.md).
///
/// ```
/// apt1.<base64url(payload)>.<base64url(HMAC-SHA256(key, "apt1." + base64url(payload)))>
/// ```
///
/// `payload` is canonical JSON (see canonical_json.dart) with exactly `exp`,
/// `game_id`, `player_id`, `role`, `squad` and `team`. The controller issues
/// and checks tokens (`controller/atalaia_controller/player_token.py`; an
/// Android controller uses this file); a player's phone only carries its
/// token and may [PlayerToken.peek] at it for display. Both implementations
/// check protocol/vectors/player_token.json.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import 'bytes.dart';
import 'canonical_json.dart';
import 'nfc_tag_signer.dart' show isPlayerId;

const String tokenPrefix = 'apt1';
const int tokenMacSize = 32;
const int tokenKeyMin = 16;
const int tokenKeyMax = 64;
const int tokenMaxLength = 512;

final _version = RegExp(r'^apt[0-9]{1,3}$');

/// Why a token was refused; [name] is the protocol's reason string.
enum TokenFailure { format, version, mac, game, team, expired }

class TokenException implements Exception {
  TokenException(this.reason, this.message);

  final TokenFailure reason;
  final String message;

  @override
  String toString() => 'TokenException(${reason.name}): $message';
}

/// The roles of ADR-P3-6's visibility table.
enum PlayerRole {
  player('player'),
  squadLeader('squad_leader'),
  vip('vip'),
  marshal('marshal'),
  gm('gm'),
  spectator('spectator');

  const PlayerRole(this.wire);

  /// The role as it is written in the token.
  final String wire;

  static PlayerRole? fromWire(String wire) {
    for (final r in values) {
      if (r.wire == wire) return r;
    }
    return null;
  }
}

/// What a player token says.
class PlayerClaims {
  PlayerClaims({
    required this.playerId,
    required this.team,
    required this.squad,
    required this.role,
    required this.gameId,
    required this.exp,
  }) {
    if (!isPlayerId(playerId)) {
      throw TokenException(
        TokenFailure.format,
        "player_id is 1-32 letters, digits, '.', '_' or '-'",
      );
    }
    _range('team', team, 0, 8);
    _range('squad', squad, 0, 255);
    _range('game_id', gameId, 1, 0xfffe);
    _range('exp', exp, 1, 0xffffffff);
  }

  /// The player's id, the same as on their player tag.
  final String playerId;

  /// 1-based team id in the game's team list; 0 for none.
  final int team;

  /// Squad number 1-255; 0 for none.
  final int squad;

  final PlayerRole role;

  /// The game's 16-bit id (as on the radio and in the join payload).
  final int gameId;

  /// Expiry, Unix seconds: the token is refused from this second on.
  final int exp;

  static void _range(String name, int v, int lo, int hi) {
    if (v < lo || v > hi) {
      throw TokenException(TokenFailure.format, '$name is $lo-$hi, not $v');
    }
  }

  /// The claims from a decoded payload object; throws [TokenException] (format).
  factory PlayerClaims.fromJson(Object? json) {
    const fields = {'exp', 'game_id', 'player_id', 'role', 'squad', 'team'};
    if (json is! Map<String, Object?> ||
        json.length != fields.length ||
        !json.keys.every(fields.contains)) {
      throw TokenException(
        TokenFailure.format,
        'the payload has exactly the fields $fields',
      );
    }
    int integer(String k) {
      final v = json[k];
      if (v is! int) {
        throw TokenException(TokenFailure.format, '$k is an integer');
      }
      return v;
    }

    final playerId = json['player_id'];
    final roleText = json['role'];
    final role = roleText is String ? PlayerRole.fromWire(roleText) : null;
    if (playerId is! String || role == null) {
      throw TokenException(
        TokenFailure.format,
        'player_id is a string and role one of the known roles',
      );
    }
    return PlayerClaims(
      playerId: playerId,
      team: integer('team'),
      squad: integer('squad'),
      role: role,
      gameId: integer('game_id'),
      exp: integer('exp'),
    );
  }

  Map<String, Object> toJson() => {
    'exp': exp,
    'game_id': gameId,
    'player_id': playerId,
    'role': role.wire,
    'squad': squad,
    'team': team,
  };

  /// The canonical payload bytes.
  Uint8List payload() => canonicalJson(toJson());

  @override
  bool operator ==(Object other) =>
      other is PlayerClaims &&
      other.playerId == playerId &&
      other.team == team &&
      other.squad == squad &&
      other.role == role &&
      other.gameId == gameId &&
      other.exp == exp;

  @override
  int get hashCode => Object.hash(playerId, team, squad, role, gameId, exp);

  @override
  String toString() => 'PlayerClaims(${toJson()})';
}

/// Issuing, checking and reading player tokens.
abstract final class PlayerToken {
  static List<int> _key(List<int> key) {
    if (key.length < tokenKeyMin || key.length > tokenKeyMax) {
      throw ArgumentError('the token key is $tokenKeyMin-$tokenKeyMax bytes');
    }
    return key;
  }

  static List<int> _mac(List<int> key, String signed) =>
      Hmac(sha256, key).convert(ascii.encode(signed)).bytes;

  /// A token for [claims], signed with the controller's token [key].
  static String issue(PlayerClaims claims, List<int> key) {
    final signed = '$tokenPrefix.${base64UrlNoPad(claims.payload())}';
    return '$signed.${base64UrlNoPad(_mac(_key(key), signed))}';
  }

  static (List<String>, Uint8List) _split(String token) {
    if (token.isEmpty ||
        token.length > tokenMaxLength ||
        token.codeUnits.any((c) => c > 0x7f)) {
      throw TokenException(
        TokenFailure.format,
        'a token is 1-$tokenMaxLength ASCII characters',
      );
    }
    final parts = token.split('.');
    if (parts.length != 3) {
      throw TokenException(TokenFailure.format, 'a token has three parts');
    }
    if (parts[0] != tokenPrefix) {
      if (_version.hasMatch(parts[0])) {
        throw TokenException(
          TokenFailure.version,
          'unknown token version ${parts[0]}',
        );
      }
      throw TokenException(TokenFailure.format, 'not a player token');
    }
    final payload = base64UrlNoPadDecode(parts[1]);
    if (payload == null) {
      throw TokenException(TokenFailure.format, 'the payload is not base64url');
    }
    return (parts, payload);
  }

  static PlayerClaims _claims(Uint8List payload) {
    final Object? json;
    try {
      json = jsonDecode(utf8.decode(payload));
    } on FormatException {
      throw TokenException(TokenFailure.format, 'the payload is not JSON');
    }
    final claims = PlayerClaims.fromJson(json);
    if (!constantTimeEquals(claims.payload(), payload)) {
      throw TokenException(
        TokenFailure.format,
        'the payload is not canonical JSON',
      );
    }
    return claims;
  }

  /// The claims of [token], checked with [key] for the game [gameId] with
  /// [teamCount] teams at [now] (Unix seconds). Throws [TokenException]:
  /// format, version, mac, then (payload) format, game, team, expired.
  static PlayerClaims verify(
    String token,
    List<int> key, {
    required int gameId,
    required int teamCount,
    required int now,
  }) {
    _key(key);
    final (parts, payload) = _split(token);
    final mac = base64UrlNoPadDecode(parts[2]);
    if (mac == null || mac.length != tokenMacSize) {
      throw TokenException(TokenFailure.format, 'the MAC is 32 bytes');
    }
    if (!constantTimeEquals(_mac(key, '${parts[0]}.${parts[1]}'), mac)) {
      throw TokenException(TokenFailure.mac, "the token's MAC does not match");
    }
    final claims = _claims(payload);
    if (claims.gameId != gameId) {
      throw TokenException(
        TokenFailure.game,
        'the token is for game ${claims.gameId}, not $gameId',
      );
    }
    if (claims.team > teamCount) {
      throw TokenException(
        TokenFailure.team,
        "team ${claims.team} is not one of the game's $teamCount",
      );
    }
    if (now >= claims.exp) {
      throw TokenException(TokenFailure.expired, 'the token has expired');
    }
    return claims;
  }

  /// The claims of [token] WITHOUT checking its MAC, or null if it is not a
  /// well-formed version 1 token. For showing a player their own role and
  /// team only: never use the result to decide anything.
  static PlayerClaims? peek(String token) {
    try {
      return _claims(_split(token).$2);
    } on TokenException {
      return null;
    }
  }
}
