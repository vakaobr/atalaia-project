// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Join payloads (lib/protocol/join_payload.dart) against the shared vectors
// that core/src/join.c and simulator/atalaia_sim/join.py check
// (protocol/vectors/join.json), and the CBOR subset under them.

import 'dart:typed_data';

import 'package:atalaia_app/protocol/cbor.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:atalaia_app/security/ndef.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

JoinPayload _fields(Map<String, dynamic> f) => JoinPayload(
  gameId: f['game_id'] as int,
  gameKey: hexDecode(f['game_key'] as String),
  nodeId: f['node_id'] as int,
  controllerId: f['controller_id'] as int,
  channelHz: f['channel_hz'] as int,
  maxHops: f['max_hops'] as int,
  teams: (f['teams'] as List).cast<String>(),
  modeId: f['mode_id'] as String,
  role: f['role'] as String,
  gameSeed: f['game_seed'] as int,
  params: (f['params'] as Map?)?.cast<String, Object?>(),
  kind: JoinKind.values.byName(f['kind'] as String),
);

/// [text] with the last base64url character's lowest bit set: a padding bit
/// when the length is not a multiple of 4.
String _withPaddingBit(String text) {
  const alphabet =
      'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  final b64 = text.substring(joinTextPrefix.length);
  expect(b64.length % 4, isNot(0));
  final last = alphabet.indexOf(b64[b64.length - 1]);
  return text.substring(0, text.length - 1) + alphabet[last | 1];
}

/// [text] with base64url characters added until there are 4n+1 of them.
String _oneTooMany(String text) {
  var t = text;
  while ((t.length - joinTextPrefix.length) % 4 != 1) {
    t += 'A';
  }
  return t;
}

void main() {
  final v = loadVectors('join.json');
  final key = hexDecode(v['join_key'] as String);
  final wrong = hexDecode(v['wrong_key'] as String);

  group('valid payloads', () {
    for (final c in cases(v, 'valid')) {
      test('${c['name']}', () {
        final payload = hexDecode(c['payload'] as String);
        final f = c['fields'] as Map<String, dynamic>;
        final j = decodeJoin(payload, key);
        expect(j.gameId, f['game_id']);
        expect(hexEncode(j.gameKey), f['game_key']);
        expect(j.nodeId, f['node_id']);
        expect(j.controllerId, f['controller_id']);
        expect(j.channelHz, f['channel_hz']);
        expect(j.maxHops, f['max_hops']);
        expect(j.teams, f['teams']);
        expect(j.modeId, f['mode_id']);
        expect(j.role, f['role']);
        expect(j.gameSeed, f['game_seed']);
        expect(j.params, f['params']);
        expect(j.kind.name, f['kind']);
        // Re-encoded byte for byte, from the vector's own fields too.
        expect(hexEncode(encodeJoin(j, key)), c['payload']);
        expect(hexEncode(encodeJoin(_fields(f), key)), c['payload']);
        // The text form and the NFC card memory.
        expect(joinToText(payload), c['text']);
        expect(hexEncode(joinFromText('  ${c['text']}\n')), c['payload']);
        expect(hexEncode(type2Memory(payload, joinNdefType)), c['ndef_tag']);
        expect(
          hexEncode(
            payloadFromType2Memory(
              hexDecode(c['ndef_tag'] as String),
              joinNdefType,
            )!,
          ),
          c['payload'],
        );
        // Another field's join key: refused for its tag.
        expect(
          () => decodeJoin(payload, wrong),
          throwsA(
            isA<JoinException>().having(
              (e) => e.reason,
              'reason',
              JoinFailure.mac,
            ),
          ),
        );
      });
    }
  });

  test('an optional key 13-31 is skipped', () {
    final j = decodeJoin(hexDecode(v['optional_key_skipped'] as String), key);
    final first = cases(v, 'valid').first;
    expect(hexEncode(encodeJoin(j, key)), first['payload']);
  });

  group('invalid payloads', () {
    for (final c in cases(v, 'invalid')) {
      test('${c['name']}: ${c['reason']}', () {
        expect(
          () => decodeJoin(hexDecode(c['payload'] as String), key),
          throwsA(
            isA<JoinException>().having(
              (e) => e.reason.name,
              'reason',
              c['reason'],
            ),
          ),
        );
      });
    }
  });

  test('HMAC-SHA256 known answers (RFC 4231)', () {
    for (final c in cases(v, 'hmac_sha256')) {
      final mac = Hmac(
        sha256,
        hexDecode(c['key'] as String),
      ).convert(hexDecode(c['data'] as String));
      expect(hexEncode(mac.bytes), c['mac'], reason: c['name'] as String);
    }
  });

  test('join texts that are not canonical base64url are refused', () {
    final good = cases(v, 'valid').first['text'] as String;
    for (final bad in [
      'atalaia:join',
      'atalaia:joi:${good.substring(13)}',
      '$good=',
      '$good+',
      _oneTooMany(good), // 4n+1 characters
      _withPaddingBit(good), // non-zero padding bits
    ]) {
      expect(
        () => joinFromText(bad),
        throwsA(isA<JoinException>()),
        reason: bad,
      );
    }
    expect(isJoinText(' $good'), isTrue);
    expect(isJoinText('http://x'), isFalse);
  });

  group('CBOR', () {
    test('shortest forms', () {
      expect(hexEncode(cborEncode(0)), '00');
      expect(hexEncode(cborEncode(23)), '17');
      expect(hexEncode(cborEncode(24)), '1818');
      expect(hexEncode(cborEncode(256)), '190100');
      expect(hexEncode(cborEncode(65536)), '1a00010000');
      expect(hexEncode(cborEncode(4294967296)), '1b0000000100000000');
      expect(hexEncode(cborEncode(-1)), '20');
      expect(hexEncode(cborEncode(-300)), '39012b');
      expect(hexEncode(cborEncode(1.5)), 'f93e00');
      expect(hexEncode(cborEncode(0.0)), 'f90000');
      expect(hexEncode(cborEncode(-0.0)), 'f98000');
      expect(hexEncode(cborEncode(100000.0)), 'fa47c35000');
      expect(hexEncode(cborEncode(1.1)), 'fb3ff199999999999a');
      expect(hexEncode(cborEncode(5.960464477539063e-8)), 'f90001');
      expect(hexEncode(cborEncode('é')), '62c3a9');
      expect(hexEncode(cborEncode(Uint8List.fromList([1, 2]))), '420102');
      expect(hexEncode(cborEncode([true, false, null])), '83f5f4f6');
      expect(hexEncode(cborEncode({'a': 1, 2: 'b'})), 'a2616101026162');
    });

    test('round trips, refusals', () {
      for (final x in <Object?>[
        0, -1, 1 << 40, 1.5, -2.25, 1e300, 'text', //
        <Object?>[1, 'a', <Object?>[], <String, Object?>{}],
        {
          'x': {'y': null},
        },
      ]) {
        expect(cborDecode(cborEncode(x)), x);
      }
      expect(cborDecode(hexDecode('f93e00')), 1.5);
      for (final bad in [
        '', 'ff', '5f', '9f', 'c1', 'f7', 'f97c00', 'fb7ff8000000000000', //
        '0000', '62c3', 'a2000000', '420102', '1c',
      ]) {
        expect(
          () => cborDecode(hexDecode(bad)),
          throwsA(isA<CborException>()),
          reason: bad,
        );
      }
      expect(cborDecode(hexDecode('420102'), allowBytes: true), [1, 2]);
      final deep = '81' * 18;
      expect(
        () => cborDecode(hexDecode('${deep}00')),
        throwsA(isA<CborException>()),
      );
      expect(cborDecode(hexDecode('${'81' * 17}00')), isList);
    });
  });
}
