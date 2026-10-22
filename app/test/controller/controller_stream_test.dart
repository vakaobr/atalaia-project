// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The stream's routing (lib/controller/controller_stream.dart) beyond the
// shared contract cases: messages marked for staff, the routing marks that
// never leave the controller, and the hub without clients.

import 'package:atalaia_app/controller/controller_checkin.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_stream.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/recording_radio.dart';

void main() {
  late ControllerEngine engine;
  late StreamHub hub;

  setUp(() {
    engine = ControllerEngine(transport: RecordingRadio());
    hub = StreamHub(engine);
  });

  test('staff-only messages reach the GM token only, without marks', () {
    final msg = {
      'type': 'checkin',
      'game': 3,
      '_staff': true,
      '_player': 'p1',
      'checkin': {'name': 'A Person'},
    };
    expect(hub.route(ApiViewer.read, msg), isNull);
    expect(hub.route(ApiViewer.gm, msg), {
      'type': 'checkin',
      'game': 3,
      'checkin': {'name': 'A Person'},
    });
  });

  test('positions need the positions service (slice S5)', () {
    expect(
      hub.route(ApiViewer.gm, {'type': 'player_position', '_position': true}),
      isNull,
    );
    expect(
      hub.route(ApiViewer.gm, {'type': 'x', '_positions_refresh': true}),
      isNull,
    );
  });

  test('gm_only event data and game parameters: GM token only', () {
    final ev = {
      'type': 'event',
      'game': 1,
      'event': {
        'type': 'hacking.solved',
        'data': {'puzzle': 'code', 'code': '1234'},
      },
    };
    expect(hub.route(ApiViewer.gm, ev)!['event'], ev['event']);
    expect((hub.route(ApiViewer.read, ev)!['event']! as Map)['data'], {
      'puzzle': 'code',
    });
    final game = engine.createGame({
      'name': 'h',
      'mode_id': 'org.atalaia.hacking_terminal',
      'params': {'reveal_code': '1234'},
    });
    final out = hub.route(ApiViewer.read, {'type': 'game', 'game': game})!;
    expect((out['game']! as Map)['params'], isNot(contains('reveal_code')));
    expect(
      hub.route(ApiViewer.gm, {'type': 'game', 'game': game})!['game'],
      game,
    );
  });

  test('publishing with no client connected does nothing', () {
    hub.publish({'type': 'system', 'kind': 'test'});
    expect(hub.clientCount, 0);
    expect(hub.droppedClients, 0);
  });

  test('the hello without a live game', () {
    expect(hub.snapshot(ApiViewer.read), {
      'type': 'hello',
      'game': null,
      'score': null,
      'nodes': <Object?>[],
      'events': <Object?>[],
      'status': engine.status(),
    });
  });
}
