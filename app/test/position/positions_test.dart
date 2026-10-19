// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Player positions: the visibility table of ADR-P3-6 for the Android
// controller role (lib/controller/visibility_engine.dart, the same rules as
// the Pi controller's positions.py), and the phone's reporter
// (lib/position/position_reporter.dart): fixes batched, at most 5 a
// request, stopped when the controller says the game is not running.

import 'dart:async';

import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/controller/visibility_engine.dart';
import 'package:atalaia_app/platform/location.dart';
import 'package:atalaia_app/position/position_reporter.dart';
import 'package:flutter_test/flutter_test.dart';

PlayerPosition at(String id, int team, int squad) =>
    PlayerPosition(gameId: 1, playerId: id, team: team, squad: squad);

class FakeLocation implements LocationService {
  final fixesOut = StreamController<LocationFix>.broadcast();
  @override
  Future<bool> available() async => true;
  @override
  Future<bool> granted() async => true;
  @override
  Stream<LocationFix> fixes(Duration interval) => fixesOut.stream;
}

void main() {
  final all = [
    at('red1', 1, 1),
    at('red2', 1, 1),
    at('red3', 1, 2),
    at('lead', 1, 1),
    at('vip', 1, 0),
    at('blue1', 2, 1),
  ];

  Set<String> sees(VisibilityEngine e, Viewer v) =>
      e.visible(v, all).map((p) => p.playerId).toSet();

  test('the visibility table', () {
    final e = VisibilityEngine();
    Viewer v(String id, String role, int team, int squad) =>
        Viewer(role: role, playerId: id, team: team, squad: squad, gameId: 1);
    expect(sees(e, v('red1', 'player', 1, 1)), {'red1'});
    expect(sees(e, v('lead', 'squad_leader', 1, 1)), {'lead', 'red1', 'red2'});
    expect(sees(e, v('vip', 'vip', 1, 0)), {
      'vip',
      'red1',
      'red2',
      'red3',
      'lead',
    });
    expect(sees(e, v('m', 'marshal', 0, 0)), hasLength(6));
    expect(sees(e, v('s', 'spectator', 0, 0)), isEmpty);
    expect(sees(e, Viewer.gmToken), hasLength(6));
    expect(
      e.visible(v('m', 'marshal', 0, 0).copyGame(2), all),
      isEmpty,
    ); // another game
    e.squadVisible = true;
    expect(sees(e, v('red1', 'player', 1, 1)), {'red1', 'red2', 'lead'});
  });

  test('a temporary grant, one way, until it expires', () {
    var now = DateTime(2026, 10, 19, 10);
    final e = VisibilityEngine(now: () => now);
    const red = Viewer(
      role: 'player',
      playerId: 'red1',
      team: 1,
      squad: 1,
      gameId: 1,
    );
    const blue = Viewer(
      role: 'player',
      playerId: 'blue1',
      team: 2,
      squad: 1,
      gameId: 1,
    );
    e.grant(1, 2, const Duration(seconds: 30));
    expect(sees(e, red), {'red1', 'blue1'});
    expect(sees(e, blue), {'blue1'});
    now = now.add(const Duration(seconds: 31));
    expect(e.expire(), [(1, 2)]);
    expect(sees(e, red), {'red1'});
  });

  test(
    'the reporter batches fixes and stops when the game is not running',
    () async {
      final loc = FakeLocation();
      final sent = <List<Map<String, Object?>>>[];
      var refuse = false;
      final r = PositionReporter(
        location: loc,
        interval: const Duration(hours: 1), // flushed by hand
        send: (reports) async {
          if (refuse) throw CheckinException(409, 'not running');
          sent.add(reports);
          return {'stored': reports.length, 'interval_s': 10};
        },
      );
      r.start();
      for (var i = 0; i < 7; i++) {
        loc.fixesOut.add(
          LocationFix(lat: 38.7, lon: -9.1, accuracyM: 4, tMs: i),
        );
      }
      await Future<void>.delayed(Duration.zero);
      await r.flush();
      expect(sent.single, hasLength(5));
      expect(sent.single.last, {
        'source': 'gps',
        'lat': 38.7,
        'lon': -9.1,
        'accuracy_m': 4.0,
        't': 6,
      });
      expect(r.interval, const Duration(seconds: 10)); // the controller's
      refuse = true;
      loc.fixesOut.add(const LocationFix(lat: 1, lon: 1, tMs: 9));
      await Future<void>.delayed(Duration.zero);
      await r.flush();
      expect(r.running, isFalse);
      expect(r.stopReason, 'not running');
      r.dispose();
    },
  );
}

extension on Viewer {
  Viewer copyGame(int g) => Viewer(
    role: role,
    playerId: playerId,
    team: team,
    squad: squad,
    gameId: g,
  );
}
