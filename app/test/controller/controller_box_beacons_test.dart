// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The Field Boxes as iBeacons on the phone controller (decisions BBC-1 to
// BBC-12, lib/controller/controller_box_beacons.dart; the Pi's twin is
// controller/tests/test_box_beacons.py): the UUID and the advertisement bytes
// against the shared vectors (protocol/vectors/box_beacon.json, made from
// hashlib alone), then the registration beyond the shared contract case "box
// beacons": a box registered by itself from its place and following it, the
// room (the box's name or the GM's), a box disabled and the field's switch
// off, a level that is not in use, what staff and everyone else read, and a
// tag that may not take the boxes' major.

import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_checkin.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_field.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

Uint8List hex(String s) => Uint8List.fromList([
  for (var i = 0; i < s.length; i += 2)
    int.parse(s.substring(i, i + 2), radix: 16),
]);

String hexOf(List<int> b) =>
    [for (final x in b) x.toRadixString(16).padLeft(2, '0')].join();

void main() {
  group('the shared vectors', () {
    final v = loadVectors('box_beacon.json');
    test('the UUID of every join key', () {
      expect(cases(v, 'uuids').length, greaterThanOrEqualTo(3));
      for (final c in cases(v, 'uuids')) {
        expect(
          deriveBoxBeaconUuid(hex(c['join_key'] as String)),
          c['uuid_text'],
        );
      }
    });

    test('the advertisement bytes of a box', () {
      expect(v['major'], boxBeaconMajor);
      for (final c in cases(v, 'adv')) {
        final adv = boxBeaconAdv(
          hex(c['join_key'] as String),
          c['node_id'] as int,
          measuredPower: c['measured_power'] as int,
        );
        expect(adv.length, 30);
        expect(hexOf(adv), c['adv'], reason: '${c['id']}');
        expect(boxBeaconId(c['node_id'] as int), c['id']);
      }
    });
  });

  group('registered from the box\'s place', () {
    late ControllerEngine engine;
    late ControllerField field;
    late int gid;
    final key = Uint8List.fromList(List.generate(32, (i) => 100 + i));
    late String uuid;

    ApiViewer player(int g) => ApiViewer('player', {
      'player_id': 'p-a',
      'game_id': g,
      'team': 1,
      'squad': 0,
      'role': 'player',
    });

    List<Map<String, Object?>> boxes(ApiViewer v) => [
      for (final b in field.beaconsFor(v)['beacons']! as List)
        if ((b as Map)['id'].toString().startsWith('$boxBeaconMajor:'))
          b.cast<String, Object?>(),
    ];

    setUp(() {
      engine = ControllerEngine();
      engine.joinKey = key;
      field = ControllerField(engine);
      gid =
          engine.createGame({
                'name': 'g',
                'mode_id': 'org.atalaia.domination',
                'teams': ['red', 'blue'],
                'assignments': {'4': 'zone', '5': 'zone'},
              })['id']!
              as int;
      uuid = deriveBoxBeaconUuid(key);
    });
    tearDown(() => engine.close());

    test('a box is registered once placed, and follows its place', () {
      expect(boxes(ApiViewer.gm), isEmpty); // not placed: no level, no place
      field.putPlace(gid, 4, {'x': 0.25, 'y': 0.5});
      final b = boxes(ApiViewer.gm).single;
      expect(b['id'], '$boxBeaconMajor:4');
      expect(b['uuid'], uuid);
      expect(b['kind'], 'box');
      expect((b['major'], b['minor'], b['node_id']), (boxBeaconMajor, 4, 4));
      expect((b['room'], b['level'], b['x'], b['y']), ('node-4', 0, 0.25, 0.5));
      expect(b['enabled'], true);
      field.putPlace(gid, 4, {'x': 0.8, 'y': 0.1});
      expect(boxes(ApiViewer.gm).single['x'], 0.8);
      field.putPlace(gid, 5, {'x': 0.4, 'y': 0.4});
      expect([for (final x in boxes(ApiViewer.gm)) x['minor']], [4, 5]);
    });

    test('a level change moves the beacon; levels off show level 0', () {
      field.putLevels({'enabled': true, 'count': 3});
      field.putPlace(gid, 4, {'x': 0.3, 'y': 0.3, 'level': 2});
      expect(boxes(ApiViewer.gm).single['level'], 2);
      field.putPlace(gid, 4, {'x': 0.3, 'y': 0.3, 'level': 1});
      expect(boxes(ApiViewer.gm).single['level'], 1);
      field.putLevels({'enabled': false, 'count': 3});
      expect(boxes(ApiViewer.gm).single['level'], 0);
    });

    test('the room is the box\'s name or the GM\'s', () {
      field.putPlace(gid, 4, {'x': 0.5, 'y': 0.5});
      final r = field.updateBoxBeacon(4, {'room': '  Server   room '});
      expect((r['room'], r['room_given']), ('Server room', true));
      expect(boxes(ApiViewer.gm).single['name'], 'node-4');
      final back = field.updateBoxBeacon(4, {'room': null});
      expect((back['room'], back['room_given']), ('node-4', false));
      for (final bad in <Object?>[
        {'room': 'x' * 49},
        {'room': 5},
        {'room': 'a\tb'},
        {'colour': 1},
        <String, Object?>{},
        {'enabled': 'yes'},
        'room',
      ]) {
        expect(
          () => field.updateBoxBeacon(4, bad),
          throwsA(isA<ControllerError>()),
        );
      }
      expect(
        () => field.updateBoxBeacon(99, {'room': 'x'}),
        throwsA(isA<ControllerError>()),
      );
    });

    test('everyone else is given the id and uuid of each enabled box', () {
      field.putPlace(gid, 4, {'x': 0.5, 'y': 0.5});
      field.putPlace(gid, 5, {'x': 0.5, 'y': 0.5});
      final short = [
        {'id': '$boxBeaconMajor:4', 'uuid': uuid},
        {'id': '$boxBeaconMajor:5', 'uuid': uuid},
      ];
      expect(boxes(ApiViewer.read), short);
      expect(boxes(player(gid)), short);
      expect(field.beaconsFor(ApiViewer.read), isNot(contains('box_beacons')));
      expect(field.beaconsFor(ApiViewer.gm)['box_beacons'], {
        'enabled': true,
        'major': boxBeaconMajor,
        'uuid': uuid,
      });
    });

    test('a box disabled, and the field\'s switch off', () {
      field.putPlace(gid, 4, {'x': 0.5, 'y': 0.5});
      field.putPlace(gid, 5, {'x': 0.5, 'y': 0.5});
      expect(field.updateBoxBeacon(4, {'enabled': false})['enabled'], false);
      final staff = {for (final b in boxes(ApiViewer.gm)) b['minor']: b};
      expect((staff[4]!['enabled'], staff[5]!['enabled']), (false, true));
      expect(
        [for (final b in boxes(ApiViewer.read)) b['id']],
        ['$boxBeaconMajor:5'],
      );
      expect(field.boxBeaconPlace('$boxBeaconMajor:4'), isNull);
      field.updateBoxBeacon(4, {'enabled': true});
      expect(field.boxBeaconPlace('$boxBeaconMajor:4'), {
        'beacon_id': '$boxBeaconMajor:4',
        'room': 'node-4',
        'level': 0,
        'x': 0.5,
        'y': 0.5,
      });
      expect(field.setBoxBeaconsEnabled({'enabled': false})['enabled'], false);
      expect(boxes(ApiViewer.read), isEmpty);
      expect(field.boxBeaconPlace('$boxBeaconMajor:4'), isNull);
      expect(boxes(ApiViewer.gm), hasLength(2)); // staff still see them
      for (final bad in <Object?>[
        <String, Object?>{},
        {'enabled': 1},
        {'enabled': true, 'x': 1},
      ]) {
        expect(
          () => field.setBoxBeaconsEnabled(bad),
          throwsA(isA<ControllerError>()),
        );
      }
      field.setBoxBeaconsEnabled({'enabled': true});
      expect(boxes(ApiViewer.read), hasLength(2));
    });

    test('a tag cannot take the boxes\' major; tags and boxes coexist', () {
      field.putPlace(gid, 4, {'x': 0.5, 'y': 0.5});
      expect(
        () => field.addBeacon({
          'uuid': 'FDA50693-A4E2-4FB1-AFCF-C28847DC5D9F',
          'major': boxBeaconMajor,
          'minor': 4,
          'room': 'Clash',
        }),
        throwsA(isA<ControllerError>()),
      );
      field.addBeacon({
        'uuid': 'FDA50693-A4E2-4FB1-AFCF-C28847DC5D9F',
        'major': 1,
        'minor': 1,
        'room': 'Lobby',
      });
      final ids = [
        for (final b in field.beaconsFor(ApiViewer.read)['beacons']! as List)
          (b as Map)['id'],
      ];
      expect(ids, ['1:1', '$boxBeaconMajor:4']);
      expect(field.beaconPlace('1:1')!['room'], 'Lobby');
      expect(field.beaconPlace('$boxBeaconMajor:4')!['room'], 'node-4');
    });

    test('with no live game or no join key there are no box beacons', () {
      final bare = ControllerField(ControllerEngine());
      expect(bare.boxBeacons(), isEmpty);
      engine.joinKey = Uint8List(0);
      field.putPlace(gid, 4, {'x': 0.5, 'y': 0.5});
      expect(field.boxBeacons(), isEmpty);
      expect(field.boxBeaconsStatus()['uuid'], isNull);
    });
  });
}
