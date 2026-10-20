// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Who the player is at a field, with no account (ADR-P3-13, decision F3):
/// a `player_id` of `p-` and 12 base32 characters and a 32-byte secret,
/// made on the first check-in at that field and kept in the app's private
/// storage (decision PD6). The controller keeps the id and a hash of the
/// secret, so the same id comes back every game day and nobody else can
/// take it; two fields cannot link a player's ids.
library;

import 'dart:convert';
import 'dart:math';

import '../storage/app_store.dart';

final _playerId = RegExp(r'^p-[a-z2-7]{12}$');
final _secret = RegExp(r'^[A-Za-z0-9_-]{43}$');
const _base32 = 'abcdefghijklmnopqrstuvwxyz234567';

bool playerIdOk(String id) => _playerId.hasMatch(id);

/// A secret in its canonical form: 32 bytes, base64url without padding.
bool secretOk(String s) {
  if (!_secret.hasMatch(s)) return false;
  try {
    final raw = base64Url.decode('$s=');
    return raw.length == 32 && base64Url.encode(raw).replaceAll('=', '') == s;
  } on FormatException {
    return false;
  }
}

String newPlayerId([Random? random]) {
  final r = random ?? Random.secure();
  return 'p-${List.generate(12, (_) => _base32[r.nextInt(32)]).join()}';
}

String newPlayerSecret([Random? random]) {
  final r = random ?? Random.secure();
  return base64Url
      .encode(List<int>.generate(32, (_) => r.nextInt(256)))
      .replaceAll('=', '');
}

final class FieldIdentity {
  const FieldIdentity(this.fieldId, this.playerId, this.secret);
  final String fieldId;
  final String playerId;
  final String secret;

  Map<String, Object?> toJson() => {
    'field_id': fieldId,
    'player_id': playerId,
    'secret': secret,
  };
}

class FieldIdentities {
  FieldIdentities(this.store, {this.random});

  final AppStore store;
  final Random? random;
  static const _list = 'field_identities';

  /// This phone's identity at [fieldId], made once and then reused.
  Future<FieldIdentity> forField(String fieldId) async {
    final all = await store.loadList(_list);
    for (final j in all) {
      final pid = j['player_id'];
      final secret = j['secret'];
      if (j['field_id'] == fieldId &&
          pid is String &&
          secret is String &&
          playerIdOk(pid) &&
          secretOk(secret)) {
        return FieldIdentity(fieldId, pid, secret);
      }
    }
    final id = FieldIdentity(
      fieldId,
      newPlayerId(random),
      newPlayerSecret(random),
    );
    await store.saveList(_list, [
      for (final j in all)
        if (j['field_id'] != fieldId) j,
      id.toJson(),
    ]);
    return id;
  }

  /// Every identity this phone has, one per field controller.
  Future<List<FieldIdentity>> all() async => [
    for (final j in await store.loadList(_list))
      if (j['field_id'] is String &&
          j['player_id'] is String &&
          j['secret'] is String &&
          playerIdOk(j['player_id']! as String) &&
          secretOk(j['secret']! as String))
        FieldIdentity(
          j['field_id']! as String,
          j['player_id']! as String,
          j['secret']! as String,
        ),
  ];

  /// The identity at [fieldId], or null when this phone has none there.
  Future<FieldIdentity?> existing(String fieldId) async =>
      (await all()).where((x) => x.fieldId == fieldId).firstOrNull;

  /// Takes [playerId] (a player id a site server made for the account's
  /// registration) as this phone's id at [fieldId], with a new secret: the
  /// controller keeps that secret's hash at the check-in that presents the
  /// registration's ticket (decision S16-8). Only when the phone has no
  /// identity there yet; otherwise the existing one is returned as it is.
  Future<FieldIdentity> adopt(String fieldId, String playerId) async {
    final have = await existing(fieldId);
    if (have != null) return have;
    if (!playerIdOk(playerId)) throw ArgumentError.value(playerId, 'playerId');
    final id = FieldIdentity(fieldId, playerId, newPlayerSecret(random));
    await store.saveList(_list, [
      for (final j in await store.loadList(_list))
        if (j['field_id'] != fieldId) j,
      id.toJson(),
    ]);
    return id;
  }

  /// Forgets the identity at [fieldId] (the player's choice: a new id next time).
  Future<void> forget(String fieldId) async => store.saveList(_list, [
    for (final j in await store.loadList(_list))
      if (j['field_id'] != fieldId) j,
  ]);
}
