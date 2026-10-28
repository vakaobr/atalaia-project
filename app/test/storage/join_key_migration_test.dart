// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A marshal's phone does not keep the field join key (decision APX-1): the
// controller signs players' tags, so only a prop (its join card) and the
// phone controller (the field's key holder) still need one. An upgrade drops
// an old marshal's key unless the phone has run the controller.

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter_test/flutter_test.dart';

final _key = 'ab' * 32;

Future<FileAppStore> _store(
  Directory dir,
  Map<String, Object?> settings, {
  bool controller = false,
}) async {
  File('${dir.path}/settings.json').writeAsStringSync(jsonEncode(settings));
  if (controller) Directory('${dir.path}/controller').createSync();
  return FileAppStore(dir.path);
}

Map<String, Object?> _onDisk(Directory dir) =>
    jsonDecode(File('${dir.path}/settings.json').readAsStringSync())
        as Map<String, Object?>;

void main() {
  late Directory dir;
  setUp(() => dir = Directory.systemTemp.createTempSync('atalaia-jk'));
  tearDown(() => dir.deleteSync(recursive: true));

  test('an old marshal phone loses its join key', () async {
    final s = await (await _store(dir, {
      'join_key': _key,
      'marshal_seed': 'cd' * 32,
    })).loadSettings();
    expect(s.joinKeyHex, isNull);
    expect(s.settingsVersion, AppSettings.currentSettingsVersion);
    expect(_onDisk(dir)['join_key'], isNull);
    expect(_onDisk(dir)['settings_version'], 2);
  });

  test('a confirmed marshal (no seed yet) loses it too', () async {
    final s = await (await _store(dir, {
      'join_key': _key,
      'marshal_validation': MarshalValidation(
        marshalId: 'm',
        name: 'Rui',
        fieldId: 'f',
        publicKey: 'k',
        validatedAtMs: 1,
        validUntilMs: 2,
      ).toJson(),
    })).loadSettings();
    expect(s.joinKeyHex, isNull);
  });

  test('a marshal that also ran the phone controller keeps it', () async {
    final s = await (await _store(dir, {
      'join_key': _key,
      'marshal_seed': 'cd' * 32,
    }, controller: true)).loadSettings();
    expect(s.joinKeyHex, _key);
    expect(s.joinKeyUse, AppSettings.joinKeyForController);
  });

  test('a prop phone (not a marshal) keeps it', () async {
    final s = await (await _store(dir, {'join_key': _key})).loadSettings();
    expect(s.joinKeyHex, _key);
    expect(s.joinKeyUse, AppSettings.joinKeyForProp);
  });

  test('the migration runs once: a key typed later stays', () async {
    final store = await _store(dir, {'marshal_seed': 'cd' * 32});
    var s = await store.loadSettings();
    s.joinKeyHex = _key; // as an operator could on the settings screen
    await store.saveSettings(s);
    s = await FileAppStore(dir.path).loadSettings();
    expect(s.joinKeyHex, _key);
  });

  test('a fresh install is already current', () async {
    final s = await FileAppStore(dir.path).loadSettings();
    expect(s.settingsVersion, AppSettings.currentSettingsVersion);
  });
}
