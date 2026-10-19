// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The player's view (plan phase D, ADR-P3-10's "player role"): link to the
/// field controller with its address and access code (scan the scoreboard's
/// QR code, or type them), then follow the game: the clock, the teams'
/// points, who holds each objective, lives, eliminated teams, the GM's
/// messages and the game's events, in the app's language. Player tokens
/// with roles (squad leader, VIP...) and positions are plan phase E.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../prop/game_timer.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'field_feed.dart';

class PlayerStartScreen extends StatefulWidget {
  const PlayerStartScreen({super.key});

  @override
  State<PlayerStartScreen> createState() => _PlayerStartScreenState();
}

class _PlayerStartScreenState extends State<PlayerStartScreen> {
  late final TextEditingController _address;
  late final TextEditingController _code;
  String? _error;

  @override
  void initState() {
    super.initState();
    final st = AppScope.read(context).settings;
    _address = TextEditingController(text: st.controllerUrl ?? '');
    _code = TextEditingController(text: st.readToken ?? '');
  }

  @override
  void dispose() {
    _address.dispose();
    _code.dispose();
    super.dispose();
  }

  Future<void> _go(FieldLink? link) async {
    if (link == null) {
      setState(() => _error = 'player.bad_link');
      return;
    }
    final app = AppScope.read(context);
    await app.update((x) {
      x.controllerUrl = link.base.toString();
      x.readToken = link.token;
    });
    if (!mounted) return;
    await Navigator.push(
      context,
      MaterialPageRoute<void>(builder: (_) => PlayerScreen(link: link)),
    );
  }

  Future<void> _scan() async {
    final s = context.s;
    final qr = context.services.qr;
    if (!await qr.available) {
      if (mounted) setState(() => _error = 'join.no_camera');
      return;
    }
    final text = await qr.scan(
      hint: s.t('player.scan_hint'),
      cancel: s.t('common.cancel'),
    );
    if (text != null && mounted) await _go(FieldLink.parse(text));
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('role.player'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(s.t('player.intro')),
          const SizedBox(height: 12),
          if (_error != null) Notice(s.t(_error!), kind: NoticeKind.error),
          FilledButton.icon(
            key: const Key('player-scan'),
            icon: const Icon(Icons.qr_code_scanner),
            label: Text(s.t('player.scan')),
            onPressed: _scan,
          ),
          SectionTitle(s.t('player.by_hand')),
          TextField(
            key: const Key('player-address'),
            controller: _address,
            keyboardType: TextInputType.url,
            decoration: InputDecoration(
              labelText: s.t('player.address'),
              hintText: '192.168.4.1:8080',
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('player-code'),
            controller: _code,
            decoration: InputDecoration(labelText: s.t('player.code')),
          ),
          const SizedBox(height: 12),
          FilledButton(
            key: const Key('player-connect'),
            onPressed: () => _go(FieldLink.parse(_address.text, _code.text)),
            child: Text(s.t('player.connect')),
          ),
        ],
      ),
    );
  }
}

class PlayerScreen extends StatefulWidget {
  const PlayerScreen({required this.link, this.feed, super.key});

  final FieldLink link;

  /// A feed to show instead of connecting (tests).
  final FieldFeed? feed;

  @override
  State<PlayerScreen> createState() => _PlayerScreenState();
}

class _PlayerScreenState extends State<PlayerScreen> {
  late final FieldFeed feed;
  Timer? _clock;

  @override
  void initState() {
    super.initState();
    feed =
        widget.feed ??
        FieldFeed(widget.link, connect: context.services.feedConnect);
    if (widget.feed == null) unawaited(feed.start());
    _clock = Timer.periodic(const Duration(milliseconds: 500), (_) {
      if (mounted && feed.gameState == 'running') setState(() {});
    });
  }

  @override
  void dispose() {
    _clock?.cancel();
    if (widget.feed == null) feed.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('role.player'))),
      body: ListenableBuilder(
        listenable: feed,
        builder: (context, _) => PlayerView(feed: feed),
      ),
    );
  }
}

/// What a player sees of the game.
class PlayerView extends StatelessWidget {
  const PlayerView({required this.feed, super.key});
  final FieldFeed feed;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final app = context.app;
    final mine = app.settings.myTeam;
    final g = feed.game;
    final teams = feed.teams;
    final left = feed.remainingMs;
    final t = feed.gameTimeMs;
    final messages = [
      for (final e in feed.events)
        if (e.type == 'gm.message' && e.data['text'] is String) e,
    ];
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        switch (feed.state) {
          FeedState.connecting => Notice(s.t('player.connecting')),
          FeedState.closed => Notice(
            s.t('player.offline'),
            kind: NoticeKind.warning,
          ),
          FeedState.denied => Notice(
            s.t('player.denied'),
            kind: NoticeKind.error,
          ),
          FeedState.open => const SizedBox.shrink(),
        },
        if (g == null && feed.state == FeedState.open)
          Notice(s.t('player.no_game')),
        if (g != null) ...[
          Text(
            '${g['name'] ?? ''}',
            key: const Key('player-game'),
            style: Theme.of(context).textTheme.headlineMedium,
          ),
          Wrap(
            spacing: 12,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Chip(label: Text(s.t('state.${feed.gameState}'))),
              if (left != null || t != null)
                Text(
                  clockText(left ?? t!),
                  key: const Key('player-clock'),
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
              if (left != null) Text(s.t('player.left')),
            ],
          ),
          if (feed.gameState == 'ended') _Result(feed: feed),
          for (final m in messages.take(3))
            Notice(
              s.t('player.message', {'text': m.data['text']}),
              kind: NoticeKind.warning,
            ),
          SectionTitle(s.t('player.score')),
          for (final (team, points) in feed.ranking)
            _TeamRow(
              team: team,
              points: points,
              mine: team == mine,
              out: feed.eliminated.contains(team),
              lives: feed.lives[team],
              onTap: () => app.update((x) => x.myTeam = team),
            ),
          if (teams.isNotEmpty && mine == null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                s.t('player.pick_team'),
                style: TextStyle(color: Theme.of(context).hintColor),
              ),
            ),
          if (feed.nodes.isNotEmpty) ...[
            SectionTitle(s.t('player.objectives')),
            for (final n in feed.nodes.values)
              ListTile(
                dense: true,
                leading: TeamDot(n['owner'] as String?),
                title: Text(
                  '${n['name'] ?? s.t('player.node', {'n': n['node_id']})}',
                ),
                subtitle: Text(
                  n['owner'] is String
                      ? s.t('player.held_by', {'team': s.team('${n['owner']}')})
                      : s.t('player.held_by_none'),
                ),
              ),
          ],
          if (feed.lives.isNotEmpty) ...[
            SectionTitle(s.t('player.lives')),
            for (final e in feed.lives.entries)
              ListTile(
                dense: true,
                title: Text(e.key),
                trailing: Text(
                  '${e.value}',
                  style: const TextStyle(fontSize: 22),
                ),
              ),
          ],
          SectionTitle(s.t('player.events')),
          if (feed.events.isEmpty) Text(s.t('player.no_events')),
          for (final e in feed.events.take(30))
            ListTile(
              dense: true,
              leading: TeamDot(e.team, size: 12),
              title: Text(eventText(s, e)),
              trailing: Text(clockText(e.tMs)),
            ),
        ],
      ],
    );
  }
}

class _Result extends StatelessWidget {
  const _Result({required this.feed});
  final FieldFeed feed;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final r = feed.ranking;
    final String text;
    if (r.isEmpty || r.first.$2 <= 0) {
      text = s.t('player.ended');
    } else if (r.length > 1 && r[0].$2 == r[1].$2) {
      text = s.t('player.tie');
    } else {
      text = s.t('player.winner', {'team': s.team(r.first.$1)});
    }
    return Notice(text, kind: NoticeKind.ok, key: const Key('player-result'));
  }
}

class _TeamRow extends StatelessWidget {
  const _TeamRow({
    required this.team,
    required this.points,
    required this.mine,
    required this.out,
    required this.lives,
    required this.onTap,
  });

  final String team;
  final int points;
  final bool mine;
  final bool out;
  final int? lives;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final color = AtalaiaColors.team(team);
    return Card(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: color, width: mine ? 4 : 2),
      ),
      child: ListTile(
        key: Key('player-team-$team'),
        onTap: onTap,
        leading: TeamDot(team, size: 28),
        title: Text(
          s.team(team).toUpperCase(),
          style: TextStyle(
            fontWeight: FontWeight.w700,
            decoration: out ? TextDecoration.lineThrough : null,
          ),
        ),
        subtitle: Text(
          [
            if (mine) s.t('player.my_team'),
            if (out) s.t('player.eliminated'),
            if (lives != null) s.t('player.lives_left', {'n': lives}),
          ].join(' · '),
        ),
        trailing: Text(
          '$points',
          key: Key('player-points-$team'),
          style: const TextStyle(fontSize: 32, fontWeight: FontWeight.w700),
        ),
      ),
    );
  }
}

/// An event of the game in words (the types of protocol/schema/events.yaml
/// that players care about; others show their type).
String eventText(Strings s, FeedEvent e) {
  final team = e.team == null ? '' : s.team(e.team!);
  final d = e.data;
  String? str(String k) => d[k] is String ? d[k]! as String : null;
  final key = 'event.${e.type}';
  final args = <String, Object?>{
    'team': team,
    'zone': str('zone') ?? s.t('player.node', {'n': e.node}),
    'previous': s.team(str('previous_team') ?? ''),
    'player': str('player') ?? '',
    'owner': str('owner') ?? '',
    'lives': d['lives_left'] ?? '',
    'amount': d['amount'] ?? '',
    'winner': s.team(str('winner') ?? ''),
    'text': str('text') ?? '',
    'fuse': d['fuse_s'] ?? '',
    'reason': str('reason') ?? '',
  };
  return s.tOr(key, e.type, args);
}
