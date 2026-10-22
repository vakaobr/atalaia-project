// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The player's view (plan phase D, ADR-P3-10's "player role"): link to the
/// field controller with its address and access code (scan the scoreboard's
/// QR code, or type them), then follow the game: the clock, the teams'
/// points, who holds each objective, lives, eliminated teams, the GM's
/// messages and the game's events, in the app's language.
///
/// Plan phase 16 (phase 4, decision S16-13): *Online registration* opens
/// the field's site server (lib/site/).
///
/// Plan phase E: checking in at the field with its poster (lib/checkin/)
/// gives a player token; the view then follows the game over the field's
/// pinned HTTPS, shows the game's events from before the phone connected,
/// and lets the player share their position while the game runs (ADR-P3-6:
/// the controller decides who sees it).
///
/// A scenario's game (phase 4 plan phase 8, decision P4R24): the scenario's
/// objectives this player may know, with their names in the app's language
/// and where each stands (the controller sends a hidden one only once it is
/// revealed, and another team's or squad's never).
///
/// The field's boundary (decisions MF-31 to MF-40): while the player shares
/// their position in a running game, the phone tests its own fixes against
/// the field's boundary (lib/position/field_bounds.dart) and, once they have
/// stayed out, shows a banner, vibrates and says so in the sharing
/// notification; nothing about it is sent to anyone.
///
/// The field's branding (decisions BR1-BR24): its logo and name in the
/// header, its wallpaper behind the view (dimmed), its accent on the
/// primary buttons, and each team's crest and display name, downloaded
/// from the controller and kept per field; the default look without it.
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../app.dart';
import '../branding/branded.dart';
import '../branding/field_branding.dart';
import '../checkin/checkin_client.dart';
import '../checkin/checkin_screen.dart';
import '../l10n/strings.dart';
import '../platform/location.dart';
import '../position/field_bounds.dart';
import '../position/position_reporter.dart';
import '../prop/game_timer.dart';
import '../site/site_screens.dart';
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
            key: const Key('player-checkin'),
            icon: const Icon(Icons.how_to_reg),
            label: Text(s.t('player.checkin')),
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute<void>(builder: (_) => const CheckinScreen()),
            ),
          ),
          const _ContinueCheckin(),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            key: const Key('player-site'),
            icon: const Icon(Icons.event_available),
            label: Text(s.t('player.site')),
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute<void>(builder: (_) => const SiteScreen()),
            ),
          ),
          SectionTitle(s.t('player.watch')),
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

/// The latest check-in, to go back to it.
class _ContinueCheckin extends StatefulWidget {
  const _ContinueCheckin();

  @override
  State<_ContinueCheckin> createState() => _ContinueCheckinState();
}

class _ContinueCheckinState extends State<_ContinueCheckin> {
  @override
  void initState() {
    super.initState();
    unawaited(context.services.checkins.load());
  }

  @override
  Widget build(BuildContext context) {
    final services = context.services;
    return ListenableBuilder(
      listenable: services.checkins,
      builder: (context, _) {
        final c = services.checkins.latest();
        if (c == null) return const SizedBox.shrink();
        return Padding(
          padding: const EdgeInsets.only(top: 8),
          child: OutlinedButton.icon(
            key: const Key('player-continue'),
            icon: const Icon(Icons.arrow_forward),
            label: Text(context.s.t('player.continue', {'game': c.gameName})),
            onPressed: () async {
              final field = await services.trust.known(c.fieldId);
              if (field == null || !context.mounted) return;
              await Navigator.push(
                context,
                MaterialPageRoute<void>(
                  builder: (_) => CheckinStatusScreen(checkin: c, field: field),
                ),
              );
            },
          ),
        );
      },
    );
  }
}

class PlayerScreen extends StatefulWidget {
  const PlayerScreen({
    required this.link,
    this.feed,
    this.onAssignment,
    super.key,
  });

  final FieldLink link;

  /// A new player token after the GM changed this player's team or role.
  final Future<String?> Function()? onAssignment;

  /// A feed to show instead of connecting (tests).
  final FieldFeed? feed;

  @override
  State<PlayerScreen> createState() => _PlayerScreenState();
}

class _PlayerScreenState extends State<PlayerScreen> {
  late final FieldFeed feed;
  Timer? _clock;
  FieldBranding? _brand;
  TeamBranding _teams = TeamBranding.none;
  BrandingSource? _source;
  String? _teamInfoSeen;
  String? _brandEtagSeen;

  Future<void>? _brandLoading;

  /// The field's branding: as kept (at once), then fresh from the controller
  /// (one request at a time).
  Future<void> _loadBranding() => _brandLoading ??= _fetchBranding()
      .whenComplete(() => _brandLoading = null);

  Future<void> _fetchBranding() async {
    final services = context.services;
    final field = widget.link.field;
    final source = _source ??= services.brandingSource(
      field?.urls ?? [widget.link.base.toString()],
      field,
    );
    if (field != null && _brand == null) {
      final kept = await services.branding.cached(field.fieldId);
      if (mounted && kept != null) setState(() => _brand = kept);
    }
    final fresh = await services.branding.refresh(
      source,
      fieldId: field?.fieldId,
    );
    if (mounted && fresh != null) setState(() => _brand = fresh);
  }

  /// The game's team names at once, their crests when they arrive; again
  /// when the game's teams change, and the field's branding when the
  /// stream says it changed.
  void _onFeed() {
    final info = feed.game?['team_info'];
    final key = jsonEncode(info);
    if (key != _teamInfoSeen) {
      _teamInfoSeen = key;
      setState(() => _teams = TeamBranding.namesOf(info));
      final services = context.services;
      unawaited(
        services.branding.teams(_source, info).then((t) {
          if (mounted && jsonEncode(feed.game?['team_info']) == key) {
            setState(() => _teams = t);
          }
        }),
      );
    }
    final etag = feed.brandingEtag;
    if (etag != null && etag != _brandEtagSeen) {
      _brandEtagSeen = etag;
      if (_brand?.etag != etag) unawaited(_loadBranding());
    }
    // The GM changed the map features: the boundary again (MF-10, MF-35).
    final features = feed.mapFeatures;
    if (features != null &&
        !identical(features, _featuresSeen) &&
        (_reporter?.running ?? false)) {
      _featuresSeen = features;
      unawaited(_loadBounds(features: features));
    }
    // Paused, ended, or no longer a playing role: no warning (MF-37).
    if (_watch.out && !_warns) unawaited(_clearWarning());
  }

  // --- the out-of-bounds warning (decisions MF-31 to MF-40) -------------------

  FieldHttp? _http;
  FieldBounds _bounds = FieldBounds.none;
  final _watch = BoundsWatch();
  List<Map<String, Object?>>? _featuresSeen;

  /// Who is warned: a player, a squad leader or a VIP in a running game, on a
  /// field with a boundary they may see (MF-37); not marshals, the GM's
  /// phone nor spectators.
  bool get _warns {
    final role = feed.me?['role'];
    return feed.gameState == 'running' &&
        !_bounds.isEmpty &&
        (role == null ||
            role == 'player' ||
            role == 'squad_leader' ||
            role == 'vip');
  }

  /// The level the controller keeps for this player (ML-5), or null.
  int? get _myLevel {
    final me = feed.me?['player_id'];
    final level = feed.positions[me]?['level'];
    return level is int ? level : null;
  }

  Future<void> _loadBounds({List<Map<String, Object?>>? features}) async {
    final http = _http;
    if (http == null) return;
    final b = await loadFieldBounds(http, feed.link.token, features: features);
    if (!mounted || b == null) return;
    setState(() => _bounds = b);
    if (b.isEmpty && _watch.out) await _clearWarning();
  }

  void _onFix(LocationFix fix) {
    if (!_warns) return;
    final alert = _watch.check(
      _bounds,
      fix,
      _myLevel,
      DateTime.now().millisecondsSinceEpoch,
    );
    if (alert != BoundsAlert.none) unawaited(_alert(alert));
  }

  /// What the player feels and reads (MF-33): a long triple vibration and the
  /// banner on leaving (again every minute while out), a short one on coming
  /// back; the sharing notification says it too, for a phone in a pocket. No
  /// sound: a tone could give a player's place away.
  Future<void> _alert(BoundsAlert alert) async {
    final services = context.services;
    final s = context.s;
    setState(() {});
    if (alert == BoundsAlert.back) {
      await services.device.vibrate(const [0, 200]);
      await services.foreground.update(
        title: s.t('player.sharing_title'),
        text: s.t('player.sharing_text'),
      );
      return;
    }
    await services.device.vibrate(const [0, 600, 300, 600, 300, 600]);
    await services.foreground.update(
      title: s.t('player.out_title'),
      text: s.t('player.out_text'),
    );
  }

  /// Ends a warning without a buzz (the game paused or ended, the boundary
  /// went away, sharing stopped).
  Future<void> _clearWarning() async {
    final services = context.services;
    final s = context.s;
    _watch.reset();
    if (mounted) setState(() {});
    if (_reporter?.running ?? false) {
      await services.foreground.update(
        title: s.t('player.sharing_title'),
        text: s.t('player.sharing_text'),
      );
    }
  }

  /// The app's services, kept for dispose (no ancestor lookups there).
  late final AppServices _services;

  @override
  void initState() {
    super.initState();
    final services = _services = context.services;
    feed =
        widget.feed ??
        FieldFeed(
          widget.link,
          // A check-in's link trusts the field's pinned CA (tests give a fake).
          connect:
              widget.link.field != null && services.feedConnect == ioConnect
              ? null
              : services.feedConnect,
          onAssignment: widget.onAssignment,
        );
    if (widget.feed == null) unawaited(feed.start());
    unawaited(_loadBranding());
    feed.addListener(_onFeed);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _onFeed();
    });
    _clock = Timer.periodic(const Duration(milliseconds: 500), (_) {
      if (mounted && feed.gameState == 'running') setState(() {});
    });
  }

  PositionReporter? _reporter;
  String? _shareError;

  Future<void> _share(bool on) async {
    final services = context.services;
    final s = context.s;
    final app = AppScope.read(context);
    final location = services.location;
    final field = widget.link.field;
    if (!on) {
      _reporter?.stop();
      _watch.reset();
      await services.foreground.stop();
      await app.update((x) => x.sharePosition = false);
      if (mounted) setState(() {});
      return;
    }
    if (location == null || field == null || !await location.available()) {
      setState(() => _shareError = s.t('player.no_location'));
      return;
    }
    if (!await services.device.requestPermission('ACCESS_FINE_LOCATION') ||
        !await location.granted()) {
      if (mounted) setState(() => _shareError = s.t('player.location_denied'));
      return;
    }
    final http = _http ??= services.fieldHttp(field);
    final client = CheckinClient(http);
    final r = _reporter ??= PositionReporter(
      location: location,
      send: (reports) => client.reportPositions(feed.link.token, reports),
      onFix: _onFix,
    );
    r.start();
    _featuresSeen = feed.mapFeatures;
    unawaited(_loadBounds(features: _featuresSeen));
    await services.foreground.start(
      title: s.t('player.sharing_title'),
      text: s.t('player.sharing_text'),
      location: true,
    );
    await app.update((x) => x.sharePosition = true);
    if (mounted) setState(() => _shareError = null);
  }

  @override
  void dispose() {
    _clock?.cancel();
    feed.removeListener(_onFeed);
    if (_reporter?.running ?? false) {
      unawaited(_services.foreground.stop());
    }
    _reporter?.dispose();
    if (widget.feed == null) feed.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return BrandedTheme(
      branding: _brand,
      child: Scaffold(
        appBar: AppBar(
          title: BrandTitle(branding: _brand, fallback: s.t('role.player')),
        ),
        body: BrandBackdrop(
          branding: _brand,
          child: ListenableBuilder(
            listenable: Listenable.merge([feed, ?_reporter]),
            builder: (context, _) => Column(
              children: [
                if (_watch.out && (_reporter?.running ?? false))
                  const OutOfBoundsBanner(),
                Expanded(
                  child: PlayerView(
                    feed: feed,
                    teams: _teams,
                    sharing: widget.link.field == null
                        ? null
                        : _SharePosition(
                            running: _reporter?.running ?? false,
                            sent: _reporter?.sent ?? 0,
                            stopped: _reporter?.stopReason,
                            error: _shareError,
                            onChanged: _share,
                            squads: ((feed.game?['squads'] as int?) ?? 0) > 0,
                            bounds: _warns,
                          ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// What a player sees of the game.
class PlayerView extends StatelessWidget {
  const PlayerView({
    required this.feed,
    this.sharing,
    this.teams = TeamBranding.none,
    super.key,
  });
  final FieldFeed feed;

  /// The game's team display names and crests (decision BR14).
  final TeamBranding teams;

  /// The position-sharing switch (a check-in's link only).
  final Widget? sharing;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final app = context.app;
    final mine = app.settings.myTeam;
    final g = feed.game;
    final teamNames = feed.teams;
    final left = feed.remainingMs;
    final t = feed.gameTimeMs;
    final messages = [
      for (final e in feed.events)
        if (e.type == 'gm.message' && e.data['text'] is String) e,
    ];
    final objectiveNames = {
      for (final o in feed.objectives) o.id: o.name(s.code),
    };
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
          if (feed.gameState == 'ended') _Result(feed: feed, teams: teams),
          if (feed.me != null)
            Text(
              s.t('player.me', {
                'role': s.t('checkin.role.${feed.me!['role']}'),
                'team': feed.me!['team'] == null
                    ? s.t('player.no_team')
                    : _meTeam(
                        s,
                        teams,
                        '${feed.me!['team']}',
                        feed.me!['squad'],
                      ),
              }),
              key: const Key('player-me'),
            ),
          if (sharing != null && feed.gameState == 'running') sharing!,
          if (feed.positions.length > 1)
            Text(
              s.t('player.positions', {'n': feed.positions.length}),
              key: const Key('player-positions'),
            ),
          for (final m in messages.take(3))
            Notice(
              s.t('player.message', {'text': m.data['text']}),
              kind: NoticeKind.warning,
            ),
          SectionTitle(s.t('player.score')),
          for (final (team, points) in feed.ranking)
            _TeamRow(
              team: team,
              teams: teams,
              points: points,
              mine: team == mine,
              out: feed.eliminated.contains(team),
              lives: feed.lives[team],
              onTap: () => app.update((x) => x.myTeam = team),
            ),
          if (teamNames.isNotEmpty && mine == null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                s.t('player.pick_team'),
                style: TextStyle(color: Theme.of(context).hintColor),
              ),
            ),
          if (feed.objectives.isNotEmpty)
            _ScenarioObjectives(feed: feed, teams: teams),
          if (feed.nodes.isNotEmpty) ...[
            SectionTitle(s.t('player.objectives')),
            for (final n in feed.nodes.values)
              ListTile(
                dense: true,
                leading: teams.crest('${n['owner']}') == null
                    ? TeamDot(n['owner'] as String?)
                    : TeamCrest(
                        team: '${n['owner']}',
                        crest: teams.crest('${n['owner']}'),
                        size: 24,
                      ),
                title: Text(
                  '${n['name'] ?? s.t('player.node', {'n': n['node_id']})}',
                ),
                subtitle: Text(
                  n['owner'] is String
                      ? s.t('player.held_by', {
                          'team': teamLabel(s, teams, '${n['owner']}'),
                        })
                      : s.t('player.held_by_none'),
                ),
              ),
          ],
          if (feed.lives.isNotEmpty) ...[
            SectionTitle(s.t('player.lives')),
            for (final e in feed.lives.entries)
              ListTile(
                dense: true,
                title: Text(teamLabel(s, teams, e.key)),
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
              title: Text(eventText(s, e, teams, objectiveNames)),
              trailing: Text(clockText(e.tMs)),
            ),
        ],
      ],
    );
  }
}

/// The scenario's objectives this player may know, and where each stands.
class _ScenarioObjectives extends StatelessWidget {
  const _ScenarioObjectives({required this.feed, required this.teams});

  final FieldFeed feed;
  final TeamBranding teams;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final scenario = feed.scenario ?? const {};
    final title = _scenarioName(scenario, s.code);
    return Column(
      key: const Key('player-scenario'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SectionTitle(s.t('player.scenario')),
        if (title != null)
          Text(title, style: Theme.of(context).textTheme.titleMedium),
        for (final o in feed.objectives)
          ListTile(
            key: Key('player-objective-${o.id}'),
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: Icon(switch (o.state) {
              ObjectiveState.waiting => Icons.hourglass_empty,
              ObjectiveState.active => Icons.flag_outlined,
              ObjectiveState.done => Icons.check_circle,
              ObjectiveState.failed => Icons.cancel_outlined,
            }, color: _stateColor(context, o)),
            title: Text(o.name(s.code)),
            subtitle: Text(
              [
                _stateText(s, o),
                if (o.assigneeTeam != null) _assignee(s, o),
              ].join(' · '),
            ),
            trailing: o.points == null
                ? null
                : Text(
                    s.t('player.objective_points', {'n': o.points}),
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
          ),
      ],
    );
  }

  Color? _stateColor(BuildContext context, ScenarioObjective o) =>
      switch (o.state) {
        ObjectiveState.done =>
          o.team == null ? null : AtalaiaColors.team(o.team!),
        ObjectiveState.failed => Theme.of(context).colorScheme.error,
        _ => null,
      };

  String _stateText(Strings s, ScenarioObjective o) => switch (o.state) {
    ObjectiveState.waiting => s.t('player.objective_waiting'),
    ObjectiveState.active => s.t('player.objective_active'),
    ObjectiveState.done =>
      o.team == null
          ? s.t('player.objective_done_no_team')
          : s.t('player.objective_done', {
              'team': teamLabel(s, teams, o.team!),
            }),
    ObjectiveState.failed => s.tOr(
      'player.objective_failed_${o.reason}',
      s.t('player.objective_failed'),
    ),
  };

  String _assignee(Strings s, ScenarioObjective o) {
    final team = teamLabel(s, teams, o.assigneeTeam!);
    final squad = o.assigneeSquad;
    return squad == null
        ? s.t('player.objective_for_team', {'team': team})
        : s.t('player.objective_for_squad', {'team': team, 'squad': squad});
  }
}

String? _scenarioName(Map<String, Object?> scenario, String lang) {
  final i18n = scenario['i18n'];
  if (i18n is Map && i18n[lang] is Map) {
    final v = (i18n[lang] as Map)['name'];
    if (v is String && v.isNotEmpty) return v;
  }
  final v = scenario['name'];
  return v is String && v.isNotEmpty ? v : null;
}

class _SharePosition extends StatelessWidget {
  const _SharePosition({
    required this.running,
    required this.sent,
    required this.stopped,
    required this.error,
    required this.onChanged,
    this.squads = false,
    this.bounds = false,
  });

  final bool running;
  final int sent;
  final String? stopped;
  final String? error;
  final ValueChanged<bool> onChanged;

  /// Whether the game has squads (the hint names them only then).
  final bool squads;

  /// Whether the phone watches the field's boundary (MF-31).
  final bool bounds;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SwitchListTile(
          key: const Key('player-share-position'),
          value: running,
          onChanged: onChanged,
          title: Text(s.t('player.share')),
          subtitle: Text(
            running
                ? s.t('player.share_on', {'n': sent})
                : s.t(
                    squads ? 'player.share_hint_squads' : 'player.share_hint',
                  ),
          ),
        ),
        if (running && bounds)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Text(
              s.t('player.bounds_watch'),
              key: const Key('player-bounds-watch'),
              style: TextStyle(color: Theme.of(context).hintColor),
            ),
          ),
        if (error != null) Notice(error!, kind: NoticeKind.warning),
        if (!running && stopped != null)
          Notice(s.t('player.share_stopped'), kind: NoticeKind.info),
      ],
    );
  }
}

/// The out-of-bounds warning (decision MF-33): above the game, in the error
/// colour, announced by screen readers when it appears.
class OutOfBoundsBanner extends StatelessWidget {
  const OutOfBoundsBanner({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final scheme = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    return Semantics(
      liveRegion: true,
      container: true,
      child: Material(
        key: const Key('player-out-of-bounds'),
        color: scheme.error,
        child: SafeArea(
          bottom: false,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            child: Row(
              children: [
                Icon(Icons.wrong_location, color: scheme.onError, size: 36),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        s.t('player.out_title'),
                        style: text.titleLarge?.copyWith(
                          color: scheme.onError,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      Text(
                        s.t('player.out_text'),
                        style: text.bodyMedium?.copyWith(color: scheme.onError),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// The player's team (and squad) as the game names it.
String _meTeam(Strings s, TeamBranding teams, String team, Object? squad) {
  final n = squad is int ? squad : 0;
  final name = teamLabel(s, teams, team);
  return n > 0 ? s.t('checkin.team_squad', {'team': name, 'squad': n}) : name;
}

class _Result extends StatelessWidget {
  const _Result({required this.feed, required this.teams});
  final FieldFeed feed;
  final TeamBranding teams;

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
      text = s.t('player.winner', {'team': teamLabel(s, teams, r.first.$1)});
    }
    return Notice(text, kind: NoticeKind.ok, key: const Key('player-result'));
  }
}

class _TeamRow extends StatelessWidget {
  const _TeamRow({
    required this.team,
    required this.teams,
    required this.points,
    required this.mine,
    required this.out,
    required this.lives,
    required this.onTap,
  });

  final String team;
  final TeamBranding teams;
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
        leading: teams.crest(team) == null
            ? TeamDot(team, size: 28)
            : TeamCrest(team: team, crest: teams.crest(team), size: 36),
        title: Text(
          teamLabel(s, teams, team).toUpperCase(),
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
String eventText(
  Strings s,
  FeedEvent e, [
  TeamBranding? teams,
  Map<String, String> objectives = const {},
]) {
  String name(String t) => teamLabel(s, teams, t);
  final team = e.team == null ? '' : name(e.team!);
  final d = e.data;
  String? str(String k) => d[k] is String ? d[k]! as String : null;
  // A scenario objective this player knows is named (plan phase 8): its name
  // from the game's scenario, in the app's language.
  final objective = objectives[str('objective')];
  final type = objective != null && e.type.startsWith('scenario.objective.')
      ? '${e.type}.named'
      : e.type;
  // An event that can come without a team has a text of its own for that
  // (`event.<type>.no_team`, such as a Hacking Terminal solved by nobody known).
  final key = team.isEmpty && s.tOr('event.$type.no_team', '').isNotEmpty
      ? 'event.$type.no_team'
      : 'event.$type';
  final args = <String, Object?>{
    'team': team,
    'zone': str('zone') ?? s.t('player.node', {'n': e.node}),
    'previous': name(str('previous_team') ?? ''),
    'player': str('player') ?? '',
    'owner': str('owner') ?? '',
    'lives': d['lives_left'] ?? '',
    'amount': d['amount'] ?? '',
    'winner': name(str('winner') ?? ''),
    'text': str('text') ?? '',
    'fuse': d['fuse_s'] ?? '',
    'reason': str('reason') ?? '',
    'remaining': d['remaining'] ?? '',
    'objective': objective ?? '',
  };
  return s.tOr(key, e.type, args);
}
