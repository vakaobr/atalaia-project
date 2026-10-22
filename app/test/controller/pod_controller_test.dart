// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A whole field on one machine with the phone as its controller (slice S4
// of PE24): the Android controller's engine on the real core, its radio an
// I/O pod (lib/controller/pod_modem.dart) running the pod firmware's own
// code (the host pod), and Field Boxes running theirs (the host box), on a
// shared UDP air; as controller/tests/test_box_e2e.py and test_pod_e2e.py
// do for the Pi. A join payload made by the phone, typed into a box's
// console, makes the box join the game; the phone's CMD and TIME drive it;
// its captures, STATE and scores reach the phone and are acknowledged; the
// phone restarting mid-game takes the game up again with a new epoch; two
// boxes score through Hold-All's field.lua on the phone.

import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:atalaia_app/controller/pod_modem.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/pod_host.dart';

final joinKey = Uint8List.fromList(List.generate(32, (i) => 100 + i));
const fast = {'capture_hold_ms': 1000, 'tick_s': 1, 'points_per_tick': 5};

Future<bool> waitFor(
  FutureOr<bool> Function() ok, {
  Duration timeout = const Duration(seconds: 8),
}) async {
  final end = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(end)) {
    if (await ok()) return true;
    await Future<void>.delayed(const Duration(milliseconds: 25));
  }
  return ok();
}

void main() {
  late AtalaiaCore core;
  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  late Directory tmp;
  late AirHub hub;
  late HostPod pod;
  late List<HostBox> boxes;
  ControllerEngine? engine;
  PodClient? client;
  Timer? ticker;

  /// The phone's controller: a new engine on the store, its pod linked
  /// again (a restart is the app's process going and coming back).
  Future<ControllerEngine> phone() async {
    client = PodClient(await SocketPodTransport.usb(pod));
    final m = PodModem(
      client!,
      pingInterval: const Duration(milliseconds: 200),
    );
    final e = engine = ControllerEngine(
      store: FileControllerStore(Directory('${tmp.path}/controller')),
      core: core,
      modem: m,
    )..joinKey = joinKey;
    await m.start();
    expect(await waitFor(() => m.isUp), isTrue, reason: 'the pod radio');
    ticker = Timer.periodic(const Duration(milliseconds: 100), (_) => e.tick());
    return e;
  }

  /// The app killed: no goodbye to the pod, whose link just goes.
  Future<void> crash() async {
    ticker?.cancel();
    await client?.close();
    engine?.close();
    engine = null;
  }

  Future<HostBox> box(String name) async {
    final b = await HostBox.start(
      hub,
      '${tmp.path}/$name',
      joinKey,
      name: name,
    );
    boxes.add(b);
    return b;
  }

  setUp(() async {
    tmp = Directory.systemTemp.createTempSync('atalaia-pod-ctrl-');
    hub = await AirHub.start();
    pod = await HostPod.start(airPeer: hub.port);
    hub.members.add(pod.airPort);
    boxes = [];
  });

  tearDown(() async {
    await crash();
    for (final b in boxes) {
      await b.kill();
    }
    await pod.stop();
    hub.close();
    tmp.deleteSync(recursive: true);
  });

  List<String> logTypes(ControllerEngine e, int gid, int node) => [
    for (final ev in e.log(gid))
      if (ev['node'] == node) ev['type']! as String,
  ];

  Map<String, Object?> node(ControllerEngine e, int id) =>
      e.nodes().firstWhere((n) => n['node_id'] == id, orElse: () => const {});

  int score(ControllerEngine e, int gid, String team) =>
      (e.score(gid)['teams']! as Map)[team]! as int;

  Future<int> join(ControllerEngine e, HostBox b) async {
    final j = e.issueJoin({'role': 'zone'});
    b.join(j['text']! as String);
    expect(
      await waitFor(() => b.logged('LOG join: joined')),
      isTrue,
      reason: '${b.lines.reversed.take(5)}',
    );
    return j['node_id']! as int;
  }

  test('join, play and end a game through the pod', () async {
    final e = await phone();
    final gid =
        e.createGame({
              'name': 'e2e',
              'mode_id': 'org.atalaia.domination',
              'params': fast,
            })['id']!
            as int;
    final alpha = await box('alpha');
    final nid = await join(e, alpha);

    // HELLO reaches the phone, which registers the box and acknowledges it.
    expect(await waitFor(() => node(e, nid)['fw_version'] == 'host'), isTrue);
    expect(
      await waitFor(() async => ((await alpha.status())['acked']! as int) >= 1),
      isTrue,
    );
    final st = await alpha.status();
    expect(
      [st['phase'], st['game_id'], st['node_id'], st['epoch']],
      [1, gid, nid, 1],
    );

    // Start: the CMD reaches the box, which starts the mode.
    e.startGame(gid, force: true);
    expect(
      await waitFor(() async => (await alpha.status())['phase'] == 2),
      isTrue,
    );

    // Red holds the button: a capture, logged once and acknowledged.
    alpha.hold(1, 1300);
    expect(
      await waitFor(() => logTypes(e, gid, nid).contains('zone.captured')),
      isTrue,
    );
    final cap = e.log(gid).firstWhere((ev) => ev['type'] == 'zone.captured');
    expect([cap['node'], cap['team'], cap['epoch']], [nid, 'red', 1]);
    expect(
      await waitFor(() async => (await alpha.status())['pending'] == 0),
      isTrue,
    );

    // Holding the zone scores; STATE brings the counters to the phone.
    expect(await waitFor(() => score(e, gid, 'red') >= 10), isTrue);
    expect(node(e, nid)['owner'], 'red');

    // Pause, resume and a message reach the box.
    e.pauseGame(gid, 'safety');
    expect(
      await waitFor(() async => (await alpha.status())['paused'] == true),
      isTrue,
    );
    e.resumeGame(gid);
    expect(
      await waitFor(() async => (await alpha.status())['paused'] == false),
      isTrue,
    );

    // End: the box ends and forgets the key.
    e.endGame(gid);
    expect(
      await waitFor(() async => (await alpha.status())['phase'] == 0),
      isTrue,
      reason: '${alpha.lines.reversed.take(8)}',
    );
    expect((await alpha.status())['have_key'], isFalse);
    expect(e.status()['tx_status'], containsPair('ok', greaterThan(0)));
  });

  test(
    'the phone restarts in the middle of a game and takes it up again',
    () async {
      var e = await phone();
      final gid =
          e.createGame({
                'name': 'e2e',
                'mode_id': 'org.atalaia.domination',
                'params': fast,
              })['id']!
              as int;
      final alpha = await box('alpha');
      final nid = await join(e, alpha);
      e.startGame(gid, force: true);
      expect(
        await waitFor(() async => (await alpha.status())['phase'] == 2),
        isTrue,
      );
      alpha.hold(1, 1300);
      expect(
        await waitFor(() => logTypes(e, gid, nid).contains('zone.captured')),
        isTrue,
      );
      expect(e.status()['tx_epoch'], 1);

      await crash();
      e = await phone();
      expect(e.keyLost, isFalse);
      expect(e.status()['tx_epoch'], 2); // a new epoch under the same key
      expect(e.liveGame!['state'], 'running');

      // The box is still heard, and the phone still reaches it.
      alpha.hold(2, 1300);
      expect(
        await waitFor(
          () =>
              logTypes(e, gid, nid).where((t) => t == 'zone.captured').length ==
              2,
          timeout: const Duration(seconds: 10),
        ),
        isTrue,
        reason: '${alpha.lines.reversed.take(8)}',
      );
      e.endGame(gid);
      expect(
        await waitFor(() async => (await alpha.status())['phase'] == 0),
        isTrue,
      );
    },
  );

  test("Hold-All: two boxes, the phone's field.lua scores", () async {
    final e = await phone();
    final gid =
        e.createGame({
              'name': 'hold all',
              'mode_id': 'org.atalaia.holdall',
              'params': fast,
            })['id']!
            as int;
    final alpha = await box('alpha');
    final bravo = await box('bravo');
    final a = await join(e, alpha);
    final b = await join(e, bravo);
    e.startGame(gid, force: true);
    expect(
      await waitFor(() async => (await bravo.status())['phase'] == 2),
      isTrue,
    );
    alpha.hold(1, 1300);
    expect(await waitFor(() => node(e, a)['owner'] == 'red'), isTrue);
    expect(score(e, gid, 'red'), 0); // one box is not enough
    bravo.hold(1, 1300);
    expect(
      await waitFor(
        () => logTypes(e, gid, e.nodeId).contains('holdall.scoring_start'),
      ),
      isTrue,
    );
    expect(await waitFor(() => score(e, gid, 'red') >= 10), isTrue);
    expect(node(e, b)['owner'], 'red');
    e.endGame(gid);
  });
}
