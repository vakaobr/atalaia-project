// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Field check-in's logic (lib/checkin/): the CA pinned per field on first
// use and a changed one refused, the field identity made once per field,
// the check-in client against a fake controller, the player's replicas and
// their declaration ids.

import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/checkin/field_identity.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/checkin/my_replicas.dart';
import 'package:atalaia_app/protocol/checkin_poster.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_field.dart';

void main() {
  group('trust', () {
    test('the first scan pins the CA; the next one checks it', () async {
      final field = FakeField();
      final store = MemoryAppStore();
      final trust = FieldTrust(store, fetch: field.fetchCa);
      final poster = parsePoster(field.posterText());
      final pinned = await trust.pin(poster);
      expect(pinned.caSha256, field.sha256Bytes);
      expect(pinned.caPem, field.pem);
      expect(field.caFetches, 1);
      // Kept: the next poster for the field is checked against it, offline.
      field.offline = true;
      final again = await FieldTrust(store, fetch: field.fetchCa).pin(poster);
      expect(again.caShort, poster.caShort);
      expect(field.caFetches, 1);
    });

    test(
      'a poster with another fingerprint is refused with both short forms',
      () async {
        final field = FakeField();
        final trust = FieldTrust(MemoryAppStore(), fetch: field.fetchCa);
        await trust.pin(parsePoster(field.posterText()));
        final other = Uint8List(32)..fillRange(0, 32, 0xab);
        final forged = parsePoster(field.posterText(ca: other));
        await expectLater(
          trust.pin(forged),
          throwsA(
            isA<TrustException>()
                .having((e) => e.reason, 'reason', TrustFailure.changed)
                .having(
                  (e) => e.knownShort,
                  'known',
                  shortFingerprint(field.sha256Bytes),
                )
                .having((e) => e.newShort, 'new', 'ABAB ABAB ABAB ABAB'),
          ),
        );
        await trust.forget(field.fieldId);
        // Only after forgetting the field; then the controller's answer decides.
        await expectLater(
          trust.pin(forged),
          throwsA(
            isA<TrustException>().having(
              (e) => e.reason,
              'reason',
              TrustFailure.mismatch,
            ),
          ),
        );
      },
    );

    test('a controller that sends no certificate is not trusted', () async {
      final trust = FieldTrust(MemoryAppStore(), fetch: (_) async => 'hello');
      await expectLater(
        trust.pin(parsePoster(FakeField().posterText())),
        throwsA(
          isA<TrustException>().having(
            (e) => e.reason,
            'reason',
            TrustFailure.notACertificate,
          ),
        ),
      );
      expect(
        pemToDer(FakeField().pem),
        utf8.encode('atalaia test field CA, DER'),
      );
    });

    test('a bundle with a second certificate is refused (APP-1)', () async {
      final real = FakeField();
      final attacker = FakeField(der: Uint8List.fromList(List.filled(40, 7)));
      for (final bundle in [
        real.pem + attacker.pem, // the real CA first: its hash matches
        attacker.pem + real.pem,
        '${real.pem}-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n',
        'junk\n${real.pem}',
      ]) {
        final store = MemoryAppStore();
        final trust = FieldTrust(store, fetch: (_) async => bundle);
        await expectLater(
          trust.pin(parsePoster(real.posterText())),
          throwsA(isA<TrustException>()),
          reason: bundle,
        );
        expect(await trust.all(), isEmpty);
      }
    });

    test(
      'a pin stored with two certificates is narrowed to the first, '
      'or dropped when that is not the pinned one (APP-1 migration)',
      () async {
        final real = FakeField();
        final attacker = FakeField(der: Uint8List.fromList(List.filled(40, 7)));
        Map<String, Object?> stored(String pem, List<int> sha) => {
          'field_id': real.fieldId,
          'field_name': real.fieldName,
          'ca_pem': pem,
          'ca_sha256': hexEncode(sha),
          'urls': real.urls,
          'wifi_ssid': null,
        };
        final store = MemoryAppStore();
        await store.saveList('trusted_fields', [
          stored(real.pem + attacker.pem, real.sha256Bytes),
        ]);
        var all = await FieldTrust(store, fetch: real.fetchCa).all();
        expect(all.single.caPem, real.pem);
        expect(all.single.caSha256, real.sha256Bytes);
        await store.saveList('trusted_fields', [
          stored(attacker.pem + real.pem, real.sha256Bytes),
        ]);
        all = await FieldTrust(store, fetch: real.fetchCa).all();
        expect(all, isEmpty);
      },
    );

    test('a prop trusts the join payload CA for its game only', () async {
      final field = FakeField();
      final store = MemoryAppStore();
      final trust = FieldTrust(store, fetch: field.fetchCa);
      final f = await trust.forGame(field.urls, field.sha256Bytes);
      expect(f.caPem, field.pem);
      expect(await trust.all(), isEmpty);
      await expectLater(
        trust.forGame(field.urls, Uint8List(32)),
        throwsA(isA<TrustException>()),
      );
    });
  });

  test('a field identity is made once per field', () async {
    final store = MemoryAppStore();
    final ids = FieldIdentities(store);
    final a = await ids.forField('campo-norte');
    final b = await FieldIdentities(store).forField('campo-norte');
    final c = await ids.forField('campo-sul');
    expect((b.playerId, b.secret), (a.playerId, a.secret));
    expect(c.playerId, isNot(a.playerId));
    expect(playerIdOk(a.playerId) && secretOk(a.secret), isTrue);
  });

  group('client', () {
    late FakeField field;
    late CheckinClient client;
    setUp(() {
      field = FakeField();
      client = CheckinClient(
        field.http(
          PinnedField(
            fieldId: field.fieldId,
            fieldName: field.fieldName,
            caPem: field.pem,
            caSha256: field.sha256Bytes,
            urls: field.urls,
          ),
        ),
      );
    });

    test('info, check-in, declaration, refresh, leave', () async {
      final info = await client.info();
      expect(
        (info.fieldName, info.noticeVersion, info.classes.length),
        ('Campo Norte', 1, 4),
      );
      final t = await client.checkIn(
        gameId: 42,
        playerId: 'p-abcdefgh2345',
        secret: newPlayerSecret(),
        displayName: 'Falcão',
        noticeVersion: 1,
      );
      expect((t.status, t.role), ('checked_in', 'player'));
      final decl = await client.putReplicas(t.token, [
        const Declaration(
          declarationId: '6f1d2a3b-4c5d-4e6f-8a9b-0c1d2e3f4a5b',
          type: 'aeg',
          replicaClass: 'rifle',
        ),
      ]);
      expect(decl.single.state, 'pending');
      field.assign(t.playerId, role: 'marshal');
      final t2 = await client.refresh(t.token);
      expect(t2.role, 'marshal');
      await client.leave(t2.token);
      await expectLater(
        client.me(t2.token),
        throwsA(isA<CheckinException>().having((e) => e.status, 'status', 401)),
      );
    });

    test('errors carry the status and the controller text', () async {
      field.notice = 2;
      await expectLater(
        client.checkIn(
          gameId: 42,
          playerId: 'p-abcdefgh2345',
          secret: newPlayerSecret(),
          displayName: 'x',
          noticeVersion: 1,
        ),
        throwsA(
          isA<CheckinException>()
              .having((e) => e.status, 'status', 409)
              .having(
                (e) => e.message,
                'message',
                'notice_version_changed: the privacy notice changed: read it again',
              ),
        ),
      );
      field.offline = true;
      await expectLater(
        client.info(),
        throwsA(
          isA<CheckinException>().having((e) => e.offline, 'offline', isTrue),
        ),
      );
    });
  });

  test(
    "my replicas keep their declaration id in a game and their field's registry id",
    () async {
      final store = CheckinStore(MemoryAppStore());
      final r = MyReplica(
        id: 'r1',
        type: 'aeg',
        replicaClass: 'rifle',
        makeModel: 'TM AK',
      );
      r.replicaIds['campo-norte'] = '0a1b2c3d-4e5f-4a6b-9c7d-8e9f0a1b2c3d';
      await store.saveReplica(r);
      await store.saveReplica(
        MyReplica(id: 'r2', type: 'gbb', replicaClass: 'cqb'),
      );
      final c = FieldCheckin(
        fieldId: 'campo-norte',
        gameId: 42,
        gameName: 'Domingo',
        playerId: 'p-abcdefgh2345',
        token: 't',
        exp: 0,
        status: 'checked_in',
        role: 'player',
      );
      final first = store.declarationsFor(c, ['r1', 'r2']);
      final again = store.declarationsFor(c, ['r1']);
      expect(again.single.declarationId, first.first.declarationId);
      expect(first.first.replicaId, '0a1b2c3d-4e5f-4a6b-9c7d-8e9f0a1b2c3d');
      expect(first.last.replicaId, isNull);
      for (final d in first) {
        expect(declarationProblem(d.toRequest()), isNull);
      }
      await store.saveCheckin(c);
      final loaded = CheckinStore(store.store);
      await loaded.load();
      expect(loaded.latest('campo-norte')!.declarations, c.declarations);
      expect(loaded.replicas.map((x) => x.id), ['r1', 'r2']);
    },
  );
}
