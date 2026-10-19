// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The node runner the conditional import picks (node_runner.dart): the FFI
// one where Dart has dart:ffi, and the one that runs nothing on the web.

import 'package:atalaia_app/core/node_runner.dart';
import 'package:atalaia_app/core/node_runner_android.dart' show FfiNodeRunner;
import 'package:atalaia_app/core/node_runner_stub.dart' as web;
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';

void main() {
  test(
    'with dart:ffi (Linux here, Android in the app) the FFI runner is used',
    () async {
      final runner = createNodeRunner(libraryPath: stubLibraryPath());
      expect(runner, isA<FfiNodeRunner>());
      expect(runner.supported, isTrue);
      final node = await runner.start(
        const NodeSpec(source: 'x', chunkName: 'x'),
        clock: GameClock.manual,
      );
      addTearDown(node.close);
      expect(node.loaded, isTrue);
      expect(await node.input('game.start'), isTrue);
      expect((await node.snapshot()).status, NodeStatus.running);
    },
  );

  test('without a core the runner is unsupported and starts nothing', () async {
    final runner = web.createNodeRunner();
    expect(runner.supported, isFalse);
    await expectLater(
      runner.start(const NodeSpec(source: 'x', chunkName: 'x')),
      throwsUnsupportedError,
    );
  });
}
