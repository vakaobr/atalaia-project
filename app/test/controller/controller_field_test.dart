// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The field plan on the phone controller (lib/controller/controller_field.dart,
// slice S7a of PE24) beyond the shared contract cases: the map position's
// arithmetic against the Pi's georef.py (numbers it printed), the plans as
// files in the controller's folder (kept across a restart, a crash's leftover
// files removed, all or nothing for the field from a map), the 200-feature
// limit, the visibility table and the request body limits of the field's
// paths.

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_checkin.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_field.dart';
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:flutter_test/flutter_test.dart';

final png = base64.decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAC'
  'hwGA60e6kgAAAABJRU5ErkJggg==',
);

Map<String, Object?> pt(num x, num y, num lat, num lon) => {
  'x': x,
  'y': y,
  'lat': lat,
  'lon': lon,
};

/// A store whose next write of the field document fails (a full disk).
class FailingStore extends FileControllerStore {
  FailingStore(super.directory);
  var failField = false;

  @override
  void putDocument(String name, Object? value) {
    if (failField && name == 'field') {
      throw const FileSystemException('no space left on device');
    }
    super.putDocument(name, value);
  }
}

void main() {
  group('the map position (georef.py, the same arithmetic)', () {
    test('two corners and three points give the corners back', () {
      for (final points in [
        [pt(0, 0, 38.72, -9.16), pt(1, 1, 38.71, -9.14)],
        [
          pt(0, 0, 38.72, -9.16),
          pt(1, 0, 38.72, -9.14),
          pt(0, 1, 38.71, -9.16),
        ],
      ]) {
        final api = Georef(checkControlPoints(points)).toApi();
        final c = (api['corners']! as Map).cast<String, Map<String, Object?>>();
        expect(c['top_left'], {'lat': 38.72, 'lon': -9.16});
        expect(c['top_right'], {'lat': 38.72, 'lon': -9.14});
        expect(c['bottom_right'], {'lat': 38.71, 'lon': -9.14});
        expect(c['bottom_left'], {'lat': 38.71, 'lon': -9.16});
        expect(api['residual_m'], 0.0);
        expect(api['kind'], points.length == 2 ? 'corners' : 'affine');
      }
    });

    test('four points: least squares, the residual as the Pi gives it', () {
      final api = Georef(
        checkControlPoints([
          pt(0.1, 0.1, 38.7195, -9.1585),
          pt(0.9, 0.15, 38.7192, -9.1418),
          pt(0.85, 0.9, 38.7111, -9.1421),
          pt(0.12, 0.88, 38.7113, -9.1583),
        ]),
      ).toApi();
      expect(api['residual_m'], 22.73);
      final c = (api['corners']! as Map).cast<String, Map<String, Object?>>();
      // Printed by controller/atalaia_controller/georef.py for these points.
      const pi = {
        'top_left': (38.72059677321109, -9.160917065546501),
        'top_right': (38.72076339668915, -9.139460024524832),
        'bottom_right': (38.71011544541027, -9.139116235670981),
        'bottom_left': (38.70994882193221, -9.160573276692652),
      };
      pi.forEach((name, ll) {
        expect(c[name]!['lat'], closeTo(ll.$1, 1e-12), reason: name);
        expect(c[name]!['lon'], closeTo(ll.$2, 1e-12), reason: name);
      });
    });

    test('refused as the Pi refuses them', () {
      for (final (points, why) in [
        ([pt(0, 0, 38.72, 179.99), pt(1, 1, 38.71, -179.99)], '180th'),
        ([pt(0, 0, 38.72, -9.16), pt(1, 1, 39.72, -9.14)], 'mirror'),
        (
          [
            pt(0, 0, 38.72, -9.16),
            pt(1, 0, 38.72, -9.14),
            pt(0, 1, 38.71, -9.16),
            pt(1, 1, 38.60, -9.00),
          ],
          'one flat image',
        ),
        ([pt(0, 0, 38.72, -9.16), pt(0.02, 1, 38.71, -9.14)], 'corners'),
        ([pt(0, 0, 38.72, -9.16), pt(1, 1, 38.40, -8.70)], '20 km'),
      ]) {
        expect(
          () => Georef(checkControlPoints(points)),
          throwsA(
            isA<GeorefException>().having(
              (e) => e.message,
              'message',
              contains(why),
            ),
          ),
          reason: why,
        );
      }
      expect(
        () => checkControlPoints([pt(0, 0, 90, 0), pt(1, 1, 0, 1)]),
        throwsA(isA<GeorefException>()),
      );
    });
  });

  group('the plans in the controller\'s folder', () {
    late Directory tmp;
    setUp(() => tmp = Directory.systemTemp.createTempSync('atalaia-field-'));
    tearDown(() => tmp.deleteSync(recursive: true));

    (ControllerEngine, ControllerField) open([ControllerStore? store]) {
      final e = ControllerEngine(
        store: store ?? FileControllerStore(Directory('${tmp.path}/store')),
      );
      return (e, ControllerField(e, dir: Directory('${tmp.path}/field')));
    }

    List<String> files() => [
      for (final f in Directory('${tmp.path}/field').listSync())
        f.uri.pathSegments.last,
    ]..sort();

    test('a plan is a file; a new one replaces it; a restart keeps it', () {
      var (_, field) = open();
      field.putImage(0, 'image/png', png);
      expect(files(), ['plan-1.img']);
      final jpeg = Uint8List.fromList([0xff, 0xd8, 0xff, 1, 2, 3]);
      field.putImage(0, 'image/jpeg; q=1', jpeg);
      expect(files(), ['plan-2.img']);
      // The document has only the plan's type and size, not its bytes.
      final doc = File('${tmp.path}/store/docs/field.json').readAsStringSync();
      expect(doc.length, lessThan(400));
      (_, field) = open();
      expect(field.image(0).$1, 'image/jpeg');
      expect(field.image(0).$2, jpeg);
      expect(field.deleteImage(0), {'deleted': true});
      expect(files(), isEmpty);
    });

    test("a crash's leftover file is removed at the next start", () {
      var (_, field) = open();
      field.putImage(0, 'image/png', png);
      File('${tmp.path}/field/plan-7.img').writeAsBytesSync([1, 2, 3]);
      File('${tmp.path}/field/plan-8.img.tmp').writeAsBytesSync([1]);
      (_, field) = open();
      expect(files(), ['plan-1.img']);
      expect(field.image(0).$2, png);
    });

    test('the field from a map is all or nothing', () {
      final store = FailingStore(Directory('${tmp.path}/store'));
      final (engine, field) = open(store);
      field
        ..putImage(0, 'image/png', png)
        ..putGeoref(0, {
          'points': [pt(0, 0, 38.72, -9.16), pt(1, 1, 38.71, -9.14)],
        });
      final heard = <Map<String, Object?>>[];
      engine.addListener(heard.add);
      store.failField = true;
      final body = {
        'content_type': 'image/jpeg',
        'image': base64.encode([0xff, 0xd8, 0xff, 9, 9]),
        'bounds': {'north': 38.73, 'south': 38.70, 'west': -9.2, 'east': -9.1},
        'outline': [
          {'lat': 38.72, 'lon': -9.19},
          {'lat': 38.72, 'lon': -9.11},
          {'lat': 38.71, 'lon': -9.11},
        ],
      };
      expect(() => field.fromMap(0, body), throwsA(isA<FileSystemException>()));
      expect(heard, isEmpty);
      // Nothing changed: the old plan, its map position, no boundary.
      expect(field.image(0).$1, 'image/png');
      expect(field.image(0).$2, png);
      expect(field.georef0()['georef'], containsPair('kind', 'corners'));
      expect(field.visibleFeatures(ApiViewer.gm), isEmpty);
      // The new plan's file is left behind until the next start.
      expect(files(), ['plan-1.img', 'plan-2.img']);
      store.failField = false;
      final (_, again) = open(store);
      expect(files(), ['plan-1.img']);
      final out = again.fromMap(0, body);
      expect(out['boundary_new'], true);
      expect(again.image(0).$1, 'image/jpeg');
      expect(files(), ['plan-2.img']);
    });

    test('in memory without a folder', () {
      final e = ControllerEngine();
      final field = ControllerField(e);
      field.putImage(0, 'image/webp', png);
      expect(field.image(0).$1, 'image/webp');
      expect(field.levelsView()['levels'], [
        {
          'level': 0,
          'name': '',
          'image': {
            'content_type': 'image/webp',
            'bytes': png.length,
            'updated_at': isA<double>(),
          },
          'own_georef': false,
          'grid': {'enabled': false, 'rows': 8, 'cols': 8},
        },
      ]);
    });

    test('the field grid (MF-81 to MF-93): kept, and all or nothing with '
        'the field from a map', () {
      final store = FailingStore(Directory('${tmp.path}/store'));
      var (engine, field) = open(store);
      expect(field.putGrid(0, {'enabled': true, 'rows': 3, 'cols': 4}), {
        'level': 0,
        'grid': {'enabled': true, 'rows': 3, 'cols': 4},
      });
      final heard = <Map<String, Object?>>[];
      engine.addListener(heard.add);
      store.failField = true;
      final body = {
        'content_type': 'image/png',
        'image': base64.encode(png),
        'bounds': {'north': 38.73, 'south': 38.70, 'west': -9.2, 'east': -9.1},
        'outline': [
          {'lat': 38.72, 'lon': -9.19},
          {'lat': 38.72, 'lon': -9.11},
          {'lat': 38.71, 'lon': -9.11},
        ],
        'grid': {'enabled': true, 'rows': 26, 'cols': 30},
      };
      expect(() => field.fromMap(0, body), throwsA(isA<FileSystemException>()));
      expect(
        () => field.putGrid(0, {'enabled': false}),
        throwsA(isA<FileSystemException>()),
      );
      expect(heard, isEmpty);
      expect(field.grid(0), {'enabled': true, 'rows': 3, 'cols': 4});
      store.failField = false;
      (engine, field) = open(store);
      expect(field.fromMap(0, body)['grid'], {
        'enabled': true,
        'rows': 26,
        'cols': 30,
      });
      (_, field) = open(store);
      expect(field.levelGrid(0)['grid'], {
        'enabled': true,
        'rows': 26,
        'cols': 30,
      });
    });
  });

  test("the grid's check refuses what the Pi's refuses", () {
    for (final bad in <Object?>[
      null,
      <Object?>[],
      <String, Object?>{},
      {'enabled': 'yes'},
      {'enabled': true, 'rows': 0},
      {'enabled': true, 'rows': 53},
      {'enabled': true, 'cols': 2.5},
      {'enabled': true, 'cols': true},
      {'enabled': true, 'cols': '4'},
      {'enabled': true, 'size': 4},
    ]) {
      expect(
        () => checkGrid(bad, gridDefault),
        throwsA(isA<ControllerError>()),
        reason: '$bad',
      );
    }
    expect(checkGrid({'enabled': false}, {'rows': 2, 'cols': 52}), {
      'enabled': false,
      'rows': 2,
      'cols': 52,
    });
  });

  test('at most 200 map features; the field from a map then only replaces '
      'a boundary', () {
    final e = ControllerEngine();
    final field = ControllerField(e);
    for (var i = 0; i < mapFeaturesMax; i++) {
      field.addFeature({
        'type': 'objective',
        'shape': 'point',
        'x': 0.5,
        'y': 0.5,
      });
    }
    expect(
      () => field.addFeature({'type': 'hq', 'shape': 'point', 'x': 0, 'y': 0}),
      throwsA(isA<ControllerError>().having((e) => e.status, 'status', 409)),
    );
    final body = {
      'content_type': 'image/png',
      'image': base64.encode(png),
      'bounds': {'north': 38.73, 'south': 38.70, 'west': -9.2, 'east': -9.1},
      'outline': [
        {'lat': 38.72, 'lon': -9.19},
        {'lat': 38.72, 'lon': -9.11},
        {'lat': 38.71, 'lon': -9.11},
      ],
    };
    expect(
      () => field.fromMap(0, body),
      throwsA(isA<ControllerError>().having((e) => e.status, 'status', 409)),
    );
    field.deleteFeature(1);
    expect(field.fromMap(0, body)['boundary_new'], true);
    expect(field.fromMap(0, body)['boundary_new'], false);
  });

  test('who sees which feature (MF-3, MF-4)', () {
    final e = ControllerEngine();
    final field = ControllerField(e);
    final gid =
        e.createGame({'name': 'g', 'mode_id': 'org.atalaia.domination'})['id']!
            as int;
    for (final f in [
      {'type': 'safe_zone', 'shape': 'point', 'x': 0, 'y': 0},
      {'type': 'respawn', 'shape': 'point', 'x': 0, 'y': 0, 'team': 'red'},
      {
        'type': 'hq',
        'shape': 'point',
        'x': 0,
        'y': 0,
        'team': 'blue',
        'visibility': 'everyone',
      },
      {
        'type': 'parking',
        'shape': 'point',
        'x': 0,
        'y': 0,
        'visibility': 'organisers',
      },
    ]) {
      field.addFeature(f);
    }
    List<Object?> ids(ApiViewer v) => [
      for (final f in field.visibleFeatures(v)) f['id'],
    ];
    ApiViewer player(int team, String role) => ApiViewer('player', {
      'role': role,
      'player_id': 'p',
      'game_id': gid,
      'team': team,
      'squad': 0,
    });
    expect(ids(ApiViewer.gm), [1, 2, 3, 4]);
    expect(ids(ApiViewer.read), [1, 3]);
    expect(ids(player(1, 'player')), [1, 2, 3]); // red
    expect(ids(player(2, 'player')), [1, 3]); // blue: its HQ is everyone's
    expect(ids(player(0, 'player')), [1, 3]); // no team yet
    expect(ids(player(0, 'marshal')), [1, 2, 3, 4]);
  });

  test("the field's paths take a whole plan's body", () async {
    final e = ControllerEngine();
    final api = ControllerApi(e, gmToken: 'gm', readToken: 'rd');
    final server = await api.serve();
    addTearDown(() => server.close(force: true));
    final client = HttpClient();
    addTearDown(client.close);
    Future<int> put(String path, int size, String type) async {
      final r = await client.put('127.0.0.1', server.port, path);
      r.headers
        ..set('Authorization', 'Bearer gm')
        ..set('Content-Type', type);
      r.contentLength = size;
      r.add(Uint8List(size));
      final res = await r.close();
      await res.drain<void>();
      return res.statusCode;
    }

    expect(await put('/api/v1/field/image', fieldImageMax, 'image/png'), 200);
    expect(
      await put('/api/v1/field/image', fieldImageMax + 1, 'image/png'),
      413,
    );
    expect(e.field!.image(0).$2.length, fieldImageMax);
  });
}
