// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The Skirmesh-RF header and message codecs in Dart (lib/radio/rf_codec.dart)
// against the shared vectors the C codecs (core/tests/) and the Python ones
// (simulator/tests/) check: protocol/vectors/{header,hello,state,ack,cmd,time}.json.

import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

int _int(Object? v) => v is String ? int.parse(v) : v! as int;

void main() {
  group('header', () {
    final v = loadVectors('header.json');
    for (final c in cases(v, 'valid')) {
      test('${c['name']}', () {
        final h = (c['header'] as Map).cast<String, Object?>();
        final header = RfHeader(
          versionFlags: _int(h['version_flags']),
          gameId: _int(h['game_id']),
          source: _int(h['source']),
          seq: _int(h['seq']),
          hopLimit: _int(h['hop_limit']),
          type: _int(h['type']),
        );
        expect(hexEncode(header.encode()), c['bytes']);
        final back = RfHeader.decode(hexDecode(c['bytes'] as String));
        expect(hexEncode(back.encode()), c['bytes']);
      });
    }
    for (final c in cases(v, 'invalid')) {
      test('refuses ${c['name']}', () {
        expect(
          () => RfHeader.decode(hexDecode(c['bytes'] as String)),
          throwsA(isA<RfException>()),
        );
      });
    }
    test('a version 1 header for the pod to encrypt', () {
      final h = RfHeader.v1(
        gameId: 1000,
        source: 7,
        seq: 42,
        hopLimit: 2,
        type: RfType.event,
        prio: RfPrio.normal,
        ack: true,
      );
      // The vector's normal_event, without the encrypted bit (the pod sets it).
      expect(hexEncode(h.encode()), '2c03e80007002a0202');
      expect((h.prio, h.ackRequested, h.encrypted), (1, true, false));
    });
  });

  group('HELLO', () {
    final v = loadVectors('hello.json');
    for (final c in cases(v, 'valid')) {
      test('${c['name']}', () {
        final f = (c['fields'] as Map).cast<String, Object?>();
        final hello = RfHello(
          nodeName: f['node_name']! as String,
          platform: f['platform']! as int,
          fwVersion: f['fw_version']! as String,
          coreVersion: f['core_version']! as String,
          tier: f['tier']! as int,
          capabilities: (f['capabilities']! as List).cast<int>(),
          transports: f['transports']! as int,
          batteryPct: f['battery_pct'] as int?,
          epoch: f['epoch']! as int,
        );
        expect(hexEncode(hello.encode()), c['cbor']);
        final back = RfHello.decode(hexDecode(c['cbor'] as String));
        expect(hexEncode(back.encode()), c['cbor']);
        expect(back.nodeName, f['node_name']);
      });
    }
    for (final c in cases(v, 'invalid')) {
      test('refuses ${c['name']}', () {
        expect(
          () => RfHello.decode(hexDecode(c['cbor'] as String)),
          throwsA(isA<RfException>()),
        );
      });
    }
  });

  group('STATE', () {
    final v = loadVectors('state.json');
    for (final c in cases(v, 'valid')) {
      test('${c['name']}', () {
        final f = (c['fields'] as Map).cast<String, Object?>();
        final st = RfState(
          ownerTeam: f['owner_team']! as int,
          phase: f['phase']! as int,
          gameTimeMs: f['game_time_ms']! as int,
          counters: {
            for (final e in (f['counters']! as Map).entries)
              int.parse('${e.key}'): e.value as int,
          },
          rssi: f['rssi'] as int?,
          batteryPct: f['battery_pct'] as int?,
          flags: f['flags'] as int?,
          epoch: f['epoch']! as int,
        );
        expect(hexEncode(st.encode()), c['cbor']);
        final back = RfState.decode(hexDecode(c['cbor'] as String));
        expect(back.counters, st.counters);
        expect(hexEncode(back.encode()), c['cbor']);
      });
    }
    for (final c in cases(v, 'invalid')) {
      test('refuses ${c['name']}', () {
        expect(
          () => RfState.decode(hexDecode(c['cbor'] as String)),
          throwsA(isA<RfException>()),
        );
      });
    }
  });

  group('ACK', () {
    final v = loadVectors('ack.json');
    for (final c in cases(v, 'valid')) {
      test('${c['name']}', () {
        final f = (c['fields'] as Map).cast<String, Object?>();
        final bm = f['ack_bitmap'] as String?;
        final ack = RfAck(
          node: f['ack_node']! as int,
          seq: f['ack_seq']! as int,
          bitmap: bm == null ? null : hexDecode(bm),
        );
        expect(hexEncode(ack.encode()), c['cbor']);
        final back = RfAck.decode(hexDecode(c['cbor'] as String));
        expect((back.node, back.seq), (ack.node, ack.seq));
      });
    }
    for (final c in cases(v, 'invalid')) {
      test('refuses ${c['name']}', () {
        expect(
          () => RfAck.decode(hexDecode(c['cbor'] as String)),
          throwsA(isA<RfException>()),
        );
      });
    }
    test('what an ACK covers: the contiguous seq and the bitmap (D7)', () {
      // ack_with_bitmap: up to 100, then ff00ff: 101-108 and 117-124.
      final a = RfAck.decode(hexDecode('a301030218640343ff00ff'));
      expect(a.covers(0), isTrue);
      expect(a.covers(100), isTrue);
      expect(a.covers(101) && a.covers(108), isTrue);
      expect(a.covers(109) || a.covers(116), isFalse);
      expect(a.covers(117) && a.covers(124), isTrue);
      expect(a.covers(125), isFalse);
      // 0xFFFF: nothing contiguous yet.
      expect(const RfAck(node: 3, seq: 0xffff).covers(0), isFalse);
      expect(
        RfAck(node: 3, seq: 0xffff, bitmap: hexDecode('01')).covers(0),
        isTrue,
      );
    });
  });

  group('CMD', () {
    final v = loadVectors('cmd.json');
    for (final c in cases(v, 'valid')) {
      test('${c['name']}', () {
        final f = (c['fields'] as Map).cast<String, Object?>();
        final cmd = RfCmd(
          cmd: f['cmd']! as int,
          params: (f['params'] as Map?)?.cast<String, Object?>(),
          dest: f['dest'] as int?,
        );
        expect(hexEncode(cmd.encode()), c['cbor']);
        final back = RfCmd.decode(hexDecode(c['cbor'] as String));
        expect(back.params, cmd.params);
        expect(back.isFor(42), cmd.dest == null || cmd.dest == 42);
      });
    }
    for (final c in cases(v, 'invalid')) {
      test('refuses ${c['name']}', () {
        expect(
          () => RfCmd.decode(hexDecode(c['cbor'] as String)),
          throwsA(isA<RfException>()),
        );
      });
    }
    test('the opcodes by name, as on the Wi-Fi link', () {
      expect(
        [for (var i = 0; i < 9; i++) RfCmd(cmd: i).name],
        [
          'start',
          'pause',
          'resume',
          'end',
          'set_owner',
          'message',
          'reset',
          'reboot',
          'mode',
        ],
      );
      expect(const RfCmd(cmd: 0, dest: 0xffff).isFor(9), isTrue);
    });
  });

  group('TIME', () {
    final v = loadVectors('time.json');
    for (final c in cases(v, 'valid')) {
      test('${c['name']}', () {
        final f = (c['fields'] as Map).cast<String, Object?>();
        final t = RfTime(
          gameTimeMs: f['game_time_ms']! as int,
          gameState: f['game_state']! as int,
          durationMs: f['duration_ms']! as int,
          wallS: f['wall_s']! as int,
          term: f['term']! as int,
          txTimeUs: f['tx_time_us'] as int?,
        );
        expect(hexEncode(t.encode()), c['cbor']);
        final back = RfTime.decode(hexDecode(c['cbor'] as String));
        expect(back.stateName, rfGameStates[t.gameState]);
      });
    }
    for (final c in cases(v, 'invalid')) {
      test('refuses ${c['name']}', () {
        expect(
          () => RfTime.decode(hexDecode(c['cbor'] as String)),
          throwsA(isA<RfException>()),
        );
      });
    }
  });

  test('payloads outside the schema are refused', () {
    expect(
      () => RfCmd.decode(hexDecode('a201000418')),
      throwsA(isA<RfException>()),
    ); // a key the schema does not have, and a truncated value
    expect(() => RfTime.decode([0x80]), throwsA(isA<RfException>()));
    expect(
      () => const RfHello(
        nodeName: 'a-name-that-is-far-too-long',
        platform: 3,
        fwVersion: 'x',
        coreVersion: 'y',
        tier: 0,
        capabilities: [],
        transports: 3,
        epoch: 1,
      ).encode(),
      throwsA(isA<RfException>()),
    );
    expect(RfPrio.of('critical'), 2);
    expect(RfPrio.of(null), 1);
  });
}
