// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A phone prop's outputs on its I/O pod (lib/prop/prop_outputs.dart; draft
// RFC "The expansion port", increment 9): the pod's output descriptors from
// the shared IDENT vector, the box's rules (on only while the game runs and in
// the end's grace, off at the start, a pause, the end and a halt, the longest
// on, the 500 ms floor, too soon), what goes to the pod as its CMDs, the
// output.switched events, CMD 12 checked against the shared params vectors
// (cmd.json output_params), the lease's pings and the lost link.

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:atalaia_app/prop/prop_outputs.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:yaml/yaml.dart';

/// The pod of the shared vector pod_simple_output: buttons, ring, case and a
/// siren (feedback false).
PodIdent vectorPod() {
  final y = loadYaml(
    File('../protocol/vectors/capability_proxy.yaml').readAsStringSync(),
  ) as YamlMap;
  final idents = (y['pod_relay'] as YamlMap)['ident'] as YamlList;
  final v = idents.firstWhere((i) => i['name'] == 'pod_simple_output');
  return decodeIdent(hexDecode(v['payload'] as String));
}

PodIdent podWith(List<Map<String, Object?>> caps) =>
    PodIdent(fwVersion: '0.8.0', capabilities: caps, hasRadio: false);

void main() {
  late List<String> sent; // "<cap> <method> <args as JSON>"
  late List<Map<String, Object?>> switched;
  late int pings;
  late PropOutputs o;

  setUp(() {
    sent = [];
    switched = [];
    pings = 0;
    o = PropOutputs(
      send: (cap, method, args) => sent.add('$cap $method ${jsonEncode(args)}'),
      ping: () => pings++,
      onSwitched: (t, data) => switched.add(data),
    );
  });

  test('the pod\'s outputs come from its IDENT (the shared vector)', () {
    expect(o.has('siren'), isFalse);
    o.attach(vectorPod());
    expect(o.ids, ['siren']);
    expect(o.has('siren'), isTrue);
    expect(o.has('ring'), isFalse); // a ring is not an output
    o.attach(
      podWith([
        {'id': 'btn.1', 'type': 'button'},
      ]),
    );
    expect(o.ids, isEmpty);
    expect(o.scriptCall(0, 'siren', 'pulse', [1000]), isFalse);
  });

  test('a mode\'s calls: only while the game runs, each sent to the pod', () {
    o.attach(vectorPod());
    // No game yet: nothing switches, nothing is sent.
    expect(o.scriptCall(1000, 'siren', 'pulse', [5000]), isTrue);
    expect(sent, isEmpty);
    expect(switched, isEmpty);

    o.gameStart(2000);
    o.scriptCall(2000, 'siren', 'pulse', [5000]);
    expect(sent.single, 'siren pulse {"ms":5000}');
    expect(switched.single, {
      'capability': 'siren',
      'ms': 5000,
      'source': 'script',
    });
    expect(o.state('siren', 4000), (on: true, leftMs: 3000, source: 'script'));
    expect(o.state('siren', 7000).on, isFalse);

    // on() without a time: the longest on (30 s, the pod build's default).
    o.scriptCall(8000, 'siren', 'on', []);
    expect(sent.last, 'siren on {"ms":$podOutputMaxOnMs}');
    o.scriptCall(9000, 'siren', 'off', []);
    expect(sent.last, 'siren off {}');
    expect(switched.last, {'capability': 'siren', 'ms': 0, 'source': 'script'});

    // A pattern; a short pulse lasts 500 ms.
    o.scriptCall(10000, 'siren', 'pattern', [500, 500, 4000]);
    expect(sent.last, 'siren pattern {"on_ms":500,"off_ms":500,"ms":4000}');
    o.scriptCall(15000, 'siren', 'pulse', [100]);
    expect(sent.last, 'siren pulse {"ms":500}');

    // Too soon after an off (the pod would refuse it too), a faster pattern,
    // a pulse longer than the longest on.
    final before = sent.length;
    o.scriptCall(15600, 'siren', 'pulse', [1000]); // 100 ms after it went off
    o.scriptCall(16500, 'siren', 'pattern', [100, 500, 4000]);
    expect(sent.length, before);
    o.scriptCall(17000, 'siren', 'pulse', [600000]);
    expect(sent.last, 'siren pulse {"ms":$podOutputMaxOnMs}');
    // An output the pod lacks: not ours (the shell passes it on as before).
    expect(o.scriptCall(18000, 'smoke', 'pulse', [1000]), isFalse);
  });

  test('pause, end with its grace, halt: off, and the end horn', () {
    o.attach(vectorPod());
    o.gameStart(0);
    o.scriptCall(1000, 'siren', 'on', [20000]);
    final n = switched.length;
    o.pause(2000);
    expect(sent.last, 'siren off {}');
    expect(switched.length, n); // the game state turned it off: no event
    o.resume();
    expect(o.state('siren', 2500).on, isFalse); // not back on
    expect(o.scriptCall(2000, 'siren', 'pulse', [1000]), isTrue);
    expect(o.state('siren', 2100).on, isFalse); // too soon after the off

    o.scriptCall(3000, 'siren', 'pulse', [20000]);
    o.end(4000);
    expect(sent.last, 'siren off {}');
    // The end's grace: a horn for at most what is left of the 10 s.
    o.scriptCall(10000, 'siren', 'pulse', [9000]);
    expect(sent.last, 'siren pulse {"ms":4000}');
    expect(o.scriptCall(14000, 'siren', 'pulse', [1000]), isTrue);
    expect(o.state('siren', 14100).on, isFalse); // the grace is over
    o.end(15000); // ended already: nothing
    expect(o.game, 'ended');

    o.gameStart(20000);
    o.scriptCall(20000, 'siren', 'pulse', [5000]);
    o.halt(21000);
    expect(sent.last, 'siren off {}');
    expect(o.scriptCall(22000, 'siren', 'pulse', [1000]), isTrue);
    expect(o.state('siren', 22100).on, isFalse);
  });

  test('CMD 12: the shared params vectors, the src, every output off', () {
    o.attach(
      podWith([
        {'id': 'siren', 'type': 'output', 'feedback': false},
        {'id': 'strobe', 'type': 'output', 'feedback': false},
      ]),
    );
    o.gameStart(0);
    final v = jsonDecode(
      File('../protocol/vectors/cmd.json').readAsStringSync(),
    ) as Map;
    final p = v['output_params']! as Map;
    var t = 1000;
    for (final c in p['refused']! as List) {
      final params = (c['params'] as Map).cast<String, Object?>();
      expect(o.command(t, params), c['reason'], reason: '${c['name']}');
    }
    expect(sent, isEmpty);
    for (final c in p['valid']! as List) {
      t += 1000;
      final params = (c['params'] as Map).cast<String, Object?>();
      final r = o.command(t, params);
      // Taken as a box takes them; then the channel's own rules: a 10 ms
      // pattern is below a simple output's floor, a box without that output
      // ignores it.
      expect(
        ['ok', 'no_such', 'bad_args'],
        contains(r),
        reason: '${c['name']}',
      );
      if (c['name'] == 'pattern') {
        expect(r, 'ok');
        expect(
          sent.last,
          'strobe pattern {"on_ms":500,"off_ms":500,"ms":20000}',
        );
        expect(switched.last['source'], 'field');
      }
      if (c['name'] == 'pattern_shortest') expect(r, 'no_such');
      if (c['name'] == 'pulse') expect(r, 'ok');
    }
    t += 1000;
    expect(
      o.command(t, {
        'capability': 'siren',
        'act': 'on',
        'ms': 5000,
        'src': 'gm',
      }),
      'ok',
    );
    expect(switched.last, {'capability': 'siren', 'ms': 5000, 'source': 'gm'});
    t += 100;
    final n = sent.length;
    expect(o.command(t, {'capability': '*', 'act': 'off', 'src': 'gm'}), 'ok');
    // The siren, and the strobe still in its 20 s pattern.
    expect(sent.skip(n), ['siren off {}', 'strobe off {}']);
    expect(switched.last, {'capability': 'strobe', 'ms': 0, 'source': 'gm'});
  });

  test('a script starts an output at most twice a second', () {
    final errors = <String>[];
    o = PropOutputs(
      send: (cap, method, args) => sent.add('$cap $method ${jsonEncode(args)}'),
      ping: () => pings++,
      onScriptError: errors.add,
    );
    o.attach(vectorPod());
    o.gameStart(0);
    o.scriptCall(1000, 'siren', 'pulse', [5000]);
    o.scriptCall(1100, 'siren', 'pulse', [5000]); // a restart while on
    o.scriptCall(1200, 'siren', 'pulse', [5000]); // the third: dropped
    o.scriptCall(1300, 'siren', 'pulse', [5000]);
    expect(sent.length, 2);
    expect(errors, ['output siren: more than 2 starts a second, dropped']);
    o.scriptCall(1400, 'siren', 'off', []); // an off is never held back
    expect(sent.last, 'siren off {}');
    o.scriptCall(2100, 'siren', 'pulse', [1000]); // a second later
    expect(sent.last, 'siren pulse {"ms":1000}');
    o.scriptCall(2150, 'siren', 'pulse', [1000]);
    o.scriptCall(2200, 'siren', 'pulse', [1000]);
    expect(errors.length, 1); // said once a game
    o.gameStart(10000);
    o.scriptCall(10000, 'siren', 'pulse', [1000]);
    o.scriptCall(10100, 'siren', 'pulse', [1000]);
    o.scriptCall(10200, 'siren', 'pulse', [1000]);
    expect(errors.length, 2);
  });

  test('the lease: a ping every 500 ms while an output is on', () {
    o.attach(vectorPod());
    o.gameStart(0);
    for (var t = 0; t < 3000; t += 50) {
      o.tick(t);
    }
    expect(pings, 0); // nothing on: the pod needs nothing
    o.scriptCall(3000, 'siren', 'pulse', [2000]);
    for (var t = 3000; t < 7000; t += 50) {
      o.tick(t);
    }
    // 3500, 4000, 4500 (the CMD at 3000 counts), then off at 5000.
    expect(pings, 3);
  });

  test('the link goes: the pod turned them off, the model follows', () {
    o.attach(vectorPod());
    o.gameStart(0);
    o.scriptCall(1000, 'siren', 'on', [20000]);
    final n = (sent.length, switched.length);
    o.detach(2000);
    expect((sent.length, switched.length), n); // no link to send on
    expect(o.has('siren'), isFalse);
    expect(o.scriptCall(3000, 'siren', 'pulse', [1000]), isFalse);
    o.tick(3000);
    expect(pings, 0);
    // Linked again: its outputs, off; the game goes on.
    o.attach(vectorPod());
    expect(o.state('siren', 4000).on, isFalse);
    o.scriptCall(4000, 'siren', 'pulse', [1000]);
    expect(sent.last, 'siren pulse {"ms":1000}');
  });
}
