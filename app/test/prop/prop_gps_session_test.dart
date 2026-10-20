// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// VIP / Payload's payload on the prop session (plan phase 5, decision P4R6):
// a role that uses `gps` gets the phone's fixes as gps.fix, on the real core
// in a game loop isolate. The mode's own geo.distance and geo.in_zone run on
// the phone; only vip.extracted leaves it, with no coordinates.

import 'dart:async';

import 'package:atalaia_app/core/node_runner.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/platform/location.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/fakes.dart';

const texts = PropTexts(
  notificationTitle: 'Atalaia: {mode}',
  notificationRunning: 'running',
  notificationLeft: '{time} left',
);

class FakeLocation implements LocationService {
  final fixesOut = StreamController<LocationFix>.broadcast();
  final intervals = <Duration>[];
  @override
  Future<bool> available() async => true;
  @override
  Future<bool> granted() async => true;
  @override
  Stream<LocationFix> fixes(Duration interval) {
    intervals.add(interval);
    return fixesOut.stream;
  }
}

/// The extraction zone of the tests: 25 m around a point in Lisbon.
const zone = '38.722345,-9.139312';

LocationFix fix(double lat, double lon, [double? acc = 8]) =>
    LocationFix(lat: lat, lon: lon, accuracyM: acc, tMs: 0);

PropSession session(
  String role,
  FakeLocation location, {
  Map<String, Object?> params = const {},
}) {
  final mode = ModeCatalog.builtin().compose('org.atalaia.vip_payload');
  const teams = ['red', 'blue'];
  return PropSession(
    setup: PropSetup(
      mode: mode,
      role: role,
      teams: teams,
      params: mode.resolveParams(params, teams),
    ),
    runner: createNodeRunner(libraryPath: coreLibraryPath()),
    device: FakeDevice(),
    texts: texts,
    clock: GameClock.manual,
    location: location,
  );
}

Future<void> settle(PropSession s) async {
  // The fixes are inputs to the node's isolate: let them arrive.
  for (var i = 0; i < 5; i++) {
    await s.advance(0);
  }
}

void main() {
  test('the payload: looking for GPS, the metres left, then extracted, '
      'once', () async {
    final location = FakeLocation();
    final s = session('payload', location, params: {'extraction': zone});
    addTearDown(s.close);
    await s.open();
    expect(s.usesGps, isTrue);
    expect(location.intervals, isEmpty); // nothing before the game starts
    await s.start();
    await settle(s);
    expect(location.intervals, [const Duration(seconds: 2)]);
    expect(s.screenName, 'payload');
    expect(s.screenData['state'], 'searching');

    location.fixesOut.add(fix(38.723244, -9.139312, 60)); // 100 m north, weak
    await settle(s);
    expect(s.screenData['state'], 'weak');
    expect(s.screenData['metres'], 60);

    location.fixesOut.add(fix(38.723244, -9.139312));
    await settle(s);
    expect(s.screenData, {'team': 'red', 'state': 'moving', 'metres': 75});
    expect(s.log.where((l) => l.startsWith('vip.extracted')), isEmpty);

    location.fixesOut.add(fix(38.722390, -9.139312)); // 5 m north: inside
    await settle(s);
    expect(s.screenData['state'], 'extracted');
    final out = s.log.where((l) => l.startsWith('vip.extracted')).toList();
    expect(out, ['vip.extracted {"team":"red"}']);

    // Out and back in: nothing more. No event ever carries a coordinate.
    location.fixesOut.add(fix(38.723244, -9.139312));
    location.fixesOut.add(fix(38.722390, -9.139312));
    await settle(s);
    expect(s.log.where((l) => l.startsWith('vip.extracted')).length, 1);
    expect(s.log.where((l) => l.contains('38.72')), isEmpty);
  });

  test(
    'a game without a zone says so; fixes stop when the game ends',
    () async {
      final location = FakeLocation();
      final s = session('payload', location);
      addTearDown(s.close);
      await s.open();
      await s.start();
      location.fixesOut.add(fix(38.722345, -9.139312));
      await settle(s);
      expect(s.screenData['state'], 'no_zone');
      await s.end();
      await settle(s);
      expect(s.phase, PropPhase.ended);
      expect(location.fixesOut.hasListener, isFalse);
    },
  );

  test('a checkpoint does not use the GPS', () async {
    final location = FakeLocation();
    final s = session('checkpoint', location, params: {'extraction': zone});
    addTearDown(s.close);
    await s.open();
    expect(s.usesGps, isFalse);
    await s.start();
    await settle(s);
    expect(location.intervals, isEmpty);
    expect(s.screenName, 'checkpoint_free');
    s.pressTeam('blue');
    for (var t = 0; t < 3200; t += 100) {
      await s.advance(100);
    }
    s.releaseTeam('blue');
    await settle(s);
    expect(s.screenName, 'checkpoint_held');
    expect(s.screenData['team'], 'blue');
  });
}
