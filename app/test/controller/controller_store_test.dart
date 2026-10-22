// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The Android field controller's file store (slice S3 of PE24, decision
// PE24-40) and what a restart carries on beyond the shared contract cases
// (api_contract_test.dart's restart steps): the files themselves, a log cut
// short by a crash, the game key on disk only with persist_game_key, and the
// node health after a restart (as the Pi's test_node_health.py).

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_radio.dart';
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/recording_radio.dart';
import '../support/vectors.dart';

Map<String, Object?> _game(int id, {String state = 'ready', double at = 1}) => {
  'id': id,
  'name': 'g$id',
  'mode_id': 'org.atalaia.domination',
  'teams': ['red', 'blue'],
  'params': <String, Object?>{},
  'assignments': <String, Object?>{},
  'duration_ms': 0,
  'game_seed': 7,
  'state': state,
  'term': 1,
  'created_at': at,
};

Map<String, Object?> _event(int seq, {int t = 0, String type = 'x.test'}) => {
  'node': 4,
  'seq': seq,
  't': t,
  'type': type,
  'team': 'red',
  'squad': 0,
  'data': {'n': seq},
  'epoch': 1,
  'pkt_seq': seq,
};

void main() {
  late Directory dir;
  setUp(() => dir = Directory.systemTemp.createTempSync('atalaia-store-'));
  tearDown(() => dir.deleteSync(recursive: true));

  FileControllerStore open() =>
      FileControllerStore(dir, wallSeconds: () => 5.0);

  group('FileControllerStore', () {
    test('keeps games, events, scores, nodes and settings', () {
      final a = open()
        ..createGame(_game(7))
        ..createGame(_game(9, state: 'running', at: 2));
      expect(a.insertEvent(9, _event(1, t: 50)), isTrue);
      expect(a.insertEvent(9, _event(1, t: 50)), isFalse); // a replay
      a
        ..insertEvent(9, _event(2, t: 10))
        ..saveScores(9, {'red': 3, 'blue': 1})
        ..upsertNode(9, {
          'node_id': 4,
          'name': 'box-4',
          'role': 'zone',
          'score': {'red': 3},
        })
        ..updateGame(7, {'state': 'ended', 'ended_at': 3.5})
        ..setSetting('field_run:9', '2')
        ..setSetting('gone', 'x')
        ..deleteSetting('gone');
      final b = open();
      expect(b.gameIds(), {7, 9});
      expect(b.game(7), containsPair('state', 'ended'));
      expect(b.game(7), containsPair('ended_at', 3.5));
      expect(b.liveGame()!['id'], 9);
      expect([for (final e in b.events(9)) e['seq']], [2, 1]); // by game time
      expect(b.events(9).last, containsPair('data', {'n': 1}));
      expect(b.events(9).last, containsPair('received_at', 5));
      expect(b.insertEvent(9, _event(2, t: 10)), isFalse); // still a replay
      expect(b.scores(9), {'red': 3, 'blue': 1});
      expect(b.nodes(9).single, containsPair('name', 'box-4'));
      expect(b.nodes(9).single, containsPair('score', {'red': 3}));
      expect(b.getSetting('field_run:9'), '2');
      expect(b.getSetting('gone'), isNull);
      expect(b.unreadableLines, 0);
    });

    test('the game key is on disk only when given, until forgotten', () {
      final key = Uint8List.fromList(List.generate(16, (i) => i + 1));
      open()
        ..createGame(_game(1))
        ..createGame(_game(2, at: 2), key: key);
      final f1 = File('${dir.path}/games/1.json').readAsStringSync();
      final f2 = File('${dir.path}/games/2.json').readAsStringSync();
      expect(f1, isNot(contains('"key"')));
      expect(jsonDecode(f2)['key'], '0102030405060708090a0b0c0d0e0f10');
      expect(jsonDecode(f2)['game'], isNot(contains('game_key')));
      final b = open();
      expect(b.gameKey(1), isNull);
      expect(b.gameKey(2), key);
      b.forgetGameKey(2);
      expect(
        File('${dir.path}/games/2.json').readAsStringSync(),
        isNot(contains('"key"')),
      );
      expect(open().gameKey(2), isNull);
    });

    test('a last line cut short by a crash is dropped, the log goes on', () {
      open()
        ..createGame(_game(3))
        ..insertEvent(3, _event(1))
        ..insertEvent(3, _event(2));
      final log = File('${dir.path}/games/3.events.jsonl');
      final full = log.readAsStringSync();
      log.writeAsStringSync(full.substring(0, full.length - 9)); // torn
      final b = open();
      expect([for (final e in b.events(3)) e['seq']], [1]);
      expect(b.unreadableLines, 0);
      expect(b.insertEvent(3, _event(2)), isTrue); // not a replay now
      b.insertEvent(3, _event(3));
      expect([for (final e in open().events(3)) e['seq']], [1, 2, 3]);
    });

    test('a line that is not an event is counted and skipped', () {
      open().createGame(_game(3));
      File('${dir.path}/games/3.events.jsonl').writeAsStringSync(
        '${jsonEncode(_event(1))}\n{"node": "x"}\nnot json\n'
        '${jsonEncode(_event(2))}\n',
      );
      final b = open();
      expect([for (final e in b.events(3)) e['seq']], [1, 2]);
      expect(b.unreadableLines, 2);
    });

    test('whole files are replaced, never left half written', () {
      open()
        ..createGame(_game(4))
        ..setSetting('a', '1');
      final names = [
        for (final f in dir.listSync(recursive: true)) f.uri.pathSegments.last,
      ];
      expect(names.where((n) => n.endsWith('.tmp')), isEmpty);
      // A temporary file a crash left behind is not read.
      File('${dir.path}/games/5.json.tmp').writeAsStringSync('{');
      expect(open().gameIds(), {4});
    });

    test('a newer layout or a broken file is refused', () {
      open();
      File('${dir.path}/store.json').writeAsStringSync('{"format": 2}');
      expect(open, throwsA(isA<ControllerStoreException>()));
      File('${dir.path}/store.json').writeAsStringSync('{"format": 1}');
      File('${dir.path}/settings.json').writeAsStringSync('{');
      expect(open, throwsA(isA<ControllerStoreException>()));
    });
  });

  group('TX epochs per game key (slice S4)', () {
    test('the key tags of protocol/vectors/epoch_tag.json', () {
      final v = loadVectors('epoch_tag.json');
      for (final c in cases(v, 'valid')) {
        final key = c['game_key'] as String;
        expect(
          epochTag([
            for (var i = 0; i < key.length; i += 2)
              int.parse(key.substring(i, i + 2), radix: 16),
          ]),
          c['tag'],
          reason: c['name'] as String,
        );
      }
    });

    test('each key goes on from its own epoch; the latest 8 are kept', () {
      final store = open();
      List<int> key(int n) => List.filled(16, n);
      expect(nextTxEpoch(store, key(1)), 1);
      expect(nextTxEpoch(store, key(1)), 2);
      expect(nextTxEpoch(store, key(2)), 1);
      expect(open().getSetting('tx_epochs'), isNotNull); // on disk
      expect(nextTxEpoch(open(), key(1)), 3);
      final s = open();
      for (var n = 3; n <= 10; n++) {
        nextTxEpoch(s, key(n));
      }
      // Key 1 fell out of the 8 kept: it starts again at 1, as a new key.
      expect((jsonDecode(s.getSetting('tx_epochs')!) as List).length, 8);
      expect(nextTxEpoch(s, key(1)), 1);
      expect(s.getSetting('tx_epochs'), isNot(contains('0101')));
    });
  });

  group('a restart', () {
    var now = 0;
    late RecordingRadio radio;
    late ControllerEngine engine;

    ControllerEngine boot({bool persist = true}) => engine = ControllerEngine(
      config: ControllerConfig(persistGameKey: persist),
      store: open(),
      transport: radio,
      clockMs: () => now,
    );

    void advance(int seconds) {
      for (var i = 0; i < seconds; i++) {
        now += 1000;
        engine.tick();
      }
    }

    void rx(int seq, int type, Uint8List payload) => engine.onPacket(
      RfHeader.v1(
        gameId: engine.liveGame!['id']! as int,
        source: 4,
        seq: seq,
        hopLimit: 2,
        type: type,
      ),
      payload,
      epoch: 2,
      rssi: -60,
      snr: 5,
    );

    List<(String, int)> health(int gid) => [
      for (final e in engine.log(gid))
        if (e['node'] == 4 && e['epoch'] == null)
          (e['type']! as String, e['seq']! as int),
    ];

    setUp(() {
      now = 0;
      radio = RecordingRadio();
    });

    test('carries the node health on (as the Pi)', () {
      boot();
      final gid =
          engine.createGame({
                'name': 'g',
                'mode_id': 'org.atalaia.domination',
                'assignments': {'4': 'zone'},
              })['id']!
              as int;
      engine.startGame(gid, force: true);
      rx(
        0,
        RfType.hello,
        const RfHello(
          nodeName: 'box-4',
          platform: 1,
          fwVersion: '0.3.0',
          coreVersion: '0.2.0',
          tier: 0,
          capabilities: [1],
          transports: 1,
          batteryPct: 12,
          epoch: 2,
        ).encode(),
      );
      advance(31);
      expect(health(gid), [('node.online', 1), ('battery.low', 2)]);
      engine.close();
      boot();
      // Not heard since the restart: offline once node_offline_s has passed.
      advance(119);
      expect(health(gid), hasLength(2));
      advance(2);
      expect(health(gid).last, ('node.offline', 3));
      engine.close();
      boot();
      // Heard again: online at once, and the low battery is not logged again.
      rx(
        1,
        RfType.state,
        const RfState(
          ownerTeam: 0,
          phase: 0,
          gameTimeMs: 0,
          counters: {},
          epoch: 2,
          batteryPct: 11,
        ).encode(),
      );
      advance(40);
      expect(health(gid), [
        ('node.online', 1),
        ('battery.low', 2),
        ('node.offline', 3),
        ('node.online', 4),
      ]);
      engine.close();
    });

    test('keeps the key with persist_game_key, else only ending is left', () {
      boot();
      final gid =
          engine.createGame({
                'name': 'g',
                'mode_id': 'org.atalaia.domination',
              })['id']!
              as int;
      final key = Uint8List.fromList(engine.gameKey);
      expect(key, hasLength(16));
      engine.close();
      boot();
      expect(engine.gameKey, key);
      expect(engine.keyLost, isFalse);
      engine.endGame(gid);
      expect(open().gameKey(gid), isNull); // not after the game
      engine.close();

      boot(persist: false);
      final gid2 =
          engine.createGame({
                'name': 'h',
                'mode_id': 'org.atalaia.domination',
              })['id']!
              as int;
      expect(open().gameKey(gid2), isNull);
      engine.close();
      boot(persist: false);
      expect(engine.keyLost, isTrue);
      expect(engine.gameKey, isEmpty);
      expect(engine.status()['key_lost'], isTrue);
      expect(
        () => engine.startGame(gid2, force: true),
        throwsA(isA<ControllerError>().having((e) => e.status, 'status', 409)),
      );
      expect(engine.endGame(gid2)['state'], 'ended');
      expect(engine.keyLost, isFalse);
      engine.close();
    });

    test('a crash loses at most gameTimeSaveMs of the game time', () {
      boot();
      final gid =
          engine.createGame({
                'name': 'g',
                'mode_id': 'org.atalaia.domination',
              })['id']!
              as int;
      engine.startGame(gid, force: true);
      advance(7); // saved at 5 s
      // A crash: no close(), a new engine on the files.
      boot();
      expect(engine.getGame(gid)['game_time_ms'], 5000);
      expect(engine.getGame(gid)['state'], 'running');
      advance(1);
      expect(engine.getGame(gid)['game_time_ms'], 6000);
      engine.close();
    });
  });
}
