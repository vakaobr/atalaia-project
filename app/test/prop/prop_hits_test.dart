// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A phone prop's hit sensors and module outputs on its I/O pod's expansion
// port (lib/prop/prop_hits.dart, lib/prop/prop_outputs.dart; draft RFC "The
// expansion port", increment 9, the port half): the pod's IDENT from the
// shared vector pod_port_modules, the hit sensors armed as a box arms them
// (the script's arming kept by id, told to the pod only while the game runs,
// again after the pod links again), a hit's channel, the EVT pod.modules'
// longest ons in the outputs' model, and an output kept on when the pod sends
// IDENT again with its link up.

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:atalaia_app/prop/prop_hits.dart';
import 'package:atalaia_app/prop/prop_outputs.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:yaml/yaml.dart';

YamlMap _vectors() => loadYaml(
  File('../protocol/vectors/capability_proxy.yaml').readAsStringSync(),
) as YamlMap;

/// The pod of the shared vector pod_port_modules: a button, a target's hit
/// sensor, a simple siren and an out4 module's four channels.
PodIdent vectorPod() {
  final idents = (_vectors()['pod_relay'] as YamlMap)['ident'] as YamlList;
  final v = idents.firstWhere((i) => i['name'] == 'pod_port_modules');
  return decodeIdent(hexDecode(v['payload'] as String));
}

/// An EVT of the shared vectors, decoded.
ProxyMessage vectorEvt(String name) {
  final evts = _vectors()['evt'] as YamlList;
  final v = evts.firstWhere((e) => e['name'] == name);
  return decodeMessage(hexDecode(v['payload'] as String));
}

void main() {
  group('hit sensors', () {
    late List<String> sent;
    late PropHits h;
    setUp(() {
      sent = [];
      h = PropHits(send: (cap, method, args) => sent.add('$cap $method'));
    });

    test('the pod\'s hit sensors come from its IDENT', () {
      h.attach(vectorPod().capabilities);
      expect(h.ids, ['hit']);
      expect(PropHits.isHit('hit'), isTrue);
      expect(PropHits.isHit('hit.2'), isTrue);
      expect(PropHits.isHit('hit.9'), isFalse);
      expect(PropHits.isHit('siren'), isFalse);
    });

    test('armed only while the game runs; kept by id; told again after a '
        'new link', () {
      h.attach(vectorPod().capabilities);
      // Between games: kept, not told.
      expect(h.scriptCall('hit', 'arm'), isTrue);
      expect(sent, isEmpty);
      expect(h.take(), isFalse);
      // The game starts: the arming of before is forgotten (a box's too).
      h.gameStart();
      expect(sent, isEmpty);
      h.scriptCall('hit', 'arm');
      expect(sent, ['hit arm']);
      expect(h.take(), isTrue);
      // A second sensor not on the pod yet: kept.
      h.scriptCall('hit.2', 'arm');
      expect(sent, ['hit arm']);
      // Paused: disarmed; resumed: armed again.
      h.pause();
      expect(h.take(), isFalse);
      h.resume();
      expect(sent, ['hit arm', 'hit disarm', 'hit arm']);
      // The pod links again (it forgot): told again; a second sensor now.
      h.detach();
      h.attach([
        {'id': 'hit', 'type': 'hit', 'channel': 1},
        {'id': 'hit.2', 'type': 'hit', 'channel': 2},
      ]);
      expect(sent.sublist(3), ['hit arm', 'hit.2 arm']);
      // The script disarms one; the game ends: every one disarmed, forgotten.
      h.scriptCall('hit.2', 'disarm');
      h.end();
      expect(sent.sublist(5), ['hit.2 disarm', 'hit disarm']);
      expect(h.armed, isEmpty);
      // Other calls are not the sensors'.
      expect(h.scriptCall('hit', 'fire'), isFalse);
      expect(h.scriptCall('ring', 'arm'), isFalse);
    });

    test('a hit\'s channel reaches the mode (draft RFC 0000 Amendment 5)', () {
      final inputs = PodInputs(
        const PodIdent(
          fwVersion: '0.8.0',
          capabilities: [
            {'id': 'hit', 'type': 'hit', 'channel': 1},
            {'id': 'hit.2', 'type': 'hit', 'channel': 2},
          ],
          hasRadio: false,
        ),
      );
      Map<String, Object?> tag(List<int> u, List<int>? t) => const {};
      final second = inputs.input(
        const ProxyMessage(
          capId: 'hit.2',
          name: 'hit',
          data: {'strength': 90, 'channel': 2},
          seq: 1,
        ),
        tagData: tag,
      );
      expect(second?.$1, 'hit.hit');
      expect(second?.$2, {'strength': 90, 'channel': 2});
      final first = inputs.input(
        const ProxyMessage(
          capId: 'hit',
          name: 'hit',
          data: {'strength': 200},
          seq: 2,
        ),
        tagData: tag,
      );
      expect(first?.$2, {'strength': 200});
    });
  });

  group('a module\'s outputs', () {
    late List<String> sent;
    late PropOutputs o;
    setUp(() {
      sent = [];
      o = PropOutputs(
        send: (cap, method, args) =>
            sent.add('$cap $method ${jsonEncode(args)}'),
        ping: () {},
      );
    });

    test('lent beside the simple output, each at the longest on the pod '
        'told (the shared vector pod_modules)', () {
      o.attach(vectorPod());
      expect(o.ids, ['siren', 'siren.2', 'strobe', 'smoke', 'out.4']);
      expect(o.maxOnMs('strobe'), podOutputMaxOnMs);
      final evt = vectorEvt('pod_modules');
      expect(evt.capId, 'pod');
      expect(evt.name, 'modules');
      o.maxOn((evt.data['max_on_s']! as Map).cast<String, Object?>());
      expect(o.maxOnMs('siren'), 30000);
      expect(o.maxOnMs('strobe'), 20000);
      // An on without a time lasts the pod's longest on.
      o.gameStart(0);
      o.scriptCall(1000, 'strobe', 'on', const []);
      expect(sent.last, 'strobe on {"ms":20000}');
      // A later IDENT (a module plugged in) keeps the longest ons.
      o.attach(vectorPod());
      expect(o.maxOnMs('strobe'), 20000);
      // Values out of range are left at 30 s.
      o.maxOn({'strobe': 0, 'smoke': 601, 'siren': 'x', 'out.4': 600});
      expect(o.maxOnMs('strobe'), podOutputMaxOnMs);
      expect(o.maxOnMs('out.4'), 600000);
    });

    test('an output on stays on when the pod sends IDENT again with its link '
        'up, and is off after a lost link', () {
      o.attach(vectorPod());
      o.gameStart(0);
      o.scriptCall(1000, 'siren', 'pulse', const [10000]);
      expect(o.state('siren', 2000).on, isTrue);
      o.attach(vectorPod()); // a module plugged in: IDENT again
      expect(o.state('siren', 2000).on, isTrue);
      expect(o.state('siren', 2000).leftMs, 9000);
      o.detach(3000);
      o.attach(vectorPod());
      expect(o.state('siren', 3000).on, isFalse);
    });
  });
}
