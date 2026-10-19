// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The marshal's records on this phone (ADR-P3-7): the replica registry,
/// the chrono readings, each signed with the marshal's Ed25519 key when it
/// is taken (protocol/chrono-record.md), kept for the retention period and
/// erasable per player (lib/chrono/retention.dart). They are sent to the
/// field controller (POST /api/v1/chrono/readings, plan phase E) one series
/// at a time; what has not been sent yet stays here and is sent later.
library;

import 'dart:convert';

import 'package:flutter/foundation.dart';

import '../chrono/limit_template.dart';
import '../chrono/reading.dart';
import '../chrono/record_signer.dart';
import '../chrono/replica.dart';
import '../chrono/retention.dart';
import '../chrono/spot_check.dart';
import '../security/bytes.dart';
import '../storage/app_store.dart';

class MarshalRecords extends ChangeNotifier {
  MarshalRecords(
    this.store,
    this.settings, {
    this.retention,
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now;

  final AppStore store;
  final AppSettings settings;
  final RetentionPolicy? retention;
  final DateTime Function() _now;

  final replicas = <Replica>[];
  final readings = <ChronoReading>[];
  MarshalKey? _key;

  /// The marshal's public key, once there is one.
  Uint8List? get publicKey => _key?.publicKey;

  /// [publicKey] in base64, as the controller registers it.
  String? get publicKeyBase64 =>
      _key == null ? null : base64.encode(publicKey!);

  /// The ids of the readings the controller has stored.
  final uploaded = <String>{};

  /// Replicas registered here for a declaration that had none (replica id ->
  /// declaration id): the next upload of their readings links them.
  final pendingLinks = <String, String>{};

  bool get hasIdentity =>
      _key != null &&
      settings.marshalName.trim().isNotEmpty &&
      settings.marshalId.isNotEmpty;

  Future<void> load() async {
    replicas
      ..clear()
      ..addAll([
        for (final j in await store.loadList('replicas'))
          ?_try(() => Replica.fromJson(j)),
      ]);
    final all = [
      for (final j in await store.loadList('readings'))
        ?_try(() => ChronoReading.fromJson(j)),
    ];
    uploaded
      ..clear()
      ..addAll([
        for (final j in await store.loadList('uploaded_readings'))
          if (j['id'] is String) j['id']! as String,
      ]);
    pendingLinks
      ..clear()
      ..addAll({
        for (final j in await store.loadList('pending_links'))
          if (j['replica_id'] is String && j['declaration_id'] is String)
            j['replica_id']! as String: j['declaration_id']! as String,
      });
    final kept = (retention ?? RetentionPolicy()).keep(all, _now());
    readings
      ..clear()
      ..addAll(kept);
    if (kept.length != all.length) await _saveReadings();
    final seed = settings.marshalSeedHex;
    if (seed != null && seed.length == 64) {
      _key = await MarshalKey.fromSeed(hexDecode(seed));
    }
    notifyListeners();
  }

  static T? _try<T>(T Function() f) {
    try {
      return f();
    } on ChronoFormatException {
      return null;
    }
  }

  /// A new key for this marshal (the old one stops signing).
  Future<void> newKey() async {
    _key = await MarshalKey.generate();
    settings.marshalSeedHex = hexEncode(_key!.seed);
    await store.saveSettings(settings);
    notifyListeners();
  }

  Future<void> addReplica(Replica r) async {
    replicas.removeWhere((x) => x.replicaId == r.replicaId);
    replicas.add(r);
    await store.saveList('replicas', [for (final x in replicas) x.toJson()]);
    notifyListeners();
  }

  /// The replica whose tag (NFC UID or QR label) is [tagUid], if registered.
  Replica? byTag(String tagUid) {
    for (final r in replicas) {
      if (r.tagUid == tagUid) return r;
    }
    return null;
  }

  /// Takes and signs one reading.
  Future<ChronoReading> record({
    required Replica replica,
    required ReadingType type,
    required double velocityMps,
    required double bbWeightG,
    String? refReadingId,
    String? gameId,
  }) async {
    final key = _key;
    if (key == null) throw StateError('the marshal has no key yet');
    final unsigned = ChronoReading.measure(
      replicaId: replica.replicaId,
      playerId: replica.ownerPlayerId,
      type: type,
      velocityMps: velocityMps,
      bbWeightG: bbWeightG,
      chronoId: settings.chronoId,
      marshalId: settings.marshalId,
      marshalName: settings.marshalName.trim(),
      fieldId: settings.fieldId,
      timestamp: _now(),
      refReadingId: refReadingId,
      gameId: gameId,
    );
    final signed = await signReading(unsigned, key);
    readings.add(signed);
    await _saveReadings();
    notifyListeners();
    return signed;
  }

  /// The readings of [replica]'s last check-in or retest: those of its
  /// latest such reading's day.
  List<ChronoReading> lastCheckin(String replicaId) {
    final ins = [
      for (final r in readings)
        if (r.replicaId == replicaId && r.type != ReadingType.spotcheck) r,
    ];
    if (ins.isEmpty) return const [];
    ins.sort((a, b) => a.timestamp.compareTo(b.timestamp));
    final day = ins.last.timestamp.substring(0, 10);
    return [
      for (final r in ins)
        if (r.timestamp.startsWith(day)) r,
    ];
  }

  /// PASS/WARN/FAIL for [series] of [type] against [limit].
  CheckOutcome judge(
    List<ChronoReading> series,
    ReadingType type,
    ClassLimit limit,
  ) => type == ReadingType.spotcheck
      ? spotCheckReadings(
          series,
          limit,
          checkin: lastCheckin(series.first.replicaId),
        )
      : checkInReadings(series, limit);

  Future<void> setPendingLink(String replicaId, String? declarationId) async {
    if (declarationId == null) {
      pendingLinks.remove(replicaId);
    } else {
      pendingLinks[replicaId] = declarationId;
    }
    await store.saveList('pending_links', [
      for (final e in pendingLinks.entries)
        {'replica_id': e.key, 'declaration_id': e.value},
    ]);
  }

  /// The controller stored these readings.
  Future<void> markUploaded(Iterable<String> ids) async {
    uploaded.addAll(ids);
    final keep = {for (final r in readings) r.readingId};
    uploaded.retainWhere(keep.contains);
    await store.saveList('uploaded_readings', [
      for (final id in uploaded) {'id': id},
    ]);
    notifyListeners();
  }

  /// The readings not sent yet, as series: one replica, player and type in a
  /// row, in the order they were taken.
  List<List<ChronoReading>> unsentSeries() {
    final out = <List<ChronoReading>>[];
    for (final r in readings) {
      if (uploaded.contains(r.readingId)) continue;
      final last = out.isEmpty ? null : out.last.last;
      if (last != null &&
          last.replicaId == r.replicaId &&
          last.playerId == r.playerId &&
          last.type == r.type &&
          out.last.length < 50) {
        out.last.add(r);
      } else {
        out.add([r]);
      }
    }
    return out;
  }

  /// Erases every reading of [playerId] (right of erasure).
  Future<void> erasePlayer(String playerId) async {
    final kept = eraseForPlayer(readings, playerId);
    readings
      ..clear()
      ..addAll(kept);
    await _saveReadings();
    notifyListeners();
  }

  Future<void> _saveReadings() =>
      store.saveList('readings', [for (final r in readings) r.toJson()]);
}
