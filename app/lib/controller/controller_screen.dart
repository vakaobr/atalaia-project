// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The field controller role's screen (slice S6 of PE24; Android only,
/// ADR-P3-10): start and stop the phone's controller (controller_shell.dart),
/// open it to the field's Wi-Fi, see the addresses and the field CA's
/// fingerprint the check-in poster carries, link an I/O pod as its radio,
/// the GM and read codes, the GM console in the app's web view, and the
/// field's Wi-Fi (Android's hotspot, or a local-only hotspot with a QR code
/// players scan to join it). Laid out for small screens (320 px wide) and
/// read aloud by TalkBack: every control has a label, codes are hidden
/// until asked.
library;

import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../platform/services.dart';
import '../pod/pod_client.dart';
import '../pod/pod_transports.dart';
import '../security/bytes.dart';
import '../ui/qr_painter.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'controller_boxes_screen.dart';
import 'controller_shell.dart';

class ControllerScreen extends StatefulWidget {
  const ControllerScreen({super.key});

  @override
  State<ControllerScreen> createState() => _ControllerScreenState();
}

class _ControllerScreenState extends State<ControllerScreen> {
  late final ControllerShell _shell = context.services.controller;
  late bool _open = _shell.lastStart?.open ?? true;
  PodTransport? _pod;
  String? _podName;
  List<PodDevice>? _found;
  bool _podBusy = false;
  String? _podError;
  FieldWifiInfo? _wifi;
  LocalHotspot? _local;
  bool _showCodes = false;
  bool? _batteryExempt;

  @override
  void initState() {
    super.initState();
    final last = _shell.lastStart;
    _pod = last?.pod;
    _podName = last?.podName;
    unawaited(_refresh());
  }

  Future<void> _refresh() async {
    final services = context.services;
    final wifi = await services.wifi?.info();
    final exempt = await services.device.ignoringBatteryOptimizations();
    if (!mounted) return;
    setState(() {
      _wifi = wifi;
      _local = wifi?.localHotspot ?? _local;
      _batteryExempt = exempt;
    });
  }

  /// The field join key: the app's own (settings), or a new one kept there
  /// so the settings show it for the boxes (decision PE24-65).
  Future<Uint8List> _joinKey() async {
    final app = AppScope.read(context);
    final have = app.settings.joinKey;
    if (have != null) return Uint8List.fromList(have);
    final r = Random.secure();
    final key = Uint8List.fromList(List.generate(32, (_) => r.nextInt(256)));
    await app.update((s) => s.joinKeyHex = hexEncode(key));
    return key;
  }

  Future<void> _start() async {
    final app = AppScope.read(context);
    final device = context.services.device;
    final strings = context.s;
    final key = await _joinKey();
    await _shell.start(
      ControllerStart(
        joinKey: key,
        open: _open,
        fieldId: app.settings.fieldId,
        limitTemplate: app.settings.limitTemplate,
        pod: _pod,
        podName: _podName,
        firmwareKeys: app.settings.firmwareKeys,
      ),
      strings,
    );
    if (!mounted) return;
    // Asked once, as for a prop (ADR-P3-5: never nag).
    if (_batteryExempt == false && !app.settings.batteryAsked) {
      await app.update((s) => s.batteryAsked = true);
      await device.requestIgnoreBatteryOptimizations();
    }
    await _refresh();
  }

  Future<void> _stop() async {
    await _shell.stop();
    if (mounted) {
      setState(() {
        _pod = null;
        _podName = null;
      });
    }
  }

  /// New release keys: a running controller restarts to take them.
  Future<void> _firmwareKeysChanged(List<String> keys) async {
    final last = _shell.lastStart;
    if (_shell.running && last != null) {
      await _shell.restart(last.withFirmwareKeys(keys));
    }
  }

  Future<void> _setOpen(bool v) async {
    setState(() => _open = v);
    final last = _shell.lastStart;
    if (_shell.running && last != null) {
      await _shell.restart(last.withOpen(v));
    }
  }

  // --- the pod ---------------------------------------------------------------

  Future<void> _findPods() async {
    final services = context.services;
    setState(() {
      _podBusy = true;
      _podError = null;
    });
    await services.device.requestPermission('BLUETOOTH_SCAN');
    await services.device.requestPermission('BLUETOOTH_CONNECT');
    final found = <PodDevice>[
      ...?await services.usbPods?.find(),
      ...?await services.blePods?.find(),
    ];
    if (!mounted) return;
    setState(() {
      _podBusy = false;
      _found = found;
    });
  }

  Future<void> _openPod(PodDevice d) async {
    final services = context.services;
    final transport = d.kind == 'usb' ? services.usbPods : services.blePods;
    if (transport == null) return;
    setState(() => _podBusy = true);
    final ok = await transport.open(d);
    if (!mounted) return;
    setState(() {
      _podBusy = false;
      if (ok) {
        _pod = transport;
        _podName = d.name;
        _found = null;
      } else {
        _podError = 'pod.open_failed';
      }
    });
  }

  Future<void> _forgetPod() async {
    await _pod?.close();
    if (mounted) {
      setState(() {
        _pod = null;
        _podName = null;
      });
    }
  }

  // --- the local hotspot -----------------------------------------------------

  Future<void> _startLocal() async {
    final services = context.services;
    final wifi = services.wifi;
    if (wifi == null) return;
    await services.device.requestPermission('NEARBY_WIFI_DEVICES');
    final h = await wifi.startLocalHotspot();
    if (!mounted) return;
    setState(() => _local = h);
    // A new network gives the phone a new address: the controller sees it
    // within seconds (controller_host.dart).
    await _refresh();
  }

  Future<void> _stopLocal() async {
    await context.services.wifi?.stopLocalHotspot();
    if (!mounted) return;
    setState(() => _local = null);
    await _refresh();
  }

  // --- the screen ------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return Scaffold(
      appBar: AppBar(
        title: Text(s.t('role.controller')),
        actions: [
          IconButton(
            key: const Key('ctl-refresh'),
            tooltip: s.t('ctl.refresh'),
            icon: const Icon(Icons.refresh),
            onPressed: _refresh,
          ),
        ],
      ),
      body: ListenableBuilder(
        listenable: _shell,
        builder: (context, _) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // Start and stop first: on a small screen they must not need a
            // scroll.
            ..._errors(s),
            _statusCard(context, s),
            const SizedBox(height: 8),
            Text(s.t('ctl.intro')),
            const SizedBox(height: 8),
            ..._battery(s),
            SectionTitle(s.t('ctl.network')),
            ..._network(context, s),
            SectionTitle(s.t('ctl.wifi')),
            ..._wifiSection(context, s),
            SectionTitle(s.t('ctl.radio')),
            ..._radio(context, s),
            if (_shell.running) ...[
              SectionTitle(s.t('ctl.codes')),
              ..._codes(context, s),
            ],
            SectionTitle(s.t('ctl.console')),
            ..._console(context, s),
            // Slice S7c: the field card, written by this phone's NFC, and
            // the firmware release keys.
            if (_shell.running && _shell.status?.httpPort != null) ...[
              SectionTitle(s.t('ctl.card')),
              FieldCardTile(
                makeCard: () => requestFieldCard(
                  _shell.status!.httpPort!,
                  _shell.status!.gmToken,
                ),
              ),
            ],
            SectionTitle(s.t('ctl.firmware')),
            FirmwareKeysTile(onChanged: _firmwareKeysChanged),
          ],
        ),
      ),
    );
  }

  List<Widget> _errors(Strings s) {
    final e = _shell.error;
    if (e == null) return const [];
    final detail = _shell.errorDetail;
    return [
      Notice(
        detail == null ? s.t(e) : '${s.t(e)}\n$detail',
        kind: NoticeKind.error,
      ),
    ];
  }

  Widget _statusCard(BuildContext context, Strings s) {
    final phase = _shell.phase;
    final st = _shell.status;
    final game = st?.game;
    final busy =
        phase == ControllerPhase.starting || phase == ControllerPhase.stopping;
    final String subtitle;
    if (!_shell.running || st == null) {
      subtitle = s.t('ctl.stopped_hint');
    } else if (game == null) {
      subtitle = s.t('ctl.no_game');
    } else {
      subtitle = s.t('ctl.game', {
        'name': game['name'],
        'state': s.tOr('ctl.game_${game['state']}', '${game['state']}'),
      });
    }
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Semantics(
              liveRegion: true,
              child: ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(
                  _shell.running ? Icons.cell_tower : Icons.power_settings_new,
                  size: 36,
                  color: _shell.running
                      ? AtalaiaColors.ok
                      : Theme.of(context).hintColor,
                ),
                title: Text(
                  s.t('ctl.phase_${phase.name}'),
                  key: const Key('ctl-phase'),
                  style: const TextStyle(fontSize: 20),
                ),
                subtitle: Text(subtitle),
              ),
            ),
            if (st != null && _shell.running)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(
                  s.t('ctl.clients', {
                    'stream': st.streamClients,
                    'mqtt': st.mqttClients,
                    'props': st.props,
                  }),
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
            if (busy) const LinearProgressIndicator(),
            const SizedBox(height: 8),
            if (_shell.running)
              OutlinedButton.icon(
                key: const Key('ctl-stop'),
                icon: const Icon(Icons.stop),
                label: Text(s.t('ctl.stop')),
                onPressed: busy ? null : _stop,
              )
            else
              FilledButton.icon(
                key: const Key('ctl-start'),
                icon: const Icon(Icons.play_arrow),
                label: Text(s.t('ctl.start')),
                onPressed: busy ? null : _start,
              ),
            if (_shell.running && !_shell.foregroundOn) ...[
              const SizedBox(height: 8),
              Notice(s.t('ctl.no_foreground'), kind: NoticeKind.warning),
            ],
          ],
        ),
      ),
    );
  }

  List<Widget> _battery(Strings s) {
    if (_batteryExempt != false) return const [];
    return [
      Notice(
        s.t('ctl.battery'),
        kind: NoticeKind.warning,
        action: TextButton(
          key: const Key('ctl-battery'),
          onPressed: () async {
            await context.services.device.requestIgnoreBatteryOptimizations();
            await _refresh();
          },
          child: Text(s.t('ctl.battery_ask')),
        ),
      ),
    ];
  }

  List<Widget> _network(BuildContext context, Strings s) {
    final st = _shell.status;
    final busy =
        _shell.phase == ControllerPhase.starting ||
        _shell.phase == ControllerPhase.stopping;
    return [
      SwitchListTile(
        key: const Key('ctl-open'),
        contentPadding: EdgeInsets.zero,
        title: Text(s.t('ctl.open')),
        subtitle: Text(s.t(_open ? 'ctl.open_on' : 'ctl.open_off')),
        value: _open,
        onChanged: busy ? null : _setOpen,
      ),
      if (st != null && _shell.running && st.open) ...[
        if (st.urls.isEmpty)
          Notice(s.t('ctl.no_address'), kind: NoticeKind.warning)
        else ...[
          Text(s.t('ctl.addresses')),
          for (final u in st.urls)
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.link),
              title: SelectableText('$u/console/'),
            ),
        ],
      ],
      if (st != null && _shell.running)
        ListTile(
          key: const Key('ctl-ca'),
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.verified_user),
          title: Text(s.t('ctl.ca')),
          subtitle: Text('${st.caShort}\n${s.t('ctl.ca_hint')}'),
          isThreeLine: true,
        ),
    ];
  }

  List<Widget> _wifiSection(BuildContext context, Strings s) {
    final w = _wifi;
    final services = context.services;
    if (w == null || !w.available) {
      return [Text(s.t('ctl.wifi_unavailable'))];
    }
    final local = _local;
    return [
      ListTile(
        contentPadding: EdgeInsets.zero,
        leading: Icon(w.wifiEnabled ? Icons.wifi : Icons.wifi_off),
        title: Text(
          !w.wifiEnabled
              ? s.t('ctl.wifi_off')
              : w.ssid != null
              ? s.t('ctl.wifi_network', {'ssid': w.ssid})
              : s.t('ctl.wifi_unknown'),
        ),
        subtitle: Text(s.t('ctl.hotspot_${w.hotspot.name}')),
      ),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          OutlinedButton(
            key: const Key('ctl-hotspot-settings'),
            onPressed: () => services.wifi?.openHotspotSettings(),
            child: Text(s.t('ctl.hotspot_settings')),
          ),
          OutlinedButton(
            key: const Key('ctl-wifi-settings'),
            onPressed: () => services.wifi?.openWifiSettings(),
            child: Text(s.t('ctl.wifi_settings')),
          ),
        ],
      ),
      const SizedBox(height: 12),
      Text(s.t('ctl.local_intro')),
      const SizedBox(height: 8),
      if (local != null && local.error != null)
        Notice(
          s.tOr(
            'ctl.local_error_${local.error}',
            s.t('ctl.local_error_generic'),
          ),
          kind: NoticeKind.error,
        ),
      if (local != null && local.started) ...[
        Text(
          s.t('ctl.local_on', {'ssid': local.ssid}),
          key: const Key('ctl-local-on'),
        ),
        if (local.passphrase != null)
          SelectableText(
            s.t('ctl.local_password', {'password': local.passphrase}),
          ),
        const SizedBox(height: 8),
        Center(
          child: Semantics(
            label: s.t('ctl.local_qr', {'ssid': local.ssid}),
            image: true,
            child: QrCodeView(data: local.qrText!, size: 200),
          ),
        ),
        const SizedBox(height: 8),
        OutlinedButton(
          key: const Key('ctl-local-stop'),
          onPressed: _stopLocal,
          child: Text(s.t('ctl.local_stop')),
        ),
      ] else
        OutlinedButton(
          key: const Key('ctl-local-start'),
          onPressed: _startLocal,
          child: Text(s.t('ctl.local_start')),
        ),
    ];
  }

  List<Widget> _radio(BuildContext context, Strings s) {
    final st = _shell.status;
    if (_shell.running && st != null) {
      return [
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: Icon(st.pod ? Icons.settings_input_antenna : Icons.wifi),
          title: Text(
            st.pod
                ? s.t('ctl.radio_pod', {'name': _podName ?? '?'})
                : s.t('ctl.radio_none'),
          ),
          subtitle: Text(
            '${s.tOr('ctl.radio_${st.radio}', st.radio)}\n${s.t('ctl.radio_locked')}',
          ),
          isThreeLine: true,
        ),
      ];
    }
    final found = _found;
    return [
      ListTile(
        contentPadding: EdgeInsets.zero,
        leading: Icon(_pod != null ? Icons.settings_input_antenna : Icons.wifi),
        title: Text(
          _pod != null
              ? s.t('ctl.radio_pod', {'name': _podName ?? '?'})
              : s.t('ctl.radio_none'),
        ),
        subtitle: Text(s.t('ctl.radio_hint')),
      ),
      if (_podError != null) Notice(s.t(_podError!), kind: NoticeKind.error),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          OutlinedButton.icon(
            key: const Key('ctl-pod-find'),
            icon: const Icon(Icons.search),
            label: Text(s.t('pod.find')),
            onPressed: _podBusy ? null : _findPods,
          ),
          if (_pod != null)
            TextButton(
              key: const Key('ctl-pod-forget'),
              onPressed: _forgetPod,
              child: Text(s.t('ctl.pod_forget')),
            ),
        ],
      ),
      if (_podBusy) const LinearProgressIndicator(),
      if (found != null && found.isEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(s.t('pod.found_none')),
        ),
      for (final d in found ?? const <PodDevice>[])
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: Icon(d.kind == 'usb' ? Icons.usb : Icons.bluetooth),
          title: Text(d.name),
          subtitle: Text(d.id),
          onTap: _podBusy ? null : () => _openPod(d),
        ),
    ];
  }

  List<Widget> _codes(BuildContext context, Strings s) {
    final st = _shell.status!;
    Widget code(String key, String label, String value) => ListTile(
      key: Key(key),
      contentPadding: EdgeInsets.zero,
      title: Text(label),
      subtitle: Semantics(
        label: _showCodes ? null : s.t('ctl.code_hidden'),
        child: _showCodes
            ? SelectableText(value)
            : const ExcludeSemantics(child: Text('••••••••••••')),
      ),
      trailing: IconButton(
        tooltip: s.t('ctl.copy', {'what': label}),
        icon: const Icon(Icons.copy),
        onPressed: () async {
          await Clipboard.setData(ClipboardData(text: value));
          if (!context.mounted) return;
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(s.t('ctl.copied', {'what': label}))),
          );
        },
      ),
    );
    return [
      Text(s.t('ctl.codes_hint')),
      code('ctl-code-gm', s.t('ctl.code_gm'), st.gmToken),
      code('ctl-code-read', s.t('ctl.code_read'), st.readToken),
      Align(
        alignment: Alignment.centerLeft,
        child: TextButton.icon(
          key: const Key('ctl-show-codes'),
          icon: Icon(_showCodes ? Icons.visibility_off : Icons.visibility),
          label: Text(s.t(_showCodes ? 'ctl.hide_codes' : 'ctl.show_codes')),
          onPressed: () => setState(() => _showCodes = !_showCodes),
        ),
      ),
    ];
  }

  List<Widget> _console(BuildContext context, Strings s) {
    final st = _shell.status;
    final url = st?.consoleUrl;
    final can = _shell.running && st != null && st.hasConsole && url != null;
    final poster = st != null && st.urls.isNotEmpty
        ? '${st.urls.first}/console/'
        : null;
    return [
      if (_shell.running && st != null && !st.hasConsole)
        Notice(s.t('ctl.no_console'), kind: NoticeKind.warning),
      FilledButton.icon(
        key: const Key('ctl-console'),
        icon: const Icon(Icons.dashboard),
        label: Text(s.t('ctl.open_console')),
        onPressed: can
            ? () => Navigator.push(
                context,
                MaterialPageRoute<void>(
                  builder: (_) => ControllerConsoleScreen(
                    url: url,
                    gmToken: st.gmToken,
                    language: s.code,
                  ),
                ),
              )
            : null,
      ),
      const SizedBox(height: 8),
      Text(
        poster == null
            ? s.t('ctl.poster_hint_closed')
            : s.t('ctl.poster_hint', {'url': poster}),
      ),
    ];
  }
}

/// The GM console of this phone's own controller in the app's web view, on
/// the loopback address (decision PE24-62), logged in with the GM token and
/// in the app's language given in the address's fragment (`#token=...&lang=`,
/// [consoleAddress]): the console stores them as a typed token and takes
/// them out of the address at once (PE24-66, PE24-70). The fragment never
/// leaves the web view: it is not sent in the request.
class ControllerConsoleScreen extends StatelessWidget {
  const ControllerConsoleScreen({
    required this.url,
    required this.gmToken,
    required this.language,
    super.key,
  });

  final Uri url;
  final String gmToken;
  final String language;

  @override
  Widget build(BuildContext context) {
    final address = consoleAddress(url, gmToken, language);
    return Scaffold(
      appBar: AppBar(title: Text(context.s.t('ctl.console_title'))),
      body: context.services.consoleView != null
          ? context.services.consoleView!(context, address)
          : _OwnConsoleView(url: address),
    );
  }
}

/// [url] with the GM token and the language in its fragment, as the console
/// (controller/console/src/ui.js `takeHashToken`) and the scoreboard take
/// them; never in the query string.
Uri consoleAddress(Uri url, String token, String language) => url.replace(
  fragment:
      'token=${Uri.encodeComponent(token)}'
      '&lang=${Uri.encodeComponent(language)}',
);

class _OwnConsoleView extends StatefulWidget {
  const _OwnConsoleView({required this.url});

  final Uri url;

  @override
  State<_OwnConsoleView> createState() => _OwnConsoleViewState();
}

class _OwnConsoleViewState extends State<_OwnConsoleView> {
  late final WebViewController _controller = WebViewController()
    ..setJavaScriptMode(JavaScriptMode.unrestricted)
    ..setNavigationDelegate(
      NavigationDelegate(
        // Only this phone's own console: anything else opens nowhere.
        onNavigationRequest: (r) {
          final u = Uri.tryParse(r.url);
          return u != null &&
                  u.host == widget.url.host &&
                  u.port == widget.url.port
              ? NavigationDecision.navigate
              : NavigationDecision.prevent;
        },
      ),
    )
    ..loadRequest(widget.url);

  @override
  Widget build(BuildContext context) => WebViewWidget(controller: _controller);
}
