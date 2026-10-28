// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The app's settings and records, as JSON files in the app's private
/// folder (Android's Context.filesDir; other apps cannot read it, and
/// android:allowBackup is off so it is not copied to the cloud). The field
/// join key, the marshal's private key, the read code, the controller's site
/// API key, the player's per-field secrets and the site refresh tokens are not
/// in their JSON files on Android: they are sealed with a key in the
/// AndroidKeyStore (`secrets.enc`, secret_vault.dart, decisions PD6, PKA-4). Where
/// there is no Keystore plugin (iOS) they stay in the file, protected by the
/// app sandbox.
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
import 'secret_vault.dart';

/// What the field controller last told this phone about its marshal id
/// (decisions MR-2 to MR-5): the id and name come from the GM's list, never
/// from the marshal; the phone acts as a marshal only while this is valid,
/// for this key, on this field. Times are milliseconds since the epoch.
final class MarshalValidation {
  const MarshalValidation({
    required this.marshalId,
    required this.name,
    required this.fieldId,
    required this.publicKey,
    required this.validatedAtMs,
    required this.validUntilMs,
  });

  final String marshalId;
  final String name;
  final String fieldId;

  /// The signing key the controller holds for [marshalId], standard base64.
  final String publicKey;
  final int validatedAtMs;
  final int validUntilMs;

  Map<String, Object?> toJson() => {
    'marshal_id': marshalId,
    'name': name,
    'field_id': fieldId,
    'public_key': publicKey,
    'validated_at': validatedAtMs,
    'valid_until': validUntilMs,
  };

  static MarshalValidation? fromJson(Object? raw) {
    if (raw is! Map) return null;
    final j = raw.cast<String, Object?>();
    final id = j['marshal_id'];
    final name = j['name'];
    final field = j['field_id'];
    final key = j['public_key'];
    final at = j['validated_at'];
    final until = j['valid_until'];
    if (id is! String ||
        name is! String ||
        field is! String ||
        key is! String ||
        at is! int ||
        until is! int) {
      return null;
    }
    return MarshalValidation(
      marshalId: id,
      name: name,
      fieldId: field,
      publicKey: key,
      validatedAtMs: at,
      validUntilMs: until,
    );
  }
}

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

  /// The field controller's confirmation that this phone is a marshal on its
  /// list (MR-2); null until one came, and after the GM took the marshal off.
  MarshalValidation? marshalValidation;
  String limitTemplate = 'portugal';

  /// The team the player view highlights.
  String? myTeam;

  /// The player's phone vibrates on key game events (VB-1): a GM message, a
  /// box of the player's team captured or lost, the game starting or ending.
  /// On by default; the squad-orders buzz (SQ-5) and the boundary warning
  /// (MF-33) are not affected.
  bool vibrateOnEvents = true;

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

  /// The phone controller's `[modes]` settings (ModesConfig's JSON: keys,
  /// box_keys, revoked, index; slice S7b of PE24).
  Map<String, Object?> controllerModes = {};

  /// The phone controller's failover (slice S7 of PE24, ADR-P2-8): manual
  /// (the GM promotes a standby) or auto.
  String failoverMode = 'manual';

  /// The phone controller's site server (SyncConfig's JSON: the address,
  /// the field's API key, branding, library, remote GM), or null: no sync.
  /// The key is kept here as the join key is (decisions PD6, PE24-125).
  Map<String, Object?>? controllerSync;

  /// The phone controller's `[atak]` section (AtakConfig.fromSection's
  /// keys), or null: off.
  Map<String, Object?>? controllerAtak;

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
    'marshal_validation': marshalValidation?.toJson(),
    'field_id': fieldId,
    'chrono_id': chronoId,
    'limit_template': limitTemplate,
    'my_team': myTeam,
    'vibrate_on_events': vibrateOnEvents,
    'display_name': displayName,
    'notice_seen': noticeSeen,
    'share_position': sharePosition,
    'firmware_keys': firmwareKeys,
    'controller_modes': controllerModes,
    'failover_mode': failoverMode,
    'controller_sync': controllerSync,
    'controller_atak': controllerAtak,
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
      ..marshalValidation = MarshalValidation.fromJson(j['marshal_validation'])
      ..fieldId = str('field_id') ?? 'field'
      ..chronoId = str('chrono_id') ?? 'chrono-1'
      ..limitTemplate = str('limit_template') ?? 'portugal'
      ..myTeam = str('my_team')
      ..vibrateOnEvents = j['vibrate_on_events'] != false
      ..displayName = str('display_name')
      ..noticeSeen = {
        for (final e in ((j['notice_seen'] as Map?) ?? const {}).entries)
          if (e.value is int) '${e.key}': e.value as int,
      }
      ..sharePosition = j['share_position'] == true
      ..firmwareKeys = [
        for (final k in (j['firmware_keys'] as List?) ?? const [])
          if (k is String) k,
      ]
      ..controllerModes =
          (j['controller_modes'] as Map?)?.cast<String, Object?>() ?? {}
      ..failoverMode = str('failover_mode') == 'auto' ? 'auto' : 'manual'
      ..controllerSync = (j['controller_sync'] as Map?)?.cast<String, Object?>()
      ..controllerAtak = (j['controller_atak'] as Map?)
          ?.cast<String, Object?>();
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

/// The settings keys that are secrets at rest (decision PD6): the field join
/// key, the marshal's Ed25519 seed and the player's read code.
const _secretKeys = ['join_key', 'marshal_seed', 'read_token'];

/// The phone controller's site API key lives inside `controller_sync`; in the
/// sealed file it has a key of its own (decision PKA-4).
const _syncKeyName = 'sync_api_key';

/// The lists with a secret in each record (decision PKA-4): the list name,
/// the field that names the record and the field that is the secret. In the
/// sealed file each is `list.<name>.<record>`.
const _listSecrets = {
  'field_identities': ('field_id', 'secret'),
  'site_accounts': ('site', 'refresh'),
};

bool _sealedKey(String k) =>
    _secretKeys.contains(k) || k == _syncKeyName || k.startsWith('list.');

/// Takes the secrets out of settings [json] (in place) and returns them.
Map<String, Object?> _takeSettingsSecrets(Map<String, Object?> json) {
  final out = <String, Object?>{
    for (final k in _secretKeys)
      if (json.remove(k) case final String v) k: v,
  };
  final sync = json['controller_sync'];
  if (sync is Map && sync['api_key'] is String) {
    out[_syncKeyName] = sync['api_key'];
    json['controller_sync'] = {...sync}..remove('api_key');
  }
  return out;
}

void _putSettingsSecrets(
  Map<String, Object?> json,
  Map<String, Object?> secrets,
) {
  for (final k in _secretKeys) {
    if (secrets[k] case final String v) json[k] = v;
  }
  final key = secrets[_syncKeyName];
  final sync = json['controller_sync'];
  if (key is String && sync is Map)
    json['controller_sync'] = {...sync, 'api_key': key};
}

class FileAppStore implements AppStore {
  /// With a [vault] (Android's Keystore), the secrets in [_secretKeys] are
  /// kept sealed in `secrets.enc`, never in `settings.json`; a plaintext
  /// `settings.json` from an earlier version is migrated on the first load.
  /// Without one, or where it is not available (iOS, tests), they stay in
  /// `settings.json` as before.
  FileAppStore(this.dir, {this.vault});

  final String dir;
  final SecretVault? vault;

  /// Why the vault last failed to give or take the secrets, for the logs and
  /// tests; the app itself just sees the secrets as missing (re-join).
  VaultFailure? lastVaultFailure;

  bool _vaultWorks = false;
  String? _sealedJson; // the secrets the file on disk holds, as sealed last
  bool _unreadable = false; // sealed secrets exist but could not be read now
  Map<String, Object?>? _secrets; // all the sealed secrets, once read
  Future<void> _turn = Future.value();

  File _file(String name) => File('$dir/$name.json');
  File get _sealedFile => File('$dir/secrets.enc');

  Future<Object?> _read(String name) async {
    final f = _file(name);
    if (!await f.exists()) return null;
    try {
      return jsonDecode(await f.readAsString());
    } on FormatException {
      return null; // a damaged file starts over
    }
  }

  Future<void> _writeBytes(File target, List<int> bytes) async {
    await target.parent.create(recursive: true);
    final tmp = File('${target.path}.tmp');
    await tmp.writeAsBytes(bytes, flush: true);
    await tmp.rename(target.path);
  }

  Future<void> _write(String name, Object? value) =>
      _writeBytes(_file(name), utf8.encode(jsonEncode(value)));

  /// One settings read or write at a time: both touch two files.
  Future<T> _serial<T>(Future<T> Function() job) {
    final done = _turn.then((_) => job());
    _turn = done.then<void>((_) {}, onError: (Object _) {});
    return done;
  }

  Future<bool> _vaultReady() async {
    final v = vault;
    if (v == null) return false;
    if (_vaultWorks) return true;
    try {
      return _vaultWorks = await v.available();
    } on Object {
      return false;
    }
  }

  Future<void> _seal(Map<String, Object?> secrets) async {
    final json = jsonEncode(secrets);
    if (json == _sealedJson && await _sealedFile.exists()) return;
    final sealed = await vault!.seal(Uint8List.fromList(utf8.encode(json)));
    await _writeBytes(_sealedFile, sealed);
    _sealedJson = json;
  }

  Future<void> _dropSealed() async {
    _sealedJson = null;
    if (await _sealedFile.exists()) await _sealedFile.delete();
  }

  /// The sealed secrets, or empty if there are none or they cannot be read:
  /// a lost key or a damaged file means they can never be read, so the file
  /// goes and the app asks to join again; a Keystore that did not answer
  /// leaves the file for a later try.
  Future<Map<String, Object?>> _unseal() async {
    try {
      if (!await _sealedFile.exists()) return {};
      final plain = await vault!.open(await _sealedFile.readAsBytes());
      final j = jsonDecode(utf8.decode(plain));
      if (j is Map<String, Object?>) {
        _sealedJson = jsonEncode(j);
        return {
          for (final e in j.entries)
            if (_sealedKey(e.key) && e.value is String) e.key: e.value,
        };
      }
      throw const FormatException('not a map');
    } on VaultException catch (e) {
      lastVaultFailure = e.failure;
      if (e.failure == VaultFailure.keyLost) {
        await _dropSealed().catchError((Object _) {});
      } else {
        _unreadable = true;
      }
    } on FormatException {
      lastVaultFailure = VaultFailure.keyLost;
      await _dropSealed().catchError((Object _) {});
    } on FileSystemException {
      lastVaultFailure = VaultFailure.unavailable;
      _unreadable = true;
    }
    return {};
  }

  @override
  Future<AppSettings> loadSettings() => _serial(() async {
    final j = await _read('settings');
    if (!await _vaultReady()) {
      return j is Map<String, Object?>
          ? AppSettings.fromJson(j)
          : AppSettings();
    }
    final map = j is Map<String, Object?> ? {...j} : <String, Object?>{};
    _unreadable = false;
    final plain = _takeSettingsSecrets(map);
    var secrets = await _unseal();
    if (plain.isNotEmpty) {
      // An earlier version's plaintext: seal it, check it reads back, and only
      // then rewrite settings.json without it. Any failure leaves the
      // plaintext as it was (the secrets are not lost over a Keystore hiccup)
      // and the next start tries again.
      final merged = {...secrets, ...plain};
      try {
        await _seal(merged);
        final back = await vault!.open(await _sealedFile.readAsBytes());
        if (utf8.decode(back) != jsonEncode(merged)) {
          throw const VaultException(VaultFailure.unavailable, 'read-back');
        }
        await _write('settings', map);
        secrets = merged;
      } on VaultException catch (e) {
        lastVaultFailure = e.failure;
        secrets = merged;
        _putSettingsSecrets(map, plain);
        _secrets = secrets;
        return AppSettings.fromJson(map);
      } on FileSystemException {
        lastVaultFailure = VaultFailure.unavailable;
        secrets = merged;
        _putSettingsSecrets(map, plain);
        _secrets = secrets;
        return AppSettings.fromJson(map);
      }
    }
    _secrets = secrets;
    _putSettingsSecrets(map, secrets);
    return AppSettings.fromJson(map);
  });

  @override
  Future<void> saveSettings(AppSettings settings) => _serial(() async {
    final json = settings.toJson();
    if (!await _vaultReady()) return _write('settings', json);
    final own = _takeSettingsSecrets(json);
    await _ensureSecrets();
    await _sealAll({...own, ..._listEntries(_secrets!)});
    await _write('settings', json);
  });

  /// The sealed secrets, read once (and again after a read that failed).
  Future<void> _ensureSecrets() async {
    if (_secrets != null && !_unreadable) return;
    _unreadable = false;
    _secrets = await _unseal();
  }

  Map<String, Object?> _listEntries(Map<String, Object?> all, [String? skip]) =>
      {
        for (final e in all.entries)
          if (e.key.startsWith('list.') &&
              (skip == null || !e.key.startsWith('list.$skip.')))
            e.key: e.value,
      };

  /// Seals [all] (the whole set; nothing in it is kept in the clear) and
  /// remembers it for this run. A failure drops the stale sealed copy: the
  /// secrets stay in memory for this run and the next start asks again.
  Future<void> _sealAll(Map<String, Object?> all) async {
    try {
      if (all.isNotEmpty) {
        await _seal(all);
        _unreadable = false;
      } else if (!_unreadable) {
        await _dropSealed();
      }
    } on VaultException catch (e) {
      lastVaultFailure = e.failure;
      await _dropSealed().catchError((Object _) {});
    } on FileSystemException {
      lastVaultFailure = VaultFailure.unavailable;
    }
    _secrets = all;
  }

  @override
  Future<List<Map<String, Object?>>> loadList(String name) {
    final spec = _listSecrets[name];
    if (spec == null) return _loadPlain(name);
    return _serial(() async {
      final items = await _loadPlain(name);
      if (!await _vaultReady()) return items;
      await _ensureSecrets();
      final (idField, secretField) = spec;
      final all = {..._secrets!};
      var migrate = false;
      final out = <Map<String, Object?>>[];
      for (final item in items) {
        final id = item[idField];
        if (id is! String) {
          out.add(item);
          continue;
        }
        final k = 'list.$name.$id';
        if (item[secretField] is String) {
          all[k] = item[secretField]; // an earlier version's plaintext
          migrate = true;
        } else if (all[k] case final String v) {
          out.add({...item, secretField: v});
          continue;
        }
        out.add(item);
      }
      if (migrate) {
        // Seal first, check, and only then rewrite the list without them; a
        // failure leaves the plaintext for the next start.
        try {
          await _seal(all);
          final back = await vault!.open(await _sealedFile.readAsBytes());
          if (utf8.decode(back) != jsonEncode(all)) {
            throw const VaultException(VaultFailure.unavailable, 'read-back');
          }
          await _write(name, [
            for (final i in out) {...i}..remove(secretField),
          ]);
          _secrets = all;
        } on VaultException catch (e) {
          lastVaultFailure = e.failure;
        } on FileSystemException {
          lastVaultFailure = VaultFailure.unavailable;
        }
      }
      return out;
    });
  }

  Future<List<Map<String, Object?>>> _loadPlain(String name) async {
    final j = await _read(name);
    return j is List ? j.whereType<Map<String, Object?>>().toList() : [];
  }

  @override
  Future<void> saveList(String name, List<Map<String, Object?>> items) {
    final spec = _listSecrets[name];
    if (spec == null) return _write(name, items);
    return _serial(() async {
      if (!await _vaultReady()) return _write(name, items);
      await _ensureSecrets();
      final (idField, secretField) = spec;
      final mine = <String, Object?>{};
      final clean = <Map<String, Object?>>[];
      for (final item in items) {
        final id = item[idField];
        final secret = item[secretField];
        if (id is String && secret is String) {
          mine['list.$name.$id'] = secret;
          clean.add({...item}..remove(secretField));
        } else {
          clean.add(item);
        }
      }
      final rest = {
        for (final e in _secrets!.entries)
          if (!e.key.startsWith('list.$name.')) e.key: e.value,
      };
      // settings secrets first, then the lists' (a stable order: an unchanged
      // set is not sealed again)
      await _sealAll({
        for (final e in rest.entries)
          if (!e.key.startsWith('list.')) e.key: e.value,
        ..._listEntries(rest),
        ...mine,
      });
      await _write(name, clean);
    });
  }

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
