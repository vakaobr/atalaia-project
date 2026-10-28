// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// APD membership on the Android field controller (protocol/apd.md): the
// field's rule in the check-in settings, the verdict on staff rows, a
// membership that does not pass leaving the check-in to a marshal (never
// refused, logged), the old federation number as the membership number, the
// site server's rule, and the erasure of what was declared.

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_checkin.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_positions.dart';
import 'package:atalaia_app/controller/controller_sync_format.dart';
import 'package:atalaia_app/protocol/apd.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/recording_radio.dart';

/// 2027-01-15 10:00:00 UTC.
const t0 = 1800007200.0;

String _secret(int n) =>
    base64Url.encode(List.filled(32, n)).replaceAll('=', '');

const _list =
    '{"format":1,"apds":['
    '{"id":"apd-a","name":"APD A","short_name":"A","website":null,"source":"https://a.example/"},'
    '{"id":"apd-b","name":"APD B","short_name":"B","website":null,"source":"https://b.example/"}'
    ']}';

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
      CheckinConfig(limitsYaml: limits, utcDay: true, apdsJson: _list),
    );
    ControllerPositions(engine);
    api = ControllerApi(engine, gmToken: 'g', readToken: 'r');
  });

  ApiResponse call(
    String method,
    String path, {
    String? token = 'g',
    Object? body,
  }) => api.handle(
    method,
    Uri.parse(path),
    authorization: token == null ? null : 'Bearer $token',
    body: body == null ? '' : jsonEncode(body),
    client: 'local',
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
    return (r.body! as Map)['id']! as int;
  }

  void rule(Map<String, Object?> r) {
    final res = call('PUT', '/api/v1/checkin/settings', body: {'apd': r});
    expect(res.status, 200, reason: '${res.body}');
  }

  var n = 0;
  String pid = '';
  ApiResponse checkIn(int gid, Map<String, Object?> extra) {
    n++;
    pid = 'p-${'abcdefghijklmnopqrstuvwxyz'[n % 26] * 12}';
    return call(
      'POST',
      '/api/v1/checkin',
      token: null,
      body: {
        'game_id': gid,
        'player_id': pid,
        'player_secret': _secret(n),
        'display_name': 'Falcão',
        'notice_version': 1,
        ...extra,
      },
    );
  }

  /// The staff row of the player [who] (default: the latest to check in).
  Map<String, Object?> row(int gid, [String? who]) {
    final list = svc.listCheckins(ApiViewer.gm, gid)['checkins']! as List;
    return (list.firstWhere((r) => (r as Map)['player_id'] == (who ?? pid))
            as Map)
        .cast<String, Object?>();
  }

  test('the rule is a check-in setting: default, saved, refused when bad', () {
    final info = svc.info();
    expect((info['settings']! as Map)['apd'], ApdRule.defaults.toJson());
    // The project's list, then the field's own entries.
    expect(
      [for (final e in info['apds']! as List) (e as Map)['id']],
      ['apd-a', 'apd-b'],
    );
    rule({
      'accepted': ['apd-a', 'x-own'],
      'checkin': true,
      'expiry': true,
      'custom': [
        {'id': 'x-own', 'name': 'Own', 'short_name': 'O'},
      ],
    });
    final saved = (svc.info()['settings']! as Map)['apd']! as Map;
    expect(saved['accepted'], ['apd-a', 'x-own']);
    expect(saved['checkin'], true);
    expect(
      [for (final e in svc.info()['apds']! as List) (e as Map)['id']],
      ['apd-a', 'apd-b', 'x-own'],
    );
    final bad = call(
      'PUT',
      '/api/v1/checkin/settings',
      body: {
        'apd': {'checkin': 'yes'},
      },
    );
    expect(bad.status, 400);
    expect(((svc.info()['settings']! as Map)['apd']! as Map)['checkin'], true);
  });

  test('a membership that passes checks in; one that does not waits', () {
    final gid = newGame();
    rule({
      'checkin': true,
      'expiry': true,
      'accepted': ['apd-a'],
    });
    var r = checkIn(gid, {
      'apd_id': 'apd-a',
      'membership_number': '123',
      'membership_expires': '2027-06-30',
    });
    expect(r.status, 201, reason: '${r.body}');
    expect((r.body! as Map)['status'], 'checked_in');
    expect(row(gid)['apd_status'], 'valid');
    for (final (extra, verdict) in [
      (<String, Object?>{}, 'missing'),
      (
        {
          'apd_id': 'apd-b',
          'membership_number': '1',
          'membership_expires': '2027-06-30',
        },
        'not_accepted',
      ),
      (
        {
          'apd_id': 'apd-a',
          'membership_number': '1',
          'membership_expires': '2027-01-14',
        },
        'expired',
      ),
    ]) {
      r = checkIn(gid, extra);
      // Never refused: pending, for a marshal.
      expect(r.status, 201, reason: '${r.body}');
      expect((r.body! as Map)['status'], 'pending', reason: verdict);
      expect(row(gid)['apd_status'], verdict);
    }
  });

  test(
    'a marshal confirms any verdict: marked and logged without the number',
    () {
      final gid = newGame();
      rule({
        'checkin': true,
        'accepted': ['apd-b'],
      });
      checkIn(gid, {'apd_id': 'apd-a', 'membership_number': '123'});
      expect(row(gid)['status'], 'pending');
      final logged = <String>[];
      svc.audit = logged.add;
      final r = call(
        'PATCH',
        '/api/v1/games/$gid/checkins/$pid',
        body: {'status': 'checked_in'},
      );
      expect(r.status, 200, reason: '${r.body}');
      final after = (r.body! as Map).cast<String, Object?>();
      expect(after['status'], 'checked_in');
      expect(after['apd_override'], true);
      expect(after['apd_status'], 'not_accepted');
      expect(logged, hasLength(1));
      expect(logged.single, contains(pid));
      expect(logged.single, contains('not_accepted'));
      expect(logged.single, isNot(contains('123')));
    },
  );

  test('a hand check-in is never refused, and keeps what was declared', () {
    final gid = newGame();
    rule({'checkin': true, 'expiry': true});
    final r = call(
      'POST',
      '/api/v1/games/$gid/checkins',
      body: {
        'display_name': 'Corvo',
        'apd_id': 'apd-a',
        'federation_number': '777',
        'membership_expires': '2026-12-31',
      },
    );
    expect(r.status, 201, reason: '${r.body}');
    final v = (r.body! as Map).cast<String, Object?>();
    expect(v['status'], 'checked_in');
    expect(v['apd_status'], 'expired');
    expect(v['apd_override'], true);
    expect(v['membership_number'], '777');
    expect(v['federation_number'], '777');
  });

  test('the old federation number is the membership number', () {
    final gid = newGame();
    call('PUT', '/api/v1/checkin/settings', body: {'federation': 'optional'});
    expect(checkIn(gid, {'federation_number': 'FPA-9'}).status, 201);
    final v = row(gid);
    expect(v['membership_number'], 'FPA-9');
    expect(v['federation_number'], 'FPA-9');
    expect(v['apd_id'], isNull);
    expect(v['apd_status'], isNull, reason: 'no rule asks: no verdict');
    // Both given: they must agree.
    expect(
      checkIn(gid, {'federation_number': '1', 'membership_number': '2'}).status,
      400,
    );
    expect(
      checkIn(gid, {'federation_number': '1', 'membership_number': '1'}).status,
      201,
    );
  });

  test('without the federation setting a rule that asks still keeps it', () {
    final gid = newGame();
    expect(checkIn(gid, {'membership_number': '5'}).status, 201);
    expect(row(gid)['membership_number'], isNull, reason: 'nothing asked');
    rule({'checkin': true});
    checkIn(gid, {
      'membership_number': '5',
      'membership_expires': '2030-01-01',
    });
    expect(row(gid)['membership_number'], '5');
    expect(row(gid)['membership_expires'], '2030-01-01');
  });

  test('bad declarations are refused', () {
    final gid = newGame();
    rule({'checkin': true});
    expect(checkIn(gid, {'membership_expires': '31/01/2027'}).status, 400);
    expect(checkIn(gid, {'apd_id': 'APD A'}).status, 400);
  });

  test('leaving erases the membership; so does the retention purge', () {
    final gid = newGame();
    rule({'checkin': true});
    final r = checkIn(gid, {
      'apd_id': 'apd-a',
      'membership_number': '9',
      'membership_expires': '2030-01-01',
    });
    final token = (r.body! as Map)['token']! as String;
    expect(call('DELETE', '/api/v1/checkin/me', token: token).status, 200);
    final v = row(gid);
    expect(
      [v['apd_id'], v['membership_number'], v['membership_expires']],
      [null, null, null],
    );
    // The purge: the game ended long ago.
    checkIn(gid, {'apd_id': 'apd-a', 'membership_number': '9'});
    expect(row(gid)['membership_number'], '9');
    call('POST', '/api/v1/games/$gid/start');
    call('POST', '/api/v1/games/$gid/end');
    wall += 31 * 86400;
    svc.purge(force: true);
    final p = row(gid);
    expect([p['apd_id'], p['membership_number']], [null, null]);
  });

  test('the staff CSV carries the APD columns, never the verdict unasked', () {
    final gid = newGame();
    rule({'checkin': true});
    checkIn(gid, {'apd_id': 'apd-a', 'membership_number': '9'});
    final csv = svc.csvExport(gid);
    expect(csv.split('\r\n').first.contains('apd_id,membership_expires'), true);
    expect(csv.contains(',apd-a,,valid,'), true);
  });

  test('the site server\'s rule applies, and the console cannot change it', () {
    final gid = newGame();
    svc.apdSiteManaged = true;
    // Nothing from the site yet: the local rule (the default).
    expect(svc.apdRule(), ApdRule.defaults);
    svc.applySiteApd(
      ApdRule.parse({
        'checkin': true,
        'accepted': ['apd-b'],
      }),
    );
    expect(((svc.info()['settings']! as Map)['apd']! as Map)['checkin'], true);
    checkIn(gid, {'apd_id': 'apd-a', 'membership_number': '1'});
    expect(row(gid)['apd_status'], 'not_accepted');
    final r = call(
      'PUT',
      '/api/v1/checkin/settings',
      body: {'apd': ApdRule.defaults.toJson()},
    );
    expect(r.status, 409);
    // Not managed any more: the console's own rule (the default) again.
    svc.apdSiteManaged = false;
    expect(svc.apdRule(), ApdRule.defaults);
  });

  group('the roster (GET /api/v1/sync/roster)', () {
    const sid = '5a5a5a5a-1111-4222-8333-444455556666';
    Map<String, Object?> roster({
      String federation = 'off',
      Object? apd,
      Map<String, Object?> reg = const {},
    }) => {
      'sync_version': 1,
      'scheduled_game_id': sid,
      'status': 'published',
      'federation': federation,
      'apd': ?apd,
      'registrations': [
        {
          'registration_id': '0e000000-0000-4000-8000-000000000001',
          'player_id': 'p-aaaaaaaaaaaa',
          'display_name': 'Falcão',
          'replicas': <Object?>[],
          ...reg,
        },
      ],
    };

    test('the format: the rule, and what is asked', () {
      final ok = checkRoster(
        roster(
          apd: {'checkin': true},
          reg: {
            'federation_number': '12',
            'apd_id': 'apd-a',
            'membership_expires': '2027-02-01',
          },
        ),
      );
      expect((ok['apd']! as Map)['checkin'], true);
      expect((ok['apd']! as Map)['accepted'], isNull, reason: 'normalised');
      // Not asked by the game nor the rule: refused, as the number was.
      for (final reg in [
        {'federation_number': '12'},
        {'apd_id': 'apd-a'},
        {'membership_expires': '2027-02-01'},
      ]) {
        expect(
          () => checkRoster(roster(reg: reg)),
          throwsA(
            isA<SyncFormatError>().having((e) => e.code, 'code', 'not_asked'),
          ),
        );
      }
      // The game asks for the number (the old rule), as before.
      checkRoster(
        roster(federation: 'optional', reg: {'federation_number': '1'}),
      );
      for (final bad in [
        roster(apd: {'checkin': 'yes'}),
        roster(
          apd: {'checkin': true},
          reg: {'membership_expires': '2027-02-30'},
        ),
        roster(apd: {'checkin': true}, reg: {'apd_id': 'APD'}),
      ]) {
        expect(() => checkRoster(bad), throwsA(isA<SyncFormatError>()));
      }
    });

    test('an old roster without the rule is still good', () {
      checkRoster(
        roster(federation: 'required', reg: {'federation_number': '1'}),
      );
    });

    test('applied: expected rows carry the APD, shown with the verdict', () {
      final gid = newGame();
      rule({'checkin': true, 'expiry': true});
      final out = svc.applyRoster(
        gid,
        checkRoster(
          roster(
            apd: {'checkin': true, 'expiry': true},
            reg: {
              'federation_number': '55',
              'apd_id': 'apd-a',
              'membership_expires': '2027-01-01',
            },
          ),
        ),
      );
      expect(out['added'], 1);
      final v = row(gid, 'p-aaaaaaaaaaaa');
      expect(v['status'], 'expected');
      expect(
        [v['apd_id'], v['membership_number'], v['membership_expires']],
        ['apd-a', '55', '2027-01-01'],
      );
      expect(v['apd_status'], 'expired');
    });

    test('applied without a rule here: not kept, as the number was', () {
      final gid = newGame();
      svc.applyRoster(
        gid,
        checkRoster(roster(apd: {'checkin': true}, reg: {'apd_id': 'apd-a'})),
      );
      expect(row(gid, 'p-aaaaaaaaaaaa')['apd_id'], isNull);
    });
  });
}
