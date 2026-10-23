// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// CPace, CPACE-X25519-SHA512 (draft-irtf-cfrg-cpace-14): the pairing
/// code's key exchange (protocol/adoption.md section 7, decision AD-10), for
/// the Android field controller (slice S7c of PE24). The Dart twin of
/// simulator/atalaia_sim/cpace.py and firmware/esp32/main/cpace.c; all check
/// protocol/vectors/pairing.json (the draft's Appendix B.1 and B.1.10).
///
/// X25519 is RFC 7748's Montgomery ladder on Dart's BigInt (any
/// u-coordinate, the top bit masked, the scalar clamped), Elligator 2 on
/// Curve25519 RFC 9380 section 6.7.1's map (Z = 2), SHA-512 the crypto
/// package's. Speed is no concern: a run does three scalar multiplications.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

final _p = (BigInt.one << 255) - BigInt.from(19);
final _a = BigInt.from(486662);
final _a24 = BigInt.from(121665);
const _sInBytes = 128; // SHA-512's input block
const cpaceFieldSize = 32;

class CpaceException implements Exception {
  CpaceException(this.message);
  final String message;
  @override
  String toString() => 'CpaceException: $message';
}

/// The draft's prepend_len: the length as LEB128, then the bytes.
Uint8List prependLen(List<int> data) {
  final out = <int>[];
  var n = data.length;
  while (true) {
    if (n < 128) {
      out.add(n);
      break;
    }
    out.add(n & 0x7f | 0x80);
    n >>= 7;
  }
  return Uint8List.fromList([...out, ...data]);
}

Uint8List lvCat(List<List<int>> parts) =>
    Uint8List.fromList([for (final p in parts) ...prependLen(p)]);

final _dsi = utf8.encode('CPace255');

Uint8List cpaceGeneratorString(List<int> prs, List<int> ci, List<int> sid) {
  var zpad = _sInBytes - prependLen(prs).length - prependLen(_dsi).length - 1;
  if (zpad < 0) zpad = 0;
  return lvCat([_dsi, prs, Uint8List(zpad), ci, sid]);
}

BigInt _le(List<int> b) {
  var x = BigInt.zero;
  for (var i = b.length - 1; i >= 0; i--) {
    x = (x << 8) | BigInt.from(b[i]);
  }
  return x;
}

Uint8List _toLe(BigInt x) {
  final out = Uint8List(cpaceFieldSize);
  var v = x;
  final mask = BigInt.from(0xff);
  for (var i = 0; i < cpaceFieldSize; i++) {
    out[i] = (v & mask).toInt();
    v >>= 8;
  }
  return out;
}

BigInt _elligator2(BigInt r) {
  final x1 =
      (-_a * (BigInt.one + BigInt.two * r * r).modPow(_p - BigInt.two, _p)) %
      _p;
  final gx1 = (x1 * x1 * x1 + _a * x1 * x1 + x1) % _p;
  final e = gx1.modPow((_p - BigInt.one) >> 1, _p);
  if (e == BigInt.zero || e == BigInt.one) return x1;
  return (-x1 - _a) % _p;
}

/// The generator g: Elligator 2 of the first 32 bytes of
/// SHA-512(generator string), read as 255 bits and reduced.
Uint8List cpaceGenerator(List<int> prs, List<int> ci, List<int> sid) {
  final h = sha512
      .convert(cpaceGeneratorString(prs, ci, sid))
      .bytes
      .sublist(0, cpaceFieldSize);
  final r = (_le(h) & ((BigInt.one << 255) - BigInt.one)) % _p;
  return _toLe(_elligator2(r));
}

/// X25519(scalar, point) with RFC 7748's clamping; all zeros for the
/// neutral element.
Uint8List x25519(List<int> scalar, List<int> point) {
  if (scalar.length != 32 || point.length != 32) {
    throw ArgumentError('X25519 takes 32-byte scalars and points');
  }
  final k = Uint8List.fromList(scalar);
  k[0] &= 248;
  k[31] &= 127;
  k[31] |= 64;
  final n = _le(k);
  final x1 = (_le(point) & ((BigInt.one << 255) - BigInt.one)) % _p;
  var x2 = BigInt.one, z2 = BigInt.zero, x3 = x1, z3 = BigInt.one;
  var swap = 0;
  for (var t = 254; t >= 0; t--) {
    final bit = ((n >> t) & BigInt.one).toInt();
    swap ^= bit;
    if (swap == 1) {
      (x2, x3) = (x3, x2);
      (z2, z3) = (z3, z2);
    }
    swap = bit;
    final a = (x2 + z2) % _p;
    final aa = a * a % _p;
    final b = (x2 - z2) % _p;
    final bb = b * b % _p;
    final e = (aa - bb) % _p;
    final c = (x3 + z3) % _p;
    final d = (x3 - z3) % _p;
    final da = d * a % _p;
    final cb = c * b % _p;
    final s = (da + cb) % _p;
    x3 = s * s % _p;
    final m = (da - cb) % _p;
    z3 = x1 * (m * m % _p) % _p;
    x2 = aa * bb % _p;
    z2 = e * ((aa + _a24 * e) % _p) % _p;
  }
  if (swap == 1) {
    (x2, x3) = (x3, x2);
    (z2, z3) = (z3, z2);
  }
  return _toLe(x2 * z2.modPow(_p - BigInt.two, _p) % _p);
}

/// As [x25519]; [CpaceException] for the neutral element (the abort case).
Uint8List x25519Verified(List<int> scalar, List<int> point) {
  final out = x25519(scalar, point);
  if (out.every((b) => b == 0)) {
    throw CpaceException("the peer's point is of low order");
  }
  return out;
}

/// ISK = SHA-512(lv_cat("CPace255_ISK", sid, K) || lv_cat(Ya, ADa) || lv_cat(Yb, ADb)).
Uint8List cpaceIskIr(
  List<int> sid,
  List<int> k,
  List<int> ya,
  List<int> ada,
  List<int> yb,
  List<int> adb,
) => Uint8List.fromList(
  sha512.convert([
    ...lvCat([utf8.encode('CPace255_ISK'), sid, k]),
    ...lvCat([ya, ada]),
    ...lvCat([yb, adb]),
  ]).bytes,
);
