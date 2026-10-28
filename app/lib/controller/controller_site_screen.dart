// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The phone controller's slice S7 settings (decisions PE24-118 onward):
/// failover (manual or auto, ADR-P2-8), the site server (its address, the
/// field's API key, branding and the scenario library from the site, the
/// remote GM) and the CoT feed for ATAK (multicast on the field's Wi-Fi,
/// staff devices, the remote relay), as a Pi's controller.toml has them in
/// `[controller] failover_mode`, `[sync]` and `[atak]`. Kept in the app's
/// settings and given to the controller when it starts
/// (controller_host.dart's [ControllerBoot]).
///
/// The API key is shown once, as it is typed: afterwards only its
/// fingerprint (the first 8 hex digits of its SHA-256, as the site server
/// lists keys).
library;

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../ui/widgets.dart';
import 'controller_atak.dart';
import 'controller_sync.dart';

class ControllerSiteScreen extends StatefulWidget {
  const ControllerSiteScreen({super.key});

  @override
  State<ControllerSiteScreen> createState() => _ControllerSiteScreenState();
}

class _ControllerSiteScreenState extends State<ControllerSiteScreen> {
  final _url = TextEditingController();
  final _key = TextEditingController();
  final _multicast = TextEditingController();
  final _staff = TextEditingController();
  var _failover = 'manual';
  var _syncOn = false, _brandingSite = false, _library = true;
  var _remoteGm = false;
  var _atakOn = false, _players = false, _remote = false;
  var _remotePlayers = false;
  String? _savedKey;
  var _loaded = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_loaded) return;
    _loaded = true;
    final st = context.app.settings;
    _failover = st.failoverMode;
    final sync = SyncConfig.fromJson(st.controllerSync);
    if (sync != null) {
      _syncOn = true;
      _url.text = sync.url;
      _savedKey = sync.apiKey;
      _brandingSite = sync.branding == 'site';
      _library = sync.library;
      _remoteGm = sync.remoteGm;
    }
    final atak = st.controllerAtak;
    AtakConfig a;
    try {
      a = atak == null ? const AtakConfig() : AtakConfig.fromSection(atak);
    } on AtakConfigError {
      a = const AtakConfig();
    }
    _atakOn = a.enabled;
    _multicast.text = a.multicast;
    _staff.text = a.staffEndpoints.join(', ');
    _players = a.players;
    _remote = a.remote;
    _remotePlayers = a.remotePlayers;
  }

  @override
  void dispose() {
    _url.dispose();
    _key.dispose();
    _multicast.dispose();
    _staff.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final s = context.s;
    final app = AppScope.read(context);
    Map<String, Object?>? sync;
    if (_syncOn) {
      final typed = _key.text.trim();
      final cfg = SyncConfig(
        url: _url.text.trim(),
        apiKey: typed.isEmpty ? (_savedKey ?? '') : typed,
        branding: _brandingSite ? 'site' : 'local',
        library: _library,
        remoteGm: _remoteGm,
      );
      final problem = cfg.problem();
      if (problem != null) {
        showMessage(context, s.t('ctl_site.bad_sync', {'why': problem}));
        return;
      }
      sync = cfg.toJson();
    }
    final atak = <String, Object?>{
      'enabled': _atakOn,
      'multicast': _multicast.text.trim(),
      'staff_endpoints': _staff.text.trim(),
      'players': _players,
      'remote': _atakOn && sync != null && _remote,
      'remote_players': _atakOn && sync != null && _remote && _remotePlayers,
    };
    try {
      AtakConfig.fromSection(atak).checkConfig(syncEnabled: sync != null);
    } on AtakConfigError catch (e) {
      showMessage(context, s.t('ctl_site.bad_atak', {'why': e.message}));
      return;
    }
    await app.update(
      (x) => x
        ..failoverMode = _failover
        ..controllerSync = sync
        ..controllerAtak = _atakOn ? atak : null,
    );
    if (!mounted) return;
    setState(() {
      _savedKey = sync?['api_key'] as String?;
      _key.clear();
    });
    showMessage(context, s.t('ctl_modes.saved'));
  }

  Widget _text(
    String label,
    TextEditingController c,
    String key, {
    bool secret = false,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: TextField(
      key: Key(key),
      controller: c,
      obscureText: secret,
      autocorrect: false,
      enableSuggestions: !secret,
      decoration: InputDecoration(
        labelText: label,
        border: const OutlineInputBorder(),
      ),
    ),
  );

  Widget _switch(
    String key,
    String title,
    bool value,
    ValueChanged<bool> on, {
    String? hint,
  }) => SwitchListTile(
    key: Key(key),
    contentPadding: EdgeInsets.zero,
    title: Text(title),
    subtitle: hint == null ? null : Text(hint),
    value: value,
    onChanged: (v) => setState(() => on(v)),
  );

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final saved = _savedKey;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('ctl_site.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(s.t('ctl_site.intro')),
          const SizedBox(height: 16),
          _switch(
            'failover-auto',
            s.t('ctl_site.failover_auto'),
            _failover == 'auto',
            (v) => _failover = v ? 'auto' : 'manual',
            hint: s.t('ctl_site.failover_hint'),
          ),
          const Divider(height: 32),
          _switch(
            'sync-on',
            s.t('ctl_site.sync'),
            _syncOn,
            (v) => _syncOn = v,
            hint: s.t('ctl_site.sync_hint'),
          ),
          if (_syncOn) ...[
            _text(s.t('ctl_site.url'), _url, 'sync-url'),
            _text(
              saved == null
                  ? s.t('ctl_site.key')
                  : s.t('ctl_site.key_set', {'fp': keyFingerprint(saved)}),
              _key,
              'sync-key',
              secret: true,
            ),
            _switch(
              'sync-branding',
              s.t('ctl_site.branding'),
              _brandingSite,
              (v) => _brandingSite = v,
            ),
            _switch(
              'sync-library',
              s.t('ctl_site.library'),
              _library,
              (v) => _library = v,
            ),
            _switch(
              'sync-remote-gm',
              s.t('ctl_site.remote_gm'),
              _remoteGm,
              (v) => _remoteGm = v,
              hint: s.t('ctl_site.remote_gm_hint'),
            ),
          ],
          const Divider(height: 32),
          _switch(
            'atak-on',
            s.t('ctl_site.atak'),
            _atakOn,
            (v) => _atakOn = v,
            hint: s.t('ctl_site.atak_hint'),
          ),
          if (_atakOn) ...[
            _text(s.t('ctl_site.multicast'), _multicast, 'atak-multicast'),
            _text(s.t('ctl_site.staff'), _staff, 'atak-staff'),
            _switch(
              'atak-players',
              s.t('ctl_site.players'),
              _players,
              (v) => _players = v,
            ),
            if (_syncOn) ...[
              _switch(
                'atak-remote',
                s.t('ctl_site.remote'),
                _remote,
                (v) => _remote = v,
              ),
              if (_remote)
                _switch(
                  'atak-remote-players',
                  s.t('ctl_site.remote_players'),
                  _remotePlayers,
                  (v) => _remotePlayers = v,
                ),
            ],
          ],
          const SizedBox(height: 16),
          FilledButton(
            key: const Key('site-save'),
            onPressed: _save,
            child: Text(s.t('common.save')),
          ),
        ],
      ),
    );
  }
}
