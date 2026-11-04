// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A phone prop's hit sensors on its I/O pod (draft RFC "The expansion
/// port", increment 9, the port half; protocol/capability-proxy.md, "The
/// pod's expansion port"): the pod lends a target module's hit channels as
/// `hit` (and `hit.2`), and the prop's shell arms them as a box's port glue
/// does (firmware/esp32/main/expansion_box.c):
///
/// - a mode's `cap("hit"):arm()` and `:disarm()` are kept by capability id,
///   whether the pod has that sensor yet or not ([scriptCall]);
/// - the pod is told to arm only what the script armed, and only while the
///   game runs; at a pause, the end and a halted script every sensor is
///   disarmed, a resumed game arms them again, and the end forgets them;
/// - when the pod links again (its arming was forgotten with the link), it
///   is told again;
/// - a hit reaches the mode only while the game runs ([take]): a hit at
///   another moment is dropped, as a box drops it.
library;

/// Sends a CMD to one of the pod's capabilities.
typedef PodHitSend = void Function(
  String capId,
  String method,
  Map<String, Object?> args,
);

final _hitId = RegExp(r'^hit(\.[2-8])?$');

class PropHits {
  PropHits({required this.send});

  final PodHitSend send;

  /// The hit capabilities the script armed (kept by id).
  final armed = <String>{};

  /// The pod's hit sensors, while it is linked.
  final _fitted = <String>{};

  /// What the pod was last told, per sensor.
  final _told = <String, bool>{};

  var _running = false;

  /// Whether [id] is a hit capability id (`hit`, `hit.2` ... `hit.8`).
  static bool isHit(String id) => _hitId.hasMatch(id);

  /// The pod's hit sensors now (none when it is not linked).
  Iterable<String> get ids => _fitted;

  /// The pod said who it is (linked, or linked again): its hit sensors, none
  /// armed on the pod (a pod forgets its arming with its link).
  void attach(Iterable<Map<String, Object?>> capabilities) {
    _fitted
      ..clear()
      ..addAll([
        for (final c in capabilities)
          if (c['type'] == 'hit' && c['id'] is String) c['id']! as String,
      ]);
    _told.clear();
    _apply();
  }

  /// The pod's link went.
  void detach() {
    _fitted.clear();
    _told.clear();
  }

  void gameStart() {
    armed.clear();
    _running = true;
    _apply();
  }

  void pause() {
    _running = false;
    _apply();
  }

  void resume() {
    _running = true;
    _apply();
  }

  /// The game ends (or the script halts): every sensor disarmed, the arming
  /// forgotten.
  void end() {
    _running = false;
    _apply();
    armed.clear();
  }

  /// A mode's cap(target):method(): true when it was a hit sensor's arm or
  /// disarm (handled here).
  bool scriptCall(String target, String method) {
    if (!isHit(target) || (method != 'arm' && method != 'disarm')) {
      return false;
    }
    if (method == 'arm') {
      armed.add(target);
    } else {
      armed.remove(target);
    }
    _apply();
    return true;
  }

  /// A hit from the pod: true when it reaches the mode (the game runs).
  bool take() => _running;

  void _apply() {
    for (final id in _fitted) {
      final want = _running && armed.contains(id);
      if (_told[id] == want) continue;
      // Not yet told and not wanted: the pod starts disarmed.
      if (!_told.containsKey(id) && !want) {
        _told[id] = false;
        continue;
      }
      _told[id] = want;
      send(id, want ? 'arm' : 'disarm', const {});
    }
  }
}
