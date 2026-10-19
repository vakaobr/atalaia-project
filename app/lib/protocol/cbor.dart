// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The CBOR subset (RFC 8949) every Atalaia payload uses: the Dart twin of
/// simulator/atalaia_sim/cbor.py and the C codecs (core/src/codec.c,
/// core/src/proxy.c, core/src/join.c).
///
/// Encodes integers, text, byte strings, lists, maps, booleans, null and
/// doubles: integers and lengths in their shortest form, doubles in the
/// shortest of half, single or double precision that keeps the value, map
/// entries in their order. The decoder refuses everything else: tags,
/// indefinite lengths, undefined and other simple values, duplicate map
/// keys, NaN and infinity, containers nested more than [cborMaxDepth] deep
/// and trailing bytes. Byte strings are accepted only with `allowBytes`.
/// Maps decode to `Map<Object, Object?>` in their order (keys are int or
/// String); byte strings to [Uint8List].
library;

import 'dart:convert';
import 'dart:typed_data';

/// Arrays and maps nested inside each other.
const int cborMaxDepth = 17;

class CborException implements Exception {
  CborException(this.message);
  final String message;
  @override
  String toString() => 'CborException: $message';
}

// ---- encoding -----------------------------------------------------------------

void _head(BytesBuilder out, int major, int value) {
  if (value < 24) {
    out.addByte(major << 5 | value);
  } else if (value < 0x100) {
    out
      ..addByte(major << 5 | 24)
      ..addByte(value);
  } else if (value < 0x10000) {
    out
      ..addByte(major << 5 | 25)
      ..add([value >> 8, value & 0xff]);
  } else if (value < 0x100000000) {
    out
      ..addByte(major << 5 | 26)
      ..add([
        (value >> 24) & 0xff,
        (value >> 16) & 0xff,
        (value >> 8) & 0xff,
        value & 0xff,
      ]);
  } else {
    final b = ByteData(8)..setUint64(0, value);
    out
      ..addByte(major << 5 | 27)
      ..add(b.buffer.asUint8List());
  }
}

/// A double as an IEEE 754 half-precision value, if it is exactly one.
int? _half(double x) {
  if (x == 0) return x.isNegative ? 0x8000 : 0;
  final sign = x.isNegative ? 0x8000 : 0;
  final a = x.abs();
  // Normal halves: 2^-14 .. 65504; subnormals: multiples of 2^-24 below 2^-14.
  if (a >= 6.103515625e-05 && a <= 65504) {
    var e = 0;
    var m = a;
    while (m >= 2) {
      m /= 2;
      e++;
    }
    while (m < 1) {
      m *= 2;
      e--;
    }
    final frac = (m - 1) * 1024;
    if (frac != frac.truncateToDouble()) return null;
    return sign | ((e + 15) << 10) | frac.toInt();
  }
  if (a < 6.103515625e-05) {
    final f = a / 5.960464477539063e-08; // 2^-24
    if (f != f.truncateToDouble() || f >= 1024) return null;
    return sign | f.toInt();
  }
  return null;
}

void _double(BytesBuilder out, double x) {
  if (!x.isFinite) throw CborException('NaN and infinity are not allowed');
  final h = _half(x);
  if (h != null) {
    out
      ..addByte(0xf9)
      ..add([h >> 8, h & 0xff]);
    return;
  }
  final f = ByteData(4)..setFloat32(0, x);
  if (f.getFloat32(0) == x) {
    out
      ..addByte(0xfa)
      ..add(f.buffer.asUint8List());
    return;
  }
  final d = ByteData(8)..setFloat64(0, x);
  out
    ..addByte(0xfb)
    ..add(d.buffer.asUint8List());
}

void _encode(BytesBuilder out, Object? value, int depth) {
  if ((value is List || value is Map) && depth >= cborMaxDepth) {
    throw CborException('containers nested more than $cborMaxDepth deep');
  }
  switch (value) {
    case null:
      out.addByte(0xf6);
    case true:
      out.addByte(0xf5);
    case false:
      out.addByte(0xf4);
    case final int n:
      if (n >= 0) {
        _head(out, 0, n);
      } else {
        _head(out, 1, -1 - n);
      }
    case final double x:
      _double(out, x);
    case final String s:
      final raw = utf8.encode(s);
      _head(out, 3, raw.length);
      out.add(raw);
    case final Uint8List b:
      _head(out, 2, b.length);
      out.add(b);
    case final List<Object?> l:
      _head(out, 4, l.length);
      for (final v in l) {
        _encode(out, v, depth + 1);
      }
    case final Map<Object?, Object?> m:
      _head(out, 5, m.length);
      for (final e in m.entries) {
        final k = e.key;
        if (k is! String && k is! int) {
          throw CborException('map keys must be text or integers');
        }
        _encode(out, k, depth + 1);
        _encode(out, e.value, depth + 1);
      }
    default:
      throw CborException('cannot encode ${value.runtimeType}');
  }
}

Uint8List cborEncode(Object? value) {
  final out = BytesBuilder(copy: false);
  _encode(out, value, 0);
  return out.takeBytes();
}

// ---- decoding -----------------------------------------------------------------

class _Decoder {
  _Decoder(this.data, this.allowBytes);

  final Uint8List data;
  final bool allowBytes;
  var pos = 0;

  Uint8List take(int n) {
    if (n > data.length - pos) throw CborException('truncated');
    final chunk = Uint8List.sublistView(data, pos, pos + n);
    pos += n;
    return chunk;
  }

  (int, int, int) head() {
    final initial = take(1)[0];
    final major = initial >> 5, ai = initial & 0x1f;
    if (ai < 24) return (major, ai, ai);
    if (ai <= 27) {
      final b = take(1 << (ai - 24));
      var v = 0;
      if (ai == 27) {
        final hi = ByteData.sublistView(b).getUint32(0);
        if (hi >= 0x80000000) throw CborException('integer out of range');
        v = ByteData.sublistView(b).getInt64(0);
      } else {
        for (final x in b) {
          v = v << 8 | x;
        }
      }
      return (major, ai, v);
    }
    throw CborException(
      'indefinite lengths and reserved values are not allowed',
    );
  }

  int count(int n) {
    if (n > data.length - pos) throw CborException('truncated');
    return n;
  }

  Object? value(int depth) {
    final (major, ai, n) = head();
    if ((major == 4 || major == 5) && depth >= cborMaxDepth) {
      throw CborException('containers nested more than $cborMaxDepth deep');
    }
    switch (major) {
      case 0:
        return n;
      case 1:
        return -1 - n;
      case 2 when allowBytes:
        return Uint8List.fromList(take(n));
      case 3:
        try {
          return utf8.decode(take(n));
        } on FormatException {
          throw CborException('text is not valid UTF-8');
        }
      case 4:
        return [for (var i = count(n); i > 0; i--) value(depth + 1)];
      case 5:
        final out = <Object, Object?>{};
        for (var i = count(n); i > 0; i--) {
          final k = value(depth + 1);
          if (k == null || (k is! String && k is! int)) {
            throw CborException('map keys must be text or integers');
          }
          if (out.containsKey(k)) throw CborException('duplicate map key $k');
          out[k] = value(depth + 1);
        }
        return out;
      case 7:
        switch (ai) {
          case 20:
            return false;
          case 21:
            return true;
          case 22:
            return null;
          case 25 || 26 || 27:
            final bd = ByteData(8);
            final double x;
            if (ai == 25) {
              x = _fromHalf(n);
            } else if (ai == 26) {
              bd.setUint32(0, n);
              x = bd.getFloat32(0);
            } else {
              bd.setInt64(0, n);
              x = bd.getFloat64(0);
            }
            if (!x.isFinite) {
              throw CborException('NaN and infinity are not allowed');
            }
            return x;
        }
        throw CborException('undefined and simple values are not allowed');
    }
    throw CborException('byte strings and tags are not allowed');
  }
}

double _fromHalf(int h) {
  final sign = (h & 0x8000) != 0 ? -1.0 : 1.0;
  final e = (h >> 10) & 0x1f, m = h & 0x3ff;
  if (e == 0) return sign * m * 5.960464477539063e-08;
  if (e == 31) return m == 0 ? sign * double.infinity : double.nan;
  return sign * (1 + m / 1024) * _pow2(e - 15);
}

double _pow2(int e) {
  var v = 1.0;
  for (var i = 0; i < e.abs(); i++) {
    v *= 2;
  }
  return e < 0 ? 1 / v : v;
}

/// Decodes one CBOR item that must take all of [data].
Object? cborDecode(List<int> data, {bool allowBytes = false}) {
  final d = _Decoder(Uint8List.fromList(data), allowBytes);
  final v = d.value(0);
  if (d.pos != d.data.length) throw CborException('trailing bytes');
  return v;
}
