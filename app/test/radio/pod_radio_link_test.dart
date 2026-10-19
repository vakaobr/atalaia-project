// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// An Android prop on the field's radio through an I/O pod
// (lib/radio/pod_radio_link.dart), end to end on this machine: the pod is
// the pod firmware's own C code (the host pod), the controller's radio is
// the USB modem's (the host modem), both with real AES-128-CCM, on a shared
// UDP "air"; the test plays the controller on the modem's serial link. The
// prop's events reach the controller encoded by the core (as a box's),
// unacknowledged ones go again in a new packet, an ACK clears them, the
// controller's TIME and commands come back as link messages, STATE keeps
// to its interval, each new link has a new epoch, and closing forgets the
// key. Then the Wi-Fi link and the radio together ([DualLink]).

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/controller/dual_link.dart';
import 'package:atalaia_app/controller/prop_link.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/radio/pod_radio_link.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/pod_host.dart';

final gameKey = Uint8List.fromList(List.generate(16, (i) => 0x40 + i));

JoinPayload join({List<String>? urls}) => JoinPayload(
  gameId: 4242,
  gameKey: gameKey,
  nodeId: 7,
  controllerId: 0,
  channelHz: 869525000,
  maxHops: 2,
  teams: const ['red', 'blue'],
  modeId: 'org.atalaia.domination',
  role: 'zone',
  gameSeed: 1,
  params: null,
  kind: JoinKind.node,
  caSha256: urls == null ? null : Uint8List(32),
  urls: urls,
);

late AtalaiaCore core;

Uint8List? encodeWithCore({
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

/// A radio packet as the modem's serial link reports it (RX): header, plaintext.
(RfHeader, Uint8List) packet(Uint8List rx) =>
    (RfHeader.decode(rx), Uint8List.sublistView(rx, 9, rx.length - 4));

/// The field: the air, the controller's modem, the pod, the phone's client.
class Field {
  late AirHub hub;
  late HostModem modem;
  late ModemLink ctl;
  late HostPod pod;
  late PodClient client;
  var _ctlSeq = 0;

  Future<void> start() async {
    hub = await AirHub.start();
    modem = await HostModem.start(airPeer: hub.port);
    hub.members.add(modem.airPort);
    pod = await HostPod.start(airPeer: hub.port);
    hub.members.add(pod.airPort);
    ctl = await ModemLink.connect(modem);
    // The controller's own node: id 0, epoch 1, the same game and channel.
    ctl.send(
      ModemLink.cmd,
      radioConfigure(
        gameId: 4242,
        nodeId: 0,
        epoch: 1,
        maxHops: 2,
        channelHz: 869525000,
        key: gameKey,
      ),
    );
    await ctl.wait(ModemLink.status);
    client = PodClient(await SocketPodTransport.usb(pod));
    final ident = client.events.firstWhere((e) => e is PodIdentified);
    await client.start();
    await ident.timeout(const Duration(seconds: 5));
  }

  /// The controller transmits a packet (through its modem).
  void controllerSends(int type, Uint8List payload, {int prio = 0}) {
    final h = RfHeader.v1(
      gameId: 4242,
      source: 0,
      seq: _ctlSeq++,
      hopLimit: 2,
      type: type,
      prio: prio,
    );
    ctl.send(ModemLink.tx, [...h.encode(), ...payload]);
  }

  /// The next packet of [type] from node 7 the controller hears, from frame [from].
  Future<(RfHeader, Uint8List, int)> heard(int type, {int from = 0}) async {
    final f = await ctl.wait(
      ModemLink.rx,
      from: from,
      match: (p) {
        final h = RfHeader.decode(p);
        return h.type == type && h.source == 7;
      },
    );
    final (h, plain) = packet(f.payload);
    return (h, plain, ctl.frames.indexOf(f) + 1);
  }

  PodRadioLink radio({EpochStore? epochs}) => PodRadioLink(
    pod: client,
    join: join(),
    epochs: epochs ?? MemoryEpochStore(),
    encodeEvent: encodeWithCore,
    hello: {
      'node_name': 'phone-7',
      'fw_version': 'app-test',
      'core_version': core.version,
      'tier': 0,
      'capabilities': const <int>[],
      'transports': RfTransport.lora | RfTransport.wifi,
    },
    retryAfter: const Duration(milliseconds: 400),
    stateEvery: const Duration(seconds: 1),
    tick: const Duration(milliseconds: 20),
  );

  Future<void> stop() async {
    await client.close();
    await ctl.close();
    await pod.stop();
    await modem.stop();
    hub.close();
  }
}

Future<void> until(bool Function() ok, {int ms = 5000}) async {
  final end = DateTime.now().add(Duration(milliseconds: ms));
  while (!ok()) {
    if (DateTime.now().isAfter(end)) throw TimeoutException('condition');
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
}

void main() {
  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  late Field field;
  setUp(() async {
    field = Field();
    await field.start();
  });
  tearDown(() async => field.stop());

  test('HELLO, events with ACKs, TIME and commands, STATE', () async {
    final radio = field.radio();
    final messages = <LinkMessage>[];
    radio.messages.listen(messages.add);
    radio.start();
    await until(() => radio.linked);
    expect(radio.epoch, 1);

    // HELLO reaches the controller, decrypted by its modem.
    final (hh, hp, afterHello) = await field.heard(RfType.hello);
    final hello = RfHello.decode(hp);
    expect((hello.nodeName, hello.platform, hello.epoch), ('phone-7', 3, 1));
    expect(hello.transports, RfTransport.lora | RfTransport.wifi);
    expect((hh.prio, hh.ackRequested, hh.encrypted), (2, true, true));
    expect(radio.heard, isFalse);
    field.controllerSends(RfType.ack, RfAck(node: 7, seq: hh.seq).encode());
    await until(() => radio.heard);

    // A capture, encoded by the core as a box would; no ACK: a new packet.
    radio.sendEvent(
      seq: 1,
      tMs: 4000,
      type: 'zone.captured',
      team: 1,
      prio: 'normal',
      data: const {'team': 'red'},
      dataJson: '{"team":"red"}',
    );
    final (e1, p1, after1) = await field.heard(RfType.event, from: afterHello);
    expect(
      p1,
      encodeWithCore(
        node: 7,
        seq: 1,
        tMs: 4000,
        type: 'zone.captured',
        team: 1,
        squad: 0,
        prio: 1,
        dataJson: '{"team":"red"}',
      ),
    );
    final (e2, p2, _) = await field.heard(RfType.event, from: after1);
    expect(e2.seq, greaterThan(e1.seq));
    expect(p2, p1);
    expect(radio.pending, 1);
    field.controllerSends(
      RfType.ack,
      RfAck(node: 7, seq: e2.seq).encode(), // contiguous up to e2: both covered
    );
    await until(() => radio.pending == 0);

    // The controller's TIME and its commands.
    field.controllerSends(
      RfType.time,
      const RfTime(
        gameTimeMs: 5000,
        gameState: 1,
        durationMs: 600000,
        wallS: 1729180800,
        term: 1,
      ).encode(),
    );
    field.controllerSends(
      RfType.cmd,
      const RfCmd(cmd: 5, params: {'text': 'hi'}, dest: 9).encode(),
    );
    field.controllerSends(
      RfType.cmd,
      const RfCmd(cmd: 3, params: {'reason': 'gm'}, dest: 7).encode(),
    );
    await until(() => messages.length >= 2);
    final time = messages.whereType<LinkTime>().single;
    expect(
      (time.state, time.gameTimeMs, time.durationMs),
      ('running', 5000, 600000),
    );
    final cmd = messages.whereType<LinkCommand>().single; // not node 9's
    expect(cmd.cmd, 'end');
    expect(cmd.params, {'reason': 'gm'});

    // STATE: telemetry, at most once a second here.
    final mark = field.ctl.frames.length;
    radio.sendState({
      'owner_team': 1,
      'phase': 1,
      'game_time_ms': 9000,
      'counters': {'1': 7},
      'flags': 1,
    });
    final (sh, sp, _) = await field.heard(RfType.state, from: mark);
    final st = RfState.decode(sp);
    expect((st.ownerTeam, st.epoch), (1, 1));
    expect(st.counters, {1: 7});
    expect(sh.ackRequested, isFalse);
    radio.sendState({
      'owner_team': 2,
      'counters': {'1': 8},
    });
    await Future<void>.delayed(const Duration(milliseconds: 300));
    expect(
      field.ctl.frames
          .skip(mark)
          .where(
            (f) =>
                f.type == ModemLink.rx &&
                RfHeader.decode(f.payload).type == RfType.state,
          ),
      hasLength(1),
    );

    // Closing forgets the game key on the pod (RADIO_CMD CLEAR).
    expect((await field.pod.status())['radio_configured'], isTrue);
    await radio.close();
    var configured = true;
    for (var i = 0; i < 50 && configured; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
      configured = (await field.pod.status())['radio_configured'] == true;
    }
    expect(configured, isFalse);
  });

  test(
    'every link has a new epoch, and the controller still hears it',
    () async {
      final store = AppEpochStore(MemoryAppStore());
      final first = field.radio(epochs: store);
      first.start();
      await until(() => first.linked);
      expect(first.epoch, 1);
      final (h1, _, after) = await field.heard(RfType.hello);
      await first.close();

      final second = field.radio(epochs: store);
      second.start();
      await until(() => second.linked);
      expect(second.epoch, 2);
      final (h2, p2, _) = await field.heard(RfType.hello, from: after);
      expect(RfHello.decode(p2).epoch, 2);
      // seq starts at 0 again under the new epoch: a new nonce all the same.
      expect(h2.seq, h1.seq);
      expect(await store.next(4242, 7), 3);
      await second.close();
    },
  );

  test(
    'the pod refuses a channel outside the rules: the link stays down',
    () async {
      final radio = PodRadioLink(
        pod: field.client,
        join: JoinPayload(
          gameId: 4242,
          gameKey: gameKey,
          nodeId: 7,
          controllerId: 0,
          channelHz: 869400000, // its 125 kHz channel starts below 869.4 MHz
          maxHops: 2,
          teams: const ['red', 'blue'],
          modeId: 'org.atalaia.domination',
          role: 'zone',
          gameSeed: 1,
          params: null,
          kind: JoinKind.node,
        ),
        epochs: MemoryEpochStore(),
        encodeEvent: encodeWithCore,
        reconfigureAfter: const Duration(seconds: 30),
      );
      radio.start();
      await until(() => radio.state == RadioLinkState.offline);
      expect(radio.linked, isFalse);
      radio.sendEvent(seq: 1, tMs: 1, type: 'zone.captured', team: 1);
      await Future<void>.delayed(const Duration(milliseconds: 200));
      expect(field.ctl.frames.where((f) => f.type == ModemLink.rx), isEmpty);
      await radio.close();
    },
  );

  test('Wi-Fi and the radio: the radio only while Wi-Fi is down', () async {
    final sockets = <_WifiController>[];
    var wifiReachable = true;
    final wifi = PropLink(
      join: join(urls: const ['https://10.0.2.2:8443']),
      urls: const ['https://10.0.2.2:8443'],
      hello: {'node_name': 'phone-7', 'capabilities': const <int>[]},
      connect: (uri) async {
        if (!wifiReachable) throw StateError('no route');
        return (sockets..add(_WifiController())).last;
      },
    );
    final dual = DualLink(wifi: wifi);
    final messages = <LinkMessage>[];
    dual.messages.listen(messages.add);
    dual.start();
    await until(() => wifi.linked);
    final radio = field.radio();
    await dual.attachRadio(radio);
    await until(() => radio.linked);
    // Both HELLOs say lora and wifi.
    expect(dual.transports, RfTransport.lora | RfTransport.wifi);
    expect(
      sockets.last.got.lastWhere((m) => m['type'] == 'hello')['transports'],
      3,
    );
    final (_, hp, afterHello) = await field.heard(RfType.hello);
    expect(RfHello.decode(hp).transports, 3);

    // Wi-Fi up: the event goes on Wi-Fi only; the radio's TIME is not taken.
    dual.sendEvent(seq: 1, tMs: 100, type: 'zone.captured', team: 1);
    await until(() => sockets.last.got.any((m) => m['type'] == 'event'));
    field.controllerSends(
      RfType.time,
      const RfTime(
        gameTimeMs: 100,
        gameState: 1,
        durationMs: 0,
        wallS: 1,
        term: 1,
      ).encode(),
    );
    await Future<void>.delayed(const Duration(milliseconds: 600));
    expect(
      field.ctl.frames
          .skip(afterHello)
          .where(
            (f) =>
                f.type == ModemLink.rx &&
                RfHeader.decode(f.payload).type == RfType.event,
          ),
      isEmpty,
    );
    // (The Wi-Fi welcome's own TIME says waiting; the radio's said running.)
    expect(
      messages.whereType<LinkTime>().where((t) => t.state == 'running'),
      isEmpty,
    );

    // Wi-Fi drops: the next event goes on the radio too, and the radio's
    // TIME and commands are taken.
    wifiReachable = false;
    await sockets.last.drop();
    await until(() => !wifi.linked);
    expect(dual.linked, isTrue); // the radio
    dual.sendEvent(seq: 2, tMs: 200, type: 'zone.captured', team: 2);
    final (_, ep, _) = await field.heard(RfType.event, from: afterHello);
    expect(
      ep,
      encodeWithCore(
        node: 7,
        seq: 2,
        tMs: 200,
        type: 'zone.captured',
        team: 2,
        squad: 0,
        prio: 1,
        dataJson: null,
      ),
    );
    field.controllerSends(
      RfType.cmd,
      const RfCmd(cmd: 1, params: {'reason': 'gm'}).encode(),
    );
    await until(() => messages.whereType<LinkCommand>().isNotEmpty);
    expect(messages.whereType<LinkCommand>().single.cmd, 'pause');
    // The Wi-Fi link keeps the event for when it is back (the controller logs it once).
    expect(wifi.unacked, 2);
    await dual.close();
  });
}

/// The controller's end of a Wi-Fi link, welcoming at once (the proof is
/// checked in test/controller/prop_link_test.dart).
class _WifiController implements LinkSocket {
  _WifiController() {
    _in.add(
      jsonEncode({
        'type': 'challenge',
        'nonce': base64Url.encode(List.filled(32, 1)).replaceAll('=', ''),
        'version': 1,
      }),
    );
  }

  final _in = StreamController<String>();
  final got = <Map<String, Object?>>[];
  @override
  int? closeCode;

  @override
  Stream<String> get messages => _in.stream;

  @override
  void send(String text) {
    final m = (jsonDecode(text) as Map).cast<String, Object?>();
    got.add(m);
    if (m['type'] == 'auth') {
      _in.add(
        jsonEncode({
          'type': 'welcome',
          'game_id': 4242,
          'node_id': 7,
          'controller_id': 0,
          'time': {'state': 'waiting', 'game_time_ms': 0, 'duration_ms': 0},
        }),
      );
    }
  }

  Future<void> drop() async {
    closeCode = 1006;
    if (!_in.isClosed) await _in.close();
  }

  @override
  Future<void> close() => drop();
}
