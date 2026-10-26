// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Every binding against the FFI stub (core/tests/stub.c), whose behaviour is
// fixed, so these tests check the bridge itself: strings both ways, the
// callbacks, field operations, the score struct and the node's life cycle.

import 'dart:io';

import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/ffi/callbacks.dart';
import 'package:atalaia_app/ffi/core_node.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';

class _Recorder {
  final events = <EmittedEvent>[];
  final commands = <NodeCommand>[];
  final logs = <String>[];
  final fieldState = <(String, String)>[];

  NodeHandlers get handlers => NodeHandlers(
    onEvent: events.add,
    onCommand: commands.add,
    onLog: logs.add,
    onFieldState: (k, v) => fieldState.add((k, v)),
  );
}

class _Field implements FieldOperations {
  final sent = <(int, String, Map<String, Object?>)>[];
  final roles = <String?>[];

  @override
  List<Map<String, Object?>> nodes(String? role) {
    roles.add(role);
    return [
      {'id': 1, 'name': 'alpha', 'role': role, 'owner': 'red'},
    ];
  }

  @override
  String? owner(int nodeId) => nodeId == 1 ? 'red' : null;

  @override
  bool send(int nodeId, String cmd, Map<String, Object?> params) {
    sent.add((nodeId, cmd, params));
    return true;
  }
}

const _spec = NodeSpec(
  source: '-- any script',
  chunkName: '@stub/node.lua',
  nodeId: 7,
  gameSeed: 42,
  teams: ['red', 'blue'],
  params: {'fuse_s': 60},
);

void main() {
  late AtalaiaCore stub;

  setUpAll(() => stub = AtalaiaCore.open(stubLibraryPath()));

  test('the library path comes from the argument, then ATALAIA_CORE_LIB', () {
    expect(
      resolveCoreLibrary('/x/libatalaia_core.so'),
      '/x/libatalaia_core.so',
    );
    expect(
      defaultCoreLibraryName(),
      Platform.isMacOS ? 'libatalaia_core.dylib' : 'libatalaia_core.so',
    );
    expect(stub.path, stubLibraryPath());
    expect(stub.version, 'stub');
  });

  test('a node is created, loaded and running', () {
    final r = _Recorder();
    final node = CoreNode.create(stub, _spec, handlers: r.handlers);
    addTearDown(node.close);
    expect(node.loaded, isTrue);
    expect(node.status, NodeStatus.running);
    expect(node.statusName, 'running');
    expect(node.paused, isFalse);
    expect(node.timeMs, 0);
    expect(node.lastError, '');
    expect(node.memUsed, 4096);
    expect(node.teamId('blue'), 2);
    expect(node.teamId('green'), 0);
    expect(node.teamName(1), 'red');
    expect(node.teamName(3), isNull);
    expect(r.events, isEmpty);
  });

  test('input reaches C and every callback comes back with its data', () {
    final r = _Recorder();
    final node = CoreNode.create(stub, _spec, handlers: r.handlers);
    addTearDown(node.close);
    expect(
      node.input('team_input.press', {'team': 'red', 'note': 'ção'}),
      isTrue,
    );
    expect(r.events, hasLength(1));
    final ev = r.events.single;
    expect(ev.node, 7);
    expect(ev.seq, 0);
    expect(ev.tMs, 0);
    expect(ev.team, 1);
    expect(ev.squad, 0);
    expect(ev.prio, 1);
    expect(ev.prioName, 'normal');
    expect(ev.type, 'team_input.press');
    expect(ev.data, {'team': 'red', 'note': 'ção'});
    expect(r.commands.single.target, 'ui');
    expect(r.commands.single.method, 'screen');
    expect(r.commands.single.args, [
      'stub',
      {'inputs': 1},
    ]);
    expect(r.logs, ['stub: team_input.press']);
    expect(node.score('red'), 1);
    expect(node.gained('red'), 1);
    expect(node.lost('red'), 0);
    expect(node.memUsed, 4096 + 64);
    expect(node.callbackErrors, isEmpty);
  });

  test('input without data sends an empty object; non-objects are refused', () {
    final r = _Recorder();
    final node = CoreNode.create(stub, _spec, handlers: r.handlers);
    addTearDown(node.close);
    expect(node.input('game.start'), isTrue);
    expect(r.events.single.dataJson, '{}');
    expect(node.inputJson('keypad.key', '[1]'), isFalse);
    expect(r.events, hasLength(1));
  });

  test('pause, resume and end change the state the bindings read', () {
    final node = CoreNode.create(stub, _spec);
    addTearDown(node.close);
    expect(node.input('game.pause', {'reason': 'gm'}), isTrue);
    expect(node.paused, isTrue);
    expect(node.input('team_input.press', {'team': 'red'}), isFalse);
    expect(node.input('game.resume'), isTrue);
    expect(node.paused, isFalse);
    expect(node.input('game.end', {'reason': 'time'}), isTrue);
    expect(node.status, NodeStatus.ended);
    expect(node.input('team_input.press', {'team': 'red'}), isFalse);
  });

  test(
    'advance moves time forward only, with a tick event per 100 ms crossed',
    () {
      final r = _Recorder();
      final node = CoreNode.create(stub, _spec, handlers: r.handlers);
      addTearDown(node.close);
      node.advance(50);
      expect(r.events, isEmpty);
      node.advance(250);
      expect(node.timeMs, 250);
      expect(r.events.single.type, 'stub.tick');
      expect(r.events.single.tMs, 250);
      node.advance(100); // backwards: ignored
      expect(node.timeMs, 250);
      node.advance(0x100000000 + 300); // wraps to uint32_t, as in C
      expect(node.timeMs, 300);
    },
  );

  test('an empty script halts the node, with the reason', () {
    final node = CoreNode.create(
      stub,
      const NodeSpec(source: '', chunkName: '@stub/empty.lua'),
    );
    addTearDown(node.close);
    expect(node.loaded, isFalse);
    expect(node.status, NodeStatus.halted);
    expect(node.lastError, 'stub: empty script');
  });

  test('teams and parameters the core refuses throw NodeSetupException', () {
    expect(
      () => CoreNode.create(
        stub,
        const NodeSpec(source: 'x', chunkName: 'x', teams: []),
      ),
      throwsA(isA<NodeSetupException>()),
    );
    expect(
      () => CoreNode.create(
        stub,
        NodeSpec(source: 'x', chunkName: 'x', teams: ['a' * 24]),
      ),
      throwsA(isA<NodeSetupException>()),
    );
  });

  test('field operations answer the core, and field state comes back', () {
    final r = _Recorder();
    final field = _Field();
    final node = CoreNode.create(
      stub,
      _spec,
      handlers: r.handlers,
      fieldOps: field,
    );
    addTearDown(node.close);
    expect(node.input('stub.field'), isTrue);
    expect(field.roles, ['zone']);
    expect(r.logs, [
      'stub: stub.field',
      'nodes: [{"id":1,"name":"alpha","role":"zone","owner":"red"}]',
      'owner: red',
      'send: true',
    ]);
    final (nodeId, cmd, params) = field.sent.single;
    expect((nodeId, cmd), (1, 'message'));
    expect(params, {'text': 'hello'});
    expect(r.fieldState, [('probe', '{"n":1}')]);
    expect(node.callbackErrors, isEmpty);
  });

  test('a node without field operations gives the core none', () {
    final r = _Recorder();
    final node = CoreNode.create(stub, _spec, handlers: r.handlers);
    addTearDown(node.close);
    node.input('stub.field');
    expect(r.logs.last, 'stub: no field ops');
  });

  test('a handler that throws does not cross into C; the error is kept', () {
    final node = CoreNode.create(
      stub,
      _spec,
      handlers: NodeHandlers(onEvent: (_) => throw StateError('boom')),
    );
    addTearDown(node.close);
    expect(node.input('team_input.press', {'team': 'red'}), isTrue);
    expect(node.callbackErrors.single, isA<StateError>());
  });

  test('a closed node refuses calls, and closing twice is harmless', () {
    final node = CoreNode.create(stub, _spec);
    node.close();
    node.close();
    expect(() => node.input('game.start'), throwsStateError);
    expect(() => node.status, throwsStateError);
  });

  test('many nodes live side by side, each with its own callbacks', () {
    final recorders = List.generate(20, (_) => _Recorder());
    final nodes = [
      for (var i = 0; i < 20; i++)
        CoreNode.create(
          stub,
          NodeSpec(source: 'x', chunkName: 'x', nodeId: i + 1),
          handlers: recorders[i].handlers,
        ),
    ];
    for (var i = 0; i < 20; i++) {
      nodes[i].input('game.start', {'n': i});
    }
    for (var i = 0; i < 20; i++) {
      expect(recorders[i].events.single.node, i + 1);
      expect(recorders[i].events.single.data, {'n': i});
      nodes[i].close();
    }
  });
}
