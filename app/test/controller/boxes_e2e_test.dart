// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Boxes over the radio with the phone as the field controller (slice S7c of
// PE24), end to end on one machine: the Android controller's engine on the
// real core, its radio the Pi's own USB radio modem (the host modem, through
// serial_modem.dart, decision PE24-92), and Field Boxes running their own
// firmware code (the host box), on a shared UDP air; as the Pi's
// controller/tests/test_box_e2e.py and test_pairing.py do. A box that played
// a game announces itself and is invited into the next one with no card; a
// game ended after the phone restarted without its key still ends on the
// box (GAME_OVER); an unadopted box is paired by its code; a firmware
// update's CMD reaches a box and its own offer checks pass. With an I/O pod
// (the host pod), whose firmware does not relay field frames yet (decision
// PE24-91), the controller says so instead.

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/chrono/record_signer.dart';
import 'package:atalaia_app/controller/controller_adoption.dart';
import 'package:atalaia_app/controller/controller_boxes.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_firmware.dart';
import 'package:atalaia_app/controller/controller_pairing.dart';
import 'package:atalaia_app/controller/controller_radio.dart';
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:atalaia_app/controller/pod_modem.dart';
import 'package:atalaia_app/controller/serial_modem.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/protocol/field_card.dart';
import 'package:atalaia_app/protocol/firmware_release.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/pod_host.dart';
import '../support/vectors.dart';

final joinKey = Uint8List.fromList(List.generate(32, (i) => 100 + i));

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

/// How long a box waits for the controller's KEY in a pairing run before it
/// burns the code (BOX_PAIR_RUN_MS in firmware/esp32/main/box_pair.h).
const boxPairRun = Duration(seconds: 10);

/// Room for a machine under load (six Docker suites at once, load average
/// about 12): the host box and the test are scheduled late, never early, so
/// a wait for a state that has a fixed delay in the box adds this to it.
const loadSlack = Duration(seconds: 40);

/// A stand-in for a Field Box image (the Pi's test_firmware_updates.py
/// `box_image`): the headers and descriptors a box reads, then filler.
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
  if (skipFileWithoutHosts(['ATALAIA_MODEM_HOST', 'ATALAIA_BOX_HOST'])) return;
  late AtalaiaCore core;
  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  late Directory tmp;
  late AirHub hub;
  late HostModem host;
  // Set when setUp has made them all: a setUp that fails (a host program that
  // does not start) must not make tearDown fail with a LateInitializationError
  // on top of the real failure.
  var up = false;
  final boxes = <HostBox>[];
  ControllerEngine? engine;
  SerialModem? modem;
  SocketPodTransport? link;
  Timer? ticker;
  var persistGameKey = true;

  /// The phone's controller on the host modem: a new engine on the store
  /// (a restart is the app's process going and coming back), with the
  /// boxes, pairing, field cards and firmware updates.
  Future<ControllerEngine> phone({List<String> firmwareKeys = const []}) async {
    link = await SocketPodTransport.modem(host);
    expect(await probeRadioLink(link!), 'modem');
    final m = modem = SerialModem(
      link!,
      pingInterval: const Duration(milliseconds: 200),
    );
    final e = engine = ControllerEngine(
      config: ControllerConfig(persistGameKey: persistGameKey),
      store: FileControllerStore(Directory('${tmp.path}/controller')),
      core: core,
      modem: m,
    )..joinKey = joinKey;
    ControllerAdoption(e);
    ControllerFirmware(e, '${tmp.path}/firmware', keys: firmwareKeys);
    ControllerBoxes(e);
    ControllerPairing(e);
    await m.start();
    expect(await waitFor(() => m.isUp), isTrue, reason: 'the modem');
    expect(m.hasFieldFrames && m.hasPairFrames, isTrue);
    ticker = Timer.periodic(const Duration(milliseconds: 50), (_) => e.tick());
    return e;
  }

  Future<void> crash() async {
    ticker?.cancel();
    await modem?.close();
    await link?.close();
    engine?.close();
    engine = null;
  }

  Future<HostBox> box(
    String name, {
    List<int>? key,
    List<String> args = const [],
  }) async {
    final b = await HostBox.start(
      hub,
      '${tmp.path}/$name',
      key ?? joinKey,
      name: name,
      args: args,
    );
    boxes.add(b);
    return b;
  }

  setUp(() async {
    tmp = Directory.systemTemp.createTempSync('atalaia-boxes-e2e-');
    up = false;
    boxes.clear();
    hub = await AirHub.start();
    host = await HostModem.start(airPeer: hub.port);
    hub.members.add(host.airPort);
    up = true;
    persistGameKey = true;
  });

  tearDown(() async {
    await crash();
    for (final b in boxes) {
      await b.kill();
    }
    if (up) {
      await host.stop();
      hub.close();
    }
    tmp.deleteSync(recursive: true);
  });

  int game(ControllerEngine e) =>
      e.createGame({
            'name': 'e2e',
            'mode_id': 'org.atalaia.domination',
            'teams': ['red', 'blue'],
          })['id']!
          as int;

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

  Map<String, Object?> node(ControllerEngine e, int id) =>
      e.nodes().firstWhere((n) => n['node_id'] == id, orElse: () => const {});

  test('a box that played a game is invited into the next one', () async {
    final e = await phone();
    final gid = game(e);
    final b = await box('alpha', args: ['--announce-ms', '400']);
    final nid = await join(e, b);
    expect(await waitFor(() => node(e, nid)['device_id'] != null), isTrue);
    final device = node(e, nid)['device_id']! as String;
    expect(device, (await b.status())['device_id']);
    e.startGame(gid);
    expect(await waitFor(() async => (await b.status())['phase'] == 2), isTrue);
    final ended = e.endGame(gid);
    expect(ended['game_over_frame'], 'sent');
    expect(
      await waitFor(() async => (await b.status())['available'] == true),
      isTrue,
    );

    final gid2 = game(e);
    expect(
      () => e.startGame(gid2),
      throwsA(
        isA<ControllerError>().having(
          (x) => (x.extra['start_check']! as Map)['missing'],
          'missing',
          ['zone'],
        ),
      ),
    );
    List<Map<String, Object?>> listed() => [
      for (final x in e.boxes!.boxes()['boxes']! as List)
        if ((x as Map)['device_id'] == device) x.cast<String, Object?>(),
    ];
    expect(await waitFor(() => listed().isNotEmpty), isTrue);
    final entry = listed().single;
    expect(
      [
        entry['name'],
        entry['previous'],
        entry['previous_role'],
        entry['last_game'],
      ],
      ['alpha', true, 'zone', gid],
    );
    final r = e.boxes!.invite(gid2, [
      {'device_id': device, 'role': 'zone'},
    ]);
    expect(
      ((r['invites']! as List).single as Map)['status'],
      anyOf('sending', 'invited'),
    );
    expect(
      await waitFor(() async => (await b.status())['game_id'] == gid2),
      isTrue,
      reason: '${b.lines.reversed.take(8)}',
    );
    String status() => (e.boxes!.invites(gid2).single)['status']! as String;
    expect(await waitFor(() => status() == 'joined'), isTrue, reason: status());
    expect(e.startCheck()['ok'], isTrue);
    e.startGame(gid2);
    expect(
      await waitFor(() async {
        final s = await b.status();
        return s['phase'] == 2 && s['game_id'] == gid2;
      }),
      isTrue,
    );
  });

  test(
    'a restart without the key: GAME_OVER still ends the game on the box',
    () async {
      persistGameKey = false;
      var e = await phone();
      final gid = game(e);
      final b = await box('alpha', args: ['--announce-ms', '400']);
      await join(e, b);
      e.startGame(gid, force: true);
      expect(
        await waitFor(() async => (await b.status())['phase'] == 2),
        isTrue,
      );
      await crash();
      e = await phone();
      expect(e.keyLost, isTrue);
      expect(e.endGame(gid)['game_over_frame'], 'sent');
      expect(
        await waitFor(
          () => b.logged('game $gid is over (said by a field controller)'),
        ),
        isTrue,
        reason: '${b.lines.reversed.take(8)}',
      );
      expect(
        await waitFor(() async => (await b.status())['available'] == true),
        isTrue,
      );
    },
  );

  test("the USB radio modem measures noise for S7a's channel scan", () async {
    await phone();
    final m = modem!;
    expect(m.canMeasure, isTrue);
    final noise = await m.measure(869525000, 50);
    expect(noise.channelHz, 869525000);
    expect(noise.dwellMs, 50);
    await expectLater(
      m.measure(869525000, 5),
      throwsA(isA<MeasureException>()),
    );
  });

  test(
    'an unadopted box paired by the code it shows',
    () async {
      final e = await phone();
      final b = await box(
        'porta-norte',
        key: const [],
        args: ['--pair', '--announce-ms', '400'],
      );
      expect(await waitFor(() => b.logged('pairing: code')), isTrue);
      String? offered() {
        for (final o in e.pairing!.status()['offers']! as List) {
          if ((o as Map)['name'] == 'porta-norte') {
            return o['pair_id'] as String;
          }
        }
        return null;
      }

      expect(await waitFor(() => offered() != null), isTrue);
      final pairId = offered()!;
      String code([int index = -1]) {
        final codes = [
          for (final l in b.lines)
            if (RegExp(r'code (\d{3}) (\d{3})').firstMatch(l) case final m?)
              '${m[1]}${m[2]}',
        ];
        return codes[index < 0 ? codes.length + index : index];
      }

      Map<String, Object?> run() =>
          (e.pairing!.status()['run']! as Map).cast<String, Object?>();
      // A wrong code: the run fails and the box shows a new one.
      final first = code();
      final wrong = ((int.parse(first) + 1) % 1000000).toString().padLeft(
        6,
        '0',
      );
      e.pairing!.pair(pairId, wrong);
      expect(
        await waitFor(
          () => run()['state'] == 'failed',
          timeout: const Duration(seconds: 15),
        ),
        isTrue,
      );
      expect(run()['detail'], 'wrong_code');
      // The box does not hear of a wrong code: the phone fails at the REPLY,
      // and the box burns its code when its own run runs out (BOX_PAIR_RUN_MS,
      // 10 s from the START, decision AD-25). So the end state comes a fixed
      // 10 s after the run began, plus however long a loaded machine keeps
      // the host box's loop from its tick: the deadline is that run and a
      // generous slack, never a bare 12 s.
      expect(
        await waitFor(
          () => b.logged('pairing: new code'),
          timeout: boxPairRun + loadSlack,
        ),
        isTrue,
        reason: 'the box burns the code ${b.lines.reversed.take(6)}',
      );
      // The right code: adopted with this field's key.
      e.pairing!.pair(pairId, code());
      expect(
        await waitFor(
          () => run()['state'] == 'done',
          timeout: const Duration(seconds: 15),
        ),
        isTrue,
        reason: '${run()} ${b.lines.reversed.take(8)}',
      );
      expect(run()['result'], 'adopted');
      expect(
        File('${tmp.path}/porta-norte/join_key').readAsBytesSync(),
        joinKey,
      );
      expect(
        b.logged(
          'adoption (radio): adopted, field ${fieldFingerprint(joinKey)}',
        ),
        isTrue,
      );
      final log = e.adoption!.info()['log']! as List;
      expect(
        [for (final x in log.take(2)) (x as Map)['result']],
        ['adopted', 'wrong_code'],
      );
      // Its field frames start under the new key: a free box.
      expect(
        await waitFor(
          () => (e.boxes!.boxes()['boxes']! as List).any(
            (x) => (x as Map)['name'] == 'porta-norte',
          ),
          timeout: const Duration(seconds: 25),
        ),
        isTrue,
        // The test's own limit is the default 30 s; the box's code burn alone
        // is 10 s, and a wrong run, a right run and the first announce
        // follow: a loaded machine needs the room (see loadSlack).
      );
    },
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test("a firmware update's offer reaches the box over the radio", () async {
    final v = loadVectors('firmware.json');
    final signing = (v['signing_key'] as Map).cast<String, String>();
    final e = await phone(firmwareKeys: [signing['public_key_b64']!]);
    e
      ..caSha256 = Uint8List.fromList(List.generate(32, (i) => i))
      ..linkUrls = ['https://10.42.0.1:8443', 'https://atalaia.local:8443'];
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
    final rel = await e.firmware!.add(image, 'esp32s3', '0.3.0', sig);
    final gid = game(e);
    final b = await box(
      'alpha',
      args: ['--as-box', '0.2.0', '--release-keys', signing['public_key']!],
    );
    final nid = await join(e, b);
    expect(await waitFor(() => node(e, nid)['fw_version'] == '0.2.0'), isTrue);
    final r = await e.firmware!.install(rel['id']! as String, [nid]);
    expect(r['results'], [
      {'node_id': nid, 'result': 'sent'},
    ]);
    final offer = jsonEncode({'id': rel['id'], 'version': '0.3.0'});
    expect(
      await waitFor(
        () => b.logged('UPDATE $offer link=yes/2 precheck=installed'),
      ),
      isTrue,
      reason: '${b.lines.reversed.take(5)}',
    );
    // Not while the update is on its way; cancelled, the game starts.
    expect(
      () => e.startGame(gid, force: true),
      throwsA(isA<ControllerError>().having((x) => x.status, 'status', 409)),
    );
    expect(e.firmware!.cancel(), [nid]);
    e.startGame(gid, force: true);
    expect(await waitFor(() async => (await b.status())['phase'] == 2), isTrue);
  });

  test(
    'an I/O pod relays field and pair frames (PE24-100): the controller uses it as its radio',
    () async {
      final pod = await HostPod.start(airPeer: hub.port);
      addTearDown(pod.stop);
      hub.members.add(pod.airPort);
      final podLink = await SocketPodTransport.usb(pod);
      expect(await probeRadioLink(podLink), 'pod');
      final client = PodClient(podLink);
      addTearDown(client.close);
      final ControllerModem m = PodModem(
        client,
        pingInterval: const Duration(milliseconds: 200),
      );
      final e = ControllerEngine(
        store: FileControllerStore(Directory('${tmp.path}/pod-controller')),
        core: core,
        modem: m,
      )..joinKey = joinKey;
      ControllerAdoption(e);
      ControllerBoxes(e);
      ControllerPairing(e);
      await (m as PodModem).start();
      expect(await waitFor(() => m.isUp), isTrue);
      // Since PE24-100 the pod's IDENT says field_frames and pair_frames and
      // it relays them as the USB modem does.
      expect(m.hasFieldFrames, isTrue);
      expect(m.hasPairFrames, isTrue);
      expect(e.boxes!.boxes()['field_frames'], isTrue);
      e.pairing!.listen();
      final gid = game(e);
      expect(e.endGame(gid)['game_over_frame'], 'sent');
      e.close();
    },
  );
}
