// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The phone's pod client (lib/pod/pod_client.dart) against the I/O pod's
// own firmware code (main/pod/*.c, run on this machine as the host pod,
// firmware/esp32/test/pod_host): IDENT, events acknowledged, commands
// reaching the pod's hardware, the mapping of a real IDENT onto a game's
// inputs (with a player tag signed for the game), the enclosure switch, over
// the USB link and the Bluetooth link (frames cut to the MTU both ways).

@Timeout(Duration(minutes: 3))
library;

import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:atalaia_app/security/nfc_tag_signer.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/pod_host.dart';

Future<PodIdent> identified(PodClient c) async {
  final got = c.events
      .firstWhere((e) => e is PodIdentified)
      .timeout(hostDeadline);
  await c.start();
  return ((await got) as PodIdentified).ident;
}

/// The next capability event from the pod.
Future<ProxyMessage> next(PodClient c, {String? capId, String? name}) async {
  final e = await c.events
      .firstWhere(
        (e) =>
            e is PodCapabilityEvent &&
            (capId == null || e.message.capId == capId) &&
            (name == null || e.message.name == name),
      )
      .timeout(hostDeadline);
  return (e as PodCapabilityEvent).message;
}

void main() {
  late HostPod pod;

  setUp(() async => pod = await HostPod.start());
  tearDown(() async => pod.stop());

  test('over USB: IDENT, a held button, commands on the hardware', () async {
    final client = PodClient(await SocketPodTransport.usb(pod));
    final ident = await identified(client);
    expect(ident.fwVersion, 'host-pod');
    expect(ident.hasRadio, isTrue);
    expect(ident.capabilities.map((c) => c['id']), [
      'btn.1',
      'btn.2',
      'btn.3',
      'btn.4',
      'keypad',
      'ring',
      'audio',
      'nfc',
      'case',
    ]);

    // Button 1 held for 600 ms: press, holds every 250 ms, release.
    final events = <ProxyMessage>[];
    final sub = client.events.listen((e) {
      if (e is PodCapabilityEvent) events.add(e.message);
    });
    pod.send('hold 1 600');
    await next(client, capId: 'btn.1', name: 'release');
    await sub.cancel();
    expect(events.map((m) => m.name), ['press', 'hold', 'hold', 'release']);
    expect(events[1].data, {'ms': 250});
    expect(events[2].data, {'ms': 500});
    expect(events[3].data['ms'], greaterThanOrEqualTo(590));
    // Every one acknowledged by the client: none left waiting on the pod.
    expect((await pod.status())['pending'], 0);

    // The script's commands, shaped by PodInputs, reach the pod's hardware.
    final inputs = PodInputs(ident, teams: const ['red', 'blue']);
    final fill = inputs.command('team_display', 'show', ['blue'])!;
    expect(
      [fill.$1, fill.$2, fill.$3],
      [
        'ring',
        'fill',
        {'team': 'blue'},
      ],
    );
    var from = pod.mark;
    expect(await client.command(fill.$1, fill.$2, fill.$3), isTrue);
    await pod.wait('LED fill 0 0 255', from: from);
    from = pod.mark;
    final tone = inputs.command('audio', 'tone', [2000, 150])!;
    expect(await client.command(tone.$1, tone.$2, tone.$3), isTrue);
    await pod.wait('TONE 2000 150', from: from);
    from = pod.mark;
    final play = inputs.command('audio', 'play', ['captured'])!;
    expect(play.$3, {
      'args': ['captured'],
    });
    expect(await client.command(play.$1, play.$2, play.$3), isTrue);
    await pod.wait('TONE 1600 200', from: from);
    from = pod.mark;
    final b = inputs.command('ring', 'set_brightness', [30])!;
    expect(await client.command(b.$1, b.$2, b.$3), isTrue);
    await pod.wait('LED brightness 30', from: from);
    // A command the pod has no part for is still acknowledged (and counted).
    expect(await client.command('nfc', 'write', {'args': '00'}), isTrue);
    expect((await pod.status())['cmd_unknown'], 1);
    await client.close();
  });

  test('a real IDENT as a game sees it: teams by number, tags, keys', () async {
    final client = PodClient(await SocketPodTransport.usb(pod));
    final ident = await identified(client);
    final key = List<int>.generate(16, (i) => 100 + i);
    final inputs = PodInputs(ident, teams: const ['red', 'blue', 'green']);
    Map<String, Object?> tagData(List<int> uid, List<int>? tag) => podTagData(
      uid,
      tag,
      gameId: 4242,
      gameKey: key,
      teams: const ['red', 'blue', 'green'],
    );

    // Button 2 stands for the game's 2nd team, as on a Field Box.
    pod.send('press 2');
    final press = await next(client, capId: 'btn.2', name: 'press');
    pod.send('release 2');
    expect(inputs.input(press, tagData: tagData)?.$2, {'team': 'blue'});
    // Button 4: this game has only three teams.
    pod.send('hold 4 100');
    final four = await next(client, capId: 'btn.4', name: 'press');
    expect(inputs.input(four, tagData: tagData), isNull);

    // A player tag signed for the game, on the pod's reader.
    final tag = encodeTag(
      const PlayerTag(player: 'p-17', team: 3, gameId: 4242),
      key,
    );
    pod.send('tag 04a1b2c3d4e5f6 ${hexEncode(tag)}');
    final read = await next(client, capId: 'nfc', name: 'tag');
    expect(read.data, {'uid': '04a1b2c3d4e5f6', 'tag': hexEncode(tag)});
    expect(inputs.input(read, tagData: tagData)!.$2, {
      'uid': '04a1b2c3d4e5f6',
      'valid': true,
      'player': 'p-17',
      'team': 'green',
    });
    // A join card is not forwarded; a card without our record is, as unsigned.
    pod.send('join 0411223344');
    await Future<void>.delayed(const Duration(milliseconds: 700));
    pod.send('tag 05a1b2c3');
    final plain = await next(client, capId: 'nfc', name: 'tag');
    expect(plain.data, {'uid': '05a1b2c3'});
    expect(inputs.input(plain, tagData: tagData)!.$2['reason'], 'unsigned');

    pod.send('key 7');
    final key7 = inputs.input(
      await next(client, capId: 'keypad'),
      tagData: tagData,
    )!;
    expect((key7.$1, key7.$2['key']), ('keypad.key', '7'));

    // The enclosure opened.
    await pod.caseArmed();
    pod.send('case open');
    final opened = await next(client, capId: 'case', name: 'opened');
    expect(inputs.caseOpened(opened), isTrue);
    pod.send('case closed');
    expect(inputs.caseClosed(await next(client, capId: 'case')), isTrue);
    await client.close();
  });

  test('over Bluetooth at a 23-byte MTU: frames in 20-byte pieces', () async {
    await pod.stop();
    pod = await HostPod.start(args: ['--ble-mtu', '23']);
    final ble = await BleSocketPodTransport.connect(pod, mtu: 23);
    final client = PodClient(ble);
    // The pod sends IDENT when the link is ready; the client asks too.
    final ident = await identified(client);
    expect(ident.capabilities, hasLength(9));
    expect(ble.notificationSizes.where((n) => n > 20), isEmpty);
    expect(ble.notificationSizes.length, greaterThan(5));
    pod.send('press 3');
    expect((await next(client, capId: 'btn.3')).name, 'press');
    final from = pod.mark;
    // A CMD frame of 34 bytes goes as two writes.
    expect(
      await client.command('ring', 'color', {'r': 1, 'g': 2, 'b': 3}),
      isTrue,
    );
    await pod.wait('LED fill 1 2 3', from: from);
    final st = await pod.status();
    expect((st['ble'], st['usb'], st['pending']), (true, false, 0));
    await client.close();
    // The pod notices the link gone when its own loop reads the close.
    var bleUp = true;
    final end = DateTime.now().add(hostDeadline);
    while (bleUp && DateTime.now().isBefore(end)) {
      bleUp = (await pod.status())['ble'] == true;
      if (bleUp) await Future<void>.delayed(const Duration(milliseconds: 20));
    }
    expect(
      bleUp,
      false,
      reason: 'the pod kept the link ${pod.lines.reversed.take(6)}',
    );
  });

  test('a phone that goes silent: the pod gives the link up', () async {
    // A link that sends IDENT and never acknowledges anything.
    final usb = await SocketPodTransport.usb(pod);
    final frames = <Frame>[];
    final dec = FrameDecoder();
    usb.incoming.listen((d) => frames.addAll(dec.feed(d)));
    await usb.send(encodeFrame(FrameType.radioCmd, [RadioOp.ident]));
    // The pod has the link when it answers with its IDENT; only then does an
    // EVT go to it.
    await eventually(
      () => frames.any((f) => f.type == FrameType.ident),
      'IDENT',
      detail: () => '${pod.lines.reversed.take(6)}',
    );
    await pod.caseArmed();
    pod.send('case open'); // one EVT ("opened"), never acknowledged
    // It is sent, then again 3 times 500 ms apart, then the link is given up
    // (the pod's own timers): wait for that end state, with all 4 EVTs
    // heard, not for a time.
    var st = await pod.status();
    final end = DateTime.now().add(hostDeadline);
    while (st['links_broken'] != 1 && DateTime.now().isBefore(end)) {
      await Future<void>.delayed(const Duration(milliseconds: 50));
      st = await pod.status();
    }
    await eventually(
      () => frames.where((f) => f.type == FrameType.evt).length >= 4,
      'the 4 EVTs',
      detail: () => '$st ${pod.lines.reversed.take(6)}',
    );
    final evts = frames.where((f) => f.type == FrameType.evt).toList();
    expect(evts, hasLength(4)); // sent, then again 3 times, 500 ms apart
    expect(evts.map((f) => hexEncode(f.payload)).toSet(), hasLength(1));
    st = await pod.status();
    expect((st['usb'], st['links_broken'], st['evt_lost']), (false, 1, 1));
    await usb.close();
  });
}
