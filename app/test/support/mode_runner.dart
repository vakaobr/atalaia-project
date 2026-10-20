// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Runs a mode's event-sequence tests (`modes/<mode>/tests/*.yaml`) on the
/// real core through the Dart bridge: the Dart port of
/// simulator/atalaia_sim/testing.py, sim.py and mode.py, without the radio
/// model. The same YAML files run in the simulator (`python -m atalaia_sim
/// test`), so Python and Dart check the same expectations; modes/README.md
/// describes every step.
///
/// Each node can run in two ways ([Via]): a `CoreNode` called directly, or a
/// game loop isolate with a manual clock (the app's own path, ADR-P3-1). A
/// mode's field script (field.lua) always runs directly with field
/// operations, as the controller runs it.
library;

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/core/game_loop_isolate.dart';
import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/ffi/callbacks.dart';
import 'package:atalaia_app/ffi/core_node.dart';
import 'package:atalaia_app/ffi/native_types.dart';
import 'package:atalaia_app/security/nfc_tag_signer.dart';
import 'package:crypto/crypto.dart';
import 'package:yaml/yaml.dart';

import 'event_schema.dart';

/// How the test's nodes run.
enum Via {
  /// CoreNode, synchronously, on the test's isolate.
  direct,

  /// One game loop isolate per node, GameClock.manual.
  isolate,
}

const defaultTeams = ['red', 'blue'];

/// While a team holds an input, shells emit team_input.hold this often.
const holdStepMs = 250;
const controller = 'controller';

/// With a field script, time moves in steps this long (sim.py FIELD_STEP_MS).
const fieldStepMs = 100;

/// field.send() commands a node understands, as the input events a Field Box
/// turns them into (decision E7). "mode" is a mode command (CMD opcode 8, RFC
/// 0001 Amendment 5): its params name it, and the script gets cmd.mode.
const fieldCommands = {
  'set_owner': 'cmd.set_owner',
  'message': 'gm.message',
  'mode': 'cmd.mode',
};

/// A CMD's parameters, as JSON, fit a box's 128-byte buffer
/// (field_controller.py CMD_PARAMS_MAX).
const cmdParamsMax = 127;

/// Positions never travel as events (decisions P4R6, P4R25): event data with
/// one of these keys, at any depth, is a problem (sim.py COORDINATE_KEYS).
const coordinateKeys = {
  'lat', 'lon', 'lng', 'latitude', 'longitude', 'alt', 'altitude', //
  'position', 'positions', 'gps', 'coords', 'coordinates', 'x', 'y',
};

/// The position-like keys anywhere in an event's data.
List<String> coordinateKeysIn(Object? data) => [
  if (data is Map)
    for (final e in data.entries) ...[
      if (coordinateKeys.contains(e.key)) '${e.key}',
      ...coordinateKeysIn(e.value),
    ]
  else if (data is List)
    for (final v in data) ...coordinateKeysIn(v),
];

/// The name of a mode command (mode.py COMMAND_NAME).
final commandName = RegExp(r'^[a-z][a-z0-9_]{0,23}$');

/// A mode's manifest or a test file that cannot be used.
class ModeError implements Exception {
  ModeError(this.message);
  final String message;
  @override
  String toString() => message;
}

class TestFailure implements Exception {
  TestFailure(this.message);
  final String message;
  @override
  String toString() => message;
}

/// YAML maps and lists as plain Dart ones.
Object? plain(Object? v) => switch (v) {
  YamlMap() => {for (final e in v.entries) '${e.key}': plain(e.value)},
  YamlList() => [for (final e in v) plain(e)],
  _ => v,
};

// ---- Modes (mode.py) -----------------------------------------------------------

/// A role package inside a composed game: its roles run it alone.
class RolePart {
  RolePart(this.id, this.nodeScript, this.chunkName, this.paramNames);
  final String id;
  final String nodeScript;
  final String chunkName;
  final Set<String> paramNames;
}

class Mode {
  Mode({
    required this.dir,
    required this.id,
    required this.name,
    required this.kind,
    required this.roles,
    required this.params,
    required this.nodeScript,
    required this.fieldScript,
    this.roleParts = const {},
    String? mainId,
    this.scenarioParams = const {},
  }) : mainId = mainId ?? id;

  final Directory dir;
  final String id;
  final String name;

  /// mode, modifier, role (a role package) or scenario (a field.lua over
  /// role packages, decision P4R7; modes/README.md).
  final String kind;
  final Map<String, Object?> roles;
  final Map<String, Map<String, Object?>> params;
  final String nodeScript;
  final String? fieldScript;

  /// For a composed mode: role -> the role package its nodes run instead.
  final Map<String, RolePart> roleParts;

  /// For a composed mode: what the main mode's roles run (main + modifiers).
  final String mainId;

  /// For a composed mode led by a scenario: its parameters, which only its
  /// field.lua reads, so no node's join carries them.
  final Set<String> scenarioParams;

  String get folder => dir.uri.pathSegments.lastWhere((s) => s.isNotEmpty);

  /// The script a node with [role] runs.
  String nodeScriptFor(String role) =>
      roleParts[role]?.nodeScript ?? nodeScript;

  String chunkNameFor(String role) =>
      roleParts[role]?.chunkName ?? '@$folder/node.lua';

  /// The mode id a node with [role] is given in its join.
  String nodeModeId(String role) => roleParts[role]?.id ?? mainId;

  /// The game's parameters a node with [role] runs with (its join's).
  Map<String, Object?> paramsFor(String role, Map<String, Object?> values) {
    if (roleParts.isEmpty) return Map.of(values);
    final part = roleParts[role];
    if (part != null) {
      return {
        for (final e in values.entries)
          if (part.paramNames.contains(e.key)) e.key: e.value,
      };
    }
    final others = {
      for (final p in roleParts.values) ...p.paramNames,
      ...scenarioParams,
    };
    return {
      for (final e in values.entries)
        if (!others.contains(e.key)) e.key: e.value,
    };
  }

  List<File> get tests => _yamlFiles(Directory('${dir.path}/tests'));

  List<File> get screens => _yamlFiles(Directory('${dir.path}/assets/screens'));

  /// Defaults from the manifest plus overrides, checked against the schema.
  Map<String, Object?> resolveParams(
    Map<String, Object?> overrides,
    List<String> teams,
  ) {
    final unknown = overrides.keys.where((k) => !params.containsKey(k));
    if (unknown.isNotEmpty) {
      throw ModeError('$id: unknown parameter(s) ${unknown.toList()..sort()}');
    }
    final values = <String, Object?>{};
    params.forEach((name, spec) {
      final Object? value;
      if (overrides.containsKey(name)) {
        value = overrides[name];
      } else if (spec.containsKey('default')) {
        value = spec['default'];
      } else if (spec['optional'] == true) {
        return;
      } else {
        throw ModeError("$id: parameter '$name' has no value");
      }
      _checkParam(id, name, spec, value, teams);
      values[name] = value;
    });
    return values;
  }
}

List<File> _yamlFiles(Directory d) {
  if (!d.existsSync()) return [];
  return d
      .listSync()
      .whereType<File>()
      .where((f) => f.path.endsWith('.yaml'))
      .toList()
    ..sort((a, b) => a.path.compareTo(b.path));
}

void _checkParam(
  String modeId,
  String name,
  Map<String, Object?> spec,
  Object? value,
  List<String> teams,
) {
  final where = "$modeId: parameter '$name'";
  switch (spec['type']) {
    case 'int':
      if (value is! int) {
        throw ModeError('$where must be an integer, got $value');
      }
      final min = spec['min'] as num?;
      final max = spec['max'] as num?;
      if (min != null && value < min) {
        throw ModeError('$where must be at least $min');
      }
      if (max != null && value > max) {
        throw ModeError('$where must be at most $max');
      }
    case 'bool':
      if (value is! bool) {
        throw ModeError('$where must be true or false, got $value');
      }
    case 'team':
      if (!teams.contains(value)) {
        throw ModeError(
          "$where must be one of the game's teams $teams, got $value",
        );
      }
    case 'string':
      if (value is! String) throw ModeError('$where must be text, got $value');
      final max = spec['max'] as num?;
      if (max != null && utf8.encode(value).length > max) {
        throw ModeError('$where must be at most $max bytes');
      }
    default:
      throw ModeError('$where has unknown type ${spec['type']}');
  }
}

/// The manifest's own checks that the scripts depend on (mode.py
/// check_manifest, for a scenario: no roles and no commands).
void checkManifest(Map<String, Object?> m, String where) {
  const kinds = ['mode', 'modifier', 'role', 'scenario'];
  final kind = m['kind'] ?? 'mode';
  if (!kinds.contains(kind)) {
    throw ModeError(
      '$where: kind must be one of ${kinds.join(', ')}, got $kind',
    );
  }
  if (kind == 'scenario') {
    if ((m['roles'] as Map?)?.isNotEmpty ?? false) {
      throw ModeError(
        '$where: a scenario has no roles: its nodes run role packages',
      );
    }
    if ((m['commands'] as Map?)?.isNotEmpty ?? false) {
      throw ModeError(
        "$where: a scenario has no commands: they are for the nodes' roles",
      );
    }
  }
}

/// A scenario is a field.lua and no node.lua (decision P4R7); every other
/// kind has a node.lua (mode.py check_files).
void checkFiles(String kind, bool hasNode, bool hasField, String where) {
  if (kind == 'scenario') {
    if (hasNode) {
      throw ModeError(
        '$where: a scenario has no node.lua: its nodes run role packages',
      );
    }
    if (!hasField) throw ModeError('$where: a scenario needs a field.lua');
  } else if (!hasNode) {
    throw ModeError('$where: no node.lua');
  }
}

Mode loadMode(Directory dir) {
  final manifest = File('${dir.path}/mode.yaml');
  if (!manifest.existsSync()) throw ModeError('${dir.path}: no mode.yaml');
  final m =
      (plain(loadYaml(manifest.readAsStringSync())) as Map<String, Object?>?) ??
      {};
  final kind = (m['kind'] ?? 'mode') as String;
  for (final key in ['id', 'version', if (kind != 'scenario') 'roles']) {
    if (!m.containsKey(key)) {
      throw ModeError("${manifest.path}: missing '$key'");
    }
  }
  checkManifest(m, manifest.path);
  final node = File('${dir.path}/node.lua');
  final field = File('${dir.path}/field.lua');
  checkFiles(kind, node.existsSync(), field.existsSync(), dir.path);
  return Mode(
    dir: dir,
    id: m['id']! as String,
    name: (m['name'] ?? m['id']) as String,
    kind: kind,
    roles: (m['roles'] as Map<String, Object?>?) ?? {},
    params: {
      for (final e in ((m['params'] as Map<String, Object?>?) ?? {}).entries)
        e.key: e.value! as Map<String, Object?>,
    },
    nodeScript: node.existsSync() ? node.readAsStringSync() : '',
    fieldScript: field.existsSync() ? field.readAsStringSync() : null,
  );
}

/// One Lua chunk from a main mode's script and its modifiers' scripts.
String composeScripts(List<String> scripts) => scripts.length == 1
    ? scripts.single
    : scripts.map((s) => 'do\n$s\nend\n').join();

/// A game's id travels in a standby controller's join: 63 bytes at most.
const modeIdMax = 63;

/// A main mode with modifiers and role packages: one id, one parameter
/// schema; the main mode's roles run it with the modifiers, and each role
/// package's roles run that package alone. A scenario leads the id and is
/// followed by at least one role package, optionally after one main mode and
/// its modifiers; it adds its field.lua (first) and its parameters, never a
/// role (mode.py compose; protocol/vectors/composition.yaml).
Mode compose(Mode main, List<Mode> modifiers) {
  Mode? scenario;
  Mode? lead;
  var rest = modifiers;
  const needsRole =
      'it needs a role package after it, such as '
      'org.atalaia.objectives';
  if (main.kind == 'scenario') {
    scenario = main;
    if (rest.isEmpty) throw ModeError('${main.id} is a scenario: $needsRole');
    if (rest.first.kind == 'mode') {
      lead = rest.first;
      rest = rest.sublist(1);
    }
  } else {
    if (rest.isEmpty) return main;
    if (main.kind != 'mode') {
      throw ModeError(
        '${main.id} is a ${main.kind}; a game needs a main mode first',
      );
    }
    lead = main;
  }
  final leaders = [?scenario, ?lead];
  final first = leaders.first;
  final seen = <String>{};
  final params = <String, Map<String, Object?>>{};
  for (final m in leaders) {
    if (!seen.add(m.id)) throw ModeError('${m.id} is named twice');
    final clash = params.keys.toSet().intersection(m.params.keys.toSet());
    if (clash.isNotEmpty) {
      throw ModeError(
        '${m.id} and ${first.id} both have the parameter(s) $clash',
      );
    }
    params.addAll(m.params);
  }
  final roles = lead == null ? <String, Object?>{} : Map.of(lead.roles);
  final mods = <Mode>[];
  final roleParts = <String, RolePart>{};
  for (final mod in rest) {
    if (mod.kind == 'scenario') {
      throw ModeError(
        "${mod.id} is a scenario: a scenario leads the game's id",
      );
    }
    if (mod.kind == 'mode') {
      if (scenario != null) {
        throw ModeError(
          "${mod.id} is a main mode: a scenario's game has one, right after "
          'the scenario',
        );
      }
      throw ModeError('${mod.id} is a main mode, not a modifier');
    }
    if (!seen.add(mod.id)) throw ModeError('${mod.id} is named twice');
    final clash = params.keys.toSet().intersection(mod.params.keys.toSet());
    if (clash.isNotEmpty) {
      throw ModeError(
        '${mod.id} and ${first.id} both have the parameter(s) $clash',
      );
    }
    params.addAll(mod.params);
    if (mod.kind == 'modifier') {
      if (lead == null) {
        throw ModeError(
          '${mod.id} is a modifier: it runs with a main mode, and this '
          "scenario's game has none",
        );
      }
      mods.add(mod);
      continue;
    }
    final roleClash = roles.keys.toSet().intersection(mod.roles.keys.toSet());
    if (roleClash.isNotEmpty) {
      throw ModeError(
        '${mod.id} and ${first.id} both have the role(s) $roleClash',
      );
    }
    roles.addAll(mod.roles);
    final part = RolePart(
      mod.id,
      mod.nodeScript,
      '@${mod.folder}/node.lua',
      mod.params.keys.toSet(),
    );
    for (final r in mod.roles.keys) {
      roleParts[r] = part;
    }
  }
  if (scenario != null && roleParts.isEmpty) {
    throw ModeError('${scenario.id} is a scenario: $needsRole');
  }
  final parts = [...leaders, ...rest];
  final id = parts.map((m) => m.id).join('+');
  if (utf8.encode(id).length > modeIdMax) {
    throw ModeError(
      '$id: a mode with its modifiers is named in at most $modeIdMax bytes',
    );
  }
  final runs = [?lead, ...mods];
  final fields = [for (final m in parts) ?m.fieldScript];
  return Mode(
    dir: first.dir,
    id: id,
    name: parts.map((m) => m.name).join(' + '),
    kind: 'mode',
    roles: roles,
    params: params,
    nodeScript: runs.isEmpty
        ? ''
        : composeScripts([for (final m in runs) m.nodeScript]),
    fieldScript: fields.isEmpty ? null : composeScripts(fields),
    roleParts: roleParts,
    mainId: runs.map((m) => m.id).join('+'),
    scenarioParams: scenario?.params.keys.toSet() ?? const {},
  );
}

/// Mode folders in [root]: the folders with a mode.yaml, sorted.
List<Directory> findModes(Directory root) =>
    root
        .listSync()
        .whereType<Directory>()
        .where((d) => File('${d.path}/mode.yaml').existsSync())
        .toList()
      ..sort((a, b) => a.path.compareTo(b.path));

// ---- Screen templates (screens.py) ----------------------------------------------

const _templateSourceMax = 4096; // ATALAIA_TPL_SOURCE_MAX

/// Problems with a mode's screen templates, checked by the core's own parser.
List<String> checkScreens(AtalaiaCore core, Mode mode) {
  final problems = <String>[];
  for (final file in mode.screens) {
    final name = file.uri.pathSegments.last;
    final stem = name.substring(0, name.length - '.yaml'.length);
    final bytes = file.readAsBytesSync();
    if (bytes.length > _templateSourceMax) {
      problems.add('$name: larger than $_templateSourceMax bytes');
      continue;
    }
    final String source;
    try {
      source = utf8.decode(bytes);
    } on FormatException {
      problems.add('$name: not UTF-8');
      continue;
    }
    final why = core.checkScreen(source);
    if (why != null) {
      problems.add('$name: $why');
      continue;
    }
    final doc = plain(loadYaml(source)) as Map<String, Object?>?;
    if (doc?['template'] != stem) {
      problems.add(
        "$name: its template: name is ${doc?['template']}; it must be '$stem'",
      );
    }
  }
  return problems;
}

// ---- The simulated game (sim.py) ------------------------------------------------

class LogEntry {
  LogEntry(
    this.tMs,
    this.node,
    this.nodeId,
    this.seq,
    this.type,
    this.team,
    this.prio,
    this.data,
  );

  final int tMs;
  final String node;
  final int nodeId;
  final int seq;
  final String type;
  final String? team;
  final int prio;
  final Map<String, Object?> data;

  String describe() {
    final t = (tMs / 1000).toStringAsFixed(3).padLeft(9);
    final tm = team != null ? ' [$team]' : '';
    final d = data.isNotEmpty ? ' $data' : '';
    return '${t}s  ${node.padRight(12)} $type$tm$d';
  }
}

/// One node of the game, behind either way of running it.
abstract class SimNode {
  int get nodeId;
  bool get loaded;
  Future<bool> input(String type, Map<String, Object?> data);
  Future<void> advance(int ms);
  Future<String> status();
  Future<String> lastError();
  Future<int> score(String team);
  Future<void> close();
}

class _DirectNode implements SimNode {
  _DirectNode(this.node, this.nodeId);
  final CoreNode node;
  @override
  final int nodeId;
  @override
  bool get loaded => node.loaded;
  void _raise() {
    if (node.callbackErrors.isNotEmpty) {
      final e = node.callbackErrors.first;
      node.callbackErrors.clear();
      throw TestFailure('a callback handler failed: $e');
    }
  }

  @override
  Future<bool> input(String type, Map<String, Object?> data) async {
    final ok = node.input(type, data);
    _raise();
    return ok;
  }

  @override
  Future<void> advance(int ms) async {
    node.advance(ms);
    _raise();
  }

  @override
  Future<String> status() async => node.status.name;
  @override
  Future<String> lastError() async => node.lastError;
  @override
  Future<int> score(String team) async => node.score(team);
  @override
  Future<void> close() async => node.close();
}

class _IsolateNode implements SimNode {
  _IsolateNode(this.loop, this.nodeId);
  final GameLoopIsolate loop;
  @override
  final int nodeId;
  @override
  bool get loaded => loop.loaded;
  @override
  Future<bool> input(String type, Map<String, Object?> data) =>
      loop.input(type, data);
  @override
  Future<void> advance(int ms) => loop.advanceTo(ms);
  @override
  Future<String> status() async => (await loop.snapshot()).status.name;
  @override
  Future<String> lastError() async => (await loop.snapshot()).lastError;
  @override
  Future<int> score(String team) async => (await loop.snapshot()).scores[team]!;
  @override
  Future<void> close() => loop.close();
}

class VirtualNode {
  VirtualNode(this.name, this.role);
  final String name;
  final String role;
  late SimNode runtime;
  final commands = <NodeCommand>[];
  final logs = <String>[];

  NodeCommand? lastCommand(String target, String method) {
    for (final c in commands.reversed) {
      if (c.target == target && c.method == method) return c;
    }
    return null;
  }
}

class Simulation {
  Simulation._(
    this.core,
    this.schema,
    this.mode,
    this.teams,
    this.params,
    this.seed,
    this.via,
  ) : gameKey = sha256
          .convert(utf8.encode('atalaia-sim-game-key:$seed'))
          .bytes
          .sublist(0, 16);

  final AtalaiaCore core;
  final EventSchema schema;
  final Mode mode;
  final List<String> teams;
  final Map<String, Object?> params;
  final int seed;
  final Via via;

  /// The game's id and 16-byte key, as a join gives them; player tags are signed with them.
  final int gameId = 1;
  final List<int> gameKey;

  int timeMs = 0;
  final _log = <LogEntry>[];
  var _controllerSeq = 0;

  /// Events that break protocol/schema/events.yaml or would not fit in a
  /// LoRa packet (they are found inside the core's callbacks, where nothing
  /// may be thrown).
  final problems = <String>[];
  final nodes = <String, VirtualNode>{};
  CoreNode? field;
  final fieldLogs = <String>[];
  final owners = <int, String?>{};
  final _toField = <(int, String, Map<String, Object?>)>[];
  final _toNodes = <(String, String, Map<String, Object?>)>[];
  (int, Map<String, Object?>)? _fieldEnd;
  var _ended = false;
  var _started = false; // game.start broadcast, game.end not yet

  static Future<Simulation> create(
    AtalaiaCore core,
    EventSchema schema,
    Mode mode,
    Map<String, String> nodeRoles,
    List<String> teams,
    Map<String, Object?> params, {
    int seed = 1,
    Via via = Via.direct,
  }) async {
    final sim = Simulation._(
      core,
      schema,
      mode,
      List.of(teams),
      params,
      seed,
      via,
    );
    try {
      var nodeId = 0;
      for (final e in nodeRoles.entries) {
        nodeId++;
        if (!mode.roles.containsKey(e.value)) {
          throw TestFailure(
            "node '${e.key}': mode ${mode.id} has no role '${e.value}'",
          );
        }
        final vnode = VirtualNode(e.key, e.value);
        sim.nodes[e.key] = vnode;
        vnode.runtime = await sim._spawn(vnode, nodeId);
        if (!vnode.runtime.loaded) {
          throw TestFailure(
            "node '${e.key}' failed to load ${mode.id}: ${await vnode.runtime.lastError()}",
          );
        }
      }
      if (mode.fieldScript != null) {
        sim.field = CoreNode.create(
          core,
          NodeSpec(
            source: mode.fieldScript!,
            chunkName: '@${mode.folder}/field.lua',
            nodeId: 0,
            gameSeed: seed,
            teams: sim.teams,
            params: params,
          ),
          handlers: NodeHandlers(
            onEvent: sim._recordField,
            onLog: sim.fieldLogs.add,
          ),
          fieldOps: _SimFieldOps(sim),
        );
        if (!sim.field!.loaded) {
          throw TestFailure(
            'field.lua of ${mode.id} failed to load: ${sim.field!.lastError}',
          );
        }
      }
    } catch (_) {
      await sim.close();
      rethrow;
    }
    return sim;
  }

  /// A node's runtime: what its role runs, with that part's parameters, as
  /// its join gives them (a role package's roles run it alone).
  Future<SimNode> _spawn(VirtualNode vnode, int nodeId) async {
    final spec = NodeSpec(
      source: mode.nodeScriptFor(vnode.role),
      chunkName: mode.chunkNameFor(vnode.role),
      nodeId: nodeId,
      gameSeed: seed,
      teams: teams,
      params: mode.paramsFor(vnode.role, params),
    );
    switch (via) {
      case Via.direct:
        return _DirectNode(
          CoreNode.create(
            core,
            spec,
            handlers: NodeHandlers(
              onEvent: (ev) => _record(vnode, ev),
              onCommand: vnode.commands.add,
              onLog: vnode.logs.add,
            ),
          ),
          nodeId,
        );
      case Via.isolate:
        return _IsolateNode(
          await GameLoopIsolate.spawn(
            spec,
            libraryPath: core.path,
            clock: GameClock.manual,
            onOutput: (out) {
              switch (out) {
                case NodeEventOutput(:final event):
                  _record(vnode, event);
                case NodeCommandOutput(:final command):
                  vnode.commands.add(command);
                case NodeLogOutput(:final line):
                  vnode.logs.add(line);
                case NodeErrorOutput(:final message):
                  problems.add('${vnode.name}: $message');
                case NodeStatusOutput():
                  break;
              }
            },
          ),
          nodeId,
        );
    }
  }

  /// A node loses power and comes back in the running game, as a Field Box
  /// does (node_runner_resume): its script is loaded again with no state, gets
  /// game.start, is brought to the game's time and gets node.rebooted; the
  /// box then reports node.rebooted (reason power) to the controller (sim.py
  /// reboot).
  Future<void> reboot(String name) async {
    final vnode = node(name);
    final nodeId = vnode.runtime.nodeId;
    await vnode.runtime.close();
    vnode.runtime = await _spawn(vnode, nodeId);
    if (!vnode.runtime.loaded) {
      throw TestFailure(
        "node '$name' failed to load ${mode.id}: ${await vnode.runtime.lastError()}",
      );
    }
    if (_started) {
      await vnode.runtime.input('game.start', {
        'preset': mode.nodeModeId(vnode.role),
      });
      await vnode.runtime.advance(timeMs);
      await vnode.runtime.input('node.rebooted', {});
    }
    const data = {'reason': 'power'};
    final prio = schema.defaultPrio('node.rebooted');
    _checkWire(
      name,
      nodeId,
      0,
      timeMs,
      'node.rebooted',
      0,
      0,
      prio,
      data,
      jsonEncode(data),
    );
    _log.add(
      LogEntry(timeMs, name, nodeId, 0, 'node.rebooted', null, prio, data),
    );
    if (field != null) {
      _toField.add((timeMs, 'node.rebooted', {...data, 'node': nodeId}));
    }
    await _pump();
  }

  Future<void> close() async {
    for (final v in nodes.values) {
      try {
        await v.runtime.close();
      } on Error {
        // never created (late field unset)
      }
    }
    field?.close();
  }

  // -- the event log --

  String? _teamName(int id) =>
      id >= 1 && id <= teams.length ? teams[id - 1] : null;

  void _record(VirtualNode vnode, EmittedEvent ev) {
    final data = ev.data;
    _checkWire(
      vnode.name,
      ev.node,
      ev.seq,
      ev.tMs,
      ev.type,
      ev.team,
      ev.squad,
      ev.prio,
      data,
      ev.dataJson,
    );
    final team = _teamName(ev.team);
    _log.add(
      LogEntry(
        ev.tMs,
        vnode.name,
        ev.node,
        ev.seq,
        ev.type,
        team,
        ev.prio,
        data,
      ),
    );
    // A box reports the team of its last capture as its owner (decision E6).
    if (ev.type == 'zone.captured') {
      owners[ev.node] = team;
    } else if (ev.type == 'zone.neutralized') {
      owners[ev.node] = null;
    }
    if (field != null) {
      final d = Map.of(data);
      d.putIfAbsent('node', () => ev.node);
      if (team != null) d.putIfAbsent('team', () => team);
      _toField.add((ev.tMs, ev.type, d));
    }
  }

  void _recordField(EmittedEvent ev) {
    if (ev.type == 'game.end') {
      _fieldEnd = (ev.tMs, ev.data);
      return;
    }
    _controllerSeq++;
    final data = ev.data;
    _checkWire(
      controller,
      0,
      _controllerSeq & 0xffff,
      ev.tMs,
      ev.type,
      ev.team,
      0,
      ev.prio,
      data,
      ev.dataJson,
    );
    _log.add(
      LogEntry(
        ev.tMs,
        controller,
        0,
        _controllerSeq,
        ev.type,
        _teamName(ev.team),
        ev.prio,
        data,
      ),
    );
  }

  void _recordController(String type, Map<String, Object?> data, [int? t]) {
    final tMs = t ?? timeMs;
    _controllerSeq++;
    final prio = schema.defaultPrio(type);
    _checkWire(
      controller,
      0,
      _controllerSeq & 0xffff,
      tMs,
      type,
      0,
      0,
      prio,
      data,
      jsonEncode(data),
    );
    _log.add(
      LogEntry(tMs, controller, 0, _controllerSeq, type, null, prio, data),
    );
  }

  /// Checks an event against the schema, and that the core's codec puts it
  /// in one LoRa payload.
  void _checkWire(
    String who,
    int node,
    int seq,
    int tMs,
    String type,
    int team,
    int squad,
    int prio,
    Map<String, Object?> data,
    String dataJson,
  ) {
    final found = schema.problems(type, data);
    final coords = coordinateKeysIn(data).toSet().toList()..sort();
    if (coords.isNotEmpty) {
      found.add(
        "'$type' carries a position (${coords.join(', ')}): positions never "
        'travel as events (P4R6)',
      );
    }
    final encoded = core.encodeEvent(
      node: node,
      seq: seq,
      tMs: tMs,
      type: type,
      team: team,
      squad: squad,
      prio: prio,
      dataJson: dataJson,
    );
    if (encoded.bytes == null) {
      found.add("'$type' cannot be sent: ${encoded.error}");
    } else if (encoded.size > rfPayloadMax) {
      found.add(
        "'$type' takes ${encoded.size} bytes on the wire, more than the "
        '$rfPayloadMax bytes of a LoRa payload',
      );
    }
    problems.addAll(found.map((p) => '$who: $p'));
  }

  /// The merged game log, by time; events at the same time keep their arrival order.
  List<LogEntry> get events {
    final indexed = [for (var i = 0; i < _log.length; i++) (i, _log[i])];
    indexed.sort((a, b) {
      final c = a.$2.tMs.compareTo(b.$2.tMs);
      return c != 0 ? c : a.$1.compareTo(b.$1);
    });
    return [for (final e in indexed) e.$2];
  }

  // -- field operations, for field.lua --

  List<Map<String, Object?>> _fieldNodes(String? role) => [
    for (final v in nodes.values)
      if (role == null || v.role == role)
        {
          'id': v.runtime.nodeId,
          'name': v.name,
          'role': v.role,
          'owner': owners[v.runtime.nodeId],
        },
  ];

  bool _fieldSend(int nodeId, String cmd, Map<String, Object?> params) {
    final target = nodes.values
        .where((v) => v.runtime.nodeId == nodeId)
        .firstOrNull;
    if (target == null || !fieldCommands.containsKey(cmd)) return false;
    if (cmd == 'mode' && !commandName.hasMatch('${params['name'] ?? ''}')) {
      return false; // a mode command names itself
    }
    final size = utf8.encode(jsonEncode(params)).length;
    if (params.isNotEmpty && size > cmdParamsMax) {
      // The controller refuses it too: a box's buffer is 128 bytes.
      problems.add(
        "$controller: field.send(${target.name}, '$cmd') parameters are "
        '$size bytes; at most $cmdParamsMax fit in a CMD',
      );
      return false;
    }
    _toNodes.add((target.name, fieldCommands[cmd]!, Map.of(params)));
    return true;
  }

  /// Delivers what the nodes and the field script sent each other, after the
  /// call that produced it has returned (the core is never re-entered).
  Future<void> _pump() async {
    for (var i = 0; i < 10000; i++) {
      if (_toField.isNotEmpty) {
        final (t, type, data) = _toField.removeAt(0);
        if (t > field!.timeMs) field!.advance(t);
        field!.input(type, data);
      } else if (_toNodes.isNotEmpty) {
        final (name, type, data) = _toNodes.removeAt(0);
        await nodes[name]!.runtime.input(type, data);
      } else if (_fieldEnd != null) {
        final (t, data) = _fieldEnd!;
        _fieldEnd = null;
        if (!_ended) {
          await end(
            (data['reason'] as String?) ?? 'finished',
            data['winner'] as String?,
            t,
          );
        }
      } else {
        return;
      }
    }
    throw TestFailure(
      'the nodes and the field script keep sending each other events',
    );
  }

  // -- driving the game --

  VirtualNode node(String name) =>
      nodes[name] ??
      (throw TestFailure(
        "no node named '$name' (nodes: ${nodes.keys.join(', ')})",
      ));

  Future<void> broadcast(
    String type, [
    Map<String, Object?>? data,
    int? t,
  ]) async {
    final d = data ?? {};
    _recordController(type, d, t);
    if (type == 'game.start') _started = true;
    if (type == 'game.end') {
      _ended = true;
      _started = false;
    }
    for (final v in nodes.values) {
      await v.runtime.input(type, d);
    }
    if (field != null) {
      final reason = d['reason'];
      field!.input(type, reason != null ? {'reason': reason} : {});
    }
    await _pump();
  }

  Future<void> start() => broadcast('game.start', {'preset': mode.id});

  Future<void> end([String reason = 'time', String? winner, int? t]) =>
      broadcast('game.end', {'reason': reason, 'winner': ?winner}, t);

  Future<void> wait(num seconds) =>
      advanceTo(timeMs + (seconds * 1000).round());

  Future<void> advanceTo(int t) async {
    if (t < timeMs) throw TestFailure('time cannot go backwards');
    if (field == null) {
      for (final v in nodes.values) {
        await v.runtime.advance(t);
      }
      timeMs = t;
      return;
    }
    var step = timeMs;
    while (step < t) {
      final next = step - step % fieldStepMs + fieldStepMs;
      step = next < t ? next : t;
      timeMs = step;
      for (final v in nodes.values) {
        await v.runtime.advance(step);
      }
      await _pump();
      field!.advance(step);
      await _pump();
    }
    timeMs = t;
  }

  Future<bool> input(
    String nodeName,
    String type, [
    Map<String, Object?>? data,
  ]) async {
    final ok = await node(nodeName).runtime.input(type, data ?? {});
    await _pump();
    return ok;
  }

  void _checkTeam(String team) {
    if (!teams.contains(team)) {
      throw TestFailure("unknown team '$team' (teams: ${teams.join(', ')})");
    }
  }

  Future<void> press(String nodeName, String team, [String? squad]) async {
    _checkTeam(team);
    await input(nodeName, 'team_input.press', _teamData(team, squad));
  }

  Future<void> hold(
    String nodeName,
    String team,
    num seconds, [
    String? squad,
  ]) async {
    _checkTeam(team);
    final total = (seconds * 1000).round();
    final start = timeMs;
    var held = 0;
    while (held < total) {
      held = held + holdStepMs < total ? held + holdStepMs : total;
      await advanceTo(start + held);
      await input(nodeName, 'team_input.hold', {
        ..._teamData(team, squad),
        'ms': held,
      });
    }
    await input(nodeName, 'team_input.release', {
      ..._teamData(team, squad),
      'ms': total,
    });
  }

  /// A checked-in player's position report, as the field controller hands it
  /// to field.lua (position.fix, decision P4R6): only the field script gets it.
  Future<void> position(
    String player,
    String? team,
    String role,
    double lat,
    double lon, {
    double? acc,
    String src = 'gps',
  }) async {
    final f = field;
    if (f == null) {
      throw TestFailure('position: ${mode.id} has no field.lua to give it to');
    }
    if (team != null) _checkTeam(team);
    if (src != 'gps' && src != 'ble') {
      throw TestFailure('position: src is one of gps, ble');
    }
    if (timeMs > f.timeMs) f.advance(timeMs);
    f.input('position.fix', {
      'player': player,
      'role': role,
      'lat': lat,
      'lon': lon,
      'src': src,
      'team': ?team,
      'acc': ?acc,
    });
    await _pump();
  }

  /// A fix from a prop's own GPS (gps.fix), as the Android prop shell gives
  /// it; without lat and lon, the phone has no fix yet.
  Future<void> gps(String nodeName, double? lat, double? lon, double? acc) =>
      input(nodeName, 'gps.fix', {
        if (lat != null && lon != null) ...{'lat': lat, 'lon': lon},
        'acc': ?acc,
      });

  Future<void> keys(String nodeName, String keys) async {
    for (final k in keys.split('')) {
      await input(nodeName, 'keypad.key', {'key': k});
    }
  }

  /// An NFC tag read: the core checks the tag against this game (atalaia/tag.h).
  Future<void> scan(String nodeName, List<int> uid, List<int>? payload) async {
    final json = core.tagEventJson(
      uid: uid,
      payload: payload,
      gameId: gameId,
      gameKey: gameKey,
      teams: teams,
    );
    await input(nodeName, 'nfc.tag', jsonDecode(json) as Map<String, Object?>);
  }

  /// Field total (every node plus the field script), or one node's.
  Future<int> score(String team, [String? nodeName]) async {
    _checkTeam(team);
    if (nodeName == controller) return field?.score(team) ?? 0;
    if (nodeName != null) return node(nodeName).runtime.score(team);
    var total = 0;
    for (final v in nodes.values) {
      total += await v.runtime.score(team);
    }
    return total + (field?.score(team) ?? 0);
  }
}

/// The controller's answers to field.lua (ADR-P2-14), from the simulated game.
class _SimFieldOps implements FieldOperations {
  _SimFieldOps(this.sim);
  final Simulation sim;
  @override
  List<Map<String, Object?>> nodes(String? role) => sim._fieldNodes(role);
  @override
  String? owner(int nodeId) => sim.owners[nodeId];
  @override
  bool send(int nodeId, String cmd, Map<String, Object?> params) =>
      sim._fieldSend(nodeId, cmd, params);
}

Map<String, Object?> _teamData(String team, String? squad) => {
  'team': team,
  'squad': ?squad,
};

// ---- Tests (testing.py) ----------------------------------------------------------

/// An expected null matches an absent key too: Lua leaves nil values out of the data.
bool _subset(Object? expected, Object? actual) {
  if (expected is Map) {
    return actual is Map &&
        expected.entries.every(
          (e) =>
              (e.value == null && actual[e.key] == null) ||
              (actual.containsKey(e.key) && _subset(e.value, actual[e.key])),
        );
  }
  return expected == actual;
}

Map<String, Object?> _eventFilter(Object? spec) {
  if (spec is String) return {'type': spec};
  if (spec is! Map<String, Object?> || !spec.containsKey('type')) {
    throw TestFailure('an event match needs a type: $spec');
  }
  return spec;
}

bool _matches(LogEntry e, Map<String, Object?> spec) {
  if (e.type != spec['type']) return false;
  if (spec.containsKey('node') && e.node != spec['node']) return false;
  if (spec.containsKey('team') && e.team != spec['team']) return false;
  if (spec.containsKey('at') &&
      e.tMs != ((spec['at']! as num) * 1000).round()) {
    return false;
  }
  if (spec.containsKey('data') && !_subset(spec['data'], e.data)) return false;
  return true;
}

class _Runner {
  _Runner(this.sim);
  final Simulation sim;
  var cursor = 0; // events before this index were consumed by `expect`

  Future<void> step(Object? step) async {
    if (step is! Map<String, Object?> || step.length != 1) {
      throw TestFailure('each step needs exactly one action: $step');
    }
    final MapEntry(key: action, value: arg) = step.entries.single;
    switch (action) {
      case 'start':
        await sim.start();
      case 'end':
        await sim.end(arg is String ? arg : 'time');
      case 'pause':
        await sim.broadcast('game.pause', {'reason': 'gm'});
      case 'resume':
        await sim.broadcast('game.resume', {});
      case 'wait':
        await sim.wait(arg! as num);
      case 'hold':
        final a = arg! as Map<String, Object?>;
        await sim.hold(
          _node(a),
          a['team']! as String,
          a['s']! as num,
          a['squad'] as String?,
        );
      case 'press':
        final a = arg! as Map<String, Object?>;
        await sim.press(_node(a), a['team']! as String, a['squad'] as String?);
      case 'input':
        final a = arg! as Map<String, Object?>;
        await sim.input(
          _node(a),
          a['type']! as String,
          a['data'] as Map<String, Object?>?,
        );
      case 'scan':
        await _scan(arg);
      case 'position':
        if (arg is! Map<String, Object?>) {
          throw TestFailure(
            'position takes a map: { player, team, role, lat, lon, acc, src }',
          );
        }
        _only('position', arg, {
          'player', 'team', 'role', 'lat', 'lon', 'acc', 'src', //
        });
        await sim.position(
          '${arg['player']}',
          arg['team'] as String?,
          '${arg['role'] ?? 'player'}',
          (arg['lat']! as num).toDouble(),
          (arg['lon']! as num).toDouble(),
          acc: (arg['acc'] as num?)?.toDouble(),
          src: '${arg['src'] ?? 'gps'}',
        );
      case 'gps':
        if (arg is! Map<String, Object?>) {
          throw TestFailure('gps takes a map: { node, lat, lon, acc }');
        }
        _only('gps', arg, {'node', 'lat', 'lon', 'acc'});
        await sim.gps(
          _node(arg),
          (arg['lat'] as num?)?.toDouble(),
          (arg['lon'] as num?)?.toDouble(),
          (arg['acc'] as num?)?.toDouble(),
        );
      case 'reboot':
        final a = arg is Map<String, Object?> ? arg : {'node': arg};
        await sim.reboot(_node(a));
      case 'keys':
        final a = arg is Map<String, Object?> ? arg : {'keys': arg};
        await sim.keys(_node(a), '${a['keys']}');
      case 'expect':
        _expect(arg);
      case 'expect_no':
        _expectNo(arg);
      case 'expect_score':
        final a = arg! as Map<String, Object?>;
        final actual = await sim.score(
          a['team']! as String,
          a['node'] as String?,
        );
        if (actual != a['points']) {
          throw TestFailure(
            'expected ${a['team']} to have ${a['points']} points, has $actual',
          );
        }
      case 'expect_status':
        final a = arg is String
            ? {'status': arg}
            : arg! as Map<String, Object?>;
        final names = a.containsKey('node')
            ? [a['node']! as String]
            : sim.nodes.keys.toList();
        for (final name in names) {
          final runtime = sim.node(name).runtime;
          final status = await runtime.status();
          if (status != a['status']) {
            final err = await runtime.lastError();
            throw TestFailure(
              "expected node '$name' to be ${a['status']}, it is $status"
              '${err.isNotEmpty ? ' ($err)' : ''}',
            );
          }
        }
      case 'expect_screen':
        final a = arg! as Map<String, Object?>;
        final name = _node(a);
        final cmd = sim.node(name).lastCommand('ui', 'screen');
        if (cmd == null) {
          throw TestFailure("node '$name' has not shown any screen");
        }
        final args = cmd.args;
        final template = args.isNotEmpty ? args[0] : null;
        final data = args.length > 1 ? args[1] : <String, Object?>{};
        if (template != a['template'] || !_subset(a['data'] ?? {}, data)) {
          throw TestFailure(
            "expected screen ${a['template']} ${a['data'] ?? {}} on '$name', "
            'last screen is $template $data',
          );
        }
      default:
        throw TestFailure("unknown step '$action'");
    }
  }

  void _only(String step, Map<String, Object?> arg, Set<String> keys) {
    final unknown = arg.keys.toSet().difference(keys);
    if (unknown.isNotEmpty) {
      throw TestFailure('$step: unknown key(s) ${unknown.toList()..sort()}');
    }
  }

  String _node(Map<String, Object?> arg) {
    if (arg.containsKey('node')) return arg['node']! as String;
    if (sim.nodes.length == 1) return sim.nodes.keys.single;
    throw TestFailure('this game has several nodes: say which one with node:');
  }

  Future<void> _scan(Object? arg) async {
    if (arg is! Map<String, Object?>) {
      throw TestFailure('scan takes a map: { player, team } or { uid }');
    }
    final unknown = arg.keys.toSet().difference({
      'node',
      'player',
      'team',
      'uid',
      'forged',
      'game',
    });
    if (unknown.isNotEmpty) {
      throw TestFailure('scan: unknown key(s) ${unknown.toList()..sort()}');
    }
    List<int>? payload;
    if (arg.containsKey('player')) {
      final team = arg['team'] as String?;
      if (team != null && !sim.teams.contains(team)) {
        throw TestFailure("scan: unknown team '$team'");
      }
      final teamId = team != null ? sim.teams.indexOf(team) + 1 : 0;
      var key = sim.gameKey;
      if (arg['forged'] == true) key = [for (final b in key) b ^ 0x5a];
      final gameId = (arg['game'] as int?) ?? sim.gameId;
      payload = encodeTag(
        PlayerTag(player: '${arg['player']}', team: teamId, gameId: gameId),
        key,
      );
    }
    final List<int> uid;
    if (arg['uid'] != null && '${arg['uid']}'.isNotEmpty) {
      final hex = '${arg['uid']}';
      uid = [
        for (var i = 0; i < hex.length; i += 2)
          int.parse(hex.substring(i, i + 2), radix: 16),
      ];
    } else if (arg.containsKey('player')) {
      uid = [
        0x04,
        ...sha256.convert(utf8.encode('${arg['player']}')).bytes.sublist(0, 6),
      ];
    } else {
      throw TestFailure('scan needs a player or a uid');
    }
    await sim.scan(_node(arg), uid, payload);
  }

  void _expect(Object? arg) {
    final spec = _eventFilter(arg);
    final events = sim.events;
    for (var i = cursor; i < events.length; i++) {
      if (_matches(events[i], spec)) {
        cursor = i + 1;
        return;
      }
    }
    throw TestFailure(
      'expected event $spec at or before ${sim.timeMs / 1000}s, not found',
    );
  }

  void _expectNo(Object? arg) {
    final spec = _eventFilter(arg);
    for (final e in sim.events.skip(cursor)) {
      if (_matches(e, spec)) {
        throw TestFailure('unexpected event: ${e.describe().trim()}');
      }
    }
  }
}

class TestResult {
  TestResult(this.name, this.passed, [this.message = '', this.log = const []]);
  final String name;
  final bool passed;
  final String message;
  final List<String> log;

  @override
  String toString() =>
      passed ? 'ok $name' : 'FAIL $name: $message\n  ${log.join('\n  ')}';
}

void _checkProblems(Simulation sim, String where) {
  if (sim.problems.isNotEmpty) {
    throw TestFailure(
      '$where: ${sim.problems.join('; ')} (see protocol/schema/events.yaml)',
    );
  }
}

/// The mode a test plays: `main:` and `modifiers:` name sibling mode folders;
/// `scenario:` a scenario package's folder, relative to the test file's, that
/// leads the game (decision P4R7).
Mode _composed(Mode mode, Map<String, Object?> spec, Directory folder) {
  final main = spec['main'];
  final modifiers = spec['modifiers'] ?? [];
  final scenario = spec['scenario'];
  if (main == null && (modifiers as List).isEmpty && scenario == null) {
    return mode;
  }
  if (modifiers is! List ||
      (main != null && main is! String) ||
      (scenario != null && scenario is! String)) {
    throw ModeError(
      'main is a mode folder name, modifiers a list of them and scenario a '
      'folder relative to the test',
    );
  }
  final parent = mode.dir.parent.path;
  final parts = [
    if (scenario != null) loadMode(Directory('${folder.path}/$scenario')),
    if (main != null) loadMode(Directory('$parent/$main')),
    mode,
    for (final m in modifiers) loadMode(Directory('$parent/$m')),
  ];
  return compose(parts.first, parts.sublist(1));
}

/// Runs one test file of [mode] with its nodes running [via].
Future<TestResult> runTest(
  AtalaiaCore core,
  EventSchema schema,
  Mode mode,
  File file,
  Via via,
) async {
  final Map<String, Object?> spec;
  try {
    spec =
        (plain(loadYaml(file.readAsStringSync())) as Map<String, Object?>?) ??
        {};
  } on YamlException catch (e) {
    return TestResult(file.path, false, 'invalid YAML: $e');
  }
  final name = (spec['name'] ?? file.path) as String;
  final teams = ((spec['teams'] as List?) ?? defaultTeams).cast<String>();
  Simulation? sim;
  try {
    final m = _composed(mode, spec, file.parent);
    final defaultNode = m.roles.keys.first;
    final nodeRoles = ((spec['nodes'] as Map?) ?? {defaultNode: defaultNode})
        .cast<String, String>();
    final params = m.resolveParams(
      (spec['params'] as Map<String, Object?>?) ?? {},
      teams,
    );
    sim = await Simulation.create(
      core,
      schema,
      m,
      nodeRoles,
      teams,
      params,
      seed: (spec['seed'] as int?) ?? 1,
      via: via,
    );
    final runner = _Runner(sim);
    if (spec['autostart'] != false) {
      await sim.start();
      _checkProblems(sim, 'start');
    }
    final steps = (spec['steps'] as List?) ?? [];
    for (var i = 0; i < steps.length; i++) {
      try {
        await runner.step(steps[i]);
      } on TestFailure catch (e) {
        throw TestFailure('step ${i + 1} ${steps[i]}: $e');
      }
      _checkProblems(sim, 'step ${i + 1} ${steps[i]}');
    }
    return TestResult(name, true);
  } on Exception catch (e) {
    final log = <String>[];
    if (sim != null) {
      log.addAll(sim.events.map((e) => e.describe()));
      for (final v in sim.nodes.values) {
        log.addAll(
          v.logs.map(
            (l) => '${''.padRight(10)}  ${v.name.padRight(12)} log: $l',
          ),
        );
      }
      log.addAll(
        sim.fieldLogs.map(
          (l) => '${''.padRight(10)}  ${controller.padRight(12)} log: $l',
        ),
      );
    }
    return TestResult(name, false, '$e', log);
  } finally {
    await sim?.close();
  }
}
