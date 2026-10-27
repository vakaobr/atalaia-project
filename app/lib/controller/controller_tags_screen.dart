// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Players' tags from the phone controller's own screen (decision TW-1): the
/// running controller signs each tag with the game's key (`POST
/// /api/v1/games/{id}/tags` on the loopback address with the GM token, as the
/// field card is asked for, controller_boxes_screen.dart) and this phone's
/// NFC writes it, with the same form as the marshal's
/// (marshal/tag_writer.dart). The game key never leaves the controller.
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../marshal/tag_writer.dart';
import '../ui/widgets.dart';

/// Asks this phone's running controller for a tag (its answer's `ndef` is
/// the record to write). [TagRequestError] when it will not make it.
Future<Map<String, Object?>> requestPlayerTag(
  int port,
  String gmToken,
  int gameId, {
  required String player,
  String? team,
}) async {
  final client = HttpClient();
  try {
    final req = await client.post(
      '127.0.0.1',
      port,
      '/api/v1/games/$gameId/tags',
    );
    req.headers
      ..set(HttpHeaders.authorizationHeader, 'Bearer $gmToken')
      ..contentType = ContentType.json;
    req.write(jsonEncode({'player': player, 'team': ?team}));
    final res = await req.close();
    final text = await utf8.decodeStream(res);
    if (res.statusCode == 200) {
      return (jsonDecode(text) as Map).cast<String, Object?>();
    }
    if (res.statusCode == 409) throw TagRequestError('tags.no_key');
    var detail = text;
    try {
      detail = '${(jsonDecode(text) as Map)['detail']}';
    } on Object {
      // Not JSON: the text itself.
    }
    throw TagRequestError('tags.refused', detail);
  } on SocketException {
    throw TagRequestError('tags.offline');
  } finally {
    client.close(force: true);
  }
}

/// The screen for the live [gameId] with its [teams] (the controller screen
/// opens it from its status).
class ControllerTagsScreen extends StatelessWidget {
  const ControllerTagsScreen({
    required this.gameId,
    required this.gameName,
    required this.teams,
    required this.request,
    super.key,
  });

  final int gameId;
  final String gameName;
  final List<String> teams;

  /// Asks the controller for the tag (tests give their own).
  final Future<Map<String, Object?>> Function(String player, String? team)
  request;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('tags.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(s.t('ctl.tags_hint')),
          const SizedBox(height: 12),
          Notice(s.t('tags.for_game', {'game': gameName}), kind: NoticeKind.ok),
          PlayerTagForm(gameId: gameId, teams: teams, request: request),
        ],
      ),
    );
  }
}
