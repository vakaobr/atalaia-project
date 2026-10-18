// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Player tags against protocol/vectors/tag.json, the vectors the C core and
// the Python simulator check too. Every vector is checked; none is skipped.

import 'package:atalaia_app/security/bytes.dart';
import 'package:atalaia_app/security/nfc_tag_signer.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

void main() {
  final v = loadVectors('tag.json');
  final key = hexDecode(v['game_key'] as String);
  final gameId = v['game_id'] as int;
  final teams = (v['teams'] as List<dynamic>).cast<String>();
  final uid = hexDecode(v['uid'] as String);

  PlayerTag fields(Map<String, dynamic> f) => PlayerTag(
    player: f['player'] as String,
    team: f['team'] as int,
    gameId: f['game_id'] as int,
  );

  test('vector counts', () {
    expect(cases(v, 'valid').length, greaterThanOrEqualTo(3));
    expect(cases(v, 'invalid').length, greaterThanOrEqualTo(9));
    expect(cases(v, 'events').length, greaterThanOrEqualTo(5));
  });

  group('valid tags', () {
    for (final c in cases(v, 'valid')) {
      test(c['name'] as String, () {
        final payload = hexDecode(c['payload'] as String);
        final tag = fields(c['fields'] as Map<String, dynamic>);
        expect(
          decodeTag(payload, gameId: gameId, gameKey: key, teamCount: 2),
          tag,
        );
        expect(hexEncode(encodeTag(tag, key)), c['payload']);
        final ndef = hexDecode(c['ndef_tag'] as String);
        expect(hexEncode(tagToNdefMemory(payload)), c['ndef_tag']);
        expect(hexEncode(tagFromNdefMemory(ndef)!), c['payload']);
      });
    }
  });

  group('invalid tags', () {
    for (final c in cases(v, 'invalid')) {
      test('${c['name']}: ${c['reason']}', () {
        expect(
          () => decodeTag(
            hexDecode(c['payload'] as String),
            gameId: gameId,
            gameKey: key,
            teamCount: teams.length,
          ),
          throwsA(
            isA<TagException>().having(
              (e) => e.reason.name,
              'reason',
              c['reason'],
            ),
          ),
        );
      });
    }
  });

  group('nfc.tag event data', () {
    for (final c in cases(v, 'events')) {
      test(c['name'] as String, () {
        final payload = c['payload'] as String?;
        expect(
          tagEventJson(
            uid: uid,
            payload: payload == null ? null : hexDecode(payload),
            gameId: gameId,
            gameKey: c['game_key'] == true ? key : null,
            teams: teams,
          ),
          c['json'],
        );
      });
    }
  });

  test('the MAC is HMAC-SHA256 with the game key, truncated to 16 bytes', () {
    const tag = PlayerTag(player: 'p-17', team: 1, gameId: 4242);
    final payload = encodeTag(tag, key);
    final body = payload.sublist(0, payload.length - 16);
    final full = Hmac(sha256, key).convert(body).bytes;
    expect(full.length, 32);
    expect(payload.sublist(payload.length - 16), full.sublist(0, 16));
    expect(payload.length, 1 + 4 + 1 + 2 + 16);
  });

  test('a tag for another game is refused as game, before the MAC', () {
    const tag = PlayerTag(player: 'p-17', team: 1, gameId: 4243);
    final payload = encodeTag(tag, List<int>.filled(16, 7));
    expect(
      () => decodeTag(payload, gameId: gameId, gameKey: key, teamCount: 2),
      throwsA(
        isA<TagException>().having((e) => e.reason, 'r', TagFailure.game),
      ),
    );
  });

  test('the wrong game key fails the MAC', () {
    final payload = encodeTag(
      const PlayerTag(player: 'p-17', team: 1, gameId: 4242),
      key,
    );
    expect(
      () => decodeTag(
        payload,
        gameId: gameId,
        gameKey: List<int>.filled(16, 0),
        teamCount: 2,
      ),
      throwsA(isA<TagException>().having((e) => e.reason, 'r', TagFailure.mac)),
    );
  });

  test('encoding refuses bad keys and player ids', () {
    const ok = PlayerTag(player: 'p-17', team: 1, gameId: 4242);
    expect(() => encodeTag(ok, List<int>.filled(15, 0)), throwsArgumentError);
    for (final p in ['', 'p 17', 'joão', 'x' * 33]) {
      expect(
        () => encodeTag(PlayerTag(player: p, team: 1, gameId: 1), key),
        throwsArgumentError,
      );
    }
    expect(
      () => encodeTag(const PlayerTag(player: 'a', team: 256, gameId: 1), key),
      throwsArgumentError,
    );
  });

  test('a card without a player-tag record has no payload', () {
    expect(tagFromNdefMemory([0x03, 0x00, 0xfe]), isNull);
    expect(tagFromNdefMemory([]), isNull);
  });
}
