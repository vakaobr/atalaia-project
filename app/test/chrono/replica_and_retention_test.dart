// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import 'package:atalaia_app/chrono/reading.dart';
import 'package:atalaia_app/chrono/replica.dart';
import 'package:atalaia_app/chrono/retention.dart';
import 'package:flutter_test/flutter_test.dart';

Matcher get badFormat => throwsA(isA<ChronoFormatException>());

const replicaJson = {
  'replica_id': '8a1f0c2e-7b3d-4c5e-8f9a-0b1c2d3e4f50',
  'owner_player_id': 'p-abc123',
  'type': 'bolt_action',
  'class': 'sniper',
  'make_model': 'Bolt rifle, black',
  'registered_at': '2026-10-18T09:00:00Z',
  'tag_type': 'nfc',
  'tag_uid': '04:A2:B3:C4:D5:E6:F7',
};

ChronoReading reading(String player, DateTime at) => ChronoReading.measure(
  replicaId: '8a1f0c2e-7b3d-4c5e-8f9a-0b1c2d3e4f50',
  playerId: player,
  type: ReadingType.checkin,
  velocityMps: 100,
  bbWeightG: 0.2,
  chronoId: 'c-1',
  marshalId: 'm-1',
  marshalName: 'Ana',
  fieldId: 'f-1',
  timestamp: at,
);

void main() {
  group('replica', () {
    test('JSON round trip (ADR-P3-7 fields)', () {
      final r = Replica.fromJson(replicaJson);
      expect(r.type, ReplicaType.boltAction);
      expect(r.replicaClass, 'sniper');
      expect(r.tagType, TagType.nfc);
      expect(r.toJson(), replicaJson);
    });

    test('make and model are optional', () {
      final json = {...replicaJson}..remove('make_model');
      expect(Replica.fromJson(json).makeModel, isNull);
      expect(
        Replica.fromJson(json).toJson().containsKey('make_model'),
        isFalse,
      );
    });

    test('NFC UIDs and QR labels', () {
      expect(
        Replica.nfcUid([4, 0xa2, 0xb3, 0xc4, 0xd5, 0xe6, 0xf7]),
        '04:A2:B3:C4:D5:E6:F7',
      );
      expect(
        Replica.fromJson({...replicaJson, 'tag_uid': '04:A2:B3:C4'}).tagUid,
        '04:A2:B3:C4',
      );
      expect(
        () => Replica.fromJson({...replicaJson, 'tag_uid': '04:a2:b3:c4'}),
        badFormat,
      );
      expect(
        () => Replica.fromJson({...replicaJson, 'tag_uid': '04:A2:B3:C4:D5'}),
        badFormat,
      );
      final qr = Replica.fromJson({
        ...replicaJson,
        'tag_type': 'qr',
        'tag_uid': 'ATL-000123',
      });
      expect(qr.tagType, TagType.qr);
      expect(
        () => Replica.fromJson({
          ...replicaJson,
          'tag_type': 'qr',
          'tag_uid': 'has space',
        }),
        badFormat,
      );
    });

    test('every type has a wire name', () {
      for (final t in ReplicaType.values) {
        expect(ReplicaTypeWire.parse(t.wire), t);
      }
    });

    test('bad fields are refused', () {
      expect(
        () => Replica.fromJson({...replicaJson, 'type': 'laser'}),
        badFormat,
      );
      expect(
        () => Replica.fromJson({...replicaJson, 'class': 'Sniper'}),
        badFormat,
      );
      expect(
        () => Replica.fromJson({...replicaJson, 'colour': 'tan'}),
        badFormat,
      );
      expect(
        () => Replica.fromJson({...replicaJson, 'tag_type': 'rfid'}),
        badFormat,
      );
      expect(
        () => Replica.fromJson({...replicaJson, 'registered_at': 'yesterday'}),
        badFormat,
      );
      expect(
        () => Replica.fromJson({...replicaJson}..remove('owner_player_id')),
        badFormat,
      );
    });
  });

  group('retention', () {
    final t0 = DateTime.utc(2026, 10, 18, 12);

    test('default 365 days, 1 day to 10 years', () {
      expect(RetentionPolicy().days, 365);
      expect(() => RetentionPolicy(days: 0), throwsArgumentError);
      expect(() => RetentionPolicy(days: 3654), throwsArgumentError);
      expect(RetentionPolicy(days: 1).days, 1);
    });

    test('readings past the period are dropped', () {
      final policy = RetentionPolicy(days: 30);
      final old = reading('p-1', t0);
      final recent = reading('p-1', t0.add(const Duration(days: 20)));
      final now = t0.add(const Duration(days: 30));
      expect(policy.isExpired(old, now), isTrue);
      expect(
        policy.isExpired(old, now.subtract(const Duration(seconds: 1))),
        isFalse,
      );
      expect(policy.keep([old, recent], now), [recent]);
    });

    test('a player can have every reading erased', () {
      final a = reading('p-1', t0);
      final b = reading('p-2', t0);
      expect(eraseForPlayer([a, b, a], 'p-1'), [b]);
    });
  });
}
