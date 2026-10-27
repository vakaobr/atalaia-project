// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The player's floor and the field plan with the positions (decisions ML-5,
// MF-14, PM-1 to PM-9): the floor the player chooses goes with the GPS
// reports (and a beacon's own floor wins), the plan, features and positions
// the controller lets this player see are drawn on the level they are on,
// and nothing is drawn that the controller did not send. Checked at a
// phone's width.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/platform/location.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/position/field_bounds.dart';
import 'package:atalaia_app/position/field_plan.dart';
import 'package:atalaia_app/position/position_reporter.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';

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

final png = base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
);

Map<String, Object?> levelsApi({int count = 2, bool images = true}) => {
  'enabled': count > 1,
  'count': count,
  'in_use': count,
  'levels': [
    for (var n = 0; n < count; n++)
      {
        'level': n,
        'name': n == 0 ? 'Ground' : (n == 1 ? '' : 'Roof'),
        'image': images
            ? {'content_type': 'image/png', 'bytes': 70, 'updated_at': 100 + n}
            : null,
      },
  ],
};

class FakeFieldHttp implements FieldHttp {
  FakeFieldHttp(this.routes);
  final Map<String, FieldResponse Function(Object? body)> routes;
  final calls = <String>[];
  final posted = <Map<String, Object?>>[];

  @override
  Future<FieldResponse> send(
    String method,
    String path, {
    Object? body,
    String? token,
  }) async {
    calls.add('$method $path $token');
    if (method == 'POST' && path == '/positions') {
      for (final r in (body! as Map)['reports'] as List) {
        posted.add((r as Map).cast<String, Object?>());
      }
      return const FieldResponse(200, {'stored': 1, 'interval_s': 10});
    }
    final r = routes['$method $path'];
    return r == null ? const FieldResponse(404, null) : r(body);
  }
}

FieldResponse json(Object? v) => FieldResponse(200, v);

class FakeLocation implements LocationService {
  final fixesOut = StreamController<LocationFix>.broadcast();
  @override
  Future<bool> available() async => true;
  @override
  Future<bool> granted() async => true;
  @override
  Stream<LocationFix> fixes(Duration interval) => fixesOut.stream;
}

LocationFix fix(int t) =>
    LocationFix(lat: 38.7220, lon: -9.1400, accuracyM: 5, tMs: t);

const safeZone = {
  'id': 3,
  'type': 'safe_zone',
  'shape': 'circle',
  'level': 0,
  'x': 0.2,
  'y': 0.2,
  'radius_m': 20,
  'label': 'Barn',
};
const redHq = {
  'id': 4,
  'type': 'hq',
  'shape': 'point',
  'level': 1,
  'x': 0.5,
  'y': 0.5,
  'team': 'red',
};
const parking = {
  'id': 5,
  'type': 'parking',
  'shape': 'polygon',
  'level': 0,
  'points': [
    {'x': 0.6, 'y': 0.6},
    {'x': 0.9, 'y': 0.6},
    {'x': 0.9, 'y': 0.9},
  ],
};
const boundary = {
  'id': 7,
  'type': 'boundary',
  'shape': 'polygon',
  'level': 0,
  'points': [
    {'x': 0.1, 'y': 0.1},
    {'x': 0.9, 'y': 0.1},
    {'x': 0.9, 'y': 0.9},
    {'x': 0.1, 'y': 0.9},
  ],
};

void main() {
  const map = PlanToGround((top, west), (top, east), (bottom, west));

  group('the plan on the ground', () {
    test('a place on the ground goes back to the plan', () {
      final (lat, lon) = map.apply(0.3, 0.7);
      final (x, y) = map.inverse(lat, lon)!;
      expect(x, closeTo(0.3, 1e-9));
      expect(y, closeTo(0.7, 1e-9));
      final (w, h) = map.groundSizeM!;
      expect(w, closeTo(173, 3));
      expect(h, closeTo(222, 3));
      expect(const PlanToGround((1, 1), (1, 1), (1, 1)).inverse(1, 1), isNull);
    });

    test('levels: the controller\'s view, a level not in use is level 0', () {
      final l = FieldLevels.fromApi(levelsApi(count: 3))!;
      expect(l.count, 3);
      expect(l.multi, isTrue);
      expect(l.names, ['Ground', '', 'Roof']);
      expect(
        [l.shown(2), l.shown(7), l.shown(null), l.shown(-1)],
        [2, 0, 0, 0],
      );
      expect(FieldLevels.fromApi(const {}), isNull);
      expect(FieldLevels.single.multi, isFalse);
    });

    test('positions on a level: its own, beacons by their place, GPS by '
        'the map position, and what cannot be placed counted', () {
      final levels = FieldLevels.fromApi(levelsApi())!;
      final (lat, lon) = map.apply(0.25, 0.5);
      final positions = <Map<String, Object?>>[
        {'player_id': 'me', 'source': 'ble', 'level': 1, 'x': 0.4, 'y': 0.4},
        {'player_id': 'ble-nowhere', 'source': 'ble', 'level': 1},
        {
          'player_id': 'gps0',
          'source': 'gps',
          'level': 0,
          'lat': lat,
          'lon': lon,
        },
        {'player_id': 'gps-unsure', 'source': 'gps', 'lat': lat, 'lon': lon},
        {
          'player_id': 'gps-away',
          'source': 'gps',
          'level': 0,
          'lat': 39.0,
          'lon': -9.1,
        },
        {'player_id': 'ble-unsure', 'source': 'ble'},
        {
          'player_id': 'p-roof',
          'source': 'gps',
          'level': 9,
          'lat': lat,
          'lon': lon,
        },
      ];
      final one = markersOn(1, positions, levels, map, 'me');
      expect([for (final m in one.markers) m.playerId], ['me', 'gps-unsure']);
      expect(one.markers.first.own, isTrue);
      expect(one.markers.last.levelKnown, isFalse); // a floor is never guessed
      expect(one.off, 1); // the beacon that is not on the plan
      final zero = markersOn(0, positions, levels, map, 'me');
      // gps0, the unsure one (hollow), the one off the plan, and level 9,
      // which is not in use and so is shown on level 0.
      expect(
        [for (final m in zero.markers) m.playerId],
        ['gps0', 'gps-unsure', 'p-roof'],
      );
      expect(zero.off, 1);
      expect(zero.markers.first.x, closeTo(0.25, 1e-9));
      expect(zero.markers.first.y, closeTo(0.5, 1e-9));
      // Without a map position, a GPS fix cannot be placed.
      expect(markersOn(0, positions, levels, null, 'me').markers, isEmpty);
      // A field without levels: everything is on its one plan, none hollow.
      final single = markersOn(0, positions, FieldLevels.single, map, 'me');
      expect(single.markers.every((m) => m.levelKnown), isTrue);
    });
  });

  group('the loader reads with the player\'s token and tolerates a 404', () {
    test('levels, features, then each level once (again when its image '
        'changed)', () async {
      var stamp = 100;
      final http = FakeFieldHttp({
        'GET /field/levels': (_) => json({
          'levels': [
            {
              'level': 0,
              'name': 'R/C',
              'image': {'updated_at': stamp},
            },
            {'level': 1, 'name': '', 'image': null},
          ],
        }),
        'GET /field/features': (_) => json({
          'features': [safeZone, 'junk'],
        }),
        'GET /field/levels/0/georef': (_) => json({'georef': georefApi()}),
        'GET /field/levels/0/image': (_) =>
            FieldResponse(200, null, bytes: png),
      });
      var token = 'tok1';
      final loader = FieldPlanLoader(() => http, () => token);
      addTearDown(loader.dispose);
      await loader.load();
      expect(loader.levels!.count, 2);
      expect(loader.features, [safeZone]);
      expect(loader.hasPlan, isTrue);
      token = 'tok2'; // renewed after a change of role
      await loader.ensureLevel(0);
      await loader.ensureLevel(0); // kept
      expect(loader.plan(0)!.image, png);
      expect(loader.plan(0)!.map, isNotNull);
      expect(http.calls, [
        'GET /field/levels tok1',
        'GET /field/features tok1',
        'GET /field/levels/0/georef tok2',
        'GET /field/levels/0/image tok2',
      ]);
      // Level 1 has no image and no map position: a plan with neither.
      await loader.ensureLevel(1);
      expect(loader.plan(1)!.image, isNull);
      expect(loader.plan(1)!.map, isNull);
      // The GM changed level 0's plan: fetched again.
      stamp = 101;
      await loader.load(streamFeatures: const []);
      http.calls.clear();
      await loader.ensureLevel(0);
      expect(http.calls, hasLength(2));
      expect(loader.features, isEmpty);
    });

    test(
      'an answer that is not a plan (a phone controller): nothing',
      () async {
        final loader = FieldPlanLoader(() => FakeFieldHttp({}), () => 't');
        addTearDown(loader.dispose);
        await loader.load();
        expect(loader.levels, isNull);
        expect(loader.hasPlan, isFalse);
        await loader.ensureLevel(0); // nothing to ask
      },
    );
  });

  group('the reporter says the floor', () {
    test('none until the player says; then every GPS report; "not sure" '
        'says null; the last fix goes again at once', () async {
      final loc = FakeLocation();
      final sent = <List<Map<String, Object?>>>[];
      final r = PositionReporter(
        location: loc,
        interval: const Duration(hours: 1),
        send: (reports) async {
          sent.add(reports);
          return {'stored': reports.length, 'interval_s': 10};
        },
      )..start();
      addTearDown(r.dispose);
      loc.fixesOut.add(fix(1000));
      await Future<void>.delayed(Duration.zero);
      await r.flush();
      expect(sent.single.single.containsKey('level'), isFalse);
      expect(r.levelGiven, isFalse);
      r.setLevel(2);
      await Future<void>.delayed(Duration.zero);
      expect(sent, hasLength(2)); // sent at once, not in 10 s
      expect(sent.last.single['level'], 2);
      expect(sent.last.single['t'], 1000);
      loc.fixesOut.add(fix(2000));
      await Future<void>.delayed(Duration.zero);
      await r.flush();
      expect(sent.last.single['level'], 2);
      r.setLevel(null);
      await Future<void>.delayed(Duration.zero);
      expect(sent.last.single.containsKey('level'), isTrue);
      expect(sent.last.single['level'], isNull);
      expect(r.level, isNull);
      expect(r.levelGiven, isTrue);
    });

    test('a choice before sharing starts goes with the first fix', () async {
      final loc = FakeLocation();
      final sent = <List<Map<String, Object?>>>[];
      final r = PositionReporter(
        location: loc,
        interval: const Duration(hours: 1),
        send: (reports) async {
          sent.add(reports);
          return {'stored': 1, 'interval_s': 10};
        },
      );
      addTearDown(r.dispose);
      r.setLevel(1);
      expect(sent, isEmpty);
      r.start();
      loc.fixesOut.add(fix(5));
      await Future<void>.delayed(Duration.zero);
      await r.flush();
      expect(sent.single.single['level'], 1);
    });
  });

  group('the player screen', () {
    PinnedField field() => PinnedField(
      fieldId: 'f1',
      fieldName: 'Campo',
      caPem: '',
      caSha256: Uint8List(32),
      urls: const ['https://10.0.0.1:8443'],
    );

    FieldFeed feed({List<Map<String, Object?>> positions = const []}) {
      final f = FieldFeed(
        FieldLink(Uri.parse('https://10.0.0.1:8443'), 'tok', field: field()),
      );
      f.onMessage({
        'type': 'hello',
        'game': {
          'id': 1,
          'name': 'Domingo',
          'state': 'running',
          'teams': ['red', 'blue'],
        },
        'me': {'player_id': 'p1', 'role': 'player', 'team': 'red'},
        'positions': positions,
      });
      return f;
    }

    Future<(FakeFieldHttp, FakeLocation, FieldFeed)> open(
      WidgetTester tester, {
      required Map<String, Object?>? levels,
      List<Map<String, Object?>> features = const [],
      List<Map<String, Object?>> positions = const [],
      double width = 360,
    }) async {
      tester.view.physicalSize = Size(width, 1800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final fd = feed(positions: positions);
      addTearDown(fd.dispose);
      final http = FakeFieldHttp({
        if (levels != null) 'GET /field/levels': (_) => json(levels),
        'GET /field/features': (_) => json({'features': features}),
        'GET /field/levels/0/georef': (_) => json({'georef': georefApi()}),
        'GET /field/levels/1/georef': (_) => json({'georef': georefApi()}),
        'GET /field/levels/0/image': (_) =>
            FieldResponse(200, null, bytes: png),
        'GET /field/levels/1/image': (_) =>
            FieldResponse(200, null, bytes: png),
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
          home: PlayerScreen(link: fd.link, feed: fd),
        ),
      );
      await settle(tester);
      return (http, loc, fd);
    }

    testWidgets('a field with floors: choose one, and it goes with the GPS '
        'reports, once and kept', (tester) async {
      final (http, loc, _) = await open(tester, levels: levelsApi());
      expect(find.byKey(const Key('player-level-picker')), findsNothing);
      await tester.tap(find.byKey(const Key('player-share-position')));
      await settle(tester);
      expect(find.byKey(const Key('player-level-picker')), findsOneWidget);
      expect(find.text('Which floor are you on?'), findsOneWidget);
      expect(find.text('Ground'), findsWidgets);
      expect(find.text('Level 1'), findsWidgets); // unnamed: its number
      expect(find.byKey(const Key('player-level-unknown')), findsOneWidget);
      loc.fixesOut.add(fix(1000));
      await settle(tester);
      await tester.tap(find.byKey(const Key('player-level-1')));
      await settle(tester);
      expect(http.posted.last['level'], 1);
      expect(
        tester
            .widget<ChoiceChip>(find.byKey(const Key('player-level-1')))
            .selected,
        isTrue,
      );
      await tester.tap(find.byKey(const Key('player-level-unknown')));
      await settle(tester);
      expect(http.posted.last.containsKey('level'), isTrue);
      expect(http.posted.last['level'], isNull);
      // Sharing off and on: the choice is kept, no second question.
      await tester.tap(find.byKey(const Key('player-share-position')));
      await settle(tester);
      await tester.tap(find.byKey(const Key('player-share-position')));
      await settle(tester);
      expect(tester.takeException(), isNull);
    });

    testWidgets('a field without floors is not asked', (tester) async {
      await open(tester, levels: levelsApi(count: 1));
      await tester.tap(find.byKey(const Key('player-share-position')));
      await settle(tester);
      expect(find.byKey(const Key('player-level-picker')), findsNothing);
    });

    testWidgets('the map at a phone\'s width: the plan, the features this '
        'player was sent and the positions on their floor', (tester) async {
      final (_, _, fd) = await open(
        tester,
        levels: levelsApi(),
        features: [safeZone, parking, boundary, redHq],
        positions: [
          {
            'player_id': 'p1',
            'team': 1,
            'source': 'ble',
            'level': 1,
            'x': 0.4,
            'y': 0.4,
          },
          {
            'player_id': 'mate',
            'team': 1,
            'source': 'gps',
            'level': 0,
            'lat': 38.7220,
            'lon': -9.1400,
          },
          {
            'player_id': 'upstairs',
            'team': 1,
            'source': 'ble',
            'level': 1,
            'x': 0.6,
            'y': 0.2,
          },
          {'player_id': 'lost', 'team': 2, 'source': 'ble', 'level': 1},
        ],
      );
      expect(find.byKey(const Key('player-map')), findsOneWidget);
      expect(find.text('Field map'), findsOneWidget);
      // Opens on the player's own floor (level 1, from their position).
      expect(
        tester
            .widget<ChoiceChip>(find.byKey(const Key('map-level-1')))
            .selected,
        isTrue,
      );
      expect(find.byKey(const Key('map-me')), findsOneWidget);
      expect(find.byKey(const Key('map-player-upstairs')), findsOneWidget);
      expect(find.byKey(const Key('map-player-mate')), findsNothing);
      expect(find.byKey(const Key('map-feature-4')), findsOneWidget); // red HQ
      expect(find.byKey(const Key('map-feature-3')), findsNothing); // level 0
      expect(find.byKey(const Key('map-off-plan')), findsOneWidget);
      expect(find.text('1 positions not on this plan'), findsOneWidget);
      final plan = tester.getSize(find.byKey(const Key('map-plan')));
      expect(plan.width, lessThanOrEqualTo(360));
      expect(plan.width / plan.height, closeTo(173 / 222, 0.03));
      // Level 0: the safe zone and the car park (pins), no boundary pin (it
      // is the outline), the mate; not the other floor's.
      await tester.tap(find.byKey(const Key('map-level-0')));
      await settle(tester);
      expect(find.byKey(const Key('map-feature-3')), findsOneWidget);
      expect(find.byKey(const Key('map-feature-5')), findsOneWidget);
      expect(find.byKey(const Key('map-feature-7')), findsNothing);
      expect(find.byKey(const Key('map-feature-4')), findsNothing);
      expect(find.byKey(const Key('map-player-mate')), findsOneWidget);
      expect(find.byKey(const Key('map-player-upstairs')), findsNothing);
      expect(find.byKey(const Key('map-me')), findsNothing);
      expect(find.byKey(const Key('map-shapes')), findsOneWidget);
      expect(find.byKey(const Key('map-legend')), findsOneWidget);
      expect(find.text('Safe zone'), findsOneWidget);
      expect(find.text('Field boundary'), findsOneWidget);
      // Names for a screen reader, not only colours.
      final semantics = tester.ensureSemantics();
      await settle(tester);
      expect(find.bySemanticsLabel('Safe zone: Barn'), findsOneWidget);
      // The stream moves a player: the map follows; a player who stops being
      // sent (the controller's rules) disappears.
      fd.onMessage({
        'type': 'player_position',
        'position': {
          'player_id': 'mate',
          'team': 1,
          'source': 'ble',
          'level': 1,
          'x': 0.3,
          'y': 0.3,
        },
      });
      await settle(tester);
      expect(find.byKey(const Key('map-player-mate')), findsNothing);
      fd.onMessage({'type': 'positions', 'positions': <Object?>[]});
      await tester.tap(find.byKey(const Key('map-level-1')));
      await settle(tester);
      expect(find.byKey(const Key('map-player-upstairs')), findsNothing);
      semantics.dispose();
      expect(tester.takeException(), isNull);
    });

    testWidgets('a floor not known: the dot is hollow, and said', (
      tester,
    ) async {
      await open(
        tester,
        levels: levelsApi(),
        positions: [
          {
            'player_id': 'p1',
            'team': 1,
            'source': 'gps',
            'lat': 38.7220,
            'lon': -9.1400,
          },
        ],
        features: [safeZone],
      );
      // Not known: the map opens on level 0 and draws the player hollow.
      expect(find.byKey(const Key('map-me')), findsOneWidget);
      expect(find.byKey(const Key('map-level-unknown')), findsOneWidget);
    });

    testWidgets('no plan at all (a phone controller answers 404): no map', (
      tester,
    ) async {
      await open(tester, levels: null);
      expect(find.byKey(const Key('player-map')), findsNothing);
      expect(find.byKey(const Key('player-game')), findsOneWidget);
    });

    testWidgets('nothing to draw: no map', (tester) async {
      await open(tester, levels: levelsApi(count: 1, images: false));
      expect(find.byKey(const Key('player-map')), findsNothing);
    });

    testWidgets('a plan of one floor: no floor buttons, the plan and its '
        'features', (tester) async {
      await open(
        tester,
        levels: levelsApi(count: 1),
        features: [safeZone, boundary],
        width: 320,
      );
      expect(find.byKey(const Key('player-map')), findsOneWidget);
      expect(find.byKey(const Key('map-level-0')), findsNothing);
      expect(find.byKey(const Key('map-feature-3')), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}

Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 6; i++) {
    await tester.pump(const Duration(milliseconds: 10));
  }
}
