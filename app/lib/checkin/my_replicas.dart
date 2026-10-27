// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// What the app keeps for field check-in (ADR-P3-13), in its private
/// storage: the player's own replicas ("my replicas", prepared before
/// arriving and sent with a check-in), and the check-ins it has made (one
/// per field and game: the player token, the role and team the controller
/// gave). Nothing here leaves the phone except what a check-in sends.
library;

import 'package:flutter/foundation.dart';

import '../chrono/reading.dart' show newUuid;
import '../chrono/replica.dart' show Replica;
import '../storage/app_store.dart';
import 'checkin_client.dart';

/// One of the player's replicas as they describe it; [replicaIds] holds the
/// registry id each field gave it once a marshal registered it there.
final class MyReplica {
  MyReplica({
    required this.id,
    required this.type,
    required this.replicaClass,
    this.makeModel,
    Map<String, String>? replicaIds,
  }) : replicaIds = replicaIds ?? {};

  final String id;
  final String type;
  final String replicaClass;
  final String? makeModel;
  final Map<String, String> replicaIds;

  Map<String, Object?> toJson() => {
    'id': id,
    'type': type,
    'class': replicaClass,
    'make_model': makeModel,
    'replica_ids': replicaIds,
  };

  static MyReplica? fromJson(Map<String, Object?> j) {
    final id = j['id'];
    final type = j['type'];
    final c = j['class'];
    if (id is! String || type is! String || c is! String) return null;
    return MyReplica(
      id: id,
      type: type,
      replicaClass: c,
      makeModel: j['make_model'] as String?,
      replicaIds: {
        for (final e in ((j['replica_ids'] as Map?) ?? const {}).entries)
          '${e.key}': '${e.value}',
      },
    );
  }
}

/// A check-in the app made: the field, the game, the player token.
final class FieldCheckin {
  FieldCheckin({
    required this.fieldId,
    required this.gameId,
    required this.gameName,
    required this.playerId,
    required this.token,
    required this.exp,
    required this.status,
    required this.role,
    this.team,
    this.squad = 0,
    Map<String, String>? declarations,
  }) : declarations = declarations ?? {};

  final String fieldId;
  final int gameId;
  final String gameName;
  final String playerId;
  String token;
  int exp;
  String status;
  String role;
  String? team;
  int squad;

  /// My replica id -> its declaration id in this game.
  final Map<String, String> declarations;

  bool get staff => role == 'marshal' || role == 'gm';

  void update(CheckinTicket t) {
    token = t.token;
    exp = t.exp;
    status = t.status;
    role = t.role;
    team = t.team;
    squad = t.squad;
  }

  Map<String, Object?> toJson() => {
    'field_id': fieldId,
    'game_id': gameId,
    'game_name': gameName,
    'player_id': playerId,
    'token': token,
    'exp': exp,
    'status': status,
    'role': role,
    'team': team,
    'squad': squad,
    'declarations': declarations,
  };

  static FieldCheckin? fromJson(Map<String, Object?> j) {
    try {
      return FieldCheckin(
        fieldId: j['field_id']! as String,
        gameId: j['game_id']! as int,
        gameName: (j['game_name'] as String?) ?? '',
        playerId: j['player_id']! as String,
        token: j['token']! as String,
        exp: j['exp']! as int,
        status: j['status']! as String,
        role: (j['role'] as String?) ?? 'player',
        team: j['team'] as String?,
        squad: (j['squad'] as int?) ?? 0,
        declarations: {
          for (final e in ((j['declarations'] as Map?) ?? const {}).entries)
            '${e.key}': '${e.value}',
        },
      );
    } on Object {
      return null;
    }
  }
}

class CheckinStore extends ChangeNotifier {
  CheckinStore(this.store);
  final AppStore store;

  final replicas = <MyReplica>[];
  final checkins = <FieldCheckin>[];

  Future<void> load() async {
    replicas
      ..clear()
      ..addAll([
        for (final j in await store.loadList('my_replicas'))
          ?MyReplica.fromJson(j),
      ]);
    checkins
      ..clear()
      ..addAll([
        for (final j in await store.loadList('checkins'))
          ?FieldCheckin.fromJson(j),
      ]);
    notifyListeners();
  }

  Future<void> saveReplica(MyReplica r) async {
    replicas.removeWhere((x) => x.id == r.id);
    replicas.add(r);
    await _saveReplicas();
  }

  Future<void> removeReplica(String id) async {
    replicas.removeWhere((x) => x.id == id);
    await _saveReplicas();
  }

  Future<void> _saveReplicas() async {
    await store.saveList('my_replicas', [for (final r in replicas) r.toJson()]);
    notifyListeners();
  }

  /// The latest check-in, at [fieldId] if given.
  FieldCheckin? latest([String? fieldId]) {
    for (final c in checkins.reversed) {
      if (fieldId == null || c.fieldId == fieldId) return c;
    }
    return null;
  }

  Future<void> saveCheckin(FieldCheckin c) async {
    checkins.removeWhere((x) => x.fieldId == c.fieldId && x.gameId == c.gameId);
    checkins.add(c);
    while (checkins.length > 20) {
      checkins.removeAt(0); // older games' tokens are of no use
    }
    await store.saveList('checkins', [for (final x in checkins) x.toJson()]);
    notifyListeners();
  }

  Future<void> removeCheckin(FieldCheckin c) async {
    checkins.remove(c);
    await store.saveList('checkins', [for (final x in checkins) x.toJson()]);
    notifyListeners();
  }

  /// The registry id the field gave each declared replica, kept with "my
  /// replicas" (so a label printed once stays good for the next game).
  Future<void> learnReplicaIds(
    FieldCheckin c,
    List<Declaration> declared,
  ) async {
    var changed = false;
    for (final e in c.declarations.entries) {
      final mine = replicas.where((r) => r.id == e.key).firstOrNull;
      final d = declared.where((d) => d.declarationId == e.value).firstOrNull;
      final rid = d?.replicaId;
      if (mine == null || rid == null || mine.replicaIds[c.fieldId] == rid) {
        continue;
      }
      mine.replicaIds[c.fieldId] = rid;
      changed = true;
    }
    if (changed) await _saveReplicas();
  }

  /// The id whose QR label (`Replica.labelFor`) is [r]'s at [c]'s field: the
  /// one the field gave it, else the id of its declaration for this game
  /// (which a marshal's phone registers it under); null before it was
  /// declared.
  String? labelIdFor(FieldCheckin c, MyReplica r) {
    final known = r.replicaIds[c.fieldId];
    if (known != null && Replica.isId(known)) return known;
    final did = c.declarations[r.id];
    return did != null && Replica.isId(did) ? did : null;
  }

  /// The declarations for [c]'s game from the replicas [picked] (my replica
  /// ids), keeping each one's declaration id across edits.
  List<Declaration> declarationsFor(FieldCheckin c, List<String> picked) {
    final out = <Declaration>[];
    for (final id in picked) {
      final r = replicas.where((x) => x.id == id).firstOrNull;
      if (r == null) continue;
      final did = c.declarations.putIfAbsent(id, newUuid);
      out.add(
        Declaration(
          declarationId: did,
          replicaId: r.replicaIds[c.fieldId],
          type: r.type,
          replicaClass: r.replicaClass,
          makeModel: r.makeModel,
        ),
      );
    }
    return out;
  }
}
