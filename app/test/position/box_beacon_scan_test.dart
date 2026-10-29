// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A Field Box that advertises as an iBeacon (decisions BBC-1 to BBC-12) needs
// nothing new in the phone: the box's UUID is one more entry in the UUID list
// the controller gives (BLE-9's hardware filter per registered UUID), its
// major:minor is a registered beacon's id like a tag's. This test takes the
// box's real advertisement bytes (the shared vectors, which the firmware's
// C checks too) through the two steps the Android plugin does with them
// (BeaconScanPlugin.kt, which has no unit test harness: the two helpers below
// are its filter and its parse, written out the same way) and then through
// the scanner and the reporter's rules: the box is heard through the filter,
// parsed to its UUID, major and minor, listened for by its UUID, and wins or
// loses against a tag by signal strength as any registered beacon does.

import 'dart:async';
import 'dart:typed_data';

import 'package:atalaia_app/platform/beacon_scan.dart';
import 'package:atalaia_app/position/beacon_scanner.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

const tagUuid = 'FDA50693-A4E2-4FB1-AFCF-C28847DC5D9F';
const appleId = 0x004c;

Uint8List hex(String s) => Uint8List.fromList([
  for (var i = 0; i < s.length; i += 2)
    int.parse(s.substring(i, i + 2), radix: 16),
]);

/// The manufacturer data of Apple's id in an advertisement (what
/// `ScanRecord.getManufacturerSpecificData(0x004C)` returns: the bytes after
/// the company id), or null. Walks the advertisement's length-type-value
/// structures.
Uint8List? appleData(Uint8List adv) {
  var i = 0;
  while (i < adv.length) {
    final len = adv[i];
    if (len == 0) break;
    if (adv[i + 1] == 0xff && len >= 3) {
      final company = adv[i + 2] | (adv[i + 3] << 8);
      if (company == appleId) return adv.sublist(i + 4, i + 1 + len);
    }
    i += 1 + len;
  }
  return null;
}

/// The hardware scan filter BeaconScanPlugin.kt builds for a UUID: the
/// iBeacon prefix (type 0x02, length 0x15) and the UUID, all 18 bytes masked.
Uint8List filterData(String uuid) {
  final h = uuid.replaceAll('-', '');
  return Uint8List.fromList([0x02, 0x15, ...hex(h)]);
}

/// What the plugin's `record()` makes of one advertisement, or null (dropped).
BeaconSighting? record(Uint8List adv, int rssi) {
  final d = appleData(adv);
  if (d == null || d.length < 23 || d[0] != 0x02 || d[1] != 0x15) return null;
  String uuid() {
    final h = [
      for (final b in d.sublist(2, 18)) b.toRadixString(16).padLeft(2, '0'),
    ].join().toUpperCase();
    return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-'
        '${h.substring(16, 20)}-${h.substring(20)}';
  }

  return BeaconSighting(
    uuid: uuid(),
    major: (d[18] << 8) | d[19],
    minor: (d[20] << 8) | d[21],
    rssi: rssi,
  );
}

class FakeScan implements BeaconScanService {
  final out = StreamController<BeaconWindow>.broadcast();
  final listens = <(List<String>, Duration)>[];
  @override
  Future<bool> available() async => true;
  @override
  Future<bool> granted() async => true;
  @override
  Future<bool> bluetoothOn() async => true;
  @override
  Stream<BeaconWindow> windows(List<String> uuids, Duration window) {
    listens.add((uuids, window));
    return out.stream;
  }
}

void main() {
  final v = loadVectors('box_beacon.json');
  final first = cases(v, 'adv').first; // node 1 of the first join key
  final boxUuid = cases(v, 'uuids').first['uuid_text'] as String;
  final adv = hex(first['adv'] as String);

  test(
    'the box\'s advertisement is an iBeacon of its UUID, major and minor',
    () {
      expect(adv.length, 30);
      final s = record(adv, -60)!;
      expect(s.uuid, boxUuid);
      expect(s.major, v['major']);
      expect(s.minor, first['node_id']);
      expect(s.id, first['id']);
    },
  );

  test('the plugin\'s hardware filter for the box\'s UUID lets it through', () {
    final data = appleData(adv)!;
    final filter = filterData(boxUuid);
    expect(filter.length, 18);
    expect(data.sublist(0, 18), filter); // the filter's mask is all 0xFF
    // ... and not the filter of another UUID.
    expect(data.sublist(0, 18), isNot(filterData(tagUuid)));
  });

  test(
    'an advertisement that is no iBeacon is dropped, as the plugin does',
    () {
      final other = Uint8List.fromList([...adv]);
      other[7] = 0x03; // not type 0x02
      expect(record(other, -60), isNull);
      final short = Uint8List.fromList([2, 1, 6, 5, 0xff, 0x4c, 0, 2, 0x15]);
      expect(record(short, -60), isNull);
    },
  );

  group('through the scanner', () {
    // The registry as the controller serves it to a player: the box with the
    // field's UUID, a tag with its own.
    final registry = [
      RegisteredBeacon.fromApi({'id': first['id'], 'uuid': boxUuid})!,
      RegisteredBeacon.fromApi({'id': '1:1', 'uuid': tagUuid})!,
    ];

    test('the box\'s UUID is one more UUID to listen for', () {
      final scan = FakeScan();
      final scanner = BeaconScanner(service: scan, registry: registry)..start();
      expect(scan.listens.single.$1.toSet(), {boxUuid, tagUuid});
      scanner.dispose();
    });

    test('a box is reported as a registered beacon, the strongest wins', () {
      final scanner = BeaconScanner(service: FakeScan(), registry: registry);
      final box = record(adv, -70)!;
      final tag = BeaconSighting(uuid: tagUuid, major: 1, minor: 1, rssi: -80);
      var r = scanner.strongest(BeaconWindow(tMs: 5, sightings: [box, tag]))!;
      expect(r.beaconId, first['id']); // -70 beats -80
      expect(r.toReport(), {'source': 'ble', 'beacon_id': first['id'], 't': 5});
      final nearTag = BeaconSighting(
        uuid: tagUuid,
        major: 1,
        minor: 1,
        rssi: -55,
      );
      r = scanner.strongest(BeaconWindow(tMs: 6, sightings: [box, nearTag]))!;
      expect(r.beaconId, '1:1'); // the tag in the room is nearer
    });

    test(
      'a box the controller does not list (disabled, not placed) is dropped',
      () {
        final scanner = BeaconScanner(
          service: FakeScan(),
          registry: [registry[1]], // the controller left the box out
        );
        final box = record(adv, -50)!;
        expect(
          scanner.strongest(BeaconWindow(tMs: 1, sightings: [box])),
          isNull,
        );
      },
    );

    test(
      'a box of another field (another UUID, same major and minor) is dropped',
      () {
        final scanner = BeaconScanner(service: FakeScan(), registry: registry);
        final foreign = BeaconSighting(
          uuid: cases(v, 'uuids')[1]['uuid_text'] as String,
          major: v['major'] as int,
          minor: first['node_id'] as int,
          rssi: -40,
        );
        expect(
          scanner.strongest(BeaconWindow(tMs: 1, sightings: [foreign])),
          isNull,
        );
      },
    );
  });
}
