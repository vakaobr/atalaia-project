// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A replica (airsoft gun or paintball marker) in the field's registry
/// (ADR-P3-7), found by the NFC sticker or QR label on it.
library;

import 'reading.dart';

enum ReplicaType { aeg, gbb, hpa, boltAction, dmr, sniper, pistol, shotgun }

/// How a replica is labelled: an NFC sticker (its UID) or a QR label (its text).
enum TagType { nfc, qr }

extension ReplicaTypeWire on ReplicaType {
  /// The type as it is written in the registry (`bolt_action`, ...).
  String get wire => this == ReplicaType.boltAction ? 'bolt_action' : name;

  static ReplicaType? parse(String wire) {
    for (final t in ReplicaType.values) {
      if (t.wire == wire) return t;
    }
    return null;
  }
}

final _id = RegExp(r'^[A-Za-z0-9._:-]{1,64}$');
final _uuid = RegExp(
  r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
);
final _class = RegExp(r'^[a-z0-9_]{1,32}$');
// NFC UIDs are 4, 7 or 10 bytes, written as uppercase hex pairs with colons.
final _nfcUid = RegExp(
  r'^[0-9A-F]{2}(:[0-9A-F]{2}){3}((:[0-9A-F]{2}){3}){0,2}$',
);
final _qrText = RegExp(r'^[\x21-\x7e]{1,64}$');

class Replica {
  Replica({
    required this.replicaId,
    required this.ownerPlayerId,
    required this.type,
    required this.replicaClass,
    this.makeModel,
    required this.registeredAt,
    required this.tagType,
    required this.tagUid,
  }) {
    if (!_uuid.hasMatch(replicaId)) {
      throw ChronoFormatException('replica_id is a lowercase UUID');
    }
    if (!_id.hasMatch(ownerPlayerId)) {
      throw ChronoFormatException('owner_player_id is not a valid id');
    }
    if (!_class.hasMatch(replicaClass)) {
      throw ChronoFormatException(
        'class is 1-32 lowercase letters, digits or _ (a limit template class)',
      );
    }
    final mm = makeModel;
    if (mm != null && (mm.isEmpty || mm.runes.length > 64)) {
      throw ChronoFormatException('make_model is 1-64 characters');
    }
    if (parseTimestamp(registeredAt) == null) {
      throw ChronoFormatException('registered_at is YYYY-MM-DDTHH:MM:SSZ');
    }
    final ok = tagType == TagType.nfc
        ? _nfcUid.hasMatch(tagUid)
        : _qrText.hasMatch(tagUid);
    if (!ok) {
      throw ChronoFormatException(
        tagType == TagType.nfc
            ? 'an NFC tag_uid is 4, 7 or 10 bytes like 04:A2:B3:C4:D5:E6:F7'
            : 'a QR tag_uid is 1-64 printable ASCII characters',
      );
    }
  }

  factory Replica.fromJson(Object? json) {
    if (json is! Map<String, Object?>) {
      throw ChronoFormatException('a replica is a JSON object');
    }
    const fields = {
      'replica_id',
      'owner_player_id',
      'type',
      'class',
      'make_model',
      'registered_at',
      'tag_type',
      'tag_uid',
    };
    final unknown = json.keys.where((k) => !fields.contains(k));
    if (unknown.isNotEmpty) {
      throw ChronoFormatException('unknown fields ${unknown.toList()}');
    }
    String text(String k) {
      final v = json[k];
      if (v is! String) throw ChronoFormatException('$k is a string');
      return v;
    }

    final type = ReplicaTypeWire.parse(text('type'));
    if (type == null) {
      throw ChronoFormatException(
        'type is one of ${ReplicaType.values.map((t) => t.wire).toList()}',
      );
    }
    final tagTypeText = text('tag_type');
    final tagType = TagType.values.where((t) => t.name == tagTypeText);
    if (tagType.isEmpty) throw ChronoFormatException('tag_type is nfc or qr');
    return Replica(
      replicaId: text('replica_id'),
      ownerPlayerId: text('owner_player_id'),
      type: type,
      replicaClass: text('class'),
      makeModel: json.containsKey('make_model') ? text('make_model') : null,
      registeredAt: text('registered_at'),
      tagType: tagType.single,
      tagUid: text('tag_uid'),
    );
  }

  final String replicaId;
  final String ownerPlayerId;
  final ReplicaType type;

  /// The field-defined class (`rifle`, `dmr`, ...) that picks the energy
  /// limit in the field's limit template.
  final String replicaClass;
  final String? makeModel;

  /// `YYYY-MM-DDTHH:MM:SSZ`.
  final String registeredAt;
  final TagType tagType;

  /// The NFC sticker's UID (logged and matched, but it can be cloned: the
  /// reading's signature is what counts) or the QR label's text.
  final String tagUid;

  Map<String, Object> toJson() => {
    'replica_id': replicaId,
    'owner_player_id': ownerPlayerId,
    'type': type.wire,
    'class': replicaClass,
    'make_model': ?makeModel,
    'registered_at': registeredAt,
    'tag_type': tagType.name,
    'tag_uid': tagUid,
  };

  /// Whether [text] is a replica id (a lowercase UUID).
  static bool isId(String text) => _uuid.hasMatch(text);

  /// The QR label text of a replica the app registers itself: `ATL-` and the
  /// first eight characters of its registry id, upper case. A marshal's
  /// phone makes the same text for the same id, so a player's label and the
  /// marshal's registry agree without sending anything.
  static String labelFor(String replicaId) =>
      'ATL-${replicaId.substring(0, 8).toUpperCase()}';

  /// The text a QR label of this replica holds (what the chrono queue's
  /// scanner matches against [tagUid]); null for an NFC tag, which has none.
  String? get labelText => tagType == TagType.qr ? tagUid : null;

  /// [uid] bytes as a registry tag_uid (`04:A2:B3:...`).
  static String nfcUid(List<int> uid) => uid
      .map((b) => (b & 0xff).toRadixString(16).padLeft(2, '0').toUpperCase())
      .join(':');
}
