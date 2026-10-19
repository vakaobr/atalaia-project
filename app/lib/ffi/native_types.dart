// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The C structs of the core's public headers (core/include/atalaia/), field
/// for field, as `dart:ffi` structs.
///
/// The same structs are mirrored with ctypes in
/// simulator/atalaia_sim/core.py. Neither copy is trusted on its own: the FFI
/// stub (core/tests/stub.c) reports what the C compiler makes of the real
/// headers (`atalaia_stub_layout`), and test/ffi/layout_test.dart compares
/// every size and offset here with it. `size_t` is [Size] and pointers are
/// pointers, so Dart lays them out per ABI (32-bit armeabi-v7a included).
library;

import 'dart:ffi';

import 'package:ffi/ffi.dart';

/// ATALAIA_EVENT_TYPE_MAX (atalaia/protocol.h): an event type and its NUL.
const int eventTypeMax = 48;

/// ATALAIA_TEAM_MAX (atalaia/event.h): team ids are 1..250, 0 is none.
const int teamMax = 250;

/// ATALAIA_NODE_DEFAULT_MEM_LIMIT: the Full tier's script memory (ADR-P3-1).
const int defaultMemLimit = 256 * 1024;

/// ATALAIA_RF_PAYLOAD_MAX: the largest CBOR payload in one LoRa packet.
const int rfPayloadMax = 200;

/// atalaia_event_t (atalaia/event.h).
final class AtalaiaEvent extends Struct {
  @Uint16()
  external int node;
  @Uint16()
  external int seq;
  @Uint32()
  external int tMs;
  @Uint8()
  external int team;
  @Uint8()
  external int squad;

  /// atalaia_prio_t: a C enum, which is an `int` on every ABI the app runs on.
  @Int()
  external int prio;
  @Array(eventTypeMax)
  external Array<Uint8> type;
}

/// void (*event)(void *user, const atalaia_event_t *ev, const char *data_json)
typedef EventCallbackNative =
    Void Function(Pointer<Void>, Pointer<AtalaiaEvent>, Pointer<Utf8>);

/// void (*command)(void *user, const char *target, const char *method, const char *args_json)
typedef CommandCallbackNative =
    Void Function(Pointer<Void>, Pointer<Utf8>, Pointer<Utf8>, Pointer<Utf8>);

/// void (*log)(void *user, const char *message)
typedef LogCallbackNative = Void Function(Pointer<Void>, Pointer<Utf8>);

/// void (*field_state)(void *user, const char *key, const char *value_json)
typedef FieldStateCallbackNative =
    Void Function(Pointer<Void>, Pointer<Utf8>, Pointer<Utf8>);

/// void *(*atalaia_alloc_fn)(void *ud, void *ptr, size_t old_size, size_t new_size)
typedef AllocNative =
    Pointer<Void> Function(Pointer<Void>, Pointer<Void>, Size, Size);

/// atalaia_node_callbacks_t (atalaia/node.h).
final class NodeCallbacks extends Struct {
  external Pointer<NativeFunction<EventCallbackNative>> event;
  external Pointer<NativeFunction<CommandCallbackNative>> command;
  external Pointer<NativeFunction<LogCallbackNative>> log;
  external Pointer<NativeFunction<FieldStateCallbackNative>> fieldState;
  external Pointer<Void> user;
}

/// char *(*nodes)(void *user, const char *role): a malloc'd JSON array the core frees.
typedef FieldNodesNative = Pointer<Utf8> Function(Pointer<Void>, Pointer<Utf8>);

/// const char *(*owner)(void *user, uint16_t node_id): copied by the core at once.
typedef FieldOwnerNative = Pointer<Utf8> Function(Pointer<Void>, Uint16);

/// bool (*send)(void *user, uint16_t node_id, const char *cmd, const char *params_json)
typedef FieldSendNative =
    Bool Function(Pointer<Void>, Uint16, Pointer<Utf8>, Pointer<Utf8>);

/// atalaia_field_ops_t (atalaia/field_ops.h).
final class FieldOpsStruct extends Struct {
  external Pointer<NativeFunction<FieldNodesNative>> nodes;
  external Pointer<NativeFunction<FieldOwnerNative>> owner;
  external Pointer<NativeFunction<FieldSendNative>> send;
}

/// atalaia_node_config_t (atalaia/node.h).
final class NodeConfig extends Struct {
  @Uint16()
  external int nodeId;
  @Uint32()
  external int gameSeed;
  @Size()
  external int memLimit;
  @Uint32()
  external int instrLimit;
  external NodeCallbacks callbacks;
  external Pointer<NativeFunction<AllocNative>> alloc;
  external Pointer<Void> allocUd;
  external Pointer<FieldOpsStruct> fieldOps;
}

/// atalaia_score_t (atalaia/score.h): index 0 (no team) is unused.
final class ScoreStruct extends Struct {
  @Array(teamMax + 1)
  external Array<Uint32> gained;
  @Array(teamMax + 1)
  external Array<Uint32> lost;
}

/// atalaia_tpl_scope_t (atalaia/screen_template.h).
final class TemplateScope extends Struct {
  external Pointer<Utf8> data;
  external Pointer<Utf8> params;
}
