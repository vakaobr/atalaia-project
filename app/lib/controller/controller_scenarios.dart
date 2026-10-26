// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Scenarios on a phone controller (slice S7b of PE24): the Dart
/// counterpart of the Pi controller's
/// controller/atalaia_controller/scenario_service.py (plan phase 8; ADR-P4-6
/// as amended, decisions P4-1, P4R7, P4R8, P4R24).
///
/// The GM console's scenario builder sends a manifest (YAML or JSON text):
///
///     POST /api/v1/scenarios/check   its problems (GM or read token): the
///                                    validator's, then the compiled
///                                    field.lua's load check in the core
///     POST /api/v1/scenarios         GM: compile, check in the core and
///                                    install it as a mode package
///     GET  /api/v1/scenarios         the installed scenarios
///     GET  /api/v1/scenarios/{id}    GM: the manifest and the package
///
/// The validator and the compiler are the C core's (core/scenario/,
/// decision PE24-109), which the Pi calls too; the phone reads the
/// manifest's text itself (scenarios/scenario_manifest.dart): the same
/// problems for the shared vectors (protocol/vectors/scenario.json) and the
/// same package, byte for byte (protocol/vectors/scenario_compile.json). The manifest is kept next
/// to its package (setting `scenario.manifest:<id>`, M8-2); the names the
/// GM gives the boxes in the Join tab (P4R8, M6-7) are kept per game
/// (`scenario.nodes:<game id>`).
///
/// [ScenarioMeta] is a scenario package's `scenario` block (M7-8): what the
/// routing of objective events and the player view need, without reading
/// Lua.
library;

import 'dart:convert';

import '../modes/mode_catalog.dart';
import 'controller_checkin.dart';
import 'controller_engine.dart';
import 'controller_modes.dart';
import 'scenarios/scenario_manifest.dart' show loadText, pyStr;
import 'scenarios/scenario_package.dart';

const scenarioManifestKey = 'scenario.manifest:';
const scenarioNodesKey = 'scenario.nodes:';

/// The GM's choice for one game of who of a squad is told its objectives
/// (SQ-4).
const scenarioDisclosureKey = 'scenario.disclosure:';

/// Who of an objective's assignee is told it (SQ-3): every member, or only
/// the squad leaders.
const disclosures = ['members', 'leader'];
const objectiveRevealed = 'scenario.objective.revealed';

/// The scenario events whose objective decides who may read them.
const objectiveEvents = {
  'scenario.objective.completed',
  'scenario.objective.failed',
  objectiveRevealed,
};

/// What a player's view of an objective carries.
const _playerFields = [
  'id',
  'type',
  'name',
  'description',
  'i18n',
  'team',
  'squad',
  'visibility',
  'points',
  'win',
  'time_window',
];

/// The manifest has errors: [problems] lists them (HTTP 400).
class ScenarioRefused implements Exception {
  ScenarioRefused(this.problems);
  final List<Problem> problems;

  @override
  String toString() {
    final e = errors(problems);
    return e.isEmpty ? 'the scenario was refused' : e.join('; ');
  }

  /// The answer's body, as the Pi's exception handler gives it.
  Map<String, Object?> toJson() => {
    'detail': '$this',
    'problems': [for (final p in problems) p.toJson()],
  };
}

/// JSON data from the YAML 1.1 loader's values (BigInt as int, keys as
/// Python's str()).
Object? _plain(Object? v) => switch (v) {
  final BigInt b when b.isValidInt => b.toInt(),
  final Map<Object?, Object?> m => {
    for (final e in m.entries) pyStr(e.key): _plain(e.value),
  },
  final List<Object?> l => [for (final x in l) _plain(x)],
  _ => v,
};

/// A scenario package's mode.yaml: its names and its `scenario` block.
final class ScenarioMeta {
  const ScenarioMeta({
    required this.id,
    required this.name,
    required this.description,
    required this.i18n,
    required this.lang,
    required this.teams,
    required this.squads,
    required this.nodes,
    required this.objectives,
    this.reveal = 'all',
    this.disclosure = 'members',
  });

  final String id;
  final String name;
  final String description;
  final Map<String, Object?> i18n;
  final String lang;
  final List<Object?> teams;
  final int squads;
  final Map<String, Map<String, Object?>> nodes;

  /// By id, in the manifest's order.
  final Map<String, Map<String, Object?>> objectives;

  /// `active`: a dependent objective is known only when it opens (SQ-1).
  final String reveal;

  /// `leader`: only the assignee squad's leaders get the details (SQ-3).
  final String disclosure;

  /// Null for a package that is not a compiled scenario.
  static ScenarioMeta? parse(String modeYaml) {
    Object? doc;
    try {
      doc = _plain(loadText(modeYaml));
    } on Object {
      return null;
    }
    if (doc is! Map || doc['kind'] != 'scenario') return null;
    final block = doc['scenario'];
    if (block is! Map) return null;
    final objectives = <String, Map<String, Object?>>{
      for (final o in (block['objectives'] as List?) ?? const [])
        if (o is Map && o['id'] is String)
          o['id']! as String: o.cast<String, Object?>(),
    };
    final nodes = <String, Map<String, Object?>>{
      for (final e in ((block['nodes'] as Map?) ?? const {}).entries)
        if (e.value is Map)
          '${e.key}': (e.value as Map).cast<String, Object?>(),
    };
    final squads = block['squads'];
    return ScenarioMeta(
      id: pyStr(doc['id']),
      name: pyStr(doc['name'] ?? doc['id']),
      description: doc['description'] == null || doc['description'] == ''
          ? ''
          : pyStr(doc['description']),
      i18n: ((doc['i18n'] as Map?) ?? const {}).cast<String, Object?>(),
      lang: pyStr(block['lang'] ?? 'pt'),
      teams: List.of((block['teams'] as List?) ?? const []),
      squads: squads is int ? squads : 0,
      nodes: nodes,
      objectives: objectives,
      reveal: block['reveal'] == 'active' ? 'active' : 'all',
      disclosure: block['disclosure'] == 'leader' ? 'leader' : 'members',
    );
  }

  /// The boxes the GM names in the Join tab: name to role.
  Map<String, String> boxNodes() => {
    for (final e in nodes.entries)
      if (!_truthy(e.value['player'])) e.key: pyStr(e.value['role']),
  };

  Map<String, Object?> header() {
    final out = <String, Object?>{'id': id, 'name': name};
    if (description.isNotEmpty) out['description'] = description;
    final texts = <String, Object?>{};
    for (final e in i18n.entries) {
      final t = e.value;
      if (t is! Map) continue;
      final picked = {
        for (final k in t.entries)
          if (k.key == 'name' || k.key == 'description') '${k.key}': k.value,
      };
      if (picked.isNotEmpty) texts[e.key] = picked;
    }
    if (texts.isNotEmpty) out['i18n'] = texts;
    return out;
  }

  /// Everything mode.yaml says (the console's Join tab and feed);
  /// [gameDisclosure] is the game's (the GM's choice or the manifest's),
  /// `disclosure_default` the manifest's (SQ-4).
  Map<String, Object?> staffView([String? gameDisclosure]) => {
    ...header(),
    'lang': lang,
    'teams': teams,
    'squads': squads,
    'reveal': reveal,
    'disclosure': gameDisclosure ?? disclosure,
    'disclosure_default': disclosure,
    'nodes': nodes,
    'objectives': objectives.values.toList(),
  };

  /// The objectives this viewer may know (P4R24): a hidden one only once it
  /// is revealed, and with [gameDisclosure] `leader` only a squad leader gets
  /// the squad's (SQ-3).
  Map<String, Object?> playerView(
    ApiViewer? viewer,
    Map<String, Object?> game,
    Set<String> revealed, [
    String gameDisclosure = 'members',
  ]) {
    final staff = viewer != null && viewer.isStaffOf(game['id'] as int?);
    return {
      ...header(),
      'objectives': [
        for (final o in objectives.values)
          if (objectiveVisible(viewer, o, game, gameDisclosure) &&
              (staff ||
                  o['visibility'] != 'hidden' ||
                  revealed.contains(o['id'])))
            {
              for (final k in _playerFields)
                if (o.containsKey(k)) k: o[k],
            },
      ],
    };
  }
}

bool _truthy(Object? v) => switch (v) {
  null || false || 0 || '' => false,
  final List<Object?> l => l.isNotEmpty,
  final Map<Object?, Object?> m => m.isNotEmpty,
  _ => true,
};

String? _playerTeam(ApiViewer? viewer, Map<String, Object?> game) {
  if (viewer == null ||
      viewer.kind != 'player' ||
      viewer.gameId != game['id']) {
    return null;
  }
  final teams = (game['teams'] as List?) ?? const [];
  return viewer.team >= 1 && viewer.team <= teams.length
      ? '${teams[viewer.team - 1]}'
      : null;
}

/// What a viewer gets of an objective (visibility.py `objective_access`):
/// `full`, `notice` (a member of the squad whose leader alone is told: only
/// that the leader has orders) or `none`.
enum ObjectiveAccess { full, notice, none }

ObjectiveAccess objectiveAccess(
  ApiViewer? viewer,
  Map<String, Object?> objective,
  Map<String, Object?> game, [
  String disclosure = 'members',
]) {
  if (viewer != null && viewer.isStaffOf(game['id'] as int?)) {
    return ObjectiveAccess.full;
  }
  var vis = objective['visibility'] ?? 'public';
  final team = objective['team'], squad = objective['squad'];
  if (vis == 'hidden') {
    vis = squad != null ? 'squad' : (team != null ? 'team' : 'public');
  }
  if (vis == 'public' || team == null) return ObjectiveAccess.full;
  if (viewer == null || _playerTeam(viewer, game) != team) {
    return ObjectiveAccess.none;
  }
  if (vis == 'squad' && squad != null && pyStr(viewer.squad) != pyStr(squad)) {
    return ObjectiveAccess.none;
  }
  if (disclosure == 'leader' &&
      viewer.squad != 0 &&
      viewer.role != 'squad_leader') {
    return ObjectiveAccess.notice;
  }
  return ObjectiveAccess.full;
}

/// Whether a viewer may know this objective whole (visibility.py
/// `objective_visible`).
bool objectiveVisible(
  ApiViewer? viewer,
  Map<String, Object?> objective,
  Map<String, Object?> game, [
  String disclosure = 'members',
]) =>
    objectiveAccess(viewer, objective, game, disclosure) ==
    ObjectiveAccess.full;

/// An event as this viewer may see it (visibility.py `scenario_event`):
/// whole for staff and, for a scenario objective's event, for the players
/// the objective is for; else without its gm_only data.
Map<String, Object?> scenarioEvent(
  ApiViewer? viewer,
  Map<String, Object?> ev,
  Map<String, Object?>? game,
  Map<String, Map<String, Object?>>? objectives, [
  String disclosure = 'members',
]) {
  if (viewer != null && viewer.isStaffOf(game?['id'] as int?)) return ev;
  final data = ev['data'];
  if (game != null &&
      objectives != null &&
      objectives.isNotEmpty &&
      objectiveEvents.contains(ev['type']) &&
      data is Map) {
    final o = objectives[data['objective']];
    final access = o == null
        ? ObjectiveAccess.none
        : objectiveAccess(viewer, o, game, disclosure);
    if (access == ObjectiveAccess.full) return ev;
    if (access == ObjectiveAccess.notice && ev['type'] == objectiveRevealed) {
      // The squad's leader has orders (SQ-3): this member is told so, not
      // which.
      final pub = publicEvent(ev);
      return {
        ...pub,
        'data': {
          ...(pub['data']! as Map<String, Object?>),
          'leader_only': true,
        },
      };
    }
  }
  return publicEvent(ev);
}

/// The manifest of a request body `{"manifest": "<YAML or JSON text>"}`.
String manifestText(Object? body) {
  final text = body is Map ? body['manifest'] : null;
  if (text is! String) {
    throw ScenarioRefused([
      const Problem(
        '',
        'bad_manifest',
        'the request body is {"manifest": "<the scenario\'s YAML>"}',
      ),
    ]);
  }
  return text;
}

Map<String, Object?> _node(String name, Map<Object?, Object?> spec) {
  final level = spec['level'];
  return {
    'name': name,
    'role': _plain(spec['role']),
    'player': _truthy(spec['player']),
    if (level is int || level is BigInt || level is bool)
      'level': _plain(level),
  };
}

Map<String, Object?> _summary(Map<Object?, Object?> manifest) {
  final nodes = manifest['nodes'] is Map
      ? manifest['nodes']! as Map<Object?, Object?>
      : const <Object?, Object?>{};
  final objectives = manifest['objectives'] is List
      ? manifest['objectives']! as List<Object?>
      : const <Object?>[];
  return {
    'id': manifest['id'] is String ? manifest['id'] : null,
    'name': manifest['name'] is String ? manifest['name'] : null,
    'nodes': [
      for (final e in nodes.entries)
        if (e.value is Map)
          _node(pyStr(e.key), (e.value as Map).cast<Object?, Object?>()),
    ],
    'objectives': [
      for (final o in objectives)
        if (o is Map)
          {
            'id': _plain(o['id']),
            'type': _plain(o['type']),
            'name': _plain(o['name']),
          },
    ],
  };
}

const _jsonIntMax = 9007199254740992; // 2**53

/// True when JSON holds the value as it is (scenario_service.py
/// `_json_exact`).
bool _jsonExact(Object? v) => switch (v) {
  null || bool() || String() => true,
  final int i => i >= -_jsonIntMax && i <= _jsonIntMax,
  final BigInt b =>
    b >= BigInt.from(-_jsonIntMax) && b <= BigInt.from(_jsonIntMax),
  final double d => d.isFinite,
  final List<Object?> l => l.every(_jsonExact),
  final Map<Object?, Object?> m => m.entries.every(
    (e) => e.key is String && _jsonExact(e.value),
  ),
  _ => false,
};

/// The scenario services of an engine: what scenario_service.py does with
/// its controller.
class ControllerScenarios {
  ControllerScenarios(this.engine) {
    engine.scenarios = this;
  }

  final ControllerEngine engine;
  final _metaCache = <String, (int, ScenarioMeta?)>{};

  ControllerModes get _modes => engine.modes;

  /// The scenario a game's id leads with (its package's mode.yaml), or null.
  ScenarioMeta? meta(Object? modeId) {
    if (modeId is! String) return null;
    final cached = _metaCache[modeId];
    if (cached != null && cached.$1 == _modes.generation) return cached.$2;
    ScenarioMeta? meta;
    ModePackage? pkg;
    try {
      pkg = modeId.contains(modeSeparator) ? _modes.get(modeId) : null;
    } on ModeException {
      pkg = null;
    }
    if (pkg != null) meta = ScenarioMeta.parse(pkg.files['mode.yaml'] ?? '');
    _metaCache[modeId] = (_modes.generation, meta);
    return meta;
  }

  /// Every problem of a manifest, for the editor; never throws for a bad
  /// manifest: `ok` is false and `problems` say why.
  Map<String, Object?> check(String text) {
    Map<Object?, Object?> manifest;
    try {
      manifest = loadManifest(text);
    } on ManifestError catch (e) {
      return {
        'ok': false,
        'problems': [Problem('', 'bad_manifest', e.message).toJson()],
        'id': null,
        'name': null,
        'nodes': <Object?>[],
        'objectives': <Object?>[],
        'installed': null,
        'manifest': null,
      };
    }
    final core = engine.core;
    var problems = <Problem>[];
    if (core != null) {
      // One call into the core: the problems and, without errors, the package.
      final (found, package) = compilePackage(manifest, core);
      problems = [...found];
      if (package != null) {
        try {
          checkScripts(core, parseModePackage(package.files));
        } on ModeException catch (e) {
          problems.add(Problem('', 'lua_does_not_load', e.message));
        }
      }
    }
    // Without the core nothing is checked: not ok, and checked_in_core says
    // why (as on the Pi).
    final out = <String, Object?>{
      'ok': core != null && errors(problems).isEmpty,
      'problems': [for (final p in problems) p.toJson()],
      ..._summary(manifest),
    };
    out['manifest'] = _jsonExact(manifest) ? _plain(manifest) : null;
    final installed = out['id'] is String
        ? _modes.package(out['id']! as String)
        : null;
    out['installed'] = installed?.mode.version;
    out['checked_in_core'] = engine.core != null;
    return out;
  }

  bool _uses(Map<String, Object?>? game, String scenarioId) =>
      game != null &&
      game['state'] != 'ended' &&
      '${game['mode_id'] ?? ''}'.split(modeSeparator).contains(scenarioId);

  /// Compiles a manifest and installs its package; the manifest is kept
  /// next to it.
  Map<String, Object?> install(String text) {
    Map<Object?, Object?> manifest;
    try {
      manifest = loadManifest(text);
    } on ManifestError catch (e) {
      throw ScenarioRefused([Problem('', 'bad_manifest', e.message)]);
    }
    final core = engine.core;
    if (core == null) {
      throw ControllerError.unavailable(
        'the core library is not loaded, so scenarios cannot be checked or '
        'compiled',
      );
    }
    final (problems, compiled) = compilePackage(manifest, core);
    if (compiled == null) throw ScenarioRefused(problems);
    final package = compiled;
    final existing = _modes.package(package.id);
    if (existing != null && existing.kind != 'scenario') {
      throw ControllerError.conflict(
        '${package.id} is installed as a ${existing.kind}, not a scenario; '
        'give the scenario another id',
      );
    }
    final live = engine.liveGame;
    if (_uses(live, package.id)) {
      throw ControllerError.conflict(
        'game ${live!['id']} runs this scenario; end it before you replace '
        'the scenario',
      );
    }
    final pkg = _modes.install(package.files);
    engine.store.setSetting('$scenarioManifestKey${pkg.id}', text);
    return {
      ...describe(pkg, hasManifest: true),
      'warnings': [for (final p in problems) p.toJson()],
      'replaced': existing != null,
    };
  }

  /// Removes an installed scenario and its kept manifest (the site archived
  /// it: decision S20-8). Throws a conflict while the game that is not ended
  /// runs it; false when no scenario of that id is installed.
  bool uninstall(String scenarioId) {
    final pkg = _modes.package(scenarioId);
    if (pkg == null || pkg.kind != 'scenario') return false;
    final live = engine.liveGame;
    if (_uses(live, scenarioId)) {
      throw ControllerError.conflict(
        'game ${live!['id']} runs this scenario; end it before you remove '
        'the scenario',
      );
    }
    final removed = _modes.remove(scenarioId);
    engine.store.deleteSetting('$scenarioManifestKey$scenarioId');
    return removed;
  }

  Map<String, Object?> describe(ModePackage pkg, {required bool hasManifest}) {
    final m = ScenarioMeta.parse(pkg.files['mode.yaml'] ?? '');
    final out = <String, Object?>{
      'id': pkg.id,
      'version': pkg.mode.version,
      'name': pkg.mode.name,
      'description': pkg.mode.description,
      'i18n': pkg.mode.i18n,
      'params': pkg.mode.params,
      'manifest': hasManifest,
      'compiled': m != null,
    };
    if (m != null) {
      out.addAll({
        'lang': m.lang,
        'teams': m.teams,
        'squads': m.squads,
        'reveal': m.reveal,
        'disclosure': m.disclosure,
        'nodes': [
          for (final e in m.nodes.entries)
            _node(e.key, e.value.cast<Object?, Object?>()),
        ],
        'objectives': [
          for (final o in m.objectives.values)
            {
              'id': o['id'],
              'type': o['type'],
              'name': o['name'],
              'i18n': o['i18n'] ?? <String, Object?>{},
            },
        ],
      });
    }
    return out;
  }

  List<Map<String, Object?>> listing() => [
    for (final p in _modes.all())
      if (p.kind == 'scenario')
        describe(
          p,
          hasManifest:
              engine.store.getSetting('$scenarioManifestKey${p.id}') != null,
        ),
  ];

  /// The manifest (null for a package uploaded as files) and the package's
  /// files.
  Map<String, Object?> read(String scenarioId) {
    final pkg = _modes.package(scenarioId);
    if (pkg == null || pkg.kind != 'scenario') {
      throw ControllerError.notFound('no scenario $scenarioId');
    }
    final manifest = engine.store.getSetting('$scenarioManifestKey${pkg.id}');
    return {
      ...describe(pkg, hasManifest: manifest != null),
      'manifest_text': manifest,
      'files': Map.of(pkg.files),
    };
  }

  // --- per game: the boxes' names and what is revealed ----------------------

  Map<int, String> nodeNames(int gameId) {
    final raw = engine.store.getSetting('$scenarioNodesKey$gameId');
    if (raw == null || raw.isEmpty) return {};
    try {
      return {
        for (final e in (jsonDecode(raw) as Map).entries)
          int.parse('${e.key}'): '${e.value}',
      };
    } on Object {
      return {};
    }
  }

  /// Gives a box a scenario node's name; the name leaves any box that had it.
  Map<int, String> nameNode(int gameId, int nodeId, String name) {
    final names = {
      for (final e in nodeNames(gameId).entries)
        if (e.value != name) e.key: e.value,
    };
    names[nodeId] = name;
    final ids = names.keys.toList()..sort();
    engine.store.setSetting(
      '$scenarioNodesKey$gameId',
      jsonEncode({for (final k in ids) '$k': names[k]}),
    );
    return names;
  }

  /// Who of an objective's assignee is told it in this game (SQ-3, SQ-4): the
  /// GM's choice for the game, else the manifest's, else everyone.
  String disclosure(int gameId, ScenarioMeta? meta) {
    final raw = engine.store.getSetting('$scenarioDisclosureKey$gameId');
    if (raw != null && disclosures.contains(raw)) return raw;
    return meta?.disclosure ?? 'members';
  }

  /// The GM's choice from a request: `members`, `leader`, or null to go back
  /// to the manifest's.
  static String? checkDisclosure(Object? value) {
    if (value != null && !disclosures.contains(value)) {
      throw ControllerError(
        'disclosure: one of $disclosures, or null for the scenario\'s own',
      );
    }
    return value as String?;
  }

  void storeDisclosure(int gameId, String? value) {
    if (value == null) {
      engine.store.deleteSetting('$scenarioDisclosureKey$gameId');
    } else {
      engine.store.setSetting('$scenarioDisclosureKey$gameId', value);
    }
  }

  /// The objectives whose reveal is in the game's log.
  Set<String> revealed(int gameId) => {
    for (final e in engine.store.events(gameId, type: objectiveRevealed))
      pyStr((e['data'] as Map?)?['objective']),
  };
}
