// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The core's callbacks (atalaia_node_callbacks_t, atalaia_field_ops_t) as
/// Dart closures.
///
/// They are `NativeCallable.isolateLocal`, not `.listener` as ADR-P3-1 first
/// said (decision PC1 in docs/review/decisions-to-review.md). The core calls
/// them synchronously, on the thread of the isolate that called
/// `atalaia_node_input` or `_advance`, and its pointer arguments (the event
/// struct, the JSON strings) only live until the callback returns. A
/// `.listener` runs later, after those pointers are gone, cannot return a
/// value (field operations must) and can reorder output against the reply
/// to the call that caused it. An isolate-local callable copies everything
/// into Dart objects while the pointers are valid, keeps the core's order,
/// and still never runs on the UI isolate: the game loop isolate owns the
/// node and forwards what it gets through its SendPort.
library;

import 'dart:convert';
import 'dart:ffi';
import 'dart:io';

import 'package:ffi/ffi.dart';

import '../core/node_types.dart';
import 'bindings.dart';
import 'native_types.dart';

/// What a controller node's field script may ask the host (ADR-P2-14): the
/// field's nodes, who owns one, and sending one a command.
abstract interface class FieldOperations {
  /// Node descriptors (JSON objects), all of them or those with [role].
  List<Map<String, Object?>> nodes(String? role);

  /// The team that owns [nodeId], or null.
  String? owner(int nodeId);

  /// Queues a command for [nodeId]; true when it was accepted.
  bool send(int nodeId, String cmd, Map<String, Object?> params);
}

/// Receives what a node gives its host. Handlers run inside the core's call:
/// they must not drive the same node (the core is not re-entrant).
final class NodeHandlers {
  const NodeHandlers({
    this.onEvent,
    this.onCommand,
    this.onLog,
    this.onFieldState,
  });

  final void Function(EmittedEvent event)? onEvent;
  final void Function(NodeCommand command)? onCommand;
  final void Function(String line)? onLog;

  /// A controller node wrote state.field: [valueJson] is JSON.
  final void Function(String key, String valueJson)? onFieldState;
}

/// The native callables for one node, and the C structs that point to them.
/// Create, use and [close] on one isolate.
final class NativeCallbacks {
  NativeCallbacks(
    this._handlers, {
    FieldOperations? fieldOps,
    int Function()? clock,
  }) : _fieldOps = fieldOps,
       _clock = clock ?? (() => 0) {
    _event = NativeCallable<EventCallbackNative>.isolateLocal(_onEvent);
    _command = NativeCallable<CommandCallbackNative>.isolateLocal(_onCommand);
    _log = NativeCallable<LogCallbackNative>.isolateLocal(_onLog);
    if (fieldOps != null) {
      _fieldState = NativeCallable<FieldStateCallbackNative>.isolateLocal(
        _onFieldState,
      );
      _nodes = NativeCallable<FieldNodesNative>.isolateLocal(_onNodes);
      _owner = NativeCallable<FieldOwnerNative>.isolateLocal(_onOwner);
      _send = NativeCallable<FieldSendNative>.isolateLocal(
        _onSend,
        exceptionalReturn: false,
      );
      _ops = calloc<FieldOpsStruct>();
      _ops!.ref
        ..nodes = _nodes!.nativeFunction
        ..owner = _owner!.nativeFunction
        ..send = _send!.nativeFunction;
    }
  }

  final NodeHandlers _handlers;
  final FieldOperations? _fieldOps;
  final int Function() _clock;

  late final NativeCallable<EventCallbackNative> _event;
  late final NativeCallable<CommandCallbackNative> _command;
  late final NativeCallable<LogCallbackNative> _log;
  NativeCallable<FieldStateCallbackNative>? _fieldState;
  NativeCallable<FieldNodesNative>? _nodes;
  NativeCallable<FieldOwnerNative>? _owner;
  NativeCallable<FieldSendNative>? _send;
  Pointer<FieldOpsStruct>? _ops;

  /// The last owner() answer: the core copies it at once, so it lives until
  /// the next call.
  Pointer<Utf8> _ownerText = nullptr;
  bool _closed = false;

  /// Exceptions thrown by the handlers. They cannot cross into C, so they
  /// are kept here; a host checks this after each call into the node.
  final List<Object> errors = [];

  /// Points [config]'s callbacks (and field operations, for a controller
  /// node) at these callables.
  void fill(Pointer<NodeConfig> config) {
    config.ref.callbacks
      ..event = _event.nativeFunction
      ..command = _command.nativeFunction
      ..log = _log.nativeFunction
      ..fieldState = _fieldState?.nativeFunction ?? nullptr
      ..user = nullptr;
    config.ref.fieldOps = _ops ?? nullptr;
  }

  void _guard(void Function() body) {
    try {
      body();
    } catch (e) {
      errors.add(e);
    }
  }

  void _onEvent(
    Pointer<Void> user,
    Pointer<AtalaiaEvent> ev,
    Pointer<Utf8> dataJson,
  ) => _guard(() {
    final e = ev.ref;
    final event = EmittedEvent(
      node: e.node,
      seq: e.seq,
      tMs: e.tMs,
      team: e.team,
      squad: e.squad,
      prio: e.prio,
      type: fixedString(e.type, eventTypeMax),
      dataJson: dataJson == nullptr ? '{}' : dataJson.toDartString(),
    );
    _handlers.onEvent?.call(event);
  });

  void _onCommand(
    Pointer<Void> user,
    Pointer<Utf8> target,
    Pointer<Utf8> method,
    Pointer<Utf8> args,
  ) => _guard(() {
    final command = NodeCommand(
      tMs: _clock(),
      target: target.toDartString(),
      method: method.toDartString(),
      argsJson: args == nullptr ? '[]' : args.toDartString(),
    );
    _handlers.onCommand?.call(command);
  });

  void _onLog(Pointer<Void> user, Pointer<Utf8> message) =>
      _guard(() => _handlers.onLog?.call(_text(message)));

  void _onFieldState(
    Pointer<Void> user,
    Pointer<Utf8> key,
    Pointer<Utf8> valueJson,
  ) => _guard(
    () => _handlers.onFieldState?.call(key.toDartString(), _text(valueJson)),
  );

  Pointer<Utf8> _onNodes(Pointer<Void> user, Pointer<Utf8> role) {
    try {
      final list = _fieldOps!.nodes(role == nullptr ? null : _text(role));
      return _mallocText(jsonEncode(list));
    } catch (e) {
      errors.add(e);
      return nullptr; // the core reads NULL as an empty list
    }
  }

  Pointer<Utf8> _onOwner(Pointer<Void> user, int nodeId) {
    try {
      final team = _fieldOps!.owner(nodeId);
      if (_ownerText != nullptr) calloc.free(_ownerText);
      _ownerText = team == null
          ? nullptr
          : team.toNativeUtf8(allocator: calloc);
      return _ownerText;
    } catch (e) {
      errors.add(e);
      return nullptr;
    }
  }

  bool _onSend(
    Pointer<Void> user,
    int nodeId,
    Pointer<Utf8> cmd,
    Pointer<Utf8> params,
  ) {
    try {
      final args = params == nullptr
          ? const <String, Object?>{}
          : jsonDecode(_text(params)) as Map<String, Object?>;
      return _fieldOps!.send(nodeId, cmd.toDartString(), args);
    } catch (e) {
      errors.add(e);
      return false;
    }
  }

  /// Frees the callables and the structs. The node that used them must be
  /// destroyed first.
  void close() {
    if (_closed) return;
    _closed = true;
    _event.close();
    _command.close();
    _log.close();
    _fieldState?.close();
    _nodes?.close();
    _owner?.close();
    _send?.close();
    if (_ops != null) calloc.free(_ops!);
    if (_ownerText != nullptr) calloc.free(_ownerText);
  }
}

String _text(Pointer<Utf8> p) => p == nullptr ? '' : _decode(p);

/// UTF-8 from C, without throwing on a malformed byte (a script can print anything).
String _decode(Pointer<Utf8> p) {
  final length = p.length;
  return utf8.decode(p.cast<Uint8>().asTypedList(length), allowMalformed: true);
}

/// A string the core will free() itself: allocated with the C library's
/// malloc, which package:ffi's [malloc] is on Android, Linux and macOS. On
/// Windows that allocator is not the C runtime's, so no list is returned
/// there (the core reads NULL as an empty list); the app runs the core on
/// Android only.
Pointer<Utf8> _mallocText(String text) {
  if (Platform.isWindows) return nullptr;
  return text.toNativeUtf8(allocator: malloc);
}
