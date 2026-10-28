// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Firmware releases (protocol/firmware-update.md): the signed manifest,
/// versions, an image's descriptors and a box's report, for the Android
/// field controller's firmware updates (slice S7c of PE24). The Dart twin
/// of controller/atalaia_controller/firmware_release.py; both check
/// protocol/vectors/firmware.json, as the Field Box's fw_update.c does.
///
/// A release key signs, with Ed25519 (RFC 8032), exactly the manifest:
///
///     atalaia-firmware-release-v1
///     platform=esp32s3
///     version=0.4.0
///     size=1572864
///     sha256=<64 lower-case hex digits>
///
/// and a box fetches the release text: the manifest, then
/// `signature=<base64>` on its own line.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import '../chrono/record_signer.dart' show ed25519Verify;

const manifestHeader = 'atalaia-firmware-release-v1';
const firmwarePlatforms = {0: 'esp32', 1: 'esp32s3', 2: 'linux', 3: 'android'};
final _version = RegExp(
  r'^(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:-([0-9A-Za-z][0-9A-Za-z.]{0,19}))?'
  r'(?:\+([0-9A-Za-z][0-9A-Za-z.]{0,19}))?$',
);

/// A version's whole text, at most (firmware_release.py `VERSION_MAX`).
const versionMax = 35;
final releaseIdPattern = RegExp(r'^[0-9a-f]{16}$');

const _espImageMagic = 0xe9;
const _appDescOffset = 32;
const _appDescMagic = 0xabcd5432;
const _appDescSize = 256;
const _atalaiaDescOffset = _appDescOffset + _appDescSize;
const _atalaiaDescSize = 36;

/// Bytes a box reads before it trusts the stream (and the controller checks).
const imageHead = _atalaiaDescOffset + _atalaiaDescSize; // 324
const imageProject = 'atalaia_esp32';

const reportHeader = 'atalaia-firmware-report-v1';
const reportResults = [
  'installed',
  'busy',
  'bad_offer',
  'no_key',
  'no_link',
  'no_wifi',
  'unreachable',
  'bad_release',
  'bad_signature',
  'wrong_platform',
  'not_newer',
  'too_big',
  'bad_image',
  'wrong_board',
  'download',
  'bad_hash',
  'flash',
  'battery',
  'cancelled',
  'layout',
];

class ReleaseException implements Exception {
  ReleaseException(this.code, [this.detail = '']);
  final String code;
  final String detail;
  @override
  String toString() => detail.isEmpty ? code : '$code: $detail';
}

/// The exact bytes a release key signs.
Uint8List releaseManifest(
  String platform,
  String version,
  int size,
  String sha256Hex,
) => utf8.encode(
  '$manifestHeader\nplatform=$platform\nversion=$version\n'
  'size=$size\nsha256=$sha256Hex\n',
);

/// What a box fetches: the manifest, then the signature on its own line.
Uint8List releaseText(
  String platform,
  String version,
  int size,
  String sha256Hex,
  String signature,
) => Uint8List.fromList([
  ...releaseManifest(platform, version, size, sha256Hex),
  ...ascii.encode('signature=$signature\n'),
]);

/// A key's id: the first 16 hex digits of the SHA-256 of its 32 bytes.
String releaseKeyId(String publicKeyB64) =>
    sha256.convert(base64.decode(publicKeyB64)).toString().substring(0, 16);

Uint8List? _strictB64(Object? value, int length) {
  if (value is! String) return null;
  if (!RegExp(r'^[A-Za-z0-9+/]*={0,2}$').hasMatch(value) ||
      value.length % 4 != 0) {
    return null;
  }
  try {
    final raw = base64.decode(value);
    return raw.length == length ? raw : null;
  } on FormatException {
    return null;
  }
}

/// A release public key as configured (standard base64 of 32 bytes), or null.
Uint8List? releasePublicKey(Object? value) => _strictB64(value, 32);

/// A signature in standard base64 (88 characters), or null.
Uint8List? releaseSignatureBytes(Object? value) =>
    value is String && value.length == 88 ? _strictB64(value, 64) : null;

/// A sortable key, or null for a version of another form (Semantic
/// Versioning 2.0.0 section 11's order). With [build] (a firmware's
/// version, decision FV-2) build metadata (`+g8560d54`) is allowed and
/// ignored; without it such a version is refused.
List<Object>? versionKey(Object? version, {bool build = false}) {
  if (version is! String || version.length > versionMax) return null;
  final m = _version.firstMatch(version);
  if (m == null) return null;
  final pre = m.group(4), meta = m.group(5);
  if (meta != null && (!build || meta.split('.').contains(''))) return null;
  if (pre != null && pre.split('.').contains('')) return null;
  return [
    int.parse(m.group(1)!),
    int.parse(m.group(2)!),
    int.parse(m.group(3)!),
    if (pre == null) 1 else 0,
    if (pre != null)
      for (final p in pre.split('.'))
        RegExp(r'^\d+$').hasMatch(p) ? BigInt.parse(p) : p,
  ];
}

/// [versionKey] for a firmware's version: build metadata allowed and
/// ignored (decision FV-2).
List<Object>? firmwareVersionKey(Object? version) =>
    versionKey(version, build: true);

/// -1, 0 or 1 as firmware version [a] sorts before, with or after [b]
/// (build metadata ignored).
int compareVersions(String a, String b) {
  final ka = firmwareVersionKey(a), kb = firmwareVersionKey(b);
  if (ka == null || kb == null) {
    throw ArgumentError('not a firmware version');
  }
  for (var i = 0; i < 4; i++) {
    final c = (ka[i] as int).compareTo(kb[i] as int);
    if (c != 0) return c.sign;
  }
  final n = ka.length < kb.length ? ka.length : kb.length;
  for (var i = 4; i < n; i++) {
    final x = ka[i], y = kb[i];
    final int c;
    if (x is BigInt && y is BigInt) {
      c = x.compareTo(y);
    } else if (x is BigInt) {
      c = -1; // numbers before words
    } else if (y is BigInt) {
      c = 1;
    } else {
      c = (x as String).compareTo(y as String);
    }
    if (c != 0) return c.sign;
  }
  return (ka.length - kb.length).sign;
}

/// A node's platform (HELLO's byte, or a name) as a name, or null.
String? platformName(Object? value) {
  if (value is String && firmwarePlatforms.containsValue(value)) return value;
  if (value is String && RegExp(r'^\d+$').hasMatch(value)) {
    value = int.parse(value);
  }
  return value is int ? firmwarePlatforms[value] : null;
}

/// The id of the trusted key whose signature this is, or null.
Future<String?> releaseSigner(
  Iterable<String> keys,
  String platform,
  String version,
  int size,
  String sha256Hex,
  String signature,
) async {
  final sig = releaseSignatureBytes(signature);
  if (sig == null) return null;
  final message = releaseManifest(platform, version, size, sha256Hex);
  for (final key in keys) {
    final raw = releasePublicKey(key);
    if (raw != null && await ed25519Verify(raw, message, sig)) {
      return releaseKeyId(key);
    }
  }
  return null;
}

/// What an ESP-IDF application image says about itself.
typedef ImageInfo = ({
  String version,
  String project,
  String variant,
  String board,
});

String? _cstr(List<int> raw) {
  final end = raw.indexOf(0);
  if (end < 0 || raw.skip(end).any((b) => b != 0)) return null;
  if (raw.take(end).any((b) => b > 0x7f)) return null;
  return ascii.decode(raw.sublist(0, end));
}

/// The version, project, variant and board an image's first [imageHead]
/// bytes declare; [ReleaseException] ("bad_image") otherwise.
ImageInfo imageInfo(List<int> head) {
  if (head.length < imageHead || head[0] != _espImageMagic) {
    throw ReleaseException('bad_image', 'not an ESP32 application image');
  }
  final magic = ByteData.sublistView(
    Uint8List.fromList(head.sublist(_appDescOffset, _appDescOffset + 4)),
  ).getUint32(0, Endian.little);
  if (magic != _appDescMagic) {
    throw ReleaseException('bad_image', 'no application descriptor');
  }
  final version = _cstr(head.sublist(_appDescOffset + 16, _appDescOffset + 48));
  final project = _cstr(head.sublist(_appDescOffset + 48, _appDescOffset + 80));
  final d = head.sublist(
    _atalaiaDescOffset,
    _atalaiaDescOffset + _atalaiaDescSize,
  );
  if (ascii.decode(d.sublist(0, 4), allowInvalid: true) != 'ATFW' ||
      d[4] != 1) {
    throw ReleaseException('bad_image', 'no Atalaia descriptor');
  }
  final variant = _cstr(d.sublist(8, 20));
  final board = _cstr(d.sublist(20, 36));
  if (version == null || project == null || variant == null || board == null) {
    throw ReleaseException('bad_image', 'a descriptor field is not plain text');
  }
  return (version: version, project: project, variant: variant, board: board);
}

/// The text a box posts after an update attempt.
Uint8List reportBody(
  int game,
  int node,
  String release,
  String result,
  String version,
) => ascii.encode(
  '$reportHeader\ngame=$game\nnode=$node\nrelease=$release\n'
  'result=$result\nversion=$version\n',
);

/// HMAC-SHA256 of the report with the game key, lower-case hex.
String reportMac(List<int> gameKey, List<int> body) =>
    Hmac(sha256, gameKey).convert(body).toString();

/// A report's fields; [ReleaseException] ("bad_report") otherwise.
({int game, int node, String release, String result, String version})
parseReport(List<int> body) {
  final String text;
  try {
    text = ascii.decode(body);
  } on FormatException {
    throw ReleaseException('bad_report', 'not ASCII');
  }
  final lines = text.split('\n');
  const names = ['game', 'node', 'release', 'result', 'version'];
  if (lines.length != names.length + 2 ||
      lines.first != reportHeader ||
      lines.last != '') {
    throw ReleaseException('bad_report', 'not a report');
  }
  final out = <String, String>{};
  for (var i = 0; i < names.length; i++) {
    final line = lines[i + 1];
    final eq = line.indexOf('=');
    if (eq < 0 || line.substring(0, eq) != names[i]) {
      throw ReleaseException('bad_report', 'line ${names[i]}');
    }
    out[names[i]] = line.substring(eq + 1);
  }
  int id(String name) {
    final v = out[name]!;
    if (!RegExp(r'^[1-9][0-9]{0,4}$').hasMatch(v) || int.parse(v) > 0xfffe) {
      throw ReleaseException('bad_report', name);
    }
    return int.parse(v);
  }

  final game = id('game'), node = id('node');
  if (!releaseIdPattern.hasMatch(out['release']!)) {
    throw ReleaseException('bad_report', 'release');
  }
  if (!reportResults.contains(out['result'])) {
    throw ReleaseException('bad_report', 'result');
  }
  if (firmwareVersionKey(out['version']) == null) {
    throw ReleaseException('bad_report', 'version');
  }
  final canonical = reportBody(
    game,
    node,
    out['release']!,
    out['result']!,
    out['version']!,
  );
  if (canonical.length != body.length ||
      !Iterable<int>.generate(
        body.length,
      ).every((i) => canonical[i] == body[i])) {
    throw ReleaseException('bad_report', 'not in its canonical form');
  }
  return (
    game: game,
    node: node,
    release: out['release']!,
    result: out['result']!,
    version: out['version']!,
  );
}

/// The project's release keys (docs/community/keys.md): root
/// 424d053af5cdbc35, held offline, and CI 32b3c815ac30ad43, which signs the
/// GitHub releases. The default of a phone controller's release keys, as the
/// Pi's `PROJECT_RELEASE_KEYS` in config.py and the boxes' firmware.
const projectReleaseKeys = [
  '5tzPkN0AJSn+g34CP59linCRf/fcaWFc7GAAg7qzYNc=',
  'rIO8ogMU3LRLLtnt6Rys+URdKYfmNv5mxvuRJQsX9Tw=',
];
