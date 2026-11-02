// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The out-of-bounds warning on a player's phone (decisions MF-31 to MF-40,
// lib/position/field_bounds.dart): the boundary placed on the ground by its
// level's map position, inside and outside as the core's geo.in_zone says
// (protocol/vectors/geo.json), distances in metres, the margin, accuracy and
// dwell that keep a GPS error at the edge from warning, the level rules, the
// fetch with the player's token, and the player screen's banner, vibration
// and notification.

import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/platform/location.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/position/field_bounds.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/vectors.dart';

// A plan near Lisbon, north-up: about 174 m across and 222 m down.
const top = 38.7230, bottom = 38.7210, west = -9.1410, east = -9.1390;

Map<String, Object?> georefApi() => {
  'kind': 'corners',
  'corners': {
    'top_left': {'lat': top, 'lon': west},
    'top_right': {'lat': top, 'lon': east},
    'bottom_right': {'lat': bottom, 'lon': east},
    'bottom_left': {'lat': bottom, 'lon': west},
  },
};

// The middle half of the plan: lat 38.7225-38.7215, lon -9.1405 to -9.1395.
Map<String, Object?> boundary({int level = 0}) => {
  'id': 7 + level,
  'type': 'boundary',
  'shape': 'polygon',
  'level': level,
  'label': 'Campo',
  'visibility': 'everyone',
  'points': [
    {'x': 0.25, 'y': 0.25},
    {'x': 0.75, 'y': 0.25},
    {'x': 0.75, 'y': 0.75},
    {'x': 0.25, 'y': 0.75},
  ],
};

const safeZone = {
  'id': 3,
  'type': 'safe_zone',
  'shape': 'circle',
  'level': 0,
  'x': 0.1,
  'y': 0.1,
  'radius_m': 20,
};

/// [m] metres east of the boundary's east edge, at its middle latitude.
double eastOf(double m) {
  const lat = 38.7220;
  final k = math.pi / 180 * earthRadiusM * math.cos(lat * math.pi / 180);
  return -9.1395 + m / k;
}

class FakeHttp implements FieldHttp {
  FakeHttp(this.routes);
  final Map<String, Object? Function()> routes;
  final calls = <String>[];
  bool offline = false;

  @override
  Future<FieldResponse> send(
    String method,
    String path, {
    Object? body,
    String? token,
  }) async {
    calls.add('$method $path $token');
    if (offline) throw CheckinException(0, 'out of reach');
    final r = routes['$method $path'];
    return r == null ? const FieldResponse(404, null) : FieldResponse(200, r());
  }
}

class FakeLocation implements LocationService {
  final fixesOut = StreamController<LocationFix>.broadcast();
  @override
  Future<bool> available() async => true;
  @override
  Future<bool> granted() async => true;
  @override
  Stream<LocationFix> fixes(Duration interval) => fixesOut.stream;
}

FieldBounds bounds() => FieldBounds.of(
  [boundary(), safeZone],
  {0: PlanToGround.fromApi(georefApi())},
);

void main() {
  test('inside and outside as the core says (geo.json)', () {
    final v = loadVectors('geo.json');
    var n = 0;
    for (final c in cases(v, 'zones')) {
      final zone = c['zone'] as Map<String, dynamic>;
      if (zone['type'] != 'polygon') continue;
      final b = GroundBoundary(0, [
        for (final p in zone['points'] as List)
          ((p[0] as num).toDouble(), (p[1] as num).toDouble()),
      ]);
      final pt = c['point'] as List;
      final lat = (pt[0] as num).toDouble();
      final lon = (pt[1] as num).toDouble();
      expect(b.contains(lat, lon), c['inside'], reason: '${c['name']}');
      // The distance's sign agrees (a point on the line is 0: inside).
      expect(
        b.signedDistanceM(lat, lon) <= 1e-6,
        c['inside'],
        reason: '${c['name']}',
      );
      n++;
    }
    expect(n, greaterThanOrEqualTo(10));
  });

  test('the boundary on the ground, from the plan and its map position', () {
    final b = bounds();
    expect(b.byLevel.keys, [0]); // the safe zone is not a boundary
    final g = b.byLevel[0]!;
    expect(g.corners[0].$1, closeTo(38.7225, 1e-9));
    expect(g.corners[0].$2, closeTo(-9.1405, 1e-9));
    expect(g.corners[2].$1, closeTo(38.7215, 1e-9));
    expect(g.corners[2].$2, closeTo(-9.1395, 1e-9));
    expect(g.contains(38.7220, -9.1400), isTrue);
    expect(g.signedDistanceM(38.7220, eastOf(30)), closeTo(30, 0.5));
    expect(g.signedDistanceM(38.7220, eastOf(-20)), closeTo(-20, 0.5));
    // A level without a map position cannot be placed: no boundary there.
    expect(FieldBounds.of([boundary()], {0: null}).isEmpty, isTrue);
    expect(PlanToGround.fromApi(null), isNull);
    expect(PlanToGround.fromApi({'corners': <String, Object?>{}}), isNull);
  });

  test('levels: the player\'s own, else every level\'s (never a guess)', () {
    final map = PlanToGround.fromApi(georefApi());
    final two = FieldBounds.of(
      [boundary(), boundary(level: 2)],
      {0: map, 2: map},
    );
    expect(two.forLevel(0), hasLength(1));
    expect(two.forLevel(1), isEmpty); // that floor has no boundary: no warning
    expect(two.distanceOutsideM(38.7220, eastOf(30), 1), isNull);
    expect(two.forLevel(null), hasLength(2));
    expect(two.distanceOutsideM(38.7220, eastOf(30), null), closeTo(30, 0.5));
  });

  group('the watch: margin, accuracy and dwell', () {
    test(
      'a fix just outside, within its accuracy or the margin, is not out',
      () {
        final w = BoundsWatch();
        expect(w.onFix(8, 5, 0), BoundsAlert.none); // under the 10 m margin
        expect(
          w.onFix(14, 15, 10000),
          BoundsAlert.none,
        ); // within 15 m accuracy
        expect(
          w.onFix(30, 15, 20000),
          BoundsAlert.none,
        ); // out, not long enough
        expect(w.out, isFalse);
      },
    );

    test('out after the dwell; reminded; back with one fix inside', () {
      final w = BoundsWatch();
      expect(w.onFix(30, 5, 0), BoundsAlert.none);
      expect(w.onFix(30, 5, 4000), BoundsAlert.none);
      expect(w.onFix(30, 5, 5000), BoundsAlert.left);
      expect(w.out, isTrue);
      expect(w.onFix(3, 5, 15000), BoundsAlert.none); // in the band: still out
      expect(w.onFix(30, 5, 65000), BoundsAlert.stillOut);
      expect(w.onFix(30, 5, 70000), BoundsAlert.none);
      expect(w.onFix(-1, 5, 75000), BoundsAlert.back);
      expect(w.out, isFalse);
    });

    test('a fix back inside before the dwell starts it again', () {
      final w = BoundsWatch();
      w.onFix(30, 5, 0);
      w.onFix(-5, 5, 3000);
      expect(w.onFix(30, 5, 6000), BoundsAlert.none);
      expect(w.onFix(30, 5, 11000), BoundsAlert.left);
    });

    test('poor fixes are not judged; no boundary ends a warning', () {
      final w = BoundsWatch();
      w.onFix(30, 5, 0);
      expect(w.onFix(500, 80, 6000), BoundsAlert.none); // 80 m: ignored
      expect(w.out, isFalse);
      expect(w.onFix(30, null, 7000), BoundsAlert.left); // 20 m assumed
      expect(w.onFix(-30, 80, 8000), BoundsAlert.none); // ignored, still out
      expect(w.onFix(null, 5, 9000), BoundsAlert.back);
      expect(w.onFix(null, 5, 9500), BoundsAlert.none);
    });
  });

  test('fetched with the player\'s token: the features, one map position '
      'per level with a boundary', () async {
    final http = FakeHttp({
      'GET /field/features': () => {
        'features': [boundary(), safeZone],
      },
      'GET /field/levels/0/georef': () => {'georef': georefApi(), 'own': true},
    });
    final b = await loadFieldBounds(http, 'tok');
    expect(b!.byLevel.keys, [0]);
    expect(http.calls, [
      'GET /field/features tok',
      'GET /field/levels/0/georef tok',
    ]);
    // The stream's list: no features request.
    http.calls.clear();
    await loadFieldBounds(http, 'tok', features: [safeZone]);
    expect(http.calls, isEmpty);
    http.offline = true;
    expect(await loadFieldBounds(http, 'tok'), isNull);
  });

  test('the feed keeps the stream\'s map features', () {
    final feed = FieldFeed(FieldLink(Uri.parse('http://10.0.0.1:8080'), 'c'));
    addTearDown(feed.dispose);
    expect(feed.mapFeatures, isNull);
    feed.onMessage({
      'type': 'map_features',
      'features': [boundary(), 'junk'],
    });
    expect(feed.mapFeatures, [boundary()]);
  });

  testWidgets('the player screen warns, and stops warning', (tester) async {
    tester.view.physicalSize = const Size(400, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final field = PinnedField(
      fieldId: 'f1',
      fieldName: 'Campo',
      caPem: '',
      caSha256: Uint8List(32),
      urls: const ['https://10.0.0.1:8443'],
    );
    final feed = FieldFeed(
      FieldLink(Uri.parse('https://10.0.0.1:8443'), 'tok', field: field),
    );
    addTearDown(feed.dispose);
    feed.onMessage({
      'type': 'hello',
      'game': {
        'id': 1,
        'name': 'Domingo',
        'state': 'running',
        'teams': ['red', 'blue'],
      },
      'me': {'player_id': 'p1', 'role': 'player', 'team': 'red'},
    });
    final http = FakeHttp({
      'GET /field/features': () => {
        'features': [boundary()],
      },
      'GET /field/levels/0/georef': () => {'georef': georefApi()},
      'POST /positions': () => {'stored': 1, 'interval_s': 10},
    });
    final loc = FakeLocation();
    final h = harness(
      language: AppLanguage.en,
      settings: AppSettings(),
      fieldHttp: (_) => http,
      location: loc,
    );
    h.device.granted.add('ACCESS_FINE_LOCATION');
    await tester.pumpWidget(
      h.app(
        home: PlayerScreen(link: feed.link, feed: feed),
      ),
    );
    await tester.pump();
    await tester.tap(find.byKey(const Key('player-share-position')));
    for (var i = 0; i < 5; i++) {
      await tester.pump(const Duration(milliseconds: 10));
    }
    expect(find.byKey(const Key('player-bounds-watch')), findsOneWidget);

    Future<void> fix(double metresOut, int t) async {
      loc.fixesOut.add(
        LocationFix(lat: 38.7220, lon: eastOf(metresOut), accuracyM: 5, tMs: t),
      );
      for (var i = 0; i < 3; i++) {
        await tester.pump(const Duration(milliseconds: 10));
      }
    }

    await fix(40, 1000);
    expect(find.byKey(const Key('player-out-of-bounds')), findsNothing);
    await fix(40, 11000);
    expect(find.byKey(const Key('player-out-of-bounds')), findsOneWidget);
    expect(find.text('Out of bounds'), findsOneWidget);
    expect(h.device.calls, contains('vibrate [0, 600, 300, 600, 300, 600]'));
    expect(
      h.foreground.calls,
      contains(
        'update Out of bounds | You have left the field\'s boundary. Go back '
        'inside.',
      ),
    );
    // The switch records the player's choice (decision LEG-12).
    expect(
      http.calls.where((c) => c.startsWith('PUT /checkin/me/position-sharing')),
      isNotEmpty,
    );
    // Nothing about it went to the controller: positions only (and the
    // player's own switch, which records the sharing choice).
    expect(
      http.calls
          .where(
            (c) =>
                !c.startsWith('GET /field/') &&
                !c.startsWith('PUT /checkin/me/position-sharing'),
          )
          .toSet(),
      everyElement(startsWith('POST /positions')),
    );

    await fix(-10, 21000);
    expect(find.byKey(const Key('player-out-of-bounds')), findsNothing);
    expect(h.device.calls.last, 'vibrate [0, 200]');
    expect(
      h.foreground.calls.last,
      'update Atalaia: sharing your position | During the game',
    );

    // The GM removes the boundary while the player is out: no warning left.
    await fix(40, 31000);
    await fix(40, 41000);
    expect(find.byKey(const Key('player-out-of-bounds')), findsOneWidget);
    feed.onMessage({'type': 'map_features', 'features': <Object?>[]});
    for (var i = 0; i < 3; i++) {
      await tester.pump(const Duration(milliseconds: 10));
    }
    expect(find.byKey(const Key('player-out-of-bounds')), findsNothing);
    expect(find.byKey(const Key('player-bounds-watch')), findsNothing);

    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('a marshal is not warned', (tester) async {
    final field = PinnedField(
      fieldId: 'f1',
      fieldName: 'Campo',
      caPem: '',
      caSha256: Uint8List(32),
      urls: const ['https://10.0.0.1:8443'],
    );
    final feed = FieldFeed(
      FieldLink(Uri.parse('https://10.0.0.1:8443'), 'tok', field: field),
    );
    addTearDown(feed.dispose);
    feed.onMessage({
      'type': 'hello',
      'game': {
        'id': 1,
        'name': 'Domingo',
        'state': 'running',
        'teams': ['red', 'blue'],
      },
      'me': {'player_id': 'm1', 'role': 'marshal'},
    });
    final http = FakeHttp({
      'GET /field/features': () => {
        'features': [boundary()],
      },
      'GET /field/levels/0/georef': () => {'georef': georefApi()},
      'POST /positions': () => {'stored': 1},
    });
    final loc = FakeLocation();
    final h = harness(fieldHttp: (_) => http, location: loc);
    h.device.granted.add('ACCESS_FINE_LOCATION');
    await tester.pumpWidget(
      h.app(
        home: PlayerScreen(link: feed.link, feed: feed),
      ),
    );
    await tester.pump();
    await tester.tap(find.byKey(const Key('player-share-position')));
    for (var i = 0; i < 5; i++) {
      await tester.pump(const Duration(milliseconds: 10));
    }
    for (final t in [1000, 11000, 21000]) {
      loc.fixesOut.add(
        LocationFix(lat: 38.7220, lon: eastOf(40), accuracyM: 5, tMs: t),
      );
      await tester.pump(const Duration(milliseconds: 10));
    }
    expect(find.byKey(const Key('player-out-of-bounds')), findsNothing);
    expect(h.device.calls.where((c) => c.startsWith('vibrate')), isEmpty);
    await tester.pumpWidget(const SizedBox());
  });
}
