// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Setting up a prop's game, like a Field Box's preset: the mode (and
/// modifiers), the role, the teams, the mode's parameters (with their
/// translated labels from mode.yaml) and the game's length. A joined game
/// brings its mode, role, teams and parameters from the join payload and
/// only the length is left to choose. The phone must have what the role
/// requires (capability_mapper.dart).
library;

import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../modes/mode_catalog.dart';
import '../platform/services.dart';
import '../pod/pod_client.dart';
import '../protocol/join_payload.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'capability_mapper.dart';
import 'prop_game.dart';
import 'prop_session.dart';

class PropSetupScreen extends StatefulWidget {
  const PropSetupScreen({this.join, this.pod, super.key});

  final JoinPayload? join;
  final PodClient? pod;

  @override
  State<PropSetupScreen> createState() => _PropSetupScreenState();
}

class _PropSetupScreenState extends State<PropSetupScreen> {
  late final ModeCatalog catalog = context.services.modes;
  ModeManifest? _main;
  final _modifiers = <ModeManifest>{};
  String? _role;
  List<String> _teams = ['red', 'blue'];
  final _values = <String, Object?>{};
  final _durationCtl = TextEditingController(text: '0');
  DeviceFeatures? _features;
  String? _error;

  JoinPayload? get join => widget.join;

  @override
  void initState() {
    super.initState();
    final j = join;
    if (j != null) {
      try {
        final g = catalog.compose(j.modeId);
        _main = g.main;
        _modifiers.addAll(g.modifiers);
        _role = g.main.role(j.role) == null ? null : j.role;
        if (_role == null) _error = 'setup.unknown_role';
        _teams = [...j.teams];
        _values.addAll(j.params ?? const {});
      } on ModeException {
        _error = 'setup.unknown_mode';
      }
    } else {
      _pick(
        catalog.modes.firstWhere(
          (m) => m.id == 'org.atalaia.domination',
          orElse: () => catalog.modes.first,
        ),
      );
    }
    _loadFeatures();
  }

  Future<void> _loadFeatures() async {
    final f = await context.services.device.features();
    if (mounted) setState(() => _features = f);
  }

  void _pick(ModeManifest m) {
    _main = m;
    _modifiers.clear();
    _role = m.roles.isEmpty ? null : m.roles.first.name;
    _values.clear();
    _fixTeamParams();
  }

  GameMode? get _mode => _main == null
      ? null
      : GameMode(_main!, [
          for (final m in catalog.modifiers)
            if (_modifiers.contains(m)) m,
        ]);

  /// Team parameters follow the teams: a team that is gone is replaced.
  void _fixTeamParams() {
    final mode = _mode;
    if (mode == null) return;
    var i = 0;
    for (final p in mode.params.where((p) => p.type == 'team')) {
      final v = _values[p.name] ?? p.defaultValue;
      if (!_teams.contains(v)) _values[p.name] = _teams[i % _teams.length];
      i++;
    }
  }

  @override
  void dispose() {
    _durationCtl.dispose();
    super.dispose();
  }

  void _prepare() {
    final s = context.s;
    final mode = _mode;
    final role = _role;
    if (mode == null || role == null) return;
    final Map<String, Object?> params;
    try {
      params = mode.resolveParams({
        for (final e in _values.entries)
          if (e.value != null && e.value != '') e.key: e.value,
      }, _teams);
    } on ModeException catch (e) {
      setState(() => _error = e.message);
      return;
    }
    final minutes = int.tryParse(_durationCtl.text) ?? 0;
    final setup = PropSetup(
      mode: mode,
      role: role,
      teams: _teams,
      params: params,
      durationMs: minutes * 60000,
      nodeId: join?.nodeId ?? 1,
      gameSeed: join?.gameSeed ?? Random.secure().nextInt(0x7fffffff) + 1,
      join: join,
    );
    Navigator.pushReplacement(
      context,
      MaterialPageRoute<void>(
        builder: (_) => PropGameScreen(
          setup: setup,
          pod: widget.pod,
          modeName: mode.name(s.code),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final lang = s.code;
    final mode = _mode;
    final locked = join != null;
    final features = _features;
    final role = mode?.main.role(_role ?? '');
    final missing = features == null || role == null
        ? const <String>[]
        : CapabilityMap.of(features, pod: widget.pod?.ident).missingFor(role);
    return Scaffold(
      appBar: AppBar(title: Text(s.t(locked ? 'setup.joined' : 'setup.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (join case final j?)
            Notice(
              s.t('setup.join_info', {
                'game': j.gameId,
                'node': j.nodeId,
                'mhz': s.number(j.channelHz / 1e6, 3),
              }),
              kind: NoticeKind.ok,
            ),
          if (_error != null)
            Notice(
              _error!.startsWith('setup.') ? s.t(_error!) : _error!,
              kind: NoticeKind.error,
              key: const Key('setup-error'),
            ),
          SectionTitle(s.t('setup.mode')),
          if (locked)
            ListTile(
              title: Text(mode?.name(lang) ?? join!.modeId),
              subtitle: Text(mode?.main.description(lang) ?? ''),
            )
          else ...[
            DropdownButtonFormField<ModeManifest>(
              key: const Key('setup-mode'),
              initialValue: _main,
              isExpanded: true,
              items: [
                for (final m in catalog.modes)
                  DropdownMenuItem(value: m, child: Text(m.name(lang))),
              ],
              onChanged: (m) => setState(() {
                if (m != null) _pick(m);
              }),
            ),
            if (_main != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(_main!.description(lang)),
              ),
            if (_main != null && !_main!.isModifier)
              for (final m in catalog.modifiers)
                CheckboxListTile(
                  title: Text(s.t('setup.with', {'mode': m.name(lang)})),
                  value: _modifiers.contains(m),
                  onChanged: (v) => setState(() {
                    if (v ?? false) {
                      _modifiers.add(m);
                    } else {
                      _modifiers.remove(m);
                      for (final p in m.params) {
                        _values.remove(p.name);
                      }
                    }
                  }),
                ),
          ],
          if (_main?.needsController ?? false)
            Notice(s.t('setup.needs_controller'), kind: NoticeKind.warning),
          if (!locked && (_main?.roles.length ?? 0) > 1) ...[
            SectionTitle(s.t('setup.role')),
            DropdownButtonFormField<String>(
              initialValue: _role,
              items: [
                for (final r in _main!.roles)
                  DropdownMenuItem(value: r.name, child: Text(r.name)),
              ],
              onChanged: (r) => setState(() => _role = r),
            ),
          ],
          if (missing.isNotEmpty)
            Notice(
              s.t('setup.missing', {
                'caps': missing.map((c) => s.tOr('cap.$c', c)).join(', '),
              }),
              kind: NoticeKind.error,
              key: const Key('setup-missing'),
            ),
          SectionTitle(s.t('setup.teams')),
          if (locked)
            Wrap(
              spacing: 8,
              children: [
                for (final t in _teams)
                  Chip(avatar: TeamDot(t), label: Text(s.team(t))),
              ],
            )
          else
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final t in teamColourNames)
                  FilterChip(
                    key: Key('team-$t'),
                    avatar: TeamDot(t),
                    label: Text(s.t('team.$t')),
                    selected: _teams.contains(t),
                    onSelected: (on) => setState(() {
                      if (on) {
                        _teams = [..._teams, t];
                      } else if (_teams.length > 1) {
                        _teams = [..._teams]..remove(t);
                      }
                      _fixTeamParams();
                    }),
                  ),
              ],
            ),
          if (mode != null && mode.params.isNotEmpty) ...[
            SectionTitle(s.t('setup.params')),
            for (final p in mode.params) _param(p, lang, locked),
          ],
          SectionTitle(s.t('setup.length')),
          TextField(
            key: const Key('setup-duration'),
            controller: _durationCtl,
            keyboardType: TextInputType.number,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            decoration: InputDecoration(
              labelText: s.t('setup.minutes'),
              helperText: s.t('setup.minutes_hint'),
            ),
          ),
          const SizedBox(height: 24),
          FilledButton.icon(
            key: const Key('setup-go'),
            icon: const Icon(Icons.check),
            label: Text(s.t('setup.prepare')),
            onPressed: mode == null || _role == null || missing.isNotEmpty
                ? null
                : _prepare,
          ),
        ],
      ),
    );
  }

  Widget _param(ModeParam p, String lang, bool locked) {
    final value = _values[p.name] ?? p.defaultValue;
    final label = p.label(lang);
    switch (p.type) {
      case 'bool':
        return SwitchListTile(
          title: Text(label),
          value: value == true,
          onChanged: locked ? null : (v) => setState(() => _values[p.name] = v),
        );
      case 'team':
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: DropdownButtonFormField<String>(
            initialValue: _teams.contains(value) ? value as String : null,
            decoration: InputDecoration(labelText: label),
            items: [
              for (final t in _teams)
                DropdownMenuItem(value: t, child: Text(context.s.team(t))),
            ],
            onChanged: locked
                ? null
                : (v) => setState(() => _values[p.name] = v),
          ),
        );
      default:
        final isInt = p.type == 'int';
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: TextFormField(
            key: Key('param-${p.name}'),
            initialValue: value == null ? '' : '$value',
            enabled: !locked,
            keyboardType: isInt ? TextInputType.number : TextInputType.text,
            inputFormatters: isInt
                ? [FilteringTextInputFormatter.allow(RegExp('[0-9-]'))]
                : null,
            decoration: InputDecoration(
              labelText: label,
              helperText: isInt && (p.min != null || p.max != null)
                  ? '${p.min ?? ''} – ${p.max ?? ''}'
                  : null,
            ),
            onChanged: (t) => _values[p.name] = isInt ? int.tryParse(t) : t,
          ),
        );
    }
  }
}
