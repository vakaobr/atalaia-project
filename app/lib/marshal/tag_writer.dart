// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Writing players' tags (protocol/nfc-tag.md, ADR-P3-9): whoever holds the
/// game key may write them, and the app gets it from the game's join
/// payload (checked with the field join key). For each player: the id and
/// the team, then the tag held to the phone; the app writes one NDEF record
/// application/vnd.atalaia.tag signed with the game key
/// (lib/security/nfc_tag_signer.dart) and checks what it wrote.
library;

import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../platform/services.dart';
import '../prop/join_screen.dart';
import '../protocol/join_payload.dart';
import '../security/bytes.dart';
import '../security/ndef.dart';
import '../security/nfc_tag_signer.dart';
import '../ui/widgets.dart';

/// The NDEF message for [tag] signed with [gameKey], and a check that it
/// reads back as that tag.
List<int> playerTagMessage(PlayerTag tag, List<int> gameKey, int teamCount) {
  final payload = encodeTag(tag, gameKey);
  final message = ndefMimeRecord(payload, tagNdefType);
  final back = payloadFromNdefMessage(message, tagNdefType)!;
  final read = decodeTag(
    back,
    gameId: tag.gameId,
    gameKey: gameKey,
    teamCount: teamCount,
  );
  assert(read == tag, 'the tag must read back');
  return message;
}

class TagWriterScreen extends StatefulWidget {
  const TagWriterScreen({this.game, super.key});

  /// The game to write for (tests); otherwise the marshal picks it.
  final JoinPayload? game;

  @override
  State<TagWriterScreen> createState() => _TagWriterScreenState();
}

class _TagWriterScreenState extends State<TagWriterScreen> {
  JoinPayload? _game;
  final _player = TextEditingController();
  int _team = 1;
  bool _writing = false;
  String? _error;
  final _written = <(String, String, String)>[]; // player, team, uid

  @override
  void initState() {
    super.initState();
    _game = widget.game;
  }

  @override
  void dispose() {
    _player.dispose();
    super.dispose();
  }

  Future<void> _pickGame() async {
    final s = context.s;
    final j = await Navigator.push<JoinPayload>(
      context,
      MaterialPageRoute(builder: (_) => JoinScreen(title: s.t('tags.game'))),
    );
    if (j != null && mounted) {
      setState(() {
        _game = j;
        _team = 1;
      });
    }
  }

  Future<void> _write() async {
    final g = _game;
    final player = _player.text.trim();
    if (g == null) return;
    if (!isPlayerId(player)) {
      setState(() => _error = 'tags.bad_player');
      return;
    }
    final nfc = context.services.nfc;
    final tag = PlayerTag(player: player, team: _team, gameId: g.gameId);
    final message = playerTagMessage(tag, g.gameKey, g.teams.length);
    setState(() {
      _writing = true;
      _error = null;
    });
    try {
      final uid = await nfc.writeNext(Uint8List.fromList(message));
      if (!mounted) return;
      setState(() {
        _written.insert(0, (
          player,
          _team == 0 ? '—' : g.teams[_team - 1],
          hexEncode(uid),
        ));
        _player.clear();
      });
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
    final g = _game;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('tags.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(s.t('tags.intro')),
          const SizedBox(height: 12),
          if (g == null)
            FilledButton.icon(
              key: const Key('tags-pick-game'),
              icon: const Icon(Icons.qr_code_scanner),
              label: Text(s.t('tags.game')),
              onPressed: _pickGame,
            )
          else ...[
            Notice(
              s.t('tags.for_game', {'game': g.gameId, 'mode': g.modeId}),
              kind: NoticeKind.ok,
              action: TextButton(
                onPressed: _pickGame,
                child: Text(s.t('tags.other_game')),
              ),
            ),
            if (_error != null)
              Notice(
                s.t(_error!),
                kind: NoticeKind.error,
                key: const Key('tags-error'),
              ),
            TextField(
              key: const Key('tags-player'),
              controller: _player,
              decoration: InputDecoration(
                labelText: s.t('tags.player'),
                helperText: s.t('tags.player_hint'),
              ),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              children: [
                for (var i = 0; i < g.teams.length; i++)
                  ChoiceChip(
                    key: Key('tags-team-${g.teams[i]}'),
                    avatar: TeamDot(g.teams[i]),
                    label: Text(s.team(g.teams[i])),
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
        ],
      ),
    );
  }
}
