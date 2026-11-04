// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A phone prop's HELLO lists its capability types (decisions PROPC-1 to
// PROPC-4), so the controllers' start check takes it as it takes a box: the
// phone's own parts, then what its pod lends in IDENT. The session on a
// Wi-Fi link (protocol/prop-link.md) says them before its first HELLO, and
// again when the pod's IDENT changes them, the pod's link breaks or the
// person unlinks the pod: with a pod simulated at the transport, and with
// the pod firmware's own code (the host pod) whose target module is
// unplugged and plugged in again.
//
// Its pod's outputs fitted but not lent (EVT pod.modules' `withheld`) reach
// the controller as node.outputs_disabled, as a box's outputs its admin has
// not enabled (decision PROPC-6).

@Timeout(Duration(minutes: 2))
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/controller/prop_link.dart';
import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/platform/services.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_pod_link.dart';
import '../support/fakes.dart';
import '../support/pod_host.dart';

const texts = PropTexts(
  notificationTitle: '',
  notificationRunning: '',
  notificationLeft: '',
);

final join = JoinPayload(
  gameId: 9,
  gameKey: Uint8List(16),
  nodeId: 3,
  controllerId: 0,
  channelHz: 869525000,
  maxHops: 2,
  teams: const ['red', 'blue'],
  modeId: 'org.atalaia.target_windows',
  role: 'target',
  gameSeed: 1,
  params: null,
  kind: JoinKind.node,
  caSha256: Uint8List(32),
  urls: const ['https://10.0.2.2:8443'],
);

/// The controller's end of the prop's Wi-Fi link: it welcomes the prop and
/// keeps what the prop sends.
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

  /// The events the prop sent of that type, their data in order.
  List<Map<String, Object?>> events(String type) => [
    for (final m in got)
      if (m['type'] == 'event' && (m['event']! as Map)['type'] == type)
        ((m['event']! as Map)['data']! as Map).cast<String, Object?>(),
  ];

  /// The event types the prop sent, in order.
  List<Object?> get eventTypes => [
    for (final m in got)
      if (m['type'] == 'event') (m['event']! as Map)['type'],
  ];

  /// The capability type ids of every HELLO, in order.
  List<List<Object?>> get hellos => [
    for (final m in got)
      if (m['type'] == 'hello') (m['capabilities']! as List).cast<Object?>(),
  ];

  @override
  Future<void> close() async {
    if (!_in.isClosed) await _in.close();
  }
}

(PropSession, LinkEnd) linkedSession(DeviceFeatures features) {
  final end = LinkEnd()..push({'type': 'challenge', 'nonce': 'AAAA'});
  final link = PropLink(
    join: join,
    urls: join.urls!,
    connect: (_) async => end,
    hello: {'node_name': 'phone-3', 'capabilities': const <int>[]},
  );
  final mode = ModeCatalog.builtin().compose('org.atalaia.target_windows');
  const teams = ['red', 'blue'];
  final s = PropSession(
    setup: PropSetup(
      mode: mode,
      role: 'target',
      teams: teams,
      params: mode.resolveParams(const {}, teams),
      nodeId: 3,
      join: join,
    ),
    runner: FakeNodeRunner(FakeRunningNode()),
    device: FakeDevice(features_: features),
    texts: texts,
    clock: GameClock.manual,
    link: link,
  );
  return (s, end);
}

/// A pod with two team buttons, a ring, a speaker, an NFC reader, a case
/// switch and a battery gauge, a target's hit sensor and a siren lent.
const lendingPod = PodIdent(
  fwVersion: '0.8.0',
  capabilities: [
    {'id': 'btn.red', 'type': 'button', 'team': 'red'},
    {'id': 'btn.blue', 'type': 'button', 'team': 'blue'},
    {'id': 'ring', 'type': 'led', 'count': 24, 'rgb': true},
    {'id': 'buzzer', 'type': 'audio'},
    {'id': 'nfc', 'type': 'nfc'},
    {'id': 'case', 'type': 'tamper'},
    {'id': 'battery', 'type': 'battery'},
    {'id': 'hit', 'type': 'hit'},
    {'id': 'siren', 'type': 'output', 'feedback': false},
  ],
  hasRadio: false,
);

// The phone's own: button 1, keypad 2, display 3, led 4, audio 5.
const screenAndSpeaker = [1, 2, 3, 4, 5];

/// The node.modules and node.outputs_disabled the prop sent, in order.
List<Object?> told(LinkEnd end) => [
  for (final t in end.eventTypes)
    if (t == 'node.modules' || t == 'node.outputs_disabled') t,
];

Future<void> settle() async {
  for (var i = 0; i < 10; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

void main() {
  test("the phone's own parts are in its first HELLO", () async {
    final (s, end) = linkedSession(
      const DeviceFeatures(
        nfc: true,
        location: true,
        accelerometer: true,
        camera: true,
        vibrator: true,
      ),
    );
    addTearDown(s.dispose);
    await s.open();
    await settle();
    // The screen's parts, the speaker, NFC 6 and GPS 8; never the camera,
    // the accelerometer or the vibrator, which the shell gives no mode.
    expect(end.hellos, [
      [...screenAndSpeaker, 6, 8],
    ]);
    expect(s.helloCapabilities, [...screenAndSpeaker, 6, 8]);
  });

  test("a pod's IDENT adds what it lends; a broken link and an unlink take "
      'it away', () async {
    final (s, end) = linkedSession(const DeviceFeatures());
    addTearDown(s.dispose);
    await s.open();
    await settle();
    expect(end.hellos, [screenAndSpeaker]);

    final pod = FakePodLink(ident: lendingPod);
    await s.attachPod(PodClient(pod));
    await until(() => end.hellos.length == 2);
    // NFC 6, hit 10 and output 11 from the pod; its case switch and battery
    // gauge are not listed (as a phone prop gives the mode neither).
    expect(end.hellos.last, [...screenAndSpeaker, 6, 10, 11]);
    expect(s.log, contains('HELLO capabilities 1,2,3,4,5,6,10,11'));

    // The pod goes out of reach before the game: HELLO without it.
    await pod.drop();
    await until(() => end.hellos.length == 3);
    expect(end.hellos.last, screenAndSpeaker);

    // Another pod, then the person unlinks it: HELLO without it again; a
    // change that leaves the list as it was sends nothing.
    final second = FakePodLink(
      ident: const PodIdent(
        fwVersion: '0.8.0',
        capabilities: [
          {'id': 'siren', 'type': 'output', 'feedback': false},
        ],
        hasRadio: false,
      ),
    );
    await s.attachPod(PodClient(second));
    await until(() => end.hellos.length == 4);
    expect(end.hellos.last, [...screenAndSpeaker, 11]);
    await s.unlinkPod();
    await settle();
    expect(end.hellos.length, 5);
    expect(end.hellos.last, screenAndSpeaker);
  });

  test("a pod's withheld outputs are node.outputs_disabled, with each "
      'node.modules and when they change; an older pod says nothing of '
      'them', () async {
    final (s, end) = linkedSession(const DeviceFeatures());
    addTearDown(s.dispose);
    await s.open();
    await settle();
    final pod = FakePodLink(ident: lendingPod);
    await s.attachPod(PodClient(pod));
    await until(() => end.hellos.length == 2);

    // A pod from before: no `withheld`, so no node.outputs_disabled.
    pod.event('pod', 'modules', 1, {
      'modules': '58:target/1.0.0:hit',
      'max_on_s': <String, Object?>{},
    });
    await until(() => end.events('node.modules').length == 1);
    expect(end.events('node.outputs_disabled'), isEmpty);

    // The shared vector pod_modules_withheld: an out4 with one channel lent;
    // node.outputs_disabled first, then node.modules, as a box sends them.
    pod.event('pod', 'modules', 2, {
      'modules': '5c:out4/1.0.0:siren',
      'max_on_s': {'siren': 30},
      'withheld': '5c:out4/1.0.0:strobe,smoke,out.4',
    });
    await until(() => end.events('node.modules').length == 2);
    expect(end.events('node.outputs_disabled'), [
      {'modules': '5c:out4/1.0.0:strobe,smoke,out.4'},
    ]);
    expect(end.events('node.modules').last, {'modules': '5c:out4/1.0.0:siren'});
    expect(told(end), [
      'node.modules',
      'node.outputs_disabled',
      'node.modules',
    ]);
    expect(
      s.log,
      contains('node.outputs_disabled 5c:out4/1.0.0:strobe,smoke,out.4'),
    );

    // The same EVT again (after an IDENT): nothing new.
    pod.event('pod', 'modules', 3, {
      'modules': '5c:out4/1.0.0:siren',
      'max_on_s': {'siren': 30},
      'withheld': '5c:out4/1.0.0:strobe,smoke,out.4',
    });
    await settle();
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(end.events('node.outputs_disabled').length, 1);
    expect(end.events('node.modules').length, 2);

    // Only the withheld outputs change (a simple output's are not in the
    // text): node.outputs_disabled alone.
    pod.event('pod', 'modules', 4, {
      'modules': '5c:out4/1.0.0:siren',
      'max_on_s': {'siren': 30},
      'withheld': 'g33:servo:horn;5c:out4/1.0.0:strobe,smoke,out.4',
    });
    await until(() => end.events('node.outputs_disabled').length == 2);
    expect(end.events('node.outputs_disabled').last, {
      'modules': 'g33:servo:horn;5c:out4/1.0.0:strobe,smoke,out.4',
    });
    expect(end.events('node.modules').length, 2);

    // Every one lent: the empty text, as a box with every output enabled.
    pod.event('pod', 'modules', 5, {
      'modules': '5c:out4/1.0.0:siren,strobe,smoke,out.4',
      'max_on_s': {'siren': 30, 'strobe': 30, 'smoke': 30, 'out.4': 30},
      'withheld': '',
    });
    await until(() => end.events('node.outputs_disabled').length == 3);
    expect(end.events('node.outputs_disabled').last, {'modules': ''});
    expect(s.log, contains('node.outputs_disabled (none)'));

    // Withheld again, then the person unlinks the pod: the empty text before
    // node.modules' empty one.
    pod.event('pod', 'modules', 6, {
      'modules': '5c:out4/1.0.0:siren',
      'max_on_s': {'siren': 30},
      'withheld': '5c:out4/1.0.0:strobe,smoke,out.4',
    });
    await until(() => end.events('node.outputs_disabled').length == 4);
    await s.unlinkPod();
    await settle();
    expect(end.events('node.outputs_disabled').last, {'modules': ''});
    expect(end.events('node.modules').last, {'modules': ''});
    final last = told(end);
    expect(last.sublist(last.length - 2), [
      'node.outputs_disabled',
      'node.modules',
    ]);
  });

  group('with the host pod', () {
    if (skipFileWithoutHosts(['ATALAIA_POD_HOST'])) return;

    test('a target unplugged and plugged in again: its pod IDENTs again, '
        'and HELLO follows', () async {
      final host = await HostPod.start(
        args: [
          '--no-radio',
          '--buttons',
          '2',
          '--no-keypad',
          '--no-nfc',
          '--no-audio',
          '--no-case',
          '--simple-out',
          'siren',
          '--module',
          'target',
        ],
      );
      final (s, end) = linkedSession(const DeviceFeatures());
      try {
        await s.open();
        await settle();
        await s.attachPod(PodClient(await SocketPodTransport.usb(host)));
        await eventually(
          () =>
              end.hellos.isNotEmpty &&
              end.hellos.last.contains(10) &&
              end.hellos.last.contains(11),
          'HELLO with the pod',
        );
        expect(end.hellos.last, [...screenAndSpeaker, 10, 11]);

        host.send('unplug 58');
        await eventually(
          () => !end.hellos.last.contains(10),
          'HELLO without the target',
        );
        expect(end.hellos.last, [...screenAndSpeaker, 11]);

        host.send('plug 58');
        await eventually(
          () => end.hellos.last.contains(10),
          'HELLO with the target again',
        );
        expect(end.hellos.last, [...screenAndSpeaker, 10, 11]);
      } finally {
        await s.close();
        await host.stop();
      }
    });
  });
}
