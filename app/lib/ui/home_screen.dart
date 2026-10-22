// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The role selector (plan phase D): a game prop (Android only, ADR-P3-10),
/// a player's view of the game, the marshal's tools (chrono check-in,
/// replicas, player tags), the GM console, and the field controller
/// (Android only; slice S6 of PE24: the phone runs the field itself).
library;

import 'package:flutter/material.dart';

import '../controller/controller_screen.dart';
import '../l10n/strings.dart';
import '../marshal/marshal_home.dart';
import '../platform/platform_check.dart';
import '../player/gm_screen.dart';
import '../player/player_screens.dart';
import '../prop/prop_home.dart';
import 'settings_screen.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final roles = <(String, IconData, String, String, WidgetBuilder)>[
      if (propRoleAvailable)
        (
          'role-prop',
          Icons.sensors,
          s.t('role.prop'),
          s.t('role.prop_hint'),
          (_) => const PropHomeScreen(),
        ),
      (
        'role-player',
        Icons.groups,
        s.t('role.player'),
        s.t('role.player_hint'),
        (_) => const PlayerStartScreen(),
      ),
      (
        'role-marshal',
        Icons.speed,
        s.t('role.marshal'),
        s.t('role.marshal_hint'),
        (_) => const MarshalHomeScreen(),
      ),
      (
        'role-gm',
        Icons.admin_panel_settings,
        s.t('role.gm'),
        s.t('role.gm_hint'),
        (_) => const GmScreen(),
      ),
      if (controllerRoleAvailable)
        (
          'role-controller',
          Icons.cell_tower,
          s.t('role.controller'),
          s.t('role.controller_hint'),
          (_) => const ControllerScreen(),
        ),
    ];
    return Scaffold(
      appBar: AppBar(
        title: const Text('Atalaia'),
        actions: [
          IconButton(
            key: const Key('open-settings'),
            tooltip: s.t('settings.title'),
            icon: const Icon(Icons.settings),
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute<void>(builder: (_) => const SettingsScreen()),
            ),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            s.t('home.choose'),
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 12),
          for (final r in roles)
            Card(
              child: ListTile(
                key: Key(r.$1),
                leading: Icon(r.$2, size: 36),
                title: Text(r.$3, style: const TextStyle(fontSize: 20)),
                subtitle: Text(r.$4),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.push(
                  context,
                  MaterialPageRoute<void>(builder: r.$5),
                ),
              ),
            ),
          if (!propRoleAvailable) ...[
            const SizedBox(height: 16),
            Text(
              s.t('home.no_prop'),
              style: TextStyle(color: Theme.of(context).hintColor),
            ),
          ],
        ],
      ),
    );
  }
}
