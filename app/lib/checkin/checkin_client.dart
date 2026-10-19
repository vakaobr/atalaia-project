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

import 'field_trust.dart';

/// One answer: its status and JSON body.
final class FieldResponse {
  const FieldResponse(this.status, this.body);
  final int status;
  final Object? body;

  bool get ok => status >= 200 && status < 300;

  Map<String, Object?> get json =>
      body is Map ? (body! as Map).cast<String, Object?>() : const {};

  /// The controller's error text (FastAPI's "detail").
  String get detail {
    final d = json['detail'];
    return d is String ? d : 'HTTP $status';
  }
}

abstract interface class FieldHttp {
  Future<FieldResponse> send(
    String method,
    String path, {
    Object? body,
    String? token,
  });
}

/// [FieldHttp] over dart:io: the field's addresses in order, its CA only.
class IoFieldHttp implements FieldHttp {
  IoFieldHttp(this.field) : _client = field.client();

  final PinnedField field;
  final HttpClient _client;
  int _working = 0;

  @override
  Future<FieldResponse> send(
    String method,
    String path, {
    Object? body,
    String? token,
  }) async {
    Object? last;
    final urls = field.urls;
    for (var i = 0; i < urls.length; i++) {
      final at = (_working + i) % urls.length;
      try {
        final req = await _client.openUrl(
          method,
          Uri.parse('${urls[at]}/api/v1$path'),
        );
        req.headers.set('Accept', 'application/json');
        if (token != null) req.headers.set('Authorization', 'Bearer $token');
        if (body != null) {
          req.headers.contentType = ContentType.json;
          req.add(utf8.encode(jsonEncode(body)));
        }
        final res = await req.close().timeout(const Duration(seconds: 15));
        final text = await utf8.decodeStream(res);
        _working = at;
        Object? json;
        try {
          json = text.isEmpty ? null : jsonDecode(text);
        } on FormatException {
          json = null;
        }
        return FieldResponse(res.statusCode, json);
      } on Object catch (e) {
        last = e; // the next address
      }
    }
    throw CheckinException(0, 'the field controller is out of reach ($last)');
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
  int get maxReplicas => (settings['max_replicas'] as int?) ?? 5;
  String get confirm => (settings['confirm'] as String?) ?? 'auto';

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
    String? teamPreference,
    List<Declaration>? replicas,
  }) async => CheckinTicket(
    await _call(
      'POST',
      '/checkin',
      body: {
        'game_id': gameId,
        'player_id': playerId,
        'player_secret': secret,
        'display_name': displayName,
        'notice_version': noticeVersion,
        'federation_number': ?federationNumber,
        'team_preference': ?teamPreference,
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

  Future<Map<String, Object?>> manualCheckin(
    String token,
    int gameId,
    Map<String, Object?> body,
  ) => _call('POST', '/games/$gameId/checkins', token: token, body: body);

  Future<Map<String, Object?>> confirm(String token, int gameId, String pid) =>
      _call(
        'PATCH',
        '/games/$gameId/checkins/$pid',
        token: token,
        body: {'status': 'checked_in'},
      );

  Future<Map<String, Object?>> registerMarshalKey(
    String token, {
    required String marshalId,
    required String name,
    required String publicKeyBase64,
  }) => _call(
    'PUT',
    '/checkin/me/marshal-key',
    token: token,
    body: {
      'marshal_id': marshalId,
      'name': name,
      'public_key': publicKeyBase64,
    },
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

  Future<Map<String, Object?>> reportPositions(
    String token,
    List<Map<String, Object?>> reports,
  ) => _call('POST', '/positions', token: token, body: {'reports': reports});
}
