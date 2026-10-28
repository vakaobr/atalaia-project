// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The field plan and the positions on it, in the player's view (decisions
/// PM-1 to PM-9; MF-14, ML-5): the level's plan image under the map features
/// this player may see (pins, circles, areas, the field's boundary), and on
/// top the positions the stream gives this player.
///
/// Only the vector plan is drawn: the app has no tile layer and the plan
/// needs none. Who may see what is the controller's: the features and the
/// positions are the lists it filtered for this token (teams, roles, the
/// organisers' own features, a grant between teams), and nothing is hidden or
/// shown here beyond that.
library;

import 'dart:async';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../controller/controller_atak.dart' show featureColour, teamColour;
import '../l10n/strings.dart';
import '../position/field_plan.dart';
import 'field_feed.dart';

/// A signed 32-bit ARGB (ATAK's colours) as a Flutter colour.
Color _argb(int v) => Color(v & 0xFFFFFFFF);

/// The icon of a feature's pin.
IconData featureIcon(String? type) => switch (type) {
  'safe_zone' => Icons.shield_outlined,
  'respawn' => Icons.refresh,
  'hq' => Icons.flag,
  'parking' => Icons.local_parking,
  'first_aid' => Icons.medical_services_outlined,
  'objective' => Icons.adjust,
  _ => Icons.circle_outlined,
};

/// A level's name as the GM gave it, else "Level n".
String levelName(Strings s, FieldLevels levels, int n) {
  final name = n < levels.count ? levels.names[n] : '';
  return name.isNotEmpty ? name : s.t('player.level_n', {'n': n});
}

class FieldMapCard extends StatefulWidget {
  const FieldMapCard({
    required this.loader,
    required this.feed,
    this.myLevel,
    super.key,
  });

  final FieldPlanLoader loader;
  final FieldFeed feed;

  /// The player's own level (their choice, or the controller's), where the
  /// map opens.
  final int? myLevel;

  @override
  State<FieldMapCard> createState() => _FieldMapCardState();
}

class _FieldMapCardState extends State<FieldMapCard> {
  int? _viewed;
  final _gridAsked = <int>{};

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final loader = widget.loader;
    final levels = loader.levels;
    if (levels == null || !loader.hasPlan) return const SizedBox.shrink();
    final level = levels.shown(_viewed ?? widget.myLevel);
    final plan = loader.plan(level);
    if (plan == null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) loader.ensureLevel(level);
      });
    }
    if (_gridAsked.add(level)) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) unawaited(loader.refreshGrid(level));
      });
    }
    final grid = loader.grid(level);
    final feed = widget.feed;
    final features = [
      for (final f in loader.features)
        if (levels.shown(f['level'] is int ? f['level']! as int : null) ==
            level)
          f,
    ];
    final me = feed.me?['player_id'] as String?;
    final placed = markersOn(
      level,
      feed.positions.values,
      levels,
      plan?.map,
      me,
    );
    final teams = feed.teams;
    final name = levelName(s, levels, level);
    final mine = placed.markers.where((m) => m.own).firstOrNull;
    final myCell = grid == null || mine == null
        ? null
        : grid.cell(mine.x, mine.y);
    return Card(
      key: const Key('player-map'),
      margin: const EdgeInsets.symmetric(vertical: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              s.t('player.map_title'),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            if (levels.multi)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Wrap(
                  spacing: 8,
                  runSpacing: 4,
                  children: [
                    for (var n = 0; n < levels.count; n++)
                      ChoiceChip(
                        key: Key('map-level-$n'),
                        label: Text(levelName(s, levels, n)),
                        selected: n == level,
                        onSelected: (_) => setState(() => _viewed = n),
                      ),
                  ],
                ),
              ),
            const SizedBox(height: 8),
            Semantics(
              label:
                  s.t('player.map_semantics', {
                    'level': name,
                    'n': placed.markers.length,
                  }) +
                  (myCell == null
                      ? ''
                      : '. ${s.t('player.map_cell', {'cell': myCell})}'),
              child: _PlanView(
                plan: plan,
                features: features,
                markers: placed.markers,
                teams: teams,
                grid: grid,
                s: s,
              ),
            ),
            if (myCell != null)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  s.t('player.map_cell', {'cell': myCell}),
                  key: const Key('map-cell'),
                  style: Theme.of(context).textTheme.titleSmall,
                ),
              ),
            if (placed.off > 0)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  s.t('player.map_off_plan', {'n': placed.off}),
                  key: const Key('map-off-plan'),
                  style: TextStyle(color: Theme.of(context).hintColor),
                ),
              ),
            if (placed.markers.any((m) => !m.levelKnown))
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  s.t('player.map_level_unknown'),
                  key: const Key('map-level-unknown'),
                  style: TextStyle(color: Theme.of(context).hintColor),
                ),
              ),
            _Legend(features: features),
          ],
        ),
      ),
    );
  }
}

/// The plan: image, areas, pins and positions, in the image's proportions.
class _PlanView extends StatefulWidget {
  const _PlanView({
    required this.plan,
    required this.features,
    required this.markers,
    required this.teams,
    required this.grid,
    required this.s,
  });

  final FieldGrid? grid;
  final LevelPlan? plan;
  final List<Map<String, Object?>> features;
  final List<MapMarker> markers;
  final List<String> teams;
  final Strings s;

  @override
  State<_PlanView> createState() => _PlanViewState();
}

class _PlanViewState extends State<_PlanView> {
  double? _imageAspect;
  ImageStream? _stream;
  ImageStreamListener? _listener;
  MemoryImage? _image;

  /// Learns the image's proportions when the map position gives none.
  void _watch(BuildContext context) {
    final bytes = widget.plan?.image;
    if (bytes == null) {
      _unwatch();
      _image = null;
      _imageAspect = null;
      return;
    }
    if (_image != null && identical(_image!.bytes, bytes)) return;
    _unwatch();
    final image = _image = MemoryImage(bytes);
    _imageAspect = null;
    final stream = image.resolve(createLocalImageConfiguration(context));
    final listener = ImageStreamListener((info, _) {
      if (mounted && identical(_image, image)) {
        setState(() => _imageAspect = info.image.width / info.image.height);
      }
    }, onError: (_, _) {});
    stream.addListener(listener);
    _stream = stream;
    _listener = listener;
  }

  void _unwatch() {
    final l = _listener;
    if (l != null) _stream?.removeListener(l);
    _stream = null;
    _listener = null;
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _watch(context);
  }

  @override
  void didUpdateWidget(_PlanView old) {
    super.didUpdateWidget(old);
    _watch(context);
  }

  @override
  void dispose() {
    _unwatch();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final plan = widget.plan;
    final ground = plan?.map?.groundSizeM;
    final aspect = ground != null
        ? ground.$1 / ground.$2
        : (_imageAspect ?? 4 / 3);
    final scheme = Theme.of(context).colorScheme;
    // A very tall plan is kept to the screen's height, in its proportions.
    final maxH = math.max(240.0, MediaQuery.sizeOf(context).height * 0.6);
    return LayoutBuilder(
      builder: (context, box) {
        var w = box.maxWidth;
        var h = w / aspect;
        if (h > maxH) {
          h = maxH;
          w = h * aspect;
        }
        Widget at(double x, double y, double size, Widget child) => Positioned(
          left: x * w - size / 2,
          top: y * h - size / 2,
          width: size,
          height: size,
          child: child,
        );
        return Center(
          child: SizedBox(
            key: const Key('map-plan'),
            width: w,
            height: h,
            child: ClipRect(
              child: Stack(
                children: [
                  Positioned.fill(
                    child: ColoredBox(color: scheme.surfaceContainerHighest),
                  ),
                  if (plan?.image != null)
                    Positioned.fill(
                      child: Image.memory(
                        plan!.image!,
                        fit: BoxFit.fill,
                        gaplessPlayback: true,
                        errorBuilder: (_, _, _) => const SizedBox.shrink(),
                      ),
                    ),
                  if (widget.grid != null)
                    Positioned.fill(
                      child: CustomPaint(
                        key: const Key('map-grid'),
                        painter: _GridPainter(widget.grid!),
                      ),
                    ),
                  Positioned.fill(
                    child: CustomPaint(
                      key: const Key('map-shapes'),
                      painter: _ShapesPainter(
                        widget.features,
                        widget.teams,
                        ground,
                      ),
                    ),
                  ),
                  for (final f in widget.features)
                    if (f['type'] != 'boundary' && _centre(f) != null)
                      at(
                        _centre(f)!.$1,
                        _centre(f)!.$2,
                        26,
                        _Pin(
                          key: Key('map-feature-${f['id']}'),
                          feature: f,
                          teams: widget.teams,
                          s: widget.s,
                        ),
                      ),
                  for (final m in widget.markers)
                    at(
                      m.x,
                      m.y,
                      m.own ? 24 : 18,
                      _Dot(
                        key: Key(m.own ? 'map-me' : 'map-player-${m.playerId}'),
                        marker: m,
                        teams: widget.teams,
                        s: widget.s,
                      ),
                    ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

/// Where a feature's pin goes: its place, or an area's vertex average.
(double, double)? _centre(Map<String, Object?> f) {
  if (f['shape'] == 'polygon') {
    final pts = _points(f);
    if (pts.isEmpty) return null;
    return (
      pts.map((p) => p.$1).reduce((a, b) => a + b) / pts.length,
      pts.map((p) => p.$2).reduce((a, b) => a + b) / pts.length,
    );
  }
  final x = f['x'], y = f['y'];
  return x is num && y is num ? (x.toDouble(), y.toDouble()) : null;
}

List<(double, double)> _points(Map<String, Object?> f) => [
  if (f['points'] is List)
    for (final p in f['points']! as List)
      if (p is Map && p['x'] is num && p['y'] is num)
        ((p['x']! as num).toDouble(), (p['y']! as num).toDouble()),
];

String featureLabel(Strings s, Map<String, Object?> f) {
  final type = s.t('player.feature.${f['type']}');
  final label = f['label'];
  return label is String && label.isNotEmpty ? '$type: $label' : type;
}

class _Pin extends StatelessWidget {
  const _Pin({
    required this.feature,
    required this.teams,
    required this.s,
    super.key,
  });

  final Map<String, Object?> feature;
  final List<String> teams;
  final Strings s;

  @override
  Widget build(BuildContext context) {
    final colour = _argb(featureColour(feature, teams));
    final label = featureLabel(s, feature);
    return Semantics(
      container: true,
      label: label,
      child: Tooltip(
        message: label,
        excludeFromSemantics: true,
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: colour,
            shape: BoxShape.circle,
            border: Border.all(color: Colors.white, width: 1.5),
          ),
          child: Icon(
            featureIcon('${feature['type']}'),
            size: 15,
            color: colour.computeLuminance() > 0.5
                ? Colors.black87
                : Colors.white,
          ),
        ),
      ),
    );
  }
}

class _Dot extends StatelessWidget {
  const _Dot({
    required this.marker,
    required this.teams,
    required this.s,
    super.key,
  });

  final MapMarker marker;
  final List<String> teams;
  final Strings s;

  @override
  Widget build(BuildContext context) {
    final n = marker.team;
    final team = n != null && n >= 1 && n <= teams.length ? teams[n - 1] : null;
    final colour = _argb(teamColour(team, teams));
    final label = marker.own
        ? s.t('player.map_you')
        : team == null
        ? s.t('player.map_player')
        : s.t('player.map_player_team', {'team': team});
    return Semantics(
      container: true,
      label: marker.levelKnown
          ? label
          : '$label (${s.t('player.map_level_unknown_short')})',
      child: Tooltip(
        message: label,
        excludeFromSemantics: true,
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: marker.levelKnown ? colour : colour.withValues(alpha: 0.25),
            shape: BoxShape.circle,
            border: Border.all(
              color: marker.own ? Colors.white : Colors.black87,
              width: marker.own ? 3 : 1.5,
            ),
            boxShadow: marker.own
                ? [BoxShadow(color: colour, spreadRadius: 2)]
                : null,
          ),
        ),
      ),
    );
  }
}

/// The types of the features on this level, each with its icon and colour,
/// so the map reads without telling colours apart.
class _Legend extends StatelessWidget {
  const _Legend({required this.features});
  final List<Map<String, Object?>> features;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final types = <String>{
      for (final f in features)
        if (f['type'] is String) f['type']! as String,
    }.toList()..sort();
    if (types.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Wrap(
        key: const Key('map-legend'),
        spacing: 12,
        runSpacing: 4,
        children: [
          for (final t in types)
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  featureIcon(t),
                  size: 16,
                  color: _argb(featureColour({'type': t}, const [])),
                ),
                const SizedBox(width: 4),
                Text(
                  s.t('player.feature.$t'),
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
        ],
      ),
    );
  }
}

/// Areas, circles and the field's boundary under the pins (the console's
/// `featureShapes`): the plan outside the boundary dimmed, circles to scale
/// when the plan has a map position, else a nominal size.
class _ShapesPainter extends CustomPainter {
  _ShapesPainter(this.features, this.teams, this.ground);

  final List<Map<String, Object?>> features;
  final List<String> teams;
  final (double, double)? ground;

  static const _nominal = 0.04; // the console's NOMINAL_RADIUS

  @override
  void paint(Canvas canvas, Size size) {
    ui.Offset p((double, double) v) =>
        Offset(v.$1 * size.width, v.$2 * size.height);
    for (final f in features) {
      if (f['type'] != 'boundary') continue;
      final pts = _points(f);
      if (pts.length < 3) continue;
      final area = Path()..addPolygon([for (final v in pts) p(v)], true);
      final dim = Path()
        ..fillType = PathFillType.evenOdd
        ..addRect(Offset.zero & size)
        ..addPath(area, Offset.zero);
      canvas.drawPath(dim, Paint()..color = const Color(0x59000000));
      canvas.drawPath(
        area,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2.5
          ..color = _argb(featureColour(f, teams)),
      );
    }
    for (final f in features) {
      final type = f['type'];
      if (type == 'boundary') continue;
      final colour = _argb(featureColour(f, teams));
      final fill = Paint()..color = colour.withValues(alpha: 0.25);
      final line = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..color = colour;
      if (f['shape'] == 'circle') {
        final c = _centre(f);
        final r = f['radius_m'];
        if (c == null) continue;
        final rx = ground != null && r is num
            ? r / ground!.$1 * size.width
            : _nominal * size.width;
        final ry = ground != null && r is num
            ? r / ground!.$2 * size.height
            : _nominal * size.width;
        final rect = Rect.fromCenter(
          center: p(c),
          width: rx * 2,
          height: ry * 2,
        );
        canvas.drawOval(rect, fill);
        canvas.drawOval(rect, line);
      } else if (f['shape'] == 'polygon') {
        final pts = _points(f);
        if (pts.length < 3) continue;
        final path = Path()..addPolygon([for (final v in pts) p(v)], true);
        canvas.drawPath(path, fill);
        canvas.drawPath(path, line);
      }
    }
  }

  @override
  bool shouldRepaint(_ShapesPainter old) =>
      old.features != features || old.ground != ground || old.teams != teams;
}

/// The field grid over the plan (the console's field-grid.js): thin white
/// lines and the row letters and column numbers on a dark halo, thinned out
/// when the cells are too small to read.
class _GridPainter extends CustomPainter {
  _GridPainter(this.grid);

  final FieldGrid grid;

  static const _minLabelPx = 26.0;

  @override
  void paint(Canvas canvas, Size size) {
    final cw = size.width / grid.cols, ch = size.height / grid.rows;
    final halo = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.4
      ..color = const Color(0x66000000);
    final line = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1
      ..color = const Color(0xB3FFFFFF);
    for (var c = 0; c <= grid.cols; c++) {
      final x = c * cw;
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), halo);
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), line);
    }
    for (var r = 0; r <= grid.rows; r++) {
      final y = r * ch;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), halo);
      canvas.drawLine(Offset(0, y), Offset(size.width, y), line);
    }
    final stepC = math.max(1, (_minLabelPx / cw).ceil());
    final stepR = math.max(1, (_minLabelPx / ch).ceil());
    void label(String text, Offset at) {
      final tp = TextPainter(
        text: TextSpan(
          text: text,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 11,
            fontWeight: FontWeight.w600,
            shadows: [Shadow(blurRadius: 3), Shadow(blurRadius: 1)],
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, at - Offset(tp.width / 2, tp.height / 2));
    }

    for (var c = 0; c < grid.cols; c += stepC) {
      label('${c + 1}', Offset((c + 0.5) * cw, 8));
    }
    for (var r = 0; r < grid.rows; r += stepR) {
      label(FieldGrid.rowLabel(r), Offset(8, (r + 0.5) * ch));
    }
  }

  @override
  bool shouldRepaint(_GridPainter old) => old.grid != grid;
}
