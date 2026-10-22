// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Settings: language, theme, the field join key a prop checks join
/// payloads with, the admin PIN that guards a prop, kiosk mode, the
/// battery guide and what this app carries (versions, licence).
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../platform/platform_check.dart';
import '../prop/battery_guide.dart';
import '../storage/app_store.dart';
import 'widgets.dart';

/// The app's version (pubspec.yaml).
const appVersion = '0.2.0';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final app = context.app;
    final st = app.settings;
    final core = app.services.runner.coreVersion;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('settings.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SectionTitle(s.t('settings.language')),
          // One chip a language, wrapping onto a second line on a narrow
          // phone: four languages no longer fit a segmented button.
          Wrap(
            key: const Key('language'),
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final l in AppLanguage.values)
                ChoiceChip(
                  key: Key('language-${l.code}'),
                  label: Text(s.t('settings.lang_${l.code}')),
                  selected: st.language == l,
                  onSelected: (_) => app.update((x) => x.language = l),
                ),
            ],
          ),
          SectionTitle(s.t('settings.theme')),
          SegmentedButton<ThemeMode>(
            segments: [
              ButtonSegment(
                value: ThemeMode.system,
                label: Text(s.t('settings.theme_system')),
              ),
              ButtonSegment(
                value: ThemeMode.dark,
                label: Text(s.t('settings.theme_dark')),
              ),
              ButtonSegment(
                value: ThemeMode.light,
                label: Text(s.t('settings.theme_light')),
              ),
            ],
            selected: {st.theme},
            onSelectionChanged: (v) => app.update((x) => x.theme = v.single),
          ),
          SectionTitle(s.t('settings.field')),
          ListTile(
            key: const Key('join-key'),
            leading: const Icon(Icons.key),
            title: Text(s.t('settings.join_key')),
            subtitle: Text(
              st.joinKey == null
                  ? s.t('settings.join_key_none')
                  : s.t('settings.join_key_set', {
                      'end': st.joinKeyHex!.substring(56),
                    }),
            ),
            onTap: () => _editJoinKey(context),
          ),
          ListTile(
            key: const Key('admin-pin'),
            leading: const Icon(Icons.pin),
            title: Text(s.t('settings.pin')),
            subtitle: Text(
              st.hasPin ? s.t('settings.pin_set') : s.t('settings.pin_none'),
            ),
            onTap: () => _editPin(context),
          ),
          if (propRoleAvailable) ...[
            SwitchListTile(
              key: const Key('kiosk'),
              secondary: const Icon(Icons.lock),
              title: Text(s.t('settings.kiosk')),
              subtitle: Text(s.t('settings.kiosk_hint')),
              value: st.kiosk,
              onChanged: (v) => app.update((x) => x.kiosk = v),
            ),
            ListTile(
              leading: const Icon(Icons.battery_alert),
              title: Text(s.t('battery.title')),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute<void>(
                  builder: (_) => const BatteryGuideScreen(),
                ),
              ),
            ),
          ],
          SectionTitle(s.t('settings.about')),
          ListTile(
            title: Text(s.t('settings.version', {'version': appVersion})),
            subtitle: Text(
              core == null
                  ? s.t('settings.no_core')
                  : s.t('settings.core', {'version': core}),
            ),
          ),
          ListTile(
            title: Text(s.t('settings.licence')),
            subtitle: Text(s.t('settings.licence_text')),
          ),
        ],
      ),
    );
  }

  Future<void> _editJoinKey(BuildContext context) async {
    final s = context.s;
    final app = AppScope.read(context);
    final result = await promptText(
      context,
      title: s.t('settings.join_key'),
      body: s.t('settings.join_key_hint'),
      fieldKey: const Key('join-key-field'),
      monospace: true,
      maxLines: 2,
      formatters: [
        FilteringTextInputFormatter.allow(RegExp('[0-9a-fA-F]')),
        LengthLimitingTextInputFormatter(64),
      ],
      actions: [
        (s.t('settings.join_key_clear'), (_) => '', false),
        (s.t('common.cancel'), (_) => null, false),
        (s.t('common.save'), (t) => t, true),
      ],
    );
    if (result == null || !context.mounted) return;
    if (result.isEmpty) {
      await app.update((x) => x.joinKeyHex = null);
    } else if (isJoinKeyHex(result)) {
      await app.update((x) => x.joinKeyHex = result.toLowerCase());
    } else if (context.mounted) {
      showMessage(context, s.t('settings.join_key_bad'));
    }
  }

  Future<void> _editPin(BuildContext context) async {
    final s = context.s;
    final app = AppScope.read(context);
    if (!await askPin(context) || !context.mounted) return;
    final result = await promptText(
      context,
      title: s.t('settings.pin'),
      fieldKey: const Key('new-pin-field'),
      helper: s.t('settings.pin_hint'),
      obscure: true,
      maxLength: 8,
      keyboard: TextInputType.number,
      formatters: [FilteringTextInputFormatter.digitsOnly],
      actions: [
        (s.t('settings.pin_remove'), (_) => '', false),
        (s.t('common.save'), (t) => t, true),
      ],
    );
    if (result == null) return;
    if (result.isEmpty) {
      await app.update((x) => x.clearPin());
    } else if (result.length >= 4) {
      await app.update((x) => x.setPin(result));
    } else if (context.mounted) {
      showMessage(context, s.t('settings.pin_hint'));
    }
  }
}
