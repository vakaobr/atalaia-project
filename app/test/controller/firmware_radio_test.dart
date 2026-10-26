// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A firmware update's offer on the phone controller through its radio
// (decision PE24-130): the I/O pod carries CMD update as it carries any game
// packet (RADIO_TX), a pod that cannot (no radio chip, a link that is down)
// or no radio at all is refused in words, never silently, and a radio's
// refusal of the offer after taking it (its TX_ACK: the duty cycle's budget,
// a full queue) fails the update at once instead of leaving it `sent` until
// the timeout. The pod is a scripted link (pod_modem_test.dart's); the
// end-to-end run with the pod firmware's own code and a Field Box's is
// boxes_e2e_test.dart. A USB radio modem is the same engine with another
// ControllerModem: the last test.
@Timeout(Duration(minutes: 3))
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/chrono/record_signer.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_firmware.dart';
import 'package:atalaia_app/controller/controller_radio.dart';
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:atalaia_app/controller/field_controller.dart' show cmdUpdate;
import 'package:atalaia_app/controller/pod_modem.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:atalaia_app/protocol/firmware_release.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/recording_modem.dart';
import '../support/vectors.dart';
import 'pod_modem_test.dart' show ScriptedPod, settle;

/// A stand-in for a Field Box image: the headers and descriptors a box reads.
Uint8List boxImage(String version, {int size = 4096}) {
  final head = Uint8List(imageHead);
  head[0] = 0xe9;
  head[1] = 4;
  head.setRange(32, 36, [0x32, 0x54, 0xcd, 0xab]);
  head.setRange(48, 48 + version.length, ascii.encode(version));
  head.setRange(80, 80 + imageProject.length, ascii.encode(imageProject));
  head.setRange(288, 292, ascii.encode('ATFW'));
  head[292] = 1;
  head.setRange(296, 299, ascii.encode('box'));
  head.setRange(308, 319, ascii.encode('heltec_v4_3'));
  return Uint8List.fromList([
    ...head,
    for (var i = 0; i < size - imageHead; i++) (i * 7) & 0xff,
  ]);
}

void main() {
  late AtalaiaCore core;
  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  late Directory tmp;
  late ControllerEngine engine;
  late ControllerFirmware firmware;
  late String releaseId;
  late int nodeId;
  late int gameId;

  setUp(() => tmp = Directory.systemTemp.createTempSync('atalaia-fw-radio-'));
  tearDown(() {
    engine.close();
    tmp.deleteSync(recursive: true);
  });

  /// A phone controller on [modem] (or no radio), one game ready, one box
  /// (node [nodeId], running 0.2.0) that said HELLO, and a signed release.
  Future<void> setUpPhone(
    ControllerModem? modem, {
    void Function(Uint8List frameFromBox)? hello,
  }) async {
    final v = loadVectors('firmware.json');
    final signing = (v['signing_key'] as Map).cast<String, String>();
    engine = ControllerEngine(
      store: FileControllerStore(Directory('${tmp.path}/controller')),
      core: core,
      modem: modem,
    )..joinKey = Uint8List.fromList(List.generate(32, (i) => 100 + i));
    firmware = ControllerFirmware(
      engine,
      '${tmp.path}/firmware',
      keys: [signing['public_key_b64']!],
    );
    engine
      ..caSha256 = Uint8List.fromList(List.generate(32, (i) => i))
      ..linkUrls = ['https://10.42.0.1:8443'];
    final image = boxImage('0.3.0');
    final key = await MarshalKey.fromSeed(hexDecode(signing['seed']!));
    final sig = base64.encode(
      await ed25519Sign(
        key,
        releaseManifest(
          'esp32s3',
          '0.3.0',
          image.length,
          sha256.convert(image).toString(),
        ),
      ),
    );
    releaseId =
        (await firmware.add(image, 'esp32s3', '0.3.0', sig))['id']! as String;
    final game = engine.createGame({
      'name': 'fw',
      'mode_id': 'org.atalaia.domination',
      'teams': ['red', 'blue'],
    });
    gameId = game['id']! as int;
    nodeId = engine.issueJoin({'role': 'zone'})['node_id']! as int;
  }

  /// The box's HELLO as the radio heard it.
  RadioRx helloRx() => RadioRx(
    RfHeader.v1(
      gameId: gameId,
      source: nodeId,
      seq: 0,
      hopLimit: 2,
      type: RfType.hello,
    ),
    RfHello(
      nodeName: 'box-$nodeId',
      platform: 1,
      fwVersion: '0.2.0',
      coreVersion: '0.2.0',
      tier: 0,
      capabilities: const [1, 2],
      transports: 1,
      batteryPct: 90,
      epoch: 1,
    ).encode(),
    epoch: 1,
  );

  /// A scripted pod, with a radio or without, up (its PING answered).
  Future<(ScriptedPod, PodModem)> pod({
    bool radio = true,
    Duration ping = const Duration(seconds: 30),
  }) async {
    final link = ScriptedPod();
    final m = PodModem(PodClient(link), pingInterval: ping);
    await m.start();
    link.ident(radio: radio, field: true, pair: true);
    await settle();
    if (radio) {
      link.pong();
      await settle();
      expect(m.isUp, isTrue);
    }
    return (link, m);
  }

  /// The RADIO_TX frames the pod was sent, as (header, plaintext).
  List<(RfHeader, Uint8List)> txFrames(ScriptedPod link) => [
    for (final f in link.sent)
      if (f.type == FrameType.radioTx)
        (
          RfHeader.decode(Uint8List.fromList(f.payload)),
          Uint8List.fromList(f.payload.sublist(9)),
        ),
  ];

  test('through an I/O pod the offer is a RADIO_TX with CMD update', () async {
    final (link, m) = await pod();
    addTearDown(m.close);
    await setUpPhone(m);
    m.onRx!(helloRx());
    final r = await firmware.install(releaseId, [nodeId]);
    expect(r['results'], [
      {'node_id': nodeId, 'result': 'sent'},
    ]);
    expect(r.containsKey('radio_problem'), isFalse);
    final tx = txFrames(link).where((t) => t.$1.type == RfType.cmd).toList();
    expect(tx, hasLength(1));
    final cmd = RfCmd.decode(tx.single.$2);
    expect(cmd.cmd, cmdUpdate);
    expect(cmd.dest, nodeId);
    expect(cmd.params, {'id': releaseId, 'version': '0.3.0'});
    expect(tx.single.$1.gameId, gameId);
    final st = await firmware.status();
    expect(st['radio'], {'kind': 'pod', 'state': 'up', 'problem': null});
    expect(firmware.attempts[nodeId]!['state'], 'sent');
  });

  test('the pod radio refusing the offer fails the update at once', () async {
    for (final (status, code, reason) in [
      (1, 'duty_cycle', 'radio_duty_cycle'),
      (6, 'queue_full', 'radio_queue_full'),
      (2, 'timeout', 'radio_failed'),
    ]) {
      final (link, m) = await pod();
      await setUpPhone(m);
      m.onRx!(helloRx());
      await firmware.install(releaseId, [nodeId]);
      final seq = firmware.attempts[nodeId]!['seq']! as int;
      final messages = <Map<String, Object?>>[];
      engine.addListener(messages.add);
      // An ok for the packet changes nothing; another packet's refusal too.
      link.frame(FrameType.radioTxAck, [seq >> 8, seq & 0xff, 0]);
      link.frame(FrameType.radioTxAck, [
        (seq + 1) >> 8,
        (seq + 1) & 0xff,
        status,
      ]);
      await settle();
      expect(firmware.attempts[nodeId]!['state'], 'sent', reason: code);
      link.frame(FrameType.radioTxAck, [seq >> 8, seq & 0xff, status]);
      await settle();
      final a = firmware.attempts[nodeId]!;
      expect(a['state'], 'failed', reason: code);
      expect(a['reason'], reason);
      expect(
        messages.where((x) => x['type'] == 'firmware' && x['updates'] != null),
        isNotEmpty,
        reason: 'the stream says so',
      );
      // The game can start: a failed offer does not hold it.
      expect(firmware.busy(), isNull);
      await m.close();
      engine.close();
      tmp.deleteSync(recursive: true);
      tmp = Directory.systemTemp.createTempSync('atalaia-fw-radio-');
    }
  });

  test('a pod with no radio chip is refused in words', () async {
    final (link, m) = await pod(radio: false);
    addTearDown(m.close);
    await setUpPhone(m);
    m.onRx!(helloRx());
    expect(m.cannotCarry, contains('no radio chip'));
    // One box: the 409 names the pod.
    await expectLater(
      firmware.install(releaseId, [nodeId]),
      throwsA(
        isA<ControllerError>()
            .having((e) => e.status, 'status', 409)
            .having((e) => e.message, 'message', contains('no radio chip')),
      ),
    );
    // All boxes: the result is the Pi's `radio`, and the reason comes with it.
    final all = await firmware.install(releaseId, 'all');
    expect(all['results'], [
      {'node_id': nodeId, 'result': 'radio'},
    ]);
    expect(all['radio_problem'], contains('I/O pod has no radio chip'));
    expect(all['radio_problem'], contains('command not sent'));
    expect(txFrames(link), isEmpty);
    expect(firmware.attempts, isEmpty);
    final st = await firmware.status();
    expect((st['radio']! as Map)['kind'], 'pod');
    expect((st['radio']! as Map)['problem'], contains('no radio chip'));
  });

  test('a pod whose link is down says so', () async {
    // Pings every 100 ms that nobody answers: 3 missed, and the radio is down.
    final (_, m) = await pod(ping: const Duration(milliseconds: 100));
    addTearDown(m.close);
    await setUpPhone(m);
    m.onRx!(helloRx());
    final end = DateTime.now().add(const Duration(seconds: 30));
    while (m.isUp && DateTime.now().isBefore(end)) {
      await settle(25);
    }
    expect(m.isUp, isFalse);
    final all = await firmware.install(releaseId, 'all');
    expect(all['results'], [
      {'node_id': nodeId, 'result': 'radio'},
    ]);
    expect(all['radio_problem'], contains("the I/O pod's radio is down"));
  });

  test('with no radio at all the refusal says what to plug in', () async {
    await setUpPhone(null);
    // A box that said HELLO cannot exist without a radio: the engine knows
    // none, so the offer is refused as unknown, and the status says why.
    final st = (await firmware.status())['radio']! as Map;
    expect([st['kind'], st['state']], ['none', 'none']);
    expect(st['problem'], contains('no radio is linked'));
    expect(engine.radioProblem(), contains('plug an I/O pod'));
    expect(engine.radioProblem(), contains('USB radio modem'));
  });

  test('a USB radio modem carries the offer as before', () async {
    final m = RecordingModem();
    await setUpPhone(m);
    m.onRx!(helloRx());
    expect(m.kind, 'modem');
    expect(m.cannotCarry, isNull);
    final r = await firmware.install(releaseId, [nodeId]);
    expect(r['results'], [
      {'node_id': nodeId, 'result': 'sent'},
    ]);
    expect(m.sent.where((s) => s.$1.type == RfType.cmd), hasLength(1));
    expect((await firmware.status())['radio'], {
      'kind': 'modem',
      'state': 'up',
      'problem': null,
    });
    // A modem that goes down: refused in words too.
    m.setState(ModemState.down);
    final down = await firmware.install(releaseId, 'all');
    // The first offer is still on its way: nothing new is sent.
    expect(down['results'], [
      {'node_id': nodeId, 'result': 'in_progress'},
    ]);
    firmware.cancel();
    final again = await firmware.install(releaseId, 'all');
    expect(again['results'], [
      {'node_id': nodeId, 'result': 'radio'},
    ]);
    expect(again['radio_problem'], contains('USB radio modem is down'));
  });
}
