// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// An Android prop gets the signed mode packages a game needs from its
/// field controller, as a Field Box does (protocol/mode-packages.md,
/// "Fetching missing modes"; decisions P5B-8 to P5B-17, P5D-1 onwards, and
/// PKF-1 onwards for the phone).
///
/// When a join names a mode (or a modifier) the app does not carry, and
/// asks for a fetch (key 16) and names the controller (keys 13 and 14),
/// the prop downloads each missing part over HTTPS pinned to the field CA,
/// in this order and refusing at the first failure, with the box's codes:
/// no mode key (`no_key`), the release text exactly the manifest's lines
/// for the part asked for (`bad_release`), a signature by one of the
/// prop's own mode keys (`bad_signature`), the kind (`kind`), the tier,
/// never a built-in id (`builtin`), the size (`too_big`), the download
/// (`download`), the archive's size and SHA-256 (`bad_hash`), its canonical
/// form with a node.lua (`bad_archive`) and the script loading in the
/// core's sandbox with the composed game (`load`). These are
/// [boxCheckRelease] and [boxCheckArchive] of the Pi controller's and the
/// firmware's shared checks (the vectors `box_checks`), then the phone's
/// own: its mode.yaml says what the signed manifest says. Nothing is run,
/// and nothing is kept, before every check passed: an unsigned or badly
/// signed package is refused with a [ModeFetchException] whose [code] the
/// screen turns into a message.
///
/// **Trust roots** ([propModeKeys]): the mode keys built into the app (the
/// `ATALAIA_MODE_KEYS` build define, space-separated base64) and those the
/// user entered in the settings; never a key a controller sends (P5B-9).
/// What was kept is checked again against the keys the app has now each
/// time it is read ([PropModeCache.load]), so a key taken away drops what
/// it signed.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import '../checkin/field_trust.dart';
import '../controller/mode_package.dart';
import '../core/node_runner.dart';
import '../protocol/join_payload.dart';
import '../storage/app_store.dart';
import 'mode_catalog.dart';

/// The most mode keys a prop takes from its settings (a box's four, for
/// rotation).
const propModeKeysMax = 4;

/// The mode keys built into this build, space-separated base64 given as
/// `--dart-define=ATALAIA_MODE_KEYS=...`; none in a build without them.
const builtInModeKeys = String.fromEnvironment('ATALAIA_MODE_KEYS');

/// The keys a prop trusts for a mode package: those built in, then the
/// settings' ([builtIn] is for tests), valid ones only, once each.
List<String> propModeKeys(AppSettings settings, {String? builtIn}) {
  final out = <String>[];
  for (final k in [
    ...(builtIn ?? builtInModeKeys).split(RegExp(r'[\s,]+')),
    ...settings.modeKeys,
  ]) {
    if (k.isNotEmpty && publicKeyBytes(k) != null && !out.contains(k)) {
      out.add(k);
    }
  }
  return out;
}

/// A fetch that did not end in an installed package: [code] is a box's
/// result (`no_key`, `unreachable`, `not_offered`, `download`, `bad_release`,
/// `bad_signature`, `kind`, `tier`, `builtin`, `too_big`, `bad_hash`,
/// `bad_archive`, `load`, `no_space`, `no_wifi`, `cancelled`), [part] the
/// mode it was fetching, [detail] what the check said.
class ModeFetchException implements Exception {
  ModeFetchException(this.code, this.detail, {this.part, this.version});
  final String code;
  final String detail;
  final String? part;
  final String? version;

  @override
  String toString() => 'ModeFetchException($code): $detail';
}

/// An answer to a GET: its status and body.
final class ModeHttpReply {
  const ModeHttpReply(this.status, this.body);
  final int status;
  final Uint8List body;
}

/// The two requests a fetch makes of the controller. Implementations throw
/// [ModeFetchException] `unreachable` when no connection could be made (or
/// its certificate is not the field's) and `download` when one broke or
/// sent more than it said.
abstract interface class ModeHttp {
  /// [maxBytes]: the most the body may have; [length]: when given, the
  /// `Content-Length` must be exactly this.
  Future<ModeHttpReply> get(Uri url, {required int maxBytes, int? length});

  Future<int> post(Uri url, List<int> body, Map<String, String> headers);

  void close();
}

/// [ModeHttp] over dart:io, trusting [field]'s CA and nothing else.
class IoModeHttp implements ModeHttp {
  IoModeHttp(PinnedField field) : _client = field.client();
  final HttpClient _client;

  @override
  Future<ModeHttpReply> get(
    Uri url, {
    required int maxBytes,
    int? length,
  }) async {
    final HttpClientResponse res;
    try {
      final req = await _client.getUrl(url);
      res = await req.close().timeout(const Duration(seconds: 15));
    } on Object {
      throw ModeFetchException('unreachable', '${url.host} did not answer');
    }
    if (res.statusCode != 200) {
      await res.drain<void>().catchError((Object _) {});
      return ModeHttpReply(res.statusCode, Uint8List(0));
    }
    if (length != null && res.contentLength != length) {
      await res.drain<void>().catchError((Object _) {});
      throw ModeFetchException(
        'download',
        'Content-Length ${res.contentLength}, expected $length',
      );
    }
    final bytes = BytesBuilder(copy: false);
    try {
      await for (final chunk in res.timeout(const Duration(seconds: 20))) {
        bytes.add(chunk);
        if (bytes.length > maxBytes) {
          throw ModeFetchException('download', 'more than $maxBytes bytes');
        }
      }
    } on ModeFetchException {
      rethrow;
    } on Object {
      throw ModeFetchException('download', 'the connection broke');
    }
    return ModeHttpReply(200, bytes.takeBytes());
  }

  @override
  Future<int> post(Uri url, List<int> body, Map<String, String> headers) async {
    try {
      final req = await _client.postUrl(url);
      headers.forEach(req.headers.set);
      req.add(body);
      final res = await req.close().timeout(const Duration(seconds: 10));
      await res.drain<void>();
      return res.statusCode;
    } on Object {
      return 0;
    }
  }

  @override
  void close() => _client.close(force: true);
}

/// A package kept on the phone: checked, with its files.
final class CachedMode {
  CachedMode({
    required this.release,
    required this.archive,
    required this.keyId,
    required this.manifest,
    required this.used,
  });

  final ModeRelease release;
  final Uint8List archive;
  final String keyId;
  final ModeManifest manifest;

  /// When a game last used it (ms since the epoch), for dropping the least
  /// recently used.
  int used;

  String get id => release.id;
}

/// What a prop keeps of the packages it fetched: up to [boxMaxFetched]
/// of them and [boxMaxFetchedBytes] of archives, the same limits as a
/// box's (P5B-12), in the app's store as each package's release text and
/// archive. Every package is checked again each time it is read ([load]).
class PropModeCache {
  PropModeCache(this.store);

  final AppStore store;
  static const _list = 'prop_modes';

  /// Checks one release text and archive for [wantedId] as a prop does: a
  /// [CachedMode], or a [ModeFetchException] with the first check that
  /// failed. [releaseText] first, then [archive] (null: checks the release
  /// only, for the early refusal before the download).
  static Future<CachedMode?> check({
    required List<int> releaseText,
    required String wantedId,
    required List<int>? archive,
    required Iterable<String> keys,
    required Iterable<String> builtin,
    required int now,
  }) async {
    final ModeRelease release;
    final String who;
    try {
      (release, who) = await boxCheckRelease(
        releaseText,
        wantedId,
        keys,
        'full',
        builtin: builtin,
      );
    } on ModePackageError catch (e) {
      throw ModeFetchException(e.code, e.detail, part: wantedId);
    }
    if (archive == null) return null;
    final Map<String, String> kept;
    final Map<String, String> files;
    try {
      kept = boxCheckArchive(archive, release);
      files = unpackArchive(
        archive,
        modeId: release.id,
        limit: release.size,
      ).$2;
      // The phone also reads mode.yaml (a box does not): it must say what
      // the signed manifest says, or the package is not what was signed.
      final own = manifestFields(files);
      for (final (a, b) in [
        (own.id, release.id),
        (own.version, release.version),
        (own.kind, release.kind),
        (own.minTier, release.minTier),
      ]) {
        if (a != b) {
          throw ModePackageError(
            'bad_archive',
            'mode.yaml does not say what the signed manifest says',
          );
        }
      }
    } on ModePackageError catch (e) {
      throw ModeFetchException(
        e.code == 'bad_hash' ? 'bad_hash' : 'bad_archive',
        e.detail,
        part: wantedId,
        version: release.version,
      );
    }
    // The files the prop runs: mode.yaml, node.lua and the screens (a
    // field.lua is the controller's; the prop never runs one).
    final run = {
      'mode.yaml': files['mode.yaml']!,
      for (final e in kept.entries) e.key: e.value,
    };
    final ModeManifest manifest;
    try {
      manifest = ModeManifest.parse(release.id, run);
    } on Object catch (e) {
      throw ModeFetchException(
        'load',
        '$e',
        part: wantedId,
        version: release.version,
      );
    }
    final bad = ModeCatalog([
      manifest,
    ]).screenProblems().entries.where((e) => e.value != null);
    if (bad.isNotEmpty) {
      throw ModeFetchException(
        'load',
        'screen ${bad.first.key}: ${bad.first.value}',
        part: wantedId,
        version: release.version,
      );
    }
    return CachedMode(
      release: release,
      archive: Uint8List.fromList(archive),
      keyId: who,
      manifest: manifest,
      used: now,
    );
  }

  /// The kept packages that pass every check again with [keys] (and are
  /// not one of [builtin]); the others are dropped from the store.
  Future<List<CachedMode>> load(
    Iterable<String> keys,
    Iterable<String> builtin, {
    int Function()? clock,
  }) async {
    final now = (clock ?? () => DateTime.now().millisecondsSinceEpoch)();
    final rows = await store.loadList(_list);
    final out = <CachedMode>[];
    var dropped = false;
    for (final j in rows) {
      try {
        final id = j['id'] as String;
        final c = await check(
          releaseText: base64.decode(j['release']! as String),
          wantedId: id,
          archive: base64.decode(j['archive']! as String),
          keys: keys,
          builtin: builtin,
          now: (j['used'] as int?) ?? now,
        );
        out.add(c!);
      } on Object {
        dropped = true;
      }
    }
    if (dropped) await _save(out);
    return out;
  }

  Future<void> _save(List<CachedMode> all) => store.saveList(_list, [
    for (final c in all)
      {
        'id': c.id,
        'version': c.release.version,
        'release': base64.encode(c.release.text()),
        'archive': base64.encode(c.archive),
        'used': c.used,
      },
  ]);

  /// Keeps [add], replacing an older version of the same id; drops the
  /// least recently used package, never one of [protect] (the joined game's
  /// parts), while there are too many or too many bytes. `no_space` when
  /// that is not enough. Returns what is kept.
  Future<List<CachedMode>> put(
    List<CachedMode> kept,
    CachedMode add,
    Set<String> protect,
  ) async {
    final all = [
      for (final c in kept)
        if (c.id != add.id) c,
      add,
    ];
    int bytes() => all.fold(0, (n, c) => n + c.archive.length);
    final order = [...all]..sort((a, b) => a.used.compareTo(b.used));
    for (final c in order) {
      if (all.length <= boxMaxFetched && bytes() <= boxMaxFetchedBytes) break;
      if (protect.contains(c.id) || c.id == add.id) continue;
      all.remove(c);
    }
    if (all.length > boxMaxFetched || bytes() > boxMaxFetchedBytes) {
      throw ModeFetchException(
        'no_space',
        'no package can be dropped to make room',
        part: add.id,
        version: add.release.version,
      );
    }
    await _save(all);
    return all;
  }

  /// Marks the packages of a game as used now.
  Future<void> touch(List<CachedMode> kept, Iterable<String> ids) async {
    final now = DateTime.now().millisecondsSinceEpoch;
    var changed = false;
    for (final c in kept) {
      if (ids.contains(c.id)) {
        c.used = now;
        changed = true;
      }
    }
    if (changed) await _save(kept);
  }

  /// Forgets every package (join key 17, as a box does).
  Future<void> forgetAll() => store.saveList(_list, const []);
}

/// The parts of [modeId] ("main+modifier+...") that neither [catalog] nor
/// [kept] has: what a fetch is for.
List<String> missingParts(
  String modeId,
  ModeCatalog catalog,
  Iterable<CachedMode> kept,
) {
  final have = {for (final c in kept) c.id};
  return [
    for (final p in modeId.split('+'))
      if (catalog.byId(p) == null && !have.contains(p)) p,
  ];
}

/// Fetches the missing parts of a game's mode from its controller.
class PropModeFetcher {
  PropModeFetcher({
    required this.cache,
    required this.open,
    required this.runner,
    this.clock,
  });

  final PropModeCache cache;

  /// The HTTP client pinned to the field of the join's keys 13 and 14
  /// (`AppServices.trust.forGame`, which checks the CA against key 13); it
  /// throws when the CA is not the one named, which is `unreachable`.
  final Future<ModeHttp> Function(List<String> urls, Uint8List caSha256) open;

  /// The core: a script must load in its sandbox before it is kept.
  final NodeRunner runner;
  final int Function()? clock;

  /// What the game's mode is, with [builtin] ones first and then the kept
  /// ones; fetches what is missing when [join] asks for it. Returns the
  /// catalogue to run it with, or throws [ModeFetchException].
  Future<ModeCatalog> resolve(
    JoinPayload join,
    ModeCatalog builtin,
    Iterable<String> keys,
  ) async {
    final ids = {for (final m in builtin.modes) m.id};
    var kept = await cache.load(keys, ids, clock: clock);
    if (join.forgetModes && kept.isNotEmpty) {
      await cache.forgetAll();
      kept = const [];
    }
    final parts = join.modeId.split('+');
    final missing = missingParts(join.modeId, builtin, kept);
    if (missing.isEmpty) {
      await cache.touch(kept, parts);
      return _catalog(builtin, kept);
    }
    final urls = join.urls, ca = join.caSha256;
    if (!join.fetchModes || urls == null || urls.isEmpty || ca == null) {
      // The box answers "no mode": nothing to fetch it with.
      throw ModeFetchException(
        'not_offered',
        'the join does not ask for a fetch',
        part: missing.first,
      );
    }
    if (keys.isEmpty) {
      throw ModeFetchException('no_key', 'no mode key', part: missing.first);
    }
    final ModeHttp http;
    try {
      http = await open(urls, ca);
    } on Object {
      throw ModeFetchException(
        'unreachable',
        'the controller is not reachable with the field certificate',
        part: missing.first,
      );
    }
    try {
      for (final id in [...missing]) {
        final got = await _one(http, join, urls, id, keys, ids, kept, parts);
        kept = got;
      }
    } finally {
      http.close();
    }
    final catalog = _catalog(builtin, kept);
    await _loads(catalog, join);
    await cache.touch(kept, parts);
    return catalog;
  }

  ModeCatalog _catalog(ModeCatalog builtin, List<CachedMode> kept) =>
      ModeCatalog([...builtin.modes, for (final c in kept) c.manifest]);

  /// The composed game must load in the core's sandbox (`load`).
  Future<void> _loads(ModeCatalog catalog, JoinPayload join) async {
    final GameMode game;
    try {
      game = catalog.compose(join.modeId);
    } on ModeException catch (e) {
      throw ModeFetchException('load', e.message);
    }
    if (!runner.supported) return;
    try {
      final node = await runner.start(
        NodeSpec(
          source: game.nodeScript,
          chunkName: game.chunkName,
          nodeId: join.nodeId,
          gameSeed: join.gameSeed,
          teams: join.teams,
          params: game.resolveParams(join.params ?? const {}, join.teams),
        ),
        clock: GameClock.manual,
      );
      final loaded = node.loaded;
      final why = loaded ? '' : (await node.snapshot()).lastError;
      await node.close();
      if (!loaded) {
        throw ModeFetchException('load', why.isEmpty ? 'did not load' : why);
      }
    } on ModeFetchException {
      rethrow;
    } on Object catch (e) {
      throw ModeFetchException('load', '$e');
    }
  }

  Future<List<CachedMode>> _one(
    ModeHttp http,
    JoinPayload join,
    List<String> urls,
    String id,
    Iterable<String> keys,
    Set<String> builtin,
    List<CachedMode> kept,
    List<String> parts,
  ) async {
    String? version;
    Future<List<CachedMode>> failed(ModeFetchException e) async {
      await _report(http, urls, join, id, version ?? e.version, e.code, kept);
      throw ModeFetchException(
        e.code,
        e.detail,
        part: id,
        version: version ?? e.version,
      );
    }

    // Each address in turn, as a box does; the first that answers decides.
    Uint8List? text;
    Uri? base;
    for (final u in urls) {
      final root = Uri.parse(u);
      final b = root.replace(
        path: '/api/v1/mode-packages/${Uri.encodeComponent(id)}',
        query: '',
      );
      try {
        final r = await http.get(
          b.replace(path: '${b.path}/release'),
          maxBytes: 512,
        );
        if (r.status != 200) {
          return failed(ModeFetchException('not_offered', 'HTTP ${r.status}'));
        }
        text = r.body;
        base = b;
        break;
      } on ModeFetchException catch (e) {
        if (e.code != 'unreachable') return failed(e);
      }
    }
    if (text == null || base == null) {
      return failed(ModeFetchException('unreachable', 'no address answered'));
    }
    final now = (clock ?? () => DateTime.now().millisecondsSinceEpoch)();
    try {
      await PropModeCache.check(
        releaseText: text,
        wantedId: id,
        archive: null,
        keys: keys,
        builtin: builtin,
        now: now,
      );
      version = parseReleaseText(text).version;
    } on ModeFetchException catch (e) {
      return failed(e);
    }
    final release = parseReleaseText(text);
    final ModeHttpReply pkg;
    try {
      pkg = await http.get(
        base.replace(path: '${base.path}/package'),
        maxBytes: release.size,
        length: release.size,
      );
    } on ModeFetchException catch (e) {
      return failed(e);
    }
    if (pkg.status != 200) {
      return failed(ModeFetchException('not_offered', 'HTTP ${pkg.status}'));
    }
    final CachedMode got;
    try {
      got = (await PropModeCache.check(
        releaseText: text,
        wantedId: id,
        archive: pkg.body,
        keys: keys,
        builtin: builtin,
        now: now,
      ))!;
    } on ModeFetchException catch (e) {
      return failed(e);
    }
    final List<CachedMode> now2;
    try {
      now2 = await cache.put(kept, got, parts.toSet());
    } on ModeFetchException catch (e) {
      return failed(e);
    }
    await _report(http, urls, join, id, got.release.version, 'installed', now2);
    return now2;
  }

  /// The report the controller waits for (best effort: no answer is the
  /// controller's `report_lost`).
  Future<void> _report(
    ModeHttp http,
    List<String> urls,
    JoinPayload join,
    String id,
    String? version,
    String result,
    List<CachedMode> kept,
  ) async {
    final body = modeReportBody(join.gameId, join.nodeId, id, version, result, {
      for (final c in kept) c.id: c.release.version,
    });
    final mac = reportMac(join.gameKey, body);
    for (final u in urls) {
      final url = Uri.parse(
        u,
      ).replace(path: '/api/v1/mode-packages/report', query: '');
      final status = await http.post(url, body, {
        'Content-Type': 'text/plain',
        'X-Atalaia-Mac': mac,
      });
      if (status == 200) return;
    }
  }
}
