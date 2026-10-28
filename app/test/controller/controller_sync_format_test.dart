// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The sync bodies' checker on the phone (lib/controller/
// controller_sync_format.dart, PE24 slice S7) against the shared vectors
// the Pi's controller/tests/test_sync_format.py and the site server run:
// protocol/vectors/sync.json (the bodies, the answers of the endpoints the
// controller pulls, the remote GM's and the ATAK relay's stream messages,
// the merges).

import 'dart:convert';

import 'package:atalaia_app/controller/controller_sync_format.dart';
import 'package:atalaia_app/controller/field_controller.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/recording_radio.dart';
import '../support/vectors.dart';

Object? _copy(Object? v) => jsonDecode(jsonEncode(v));

void main() {
  final v = loadVectors('sync.json');
  List<Map<String, Object?>> list(Object? l) =>
      (l! as List).cast<Map<String, Object?>>();

  test('the counts and kinds are the Pi\'s', () {
    expect((list(v['valid']).length, list(v['invalid']).length), (14, 65));
    final answers = v['answers']! as Map;
    expect(
      (list(answers['valid']).length, list(answers['invalid']).length),
      (18, 75),
    );
    expect({
      for (final c in list(answers['valid'])) c['kind'],
    }, syncAnswers.keys.toSet());
    expect({
      for (final c in list(v['valid'])) c['kind'],
    }, syncChecks.keys.toSet());
    final stream = v['stream']! as Map;
    expect(
      (list(stream['valid']).length, list(stream['invalid']).length),
      (19, 51),
    );
    expect({
      for (final c in list(stream['valid'])) c['kind'],
    }, streamChecks.keys.toSet());
  });

  group('bodies', () {
    for (final c in list(v['valid'])) {
      test('${c['name']}', () {
        final body = syncChecks[c['kind']]!(_copy(c['body']));
        if (c.containsKey('info')) {
          expect({
            for (final n in body['nodes']! as List)
              '${(n as Map)['node_id']}': n['info'],
          }, c['info']);
        }
        expect(
          (c['body']! as Map).containsKey('game'),
          gameKinds.contains(c['kind']),
        );
      });
    }
    for (final c in list(v['invalid'])) {
      test('refuses ${c['name']}', () {
        expect(
          () => syncChecks[c['kind']]!(_copy(c['body'])),
          throwsA(
            isA<SyncFormatError>()
                .having((e) => e.code, 'code', c['error'])
                .having((e) => e.path, 'path', c['path']),
          ),
        );
      });
    }
  });

  for (final block in ['answers', 'stream']) {
    final checks = block == 'answers' ? syncAnswers : streamChecks;
    group(block, () {
      final b = v[block]! as Map;
      for (final c in list(b['valid'])) {
        test('${c['name']}', () => checks[c['kind']]!(_copy(c['body'])));
      }
      for (final c in list(b['invalid'])) {
        test('refuses ${c['name']}', () {
          expect(
            () => checks[c['kind']]!(_copy(c['body'])),
            throwsA(
              isA<SyncFormatError>()
                  .having((e) => e.code, 'code', c['error'])
                  .having((e) => e.path, 'path', c['path']),
            ),
          );
        });
      }
    });
  }

  test('a command\'s defaults', () {
    final stream = list((v['stream']! as Map)['valid']);
    Map<String, Object?> named(String n) =>
        _copy(stream.firstWhere((c) => c['name'] == n)['body'])!
            as Map<String, Object?>;
    expect(checkCommand(named('command_mode_every_node'))['params'], {
      'name': 'refill',
      'node': 0xffff,
    });
    expect(checkCommand(named('command_end'))['params'], {'reason': ''});
  });

  test('what the site no longer lists is the Pi\'s (decision S20-8)', () {
    final cases = list(v['library_removal']);
    expect(cases.length, 5);
    for (final c in cases) {
      final answer = checkPresets(_copy(c['answer']));
      final state = {
        for (final e in (c['state']! as Map).entries)
          e.key as String: (e.value! as Map).cast<String, String>(),
      };
      final want = (c['removals']! as Map).cast<String, Object?>();
      expect(libraryRemovals(state, answer), {
        for (final e in want.entries) e.key: (e.value! as List).cast<String>(),
      }, reason: '${c['name']}');
    }
  });

  test('the merges, and the phone\'s FieldController reaches the same '
      'totals (P4R10)', () {
    for (final c in list(v['merge'])) {
      final teams = (c['teams']! as List).cast<String>();
      var counters = <String, Map<String, int>>{};
      final fc = FieldController(
        transport: RecordingRadio(),
        gameId: 1,
        teams: teams,
      );
      for (final s in (c['snapshots']! as List).cast<Map<String, Object?>>()) {
        final snap = {
          for (final e in s.entries)
            e.key: (e.value! as Map).cast<String, int>(),
        };
        counters = mergeCounters(counters, snap);
        snap.forEach(fc.mergeCounters);
      }
      expect(counters, c['counters']);
      final deltas = [
        for (final d in (c['deltas']! as List).cast<List<Object?>>())
          (d[0] as String, d[1] as int),
      ];
      expect(syncTotals(teams, counters, deltas), c['totals']);
      for (final (team, amount) in deltas) {
        fc.adjustScore(team, amount, '');
      }
      expect({for (final t in teams) t: fc.totalScores[t] ?? 0}, c['totals']);
    }
  });

  test('public keys: standard base64 with padding only', () {
    final raw = List.generate(32, (i) => i);
    expect(publicKeyBytes(base64.encode(raw)), raw);
    for (final bad in <Object?>[
      raw.map((b) => b.toRadixString(16).padLeft(2, '0')).join(),
      base64Url.encode(List.filled(32, 0xfb)),
      '${base64.encode(raw).substring(0, 43)}B',
      null,
      32,
    ]) {
      expect(() => publicKeyBytes(bad), throwsA(isA<SyncFormatError>()));
    }
  });

  test('an event\'s defaults', () {
    final ev = checkEvent(<String, Object?>{
      'id': 1,
      'node': 2,
      'seq': 3,
      't': 4,
      'type': 'game.start',
      'prio': 'critical',
    });
    expect(
      (ev['team'], ev['squad'], ev['epoch'], ev['pkt_seq']),
      (null, null, null, null),
    );
    expect(ev['data'], isEmpty);
  });
}
