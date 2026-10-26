// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The secrets at rest (decision PD6): the join key, the marshal's seed and the
// read code sealed with the Keystore's key. The vault here is a fake (XOR with
// a key byte, a tag in front), the channel a mocked one: the real Keystore
// runs in integration_test/keystore_test.dart on the CI emulator.

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/platform/channels.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:atalaia_app/storage/secret_vault.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeVault implements SecretVault {
  FakeVault({this.present = true});

  bool present;
  int key = 0x5a;
  VaultFailure? failSeal;
  VaultFailure? failOpen;
  int seals = 0;

  @override
  Future<bool> available() async => present;

  @override
  Future<Uint8List> seal(Uint8List plain) async {
    final f = failSeal;
    if (f != null) throw VaultException(f);
    seals++;
    return Uint8List.fromList([key, ...plain.map((b) => b ^ key)]);
  }

  @override
  Future<Uint8List> open(Uint8List sealed) async {
    final f = failOpen;
    if (f != null) throw VaultException(f);
    if (sealed.isEmpty || sealed[0] != key) {
      throw const VaultException(VaultFailure.keyLost, 'bad tag');
    }
    return Uint8List.fromList([for (final b in sealed.skip(1)) b ^ key]);
  }
}

final _joinKey = 'ab' * 32;
final _seed = 'cd' * 32;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Directory dir;
  late FakeVault vault;

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('atalaia-vault');
    vault = FakeVault();
    addTearDown(() => dir.delete(recursive: true));
  });

  FileAppStore store() => FileAppStore(dir.path, vault: vault);
  File settingsFile() => File('${dir.path}/settings.json');
  File sealedFile() => File('${dir.path}/secrets.enc');

  AppSettings withSecrets() => AppSettings()
    ..marshalName = 'Rui'
    ..joinKeyHex = _joinKey
    ..marshalSeedHex = _seed
    ..readToken = 'read-code-1';

  group('sealed at rest', () {
    test('the secrets are in secrets.enc, never in settings.json', () async {
      final s = store();
      await s.saveSettings(withSecrets());
      final plain = settingsFile().readAsStringSync();
      expect(plain, isNot(contains(_joinKey)));
      expect(plain, isNot(contains(_seed)));
      expect(plain, isNot(contains('read-code-1')));
      expect(plain, contains('Rui')); // the rest is as before
      final bytes = sealedFile().readAsBytesSync();
      expect(latin1.decode(bytes), isNot(contains(_joinKey)));
      final back = await store().loadSettings();
      expect(back.joinKeyHex, _joinKey);
      expect(back.marshalSeedHex, _seed);
      expect(back.readToken, 'read-code-1');
      expect(back.marshalName, 'Rui');
      expect(dir.listSync().where((f) => f.path.endsWith('.tmp')), isEmpty);
    });

    test('clearing the secrets removes the sealed file', () async {
      final s = store();
      await s.saveSettings(withSecrets());
      await s.saveSettings(AppSettings()..marshalName = 'Rui');
      expect(sealedFile().existsSync(), isFalse);
      expect((await store().loadSettings()).joinKeyHex, isNull);
    });

    test('an unchanged secret is not sealed again', () async {
      final s = store();
      final cfg = withSecrets();
      await s.saveSettings(cfg);
      await s.saveSettings(cfg..marshalName = 'Ana');
      expect(vault.seals, 1);
    });
  });

  group('migration of a plaintext file', () {
    Future<void> legacy() =>
        settingsFile().writeAsString(jsonEncode(withSecrets().toJson()));

    test('first load seals, then the plaintext is gone', () async {
      await legacy();
      final got = await store().loadSettings();
      expect(got.joinKeyHex, _joinKey);
      expect(got.marshalSeedHex, _seed);
      expect(got.readToken, 'read-code-1');
      final text = settingsFile().readAsStringSync();
      expect(text, isNot(contains(_joinKey)));
      expect(text, isNot(contains(_seed)));
      expect(text, isNot(contains('read-code-1')));
      expect(text, contains('Rui'));
      expect(sealedFile().existsSync(), isTrue);
      // and the next start reads it from the sealed file
      final again = await store().loadSettings();
      expect(again.joinKeyHex, _joinKey);
      expect(again.marshalSeedHex, _seed);
    });

    test('a failing Keystore leaves the plaintext, loses nothing', () async {
      await legacy();
      vault.failSeal = VaultFailure.unavailable;
      final s = store();
      final got = await s.loadSettings();
      expect(got.joinKeyHex, _joinKey);
      expect(settingsFile().readAsStringSync(), contains(_joinKey));
      expect(s.lastVaultFailure, VaultFailure.unavailable);
      vault.failSeal = null; // the next start tries again
      await store().loadSettings();
      expect(settingsFile().readAsStringSync(), isNot(contains(_joinKey)));
      expect(sealedFile().existsSync(), isTrue);
    });
  });

  group('failing safe', () {
    test(
      'a lost key: the secrets are missing, the file goes, no throw',
      () async {
        await store().saveSettings(withSecrets());
        vault.key = 0x11; // another key: a restore on another phone
        final s = store();
        final got = await s.loadSettings();
        expect(got.joinKeyHex, isNull);
        expect(got.marshalSeedHex, isNull);
        expect(got.readToken, isNull);
        expect(got.marshalName, 'Rui'); // the settings stay
        expect(s.lastVaultFailure, VaultFailure.keyLost);
        expect(sealedFile().existsSync(), isFalse);
        // joining again seals under the new key
        await s.saveSettings(got..joinKeyHex = _joinKey);
        expect((await store().loadSettings()).joinKeyHex, _joinKey);
      },
    );

    test('a damaged sealed file reads as lost', () async {
      await store().saveSettings(withSecrets());
      sealedFile().writeAsBytesSync([1, 2, 3]);
      final got = await store().loadSettings();
      expect(got.joinKeyHex, isNull);
      expect(sealedFile().existsSync(), isFalse);
    });

    test('a Keystore that is busy now keeps the file for later', () async {
      await store().saveSettings(withSecrets());
      vault.failOpen = VaultFailure.unavailable;
      final s = store();
      final got = await s.loadSettings();
      expect(got.joinKeyHex, isNull);
      expect(sealedFile().existsSync(), isTrue);
      // saving the settings meanwhile does not wipe the sealed secrets
      await s.saveSettings(got..marshalName = 'Ana');
      expect(sealedFile().existsSync(), isTrue);
      vault.failOpen = null;
      final later = await store().loadSettings();
      expect(later.joinKeyHex, _joinKey);
      expect(later.marshalName, 'Ana');
    });

    test(
      'sealing fails: the secrets never reach the disk in the clear',
      () async {
        final s = store();
        await s.saveSettings(withSecrets());
        vault.failSeal = VaultFailure.unavailable;
        await s.saveSettings(withSecrets()..joinKeyHex = 'ef' * 32);
        expect(settingsFile().readAsStringSync(), isNot(contains('ef' * 32)));
        expect(settingsFile().readAsStringSync(), isNot(contains(_joinKey)));
        expect(sealedFile().existsSync(), isFalse); // stale copy removed
        expect((await store().loadSettings()).joinKeyHex, isNull);
      },
    );

    test('a vault that throws something odd is no vault', () async {
      final s = FileAppStore(dir.path, vault: _Throwing());
      await s.saveSettings(withSecrets());
      expect((await s.loadSettings()).joinKeyHex, _joinKey); // as before
    });
  });

  group('no Keystore (iOS, tests)', () {
    test('without a vault: plaintext, as before', () async {
      final s = FileAppStore(dir.path);
      await s.saveSettings(withSecrets());
      expect(settingsFile().readAsStringSync(), contains(_joinKey));
      expect(sealedFile().existsSync(), isFalse);
      expect((await s.loadSettings()).marshalSeedHex, _seed);
    });

    test('a vault that is not available: plaintext, as before', () async {
      vault.present = false;
      final s = store();
      await s.saveSettings(withSecrets());
      expect(settingsFile().readAsStringSync(), contains(_joinKey));
      expect(sealedFile().existsSync(), isFalse);
      expect((await s.loadSettings()).joinKeyHex, _joinKey);
    });
  });

  group('the channel', () {
    TestDefaultBinaryMessenger messenger() =>
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    const channel = MethodChannel('org.atalaia.app/keystore');

    void answer(Future<Object?> Function(MethodCall) f) {
      messenger().setMockMethodCallHandler(channel, f);
      addTearDown(() => messenger().setMockMethodCallHandler(channel, null));
    }

    test('no plugin: not available, and seal reports unavailable', () async {
      final v = ChannelSecretVault();
      expect(await v.available(), isFalse);
      await expectLater(
        v.seal(Uint8List(1)),
        throwsA(
          isA<VaultException>().having(
            (e) => e.failure,
            'failure',
            VaultFailure.unavailable,
          ),
        ),
      );
    });

    test('data goes out as bytes and comes back', () async {
      MethodCall? seen;
      answer((c) async {
        seen = c;
        return c.method == 'available' ? true : Uint8List.fromList([9, 8, 7]);
      });
      final v = ChannelSecretVault();
      expect(await v.available(), isTrue);
      expect(await v.seal(Uint8List.fromList([1])), [9, 8, 7]);
      expect(seen!.method, 'seal');
      expect((seen!.arguments as Map)['data'], [1]);
    });

    test('key_lost and every other error map to their failure', () async {
      answer((c) async {
        throw PlatformException(
          code: c.method == 'open' ? 'key_lost' : 'unavailable',
        );
      });
      final v = ChannelSecretVault();
      await expectLater(
        v.open(Uint8List(40)),
        throwsA(
          isA<VaultException>().having(
            (e) => e.failure,
            'failure',
            VaultFailure.keyLost,
          ),
        ),
      );
      await expectLater(
        v.seal(Uint8List(1)),
        throwsA(
          isA<VaultException>().having(
            (e) => e.failure,
            'failure',
            VaultFailure.unavailable,
          ),
        ),
      );
      expect(await v.available(), isFalse);
    });
  });
}

class _Throwing implements SecretVault {
  @override
  Future<bool> available() async => throw StateError('boom');

  @override
  Future<Uint8List> seal(Uint8List plain) async => throw StateError('boom');

  @override
  Future<Uint8List> open(Uint8List sealed) async => throw StateError('boom');
}
