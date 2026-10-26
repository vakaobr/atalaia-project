// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The site sync on the phone (lib/controller/controller_sync.dart, PE24
// slice S7) end to end against a small site server in this process, over
// real HTTP on the loopback address: the cases of the Pi's
// controller/tests/test_sync_client.py, test_sync_schedule.py,
// test_sync_branding.py and test_sync_library.py that are not Python's own
// (its thread, its TOML, its CLI). The fake site checks every body with the
// shared format (controller_sync_format.dart, the same rules the real site
// server applies) and merges events and counters by the real rules.

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/chrono/reading.dart';
import 'package:atalaia_app/chrono/record_signer.dart';
import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_branding.dart';
import 'package:atalaia_app/controller/controller_checkin.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_images.dart';
import 'package:atalaia_app/controller/controller_positions.dart';
import 'package:atalaia_app/controller/controller_scenarios.dart';
import 'package:atalaia_app/controller/controller_schedule.dart';
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:atalaia_app/controller/controller_sync.dart';
import 'package:atalaia_app/controller/controller_sync_format.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/recording_radio.dart';
import '../support/vectors.dart';

final key = 'k' * 43;
const domination = 'org.atalaia.domination';
const t0 = 1800007200.0;
const scheduledId = '5a5a5a5a-1111-4222-8333-444455556666';

Uint8List _unhex(String s) => Uint8List.fromList([
  for (var i = 0; i < s.length; i += 2)
    int.parse(s.substring(i, i + 2), radix: 16),
]);

/// A site server's sync endpoints in memory, with the real merge rules and
/// switches for failures (the Pi's tests' FakeSite).
class FakeSite {
  late HttpServer server;
  final requests = <(String, String, HttpHeaders, Map<String, Object?>?)>[];
  final games = <(int, int), Map<String, Object?>>{};
  final events =
      <
        (int, int),
        Map<(Object?, Object?, Object?, Object?), Map<String, Object?>>
      >{};
  final counters = <(int, int), Map<String, Map<String, int>>>{};
  final marshals = <(Object?, Object?), Map<String, Object?>>{};
  final replicas = <Object?, Map<String, Object?>>{};
  final readings = <Map<String, Object?>>[];
  final checkins = <Map<String, Object?>>[];
  final claimResults = <Map<String, Object?>>[];

  /// Answers to give first: (status, body, headers).
  final fail = <(int, Map<String, Object?>, Map<String, String>)>[];
  String? lose, reject;
  String? redirectTo;
  final refuseReadings = <String>{};

  /// GET answers by path (without the query); null: 404 Not Found.
  final gets = <String, Object?>{};
  final images = <String, Uint8List>{};

  String get url => 'http://127.0.0.1:${server.port}';

  Future<void> start() async {
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen(_serve);
  }

  Future<void> close() => server.close(force: true);

  Future<void> _serve(HttpRequest req) async {
    final raw = await req.fold<List<int>>([], (a, b) => a..addAll(b));
    final body = raw.isEmpty
        ? null
        : (jsonDecode(utf8.decode(raw)) as Map).cast<String, Object?>();
    requests.add((req.method, req.uri.path, req.headers, body));
    final (status, answer, headers) = _handle(req, body);
    req.response.statusCode = status;
    headers.forEach(req.response.headers.set);
    if (answer is Uint8List) {
      req.response.headers.contentType = ContentType('image', 'png');
      req.response.add(answer);
    } else {
      req.response.headers.contentType = ContentType.json;
      req.response.write(jsonEncode(answer));
    }
    await req.response.close();
  }

  (int, Object?, Map<String, String>) _handle(
    HttpRequest req,
    Map<String, Object?>? body,
  ) {
    final path = req.uri.path;
    if (redirectTo != null) {
      return (307, <String, Object?>{}, {'Location': '$redirectTo$path'});
    }
    if (req.headers.value('authorization') != 'Bearer $key') {
      return (401, {'detail': 'invalid_api_key'}, {});
    }
    if (fail.isNotEmpty) return fail.removeAt(0);
    if (req.method == 'GET') {
      if (path.startsWith('/api/v1/sync/images/')) {
        final img = images[path.split('/').last];
        return img == null
            ? (404, {'detail': 'image_not_found'}, {})
            : (200, img, {});
      }
      if (!gets.containsKey(path) || gets[path] == null) {
        return (404, {'detail': 'Not Found'}, {});
      }
      return (200, gets[path], {});
    }
    final kind = path.split('/').last;
    if (reject == kind) {
      reject = null;
      return (
        400,
        {'detail': 'invalid_body', 'error': 'bad_source', 'path': 'counters.x'},
        {},
      );
    }
    Map<String, Object?> checked;
    try {
      checked = syncChecks[kind]!(jsonDecode(jsonEncode(body)));
    } on SyncFormatError catch (e) {
      return (
        400,
        {'detail': 'invalid_body', 'error': e.code, 'path': e.path},
        {},
      );
    }
    if (!gameKinds.contains(kind)) return (200, _registry(kind, checked), {});
    final g = checked['game']! as Map;
    final game = (g['game_id']! as int, g['game_seed']! as int);
    if (kind != 'games' && !games.containsKey(game)) {
      return (404, {'detail': 'game_not_found'}, {});
    }
    Map<String, Object?> answer;
    switch (kind) {
      case 'games':
        games[game] = (checked['meta']! as Map).cast<String, Object?>();
        answer = {'game': 'g-${game.$1}', 'created': true};
      case 'events':
        final log = events.putIfAbsent(game, () => {});
        var inserted = 0;
        final list = (checked['events']! as List).cast<Map<String, Object?>>();
        for (final ev in list) {
          final k = (ev['node'], ev['seq'], ev['t'], ev['type']);
          if (!log.containsKey(k)) {
            log[k] = ev;
            inserted++;
          }
        }
        answer = {
          'acked_id': list.last['id'],
          'inserted': inserted,
          'duplicates': list.length - inserted,
        };
      case 'scores':
        counters[game] = mergeCounters(counters[game] ?? {}, {
          for (final e in (checked['counters']! as Map).entries)
            '${e.key}': (e.value as Map).cast<String, int>(),
        });
        answer = {'totals': totals(game), 'updated': 0};
      case 'checkins':
        checkins.add(checked);
        answer = {
          'linked': true,
          'applied': 0,
          'ignored': 0,
          'declarations': 0,
        };
      default:
        answer = {'nodes': (checked['nodes']! as List).length};
    }
    if (lose == kind) {
      lose = null;
      return (500, {'detail': 'internal'}, {});
    }
    return (200, answer, {});
  }

  Map<String, Object?> _registry(String kind, Map<String, Object?> body) {
    switch (kind) {
      case 'marshals':
        for (final m
            in (body['marshals']! as List).cast<Map<String, Object?>>()) {
          marshals[(m['marshal_id'], m['public_key'])] = m;
        }
        return {'marshals': (body['marshals']! as List).length, 'added': 0};
      case 'replicas':
        for (final r
            in (body['replicas']! as List).cast<Map<String, Object?>>()) {
          replicas[r['replica_id']] = r;
        }
        return {'replicas': (body['replicas']! as List).length};
      case 'claims':
        claimResults.addAll(
          (body['results']! as List).cast<Map<String, Object?>>(),
        );
        return {'confirmed': 0, 'refused': 0, 'pending': 0};
    }
    final refused = <Map<String, Object?>>[];
    final list = (body['readings']! as List).cast<Map<String, Object?>>();
    for (var i = 0; i < list.length; i++) {
      final rid =
          (jsonDecode(list[i]['record']! as String) as Map)['reading_id'];
      if (refuseReadings.contains(rid)) {
        refused.add({'index': i, 'reading_id': rid, 'reason': 'signature'});
      } else {
        readings.add(list[i]);
      }
    }
    return {
      'accepted': list.length - refused.length,
      'duplicates': 0,
      'refused': refused,
      'violations': 0,
    };
  }

  Map<String, int> totals((int, int) game) {
    final deltas = [
      for (final e in events[game]?.values ?? const <Map<String, Object?>>[])
        if (e['type'] == 'score.delta')
          (
            ((e['data']! as Map)['team'] ?? e['team'])! as String,
            (e['data']! as Map)['amount']! as int,
          ),
    ];
    return syncTotals(
      (games[game]!['teams']! as List).cast<String>(),
      counters[game] ?? {},
      deltas,
    );
  }

  List<String> paths() => [
    for (final r in requests)
      if (r.$1 == 'POST') r.$2.split('/').last,
  ];

  List<Map<String, Object?>> bodies(String kind) => [
    for (final r in requests)
      if (r.$1 == 'POST' && r.$2.endsWith('/$kind')) r.$4!,
  ];
}

void main() {
  late AtalaiaCore core;
  final limits = File(
    'lib/chrono/limit_templates/portugal.yaml',
  ).readAsStringSync();
  final fixtures =
      (loadVectors('controller_api.json')['fixtures']! as Map)['values']!
          as Map;
  final crestPng = _unhex(fixtures['crest_png_hex']! as String);
  final manifest =
      ((loadVectors('scenario_compile.json')['compile']! as List).first
              as Map)['manifest_text']!
          as String;

  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  late FakeSite site;
  late double wall;
  late Directory dir;
  late ControllerEngine engine;
  late ControllerCheckin checkin;
  late ControllerSchedule schedule;
  late ControllerApi api;
  final clients = <ControllerSync>[];

  ControllerEngine boot() {
    final e = ControllerEngine(
      store: FileControllerStore(dir),
      core: core,
      transport: RecordingRadio(),
      wallSeconds: () => wall,
    );
    checkin = ControllerCheckin(
      e,
      CheckinConfig(limitsYaml: limits, utcDay: true),
    );
    ControllerPositions(e);
    ControllerScenarios(e);
    ControllerBranding(e);
    schedule = ControllerSchedule(e);
    api = ControllerApi(e, gmToken: 'g', readToken: 'r');
    return e;
  }

  setUp(() async {
    wall = t0;
    dir = Directory.systemTemp.createTempSync('atalaia-sync-');
    site = FakeSite();
    await site.start();
    engine = boot();
  });

  tearDown(() async {
    for (final c in clients) {
      await c.stop();
    }
    clients.clear();
    engine.close();
    await site.close();
    dir.deleteSync(recursive: true);
  });

  ControllerSync client({
    String branding = 'local',
    bool library = false,
    String? url,
  }) {
    final c = ControllerSync(
      engine,
      SyncConfig(
        url: url ?? site.url,
        apiKey: key,
        timeoutS: 10,
        branding: branding,
        library: library,
      ),
      schedule: schedule,
      wall: () => wall,
    );
    clients.add(c);
    return c;
  }

  int play({bool end = true, int captures = 3}) {
    final gid =
        engine.createGame({
              'name': 'Domingo',
              'mode_id': domination,
              'teams': ['red', 'blue'],
              'assignments': {'3': 'zone'},
            })['id']!
            as int;
    engine
      ..startGame(gid, force: true)
      ..onPacket(
        RfHeader.v1(
          gameId: gid,
          source: 3,
          seq: 1,
          hopLimit: 2,
          type: RfType.state,
        ),
        const RfState(
          ownerTeam: 1,
          phase: 1,
          gameTimeMs: 0,
          counters: {1: 100},
          epoch: 1,
        ).encode(),
      );
    for (var seq = 1; seq <= captures; seq++) {
      engine.logControllerEvent(gid, 'zone.captured', {'zone': 'alpha'});
    }
    engine.adjustScore(gid, 'red', -30, 'penalty');
    if (end) engine.endGame(gid);
    return gid;
  }

  int seedOf(int gid) => engine.store.game(gid)!['game_seed']! as int;

  group('games', () {
    test(
      'a game in its log\'s order with its cursor; ended, it is final',
      () async {
        final gid = play();
        final c = client();
        expect(await c.runOnce(), isTrue, reason: c.lastError);
        expect(site.paths(), ['games', 'events', 'scores', 'nodes']);
        final sent = site.bodies('events').single;
        final ids = [for (final e in sent['events']! as List) (e as Map)['id']];
        expect(ids, [for (var i = 1; i <= ids.length; i++) i]);
        expect(sent['after_id'], 0);
        final st = c.syncState(gid, seedOf(gid));
        expect(st['acked_id'], ids.last);
        expect(st['final'], isTrue);
        final game = (gid, seedOf(gid));
        expect(site.events[game]!.length, engine.store.eventLog(gid).length);
        expect(site.totals(game), engine.score(gid)['teams']);
        expect(site.games[game]!['state'], 'ended');
        expect(site.games[game]!['node_id'], 0);
        // Never in the metadata: the key, assignments, check-ins.
        expect(site.games[game]!.keys, isNot(contains('assignments')));
      },
    );

    test('a restart sends nothing again', () async {
      play();
      expect(await client().runOnce(), isTrue);
      final n = site.requests.length;
      engine.close();
      engine = boot();
      final again = client();
      expect(await again.runOnce(), isTrue);
      expect((site.paths().length, again.requests), (site.paths().length, 0));
      expect(
        site.requests.where((r) => r.$1 == 'POST').length,
        lessThanOrEqualTo(n),
      );
    });

    test('only the new events of a live game', () async {
      final gid = play(end: false);
      final c = client();
      await c.runOnce();
      final first = c.syncState(gid, seedOf(gid))['acked_id'];
      expect(c.syncState(gid, seedOf(gid))['final'], isFalse);
      engine.logControllerEvent(gid, 'zone.captured', {'zone': 'bravo'});
      site.requests.clear();
      await c.runOnce();
      expect(site.paths(), ['events']);
      final body = site.bodies('events').single;
      expect(body['after_id'], first);
      expect((body['events']! as List).length, 1);
    });

    test('a lost answer: sent again, counted twice nowhere', () async {
      final gid = play();
      site.lose = 'events';
      final c = client();
      expect(await c.runOnce(), isFalse);
      expect(c.syncState(gid, seedOf(gid))['acked_id'], 0);
      expect(await c.runOnce(), isTrue);
      final game = (gid, seedOf(gid));
      expect(site.events[game]!.length, engine.store.eventLog(gid).length);
      expect(site.totals(game), engine.score(gid)['teams']);
      final batches = site.bodies('events');
      expect(batches, hasLength(2));
      expect(
        jsonEncode(batches[0]['events']),
        jsonEncode(batches[1]['events']),
      );
    });

    test('big logs go in batches of 500', () async {
      final gid = play(captures: maxEvents + 20);
      expect(await client().runOnce(), isTrue);
      final batches = site.bodies('events');
      expect(
        [for (final b in batches) (b['events']! as List).length],
        [500, engine.store.eventLog(gid).length - 500],
      );
      expect(batches[1]['after_id'], 500);
    });

    test('a game the site server lost is sent again first', () async {
      final gid = play(end: false);
      final c = client();
      await c.runOnce();
      site.games.clear();
      engine.logControllerEvent(gid, 'zone.captured', {});
      site.requests.clear();
      expect(await c.runOnce(), isTrue);
      expect(site.paths(), ['events', 'games', 'events']);
    });

    test('an event out of form is skipped, never stuck', () async {
      final gid = play(end: false);
      engine.store
        ..insertEvent(gid, {
          'node': 3,
          'seq': 50,
          't': 50,
          'type': 'zone.captured',
          'prio': 'normal',
          'data': {'lat': 38.7},
        })
        ..insertEvent(gid, {
          'node': 3,
          'seq': 51,
          't': 51,
          'type': 'zone.captured',
          'prio': 'normal',
          'data': <String, Object?>{},
        });
      final c = client();
      expect(await c.runOnce(), isTrue);
      expect(c.syncState(gid, seedOf(gid))['skipped'], 1);
      final seqs = [
        for (final b in site.bodies('events'))
          for (final e in b['events']! as List) (e as Map)['seq'],
      ];
      expect(seqs, contains(51));
      expect(seqs, isNot(contains(50)));
      expect(c.status()['pending_events'], 0);
    });

    test('a refused body does not hold up the rest', () async {
      final first = play();
      final second = play();
      site.reject = 'scores';
      final c = client();
      expect(await c.runOnce(), isTrue);
      expect(
        c.syncState(first, seedOf(first))['last_error'],
        contains('bad_source'),
      );
      expect(c.syncState(second, seedOf(second))['final'], isTrue);
    });

    test('a box that said HELLO goes with its capabilities as texts '
        '(PE24-121)', () async {
      final gid = play(end: false);
      engine.store.upsertNode(gid, {
        'node_id': 3,
        'name': 'alpha',
        'role': 'zone',
        'platform': 0,
        'fw_version': '1.2.0',
        'tier': 0,
        'capabilities': [1, 4],
        'score': {'red': 7},
        'device_id': 'aabbccdd',
      });
      expect(await client().runOnce(), isTrue);
      final nodes = site.bodies('nodes').last['nodes']! as List;
      final info = (nodes.single as Map)['info']! as Map;
      expect(info['capabilities'], ['1', '4']);
      expect(info, isNot(contains('device_id')));
      expect(site.bodies('scores').last['counters'], {
        'node-3': {'red': 7},
      });
    });
  });

  group('the link', () {
    test(
      'network errors keep everything for later; the wait doubles',
      () async {
        final gid = play();
        final c = client(url: 'http://127.0.0.1:1');
        expect(await c.runOnce(), isFalse);
        expect(c.lastError, 'unreachable');
        expect(c.syncState(gid, seedOf(gid))['acked_id'], 0);
        expect(c.nextDelay(), 300); // idle: 5 min
        expect(c.status()['pending_events'], engine.store.eventLog(gid).length);
      },
    );

    test('intervals: 30 s while a game runs, doubling up to 5 min', () async {
      play(end: false);
      final c = client();
      expect(c.nextDelay(), 30);
      c.failures = 1;
      expect(c.nextDelay(), 60);
      c.failures = 5;
      expect(c.nextDelay(), 300);
    });

    test('a refused key and Retry-After', () async {
      play();
      site.fail.add((429, {'detail': 'rate_limited'}, {'Retry-After': '900'}));
      final c = client();
      expect(await c.runOnce(), isFalse);
      expect(
        (c.lastError, c.retryAfter, c.nextDelay()),
        ('rate_limited', 900, 900),
      );
      site.fail.add((401, {'detail': 'invalid_api_key'}, {}));
      expect(await c.runOnce(), isFalse);
      expect(c.lastError, 'invalid_api_key');
    });

    test('redirects are not followed: the key goes nowhere else', () async {
      final other = FakeSite();
      await other.start();
      addTearDown(other.close);
      play();
      site.redirectTo = other.url;
      final c = client();
      expect(await c.runOnce(), isFalse);
      expect(c.lastError, 'http_307');
      expect(other.requests, isEmpty);
    });

    test('headers: the key, JSON, the app', () async {
      play();
      await client().runOnce();
      final h = site.requests.first.$3;
      expect(h.value('authorization'), 'Bearer $key');
      expect(h.contentType?.mimeType, 'application/json');
      expect(h.value('user-agent'), startsWith('atalaia-controller/'));
    });

    test('addresses and keys', () {
      expect(syncUrlProblem('https://site.example.org'), isNull);
      expect(syncUrlProblem('http://127.0.0.1:8080'), isNull);
      expect(syncUrlProblem('http://site.example.org'), contains('https://'));
      expect(syncUrlProblem('https://u:p@site.example.org'), isNotNull);
      expect(syncUrlProblem('ftp://x'), isNotNull);
      expect(apiKeyOk(key), isTrue);
      expect(apiKeyOk('k' * 42), isFalse);
      expect(
        keyFingerprint(key),
        sha256.convert(ascii.encode(key)).toString().substring(0, 8),
      );
      final cfg = SyncConfig(url: site.url, apiKey: key, branding: 'site');
      expect(SyncConfig.fromJson(cfg.toJson())!.toJson(), cfg.toJson());
      expect(cfg.problem(), isNull);
      expect(
        SyncConfig(url: site.url, apiKey: 'x').problem(),
        contains('api_key'),
      );
    });

    test('the game never waits for the network', () async {
      final gid = play(end: false);
      final c = client(url: 'http://127.0.0.1:1')..start();
      engine.logControllerEvent(gid, 'zone.captured', {});
      engine.tick();
      expect(engine.endGame(gid)['state'], 'ended');
      await c.stop();
    });

    test('the controller\'s state shows the sync', () async {
      play();
      final c = client();
      await c.runOnce();
      final st = engine.status()['sync']! as Map;
      expect(st['enabled'], isTrue);
      expect(st['key_fingerprint'], keyFingerprint(key));
      expect(st['controller_id'], c.controllerId);
      expect(st['last_error'], isNull);
      expect(st['pending_events'], 0);
    });
  });

  group('the chrono registry', () {
    const replica = '22222222-2222-4222-8222-222222222222';

    Future<String> reading(MarshalKey k, String pid, double v) async {
      final r = await signReading(
        ChronoReading.measure(
          replicaId: replica,
          playerId: pid,
          type: ReadingType.checkin,
          velocityMps: v,
          bbWeightG: 0.2,
          chronoId: 'chrono-1',
          marshalId: 'm-ana',
          marshalName: 'Ana',
          fieldId: 'field',
          timestamp: DateTime.utc(2027, 1, 15, 10),
        ),
        k,
      );
      final resp = await api.handleAsync(
        'POST',
        Uri.parse('/api/v1/chrono/readings'),
        authorization: 'Bearer g',
        body: jsonEncode({
          'readings': [r.toJson()],
          'replica': {
            'replica_id': replica,
            'owner_player_id': pid,
            'type': 'aeg',
            'class': 'rifle',
            'registered_at': '2027-01-01T10:00:00Z',
          },
        }),
      );
      expect(resp.status, 200, reason: '${resp.body}');
      return r.readingId;
    }

    test('keys, then replicas, then readings, each once; a rotated key keeps '
        'its period', () async {
      final k1 = await MarshalKey.fromSeed(List.filled(32, 7));
      final k2 = await MarshalKey.fromSeed(List.filled(32, 8));
      checkin.addMarshal({
        'marshal_id': 'm-ana',
        'name': 'Ana',
        'public_key': base64.encode(k1.publicKey),
      });
      final first = await reading(k1, 'p-aaaaaaaaaaaa', 90);
      wall += 100;
      checkin.addMarshal({
        'marshal_id': 'm-ana',
        'name': 'Ana',
        'public_key': base64.encode(k2.publicKey),
      });
      site.refuseReadings.add(first);
      await reading(k2, 'p-aaaaaaaaaaaa', 91);
      final c = client();
      expect(await c.runOnce(), isTrue, reason: c.lastError);
      expect(site.paths(), ['marshals', 'replicas', 'chrono']);
      final keys = site.bodies('marshals').single['marshals']! as List;
      expect(keys, hasLength(2));
      final old = keys.cast<Map<String, Object?>>().firstWhere(
        (m) => m['public_key'] == base64.encode(k1.publicKey),
      );
      expect((old['registered_at'], old['replaced_at']), (t0, t0 + 100));
      expect(site.replicas.keys, [replica]);
      expect(site.readings, hasLength(1));
      expect(c.refusedReadings, 1);
      site.requests.clear();
      expect(await c.runOnce(), isTrue);
      expect(site.paths(), isEmpty); // nothing new
      expect(c.status()['pending_readings'], 0);
    });
  });

  group('game day', () {
    Map<String, Object?> scheduled({String status = 'published'}) => {
      'sync_version': 1,
      'games': [
        {
          'scheduled_game_id': scheduledId,
          'title': 'Domingo de manhã',
          'starts_at': t0 + 3600,
          'ends_at': t0 + 3600 + 7200,
          'status': status,
          'teams': ['red', 'blue'],
          'federation': 'off',
          'predeclare_replicas': true,
          'registered': 2,
          'mode_id': domination,
        },
      ],
    };

    Map<String, Object?> roster() => {
      'sync_version': 1,
      'scheduled_game_id': scheduledId,
      'status': 'published',
      'federation': 'off',
      'registrations': [
        {
          'registration_id': '7a000000-0000-4000-8000-000000000001',
          'player_id': 'p-aaaaaaaaaaaa',
          'display_name': 'Falcão',
          'team_preference': 'red',
          'ticket_sha256': sha256.convert(List.filled(32, 9)).toString(),
          'replicas': [
            {
              'declaration_id': '7d000000-0000-4000-8000-000000000001',
              'type': 'aeg',
              'class': 'rifle',
            },
          ],
        },
        {
          'registration_id': '7a000000-0000-4000-8000-000000000002',
          'player_id': 'p-bbbbbbbbbbbb',
          'display_name': 'Corvo',
          'replicas': <Object?>[],
        },
      ],
    };

    test('the schedule, a game made from it, its roster until the start, '
        'claims, and the outcomes after the end', () async {
      site.gets['/api/v1/sync/schedule'] = scheduled();
      site.gets['/api/v1/sync/claims'] = {
        'sync_version': 1,
        'claims': <Object?>[],
      };
      final c = client();
      expect(await c.runOnce(), isTrue, reason: c.lastError);
      final view = api.handle(
        'GET',
        Uri.parse('/api/v1/schedule'),
        authorization: 'Bearer r',
      );
      expect(view.status, 200);
      final sgames = (view.body! as Map)['games']! as List;
      expect((sgames.single as Map)['title'], 'Domingo de manhã');
      expect((view.body! as Map)['enabled'], isTrue);
      final made = api.handle(
        'POST',
        Uri.parse('/api/v1/schedule/$scheduledId/game'),
        authorization: 'Bearer g',
        body: '{}',
      );
      expect(made.status, 201, reason: '${made.body}');
      final game = made.body! as Map;
      expect(
        (game['name'], game['mode_id'], game['duration_ms']),
        ('Domingo de manhã', domination, 7200000),
      );
      final gid = game['id']! as int;
      site.gets['/api/v1/sync/roster'] = roster();
      expect(await c.runOnce(), isTrue, reason: c.lastError);
      final list = checkin.listCheckins(ApiViewer.gm, gid);
      final rows = (list['checkins']! as List).cast<Map<String, Object?>>();
      expect(rows.map((r) => r['status']), ['expected', 'expected']);
      expect(site.games[(gid, seedOf(gid))]!['scheduled_game_id'], scheduledId);
      // A player who arrives; the other never does.
      api.handle(
        'POST',
        Uri.parse('/api/v1/games/$gid/checkin/open'),
        authorization: 'Bearer g',
        body: '{}',
      );
      final r = api.handle(
        'POST',
        Uri.parse('/api/v1/checkin'),
        body: jsonEncode({
          'game_id': gid,
          'player_id': 'p-aaaaaaaaaaaa',
          'player_secret': base64Url
              .encode(List.filled(32, 1))
              .replaceAll('=', ''),
          'display_name': 'Falcão',
          'notice_version': 1,
          'registration_id': '7a000000-0000-4000-8000-000000000001',
          'ticket': base64Url.encode(List.filled(32, 9)).replaceAll('=', ''),
        }),
      );
      expect(r.status, 201, reason: '${r.body}');
      engine.startGame(gid, force: true);
      // After the start the roster is never applied again.
      site.gets['/api/v1/sync/roster'] = {
        ...roster(),
        'registrations': <Object?>[],
      };
      // Claims: one this controller knows with the same secret, one with
      // another, one it never saw.
      final secretSha = sha256
          .convert(
            utf8.encode(
              base64Url.encode(List.filled(32, 1)).replaceAll('=', ''),
            ),
          )
          .toString();
      site.gets['/api/v1/sync/claims'] = {
        'sync_version': 1,
        'claims': [
          {
            'claim_id': 'c1000000-0000-4000-8000-000000000001',
            'player_id': 'p-aaaaaaaaaaaa',
            'secret_sha256': checkin
                .fieldPlayer('p-aaaaaaaaaaaa')!
                .secretSha256,
          },
          {
            'claim_id': 'c1000000-0000-4000-8000-000000000002',
            'player_id': 'p-aaaaaaaaaaaa',
            'secret_sha256': 'f' * 64,
          },
          {
            'claim_id': 'c1000000-0000-4000-8000-000000000003',
            'player_id': 'p-cccccccccccc',
            'secret_sha256': secretSha,
          },
        ],
      };
      expect(await c.runOnce(), isTrue, reason: c.lastError);
      expect(checkin.listCheckins(ApiViewer.gm, gid)['checkins'], hasLength(2));
      expect(site.claimResults.map((x) => x['result']), [
        'confirmed',
        'refused',
        'unknown',
      ]);
      engine.endGame(gid);
      site.gets['/api/v1/sync/claims'] = {
        'sync_version': 1,
        'claims': <Object?>[],
      };
      expect(await c.runOnce(), isTrue, reason: c.lastError);
      final out = site.checkins.single;
      expect(out['walkins'], 0);
      final regs = (out['registrations']! as List).cast<Map<String, Object?>>();
      expect(
        {for (final x in regs) x['player_id']: x['outcome']},
        {'p-aaaaaaaaaaaa': 'checked_in', 'p-bbbbbbbbbbbb': 'no_show'},
      );
      // No names, ever.
      expect(jsonEncode(out), isNot(contains('Falcão')));
      site.requests.clear();
      await c.runOnce();
      expect(site.paths(), isNot(contains('checkins'))); // sent once
    });

    test('a site server without game day is skipped quietly', () async {
      play();
      final c = client();
      expect(await c.runOnce(), isTrue);
      expect(c.status()['game_day'], containsPair('supported', false));
    });

    test('a cancelled scheduled game makes no game', () async {
      site.gets['/api/v1/sync/schedule'] = scheduled(status: 'cancelled');
      site.gets['/api/v1/sync/claims'] = {
        'sync_version': 1,
        'claims': <Object?>[],
      };
      await client().runOnce();
      expect(
        api
            .handle(
              'POST',
              Uri.parse('/api/v1/schedule/$scheduledId/game'),
              authorization: 'Bearer g',
              body: '{}',
            )
            .status,
        409,
      );
    });
  });

  group('branding from the site', () {
    test('the field\'s branding and saved teams, images by SHA-256; the '
        'console may not change them', () async {
      final checked = checkImage(crestPng, 'image/png', ImageLimits.crest);
      final sha = sha256.convert(checked.data).toString();
      site.images[sha] = checked.data;
      Map<String, Object?> ref() => {
        'sha256': sha,
        'content_type': 'image/png',
        'width': checked.width,
        'height': checked.height,
        'bytes': checked.data.length,
      };
      site.gets['/api/v1/sync/field'] = {
        'sync_version': 1,
        'field': {
          'field_name': 'Campo do Sul',
          'accent': '#123456',
          'logo': ref(),
          'wallpaper': null,
        },
        'teams': [
          {
            'team_id': '0e000000-0000-4000-8000-000000000001',
            'name': 'Lobos',
            'colour': 'red',
            'crest': ref(),
            'club': {'slug': 'lobos', 'name': 'Clube Lobos'},
          },
        ],
      };
      final c = client(branding: 'site');
      expect(await c.runOnce(), isTrue, reason: c.lastError);
      final b = engine.branding!;
      expect(b.view()['field_name'], 'Campo do Sul');
      expect(b.view()['accent'], '#123456');
      expect((b.view()['logo']! as Map)['id'], sha);
      final presets = b.teamPresets();
      expect(presets.single['name'], 'Lobos');
      expect(presets.single['source'], 'site');
      expect(c.imagesFetched, 1);
      final put = api.handle(
        'PUT',
        Uri.parse('/api/v1/field/branding'),
        authorization: 'Bearer g',
        body: jsonEncode({'accent': '#000000'}),
      );
      expect(put.status, 409);
      // The team gone from the site goes here too.
      (site.gets['/api/v1/sync/field']! as Map)['teams'] = <Object?>[];
      expect(await c.runOnce(), isTrue);
      expect(b.teamPresets(), isEmpty);
    });

    test('an image that does not hash to its name is refused', () async {
      final checked = checkImage(crestPng, 'image/png', ImageLimits.crest);
      final sha = sha256.convert(checked.data).toString();
      site.images[sha] = Uint8List.fromList([...checked.data, 0]);
      site.gets['/api/v1/sync/field'] = {
        'sync_version': 1,
        'field': {
          'logo': {
            'sha256': sha,
            'content_type': 'image/png',
            'width': checked.width,
            'height': checked.height,
            'bytes': checked.data.length,
          },
        },
        'teams': <Object?>[],
      };
      final c = client(branding: 'site');
      expect(await c.runOnce(), isTrue);
      expect(engine.branding!.view()['logo'], isNull);
      expect(c.brandingError, '1 images not fetched yet');
    });
  });

  group('the library', () {
    test('a scenario installed from the site once, a preset saved; a refused '
        'manifest is not fetched again', () async {
      final sha = sha256.convert(utf8.encode(manifest)).toString();
      site.gets['/api/v1/sync/presets'] = {
        'sync_version': 1,
        'scenarios': [
          {
            'scenario_id': 'org.club.vectors',
            'revision': 1,
            'version': '1.0.0',
            'name': 'Vectors',
            'sha256': sha,
          },
          {
            'scenario_id': 'org.club.broken',
            'revision': 1,
            'version': '1.0.0',
            'name': 'Broken',
            'sha256': sha256.convert(utf8.encode('id: x')).toString(),
          },
        ],
        'presets': [
          {
            'preset_id': '9e000000-0000-4000-8000-000000000001',
            'name': 'Domingo curto',
            'mode_id': domination,
            'params': <String, Object?>{},
          },
        ],
      };
      site.gets['/api/v1/sync/scenarios/org.club.vectors'] = {
        'sync_version': 1,
        'scenario_id': 'org.club.vectors',
        'revision': 1,
        'sha256': sha,
        'manifest': manifest,
      };
      site.gets['/api/v1/sync/scenarios/org.club.broken'] = {
        'sync_version': 1,
        'scenario_id': 'org.club.broken',
        'revision': 1,
        'sha256': sha256.convert(utf8.encode('id: x')).toString(),
        'manifest': 'id: x',
      };
      final c = client(library: true);
      expect(await c.runOnce(), isTrue, reason: c.lastError);
      expect(c.scenariosInstalled, 1);
      expect(engine.modes.package('org.club.vectors'), isNotNull);
      expect(
        engine.modes.presets().map((p) => p['name']),
        contains('Domingo curto'),
      );
      expect(c.libraryError, contains('org.club.broken'));
      site.requests.clear();
      await c.runOnce();
      expect(
        site.requests.where((r) => r.$2.startsWith('/api/v1/sync/scenarios/')),
        isEmpty,
      );
    });
  });

  test('nothing private is ever sent', () async {
    final gid = play(end: false);
    api.handle(
      'POST',
      Uri.parse('/api/v1/games/$gid/checkin/open'),
      authorization: 'Bearer g',
      body: '{}',
    );
    final r = api.handle(
      'POST',
      Uri.parse('/api/v1/checkin'),
      body: jsonEncode({
        'game_id': gid,
        'player_id': 'p-aaaaaaaaaaaa',
        'player_secret': base64Url
            .encode(List.filled(32, 1))
            .replaceAll('=', ''),
        'display_name': 'Falcão Secreto',
        'notice_version': 1,
      }),
    );
    expect(r.status, 201);
    engine.endGame(gid);
    await client().runOnce();
    final all = jsonEncode([for (final x in site.requests) x.$4]);
    expect(all, isNot(contains('Falcão Secreto')));
    expect(all, isNot(contains('player_secret')));
    expect(all, isNot(contains('game_key')));
    final keyHex = engine.store.gameKey(gid);
    expect(keyHex, isNull); // gone with the game
    for (final x in site.requests) {
      expect(x.$4?.keys ?? const <String>[], isNot(contains('positions')));
    }
  });
}
