// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The two languages have the same keys and placeholders, every key the code
// names exists, and the families of keys built at run time are complete.

import 'dart:io';

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/l10n/strings_de.dart';
import 'package:atalaia_app/l10n/strings_en.dart';
import 'package:atalaia_app/l10n/strings_pt.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:atalaia_app/ui/theme.dart';
import 'package:atalaia_app/chrono/replica.dart';
import 'package:atalaia_app/controller/controller_shell.dart';
import 'package:atalaia_app/controller/prop_link.dart';
import 'package:atalaia_app/platform/services.dart';
import 'package:atalaia_app/radio/pod_radio_link.dart';
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
      r"'((?:setup|join|chrono|replica|tags|pod|player|marshal|prop|battery|settings|nfc|gm|pin|role|home|common|ctl)\.[a-z_]+)'",
    );
    for (final f in Directory('lib').listSync(recursive: true)) {
      if (f is! File || !f.path.endsWith('.dart')) continue;
      if (f.path.contains('l10n')) continue;
      final text = f.readAsStringSync();
      used.addAll(literal.allMatches(text).map((m) => m.group(1)!));
      used.addAll(quoted.allMatches(text).map((m) => m.group(1)!));
    }
    // Not translation keys: file names and event types that look alike.
    used.removeAll({
      'replica.dart',
      'nfc.tag',
      'player.respawn',
      'gm.message',
      'battery.low',
      'chrono.violation', // an event the phone controller logs (slice S5)
      'settings.json', // the controller store's file (controller_store.dart)
    });
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
      // Plan phase E: check-in states and roles, chrono states, the prop link.
      for (final st in ['pending', 'checked_in', 'left', 'removed'])
        'checkin.status.$st',
      for (final r in [
        'player',
        'squad_leader',
        'vip',
        'marshal',
        'gm',
        'spectator',
      ])
        'checkin.role.$r',
      for (final st in ['pending', 'passed', 'refused', 'withdrawn'])
        'chrono_state.$st',
      for (final o in ['pass', 'fail', 'warn', 'unjudged', 'null'])
        'chrono.sent_$o',
      for (final st in LinkState.values) 'prop.link.${st.name}',
      // Plan phase F: the radio link through an I/O pod.
      for (final st in RadioLinkState.values) 'prop.radio.${st.name}',
      // Phase 4 plan phase 8: a scenario objective's failure reasons.
      for (final r in ['captured', 'defused', 'time', 'blocked', 'lives'])
        'player.objective_failed_$r',
      for (final t in ['completed', 'failed', 'revealed']) ...[
        'event.scenario.objective.$t.named',
        'event.scenario.objective.$t.named.no_team',
      ],
      'prop.radio.heard',
      'prop.pod_opened',
      // PE24 slice S6: the field controller's screen.
      for (final p in ControllerPhase.values) 'ctl.phase_${p.name}',
      for (final s in ['ready', 'running', 'paused', 'ended']) 'ctl.game_$s',
      for (final h in HotspotState.values) 'ctl.hotspot_${h.name}',
      for (final r in ['none', 'up', 'down', 'connecting']) 'ctl.radio_$r',
      for (final e in [
        'permission',
        'location_off',
        'incompatible_mode',
        'tethering_disallowed',
        'no_channel',
        'generic',
        'unavailable',
      ])
        'ctl.local_error_$e',
      // The settings' language buttons (settings_screen.dart).
      for (final l in AppLanguage.values) 'settings.lang_${l.code}',
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

  // German (plan phase 10, decision P5H-2): drafted by an AI model, to be
  // reviewed by a native-speaking player. Other work adds keys to English
  // and Portuguese without German; such a key shows in English, so German
  // may lack keys (tools/i18n_check.py lists them) but never has one
  // English lacks, a different placeholder or an empty text.
  group('German', () {
    test('has no key English lacks', () {
      expect(
        deStrings.keys.toSet().difference(enStrings.keys.toSet()),
        isEmpty,
      );
    });

    test('has the same placeholders, and no empty text', () {
      for (final k in deStrings.keys) {
        expect(
          placeholders(deStrings[k]!),
          placeholders(enStrings[k]!),
          reason: k,
        );
        expect(deStrings[k]!.trim(), isNotEmpty, reason: k);
      }
    });

    test(
      'a key German lacks shows in English; numbers have a decimal comma',
      () {
        const de = Strings(AppLanguage.de);
        expect(de.t('settings.lang_de'), 'Deutsch');
        expect(de.t('settings.language'), deStrings['settings.language']);
        const missing = 'test.only_in_english';
        expect(deStrings.containsKey(missing), isFalse);
        expect(de.t(missing), missing); // no text anywhere: the key itself
        final english = enStrings.keys.firstWhere(
          (k) => !deStrings.containsKey(k),
          orElse: () => '',
        );
        if (english.isNotEmpty) expect(de.t(english), enStrings[english]);
        expect(de.number(1.25, 2), '1,25');
        expect(AppLanguage.fromCode('de'), AppLanguage.de);
        expect(AppLanguage.de.locale.toString(), 'de');
      },
    );
  });
}
