// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// On an Android device or emulator: the real AndroidKeyStore behind the
// secrets at rest (decision PD6, KeystorePlugin.kt). A sealed value is not
// the plain one, opens again, changes if tampered with (read as a lost key,
// never a crash), and a plaintext settings file from an earlier version is
// migrated and its plaintext removed. On iOS the plugin does not exist and the
// store must keep its earlier behaviour; on the host there is no plugin either.

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/platform/channels.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:atalaia_app/storage/secret_vault.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'support.dart';

final _joinKey = '0f' * 32;
final _seed = 'a1' * 32;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  late Directory dir;
  late ChannelSecretVault vault;

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('atalaia-keystore');
    vault = ChannelSecretVault();
  });
  tearDown(() => dir.delete(recursive: true));

  File settingsFile() => File('${dir.path}/settings.json');
  File sealedFile() => File('${dir.path}/secrets.enc');

  AppSettings secrets() => AppSettings()
    ..marshalName = 'Rui'
    ..joinKeyHex = _joinKey
    ..marshalSeedHex = _seed
    ..readToken = 'read-code-1';

  group('on Android', () {
    testWidgets('the Keystore is available, and seals and opens', (_) async {
      expect(await vault.available(), isTrue);
      final plain = Uint8List.fromList(utf8.encode('the join key'));
      final sealed = await vault.seal(plain);
      expect(sealed.length, plain.length + 12 + 16); // nonce + tag
      expect(sealed, isNot(containsAllInOrder(plain)));
      expect(await vault.open(sealed), plain);
      // GCM: a fresh nonce each time
      expect(await vault.seal(plain), isNot(sealed));
    });

    testWidgets('a changed or short sealed value is a lost key', (_) async {
      final sealed = await vault.seal(Uint8List.fromList([1, 2, 3, 4]));
      final bad = Uint8List.fromList(sealed)..[sealed.length - 1] ^= 1;
      for (final data in [bad, Uint8List(5)]) {
        await expectLater(
          vault.open(data),
          throwsA(
            isA<VaultException>().having(
              (e) => e.failure,
              'failure',
              VaultFailure.keyLost,
            ),
          ),
        );
      }
    });

    testWidgets('secrets round trip through the file store', (_) async {
      final store = FileAppStore(dir.path, vault: vault);
      await store.saveSettings(secrets());
      expect(settingsFile().readAsStringSync(), isNot(contains(_joinKey)));
      expect(settingsFile().readAsStringSync(), isNot(contains(_seed)));
      expect(sealedFile().existsSync(), isTrue);
      final back = await FileAppStore(dir.path, vault: vault).loadSettings();
      expect(back.joinKeyHex, _joinKey);
      expect(back.marshalSeedHex, _seed);
      expect(back.readToken, 'read-code-1');
      expect(back.marshalName, 'Rui');
    });

    testWidgets('a plaintext file from an earlier version is migrated', (
      _,
    ) async {
      await settingsFile().writeAsString(jsonEncode(secrets().toJson()));
      final store = FileAppStore(dir.path, vault: vault);
      final got = await store.loadSettings();
      expect(got.joinKeyHex, _joinKey);
      expect(got.marshalSeedHex, _seed);
      expect(got.readToken, 'read-code-1');
      final text = settingsFile().readAsStringSync();
      expect(text, isNot(contains(_joinKey)));
      expect(text, isNot(contains(_seed)));
      expect(text, isNot(contains('read-code-1')));
      expect(sealedFile().existsSync(), isTrue);
      expect(
        (await FileAppStore(dir.path, vault: vault).loadSettings()).joinKeyHex,
        _joinKey,
      );
    });

    testWidgets('data sealed by another key: missing, no crash', (_) async {
      final store = FileAppStore(dir.path, vault: vault);
      await store.saveSettings(secrets());
      // What an app-data restore on another phone leaves: the sealed file the
      // phone's Keystore cannot open.
      final bytes = sealedFile().readAsBytesSync();
      bytes[bytes.length - 3] ^= 0x55;
      sealedFile().writeAsBytesSync(bytes);
      final s = FileAppStore(dir.path, vault: vault);
      final got = await s.loadSettings();
      expect(got.joinKeyHex, isNull);
      expect(got.marshalSeedHex, isNull);
      expect(got.readToken, isNull);
      expect(got.marshalName, 'Rui');
      expect(s.lastVaultFailure, VaultFailure.keyLost);
      expect(sealedFile().existsSync(), isFalse);
      // joining again works
      await s.saveSettings(got..joinKeyHex = _joinKey);
      expect(
        (await FileAppStore(dir.path, vault: vault).loadSettings()).joinKeyHex,
        _joinKey,
      );
    });
  }, skip: !onAndroidDevice);

  group('without the plugin', () {
    testWidgets('the store keeps its earlier behaviour', (_) async {
      expect(await vault.available(), isFalse);
      final store = FileAppStore(dir.path, vault: vault);
      await store.saveSettings(secrets());
      expect(settingsFile().readAsStringSync(), contains(_joinKey));
      expect(sealedFile().existsSync(), isFalse);
      expect((await store.loadSettings()).marshalSeedHex, _seed);
    });
  }, skip: onAndroidDevice);
}
