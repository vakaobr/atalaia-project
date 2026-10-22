// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The phone controller's own isolate (slice S6 of PE24; constraint 1: the
/// UI isolate never calls the core). The engine, its core node, the API's
/// servers, the broker and the tick all live on it (controller_host.dart);
/// the UI isolate only starts it, reads its status and stops it, with
/// messages:
///
///     UI isolate                         controller isolate
///       spawn(ControllerBoot) ---------->  ControllerHost.start()
///                            <----------  ready + status, then a status
///                                          every second and on a change
///       pod bytes (USB/BLE) ----------->  the pod relay (RelayPodTransport)
///                            <----------  bytes for the pod
///       stop ------------------------->  ControllerHost.stop(), exit
///
/// The UI side of a pod link stays on the UI isolate (the Kotlin plugins'
/// channels are the root isolate's): its bytes are relayed, a few hundred
/// bytes a second at the radio's rate (decision PE24-63).
library;

import 'dart:async';
import 'dart:isolate';
import 'dart:typed_data';

import '../ffi/bindings.dart';
import '../pod/pod_client.dart';
import 'controller_host.dart';

/// What the screen shows of a running controller ([ControllerHost.status]).
final class ControllerStatus {
  const ControllerStatus(this.raw);

  final Map<String, Object?> raw;

  bool get running => raw['running'] == true;
  bool get open => raw['open'] == true;
  int? get httpPort => raw['http_port'] as int?;
  int? get httpsPort => raw['https_port'] as int?;
  int? get mqttPort => raw['mqtt_port'] as int?;
  List<String> get addresses => _strings(raw['addresses']);
  List<String> get urls => _strings(raw['urls']);
  String get caShort => (raw['ca_short'] as String?) ?? '';
  String get caSha256 => (raw['ca_sha256'] as String?) ?? '';
  String get gmToken => (raw['gm_token'] as String?) ?? '';
  String get readToken => (raw['read_token'] as String?) ?? '';
  String get radio => (raw['radio'] as String?) ?? 'none';
  bool get pod => raw['pod'] == true;
  Map<String, Object?>? get game =>
      (raw['game'] as Map?)?.cast<String, Object?>();
  int get streamClients => (raw['stream_clients'] as int?) ?? 0;
  int get mqttClients => (raw['mqtt_clients'] as int?) ?? 0;
  int get props => (raw['props'] as int?) ?? 0;
  bool get hasConsole => raw['console'] == true;

  /// The GM console in the app's own web view: plain HTTP on the loopback
  /// address, which never leaves the phone (decision PE24-62).
  Uri? get consoleUrl => httpPort == null
      ? null
      : Uri(
          scheme: 'http',
          host: '127.0.0.1',
          port: httpPort,
          path: '/console/',
        );

  static List<String> _strings(Object? v) => [
    if (v is List)
      for (final x in v)
        if (x is String) x,
  ];
}

/// A running controller as the UI isolate sees it (a test gives a fake).
abstract interface class ControllerRun {
  /// The latest status, then each new one.
  ControllerStatus get status;
  Stream<ControllerStatus> get changes;

  /// The controller ended by itself (an error on its isolate): why.
  Future<String?> get ended;

  Future<void> stop();
}

/// Starts a controller; [pod] is the UI isolate's link to an I/O pod (opened
/// already) when [ControllerBoot.pod] says one is linked.
typedef ControllerLauncher =
    Future<ControllerRun> Function(ControllerBoot boot, {PodTransport? pod});

class ControllerStartException implements Exception {
  ControllerStartException(this.message);
  final String message;

  @override
  String toString() => 'ControllerStartException: $message';
}

// --- messages -----------------------------------------------------------------

final class _Start {
  const _Start(this.boot, this.reply);
  final ControllerBoot boot;
  final SendPort reply;
}

final class _Ready {
  const _Ready(this.commands, this.status);
  final SendPort commands;
  final Map<String, Object?> status;
}

final class _Failed {
  const _Failed(this.message);
  final String message;
}

final class _Status {
  const _Status(this.status);
  final Map<String, Object?> status;
}

final class _PodBytes {
  const _PodBytes(this.bytes);
  final Uint8List bytes;
}

final class _PodClosed {
  const _PodClosed();
}

final class _Stop {
  const _Stop();
}

final class _Stopped {
  const _Stopped();
}

// --- the UI isolate's side ------------------------------------------------------

/// [ControllerLauncher] on a new isolate.
Future<ControllerRun> spawnControllerIsolate(
  ControllerBoot boot, {
  PodTransport? pod,
}) => ControllerIsolate.spawn(boot, pod: pod);

final class ControllerIsolate implements ControllerRun {
  ControllerIsolate._(this._isolate, this._port, this._commands, this._status);

  final Isolate _isolate;
  final ReceivePort _port;
  final SendPort _commands;
  ControllerStatus _status;
  final _changes = StreamController<ControllerStatus>.broadcast();
  final _ended = Completer<String?>();
  final _stopped = Completer<void>();
  StreamSubscription<Uint8List>? _podSub;
  PodTransport? _pod;

  static Future<ControllerIsolate> spawn(
    ControllerBoot boot, {
    PodTransport? pod,
  }) async {
    final port = ReceivePort('atalaia controller');
    final ready = Completer<_Ready>();
    final early = <Object?>[];
    late final StreamSubscription<Object?> sub;
    sub = port.listen((msg) {
      if (ready.isCompleted) return;
      if (msg is _Ready) {
        ready.complete(msg);
      } else if (msg is _Failed) {
        ready.completeError(ControllerStartException(msg.message));
      } else if (msg is List && msg.length == 2) {
        ready.completeError(ControllerStartException('${msg[0]}'));
      } else if (msg == null) {
        ready.completeError(ControllerStartException('the isolate exited'));
      } else {
        early.add(msg);
      }
    });
    final isolate = await Isolate.spawn(
      _main,
      _Start(boot, port.sendPort),
      debugName: 'atalaia-controller',
      onError: port.sendPort,
      onExit: port.sendPort,
    );
    final _Ready r;
    try {
      r = await ready.future;
    } catch (_) {
      await sub.cancel();
      port.close();
      isolate.kill(priority: Isolate.immediate);
      rethrow;
    }
    final run = ControllerIsolate._(
      isolate,
      port,
      r.commands,
      ControllerStatus(r.status),
    );
    if (pod != null && boot.pod) run._relay(pod);
    sub.onData(run._receive);
    early.forEach(run._receive);
    return run;
  }

  void _relay(PodTransport pod) {
    _pod = pod;
    _podSub = pod.incoming.listen(
      (b) => _commands.send(_PodBytes(b)),
      onDone: () => _commands.send(const _PodClosed()),
      onError: (Object _) => _commands.send(const _PodClosed()),
    );
  }

  void _receive(Object? msg) {
    switch (msg) {
      case _Status(:final status):
        _status = ControllerStatus(status);
        if (!_changes.isClosed) _changes.add(_status);
      case _PodBytes(:final bytes):
        unawaited(_pod?.send(bytes));
      case _Stopped():
        if (!_stopped.isCompleted) _stopped.complete();
      case List() when msg.length == 2:
        // An uncaught error on the controller's isolate.
        _finish('${msg[0]}');
      case null:
        _finish(_stopped.isCompleted ? null : 'the controller stopped');
    }
  }

  void _finish(String? why) {
    if (!_ended.isCompleted) _ended.complete(why);
    if (!_stopped.isCompleted) _stopped.complete();
    unawaited(_podSub?.cancel());
    unawaited(_changes.close());
    _port.close();
  }

  @override
  ControllerStatus get status => _status;

  @override
  Stream<ControllerStatus> get changes => _changes.stream;

  @override
  Future<String?> get ended => _ended.future;

  @override
  Future<void> stop() async {
    if (_ended.isCompleted) return;
    _commands.send(const _Stop());
    try {
      await _stopped.future.timeout(const Duration(seconds: 10));
    } on TimeoutException {
      _isolate.kill(priority: Isolate.immediate);
    }
    // The pod's link is the shell's: it stays open across a restart.
    _finish(null);
  }
}

// --- the controller's isolate -------------------------------------------------

Future<void> _main(_Start start) async {
  final reply = start.reply;
  final commands = ReceivePort('atalaia controller commands');
  AtalaiaCore? core;
  try {
    core = AtalaiaCore.open(resolveCoreLibrary(start.boot.coreLibrary));
  } on Object catch (e) {
    commands.close();
    reply.send(_Failed('the core did not load: $e'));
    return;
  }
  RelayPodTransport? pod;
  if (start.boot.pod) {
    pod = RelayPodTransport('relay', (b) => reply.send(_PodBytes(b)));
  }
  final host = ControllerHost(start.boot, core: core, podTransport: pod);
  try {
    await host.start();
  } on Object catch (e) {
    commands.close();
    reply.send(_Failed('$e'));
    return;
  }
  void send() => reply.send(_Status(host.status()));
  host.onChange = send;
  reply.send(_Ready(commands.sendPort, host.status()));
  final every = Timer.periodic(const Duration(seconds: 1), (_) => send());
  await for (final msg in commands) {
    switch (msg) {
      case _PodBytes(:final bytes):
        pod?.receive(bytes);
      case _PodClosed():
        await pod?.linkClosed();
      case _Stop():
        every.cancel();
        await host.stop();
        reply.send(const _Stopped());
        commands.close();
    }
  }
}
