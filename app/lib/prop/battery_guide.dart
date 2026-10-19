// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// How to keep Android from stopping a prop during a game (ADR-P3-5
/// "Battery optimisation exemption"): the exemption is asked once; if it is
/// refused, this screen says how to grant it by hand on the phone's make.
/// The instructions are in the app, not fetched: a prop may be offline.
library;

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../ui/widgets.dart';

/// The guide for a maker (Build.MANUFACTURER): samsung, xiaomi, huawei,
/// oneplus or generic.
String batteryGuideFor(String manufacturer) {
  final m = manufacturer.toLowerCase();
  if (m.contains('samsung')) return 'samsung';
  if (m.contains('xiaomi') || m.contains('redmi') || m.contains('poco')) {
    return 'xiaomi';
  }
  if (m.contains('huawei') || m.contains('honor')) return 'huawei';
  if (m.contains('oneplus') || m.contains('oppo') || m.contains('realme')) {
    return 'oneplus';
  }
  return 'generic';
}

class BatteryGuideScreen extends StatefulWidget {
  const BatteryGuideScreen({super.key});

  @override
  State<BatteryGuideScreen> createState() => _BatteryGuideScreenState();
}

class _BatteryGuideScreenState extends State<BatteryGuideScreen> {
  bool? _exempt;
  String _guide = 'generic';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final d = context.services.device;
    final exempt = await d.ignoringBatteryOptimizations();
    final maker = await d.manufacturer();
    if (!mounted) return;
    setState(() {
      _exempt = exempt;
      _guide = batteryGuideFor(maker);
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final d = context.services.device;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('battery.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(s.t('battery.intro')),
          const SizedBox(height: 12),
          if (_exempt != null)
            Notice(
              _exempt! ? s.t('battery.exempt') : s.t('battery.not_exempt'),
              kind: _exempt! ? NoticeKind.ok : NoticeKind.warning,
            ),
          SectionTitle(s.t('battery.on_${_guide}_title')),
          Text(
            s.t('battery.on_$_guide'),
            key: const Key('battery-steps'),
            style: const TextStyle(fontSize: 17),
          ),
          const SizedBox(height: 20),
          FilledButton.icon(
            icon: const Icon(Icons.battery_charging_full),
            label: Text(s.t('battery.request')),
            onPressed: () async {
              await d.requestIgnoreBatteryOptimizations();
              await _load();
            },
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            icon: const Icon(Icons.settings),
            label: Text(s.t('battery.open_settings')),
            onPressed: d.openBatterySettings,
          ),
        ],
      ),
    );
  }
}
