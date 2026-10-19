// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The Flutter renderer for declarative screen templates (ADR-P3-4): the
/// same files and the same layout rules as the Field Box's LVGL renderer
/// (firmware/esp32/main/screen_template.c).
///
/// The template is laid out on a 320x240 canvas, the Field Box's screen, and
/// scaled to the room it gets, so a mode's screen looks the same on a box
/// and on a phone and its font sizes scale with the display (ADR-P3-4). The
/// widgets stack in a column, centred both ways, 4 px apart; rows and
/// columns centre their children, 6 px and 4 px apart. "fill" takes the room
/// left along the parent's direction and the whole parent across it. Fonts
/// default to 20; a progress bar is 200x12 by default; a QR code 120 square.
/// Colours not set: white text on the dark background, accent bars. "team"
/// is the colour of the data's team, "contrast" black or white against what
/// is behind the widget. Rebuilding with new data is how the screen is
/// patched (ADR-P3-4's "reactive rebuild").
library;

import 'package:flutter/material.dart';

import '../qr_painter.dart';
import 'expression.dart';
import 'screen_template.dart';

/// The Field Box's screen.
const Size fieldBoxScreen = Size(320, 240);

const int colorBackground = 0x101418;
const int _colorText = 0xFFFFFF;
const int _colorDark = 0x101418;
const int _colorTrack = 0x222B35;
const int _colorBar = 0xFFB300;
const int _colorUnknown = 0x78909C; // a team without a colour

const double _barWidth = 200;
const double _barHeight = 12;
const double _qrSize = 120;
const double _defaultFont = 20;

/// The colour of a team name (red, blue...), or grey for a team whose name
/// is not a colour, as the renderers show it.
Color teamColor(String? team) {
  final rgb = team == null ? null : paletteColor(team);
  return Color(0xFF000000 | (rgb ?? _colorUnknown));
}

/// Dark text on light backgrounds (yellow), white text on the rest.
int contrastOn(int bg) {
  final r = (bg >> 16) & 0xff, g = (bg >> 8) & 0xff, b = bg & 0xff;
  return (r * 299 + g * 587 + b * 114) ~/ 1000 > 160 ? _colorDark : _colorText;
}

/// A colour property (the firmware's resolve()): null when it is not set or
/// comes out empty; [under] is the colour behind the widget.
int? resolveColor(String? v, TemplateScope scope, int under) {
  if (v == null) return null;
  if (v == 'contrast') return contrastOn(under);
  final String name;
  if (v == 'team') {
    name = interpolate('{team}', scope);
  } else if (v.startsWith('{')) {
    name = interpolate(v, scope);
  } else {
    name = v;
  }
  if (name.isEmpty) return null;
  if (name == 'contrast') return contrastOn(under);
  return paletteColor(name) ?? _colorUnknown;
}

Color _c(int rgb) => Color(0xFF000000 | rgb);

const _icons = <String, IconData>{
  'ok': Icons.check,
  'close': Icons.close,
  'warning': Icons.warning,
  'pause': Icons.pause,
  'play': Icons.play_arrow,
  'stop': Icons.stop,
  'bell': Icons.notifications,
  'home': Icons.home,
  'refresh': Icons.refresh,
  'gps': Icons.gps_fixed,
  'wifi': Icons.wifi,
  'battery': Icons.battery_full,
  'power': Icons.power_settings_new,
  'bluetooth': Icons.bluetooth,
  'settings': Icons.settings,
  'eye': Icons.visibility,
  'plus': Icons.add,
  'minus': Icons.remove,
  'left': Icons.chevron_left,
  'right': Icons.chevron_right,
  'up': Icons.expand_less,
  'down': Icons.expand_more,
  'audio': Icons.volume_up,
  'mute': Icons.volume_off,
  'bars': Icons.menu,
  'loop': Icons.loop,
  'charge': Icons.bolt,
};

/// A mode's screen: [template] filled with [data] (ui.screen's second
/// argument) and the game's [params], on a canvas of [canvas] logical
/// pixels scaled to fit.
class TemplateScreen extends StatelessWidget {
  const TemplateScreen({
    required this.template,
    this.data = const {},
    this.params = const {},
    this.canvas = fieldBoxScreen,
    super.key,
  });

  final ScreenTemplate template;
  final Map<String, Object?> data;
  final Map<String, Object?> params;
  final Size canvas;

  @override
  Widget build(BuildContext context) {
    final scope = TemplateScope(data: data, params: params);
    final bg =
        resolveColor(template.background, scope, colorBackground) ??
        colorBackground;
    final b = _Builder(template, scope);
    return ColoredBox(
      color: _c(bg),
      child: FittedBox(
        child: SizedBox.fromSize(
          size: canvas,
          child: MediaQuery.withNoTextScaling(
            child: DefaultTextStyle(
              style: TextStyle(
                color: const Color(0xFFFFFFFF),
                fontSize: _defaultFont,
                height: 1.2,
                fontFamily: Theme.of(context).textTheme.bodyMedium?.fontFamily,
              ),
              child: Semantics(
                container: true,
                label: 'screen ${template.name}',
                child: b.container(
                  template.roots.toList(),
                  row: false,
                  under: bg,
                  fixedW: true,
                  fixedH: true,
                  gap: 4,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Builder {
  _Builder(this.t, this.scope);

  final ScreenTemplate t;
  final TemplateScope scope;

  /// A row or a column (or the screen itself) with [children], centred.
  Widget container(
    List<int> children, {
    required bool row,
    required int under,
    required bool fixedW,
    required bool fixedH,
    required double gap,
  }) {
    final kids = <Widget>[
      for (final i in children)
        if (isVisible(t.widgets[i].visible, scope))
          widget(i, inRow: row, under: under, parentW: fixedW, parentH: fixedH),
    ];
    return row
        ? Row(
            mainAxisSize: fixedW ? MainAxisSize.max : MainAxisSize.min,
            mainAxisAlignment: MainAxisAlignment.center,
            spacing: gap,
            children: kids,
          )
        : Column(
            mainAxisSize: fixedH ? MainAxisSize.max : MainAxisSize.min,
            mainAxisAlignment: MainAxisAlignment.center,
            spacing: gap,
            children: kids,
          );
  }

  Widget widget(
    int i, {
    required bool inRow,
    required int under,
    required bool parentW,
    required bool parentH,
  }) {
    final w = t.widgets[i];
    final bgSet = resolveColor(w.background, scope, under);
    final below = bgSet ?? under;
    final fg = resolveColor(w.color, scope, below);

    // Which "fill" sizes take effect: along the parent's direction when the
    // parent's own size is settled there (flex grow), across it when the
    // parent's size is settled across.
    final fillW = w.width == sizeFill && parentW;
    final fillH = w.height == sizeFill && parentH;
    final growMain = inRow ? fillW : fillH;
    final fixedW = w.width >= 0 || fillW;
    final fixedH = w.height >= 0 || fillH;

    double? width = w.width >= 0 ? w.width.toDouble() : null;
    double? height = w.height >= 0 ? w.height.toDouble() : null;
    if (!inRow && fillW) width = double.infinity;
    if (inRow && fillH) height = double.infinity;

    Widget child;
    switch (w.type) {
      case WidgetType.label:
        child = Text(
          interpolate(w.content, scope),
          textAlign: _align(w.align),
          style: TextStyle(
            fontSize: w.fontSize > 0 ? w.fontSize.toDouble() : _defaultFont,
            color: _c(fg ?? _colorText),
          ),
        );
      case WidgetType.icon:
        child = Icon(
          _icons[w.content] ?? Icons.help_outline,
          size: w.fontSize > 0 ? w.fontSize.toDouble() : _defaultFont,
          color: _c(fg ?? _colorText),
        );
      case WidgetType.progressBar:
        final h = w.height > 0 ? w.height.toDouble() : _barHeight;
        width ??= (fillW ? null : _barWidth);
        height ??= (fillH ? null : _barHeight);
        child = _Bar(
          fraction: fraction(w.content, scope),
          color: _c(fg ?? _colorBar),
          radius: h / 2,
        );
      case WidgetType.qrCode:
        final size = w.width > 0
            ? w.width.toDouble()
            : (w.height > 0 ? w.height.toDouble() : _qrSize);
        child = QrCodeView(
          data: interpolate(w.content, scope),
          size: size,
          dark: _c(fg ?? _colorDark),
        );
        width = height = null;
      case WidgetType.spacer:
        width ??= 1;
        child = const SizedBox.shrink();
      case WidgetType.row || WidgetType.column:
        child = container(
          w.children,
          row: w.type == WidgetType.row,
          under: below,
          fixedW: fixedW,
          fixedH: fixedH,
          gap: w.type == WidgetType.row ? 6 : 4,
        );
    }

    final pad = w.padding;
    if (pad.any((p) => p != 0)) {
      child = Padding(
        padding: EdgeInsets.fromLTRB(
          pad[3].toDouble(),
          pad[0].toDouble(),
          pad[1].toDouble(),
          pad[2].toDouble(),
        ),
        child: child,
      );
    }
    if (w.type != WidgetType.progressBar && bgSet != null) {
      child = ColoredBox(color: _c(bgSet), child: child);
    }
    if (width != null || height != null) {
      child = SizedBox(
        width: width,
        height: height,
        child: w.type == WidgetType.label
            ? Align(alignment: _boxAlign(w.align), child: child)
            : child,
      );
    }
    child = KeyedSubtree(key: ValueKey('tpl-$i-${w.id ?? ''}'), child: child);
    return growMain ? Expanded(child: child) : child;
  }

  static TextAlign _align(TextAlignment a) => switch (a) {
    TextAlignment.left => TextAlign.left,
    TextAlignment.right => TextAlign.right,
    _ => TextAlign.center,
  };

  static Alignment _boxAlign(TextAlignment a) => switch (a) {
    TextAlignment.left => Alignment.centerLeft,
    TextAlignment.right => Alignment.centerRight,
    _ => Alignment.center,
  };
}

/// A progress bar: a dark track with a filled part.
class _Bar extends StatelessWidget {
  const _Bar({
    required this.fraction,
    required this.color,
    required this.radius,
  });

  final double fraction;
  final Color color;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final r = BorderRadius.circular(radius);
    return DecoratedBox(
      decoration: BoxDecoration(color: _c(_colorTrack), borderRadius: r),
      child: Align(
        alignment: Alignment.centerLeft,
        child: FractionallySizedBox(
          widthFactor: (fraction * 100).round() / 100,
          heightFactor: 1,
          child: DecoratedBox(
            decoration: BoxDecoration(color: color, borderRadius: r),
          ),
        ),
      ),
    );
  }
}
