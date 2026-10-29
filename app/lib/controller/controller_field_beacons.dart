// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The indoor BLE beacon registry on the Android field controller (ADR-P3-6,
/// decisions BLE-1 to BLE-9; the Pi's beacons.py, with the same rules,
/// endpoints and stream message; the shared contract cases check both):
///
///     GET|POST /api/v1/beacons               staff the whole registry, anyone
///                                            else each beacon's id and uuid; POST: GM
///     PUT|DELETE /api/v1/beacons/{major:minor}  GM
///
/// A beacon is its uuid, major and minor (its id for a position report is
/// `major:minor`, unique on the field), the room it is in (and an optional
/// zone), the level of the field's plans it is on and, optionally, where it
/// is on that plan (`x`, `y`, fractions 0 to 1). The registry is a list in
/// the field's store document (`beacons`), by major and minor. A level that
/// goes takes its beacons to level 0, unplaced.
part of 'controller_field.dart';

const beaconsMax = 200;

/// The Field Boxes' own major (box_beacons.py): a tag may not use it.
const _boxMajorReserved = 0xB0C5;
const _beaconRoomMax = 48;
const _beaconZoneMax = 48;
const bleIntervalDefaultS = 5;
const bleIntervalMinS = 3;
const bleIntervalMaxS = 30;

final _beaconIdRe = RegExp(r'^[0-9]{1,5}:[0-9]{1,5}$');
final _beaconUuidRe = RegExp(
  r'^[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$',
);

/// The registry changed: every connection is told to read it again, staff
/// for the console and players for their phone's scan (BLE-20; api.py
/// BEACONS_CHANGED). The message carries no data.
const beaconsChanged = {'type': 'beacons', '_beacons': true};

/// `"major:minor"` as numbers, or a [ControllerError].
(int, int) parseBeaconId(Object? id) {
  if (id is! String || !_beaconIdRe.hasMatch(id)) {
    throw ControllerError(
      'beacon id: major:minor, two numbers from 0 to 65535',
    );
  }
  final parts = id.split(':').map(int.parse).toList();
  if (parts[0] > 65535 || parts[1] > 65535) {
    throw ControllerError(
      'beacon id: major:minor, two numbers from 0 to 65535',
    );
  }
  return (parts[0], parts[1]);
}

String beaconId(int major, int minor) => '$major:$minor';

int _id16(Object? v, String where) {
  if (v is! int || v < 0 || v > 65535) {
    throw ControllerError('$where: a whole number from 0 to 65535');
  }
  return v;
}

/// The GM's beacon, checked (beacons.py `check`): `{major, minor, uuid,
/// room, zone, level, x, y}` as stored. With [pathId] (a PUT) a major and
/// minor given must be it.
Map<String, Object?> checkBeacon(
  Object? body,
  Map<String, Object?> meta, [
  String? pathId,
]) {
  if (body is! Map) {
    throw ControllerError(
      'the body is {"uuid", "major", "minor", "room", ...}',
    );
  }
  const fields = {'uuid', 'major', 'minor', 'room', 'zone', 'level', 'x', 'y'};
  final unknown = body.keys.where((k) => !fields.contains(k)).toList()..sort();
  if (unknown.isNotEmpty) throw ControllerError('unknown fields $unknown');
  int major, minor;
  if (pathId != null) {
    (major, minor) = parseBeaconId(pathId);
    for (final (name, want) in [('major', major), ('minor', minor)]) {
      if (body.containsKey(name) && body[name] != want) {
        throw ControllerError(
          "$name: a beacon's major and minor do not change (delete it and "
          'add another)',
        );
      }
    }
  } else {
    major = _id16(body['major'], 'major');
    minor = _id16(body['minor'], 'minor');
  }
  if (major == _boxMajorReserved) {
    throw ControllerError(
      "major: $_boxMajorReserved is the Field Boxes' own (they register "
      'themselves from their place); give a tag another major',
    );
  }
  final level = body.containsKey('level') ? body['level'] : 0;
  if (level is! int) {
    throw ControllerError('level: a level in use, from 0');
  }
  final why = checkLevel(meta, level, write: true);
  if (why != null) throw ControllerError('level: $why');
  final uuid = body['uuid'];
  if (uuid is! String || !_beaconUuidRe.hasMatch(uuid)) {
    throw ControllerError(
      'uuid: the beacon\'s proximity UUID, 8-4-4-4-12 hexadecimal digits',
    );
  }
  final room = _oneLine(body['room'], 'room', _beaconRoomMax, nullable: true);
  if (room.isEmpty) throw ControllerError('room: a name is needed');
  final zone = _oneLine(body['zone'], 'zone', _beaconZoneMax, nullable: true);
  final hasX = body['x'] != null, hasY = body['y'] != null;
  if (hasX != hasY) {
    throw ControllerError(
      'x, y: both, or neither (a beacon not yet placed on the plan)',
    );
  }
  return {
    'major': major,
    'minor': minor,
    'uuid': uuid.toUpperCase(),
    'room': room,
    'zone': zone,
    'level': level,
    'x': hasX ? _fraction(body['x'], 'x') : null,
    'y': hasY ? _fraction(body['y'], 'y') : null,
  };
}

/// How often a phone reports a beacon: the game's `ble_interval_s`, 3 to 30
/// s (ADR-P3-6), else 5.
int bleIntervalS(Map<String, Object?>? game) {
  final params = game?['params'];
  final v = params is Map ? params['ble_interval_s'] : null;
  return v is int && v >= bleIntervalMinS && v <= bleIntervalMaxS
      ? v
      : bleIntervalDefaultS;
}

extension FieldBeacons on ControllerField {
  List<Map<String, Object?>> get _beacons => [
    for (final b in (_state['beacons'] as List?) ?? const [])
      (b as Map).cast<String, Object?>(),
  ];

  void _saveBeacons(List<Map<String, Object?>> rows) {
    final sorted = [...rows]
      ..sort((a, b) {
        final c = (a['major']! as int).compareTo(b['major']! as int);
        return c != 0 ? c : (a['minor']! as int).compareTo(b['minor']! as int);
      });
    _save({..._state, 'beacons': sorted});
  }

  Map<String, Object?>? _beacon(int major, int minor) {
    for (final b in _beacons) {
      if (b['major'] == major && b['minor'] == minor) return b;
    }
    return null;
  }

  static Map<String, Object?> _beaconView(Map<String, Object?> row) {
    final d = (row['data']! as Map).cast<String, Object?>();
    return {
      'id': beaconId(row['major']! as int, row['minor']! as int),
      'uuid': d['uuid'],
      'major': row['major'],
      'minor': row['minor'],
      'room': d['room'],
      'zone': d['zone'] ?? '',
      'level': row['level'],
      'x': d['x'],
      'y': d['y'],
      'updated_at': row['updated_at'],
    };
  }

  Map<String, Object?> _beaconOr404(String id) {
    final (int, int) key;
    try {
      key = parseBeaconId(id);
    } on ControllerError {
      throw ControllerError.notFound('no such beacon');
    }
    final row = _beacon(key.$1, key.$2);
    if (row == null) throw ControllerError.notFound('no such beacon');
    return row;
  }

  /// GET /api/v1/beacons: staff the whole registry, everyone else each
  /// beacon's id and uuid (what a phone listens for). The Field Boxes of the
  /// live game are in it as beacons of their own (controller_box_beacons.dart);
  /// staff also get the field's box-beacon setting.
  Map<String, Object?> beaconsFor(ApiViewer v) {
    final live = engine.liveGame;
    final game = live == null ? null : engine.store.game(live['id']! as int);
    return {
      'beacons': [
        for (final b in _beacons)
          if (v.isStaff)
            _beaconView(b)
          else
            {
              'id': beaconId(b['major']! as int, b['minor']! as int),
              'uuid': (b['data']! as Map)['uuid'],
            },
        if (v.isStaff)
          ...boxBeacons()
        else
          for (final b in registeredBoxBeacons())
            {'id': b['id'], 'uuid': b['uuid']},
      ],
      'ble_interval_s': bleIntervalS(game),
      if (v.isStaff) 'box_beacons': boxBeaconsStatus(),
    };
  }

  /// POST /api/v1/beacons.
  Map<String, Object?> addBeacon(Object? body) {
    final data = checkBeacon(body, levelsMeta());
    final rows = _beacons;
    if (rows.length >= beaconsMax) {
      throw ControllerError.conflict(
        'the field has $beaconsMax beacons: delete one first',
      );
    }
    final major = data.remove('major')! as int;
    final minor = data.remove('minor')! as int;
    final level = data.remove('level')! as int;
    if (_beacon(major, minor) != null) {
      throw ControllerError.conflict(
        'a beacon $major:$minor is already in the registry: change that one',
      );
    }
    final now = engine.wallSeconds();
    _saveBeacons([
      ...rows,
      {
        'major': major,
        'minor': minor,
        'level': level,
        'data': data,
        'created_at': now,
        'updated_at': now,
      },
    ]);
    _emit(beaconsChanged);
    return _beaconView(_beacon(major, minor)!);
  }

  /// PUT /api/v1/beacons/{major:minor}.
  Map<String, Object?> putBeacon(String id, Object? body) {
    _beaconOr404(id);
    final data = checkBeacon(body, levelsMeta(), id);
    final major = data.remove('major')! as int;
    final minor = data.remove('minor')! as int;
    final level = data.remove('level')! as int;
    _saveBeacons([
      for (final b in _beacons)
        b['major'] == major && b['minor'] == minor
            ? {
                ...b,
                'level': level,
                'data': data,
                'updated_at': engine.wallSeconds(),
              }
            : b,
    ]);
    _emit(beaconsChanged);
    return _beaconView(_beacon(major, minor)!);
  }

  /// DELETE /api/v1/beacons/{major:minor}.
  Map<String, Object?> deleteBeacon(String id) {
    final row = _beaconOr404(id);
    _saveBeacons([
      for (final b in _beacons)
        if (b['major'] != row['major'] || b['minor'] != row['minor']) b,
    ]);
    _emit(beaconsChanged);
    return {'deleted': true};
  }

  /// Where a report's beacon puts the player (beacons.py `place_of`):
  /// `{beacon_id, room, level[, zone][, x, y]}`, or null when the beacon is
  /// not in the registry.
  Map<String, Object?>? beaconPlace(String id) {
    final (int, int) key;
    try {
      key = parseBeaconId(id);
    } on ControllerError {
      return null;
    }
    // A Field Box's own beacon (its place on the field view), else a tag.
    if (key.$1 == boxBeaconMajor) return boxBeaconPlace(id);
    final row = _beacon(key.$1, key.$2);
    if (row == null) return null;
    final d = (row['data']! as Map).cast<String, Object?>();
    return {
      'beacon_id': id,
      'room': d['room'],
      'level': row['level'],
      if (d['zone'] is String && (d['zone']! as String).isNotEmpty)
        'zone': d['zone'],
      if (d['x'] != null) ...{'x': d['x'], 'y': d['y']},
    };
  }

  /// Beacons on levels that no longer exist go to level 0, unplaced.
  List<Map<String, Object?>> _beaconsAfterLevels(int levelsFrom) => [
    for (final b in _beacons)
      if ((b['level']! as int) >= levelsFrom)
        {
          ...b,
          'level': 0,
          'data': {
            ...(b['data']! as Map).cast<String, Object?>(),
            'x': null,
            'y': null,
          },
          'updated_at': engine.wallSeconds(),
        }
      else
        b,
  ];
}
