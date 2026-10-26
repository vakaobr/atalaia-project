// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The remote GM on the phone (lib/controller/controller_remote_gm.dart, PE24
// slice S7): the Pi's controller/tests/test_remote_gm.py, its commands, the
// log, the live view, and the stream end to end against a site server's
// WebSocket in this process (dart:io on the loopback address): hello, live,
// a command and its result, a refused key, and the ATAK relay's cot
// messages once the site server says it takes them.

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_remote_gm.dart';
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:atalaia_app/controller/controller_sync.dart';
import 'package:atalaia_app/controller/controller_sync_format.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/recording_radio.dart';
import '../support/vectors.dart';

final key = 'k' * 43;
const domination = 'org.atalaia.domination';
const medic = 'org.atalaia.medic';
const user = {
  'id': '0c0c0c0c-1111-4222-8333-444455556666',
  'username': 'gm-norte',
};
const t0 = 1800007200.0;
var _n = 0;

String _uuid() {
  _n++;
  return 'aaaaaaaa-0000-4000-8000-${_n.toRadixString(16).padLeft(12, '0')}';
}

Map<String, Object?> command(
  Map<String, Object?> game,
  String what, [
  Map<String, Object?> params = const {},
  double? sentAt,
]) => {
  'id': _uuid(),
  'game': {'game_id': game['id'], 'game_seed': game['game_seed']},
  'command': what,
  'params': params,
  'user': user,
  'sent_at': sentAt ?? t0,
};

/// A site server's stream in this process.
class FakeStream {
  late HttpServer server;
  final received = <Map<String, Object?>>[];
  final headers = <HttpHeaders>[];
  WebSocket? socket;
  int? closeWith;
  int? refuse;
  final _waiters = <void Function()>[];

  String get url => 'http://127.0.0.1:${server.port}';

  Future<void> start() async {
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((req) async {
      headers.add(req.headers);
      if (refuse != null) {
        req.response.statusCode = refuse!;
        await req.response.close();
        return;
      }
      final ws = await WebSocketTransformer.upgrade(req);
      socket = ws;
      if (closeWith != null) {
        await ws.close(closeWith);
        return;
      }
      ws.listen((m) {
        received.add((jsonDecode(m as String) as Map).cast<String, Object?>());
        for (final w in List.of(_waiters)) {
          w();
        }
      });
    });
  }

  Future<void> close() async {
    await socket?.close();
    await server.close(force: true);
  }

  void send(Map<String, Object?> msg) => socket!.add(jsonEncode(msg));

  /// The next message of [type] (waiting for it), taken out.
  Future<Map<String, Object?>> next(String type) async {
    for (var i = 0; i < 600; i++) {
      final at = received.indexWhere((m) => m['type'] == type);
      if (at >= 0) return received.removeAt(at);
      await Future<void>.delayed(const Duration(milliseconds: 25));
    }
    fail('no $type message (got ${received.map((m) => m['type']).toList()})');
  }
}

Future<bool> waitFor(bool Function() ok, [int ms = 15000]) async {
  for (var i = 0; i < ms ~/ 25; i++) {
    if (ok()) return true;
    await Future<void>.delayed(const Duration(milliseconds: 25));
  }
  return ok();
}

void main() {
  late AtalaiaCore core;
  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  late double wall;
  late Directory dir;
  late ControllerEngine engine;
  late RecordingRadio radio;
  late ControllerSync sync;
  late List<Future<void> Function()> cleanups;

  setUp(() {
    wall = t0;
    dir = Directory.systemTemp.createTempSync('atalaia-remote-');
    radio = RecordingRadio();
    engine = ControllerEngine(
      store: FileControllerStore(dir),
      core: core,
      transport: radio,
      wallSeconds: () => wall,
    );
    cleanups = [];
  });

  tearDown(() async {
    for (final c in cleanups.reversed) {
      await c();
    }
    engine.close();
    dir.deleteSync(recursive: true);
  });

  ControllerSync syncTo(String url) {
    final s = ControllerSync(
      engine,
      SyncConfig(url: url, apiKey: key, timeoutS: 10),
      wall: () => wall,
    );
    cleanups.add(s.stop);
    return s;
  }

  RemoteGm remote({bool on = true, bool atak = false, String? url}) {
    sync = syncTo(url ?? 'https://site.example.org');
    return RemoteGm(
      engine,
      sync,
      remoteGm: on,
      atakRemote: atak,
      wall: () => wall,
    );
  }

  Map<String, Object?> game({
    String mode = domination,
    bool joined = true,
    Map<String, Object?> assignments = const {'4': 'zone'},
  }) {
    final g = engine.createGame({
      'name': 'Domingo',
      'mode_id': mode,
      'teams': ['red', 'blue'],
      'assignments': assignments,
    });
    if (joined && mode == domination) {
      // Box 4 says HELLO: the zone has a box (decision RJ-1).
      engine.onPacket(
        RfHeader.v1(
          gameId: g['id']! as int,
          source: 4,
          seq: 0,
          hopLimit: 2,
          type: RfType.hello,
        ),
        const RfHello(
          nodeName: 'box-4',
          platform: 1,
          fwVersion: '0.4.0',
          coreVersion: '0.2.0',
          tier: 0,
          capabilities: [0],
          transports: 1,
          epoch: 1,
        ).encode(),
        epoch: 1,
      );
    }
    return engine.store.game(g['id']! as int)!;
  }

  String state(Map<String, Object?> g) =>
      engine.store.game(g['id']! as int)!['state']! as String;

  group('commands', () {
    test('the game through its life', () {
      final r = remote();
      final g = game();
      for (final (what, params, st) in [
        ('start', <String, Object?>{}, 'running'),
        ('pause', <String, Object?>{'reason': 'medic'}, 'paused'),
        ('resume', <String, Object?>{}, 'running'),
        ('end', <String, Object?>{'reason': 'time'}, 'ended'),
      ]) {
        final out = r.handleCommand(command(g, what, params));
        expect(out['code'], 'done', reason: '$out');
        expect(state(g), st);
      }
      final log = r.remoteCommands();
      expect(log.reversed.map((e) => e['command']), [
        'start',
        'pause',
        'resume',
        'end',
      ]);
      expect(
        {for (final e in log) (e['user_id'], e['username'], e['result'])},
        {(user['id'], 'gm-norte', 'done')},
      );
      expect(log[2]['params'], {'reason': 'medic'});
      final pause = engine
          .log(g['id']! as int)
          .where((e) => e['type'] == 'game.pause');
      expect(pause.single['data'], {'reason': 'medic'});
    });

    test('a start without a box for a role is refused, roles named (RG-1)', () {
      final r = remote();
      final g = game(joined: false);
      final out = r.handleCommand(command(g, 'start'));
      expect(out['code'], 'conflict');
      expect(out['detail'], contains('zone'));
      expect(out['missing'], ['zone']);
      expect(state(g), 'ready');
      // force: false is the same as none
      final again = r.handleCommand(command(g, 'start', {'force': false}));
      expect(again['code'], 'conflict');
      expect(again['missing'], ['zone']);
      expect(state(g), 'ready');
    });

    test('a start with force starts anyway, and the log says so (RG-1)', () {
      final r = remote();
      final g = game(joined: false);
      final out = r.handleCommand(command(g, 'start', {'force': true}));
      expect(out['code'], 'done', reason: '$out');
      expect(out.containsKey('missing'), isFalse);
      expect(out['detail'], contains('started anyway without nodes for: zone'));
      expect(state(g), 'running');
      final log = r.remoteCommands();
      expect(log.first['params'], {'force': true});
      expect(
        engine
            .log(g['id']! as int)
            .where((e) => e['type'] == 'game.start')
            .length,
        1,
      );
    });

    test('force on a game with all its boxes is no different (RG-1)', () {
      final r = remote();
      final g = game();
      final out = r.handleCommand(command(g, 'start', {'force': true}));
      expect(out['detail'], 'game ${g['id']} is running');
      expect(state(g), 'running');
    });

    test('a message and a mode command go on the radio', () {
      final r = remote();
      final g = game(mode: medic, assignments: {'7': 'medic'});
      engine.startGame(g['id']! as int, force: true);
      radio.sent.clear();
      var out = r.handleCommand(command(g, 'message', {'text': '5 minutos'}));
      expect(out['code'], 'done', reason: '$out');
      final cmds = [
        for (final (t, p) in radio.sent)
          if (t == RfType.cmd) RfCmd.decode(p),
      ];
      expect(cmds.last.cmd, 5);
      expect(cmds.last.params, {'text': '5 minutos'});
      out = r.handleCommand(command(g, 'mode', {'name': 'refill', 'node': 7}));
      expect(out['code'], 'done', reason: '$out');
      out = r.handleCommand(command(g, 'mode', {'name': 'detonate'}));
      expect(out['code'], 'invalid');
      expect(out['detail'], contains('mode commands'));
    });

    test('commands outside the list are refused and logged', () {
      final r = remote();
      final g = game();
      engine.startGame(g['id']! as int, force: true);
      final sent = radio.sent.length;
      for (final (what, params) in [
        ('set_owner', {'team': 'red'}),
        ('reboot', <String, Object?>{}),
        ('score', {'team': 'red', 'amount': 50}),
        ('start', {'preset': 'x'}),
        ('message', {'text': ''}),
      ]) {
        expect(r.handleCommand(command(g, what, params))['code'], 'invalid');
      }
      expect(radio.sent.length, sent);
      expect({for (final e in r.remoteCommands()) e['result']}, {'invalid'});
      expect(r.remoteCommands(), hasLength(5));
    });

    test('another game, a stale or a repeated command', () {
      final r = remote();
      final g = game();
      final other = {
        ...g,
        'game_seed': ((g['game_seed']! as int) + 1) % 0x100000000,
      };
      expect(r.handleCommand(command(other, 'start'))['code'], 'not_live');
      expect(
        r.handleCommand(command(g, 'start', const {}, t0 - 120))['code'],
        'stale',
      );
      expect(state(g), 'ready');
      final once = command(g, 'start');
      expect(r.handleCommand(once)['code'], 'done');
      engine
        ..pauseGame(g['id']! as int)
        ..resumeGame(g['id']! as int);
      expect(r.handleCommand(jsonDecode(jsonEncode(once)))['code'], 'done');
      expect(
        engine.log(g['id']! as int).where((e) => e['type'] == 'game.start'),
        hasLength(1),
      );
      expect(r.handleCommand(command(g, 'resume'))['code'], 'conflict');
    });

    test('the log keeps 365 days', () {
      final r = remote();
      r
        ..addRemoteCommand({
          'command_id': _uuid(),
          'received_at': t0 - (remoteLogDays + 1) * 86400,
          'result': 'done',
        })
        ..addRemoteCommand({'command_id': _uuid(), 'result': 'invalid'});
      expect(r.remoteCommands().map((e) => e['result']), ['invalid']);
    });

    test('every command is refused while the remote GM is off; the log '
        'needs the GM token', () {
      final r = remote(on: false);
      final g = game();
      for (final (what, params) in [
        ('start', <String, Object?>{}),
        ('message', {'text': 'olá'}),
        ('end', <String, Object?>{}),
      ]) {
        expect(
          r.handleCommand(command(g, what, params))['code'],
          'remote_gm_off',
        );
      }
      expect(state(g), 'ready');
      final api = ControllerApi(engine, gmToken: 'g', readToken: 'r');
      expect(
        api
            .handle(
              'GET',
              Uri.parse('/api/v1/remote-gm'),
              authorization: 'Bearer r',
            )
            .status,
        403,
      );
      final body =
          api
                  .handle(
                    'GET',
                    Uri.parse('/api/v1/remote-gm'),
                    authorization: 'Bearer g',
                  )
                  .body!
              as Map;
      expect((body['enabled'], (body['log']! as List).length), (false, 3));
      final st = (engine.status()['sync']! as Map)['remote_gm']! as Map;
      expect(st['enabled'], isFalse);
    });
  });

  group('the live view', () {
    test('as the console sees it: no position, token or key', () {
      final r = remote();
      expect(r.liveBody()!['live'], isNull);
      final g = game(mode: medic, assignments: {'7': 'medic'});
      final gid = g['id']! as int;
      engine
        ..startGame(gid, force: true)
        ..logControllerEvent(gid, 'zone.captured', {
          'zone': 'alpha',
        }, team: 'red')
        ..adjustScore(gid, 'red', -5, 'penalty');
      final body = r.liveBody()!;
      final live = body['live']! as Map;
      expect(
        ((live['game']! as Map)['game_id'], live['state'], live['in_charge']),
        (gid, 'running', true),
      );
      expect(live['totals'], {'red': -5, 'blue': 0});
      expect(
        (live['events']! as List).last,
        containsPair('type', 'score.delta'),
      );
      expect(live['mode_commands'], [
        {
          'name': 'refill',
          'roles': ['medic'],
        },
      ]);
      checkLive(jsonDecode(jsonEncode(body)));
      final text = jsonEncode(body);
      expect(text, isNot(contains(key)));
      final gameKey = engine.gameKey
          .map((b) => b.toRadixString(16).padLeft(2, '0'))
          .join();
      expect(text, isNot(contains(gameKey)));
    });

    test('at most fifty events; a box that said HELLO is in it', () {
      final r = remote();
      final g = game();
      final gid = g['id']! as int;
      engine.startGame(gid, force: true);
      for (var i = 0; i < 80; i++) {
        engine.logControllerEvent(gid, 'zone.captured', {});
      }
      final live = r.liveBody()!['live']! as Map;
      expect((live['events']! as List).length, maxLiveEvents);
      final nodes = (live['nodes']! as List).cast<Map<String, Object?>>();
      expect(nodes.map((n) => n['node_id']), [4]);
      expect((nodes.single['info']! as Map)['capabilities'], ['0']);
    });
  });

  group('the stream', () {
    test('the address', () {
      expect(
        streamUrl('https://site.example.org'),
        'wss://site.example.org/api/v1/sync/stream',
      );
      expect(
        streamUrl('https://site.example.org:8443/atalaia/'),
        'wss://site.example.org:8443/atalaia/api/v1/sync/stream',
      );
      expect(
        streamUrl('http://127.0.0.1:8000'),
        'ws://127.0.0.1:8000/api/v1/sync/stream',
      );
    });

    test('hello, live and a command on the socket', () async {
      final site = FakeStream();
      await site.start();
      cleanups.add(site.close);
      final g = game();
      final r = remote(url: site.url)..start();
      cleanups.add(r.stop);
      final hello = await site.next('hello');
      expect(
        (hello['remote_gm'], (hello['controller']! as Map)['id']),
        (true, sync.controllerId),
      );
      expect(hello, isNot(contains('atak')));
      checkHello({...hello}..remove('type'));
      expect(site.headers.first.value('authorization'), 'Bearer $key');
      final live = await site.next('live');
      expect((live['live']! as Map)['state'], 'ready');
      final cmd = command(g, 'start');
      site.send({'type': 'command', ...cmd});
      final result = await site.next('command.result');
      expect((result['id'], result['code']), (cmd['id'], 'done'));
      checkResult({...result}..remove('type'));
      expect(state(g), 'running');
      expect(await waitFor(() => r.status()['connected'] == true), isTrue);
      final again = await site.next('live');
      expect((again['live']! as Map)['state'], 'running');
    });

    test('a refused key is reported', () async {
      for (final (refuse, closeWith) in [(403, null), (null, 4401)]) {
        final site = FakeStream()
          ..refuse = refuse
          ..closeWith = closeWith;
        await site.start();
        final r = remote(url: site.url)..start();
        expect(
          await waitFor(
            () => r.lastError == 'the site server refused the API key',
          ),
          isTrue,
          reason: '${r.lastError}',
        );
        await r.stop();
        await site.close();
      }
    });

    test('the ATAK relay: cot once the site server takes it; no live view, '
        'no command without the remote GM', () async {
      final site = FakeStream();
      await site.start();
      cleanups.add(site.close);
      final g = game();
      final r = remote(on: false, atak: true, url: site.url);
      final relay = <bool>[];
      r
        ..onRelay = relay.add
        ..start();
      cleanups.add(r.stop);
      final hello = await site.next('hello');
      expect((hello['remote_gm'], hello['atak']), (false, true));
      checkHello({...hello}..remove('type'));
      expect(await waitFor(() => r.connected), isTrue);
      final vectors = loadVectors('sync.json');
      final cotBody =
          ((vectors['stream']! as Map)['valid']! as List)
                  .cast<Map<String, Object?>>()
                  .firstWhere((v) => v['kind'] == 'cot')['body']!
              as Map;
      final events = (cotBody['events']! as List).cast<String>();
      expect(r.pushCot(events), 0); // not before the site server said yes
      site.send({'type': 'hello.ack', 'remote_gm': false, 'atak_relay': true});
      expect(await waitFor(() => r.atakRelay), isTrue);
      expect(relay, [true]);
      expect(r.pushCot(events), events.length);
      final cot = await site.next('cot');
      expect(cot['events'], events);
      checkCot({...cot}..remove('type'));
      expect(r.status()['atak'], {
        'enabled': true,
        'relay': true,
        'sent': events.length,
      });
      expect(site.received.where((m) => m['type'] == 'live'), isEmpty);
      site.send({'type': 'command', ...command(g, 'start')});
      expect((await site.next('command.result'))['code'], 'remote_gm_off');
    });

    test('a site server without the relay', () async {
      final site = FakeStream();
      await site.start();
      cleanups.add(site.close);
      final r = remote(on: false, atak: true, url: site.url)..start();
      cleanups.add(r.stop);
      await site.next('hello');
      site.send({'type': 'hello.ack', 'remote_gm': false, 'atak_relay': false});
      await Future<void>.delayed(const Duration(milliseconds: 300));
      expect(r.atakRelay, isFalse);
      expect(r.pushCot(['x']), 0);
    });
  });
}
