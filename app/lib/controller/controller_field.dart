// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The field plan on the Android field controller (slice S7a of PE24): the
/// Pi controller's field image and floor plans per level, its multi-story
/// levels, the map position of each plan, the map features (the field
/// boundary among them), the field loaded from a map and the boxes' places
/// on the plan, with the same rules, endpoints and stream messages
/// (controller_api.dart; the shared contract cases check both):
///
///   - levels (field_levels.py, decisions ML-0 to ML-12): off by default
///     (one plan, level 0); on, 2 to 10 levels with names; fewer levels
///     take the plans, own map positions and map features of the levels
///     that go, and move the boxes on them to level 0;
///   - a plan per level (PNG, JPEG or WebP, at most [fieldImageMax] bytes);
///     a new or removed plan drops its level's map position (decision M9-4);
///   - the map position (georef.py, GR-1, decisions M9-1 to M9-4): two
///     opposite corners of a north-up plan, or 3 to 8 points fitted by
///     least squares in a local plane in metres, with the Pi's refusals; a
///     level without its own shares level 0's (ML-6);
///   - map features (map_features.py, decisions MF-0 to MF-49): points,
///     circles and polygons of eight types, the field boundary at most once
///     per level, each with a visibility checked here on every path (REST
///     and the stream's `map_features` message, which each connection gets
///     filtered for its own token: MF-3, MF-10);
///   - the field from a map (field_map.py, MF-26): the plan, its map
///     position from its edges and the boundary, written together or not
///     at all;
///   - the boxes' places (`/api/v1/games/{id}/positions`, MF-14), with
///     their level;
///   - the field grid (field_grid.py, decisions MF-81 to MF-93): lettered
///     rows and numbered columns over each level's plan, off by default,
///     set by the GM and sent with the field from a map; fewer levels take
///     the grids of the levels that go;
///   - the indoor BLE beacon registry (beacons.py, ADR-P3-6, decisions BLE-1
///     to BLE-9; controller_field_beacons.dart): which beacon is in which
///     room, zone and level and where on its plan, the rooms position
///     reports that name a beacon turn into.
///
/// Storage (decision PE24-75): one store document, `field` (the levels, the
/// map positions' points, the plans' types and sizes, the features, the
/// grids), and each plan's bytes in a file of [ControllerField.dir] (the
/// controller's folder in the app's private storage), named with a serial
/// number. A new
/// plan is written to a new file first and becomes the plan only when the
/// document naming it is replaced (the store renames it over the old one),
/// so the field from a map is all or nothing as the Pi's SQLite transaction
/// is; files no document names (a crash between the two) are removed when
/// the controller starts. The boxes' places are the document
/// `field_places`. Without [ControllerField.dir] the plans stay in memory
/// (tests).
library;

import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'controller_checkin.dart';
import 'controller_engine.dart';

part 'controller_field_beacons.dart';

/// Bytes of one level's plan (store.py FIELD_IMAGE_MAX).
const fieldImageMax = 4 * 1024 * 1024;

/// Levels of a multi-story field (decision ML-1).
const fieldLevelsMax = 10;
const fieldLevelsMin = 2;
const levelNameMax = 32;

/// The plans' content types (api.py IMAGE_TYPES).
const fieldImageTypes = {'image/png', 'image/jpeg', 'image/webp'};

// --- small checks shared with the Pi's ----------------------------------------

bool _controlChar(int c) => c < 0x20 || (c >= 0x7f && c < 0xa0);

/// A one-line text: spaces folded, tabs and line breaks refused, at most
/// [limit] characters (field_levels.py `_name`, map_features.py `_text`).
String _oneLine(Object? v, String where, int limit, {bool nullable = false}) {
  if (v == null && nullable) return '';
  if (v is! String) throw ControllerError('$where: a text');
  final text = v.split(' ').where((w) => w.isNotEmpty).join(' ');
  if (text.runes.length > limit || v.runes.any(_controlChar)) {
    throw ControllerError('$where: at most $limit characters on one line');
  }
  return text;
}

bool _isNum(Object? v) => v is num && v.isFinite;

// --- the map position (georef.py) -------------------------------------------

const _earthRadiusM = 6371000.0;
const georefPointsMin = 2, georefPointsMax = 8;
const _minImageSep = 0.05;
const _minImageArea = 0.01;
const _minGroundSepM = 1.0;
const _minGroundAreaM2 = 1.0;
const _maxSpanM = 20000.0;
const georefMaxLat = 85.0;
const _maxResidual = 0.05;
const _minResidualM = 5.0;

/// Control points that do not make a map; the message says what to change.
class GeorefException implements Exception {
  GeorefException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// x' = a x + b y + c, y' = d x + e y + f.
final class _Affine {
  const _Affine(this.a, this.b, this.c, this.d, this.e, this.f);
  final double a, b, c, d, e, f;
  (double, double) apply(double x, double y) =>
      (a * x + b * y + c, d * x + e * y + f);
  double get det => a * e - b * d;
}

List<double> _solve3(List<List<double>> m, List<double> v) {
  final a = [
    for (var i = 0; i < 3; i++) [...m[i], v[i]],
  ];
  for (var col = 0; col < 3; col++) {
    var piv = col;
    for (var r = col + 1; r < 3; r++) {
      if (a[r][col].abs() > a[piv][col].abs()) piv = r;
    }
    if (a[piv][col] == 0.0) {
      throw GeorefException('the control points are on one line');
    }
    final t = a[col];
    a[col] = a[piv];
    a[piv] = t;
    for (var r = col + 1; r < 3; r++) {
      final k = a[r][col] / a[col][col];
      for (var c = col; c < 4; c++) {
        a[r][c] -= k * a[col][c];
      }
    }
  }
  final out = [0.0, 0.0, 0.0];
  for (final r in [2, 1, 0]) {
    var s = 0.0;
    for (var c = r + 1; c < 3; c++) {
      s += a[r][c] * out[c];
    }
    out[r] = (a[r][3] - s) / a[r][r];
  }
  return out;
}

double _maxTriangle(List<(double, double)> pts) {
  var best = 0.0;
  for (var i = 0; i < pts.length; i++) {
    for (var j = i + 1; j < pts.length; j++) {
      for (var k = j + 1; k < pts.length; k++) {
        final (x1, y1) = pts[i];
        final (x2, y2) = pts[j];
        final (x3, y3) = pts[k];
        best = math.max(
          best,
          ((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)).abs() / 2.0,
        );
      }
    }
  }
  return best;
}

double _sum(Iterable<double> xs) => xs.fold(0.0, (a, b) => a + b);

_Affine _fitAffine(List<(double, double)> src, List<(double, double)> dst) {
  final n = src.length;
  final sx = _sum(src.map((p) => p.$1)) / n;
  final sy = _sum(src.map((p) => p.$2)) / n;
  final tx = _sum(dst.map((p) => p.$1)) / n;
  final ty = _sum(dst.map((p) => p.$2)) / n;
  final u = [for (final p in src) (p.$1 - sx, p.$2 - sy)];
  final w = [for (final p in dst) (p.$1 - tx, p.$2 - ty)];
  final suu = _sum(u.map((p) => p.$1 * p.$1));
  final suv = _sum(u.map((p) => p.$1 * p.$2));
  final svv = _sum(u.map((p) => p.$2 * p.$2));
  final det = suu * svv - suv * suv;
  final scale = math.max(suu, svv);
  if (scale == 0.0 || det.abs() <= 1e-12 * scale * scale) {
    throw GeorefException('the control points are on one line');
  }
  final m = [
    [suu, suv, 0.0],
    [suv, svv, 0.0],
    [0.0, 0.0, n.toDouble()],
  ];
  final rows = <(double, double)>[];
  for (final k in [0, 1]) {
    double q(int i) => k == 0 ? w[i].$1 : w[i].$2;
    var su = 0.0, sv = 0.0;
    for (var i = 0; i < n; i++) {
      su += u[i].$1 * q(i);
    }
    for (var i = 0; i < n; i++) {
      sv += u[i].$2 * q(i);
    }
    final s = _solve3(m, [su, sv, 0.0]);
    rows.add((s[0], s[1]));
  }
  final (a, b) = rows[0];
  final (d, e) = rows[1];
  return _Affine(a, b, tx - a * sx - b * sy, d, e, ty - d * sx - e * sy);
}

double _degNum(Object? v, String name, double lo, double hi) {
  if (!_isNum(v) || (v! as num) < lo || v as num > hi) {
    throw GeorefException('$name: a number from $lo to $hi');
  }
  return v.toDouble();
}

/// A control point: a place on the plan (0-1) and its WGS 84 degrees.
final class ControlPoint {
  const ControlPoint(this.x, this.y, this.lat, this.lon);
  final double x, y, lat, lon;
  Map<String, Object?> toJson() => {'x': x, 'y': y, 'lat': lat, 'lon': lon};
}

/// The API's `points`: 2 to 8 objects {x, y, lat, lon} (georef.py
/// `check_points`).
List<ControlPoint> checkControlPoints(Object? raw) {
  if (raw is! List ||
      raw.length < georefPointsMin ||
      raw.length > georefPointsMax) {
    throw GeorefException(
      'points: $georefPointsMin to $georefPointsMax control points '
      '{x, y, lat, lon}',
    );
  }
  final out = <ControlPoint>[];
  for (var i = 0; i < raw.length; i++) {
    final p = raw[i];
    if (p is! Map ||
        p.length != 4 ||
        !p.keys.toSet().containsAll(['x', 'y', 'lat', 'lon'])) {
      throw GeorefException(
        'points[$i]: an object with exactly x, y, lat and lon',
      );
    }
    out.add(
      ControlPoint(
        _degNum(p['x'], 'points[$i].x', 0, 1),
        _degNum(p['y'], 'points[$i].y', 0, 1),
        _degNum(p['lat'], 'points[$i].lat', -georefMaxLat, georefMaxLat),
        _degNum(p['lon'], 'points[$i].lon', -180, 180),
      ),
    );
  }
  return out;
}

double _dist((double, double) p, (double, double) q) {
  final dx = p.$1 - q.$1, dy = p.$2 - q.$2;
  return math.sqrt(dx * dx + dy * dy);
}

/// A fitted map from plan positions (0-1) to WGS 84 degrees (georef.py
/// `Georef`, the same arithmetic in the same order).
class Georef {
  Georef(List<ControlPoint> points) : points = List.unmodifiable(points) {
    final pts = this.points;
    if (pts.length < georefPointsMin || pts.length > georefPointsMax) {
      throw GeorefException(
        'points: $georefPointsMin to $georefPointsMax control points',
      );
    }
    final lons = [for (final p in pts) p.lon];
    if (lons.reduce(math.max) - lons.reduce(math.min) > 180.0) {
      throw GeorefException(
        'the points cross the 180th meridian (not supported)',
      );
    }
    lat0 = _sum(pts.map((p) => p.lat)) / pts.length;
    lon0 = _sum(lons) / pts.length;
    _kLat = 1.0 * (math.pi / 180.0) * _earthRadiusM;
    _kLon = _kLat * math.cos(lat0 * (math.pi / 180.0));
    final ground = [for (final p in pts) _plane(p.lat, p.lon)];
    final image = [for (final p in pts) (p.x, p.y)];
    for (var i = 0; i < pts.length; i++) {
      for (var j = i + 1; j < pts.length; j++) {
        if (_dist(image[i], image[j]) < _minImageSep) {
          throw GeorefException(
            'points ${i + 1} and ${j + 1} are at almost the same place on '
            'the image',
          );
        }
      }
    }
    if (pts.length == 2) {
      kind = 'corners';
      final (x1, y1) = image[0];
      final (x2, y2) = image[1];
      final (e1, n1) = ground[0];
      final (e2, n2) = ground[1];
      if ((x2 - x1).abs() < _minImageSep || (y2 - y1).abs() < _minImageSep) {
        throw GeorefException(
          'two points must be opposite corners: they differ in x and in y '
          '(or give three points for a rotated image)',
        );
      }
      if ((e2 - e1).abs() < _minGroundSepM ||
          (n2 - n1).abs() < _minGroundSepM) {
        throw GeorefException(
          'two points must differ in latitude and in longitude (or give '
          'three points for a rotated image)',
        );
      }
      final a = (e2 - e1) / (x2 - x1);
      final e = (n2 - n1) / (y2 - y1);
      _affine = _Affine(a, 0.0, e1 - a * x1, 0.0, e, n1 - e * y1);
    } else {
      kind = 'affine';
      if (_maxTriangle(image) < _minImageArea) {
        throw GeorefException(
          'the control points are on one line on the image',
        );
      }
      _affine = _fitAffine(image, ground);
    }
    final det = _affine.det;
    if (det.abs() < _minGroundAreaM2) {
      throw GeorefException(
        'the control points are on one line on the ground (or all at one '
        'place)',
      );
    }
    if (det > 0.0) {
      throw GeorefException(
        "the points make a mirror image: check that each point's latitude "
        'and longitude are not swapped',
      );
    }
    for (final (cx, cy) in const [
      (0.0, 0.0),
      (1.0, 0.0),
      (1.0, 1.0),
      (0.0, 1.0),
    ]) {
      final (east, north) = _affine.apply(cx, cy);
      if (math.sqrt(east * east + north * north) > _maxSpanM) {
        throw GeorefException(
          'the image would cover more than 20 km: check the points',
        );
      }
    }
    if (pts.length >= 3) {
      final sq = <double>[];
      for (var i = 0; i < pts.length; i++) {
        final (ax, ay) = _affine.apply(image[i].$1, image[i].$2);
        final dx = ax - ground[i].$1, dy = ay - ground[i].$2;
        sq.add(dx * dx + dy * dy);
      }
      residualM = math.sqrt(_sum(sq) / sq.length);
      final tl = _affine.apply(0, 0), br = _affine.apply(1, 1);
      final tr = _affine.apply(1, 0), bl = _affine.apply(0, 1);
      final diag = math.max(_dist(tl, br), _dist(tr, bl));
      if (residualM > math.max(_minResidualM, _maxResidual * diag)) {
        throw GeorefException(
          'the points do not fit one flat image (they are '
          '${residualM.toStringAsFixed(0)} m off on average): check them',
        );
      }
    }
  }

  final List<ControlPoint> points;
  late final double lat0;
  late final double lon0;
  late final double _kLat;
  late final double _kLon;
  late final _Affine _affine;

  /// "corners" (two points) or "affine" (three to eight).
  late final String kind;
  double residualM = 0.0;

  (double, double) _plane(double lat, double lon) =>
      ((lon - lon0) * _kLon, (lat - lat0) * _kLat);

  /// A plan position (0-1) as (latitude, longitude) in degrees.
  (double, double) toLatLon(double x, double y) {
    final (east, north) = _affine.apply(x, y);
    final lat = lat0 + north / _kLat;
    var lon = lon0 + east / _kLon;
    if (lon > 180.0) {
      lon -= 360.0;
    } else if (lon < -180.0) {
      lon += 360.0;
    }
    return (lat, lon);
  }

  Map<String, Object?> toApi() {
    Map<String, Object?> corner(double x, double y) {
      final (lat, lon) = toLatLon(x, y);
      return {'lat': lat, 'lon': lon};
    }

    return {
      'points': [for (final p in points) p.toJson()],
      'kind': kind,
      'residual_m': double.parse(residualM.toStringAsFixed(2)),
      'corners': {
        'top_left': corner(0, 0),
        'top_right': corner(1, 0),
        'bottom_right': corner(1, 1),
        'bottom_left': corner(0, 1),
      },
    };
  }
}

// --- levels (field_levels.py) -----------------------------------------------

Map<String, Object?> _defaultLevels() => {
  'enabled': false,
  'count': 1,
  'names': [''],
};

int levelsInUse(Map<String, Object?> meta) =>
    meta['enabled'] == true ? meta['count']! as int : 1;

/// Why [level] cannot be read (or written) now, or null; level 0 always can.
String? checkLevel(Map<String, Object?> meta, int level, {bool write = false}) {
  if (level == 0) return null;
  if (level <= 0 || level >= fieldLevelsMax) {
    return 'level: 0 to ${fieldLevelsMax - 1}';
  }
  if (level >= levelsInUse(meta)) {
    return write
        ? 'turn levels on and set their number first'
        : 'no such level in use';
  }
  return null;
}

/// The GM's `{"enabled", "count"?, "names"?}`, checked (field_levels.py
/// `check`): the new settings.
Map<String, Object?> checkLevels(Object? body, Map<String, Object?> current) {
  if (body is! Map || body['enabled'] is! bool) {
    throw ControllerError(
      'the body is {"enabled": true|false, "count": 2-10, "names": [...]}',
    );
  }
  final unknown = body.keys.toSet().difference({'enabled', 'count', 'names'});
  if (unknown.isNotEmpty) {
    throw ControllerError('unknown fields ${(unknown.toList()..sort())}');
  }
  final enabled = body['enabled']! as bool;
  final curCount = current['count']! as int;
  final count = body.containsKey('count')
      ? body['count']
      : (curCount >= fieldLevelsMin || !enabled ? curCount : fieldLevelsMin);
  final lo = enabled ? fieldLevelsMin : 1;
  if (count is! int || count < lo || count > fieldLevelsMax) {
    throw ControllerError('count: $lo to $fieldLevelsMax levels');
  }
  final names = List<String>.of((current['names']! as List).cast<String>());
  if (body.containsKey('names')) {
    final given = body['names'];
    if (given is! List || given.length > count) {
      throw ControllerError(
        'names: a list of at most $count names, one per level from level 0',
      );
    }
    final checked = [
      for (var i = 0; i < given.length; i++)
        _oneLine(given[i], 'names[$i]', levelNameMax),
    ];
    while (names.length < checked.length) {
      names.add('');
    }
    names.setRange(0, checked.length, checked);
  }
  final padded = [...names, ...List.filled(count, '')].take(count).toList();
  return {'enabled': enabled, 'count': count, 'names': padded};
}

// --- the field grid (field_grid.py) ------------------------------------------

/// Rows (A to Z, then AA to AZ) and columns of a level's grid (MF-83).
const gridRowsMax = 52, gridColsMax = 52;

/// A level's grid when the GM never set one: off, 8 by 8.
const gridDefault = <String, Object?>{'enabled': false, 'rows': 8, 'cols': 8};

int _gridCount(Object? v, String where, int top) {
  if (v is! int || v < 1 || v > top) {
    throw ControllerError('$where: a whole number from 1 to $top');
  }
  return v;
}

/// Row 0 is "A", 25 "Z", 26 "AA", 27 "AB", ... (field_grid.py `row_label`).
String gridRowLabel(int row) {
  var out = '';
  var n = row + 1;
  while (n > 0) {
    final r = (n - 1) % 26;
    n = (n - 1) ~/ 26;
    out = String.fromCharCode(0x41 + r) + out;
  }
  return out;
}

/// The cell of a place on a plan ([x], [y]: fractions of its width and
/// height) as the radio says it, "C4": the row's letters, then the column's
/// number (field_grid.py `cell`). The right and bottom edges are in the last
/// cell; null when the grid is off or the place is not on the plan.
String? gridCell(Map<String, Object?> grid, num x, num y) {
  if (grid['enabled'] != true || !(x >= 0 && x <= 1 && y >= 0 && y <= 1)) {
    return null;
  }
  final rows = grid['rows']! as int;
  final cols = grid['cols']! as int;
  final row = (y * rows).floor() < rows - 1 ? (y * rows).floor() : rows - 1;
  final col = (x * cols).floor() < cols - 1 ? (x * cols).floor() : cols - 1;
  return '${gridRowLabel(row)}${col + 1}';
}

/// The GM's `{"enabled", "rows"?, "cols"?}`, checked (field_grid.py
/// `check`): rows and columns not given stay as [current] has them.
Map<String, Object?> checkGrid(Object? body, Map<String, Object?> current) {
  if (body is! Map || body['enabled'] is! bool) {
    throw ControllerError(
      'the body is {"enabled": true|false, "rows": 1-$gridRowsMax, '
      '"cols": 1-$gridColsMax}',
    );
  }
  final unknown = body.keys.toSet().difference({'enabled', 'rows', 'cols'});
  if (unknown.isNotEmpty) {
    throw ControllerError('unknown fields ${(unknown.toList()..sort())}');
  }
  return {
    'enabled': body['enabled'],
    'rows': _gridCount(
      body.containsKey('rows') ? body['rows'] : current['rows'],
      'rows',
      gridRowsMax,
    ),
    'cols': _gridCount(
      body.containsKey('cols') ? body['cols'] : current['cols'],
      'cols',
      gridColsMax,
    ),
  };
}

// --- map features (map_features.py) -----------------------------------------

const mapFeatureTypes = [
  'safe_zone',
  'respawn',
  'hq',
  'parking',
  'first_aid',
  'objective',
  'other',
  'boundary',
];
const mapFeatureShapes = ['point', 'circle', 'polygon'];
const mapFeatureVisibilities = ['everyone', 'team', 'organisers'];
const mapFeaturesMax = 200;
const _labelMax = 48;
const _noteMax = 200;
const _teamNameMax = 23;
const _radiusMinM = 1.0, _radiusMaxM = 2000.0;
const polygonMin = 3, polygonMax = 12;
const _minArea = 1e-6;
const _featureFields = {
  'level',
  'type',
  'label',
  'shape',
  'x',
  'y',
  'radius_m',
  'points',
  'team',
  'visibility',
  'note',
};

double _fraction(Object? v, String where) {
  if (!_isNum(v) || (v! as num) < 0 || v as num > 1) {
    throw ControllerError(
      '$where: a number from 0 to 1 (fraction of the plan)',
    );
  }
  return v.toDouble();
}

String? _team(Object? v) {
  if (v == null) return null;
  if (v is! String ||
      utf8.encode(v).isEmpty ||
      utf8.encode(v).length > _teamNameMax ||
      v != v.trim() ||
      v.runes.any(_controlChar)) {
    throw ControllerError(
      'team: a team\'s name as games use it (red, blue...), 1-$_teamNameMax '
      'bytes, or null',
    );
  }
  return v;
}

double _area(List<Map<String, double>> pts) {
  final n = pts.length;
  var s = 0.0;
  for (var i = 0; i < n; i++) {
    s +=
        pts[i]['x']! * pts[(i + 1) % n]['y']! -
        pts[(i + 1) % n]['x']! * pts[i]['y']!;
  }
  return s.abs() / 2.0;
}

/// The GM's feature, checked (map_features.py `check`): `{level, type,
/// label, shape, x, y | radius_m | points, team, visibility, note}`.
Map<String, Object?> checkMapFeature(Object? body, Map<String, Object?> meta) {
  if (body is! Map) {
    throw ControllerError(
      'the body is {"type", "shape", "x", "y" | "points", ...}',
    );
  }
  final unknown = body.keys.toSet().difference(_featureFields);
  if (unknown.isNotEmpty) {
    throw ControllerError('unknown fields ${(unknown.toList()..sort())}');
  }
  final level = body.containsKey('level') ? body['level'] : 0;
  if (level is! int) throw ControllerError('level: a level in use, from 0');
  final why = checkLevel(meta, level, write: true);
  if (why != null) throw ControllerError('level: $why');
  final kind = body['type'];
  if (!mapFeatureTypes.contains(kind)) {
    throw ControllerError('type: one of $mapFeatureTypes');
  }
  final label = _oneLine(body['label'], 'label', _labelMax, nullable: true);
  if (kind == 'other' && label.isEmpty) {
    throw ControllerError('label: a feature of type other needs a label');
  }
  final shape = body['shape'];
  if (!mapFeatureShapes.contains(shape)) {
    throw ControllerError('shape: one of $mapFeatureShapes');
  }
  final out = <String, Object?>{
    'level': level,
    'type': kind,
    'label': label,
    'shape': shape,
  };
  if (shape == 'point' || shape == 'circle') {
    if (body.containsKey('points')) {
      throw ControllerError(
        'points: only for a polygon (a $shape has x and y)',
      );
    }
    out['x'] = _fraction(body['x'], 'x');
    out['y'] = _fraction(body['y'], 'y');
  }
  if (shape == 'circle') {
    final r = body['radius_m'];
    if (!_isNum(r) || (r! as num) < _radiusMinM || r as num > _radiusMaxM) {
      throw ControllerError('radius_m: 1 to 2000 metres');
    }
    out['radius_m'] = double.parse(r.toDouble().toStringAsFixed(1));
  } else if (body.containsKey('radius_m')) {
    throw ControllerError('radius_m: only for a circle');
  }
  if (shape == 'polygon') {
    if (body.containsKey('x') || body.containsKey('y')) {
      throw ControllerError('x, y: a polygon has points instead');
    }
    final raw = body['points'];
    if (raw is! List || raw.length < polygonMin || raw.length > polygonMax) {
      throw ControllerError(
        'points: $polygonMin to $polygonMax points {x, y} around the area',
      );
    }
    final pts = <Map<String, double>>[];
    for (var i = 0; i < raw.length; i++) {
      final p = raw[i];
      if (p is! Map ||
          p.length != 2 ||
          !p.containsKey('x') ||
          !p.containsKey('y')) {
        throw ControllerError('points[$i]: an object with exactly x and y');
      }
      pts.add({
        'x': _fraction(p['x'], 'points[$i].x'),
        'y': _fraction(p['y'], 'points[$i].y'),
      });
    }
    if (_area(pts) < _minArea) {
      throw ControllerError(
        'points: the area is empty (the points are on one line or at one '
        'place)',
      );
    }
    out['points'] = pts;
  }
  out['team'] = _team(body['team']);
  if (kind == 'boundary') {
    if (shape != 'polygon') {
      throw ControllerError('shape: the field boundary is an area (polygon)');
    }
    if (out['team'] != null) {
      throw ControllerError('team: the field boundary belongs to no team');
    }
  }
  var vis = body['visibility'];
  vis ??= out['team'] != null ? 'team' : 'everyone'; // MF-4
  if (!mapFeatureVisibilities.contains(vis)) {
    throw ControllerError('visibility: one of $mapFeatureVisibilities');
  }
  if (vis == 'team' && out['team'] == null) {
    throw ControllerError('visibility team: name the team');
  }
  out['visibility'] = vis;
  out['note'] = _oneLine(body['note'], 'note', _noteMax, nullable: true);
  return out;
}

// --- the field from a map (field_map.py) -----------------------------------

const _magic = {
  'image/png': [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a],
  'image/jpeg': [0xff, 0xd8, 0xff],
};
const _b64Max = 4 * ((fieldImageMax + 2) ~/ 3);
const _edgeTolerance = 1e-6;
final _base64 = RegExp(r'^[A-Za-z0-9+/]*={0,2}$');

double _degrees(Object? v, String where, double limit) {
  if (!_isNum(v) || (v! as num) < -limit || v as num > limit) {
    throw ControllerError('$where: degrees from ${-limit} to $limit');
  }
  return v.toDouble();
}

double _round7(double x) => double.parse(x.toStringAsFixed(7));

/// POST .../from-map's body, checked (field_map.py `check`): the content
/// type, the image's bytes, its map position and the boundary (with its
/// level).
({
  String contentType,
  Uint8List data,
  Georef georef,
  Map<String, Object?> boundary,
  Map<String, Object?>? grid,
})
checkFromMap(Object? body, Map<String, Object?> meta, int level) {
  if (body is! Map) {
    throw ControllerError(
      'the body is {"content_type", "image", "bounds", "outline", "label"?, '
      '"grid"?}',
    );
  }
  final unknown = body.keys.toSet().difference({
    'content_type',
    'image',
    'bounds',
    'outline',
    'label',
    'grid',
  });
  if (unknown.isNotEmpty) {
    throw ControllerError('unknown fields ${(unknown.toList()..sort())}');
  }
  final ctype = body['content_type'];
  final magic = _magic[ctype];
  if (ctype is! String || magic == null) {
    throw ControllerError(
      'content_type: one of ${(_magic.keys.toList()..sort())}',
    );
  }
  final raw = body['image'];
  if (raw is! String || raw.isEmpty) {
    throw ControllerError('image: the image, base64');
  }
  if (raw.length > _b64Max) {
    throw ControllerError('image: over $fieldImageMax bytes');
  }
  final Uint8List data;
  if (raw.length % 4 != 0 || !_base64.hasMatch(raw)) {
    throw ControllerError('image: not base64');
  }
  try {
    data = base64.decode(raw);
  } on FormatException {
    throw ControllerError('image: not base64');
  }
  if (data.length > fieldImageMax) {
    throw ControllerError('image: over $fieldImageMax bytes');
  }
  if (data.length < magic.length ||
      [
        for (var i = 0; i < magic.length; i++) data[i] == magic[i],
      ].contains(false)) {
    throw ControllerError('image: not a $ctype image');
  }
  final b = body['bounds'];
  if (b is! Map ||
      b.length != 4 ||
      !b.keys.toSet().containsAll(['north', 'south', 'west', 'east'])) {
    throw ControllerError('bounds: {north, south, west, east} in degrees');
  }
  final north = _degrees(b['north'], 'bounds.north', georefMaxLat);
  final south = _degrees(b['south'], 'bounds.south', georefMaxLat);
  final west = _degrees(b['west'], 'bounds.west', 180);
  final east = _degrees(b['east'], 'bounds.east', 180);
  if (!(north > south) || !(east > west)) {
    throw ControllerError(
      'bounds: north above south and east of west (not across the 180th '
      'meridian)',
    );
  }
  final Georef geo;
  try {
    geo = Georef(
      checkControlPoints([
        {'x': 0, 'y': 0, 'lat': north, 'lon': west},
        {'x': 1, 'y': 1, 'lat': south, 'lon': east},
      ]),
    );
  } on GeorefException catch (e) {
    throw ControllerError('bounds: ${e.message}');
  }
  final outline = body['outline'];
  if (outline is! List ||
      outline.length < polygonMin ||
      outline.length > polygonMax) {
    throw ControllerError(
      'outline: $polygonMin to $polygonMax corners {lat, lon}',
    );
  }
  final plan = <Map<String, Object?>>[];
  for (var i = 0; i < outline.length; i++) {
    final p = outline[i];
    if (p is! Map ||
        p.length != 2 ||
        !p.containsKey('lat') ||
        !p.containsKey('lon')) {
      throw ControllerError('outline[$i]: an object with exactly lat and lon');
    }
    final lat = _degrees(p['lat'], 'outline[$i].lat', georefMaxLat);
    final lon = _degrees(p['lon'], 'outline[$i].lon', 180);
    // The inverse of the two-corner map (MF-24).
    final x = (lon - west) / (east - west);
    final y = (north - lat) / (north - south);
    if (x < -_edgeTolerance ||
        x > 1 + _edgeTolerance ||
        y < -_edgeTolerance ||
        y > 1 + _edgeTolerance) {
      throw ControllerError("outline[$i]: outside the image's bounds");
    }
    plan.add({
      'x': _round7(math.min(1.0, math.max(0.0, x))),
      'y': _round7(math.min(1.0, math.max(0.0, y))),
    });
  }
  final boundary = checkMapFeature({
    'level': level,
    'type': 'boundary',
    'label': body['label'],
    'shape': 'polygon',
    'points': plan,
    'visibility': 'everyone',
  }, meta);
  Map<String, Object?>? grid;
  if (body.containsKey('grid')) {
    try {
      grid = checkGrid(body['grid'], gridDefault);
    } on ControllerError catch (e) {
      throw ControllerError('grid: ${e.message}');
    }
  }
  return (
    contentType: ctype,
    data: data,
    georef: geo,
    boundary: boundary,
    grid: grid,
  );
}

// --- the service --------------------------------------------------------------

/// A map feature or the levels changed: each stream connection gets the
/// features its token may see (api.py FEATURES_CHANGED; the stream's route
/// asks [ControllerField.visibleFeatures]).
const featuresChanged = {'type': 'map_features', '_map_features': true};

/// The field plan of a phone controller (one per engine, [engine.field]).
class ControllerField {
  ControllerField(this.engine, {this.dir}) {
    engine.field = this;
    final d = dir;
    if (d != null) {
      d.createSync(recursive: true);
      // Plans no document names: a crash between a new plan's file and the
      // document, or an old plan whose file was not removed.
      final named = {for (final i in _images.values) (i as Map)['file']};
      for (final f in d.listSync()) {
        if (f is File && !named.contains(f.uri.pathSegments.last)) {
          f.deleteSync();
        }
      }
    }
  }

  final ControllerEngine engine;

  /// Where the plans' bytes are kept (null: in memory).
  final Directory? dir;
  final _memory = <String, Uint8List>{};

  static const _doc = 'field';
  static const _placesDoc = 'field_places';

  Map<String, Object?> get _state =>
      ((engine.store.document(_doc) as Map?) ?? const {})
          .cast<String, Object?>();

  void _save(Map<String, Object?> state) =>
      engine.store.putDocument(_doc, state);

  Map<String, Object?> get _images =>
      ((_state['images'] as Map?) ?? const {}).cast<String, Object?>();

  List<Map<String, Object?>> get _features => [
    for (final f in (_state['features'] as List?) ?? const [])
      (f as Map).cast<String, Object?>(),
  ];

  void _emit(Map<String, Object?> msg) => engine.emit(msg);

  // --- levels ---------------------------------------------------------------

  Map<String, Object?> levelsMeta() {
    final raw = _state['levels'];
    if (raw is! Map) return _defaultLevels();
    return raw.cast<String, Object?>();
  }

  /// GET /api/v1/field/levels.
  Map<String, Object?> levelsView() {
    final meta = levelsMeta();
    final images = _images;
    final count = meta['count']! as int;
    return {
      ...meta,
      'in_use': levelsInUse(meta),
      'levels': [
        for (var level = 0; level < count; level++)
          {
            'level': level,
            'name': (meta['names']! as List)[level],
            'image': _imageInfo(images['$level']),
            'own_georef': _loadGeoref(level) != null,
            'grid': grid(level),
          },
      ],
    };
  }

  // --- the field grid (MF-81 to MF-93) ----------------------------------------

  /// A level's grid: off, 8 by 8, when never set.
  Map<String, Object?> grid(int level) {
    final raw = ((_state['grids'] as Map?) ?? const {})['$level'];
    if (raw is Map) {
      try {
        return checkGrid(raw, gridDefault);
      } on ControllerError {
        // unreadable: the default
      }
    }
    return Map.of(gridDefault);
  }

  /// GET /api/v1/field/grid and .../levels/{n}/grid.
  Map<String, Object?> levelGrid(int level) {
    _levelOr404(level);
    return {'level': level, 'grid': grid(level)};
  }

  /// PUT .../grid: `{"enabled", "rows"?, "cols"?}`.
  Map<String, Object?> putGrid(int level, Object? body) {
    _levelOr404(level, write: true);
    final out = checkGrid(body, grid(level));
    final state = Map<String, Object?>.of(_state);
    state['grids'] = {
      ...((state['grids'] as Map?) ?? const {}).cast<String, Object?>(),
      '$level': out,
    };
    _save(state);
    _emit({'type': 'field_grid', 'level': level, 'grid': out});
    return {'level': level, 'grid': out};
  }

  static Map<String, Object?>? _imageInfo(Object? img) => img is Map
      ? {
          'content_type': img['content_type'],
          'bytes': img['bytes'],
          'updated_at': img['updated_at'],
        }
      : null;

  /// PUT /api/v1/field/levels: levels on or off, their number and names.
  Map<String, Object?> putLevels(Object? body) {
    final meta = checkLevels(body, levelsMeta());
    final count = meta['count']! as int;
    final state = Map<String, Object?>.of(_state);
    final images = Map<String, Object?>.of(_images);
    final georef = Map<String, Object?>.of(
      ((state['georef'] as Map?) ?? const {}).cast<String, Object?>(),
    );
    final features = _features;
    final featured = {for (final f in features) f['level']};
    final grids = Map<String, Object?>.of(
      ((state['grids'] as Map?) ?? const {}).cast<String, Object?>(),
    );
    final removed = <int>[];
    final gone = <String>[];
    for (var level = count; level < fieldLevelsMax; level++) {
      if (level != 0) grids.remove('$level');
      final plan = images.remove('$level');
      if (plan is Map) gone.add(plan['file']! as String);
      final points = level != 0 && georef.remove('$level') != null;
      if (plan != null || points || featured.contains(level)) {
        removed.add(level);
      }
    }
    state
      ..['levels'] = meta
      ..['images'] = images
      ..['georef'] = georef
      ..['grids'] = grids
      ..['features'] = [
        for (final f in features)
          if ((f['level']! as int) < count) f,
      ]
      ..['beacons'] = _beaconsAfterLevels(count);
    _save(state);
    gone.forEach(_dropFile);
    _movePlacesToLevel0(count);
    final out = levelsView();
    _emit({'type': 'field_levels', 'levels': out});
    _emit(featuresChanged);
    return {...out, 'removed': removed};
  }

  /// Why [level] cannot be read: 404; written: 400 (api.py `level_or_404`).
  void _levelOr404(int level, {bool write = false}) {
    final why = checkLevel(levelsMeta(), level, write: write);
    if (why != null) {
      throw write ? ControllerError(why) : ControllerError.notFound(why);
    }
  }

  // --- plans ----------------------------------------------------------------

  Uint8List? _read(String file) {
    final d = dir;
    if (d == null) return _memory[file];
    final f = File('${d.path}/$file');
    return f.existsSync() ? f.readAsBytesSync() : null;
  }

  void _write(String file, Uint8List data) {
    final d = dir;
    if (d == null) {
      _memory[file] = data;
      return;
    }
    final tmp = File('${d.path}/$file.tmp');
    final raf = tmp.openSync(mode: FileMode.write);
    try {
      raf
        ..writeFromSync(data)
        ..flushSync();
    } finally {
      raf.closeSync();
    }
    tmp.renameSync('${d.path}/$file');
  }

  void _dropFile(String file) {
    final d = dir;
    if (d == null) {
      _memory.remove(file);
      return;
    }
    final f = File('${d.path}/$file');
    if (f.existsSync()) f.deleteSync();
  }

  /// A new plan's file (not yet the plan: see [_setImage]).
  (String, Map<String, Object?>) _newImage(String ctype, Uint8List data) {
    final state = _state;
    final serial = ((state['image_serial'] as int?) ?? 0) + 1;
    final file = 'plan-$serial.img';
    _write(file, data);
    return (
      file,
      {
        'content_type': ctype,
        'bytes': data.length,
        'updated_at': engine.wallSeconds(),
        'file': file,
        'serial': serial,
      },
    );
  }

  /// The plan of [level] in [state] becomes [info]; returns the old file.
  static String? _setImage(
    Map<String, Object?> state,
    int level,
    Map<String, Object?> info,
  ) {
    final images = Map<String, Object?>.of(
      ((state['images'] as Map?) ?? const {}).cast<String, Object?>(),
    );
    final old = images['$level'];
    images['$level'] = info;
    state
      ..['images'] = images
      ..['image_serial'] = info['serial'];
    return old is Map ? old['file'] as String? : null;
  }

  Map<String, Object?>? imageInfo(int level) => _imageInfo(_images['$level']);

  /// GET /api/v1/field/info.
  Map<String, Object?> info() => {
    'image': imageInfo(0),
    'levels': levelsView(),
  };

  /// GET .../image: (content type, bytes).
  (String, Uint8List) image(int level) {
    _levelOr404(level);
    final img = _images['$level'];
    final data = img is Map ? _read(img['file']! as String) : null;
    if (img is! Map || data == null) {
      throw ControllerError.notFound(
        level == 0
            ? 'no field image uploaded'
            : 'no plan uploaded for this level',
      );
    }
    return (img['content_type']! as String, data);
  }

  /// PUT .../image with the plan's bytes and content type.
  Map<String, Object?> putImage(
    int level,
    String? contentType,
    Uint8List data,
  ) {
    _levelOr404(level, write: true);
    final ctype = (contentType ?? '').split(';').first.trim().toLowerCase();
    if (!fieldImageTypes.contains(ctype)) {
      throw ControllerError(
        'the field image must be one of ${(fieldImageTypes.toList()..sort())}',
        status: 415,
      );
    }
    if (data.length > fieldImageMax) {
      throw ControllerError(
        'the field image is over $fieldImageMax bytes',
        status: 413,
      );
    }
    if (data.isEmpty) throw ControllerError('empty image');
    final (_, info) = _newImage(ctype, data);
    final state = Map<String, Object?>.of(_state);
    final old = _setImage(state, level, info);
    // The control points were places on the old image (decision M9-4).
    final dropped = _clearGeorefIn(state, level);
    _save(state);
    if (old != null) _dropFile(old);
    _emit({'type': 'field_image', 'level': level});
    if (dropped) {
      _emit({'type': 'field_georef', 'level': level, 'georef': null});
    }
    return {
      'content_type': ctype,
      'bytes': data.length,
      'level': level,
      'georef_cleared': dropped,
    };
  }

  /// DELETE .../image.
  Map<String, Object?> deleteImage(int level) {
    if (level < 0 || level >= fieldLevelsMax) {
      throw ControllerError.notFound('level: 0 to ${fieldLevelsMax - 1}');
    }
    final state = Map<String, Object?>.of(_state);
    final images = Map<String, Object?>.of(_images);
    final old = images.remove('$level');
    state['images'] = images;
    final dropped = _clearGeorefIn(state, level);
    if (old != null || dropped) _save(state);
    if (old is Map) _dropFile(old['file']! as String);
    if (old != null) _emit({'type': 'field_image', 'level': level});
    if (dropped) {
      _emit({'type': 'field_georef', 'level': level, 'georef': null});
    }
    return {'deleted': old != null};
  }

  // --- map positions ----------------------------------------------------------

  Georef? _loadGeoref(int level) {
    final raw = ((_state['georef'] as Map?) ?? const {})['$level'];
    if (raw == null) return null;
    try {
      return Georef(checkControlPoints(raw));
    } on GeorefException {
      return null;
    }
  }

  /// A level's own points, else level 0's (decision ML-6).
  Georef? georefFor(int level) =>
      _loadGeoref(level) ?? (level != 0 ? _loadGeoref(0) : null);

  static bool _clearGeorefIn(Map<String, Object?> state, int level) {
    final g = Map<String, Object?>.of(
      ((state['georef'] as Map?) ?? const {}).cast<String, Object?>(),
    );
    final had = g.remove('$level') != null;
    state['georef'] = g;
    return had;
  }

  /// GET /api/v1/field/georef (level 0's own).
  Map<String, Object?> georef0() => {'georef': _loadGeoref(0)?.toApi()};

  /// GET /api/v1/field/levels/{n}/georef.
  Map<String, Object?> levelGeoref(int level) {
    _levelOr404(level);
    final own = _loadGeoref(level);
    return {'georef': (own ?? georefFor(level))?.toApi(), 'own': own != null};
  }

  /// PUT .../georef: `{"points": [...]}`.
  Map<String, Object?> putGeoref(int level, Object? body) {
    _levelOr404(level, write: true);
    if (_images['$level'] == null) {
      throw ControllerError.conflict(
        'upload the field image first: the points are places on it',
      );
    }
    final spec = body ?? const <String, Object?>{};
    if (spec is! Map) {
      throw ControllerError('the request body must be a JSON object');
    }
    if (spec.length != 1 || !spec.containsKey('points')) {
      throw ControllerError(
        'the body is {"points": [{"x", "y", "lat", "lon"}, ...]}',
      );
    }
    final Georef geo;
    try {
      geo = Georef(checkControlPoints(spec['points']));
    } on GeorefException catch (e) {
      throw ControllerError(e.message);
    }
    final state = Map<String, Object?>.of(_state);
    state['georef'] = {
      ...((state['georef'] as Map?) ?? const {}).cast<String, Object?>(),
      '$level': [for (final p in geo.points) p.toJson()],
    };
    _save(state);
    final out = geo.toApi();
    _emit({'type': 'field_georef', 'level': level, 'georef': out});
    return {'georef': out};
  }

  /// DELETE .../georef.
  Map<String, Object?> deleteGeoref(int level) {
    if (level < 0 || level >= fieldLevelsMax) {
      throw ControllerError.notFound('level: 0 to ${fieldLevelsMax - 1}');
    }
    final state = Map<String, Object?>.of(_state);
    final deleted = _clearGeorefIn(state, level);
    if (deleted) {
      _save(state);
      _emit({'type': 'field_georef', 'level': level, 'georef': null});
    }
    return {'deleted': deleted};
  }

  // --- the field from a map ------------------------------------------------

  /// POST /api/v1/field/levels/{n}/from-map: the plan, its map position
  /// and the boundary, all or nothing (MF-26).
  Map<String, Object?> fromMap(int level, Object? body) {
    _levelOr404(level, write: true);
    final spec = checkFromMap(body, levelsMeta(), level);
    final boundary = Map<String, Object?>.of(spec.boundary)..remove('level');
    final features = _features;
    final existing = _boundaryOf(features, level);
    if (existing == null && features.length >= mapFeaturesMax) {
      throw ControllerError.conflict(
        'the field has $mapFeaturesMax map features: delete one first',
      );
    }
    final (_, info) = _newImage(spec.contentType, spec.data);
    final state = Map<String, Object?>.of(_state);
    final old = _setImage(state, level, info);
    state['georef'] = {
      ...((state['georef'] as Map?) ?? const {}).cast<String, Object?>(),
      '$level': [for (final p in spec.georef.points) p.toJson()],
    };
    final now = engine.wallSeconds();
    late final int fid;
    if (existing == null) {
      fid = (state['next_feature_id'] as int?) ?? 1;
      state['next_feature_id'] = fid + 1;
      features.add({
        'id': fid,
        'level': level,
        'data': boundary,
        'created_at': now,
        'updated_at': now,
      });
    } else {
      fid = existing;
      final i = features.indexWhere((f) => f['id'] == fid);
      features[i] = {...features[i], 'data': boundary, 'updated_at': now};
    }
    state['features'] = features;
    final newGrid = spec.grid;
    if (newGrid != null) {
      state['grids'] = {
        ...((state['grids'] as Map?) ?? const {}).cast<String, Object?>(),
        '$level': newGrid,
      };
    }
    _save(
      state,
    ); // the one write that makes all three (and the grid) the field's
    if (old != null) _dropFile(old);
    final out = spec.georef.toApi();
    _emit({'type': 'field_image', 'level': level});
    _emit({'type': 'field_georef', 'level': level, 'georef': out});
    if (newGrid != null) {
      _emit({'type': 'field_grid', 'level': level, 'grid': newGrid});
    }
    _emit(featuresChanged);
    return {
      'level': level,
      'content_type': spec.contentType,
      'bytes': spec.data.length,
      'georef': out,
      'boundary': _view(_feature(fid)!),
      'boundary_new': existing == null,
      'grid': grid(level),
    };
  }

  // --- map features -----------------------------------------------------------

  static int? _boundaryOf(
    List<Map<String, Object?>> features,
    int level, [
    int? except,
  ]) {
    for (final f in features) {
      if (f['level'] == level &&
          (f['data'] as Map?)?['type'] == 'boundary' &&
          f['id'] != except) {
        return f['id']! as int;
      }
    }
    return null;
  }

  Map<String, Object?>? _feature(int id) {
    for (final f in _features) {
      if (f['id'] == id) return f;
    }
    return null;
  }

  static Map<String, Object?> _view(Map<String, Object?> row) => {
    'id': row['id'],
    ...(row['data']! as Map).cast<String, Object?>(),
    'level': row['level'],
    'updated_at': row['updated_at'],
  };

  Map<String, Object?> _featureOr404(int id) {
    final f = _feature(id);
    if (f == null) throw ControllerError.notFound('no such map feature');
    return f;
  }

  /// The features on levels in use (MF-8).
  List<Map<String, Object?>> featuresInUse() {
    final count = levelsInUse(levelsMeta());
    return [
      for (final f in _features)
        if ((f['level']! as int) < count) _view(f),
    ];
  }

  /// A player token's team name in its game, else null.
  String? _viewerTeam(ApiViewer v) {
    if (v.kind != 'player' || v.team == 0 || v.gameId == null) return null;
    final teams = (engine.store.game(v.gameId!)?['teams'] as List?) ?? const [];
    return v.team >= 1 && v.team <= teams.length
        ? teams[v.team - 1] as String
        : null;
  }

  /// MF-3: staff see every feature, anyone the ones for everyone, a player
  /// their team's too.
  static bool _canSee(ApiViewer v, Map<String, Object?> f, String? team) {
    if (v.isStaff) return true;
    final vis = f['visibility'];
    if (vis == 'everyone') return true;
    return vis == 'team' && team != null && f['team'] == team;
  }

  /// GET /api/v1/field/features, and the stream's `map_features` for [v].
  List<Map<String, Object?>> visibleFeatures(ApiViewer v) {
    final team = _viewerTeam(v);
    return [
      for (final f in featuresInUse())
        if (_canSee(v, f, team)) f,
    ];
  }

  void _oneBoundary(Map<String, Object?> data, [int? except]) {
    if (data['type'] == 'boundary' &&
        _boundaryOf(_features, data['level']! as int, except) != null) {
      throw ControllerError.conflict(
        'this level already has a field boundary: change that one',
      );
    }
  }

  /// POST /api/v1/field/features.
  Map<String, Object?> addFeature(Object? body) {
    final data = checkMapFeature(body, levelsMeta());
    _oneBoundary(data);
    final features = _features;
    if (features.length >= mapFeaturesMax) {
      throw ControllerError.conflict(
        'the field has $mapFeaturesMax map features: delete one first',
      );
    }
    final level = data.remove('level')! as int;
    final state = Map<String, Object?>.of(_state);
    final id = (state['next_feature_id'] as int?) ?? 1;
    final now = engine.wallSeconds();
    state
      ..['next_feature_id'] = id + 1
      ..['features'] = [
        ...features,
        {
          'id': id,
          'level': level,
          'data': data,
          'created_at': now,
          'updated_at': now,
        },
      ];
    _save(state);
    _emit(featuresChanged);
    return _view(_feature(id)!);
  }

  /// PUT /api/v1/field/features/{id}.
  Map<String, Object?> putFeature(int id, Object? body) {
    _featureOr404(id);
    final data = checkMapFeature(body, levelsMeta());
    _oneBoundary(data, id);
    final level = data.remove('level')! as int;
    final state = Map<String, Object?>.of(_state);
    state['features'] = [
      for (final f in _features)
        f['id'] == id
            ? {
                ...f,
                'level': level,
                'data': data,
                'updated_at': engine.wallSeconds(),
              }
            : f,
    ];
    _save(state);
    _emit(featuresChanged);
    return _view(_feature(id)!);
  }

  /// DELETE /api/v1/field/features/{id}.
  Map<String, Object?> deleteFeature(int id) {
    _featureOr404(id);
    final state = Map<String, Object?>.of(_state);
    state['features'] = [
      for (final f in _features)
        if (f['id'] != id) f,
    ];
    _save(state);
    _emit(featuresChanged);
    return {'deleted': true};
  }

  // --- the boxes' places on the plan ----------------------------------------

  Map<String, Object?> get _places =>
      ((engine.store.document(_placesDoc) as Map?) ?? const {})
          .cast<String, Object?>();

  /// GET /api/v1/games/{id}/positions: `{node id: {x, y, level}}`.
  Map<String, Object?> places(int gameId) {
    engine.getGame(gameId); // 404 for an unknown game
    final game = ((_places['$gameId'] as Map?) ?? const {})
        .cast<String, Object?>();
    final ids = game.keys.map(int.parse).toList()..sort();
    return {for (final id in ids) '$id': game['$id']};
  }

  /// PUT /api/v1/games/{id}/positions/{node}: `{x, y, level?}`; without a
  /// level the box stays on its own (decision ML-4).
  Map<String, Object?> putPlace(int gameId, int nodeId, Object? body) {
    engine.getGame(gameId);
    final spec = body ?? const <String, Object?>{};
    if (spec is! Map) {
      throw ControllerError('the request body must be a JSON object');
    }
    if (nodeId < 0 || nodeId > 0xfffe) {
      throw ControllerError('node id: 0-65534');
    }
    final xy = <double>[];
    for (final name in ['x', 'y']) {
      final v = spec[name];
      if (!_isNum(v) || (v! as num) < 0 || v as num > 1) {
        throw ControllerError(
          '$name: a number from 0 to 1 (fraction of the image)',
        );
      }
      xy.add(v.toDouble());
    }
    var level = spec['level'];
    if (level != null) {
      if (level is! int) throw ControllerError('level: a level in use, from 0');
      _levelOr404(level, write: true);
    }
    final all = Map<String, Object?>.of(_places);
    final game = Map<String, Object?>.of(
      ((all['$gameId'] as Map?) ?? const {}).cast<String, Object?>(),
    );
    level ??= ((game['$nodeId'] as Map?)?['level'] as int?) ?? 0;
    game['$nodeId'] = {'x': xy[0], 'y': xy[1], 'level': level};
    all['$gameId'] = game;
    engine.store.putDocument(_placesDoc, all);
    final msg = <String, Object?>{
      'type': 'position',
      'game': gameId,
      'node_id': nodeId,
      'x': xy[0],
      'y': xy[1],
      'level': level,
    };
    _emit(msg);
    return msg;
  }

  void _movePlacesToLevel0(int levelsFrom) {
    final out = <String, Object?>{};
    var changed = false;
    _places.forEach((game, nodes) {
      final moved = <String, Object?>{};
      (nodes! as Map).forEach((node, place) {
        final p = (place as Map).cast<String, Object?>();
        if (((p['level'] as int?) ?? 0) >= levelsFrom) {
          changed = true;
          moved['$node'] = {...p, 'level': 0};
        } else {
          moved['$node'] = p;
        }
      });
      out[game] = moved;
    });
    if (changed) engine.store.putDocument(_placesDoc, out);
  }
}
