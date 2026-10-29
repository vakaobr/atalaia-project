// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The prop session with a fake node: a tick whose snapshot is still on its
// way when the screen disposes the session (the notification that follows
// must not reach the disposed notifier: CI's emulator saw "A PropSession
// was used after being disposed"), and the session on a Wi-Fi link to the
// controller (protocol/prop-link.md): its events and STATE go up, the
// controller's start, message and end come down.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/controller/prop_link.dart';
import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';

/// A node whose snapshots wait for the test when [gates] has one.
class GatedNode extends FakeRunningNode {
  final gates = <Completer<void>>[];
  var waiting = false;
  var snapshots = 0;

  @override
  Future<NodeSnapshot> snapshot() async {
    snapshots++;
    if (gates.isNotEmpty) {
      waiting = true;
      await gates.removeAt(0).future;
      waiting = false;
    }
    return super.snapshot();
  }
}

const texts = PropTexts(
  notificationTitle: 'Atalaia: {mode}',
  notificationRunning: 'running',
  notificationLeft: '{time} left',
);

PropSession fakeSession(
  FakeRunningNode node, {
  PropLink? link,
  JoinPayload? join,
}) {
  final mode = ModeCatalog.builtin().compose('org.atalaia.domination');
  const teams = ['red', 'blue'];
  return PropSession(
    setup: PropSetup(
      mode: mode,
      role: 'zone',
      teams: teams,
      params: mode.resolveParams(const {}, teams),
      join: join,
    ),
    runner: FakeNodeRunner(node),
    device: FakeDevice(),
    texts: texts,
    clock: GameClock.manual,
    link: link,
  );
}

class LinkEnd implements LinkSocket {
  final _in = StreamController<String>();
  final got = <Map<String, Object?>>[];
  @override
  int? closeCode;
  void push(Map<String, Object?> m) => _in.add(jsonEncode(m));
  @override
  Stream<String> get messages => _in.stream;
  @override
  void send(String text) {
    final m = (jsonDecode(text) as Map).cast<String, Object?>();
    got.add(m);
    if (m['type'] == 'auth') {
      push({
        'type': 'welcome',
        'game_id': 9,
        'node_id': 3,
        'time': {'state': 'waiting'},
      });
    }
  }

  @override
  Future<void> close() async {
    if (!_in.isClosed) await _in.close();
  }
}

Future<void> settle() async {
  for (var i = 0; i < 10; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

void main() {
  test('a snapshot that arrives after dispose notifies no one', () async {
    final node = GatedNode();
    final s = fakeSession(node);
    await s.open();
    await s.start();
    final gate = Completer<void>();
    node.snapshots = 0;
    // advance's own snapshot goes through; the refresh after it waits.
    node.gates
      ..add(Completer<void>()..complete())
      ..add(gate);
    final tick = s.advance(250);
    while (node.snapshots < 2 || !node.waiting) {
      await Future<void>.delayed(Duration.zero);
    }
    s.dispose();
    node.scoreMap = const {'red': 5, 'blue': 0}; // something to announce
    gate.complete();
    await tick; // no "used after being disposed"
  });

  test(
    'on a Wi-Fi link: events and STATE up, start, message and end down',
    () async {
      final join = JoinPayload(
        gameId: 9,
        gameKey: Uint8List(16),
        nodeId: 3,
        controllerId: 0,
        channelHz: 869525000,
        maxHops: 2,
        teams: const ['red', 'blue'],
        modeId: 'org.atalaia.domination',
        role: 'zone',
        gameSeed: 1,
        params: null,
        kind: JoinKind.node,
        caSha256: Uint8List(32),
        urls: const ['https://10.0.2.2:8443'],
      );
      final end = LinkEnd();
      end.push({'type': 'challenge', 'nonce': 'AAAA'});
      final link = PropLink(
        join: join,
        urls: join.urls!,
        connect: (_) async => end,
        hello: {'node_name': 'phone-3'},
      );
      final node = FakeRunningNode();
      final s = fakeSession(node, link: link, join: join);
      addTearDown(s.dispose);
      await s.open();
      await settle();
      expect(link.state, LinkState.linked);
      expect(end.got.map((m) => m['type']), ['auth', 'hello']);
      // The controller starts the game.
      end.push({'type': 'cmd', 'cmd': 'start', 'params': <String, Object?>{}});
      await settle();
      expect(s.phase, PropPhase.running);
      expect(node.inputs.map((i) => i.$1), contains('game.start'));
      // The mode's event goes up, with the owner in STATE.
      node.emit(
        NodeEventOutput(
          EmittedEvent(
            node: 3,
            seq: 1,
            tMs: 4000,
            team: 1,
            squad: 0,
            prio: 1,
            type: 'zone.captured',
            dataJson: '{"team":"red"}',
          ),
        ),
      );
      node.scoreMap = const {'red': 7, 'blue': 0};
      await s.advance(5000);
      await settle();
      final ev =
          end.got.firstWhere((m) => m['type'] == 'event')['event']! as Map;
      expect(
        (ev['seq'], ev['type'], ev['team'], ev['prio']),
        (1, 'zone.captured', 1, 'normal'),
      );
      final st = end.got.lastWhere((m) => m['type'] == 'state');
      expect(st['owner_team'], 1);
      expect(st['counters'], {'1': 7});
      expect(st['lost'], isEmpty); // none yet: nothing to carry
      // A box's penalty (BSC-1): the counters stay the gains, STATE's key 9
      // carries the loss, so the controller's merge by maximum can total it.
      node
        ..scoreMap = const {'red': 4, 'blue': 0}
        ..gainedMap = const {'red': 7, 'blue': 0}
        ..lostMap = const {'red': 3};
      await s.advance(1000);
      await settle();
      final pen = end.got.lastWhere((m) => m['type'] == 'state');
      expect(pen['counters'], {'1': 7});
      expect(pen['lost'], {'1': 3});
      end.push({'type': 'ack', 'seq': 1, 'event_type': 'zone.captured'});
      end.push({
        'type': 'cmd',
        'cmd': 'message',
        'params': {'text': 'Última volta'},
      });
      // A mode command (CMD opcode 8): the script gets cmd.mode with its name.
      end.push({
        'type': 'cmd',
        'cmd': 'mode',
        'opcode': 8,
        'params': {'name': 'refill'},
      });
      end.push({
        'type': 'cmd',
        'cmd': 'end',
        'params': {'reason': 'time'},
      });
      await settle();
      expect(link.unacked, 0);
      expect(s.gmMessage, 'Última volta');
      expect(
        node.inputs.map((i) => i.$1),
        containsAll(['gm.message', 'cmd.mode', 'game.end']),
      );
      expect(node.inputs.firstWhere((i) => i.$1 == 'cmd.mode').$2, {
        'name': 'refill',
      });
    },
  );
}
