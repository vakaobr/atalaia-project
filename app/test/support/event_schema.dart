// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// protocol/schema/events.yaml, for the mode tests' checks: the Dart side of
/// `schema_problems` and `default_prio` in simulator/atalaia_sim/codec.py.
library;

import 'dart:io';

import 'package:atalaia_app/core/node_types.dart';
import 'package:yaml/yaml.dart';

/// Custom events are named `x.<club>.<name>` (protocol/schema/events.yaml).
final _custom = RegExp(r'^x\.[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+$');

class EventSchema {
  EventSchema._(this._events, this._fields);

  factory EventSchema.load([String path = '../protocol/schema/events.yaml']) {
    final doc = loadYaml(File(path).readAsStringSync()) as YamlMap;
    final events = <String, ({String prio, List<String> data})>{};
    (doc['events'] as YamlMap).forEach((name, spec) {
      final s = spec as YamlMap;
      events[name as String] = (
        prio: s['prio'] as String,
        data: (s['data'] as YamlList).cast<String>().toList(),
      );
    });
    final fields = <String, ({String type, bool common})>{};
    (doc['data_fields'] as YamlMap).forEach((name, spec) {
      final s = spec as YamlMap;
      fields[name as String] = (
        type: s['type'] as String,
        common: s['common'] == true,
      );
    });
    return EventSchema._(events, fields);
  }

  final Map<String, ({String prio, List<String> data})> _events;
  final Map<String, ({String type, bool common})> _fields;

  bool isStandard(String type) => _events.containsKey(type);

  /// The schema's priority for a standard event; normal for custom ones.
  int defaultPrio(String type) =>
      prioNames.indexOf(_events[type]?.prio ?? 'normal');

  static bool _typeOk(String type, Object? v) => switch (type) {
    'string' => v is String,
    'integer' => v is int,
    'number' => v is num,
    'boolean' => v is bool,
    _ => false,
  };

  /// What is wrong with an event's type and data, by the schema.
  List<String> problems(String type, Map<String, Object?> data) {
    final ev = _events[type];
    if (ev == null) {
      if (_custom.hasMatch(type)) return const [];
      return [
        "'$type' is not a standard event; custom events are named x.<club>.<name>",
      ];
    }
    final out = <String>[];
    data.forEach((k, v) {
      final field = _fields[k];
      if (field == null || !(field.common || ev.data.contains(k))) {
        final allowed = [
          for (final e in _fields.entries)
            if (e.value.common) e.key,
          ...ev.data,
        ];
        out.add(
          "'$type' has no data field '$k' (allowed: ${allowed.join(', ')})",
        );
      } else if (!_typeOk(field.type, v)) {
        out.add("'$type' data field '$k' must be a ${field.type}, got $v");
      }
    });
    return out;
  }
}
