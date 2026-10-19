// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The capability proxy codec (lib/pod/pod_codec.dart) against the shared
// vectors that the C codec (core/tests/test_proxy.c, firmware's
// test_proxy_codec.c) and the Python one check:
// protocol/vectors/capability_proxy.yaml.

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:yaml/yaml.dart';

Object? _plain(Object? v) => switch (v) {
  YamlMap() => {for (final e in v.entries) '${e.key}': _plain(e.value)},
  YamlList() => [for (final e in v) _plain(e)],
  _ => v,
};

Map<String, Object?> _vectors() =>
    _plain(
          loadYaml(
            File(
              '../protocol/vectors/capability_proxy.yaml',
            ).readAsStringSync(),
          ),
        )!
        as Map<String, Object?>;

List<Map<String, Object?>> _list(Map<String, Object?> v, String k) =>
    (v[k]! as List).cast<Map<String, Object?>>();

PodIdent _ident(Map<String, Object?> f) => PodIdent(
  fwVersion: f['fw_version']! as String,
  capabilities: (f['capabilities']! as List)
      .map((c) => (c as Map).cast<String, Object?>())
      .toList(),
  batteryPct: f['battery_pct'] as int?,
  hasRadio: f['has_radio']! as bool,
);

void main() {
  final v = _vectors();

  test('CRC-16/CCITT-FALSE check value', () {
    final c = v['crc']! as Map<String, Object?>;
    expect(crc16(hexDecode(c['data']! as String)), c['crc']);
  });

  group('IDENT', () {
    for (final c in _list(v, 'ident')) {
      test('${c['name']}', () {
        final f = c['fields']! as Map<String, Object?>;
        final payload = encodeIdent(_ident(f));
        expect(hexEncode(payload), c['payload']);
        expect(hexEncode(encodeFrame(FrameType.ident, payload)), c['frame']);
        final back = decodeIdent(payload);
        expect(back.toJson(), f);
      });
    }
  });

  for (final kind in ['evt', 'cmd']) {
    group(kind.toUpperCase(), () {
      for (final c in _list(v, kind)) {
        test('${c['name']}', () {
          final f = c['fields']! as Map<String, Object?>;
          final name = (kind == 'evt' ? f['event'] : f['method'])! as String;
          final data = ((kind == 'evt' ? f['data'] : f['args'])! as Map)
              .cast<String, Object?>();
          final msg = ProxyMessage(
            capId: f['cap_id']! as String,
            name: name,
            data: data,
            seq: f['seq']! as int,
          );
          final payload = encodeMessage(msg);
          expect(hexEncode(payload), c['payload']);
          final type = kind == 'evt' ? FrameType.evt : FrameType.cmd;
          expect(hexEncode(encodeFrame(type, payload)), c['frame']);
          final back = decodeMessage(payload);
          expect(back.capId, msg.capId);
          expect(back.name, name);
          expect(back.data, data);
          expect(back.seq, msg.seq);
        });
      }
    });
  }

  group('ACK', () {
    for (final c in _list(v, 'ack')) {
      test('${c['name']}', () {
        final payload = encodeAck(c['seq']! as int);
        expect(hexEncode(payload), c['payload']);
        expect(hexEncode(encodeFrame(FrameType.ack, payload)), c['frame']);
        expect(decodeAck(payload), c['seq']);
      });
    }
  });

  group('radio frames', () {
    for (final c in _list(v, 'radio')) {
      test('${c['name']}', () {
        final f = c['fields']! as Map<String, Object?>;
        final type = c['type']! as int;
        final payload = switch (type) {
          FrameType.radioRx => radioRx(
            hexDecode(f['header']! as String),
            hexDecode(f['payload']! as String),
            f['rssi']! as int,
            f['snr']! as int,
            f['epoch']! as int,
          ),
          FrameType.radioTx => radioTx(
            hexDecode(f['header']! as String),
            hexDecode(f['payload']! as String),
          ),
          FrameType.radioTxAck => radioTxAck(
            f['seq']! as int,
            f['status']! as int,
          ),
          FrameType.radioCmd when f['opcode'] == RadioOp.configure =>
            radioConfigure(
              gameId: f['game_id']! as int,
              nodeId: f['node_id']! as int,
              epoch: f['epoch']! as int,
              maxHops: f['max_hops']! as int,
              channelHz: f['channel_hz']! as int,
              key: hexDecode(f['key']! as String),
            ),
          FrameType.radioCmd => [f['opcode']! as int],
          FrameType.radioStatus => utf8.encode(f['json']! as String),
          FrameType.radioError => radioError(
            f['code']! as int,
            f['message']! as String,
          ),
          _ => throw StateError('type $type'),
        };
        expect(hexEncode(payload), c['payload']);
        expect(hexEncode(encodeFrame(type, payload)), c['frame']);
      });
    }
  });

  test('keys 6-23 a later version adds are skipped', () {
    final s = v['skipped_keys']! as Map<String, Object?>;
    final ident = s['ident']! as Map<String, Object?>;
    expect(
      decodeIdent(hexDecode(ident['payload']! as String)).fwVersion,
      ident['fw_version'],
    );
    final evt = s['evt']! as Map<String, Object?>;
    final back = decodeMessage(hexDecode(evt['payload']! as String));
    final hold = _list(v, 'evt').firstWhere((e) => e['name'] == evt['same_as']);
    expect(hexEncode(encodeMessage(back)), hold['payload']);
  });

  group('invalid payloads are refused', () {
    for (final c in _list(v, 'invalid')) {
      test('${c['name']}: ${c['why']}', () {
        final payload = hexDecode(c['payload']! as String);
        final type = c['type']! as int;
        expect(
          () => switch (type) {
            FrameType.ident => decodeIdent(payload),
            FrameType.ack => decodeAck(payload),
            _ => decodeMessage(payload),
          },
          throwsA(isA<ProxyException>()),
        );
      });
    }
  });

  test('a stream with junk: the good frames, one CRC and one length error', () {
    final s = v['stream']! as Map<String, Object?>;
    final bytes = hexDecode(s['bytes']! as String);
    // Fed in pieces, as a USB or BLE link delivers them.
    final d = FrameDecoder();
    final frames = <Frame>[];
    for (var i = 0; i < bytes.length; i += 7) {
      frames.addAll(
        d.feed(bytes.sublist(i, i + 7 > bytes.length ? bytes.length : i + 7)),
      );
    }
    final want = (s['frames']! as List).cast<Map<String, Object?>>();
    expect(frames.length, want.length);
    for (var i = 0; i < want.length; i++) {
      expect(frames[i].type, want[i]['type']);
      expect(hexEncode(frames[i].payload), want[i]['payload']);
    }
    expect(d.crcErrors, s['crc_errors']);
    expect(d.lengthErrors, s['length_errors']);
  });
}
