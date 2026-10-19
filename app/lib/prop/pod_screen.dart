// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Linking an I/O pod (protocol/capability-proxy.md): over USB-OTG first,
/// else Bluetooth LE. The screen finds pods, opens the chosen link, waits
/// for the pod's IDENT and hands the linked [PodClient] back. Over
/// Bluetooth the pod asks to pair first (an encrypted link, decision PF4),
/// so the wait is longer: Android shows its pairing question. Not run with
/// a real pod yet (plan phase G).
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../pod/pod_client.dart';
import '../pod/pod_transports.dart';
import '../ui/widgets.dart';

class PodScreen extends StatefulWidget {
  const PodScreen({super.key});

  @override
  State<PodScreen> createState() => _PodScreenState();
}

class _PodScreenState extends State<PodScreen> {
  List<PodDevice>? _found;
  bool _busy = false;
  String? _error;

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
    setState(() => _busy = true);
    if (!await transport.open(d)) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = 'pod.open_failed';
        });
      }
      return;
    }
    final client = PodClient(transport);
    final identified = Completer<void>();
    final sub = client.events.listen((e) {
      if (e is PodIdentified && !identified.isCompleted) identified.complete();
    });
    await client.start();
    try {
      await identified.future.timeout(
        d.kind == 'usb'
            ? const Duration(seconds: 3)
            : const Duration(seconds: 30),
      );
    } on TimeoutException {
      await sub.cancel();
      await client.close();
      if (mounted) {
        setState(() {
          _busy = false;
          _error = 'pod.no_ident';
        });
      }
      return;
    }
    await sub.cancel();
    if (mounted) Navigator.pop(context, client);
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
