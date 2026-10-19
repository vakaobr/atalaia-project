// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The two languages have the same keys and placeholders, every key the code
// names exists, and the families of keys built at run time are complete.

import 'dart:io';

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/l10n/strings_en.dart';
import 'package:atalaia_app/l10n/strings_pt.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:atalaia_app/ui/theme.dart';
import 'package:atalaia_app/chrono/replica.dart';
import 'package:flutter_test/flutter_test.dart';

Set<String> placeholders(String s) =>
    RegExp(r'\{(\w+)\}').allMatches(s).map((m) => m.group(1)!).toSet();

void main() {
  test('European Portuguese and English have the same keys', () {
    expect(ptStrings.keys.toSet(), enStrings.keys.toSet());
  });

  test('and the same placeholders', () {
    for (final k in ptStrings.keys) {
      expect(
        placeholders(ptStrings[k]!),
        placeholders(enStrings[k]!),
        reason: k,
      );
    }
  });

  test('no text is empty or left untranslated by mistake', () {
    for (final k in ptStrings.keys) {
      expect(ptStrings[k]!.trim(), isNotEmpty, reason: k);
      expect(enStrings[k]!.trim(), isNotEmpty, reason: k);
    }
  });

  test('every key the code names exists', () {
    final used = <String>{};
    final literal = RegExp(r"""\bt(?:Or)?\(\s*'([a-z_]+\.[a-z0-9_.]+)'""");
    final quoted = RegExp(
      r"'((?:setup|join|chrono|replica|tags|pod|player|marshal|prop|battery|settings|nfc|gm|pin|role|home|common)\.[a-z_]+)'",
    );
    for (final f in Directory('lib').listSync(recursive: true)) {
      if (f is! File || !f.path.endsWith('.dart')) continue;
      if (f.path.contains('l10n')) continue;
      final text = f.readAsStringSync();
      used.addAll(literal.allMatches(text).map((m) => m.group(1)!));
      used.addAll(quoted.allMatches(text).map((m) => m.group(1)!));
    }
    // Not translation keys: file names and event types that look alike.
    used.removeAll({'replica.dart', 'nfc.tag', 'player.respawn', 'gm.message'});
    expect(used.length, greaterThan(150));
    final missing = used.where((k) => !ptStrings.containsKey(k)).toList()
      ..sort();
    expect(missing, isEmpty);
  });

  test('the keys built at run time are all there', () {
    final keys = <String>[
      for (final g in [
        'samsung',
        'xiaomi',
        'huawei',
        'oneplus',
        'generic',
      ]) ...['battery.on_$g', 'battery.on_${g}_title'],
      for (final p in PropPhase.values) 'prop.phase_${p.name}',
      for (final t in ReplicaType.values) 'replica.type_${t.wire}',
      for (final t in teamColourNames) 'team.$t',
      for (final s in ['ready', 'running', 'paused', 'ended']) 'state.$s',
      for (final c in [
        'team_input', 'keypad', 'display', 'team_display', 'led', 'audio', //
        'haptic', 'nfc', 'gps', 'imu', 'qr_scanner',
      ])
        'cap.$c',
      for (final r in [
        'not_ndef',
        'read_only',
        'too_small',
        'io',
        'unavailable',
      ])
        'tags.write_$r',
    ];
    for (final k in keys) {
      expect(ptStrings.containsKey(k), isTrue, reason: k);
    }
  });

  test('placeholders are filled; a missing key shows itself', () {
    const pt = Strings(AppLanguage.pt);
    const en = Strings(AppLanguage.en);
    expect(pt.t('player.winner', {'team': 'azul'}), 'Vence a equipa azul');
    expect(en.t('player.winner', {'team': 'blue'}), 'blue team wins');
    expect(pt.t('no.such.key'), 'no.such.key');
    expect(pt.tOr('cap.lasers', 'lasers'), 'lasers');
    expect(pt.team('red'), 'vermelha');
    expect(en.team('red'), 'red');
    expect(pt.team('Lobos'), 'Lobos');
    expect(AppLanguage.fromCode('en'), AppLanguage.en);
    expect(AppLanguage.fromCode('xx'), AppLanguage.pt);
    expect(AppLanguage.pt.locale.toString(), 'pt_PT');
  });
}
