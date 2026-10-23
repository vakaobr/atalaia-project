// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The Android field controller's mode packages and presets (slice S7b of
/// PE24): the Dart counterpart of the Pi controller's
/// controller/atalaia_controller/modes.py and of the simulator's mode
/// composition (simulator/atalaia_sim/mode.py `compose`), with the presets
/// of the Pi's store.
///
/// A package is a main mode, a modifier (`kind: modifier`), a role package
/// (`kind: role`: the Medic Kit, the objectives package) or a scenario
/// (`kind: scenario`, decision P4R7: a field.lua and no node.lua, uploaded
/// only, never built in). A game or a preset names a main mode and its other
/// parts with one id joined by `+` (`org.atalaia.domination+org.atalaia.codes+org.atalaia.medic`),
/// a scenario first (`org.club.foxhound+org.atalaia.objectives`);
/// [ControllerModes.get] composes them ([composeModes]): the main mode's
/// roles run the main mode's and the modifiers' scripts, each role
/// package's roles run that package alone, and the field scripts of every
/// part run together on the controller. A box's join names only what that
/// box runs ([ControllerMode.nodeModeId]), never a scenario.
///
/// The built-in packages are the app's (modes/ at build time, the same as a
/// Pi's); uploads ([ControllerModes.install]: `POST /api/v1/modes`, signed
/// packages, compiled scenarios) are checked as on the Pi: the manifest must
/// parse and name its id, version and roles, and the scripts must load in
/// the real core, so a typo is caught at upload and not on the field. They
/// are kept in the store's `modes` document (the files, a signed package's
/// release and its archive exactly as signed, in base64), the presets in its
/// `presets` document (decision PE24-80).
///
/// mode.yaml is read with package:yaml (YAML 1.2) where the Pi uses PyYAML
/// (YAML 1.1): a manifest that only YAML 1.1 reads as the Pi does (`yes` as
/// true, a key given twice) may be read differently or refused here
/// (PE24-80); the scenario compiler's own loader follows YAML 1.1
/// (scenarios/scenario_manifest.dart).
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:yaml/yaml.dart';

import '../core/node_types.dart';
import '../ffi/bindings.dart';
import '../ffi/callbacks.dart';
import '../ffi/core_node.dart';
import '../modes/builtin_modes.g.dart';
import '../modes/mode_catalog.dart';
import 'controller_store.dart';

/// The kinds of package (atalaia_sim.mode KINDS).
const packageKinds = ['mode', 'modifier', 'role', 'scenario'];

/// The joined ids of a game's parts (atalaia_sim.mode SEPARATOR).
const modeSeparator = '+';

/// A game's whole id in a join payload: 63 bytes at most.
const composedIdMax = 63;

/// What an upload may weigh (modes.py MAX_PACKAGE_BYTES, decision P5-6).
const uploadMaxBytes = 1000000;

// Python's `re.match` with `$` also takes a final line feed: kept, so that
// both controllers accept the same names (modes.py `_FILE_NAME`, `_MODE_ID`).
final _fileName = RegExp(
  r'^(mode\.yaml|node\.lua|field\.lua|assets/[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*)\n?$',
);
final _modeId = RegExp(r'^[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+\n?$');
final _commandName = RegExp(r'^[a-z][a-z0-9_]{0,23}\n?$');

/// A role package inside a composed game: the nodes with one of its roles
/// run it alone (atalaia_sim.mode `RolePart`).
final class RolePart {
  const RolePart(this.id, this.nodeScript, this.chunkName, this.paramNames);
  final String id;
  final String nodeScript;
  final String chunkName;
  final List<String> paramNames;
}

/// A mode as the controller runs it: one package, or a main mode composed
/// with its other parts (atalaia_sim.mode `Mode`).
final class ControllerMode {
  ControllerMode({
    required this.folder,
    required this.id,
    required this.name,
    required this.version,
    required this.roles,
    required this.params,
    required this.nodeScript,
    this.fieldScript,
    this.kind = 'mode',
    this.description = '',
    this.i18n = const {},
    this.parts = const [],
    this.commands = const {},
    this.roleParts = const {},
    this.mainId = '',
    this.scenarioParams = const {},
  });

  /// The package's folder name (the chunk names' `@folder/node.lua`).
  final String folder;
  final String id;
  final String name;
  final String version;

  /// Role name to its manifest entry (`requires`, `optional`, `needed`).
  final Map<String, Object?> roles;

  /// Parameter name to its schema.
  final Map<String, Map<String, Object?>> params;
  final String nodeScript;
  final String? fieldScript;
  final String kind;
  final String description;
  final Map<String, Object?> i18n;

  /// A composed mode's parts, in order (empty for one package).
  final List<String> parts;
  final Map<String, Object?> commands;

  /// Role to the role package its nodes run.
  final Map<String, RolePart> roleParts;

  /// What the main mode's roles run (main mode and modifiers).
  final String mainId;

  /// A scenario's parameters: only its field.lua reads them.
  final Set<String> scenarioParams;

  /// The mode id a node with [role] is given in its join: what it runs.
  String nodeModeId(String role) =>
      roleParts[role]?.id ?? (mainId.isNotEmpty ? mainId : id);

  /// The game's parameters a node with [role] runs with (its join's).
  Map<String, Object?> paramsFor(String role, Map<String, Object?> params) {
    if (roleParts.isEmpty) return Map.of(params);
    final part = roleParts[role];
    if (part != null) {
      return {
        for (final e in params.entries)
          if (part.paramNames.contains(e.key)) e.key: e.value,
      };
    }
    final others = {
      for (final p in roleParts.values) ...p.paramNames,
      ...scenarioParams,
    };
    return {
      for (final e in params.entries)
        if (!others.contains(e.key)) e.key: e.value,
    };
  }

  /// Parameters only staff may read (manifest `gm_only: true`, M5-1).
  Set<String> get gmOnlyParams => {
    for (final e in params.entries)
      if (e.value['gm_only'] == true) e.key,
  };

  /// A game's parameters without the gm_only ones.
  Map<String, Object?> publicParams(Map<String, Object?> values) {
    final hidden = gmOnlyParams;
    return {
      for (final e in values.entries)
        if (!hidden.contains(e.key)) e.key: e.value,
    };
  }

  /// Defaults plus [overrides], checked against the schema (Mode.resolve_params):
  /// an override given, even null, is checked as given.
  Map<String, Object?> resolveParams(
    Map<String, Object?> overrides,
    List<Object?> teams,
  ) {
    final unknown = overrides.keys.where((k) => !params.containsKey(k)).toList()
      ..sort();
    if (unknown.isNotEmpty) {
      throw ModeException('$id: unknown parameter(s) $unknown');
    }
    final out = <String, Object?>{};
    for (final e in params.entries) {
      final spec = e.value;
      final Object? value;
      if (overrides.containsKey(e.key)) {
        value = overrides[e.key];
      } else if (spec.containsKey('default')) {
        value = spec['default'];
      } else if (spec['optional'] == true) {
        continue;
      } else {
        throw ModeException("$id: parameter '${e.key}' has no value");
      }
      _checkParam(id, e.key, spec, value, teams);
      out[e.key] = value;
    }
    return out;
  }
}

void _checkParam(
  String modeId,
  String name,
  Map<String, Object?> spec,
  Object? value,
  List<Object?> teams,
) {
  final where = "$modeId: parameter '$name'";
  switch (spec['type']) {
    case 'int':
      if (value is! int) {
        throw ModeException('$where must be an integer, got $value');
      }
      final lo = spec['min'], hi = spec['max'];
      if (lo is num && value < lo) {
        throw ModeException('$where must be at least $lo');
      }
      if (hi is num && value > hi) {
        throw ModeException('$where must be at most $hi');
      }
    case 'bool':
      if (value is! bool) {
        throw ModeException('$where must be true or false, got $value');
      }
    case 'team':
      if (!teams.contains(value)) {
        throw ModeException(
          "$where must be one of the game's teams $teams, got $value",
        );
      }
    case 'string':
      if (value is! String) throw ModeException('$where must be text');
      final hi = spec['max'];
      if (hi is num && utf8.encode(value).length > hi) {
        throw ModeException('$where must be at most $hi bytes');
      }
    default:
      throw ModeException('$where has unknown type ${spec['type']}');
  }
}

/// Defaults plus overrides; without [teams] (a preset is not tied to team
/// names) a team parameter is only checked to be text (modes.py
/// `resolve_params`).
Map<String, Object?> resolvePresetParams(
  ControllerMode mode,
  Object? overrides,
  List<Object?>? teams,
) {
  if (overrides is! Map) throw ModeException('params must be a map');
  final o = overrides.cast<String, Object?>();
  final t =
      teams ??
      [
        for (final e in o.entries)
          if (mode.params[e.key]?['type'] == 'team' && e.value is String)
            e.value,
        for (final s in mode.params.values)
          if (s['type'] == 'team' && s['default'] is String) s['default'],
      ];
  return mode.resolveParams(o, t);
}

/// The optional parts of a manifest: kind, commands and i18n
/// (atalaia_sim.mode `check_manifest`).
void checkManifest(Map<String, Object?> manifest, String where) {
  final kind = manifest['kind'] ?? 'mode';
  if (!packageKinds.contains(kind)) {
    throw ModeException(
      '$where: kind must be one of ${packageKinds.join(', ')}, got $kind',
    );
  }
  if (kind == 'scenario') {
    if (_truthy(manifest['roles'])) {
      throw ModeException(
        '$where: a scenario has no roles: its nodes run role packages',
      );
    }
    if (_truthy(manifest['commands'])) {
      throw ModeException(
        '$where: a scenario has no commands: they are for the nodes\' roles',
      );
    }
  }
  final params = _truthy(manifest['params'])
      ? manifest['params']
      : const <String, Object?>{};
  if (params is! Map || params.values.any((s) => s is! Map)) {
    throw ModeException(
      '$where: params must map a parameter name to its schema',
    );
  }
  for (final e in params.entries) {
    final g = (e.value as Map)['gm_only'] ?? false;
    if (g is! bool) {
      throw ModeException(
        '$where: parameter ${e.key}: gm_only is true or false',
      );
    }
  }
  final commands = manifest['commands'];
  if (commands != null) {
    if (commands is! Map) {
      throw ModeException(
        '$where: commands must map a command name to its roles and label',
      );
    }
    final roles = _truthy(manifest['roles'])
        ? manifest['roles']
        : const <String, Object?>{};
    for (final e in commands.entries) {
      final name = e.key, spec = e.value;
      if (name is! String || !_commandName.hasMatch(name)) {
        throw ModeException(
          '$where: command $name: 1-24 of a-z, 0-9 and _, starting with a letter',
        );
      }
      final ok =
          spec is Map &&
          spec.keys.every((k) => k == 'roles' || k == 'label') &&
          spec['label'] is String &&
          spec['roles'] is List &&
          (spec['roles'] as List).isNotEmpty &&
          (spec['roles'] as List).every(
            (r) => r is String && roles is Map && roles.containsKey(r),
          );
      if (!ok) {
        throw ModeException(
          "$where: command $name needs a label and a list of the mode's roles",
        );
      }
    }
  }
  final i18n = manifest['i18n'];
  if (i18n == null) return;
  if (i18n is! Map) {
    throw ModeException('$where: i18n must map a language to its strings');
  }
  for (final e in i18n.entries) {
    final strings = e.value;
    if (e.key is! String || strings is! Map) {
      throw ModeException('$where: i18n.${e.key} must be a map of strings');
    }
    for (final s in strings.entries) {
      if (s.key == 'params' || s.key == 'commands') {
        final v = s.value;
        if (v is! Map ||
            !v.entries.every((x) => x.key is String && x.value is String)) {
          throw ModeException(
            '$where: i18n.${e.key}.${s.key} maps names to labels',
          );
        }
      } else if (s.key == 'name' || s.key == 'description') {
        if (s.value is! String) {
          throw ModeException('$where: i18n.${e.key}.${s.key} must be text');
        }
      } else {
        throw ModeException(
          '$where: i18n.${e.key} has an unknown key ${s.key}',
        );
      }
    }
  }
}

/// A scenario is a field.lua and no node.lua (P4R7); every other kind has a
/// node.lua (atalaia_sim.mode `check_files`).
void checkFiles(String kind, bool hasNode, bool hasField, String where) {
  if (kind == 'scenario') {
    if (hasNode) {
      throw ModeException(
        '$where: a scenario has no node.lua: its nodes run role packages',
      );
    }
    if (!hasField) throw ModeException('$where: a scenario needs a field.lua');
  } else if (!hasNode) {
    throw ModeException('$where: no node.lua');
  }
}

bool _truthy(Object? v) => switch (v) {
  null || false => false,
  final String s => s.isNotEmpty,
  final Map<Object?, Object?> m => m.isNotEmpty,
  final List<Object?> l => l.isNotEmpty,
  final num n => n != 0,
  _ => true,
};

String _str(Object? v) => switch (v) {
  null => 'None',
  true => 'True',
  false => 'False',
  final double d when d == d.truncateToDouble() && d.abs() < 1e16 =>
    d.toStringAsFixed(1),
  _ => '$v',
};

/// One package from its manifest and scripts (modes.py `parse_package`'s
/// Mode).
ControllerMode modeFromManifest(
  Map<String, Object?> manifest,
  String folder, {
  String? nodeScript,
  String? fieldScript,
}) {
  Map<String, Object?> map(Object? v) =>
      _truthy(v) && v is Map ? v.cast<String, Object?>() : const {};
  return ControllerMode(
    folder: folder,
    id: manifest['id']! as String,
    name: _str(manifest['name'] ?? manifest['id']),
    version: _str(manifest['version']),
    roles: map(manifest['roles']),
    params: {
      for (final e in map(manifest['params']).entries)
        e.key: (e.value! as Map).cast<String, Object?>(),
    },
    nodeScript: nodeScript ?? '',
    fieldScript: fieldScript,
    kind: '${manifest['kind'] ?? 'mode'}',
    description: manifest.containsKey('description')
        ? _str(manifest['description'])
        : '',
    i18n: map(manifest['i18n']),
    commands: map(manifest['commands']),
  );
}

/// A package's files: the manifest, its scripts and assets.
final class ModePackage {
  ModePackage(this.mode, this.files, {required this.builtin, this.signed});

  final ControllerMode mode;
  final Map<String, String> files;
  bool builtin;

  /// A signed package's release (signed_modes.dart), else null.
  Map<String, Object?>? signed;

  String get id => mode.id;
  String get kind => mode.kind;
  String? get fieldScript => mode.fieldScript;

  /// The package's mode.yaml, as plain maps.
  Map<String, Object?> get manifest {
    try {
      final m = plainYaml(loadYaml(files['mode.yaml'] ?? ''));
      return m is Map<String, Object?> ? m : const {};
    } on Object {
      return const {};
    }
  }

  /// GET /api/v1/modes' form (modes.py `to_api`).
  Map<String, Object?> toApi() => {
    'id': mode.id,
    'kind': mode.kind,
    'name': mode.name,
    'version': mode.version,
    'description': mode.description,
    'min_tier': manifest['min_tier'],
    'roles': mode.roles,
    'params': mode.params,
    'commands': mode.commands,
    'i18n': mode.i18n,
    'parts': mode.parts,
    'field_script': mode.fieldScript != null,
    'builtin': builtin,
    'files': files.keys.toList()..sort(),
    'signed': signed,
  };
}

/// A package from its files, checked (modes.py `parse_package`); throws
/// [ModeException].
ModePackage parseModePackage(Object? files, {String folder = '<upload>'}) {
  if (files is! Map || files.isEmpty) {
    throw ModeException('a mode package is a map of file names to their text');
  }
  var total = 0;
  final out = <String, String>{};
  for (final e in files.entries) {
    final name = e.key, text = e.value;
    if (name is! String || !_fileName.hasMatch(name) || name.contains('..')) {
      throw ModeException('file $name is not allowed in a mode package');
    }
    if (text is! String) throw ModeException('$name: files are text');
    total += name.runes.length + utf8.encode(text).length;
    out[name] = text;
  }
  if (total > uploadMaxBytes) {
    throw ModeException('the package is $total bytes; at most $uploadMaxBytes');
  }
  final yamlText = out['mode.yaml'];
  if (yamlText == null) throw ModeException('the package has no mode.yaml');
  Object? doc;
  try {
    doc = plainYaml(loadYaml(yamlText));
  } on YamlException catch (e) {
    throw ModeException('mode.yaml: ${e.message}');
  }
  doc ??= <String, Object?>{};
  if (doc is! Map) throw ModeException('mode.yaml must be a map');
  final manifest = doc.cast<String, Object?>();
  final kind = manifest['kind'] ?? 'mode';
  if (kind != 'scenario' && !out.containsKey('node.lua')) {
    throw ModeException('the package has no node.lua');
  }
  for (final key in ['id', 'version', if (kind != 'scenario') 'roles']) {
    if (!manifest.containsKey(key)) {
      throw ModeException("mode.yaml: missing '$key'");
    }
  }
  final id = manifest['id'];
  if (id is! String || !_modeId.hasMatch(id)) {
    throw ModeException('mode.yaml: id must look like org.club.name');
  }
  final roles = manifest['roles'];
  if (kind != 'scenario' && (roles is! Map || roles.isEmpty)) {
    throw ModeException('mode.yaml: roles must be a non-empty map');
  }
  final params = _truthy(manifest['params'])
      ? manifest['params']
      : const <String, Object?>{};
  if (params is! Map) throw ModeException('mode.yaml: params must be a map');
  checkManifest(manifest, 'mode.yaml');
  checkFiles(
    '$kind',
    out.containsKey('node.lua'),
    out.containsKey('field.lua'),
    'the package',
  );
  final mode = modeFromManifest(
    manifest,
    folder,
    nodeScript: out['node.lua'],
    fieldScript: out['field.lua'],
  );
  return ModePackage(mode, out, builtin: false);
}

String _composeScripts(List<String> scripts) => scripts.length == 1
    ? scripts.single
    : scripts.map((s) => 'do\n$s\nend\n').join();

/// A main mode with modifiers and role packages: one id, one parameter
/// schema (atalaia_sim.mode `compose`). A scenario leads the id and is
/// followed by at least one role package, optionally after one main mode
/// and its modifiers. Throws [ModeException].
ControllerMode composeModes(ControllerMode main, List<ControllerMode> rest) {
  ControllerMode? scenario;
  ControllerMode? lead;
  var modifiers = rest;
  if (main.kind == 'scenario') {
    scenario = main;
    if (modifiers.isEmpty) {
      throw ModeException(
        '${main.id} is a scenario: it needs a role package after it, such as '
        'org.atalaia.objectives',
      );
    }
    if (modifiers.first.kind == 'mode') {
      lead = modifiers.first;
      modifiers = modifiers.sublist(1);
    }
  } else {
    if (modifiers.isEmpty) return main;
    if (main.kind != 'mode') {
      throw ModeException(
        '${main.id} is a ${main.kind}; a game needs a main mode first',
      );
    }
    lead = main;
  }
  final leaders = [?scenario, ?lead];
  final seen = {for (final m in leaders) m.id};
  if (seen.length != leaders.length) {
    throw ModeException('${leaders.last.id} is named twice');
  }
  final params = <String, Map<String, Object?>>{};
  for (final m in leaders) {
    final clash = params.keys.where(m.params.containsKey).toList()..sort();
    if (clash.isNotEmpty) {
      throw ModeException(
        '${m.id} and ${leaders.first.id} both have the parameter(s) $clash',
      );
    }
    params.addAll(m.params);
  }
  final roles = <String, Object?>{...?lead?.roles};
  final commands = <String, Object?>{...?lead?.commands};
  final first = leaders.first;
  final mods = <ControllerMode>[];
  final roleParts = <String, RolePart>{};
  for (final mod in modifiers) {
    if (mod.kind == 'scenario') {
      throw ModeException(
        '${mod.id} is a scenario: a scenario leads the game\'s id',
      );
    }
    if (mod.kind == 'mode') {
      if (scenario != null) {
        throw ModeException(
          "${mod.id} is a main mode: a scenario's game has one, right after "
          'the scenario',
        );
      }
      throw ModeException('${mod.id} is a main mode, not a modifier');
    }
    if (!seen.add(mod.id)) throw ModeException('${mod.id} is named twice');
    var clash = params.keys.where(mod.params.containsKey).toList()..sort();
    if (clash.isNotEmpty) {
      throw ModeException(
        '${mod.id} and ${first.id} both have the parameter(s) $clash',
      );
    }
    params.addAll(mod.params);
    clash = commands.keys.where(mod.commands.containsKey).toList()..sort();
    if (clash.isNotEmpty) {
      throw ModeException(
        '${mod.id} and ${first.id} both have the command(s) $clash',
      );
    }
    commands.addAll(mod.commands);
    if (mod.kind == 'modifier') {
      if (lead == null) {
        throw ModeException(
          '${mod.id} is a modifier: it runs with a main mode, and this '
          "scenario's game has none",
        );
      }
      mods.add(mod);
      continue;
    }
    clash = roles.keys.where(mod.roles.containsKey).toList()..sort();
    if (clash.isNotEmpty) {
      throw ModeException(
        '${mod.id} and ${first.id} both have the role(s) $clash',
      );
    }
    roles.addAll(mod.roles);
    final part = RolePart(
      mod.id,
      mod.nodeScript,
      '@${mod.folder}/node.lua',
      mod.params.keys.toList(),
    );
    for (final role in mod.roles.keys) {
      roleParts[role] = part;
    }
  }
  if (scenario != null && roleParts.isEmpty) {
    throw ModeException(
      '${scenario.id} is a scenario: it needs a role package after it, such '
      'as org.atalaia.objectives',
    );
  }
  final parts = [...leaders, ...modifiers];
  final modeId = parts.map((m) => m.id).join(modeSeparator);
  if (utf8.encode(modeId).length > composedIdMax) {
    throw ModeException(
      '$modeId: a mode with its modifiers is named in at most $composedIdMax bytes',
    );
  }
  final runs = [?lead, ...mods];
  final fields = [
    for (final m in parts)
      if (m.fieldScript != null) m.fieldScript!,
  ];
  final langs = {for (final m in parts) ...m.i18n.keys}.toList()..sort();
  Map<String, Object?> texts(ControllerMode m, String lang) =>
      (m.i18n[lang] as Map?)?.cast<String, Object?>() ?? const {};
  final i18n = <String, Object?>{};
  for (final lang in langs) {
    final names = [for (final m in parts) texts(m, lang)['name'] ?? m.name];
    final labels = <String, Object?>{};
    final commandLabels = <String, Object?>{};
    for (final m in parts) {
      labels.addAll(
        (texts(m, lang)['params'] as Map?)?.cast<String, Object?>() ?? const {},
      );
      commandLabels.addAll(
        (texts(m, lang)['commands'] as Map?)?.cast<String, Object?>() ??
            const {},
      );
    }
    final entry = <String, Object?>{
      'name': names.join(' + '),
      'params': labels,
    };
    if (commandLabels.isNotEmpty) entry['commands'] = commandLabels;
    if (texts(first, lang).containsKey('description')) {
      entry['description'] = texts(first, lang)['description'];
    }
    i18n[lang] = entry;
  }
  return ControllerMode(
    folder: first.folder,
    id: modeId,
    name: parts.map((m) => m.name).join(' + '),
    version: first.version,
    roles: roles,
    params: params,
    nodeScript: runs.isEmpty
        ? ''
        : _composeScripts([for (final m in runs) m.nodeScript]),
    fieldScript: fields.isEmpty ? null : _composeScripts(fields),
    description: first.description,
    i18n: i18n,
    parts: [for (final m in parts) m.id],
    commands: commands,
    roleParts: roleParts,
    mainId: runs.map((m) => m.id).join(modeSeparator),
    scenarioParams: scenario == null ? const {} : scenario.params.keys.toSet(),
  );
}

class _NoField implements FieldOperations {
  @override
  List<Map<String, Object?>> nodes(String? role) => const [];
  @override
  String? owner(int nodeId) => null;
  @override
  bool send(int nodeId, String cmd, Map<String, Object?> params) => false;
}

/// Loads node.lua (a scenario has none) and field.lua in the core with the
/// default parameters (modes.py `check_scripts`); throws [ModeException].
void checkScripts(AtalaiaCore core, ModePackage pkg) {
  const teams = ['red', 'blue'];
  Map<String, Object?> params;
  try {
    params = pkg.mode.resolveParams(const {}, teams);
  } on ModeException {
    params = const {}; // parameters without defaults: load with none
  }
  void load(int nodeId, String source, String chunk, String what) {
    CoreNode node;
    try {
      node = CoreNode.create(
        core,
        NodeSpec(
          source: source,
          chunkName: chunk,
          nodeId: nodeId,
          teams: teams,
          params: params,
        ),
        fieldOps: nodeId == 0 ? _NoField() : null,
      );
    } on NodeSetupException catch (e) {
      throw ModeException('$what does not load: ${e.message}');
    }
    try {
      if (!node.loaded) {
        throw ModeException('$what does not load: ${node.lastError}');
      }
    } finally {
      node.close();
    }
  }

  if (pkg.kind != 'scenario') {
    load(1, pkg.mode.nodeScript, '${pkg.id}/node.lua', 'node.lua');
  }
  final field = pkg.fieldScript;
  if (field != null) load(0, field, '${pkg.id}/field.lua', 'field.lua');
}

/// Compares texts by code point (SQLite's binary order of UTF-8).
int compareCodePoints(String a, String b) {
  final x = a.runes.toList(), y = b.runes.toList();
  for (var i = 0; i < x.length && i < y.length; i++) {
    if (x[i] != y[i]) return x[i].compareTo(y[i]);
  }
  return x.length.compareTo(y.length);
}

/// The built-in packages and the uploads (modes.py `ModeRegistry`), and the
/// presets (the Pi store's `presets` table).
class ControllerModes {
  ControllerModes(
    this.store, {
    this.core,
    ModeCatalog? catalog,
    double Function()? wallSeconds,
  }) : _wall =
           wallSeconds ?? (() => DateTime.now().microsecondsSinceEpoch / 1e6) {
    for (final m in (catalog ?? ModeCatalog.builtin()).modes) {
      if (m.isScenario) continue; // a scenario is uploaded, never built in
      final source = builtinModeFiles[m.folder];
      final files = <String, String>{
        'mode.yaml': source?['mode.yaml'] ?? jsonEncode(m.manifest),
        'node.lua': m.nodeScript,
        'field.lua': ?m.fieldScript,
      };
      _builtin[m.id] = ModePackage(
        modeFromManifest(
          m.manifest,
          m.folder,
          nodeScript: m.nodeScript,
          fieldScript: m.fieldScript,
        ),
        files,
        builtin: true,
      );
    }
  }

  final ControllerStore store;

  /// The core: uploads' scripts are loaded in it (null: uploads refused).
  final AtalaiaCore? core;
  final double Function() _wall;
  final _builtin = <String, ModePackage>{};

  /// Counts installs: what a cache of the uploads compares.
  int generation = 0;

  static const _doc = 'modes';
  static const _presetsDoc = 'presets';

  Map<String, Object?> _uploads() =>
      (store.document(_doc) as Map?)?.cast<String, Object?>() ?? {};

  /// Every package, by id.
  List<ModePackage> all() {
    final mods = Map<String, ModePackage>.of(_builtin);
    _uploads().forEach((id, row) {
      if (_builtin.containsKey(id) || row is! Map) return;
      try {
        final pkg = parseModePackage(row['files']);
        pkg.signed = (row['signed'] as Map?)?.cast<String, Object?>();
        mods[id] = pkg;
      } on ModeException {
        // A stored package this version cannot read: left out.
      }
    });
    final ids = mods.keys.toList()..sort(compareCodePoints);
    return [for (final id in ids) mods[id]!];
  }

  /// One package by its own id (a scenario too), or null.
  ModePackage? package(String id) {
    for (final p in all()) {
      if (p.id == id) return p;
    }
    return null;
  }

  /// A package, or a main mode with its other parts ("main+modifier"),
  /// composed; null when a part is not installed. Throws [ModeException]
  /// when the parts do not go together (modes.py `ModeRegistry.get`).
  ModePackage? get(Object? modeId) {
    if (modeId is! String) return null;
    final names = modeId.split(modeSeparator);
    final found = {
      for (final m in all())
        if (names.contains(m.id)) m.id: m,
    };
    if (names.length == 1) {
      final pkg = found[modeId];
      if (pkg != null && pkg.kind == 'scenario') {
        composeModes(pkg.mode, const []); // a scenario alone is no game
      }
      return pkg;
    }
    if (names.any((n) => !found.containsKey(n))) return null;
    final parts = [for (final n in names) found[n]!];
    final mode = composeModes(parts.first.mode, [
      for (final p in parts.skip(1)) p.mode,
    ]);
    return ModePackage(mode, {
      'mode.yaml': parts.first.files['mode.yaml']!,
      'node.lua': mode.nodeScript,
      'field.lua': ?mode.fieldScript,
    }, builtin: parts.every((p) => p.builtin));
  }

  /// The composed mode of [modeId], or null (unknown, or parts that do not
  /// go together).
  ControllerMode? modeOf(Object? modeId) {
    try {
      return get(modeId)?.mode;
    } on ModeException {
      return null;
    }
  }

  /// Checks and keeps a package; [signed] and [archive] when
  /// signed_modes.dart verified it (an unsigned upload replaces a signed
  /// one, signature and all). Throws [ModeException].
  ModePackage install(
    Object? files, {
    Map<String, Object?>? signed,
    Uint8List? archive,
  }) {
    final pkg = parseModePackage(files);
    if (_builtin.containsKey(pkg.id)) {
      throw ModeException(
        '${pkg.id} is a built-in mode; give your version another id',
      );
    }
    final c = core;
    if (c == null) {
      throw ModeException(
        'the core library is not loaded, so scripts cannot be checked',
      );
    }
    checkScripts(c, pkg);
    pkg.signed = signed;
    final uploads = _uploads();
    uploads[pkg.id] = {
      'id': pkg.id,
      'version': pkg.mode.version,
      'files': pkg.files,
      'installed_at': _wall(),
      'signed': signed,
      'archive': signed != null && archive != null
          ? base64.encode(archive)
          : null,
    };
    store.putDocument(_doc, uploads);
    generation++;
    return pkg;
  }

  /// A signed package's archive, exactly as signed (null for an unsigned or
  /// unknown one).
  Uint8List? archive(String modeId) {
    final row = _uploads()[modeId];
    final a = row is Map ? row['archive'] : null;
    return a is String ? base64.decode(a) : null;
  }

  // --- presets ---------------------------------------------------------------

  Map<String, Object?> _presetDoc() =>
      (store.document(_presetsDoc) as Map?)?.cast<String, Object?>() ??
      {'next_id': 1, 'items': <Object?>[]};

  /// Every preset, by name.
  List<Map<String, Object?>> presets() {
    final items = [
      for (final p in (_presetDoc()['items'] as List?) ?? const [])
        (p as Map).cast<String, Object?>(),
    ]..sort((a, b) => compareCodePoints('${a['name']}', '${b['name']}'));
    return items;
  }

  Map<String, Object?>? preset(int id) {
    for (final p in presets()) {
      if (p['id'] == id) return p;
    }
    return null;
  }

  /// Saves a preset under [name], replacing one of that name (keeping its
  /// id), as the Pi's `save_preset`.
  Map<String, Object?> savePreset(
    String name,
    String modeId,
    Map<String, Object?> params,
  ) {
    final doc = _presetDoc();
    final items = [
      for (final p in (doc['items'] as List?) ?? const [])
        (p as Map).cast<String, Object?>(),
    ];
    final now = _wall();
    final i = items.indexWhere((p) => p['name'] == name);
    Map<String, Object?> row;
    if (i >= 0) {
      row = {
        ...items[i],
        'mode_id': modeId,
        'params': params,
        'updated_at': now,
      };
      items[i] = row;
    } else {
      final id = (doc['next_id'] as int?) ?? 1;
      row = {
        'id': id,
        'name': name,
        'mode_id': modeId,
        'params': params,
        'created_at': now,
        'updated_at': now,
      };
      items.add(row);
      doc['next_id'] = id + 1;
    }
    doc['items'] = items;
    store.putDocument(_presetsDoc, doc);
    return row;
  }
}
