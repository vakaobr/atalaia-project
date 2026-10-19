// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The check-in poster's text (protocol/checkin.md, ADR-P3-13): the Dart
/// side of controller/atalaia_controller/checkin_poster.py, checked against
/// the same vectors (protocol/vectors/checkin.json).
///
///     atalaia:checkin:<base64url, no padding, of: version (1) | CBOR map>
///
/// The poster holds the field's id and name, the controller's https
/// addresses, the SHA-256 of the field CA's certificate (the app pins it per
/// field on the first scan, lib/checkin/field_trust.dart), and optionally the
/// Wi-Fi network's name and one game. It carries no secret and no MAC.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'cbor.dart';
import 'join_payload.dart' show httpsBaseUrlOk;

const int posterVersion = 1;
const int posterMaxLength = 192;
const String posterTextPrefix = 'atalaia:checkin:';

/// Why a poster is refused: its text, its length, its version or its body.
enum PosterFailure { text, length, version, body }

class PosterException implements Exception {
  PosterException(this.reason, this.message);
  final PosterFailure reason;
  final String message;
  @override
  String toString() => 'PosterException(${reason.name}): $message';
}

final _fieldId = RegExp(r'^[A-Za-z0-9._:-]{1,64}$');

bool _printable(String s) => s.runes.every(
  (c) =>
      !(c < 0x20 || (c >= 0x7f && c <= 0x9f) || (c >= 0xd800 && c <= 0xdfff)),
);

final class CheckinPoster {
  CheckinPoster({
    required this.fieldId,
    required this.fieldName,
    required this.urls,
    required this.caSha256,
    this.wifiSsid,
    this.gameId,
  });

  final String fieldId;
  final String fieldName;

  /// 1-3 https base addresses of the controller, tried in order.
  final List<String> urls;

  /// SHA-256 of the field CA's DER certificate.
  final Uint8List caSha256;
  final String? wifiSsid;

  /// A poster pinned to one game; null: every game open for check-in.
  final int? gameId;

  /// The fingerprint's short form people compare: `XXXX XXXX XXXX XXXX`.
  String get caShort => shortFingerprint(caSha256);

  @override
  String toString() => 'CheckinPoster($fieldId, $fieldName, $urls)';
}

/// The first 8 bytes of a fingerprint as 4 groups of 4 uppercase hex digits.
String shortFingerprint(List<int> sha256) {
  final h = sha256
      .take(8)
      .map((b) => b.toRadixString(16).padLeft(2, '0'))
      .join()
      .toUpperCase();
  return [for (var i = 0; i < 16; i += 4) h.substring(i, i + 4)].join(' ');
}

PosterException _body(String why) => PosterException(PosterFailure.body, why);

CheckinPoster _validate(Map<String, Object?> p) {
  for (final k in ['field_id', 'field_name', 'urls', 'ca_sha256']) {
    if (p[k] == null) throw _body('missing poster field $k');
  }
  final fid = p['field_id'];
  if (fid is! String || !_fieldId.hasMatch(fid)) {
    throw _body('field_id: 1-64 of A-Z a-z 0-9 . _ : -');
  }
  final name = p['field_name'];
  if (name is! String ||
      name.runes.isEmpty ||
      name.runes.length > 48 ||
      !_printable(name) ||
      name.trim() != name) {
    throw _body('field_name: 1-48 characters');
  }
  final urls = p['urls'];
  if (urls is! List || urls.isEmpty || urls.length > 3) {
    throw _body('urls: 1 to 3 addresses');
  }
  final list = <String>[];
  for (final u in urls) {
    if (u is! String || !httpsBaseUrlOk(u)) {
      throw _body('urls: $u is not https://host[:port]');
    }
    list.add(u);
  }
  if (list.toSet().length != list.length) throw _body('urls: each once');
  final ca = p['ca_sha256'];
  if (ca is! Uint8List || ca.length != 32) {
    throw _body('ca_sha256: 32 bytes');
  }
  final ssid = p['wifi_ssid'];
  if (ssid != null) {
    if (ssid is! String) throw _body('wifi_ssid is text');
    final n = utf8.encode(ssid).length;
    if (n < 1 || n > 32 || ssid.contains('\u0000')) {
      throw _body('wifi_ssid: 1-32 bytes without NUL');
    }
  }
  final gid = p['game_id'];
  if (gid != null && (gid is! int || gid < 1 || gid > 0xfffe)) {
    throw _body('game_id: 1-65534');
  }
  return CheckinPoster(
    fieldId: fid,
    fieldName: name,
    urls: list,
    caSha256: ca,
    wifiSsid: ssid as String?,
    gameId: gid as int?,
  );
}

const _keys = {
  1: 'field_id',
  2: 'field_name',
  3: 'urls',
  4: 'ca_sha256',
  5: 'wifi_ssid',
  6: 'game_id',
};

bool _hasBytes(Object? v) => switch (v) {
  Uint8List() => true,
  final List<Object?> l => l.any(_hasBytes),
  final Map<Object?, Object?> m => m.values.any(_hasBytes),
  _ => false,
};

/// The poster in [data] (version byte and CBOR body). Throws [PosterException].
CheckinPoster decodePoster(List<int> data) {
  if (data.length < 2 || data.length > posterMaxLength) {
    throw PosterException(
      PosterFailure.length,
      'a poster is 2 to $posterMaxLength bytes, not ${data.length}',
    );
  }
  if (data[0] != posterVersion) {
    throw PosterException(
      PosterFailure.version,
      'unknown poster version ${data[0]}',
    );
  }
  final Object? raw;
  try {
    raw = cborDecode(data.sublist(1), allowBytes: true);
  } on CborException catch (e) {
    throw _body('poster body: ${e.message}');
  }
  if (raw is! Map) throw _body('the poster body is a map');
  final p = <String, Object?>{};
  for (final e in raw.entries) {
    final k = e.key;
    if (k is! int || k < 0 || k >= 32) {
      throw _body('poster key $k: keys are integers below 32');
    }
    final name = _keys[k];
    // 0 and 7-31: kept for optional fields a newer controller adds.
    if (name == null) continue;
    final v = e.value;
    if (v == null) throw _body('$name is null');
    if (name == 'ca_sha256') {
      if (v is! Uint8List) throw _body('ca_sha256 is a byte string');
    } else if (_hasBytes(v)) {
      throw _body('$name cannot hold byte strings');
    }
    p[name] = v;
  }
  return _validate(p);
}

/// The version byte and the body, keys in order, shortest form.
Uint8List encodePoster(CheckinPoster poster) {
  final v = _validate({
    'field_id': poster.fieldId,
    'field_name': poster.fieldName,
    'urls': poster.urls,
    'ca_sha256': poster.caSha256,
    'wifi_ssid': poster.wifiSsid,
    'game_id': poster.gameId,
  });
  final body = <int, Object?>{
    1: v.fieldId,
    2: v.fieldName,
    3: v.urls,
    4: v.caSha256,
    if (v.wifiSsid != null) 5: v.wifiSsid,
    if (v.gameId != null) 6: v.gameId,
  };
  final out = Uint8List.fromList([posterVersion, ...cborEncode(body)]);
  if (out.length > posterMaxLength) {
    throw PosterException(
      PosterFailure.length,
      'the poster is ${out.length} bytes; at most $posterMaxLength fit',
    );
  }
  return out;
}

String posterToText(List<int> data) =>
    posterTextPrefix + base64Url.encode(data).replaceAll('=', '');

/// The payload in a poster text; spaces and line ends around it are ignored.
Uint8List posterFromText(String text) {
  final t = text.trim();
  if (!t.startsWith(posterTextPrefix)) {
    throw PosterException(
      PosterFailure.text,
      'a check-in poster text starts with $posterTextPrefix',
    );
  }
  final b64 = t.substring(posterTextPrefix.length);
  if (b64.isEmpty ||
      b64.length % 4 == 1 ||
      !RegExp(r'^[A-Za-z0-9_-]*$').hasMatch(b64)) {
    throw PosterException(PosterFailure.text, 'not base64url');
  }
  final Uint8List raw;
  try {
    raw = base64Url.decode(b64.padRight((b64.length + 3) ~/ 4 * 4, '='));
  } on FormatException {
    throw PosterException(PosterFailure.text, 'not base64url');
  }
  if (posterToText(raw) != posterTextPrefix + b64) {
    throw PosterException(PosterFailure.text, 'not canonical base64url');
  }
  return raw;
}

/// A poster from its text (a QR code), checked.
CheckinPoster parsePoster(String text) => decodePoster(posterFromText(text));

/// Whether [text] looks like a check-in poster (before any check).
bool isPosterText(String text) => text.trim().startsWith(posterTextPrefix);
