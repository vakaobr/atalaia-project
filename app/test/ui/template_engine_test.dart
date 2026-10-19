// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The app's screen-template parser and expressions (lib/ui/template/) against
// the core's (core/src/screen_template.c, the Field Box's), through dart:ffi:
// every template the modes ship, thousands of mutated templates, and
// thousands of generated expressions, texts, visibilities, fractions and
// colours must come out the same, error messages included.

import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/ui/template/expression.dart';
import 'package:atalaia_app/ui/template/screen_template.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';

/// The core's error buffer in these bindings: 160 bytes, NUL included.
String _cut(String? s) {
  if (s == null) return '';
  final b = utf8.encode(s);
  return b.length <= 159
      ? s
      : utf8.decode(b.sublist(0, 159), allowMalformed: true);
}

List<File> shippedTemplates() {
  final out = <File>[];
  for (final d in Directory('../modes').listSync().whereType<Directory>()) {
    final screens = Directory('${d.path}/assets/screens');
    if (!screens.existsSync()) continue;
    out.addAll(
      screens.listSync().whereType<File>().where(
        (f) => f.path.endsWith('.yaml'),
      ),
    );
  }
  return out..sort((a, b) => a.path.compareTo(b.path));
}

const _names = [
  'a', 'b', 'n', 's', 't', 'f', 'team', 'left', 'missing', 'obj', //
  'obj.x', 'obj.y.z', 'obj.s', 'list', 'nul', 'long', 'tie', 'neg', 'big',
  'huge', 'third', 'u', 'nl', 'params.fuse_s', 'params.n', 'params.s',
  'params', 'params.missing', 'true', 'false', 'nil', 'x1', '_u',
];

const _numbers = [
  '0', '1', '2', '10', '0.5', '.5', '5.', '3.25', '007', '1.2.3', '.', //
  '12345678901234567890', '0.125', '2.675', '1e3', '99',
];

const _texts = [
  "''", "'red'", "'blue'", "'a b'", "'é'", "'x|y'", "'danger'", "'team'", //
  "'unterminated", "'café ç'", "'0'", "'10'",
];

const _junk = ['@', '#', '&', '|', ')', '(', '  ', '\t', ',', '=', '!=', '<'];

const _ops = [
  '+', '-', '*', '/', '<', '<=', '>', '>=', '==', '!=', '&&', '||', //
];

String _expr(Random r, int depth) {
  final k = depth > 3 ? r.nextInt(3) : r.nextInt(9);
  return switch (k) {
    0 => _numbers[r.nextInt(_numbers.length)],
    1 => _names[r.nextInt(_names.length)],
    2 => _texts[r.nextInt(_texts.length)],
    3 => '-${_expr(r, depth + 1)}',
    4 => '!${_expr(r, depth + 1)}',
    5 => '(${_expr(r, depth + 1)})',
    6 =>
      '${_expr(r, depth + 1)} ${_ops[r.nextInt(_ops.length)]} '
          '${_expr(r, depth + 1)}',
    7 =>
      '${_expr(r, depth + 1)}${_ops[r.nextInt(_ops.length)]}'
          '${_expr(r, depth + 1)}',
    _ =>
      r.nextInt(4) == 0
          ? _junk[r.nextInt(_junk.length)] + _expr(r, depth + 1)
          : '${_expr(r, depth + 1)} ${_ops[r.nextInt(_ops.length)]} ${_expr(r, depth + 1)}',
  };
}

String _text(Random r) {
  const filters = ['', '|clock', '|upper', '|int', '| clock ', '|bad'];
  final parts = <String>[];
  for (var i = r.nextInt(4); i >= 0; i--) {
    switch (r.nextInt(6)) {
      case 0:
        parts.add(
          ['Armed by ', ' points', 'é ', '', 'x', '}}', '{{'][r.nextInt(7)],
        );
      case 1:
        parts.add('{${_expr(r, 2)}${filters[r.nextInt(filters.length)]}}');
      default:
        parts.add('{${_expr(r, 1)}${filters[r.nextInt(filters.length)]}}');
    }
  }
  return parts.join();
}

Map<String, Object?> _data(Random r) {
  Object? pick() => switch (r.nextInt(14)) {
    0 => r.nextInt(2000) - 500,
    1 => (r.nextInt(100000) - 20000) / 8, // exact ties at two decimals
    2 => r.nextDouble() * 1000,
    3 => ['red', 'blue', 'yellow', 'green', 'teal', '', 'Red'][r.nextInt(7)],
    4 => r.nextBool(),
    5 => null,
    6 => 0.125,
    7 => 2.675,
    8 => -0.001,
    9 => 1e15 + 0.5,
    10 => 1e21,
    11 => 1 / 3,
    12 => 'line\nbreak\ttab\u0000nul é',
    _ => 'x' * r.nextInt(300),
  };
  return {
    'a': pick(),
    'b': pick(),
    'n': pick(),
    's': pick(),
    't': true,
    'f': false,
    'team': ['red', 'blue', 'yellow', '', 'teal', null][r.nextInt(6)],
    'left': r.nextInt(5000) / 10,
    'obj': {
      'x': pick(),
      'y': {'z': pick()},
      's': 'inner',
    },
    'list': [1, 2],
    'nul': null,
    'long': 'L' * (200 + r.nextInt(100)),
    'tie': 0.375,
    'neg': -2.5,
    'big': 123456789012345.0,
    'huge': 1e22,
    'third': 2 / 3,
    'u': 'ünï ✓',
    'nl': 'a\nb',
  };
}

Map<String, Object?> _params(Random r) => {
  'fuse_s': [300, 0, 60.5, 'x', null][r.nextInt(5)],
  'n': r.nextInt(100),
  's': 'text',
};

void main() {
  late final AtalaiaCore core;
  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  group('shipped templates', () {
    final files = shippedTemplates();

    test('there are templates to check', () {
      expect(files.length, greaterThanOrEqualTo(10));
    });

    for (final f in files) {
      final name = f.uri.pathSegments.last;
      test('$name parses in Dart and in C, named after its file', () {
        final src = f.readAsStringSync();
        expect(core.checkScreen(src), isNull);
        final t = parseScreenTemplate(src);
        expect(t.name, name.substring(0, name.length - '.yaml'.length));
        expect(t.widgets, isNotEmpty);
      });
    }
  });

  test('mutated templates: Dart and C accept the same ones, with the same '
      'messages', () {
    final sources = [for (final f in shippedTemplates()) f.readAsStringSync()];
    const inserts = [
      '\t', ' ', ':', '- ', '{', '}', '"', "'", '#', '&a ', '*a', '!t ', //
      '|', '>', '[', ']', ',', '---\n', '...', '\n', '\r\n', 'x', r'\',
      r'\u00e9', r'\q', 'é', '\u0000', '  ', ': ', 'fill', '1000', '-1',
      '{x}', '{{', '}}', '{a|clock}', '{a|bad}', "'q'", '"q"', 'ok',
    ];
    const swaps = {
      'label': ['labl', 'icon', 'qr_code', 'spacer', 'row'],
      'font_size: 48': [
        'font_size: 5',
        'font_size: 201',
        'font_size: "48"',
        'font_size: +48',
        'font_size: 0x30',
        'font_size:',
      ],
      'fill': ['fil', '1001', '"fill"', '-5', ''],
      'center': ['middle', 'left', 'right'],
      'color: muted': [
        'color: teal',
        'color: "#12345"',
        'color: "#a1B2c3"',
        'color: MUTED',
        'color: "{team"',
        'color: contrast',
      ],
      'text:': ['txt:', 'value:', 'data:', 'icon:'],
      'visible: "{team}"': [
        'visible: "{team"',
        'visible: team',
        'visible: true',
        'visible: false',
        'visible: "{a|clock}"',
      ],
      'padding: { bottom: 10 }': [
        'padding: 10',
        'padding: { bottom: 201 }',
        'padding: { middle: 1 }',
        'padding: { bottom: "1" }',
      ],
      'type: spacer': ['type: spacer\n    style: {}', 'type: column'],
      'template:': ['templat:', 'template: Bad'],
      'layout:': ['layout: []', 'layouts:', 'layout: x'],
    };
    final r = Random(20261019);
    var accepted = 0, refused = 0;
    for (var n = 0; n < 2500; n++) {
      var s = sources[r.nextInt(sources.length)];
      for (var m = 1 + r.nextInt(2); m > 0; m--) {
        switch (r.nextInt(5)) {
          case 0:
            final at = r.nextInt(s.length + 1);
            s =
                s.substring(0, at) +
                inserts[r.nextInt(inserts.length)] +
                s.substring(at);
          case 1:
            final at = r.nextInt(s.length);
            final end = min(s.length, at + 1 + r.nextInt(10));
            s = s.substring(0, at) + s.substring(end);
          case 2:
            final lines = s.split('\n');
            final i = r.nextInt(lines.length);
            lines.insert(i, lines[i]);
            s = lines.join('\n');
          case 3:
            final lines = s.split('\n');
            final i = r.nextInt(lines.length), j = r.nextInt(lines.length);
            final x = lines[i];
            lines[i] = lines[j];
            lines[j] = x;
            s = lines.join('\n');
          default:
            final keys = swaps.keys.where(s.contains).toList();
            if (keys.isEmpty) break;
            final k = keys[r.nextInt(keys.length)];
            final options = swaps[k]!;
            s = s.replaceFirst(k, options[r.nextInt(options.length)]);
        }
      }
      final c = core.checkScreen(s);
      final d = screenTemplateError(s);
      expect(_cut(d), c ?? '', reason: 'template:\n$s');
      if (c == null) {
        accepted++;
      } else {
        refused++;
      }
    }
    // Both kinds must have been exercised.
    expect(accepted, greaterThan(100));
    expect(refused, greaterThan(500));
  });

  test('hand-written edge cases match too', () {
    final cases = [
      '',
      ' template: x\nlayout:\n  - type: label\n    text: a\n',
      'template: x\n',
      'template: x\nlayout:\n',
      'template: x\nlayout:\n  - type: label\n',
      'template: x\nlayout:\n  - type: icon\n    icon: nope\n',
      'template: x\nlayout:\n  - type: spacer\n',
      'template: x\nlayout:\n  - type: row\n',
      'template: x\nlayout:\n  - type: row\n    children: x\n',
      'template: x\nlayout:\n  - type: progress_bar\n    value: -1\n',
      'template: x\nlayout:\n  - type: progress_bar\n    value: inf\n',
      'template: x\nlayout:\n  - type: progress_bar\n    value: nan\n',
      'template: x\nlayout:\n  - type: progress_bar\n    value: "0x1p-1"\n',
      'template: x\nlayout:\n  - type: progress_bar\n    value: " 0.5"\n',
      'template: x\nlayout:\n  - type: progress_bar\n    value: "0.5 "\n',
      'template: x\nlayout:\n  - type: progress_bar\n    value: 1e-1\n',
      'template: x\nlayout:\n  - type: label\n    text: "{a|clock}"\n'
          '    style: { color: "{a|clock}" }\n',
      'template: x\nstyle: { foreground: red }\nlayout:\n  - type: label\n'
          '    text: a\n',
      'template: x\nlayout:\n  - type: label\n    text: "\\u0000"\n',
      'template: x\nlayout:\n  - type: label\n    text: "\\ud800"\n',
      'template: x\nlayout:\n  - type: label\n    text: "\\u00e9 \\" \\/"\n',
      "template: x\nlayout:\n  - type: label\n    text: 'it''s'\n",
      'template: x\nlayout:\n  - type: label\n    text: a: b\n',
      'template: x\nlayout:\n  - type: label\n    text: {a: b}\n',
      'template: x\nlayout:\n  - type: label\n    style: { font_size: 20,}\n'
          '    text: a\n',
      'template: x\nlayout:\n  - type: label\n    text: a\n  - type: label\n'
          '    text: "${'w' * 1600}"\n',
      'template: x\nlayout:\n${'  - type: label\n    text: a\n' * 33}',
      'template: x\nlayout:\n  - type: row\n    children:\n      - type: row\n'
          '        children:\n          - type: row\n            children:\n'
          '              - type: row\n                children:\n'
          '                  - type: row\n                    children:\n'
          '                      - type: label\n'
          '                        text: deep\n',
      'template: x\nlayout:\n  - type: label\n    text: a\n---\n',
      'template: x # a comment\nlayout: # list\n  - type: label # w\n'
          '    text: "#{1+1}" # not a comment inside quotes\n',
      'template: ${'n' * 32}\nlayout:\n  - type: label\n    text: a\n',
      'template: x\r\nlayout:\r\n  - type: label\r\n    text: crlf\r\n',
    ];
    for (final s in cases) {
      expect(
        _cut(screenTemplateError(s)),
        core.checkScreen(s) ?? '',
        reason: 'template:\n$s',
      );
    }
  });

  test('generated expressions: same check results as the core', () {
    final r = Random(1);
    for (var n = 0; n < 4000; n++) {
      final e = _expr(r, 0);
      expect(
        expressionError(e),
        core.screenExpressionError(e),
        reason: 'expression: $e',
      );
    }
  });

  test('generated texts: the same text as the core, filters included', () {
    final r = Random(2);
    for (var n = 0; n < 4000; n++) {
      final text = _text(r);
      final data = _data(r);
      final params = _params(r);
      expect(
        interpolate(text, TemplateScope(data: data, params: params)),
        core.screenText(text, data, params),
        reason: 'text: $text\ndata: $data\nparams: $params',
      );
    }
  });

  test('generated visible: and progress values: as the core reads them', () {
    final r = Random(3);
    const literals = [
      '0.5', '1', '2', ' 0.5', 'inf', 'nan', '-1', '0x1p-1', 'abc', '1e-1', //
      '', '0.004', '0.995', 'true', 'false', '{a}{b}', '1abc', '.5', 'INF',
    ];
    for (var n = 0; n < 3000; n++) {
      final data = _data(r);
      final params = _params(r);
      final scope = TemplateScope(data: data, params: params);
      final v = r.nextInt(3) == 0
          ? literals[r.nextInt(literals.length)]
          : '{${_expr(r, 1)}}';
      expect(
        isVisible(v, scope),
        core.screenTruthy(v, data, params),
        reason: 'visible: $v\ndata: $data',
      );
      final f = fraction(v, scope);
      final c = core.screenFraction(v, data, params);
      expect(f, c, reason: 'value: $v\ndata: $data');
    }
    expect(isVisible(null, const TemplateScope()), isTrue);
    expect(core.screenTruthy(null, const {}, const {}), isTrue);
    expect(fraction(null, const TemplateScope()), 0);
  });

  test('colour names as the core reads them', () {
    const names = [
      'red', 'RED', 'Red', 'bLuE', 'muted', 'teal', '', '#a1B2c3', '#12345', //
      '#GGGGGG', '#000000', 'Background', 'background', 'panel', 'danger',
      'accent', 'grey', 'gray', 'white', 'black', 'yellow', 'purple',
      'orange', 'green', '#ffffff1', 'team', 'contrast', 'r', 'redd',
    ];
    for (final n in names) {
      expect(paletteColor(n), core.screenColor(n), reason: n);
    }
  });

  test('numbers: whole, two decimals rounding ties to even, as printf', () {
    expect(formatNumber(5), '5');
    expect(formatNumber(-0.0), '0');
    expect(formatNumber(0.125), '0.12');
    expect(formatNumber(0.375), '0.38');
    expect(formatNumber(2.5), '2.5');
    expect(formatNumber(1 / 3), '0.33');
    expect(formatNumber(-0.001), '-0');
    expect(formatNumber(1e21), '1000000000000000000000');
    expect(formatNumber(double.nan), '0');
    expect(
      interpolate(
        '{a|clock} {b|clock} {c|clock}',
        const TemplateScope(data: {'a': 59.2, 'b': 3600, 'c': -5}),
      ),
      '1:00 1:00:00 0:00',
    );
  });
}
