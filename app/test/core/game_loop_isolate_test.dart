// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The game loop isolate (ADR-P3-1): the node lives in its own isolate, the
// test isolate only sends messages. Most tests use the FFI stub, whose
// behaviour is fixed; the last ones run a real mode on the real core.

import 'dart:async';
import 'dart:io';

import 'package:atalaia_app/core/game_loop_isolate.dart';
import 'package:atalaia_app/core/node_types.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';

const _spec = NodeSpec(
  source: '-- any script',
  chunkName: '@stub/node.lua',
  nodeId: 3,
  teams: ['red', 'blue'],
);

/// Everything a running node sent, by kind.
class _Outputs {
  _Outputs(RunningNode node) {
    node.outputs.listen(all.add);
  }
  final all = <NodeOutput>[];
  List<EmittedEvent> get events => [
    for (final o in all)
      if (o is NodeEventOutput) o.event,
  ];
  List<NodeCommand> get commands => [
    for (final o in all)
      if (o is NodeCommandOutput) o.command,
  ];
  List<String> get logs => [
    for (final o in all)
      if (o is NodeLogOutput) o.line,
  ];
  List<NodeSnapshot> get statuses => [
    for (final o in all)
      if (o is NodeStatusOutput) o.snapshot,
  ];
}

/// Waits (in real time) until [done] holds, or fails after [timeout].
Future<void> _until(
  bool Function() done, {
  Duration timeout = const Duration(seconds: 10),
}) async {
  final end = DateTime.now().add(timeout);
  while (!done()) {
    if (DateTime.now().isAfter(end)) fail('timed out');
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
}

void main() {
  late String stub;

  setUpAll(() => stub = stubLibraryPath());

  group('manual clock (stub)', () {
    test('the node is set up in the isolate and reports its state', () async {
      final loop = await GameLoopIsolate.spawn(
        _spec,
        libraryPath: stub,
        clock: GameClock.manual,
      );
      addTearDown(loop.close);
      expect(loop.loaded, isTrue);
      expect(loop.lastSnapshot!.status, NodeStatus.running);
      final s = await loop.snapshot();
      expect(s.status, NodeStatus.running);
      expect(s.paused, isFalse);
      expect(s.timeMs, 0);
      expect(s.memUsed, 4096);
      expect(s.scores, {'red': 0, 'blue': 0});
    });

    test(
      'an input comes back as event, command and log before its reply',
      () async {
        final loop = await GameLoopIsolate.spawn(
          _spec,
          libraryPath: stub,
          clock: GameClock.manual,
        );
        addTearDown(loop.close);
        final out = _Outputs(loop);
        expect(await loop.input('game.start', {'preset': 'x'}), isTrue);
        // Delivered in order, all of it before the input's future completed.
        expect(out.all.map((o) => o.runtimeType), [
          NodeEventOutput,
          NodeCommandOutput,
          NodeLogOutput,
        ]);
        expect(out.events.single.type, 'game.start');
        expect(out.events.single.node, 3);
        expect(out.events.single.data, {'preset': 'x'});
        expect(out.commands.single.args, [
          'stub',
          {'inputs': 1},
        ]);
        expect(out.logs.single, 'stub: game.start');
        expect((await loop.snapshot()).scores['red'], 1);
      },
    );

    test('advanceTo moves game time and fires what is due', () async {
      final loop = await GameLoopIsolate.spawn(
        _spec,
        libraryPath: stub,
        clock: GameClock.manual,
      );
      addTearDown(loop.close);
      final out = _Outputs(loop);
      await loop.advanceTo(450);
      expect(out.events.single.type, 'stub.tick');
      expect(out.events.single.tMs, 450);
      expect((await loop.snapshot()).timeMs, 450);
    });

    test('status changes are reported as they happen', () async {
      final loop = await GameLoopIsolate.spawn(
        _spec,
        libraryPath: stub,
        clock: GameClock.manual,
      );
      addTearDown(loop.close);
      final out = _Outputs(loop);
      await loop.input('game.pause', {'reason': 'gm'});
      expect(await loop.input('team_input.press', {'team': 'red'}), isFalse);
      await loop.input('game.resume');
      await loop.input('game.end', {'reason': 'time'});
      expect(out.statuses.map((s) => (s.status, s.paused)), [
        (NodeStatus.running, true),
        (NodeStatus.running, false),
        (NodeStatus.ended, false),
      ]);
      expect(loop.lastSnapshot!.status, NodeStatus.ended);
    });

    test('many isolates run side by side', () async {
      final loops = await Future.wait([
        for (var i = 1; i <= 8; i++)
          GameLoopIsolate.spawn(
            NodeSpec(source: 'x', chunkName: 'x', nodeId: i),
            libraryPath: stub,
            clock: GameClock.manual,
          ),
      ]);
      final outs = [for (final l in loops) _Outputs(l)];
      await Future.wait([for (final l in loops) l.input('game.start')]);
      for (var i = 0; i < loops.length; i++) {
        expect(outs[i].events.single.node, i + 1);
      }
      await Future.wait([for (final l in loops) l.close()]);
    });

    test(
      'a script that does not load gives a halted node, not a failure',
      () async {
        final loop = await GameLoopIsolate.spawn(
          const NodeSpec(source: '', chunkName: '@stub/empty.lua'),
          libraryPath: stub,
          clock: GameClock.manual,
        );
        addTearDown(loop.close);
        expect(loop.loaded, isFalse);
        final s = await loop.snapshot();
        expect(s.status, NodeStatus.halted);
        expect(s.lastError, 'stub: empty script');
      },
    );

    test('a library that does not load fails the spawn', () async {
      await expectLater(
        GameLoopIsolate.spawn(
          _spec,
          libraryPath: '/nonexistent/libatalaia_core.so',
          clock: GameClock.manual,
        ),
        throwsA(
          isA<GameLoopException>().having(
            (e) => e.message,
            'message',
            contains('cannot load the core'),
          ),
        ),
      );
    });

    test('teams the core refuses fail the spawn', () async {
      await expectLater(
        GameLoopIsolate.spawn(
          const NodeSpec(source: 'x', chunkName: 'x', teams: []),
          libraryPath: stub,
          clock: GameClock.manual,
        ),
        throwsA(isA<GameLoopException>()),
      );
    });

    test(
      'after close every call fails, and close can be called again',
      () async {
        final loop = await GameLoopIsolate.spawn(
          _spec,
          libraryPath: stub,
          clock: GameClock.manual,
        );
        final done = Completer<void>();
        loop.outputs.listen(null, onDone: done.complete);
        await loop.close();
        await done.future; // the output stream ends
        await loop.close();
        await expectLater(
          loop.input('game.start'),
          throwsA(isA<GameLoopException>()),
        );
        await expectLater(loop.snapshot(), throwsA(isA<GameLoopException>()));
      },
    );
  });

  group('real-time clock (stub)', () {
    test('inputs wait for a tick; game time starts with game.start', () async {
      final loop = await GameLoopIsolate.spawn(_spec, libraryPath: stub);
      addTearDown(loop.close);
      final out = _Outputs(loop);
      await Future<void>.delayed(const Duration(milliseconds: 150));
      expect((await loop.snapshot()).timeMs, 0, reason: 'no game.start yet');
      expect(out.events, isEmpty);

      final watch = Stopwatch()..start();
      expect(await loop.input('game.start'), isTrue);
      await _until(
        () => out.events.where((e) => e.type == 'stub.tick').length >= 3,
      );
      final s = await loop.snapshot();
      watch.stop();
      // Game time follows the wall clock (within the time the test took).
      expect(s.timeMs, greaterThanOrEqualTo(300));
      expect(s.timeMs, lessThanOrEqualTo(watch.elapsedMilliseconds + 20));
      final ticks = out.events.where((e) => e.type == 'stub.tick').toList();
      for (var i = 1; i < ticks.length; i++) {
        expect(ticks[i].tMs, greaterThan(ticks[i - 1].tMs));
      }
    });

    test('game time stands still while the game is paused', () async {
      final loop = await GameLoopIsolate.spawn(_spec, libraryPath: stub);
      addTearDown(loop.close);
      await loop.input('game.start');
      await Future<void>.delayed(const Duration(milliseconds: 120));
      await loop.input('game.pause', {'reason': 'gm'});
      final atPause = (await loop.snapshot()).timeMs;
      expect(atPause, greaterThan(0));
      await Future<void>.delayed(const Duration(milliseconds: 200));
      expect((await loop.snapshot()).timeMs, atPause);
      await loop.input('game.resume');
      await Future<void>.delayed(const Duration(milliseconds: 100));
      final after = (await loop.snapshot()).timeMs;
      expect(after, greaterThan(atPause));
      expect(
        after,
        lessThan(atPause + 200),
        reason: 'the pause is not counted',
      );
    });

    test('advanceTo is refused: the wall clock drives time', () async {
      final loop = await GameLoopIsolate.spawn(_spec, libraryPath: stub);
      addTearDown(loop.close);
      await expectLater(
        loop.advanceTo(1000),
        throwsA(isA<GameLoopException>()),
      );
    });

    test('inputs queued before close are answered false', () async {
      final loop = await GameLoopIsolate.spawn(
        _spec,
        libraryPath: stub,
        tick: const Duration(seconds: 30), // no tick during the test
      );
      final pending = loop.input('game.start');
      await loop.close();
      expect(await pending, isFalse);
    });
  });

  group('real core', () {
    test('Domination runs in its isolate on the wall clock', () async {
      final loop = await GameLoopIsolate.spawn(
        NodeSpec(
          source: File('../modes/domination/node.lua').readAsStringSync(),
          chunkName: '@domination/node.lua',
          params: const {
            'capture_hold_ms': 100,
            'tick_s': 1,
            'points_per_tick': 5,
          },
        ),
        libraryPath: coreLibraryPath(),
      );
      addTearDown(loop.close);
      final out = _Outputs(loop);
      expect(loop.loaded, isTrue);
      expect(
        await loop.input('game.start', {'preset': 'org.atalaia.domination'}),
        isTrue,
      );
      expect(out.commands.last.args.first, 'neutral');
      expect(
        await loop.input('team_input.hold', {'team': 'blue', 'ms': 150}),
        isTrue,
      );
      final captured = out.events.singleWhere((e) => e.type == 'zone.captured');
      expect(captured.team, 2);
      await _until(
        () =>
            out.commands.last.args.length > 1 &&
            (out.commands.last.args[1]! as Map)['points'] == 5,
      );
      expect((await loop.snapshot()).scores['blue'], greaterThanOrEqualTo(5));
      expect(await loop.input('game.end', {'reason': 'time'}), isTrue);
      expect(loop.lastSnapshot!.status, NodeStatus.ended);
      expect(out.commands.last.args.first, 'final_score');
    });

    test('a script error in a handler is reported, the node runs on', () async {
      final loop = await GameLoopIsolate.spawn(
        const NodeSpec(
          source: 'on("boom", function() error("kaput") end)',
          chunkName: '@boom.lua',
        ),
        libraryPath: coreLibraryPath(),
        clock: GameClock.manual,
      );
      addTearDown(loop.close);
      final out = _Outputs(loop);
      await loop.input('game.start');
      expect(await loop.input('boom'), isTrue);
      final err = out.events.singleWhere((e) => e.type == 'script.error');
      expect(err.data['message'], contains('kaput'));
      expect((await loop.snapshot()).status, NodeStatus.running);
    });
  });
}
