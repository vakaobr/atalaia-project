// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The check-in ticket (lib/protocol/checkin_ticket.dart) against the shared
// vectors that controller/atalaia_controller/checkin_ticket.py checks too
// (the `tickets` part of protocol/vectors/checkin.json).

import 'package:atalaia_app/protocol/checkin_ticket.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

void main() {
  final v = loadVectors('checkin.json')['tickets'] as Map<String, dynamic>;

  test('vector counts', () {
    expect(cases(v, 'valid').length, greaterThanOrEqualTo(2));
    expect(cases(v, 'invalid').length, greaterThanOrEqualTo(20));
  });

  group('valid tickets', () {
    for (final c in cases(v, 'valid')) {
      test('${c['name']}', () {
        final f = c['fields'] as Map<String, dynamic>;
        final payload = hexDecode(c['payload'] as String);
        final t = decodeTicket(payload);
        expect(t.registrationId, f['registration_id']);
        expect(t.playerId, f['player_id']);
        expect(hexEncode(t.secret), f['secret']);
        expect(t.secretText.length, 43);
        expect(hexEncode(encodeTicket(t)), c['payload']);
        expect(ticketToText(payload), c['text']);
        expect(hexEncode(parseTicket(c['text'] as String).secret), f['secret']);
        final again = CheckinTicket(
          registrationId: f['registration_id'] as String,
          playerId: f['player_id'] as String,
          secret: hexDecode(f['secret'] as String),
        );
        expect(hexEncode(encodeTicket(again)), c['payload']);
      });
    }
  });

  test('optional keys are skipped', () {
    final o = v['optional_keys_skipped'] as Map<String, dynamic>;
    final same = cases(v, 'valid').firstWhere((c) => c['name'] == o['same_as']);
    final t = decodeTicket(hexDecode(o['payload'] as String));
    expect(hexEncode(encodeTicket(t)), same['payload']);
  });

  group('invalid tickets', () {
    for (final c in cases(v, 'invalid')) {
      test('${c['name']}: ${c['reason']}', () {
        expect(
          () => decodeTicket(hexDecode(c['payload'] as String)),
          throwsA(
            isA<TicketException>().having(
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
    expect(hexEncode(ticketFromText(same['text'] as String)), ref['payload']);
    for (final c in cases(texts, 'invalid')) {
      expect(
        () => ticketFromText(c['text'] as String),
        throwsA(
          isA<TicketException>().having(
            (e) => e.reason,
            'reason',
            TicketFailure.text,
          ),
        ),
        reason: c['name'] as String,
      );
    }
    expect(isTicketText(' atalaia:ticket:AQ'), isTrue);
    expect(isTicketText('atalaia:checkin:AQ'), isFalse);
  });
}
