// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Canonical JSON for signed records: protocol/chrono-record.md (chrono
/// readings) and protocol/player-token.md (player tokens).
///
/// A flat JSON object whose members are strings, integers or binary64
/// numbers:
///
/// * members sorted by key; keys are ASCII, so code-unit order is byte order;
/// * no whitespace anywhere;
/// * strings in UTF-8, with only `"` and `\` escaped (as `\"` and `\\`):
///   control characters (U+0000-U+001F, U+007F-U+009F) and lone surrogates
///   are refused, so no other escape is ever needed;
/// * integers in decimal;
/// * other numbers as the shortest decimal that reads back as the same
///   binary64 value, in plain notation with at least one digit after the
///   point (`0.2`, `100.0`, `106.68`); the value must be 0 or have a
///   magnitude from 1e-4 to below 1e15, where Dart's `double.toString()`
///   and Python's `repr(float)` agree.
///
/// For such values this is exactly Python's
/// `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
/// encoded as UTF-8, which is what the controller and the site server use.
/// Dart's VM is assumed: on the web, `100.0` would print as `100`.
library;

import 'dart:convert';
import 'dart:typed_data';

final _key = RegExp(r'^[a-z0-9_]+$');

/// Whether [s] is text the canonical form accepts: no control characters
/// (C0, DEL, C1) and no lone surrogates.
bool isCanonicalText(String s) {
  for (var i = 0; i < s.length; i++) {
    final c = s.codeUnitAt(i);
    if (c < 0x20 || (c >= 0x7f && c <= 0x9f)) return false;
    if (c >= 0xd800 && c <= 0xdbff) {
      if (i + 1 >= s.length) return false;
      final d = s.codeUnitAt(i + 1);
      if (d < 0xdc00 || d > 0xdfff) return false;
      i++;
    } else if (c >= 0xdc00 && c <= 0xdfff) {
      return false;
    }
  }
  return true;
}

/// The canonical text of a binary64 number (see the library comment).
String canonicalNumber(double x) {
  if (!x.isFinite) {
    throw ArgumentError.value(x, 'x', 'not a finite number');
  }
  if (x != 0 && (x.abs() < 1e-4 || x.abs() >= 1e15)) {
    throw ArgumentError.value(x, 'x', 'outside 1e-4 to 1e15');
  }
  final text = x.toString();
  if (text.contains('e') || !text.contains('.')) {
    throw StateError('unexpected double text $text (not the Dart VM?)');
  }
  return text;
}

String _quote(String s) {
  if (!isCanonicalText(s)) {
    throw ArgumentError.value(s, 's', 'control character or lone surrogate');
  }
  return '"${s.replaceAll(r'\', r'\\').replaceAll('"', r'\"')}"';
}

/// The canonical JSON text of [members] (String, int or double values).
String canonicalJsonString(Map<String, Object> members) {
  final keys = members.keys.toList()..sort();
  final out = StringBuffer('{');
  var first = true;
  for (final k in keys) {
    if (!_key.hasMatch(k)) {
      throw ArgumentError.value(k, 'key', 'keys are a-z, 0-9 and _');
    }
    if (!first) out.write(',');
    first = false;
    out.write('"$k":');
    final v = members[k]!;
    if (v is String) {
      out.write(_quote(v));
    } else if (v is int) {
      out.write(v.toString());
    } else if (v is double) {
      out.write(canonicalNumber(v));
    } else {
      throw ArgumentError.value(v, k, 'only strings, integers and numbers');
    }
  }
  out.write('}');
  return out.toString();
}

/// The canonical JSON of [members] in UTF-8: the bytes that are signed.
Uint8List canonicalJson(Map<String, Object> members) =>
    utf8.encode(canonicalJsonString(members));
