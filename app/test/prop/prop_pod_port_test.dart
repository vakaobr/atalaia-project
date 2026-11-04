// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A phone prop's target and output module through its I/O pod's expansion
// port (draft RFC "The expansion port", increment 9, the port half): the prop
// session (lib/prop/prop_session.dart) with the pod firmware's own code on
// this machine (the host pod, `--module target --module out4
// --module-outputs`: main/pod/pod_port.c on the box's port driver, the
// modules simulated on the real module core). The pod lends the target's hit
// and the module's channels; its EVT pod.modules gives the prop node.modules
// and the longest ons; the mode's arm reaches the plate only while the game
// runs and its hits reach the mode; the mode's pulse switches the module's
// relay, and the session's end turns it off. A pod with every part has no
// room in IDENT for the module's last three channels: it withholds them, and
// the prop tells the controller node.outputs_disabled with them (decision
// PROPC-6).

@Timeout(Duration(minutes: 3))
library;

import 'dart:async';
import 'dart:convert';

import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fakes.dart';
import '../support/pod_host.dart';

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

/// The prop's loop turning, as its ticker does on a phone.
Timer turning(PropSession s) => Timer.periodic(
  const Duration(milliseconds: 50),
  (_) => unawaited(s.advance(50)),
);

void main() {
  if (skipFileWithoutHosts(['ATALAIA_POD_HOST'])) return;

  test('the pod lends its modules: node.modules, the longest ons, a hit '
      'armed while the game runs, a module relay switched', () async {
    final pod = await HostPod.start(
      // A pod with one button and nothing else of its own, so that IDENT has
      // room for every output (a pod with every part and a target lends the
      // module's hit and none of its outputs: pod.h, POD_IDENT_TRIM).
      args: [
        '--no-radio',
        '--buttons',
        '1',
        '--no-keypad',
        '--no-nfc',
        '--no-leds',
        '--no-audio',
        '--no-case',
        '--simple-out',
        'siren',
        '--module',
        'target',
        '--module',
        'out4',
        '--module-outputs',
        '--module-max-on',
        '60',
      ],
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
      loop = turning(s);
      await eventually(
        () => s.outputs.has('strobe') && s.hits.ids.contains('hit'),
        'the pod\'s modules',
      );
      expect(s.outputs.ids, ['siren', 'siren.2', 'strobe', 'smoke', 'out.4']);
      // The EVT pod.modules: node.modules' text, the longest ons (the pod's
      // 60 s, or the module's own when lower: smoke 30 s).
      await eventually(
        () => s.outputs.maxOnMs('strobe') == 60000,
        'the longest ons',
      );
      expect(s.outputs.maxOnMs('smoke'), 30000);
      expect(s.outputs.maxOnMs('siren'), 30000);
      expect(
        s.log,
        contains(
          'node.modules g33:servo:siren;58:target/1.0.0:hit;'
          '5c:out4/1.0.0:siren.2,strobe,smoke,out.4',
        ),
      );
      // Every output lent: node.outputs_disabled's empty text.
      expect(s.log, contains('node.outputs_disabled (none)'));

      // The mode arms the plate before the game: kept, not told; a hit is not
      // felt.
      scriptCall(node, 'hit', 'arm', const []);
      var mark = pod.mark;
      pod.send('hit 58 120');
      await pod.wait('LOG module 58: hit 120 not kept', from: mark);

      // The game starts and the mode arms it: a hit reaches the mode.
      await s.start();
      scriptCall(node, 'hit', 'arm', const []);
      for (var i = 0; i < 20; i++) {
        mark = pod.mark;
        pod.send('hit 58 180');
        final line = await pod.wait('LOG module 58: hit 180', from: mark);
        if (line.endsWith('felt')) break;
        await Future<void>.delayed(const Duration(milliseconds: 50));
      }
      await eventually(
        () => node.inputs.any(
          (i) => i.$1 == 'hit.hit' && i.$2?['strength'] == 180,
        ),
        'hit.hit',
      );

      // The mode pulses the module's strobe: its relay (channel 2) on, then
      // off by itself.
      mark = pod.mark;
      scriptCall(node, 'strobe', 'pulse', const [1500]);
      await pod.wait('MODULE 5c outputs=0x02', from: mark);
      await pod.wait('MODULE 5c outputs=0x00', from: mark);

      // On again, then the session ends: its link closes, and the pod turns
      // the module's relay off itself.
      await Future<void>.delayed(const Duration(milliseconds: 600));
      mark = pod.mark;
      scriptCall(node, 'smoke', 'on', const [20000]);
      await pod.wait('MODULE 5c outputs=0x04', from: mark);
      loop.cancel();
      await s.close();
      await pod.wait('MODULE 5c outputs=0x00', from: mark);
    } finally {
      loop?.cancel();
      await s.close();
      await pod.stop();
    }
  });

  test('a pod with every part withholds the out4\'s last three channels: '
      'node.outputs_disabled names them', () async {
    final pod = await HostPod.start(
      args: ['--no-radio', '--module', 'out4', '--module-outputs'],
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
      loop = turning(s);
      await eventually(
        () => s.log.contains('node.modules 5c:out4/1.0.0:siren'),
        'node.modules with the lent channel',
      );
      expect(s.outputs.ids, ['siren']);
      expect(
        s.log,
        contains('node.outputs_disabled 5c:out4/1.0.0:strobe,smoke,out.4'),
      );
      // node.outputs_disabled goes just before node.modules, as on a box.
      final at = s.log.indexOf(
        'node.outputs_disabled 5c:out4/1.0.0:strobe,smoke,out.4',
      );
      expect(s.log.indexOf('node.modules 5c:out4/1.0.0:siren'), at + 1);
    } finally {
      loop?.cancel();
      await s.close();
      await pod.stop();
    }
  });
}
