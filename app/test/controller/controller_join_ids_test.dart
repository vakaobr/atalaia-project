// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A controller's node id is never given to a new device once the controller
// has been on the air in the game (decision EP-3, RFC 0001 Amendment 24 item
// 4; the Pi's twin is controller/tests/test_join.py): a former leader that
// lost its stores and is joined again as a standby under its old id would
// repeat its nonces (epoch 1 under a key it already used) and be deaf to every
// receiver that heard its old epochs. A join with no id gets a new one.

import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/recording_radio.dart';

final key = Uint8List.fromList(List.generate(32, (i) => 100 + i));

void main() {
  late ControllerEngine engine;
  late int gid;

  // The game key is kept on disk (persist_game_key), so a restart resumes it.
  ControllerEngine open(ControllerStore store) => ControllerEngine(
    config: const ControllerConfig(persistGameKey: true),
    store: store,
    transport: RecordingRadio(),
  )..joinKey = key;

  /// Another controller's TIME or CLAIM, authenticated by the radio.
  void hear(int source, {int type = RfType.time}) {
    final payload = type == RfType.time
        ? const RfTime(
            gameTimeMs: 0,
            gameState: 0,
            durationMs: 0,
            wallS: 1,
            term: 1,
          ).encode()
        : Uint8List.fromList([0xa0]);
    engine.onPacket(
      RfHeader.v1(gameId: gid, source: source, seq: 0, hopLimit: 0, type: type),
      payload,
      epoch: 9,
    );
  }

  int joinId(Map<String, Object?> made) =>
      decodeJoin(joinFromText(made['text']! as String), key).nodeId;

  setUp(() {
    engine = open(MemoryControllerStore());
    gid =
        engine.createGame({
              'name': 'g',
              'mode_id': 'org.atalaia.domination',
              'teams': ['red', 'blue'],
              'assignments': {'4': 'zone'},
            })['id']!
            as int;
  });
  tearDown(() => engine.close());

  test('a controller that was heard keeps its id: no join under it', () {
    hear(6);
    hear(8, type: RfType.claim);
    for (final id in [6, 8]) {
      expect(
        () => engine.issueJoin({'kind': 'controller'}, nodeIdValue: id),
        throwsA(
          isA<ControllerError>()
              .having((e) => e.status, 'status', 409)
              .having((e) => e.message, 'message', contains('new node id')),
        ),
      );
      // Nor as "the same device invited again".
      expect(
        () => engine.issueJoin(
          {'kind': 'controller'},
          nodeIdValue: id,
          sameDevice: true,
        ),
        throwsA(isA<ControllerError>()),
      );
    }
    // A join with no id skips them.
    final ids = {
      for (var i = 0; i < 6; i++)
        joinId(engine.issueJoin({'kind': 'controller'})),
    };
    expect(ids.intersection({6, 8}), isEmpty, reason: '$ids');
    // A standby never heard can be invited again under its id (the refresh).
    expect(
      joinId(engine.issueJoin({'kind': 'controller'}, nodeIdValue: 15)),
      15,
    );
    expect(
      joinId(
        engine.issueJoin(
          {'kind': 'controller'},
          nodeIdValue: 15,
          sameDevice: true,
        ),
      ),
      15,
    );
  });

  test('the list is kept across a restart', () {
    final store = engine.store;
    hear(6);
    engine.close();
    engine = open(store);
    expect(
      () => engine.issueJoin(
        {'kind': 'controller'},
        nodeIdValue: 6,
        sameDevice: true,
      ),
      throwsA(isA<ControllerError>().having((e) => e.status, 'status', 409)),
    );
  });
}
