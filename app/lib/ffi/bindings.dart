// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// `dart:ffi` bindings to the shared C core (ADR-P3-1), mirroring the ctypes
/// wrapper in simulator/atalaia_sim/core.py.
///
/// [AtalaiaBindings] is the raw C API: one field per function, looked up
/// when first used, so a library that lacks some functions (the FFI stub has
/// only node.h) loads fine. [AtalaiaCore] adds the helpers that do not touch
/// a node: the version, screen templates, player tags and the event codec.
/// Nodes are driven through `CoreNode` (core_node.dart), and in the app only
/// from the game loop isolate (lib/core/game_loop_isolate.dart).
library;

import 'dart:convert';
import 'dart:ffi';
import 'dart:io';
import 'dart:typed_data';

import 'package:ffi/ffi.dart';

import 'native_types.dart';

/// An `atalaia_node_t *`: only the core looks inside.
final class AtalaiaNode extends Opaque {}

/// The library file the platform's loader looks for when no path is given:
/// on Android the APK's `lib/<abi>/libatalaia_core.so` (ADR-P3-1).
String defaultCoreLibraryName() {
  if (Platform.isWindows) return 'atalaia_core.dll';
  if (Platform.isMacOS || Platform.isIOS) return 'libatalaia_core.dylib';
  return 'libatalaia_core.so';
}

/// Which core library to open: [explicit], then `$ATALAIA_CORE_LIB` (tests and
/// desktop runs, as the simulator does), then [defaultCoreLibraryName].
String resolveCoreLibrary([String? explicit]) {
  if (explicit != null && explicit.isNotEmpty) return explicit;
  final env = Platform.environment['ATALAIA_CORE_LIB'];
  if (env != null && env.isNotEmpty) return env;
  return defaultCoreLibraryName();
}

/// The C functions, typed. Names follow the C names without the `atalaia_`
/// prefix. Functions that never call back into Dart are leaf calls.
class AtalaiaBindings {
  AtalaiaBindings(this.library);

  final DynamicLibrary library;

  late final version = library
      .lookupFunction<Pointer<Utf8> Function(), Pointer<Utf8> Function()>(
        'atalaia_version',
        isLeaf: true,
      );

  late final nodeCreate = library
      .lookupFunction<
        Pointer<AtalaiaNode> Function(Pointer<NodeConfig>),
        Pointer<AtalaiaNode> Function(Pointer<NodeConfig>)
      >('atalaia_node_create', isLeaf: true);

  late final nodeDestroy = library
      .lookupFunction<
        Void Function(Pointer<AtalaiaNode>),
        void Function(Pointer<AtalaiaNode>)
      >('atalaia_node_destroy', isLeaf: true);

  late final nodeSetTeams = library
      .lookupFunction<
        Bool Function(Pointer<AtalaiaNode>, Pointer<Pointer<Utf8>>, Size),
        bool Function(Pointer<AtalaiaNode>, Pointer<Pointer<Utf8>>, int)
      >('atalaia_node_set_teams', isLeaf: true);

  late final nodeSetParams = library
      .lookupFunction<
        Bool Function(Pointer<AtalaiaNode>, Pointer<Utf8>),
        bool Function(Pointer<AtalaiaNode>, Pointer<Utf8>)
      >('atalaia_node_set_params', isLeaf: true);

  /// Runs the script's top level, which may emit events and commands: not a leaf call.
  late final nodeLoad = library
      .lookupFunction<
        Bool Function(Pointer<AtalaiaNode>, Pointer<Utf8>, Size, Pointer<Utf8>),
        bool Function(Pointer<AtalaiaNode>, Pointer<Utf8>, int, Pointer<Utf8>)
      >('atalaia_node_load');

  late final nodeInput = library
      .lookupFunction<
        Bool Function(Pointer<AtalaiaNode>, Pointer<Utf8>, Pointer<Utf8>),
        bool Function(Pointer<AtalaiaNode>, Pointer<Utf8>, Pointer<Utf8>)
      >('atalaia_node_input');

  late final nodeAdvance = library
      .lookupFunction<
        Void Function(Pointer<AtalaiaNode>, Uint32),
        void Function(Pointer<AtalaiaNode>, int)
      >('atalaia_node_advance');

  late final nodeStatus = library
      .lookupFunction<
        Int Function(Pointer<AtalaiaNode>),
        int Function(Pointer<AtalaiaNode>)
      >('atalaia_node_status', isLeaf: true);

  late final nodeStatusName = library
      .lookupFunction<Pointer<Utf8> Function(Int), Pointer<Utf8> Function(int)>(
        'atalaia_node_status_name',
        isLeaf: true,
      );

  late final nodePaused = library
      .lookupFunction<
        Bool Function(Pointer<AtalaiaNode>),
        bool Function(Pointer<AtalaiaNode>)
      >('atalaia_node_paused', isLeaf: true);

  late final nodeTime = library
      .lookupFunction<
        Uint32 Function(Pointer<AtalaiaNode>),
        int Function(Pointer<AtalaiaNode>)
      >('atalaia_node_time', isLeaf: true);

  late final nodeLastError = library
      .lookupFunction<
        Pointer<Utf8> Function(Pointer<AtalaiaNode>),
        Pointer<Utf8> Function(Pointer<AtalaiaNode>)
      >('atalaia_node_last_error', isLeaf: true);

  late final nodeMemUsed = library
      .lookupFunction<
        Size Function(Pointer<AtalaiaNode>),
        int Function(Pointer<AtalaiaNode>)
      >('atalaia_node_mem_used', isLeaf: true);

  late final nodeScore = library
      .lookupFunction<
        Pointer<ScoreStruct> Function(Pointer<AtalaiaNode>),
        Pointer<ScoreStruct> Function(Pointer<AtalaiaNode>)
      >('atalaia_node_score', isLeaf: true);

  late final nodeTeamId = library
      .lookupFunction<
        Uint8 Function(Pointer<AtalaiaNode>, Pointer<Utf8>),
        int Function(Pointer<AtalaiaNode>, Pointer<Utf8>)
      >('atalaia_node_team_id', isLeaf: true);

  late final nodeTeamName = library
      .lookupFunction<
        Pointer<Utf8> Function(Pointer<AtalaiaNode>, Uint8),
        Pointer<Utf8> Function(Pointer<AtalaiaNode>, int)
      >('atalaia_node_team_name', isLeaf: true);

  late final scoreNet = library
      .lookupFunction<
        Int64 Function(Pointer<ScoreStruct>, Uint8),
        int Function(Pointer<ScoreStruct>, int)
      >('atalaia_score_net', isLeaf: true);

  late final tagEventJson = library
      .lookupFunction<
        Size Function(
          Pointer<Uint8>,
          Size,
          Pointer<Uint8>,
          Size,
          Uint16,
          Pointer<Uint8>,
          Pointer<Pointer<Utf8>>,
          Size,
          Pointer<Utf8>,
          Size,
        ),
        int Function(
          Pointer<Uint8>,
          int,
          Pointer<Uint8>,
          int,
          int,
          Pointer<Uint8>,
          Pointer<Pointer<Utf8>>,
          int,
          Pointer<Utf8>,
          int,
        )
      >('atalaia_tag_event_json', isLeaf: true);

  late final tplSizeof = library
      .lookupFunction<Size Function(), int Function()>(
        'atalaia_tpl_sizeof',
        isLeaf: true,
      );

  late final tplParse = library
      .lookupFunction<
        Bool Function(Pointer<Void>, Pointer<Utf8>, Size, Pointer<Utf8>, Size),
        bool Function(Pointer<Void>, Pointer<Utf8>, int, Pointer<Utf8>, int)
      >('atalaia_tpl_parse', isLeaf: true);

  late final tplText = library
      .lookupFunction<
        Size Function(
          Pointer<Utf8>,
          Pointer<TemplateScope>,
          Pointer<Utf8>,
          Size,
        ),
        int Function(Pointer<Utf8>, Pointer<TemplateScope>, Pointer<Utf8>, int)
      >('atalaia_tpl_text', isLeaf: true);

  late final tplTruthy = library
      .lookupFunction<
        Bool Function(Pointer<Utf8>, Pointer<TemplateScope>),
        bool Function(Pointer<Utf8>, Pointer<TemplateScope>)
      >('atalaia_tpl_truthy', isLeaf: true);

  late final tplFraction = library
      .lookupFunction<
        Double Function(Pointer<Utf8>, Pointer<TemplateScope>),
        double Function(Pointer<Utf8>, Pointer<TemplateScope>)
      >('atalaia_tpl_fraction', isLeaf: true);

  late final tplColor = library
      .lookupFunction<
        Bool Function(Pointer<Utf8>, Pointer<Uint32>),
        bool Function(Pointer<Utf8>, Pointer<Uint32>)
      >('atalaia_tpl_color', isLeaf: true);

  late final tplExprOk = library
      .lookupFunction<
        Bool Function(Pointer<Utf8>, Size, Pointer<Utf8>, Size),
        bool Function(Pointer<Utf8>, int, Pointer<Utf8>, int)
      >('atalaia_tpl_expr_ok', isLeaf: true);

  late final eventEncode = library
      .lookupFunction<
        Size Function(
          Pointer<AtalaiaEvent>,
          Pointer<Utf8>,
          Pointer<Uint8>,
          Size,
          Pointer<Pointer<Utf8>>,
        ),
        int Function(
          Pointer<AtalaiaEvent>,
          Pointer<Utf8>,
          Pointer<Uint8>,
          int,
          Pointer<Pointer<Utf8>>,
        )
      >('atalaia_event_encode', isLeaf: true);

  /// Only in the FFI stub (core/tests/stub.c): the C structs' layout as JSON.
  late final stubLayout = library
      .lookupFunction<Pointer<Utf8> Function(), Pointer<Utf8> Function()>(
        'atalaia_stub_layout',
        isLeaf: true,
      );
}

/// An event as the core's codec encodes it for the radio (atalaia/codec.h):
/// the CBOR payload, or why it cannot be encoded.
final class EncodedEvent {
  const EncodedEvent(this.bytes, [this.error]);

  /// Null when the codec refused the event.
  final Uint8List? bytes;
  final String? error;

  int get size => bytes?.length ?? 0;
}

/// The loaded core, with the helpers that need no node.
class AtalaiaCore {
  AtalaiaCore._(this.path, this.bindings);

  /// Opens the core at [path] (see [resolveCoreLibrary]).
  factory AtalaiaCore.open([String? path]) {
    final resolved = resolveCoreLibrary(path);
    return AtalaiaCore._(
      resolved,
      AtalaiaBindings(DynamicLibrary.open(resolved)),
    );
  }

  final String path;
  final AtalaiaBindings bindings;

  /// The core's version, e.g. "0.2.0" ("stub" for the FFI stub).
  String get version => bindings.version().toDartString();

  /// Parses a screen template with the core's parser, the one the Field Box
  /// renders with; returns why it is refused, or null.
  String? checkScreen(String source) {
    final src = utf8.encode(source);
    final tpl = calloc<Uint8>(bindings.tplSizeof());
    final err = calloc<Uint8>(160);
    final text = _nativeBytes(src);
    try {
      final ok = bindings.tplParse(
        tpl.cast(),
        text.cast(),
        src.length,
        err.cast(),
        160,
      );
      if (ok) return null;
      final n = err.asTypedList(160).indexOf(0);
      return utf8.decode(
        err.asTypedList(n < 0 ? 159 : n),
        allowMalformed: true,
      );
    } finally {
      calloc
        ..free(tpl)
        ..free(err)
        ..free(text);
    }
  }

  /// A template text with its {expressions} filled in, as the renderers do it.
  String screenText(
    String text,
    Map<String, Object?> data,
    Map<String, Object?> params,
  ) {
    const cap = 160; // ATALAIA_TPL_TEXT_MAX
    final out = calloc<Uint8>(cap);
    try {
      _withScope(text, data, params, (t, scope) {
        bindings.tplText(t, scope, out.cast(), cap);
      });
      final n = out.asTypedList(cap).indexOf(0);
      return utf8.decode(out.asTypedList(n), allowMalformed: true);
    } finally {
      calloc.free(out);
    }
  }

  /// A visible: property's truth (atalaia_tpl_truthy).
  bool screenTruthy(
    String? value,
    Map<String, Object?> data,
    Map<String, Object?> params,
  ) {
    var r = false;
    _withScope(value, data, params, (v, scope) {
      r = bindings.tplTruthy(v, scope);
    });
    return r;
  }

  /// A progress_bar value, 0-1 (atalaia_tpl_fraction).
  double screenFraction(
    String? value,
    Map<String, Object?> data,
    Map<String, Object?> params,
  ) {
    var r = 0.0;
    _withScope(value, data, params, (v, scope) {
      r = bindings.tplFraction(v, scope);
    });
    return r;
  }

  /// A colour name's 0xRRGGBB, or null (atalaia_tpl_color).
  int? screenColor(String name) {
    final n = name.toNativeUtf8(allocator: calloc);
    final rgb = calloc<Uint32>();
    try {
      return bindings.tplColor(n, rgb) ? rgb.value : null;
    } finally {
      calloc
        ..free(n)
        ..free(rgb);
    }
  }

  /// Why an expression (without braces) is refused, or null (atalaia_tpl_expr_ok).
  String? screenExpressionError(String expr) {
    final bytes = utf8.encode(expr);
    final e = _nativeBytes(bytes);
    final err = calloc<Uint8>(64);
    try {
      return bindings.tplExprOk(e.cast(), bytes.length, err.cast(), 64)
          ? null
          : err.cast<Utf8>().toDartString();
    } finally {
      calloc
        ..free(e)
        ..free(err);
    }
  }

  /// Runs [body] with [text] (null for NULL) and a scope of [data] and [params]
  /// in native memory.
  void _withScope(
    String? text,
    Map<String, Object?> data,
    Map<String, Object?> params,
    void Function(Pointer<Utf8> text, Pointer<TemplateScope> scope) body,
  ) {
    final scope = calloc<TemplateScope>();
    final t = text == null ? nullptr : text.toNativeUtf8(allocator: calloc);
    scope.ref
      ..data = jsonEncode(data).toNativeUtf8(allocator: calloc)
      ..params = jsonEncode(params).toNativeUtf8(allocator: calloc);
    try {
      body(t.cast(), scope);
    } finally {
      calloc
        ..free(scope.ref.data)
        ..free(scope.ref.params)
        ..free(scope);
      if (t != nullptr) calloc.free(t);
    }
  }

  /// The `nfc.tag` data for a tag read, checked by the core against the
  /// game's id and key (atalaia/tag.h), as a box's shell gives it to its mode.
  String tagEventJson({
    required List<int> uid,
    required List<int>? payload,
    required int gameId,
    required List<int>? gameKey,
    required List<String> teams,
  }) {
    const cap = 256; // ATALAIA_TAG_JSON_MAX
    final u = _nativeBytes(uid);
    final p = payload == null ? nullptr : _nativeBytes(payload);
    final k = gameKey == null ? nullptr : _nativeBytes(gameKey);
    final names = calloc<Pointer<Utf8>>(teams.isEmpty ? 1 : teams.length);
    for (var i = 0; i < teams.length; i++) {
      names[i] = teams[i].toNativeUtf8(allocator: calloc);
    }
    final out = calloc<Uint8>(cap);
    try {
      final n = bindings.tagEventJson(
        u,
        uid.length,
        p,
        payload?.length ?? 0,
        gameId,
        k,
        names,
        teams.length,
        out.cast(),
        cap,
      );
      if (n == 0) {
        throw StateError('atalaia_tag_event_json: the data does not fit');
      }
      return out.cast<Utf8>().toDartString();
    } finally {
      for (var i = 0; i < teams.length; i++) {
        calloc.free(names[i]);
      }
      calloc
        ..free(names)
        ..free(u)
        ..free(out);
      if (p != nullptr) calloc.free(p);
      if (k != nullptr) calloc.free(k);
    }
  }

  /// The CBOR payload of an event as the core's codec encodes it for the
  /// radio (atalaia/codec.h), or why it cannot be encoded.
  EncodedEvent encodeEvent({
    required int node,
    required int seq,
    required int tMs,
    required String type,
    required int team,
    required int squad,
    required int prio,
    required String? dataJson,
  }) {
    const cap = 65535; // ATALAIA_CODEC_MAX_BYTES
    final typeBytes = utf8.encode(type);
    if (typeBytes.length >= eventTypeMax) {
      return const EncodedEvent(null, 'the event type is too long');
    }
    final ev = calloc<AtalaiaEvent>();
    ev.ref
      ..node = node
      ..seq = seq
      ..tMs = tMs
      ..team = team
      ..squad = squad
      ..prio = prio;
    for (var i = 0; i < typeBytes.length; i++) {
      ev.ref.type[i] = typeBytes[i];
    }
    final data = dataJson == null
        ? nullptr
        : dataJson.toNativeUtf8(allocator: calloc);
    final buf = calloc<Uint8>(cap);
    final err = calloc<Pointer<Utf8>>();
    try {
      final n = bindings.eventEncode(ev, data, buf, cap, err);
      if (n == 0) {
        return EncodedEvent(
          null,
          err.value == nullptr ? 'refused' : err.value.toDartString(),
        );
      }
      return EncodedEvent(Uint8List.fromList(buf.asTypedList(n)));
    } finally {
      calloc
        ..free(ev)
        ..free(buf)
        ..free(err);
      if (data != nullptr) calloc.free(data);
    }
  }
}

/// [bytes] copied into native memory from calloc (at least one byte, so an
/// empty list is still a valid pointer).
Pointer<Uint8> _nativeBytes(List<int> bytes) {
  final p = calloc<Uint8>(bytes.isEmpty ? 1 : bytes.length);
  p.asTypedList(bytes.isEmpty ? 1 : bytes.length).setAll(0, bytes);
  return p;
}

/// The text of a NUL-terminated C array of [length] bytes (an event type).
String fixedString(Array<Uint8> array, int length) {
  final out = BytesBuilder(copy: false);
  for (var i = 0; i < length; i++) {
    final b = array[i];
    if (b == 0) break;
    out.addByte(b);
  }
  return utf8.decode(out.takeBytes(), allowMalformed: true);
}
