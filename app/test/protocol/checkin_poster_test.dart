// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The check-in poster (lib/protocol/checkin_poster.dart) against the shared
// vectors that controller/atalaia_controller/checkin_poster.py checks too
// (protocol/vectors/checkin.json), and the declarations' and field
// identities' rules from the same file.

import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/checkin/field_identity.dart';
import 'package:atalaia_app/protocol/checkin_poster.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

void main() {
  final v = loadVectors('checkin.json');

  group('valid posters', () {
    for (final c in cases(v, 'valid')) {
      test('${c['name']}', () {
        final f = c['fields'] as Map<String, dynamic>;
        final payload = hexDecode(c['payload'] as String);
        final p = decodePoster(payload);
        expect(p.fieldId, f['field_id']);
        expect(p.fieldName, f['field_name']);
        expect(p.urls, f['urls']);
        expect(hexEncode(p.caSha256), f['ca_sha256']);
        expect(p.wifiSsid, f['wifi_ssid']);
        expect(p.gameId, f['game_id']);
        expect(hexEncode(encodePoster(p)), c['payload']);
        expect(posterToText(payload), c['text']);
        expect(hexEncode(posterFromText(c['text'] as String)), c['payload']);
        final again = CheckinPoster(
          fieldId: f['field_id'] as String,
          fieldName: f['field_name'] as String,
          urls: (f['urls'] as List).cast<String>(),
          caSha256: hexDecode(f['ca_sha256'] as String),
          wifiSsid: f['wifi_ssid'] as String?,
          gameId: f['game_id'] as int?,
        );
        expect(hexEncode(encodePoster(again)), c['payload']);
      });
    }
  });

  test('optional keys are skipped', () {
    final o = v['optional_keys_skipped'] as Map<String, dynamic>;
    final same = cases(v, 'valid').firstWhere((c) => c['name'] == o['same_as']);
    final p = decodePoster(hexDecode(o['payload'] as String));
    expect(hexEncode(encodePoster(p)), same['payload']);
  });

  group('invalid posters', () {
    for (final c in cases(v, 'invalid')) {
      test('${c['name']}: ${c['reason']}', () {
        expect(
          () => decodePoster(hexDecode(c['payload'] as String)),
          throwsA(
            isA<PosterException>().having(
              (e) => e.reason.name,
              'reason',
              c['reason'],
            ),
          ),
        );
      });
    }
  });

  test('texts', () {
    final texts = v['texts'] as Map<String, dynamic>;
    final same = texts['same'] as Map<String, dynamic>;
    final ref = cases(
      v,
      'valid',
    ).firstWhere((c) => c['name'] == same['same_as']);
    expect(hexEncode(posterFromText(same['text'] as String)), ref['payload']);
    for (final c in cases(texts, 'invalid')) {
      expect(
        () => posterFromText(c['text'] as String),
        throwsA(
          isA<PosterException>().having(
            (e) => e.reason,
            'reason',
            PosterFailure.text,
          ),
        ),
        reason: c['name'] as String,
      );
    }
    expect(isPosterText('  atalaia:checkin:AQ'), isTrue);
    expect(isPosterText('atalaia:join:AQ'), isFalse);
  });

  test('the short fingerprint', () {
    expect(
      shortFingerprint(List.generate(32, (i) => i)),
      '0001 0203 0405 0607',
    );
  });

  test('declarations', () {
    final d = v['declarations'] as Map<String, dynamic>;
    for (final c in cases(d, 'valid')) {
      expect(
        declarationProblem((c['declaration'] as Map).cast<String, Object?>()),
        isNull,
        reason: c['name'] as String,
      );
    }
    for (final c in cases(d, 'invalid')) {
      expect(
        declarationProblem((c['declaration'] as Map).cast<String, Object?>()),
        isNotNull,
        reason: c['name'] as String,
      );
    }
  });

  test('field identities', () {
    final ids = v['identities'] as Map<String, dynamic>;
    final pids = ids['player_ids'] as Map<String, dynamic>;
    for (final p in (pids['valid'] as List).cast<String>()) {
      expect(playerIdOk(p), isTrue, reason: p);
    }
    for (final p in (pids['invalid'] as List).cast<String>()) {
      expect(playerIdOk(p), isFalse, reason: p);
    }
    final secrets = ids['secrets'] as Map<String, dynamic>;
    for (final s in (secrets['valid'] as List).cast<String>()) {
      expect(secretOk(s), isTrue, reason: s);
    }
    for (final s in (secrets['invalid'] as List).cast<String>()) {
      expect(secretOk(s), isFalse, reason: s);
    }
    for (var i = 0; i < 50; i++) {
      expect(playerIdOk(newPlayerId()), isTrue);
      expect(secretOk(newPlayerSecret()), isTrue);
    }
  });
}
