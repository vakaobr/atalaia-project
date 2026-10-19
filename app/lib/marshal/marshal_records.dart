// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The marshal's records on this phone (ADR-P3-7): the replica registry,
/// the chrono readings, each signed with the marshal's Ed25519 key when it
/// is taken (protocol/chrono-record.md), kept for the retention period and
/// erasable per player (lib/chrono/retention.dart). Sending them to the
/// field controller is plan phase E.
library;

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
