// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Field check-in on the Android field controller (controller_checkin.dart,
// slice S5 of PE24) beyond the shared contract cases (api_contract_test.dart):
// the poster's text once the phone has a field CA, the CSV export, the rate
// limit, spot checks, erasing a player and the retention purge, as the Pi's
// test_checkin.py, test_checkin_poster.py and test_chrono_list.py check them.

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/chrono/reading.dart';
import 'package:atalaia_app/chrono/record_signer.dart';
import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_checkin.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_positions.dart';
import 'package:atalaia_app/protocol/checkin_poster.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/recording_radio.dart';

/// 2027-01-15 10:00:00 UTC, as the Pi's tests' T0.
const t0 = 1800007200.0;

String _secret(int n) =>
    base64Url.encode(List.filled(32, n)).replaceAll('=', '');

void main() {
  late double wall;
  late ControllerEngine engine;
  late ControllerCheckin svc;
  late ControllerApi api;
  final limits = File(
    'lib/chrono/limit_templates/portugal.yaml',
  ).readAsStringSync();

  setUp(() {
    wall = t0;
    engine = ControllerEngine(
      transport: RecordingRadio(),
      wallSeconds: () => wall,
    );
    svc = ControllerCheckin(
      engine,
      CheckinConfig(limitsYaml: limits, utcDay: true),
    );
    ControllerPositions(engine);
    api = ControllerApi(engine, gmToken: 'g', readToken: 'r');
  });

  ApiResponse call(
    String method,
    String path, {
    String? token = 'g',
    Object? body,
    String client = 'local',
  }) => api.handle(
    method,
    Uri.parse(path),
    authorization: token == null ? null : 'Bearer $token',
    body: body == null ? '' : jsonEncode(body),
    client: client,
  );

  Future<ApiResponse> callAsync(String path, String token, Object body) =>
      api.handleAsync(
        'POST',
        Uri.parse(path),
        authorization: 'Bearer $token',
        body: jsonEncode(body),
      );

  int newGame() {
    final r = call(
      'POST',
      '/api/v1/games',
      body: {
        'name': 'Domingo',
        'mode_id': 'org.atalaia.domination',
        'teams': ['red', 'blue'],
      },
    );
    expect(r.status, 201, reason: '${r.body}');
    return (r.body! as Map)['id']! as int;
  }

  var players = 0;
  Map<String, Object?> checkIn(
    int gid, {
    String name = 'Falcão',
    List<Object?>? replicas,
    String client = 'local',
    int status = 201,
  }) {
    players++;
    final pid = 'p-${'abcdefghijklmnopqrstuvwxyz'[players % 26] * 12}';
    final r = call(
      'POST',
      '/api/v1/checkin',
      token: null,
      client: client,
      body: {
        'game_id': gid,
        'player_id': pid,
        'player_secret': _secret(players),
        'display_name': name,
        'notice_version': 1,
        'replicas': ?replicas,
      },
    );
    expect(r.status, status, reason: '${r.body}');
    return (r.body! as Map).cast<String, Object?>();
  }

  test('the poster text once the phone has a field CA, and its problems', () {
    svc
      ..caSha256 = Uint8List.fromList(List.generate(32, (i) => i))
      ..defaultUrls = ['https://10.42.0.1:8443'];
    final p = svc.poster();
    expect(p['problem_code'], isNull);
    expect(p['ca_short'], '0001 0203 0405 0607');
    final poster = parsePoster(p['text']! as String);
    expect(poster.fieldId, 'field');
    expect(poster.urls, ['https://10.42.0.1:8443']);
    expect(poster.gameId, isNull);
    final gid = newGame();
    expect(svc.setPoster({'game_id': gid})['text'], isNotNull);
    expect(parsePoster(svc.poster()['text']! as String).gameId, gid);
    expect(svc.setPoster({'field_name': 'N' * 48})['problem_code'], isNull);
    svc.defaultUrls = [
      for (var i = 0; i < 3; i++) 'https://${'a' * 42}$i.example:8443',
    ];
    expect(svc.poster()['problem_code'], 'too_long');
    svc.defaultUrls = [];
    expect(svc.poster()['problem_code'], 'no_address');
  });

  test('ten check-ins a minute from one address', () {
    final gid = newGame();
    for (var i = 0; i < 10; i++) {
      checkIn(gid, client: '10.0.0.5');
    }
    checkIn(gid, client: '10.0.0.5', status: 429);
    checkIn(gid, client: '10.0.0.6');
  });

  test('the CSV export: one line per declaration, no formulas', () {
    final gid = newGame();
    checkIn(
      gid,
      name: '=1+1',
      replicas: [
        {
          'declaration_id': '11111111-1111-4111-8111-111111111111',
          'type': 'aeg',
          'class': 'rifle',
          'make_model': 'Tokyo, "Marui"',
        },
      ],
    );
    checkIn(gid, name: 'Corvo');
    expect(
      call('GET', '/api/v1/games/$gid/checkins.csv', token: 'r').status,
      403,
    );
    final r = call('GET', '/api/v1/games/$gid/checkins.csv');
    expect(r.status, 200);
    expect(r.contentType, 'text/csv; charset=utf-8');
    expect(r.headers['Content-Disposition'], contains('checkins-$gid.csv'));
    final lines = r.text!.split('\r\n');
    expect(lines.first, startsWith('﻿player_id,display_name,status,'));
    expect(lines[1], contains(",'=1+1,checked_in,"));
    expect(lines[1], contains(',"Tokyo, ""Marui""",pending'));
    expect(lines[2], contains(',Corvo,checked_in,'));
    expect(lines[2], endsWith(',,,,,,'));
  });

  test('spot checks: pass, warn over the check-in plus 5%, fail over the '
      'limit; violations are logged', () async {
    final gid = newGame();
    const replica = '22222222-2222-4222-8222-222222222222';
    final me = checkIn(
      gid,
      replicas: [
        {
          'declaration_id': '33333333-3333-4333-8333-333333333333',
          'replica_id': replica,
          'type': 'aeg',
          'class': 'rifle',
        },
      ],
    );
    final key = await MarshalKey.fromSeed(List.filled(32, 7));
    svc.registerMarshal({
      'marshal_id': 'm-ana',
      'name': 'Ana',
      'public_key': base64.encode(key.publicKey),
    });
    Future<Map<String, Object?>> series(
      ReadingType type,
      double v, {
      String? ref,
    }) async {
      final reading = await signReading(
        ChronoReading.measure(
          replicaId: replica,
          playerId: me['player_id']! as String,
          type: type,
          velocityMps: v,
          bbWeightG: 0.2,
          chronoId: 'chrono-1',
          marshalId: 'm-ana',
          marshalName: 'Ana',
          fieldId: 'field',
          timestamp: DateTime.utc(2027, 1, 15, 10),
          refReadingId: ref,
        ),
        key,
      );
      final r = await callAsync('/api/v1/chrono/readings', 'g', {
        'readings': [reading.toJson()],
      });
      expect(r.status, 200, reason: '${r.body}');
      return (r.body! as Map).cast<String, Object?>();
    }

    expect((await series(ReadingType.checkin, 90))['outcome'], 'pass');
    expect((await series(ReadingType.spotcheck, 91))['outcome'], 'pass');
    expect((await series(ReadingType.spotcheck, 93))['outcome'], 'warn');
    final fail = await series(ReadingType.spotcheck, 110);
    expect(fail['outcome'], 'fail');
    expect(fail['changed'], isEmpty); // a spot check leaves the list alone
    final log = engine.log(gid);
    expect(
      [for (final e in log) e['type']],
      [
        'player.checkin',
        'chrono.checkin',
        'chrono.spotcheck',
        'chrono.spotcheck',
        'chrono.violation',
        'chrono.spotcheck',
        'chrono.violation',
      ],
    );
    expect(log[4]['prio'], 'critical');
    expect((log[4]['data']! as Map)['limit_j'], 1.14);
    expect(
      () => api.handle(
        'POST',
        Uri.parse('/api/v1/chrono/readings'),
        authorization: 'Bearer g',
        body: '{"readings": []}',
      ),
      throwsStateError,
    );
  });

  test('erasing a player: the check-in, the identity and, if asked, the '
      'readings', () {
    final gid = newGame();
    final me = checkIn(gid);
    final pid = me['player_id']! as String;
    expect(call('DELETE', '/api/v1/players/$pid', token: 'r').status, 403);
    final r = call('DELETE', '/api/v1/players/$pid?chrono=1');
    expect(r.body, {'player_id': pid, 'erased': true, 'readings_deleted': 0});
    expect(svc.checkinRow(gid, pid), isNull);
    expect(
      call('GET', '/api/v1/whoami', token: me['token']! as String).status,
      401,
    );
    expect(call('DELETE', '/api/v1/players/$pid?chrono=maybe').status, 422);
  });

  test('retention: names after the game, identities after a year', () {
    final gid = newGame();
    final me = checkIn(
      gid,
      replicas: [
        {
          'declaration_id': '44444444-4444-4444-8444-444444444444',
          'type': 'aeg',
          'class': 'rifle',
        },
      ],
    );
    final pid = me['player_id']! as String;
    expect(svc.purge(force: true)!.values.every((v) => v == 0), isTrue);
    call('POST', '/api/v1/games/$gid/end');
    wall += 29 * 86400;
    expect(svc.purge(force: true)!['checkins'], 0);
    wall += 2 * 86400;
    expect(
      svc.purge(),
      containsPair('checkins', 1),
    ); // 10 minutes since the last
    expect(svc.purge(), isNull);
    final row = svc.checkinRow(gid, pid)!;
    expect(row['display_name'], isNull);
    expect(row['erased_at'], isNotNull);
    expect(svc.listCheckins(ApiViewer.gm, gid)['checkins'], [
      containsPair('declarations', isEmpty),
    ]);
    wall += 340 * 86400;
    expect(svc.purge(force: true)!['identities'], 1);
    expect(svc.checkinRow(gid, pid), isNull);
  });
}
