// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Linking an I/O pod (protocol/capability-proxy.md): over USB-OTG first,
/// else Bluetooth LE. The screen finds pods, opens the chosen link, waits
/// for the pod's IDENT and hands the linked [PodClient] back. Over
/// Bluetooth the pod asks to pair first (an encrypted link, decision PF4)
/// with a 6-digit passkey on its OLED that Android's pairing dialog asks
/// for (PODPK-1 to PODPK-11, lib/pod/pod_pairing.dart), so the wait is
/// longer; a wrong passkey, a pairing that ran out of time and a pod that
/// needs pairing again each get their message, and the last is paired
/// again once by itself. Not run with a real pod yet (plan phase G).
library;

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../pod/pod_client.dart';
import '../pod/pod_pairing.dart';
import '../pod/pod_reconnect.dart';
import '../pod/pod_transports.dart';
import '../ui/widgets.dart';

/// Opens the pod [lost] was linked to again, over the same kind of link
/// (the Android plugins), for [PodReconnector]; null when it cannot be
/// opened (no plugin, the pod out of reach, USB permission refused) or when
/// the link did not come from a scan. Not started: the reconnector waits
/// for the IDENT as the first link does.
PodReopen podReopenFor(AppServices services) => (lost) async {
  final d = lost.device;
  if (d == null) return null;
  final transport = d.kind == 'usb' ? services.usbPods : services.blePods;
  if (transport == null || !await transport.open(d)) return null;
  return PodClient(transport, device: d);
};

class PodScreen extends StatefulWidget {
  const PodScreen({super.key});

  @override
  State<PodScreen> createState() => _PodScreenState();
}

class _PodScreenState extends State<PodScreen> {
  List<PodDevice>? _found;
  bool _busy = false;
  String? _error;

  /// While a Bluetooth pod pairs: what to tell the person ("pod.pair_hint", "pod.repair").
  String? _pairing;

  Future<void> _find() async {
    final services = context.services;
    setState(() {
      _busy = true;
      _error = null;
    });
    final permissions = services.device;
    // Android 12+ asks for these at run time; older versions grant them.
    await permissions.requestPermission('BLUETOOTH_SCAN');
    await permissions.requestPermission('BLUETOOTH_CONNECT');
    final found = <PodDevice>[
      ...?await services.usbPods?.find(),
      ...?await services.blePods?.find(),
    ];
    if (!mounted) return;
    setState(() {
      _busy = false;
      _found = found;
    });
  }

  Future<void> _open(PodDevice d) async {
    final services = context.services;
    final transport = d.kind == 'usb' ? services.usbPods : services.blePods;
    if (transport == null) return;
    setState(() {
      _busy = true;
      _error = null;
      _pairing = d.kind == 'ble' ? 'pod.pair_hint' : null;
    });
    final outcome = await linkPod(
      d,
      () => linkAndIdentify(transport, d, transport.open),
      bonds: transport,
      onRepair: () {
        if (mounted) setState(() => _pairing = 'pod.repair');
      },
    );
    if (!mounted) {
      if (outcome is PodLinked<PodClient>) await outcome.link.close();
      return;
    }
    switch (outcome) {
      case PodLinked(:final link):
        Navigator.pop(context, link);
      case PodLinkFailed(:final messageKey):
        setState(() {
          _busy = false;
          _pairing = null;
          _error = messageKey;
        });
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final found = _found;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('pod.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(s.t('pod.intro')),
          const SizedBox(height: 12),
          if (_error != null) Notice(s.t(_error!), kind: NoticeKind.error),
          if (_pairing != null) Notice(s.t(_pairing!)),
          FilledButton.icon(
            icon: const Icon(Icons.search),
            label: Text(s.t('pod.find')),
            onPressed: _busy ? null : _find,
          ),
          if (_busy) const LinearProgressIndicator(),
          if (found != null && found.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 16),
              child: Text(s.t('pod.found_none')),
            ),
          for (final d in found ?? const <PodDevice>[])
            ListTile(
              leading: Icon(d.kind == 'usb' ? Icons.usb : Icons.bluetooth),
              title: Text(d.name),
              subtitle: Text(d.id),
              onTap: _busy ? null : () => _open(d),
            ),
        ],
      ),
    );
  }
}
