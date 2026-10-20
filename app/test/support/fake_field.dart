// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A stand-in for a field controller's check-in API (protocol/checkin.md),
/// enough for the app's check-in, declaration, marshal queue and position
/// tests: the same paths, bodies and status codes as
/// controller/atalaia_controller/checkin.py, with its state in memory. The
/// controller's own tests check the real rules; these check that the app
/// sends and shows them right.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/protocol/checkin_poster.dart';
import 'package:crypto/crypto.dart';

class FakeField {
  FakeField({
    this.fieldId = 'campo-norte',
    this.fieldName = 'Campo Norte',
    Uint8List? der,
    String? pem,
  }) : der =
           der ?? Uint8List.fromList(utf8.encode('atalaia test field CA, DER')),
       _customPem = pem;

  final String fieldId;
  final String fieldName;

  /// The CA's DER bytes (the poster's fingerprint is their SHA-256) and PEM.
  final Uint8List der;
  final String? _customPem;

  String get pem =>
      _customPem ??
      '-----BEGIN CERTIFICATE-----\n${base64.encode(der)}\n'
          '-----END CERTIFICATE-----\n';

  Uint8List get sha256Bytes => Uint8List.fromList(sha256.convert(der).bytes);

  final urls = ['https://10.0.2.2:8443'];
  String? wifiSsid = 'Atalaia';

  String posterText({Uint8List? ca}) => posterToText(
    encodePoster(
      CheckinPoster(
        fieldId: fieldId,
        fieldName: fieldName,
        urls: urls,
        caSha256: ca ?? sha256Bytes,
        wifiSsid: wifiSsid,
      ),
    ),
  );

  // --- what the controller holds ---------------------------------------------
  var federation = 'off';
  var confirm = 'auto';
  var notice = 1;
  final games = <Map<String, Object?>>[
    {
      'game_id': 42,
      'name': 'Domingo de manhã',
      'state': 'ready',
      'teams': ['red', 'blue'],
    },
  ];
  final rows = <String, Map<String, Object?>>{};
  final secrets = <String, String>{};
  final tokens = <String, String>{};
  final readings = <Map<String, Object?>>[];
  final positions = <Map<String, Object?>>[];
  final marshalKeys = <String, String>{};
  final requests = <String>[];
  var caFetches = 0;
  var offline = false;
  var _tokenN = 0;

  Future<String> fetchCa(Uri url) async {
    caFetches++;
    if (offline) throw StateError('unreachable');
    return pem;
  }

  FieldHttp http(PinnedField field) => _FakeHttp(this);

  String _token(String pid) {
    final t = 'apt1.test-${++_tokenN}-$pid';
    tokens[t] = pid;
    return t;
  }

  Map<String, Object?> _ticket(String pid) {
    final r = rows[pid]!;
    return {
      'game_id': 42,
      'player_id': pid,
      'token': _token(pid),
      'exp': 4102444800,
      'status': r['status'],
      'team': r['team'],
      'squad': r['squad'],
      'role': r['role'],
    };
  }

  /// The GM's change: a new role or team for [pid].
  void assign(String pid, {String? role, String? team, int? squad}) {
    if (role != null) rows[pid]!['role'] = role;
    if (team != null) rows[pid]!['team'] = team;
    if (squad != null) rows[pid]!['squad'] = squad;
  }

  /// A marshal's signed reading changing a declaration's state.
  void judge(String declarationId, String state) {
    for (final r in rows.values) {
      for (final d
          in (r['declarations']! as List).cast<Map<String, Object?>>()) {
        if (d['declaration_id'] == declarationId) d['state'] = state;
      }
    }
  }

  FieldResponse handle(
    String method,
    String path,
    Object? body,
    String? token,
  ) {
    requests.add('$method $path');
    final b = body is Map ? body.cast<String, Object?>() : <String, Object?>{};
    final who = token == null ? null : tokens[token];
    FieldResponse err(int status, String detail) =>
        FieldResponse(status, {'detail': detail});
    switch ('$method $path') {
      case 'GET /checkin':
        return FieldResponse(200, {
          'version': 1,
          'field': {'id': fieldId, 'name': fieldName, 'operator': 'Clube'},
          'notice': {
            'version': notice,
            'pt': '**Check-in no campo: os teus dados** O nome fica 30 dias.',
            'en': '**Checking in at the field: your data** Kept 30 days.',
          },
          'settings': {
            'confirm': confirm,
            'federation': federation,
            'federation_label': 'FPA',
            'max_replicas': 5,
            'chrono_valid_for': 'day',
          },
          'limits': {
            'classes': ['cqb', 'dmr', 'rifle', 'sniper'],
          },
          'games': games,
        });
      case 'POST /checkin':
        final pid = b['player_id']! as String;
        if (b['notice_version'] != notice) return err(409, 'notice changed');
        final known = secrets[pid];
        if (known != null && known != b['player_secret']) {
          return err(409, 'someone else');
        }
        if (federation == 'required' && b['federation_number'] == null) {
          return err(400, 'federation_number: required');
        }
        secrets[pid] = b['player_secret']! as String;
        final created = !rows.containsKey(pid);
        final row = rows.putIfAbsent(
          pid,
          () => {
            'player_id': pid,
            'status': confirm == 'auto' ? 'checked_in' : 'pending',
            'role': 'player',
            'team': null,
            'squad': 0,
            'declarations': <Map<String, Object?>>[],
          },
        );
        row['display_name'] = b['display_name'];
        row['federation_number'] = b['federation_number'];
        // A site server registration's id and ticket (decision S16-8).
        row['registration_id'] = b['registration_id'];
        row['registration_ticket'] = b['ticket'];
        if (b['replicas'] is List) _declare(row, b['replicas']! as List);
        return FieldResponse(created ? 201 : 200, _ticket(pid));
      case 'POST /checkin/token':
        if (who == null) return err(401, 'no');
        return FieldResponse(200, _ticket(who));
      case 'GET /checkin/me':
        if (who == null || rows[who]!['status'] == 'left') {
          return err(401, 'no');
        }
        final r = rows[who]!;
        return FieldResponse(200, {...r, 'stale_token': false, 'game_id': 42});
      case 'PUT /checkin/me/replicas':
        if (who == null) return err(401, 'no');
        _declare(rows[who]!, b['replicas']! as List);
        return FieldResponse(200, {'declarations': rows[who]!['declarations']});
      case 'DELETE /checkin/me':
        if (who == null) return err(401, 'no');
        rows[who]!
          ..['status'] = 'left'
          ..['display_name'] = null;
        return FieldResponse(200, {'status': 'left'});
      case 'PUT /checkin/me/marshal-key':
        if (who == null || rows[who]!['role'] != 'marshal') {
          return err(403, 'marshals only');
        }
        marshalKeys[b['marshal_id']! as String] = b['public_key']! as String;
        return FieldResponse(200, b);
      case 'GET /games/42/chrono-list':
        if (who == null || rows[who]!['role'] != 'marshal') {
          return err(403, 'staff only');
        }
        final players = [
          for (final r in rows.values)
            if ((r['declarations']! as List).isNotEmpty)
              {
                'player_id': r['player_id'],
                'display_name': r['display_name'],
                'status': r['status'],
                'team': r['team'],
                'declarations': r['declarations'],
              },
        ];
        final counts = {'pending': 0, 'passed': 0, 'refused': 0};
        for (final p in players) {
          for (final d
              in (p['declarations']! as List).cast<Map<String, Object?>>()) {
            counts[d['state']! as String] = (counts[d['state']] ?? 0) + 1;
          }
        }
        return FieldResponse(200, {
          'game_id': 42,
          'counts': counts,
          'players': players,
        });
      case 'POST /chrono/readings':
        if (who == null || rows[who]!['role'] != 'marshal') {
          return err(403, 'marshals only');
        }
        final rs = (b['readings']! as List).cast<Map<String, Object?>>();
        if (rs.any((r) => r['signature'] == null)) {
          return FieldResponse(422, {
            'detail': 'refused',
            'reasons': [
              {'index': 0, 'reason': 'unsigned'},
            ],
          });
        }
        readings.addAll(rs);
        final first = rs.first;
        final energy = rs
            .map((r) => r['energy_j']! as num)
            .reduce((a, c) => a > c ? a : c);
        final pass = energy <= 1.14;
        for (final r in rows.values) {
          for (final d
              in (r['declarations']! as List).cast<Map<String, Object?>>()) {
            if (b['declaration_id'] != null &&
                d['declaration_id'] == b['declaration_id']) {
              d['replica_id'] = first['replica_id'];
            }
            if (d['replica_id'] == first['replica_id']) {
              d['state'] = pass ? 'passed' : 'refused';
            }
          }
        }
        return FieldResponse(200, {
          'outcome': pass ? 'pass' : 'fail',
          'stored': rs.length,
          'duplicate': false,
        });
      case 'POST /games/42/checkins':
        final pid = 'p-hand${rows.length.toString().padLeft(8, 'a')}';
        rows[pid] = {
          'player_id': pid,
          'status': 'checked_in',
          'role': 'player',
          'display_name': b['display_name'],
          'declarations': <Map<String, Object?>>[],
        };
        return FieldResponse(201, rows[pid]);
      case 'POST /positions':
        if (who == null) return err(401, 'no');
        positions.addAll((b['reports']! as List).cast<Map<String, Object?>>());
        return FieldResponse(200, {
          'stored': (b['reports']! as List).length,
          'interval_s': 10,
        });
    }
    return err(404, 'not here');
  }

  void _declare(Map<String, Object?> row, List<Object?> items) {
    final old = {
      for (final d
          in (row['declarations']! as List).cast<Map<String, Object?>>())
        d['declaration_id']: d,
    };
    row['declarations'] = [
      for (final i in items.cast<Map<String, Object?>>())
        {...i, 'state': (old[i['declaration_id']]?['state']) ?? 'pending'},
    ];
  }
}

class _FakeHttp implements FieldHttp {
  _FakeHttp(this.field);
  final FakeField field;

  @override
  Future<FieldResponse> send(
    String method,
    String path, {
    Object? body,
    String? token,
  }) async {
    if (field.offline) throw CheckinException(0, 'offline');
    // The body goes through JSON, as on the wire.
    final b = body == null ? null : jsonDecode(jsonEncode(body));
    final r = field.handle(method, path, b, token);
    return FieldResponse(r.status, jsonDecode(jsonEncode(r.body)));
  }
}
