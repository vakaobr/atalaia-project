// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The registration import's format on the phone controller: reading a CSV or
/// JSON list and checking each row, a port of
/// controller/atalaia_controller/import_format.py (which the site server
/// re-exports; ADR-P4-12, plan phase 17, decisions F20, S17-*; PKE-1). Plain
/// Dart, no controller: the same cases (protocol/vectors/registration_import.json)
/// run against this file and the Python one, so a list reads the same on the
/// site server, on the Pi and on the phone.
///
/// A CSV file (RFC 4180, UTF-8, a header row, an optional byte order mark) or a
/// JSON array of objects, with only the five [importColumns]; any other column
/// is not read (its name is listed, its values never leave this file). A file
/// is refused whole ([ImportFileError]) when it is not what it says; a row is
/// refused on its own ([ImportRowError], with a code) when a value is not valid.
/// At most [importMaxBytes] (1 MiB) and [importMaxRows] (5,000) rows.
///
/// The CSV reader follows Python's `csv` module (strict, "excel" dialect): a
/// quote inside an unquoted field is kept, text after a closing quote is an
/// error, a lone CR, LF or CRLF ends a record, a blank line is skipped, a field
/// over 131072 characters is an error.
library;

import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

const importColumns = [
  'display_name',
  'external_ref',
  'team_preference',
  'federation_number',
  'replicas',
];
const importMaxBytes = 1024 * 1024;
const importMaxRows = 5000;
const _nameMax = 32;
const _refMax = 128;
const _teamMax = 32;
const _federationMax = 32;
const _makeModelMax = 64;
const _maxReplicas = 20;
const _maxIgnored = 50;
const _csvFieldLimit = 131072;
const _jsonMaxDepth = 900;
const _formulaStart = '=+-@\t\r';
const importReplicaTypes = [
  'aeg',
  'gbb',
  'hpa',
  'bolt_action',
  'dmr',
  'sniper',
  'pistol',
  'shotgun',
];
final _sourceRe = RegExp(r'^[a-z0-9][a-z0-9._-]{0,31}$');
const _reservedSources = {'site'};

/// The whole file is refused: [code] is the API's `detail`, [line] where it
/// went wrong in a CSV, if known.
class ImportFileError implements Exception {
  ImportFileError(this.code, [this.line]);
  final String code;
  final int? line;
  @override
  String toString() => code;
}

/// One row is refused (the other rows still go in).
class ImportRowError implements Exception {
  ImportRowError(this.code);
  final String code;
  @override
  String toString() => code;
}

/// A row as read: [values] holds only the listed columns that were present,
/// as strings (CSV) or JSON values; [error] is set for a row that could not
/// even be read.
class RawRow {
  RawRow(this.number, this.values, [this.error]);
  final int number;
  final Map<String, Object?> values;
  final String? error;
}

class ParsedImport {
  ParsedImport(
    this.format,
    this.columns,
    this.ignored,
    this.ignoredMore,
    this.rows,
  );
  final String format;
  final List<String> columns;
  final List<String> ignored;
  final int ignoredMore;
  final List<RawRow> rows;
}

/// What the game and its field accept.
class ImportRules {
  const ImportRules({
    required this.teams,
    required this.federation,
    required this.predeclareReplicas,
    required this.classes,
    required this.maxReplicas,
  });
  final List<String> teams;
  final String federation; // off, optional, required
  final bool predeclareReplicas;
  final List<String> classes;
  final int maxReplicas;
}

/// A checked row: the values to store, which columns the file had (an update
/// changes only those), and warnings.
class ImportRow {
  ImportRow({
    required this.number,
    required this.displayName,
    required this.externalRef,
    required this.teamPreference,
    required this.federationNumber,
    required this.replicas,
    required this.present,
    required this.warnings,
  });
  final int number;
  final String displayName;
  final String? externalRef;
  final String? teamPreference;
  final String? federationNumber;

  /// null: no replicas column in the file.
  final List<Map<String, String?>>? replicas;
  final Set<String> present;
  final List<String> warnings;
}

// --- formula injection --------------------------------------------------------

/// A cell for an exported CSV: a leading `'` when a spreadsheet would read it
/// as a formula.
String csvSafe(String? value) {
  if (value == null || value.isEmpty) return '';
  return _formulaStart.contains(value[0]) ? "'$value" : value;
}

/// The import's inverse of [csvSafe]: `'=1` reads as `=1`; any other `'`
/// stays.
String csvUnsafe(String value) {
  if (value.length >= 2 &&
      value[0] == "'" &&
      _formulaStart.contains(value[1])) {
    return value.substring(1);
  }
  return value;
}

// --- reading ------------------------------------------------------------------

/// The import's source label: 1-32 of a-z, 0-9 and `. _ -`, not `site`.
String checkImportSource(Object? value) {
  if (value is! String ||
      !_sourceRe.hasMatch(value) ||
      _reservedSources.contains(value)) {
    throw ImportFileError('source_invalid');
  }
  return value;
}

// Python's str.strip() / str.isspace() set (not Dart's trim(), which also
// strips U+FEFF and does not strip U+001C-001F).
bool _isSpace(int c) =>
    (c >= 0x09 && c <= 0x0d) ||
    (c >= 0x1c && c <= 0x20) ||
    c == 0x85 ||
    c == 0xa0 ||
    c == 0x1680 ||
    (c >= 0x2000 && c <= 0x200a) ||
    c == 0x2028 ||
    c == 0x2029 ||
    c == 0x202f ||
    c == 0x205f ||
    c == 0x3000;

String _strip(String s) {
  var a = 0;
  var b = s.length;
  while (a < b && _isSpace(s.codeUnitAt(a))) {
    a++;
  }
  while (b > a && _isSpace(s.codeUnitAt(b - 1))) {
    b--;
  }
  return s.substring(a, b);
}

String _decode(Uint8List data) {
  if (data.length > importMaxBytes) throw ImportFileError('too_large');
  String text;
  try {
    text = const Utf8Decoder(allowMalformed: false).convert(data);
  } on FormatException {
    throw ImportFileError('encoding_invalid');
  }
  if (text.startsWith('﻿')) text = text.substring(1);
  if (text.contains('\u0000')) throw ImportFileError('encoding_invalid');
  return text;
}

/// The input as UTF-8 bytes, or null when a string has a lone surrogate (the
/// Python side cannot encode it either: `encoding_invalid`).
Uint8List? importBytes(String text) {
  for (var i = 0; i < text.length; i++) {
    final c = text.codeUnitAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      if (i + 1 < text.length &&
          text.codeUnitAt(i + 1) >= 0xdc00 &&
          text.codeUnitAt(i + 1) <= 0xdfff) {
        i++;
        continue;
      }
      return null;
    }
    if (c >= 0xdc00 && c <= 0xdfff) return null;
  }
  return Uint8List.fromList(utf8.encode(text));
}

({Map<String, int> known, List<String> ignored}) _splitColumns(
  Iterable<String> names,
) {
  final known = <String, int>{};
  final ignored = <String>[];
  var index = 0;
  for (final raw in names) {
    final name = _strip(raw).toLowerCase();
    if (importColumns.contains(name)) {
      if (known.containsKey(name)) throw ImportFileError('column_twice');
      known[name] = index;
    } else {
      final shown = _strip(raw);
      ignored.add(shown.isEmpty ? '(column ${index + 1})' : shown);
    }
    index++;
  }
  if (!known.containsKey('display_name')) {
    throw ImportFileError('display_name_column_missing');
  }
  return (known: known, ignored: ignored);
}

/// The records of a CSV text, one at a time (so a refusal of the header or
/// the row count comes before a bad quote further down, as in Python).
Iterable<List<String>> _csvRecords(String text) sync* {
  const startRecord = 0;
  const startField = 1;
  const inField = 2;
  const inQuoted = 3;
  const quoteInQuoted = 4;
  var state = startRecord;
  var fields = <String>[];
  final field = StringBuffer();
  var fieldLen = 0;
  var terms = 0; // line terminators passed (CRLF counts once)
  var prevCr = false;
  var lastHigh = false;

  void add(String ch) {
    final c = ch.codeUnitAt(0);
    if (!(c >= 0xdc00 && c <= 0xdfff && lastHigh)) fieldLen++;
    lastHigh = c >= 0xd800 && c <= 0xdbff;
    if (fieldLen > _csvFieldLimit) {
      throw ImportFileError('csv_invalid', terms + 1);
    }
    field.write(ch);
  }

  void save() {
    fields.add(field.toString());
    field.clear();
    fieldLen = 0;
    lastHigh = false;
  }

  for (var i = 0; i < text.length; i++) {
    final ch = text[i];
    if (ch == '\n' || ch == '\r') {
      if (ch == '\n' && prevCr) {
        // The LF of a CRLF: the line is already counted, and outside quotes
        // the record already ended.
        prevCr = false;
        if (state == inQuoted) add(ch);
        continue;
      }
      terms++;
      prevCr = ch == '\r';
      switch (state) {
        case startRecord:
          yield <String>[];
        case startField:
        case inField:
        case quoteInQuoted:
          save();
          yield fields;
          fields = <String>[];
          state = startRecord;
        case inQuoted:
          add(ch);
      }
      continue;
    }
    prevCr = false;
    switch (state) {
      case startRecord:
      case startField:
        if (ch == '"') {
          state = inQuoted;
        } else if (ch == ',') {
          save();
          state = startField;
        } else {
          add(ch);
          state = inField;
        }
      case inField:
        if (ch == ',') {
          save();
          state = startField;
        } else {
          add(ch);
        }
      case inQuoted:
        if (ch == '"') {
          state = quoteInQuoted;
        } else {
          add(ch);
        }
      case quoteInQuoted:
        if (ch == '"') {
          add('"');
          state = inQuoted;
        } else if (ch == ',') {
          save();
          state = startField;
        } else {
          throw ImportFileError('csv_invalid', terms + 1);
        }
    }
  }
  if (state == inQuoted) {
    final endsInTerm = text.endsWith('\n') || text.endsWith('\r');
    throw ImportFileError('csv_invalid', endsInTerm ? terms : terms + 1);
  }
  if (state != startRecord) {
    save();
    yield fields;
  }
}

ParsedImport parseCsv(Uint8List data) {
  final text = _decode(data);
  final it = _csvRecords(text).iterator;
  if (!it.moveNext()) throw ImportFileError('empty');
  final header = it.current;
  final split = _splitColumns(header);
  final rows = <RawRow>[];
  var number = 1;
  while (it.moveNext()) {
    final record = it.current;
    number++;
    if (record.isEmpty || (record.length == 1 && record[0].isEmpty)) continue;
    if (rows.length >= importMaxRows) throw ImportFileError('too_many_rows');
    if (record.length != header.length) {
      rows.add(RawRow(number, const {}, 'row_length'));
      continue;
    }
    rows.add(
      RawRow(number, {
        for (final e in split.known.entries) e.key: csvUnsafe(record[e.value]),
      }),
    );
  }
  final ignored = split.ignored;
  return ParsedImport(
    'csv',
    [
      for (final c in importColumns)
        if (split.known.containsKey(c)) c,
    ],
    ignored.take(_maxIgnored).toList(),
    max(ignored.length - _maxIgnored, 0),
    rows,
  );
}

/// A JSON integer, kept as the digits' value (any size) until a text is made
/// of it.
class _JsonInt {
  _JsonInt(this.value);
  final BigInt value;
}

class _JsonFail implements Exception {}

/// A strict JSON reader (RFC 8259) that refuses an object with a key twice,
/// which `jsonDecode` would silently accept (Python's reader is given a hook
/// that does the same).
class _JsonReader {
  _JsonReader(this.s);
  final String s;
  int i = 0;

  Object? readDocument() {
    _ws();
    final v = _value(0);
    _ws();
    if (i != s.length) throw _JsonFail();
    return v;
  }

  void _ws() {
    while (i < s.length) {
      final c = s.codeUnitAt(i);
      if (c == 0x20 || c == 0x09 || c == 0x0a || c == 0x0d) {
        i++;
      } else {
        break;
      }
    }
  }

  Object? _value(int depth) {
    if (depth > _jsonMaxDepth) throw _JsonFail();
    if (i >= s.length) throw _JsonFail();
    final c = s[i];
    if (c == '{') return _object(depth);
    if (c == '[') return _array(depth);
    if (c == '"') return _string();
    if (s.startsWith('true', i)) {
      i += 4;
      return true;
    }
    if (s.startsWith('false', i)) {
      i += 5;
      return false;
    }
    if (s.startsWith('null', i)) {
      i += 4;
      return null;
    }
    return _number();
  }

  Map<String, Object?> _object(int depth) {
    i++;
    final out = <String, Object?>{};
    _ws();
    if (i < s.length && s[i] == '}') {
      i++;
      return out;
    }
    while (true) {
      _ws();
      if (i >= s.length || s[i] != '"') throw _JsonFail();
      final key = _string();
      _ws();
      if (i >= s.length || s[i] != ':') throw _JsonFail();
      i++;
      _ws();
      final v = _value(depth + 1);
      if (out.containsKey(key)) throw ImportFileError('json_invalid');
      out[key] = v;
      _ws();
      if (i >= s.length) throw _JsonFail();
      if (s[i] == ',') {
        i++;
        continue;
      }
      if (s[i] == '}') {
        i++;
        return out;
      }
      throw _JsonFail();
    }
  }

  List<Object?> _array(int depth) {
    i++;
    final out = <Object?>[];
    _ws();
    if (i < s.length && s[i] == ']') {
      i++;
      return out;
    }
    while (true) {
      _ws();
      out.add(_value(depth + 1));
      _ws();
      if (i >= s.length) throw _JsonFail();
      if (s[i] == ',') {
        i++;
        continue;
      }
      if (s[i] == ']') {
        i++;
        return out;
      }
      throw _JsonFail();
    }
  }

  String _string() {
    i++; // the opening quote
    final out = StringBuffer();
    while (true) {
      if (i >= s.length) throw _JsonFail();
      final c = s.codeUnitAt(i);
      if (c == 0x22) {
        i++;
        return out.toString();
      }
      if (c < 0x20) throw _JsonFail();
      if (c == 0x5c) {
        i++;
        if (i >= s.length) throw _JsonFail();
        final e = s[i];
        i++;
        switch (e) {
          case '"':
            out.write('"');
          case '\\':
            out.write('\\');
          case '/':
            out.write('/');
          case 'b':
            out.writeCharCode(8);
          case 'f':
            out.writeCharCode(12);
          case 'n':
            out.writeCharCode(10);
          case 'r':
            out.writeCharCode(13);
          case 't':
            out.writeCharCode(9);
          case 'u':
            if (i + 4 > s.length) throw _JsonFail();
            final hex = s.substring(i, i + 4);
            if (!RegExp(r'^[0-9a-fA-F]{4}$').hasMatch(hex)) throw _JsonFail();
            out.writeCharCode(int.parse(hex, radix: 16));
            i += 4;
          default:
            throw _JsonFail();
        }
        continue;
      }
      out.writeCharCode(c);
      i++;
    }
  }

  static final _numRe = RegExp(
    r'-?(?:0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?',
  );

  Object _number() {
    final m = _numRe.matchAsPrefix(s, i);
    if (m == null) throw _JsonFail();
    i = m.end;
    final text = m.group(0)!;
    if (m.group(1) == null && m.group(2) == null) {
      return _JsonInt(BigInt.parse(text));
    }
    return double.parse(text);
  }
}

ParsedImport parseJson(Uint8List data) {
  final text = _decode(data);
  Object? items;
  try {
    items = _JsonReader(text).readDocument();
  } on _JsonFail {
    throw ImportFileError('json_invalid');
  }
  if (items is! List) throw ImportFileError('json_invalid');
  if (items.length > importMaxRows) throw ImportFileError('too_many_rows');
  final seen = <String>{};
  final ignored = <String>[];
  final rows = <RawRow>[];
  var number = 0;
  for (final item in items) {
    number++;
    if (item is! Map<String, Object?>) {
      rows.add(RawRow(number, const {}, 'row_not_object'));
      continue;
    }
    final values = <String, Object?>{};
    var twice = false;
    for (final e in item.entries) {
      final name = _strip(e.key).toLowerCase();
      if (importColumns.contains(name)) {
        if (values.containsKey(name)) {
          twice = true;
          break;
        }
        values[name] = e.value;
        seen.add(name);
      } else {
        final shown = _strip(e.key).isEmpty ? '(empty)' : _strip(e.key);
        if (!ignored.contains(shown)) ignored.add(shown);
      }
    }
    rows.add(
      twice ? RawRow(number, const {}, 'column_twice') : RawRow(number, values),
    );
  }
  return ParsedImport(
    'json',
    [
      for (final c in importColumns)
        if (seen.contains(c)) c,
    ],
    ignored.take(_maxIgnored).toList(),
    max(ignored.length - _maxIgnored, 0),
    rows,
  );
}

ParsedImport parseImport(Uint8List data, Object? format) {
  if (format == 'csv') return parseCsv(data);
  if (format == 'json') return parseJson(data);
  throw ImportFileError('format_invalid');
}

// --- checking a row -----------------------------------------------------------

bool _printable(String value) {
  for (final c in value.runes) {
    if (c < 0x20 || (c >= 0x7f && c <= 0x9f) || (c >= 0xd800 && c <= 0xdfff)) {
      return false;
    }
  }
  return true;
}

/// One line of 1..limit characters (trimmed), or null for empty; JSON
/// integers too when [integers].
String? _text(Object? value, String code, int limit, {bool integers = false}) {
  if (value == null) return null;
  if (integers && value is _JsonInt) value = value.value.toString();
  if (value is! String) throw ImportRowError(code);
  final text = _strip(value);
  if (text.isEmpty) return null;
  if (text.runes.length > limit || !_printable(text))
    throw ImportRowError(code);
  return text;
}

List<Map<String, Object?>> _replicaEntries(Object? value) {
  if (value == null) return const [];
  if (value is String) {
    final text = _strip(value);
    if (text.isEmpty) return const [];
    final out = <Map<String, Object?>>[];
    for (final part in text.split('|')) {
      final p = _strip(part);
      final first = p.indexOf(':');
      if (first < 0) throw ImportRowError('replicas_invalid');
      final second = p.indexOf(':', first + 1);
      out.add({
        'type': _strip(p.substring(0, first)).toLowerCase(),
        'class': _strip(
          second < 0 ? p.substring(first + 1) : p.substring(first + 1, second),
        ),
        'make_model': second < 0 ? null : p.substring(second + 1),
      });
    }
    return out;
  }
  if (value is List) {
    final out = <Map<String, Object?>>[];
    for (final entry in value) {
      if (entry is! Map<String, Object?> ||
          entry.keys.any(
            (k) => !const {'type', 'class', 'make_model'}.contains(k),
          )) {
        throw ImportRowError('replicas_invalid');
      }
      out.add(entry);
    }
    return out;
  }
  throw ImportRowError('replicas_invalid');
}

List<Map<String, String?>> _checkReplicas(Object? value, ImportRules rules) {
  final entries = _replicaEntries(value);
  if (entries.isNotEmpty && !rules.predeclareReplicas) {
    throw ImportRowError('replicas_not_asked');
  }
  if (entries.length > min(rules.maxReplicas, _maxReplicas)) {
    throw ImportRowError('too_many_replicas');
  }
  final out = <Map<String, String?>>[];
  for (final entry in entries) {
    final kind = entry['type'];
    final cls = entry['class'];
    if (kind is! String || !importReplicaTypes.contains(kind)) {
      throw ImportRowError('replica_type_invalid');
    }
    if (cls is! String || !rules.classes.contains(cls)) {
      throw ImportRowError('replica_class_invalid');
    }
    out.add({
      'type': kind,
      'class': cls,
      'make_model': _text(
        entry['make_model'],
        'make_model_invalid',
        _makeModelMax,
      ),
    });
  }
  return out;
}

/// A row as it would be stored, or [ImportRowError]: the same limits as a
/// registration on the site and the controller's check-in.
ImportRow checkImportRow(RawRow raw, ImportRules rules) {
  if (raw.error != null) throw ImportRowError(raw.error!);
  final v = raw.values;
  final name = _text(v['display_name'], 'display_name_invalid', _nameMax);
  if (name == null) throw ImportRowError('display_name_invalid');
  final ref = _text(
    v['external_ref'],
    'external_ref_invalid',
    _refMax,
    integers: true,
  );
  final team = _text(v['team_preference'], 'team_preference_invalid', _teamMax);
  if (team != null && !rules.teams.contains(team)) {
    throw ImportRowError('team_preference_invalid');
  }
  var number = _text(
    v['federation_number'],
    'federation_number_invalid',
    _federationMax,
    integers: true,
  );
  final warnings = <String>[];
  if (rules.federation == 'off') {
    if (number != null) warnings.add('federation_number_dropped');
    number = null;
  } else if (rules.federation == 'required' && number == null) {
    throw ImportRowError('federation_number_required');
  }
  final replicas = v.containsKey('replicas')
      ? _checkReplicas(v['replicas'], rules)
      : null;
  if (ref == null) warnings.add('no_external_ref');
  return ImportRow(
    number: raw.number,
    displayName: name,
    externalRef: ref,
    teamPreference: team,
    federationNumber: number,
    replicas: replicas,
    present: v.keys.toSet(),
    warnings: warnings,
  );
}

// --- ids ----------------------------------------------------------------------

/// A name-based (version 5) UUID, as Python's `uuid.uuid5`.
String uuid5(String namespace, String name) {
  final hexNs = namespace.replaceAll('-', '');
  final ns = <int>[
    for (var i = 0; i < hexNs.length; i += 2)
      int.parse(hexNs.substring(i, i + 2), radix: 16),
  ];
  final digest = sha1
      .convert([...ns, ...utf8.encode(name)])
      .bytes
      .sublist(0, 16);
  digest[6] = (digest[6] & 0x0f) | 0x50;
  digest[8] = (digest[8] & 0x3f) | 0x80;
  final hex = [
    for (final b in digest) b.toRadixString(16).padLeft(2, '0'),
  ].join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-'
      '${hex.substring(16, 20)}-${hex.substring(20)}';
}

/// A random (version 4) UUID.
String uuid4(Random random) {
  final b = List<int>.generate(16, (_) => random.nextInt(256));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  final hex = [for (final x in b) x.toRadixString(16).padLeft(2, '0')].join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-'
      '${hex.substring(16, 20)}-${hex.substring(20)}';
}
