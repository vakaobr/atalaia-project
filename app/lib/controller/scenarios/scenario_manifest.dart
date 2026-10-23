// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The scenario manifest (ADR-P4-6 as amended) on the Android field
/// controller (decision PE24): reading it, its names (decision P4R8) and the
/// objective types. A port of the Pi controller's
/// controller/atalaia_controller/scenarios/manifest.py, with the few Python
/// semantics the validator, the Lua writer and mode.yaml rely on ([pyStr],
/// [pyTruthy], [pyGet], [pyFloatRepr]).
///
/// A manifest is YAML (or JSON, which is YAML too). Reading it never runs
/// code and refuses a key given twice in one map. The Pi reads it with
/// PyYAML 6's safe loader, which reads YAML 1.1; package:yaml reads YAML
/// 1.2's core schema. [loadText] reads the text with package:yaml and then
/// reads every plain scalar again as PyYAML does (its resolver and
/// constructors), so that a manifest means the same on both controllers.
/// What that changes (protocol/vectors/scenario_compile.json, "loads",
/// checks each):
///
/// * yes, no, on and off (in any of PyYAML's spellings) are true and false,
///   as keys too (`yes:` is the key true, as the Pi reads it);
/// * 0815 is the text "0815" (so a code needs no quotes), 0755 and 010 are
///   octal, 1_000 is 1000, 0b101 is binary, 1:30 is 90 (sexagesimal), and
///   0o17 is the text "0o17";
/// * 1e5 is the text "1e5" (a YAML 1.1 float has a dot, and a sign on its
///   exponent: 1.0e+5), -.5 is text and .5 is a float;
/// * "1 \u3000" is a text (Dart's int.tryParse, which package:yaml uses,
///   skips the Unicode space);
/// * 2026-10-23 and 2026-10-23 10:00:00 are dates ([PyTimestamp]), which no
///   field accepts; an impossible date (2026-13-45) is refused (PyYAML
///   raises a ValueError there, which the Pi does not catch);
/// * integers of any size are kept (a BigInt past 64 bits, as Python's int);
/// * merge keys (`<<: *anchor`, `<<: [*a, *b]`) are merged as PyYAML does,
///   and a key a merge already gave is "given twice", as the Pi's loader
///   says; an anchored map read twice is one object, as in Python, so
///   mode.yaml writes it once with an anchor;
/// * keys equal in Python are one key, so a repeated one: yes and true, 1
///   and 1.0, yes and 1;
/// * a character past U+FFFF written as two escapes, a surrogate pair
///   ("😀", as JSON in ASCII writes an emoji), is that character
///   in a double-quoted text (package:yaml refuses the escapes; the Pi's
///   loader joins what PyYAML reads), and half of a pair is refused, on
///   both (decision PE24-107);
/// * a plain = or << as a value is refused (PyYAML has no constructor for
///   them), as is a character PyYAML's reader does not accept (C0 controls
///   but tab and line breaks, DEL, C1 controls but NEL, lone surrogates,
///   U+FFFE and U+FFFF), and a tab outside a quoted or block text or a
///   comment (PyYAML's scanner separates with spaces only).
///
/// What still differs, on texts a GM is unlikely to write (a manifest one
/// side reads and the other refuses; never one both read differently, as
/// far as the vectors and a fuzz of both readers found):
///
/// * a raw NEL, line separator or paragraph separator, which PyYAML reads
///   as a line break even inside quotes, is refused here (written as an
///   escape, "\L", it is the same on both);
/// * the explicit tags read are !!str and the non-specific ! (PyYAML reads
///   `! "12"` as 12, and so does this), !!int, !!float, !!bool and !!null on
///   plain scalars, and !!map and !!seq; every other tag (!!binary, !!set,
///   !!omap, !!timestamp, a quoted !!int), %TAG directives, and a tagged
///   value package:yaml does not read itself (!!bool yes, !!null x, !!float
///   1) are refused;
/// * a map with two merge keys is refused (package:yaml calls them a
///   repeated key), and so are keys equal under YAML 1.2 but not 1.1 (010
///   and 10, yes and 'yes');
/// * the grammars of YAML 1.1 and 1.2 differ on a few plain scalars: a lone
///   - in a flow list and an empty ! read on the Pi, a plain text that
///   starts with : (`[:3]`, `- :`) reads here; each is refused by the other.
library;

import 'dart:convert';

import 'package:yaml/yaml.dart';

// The names (P4R8). An objective id goes into every scenario event (data key
// 34), so it is short. Each ends where it seems: the Pi's patterns end with
// \Z since PE24-106 (Python's "$" had also matched before a final newline,
// so "hill\n" was an objective id); Dart's "$" never did.
final RegExp objectiveIdPattern = RegExp(r'^[a-z][a-z0-9_]{0,23}$');

/// A mode id, as modes.py checks it on upload.
final RegExp scenarioIdPattern = RegExp(
  r'^[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+$',
);
final RegExp paramNamePattern = RegExp(r'^[a-z][a-z0-9_]{0,31}$');
final RegExp playerRolePattern = RegExp(r'^[a-z][a-z0-9_]{0,23}$');

/// The objectives package takes up to 8 digits, then #.
final RegExp codePattern = RegExp(r'^[0-9]{1,8}$');

const String objectivesPackage = 'org.atalaia.objectives';

/// A game's id in a join (protocol/join.md).
const int modeIdMax = 63;

/// The scenario leads the game's id and the objectives package follows
/// (decision M6-1).
const int scenarioIdMax = modeIdMax - 1 - objectivesPackage.length;

/// The core's ATALAIA_TEAM_NAME_MAX - 1.
const int teamNameMax = 23;
const int teamsMax = 8;
const int squadsMax = 16;

/// A box's name in its HELLO (protocol/schema/messages.yaml).
const int nodeNameMax = 24;

/// Bytes: a scenario's or an objective's name.
const int nameMax = 64;
const int descriptionMax = 2000;
const int versionMax = 32;
const int objectivesMax = 64;
const int nodesMax = 64;

/// A box's optional level on a multi-story field (ML-8).
const int levelsMax = 10;
const int pointsMax = 100000;

/// A week, in minutes.
const int windowMaxMin = 7 * 24 * 60;
const int manifestMaxBytes = 256 * 1024;

/// The objectives package's screens (modes/objectives/node.lua).
const List<String> langs = ['pt', 'en'];

/// Texts are in English, with i18n.pt (P4R8).
const List<String> translations = ['pt'];

/// org.atalaia.objectives' roles.
const List<String> nodeRoles = ['objective', 'bomb_site'];
const List<String> visibilities = ['public', 'team', 'squad', 'hidden'];

/// ATALAIA_GEO_POLYGON_MAX (core/include/atalaia/geo.h).
const int polygonMax = 32;

/// A phone's GPS is rarely better than this.
const int radiusWarnM = 10;

/// One parameter of an objective type: its type and range, and whether it
/// is required.
class Param {
  const Param(this.kind, {this.required = false, this.lo = 0, this.hi = 0});

  /// int, bool, code or destination.
  final String kind;
  final bool required;
  final int lo;
  final int hi;
}

/// An objective type (ADR-P4-6's table): what it targets, its parameters,
/// and what it needs.
class ObjectiveType {
  const ObjectiveType(
    this.target,
    this.params, {
    this.needsTeam = false,
    this.needsEnd = false,
  });

  /// "objective" or "bomb_site" (a box's role), "player", or null.
  final String? target;
  final Map<String, Param> params;

  /// An assignee team is required.
  final bool needsTeam;

  /// A time window's end is required (it is judged then).
  final bool needsEnd;
}

const Param _hold = Param('int', lo: 0, hi: 600000);

/// The objective types, in the manifest's documented order.
const Map<String, ObjectiveType> objectiveTypes = {
  // Hold the target: completed when the team has held it for duration_s.
  'capture_and_hold': ObjectiveType('objective', {
    'hold_ms': _hold,
    'duration_s': Param('int', lo: 0, hi: 86400),
  }),
  // Type the code on the target's keypad.
  'enter_code': ObjectiveType('objective', {
    'code': Param('code', required: true),
  }),
  // Scan tag_count tags at the target (with any, any cards).
  'scan_tags': ObjectiveType('objective', {
    'tag_count': Param('int', required: true, lo: 1, hi: 100),
    'any': Param('bool'),
  }),
  // A player with the target's role reaches the destination.
  'escort': ObjectiveType('player', {
    'destination': Param('destination', required: true),
    'max_acc_m': Param('int', lo: 1, hi: 1000),
  }),
  // Arm the bomb at the target and let it explode; a defuse fails it.
  'destroy': ObjectiveType('bomb_site', {
    'hold_ms': _hold,
    'defuse_ms': _hold,
    'fuse_s': Param('int', lo: 10, hi: 3600),
  }),
  // Keep the target for duration_s from when the objective opens.
  'defend': ObjectiveType('objective', {
    'duration_s': Param('int', required: true, lo: 1, hi: 86400),
    'hold_ms': _hold,
  }, needsTeam: true),
  // Keep at least minimum_lives of Respawn's lives until the window's end.
  'survive': ObjectiveType(
    null,
    {'minimum_lives': Param('int', required: true, lo: 0, hi: 1000)},
    needsTeam: true,
    needsEnd: true,
  ),
};

const List<String> topKeys = [
  'id',
  'version',
  'name',
  'description',
  'author',
  'lang',
  'teams',
  'squads',
  'params',
  'i18n',
  'nodes',
  'objectives',
];
const List<String> objectiveKeys = [
  'id',
  'type',
  'name',
  'description',
  'i18n',
  'target',
  'assignee',
  'params',
  'visibility',
  'depends_on',
  'time_window',
  'effect',
];

/// The text is not a manifest at all (not YAML, not a map, too large).
class ManifestError implements Exception {
  ManifestError(this.message);

  final String message;

  @override
  String toString() => message;
}

/// A YAML 1.1 timestamp, as PyYAML reads one: a date, or a date and time
/// (with a time zone or without). No field of a manifest takes one; it only
/// has to be told apart from a text, compared as a key, and printed as
/// Python's str() prints it.
class PyTimestamp {
  PyTimestamp.date(this.year, this.month, this.day)
    : isDate = true,
      hour = 0,
      minute = 0,
      second = 0,
      microsecond = 0,
      offsetMinutes = null;

  PyTimestamp.dateTime(
    this.year,
    this.month,
    this.day,
    this.hour,
    this.minute,
    this.second,
    this.microsecond,
    this.offsetMinutes,
  ) : isDate = false;

  final bool isDate;
  final int year, month, day, hour, minute, second, microsecond;

  /// Minutes east of UTC; null for a time without a zone.
  final int? offsetMinutes;

  DateTime get _utc => DateTime.utc(
    year,
    month,
    day,
    hour,
    minute,
    second,
    0,
    microsecond,
  ).subtract(Duration(minutes: offsetMinutes ?? 0));

  @override
  bool operator ==(Object other) {
    if (other is! PyTimestamp || other.isDate != isDate) return false;
    if ((offsetMinutes == null) != (other.offsetMinutes == null)) return false;
    return _utc == other._utc;
  }

  @override
  int get hashCode => Object.hash(isDate, _utc);

  @override
  String toString() {
    String two(int n) => n.toString().padLeft(2, '0');
    final date = '${year.toString().padLeft(4, '0')}-${two(month)}-${two(day)}';
    if (isDate) return date;
    var text = '$date ${two(hour)}:${two(minute)}:${two(second)}';
    if (microsecond != 0) text += '.${microsecond.toString().padLeft(6, '0')}';
    final offset = offsetMinutes;
    if (offset != null) {
      final sign = offset < 0 ? '-' : '+';
      text += '$sign${two(offset.abs() ~/ 60)}:${two(offset.abs() % 60)}';
    }
    return text;
  }
}

// -- Python's semantics, where the port depends on them --

/// Python's str() of a manifest value, for paths such as nodes.True.
String pyStr(Object? value) => switch (value) {
  null => 'None',
  true => 'True',
  false => 'False',
  final double d => pyFloatRepr(d),
  final String s => s,
  final List<Object?> l => '[${l.map(pyRepr).join(', ')}]',
  final Map<Object?, Object?> m =>
    '{${m.entries.map((e) => '${pyRepr(e.key)}: ${pyRepr(e.value)}').join(', ')}}',
  _ => value.toString(),
};

/// Python's repr() of a value, for messages (close to Python's; messages
/// are free text).
String pyRepr(Object? value) {
  if (value is! String) return pyStr(value);
  final quote = value.contains("'") && !value.contains('"') ? '"' : "'";
  final out = StringBuffer(quote);
  for (final rune in value.runes) {
    if (rune == 0x5C) {
      out.write(r'\\');
    } else if (rune == quote.codeUnitAt(0)) {
      out.write('\\$quote');
    } else if (rune == 0x0A) {
      out.write(r'\n');
    } else if (rune == 0x0D) {
      out.write(r'\r');
    } else if (rune == 0x09) {
      out.write(r'\t');
    } else if (rune < 0x20 || rune == 0x7F) {
      out.write('\\x${rune.toRadixString(16).padLeft(2, '0')}');
    } else {
      out.writeCharCode(rune);
    }
  }
  out.write(quote);
  return out.toString();
}

/// Python's repr() of a float: the shortest text that reads back the same,
/// in exponent form below 1e-4 and from 1e16 on (1e-05, 1e+16), else with
/// at least one decimal (38.0).
String pyFloatRepr(double value) {
  if (value.isNaN) return 'nan';
  if (value.isInfinite) return value > 0 ? 'inf' : '-inf';
  final sign = (value < 0 || (value == 0 && value.isNegative)) ? '-' : '';
  if (value == 0) return '${sign}0.0';
  // Dart's shortest round trip, as d.ddde[+-]x; Python's repr is the same
  // shortest digits (David Gay's algorithm), only written differently.
  final exp = value.abs().toStringAsExponential();
  final e = exp.indexOf('e');
  final digits = exp.substring(0, e).replaceAll('.', '');
  final exponent = int.parse(exp.substring(e + 1));
  final point = exponent + 1; // digits are 0.ddd * 10^point
  if (point <= -4 || point > 16) {
    final mantissa = digits.length > 1
        ? '${digits[0]}.${digits.substring(1)}'
        : digits;
    final esign = exponent < 0 ? '-' : '+';
    return '$sign${mantissa}e$esign${exponent.abs().toString().padLeft(2, '0')}';
  }
  if (point <= 0) return '${sign}0.${'0' * -point}$digits';
  if (point >= digits.length) {
    return '$sign$digits${'0' * (point - digits.length)}.0';
  }
  return '$sign${digits.substring(0, point)}.${digits.substring(point)}';
}

/// Python's truth of a value: None, False, 0, "" and empty lists and maps
/// are false.
bool pyTruthy(Object? value) => switch (value) {
  null => false,
  final bool b => b,
  final int i => i != 0,
  final double d => d != 0,
  final BigInt b => b != BigInt.zero,
  final String s => s.isNotEmpty,
  final List<Object?> l => l.isNotEmpty,
  final Map<Object?, Object?> m => m.isNotEmpty,
  _ => true,
};

/// Python's dict.get(key, default): the default only when the key is
/// absent (a key given as null is null).
Object? pyGet(Object? map, Object? key, [Object? fallback]) {
  if (map is! Map<Object?, Object?>) return fallback;
  return map.containsKey(key) ? map[key] : fallback;
}

/// Whether a value is a Python int (an int or a BigInt, never a bool).
bool pyIsInt(Object? value) => value is int || value is BigInt;

/// Python's == between two manifest values: numbers by value (True == 1 ==
/// 1.0), texts and the rest as Dart compares them.
bool pyEq(Object? a, Object? b) {
  final ka = _numKey(a), kb = _numKey(b);
  if (ka != null || kb != null) return ka != null && kb != null && ka == kb;
  if (a is List<Object?> && b is List<Object?>) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (!pyEq(a[i], b[i])) return false;
    }
    return true;
  }
  if (a is Map<Object?, Object?> && b is Map<Object?, Object?>) {
    if (a.length != b.length) return false;
    for (final key in a.keys) {
      if (!pyHasKey(b, key) || !pyEq(a[key], pyLookup(b, key))) return false;
    }
    return true;
  }
  return a == b;
}

/// Python's `key in map`, with Python's equality of keys.
bool pyHasKey(Map<Object?, Object?> map, Object? key) =>
    map.containsKey(key) || map.keys.any((k) => pyEq(k, key));

/// Python's map[key], with Python's equality of keys.
Object? pyLookup(Map<Object?, Object?> map, Object? key) {
  if (map.containsKey(key)) return map[key];
  for (final entry in map.entries) {
    if (pyEq(entry.key, key)) return entry.value;
  }
  return null;
}

/// A number as one exact value (bool, int, BigInt, an integral double), or
/// the double itself; null for anything else.
Object? _numKey(Object? v) {
  if (v is bool) return BigInt.from(v ? 1 : 0);
  if (v is int) return BigInt.from(v);
  if (v is BigInt) return v;
  if (v is double) {
    if (v.isFinite && v == v.truncateToDouble()) return BigInt.from(v);
    return v;
  }
  return null;
}

/// The UTF-8 length of a text, as Python's len(text.encode()).
int utf8Length(String text) => utf8.encode(text).length;

/// The length of a text in code points, as Python's len(text).
int pyLen(String text) => text.runes.length;

// Python's str.isspace() characters (str.strip() removes them).
bool _pySpace(int c) =>
    (c >= 0x09 && c <= 0x0D) ||
    (c >= 0x1C && c <= 0x20) ||
    c == 0x85 ||
    c == 0xA0 ||
    c == 0x1680 ||
    (c >= 0x2000 && c <= 0x200A) ||
    c == 0x2028 ||
    c == 0x2029 ||
    c == 0x202F ||
    c == 0x205F ||
    c == 0x3000;

/// Whether Python's text.strip() is empty.
bool pyBlank(String text) => text.runes.every(_pySpace);

/// A text in the language: `i18n.<lang>.<key>`, else the English one.
String? translated(
  Map<Object?, Object?> entry,
  Object? lang, [
  String key = 'name',
]) {
  if (lang != 'en') {
    final i18n = entry['i18n'];
    if (i18n is Map<Object?, Object?>) {
      final strings = pyLookup(i18n, lang);
      if (pyHasKey(i18n, lang) && strings is Map<Object?, Object?>) {
        final value = strings[key];
        if (value is String && value.isNotEmpty) return value;
      }
    }
  }
  final value = entry[key];
  return value is String ? value : null;
}

/// An objective's visibility when the manifest gives none.
String defaultVisibility(Map<Object?, Object?> objective) {
  final raw = objective['assignee'];
  final assignee = pyTruthy(raw) ? raw : const <Object?, Object?>{};
  if (assignee is Map<Object?, Object?> && assignee['squad'] != null) {
    return 'squad';
  }
  if (assignee is Map<Object?, Object?> && assignee['team'] != null) {
    return 'team';
  }
  return 'public';
}

// -- Reading the text --

/// The manifest in a YAML or JSON text. [ManifestError] when it is not one.
Map<Object?, Object?> loadText(String text) {
  if (utf8Length(text) > manifestMaxBytes) {
    throw ManifestError('the manifest is larger than $manifestMaxBytes bytes');
  }
  for (final rune in text.runes) {
    if (!_printable(rune)) {
      throw ManifestError(
        'not valid YAML: unacceptable character '
        '#x${rune.toRadixString(16).padLeft(4, '0')}: special characters '
        'are not allowed',
      );
    }
    if (rune == 0x85 || rune == 0x2028 || rune == 0x2029) {
      throw ManifestError(
        'not valid YAML: a raw NEL, line separator or paragraph separator '
        '(write it as an escape in a double-quoted text)',
      );
    }
  }
  // A character past U+FFFF written as two escapes, a surrogate pair (as
  // JSON writes one when it keeps to ASCII): PyYAML reads each half and the
  // Pi's loader joins them; package:yaml refuses a surrogate escape, so the
  // pair is written as the one \U escape it means first (decision PE24-107).
  // Escapes are YAML's only in double-quoted texts: the quick way joins
  // every pair and keeps the result when no other text held one; else each
  // pair is joined where package:yaml stops at it.
  final (joined, at) = _joinSurrogateEscapes(text);
  if (at.isNotEmpty) {
    try {
      final (data, literal) = _read(joined, retry: false);
      if (!at.any((j) => literal.any((s) => j.$1 < s.$2 && s.$1 < j.$2))) {
        return data;
      }
    } on ManifestError {
      // The text as it is says why.
    }
  }
  return _read(text, retry: true).$1;
}

/// The manifest in [text], and where its texts that are not double-quoted
/// are (offsets). With [retry], a surrogate pair's escape that package:yaml
/// stops at is joined and the text read again.
(Map<Object?, Object?>, List<(int, int)>) _read(
  String text, {
  required bool retry,
}) {
  YamlDocument? document;
  while (document == null) {
    try {
      document = loadYamlDocument(text);
    } on YamlException catch (e) {
      final at = e.span?.start.offset;
      if (at != null && _surrogateEscape.matchAsPrefix(text, at) != null) {
        final pair = retry ? _pairAt(text, at) : null;
        if (pair == null) {
          throw ManifestError(
            'not valid YAML: ${text.substring(at, at + (text[at + 1] == 'u' ? 6 : 10))} '
            'is half of a surrogate pair; a character past U+FFFF is written '
            r'as both halves (\ud83d\ude00), as \U0001F600, or as it is',
          );
        }
        text = text.replaceRange(at, pair.$2, _bigEscape(pair.$1));
        continue;
      }
      throw ManifestError('not valid YAML: ${e.message}');
    } catch (e) {
      // package:yaml can also fail with an Error (a RangeError on !!float 1).
      throw ManifestError('not valid YAML: $e');
    }
  }
  if (document.tagDirectives.isNotEmpty) {
    throw ManifestError('not valid YAML: %TAG directives are not accepted');
  }
  final reader = _Reader();
  final data = reader.node(document.contents);
  _checkTabs(text, reader.quoted);
  if (data is! Map<Object?, Object?>) {
    throw ManifestError(
      'a scenario manifest is a map (id, version, name, nodes, objectives, '
      '...)',
    );
  }
  return (data, reader.literal);
}

// A YAML escape of a surrogate (\uD83D, \U0000D83D), of a high one, and a
// low one after the escaped line breaks that a double-quoted text drops.
final RegExp _surrogateEscape = RegExp(
  r'\\(?:u[dD][89a-fA-F][0-9a-fA-F]{2}|U0000[dD][89a-fA-F][0-9a-fA-F]{2})',
);
final RegExp _highEscape = RegExp(
  r'\\(?:u[dD][89abAB][0-9a-fA-F]{2}|U0000[dD][89abAB][0-9a-fA-F]{2})',
);
final RegExp _lowEscape = RegExp(
  r'(?:\\(?:\r\n|\r|\n)[ \t]*)*'
  r'\\(?:u[dD][c-fC-F][0-9a-fA-F]{2}|U0000[dD][c-fC-F][0-9a-fA-F]{2})',
);

/// The character of a surrogate pair whose high half's escape starts at
/// [at], and where its low half's escape ends; null without a low half.
(int, int)? _pairAt(String text, int at) {
  final high = _highEscape.matchAsPrefix(text, at);
  if (high == null) return null;
  final low = _lowEscape.matchAsPrefix(text, high.end);
  if (low == null) return null;
  int half(String escape) =>
      int.parse(escape.substring(escape.length - 4), radix: 16);
  final code =
      0x10000 + ((half(high[0]!) - 0xD800) << 10) + (half(low[0]!) - 0xDC00);
  return (code, low.end);
}

String _bigEscape(int code) => '\\U${code.toRadixString(16).padLeft(8, '0')}';

/// Every surrogate pair's escape (not after an escaped backslash) written as
/// one \U escape, and where the new escapes are.
(String, List<(int, int)>) _joinSurrogateEscapes(String text) {
  if (!text.contains(r'\')) return (text, const []);
  final out = StringBuffer();
  final at = <(int, int)>[];
  var done = 0;
  for (final m in _highEscape.allMatches(text)) {
    if (m.start < done) continue;
    var slashes = 0;
    for (var i = m.start - 1; i >= 0 && text.codeUnitAt(i) == 0x5C; i--) {
      slashes++;
    }
    final pair = slashes.isEven ? _pairAt(text, m.start) : null;
    if (pair == null) continue;
    out.write(text.substring(done, m.start));
    final start = out.length;
    out.write(_bigEscape(pair.$1));
    at.add((start, out.length));
    done = pair.$2;
  }
  out.write(text.substring(done));
  return (out.toString(), at);
}

// PyYAML's reader: what it accepts in a stream (reader.py, NON_PRINTABLE).
bool _printable(int c) =>
    c == 0x09 ||
    c == 0x0A ||
    c == 0x0D ||
    (c >= 0x20 && c <= 0x7E) ||
    c == 0x85 ||
    (c >= 0xA0 && c <= 0xD7FF) ||
    (c >= 0xE000 && c <= 0xFFFD) ||
    (c >= 0x10000 && c <= 0x10FFFF);

const _yamlTag = 'tag:yaml.org,2002:';

/// Reads package:yaml's nodes as PyYAML's safe loader would have built
/// them. An anchored node read twice (an alias) is the same Dart object, as
/// in Python.
class _Reader {
  final Map<YamlNode, Object?> _done = Map.identity();

  /// Where the quoted and block texts are (offsets), for [_checkTabs].
  final List<(int, int)> quoted = [];

  /// Where the texts that are not double-quoted are (offsets): YAML reads no
  /// escape in them ([loadText]).
  final List<(int, int)> literal = [];

  Object? node(YamlNode node) {
    if (_done.containsKey(node)) return _done[node];
    final props = _properties(node.span.text);
    final tag = props.tag;
    if (node is YamlMap) {
      if (tag != null && tag != '!' && tag != '${_yamlTag}map') {
        throw ManifestError('not valid YAML: the tag $tag is not accepted');
      }
      final out = <Object?, Object?>{};
      _done[node] = out;
      final seen = <_Key>{};
      for (final (k, v) in _flatten(node)) {
        final key = k is YamlNode ? this.node(k) : k;
        if (key is Map || key is List) {
          throw ManifestError(
            'not valid YAML: found unhashable key ${pyRepr(key)}',
          );
        }
        if (!seen.add(_Key(key))) {
          throw ManifestError(
            'not valid YAML: the key ${pyRepr(key)} is given twice',
          );
        }
        out[key] = this.node(v);
      }
      return out;
    }
    if (node is YamlList) {
      if (tag != null && tag != '!' && tag != '${_yamlTag}seq') {
        throw ManifestError('not valid YAML: the tag $tag is not accepted');
      }
      final out = <Object?>[];
      _done[node] = out;
      for (final item in node.nodes) {
        out.add(this.node(item));
      }
      return out;
    }
    final scalar = node as YamlScalar;
    if (scalar.style != ScalarStyle.PLAIN) {
      quoted.add((scalar.span.start.offset, scalar.span.end.offset));
    }
    if (scalar.style != ScalarStyle.DOUBLE_QUOTED) {
      literal.add((scalar.span.start.offset, scalar.span.end.offset));
    }
    final value = _scalar(scalar, props);
    if (value is _Marker) {
      throw ManifestError(
        'not valid YAML: could not determine a constructor for the tag '
        "'$_yamlTag${value.name}'",
      );
    }
    _done[node] = value;
    return value;
  }

  /// The pairs of a map with its merge keys merged (PyYAML's
  /// flatten_mapping): merged pairs first, a list's maps last to first. A
  /// key is a node, or the text "=" that a plain = key is.
  List<(Object, YamlNode)> _flatten(YamlMap map) {
    final merged = <(Object, YamlNode)>[];
    final rest = <(Object, YamlNode)>[];
    map.nodes.forEach((k, v) {
      final key = k as YamlNode;
      final raw = key is YamlScalar
          ? _scalar(key, _properties(key.span.text))
          : null;
      if (raw == _merge) {
        if (v is YamlMap) {
          merged.addAll(_flatten(v));
        } else if (v is YamlList) {
          final maps = <List<(Object, YamlNode)>>[];
          for (final item in v.nodes) {
            if (item is! YamlMap) {
              throw ManifestError(
                'not valid YAML: expected a mapping for merging',
              );
            }
            maps.add(_flatten(item));
          }
          for (final pairs in maps.reversed) {
            merged.addAll(pairs);
          }
        } else {
          throw ManifestError(
            'not valid YAML: expected a mapping or list of mappings for '
            'merging',
          );
        }
      } else if (raw == _value) {
        rest.add(('=', v));
      } else {
        rest.add((key, v));
      }
    });
    return [...merged, ...rest];
  }

  Object? _scalar(YamlScalar scalar, _Props props) {
    final tag = props.tag;
    final value = scalar.value;
    if (tag == null) {
      if (scalar.style != ScalarStyle.PLAIN) return value;
      return _resolve(value is String ? value : props.rest);
    }
    if (tag == '!') {
      // PyYAML reads a value with the non-specific tag as a plain one, even
      // when it is quoted (! "12" is 12).
      return _resolve(value is String ? value : props.rest);
    }
    if (tag == '${_yamlTag}str') return value is String ? value : props.rest;
    if (scalar.style != ScalarStyle.PLAIN) {
      throw ManifestError('not valid YAML: a quoted value with the tag $tag');
    }
    final raw = props.rest;
    try {
      return switch (tag) {
        '${_yamlTag}int' => _constructInt(raw),
        '${_yamlTag}float' => _constructFloat(raw),
        '${_yamlTag}bool' => switch (raw.toLowerCase()) {
          'yes' || 'true' || 'on' => true,
          'no' || 'false' || 'off' => false,
          _ => throw const FormatException('not a bool'),
        },
        '${_yamlTag}null' => null,
        _ => throw ManifestError(
          'not valid YAML: the tag $tag is not accepted',
        ),
      };
    } on FormatException {
      throw ManifestError('not valid YAML: $raw is not a $tag');
    }
  }
}

/// PyYAML takes a tab only inside a quoted or block text, or a comment (its
/// scanner skips spaces only): any other tab is refused here.
void _checkTabs(String text, List<(int, int)> quoted) {
  if (!text.contains('\t')) return;
  final inQuoted = List<bool>.filled(text.length, false);
  for (final (start, end) in quoted) {
    inQuoted.fillRange(start, end, true);
  }
  var lineStart = 0;
  var comment = false;
  for (var i = 0; i < text.length; i++) {
    final c = text.codeUnitAt(i);
    if (c == 0x0A) {
      lineStart = i + 1;
      comment = false;
      continue;
    }
    if (comment || inQuoted[i]) continue;
    if (c == 0x23 && (i == lineStart || ' \t'.contains(text[i - 1]))) {
      comment = true;
    } else if (c == 0x09) {
      throw ManifestError(
        'not valid YAML: a tab outside a quoted text or a comment (YAML '
        'indents and separates with spaces)',
      );
    }
  }
}

/// A node's properties: its tag (resolved to a full tag, '!' for the
/// non-specific one) and the text after them.
class _Props {
  const _Props(this.tag, this.rest);

  final String? tag;
  final String rest;
}

_Props _properties(String span) {
  var text = span;
  String? tag;
  while (text.startsWith('&') || text.startsWith('!')) {
    var end = 0;
    while (end < text.length && !' \t\r\n,[]{}'.contains(text[end])) {
      end++;
    }
    final token = text.substring(0, end);
    if (token.startsWith('!')) {
      if (token == '!') {
        tag = '!';
      } else if (token.startsWith('!!')) {
        tag = '$_yamlTag${token.substring(2)}';
      } else if (token.startsWith('!<') && token.endsWith('>')) {
        tag = token.substring(2, token.length - 1);
      } else {
        tag = token;
      }
    }
    text = text.substring(end).trimLeft();
  }
  // A span can run on past its scalar (the spaces before a flow map's }, a
  // comment). Only YAML's own white space ends a plain scalar: Dart's
  // int.tryParse, which package:yaml uses, also skips Unicode spaces ("1
  // \u3000" is 1 to it, a text to PyYAML).
  final comment = text.indexOf(RegExp(r'[ \t]#'));
  final word = comment < 0 ? text : text.substring(0, comment);
  return _Props(tag, word.replaceFirst(RegExp(r'[ \t\r\n]+$'), ''));
}

// What a plain scalar is in PyYAML (resolver.py: bool, float, int, merge,
// null, timestamp, value, in that order). Each "$" also matches before a
// final newline, as Python's.
final RegExp _bool = RegExp(
  r'^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)\n?$',
);
final RegExp _float = RegExp(
  r'^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?'
  r'|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?' // PyYAML 6 (5 had \.[0-9_]+)
  r'|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*'
  r'|[-+]?\.(?:inf|Inf|INF)'
  r'|\.(?:nan|NaN|NAN))\n?$',
);
final RegExp _int = RegExp(
  r'^(?:[-+]?0b[0-1_]+'
  r'|[-+]?0[0-7_]+'
  r'|[-+]?(?:0|[1-9][0-9_]*)'
  r'|[-+]?0x[0-9a-fA-F_]+'
  r'|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)\n?$',
);
final RegExp _null = RegExp(r'^(?:~|null|Null|NULL|)\n?$');
final RegExp _timestamp = RegExp(
  r'^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
  r'|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?'
  r'(?:[Tt]|[ \t]+)[0-9][0-9]?'
  r':[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?'
  r'(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)\n?$',
);
final RegExp _timestampParts = RegExp(
  r'^([0-9][0-9][0-9][0-9])-([0-9][0-9]?)-([0-9][0-9]?)'
  r'(?:(?:[Tt]|[ \t]+)([0-9][0-9]?):([0-9][0-9]):([0-9][0-9])'
  r'(?:\.([0-9]*))?'
  r'(?:[ \t]*(Z|([-+])([0-9][0-9]?)(?::([0-9][0-9]))?))?)?\n?$',
);

/// Markers for the two plain scalars that are not values.
const Object _merge = _Marker('<<');
const Object _value = _Marker('=');

class _Marker {
  const _Marker(this.name);

  final String name;
}

/// The YAML 1.1 tag PyYAML gives a plain text: 'bool', 'float', 'int',
/// 'merge', 'null', 'timestamp', 'value', or 'str'.
String pyYamlKind(String text) {
  if (text.isNotEmpty) {
    final first = text[0];
    if ('yYnNtTfFoO'.contains(first) && _bool.hasMatch(text)) return 'bool';
    if ('-+0123456789.'.contains(first) && _float.hasMatch(text)) {
      return 'float';
    }
    if ('-+0123456789'.contains(first) && _int.hasMatch(text)) return 'int';
    if (text == '<<') return 'merge';
  }
  if ((text.isEmpty || '~nN'.contains(text[0])) && _null.hasMatch(text)) {
    return 'null';
  }
  if (text.isNotEmpty &&
      '0123456789'.contains(text[0]) &&
      _timestamp.hasMatch(text)) {
    return 'timestamp';
  }
  if (text == '=') return 'value';
  return 'str';
}

Object? _resolve(String text) => switch (pyYamlKind(text)) {
  'bool' => const {
    'yes': true,
    'true': true,
    'on': true,
    'no': false,
    'false': false,
    'off': false,
  }[text.toLowerCase().trim()],
  'float' => _constructFloat(text),
  'int' => _constructInt(text),
  'merge' => _merge,
  'null' => null,
  'timestamp' => _constructTimestamp(text),
  'value' => _value,
  _ => text,
};

/// PyYAML's construct_yaml_int, with Python's int(): any size.
Object _constructInt(String text) {
  var value = text.replaceAll('_', '');
  var sign = BigInt.one;
  if (value.startsWith('-')) sign = -BigInt.one;
  if (value.startsWith('-') || value.startsWith('+')) {
    value = value.substring(1);
  }
  BigInt result;
  if (value == '0') {
    result = BigInt.zero;
  } else if (value.startsWith('0b')) {
    result = _parseBig(value.substring(2), 2);
  } else if (value.startsWith('0x')) {
    result = _parseBig(value.substring(2), 16);
  } else if (value.startsWith('0')) {
    final digits = value.startsWith('0o') || value.startsWith('0O')
        ? value.substring(2)
        : value;
    result = _parseBig(digits, 8);
  } else if (value.contains(':')) {
    result = BigInt.zero;
    for (final part in value.split(':')) {
      result = result * BigInt.from(60) + _parseBig(part, 10);
    }
  } else {
    result = _parseBig(value, 10);
  }
  return normalInt(sign * result);
}

BigInt _parseBig(String digits, int radix) {
  final parsed = digits.isEmpty ? null : BigInt.tryParse(digits, radix: radix);
  if (parsed == null || digits.startsWith('-') || digits.startsWith('+')) {
    throw ManifestError('not valid YAML: $digits is not a base-$radix number');
  }
  return parsed;
}

/// An integer as an int when it fits 64 bits, else as a BigInt.
Object normalInt(BigInt value) => value.isValidInt ? value.toInt() : value;

/// PyYAML's construct_yaml_float, with Python's float().
double _constructFloat(String text) {
  var value = text.replaceAll('_', '').toLowerCase();
  var sign = 1.0;
  if (value.startsWith('-')) sign = -1.0;
  if (value.startsWith('-') || value.startsWith('+')) {
    value = value.substring(1);
  }
  if (value == '.inf') return sign * double.infinity;
  if (value == '.nan') return double.nan;
  if (value.contains(':')) {
    var result = 0.0;
    var base = 1.0;
    for (final part in value.split(':').reversed) {
      result += _parseFloat(part) * base;
      base *= 60;
    }
    return sign * result;
  }
  return sign * _parseFloat(value);
}

double _parseFloat(String text) {
  // Python's float() takes "1." and ".5"; Dart's double.parse may not.
  var t = text;
  if (t.startsWith('.')) t = '0$t';
  t = t.replaceFirst(RegExp(r'\.(?=e|$)'), '.0');
  final parsed = double.tryParse(t);
  if (parsed == null || t.isEmpty || !RegExp(r'^[0-9.e+-]+$').hasMatch(t)) {
    throw ManifestError('not valid YAML: $text is not a float');
  }
  return parsed;
}

PyTimestamp _constructTimestamp(String text) {
  final m = _timestampParts.firstMatch(text);
  if (m == null) throw ManifestError('not valid YAML: $text is not a date');
  final year = int.parse(m[1]!), month = int.parse(m[2]!);
  final day = int.parse(m[3]!);
  final daysIn = DateTime.utc(year, month + 1, 0).day;
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > daysIn) {
    throw ManifestError('not valid YAML: $text is not a date');
  }
  if (m[4] == null) return PyTimestamp.date(year, month, day);
  final hour = int.parse(m[4]!), minute = int.parse(m[5]!);
  final second = int.parse(m[6]!);
  if (hour > 23 || minute > 59 || second > 59) {
    throw ManifestError('not valid YAML: $text is not a time');
  }
  var micro = 0;
  final fraction = m[7];
  if (fraction != null && fraction.isNotEmpty) {
    final six = fraction.length > 6 ? fraction.substring(0, 6) : fraction;
    micro = int.parse(six.padRight(6, '0'));
  }
  int? offset;
  if (m[9] != null) {
    final hours = int.parse(m[10]!), minutes = int.parse(m[11] ?? '0');
    if (hours * 60 + minutes >= 24 * 60) {
      throw ManifestError('not valid YAML: $text has no valid time zone');
    }
    offset = (hours * 60 + minutes) * (m[9] == '-' ? -1 : 1);
  } else if (m[8] != null) {
    offset = 0;
  }
  return PyTimestamp.dateTime(
    year,
    month,
    day,
    hour,
    minute,
    second,
    micro,
    offset,
  );
}

/// A key as Python compares keys in a dict: numbers by value.
class _Key {
  _Key(Object? key)
    : value = _numKey(key) ?? key,
      isNan = key is double && key.isNaN;

  final Object? value;
  final bool isNan;

  @override
  bool operator ==(Object other) =>
      other is _Key && !isNan && !other.isNan && value == other.value;

  @override
  int get hashCode => value.hashCode;
}
