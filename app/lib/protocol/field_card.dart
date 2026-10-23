// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The NFC field card (protocol/adoption.md section 4): the Dart twin of
/// simulator/atalaia_sim/field_card.py and firmware/esp32/main/adoption.c,
/// checked against protocol/vectors/field_card.json. A field card carries
/// the field's 32-byte join key, the field's master secret, and its name:
///
///     version (1, = 1) | name_len (1, 0-48) | name (UTF-8) | join_key (32) | check (8)
///
/// check = HMAC-SHA256(join_key, "atalaia-field-card" | version | name_len |
/// name)[:8]: it catches a card written wrong and ties the name to the key;
/// it is no signature. The record's MIME type is application/vnd.atalaia.field.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import '../security/bytes.dart';
import '../security/ndef.dart';

const fieldCardNdefType = 'application/vnd.atalaia.field';
const fieldCardKeySize = 32;
const fieldCardNameMax = 48;
const _checkSize = 8;
const _minLen = 2 + fieldCardKeySize + _checkSize;
const _maxLen = _minLen + fieldCardNameMax;

class FieldCardException implements Exception {
  FieldCardException(this.reason, this.message);

  /// One of the vectors' reasons: length, version, name, check (or key).
  final String reason;
  final String message;
  @override
  String toString() => 'FieldCardException($reason): $message';
}

/// The field's fingerprint, "XXXX-XXXX" (nothing of the key can be read
/// from it).
String fieldFingerprint(List<int> joinKey) {
  if (joinKey.length != fieldCardKeySize) {
    throw ArgumentError('the join key is 32 bytes');
  }
  final d = hexEncode(
    Hmac(
      sha256,
      joinKey,
    ).convert(utf8.encode('atalaia-field-fingerprint')).bytes.sublist(0, 4),
  ).toUpperCase();
  return '${d.substring(0, 4)}-${d.substring(4)}';
}

/// 0-48 bytes of UTF-8 without control characters, '"' or '\'.
bool fieldCardNameOk(List<int> raw) {
  if (raw.length > fieldCardNameMax) return false;
  for (final b in raw) {
    if (b < 0x20 || b == 0x7f || b == 0x22 || b == 0x5c) return false;
  }
  try {
    utf8.decode(raw);
  } on FormatException {
    return false;
  }
  return true;
}

bool _printable(int c) {
  if (c < 0x20 || (c >= 0x7f && c <= 0xa0)) return false;
  // Python's str.isprintable() also refuses these separators and format
  // characters a name might pick up from a paste.
  if (c == 0xad ||
      (c >= 0x2000 && c <= 0x200f) ||
      (c >= 0x2028 && c <= 0x202f)) {
    return false;
  }
  if ((c >= 0x205f && c <= 0x206f) || c == 0x3000 || c == 0xfeff) return false;
  return true;
}

/// A field's display name made fit for a card: the characters a card
/// refuses dropped, then cut to 48 bytes of UTF-8 on a character boundary
/// (field_card.py `clean_name`).
String cleanFieldName(String text) {
  final kept = String.fromCharCodes(
    text.runes.where((c) => _printable(c) && c != 0x22 && c != 0x5c),
  ).trim();
  final out = StringBuffer();
  var n = 0;
  for (final c in kept.runes) {
    final w = utf8.encode(String.fromCharCode(c)).length;
    if (n + w > fieldCardNameMax) break;
    out.writeCharCode(c);
    n += w;
  }
  return out.toString().trim();
}

Uint8List _check(List<int> key, List<int> head) => Uint8List.fromList(
  Hmac(sha256, key)
      .convert([...utf8.encode('atalaia-field-card'), ...head])
      .bytes
      .sublist(0, _checkSize),
);

Uint8List encodeFieldCard(List<int> joinKey, [String name = '']) {
  if (joinKey.length != fieldCardKeySize) {
    throw FieldCardException('key', 'the join key is 32 bytes');
  }
  final raw = utf8.encode(name);
  if (!fieldCardNameOk(raw)) {
    throw FieldCardException(
      'name',
      'the name: 0-48 bytes, no control characters',
    );
  }
  final head = [1, raw.length, ...raw];
  return Uint8List.fromList([...head, ...joinKey, ..._check(joinKey, head)]);
}

/// The card's key, name and fingerprint; [FieldCardException] otherwise.
({Uint8List joinKey, String name, String fingerprint}) decodeFieldCard(
  List<int> data,
) {
  if (data.length < _minLen || data.length > _maxLen) {
    throw FieldCardException(
      'length',
      'a field card is $_minLen-$_maxLen bytes',
    );
  }
  if (data[0] != 1) throw FieldCardException('version', 'version ${data[0]}');
  final n = data[1];
  if (n > fieldCardNameMax || data.length != _minLen + n) {
    throw FieldCardException('length', "the name's length does not match");
  }
  final raw = data.sublist(2, 2 + n);
  if (!fieldCardNameOk(raw)) {
    throw FieldCardException('name', 'the name is not clean UTF-8');
  }
  final key = Uint8List.fromList(data.sublist(2 + n, 2 + n + fieldCardKeySize));
  if (!constantTimeEquals(
    _check(key, data.sublist(0, 2 + n)),
    data.sublist(2 + n + fieldCardKeySize),
  )) {
    throw FieldCardException('check', "the card's check does not match");
  }
  return (
    joinKey: key,
    name: utf8.decode(raw),
    fingerprint: fieldFingerprint(key),
  );
}

/// An NTAG215/216's user memory from page 4 for the card.
Uint8List fieldCardTag(List<int> payload) =>
    type2Memory(payload, fieldCardNdefType);

/// The NDEF message (one MIME record) a phone's NFC writes for the card.
Uint8List fieldCardNdefMessage(List<int> payload) =>
    ndefMimeRecord(payload, fieldCardNdefType);
