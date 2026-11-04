// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A box's outputs: the port of simulator/atalaia_sim/box_outputs.py (draft
/// RFC "The expansion port", increment 4), the box's output layer
/// (firmware/esp32/main/outputs.c): an output switches on only while the game
/// runs or in the 10 s grace after its end; every output goes off at the
/// start, a pause, the end and a halted script; a call never runs longer than
/// the output's max on; a simple output shows a change for at least 500 ms; a
/// call to an output the box lacks does nothing. Each start, and each off
/// before its time, is an output.switched.
///
/// The Dart mode runner's boxes use it (app/test/support/mode_runner.dart,
/// as the simulator's does), and so does a phone prop for its I/O pod's
/// outputs (prop_outputs.dart, increment 9), with [BoxOutputs.strict]: an
/// output that went off less than 500 ms ago does not switch on again, as
/// the pod's own output layer refuses it (the simulator leaves that out).
library;

const outputGraceMs = 10000;
const _simpleMinMs = 500;
const _msMax = 600000;
const _patternMaxMs = 10000;
const outputMaxOnDefaultS = 30;
const _maxOnMaxS = 600;
const _methods = {'on', 'off', 'pulse', 'pattern'};

/// One output of a box: its function, max on and desired state.
class OutputChannel {
  OutputChannel(this.id, this.maxOnMs);
  final String id;
  final int maxOnMs;
  int startMs = 0;
  int untilMs = 0; // on while the game time is before this
  int onMs = 0; // a pattern's on and off times (0: steady)
  int offMs = 0;
  String source = '';

  bool on(int t) => t < untilMs;

  bool level(int t) {
    if (!on(t)) return false;
    if (onMs == 0) return true;
    return (t - startMs) % (onMs + offMs) < onMs;
  }
}

/// A test's outputs for one node: a list of functions (the default max on)
/// or a map of function to max on in seconds (1-600). Throws [ArgumentError].
Map<String, int> fittedOutputs(Object? spec, String where) {
  final Map<Object?, Object?> map;
  if (spec is List) {
    map = {for (final fn in spec) fn: outputMaxOnDefaultS};
  } else if (spec is Map) {
    map = spec;
  } else {
    throw ArgumentError(
      '$where: outputs are a list of functions, or a map of function to max on (s)',
    );
  }
  final out = <String, int>{};
  for (final e in map.entries) {
    final fn = e.key, maxOn = e.value;
    if (fn is! String || fn.isEmpty) {
      throw ArgumentError(
        "$where: an output's function is text, such as siren",
      );
    }
    if (maxOn is! int || maxOn < 1 || maxOn > _maxOnMaxS) {
      throw ArgumentError('$where: output $fn: max on is 1 to $_maxOnMaxS s');
    }
    out[fn] = maxOn * 1000;
  }
  return out;
}

/// One box's outputs; [onSwitched] gets each output.switched's data.
class BoxOutputs {
  BoxOutputs(Map<String, int> fitted, [this.onSwitched, this.strict = false])
    : channels = {
        for (final e in fitted.entries) e.key: OutputChannel(e.key, e.value),
      };

  final Map<String, OutputChannel> channels;
  final void Function(int tMs, Map<String, Object?> data)? onSwitched;

  /// Refuses an on within 500 ms of the output's last off (`too_soon`), as
  /// the firmware's output layer does.
  final bool strict;
  String game = 'none'; // none, running, paused, ended, halted
  int graceUntil = 0;

  bool has(String capability) => channels.containsKey(capability);

  void _allOff(int t) {
    for (final c in channels.values) {
      if (c.on(t)) c.untilMs = t;
    }
  }

  void gameStart(int t) {
    _allOff(t);
    game = 'running';
  }

  void pause(int t) {
    if (game == 'running') {
      _allOff(t);
      game = 'paused';
    }
  }

  void resume() {
    if (game == 'paused') game = 'running';
  }

  /// The game ends: every output off, then the grace (before the mode's
  /// game.end handlers run).
  void end(int t) {
    if (game == 'running' || game == 'paused') {
      _allOff(t);
      game = 'ended';
      graceUntil = t + outputGraceMs;
    }
  }

  /// The box restarted: every output off, then it plays on in the running
  /// game (or waits for one).
  void boot(int t, bool running) {
    _allOff(t);
    game = running ? 'running' : 'none';
  }

  void halt(int t) {
    if (game != 'halted') {
      _allOff(t);
      game = 'halted';
    }
  }

  void _tell(int t, String capability, int ms, String source) => onSwitched
      ?.call(t, {'capability': capability, 'ms': ms, 'source': source});

  void _off(int t, OutputChannel c, String source) {
    if (c.on(t)) {
      c.untilMs = t;
      _tell(t, c.id, 0, source);
    }
  }

  /// outputs_switch: ok, no_such, not_now, bad_args (or too_soon when
  /// [strict]).
  String switchOutput(
    int t,
    String capability,
    String act, {
    int ms = 0,
    int onMs = 0,
    int offMs = 0,
    String source = 'script',
  }) {
    if (capability == '*') {
      if (act != 'off') return 'bad_args';
      for (final c in channels.values) {
        _off(t, c, source);
      }
      return 'ok';
    }
    final c = channels[capability];
    if (c == null) return 'no_such';
    if (act == 'off') {
      _off(t, c, source);
      return 'ok';
    }
    final grace = game == 'ended' && t < graceUntil;
    if (game != 'running' && !grace) return 'not_now';
    var d = ms;
    if (act == 'on') {
      d = d <= 0 || d > c.maxOnMs ? c.maxOnMs : d;
    } else if (act == 'pulse' || act == 'pattern') {
      if (d < 1 || d > _msMax) return 'bad_args';
      if (d > c.maxOnMs) d = c.maxOnMs;
    } else {
      return 'bad_args';
    }
    if (act == 'pattern' &&
        !(onMs >= _simpleMinMs &&
            onMs <= _patternMaxMs &&
            offMs >= _simpleMinMs &&
            offMs <= _patternMaxMs)) {
      return 'bad_args';
    }
    if (d < _simpleMinMs) d = _simpleMinMs;
    if (grace) {
      final left = graceUntil - t;
      if (left < _simpleMinMs) return 'not_now';
      if (d > left) d = left;
    }
    // Off to on: not within 500 ms of the last change (an off is never held
    // back). An output that is off went off at untilMs.
    if (strict && !c.on(t) && c.untilMs > 0 && t - c.untilMs < _simpleMinMs) {
      return 'too_soon';
    }
    c
      ..startMs = t
      ..untilMs = t + d
      ..source = source
      ..onMs = act == 'pattern' ? onMs : 0
      ..offMs = act == 'pattern' ? offMs : 0;
    _tell(t, c.id, d, source);
    return 'ok';
  }

  /// A script's cap(target):method(args): true when it was for an output of
  /// this box (command_dispatch_output).
  bool scriptCall(int t, String target, String method, List<Object?> args) {
    if (!channels.containsKey(target) || !_methods.contains(method)) {
      return false;
    }
    int ms(int i) {
      final v = i < args.length ? args[i] : null;
      if (v is! num || !(v >= 1)) return 0;
      return v > _msMax ? _msMax : v.toInt();
    }

    switch (method) {
      case 'pulse':
        if (ms(0) > 0) switchOutput(t, target, 'pulse', ms: ms(0));
      case 'on':
        switchOutput(t, target, 'on', ms: ms(0));
      case 'off':
        switchOutput(t, target, 'off');
      default:
        if (ms(0) > 0 && ms(1) > 0 && ms(2) > 0) {
          switchOutput(
            t,
            target,
            'pattern',
            ms: ms(2),
            onMs: ms(0),
            offMs: ms(1),
          );
        }
    }
    return true;
  }

  bool level(String capability, int t) =>
      game != 'halted' && (channels[capability]?.level(t) ?? false);

  /// An output now: on, the ms it stays on, and who switched it.
  ({bool on, int leftMs, String? source}) state(String capability, int t) {
    final c = channels[capability]!;
    final running = c.on(t) && game != 'halted';
    return (
      on: level(capability, t),
      leftMs: running ? c.untilMs - t : 0,
      source: running ? c.source : null,
    );
  }
}
