// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Boxes' modules and outputs on the Android controller (draft RFC "The
/// expansion port", increment 3): the Pi's
/// controller/atalaia_controller/outputs.py, with the same answers, checked by
/// the shared contract cases (protocol/vectors/controller_api.json).
///
/// - **Modules** (EXP-21, EXP-36): the last `node.modules` of each box,
///   parsed into `[{address, model, fw, caps, feedback}]` (the simulator's
///   `atalaia_sim.expansion.parse_modules`); `node.module_lost` marks the
///   module it names `"lost": true` until the box's next `node.modules`.
/// - **The capability start check** (EXP-21, Q11): a joined node's role
///   `requires:` a capability it lacks: missing; an `optional:` one: a
///   warning. `team_input` and `team_display` are met by the types of
///   protocol/schema/capabilities.yaml's `role_names`; any other name that is
///   not a type is never checked. Only nodes whose HELLO lists a type this
///   controller knows are checked; an enabled simple output counts as present
///   and is named "not checked".
/// - **CMD 12** (EXP-23, EXP-27, EXP-30): the params a GM's request or a field
///   script's `field.send(node, "output", {...})` become, checked as a box
///   checks them (`output_params_problem`), `src` set by the controller, and
///   at most one start to a node every 2 s (off never held back).
library;

import '../protocol/capability_types.g.dart';

/// CMD 12 to one node at most this often (EXP-30); off is never held back.
const outputGapMs = 2000;

/// A GM's on or pulse without ms (EXP-27: "default 5 s").
const gmDefaultMs = 5000;

/// The `output` capability type's id in HELLO.
final int outputTypeId = capabilityTypeIds['output']!;

const _modulesTextMax = 100;
final _capId = RegExp(r'^[a-z0-9._-]{1,23}$');
final _module = RegExp(
  r'^(5[89a-f]):([a-z0-9][a-z0-9_-]{0,15})/(\d{1,3}\.\d{1,3}\.\d{1,3}):(.+)$',
);
final _simple = RegExp(r'^g(\d{1,2}):servo:([^,:;/]+)$');

/// node.modules' text (entries joined by ';': a module
/// `<address hex>:<model>/<version>:<caps>` or a simple output
/// `g<gpio>:servo:<function>`); throws [FormatException] if not well formed
/// (simulator/atalaia_sim/expansion.py `parse_modules`).
List<Map<String, Object?>> parseModules(String text) {
  if (_utf8Length(text) > _modulesTextMax) {
    throw const FormatException('longer than 100 bytes');
  }
  if (text.isEmpty) return [];
  final out = <Map<String, Object?>>[];
  final seen = <String>{};
  for (final entry in text.split(';')) {
    final m = _module.firstMatch(entry);
    final s = _simple.firstMatch(entry);
    String address;
    String model;
    String? fw;
    List<String> caps;
    if (m != null) {
      address = m.group(1)!;
      model = m.group(2)!;
      fw = m.group(3);
      caps = m.group(4)!.split(',');
    } else if (s != null && int.parse(s.group(1)!) <= 48) {
      address = 'g${int.parse(s.group(1)!)}';
      model = 'servo';
      fw = null;
      caps = [s.group(2)!];
    } else {
      throw FormatException('not a module or a simple output: $entry');
    }
    if (!caps.every(_capId.hasMatch)) {
      throw FormatException('bad capability id in $entry');
    }
    if (!seen.add(address)) throw FormatException('$address twice');
    out.add({
      'address': address,
      'model': model,
      'fw': fw,
      'caps': caps,
      'feedback': fw != null,
    });
  }
  return out;
}

int _utf8Length(String s) {
  var n = 0;
  for (final r in s.runes) {
    n += r < 0x80
        ? 1
        : r < 0x800
        ? 2
        : r < 0x10000
        ? 3
        : 4;
  }
  return n;
}

const outputActs = ['on', 'off', 'pulse', 'pattern'];

bool _intIn(Map<String, Object?> p, String key, int lo, int hi) {
  final v = p[key];
  return v is int && v >= lo && v <= hi;
}

/// Null when a box takes these CMD 12 params, else why it refuses them;
/// unknown keys are ignored (expansion.py `output_params_problem`,
/// protocol/vectors/cmd.json's output_params).
String? outputParamsProblem(Object? params) {
  if (params is! Map) return 'params is a map';
  final p = params.cast<String, Object?>();
  final cap = p['capability'];
  if (cap is! String) return 'capability is required';
  if (cap != '*' && !_capId.hasMatch(cap)) {
    return 'a capability id is 1-23 bytes of a-z 0-9 . _ -';
  }
  final act = p['act'];
  if (!outputActs.contains(act)) return 'act is on, off, pulse or pattern';
  if (p['src'] != 'field' && p['src'] != 'gm') return 'src is field or gm';
  if (cap == '*' && act != 'off') return '* only with off';
  if (act == 'off') return null;
  if (!p.containsKey('ms')) return 'ms is required for on, pulse and pattern';
  if (p['ms'] is! int) return 'ms is an integer';
  if (!_intIn(p, 'ms', 1, 600000)) return 'ms is 1 to 600000';
  if (act == 'pattern') {
    if (!p.containsKey('on_ms') || !p.containsKey('off_ms')) {
      return 'on_ms and off_ms are required for pattern';
    }
    if (!(_intIn(p, 'on_ms', 10, 10000) && _intIn(p, 'off_ms', 10, 10000))) {
      return 'on_ms and off_ms are 10 to 10000';
    }
  }
  return null;
}

/// node.modules' text as the node list's `modules`; null if not well formed.
List<Map<String, Object?>>? modulesOf(Object? text) {
  if (text is! String) return null;
  try {
    return parseModules(text);
  } on FormatException {
    return null;
  }
}

/// [modules] with the module(s) a node.module_lost names marked `lost`; null
/// when nothing changed.
List<Map<String, Object?>>? markLost(
  List<Map<String, Object?>>? modules,
  Object? text,
) {
  final gone = modulesOf(text);
  if (modules == null || modules.isEmpty || gone == null || gone.isEmpty) {
    return null;
  }
  final addresses = {for (final m in gone) m['address']};
  if (!modules.any((m) => addresses.contains(m['address']))) return null;
  return [
    for (final m in modules)
      addresses.contains(m['address']) ? {...m, 'lost': true} : m,
  ];
}

/// The capability types a HELLO lists, by name; unknown ids are left out.
Set<String> typesOf(Object? capabilities) {
  if (capabilities is! List) return {};
  return {
    for (final c in capabilities)
      if (c is int && capabilityTypeName(c) != null) capabilityTypeName(c)!,
  };
}

/// Whether a node with these types has the role's capability [name]; null
/// when the name is neither a type nor a role name (never checked).
bool? hasCapability(Set<String> types, String name) {
  if (capabilityTypeIds.containsKey(name)) return types.contains(name);
  final metBy = capabilityRoleNames[name];
  if (metBy == null) return null;
  return metBy.any(types.contains);
}

List<Map<String, Object?>> _mods(Object? modules) => [
  if (modules is List)
    for (final m in modules)
      if (m is Map) m.cast<String, Object?>(),
];

List<String> _caps(Map<String, Object?> m) => [
  if (m['caps'] is List)
    for (final c in m['caps']! as List) '$c',
];

/// The functions of a node's simple outputs (no feedback).
List<String> simpleOutputs(Object? modules) => [
  for (final m in _mods(modules))
    if (m['feedback'] == false) ..._caps(m),
];

/// Every capability a node's modules list (lost ones left out).
Set<String> outputCaps(Object? modules) => {
  for (final m in _mods(modules))
    if (m['lost'] != true) ..._caps(m),
};

List<String> _names(Object? value) => [
  if (value is List)
    for (final v in value)
      if (v is String) v,
];

/// The capability part of the start check for the joined nodes, each
/// `{node, name, role, capabilities, modules}` (outputs.py `check_nodes`).
Map<String, List<Map<String, Object?>>> checkNodes(
  Iterable<Map<String, Object?>> nodes,
  Object? Function(String role) roleSpec,
) {
  final missing = <Map<String, Object?>>[];
  final warnings = <Map<String, Object?>>[];
  final unchecked = <Map<String, Object?>>[];
  for (final n in nodes) {
    final who = {'node': n['node'], 'name': n['name'], 'role': n['role']};
    for (final fn in simpleOutputs(n['modules'])) {
      unchecked.add({
        ...who,
        'capability': fn,
        'text': '$fn on ${n['name']}: not checked (simple output)',
      });
    }
    final types = typesOf(n['capabilities']);
    final spec = roleSpec('${n['role']}');
    if (types.isEmpty || spec is! Map) continue;
    for (final name in _names(spec['requires'])) {
      if (hasCapability(types, name) == false) {
        missing.add({...who, 'capability': name});
      }
    }
    final lacking = [
      for (final name in _names(spec['optional']))
        if (hasCapability(types, name) == false) name,
    ];
    if (lacking.isNotEmpty) {
      warnings.add({
        'code': 'optional_caps',
        ...who,
        'capabilities': lacking,
        'text': '${n['name']} (${n['role']}) has no ${lacking.join(', ')}',
      });
    }
  }
  return {
    'missing_caps': missing,
    'warnings': warnings,
    'not_checked': unchecked,
  };
}

/// CMD 12's params from a request or a field script's table: `(params,
/// null)` or `(null, why not)`. [src] is the controller's (`gm` or `field`).
(Map<String, Object?>?, String?) outputParams(Object? spec, String src) {
  if (spec is! Map) {
    return (
      null,
      'the output request is a map: capability, act, ms, on_ms, off_ms',
    );
  }
  var params = <String, Object?>{
    for (final k in ['capability', 'act', 'ms', 'on_ms', 'off_ms'])
      if (spec.containsKey(k)) k: spec[k],
  };
  if (src == 'gm' &&
      ['on', 'pulse', 'pattern'].contains(params['act']) &&
      !params.containsKey('ms')) {
    params['ms'] = gmDefaultMs;
  }
  if (params['act'] == 'off') {
    params = {
      for (final e in params.entries)
        if (e.key == 'capability' || e.key == 'act') e.key: e.value,
    };
  } else if (params['act'] != 'pattern') {
    params
      ..remove('on_ms')
      ..remove('off_ms');
  }
  params['src'] = src;
  final problem = outputParamsProblem(params);
  return problem == null ? (params, null) : (null, problem);
}

/// At most one CMD 12 that starts an output to a node every [outputGapMs];
/// off goes always.
class OutputRateLimit {
  final _last = <int, int>{};

  /// 0 when a CMD 12 with this act may go to the node now, else how long
  /// until it may.
  int waitMs(int nodeId, String act, int nowMs) {
    final last = _last[nodeId];
    if (act == 'off' || last == null) return 0;
    final wait = last + outputGapMs - nowMs;
    return wait > 0 ? wait : 0;
  }

  void sent(int nodeId, String act, int nowMs) {
    if (act != 'off') _last[nodeId] = nowMs;
  }

  void clear() => _last.clear();
}
