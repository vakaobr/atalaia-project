// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Signed player tags for the GM console, the controller's own screen and
/// the marshal's app (decision TW-1, protocol/nfc-tag.md): the phone
/// controller's `POST /api/v1/games/{id}/tags`, as the Pi's
/// controller/atalaia_controller/player_tags.py answers it (the shared
/// contract cases check both).
///
/// The body is `{"player": "p-17", "team": "blue"}` (no team: none), the
/// answer the tag's payload, the NDEF record and the Type 2 memory, all in
/// hex, signed with the live game's key. The game key never goes out: only
/// the tag's own MAC, which is what the box checks.
library;

import '../security/bytes.dart';
import '../security/ndef.dart';
import '../security/nfc_tag_signer.dart';
import 'controller_checkin.dart';
import 'controller_engine.dart';

/// The tag asked for in [body] for game [gameId]: staff only (the GM token,
/// or a marshal's for this game).
Map<String, Object?> issuePlayerTag(
  ControllerEngine engine,
  ApiViewer viewer,
  int gameId,
  Map<String, Object?> body,
) {
  if (!viewer.isStaff) {
    throw ControllerError(
      "staff only: the GM token or a marshal's token",
      status: 403,
    );
  }
  if (viewer.kind == 'player' && viewer.gameId != gameId) {
    throw ControllerError('this token is for another game', status: 403);
  }
  final game = engine.getGame(gameId);
  final unknown = body.keys.where((k) => k != 'player' && k != 'team').toList()
    ..sort();
  if (unknown.isNotEmpty) throw ControllerError('unknown fields $unknown');
  final player = body['player'];
  if (player is! String || !isPlayerId(player)) {
    throw ControllerError("player: 1-32 letters, digits, '-', '_' or '.'");
  }
  final teams = [for (final t in game['teams']! as List) t as String];
  final name = body['team'];
  var team = 0;
  String? teamName;
  if (name != null && name != '') {
    final i = name is String ? teams.indexOf(name) : -1;
    if (i < 0) throw ControllerError('team: one of $teams, or none');
    team = i + 1;
    teamName = name as String;
  }
  if (gameId <= 0 || gameId > 0xffff) {
    throw ControllerError.conflict(
      'game $gameId: a tag holds a 16-bit game id',
    );
  }
  final live = engine.liveGame;
  final key = engine.gameKey;
  if (live == null || live['id'] != gameId || engine.keyLost || key.isEmpty) {
    throw ControllerError.conflict(
      'no key: the game is not live on this controller',
    );
  }
  final payload = encodeTag(
    PlayerTag(player: player, team: team, gameId: gameId),
    key,
  );
  return {
    'game_id': gameId,
    'player': player,
    'team': teamName,
    'team_id': team,
    'mime': tagNdefType,
    'payload': hexEncode(payload),
    'ndef': hexEncode(ndefMimeRecord(payload, tagNdefType)),
    'memory': hexEncode(tagToNdefMemory(payload)),
  };
}
