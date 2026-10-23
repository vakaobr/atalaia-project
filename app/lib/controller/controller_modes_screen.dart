// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The phone controller's `[modes]` settings (slice S7b of PE24, decision
/// PE24-82): the mode keys it trusts for signed mode packages, the mode keys
/// built into the boxes' firmware (it offers the boxes only packages they
/// take), revoked key ids and the registry's index, as a Pi's controller.toml
/// `[modes]` section. Kept in the app's settings and given to the controller
/// when it starts (controller_host.dart's [ControllerBoot.modes]).
library;

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../ui/widgets.dart';
import 'controller_signed_modes.dart';
import 'mode_package.dart';

/// Why [config]'s fields cannot be saved: (message key, line), or null.
(String, int)? modesConfigProblem(ModesConfig config) {
  for (final (list, what) in [
    (config.keys, 'ctl_modes.bad_key'),
    (config.boxKeys, 'ctl_modes.bad_key'),
  ]) {
    for (var i = 0; i < list.length; i++) {
      if (publicKeyBytes(list[i]) == null) return (what, i + 1);
    }
  }
  for (var i = 0; i < config.revoked.length; i++) {
    if (!modeKeyIdPattern.hasMatch(config.revoked[i])) {
      return ('ctl_modes.bad_id', i + 1);
    }
  }
  final index = config.index;
  if (index.isNotEmpty &&
      (index.startsWith('http://') ||
          index.startsWith('file:') ||
          index.startsWith('ftp:') ||
          index.contains('\n'))) {
    return ('ctl_modes.bad_index', 0);
  }
  return null;
}

List<String> _lines(String text) => [
  for (final l in text.split('\n'))
    if (l.trim().isNotEmpty) l.trim(),
];

class ControllerModesScreen extends StatefulWidget {
  const ControllerModesScreen({super.key});

  @override
  State<ControllerModesScreen> createState() => _ControllerModesScreenState();
}

class _ControllerModesScreenState extends State<ControllerModesScreen> {
  late final TextEditingController _keys;
  late final TextEditingController _boxKeys;
  late final TextEditingController _revoked;
  late final TextEditingController _index;
  var _loaded = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_loaded) return;
    _loaded = true;
    final c = ModesConfig.fromJson(context.app.settings.controllerModes);
    _keys = TextEditingController(text: c.keys.join('\n'));
    _boxKeys = TextEditingController(text: c.boxKeys.join('\n'));
    _revoked = TextEditingController(text: c.revoked.join('\n'));
    _index = TextEditingController(text: c.index);
  }

  @override
  void dispose() {
    _keys.dispose();
    _boxKeys.dispose();
    _revoked.dispose();
    _index.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final s = context.s;
    final app = AppScope.read(context);
    final old = ModesConfig.fromJson(app.settings.controllerModes);
    final config = ModesConfig(
      keys: _lines(_keys.text),
      boxKeys: _lines(_boxKeys.text),
      revoked: [for (final l in _lines(_revoked.text)) l.toLowerCase()],
      index: _index.text.trim(),
      fetchTimeoutS: old.fetchTimeoutS,
    );
    final problem = modesConfigProblem(config);
    if (problem != null) {
      showMessage(context, s.t(problem.$1, {'line': '${problem.$2}'}));
      return;
    }
    await app.update((x) => x.controllerModes = config.toJson());
    if (mounted) showMessage(context, s.t('ctl_modes.saved'));
  }

  Widget _field(String label, TextEditingController c, String key) => Padding(
    padding: const EdgeInsets.only(bottom: 16),
    child: TextField(
      key: Key(key),
      controller: c,
      minLines: 1,
      maxLines: 4,
      style: const TextStyle(fontFamily: 'monospace'),
      decoration: InputDecoration(
        labelText: label,
        border: const OutlineInputBorder(),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('ctl_modes.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(s.t('ctl_modes.intro')),
          const SizedBox(height: 16),
          _field(s.t('ctl_modes.keys'), _keys, 'mode-keys'),
          _field(s.t('ctl_modes.box_keys'), _boxKeys, 'box-keys'),
          _field(s.t('ctl_modes.revoked'), _revoked, 'revoked-keys'),
          _field(s.t('ctl_modes.index'), _index, 'mode-index'),
          FilledButton(
            key: const Key('modes-save'),
            onPressed: _save,
            child: Text(s.t('common.save')),
          ),
        ],
      ),
    );
  }
}
