// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The site server sync on the Android field controller (PE24 slice S7,
/// decisions PE24-118 onward): the Pi's
/// controller/atalaia_controller/sync_client.py in Dart, the same requests
/// in the same order with the same bodies (protocol/sync.md; every body
/// checked with controller_sync_format.dart before it goes, every answer
/// before it is used).
///
/// The controller opens every connection (a phone usually sits behind 4G
/// and carrier-grade NAT, P4R12): HTTPS requests to the site server's
/// `/api/v1/sync/*` with the field's API key in `Authorization: Bearer`;
/// the site server never connects to the phone and holds none of its
/// tokens. `http://` is allowed only to the phone itself; redirects are
/// refused, so the key never goes to another address.
///
/// **Offline first.** A game runs the same whether the site server is
/// reachable or not: the engine keeps everything in its store, and this
/// client sends from there, on the controller's own isolate, between ticks
/// (it never holds the engine up: one request at a time, each awaited).
/// Per game and in the log's order, the events above the last id the site
/// server acknowledged, then the game's score counters per source and its
/// nodes when they changed; then the field's chrono registry (marshal keys
/// with their periods, the replica registry, the signed readings), game day
/// (the schedule, each linked game's roster until it starts, the claims'
/// verdicts, the outcomes after the game), with branding "site" the
/// field's branding and saved teams with their images, with the library on
/// the field's scenarios and game presets. Every 30 s while a game runs and
/// every 5 min between games; a failure doubles the wait up to 5 min; a
/// `Retry-After` is respected; a game's start, pause or end wakes it.
///
/// An event's id is its place in the game's log (1, 2, ...; the store
/// keeps the log in the order it was written), so the cursor is per game
/// and never moves backwards; the site server's key `(game, node, seq,
/// game time, type)` keeps replays harmless, as for a Pi.
///
/// Never sent: positions, check-in names and federation numbers, tokens,
/// the game, join and token keys, private keys.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import '../chrono/reading.dart' show newUuid;
import '../modes/mode_catalog.dart' show ModeException;
import 'controller_branding.dart';
import 'controller_engine.dart';
import 'controller_images.dart';
import 'controller_modes.dart';
import 'controller_scenarios.dart';
import 'controller_schedule.dart';
import 'controller_sync_format.dart';

/// The app's version, as `controller.version` names it.
const syncAppVersion = '0.4.0-dev';

final _apiKeyRe = RegExp(r'^[A-Za-z0-9_-]{43}$');
const _idSetting = 'sync.controller_id';
const _librarySetting = 'sync.site_library';
const _batchesPerGame = 20;
const _batchesPerKind = 20;
final _fieldRun = RegExp(r'^field-(\d{1,6})$');
const _live = ['running', 'paused'];
const _scheduleDays = 14;
const _unsupported = [404, 405, 501];
const _unsupportedCodes = [
  'Not Found',
  'Method Not Allowed',
  'http_404',
  'http_405',
  'http_501',
];
const _imagesPerCycle = 50;

/// A key as the site server makes them: 32 random bytes, base64url
/// without padding.
bool apiKeyOk(String? key) => key != null && _apiKeyRe.hasMatch(key);

/// The first 8 hex digits of the key's SHA-256 (the site server lists keys
/// by the same).
String keyFingerprint(String key) =>
    sha256.convert(ascii.encode(key)).toString().substring(0, 8);

bool _loopback(String host) {
  if (host == 'localhost') return true;
  final a = InternetAddress.tryParse(host.replaceAll(RegExp(r'^\[|\]$'), ''));
  return a != null && a.isLoopback;
}

/// Why the site server's address is not usable, or null (sync_client.py
/// `url_problem`).
String? syncUrlProblem(String url) {
  final Uri u;
  try {
    u = Uri.parse(url);
  } on FormatException {
    return 'not a valid URL';
  }
  if ((u.scheme != 'https' && u.scheme != 'http') || u.host.isEmpty) {
    return 'an https:// address such as https://site.example.org';
  }
  if (u.userInfo.isNotEmpty || u.hasQuery || u.hasFragment) {
    return 'no user, password, query or fragment in the address';
  }
  if (u.scheme == 'http' && !_loopback(u.host)) {
    return 'https:// is required (http:// only to this machine)';
  }
  return null;
}

/// The canonical JSON of a value, for the change hashes.
String _canonical(Object? v) {
  if (v is Map) {
    final keys = [for (final k in v.keys) '$k']..sort();
    return '{${[for (final k in keys) '${jsonEncode(k)}:${_canonical(v[k])}'].join(',')}}';
  }
  if (v is List) return '[${v.map(_canonical).join(',')}]';
  return jsonEncode(v);
}

String digestOf(Object? value) =>
    sha256.convert(utf8.encode(_canonical(value))).toString();

/// The sync's settings: the Pi's `[sync]` section.
class SyncConfig {
  const SyncConfig({
    required this.url,
    required this.apiKey,
    this.intervalGameS = 30,
    this.intervalIdleS = 300,
    this.timeoutS = 15,
    this.branding = 'local',
    this.library = true,
    this.remoteGm = false,
    this.caPem,
  });

  /// The site server's base address (https://...).
  final String url;

  /// The field's API key (43 characters of base64url).
  final String apiKey;
  final double intervalGameS;
  final double intervalIdleS;
  final double timeoutS;

  /// "local" (the console's branding) or "site" (the site server's).
  final String branding;

  /// Pull the field's scenarios and game presets.
  final bool library;

  /// Open the stream for the remote GM (controller_remote_gm.dart).
  final bool remoteGm;

  /// A CA certificate (PEM) to check the site server against instead of
  /// the system's (the Pi's `[sync] ca_file`).
  final String? caPem;

  /// Why these settings cannot be used, or null.
  String? problem() {
    final u = syncUrlProblem(url);
    if (u != null) return 'url: $u';
    if (!apiKeyOk(apiKey)) {
      return "api_key: the field's key from the site server (43 characters)";
    }
    if (branding != 'local' && branding != 'site') {
      return "branding: 'local' or 'site'";
    }
    if (intervalGameS < 5 || intervalIdleS < intervalGameS) {
      return 'intervals: at least 5 s while a game runs, and no less between games';
    }
    return null;
  }

  Map<String, Object?> toJson() => {
    'url': url,
    'api_key': apiKey,
    'interval_game_s': intervalGameS,
    'interval_idle_s': intervalIdleS,
    'timeout_s': timeoutS,
    'branding': branding,
    'library': library,
    'remote_gm': remoteGm,
    if (caPem != null) 'ca_pem': caPem,
  };

  static SyncConfig? fromJson(Object? j) {
    if (j is! Map) return null;
    final url = j['url'], key = j['api_key'];
    if (url is! String || key is! String) return null;
    double n(Object? v, double d) => v is num ? v.toDouble() : d;
    return SyncConfig(
      url: url,
      apiKey: key,
      intervalGameS: n(j['interval_game_s'], 30),
      intervalIdleS: n(j['interval_idle_s'], 300),
      timeoutS: n(j['timeout_s'], 15),
      branding: j['branding'] == 'site' ? 'site' : 'local',
      library: j['library'] != false,
      remoteGm: j['remote_gm'] == true,
      caPem: j['ca_pem'] as String?,
    );
  }
}

/// A request that did not go through: [code] says why.
class SyncError implements Exception {
  SyncError(this.code, {this.status, this.retryAfter, this.detail});
  final String code;
  final int? status;
  final double? retryAfter;
  final Object? detail;
  @override
  String toString() => 'SyncError($code${status == null ? '' : ', $status'})';
}

(String, String) _refusal(SyncError e) {
  final d = e.detail is Map ? e.detail! as Map : const <String, Object?>{};
  return ('${d['error'] ?? e.code}', '${d['path'] ?? 'the body'}');
}

/// What carries the sync's requests (a test's fake, or [HttpSyncTransport]).
abstract interface class SyncTransport {
  Future<Map<String, Object?>> post(String path, Map<String, Object?> body);
  Future<Map<String, Object?>> get(String path);
  Future<Uint8List> getBytes(String path, int limit);
  void close();
}

/// HTTPS to the site server with dart:io's HttpClient: no redirects, TLS
/// 1.2 or later checked against the system's CAs (or [SyncConfig.caPem]).
class HttpSyncTransport implements SyncTransport {
  HttpSyncTransport(SyncConfig config, {HttpClient? client})
    : base = config.url.replaceAll(RegExp(r'/+$'), ''),
      _auth = 'Bearer ${config.apiKey}',
      timeout = Duration(milliseconds: (config.timeoutS * 1000).round()),
      _client = client ?? HttpClient(context: _context(config.caPem)) {
    _client
      ..connectionTimeout = timeout
      ..userAgent = 'atalaia-controller/$syncAppVersion (android)';
  }

  static SecurityContext? _context(String? pem) {
    if (pem == null || pem.trim().isEmpty) return null;
    return SecurityContext(withTrustedRoots: false)
      ..setTrustedCertificatesBytes(utf8.encode(pem));
  }

  final String base;
  final String _auth;
  final Duration timeout;
  final HttpClient _client;

  Future<(int, HttpHeaders, List<int>)> _send(
    String method,
    String path, {
    Map<String, Object?>? body,
    int limit = 1024 * 1024,
  }) async {
    try {
      final req = await _client.openUrl(method, Uri.parse(base + path));
      req
        ..followRedirects = false
        ..headers.set(HttpHeaders.authorizationHeader, _auth)
        ..headers.set(HttpHeaders.acceptHeader, 'application/json');
      if (body != null) {
        req.headers.contentType = ContentType.json;
        req.add(utf8.encode(jsonEncode(body)));
      }
      final resp = await req.close().timeout(timeout);
      final bytes = <int>[];
      await for (final chunk in resp.timeout(timeout)) {
        bytes.addAll(chunk);
        if (bytes.length > limit + 1) break;
      }
      return (resp.statusCode, resp.headers, bytes);
    } on SocketException catch (e) {
      throw SyncError('unreachable', detail: e.message);
    } on HandshakeException catch (e) {
      throw SyncError('unreachable', detail: e.message);
    } on TimeoutException {
      throw SyncError('unreachable', detail: 'timed out');
    } on HttpException catch (e) {
      throw SyncError('unreachable', detail: e.message);
    }
  }

  Never _http(int status, HttpHeaders headers, List<int> bytes) {
    Object? detail;
    try {
      detail = jsonDecode(utf8.decode(bytes));
    } on FormatException {
      detail = const {};
    }
    final retry = headers.value('retry-after');
    final code = detail is Map && detail['detail'] is String
        ? detail['detail']! as String
        : 'http_$status';
    throw SyncError(
      code,
      status: status,
      retryAfter: retry != null && RegExp(r'^\d+$').hasMatch(retry)
          ? double.parse(retry)
          : null,
      detail: detail,
    );
  }

  Map<String, Object?> _json(List<int> bytes) {
    final Object? v;
    try {
      v = jsonDecode(utf8.decode(bytes));
    } on FormatException {
      throw SyncError('bad_answer');
    }
    if (v is! Map<String, Object?>) throw SyncError('bad_answer');
    return v;
  }

  @override
  Future<Map<String, Object?>> post(
    String path,
    Map<String, Object?> body,
  ) async {
    final (status, headers, bytes) = await _send('POST', path, body: body);
    if (status < 200 || status > 299) _http(status, headers, bytes);
    return _json(bytes);
  }

  @override
  Future<Map<String, Object?>> get(String path) async {
    final (status, headers, bytes) = await _send('GET', path);
    if (status < 200 || status > 299) _http(status, headers, bytes);
    return _json(bytes);
  }

  @override
  Future<Uint8List> getBytes(String path, int limit) async {
    final (status, headers, bytes) = await _send('GET', path, limit: limit);
    if (status < 200 || status > 299) _http(status, headers, bytes);
    if (bytes.length > limit) throw SyncError('too_large');
    return Uint8List.fromList(bytes);
  }

  @override
  void close() => _client.close(force: true);
}

/// The site sync client: [start] runs it on the controller's isolate.
class ControllerSync {
  ControllerSync(
    this.engine,
    this.config, {
    SyncTransport? transport,
    double Function()? wall,
    this.schedule,
  }) : transport = transport ?? HttpSyncTransport(config),
       _wall = wall ?? engine.wallSeconds,
       keyFingerprintText = keyFingerprint(config.apiKey) {
    engine.syncStatus = status;
    engine.addListener(_onMessage);
    final s = schedule;
    if (s != null) {
      s
        ..kick = kick
        ..syncEnabled = true;
    }
    engine.branding?.siteManaged = config.branding == 'site';
  }

  final ControllerEngine engine;
  final SyncConfig config;
  final SyncTransport transport;
  final ControllerSchedule? schedule;
  final double Function() _wall;
  final String keyFingerprintText;

  int failures = 0;
  double? retryAfter;
  double? lastOkAt, lastAttemptAt;
  String? lastError, registryError;
  int refusedReadings = 0, requests = 0, pulls = 0;
  String? gameDayError;
  bool gameDaySupported = true;
  double? schedulePulledAt;
  int claimsAnswered = 0;
  bool brandingSupported = true;
  double? brandingPulledAt;
  String? brandingError;
  int imagesFetched = 0;
  bool librarySupported = true;
  double? libraryPulledAt;
  String? libraryError;
  int scenariosInstalled = 0;

  /// The remote GM's status (controller_remote_gm.dart), when it runs.
  Map<String, Object?> Function()? remoteStatus;

  Timer? _timer;
  bool _running = false, _stopped = true;
  Future<bool>? _cycle;

  // --- identity -------------------------------------------------------------

  /// This controller's id on the site server: random, made once, kept in
  /// the store.
  String get controllerId {
    var id = engine.store.getSetting(_idSetting);
    if (id == null || id.isEmpty) {
      id = newUuid(Random.secure());
      engine.store.setSetting(_idSetting, id);
    }
    return id;
  }

  Map<String, Object?> envelope([Map<String, Object?>? game]) => {
    'sync_version': syncVersion,
    'controller': {'id': controllerId, 'version': syncAppVersion},
    if (game != null)
      'game': {'game_id': game['id'], 'game_seed': game['game_seed']},
  };

  // --- the store's sync state (store.py's sync_state and sync_items) --------

  static const _doc = 'sync';

  Map<String, Object?> _state() {
    final d = engine.store.document(_doc);
    return d is Map
        ? {
            'games': (d['games'] as Map?)?.cast<String, Object?>() ?? {},
            'items': (d['items'] as Map?)?.cast<String, Object?>() ?? {},
          }
        : {'games': <String, Object?>{}, 'items': <String, Object?>{}};
  }

  Map<String, Object?> syncState(int gid, int seed) {
    final g = (_state()['games']! as Map)['$gid:$seed'];
    return {
      'acked_id': 0,
      'meta_sha': null,
      'scores_sha': null,
      'nodes_sha': null,
      'skipped': 0,
      'final': false,
      'last_ok_at': null,
      'last_error': null,
      if (g is Map) ...g.cast<String, Object?>(),
    };
  }

  void _saveState(int gid, int seed, Map<String, Object?> fields) {
    final st = _state();
    final games = st['games']! as Map<String, Object?>;
    final key = '$gid:$seed';
    games[key] = {
      ...((games[key] as Map?)?.cast<String, Object?>() ?? {}),
      ...fields,
    };
    engine.store.putDocument(_doc, st);
  }

  Map<String, String> syncItems(String kind) {
    final m = (_state()['items']! as Map)[kind];
    return m is Map ? m.cast<String, String>() : {};
  }

  void _markSynced(String kind, Map<String, String> items) {
    final st = _state();
    final all = st['items']! as Map<String, Object?>;
    all[kind] = {...syncItems(kind), ...items};
    engine.store.putDocument(_doc, st);
  }

  /// Forgets what was sent (a new site server): everything goes again and
  /// the site server drops what it already has as duplicates.
  void resetState() => engine.store.putDocument(_doc, <String, Object?>{
    'games': <String, Object?>{},
    'items': <String, Object?>{},
  });

  // --- the loop ---------------------------------------------------------------

  void start() {
    _stopped = false;
    _schedule(Duration.zero);
  }

  Future<void> stop() async {
    _stopped = true;
    _timer?.cancel();
    _timer = null;
    engine.removeListener(_onMessage);
    await _cycle;
    transport.close();
  }

  void _schedule(Duration d) {
    _timer?.cancel();
    if (_stopped) return;
    _timer = Timer(d, () async {
      try {
        await runOnce();
      } on Object {
        failures++;
      }
      _schedule(Duration(milliseconds: (nextDelay() * 1000).round()));
    });
  }

  /// Sync soon (a game started, paused or ended), unless backing off.
  void kick() {
    if (failures == 0 && !_running && !_stopped) _schedule(Duration.zero);
  }

  void _onMessage(Map<String, Object?> msg) {
    if (msg['type'] == 'game' || msg['type'] == 'chrono_list') kick();
  }

  double nextDelay() {
    final game = engine.store.liveGame();
    final base = game != null && _live.contains(game['state'])
        ? config.intervalGameS
        : config.intervalIdleS;
    var delay = failures == 0
        ? base
        : min(base * pow(2, failures), config.intervalIdleS);
    delay = max(delay, base);
    final r = retryAfter;
    if (r != null) delay = max(delay, min(r, 3600.0));
    return delay;
  }

  /// One pass over every game; true when everything due went through.
  Future<bool> runOnce() async {
    while (_running) {
      await _cycle;
    }
    _running = true;
    final c = _cycle = _once();
    try {
      return await c;
    } finally {
      _running = false;
    }
  }

  Future<bool> _once() async {
    lastAttemptAt = _wall();
    try {
      for (final game in engine.store.games()) {
        await _syncGame(game);
      }
      await _syncRegistry();
      await _gameDay();
      await _siteBranding();
      await _siteLibrary();
    } on SyncError catch (e) {
      failures++;
      retryAfter = e.retryAfter;
      lastError = e.code;
      return false;
    }
    failures = 0;
    retryAfter = null;
    lastError = null;
    lastOkAt = _wall();
    return true;
  }

  Future<Map<String, Object?>> _post(String path, Map<String, Object?> body) {
    requests++;
    return transport.post(path, body);
  }

  /// A request about a game the site server may not have yet: the game's
  /// metadata first, then the request again.
  Future<Map<String, Object?>> _bound(
    Map<String, Object?> game,
    String path,
    Map<String, Object?> body,
  ) async {
    try {
      return await _post(path, body);
    } on SyncError catch (e) {
      if (e.code != 'game_not_found') rethrow;
    }
    final meta = this.meta(game);
    await _post('/api/v1/sync/games', {...envelope(game), 'meta': meta});
    _saveState(game['id']! as int, game['game_seed']! as int, {
      'meta_sha': digestOf(meta),
    });
    return _post(path, body);
  }

  Future<void> _syncGame(Map<String, Object?> game) async {
    final gid = game['id']! as int, seed = game['game_seed']! as int;
    final state = syncState(gid, seed);
    if (state['final'] == true) return;
    final env = envelope(game);
    var refused = false, sent = false;
    final meta = this.meta(game);
    if (digestOf(meta) != state['meta_sha']) {
      refused |= await _rejected(gid, seed, '/api/v1/sync/games', {
        ...env,
        'meta': meta,
      });
      _saveState(gid, seed, {'meta_sha': digestOf(meta)});
      sent = true;
    }
    final acked = await _pushEvents(game, env, state);
    sent |= acked != null && acked != state['acked_id'];
    final counters = this.counters(game);
    if (counters.isNotEmpty && digestOf(counters) != state['scores_sha']) {
      refused |= await _rejected(gid, seed, '/api/v1/sync/scores', {
        ...env,
        'counters': counters,
      }, game);
      _saveState(gid, seed, {'scores_sha': digestOf(counters)});
      sent = true;
    }
    final nodes = this.nodes(game);
    if (nodes.isNotEmpty && digestOf(nodes) != state['nodes_sha']) {
      refused |= await _rejected(gid, seed, '/api/v1/sync/nodes', {
        ...env,
        'nodes': nodes,
      }, game);
      _saveState(gid, seed, {'nodes_sha': digestOf(nodes)});
      sent = true;
    }
    if (acked == null) refused = true;
    final fin =
        !refused &&
        game['state'] == 'ended' &&
        acked != null &&
        _eventsAfter(gid, acked).isEmpty;
    _saveState(gid, seed, {
      'final': fin,
      'last_ok_at': _wall(),
      if (sent && !refused) 'last_error': null,
    });
  }

  /// Sends one body; a 400 is kept in the game's `last_error` and the body
  /// counts as sent (it goes again only once it changes). True when
  /// refused.
  Future<bool> _rejected(
    int gid,
    int seed,
    String path,
    Map<String, Object?> body, [
    Map<String, Object?>? game,
  ]) async {
    try {
      if (game == null) {
        await _post(path, body);
      } else {
        await _bound(game, path, body);
      }
      return false;
    } on SyncError catch (e) {
      if (e.status != 400) rethrow;
      final (code, where) = _refusal(e);
      _saveState(gid, seed, {'last_error': '$path: $code at $where'});
      return true;
    }
  }

  /// The game's events with an id above [after], in the log's order.
  List<Map<String, Object?>> _eventsAfter(int gid, int after, [int? limit]) {
    final log = engine.store.eventLog(gid);
    final out = <Map<String, Object?>>[];
    for (var i = after; i < log.length; i++) {
      final e = log[i];
      out.add({
        'id': i + 1,
        'node': e['node'],
        'seq': e['seq'],
        't': e['t'],
        'type': e['type'],
        'team': e['team'],
        'squad': e['squad'],
        'prio': e['prio'],
        'data': e['data'],
        'epoch': e['epoch'],
        'pkt_seq': e['pkt_seq'],
      });
      if (limit != null && out.length >= limit) break;
    }
    return out;
  }

  Future<int?> _pushEvents(
    Map<String, Object?> game,
    Map<String, Object?> env,
    Map<String, Object?> state,
  ) async {
    final gid = game['id']! as int, seed = game['game_seed']! as int;
    var acked = state['acked_id']! as int;
    var skipped = state['skipped']! as int;
    for (var b = 0; b < _batchesPerGame; b++) {
      final rows = _eventsAfter(gid, acked, maxEvents);
      if (rows.isEmpty) break;
      final batch = <Map<String, Object?>>[];
      for (final row in rows) {
        try {
          batch.add(checkEvent(jsonDecode(jsonEncode(row)), 'event'));
        } on SyncFormatError {
          skipped++; // never stalls the queue
        }
      }
      if (batch.isNotEmpty) {
        final body = {...env, 'after_id': acked, 'events': batch};
        final Map<String, Object?> answer;
        try {
          answer = await _bound(game, '/api/v1/sync/events', body);
        } on SyncError catch (e) {
          if (e.status != 400) rethrow;
          final (code, where) = _refusal(e);
          _saveState(gid, seed, {
            'last_error': '/api/v1/sync/events: $code at $where',
          });
          return null;
        }
        if (answer['acked_id'] != batch.last['id']) {
          throw SyncError('bad_answer', detail: answer);
        }
      }
      acked = rows.last['id']! as int;
      _saveState(gid, seed, {'acked_id': acked, 'skipped': skipped});
      if (rows.length < maxEvents) break;
    }
    return acked;
  }

  // --- the field's chrono registry ------------------------------------------

  Future<void> _syncRegistry() async {
    final env = envelope();
    await _pushItems(
      'marshal',
      '/api/v1/sync/marshals',
      'marshals',
      marshalEntries(),
      maxMarshals,
      env,
    );
    await _pushItems(
      'replica',
      '/api/v1/sync/replicas',
      'replicas',
      replicaEntries(),
      maxReplicas,
      env,
    );
    await _pushReadings(env);
  }

  void _registryRefused(String path, SyncError e) {
    if (e.status != 400) throw e;
    final (code, where) = _refusal(e);
    registryError = '$path: $code at $where';
  }

  Future<void> _pushItems(
    String kind,
    String path,
    String field,
    Map<String, Map<String, Object?>> entries,
    int limit,
    Map<String, Object?> env,
  ) async {
    final sent = syncItems(kind);
    final due = [
      for (final e in entries.entries)
        if (digestOf(e.value) != sent[e.key]) e,
    ];
    final end = min(due.length, limit * _batchesPerKind);
    for (var start = 0; start < end; start += limit) {
      final chunk = due.sublist(start, min(start + limit, end));
      try {
        await _post(path, {
          ...env,
          field: [for (final e in chunk) e.value],
        });
      } on SyncError catch (e) {
        _registryRefused(path, e);
      }
      _markSynced(kind, {for (final e in chunk) e.key: digestOf(e.value)});
    }
  }

  Future<void> _pushReadings(Map<String, Object?> env) async {
    final checkin = engine.checkin;
    if (checkin == null) return;
    for (var b = 0; b < _batchesPerKind; b++) {
      final sent = syncItems('reading');
      final rows = [
        for (final r in checkin.storedReadings())
          if (!sent.containsKey(r['reading_id'])) r,
      ].take(maxReadings).toList();
      if (rows.isEmpty) return;
      final batch = <Map<String, Object?>>[];
      for (final row in rows) {
        final entry = <String, Object?>{
          'record': row['record_json'],
          'series_id': row['series_id'],
          'outcome': row['outcome'],
          'received_at': row['received_at'],
        };
        final seed = _gameSeed(row['game_id']);
        if (seed != null) entry['game_seed'] = seed;
        try {
          batch.add(checkReading(entry));
        } on SyncFormatError {
          // Not in protocol/sync.md's form: not sent (the Pi logs it).
        }
      }
      if (batch.isNotEmpty) {
        Map<String, Object?> answer = const {};
        try {
          answer = await _post('/api/v1/sync/chrono', {
            ...env,
            'readings': batch,
          });
        } on SyncError catch (e) {
          _registryRefused('/api/v1/sync/chrono', e);
        }
        final refused = answer['refused'];
        if (refused is List) refusedReadings += refused.length;
      }
      _markSynced('reading', {
        for (final r in rows) '${r['reading_id']}': '${r['reading_id']}',
      });
      if (rows.length < maxReadings) return;
    }
  }

  int? _gameSeed(Object? gameId) {
    if (gameId is! String ||
        !RegExp(r'^[0-9]+$').hasMatch(gameId) ||
        int.parse(gameId) > 0xffff) {
      return null;
    }
    return engine.store.game(int.parse(gameId))?['game_seed'] as int?;
  }

  /// Each marshal key once, by (marshal, key): its first registration and,
  /// for an earlier key, when it was last replaced. Public keys only.
  Map<String, Map<String, Object?>> marshalEntries() {
    final checkin = engine.checkin;
    if (checkin == null) return {};
    final out = <String, Map<String, Object?>>{};
    final rows = [
      for (final h in checkin.marshalKeyHistory()) {...h, 'current': false},
      for (final m in checkin.marshals())
        {...m, 'current': true, 'replaced_at': null},
    ];
    for (final row in rows) {
      final item = '${row['marshal_id']}:${row['public_key']}';
      final entry = out.putIfAbsent(
        item,
        () => {
          'marshal_id': row['marshal_id'],
          'public_key': row['public_key'],
          'registered_at': row['registered_at'],
          'replaced_at': null,
        },
      );
      entry['name'] = row['name'];
      entry['player_id'] = row['player_id'];
      entry['registered_at'] = min(
        entry['registered_at']! as num,
        row['registered_at']! as num,
      );
      if (row['current'] == true) {
        entry['replaced_at'] = null;
      } else {
        entry['replaced_at'] = max(
          (entry['replaced_at'] as num?) ?? 0,
          row['replaced_at']! as num,
        );
      }
    }
    out.removeWhere((_, e) {
      try {
        checkMarshal(Map<String, Object?>.of(e), 'marshal');
        return false;
      } on SyncFormatError {
        return true;
      }
    });
    return out;
  }

  /// The replica registry as protocol/sync.md lists it.
  Map<String, Map<String, Object?>> replicaEntries() {
    final checkin = engine.checkin;
    if (checkin == null) return {};
    final out = <String, Map<String, Object?>>{};
    for (final rep in checkin.replicaRegistry()) {
      final entry = <String, Object?>{
        for (final k in const [
          'replica_id',
          'owner_player_id',
          'type',
          'class',
          'make_model',
          'registered_at',
          'tag_type',
          'tag_uid',
        ])
          if (rep[k] != null) k: rep[k],
      };
      try {
        out['${entry['replica_id']}'] = checkReplica(
          Map<String, Object?>.of(entry),
        );
      } on SyncFormatError {
        // Out of protocol/sync.md's form: not sent.
      }
    }
    return out;
  }

  // --- game day ----------------------------------------------------------------

  Future<Map<String, Object?>?> _get(String path, String kind) async {
    pulls++;
    final Map<String, Object?> answer;
    try {
      answer = await transport.get(path);
    } on SyncError catch (e) {
      if (_unsupported.contains(e.status) &&
          _unsupportedCodes.contains(e.code)) {
        gameDaySupported = false;
        return null;
      }
      rethrow;
    }
    gameDaySupported = true;
    try {
      return syncAnswers[kind]!(answer);
    } on SyncFormatError catch (e) {
      throw SyncError('bad_answer', detail: '$e');
    }
  }

  Future<void> _gameDay() async {
    gameDayError = null;
    final sched = await _get(
      '/api/v1/sync/schedule?days=$_scheduleDays',
      'schedule',
    );
    if (sched == null) return;
    final now = _wall();
    schedule?.setSchedule(
      (sched['games']! as List).cast<Map<String, Object?>>(),
      now,
    );
    schedulePulledAt = now;
    await _pullRosters();
    await _answerClaims();
    await _pushCheckins();
  }

  List<(Map<String, Object?>, Map<String, Object?>)> _linked() {
    final s = schedule;
    if (s == null) return const [];
    return [
      for (final link in s.scheduleLinks())
        if (engine.store.game(link['game_id']! as int) case final game?)
          if (game['game_seed'] == link['game_seed']) (link, game),
    ];
  }

  Future<void> _pullRosters() async {
    final checkin = engine.checkin;
    final s = schedule;
    if (checkin == null || s == null) return;
    for (final (link, game) in _linked()) {
      if (game['state'] != 'ready') continue;
      final gid = game['id']! as int, seed = game['game_seed']! as int;
      final Map<String, Object?>? roster;
      try {
        roster = await _get(
          '/api/v1/sync/roster?scheduled_game_id=${link['scheduled_game_id']}',
          'roster',
        );
      } on SyncError catch (e) {
        if (e.status != 404) rethrow;
        s.rosterPulled(gid, seed, _wall(), null, e.code);
        continue; // gone or another field's: the game goes on as it is
      }
      if (roster == null) return;
      if (roster['scheduled_game_id'] != link['scheduled_game_id']) {
        throw SyncError('bad_answer', detail: 'the roster of another game');
      }
      checkin.applyRoster(gid, roster);
      s.rosterPulled(
        gid,
        seed,
        _wall(),
        (roster['registrations']! as List).length,
        null,
      );
    }
  }

  /// Claims of this field's player ids: confirmed when this controller
  /// knows the id with the same secret's hash (in constant time), refused
  /// with another or none, unknown otherwise. The hashes never leave.
  Future<void> _answerClaims() async {
    final claims = await _get('/api/v1/sync/claims', 'claims');
    final list = (claims?['claims'] as List?)?.cast<Map<String, Object?>>();
    if (list == null || list.isEmpty) return;
    final results = <Map<String, Object?>>[];
    for (final c in list) {
      final known = engine.checkin?.fieldPlayer(c['player_id']! as String);
      final String result;
      if (known == null) {
        result = 'unknown';
      } else if (known.secretSha256 == null) {
        result = 'refused';
      } else {
        result = _sameText(known.secretSha256!, c['secret_sha256']! as String)
            ? 'confirmed'
            : 'refused';
      }
      results.add({'claim_id': c['claim_id'], 'result': result});
    }
    final body = checkClaims({...envelope(), 'results': results});
    try {
      await _post('/api/v1/sync/claims', body);
    } on SyncError catch (e) {
      _registryRefused('/api/v1/sync/claims', e);
    }
    claimsAnswered += results.where((r) => r['result'] != 'unknown').length;
  }

  static bool _sameText(String a, String b) {
    if (a.length != b.length) return false;
    var d = 0;
    for (var i = 0; i < a.length; i++) {
      d |= a.codeUnitAt(i) ^ b.codeUnitAt(i);
    }
    return d == 0;
  }

  Future<void> _pushCheckins() async {
    final checkin = engine.checkin;
    if (checkin == null) return;
    final sent = syncItems('checkins');
    for (final (link, game) in _linked()) {
      if (game['state'] != 'ended') continue;
      final gid = game['id']! as int;
      final out = checkin.outcomes(gid);
      final item = '$gid:${game['game_seed']}';
      final sha = digestOf(out);
      if (sha == sent[item]) continue;
      final env = envelope(game);
      final regs = (out['registrations']! as List).cast<Object?>();
      for (var start = 0; start < max(regs.length, 1); start += maxRoster) {
        final body = <String, Object?>{
          ...env,
          'scheduled_game_id': link['scheduled_game_id'],
          'walkins': out['walkins'],
          'registrations': jsonDecode(
            jsonEncode(
              regs.sublist(start, min(start + maxRoster, regs.length)),
            ),
          ),
        };
        try {
          await _bound(game, '/api/v1/sync/checkins', checkCheckins(body));
        } on SyncFormatError {
          // Not in protocol/sync.md's form (the Pi logs it).
        } on SyncError catch (e) {
          if (e.status != 400) rethrow;
        }
      }
      _markSynced('checkins', {item: sha});
    }
  }

  // --- branding and saved teams -----------------------------------------------

  Future<void> _siteBranding() async {
    final branding = engine.branding;
    if (config.branding != 'site' || branding == null) return;
    pulls++;
    Map<String, Object?> answer;
    try {
      answer = await transport.get('/api/v1/sync/field');
    } on SyncError catch (e) {
      if (_unsupported.contains(e.status) &&
          _unsupportedCodes.contains(e.code)) {
        brandingSupported = false;
        return;
      }
      rethrow;
    }
    brandingSupported = true;
    try {
      answer = checkField(answer);
    } on SyncFormatError catch (e) {
      throw SyncError('bad_answer', detail: '$e');
    }
    final wanted = <String, (String, Map<String, Object?>)>{};
    final field = answer['field']! as Map;
    for (final slot in const ['logo', 'wallpaper']) {
      final ref = field[slot];
      if (ref is Map) {
        wanted.putIfAbsent(
          ref['sha256']! as String,
          () => (slot, ref.cast<String, Object?>()),
        );
      }
    }
    for (final team
        in (answer['teams']! as List).cast<Map<String, Object?>>()) {
      final crest = team['crest'];
      if (crest is Map) {
        wanted.putIfAbsent(
          crest['sha256']! as String,
          () => ('crest', crest.cast<String, Object?>()),
        );
      }
    }
    final missing = [
      for (final sha in wanted.keys)
        if (branding.image(sha, withData: false) == null) sha,
    ];
    final failed = <String>{};
    for (final sha in missing.take(_imagesPerCycle)) {
      final (kind, ref) = wanted[sha]!;
      if (!await _fetchImage(branding, sha, kind, ref)) failed.add(sha);
    }
    failed.addAll(missing.skip(_imagesPerCycle));
    brandingError = failed.isEmpty
        ? null
        : '${failed.length} images not fetched yet';
    branding.applySite(answer, unavailable: failed);
    brandingPulledAt = _wall();
  }

  Future<bool> _fetchImage(
    ControllerBranding branding,
    String sha,
    String kind,
    Map<String, Object?> ref,
  ) async {
    pulls++;
    final limits = ImageLimits.kinds[kind]!;
    final Uint8List data;
    try {
      data = await transport.getBytes(
        '/api/v1/sync/images/$sha',
        limits.maxBytes,
      );
    } on SyncError catch (e) {
      if (e.status == 404 || e.code == 'too_large') return false;
      rethrow;
    }
    if (sha256.convert(data).toString() != sha) return false;
    final CheckedImage checked;
    try {
      checked = checkImage(data, ref['content_type'] as String?, limits);
    } on ImageError {
      return false;
    }
    if (checked.data.length != data.length ||
        sha256.convert(checked.data).toString() != sha) {
      return false; // not stripped as this controller strips it
    }
    branding.storeSiteImage(sha, kind, checked);
    imagesFetched++;
    return true;
  }

  // --- the scenario library and presets -------------------------------------

  Map<String, Map<String, String>> _libraryState() {
    Object? state;
    try {
      state = jsonDecode(engine.store.getSetting(_librarySetting) ?? '{}');
    } on FormatException {
      state = <String, Object?>{};
    }
    final m = state is Map ? state : const <String, Object?>{};
    return {
      for (final k in const ['scenarios', 'refused', 'presets'])
        k: (m[k] is Map) ? (m[k] as Map).cast<String, String>() : {},
    };
  }

  Future<void> _siteLibrary() async {
    if (!config.library || engine.scenarios == null) return;
    pulls++;
    Map<String, Object?> answer;
    try {
      answer = await transport.get('/api/v1/sync/presets');
    } on SyncError catch (e) {
      if (_unsupported.contains(e.status) &&
          _unsupportedCodes.contains(e.code)) {
        librarySupported = false;
        return;
      }
      rethrow;
    }
    librarySupported = true;
    try {
      answer = checkPresets(answer);
    } on SyncFormatError catch (e) {
      throw SyncError('bad_answer', detail: '$e');
    }
    final state = _libraryState();
    final problems = <String>[];
    try {
      for (final ref
          in (answer['scenarios']! as List).cast<Map<String, Object?>>()) {
        final sid = ref['scenario_id']! as String,
            sha = ref['sha256']! as String;
        if (sha != state['scenarios']![sid] && sha != state['refused']![sid]) {
          final problem = await _installScenario(sid, sha, state);
          if (problem != null) problems.add('$sid: $problem');
        }
      }
      for (final p
          in (answer['presets']! as List).cast<Map<String, Object?>>()) {
        final sha = digestOf({
          for (final k in const ['name', 'mode_id', 'params']) k: p[k],
        });
        if (state['presets']![p['name']] != sha) {
          final problem = _savePreset(p);
          if (problem != null) {
            problems.add('preset ${p['name']}: $problem');
          } else {
            state['presets']![p['name']! as String] = sha;
          }
        }
      }
    } finally {
      engine.store.setSetting(_librarySetting, _canonical(state));
    }
    final text = problems.join('; ');
    libraryError = text.isEmpty
        ? null
        : (text.length > 500 ? text.substring(0, 500) : text);
    libraryPulledAt = _wall();
  }

  Future<String?> _installScenario(
    String sid,
    String sha,
    Map<String, Map<String, String>> state,
  ) async {
    pulls++;
    Map<String, Object?> body;
    try {
      body = await transport.get('/api/v1/sync/scenarios/$sid');
    } on SyncError catch (e) {
      if (e.status == 404) return 'gone from the site server';
      rethrow;
    }
    try {
      body = checkScenario(body);
    } on SyncFormatError catch (e) {
      throw SyncError('bad_answer', detail: '$e');
    }
    if (body['scenario_id'] != sid || body['sha256'] != sha) {
      return 'changed on the site server while fetched; next cycle';
    }
    try {
      engine.scenarios!.install(body['manifest']! as String);
    } on ScenarioRefused catch (e) {
      state['refused']![sid] = sha;
      return 'refused: ${[for (final p in e.problems) p.message].join('; ')}';
    } on ModeException catch (e) {
      state['refused']![sid] = sha;
      return 'refused: $e';
    } on ControllerError catch (e) {
      final live = engine.liveGame;
      final runs =
          live != null &&
          live['state'] != 'ended' &&
          '${live['mode_id'] ?? ''}'.split(modeSeparator).contains(sid);
      if (!runs && e.status == 409) state['refused']![sid] = sha;
      return e.message;
    }
    state['scenarios']![sid] = sha;
    state['refused']!.remove(sid);
    scenariosInstalled++;
    engine.emit({'type': 'modes'});
    return null;
  }

  String? _savePreset(Map<String, Object?> preset) {
    try {
      final pkg = engine.modes.get(preset['mode_id']);
      if (pkg == null) return 'mode ${preset['mode_id']} is not installed here';
      resolvePresetParams(pkg.mode, preset['params'], null);
      engine.modes.savePreset(
        preset['name']! as String,
        pkg.mode.id,
        (preset['params']! as Map).cast<String, Object?>(),
      );
    } on ModeException catch (e) {
      return '$e';
    } on ControllerError catch (e) {
      return e.message;
    }
    return null;
  }

  // --- what is sent -------------------------------------------------------------

  /// A game's metadata: never its key, assignments or check-ins.
  Map<String, Object?> meta(Map<String, Object?> game) {
    final teams = (game['teams']! as List).cast<String>();
    final info = <String, Object?>{};
    final ti = game['team_info'];
    if (ti is Map) {
      for (final e in ti.entries) {
        if (teams.contains(e.key) && e.value is Map) {
          final entry = e.value as Map;
          final kept = {
            for (final k in const ['display_name', 'crest_id'])
              if (entry[k] != null) k: entry[k],
          };
          if (kept.isNotEmpty) info['${e.key}'] = kept;
        }
      }
    }
    final link = schedule?.scheduleLink(
      game['id']! as int,
      game['game_seed']! as int,
    );
    return {
      'name': game['name'],
      'mode_id': game['mode_id'],
      'teams': teams,
      'team_info': info,
      'params': game['params'] ?? <String, Object?>{},
      'squads': (game['squads'] as int?) ?? 0,
      'duration_ms': (game['duration_ms'] as int?) ?? 0,
      'state': game['state'],
      'node_id': game['node_id'],
      'joined': game['joined'] == true,
      'created_at': game['created_at'],
      'started_at': game['started_at'],
      'ended_at': game['ended_at'],
      'scheduled_game_id': link?['scheduled_game_id'],
    };
  }

  /// The game's score counters per source: each node's as it last
  /// reported them, and each run of this controller's field script,
  /// qualified by this controller's node id (decision S13-3).
  Map<String, Map<String, int>> counters(Map<String, Object?> game) {
    final teams = (game['teams']! as List).toSet();
    Map<String, int> positive(Object? values) => {
      if (values is Map)
        for (final e in values.entries)
          if (teams.contains(e.key) &&
              e.value is int &&
              (e.value as int) > 0 &&
              (e.value as int) < 2147483648)
            '${e.key}': e.value as int,
    };
    final out = <String, Map<String, int>>{};
    for (final node in engine.store.nodes(game['id']! as int)) {
      final v = positive(node['score']);
      if (v.isNotEmpty) out['node-${node['node_id']}'] = v;
    }
    final me = (game['node_id'] as int?) ?? engine.config.nodeId;
    Object? runs;
    try {
      runs = jsonDecode(
        engine.store.getSetting('field_scores:${game['id']}') ?? '{}',
      );
    } on FormatException {
      runs = <String, Object?>{};
    }
    if (runs is Map) {
      for (final e in runs.entries) {
        final v = positive(e.value);
        if (_fieldRun.hasMatch('${e.key}') && v.isNotEmpty) {
          out['${e.key}@$me'] = v;
        }
      }
    }
    return out;
  }

  /// The game's nodes: name, role, last seen and the health fields of
  /// protocol/sync.md only. A capability goes as its id's text (decision
  /// PE24-121: the HELLO's ids are integers, the format's texts).
  List<Map<String, Object?>> nodes(Map<String, Object?> game) {
    final out = <Map<String, Object?>>[];
    for (final node in engine.store.nodes(game['id']! as int)) {
      final info = <String, Object?>{
        for (final k in nodeInfoKinds.keys)
          if (node.containsKey(k)) k: node[k],
      };
      final caps = info['capabilities'];
      if (caps is List) info['capabilities'] = [for (final c in caps) '$c'];
      final entry = <String, Object?>{
        'node_id': node['node_id'],
        'name': node['name'],
        'role': node['role'],
        'last_seen': node['last_seen'],
        'info': info,
      };
      try {
        checkNodes(
          jsonDecode(
            jsonEncode({
              ...envelope(game),
              'nodes': [entry],
            }),
          ),
        );
      } on SyncFormatError {
        continue; // not sent (the Pi logs it)
      }
      out.add(entry);
    }
    return out;
  }

  // --- status --------------------------------------------------------------

  Map<String, Object?> status() {
    var pending = 0;
    for (final game in engine.store.games()) {
      final st = syncState(game['id']! as int, game['game_seed']! as int);
      if (st['final'] != true) {
        pending += _eventsAfter(
          game['id']! as int,
          st['acked_id']! as int,
        ).length;
      }
    }
    final sent = syncItems('reading');
    final readings = engine.checkin?.storedReadings() ?? const [];
    final lib = _libraryState();
    return {
      'enabled': true,
      'url': config.url,
      'key': 'stored',
      'key_fingerprint': keyFingerprintText,
      'controller_id': controllerId,
      'last_ok_at': lastOkAt,
      'last_attempt_at': lastAttemptAt,
      'last_error': lastError,
      'failures': failures,
      'pending_events': pending,
      'pending_readings': readings
          .where((r) => !sent.containsKey(r['reading_id']))
          .length,
      'registry_error': registryError,
      'refused_readings': refusedReadings,
      'game_day': {
        'supported': gameDaySupported,
        'schedule_pulled_at': schedulePulledAt,
        'linked_games': schedule?.scheduleLinks().length ?? 0,
        'claims_answered': claimsAnswered,
      },
      'branding': {
        'source': config.branding,
        'supported': brandingSupported,
        'pulled_at': brandingPulledAt,
        'error': brandingError,
        'images_fetched': imagesFetched,
      },
      'remote_gm': remoteStatus?.call() ?? {'enabled': false},
      'library': {
        'enabled': config.library,
        'supported': librarySupported,
        'pulled_at': libraryPulledAt,
        'error': libraryError,
        'scenarios_installed': scenariosInstalled,
        'from_site': {
          for (final e in lib.entries) e.key: e.value.keys.toList()..sort(),
        },
      },
    };
  }
}
