// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The out-of-bounds warning on a player's phone (decisions MF-31 to
/// MF-40): the field's boundary (a `boundary` map feature, an area traced on
/// a level's plan, decisions MF-19 to MF-30) placed on the ground by that
/// level's map position (the controller's georef.py), and the phone's own
/// fixes tested against it.
///
/// Everything here runs on the phone, from what the player's token may
/// already read (`GET /api/v1/field/features`, `GET
/// /api/v1/field/levels/{n}/georef`) and from the fixes the phone already
/// takes to share its position (MF-31): no new report, no extra GPS fix,
/// nothing sent to anyone about the warning (MF-36).
///
/// GPS wanders, most of all near trees and walls, so the warning is not
/// given on one fix a few metres outside (MF-32): a fix is judged only when
/// its accuracy is [BoundsWatch.maxAccuracyM] or better; it counts as
/// outside only when it is further out than its own accuracy and at least
/// [BoundsWatch.minMarginM]; and the phone warns only when the fixes have
/// stayed out for [BoundsWatch.dwell]. One fix inside (on the line counts)
/// ends the warning.
library;

import 'dart:math' as math;

import '../checkin/checkin_client.dart';
import '../platform/location.dart';

/// The sphere of the core's geo.c and the controller's georef.py (ADR-P4-9).
const earthRadiusM = 6371000.0;

/// One level's field boundary on the ground: its corners as (latitude,
/// longitude) in degrees, in the order traced.
final class GroundBoundary {
  const GroundBoundary(this.level, this.corners);

  final int level;
  final List<(double, double)> corners;

  /// Whether ([lat], [lon]) is inside or on the edge: the ray casting of the
  /// core's `atalaia_geo_in_polygon` (geo.c), on the same numbers, so the
  /// phone and `geo.in_zone` agree on every point (protocol/vectors/geo.json).
  bool contains(double lat, double lon) {
    final n = corners.length;
    if (n < 3) return false;
    var inside = false;
    for (var i = 0, j = n - 1; i < n; j = i++) {
      final (yi, xi) = corners[i];
      final (yj, xj) = corners[j];
      if (lat >= math.min(yi, yj) &&
          lat <= math.max(yi, yj) &&
          lon >= math.min(xi, xj) &&
          lon <= math.max(xi, xj)) {
        final cross = (xj - xi) * (lat - yi) - (yj - yi) * (lon - xi);
        if (cross == 0.0) return true;
      }
      if ((yi > lat) != (yj > lat)) {
        final x = xi + (lat - yi) * (xj - xi) / (yj - yi);
        if (lon < x) inside = !inside;
      }
    }
    return inside;
  }

  /// How far ([lat], [lon]) is from the boundary's line, in metres: positive
  /// outside, negative inside, 0 on it. Measured in a flat plane in metres
  /// around the point (east = R cos(lat) dlon, north = R dlat), as georef.py
  /// fits its map: good to well under a metre over a field.
  double signedDistanceM(double lat, double lon) {
    final k = math.pi / 180 * earthRadiusM;
    final kLon = k * math.cos(lat * math.pi / 180);
    final pts = [
      for (final (cLat, cLon) in corners)
        ((cLon - lon) * kLon, (cLat - lat) * k),
    ];
    var best = double.infinity;
    for (var i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      best = math.min(best, _toSegment(pts[j], pts[i]));
    }
    return contains(lat, lon) ? -best : best;
  }

  /// The distance from the origin to the segment a-b.
  static double _toSegment((double, double) a, (double, double) b) {
    final (ax, ay) = a;
    final (bx, by) = b;
    final dx = bx - ax;
    final dy = by - ay;
    final len2 = dx * dx + dy * dy;
    var t = len2 == 0 ? 0.0 : -(ax * dx + ay * dy) / len2;
    t = t.clamp(0.0, 1.0);
    final px = ax + t * dx;
    final py = ay + t * dy;
    return math.sqrt(px * px + py * py);
  }
}

/// A level's map position as the controller gives it (`georef.corners`:
/// where the plan's corners are on the ground). georef.py's map is linear
/// in latitude and longitude, so three corners give it exactly.
final class PlanToGround {
  const PlanToGround(this.topLeft, this.topRight, this.bottomLeft);

  final (double, double) topLeft;
  final (double, double) topRight;
  final (double, double) bottomLeft;

  /// From `GET /api/v1/field/levels/{n}/georef`'s `georef`, or null.
  static PlanToGround? fromApi(Object? georef) {
    if (georef is! Map) return null;
    final c = georef['corners'];
    if (c is! Map) return null;
    (double, double)? at(String name) {
      final p = c[name];
      if (p is! Map || p['lat'] is! num || p['lon'] is! num) return null;
      return ((p['lat']! as num).toDouble(), (p['lon']! as num).toDouble());
    }

    final tl = at('top_left');
    final tr = at('top_right');
    final bl = at('bottom_left');
    if (tl == null || tr == null || bl == null) return null;
    return PlanToGround(tl, tr, bl);
  }

  /// A place on the plan (x across, y down, 0-1) as (latitude, longitude).
  (double, double) apply(double x, double y) => (
    topLeft.$1 +
        x * (topRight.$1 - topLeft.$1) +
        y * (bottomLeft.$1 - topLeft.$1),
    topLeft.$2 +
        x * (topRight.$2 - topLeft.$2) +
        y * (bottomLeft.$2 - topLeft.$2),
  );
}

/// The field's boundaries this phone knows, by level (at most one per level,
/// decision MF-20).
final class FieldBounds {
  const FieldBounds(this.byLevel);

  static const none = FieldBounds({});

  final Map<int, GroundBoundary> byLevel;

  bool get isEmpty => byLevel.isEmpty;

  /// The `boundary` features of [features] (the controller's list, already
  /// filtered for this token and to the levels in use), with each level's map
  /// position from [georefs]; a boundary whose level has no map position is
  /// left out (it cannot be placed on the ground).
  static FieldBounds of(
    List<Map<String, Object?>> features,
    Map<int, PlanToGround?> georefs,
  ) {
    final out = <int, GroundBoundary>{};
    for (final f in boundaries(features)) {
      final level = f['level']! as int;
      final map = georefs[level];
      if (map == null) continue;
      out[level] = GroundBoundary(level, [
        for (final p in f['points']! as List)
          map.apply(
            ((p as Map)['x']! as num).toDouble(),
            (p['y']! as num).toDouble(),
          ),
      ]);
    }
    return FieldBounds(out);
  }

  /// The well-formed `boundary` features of a feature list.
  static List<Map<String, Object?>> boundaries(
    List<Map<String, Object?>> features,
  ) => [
    for (final f in features)
      if (f['type'] == 'boundary' &&
          f['shape'] == 'polygon' &&
          f['level'] is int &&
          f['points'] is List &&
          (f['points']! as List).length >= 3 &&
          (f['points']! as List).every(
            (p) => p is Map && p['x'] is num && p['y'] is num,
          ))
        f,
  ];

  /// The boundaries a player on [level] is held to (decision MF-34): that
  /// level's, if it has one (none: no warning on that level); with the level
  /// not known, every level's, and the player is out only when outside all
  /// of them (a floor is never guessed, decision ML-5).
  List<GroundBoundary> forLevel(int? level) {
    if (level != null) {
      final b = byLevel[level];
      return b == null ? const [] : [b];
    }
    return byLevel.values.toList();
  }

  /// How far outside the nearest of [forLevel]'s boundaries the point is, in
  /// metres (negative: inside one); null with no boundary.
  double? distanceOutsideM(double lat, double lon, int? level) {
    double? best;
    for (final b in forLevel(level)) {
      final d = b.signedDistanceM(lat, lon);
      if (best == null || d < best) best = d;
    }
    return best;
  }
}

/// Fetches the field's boundaries with the player's token: the features
/// this token may see, and the map position of each level with a boundary.
/// [features]: the list the stream just sent (`map_features`), else fetched.
/// Null when the controller cannot be reached.
Future<FieldBounds?> loadFieldBounds(
  FieldHttp http,
  String token, {
  List<Map<String, Object?>>? features,
}) async {
  try {
    var list = features;
    if (list == null) {
      final r = await http.send('GET', '/field/features', token: token);
      if (!r.ok) return null;
      list = [
        for (final f in (r.json['features'] as List?) ?? const [])
          if (f is Map) f.cast<String, Object?>(),
      ];
    }
    final georefs = <int, PlanToGround?>{};
    for (final f in FieldBounds.boundaries(list)) {
      final level = f['level']! as int;
      if (georefs.containsKey(level)) continue;
      final r = await http.send(
        'GET',
        '/field/levels/$level/georef',
        token: token,
      );
      georefs[level] = r.ok ? PlanToGround.fromApi(r.json['georef']) : null;
    }
    return FieldBounds.of(list, georefs);
  } on CheckinException {
    return null;
  }
}

/// What a fix changed (decision MF-33).
enum BoundsAlert {
  /// Nothing to tell the player.
  none,

  /// The player has just left the field.
  left,

  /// Still out: a reminder (every [BoundsWatch.remindEvery]).
  stillOut,

  /// Back inside the field.
  back,
}

/// The out-of-bounds state over a player's fixes (decision MF-32): margin,
/// accuracy and dwell, so a GPS error at the edge does not warn.
class BoundsWatch {
  BoundsWatch({
    this.minMarginM = 10,
    this.maxAccuracyM = 50,
    this.unknownAccuracyM = 20,
    this.dwell = const Duration(seconds: 5),
    this.remindEvery = const Duration(seconds: 60),
  });

  /// A fix counts as outside only when further out than this, or than its
  /// accuracy if that is larger.
  final double minMarginM;

  /// Fixes less accurate than this are not judged (they change nothing).
  final double maxAccuracyM;

  /// The accuracy assumed for a fix that does not give one.
  final double unknownAccuracyM;

  /// How long the fixes must stay outside before the warning.
  final Duration dwell;

  /// How often the warning is repeated while the player stays out.
  final Duration remindEvery;

  bool _out = false;
  int? _outsideSince;
  int? _lastAlert;

  /// Whether the player is out of bounds now.
  bool get out => _out;

  /// Forgets everything (sharing stopped, the game paused or ended, the
  /// boundary changed).
  void reset() {
    _out = false;
    _outsideSince = null;
    _lastAlert = null;
  }

  /// One fix: [distanceM] is how far outside the boundary it is (negative:
  /// inside; null: no boundary for the player's level), [accuracyM] its
  /// accuracy and [tMs] when it was taken.
  BoundsAlert onFix(double? distanceM, double? accuracyM, int tMs) {
    if (distanceM == null) {
      final was = _out;
      reset();
      return was ? BoundsAlert.back : BoundsAlert.none;
    }
    final acc = accuracyM ?? unknownAccuracyM;
    if (acc > maxAccuracyM) return BoundsAlert.none;
    if (_out) {
      if (distanceM <= 0) {
        reset();
        return BoundsAlert.back;
      }
      if (tMs - _lastAlert! >= remindEvery.inMilliseconds) {
        _lastAlert = tMs;
        return BoundsAlert.stillOut;
      }
      return BoundsAlert.none;
    }
    if (distanceM <= math.max(minMarginM, acc)) {
      _outsideSince = null;
      return BoundsAlert.none;
    }
    final since = _outsideSince ??= tMs;
    if (tMs - since >= dwell.inMilliseconds) {
      _out = true;
      _lastAlert = tMs;
      return BoundsAlert.left;
    }
    return BoundsAlert.none;
  }

  /// [onFix] for a phone fix against [bounds], on [level] (null: not known).
  BoundsAlert check(
    FieldBounds bounds,
    LocationFix fix,
    int? level,
    int nowMs,
  ) => onFix(
    bounds.distanceOutsideM(fix.lat, fix.lon, level),
    fix.accuracyM,
    fix.tMs > 0 ? fix.tMs : nowMs,
  );
}
