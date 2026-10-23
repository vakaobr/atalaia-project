// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The app's settings and records, as JSON files in the app's private
/// folder (Android's Context.filesDir; other apps cannot read it, and
/// android:allowBackup is off so it is not copied to the cloud). The field
/// join key and the marshal's private key live here too: protected by
/// Android's app sandbox, not by a hardware-backed keystore (decision PD6).
/// Writes go to a temporary file first, then replace the old one. Binary
/// files (a field's logo and wallpaper, team crests: lib/branding/) are
/// kept the same way under `blobs/`.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart' show ThemeMode;

import '../l10n/strings.dart';
import '../security/bytes.dart';

final class AppSettings {
  AppSettings();

  AppLanguage language = AppLanguage.pt;
  ThemeMode theme = ThemeMode.system;

  /// The field join key (64 hex digits), to check join payloads (protocol/join.md).
  String? joinKeyHex;

  /// The admin PIN that guards a prop's pause, end and leave: a salted
  /// SHA-256 of it, never the PIN.
  String? pinHash;
  String? pinSalt;

  /// Kiosk mode (lock task) while a prop game runs.
  bool kiosk = false;

  /// Battery-optimisation exemption asked once (ADR-P3-5: never nag).
  bool batteryAsked = false;

  /// The player view's link to a field controller.
  String? controllerUrl;
  String? readToken;

  /// The GM console's address.
  String? consoleUrl;

  /// The marshal: name and id on records, the Ed25519 seed (64 hex digits).
  String marshalName = '';
  String marshalId = '';
  String? marshalSeedHex;
  String fieldId = 'field';
  String chronoId = 'chrono-1';
  String limitTemplate = 'portugal';

  /// The team the player view highlights.
  String? myTeam;

  /// Field check-in (ADR-P3-13): the name last used, and the version of each
  /// field's privacy notice the player has read (field id -> version).
  String? displayName;
  Map<String, int> noticeSeen = {};

  /// Sharing the phone's position in a game (ADR-P3-6): asked each game,
  /// remembered only as the last answer.
  bool sharePosition = false;

  /// The firmware release keys a phone controller trusts (slice S7c,
  /// decision PE24-96; the Pi's `[firmware] release_keys`): the public
  /// halves, standard base64 of 32 bytes, at most 8.
  List<String> firmwareKeys = [];

  List<int>? get joinKey {
    final h = joinKeyHex;
    if (h == null || !isJoinKeyHex(h)) return null;
    return hexDecode(h);
  }

  bool get hasPin => pinHash != null && pinSalt != null;

  void setPin(String pin, [Random? random]) {
    final r = random ?? Random.secure();
    pinSalt = hexEncode(List<int>.generate(16, (_) => r.nextInt(256)));
    pinHash = _pinHash(pinSalt!, pin);
  }

  void clearPin() => pinHash = pinSalt = null;

  /// Whether [pin] is the admin PIN; with no PIN set, anyone may.
  bool checkPin(String pin) {
    if (!hasPin) return true;
    return constantTimeEquals(
      utf8.encode(_pinHash(pinSalt!, pin)),
      utf8.encode(pinHash!),
    );
  }

  static String _pinHash(String salt, String pin) =>
      sha256.convert(utf8.encode('atalaia-pin:$salt:$pin')).toString();

  Map<String, Object?> toJson() => {
    'language': language.code,
    'theme': theme.name,
    'join_key': joinKeyHex,
    'pin_hash': pinHash,
    'pin_salt': pinSalt,
    'kiosk': kiosk,
    'battery_asked': batteryAsked,
    'controller_url': controllerUrl,
    'read_token': readToken,
    'console_url': consoleUrl,
    'marshal_name': marshalName,
    'marshal_id': marshalId,
    'marshal_seed': marshalSeedHex,
    'field_id': fieldId,
    'chrono_id': chronoId,
    'limit_template': limitTemplate,
    'my_team': myTeam,
    'display_name': displayName,
    'notice_seen': noticeSeen,
    'share_position': sharePosition,
    'firmware_keys': firmwareKeys,
  };

  static AppSettings fromJson(Map<String, Object?> j) {
    String? str(String k) => j[k] is String ? j[k]! as String : null;
    return AppSettings()
      ..language = AppLanguage.fromCode(str('language'))
      ..theme = ThemeMode.values.asNameMap()[str('theme')] ?? ThemeMode.system
      ..joinKeyHex = str('join_key')
      ..pinHash = str('pin_hash')
      ..pinSalt = str('pin_salt')
      ..kiosk = j['kiosk'] == true
      ..batteryAsked = j['battery_asked'] == true
      ..controllerUrl = str('controller_url')
      ..readToken = str('read_token')
      ..consoleUrl = str('console_url')
      ..marshalName = str('marshal_name') ?? ''
      ..marshalId = str('marshal_id') ?? ''
      ..marshalSeedHex = str('marshal_seed')
      ..fieldId = str('field_id') ?? 'field'
      ..chronoId = str('chrono_id') ?? 'chrono-1'
      ..limitTemplate = str('limit_template') ?? 'portugal'
      ..myTeam = str('my_team')
      ..displayName = str('display_name')
      ..noticeSeen = {
        for (final e in ((j['notice_seen'] as Map?) ?? const {}).entries)
          if (e.value is int) '${e.key}': e.value as int,
      }
      ..sharePosition = j['share_position'] == true
      ..firmwareKeys = [
        for (final k in (j['firmware_keys'] as List?) ?? const [])
          if (k is String) k,
      ];
  }
}

bool isJoinKeyHex(String s) => RegExp(r'^[0-9a-fA-F]{64}$').hasMatch(s);

abstract interface class AppStore {
  Future<AppSettings> loadSettings();
  Future<void> saveSettings(AppSettings settings);

  /// A list of JSON records by name (readings, replicas).
  Future<List<Map<String, Object?>>> loadList(String name);
  Future<void> saveList(String name, List<Map<String, Object?>> items);

  /// A binary file by name (letters, digits and dashes), or null.
  Future<Uint8List?> loadBlob(String name);
  Future<void> saveBlob(String name, Uint8List bytes);
  Future<void> deleteBlob(String name);
}

final _blobName = RegExp(r'^[a-z0-9-]{1,100}$');

String _checkBlobName(String name) {
  if (!_blobName.hasMatch(name)) throw ArgumentError.value(name, 'name');
  return name;
}

class FileAppStore implements AppStore {
  FileAppStore(this.dir);

  final String dir;

  File _file(String name) => File('$dir/$name.json');

  Future<Object?> _read(String name) async {
    final f = _file(name);
    if (!await f.exists()) return null;
    try {
      return jsonDecode(await f.readAsString());
    } on FormatException {
      return null; // a damaged file starts over
    }
  }

  Future<void> _write(String name, Object? value) async {
    await Directory(dir).create(recursive: true);
    final tmp = File('$dir/$name.json.tmp');
    await tmp.writeAsString(jsonEncode(value), flush: true);
    await tmp.rename(_file(name).path);
  }

  @override
  Future<AppSettings> loadSettings() async {
    final j = await _read('settings');
    return j is Map<String, Object?> ? AppSettings.fromJson(j) : AppSettings();
  }

  @override
  Future<void> saveSettings(AppSettings settings) =>
      _write('settings', settings.toJson());

  @override
  Future<List<Map<String, Object?>>> loadList(String name) async {
    final j = await _read(name);
    return j is List ? j.whereType<Map<String, Object?>>().toList() : [];
  }

  @override
  Future<void> saveList(String name, List<Map<String, Object?>> items) =>
      _write(name, items);

  File _blob(String name) => File('$dir/blobs/${_checkBlobName(name)}');

  @override
  Future<Uint8List?> loadBlob(String name) async {
    final f = _blob(name);
    return await f.exists() ? f.readAsBytes() : null;
  }

  @override
  Future<void> saveBlob(String name, Uint8List bytes) async {
    final f = _blob(name);
    await f.parent.create(recursive: true);
    final tmp = File('${f.path}.tmp');
    await tmp.writeAsBytes(bytes, flush: true);
    await tmp.rename(f.path);
  }

  @override
  Future<void> deleteBlob(String name) async {
    final f = _blob(name);
    if (await f.exists()) await f.delete();
  }
}

/// Keeps everything in memory (tests, and platforms without a files folder).
class MemoryAppStore implements AppStore {
  MemoryAppStore([AppSettings? settings])
    : _settings = settings?.toJson() ?? AppSettings().toJson();

  Map<String, Object?> _settings;
  final _lists = <String, List<Map<String, Object?>>>{};

  @override
  Future<AppSettings> loadSettings() async => AppSettings.fromJson(_settings);

  @override
  Future<void> saveSettings(AppSettings settings) async =>
      _settings = settings.toJson();

  @override
  Future<List<Map<String, Object?>>> loadList(String name) async => [
    ...?_lists[name],
  ];

  @override
  Future<void> saveList(String name, List<Map<String, Object?>> items) async =>
      _lists[name] = [...items];

  final _blobs = <String, Uint8List>{};

  @override
  Future<Uint8List?> loadBlob(String name) async =>
      _blobs[_checkBlobName(name)];

  @override
  Future<void> saveBlob(String name, Uint8List bytes) async =>
      _blobs[_checkBlobName(name)] = Uint8List.fromList(bytes);

  @override
  Future<void> deleteBlob(String name) async =>
      _blobs.remove(_checkBlobName(name));
}
