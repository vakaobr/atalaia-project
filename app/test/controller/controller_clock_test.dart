// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The phone controller's wall clock and its guard (controller_clock.dart;
// decisions CLK-1 to CLK-8, on the phone since STUCK-62 as the maintainer
// changed it on 2026-11-05), as the Pi's controller/tests/test_wallclock.py:
// the floor (release date, high-water mark, the store's records), the GM's
// forward-only correction, jumps that hold the retention purge, the API, and
// the TIME beacons and RELEASE on the corrected clock.

import 'dart:io';

import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_checkin.dart';
import 'package:atalaia_app/controller/controller_clock.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:flutter_test/flutter_test.dart';

const rel = clockReleaseDateS;
const day = 86400;

/// The system clock and the monotonic one, which a test moves apart.
class FakeTime {
  FakeTime(this.wall);
  double wall;
  double mono = 1000;

  void advance(double s) {
    wall += s;
    mono += s;
  }
}

Matcher refused(String code) =>
    throwsA(isA<ClockError>().having((e) => e.code, 'code', code));

void main() {
  test("the release date is the Pi's RELEASE_DATE, not in the future", () {
    final src = File('../controller/atalaia_controller/wallclock.py')
        .readAsStringSync();
    final m = RegExp(
      r'RELEASE_DATE = calendar\.timegm\(\((\d+), (\d+), (\d+), 0, 0, 0\)\)',
    ).firstMatch(src)!;
    final date = DateTime.utc(
      int.parse(m[1]!),
      int.parse(m[2]!),
      int.parse(m[3]!),
    );
    expect(clockReleaseDateS, date.millisecondsSinceEpoch ~/ 1000);
    expect(
      clockReleaseDateS,
      lessThanOrEqualTo(DateTime.now().millisecondsSinceEpoch ~/ 1000),
    );
  });

  group('the guard', () {
    late FakeTime ft;
    late MemoryControllerStore store;
    late double newest;
    late ClockGuard guard;

    ClockGuard make() => ClockGuard(
      raw: () => ft.wall,
      mono: () => ft.mono,
      newestRecord: () => newest,
      getSetting: store.getSetting,
      setSetting: store.setSetting,
    );

    setUp(() {
      ft = FakeTime(rel + 10.0 * day);
      store = MemoryControllerStore();
      newest = 0;
      guard = make();
    });

    test('a plausible clock is ok and remembered', () {
      guard.start();
      expect(guard.status()['ok'], isTrue);
      expect(guard.highWater(), closeTo(ft.wall, 1));
      expect(store.getSetting(clockHighWaterKey), isNotNull);
      expect(guard.purgeAllowed(), isTrue);
    });

    test('1970 is wrong', () {
      ft.wall = 5;
      guard.start();
      final s = guard.status();
      expect(s['ok'], isFalse);
      expect(s['reason'], 'before_release');
      expect(guard.purgeAllowed(), isFalse);
      expect(s['purge_held'], isTrue);
    });

    test('days behind is caught by the high-water mark', () {
      guard.start();
      ft.advance(2.0 * day);
      guard.tick(); // stored: the controller saw this time
      ft.wall -= 3 * day; // a restart: the clock comes up at an old time
      final s = make().status();
      expect(s['ok'], isFalse);
      expect(s['reason'], 'behind_records');
    });

    test("the store's newest record counts", () {
      newest = rel + 50.0 * day;
      expect(make().status()['ok'], isFalse);
    });

    test('a set moves forward only and never below the floor', () {
      ft.wall = 5;
      guard.start();
      // This device's clock is wrong too.
      expect(() => guard.set(rel - 5 * day), refused('below_floor'));
      for (final bad in [true, 'x', null, double.nan]) {
        expect(() => guard.set(bad), refused('invalid'));
      }
      expect(() => guard.set(rel + 10 * 365 * day), refused('too_far'));
      final s = guard.set(rel + 3 * day);
      expect(s['ok'], isTrue);
      expect(guard.now(), closeTo(rel + 3 * day, 2));
      expect(guard.purgeAllowed(), isTrue);
      // The correction follows the system clock, which goes on.
      ft.advance(100);
      expect(guard.now(), closeTo(rel + 3 * day + 100, 2));
    });

    test('backwards is refused, so expired tokens stay expired', () {
      guard.start();
      final before = guard.now();
      // Under what the controller has seen.
      expect(() => guard.set(before - 3600), refused('below_floor'));
      store.deleteSetting(clockHighWaterKey);
      final fresh = make(); // even with nothing seen before: not backwards
      expect(() => fresh.set(before - 3600), refused('backwards'));
      expect(fresh.offset, 0);
      // A small forward step from a plausible clock is fine; a month is not.
      fresh.set(before + 3600);
      expect(() => fresh.set(fresh.now() + 30 * day), refused('too_far'));
    });

    test('a forward jump holds the purge and is reported', () {
      guard
        ..start()
        ..tick();
      ft.wall += 400 * day; // NTP, or a wrong clock coming right the other way
      guard.tick();
      final jump = guard.status()['last_jump']! as Map;
      expect(jump['seconds'] as num, greaterThan(300 * day));
      expect(guard.purgeAllowed(), isFalse);
      ft.advance(clockPurgeHoldS + 1.0);
      expect(guard.purgeAllowed(), isTrue);
    });

    test('a small correction is a jump but holds nothing', () {
      guard.start();
      ft.wall += 90;
      guard.tick();
      expect(guard.status()['last_jump'], isNotNull);
      expect(guard.purgeAllowed(), isTrue);
    });
  });

  group('the engine', () {
    late int now;
    late double wall;
    late ControllerEngine engine;
    late ControllerApi api;

    setUp(() {
      now = 0;
      wall = rel + 4.0 * day;
      engine = ControllerEngine(
        clockMs: () => now,
        wallSeconds: () => wall + now / 1000,
      );
      api = ControllerApi(engine, gmToken: 'gm-secret', readToken: 'rd-secret');
    });

    tearDown(() => engine.close());

    (int, Map<String, Object?>) call(
      String method,
      String path, {
      String? token,
      String body = '',
    }) {
      final r = api.handle(
        method,
        Uri.parse(path),
        authorization: token == null ? null : 'Bearer $token',
        body: body,
      );
      return (r.status, (r.body as Map?)?.cast<String, Object?>() ?? {});
    }

    test('the status carries the clock and the API sets it for a GM only', () {
      final st = call('GET', '/api/v1/controller', token: 'rd-secret').$2;
      expect((st['clock']! as Map)['ok'], isTrue);
      expect(call('GET', '/api/v1/clock', token: 'rd-secret').$2['ok'], isTrue);
      final ahead = '{"epoch": ${wall + 5}}';
      expect(call('PUT', '/api/v1/clock', body: ahead).$1, 401);
      expect(
        call('PUT', '/api/v1/clock', token: 'rd-secret', body: ahead).$1,
        403,
      );
      final back = call(
        'PUT',
        '/api/v1/clock',
        token: 'gm-secret',
        body: '{"epoch": ${wall - 3600}}',
      );
      expect(back.$1, 409);
      expect(back.$2['code'], anyOf('backwards', 'below_floor'));
      expect(
        call(
          'PUT',
          '/api/v1/clock',
          token: 'gm-secret',
          body: '{"epoch": "x"}',
        ).$1,
        400,
      );
    });

    test('a wrong clock in the status, set from the GM device: what it records '
        'follows', () {
      engine.close();
      wall = 100; // a phone reset to 1970
      engine = ControllerEngine(
        clockMs: () => now,
        wallSeconds: () => wall + now / 1000,
      );
      api = ControllerApi(engine, gmToken: 'gm-secret', readToken: 'rd-secret');
      final st = call('GET', '/api/v1/controller', token: 'rd-secret').$2;
      expect((st['clock']! as Map)['ok'], isFalse);
      final set = call(
        'PUT',
        '/api/v1/clock',
        token: 'gm-secret',
        body: '{"epoch": ${rel + 2 * day}}',
      );
      expect(set.$1, 200, reason: '${set.$2}');
      expect(set.$2['ok'], isTrue);
      expect(engine.wallSeconds(), greaterThan(rel + day));
      // What it records is on the corrected clock too.
      final game = engine.createGame({
        'name': 'Sábado',
        'mode_id': 'org.atalaia.domination',
        'teams': ['red', 'blue'],
      });
      expect(game['created_at']! as num, greaterThan(rel + day));
    });

    test('nothing is purged while the clock is wrong', () {
      final checkin = ControllerCheckin(
        engine,
        CheckinConfig(
          limitsYaml: File('lib/chrono/limit_templates/portugal.yaml')
              .readAsStringSync(),
        ),
      );
      expect(checkin.purge(force: true), isNotNull);
      wall = rel - 30.0 * day; // the clock went back under the floor
      expect(engine.clock.purgeAllowed(), isFalse);
      expect(checkin.purge(force: true), isNull);
    });
  });
}
