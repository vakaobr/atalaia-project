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
import 'package:atalaia_app/protocol/join_payload.dart';
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

    test('a standby takes the primary\'s choices and serves the same '
        'registry after a failover (BBC-20)', () {
      final standby = ControllerEngine()..joinKey = key;
      addTearDown(standby.close);
      final sfield = ControllerField(standby);
      // Places the standby can hold exactly (key 22 carries 16-bit numbers).
      double exact(double v) => dequantizePlace(quantizePlace(v));
      for (final n in [4, 5]) {
        field.putPlace(gid, n, {'x': exact(0.1 * n), 'y': exact(0.5)});
      }
      // Before the standby joins: box 4 disabled, box 5 given a room.
      field.updateBoxBeacon(4, {'enabled': false});
      field.updateBoxBeacon(5, {'room': 'Kitchen'});
      final first = engine.issueJoin({'kind': 'controller'})['text']! as String;
      final j = decodeJoin(joinFromText(first), key);
      expect(j.boxBeacons!.off, [4]);
      expect(j.boxBeacons!.rooms, {5: 'Kitchen'});
      expect(j.boxBeacon, true);
      expect(standby.joinAsStandby(first)['id'], gid);
      // The boxes the standby knows and where the GM put them there.
      for (final n in [4, 5]) {
        standby.store.upsertNode(gid, {'node_id': n, 'name': 'node-$n'});
        sfield.putPlace(gid, n, {'x': 0.3, 'y': 0.9});
      }
      // The primary's later choices reach it by a join made again.
      field.setBoxBeaconsEnabled({'enabled': false});
      field.updateBoxBeacon(4, {'enabled': true});
      field.updateBoxBeacon(5, {'enabled': false, 'room': 'Hall'});
      field.setBoxBeaconsEnabled({'enabled': true});
      field.updateBoxBeacon(4, {'room': 'Garage'});
      expect(
        sfield.boxBeaconsEnabled,
        true,
        reason: 'what the first join said, until the next',
      );
      final second =
          engine.issueJoin({'kind': 'controller'})['text']! as String;
      expect(standby.joinAsStandby(second)['id'], gid);
      expect(standby.liveGame?['joined'], true);
      for (final viewer in [ApiViewer.gm, ApiViewer.read, player(gid)]) {
        expect(sfield.beaconsFor(viewer), field.beaconsFor(viewer));
      }
      final by = {for (final b in boxes(ApiViewer.gm)) b['minor']: b};
      expect((by[4]!['room'], by[4]!['enabled']), ('Garage', true));
      expect((by[5]!['room'], by[5]!['enabled']), ('Hall', false));
      // The field switch off, then joined again: the standby is off too, and
      // a phone listens for no box on either.
      field.setBoxBeaconsEnabled({'enabled': false});
      standby.joinAsStandby(engine.issueJoin({'kind': 'controller'})['text']);
      expect(sfield.boxBeaconsEnabled, false);
      expect(
        sfield.beaconsFor(ApiViewer.read),
        field.beaconsFor(ApiViewer.read),
      );
      expect(boxes(ApiViewer.read), isEmpty);
      expect(sfield.boxBeaconPlace('$boxBeaconMajor:4'), isNull);
      // Back on, with nothing set per box: the standby's own choices go too.
      field.setBoxBeaconsEnabled({'enabled': true});
      field.updateBoxBeacon(5, {'enabled': true, 'room': null});
      field.updateBoxBeacon(4, {'room': null});
      standby.joinAsStandby(engine.issueJoin({'kind': 'controller'})['text']);
      expect(sfield.beaconsFor(ApiViewer.gm), field.beaconsFor(ApiViewer.gm));
      expect(standby.store.getSetting('box_beacons_off:$gid'), isNull);
      expect(standby.store.getSetting('box_beacon_rooms:$gid'), isNull);
    });

    test('a standby takes the primary\'s box places, a move reaches it with '
        'the next join, and it serves them with no HELLO (BBC-25)', () {
      final standby = ControllerEngine()..joinKey = key;
      addTearDown(standby.close);
      final sfield = ControllerField(standby);
      field.putLevels({'enabled': true, 'count': 3});
      sfield.putLevels({'enabled': true, 'count': 3});
      field.putPlace(gid, 4, {'x': 0.25, 'y': 0.5, 'level': 2});
      field.putPlace(gid, 5, {'x': 1.0, 'y': 0.0, 'level': 0});
      final first = engine.issueJoin({'kind': 'controller'})['text']! as String;
      final j = decodeJoin(joinFromText(first), key);
      expect(j.boxPlaces, [
        BoxPlace(4, 2, quantizePlace(0.25), quantizePlace(0.5)),
        const BoxPlace(5, 0, 65535, 0),
      ]);
      expect(standby.joinAsStandby(first)['id'], gid);
      // Nothing placed on the standby and no HELLO: the boxes are in place.
      final by = {for (final b in boxes(ApiViewer.gm)) b['minor']: b};
      expect(by.keys, [4, 5]);
      final sby = {for (final b in sfield.boxBeacons()) b['minor']: b};
      expect(sby.keys, [4, 5]);
      expect(
        (sby[4]!['level'], sby[4]!['x'], sby[4]!['y']),
        (
          2,
          dequantizePlace(quantizePlace(0.25)),
          dequantizePlace(quantizePlace(0.5)),
        ),
      );
      expect((sby[5]!['level'], sby[5]!['x'], sby[5]!['y']), (0, 1.0, 0.0));
      expect(
        sfield.beaconsFor(ApiViewer.read),
        field.beaconsFor(ApiViewer.read),
      );
      // A box moved and one more placed after the standby joined.
      field.putPlace(gid, 5, {'x': 0.0, 'y': 1.0, 'level': 1});
      expect((sfield.boxBeacons().last['level']), 0);
      standby.joinAsStandby(engine.issueJoin({'kind': 'controller'})['text']);
      final moved = sfield.boxBeacons().last;
      expect((moved['level'], moved['x'], moved['y']), (1, 0.0, 1.0));
      // Promoted, a phone that hears the box is placed where the primary has it.
      final place = sfield.boxBeaconPlace('$boxBeaconMajor:5')!;
      expect((place['level'], place['x'], place['y']), (1, 0.0, 1.0));
      // The standby's levels govern what it shows: not in use, level 0.
      sfield.putLevels({'enabled': false, 'count': 3});
      expect(sfield.boxBeacons().first['level'], 0);
    });

    test('box places that do not fit are refused, not dropped (BBC-25)', () {
      final big = ControllerEngine()..joinKey = key;
      addTearDown(big.close);
      final bfield = ControllerField(big);
      final g =
          big.createGame({
                'name': 'big',
                'mode_id': 'org.atalaia.domination',
                'teams': ['red', 'blue'],
                'assignments': {for (var n = 4; n < 4 + 29; n++) '$n': 'zone'},
              })['id']!
              as int;
      for (var n = 4; n < 4 + 29; n++) {
        bfield.putPlace(g, n, {'x': 0.5, 'y': 0.5});
      }
      expect(
        () => big.issueJoin({'kind': 'controller'}),
        throwsA(
          isA<ControllerError>().having(
            (e) => e.message,
            'message',
            allOf(contains('box_places'), contains('28')),
          ),
        ),
      );
      // A box's own join never carries the places.
      expect(big.issueJoin({'role': 'zone'})['text'], isNotNull);
    });

    test('a join of another game is not a refresh', () {
      final other = ControllerEngine()..joinKey = key;
      addTearDown(other.close);
      other.createGame({
        'name': 'o',
        'mode_id': 'org.atalaia.domination',
        'teams': ['red', 'blue'],
      });
      final text = other.issueJoin({'kind': 'controller'})['text']! as String;
      final standby = ControllerEngine()..joinKey = key;
      addTearDown(standby.close);
      standby.joinAsStandby(engine.issueJoin({'kind': 'controller'})['text']);
      expect(
        () => standby.joinAsStandby(text),
        throwsA(isA<ControllerError>()),
      );
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
