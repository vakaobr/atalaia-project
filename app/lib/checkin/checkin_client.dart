// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The field controller's check-in endpoints (protocol/checkin.md): the
/// field's info, checking in with a field identity, the player token and its
/// refresh, the player's own check-in and declaration, leaving; and for
/// marshals the "replicas to chrono" list, signed readings and their key.
///
/// Requests go to the pinned field's https addresses in order
/// ([FieldHttp]), trusting the field's CA only (field_trust.dart); tests
/// replace [FieldHttp] with a fake controller.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import '../chrono/replica.dart' show Replica;
import '../protocol/apd.dart';
import 'apd_fields.dart' show apdCountryOf;
import 'field_route.dart';
import 'field_trust.dart';

/// One answer: its status and JSON body.
final class FieldResponse {
  const FieldResponse(this.status, this.body, {this.bytes});
  final int status;
  final Object? body;

  /// The raw body of an image answer (a level's plan, `image/*`); null for
  /// everything else, which is JSON in [body].
  final Uint8List? bytes;

  bool get ok => status >= 200 && status < 300;

  Map<String, Object?> get json =>
      body is Map ? (body! as Map).cast<String, Object?>() : const {};

  /// The controller's error text (FastAPI's "detail").
  String get detail {
    final d = json['detail'];
    return d is String ? d : 'HTTP $status';
  }
}

/// A level's plan is at most 4 MB on the controller (ML-1); the phone refuses
/// more.
const _imageMaxBytes = 4 * 1024 * 1024;

abstract interface class FieldHttp {
  Future<FieldResponse> send(
    String method,
    String path, {
    Object? body,
    String? token,
  });
}

/// Opens a TLS connection to [url] with the field's CA alone, and closes it:
/// the race's probe (a "does this address answer, and is it the field's
/// controller"). The same security context as every request, so an address
/// held by another device fails here exactly as it would later.
typedef FieldProbe =
    Future<void> Function(PinnedField field, Uri url, RaceCancel cancel);

Future<void> ioProbe(PinnedField field, Uri url, RaceCancel cancel) async {
  final task = await SecureSocket.startConnect(
    url.host,
    url.hasPort ? url.port : 443,
    context: field.securityContext(),
  );
  cancel.onCancel(task.cancel);
  final socket = await task.socket;
  socket.destroy();
}

/// [FieldHttp] over dart:io: the field's addresses raced (check-R1), the one
/// that answered first remembered and tried first, its CA only.
class IoFieldHttp implements FieldHttp {
  IoFieldHttp(this.field, {FieldRoutes? routes, FieldProbe? probe})
    : routes = routes ?? FieldRoutes(),
      _probe = probe ?? ioProbe,
      _client = field.client();

  final PinnedField field;
  final FieldRoutes routes;
  final FieldProbe _probe;
  final HttpClient _client;

  Future<FieldResponse> _request(
    String url,
    String method,
    String path,
    Object? body,
    String? token,
  ) async {
    final req = await _client.openUrl(method, Uri.parse('$url/api/v1$path'));
    req.headers.set('Accept', 'application/json');
    if (token != null) req.headers.set('Authorization', 'Bearer $token');
    if (body != null) {
      req.headers.contentType = ContentType.json;
      req.add(utf8.encode(jsonEncode(body)));
    }
    final res = await req.close().timeout(const Duration(seconds: 15));
    if (res.headers.contentType?.primaryType == 'image') {
      final out = BytesBuilder(copy: false);
      await for (final chunk in res.timeout(const Duration(seconds: 15))) {
        out.add(chunk);
        if (out.length > _imageMaxBytes) {
          return FieldResponse(res.statusCode, null); // no plan: too large
        }
      }
      return FieldResponse(res.statusCode, null, bytes: out.takeBytes());
    }
    final text = await utf8.decodeStream(res);
    Object? json;
    try {
      json = text.isEmpty ? null : jsonDecode(text);
    } on FormatException {
      json = null;
    }
    return FieldResponse(res.statusCode, json);
  }

  @override
  Future<FieldResponse> send(
    String method,
    String path, {
    Object? body,
    String? token,
  }) async {
    final key = field.fieldId;
    // The address that answered last goes first, on its own: no probe.
    final known = routes.winner(key, field.lastUrl);
    String? failed;
    if (known != null && field.urls.contains(known)) {
      try {
        return _answered(
          key,
          known,
          await _request(known, method, path, body, token),
        );
      } on Object catch (e) {
        routes.noteFailure(key, routes.failure(known, e));
        failed = known;
      }
    }
    // First use, or it failed: race the addresses, the failed one last.
    String url;
    try {
      final r = await routes.choose<void>(
        key,
        field.urls,
        (u, cancel) => _probe(field, Uri.parse(u), cancel),
        seed: field.lastUrl,
        avoid: failed,
      );
      url = r.$1;
    } on RaceFailed catch (e) {
      throw CheckinException(
        0,
        'the field controller is out of reach '
        '(${e.failures.map((f) => '${f.kind.name} ${f.url}').join(', ')})',
      );
    }
    try {
      return _answered(
        key,
        url,
        await _request(url, method, path, body, token),
      );
    } on Object catch (e) {
      final f = routes.failure(url, e);
      routes.noteFailure(key, f);
      throw CheckinException(
        0,
        'the field controller is out of reach (${f.kind.name} $url)',
      );
    }
  }

  /// The address answered: it is the winner; a status of 400 or more is kept
  /// as the last failure (kind http).
  FieldResponse _answered(String key, String url, FieldResponse r) {
    routes.succeeded(key, url);
    if (r.status >= 400) {
      routes.noteFailure(
        key,
        routes.failure(
          url,
          RouteError(FailKind.http, 'HTTP ${r.status}', status: r.status),
        ),
      );
    }
    return r;
  }

  void close() => _client.close(force: true);
}

class CheckinException implements Exception {
  CheckinException(this.status, this.message, [this.reasons = const []]);

  /// The HTTP status, or 0 when the controller did not answer.
  final int status;
  final String message;

  /// For refused readings: each record's index and reason.
  final List<Map<String, Object?>> reasons;

  bool get offline => status == 0;

  @override
  String toString() => 'CheckinException($status): $message';
}

/// A replica declared for a game (protocol/checkin.md "Declarations"); the
/// state and reading come from the controller.
final class Declaration {
  const Declaration({
    required this.declarationId,
    required this.type,
    required this.replicaClass,
    this.replicaId,
    this.makeModel,
    this.state = 'pending',
    this.readingId,
    this.refusedToday = false,
  });

  final String declarationId;
  final String? replicaId;
  final String type;
  final String replicaClass;
  final String? makeModel;
  final String state;
  final String? readingId;
  final bool refusedToday;

  /// The id a marshal's phone registers this replica under: the field's own
  /// once it has one, else the declaration's (a lowercase UUID, made by the
  /// player's app), so the QR label `ATL-` + its first eight characters is
  /// known before the replica is chronographed, to the player's app and to
  /// the console alike. Null for a declaration id that is no UUID.
  String? get registryId =>
      replicaId ?? (Replica.isId(declarationId) ? declarationId : null);

  Map<String, Object?> toRequest() => {
    'declaration_id': declarationId,
    'replica_id': ?replicaId,
    'type': type,
    'class': replicaClass,
    'make_model': ?makeModel,
  };

  static Declaration fromJson(Map<String, Object?> j) => Declaration(
    declarationId: j['declaration_id']! as String,
    replicaId: j['replica_id'] as String?,
    type: j['type']! as String,
    replicaClass: j['class']! as String,
    makeModel: j['make_model'] as String?,
    state: (j['state'] as String?) ?? 'pending',
    readingId: j['reading_id'] as String?,
    refusedToday: j['refused_today'] == true,
  );
}

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
final _uuid = RegExp(
  r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
);
final _class = RegExp(r'^[a-z0-9_]{1,32}$');

/// The controller's rules for a declaration as the app sends it (null: fine).
String? declarationProblem(Map<String, Object?> d) {
  const allowed = {
    'declaration_id',
    'replica_id',
    'type',
    'class',
    'make_model',
  };
  if (d.keys.any((k) => !allowed.contains(k))) return 'unknown fields';
  final id = d['declaration_id'];
  if (id is! String || !_uuid.hasMatch(id)) return 'declaration_id';
  final rid = d['replica_id'];
  if (rid != null && (rid is! String || !_uuid.hasMatch(rid))) {
    return 'replica_id';
  }
  if (!replicaTypes.contains(d['type'])) return 'type';
  final c = d['class'];
  if (c is! String || !_class.hasMatch(c)) return 'class';
  final mm = d['make_model'];
  if (mm != null) {
    if (mm is! String || mm.isEmpty || mm.runes.length > 64) {
      return 'make_model';
    }
    if (mm.runes.any((r) => r < 0x20 || (r >= 0x7f && r <= 0x9f))) {
      return 'make_model';
    }
  }
  return null;
}

/// GET /api/v1/checkin.
final class FieldInfo {
  FieldInfo(this.json);
  final Map<String, Object?> json;

  Map<String, Object?> get _field =>
      (json['field'] as Map?)?.cast<String, Object?>() ?? const {};
  Map<String, Object?> get settings =>
      (json['settings'] as Map?)?.cast<String, Object?>() ?? const {};
  Map<String, Object?> get notice =>
      (json['notice'] as Map?)?.cast<String, Object?>() ?? const {};

  String get fieldId => '${_field['id']}';
  String get fieldName => '${_field['name']}';
  String? get operator => _field['operator'] as String?;
  int get noticeVersion => (notice['version'] as int?) ?? 1;
  String noticeText(String lang) =>
      (notice[lang] as String?) ?? (notice['en'] as String?) ?? '';
  String get federation => (settings['federation'] as String?) ?? 'off';
  String get federationLabel =>
      (settings['federation_label'] as String?) ?? 'FPA';

  /// The field's APD rule (protocol/apd.md); the default from an older
  /// controller or one this build cannot read.
  ApdRule get apdRule => ApdRule.lenient(settings['apd']);

  /// The field's country (protocol/apd.md): `PT` for an older controller, which
  /// only knew Portugal's APDs; null when the controller has none set.
  String? get country => apdCountryOf(settings);

  /// The APDs to offer: the controller's list for its country and the field's
  /// own entries.
  List<ApdEntry> get apds {
    final raw = json['apds'];
    if (raw is! List) return const [];
    return [
      for (final e in raw)
        if (e is Map)
          ApdEntry(
            id: '${e['id']}',
            name: '${e['name']}',
            shortName: '${e['short_name'] ?? e['name']}',
            website: e['website'] as String?,
            country: e['country'] as String?,
          ),
    ];
  }

  int get maxReplicas => (settings['max_replicas'] as int?) ?? 5;
  String get confirm => (settings['confirm'] as String?) ?? 'auto';

  /// The id of the limit template the controller judges with (its
  /// `[checkin] limit_template`), and its name; null from an older one.
  String? get limitsId => (json['limits'] as Map?)?['id'] as String?;
  String? get limitsName => (json['limits'] as Map?)?['name'] as String?;

  List<String> get classes => [
    for (final c in ((json['limits'] as Map?)?['classes'] as List?) ?? const [])
      '$c',
  ];

  List<Map<String, Object?>> get games => [
    for (final g in (json['games'] as List?) ?? const [])
      if (g is Map) g.cast<String, Object?>(),
  ];
}

/// The answer to a check-in or a token refresh.
final class CheckinTicket {
  CheckinTicket(this.json);
  final Map<String, Object?> json;

  int get gameId => json['game_id']! as int;
  String get playerId => json['player_id']! as String;
  String get token => json['token']! as String;
  int get exp => json['exp']! as int;
  String get status => json['status']! as String;
  String? get team => json['team'] as String?;
  int get squad => (json['squad'] as int?) ?? 0;
  String get role => (json['role'] as String?) ?? 'player';
}

class CheckinClient {
  CheckinClient(this.http);
  final FieldHttp http;

  Future<Map<String, Object?>> _call(
    String method,
    String path, {
    Object? body,
    String? token,
  }) async {
    final r = await http.send(method, path, body: body, token: token);
    if (!r.ok) {
      final reasons = [
        for (final x in (r.json['reasons'] as List?) ?? const [])
          if (x is Map) x.cast<String, Object?>(),
      ];
      throw CheckinException(r.status, r.detail, reasons);
    }
    return r.json;
  }

  Future<FieldInfo> info() async => FieldInfo(await _call('GET', '/checkin'));

  Future<CheckinTicket> checkIn({
    required int gameId,
    required String playerId,
    required String secret,
    required String displayName,
    required int noticeVersion,
    String? federationNumber,
    String? apdId,
    String? membershipExpires,
    String? teamPreference,
    List<Declaration>? replicas,
    String? registrationId,
    String? registrationTicket,
    bool? sharePosition,
  }) async => CheckinTicket(
    await _call(
      'POST',
      '/checkin',
      body: {
        // A registration on the field's site server and its ticket, both or
        // neither (decision S16-8).
        if (registrationId != null && registrationTicket != null) ...{
          'registration_id': registrationId,
          'ticket': registrationTicket,
        },
        'game_id': gameId,
        'player_id': playerId,
        'player_secret': secret,
        'display_name': displayName,
        'notice_version': noticeVersion,
        'federation_number': ?federationNumber,
        'membership_number': ?federationNumber,
        'apd_id': ?apdId,
        'membership_expires': ?membershipExpires,
        'team_preference': ?teamPreference,
        // The player's own, separate choice (an unticked box): decision LEG-12.
        'share_position': ?sharePosition,
        if (replicas != null)
          'replicas': [for (final d in replicas) d.toRequest()],
      },
    ),
  );

  Future<CheckinTicket> refresh(String token) async =>
      CheckinTicket(await _call('POST', '/checkin/token', token: token));

  Future<Map<String, Object?>> me(String token) =>
      _call('GET', '/checkin/me', token: token);

  Future<List<Declaration>> putReplicas(
    String token,
    List<Declaration> replicas,
  ) async {
    final j = await _call(
      'PUT',
      '/checkin/me/replicas',
      token: token,
      body: {
        'replicas': [for (final d in replicas) d.toRequest()],
      },
    );
    return [
      for (final d in (j['declarations'] as List?) ?? const [])
        Declaration.fromJson((d as Map).cast<String, Object?>()),
    ];
  }

  Future<void> leave(String token) =>
      _call('DELETE', '/checkin/me', token: token);

  Future<Map<String, Object?>> chronoList(String token, int gameId) =>
      _call('GET', '/games/$gameId/chrono-list', token: token);

  /// A game as staff see it (its `teams`, `mode_id` and `state`).
  Future<Map<String, Object?>> game(String token, int gameId) =>
      _call('GET', '/games/$gameId', token: token);

  /// One signed player tag (decision TW-1, protocol/nfc-tag.md): the
  /// controller signs it with the game's key, which never leaves it; the
  /// answer's `ndef` (hex) is the record to write. Staff only.
  Future<Map<String, Object?>> playerTag(
    String token,
    int gameId, {
    required String player,
    String? team,
  }) => _call(
    'POST',
    '/games/$gameId/tags',
    token: token,
    body: {'player': player, 'team': ?team},
  );

  /// The player turns sharing their position with the game on or off, any
  /// time (an older controller has no such route: 404 or 405).
  Future<Map<String, Object?>> setPositionSharing(String token, bool on) =>
      _call(
        'PUT',
        '/checkin/me/position-sharing',
        token: token,
        body: {'share_position': on},
      );

  Future<Map<String, Object?>> manualCheckin(
    String token,
    int gameId,
    Map<String, Object?> body,
  ) => _call('POST', '/games/$gameId/checkins', token: token, body: body);

  /// The marshal ticks "card seen, matches": the controller records who and
  /// when, stores the verdict, erases the number and lets the player in
  /// (protocol/apd.md, "The card check").
  Future<Map<String, Object?>> cardSeen(String token, int gameId, String pid) =>
      _call(
        'PATCH',
        '/games/$gameId/checkins/$pid',
        token: token,
        body: {'federation_seen': true},
      );

  Future<Map<String, Object?>> confirm(String token, int gameId, String pid) =>
      _call(
        'PATCH',
        '/games/$gameId/checkins/$pid',
        token: token,
        body: {'status': 'checked_in'},
      );

  /// The marshal's phone registers the key that signs its readings, for the
  /// id the GM's list gave this player (decision MR-2): the controller
  /// answers 403 when the player is not on the list.
  Future<Map<String, Object?>> registerMarshalKey(
    String token, {
    required String publicKeyBase64,
    String? marshalId,
  }) => _call(
    'PUT',
    '/checkin/me/marshal-key',
    token: token,
    body: {'marshal_id': ?marshalId, 'public_key': publicKeyBase64},
  );

  /// One series of signed readings (protocol/checkin.md).
  Future<Map<String, Object?>> uploadReadings(
    String token,
    List<Map<String, Object?>> readings, {
    String? declarationId,
    Map<String, Object?>? replica,
  }) => _call(
    'POST',
    '/chrono/readings',
    token: token,
    body: {
      'readings': readings,
      'declaration_id': ?declarationId,
      'replica': ?replica,
    },
  );

  /// The field's indoor beacons as a player may know them (each one's `id`
  /// and `uuid`, nothing about the building) and the interval to report them
  /// at (`ble_interval_s`): what the phone listens for (ADR-P3-6).
  Future<Map<String, Object?>> fetchBeacons(String token) =>
      _call('GET', '/beacons', token: token);

  Future<Map<String, Object?>> reportPositions(
    String token,
    List<Map<String, Object?>> reports,
  ) => _call('POST', '/positions', token: token, body: {'reports': reports});
}
