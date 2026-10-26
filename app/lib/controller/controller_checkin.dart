// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Field check-in and the "replicas to chrono" list on the Android field
/// controller (ADR-P3-13, protocol/checkin.md; decision PE24, slice S5): the
/// Pi controller's controller/atalaia_controller/checkin.py, with the same
/// endpoints, records, checks and status codes, checked by the shared
/// contract cases (protocol/vectors/controller_api.json).
///
/// A player scans the field's poster, the app calls POST /api/v1/checkin
/// with its field identity (a player id and a secret, made on the phone once
/// per field) and gets a player token (protocol/player-token.md) signed with
/// the game's own token key, made by this controller (decision B8). The
/// player then declares the replicas they will use; each declaration is
/// `pending` until a signed chrono check-in series for that replica arrives
/// from a marshal's phone (POST /api/v1/chrono/readings), verified with the
/// marshal's registered Ed25519 key, which makes it `passed` or `refused`.
///
/// Personal data is a short list (a display name, an optional federation
/// number nothing checks, a team preference) and stays here: events carry
/// only the player id, the stream sends names to staff connections only, and
/// the retention purge erases them [CheckinConfig.retentionDays] after the
/// game.
///
/// The controller is the authority: a token's role, team and squad are
/// checked against the player's current check-in on every request
/// ([resolve]), so a demotion, a team change or a removal takes effect at
/// once.
///
/// The records are kept in one document of the controller's store
/// ("checkin", decision PE24-56), written whole after every change. Slice
/// S7 (the site sync, controller_sync.dart): rosters of
/// registered players from a site server ([applyRoster]), the outcomes
/// sent back to it ([outcomes]), a marshal's earlier keys
/// ([marshalKeyHistory]) and what the chrono registry's sync reads.
library;

import 'dart:convert';
import 'dart:developer' as developer;
import 'dart:math';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import '../chrono/limit_template.dart';
import '../chrono/reading.dart';
import '../chrono/record_signer.dart';
import '../protocol/checkin_poster.dart';
import '../protocol/checkin_ticket.dart';
import '../security/bytes.dart';
import '../security/player_token.dart';
import 'controller_engine.dart';
import 'field_addresses.dart';

final _playerIdRe = RegExp(r'^p-[a-z2-7]{12}$');
final _secretRe = RegExp(r'^[A-Za-z0-9_-]{43}$');
final _uuidRe = RegExp(
  r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
);
final _classRe = RegExp(r'^[a-z0-9_]{1,32}$');
final _marshalIdRe = RegExp(r'^[A-Za-z0-9._:-]{1,64}$');
final _hex64 = RegExp(r'^[0-9a-fA-F]{64}$');
final _base64Re = RegExp(r'^[A-Za-z0-9+/]*={0,2}$');
final _noticeHeader = RegExp(r'^<!--.*?-->\s*', dotAll: true);
const _base32 = 'abcdefghijklmnopqrstuvwxyz234567';

const replicaTypes = [
  'aeg',
  'gbb',
  'hpa',
  'bolt_action',
  'dmr',
  'sniper',
  'pistol',
  'shotgun',
];
const checkinStatuses = [
  'expected',
  'pending',
  'checked_in',
  'left',
  'removed',
];
const playerRoles = [
  'player',
  'squad_leader',
  'vip',
  'marshal',
  'gm',
  'spectator',
];
const _rank = {
  'spectator': 0,
  'player': 1,
  'squad_leader': 2,
  'vip': 2,
  'marshal': 3,
  'gm': 4,
};
const staffRoles = ['marshal', 'gm'];

/// How long a phone may act as a marshal offline after the controller said
/// yes (MR-4); `GET /api/v1/checkin/me` tells it as `valid_for_s`.
const marshalValidForSeconds = 2 * 3600;
const _nameMax = 32;
const _federationMax = 32;
const _seriesMax = 50;
const _tokenGraceS = 2 * 3600;
const _tokenMinS = 60;
const _identityDays = 365;
const _chronoRetentionDays = 365;
const _settingsKeys = [
  'confirm',
  'federation',
  'federation_label',
  'max_replicas',
  'max_players',
  'chrono_valid_for',
];

/// Who a request or a stream connection belongs to (checkin.py `Viewer`):
/// the GM token, the read token, or a player token whose claims were
/// checked against the player's check-in ([ControllerCheckin.resolve]).
final class ApiViewer {
  const ApiViewer(this.kind, [this.claims = const {}, this.stale = false]);

  static const gm = ApiViewer('gm');
  static const read = ApiViewer('read');

  /// "gm", "read" or "player".
  final String kind;
  final Map<String, Object?> claims;

  /// The token's role, team or squad no longer match the check-in.
  final bool stale;

  String get role => kind == 'player'
      ? claims['role']! as String
      : (kind == 'gm' ? 'gm' : 'spectator');
  String? get playerId =>
      kind == 'player' ? claims['player_id'] as String? : null;
  int? get gameId => kind == 'player' ? claims['game_id'] as int? : null;
  int get team => kind == 'player' ? (claims['team'] as int?) ?? 0 : 0;
  int get squad => kind == 'player' ? (claims['squad'] as int?) ?? 0 : 0;
  bool get isGmToken => kind == 'gm';

  /// The GM token, or a marshal or gm player token: sees names and the
  /// chrono list.
  bool get isStaff =>
      kind == 'gm' || (kind == 'player' && staffRoles.contains(role));

  /// Staff of this game (visibility.py `is_staff`): a player token only for
  /// its own game.
  bool isStaffOf(int? game) =>
      isStaff && (kind != 'player' || game == null || gameId == game);
}

/// What an older token may still do: its own role if the check-in still
/// says it, else the lesser of the two.
String effectiveRole(String tokenRole, String rowRole) {
  if (tokenRole == rowRole) return tokenRole;
  final a = _rank[tokenRole]!, b = _rank[rowRole]!;
  if (a == b) return 'player'; // squad_leader and vip are not above one another
  return a < b ? tokenRole : rowRole;
}

/// The Pi's [checkin] settings (config.py) that apply here.
class CheckinConfig {
  const CheckinConfig({
    required this.limitsYaml,
    this.fieldId = 'field',
    this.fieldName = 'Atalaia',
    this.operator = '',
    this.confirm = 'auto',
    this.federation = 'off',
    this.federationLabel = 'FPA',
    this.maxReplicas = 5,
    this.maxPlayers = 300,
    this.chronoValidFor = 'day',
    this.ratePerMinute = 10,
    this.urls = const [],
    this.wifiSsid = '',
    this.noticeVersion = 1,
    this.noticePt = '',
    this.noticeEn = '',
    this.retentionDays = 30,
    this.utcDay = false,
  });

  /// The chrono limit template the classes come from (a file of
  /// lib/chrono/limit_templates, as text: the shell reads the asset).
  final String limitsYaml;
  final String fieldId;
  final String fieldName;
  final String operator;
  final String confirm;
  final String federation;
  final String federationLabel;
  final int maxReplicas;
  final int maxPlayers;
  final String chronoValidFor;
  final int ratePerMinute;
  final List<String> urls;
  final String wifiSsid;
  final int noticeVersion;

  /// The privacy notice in Portuguese and English (Markdown, as
  /// controller/templates/checkin-notice-*.md).
  final String noticePt;
  final String noticeEn;
  final int retentionDays;

  /// The field's day ends at midnight UTC instead of local midnight (tests).
  final bool utcDay;
}

/// At most [perMinute] calls per key in any 60 s.
class RateLimit {
  RateLimit(this.perMinute, [int Function()? clockMs])
    : _clock = clockMs ?? _monotonic;

  static final _watch = Stopwatch()..start();
  static int _monotonic() => _watch.elapsedMilliseconds;

  final int perMinute;
  final int Function() _clock;
  final _calls = <String, List<int>>{};

  bool allow(String key) {
    final now = _clock();
    final q = _calls.putIfAbsent(key, () => []);
    q.removeWhere((t) => now - t >= 60000);
    if (q.length >= perMinute) return false;
    q.add(now);
    if (_calls.length > 10000) _calls.removeWhere((_, v) => v.isEmpty);
    return true;
  }
}

ControllerError _unauthorized(String m) => ControllerError(m, status: 401);
ControllerError _forbidden(String m) => ControllerError(m, status: 403);

bool _printable(String s) => s.runes.every(
  (c) =>
      !(c < 0x20 || (c >= 0x7f && c <= 0x9f) || (c >= 0xd800 && c <= 0xdfff)),
);

String? _text(
  String name,
  Object? value,
  int maxChars, {
  bool optional = false,
}) {
  if (value == null && optional) return null;
  if (value is! String) throw ControllerError('$name: text');
  final v = value.trim();
  final n = v.runes.length;
  if (n < 1 || n > maxChars || !_printable(v)) {
    throw ControllerError(
      '$name: 1-$maxChars characters without control characters',
    );
  }
  return v;
}

/// Python's truthiness for the values these records hold.
bool _truthy(Object? v) => switch (v) {
  null => false,
  final bool b => b,
  final num n => n != 0,
  final String s => s.isNotEmpty,
  final List<Object?> l => l.isNotEmpty,
  final Map<Object?, Object?> m => m.isNotEmpty,
  _ => true,
};

String _hex(List<int> b) =>
    [for (final x in b) x.toRadixString(16).padLeft(2, '0')].join();

Uint8List _unhex(String s) => Uint8List.fromList([
  for (var i = 0; i + 1 < s.length; i += 2)
    int.parse(s.substring(i, i + 2), radix: 16),
]);

/// One declared replica as the app or staff send it; throws
/// [ControllerError].
Map<String, Object?> validateDeclaration(Object? item) {
  if (item is! Map) throw ControllerError('a declaration is an object');
  const allowed = {
    'declaration_id',
    'replica_id',
    'type',
    'class',
    'make_model',
  };
  final unknown = item.keys.where((k) => !allowed.contains(k)).toList()..sort();
  if (unknown.isNotEmpty) {
    throw ControllerError(
      "declaration: unknown fields $unknown (the state is the controller's)",
    );
  }
  final did = item['declaration_id'];
  if (did is! String || !_uuidRe.hasMatch(did)) {
    throw ControllerError('declaration_id: a lowercase UUID');
  }
  final rid = item['replica_id'];
  if (rid != null && (rid is! String || !_uuidRe.hasMatch(rid))) {
    throw ControllerError('replica_id: a lowercase UUID');
  }
  final rtype = item['type'];
  if (!replicaTypes.contains(rtype)) {
    throw ControllerError('type: one of ${replicaTypes.join(', ')}');
  }
  final rclass = item['class'];
  if (rclass is! String || !_classRe.hasMatch(rclass)) {
    throw ControllerError(
      "class: 1-32 of a-z 0-9 _ (a class of the field's limits)",
    );
  }
  final mm = item['make_model'];
  if (mm != null) {
    if (mm is! String ||
        mm.runes.isEmpty ||
        mm.runes.length > 64 ||
        !_printable(mm)) {
      throw ControllerError(
        'make_model: 1-64 characters without control characters',
      );
    }
  }
  return {
    'declaration_id': did,
    'replica_id': rid,
    'type': rtype,
    'class': rclass,
    'make_model': mm,
  };
}

/// The check-in service of one controller ([ControllerEngine.checkin]).
class ControllerCheckin {
  ControllerCheckin(
    this.engine,
    this.config, {
    this.caSha256,
    List<String> defaultUrls = const [],
    Random? random,
  }) : defaultUrls = List.of(defaultUrls),
       limits = LimitTemplate.parse(config.limitsYaml),
       rate = RateLimit(config.ratePerMinute),
       infoRate = RateLimit(max(60, config.ratePerMinute * 6)),
       _random = random ?? Random.secure() {
    _load();
    engine.checkin = this;
  }

  final ControllerEngine engine;
  final CheckinConfig config;

  /// The field CA's SHA-256 for the poster (the shell's field CA since
  /// slice S6, controller_host.dart); null: the poster says `https_off`.
  Uint8List? caSha256;
  List<String> defaultUrls;

  /// The phone's addresses now (controller_host.dart `_applyLinks`), set by
  /// [useAddresses]: a saved poster's or `config.urls`' address that is on no
  /// interface is then left out and warned about (check-R8). Null: the lists
  /// are used as given (tests).
  FieldAddresses? addresses;

  /// The GM's addresses that are still current (saved poster, else
  /// `config.urls`); empty: the poster is [defaultUrls].
  List<String> explicitUrls = const [];

  /// Where the warnings about a dropped address go (default: the developer
  /// log, `flutter run` and `adb logcat` show it).
  void Function(String message) warn = _warnDefault;
  static void _warnDefault(String m) =>
      developer.log(m, name: 'atalaia.addresses', level: 900);
  final LimitTemplate limits;
  final RateLimit rate;
  final RateLimit infoRate;
  final Random _random;
  double _lastPurge = 0;

  // The records (the Pi store's tables), saved as one document.
  var _fieldPlayers = <String, Map<String, Object?>>{};
  var _checkins = <Map<String, Object?>>[];
  var _declarations = <String, Map<String, Object?>>{};
  var _readings = <Map<String, Object?>>[];
  var _marshals = <String, Map<String, Object?>>{};

  /// The GM's list of marshals (the Pi's `marshal_roster`, schema 12): the
  /// keys above exist only for ids on it.
  var _roster = <String, Map<String, Object?>>{};
  var _replicas = <String, Map<String, Object?>>{};
  var _tokenKeys = <String, String>{};

  /// A marshal's earlier keys with the time each was replaced (the Pi's
  /// `marshal_key_history`, schema 6): what they signed still verifies on
  /// the site server (slice S7's sync).
  var _marshalHistory = <Map<String, Object?>>[];

  double _wall() => engine.wallSeconds();

  // --- the document ---------------------------------------------------------

  static Map<String, Map<String, Object?>> _mapOf(Object? v) => {
    if (v is Map)
      for (final e in v.entries)
        if (e.value is Map)
          '${e.key}': (e.value as Map).cast<String, Object?>(),
  };

  static List<Map<String, Object?>> _listOf(Object? v) => [
    if (v is List)
      for (final e in v)
        if (e is Map) e.cast<String, Object?>(),
  ];

  void _load() {
    final doc = engine.store.document('checkin');
    if (doc is! Map) return;
    final f = doc['format'];
    if (f is! int || f > 1) {
      throw ControllerError.unavailable(
        'the check-in records have format $f; this app reads up to 1',
      );
    }
    _fieldPlayers = _mapOf(doc['field_players']);
    _checkins = _listOf(doc['checkins']);
    _declarations = {
      for (final d in _listOf(doc['declarations']))
        d['declaration_id']! as String: d,
    };
    _readings = _listOf(doc['readings']);
    _marshals = _mapOf(doc['marshals']);
    _roster = _mapOf(doc['marshal_roster']);
    // A marshal registered before the list existed is on it (the Pi's upgrade).
    for (final m in _marshals.values) {
      _roster.putIfAbsent(
        m['marshal_id']! as String,
        () => {
          'marshal_id': m['marshal_id'],
          'name': m['name'],
          'player_id': m['player_id'],
          'created_at': m['registered_at'],
        },
      );
    }
    _replicas = _mapOf(doc['replicas']);
    _marshalHistory = _listOf(doc['marshal_history']);
    _tokenKeys = {
      if (doc['token_keys'] is Map)
        for (final e in (doc['token_keys'] as Map).entries)
          '${e.key}': '${e.value}',
    };
  }

  void _save() => engine.store.putDocument('checkin', {
    'format': 1,
    'field_players': _fieldPlayers,
    'checkins': _checkins,
    'declarations': _declarations.values.toList(),
    'readings': _readings,
    'marshals': _marshals,
    'marshal_roster': _roster,
    'replicas': _replicas,
    'token_keys': _tokenKeys,
    'marshal_history': _marshalHistory,
  });

  // --- the store's queries (store.py) ---------------------------------------

  /// The game's player-token key (decision B8): made once, kept here only.
  Uint8List? tokenKey(int gameId, {bool create = false}) {
    final hex = _tokenKeys['$gameId'];
    if (hex != null) return _unhex(hex);
    if (!create) return null;
    final key = Uint8List.fromList(
      List<int>.generate(32, (_) => _random.nextInt(256)),
    );
    _tokenKeys['$gameId'] = _hex(key);
    return key;
  }

  Map<String, Object?>? _row(int gameId, String pid) {
    for (final r in _checkins) {
      if (r['game_id'] == gameId && r['player_id'] == pid) return r;
    }
    return null;
  }

  Map<String, Object?>? checkinRow(int gameId, String pid) {
    final r = _row(gameId, pid);
    return r == null ? null : Map.of(r);
  }

  List<Map<String, Object?>> _rows(int gameId) {
    final out = [
      for (final r in _checkins)
        if (r['game_id'] == gameId) r,
    ]..sort((a, b) => (a['seq']! as int).compareTo(b['seq']! as int));
    return out;
  }

  int _count(int gameId) => _checkins
      .where(
        (r) =>
            r['game_id'] == gameId &&
            (r['status'] == 'pending' || r['status'] == 'checked_in'),
      )
      .length;

  void _addCheckin(
    int gameId,
    String pid,
    Map<String, Object?> fields,
    double now,
  ) {
    var seq = 0;
    for (final r in _checkins) {
      if (r['game_id'] == gameId) seq = max(seq, r['seq']! as int);
    }
    _checkins.add({
      'game_id': gameId,
      'player_id': pid,
      'seq': seq + 1,
      'created_at': now,
      'updated_at': now,
      'status': 'pending',
      'display_name': null,
      'federation_number': null,
      'federation_seen': false,
      'team_preference': null,
      'team': 0,
      'squad': 0,
      'role': 'player',
      'manual': false,
      'notice_version': null,
      'checked_in_at': null,
      'erased_at': null,
      'registration_id': null,
      'ticket_sha256': null,
      'from_roster': false,
      ...fields,
    });
  }

  void _update(int gameId, String pid, Map<String, Object?> fields) =>
      _row(gameId, pid)?.addAll(fields);

  Map<String, Object?>? _byRegistration(int gameId, String regId) {
    for (final r in _checkins) {
      if (r['game_id'] == gameId && r['registration_id'] == regId) return r;
    }
    return null;
  }

  List<Map<String, Object?>> _decls(int gameId, [String? pid]) {
    final out = [
      for (final d in _declarations.values)
        if (d['game_id'] == gameId && (pid == null || d['player_id'] == pid)) d,
    ]..sort((a, b) => (a['position']! as int).compareTo(b['position']! as int));
    return out;
  }

  void _putDeclaration(Map<String, Object?> d, double now) {
    final id = d['declaration_id']! as String;
    final old = _declarations[id];
    _declarations[id] = {
      for (final k in [
        'declaration_id',
        'game_id',
        'player_id',
        'replica_id',
        'type',
        'class',
        'make_model',
        'state',
        'reading_id',
        'position',
      ])
        k: d[k],
      'created_at': old?['created_at'] ?? now,
      'updated_at': now,
    };
  }

  /// Readings, oldest first (by timestamp, then reading id).
  List<Map<String, Object?>> _readingsOf({
    String? replicaId,
    String? playerId,
    List<String>? ids,
  }) {
    final out = [
      for (final r in _readings)
        if ((replicaId == null || r['replica_id'] == replicaId) &&
            (playerId == null || r['player_id'] == playerId) &&
            (ids == null || ids.contains(r['reading_id'])))
          r,
    ];
    out.sort((a, b) {
      final c = (a['timestamp']! as String).compareTo(
        b['timestamp']! as String,
      );
      return c != 0
          ? c
          : (a['reading_id']! as String).compareTo(b['reading_id']! as String);
    });
    return out;
  }

  int _deleteReadings({String? playerId, String? before}) {
    final n = _readings.length;
    if (playerId != null) {
      _readings.removeWhere((r) => r['player_id'] == playerId);
    } else if (before != null) {
      _readings.removeWhere(
        (r) => (r['timestamp']! as String).compareTo(before) < 0,
      );
    }
    return n - _readings.length;
  }

  void _erasePlayerRecords(String pid) {
    _declarations.removeWhere((_, d) => d['player_id'] == pid);
    _checkins.removeWhere((r) => r['player_id'] == pid);
    _fieldPlayers.remove(pid);
    engine.positions?.erasePlayer(pid);
  }

  // --- settings and the poster ------------------------------------------------

  Map<String, Object?> settings() {
    final out = <String, Object?>{
      'confirm': config.confirm,
      'federation': config.federation,
      'federation_label': config.federationLabel,
      'max_replicas': config.maxReplicas,
      'max_players': config.maxPlayers,
      'chrono_valid_for': config.chronoValidFor,
    };
    final saved = engine.store.getSetting('checkin.settings');
    if (saved != null) {
      try {
        final m = jsonDecode(saved);
        if (m is Map) {
          for (final e in m.entries) {
            if (_settingsKeys.contains(e.key)) out['${e.key}'] = e.value;
          }
        }
      } on FormatException {
        // As the Pi: a setting that is not JSON is ignored.
      }
    }
    return out;
  }

  Map<String, Object?> setSettings(Map<String, Object?> spec) {
    final unknown = spec.keys.where((k) => !_settingsKeys.contains(k)).toList()
      ..sort();
    if (unknown.isNotEmpty) {
      throw ControllerError('unknown check-in settings $unknown');
    }
    final cur = settings();
    const choices = {
      'confirm': ['auto', 'staff'],
      'federation': ['off', 'optional', 'required'],
      'chrono_valid_for': ['day', 'game'],
    };
    for (final e in spec.entries) {
      final k = e.key, v = e.value;
      final c = choices[k];
      if (c != null && !c.contains(v)) {
        throw ControllerError('$k: one of ${c.join(', ')}');
      }
      if (k == 'federation_label') _text(k, v, 16);
      if (k == 'max_replicas' && (v is! int || v < 1 || v > 20)) {
        throw ControllerError('max_replicas: 1-20');
      }
      if (k == 'max_players' && (v is! int || v < 1 || v > 5000)) {
        throw ControllerError('max_players: 1-5000');
      }
      cur[k] = v is String ? v.trim() : v;
    }
    engine.store.setSetting(
      'checkin.settings',
      jsonEncode({for (final k in _settingsKeys) k: cur[k]}),
    );
    engine.emit({'type': 'checkin_settings', 'settings': cur, '_staff': true});
    return cur;
  }

  Map<String, Object?> _savedPoster() {
    final raw = engine.store.getSetting('checkin.poster');
    if (raw == null) return {};
    try {
      final m = jsonDecode(raw);
      return m is Map ? m.cast<String, Object?>() : {};
    } on FormatException {
      return {};
    }
  }

  List<String> _savedUrls() {
    final u = _savedPoster()['urls'];
    return u is List
        ? [
            for (final x in u)
              if (x is String) x,
          ]
        : const [];
  }

  void _warnDropped(Iterable<String> dropped) {
    for (final d in dropped) {
      warn(
        'check-in poster: $d is not an address on any interface of this '
        'phone now: left out of the poster and the server certificate '
        '(a host name would stay)',
      );
    }
  }

  /// The addresses this phone has now (every start and every change of
  /// them). The saved poster is re-derived, not kept as it was: its urls that
  /// are stale are dropped from the setting (it keeps its other fields).
  void useAddresses(FieldAddresses a, {bool quiet = false}) {
    addresses = a;
    final had = _savedUrls();
    final plan = a.plan(saved: had, checkinUrls: config.urls);
    if (!quiet) _warnDropped(plan.dropped);
    final (kept, _) = a.keep(had);
    if (kept.length != had.length) {
      final doc = {..._savedPoster()};
      if (kept.isEmpty) {
        doc.remove('urls');
      } else {
        doc['urls'] = kept;
      }
      engine.store.setSetting('checkin.poster', jsonEncode(doc));
    }
    explicitUrls = plan.explicit;
  }

  Map<String, Object?> posterFields() {
    final saved = _savedPoster();
    final List<Object?> urls;
    if (addresses != null) {
      urls = explicitUrls.isNotEmpty ? explicitUrls : defaultUrls;
    } else {
      urls = _truthy(saved['urls'])
          ? saved['urls']! as List
          : (config.urls.isNotEmpty ? config.urls : defaultUrls);
    }
    final name = saved['field_name'];
    final ssid = saved.containsKey('wifi_ssid')
        ? saved['wifi_ssid']
        : (config.wifiSsid.isEmpty ? null : config.wifiSsid);
    return {
      'field_id': config.fieldId,
      'field_name': _truthy(name) ? name : config.fieldName,
      'urls': urls.take(3).toList(),
      'ca_sha256': caSha256,
      'wifi_ssid': _truthy(ssid) ? ssid : null,
      'game_id': saved['game_id'],
    };
  }

  Map<String, Object?> poster() {
    final p = posterFields();
    final ca = p['ca_sha256'] as Uint8List?;
    final out = <String, Object?>{
      for (final e in p.entries)
        if (e.key != 'ca_sha256') e.key: e.value,
      'ca_sha256': ca == null ? null : _hex(ca),
      'ca_short': ca == null ? null : shortFingerprint(ca),
    };
    if (ca == null) {
      out['text'] = null;
      out['problem_code'] = 'https_off';
      out['problem'] =
          "HTTPS is off on this phone controller: the poster needs the field's CA";
    } else if ((p['urls']! as List).isEmpty) {
      out['text'] = null;
      out['problem_code'] = 'no_address';
      out['problem'] = 'no https address for the poster';
    } else {
      try {
        out['text'] = posterToText(encodePosterFields(p));
        out['problem'] = out['problem_code'] = null;
      } on PosterException catch (e) {
        out['text'] = null;
        out['problem_code'] = e.reason == PosterFailure.length
            ? 'too_long'
            : 'invalid';
        out['problem'] = e.message;
      }
    }
    return out;
  }

  Map<String, Object?> setPoster(Map<String, Object?> spec) {
    const keys = ['urls', 'wifi_ssid', 'game_id', 'field_name'];
    final unknown = spec.keys.where((k) => !keys.contains(k)).toList()..sort();
    if (unknown.isNotEmpty) {
      throw ControllerError('unknown poster fields $unknown');
    }
    final a = addresses;
    var given = spec;
    if (a != null && spec['urls'] is List) {
      // An address typed now that is on no interface is left out, as at start.
      final (kept, dropped) = a.keep([
        for (final u in spec['urls']! as List)
          if (u is String) u,
      ]);
      _warnDropped(dropped);
      given = {...spec, 'urls': kept};
    }
    final trial = {...posterFields(), ...given};
    if (trial['wifi_ssid'] == '') trial['wifi_ssid'] = null;
    if (!_truthy(trial['urls'])) {
      trial['urls'] = config.urls.isNotEmpty ? config.urls : defaultUrls;
    }
    // Checked even before the phone has an address or its CA (decision
    // PE24-58): a placeholder stands in for what is missing, so a bad
    // field is refused now, not when HTTPS comes.
    final checked = {
      ...trial,
      if (!_truthy(trial['urls'])) 'urls': ['https://a.invalid'],
      if (trial['ca_sha256'] == null) 'ca_sha256': Uint8List(32),
    };
    try {
      encodePosterFields(checked);
    } on PosterException catch (e) {
      throw ControllerError(e.message);
    }
    final saved = {for (final k in keys) k: trial[k]};
    if (!spec.containsKey('urls') || (a != null && !_truthy(given['urls']))) {
      saved.remove('urls');
    }
    engine.store.setSetting('checkin.poster', jsonEncode(saved));
    if (a != null) useAddresses(a, quiet: true);
    return poster();
  }

  Map<String, Object?> notice() {
    final texts = <String, Object?>{};
    for (final (lang, text) in [
      ('pt', config.noticePt),
      ('en', config.noticeEn),
    ]) {
      final body = text.replaceFirst(_noticeHeader, '');
      final op = config.operator.isNotEmpty
          ? config.operator
          : '${posterFields()['field_name']}';
      texts[lang] = body
          .replaceAll('{operator}', op)
          .replaceAll('{retention_days}', '${config.retentionDays}');
    }
    return {'version': config.noticeVersion, ...texts};
  }

  // --- games open for check-in ------------------------------------------------

  bool isOpen(int gameId) {
    final game = engine.store.game(gameId);
    if (game == null || game['state'] == 'ended' || game['joined'] == true) {
      return false;
    }
    return engine.store.getSetting('checkin.open:$gameId') != '0';
  }

  Map<String, Object?> setOpen(int gameId, bool open) {
    final game = engine.getGame(gameId);
    if (game['state'] == 'ended') {
      throw ControllerError.conflict('game $gameId has ended');
    }
    engine.store.setSetting('checkin.open:$gameId', open ? '1' : '0');
    final out = {'game_id': gameId, 'open': isOpen(gameId)};
    engine.emit({'type': 'checkin_open', 'game': gameId, 'open': out['open']});
    return out;
  }

  List<Map<String, Object?>> openGames() {
    var out = <Map<String, Object?>>[
      for (final g in engine.store.games())
        if (g['state'] != 'ended' && isOpen(g['id']! as int))
          {
            'game_id': g['id'],
            'name': g['name'],
            'state': g['state'],
            'teams': g['teams'],
            'squads': (g['squads'] as int?) ?? 0,
          },
    ];
    final pinned = posterFields()['game_id'];
    if (_truthy(pinned)) {
      out = [
        for (final g in out)
          if (g['game_id'] == pinned) g,
      ];
    }
    return out;
  }

  /// GET /api/v1/checkin: what a player's app needs before checking in. No
  /// names.
  Map<String, Object?> info() {
    final p = posterFields();
    return {
      'version': 1,
      'field': {
        'id': config.fieldId,
        'name': p['field_name'],
        'operator': config.operator.isEmpty ? null : config.operator,
      },
      'notice': notice(),
      'settings': {
        for (final e in settings().entries)
          if (e.key != 'max_players') e.key: e.value,
      },
      'limits': {
        'id': limits.id,
        'name': limits.name,
        'status': limits.verified ? 'verified' : 'unverified',
        'classes': limits.classes.keys.toList()..sort(),
      },
      'replica_types': replicaTypes,
      'games': openGames(),
    };
  }

  // --- tokens -------------------------------------------------------------------

  DateTime _at(double ts) => DateTime.fromMicrosecondsSinceEpoch(
    (ts * 1e6).round(),
    isUtc: config.utcDay,
  );

  double _localDayEnd(double now) {
    final d = _at(now);
    final next = config.utcDay
        ? DateTime.utc(d.year, d.month, d.day + 1)
        : DateTime(d.year, d.month, d.day + 1);
    return next.microsecondsSinceEpoch / 1e6;
  }

  /// The field's day of [ts] (local time, or UTC with [CheckinConfig.utcDay]).
  (int, int, int) localDay(double ts) {
    final d = _at(ts);
    return (d.year, d.month, d.day);
  }

  /// The game's planned end plus 2 hours, or the end of the field's day,
  /// whichever is first.
  int tokenExp(Map<String, Object?> game, double now) {
    var exp = _localDayEnd(now);
    final dur = game['duration_ms'], started = game['started_at'];
    if (_truthy(dur) && _truthy(started)) {
      exp = min(exp, (started! as num) + (dur! as num) / 1000 + _tokenGraceS);
    }
    return max(exp, now + _tokenMinS).floor();
  }

  (String, int) issueToken(
    Map<String, Object?> game,
    Map<String, Object?> row,
  ) {
    final id = game['id']! as int;
    final key = tokenKey(id, create: true)!;
    final exp = tokenExp(game, _wall());
    final claims = PlayerClaims(
      playerId: row['player_id']! as String,
      team: row['team']! as int,
      squad: row['squad']! as int,
      role: PlayerRole.fromWire(row['role']! as String)!,
      gameId: id,
      exp: exp,
    );
    return (PlayerToken.issue(claims, key), exp);
  }

  /// A player token's viewer, its claims checked against the check-in row;
  /// throws [ControllerError] (401).
  ApiViewer resolve(String token) {
    int gameId;
    try {
      final parts = token.split('.');
      if (parts.length != 3) throw const FormatException();
      final raw = base64Url.decode(base64Url.normalize(parts[1]));
      final payload = jsonDecode(utf8.decode(raw));
      final gid = payload is Map ? payload['game_id'] : null;
      if (gid is! int) throw const FormatException();
      gameId = gid;
    } on FormatException {
      throw _unauthorized('not a valid token');
    }
    final key = tokenKey(gameId);
    final game = engine.store.game(gameId);
    if (key == null || game == null) throw _unauthorized('not a valid token');
    final PlayerClaims claims;
    try {
      claims = PlayerToken.verify(
        token,
        key,
        gameId: gameId,
        teamCount: (game['teams']! as List).length,
        now: _wall().floor(),
      );
    } on TokenException catch (e) {
      throw _unauthorized('player token refused (${e.reason.name})');
    }
    final row = _row(gameId, claims.playerId);
    if (row == null || row['status'] == 'left' || row['status'] == 'removed') {
      throw _unauthorized('this check-in is no longer valid; check in again');
    }
    final eff = claims.toJson().cast<String, Object?>();
    eff['role'] = effectiveRole(claims.role.wire, row['role']! as String);
    eff['team'] = row['team'];
    eff['squad'] = row['squad'];
    final stale =
        claims.role.wire != row['role'] ||
        claims.team != row['team'] ||
        claims.squad != row['squad'];
    return ApiViewer('player', eff, stale);
  }

  // --- checking in ----------------------------------------------------------------

  int _teamId(Map<String, Object?> game, Object? team, [String name = 'team']) {
    final teams = (game['teams']! as List).cast<String>();
    if (team == null || team == 0 || team == '' || team == false) return 0;
    if (team is String) {
      if (!teams.contains(team)) throw ControllerError('$name: one of $teams');
      return teams.indexOf(team) + 1;
    }
    if (team is! int || team < 0 || team > teams.length) {
      throw ControllerError('$name: a team of the game');
    }
    return team;
  }

  static String? _teamName(Map<String, Object?> game, int teamId) {
    final teams = game['teams']! as List;
    return teamId >= 1 && teamId <= teams.length
        ? teams[teamId - 1] as String
        : null;
  }

  /// POST /api/v1/checkin from [client] (its address): the answer and
  /// whether a check-in was made (201) or taken up again (200).
  (Map<String, Object?>, bool) checkIn(
    Map<String, Object?> body,
    String client,
  ) {
    if (!rate.allow(client)) {
      throw ControllerError(
        'too many check-ins from this address; wait a minute',
        status: 429,
      );
    }
    const allowed = {
      'game_id',
      'player_id',
      'player_secret',
      'display_name',
      'federation_number',
      'team_preference',
      'notice_version',
      'replicas',
      'registration_id',
      'ticket',
    };
    final unknown = body.keys.where((k) => !allowed.contains(k)).toList()
      ..sort();
    if (unknown.isNotEmpty) throw ControllerError('unknown fields $unknown');
    final gameId = body['game_id'];
    if (gameId is! int) throw ControllerError("game_id: the game's id");
    final game = engine.store.game(gameId);
    if (game == null) throw ControllerError.notFound('no game $gameId');
    if (!isOpen(gameId)) {
      throw _forbidden('check-in for game $gameId is closed');
    }
    final pinned = posterFields()['game_id'];
    if (_truthy(pinned) && pinned != gameId) {
      throw _forbidden("this field's check-in is for another game");
    }
    final pid = body['player_id'];
    if (pid is! String || !_playerIdRe.hasMatch(pid)) {
      throw ControllerError('player_id: p- and 12 of a-z 2-7');
    }
    final secret = _secretBytes(body['player_secret']);
    final (regId, ticketHex) = _registrationProof(body);
    final st = settings();
    final name = _text('display_name', body['display_name'], _nameMax);
    final fedIn = _text(
      'federation_number',
      _truthy(body['federation_number']) ? body['federation_number'] : null,
      _federationMax,
      optional: true,
    );
    var pref = body['team_preference'];
    if (pref != null) _teamId(game, pref, 'team_preference');
    final notice = body['notice_version'];
    if (notice != config.noticeVersion) {
      throw ControllerError.conflict(
        'the privacy notice changed: read it again (GET /api/v1/checkin)',
      );
    }
    final replicas = body['replicas'];
    final decls = replicas == null ? null : _checkDeclarations(replicas, st);
    final now = _wall();
    final digest = _hex(sha256.convert(secret).bytes);
    final known = _fieldPlayers[pid];
    var row = _row(gameId, pid);
    final expected = _expectedMatch(gameId, pid, row, known, regId, ticketHex);
    if (known != null) {
      final stored = known['secret_sha256'] as String?;
      if (stored == null ||
          !constantTimeEquals(utf8.encode(stored), utf8.encode(digest))) {
        throw ControllerError.conflict(
          "this player id is someone else's at this field",
        );
      }
      known['last_seen_at'] = now;
    }
    if (row != null && row['status'] == 'removed') {
      throw _forbidden('staff removed this check-in; ask at the desk');
    }
    // A registered player's roster entry fills in what the app did not send.
    var fed = fedIn != null || expected == null
        ? fedIn
        : expected['federation_number'] as String?;
    if (pref == null &&
        expected != null &&
        (game['teams']! as List).contains(expected['team_preference'])) {
      pref = expected['team_preference'];
    }
    if (st['federation'] == 'off') {
      fed = null;
    } else if (st['federation'] == 'required' && fed == null) {
      throw ControllerError(
        'federation_number: this field asks for your '
        '${st['federation_label']} number',
      );
    }
    final created = row == null || row['status'] == 'expected';
    var emit = false;
    if (created) {
      if (_count(gameId) >= (st['max_players']! as int)) {
        throw _forbidden('game $gameId is full (${st['max_players']} players)');
      }
      if (known == null) {
        _fieldPlayers[pid] = {
          'player_id': pid,
          'secret_sha256': digest,
          'created_at': now,
          'last_seen_at': now,
        };
      }
      final status = st['confirm'] == 'auto' ? 'checked_in' : 'pending';
      final fields = <String, Object?>{
        'status': status,
        'display_name': name,
        'federation_number': fed,
        'team_preference': pref,
        'notice_version': notice,
        'checked_in_at': status == 'checked_in' ? now : null,
      };
      if (row == null) {
        if (regId != null) {
          // No roster here: kept, so the site server can match it later.
          fields['registration_id'] = regId;
          fields['ticket_sha256'] = ticketHex;
        }
        _addCheckin(gameId, pid, fields, now);
      } else {
        _update(gameId, pid, {...fields, 'updated_at': now});
      }
      emit = status == 'checked_in';
    } else {
      var status = row['status']! as String;
      if (status == 'left') {
        status = st['confirm'] == 'auto' ? 'checked_in' : 'pending';
        emit = status == 'checked_in';
      }
      final fields = <String, Object?>{
        'status': status,
        'display_name': name,
        'team_preference': pref,
        'notice_version': notice,
        'updated_at': now,
      };
      if (fed != row['federation_number']) {
        fields['federation_number'] = fed;
        fields['federation_seen'] = false;
      }
      if (emit) fields['checked_in_at'] = now;
      if (regId != null && row['registration_id'] == null) {
        fields['registration_id'] = regId;
        fields['ticket_sha256'] = ticketHex;
      }
      _update(gameId, pid, fields);
    }
    if (decls != null) {
      _replaceDeclarations(game, pid, decls, staff: false, now: now);
    }
    row = _row(gameId, pid)!;
    final (token, exp) = issueToken(game, row);
    _save();
    if (emit) _emitCheckinEvent(game, row);
    _notify(gameId, pid);
    return (_tokenAnswer(game, row, token, exp), created);
  }

  static Uint8List _secretBytes(Object? value) {
    final raw = value is String && _secretRe.hasMatch(value)
        ? base64UrlNoPadDecode(value)
        : null;
    if (raw == null || raw.length != 32) {
      throw ControllerError(
        'player_secret: 32 bytes in base64url without padding (43 characters)',
      );
    }
    return raw;
  }

  Map<String, Object?> _tokenAnswer(
    Map<String, Object?> game,
    Map<String, Object?> row,
    String token,
    int exp,
  ) => {
    'game_id': game['id'],
    'player_id': row['player_id'],
    'token': token,
    'exp': exp,
    'status': row['status'],
    'team': _teamName(game, row['team']! as int),
    'team_id': row['team'],
    'squad': row['squad'],
    'role': row['role'],
  };

  /// `registration_id` and `ticket` (both or neither): the id and the
  /// ticket's SHA-256 (hex).
  (String?, String?) _registrationProof(Map<String, Object?> body) {
    final regId = body['registration_id'], ticket = body['ticket'];
    if (regId == null && ticket == null) return (null, null);
    if (regId == null || ticket == null) {
      throw ControllerError('registration_id and ticket go together');
    }
    if (regId is! String || !_uuidRe.hasMatch(regId)) {
      throw ControllerError('registration_id: a lowercase UUID');
    }
    final raw = ticket is String && _secretRe.hasMatch(ticket)
        ? base64UrlNoPadDecode(ticket)
        : null;
    if (raw == null || raw.length != 32) {
      throw ControllerError(
        'ticket: 32 bytes in base64url without padding (43 characters)',
      );
    }
    return (regId, _hex(sha256.convert(raw).bytes));
  }

  /// The roster's check-in this arrival is, checked against its ticket;
  /// null for a walk-in (checkin.py `_expected_match`).
  Map<String, Object?>? _expectedMatch(
    int gameId,
    String pid,
    Map<String, Object?>? row,
    Map<String, Object?>? known,
    String? regId,
    String? ticketHex,
  ) {
    if (regId != null) {
      final match = _byRegistration(gameId, regId);
      if (match != null && match['from_roster'] == true) {
        if (match['player_id'] != pid) {
          throw ControllerError.conflict(
            'this registration is for another player id at this field',
          );
        }
        final want = match['ticket_sha256'] as String?;
        if (want == null ||
            want.isEmpty ||
            !constantTimeEquals(
              utf8.encode(want),
              utf8.encode(ticketHex ?? ''),
            )) {
          throw _forbidden(
            "this ticket is not this registration's (was a newer one made?)",
          );
        }
        return match;
      }
    }
    if (row != null && row['from_roster'] == true && known == null) {
      throw _forbidden(
        'this player id is registered for the game: check in with the '
        "registration's ticket",
      );
    }
    return row != null && row['from_roster'] == true ? row : null;
  }

  Map<String, Object?> refreshToken(ApiViewer viewer) {
    final game = engine.store.game(viewer.gameId!);
    final row = _row(viewer.gameId!, viewer.playerId!);
    if (game == null || row == null) {
      throw _unauthorized('this check-in is no longer valid');
    }
    if (game['state'] == 'ended') {
      throw ControllerError.conflict('the game has ended');
    }
    final (token, exp) = issueToken(game, row);
    _save();
    return _tokenAnswer(game, row, token, exp);
  }

  /// player.checkin as the controller's node: the player id only, never the
  /// name.
  void _emitCheckinEvent(Map<String, Object?> game, Map<String, Object?> row) {
    engine.logControllerEvent(game['id']! as int, 'player.checkin', {
      'player': row['player_id'],
    }, team: _teamName(game, row['team']! as int));
  }

  // --- the player's own check-in ------------------------------------------------

  Map<String, Object?> _declView(
    Map<String, Object?> d, [
    bool refusedToday = false,
  ]) => {
    for (final k in [
      'declaration_id',
      'replica_id',
      'type',
      'class',
      'make_model',
      'state',
      'reading_id',
    ])
      k: d[k],
    if (refusedToday) 'refused_today': true,
  };

  List<Map<String, Object?>> _declViews(int gameId, String pid) => [
    for (final d in _decls(gameId, pid)) _declView(d, _refusedToday(d)),
  ];

  Map<String, Object?> rowView(
    Map<String, Object?> game,
    Map<String, Object?> row, {
    bool names = true,
    bool declarations = true,
  }) {
    final out = <String, Object?>{
      'game_id': game['id'],
      'player_id': row['player_id'],
      'status': row['status'],
      'team': _teamName(game, row['team']! as int),
      'team_id': row['team'],
      'squad': row['squad'],
      'role': row['role'],
      'manual': row['manual'],
      'checked_in_at': row['checked_in_at'],
      'seq': row['seq'],
      'registration_id': row['registration_id'],
      'registered': _truthy(row['registration_id']),
    };
    if (names) {
      out.addAll({
        'display_name': row['display_name'],
        'federation_number': row['federation_number'],
        'federation_seen': row['federation_seen'],
        'team_preference': row['team_preference'],
      });
    }
    if (declarations) {
      out['declarations'] = _declViews(
        game['id']! as int,
        row['player_id']! as String,
      );
    }
    return out;
  }

  /// The player's own check-in as the stream's hello gives it, or null.
  Map<String, Object?>? me(ApiViewer viewer, {bool forHello = false}) {
    final game = engine.store.game(viewer.gameId!);
    final row = _row(viewer.gameId!, viewer.playerId!);
    if (game == null || row == null) {
      if (forHello) return null;
      throw ControllerError.notFound('no check-in');
    }
    final out = rowView(game, row)..['stale_token'] = viewer.stale;
    if (!forHello && row['role'] == 'marshal') {
      out['marshal'] = myMarshal(viewer);
    }
    if (!forHello) {
      out['settings'] = {
        for (final e in settings().entries)
          if (e.key != 'max_players') e.key: e.value,
      };
    }
    return out;
  }

  List<Map<String, Object?>> _checkDeclarations(
    Object? items,
    Map<String, Object?> st,
  ) {
    if (items is! List) {
      throw ControllerError('replicas: a list of declarations');
    }
    if (items.length > (st['max_replicas']! as int)) {
      throw ControllerError(
        'at most ${st['max_replicas']} replicas per player and game',
      );
    }
    final out = [for (final i in items) validateDeclaration(i)];
    final ids = [for (final d in out) d['declaration_id']];
    if (ids.toSet().length != ids.length) {
      throw ControllerError('each declaration_id once');
    }
    final rids = [
      for (final d in out)
        if (_truthy(d['replica_id'])) d['replica_id'],
    ];
    if (rids.toSet().length != rids.length) {
      throw ControllerError('each replica once');
    }
    for (final d in out) {
      if (!limits.classes.containsKey(d['class'])) {
        throw ControllerError(
          "class '${d['class']}' is not one of the field's "
          '${limits.classes.keys.toList()..sort()}',
        );
      }
    }
    return out;
  }

  void _replaceDeclarations(
    Map<String, Object?> game,
    String pid,
    List<Map<String, Object?>> items, {
    required bool staff,
    required double now,
  }) {
    final gid = game['id']! as int;
    final existing = {
      for (final d in _decls(gid, pid)) d['declaration_id']! as String: d,
    };
    final newIds = {for (final d in items) d['declaration_id']};
    for (final d in items) {
      final other = _declarations[d['declaration_id']];
      if (other != null &&
          (other['game_id'] != gid || other['player_id'] != pid)) {
        throw ControllerError.conflict(
          'declaration ${d['declaration_id']} belongs to someone else',
        );
      }
    }
    if (!staff) {
      for (final e in existing.entries) {
        final d = e.value;
        if (d['state'] == 'passed' || d['state'] == 'refused') {
          final kept = items
              .where((i) => i['declaration_id'] == e.key)
              .firstOrNull;
          if (kept == null ||
              ['replica_id', 'type', 'class'].any((k) => kept[k] != d[k])) {
            throw ControllerError.conflict(
              'a chronographed replica stays declared; ask a marshal to change it',
            );
          }
        }
      }
    }
    for (var pos = 0; pos < items.length; pos++) {
      final d = items[pos];
      final old = existing[d['declaration_id']];
      final row = <String, Object?>{
        ...d,
        'game_id': gid,
        'player_id': pid,
        'position': pos,
      };
      if (old != null &&
          old['state'] != 'withdrawn' &&
          old['replica_id'] == d['replica_id']) {
        row['state'] = old['state'];
        row['reading_id'] = old['reading_id'];
      } else {
        row['state'] = 'pending';
        row['reading_id'] = null;
        final rid = d['replica_id'];
        if (rid is String && rid.isNotEmpty) {
          final passed = _passedEarlier(rid, pid, now);
          if (passed != null) {
            row['state'] = 'passed';
            row['reading_id'] = passed;
          }
        }
      }
      _putDeclaration(row, now);
    }
    for (final e in existing.entries) {
      if (!newIds.contains(e.key) && e.value['state'] != 'withdrawn') {
        _putDeclaration({...e.value, 'state': 'withdrawn'}, now);
      }
    }
  }

  Map<String, Object?> putMyReplicas(
    ApiViewer viewer,
    Map<String, Object?> body,
  ) {
    final game = engine.store.game(viewer.gameId!)!;
    if (game['state'] == 'ended') {
      throw ControllerError.conflict('the game has ended');
    }
    final decls = _checkDeclarations(body['replicas'], settings());
    _replaceDeclarations(
      game,
      viewer.playerId!,
      decls,
      staff: false,
      now: _wall(),
    );
    _save();
    _notify(game['id']! as int, viewer.playerId!);
    return {'declarations': _declViews(game['id']! as int, viewer.playerId!)};
  }

  /// DELETE /api/v1/checkin/me: the player leaves the game; the personal
  /// fields are erased.
  Map<String, Object?> leave(ApiViewer viewer) {
    final gid = viewer.gameId!, pid = viewer.playerId!;
    final now = _wall();
    _eraseRow(gid, pid, 'left', now);
    _save();
    _notify(gid, pid);
    return {'game_id': gid, 'player_id': pid, 'status': 'left'};
  }

  void _eraseRow(int gid, String pid, String status, double now) {
    _update(gid, pid, {
      'status': status,
      'display_name': null,
      'federation_number': null,
      'federation_seen': false,
      'team_preference': null,
      'updated_at': now,
      'erased_at': now,
    });
    for (final d in _decls(gid, pid)) {
      if (d['state'] == 'pending') {
        _putDeclaration({...d, 'state': 'withdrawn'}, now);
      }
    }
  }

  // --- staff ------------------------------------------------------------------------

  Map<String, Object?> _staff(ApiViewer viewer, int gameId) {
    if (!viewer.isStaff) {
      throw _forbidden("staff only: the GM token or a marshal's token");
    }
    if (viewer.kind == 'player' && viewer.gameId != gameId) {
      throw _forbidden('this token is for another game');
    }
    return engine.getGame(gameId);
  }

  Map<String, Object?> listCheckins(ApiViewer viewer, int gameId) {
    final game = _staff(viewer, gameId);
    final rows = [for (final r in _rows(gameId)) rowView(game, r)];
    int count(String s) => rows.where((r) => r['status'] == s).length;
    final arrived = rows.where(
      (r) => r['status'] == 'pending' || r['status'] == 'checked_in',
    );
    return {
      'game_id': gameId,
      'open': isOpen(gameId),
      'settings': settings(),
      'squads': (game['squads'] as int?) ?? 0,
      'counts': {for (final s in checkinStatuses) s: count(s)},
      'checkins': rows,
      'registrations': {
        'expected': count('expected'),
        'arrived': arrived.where((r) => r['registered'] == true).length,
        'walkins': arrived.where((r) => r['registered'] != true).length,
      },
    };
  }

  String _newPlayerId() =>
      'p-${List.generate(12, (_) => _base32[_random.nextInt(32)]).join()}';

  /// A player without the app, checked in by a marshal or the GM.
  Map<String, Object?> manualCheckin(
    ApiViewer viewer,
    int gameId,
    Map<String, Object?> body,
  ) {
    final game = _staff(viewer, gameId);
    if (game['state'] == 'ended') {
      throw ControllerError.conflict('the game has ended');
    }
    const allowed = {
      'display_name',
      'federation_number',
      'team_preference',
      'replicas',
    };
    final unknown = body.keys.where((k) => !allowed.contains(k)).toList()
      ..sort();
    if (unknown.isNotEmpty) throw ControllerError('unknown fields $unknown');
    final st = settings();
    final name = _text('display_name', body['display_name'], _nameMax);
    var fed = _text(
      'federation_number',
      _truthy(body['federation_number']) ? body['federation_number'] : null,
      _federationMax,
      optional: true,
    );
    if (st['federation'] == 'off') {
      fed = null;
    } else if (st['federation'] == 'required' && fed == null) {
      throw ControllerError(
        'federation_number: this field asks for the '
        '${st['federation_label']} number',
      );
    }
    final pref = body['team_preference'];
    if (pref != null) _teamId(game, pref, 'team_preference');
    final decls = _checkDeclarations(
      _truthy(body['replicas']) ? body['replicas'] : const <Object?>[],
      st,
    );
    final now = _wall();
    if (_count(gameId) >= (st['max_players']! as int)) {
      throw _forbidden('game $gameId is full (${st['max_players']} players)');
    }
    var pid = _newPlayerId();
    while (_fieldPlayers.containsKey(pid)) {
      pid = _newPlayerId();
    }
    _fieldPlayers[pid] = {
      'player_id': pid,
      'secret_sha256': null,
      'created_at': now,
      'last_seen_at': now,
    };
    _addCheckin(gameId, pid, {
      'status': 'checked_in',
      'display_name': name,
      'federation_number': fed,
      'federation_seen': fed != null,
      'team_preference': pref,
      'manual': true,
      'checked_in_at': now,
    }, now);
    _replaceDeclarations(game, pid, decls, staff: true, now: now);
    final row = _row(gameId, pid)!;
    _save();
    _emitCheckinEvent(game, row);
    _notify(gameId, pid);
    return rowView(game, row);
  }

  Map<String, Object?> patchCheckin(
    ApiViewer viewer,
    int gameId,
    String pid,
    Map<String, Object?> body,
  ) {
    final game = _staff(viewer, gameId);
    final row = _row(gameId, pid);
    if (row == null) {
      throw ControllerError.notFound('$pid is not checked in to game $gameId');
    }
    const gmFields = {'team', 'squad', 'role'};
    const marshalFields = {'status', 'federation_seen', 'replicas'};
    final unknown =
        body.keys
            .where((k) => !gmFields.contains(k) && !marshalFields.contains(k))
            .toList()
          ..sort();
    if (unknown.isNotEmpty) throw ControllerError('unknown fields $unknown');
    if (body.keys.any(gmFields.contains) && !viewer.isGmToken) {
      throw _forbidden('team, squad and role: the GM token only');
    }
    if (row['status'] == 'left' || row['status'] == 'removed') {
      throw ControllerError.conflict('this check-in is ${row['status']}');
    }
    final now = _wall();
    final fields = <String, Object?>{'updated_at': now};
    var emit = false;
    if (body.containsKey('team')) fields['team'] = _teamId(game, body['team']);
    final squads = (game['squads'] as int?) ?? 0;
    if (body.containsKey('squad')) {
      final sq = body['squad'];
      if (sq is! int || sq < 0 || sq > squads) {
        throw ControllerError(
          squads == 0
              ? 'squad: this game has no squads'
              : 'squad: 0 (none) to $squads',
        );
      }
      fields['squad'] = sq;
    }
    if (body.containsKey('role')) {
      if (!playerRoles.contains(body['role'])) {
        throw ControllerError('role: one of ${playerRoles.join(', ')}');
      }
      if (body['role'] == 'squad_leader' && squads == 0) {
        throw ControllerError(
          'role: this game has no squads, so no squad leaders',
        );
      }
      fields['role'] = body['role'];
    }
    if (_truthy(fields['squad'] ?? row['squad']) &&
        !_truthy(fields['team'] ?? row['team'])) {
      throw ControllerError(
        'squad: a squad is inside a team; give the team first',
      );
    }
    final assignment = [
      'team',
      'squad',
      'role',
    ].any((k) => fields.containsKey(k) && fields[k] != row[k]);
    if (body.containsKey('status')) {
      if (body['status'] != 'checked_in') {
        throw ControllerError(
          'status: only "checked_in" (confirm); remove with DELETE',
        );
      }
      if (row['status'] == 'pending' || row['status'] == 'expected') {
        fields['status'] = 'checked_in';
        fields['checked_in_at'] = now;
        emit = true;
      }
    }
    if (body.containsKey('federation_seen')) {
      if (body['federation_seen'] is! bool) {
        throw ControllerError('federation_seen: true or false');
      }
      fields['federation_seen'] = body['federation_seen'];
    }
    if (body.containsKey('replicas')) {
      final decls = _checkDeclarations(body['replicas'], settings());
      _replaceDeclarations(game, pid, decls, staff: true, now: now);
    }
    _update(gameId, pid, fields);
    _save();
    final after = _row(gameId, pid)!;
    if (emit) _emitCheckinEvent(game, after);
    _notify(gameId, pid, assignment: assignment);
    return rowView(game, after);
  }

  Map<String, Object?> removeCheckin(ApiViewer viewer, int gameId, String pid) {
    final game = _staff(viewer, gameId);
    if (!viewer.isGmToken) {
      throw _forbidden('removing a check-in: the GM token only');
    }
    if (_row(gameId, pid) == null) {
      throw ControllerError.notFound('$pid is not checked in to game $gameId');
    }
    _eraseRow(gameId, pid, 'removed', _wall());
    _save();
    _notify(gameId, pid, assignment: true);
    return {'game_id': game['id'], 'player_id': pid, 'status': 'removed'};
  }

  /// POST /api/v1/games/{id}/checkins/ticket: a marshal scans a registered
  /// player's printed ticket. Without a roster from a site server (slice
  /// S7) no registration is on the list, so this is 404, as on a Pi
  /// without one.
  Map<String, Object?> ticketCheckin(
    ApiViewer viewer,
    int gameId,
    Map<String, Object?> body,
  ) {
    final game = _staff(viewer, gameId);
    if (game['state'] == 'ended') {
      throw ControllerError.conflict('the game has ended');
    }
    final unknown = body.keys.where((k) => k != 'ticket').toList()..sort();
    if (unknown.isNotEmpty) throw ControllerError('unknown fields $unknown');
    final CheckinTicket ticket;
    try {
      final text = body['ticket'];
      if (text is! String) {
        throw TicketException(TicketFailure.text, 'a ticket text is a string');
      }
      ticket = parseTicket(text);
    } on TicketException catch (e) {
      throw ControllerError('ticket: ${e.message}');
    }
    final digest = _hex(sha256.convert(ticket.secret).bytes);
    final now = _wall();
    var row = _byRegistration(gameId, ticket.registrationId);
    if (row == null || row['from_roster'] != true) {
      throw ControllerError.notFound(
        "this ticket's registration is not on this game's roster",
      );
    }
    final want = row['ticket_sha256'] as String?;
    if (row['player_id'] != ticket.playerId ||
        want == null ||
        want.isEmpty ||
        !constantTimeEquals(utf8.encode(want), utf8.encode(digest))) {
      throw _forbidden(
        "this ticket is not this registration's (was a newer one made?)",
      );
    }
    if (row['status'] == 'removed') {
      throw _forbidden('staff removed this check-in');
    }
    final pid = row['player_id']! as String;
    final emit = row['status'] == 'expected';
    if (emit) {
      final st = settings();
      if (_count(gameId) >= (st['max_players']! as int)) {
        throw _forbidden('game $gameId is full (${st['max_players']} players)');
      }
      _update(gameId, pid, {
        'status': 'checked_in',
        'checked_in_at': now,
        'updated_at': now,
      });
      _save();
    }
    row = _row(gameId, pid)!;
    if (emit) _emitCheckinEvent(game, row);
    _notify(gameId, pid);
    return rowView(game, row);
  }

  /// GET /api/v1/games/{id}/checkins.csv (the GM token): one line per
  /// declaration, as the Pi writes it.
  String csvExport(int gameId) {
    final game = engine.getGame(gameId);
    final out = StringBuffer();
    void line(List<Object?> cells) {
      out.write(cells.map(_csvCell).join(','));
      out.write('\r\n');
    }

    line([
      'player_id',
      'display_name',
      'status',
      'team',
      'squad',
      'role',
      'federation_number',
      'card_seen',
      'manual',
      'checked_in_at',
      'declaration_id',
      'replica_id',
      'type',
      'class',
      'make_model',
      'chrono',
    ]);
    for (final r in _rows(gameId)) {
      final base = [
        r['player_id'],
        _csvSafe(r['display_name'] as String?),
        r['status'],
        _teamName(game, r['team']! as int) ?? '',
        _truthy(r['squad']) ? r['squad'] : '',
        r['role'],
        _csvSafe(r['federation_number'] as String?),
        r['federation_seen'] == true ? 'yes' : '',
        r['manual'] == true ? 'yes' : '',
        _iso(r['checked_in_at'] as num?),
      ];
      final decls = _decls(gameId, r['player_id']! as String);
      if (decls.isEmpty) {
        line([...base, '', '', '', '', '', '']);
      }
      for (final d in decls) {
        line([
          ...base,
          d['declaration_id'],
          d['replica_id'] ?? '',
          d['type'],
          d['class'],
          _csvSafe(d['make_model'] as String?),
          d['state'],
        ]);
      }
    }
    return out.toString();
  }

  // --- the "replicas to chrono" list ------------------------------------------------

  bool _refusedToday(Map<String, Object?> d) {
    final rid = d['replica_id'];
    if (d['state'] != 'pending' || rid is! String || rid.isEmpty) return false;
    final today = localDay(_wall());
    for (final r in _readingsOf(
      replicaId: rid,
      playerId: d['player_id']! as String,
    )) {
      if (r['type'] != 'spotcheck' &&
          r['outcome'] == 'fail' &&
          _readingDay(r) == today) {
        return true;
      }
    }
    return false;
  }

  (int, int, int) _readingDay(Map<String, Object?> r) => localDay(
    parseTimestamp(r['timestamp']! as String)!.millisecondsSinceEpoch / 1000,
  );

  /// The newest series by when it arrived (the first of equals, as Python's
  /// max).
  static List<Map<String, Object?>> _latestSeries(
    Map<String, List<Map<String, Object?>>> series,
  ) {
    List<Map<String, Object?>>? best;
    double? bestAt;
    for (final rs in series.values) {
      final at = rs
          .map((x) => (x['received_at']! as num).toDouble())
          .reduce(max);
      if (bestAt == null || at > bestAt) {
        best = rs;
        bestAt = at;
      }
    }
    return best!;
  }

  static double _energy(Map<String, Object?> r) =>
      ((r['record']! as Map)['energy_j']! as num).toDouble();

  /// The reading with the highest energy (then the highest reading id).
  static Map<String, Object?> _highest(List<Map<String, Object?>> rs) =>
      rs.reduce((a, b) {
        final c = _energy(a).compareTo(_energy(b));
        if (c != 0) return c > 0 ? a : b;
        return (a['reading_id']! as String).compareTo(
                  b['reading_id']! as String,
                ) >=
                0
            ? a
            : b;
      });

  /// With chrono_valid_for = "day": the deciding reading of a passing
  /// check-in series for this replica earlier on the field's day (in any
  /// game), if its latest series passed.
  String? _passedEarlier(String replicaId, String pid, double now) {
    if (settings()['chrono_valid_for'] != 'day') return null;
    final today = localDay(now);
    final series = <String, List<Map<String, Object?>>>{};
    for (final r in _readingsOf(replicaId: replicaId, playerId: pid)) {
      if (r['type'] != 'spotcheck' &&
          (r['outcome'] == 'pass' || r['outcome'] == 'fail') &&
          _readingDay(r) == today) {
        series.putIfAbsent(r['series_id']! as String, () => []).add(r);
      }
    }
    if (series.isEmpty) return null;
    final latest = _latestSeries(series);
    if (latest.first['outcome'] != 'pass') return null;
    return _highest(latest)['reading_id']! as String;
  }

  Map<String, Object?> chronoList(ApiViewer viewer, int gameId) =>
      _chronoList(_staff(viewer, gameId));

  Map<String, Object?> _chronoList(Map<String, Object?> game) {
    final gid = game['id']! as int;
    final players = <Map<String, Object?>>[];
    final counts = <String, int>{};
    for (final r in _rows(gid)) {
      if (r['status'] == 'left' || r['status'] == 'removed') continue;
      final decls = [
        for (final d in _decls(gid, r['player_id']! as String))
          if (d['state'] != 'withdrawn') _declView(d, _refusedToday(d)),
      ];
      for (final d in decls) {
        counts[d['state']! as String] = (counts[d['state']] ?? 0) + 1;
      }
      if (decls.isEmpty) continue;
      players.add({
        'player_id': r['player_id'],
        'display_name': r['display_name'],
        'status': r['status'],
        'team': _teamName(game, r['team']! as int),
        'squad': r['squad'],
        'seq': r['seq'],
        'pending': decls.where((d) => d['state'] == 'pending').length,
        'declarations': decls,
      });
    }
    // Stable, as Python's sort: players with pending declarations first.
    final waiting = [
      for (final p in players)
        if (p['pending'] != 0) p,
    ];
    final done = [
      for (final p in players)
        if (p['pending'] == 0) p,
    ];
    int bySeq(Map<String, Object?> a, Map<String, Object?> b) =>
        (a['seq']! as int).compareTo(b['seq']! as int);
    return {
      'game_id': gid,
      'squads': (game['squads'] as int?) ?? 0,
      'counts': {
        for (final s in ['pending', 'passed', 'refused']) s: counts[s] ?? 0,
      },
      'chrono_valid_for': settings()['chrono_valid_for'],
      'players': [...(waiting..sort(bySeq)), ...(done..sort(bySeq))],
    };
  }

  /// Pending declarations of the players at the field (not of registered
  /// players who never came): Start's warning (ADR-P3-13).
  int pendingCount(int gameId) {
    final game = engine.store.game(gameId);
    if (game == null) return 0;
    var n = 0;
    for (final p
        in (_chronoList(game)['players']! as List)
            .cast<Map<String, Object?>>()) {
      if (p['status'] != 'expected') n += p['pending']! as int;
    }
    return n;
  }

  // --- marshals and readings ------------------------------------------------------

  static Uint8List _publicKey(Object? value) {
    const why = 'public_key: the Ed25519 public key, 32 bytes in base64 or hex';
    if (value is! String) throw ControllerError(why);
    Uint8List? raw;
    if (_hex64.hasMatch(value)) {
      raw = _unhex(value.toLowerCase());
    } else if (_base64Re.hasMatch(value) && value.length % 4 == 0) {
      try {
        raw = base64.decode(value);
      } on FormatException {
        raw = null;
      }
    }
    if (raw == null || raw.length != 32) throw ControllerError(why);
    return raw;
  }

  // The GM's marshal list (decisions MR-1 to MR-14, the Pi's `add_marshal` and the rest): a marshal
  // exists only on it. The GM adds a checked-in player (the id, M-01, M-02..., is made here), the
  // player's phone learns its id from GET /api/v1/checkin/me and registers its key for that id only.

  Map<String, Object?> _marshalView(Map<String, Object?> e) {
    final key = _marshals[e['marshal_id']];
    return {
      'marshal_id': e['marshal_id'],
      'name': e['name'],
      'player_id': e['player_id'],
      'public_key': key?['public_key'],
      'key_registered': key != null,
      'registered_at': key?['registered_at'],
      'created_at': e['created_at'],
    };
  }

  Map<String, Object?>? _rosterOf(String? pid) {
    if (pid == null) return null;
    for (final k in _roster.keys.toList()..sort()) {
      if (_roster[k]!['player_id'] == pid) return _roster[k];
    }
    return null;
  }

  /// A player added to the list is a marshal in every check-in that still
  /// counts; one taken off it is a player again (MR-9). A gm-role player
  /// keeps their role.
  void _followRole(String pid, String to) {
    final now = _wall();
    final rows = [
      for (final r in _checkins)
        if (r['player_id'] == pid &&
            const ['expected', 'pending', 'checked_in'].contains(r['status']))
          r,
    ]..sort((a, b) => (a['game_id']! as int).compareTo(b['game_id']! as int));
    for (final row in rows) {
      final role = row['role'];
      if (to == 'marshal' && (role == 'marshal' || role == 'gm')) continue;
      if (to != 'marshal' && role != 'marshal') continue;
      row['role'] = to;
      row['updated_at'] = now;
      _notify(row['game_id']! as int, pid, assignment: true);
    }
  }

  String _freeMarshalId() {
    var n = 1;
    while (_roster.containsKey('M-${n.toString().padLeft(2, '0')}')) {
      n++;
    }
    return 'M-${n.toString().padLeft(2, '0')}';
  }

  String? _nameOf(String pid) {
    final rows = [
      for (final r in _checkins)
        if (r['player_id'] == pid &&
            const ['expected', 'pending', 'checked_in'].contains(r['status']))
          r,
    ]..sort((a, b) => (a['game_id']! as int).compareTo(b['game_id']! as int));
    for (final r in rows.reversed) {
      final n = r['display_name'];
      if (n is String && n.isNotEmpty) return n;
    }
    return null;
  }

  String _checkPlayer(Object? pid) {
    if (pid is! String || !_playerIdRe.hasMatch(pid)) {
      throw ControllerError("player_id: a player's field id (p-...)");
    }
    if (_fieldPlayers[pid] == null) {
      throw ControllerError.notFound('$pid has not checked in here');
    }
    return pid;
  }

  /// store.py `put_marshal`: a different key replaces the current one (which
  /// goes to the history); a key taken back after a removal is the same
  /// period again, not a second row.
  void _putKey(String mid, String name, String b64, String? pid, double now) {
    final old = _marshals[mid];
    final same = old != null && old['public_key'] == b64;
    if (old != null && !same) {
      _marshalHistory.add({
        'marshal_id': mid,
        'name': old['name'],
        'public_key': old['public_key'],
        'player_id': old['player_id'],
        'registered_at': old['registered_at'],
        'replaced_at': now,
      });
    }
    num at = same ? old['registered_at']! as num : now;
    if (!same) {
      final back = [
        for (final h in _marshalHistory)
          if (h['marshal_id'] == mid && h['public_key'] == b64)
            h['registered_at']! as num,
      ];
      if (back.isNotEmpty) {
        at = back.reduce((a, b) => a < b ? a : b);
        _marshalHistory.removeWhere(
          (h) => h['marshal_id'] == mid && h['public_key'] == b64,
        );
      }
    }
    _marshals[mid] = {
      'marshal_id': mid,
      'name': name,
      'public_key': b64,
      'player_id': pid,
      'registered_at': at,
    };
  }

  /// store.py `retire_marshal`: the key leaves for the history, so what it
  /// signed before still verifies on the site server (MR-8).
  void _retire(String mid, double now) {
    final old = _marshals.remove(mid);
    if (old != null) {
      _marshalHistory.add({
        'marshal_id': mid,
        'name': old['name'],
        'public_key': old['public_key'],
        'player_id': old['player_id'],
        'registered_at': old['registered_at'],
        'replaced_at': now,
      });
    }
    _roster.remove(mid);
  }

  void _retireKeyOnly(String mid, double now) {
    final entry = _roster[mid];
    _retire(mid, now);
    if (entry != null) _roster[mid] = entry;
  }

  /// POST /api/v1/marshals (GM): adds a marshal to the list, or changes the
  /// id's name, player or key.
  Map<String, Object?> addMarshal(Map<String, Object?> body) {
    const allowed = {'marshal_id', 'name', 'public_key', 'player_id'};
    final unknown = body.keys.where((k) => !allowed.contains(k)).toList()
      ..sort();
    if (unknown.isNotEmpty) throw ControllerError('unknown fields $unknown');
    var mid = body['marshal_id'];
    if (mid != null && (mid is! String || !_marshalIdRe.hasMatch(mid))) {
      throw ControllerError('marshal_id: 1-64 of A-Z a-z 0-9 . _ : -');
    }
    final key = body['public_key'] != null
        ? base64.encode(_publicKey(body['public_key']))
        : null;
    final pid = body['player_id'] != null
        ? _checkPlayer(body['player_id'])
        : null;
    var before = mid == null ? null : _roster['$mid'];
    final given =
        body['name'] ??
        (before != null ? before['name'] : (pid != null ? _nameOf(pid) : null));
    final name = _text('name', given, 64)!;
    if (pid != null) {
      final other = _rosterOf(pid);
      if (other != null && mid != null && other['marshal_id'] != mid) {
        throw ControllerError.conflict(
          '$pid is already marshal ${other['marshal_id']}',
        );
      }
      if (other != null && mid == null) {
        mid = other['marshal_id'];
        before = other;
      }
    }
    final id = (mid ?? _freeMarshalId()) as String;
    final now = _wall();
    _roster[id] = {
      'marshal_id': id,
      'name': name,
      'player_id': pid,
      'created_at': _roster[id]?['created_at'] ?? now,
    };
    if (before != null && before['player_id'] != pid) {
      _retireKeyOnly(id, now); // another phone's key does not carry over (MR-6)
      if (before['player_id'] != null) {
        _followRole(before['player_id']! as String, 'player');
      }
    }
    if (key != null) {
      _putKey(id, name, key, pid, now);
    } else if (_marshals[id] != null) {
      _putKey(id, name, _marshals[id]!['public_key']! as String, pid, now);
    }
    if (pid != null) _followRole(pid, 'marshal');
    _save();
    return _marshalView(_roster[id]!);
  }

  /// PATCH /api/v1/marshals/{id} (GM): the name, or the player the id is
  /// bound to (null unbinds).
  Map<String, Object?> patchMarshal(String mid, Map<String, Object?> body) {
    const allowed = {'name', 'player_id'};
    final unknown = body.keys.where((k) => !allowed.contains(k)).toList()
      ..sort();
    if (unknown.isNotEmpty) throw ControllerError('unknown fields $unknown');
    final entry = _roster[mid];
    if (entry == null) {
      throw ControllerError.notFound('$mid is not on the marshal list');
    }
    final name = body.containsKey('name')
        ? _text('name', body['name'], 64)!
        : entry['name']! as String;
    var pid = entry['player_id'] as String?;
    if (body.containsKey('player_id')) {
      pid = body['player_id'] != null ? _checkPlayer(body['player_id']) : null;
      final other = _rosterOf(pid);
      if (other != null && other['marshal_id'] != mid) {
        throw ControllerError.conflict(
          '$pid is already marshal ${other['marshal_id']}',
        );
      }
    }
    final now = _wall();
    _roster[mid] = {...entry, 'name': name, 'player_id': pid};
    if (pid != entry['player_id']) {
      _retireKeyOnly(mid, now); // the new phone registers its own key (MR-6)
      if (entry['player_id'] != null) {
        _followRole(entry['player_id']! as String, 'player');
      }
      if (pid != null) _followRole(pid, 'marshal');
    } else if (_marshals[mid] != null) {
      _putKey(mid, name, _marshals[mid]!['public_key']! as String, pid, now);
    }
    _save();
    return _marshalView(_roster[mid]!);
  }

  /// DELETE /api/v1/marshals/{id} (GM): the marshal is revoked at once
  /// (MR-8, MR-9).
  Map<String, Object?> removeMarshal(String mid) {
    final entry = _roster[mid];
    if (entry == null) {
      throw ControllerError.notFound('$mid is not on the marshal list');
    }
    _retire(mid, _wall());
    if (entry['player_id'] != null) {
      _followRole(entry['player_id']! as String, 'player');
    }
    _save();
    return {'marshal_id': mid, 'removed': true};
  }

  /// What GET /api/v1/checkin/me says to a marshal's phone (MR-2): the id
  /// the GM gave this player and the key held for it, or null when the
  /// player is not on the list.
  Map<String, Object?>? myMarshal(ApiViewer viewer) {
    final entry = _rosterOf(viewer.playerId);
    if (entry == null) return null;
    final v = _marshalView(entry);
    return {
      'marshal_id': v['marshal_id'],
      'name': v['name'],
      'public_key': v['public_key'],
      'valid_for_s': marshalValidForSeconds,
    };
  }

  /// PUT /api/v1/checkin/me/marshal-key: the marshal's phone registers the
  /// key that signs its readings, for the id the GM's list gave this player
  /// (MR-2, MR-5).
  Map<String, Object?> registerMyKey(
    ApiViewer viewer,
    Map<String, Object?> body,
  ) {
    const allowed = {'marshal_id', 'name', 'public_key'};
    final unknown = body.keys.where((k) => !allowed.contains(k)).toList()
      ..sort();
    if (unknown.isNotEmpty) throw ControllerError('unknown fields $unknown');
    final entry = _rosterOf(viewer.playerId);
    if (entry == null) {
      throw _forbidden(
        "you are not on the field's marshal list: ask the GM to add you as a marshal",
      );
    }
    final mid = body['marshal_id'];
    if (mid != null && mid != entry['marshal_id']) {
      throw ControllerError.conflict(
        'your marshal id is ${entry['marshal_id']}, not $mid',
      );
    }
    final b64 = base64.encode(_publicKey(body['public_key']));
    _putKey(
      entry['marshal_id']! as String,
      entry['name']! as String,
      b64,
      viewer.playerId,
      _wall(),
    );
    _save();
    return {
      'marshal_id': entry['marshal_id'],
      'name': entry['name'],
      'public_key': b64,
      'player_id': viewer.playerId,
    };
  }

  List<Map<String, Object?>> marshals() => [
    for (final k in _roster.keys.toList()..sort()) _marshalView(_roster[k]!),
  ];

  /// POST /api/v1/chrono/readings: one series of signed readings
  /// (protocol/checkin.md). Asynchronous: Ed25519 runs on the
  /// `cryptography` package's futures; everything after the checks runs at
  /// once, as one step.
  Future<Map<String, Object?>> uploadReadings(
    ApiViewer viewer,
    Map<String, Object?> body,
  ) async {
    if (!(viewer.isGmToken ||
        (viewer.kind == 'player' && staffRoles.contains(viewer.role)))) {
      throw _forbidden("chrono readings come from a marshal's token");
    }
    const allowed = {'readings', 'declaration_id', 'replica'};
    final unknown = body.keys.where((k) => !allowed.contains(k)).toList()
      ..sort();
    if (unknown.isNotEmpty) throw ControllerError('unknown fields $unknown');
    final items = body['readings'];
    if (items is! List || items.isEmpty || items.length > _seriesMax) {
      throw ControllerError(
        'readings: 1 to $_seriesMax signed records of one series',
      );
    }
    final reasons = <Map<String, Object?>>[];
    final checked = <(Map<String, Object?>, ChronoReading)>[];
    for (var i = 0; i < items.length; i++) {
      final rec = items[i];
      try {
        final ChronoReading reading;
        try {
          reading = ChronoReading.fromJson(rec);
        } on ChronoFormatException catch (e) {
          throw ChronoVerifyException(ChronoFailure.format, e.message);
        }
        final m = _marshals[reading.marshalId];
        if (reading.signature == null) {
          throw ChronoVerifyException(
            ChronoFailure.unsigned,
            'the record has no signature',
          );
        }
        if (m == null) throw _MarshalUnknown(reading.marshalId);
        await verifyReading(reading, base64.decode(m['public_key']! as String));
        if (reading.fieldId != config.fieldId) {
          throw _WrongField(reading.fieldId);
        }
        checked.add(((rec! as Map).cast<String, Object?>(), reading));
      } on ChronoVerifyException catch (e) {
        reasons.add(_reason(i, rec, e.reason.name, e.message));
      } on _MarshalUnknown catch (e) {
        reasons.add(
          _reason(
            i,
            rec,
            'marshal',
            "marshal ${e.id} is not on this field's marshal list "
                '(never added, or removed by the GM)',
          ),
        );
      } on _WrongField catch (e) {
        reasons.add(
          _reason(i, rec, 'field', 'the record is for field ${e.id}'),
        );
      }
    }
    if (reasons.isNotEmpty) {
      throw ControllerError(
        'readings refused: nothing was stored',
        status: 422,
        extra: {'reasons': reasons},
      );
    }
    final first = checked.first.$2;
    for (final (_, f) in checked) {
      if (f.replicaId != first.replicaId ||
          f.playerId != first.playerId ||
          f.type != first.type) {
        throw ControllerError(
          'one series per request: the same replica, player and type',
        );
      }
    }
    final ids = [for (final (_, f) in checked) f.readingId];
    if (ids.toSet().length != ids.length) {
      throw ControllerError('each reading once');
    }
    final game = _readingGame(first);
    final stored = _readingsOf(ids: ids);
    if (stored.isNotEmpty) {
      if (stored.length == ids.length) {
        // A resend: nothing changes.
        final out = <String, Object?>{
          'series_id': stored.first['series_id'],
          'outcome': stored.first['outcome'],
          'duplicate': true,
          'stored': 0,
        };
        if (game != null) {
          out['declarations'] = _declViews(game['id']! as int, first.playerId);
        }
        return out;
      }
      throw ControllerError.conflict(
        'some of these readings were stored with another series',
      );
    }
    _link(first, body, game);
    final rclass = _classFor(first, game);
    final judged = _judge(
      first.type,
      [for (final (_, f) in checked) f],
      rclass,
      first,
    );
    final seriesId = newUuid(_random);
    final now = _wall();
    for (final (rec, f) in checked) {
      _readings.add({
        'reading_id': f.readingId,
        'replica_id': f.replicaId,
        'player_id': f.playerId,
        'marshal_id': f.marshalId,
        'type': f.type.name,
        'game_id': f.gameId,
        'timestamp': f.timestamp,
        'record': rec,
        'series_id': seriesId,
        'outcome': judged.outcome,
        'received_at': now,
      });
    }
    var changed = <String>[];
    if (game != null &&
        first.type != ReadingType.spotcheck &&
        (judged.outcome == 'pass' || judged.outcome == 'fail')) {
      changed = _apply(game, first, judged, now);
    }
    _save();
    _chronoEvents(game, first, judged);
    if (game != null) _notify(game['id']! as int, first.playerId);
    final out = <String, Object?>{
      'series_id': seriesId,
      'outcome': judged.outcome,
      'stored': checked.length,
      'highest_energy_j': judged.highest.energyJ,
      'limit_j': judged.limitJ,
      'class': rclass,
      'duplicate': false,
      'changed': changed,
    };
    if (game != null) {
      out['declarations'] = _declViews(game['id']! as int, first.playerId);
    }
    return out;
  }

  static Map<String, Object?> _reason(
    int i,
    Object? rec,
    String reason,
    String detail,
  ) => {
    'index': i,
    'reading_id': rec is Map ? rec['reading_id'] : null,
    'reason': reason,
    'detail': detail,
  };

  Map<String, Object?>? _readingGame(ChronoReading f) {
    final gid = f.gameId;
    if (gid != null) {
      if (!RegExp(r'^[0-9]+$').hasMatch(gid)) return null;
      return engine.store.game(int.parse(gid));
    }
    final live = engine.liveGame;
    return live == null ? null : engine.store.game(live['id']! as int);
  }

  /// Registers the replica (if sent) and links a declaration that had no
  /// replica id yet.
  void _link(
    ChronoReading f,
    Map<String, Object?> body,
    Map<String, Object?>? game,
  ) {
    final rep = body['replica'];
    if (rep != null) {
      if (rep is! Map ||
          rep['replica_id'] != f.replicaId ||
          rep['owner_player_id'] != f.playerId) {
        throw ControllerError(
          "replica: the registry record of the readings' replica and player",
        );
      }
      final rc = rep['class'];
      if (rc is! String ||
          !_classRe.hasMatch(rc) ||
          !replicaTypes.contains(rep['type'])) {
        throw ControllerError('replica: a type and a class are required');
      }
      _replicas[f.replicaId] = {
        for (final k in [
          'replica_id',
          'owner_player_id',
          'type',
          'class',
          'make_model',
          'registered_at',
          'tag_type',
          'tag_uid',
        ])
          if (rep.containsKey(k)) k: rep[k],
      };
    }
    final did = body['declaration_id'];
    if (did == null) return;
    final d = did is String ? _declarations[did] : null;
    if (d == null) throw ControllerError.notFound('no such declaration');
    if (d['player_id'] != f.playerId ||
        (game != null && d['game_id'] != game['id'])) {
      throw ControllerError.conflict(
        "that declaration is another player's or another game's",
      );
    }
    if (d['replica_id'] != null && d['replica_id'] != f.replicaId) {
      throw ControllerError.conflict('that declaration is for another replica');
    }
    if (d['replica_id'] == null) {
      _putDeclaration({...d, 'replica_id': f.replicaId}, _wall());
    }
  }

  String? _classFor(ChronoReading f, Map<String, Object?>? game) {
    if (game != null) {
      for (final d in _decls(game['id']! as int, f.playerId)) {
        if (d['replica_id'] == f.replicaId && d['state'] != 'withdrawn') {
          return d['class'] as String?;
        }
      }
    }
    final rep = _replicas[f.replicaId];
    if (rep != null) return rep['class'] as String?;
    final byReplica =
        [
          for (final d in _declarations.values)
            if (d['replica_id'] == f.replicaId && d['player_id'] == f.playerId)
              d,
        ]..sort(
          (a, b) =>
              (a['created_at']! as num).compareTo(b['created_at']! as num),
        );
    return byReplica.isEmpty ? null : byReplica.last['class'] as String?;
  }

  /// ADR-P3-7 and decision B11: the series' highest energy against the class
  /// limit; a spot check also against the replica's last passing check-in
  /// plus the tolerance.
  _Judged _judge(
    ReadingType type,
    List<ChronoReading> fields,
    String? rclass,
    ChronoReading first,
  ) {
    final highest = fields.reduce((a, b) {
      final c = a.energyJ.compareTo(b.energyJ);
      if (c != 0) return c > 0 ? a : b;
      return a.readingId.compareTo(b.readingId) >= 0 ? a : b;
    });
    final limit = rclass == null ? null : limits.classes[rclass];
    final out = _Judged(highest, limit?.maxEnergyJ);
    if (limit == null) {
      out.outcome = 'unjudged'; // no class known: stored, the list stays
      return out;
    }
    if (type != ReadingType.spotcheck) {
      out.outcome = highest.energyJ <= limit.maxEnergyJ ? 'pass' : 'fail';
      return out;
    }
    const tol = 5.0;
    out.tolerancePct = tol;
    final last = _lastPass(first.replicaId, first.playerId);
    out.checkinJ = last;
    if (highest.energyJ > limit.maxEnergyJ) {
      out.outcome = 'fail';
    } else if (last != null && highest.energyJ > last * (1 + tol / 100)) {
      out.outcome = 'warn';
    } else {
      out.outcome = 'pass';
    }
    return out;
  }

  double? _lastPass(String replicaId, String pid) {
    final series = <String, List<Map<String, Object?>>>{};
    for (final r in _readingsOf(replicaId: replicaId, playerId: pid)) {
      if (r['type'] != 'spotcheck' && r['outcome'] == 'pass') {
        series.putIfAbsent(r['series_id']! as String, () => []).add(r);
      }
    }
    if (series.isEmpty) return null;
    return _latestSeries(series).map(_energy).reduce(max);
  }

  List<String> _apply(
    Map<String, Object?> game,
    ChronoReading f,
    _Judged judged,
    double now,
  ) {
    final state = judged.outcome == 'pass' ? 'passed' : 'refused';
    final changed = <String>[];
    for (final d in _decls(game['id']! as int, f.playerId)) {
      if (d['replica_id'] == f.replicaId && d['state'] != 'withdrawn') {
        _putDeclaration({
          ...d,
          'state': state,
          'reading_id': judged.highest.readingId,
        }, now);
        changed.add(d['declaration_id']! as String);
      }
    }
    return changed;
  }

  /// chrono.checkin once per passing series; spot checks: chrono.spotcheck,
  /// and chrono.violation on WARN or FAIL. A refusal adds no event (it is in
  /// the list).
  void _chronoEvents(
    Map<String, Object?>? game,
    ChronoReading f,
    _Judged judged,
  ) {
    if (game == null) return;
    final gid = game['id']! as int;
    final h = judged.highest;
    final base = <String, Object?>{
      'replica': f.replicaId,
      'player': f.playerId,
      'reading_mps': h.velocityMps,
      'bb_g': h.bbWeightG,
    };
    if (f.type != ReadingType.spotcheck) {
      if (judged.outcome == 'pass') {
        engine.logControllerEvent(gid, 'chrono.checkin', base);
      }
      return;
    }
    if (['pass', 'warn', 'fail'].contains(judged.outcome)) {
      engine.logControllerEvent(gid, 'chrono.spotcheck', {
        ...base,
        'tolerance_pct': judged.tolerancePct,
      });
    }
    if (judged.outcome == 'warn' || judged.outcome == 'fail') {
      engine.logControllerEvent(gid, 'chrono.violation', {
        'replica': f.replicaId,
        'reading_mps': h.velocityMps,
        'bb_g': h.bbWeightG,
        'limit_j': judged.limitJ,
      }, prio: 'critical');
    }
  }

  List<Object?> playerReadings(String pid) => [
    for (final r in _readingsOf(playerId: pid)) r['record'],
  ];

  int deletePlayerReadings(String pid) {
    final n = _deleteReadings(playerId: pid);
    _save();
    return n;
  }

  Map<String, Object?> erasePlayer(String pid, {bool chronoToo = false}) {
    final games = {
      for (final r in _checkins)
        if (r['player_id'] == pid) r['game_id'],
    };
    _erasePlayerRecords(pid);
    final readings = chronoToo ? _deleteReadings(playerId: pid) : 0;
    _save();
    for (final gid in games) {
      engine.emit({
        'type': 'checkin',
        'game': gid,
        'player_id': pid,
        'erased': true,
        '_staff': true,
      });
    }
    return {'player_id': pid, 'erased': true, 'readings_deleted': readings};
  }

  // --- the site sync (slice S7, controller_sync.dart) -----------------------

  /// The field identity [pid] as the sync's claims need it: its secret's
  /// SHA-256 (hex), null for one made for a hand check-in; null when this
  /// controller never saw the id (store.py `field_player`).
  ({String? secretSha256})? fieldPlayer(String pid) {
    final p = _fieldPlayers[pid];
    if (p == null) return null;
    return (secretSha256: p['secret_sha256'] as String?);
  }

  /// Every earlier key of every marshal, oldest first (store.py
  /// `marshal_key_history`, schema 6).
  List<Map<String, Object?>> marshalKeyHistory() {
    final out = [for (final h in _marshalHistory) Map.of(h)]
      ..sort((a, b) {
        final c = (a['replaced_at']! as num).compareTo(
          b['replaced_at']! as num,
        );
        return c != 0
            ? c
            : (a['marshal_id']! as String).compareTo(
                b['marshal_id']! as String,
              );
      });
    return out;
  }

  /// The replica registry, by when each was registered (store.py
  /// `replicas`).
  List<Map<String, Object?>> replicaRegistry() {
    final out = [for (final r in _replicas.values) Map.of(r)]
      ..sort((a, b) {
        final ra = '${a['registered_at'] ?? ''}',
            rb = '${b['registered_at'] ?? ''}';
        final c = ra.compareTo(rb);
        return c != 0
            ? c
            : (a['replica_id']! as String).compareTo(
                b['replica_id']! as String,
              );
      });
    return out;
  }

  /// The stored readings in the order they arrived, with their record's
  /// text (store.py `readings_unsynced` without the sync's marks).
  List<Map<String, Object?>> storedReadings() => [
    for (final r in _readings)
      {
        'reading_id': r['reading_id'],
        // The phone keeps the signed record as JSON data; its text is that
        // data written again (the site server verifies the fields and the
        // signature, not the text's spacing).
        'record_json': r['record'] is String
            ? r['record']
            : jsonEncode(r['record']),
        'series_id': r['series_id'],
        'outcome': r['outcome'],
        'received_at': r['received_at'],
        'game_id': r['game_id'],
      },
  ];

  /// A roster pulled from the site server (checked by
  /// controller_sync_format.dart's `checkRoster`) becomes this game's
  /// expected check-ins until the game starts (ADR-P4-11; checkin.py
  /// `apply_roster`): new registrations are added with their declarations
  /// `pending`, an expected one takes the roster's latest data, a cancelled
  /// one that has not arrived goes, and anyone already at the field stays as
  /// the controller has them. A declaration this field's check-in would
  /// refuse is dropped and counted.
  Map<String, Object?> applyRoster(int gameId, Map<String, Object?> roster) {
    final out = <String, Object?>{
      'added': 0,
      'updated': 0,
      'removed': 0,
      'kept': 0,
      'conflicts': 0,
      'dropped_declarations': 0,
      'frozen': false,
    };
    void inc(String k) => out[k] = (out[k]! as int) + 1;
    final game = engine.store.game(gameId);
    if (game == null || game['state'] != 'ready') {
      out['frozen'] = true; // started (or gone): the controller's list rules
      return out;
    }
    final st = settings();
    final now = _wall();
    final listed = <Object?>{};
    final teams = (game['teams']! as List).cast<String>();
    for (final reg
        in (roster['registrations']! as List).cast<Map<String, Object?>>()) {
      final pid = reg['player_id']! as String;
      final rid = reg['registration_id']! as String;
      listed.add(rid);
      final byReg = _byRegistration(gameId, rid);
      final row = _row(gameId, pid);
      if ((byReg != null && byReg['player_id'] != pid) ||
          (row != null &&
              row['registration_id'] != null &&
              row['registration_id'] != rid)) {
        inc('conflicts');
        continue;
      }
      final String name;
      try {
        name = _text('display_name', reg['display_name'], _nameMax)!;
      } on ControllerError {
        inc('conflicts');
        continue;
      }
      final fed = st['federation'] != 'off' ? reg['federation_number'] : null;
      final pref = teams.contains(reg['team_preference'])
          ? reg['team_preference']
          : null;
      final decls = _rosterDeclarations(
        gameId,
        pid,
        (reg['replicas']! as List).cast<Object?>(),
        st,
        out,
      );
      final fields = <String, Object?>{
        'display_name': name,
        'federation_number': fed,
        'team_preference': pref,
        'registration_id': rid,
        'ticket_sha256': reg['ticket_sha256'],
        'from_roster': true,
      };
      if (row == null) {
        _addCheckin(gameId, pid, {'status': 'expected', ...fields}, now);
        _replaceDeclarations(game, pid, decls, staff: true, now: now);
        inc('added');
      } else if (row['status'] == 'expected') {
        _update(gameId, pid, {...fields, 'updated_at': now});
        _replaceDeclarations(game, pid, decls, staff: true, now: now);
        inc('updated');
      } else {
        if (row['registration_id'] == null) {
          // A walk-in who turns out to be registered.
          _update(gameId, pid, {
            'registration_id': rid,
            'from_roster': true,
            'ticket_sha256': reg['ticket_sha256'],
            'updated_at': now,
          });
        }
        inc('kept');
      }
    }
    for (final row in _rows(gameId)) {
      if (row['status'] == 'expected' &&
          !listed.contains(row['registration_id'])) {
        final pid = row['player_id'];
        _declarations.removeWhere(
          (_, d) => d['game_id'] == gameId && d['player_id'] == pid,
        );
        _checkins.remove(row);
        inc('removed');
      }
    }
    if (['added', 'updated', 'removed'].any((k) => out[k] != 0)) {
      _save();
      engine.emit({
        'type': 'roster',
        'game': gameId,
        'counts': Map.of(out),
        '_staff': true,
      });
    }
    return out;
  }

  List<Map<String, Object?>> _rosterDeclarations(
    int gameId,
    String pid,
    List<Object?> items,
    Map<String, Object?> st,
    Map<String, Object?> out,
  ) {
    final decls = <Map<String, Object?>>[];
    void drop() =>
        out['dropped_declarations'] = (out['dropped_declarations']! as int) + 1;
    for (final item in items) {
      final Map<String, Object?> d;
      try {
        d = validateDeclaration(item);
      } on ControllerError {
        drop();
        continue;
      }
      final other = _declarations[d['declaration_id']];
      if (!limits.classes.containsKey(d['class']) ||
          decls.length >= (st['max_replicas']! as int) ||
          (other != null &&
              (other['game_id'] != gameId || other['player_id'] != pid))) {
        drop();
        continue;
      }
      decls.add(d);
    }
    return decls;
  }

  /// What goes back to the site server after the game (checkin.py
  /// `outcomes`): per registration its outcome and its declarations' final
  /// states, and the walk-ins as a count. No names, no federation numbers.
  Map<String, Object?> outcomes(int gameId) {
    const arrivedStates = ['pending', 'checked_in', 'left'];
    final regs = <Map<String, Object?>>[];
    var walkins = 0;
    for (final r in _rows(gameId)) {
      final arrived =
          arrivedStates.contains(r['status']) ||
          (r['status'] == 'removed' && r['checked_in_at'] != null);
      final rid = r['registration_id'];
      if (rid == null || rid == '') {
        if (arrived) walkins++;
        continue;
      }
      final fromRoster = r['from_roster'] == true;
      final ticket = r['ticket_sha256'];
      if (!fromRoster && (ticket == null || ticket == '')) continue;
      final pid = r['player_id']! as String;
      regs.add({
        'registration_id': rid,
        'player_id': pid,
        'outcome': arrived ? 'checked_in' : 'no_show',
        'declarations': [
          for (final d in _decls(gameId, pid).take(20))
            {
              'declaration_id': d['declaration_id'],
              'state': d['state'],
              'reading_id': d['reading_id'],
            },
        ],
        if (!fromRoster) 'ticket_sha256': ticket,
      });
    }
    return {'registrations': regs, 'walkins': walkins};
  }

  // --- retention ------------------------------------------------------------------

  /// Erases what the retention rules say has been kept long enough (at most
  /// every 10 minutes unless [force]): the personal fields and declarations
  /// of games that ended [CheckinConfig.retentionDays] ago, field
  /// identities not seen for a year, readings older than a year.
  Map<String, int>? purge({bool force = false}) {
    final now = _wall();
    if (!force && now - _lastPurge < 600) return null;
    _lastPurge = now;
    final endedBefore = now - config.retentionDays * 86400;
    var erased = 0, declarations = 0;
    for (final g in engine.store.games()) {
      final ended = g['ended_at'];
      if (g['state'] != 'ended' || ended is! num || ended >= endedBefore) {
        continue;
      }
      final gid = g['id'];
      for (final r in _checkins) {
        if (r['game_id'] == gid && r['erased_at'] == null) {
          r
            ..['display_name'] = null
            ..['federation_number'] = null
            ..['team_preference'] = null
            ..['erased_at'] = now;
          erased++;
        }
      }
      final n = _declarations.length;
      _declarations.removeWhere((_, d) => d['game_id'] == gid);
      declarations += n - _declarations.length;
    }
    final idleBefore = now - _identityDays * 86400;
    final idle = [
      for (final p in _fieldPlayers.values)
        if ((p['last_seen_at']! as num) < idleBefore) p['player_id']! as String,
    ];
    idle.forEach(_erasePlayerRecords);
    final cutoff = formatTimestamp(
      DateTime.fromMillisecondsSinceEpoch(
        ((now - _chronoRetentionDays * 86400) * 1000).round(),
        isUtc: true,
      ),
    );
    final keysBefore = _marshalHistory.length;
    _marshalHistory.removeWhere(
      (h) => (h['replaced_at']! as num) < now - _chronoRetentionDays * 86400,
    );
    final out = {
      'checkins': erased,
      'declarations': declarations,
      'identities': idle.length,
      'readings': _deleteReadings(before: cutoff),
      'marshal_keys': keysBefore - _marshalHistory.length,
    };
    if (out.values.any((v) => v > 0)) _save();
    return out;
  }

  // --- the stream -------------------------------------------------------------------

  /// Tells staff connections (names included) and the player's own
  /// connections what changed.
  void _notify(int gameId, String pid, {bool assignment = false}) {
    final game = engine.store.game(gameId);
    final row = _row(gameId, pid);
    if (game == null || row == null) return;
    final view = rowView(game, row);
    engine.emit({
      'type': 'checkin',
      'game': gameId,
      'checkin': view,
      'assignment': assignment,
      '_staff': true,
      '_player': pid,
      '_assignment': assignment,
    });
    engine.emit({
      'type': 'chrono_list',
      'game': gameId,
      'player_id': pid,
      'declarations': [
        for (final d
            in (view['declarations']! as List).cast<Map<String, Object?>>())
          if (d['state'] != 'withdrawn') d,
      ],
      'counts': _chronoList(game)['counts'],
      '_staff': true,
      '_player': pid,
    });
  }
}

class _Judged {
  _Judged(this.highest, this.limitJ);

  final ChronoReading highest;
  final double? limitJ;
  String? outcome;
  double? tolerancePct;
  double? checkinJ;
}

class _MarshalUnknown implements Exception {
  _MarshalUnknown(this.id);
  final String id;
}

class _WrongField implements Exception {
  _WrongField(this.id);
  final String id;
}

String _iso(num? ts) {
  if (ts == null || ts == 0) return '';
  return formatTimestamp(
    DateTime.fromMillisecondsSinceEpoch((ts * 1000).floor(), isUtc: true),
  );
}

/// No formula injection when the CSV is opened in a spreadsheet.
String _csvSafe(String? value) {
  if (value == null || value.isEmpty) return '';
  return '=+-@\t\r'.contains(value[0]) ? "'$value" : value;
}

/// A CSV cell as Python's csv module writes it (minimal quoting).
String _csvCell(Object? v) {
  final s = v == null ? '' : '$v';
  if (s.contains(RegExp('[",\r\n]'))) return '"${s.replaceAll('"', '""')}"';
  return s;
}
