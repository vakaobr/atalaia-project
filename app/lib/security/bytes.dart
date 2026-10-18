// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Small byte helpers shared by the tag, token and chrono code.
library;

import 'dart:convert';
import 'dart:typed_data';

/// Lowercase hex, two digits per byte.
String hexEncode(List<int> bytes) {
  final out = StringBuffer();
  for (final b in bytes) {
    out.write((b & 0xff).toRadixString(16).padLeft(2, '0'));
  }
  return out.toString();
}

/// The bytes of an even-length hex string (either case).
Uint8List hexDecode(String hex) {
  if (hex.length.isOdd || !RegExp(r'^[0-9a-fA-F]*$').hasMatch(hex)) {
    throw FormatException('not hex', hex);
  }
  final out = Uint8List(hex.length ~/ 2);
  for (var i = 0; i < out.length; i++) {
    out[i] = int.parse(hex.substring(2 * i, 2 * i + 2), radix: 16);
  }
  return out;
}

/// Compares two byte strings in time that depends only on their length.
bool constantTimeEquals(List<int> a, List<int> b) {
  if (a.length != b.length) return false;
  var diff = 0;
  for (var i = 0; i < a.length; i++) {
    diff |= (a[i] ^ b[i]) & 0xff;
  }
  return diff == 0;
}

/// base64url without padding (RFC 4648 section 5).
String base64UrlNoPad(List<int> bytes) =>
    base64Url.encode(bytes).replaceAll('=', '');

final _base64Url = RegExp(r'^[A-Za-z0-9_-]+$');

/// The bytes of [text] if it is canonical base64url without padding, else null.
Uint8List? base64UrlNoPadDecode(String text) {
  if (!_base64Url.hasMatch(text) || text.length % 4 == 1) return null;
  final Uint8List raw;
  try {
    raw = base64Url.decode(text.padRight((text.length + 3) ~/ 4 * 4, '='));
  } on FormatException {
    return null;
  }
  return base64UrlNoPad(raw) == text ? raw : null;
}

final _base64 = RegExp(r'^[A-Za-z0-9+/]*={0,2}$');

/// The bytes of [text] if it is canonical standard base64 with padding, else null.
Uint8List? base64DecodeCanonical(String text) {
  if (!_base64.hasMatch(text) || text.length % 4 != 0) return null;
  final Uint8List raw;
  try {
    raw = base64.decode(text);
  } on FormatException {
    return null;
  }
  return base64.encode(raw) == text ? raw : null;
}
