// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The app's texts in European Portuguese (the default) and English, like
/// the GM console's (controller/console/src/i18n/) and the project page's
/// (site/i18n/): flat keys, `{name}` placeholders. Portuguese is written
/// as players say it, addressing the reader as "tu" and naming people
/// inclusively ("quem joga", "participante"). Material's own strings come
/// from flutter_localizations (pt_PT and en). The tests check that both
/// languages have the same keys and placeholders and that every key the
/// code uses exists.
library;

import 'package:flutter/widgets.dart';

import 'strings_en.dart';
import 'strings_pt.dart';

enum AppLanguage {
  pt(Locale('pt', 'PT'), ptStrings),
  en(Locale('en'), enStrings);

  const AppLanguage(this.locale, this.table);

  final Locale locale;
  final Map<String, String> table;

  /// The language code modes use in their manifests (`i18n.pt`).
  String get code => name;

  static AppLanguage fromCode(String? code) =>
      values.asNameMap()[code] ?? AppLanguage.pt;
}

class Strings {
  const Strings(this.language);

  final AppLanguage language;

  String get code => language.code;

  /// The text for [key] with its {placeholders} filled from [args]. A
  /// missing key shows itself, so it is easy to spot (and a test fails).
  String t(String key, [Map<String, Object?> args = const {}]) {
    var s = language.table[key] ?? enStrings[key] ?? key;
    if (args.isEmpty) return s;
    args.forEach((k, v) => s = s.replaceAll('{$k}', '$v'));
    return s;
  }

  /// [t], or [fallback] when there is no text for [key] (open-ended keys:
  /// a pod's capability types, event types).
  String tOr(
    String key,
    String fallback, [
    Map<String, Object?> args = const {},
  ]) => language.table.containsKey(key) || enStrings.containsKey(key)
      ? t(key, args)
      : fallback;

  /// A team's name to show: its colour in this language when the name is
  /// one of the palette's colours (red: vermelha), otherwise as the game
  /// names it.
  String team(String name) => tOr('team.$name', name);

  /// [v] with [decimals] decimals, with a decimal comma in Portuguese.
  String number(double v, int decimals) {
    final t = v.toStringAsFixed(decimals);
    return language == AppLanguage.pt ? t.replaceAll('.', ',') : t;
  }

  static Strings of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<StringsScope>()?.strings ??
      const Strings(AppLanguage.pt);
}

class StringsScope extends InheritedWidget {
  const StringsScope({required this.strings, required super.child, super.key});

  final Strings strings;

  @override
  bool updateShouldNotify(StringsScope old) =>
      old.strings.language != strings.language;
}

extension StringsContext on BuildContext {
  Strings get s => Strings.of(this);
}
