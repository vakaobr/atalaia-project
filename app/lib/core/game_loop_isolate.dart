// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The game loop isolate (ADR-P3-1): one isolate owns one node and is the
/// only code that calls into it. The UI isolate talks to it with messages.
///
///     UI isolate                     game loop isolate
///       input(type, data) --------->  queued; applied on the next tick
///                                     atalaia_node_input / _advance (100 Hz)
///       outputs  <------------------  events, commands, log lines, status
///
/// With [GameClock.realTime] a `Timer.periodic` of 10 ms drains the queued
/// inputs, then moves game time on by the wall-clock time since the last
/// tick (measured with a Stopwatch), as the Field Box's shell does. Game
/// time starts with the first accepted game.start, and stands still while
/// the game is paused and once it has ended or halted. With
/// [GameClock.manual] inputs apply at once and time moves only on
/// [GameLoopIsolate.advanceTo]: tests and replays.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:isolate';

import '../ffi/bindings.dart';
import '../ffi/callbacks.dart';
import '../ffi/core_node.dart';
import 'node_types.dart';

/// The node's setup failed in its isolate (the library did not load, or the
/// core refused the teams or parameters).
class GameLoopException implements Exception {
  GameLoopException(this.message);

  final String message;

  @override
  String toString() => 'GameLoopException: $message';
}

/// The main-isolate side of a game loop isolate.
final class GameLoopIsolate implements RunningNode {
  GameLoopIsolate._(
    this._isolate,
    this._port,
    this._commands,
    this.loaded,
    this.clock,
  );

  /// Spawns the isolate, loads the core from [libraryPath] (see
  /// `resolveCoreLibrary`) and the node from [spec]. The node runs even if
  /// its script does not load ([loaded] false; the core halts it and shows
  /// its paused screen). [onOutput], if given, listens to [outputs] from the
  /// start, so it also gets what the script's top level emitted; those
  /// outputs are kept in [startupOutputs] as well.
  static Future<GameLoopIsolate> spawn(
    NodeSpec spec, {
    String? libraryPath,
    GameClock clock = GameClock.realTime,
    Duration tick = const Duration(milliseconds: 10),
    void Function(NodeOutput output)? onOutput,
  }) async {
    final port = ReceivePort('atalaia game loop');
    final ready = Completer<_Ready>();
    final early = <Object?>[];
    late final StreamSubscription<Object?> sub;
    sub = port.listen((msg) {
      if (!ready.isCompleted) {
        if (msg is _Ready) {
          ready.complete(msg);
        } else if (msg is _Failed) {
          ready.completeError(GameLoopException(msg.message));
        } else if (msg is List && msg.length == 2) {
          // An uncaught error from the isolate (onError): [message, stack].
          ready.completeError(GameLoopException('${msg[0]}'));
        } else if (msg == null) {
          ready.completeError(GameLoopException('the isolate exited'));
        } else {
          early.add(msg); // outputs of the script's top level
        }
      }
    });
    final isolate = await Isolate.spawn(
      _main,
      _Boot(port.sendPort, spec, resolveCoreLibrary(libraryPath), clock, tick),
      debugName: 'atalaia-game-loop',
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
    final loop = GameLoopIsolate._(isolate, port, r.commands, r.loaded, clock);
    loop._lastSnapshot = r.snapshot;
    if (onOutput != null) loop._outputs.stream.listen(onOutput);
    for (final msg in early) {
      if (msg is NodeOutput) loop.startupOutputs.add(msg);
      loop._receive(msg);
    }
    sub.onData(loop._receive);
    return loop;
  }

  final Isolate _isolate;
  final ReceivePort _port;
  final SendPort _commands;
  final GameClock clock;

  @override
  final bool loaded;

  final _outputs = StreamController<NodeOutput>.broadcast(sync: true);
  final _pending = <int, Completer<Object?>>{};
  var _nextId = 1;
  var _closed = false;
  NodeSnapshot? _lastSnapshot;

  /// What the script's top level emitted while the node was loading.
  final List<NodeOutput> startupOutputs = [];

  @override
  Stream<NodeOutput> get outputs => _outputs.stream;

  /// The last state the isolate reported (at start, and on every change).
  NodeSnapshot? get lastSnapshot => _lastSnapshot;

  void _receive(Object? msg) {
    switch (msg) {
      case _Reply(:final id, :final value, :final error):
        final c = _pending.remove(id);
        if (c == null) return;
        if (error != null) {
          c.completeError(GameLoopException(error));
        } else {
          c.complete(value);
        }
      case final NodeOutput output:
        if (output is NodeStatusOutput) _lastSnapshot = output.snapshot;
        _outputs.add(output);
      case [final Object? error, final Object? _]:
        _outputs.add(NodeErrorOutput('the game loop isolate failed: $error'));
      case null:
        _shutDown('the game loop isolate exited');
    }
  }

  void _shutDown(String why) {
    if (_closed) return;
    _closed = true;
    for (final c in _pending.values) {
      c.completeError(GameLoopException(why));
    }
    _pending.clear();
    _port.close();
    unawaited(_outputs.close());
  }

  Future<Object?> _call(_Op op, [Object? a, Object? b]) {
    if (_closed) {
      return Future.error(GameLoopException('the game loop is closed'));
    }
    final id = _nextId++;
    final c = Completer<Object?>();
    _pending[id] = c;
    _commands.send(_Request(id, op, a, b));
    return c.future;
  }

  @override
  Future<bool> input(String type, [Map<String, Object?>? data]) async =>
      await _call(_Op.input, type, data == null ? null : jsonEncode(data))
          as bool;

  @override
  Future<void> advanceTo(int timeMs) async {
    await _call(_Op.advance, timeMs);
  }

  @override
  Future<NodeSnapshot> snapshot() async =>
      await _call(_Op.snapshot) as NodeSnapshot;

  @override
  Future<void> close() async {
    if (_closed) return;
    try {
      await _call(_Op.close);
    } on GameLoopException {
      // already gone
    }
    _shutDown('closed');
    _isolate.kill();
  }
}

// ---- Messages ----------------------------------------------------------------

enum _Op { input, advance, snapshot, close }

final class _Boot {
  const _Boot(this.port, this.spec, this.library, this.clock, this.tick);
  final SendPort port;
  final NodeSpec spec;
  final String library;
  final GameClock clock;
  final Duration tick;
}

final class _Ready {
  const _Ready(this.commands, this.loaded, this.snapshot);
  final SendPort commands;
  final bool loaded;
  final NodeSnapshot snapshot;
}

final class _Failed {
  const _Failed(this.message);
  final String message;
}

final class _Request {
  const _Request(this.id, this.op, this.a, this.b);
  final int id;
  final _Op op;
  final Object? a;
  final Object? b;
}

final class _Reply {
  const _Reply(this.id, this.value, [this.error]);
  final int id;
  final Object? value;
  final String? error;
}

// ---- The isolate ---------------------------------------------------------------

void _main(_Boot boot) {
  final out = boot.port;
  final AtalaiaCore core;
  try {
    core = AtalaiaCore.open(boot.library);
  } catch (e) {
    out.send(_Failed('cannot load the core from ${boot.library}: $e'));
    return;
  }
  final CoreNode node;
  try {
    node = CoreNode.create(
      core,
      boot.spec,
      handlers: NodeHandlers(
        onEvent: (e) => out.send(NodeEventOutput(e)),
        onCommand: (c) => out.send(NodeCommandOutput(c)),
        onLog: (l) => out.send(NodeLogOutput(l)),
      ),
    );
  } catch (e) {
    out.send(_Failed('$e'));
    return;
  }
  _Loop(node, out, boot.clock, boot.tick).run();
}

final class _Loop {
  _Loop(this.node, this.out, this.clock, this.tick);

  final CoreNode node;
  final SendPort out;
  final GameClock clock;
  final Duration tick;
  final _in = ReceivePort('atalaia game loop commands');
  final _queue = <_Request>[];
  final _watch = Stopwatch();
  Timer? _timer;
  var _started = false;
  var _gameUs = 0;
  var _lastUs = 0;
  late NodeSnapshot _state;

  void run() {
    _state = _snapshot();
    _flushErrors();
    out.send(_Ready(_in.sendPort, node.loaded, _state));
    _in.listen((msg) => _handle(msg as _Request));
    if (clock == GameClock.realTime) {
      _watch.start();
      _timer = Timer.periodic(tick, (_) => _tick());
    }
  }

  NodeSnapshot _snapshot() => NodeSnapshot(
    status: node.status,
    paused: node.paused,
    timeMs: node.timeMs,
    memUsed: node.memUsed,
    lastError: node.lastError,
    scores: {for (final t in node.teams) t: node.score(t)},
  );

  /// Reports handler exceptions and status changes after each call.
  void _afterCall() {
    _flushErrors();
    final now = _snapshot();
    if (now.status != _state.status || now.paused != _state.paused) {
      out.send(NodeStatusOutput(now));
    }
    _state = now;
  }

  void _flushErrors() {
    for (final e in node.callbackErrors) {
      out.send(NodeErrorOutput('a callback handler failed: $e'));
    }
    node.callbackErrors.clear();
  }

  bool _input(_Request r) {
    final type = r.a! as String;
    final ok = node.inputJson(type, r.b as String?);
    if (ok && type == 'game.start') _started = true;
    _afterCall();
    return ok;
  }

  void _handle(_Request r) {
    try {
      switch (r.op) {
        case _Op.input:
          if (clock == GameClock.realTime) {
            _queue.add(r); // applied on the next tick, in order
            return;
          }
          out.send(_Reply(r.id, _input(r)));
        case _Op.advance:
          if (clock != GameClock.manual) {
            out.send(_Reply(r.id, null, 'advanceTo needs GameClock.manual'));
            return;
          }
          node.advance(r.a! as int);
          _afterCall();
          out.send(_Reply(r.id, null));
        case _Op.snapshot:
          out.send(_Reply(r.id, _snapshot()));
        case _Op.close:
          _timer?.cancel();
          for (final q in _queue) {
            out.send(_Reply(q.id, false));
          }
          _queue.clear();
          node.close();
          out.send(_Reply(r.id, null));
          _in.close();
          Isolate.exit();
      }
    } catch (e) {
      out.send(_Reply(r.id, null, '$e'));
    }
  }

  void _tick() {
    for (final r in _queue) {
      try {
        out.send(_Reply(r.id, _input(r)));
      } catch (e) {
        out.send(_Reply(r.id, null, '$e'));
      }
    }
    _queue.clear();
    final nowUs = _watch.elapsedMicroseconds;
    final delta = nowUs - _lastUs;
    _lastUs = nowUs;
    if (!_started || _state.status != NodeStatus.running || _state.paused) {
      return;
    }
    _gameUs += delta;
    node.advance(_gameUs ~/ 1000);
    _afterCall();
  }
}
