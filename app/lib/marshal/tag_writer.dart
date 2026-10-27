// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Writing players' tags (protocol/nfc-tag.md, ADR-P3-9, decision TW-1): the
/// field controller signs each tag with the game's key (`POST
/// /api/v1/games/{id}/tags`, for the GM token or a marshal's) and this phone
/// writes the NDEF record it gets to the NFC tag. The marshal's phone never
/// holds the field join key or the game key for it, and so needs the
/// controller (the field's Wi-Fi) for every tag: that is the price of the
/// key staying in one place.
///
/// [PlayerTagForm] is the form both writers share: the marshal's screen
/// ([TagWriterScreen]) and the phone controller's own
/// (`controller/controller_tags_screen.dart`). It checks that what the
/// controller sent is the tag asked for before it goes to the NFC tag (the
/// MAC cannot be checked here: only the controller has the key; the boxes
/// check it).
library;

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../app.dart';
import '../checkin/checkin_client.dart';
import '../checkin/field_trust.dart';
import '../checkin/my_replicas.dart';
import '../l10n/strings.dart';
import '../platform/services.dart';
import '../security/bytes.dart';
import '../security/ndef.dart';
import '../security/nfc_tag_signer.dart';
import '../ui/widgets.dart';

/// The controller would not make the tag; [key] is the text to show
/// (`tags.offline`, `tags.not_marshal`, ...) and [detail] the controller's
/// own words, for `tags.refused`.
class TagRequestError implements Exception {
  TagRequestError(this.key, [this.detail]);

  final String key;
  final String? detail;

  @override
  String toString() => 'TagRequestError($key, $detail)';
}

/// The NDEF message in the controller's [answer] (its `ndef`, hex), checked
/// to hold a player tag for [player] in game [gameId] with team number
/// [team]: one record of the tag's type, the layout of protocol/nfc-tag.md,
/// the id, team and game as asked. Throws [FormatException] when not.
Uint8List checkedTagMessage(
  Map<String, Object?> answer, {
  required String player,
  required int team,
  required int gameId,
}) {
  final hex = answer['ndef'];
  if (hex is! String) throw const FormatException('no ndef');
  final message = hexDecode(hex);
  final payload = payloadFromNdefMessage(message, tagNdefType);
  if (payload == null ||
      payload.length < tagMinLength ||
      payload.length > tagMaxLength) {
    throw const FormatException('not a player tag');
  }
  final id = String.fromCharCodes(payload.sublist(1, payload.length - 19));
  final game =
      (payload[payload.length - 18] << 8) | payload[payload.length - 17];
  if (payload[0] != tagVersion ||
      id != player ||
      payload[payload.length - 19] != team ||
      game != gameId) {
    throw const FormatException('not the tag asked for');
  }
  return message;
}

/// The form: a player's id, the team, then the tag held to the phone.
/// [request] asks the controller for the tag (throwing [TagRequestError]).
class PlayerTagForm extends StatefulWidget {
  const PlayerTagForm({
    required this.gameId,
    required this.teams,
    required this.request,
    super.key,
  });

  final int gameId;
  final List<String> teams;
  final Future<Map<String, Object?>> Function(String player, String? team)
  request;

  @override
  State<PlayerTagForm> createState() => _PlayerTagFormState();
}

class _PlayerTagFormState extends State<PlayerTagForm> {
  final _player = TextEditingController();
  int _team = 1;
  bool _writing = false;
  String? _error;
  String? _detail;
  final _written = <(String, String, String)>[]; // player, team, uid

  @override
  void dispose() {
    _player.dispose();
    super.dispose();
  }

  Future<void> _write() async {
    final player = _player.text.trim();
    if (!isPlayerId(player)) {
      setState(() {
        _error = 'tags.bad_player';
        _detail = null;
      });
      return;
    }
    final nfc = context.services.nfc;
    final team = _team == 0 ? null : widget.teams[_team - 1];
    setState(() {
      _writing = true;
      _error = null;
      _detail = null;
    });
    try {
      final answer = await widget.request(player, team);
      final Uint8List message;
      try {
        message = checkedTagMessage(
          answer,
          player: player,
          team: _team,
          gameId: widget.gameId,
        );
      } on FormatException {
        throw TagRequestError('tags.bad_answer');
      }
      if (!mounted) return;
      final uid = await nfc.writeNext(message);
      if (!mounted) return;
      setState(() {
        _written.insert(0, (player, team ?? '—', hexEncode(uid)));
        _player.clear();
      });
    } on TagRequestError catch (e) {
      if (mounted) {
        setState(() {
          _error = e.key;
          _detail = e.detail;
        });
      }
    } on NfcWriteException catch (e) {
      if (mounted && e.reason != 'cancelled') {
        setState(() => _error = 'tags.write_${e.reason}');
      }
    } finally {
      if (mounted) setState(() => _writing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final teams = widget.teams;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (_error != null)
          Notice(
            _error == 'tags.refused'
                ? s.t(_error!, {'error': _detail ?? ''})
                : s.t(_error!),
            kind: NoticeKind.error,
            key: const Key('tags-error'),
          ),
        TextField(
          key: const Key('tags-player'),
          controller: _player,
          decoration: InputDecoration(
            labelText: s.t('tags.player'),
            helperText: s.t('tags.player_hint'),
            helperMaxLines: 3,
          ),
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          children: [
            for (var i = 0; i < teams.length; i++)
              ChoiceChip(
                key: Key('tags-team-${teams[i]}'),
                avatar: TeamDot(teams[i]),
                label: Text(s.team(teams[i])),
                selected: _team == i + 1,
                onSelected: (_) => setState(() => _team = i + 1),
              ),
            ChoiceChip(
              label: Text(s.t('tags.no_team')),
              selected: _team == 0,
              onSelected: (_) => setState(() => _team = 0),
            ),
          ],
        ),
        const SizedBox(height: 16),
        if (_writing)
          Notice(
            s.t('tags.hold'),
            key: const Key('tags-waiting'),
            action: TextButton(
              onPressed: context.services.nfc.cancelWrite,
              child: Text(s.t('common.cancel')),
            ),
          )
        else
          FilledButton.icon(
            key: const Key('tags-write'),
            icon: const Icon(Icons.nfc),
            label: Text(s.t('tags.write')),
            onPressed: _write,
          ),
        if (_written.isNotEmpty) SectionTitle(s.t('tags.written')),
        for (final (player, team, uid) in _written)
          ListTile(
            dense: true,
            leading: TeamDot(team == '—' ? null : team),
            title: Text(player),
            subtitle: Text(uid),
          ),
      ],
    );
  }
}

/// The marshal's screen: the game of this phone's check-in, and the form.
class TagWriterScreen extends StatefulWidget {
  const TagWriterScreen({
    required this.checkin,
    required this.field,
    super.key,
  });

  final FieldCheckin checkin;
  final PinnedField field;

  @override
  State<TagWriterScreen> createState() => _TagWriterScreenState();
}

class _TagWriterScreenState extends State<TagWriterScreen> {
  late final CheckinClient _client = CheckinClient(
    context.services.fieldHttp(widget.field),
  );
  List<String>? _teams;
  String? _error;

  FieldCheckin get c => widget.checkin;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  /// What a controller's refusal means for the marshal.
  TagRequestError _why(CheckinException e) => switch (e.status) {
    0 => TagRequestError('tags.offline'),
    401 => TagRequestError('tags.session'),
    403 => TagRequestError('tags.not_marshal'),
    409 => TagRequestError('tags.no_key'),
    _ => TagRequestError('tags.refused', e.message),
  };

  Future<void> _load() async {
    try {
      final game = await _client.game(c.token, c.gameId);
      if (!mounted) return;
      setState(() => _teams = [for (final t in game['teams']! as List) '$t']);
    } on CheckinException catch (e) {
      if (!mounted) return;
      final why = _why(e);
      setState(() => _error = why.key);
    }
  }

  Future<Map<String, Object?>> _request(String player, String? team) async {
    try {
      return await _client.playerTag(
        c.token,
        c.gameId,
        player: player,
        team: team,
      );
    } on CheckinException catch (e) {
      throw _why(e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final teams = _teams;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('tags.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(s.t('tags.intro')),
          const SizedBox(height: 12),
          if (_error != null)
            Notice(
              s.t(_error!),
              kind: NoticeKind.error,
              key: const Key('tags-load-error'),
              action: TextButton(
                onPressed: () {
                  setState(() => _error = null);
                  unawaited(_load());
                },
                child: Text(s.t('marshal.retry')),
              ),
            )
          else if (teams == null)
            Notice(s.t('tags.loading'), key: const Key('tags-loading'))
          else ...[
            Notice(
              s.t('tags.for_game', {'game': c.gameName}),
              kind: NoticeKind.ok,
            ),
            PlayerTagForm(gameId: c.gameId, teams: teams, request: _request),
          ],
        ],
      ),
    );
  }
}
