// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The few DER (ITU-T X.690) forms a field CA's certificates and keys need
/// (controller/field_tls.dart): writing them, and reading back the ones the
/// app wrote. Definite lengths only, as DER requires.
library;

import 'dart:convert';
import 'dart:typed_data';

/// One DER value: its tag and its contents (a constructed value's contents
/// are its children, encoded).
final class Der {
  Der(this.tag, List<int> contents) : contents = Uint8List.fromList(contents);

  final int tag;
  final Uint8List contents;

  static const tagBoolean = 0x01;
  static const tagInteger = 0x02;
  static const tagBitString = 0x03;
  static const tagOctetString = 0x04;
  static const tagNull = 0x05;
  static const tagOid = 0x06;
  static const tagUtf8String = 0x0c;
  static const tagIa5String = 0x16;
  static const tagUtcTime = 0x17;
  static const tagGeneralizedTime = 0x18;
  static const tagSequence = 0x30;
  static const tagSet = 0x31;

  bool get constructed => tag & 0x20 != 0;

  /// The value, encoded: tag, length, contents.
  Uint8List get bytes {
    final out = BytesBuilder(copy: false)
      ..addByte(tag)
      ..add(_length(contents.length))
      ..add(contents);
    return out.toBytes();
  }

  static Uint8List _length(int n) {
    if (n < 0x80) return Uint8List.fromList([n]);
    final b = <int>[];
    for (var v = n; v > 0; v >>= 8) {
      b.insert(0, v & 0xff);
    }
    return Uint8List.fromList([0x80 | b.length, ...b]);
  }

  // --- writing ----------------------------------------------------------------

  static Der sequence(List<Der> items) => Der(tagSequence, _concat(items));

  static Der set(List<Der> items) => Der(tagSet, _concat(items));

  /// A context-specific constructed value ([n] EXPLICIT).
  static Der explicit(int n, Der inner) => Der(0xa0 | n, inner.bytes);

  /// A context-specific primitive value ([n] IMPLICIT of a primitive type).
  static Der implicit(int n, List<int> contents) => Der(0x80 | n, contents);

  static Der boolean(bool v) => Der(tagBoolean, [v ? 0xff : 0x00]);

  static Der integer(BigInt v) {
    if (v.isNegative) throw ArgumentError.value(v, 'v', 'not negative');
    var b = unsignedBytes(v);
    if (b.isEmpty) b = Uint8List(1);
    if (b[0] & 0x80 != 0) b = Uint8List.fromList([0, ...b]);
    return Der(tagInteger, b);
  }

  static Der smallInteger(int v) => integer(BigInt.from(v));

  /// A bit string with no unused bits.
  static Der bitString(List<int> bits, {int unused = 0}) =>
      Der(tagBitString, [unused, ...bits]);

  static Der octetString(List<int> v) => Der(tagOctetString, v);

  static Der utf8String(String s) => Der(tagUtf8String, utf8.encode(s));

  static Der oid(String dotted) {
    final parts = dotted.split('.').map(int.parse).toList();
    final out = <int>[parts[0] * 40 + parts[1]];
    for (final p in parts.skip(2)) {
      final chunk = <int>[p & 0x7f];
      for (var v = p >> 7; v > 0; v >>= 7) {
        chunk.insert(0, 0x80 | (v & 0x7f));
      }
      out.addAll(chunk);
    }
    return Der(tagOid, out);
  }

  /// UTCTime up to 2049, GeneralizedTime from 2050 (RFC 5280 4.1.2.5).
  static Der time(DateTime t) {
    final u = t.toUtc();
    String two(int v) => v.toString().padLeft(2, '0');
    final rest =
        '${two(u.month)}${two(u.day)}${two(u.hour)}${two(u.minute)}${two(u.second)}Z';
    if (u.year >= 1950 && u.year < 2050) {
      return Der(tagUtcTime, ascii.encode('${two(u.year % 100)}$rest'));
    }
    return Der(tagGeneralizedTime, ascii.encode('${u.year}$rest'));
  }

  static Uint8List _concat(List<Der> items) {
    final b = BytesBuilder(copy: false);
    for (final i in items) {
      b.add(i.bytes);
    }
    return b.toBytes();
  }

  // --- reading ----------------------------------------------------------------

  /// The one value [bytes] holds (nothing may follow it).
  static Der parse(List<int> bytes) {
    final data = Uint8List.fromList(bytes);
    final (value, end) = _read(data, 0);
    if (end != data.length) throw const FormatException('DER: trailing bytes');
    return value;
  }

  /// A constructed value's children.
  List<Der> get children {
    if (!constructed) throw const FormatException('DER: not constructed');
    final out = <Der>[];
    var at = 0;
    while (at < contents.length) {
      final (v, end) = _read(contents, at);
      out.add(v);
      at = end;
    }
    return out;
  }

  /// An INTEGER's value (not negative).
  BigInt get asInteger {
    if (tag != tagInteger) throw const FormatException('DER: not an INTEGER');
    return bigIntOf(contents);
  }

  static (Der, int) _read(Uint8List data, int at) {
    if (at + 2 > data.length) throw const FormatException('DER: cut short');
    final tag = data[at];
    var len = data[at + 1];
    var pos = at + 2;
    if (len & 0x80 != 0) {
      final n = len & 0x7f;
      if (n == 0 || n > 4 || pos + n > data.length) {
        throw const FormatException('DER: bad length');
      }
      len = 0;
      for (var i = 0; i < n; i++) {
        len = (len << 8) | data[pos + i];
      }
      pos += n;
    }
    if (pos + len > data.length) throw const FormatException('DER: cut short');
    return (Der(tag, data.sublist(pos, pos + len)), pos + len);
  }
}

/// [v] as big-endian bytes, as short as it goes ([] for 0).
Uint8List unsignedBytes(BigInt v) {
  final out = <int>[];
  for (var x = v; x > BigInt.zero; x >>= 8) {
    out.insert(0, (x & BigInt.from(0xff)).toInt());
  }
  return Uint8List.fromList(out);
}

/// [v] as exactly [length] big-endian bytes.
Uint8List fixedBytes(BigInt v, int length) {
  final b = unsignedBytes(v);
  if (b.length > length) throw ArgumentError.value(v, 'v', 'too large');
  return Uint8List(length)..setRange(length - b.length, length, b);
}

BigInt bigIntOf(List<int> bytes) {
  var v = BigInt.zero;
  for (final b in bytes) {
    v = (v << 8) | BigInt.from(b);
  }
  return v;
}

/// [der] as PEM with [label] ("CERTIFICATE", "PRIVATE KEY").
String toPem(String label, List<int> der) {
  final b64 = base64.encode(der);
  final lines = [
    for (var i = 0; i < b64.length; i += 64)
      b64.substring(i, i + 64 > b64.length ? b64.length : i + 64),
  ];
  return '-----BEGIN $label-----\n${lines.join('\n')}\n-----END $label-----\n';
}

/// The DER of every PEM block labelled [label] in [pem], in order.
List<Uint8List> fromPem(String pem, String label) {
  final re = RegExp(
    '-----BEGIN $label-----([A-Za-z0-9+/=\\s]+)-----END $label-----',
  );
  return [
    for (final m in re.allMatches(pem))
      base64.decode(m.group(1)!.replaceAll(RegExp(r'\s'), '')),
  ];
}
