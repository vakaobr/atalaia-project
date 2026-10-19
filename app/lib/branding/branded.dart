// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A field's look on the app's screens (decisions BR16-BR21): its accent on
/// the primary buttons ([BrandedTheme]), its logo and name in the header
/// ([BrandTitle]), its wallpaper behind the screen, blurred a little and
/// under a veil of the theme's background so text keeps its contrast
/// ([BrandBackdrop]), and team crests next to (or instead of) the colour
/// dots ([TeamCrest]). Each one is the default Atalaia look when there is
/// no branding, and when an image does not decode.
library;

import 'dart:typed_data';
import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'field_branding.dart';

/// The field's accent as the primary colour of [child]'s theme.
class BrandedTheme extends StatelessWidget {
  const BrandedTheme({required this.branding, required this.child, super.key});

  final FieldBranding? branding;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final accent = branding?.accent;
    if (accent == null) return child;
    final theme = Theme.of(context);
    final primary = brandPrimary(accent, theme.brightness);
    final on = AtalaiaColors.on(primary);
    return Theme(
      data: theme.copyWith(
        colorScheme: theme.colorScheme.copyWith(
          primary: primary,
          onPrimary: on,
          secondary: primary,
          onSecondary: on,
        ),
      ),
      child: child,
    );
  }
}

/// How much of the theme's background covers the wallpaper (decision BR18).
const wallpaperVeilDark = 0.80;
const wallpaperVeilLight = 0.86;
const wallpaperBlur = 3.0;

/// The field's wallpaper behind [child], or [child] alone.
class BrandBackdrop extends StatelessWidget {
  const BrandBackdrop({
    required this.branding,
    required this.child,
    this.dark,
    super.key,
  });

  final FieldBranding? branding;
  final Widget child;

  /// Force the dark veil (the prop's screens are always dark).
  final bool? dark;

  @override
  Widget build(BuildContext context) {
    final w = branding?.wallpaper;
    if (w == null) return child;
    final isDark = dark ?? Theme.of(context).brightness == Brightness.dark;
    final mq = MediaQuery.of(context);
    final width = (mq.size.width * mq.devicePixelRatio).round().clamp(
      320,
      2048,
    );
    final veil = isDark
        ? AtalaiaColors.background.withValues(alpha: wallpaperVeilDark)
        : Colors.white.withValues(alpha: wallpaperVeilLight);
    return Stack(
      fit: StackFit.expand,
      children: [
        ExcludeSemantics(
          child: ImageFiltered(
            imageFilter: ImageFilter.blur(
              sigmaX: wallpaperBlur,
              sigmaY: wallpaperBlur,
              tileMode: TileMode.clamp,
            ),
            child: Image.memory(
              w.bytes,
              key: const Key('brand-wallpaper'),
              fit: BoxFit.cover,
              cacheWidth: width,
              gaplessPlayback: true,
              errorBuilder: (_, _, _) => const SizedBox.shrink(),
            ),
          ),
        ),
        ColoredBox(key: const Key('brand-veil'), color: veil),
        child,
      ],
    );
  }
}

/// The field's logo, [height] tall, or nothing.
class BrandLogo extends StatelessWidget {
  const BrandLogo({required this.branding, this.height = 32, super.key});

  final FieldBranding? branding;
  final double height;

  @override
  Widget build(BuildContext context) {
    final logo = branding?.logo;
    if (logo == null) return const SizedBox.shrink();
    final dpr = MediaQuery.devicePixelRatioOf(context);
    return Image.memory(
      logo.bytes,
      key: const Key('brand-logo'),
      height: height,
      fit: BoxFit.contain,
      cacheHeight: (height * dpr).round(),
      semanticLabel: context.s.t('branding.logo', {
        'name': branding!.fieldName,
      }),
      errorBuilder: (_, _, _) => const SizedBox.shrink(),
    );
  }
}

/// An app bar title: the field's logo and name, else [fallback] (a field
/// without branding keeps the default title).
class BrandTitle extends StatelessWidget {
  const BrandTitle({required this.branding, required this.fallback, super.key});

  final FieldBranding? branding;
  final String fallback;

  @override
  Widget build(BuildContext context) {
    final b = branding;
    // A field that set nothing keeps the default title (decision BR16).
    if (b == null || b.isEmpty) return Text(fallback);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (b.logo != null) ...[
          BrandLogo(branding: b),
          const SizedBox(width: 10),
        ],
        Flexible(
          child: Text(
            b.fieldName.isEmpty ? fallback : b.fieldName,
            key: const Key('brand-name'),
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
    );
  }
}

/// A team's crest, or its colour dot.
class TeamCrest extends StatelessWidget {
  const TeamCrest({
    required this.team,
    required this.crest,
    this.size = 28,
    super.key,
  });

  final String team;
  final Uint8List? crest;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = crest;
    if (c == null) return TeamDot(team, size: size);
    final dpr = MediaQuery.devicePixelRatioOf(context);
    return SizedBox.square(
      dimension: size,
      child: Image.memory(
        c,
        key: Key('crest-$team'),
        fit: BoxFit.contain,
        cacheWidth: (size * dpr).round(),
        gaplessPlayback: true,
        errorBuilder: (_, _, _) => TeamDot(team, size: size),
      ),
    );
  }
}

/// A team's name as players see it: the game's display name, else its
/// colour in the app's language.
String teamLabel(Strings s, TeamBranding? teams, String team) =>
    teams?.displayName(team) ?? s.team(team);
