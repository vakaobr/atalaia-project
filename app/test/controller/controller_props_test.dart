// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Android props on the phone controller's Wi-Fi (slice S4 of PE24,
// lib/controller/controller_props.dart): the app's own prop link
// (lib/controller/prop_link.dart, the client a prop phone runs) against the
// phone controller's WS /api/v1/prop on the loopback address, beyond the
// shared contract case: the link, HELLO, an event acknowledged, TIME and
// commands back, a controller without a radio whose commands reach the
// Wi-Fi props and count as sent (protocol/prop-link.md), and a wrong key.

import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/prop_link.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';

final joinKey = Uint8List.fromList(List.generate(32, (i) => 100 + i));

Future<bool> waitFor(bool Function() ok) async {
  final end = DateTime.now().add(const Duration(seconds: 5));
  while (DateTime.now().isBefore(end)) {
    if (ok()) return true;
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
  return ok();
}

void main() {
  late AtalaiaCore core;
  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  late ControllerEngine engine;
  late ControllerApi api;
  late HttpServer server;
  late int gid;

  setUp(() async {
    // No radio at all: the props are the field.
    engine = ControllerEngine(core: core)..joinKey = joinKey;
    api = ControllerApi(engine, gmToken: 'g', readToken: 'r');
    server = await api.serve();
    gid =
        engine.createGame({
              'name': 'wifi',
              'mode_id': 'org.atalaia.domination',
            })['id']!
            as int;
  });

  tearDown(() async {
    await api.props.close();
    await api.hub.close();
    await server.close(force: true);
    engine.close();
  });

  PropLink prop(JoinPayload j) => PropLink(
    join: j,
    // The phone controller serves plain ws:// on the loopback address until
    // slice S6 brings HTTPS; the link's own address is replaced here.
    urls: const ['https://127.0.0.1:1'],
    connect: (uri) => ioLinkConnect(null)(
      Uri.parse('ws://127.0.0.1:${server.port}/api/v1/prop'),
    ),
    hello: {
      'node_name': 'telemovel-7',
      'capabilities': <int>[0, 2],
    },
  );

  JoinPayload joined(int node) => decodeJoin(
    joinFromText(engine.issueJoin({'node_id': node})['text']! as String),
    joinKey,
  );

  test("the app's prop link plays a game on the phone controller", () async {
    final link = prop(joined(7));
    final heard = <LinkMessage>[];
    link.messages.listen(heard.add);
    link.sendEvent(seq: 1, tMs: 100, type: 'zone.captured', team: 1);
    link.start();
    expect(await waitFor(() => link.linked), isTrue);
    expect(await waitFor(() => link.unacked == 0), isTrue);
    final node = engine.nodes().firstWhere((n) => n['node_id'] == 7);
    expect([node['name'], node['platform']], ['telemovel-7', 3]);
    expect(engine.log(gid).where((e) => e['type'] == 'zone.captured'), [
      containsPair('node', 7),
    ]);
    expect(
      heard.whereType<LinkTime>().first,
      isA<LinkTime>().having((t) => t.state, 'state', 'waiting'),
    );

    link.sendState({
      'owner_team': 1,
      'phase': 1,
      'game_time_ms': 100,
      'counters': {'1': 6},
    });
    expect(
      await waitFor(() => (engine.score(gid)['teams']! as Map)['red'] == 6),
      isTrue,
    );

    // Without a radio, the start and a command still reach the prop, and
    // the command counts as sent (protocol/prop-link.md).
    engine.startGame(gid, force: true);
    expect(engine.sendNodeCmd(7, 'message', {'text': 'go'})['node'], 7);
    expect(
      () => engine.sendNodeCmd(4, 'message', {'text': 'x'}),
      throwsA(isA<ControllerError>().having((e) => e.status, 'status', 503)),
    );
    expect(
      await waitFor(
        () => heard.whereType<LinkCommand>().any((c) => c.cmd == 'message'),
      ),
      isTrue,
    );
    expect(heard.whereType<LinkCommand>().map((c) => c.cmd), [
      'start',
      'message',
    ]);
    expect(heard.whereType<LinkTime>().last.state, 'running');
    expect(api.props.linked, [7]);
    await link.close();
    expect(await waitFor(() => api.props.linked.isEmpty), isTrue);
  });

  test('a prop with the wrong key is refused', () async {
    final j = joined(7);
    final wrong = JoinPayload(
      gameId: j.gameId,
      gameKey: Uint8List(16),
      nodeId: j.nodeId,
      controllerId: j.controllerId,
      channelHz: j.channelHz,
      maxHops: j.maxHops,
      teams: j.teams,
      modeId: j.modeId,
      role: j.role,
      gameSeed: j.gameSeed,
      params: j.params,
      kind: j.kind,
    );
    final link = prop(wrong)..start();
    expect(await waitFor(() => link.state == LinkState.refused), isTrue);
    expect(api.props.linked, isEmpty);
    await link.close();
  });
}
