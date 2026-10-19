// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The Android prop's game screen: the mode's screen at the top (drawn
/// from its YAML templates, as on a Field Box), the team buttons (hold to
/// act), an optional keypad, tag reading, the light (the ring's or team
/// display's colour) and the game clock. The admin controls (start, pause,
/// end, leave) sit behind the admin PIN; the back button asks for it too.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../platform/services.dart';
import '../pod/pod_client.dart';
import '../ui/template/template_view.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'capability_mapper.dart';
import 'game_timer.dart';
import 'prop_session.dart';

PropTexts propTexts(Strings s) => PropTexts(
  notificationTitle: s.t('prop.notification_title'),
  notificationRunning: s.t('prop.notification_running'),
  notificationLeft: s.t('prop.notification_left'),
);

class PropGameScreen extends StatefulWidget {
  const PropGameScreen({
    required this.setup,
    this.pod,
    this.modeName = '',
    this.session,
    super.key,
  });

  final PropSetup setup;
  final PodClient? pod;
  final String modeName;

  /// A session to show instead of starting one (tests).
  final PropSession? session;

  @override
  State<PropGameScreen> createState() => _PropGameScreenState();
}

class _PropGameScreenState extends State<PropGameScreen> {
  late final PropSession session;
  late final NfcService _nfc;
  StreamSubscription<NfcRead>? _tags;
  bool _keypad = false;
  bool _nfcOn = false;
  bool _teamButtons = true;
  bool _keypadOffered = false;
  bool _left = false;

  @override
  void initState() {
    super.initState();
    final app = AppScope.read(context);
    final services = app.services;
    _nfc = services.nfc;
    session =
        widget.session ??
        PropSession(
          setup: widget.setup,
          runner: services.runner,
          device: services.device,
          texts: propTexts(app.strings),
          foreground: services.foreground,
          kiosk: services.kiosk,
          kioskEnabled: app.settings.kiosk,
          modeName: widget.modeName,
        );
    unawaited(_open(services));
  }

  Future<void> _open(AppServices services) async {
    if (widget.session == null) await session.open();
    final role = widget.setup.mode.main.role(widget.setup.role);
    final features = await services.device.features();
    final caps = CapabilityMap.of(features, pod: widget.pod?.ident);
    if (!mounted) return;
    setState(() {
      _teamButtons = role == null || role.uses('team_input');
      _keypadOffered = role != null && caps.offers(role, 'keypad');
    });
    if (widget.pod != null) await session.attachPod(widget.pod!);
    if (role != null && role.uses('nfc') && features.nfc) {
      _tags = _nfc.reads.listen(session.tagRead);
      await _nfc.startReading();
      if (mounted) setState(() => _nfcOn = true);
    }
  }

  @override
  void dispose() {
    unawaited(_tags?.cancel());
    if (_nfcOn) unawaited(_nfc.stopReading());
    if (widget.session == null) session.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    final s = context.s;
    if (!await askPin(context) || !mounted) return;
    if (!await confirm(
      context,
      title: s.t('prop.confirm_start'),
      yes: s.t('prop.start'),
    )) {
      return;
    }
    if (!mounted) return;
    await context.services.device.requestPermission('POST_NOTIFICATIONS');
    await session.start();
  }

  Future<void> _admin() async {
    if (!await askPin(context) || !mounted) return;
    final s = context.s;
    final action = await showModalBottomSheet<String>(
      context: context,
      builder: (c) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (session.phase == PropPhase.running)
              ListTile(
                key: const Key('admin-pause'),
                leading: const Icon(Icons.pause),
                title: Text(s.t('prop.pause')),
                onTap: () => Navigator.pop(c, 'pause'),
              ),
            if (session.phase == PropPhase.paused)
              ListTile(
                key: const Key('admin-resume'),
                leading: const Icon(Icons.play_arrow),
                title: Text(s.t('prop.resume')),
                onTap: () => Navigator.pop(c, 'resume'),
              ),
            if (session.running)
              ListTile(
                key: const Key('admin-end'),
                leading: const Icon(Icons.stop),
                title: Text(s.t('prop.end')),
                onTap: () => Navigator.pop(c, 'end'),
              ),
            ListTile(
              leading: const Icon(Icons.list),
              title: Text(s.t('prop.log')),
              onTap: () => Navigator.pop(c, 'log'),
            ),
            ListTile(
              key: const Key('admin-leave'),
              leading: const Icon(Icons.logout),
              title: Text(s.t('prop.leave')),
              onTap: () => Navigator.pop(c, 'leave'),
            ),
          ],
        ),
      ),
    );
    if (!mounted) return;
    switch (action) {
      case 'pause':
        await session.pause();
      case 'resume':
        await session.resume();
      case 'end':
        if (await confirm(
          context,
          title: s.t('prop.confirm_end'),
          yes: s.t('prop.end'),
        )) {
          await session.end();
        }
      case 'log':
        await _showLog();
      case 'leave':
        await _leave(pinAsked: true);
    }
  }

  Future<void> _leave({bool pinAsked = false}) async {
    if (_left) return;
    if (!pinAsked && !await askPin(context)) return;
    if (!mounted) return;
    final s = context.s;
    if (session.running &&
        !await confirm(
          context,
          title: s.t('prop.confirm_leave'),
          body: s.t('prop.confirm_leave_body'),
          yes: s.t('prop.leave'),
        )) {
      return;
    }
    _left = true;
    await session.close();
    if (mounted) Navigator.pop(context);
  }

  Future<void> _showLog() => showDialog<void>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(c.s.t('prop.log')),
      content: SizedBox(
        width: double.maxFinite,
        child: ListView(
          shrinkWrap: true,
          children: [
            for (final l in session.log.reversed)
              Text(l, style: const TextStyle(fontFamily: 'monospace')),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(c),
          child: Text(c.s.t('common.close')),
        ),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) => Theme(
    data: atalaiaTheme(Brightness.dark),
    child: PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) unawaited(_leave());
      },
      child: Scaffold(
        backgroundColor: AtalaiaColors.background,
        body: SafeArea(
          child: Listener(
            onPointerDown: (_) => session.touched(),
            child: ListenableBuilder(
              listenable: session,
              builder: (context, _) => _body(context),
            ),
          ),
        ),
      ),
    ),
  );

  Widget _body(BuildContext context) {
    final s = context.s;
    final teams = widget.setup.teams;
    return Column(
      children: [
        _TopBar(
          session: session,
          modeName: widget.modeName,
          nfc: _nfcOn,
          onAdmin: _admin,
        ),
        if (session.tamper)
          Container(
            width: double.infinity,
            color: AtalaiaColors.danger,
            padding: const EdgeInsets.all(8),
            child: Text(
              s.t('prop.tamper'),
              style: const TextStyle(color: Colors.white),
            ),
          ),
        Expanded(
          flex: 5,
          child: Stack(
            children: [
              Positioned.fill(child: _Screen(session: session)),
              if (session.phase == PropPhase.paused)
                _Overlay(
                  icon: Icons.pause,
                  title: s.t('prop.paused'),
                  text: s.t('prop.paused_hint'),
                ),
              if (session.phase == PropPhase.failed ||
                  session.phase == PropPhase.halted)
                _Overlay(
                  icon: Icons.error_outline,
                  title: s.t('prop.script_error'),
                  text: session.error ?? '',
                ),
            ],
          ),
        ),
        if (session.phase == PropPhase.ready)
          Padding(
            padding: const EdgeInsets.all(16),
            child: SizedBox(
              width: double.infinity,
              height: 72,
              child: FilledButton.icon(
                key: const Key('prop-start'),
                icon: const Icon(Icons.play_arrow, size: 32),
                label: Text(
                  s.t('prop.start'),
                  style: const TextStyle(fontSize: 24),
                ),
                onPressed: _start,
              ),
            ),
          ),
        if (session.phase == PropPhase.ended)
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              children: [
                Text(
                  s.t('prop.ended'),
                  style: const TextStyle(fontSize: 22, color: Colors.white),
                ),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  key: const Key('prop-leave'),
                  icon: const Icon(Icons.logout),
                  label: Text(s.t('prop.leave')),
                  onPressed: _leave,
                ),
              ],
            ),
          ),
        if (_teamButtons && session.running)
          Expanded(
            flex: 3,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(8, 8, 8, 0),
              child: Row(
                children: [
                  for (final t in teams)
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.all(6),
                        child: TeamButton(
                          team: t,
                          label: s.t('prop.hold', {
                            'team': s.team(t).toUpperCase(),
                          }),
                          down: session.tracker.isDown(t),
                          onDown: () => session.pressTeam(t),
                          onUp: () => session.releaseTeam(t),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
        if (_keypad && session.running) _Keypad(onKey: session.key),
        if (session.running)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            child: Row(
              children: [
                if (_nfcOn)
                  Expanded(
                    child: Row(
                      children: [
                        const Icon(Icons.nfc, color: AtalaiaColors.accent),
                        const SizedBox(width: 6),
                        Flexible(
                          child: Text(
                            s.t('prop.nfc_hint'),
                            style: const TextStyle(color: AtalaiaColors.muted),
                          ),
                        ),
                      ],
                    ),
                  )
                else
                  const Spacer(),
                if (_keypadOffered)
                  TextButton.icon(
                    key: const Key('prop-keypad'),
                    icon: const Icon(Icons.dialpad),
                    label: Text(
                      s.t(_keypad ? 'prop.keypad_hide' : 'prop.keypad'),
                    ),
                    onPressed: () => setState(() => _keypad = !_keypad),
                  ),
              ],
            ),
          ),
      ],
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({
    required this.session,
    required this.modeName,
    required this.nfc,
    required this.onAdmin,
  });

  final PropSession session;
  final String modeName;
  final bool nfc;
  final VoidCallback onAdmin;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final left = session.remainingMs;
    final clock = session.phase == PropPhase.ready
        ? ''
        : left != null
        ? clockText(left)
        : clockText(session.gameTimeMs);
    final phase = s.t('prop.phase_${session.phase.name}');
    return Column(
      children: [
        AnimatedContainer(
          duration: const Duration(milliseconds: 300),
          height: 10,
          color: session.light == null
              ? AtalaiaColors.panel
              : AtalaiaColors.team(session.light),
          key: const Key('prop-light'),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 6, 4, 6),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      modeName,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 18,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    Text(
                      phase,
                      style: const TextStyle(color: AtalaiaColors.muted),
                    ),
                  ],
                ),
              ),
              if (session.pod != null)
                const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 4),
                  child: Icon(Icons.memory, color: AtalaiaColors.accent),
                ),
              Text(
                clock,
                key: const Key('prop-clock'),
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 28,
                  fontFeatures: [FontFeature.tabularFigures()],
                ),
              ),
              IconButton(
                key: const Key('prop-admin'),
                tooltip: s.t('prop.admin'),
                icon: const Icon(Icons.lock, color: AtalaiaColors.muted),
                onPressed: onAdmin,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// The mode's screen, at the Field Box's 4:3.
class _Screen extends StatelessWidget {
  const _Screen({required this.session});
  final PropSession session;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final t = session.template;
    Widget child;
    if (t != null) {
      child = TemplateScreen(
        template: t,
        data: session.screenData,
        params: session.setup.params,
      );
    } else if (session.screenName != null) {
      // A screen neither the mode nor the shell has: its name and data.
      child = ColoredBox(
        color: AtalaiaColors.background,
        child: Center(
          child: Text(
            '${session.screenName}\n${session.screenData}',
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.white, fontSize: 18),
          ),
        ),
      );
    } else {
      child = ColoredBox(
        color: AtalaiaColors.background,
        child: Center(
          child: Text(
            session.phase == PropPhase.loading
                ? s.t('prop.loading')
                : s.t('prop.waiting'),
            style: const TextStyle(color: AtalaiaColors.muted, fontSize: 22),
          ),
        ),
      );
    }
    return Center(
      child: AspectRatio(aspectRatio: fieldBoxScreen.aspectRatio, child: child),
    );
  }
}

class _Overlay extends StatelessWidget {
  const _Overlay({required this.icon, required this.title, required this.text});
  final IconData icon;
  final String title;
  final String text;

  @override
  Widget build(BuildContext context) => Positioned.fill(
    child: ColoredBox(
      color: const Color(0xD0101418),
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, color: AtalaiaColors.accent, size: 56),
              Text(
                title,
                style: const TextStyle(color: Colors.white, fontSize: 36),
              ),
              Text(
                text,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: AtalaiaColors.muted,
                  fontSize: 18,
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

/// A team's big button: down while a finger is on it (the mode gets
/// team_input.press, .hold every 250 ms, .release).
class TeamButton extends StatelessWidget {
  const TeamButton({
    required this.team,
    required this.label,
    required this.down,
    required this.onDown,
    required this.onUp,
    super.key,
  });

  final String team;
  final String label;
  final bool down;
  final VoidCallback onDown;
  final VoidCallback onUp;

  @override
  Widget build(BuildContext context) {
    final color = AtalaiaColors.team(team);
    return Semantics(
      button: true,
      label: label,
      child: Listener(
        key: Key('team-button-$team'),
        onPointerDown: (_) => onDown(),
        onPointerUp: (_) => onUp(),
        onPointerCancel: (_) => onUp(),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 80),
          decoration: BoxDecoration(
            color: down ? Color.lerp(color, Colors.black, 0.35) : color,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: down ? Colors.white : Colors.transparent,
              width: 4,
            ),
          ),
          alignment: Alignment.center,
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: Text(
              label,
              textAlign: TextAlign.center,
              style: TextStyle(
                color: AtalaiaColors.on(color),
                fontSize: 22,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Keypad extends StatelessWidget {
  const _Keypad({required this.onKey});
  final void Function(String key) onKey;

  @override
  Widget build(BuildContext context) {
    const keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#'];
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: GridView.count(
        crossAxisCount: 3,
        shrinkWrap: true,
        childAspectRatio: 2.4,
        mainAxisSpacing: 6,
        crossAxisSpacing: 6,
        physics: const NeverScrollableScrollPhysics(),
        children: [
          for (final k in keys)
            FilledButton.tonal(
              key: Key('key-$k'),
              onPressed: () => onKey(k),
              child: Text(k, style: const TextStyle(fontSize: 26)),
            ),
        ],
      ),
    );
  }
}
