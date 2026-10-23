// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The controller sync's bodies (protocol/sync.md) on the Android field
/// controller (PE24 slice S7): the Pi's
/// controller/atalaia_controller/sync_format.py in Dart, with the same
/// codes, paths and normalisation (defaults filled in, a node's unknown
/// `info` keys dropped), checked against the same shared vectors
/// (protocol/vectors/sync.json: the bodies, the answers of the endpoints
/// the controller pulls, the stream's messages; test/controller/
/// controller_sync_format_test.dart).
///
/// The sync client (controller_sync.dart) checks every event and body
/// before it sends it and every answer before it uses it; the remote GM
/// (controller_remote_gm.dart) checks every command before it acts on it;
/// the ATAK relay (controller_atak.dart) checks every CoT event before it
/// pushes it. What never travels: positions (an event whose data carries a
/// coordinate is refused), tokens and keys, check-in names.
///
/// Bodies are JSON as `jsonDecode` gives them (mutable maps and lists):
/// each check returns its body with the Pi's defaults filled in, or throws
/// [SyncFormatError] with the code and path of the first problem.
library;

import 'dart:convert';

import 'package:crypto/crypto.dart';

import 'controller_images.dart' show ImageLimits, imageTypes;

const syncVersion = 1;
const maxEvents = 500;
const maxSources = 1024;
const maxNodes = 512;
const maxEventData = 1024;
const maxParams = 8192;
const maxBody = 1024 * 1024;
const maxMarshals = 512;
const maxReplicas = 500;
const maxReadings = 500;
const maxRecord = 4096;
const _teamMax = 23;
const _teamsMax = 8;
const syncStates = ['ready', 'running', 'paused', 'ended'];
const _priorities = ['telemetry', 'normal', 'critical'];
const _u16 = 0xffff;
const _u32 = 0xffffffff;
const _counterMax = 2147483647;
const _timeMax = 17179869184; // 2**34 seconds since 1970
const _int64Max = 9223372036854775807;

RegExp _full(String pattern) => RegExp('^(?:$pattern)\$');

final eventTypeRe = _full(r'[a-z][a-z0-9_]*(\.[a-z0-9][a-z0-9_-]*)+');
const eventTypeMax = 47;
final sourceRe = _full(r'node-(\d{1,5})|field-(\d{1,6})@(\d{1,5})');
final modeIdRe = _full(r'[a-z0-9][a-z0-9._+-]{0,127}');
final _versionRe = _full(r'[A-Za-z0-9][A-Za-z0-9.+_-]{0,31}');
final _crestIdRe = _full(r'[0-9a-f]{64}');
final dataKeyRe = _full(r'[a-z][a-z0-9_]{0,31}');

/// Keys that would carry a position (P4R25): refused anywhere in an
/// event's data.
const positionKeys = {
  'lat',
  'lon',
  'lng',
  'latitude',
  'longitude',
  'alt',
  'altitude',
  'position',
  'positions',
  'gps',
  'coords',
  'coordinates',
  'x',
  'y',
};
const replicaTypesSync = [
  'aeg',
  'gbb',
  'hpa',
  'bolt_action',
  'dmr',
  'sniper',
  'pistol',
  'shotgun',
];
final _replicaClassRe = _full(r'[a-z0-9_]{1,32}');
final _tagNfcRe = _full(
  r'[0-9A-F]{2}(:[0-9A-F]{2}){3}((:[0-9A-F]{2}){3}){0,2}',
);
final _tagQrRe = _full(r'[\x21-\x7e]{1,64}');
const _outcomes = ['pass', 'fail', 'warn', 'unjudged'];
const _publicKeyB64 = 44;

/// chrono.py's forms (protocol/chrono-record.md).
final _chronoIdRe = _full(r'[A-Za-z0-9._:-]{1,64}');
final uuidRe = _full(
  r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
);
final _chronoTimeRe = _full(
  r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z',
);
const _chronoNameMax = 64;

/// What a node's info may carry to the site server; anything else is
/// dropped.
const nodeInfoKinds = {
  'owner': 'team?',
  'phase': 'int?',
  'battery_pct': 'int?',
  'rssi': 'int?',
  'snr': 'num?',
  'epoch': 'int?',
  'platform': 'text?',
  'fw_version': 'text?',
  'core_version': 'text?',
  'tier': 'text?',
  'capabilities': 'texts?',
  'game_time_ms': 'int?',
};

/// A body that does not follow protocol/sync.md: [code] and the [path] of
/// the value.
class SyncFormatError implements Exception {
  SyncFormatError(this.code, [this.path = '']);
  final String code;
  final String path;
  @override
  String toString() => '$code at ${path.isEmpty ? 'the body' : path}';
}

typedef Json = Map<String, Object?>;

Never _fail(String code, String path) => throw SyncFormatError(code, path);

Json _obj(Object? value, String path) {
  if (value is! Map<String, Object?>) {
    if (value is Map && value.keys.every((k) => k is String)) {
      return value.cast<String, Object?>();
    }
    _fail('not_an_object', path);
  }
  return value;
}

String _at(String path, String key) => path.isEmpty ? key : '$path.$key';

void _keys(
  Json value,
  String path,
  List<String> required, [
  List<String> optional = const [],
]) {
  for (final key in required) {
    if (!value.containsKey(key)) _fail('missing', _at(path, key));
  }
  for (final key in value.keys) {
    if (!required.contains(key) && !optional.contains(key)) {
      _fail('unknown_field', _at(path, key));
    }
  }
}

int? _int(Object? value, String path, int lo, int hi, {bool nullable = false}) {
  if (value == null && nullable) return null;
  if (value is! int) _fail('not_an_integer', path);
  if (value < lo || value > hi) _fail('out_of_range', path);
  return value;
}

num? _num(Object? value, String path, num lo, num hi, {bool nullable = false}) {
  if (value == null && nullable) return null;
  if (value is! num || (value is double && !value.isFinite)) {
    _fail('not_a_number', path);
  }
  if (value < lo || value > hi) _fail('out_of_range', path);
  return value;
}

bool _control(int c) => c < 0x20 || (c >= 0x7f && c <= 0x9f);

String? _text(
  Object? value,
  String path,
  int maxLen, {
  bool nullable = false,
  RegExp? pattern,
}) {
  if (value == null && nullable) return null;
  if (value is! String || value.isEmpty) _fail('not_a_text', path);
  final runes = value.runes;
  if (runes.length > maxLen || runes.any(_control)) _fail('bad_text', path);
  if (pattern != null && !pattern.hasMatch(value)) _fail('bad_text', path);
  return value;
}

String? _team(Object? value, String path, {bool nullable = false}) {
  if (value == null && nullable) return null;
  final t = _text(value, path, _teamMax)!;
  if (utf8.encode(t).length > _teamMax) _fail('bad_text', path);
  return t;
}

int _jsonSize(Object? value) => utf8.encode(jsonEncode(value)).length;

Object? _default(Json m, String key, Object? value) =>
    m.putIfAbsent(key, () => value);

Json _envelope(Object? raw, List<String> extra, {bool game = true}) {
  final body = _obj(raw, '');
  _keys(body, '', ['sync_version', 'controller', if (game) 'game', ...extra]);
  if (body['sync_version'] != syncVersion) {
    _fail('unsupported_version', 'sync_version');
  }
  final ctrl = _obj(body['controller'], 'controller');
  _keys(ctrl, 'controller', ['id', 'version']);
  final id = ctrl['id'];
  if (id is! String || !uuidRe.hasMatch(id)) {
    _fail('not_a_uuid', 'controller.id');
  }
  _text(ctrl['version'], 'controller.version', 32, pattern: _versionRe);
  if (!game) return body;
  final ident = _obj(body['game'], 'game');
  _keys(ident, 'game', ['game_id', 'game_seed']);
  _int(ident['game_id'], 'game.game_id', 0, _u16);
  _int(ident['game_seed'], 'game.game_seed', 0, _u32);
  return body;
}

// --- POST /api/v1/sync/games ----------------------------------------------

Json checkGame(Object? raw) {
  final body = _envelope(raw, ['meta']);
  final meta = _obj(body['meta'], 'meta');
  _keys(
    meta,
    'meta',
    ['name', 'mode_id', 'teams', 'state', 'created_at'],
    [
      'team_info',
      'params',
      'squads',
      'duration_ms',
      'node_id',
      'joined',
      'started_at',
      'ended_at',
      'scheduled_game_id',
    ],
  );
  _text(meta['name'], 'meta.name', 64);
  _text(meta['mode_id'], 'meta.mode_id', 128, pattern: modeIdRe);
  final teams = meta['teams'];
  if (teams is! List || teams.isEmpty || teams.length > _teamsMax) {
    _fail('bad_teams', 'meta.teams');
  }
  for (var i = 0; i < teams.length; i++) {
    _team(teams[i], 'meta.teams[$i]');
  }
  if (teams.toSet().length != teams.length) _fail('bad_teams', 'meta.teams');
  final info = _obj(
    _default(meta, 'team_info', <String, Object?>{}),
    'meta.team_info',
  );
  for (final e in info.entries) {
    final path = 'meta.team_info.${e.key}';
    if (!teams.contains(e.key)) _fail('unknown_team', path);
    final entry = _obj(e.value, path);
    _keys(entry, path, const [], ['display_name', 'crest_id']);
    _text(entry['display_name'], '$path.display_name', 32, nullable: true);
    _text(
      entry['crest_id'],
      '$path.crest_id',
      64,
      nullable: true,
      pattern: _crestIdRe,
    );
  }
  final params = _obj(
    _default(meta, 'params', <String, Object?>{}),
    'meta.params',
  );
  if (_jsonSize(params) > maxParams) _fail('too_large', 'meta.params');
  _int(_default(meta, 'squads', 0), 'meta.squads', 0, 16);
  _int(_default(meta, 'duration_ms', 0), 'meta.duration_ms', 0, _u32);
  if (!syncStates.contains(meta['state'])) _fail('bad_state', 'meta.state');
  _int(
    _default(meta, 'node_id', null),
    'meta.node_id',
    0,
    _u16 - 1,
    nullable: true,
  );
  if (_default(meta, 'joined', false) is! bool) {
    _fail('not_a_boolean', 'meta.joined');
  }
  _num(meta['created_at'], 'meta.created_at', 0, _timeMax);
  _num(
    _default(meta, 'started_at', null),
    'meta.started_at',
    0,
    _timeMax,
    nullable: true,
  );
  _num(
    _default(meta, 'ended_at', null),
    'meta.ended_at',
    0,
    _timeMax,
    nullable: true,
  );
  _text(
    _default(meta, 'scheduled_game_id', null),
    'meta.scheduled_game_id',
    36,
    nullable: true,
    pattern: uuidRe,
  );
  return body;
}

// --- POST /api/v1/sync/events ---------------------------------------------

void _data(Object? value, String path, [int depth = 0]) {
  if (value is Map) {
    if (depth >= 2) _fail('too_deep', path);
    for (final e in value.entries) {
      final key = e.key;
      if (key is! String || !dataKeyRe.hasMatch(key)) {
        _fail('bad_key', '$path.$key');
      }
      if (positionKeys.contains(key)) {
        _fail('position_not_allowed', '$path.$key');
      }
      _data(e.value, '$path.$key', depth + 1);
    }
  } else if (value is List) {
    if (depth >= 2 || value.length > 32) _fail('too_deep', path);
    for (var i = 0; i < value.length; i++) {
      _data(value[i], '$path[$i]', depth + 1);
    }
  } else if (value is double) {
    if (!value.isFinite) _fail('not_a_number', path);
  } else if (value != null &&
      value is! String &&
      value is! int &&
      value is! bool) {
    _fail('bad_value', path);
  }
}

/// One event as the controller's log holds it, with its `id` in that log.
Json checkEvent(Object? raw, [String path = 'event']) {
  final ev = _obj(raw, path);
  _keys(
    ev,
    path,
    ['id', 'node', 'seq', 't', 'type', 'prio'],
    ['team', 'squad', 'data', 'epoch', 'pkt_seq'],
  );
  _int(ev['id'], '$path.id', 1, _int64Max);
  _int(ev['node'], '$path.node', 0, _u16);
  _int(ev['seq'], '$path.seq', 0, _u16);
  _int(ev['t'], '$path.t', 0, _u32);
  _text(ev['type'], '$path.type', eventTypeMax, pattern: eventTypeRe);
  if (!_priorities.contains(ev['prio'])) _fail('bad_priority', '$path.prio');
  _team(_default(ev, 'team', null), '$path.team', nullable: true);
  _int(_default(ev, 'squad', null), '$path.squad', 0, 255, nullable: true);
  final data = _obj(_default(ev, 'data', <String, Object?>{}), '$path.data');
  _data(data, '$path.data');
  if (_jsonSize(data) > maxEventData) _fail('too_large', '$path.data');
  _int(_default(ev, 'epoch', null), '$path.epoch', 0, _u16, nullable: true);
  _int(_default(ev, 'pkt_seq', null), '$path.pkt_seq', 0, _u16, nullable: true);
  if (ev['type'] == 'score.delta') {
    // A GM's adjustment (P4R10): the site server adds these amounts.
    _int(data['amount'], '$path.data.amount', -1000000, 1000000);
    final team = data.containsKey('team') ? data['team'] : ev['team'];
    _team(team, '$path.data.team');
    if (ev['team'] != null && ev['team'] != team) {
      _fail('team_mismatch', '$path.team');
    }
  }
  return ev;
}

Json checkEvents(Object? raw) {
  final body = _envelope(raw, ['after_id', 'events']);
  final after = _int(body['after_id'], 'after_id', 0, _int64Max)!;
  final events = body['events'];
  if (events is! List || events.isEmpty || events.length > maxEvents) {
    _fail('bad_batch_size', 'events');
  }
  var last = after;
  for (var i = 0; i < events.length; i++) {
    final ev = checkEvent(events[i], 'events[$i]');
    final id = ev['id']! as int;
    if (id <= last) _fail('ids_not_increasing', 'events[$i].id');
    last = id;
  }
  return body;
}

// --- POST /api/v1/sync/scores ---------------------------------------------

Json checkScores(Object? raw) {
  final body = _envelope(raw, ['counters']);
  final counters = _obj(body['counters'], 'counters');
  if (counters.length > maxSources) _fail('too_large', 'counters');
  for (final e in counters.entries) {
    final path = 'counters.${e.key}';
    if (!sourceRe.hasMatch(e.key)) _fail('bad_source', path);
    final teams = _obj(e.value, path);
    if (teams.length > _teamsMax) _fail('bad_teams', path);
    for (final t in teams.entries) {
      _team(t.key, '$path.${t.key}');
      _int(t.value, '$path.${t.key}', 0, _counterMax);
    }
  }
  return body;
}

// --- POST /api/v1/sync/nodes ----------------------------------------------

Object? _infoValue(String kind, Object? value, String path) {
  if (value == null) return null;
  switch (kind) {
    case 'team?':
      return _team(value, path);
    case 'int?':
      return _int(value, path, -2147483648, 4294967296);
    case 'num?':
      return _num(value, path, -1e9, 1e9);
    case 'text?':
      return _text(value is int ? '$value' : value, path, 32);
  }
  if (value is! List || value.length > 32) _fail('bad_value', path);
  return [
    for (var i = 0; i < value.length; i++) _text(value[i], '$path[$i]', 32),
  ];
}

Json checkNodes(Object? raw) {
  final body = _envelope(raw, ['nodes']);
  _nodeList(body['nodes'], 'nodes');
  return body;
}

void _nodeList(Object? nodes, String where) {
  if (nodes is! List || nodes.length > maxNodes) _fail('bad_batch_size', where);
  final seen = <int>{};
  for (var i = 0; i < nodes.length; i++) {
    final path = '$where[$i]';
    final node = _obj(nodes[i], path);
    nodes[i] = node;
    _keys(node, path, ['node_id', 'name', 'role', 'last_seen'], ['info']);
    final id = _int(node['node_id'], '$path.node_id', 0, _u16)!;
    if (!seen.add(id)) _fail('duplicate_node', '$path.node_id');
    _text(node['name'], '$path.name', 32);
    _text(node['role'], '$path.role', 32);
    _num(node['last_seen'], '$path.last_seen', 0, _timeMax);
    final info = _obj(node['info'] ?? <String, Object?>{}, '$path.info');
    node['info'] = {
      for (final e in info.entries)
        if (nodeInfoKinds.containsKey(e.key))
          e.key: _infoValue(
            nodeInfoKinds[e.key]!,
            e.value,
            '$path.info.${e.key}',
          ),
    };
  }
}

// --- the chrono registry (plan phase 14) ----------------------------------

bool _chronoTextOk(String v) => !v.runes.any(
  (c) => c < 0x20 || (c >= 0x7f && c <= 0x9f) || (c >= 0xd800 && c <= 0xdfff),
);

String _name(Object? value, String path) {
  if (value is! String ||
      value.runes.isEmpty ||
      value.runes.length > _chronoNameMax ||
      !_chronoTextOk(value)) {
    _fail('bad_text', path);
  }
  return value;
}

final _b64Std = _full(r'[A-Za-z0-9+/]{43}=');

/// An Ed25519 public key as the sync sends it: 32 bytes in standard base64
/// with padding.
List<int> publicKeyBytes(Object? value, [String path = 'public_key']) {
  if (value is! String ||
      value.length != _publicKeyB64 ||
      !_b64Std.hasMatch(value)) {
    _fail('bad_public_key', path);
  }
  final raw = base64.decode(value);
  if (raw.length != 32 || base64.encode(raw) != value) {
    _fail('bad_public_key', path);
  }
  return raw;
}

Json checkMarshal(Object? raw, [String path = 'marshal']) {
  final entry = _obj(raw, path);
  _keys(
    entry,
    path,
    ['marshal_id', 'name', 'public_key', 'registered_at'],
    ['player_id', 'replaced_at'],
  );
  _text(entry['marshal_id'], '$path.marshal_id', 64, pattern: _chronoIdRe);
  _name(entry['name'], '$path.name');
  publicKeyBytes(entry['public_key'], '$path.public_key');
  _text(
    _default(entry, 'player_id', null),
    '$path.player_id',
    64,
    nullable: true,
    pattern: _chronoIdRe,
  );
  final registered = _num(
    entry['registered_at'],
    '$path.registered_at',
    0,
    _timeMax,
  )!;
  final replaced = _num(
    _default(entry, 'replaced_at', null),
    '$path.replaced_at',
    0,
    _timeMax,
    nullable: true,
  );
  if (replaced != null && replaced < registered) {
    _fail('bad_period', '$path.replaced_at');
  }
  return entry;
}

Json checkMarshals(Object? raw) {
  final body = _envelope(raw, ['marshals'], game: false);
  final marshals = body['marshals'];
  if (marshals is! List || marshals.isEmpty || marshals.length > maxMarshals) {
    _fail('bad_batch_size', 'marshals');
  }
  final seen = <(Object?, Object?)>{};
  final current = <Object?>{};
  for (var i = 0; i < marshals.length; i++) {
    final path = 'marshals[$i]';
    final entry = checkMarshal(marshals[i], path);
    if (!seen.add((entry['marshal_id'], entry['public_key']))) {
      _fail('duplicate_key', '$path.public_key');
    }
    if (entry['replaced_at'] == null && !current.add(entry['marshal_id'])) {
      _fail('two_current_keys', '$path.replaced_at');
    }
  }
  return body;
}

Json checkReplica(Object? raw, [String path = 'replica']) {
  final entry = _obj(raw, path);
  _keys(
    entry,
    path,
    ['replica_id', 'owner_player_id', 'type', 'class'],
    ['make_model', 'registered_at', 'tag_type', 'tag_uid'],
  );
  _text(entry['replica_id'], '$path.replica_id', 36, pattern: uuidRe);
  _text(
    entry['owner_player_id'],
    '$path.owner_player_id',
    64,
    pattern: _chronoIdRe,
  );
  if (!replicaTypesSync.contains(entry['type'])) {
    _fail('bad_type', '$path.type');
  }
  _text(entry['class'], '$path.class', 32, pattern: _replicaClassRe);
  final mm = _default(entry, 'make_model', null);
  if (mm != null) _name(mm, '$path.make_model');
  final registered = _default(entry, 'registered_at', null);
  if (registered != null) {
    _text(registered, '$path.registered_at', 20, pattern: _chronoTimeRe);
  }
  final tagType = _default(entry, 'tag_type', null);
  final tagUid = _default(entry, 'tag_uid', null);
  if ((tagType == null) != (tagUid == null)) _fail('bad_tag', '$path.tag_uid');
  if (tagType != null) {
    if (tagType != 'nfc' && tagType != 'qr') _fail('bad_tag', '$path.tag_type');
    if (tagUid is! String ||
        !(tagType == 'nfc' ? _tagNfcRe : _tagQrRe).hasMatch(tagUid)) {
      _fail('bad_tag', '$path.tag_uid');
    }
  }
  return entry;
}

Json checkReplicas(Object? raw) {
  final body = _envelope(raw, ['replicas'], game: false);
  final replicas = body['replicas'];
  if (replicas is! List || replicas.isEmpty || replicas.length > maxReplicas) {
    _fail('bad_batch_size', 'replicas');
  }
  final seen = <Object?>{};
  for (var i = 0; i < replicas.length; i++) {
    final entry = checkReplica(replicas[i], 'replicas[$i]');
    if (!seen.add(entry['replica_id'])) {
      _fail('duplicate_replica', 'replicas[$i].replica_id');
    }
  }
  return body;
}

/// One stored reading: `{record, series_id, outcome, received_at,
/// game_seed?}`; the record's content is the site server's to verify.
Json checkReading(Object? raw, [String path = 'reading']) {
  final entry = _obj(raw, path);
  _keys(
    entry,
    path,
    ['record', 'series_id', 'outcome', 'received_at'],
    ['game_seed'],
  );
  final record = entry['record'];
  if (record is! String || record.isEmpty) _fail('not_a_text', '$path.record');
  if (utf8.encode(record).length > maxRecord) {
    _fail('too_large', '$path.record');
  }
  _text(entry['series_id'], '$path.series_id', 36, pattern: uuidRe);
  if (entry['outcome'] != null && !_outcomes.contains(entry['outcome'])) {
    _fail('bad_outcome', '$path.outcome');
  }
  _num(entry['received_at'], '$path.received_at', 0, _timeMax);
  _int(
    _default(entry, 'game_seed', null),
    '$path.game_seed',
    0,
    _u32,
    nullable: true,
  );
  return entry;
}

Json checkChrono(Object? raw) {
  final body = _envelope(raw, ['readings'], game: false);
  final readings = body['readings'];
  if (readings is! List || readings.isEmpty || readings.length > maxReadings) {
    _fail('bad_batch_size', 'readings');
  }
  for (var i = 0; i < readings.length; i++) {
    checkReading(readings[i], 'readings[$i]');
  }
  return body;
}

// --- game day (plan phase 16; ADR-P4-11) ------------------------------------

const maxSchedule = 200;
const maxRoster = 5000;
const maxClaims = 500;
const maxDeclarations = 20;
const _scheduledStates = ['published', 'in_progress', 'completed', 'cancelled'];
const _checkinOutcomes = ['checked_in', 'no_show'];
const _declarationStates = ['pending', 'passed', 'refused', 'withdrawn'];
const claimResults = ['confirmed', 'refused', 'unknown'];
final playerIdRe = _full(r'p-[a-z2-7]{12}');
final sha256HexRe = _full(r'[0-9a-f]{64}');
const _scheduleTeamMax = 32;
const _federations = ['off', 'optional', 'required'];

String? _uuid(Object? value, String path, {bool nullable = false}) =>
    _text(value, path, 36, nullable: nullable, pattern: uuidRe);

bool _bool(Object? value, String path) {
  if (value is! bool) _fail('not_a_boolean', path);
  return value;
}

List<Object?> _list(Object? value, String path, int hi, [int lo = 0]) {
  if (value is! List || value.length < lo || value.length > hi) {
    _fail('bad_batch_size', path);
  }
  return value;
}

Json _answerEnvelope(Object? raw, List<String> required) {
  final body = _obj(raw, '');
  _keys(body, '', ['sync_version', ...required]);
  if (body['sync_version'] != syncVersion) {
    _fail('unsupported_version', 'sync_version');
  }
  return body;
}

Json checkSchedule(Object? raw) {
  final body = _answerEnvelope(raw, ['games']);
  final seen = <Object?>{};
  final games = _list(body['games'], 'games', maxSchedule);
  for (var i = 0; i < games.length; i++) {
    final path = 'games[$i]';
    final g = _obj(games[i], path);
    _keys(
      g,
      path,
      [
        'scheduled_game_id',
        'title',
        'starts_at',
        'ends_at',
        'status',
        'teams',
        'federation',
        'predeclare_replicas',
        'registered',
      ],
      ['mode_id', 'max_players', 'location'],
    );
    _uuid(g['scheduled_game_id'], '$path.scheduled_game_id');
    if (!seen.add(g['scheduled_game_id'])) {
      _fail('duplicate_game', '$path.scheduled_game_id');
    }
    _text(g['title'], '$path.title', 256);
    final starts = _num(g['starts_at'], '$path.starts_at', 0, _timeMax)!;
    final ends = _num(g['ends_at'], '$path.ends_at', 0, _timeMax)!;
    if (ends <= starts) _fail('bad_period', '$path.ends_at');
    if (!_scheduledStates.contains(g['status'])) {
      _fail('bad_state', '$path.status');
    }
    final teams = _list(g['teams'], '$path.teams', 16);
    for (var j = 0; j < teams.length; j++) {
      _text(teams[j], '$path.teams[$j]', _scheduleTeamMax);
    }
    if (teams.toSet().length != teams.length) _fail('bad_teams', '$path.teams');
    if (!_federations.contains(g['federation'])) {
      _fail('bad_value', '$path.federation');
    }
    _bool(g['predeclare_replicas'], '$path.predeclare_replicas');
    _int(g['registered'], '$path.registered', 0, 10000);
    _text(
      _default(g, 'mode_id', null),
      '$path.mode_id',
      128,
      nullable: true,
      pattern: modeIdRe,
    );
    _int(
      _default(g, 'max_players', null),
      '$path.max_players',
      1,
      10000,
      nullable: true,
    );
    _text(_default(g, 'location', null), '$path.location', 512, nullable: true);
  }
  return body;
}

Json checkDeclaration(Object? raw, String path) {
  final d = _obj(raw, path);
  _keys(
    d,
    path,
    ['declaration_id', 'type', 'class'],
    ['replica_id', 'make_model'],
  );
  _uuid(d['declaration_id'], '$path.declaration_id');
  _uuid(_default(d, 'replica_id', null), '$path.replica_id', nullable: true);
  if (!replicaTypesSync.contains(d['type'])) _fail('bad_type', '$path.type');
  _text(d['class'], '$path.class', 32, pattern: _replicaClassRe);
  final mm = _default(d, 'make_model', null);
  if (mm != null) _name(mm, '$path.make_model');
  return d;
}

Json checkRoster(Object? raw) {
  final body = _answerEnvelope(raw, [
    'scheduled_game_id',
    'status',
    'federation',
    'registrations',
  ]);
  _uuid(body['scheduled_game_id'], 'scheduled_game_id');
  if (!_scheduledStates.contains(body['status'])) _fail('bad_state', 'status');
  if (!_federations.contains(body['federation'])) {
    _fail('bad_value', 'federation');
  }
  final regs = <Object?>{}, players = <Object?>{}, decls = <Object?>{};
  final list = _list(body['registrations'], 'registrations', maxRoster);
  for (var i = 0; i < list.length; i++) {
    final path = 'registrations[$i]';
    final r = _obj(list[i], path);
    list[i] = r;
    _keys(
      r,
      path,
      ['registration_id', 'player_id', 'display_name', 'replicas'],
      ['team_preference', 'federation_number', 'ticket_sha256'],
    );
    _uuid(r['registration_id'], '$path.registration_id');
    _text(r['player_id'], '$path.player_id', 14, pattern: playerIdRe);
    if (regs.contains(r['registration_id']) ||
        players.contains(r['player_id'])) {
      _fail('duplicate_registration', path);
    }
    regs.add(r['registration_id']);
    players.add(r['player_id']);
    _text(r['display_name'], '$path.display_name', 32);
    _text(
      _default(r, 'team_preference', null),
      '$path.team_preference',
      _scheduleTeamMax,
      nullable: true,
    );
    final fed = _text(
      _default(r, 'federation_number', null),
      '$path.federation_number',
      32,
      nullable: true,
    );
    if (fed != null && body['federation'] == 'off') {
      _fail('not_asked', '$path.federation_number');
    }
    _text(
      _default(r, 'ticket_sha256', null),
      '$path.ticket_sha256',
      64,
      nullable: true,
      pattern: sha256HexRe,
    );
    final reps = _list(r['replicas'], '$path.replicas', maxDeclarations);
    for (var j = 0; j < reps.length; j++) {
      final d = checkDeclaration(reps[j], '$path.replicas[$j]');
      reps[j] = d;
      if (!decls.add(d['declaration_id'])) {
        _fail('duplicate_declaration', '$path.replicas[$j].declaration_id');
      }
    }
  }
  return body;
}

Json checkClaimsList(Object? raw) {
  final body = _answerEnvelope(raw, ['claims']);
  final seen = <Object?>{};
  final claims = _list(body['claims'], 'claims', maxClaims);
  for (var i = 0; i < claims.length; i++) {
    final path = 'claims[$i]';
    final c = _obj(claims[i], path);
    _keys(c, path, ['claim_id', 'player_id', 'secret_sha256']);
    _uuid(c['claim_id'], '$path.claim_id');
    if (!seen.add(c['claim_id'])) _fail('duplicate_claim', '$path.claim_id');
    _text(c['player_id'], '$path.player_id', 14, pattern: playerIdRe);
    _text(c['secret_sha256'], '$path.secret_sha256', 64, pattern: sha256HexRe);
  }
  return body;
}

Json checkCheckins(Object? raw) {
  final body = _envelope(raw, [
    'scheduled_game_id',
    'registrations',
    'walkins',
  ]);
  _uuid(body['scheduled_game_id'], 'scheduled_game_id');
  _int(body['walkins'], 'walkins', 0, 100000);
  final seen = <Object?>{};
  final regs = _list(body['registrations'], 'registrations', maxRoster);
  for (var i = 0; i < regs.length; i++) {
    final path = 'registrations[$i]';
    final r = _obj(regs[i], path);
    _keys(
      r,
      path,
      ['registration_id', 'player_id', 'outcome', 'declarations'],
      ['ticket_sha256'],
    );
    _uuid(r['registration_id'], '$path.registration_id');
    if (!seen.add(r['registration_id'])) {
      _fail('duplicate_registration', '$path.registration_id');
    }
    _text(r['player_id'], '$path.player_id', 14, pattern: playerIdRe);
    if (!_checkinOutcomes.contains(r['outcome'])) {
      _fail('bad_outcome', '$path.outcome');
    }
    _text(
      _default(r, 'ticket_sha256', null),
      '$path.ticket_sha256',
      64,
      nullable: true,
      pattern: sha256HexRe,
    );
    final decls = <Object?>{};
    final list = _list(
      r['declarations'],
      '$path.declarations',
      maxDeclarations,
    );
    for (var j = 0; j < list.length; j++) {
      final dpath = '$path.declarations[$j]';
      final d = _obj(list[j], dpath);
      _keys(d, dpath, ['declaration_id', 'state'], ['reading_id']);
      _uuid(d['declaration_id'], '$dpath.declaration_id');
      if (!decls.add(d['declaration_id'])) {
        _fail('duplicate_declaration', '$dpath.declaration_id');
      }
      if (!_declarationStates.contains(d['state'])) {
        _fail('bad_state', '$dpath.state');
      }
      _uuid(
        _default(d, 'reading_id', null),
        '$dpath.reading_id',
        nullable: true,
      );
    }
  }
  return body;
}

Json checkClaims(Object? raw) {
  final body = _envelope(raw, ['results'], game: false);
  final seen = <Object?>{};
  final results = _list(body['results'], 'results', maxClaims, 1);
  for (var i = 0; i < results.length; i++) {
    final path = 'results[$i]';
    final r = _obj(results[i], path);
    _keys(r, path, ['claim_id', 'result']);
    _uuid(r['claim_id'], '$path.claim_id');
    if (!seen.add(r['claim_id'])) _fail('duplicate_claim', '$path.claim_id');
    if (!claimResults.contains(r['result'])) _fail('bad_value', '$path.result');
  }
  return body;
}

// --- branding and saved teams (plan phase 18; P4R19) ----------------------

const maxSyncTeams = 200;
const _fieldNameMax = 48;
const _teamDisplayMax = 32;
final _accentRe = _full(r'#[0-9a-f]{6}');
final _clubSlugRe = _full(r'[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?');

/// Python's `str.strip()`'s whitespace, for the "no space at either end"
/// rules.
String _pyStrip(String s) {
  bool ws(int c) =>
      c == 0x20 ||
      (c >= 0x09 && c <= 0x0d) ||
      (c >= 0x1c && c <= 0x1f) ||
      c == 0x85 ||
      c == 0xa0 ||
      c == 0x1680 ||
      (c >= 0x2000 && c <= 0x200a) ||
      c == 0x2028 ||
      c == 0x2029 ||
      c == 0x202f ||
      c == 0x205f ||
      c == 0x3000;
  final r = s.runes.toList();
  var a = 0, b = r.length;
  while (a < b && ws(r[a])) {
    a++;
  }
  while (b > a && ws(r[b - 1])) {
    b--;
  }
  return String.fromCharCodes(r.sublist(a, b));
}

Json? checkImageRef(Object? value, String path, String kind) {
  if (value == null) return null;
  final ref = _obj(value, path);
  _keys(ref, path, ['sha256', 'content_type', 'width', 'height', 'bytes']);
  _text(ref['sha256'], '$path.sha256', 64, pattern: sha256HexRe);
  if (!imageTypes.contains(ref['content_type'])) {
    _fail('bad_type', '$path.content_type');
  }
  final lim = ImageLimits.kinds[kind]!;
  _int(ref['width'], '$path.width', lim.minSide, lim.maxSide);
  _int(ref['height'], '$path.height', lim.minSide, lim.maxSide);
  _int(ref['bytes'], '$path.bytes', 1, lim.maxBytes);
  return ref;
}

Json checkField(Object? raw) {
  final body = _answerEnvelope(raw, ['field', 'teams']);
  final f = _obj(body['field'], 'field');
  body['field'] = f;
  _keys(f, 'field', const [], ['field_name', 'accent', 'logo', 'wallpaper']);
  final name = _text(
    _default(f, 'field_name', null),
    'field.field_name',
    _fieldNameMax,
    nullable: true,
  );
  if (name != null && name != _pyStrip(name)) {
    _fail('bad_text', 'field.field_name');
  }
  _text(
    _default(f, 'accent', null),
    'field.accent',
    7,
    nullable: true,
    pattern: _accentRe,
  );
  for (final slot in ['logo', 'wallpaper']) {
    checkImageRef(_default(f, slot, null), 'field.$slot', slot);
  }
  final ids = <Object?>{}, names = <Object?>{};
  final teams = _list(body['teams'], 'teams', maxSyncTeams);
  for (var i = 0; i < teams.length; i++) {
    final path = 'teams[$i]';
    final t = _obj(teams[i], path);
    teams[i] = t;
    _keys(t, path, ['team_id', 'name'], ['colour', 'crest', 'club']);
    _uuid(t['team_id'], '$path.team_id');
    if (!ids.add(t['team_id'])) _fail('duplicate_team', '$path.team_id');
    final n = _text(t['name'], '$path.name', _teamDisplayMax)!;
    if (n != _pyStrip(n)) _fail('bad_text', '$path.name');
    if (!names.add(n)) _fail('duplicate_team', '$path.name');
    final colour = _team(
      _default(t, 'colour', null),
      '$path.colour',
      nullable: true,
    );
    if (colour != null && colour.contains(' ')) {
      _fail('bad_text', '$path.colour');
    }
    checkImageRef(_default(t, 'crest', null), '$path.crest', 'crest');
    final club = _default(t, 'club', null);
    if (club != null) {
      final c = _obj(club, '$path.club');
      _keys(c, '$path.club', ['slug', 'name']);
      _text(c['slug'], '$path.club.slug', 128, pattern: _clubSlugRe);
      _text(c['name'], '$path.club.name', 128);
    }
  }
  return body;
}

// --- the remote GM on the stream (plan phase 19; P4R12) -------------------

const remoteCommands = ['start', 'pause', 'resume', 'end', 'message', 'mode'];
const _messageMax = 100;
const _reasonMax = 64;
const _usernameMax = 64;
const _detailMax = 200;
const maxLiveEvents = 50;
const _maxModeCommands = 32;
final commandNameRe = _full(r'[a-z][a-z0-9_]{0,23}');
const resultCodes = [
  'done',
  'remote_gm_off',
  'invalid',
  'stale',
  'not_live',
  'not_found',
  'conflict',
  'unavailable',
  'failed',
];
const _totalMin = -1099511627776; // -(2**40)
const _totalMax = 1099511627776;

/// A command sent longer ago than this (or this far ahead) is refused.
const commandStaleS = 60.0;

Json checkHello(Object? raw) {
  final body = _obj(raw, '');
  _envelope(
    {
      for (final e in body.entries)
        if (e.key != 'atak') e.key: e.value,
    },
    ['remote_gm'],
    game: false,
  );
  _bool(body['remote_gm'], 'remote_gm');
  _bool(_default(body, 'atak', false), 'atak');
  return body;
}

Json checkLive(Object? raw) {
  final body = _envelope(raw, ['live'], game: false);
  if (body['live'] == null) return body;
  final live = _obj(body['live'], 'live');
  _keys(
    live,
    'live',
    [
      'game',
      'name',
      'mode_id',
      'teams',
      'state',
      'in_charge',
      'totals',
      'nodes',
      'events',
    ],
    ['game_time_ms', 'duration_ms', 'mode_commands'],
  );
  final ident = _obj(live['game'], 'live.game');
  _keys(ident, 'live.game', ['game_id', 'game_seed']);
  _int(ident['game_id'], 'live.game.game_id', 0, _u16);
  _int(ident['game_seed'], 'live.game.game_seed', 0, _u32);
  _text(live['name'], 'live.name', 64);
  _text(live['mode_id'], 'live.mode_id', 128, pattern: modeIdRe);
  final teams = live['teams'];
  if (teams is! List || teams.isEmpty || teams.length > _teamsMax) {
    _fail('bad_teams', 'live.teams');
  }
  for (var i = 0; i < teams.length; i++) {
    _team(teams[i], 'live.teams[$i]');
  }
  if (!syncStates.contains(live['state'])) _fail('bad_state', 'live.state');
  _bool(live['in_charge'], 'live.in_charge');
  final totals = _obj(live['totals'], 'live.totals');
  for (final e in totals.entries) {
    if (!teams.contains(e.key)) _fail('unknown_team', 'live.totals.${e.key}');
    _int(e.value, 'live.totals.${e.key}', _totalMin, _totalMax);
  }
  _int(
    _default(live, 'game_time_ms', null),
    'live.game_time_ms',
    0,
    _u32,
    nullable: true,
  );
  _int(_default(live, 'duration_ms', 0), 'live.duration_ms', 0, _u32);
  _nodeList(live['nodes'], 'live.nodes');
  final events = _list(live['events'], 'live.events', maxLiveEvents);
  for (var i = 0; i < events.length; i++) {
    checkEvent(events[i], 'live.events[$i]');
  }
  final cmds = _list(
    _default(live, 'mode_commands', <Object?>[]),
    'live.mode_commands',
    _maxModeCommands,
  );
  for (var i = 0; i < cmds.length; i++) {
    final path = 'live.mode_commands[$i]';
    final cmd = _obj(cmds[i], path);
    _keys(cmd, path, ['name', 'roles']);
    _text(cmd['name'], '$path.name', 24, pattern: commandNameRe);
    final roles = _list(cmd['roles'], '$path.roles', 16, 1);
    for (var j = 0; j < roles.length; j++) {
      _text(roles[j], '$path.roles[$j]', 32);
    }
  }
  return body;
}

Json checkCommandParams(
  Object? command,
  Object? raw, [
  String path = 'params',
]) {
  if (!remoteCommands.contains(command)) _fail('not_allowed', 'command');
  final params = _obj(raw, path);
  switch (command) {
    case 'start' || 'resume':
      _keys(params, path, const []);
    case 'pause' || 'end':
      _keys(params, path, const [], ['reason']);
      final reason = _default(params, 'reason', '');
      if (reason != '') _text(reason, '$path.reason', _reasonMax);
    case 'message':
      _keys(params, path, ['text']);
      final text = _text(params['text'], '$path.text', _messageMax)!;
      if (_pyStrip(text).isEmpty) _fail('bad_text', '$path.text');
    default: // mode
      _keys(params, path, ['name'], ['node']);
      _text(params['name'], '$path.name', 24, pattern: commandNameRe);
      _int(_default(params, 'node', _u16), '$path.node', 1, _u16);
  }
  return params;
}

Json checkCommand(Object? raw) {
  final body = _obj(raw, '');
  _keys(body, '', ['id', 'game', 'command', 'params', 'user', 'sent_at']);
  _uuid(body['id'], 'id');
  final ident = _obj(body['game'], 'game');
  _keys(ident, 'game', ['game_id', 'game_seed']);
  _int(ident['game_id'], 'game.game_id', 0, _u16);
  _int(ident['game_seed'], 'game.game_seed', 0, _u32);
  if (!remoteCommands.contains(body['command'])) {
    _fail('not_allowed', 'command');
  }
  body['params'] = checkCommandParams(body['command'], body['params']);
  final user = _obj(body['user'], 'user');
  _keys(user, 'user', ['id', 'username']);
  _uuid(user['id'], 'user.id');
  _text(user['username'], 'user.username', _usernameMax);
  _num(body['sent_at'], 'sent_at', 0, _timeMax);
  return body;
}

Json checkResult(Object? raw) {
  final body = _obj(raw, '');
  _envelope(
    {
      for (final e in body.entries)
        if (e.key != 'detail') e.key: e.value,
    },
    ['id', 'code'],
    game: false,
  );
  _default(body, 'detail', null);
  _uuid(body['id'], 'id');
  if (!resultCodes.contains(body['code'])) _fail('bad_value', 'code');
  _text(body['detail'], 'detail', _detailMax, nullable: true);
  return body;
}

// --- the remote ATAK relay (Phase 4 follow-up FU5) ------------------------

const maxCotEvents = 100;
const maxCotBytes = 2048;
const cotDecl = "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n";
final _cotUidRe = _full(r'atalaia\.[A-Za-z0-9._:-]{1,120}');
final _cotHowRe = _full(r'[a-z](-[a-z]){0,4}');
final _cotTimeRe = _full(
  r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{1,6})?Z',
);
final _cotNumberRe = _full(r'-?\d{1,9}(\.\d{1,9})?');
const cotMapTypes = ['b-m-p-s-m'];
const cotMapHows = ['h-e', 'h-p'];
const cotTypes = ['b-m-p-s-m', 'a-f-G-U-C'];
const _cotDetails = [
  'contact',
  'remarks',
  'color',
  'usericon',
  '__group',
  'status',
];
const _cotPlayerDetails = ['contact', '__group', 'remarks'];
const _cotEventAttrs = [
  'version',
  'uid',
  'type',
  'how',
  'time',
  'start',
  'stale',
];
const cotCallsignMax = 48;
const cotRemarksMax = 160;
const cotRemarksPrefix = 'Atalaia: ';
final _cotArgbRe = _full(r'-?[0-9]{1,10}');
final _cotBatteryRe = _full(r'100|[1-9]?[0-9]');
const cotIconset = 'COT_MAPPING_SPOTMAP/b-m-p-s-m/';
const cotGroupRole = 'Team Member';
const cotTeams = [
  'White',
  'Yellow',
  'Orange',
  'Magenta',
  'Red',
  'Maroon',
  'Purple',
  'Dark Blue',
  'Blue',
  'Cyan',
  'Teal',
  'Green',
  'Dark Green',
  'Brown',
];
const _cotForbidden = ['<!', '<?', '&#', ']]>'];

/// A parsed XML element of the narrow form CoT events take (no DOCTYPE,
/// entity, comment, CDATA or processing instruction get this far).
class XmlElement {
  XmlElement(this.tag, this.attrib);
  final String tag;
  final Map<String, String> attrib;
  final children = <XmlElement>[];
  String? text;
  String? tail;
}

class _XmlError implements Exception {}

/// A small XML parser for one element tree, as Python's ElementTree reads
/// the forms that reach it: elements, attributes in either quote, the five
/// predefined entities, text and tails. Anything else is an error.
XmlElement parseXmlElement(String s) {
  var i = 0;
  bool nameStart(int c) =>
      c == 0x3a ||
      c == 0x5f ||
      (c >= 0x41 && c <= 0x5a) ||
      (c >= 0x61 && c <= 0x7a) ||
      c >= 0xc0;
  bool nameChar(int c) =>
      nameStart(c) || c == 0x2d || c == 0x2e || (c >= 0x30 && c <= 0x39);
  bool space(int c) => c == 0x20 || c == 0x09 || c == 0x0a || c == 0x0d;
  void skip() {
    while (i < s.length && space(s.codeUnitAt(i))) {
      i++;
    }
  }

  String name() {
    final start = i;
    if (i >= s.length || !nameStart(s.codeUnitAt(i))) throw _XmlError();
    while (i < s.length && nameChar(s.codeUnitAt(i))) {
      i++;
    }
    return s.substring(start, i);
  }

  String chars(String raw, {bool attr = false}) {
    final out = StringBuffer();
    for (var k = 0; k < raw.length; k++) {
      final c = raw[k];
      if (c == '<') throw _XmlError();
      if (c == '&') {
        final end = raw.indexOf(';', k);
        if (end < 0) throw _XmlError();
        final ent = raw.substring(k + 1, end);
        out.write(switch (ent) {
          'amp' => '&',
          'lt' => '<',
          'gt' => '>',
          'quot' => '"',
          'apos' => "'",
          _ => throw _XmlError(),
        });
        k = end;
      } else if (attr && (c == '\t' || c == '\n' || c == '\r')) {
        out.write(' ');
      } else if (c == '\r') {
        // XML end-of-line handling: CR and CRLF become LF.
        if (k + 1 < raw.length && raw[k + 1] == '\n') continue;
        out.write('\n');
      } else {
        out.write(c);
      }
    }
    return out.toString();
  }

  String textUntilTag() {
    final start = i;
    final next = s.indexOf('<', i);
    i = next < 0 ? s.length : next;
    return chars(s.substring(start, i));
  }

  XmlElement element() {
    if (i >= s.length || s[i] != '<') throw _XmlError();
    i++;
    final tag = name();
    final attrib = <String, String>{};
    while (true) {
      final before = i;
      skip();
      if (i >= s.length) throw _XmlError();
      final c = s[i];
      if (c == '/' || c == '>') break;
      if (i == before) throw _XmlError(); // attributes need a space between
      final key = name();
      skip();
      if (i >= s.length || s[i] != '=') throw _XmlError();
      i++;
      skip();
      if (i >= s.length || (s[i] != '"' && s[i] != "'")) throw _XmlError();
      final q = s[i++];
      final end = s.indexOf(q, i);
      if (end < 0) throw _XmlError();
      if (attrib.containsKey(key)) throw _XmlError();
      attrib[key] = chars(s.substring(i, end), attr: true);
      i = end + 1;
    }
    final el = XmlElement(tag, attrib);
    if (s[i] == '/') {
      if (i + 1 >= s.length || s[i + 1] != '>') throw _XmlError();
      i += 2;
      return el;
    }
    i++; // '>'
    final text = textUntilTag();
    el.text = text.isEmpty ? null : text;
    while (true) {
      if (i >= s.length) throw _XmlError();
      if (s.startsWith('</', i)) {
        i += 2;
        if (name() != tag) throw _XmlError();
        skip();
        if (i >= s.length || s[i] != '>') throw _XmlError();
        i++;
        return el;
      }
      final child = element();
      final tail = textUntilTag();
      child.tail = tail.isEmpty ? null : tail;
      el.children.add(child);
    }
  }

  skip();
  final root = element();
  skip();
  if (i != s.length) throw _XmlError();
  return root;
}

bool _cotText(String? value, int limit) =>
    value != null &&
    value.runes.length <= limit &&
    value ==
        _pyStrip(
          value,
        ).split(RegExp(r'\s+')).where((w) => w.isNotEmpty).join(' ');

bool _argb(String? value) {
  if (value == null || !_cotArgbRe.hasMatch(value)) return false;
  final v = int.parse(value);
  return v >= -2147483648 && v < 2147483648;
}

bool _cotDetail(XmlElement child, String kind) {
  final a = child.attrib, tag = child.tag;
  if (tag != 'remarks' && (child.text ?? '').isNotEmpty) return false;
  if (!cotMapTypes.contains(kind) && !_cotPlayerDetails.contains(tag)) {
    return false;
  }
  bool only(Set<String> keys) =>
      a.length == keys.length && a.keys.every(keys.contains);
  switch (tag) {
    case 'contact':
      return only({'callsign'}) &&
          _cotText(a['callsign'], cotCallsignMax) &&
          a['callsign'] != '';
    case 'remarks':
      final text = child.text ?? '';
      return a.isEmpty &&
          _cotText(text, cotRemarksMax) &&
          text.startsWith(cotRemarksPrefix);
    case 'color':
      return only({'argb'}) && _argb(a['argb']);
    case 'usericon':
      final p = a['iconsetpath'] ?? '';
      return only({'iconsetpath'}) &&
          p.startsWith(cotIconset) &&
          _argb(p.substring(cotIconset.length));
    case '__group':
      return only({'name', 'role'}) &&
          cotTeams.contains(a['name']) &&
          a['role'] == cotGroupRole;
    case 'status':
      return only({'battery'}) && _cotBatteryRe.hasMatch(a['battery']!);
  }
  return false;
}

double _cotTime(String? value, String path) {
  final m = value == null ? null : _cotTimeRe.firstMatch(value);
  if (m == null) _fail('bad_time', path);
  final g = [for (var k = 1; k <= 6; k++) int.parse(m.group(k)!)];
  final (y, mo, d, h, mi, sec) = (g[0], g[1], g[2], g[3], g[4], g[5]);
  if (!(y >= 1970 &&
      y <= 2500 &&
      mo >= 1 &&
      mo <= 12 &&
      d >= 1 &&
      d <= 31 &&
      h <= 23 &&
      mi <= 59 &&
      sec <= 60)) {
    _fail('bad_time', path);
  }
  final base = DateTime.utc(y, mo, d, h, mi, sec).millisecondsSinceEpoch / 1000;
  final frac = m.group(7);
  return base + (frac == null ? 0 : double.parse(frac));
}

/// One CoT event as the controller's emitter makes it, checked:
/// `{uid, type, how, start, stale, map}` (`map`: what any enrolled ATAK
/// client may see).
Json cotEvent(Object? text, [String path = 'event']) {
  if (text is! String || !text.startsWith(cotDecl)) _fail('not_cot', path);
  if (utf8.encode(text).length > maxCotBytes) _fail('too_large', path);
  final body = text.substring(cotDecl.length);
  if (_cotForbidden.any(body.contains)) _fail('not_cot', path);
  final XmlElement root;
  try {
    root = parseXmlElement(body);
  } on _XmlError {
    _fail('not_cot', path);
  }
  if (root.tag != 'event' || root.attrib['version'] != '2.0') {
    _fail('not_cot', path);
  }
  if (root.attrib.keys.any((k) => !_cotEventAttrs.contains(k))) {
    _fail('unknown_field', path);
  }
  final uid = root.attrib['uid'], kind = root.attrib['type'];
  final how = root.attrib['how'];
  if (uid == null || !_cotUidRe.hasMatch(uid)) _fail('bad_uid', '$path.uid');
  if (!cotTypes.contains(kind)) _fail('bad_type', '$path.type');
  if (how == null || !_cotHowRe.hasMatch(how)) _fail('bad_how', '$path.how');
  _cotTime(root.attrib['time'], '$path.time');
  final start = _cotTime(root.attrib['start'], '$path.start');
  final stale = _cotTime(root.attrib['stale'], '$path.stale');
  final children = root.children;
  if (children.length != 2 ||
      children[0].tag != 'point' ||
      children[1].tag != 'detail' ||
      _pyStrip(root.text ?? '').isNotEmpty) {
    _fail('not_cot', path);
  }
  final point = children[0];
  const pointKeys = ['lat', 'lon', 'hae', 'ce', 'le'];
  if (point.attrib.length != 5 ||
      !point.attrib.keys.every(pointKeys.contains) ||
      point.children.isNotEmpty) {
    _fail('bad_point', '$path.point');
  }
  for (final key in pointKeys) {
    if (!_cotNumberRe.hasMatch(point.attrib[key] ?? '')) {
      _fail('bad_point', '$path.point.$key');
    }
  }
  final lat = double.parse(point.attrib['lat']!);
  final lon = double.parse(point.attrib['lon']!);
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    _fail('bad_point', '$path.point');
  }
  final detail = children[1];
  if (_pyStrip(detail.text ?? '').isNotEmpty || detail.attrib.isNotEmpty) {
    _fail('bad_detail', '$path.detail');
  }
  final seen = <String>{};
  for (final child in detail.children) {
    if (!_cotDetails.contains(child.tag) ||
        child.children.isNotEmpty ||
        _pyStrip(child.tail ?? '').isNotEmpty ||
        !seen.add(child.tag)) {
      _fail('bad_detail', '$path.detail');
    }
    if (!_cotDetail(child, kind!)) {
      _fail('bad_detail', '$path.detail.${child.tag}');
    }
  }
  return {
    'uid': uid,
    'type': kind,
    'how': how,
    'start': start,
    'stale': stale,
    'map': cotMapTypes.contains(kind) && cotMapHows.contains(how),
  };
}

Json checkCot(Object? raw) {
  final body = _envelope(raw, ['events'], game: false);
  final events = _list(body['events'], 'events', maxCotEvents, 1);
  for (var i = 0; i < events.length; i++) {
    cotEvent(events[i], 'events[$i]');
  }
  return body;
}

/// The stream's own messages (`type` taken out).
const streamChecks = <String, Json Function(Object?)>{
  'hello': checkHello,
  'live': checkLive,
  'command.result': checkResult,
  'command': checkCommand,
  'cot': checkCot,
};

// --- the scenario library and presets (plan phase 20) ---------------------

const _maxLibrary = 200;
const manifestMax = 256 * 1024;
const _presetNameMax = 64;
final _scenarioIdRe = _full(r'[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+');
const _scenarioIdMax = 40;
const _revisionMax = 2147483647;

Json _scenarioRef(Json s, String path) {
  String at(String key) => path.isEmpty ? key : '$path.$key';
  _text(
    s['scenario_id'],
    at('scenario_id'),
    _scenarioIdMax,
    pattern: _scenarioIdRe,
  );
  _int(s['revision'], at('revision'), 1, _revisionMax);
  _text(s['sha256'], at('sha256'), 64, pattern: sha256HexRe);
  return s;
}

Json checkPresets(Object? raw) {
  final body = _answerEnvelope(raw, ['scenarios', 'presets']);
  final ids = <Object?>{};
  final scenarios = _list(body['scenarios'], 'scenarios', _maxLibrary);
  for (var i = 0; i < scenarios.length; i++) {
    final path = 'scenarios[$i]';
    final s = _obj(scenarios[i], path);
    scenarios[i] = s;
    _keys(s, path, ['scenario_id', 'revision', 'version', 'name', 'sha256']);
    _scenarioRef(s, path);
    if (!ids.add(s['scenario_id'])) {
      _fail('duplicate_scenario', '$path.scenario_id');
    }
    _text(s['version'], '$path.version', 32);
    _text(s['name'], '$path.name', 128);
  }
  final names = <Object?>{}, presetIds = <Object?>{};
  final presets = _list(body['presets'], 'presets', _maxLibrary);
  for (var i = 0; i < presets.length; i++) {
    final path = 'presets[$i]';
    final p = _obj(presets[i], path);
    presets[i] = p;
    _keys(p, path, ['preset_id', 'name', 'mode_id', 'params']);
    _uuid(p['preset_id'], '$path.preset_id');
    if (!presetIds.add(p['preset_id'])) {
      _fail('duplicate_preset', '$path.preset_id');
    }
    final n = _text(p['name'], '$path.name', _presetNameMax)!;
    if (n != _pyStrip(n)) _fail('bad_text', '$path.name');
    if (!names.add(n)) _fail('duplicate_preset', '$path.name');
    _text(p['mode_id'], '$path.mode_id', 128, pattern: modeIdRe);
    _obj(p['params'], '$path.params');
    if (_jsonSize(p['params']) > maxParams) _fail('too_large', '$path.params');
  }
  return body;
}

Json checkScenario(Object? raw) {
  final body = _answerEnvelope(raw, [
    'scenario_id',
    'revision',
    'sha256',
    'manifest',
  ]);
  _scenarioRef(body, '');
  final manifest = body['manifest'];
  if (manifest is! String || _pyStrip(manifest).isEmpty) {
    _fail('not_a_text', 'manifest');
  }
  final bytes = utf8.encode(manifest);
  if (bytes.length > manifestMax) _fail('too_large', 'manifest');
  if (sha256.convert(bytes).toString() != body['sha256']) {
    _fail('sha256_mismatch', 'sha256');
  }
  return body;
}

/// The bodies the controller pushes, by kind.
const syncChecks = <String, Json Function(Object?)>{
  'games': checkGame,
  'events': checkEvents,
  'scores': checkScores,
  'nodes': checkNodes,
  'marshals': checkMarshals,
  'replicas': checkReplicas,
  'chrono': checkChrono,
  'checkins': checkCheckins,
  'claims': checkClaims,
};

/// The bodies about one game; the rest are the field's.
const gameKinds = ['games', 'events', 'scores', 'nodes', 'checkins'];

/// The answers of the GET endpoints the controller pulls.
const syncAnswers = <String, Json Function(Object?)>{
  'schedule': checkSchedule,
  'roster': checkRoster,
  'claims': checkClaimsList,
  'field': checkField,
  'presets': checkPresets,
  'scenario': checkScenario,
};

// --- the merge (P4R10) ------------------------------------------------------

/// Each (source, team) counter keeps the largest value it was ever
/// reported with.
Map<String, Map<String, int>> mergeCounters(
  Map<String, Map<String, int>> stored,
  Map<String, Map<String, int>> incoming,
) {
  final out = {for (final e in stored.entries) e.key: Map.of(e.value)};
  incoming.forEach((source, teams) {
    final row = out.putIfAbsent(source, () => {});
    teams.forEach((team, value) {
      final have = row[team] ?? 0;
      row[team] = value > have ? value : have;
    });
  });
  return out;
}

/// A game's totals: the counters' sum per team plus every GM adjustment.
Map<String, int> syncTotals(
  List<String> teams,
  Map<String, Map<String, int>> counters,
  List<(String, int)> deltas,
) {
  final out = {for (final t in teams) t: 0};
  for (final row in counters.values) {
    row.forEach((team, value) => out[team] = (out[team] ?? 0) + value);
  }
  for (final (team, amount) in deltas) {
    out[team] = (out[team] ?? 0) + amount;
  }
  return out;
}
