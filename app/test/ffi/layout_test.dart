// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The Dart structs in lib/ffi/native_types.dart against the C compiler's
// layout of the real headers, which the FFI stub reports
// (atalaia_stub_layout in core/tests/stub.c). simulator/tests/test_ffi_layout.py
// checks the simulator's ctypes structs against the same report.

import 'dart:convert';
import 'dart:ffi';

import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/ffi/native_types.dart';
import 'package:ffi/ffi.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';

final _one = Pointer<Never>.fromAddress(1);

void main() {
  late Map<String, dynamic> layout;

  setUpAll(() {
    final stub = AtalaiaCore.open(stubLibraryPath());
    layout =
        jsonDecode(stub.bindings.stubLayout().toDartString())
            as Map<String, dynamic>;
  });

  /// Compares sizeof and every field offset of [cName] with the Dart struct
  /// at [raw] ([size] bytes): each setter writes a non-zero value into one
  /// field of a zeroed struct, and its offset is the first non-zero byte.
  void check(
    String cName,
    int size,
    Pointer<NativeType> raw,
    Map<String, void Function()> fields,
  ) {
    final c = layout[cName] as Map<String, dynamic>;
    expect(size, c['size'], reason: 'sizeof($cName)');
    final cFields = c['fields'] as Map<String, dynamic>;
    expect(fields.keys.toSet(), cFields.keys.toSet(), reason: '$cName fields');
    final bytes = raw.cast<Uint8>().asTypedList(size);
    fields.forEach((name, set) {
      bytes.fillRange(0, size, 0);
      set();
      expect(
        bytes.indexWhere((b) => b != 0),
        cFields[name],
        reason: 'offsetof($cName, $name)',
      );
    });
    calloc.free(raw);
  }

  test('atalaia_event_t', () {
    final p = calloc<AtalaiaEvent>();
    check('atalaia_event_t', sizeOf<AtalaiaEvent>(), p, {
      'node': () => p.ref.node = 1,
      'seq': () => p.ref.seq = 1,
      't_ms': () => p.ref.tMs = 1,
      'team': () => p.ref.team = 1,
      'squad': () => p.ref.squad = 1,
      'prio': () => p.ref.prio = 1,
      'type': () => p.ref.type[0] = 1,
    });
  });

  test('atalaia_node_callbacks_t', () {
    final p = calloc<NodeCallbacks>();
    check('atalaia_node_callbacks_t', sizeOf<NodeCallbacks>(), p, {
      'event': () => p.ref.event = _one.cast(),
      'command': () => p.ref.command = _one.cast(),
      'log': () => p.ref.log = _one.cast(),
      'field_state': () => p.ref.fieldState = _one.cast(),
      'user': () => p.ref.user = _one.cast(),
    });
  });

  test('atalaia_field_ops_t', () {
    final p = calloc<FieldOpsStruct>();
    check('atalaia_field_ops_t', sizeOf<FieldOpsStruct>(), p, {
      'nodes': () => p.ref.nodes = _one.cast(),
      'owner': () => p.ref.owner = _one.cast(),
      'send': () => p.ref.send = _one.cast(),
    });
  });

  test('atalaia_node_config_t', () {
    final p = calloc<NodeConfig>();
    check('atalaia_node_config_t', sizeOf<NodeConfig>(), p, {
      'node_id': () => p.ref.nodeId = 1,
      'game_seed': () => p.ref.gameSeed = 1,
      'mem_limit': () => p.ref.memLimit = 1,
      'instr_limit': () => p.ref.instrLimit = 1,
      'callbacks': () => p.ref.callbacks.event = _one.cast(),
      'alloc': () => p.ref.alloc = _one.cast(),
      'alloc_ud': () => p.ref.allocUd = _one.cast(),
      'field_ops': () => p.ref.fieldOps = _one.cast(),
    });
  });

  test('atalaia_score_t', () {
    final p = calloc<ScoreStruct>();
    check('atalaia_score_t', sizeOf<ScoreStruct>(), p, {
      'gained': () => p.ref.gained[0] = 1,
      'lost': () => p.ref.lost[0] = 1,
    });
  });

  test('atalaia_tpl_scope_t', () {
    final p = calloc<TemplateScope>();
    check('atalaia_tpl_scope_t', sizeOf<TemplateScope>(), p, {
      'data': () => p.ref.data = _one.cast(),
      'params': () => p.ref.params = _one.cast(),
    });
  });

  test('the stub reports every struct the bindings mirror', () {
    expect(layout.keys.toSet(), {
      'atalaia_event_t',
      'atalaia_node_callbacks_t',
      'atalaia_field_ops_t',
      'atalaia_node_config_t',
      'atalaia_score_t',
      'atalaia_tpl_scope_t',
    });
  });
}
