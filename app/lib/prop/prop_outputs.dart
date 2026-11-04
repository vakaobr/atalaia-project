// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A phone prop's outputs on its I/O pod (draft RFC "The expansion port",
/// increment 9, decision EXP-26; protocol/capability-proxy.md, "Outputs"):
/// the pod lends its simple outputs as capabilities of type `output`
/// (`{"id": "siren", "type": "output", "feedback": false}`), and the prop's
/// shell does for them what a box's output layer does
/// (firmware/esp32/main/outputs.c), with the same model as the Dart mode
/// runner's boxes ([BoxOutputs], strict):
///
/// - a mode's `cap("siren"):pulse(ms)`, `:on(max_ms)`, `:off()` and
///   `:pattern(on_ms, off_ms, ms)` ([scriptCall]), and the controller's CMD 12
///   ([command]: its params checked as a box checks them, `src` field or gm);
/// - on only while the game runs, or in the 10 s grace after its end; every
///   output off at the start, a pause, the end and a halted script; a call
///   never longer than the output's longest on ([podOutputMaxOnMs]); a change
///   at most every 500 ms (a shorter pulse lasts 500 ms, a faster pattern and
///   an on within 500 ms of an off are refused); a script starts an output at
///   most twice a second (more are dropped, and one script.error a game says
///   so: [onScriptError]); a call to an output the pod lacks does nothing;
/// - each start, and each off before its time, is an output.switched for the
///   controller ([onSwitched]);
/// - what the model decides goes to the pod as its CMDs: `on {"ms"}`,
///   `pulse {"ms"}` or `pattern {"on_ms", "off_ms", "ms"}` with the time the
///   model gave it, and `off`;
/// - the pod's lease: while one of its outputs is on, the phone speaks to the
///   pod at least every [podKeepaliveMs] (a RADIO_CMD PING, [ping]); the pod
///   turns its outputs off after 1.5 s of silence, and at once when the link
///   goes. The model then counts them off too ([detach]).
///
/// The pod keeps its own limits (its build's longest on, the 500 ms floor),
/// so a phone that asks for more gets what the pod allows.
library;

import '../controller/controller_outputs.dart' show outputParamsProblem;
import '../pod/pod_codec.dart' show PodIdent;
import 'box_outputs.dart';

/// How long a pod's output may stay on, as the phone counts it: a box's
/// default longest on, which is also the pod build's default (the pod's own
/// may be shorter: the shorter wins).
const podOutputMaxOnMs = outputMaxOnDefaultS * 1000;

/// While one of the pod's outputs is on, the phone speaks to the pod at least
/// this often (the pod's lease: firmware/esp32/main/pod/pod_outputs.h).
const podKeepaliveMs = 500;

/// A script starts one output at most this many times a second (EXP-30).
const _scriptStarts = 2;

/// Sends a CMD to one of the pod's capabilities.
typedef PodOutputSend = void Function(
  String capId,
  String method,
  Map<String, Object?> args,
);

class PropOutputs {
  PropOutputs({
    required this.send,
    required this.ping,
    this.onSwitched,
    this.onScriptError,
  });

  final PodOutputSend send;

  /// Something for the pod to hear while an output is on (a RADIO_CMD PING).
  final void Function() ping;

  /// Each output.switched's data (`capability`, `ms`, `source`).
  final void Function(int tMs, Map<String, Object?> data)? onSwitched;

  /// A script.error's message (a script's third start of an output within a
  /// second; once a game, as a box says it).
  final void Function(String message)? onScriptError;

  final _starts = <String, List<int>>{};
  final _rateTold = <String>{};

  BoxOutputs _box = BoxOutputs(const {});
  var _linked = false;
  var _lastSent = 0;
  String _act = 'on';

  /// The pod's outputs, while it is linked.
  Iterable<String> get ids => _linked ? _box.channels.keys : const [];

  /// Whether the linked pod has the output [id].
  bool has(String id) => _linked && _box.has(id);

  /// The game as the outputs see it: none, running, paused, ended, halted.
  String get game => _box.game;

  /// An output now: on, how long it stays on, who switched it.
  ({bool on, int leftMs, String? source}) state(String id, int t) =>
      has(id) ? _box.state(id, t) : (on: false, leftMs: 0, source: null);

  /// The pod said who it is (linked, or linked again): its outputs, each
  /// off (the pod starts them off). The game's state carries over.
  void attach(PodIdent ident) {
    final fitted = <String, int>{
      for (final c in ident.capabilities)
        if (c['type'] == 'output' && c['id'] is String)
          c['id']! as String: podOutputMaxOnMs,
    };
    _box = BoxOutputs(fitted, onSwitched, true)
      ..game = _box.game
      ..graceUntil = _box.graceUntil;
    _linked = fitted.isNotEmpty;
  }

  /// The pod's link went: the pod turned its outputs off itself; the model
  /// follows, without an output.switched (as when the game state turns them
  /// off).
  void detach(int t) {
    _linked = false;
    for (final c in _box.channels.values) {
      if (c.on(t)) c.untilMs = t;
    }
  }

  /// The game starts (before the mode's game.start handlers run).
  void gameStart(int t) {
    _starts.clear();
    _rateTold.clear();
    _apply(t, () => _box.gameStart(t));
  }

  void pause(int t) => _apply(t, () => _box.pause(t));

  void resume() => _box.resume();

  /// The game ends: every output off, then the 10 s grace (before the mode's
  /// game.end handlers run). Nothing when it was not running or paused.
  void end(int t) => _apply(t, () => _box.end(t));

  /// The mode's script was halted.
  void halt(int t) => _apply(t, () => _box.halt(t));

  /// A mode's cap(target):method(args): true when it was for one of the
  /// pod's outputs (handled here, never passed on as it is).
  bool scriptCall(int t, String target, String method, List<Object?> args) {
    if (!has(target)) return false;
    if (method != 'off' && _tooMany(t, target)) return true;
    _act = method;
    return _apply(t, () => _box.scriptCall(t, target, method, args));
  }

  /// A script's start beyond its two a second (outputs_switch's OUT_RATE):
  /// dropped, and said once a game.
  bool _tooMany(int t, String id) {
    final starts = (_starts[id] ??= [])..removeWhere((s) => t - s >= 1000);
    if (starts.length < _scriptStarts) {
      starts.add(t);
      return false;
    }
    if (_rateTold.add(id)) {
      onScriptError?.call(
        'output $id: more than $_scriptStarts starts a second, dropped',
      );
    }
    return true;
  }

  /// Switches an output (ok, no_such, not_now, bad_args or too_soon).
  String switchOutput(
    int t,
    String capability,
    String act, {
    int ms = 0,
    int onMs = 0,
    int offMs = 0,
    String source = 'script',
  }) {
    if (!_linked) return 'no_such';
    _act = act;
    return _apply(
      t,
      () => _box.switchOutput(
        t,
        capability,
        act,
        ms: ms,
        onMs: onMs,
        offMs: offMs,
        source: source,
      ),
    );
  }

  /// CMD 12 for this prop (RFC 0001 Amendment 26), handled by the shell
  /// whatever the mode: the params checked as a box checks them (null when
  /// taken), then [switchOutput] with the controller's `src`. Returns why it
  /// was refused, or the switch's result.
  String command(int t, Map<String, Object?> params) {
    final problem = outputParamsProblem(params);
    if (problem != null) return problem;
    int n(String k) => params[k] is int ? params[k]! as int : 0;
    return switchOutput(
      t,
      params['capability']! as String,
      params['act']! as String,
      ms: n('ms'),
      onMs: n('on_ms'),
      offMs: n('off_ms'),
      source: params['src']! as String,
    );
  }

  /// Every turn of the prop's loop: the lease while an output is on.
  void tick(int t) {
    if (!_linked || t - _lastSent < podKeepaliveMs) return;
    if (!_box.channels.values.any((c) => c.on(t))) return;
    _lastSent = t;
    ping();
  }

  /// Runs [op] on the model and sends the pod what changed.
  T _apply<T>(int t, T Function() op) {
    final before = {
      for (final c in _box.channels.values)
        c.id: (c.on(t), c.startMs, c.untilMs, c.onMs, c.offMs),
    };
    final result = op();
    if (!_linked) return result;
    for (final c in _box.channels.values) {
      final was = before[c.id];
      final now = (c.on(t), c.startMs, c.untilMs, c.onMs, c.offMs);
      if (was == now) continue;
      if (!c.on(t)) {
        if (was != null && was.$1) _send(t, c.id, 'off', const {});
        continue;
      }
      final ms = c.untilMs - t;
      if (c.onMs > 0) {
        _send(t, c.id, 'pattern', {
          'on_ms': c.onMs,
          'off_ms': c.offMs,
          'ms': ms,
        });
      } else {
        _send(t, c.id, _act == 'on' ? 'on' : 'pulse', {'ms': ms});
      }
    }
    return result;
  }

  void _send(int t, String id, String method, Map<String, Object?> args) {
    _lastSent = t;
    send(id, method, args);
  }
}
