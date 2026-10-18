// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Player tokens against protocol/vectors/player_token.json, which the
// controller's Python checks too. Every vector is checked; none is skipped.

import 'package:atalaia_app/security/bytes.dart';
import 'package:atalaia_app/security/player_token.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

Matcher fails(TokenFailure reason) =>
    throwsA(isA<TokenException>().having((e) => e.reason, 'reason', reason));

void main() {
  final v = loadVectors('player_token.json');
  final key = hexDecode(v['key'] as String);
  final gameId = v['game_id'] as int;
  final teamCount = v['team_count'] as int;
  final now = v['now'] as int;

  PlayerClaims verify(String token, {List<int>? withKey, int? at}) =>
      PlayerToken.verify(
        token,
        withKey ?? key,
        gameId: gameId,
        teamCount: teamCount,
        now: at ?? now,
      );

  test('vector counts', () {
    expect(cases(v, 'valid').length, greaterThanOrEqualTo(3));
    expect(cases(v, 'invalid').length, greaterThanOrEqualTo(20));
  });

  group('valid tokens', () {
    for (final c in cases(v, 'valid')) {
      test(c['name'] as String, () {
        final claims = PlayerClaims.fromJson(c['claims']);
        final token = c['token'] as String;
        expect(verify(token), claims);
        expect(PlayerToken.issue(claims, key), token);
        expect(String.fromCharCodes(claims.payload()), c['payload']);
        expect(PlayerToken.peek(token), claims);
        expect(
          () => verify(token, withKey: List<int>.filled(32, 0)),
          fails(TokenFailure.mac),
        );
      });
    }
  });

  group('invalid tokens', () {
    for (final c in cases(v, 'invalid')) {
      test('${c['name']}: ${c['reason']}', () {
        final reason = TokenFailure.values.byName(c['reason'] as String);
        expect(() => verify(c['token'] as String), fails(reason));
      });
    }
  });

  group('claims', () {
    final first = cases(v, 'valid').first;
    final claims = PlayerClaims.fromJson(first['claims']);

    test('role, team and squad come out of a verified token', () {
      final c = verify(first['token'] as String);
      expect(c.role, PlayerRole.player);
      expect(c.team, 1);
      expect(c.squad, 2);
      expect(c.playerId, 'p-17');
    });

    test('every role round-trips', () {
      for (final role in PlayerRole.values) {
        final c = PlayerClaims(
          playerId: 'p-1',
          team: 0,
          squad: 0,
          role: role,
          gameId: gameId,
          exp: now + 60,
        );
        expect(verify(PlayerToken.issue(c, key)).role, role);
      }
      expect(PlayerRole.squadLeader.wire, 'squad_leader');
    });

    test('a token expires at exp exactly', () {
      final c = PlayerClaims(
        playerId: 'p-1',
        team: 1,
        squad: 0,
        role: PlayerRole.player,
        gameId: gameId,
        exp: now + 10,
      );
      final token = PlayerToken.issue(c, key);
      expect(verify(token, at: now + 9), c);
      expect(() => verify(token, at: now + 10), fails(TokenFailure.expired));
    });

    test('out-of-range claims are refused when issuing', () {
      PlayerClaims make({
        int team = 1,
        int squad = 0,
        int game = 1,
        int exp = 1,
      }) => PlayerClaims(
        playerId: 'p-1',
        team: team,
        squad: squad,
        role: PlayerRole.player,
        gameId: game,
        exp: exp,
      );
      expect(() => make(team: 9), fails(TokenFailure.format));
      expect(() => make(squad: 256), fails(TokenFailure.format));
      expect(() => make(game: 0), fails(TokenFailure.format));
      expect(() => make(game: 0xffff), fails(TokenFailure.format));
      expect(() => make(exp: 0), fails(TokenFailure.format));
      expect(
        () => PlayerClaims(
          playerId: 'p 1',
          team: 1,
          squad: 0,
          role: PlayerRole.player,
          gameId: 1,
          exp: 1,
        ),
        fails(TokenFailure.format),
      );
    });

    test('the token key is 16-64 bytes', () {
      expect(
        () => PlayerToken.issue(claims, List<int>.filled(15, 1)),
        throwsArgumentError,
      );
      expect(
        () => PlayerToken.issue(claims, List<int>.filled(65, 1)),
        throwsArgumentError,
      );
      expect(
        PlayerToken.issue(claims, List<int>.filled(16, 1)),
        startsWith('apt1.'),
      );
    });

    test('peek reads a forged token but verify refuses it', () {
      final forged = PlayerToken.issue(claims, List<int>.filled(32, 9));
      expect(PlayerToken.peek(forged), claims);
      expect(() => verify(forged), fails(TokenFailure.mac));
      expect(PlayerToken.peek('gm-secret'), isNull);
    });

    test('non-ASCII and over-long tokens are format errors', () {
      expect(() => verify('apt1.é.x'), fails(TokenFailure.format));
      expect(() => verify('a' * 513), fails(TokenFailure.format));
      expect(() => verify(''), fails(TokenFailure.format));
    });
  });
}
