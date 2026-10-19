// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The expressions inside a screen template's {braces} (ADR-P3-4,
/// modes/README.md "Screens"): the Dart twin of the evaluator in
/// core/src/screen_template.c, which the Field Box uses. Same grammar, same
/// values, same text: the tests compare the two on every template the modes
/// ship and on thousands of generated expressions (test/ui/).
///
///     or   := and ('||' and)*
///     and  := cmp ('&&' cmp)*
///     cmp  := sum (('<' | '<=' | '>' | '>=' | '==' | '!=') sum)?
///     sum  := prod (('+' | '-') prod)*
///     prod := unary (('*' | '/') unary)*
///     unary:= ('-' | '!') unary | atom
///     atom := number | 'text' | name ('.' name)* | '(' or ')'
///
/// Names read the screen's data (dots reach into objects; `params.x` reads
/// the game's parameters). A missing name is nil: 0 in arithmetic, "" in
/// text, false in tests. && and || give the deciding operand, as in Lua.
/// Division by zero gives 0. Text filters: |clock, |upper, |int.
///
/// Two limits are kept from the C code because they change results: the
/// strings one expression reads share 256 bytes, and a text is cut at 159
/// bytes. Where the C code would cut a multi-byte UTF-8 character in two,
/// this code drops the whole character instead.
library;

import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

/// ATALAIA_TPL_TEXT_MAX: a widget's text after interpolation, NUL included.
const int templateTextMax = 160;

const int _scratchSize = 256;

/// What the expressions read: the screen's data (the second argument of
/// ui.screen) and the game's parameters.
final class TemplateScope {
  const TemplateScope({this.data = const {}, this.params = const {}});

  final Map<String, Object?> data;
  final Map<String, Object?> params;
}

enum _Kind { nil, number, text, boolean }

/// A value while evaluating.
final class TemplateValue {
  const TemplateValue._(this._kind, this.number, this.text);

  static const nil = TemplateValue._(_Kind.nil, 0, '');
  static const yes = TemplateValue._(_Kind.boolean, 1, '');
  static const no = TemplateValue._(_Kind.boolean, 0, '');

  factory TemplateValue.number(double d) =>
      TemplateValue._(_Kind.number, d, '');
  factory TemplateValue.text(String s) => TemplateValue._(_Kind.text, 0, s);

  final _Kind _kind;
  final double number;
  final String text;

  bool get isNil => _kind == _Kind.nil;
  bool get isText => _kind == _Kind.text;
  bool get isNumber => _kind == _Kind.number;
  bool get isBool => _kind == _Kind.boolean;

  /// As a number: numbers and booleans, 0 for the rest.
  double get asNumber =>
      _kind == _Kind.number || _kind == _Kind.boolean ? number : 0.0;

  bool get truth => switch (_kind) {
    _Kind.number || _Kind.boolean => number != 0.0,
    _Kind.text => text.isNotEmpty,
    _Kind.nil => false,
  };

  @override
  String toString() => switch (_kind) {
    _Kind.nil => 'nil',
    _Kind.number => '$number',
    _Kind.text => "'$text'",
    _Kind.boolean => number != 0 ? 'true' : 'false',
  };
}

bool _isSpace(int c) => c == 0x20 || c == 0x09;

/// A character of a name: letters and _ (and digits after the first).
bool isKeyChar(int c, {required bool first}) =>
    (c >= 0x61 && c <= 0x7a) ||
    (c >= 0x41 && c <= 0x5a) ||
    c == 0x5f ||
    (!first && c >= 0x30 && c <= 0x39);

bool _isDigit(int c) => c >= 0x30 && c <= 0x39;

class _Eval {
  _Eval(this.s, this.scope);

  /// The expression's UTF-8 bytes.
  final Uint8List s;
  final TemplateScope? scope;
  var i = 0;
  var used = 0; // bytes of the 256-byte scratch the strings took
  var error = false;
  String why = '';

  int get len => s.length;

  void skipWs() {
    while (i < len && _isSpace(s[i])) {
      i++;
    }
  }

  bool at(String op) {
    final n = op.length;
    skipWs();
    if (len - i < n) return false;
    for (var k = 0; k < n; k++) {
      if (s[i + k] != op.codeUnitAt(k)) return false;
    }
    // "<" must not match "<=", "!" must not match "!=".
    if (n == 1 && i + 1 < len && s[i + 1] == 0x3d && '<>!='.contains(op)) {
      return false;
    }
    i += n;
    return true;
  }

  void fail(String reason) {
    if (!error) why = reason;
    error = true;
  }

  /// A decoded string takes its bytes plus one (the C code's NUL) of the
  /// scratch; [cut] says whether a too-long string is cut (data) or refused.
  TemplateValue keep(String text, {required bool cut}) {
    final room = _scratchSize - used;
    final bytes = utf8.encode(text);
    if (bytes.length + 1 > room) {
      if (!cut) {
        fail('text too long');
        return TemplateValue.nil;
      }
      if (room < 2) return TemplateValue.nil;
      text = _cutUtf8(text, room - 1);
      used += utf8.encode(text).length + 1;
      return TemplateValue.text(text);
    }
    used += bytes.length + 1;
    return TemplateValue.text(text);
  }

  TemplateValue lookup(String name) {
    final sc = scope;
    if (sc == null) return TemplateValue.nil;
    Object? obj = sc.data;
    var path = name;
    if (name.length >= 7 && name.startsWith('params.')) {
      obj = sc.params;
      path = name.substring(7);
    }
    for (final part in path.split('.')) {
      if (obj is! Map) return TemplateValue.nil;
      if (!obj.containsKey(part)) return TemplateValue.nil;
      obj = obj[part];
    }
    return switch (obj) {
      final String text => keep(_jsonText(text), cut: true),
      true => TemplateValue.yes,
      false => TemplateValue.no,
      final num n => TemplateValue.number(n.toDouble()),
      _ => TemplateValue.nil, // null, objects and lists
    };
  }

  TemplateValue atom(int depth) {
    skipWs();
    if (i >= len) {
      fail('an expression is missing');
      return TemplateValue.nil;
    }
    final c = s[i];
    if (c == 0x28) {
      i++;
      final v = or(depth + 1);
      if (!at(')')) fail("a ')' is missing");
      return v;
    }
    if (_isDigit(c) || c == 0x2e) {
      final a = i;
      while (i < len && (_isDigit(s[i]) || s[i] == 0x2e)) {
        i++;
      }
      final n = i - a;
      if (n >= 32) {
        fail('number too long');
        return TemplateValue.nil;
      }
      final text = ascii.decode(s.sublist(a, i));
      final d = _parseDecimal(text);
      if (d == null) {
        fail('bad number');
        return TemplateValue.number(_strtodPrefix(text));
      }
      return TemplateValue.number(d);
    }
    if (c == 0x27) {
      final a = ++i;
      while (i < len && s[i] != 0x27) {
        i++;
      }
      if (i >= len) {
        fail("unterminated 'text'");
        return TemplateValue.nil;
      }
      final text = utf8.decode(s.sublist(a, i), allowMalformed: true);
      i++;
      return keep(text, cut: false);
    }
    if (isKeyChar(c, first: true)) {
      final a = i;
      for (;;) {
        while (i < len && isKeyChar(s[i], first: i == a)) {
          i++;
        }
        if (i < len &&
            s[i] == 0x2e &&
            i + 1 < len &&
            isKeyChar(s[i + 1], first: true)) {
          i++;
          continue;
        }
        break;
      }
      final name = ascii.decode(s.sublist(a, i));
      if (name == 'true') return TemplateValue.yes;
      if (name == 'false') return TemplateValue.no;
      if (name == 'nil') return TemplateValue.nil;
      return lookup(name);
    }
    fail('unexpected character');
    return TemplateValue.nil;
  }

  TemplateValue unary(int depth) {
    if (depth > 32) {
      fail('nested too deeply');
      return TemplateValue.nil;
    }
    if (at('-')) return TemplateValue.number(-unary(depth + 1).asNumber);
    if (at('!')) {
      return TemplateValue.number(unary(depth + 1).truth ? 0 : 1);
    }
    return atom(depth);
  }

  TemplateValue prod(int depth) {
    var v = unary(depth);
    for (;;) {
      if (at('*')) {
        v = TemplateValue.number(v.asNumber * unary(depth).asNumber);
      } else if (at('/')) {
        final d = unary(depth).asNumber;
        v = TemplateValue.number(d == 0.0 ? 0.0 : v.asNumber / d);
      } else {
        return v;
      }
    }
  }

  TemplateValue sum(int depth) {
    var v = prod(depth);
    for (;;) {
      if (at('+')) {
        v = TemplateValue.number(v.asNumber + prod(depth).asNumber);
      } else if (at('-')) {
        v = TemplateValue.number(v.asNumber - prod(depth).asNumber);
      } else {
        return v;
      }
    }
  }

  TemplateValue cmp(int depth) {
    final a = sum(depth);
    const ops = ['<=', '>=', '==', '!=', '<', '>'];
    for (var k = 0; k < ops.length; k++) {
      if (!at(ops[k])) continue;
      final b = sum(depth);
      final (c, ok) = _compare(a, b);
      final r = switch (k) {
        0 => ok && c <= 0,
        1 => ok && c >= 0,
        2 => ok && c == 0,
        3 => !ok || c != 0,
        4 => ok && c < 0,
        _ => ok && c > 0,
      };
      return TemplateValue.number(r ? 1 : 0);
    }
    return a;
  }

  TemplateValue and(int depth) {
    var v = cmp(depth);
    while (at('&&')) {
      final w = cmp(depth);
      if (v.truth) v = w; // Lua: a and b
    }
    return v;
  }

  TemplateValue or(int depth) {
    var v = and(depth);
    while (at('||')) {
      final w = and(depth);
      if (!v.truth) v = w; // Lua: a or b
    }
    return v;
  }
}

/// (sign of a - b, whether they compare at all): text against a number or
/// nil compares as different.
(int, bool) _compare(TemplateValue a, TemplateValue b) {
  if (a.isText && b.isText) {
    final x = utf8.encode(a.text), y = utf8.encode(b.text);
    for (var k = 0; k < x.length && k < y.length; k++) {
      if (x[k] != y[k]) return (x[k] < y[k] ? -1 : 1, true);
    }
    return (x.length.compareTo(y.length).sign, true);
  }
  if (a.isText || b.isText) return (1, false);
  final x = a.asNumber, y = b.asNumber;
  return (
    x < y
        ? -1
        : x > y
        ? 1
        : 0,
    true,
  );
}

/// How the C code's JSON string reader sees a data string: \n, \r and \t
/// become spaces, NUL becomes '?'.
String _jsonText(String s) {
  if (!s.contains(RegExp('[\n\r\t\u0000]'))) return s;
  return s.replaceAll(RegExp('[\n\r\t]'), ' ').replaceAll('\u0000', '?');
}

String _cutUtf8(String s, int maxBytes) {
  final out = StringBuffer();
  var used = 0;
  for (final rune in s.runes) {
    final n = rune < 0x80
        ? 1
        : rune < 0x800
        ? 2
        : rune < 0x10000
        ? 3
        : 4;
    if (used + n > maxBytes) break;
    out.writeCharCode(rune);
    used += n;
  }
  return out.toString();
}

/// A number of digits and dots, as strtod reads it whole: null if it is not.
double? _parseDecimal(String text) {
  if (!RegExp(r'^(\d+\.?\d*|\.\d+)$').hasMatch(text)) return null;
  return double.parse(text.endsWith('.') ? '${text}0' : text);
}

/// What strtod makes of a malformed number (its longest valid prefix).
double _strtodPrefix(String text) {
  final m = RegExp(r'^(\d+\.?\d*|\.\d+)').firstMatch(text);
  return m == null ? 0 : _parseDecimal(m.group(0)!) ?? 0;
}

/// Evaluates one expression (no braces). Null scope: syntax check only.
/// Returns nil on any error, as the C code does.
TemplateValue evaluate(String expr, TemplateScope? scope) {
  final e = _Eval(Uint8List.fromList(utf8.encode(expr)), scope);
  final v = e.or(0);
  e.skipWs();
  if (e.i != e.len) e.fail('unexpected text after the expression');
  return e.error ? TemplateValue.nil : v;
}

/// Why [expr] is not a valid expression, or null (atalaia_tpl_expr_ok).
String? expressionError(String expr) {
  final e = _Eval(Uint8List.fromList(utf8.encode(expr)), null);
  e.or(0);
  e.skipWs();
  if (e.i != e.len) e.fail('unexpected text after the expression');
  return e.error ? e.why : null;
}

/// The text filters.
enum TextFilter { none, clock, upper, integer, bad }

/// Splits the inside of "{expr|filter}": the expression's length (in bytes
/// of [s]) and its filter. "||" is an operator, not a filter.
(int, TextFilter) splitFilter(Uint8List s) {
  var quoted = false;
  for (var i = 0; i < s.length; i++) {
    if (s[i] == 0x27) quoted = !quoted;
    if (quoted || s[i] != 0x7c) continue;
    if (i + 1 < s.length && s[i + 1] == 0x7c) {
      i++;
      continue;
    }
    var a = i + 1, b = s.length;
    while (a < b && _isSpace(s[a])) {
      a++;
    }
    while (b > a && _isSpace(s[b - 1])) {
      b--;
    }
    final f = String.fromCharCodes(s.sublist(a, b));
    return (
      i,
      switch (f) {
        'clock' => TextFilter.clock,
        'upper' => TextFilter.upper,
        'int' => TextFilter.integer,
        _ => TextFilter.bad,
      },
    );
  }
  return (s.length, TextFilter.none);
}

/// A number as the templates show it: whole numbers without decimals,
/// others with up to two (printf's "%.2f", rounding ties to even, then
/// trailing zeros dropped).
String formatNumber(double d) {
  if (!d.isFinite) return '0';
  if (d == d.floorToDouble() && d.abs() < 1e15) return '${d.toInt()}';
  var s = _fixed2(d);
  if (s.contains('.')) {
    s = s.replaceFirst(RegExp(r'0+$'), '');
    if (s.endsWith('.')) s = s.substring(0, s.length - 1);
  }
  return s;
}

/// printf("%.2f", d): the exact binary value rounded half to even.
String _fixed2(double d) {
  final neg = d < 0 || (d == 0 && d.isNegative);
  final a = d.abs();
  final (mant, exp) = _exact(a); // a == mant * 2^exp
  // a * 100, as a fraction num / den with den a power of two.
  var num = mant * BigInt.from(100);
  var den = BigInt.one;
  if (exp >= 0) {
    num = num << exp;
  } else {
    den = den << -exp;
  }
  var q = num ~/ den;
  final r = num - q * den;
  final twice = r * BigInt.two;
  if (twice > den || (twice == den && q.isOdd)) q += BigInt.one;
  final digits = q.toString().padLeft(3, '0');
  final whole = digits.substring(0, digits.length - 2);
  return '${neg ? '-' : ''}$whole.${digits.substring(digits.length - 2)}';
}

/// A finite double as mantissa * 2^exponent, exactly.
(BigInt, int) _exact(double d) {
  final bits = ByteData(8)..setFloat64(0, d);
  final hi = bits.getUint32(0), lo = bits.getUint32(4);
  final e = (hi >> 20) & 0x7ff;
  var m = (BigInt.from(hi & 0xfffff) << 32) | BigInt.from(lo);
  if (e == 0) return (m, -1074);
  m |= BigInt.one << 52;
  return (m, e - 1075);
}

String _clock(double d) {
  // Clamped as the core does: beyond 1e15 s nothing is converted.
  if (d.isFinite && d > 1e15) d = 1e15;
  final s = d > 0 && d.isFinite ? (d - 1e-9).ceil() : 0;
  String two(int n) => n.toString().padLeft(2, '0');
  if (s >= 3600) return '${s ~/ 3600}:${two((s ~/ 60) % 60)}:${two(s % 60)}';
  return '${s ~/ 60}:${two(s % 60)}';
}

String _upperAscii(String s) => String.fromCharCodes(
  s.codeUnits.map((c) => c >= 0x61 && c <= 0x7a ? c - 0x20 : c),
);

String _show(TemplateValue v, TextFilter filter) {
  switch (filter) {
    case TextFilter.clock:
      return _clock(v.asNumber);
    case TextFilter.integer:
      final d = v.asNumber;
      return formatNumber(d.isFinite ? d.floorToDouble() : 0);
    default:
      final out = v.isNumber
          ? formatNumber(v.number)
          : v.isBool
          ? (v.number != 0 ? 'true' : 'false')
          : v.isText
          ? v.text
          : '';
      return filter == TextFilter.upper ? _upperAscii(out) : out;
  }
}

/// A text with its {expressions} filled in (a label's text, a QR code's
/// data): atalaia_tpl_text. At most 159 bytes of UTF-8.
String interpolate(String? text, TemplateScope scope) {
  if (text == null) return '';
  final src = Uint8List.fromList(utf8.encode(text));
  final out = BytesBuilder(copy: false);
  final n = src.length;
  for (var i = 0; i < n; i++) {
    final c = src[i];
    if ((c == 0x7b || c == 0x7d) && i + 1 < n && src[i + 1] == c) {
      out.addByte(c);
      i++;
      continue;
    }
    if (c != 0x7b) {
      out.addByte(c);
      continue;
    }
    var close = i + 1;
    while (close < n && src[close] != 0x7d) {
      close++;
    }
    if (close >= n) break;
    final inner = Uint8List.sublistView(src, i + 1, close);
    final (elen, filter) = splitFilter(inner);
    final expr = utf8.decode(inner.sublist(0, elen), allowMalformed: true);
    out.add(utf8.encode(_show(evaluate(expr, scope), filter)));
    i = close;
  }
  final bytes = out.takeBytes();
  final all = utf8.decode(bytes, allowMalformed: true);
  return bytes.length <= templateTextMax - 1
      ? all
      : _cutUtf8(all, templateTextMax - 1);
}

/// "{expr}" covering the whole value: its expression, or null.
String? wholeExpression(String v) {
  if (v.length < 2 || !v.startsWith('{') || !v.endsWith('}')) return null;
  final inner = v.substring(1, v.length - 1);
  if (inner.contains('{') || inner.contains('}')) return null;
  return inner;
}

/// A visible: property (atalaia_tpl_truthy): null or "true" is true,
/// "false" false, "{expr}" its truth.
bool isVisible(String? value, TemplateScope scope) {
  if (value == null || value == 'true') return true;
  if (value == 'false') return false;
  final expr = wholeExpression(value);
  if (expr == null) return true;
  return evaluate(expr, scope).truth;
}

/// A progress_bar value (atalaia_tpl_fraction): a number or "{expr}",
/// clamped to 0-1.
double fraction(String? value, TemplateScope scope) {
  if (value == null) return 0;
  final expr = wholeExpression(value);
  final d = expr != null ? evaluate(expr, scope).asNumber : strtod(value).$1;
  if (!(d > 0)) return 0; // also NaN
  return math.min(d, 1);
}

/// C's strtod: the value of the longest prefix of [s] that is a number
/// (decimal or hexadecimal, inf, nan, after leading white space) and how
/// many characters it took (0: none).
(double, int) strtod(String s) {
  final m = RegExp(
    r'^[ \t\n\v\f\r]*([+-]?)'
    r'(?:(0[xX])((?:[0-9a-fA-F]+\.?[0-9a-fA-F]*|\.[0-9a-fA-F]+))([pP][+-]?\d+)?'
    r'|((?:\d+\.?\d*|\.\d+))([eE][+-]?\d+)?'
    r'|([iI][nN][fF](?:[iI][nN][iI][tT][yY])?)'
    r'|([nN][aA][nN](?:\([0-9A-Za-z_]*\))?))',
  ).firstMatch(s);
  if (m == null) return (0, 0);
  final sign = m.group(1) == '-' ? -1.0 : 1.0;
  double v;
  if (m.group(2) != null) {
    final digits = m.group(3)!;
    final dot = digits.indexOf('.');
    final intPart = dot < 0 ? digits : digits.substring(0, dot);
    final frac = dot < 0 ? '' : digits.substring(dot + 1);
    final mant = BigInt.parse(
      '0${intPart.isEmpty ? '' : intPart}$frac',
      radix: 16,
    );
    var exp = -4 * frac.length;
    final p = m.group(4);
    if (p != null) exp += int.parse(p.substring(1));
    v = mant.toDouble() * math.pow(2, exp);
  } else if (m.group(5) != null) {
    v = double.parse('${_fixDot(m.group(5)!)}${m.group(6) ?? ''}');
  } else if (m.group(7) != null) {
    v = double.infinity;
  } else {
    v = double.nan;
  }
  return (sign * v, m.end);
}

String _fixDot(String d) =>
    d.endsWith('.') ? '${d}0' : (d.startsWith('.') ? '0$d' : d);
