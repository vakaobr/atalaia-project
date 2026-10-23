// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The scenario compiler on the Android field controller (ADR-P4-6 as
/// amended, decisions P4-1, P4R7, P4R8, P4R9; PE24): the library's entry
/// points, as the Pi controller's controller/atalaia_controller/scenarios
/// gives them, so that the phone serves POST /api/v1/scenarios/check and
/// POST /api/v1/scenarios as the Pi does.
///
///     final manifest = loadManifest(text);         // ManifestError: not a manifest
///     final problems = validate(manifest, core);   // [Problem(path, code, ...)]
///     final package = compileScenario(manifest, core); // ScenarioError on an error
///
/// The phone reads the manifest's text itself (scenario_manifest.dart, YAML
/// 1.1 as PyYAML reads it); the rules, field.lua and mode.yaml are the C
/// core's (core/scenario/, decision PE24-109), the one implementation the Pi
/// calls too, so both controllers give the same problems and the same
/// package byte for byte (protocol/vectors/scenario.json and
/// scenario_compile.json). What was read goes to the core as the manifest's
/// data tree ([encodeTree], core/scenario/README.md).
library;

import 'dart:convert';

import '../../ffi/bindings.dart';
import 'scenario_manifest.dart' as m;

export 'scenario_manifest.dart' show ManifestError, PyTimestamp;

const String levelError = 'error';
const String levelWarning = 'warning';

/// One problem of a manifest.
class Problem {
  const Problem(this.path, this.code, this.message, [this.level = levelError]);

  factory Problem.fromJson(Map<String, Object?> json) => Problem(
    json['path']! as String,
    json['code']! as String,
    json['message']! as String,
    json['level']! as String,
  );

  /// Where: '' for the manifest itself, 'objectives[1].depends_on[0]'.
  final String path;

  /// What, for programs (protocol/vectors/scenario.json).
  final String code;

  /// What, for the GM.
  final String message;

  /// [levelError] or [levelWarning].
  final String level;

  Map<String, String> toJson() => {
    'path': path,
    'code': code,
    'message': message,
    'level': level,
  };

  @override
  String toString() =>
      '${path.isEmpty ? '' : '$path: '}$level: $message ($code)';
}

/// The errors among [problems].
List<Problem> errors(List<Problem> problems) => [
  for (final p in problems)
    if (p.level == levelError) p,
];

/// The manifest has errors: [problems] lists them (and the warnings).
class ScenarioError implements Exception {
  ScenarioError(this.problems);

  final List<Problem> problems;

  @override
  String toString() => errors(problems).join('; ');
}

/// A value Lua cannot hold ([luaLiteral]).
class LuaError implements Exception {
  LuaError(this.message);

  final String message;

  @override
  String toString() => 'LuaError: $message';
}

/// The core could not read the data tree: a bug here, never the manifest's.
class CompilerFailed implements Exception {
  CompilerFailed(this.message);

  final String message;

  @override
  String toString() => 'the scenario compiler failed: $message';
}

/// A compiled scenario package (kind: scenario, decision P4R7).
class ScenarioPackage {
  const ScenarioPackage(this.id, this.version, this.files);

  final String id;
  final String version;

  /// mode.yaml and field.lua, as the controller's package upload takes them.
  final Map<String, String> files;

  String get modeYaml => files['mode.yaml']!;
  String get fieldLua => files['field.lua']!;
}

/// The manifest in a YAML (or JSON) text; [m.ManifestError] if it is not a
/// map, or a key repeats.
Map<Object?, Object?> loadManifest(String text) => m.loadText(text);

Map<String, Object?> _answer(AtalaiaCore core, String op, Object? manifest) {
  final out = core.scenario(op, encodeTree(manifest));
  if (out.containsKey('error') && !out.containsKey('ok')) {
    throw CompilerFailed(out['error']! as String);
  }
  return out;
}

List<Problem> _problems(Map<String, Object?> out) => [
  for (final p in (out['problems']! as List<Object?>))
    Problem.fromJson((p! as Map).cast<String, Object?>()),
];

/// Every problem in the manifest (a parsed map), errors and warnings, in the
/// manifest's order.
List<Problem> validate(Object? manifest, AtalaiaCore core) =>
    _problems(_answer(core, 'check', manifest));

/// The manifest's problems and, without errors, its package: one call.
(List<Problem>, ScenarioPackage?) compilePackage(
  Object? manifest,
  AtalaiaCore core,
) {
  final out = _answer(core, 'compile', manifest);
  final problems = _problems(out);
  if (errors(problems).isNotEmpty) return (problems, null);
  final files = (out['files']! as Map).cast<String, String>();
  return (
    problems,
    ScenarioPackage(out['id']! as String, out['version']! as String, {
      'mode.yaml': files['mode.yaml']!,
      'field.lua': files['field.lua']!,
    }),
  );
}

/// The scenario package of a manifest. [ScenarioError] when the manifest
/// has an error.
ScenarioPackage compileScenario(Object? manifest, AtalaiaCore core) {
  final (problems, package) = compilePackage(manifest, core);
  if (package == null) throw ScenarioError(problems);
  return package;
}

/// A value as the compiler writes it in field.lua: a Lua literal
/// ([LuaError] when Lua cannot hold it).
String luaLiteral(Object? value, AtalaiaCore core) {
  final out = _answer(core, 'literal', value);
  if (out['ok'] != true) throw LuaError(out['error']! as String);
  return out['lua']! as String;
}

// Deeper than the core reads (core/scenario/tree.lua, MAX_DEPTH = 100): the
// rest of a branch is not written, and the core says the manifest is nested
// too deep.
const int _depthWritten = 102;

/// A manifest as the data tree's JSON, UTF-8 (core/scenario/README.md): every
/// value typed as protocol/vectors/scenario_compile.json's "loads" write
/// them, and a list or map met again (a YAML alias, which the reader keeps as
/// one object, as PyYAML does) as {"alias": n}. Half of a surrogate pair in a
/// text built in code is written as its \u escape, which the core reads as
/// that one code point (and reports as bad_unicode).
List<int> encodeTree(Object? value) {
  final shared = Map<Object, int>.identity();
  final out = StringBuffer();

  void text(String s) {
    out.write('"');
    for (final rune in s.runes) {
      if (rune == 0x22) {
        out.write(r'\"');
      } else if (rune == 0x5C) {
        out.write(r'\\');
      } else if (rune < 0x20 || (rune >= 0xD800 && rune <= 0xDFFF)) {
        out.write('\\u${rune.toRadixString(16).padLeft(4, '0')}');
      } else {
        out.writeCharCode(rune);
      }
    }
    out.write('"');
  }

  void enc(Object? v, int depth) {
    switch (v) {
      case null:
        out.write('{"null":null}');
      case final bool b:
        out.write('{"bool":$b}');
      case final int i:
        out.write('{"int":"$i"}');
      case final BigInt b:
        out.write('{"int":"$b"}');
      case final double d:
        out.write('{"float":"${m.pyFloatRepr(d)}"}');
      case final String s:
        out.write('{"str":');
        text(s);
        out.write('}');
      case final m.PyTimestamp t:
        out.write('{"timestamp":"$t"}');
      case final List<Object?> l:
        final n = shared[l];
        if (n != null) {
          out.write('{"alias":$n}');
          return;
        }
        shared[l] = shared.length;
        out.write('{"list":[');
        if (depth < _depthWritten) {
          for (var i = 0; i < l.length; i++) {
            if (i > 0) out.write(',');
            enc(l[i], depth + 1);
          }
        }
        out.write(']}');
      case final Map<Object?, Object?> map:
        final n = shared[map];
        if (n != null) {
          out.write('{"alias":$n}');
          return;
        }
        shared[map] = shared.length;
        out.write('{"map":[');
        if (depth < _depthWritten) {
          var first = true;
          for (final e in map.entries) {
            if (!first) out.write(',');
            first = false;
            out.write('[');
            enc(e.key, depth + 1);
            out.write(',');
            enc(e.value, depth + 1);
            out.write(']');
          }
        }
        out.write(']}');
      default:
        out.write('{"other":{"repr":');
        text('$v');
        out.write(',"truthy":true}}');
    }
  }

  enc(value, 0);
  return utf8.encode(out.toString());
}
