// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The phone controller's shell on the UI isolate (slice S6 of PE24,
/// ADR-P3-12): it starts the controller's isolate (controller_isolate.dart)
/// with what the app has (its private folder, the field join key, the GM
/// console's files, the check-in notices, the limit template, an I/O pod's
/// link), keeps the process and the CPU running while it serves with the
/// foreground service and its wake and Wi-Fi locks (ADR-P3-5's service,
/// AtalaiaForegroundService.kt; constraint 7), shows the live game in the
/// service's notification, and stops it all. It outlives the controller's
/// screen: the GM can leave it and come back (AppServices.controller).
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../l10n/strings.dart';
import '../platform/services.dart';
import '../pod/pod_client.dart';
import 'console_assets.dart';
import 'controller_host.dart';
import 'controller_isolate.dart';

/// What the controller takes from the app's assets.
final class ControllerAssets {
  const ControllerAssets({
    required this.console,
    required this.limitsYaml,
    this.noticePt = '',
    this.noticeEn = '',
  });

  final Map<String, Uint8List> console;
  final String limitsYaml;
  final String noticePt;
  final String noticeEn;
}

typedef ControllerAssetsLoader =
    Future<ControllerAssets> Function(String limitTemplate);

/// [ControllerAssetsLoader] from the APK's assets (rootBundle).
Future<ControllerAssets> bundledControllerAssets(String limitTemplate) async {
  final console = await loadConsoleFiles(rootBundle);
  final (pt, en) = await loadNotices(rootBundle);
  String limits;
  try {
    limits = await rootBundle.loadString(
      'lib/chrono/limit_templates/$limitTemplate.yaml',
    );
  } on Object {
    limits = await rootBundle.loadString(
      'lib/chrono/limit_templates/portugal.yaml',
    );
  }
  return ControllerAssets(
    console: console.files,
    limitsYaml: limits,
    noticePt: pt,
    noticeEn: en,
  );
}

/// How the controller is started: kept for a restart.
final class ControllerStart {
  const ControllerStart({
    required this.joinKey,
    required this.open,
    this.fieldId = 'field',
    this.limitTemplate = 'portugal',
    this.pod,
    this.podName,
    this.firmwareKeys = const [],
  });

  final Uint8List joinKey;
  final bool open;
  final String fieldId;
  final String limitTemplate;

  /// The firmware release keys (the app's settings; slice S7c).
  final List<String> firmwareKeys;

  /// The I/O pod's link, opened already (null: no radio).
  final PodTransport? pod;
  final String? podName;

  ControllerStart withoutPod() => ControllerStart(
    joinKey: joinKey,
    open: open,
    fieldId: fieldId,
    limitTemplate: limitTemplate,
    firmwareKeys: firmwareKeys,
  );

  ControllerStart withFirmwareKeys(List<String> keys) => ControllerStart(
    joinKey: joinKey,
    open: open,
    fieldId: fieldId,
    limitTemplate: limitTemplate,
    pod: pod,
    podName: podName,
    firmwareKeys: keys,
  );

  ControllerStart withOpen(bool open) => ControllerStart(
    joinKey: joinKey,
    open: open,
    fieldId: fieldId,
    limitTemplate: limitTemplate,
    pod: pod,
    podName: podName,
    firmwareKeys: firmwareKeys,
  );
}

enum ControllerPhase { stopped, starting, running, stopping }

class ControllerShell extends ChangeNotifier {
  ControllerShell({
    required this.device,
    required this.foreground,
    ControllerLauncher? launcher,
    ControllerAssetsLoader? assets,
    this.directory,
  }) : _launch = launcher ?? spawnControllerIsolate,
       _assets = assets ?? bundledControllerAssets;

  final DeviceServices device;
  final ForegroundService foreground;
  final ControllerLauncher _launch;
  final ControllerAssetsLoader _assets;

  /// The controller's folder (null: `controller/` in the app's private
  /// folder, DeviceServices.filesDir).
  final String? directory;

  ControllerRun? _run;
  StreamSubscription<ControllerStatus>? _sub;
  ControllerStart? _start;
  Strings _strings = const Strings(AppLanguage.pt);
  String? _notified;

  ControllerPhase phase = ControllerPhase.stopped;

  /// Why the last start failed or the controller stopped by itself: a
  /// string key (ctl.*), with [errorDetail] when there is one.
  String? error;
  String? errorDetail;

  /// Whether Android let the foreground service start (false: the
  /// controller runs, but Android may stop it with the screen off).
  bool foregroundOn = false;

  ControllerStatus? get status => _run?.status;
  bool get running => phase == ControllerPhase.running;
  ControllerStart? get lastStart => _start;

  /// Starts the controller; false (with [error]) when it could not.
  Future<bool> start(ControllerStart how, Strings strings) async {
    if (phase != ControllerPhase.stopped) return false;
    _strings = strings;
    _start = how;
    phase = ControllerPhase.starting;
    error = errorDetail = null;
    notifyListeners();
    // Android 13+ asks for the notification; without it the service still
    // runs, its notification just is not shown.
    await device.requestPermission('POST_NOTIFICATIONS');
    foregroundOn = await foreground.start(
      title: strings.t('ctl.notif_title'),
      text: strings.t('ctl.notif_starting'),
    );
    try {
      final dir = directory ?? await _defaultDir();
      if (dir == null) throw const _ShellError('ctl.error_storage');
      final assets = await _assets(how.limitTemplate);
      final boot = ControllerBoot(
        dir: dir,
        joinKey: how.joinKey,
        limitsYaml: assets.limitsYaml,
        noticePt: assets.noticePt,
        noticeEn: assets.noticeEn,
        console: assets.console,
        open: how.open,
        pod: how.pod != null,
        fieldId: how.fieldId,
        firmwareKeys: how.firmwareKeys,
      );
      final run = _run = await _launch(boot, pod: how.pod);
      _sub = run.changes.listen((_) => _changed());
      unawaited(run.ended.then(_ended));
      phase = ControllerPhase.running;
      _changed();
      return true;
    } on _ShellError catch (e) {
      error = e.key;
    } on ControllerStartException catch (e) {
      error = 'ctl.error_start';
      errorDetail = e.message;
    } on Object catch (e) {
      error = 'ctl.error_start';
      errorDetail = '$e';
    }
    await foreground.stop();
    foregroundOn = false;
    phase = ControllerPhase.stopped;
    notifyListeners();
    return false;
  }

  Future<String?> _defaultDir() async {
    final files = await device.filesDir();
    return files == null ? null : '$files/controller';
  }

  void _changed() {
    final text = _notificationText(status);
    if (foregroundOn && text != _notified) {
      _notified = text;
      unawaited(
        foreground.update(title: _strings.t('ctl.notif_title'), text: text),
      );
    }
    notifyListeners();
  }

  String _notificationText(ControllerStatus? st) {
    final g = st?.game;
    if (g == null) return _strings.t('ctl.notif_idle');
    return _strings.t('ctl.notif_game', {
      'name': g['name'],
      'state': _strings.tOr('ctl.game_${g['state']}', '${g['state']}'),
    });
  }

  void _ended(String? why) {
    if (why == null || phase == ControllerPhase.stopping) return;
    // The controller's isolate ended by itself: say so, let the service go.
    error = 'ctl.error_ended';
    errorDetail = why;
    unawaited(_cleanUp());
  }

  Future<void> _cleanUp() async {
    // Not awaited: nothing waits on the status stream once it is dropped.
    unawaited(_sub?.cancel());
    _sub = null;
    _run = null;
    _notified = null;
    await foreground.stop();
    foregroundOn = false;
    phase = ControllerPhase.stopped;
    notifyListeners();
  }

  /// Stops the controller (the store keeps the live game for the next
  /// start), closes the pod's link and lets the foreground service go.
  Future<void> stop() async {
    if (!await _stopRun()) return;
    final pod = _start?.pod;
    if (pod != null) {
      await pod.close();
      _start = _start!.withoutPod();
    }
    notifyListeners();
  }

  Future<bool> _stopRun() async {
    final run = _run;
    if (run == null || phase != ControllerPhase.running) return false;
    phase = ControllerPhase.stopping;
    notifyListeners();
    await run.stop();
    await _cleanUp();
    return true;
  }

  /// Stops and starts again with [how] (another Wi-Fi opening), the pod's
  /// link kept: the live game is taken up again as after a restart (slice
  /// S3).
  Future<bool> restart(ControllerStart how) async {
    await _stopRun();
    return start(how, _strings);
  }
}

class _ShellError implements Exception {
  const _ShellError(this.key);
  final String key;
}
