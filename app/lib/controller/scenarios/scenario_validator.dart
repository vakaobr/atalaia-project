// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Checks a scenario manifest before it is compiled (ADR-P4-6's rules, as
/// amended; decisions P4R7, P4R8, P4R9) on the Android field controller: a
/// port of the Pi controller's
/// controller/atalaia_controller/scenarios/validator.py.
///
/// [validate] returns every problem it finds, each with the path of the
/// value (objectives[2].params.code), a short code that other
/// implementations match (protocol/vectors/scenario.json) and a sentence for
/// the GM. Errors stop the compiler; warnings do not. The paths, codes and
/// levels are the Pi's, in the Pi's order (protocol/vectors/
/// scenario_compile.json checks them); the sentences are close to the Pi's.
///
/// The Pi measures two things with its own code: a box's setup command as
/// Python's json.dumps writes it ([pyJsonLength]), and the scenario events
/// as atalaia_sim.codec encodes them (CBOR); the second is worked out here
/// from the fixed shape of those four events.
library;

import 'scenario_lua.dart';
import 'scenario_manifest.dart' as m;

const String levelError = 'error';
const String levelWarning = 'warning';

/// The largest params of a CMD (field_controller.dart, cmdParamsMax).
const int _cmdParamsMax = 127;

/// The largest CBOR payload in one LoRa packet (ATALAIA_RF_PAYLOAD_MAX).
const int _rfPayloadMax = 200;

/// One problem of a manifest.
class Problem {
  const Problem(this.path, this.code, this.message, [this.level = levelError]);

  /// Where: '' for the manifest itself, 'objectives[1].depends_on[0]'.
  final String path;

  /// What, for programs (protocol/vectors/scenario.json).
  final String code;

  /// What, for the GM.
  final String message;

  /// [levelError] or [levelWarning].
  final String level;

  Map<String, String> toJson() => {
    'path': path,
    'code': code,
    'message': message,
    'level': level,
  };

  @override
  String toString() =>
      '${path.isEmpty ? '' : '$path: '}$level: $message ($code)';
}

/// The errors among [problems].
List<Problem> errors(List<Problem> problems) => [
  for (final p in problems)
    if (p.level == levelError) p,
];

/// Every problem in the manifest (a parsed map), errors and warnings, in the
/// manifest's order.
List<Problem> validate(Object? manifest) {
  if (manifest is! Map<Object?, Object?>) {
    return const [
      Problem(
        '',
        'bad_manifest',
        'a scenario manifest is a map (id, version, name, nodes, objectives)',
      ),
    ];
  }
  return _Checker(manifest).run();
}

bool _isInt(Object? v) => m.pyIsInt(v);

bool _isNumber(Object? v) =>
    v is int || v is BigInt || (v is double && v.isFinite);

/// lo <= v <= hi for a number (a BigInt is past every bound here).
bool _within(Object? v, num lo, num hi) =>
    v is num && !(v is double && v.isNaN) && lo <= v && v <= hi;

final RegExp _controls = RegExp(r'[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]', unicode: true);

/// Control characters in a one-line text (a name): newlines, escapes, bidi
/// overrides.
bool _hasControls(String text) => _controls.hasMatch(text);

/// Whether a text holds half of a surrogate pair: a lone UTF-16 surrogate,
/// which no UTF-8 text holds (decision PE24-107). A pair is the character it
/// encodes, as in the Pi's texts once its loader has joined them.
bool _loneSurrogate(String text) {
  for (var i = 0; i < text.length; i++) {
    final c = text.codeUnitAt(i);
    if (c >= 0xD800 && c <= 0xDBFF) {
      final next = i + 1 < text.length ? text.codeUnitAt(i + 1) : 0;
      if (next < 0xDC00 || next > 0xDFFF) return true;
      i++;
    } else if (c >= 0xDC00 && c <= 0xDFFF) {
      return true;
    }
  }
  return false;
}

/// validator.py `_surrogates`: every text and key with half a surrogate
/// pair, where it is (a key: the map's path).
void _surrogates(
  Object? value,
  String path,
  List<Problem> out,
  Set<Object> seen,
) {
  if (value is String) {
    if (_loneSurrogate(value)) {
      out.add(
        Problem(
          path,
          'bad_unicode',
          'not valid Unicode: half of a surrogate pair (a character past '
              r'U+FFFF needs both halves, \ud83d\ude00)',
        ),
      );
    }
    return;
  }
  if ((value is! Map && value is! List) || !seen.add(value!)) return;
  if (value is List) {
    for (var i = 0; i < value.length; i++) {
      _surrogates(value[i], '$path[$i]', out, seen);
    }
    return;
  }
  for (final e in (value as Map<Object?, Object?>).entries) {
    final key = e.key;
    if (key is String && _loneSurrogate(key)) {
      out.add(
        Problem(
          path,
          'bad_unicode',
          'a key that is not valid Unicode: half of a surrogate pair',
        ),
      );
      continue;
    }
    _surrogates(
      e.value,
      path.isNotEmpty ? '$path.${m.pyStr(key)}' : m.pyStr(key),
      out,
      seen,
    );
  }
}

Map<Object?, Object?> _asMap(Object? v) =>
    v is Map<Object?, Object?> ? v : const {};

class _Checker {
  _Checker(this.mf);

  final Map<Object?, Object?> mf;
  final List<Problem> problems = [];
  List<String> teams = [];
  Object? squads = 0;
  Map<String, Map<Object?, Object?>> params = {};
  Map<String, Map<String, Object?>> nodes = {};
  final Map<String, int> ids = {};
  final Set<String> revealedBy = {};

  void err(String path, String code, String message) =>
      problems.add(Problem(path, code, message));

  void warn(String path, String code, String message) =>
      problems.add(Problem(path, code, message, levelWarning));

  int get _errorCount => errors(problems).length;

  void unknownKeys(
    Map<Object?, Object?> value,
    List<String> allowed,
    String path,
  ) {
    for (final key in value.keys) {
      if (!allowed.contains(key)) {
        final where = path.isNotEmpty ? '$path.${m.pyStr(key)}' : m.pyStr(key);
        err(
          where,
          'unknown_key',
          'unknown key ${m.pyRepr(key)} (allowed: ${allowed.join(', ')})',
        );
      }
    }
  }

  bool text(
    Object? value,
    String path,
    int maxBytes,
    bool required, {
    bool oneLine = true,
  }) {
    if (value == null) {
      if (required) err(path, 'missing', 'required');
      return false;
    }
    if (value is! String || (required && m.pyBlank(value))) {
      err(path, 'bad_text', 'must be a non-empty text');
      return false;
    }
    if (m.utf8Length(value) > maxBytes) {
      err(path, 'too_long', 'at most $maxBytes bytes');
      return false;
    }
    if (oneLine && _hasControls(value)) {
      err(path, 'bad_text', 'must be one line, without control characters');
      return false;
    }
    return true;
  }

  // -- the manifest --

  List<Problem> run() {
    // Half a surrogate pair anywhere: said alone, as on the Pi (PE24-107).
    _surrogates(mf, '', problems, Set.identity());
    if (problems.isNotEmpty) return problems;
    unknownKeys(mf, m.topKeys, '');
    checkId();
    var version = mf['version'];
    if (_isInt(version) || version is double) version = m.pyStr(version);
    text(version, 'version', m.versionMax, true);
    text(mf['name'], 'name', m.nameMax, true);
    text(
      mf['description'],
      'description',
      m.descriptionMax,
      false,
      oneLine: false,
    );
    text(mf['author'], 'author', m.nameMax, false);
    final lang = m.pyGet(mf, 'lang', 'pt');
    if (!m.langs.contains(lang)) {
      err(
        'lang',
        'bad_lang',
        "the boxes' screens are in ${m.langs.join(' or ')}",
      );
    }
    teams = checkTeams();
    var squads = m.pyGet(mf, 'squads', 0);
    if (!_isInt(squads) || !_within(squads, 0, m.squadsMax)) {
      err(
        'squads',
        'bad_squads',
        'a number of squads per team, 0 (none) to ${m.squadsMax}',
      );
      squads = 0;
    }
    this.squads = squads;
    params = checkParams();
    checkI18n(mf['i18n'], 'i18n', const ['name', 'description', 'params']);
    nodes = checkNodes();
    final objectives = mf['objectives'];
    if (objectives is! List<Object?> || objectives.isEmpty) {
      err(
        'objectives',
        objectives == null ? 'missing' : 'bad_objectives',
        'a list of at least one objective',
      );
      return problems;
    }
    if (objectives.length > m.objectivesMax) {
      err('objectives', 'too_many', 'at most ${m.objectivesMax} objectives');
    }
    for (var i = 0; i < objectives.length; i++) {
      final o = objectives[i];
      final oid = o is Map<Object?, Object?> ? o['id'] : null;
      if (oid is String && m.objectiveIdPattern.hasMatch(oid)) {
        if (ids.containsKey(oid)) {
          err(
            'objectives[$i].id',
            'duplicate_id',
            '${m.pyRepr(oid)} is already the id of objectives[${ids[oid]}]',
          );
        } else {
          ids[oid] = i;
        }
      }
    }
    for (final o in objectives) {
      final effect = o is Map<Object?, Object?> ? o['effect'] : null;
      if (effect is Map<Object?, Object?> &&
          effect['reveal'] is List<Object?>) {
        revealedBy.addAll(
          (effect['reveal']! as List<Object?>).whereType<String>(),
        );
      }
    }
    final targeted = <String, int>{};
    for (var i = 0; i < objectives.length; i++) {
      checkObjective(i, objectives[i], targeted);
    }
    checkCycles(objectives);
    for (final name in nodes.keys) {
      if (!targeted.containsKey(name)) {
        warn('nodes.$name', 'unused_node', 'no objective targets this node');
      }
    }
    return problems;
  }

  void checkId() {
    final sid = mf['id'];
    if (sid == null) {
      err('id', 'missing', 'required: the package id, like org.club.foxhound');
    } else if (sid is! String || !m.scenarioIdPattern.hasMatch(sid)) {
      err(
        'id',
        'bad_id',
        'a package id like org.club.foxhound: lowercase letters, digits, - and _, '
            'in at least two parts joined by dots',
      );
    } else if (m.utf8Length(sid) > m.scenarioIdMax) {
      err(
        'id',
        'id_too_long',
        'at most ${m.scenarioIdMax} bytes, so that '
            "$sid+${m.objectivesPackage} fits a join's ${m.modeIdMax}",
      );
    } else if (sid == m.objectivesPackage || sid.startsWith('org.atalaia.')) {
      err(
        'id',
        'bad_id',
        "org.atalaia. is the built-in modes' namespace: use your club's",
      );
    }
  }

  List<String> checkTeams() {
    final teams = m.pyGet(mf, 'teams', const ['red', 'blue']);
    if (teams is! List<Object?> ||
        teams.isEmpty ||
        teams.length > m.teamsMax ||
        !teams.every(
          (t) =>
              t is String &&
              m.utf8Length(t) > 0 &&
              m.utf8Length(t) <= m.teamNameMax &&
              !_hasControls(t),
        )) {
      err(
        'teams',
        'bad_teams',
        'a list of 1 to ${m.teamsMax} team names of 1 to ${m.teamNameMax} '
            'bytes, as the game names its teams (red, blue, ...)',
      );
      return teams is List<Object?> ? teams.whereType<String>().toList() : [];
    }
    final names = teams.cast<String>();
    if (names.toSet().length != names.length) {
      err('teams', 'bad_teams', 'a team is named twice');
    }
    return [...names];
  }

  Map<String, Map<Object?, Object?>> checkParams() {
    final params = mf['params'];
    if (params == null) return {};
    if (params is! Map<Object?, Object?>) {
      err('params', 'bad_params', 'a map of parameter names to their schema');
      return {};
    }
    final good = <String, Map<Object?, Object?>>{};
    for (final MapEntry(key: name, value: spec) in params.entries) {
      final path = 'params.${m.pyStr(name)}';
      if (name is! String || !m.paramNamePattern.hasMatch(name)) {
        err(path, 'bad_name', '1-32 of a-z, 0-9 and _, starting with a letter');
        continue;
      }
      if (spec is! Map<Object?, Object?>) {
        err(
          path,
          'bad_params',
          'a map: { type: int, min, max, default, label }',
        );
        continue;
      }
      unknownKeys(spec, const [
        'type',
        'min',
        'max',
        'default',
        'label',
        'gm_only',
      ], path);
      if (spec['type'] != 'int') {
        err(
          '$path.type',
          'bad_param_type',
          "a scenario's parameters are int (whole numbers): "
              "objectives' points",
        );
        continue;
      }
      final lo = m.pyGet(spec, 'min', 0);
      final hi = m.pyGet(spec, 'max', m.pointsMax);
      final fallback = spec['default'];
      if (!_isInt(lo) ||
          !_isInt(hi) ||
          !_within(lo, 0, m.pointsMax) ||
          !_within(hi, lo is int ? lo : 0, m.pointsMax)) {
        err(
          path,
          'bad_range',
          'min and max are whole numbers from 0 to ${m.pointsMax}, min <= max',
        );
        continue;
      }
      if (!_isInt(fallback) || !_within(fallback, lo! as int, hi! as int)) {
        err('$path.default', 'bad_default', 'a whole number from $lo to $hi');
        continue;
      }
      text(spec['label'], '$path.label', m.nameMax * 2, false);
      if (m.pyGet(spec, 'gm_only', false) is! bool) {
        err('$path.gm_only', 'bad_bool', 'true or false');
      }
      good[name] = spec;
    }
    return good;
  }

  void checkI18n(Object? i18n, String path, List<String> keys) {
    if (i18n == null) return;
    if (i18n is! Map<Object?, Object?>) {
      err(path, 'bad_i18n', 'a map of a language (pt) to its texts');
      return;
    }
    for (final MapEntry(key: lang, value: strings) in i18n.entries) {
      final where = '$path.${m.pyStr(lang)}';
      if (!m.translations.contains(lang)) {
        err(
          where,
          'bad_lang',
          'texts are in English with translations in ${m.translations.join(', ')}',
        );
        continue;
      }
      if (strings is! Map<Object?, Object?>) {
        err(where, 'bad_i18n', 'a map of ${keys.join(', ')}');
        continue;
      }
      unknownKeys(strings, keys, where);
      text(strings['name'], '$where.name', m.nameMax, false);
      text(
        strings['description'],
        '$where.description',
        m.descriptionMax,
        false,
        oneLine: false,
      );
      final labels = strings['params'];
      if (labels != null && keys.contains('params')) {
        if (labels is! Map<Object?, Object?>) {
          err(
            '$where.params',
            'bad_i18n',
            'a map of parameter names to labels',
          );
          continue;
        }
        final declared = mf['params'];
        for (final MapEntry(key: name, value: label) in labels.entries) {
          if (declared is! Map<Object?, Object?> ||
              !m.pyHasKey(declared, name)) {
            err(
              '$where.params.${m.pyStr(name)}',
              'unknown_param',
              '${m.pyRepr(name)} is not a parameter',
            );
          } else {
            text(label, '$where.params.${m.pyStr(name)}', m.nameMax * 2, true);
          }
        }
      }
    }
  }

  Map<String, Map<String, Object?>> checkNodes() {
    final nodes = mf['nodes'];
    if (nodes == null) return {};
    if (nodes is! Map<Object?, Object?>) {
      err(
        'nodes',
        'bad_nodes',
        'a map of node names to { role: objective } or { role: bomb_site }',
      );
      return {};
    }
    if (nodes.length > m.nodesMax) {
      err('nodes', 'too_many', 'at most ${m.nodesMax} nodes');
    }
    final good = <String, Map<String, Object?>>{};
    for (final MapEntry(key: name, value: spec) in nodes.entries) {
      final path = 'nodes.${m.pyStr(name)}';
      if (name is! String ||
          m.pyBlank(name) ||
          m.utf8Length(name) > m.nodeNameMax ||
          _hasControls(name)) {
        err(
          path,
          'bad_name',
          "a node's name: 1 to ${m.nodeNameMax} bytes on one line, as the "
              'GM names the box in the console',
        );
        continue;
      }
      if (spec is! Map<Object?, Object?>) {
        err(
          path,
          'bad_node',
          'a map: { role: objective }, { role: bomb_site } or '
              '{ player: true, role: vip }',
        );
        continue;
      }
      unknownKeys(spec, const ['role', 'player', 'level'], path);
      final player = m.pyGet(spec, 'player', false);
      var role = spec['role'];
      if (player is! bool) {
        err('$path.player', 'bad_bool', 'true or false');
        continue;
      }
      if (player) {
        role = m.pyGet(spec, 'role', 'vip');
        if (role is! String || !m.playerRolePattern.hasMatch(role)) {
          err(
            '$path.role',
            'bad_role',
            "a player's check-in role: 1-24 of a-z, 0-9 and _",
          );
          continue;
        }
      } else if (!m.nodeRoles.contains(role)) {
        err(
          '$path.role',
          'bad_role',
          'a box runs ${m.objectivesPackage}: role '
              '${m.nodeRoles.join(' or ')} (a player: player: true)',
        );
        continue;
      }
      final level = spec['level'];
      if (level != null &&
          (player || !_isInt(level) || !_within(level, 0, m.levelsMax - 1))) {
        // The level of a multi-story field the box goes on (ML-8); a player
        // has none.
        err(
          '$path.level',
          'bad_level',
          "a box's level of the field, 0 to ${m.levelsMax - 1}",
        );
        continue;
      }
      good[name] = {'role': role, 'player': player};
    }
    return good;
  }

  // -- one objective --

  void checkObjective(int i, Object? o, Map<String, int> targeted) {
    final path = 'objectives[$i]';
    if (o is! Map<Object?, Object?>) {
      err(
        path,
        'bad_objective',
        'an objective is a map: { id, type, name, ... }',
      );
      return;
    }
    final before = _errorCount;
    unknownKeys(o, m.objectiveKeys, path);
    final oid = o['id'];
    if (oid == null) {
      err('$path.id', 'missing', 'required');
    } else if (oid is! String || !m.objectiveIdPattern.hasMatch(oid)) {
      err(
        '$path.id',
        'bad_id',
        '1-24 of a-z, 0-9 and _, starting with a letter (it goes in every '
            'scenario event)',
      );
    }
    text(o['name'], '$path.name', m.nameMax, true);
    text(
      o['description'],
      '$path.description',
      m.descriptionMax,
      false,
      oneLine: false,
    );
    checkI18n(o['i18n'], '$path.i18n', const ['name', 'description']);
    final kind = o['type'];
    final otype = kind is String ? m.objectiveTypes[kind] : null;
    final typeNames = m.objectiveTypes.keys.join(', ');
    if (kind == null) {
      err('$path.type', 'missing', 'required: one of $typeNames');
    } else if (otype == null) {
      err(
        '$path.type',
        'unknown_type',
        '${m.pyRepr(kind)} is not an objective type ($typeNames)',
      );
    }
    final team = checkAssignee(o, path, otype);
    if (otype != null) {
      checkTarget(o, path, otype, targeted, i);
      checkTypeParams(o, path, otype);
    }
    checkVisibility(o, path, team);
    checkRefs(o['depends_on'], '$path.depends_on', oid);
    checkWindow(o, path, otype);
    checkEffect(o, path, oid);
    if (otype != null &&
        m.nodeRoles.contains(otype.target) &&
        _errorCount == before) {
      checkSizes(o, path); // only with no other error: its setup can be built
    }
    if (oid is String && m.objectiveIdPattern.hasMatch(oid)) {
      checkEvents(oid, path);
    }
  }

  String? checkAssignee(
    Map<Object?, Object?> o,
    String path,
    m.ObjectiveType? otype,
  ) {
    final raw = o['assignee'];
    if (raw != null && raw is! Map<Object?, Object?>) {
      err('$path.assignee', 'bad_assignee', 'a map: { team, squad }');
      return null;
    }
    final assignee = raw is Map<Object?, Object?>
        ? raw
        : const <Object?, Object?>{};
    unknownKeys(assignee, const ['team', 'squad'], '$path.assignee');
    Object? team = assignee['team'];
    final squad = assignee['squad'];
    if (team == null) {
      if (otype != null && otype.needsTeam) {
        err(
          '$path.assignee.team',
          'missing_team',
          '${m.pyStr(o['type'])} is for one team: name it (${teams.join(', ')})',
        );
      }
    } else if (!teams.any((t) => m.pyEq(t, team))) {
      err(
        '$path.assignee.team',
        'unknown_team',
        "${m.pyRepr(team)} is not one of the scenario's teams "
            '(${teams.join(', ')})',
      );
      team = null;
    }
    if (squad != null) {
      if (team == null && assignee['team'] == null) {
        err(
          '$path.assignee.squad',
          'squad_needs_team',
          'a squad belongs to a team: name the team',
        );
      } else if (m.pyEq(squads, 0)) {
        err(
          '$path.assignee.squad',
          'unknown_squad',
          'the scenario has no squads (squads: 0)',
        );
      } else if (!_isInt(squad) || !_within(squad, 1, squads! as int)) {
        err(
          '$path.assignee.squad',
          'unknown_squad',
          'squads are numbers, 1 to $squads',
        );
      }
    }
    return team is String ? team : null;
  }

  void checkTarget(
    Map<Object?, Object?> o,
    String path,
    m.ObjectiveType otype,
    Map<String, int> targeted,
    int i,
  ) {
    final target = o['target'];
    final type = m.pyStr(o['type']);
    if (otype.target == null) {
      if (target != null) {
        err('$path.target', 'unexpected_target', '$type has no target');
      }
      return;
    }
    if (target == null) {
      err(
        '$path.target',
        'missing_target',
        'required: a node of the nodes map',
      );
      return;
    }
    final node = target is String ? nodes[target] : null;
    if (node == null) {
      final raw = mf['nodes'];
      if (target is! String ||
          raw is! Map<Object?, Object?> ||
          !raw.containsKey(target)) {
        err(
          '$path.target',
          'unknown_node',
          '${m.pyRepr(target)} is not in the nodes map',
        );
      }
      return;
    }
    final name = target as String;
    if (otype.target == 'player') {
      if (node['player'] != true) {
        err(
          '$path.target',
          'wrong_role',
          '$type targets a player '
              '(nodes.$name: { player: true, role: vip })',
        );
      }
    } else if (node['player'] == true || node['role'] != otype.target) {
      err(
        '$path.target',
        'wrong_role',
        '$type needs a node with the role ${otype.target}',
      );
    } else if (targeted.containsKey(name)) {
      err(
        '$path.target',
        'node_shared',
        '${m.pyRepr(name)} is already the target of '
            'objectives[${targeted[name]}]: a box serves one objective',
      );
    } else {
      targeted[name] = i;
    }
    if (node['player'] == true) {
      targeted.putIfAbsent(
        name,
        () => i,
      ); // a VIP may be escorted to more than one place
    }
  }

  void checkTypeParams(
    Map<Object?, Object?> o,
    String path,
    m.ObjectiveType otype,
  ) {
    var params = o['params'];
    params ??= const <Object?, Object?>{};
    if (params is! Map<Object?, Object?>) {
      err('$path.params', 'bad_params', "a map of the type's parameters");
      return;
    }
    final type = m.pyStr(o['type']);
    for (final name in params.keys) {
      if (!otype.params.containsKey(name)) {
        final takes = otype.params.isEmpty
            ? 'no parameters'
            : otype.params.keys.join(', ');
        err(
          '$path.params.${m.pyStr(name)}',
          'unknown_param',
          '$type takes $takes',
        );
      }
    }
    for (final MapEntry(key: name, value: spec) in otype.params.entries) {
      final where = '$path.params.$name';
      if (!params.containsKey(name)) {
        if (spec.required) err(where, 'missing_param', '$type needs $name');
        continue;
      }
      final value = params[name];
      switch (spec.kind) {
        case 'int':
          if (!_isInt(value) || !_within(value, spec.lo, spec.hi)) {
            err(
              where,
              'bad_param',
              'a whole number from ${spec.lo} to ${spec.hi}',
            );
          }
        case 'bool':
          if (value is! bool) err(where, 'bad_param', 'true or false');
        case 'code':
          if (_isInt(value)) {
            err(
              where,
              'bad_param',
              'write the code in quotes ("0815"), so that leading zeros stay',
            );
          } else if (value is! String || !m.codePattern.hasMatch(value)) {
            err(where, 'bad_param', '1 to 8 digits');
          }
        case 'destination':
          checkDestination(value, where);
      }
    }
  }

  void checkDestination(Object? d, String path) {
    if (d is! Map<Object?, Object?>) {
      err(
        path,
        'bad_destination',
        '{ lat, lon, radius_m } or { points: [[lat, lon], ...] }',
      );
      return;
    }
    if (d.containsKey('points')) {
      unknownKeys(d, const ['points'], path);
      checkPolygon(d['points'], '$path.points');
      return;
    }
    unknownKeys(d, const ['lat', 'lon', 'radius_m'], path);
    for (final (key, limit) in const [('lat', 90), ('lon', 180)]) {
      final v = d[key];
      if (!_isNumber(v) || !_within(v, -limit, limit)) {
        err('$path.$key', 'bad_destination', 'degrees, -$limit to $limit');
      }
    }
    final r = d['radius_m'];
    if (!_isNumber(r) || !(r is num && r > 0 && r <= 10000)) {
      err(
        '$path.radius_m',
        'bad_destination',
        'a radius in metres, more than 0 and at most 10000',
      );
    } else if (r < m.radiusWarnM) {
      warn(
        '$path.radius_m',
        'small_radius',
        "under ${m.radiusWarnM} m: a phone's GPS is rarely "
            'that precise, so the VIP may never be seen inside',
      );
    }
  }

  void checkPolygon(Object? points, String path) {
    if (points is! List<Object?> ||
        points.length < 3 ||
        points.length > m.polygonMax) {
      err(
        path,
        'bad_polygon',
        'a list of 3 to ${m.polygonMax} [lat, lon] points',
      );
      return;
    }
    final good = <(double, double)>[];
    for (var j = 0; j < points.length; j++) {
      final p = points[j];
      if (p is! List<Object?> ||
          p.length != 2 ||
          !_isNumber(p[0]) ||
          !_isNumber(p[1]) ||
          !_within(p[0], -90, 90) ||
          !_within(p[1], -180, 180)) {
        err('$path[$j]', 'bad_polygon', '[lat, lon] in degrees');
        return;
      }
      good.add(((p[0]! as num).toDouble(), (p[1]! as num).toDouble()));
    }
    if (!_simple(good)) {
      err(
        path,
        'polygon_not_simple',
        "the polygon's edges cross or touch, or it has no area: list "
            'its corners in order around it',
      );
    }
  }

  void checkVisibility(Map<Object?, Object?> o, String path, String? team) {
    final vis = m.pyGet(o, 'visibility', m.defaultVisibility(o));
    final assignee = _asMap(o['assignee']);
    if (!m.visibilities.any((v) => m.pyEq(v, vis))) {
      err(
        '$path.visibility',
        'bad_visibility',
        'one of ${m.visibilities.join(', ')}',
      );
    } else if (vis == 'team' && assignee['team'] == null) {
      err(
        '$path.visibility',
        'visibility_needs_team',
        "team: name the assignee's team",
      );
    } else if (vis == 'squad' && assignee['squad'] == null) {
      err(
        '$path.visibility',
        'visibility_needs_squad',
        "squad: name the assignee's squad",
      );
    } else if (vis == 'hidden' &&
        !m.pyTruthy(o['depends_on']) &&
        !(o['id'] is String && revealedBy.contains(o['id']))) {
      err(
        '$path.visibility',
        'never_revealed',
        'a hidden objective is revealed when what it '
            "depends_on is completed, or by another's effect.reveal: it has neither",
      );
    }
  }

  void checkRefs(Object? refs, String path, Object? oid) {
    if (refs == null) return;
    if (refs is! List<Object?>) {
      err(path, 'bad_reference', 'a list of objective ids');
      return;
    }
    final seen = <String?>{};
    for (var j = 0; j < refs.length; j++) {
      final ref = refs[j];
      if (m.pyEq(ref, oid)) {
        err('$path[$j]', 'self_reference', 'an objective cannot name itself');
      } else if (ref is! String || !ids.containsKey(ref)) {
        err(
          '$path[$j]',
          'unknown_reference',
          '${m.pyRepr(ref)} is not an objective id',
        );
      } else if (seen.contains(ref)) {
        err('$path[$j]', 'bad_reference', '${m.pyRepr(ref)} is named twice');
      }
      seen.add(ref is String ? ref : null);
    }
  }

  void checkWindow(
    Map<Object?, Object?> o,
    String path,
    m.ObjectiveType? otype,
  ) {
    final w = o['time_window'];
    final where = '$path.time_window';
    final type = m.pyStr(o['type']);
    if (w == null) {
      if (otype != null && otype.needsEnd) {
        err(
          where,
          'missing_end',
          "$type is judged at its time window's end: "
              'give time_window.end_min',
        );
      }
      return;
    }
    if (w is! Map<Object?, Object?>) {
      err(where, 'bad_time_window', 'a map: { start_min, end_min }');
      return;
    }
    unknownKeys(w, const ['start_min', 'end_min'], where);
    final start = m.pyGet(w, 'start_min', 0);
    final end = w['end_min'];
    if (!_isInt(start) || !_within(start, 0, m.windowMaxMin)) {
      err(
        '$where.start_min',
        'bad_time_window',
        "minutes from the game's start, 0 to ${m.windowMaxMin}",
      );
      return;
    }
    if (end == null) {
      if (otype != null && otype.needsEnd) {
        err(
          '$where.end_min',
          'missing_end',
          "$type is judged at its time window's end",
        );
      }
      return;
    }
    if (!_isInt(end) || !_within(end, 1, m.windowMaxMin)) {
      err(
        '$where.end_min',
        'bad_time_window',
        "minutes from the game's start, 1 to ${m.windowMaxMin}",
      );
    } else if ((start! as int) >= (end as int)) {
      err(where, 'bad_time_window', 'start_min must be before end_min');
    }
  }

  void checkEffect(Map<Object?, Object?> o, String path, Object? oid) {
    final effect = o['effect'];
    final where = '$path.effect';
    if (effect == null) return;
    if (effect is! Map<Object?, Object?>) {
      err(where, 'bad_effect', 'a map: { points, win, reveal }');
      return;
    }
    unknownKeys(effect, const ['points', 'win', 'reveal'], where);
    final points = effect['points'];
    if (points is Map<Object?, Object?>) {
      unknownKeys(points, const ['param'], '$where.points');
      final name = points['param'];
      if (name is! String || !params.containsKey(name)) {
        err(
          '$where.points.param',
          'unknown_param',
          "${m.pyRepr(name)} is not one of the scenario's params",
        );
      }
    } else if (points != null &&
        (!_isInt(points) || !_within(points, 0, m.pointsMax))) {
      err(
        '$where.points',
        'bad_points',
        'whole points, 0 to ${m.pointsMax} (score.add takes '
            'integers), or { param: name }',
      );
    }
    if (m.pyGet(effect, 'win', false) is! bool) {
      err('$where.win', 'bad_bool', 'true or false');
    }
    checkRefs(effect['reveal'], '$where.reveal', oid);
  }

  /// The depends_on graph is a DAG (Kahn's topological sort); every
  /// objective on a cycle is named.
  void checkCycles(List<Object?> objectives) {
    final deps = <String, Set<String>>{};
    for (final o in objectives) {
      if (o is Map<Object?, Object?> &&
          o['id'] is String &&
          ids.containsKey(o['id'])) {
        final id = o['id']! as String;
        final refs = o['depends_on'] is List<Object?>
            ? o['depends_on']! as List<Object?>
            : const <Object?>[];
        deps
            .putIfAbsent(id, () => {})
            .addAll(
              refs.whereType<String>().where(
                (r) => ids.containsKey(r) && r != id,
              ),
            );
      }
    }
    final left = {
      for (final e in deps.entries) e.key: {...e.value},
    };
    final ready = [
      for (final e in left.entries)
        if (e.value.isEmpty) e.key,
    ];
    while (ready.isNotEmpty) {
      final done = ready.removeLast();
      left.remove(done);
      for (final e in left.entries) {
        if (e.value.remove(done) && e.value.isEmpty) ready.add(e.key);
      }
    }
    // What is left is on a cycle or waits for one; name those on a cycle.
    final onCycle = left.keys.toList()
      ..sort((a, b) => ids[a]!.compareTo(ids[b]!));
    for (final oid in onCycle) {
      if (_reaches(oid, oid, left)) {
        err(
          'objectives[${ids[oid]}].depends_on',
          'cycle',
          "${m.pyRepr(oid)} depends on itself through ${_cycle(oid, left).join(' -> ')}",
        );
      }
    }
  }

  /// The setup command, as it is sent after a reboot (the longest), fits a
  /// box's CMD buffer.
  void checkSizes(Map<Object?, Object?> o, String path) {
    var longest = 'red';
    var longestBytes = -1;
    for (final t in teams) {
      if (m.utf8Length(t) > longestBytes) {
        longest = t;
        longestBytes = m.utf8Length(t);
      }
    }
    final rawLang = mf['lang'];
    final label =
        m.translated(o, m.langs.contains(rawLang) ? rawLang : 'pt') ?? '';
    final setup = setupCommand(o, m.pyGet(mf, 'lang', 'pt'), label);
    // What the runtime adds after a reboot, by kind (runtime.lua, setup()).
    final extra = switch (setup['kind']) {
      'capture' => {'holder': longest},
      'tags' => setup.containsKey('team') ? {'have': 100} : <String, Object?>{},
      'bomb' => {'armed': longest, 'left': 3600},
      _ => <String, Object?>{},
    };
    final size = pyJsonLength({'name': 'setup', ...setup, ...extra});
    if (size > _cmdParamsMax) {
      err(
        '$path.name',
        'setup_too_large',
        "the box's setup takes $size bytes, more than the "
            "$_cmdParamsMax of a command: shorten the name in the boxes' language",
      );
    }
  }

  void checkEvents(String oid, String path) {
    final sid = mf['id'] is String ? mf['id']! as String : '';
    // The four scenario events as atalaia_sim.codec.encode_event writes them
    // with the largest envelope (node 0, seq 0xFFFF, t 0xFFFFFFFF, team 8,
    // prio critical: the events' own): a map of 6 (1), node (2), seq (4),
    // t (6), type (3: ids 42 to 45), team (2), the data key (1), then the
    // data map. Data keys: objective 34 (2 bytes), squad 2, reason 3 (1
    // byte), scenario 35 (2 bytes).
    const envelope = 1 + 2 + 4 + 6 + 3 + 2 + 1;
    final events = <(String, List<(int, String)>)>[
      ('scenario.objective.completed', [(2, oid), (1, '16')]),
      ('scenario.objective.failed', [(2, oid), (1, '16'), (1, 'captured')]),
      ('scenario.objective.revealed', [(2, oid), (1, '16')]),
      ('scenario.started', [(2, sid)]),
    ];
    for (final (type, data) in events) {
      var size = envelope + _cborHead(data.length);
      for (final (keyBytes, value) in data) {
        final bytes = m.utf8Length(value);
        size += keyBytes + _cborHead(bytes) + bytes;
      }
      if (size > _rfPayloadMax) {
        err(
          path,
          'event_too_large',
          "$type takes $size bytes, more than a LoRa payload's "
              '$_rfPayloadMax',
        );
      }
    }
  }
}

/// The length of a CBOR head for a count or length n.
int _cborHead(int n) => n < 24
    ? 1
    : n < 0x100
    ? 2
    : n < 0x10000
    ? 3
    : n < 0x100000000
    ? 5
    : 9;

bool _reaches(String start, String goal, Map<String, Set<String>> graph) {
  final seen = <String>{};
  final stack = [...?graph[start]];
  while (stack.isNotEmpty) {
    final n = stack.removeLast();
    if (n == goal) return true;
    if (!seen.contains(n) && graph.containsKey(n)) {
      seen.add(n);
      stack.addAll(graph[n]!);
    }
  }
  return false;
}

/// One cycle through start, for the message: start -> ... -> start.
List<String> _cycle(String start, Map<String, Set<String>> graph) {
  final path = [start];
  final seen = {start};
  bool walk(String n) {
    for (final next in (graph[n]?.toList() ?? <String>[])..sort()) {
      if (next == start) {
        path.add(start);
        return true;
      }
      if (!seen.contains(next) && graph.containsKey(next)) {
        seen.add(next);
        path.add(next);
        if (walk(next)) return true;
        path.removeLast();
      }
    }
    return false;
  }

  walk(start);
  return path;
}

/// A simple polygon: no two edges cross or touch (except neighbours at
/// their shared corner), and an area.
bool _simple(List<(double, double)> points) {
  final n = points.length;
  var area = 0.0;
  for (var i = 0; i < n; i++) {
    final a = points[i], b = points[(i + 1) % n];
    area += a.$2 * b.$1 - b.$2 * a.$1;
  }
  if (area.abs() < 1e-12) return false;
  for (var i = 0; i < n; i++) {
    for (var j = i + 1; j < n; j++) {
      if (points[i].$1 == points[j].$1 && points[i].$2 == points[j].$2) {
        return false;
      }
    }
  }

  int orient((double, double) a, (double, double) b, (double, double) c) {
    final v = (b.$1 - a.$1) * (c.$2 - a.$2) - (b.$2 - a.$2) * (c.$1 - a.$1);
    return v.abs() < 1e-15 ? 0 : (v > 0 ? 1 : -1);
  }

  bool onSegment((double, double) a, (double, double) b, (double, double) c) =>
      _min(a.$1, b.$1) <= c.$1 &&
      c.$1 <= _max(a.$1, b.$1) &&
      _min(a.$2, b.$2) <= c.$2 &&
      c.$2 <= _max(a.$2, b.$2);

  bool intersect(
    (double, double) p1,
    (double, double) p2,
    (double, double) p3,
    (double, double) p4,
  ) {
    final d1 = orient(p3, p4, p1), d2 = orient(p3, p4, p2);
    final d3 = orient(p1, p2, p3), d4 = orient(p1, p2, p4);
    if (d1 != d2 && d3 != d4) return true;
    return (d1 == 0 && onSegment(p3, p4, p1)) ||
        (d2 == 0 && onSegment(p3, p4, p2)) ||
        (d3 == 0 && onSegment(p1, p2, p3)) ||
        (d4 == 0 && onSegment(p1, p2, p4));
  }

  final edges = [for (var i = 0; i < n; i++) (points[i], points[(i + 1) % n])];
  for (var i = 0; i < n; i++) {
    for (var j = i + 1; j < n; j++) {
      if (j == i + 1 || (i == 0 && j == n - 1)) {
        // Neighbours share a corner s; collinear, they must not fold back
        // over each other.
        final (a, s, b) = j == i + 1
            ? (edges[i].$1, edges[i].$2, edges[j].$2)
            : (edges[j].$1, edges[i].$1, edges[i].$2);
        if (orient(a, s, b) == 0 &&
            (onSegment(a, s, b) || onSegment(s, b, a))) {
          return false;
        }
        continue;
      }
      if (intersect(edges[i].$1, edges[i].$2, edges[j].$1, edges[j].$2)) {
        return false;
      }
    }
  }
  return true;
}

// Python's min and max of two floats (the first when equal, so -0.0 and 0.0
// keep their order).
double _min(double a, double b) => b < a ? b : a;
double _max(double a, double b) => b > a ? b : a;
