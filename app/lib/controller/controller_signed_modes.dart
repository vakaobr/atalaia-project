// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Signed mode packages on the Android field controller (slice S7b of
/// PE24): the Dart counterpart of the Pi controller's
/// controller/atalaia_controller/signed_modes.py (phase 5 plan phase 6,
/// decisions P5C-17 onwards).
///
/// The GM installs a signed package from the console, by uploading it (the
/// archive and its `.release.json` from tools/mode_package.py) or from the
/// field's registry index (an `https://` URL, or a file on the phone for a
/// field without internet, its packages next to it). Each one is checked
/// with mode_package.dart's [verifyModePackage] against the controller's
/// trusted mode keys and revoked key ids (the settings' and the index's
/// `revoked.json`), fails closed at the first problem, and is then installed
/// through the same checks as an upload ([ControllerModes.install]). The
/// store keeps the archive and its release, so the boxes are sent exactly the
/// signed bytes (controller_mode_fetch.dart).
///
/// The keys, revocations and index are the phone's `[modes]` settings
/// ([ModesConfig], decision PE24-82): the app's settings, given to the
/// controller when it starts, as the Pi reads them from its configuration.
///
/// Revocations fail closed (security review FLD-7, phone parity FU30-9), as on
/// the Pi: with an index set, every install and every upload first fetches the
/// index's `revoked.json` again; a list that is missing, unreadable or
/// malformed refuses the install, and so does a list that cannot be reached
/// for longer than [ModesConfig.revocationMaxAgeDays] (30 by default). A phone
/// with no internet goes on with the last list it fetched (kept in the store,
/// so it survives a restart) until that age; with none yet, or an older one,
/// it installs nothing signed until the index answers (or the field sets no
/// index and keeps [ModesConfig.revoked] itself). [ModesConfig.minVersions] is
/// a floor per mode id: an older version is refused.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import '../modes/mode_catalog.dart';
import 'controller_modes.dart';
import 'mode_package.dart';

/// An index or a revocation list's most bytes (INDEX_MAX).
const indexMaxBytes = 1000000;

/// An index fetched this recently is not fetched again unless asked.
const indexTtlS = 300.0;

/// The store setting that keeps the last revocation list fetched:
/// `{"keys": {id: reason}, "fetched_at"}` (the Pi's `REVOCATIONS_SETTING`).
const revocationsSetting = 'modes.revocations';

const _dayS = 86400.0;

/// The project's registry keys (docs/community/keys.md): root
/// d9521a79030ce544, held offline, and CI 7275108d2e3fe583. The default of
/// the boxes' firmware keys, so the default of [ModesConfig.boxKeys], as on
/// the Pi (`PROJECT_MODE_KEYS` in config.py).
const projectModeKeys = [
  'I+m3rO++TcVNhvDHzI28pkNA8UGoTJSi84IWQguq4Mo=',
  '0nMp0OGboGJZUMsbc/ykqkxQFNdmI/a2k4nQ6YsdTIY=',
];

/// The Pi's `[modes]` settings on a phone controller.
final class ModesConfig {
  const ModesConfig({
    this.keys = const [],
    this.revoked = const [],
    this.index = '',
    this.boxKeys = projectModeKeys,
    this.fetchTimeoutS = 300,
    this.revocationMaxAgeDays = 30,
    this.minVersions = const [],
  });

  /// Trusted mode keys (base64 Ed25519 public keys): `[modes] keys`.
  final List<String> keys;

  /// Key ids that no longer count: `[modes] revoked`.
  final List<String> revoked;

  /// The registry index: an https URL or a file ('' for none).
  final String index;

  /// The mode keys built into the boxes' firmware: `[modes] box_keys`.
  final List<String> boxKeys;

  /// How long a box's fetch may take: `[modes] fetch_timeout_s`.
  final double fetchTimeoutS;

  /// With an index set, how many days the last revocation list fetched
  /// still counts when the index cannot be reached; 0: never an old list
  /// (`[modes] revocation_max_age_days`, FLD-7).
  final double revocationMaxAgeDays;

  /// A floor per mode, `org.example.mode=1.2.0`: an older version is
  /// refused (`[modes] min_versions`).
  final List<String> minVersions;

  Map<String, Object?> toJson() => {
    'keys': keys,
    'revoked': revoked,
    'index': index,
    'box_keys': boxKeys,
    'fetch_timeout_s': fetchTimeoutS,
    'revocation_max_age_days': revocationMaxAgeDays,
    'min_versions': minVersions,
  };

  static ModesConfig fromJson(Object? j) {
    if (j is! Map) return const ModesConfig();
    List<String> list(Object? v) => [
      for (final x in v is List ? v : const []) '$x',
    ];
    final t = j['fetch_timeout_s'];
    return ModesConfig(
      keys: list(j['keys']),
      revoked: list(j['revoked']),
      index: j['index'] is String ? j['index'] as String : '',
      boxKeys: j.containsKey('box_keys')
          ? list(j['box_keys'])
          : projectModeKeys,
      fetchTimeoutS: t is num ? t.toDouble() : 300,
      revocationMaxAgeDays: j['revocation_max_age_days'] is num
          ? (j['revocation_max_age_days'] as num).toDouble()
          : 30,
      minVersions: list(j['min_versions']),
    );
  }
}

/// A document that could not be fetched; [missing] when it is not there.
class FetchError implements Exception {
  FetchError(this.message, {this.missing = false, this.offline = false});
  final String message;
  final bool missing;

  /// The network (or the server) did not answer: not a document that is wrong.
  final bool offline;
  @override
  String toString() => message;
}

/// GET over HTTPS (the system's trust store), at most [limit] bytes; never
/// plain HTTP (signed_modes.py `https_fetch`).
Future<Uint8List> httpsFetch(String url, int limit) async {
  if (!url.startsWith('https://')) throw FetchError('only https:// URLs');
  final client = HttpClient()
    ..connectionTimeout = const Duration(seconds: 15)
    ..userAgent = 'atalaia-controller';
  try {
    final req = await client.getUrl(Uri.parse(url));
    req.followRedirects = false;
    final res = await req.close().timeout(const Duration(seconds: 15));
    if (res.statusCode != 200) {
      await res.drain<void>();
      throw FetchError(
        '$url: HTTP ${res.statusCode}',
        missing: res.statusCode == 404,
        offline: res.statusCode >= 500,
      );
    }
    final out = BytesBuilder(copy: false);
    await for (final chunk in res.timeout(const Duration(seconds: 15))) {
      out.add(chunk);
      if (out.length > limit) throw FetchError('$url: over $limit bytes');
    }
    return out.takeBytes();
  } on FetchError {
    rethrow;
  } on Object catch (e) {
    throw FetchError('$url: $e', offline: true);
  } finally {
    client.close(force: true);
  }
}

class ControllerSignedModes {
  ControllerSignedModes(
    this.modes,
    this.config, {
    Future<Uint8List> Function(String url, int limit)? fetch,
    double Function()? wallSeconds,
  }) : _fetch = fetch ?? httpsFetch,
       _wall =
           wallSeconds ?? (() => DateTime.now().microsecondsSinceEpoch / 1e6) {
    _rev = _loadRevocations();
    _floors = {
      for (final e in config.minVersions)
        if (e.contains('='))
          e.substring(0, e.indexOf('=')).trim(): e
              .substring(e.indexOf('=') + 1)
              .trim(),
    };
  }

  final ControllerModes modes;
  final ModesConfig config;
  final Future<Uint8List> Function(String url, int limit) _fetch;
  final double Function() _wall;

  /// {entries, fetched_at, error}, or null before the first read.
  Map<String, Object?>? _index;

  /// The last revocation list fetched, kept apart from the index: a failed
  /// fetch never erases it. `{keys: {id: reason}, fetched_at}` or null.
  Map<String, Object?>? _rev;

  late final Map<String, String> _floors;

  // ---- the revocation list, fetched and kept ------------------------------

  Map<String, Object?>? _loadRevocations() {
    try {
      final raw = modes.store.getSetting(revocationsSetting);
      if (raw == null) return null;
      final saved = jsonDecode(raw);
      if (saved is Map && saved['keys'] is Map && saved['fetched_at'] is num) {
        return {
          'keys': {
            for (final e in (saved['keys'] as Map).entries)
              '${e.key}': '${e.value}',
          },
          'fetched_at': (saved['fetched_at'] as num).toDouble(),
        };
      }
    } on Object {
      // A list that cannot be read is no list: nothing is installed offline.
    }
    return null;
  }

  /// revoked.json from the index's place, now; kept (with the time) when it
  /// is a good one. A list that is missing is an error: nothing says nothing
  /// was revoked.
  Future<void> _fetchRevocations() async {
    final revoked = parseRevoked(
      jsonDecode(
        utf8.decode(await _read(_locate('revoked.json'), indexMaxBytes)),
      ),
    );
    _rev = {'keys': revoked, 'fetched_at': _wall()};
    modes.store.setSetting(revocationsSetting, jsonEncode(_rev));
  }

  /// How old the kept revocation list is, in seconds, or null for none.
  double? revocationsAgeS() {
    final r = _rev;
    if (r == null) return null;
    final age = _wall() - (r['fetched_at']! as double);
    return age < 0 ? 0 : age;
  }

  /// Before an install or an upload (FLD-7): the revocation list again, or
  /// the last one while it is young enough, or nothing is installed. No index
  /// set: the field keeps [ModesConfig.revoked] itself.
  Future<void> requireCurrentRevocations() async {
    if (indexSource.isEmpty) return;
    final String reason;
    try {
      await _fetchRevocations();
      return;
    } on FetchError catch (e) {
      if (!e.offline) {
        throw ModeException(
          'the revocation list could not be read, so nothing is installed: '
          '${e.message}',
        );
      }
      reason = e.message;
    } on Object catch (e) {
      throw ModeException(
        'the revocation list is not a good one, so nothing is installed: '
        '${e is ModePackageError ? e.detail : e}',
      );
    }
    final age = revocationsAgeS();
    final maxS = config.revocationMaxAgeDays.clamp(0, double.infinity) * _dayS;
    if (age == null || age > maxS) {
      final have = age == null
          ? 'none was ever fetched'
          : 'the last one is ${age ~/ _dayS} days old';
      throw ModeException(
        'the revocation list cannot be reached ($reason) and $have '
        '([modes] revocation_max_age_days = ${config.revocationMaxAgeDays}): '
        'nothing signed is installed until the index answers',
      );
    }
  }

  String get indexSource => config.index.trim();

  // ---- the trusted keys --------------------------------------------------

  List<String> keyIds() => [
    for (final k in config.keys)
      if (_keyIdOrNull(k) != null) _keyIdOrNull(k)!,
  ];

  static String? _keyIdOrNull(String k) {
    try {
      return keyId(k);
    } on FormatException {
      return null;
    }
  }

  Set<String> revoked() => {
    ...config.revoked,
    ...((_rev?['keys'] as Map?)?.keys.cast<String>() ?? const []),
  };

  /// "trusted", "revoked" or "untrusted".
  String trust(Object? keyIdValue) {
    if (revoked().contains(keyIdValue)) return 'revoked';
    return keyIds().contains(keyIdValue) ? 'trusted' : 'untrusted';
  }

  // ---- where the index and its packages are ------------------------------

  String _locate(String relative) {
    final source = indexSource;
    if (relative.startsWith('https://')) return relative;
    if (source.startsWith('https://')) {
      final url = Uri.parse(source).resolve(relative).toString();
      if (!url.startsWith('https://')) {
        throw FetchError('a package outside https://');
      }
      return url;
    }
    final folder = File(source).absolute.parent.path;
    final path = File('$folder/$relative').absolute.uri.normalizePath();
    final file = path.toFilePath();
    if (!file.startsWith('$folder/')) {
      throw FetchError("a package outside the index's folder");
    }
    return file;
  }

  Future<Uint8List> _read(String where, int limit) async {
    if (where.startsWith('https://')) return _fetch(where, limit);
    if (where.startsWith('http://') ||
        where.startsWith('file:') ||
        where.startsWith('ftp:')) {
      throw FetchError('only https:// URLs or files');
    }
    final f = File(where);
    if (!f.existsSync()) {
      throw FetchError('$where: no such file', missing: true);
    }
    if (f.lengthSync() > limit) throw FetchError('$where: over $limit bytes');
    return f.readAsBytesSync();
  }

  /// The index's entries and revocations, fetched again when asked or old.
  Future<Map<String, Object?>> loadIndex({bool refresh = false}) async {
    if (indexSource.isEmpty) {
      return {'error': null, 'entries': <ModeIndexEntry>[]};
    }
    final cached = _index;
    if (!refresh &&
        cached != null &&
        cached['error'] == null &&
        _wall() - (cached['fetched_at']! as double) < indexTtlS) {
      return cached;
    }
    try {
      final entries = parseModeIndex(
        jsonDecode(utf8.decode(await _read(indexSource, indexMaxBytes))),
      );
      await _fetchRevocations(); // a missing revoked.json is an error too
      _index = {'entries': entries, 'fetched_at': _wall(), 'error': null};
    } on Object catch (e) {
      // Fail closed: an index that cannot be read whole offers nothing. What
      // was revoked stays revoked (_rev is not touched).
      final why = switch (e) {
        ModePackageError() => '$e',
        FetchError() => e.message,
        _ => '$e',
      };
      _index = {
        'error': why,
        'entries': <ModeIndexEntry>[],
        'fetched_at': _wall(),
      };
    }
    return _index!;
  }

  // ---- installing --------------------------------------------------------

  /// The floor ([ModesConfig.minVersions]) a version is under, else null.
  String? belowFloor(Object? modeId, Object? version) {
    final floor = modeId is String ? _floors[modeId] : null;
    if (floor == null || version is! String) return null;
    final have = versionKey(version), want = versionKey(floor);
    return have != null && want != null && have.compareTo(want) < 0
        ? floor
        : null;
  }

  Future<Map<String, Object?>> _install(
    Uint8List archive,
    ModeRelease release,
    String? namedKey,
    bool verified,
    String source, {
    bool revocationsCurrent = false,
  }) async {
    if (config.keys.isEmpty) {
      throw ModeException(
        'no mode keys are set on this controller ([modes] keys): it '
        'installs nothing signed',
      );
    }
    final floor = belowFloor(release.id, release.version);
    if (floor != null) {
      throw ModeException(
        '${release.id} ${release.version} is below this controller\'s floor '
        'for it, $floor ([modes] min_versions): install a newer version',
      );
    }
    if (!revocationsCurrent) await requireCurrentRevocations();
    VerifiedModePackage package;
    try {
      package = await verifyModePackage(
        archive,
        release,
        config.keys,
        revoked: revoked(),
        namedKey: namedKey,
      );
    } on ModePackageError catch (e) {
      throw ModeException(
        'the signed package was refused (${e.code}): '
        '${e.detail.isEmpty ? e.code : e.detail}',
      );
    }
    final signed = <String, Object?>{
      'format': modeManifestHeader,
      'id': release.id,
      'version': release.version,
      'kind': release.kind,
      'min_tier': release.minTier,
      'size': release.size,
      'sha256': release.sha256,
      'signature': release.signature,
      'key_id': package.keyId,
      'license': package.license,
      'verified': verified,
      'source': source,
    };
    final pkg = modes.install(package.files, signed: signed, archive: archive);
    return annotate(pkg.toApi());
  }

  /// A package the GM uploaded with its release's fields: never verified by
  /// the project, whoever signed it.
  Future<Map<String, Object?>> upload(
    Uint8List archive,
    Map<String, Object?> fields,
  ) async {
    ModeRelease release;
    try {
      release = releaseFrom({
        ...fields,
        'size': archive.length,
        'sha256': sha256Hex(archive),
      });
    } on ModePackageError catch (e) {
      throw ModeException('the release file is not one (${e.detail})');
    }
    final named = fields['key_id'] is String
        ? fields['key_id']! as String
        : null;
    return _install(archive, release, named, false, 'upload');
  }

  Future<Map<String, Object?>> installFromIndex(
    Object? modeId,
    Object? version,
  ) async {
    final index = await loadIndex(refresh: true);
    if (index['error'] != null) {
      throw ModeException('the index could not be read: ${index['error']}');
    }
    ModeIndexEntry? entry;
    for (final e in index['entries']! as List<ModeIndexEntry>) {
      if (e.release.id == modeId && e.release.version == version) entry = e;
    }
    if (entry == null) {
      throw ModeException('$modeId $version is not in the index');
    }
    Uint8List archive;
    try {
      archive = await _read(_locate(entry.url), modePackageMaxBytes);
    } on FetchError catch (e) {
      throw ModeException('the package could not be fetched: ${e.message}');
    }
    return _install(
      archive,
      entry.release,
      entry.keyId,
      entry.verified,
      'index',
      revocationsCurrent: true,
    );
  }

  // ---- what the console shows --------------------------------------------

  /// A mode's API form with its signature's trust today.
  Map<String, Object?> annotate(Map<String, Object?> mode) {
    final signed = mode['signed'];
    if (signed is Map && signed.isNotEmpty) {
      mode['signed'] = {
        for (final k in ['key_id', 'verified', 'sha256', 'source', 'license'])
          k: signed[k],
        'trust': trust(signed['key_id']),
        if (belowFloor(mode['id'], mode['version']) != null)
          'below_floor': true,
      };
    }
    return mode;
  }

  Future<Map<String, Object?>> status({bool refresh = false}) async {
    final index = await loadIndex(refresh: refresh);
    final installed = {for (final m in modes.all()) m.id: m};
    final entries = <Map<String, Object?>>[];
    for (final e in index['entries']! as List<ModeIndexEntry>) {
      final have = installed[e.release.id];
      final String state;
      if (revoked().contains(e.keyId)) {
        state = 'revoked';
      } else if (!keyIds().contains(e.keyId)) {
        state = 'no_key';
      } else if (have != null && have.builtin) {
        state = 'builtin';
      } else if (have != null && have.mode.version == e.release.version) {
        state = 'installed';
      } else {
        state = 'available';
      }
      entries.add({
        'id': e.release.id,
        'name': e.name,
        'description': e.description,
        'author': e.author,
        'version': e.release.version,
        'kind': e.release.kind,
        'min_tier': e.release.minTier,
        'size': e.release.size,
        'license': e.license,
        'key_id': e.keyId,
        'verified': e.verified,
        'installed_version': have?.mode.version,
        'state': state,
      });
    }
    final age = revocationsAgeS();
    return {
      'keys': keyIds(),
      'revoked': revoked().toList()..sort(),
      'revocations_age_s': age?.toInt(),
      'index': {
        'source': indexSource.isEmpty ? null : indexSource,
        'error': index['error'],
        'entries': entries,
      },
    };
  }
}
