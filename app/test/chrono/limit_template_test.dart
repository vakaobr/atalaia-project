// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import 'dart:io';

import 'package:atalaia_app/chrono/limit_template.dart';
import 'package:flutter_test/flutter_test.dart';

LimitTemplate load(String path) =>
    LimitTemplate.parse(File(path).readAsStringSync());

Matcher get bad => throwsA(isA<LimitTemplateException>());

const minimal = '''
format: 1
id: test
name: Test
status: unverified
warning: Unverified.
source: tests
verified_date: null
classes:
  rifle: {max_energy_j: 1.0, max_fps_020: 328, med_m: 0, fire_mode: full_auto}
''';

void main() {
  test('the built-in list is the folder', () {
    final files = Directory('lib/chrono/limit_templates')
        .listSync()
        .map((f) => f.path.replaceAll(r'\', '/'))
        .where((p) => p.endsWith('.yaml'))
        .toSet();
    expect(files, builtinLimitTemplates.toSet());
  });

  test('every built-in template loads and is marked unverified (P3-5)', () {
    for (final path in builtinLimitTemplates) {
      final t = load(path);
      expect(t.verified, isFalse, reason: path);
      expect(t.verifiedDate, isNull, reason: path);
      expect(t.warning, contains('Unverified'), reason: path);
      expect(
        t.warning,
        contains('check against current national/association rules before use'),
        reason: path,
      );
      expect(File(path).readAsStringSync(), contains('# UNVERIFIED.'));
      expect(t.classes, isNotEmpty);
      expect('lib/chrono/limit_templates/${t.id}.yaml', path);
    }
  });

  test('Portugal: class limits and minimum engagement distances', () {
    final t = load('lib/chrono/limit_templates/portugal.yaml');
    expect(t.name, 'Portugal');
    expect(t.limitFor('rifle')!.maxEnergyJ, 1.14);
    expect(t.limitFor('rifle')!.maxFps020, 350);
    expect(t.limitFor('rifle')!.fireMode, FireMode.fullAuto);
    expect(t.limitFor('dmr')!.maxEnergyJ, 1.88);
    expect(t.limitFor('dmr')!.medM, 20);
    expect(t.limitFor('dmr')!.fireMode, FireMode.semiOnly);
    expect(t.limitFor('sniper')!.maxEnergyJ, 2.81);
    expect(t.limitFor('sniper')!.medM, 30);
    expect(t.limitFor('sniper')!.fireMode, FireMode.boltOnly);
    expect(t.limitFor('cqb')!.maxEnergyJ, 0.84);
  });

  test('UK, Germany and generic CQB', () {
    final uk = load('lib/chrono/limit_templates/uk.yaml');
    expect(uk.limitFor('dmr')!.maxEnergyJ, 1.64);
    expect(uk.limitFor('sniper')!.maxEnergyJ, 2.32);
    final de = load('lib/chrono/limit_templates/germany.yaml');
    expect(de.limitFor('rifle')!.maxEnergyJ, 0.5);
    expect(de.limitFor('semi')!.maxEnergyJ, 7.5);
    expect(de.limitFor('semi')!.medM, isNull);
    final cqb = load('lib/chrono/limit_templates/generic_cqb.yaml');
    for (final c in cqb.classes.values) {
      expect(c.maxEnergyJ, 1.0);
    }
  });

  test('an unknown class has no limit', () {
    final t = load('lib/chrono/limit_templates/portugal.yaml');
    expect(t.limitFor('shotgun'), isNull);
    expect(t.limitFor('Rifle'), isNull);
  });

  test('a field overrides a class', () {
    final t = load('lib/chrono/limit_templates/portugal.yaml');
    final rifle = t.limitFor('rifle')!.copyWith(maxEnergyJ: 1.0);
    final field = t.withClasses({'rifle': rifle});
    expect(field.limitFor('rifle')!.maxEnergyJ, 1.0);
    expect(field.limitFor('rifle')!.maxFps020, 328);
    expect(field.limitFor('dmr')!.maxEnergyJ, 1.88);
    expect(field.verified, isFalse);
    expect(t.limitFor('rifle')!.maxEnergyJ, 1.14);
    expect(t.limitFor('dmr')!.copyWith(clearMed: true).medM, isNull);
  });

  test('a minimal template parses', () {
    expect(LimitTemplate.parse(minimal).limitFor('rifle')!.medM, 0);
  });

  test('malformed templates are refused', () {
    expect(() => LimitTemplate.parse('[1, 2]'), bad);
    expect(() => LimitTemplate.parse('a: [b'), bad);
    expect(
      () => LimitTemplate.parse(minimal.replaceFirst('format: 1', 'format: 2')),
      bad,
    );
    expect(() => LimitTemplate.parse('$minimal\nextra: 1'), bad);
    expect(
      () => LimitTemplate.parse(
        minimal.replaceFirst('warning: Unverified.', 'warning: null'),
      ),
      bad,
    );
    expect(
      () => LimitTemplate.parse(
        minimal.replaceFirst('status: unverified', 'status: verified'),
      ),
      bad,
    );
    expect(
      () => LimitTemplate.parse(
        minimal.replaceFirst('max_fps_020: 328', 'max_fps_020: 350'),
      ),
      bad,
    );
    expect(
      () => LimitTemplate.parse(minimal.replaceFirst('full_auto', 'burst')),
      bad,
    );
    expect(
      () => LimitTemplate.parse(minimal.replaceFirst('med_m: 0', 'med_m: -1')),
      bad,
    );
    expect(
      () => LimitTemplate.parse(
        minimal.replaceFirst('max_energy_j: 1.0', 'max_energy_j: x'),
      ),
      bad,
    );
    expect(
      () => LimitTemplate.parse(minimal.replaceFirst('id: test', 'id: Test')),
      bad,
    );
  });

  test('a verified template has a date', () {
    final t = LimitTemplate.parse(
      minimal
          .replaceFirst('status: unverified', 'status: verified')
          .replaceFirst('verified_date: null', 'verified_date: "2027-01-15"'),
    );
    expect(t.verified, isTrue);
    expect(t.verifiedDate, '2027-01-15');
  });
}
