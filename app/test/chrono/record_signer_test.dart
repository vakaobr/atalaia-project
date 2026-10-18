// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Ed25519-signed chrono readings against protocol/vectors/chrono_record.json,
// which the controller's Python verifier checks too. Every vector is checked;
// none is skipped. (PLAN.md named this hmac_signer_test.dart: decision P3-1
// changed chrono signing to Ed25519.)

import 'dart:convert';

import 'package:atalaia_app/chrono/reading.dart';
import 'package:atalaia_app/chrono/record_signer.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

Matcher fails(ChronoFailure reason) => throwsA(
  isA<ChronoVerifyException>().having((e) => e.reason, 'reason', reason),
);

void main() {
  final v = loadVectors('chrono_record.json');
  final seed = hexDecode(v['seed'] as String);
  final publicKey = hexDecode(v['public_key'] as String);
  late MarshalKey marshal;

  setUpAll(() async {
    marshal = await MarshalKey.fromSeed(seed);
  });

  test('vector counts', () {
    expect(cases(v, 'valid').length, greaterThanOrEqualTo(4));
    expect(cases(v, 'invalid').length, greaterThanOrEqualTo(20));
    expect(cases(v, 'rfc8032').length, 3);
  });

  test('the test seed gives the test public key', () {
    expect(hexEncode(marshal.publicKey), v['public_key']);
  });

  group('RFC 8032 known answers', () {
    for (final c in cases(v, 'rfc8032')) {
      test(c['name'] as String, () async {
        final key = await MarshalKey.fromSeed(hexDecode(c['seed'] as String));
        expect(hexEncode(key.publicKey), c['public_key']);
        final message = hexDecode(c['message'] as String);
        final sig = await ed25519Sign(key, message);
        expect(hexEncode(sig), c['signature']);
        expect(await ed25519Verify(key.publicKey, message, sig), isTrue);
      });
    }
  });

  group('valid records', () {
    for (final c in cases(v, 'valid')) {
      test(c['name'] as String, () async {
        final json = c['record'] as Map<String, dynamic>;
        final reading = ChronoReading.fromJson(json);
        expect(utf8.decode(reading.canonicalBytes()), c['canonical']);
        expect(hexEncode(reading.canonicalBytes()), c['canonical_hex']);
        expect(await verifyRecordJson(json, publicKey), isA<ChronoReading>());
        expect(
          await verifyRecordText(jsonEncode(json), publicKey),
          isA<ChronoReading>(),
        );
        // Ed25519 is deterministic: signing again gives the same signature.
        final resigned = await signReading(
          reading.withSignature(null),
          marshal,
        );
        expect(resigned.signature, json['signature']);
        expect(resigned.toJson(), json);
      });
    }
  });

  group('invalid records', () {
    for (final c in cases(v, 'invalid')) {
      test('${c['name']}: ${c['reason']}', () async {
        final reason = ChronoFailure.values.byName(c['reason'] as String);
        await expectLater(
          verifyRecordJson(c['record'], publicKey),
          fails(reason),
        );
      });
    }
  });

  group('signing', () {
    ChronoReading reading() => ChronoReading.measure(
      replicaId: newUuid(),
      playerId: 'p-17',
      type: ReadingType.checkin,
      velocityMps: 101.234,
      bbWeightG: 0.2,
      chronoId: 'chrono-1',
      marshalId: 'm-1',
      marshalName: 'Ana',
      fieldId: 'field-1',
      timestamp: DateTime.utc(2026, 10, 18, 9, 30, 15, 999),
    );

    test('sign then verify with a new key', () async {
      final key = await MarshalKey.generate();
      final signed = await signReading(reading(), key);
      expect(signed.signature, hasLength(88));
      expect(await verifyReading(signed, key.publicKey), signed);
      final other = await MarshalKey.generate();
      await expectLater(
        verifyReading(signed, other.publicKey),
        fails(ChronoFailure.signature),
      );
    });

    test('changing any field after signing breaks the signature', () async {
      final signed = (await signReading(reading(), marshal)).toJson();
      final changes = <Map<String, Object>>[
        {'player_id': 'p-18'},
        {'marshal_name': 'Rui'},
        {'timestamp': '2026-10-18T09:30:16Z'},
        {'chrono_id': 'chrono-2'},
        {'type': 'spotcheck'},
        {'game_id': 'g-2'},
        {'velocity_mps': 99.0, 'energy_j': recordEnergy(0.2, 99.0)},
      ];
      for (final change in changes) {
        await expectLater(
          verifyRecordJson({...signed, ...change}, marshal.publicKey),
          fails(ChronoFailure.signature),
          reason: '$change',
        );
      }
      expect(await verifyRecordJson(signed, marshal.publicKey), isNotNull);
    });

    test('the canonical form does not depend on the order of the fields', () {
      final r = reading();
      final shuffled = Map.fromEntries(r.toJson().entries.toList().reversed);
      expect(
        ChronoReading.fromJson(shuffled).canonicalBytes(),
        r.canonicalBytes(),
      );
      expect(r.canonicalBytes(), r.canonicalBytes());
    });

    test('an unsigned record is refused as unsigned', () async {
      await expectLater(
        verifyReading(reading(), marshal.publicKey),
        fails(ChronoFailure.unsigned),
      );
    });

    test('a seed is 32 bytes', () {
      expect(
        () => MarshalKey.fromSeed(List<int>.filled(31, 0)),
        throwsArgumentError,
      );
    });

    test('raw verify refuses wrong sizes', () async {
      expect(
        await ed25519Verify(
          List<int>.filled(31, 0),
          [],
          List<int>.filled(64, 0),
        ),
        isFalse,
      );
      expect(
        await ed25519Verify(marshal.publicKey, [], List<int>.filled(63, 0)),
        isFalse,
      );
    });

    test('not JSON is a format error', () async {
      await expectLater(
        verifyRecordText('{', marshal.publicKey),
        fails(ChronoFailure.format),
      );
    });
  });
}
