// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// What the player's map draws (decisions MF-14, ML-5, PM-1 to PM-9): the
/// field's levels and each level's plan (image and map position), the map
/// features this token may see, and where the positions the stream gave this
/// player fall on a level's plan.
///
/// Everything is read with the player's own token from endpoints it may
/// already use (`GET /field/levels`, `/field/levels/{n}/image`,
/// `/field/levels/{n}/georef`, `/field/features`): the controller has already
/// filtered the features and the positions for this player's team and role,
/// so nothing here decides who may see what, and nothing is sent.
library;

import 'package:flutter/foundation.dart';

import '../checkin/checkin_client.dart';
import 'field_bounds.dart';

/// The levels in use (`GET /field/levels`): one while levels are off.
final class FieldLevels {
  const FieldLevels(this.names, this.hasImage, this.imageStamp);

  /// A field with one plan and no levels.
  static const single = FieldLevels([''], [false], ['']);

  /// The level names the GM gave, one per level in use ('' when none).
  final List<String> names;
  final List<bool> hasImage;

  /// Each level's plan `updated_at`, to know when it must be fetched again.
  final List<String> imageStamp;

  int get count => names.length;

  /// Whether the field has floors to choose from.
  bool get multi => count > 1;

  /// A position's level as the plan shows it: its own while in use, else
  /// level 0 (the controller's `shown`).
  int shown(int? level) =>
      level != null && level >= 0 && level < count ? level : 0;

  static FieldLevels? fromApi(Map<String, Object?> j) {
    final list = j['levels'];
    if (list is! List || list.isEmpty) return null;
    final names = <String>[], images = <bool>[], stamps = <String>[];
    for (final l in list) {
      if (l is! Map) continue;
      names.add(l['name'] is String ? l['name']! as String : '');
      final img = l['image'];
      images.add(img is Map);
      stamps.add(img is Map ? '${img['updated_at']}' : '');
    }
    return names.isEmpty ? null : FieldLevels(names, images, stamps);
  }
}

/// One level's plan: its map position (null: not placed on the ground) and
/// its image (null: none, or not fetched).
final class LevelPlan {
  const LevelPlan(this.map, this.image, this.stamp);
  final PlanToGround? map;
  final Uint8List? image;
  final String stamp;
}

/// A position that can be drawn on a level's plan.
final class MapMarker {
  const MapMarker({
    required this.playerId,
    required this.x,
    required this.y,
    required this.team,
    required this.own,
    required this.levelKnown,
  });

  final String playerId;

  /// Across and down the plan, 0-1.
  final double x, y;

  /// The 1-based team number of the position (0 or null: none).
  final int? team;
  final bool own;

  /// False for a position without a level on a field with several: it is
  /// drawn on the level being looked at, hollow (decision ML-5: a floor is
  /// never guessed).
  final bool levelKnown;
}

/// The positions to draw on [level]'s plan, and how many cannot be drawn
/// there (a position with no place on this plan: a beacon not put on the
/// plan, a fix off the plan, a plan without a map position).
({List<MapMarker> markers, int off}) markersOn(
  int level,
  Iterable<Map<String, Object?>> positions,
  FieldLevels levels,
  PlanToGround? map,
  String? me,
) {
  final out = <MapMarker>[];
  var off = 0;
  for (final p in positions) {
    final id = p['player_id'];
    if (id is! String) continue;
    final raw = p['level'];
    final known = raw is int;
    if (known && levels.shown(raw) != level) continue;
    // A beacon always carries its level: without one it is not drawn here.
    if (!known && levels.multi && p['source'] == 'ble') continue;
    double? x, y;
    if (p['x'] is num && p['y'] is num) {
      x = (p['x']! as num).toDouble();
      y = (p['y']! as num).toDouble();
    } else if (p['lat'] is num && p['lon'] is num && map != null) {
      final at = map.inverse(
        (p['lat']! as num).toDouble(),
        (p['lon']! as num).toDouble(),
      );
      if (at != null) (x, y) = at;
    }
    if (x == null ||
        y == null ||
        x < -0.02 ||
        x > 1.02 ||
        y < -0.02 ||
        y > 1.02) {
      off++;
      continue;
    }
    final team = p['team'];
    out.add(
      MapMarker(
        playerId: id,
        x: x.clamp(0.0, 1.0),
        y: y.clamp(0.0, 1.0),
        team: team is int ? team : null,
        own: id == me,
        levelKnown: known || !levels.multi,
      ),
    );
  }
  return (markers: out, off: off);
}

/// Loads and keeps the field plan for the player's map: the levels, the
/// features (from the stream when it has sent them, else fetched) and each
/// level's plan on demand. A controller without a field plan (the phone's,
/// decision MF-14) answers 404: the map is simply not shown.
class FieldPlanLoader extends ChangeNotifier {
  FieldPlanLoader(this.httpOf, this.token);

  /// The field's HTTP client, made when first needed (a bad field trust is a
  /// failure to load, not to build the screen).
  final FieldHttp Function() httpOf;

  /// The player's token now (it is renewed after a change of team or role).
  final String Function() token;

  FieldLevels? levels;
  List<Map<String, Object?>>? _features;
  final _plans = <int, LevelPlan>{};
  final _loading = <int>{};
  bool _disposed = false;

  /// The map features this token may see (empty until known).
  List<Map<String, Object?>> get features => _features ?? const [];

  LevelPlan? plan(int level) => _plans[level];

  /// Whether there is anything to draw: a plan image or a feature.
  bool get hasPlan =>
      levels != null && (levels!.hasImage.any((b) => b) || features.isNotEmpty);

  /// The levels, and the features unless the stream's list is given.
  Future<void> load({List<Map<String, Object?>>? streamFeatures}) async {
    try {
      final http = httpOf();
      final r = await http.send('GET', '/field/levels', token: token());
      if (r.ok) levels = FieldLevels.fromApi(r.json);
      if (streamFeatures != null) {
        _features = streamFeatures;
      } else {
        final f = await http.send('GET', '/field/features', token: token());
        if (f.ok) {
          _features = [
            for (final x in (f.json['features'] as List?) ?? const [])
              if (x is Map) x.cast<String, Object?>(),
          ];
        }
      }
    } on Object {
      // Out of reach: what was known stays; the next change tries again.
    }
    _changed();
  }

  /// Level [n]'s plan (its map position and image), fetched when not kept or
  /// when the controller says the image changed.
  Future<void> ensureLevel(int n) async {
    final lv = levels;
    if (lv == null || n < 0 || n >= lv.count || _loading.contains(n)) return;
    final stamp = lv.imageStamp[n];
    final kept = _plans[n];
    if (kept != null && kept.stamp == stamp) return;
    _loading.add(n);
    try {
      final http = httpOf();
      PlanToGround? map;
      final g = await http.send(
        'GET',
        '/field/levels/$n/georef',
        token: token(),
      );
      if (g.ok) map = PlanToGround.fromApi(g.json['georef']);
      Uint8List? image;
      if (lv.hasImage[n]) {
        final i = await http.send(
          'GET',
          '/field/levels/$n/image',
          token: token(),
        );
        if (i.ok) image = i.bytes;
      }
      _plans[n] = LevelPlan(map, image, stamp);
    } on Object {
      // Not this time; the map shows what it has.
    } finally {
      _loading.remove(n);
    }
    _changed();
  }

  void _changed() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
