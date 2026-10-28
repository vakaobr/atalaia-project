// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The I/O pod's settings, pushed over the radio (protocol/pod-config.md,
/// decision PODC) on the Android field controller: the Pi controller's
/// controller/atalaia_controller/pod_config.py in Dart.
///
/// The GM sets the buttons' colours, the ring's brightness, the volume and
/// the enclosure switch of the pod a phone serves; the controller sends them
/// as CMD pod (opcode 10, RFC 0001 Amendment 17) to the phone's node id, a
/// sealed game packet like every other CMD. The pod's radio takes them,
/// keeps them in its flash and says so to its phone, which sends
/// `node.setup_applied` (`kind` `pod_config`, `rev`) over the radio. Until
/// that arrives the command is sent again after 8, 16, 32, 64 and 128 s,
/// then the pod "did not answer". Only before a game starts or after it
/// ended. The pushes live in memory; the pod's flash holds the truth.
library;

import 'dart:convert';

import 'controller_engine.dart';

const podConfigVersion = 1;
const podCmdParamsMax = 127;
const podColours = [
  'red',
  'blue',
  'green',
  'yellow',
  'orange',
  'purple',
  'white',
  'pink',
  'cyan',
];
const podButtons = 4;
const podKeys = ['btn', 'bright', 'vol', 'tamper', 'reset'];
const podKind = 'pod_config';

/// The waits after each sending; the last one ends the tries.
const podResendS = [8, 16, 32, 64, 128];
const _platformAndroid = 3;

int _uint(Object? v, String name, int lo, int hi) {
  if (v is! int || v < lo || v > hi) {
    throw ControllerError('$name: a whole number from $lo to $hi');
  }
  return v;
}

/// The command's params checked as the pod checks them (pod_settings.c):
/// the exact keys, ranges and colours, `v` 1 and `rev` 1 to 2^32-1.
Map<String, Object?> checkPodParams(Object? params) {
  if (params is! Map) throw ControllerError('the settings must be a map');
  final unknown = [
    for (final k in params.keys)
      if (k != 'v' && k != 'rev' && !podKeys.contains(k)) '$k',
  ]..sort();
  if (unknown.isNotEmpty) {
    throw ControllerError(
      'unknown setting: ${unknown.join(', ')} (one of ${podKeys.join(', ')})',
    );
  }
  if (params['v'] != podConfigVersion) {
    throw ControllerError('v: $podConfigVersion');
  }
  _uint(params['rev'], 'rev', 1, 0xFFFFFFFF);
  if (params.containsKey('btn')) {
    final btn = params['btn'];
    if (btn is! List ||
        btn.length != podButtons ||
        !btn.every(
          (c) => c is String && (c.isEmpty || podColours.contains(c)),
        )) {
      throw ControllerError(
        'btn: $podButtons colours, each empty (the game\'s N-th team) or one '
        'of ${podColours.join(', ')}',
      );
    }
  }
  for (final key in ['bright', 'vol']) {
    if (params.containsKey(key)) _uint(params[key], key, 0, 100);
  }
  for (final key in ['tamper', 'reset']) {
    if (params.containsKey(key) && params[key] is! bool) {
      throw ControllerError('$key: true or false');
    }
  }
  final size = utf8.encode(jsonEncode(params)).length;
  if (size > podCmdParamsMax) {
    throw ControllerError(
      'the settings are $size bytes; at most $podCmdParamsMax fit in a CMD',
    );
  }
  return params.cast<String, Object?>();
}

/// What the GM sent (some of btn, bright, vol, tamper, reset, rev) as the
/// command's params.
Map<String, Object?> podParamsFromBody(Map<String, Object?> body, int rev) {
  final unknown = [
    for (final k in body.keys)
      if (k != 'rev' && !podKeys.contains(k)) k,
  ]..sort();
  if (unknown.isNotEmpty) {
    throw ControllerError(
      'unknown setting: ${unknown.join(', ')} (one of ${podKeys.join(', ')})',
    );
  }
  if (!podKeys.any(body.containsKey)) {
    throw ControllerError(
      'nothing to set: give at least one of ${podKeys.join(', ')}',
    );
  }
  return checkPodParams({
    'v': podConfigVersion,
    'rev': body['rev'] ?? rev,
    for (final k in podKeys)
      if (body.containsKey(k)) k: body[k],
  });
}

/// The pod's side, as pod_settings.c does it: the reference the shared
/// vectors (protocol/vectors/pod_config.json) are made with.
class PodSettingsModel {
  int rev = 0;
  final set = <String, Object?>{};

  /// applied, same, stale or refused (pod_config_result_t).
  String handle(Object? params) {
    final Map<String, Object?> p;
    try {
      p = checkPodParams(params);
    } on ControllerError {
      return 'refused';
    }
    final r = p['rev']! as int;
    if (r < rev) return 'stale';
    if (r == rev) return 'same';
    if (p['reset'] == true) set.clear();
    rev = r;
    for (final k in const ['btn', 'bright', 'vol', 'tamper']) {
      if (p.containsKey(k)) set[k] = p[k];
    }
    return 'applied';
  }

  /// The stored form (pod_settings_to_json): keys in this order.
  String stored() => jsonEncode({
    'v': podConfigVersion,
    'rev': rev,
    for (final k in const ['btn', 'bright', 'vol', 'tamper'])
      if (set.containsKey(k)) k: set[k],
  });
}

class ControllerPodConfig {
  ControllerPodConfig(this.engine) {
    engine
      ..podConfig = this
      ..addListener(onMessage);
  }

  final ControllerEngine engine;

  /// Node id -> the latest push sent to it.
  final pushes = <int, Map<String, Object?>>{};

  double _now() => engine.wallSeconds();

  /// Seconds since 1970, and above the last rev sent to the node: a pod keeps
  /// the last rev it took in its flash, so a controller that restarted (and
  /// forgot) must still go above it.
  int _nextRev(int nodeId) {
    final last = (pushes[nodeId]?['rev'] as int?) ?? 0;
    final now = _now().floor();
    return now > last ? now : last + 1;
  }

  /// The phones of the live game: the only nodes an I/O pod can serve (their
  /// HELLO says platform android; whether one has a pod is not in it, the
  /// pod's answer tells).
  List<Map<String, Object?>> candidates() => [
    for (final n in engine.nodes())
      if (n['platform'] == _platformAndroid)
        {'node_id': n['node_id'], 'name': n['name'], 'link': n['link']},
  ];

  Map<String, Object?> push(Object? nodeId, Map<String, Object?> body) {
    if (nodeId is! int || nodeId < 1 || nodeId > 0xFFFE) {
      throw ControllerError(
        "node id: 1-65534 (a pod's settings are never broadcast)",
      );
    }
    final g = engine.liveGame;
    if (g == null) {
      throw ControllerError.conflict(
        "no live game: the pod's phone must be joined to one",
      );
    }
    if (g['state'] != 'ready' && g['state'] != 'ended') {
      throw ControllerError.conflict(
        "game ${g['id']} is ${g['state']}: pod settings only before a game "
        'starts or after it ended',
      );
    }
    if (!candidates().any((n) => n['node_id'] == nodeId)) {
      throw ControllerError.notFound(
        'node $nodeId is not a phone of this game (only a phone has an I/O '
        'pod)',
      );
    }
    final params = podParamsFromBody(body, _nextRev(nodeId));
    final seq = engine.sendPodConfig(nodeId, params);
    final now = _now();
    final push = {
      'node_id': nodeId,
      'game': g['id'],
      'rev': params['rev'],
      'settings': {
        for (final e in params.entries)
          if (e.key != 'v' && e.key != 'rev') e.key: e.value,
      },
      'state': 'sent',
      'tries': 1,
      'seq': seq,
      'sent_at': now,
      'updated_at': now,
      'next_at': now + podResendS.first,
    };
    pushes[nodeId] = push;
    _emit();
    return _public(push);
  }

  Map<String, Object?> status() => {
    'colours': podColours,
    'buttons': podButtons,
    'nodes': candidates(),
    'pushes': [
      for (final id in (pushes.keys.toList()..sort())) _public(pushes[id]!),
    ],
  };

  /// Stops waiting for the answers (and resending).
  List<int> cancel() {
    final nodes = [
      for (final e in pushes.entries)
        if (e.value['state'] == 'sent') e.key,
    ]..sort();
    for (final n in nodes) {
      pushes[n]!
        ..['state'] = 'cancelled'
        ..['updated_at'] = _now();
    }
    if (nodes.isNotEmpty) _emit();
    return nodes;
  }

  static Map<String, Object?> _public(Map<String, Object?> p) => {
    for (final k in const [
      'node_id',
      'rev',
      'settings',
      'state',
      'tries',
      'sent_at',
      'updated_at',
    ])
      k: p[k],
  };

  /// node.setup_applied (kind pod_config, rev) from the node: the pod took it.
  void onMessage(Map<String, Object?> msg) {
    final ev = msg['event'];
    if (msg['type'] != 'event' || ev is! Map) return;
    final data = (ev['data'] as Map?) ?? const {};
    if (ev['type'] != 'node.setup_applied' || data['kind'] != podKind) return;
    final p = pushes[ev['node']];
    if (p == null ||
        !(p['state'] == 'sent' || p['state'] == 'no_answer') ||
        data['rev'] != p['rev']) {
      return;
    }
    p
      ..['state'] = 'applied'
      ..['updated_at'] = _now();
    _emit();
  }

  /// The next sending of every push still waiting, or its end.
  void tick() {
    final now = _now();
    var changed = false;
    for (final p in pushes.values) {
      if (p['state'] != 'sent' || now < (p['next_at']! as double)) continue;
      final tries = p['tries']! as int;
      if (tries > podResendS.length) {
        // The first sending and five repeats are done.
        p
          ..['state'] = 'no_answer'
          ..['updated_at'] = now;
        changed = true;
        continue;
      }
      try {
        final seq = engine.sendPodConfig(p['node_id']! as int, {
          'v': podConfigVersion,
          'rev': p['rev'],
          ...(p['settings']! as Map<String, Object?>),
        });
        p
          ..['seq'] = seq
          ..['sent_at'] = now;
      } on ControllerError catch (e) {
        if (e.status != 503) {
          // The game moved on.
          p
            ..['state'] = 'cancelled'
            ..['updated_at'] = now;
          changed = true;
          continue;
        } // The radio is down: the next wait tries again.
      }
      p
        ..['tries'] = tries + 1
        ..['next_at'] =
            now +
            podResendS[tries < podResendS.length
                ? tries
                : podResendS.length - 1];
    }
    if (changed) _emit();
  }

  void _emit() =>
      engine.emit({'type': 'pod_config', 'pushes': status()['pushes']});
}
