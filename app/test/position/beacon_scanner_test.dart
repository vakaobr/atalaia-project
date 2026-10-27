// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Indoor positions from iBeacons (ADR-P3-6, decisions BLE-1 to BLE-9): the
// scanner reports only the strongest beacon of the field's registry, above a
// signal floor, one reading a window; the reporter sends it as a `ble`
// position and drops the GPS fixes while a beacon is heard (and goes back to
// them two windows after the last one); the plugin's channel contract; and
// the player screen: nothing asked on a field without beacons, the
// explanation before the permission, a refusal leaving GPS as it was, and
// the room the controller names. The radio is a fake (no hardware here).

import 'dart:async';

import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/platform/beacon_scan.dart';
import 'package:atalaia_app/platform/location.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/position/beacon_scanner.dart';
import 'package:atalaia_app/position/position_reporter.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';

const uuid = 'FDA50693-A4E2-4FB1-AFCF-C28847DC5D9F';
const other = '11111111-2222-3333-4444-555555555555';

const lobby = RegisteredBeacon(uuid: uuid, major: 1, minor: 1);
const hall = RegisteredBeacon(uuid: uuid, major: 1, minor: 2);

BeaconSighting heard(int major, int minor, int rssi, {String u = uuid}) =>
    BeaconSighting(uuid: u, major: major, minor: minor, rssi: rssi);

BeaconWindow window(int t, List<BeaconSighting> list) =>
    BeaconWindow(tMs: t, sightings: list);

class FakeScan implements BeaconScanService {
  FakeScan({this.isAvailable = true, this.isGranted = true, this.isOn = true});
  bool isAvailable, isGranted, isOn;
  final out = StreamController<BeaconWindow>.broadcast();
  final listens = <(List<String>, Duration)>[];
  var cancelled = 0;

  @override
  Future<bool> available() async => isAvailable;
  @override
  Future<bool> granted() async => isGranted;
  @override
  Future<bool> bluetoothOn() async => isOn;
  @override
  Stream<BeaconWindow> windows(List<String> uuids, Duration window) {
    listens.add((uuids, window));
    return out.stream;
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

LocationFix fix(int t) =>
    LocationFix(lat: 38.72, lon: -9.14, accuracyM: 5, tMs: t);

Future<void> settle() => Future<void>.delayed(Duration.zero);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  group('the scanner: only a registered beacon, the strongest', () {
    test('the strongest of the window, by its signal', () {
      final s = BeaconScanner(service: FakeScan(), registry: [lobby, hall]);
      final r = s.strongest(
        window(1000, [heard(1, 1, -80), heard(1, 2, -62), heard(1, 1, -90)]),
      );
      expect(r!.beaconId, '1:2');
      expect(r.rssi, -62);
      expect(r.tMs, 1000);
      expect(r.toReport(), {'source': 'ble', 'beacon_id': '1:2', 't': 1000});
    });

    test('an unregistered beacon is never reported', () {
      final s = BeaconScanner(service: FakeScan(), registry: [lobby]);
      // Another UUID with a registered major and minor, and an id the
      // registry lacks, however strong.
      expect(
        s.strongest(window(1, [heard(1, 1, -40, u: other), heard(9, 9, -30)])),
        isNull,
      );
      expect(
        s.strongest(window(1, [heard(9, 9, -30), heard(1, 1, -88)]))!.beaconId,
        '1:1',
      );
      expect(s.strongest(window(1, const [])), isNull);
    });

    test('too weak is not the room: below -95 dBm is dropped', () {
      final s = BeaconScanner(service: FakeScan(), registry: [lobby, hall]);
      expect(s.strongest(window(1, [heard(1, 1, -96)])), isNull);
      expect(s.strongest(window(1, [heard(1, 1, -95)]))!.beaconId, '1:1');
    });

    test('a tie: more advertisements, then the lower id', () {
      final s = BeaconScanner(service: FakeScan(), registry: [lobby, hall]);
      const a = BeaconSighting(
        uuid: uuid,
        major: 1,
        minor: 1,
        rssi: -70,
        count: 2,
      );
      const b = BeaconSighting(
        uuid: uuid,
        major: 1,
        minor: 2,
        rssi: -70,
        count: 5,
      );
      expect(s.strongest(window(1, [a, b]))!.beaconId, '1:2');
      expect(
        s.strongest(window(1, [heard(1, 2, -70), heard(1, 1, -70)]))!.beaconId,
        '1:1',
      );
    });

    test('the registry as the controller lists it, the UUID in any case', () {
      expect(
        RegisteredBeacon.fromApi({
          'id': '12:34',
          'uuid': uuid.toLowerCase(),
        })!.uuid,
        uuid,
      );
      for (final bad in <Object?>[
        null,
        'x',
        {'id': '1', 'uuid': uuid},
        {'id': '1:70000', 'uuid': uuid},
        {'id': 'a:b', 'uuid': uuid},
        {'id': '1:2'},
      ]) {
        expect(RegisteredBeacon.fromApi(bad), isNull, reason: '$bad');
      }
    });

    test(
      'listens for the registry\'s UUIDs, one window a reading; stop forgets',
      () async {
        final scan = FakeScan();
        final s = BeaconScanner(
          service: scan,
          registry: [lobby, hall],
          window: const Duration(seconds: 9),
        );
        final got = <BeaconReading>[];
        s.readings.listen(got.add);
        s.start();
        expect(scan.listens.single.$1, [uuid]);
        expect(scan.listens.single.$2, const Duration(seconds: 9));
        scan.out.add(window(1000, [heard(1, 1, -70)]));
        scan.out.add(window(2000, const []));
        scan.out.add(window(3000, [heard(1, 2, -60)]));
        await settle();
        expect(got.map((r) => r.beaconId), ['1:1', '1:2']);
        expect(s.latest!.beaconId, '1:2');
        s.stop();
        expect(s.latest, isNull);
        expect(s.running, isFalse);
        // A new interval from the controller restarts the scan with it, kept in
        // the ADR's 3 to 30 s.
        s.start();
        s.setWindow(const Duration(seconds: 1));
        expect(scan.listens.last.$2, const Duration(seconds: 3));
        s.setWindow(const Duration(minutes: 5));
        expect(scan.listens.last.$2, const Duration(seconds: 30));
        s.dispose();
      },
    );

    test('an empty registry listens for nothing', () {
      final scan = FakeScan();
      BeaconScanner(service: scan, registry: const []).start();
      expect(scan.listens, isEmpty);
    });
  });

  group('the reporter: a beacon indoors, GPS outdoors', () {
    late FakeScan scan;
    late FakeLocation loc;
    late BeaconScanner scanner;
    late PositionReporter reporter;
    late DateTime clock;
    final sent = <List<Map<String, Object?>>>[];
    Map<String, Object?> answer = {'stored': 1, 'interval_s': 10};

    setUp(() {
      scan = FakeScan();
      loc = FakeLocation();
      clock = DateTime(2026, 10, 27, 10);
      sent.clear();
      answer = {'stored': 1, 'interval_s': 10, 'ble_interval_s': 5};
      scanner = BeaconScanner(service: scan, registry: [lobby, hall]);
      reporter = PositionReporter(
        location: loc,
        send: (reports) async {
          sent.add(reports);
          return answer;
        },
        beacons: scanner,
        now: () => clock,
      )..start();
      addTearDown(reporter.dispose);
    });

    test('a beacon is sent as a ble report, once, and the GPS fixes with it '
        'are not', () async {
      loc.fixesOut.add(fix(1000)); // outdoors still
      scan.out.add(window(2000, [heard(1, 1, -70)]));
      await settle();
      expect(reporter.indoors, isTrue);
      expect(reporter.beaconId, '1:1');
      loc.fixesOut.add(fix(3000)); // indoors: GPS is not the position
      await settle();
      await reporter.flush();
      expect(sent, hasLength(1));
      expect([for (final r in sent[0]) r['source']], ['gps', 'ble']);
      expect(sent[0][1], {'source': 'ble', 'beacon_id': '1:1', 't': 2000});
      // Nothing new: nothing is sent twice.
      await reporter.flush();
      expect(sent, hasLength(1));
      // The next window: the same beacon again, a new report.
      scan.out.add(window(7000, [heard(1, 1, -72)]));
      await settle();
      await reporter.flush();
      expect(sent, hasLength(2));
      expect(sent[1].single['t'], 7000);
    });

    test('two windows without a beacon and the GPS fixes go on', () async {
      scan.out.add(window(1000, [heard(1, 2, -60)]));
      await settle();
      await reporter.flush(); // the beacon's own report goes first
      expect(reporter.indoors, isTrue);
      clock = clock.add(const Duration(seconds: 9)); // under two windows
      expect(reporter.indoors, isTrue);
      clock = clock.add(const Duration(seconds: 2)); // over
      expect(reporter.indoors, isFalse);
      expect(reporter.beaconId, isNull);
      loc.fixesOut.add(fix(20000));
      await settle();
      await reporter.flush();
      expect(sent.last.single['source'], 'gps');
    });

    test('the controller\'s beacon interval retimes the scan; it flushes on '
        'the shorter of the two', () async {
      expect(scanner.window, const Duration(seconds: 5));
      scan.out.add(window(1000, [heard(1, 1, -70)]));
      await settle();
      answer = {'stored': 1, 'interval_s': 20, 'ble_interval_s': 12};
      await reporter.flush();
      expect(reporter.interval, const Duration(seconds: 20));
      expect(scanner.window, const Duration(seconds: 12));
      expect(scan.listens.last.$2, const Duration(seconds: 12));
      // An interval out of the ADR's range is ignored.
      answer = {'stored': 1, 'interval_s': 20, 'ble_interval_s': 2};
      scan.out.add(window(2000, [heard(1, 1, -70)]));
      await settle();
      await reporter.flush();
      expect(scanner.window, const Duration(seconds: 12));
    });

    test(
      'at most five reports a request: the beacon is the last of them',
      () async {
        for (var i = 0; i < 5; i++) {
          loc.fixesOut.add(fix(100 + i));
        }
        await settle();
        scan.out.add(window(900, [heard(1, 1, -70)]));
        await settle();
        await reporter.flush();
        expect(sent.single, hasLength(5));
        expect(sent.single.last['source'], 'ble');
      },
    );

    test(
      'a 409 stops the reporter and the scan; stop forgets the beacon',
      () async {
        scan.out.add(window(1000, [heard(1, 1, -70)]));
        await settle();
        final failing = PositionReporter(
          location: loc,
          send: (_) async => throw CheckinException(409, 'not running'),
          beacons: BeaconScanner(service: scan, registry: [lobby]),
        )..start();
        scan.out.add(window(2000, [heard(1, 1, -70)]));
        await settle();
        await failing.flush();
        expect(failing.running, isFalse);
        expect(failing.beacons!.running, isFalse);
        expect(failing.stopReason, 'not running');
        reporter.stop();
        expect(scanner.latest, isNull);
        expect(reporter.indoors, isFalse);
      },
    );

    test('a failed send keeps the beacon for the next try', () async {
      scan.out.add(window(1000, [heard(1, 1, -70)]));
      await settle();
      var fail = true;
      final r = PositionReporter(
        location: loc,
        send: (reports) async {
          if (fail) throw CheckinException(0, 'out of reach');
          sent.add(reports);
          return answer;
        },
        beacons: BeaconScanner(service: scan, registry: [lobby]),
      )..start();
      addTearDown(r.dispose);
      scan.out.add(window(2000, [heard(1, 1, -70)]));
      await settle();
      await r.flush();
      expect(sent, isEmpty);
      fail = false;
      await r.flush();
      expect(sent.single.single['beacon_id'], '1:1');
    });
  });

  group('the player\'s floor with a beacon (decisions PM-1, PM-2)', () {
    test('a beacon report never carries the chosen level; GPS does', () async {
      final scan = FakeScan();
      final loc = FakeLocation();
      final sent = <List<Map<String, Object?>>>[];
      final r = PositionReporter(
        location: loc,
        send: (reports) async {
          sent.add(reports);
          return {'stored': 1, 'interval_s': 10};
        },
        beacons: BeaconScanner(service: scan, registry: [lobby]),
      )..start();
      addTearDown(r.dispose);
      r.setLevel(2);
      scan.out.add(window(2000, [heard(1, 1, -70)]));
      await settle();
      expect(r.indoors, isTrue);
      r.setLevel(1); // indoors: nothing is sent for it (the beacon is)
      await settle();
      expect(sent, isEmpty);
      await r.flush();
      expect(sent.single.single, {
        'source': 'ble',
        'beacon_id': '1:1',
        't': 2000,
      });
      loc.fixesOut.add(fix(3000)); // indoors: not sent
      await settle();
      await r.flush();
      expect(sent, hasLength(1));
    });
  });

  group('the plugin\'s channels (org.atalaia.app/beacons)', () {
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

    test(
      'without the plugin: not available, not granted, Bluetooth off',
      () async {
        final s = ChannelBeaconScanService();
        expect(await s.available(), isFalse);
        expect(await s.granted(), isFalse);
        expect(await s.bluetoothOn(), isFalse);
      },
    );

    test('booleans, and a window as the Kotlin side sends it', () async {
      messenger.setMockMethodCallHandler(
        const MethodChannel('org.atalaia.app/beacons'),
        (call) async => switch (call.method) {
          'available' => true,
          'granted' => false,
          'enabled' => true,
          _ => throw MissingPluginException(),
        },
      );
      Object? listenedWith;
      const events = EventChannel('org.atalaia.app/beacons/sightings');
      messenger.setMockStreamHandler(
        events,
        MockStreamHandler.inline(
          onListen: (arguments, sink) {
            listenedWith = arguments;
            sink.success({
              't': 1790000000000,
              'beacons': [
                {
                  'uuid': uuid.toLowerCase(),
                  'major': 1,
                  'minor': 2,
                  'rssi': -71,
                  'count': 4,
                },
                {
                  'uuid': uuid,
                  'major': 70000,
                  'minor': 1,
                  'rssi': -50,
                  'count': 1,
                },
                'junk',
              ],
            });
            sink.success({'t': 1790000005000, 'beacons': <Object?>[]});
            sink.success('junk');
          },
        ),
      );
      addTearDown(() {
        messenger.setMockMethodCallHandler(
          const MethodChannel('org.atalaia.app/beacons'),
          null,
        );
        messenger.setMockStreamHandler(events, null);
      });
      final s = ChannelBeaconScanService();
      expect(await s.available(), isTrue);
      expect(await s.granted(), isFalse);
      expect(await s.bluetoothOn(), isTrue);
      final got = await s
          .windows([uuid], const Duration(seconds: 5))
          .take(2)
          .toList();
      expect(listenedWith, {
        'uuids': [uuid],
        'window_ms': 5000,
      });
      expect(got[0].tMs, 1790000000000);
      expect(got[0].sightings, hasLength(1)); // the others are not beacons
      expect(got[0].sightings.single.uuid, uuid);
      expect(got[0].sightings.single.count, 4);
      expect(got[1].sightings, isEmpty);
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

    FieldFeed feed(PinnedField f) {
      final feed = FieldFeed(
        FieldLink(Uri.parse('https://10.0.0.1:8443'), 'tok', field: f),
      );
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
      return feed;
    }

    Future<(Harness, _Http, FakeLocation, FakeScan, FieldFeed)> open(
      WidgetTester tester, {
      List<Map<String, Object?>>? registry,
      Map<String, Object?>? levels,
      FakeScan? scan,
      Set<String> granted = const {'ACCESS_FINE_LOCATION', 'BLUETOOTH_SCAN'},
    }) async {
      tester.view.physicalSize = const Size(400, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final f = field();
      final fd = feed(f);
      addTearDown(fd.dispose);
      final http = _Http(registry, levels: levels);
      final loc = FakeLocation();
      final sc = scan ?? FakeScan();
      final h = harness(
        language: AppLanguage.en,
        settings: AppSettings(),
        fieldHttp: (_) => http,
        location: loc,
        beacons: sc,
      );
      h.device.granted.addAll(granted);
      await tester.pumpWidget(
        h.app(
          home: PlayerScreen(link: fd.link, feed: fd),
        ),
      );
      await tester.pump();
      return (h, http, loc, sc, fd);
    }

    Future<void> pumpAfter(WidgetTester tester) async {
      for (var i = 0; i < 6; i++) {
        await tester.pump(const Duration(milliseconds: 10));
      }
    }

    testWidgets('a field without beacons: nothing asked, GPS only', (
      tester,
    ) async {
      final (h, _, _, scan, _) = await open(tester, registry: const []);
      await tester.tap(find.byKey(const Key('player-share-position')));
      await pumpAfter(tester);
      expect(find.byKey(const Key('player-beacons-why')), findsNothing);
      expect(find.byKey(const Key('player-beacons-note')), findsNothing);
      expect(scan.listens, isEmpty);
      expect(h.device.calls.where((c) => c.contains('BLUETOOTH')), isEmpty);
    });

    testWidgets('an older controller (no registry): GPS only', (tester) async {
      final (_, _, _, scan, _) = await open(tester); // GET /beacons: 404
      await tester.tap(find.byKey(const Key('player-share-position')));
      await pumpAfter(tester);
      expect(find.byKey(const Key('player-beacons-why')), findsNothing);
      expect(scan.listens, isEmpty);
    });

    testWidgets('the explanation first, then the permission, then the scan '
        'and the room', (tester) async {
      final (h, http, loc, scan, fd) = await open(
        tester,
        registry: [
          {'id': '1:1', 'uuid': uuid},
          {'id': '1:2', 'uuid': uuid},
        ],
      );
      await tester.tap(find.byKey(const Key('player-share-position')));
      await pumpAfter(tester);
      expect(find.byKey(const Key('player-beacons-why')), findsOneWidget);
      expect(find.text('Indoor positions'), findsOneWidget);
      expect(scan.listens, isEmpty); // not before the player agrees
      await tester.tap(find.byKey(const Key('player-beacons-allow')));
      await pumpAfter(tester);
      expect(scan.listens.single.$1, [uuid]);
      expect(scan.listens.single.$2, const Duration(seconds: 7));
      expect(find.byKey(const Key('player-beacons-note')), findsOneWidget);
      // Indoors: the beacon is reported, the GPS fix is not; the controller
      // names the room and the screen shows it.
      scan.out.add(window(5000, [heard(1, 2, -65)]));
      await pumpAfter(tester);
      loc.fixesOut.add(fix(6000));
      await pumpAfter(tester);
      await tester.pump(const Duration(seconds: 8));
      await pumpAfter(tester);
      final posts = http.posted.expand((b) => b).toList();
      expect(
        posts.any((r) => r['source'] == 'ble' && r['beacon_id'] == '1:2'),
        isTrue,
      );
      expect(posts.where((r) => r['source'] == 'gps'), isEmpty);
      fd.onMessage({
        'type': 'player_position',
        'game': 1,
        'position': {
          'player_id': 'p1',
          'source': 'ble',
          'beacon_id': '1:2',
          'room': 'Lobby',
          'zone': 'Ground',
          't': 5000,
        },
      });
      await pumpAfter(tester);
      expect(find.text('Your position: Lobby (Ground)'), findsOneWidget);
      // Sharing off: the scan stops and the notes go.
      await tester.tap(find.byKey(const Key('player-share-position')));
      await pumpAfter(tester);
      expect(find.byKey(const Key('player-beacons-note')), findsNothing);
      expect(scan.out.hasListener, isFalse);
      expect(h.foreground.calls.last, startsWith('stop'));
    });

    testWidgets('a room beacon gives the floor: the picker gives way to it', (
      tester,
    ) async {
      final (_, http, loc, scan, _) = await open(
        tester,
        registry: [
          {'id': '1:2', 'uuid': uuid},
        ],
        levels: {
          'levels': [
            {'level': 0, 'name': 'Ground', 'image': null},
            {'level': 1, 'name': 'First', 'image': null},
          ],
        },
      );
      await tester.tap(find.byKey(const Key('player-share-position')));
      await pumpAfter(tester);
      await tester.tap(find.byKey(const Key('player-beacons-allow')));
      await pumpAfter(tester);
      expect(find.byKey(const Key('player-level-picker')), findsOneWidget);
      await tester.tap(find.byKey(const Key('player-level-1')));
      await pumpAfter(tester);
      loc.fixesOut.add(fix(4000));
      await pumpAfter(tester);
      await tester.pump(const Duration(seconds: 8));
      await pumpAfter(tester);
      expect(http.posted.expand((b) => b).any((r) => r['level'] == 1), isTrue);
      // A beacon is heard: its floor is the position, the choice waits.
      scan.out.add(window(5000, [heard(1, 2, -65)]));
      await pumpAfter(tester);
      expect(find.byKey(const Key('player-level-picker')), findsNothing);
      expect(find.byKey(const Key('player-level-beacon')), findsOneWidget);
      final beaconReports = http.posted
          .expand((b) => b)
          .where((r) => r['source'] == 'ble');
      expect(beaconReports.every((r) => !r.containsKey('level')), isTrue);
    });

    testWidgets('"Not now" leaves GPS as it was, and says so', (tester) async {
      final (_, _, _, scan, _) = await open(
        tester,
        registry: [
          {'id': '1:1', 'uuid': uuid},
        ],
      );
      await tester.tap(find.byKey(const Key('player-share-position')));
      await pumpAfter(tester);
      await tester.tap(find.byKey(const Key('player-beacons-skip')));
      await pumpAfter(tester);
      expect(scan.listens, isEmpty);
      expect(find.byKey(const Key('player-share-position')), findsOneWidget);
      expect(
        find.text(
          'Indoor positions are off. Your GPS position is still shared.',
        ),
        findsOneWidget,
      );
    });

    testWidgets('no Bluetooth permission: said, and GPS goes on', (
      tester,
    ) async {
      final (_, _, _, scan, _) = await open(
        tester,
        registry: [
          {'id': '1:1', 'uuid': uuid},
        ],
        granted: const {'ACCESS_FINE_LOCATION'},
      );
      await tester.tap(find.byKey(const Key('player-share-position')));
      await pumpAfter(tester);
      await tester.tap(find.byKey(const Key('player-beacons-allow')));
      await pumpAfter(tester);
      expect(scan.listens, isEmpty);
      expect(
        find.textContaining('no permission for Bluetooth'),
        findsOneWidget,
      );
    });

    testWidgets('Bluetooth switched off, or no Bluetooth LE: said', (
      tester,
    ) async {
      final (_, _, _, scan, _) = await open(
        tester,
        registry: [
          {'id': '1:1', 'uuid': uuid},
        ],
        scan: FakeScan(isOn: false),
      );
      await tester.tap(find.byKey(const Key('player-share-position')));
      await pumpAfter(tester);
      await tester.tap(find.byKey(const Key('player-beacons-allow')));
      await pumpAfter(tester);
      expect(scan.listens, isEmpty);
      expect(find.textContaining('Bluetooth is switched off'), findsOneWidget);
    });

    testWidgets('a phone without Bluetooth LE is not asked anything', (
      tester,
    ) async {
      final (h, _, _, scan, _) = await open(
        tester,
        registry: [
          {'id': '1:1', 'uuid': uuid},
        ],
        scan: FakeScan(isAvailable: false),
      );
      await tester.tap(find.byKey(const Key('player-share-position')));
      await pumpAfter(tester);
      expect(find.byKey(const Key('player-beacons-why')), findsNothing);
      expect(scan.listens, isEmpty);
      expect(h.device.calls.where((c) => c.contains('BLUETOOTH')), isEmpty);
      expect(find.textContaining('cannot listen'), findsOneWidget);
    });
  });
}

/// The field controller as the player screen's requests see it: the beacon
/// registry (null: an older controller, a 404) and the positions posted.
class _Http implements FieldHttp {
  _Http(this.registry, {this.levels});
  final List<Map<String, Object?>>? registry;

  /// The field's levels (GET /field/levels), or null: a 404.
  final Map<String, Object?>? levels;
  final posted = <List<Map<String, Object?>>>[];

  @override
  Future<FieldResponse> send(
    String method,
    String path, {
    Object? body,
    String? token,
  }) async {
    if (method == 'GET' && path == '/beacons' && registry != null) {
      return FieldResponse(200, {'beacons': registry, 'ble_interval_s': 7});
    }
    if (method == 'GET' && path == '/field/levels' && levels != null) {
      return FieldResponse(200, levels);
    }
    if (method == 'POST' && path == '/positions') {
      posted.add([
        for (final r in (body! as Map)['reports'] as List)
          (r as Map).cast<String, Object?>(),
      ]);
      return const FieldResponse(200, {
        'stored': 1,
        'interval_s': 10,
        'ble_interval_s': 7,
      });
    }
    return const FieldResponse(404, null);
  }
}
