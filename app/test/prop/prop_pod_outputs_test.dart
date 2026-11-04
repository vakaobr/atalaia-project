// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A phone prop's outputs through its I/O pod (draft RFC "The expansion port",
// increment 9): the prop session (lib/prop/prop_session.dart) with the pod
// firmware's own code on this machine (the host pod, `--simple-out siren`:
// main/pod/pod_outputs.c, the box's output layer and burst scheduler) and the
// controller's radio (the host modem). The mode's cap("siren"):pulse and the
// controller's CMD 12 over the radio switch the pod's output; a pause turns it
// off; the session's end (its link closed) too; a phone that stops speaking
// with the output on loses it after 1.5 s (the pod's lease), and one that
// keeps speaking keeps it.

@Timeout(Duration(minutes: 3))
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/radio/pod_radio_link.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/fakes.dart';
import '../support/pod_host.dart';

final key = Uint8List.fromList(List.generate(16, (i) => 0x70 + i));

final joinPayload = JoinPayload(
  gameId: 778,
  gameKey: key,
  nodeId: 6,
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

const texts = PropTexts(
  notificationTitle: '',
  notificationRunning: '',
  notificationLeft: '',
);

/// The mode's cap(target):method(args), as the core gives it to the shell.
void scriptCall(
  FakeRunningNode node,
  String target,
  String method,
  List<Object?> args,
) => node.emit(
  NodeCommandOutput(
    NodeCommand(
      tMs: node.timeMs,
      target: target,
      method: method,
      argsJson: jsonEncode(args),
    ),
  ),
);

/// The prop's loop turning, as its ticker does on a phone (the tests' clock
/// is manual): the outputs' lease goes with it.
Timer turning(PropSession s) => Timer.periodic(
  const Duration(milliseconds: 50),
  (_) => unawaited(s.advance(50)),
);

/// Until a simple output may switch on again: the phone's model has the
/// siren off (its own pulse may end later than the pod's, which a stalled
/// phone's lease ends early), then a simple output's 500 ms floor and a
/// margin, on the wall clock both sides keep.
Future<void> settled(PropSession s) async {
  await eventually(
    () => !s.outputs.state('siren', DateTime.now().millisecondsSinceEpoch).on,
    "the phone's model off",
  );
  await Future<void>.delayed(const Duration(milliseconds: 600));
}

void main() {
  if (skipFileWithoutHosts(['ATALAIA_POD_HOST', 'ATALAIA_MODEM_HOST'])) return;
  late AtalaiaCore core;

  Uint8List? encode({
    required int node,
    required int seq,
    required int tMs,
    required String type,
    required int team,
    required int squad,
    required int prio,
    required String? dataJson,
  }) => core
      .encodeEvent(
        node: node,
        seq: seq,
        tMs: tMs,
        type: type,
        team: team,
        squad: squad,
        prio: prio,
        dataJson: dataJson,
      )
      .bytes;

  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  test('the mode and the controller switch the pod\'s siren; pause and the '
      'end turn it off', () async {
    final hub = await AirHub.start();
    final modem = await HostModem.start(airPeer: hub.port);
    hub.members.add(modem.airPort);
    final pod = await HostPod.start(
      airPeer: hub.port,
      args: ['--simple-out', 'siren'],
    );
    hub.members.add(pod.airPort);
    final ctl = await ModemLink.connect(modem);
    var ctlSeq = 0;
    void controllerSends(RfCmd c) {
      final h = RfHeader.v1(
        gameId: 778,
        source: 0,
        seq: ctlSeq++,
        hopLimit: 2,
        type: RfType.cmd,
      );
      ctl.send(ModemLink.tx, [...h.encode(), ...c.encode()]);
    }

    ctl.send(
      ModemLink.cmd,
      radioConfigure(
        gameId: 778,
        nodeId: 0,
        epoch: 1,
        maxHops: 2,
        channelHz: 869525000,
        key: key,
      ),
    );
    await ctl.wait(ModemLink.status);

    final node = FakeRunningNode();
    final mode = ModeCatalog.builtin().compose('org.atalaia.domination');
    const teams = ['red', 'blue'];
    final s = PropSession(
      setup: PropSetup(
        mode: mode,
        role: 'zone',
        teams: teams,
        params: mode.resolveParams(const {}, teams),
        nodeId: 6,
        join: joinPayload,
      ),
      runner: FakeNodeRunner(node),
      device: FakeDevice(),
      texts: texts,
      clock: GameClock.manual,
      radioLinkFor: (client) => PodRadioLink(
        pod: client,
        join: joinPayload,
        epochs: MemoryEpochStore(),
        encodeEvent: encode,
        hello: const {'node_name': 'phone-6', 'fw_version': 'app-test'},
        retryAfter: const Duration(milliseconds: 500),
        tick: const Duration(milliseconds: 20),
      ),
    );
    Timer? loop;
    try {
      await s.open();
      await s.attachPod(PodClient(await SocketPodTransport.usb(pod)));
      await eventually(() => s.radio?.linked ?? false, 'radio link');
      expect(s.outputs.ids, ['siren']);
      loop = turning(s);

      // The controller starts the game over the radio.
      controllerSends(const RfCmd(cmd: 0));
      await eventually(() => s.phase == PropPhase.running, 'running');

      // The mode's cap("siren"):pulse(2000): on at the pod, then off by
      // itself; the controller hears output.switched over the radio.
      var mark = pod.mark;
      final heard = ctl.frames.length;
      scriptCall(node, 'siren', 'pulse', [2000]);
      await pod.wait('OUTPUT siren on', from: mark);
      await pod.wait('OUTPUT siren off', from: mark);
      await ctl.wait(
        ModemLink.rx,
        from: heard,
        match: (p) =>
            RfHeader.decode(p).type == RfType.event &&
            latin1.decode(p, allowInvalid: true).contains('siren'),
      );

      // CMD 12 from the controller (a field script, a scenario trigger), more
      // than 500 ms after the last change (a simple output's floor) on both
      // sides: the pod's, and the phone's model, which refuses an on within
      // 500 ms of its own off (too_soon). The two offs differ when the pod
      // ends the pulse early (a phone that stalled 1.5 s under load: its
      // lease), so the model's is waited for too, not only the pod's line.
      await settled(s);
      mark = pod.mark;
      controllerSends(
        const RfCmd(
          cmd: 12,
          params: {
            'capability': 'siren',
            'act': 'pulse',
            'ms': 20000,
            'src': 'field',
          },
          dest: 6,
        ),
      );
      await pod.wait('OUTPUT siren on', from: mark);

      // The controller pauses the game: off at once, and not back on resume.
      mark = pod.mark;
      controllerSends(const RfCmd(cmd: 1));
      await pod.wait('OUTPUT siren off', from: mark);
      // The session takes a resume only once its phase is paused (it follows
      // the core's snapshots); a controller's TIME beacons would repeat it.
      await eventually(
        () => s.phase == PropPhase.paused && s.outputs.game == 'paused',
        'paused',
      );
      controllerSends(const RfCmd(cmd: 2));
      await eventually(
        () => s.phase == PropPhase.running && s.outputs.game == 'running',
        'resumed',
      );
      expect(
        pod.lines.skip(mark).where((l) => l.startsWith('OUTPUT siren on')),
        isEmpty,
      );
      await settled(s);

      // On again, then the session ends: its link to the pod closes and the
      // pod turns the siren off itself.
      mark = pod.mark;
      scriptCall(node, 'siren', 'on', [20000]);
      await pod.wait('OUTPUT siren on', from: mark);
      loop.cancel();
      await s.close();
      await pod.wait('OUTPUT siren off', from: mark);
      // The pod turned it off itself: for the lost link (or, on a machine so
      // loaded that the phone's loop stalled for 1.5 s first, for its silence).
      final st = await pod.status();
      expect(
        (st['output_link_offs']! as int) + (st['output_quiet_offs']! as int),
        greaterThanOrEqualTo(1),
      );
    } finally {
      loop?.cancel();
      await s.close();
      await ctl.close();
      await pod.stop();
      await modem.stop();
      hub.close();
    }
  });

  test('the pod\'s lease: a silent phone loses its output, a speaking one '
      'keeps it', () async {
    final pod = await HostPod.start(
      args: ['--no-radio', '--simple-out', 'siren'],
    );
    final node = FakeRunningNode();
    final mode = ModeCatalog.builtin().compose('org.atalaia.domination');
    final s = PropSession(
      setup: PropSetup(
        mode: mode,
        role: 'zone',
        teams: const ['red', 'blue'],
        params: mode.resolveParams(const {}, const ['red', 'blue']),
      ),
      runner: FakeNodeRunner(node),
      device: FakeDevice(),
      texts: texts,
      clock: GameClock.manual,
    );
    Timer? loop;
    try {
      await s.open();
      await s.attachPod(PodClient(await SocketPodTransport.usb(pod)));
      await eventually(() => s.outputs.has('siren'), 'the pod\'s siren');
      await s.start();
      expect(s.phase, PropPhase.running);

      // On for 30 s, and the phone says nothing more (its loop is stopped):
      // the pod turns it off after 1.5 s of silence.
      var mark = pod.mark;
      scriptCall(node, 'siren', 'on', [30000]);
      await pod.wait('OUTPUT siren on', from: mark);
      await pod.wait('OUTPUT siren off', from: mark);
      expect((await pod.status())['output_quiet_offs'], 1);

      // With the loop turning, the phone pings the pod every 500 ms: a 3 s
      // pulse lasts its 3 s. On a machine so loaded that the test's own timer
      // stalls for 1.5 s the pod rightly turns it off early (its quiet count
      // says so); then the pulse is tried again, up to three times.
      loop = turning(s);
      var quiet = 1;
      var lasted = 0;
      for (var attempt = 0; attempt < 3 && lasted <= 2500; attempt++) {
        await Future<void>.delayed(const Duration(milliseconds: 600));
        mark = pod.mark;
        scriptCall(node, 'siren', 'pulse', [3000]);
        await pod.wait('OUTPUT siren on', from: mark);
        final on = Stopwatch()..start();
        await pod.wait('OUTPUT siren off', from: mark);
        lasted = on.elapsedMilliseconds;
        final q = (await pod.status())['output_quiet_offs']! as int;
        // Off before its time only for the phone's silence, never otherwise.
        if (lasted <= 2500) expect(q, quiet + 1);
        quiet = q;
      }
      expect(lasted, greaterThan(2500));
    } finally {
      loop?.cancel();
      await s.close();
      await pod.stop();
    }
  });
}
