// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The registering phone's proof (lib/protocol/checkin_binding.dart) against
// the shared vectors that controller/atalaia_controller/checkin_binding.py
// checks too (the `binding` part of protocol/vectors/checkin.json).

import 'package:atalaia_app/protocol/checkin_binding.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

void main() {
  final v = loadVectors('checkin.json')['binding'] as Map<String, dynamic>;

  Future<bool> check(Map<String, dynamic> c) {
    final x = {...v, ...c};
    return verifyBinding(
      x['public_key'],
      bindingMessage(
        challenge: x['challenge'] as String,
        gameId: x['game_id'] as int,
        registrationId: x['registration_id'] as String,
        playerId: x['player_id'] as String,
        playerSecret: base64UrlNoPadDecode(x['player_secret'] as String)!,
      ),
      base64UrlNoPadDecode(x['signature'] as String)!,
    );
  }

  test('the message, the key and the signature', () async {
    final msg = bindingMessage(
      challenge: v['challenge'] as String,
      gameId: v['game_id'] as int,
      registrationId: v['registration_id'] as String,
      playerId: v['player_id'] as String,
      playerSecret: base64UrlNoPadDecode(v['player_secret'] as String)!,
    );
    expect(String.fromCharCodes(msg), v['message']);
    final key = await BindingKey.fromSeed(hexDecode(v['seed'] as String));
    expect(key.publicKeyText, v['public_key']);
    final proof = await key.prove(
      challenge: v['challenge'] as String,
      gameId: v['game_id'] as int,
      registrationId: v['registration_id'] as String,
      playerId: v['player_id'] as String,
      playerSecret: base64UrlNoPadDecode(v['player_secret'] as String)!,
    );
    expect(proof, {'challenge': v['challenge'], 'signature': v['signature']});
    expect(await check({}), isTrue);
  });

  for (final c in (v['invalid'] as List).cast<Map<String, dynamic>>()) {
    test('refused: ${c['name']}', () async {
      expect(await check(c), isFalse);
    });
  }

  test('the challenge: made and checked as the Pi does', () {
    final key = hexDecode(v['challenge_key'] as String);
    final clock = v['clock'] as int, ttl = v['ttl'] as int;
    final made = Challenges(
      clock: () => clock,
      key: key,
    ).issue(hexDecode(v['nonce'] as String));
    expect(made, v['challenge']);
    for (final (at, ok) in [
      (clock, true),
      (clock + ttl, true),
      (clock + ttl + 1, false),
    ]) {
      expect(Challenges(clock: () => at, key: key).valid(made), ok);
    }
    expect(
      Challenges(clock: () => clock, key: List.filled(32, 0)).valid(made),
      isFalse,
    );
    expect(Challenges(clock: () => clock, key: key).valid('x'), isFalse);
  });

  test('a proof is parsed strictly', () {
    final sig = v['signature'] as String;
    final ch = v['challenge'] as String;
    expect(parseBindingProof({'challenge': ch, 'signature': sig}).$1, ch);
    for (final bad in <Object?>[
      'proof',
      {'challenge': ch},
      {'challenge': ch, 'signature': sig, 'x': 1},
      {'challenge': 'short', 'signature': sig},
      {'challenge': ch, 'signature': '${sig.substring(1)}='},
    ]) {
      expect(() => parseBindingProof(bad), throwsFormatException);
    }
  });
}
