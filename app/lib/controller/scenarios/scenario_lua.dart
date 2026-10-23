// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Lua generation for a scenario's field.lua (ADR-P4-6 as amended, decision
/// P4R9) on the Android field controller: a port of the Pi controller's
/// controller/atalaia_controller/scenarios/lua.py, byte for byte
/// (protocol/vectors/scenario_compile.json checks it).
///
/// The generated script is a data table, SCENARIO, followed by the scenario
/// runtime (runtime.lua, the same text for every scenario; here
/// [scenarioRuntimeLua]). Nothing the GM wrote is ever pasted into Lua code:
/// every value from the manifest reaches the script only through
/// [luaValue], which writes it as a Lua literal (a string in double quotes
/// with every quote, backslash and control character escaped; numbers that
/// must be finite; keys that are names or quoted strings). Comments in the
/// generated script hold only names the validator restricted to
/// [a-z0-9_.-].
///
/// Lengths are Python's: code points, not UTF-16 units, so a table with an
/// emoji in it breaks into lines where the Pi's does. Which characters
/// [luaString] writes as they are follows the Unicode categories of Dart's
/// RegExp (\p{L}, \p{M}, \p{N}, \p{P}, \p{S}, not \p{Co}), where Python uses
/// unicodedata: the two agree as long as they use the same Unicode version.
/// A character assigned in a newer version than one of them knows (an
/// emoji of the year, say) is escaped by one and written as it is by the
/// other; the script means the same either way, but the bytes differ.
library;

import 'dart:convert';

import 'scenario_manifest.dart' as m;
import 'scenario_runtime.g.dart';

/// The runtime's licence (runtime.lua), copied into every package.
const String license = 'GPL-3.0-or-later';

/// The SPDX tag, split so that REUSE does not read this line as a licence.
const String spdxTag =
    'SPDX-'
    'License-Identifier:';

/// The largest integer a Lua value takes, either way.
const int luaIntMax = 0x7FFFFFFFFFFFFFFF;

/// A value the Lua writer cannot write.
class LuaError implements Exception {
  LuaError(this.message);

  final String message;

  @override
  String toString() => message;
}

final RegExp _name = RegExp(r'^[A-Za-z_][A-Za-z0-9_]*\n?$');
const Set<String> _keywords = {
  'and', 'break', 'do', 'else', 'elseif', 'end', 'false', 'for', 'function', //
  'goto', 'if', 'in', 'local', 'nil', 'not', 'or', 'repeat', 'return', 'then',
  'true', 'until', 'while',
};
final RegExp _safeComment = RegExp(r'^[a-z0-9_.+-]*\n?$');
const Map<int, String> _short = {
  0x5C: r'\\',
  0x22: r'\"',
  0x0A: r'\n',
  0x0D: r'\r',
  0x09: r'\t',
};
final RegExp _printable = RegExp(
  r'^[\p{L}\p{M}\p{N}\p{P}\p{S}]$',
  unicode: true,
);
final RegExp _private = RegExp(r'^\p{Co}$', unicode: true);

/// A Lua string literal for any text: printable characters as they are (so
/// names stay readable), quotes and backslashes escaped, and every control,
/// format (bidi) or separator character, or anything else not printable, as
/// decimal byte escapes of its UTF-8 (\ddd).
String luaString(String text) {
  final out = StringBuffer('"');
  for (final rune in text.runes) {
    final short = _short[rune];
    if (short != null) {
      out.write(short);
    } else if (rune >= 0x20 && rune <= 0x7E) {
      out.writeCharCode(rune);
    } else if (rune > 0x7F && _isPrintable(rune)) {
      out.writeCharCode(rune);
    } else {
      for (final b in _utf8(rune)) {
        out.write('\\${b.toString().padLeft(3, '0')}');
      }
    }
  }
  out.write('"');
  return out.toString();
}

bool _isPrintable(int rune) {
  if (rune >= 0xD800 && rune <= 0xDFFF) return false; // a lone surrogate (Cs)
  final ch = String.fromCharCode(rune);
  return _printable.hasMatch(ch) && !_private.hasMatch(ch);
}

/// A code point's UTF-8, a lone surrogate included (Python's
/// "surrogatepass").
List<int> _utf8(int rune) {
  if (rune < 0x80) return [rune];
  if (rune < 0x800) return [0xC0 | (rune >> 6), 0x80 | (rune & 0x3F)];
  if (rune < 0x10000) {
    return [
      0xE0 | (rune >> 12),
      0x80 | ((rune >> 6) & 0x3F),
      0x80 | (rune & 0x3F),
    ];
  }
  return [
    0xF0 | (rune >> 18),
    0x80 | ((rune >> 12) & 0x3F),
    0x80 | ((rune >> 6) & 0x3F),
    0x80 | (rune & 0x3F),
  ];
}

/// A Lua literal for a manifest value: nil, booleans, finite numbers, texts,
/// lists and maps (in their order; a map's null values are left out).
String luaValue(Object? value, [int indent = 0]) {
  final pad = '  ' * (indent + 1);
  switch (value) {
    case null:
      return 'nil';
    case final bool b:
      return b ? 'true' : 'false';
    case final int i:
      if (i < -luaIntMax) throw LuaError('$i does not fit a Lua integer');
      return '$i';
    case BigInt():
      throw LuaError('$value does not fit a Lua integer');
    case final double d:
      if (!d.isFinite) throw LuaError('${m.pyFloatRepr(d)} is not finite');
      final text = m.pyFloatRepr(d);
      return text.contains(RegExp('[.en]')) ? text : '$text.0';
    case final String s:
      return luaString(s);
    case final List<Object?> list:
      if (list.isEmpty) return '{}';
      final items = [for (final v in list) luaValue(v, indent + 1)];
      return _table(items, pad, indent);
    case final Map<Object?, Object?> map:
      final lines = <String>[];
      for (final MapEntry(:key, value: v) in map.entries) {
        if (v == null) continue;
        if (key is! String) throw LuaError('a key must be text: $key');
        final name = _name.hasMatch(key) && !_keywords.contains(key)
            ? key
            : '[${luaString(key)}]';
        lines.add('$name = ${luaValue(v, indent + 1)}');
      }
      if (lines.isEmpty) return '{}';
      return _table(lines, pad, indent);
  }
  throw LuaError('cannot write ${value.runtimeType} as Lua');
}

String _table(List<String> items, String pad, int indent) {
  var width = 0;
  for (final item in items) {
    width += m.pyLen(item) + 2;
  }
  if (items.every((i) => !i.contains('\n')) && width < 80) {
    return '{ ${items.join(', ')} }';
  }
  return '{\n${items.map((i) => '$pad$i,\n').join()}${'  ' * indent}}';
}

/// A comment line: only for names the validator restricted (never a free
/// text).
String comment(String text) {
  if (!_safeComment.hasMatch(text)) {
    throw LuaError('${m.pyRepr(text)} cannot go in a comment');
  }
  return '-- $text';
}

// -- the objectives package's setup (modes/objectives/node.lua) --

const Map<String, String> _kinds = {
  'capture_and_hold': 'capture',
  'defend': 'capture',
  'enter_code': 'code',
  'scan_tags': 'tags',
  'destroy': 'bomb',
};

Map<Object?, Object?> _map(Object? value) =>
    m.pyTruthy(value) ? value! as Map<Object?, Object?> : {};

/// What the box of an open objective is told (the mode command setup,
/// without its name): only what the manifest gives, so the box's defaults
/// apply to the rest.
Map<String, Object?> setupCommand(
  Map<Object?, Object?> o,
  Object? lang,
  String label,
) {
  final kind = _kinds[o['type']]!;
  final params = _map(o['params']);
  final team = _map(o['assignee'])['team'];
  final setup = <String, Object?>{'kind': kind, 'label': label};
  if (lang != 'pt') setup['lang'] = lang;
  if (team != null && o['type'] != 'defend') setup['team'] = team;
  if ((kind == 'capture' || kind == 'bomb') && params.containsKey('hold_ms')) {
    setup['hold_ms'] = params['hold_ms'];
  }
  if (kind == 'bomb') {
    for (final key in ['defuse_ms', 'fuse_s']) {
      if (params.containsKey(key)) setup[key] = params[key];
    }
  }
  if (kind == 'code') setup['code'] = params['code'];
  if (kind == 'tags') {
    setup['count'] = params['tag_count'];
    if (m.pyTruthy(params['any'])) setup['any'] = true;
  }
  return setup;
}

double _float(Object? v) => (v! as num).toDouble();

Map<String, Object?> _zone(Map<Object?, Object?> destination) {
  if (destination.containsKey('points')) {
    return {
      'type': 'polygon',
      'points': [
        for (final p
            in (destination['points']! as List<Object?>).cast<List<Object?>>())
          [_float(p[0]), _float(p[1])],
      ],
    };
  }
  return {
    'type': 'circle',
    'lat': _float(destination['lat']),
    'lon': _float(destination['lon']),
    'radius_m': _float(destination['radius_m']),
  };
}

/// One objective as the runtime reads it (runtime.lua, "The data").
Map<String, Object?> objectiveData(
  Map<Object?, Object?> o,
  Map<Object?, Object?> manifest,
) {
  final lang = m.pyGet(manifest, 'lang', 'pt');
  final nodes = _map(manifest['nodes']);
  final params = _map(o['params']);
  final assignee = _map(o['assignee']);
  final effect = _map(o['effect']);
  final window = _map(o['time_window']);
  final points = effect['points'];
  final squad = assignee['squad'];
  final type = o['type'];
  final data = <String, Object?>{
    'id': o['id'],
    'type': type,
    'team': assignee['team'],
    // The events' squad is text (data key 2).
    'squad': squad != null ? m.pyStr(squad) : null,
    'hidden': m.pyGet(o, 'visibility', m.defaultVisibility(o)) == 'hidden',
    'depends_on': [
      ...(m.pyTruthy(o['depends_on'])
          ? o['depends_on']! as List<Object?>
          : const <Object?>[]),
    ],
    'reveals': [
      ...(m.pyTruthy(effect['reveal'])
          ? effect['reveal']! as List<Object?>
          : const <Object?>[]),
    ],
    'start_s': (m.pyGet(window, 'start_min', 0)! as int) * 60,
    'end_s': window['end_min'] != null
        ? (window['end_min']! as int) * 60
        : null,
    'points': points is int ? points : null,
    'points_param': points is Map<Object?, Object?> ? points['param'] : null,
    'win': m.pyTruthy(m.pyGet(effect, 'win', false)),
  };
  final target = o['target'];
  if (_kinds.containsKey(type)) {
    data['node'] = target;
    final label = m.translated(o, lang);
    data['setup'] = setupCommand(
      o,
      lang,
      m.pyTruthy(label) ? label! : o['id']! as String,
    );
  }
  if (type == 'capture_and_hold' || type == 'defend') {
    data['duration_s'] = m.pyGet(params, 'duration_s', 0);
  }
  if (type == 'escort') {
    final zone = _zone(params['destination']! as Map<Object?, Object?>);
    data['role'] = m.pyGet(_map(nodes[target]), 'role', 'vip');
    data['zone'] = zone;
    data['max_acc_m'] = m.pyGet(
      params,
      'max_acc_m',
      m.pyGet(zone, 'radius_m', 25.0),
    );
  }
  if (type == 'survive') data['minimum_lives'] = params['minimum_lives'];
  return data;
}

/// The scenario's field.lua: a header, the data table and the runtime.
String fieldLua(Map<Object?, Object?> manifest, [String? runtime]) {
  final sid = manifest['id']! as String;
  final data = <String, Object?>{
    'id': sid,
    'teams': [
      ...m.pyGet(manifest, 'teams', const ['red', 'blue'])! as List<Object?>,
    ],
    'objectives': [
      for (final o in manifest['objectives']! as List<Object?>)
        objectiveData(o! as Map<Object?, Object?>, manifest),
    ],
  };
  final lines = [
    '-- $spdxTag $license',
    '--',
    '-- Generated by the Atalaia scenario compiler '
        '(controller/atalaia_controller/scenarios)',
    '-- from the scenario manifest of:',
    comment(sid),
    '-- Edit the manifest and compile it again rather than this file. The '
        'objectives and',
    '-- their texts are in the table below; the code after it is the same '
        'for every scenario.',
    '',
    'local SCENARIO = ${luaValue(data)}',
    '',
  ];
  final text = runtime ?? scenarioRuntimeLua;
  const marker = '-- @runtime\n';
  // The runtime's own header stays in the repository.
  final body = text.substring(text.indexOf(marker) + marker.length);
  return lines.join('\n') + body;
}

/// The UTF-8 length of a value written as compact JSON the way Python's
/// json.dumps(value, separators=(",", ":"), ensure_ascii=False) writes it.
int pyJsonLength(Object? value) => utf8.encode(_pyJson(value)).length;

String _pyJson(Object? value) => switch (value) {
  null => 'null',
  true => 'true',
  false => 'false',
  final int i => '$i',
  final BigInt b => '$b',
  final double d =>
    d.isNaN
        ? 'NaN'
        : (d.isInfinite
              ? (d > 0 ? 'Infinity' : '-Infinity')
              : m.pyFloatRepr(d)),
  final String s => _pyJsonString(s),
  final List<Object?> l => '[${l.map(_pyJson).join(',')}]',
  final Map<Object?, Object?> map =>
    '{${map.entries.map((e) => '${_pyJsonString(_jsonKey(e.key))}:${_pyJson(e.value)}').join(',')}}',
  _ => _pyJsonString(value.toString()),
};

String _jsonKey(Object? key) => switch (key) {
  null => 'null',
  true => 'true',
  false => 'false',
  final double d => m.pyFloatRepr(d),
  _ => key.toString(),
};

String _pyJsonString(String s) {
  final out = StringBuffer('"');
  for (final unit in s.codeUnits) {
    switch (unit) {
      case 0x22:
        out.write(r'\"');
      case 0x5C:
        out.write(r'\\');
      case 0x0A:
        out.write(r'\n');
      case 0x0D:
        out.write(r'\r');
      case 0x09:
        out.write(r'\t');
      case 0x08:
        out.write(r'\b');
      case 0x0C:
        out.write(r'\f');
      default:
        if (unit < 0x20) {
          out.write('\\u${unit.toRadixString(16).padLeft(4, '0')}');
        } else {
          out.writeCharCode(unit);
        }
    }
  }
  out.write('"');
  return out.toString();
}
