// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Checking in at the field (ADR-P3-13): scan the field's poster (or paste
/// its text), trust the field's controller (its CA pinned on the first
/// scan), read the privacy notice once per field and version, fill in the
/// short form (a display name, the federation number if the field asks for
/// one, a team preference), check in and get a player token. Then the
/// check-in's page: the status the controller gave, the replicas declared
/// for this game and their chrono state, following the game, leaving.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../marshal/chrono_queue.dart';
import '../player/field_feed.dart';
import '../player/player_screens.dart';
import '../protocol/checkin_poster.dart';
import '../ui/widgets.dart';
import 'checkin_client.dart';
import 'declare_replicas_screen.dart';
import 'field_identity.dart';
import 'field_trust.dart';
import 'my_replicas.dart';

class CheckinScreen extends StatefulWidget {
  const CheckinScreen({this.posterText, super.key});

  /// A poster's text to start from (tests, a deep link).
  final String? posterText;

  @override
  State<CheckinScreen> createState() => _CheckinScreenState();
}

enum _Step { scan, connecting, notice, form, sending }

class _CheckinScreenState extends State<CheckinScreen> {
  final _text = TextEditingController();
  final _name = TextEditingController();
  final _fed = TextEditingController();
  _Step _step = _Step.scan;
  String? _error;
  Map<String, Object?> _errorArgs = const {};
  TrustException? _changed;
  CheckinPoster? _poster;
  PinnedField? _field;
  CheckinClient? _client;
  FieldInfo? _info;
  int? _gameId;
  String? _team;
  final _picked = <String>{};

  @override
  void initState() {
    super.initState();
    final st = AppScope.read(context).settings;
    _name.text = st.displayName ?? '';
    unawaited(context.services.checkins.load());
    if (widget.posterText != null) {
      WidgetsBinding.instance.addPostFrameCallback(
        (_) => _usePoster(widget.posterText!),
      );
    }
  }

  @override
  void dispose() {
    _text.dispose();
    _name.dispose();
    _fed.dispose();
    super.dispose();
  }

  void _fail(String key, [Map<String, Object?> args = const {}]) {
    if (!mounted) return;
    setState(() {
      _error = key;
      _errorArgs = args;
      _step = _Step.scan;
    });
  }

  Future<void> _scan() async {
    final s = context.s;
    final qr = context.services.qr;
    if (!await qr.available) {
      _fail('join.no_camera');
      return;
    }
    final text = await qr.scan(
      hint: s.t('checkin.scan_hint'),
      cancel: s.t('common.cancel'),
    );
    if (text != null && mounted) await _usePoster(text);
  }

  Future<void> _usePoster(String text) async {
    final CheckinPoster poster;
    try {
      poster = parsePoster(text);
    } on PosterException {
      _fail(isPosterText(text) ? 'checkin.bad_poster' : 'checkin.not_poster');
      return;
    }
    setState(() {
      _poster = poster;
      _error = null;
      _changed = null;
      _step = _Step.connecting;
    });
    final services = context.services;
    try {
      final field = await services.trust.pin(poster);
      final client = CheckinClient(services.fieldHttp(field));
      final info = await client.info();
      if (!mounted) return;
      final games = info.games;
      final st = AppScope.read(context).settings;
      setState(() {
        _field = field;
        _client = client;
        _info = info;
        _gameId = games.length == 1 ? games.first['game_id'] as int? : null;
        _step = st.noticeSeen[field.fieldId] == info.noticeVersion
            ? _Step.form
            : _Step.notice;
      });
    } on TrustException catch (e) {
      if (e.reason == TrustFailure.changed) {
        setState(() {
          _changed = e;
          _step = _Step.scan;
        });
        return;
      }
      _fail(
        switch (e.reason) {
          TrustFailure.unreachable =>
            poster.wifiSsid == null
                ? 'checkin.unreachable'
                : 'checkin.join_wifi',
          TrustFailure.mismatch => 'checkin.mismatch',
          _ => 'checkin.not_controller',
        },
        {
          'ssid': poster.wifiSsid ?? '',
          'poster': e.knownShort ?? '',
          'got': e.newShort ?? '',
        },
      );
    } on CheckinException catch (e) {
      _fail(e.offline ? 'checkin.unreachable' : 'checkin.error', {
        'error': e.message,
      });
    }
  }

  Future<void> _forgetField() async {
    final poster = _poster;
    if (poster == null) return;
    await context.services.trust.forget(poster.fieldId);
    if (mounted) await _usePoster(posterToText(encodePoster(poster)));
  }

  Future<void> _acceptNotice() async {
    final app = AppScope.read(context);
    final f = _field!;
    final v = _info!.noticeVersion;
    await app.update((x) => x.noticeSeen = {...x.noticeSeen, f.fieldId: v});
    if (mounted) setState(() => _step = _Step.form);
  }

  Future<void> _submit() async {
    final info = _info!;
    final field = _field!;
    final name = _name.text.trim();
    final fed = _fed.text.trim();
    if (name.isEmpty) {
      setState(() => _error = 'checkin.need_name');
      return;
    }
    if (info.federation == 'required' && fed.isEmpty) {
      setState(() {
        _error = 'checkin.need_federation';
        _errorArgs = {'label': info.federationLabel};
      });
      return;
    }
    final gameId = _gameId;
    if (gameId == null) {
      setState(() => _error = 'checkin.pick_game');
      return;
    }
    setState(() {
      _step = _Step.sending;
      _error = null;
    });
    final services = context.services;
    final app = AppScope.read(context);
    final id = await FieldIdentities(services.store).forField(field.fieldId);
    final game = info.games.firstWhere((g) => g['game_id'] == gameId);
    final pending = FieldCheckin(
      fieldId: field.fieldId,
      gameId: gameId,
      gameName: '${game['name'] ?? ''}',
      playerId: id.playerId,
      token: '',
      exp: 0,
      status: 'pending',
      role: 'player',
    );
    final store = services.checkins;
    final old = store.checkins
        .where((c) => c.fieldId == field.fieldId && c.gameId == gameId)
        .firstOrNull;
    if (old != null) pending.declarations.addAll(old.declarations);
    final decls = store.declarationsFor(pending, _picked.toList());
    try {
      final ticket = await _client!.checkIn(
        gameId: gameId,
        playerId: id.playerId,
        secret: id.secret,
        displayName: name,
        noticeVersion: info.noticeVersion,
        federationNumber: info.federation == 'off' || fed.isEmpty ? null : fed,
        teamPreference: _team,
        replicas: decls.isEmpty ? null : decls,
      );
      pending.update(ticket);
      await store.saveCheckin(pending);
      await app.update((x) {
        x.displayName = name;
        if (x.fieldId == 'field' || x.fieldId.isEmpty) {
          x.fieldId = field.fieldId;
        }
      });
      if (!mounted) return;
      await Navigator.pushReplacement(
        context,
        MaterialPageRoute<void>(
          builder: (_) => CheckinStatusScreen(checkin: pending, field: field),
        ),
      );
    } on CheckinException catch (e) {
      if (!mounted) return;
      setState(() {
        _step = _Step.form;
        _error = e.offline ? 'checkin.unreachable' : 'checkin.error';
        _errorArgs = {'error': e.message};
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('checkin.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_error != null)
            Notice(
              s.t(_error!, _errorArgs),
              kind: NoticeKind.error,
              key: const Key('checkin-error'),
            ),
          ...switch (_step) {
            _Step.scan => _scanStep(s),
            _Step.connecting || _Step.sending => [
              const Center(child: CircularProgressIndicator()),
              const SizedBox(height: 12),
              Center(child: Text(s.t('checkin.connecting'))),
            ],
            _Step.notice => _noticeStep(s),
            _Step.form => _formStep(s),
          },
        ],
      ),
    );
  }

  List<Widget> _scanStep(Strings s) => [
    Text(s.t('checkin.intro')),
    const SizedBox(height: 12),
    if (_changed != null) ...[
      Notice(
        s.t('checkin.changed', {
          'old': _changed!.knownShort ?? '',
          'new': _changed!.newShort ?? '',
        }),
        kind: NoticeKind.error,
        key: const Key('checkin-changed'),
      ),
      OutlinedButton(
        key: const Key('checkin-forget-field'),
        onPressed: _forgetField,
        child: Text(s.t('checkin.forget_field')),
      ),
      const SizedBox(height: 12),
    ],
    FilledButton.icon(
      key: const Key('checkin-scan'),
      icon: const Icon(Icons.qr_code_scanner),
      label: Text(s.t('checkin.scan')),
      onPressed: _scan,
    ),
    SectionTitle(s.t('checkin.by_text')),
    TextField(
      key: const Key('checkin-text'),
      controller: _text,
      minLines: 2,
      maxLines: 4,
      decoration: InputDecoration(hintText: s.t('checkin.text_hint')),
    ),
    const SizedBox(height: 8),
    OutlinedButton(
      key: const Key('checkin-use-text'),
      onPressed: () => _usePoster(_text.text),
      child: Text(s.t('checkin.use_text')),
    ),
  ];

  List<Widget> _noticeStep(Strings s) {
    final info = _info!;
    return [
      Text(
        s.t('checkin.notice_title', {'field': info.fieldName}),
        style: Theme.of(context).textTheme.titleLarge,
      ),
      const SizedBox(height: 8),
      Text(
        info.noticeText(s.code).replaceAll('**', '').replaceAll('*', ''),
        key: const Key('checkin-notice'),
      ),
      const SizedBox(height: 12),
      FilledButton(
        key: const Key('checkin-notice-ok'),
        onPressed: _acceptNotice,
        child: Text(s.t('checkin.notice_ok')),
      ),
    ];
  }

  List<Widget> _formStep(Strings s) {
    final info = _info!;
    final field = _field!;
    final games = info.games;
    final mine = context.services.checkins.replicas;
    final game = games.where((g) => g['game_id'] == _gameId).firstOrNull;
    final teams = ((game?['teams'] as List?) ?? const []).cast<String>();
    return [
      Text(
        field.fieldName,
        key: const Key('checkin-field'),
        style: Theme.of(context).textTheme.headlineSmall,
      ),
      Text(
        s.t('checkin.trusted', {'ca': field.caShort}),
        style: TextStyle(color: Theme.of(context).hintColor),
      ),
      const SizedBox(height: 8),
      if (games.isEmpty)
        Notice(s.t('checkin.no_games'), key: const Key('checkin-no-games')),
      if (games.length > 1) ...[
        SectionTitle(s.t('checkin.game')),
        for (final g in games)
          ListTile(
            key: Key('checkin-game-${g['game_id']}'),
            selected: g['game_id'] == _gameId,
            leading: Icon(
              g['game_id'] == _gameId
                  ? Icons.radio_button_checked
                  : Icons.radio_button_unchecked,
            ),
            onTap: () => setState(() => _gameId = g['game_id'] as int?),
            title: Text('${g['name']}'),
          ),
      ],
      if (game != null) ...[
        if (games.length == 1)
          Text(
            s.t('checkin.for_game', {'game': '${game['name']}'}),
            key: const Key('checkin-game'),
          ),
        const SizedBox(height: 8),
        TextField(
          key: const Key('checkin-name'),
          controller: _name,
          maxLength: 32,
          decoration: InputDecoration(
            labelText: s.t('checkin.name'),
            helperText: s.t('checkin.name_hint'),
          ),
        ),
        if (info.federation != 'off')
          TextField(
            key: const Key('checkin-federation'),
            controller: _fed,
            maxLength: 32,
            decoration: InputDecoration(
              labelText: s.t(
                info.federation == 'required'
                    ? 'checkin.federation_required'
                    : 'checkin.federation_optional',
                {'label': info.federationLabel},
              ),
              helperText: s.t('checkin.federation_hint'),
            ),
          ),
        if (teams.isNotEmpty)
          DropdownButtonFormField<String?>(
            key: const Key('checkin-team'),
            initialValue: _team,
            decoration: InputDecoration(labelText: s.t('checkin.team_pref')),
            items: [
              DropdownMenuItem(
                value: null,
                child: Text(s.t('checkin.any_team')),
              ),
              for (final t in teams)
                DropdownMenuItem(value: t, child: Text(s.team(t))),
            ],
            onChanged: (v) => setState(() => _team = v),
          ),
        if (mine.isNotEmpty) ...[
          SectionTitle(s.t('checkin.bring')),
          for (final r in mine)
            CheckboxListTile(
              key: Key('checkin-bring-${r.id}'),
              value: _picked.contains(r.id),
              onChanged: (v) => setState(
                () => v == true ? _picked.add(r.id) : _picked.remove(r.id),
              ),
              title: Text(replicaLabel(s, r.type, r.makeModel)),
              subtitle: Text(r.replicaClass),
            ),
        ],
        const SizedBox(height: 12),
        FilledButton(
          key: const Key('checkin-submit'),
          onPressed: _submit,
          child: Text(s.t('checkin.submit')),
        ),
      ],
    ];
  }
}

/// "vermelha › squad 2" where the game has squads and the player is in one,
/// else the team alone: squads are sub-groups inside a team (decision PE25).
String teamAndSquad(Strings s, String team, int squad) => squad > 0
    ? s.t('checkin.team_squad', {'team': s.team(team), 'squad': squad})
    : s.team(team);

/// A replica's line: its type in words and its make and model.
String replicaLabel(Strings s, String type, String? makeModel) {
  final t = s.tOr('replica.type_$type', type);
  return makeModel == null || makeModel.isEmpty ? t : '$t · $makeModel';
}

/// A declaration's chrono state as a coloured chip.
class ChronoStateChip extends StatelessWidget {
  const ChronoStateChip(this.state, {this.refusedToday = false, super.key});
  final String state;
  final bool refusedToday;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final scheme = Theme.of(context).colorScheme;
    final color = switch (state) {
      'passed' => Colors.green.shade700,
      'refused' => scheme.error,
      'withdrawn' => Theme.of(context).disabledColor,
      _ => Colors.orange.shade800,
    };
    return Chip(
      label: Text(
        s.t('chrono_state.$state') +
            (refusedToday ? ' · ${s.t('chrono_state.refused_today')}' : ''),
        style: TextStyle(color: color, fontWeight: FontWeight.w600),
      ),
      side: BorderSide(color: color),
    );
  }
}

/// A check-in: the status, the replicas and their chrono state, the game.
class CheckinStatusScreen extends StatefulWidget {
  const CheckinStatusScreen({
    required this.checkin,
    required this.field,
    super.key,
  });

  final FieldCheckin checkin;
  final PinnedField field;

  @override
  State<CheckinStatusScreen> createState() => _CheckinStatusScreenState();
}

class _CheckinStatusScreenState extends State<CheckinStatusScreen> {
  late final CheckinClient _client = CheckinClient(
    context.services.fieldHttp(widget.field),
  );
  Map<String, Object?>? _me;
  String? _error;
  bool _left = false;

  FieldCheckin get c => widget.checkin;

  @override
  void initState() {
    super.initState();
    unawaited(_refresh());
  }

  Future<void> _refresh() async {
    final store = context.services.checkins;
    try {
      var me = await _client.me(c.token);
      if (me['stale_token'] == true || _expiresSoon()) {
        c.update(await _client.refresh(c.token));
        await store.saveCheckin(c);
        me = await _client.me(c.token);
      }
      c.status = '${me['status']}';
      c.role = '${me['role']}';
      c.team = me['team'] as String?;
      c.squad = (me['squad'] as int?) ?? 0;
      await _registerMarshalKey();
      if (mounted) {
        setState(() {
          _me = me;
          _error = null;
        });
      }
    } on CheckinException catch (e) {
      if (!mounted) return;
      setState(
        () => _error = e.offline
            ? context.s.t('checkin.offline')
            : (e.status == 401
                  ? context.s.t('checkin.expired')
                  : context.s.t('checkin.error', {'error': e.message})),
      );
    }
  }

  bool _expiresSoon() =>
      c.exp * 1000 - DateTime.now().millisecondsSinceEpoch < 15 * 60 * 1000;

  /// A marshal's phone registers the key that signs its readings, once the
  /// GM has given the marshal role (ADR-P3-13).
  Future<void> _registerMarshalKey() async {
    if (c.role != 'marshal') return;
    final st = AppScope.read(context).settings;
    final seed = st.marshalSeedHex;
    if (seed == null || st.marshalId.isEmpty || st.marshalName.trim().isEmpty) {
      return;
    }
    final records = await marshalRecordsFor(context);
    final key = records.publicKeyBase64;
    if (key == null) return;
    try {
      await _client.registerMarshalKey(
        c.token,
        marshalId: st.marshalId,
        name: st.marshalName.trim(),
        publicKeyBase64: key,
      );
    } on CheckinException {
      // Shown in the marshal's queue when a reading is refused.
    }
  }

  Future<void> _leave() async {
    final s = context.s;
    final store = context.services.checkins;
    if (!await confirm(
      context,
      title: s.t('checkin.leave'),
      body: s.t('checkin.leave_body'),
      yes: s.t('checkin.leave'),
    )) {
      return;
    }
    try {
      await _client.leave(c.token);
      await store.removeCheckin(c);
      if (mounted) setState(() => _left = true);
    } on CheckinException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<String?> _newToken() async {
    final store = context.services.checkins;
    try {
      c.update(await _client.refresh(c.token));
      await store.saveCheckin(c);
      unawaited(_refresh());
      return c.token;
    } on CheckinException {
      return null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final me = _me;
    final decls = [
      for (final d in (me?['declarations'] as List?) ?? const [])
        if (d is Map && d['state'] != 'withdrawn')
          Declaration.fromJson(d.cast<String, Object?>()),
    ];
    return Scaffold(
      appBar: AppBar(title: Text(s.t('checkin.status_title'))),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(
              widget.field.fieldName,
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            Text(c.gameName, key: const Key('checkin-status-game')),
            const SizedBox(height: 8),
            if (_left)
              Notice(
                s.t('checkin.left'),
                kind: NoticeKind.ok,
                key: const Key('checkin-left'),
              ),
            if (_error != null) Notice(_error!, kind: NoticeKind.warning),
            if (!_left) ...[
              Notice(
                s.t('checkin.status.${c.status}'),
                kind: c.status == 'checked_in'
                    ? NoticeKind.ok
                    : NoticeKind.info,
                key: const Key('checkin-status'),
              ),
              Wrap(
                spacing: 8,
                children: [
                  Chip(
                    key: const Key('checkin-role'),
                    label: Text(s.t('checkin.role.${c.role}')),
                  ),
                  if (c.team != null)
                    Chip(
                      key: const Key('checkin-team'),
                      label: Text(teamAndSquad(s, c.team!, c.squad)),
                    ),
                  Chip(label: Text(c.playerId)),
                ],
              ),
              SectionTitle(s.t('checkin.my_declaration')),
              if (me != null && decls.isEmpty) Text(s.t('checkin.no_replicas')),
              for (final d in decls)
                ListTile(
                  key: Key('checkin-decl-${d.declarationId}'),
                  title: Text(replicaLabel(s, d.type, d.makeModel)),
                  subtitle: Text(d.replicaClass),
                  trailing: ChronoStateChip(
                    d.state,
                    refusedToday: d.refusedToday,
                  ),
                ),
              const SizedBox(height: 8),
              FilledButton.icon(
                key: const Key('checkin-declare'),
                icon: const Icon(Icons.inventory_2),
                label: Text(s.t('checkin.declare')),
                onPressed: () async {
                  await Navigator.push(
                    context,
                    MaterialPageRoute<void>(
                      builder: (_) => DeclareReplicasScreen(
                        checkin: c,
                        client: _client,
                        declared: decls,
                      ),
                    ),
                  );
                  await _refresh();
                },
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                key: const Key('checkin-follow'),
                icon: const Icon(Icons.sports_score),
                label: Text(s.t('checkin.follow')),
                onPressed: () => Navigator.push(
                  context,
                  MaterialPageRoute<void>(
                    builder: (_) => PlayerScreen(
                      link: FieldLink(
                        Uri.parse(widget.field.urls.first),
                        c.token,
                        field: widget.field,
                      ),
                      onAssignment: _newToken,
                    ),
                  ),
                ),
              ),
              if (c.staff) ...[
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  key: const Key('checkin-queue'),
                  icon: const Icon(Icons.speed),
                  label: Text(s.t('queue.title')),
                  onPressed: () => Navigator.push(
                    context,
                    MaterialPageRoute<void>(
                      builder: (_) =>
                          ChronoQueueScreen(checkin: c, field: widget.field),
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 24),
              TextButton.icon(
                key: const Key('checkin-leave'),
                icon: const Icon(Icons.logout),
                label: Text(s.t('checkin.leave')),
                onPressed: _leave,
              ),
            ],
          ],
        ),
      ),
    );
  }
}
