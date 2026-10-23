// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// AES-128-CCM (RFC 3610, NIST SP 800-38C) with a 13-byte nonce and an
/// 8-byte MIC, as the field frames (protocol/field-frames.md) and the
/// pairing code's sealed key (protocol/adoption.md section 7) use it: the
/// Dart twin of the cryptography library's `AESCCM(key, tag_length=8)` in
/// the controller and the simulator, and of mbedtls's in the firmware.
///
/// Only the AES block function comes from pointycastle (AESEngine); the
/// CBC-MAC and the counter mode are written here, small enough to read
/// against RFC 3610 section 2, and checked by the shared vectors
/// (protocol/vectors/field_frame.json, pairing.json).
library;

import 'dart:typed_data';

import 'package:pointycastle/export.dart' as pc;

import 'bytes.dart';

const ccmNonceSize = 13;
const ccmMicSize = 8;

/// A sealed message that does not open: another key, or altered.
class CcmException implements Exception {
  CcmException(this.message);
  final String message;
  @override
  String toString() => 'CcmException: $message';
}

pc.BlockCipher _aes(List<int> key) {
  if (key.length != 16) throw ArgumentError('an AES-128 key is 16 bytes');
  return pc.AESEngine()..init(true, pc.KeyParameter(Uint8List.fromList(key)));
}

// L = 15 - 13 = 2: the message length takes two bytes, M = 8.
const _l = 15 - ccmNonceSize;

Uint8List _mac(
  pc.BlockCipher aes,
  List<int> nonce,
  List<int> aad,
  List<int> m,
) {
  final b0 = Uint8List(16);
  b0[0] = (aad.isNotEmpty ? 0x40 : 0) | ((ccmMicSize - 2) ~/ 2) << 3 | (_l - 1);
  b0.setRange(1, 1 + ccmNonceSize, nonce);
  b0[14] = m.length >> 8 & 0xff;
  b0[15] = m.length & 0xff;
  final blocks = BytesBuilder()..add(b0);
  if (aad.isNotEmpty) {
    // Associated data under 0xff00 bytes: its length in two bytes.
    final a = BytesBuilder()
      ..add([aad.length >> 8 & 0xff, aad.length & 0xff])
      ..add(aad);
    blocks.add(_padded(a.toBytes()));
  }
  blocks.add(_padded(m));
  final data = blocks.toBytes();
  var x = Uint8List(16);
  final out = Uint8List(16);
  for (var i = 0; i < data.length; i += 16) {
    for (var j = 0; j < 16; j++) {
      x[j] ^= data[i + j];
    }
    aes.processBlock(x, 0, out, 0);
    x = Uint8List.fromList(out);
  }
  return Uint8List.sublistView(x, 0, ccmMicSize);
}

Uint8List _padded(List<int> b) {
  final n = (b.length + 15) ~/ 16 * 16;
  return Uint8List(n)..setRange(0, b.length, b);
}

/// The counter block A_i's keystream block.
Uint8List _s(pc.BlockCipher aes, List<int> nonce, int i) {
  final a = Uint8List(16);
  a[0] = _l - 1;
  a.setRange(1, 1 + ccmNonceSize, nonce);
  a[14] = i >> 8 & 0xff;
  a[15] = i & 0xff;
  final out = Uint8List(16);
  aes.processBlock(a, 0, out, 0);
  return out;
}

Uint8List _ctr(pc.BlockCipher aes, List<int> nonce, List<int> data) {
  final out = Uint8List(data.length);
  for (var i = 0; i < data.length; i += 16) {
    final s = _s(aes, nonce, i ~/ 16 + 1);
    for (var j = 0; j < 16 && i + j < data.length; j++) {
      out[i + j] = data[i + j] ^ s[j];
    }
  }
  return out;
}

void _checkNonce(List<int> nonce) {
  if (nonce.length != ccmNonceSize) {
    throw ArgumentError('a CCM nonce here is $ccmNonceSize bytes');
  }
}

/// The ciphertext followed by the 8-byte MIC.
Uint8List ccmSeal(
  List<int> key,
  List<int> nonce,
  List<int> plaintext,
  List<int> aad,
) {
  _checkNonce(nonce);
  if (plaintext.length > 0xffff) throw ArgumentError('too long for CCM here');
  final aes = _aes(key);
  final t = _mac(aes, nonce, aad, plaintext);
  final s0 = _s(aes, nonce, 0);
  return Uint8List.fromList([
    ..._ctr(aes, nonce, plaintext),
    for (var j = 0; j < ccmMicSize; j++) t[j] ^ s0[j],
  ]);
}

/// The plaintext of [sealed] (ciphertext and MIC); [CcmException] when the
/// MIC does not match.
Uint8List ccmOpen(
  List<int> key,
  List<int> nonce,
  List<int> sealed,
  List<int> aad,
) {
  _checkNonce(nonce);
  if (sealed.length < ccmMicSize) throw CcmException('shorter than its MIC');
  final aes = _aes(key);
  final n = sealed.length - ccmMicSize;
  final plain = _ctr(aes, nonce, sealed.sublist(0, n));
  final s0 = _s(aes, nonce, 0);
  final t = _mac(aes, nonce, aad, plain);
  final got = [for (var j = 0; j < ccmMicSize; j++) sealed[n + j] ^ s0[j]];
  if (!constantTimeEquals(t, got)) {
    throw CcmException('the MIC does not match');
  }
  return plain;
}
