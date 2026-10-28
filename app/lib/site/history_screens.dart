// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The player's own game history (decision S20-8: "the history views in the
/// app"), with the account on the field's site server: the games they played
/// (by the player ids the account holds at each field, or a check-in through
/// a registration), each game's scores and the player's own events in it, in
/// words. It reads what the site server already answers a player
/// (`SiteApi.history`); no data is kept on the phone. What a player sees of
/// a game's whole log and timeline needs a role at the field, so those stay
/// with the staff pages.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../player/field_feed.dart' show FeedEvent;
import '../player/player_screens.dart' show eventText;
import '../ui/widgets.dart';
import 'site_api.dart';
import 'site_client.dart';
import 'site_screens.dart' show siteError, siteMoment;

/// Game time as `m:ss` (or `h:mm:ss`).
String historyClock(int ms) {
  final total = ms ~/ 1000;
  final h = total ~/ 3600;
  final m = (total % 3600) ~/ 60;
  String two(int v) => v.toString().padLeft(2, '0');
  return h > 0 ? '$h:${two(m)}:${two(total % 60)}' : '$m:${two(total % 60)}';
}

/// The games the account played, newest first.
class GameHistoryScreen extends StatefulWidget {
  const GameHistoryScreen({required this.session, super.key});
  final SiteSession session;

  @override
  State<GameHistoryScreen> createState() => _GameHistoryScreenState();
}

class _GameHistoryScreenState extends State<GameHistoryScreen> {
  List<HistoryGame>? _games;
  String? _error;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    setState(() {
      _games = null;
      _error = null;
    });
    try {
      final games = await SiteApi(widget.session).history();
      // Newest first; a game without a start time by when it was made is
      // last in what the site server sent, so keep that order reversed.
      final sorted = games.reversed.toList();
      if (mounted) setState(() => _games = sorted);
    } on SiteException catch (e) {
      if (mounted) setState(() => _error = siteError(context.s, e));
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final games = _games;
    return Scaffold(
      appBar: AppBar(
        title: Text(s.t('history.title')),
        actions: [
          IconButton(
            key: const Key('history-reload'),
            tooltip: s.t('history.reload'),
            icon: const Icon(Icons.refresh),
            onPressed: _load,
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(s.t('history.intro')),
          const SizedBox(height: 12),
          if (_error != null)
            Notice(
              _error!,
              kind: NoticeKind.error,
              key: const Key('history-error'),
            )
          else if (games == null)
            const Center(child: CircularProgressIndicator())
          else if (games.isEmpty)
            Notice(s.t('history.none'), key: const Key('history-none'))
          else
            for (final g in games) _tile(s, g),
        ],
      ),
    );
  }

  Widget _tile(Strings s, HistoryGame g) {
    final when = g.startedAt ?? g.endedAt;
    final winner = g.winner;
    return Card(
      child: ListTile(
        key: Key('history-game-${g.id}'),
        title: Text(g.name.isEmpty ? s.t('history.unnamed') : g.name),
        subtitle: Text(
          [
            if (g.field.isNotEmpty) g.field,
            if (when != null) siteMoment(when),
            s.t('history.state.${g.state}'),
            if (g.ended && winner != null)
              s.t('history.winner', {'team': s.team(winner)}),
          ].join(' · '),
        ),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute<void>(builder: (_) => GameHistoryDetailScreen(g)),
        ),
      ),
    );
  }
}

/// One game: its scores and the player's own events.
class GameHistoryDetailScreen extends StatelessWidget {
  const GameHistoryDetailScreen(this.game, {super.key});
  final HistoryGame game;

  /// An event in words, the player's own ids shown as "you".
  String _text(Strings s, HistoryEvent e) {
    final mine = game.playerIds.toSet();
    final you = s.t('history.you');
    final data = {
      for (final x in e.data.entries)
        x.key: mine.contains(x.value) ? you : x.value,
    };
    return eventText(s, FeedEvent(e.type, e.team, data, e.tMs, 0));
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final g = game;
    final winner = g.winner;
    final when = g.startedAt ?? g.endedAt;
    final teams = [
      ...g.teams,
      for (final t in g.totals.keys)
        if (!g.teams.contains(t)) t,
    ];
    return Scaffold(
      appBar: AppBar(
        title: Text(g.name.isEmpty ? s.t('history.unnamed') : g.name),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            [
              if (g.field.isNotEmpty) s.t('history.at', {'field': g.field}),
              if (when != null) siteMoment(when),
              s.t('history.state.${g.state}'),
            ].join(' · '),
            key: const Key('history-head'),
          ),
          if (g.registered)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(s.t('history.registered')),
            ),
          SectionTitle(s.t('history.scores')),
          if (teams.isEmpty)
            Text(s.t('history.no_scores'), key: const Key('history-no-scores'))
          else ...[
            for (final t in teams)
              ListTile(
                key: Key('history-score-$t'),
                dense: true,
                title: Text(s.team(t)),
                trailing: Text(
                  '${g.totals[t] ?? 0}',
                  style: const TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            if (g.ended)
              Text(
                winner == null
                    ? s.t('history.no_winner')
                    : s.t('history.winner', {'team': s.team(winner)}),
                key: const Key('history-winner'),
              ),
          ],
          SectionTitle(s.t('history.events')),
          if (g.events.isEmpty)
            Notice(
              s.t('history.no_events'),
              key: const Key('history-no-events'),
            )
          else
            for (final e in g.events)
              ListTile(
                dense: true,
                leading: Text(
                  historyClock(e.tMs),
                  style: const TextStyle(
                    fontFeatures: [FontFeature.tabularFigures()],
                  ),
                ),
                title: Text(_text(s, e)),
              ),
        ],
      ),
    );
  }
}
