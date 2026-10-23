// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Declarative screen templates (ADR-P3-4, modes/README.md "Screens"): the
/// parser and the checks, ported from core/src/screen_template.c so the app
/// accepts exactly the templates the Field Box accepts, with the same
/// messages ("line N: why"). The tests compare the two on every template the
/// modes ship and on a corpus of broken ones (test/ui/).
///
/// The templates are a small YAML subset: block mappings and sequences,
/// one-line flow mappings, plain and quoted scalars, comments; no anchors,
/// tags, block scalars, flow sequences or multiple documents. A full YAML
/// library (the `yaml` package, which ADR-P3-4 named) reads more than that
/// and reads some plain values differently (`1e3`, `0x10`, `~`), so the
/// renderer uses this port instead (decision PD2).
library;

import 'dart:convert';
import 'dart:typed_data';

import 'expression.dart';

const int templateSourceMax = 4096; // bytes of YAML
const int templateWidgetsMax = 32;
const int _yamlNodesMax = 192;
const int _poolMax = 3072; // ATALAIA_TPL_POOL_MAX (P5H-12)
const int templateNameMax = 31;
const int templateDepthMax = 4; // rows and columns inside each other
const int _nestMax = 20;

/// Widget sizes besides pixels.
const int sizeAuto = -1; // fit the content
const int sizeFill = -2; // take the room left in the parent

enum WidgetType { label, progressBar, icon, qrCode, spacer, row, column }

const _typeNames = {
  'label': WidgetType.label,
  'progress_bar': WidgetType.progressBar,
  'icon': WidgetType.icon,
  'qr_code': WidgetType.qrCode,
  'spacer': WidgetType.spacer,
  'row': WidgetType.row,
  'column': WidgetType.column,
};

String widgetTypeName(WidgetType t) =>
    _typeNames.entries.firstWhere((e) => e.value == t).key;

enum TextAlignment { standard, left, center, right }

/// The icon names a template may use (the Field Box's LVGL symbols).
const templateIcons = [
  'ok', 'close', 'warning', 'pause', 'play', 'stop', 'bell', 'home', //
  'refresh', 'gps', 'wifi', 'battery', 'power', 'bluetooth', 'settings',
  'eye', 'plus', 'minus', 'left', 'right', 'up', 'down', 'audio', 'mute',
  'bars', 'loop', 'charge',
];

/// One widget, as atalaia_tpl_widget_t: parents come before their children.
final class TemplateWidget {
  TemplateWidget(this.type, this.parent, this.depth);

  final WidgetType type;

  /// Index of the row or column it is in; -1 for the screen.
  final int parent;

  /// 0 on the screen.
  final int depth;
  TextAlignment align = TextAlignment.standard;

  /// 0: the renderer's default.
  int fontSize = 0;
  int width = sizeAuto;
  int height = sizeAuto;

  /// top, right, bottom, left
  final List<int> padding = [0, 0, 0, 0];
  String? id;

  /// Label text, progress value, icon name or QR data.
  String? content;

  /// "team", "contrast", a colour name, #RRGGBB or {expr}.
  String? color;
  String? background;

  /// "{expr}" or "false"; null: always visible.
  String? visible;

  final List<int> children = [];
}

final class ScreenTemplate {
  ScreenTemplate(this.name, this.background, this.widgets);

  final String name;

  /// The screen's background, or null.
  final String? background;

  /// Every widget, parents before their children.
  final List<TemplateWidget> widgets;

  /// The widgets directly on the screen.
  Iterable<int> get roots sync* {
    for (var i = 0; i < widgets.length; i++) {
      if (widgets[i].parent < 0) yield i;
    }
  }
}

/// A template the core's parser refuses, with its "line N: why".
class TemplateException implements Exception {
  TemplateException(this.message);
  final String message;
  @override
  String toString() => 'TemplateException: $message';
}

/// Parses and checks [source]; throws [TemplateException].
ScreenTemplate parseScreenTemplate(String source) {
  final p = _Parser(Uint8List.fromList(utf8.encode(source)));
  final t = p.parse();
  if (t == null) throw TemplateException(p.message);
  return t;
}

/// Why [source] is refused (as the core says it), or null.
String? screenTemplateError(String source) {
  final p = _Parser(Uint8List.fromList(utf8.encode(source)));
  return p.parse() == null ? p.message : null;
}

// ==== YAML subset ============================================================

enum _Kind { scalar, map, seq }

enum _Style { plain, single, double, none }

final class _Y {
  _Y(this.kind, this.line);
  final _Kind kind;
  final int line;
  _Style style = _Style.plain;
  int key = 0;
  int keyLen = 0; // 0: no key
  int val = 0;
  int valLen = 0;
  int child = -1;
  int next = -1;
}

bool _space(int c) => c == 0x20 || c == 0x09;

class _Parser {
  _Parser(this.src);

  final Uint8List src;
  final ys = <_Y>[];
  var pos = 0;
  var lineNo = 1;
  var have = false;
  var indent = 0, start = 0, end = 0, atLine = 0;
  var depth = 0;
  var failed = false;
  var message = '';

  // Template state.
  var poolUsed = 1; // offset 0 means "not set"
  final widgets = <TemplateWidget>[];

  int get len => src.length;

  bool fail(int line, String why) {
    if (!failed) message = 'line $line: $why';
    failed = true;
    return false;
  }

  /// Where a line's content ends: before a comment, without trailing spaces.
  int contentEnd(int a, int b) {
    var single = false, dbl = false;
    var e = b;
    for (var i = a; i < b; i++) {
      final c = src[i];
      if (dbl) {
        if (c == 0x5c && i + 1 < b) {
          i++;
        } else if (c == 0x22) {
          dbl = false;
        }
      } else if (single) {
        if (c == 0x27) single = false;
      } else if (c == 0x22) {
        dbl = true;
      } else if (c == 0x27) {
        single = true;
      } else if (c == 0x23 && (i == a || _space(src[i - 1]))) {
        e = i;
        break;
      }
    }
    while (e > a && _space(src[e - 1])) {
      e--;
    }
    return e;
  }

  bool peek() {
    if (have) return true;
    while (pos < len) {
      final a = pos;
      var b = a;
      while (b < len && src[b] != 0x0a) {
        b++;
      }
      final next = b < len ? b + 1 : b;
      var lineEnd = b;
      if (lineEnd > a && src[lineEnd - 1] == 0x0d) lineEnd--;
      final line = lineNo;
      pos = next;
      lineNo++;
      var i = a;
      while (i < lineEnd && src[i] == 0x20) {
        i++;
      }
      if (i < lineEnd && src[i] == 0x09) {
        return fail(line, 'tabs are not allowed for indentation');
      }
      final e = contentEnd(i, lineEnd);
      if (e == i) continue; // blank or comment only
      if (e - i >= 3 &&
          (_same(i, '---') || _same(i, '...')) &&
          (e - i == 3 || _space(src[i + 3]))) {
        return fail(line, 'only one YAML document is allowed');
      }
      have = true;
      indent = i - a;
      start = i;
      end = e;
      atLine = line;
      return true;
    }
    return false;
  }

  bool _same(int at, String s) {
    for (var k = 0; k < s.length; k++) {
      if (src[at + k] != s.codeUnitAt(k)) return false;
    }
    return true;
  }

  int newNode(_Kind kind, int line) {
    if (ys.length >= _yamlNodesMax) {
      fail(
        line,
        'the template is too large (more than $_yamlNodesMax YAML nodes)',
      );
      return -1;
    }
    ys.add(_Y(kind, line));
    return ys.length - 1;
  }

  void appendChild(int parent, int child, List<int> last) {
    if (last[0] < 0) {
      ys[parent].child = child;
    } else {
      ys[last[0]].next = child;
    }
    last[0] = child;
  }

  /// A quoted scalar starting at src[a]: the index after its closing quote, or 0.
  int quotedEnd(int a, int b) {
    final q = src[a];
    for (var i = a + 1; i < b; i++) {
      if (q == 0x22 && src[i] == 0x5c) {
        i++;
      } else if (src[i] == q) {
        if (q == 0x27 && i + 1 < b && src[i + 1] == 0x27) {
          i++;
          continue;
        }
        return i + 1;
      }
    }
    return 0;
  }

  int scalar(int a, int b, int line, {required bool flow}) {
    final n = newNode(_Kind.scalar, line);
    if (n < 0) return -1;
    final y = ys[n];
    if (a == b) {
      y.style = _Style.none;
      return n;
    }
    final c = src[a];
    if (c == 0x22 || c == 0x27) {
      final e = quotedEnd(a, b);
      if (e == 0) return _f(line, 'unterminated quoted text');
      if (e != b) return _f(line, 'unexpected text after a quoted value');
      y.style = c == 0x22 ? _Style.double : _Style.single;
    } else {
      if (c == 0x26 || c == 0x2a || c == 0x21) {
        return _f(line, 'anchors, aliases and tags are not supported');
      }
      if (c == 0x7c || c == 0x3e) {
        return _f(line, 'block scalars are not supported');
      }
      if (c == 0x5b) return _f(line, 'flow sequences are not supported');
      if (c == 0x7b) return _f(line, 'flow mappings cannot be nested');
      for (var i = a; i < b; i++) {
        if (src[i] == 0x3a && (i + 1 == b || _space(src[i + 1]))) {
          return _f(line, "a plain value cannot contain ': ' (quote it)");
        }
        if (flow &&
            (src[i] == 0x7b ||
                src[i] == 0x7d ||
                src[i] == 0x5b ||
                src[i] == 0x5d)) {
          return _f(line, 'brackets in a flow mapping value must be quoted');
        }
      }
      y.style = _Style.plain;
    }
    if (b - a > 0xffff) return _f(line, 'value too long');
    y.val = a;
    y.valLen = b - a;
    return n;
  }

  int _f(int line, String why) {
    fail(line, why);
    return -1;
  }

  /// A key at src[a]: its length (followed by ':' and a space or the end), or 0.
  int keyAt(int a, int b) {
    var i = a;
    while (i < b && isKeyChar(src[i], first: i == a)) {
      i++;
    }
    if (i == a || i >= b || src[i] != 0x3a) return 0;
    if (i + 1 < b && !_space(src[i + 1])) return 0;
    return i - a;
  }

  bool sameKey(int parent, int key, int keyLen) {
    for (var c = ys[parent].child; c >= 0; c = ys[c].next) {
      final y = ys[c];
      if (y.keyLen != keyLen) continue;
      var same = true;
      for (var k = 0; k < keyLen; k++) {
        if (src[y.key + k] != src[key + k]) same = false;
      }
      if (same) return true;
    }
    return false;
  }

  int setKey(int node, int parent, int key, int keyLen, int line) {
    if (node < 0) return -1;
    if (keyLen > 255) return _f(line, 'key too long');
    if (sameKey(parent, key, keyLen)) {
      return _f(line, "duplicate key '${_str(key, keyLen)}'");
    }
    ys[node]
      ..key = key
      ..keyLen = keyLen;
    return node;
  }

  String _str(int a, int n) =>
      utf8.decode(src.sublist(a, a + n), allowMalformed: true);

  /// { key: value, ... } on one line, from src[a] ('{') to src[b-1] ('}').
  int flowMap(int a, int b, int line) {
    if (b - a < 2 || src[b - 1] != 0x7d) {
      return _f(line, "a flow mapping must end the line with '}'");
    }
    final map = newNode(_Kind.map, line);
    if (map < 0) return -1;
    final last = [-1];
    var i = a + 1;
    final close = b - 1;
    for (;;) {
      while (i < close && _space(src[i])) {
        i++;
      }
      if (i == close) break;
      final kl = keyAt(i, close);
      if (kl == 0) {
        return _f(line, "expected 'key: value' in the flow mapping");
      }
      final key = i;
      i += kl + 1;
      while (i < close && _space(src[i])) {
        i++;
      }
      final v = i;
      int ve;
      if (i < close && (src[i] == 0x22 || src[i] == 0x27)) {
        ve = quotedEnd(i, close);
        if (ve == 0) return _f(line, 'unterminated quoted text');
        i = ve;
        while (i < close && _space(src[i])) {
          i++;
        }
        if (i < close && src[i] != 0x2c) return _f(line, "expected ',' or '}'");
      } else {
        while (i < close && src[i] != 0x2c) {
          i++;
        }
        ve = i;
        while (ve > v && _space(src[ve - 1])) {
          ve--;
        }
      }
      final n = setKey(scalar(v, ve, line, flow: true), map, key, kl, line);
      if (n < 0) return -1;
      appendChild(map, n, last);
      if (i < close && src[i] == 0x2c) {
        i++;
        var j = i;
        while (j < close && _space(src[j])) {
          j++;
        }
        if (j == close) return _f(line, "a trailing ',' in a flow mapping");
      }
    }
    return map;
  }

  int inlineValue(int a, int b, int line) {
    if (a < b && src[a] == 0x7b) return flowMap(a, b, line);
    return scalar(a, b, line, flow: false);
  }

  bool _dashAtStart() =>
      src[start] == 0x2d && (end == start + 1 || _space(src[start + 1]));

  int nestedValue(int ind, int line) {
    if (peek()) {
      final dash = _dashAtStart();
      if (indent > ind || (indent == ind && dash)) return parseBlock(indent);
    }
    if (failed) return -1;
    return scalar(0, 0, line, flow: false); // null
  }

  int parseMap(int ind) {
    final map = newNode(_Kind.map, have ? atLine : lineNo);
    if (map < 0) return -1;
    final last = [-1];
    while (peek()) {
      if (indent < ind) break;
      final line = atLine;
      if (indent > ind) return _f(line, 'unexpected indentation');
      final a = start, b = end;
      if (src[a] == 0x2d && (b == a + 1 || _space(src[a + 1]))) {
        return _f(line, "a list item where a 'key: value' was expected");
      }
      final kl = keyAt(a, b);
      if (kl == 0) return _f(line, "expected 'key: value'");
      var v = a + kl + 1;
      while (v < b && _space(src[v])) {
        v++;
      }
      have = false;
      var n = v < b ? inlineValue(v, b, line) : nestedValue(ind, line);
      n = setKey(n, map, a, kl, line);
      if (n < 0) return -1;
      appendChild(map, n, last);
    }
    return failed ? -1 : map;
  }

  int parseSeq(int ind) {
    final seq = newNode(_Kind.seq, atLine);
    if (seq < 0) return -1;
    final last = [-1];
    while (peek()) {
      if (indent < ind) break;
      final line = atLine;
      if (indent > ind) return _f(line, 'unexpected indentation');
      final a = start, b = end;
      if (!(src[a] == 0x2d && (b == a + 1 || _space(src[a + 1])))) break;
      var v = a + 1;
      while (v < b && _space(src[v])) {
        v++;
      }
      int n;
      if (v == b) {
        have = false;
        n = nestedValue(ind, line);
      } else if (keyAt(v, b) > 0) {
        // "- key: value": a mapping whose entries line up with this key.
        indent = v - (a - indent);
        start = v;
        n = parseBlock(indent);
      } else {
        have = false;
        n = inlineValue(v, b, line);
      }
      if (n < 0) return -1;
      appendChild(seq, n, last);
    }
    return failed ? -1 : seq;
  }

  int parseBlock(int ind) {
    if (!peek()) return -1;
    if (++depth > _nestMax) return _f(atLine, 'nested too deeply');
    final n = _dashAtStart() ? parseSeq(ind) : parseMap(ind);
    depth--;
    return n;
  }

  // ==== From YAML to a template ==============================================

  bool keyIs(int i, String k) {
    final y = ys[i];
    if (y.keyLen != k.length) return false;
    for (var j = 0; j < y.keyLen; j++) {
      if (src[y.key + j] != k.codeUnitAt(j)) return false;
    }
    return true;
  }

  int childOf(int map, String k) {
    for (var i = ys[map].child; i >= 0; i = ys[i].next) {
      if (keyIs(i, k)) return i;
    }
    return -1;
  }

  String keyText(int i) => _str(ys[i].key, ys[i].keyLen);

  /// A scalar's text, decoded (the C code's store()); null on failure.
  String? store(int i) {
    final y = ys[i];
    final s = y.val;
    final n = y.valLen;
    if (poolUsed + n + 1 > _poolMax) {
      fail(y.line, "the template's text is too long ($_poolMax bytes in all)");
      return null;
    }
    final out = BytesBuilder();
    if (y.style == _Style.double) {
      for (var k = 1; k + 1 < n; k++) {
        final ch = src[s + k];
        if (ch != 0x5c) {
          out.addByte(ch);
          continue;
        }
        final e = src[s + ++k];
        switch (e) {
          case 0x6e:
            out.addByte(0x0a);
          case 0x74:
            out.addByte(0x09);
          case 0x22 || 0x5c || 0x2f:
            out.addByte(e);
          case 0x75:
            var cp = 0;
            for (var d = 0; d < 4; d++) {
              final h = k + 1 < n - 1 ? _hex(src[s + k + 1]) : -1;
              if (h < 0) {
                fail(y.line, r'bad \u escape');
                return null;
              }
              cp = cp * 16 + h;
              k++;
            }
            if (cp == 0 || (cp >= 0xd800 && cp <= 0xdfff)) {
              fail(y.line, r'bad \u escape');
              return null;
            }
            out.add(utf8.encode(String.fromCharCode(cp)));
          default:
            fail(y.line, "unknown escape '\\${String.fromCharCode(e)}'");
            return null;
        }
      }
    } else if (y.style == _Style.single) {
      for (var k = 1; k + 1 < n; k++) {
        out.addByte(src[s + k]);
        if (src[s + k] == 0x27) k++; // '' is one quote
      }
    } else if (y.style == _Style.plain) {
      out.add(src.sublist(s, s + n));
    }
    final bytes = out.takeBytes();
    poolUsed += bytes.length + 1;
    return utf8.decode(bytes, allowMalformed: true);
  }

  /// A scalar as text, cut to [cap] - 1 bytes like the C code's scratch
  /// buffers (for checks; never kept). Null if it is not a value.
  String? textOf(int i, int cap) {
    final y = ys[i];
    if (y.kind != _Kind.scalar || y.style == _Style.none) return null;
    final before = poolUsed;
    final v = store(i);
    if (v == null) return null;
    poolUsed = before;
    final bytes = utf8.encode(v);
    return bytes.length < cap
        ? v
        : utf8.decode(bytes.sublist(0, cap - 1), allowMalformed: true);
  }

  bool wantScalar(int i, String what) {
    if (ys[i].kind != _Kind.scalar || ys[i].style == _Style.none) {
      return fail(ys[i].line, '$what must be a value');
    }
    return true;
  }

  String? storeChecked(int i, String what) {
    if (!wantScalar(i, what)) return null;
    return store(i);
  }

  /// Every {expression} in a text: balanced, parseable, known filter.
  bool checkText(int line, String text, {required bool filters}) {
    final t = utf8.encode(text);
    final n = t.length;
    for (var i = 0; i < n; i++) {
      final ch = t[i];
      if ((ch == 0x7b || ch == 0x7d) && i + 1 < n && t[i + 1] == ch) {
        i++;
        continue;
      }
      if (ch == 0x7d) {
        return fail(line, "a '}' without its '{' (write }} for a brace)");
      }
      if (ch != 0x7b) continue;
      var close = i + 1;
      while (close < n && t[close] != 0x7d && t[close] != 0x7b) {
        close++;
      }
      if (close >= n || t[close] != 0x7d) {
        return fail(line, "a '{' without its '}'");
      }
      final inner = Uint8List.fromList(t.sublist(i + 1, close));
      final (elen, filter) = splitFilter(inner);
      if (filter == TextFilter.bad) {
        return fail(line, 'unknown filter (clock, upper or int)');
      }
      if (filter != TextFilter.none && !filters) {
        return fail(line, 'filters are only for text');
      }
      final expr = utf8.decode(inner.sublist(0, elen), allowMalformed: true);
      final why = expressionError(expr);
      if (why != null) return fail(line, '{$expr}: $why');
      i = close;
    }
    return true;
  }

  bool checkColor(int line, String v) {
    if (v == 'team' || v == 'contrast' || paletteColor(v) != null) return true;
    if (wholeExpression(v) != null) return checkText(line, v, filters: false);
    return fail(
      line,
      "'$v' is not a colour (team, contrast, a palette name, #RRGGBB or {expression})",
    );
  }

  bool checkWholeExpr(int line, String v, String what) {
    if (wholeExpression(v) == null) {
      return fail(line, '$what must be {expression}');
    }
    return checkText(line, v, filters: false);
  }

  /// strtol(s, 10) over the whole of s, within lo..hi.
  int? parseInt(String s, int lo, int hi) {
    final m = RegExp(r'^[ \t\n\v\f\r]*([+-]?\d+)$').firstMatch(s);
    if (m == null) return null;
    final v = BigInt.parse(m.group(1)!);
    if (v < BigInt.from(lo) || v > BigInt.from(hi)) return null;
    return v.toInt();
  }

  /// A size: pixels (0-1000) or "fill".
  int? sizeValue(int i, String what) {
    if (!wantScalar(i, what)) return null;
    final buf = textOf(i, 16);
    if (buf == null) return null;
    if (buf == 'fill') return sizeFill;
    final v = ys[i].style == _Style.plain ? parseInt(buf, 0, 1000) : null;
    if (v == null) {
      fail(ys[i].line, '$what is a number of pixels (0-1000) or fill');
      return null;
    }
    return v;
  }

  bool parseStyle(int map, TemplateWidget w) {
    if (ys[map].kind != _Kind.map) {
      return fail(ys[map].line, 'style must be a mapping');
    }
    for (var i = ys[map].child; i >= 0; i = ys[i].next) {
      final line = ys[i].line;
      if (keyIs(i, 'font_size')) {
        int? v;
        if (wantScalar(i, 'font_size')) {
          final buf = textOf(i, 24);
          if (buf != null && ys[i].style == _Style.plain) {
            v = parseInt(buf, 6, 200);
          }
        }
        if (v == null) return fail(line, 'font_size is a number (6-200)');
        w.fontSize = v;
      } else if (keyIs(i, 'align')) {
        if (!wantScalar(i, 'align')) return false;
        final buf = textOf(i, 24);
        if (buf == null) return false;
        switch (buf) {
          case 'left':
            w.align = TextAlignment.left;
          case 'center':
            w.align = TextAlignment.center;
          case 'right':
            w.align = TextAlignment.right;
          default:
            return fail(line, 'align is left, center or right');
        }
      } else if (keyIs(i, 'color') || keyIs(i, 'background')) {
        final bg = keyIs(i, 'background');
        final v = storeChecked(i, bg ? 'background' : 'color');
        if (v == null) return false;
        if (bg) {
          w.background = v;
        } else {
          w.color = v;
        }
        if (!checkColor(line, v)) return false;
      } else if (keyIs(i, 'padding')) {
        const sides = ['top', 'right', 'bottom', 'left'];
        const why =
            'padding is a number or { top, right, bottom, left } (0-200)';
        if (ys[i].kind == _Kind.map) {
          for (var s = ys[i].child; s >= 0; s = ys[s].next) {
            final k = sides.indexWhere((side) => keyIs(s, side));
            final buf = k < 0 ? null : textOf(s, 24);
            final v = buf != null && ys[s].style == _Style.plain
                ? parseInt(buf, 0, 200)
                : null;
            if (v == null) return fail(ys[s].line, why);
            w.padding[k] = v;
          }
        } else {
          final buf = textOf(i, 24);
          final v = buf != null && ys[i].style == _Style.plain
              ? parseInt(buf, 0, 200)
              : null;
          if (v == null) return fail(line, why);
          w.padding.fillRange(0, 4, v);
        }
      } else if (keyIs(i, 'width')) {
        final v = sizeValue(i, 'width');
        if (v == null) return false;
        w.width = v;
      } else if (keyIs(i, 'height')) {
        final v = sizeValue(i, 'height');
        if (v == null) return false;
        w.height = v;
      } else if (keyIs(i, 'visible')) {
        if (!wantScalar(i, 'visible')) return false;
        final buf = textOf(i, 24);
        if (buf == null) return false;
        if (buf == 'true') {
          w.visible = null;
        } else {
          final v = storeChecked(i, 'visible');
          if (v == null) return false;
          w.visible = v;
          if (v != 'false' && !checkWholeExpr(line, v, 'visible')) {
            return false;
          }
        }
      } else {
        return fail(line, "unknown style property '${keyText(i)}'");
      }
    }
    return true;
  }

  bool parseWidget(int map, int parent, int depth) {
    final line = ys[map].line;
    if (ys[map].kind != _Kind.map) {
      return fail(line, 'each widget is a mapping with a type');
    }
    if (widgets.length >= templateWidgetsMax) {
      return fail(line, 'too many widgets (at most $templateWidgetsMax)');
    }
    final ti = childOf(map, 'type');
    final type = ti < 0 ? null : textOf(ti, 16);
    if (type == null) return fail(line, 'a widget needs a type');
    final kind = _typeNames[type];
    if (kind == null) return fail(ys[ti].line, "unknown widget type '$type'");

    final index = widgets.length;
    final w = TemplateWidget(kind, parent, depth);
    widgets.add(w);
    if (parent >= 0) widgets[parent].children.add(index);

    final contentKey = switch (kind) {
      WidgetType.label => 'text',
      WidgetType.progressBar => 'value',
      WidgetType.icon => 'icon',
      WidgetType.qrCode => 'data',
      _ => null,
    };
    var children = -1;
    for (var i = ys[map].child; i >= 0; i = ys[i].next) {
      final l = ys[i].line;
      if (keyIs(i, 'type')) continue;
      if (keyIs(i, 'id')) {
        w.id = storeChecked(i, 'id');
        if (w.id == null) return false;
      } else if (keyIs(i, 'style')) {
        if (!parseStyle(i, w)) return false;
      } else if (contentKey != null && keyIs(i, contentKey)) {
        w.content = storeChecked(i, contentKey);
        if (w.content == null) return false;
      } else if (kind == WidgetType.spacer && keyIs(i, 'height')) {
        final v = sizeValue(i, 'height');
        if (v == null) return false;
        w.height = v;
      } else if ((kind == WidgetType.row || kind == WidgetType.column) &&
          keyIs(i, 'children')) {
        children = i;
      } else {
        return fail(l, "a $type has no property '${keyText(i)}'");
      }
    }

    final content = w.content;
    switch (kind) {
      case WidgetType.label:
        if (content == null) return fail(line, 'a label needs text');
        return checkText(line, content, filters: true);
      case WidgetType.qrCode:
        if (content == null) return fail(line, 'a qr_code needs data');
        return checkText(line, content, filters: true);
      case WidgetType.progressBar:
        if (content == null) return fail(line, 'a progress_bar needs a value');
        if (wholeExpression(content) != null) {
          return checkText(line, content, filters: false);
        }
        final (d, used) = strtod(content);
        if (d < 0 || used != content.length || used == 0) {
          return fail(
            line,
            'a progress_bar value is a number (0-1) or {expression}',
          );
        }
        return true;
      case WidgetType.icon:
        if (content == null) return fail(line, 'an icon needs an icon name');
        if (!templateIcons.contains(content)) {
          return fail(line, "unknown icon '$content'");
        }
        return true;
      case WidgetType.spacer:
        if (w.height == sizeAuto) return fail(line, 'a spacer needs a height');
        return true;
      case WidgetType.row || WidgetType.column:
        if (children < 0) return fail(line, 'a $type needs children');
        if (depth + 1 > templateDepthMax) {
          return fail(
            line,
            'rows and columns nest at most $templateDepthMax deep',
          );
        }
        if (ys[children].kind != _Kind.seq) {
          return fail(ys[children].line, 'children is a list of widgets');
        }
        return parseWidgets(children, index, depth + 1);
    }
  }

  bool parseWidgets(int seq, int parent, int depth) {
    for (var i = ys[seq].child; i >= 0; i = ys[i].next) {
      if (!parseWidget(i, parent, depth)) return false;
    }
    return true;
  }

  static bool nameOk(String s) =>
      RegExp('^[a-z0-9_]{1,$templateNameMax}\$').hasMatch(s);

  ScreenTemplate? parse() {
    if (len == 0) {
      fail(1, 'the template is empty');
      return null;
    }
    if (len > templateSourceMax) {
      fail(1, 'the template is larger than $templateSourceMax bytes');
      return null;
    }
    if (src.contains(0)) {
      fail(1, 'the template contains a NUL byte');
      return null;
    }
    if (!peek()) {
      if (!failed) fail(1, 'the template is empty');
      return null;
    }
    if (indent != 0) {
      fail(atLine, 'the template must start at column 1');
      return null;
    }
    final root = parseBlock(0);
    if (root < 0 || failed) {
      if (!failed) fail(lineNo, 'not a template');
      return null;
    }
    if (peek()) {
      fail(atLine, 'unexpected text after the template');
      return null;
    }
    if (failed) return null;

    if (ys[root].kind != _Kind.map) {
      fail(1, 'a template is a mapping');
      return null;
    }
    String? name;
    String? background;
    var layout = -1;
    for (var i = ys[root].child; i >= 0; i = ys[i].next) {
      final line = ys[i].line;
      if (keyIs(i, 'template')) {
        name = storeChecked(i, 'template');
        if (name == null) return null;
        if (!nameOk(name)) {
          fail(
            line,
            'template names are 1-$templateNameMax lower-case letters, digits and _',
          );
          return null;
        }
      } else if (keyIs(i, 'layout')) {
        layout = i;
      } else if (keyIs(i, 'style')) {
        if (ys[i].kind != _Kind.map) {
          fail(line, 'style must be a mapping');
          return null;
        }
        for (var s = ys[i].child; s >= 0; s = ys[s].next) {
          if (!keyIs(s, 'background')) {
            fail(ys[s].line, "a screen's style has only a background");
            return null;
          }
          background = storeChecked(s, 'background');
          if (background == null) return null;
          if (!checkColor(ys[s].line, background)) return null;
        }
      } else {
        fail(line, "unknown key '${keyText(i)}' (template, style, layout)");
        return null;
      }
    }
    if (name == null) {
      fail(1, 'the template has no name (template: ...)');
      return null;
    }
    if (layout < 0 || ys[layout].kind != _Kind.seq || ys[layout].child < 0) {
      fail(layout < 0 ? 1 : ys[layout].line, 'layout must list the widgets');
      return null;
    }
    if (!parseWidgets(layout, -1, 0)) return null;
    return ScreenTemplate(name, background, widgets);
  }
}

int _hex(int h) {
  if (h >= 0x30 && h <= 0x39) return h - 0x30;
  if (h >= 0x61 && h <= 0x66) return h - 0x61 + 10;
  if (h >= 0x41 && h <= 0x46) return h - 0x41 + 10;
  return -1;
}

// ==== Colours =================================================================

/// The template palette: team colours (the Field Box's) and interface colours.
const templatePalette = <String, int>{
  'red': 0xE53935,
  'blue': 0x1E88E5,
  'green': 0x43A047,
  'yellow': 0xFDD835,
  'orange': 0xFB8C00,
  'purple': 0x8E24AA,
  'white': 0xFFFFFF,
  'black': 0x000000,
  'grey': 0x78909C,
  'muted': 0x9AA5B1,
  'accent': 0xFFB300,
  'danger': 0xE53935,
  'panel': 0x222B35,
  'background': 0x101418,
};

/// A colour name (atalaia_tpl_color): "#RRGGBB" or a palette name, in any
/// case; null for anything else (an unknown team).
int? paletteColor(String name) {
  if (name.isEmpty) return null;
  if (name.startsWith('#')) {
    if (name.length != 7) return null;
    var v = 0;
    for (var i = 1; i < 7; i++) {
      final h = _hex(name.codeUnitAt(i));
      if (h < 0) return null;
      v = v << 4 | h;
    }
    return v;
  }
  for (final e in templatePalette.entries) {
    final a = e.key;
    if (a.length != name.length) continue;
    var same = true;
    for (var i = 0; i < a.length; i++) {
      if ((name.codeUnitAt(i) | 0x20) != a.codeUnitAt(i)) same = false;
    }
    if (same) return e.value;
  }
  return null;
}
