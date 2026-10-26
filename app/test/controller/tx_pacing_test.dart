// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The controller's TX pacing (decision SL-13; the relay study's H_paced): its
// own frames leave one at a time, controllerPaceMs apart, through a recording
// modem and a clock the test moves. The same cases as the Pi's
// controller/tests/test_tx_pacing.py; the shared contract cases (the "TX
// pacing" ones in protocol/vectors/controller_api.json) run through the
// engine in api_contract_test.dart.

import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_radio.dart';
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/recording_modem.dart';

void main() {
  late AtalaiaCore core;
  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  final key = Uint8List.fromList(List.generate(16, (i) => i));

  group('RadioTransport', () {
    late RecordingModem modem;
    late MemoryControllerStore store;
    setUp(() {
      modem = RecordingModem();
      store = MemoryControllerStore();
    });

    RadioTransport transport({int pace = 800, int queueMax = paceQueueMax}) =>
        RadioTransport(
          modem: modem,
          store: store,
          gameId: 7,
          nodeId: 0,
          maxHops: 2,
          channelHz: 869525000,
          key: key,
          paceMs: pace,
          queueMax: queueMax,
        );

    int? send(RadioTransport t, [int type = RfType.cmd]) => t.send(
      type,
      Uint8List.fromList([1]),
      prio: RfPrio.critical,
      ack: false,
      hopLimit: 2,
    );

    List<int> seqs() => [for (final (h, _) in modem.sent) h.seq];

    test('the first frame leaves at once, the rest wait their gap', () {
      final t = transport();
      expect([for (var i = 0; i < 3; i++) send(t)], [0, 1, 2]);
      expect(seqs(), [0]);
      expect(t.queued, 2);
      t.pump(799);
      expect(seqs(), [0]);
      t.pump(800);
      expect(seqs(), [0, 1]);
      t.pump(1599);
      expect(seqs(), [0, 1]);
      t.pump(1600);
      expect(seqs(), [0, 1, 2]);
      expect(t.queued, 0);
    });

    test('one frame per pump even when the clock jumps', () {
      final t = transport();
      for (var i = 0; i < 4; i++) {
        send(t);
      }
      t.pump(60000);
      expect(seqs(), [0, 1]); // the gap runs from the hand-over
      t.pump(60800);
      expect(seqs(), [0, 1, 2]);
    });

    test('the gap runs from the modem\'s TX_ACK', () {
      final t = transport();
      send(t);
      send(t);
      t.txDone(0, 350); // on the air till 350 ms: the next may go at 1150
      t.pump(800);
      expect(seqs(), [0]);
      t.pump(1149);
      expect(seqs(), [0]);
      t.pump(1150);
      expect(seqs(), [0, 1]);
    });

    test(
      'a TX_ACK of another frame changes nothing; a lost one never stalls',
      () {
        final t = transport();
        send(t);
        send(t);
        t.txDone(99, 700);
        t.pump(800);
        expect(seqs(), [0, 1]);
      },
    );

    test('zero is no pacing', () {
      final t = transport(pace: 0);
      for (var i = 0; i < 5; i++) {
        send(t);
      }
      expect(seqs(), [0, 1, 2, 3, 4]);
      expect(t.queued, 0);
    });

    test('every kind of frame waits in one FIFO, with no priorities', () {
      final t = transport();
      const kinds = [
        RfType.cmd,
        RfType.ack,
        RfType.time,
        RfType.cmd,
        RfType.ack,
      ];
      for (final k in kinds) {
        send(t, k);
      }
      for (var ms = 0; ms < 4000; ms += 800) {
        t.pump(ms);
      }
      expect([for (final (h, _) in modem.sent) h.type], kinds);
      expect(seqs(), [0, 1, 2, 3, 4]);
    });

    test(
      'a full queue drops the new frame, counts it and leaves no seq hole',
      () {
        final t = transport();
        final got = [for (var i = 0; i < 1 + paceQueueMax + 2; i++) send(t)];
        expect(got.sublist(0, 1 + paceQueueMax), List.generate(9, (i) => i));
        expect(got.sublist(1 + paceQueueMax), [null, null]);
        expect((t.queued, t.queueDropped, t.refused), (paceQueueMax, 2, 2));
        t.pump(800);
        expect(send(t), 1 + paceQueueMax);
      },
    );

    test('the default queue is the modem\'s own: 8', () {
      expect(paceQueueMax, 8);
    });

    test('a modem that is down refuses at once; one that goes down while '
        'frames wait drops them', () {
      final t = transport();
      modem.state = ModemState.down;
      expect(send(t), isNull);
      expect((t.refused, t.queued), (1, 0));
      modem.state = ModemState.up;
      for (var i = 0; i < 3; i++) {
        send(t);
      }
      modem.state = ModemState.down;
      t.pump(800);
      t.pump(1600);
      expect(seqs(), [0]);
      expect((t.queued, t.refused), (0, 3));
    });

    test('discard drops what waits and counts it', () {
      final t = transport();
      for (final k in [RfType.cmd, RfType.cmd, RfType.ack, RfType.time]) {
        send(t, k);
      }
      expect(t.discard(), 2); // the CMD and the TIME go, the ACK stays
      expect((t.queued, t.queueDropped), (1, 2));
      expect(seqs(), [0]);
      t.flush();
      expect(
        [for (final (h, _) in modem.sent) h.type],
        [RfType.cmd, RfType.ack],
      );
    });

    test('flush hands everything over in order, without the gap', () {
      final t = transport();
      for (var i = 0; i < 5; i++) {
        send(t);
      }
      expect(t.flush(), 4);
      expect(seqs(), [0, 1, 2, 3, 4]);
      expect((t.queued, t.flush()), (0, 0));
    });

    test('the seq wrap sends the old epoch\'s frames first', () {
      final t = transport();
      t.nextSeq = 0xfffe;
      send(t); // 0xfffe leaves
      send(t); // 0xffff waits for its gap
      send(t); // the seqs of epoch 1 are spent: 0xffff goes first
      expect(t.epoch, 2);
      expect(seqs(), [0xfffe, 0xffff]);
      expect(modem.log.last['kind'], 'configure');
      expect(modem.log.last['epoch'], 2);
      expect(t.queued, 1); // epoch 2's seq 0, waiting its gap
    });
  });

  group('the engine', () {
    late RecordingModem modem;
    late ControllerEngine engine;
    var now = 0;

    setUp(() {
      now = 0;
      modem = RecordingModem();
      engine = ControllerEngine(
        config: const ControllerConfig(controllerPaceMs: 800),
        core: core,
        modem: modem,
        clockMs: () => now,
      );
    });

    int create() =>
        engine.createGame({
              'name': 'S',
              'mode_id': 'org.atalaia.domination',
              'teams': ['red', 'blue'],
              'assignments': {'4': 'zone', '5': 'zone'},
            })['id']!
            as int;

    List<String> kinds() => [
      for (final e in modem.log)
        if (e['kind'] != 'configure' && e['kind'] != 'peer_epochs')
          e['kind']! as String,
    ];

    void advance(int ms) {
      now += ms;
      engine.tick();
    }

    test('pacing is off by default (800 is the candidate)', () {
      expect(const ControllerConfig().controllerPaceMs, 0);
    });

    test('start sends the CMD, then the TIME beacon a gap later', () {
      final id = create();
      engine.startGame(id, force: true);
      expect(kinds(), ['CMD']);
      advance(500);
      expect(kinds(), ['CMD']);
      advance(310);
      expect(kinds(), ['CMD', 'TIME']);
      expect([for (final (h, _) in modem.sent) h.seq], [0, 1]);
    });

    test('the modem\'s TX_ACK moves the gap', () {
      final id = create();
      engine.startGame(id, force: true);
      advance(500);
      modem.onTxAck?.call(0, 'ok'); // on the air till 500: the next at 1300
      advance(500);
      expect(kinds(), ['CMD']);
      advance(310);
      expect(kinds(), ['CMD', 'TIME']);
    });

    test('commands to boxes are paced too', () {
      final id = create();
      engine.startGame(id, force: true);
      engine.sendNodeCmd(4, 'message', {'text': 'hi'});
      engine.sendNodeCmd(5, 'message', {'text': 'hi'});
      expect(kinds(), ['CMD']);
      for (var i = 0; i < 40; i++) {
        advance(100);
      }
      final cmds = [
        for (final (h, p) in modem.sent)
          if (h.type == RfType.cmd) RfCmd.decode(p),
      ];
      expect(cmds.map((c) => (c.name, c.dest)), [
        ('start', null),
        ('message', 4),
        ('message', 5),
      ]);
    });

    test(
      'the end drops what waits and sends its own frames before the key goes',
      () {
        final id = create();
        engine.startGame(id, force: true); // START leaves, its TIME waits
        engine.sendNodeCmd(4, 'message', {'text': 'hi'});
        engine.sendNodeCmd(5, 'message', {'text': 'hi'});
        engine.radioTransport!.send(
          RfType.ack,
          Uint8List(1),
          prio: RfPrio.normal,
          ack: false,
          hopLimit: 2,
        );
        advance(100);
        engine.endGame(id, 'done');
        final k = kinds();
        expect(k.last, 'clear');
        // START, the box's ACK, then END and its TIME: the stale messages
        // are gone.
        expect(k.sublist(0, k.length - 1), ['CMD', 'ACK', 'CMD', 'TIME']);
        final cmds = [
          for (final (h, p) in modem.sent)
            if (h.type == RfType.cmd) RfCmd.decode(p).name,
        ];
        expect(cmds, ['start', 'end']);
      },
    );

    test('the status shows the queue', () {
      final id = create();
      engine.startGame(id, force: true);
      expect(engine.status()['tx_queue'], {
        'queued': 1,
        'dropped': 0,
        'pace_ms': 800,
      });
    });

    test('pace 0 keeps the old burst', () {
      final m = RecordingModem();
      final e = ControllerEngine(
        config: const ControllerConfig(controllerPaceMs: 0),
        core: core,
        modem: m,
        clockMs: () => now,
      );
      final id =
          e.createGame({
                'name': 'S',
                'mode_id': 'org.atalaia.domination',
                'teams': ['red', 'blue'],
                'assignments': {'4': 'zone'},
              })['id']!
              as int;
      e.startGame(id, force: true);
      expect([for (final (h, _) in m.sent) h.type], [RfType.cmd, RfType.time]);
    });
  });
}
