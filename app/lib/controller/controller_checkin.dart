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

import '../chrono/energy.dart';
import '../chrono/limit_template.dart';
import '../chrono/reading.dart';
import '../chrono/record_signer.dart';
import '../protocol/apd.dart';
import '../protocol/checkin_poster.dart';
import '../protocol/checkin_ticket.dart';
import '../security/bytes.dart';
import '../security/player_token.dart';
import 'controller_engine.dart';
import 'field_addresses.dart';
import 'registration_import.dart';

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
final _apdIdRe = RegExp(r'^[a-z0-9][a-z0-9-]{0,31}$');
const _seriesMax = 50;
const _tokenGraceS = 2 * 3600;
const _tokenMinS = 60;
const _identityDays = 365;

/// How long the field keeps chrono records and an ended game's data, in days
/// (decisions RET-1, RET-2; the Pi's `chrono_retention_days` and
/// `game_retention_days`): a setting of the field, 365 by default.
const retentionKeys = ['chrono_retention_days', 'game_retention_days'];
const retentionMinDays = 30;
const retentionMaxDays = 3653;

/// The settings a player's app is not told (the Pi's `PLAYER_HIDDEN`).
const _playerHidden = ['max_players', ...retentionKeys];
bool _daysOk(Object? v) =>
    v is int && v >= retentionMinDays && v <= retentionMaxDays;
const _settingsKeys = [
  'confirm',
  'federation',
  'federation_label',
  'max_replicas',
  'max_players',
  'chrono_valid_for',
  'apd',
  'country',
  ...retentionKeys,
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
    this.country = '',
    this.zoneName,
    this.maxReplicas = 5,
    this.maxPlayers = 300,
    this.chronoValidFor = 'day',
    this.ratePerMinute = 10,
    this.urls = const [],
    this.wifiSsid = '',
    this.noticeVersion = 1,
    this.noticePt = '',
    this.noticeEn = '',
    this.apdsJson = '',
    this.retentionDays = 30,
    this.chronoRetentionDays = 365,
    this.gameRetentionDays = 365,
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

  /// The field's country (two capitals); empty: PT where [zoneName] is
  /// Portugal's, else unset (decision MEM-2).
  final String country;

  /// The IANA name of the phone's time zone, when known.
  final String? zoneName;
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

  /// The list of APDs (assets/apds.json, protocol/apd.md), as text.
  final String apdsJson;
  final int retentionDays;

  /// The configured days chrono records, and an ended game's data, are kept
  /// (the console's and the site server's setting wins).
  final int chronoRetentionDays;
  final int gameRetentionDays;

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

/// How the poster now differs from the one last printed (checkin.py
/// `poster_change`, shared cases `poster_change` in protocol/vectors/checkin.json):
/// null when nothing was printed, there is no poster to compare or nothing
/// changed; else `added`, `removed`, `ca_changed` and `still_works`.
Map<String, Object?>? posterChange(
  Map<String, Object?>? printed,
  List<String> urls,
  String? caHex,
) {
  if (printed == null || urls.isEmpty || caHex == null) return null;
  final old = [
    for (final u in (printed['urls'] as List?) ?? const [])
      if (u is String) u,
  ];
  final added = [
    for (final u in urls)
      if (!old.contains(u)) u,
  ];
  final removed = [
    for (final u in old)
      if (!urls.contains(u)) u,
  ];
  final was = printed['ca_sha256'];
  final caChanged = was is String && was.isNotEmpty && was != caHex;
  if (added.isEmpty && removed.isEmpty && !caChanged) return null;
  return {
    'added': added,
    'removed': removed,
    'ca_changed': caChanged,
    'still_works': !caChanged && old.any(urls.contains),
  };
}

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
       _limits = LimitTemplate.parse(config.limitsYaml),
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
  LimitTemplate _limits;

  /// The chrono limit template the classes come from: the configured one, or
  /// with `[sync] branding = "site"` the one the site server sent last
  /// (BR24).
  LimitTemplate get limits => _limits;
  bool _siteManaged = false;

  /// Where a marshal's override of a membership that does not pass is logged
  /// (the player id and the verdict, never the number).
  void Function(String message) audit = _auditDefault;
  static void _auditDefault(String m) =>
      developer.log(m, name: 'atalaia.checkin', level: 800);
  final RateLimit rate;
  final RateLimit infoRate;
  final Random _random;
  double _lastPurge = 0;

  // The records (the Pi store's tables), saved as one document.
  var _fieldPlayers = <String, Map<String, Object?>>{};
  var _checkins = <Map<String, Object?>>[];
  var _declarations = <String, Map<String, Object?>>{};
  var _readings = <Map<String, Object?>>[];

  /// Other fields' records of the players on a linked game's roster, pulled
  /// from the site server with each person's consent (the Pi's
  /// `shared_readings`, schema 13, decision S14-5): `{player_id, reading_id,
  /// field_name, timestamp, record_json, public_key, pulled_at}`. Kept apart
  /// from [_readings] (the field's own measurements): never judged, counted
  /// for the list's states or sent back, and never replacing a local reading.
  var _shared = <Map<String, Object?>>[];
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

  /// Players whose data was erased on request and that the site server may
  /// not know yet (the Pi's `erasures`, schema 17, decision RET-4):
  /// `{player_id, chrono, identity, erased_at}`.
  var _erasures = <Map<String, Object?>>[];

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
    _shared = _listOf(doc['shared_readings']);
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
    _erasures = _listOf(doc['erasures']);
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
    'shared_readings': _shared,
    'marshals': _marshals,
    'marshal_roster': _roster,
    'replicas': _replicas,
    'token_keys': _tokenKeys,
    'marshal_history': _marshalHistory,
    'erasures': _erasures,
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
      'apd_id': null,
      'membership_expires': null,
      'apd_override': false,
      'apd_verdict': null,
      'apd_verdict_on': null,
      'card_checked_by': null,
      'card_checked_at': null,
      'position_share': false,
      'position_share_at': null,
      'position_share_notice': null,
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

  int _deleteShared({String? playerId, String? before}) {
    final n = _shared.length;
    if (playerId != null) {
      _shared.removeWhere((r) => r['player_id'] == playerId);
    } else if (before != null) {
      _shared.removeWhere(
        (r) => (r['timestamp']! as String).compareTo(before) < 0,
      );
    }
    return n - _shared.length;
  }

  void _erasePlayerRecords(String pid) {
    _deleteShared(playerId: pid); // other fields' copies (S14-5)
    _declarations.removeWhere((_, d) => d['player_id'] == pid);
    _checkins.removeWhere((r) => r['player_id'] == pid);
    _fieldPlayers.remove(pid);
    engine.positions?.erasePlayer(pid);
  }

  // --- settings and the poster ------------------------------------------------

  static const _siteLimitsKey = 'checkin.site_limits';
  static const _countrySiteKey = 'checkin.country_site';

  /// With `[sync] branding = "site"` (set by the sync): the limit template
  /// the site server sent last, kept in the store, replaces the configured
  /// one, so a controller that restarts offline keeps the field's rules.
  set siteManaged(bool on) {
    _siteManaged = on;
    if (!on) return;
    final saved = engine.store.getSetting(_siteLimitsKey);
    if (saved == null) return;
    try {
      final t = jsonDecode(saved);
      if (t is Map<String, Object?>) _limits = _siteTemplate(t);
    } on Object {
      // As the Pi: the saved template is unreadable, the configured one stays.
    }
  }

  bool get siteManaged => _siteManaged;

  /// A limit template as the site server sends it (`checkFieldSettings`).
  static LimitTemplate _siteTemplate(Map<String, Object?> t) {
    final verified = t['status'] == 'verified';
    final classes = <String, ClassLimit>{};
    for (final e in (t['classes']! as Map).entries) {
      final c = e.value as Map;
      final energy = (c['max_energy_j']! as num).toDouble();
      classes['${e.key}'] = ClassLimit(
        name: '${e.key}',
        maxEnergyJ: energy,
        maxFps020: fpsWith020(energy).round(),
        medM: c['med_m'] as int?,
        fireMode: FireMode.fromWire(c['fire_mode']! as String)!,
      );
    }
    return LimitTemplate(
      id: t['id']! as String,
      name: t['name']! as String,
      verified: verified,
      warning: verified ? null : "From the field's site server.",
      source: "the field's site server",
      verifiedDate: verified ? t['verified_date'] as String? : null,
      notes: null,
      classes: classes,
    );
  }

  /// The field's check-in settings from the site server (`GET
  /// /api/v1/sync/field`, with `[sync] branding = "site"`; checked by
  /// `checkFieldSettings`): its federation label (when it has one),
  /// `max_replicas` and limit template replace this controller's, so a
  /// registration the site server accepted is one this controller accepts
  /// (decision S16-6, BR24). Returns how many of the three changed.
  int applySiteSettings(Map<String, Object?> site) {
    var changed = 0;
    final cur = settings();
    final spec = <String, Object?>{'max_replicas': site['max_replicas']};
    if (site['federation_label'] != null) {
      spec['federation_label'] = site['federation_label'];
    }
    spec.removeWhere((k, v) => cur[k] == v);
    if (spec.isNotEmpty) {
      setSettings(spec);
      changed += spec.length;
    }
    if (site.containsKey('apd')) {
      // The field's APD rule (protocol/apd.md); an older site server sends none.
      final rule = ApdRule.parse(site['apd']);
      if (engine.store.getSetting('checkin.apd_site') !=
          jsonEncode(rule.toJson())) {
        applySiteApd(rule);
        changed++;
        if (spec.isEmpty) {
          engine.emit({
            'type': 'checkin_settings',
            'settings': settings(),
            '_staff': true,
          });
        }
      }
    }
    if (site.containsKey('country')) {
      // The field's country (protocol/apd.md); an older site server sends none.
      final encodedCountry = jsonEncode(site['country']);
      if (engine.store.getSetting(_countrySiteKey) != encodedCountry) {
        engine.store.setSetting(_countrySiteKey, encodedCountry);
        _save();
        changed++;
        if (spec.isEmpty) {
          engine.emit({
            'type': 'checkin_settings',
            'settings': settings(),
            '_staff': true,
          });
        }
      }
    }
    final sentDays = {
      for (final k in retentionKeys)
        if (site.containsKey(k)) k: site[k],
    };
    if (sentDays.isNotEmpty) {
      // The field's retention days (decisions RET-1, RET-2); an older site
      // server sends none.
      Map<String, Object?> before = const {};
      final raw = engine.store.getSetting(_retentionSiteKey);
      if (raw != null) {
        try {
          final m = jsonDecode(raw);
          if (m is Map) before = m.cast<String, Object?>();
        } on FormatException {
          // Replaced below.
        }
      }
      final merged = {...before, ...sentDays};
      if (jsonEncode(_sorted(merged)) != jsonEncode(_sorted(before))) {
        engine.store.setSetting(_retentionSiteKey, jsonEncode(_sorted(merged)));
        _save();
        changed++;
        if (spec.isEmpty) {
          engine.emit({
            'type': 'checkin_settings',
            'settings': settings(),
            '_staff': true,
          });
        }
      }
    }
    final template = (site['limit_template']! as Map).cast<String, Object?>();
    final encoded = jsonEncode(template);
    if (engine.store.getSetting(_siteLimitsKey) != encoded) {
      _limits = _siteTemplate(template);
      engine.store.setSetting(_siteLimitsKey, encoded);
      changed++;
      if (spec.isEmpty) {
        // setSettings told the console about the others.
        engine.emit({
          'type': 'checkin_settings',
          'settings': settings(),
          '_staff': true,
        });
      }
    }
    return changed;
  }

  Map<String, Object?> settings() {
    final out = <String, Object?>{
      'confirm': config.confirm,
      'federation': config.federation,
      'federation_label': config.federationLabel,
      'max_replicas': config.maxReplicas,
      'max_players': config.maxPlayers,
      'chrono_valid_for': config.chronoValidFor,
      'chrono_retention_days': config.chronoRetentionDays,
      'game_retention_days': config.gameRetentionDays,
    };
    final saved = engine.store.getSetting('checkin.settings');
    if (saved != null) {
      try {
        final m = jsonDecode(saved);
        if (m is Map) {
          for (final e in m.entries) {
            if (e.key == 'country' || !_settingsKeys.contains(e.key)) continue;
            if (retentionKeys.contains(e.key) && !_daysOk(e.value)) continue;
            out['${e.key}'] = e.value;
          }
        }
      } on FormatException {
        // As the Pi: a setting that is not JSON is ignored.
      }
    }
    out['apd'] = apdRule().toJson();
    out['country'] = country();
    out.addAll(_siteRetention());
    return out;
  }

  static const _retentionSiteKey = 'checkin.retention_site';

  /// The retention days the site server sent (the field's own, decision
  /// RET-2), when managed there; empty otherwise or while it sent none.
  Map<String, int> _siteRetention() {
    if (!_siteManaged) return const {};
    final raw = engine.store.getSetting(_retentionSiteKey);
    if (raw == null) return const {};
    try {
      final m = jsonDecode(raw);
      if (m is! Map) return const {};
      return {
        for (final k in retentionKeys)
          if (_daysOk(m[k])) k: m[k] as int,
      };
    } on FormatException {
      return const {};
    }
  }

  /// The console's saved value of a retention key, else the configured one.
  int _localRetention(String key) {
    final saved = engine.store.getSetting('checkin.settings');
    if (saved != null) {
      try {
        final m = jsonDecode(saved);
        if (m is Map && _daysOk(m[key])) return m[key] as int;
      } on FormatException {
        // As the Pi: ignored.
      }
    }
    return key == 'chrono_retention_days'
        ? config.chronoRetentionDays
        : config.gameRetentionDays;
  }

  /// `chrono_retention_days` or `game_retention_days` as the field has them now.
  int retentionDays(String key) => settings()[key]! as int;

  // --- the field's country (protocol/apd.md, decisions MEM-2, MEM-3) ---------

  /// The console's own choice: null when it made none.
  String? _savedCountry() {
    final saved = engine.store.getSetting('checkin.settings');
    if (saved == null) return null;
    try {
      final m = jsonDecode(saved);
      return m is Map ? lenientApdCountry(m['country']) : null;
    } on Object {
      return null;
    }
  }

  /// The configured country, else the default of the phone's time zone.
  String? _configCountry() => config.country.isNotEmpty
      ? config.country
      : apdDefaultCountry(config.zoneName);

  /// The field's country: the site server's when managed there (it may say
  /// unset), else the console's, else the configured or default one.
  String? country() {
    if (_siteManaged) {
      final raw = engine.store.getSetting(_countrySiteKey);
      if (raw != null) {
        try {
          return lenientApdCountry(jsonDecode(raw));
        } on Object {
          // Falls through to the local one.
        }
      }
    }
    return _savedCountry() ?? _configCountry();
  }

  // --- APD membership (protocol/apd.md) --------------------------------------

  ApdRule _localApd() {
    final saved = engine.store.getSetting('checkin.settings');
    if (saved == null) return ApdRule.defaults;
    try {
      final m = jsonDecode(saved);
      return m is Map ? ApdRule.parse(m['apd']) : ApdRule.defaults;
    } on Object {
      return ApdRule.defaults; // not JSON, or a rule that no longer parses
    }
  }

  /// The rule in force: the site's when managed there, else the console's.
  ApdRule apdRule() {
    if (_siteManaged) {
      final raw = engine.store.getSetting('checkin.apd_site');
      if (raw != null && raw != 'null') {
        try {
          return ApdRule.parse(jsonDecode(raw));
        } on Object {
          return ApdRule.defaults;
        }
      }
    }
    return _localApd();
  }

  /// The rule the site server's field answer carried (null: none).
  void applySiteApd(ApdRule? rule) {
    engine.store.setSetting('checkin.apd_site', jsonEncode(rule?.toJson()));
    _save();
  }

  List<ApdEntry>? _projectApds;

  /// The project's list of APDs (the shipped file).
  List<ApdEntry> projectApds() {
    if (_projectApds != null) return _projectApds!;
    try {
      return _projectApds = config.apdsJson.isEmpty
          ? const []
          : parseApdList(config.apdsJson);
    } on Object {
      return _projectApds = const [];
    }
  }

  /// What a form offers: the project's entries of the field's country, then
  /// the field's own entries.
  List<Map<String, Object?>> apdChoices() => [
    for (final e in apdRule().choices(projectApds(), country())) e.toJson(),
  ];

  /// The local date a membership is checked against (the field's day).
  String _apdToday() => apdDateOf(
    DateTime.fromMillisecondsSinceEpoch(
      (_wall() * 1000).round(),
      isUtc: config.utcDay,
    ),
  );

  /// The verdict for a check-in's membership; null when the rule does not
  /// ask at check-in.
  String? _apdVerdict(
    String? apd,
    String? number,
    String? expires, [
    ApdRule? rule,
  ]) {
    final r = rule ?? apdRule();
    if (!r.checkin) return null;
    return apdStatus(
      r,
      ApdMembership(apd: apd, number: number, expires: expires),
      _apdToday(),
    );
  }

  /// What a request body declares: the APD, the number (as
  /// `membership_number` or the old `federation_number`; both must agree)
  /// and the expiry. Each null when not sent.
  ({String? apd, String? number, String? expires}) _declared(
    Map<String, Object?> body,
  ) {
    final fed = _text(
      'federation_number',
      _truthy(body['federation_number']) ? body['federation_number'] : null,
      _federationMax,
      optional: true,
    );
    final mem = _text(
      'membership_number',
      _truthy(body['membership_number']) ? body['membership_number'] : null,
      _federationMax,
      optional: true,
    );
    if (fed != null && mem != null && fed != mem) {
      throw ControllerError(
        'membership_number: federation_number says another number',
      );
    }
    final apd = body['apd_id'];
    if (_truthy(apd) && (apd is! String || !_apdIdRe.hasMatch(apd))) {
      throw ControllerError('apd_id: a-z, 0-9 and -, 1-32 characters');
    }
    final exp = body['membership_expires'];
    if (_truthy(exp) && (exp is! String || !validApdDate(exp))) {
      throw ControllerError('membership_expires: a date, YYYY-MM-DD');
    }
    return (
      apd: _truthy(apd) ? apd as String : null,
      number: mem ?? fed,
      expires: _truthy(exp) ? exp as String : null,
    );
  }

  /// What staff see: the verdict stored when the card was checked, else the
  /// one worked out now (protocol/apd.md, "The card check").
  String? _rowVerdict(Map<String, Object?> row) =>
      (row['apd_verdict'] as String?) ??
      _apdVerdict(
        row['apd_id'] as String?,
        row['federation_number'] as String?,
        row['membership_expires'] as String?,
      );

  /// The columns of a confirmed card check: who and when, the verdict as it
  /// stood that day, and the number gone.
  Map<String, Object?> _cardFields(
    String? apd,
    String? number,
    String? expires,
    String staff,
    double now,
  ) {
    final rule = apdRule();
    return {
      'federation_seen': true,
      'card_checked_by': staff,
      'card_checked_at': now,
      'apd_verdict': apdStatus(
        rule,
        ApdMembership(apd: apd, number: number, expires: expires),
        _apdToday(),
      ),
      'apd_verdict_on': _apdToday(),
      'federation_number': null,
    };
  }

  /// Who ticked the card: the marshal's player id, or "gm" for the GM token.
  static String _staffId(ApiViewer viewer) => viewer.playerId ?? 'gm';

  /// The position-sharing choice with its time and notice version.
  Map<String, Object?> _shareFields(bool? share, Object? notice, double now) =>
      {
        'position_share': share == true,
        'position_share_at': now,
        'position_share_notice': notice,
      };

  static bool? _shareChoice(Map<String, Object?> body) {
    final v = body['share_position'];
    if (v != null && v is! bool) {
      throw ControllerError('share_position: true or false');
    }
    return v as bool?;
  }

  static const _erasedCard = <String, Object?>{
    'apd_verdict': null,
    'apd_verdict_on': null,
    'card_checked_by': null,
    'card_checked_at': null,
  };

  /// A marshal's confirmation that is not a card check, or whose verdict
  /// does not pass, is never refused, but it is logged (reason, no number)
  /// and marked. The reason is `no_card` or the verdict.
  bool _apdOverride(Map<String, Object?> row) {
    final rule = apdRule();
    final String? verdict = row['card_checked_at'] != null
        ? row['apd_verdict'] as String?
        : _rowVerdict(row);
    final reason = rule.checkin && row['card_checked_at'] == null
        ? 'no_card'
        : (verdict == null || verdict == 'valid' ? null : verdict);
    if (reason == null) return false;
    audit(
      'apd override: ${row['player_id']} confirmed in game '
      '${row['game_id']} by staff, reason $reason, verdict $verdict',
    );
    return true;
  }

  Map<String, Object?> setSettings(Map<String, Object?> spec) {
    final unknown = spec.keys.where((k) => !_settingsKeys.contains(k)).toList()
      ..sort();
    if (unknown.isNotEmpty) {
      throw ControllerError('unknown check-in settings $unknown');
    }
    if (spec.containsKey('country') &&
        _siteManaged &&
        engine.store.getSetting(_countrySiteKey) != null) {
      throw ControllerError.conflict(
        "the field's country comes from the site server (the sync's "
        'branding is "site"): change it there',
      );
    }
    if (_siteManaged) {
      final held = spec.keys.where(_siteRetention().containsKey).toList()
        ..sort();
      if (held.isNotEmpty) {
        throw ControllerError.conflict(
          '${held.first} comes from the site server (the sync\'s branding is '
          '"site"): change it there',
        );
      }
    }
    final cur = settings();
    var savedCountry = _savedCountry();
    const choices = {
      'confirm': ['auto', 'staff'],
      'federation': ['off', 'optional', 'required'],
      'chrono_valid_for': ['day', 'game'],
    };
    ApdRule? apd;
    if (spec.containsKey('apd')) {
      final site = engine.store.getSetting('checkin.apd_site');
      if (_siteManaged && site != null && site != 'null') {
        throw ControllerError.conflict(
          "the field's APD rule comes from the site server (the sync's "
          'branding is "site"): change it there',
        );
      }
      try {
        apd = ApdRule.parse(spec['apd']);
      } on ApdError catch (e) {
        throw ControllerError('apd: ${e.code}');
      }
    }
    for (final e in spec.entries) {
      final k = e.key, v = e.value;
      if (k == 'apd') continue;
      if (k == 'country') {
        final code = v is String ? v.trim().toUpperCase() : v;
        try {
          savedCountry = checkApdCountry(code == '' ? null : code);
        } on ApdError {
          throw ControllerError(
            'country: two letters (ISO 3166-1 alpha-2, e.g. PT) or empty',
          );
        }
        cur[k] = savedCountry ?? _configCountry();
        continue;
      }
      final c = choices[k];
      if (c != null && !c.contains(v)) {
        throw ControllerError('$k: one of ${c.join(', ')}');
      }
      if (k == 'federation_label') _text(k, v, 16);
      if (k == 'max_replicas' && (v is! int || v < 1 || v > 20)) {
        throw ControllerError('max_replicas: 1-20');
      }
      if (retentionKeys.contains(k) && !_daysOk(v)) {
        throw ControllerError('$k: $retentionMinDays-$retentionMaxDays');
      }
      if (k == 'max_players' && (v is! int || v < 1 || v > 5000)) {
        throw ControllerError('max_players: 1-5000');
      }
      cur[k] = v is String ? v.trim() : v;
    }
    engine.store.setSetting(
      'checkin.settings',
      jsonEncode({
        for (final k in _settingsKeys)
          k: switch (k) {
            'apd' => (apd ?? _localApd()).toJson(),
            'country' => savedCountry,
            // The console's own choice, not the site server's value laid over it.
            'chrono_retention_days' || 'game_retention_days' =>
              spec.containsKey(k) ? spec[k] : _localRetention(k),
            _ => cur[k],
          },
      }),
    );
    cur['apd'] = apdRule().toJson();
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
    final printed = printedPoster();
    out['printed'] = printed;
    out['changed'] = posterChange(printed, [
      for (final u in p['urls']! as List) '$u',
    ], out['ca_sha256'] as String?);
    return out;
  }

  /// The poster the GM last printed: `urls`, `ca_sha256` (hex) and `at`
  /// (seconds), or null (checkin.py `printed_poster`).
  Map<String, Object?>? printedPoster() {
    final raw = engine.store.getSetting('checkin.poster_printed');
    if (raw == null) return null;
    try {
      final m = jsonDecode(raw);
      return m is Map && m['urls'] is List ? m.cast<String, Object?>() : null;
    } on FormatException {
      return null;
    }
  }

  /// The GM printed (or showed) the poster as it is now: later changes are
  /// measured from here (checkin.py `mark_poster_printed`).
  Map<String, Object?> markPosterPrinted() {
    final p = posterFields();
    final ca = p['ca_sha256'] as Uint8List?;
    final urls = p['urls']! as List;
    if (ca == null || urls.isEmpty) {
      throw ControllerError('there is no poster to print yet');
    }
    engine.store.setSetting(
      'checkin.poster_printed',
      jsonEncode({'urls': urls, 'ca_sha256': _hex(ca), 'at': _wall()}),
    );
    return poster();
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
      final st = settings();
      texts[lang] = body
          .replaceAll('{operator}', op)
          .replaceAll('{retention_days}', '${config.retentionDays}')
          .replaceAll(
            '{chrono_retention_days}',
            '${st['chrono_retention_days']}',
          )
          .replaceAll('{game_retention_days}', '${st['game_retention_days']}');
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
          if (!_playerHidden.contains(e.key)) e.key: e.value,
      },
      'limits': {
        'id': limits.id,
        'name': limits.name,
        'status': limits.verified ? 'verified' : 'unverified',
        'classes': limits.classes.keys.toList()..sort(),
      },
      'replica_types': replicaTypes,
      'apds': apdChoices(),
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
      'membership_number',
      'apd_id',
      'membership_expires',
      'team_preference',
      'notice_version',
      'replicas',
      'registration_id',
      'ticket',
      'share_position',
    };
    final unknown = body.keys.where((k) => !allowed.contains(k)).toList()
      ..sort();
    if (unknown.isNotEmpty) throw ControllerError('unknown fields $unknown');
    final share = _shareChoice(body);
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
    final declared = _declared(body);
    final fedIn = declared.number;
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
    var apdId = declared.apd ?? expected?['apd_id'] as String?;
    var expires =
        declared.expires ?? expected?['membership_expires'] as String?;
    final rule = apdRule();
    if (st['federation'] == 'off' && !rule.checkin) {
      fed = null;
      apdId = null;
      expires = null;
    } else if (st['federation'] == 'required' && fed == null) {
      throw ControllerError(
        'federation_number: this field asks for your '
        '${st['federation_label']} number',
      );
    }
    // A membership that does not pass leaves the check-in to a marshal; so
    // does any rule that checks at check-in: only "card seen, matches"
    // lets a player in (protocol/apd.md, "The card check").
    final apdPending =
        rule.checkin ||
        (_apdVerdict(apdId, fed, expires, rule) ?? 'valid') != 'valid';
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
      final status = st['confirm'] == 'auto' && !apdPending
          ? 'checked_in'
          : 'pending';
      final fields = <String, Object?>{
        'status': status,
        'display_name': name,
        'federation_number': fed,
        'apd_id': apdId,
        'membership_expires': expires,
        'team_preference': pref,
        'notice_version': notice,
        'checked_in_at': status == 'checked_in' ? now : null,
        ..._shareFields(share, notice, now),
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
        status = st['confirm'] == 'auto' && !apdPending
            ? 'checked_in'
            : 'pending';
        emit = status == 'checked_in';
      }
      final fields = <String, Object?>{
        'status': status,
        'display_name': name,
        'team_preference': pref,
        'notice_version': notice,
        'updated_at': now,
      };
      // Once a marshal checked the card the number is gone and the stored
      // verdict stands: the app cannot put the number back.
      if (row['card_checked_at'] == null) {
        if (fed != row['federation_number']) {
          fields['federation_number'] = fed;
          fields['federation_seen'] = false;
        }
        if (apdId != row['apd_id']) fields['apd_id'] = apdId;
        if (expires != row['membership_expires']) {
          fields['membership_expires'] = expires;
        }
      }
      if (share != null) fields.addAll(_shareFields(share, notice, now));
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
    'position_share': row['position_share'] == true,
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
      'position_share': row['position_share'] == true,
      'position_share_at': row['position_share_at'],
      'position_share_notice': row['position_share_notice'],
    };
    if (names) {
      out.addAll({
        'display_name': row['display_name'],
        'federation_number': row['federation_number'],
        'federation_seen': row['federation_seen'],
        'team_preference': row['team_preference'],
        'apd_id': row['apd_id'],
        'membership_number': row['federation_number'],
        'membership_expires': row['membership_expires'],
        'apd_override': row['apd_override'] == true,
        'apd_status': _rowVerdict(row),
        'apd_verdict_on': row['apd_verdict_on'],
        'card_checked_by': row['card_checked_by'],
        'card_checked_at': row['card_checked_at'],
        'country': country(),
      });
    }
    if (declarations) {
      out['declarations'] = _declViews(
        game['id']! as int,
        row['player_id']! as String,
      );
      if (names) {
        final shared = sharedView(row['player_id']! as String);
        if (shared.isNotEmpty) out['shared_readings'] = shared;
      }
    }
    return out;
  }

  /// For tests only: the field's own readings replaced by these signed
  /// records, as if marshals had uploaded them (the shared vectors' "already
  /// a local measurement").
  void debugSetLocalReadings(List<Map<String, Object?>> records) {
    _readings = [
      for (final r in records)
        {
          'reading_id': r['reading_id'],
          'replica_id': r['replica_id'],
          'player_id': r['player_id'],
          'marshal_id': r['marshal_id'],
          'type': r['type'],
          'game_id': r['game_id'],
          'timestamp': r['timestamp'],
          'record': r,
          'series_id': newUuid(_random),
          'outcome': 'pass',
          'received_at': _wall(),
        },
    ];
  }

  /// A player's records from other fields as the lists show them: marked as
  /// from another field (with its name) and never part of the field's own
  /// readings or judgements (checkin.py `shared_view`).
  List<Map<String, Object?>> sharedView(String pid) {
    final rows = [
      for (final r in _shared)
        if (r['player_id'] == pid) r,
    ];
    rows.sort((a, b) {
      final c = (a['timestamp']! as String).compareTo(
        b['timestamp']! as String,
      );
      return c != 0
          ? c
          : (a['reading_id']! as String).compareTo(b['reading_id']! as String);
    });
    final out = <Map<String, Object?>>[];
    for (final r in rows) {
      final rec = jsonDecode(r['record_json']! as String) as Map;
      out.add({
        'reading_id': r['reading_id'],
        'field': r['field_name'],
        'from_other_field': true,
        'type': rec['type'],
        'timestamp': r['timestamp'],
        'velocity_mps': rec['velocity_mps'],
        'bb_weight_g': rec['bb_weight_g'],
        'energy_j': rec['energy_j'],
        'marshal_name': rec['marshal_name'],
      });
    }
    return out;
  }

  /// Other fields' records of the game's roster players, from `GET
  /// /api/v1/sync/chrono` (S14-5, checked by controller_sync_format.dart's
  /// `checkSharedChrono`; checkin.py `apply_shared_chrono`). The site server
  /// decided what may be shared (consent for both fields); this keeps only
  /// what it can check: players on this roster, a record the marshal's key
  /// given with it signed, one younger than the retention period, and none
  /// whose id is a measurement of this field (a local reading is never
  /// replaced). A roster player the answer leaves out has none kept (a
  /// consent withdrawn). Returns `{players, stored, dropped}`.
  Future<Map<String, Object?>> applySharedChrono(
    int gameId,
    List<String> rosterPlayers,
    Map<String, Object?> answer,
  ) async {
    final now = _wall();
    final cutoff = formatTimestamp(
      DateTime.fromMillisecondsSinceEpoch(
        ((now - retentionDays('chrono_retention_days') * 86400) * 1000).round(),
        isUtc: true,
      ),
    );
    final on = rosterPlayers.toSet();
    final rows = <String, List<Map<String, Object?>>>{
      for (final p in rosterPlayers) p: [],
    };
    var dropped = 0;
    for (final entry
        in (answer['players']! as List).cast<Map<String, Object?>>()) {
      final readings = (entry['readings']! as List)
          .cast<Map<String, Object?>>();
      final pid = entry['player_id']! as String;
      if (!on.contains(pid)) {
        dropped += readings.length;
        continue;
      }
      for (final item in readings) {
        final key = base64.decode(item['public_key']! as String);
        final ChronoReading record;
        try {
          record = await verifyRecordText(item['record']! as String, key);
        } on ChronoVerifyException {
          dropped++;
          continue;
        }
        if (record.timestamp.compareTo(cutoff) < 0 ||
            _readings.any((r) => r['reading_id'] == record.readingId)) {
          dropped++;
          continue;
        }
        rows[pid]!.add({
          'player_id': pid,
          'reading_id': record.readingId,
          'field_name': item['field'],
          'timestamp': record.timestamp,
          'record_json': item['record'],
          'public_key': item['public_key'],
          'pulled_at': now,
        });
      }
    }
    final changed = <String>[];
    for (final e in rows.entries) {
      final before = {
        for (final r in _shared)
          if (r['player_id'] == e.key) r['reading_id'],
      };
      final after = {for (final r in e.value) r['reading_id']};
      if (before.length != after.length || !before.containsAll(after)) {
        changed.add(e.key);
      }
      _shared.removeWhere((r) => r['player_id'] == e.key);
      _shared.addAll(e.value);
    }
    _save();
    for (final pid in changed) {
      if (_row(gameId, pid) != null) _notify(gameId, pid);
    }
    return {
      'players': rows.values.where((v) => v.isNotEmpty).length,
      'stored': rows.values.fold<int>(0, (n, v) => n + v.length),
      'dropped': dropped,
    };
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
          if (!_playerHidden.contains(e.key)) e.key: e.value,
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

  /// PUT /api/v1/checkin/me/position-sharing: the player turns sharing their
  /// position with the game on or off, at any time. Off drops the stored
  /// position at once. Recorded with the time and the notice version.
  Map<String, Object?> setPositionSharing(
    ApiViewer viewer,
    Map<String, Object?> body,
  ) {
    if (body.keys.any((k) => k != 'share_position') ||
        body['share_position'] is! bool) {
      throw ControllerError('share_position: true or false, nothing else');
    }
    final gid = viewer.gameId!, pid = viewer.playerId!;
    final game = engine.store.game(gid);
    if (game == null || game['state'] == 'ended') {
      throw ControllerError.conflict('the game has ended');
    }
    final row = _row(gid, pid);
    if (row == null || row['status'] == 'left' || row['status'] == 'removed') {
      throw ControllerError.conflict('this check-in is over');
    }
    final now = _wall();
    final on = body['share_position']! as bool;
    _update(gid, pid, {
      'updated_at': now,
      ..._shareFields(on, config.noticeVersion, now),
    });
    if (!on) {
      engine.positions?.erasePlayerIn(gid, pid);
      engine.emit({
        'type': 'positions',
        'game': gid,
        '_positions_refresh': true,
      });
    }
    _save();
    _notify(gid, pid);
    return rowView(game, _row(gid, pid)!, names: false, declarations: false);
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
      'apd_id': null,
      'membership_expires': null,
      'apd_override': false,
      ..._erasedCard,
      'position_share': false,
      'position_share_at': now,
      'team_preference': null,
      'updated_at': now,
      'erased_at': now,
    });
    engine.positions?.erasePlayerIn(gid, pid);
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
      'membership_number',
      'apd_id',
      'membership_expires',
      'team_preference',
      'replicas',
      'federation_seen',
      'share_position',
    };
    final unknown = body.keys.where((k) => !allowed.contains(k)).toList()
      ..sort();
    if (unknown.isNotEmpty) throw ControllerError('unknown fields $unknown');
    final share = _shareChoice(body);
    final seen = body['federation_seen'];
    if (seen != null && seen is! bool) {
      throw ControllerError('federation_seen: true or false');
    }
    final st = settings();
    final name = _text('display_name', body['display_name'], _nameMax);
    final declared = _declared(body);
    var fed = declared.number;
    var apdId = declared.apd;
    var expires = declared.expires;
    if (st['federation'] == 'off' && !apdRule().checkin) {
      fed = null;
      apdId = null;
      expires = null;
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
    final carded = apdRule().checkin && seen == true;
    _addCheckin(gameId, pid, {
      'status': 'checked_in',
      'display_name': name,
      'federation_number': fed,
      'federation_seen': apdRule().checkin ? carded : fed != null,
      'apd_id': apdId,
      'membership_expires': expires,
      'team_preference': pref,
      'manual': true,
      'checked_in_at': now,
      ..._shareFields(share, config.noticeVersion, now),
      if (carded) ..._cardFields(apdId, fed, expires, _staffId(viewer), now),
    }, now);
    if (carded) {
      audit(
        'card check: game $gameId, $pid by ${_staffId(viewer)}, verdict '
        '${_row(gameId, pid)!['apd_verdict']}',
      );
    }
    _update(gameId, pid, {'apd_override': _apdOverride(_row(gameId, pid)!)});
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
    const marshalFields = {
      'status',
      'federation_seen',
      'replicas',
      'federation_number',
      'membership_number',
      'apd_id',
      'membership_expires',
    };
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
    final seen = body['federation_seen'];
    if (body.containsKey('federation_seen')) {
      if (seen is! bool) {
        throw ControllerError('federation_seen: true or false');
      }
      fields['federation_seen'] = seen;
    }
    var redone = false;
    if (const [
      'federation_number',
      'membership_number',
      'apd_id',
      'membership_expires',
    ].any(body.containsKey)) {
      // The marshal corrects what the card shows (an empty value clears it).
      final d = _declared(body);
      final before = [
        row['federation_number'],
        row['apd_id'],
        row['membership_expires'],
      ];
      if (body.containsKey('federation_number') ||
          body.containsKey('membership_number')) {
        fields['federation_number'] = d.number;
        fields['federation_seen'] = false;
      }
      if (body.containsKey('apd_id')) fields['apd_id'] = d.apd;
      if (body.containsKey('membership_expires')) {
        fields['membership_expires'] = d.expires;
      }
      final after = [
        fields.containsKey('federation_number')
            ? fields['federation_number']
            : row['federation_number'],
        fields.containsKey('apd_id') ? fields['apd_id'] : row['apd_id'],
        fields.containsKey('membership_expires')
            ? fields['membership_expires']
            : row['membership_expires'],
      ];
      if (before.toString() != after.toString()) {
        // New data: an earlier card check no longer covers it.
        fields.addAll(_erasedCard);
        redone = true;
        if (body.containsKey('federation_seen')) {
          fields['federation_seen'] = seen;
        }
      }
    }
    final cardRule = apdRule().checkin;
    final cardDone = row['card_checked_at'] != null && !redone;
    if (cardRule && seen == false && cardDone) {
      throw ControllerError.conflict(
        'the card check is recorded and the number erased; send the number '
        'again to redo it',
      );
    }
    if (cardRule && seen == true && !cardDone) {
      // "Card seen, matches": records who and when, stores the verdict,
      // erases the number; the tick is the confirmation the rule waits for.
      final number = fields.containsKey('federation_number')
          ? fields['federation_number'] as String?
          : row['federation_number'] as String?;
      fields.addAll(
        _cardFields(
          (fields.containsKey('apd_id') ? fields['apd_id'] : row['apd_id'])
              as String?,
          number,
          (fields.containsKey('membership_expires')
                  ? fields['membership_expires']
                  : row['membership_expires'])
              as String?,
          _staffId(viewer),
          now,
        ),
      );
      if ((row['status'] == 'pending' || row['status'] == 'expected') &&
          !fields.containsKey('status')) {
        fields['status'] = 'checked_in';
        fields['checked_in_at'] = now;
        emit = true;
      }
      audit(
        'card check: game $gameId, $pid by ${_staffId(viewer)}, verdict '
        '${fields['apd_verdict']}',
      );
    }
    if (body.containsKey('replicas')) {
      final decls = _checkDeclarations(body['replicas'], settings());
      _replaceDeclarations(game, pid, decls, staff: true, now: now);
    }
    _update(gameId, pid, fields);
    var after = _row(gameId, pid)!;
    if (emit && _apdOverride(after)) {
      _update(gameId, pid, {'apd_override': true});
      after = _row(gameId, pid)!;
    }
    _save();
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
    final arriving = row['status'] == 'expected';
    var emit = false;
    if (arriving) {
      final st = settings();
      if (_count(gameId) >= (st['max_players']! as int)) {
        throw _forbidden('game $gameId is full (${st['max_players']} players)');
      }
      if (apdRule().checkin) {
        // The ticket is not the card: pending until "card seen, matches".
        _update(gameId, pid, {'status': 'pending', 'updated_at': now});
      } else {
        emit = true;
        _update(gameId, pid, {
          'status': 'checked_in',
          'checked_in_at': now,
          'updated_at': now,
        });
      }
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
      'apd_id',
      'membership_expires',
      'apd_status',
      'card_seen',
      'card_checked_by',
      'card_checked_at',
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
        r['apd_id'] ?? '',
        r['membership_expires'] ?? '',
        _rowVerdict(r) ?? '',
        r['federation_seen'] == true ? 'yes' : '',
        r['card_checked_by'] ?? '',
        _iso(r['card_checked_at'] as num?),
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
      // A player with no replica is listed only while a marshal has to let
      // them in.
      if (decls.isEmpty && r['status'] != 'pending') continue;
      players.add({
        'player_id': r['player_id'],
        'display_name': r['display_name'],
        'status': r['status'],
        'team': _teamName(game, r['team']! as int),
        'squad': r['squad'],
        'seq': r['seq'],
        'pending': decls.where((d) => d['state'] == 'pending').length,
        'apd_id': r['apd_id'],
        'membership_number': r['federation_number'],
        'membership_expires': r['membership_expires'],
        'apd_override': r['apd_override'] == true,
        'apd_status': _rowVerdict(r),
        'declarations': decls,
        'shared_readings': sharedView(r['player_id']! as String),
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
      'country': country(),
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
        'limit_j': judged.limitJ,
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
    _deleteShared(playerId: pid); // other fields' copies of them (S14-5)
    final n = _deleteReadings(playerId: pid);
    _recordErasure(pid, chrono: true, identity: false);
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
    _recordErasure(pid, chrono: chronoToo, identity: true);
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
        'limit_j': r['limit_j'],
      },
  ];

  /// The namespace of an imported list's registration ids (uuid5 of source +
  /// reference; checkin.py `IMPORT_NS`).
  static const _importNamespace = '6f1b5f0e-3c1d-5a7e-9b44-0a7a1a1a0001';
  static const _importListed = 100;

  /// `POST /api/v1/games/{id}/checkins/import` (checkin.py
  /// `import_registrations`, PKE-1): a CSV or JSON list of registrations (the
  /// site server's import format, registration_import.dart) becomes this
  /// game's expected check-ins, for a field with no site server. Body:
  /// `format` (csv or json), `data` (the file's text), `source`, `dry_run`
  /// and, for a real import, `basis_confirmed`. A row the field's rules refuse
  /// is listed with a code and the others still go in; an imported
  /// registration has no ticket and no app identity (a marshal ticks it by
  /// name); a player who has arrived is never changed; a registration the file
  /// no longer lists is reported (`missing`), never removed.
  Map<String, Object?> importRegistrations(
    int gameId,
    Map<String, Object?> body,
  ) {
    const allowed = {'format', 'data', 'source', 'dry_run', 'basis_confirmed'};
    final unknown = body.keys.where((k) => !allowed.contains(k)).toList()
      ..sort();
    if (unknown.isNotEmpty) throw ControllerError('unknown fields $unknown');
    final game = engine.store.game(gameId);
    if (game == null) throw ControllerError.notFound('no game $gameId');
    if (game['state'] == 'ended') throw ControllerError.conflict('game_ended');
    final dryRun = body['dry_run'] ?? false;
    final confirmed = body['basis_confirmed'] ?? false;
    if (dryRun is! bool || confirmed is! bool) {
      throw ControllerError('dry_run and basis_confirmed: true or false');
    }
    final ParsedImport parsed;
    final String source;
    try {
      source = checkImportSource(body['source'] ?? 'csv');
      final data = body['data'];
      if (data is! String) throw ImportFileError('empty');
      if (!dryRun && !confirmed) {
        throw ControllerError('basis_not_confirmed');
      }
      final bytes = importBytes(data);
      if (bytes == null) throw ImportFileError('encoding_invalid');
      parsed = parseImport(bytes, body['format']);
    } on ImportFileError catch (e) {
      throw ControllerError(
        e.code,
        status: e.code == 'too_large' || e.code == 'too_many_rows' ? 413 : 400,
        extra: {if (e.line != null) 'line': e.line},
      );
    }
    final st = settings();
    final asked = st['federation'] != 'off' || apdRule().checkin;
    final rules = ImportRules(
      teams: (game['teams']! as List).cast<String>(),
      // A field whose APD rule asks at check-in keeps the number an import
      // carries even when the federation setting asks for none.
      federation: st['federation'] == 'off' && apdRule().checkin
          ? 'optional'
          : st['federation']! as String,
      predeclareReplicas: true,
      classes: limits.classes.keys.toList(),
      maxReplicas: st['max_replicas']! as int,
    );
    final now = _wall();
    final counts = {
      'created': 0,
      'updated': 0,
      'unchanged': 0,
      'skipped': 0,
      'refused': 0,
    };
    final results = <Map<String, Object?>>[];
    final seen = <String>{};
    final byRef = <String, Map<String, Object?>>{
      for (final r in _rows(gameId))
        if (r['registration_id'] != null &&
            r['registration_id'] != '' &&
            r['from_roster'] != true &&
            (r['ticket_sha256'] == null || r['ticket_sha256'] == ''))
          r['registration_id']! as String: r,
    };
    for (final raw in parsed.rows) {
      final entry = <String, Object?>{'row': raw.number};
      final ImportRow row;
      try {
        row = checkImportRow(raw, rules);
      } on ImportRowError catch (e) {
        entry
          ..['result'] = 'refused'
          ..['code'] = e.code;
        counts['refused'] = counts['refused']! + 1;
        results.add(entry);
        continue;
      }
      entry
        ..['external_ref'] = row.externalRef
        ..['display_name'] = row.displayName
        ..['warnings'] = List.of(row.warnings);
      String? rid;
      if (row.externalRef != null) {
        rid = uuid5(_importNamespace, '$source\u0000${row.externalRef}');
        if (!seen.add(rid)) {
          entry
            ..['result'] = 'refused'
            ..['code'] = 'external_ref_twice';
          counts['refused'] = counts['refused']! + 1;
          results.add(entry);
          continue;
        }
      }
      final existing = rid == null ? null : byRef[rid];
      if (existing == null) {
        entry['result'] = 'created';
        if (!dryRun) _importNew(game, row, rid ?? uuid4(_random), now, asked);
      } else if (existing['status'] != 'expected') {
        entry
          ..['result'] = 'skipped'
          ..['code'] = existing['status'] == 'removed'
              ? 'removed'
              : 'already_arrived';
      } else {
        final changed = _importChanges(gameId, existing, row, asked);
        entry['result'] = changed.isEmpty ? 'unchanged' : 'updated';
        if (changed.isNotEmpty) {
          entry['changed'] = changed;
          if (!dryRun) _importUpdate(game, existing, row, now, asked);
        }
      }
      final result = entry['result']! as String;
      counts[result] = counts[result]! + 1;
      results.add(entry);
    }
    final missing = [
      for (final e in byRef.entries)
        if (e.value['status'] == 'expected' && !seen.contains(e.key))
          e.value['player_id']! as String,
    ]..sort();
    if (!dryRun && (counts['created']! > 0 || counts['updated']! > 0)) {
      _save();
      engine.emit({
        'type': 'roster',
        'game': gameId,
        'counts': Map.of(counts),
        '_staff': true,
      });
      developer.log(
        'registration import for game $gameId: $counts (source $source)',
        name: 'atalaia.checkin',
        level: 800,
      );
    }
    return {
      'dry_run': dryRun,
      'format': parsed.format,
      'source': source,
      'game_id': gameId,
      'columns': parsed.columns,
      'not_imported_columns': parsed.ignored,
      'not_imported_more': parsed.ignoredMore,
      'rows': parsed.rows.length,
      'counts': counts,
      'missing': {
        'count': missing.length,
        'player_ids': missing.take(_importListed).toList(),
      },
      'results': results,
    };
  }

  void _importNew(
    Map<String, Object?> game,
    ImportRow row,
    String rid,
    double now,
    bool asked,
  ) {
    var pid = _newPlayerId();
    while (_fieldPlayers.containsKey(pid)) {
      pid = _newPlayerId();
    }
    final teams = (game['teams']! as List).cast<String>();
    _fieldPlayers[pid] = {
      'player_id': pid,
      'secret_sha256': null,
      'created_at': now,
      'last_seen_at': now,
    };
    _addCheckin(game['id']! as int, pid, {
      'status': 'expected',
      'display_name': row.displayName,
      'federation_number': asked ? row.federationNumber : null,
      'apd_id': asked ? row.apdId : null,
      'membership_expires': asked ? row.membershipExpires : null,
      'team_preference': teams.contains(row.teamPreference)
          ? row.teamPreference
          : null,
      'registration_id': rid,
      'from_roster': false,
    }, now);
    _replaceDeclarations(
      game,
      pid,
      _importDeclarations(rid, row),
      staff: true,
      now: now,
    );
  }

  void _importUpdate(
    Map<String, Object?> game,
    Map<String, Object?> existing,
    ImportRow row,
    double now,
    bool asked,
  ) {
    final pid = existing['player_id']! as String;
    final fields = <String, Object?>{'updated_at': now};
    if (row.present.contains('display_name')) {
      fields['display_name'] = row.displayName;
    }
    if (row.present.contains('team_preference')) {
      fields['team_preference'] = row.teamPreference;
    }
    // Once the card was checked the number is gone for good: an import
    // never puts it (or a changed membership) back over the stored verdict.
    final carded = existing['card_checked_at'] != null;
    if (row.present.contains('federation_number') && !carded) {
      fields['federation_number'] = asked ? row.federationNumber : null;
    }
    if (row.present.contains('apd_id') && !carded) {
      fields['apd_id'] = asked ? row.apdId : null;
    }
    if (row.present.contains('membership_expires') && !carded) {
      fields['membership_expires'] = asked ? row.membershipExpires : null;
    }
    _update(game['id']! as int, pid, fields);
    if (row.replicas != null) {
      _replaceDeclarations(
        game,
        pid,
        _importDeclarations(existing['registration_id']! as String, row),
        staff: true,
        now: now,
      );
    }
  }

  List<Map<String, Object?>> _importDeclarations(String rid, ImportRow row) => [
    for (final (i, r) in (row.replicas ?? const []).indexed)
      {
        'declaration_id': uuid5(rid, 'declaration-$i'),
        'replica_id': null,
        'type': r['type'],
        'class': r['class'],
        'make_model': r['make_model'],
      },
  ];

  /// The names of what the row changes, among the columns the file has.
  List<String> _importChanges(
    int gameId,
    Map<String, Object?> existing,
    ImportRow row,
    bool asked,
  ) {
    final changed = <String>[];
    if (row.present.contains('display_name') &&
        row.displayName != existing['display_name']) {
      changed.add('display_name');
    }
    if (row.present.contains('team_preference') &&
        row.teamPreference != existing['team_preference']) {
      changed.add('team_preference');
    }
    final carded = existing['card_checked_at'] != null; // see _importUpdate
    if (!carded &&
        row.present.contains('federation_number') &&
        (asked ? row.federationNumber : null) !=
            existing['federation_number']) {
      changed.add('federation_number');
    }
    if (!carded &&
        row.present.contains('apd_id') &&
        (asked ? row.apdId : null) != existing['apd_id']) {
      changed.add('apd_id');
    }
    if (!carded &&
        row.present.contains('membership_expires') &&
        (asked ? row.membershipExpires : null) !=
            existing['membership_expires']) {
      changed.add('membership_expires');
    }
    final replicas = row.replicas;
    if (replicas != null) {
      final old = [
        for (final d in _decls(gameId, existing['player_id']! as String))
          if (d['state'] != 'withdrawn')
            '${d['type']}|${d['class']}|${d['make_model']}',
      ];
      final wanted = [
        for (final r in replicas)
          '${r['type']}|${r['class']}|${r['make_model']}',
      ];
      if (old.length != wanted.length ||
          [
            for (var i = 0; i < old.length; i++) old[i] != wanted[i],
          ].any((x) => x)) {
        changed.add('replicas');
      }
    }
    return changed;
  }

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
      final asked = st['federation'] != 'off' || apdRule().checkin;
      final fed = asked ? reg['federation_number'] : null;
      final apdId = asked ? reg['apd_id'] : null;
      final expires = asked ? reg['membership_expires'] : null;
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
        'apd_id': apdId,
        'membership_expires': expires,
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
          row['from_roster'] == true &&
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
            ..['apd_id'] = null
            ..['membership_expires'] = null
            ..['apd_verdict'] = null
            ..['apd_verdict_on'] = null
            ..['card_checked_by'] = null
            ..['card_checked_at'] = null
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
    final chronoDays = retentionDays('chrono_retention_days');
    final cutoff = formatTimestamp(
      DateTime.fromMillisecondsSinceEpoch(
        ((now - chronoDays * 86400) * 1000).round(),
        isUtc: true,
      ),
    );
    final keysBefore = _marshalHistory.length;
    _marshalHistory.removeWhere(
      (h) => (h['replaced_at']! as num) < now - chronoDays * 86400,
    );
    final erasuresBefore = _erasures.length;
    _erasures.removeWhere(
      (e) => (e['erased_at']! as num) < now - chronoDays * 86400,
    );
    final games = _purgeGames(now);
    final out = {
      'checkins': erased,
      'declarations': declarations,
      'identities': idle.length,
      'readings': _deleteReadings(before: cutoff),
      // Other fields' records pulled from the site server (S14-5): the same period.
      'shared_readings': _deleteShared(before: cutoff),
      'marshal_keys': keysBefore - _marshalHistory.length,
      'erasure_records': erasuresBefore - _erasures.length,
      ...games,
    };
    if (out.values.any((v) => v > 0)) _save();
    return out;
  }

  /// Ended games older than `game_retention_days` go whole: events, scores,
  /// nodes, positions, their check-in rows and token key and sync bookkeeping
  /// (decision RET-1). With the site sync on, a game the site server has not
  /// confirmed (sync state `final`: ended and every event acknowledged) is
  /// never purged (decision RET-3): the field's only copy would go. Without
  /// a sync, age alone decides.
  Map<String, int> _purgeGames(double now) {
    final before = now - retentionDays('game_retention_days') * 86400;
    final syncOn = engine.syncStatus != null;
    final sync = engine.store.document('sync');
    final states = sync is Map && sync['games'] is Map
        ? (sync['games'] as Map)
        : const <Object?, Object?>{};
    var games = 0, events = 0, kept = 0;
    final gone = <String>[];
    for (final g in engine.store.games()) {
      if (g['state'] != 'ended') continue;
      final ended = g['ended_at'] ?? g['created_at'];
      if (ended is! num || ended >= before) continue;
      final gid = g['id']! as int;
      if (syncOn) {
        final st = states['$gid:${g['game_seed']}'];
        if (!(st is Map && st['final'] == true)) {
          kept++;
          continue;
        }
      }
      events += engine.store.eventLog(gid).length;
      _checkins.removeWhere((r) => r['game_id'] == gid);
      _declarations.removeWhere((_, d) => d['game_id'] == gid);
      _tokenKeys.remove('$gid');
      engine.schedule?.forgetGame(gid, g['game_seed']! as int);
      engine.store.deleteGame(gid);
      gone.add('$gid:${g['game_seed']}');
      games++;
    }
    if (gone.isNotEmpty && sync is Map) {
      final all = {...?(sync['games'] as Map?)?.cast<String, Object?>()}
        ..removeWhere((k, _) => gone.contains(k));
      engine.store.putDocument('sync', {
        ...sync.cast<String, Object?>(),
        'games': all,
      });
    }
    return {'games': games, 'game_events': events, 'games_unsynced_kept': kept};
  }

  // --- erasure records (S14-10, decision RET-4) ---------------------------------

  /// With the site sync on, keeps that this player's data was erased until
  /// the site server has it: the next sync sends `POST
  /// /api/v1/sync/erasures`. Nothing is kept without a sync.
  void _recordErasure(
    String pid, {
    required bool chrono,
    required bool identity,
  }) {
    if (engine.syncStatus == null) return;
    final old = _erasures.where((e) => e['player_id'] == pid).firstOrNull;
    _erasures.removeWhere((e) => e['player_id'] == pid);
    _erasures.add({
      'player_id': pid,
      'chrono': chrono || old?['chrono'] == true,
      'identity': identity || old?['identity'] == true,
      'erased_at': _wall(),
    });
  }

  /// The erasures the site server may not have yet, oldest first.
  List<Map<String, Object?>> erasures([int limit = 500]) {
    final out = [..._erasures]
      ..sort((a, b) {
        final c = (a['erased_at']! as num).compareTo(b['erased_at']! as num);
        return c != 0
            ? c
            : (a['player_id']! as String).compareTo(b['player_id']! as String);
      });
    return [
      for (final e in out.take(limit)) {...e},
    ];
  }

  /// The records the site server acknowledged: only as they were sent (an
  /// erasure added to since stays).
  int deleteErasures(List<Map<String, Object?>> sent) {
    final n = _erasures.length;
    for (final e in sent) {
      _erasures.removeWhere(
        (x) =>
            x['player_id'] == e['player_id'] &&
            x['erased_at'] == e['erased_at'],
      );
    }
    if (_erasures.length != n) _save();
    return n - _erasures.length;
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

/// [m] with its keys in order, so two equal maps encode alike.
Map<String, Object?> _sorted(Map<String, Object?> m) => {
  for (final k in m.keys.toList()..sort()) k: m[k],
};
