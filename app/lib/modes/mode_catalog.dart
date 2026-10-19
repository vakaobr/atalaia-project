// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The modes an Android prop can run: the built-in modes of modes/ (the
/// same as a Field Box's), their manifests (mode.yaml), scripts and screen
/// templates, and a main mode composed with modifiers (Codes), as the
/// simulator's mode.py and the field controller do it (modes/README.md).
library;

import 'dart:convert';

import 'package:yaml/yaml.dart';

import '../ui/template/screen_template.dart';
import 'builtin_modes.g.dart';

class ModeException implements Exception {
  ModeException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// YAML maps and lists as plain Dart ones.
Object? plainYaml(Object? v) => switch (v) {
  YamlMap() => {for (final e in v.entries) '${e.key}': plainYaml(e.value)},
  YamlList() => [for (final e in v) plainYaml(e)],
  _ => v,
};

/// A parameter of a mode (mode.yaml `params`).
final class ModeParam {
  const ModeParam({
    required this.name,
    required this.type,
    this.min,
    this.max,
    this.defaultValue,
    this.optional = false,
    this.labels = const {},
  });

  final String name;

  /// int, bool, team or string.
  final String type;
  final num? min;

  /// For a string, the most bytes.
  final num? max;
  final Object? defaultValue;
  final bool optional;

  /// The label by language ("en" is the manifest's own).
  final Map<String, String> labels;

  bool get hasDefault => defaultValue != null;

  String label(String lang) => labels[lang] ?? labels['en'] ?? name;

  /// Why [value] is not acceptable for this parameter, or null.
  String? check(Object? value, List<String> teams) {
    switch (type) {
      case 'int':
        if (value is! int) return 'an integer';
        if (min != null && value < min!) return 'at least $min';
        if (max != null && value > max!) return 'at most $max';
      case 'bool':
        if (value is! bool) return 'true or false';
      case 'team':
        if (value is! String || !teams.contains(value)) {
          return "one of the game's teams";
        }
      case 'string':
        if (value is! String) return 'text';
        if (max != null && utf8.encode(value).length > max!) {
          return 'at most $max bytes';
        }
      default:
        return 'of an unknown type $type';
    }
    return null;
  }
}

/// What a role needs and may use (mode.yaml `roles`).
final class ModeRole {
  const ModeRole(this.name, this.requires, this.optional);
  final String name;
  final List<String> requires;
  final List<String> optional;

  bool uses(String capability) =>
      requires.contains(capability) || optional.contains(capability);
}

final class ModeManifest {
  ModeManifest({
    required this.folder,
    required this.id,
    required this.version,
    required this.kind,
    required this.names,
    required this.descriptions,
    required this.roles,
    required this.params,
    required this.nodeScript,
    required this.fieldScript,
    required this.screens,
  });

  final String folder;
  final String id;
  final String version;

  /// mode or modifier.
  final String kind;
  final Map<String, String> names;
  final Map<String, String> descriptions;
  final List<ModeRole> roles;
  final List<ModeParam> params;
  final String nodeScript;

  /// The controller's script, for modes that span several boxes.
  final String? fieldScript;

  /// The screen templates by name (`assets/screens/<name>.yaml`).
  final Map<String, String> screens;

  bool get isModifier => kind == 'modifier';

  /// Modes with a field.lua need the field controller (Hold-All, Last
  /// Stand): a prop on its own cannot score them.
  bool get needsController => fieldScript != null;

  String name(String lang) => names[lang] ?? names['en'] ?? id;
  String description(String lang) =>
      descriptions[lang] ?? descriptions['en'] ?? '';

  ModeRole? role(String name) {
    for (final r in roles) {
      if (r.name == name) return r;
    }
    return null;
  }

  static ModeManifest parse(String folder, Map<String, String> files) {
    final text = files['mode.yaml'];
    if (text == null) throw ModeException('$folder: no mode.yaml');
    final m = plainYaml(loadYaml(text)) as Map<String, Object?>? ?? {};
    for (final key in ['id', 'version', 'roles']) {
      if (!m.containsKey(key)) {
        throw ModeException("$folder/mode.yaml: missing '$key'");
      }
    }
    final node = files['node.lua'];
    if (node == null) throw ModeException('$folder: no node.lua');
    final i18n = (m['i18n'] as Map<String, Object?>?) ?? const {};
    final names = <String, String>{'en': '${m['name'] ?? m['id']}'};
    final descriptions = <String, String>{'en': '${m['description'] ?? ''}'};
    final labels = <String, Map<String, String>>{};
    for (final e in i18n.entries) {
      final t = (e.value as Map<String, Object?>?) ?? const {};
      if (t['name'] != null) names[e.key] = '${t['name']}';
      if (t['description'] != null) descriptions[e.key] = '${t['description']}';
      final p = (t['params'] as Map<String, Object?>?) ?? const {};
      for (final pe in p.entries) {
        (labels[pe.key] ??= {})[e.key] = '${pe.value}';
      }
    }
    final roles = <ModeRole>[
      for (final e in ((m['roles'] as Map<String, Object?>?) ?? {}).entries)
        ModeRole(
          e.key,
          [
            for (final c
                in ((e.value as Map?)?['requires'] as List?) ?? const [])
              '$c',
          ],
          [
            for (final c
                in ((e.value as Map?)?['optional'] as List?) ?? const [])
              '$c',
          ],
        ),
    ];
    final params = <ModeParam>[
      for (final e in ((m['params'] as Map<String, Object?>?) ?? {}).entries)
        _param(e.key, (e.value as Map<String, Object?>?) ?? const {}, {
          'en': '${(e.value as Map?)?['label'] ?? e.key}',
          ...?labels[e.key],
        }),
    ];
    final screens = <String, String>{
      for (final e in files.entries)
        if (e.key.startsWith('assets/screens/') && e.key.endsWith('.yaml'))
          e.key.substring(15, e.key.length - 5): e.value,
    };
    return ModeManifest(
      folder: folder,
      id: '${m['id']}',
      version: '${m['version']}',
      kind: '${m['kind'] ?? 'mode'}',
      names: names,
      descriptions: descriptions,
      roles: roles,
      params: params,
      nodeScript: node,
      fieldScript: files['field.lua'],
      screens: screens,
    );
  }

  static ModeParam _param(
    String name,
    Map<String, Object?> spec,
    Map<String, String> labels,
  ) => ModeParam(
    name: name,
    type: '${spec['type']}',
    min: spec['min'] as num?,
    max: spec['max'] as num?,
    defaultValue: spec['default'],
    optional: spec['optional'] == true,
    labels: labels,
  );
}

/// A main mode with its modifiers, ready to run: one id, one parameter
/// list, one script, the screens of all of them (the main mode's first).
final class GameMode {
  GameMode(this.main, this.modifiers);

  final ModeManifest main;
  final List<ModeManifest> modifiers;

  List<ModeManifest> get parts => [main, ...modifiers];

  String get id => parts.map((m) => m.id).join('+');

  String name(String lang) => parts.map((m) => m.name(lang)).join(' + ');

  List<ModeParam> get params => [for (final m in parts) ...m.params];

  /// One Lua chunk: each part in its own block when there are modifiers.
  String get nodeScript => modifiers.isEmpty
      ? main.nodeScript
      : parts.map((m) => 'do\n${m.nodeScript}\nend\n').join();

  String get chunkName => '@${main.folder}/node.lua';

  /// The template for a screen name, from the first part that has it.
  String? screen(String name) {
    for (final m in parts) {
      final s = m.screens[name];
      if (s != null) return s;
    }
    return null;
  }

  /// The defaults plus [overrides], checked; throws [ModeException].
  Map<String, Object?> resolveParams(
    Map<String, Object?> overrides,
    List<String> teams,
  ) {
    final known = {for (final p in params) p.name};
    final unknown = overrides.keys.where((k) => !known.contains(k)).toList();
    if (unknown.isNotEmpty) {
      throw ModeException('$id: unknown parameter(s) $unknown');
    }
    final out = <String, Object?>{};
    for (final p in params) {
      final Object? value;
      if (overrides.containsKey(p.name) && overrides[p.name] != null) {
        value = overrides[p.name];
      } else if (p.hasDefault) {
        value = p.defaultValue;
      } else if (p.optional) {
        continue;
      } else {
        throw ModeException("$id: parameter '${p.name}' has no value");
      }
      final why = p.check(value, teams);
      if (why != null) {
        throw ModeException("$id: parameter '${p.name}' must be $why");
      }
      out[p.name] = value;
    }
    return out;
  }
}

class ModeCatalog {
  ModeCatalog(this.modes);

  /// The modes built into the app (modes/ at build time).
  factory ModeCatalog.builtin() => ModeCatalog([
    for (final e in builtinModeFiles.entries)
      ModeManifest.parse(e.key, e.value),
  ]);

  final List<ModeManifest> modes;

  List<ModeManifest> get mainModes => [
    for (final m in modes)
      if (!m.isModifier) m,
  ];

  List<ModeManifest> get modifiers => [
    for (final m in modes)
      if (m.isModifier) m,
  ];

  ModeManifest? byId(String id) {
    for (final m in modes) {
      if (m.id == id) return m;
    }
    return null;
  }

  /// A main mode and modifiers by id ("main+modifier+..."); throws
  /// [ModeException] for an unknown or misplaced part.
  GameMode compose(String id) {
    final parts = id.split('+');
    final main = byId(parts.first);
    if (main == null) throw ModeException('unknown mode ${parts.first}');
    // A modifier may run on its own (Codes alone is a code terminal), but
    // not as the main mode of others.
    if (main.isModifier && parts.length > 1) {
      throw ModeException('${main.id} is a modifier; a game needs a main mode');
    }
    final mods = <ModeManifest>[];
    final names = {for (final p in main.params) p.name};
    for (final p in parts.skip(1)) {
      final m = byId(p);
      if (m == null) throw ModeException('unknown modifier $p');
      if (!m.isModifier) throw ModeException('$p is a main mode');
      if (mods.contains(m)) throw ModeException('$p is named twice');
      for (final param in m.params) {
        if (!names.add(param.name)) {
          throw ModeException('$p and ${main.id} both have ${param.name}');
        }
      }
      mods.add(m);
    }
    return GameMode(main, mods);
  }

  /// Every screen template of every mode parses (the tests check it).
  Map<String, String?> screenProblems() => {
    for (final m in modes)
      for (final e in m.screens.entries)
        '${m.folder}/${e.key}': screenTemplateError(e.value),
  };
}
