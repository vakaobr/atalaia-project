// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The prop role's start: a new game on this phone, or one joined with a
/// join payload; an I/O pod to link; what the phone can do; and, once, the
/// battery-optimisation exemption (ADR-P3-5).
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../platform/services.dart';
import '../pod/pod_client.dart';
import '../protocol/join_payload.dart';
import '../ui/widgets.dart';
import 'battery_guide.dart';
import 'capability_mapper.dart';
import 'join_screen.dart';
import 'pod_screen.dart';
import 'prop_setup.dart';

class PropHomeScreen extends StatefulWidget {
  const PropHomeScreen({super.key});

  @override
  State<PropHomeScreen> createState() => _PropHomeScreenState();
}

class _PropHomeScreenState extends State<PropHomeScreen> {
  DeviceFeatures? _features;
  bool? _exempt;
  PodClient? _pod;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final app = AppScope.read(context);
    final d = app.services.device;
    final features = await d.features();
    var exempt = await d.ignoringBatteryOptimizations();
    if (!exempt && !app.settings.batteryAsked) {
      // Asked once, at the prop role's first use; never again (ADR-P3-5).
      await app.update((s) => s.batteryAsked = true);
      await d.requestIgnoreBatteryOptimizations();
      exempt = await d.ignoringBatteryOptimizations();
    }
    if (!mounted) return;
    setState(() {
      _features = features;
      _exempt = exempt;
    });
  }

  Future<void> _newGame({JoinPayload? join}) => Navigator.push(
    context,
    MaterialPageRoute<void>(
      builder: (_) => PropSetupScreen(join: join, pod: _pod),
    ),
  );

  Future<void> _join() async {
    final s = context.s;
    final j = await Navigator.push<JoinPayload>(
      context,
      MaterialPageRoute(builder: (_) => JoinScreen(title: s.t('prop.join'))),
    );
    if (j != null && mounted) await _newGame(join: j);
  }

  Future<void> _linkPod() async {
    final client = await Navigator.push<PodClient>(
      context,
      MaterialPageRoute(builder: (_) => const PodScreen()),
    );
    if (client != null && mounted) {
      await _pod?.close();
      setState(() => _pod = client);
    }
  }

  @override
  void dispose() {
    unawaited(_pod?.close());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final features = _features;
    final caps = features == null
        ? null
        : CapabilityMap.of(features, pod: _pod?.ident);
    return Scaffold(
      appBar: AppBar(title: Text(s.t('role.prop'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(s.t('prop.intro')),
          const SizedBox(height: 12),
          if (_exempt == false)
            Notice(
              s.t('battery.not_exempt'),
              kind: NoticeKind.warning,
              action: OutlinedButton(
                onPressed: () => Navigator.push(
                  context,
                  MaterialPageRoute<void>(
                    builder: (_) => const BatteryGuideScreen(),
                  ),
                ),
                child: Text(s.t('battery.title')),
              ),
            ),
          const SizedBox(height: 8),
          FilledButton.icon(
            key: const Key('prop-new'),
            icon: const Icon(Icons.play_arrow),
            label: Text(s.t('prop.new_game')),
            onPressed: _newGame,
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            key: const Key('prop-join'),
            icon: const Icon(Icons.qr_code),
            label: Text(s.t('prop.join')),
            onPressed: _join,
          ),
          SectionTitle(s.t('pod.title')),
          if (_pod?.ident case final ident?)
            Notice(
              s.t('pod.linked', {
                'kind': _pod!.transport.kind.toUpperCase(),
                'fw': ident.fwVersion,
                'n': ident.capabilities.length,
              }),
              kind: NoticeKind.ok,
            )
          else
            Text(s.t('pod.none')),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            icon: const Icon(Icons.usb),
            label: Text(s.t('pod.link')),
            onPressed: _linkPod,
          ),
          SectionTitle(s.t('prop.capabilities')),
          if (caps != null)
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final t in caps.types.toList()..sort())
                  Chip(label: Text(s.tOr('cap.$t', t))),
              ],
            ),
          if (features != null && features.nfc && !features.nfcEnabled)
            Notice(s.t('nfc.off'), kind: NoticeKind.warning),
        ],
      ),
    );
  }
}
