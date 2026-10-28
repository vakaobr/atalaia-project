// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A prop session with an I/O pod that goes out of reach and comes back
// (decision PF15): the session shows the state, opens the same pod again
// by itself, takes its buttons again and, with a radio, a new radio link
// (a new epoch); the person's unlink and the end of the game stop it. Then
// the prop's screen: the banner, the icon, and the admin's "unlink".

import 'dart:typed_data';

import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:atalaia_app/pod/pod_reconnect.dart';
import 'package:atalaia_app/prop/prop_game.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/radio/pod_radio_link.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_pod_link.dart';
import '../support/fakes.dart';

Duration fast(int attempt) => const Duration(milliseconds: 10);
Duration quick(PodClient c) => const Duration(milliseconds: 80);

final catalog = ModeCatalog.builtin();

PropSetup setup({JoinPayload? join}) {
  final mode = catalog.compose('org.atalaia.domination');
  const teams = ['red', 'blue'];
  return PropSetup(
    mode: mode,
    role: 'zone',
    teams: teams,
    params: mode.resolveParams(const {}, teams),
    join: join,
  );
}

PropSession session(
  FakeRunningNode node, {
  PodReopen? reopen,
  PodRadioLink? Function(PodClient)? radio,
  JoinPayload? join,
}) => PropSession(
  setup: setup(join: join),
  runner: FakeNodeRunner(node),
  device: FakeDevice(),
  texts: const PropTexts(
    notificationTitle: '',
    notificationRunning: '',
    notificationLeft: '',
  ),
  clock: GameClock.manual,
  reopenPod: reopen,
  podBackoff: fast,
  podIdentWait: quick,
  radioLinkFor: radio,
);

bool pressed(FakeRunningNode node, String team) =>
    node.inputs.any((i) => i.$1 == 'team_input.press' && i.$2?['team'] == team);

void main() {
  test('the pod comes back by itself and its buttons work again', () async {
    final node = FakeRunningNode();
    final links = <FakePodLink>[];
    var tries = 0;
    final s = session(
      node,
      reopen: (lost) async {
        tries++;
        if (tries == 1) return null; // out of reach at the first try
        final l = FakePodLink();
        links.add(l);
        return PodClient(l);
      },
    );
    await s.open();
    final first = FakePodLink();
    await s.attachPod(PodClient(first));
    await until(() => s.pod != null);
    expect(s.podPhase, PodLinkPhase.linked);
    first.event('btn.blue', 'press', 1);
    await until(() => pressed(node, 'blue'));

    final phases = <PodLinkPhase?>[];
    s.addListener(() => phases.add(s.podPhase));
    await first.drop();
    await until(() => s.podPhase == PodLinkPhase.reconnecting);
    expect(s.log.last, contains('pod link lost'));
    // While the link is down the pod's inputs are not mapped.
    await until(() => links.isNotEmpty && s.podPhase == PodLinkPhase.linked);
    expect(tries, 2);
    expect(phases, contains(PodLinkPhase.reconnecting));
    expect(s.pod, isNotNull);
    expect(s.log, contains('pod link restored'));

    // The new link's buttons are the game's team inputs again.
    links.single.event('btn.red', 'press', 1);
    await until(() => pressed(node, 'red'));
    await s.close();
    expect(links.single.closed, isTrue);
  });

  test('a pod with a radio gets a new radio link after it came back', () async {
    final node = FakeRunningNode();
    final links = <FakePodLink>[];
    var radios = 0;
    final key = List<int>.generate(16, (i) => i);
    final join = JoinPayload(
      gameId: 777,
      gameKey: Uint8List.fromList(key),
      nodeId: 5,
      controllerId: 0,
      channelHz: 869525000,
      maxHops: 2,
      teams: const ['red', 'blue'],
      modeId: 'org.atalaia.domination',
      role: 'zone',
      gameSeed: 1,
      params: null,
      kind: JoinKind.node,
    );
    final radioPod = FakePodLink(
      ident: const PodIdent(
        fwVersion: '0.3.0',
        capabilities: [
          {'id': 'btn.red', 'type': 'button', 'team': 'red'},
        ],
        hasRadio: true,
      ),
    );
    final epochs = MemoryEpochStore();
    final s = session(
      node,
      join: join,
      reopen: (lost) async {
        final l = FakePodLink(ident: radioPod.ident);
        links.add(l);
        return PodClient(l);
      },
      radio: (client) {
        radios++;
        return PodRadioLink(
          pod: client,
          join: join,
          epochs: epochs,
          encodeEvent:
              ({
                required node,
                required seq,
                required tMs,
                required type,
                required team,
                required squad,
                required prio,
                required dataJson,
              }) => null,
          tick: const Duration(milliseconds: 20),
        );
      },
    );
    await s.open();
    await s.attachPod(PodClient(radioPod));
    await until(() => radios == 1);
    final firstRadio = s.radio;
    expect(firstRadio, isNotNull);
    await radioPod.drop();
    await until(() => radios == 2);
    expect(s.radio, isNot(same(firstRadio)));
    expect(s.radio!.pod.transport, same(links.single));
    await s.close();
  });

  test('the person unlinking stops it for good', () async {
    final node = FakeRunningNode();
    var tries = 0;
    final s = session(
      node,
      reopen: (lost) async {
        tries++;
        return PodClient(FakePodLink());
      },
    );
    await s.open();
    final link = FakePodLink();
    await s.attachPod(PodClient(link));
    await until(() => s.pod != null);
    await s.unlinkPod();
    expect(s.podPhase, PodLinkPhase.unlinked);
    expect(s.pod, isNull);
    expect(link.closed, isTrue);
    await Future<void>.delayed(const Duration(milliseconds: 100));
    expect(tries, 0);
    expect(s.log, contains('pod unlinked'));
    await s.close();
  });

  test('a session without a way to reopen behaves as before', () async {
    final node = FakeRunningNode();
    final s = session(node);
    await s.open();
    final link = FakePodLink();
    await s.attachPod(PodClient(link));
    await until(() => s.pod != null);
    await link.drop();
    await until(() => s.log.any((l) => l.contains('pod link lost')));
    expect(s.podPhase, PodLinkPhase.linked);
    await s.close();
  });

  test('ending the game while the link is down stops the tries', () async {
    final node = FakeRunningNode();
    var tries = 0;
    final s = session(
      node,
      reopen: (lost) async {
        tries++;
        return null;
      },
    );
    await s.open();
    final link = FakePodLink();
    await s.attachPod(PodClient(link));
    await until(() => s.pod != null);
    await link.drop();
    await until(() => tries >= 2);
    await s.close();
    final seen = tries;
    await Future<void>.delayed(const Duration(milliseconds: 100));
    expect(tries, seen);
  });

  testWidgets('the screen says the link is lost, and the admin can unlink', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(400, 840);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final node = FakeRunningNode();
    final h = harness(
      runner: FakeNodeRunner(node),
      settings: AppSettings()..setPin('1234'),
    );
    final link = FakePodLink();
    // The link is opened again only when the test lets it.
    final session0 = session(node, reopen: (lost) async => null);
    await tester.runAsync(() async {
      await session0.open();
      await session0.attachPod(PodClient(link));
    });
    await tester.pumpWidget(
      h.app(
        home: PropGameScreen(
          setup: setup(),
          session: session0,
          modeName: 'Domination',
        ),
      ),
    );
    await tester.pump();
    expect(find.byKey(const Key('prop-pod-reconnecting')), findsNothing);
    await tester.runAsync(link.drop);
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.byKey(const Key('prop-pod-reconnecting')), findsOneWidget);
    expect(find.byIcon(Icons.link_off), findsOneWidget);

    await tester.tap(find.byKey(const Key('prop-admin')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('pin-field')), '1234');
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('admin-unlink-pod')));
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 50)),
    );
    await tester.pumpAndSettle();
    expect(session0.podPhase, PodLinkPhase.unlinked);
    expect(find.byKey(const Key('prop-pod-reconnecting')), findsNothing);
    await tester.runAsync(session0.close);
  });
}
