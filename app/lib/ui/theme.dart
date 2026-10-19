// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The app's look: the Field Box's palette (the screen templates' colours,
/// so a prop and a box look alike), large type and big touch targets for
/// outdoors and gloves. Dark by default (props, night games); a light theme
/// reads better in full sun (decision PD9).
library;

import 'package:flutter/material.dart';

import 'template/screen_template.dart';

abstract final class AtalaiaColors {
  static const background = Color(0xFF101418);
  static const panel = Color(0xFF222B35);
  static const accent = Color(0xFFFFB300);
  static const danger = Color(0xFFE53935);
  static const muted = Color(0xFF9AA5B1);
  static const ok = Color(0xFF43A047);
  static const warn = Color(0xFFFB8C00);

  /// A team's colour: its name if it names one (red, blue...), else grey.
  static Color team(String? name) {
    final rgb = name == null ? null : paletteColor(name);
    return Color(0xFF000000 | (rgb ?? 0x78909C));
  }

  /// Black or white, whichever reads on [bg].
  static Color on(Color bg) =>
      bg.computeLuminance() > 0.4 ? background : Colors.white;
}

/// The colours a player can pick for a team: the palette's team colours.
const teamColourNames = ['red', 'blue', 'green', 'yellow', 'orange', 'purple'];

ThemeData atalaiaTheme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final scheme = dark
      ? const ColorScheme.dark(
          primary: AtalaiaColors.accent,
          onPrimary: AtalaiaColors.background,
          secondary: AtalaiaColors.accent,
          surface: AtalaiaColors.background,
          surfaceContainerHighest: AtalaiaColors.panel,
          surfaceContainer: Color(0xFF1A2129),
          error: AtalaiaColors.danger,
        )
      : const ColorScheme.light(
          // Darker amber: readable on white in sunlight.
          primary: Color(0xFF8A5A00),
          secondary: Color(0xFF8A5A00),
          surface: Colors.white,
          surfaceContainerHighest: Color(0xFFE8ECEF),
          surfaceContainer: Color(0xFFF2F4F6),
          error: Color(0xFFB71C1C),
        );
  final base = ThemeData(colorScheme: scheme, useMaterial3: true);
  return base.copyWith(
    scaffoldBackgroundColor: scheme.surface,
    // A size up from Material's defaults: read at arm's length, outdoors.
    textTheme: base.textTheme.copyWith(
      bodyLarge: base.textTheme.bodyLarge?.copyWith(fontSize: 18),
      bodyMedium: base.textTheme.bodyMedium?.copyWith(fontSize: 16),
      bodySmall: base.textTheme.bodySmall?.copyWith(fontSize: 14),
      titleMedium: base.textTheme.titleMedium?.copyWith(fontSize: 18),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(64, 56),
        textStyle: base.textTheme.labelLarge?.copyWith(
          fontSize: 18,
          fontWeight: FontWeight.w600,
        ),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(64, 52),
        textStyle: base.textTheme.labelLarge?.copyWith(fontSize: 17),
      ),
    ),
    listTileTheme: const ListTileThemeData(minVerticalPadding: 12),
    inputDecorationTheme: const InputDecorationTheme(
      border: OutlineInputBorder(),
    ),
  );
}
