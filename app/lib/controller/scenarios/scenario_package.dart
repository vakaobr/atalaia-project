// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The scenario compiler on the Android field controller (ADR-P4-6 as
/// amended, decisions P4-1, P4R7, P4R8, P4R9; PE24): the compiled scenario
/// package (kind: scenario), mode.yaml and field.lua, and the library's
/// entry points, as the Pi controller's
/// controller/atalaia_controller/scenarios/__init__.py and package.py give
/// them, so that the phone serves POST /api/v1/scenarios/check and POST
/// /api/v1/scenarios as the Pi does.
///
///     final manifest = loadManifest(text);   // ManifestError: not a manifest
///     final problems = validate(manifest);   // [Problem(path, code, ...)]
///     final package = compileScenario(manifest); // ScenarioError on an error
///
/// mode.yaml carries what the controller and the app need to show the
/// scenario without reading its Lua: the names in English and Portuguese,
/// the scenario's parameters, and under scenario the boxes' language, the
/// teams, the squads, the nodes the GM assigns (P4R8) and every objective's
/// id, type, names, assignee, visibility, dependencies and points. Codes and
/// destinations are only in field.lua, which only staff read.
///
/// The Pi writes mode.yaml with PyYAML's yaml.safe_dump(doc, sort_keys=False,
/// allow_unicode=True, width=100). [modeYaml] has its own emitter, a port of
/// the parts of PyYAML's emitter that such a document uses (block maps and
/// lists, {} for an empty map, plain, single-quoted and double-quoted
/// scalars with PyYAML's choice between them and its folding at 100
/// columns, counted in code points, and &id001 anchors where one map
/// appears twice), so the text is the Pi's byte for byte:
/// protocol/vectors/scenario_compile.json checks it on every vector, and
/// also that the text reads back to the same data. The one known gap is a
/// character assigned after the Unicode version of either side, which
/// matters only to field.lua (scenario_lua.dart).
library;

import 'scenario_lua.dart';
import 'scenario_manifest.dart' as m;
import 'scenario_validator.dart';

export 'scenario_lua.dart' show LuaError, fieldLua, luaString, luaValue;
export 'scenario_manifest.dart' show ManifestError, PyTimestamp;
export 'scenario_validator.dart'
    show Problem, errors, levelError, levelWarning, validate;

/// The manifest has errors: [problems] lists them (and the warnings).
class ScenarioError implements Exception {
  ScenarioError(this.problems);

  final List<Problem> problems;

  @override
  String toString() => errors(problems).join('; ');
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

/// The scenario package of a manifest. [ScenarioError] when the manifest
/// has an error.
ScenarioPackage compileScenario(Object? manifest) {
  final problems = validate(manifest);
  if (errors(problems).isNotEmpty) throw ScenarioError(problems);
  return build(manifest! as Map<Object?, Object?>);
}

/// The package of a manifest that validated without errors.
ScenarioPackage build(Map<Object?, Object?> manifest) => ScenarioPackage(
  manifest['id']! as String,
  m.pyStr(manifest['version']),
  {'mode.yaml': modeYaml(manifest), 'field.lua': fieldLua(manifest)},
);

Map<Object?, Object?> _map(Object? value) =>
    m.pyTruthy(value) ? value! as Map<Object?, Object?> : {};

Map<String, Object?> _texts(Map<Object?, Object?> entry, List<String> keys) {
  final out = <String, Object?>{};
  for (final MapEntry(key: lang, value: strings) in _map(
    entry['i18n'],
  ).entries) {
    final s = strings! as Map<Object?, Object?>;
    final picked = <String, Object?>{
      for (final k in keys)
        if (m.pyTruthy(s[k])) k: s[k],
    };
    if (picked.isNotEmpty) out[lang! as String] = picked;
  }
  return out;
}

Map<String, Object?> _objectiveMeta(Map<Object?, Object?> o) {
  final assignee = _map(o['assignee']);
  final effect = _map(o['effect']);
  final meta = <String, Object?>{
    'id': o['id'],
    'type': o['type'],
    'name': o['name'],
  };
  if (m.pyTruthy(o['description'])) meta['description'] = o['description'];
  final texts = _texts(o, const ['name', 'description']);
  if (texts.isNotEmpty) meta['i18n'] = texts;
  if (assignee['team'] != null) meta['team'] = assignee['team'];
  if (assignee['squad'] != null) meta['squad'] = assignee['squad'];
  meta['visibility'] = m.pyGet(o, 'visibility', m.defaultVisibility(o));
  if (o['target'] != null) meta['target'] = o['target'];
  if (m.pyTruthy(o['depends_on'])) {
    meta['depends_on'] = [...o['depends_on']! as List<Object?>];
  }
  if (m.pyTruthy(effect['reveal'])) {
    meta['reveals'] = [...effect['reveal']! as List<Object?>];
  }
  // The same object as the manifest's, as in Python: a points map shared by
  // two objectives (a YAML alias) is written once with an anchor.
  if (effect['points'] != null) meta['points'] = effect['points'];
  if (m.pyTruthy(effect['win'])) meta['win'] = true;
  if (m.pyTruthy(o['time_window'])) {
    meta['time_window'] = {...o['time_window']! as Map<Object?, Object?>};
  }
  return meta;
}

/// The package's mode.yaml, as the Pi writes it.
String modeYaml(Map<Object?, Object?> manifest) {
  final doc = <String, Object?>{
    'id': manifest['id'],
    'version': m.pyStr(manifest['version']),
    'license': license,
    'kind': 'scenario',
    'name': manifest['name'],
  };
  if (m.pyTruthy(manifest['description'])) {
    doc['description'] = manifest['description'];
  }
  if (m.pyTruthy(manifest['author'])) doc['author'] = manifest['author'];
  if (m.pyTruthy(manifest['params'])) {
    doc['params'] = {
      for (final MapEntry(:key, :value)
          in (manifest['params']! as Map<Object?, Object?>).entries)
        key: {...value! as Map<Object?, Object?>},
    };
  }
  final texts = _texts(manifest, const ['name', 'description', 'params']);
  if (texts.isNotEmpty) doc['i18n'] = texts;
  doc['scenario'] = {
    'lang': m.pyGet(manifest, 'lang', 'pt'),
    'teams': [
      ...m.pyGet(manifest, 'teams', const ['red', 'blue'])! as List<Object?>,
    ],
    'squads': m.pyGet(manifest, 'squads', 0),
    'nodes': {
      for (final MapEntry(:key, :value) in _map(manifest['nodes']).entries)
        key: {...value! as Map<Object?, Object?>},
    },
    'objectives': [
      for (final o in manifest['objectives']! as List<Object?>)
        _objectiveMeta(o! as Map<Object?, Object?>),
    ],
  };
  final head =
      '# $spdxTag $license\n'
      '#\n'
      '# Generated by the Atalaia scenario compiler '
      '(controller/atalaia_controller/scenarios) from a\n'
      '# scenario manifest: a scenario package (kind: scenario, decision '
      "P4R7) that leads the game's id,\n"
      '# <this id>+${m.objectivesPackage}. Compile the manifest again rather '
      'than editing this file.\n';
  return head + safeDump(doc);
}

/// PyYAML's yaml.safe_dump(value, sort_keys=False, allow_unicode=True,
/// width=100) for maps, lists, texts, integers, floats, booleans and null.
String safeDump(Object? value) => (_Emitter()..document(value)).out.toString();

const int _bestIndent = 2;
const int _bestWidth = 100;

bool _isBreak(int c) => c == 0x0A || c == 0x85 || c == 0x2028 || c == 0x2029;

/// The parts of PyYAML's Emitter (emitter.py) that a safe_dump of plain data
/// in block style uses, with its state: the same column, indent, whitespace
/// and indention flags decide every space and line break.
class _Emitter {
  final StringBuffer out = StringBuffer();
  int column = 0;
  bool whitespace = true;
  bool indention = true;
  int? indent;
  final List<int?> indents = [];
  int flowLevel = 0;
  bool rootContext = false;
  bool sequenceContext = false;
  bool mappingContext = false;
  bool simpleKeyContext = false;

  /// The anchors of the maps and lists that appear more than once (id001,
  /// ...), numbered as PyYAML's serializer does; and those already written.
  final Map<Object, String?> anchors = Map.identity();
  final Set<Object> written = Set.identity();
  int lastAnchor = 0;

  void document(Object? value) {
    _anchor(value);
    node(value, root: true);
    // expect_document_end: an implicit end.
    writeIndent();
  }

  void _anchor(Object? value) {
    if (value is! Map && value is! List) return;
    final key = value!;
    if (anchors.containsKey(key)) {
      anchors[key] ??= 'id${(++lastAnchor).toString().padLeft(3, '0')}';
      return;
    }
    anchors[key] = null;
    if (value is List<Object?>) {
      value.forEach(_anchor);
    } else if (value is Map<Object?, Object?>) {
      value.forEach((k, v) {
        _anchor(k);
        _anchor(v);
      });
    }
  }

  void node(
    Object? value, {
    bool root = false,
    bool sequence = false,
    bool mapping = false,
    bool simpleKey = false,
  }) {
    rootContext = root;
    sequenceContext = sequence;
    mappingContext = mapping;
    simpleKeyContext = simpleKey;
    if (value is Map || value is List) {
      final key = value!;
      final anchor = anchors[key];
      if (written.contains(key)) {
        writeIndicator('*$anchor', true);
        return;
      }
      written.add(key);
      if (anchor != null) writeIndicator('&$anchor', true);
      if (value is List<Object?>) {
        if (flowLevel > 0 || value.isEmpty) {
          flowCollection('[', ']', value.isEmpty);
        } else {
          blockSequence(value);
        }
      } else {
        final map = value as Map<Object?, Object?>;
        if (flowLevel > 0 || map.isEmpty) {
          flowCollection('{', '}', map.isEmpty);
        } else {
          blockMapping(map);
        }
      }
      return;
    }
    increaseIndent(flow: true);
    scalar(value);
    indent = indents.removeLast();
  }

  void increaseIndent({bool flow = false, bool indentless = false}) {
    indents.add(indent);
    final current = indent;
    if (current == null) {
      indent = flow ? _bestIndent : 0;
    } else if (!indentless) {
      indent = current + _bestIndent;
    }
  }

  void flowCollection(String open, String close, bool empty) {
    // Only empty collections are written in flow style here.
    if (!empty) throw StateError('a non-empty flow collection');
    writeIndicator(open, true, whitespace: true);
    flowLevel++;
    increaseIndent(flow: true);
    indent = indents.removeLast();
    flowLevel--;
    writeIndicator(close, false);
  }

  void blockSequence(List<Object?> list) {
    final indentless = mappingContext && !indention;
    increaseIndent(indentless: indentless);
    for (final item in list) {
      writeIndent();
      writeIndicator('-', true, indention: true);
      node(item, sequence: true);
    }
    indent = indents.removeLast();
  }

  void blockMapping(Map<Object?, Object?> map) {
    increaseIndent();
    for (final MapEntry(:key, :value) in map.entries) {
      writeIndent();
      if (checkSimpleKey(key)) {
        node(key, mapping: true, simpleKey: true);
        writeIndicator(':', false);
        node(value, mapping: true);
      } else {
        writeIndicator('?', true, indention: true);
        node(key, mapping: true);
        writeIndent();
        writeIndicator(':', true, indention: true);
        node(value, mapping: true);
      }
    }
    indent = indents.removeLast();
  }

  bool checkSimpleKey(Object? key) {
    if (key is Map || key is List) {
      return written.contains(key) ||
          (key is Map && key.isEmpty) ||
          (key is List && key.isEmpty);
    }
    final (text, _) = _represent(key);
    final a = _Analysis(text);
    return a.length < 128 && !a.empty && !a.multiline;
  }

  // -- scalars --

  /// A scalar's text and whether PyYAML would read it back, plain, as the
  /// same type (the serializer's implicit[0]).
  (String, bool) _represent(Object? value) => switch (value) {
    null => ('null', true),
    true => ('true', true),
    false => ('false', true),
    final int i => ('$i', true),
    final BigInt b => ('$b', true),
    final double d => (_representFloat(d), true),
    final String s => (s, m.pyYamlKind(s) == 'str'),
    _ => (value.toString(), false),
  };

  String _representFloat(double d) {
    if (d.isNaN) return '.nan';
    if (d.isInfinite) return d > 0 ? '.inf' : '-.inf';
    final text = m.pyFloatRepr(d).toLowerCase();
    if (!text.contains('.') && text.contains('e')) {
      return text.replaceFirst('e', '.0e');
    }
    return text;
  }

  void scalar(Object? value) {
    final (text, implicit) = _represent(value);
    final a = _Analysis(text);
    final style = _chooseStyle(a, implicit);
    final split = !simpleKeyContext;
    final runes = text.runes.toList();
    switch (style) {
      case '"':
        writeDoubleQuoted(runes, split);
      case "'":
        writeSingleQuoted(runes, split);
      default:
        writePlain(runes, split);
    }
  }

  String _chooseStyle(_Analysis a, bool implicit) {
    if (implicit &&
        !(simpleKeyContext && (a.empty || a.multiline)) &&
        (flowLevel > 0 ? a.allowFlowPlain : a.allowBlockPlain)) {
      return '';
    }
    if (a.allowSingleQuoted && !(simpleKeyContext && a.multiline)) return "'";
    return '"';
  }

  // -- writers --

  void _write(String data) {
    column += m.pyLen(data);
    out.write(data);
  }

  void writeIndicator(
    String indicator,
    bool needWhitespace, {
    bool whitespace = false,
    bool indention = false,
  }) {
    final data = (this.whitespace || !needWhitespace)
        ? indicator
        : ' $indicator';
    this.whitespace = whitespace;
    this.indention = this.indention && indention;
    _write(data);
  }

  void writeIndent() {
    final indent = this.indent ?? 0;
    if (!indention || column > indent || (column == indent && !whitespace)) {
      writeLineBreak();
    }
    if (column < indent) {
      whitespace = true;
      out.write(' ' * (indent - column));
      column = indent;
    }
  }

  void writeLineBreak([String data = '\n']) {
    whitespace = true;
    indention = true;
    column = 0;
    out.write(data);
  }

  /// Python's text[start:end] (empty when start is past end).
  String _text(List<int> runes, int start, int end) =>
      start >= end ? '' : String.fromCharCodes(runes.sublist(start, end));

  void writePlain(List<int> text, bool split) {
    if (text.isEmpty) return;
    if (!whitespace) _write(' ');
    whitespace = false;
    indention = false;
    var spaces = false;
    var breaks = false;
    var start = 0;
    var end = 0;
    while (end <= text.length) {
      final ch = end < text.length ? text[end] : null;
      if (spaces) {
        if (ch != 0x20) {
          if (start + 1 == end && column > _bestWidth && split) {
            writeIndent();
            whitespace = false;
            indention = false;
          } else {
            _write(_text(text, start, end));
          }
          start = end;
        }
      } else if (breaks) {
        if (ch == null || !_isBreak(ch)) {
          if (text[start] == 0x0A) writeLineBreak();
          for (final br in text.sublist(start, end)) {
            writeLineBreak(br == 0x0A ? '\n' : String.fromCharCode(br));
          }
          writeIndent();
          whitespace = false;
          indention = false;
          start = end;
        }
      } else {
        if (ch == null || ch == 0x20 || _isBreak(ch)) {
          _write(_text(text, start, end));
          start = end;
        }
      }
      if (ch != null) {
        spaces = ch == 0x20;
        breaks = _isBreak(ch);
      }
      end++;
    }
  }

  void writeSingleQuoted(List<int> text, bool split) {
    writeIndicator("'", true);
    var spaces = false;
    var breaks = false;
    var start = 0;
    var end = 0;
    while (end <= text.length) {
      final ch = end < text.length ? text[end] : null;
      if (spaces) {
        if (ch == null || ch != 0x20) {
          if (start + 1 == end &&
              column > _bestWidth &&
              split &&
              start != 0 &&
              end != text.length) {
            writeIndent();
          } else {
            _write(_text(text, start, end));
          }
          start = end;
        }
      } else if (breaks) {
        if (ch == null || !_isBreak(ch)) {
          if (text[start] == 0x0A) writeLineBreak();
          for (final br in text.sublist(start, end)) {
            writeLineBreak(br == 0x0A ? '\n' : String.fromCharCode(br));
          }
          writeIndent();
          start = end;
        }
      } else {
        if (ch == null || ch == 0x20 || _isBreak(ch) || ch == 0x27) {
          if (start < end) {
            _write(_text(text, start, end));
            start = end;
          }
        }
      }
      if (ch == 0x27) {
        _write("''");
        start = end + 1;
      }
      if (ch != null) {
        spaces = ch == 0x20;
        breaks = _isBreak(ch);
      }
      end++;
    }
    writeIndicator("'", false);
  }

  static const Map<int, String> _escapes = {
    0x00: '0',
    0x07: 'a',
    0x08: 'b',
    0x09: 't',
    0x0A: 'n',
    0x0B: 'v',
    0x0C: 'f',
    0x0D: 'r',
    0x1B: 'e',
    0x22: '"',
    0x5C: r'\',
    0x85: 'N',
    0xA0: '_',
    0x2028: 'L',
    0x2029: 'P',
  };

  void writeDoubleQuoted(List<int> text, bool split) {
    writeIndicator('"', true);
    var start = 0;
    var end = 0;
    while (end <= text.length) {
      final ch = end < text.length ? text[end] : null;
      if (ch == null ||
          ch == 0x22 ||
          ch == 0x5C ||
          ch == 0x85 ||
          ch == 0x2028 ||
          ch == 0x2029 ||
          ch == 0xFEFF ||
          !((ch >= 0x20 && ch <= 0x7E) ||
              (ch >= 0xA0 && ch <= 0xD7FF) ||
              (ch >= 0xE000 && ch <= 0xFFFD))) {
        if (start < end) {
          _write(_text(text, start, end));
          start = end;
        }
        if (ch != null) {
          final escape = _escapes[ch];
          final String data;
          if (escape != null) {
            data = '\\$escape';
          } else if (ch <= 0xFF) {
            data = '\\x${_hex(ch, 2)}';
          } else if (ch <= 0xFFFF) {
            data = '\\u${_hex(ch, 4)}';
          } else {
            data = '\\U${_hex(ch, 8)}';
          }
          _write(data);
          start = end + 1;
        }
      }
      if (end > 0 &&
          end < text.length - 1 &&
          (ch == 0x20 || start >= end) &&
          column + (end - start) > _bestWidth &&
          split) {
        var data = '${_text(text, start, end)}\\';
        if (start < end) start = end;
        _write(data);
        writeIndent();
        whitespace = false;
        indention = false;
        if (text[start] == 0x20) {
          data = r'\';
          _write(data);
        }
      }
      end++;
    }
    writeIndicator('"', false);
  }

  static String _hex(int value, int width) =>
      value.toRadixString(16).toUpperCase().padLeft(width, '0');
}

/// PyYAML's analyze_scalar, for allow_unicode=True.
class _Analysis {
  factory _Analysis(String scalar) {
    final s = scalar.runes.toList();
    if (s.isEmpty) {
      return _Analysis._(
        length: 0,
        empty: true,
        multiline: false,
        allowFlowPlain: false,
        allowBlockPlain: true,
        allowSingleQuoted: true,
      );
    }
    var blockIndicators = false;
    var flowIndicators = false;
    var lineBreaks = false;
    var specialCharacters = false;
    var leadingSpace = false;
    var leadingBreak = false;
    var trailingSpace = false;
    var trailingBreak = false;
    var breakSpace = false;
    var spaceBreak = false;
    if (scalar.startsWith('---') || scalar.startsWith('...')) {
      blockIndicators = true;
      flowIndicators = true;
    }
    bool ws(int c) =>
        c == 0 || c == 0x20 || c == 0x09 || c == 0x0D || _isBreak(c);
    var precededByWhitespace = true;
    var followedByWhitespace = s.length == 1 || ws(s[1]);
    var previousSpace = false;
    var previousBreak = false;
    for (var index = 0; index < s.length; index++) {
      final ch = s[index];
      if (index == 0) {
        if ('#,[]{}&*!|>\'"%@`'.runes.contains(ch)) {
          flowIndicators = true;
          blockIndicators = true;
        }
        if (ch == 0x3F || ch == 0x3A) {
          flowIndicators = true;
          if (followedByWhitespace) blockIndicators = true;
        }
        if (ch == 0x2D && followedByWhitespace) {
          flowIndicators = true;
          blockIndicators = true;
        }
      } else {
        if (',?[]{}'.runes.contains(ch)) flowIndicators = true;
        if (ch == 0x3A) {
          flowIndicators = true;
          if (followedByWhitespace) blockIndicators = true;
        }
        if (ch == 0x23 && precededByWhitespace) {
          flowIndicators = true;
          blockIndicators = true;
        }
      }
      if (_isBreak(ch)) lineBreaks = true;
      if (!(ch == 0x0A || (ch >= 0x20 && ch <= 0x7E))) {
        final unicode =
            (ch == 0x85 ||
                (ch >= 0xA0 && ch <= 0xD7FF) ||
                (ch >= 0xE000 && ch <= 0xFFFD) ||
                (ch >= 0x10000 && ch < 0x10FFFF)) &&
            ch != 0xFEFF;
        if (!unicode) specialCharacters = true;
      }
      if (ch == 0x20) {
        if (index == 0) leadingSpace = true;
        if (index == s.length - 1) trailingSpace = true;
        if (previousBreak) breakSpace = true;
        previousSpace = true;
        previousBreak = false;
      } else if (_isBreak(ch)) {
        if (index == 0) leadingBreak = true;
        if (index == s.length - 1) trailingBreak = true;
        if (previousSpace) spaceBreak = true;
        previousSpace = false;
        previousBreak = true;
      } else {
        previousSpace = false;
        previousBreak = false;
      }
      precededByWhitespace = ws(ch);
      followedByWhitespace = index + 2 >= s.length || ws(s[index + 2]);
    }
    var allowFlowPlain = true;
    var allowBlockPlain = true;
    var allowSingleQuoted = true;
    if (leadingSpace || leadingBreak || trailingSpace || trailingBreak) {
      allowFlowPlain = allowBlockPlain = false;
    }
    if (breakSpace) {
      allowFlowPlain = allowBlockPlain = allowSingleQuoted = false;
    }
    if (spaceBreak || specialCharacters) {
      allowFlowPlain = allowBlockPlain = allowSingleQuoted = false;
    }
    if (lineBreaks) allowFlowPlain = allowBlockPlain = false;
    if (flowIndicators) allowFlowPlain = false;
    if (blockIndicators) allowBlockPlain = false;
    return _Analysis._(
      length: s.length,
      empty: false,
      multiline: lineBreaks,
      allowFlowPlain: allowFlowPlain,
      allowBlockPlain: allowBlockPlain,
      allowSingleQuoted: allowSingleQuoted,
    );
  }

  _Analysis._({
    required this.length,
    required this.empty,
    required this.multiline,
    required this.allowFlowPlain,
    required this.allowBlockPlain,
    required this.allowSingleQuoted,
  });

  final int length;
  final bool empty;
  final bool multiline;
  final bool allowFlowPlain;
  final bool allowBlockPlain;
  final bool allowSingleQuoted;
}
