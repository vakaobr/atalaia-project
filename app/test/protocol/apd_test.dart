// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// APD membership (protocol/apd.md) against the shared vectors
// protocol/vectors/apd.json, and the shipped list against the registry's.

import 'dart:io';

import 'package:atalaia_app/protocol/apd.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

void main() {
  final v = loadVectors('apd.json');

  group('rules (apd.json)', () {
    for (final c in cases(v, 'rule_valid')) {
      test('valid: ${c['name']}', () {
        expect(ApdRule.parse(c['input']).toJson(), c['rule']);
      });
    }
    for (final c in cases(v, 'rule_invalid')) {
      test('invalid: ${c['name']}', () {
        expect(
          () => ApdRule.parse(c['input']),
          throwsA(isA<ApdError>().having((e) => e.code, 'code', c['error'])),
        );
      });
    }
  });

  group('memberships (apd.json)', () {
    for (final c in cases(v, 'membership_valid')) {
      test('valid: ${c['name']}', () {
        final m = ApdMembership.parse(c['input']);
        expect(m.toJson(), c['membership']);
      });
    }
    for (final c in cases(v, 'membership_invalid')) {
      test('invalid: ${c['name']}', () {
        expect(
          () => ApdMembership.parse(c['input']),
          throwsA(isA<ApdError>().having((e) => e.code, 'code', c['error'])),
        );
      });
    }
  });

  group('verdicts (apd.json)', () {
    for (final c in cases(v, 'status')) {
      test(c['name'] as String, () {
        final m = ApdMembership.parse(
          (c['membership'] as Map).cast<String, Object?>(),
        );
        expect(
          apdStatus(ApdRule.parse(c['rule']), m, c['on'] as String),
          c['status'],
        );
      });
    }
    test('no rule asks: no verdict', () {
      expect(
        apdVerdict(ApdRule.defaults, const ApdMembership(), '2026-11-15'),
        isNull,
      );
    });
  });

  group('countries (apd.json)', () {
    for (final c in cases(v, 'country_valid')) {
      test('valid: ${c['name']}', () {
        expect(checkApdCountry(c['input']), c['country']);
      });
    }
    for (final c in cases(v, 'country_invalid')) {
      test('invalid: ${c['name']}', () {
        expect(
          () => checkApdCountry(c['input']),
          throwsA(isA<ApdError>().having((e) => e.code, 'code', c['error'])),
        );
      });
    }
    for (final c in cases(v, 'default_country')) {
      test('default for ${c['zone']}', () {
        expect(apdDefaultCountry(c['zone'] as String?), c['country']);
      });
    }
    for (final c in cases(v, 'wording')) {
      test('wording for ${c['country']}', () {
        expect(apdWording(c['country'] as String?), c['wording']);
      });
    }
    for (final c in cases(v, 'choices')) {
      test('offers: ${c['name']}', () {
        final project = [
          for (final e in (c['project'] as List).cast<Map<String, Object?>>())
            ApdEntry(
              id: e['id'] as String,
              country: e['country'] as String?,
              name: e['name'] as String,
              shortName: e['short_name'] as String,
              website: e['website'] as String?,
            ),
        ];
        final offered = apdOffered(
          project,
          ApdRule.parse(c['rule']),
          c['country'] as String?,
        );
        expect([for (final e in offered) e.id], c['ids']);
      });
    }
    test('a phone gives only an abbreviation of its zone', () {
      expect(apdDefaultCountry(apdZoneOfAbbreviation('WET')), 'PT');
      expect(apdDefaultCountry(apdZoneOfAbbreviation('WEST')), 'PT');
      expect(apdDefaultCountry(apdZoneOfAbbreviation('AZOT')), 'PT');
      expect(apdDefaultCountry(apdZoneOfAbbreviation('CET')), isNull);
      expect(apdDefaultCountry(apdZoneOfAbbreviation('UTC')), isNull);
    });
  });

  test('the shipped list is the registry\'s', () {
    final shipped = File('assets/apds.json').readAsBytesSync();
    final registry = File('../registry/apds/apds.json').readAsBytesSync();
    expect(shipped, registry);
    final list = parseApdList(String.fromCharCodes(shipped));
    expect(list, isA<List<ApdEntry>>());
    for (final e in list) {
      expect(e.country, matches(RegExp(r'^[A-Z]{2}$')), reason: e.id);
    }
  });
}
