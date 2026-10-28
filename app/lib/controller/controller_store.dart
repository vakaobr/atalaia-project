// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// What the Android field controller keeps about its games (PE24): games,
/// their event log, scores, the nodes heard and a few settings, as the Pi
/// controller's SQLite store keeps them (controller/atalaia_controller/
/// store.py), with the same record shapes so the API answers alike.
///
/// [MemoryControllerStore] keeps everything in memory (tests, and a
/// controller that need not outlive its process). [FileControllerStore]
/// (slice S3, PLAN.md "PE24 slices") keeps the same in files in a directory
/// of the app's private storage, so a restarted controller finds its live
/// game again; the game key is written there only when the controller's
/// persist_game_key is on (ADR-P2-4, decision OT-7: on by default), as the
/// Pi keeps it in its SQLite file.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

/// Game states a game can be in and still be the live game.
const liveStates = ['ready', 'running', 'paused'];

abstract interface class ControllerStore {
  /// Stores a new game, with its key when it is to be kept (null: the key
  /// stays in the controller's memory only).
  void createGame(Map<String, Object?> game, {Uint8List? key});
  Map<String, Object?>? game(int id);

  /// The game's key as stored, or null (never kept, or the game ended).
  Uint8List? gameKey(int id);

  /// Forgets the game's key (when the game ends: the key does not outlive
  /// it).
  void forgetGameKey(int id);

  /// Every game, oldest first.
  List<Map<String, Object?>> games();
  Map<String, Object?>? liveGame();
  Set<int> gameIds();
  void updateGame(int id, Map<String, Object?> fields);

  /// Deletes a game with everything stored about it: its record and key,
  /// events, scores, nodes and the settings kept per game (the retention
  /// purge, decision RET-1).
  void deleteGame(int id);

  /// Stores one event; false when the log already had it (a replay).
  bool insertEvent(int gameId, Map<String, Object?> event);

  /// The game's events in game-time order (then node, then seq).
  List<Map<String, Object?>> events(int gameId, {int? sinceMs, String? type});

  /// The game's events in the order they were written (the site sync's
  /// cursor, slice S7: an event's id is its place here, from 1).
  List<Map<String, Object?>> eventLog(int gameId);
  void saveScores(int gameId, Map<String, int> totals);
  Map<String, int> scores(int gameId);
  void upsertNode(int gameId, Map<String, Object?> info);
  List<Map<String, Object?>> nodes(int gameId);
  String? getSetting(String key);
  void setSetting(String key, String value);
  void deleteSetting(String key);

  /// A service's JSON document, or null when it was never stored (slice
  /// S5: "checkin", the field check-in's records, and "positions", the
  /// players' latest positions; decision PE24-56).
  Object? document(String name);

  /// Stores [value] (JSON data) as the document [name], replacing it whole.
  void putDocument(String name, Object? value);
}

class MemoryControllerStore implements ControllerStore {
  MemoryControllerStore({double Function()? wallSeconds})
    : _wall =
          wallSeconds ?? (() => DateTime.now().microsecondsSinceEpoch / 1e6);

  final double Function() _wall;
  final _games = <int, Map<String, Object?>>{};
  final _keys = <int, Uint8List>{};
  final _events = <int, List<Map<String, Object?>>>{};
  final _eventKeys = <int, Set<(int, int, int, String)>>{};
  final _scores = <int, Map<String, int>>{};
  final _nodes = <int, Map<int, Map<String, Object?>>>{};
  final _settings = <String, String>{};
  final _documents = <String, Object?>{};

  static const _gameFields = {
    'state',
    'term',
    'started_at',
    'ended_at',
    'assignments',
    'duration_ms',
    'team_info',
  };

  @override
  void createGame(Map<String, Object?> game, {Uint8List? key}) {
    final id = game['id']! as int;
    _games[id] = _copy({
      'started_at': null,
      'ended_at': null,
      'controller_id': null,
      ...game,
    });
    if (key != null) _keys[id] = Uint8List.fromList(key);
  }

  @override
  Map<String, Object?>? game(int id) {
    final g = _games[id];
    return g == null ? null : _copy(g);
  }

  @override
  Uint8List? gameKey(int id) {
    final k = _keys[id];
    return k == null ? null : Uint8List.fromList(k);
  }

  @override
  void forgetGameKey(int id) => _keys.remove(id);

  @override
  List<Map<String, Object?>> games() {
    final out = [for (final g in _games.values) _copy(g)];
    out.sort(
      (a, b) => (a['created_at']! as num).compareTo(b['created_at']! as num),
    );
    return out;
  }

  @override
  Map<String, Object?>? liveGame() {
    for (final g in games().reversed) {
      if (liveStates.contains(g['state'])) return g;
    }
    return null;
  }

  @override
  Set<int> gameIds() => _games.keys.toSet();

  @override
  void updateGame(int id, Map<String, Object?> fields) {
    final unknown = fields.keys.toSet().difference(_gameFields);
    if (unknown.isNotEmpty) throw ArgumentError('cannot update $unknown');
    _games[id]?.addAll(_copy(fields));
  }

  /// Settings kept per game as `prefix:id` (they go with the game).
  static const gameSettingPrefixes = [
    'checkin.open',
    'key_tag',
    'game_time',
    'field_scores',
    'field_run',
    'box_lang',
    'issued_nodes',
  ];

  @override
  void deleteGame(int id) {
    _games.remove(id);
    _keys.remove(id);
    _events.remove(id);
    _eventKeys.remove(id);
    _scores.remove(id);
    _nodes.remove(id);
    for (final prefix in gameSettingPrefixes) {
      _settings.remove('$prefix:$id');
    }
  }

  @override
  bool insertEvent(int gameId, Map<String, Object?> ev) =>
      _addEvent(gameId, {
        'node': ev['node'],
        'seq': ev['seq'],
        't': ev['t'],
        'type': ev['type'],
        'team': ev['team'],
        'squad': ev['squad'],
        'prio': ev['prio'] ?? 'normal',
        'data': _copy((ev['data'] as Map?)?.cast<String, Object?>() ?? {}),
        'epoch': ev['epoch'],
        'pkt_seq': ev['pkt_seq'],
        'received_at': _wall(),
      }) !=
      null;

  /// Adds a stored record unless the log has its key: the record, or null.
  Map<String, Object?>? _addEvent(int gameId, Map<String, Object?> record) {
    final key = (
      record['node']! as int,
      record['seq']! as int,
      record['t']! as int,
      record['type']! as String,
    );
    if (!(_eventKeys[gameId] ??= {}).add(key)) return null;
    (_events[gameId] ??= []).add(record);
    return record;
  }

  @override
  List<Map<String, Object?>> events(int gameId, {int? sinceMs, String? type}) {
    final out = [
      for (final e in _events[gameId] ?? const <Map<String, Object?>>[])
        if ((sinceMs == null || (e['t']! as int) >= sinceMs) &&
            (type == null || e['type'] == type))
          _copy(e),
    ];
    out.sort((a, b) {
      for (final k in ['t', 'node', 'seq']) {
        final c = (a[k]! as int).compareTo(b[k]! as int);
        if (c != 0) return c;
      }
      return 0;
    });
    return out;
  }

  @override
  List<Map<String, Object?>> eventLog(int gameId) => [
    for (final e in _events[gameId] ?? const <Map<String, Object?>>[]) _copy(e),
  ];

  @override
  void saveScores(int gameId, Map<String, int> totals) =>
      (_scores[gameId] ??= {}).addAll(totals);

  @override
  Map<String, int> scores(int gameId) => Map.of(_scores[gameId] ?? const {});

  @override
  void upsertNode(int gameId, Map<String, Object?> info) {
    (_nodes[gameId] ??= {})[info['node_id']! as int] = {
      ..._copy(info),
      'last_seen': _wall(),
    };
  }

  @override
  List<Map<String, Object?>> nodes(int gameId) {
    final m = _nodes[gameId] ?? const <int, Map<String, Object?>>{};
    return [for (final k in m.keys.toList()..sort()) _copy(m[k]!)];
  }

  @override
  String? getSetting(String key) => _settings[key];

  @override
  void setSetting(String key, String value) => _settings[key] = value;

  @override
  void deleteSetting(String key) => _settings.remove(key);

  @override
  Object? document(String name) => _deep(_documents[name]);

  @override
  void putDocument(String name, Object? value) =>
      _documents[name] = _deep(value);
}

/// The store's files are not in a form this app reads.
class ControllerStoreException implements Exception {
  ControllerStoreException(this.message);
  final String message;
  @override
  String toString() => 'controller store: $message';
}

/// The controller's store in files under [directory] (decision PE24-40):
///
///     store.json             {"format": 1}
///     settings.json          every setting
///     games/ID.json          the game's record, and its key (hex) only with
///                            persist_game_key, until the game ends
///     games/ID.events.jsonl  the event log, one JSON record per line
///     games/ID.scores.json   the totals per team
///     games/ID.nodes.json    the nodes heard, as the API lists them
///     docs/NAME.json         a service's document (slice S5: the check-in's
///                            records, the players' positions)
///
/// Everything is read into memory when the store opens, and every change is
/// written through before the call returns: a whole file is written to a
/// temporary file, flushed and renamed over the old one, so a crash leaves
/// the old file or the new one; events are appended and flushed, and a last
/// line cut short by a crash is dropped when the store opens again. One
/// controller at a time may open a directory.
class FileControllerStore extends MemoryControllerStore {
  FileControllerStore(this.directory, {super.wallSeconds}) {
    _open();
  }

  /// The files' layout; a newer one is refused.
  static const format = 1;

  final Directory directory;

  /// Lines of event logs that could not be read when the store opened (a
  /// last line cut short by a crash is not counted: it is dropped).
  int unreadableLines = 0;

  Directory get _gamesDir => Directory('${directory.path}/games');
  Directory get _docsDir => Directory('${directory.path}/docs');
  File _file(String name) => File('${directory.path}/$name');
  File _gameFile(int id, String suffix) => File('${_gamesDir.path}/$id$suffix');

  static final _gameFileName = RegExp(r'^(\d+)\.json$');
  static final _docName = RegExp(r'^[a-z][a-z0-9_]{0,31}$');

  void _open() {
    _gamesDir.createSync(recursive: true);
    final marker = _file('store.json');
    if (marker.existsSync()) {
      final f = (_readJson(marker) as Map?)?['format'];
      if (f is! int || f > format) {
        throw ControllerStoreException(
          '${marker.path} has format $f; this app reads up to $format',
        );
      }
    } else {
      _writeJson(marker, {'format': format});
    }
    final settings = _readJson(_file('settings.json'));
    if (settings is Map) {
      settings.forEach((k, v) => _settings['$k'] = '$v');
    }
    _docsDir.createSync(recursive: true);
    for (final entity in _docsDir.listSync()) {
      final name = entity.uri.pathSegments.last;
      if (entity is! File || !name.endsWith('.json')) continue;
      final doc = name.substring(0, name.length - 5);
      if (_docName.hasMatch(doc)) _documents[doc] = _readJson(entity);
    }
    for (final entity in _gamesDir.listSync()) {
      final m = _gameFileName.firstMatch(entity.uri.pathSegments.last);
      if (entity is! File || m == null) continue;
      final id = int.parse(m[1]!);
      final rec = _readJson(entity);
      if (rec is! Map || rec['game'] is! Map) {
        throw ControllerStoreException('${entity.path} is not a game');
      }
      _games[id] = _copy((rec['game'] as Map).cast<String, Object?>());
      final key = rec['key'];
      if (key is String && key.length == 32) _keys[id] = _unhex(key);
      _loadEvents(id);
      final scores = _readJson(_gameFile(id, '.scores.json'));
      if (scores is Map) {
        _scores[id] = {
          for (final e in scores.entries)
            if (e.value is int) '${e.key}': e.value as int,
        };
      }
      final nodes = _readJson(_gameFile(id, '.nodes.json'));
      if (nodes is List) {
        _nodes[id] = {
          for (final n in nodes)
            if (n is Map && n['node_id'] is int)
              n['node_id'] as int: _copy(n.cast<String, Object?>()),
        };
      }
    }
  }

  void _loadEvents(int id) {
    final file = _gameFile(id, '.events.jsonl');
    if (!file.existsSync()) return;
    final bytes = file.readAsBytesSync();
    var start = 0;
    while (start < bytes.length) {
      final nl = bytes.indexOf(0x0a, start);
      if (nl < 0) break; // a last line cut short by a crash: dropped below
      final line = utf8.decode(bytes.sublist(start, nl), allowMalformed: true);
      start = nl + 1;
      if (line.trim().isEmpty) continue;
      if (!_addStored(id, line)) unreadableLines++;
    }
    if (start < bytes.length) {
      final raf = file.openSync(mode: FileMode.append);
      try {
        raf
          ..truncateSync(start)
          ..flushSync();
      } finally {
        raf.closeSync();
      }
    }
  }

  /// One line of an event log back into the log; false if it is not one.
  bool _addStored(int id, String line) {
    final Object? rec;
    try {
      rec = jsonDecode(line);
    } on FormatException {
      return false;
    }
    if (rec is! Map ||
        rec['node'] is! int ||
        rec['seq'] is! int ||
        rec['t'] is! int ||
        rec['type'] is! String) {
      return false;
    }
    _addEvent(id, _copy(rec.cast<String, Object?>()));
    return true;
  }

  void _saveGame(int id) {
    final game = _games[id];
    if (game == null) return;
    final key = _keys[id];
    _writeJson(_gameFile(id, '.json'), {
      'game': game,
      if (key != null) 'key': _hex(key),
    });
  }

  @override
  void createGame(Map<String, Object?> game, {Uint8List? key}) {
    super.createGame(game, key: key);
    _saveGame(game['id']! as int);
  }

  @override
  void forgetGameKey(int id) {
    if (!_keys.containsKey(id)) return;
    super.forgetGameKey(id);
    _saveGame(id);
  }

  @override
  void updateGame(int id, Map<String, Object?> fields) {
    super.updateGame(id, fields);
    _saveGame(id);
  }

  @override
  void deleteGame(int id) {
    final hadSettings = MemoryControllerStore.gameSettingPrefixes.any(
      (p) => _settings.containsKey('$p:$id'),
    );
    super.deleteGame(id);
    for (final suffix in [
      '.json',
      '.events.jsonl',
      '.scores.json',
      '.nodes.json',
    ]) {
      final f = _gameFile(id, suffix);
      if (f.existsSync()) f.deleteSync();
    }
    if (hadSettings) _writeJson(_file('settings.json'), _settings);
  }

  @override
  bool insertEvent(int gameId, Map<String, Object?> ev) {
    if (!super.insertEvent(gameId, ev)) return false;
    final raf = _gameFile(
      gameId,
      '.events.jsonl',
    ).openSync(mode: FileMode.append);
    try {
      raf
        ..writeStringSync('${jsonEncode(_events[gameId]!.last)}\n')
        ..flushSync();
    } finally {
      raf.closeSync();
    }
    return true;
  }

  @override
  void saveScores(int gameId, Map<String, int> totals) {
    super.saveScores(gameId, totals);
    _writeJson(_gameFile(gameId, '.scores.json'), _scores[gameId]);
  }

  @override
  void upsertNode(int gameId, Map<String, Object?> info) {
    super.upsertNode(gameId, info);
    _writeJson(_gameFile(gameId, '.nodes.json'), nodes(gameId));
  }

  @override
  void setSetting(String key, String value) {
    if (_settings[key] == value) return;
    super.setSetting(key, value);
    _writeJson(_file('settings.json'), _settings);
  }

  @override
  void deleteSetting(String key) {
    if (!_settings.containsKey(key)) return;
    super.deleteSetting(key);
    _writeJson(_file('settings.json'), _settings);
  }

  @override
  void putDocument(String name, Object? value) {
    if (!_docName.hasMatch(name)) throw ArgumentError('document name $name');
    super.putDocument(name, value);
    _writeJson(File('${_docsDir.path}/$name.json'), _documents[name]);
  }

  static Object? _readJson(File file) {
    if (!file.existsSync()) return null;
    try {
      return jsonDecode(file.readAsStringSync());
    } on FormatException {
      throw ControllerStoreException('${file.path} is not JSON');
    }
  }

  /// Writes [file] whole: a temporary file, flushed, renamed over it.
  static void _writeJson(File file, Object? value) {
    final tmp = File('${file.path}.tmp');
    final raf = tmp.openSync(mode: FileMode.write);
    try {
      raf
        ..writeStringSync(jsonEncode(value))
        ..flushSync();
    } finally {
      raf.closeSync();
    }
    tmp.renameSync(file.path);
  }
}

String _hex(Uint8List b) =>
    b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();

Uint8List _unhex(String s) => Uint8List.fromList([
  for (var i = 0; i + 1 < s.length; i += 2)
    int.parse(s.substring(i, i + 2), radix: 16),
]);

/// A deep copy of JSON-like data, so callers never share the store's maps.
Map<String, Object?> _copy(Map<String, Object?> m) =>
    _deep(m) as Map<String, Object?>;

Object? _deep(Object? v) => switch (v) {
  Map() => <String, Object?>{
    for (final e in v.entries) '${e.key}': _deep(e.value),
  },
  List() => [for (final e in v) _deep(e)],
  _ => v,
};
