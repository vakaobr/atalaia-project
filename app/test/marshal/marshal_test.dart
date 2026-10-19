// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The marshal's view models: records signed as they are taken and verified
// with the marshal's public key, the last check-in a spot check compares
// with, retention and erasure, the velocity keypad, and player tags that
// read back as written. Plus the app's storage they live in.

import 'dart:io';

import 'package:atalaia_app/chrono/chrono_ui.dart';
import 'package:atalaia_app/chrono/limit_template.dart';
import 'package:atalaia_app/chrono/reading.dart';
import 'package:atalaia_app/chrono/record_signer.dart';
import 'package:atalaia_app/chrono/replica.dart';
import 'package:atalaia_app/chrono/retention.dart';
import 'package:atalaia_app/chrono/spot_check.dart';
import 'package:atalaia_app/marshal/marshal_records.dart';
import 'package:atalaia_app/marshal/tag_writer.dart';
import 'package:atalaia_app/security/ndef.dart';
import 'package:atalaia_app/security/nfc_tag_signer.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter_test/flutter_test.dart';

LimitTemplate portugal() => LimitTemplate.parse(
  File('lib/chrono/limit_templates/portugal.yaml').readAsStringSync(),
);

Replica replica({String owner = 'p-17', String cls = 'rifle'}) => Replica(
  replicaId: newUuid(),
  ownerPlayerId: owner,
  type: ReplicaType.aeg,
  replicaClass: cls,
  makeModel: 'M4',
  registeredAt: '2026-10-19T09:00:00Z',
  tagType: TagType.nfc,
  tagUid: '04:A1:B2:C3',
);

void main() {
  var now = DateTime.utc(2026, 10, 19, 9, 30);

  Future<MarshalRecords> records([AppStore? store]) async {
    final settings = AppSettings()
      ..marshalName = 'Ana Marshal'
      ..marshalId = 'm-1'
      ..fieldId = 'campo-1';
    final r = MarshalRecords(
      store ?? MemoryAppStore(settings),
      settings,
      now: () => now,
    );
    await r.load();
    return r;
  }

  test('no key, no identity; a new key makes one', () async {
    final r = await records();
    expect(r.hasIdentity, isFalse);
    await r.newKey();
    expect(r.hasIdentity, isTrue);
    expect(r.publicKey, hasLength(32));
    expect(r.settings.marshalSeedHex, hasLength(64));
  });

  test('each shot is a signed record the public key verifies', () async {
    final r = await records();
    await r.newKey();
    final rep = replica();
    await r.addReplica(rep);
    final reading = await r.record(
      replica: rep,
      type: ReadingType.checkin,
      velocityMps: 98.765,
      bbWeightG: 0.20,
    );
    expect(reading.velocityMps, 98.77);
    expect(reading.marshalName, 'Ana Marshal');
    expect(reading.fieldId, 'campo-1');
    expect(reading.playerId, 'p-17');
    await verifyReading(reading, r.publicKey!);
    expect(r.byTag('04:A1:B2:C3')!.replicaId, rep.replicaId);
  });

  test('a spot check against the last check-in: PASS, WARN, FAIL', () async {
    final r = await records();
    await r.newKey();
    final rep = replica();
    final limit = portugal().limitFor('rifle')!; // 1.14 J
    final checkin = [
      await r.record(
        replica: rep,
        type: ReadingType.checkin,
        velocityMps: 100,
        bbWeightG: 0.20,
      ), // 1.0 J
    ];
    expect(
      r.judge(checkin, ReadingType.checkin, limit).result,
      CheckResult.pass,
    );
    now = now.add(const Duration(hours: 3));
    Future<CheckResult> spot(double v) async => r
        .judge(
          [
            await r.record(
              replica: rep,
              type: ReadingType.spotcheck,
              velocityMps: v,
              bbWeightG: 0.20,
            ),
          ],
          ReadingType.spotcheck,
          limit,
        )
        .result;
    expect(await spot(101), CheckResult.pass); // 1.02 J, within 5%
    expect(await spot(104), CheckResult.warn); // 1.08 J, over check-in + 5%
    expect(await spot(108), CheckResult.fail); // 1.17 J, over the limit
    expect(
      r.lastCheckin(rep.replicaId).single.readingId,
      checkin.single.readingId,
    );
  });

  test('records survive a restart; old ones go; erasure per player', () async {
    final store = MemoryAppStore();
    var r = await records(store);
    await r.newKey();
    await r.addReplica(replica());
    final a = replica(owner: 'p-1');
    final b = replica(owner: 'p-2');
    await r.record(
      replica: a,
      type: ReadingType.checkin,
      velocityMps: 90,
      bbWeightG: 0.25,
    );
    await r.record(
      replica: b,
      type: ReadingType.checkin,
      velocityMps: 90,
      bbWeightG: 0.25,
    );
    r = await records(store);
    expect(r.readings.length, 2);
    expect(r.replicas.length, 1);
    await r.erasePlayer('p-1');
    expect(r.readings.map((x) => x.playerId), ['p-2']);
    // A year and a day later the reading is past the retention period.
    now = now.add(const Duration(days: RetentionPolicy.defaultDays + 1));
    r = await records(store);
    expect(r.readings, isEmpty);
    expect(await store.loadList('readings'), isEmpty);
  });

  test('the velocity keypad', () {
    final e = VelocityEntry();
    for (final k in ['1', '0', '0', '.', '5', '5', '5']) {
      e.key(k);
    }
    expect(e.text, '100.55');
    expect(e.value, 100.55);
    e
      ..back()
      ..back()
      ..back();
    e.key('.');
    e.key('.');
    expect(e.text, '100.');
    e.clear();
    e.key('.');
    expect(e.text, '0.');
    e
      ..clear()
      ..key('0')
      ..key('7');
    expect(e.text, '7');
    for (final k in ['7', '7', '7', '7']) {
      e.key(k);
    }
    expect(e.text, '7777');
    e.clear();
    expect(e.value, isNull);
  });

  test("a player's tag is one NDEF record that reads back as written", () {
    final key = List<int>.generate(16, (i) => 200 - i);
    const tag = PlayerTag(player: 'b3', team: 2, gameId: 4242);
    final message = playerTagMessage(tag, key, 2);
    final payload = payloadFromNdefMessage(message, tagNdefType)!;
    expect(decodeTag(payload, gameId: 4242, gameKey: key, teamCount: 2), tag);
    expect(
      tagEventData(
        uid: [4, 1],
        payload: payload,
        gameId: 4242,
        gameKey: key,
        teams: const ['red', 'blue'],
      )['team'],
      'blue',
    );
  });

  group('storage', () {
    test('settings and lists in files, written atomically', () async {
      final dir = await Directory.systemTemp.createTemp('atalaia-store');
      addTearDown(() => dir.delete(recursive: true));
      final store = FileAppStore(dir.path);
      final s = await store.loadSettings();
      expect(s.marshalName, '');
      s
        ..marshalName = 'Rui'
        ..joinKeyHex = 'ab' * 32
        ..setPin('2468');
      await store.saveSettings(s);
      await store.saveList('replicas', [replica().toJson()]);
      final back = await store.loadSettings();
      expect(back.marshalName, 'Rui');
      expect(back.joinKey, hasLength(32));
      expect(back.checkPin('2468'), isTrue);
      expect(back.checkPin('1357'), isFalse);
      expect(back.pinHash, isNot(contains('2468')));
      expect((await store.loadList('replicas')).single['class'], 'rifle');
      expect(dir.listSync().where((f) => f.path.endsWith('.tmp')), isEmpty);
      await File('${dir.path}/settings.json').writeAsString('{broken');
      expect((await store.loadSettings()).marshalName, '');
    });

    test('no PIN: anyone; a bad join key is no key', () {
      final s = AppSettings();
      expect(s.checkPin(''), isTrue);
      s.joinKeyHex = 'xyz';
      expect(s.joinKey, isNull);
      expect(isJoinKeyHex('0' * 64), isTrue);
      expect(isJoinKeyHex('0' * 63), isFalse);
    });
  });
}
