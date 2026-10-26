// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// An Android prop with an I/O pod in a joined game at a field without
// Wi-Fi (decision PF9): the prop session (lib/prop/prop_session.dart) with
// the pod firmware's own code on this machine (the host pod) and the
// controller's radio (the host modem) on a shared UDP "air". The pod's radio
// joins the session's link to the controller; the controller's start comes
// over the radio; the mode's event goes up over the radio; the pod's button
// is the game's team by number; an opened pod is node.tamper (pod_opened).

import 'dart:async';
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

final key = Uint8List.fromList(List.generate(16, (i) => 0x60 + i));

final joinPayload = JoinPayload(
  gameId: 777,
  gameKey: key,
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

Future<void> until(bool Function() ok, {int ms = 5000}) async {
  final end = DateTime.now().add(Duration(milliseconds: ms));
  while (!ok()) {
    if (DateTime.now().isAfter(end)) throw TimeoutException('condition');
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
}

void main() {
  if (skipFileWithoutHosts(['ATALAIA_POD_HOST', 'ATALAIA_MODEM_HOST'])) return;
  late AtalaiaCore core;
  late AirHub hub;
  late HostModem modem;
  late HostPod pod;
  late ModemLink ctl;
  var ctlSeq = 0;

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

  void controllerSends(int type, Uint8List payload) {
    final h = RfHeader.v1(
      gameId: 777,
      source: 0,
      seq: ctlSeq++,
      hopLimit: 2,
      type: type,
    );
    ctl.send(ModemLink.tx, [...h.encode(), ...payload]);
  }

  bool fromPhone(Uint8List p, int type) {
    final h = RfHeader.decode(p);
    return h.type == type && h.source == 5;
  }

  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  setUp(() async {
    hub = await AirHub.start();
    modem = await HostModem.start(airPeer: hub.port);
    hub.members.add(modem.airPort);
    pod = await HostPod.start(airPeer: hub.port);
    hub.members.add(pod.airPort);
    ctl = await ModemLink.connect(modem);
    ctl.send(
      ModemLink.cmd,
      radioConfigure(
        gameId: 777,
        nodeId: 0,
        epoch: 1,
        maxHops: 2,
        channelHz: 869525000,
        key: key,
      ),
    );
    await ctl.wait(ModemLink.status);
  });

  tearDown(() async {
    await ctl.close();
    await pod.stop();
    await modem.stop();
    hub.close();
  });

  test(
    'a joined prop on the pod\'s radio, with its buttons and its case',
    () async {
      final node = FakeRunningNode();
      final mode = ModeCatalog.builtin().compose('org.atalaia.domination');
      const teams = ['red', 'blue'];
      final device = FakeDevice();
      final s = PropSession(
        setup: PropSetup(
          mode: mode,
          role: 'zone',
          teams: teams,
          params: mode.resolveParams(const {}, teams),
          nodeId: 5,
          join: joinPayload,
        ),
        runner: FakeNodeRunner(node),
        device: device,
        texts: const PropTexts(
          notificationTitle: 'Atalaia: {mode}',
          notificationRunning: 'running',
          notificationLeft: '{time} left',
        ),
        clock: GameClock.manual,
        radioLinkFor: (client) => PodRadioLink(
          pod: client,
          join: joinPayload,
          epochs: MemoryEpochStore(),
          encodeEvent: encode,
          hello: const {'node_name': 'phone-5', 'fw_version': 'app-test'},
          retryAfter: const Duration(milliseconds: 500),
          tick: const Duration(milliseconds: 20),
        ),
      );
      await s.open();
      expect(s.controllerLink, isNotNull); // a join payload, no Wi-Fi link
      await s.attachPod(PodClient(await SocketPodTransport.usb(pod)));
      await until(() => s.radio?.linked ?? false);

      // HELLO over the radio says LoRa only: there is no Wi-Fi link.
      final hello = await ctl.wait(
        ModemLink.rx,
        match: (p) => fromPhone(p, RfType.hello),
      );
      final h = RfHello.decode(
        Uint8List.sublistView(hello.payload, 9, hello.payload.length - 4),
      );
      expect((h.nodeName, h.transports), ('phone-5', RfTransport.lora));

      // The controller starts the game over the radio.
      controllerSends(RfType.cmd, const RfCmd(cmd: 0).encode());
      await until(() => s.phase == PropPhase.running);

      // The pod's button 2 is the game's 2nd team.
      pod.send('press 2');
      await until(
        () => node.inputs.any(
          (i) => i.$1 == 'team_input.press' && i.$2?['team'] == 'blue',
        ),
      );
      pod.send('release 2');

      // The mode's event goes up over the radio, as the core encodes it.
      final mark = ctl.frames.length;
      node.emit(
        NodeEventOutput(
          EmittedEvent(
            node: 5,
            seq: 1,
            tMs: 4000,
            team: 2,
            squad: 0,
            prio: 1,
            type: 'zone.captured',
            dataJson: '{"team":"blue"}',
          ),
        ),
      );
      final ev = await ctl.wait(
        ModemLink.rx,
        from: mark,
        match: (p) => fromPhone(p, RfType.event),
      );
      expect(
        Uint8List.sublistView(ev.payload, 9, ev.payload.length - 4),
        encode(
          node: 5,
          seq: 1,
          tMs: 4000,
          type: 'zone.captured',
          team: 2,
          squad: 0,
          prio: 1,
          dataJson: '{"team":"blue"}',
        ),
      );

      // Someone opens the pod: node.tamper (critical) with reason pod_opened.
      final mark2 = ctl.frames.length;
      await pod.caseArmed();
      pod.send('case open');
      await until(() => s.podOpened);
      final tamper = await ctl.wait(
        ModemLink.rx,
        from: mark2,
        match: (p) => fromPhone(p, RfType.event),
      );
      final th = RfHeader.decode(tamper.payload);
      expect(th.prio, RfPrio.critical);
      expect(
        Uint8List.sublistView(tamper.payload, 9, tamper.payload.length - 4),
        encode(
          node: 5,
          seq: 1,
          tMs: s.gameTimeMs,
          type: 'node.tamper',
          team: 0,
          squad: 0,
          prio: 2,
          dataJson: '{"reason":"pod_opened"}',
        ),
      );
      expect(device.calls.where((c) => c.startsWith('vibrate')), isNotEmpty);
      pod.send('case closed');
      await until(() => !s.podOpened);
      await s.close();
      // Closing the session clears the pod's radio.
      var configured = true;
      for (var i = 0; i < 50 && configured; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 20));
        configured = (await pod.status())['radio_configured'] == true;
      }
      expect(configured, isFalse);
    },
  );

  test('without a radio on the pod, the session has no radio link', () async {
    await pod.stop();
    pod = await HostPod.start(args: ['--no-radio']);
    final node = FakeRunningNode();
    final mode = ModeCatalog.builtin().compose('org.atalaia.domination');
    var asked = 0;
    final s = PropSession(
      setup: PropSetup(
        mode: mode,
        role: 'zone',
        teams: const ['red', 'blue'],
        params: mode.resolveParams(const {}, const ['red', 'blue']),
        join: joinPayload,
      ),
      runner: FakeNodeRunner(node),
      device: FakeDevice(),
      texts: const PropTexts(
        notificationTitle: '',
        notificationRunning: '',
        notificationLeft: '',
      ),
      clock: GameClock.manual,
      radioLinkFor: (client) {
        asked++;
        return null;
      },
    );
    await s.open();
    final client = PodClient(await SocketPodTransport.usb(pod));
    await s.attachPod(client);
    await until(() => s.pod != null);
    expect(s.pod!.hasRadio, isFalse);
    expect((asked, s.radio), (0, null));
    await s.close();
  });
}
