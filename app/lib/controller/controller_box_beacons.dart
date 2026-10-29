// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The Field Boxes as iBeacons on the Android field controller (decisions
/// BBC-1 to BBC-12, protocol/box-beacon.md; the Pi's box_beacons.py, with the
/// same rules, endpoints and answers; the shared contract case "box beacons"
/// and the vectors in protocol/vectors/box_beacon.json check both):
///
///     PUT /api/v1/box-beacons                GM: the field's switch
///     PUT /api/v1/box-beacons/{node_id}      GM: disable one box, or give it a room
///
/// A box joined to a game advertises a non-connectable iBeacon, and the
/// controller derives each box's beacon from the box itself, so nothing is
/// registered by hand:
///
///  * `uuid`: the field's, `HMAC-SHA256(join key, "atalaia box beacon uuid
///    v1")[:16]` with the version nibble 8 and the RFC 4122 variant;
///  * `major`: [boxBeaconMajor] (45253), which a GM's tag may not use;
///  * `minor`: the box's node id in the game;
///  * `room`: the box's name (the GM's scenario name, else the node's own),
///    or the room the GM gave it; `level`, `x`, `y`: the box's place on the
///    field view (decision ML-4), so a box moved or put on another level
///    moves its beacon. A box the GM has not placed is not registered.
///
/// The beacons belong to the live game and are never stored; the GM's
/// choices are settings: `box_beacons` (`off`: the next join says so, key
/// 19, and the boxes do not advertise), and per game `box_beacons_off:<id>`
/// (the node ids disabled) and `box_beacon_rooms:<id>` (the rooms given).
part of 'controller_field.dart';

/// The Field Boxes' own major: a GM's tag may not use it (beacons.py).
const boxBeaconMajor = 0xB0C5; // 45253
const _boxBeaconLabel = 'atalaia box beacon uuid v1';
const boxBeaconsSetting = 'box_beacons';
const boxBeaconsOffPrefix = 'box_beacons_off:';
const boxBeaconRoomsPrefix = 'box_beacon_rooms:';
const _boxRoomMax = 48;

/// The field's box-beacon UUID from its join key, upper case 8-4-4-4-12.
String deriveBoxBeaconUuid(List<int> joinKey) {
  final mac = Hmac(sha256, joinKey).convert(utf8.encode(_boxBeaconLabel)).bytes;
  final u = Uint8List.fromList(mac.sublist(0, 16));
  u[6] = (u[6] & 0x0f) | 0x80; // version 8: custom
  u[8] = (u[8] & 0x3f) | 0x80; // variant of RFC 4122
  final h = [
    for (final b in u) b.toRadixString(16).padLeft(2, '0'),
  ].join().toUpperCase();
  return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-'
      '${h.substring(16, 20)}-${h.substring(20)}';
}

/// The 30 advertisement bytes a box with [nodeId] sends (what a phone's scan
/// sees): flags, Apple's manufacturer data, the UUID, major, minor, power.
Uint8List boxBeaconAdv(
  List<int> joinKey,
  int nodeId, {
  int measuredPower = -59,
}) {
  final uuid = deriveBoxBeaconUuid(joinKey).replaceAll('-', '');
  return Uint8List.fromList([
    0x02, 0x01, 0x06, 0x1a, 0xff, 0x4c, 0x00, 0x02, 0x15, //
    for (var i = 0; i < 32; i += 2)
      int.parse(uuid.substring(i, i + 2), radix: 16),
    boxBeaconMajor >> 8, boxBeaconMajor & 0xff,
    nodeId >> 8, nodeId & 0xff,
    measuredPower & 0xff,
  ]);
}

String boxBeaconId(int nodeId) => '$boxBeaconMajor:$nodeId';

extension BoxBeacons on ControllerField {
  /// Whether the field's boxes advertise (the GM's setting; on by default).
  bool get boxBeaconsEnabled =>
      engine.store.getSetting(boxBeaconsSetting) != 'off';

  Set<int> _boxesDisabled(int gameId) {
    final raw = engine.store.getSetting('$boxBeaconsOffPrefix$gameId');
    if (raw == null || raw.isEmpty) return {};
    try {
      return {
        for (final n in jsonDecode(raw) as List)
          if (n is int) n,
      };
    } on Object {
      return {};
    }
  }

  Map<int, String> _boxRooms(int gameId) {
    final raw = engine.store.getSetting('$boxBeaconRoomsPrefix$gameId');
    if (raw == null || raw.isEmpty) return {};
    try {
      return {
        for (final e in (jsonDecode(raw) as Map).entries)
          if (int.tryParse('${e.key}') != null && e.value is String)
            int.parse('${e.key}'): e.value as String,
      };
    } on Object {
      return {};
    }
  }

  /// The live game's boxes and their names: the GM's scenario name, else the
  /// node's own (`node-N` until it says HELLO).
  Map<int, String> _boxNodes() {
    final game = engine.liveGame;
    if (game == null) return {};
    final gid = game['id']! as int;
    final scenario = engine.scenarios?.nodeNames(gid) ?? const <int, String>{};
    final names = <int, String>{
      for (final n in engine.nodes(gid))
        n['node_id']! as int: scenario[n['node_id']] ?? '${n['name']}',
    };
    final assigned = (game['assignments'] as Map?) ?? const {};
    for (final k in assigned.keys) {
      final id = int.tryParse('$k');
      if (id != null) names.putIfAbsent(id, () => scenario[id] ?? 'node-$id');
    }
    names.remove(engine.nodeId);
    return names;
  }

  /// Whether [nodeId] is a box of the live game [gameId]: placing it changes
  /// the registry.
  bool isLiveBox(int gameId, int nodeId) =>
      engine.liveGame?['id'] == gameId && _boxNodes().containsKey(nodeId);

  /// Every placed box of the live game as a beacon, enabled or not, by node
  /// id; empty with no live game or no join key.
  List<Map<String, Object?>> boxBeacons() {
    final game = engine.liveGame;
    if (game == null || engine.joinKey.isEmpty) return [];
    final gid = game['id']! as int;
    final uuid = deriveBoxBeaconUuid(engine.joinKey);
    final meta = levelsMeta();
    final inUse = levelsInUse(meta);
    final placed = places(gid);
    final off = _boxesDisabled(gid);
    final given = _boxRooms(gid);
    final nodes = _boxNodes();
    final ids = nodes.keys.toList()..sort();
    return [
      for (final id in ids)
        if (id >= 1 && id <= 0xfffe && placed['$id'] is Map)
          () {
            final pos = (placed['$id']! as Map).cast<String, Object?>();
            final level = pos['level'];
            return <String, Object?>{
              'id': boxBeaconId(id),
              'kind': 'box',
              'uuid': uuid,
              'major': boxBeaconMajor,
              'minor': id,
              'node_id': id,
              'name': nodes[id],
              'room': given[id] ?? nodes[id],
              'room_given': given.containsKey(id),
              'zone': '',
              'level': level is int && level >= 0 && level < inUse ? level : 0,
              'x': pos['x'],
              'y': pos['y'],
              'enabled': !off.contains(id),
              'updated_at': null,
            };
          }(),
    ];
  }

  /// The boxes a phone may be placed by: enabled, with the field's switch on.
  List<Map<String, Object?>> registeredBoxBeacons() => !boxBeaconsEnabled
      ? []
      : [
          for (final b in boxBeacons())
            if (b['enabled'] == true) b,
        ];

  /// The field's box-beacon setting for the console.
  Map<String, Object?> boxBeaconsStatus() => {
    'enabled': boxBeaconsEnabled,
    'major': boxBeaconMajor,
    'uuid': engine.joinKey.isEmpty ? null : deriveBoxBeaconUuid(engine.joinKey),
  };

  /// PUT /api/v1/box-beacons: the field's switch.
  Map<String, Object?> setBoxBeaconsEnabled(Object? body) {
    if (body is! Map || body.length != 1 || !body.containsKey('enabled')) {
      throw ControllerError('the body is {"enabled": true|false}');
    }
    final v = body['enabled'];
    if (v is! bool) throw ControllerError('enabled: true or false');
    engine.store.setSetting(boxBeaconsSetting, v ? 'on' : 'off');
    _emit(beaconsChanged);
    return boxBeaconsStatus();
  }

  /// PUT /api/v1/box-beacons/{node}: `enabled` and/or `room` (a text, or
  /// null for the box's name again).
  Map<String, Object?> updateBoxBeacon(int nodeId, Object? body) {
    final game = engine.liveGame;
    if (game == null) {
      throw ControllerError(
        'no live game: the boxes\' beacons belong to the game',
      );
    }
    if (body is! Map ||
        body.isEmpty ||
        body.keys.any((k) => k != 'enabled' && k != 'room')) {
      throw ControllerError(
        'the body is {"enabled": true|false} and/or {"room": "text"|null}',
      );
    }
    if (!_boxNodes().containsKey(nodeId)) {
      throw ControllerError('node id $nodeId is not a box of this game');
    }
    final gid = game['id']! as int;
    if (body.containsKey('enabled')) {
      final v = body['enabled'];
      if (v is! bool) throw ControllerError('enabled: true or false');
    }
    String? room;
    if (body.containsKey('room') && body['room'] != null) {
      final r = body['room'];
      if (r is! String) throw ControllerError('room: a text');
      room = _oneLine(r, 'room', _boxRoomMax);
    }
    if (body.containsKey('enabled')) {
      final off = _boxesDisabled(gid);
      body['enabled'] == true ? off.remove(nodeId) : off.add(nodeId);
      engine.store.setSetting(
        '$boxBeaconsOffPrefix$gid',
        jsonEncode(off.toList()..sort()),
      );
    }
    if (body.containsKey('room')) {
      final given = _boxRooms(gid);
      room == null || room.isEmpty
          ? given.remove(nodeId)
          : given[nodeId] = room;
      engine.store.setSetting(
        '$boxBeaconRoomsPrefix$gid',
        jsonEncode({for (final e in given.entries) '${e.key}': e.value}),
      );
    }
    _emit(beaconsChanged);
    for (final b in boxBeacons()) {
      if (b['node_id'] == nodeId) return b;
    }
    return {
      'node_id': nodeId,
      'id': boxBeaconId(nodeId),
      'placed': false,
      'enabled': !_boxesDisabled(gid).contains(nodeId),
    };
  }

  /// Where a report of box [id] puts the player, as [beaconPlace] does for a
  /// tag, or null when it is not a registered box.
  Map<String, Object?>? boxBeaconPlace(String id) {
    for (final b in registeredBoxBeacons()) {
      if (b['id'] == id) {
        return {
          'beacon_id': id,
          'room': b['room'],
          'level': b['level'],
          'x': b['x'],
          'y': b['y'],
        };
      }
    }
    return null;
  }
}
