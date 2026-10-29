// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The field's radio channel on the phone controller
// (lib/controller/controller_channel.dart, slice S7a of PE24) beyond the
// shared contract cases: the ranking and the suggestion (channels.py's
// cases), why a scan cannot run on a phone, a measurement that fails, a
// stored channel that is not legal, the I/O pod's MEASURE against a
// scripted pod link, and a whole scan through the host pod (the pod
// firmware's own code measuring).

import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_boxes.dart';
import 'package:atalaia_app/controller/controller_channel.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_radio.dart';
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:atalaia_app/controller/pod_modem.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:atalaia_app/protocol/field_frame.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/pod_host.dart';
import '../support/recording_modem.dart';
import 'pod_modem_test.dart' show ScriptedPod, settle;

RadioNoise noise(int hz, int p90, {int hits = 0}) => RadioNoise(
  channelHz: hz,
  dwellMs: 1000,
  samples: 1000,
  minDbm: p90 - 6,
  meanDbm: p90 - 3,
  p50Dbm: p90 - 4,
  p90Dbm: p90,
  maxDbm: p90 + 9,
  cadTries: 10,
  cadDetected: hits,
);

/// A radio whose measurements fail from the [failAt]th on.
class FailingModem extends RecordingModem {
  FailingModem(this.failAt);
  final int failAt;
  var count = 0;

  @override
  Future<RadioNoise> measure(int channelHz, int dwellMs, {bool cad = true}) {
    if (++count >= failAt) {
      return Future.error(
        MeasureException('radio', 'MEASURE: the radio failed'),
      );
    }
    return super.measure(channelHz, dwellMs, cad: cad);
  }
}

void main() {
  group('the ranking and the suggestion (channels.py)', () {
    test(
      'quietest first, LoRa activity last; the quiet full-power channel',
      () {
        final results = [
          noise(869525000, -110),
          noise(868100000, -125, hits: 5),
          noise(868300000, -118),
        ];
        expect(suggestChannel(results, -105), {
          'channel_hz': 869525000,
          'reason': 'quiet_full_power',
        });
        final scan = ChannelScan(
          (hz, ms) async => noise(hz, -118),
          11,
          -105,
          (_) {},
        )..results.addAll(results);
        expect(
          [
            for (final r in scan.public()['results']! as List)
              (r as Map)['channel_hz'],
          ],
          [868300000, 869525000, 868100000],
        );
      },
    );

    test('else the quietest of all, noisy or not', () {
      expect(
        suggestChannel([noise(869525000, -100), noise(868300000, -110)], -105),
        {'channel_hz': 868300000, 'reason': 'quietest'},
      );
      expect(
        suggestChannel([noise(869525000, -100), noise(868300000, -99)], -105),
        {'channel_hz': 869525000, 'reason': 'quietest_but_noisy'},
      );
      expect(suggestChannel([], -105), isNull);
    });

    test('the candidates, the random pick, the dwell', () {
      expect(scanCandidates(), hasLength(11));
      expect(
        describeChannel(868800000),
        containsPair('notes', ['low_airtime']),
      );
      expect(describeChannel(868800000)['usable'], false);
      expect(channelOk(868000000), isFalse); // spills out of its sub-band
      final r = randomChannel();
      expect(scanCandidates(), contains(r['channel_hz']));
      expect([r['pool'], r['pool_full_power']], [11, 3]);
      expect(perChannelDwellS(60, 11), closeTo(5.4545, 1e-4));
      expect(perChannelDwellS(600, 11), 10.0);
      expect(perChannelDwellS(0.01, 11), 0.01);
      expect(
        [roundHalfEven(0.5), roundHalfEven(1.5), roundHalfEven(2.6)],
        [0, 2, 3],
      );
    });
  });

  test('a phone with no pod, or a pod without a radio, cannot scan', () {
    final e = ControllerEngine();
    final ch = ControllerChannel(e);
    expect(ch.settings()['scan_unavailable'], 'no_modem');
    expect(
      () => ch.startScan(null),
      throwsA(isA<ControllerError>().having((x) => x.status, 'status', 503)),
    );
    // The channel can still be chosen: new games use it.
    expect(ch.setChannel(869575000, 'manual')['confirmed'], true);
    expect(e.fieldChannel, 869575000);
    final m = RecordingModem()..ident = {'radio': 'none'};
    expect(
      ControllerChannel(
        ControllerEngine(modem: m),
      ).settings()['scan_unavailable'],
      'no_radio',
    );
  });

  test(
    'a measurement that fails ends the scan, back on the field channel',
    () async {
      final m = FailingModem(3);
      final e = ControllerEngine(modem: m);
      final ch = ControllerChannel(e);
      final states = <Object?>[];
      e.addListener((msg) {
        if (msg['type'] == 'radio_scan') {
          states.add((msg['scan']! as Map)['state']);
        }
      });
      ch.startScan(11);
      await ch.scan!.done;
      final s = ch.scanStatus()!;
      expect(s['state'], 'failed');
      expect(s['error'], 'MEASURE: the radio failed');
      expect(s['measured'], 2);
      expect(s['suggestion'], isNull);
      expect(states, ['running', 'running', 'running', 'failed']);
      expect(m.log.last, {'kind': 'channel', 'channel_hz': 869525000});
      // Kept for the next start.
      expect(
        jsonDecode(e.store.getSetting('radio.last_scan')!),
        containsPair('state', 'failed'),
      );
    },
  );

  group('a change of the field channel is told to the boxes (MOVE)', () {
    // RFC 0001 Amendment 19, as controller/tests/test_reinvite.py MoveTests:
    // the bench finding of 2026-10-29, a scan moved the channel and the idle
    // boxes, listening on their last game's, were lost.
    const oldHz = 869525000, newHz = 869925000;
    late int now;
    late RecordingModem radio;
    late ControllerEngine engine;
    late ControllerChannel ch;
    late Uint8List key;

    setUp(() {
      now = 0;
      radio = RecordingModem();
      engine = ControllerEngine(modem: radio, clockMs: () => now)
        ..joinKey = Uint8List.fromList(List.generate(32, (i) => i));
      ControllerBoxes(engine);
      ch = ControllerChannel(engine);
      key = fieldKey(engine.joinKey);
      radio.log.clear();
    });

    void run(int ms) {
      final end = now + ms;
      while (now < end) {
        now += 100;
        engine.tick();
      }
    }

    List<String> kinds() => [
      for (final f in radio.fields) decodeFieldFrame(key, f)['kind']! as String,
    ];

    List<int> tunes() => [
      for (final e in radio.log)
        if (e['kind'] == 'channel') e['channel_hz']! as int,
    ];

    test(
      'MOVE three times on the old channel, then the new one and a DISCOVER',
      () {
        final out = ch.setChannel(newHz, 'scan');
        expect((out['channel']! as Map)['channel_hz'], newHz);
        expect(out['previous_channels_hz'], [oldHz]);
        expect(engine.fieldChannel, newHz);
        // The radio stays on the old channel to say it: nothing tunes to the new
        // one yet, and the first MOVE is already out.
        expect(tunes(), [oldHz]);
        expect(kinds(), ['move']);
        final move = decodeFieldFrame(key, radio.fields.first);
        expect(move['channel_hz'], newHz);
        expect(move['rev'], greaterThan(0));
        expect(engine.store.getSetting('radio.move_rev'), '${move['rev']}');
        run(12000);
        expect(kinds(), ['move', 'move', 'move', 'discover']);
        expect(tunes().last, newHz);
        expect(tunes().where((hz) => hz == newHz), hasLength(1));
      },
    );

    test('radio.move says how far the MOVEs are, and the stream hears of it', () {
      expect(ch.settings()['move'], isNull);
      final heard = <Map<String, Object?>>[];
      engine.addListener((m) {
        if (m['type'] == 'radio') heard.add(m);
      });
      final out = ch.setChannel(newHz, 'scan');
      final first = out['move']! as Map<String, Object?>;
      expect(first['state'], 'telling');
      expect(
        [first['from_hz'], first['to_hz'], first['sent'], first['repeats']],
        [oldHz, newHz, 1, 3],
      );
      expect(
        first['rev'],
        int.parse(engine.store.getSetting('radio.move_rev')!),
      );
      run(12000);
      final done = ch.settings()['move']! as Map<String, Object?>;
      expect([done['state'], done['sent']], ['moved', 3]);
      // One radio message per step: the change's own (1 said), 2, 3, then moved.
      final steps = [
        for (final m in heard)
          (((m['radio']! as Map)['move']) as Map)['state'] == 'moved'
              ? 'moved'
              : '${(((m['radio']! as Map)['move']) as Map)['sent']}',
      ];
      expect(steps, ['1', '2', '3', 'moved']);
    });

    test(
      'the revision rises, the same channel says nothing, a region forgets',
      () {
        ch.setChannel(newHz, 'scan');
        run(12000);
        final first = int.parse(engine.store.getSetting('radio.move_rev')!);
        ch.setChannel(868100000, 'manual');
        run(12000);
        expect(
          int.parse(engine.store.getSetting('radio.move_rev')!),
          first + 1,
        );
        expect(ch.history(), [newHz, oldHz]);
        final n = radio.fields.length;
        ch.setChannel(868100000, 'manual'); // accepting it again
        run(12000);
        expect(radio.fields.length, n);
        ch.setRegion('as923-tw');
        expect(ch.history(), isEmpty);
      },
    );

    test("the GM's discover sweeps the earlier channels, once a minute", () {
      ch.setChannel(newHz, 'scan');
      run(
        20000,
      ); // and the DISCOVER after the MOVEs is no longer within the 10 s minimum
      radio.fields.clear();
      radio.log.clear();
      final r = engine.boxes!.discover();
      expect(r, {
        'sent': true,
        'sweep': [oldHz],
      });
      run(15000);
      // DISCOVER, four seconds later the MOVE twice on the old channel, then
      // DISCOVER on the new one.
      expect(kinds(), ['discover', 'move', 'move', 'discover']);
      expect(tunes(), [oldHz, newHz]); // tuned once to each
      expect(engine.boxes!.discover()['sweep'], isEmpty);
    });
  });

  test('a stored channel that is not legal falls back to the default', () {
    final store = MemoryControllerStore()
      ..setSetting('radio.channel_hz', '868000000')
      ..setSetting('radio.channel_source', 'manual');
    final e = ControllerEngine(store: store);
    final ch = ControllerChannel(e);
    expect(e.fieldChannel, 869525000);
    expect(ch.settings()['source'], 'default');
  });

  group("the I/O pod's MEASURE (a scripted pod)", () {
    late ScriptedPod link;
    late PodModem modem;
    final errors = <String>[];

    setUp(() async {
      errors.clear();
      link = ScriptedPod();
      modem = PodModem(
        PodClient(link),
        pingInterval: const Duration(milliseconds: 50),
      )..onError = (code, message) => errors.add(code);
      await modem.start();
      link.ident();
      await settle();
      link.pong();
      await settle();
      // Under load the link can still be connecting after the two settles:
      // wait for it to be up (the PINGs and the PONG above), at most 5 s.
      final deadline = DateTime.now().add(const Duration(seconds: 5));
      while (!modem.isUp && DateTime.now().isBefore(deadline)) {
        link.pong();
        await Future<void>.delayed(const Duration(milliseconds: 20));
      }
      expect(modem.isUp, isTrue);
    });

    tearDown(() async => modem.close());

    test(
      'RADIO_CMD 8 with the channel, the dwell and CAD; RADIO_NOISE answers',
      () async {
        expect(modem.canMeasure, isTrue);
        final f = modem.measure(869525000, 500);
        await settle();
        // (PINGs go on meanwhile.)
        final measures = [
          for (final (op, params) in link.commands)
            if (op == RadioOp.measure) params,
        ];
        expect(measures, [
          [0x33, 0xd3, 0xe6, 0x08, 0x01, 0xf4, 1],
        ]);
        link.frame(
          FrameType.radioNoise,
          noise(869525000, -111, hits: 2).encode(),
        );
        final n = await f;
        expect([n.channelHz, n.p90Dbm, n.cadDetected], [869525000, -111, 2]);
      },
    );

    test(
      "the pod's refusal is the measurement's error, not an alert",
      () async {
        final f = modem.measure(869525000, 500);
        await settle();
        link.frame(FrameType.radioError, [
          7,
          ...utf8.encode('MEASURE: a game is configured; CLEAR it first'),
        ]);
        await expectLater(
          f,
          throwsA(
            isA<MeasureException>().having((e) => e.code, 'code', 'busy'),
          ),
        );
        expect(errors, isEmpty);
        // One at a time; another channel's answer is refused.
        final g = modem.measure(869525000, 500);
        expect(modem.measure(869575000, 500), throwsA(isA<MeasureException>()));
        link.frame(FrameType.radioNoise, noise(869575000, -111).encode());
        await expectLater(
          g,
          throwsA(
            isA<MeasureException>().having((e) => e.code, 'code', 'bad_frame'),
          ),
        );
      },
    );

    test(
      'a pod whose IDENT says measure: false: the scan refuses up front (PE24-105)',
      () async {
        // An older pod leaves the flag out and is taken to measure (above).
        expect(modem.ident!.containsKey('measure'), isFalse);
        link.ident(measure: true);
        await settle();
        expect(modem.canMeasure, isTrue);
        link.ident(measure: false);
        await settle();
        expect(modem.isUp, isTrue);
        expect(modem.hasRadioChip, isTrue);
        expect(modem.canMeasure, isFalse);
        final e = ControllerEngine(modem: modem);
        final ch = ControllerChannel(e);
        // The Pi's reason for a modem without `measure` (engine.py).
        expect(ch.settings()['scan_unavailable'], 'old_firmware');
        expect(
          () => ch.startScan(null),
          throwsA(
            isA<ControllerError>()
                .having((x) => x.status, 'status', 503)
                .having(
                  (x) => x.message,
                  'message',
                  scanUnavailableTexts['old_firmware'],
                ),
          ),
        );
        expect(ch.scan, isNull);
        await settle();
        expect([
          for (final (op, _) in link.commands)
            if (op == RadioOp.measure) op,
        ], isEmpty);
      },
    );

    test('a pod without a radio chip cannot measure', () async {
      link.ident(radio: false);
      await settle();
      expect(modem.hasRadioChip, isFalse);
      expect(modem.canMeasure, isFalse);
      // Never up without a radio (PE24-45), so the scan says the radio is down.
      final e = ControllerEngine(modem: modem);
      expect(ControllerChannel(e).settings()['scan_unavailable'], 'modem_down');
    });
  });

  test(
    'a whole scan through the host pod (the pod firmware measuring)',
    skip: hostSkip(['ATALAIA_POD_HOST']),
    () async {
      final hub = await AirHub.start();
      final pod = await HostPod.start(airPeer: hub.port);
      hub.members.add(pod.airPort);
      final client = PodClient(await SocketPodTransport.usb(pod));
      final m = PodModem(
        client,
        pingInterval: const Duration(milliseconds: 200),
      );
      final e = ControllerEngine(modem: m);
      final ch = ControllerChannel(e);
      addTearDown(() async {
        await client.close();
        await pod.stop();
        hub.close();
      });
      await m.start();
      final end = DateTime.now().add(const Duration(seconds: 8));
      while (!m.isUp && DateTime.now().isBefore(end)) {
        await Future<void>.delayed(const Duration(milliseconds: 25));
      }
      expect(m.isUp, isTrue, reason: 'the pod radio');
      expect(ch.settings()['scan_unavailable'], isNull);
      ch.startScan(1); // 11 channels of 91 ms
      await ch.scan!.done.timeout(const Duration(seconds: 20));
      final s = ch.scanStatus()!;
      expect(s['error'], isNull);
      expect(s['state'], 'done');
      expect(s['measured'], 11);
      for (final r in (s['results']! as List).cast<Map<String, Object?>>()) {
        // The host pod's noise: -122 to -118 dBm, no LoRa preambles.
        expect(r['p90_dbm'], inInclusiveRange(-122, -118));
        expect(r['cad_detected'], 0);
        expect(r['dwell_ms'], 91);
        expect(r['quiet'], isTrue);
      }
      expect(s['suggestion'], containsPair('reason', 'quiet_full_power'));
      final status = await pod.status();
      expect(status['radio_configured'], false);
    },
  );
}
