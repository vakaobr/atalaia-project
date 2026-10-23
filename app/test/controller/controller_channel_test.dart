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

import 'package:atalaia_app/controller/controller_channel.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_radio.dart';
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:atalaia_app/controller/pod_modem.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
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
