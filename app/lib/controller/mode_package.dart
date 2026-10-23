// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Signed mode packages on the Android field controller: the Dart port of
/// the Pi controller's controller/atalaia_controller/mode_package.py, with
/// the helpers it takes from firmware_release.py (key ids, strict base64,
/// versions, the report's MAC). The format is protocol/mode-packages.md;
/// both check the shared vectors protocol/vectors/mode_package.json.
///
/// **The archive** is a POSIX ustar tar of the package's files under one
/// root folder named after the mode's id, in one canonical form: regular
/// files only, sorted by name, mode 0644, owner 0, time 0, names of at most
/// 100 bytes, two zero blocks at the end and nothing after them. A reader
/// takes only this form ([unpackArchive]); any other archive is refused
/// (`bad_archive`).
///
/// **The manifest** a mode key signs ([ModeRelease.manifest]) is seven
/// lines, each ending with a line feed: the header, then id, version, kind,
/// min_tier, size and sha256. The release text a box fetches is the
/// manifest followed by `signature=<base64>` and a line feed.
///
/// Verifying ([verifyModePackage]) fails closed: every check must pass, in
/// the Python order, or a [ModePackageError] says which failed ([code]): the
/// size limit, the archive's size and SHA-256, a signature by one of the
/// trusted keys (`no_key` or `bad_signature`), the key not revoked, the
/// archive's form, and its own mode.yaml agreeing with the manifest and
/// naming an approved licence.
///
/// Ed25519 is RFC 8032's pure variant from the `cryptography` package's
/// pure-Dart implementation (as lib/chrono/record_signer.dart), which is
/// asynchronous: so [verifyModePackage], [releaseSigner], [boxCheckRelease]
/// and [verifyEd25519] return futures. Everything else is synchronous.
///
/// Where Python's own rules are loose, this port follows them on purpose,
/// so that both accept exactly the same data: `\d` in a version is any
/// Unicode decimal digit (Python's `re` on text), whitespace is Python's
/// `str.isspace`, lengths are counted in code points, and an index's
/// `schema_version` compares as Python's `==` (so `true` and `1.0` equal 1).
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';
import 'package:cryptography/dart.dart';
import 'package:yaml/yaml.dart';

// ---- constants (mode_package.py's, then firmware_release.py's) --------------

/// The first line of a manifest (MANIFEST_HEADER).
const modeManifestHeader = 'atalaia-mode-package-v1';

/// Every kind of package (KINDS).
const modeKinds = ['mode', 'modifier', 'role', 'scenario'];

/// The kinds a box may take (BOX_KINDS, decision P5B-10).
const boxModeKinds = ['mode', 'modifier', 'role'];

/// A package's minimum box tier (TIERS).
const modeTiers = ['reduced', 'full'];

/// The approved licences of community modes (LICENCES, ADR-P5-5).
const modeLicences = [
  'GPL-3.0-or-later',
  'LGPL-3.0-or-later',
  'MIT',
  'Apache-2.0',
  'BSD-2-Clause',
  'BSD-3-Clause',
  'CC0-1.0',
];

/// The controller's limit for a package (MAX_PACKAGE_BYTES, decision P5-6).
const modePackageMaxBytes = 1000000;

/// The most files a package has (MAX_FILES).
const modePackageMaxFiles = 64;

/// A mode's id, like org.club.name (MODE_ID).
final modeIdPattern = RegExp(r'^[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+$');

/// The longest id, in bytes (MODE_ID_MAX): a game's whole id is at most 63.
const modeIdMax = 63;

/// The files a package may have (FILE_NAME).
final modeFileNamePattern = RegExp(
  r'^(mode\.yaml|node\.lua|field\.lua|assets/[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*)$',
);

/// A key id: 16 lower-case hex digits (KEY_ID).
final modeKeyIdPattern = RegExp(r'^[0-9a-f]{16}$');

/// 64 lower-case hex digits (firmware_release.SHA256).
final sha256HexPattern = RegExp(r'^[0-9a-f]{64}$');

/// MAJOR.MINOR.PATCH with an optional pre-release (firmware_release.VERSION).
/// `\d` is any Unicode decimal digit, as in Python.
final versionPattern = RegExp(
  r'^(\p{Nd}{1,4})\.(\p{Nd}{1,4})\.(\p{Nd}{1,4})(?:-([0-9A-Za-z][0-9A-Za-z.]{0,19}))?$',
  unicode: true,
);

/// The index's schema version (INDEX_SCHEMA_VERSION).
const modeIndexSchemaVersion = 1;

/// The keys of one version in an index (ENTRY_KEYS).
const modeIndexEntryKeys = {
  'version',
  'kind',
  'min_tier',
  'size',
  'sha256',
  'signature',
  'key_id',
  'license',
  'url',
  'verified',
};

/// The keys a mode in an index may have (INDEX_MODE_KEYS).
const modeIndexModeKeys = {'id', 'name', 'description', 'author', 'versions'};

/// A box takes an archive of at most 256 KiB (BOX_MAX_PACKAGE_BYTES, P5B-12).
const boxMaxPackageBytes = 262144;

/// The fetched packages a box keeps at most (BOX_MAX_FETCHED).
const boxMaxFetched = 8;

/// Their archives' sizes together at most, 512 KiB (BOX_MAX_FETCHED_BYTES).
const boxMaxFetchedBytes = 524288;

/// The screens a box keeps (SCREEN_FILE).
final boxScreenFilePattern = RegExp(r'^assets/screens/[A-Za-z0-9_.-]+\.yaml$');

/// The first line of a box's report (REPORT_HEADER).
const modeReportHeader = 'atalaia-mode-report-v1';

/// The longest report, in bytes (REPORT_MAX).
const modeReportMax = 1024;

/// What a box reports for each part it fetched (BOX_RESULTS), in the order
/// a box meets them.
const boxResults = [
  'installed',
  'no_wifi',
  'unreachable',
  'not_offered',
  'download',
  'no_key',
  'bad_release',
  'bad_signature',
  'kind',
  'tier',
  'builtin',
  'too_big',
  'bad_hash',
  'bad_archive',
  'load',
  'no_space',
  'storage',
  'cancelled',
];

const _block = 512;
const _nameMax = 100;
const _keyLen = 32;
const _signatureLen = 64;

final _ed25519 = DartEd25519();

/// Something a package, a release, an index or a report must not be:
/// [code] says what (PackageError).
class ModePackageError implements Exception {
  ModePackageError(this.code, [this.detail = '']);

  final String code;
  final String detail;

  @override
  String toString() => detail.isEmpty
      ? 'ModePackageError($code)'
      : 'ModePackageError($code: $detail)';
}

// ---- Python's text rules --------------------------------------------------------

/// Python's `str.isspace` characters (`str.strip()`, `\s`).
bool _isPySpace(int c) =>
    (c >= 0x09 && c <= 0x0d) ||
    (c >= 0x1c && c <= 0x20) ||
    c == 0x85 ||
    c == 0xa0 ||
    c == 0x1680 ||
    (c >= 0x2000 && c <= 0x200a) ||
    c == 0x2028 ||
    c == 0x2029 ||
    c == 0x202f ||
    c == 0x205f ||
    c == 0x3000;

/// Python's `len()`: code points.
int _pyLen(String s) => s.runes.length;

/// Orders as Python's `sorted()` orders text: by code point.
int _compareCodePoints(String a, String b) {
  final x = a.runes.toList(), y = b.runes.toList();
  for (var i = 0; i < x.length && i < y.length; i++) {
    if (x[i] != y[i]) return x[i] - y[i];
  }
  return x.length - y.length;
}

/// Python's `value == 1` for a JSON value (True and 1.0 are equal to 1).
bool _isPyOne(Object? value) => value == true || (value is num && value == 1);

/// Python's truth of a YAML value.
bool _pyFalsy(Object? value) =>
    value == null ||
    value == false ||
    (value is num && value == 0) ||
    (value is String && value.isEmpty) ||
    (value is Map && value.isEmpty) ||
    (value is List && value.isEmpty);

/// Python's `str()` of a YAML value, as far as it matters here (a version
/// that is not text never passes [versionKey] in either language).
String _pyStr(Object? value) {
  if (value == null) return 'None';
  if (value is String) return value;
  if (value is bool) return value ? 'True' : 'False';
  if (value is int) return value.toString();
  if (value is double) {
    if (value.isNaN) return 'nan';
    if (value.isInfinite) return value > 0 ? 'inf' : '-inf';
    if (value == value.truncateToDouble() && value.abs() < 1e16) {
      return '${value.toInt()}.0';
    }
    return value.toString();
  }
  return value.toString();
}

/// ASCII text of [bytes], or null (Python's `bytes.decode("ascii")`).
String? _asciiOrNull(List<int> bytes) {
  for (final b in bytes) {
    if (b > 0x7f) return null;
  }
  return String.fromCharCodes(bytes);
}

bool _bytesEqual(List<int> a, List<int> b) {
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}

bool _isModeId(Object? value) =>
    value is String &&
    modeIdPattern.hasMatch(value) &&
    value.length <= modeIdMax;

// ---- base64 as Python's b64decode ---------------------------------------------

final _base64Validate = RegExp(r'^[A-Za-z0-9+/]*={0,2}$');
const _b64Alphabet =
    'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

/// Python's `base64.b64decode(text, validate=validate)`: null where Python
/// raises. With [validate], only the alphabet then at most two `=`; without
/// it, other characters are skipped. Then binascii's (non-strict) rules:
/// decoding ends at enough padding, and a last group of 2 or 3 characters
/// needs its padding.
Uint8List? _pyB64Decode(String text, {required bool validate}) {
  if (validate && !_base64Validate.hasMatch(text)) return null;
  final out = BytesBuilder(copy: false);
  var quadPos = 0, leftChar = 0, pads = 0;
  for (final unit in text.codeUnits) {
    if (unit == 0x3d) {
      if (quadPos >= 2 && quadPos + ++pads >= 4) {
        return out.toBytes();
      }
      continue;
    }
    final c = unit < 128 ? _b64Alphabet.indexOf(String.fromCharCode(unit)) : -1;
    if (c < 0) continue;
    pads = 0;
    switch (quadPos) {
      case 0:
        leftChar = c;
        quadPos = 1;
      case 1:
        out.addByte(((leftChar << 2) | (c >> 4)) & 0xff);
        leftChar = c & 0x0f;
        quadPos = 2;
      case 2:
        out.addByte(((leftChar << 4) | (c >> 2)) & 0xff);
        leftChar = c & 0x03;
        quadPos = 3;
      default:
        out.addByte(((leftChar << 6) | c) & 0xff);
        quadPos = 0;
    }
  }
  return quadPos == 0 ? out.toBytes() : null;
}

// ---- keys, signatures and versions (firmware_release.py) ----------------------

/// A key's id: the first 16 hex digits of the SHA-256 of its 32 bytes
/// (firmware_release.key_id). As Python's plain `b64decode`, characters
/// outside the alphabet are skipped; a [FormatException] where Python
/// raises.
String keyId(String publicKeyBase64) {
  final raw = publicKeyBase64.codeUnits.every((u) => u < 128)
      ? _pyB64Decode(publicKeyBase64, validate: false)
      : null;
  if (raw == null) {
    throw FormatException('not base64', publicKeyBase64);
  }
  return crypto.sha256.convert(raw).toString().substring(0, 16);
}

/// A mode public key as configured (standard base64 of 32 bytes), or null
/// (firmware_release.public_key_bytes).
Uint8List? publicKeyBytes(Object? value) {
  if (value is! String) return null;
  final raw = _pyB64Decode(value, validate: true);
  return raw != null && raw.length == _keyLen ? raw : null;
}

/// A signature as a release carries it (88 characters of standard base64,
/// 64 bytes), or null (firmware_release.signature_bytes).
Uint8List? signatureBytes(Object? value) {
  if (value is! String || value.length != 88) return null;
  final raw = _pyB64Decode(value, validate: true);
  return raw != null && raw.length == _signatureLen ? raw : null;
}

final _nd = RegExp(r'^\p{Nd}$', unicode: true);

/// The value of a Unicode decimal digit: Unicode keeps each set of ten
/// digits together, from 0 to 9, so it is the distance from the start of
/// the run of digits it is in, modulo 10.
int _digitValue(int codePoint) {
  var start = codePoint;
  while (start > 0 && _nd.hasMatch(String.fromCharCode(start - 1))) {
    start--;
  }
  return (codePoint - start) % 10;
}

/// Python's `int()` of a string of 1 to 4 Unicode decimal digits.
int _pyDigits(String digits) {
  var value = 0;
  for (final c in digits.runes) {
    value = value * 10 + _digitValue(c);
  }
  return value;
}

/// A version's sort key (firmware_release.version_key): Semantic Versioning
/// 2.0.0 section 11's order. Compare two with [compareTo].
class VersionKey implements Comparable<VersionKey> {
  VersionKey._(this.major, this.minor, this.patch, this.preRelease);

  final int major;
  final int minor;
  final int patch;

  /// The pre-release identifiers: a [BigInt] for a number, else a string;
  /// empty for a release.
  final List<Object> preRelease;

  @override
  int compareTo(VersionKey other) {
    for (final d in [
      major - other.major,
      minor - other.minor,
      patch - other.patch,
      // A pre-release sorts before its release.
      (preRelease.isEmpty ? 1 : 0) - (other.preRelease.isEmpty ? 1 : 0),
    ]) {
      if (d != 0) return d.sign;
    }
    final a = preRelease, b = other.preRelease;
    for (var i = 0; i < a.length && i < b.length; i++) {
      final x = a[i], y = b[i];
      final int d;
      if (x is BigInt && y is BigInt) {
        d = x.compareTo(y);
      } else if (x is BigInt) {
        d = -1; // numbers before words
      } else if (y is BigInt) {
        d = 1;
      } else {
        d = _compareCodePoints(x as String, y as String);
      }
      if (d != 0) return d.sign;
    }
    return (a.length - b.length).sign;
  }
}

final _asciiDigits = RegExp(r'^[0-9]+$');

/// The sort key of [version], or null for a version of another form
/// (firmware_release.version_key; an empty pre-release identifier is
/// refused).
VersionKey? versionKey(Object? version) {
  if (version is! String) return null;
  final m = versionPattern.firstMatch(version);
  if (m == null) return null;
  final pre = m.group(4);
  if (pre != null && pre.split('.').contains('')) return null;
  final ids = pre == null || pre.isEmpty
      ? const <Object>[]
      : [
          for (final p in pre.split('.'))
            _asciiDigits.hasMatch(p) ? BigInt.parse(p) : p,
        ];
  return VersionKey._(
    _pyDigits(m.group(1)!),
    _pyDigits(m.group(2)!),
    _pyDigits(m.group(3)!),
    ids,
  );
}

/// -1, 0 or 1 as [a] sorts before, with or after [b]
/// (firmware_release.compare_versions); [FormatException] for a version of
/// another form.
int compareVersions(String a, String b) {
  final ka = versionKey(a), kb = versionKey(b);
  if (ka == null || kb == null) {
    throw const FormatException('not a version');
  }
  return ka.compareTo(kb);
}

/// Raw Ed25519 (RFC 8032): whether [signature] is [publicKey]'s signature
/// of [message] (firmware_release.verify_signature).
Future<bool> verifyEd25519(
  List<int> publicKey,
  List<int> message,
  List<int> signature,
) async {
  if (publicKey.length != _keyLen || signature.length != _signatureLen) {
    return false;
  }
  try {
    return await _ed25519.verify(
      message,
      signature: Signature(
        signature,
        publicKey: SimplePublicKey(publicKey, type: KeyPairType.ed25519),
      ),
    );
  } on Object {
    return false;
  }
}

/// HMAC-SHA256 of a report with the game key, lower-case hex (the
/// X-Atalaia-Mac header; firmware_release.report_mac).
String reportMac(List<int> gameKey, List<int> body) =>
    crypto.Hmac(crypto.sha256, gameKey).convert(body).toString();

// ---- the archive ------------------------------------------------------------------

/// SHA-256 of [bytes], 64 lower-case hex digits.
String sha256Hex(List<int> bytes) => crypto.sha256.convert(bytes).toString();

/// A ustar number field: width - 1 octal digits, then NUL.
List<int> _octal(int value, int width) => [
  ...ascii.encode(value.toRadixString(8).padLeft(width - 1, '0')),
  0,
];

void _put(Uint8List h, int at, List<int> bytes) =>
    h.setRange(at, at + bytes.length, bytes);

Uint8List _header(List<int> name, int size) {
  final h = Uint8List(_block);
  _put(h, 0, name);
  _put(h, 100, _octal(0x1a4, 8)); // 0644
  _put(h, 108, _octal(0, 8));
  _put(h, 116, _octal(0, 8));
  _put(h, 124, _octal(size, 12));
  _put(h, 136, _octal(0, 12));
  _put(h, 148, List.filled(8, 0x20));
  h[156] = 0x30; // '0': a regular file
  _put(h, 257, ascii.encode('ustar\x00'));
  _put(h, 263, ascii.encode('00'));
  _put(h, 329, _octal(0, 8));
  _put(h, 337, _octal(0, 8));
  final sum = h.fold<int>(0, (a, b) => a + b);
  _put(h, 148, [
    ...ascii.encode(sum.toRadixString(8).padLeft(6, '0')),
    0,
    0x20,
  ]);
  return h;
}

/// Refuses (`bad_archive`) a file name a package must not have: only
/// mode.yaml, node.lua, field.lua and assets/..., no empty segment and none
/// starting with a dot (check_file_name).
void checkModeFileName(String name) {
  if (!modeFileNamePattern.hasMatch(name) ||
      name.split('/').any((part) => part.isEmpty || part.startsWith('.'))) {
    throw ModePackageError(
      'bad_archive',
      'file ${jsonEncode(name)} is not allowed in a mode package',
    );
  }
}

/// The canonical archive of a package's [files] (name -> text) under the
/// root folder [modeId] (pack).
Uint8List packArchive(String modeId, Map<String, String> files) {
  if (!_isModeId(modeId)) {
    throw ModePackageError(
      'bad_archive',
      'the id must look like org.club.name, at most 63 bytes',
    );
  }
  if (files.isEmpty || files.length > modePackageMaxFiles) {
    throw ModePackageError(
      'bad_archive',
      'a package has 1 to $modePackageMaxFiles files',
    );
  }
  final out = BytesBuilder(copy: false);
  for (final name in files.keys.toList()..sort(_compareCodePoints)) {
    checkModeFileName(name);
    final text = files[name]!;
    if (text.contains('\x00')) {
      throw ModePackageError('bad_archive', '$name: files are text');
    }
    final data = utf8.encode(text);
    final path = ascii.encode('$modeId/$name');
    if (path.length > _nameMax) {
      throw ModePackageError(
        'bad_archive',
        '$name: the path is longer than $_nameMax bytes',
      );
    }
    out
      ..add(_header(path, data.length))
      ..add(data)
      ..add(Uint8List((_block - data.length % _block) % _block));
  }
  out.add(Uint8List(2 * _block));
  if (out.length > modePackageMaxBytes) {
    throw ModePackageError(
      'too_big',
      'the archive is ${out.length} bytes; at most $modePackageMaxBytes',
    );
  }
  return out.toBytes();
}

final _octalDigits = RegExp(r'^[0-7]+$');

int _fieldOctal(List<int> raw, String what) {
  var end = raw.length;
  while (end > 0 && raw[end - 1] == 0) {
    end--;
  }
  final digits = _asciiOrNull(raw.sublist(0, end));
  if (digits == null || !_octalDigits.hasMatch(digits)) {
    throw ModePackageError('bad_archive', '$what is not an octal number');
  }
  return int.parse(digits, radix: 8);
}

int _sum(List<int> bytes, int start, int end) {
  var s = 0;
  for (var i = start; i < end; i++) {
    s += bytes[i];
  }
  return s;
}

/// The root (the package's id) and files of a canonical archive; a
/// [ModePackageError] otherwise (unpack). [modeId], when given, is the root
/// the archive must have (`mismatch`). Nothing is written anywhere: the
/// files come back as text.
(String, Map<String, String>) unpackArchive(
  List<int> archive, {
  String? modeId,
  int limit = modePackageMaxBytes,
}) {
  if (archive.length > limit) {
    throw ModePackageError(
      'too_big',
      'the archive is ${archive.length} bytes; at most $limit',
    );
  }
  if (archive.length % _block != 0 || archive.length < 2 * _block) {
    throw ModePackageError(
      'bad_archive',
      'not a whole number of 512-byte blocks',
    );
  }
  final files = <String, String>{};
  String? root;
  var pos = 0;
  while (true) {
    if (pos + _block > archive.length) {
      throw ModePackageError('bad_archive', 'no end of archive');
    }
    final head = archive.sublist(pos, pos + _block);
    if (head.every((b) => b == 0)) break;
    if (!_bytesEqual(head.sublist(257, 265), ascii.encode('ustar\x0000'))) {
      throw ModePackageError('bad_archive', 'not a POSIX ustar archive');
    }
    final expected = _fieldOctal(head.sublist(148, 155), 'the checksum');
    if (expected != _sum(head, 0, 148) + 8 * 32 + _sum(head, 156, _block)) {
      throw ModePackageError('bad_archive', "a header's checksum is wrong");
    }
    if (head[156] != 0x30) {
      throw ModePackageError(
        'bad_archive',
        'only regular files (no folders, links or devices)',
      );
    }
    var nameEnd = _nameMax;
    while (nameEnd > 0 && head[nameEnd - 1] == 0) {
      nameEnd--;
    }
    final rawName = head.sublist(0, nameEnd);
    if (rawName.contains(0) || head.sublist(345, 500).any((b) => b != 0)) {
      throw ModePackageError(
        'bad_archive',
        'a name with a prefix or a NUL inside',
      );
    }
    final path = _asciiOrNull(rawName);
    if (path == null) {
      throw ModePackageError('bad_archive', 'a name that is not ASCII');
    }
    final slash = path.indexOf('/');
    final top = slash < 0 ? path : path.substring(0, slash);
    final name = slash < 0 ? '' : path.substring(slash + 1);
    if (slash < 0 || (root != null && top != root)) {
      throw ModePackageError(
        'bad_archive',
        "${jsonEncode(path)} is not under the package's one root folder",
      );
    }
    if (root == null) {
      if (!_isModeId(top)) {
        throw ModePackageError(
          'bad_archive',
          'the root folder ${jsonEncode(top)} is not a mode id',
        );
      }
      if (modeId != null && top != modeId) {
        throw ModePackageError('mismatch', 'the archive is $top, not $modeId');
      }
      root = top;
    }
    checkModeFileName(name);
    if (files.containsKey(name)) {
      throw ModePackageError('bad_archive', '$name is in the archive twice');
    }
    if (files.length >= modePackageMaxFiles) {
      throw ModePackageError(
        'bad_archive',
        'more than $modePackageMaxFiles files',
      );
    }
    final size = _fieldOctal(head.sublist(124, 136), 'a size');
    final start = pos + _block;
    final end = start + size;
    if (end > archive.length) {
      throw ModePackageError('bad_archive', '$name runs past the end');
    }
    final String text;
    try {
      text = utf8.decode(archive.sublist(start, end));
    } on FormatException {
      throw ModePackageError('bad_archive', '$name is not UTF-8 text');
    }
    if (text.contains('\x00')) {
      throw ModePackageError('bad_archive', '$name is not text');
    }
    files[name] = text;
    pos = start + size + (_block - size % _block) % _block;
  }
  if (root == null) {
    throw ModePackageError('bad_archive', 'an empty archive');
  }
  // Only the canonical form: the same files packed again must give exactly
  // these bytes (sorted, the fixed header fields, zero padding, two zero
  // blocks and nothing after).
  if (!_bytesEqual(packArchive(root, files), archive)) {
    throw ModePackageError(
      'bad_archive',
      'not in the canonical form (tools/mode_package.py pack makes it)',
    );
  }
  return (root, files);
}

// ---- the manifest and its signature -----------------------------------------------

/// The exact bytes a mode key signs (manifest).
Uint8List modeManifest(
  String modeId,
  String version,
  String kind,
  String minTier,
  int size,
  String digest,
) => utf8.encode(
  '$modeManifestHeader\nid=$modeId\nversion=$version\nkind=$kind\n'
  'min_tier=$minTier\nsize=$size\nsha256=$digest\n',
);

/// A package's signed manifest and its signature (Release).
class ModeRelease {
  const ModeRelease(
    this.id,
    this.version,
    this.kind,
    this.minTier,
    this.size,
    this.sha256,
    this.signature,
  );

  final String id;
  final String version;
  final String kind;
  final String minTier;
  final int size;
  final String sha256;

  /// Standard base64 of the 64-byte Ed25519 signature.
  final String signature;

  /// The exact bytes the mode key signed.
  Uint8List manifest() =>
      modeManifest(id, version, kind, minTier, size, sha256);

  /// The release text a box fetches: the manifest, then the signature.
  Uint8List text() => Uint8List.fromList([
    ...manifest(),
    ...ascii.encode('signature=$signature\n'),
  ]);

  @override
  bool operator ==(Object other) =>
      other is ModeRelease &&
      other.id == id &&
      other.version == version &&
      other.kind == kind &&
      other.minTier == minTier &&
      other.size == size &&
      other.sha256 == sha256 &&
      other.signature == signature;

  @override
  int get hashCode =>
      Object.hash(id, version, kind, minTier, size, sha256, signature);

  @override
  String toString() => 'ModeRelease($id $version $kind $minTier $size)';
}

/// A release from its JSON form (`.release.json`, an index entry), its
/// fields checked (release_from); `bad_release` otherwise.
ModeRelease releaseFrom(Object? value) {
  if (value is! Map) {
    throw ModePackageError('bad_release', 'a release is an object');
  }
  final modeId = value['id'], version = value['version'];
  final kind = value['kind'], tier = value['min_tier'];
  final size = value['size'], digest = value['sha256'];
  final signature = value['signature'];
  if (!_isModeId(modeId)) throw ModePackageError('bad_release', 'id');
  if (version is! String || versionKey(version) == null) {
    throw ModePackageError('bad_release', 'version');
  }
  if (!modeKinds.contains(kind)) throw ModePackageError('bad_release', 'kind');
  if (!modeTiers.contains(tier)) {
    throw ModePackageError('bad_release', 'min_tier');
  }
  if (size is! int || size <= 0 || size > modePackageMaxBytes) {
    throw ModePackageError('bad_release', 'size');
  }
  if (digest is! String || !sha256HexPattern.hasMatch(digest)) {
    throw ModePackageError('bad_release', 'sha256');
  }
  if (signatureBytes(signature) == null) {
    throw ModePackageError('bad_release', 'signature');
  }
  return ModeRelease(
    modeId as String,
    version,
    kind as String,
    tier as String,
    size,
    digest,
    signature as String,
  );
}

final _releaseSize = RegExp(r'^[1-9][0-9]{0,6}$');
const _releaseLines = [
  'id',
  'version',
  'kind',
  'min_tier',
  'size',
  'sha256',
  'signature',
];

/// A release text (what a box fetches): exactly the manifest's lines and
/// the signature (parse_release_text); `bad_release` otherwise.
ModeRelease parseReleaseText(List<int> text) {
  final decoded = _asciiOrNull(text);
  if (decoded == null) throw ModePackageError('bad_release', 'not ASCII');
  final lines = decoded.split('\n');
  if (lines.length != _releaseLines.length + 2 ||
      lines.first != modeManifestHeader ||
      lines.last != '') {
    throw ModePackageError('bad_release', 'not a mode package release');
  }
  final values = <String, Object?>{};
  for (var i = 0; i < _releaseLines.length; i++) {
    final name = _releaseLines[i], line = lines[i + 1];
    final eq = line.indexOf('=');
    if (eq < 0 || line.substring(0, eq) != name) {
      throw ModePackageError('bad_release', 'line $name');
    }
    values[name] = line.substring(eq + 1);
  }
  final size = values['size']! as String;
  if (!_releaseSize.hasMatch(size)) {
    throw ModePackageError('bad_release', 'size');
  }
  values['size'] = int.parse(size);
  final release = releaseFrom(values);
  if (!_bytesEqual(release.text(), text)) {
    throw ModePackageError('bad_release', 'not in its canonical form');
  }
  return release;
}

/// The id of the trusted key (base64) that signed exactly this manifest,
/// or null (signer).
Future<String?> releaseSigner(
  Iterable<String> keys,
  ModeRelease release,
) async {
  final sig = signatureBytes(release.signature);
  if (sig == null) return null;
  final message = release.manifest();
  for (final key in keys) {
    final raw = publicKeyBytes(key);
    if (raw != null && await verifyEd25519(raw, message, sig)) {
      return keyId(key);
    }
  }
  return null;
}

/// What a package's own mode.yaml says the manifest must say
/// (manifest_fields).
class ModeManifestFields {
  const ModeManifestFields(
    this.id,
    this.version,
    this.kind,
    this.minTier,
    this.license,
  );

  final String id;
  final String version;
  final String kind;

  /// `reduced` when mode.yaml says none.
  final String minTier;
  final String license;
}

/// The id, version, kind, min_tier and licence of a package's mode.yaml
/// (manifest_fields); `bad_manifest` (or `licence`) otherwise. A version
/// that YAML reads as a number becomes its Python `str()` (1 -> "1",
/// 1.5 -> "1.5", 1.0 -> "1.0"), which is never a valid version.
ModeManifestFields manifestFields(Map<String, String> files) {
  final source = files['mode.yaml'];
  if (source == null) {
    throw ModePackageError('bad_manifest', 'the package has no mode.yaml');
  }
  Object? data;
  try {
    data = loadYaml(source);
  } on Exception catch (e) {
    throw ModePackageError('bad_manifest', 'mode.yaml: $e');
  }
  if (_pyFalsy(data)) data = const <String, Object?>{};
  if (data is! Map) {
    throw ModePackageError('bad_manifest', 'mode.yaml must be a map');
  }
  final id = data['id'];
  final version = data.containsKey('version') ? _pyStr(data['version']) : '';
  final kind = data.containsKey('kind') ? data['kind'] : 'mode';
  final tier = data.containsKey('min_tier') ? data['min_tier'] : 'reduced';
  final license = data['license'];
  if (!_isModeId(id)) {
    throw ModePackageError(
      'bad_manifest',
      'mode.yaml: id must look like org.club.name',
    );
  }
  if (versionKey(version) == null) {
    throw ModePackageError(
      'bad_manifest',
      'mode.yaml: version must be MAJOR.MINOR.PATCH',
    );
  }
  if (!modeKinds.contains(kind)) {
    throw ModePackageError('bad_manifest', 'mode.yaml: kind');
  }
  if (!modeTiers.contains(tier)) {
    throw ModePackageError(
      'bad_manifest',
      'mode.yaml: min_tier must be reduced or full',
    );
  }
  if (!modeLicences.contains(license)) {
    throw ModePackageError(
      'licence',
      'mode.yaml: license must be one of ${modeLicences.join(', ')}',
    );
  }
  return ModeManifestFields(
    id as String,
    version,
    kind as String,
    tier as String,
    license as String,
  );
}

/// A package that passed every check: its release, its files and who
/// signed it (VerifiedPackage).
class VerifiedModePackage {
  const VerifiedModePackage(this.release, this.files, this.keyId, this.license);

  final ModeRelease release;
  final Map<String, String> files;

  /// The id of the trusted key that signed it.
  final String keyId;
  final String license;
}

/// Checks a package as the controller installs it (verify); a
/// [ModePackageError] at the first failure.
///
/// [keys]: the trusted mode keys (base64); [revoked]: key ids that no
/// longer count, even when a key is still listed; [namedKey]: the key id
/// the release says signed it (only to tell `no_key` from `bad_signature`;
/// never trusted for anything else); [limit]: the largest archive taken.
Future<VerifiedModePackage> verifyModePackage(
  List<int> archive,
  ModeRelease release,
  Iterable<String> keys, {
  Iterable<String> revoked = const [],
  String? namedKey,
  int limit = modePackageMaxBytes,
}) async {
  if (release.size > limit) {
    throw ModePackageError('too_big', '${release.size} bytes; at most $limit');
  }
  if (archive.length != release.size) {
    throw ModePackageError(
      'bad_hash',
      'the archive has ${archive.length} bytes, the release says ${release.size}',
    );
  }
  if (sha256Hex(archive) != release.sha256) {
    throw ModePackageError('bad_hash', 'the archive is not the one signed');
  }
  final trusted = keys.toList();
  final who = await releaseSigner(trusted, release);
  if (who == null) {
    final known = {
      for (final k in trusted)
        if (publicKeyBytes(k) != null) keyId(k),
    };
    if (namedKey != null && !known.contains(namedKey)) {
      throw ModePackageError(
        'no_key',
        'signed with key $namedKey, which this controller does not trust',
      );
    }
    throw ModePackageError(
      'bad_signature',
      'no trusted mode key signed this manifest',
    );
  }
  if (revoked.toSet().contains(who)) {
    throw ModePackageError('revoked', 'key $who is revoked');
  }
  final (_, files) = unpackArchive(archive, modeId: release.id, limit: limit);
  final own = manifestFields(files);
  for (final (name, mine, signed) in [
    ('id', own.id, release.id),
    ('version', own.version, release.version),
    ('kind', own.kind, release.kind),
    ('min_tier', own.minTier, release.minTier),
  ]) {
    if (mine != signed) {
      throw ModePackageError(
        'mismatch',
        'mode.yaml says $name ${jsonEncode(mine)}, the signed manifest '
            '${jsonEncode(signed)}',
      );
    }
  }
  return VerifiedModePackage(release, files, who, own.license);
}

/// The `.release.json` next to an archive (release_json): the manifest's
/// fields, the signature, the key's id and the licence (the last two only
/// describe it: verifying never trusts them).
Map<String, Object> releaseJson(
  ModeRelease release,
  String keyId,
  String license,
) => {
  'format': modeManifestHeader,
  'id': release.id,
  'version': release.version,
  'kind': release.kind,
  'min_tier': release.minTier,
  'size': release.size,
  'sha256': release.sha256,
  'signature': release.signature,
  'key_id': keyId,
  'license': license,
};

// ---- the registry's index and revocation list ---------------------------------------

/// One version of one mode in an index: where to fetch it and its release
/// (IndexEntry).
class ModeIndexEntry {
  const ModeIndexEntry(
    this.release,
    this.keyId,
    this.license,
    this.url,
    this.verified,
    this.name, {
    this.description = '',
    this.author = '',
  });

  final ModeRelease release;
  final String keyId;
  final String license;

  /// `https://...` or a path relative to the index.
  final String url;
  final bool verified;
  final String name;
  final String description;
  final String author;
}

String _text(Object? value, String what, int longest, {bool required = true}) {
  if (value == null && !required) return '';
  if (value is! String ||
      (required && value.runes.every(_isPySpace)) ||
      _pyLen(value) > longest) {
    throw ModePackageError('bad_index', what);
  }
  return value;
}

final _httpsUrl = RegExp(
  '^https://[^\\\\\\t\\n\\x0b\\x0c\\r\\x1c-\\x20\\x85\\xa0\\u1680'
  '\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]+\$',
);
final _relativeUrl = RegExp(r'^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$');

/// Every version of every mode of a registry index
/// (registry/schema/index.schema.json; parse_index). The whole index is
/// refused (`bad_index`) for anything it does not allow. A package's url is
/// `https://...` or a relative path.
List<ModeIndexEntry> parseModeIndex(Object? value) {
  if (value is! Map ||
      value.keys.any((k) => !{'schema_version', 'modes', 'name'}.contains(k))) {
    throw ModePackageError(
      'bad_index',
      'an index is {schema_version, name?, modes}',
    );
  }
  if (!_isPyOne(value['schema_version'])) {
    throw ModePackageError(
      'bad_index',
      'schema_version must be $modeIndexSchemaVersion',
    );
  }
  final modes = value['modes'];
  if (modes is! List || modes.length > 1000) {
    throw ModePackageError('bad_index', 'modes must be a list (at most 1000)');
  }
  final out = <ModeIndexEntry>[];
  final seen = <String>{};
  for (final mode in modes) {
    if (mode is! Map ||
        mode.keys.any((k) => !modeIndexModeKeys.contains(k)) ||
        !mode.containsKey('versions')) {
      throw ModePackageError(
        'bad_index',
        'a mode is {id, name, description?, author?, versions}',
      );
    }
    final rawId = mode['id'];
    if (!_isModeId(rawId)) throw ModePackageError('bad_index', "a mode's id");
    final modeId = rawId as String;
    final name = _text(mode['name'], '$modeId: name', 80);
    final description = _text(
      mode['description'],
      '$modeId: description',
      2000,
      required: false,
    );
    final author = _text(
      mode['author'],
      '$modeId: author',
      120,
      required: false,
    );
    final versions = mode['versions'];
    if (versions is! List || versions.isEmpty || versions.length > 100) {
      throw ModePackageError(
        'bad_index',
        '$modeId: versions must be a list of 1 to 100',
      );
    }
    for (final entry in versions) {
      if (entry is! Map ||
          entry.length != modeIndexEntryKeys.length ||
          !entry.keys.every(modeIndexEntryKeys.contains)) {
        final keys = modeIndexEntryKeys.toList()..sort();
        throw ModePackageError(
          'bad_index',
          '$modeId: a version has exactly ${keys.join(', ')}',
        );
      }
      final ModeRelease release;
      try {
        release = releaseFrom({...entry, 'id': modeId});
      } on ModePackageError catch (e) {
        throw ModePackageError(
          'bad_index',
          '$modeId ${entry['version']}: ${e.detail}',
        );
      }
      final keyIdValue = entry['key_id'];
      if (keyIdValue is! String || !modeKeyIdPattern.hasMatch(keyIdValue)) {
        throw ModePackageError(
          'bad_index',
          '$modeId ${release.version}: key_id',
        );
      }
      final license = entry['license'];
      if (!modeLicences.contains(license)) {
        throw ModePackageError(
          'bad_index',
          '$modeId ${release.version}: license must be an approved one',
        );
      }
      final url = entry['url'];
      if (url is! String ||
          _pyLen(url) > 500 ||
          !(_httpsUrl.hasMatch(url) ||
              (_relativeUrl.hasMatch(url) && !url.split('/').contains('..')))) {
        throw ModePackageError(
          'bad_index',
          '$modeId ${release.version}: url must be https:// or a relative path',
        );
      }
      final verified = entry['verified'];
      if (verified is! bool) {
        throw ModePackageError(
          'bad_index',
          '$modeId ${release.version}: verified is true or false',
        );
      }
      if (!seen.add('$modeId\n${release.version}')) {
        throw ModePackageError(
          'bad_index',
          '$modeId ${release.version} is listed twice',
        );
      }
      out.add(
        ModeIndexEntry(
          release,
          keyIdValue,
          license as String,
          url,
          verified,
          name,
          description: description,
          author: author,
        ),
      );
    }
  }
  return out;
}

final _date = RegExp(r'^\p{Nd}{4}-\p{Nd}{2}-\p{Nd}{2}$', unicode: true);

/// A revocation list (registry/schema/revoked.schema.json; parse_revoked):
/// key id -> reason; `bad_index` otherwise.
Map<String, String> parseRevoked(Object? value) {
  if (value is! Map ||
      value.length != 2 ||
      !value.containsKey('schema_version') ||
      !value.containsKey('keys') ||
      !_isPyOne(value['schema_version'])) {
    throw ModePackageError(
      'bad_index',
      'a revocation list is {schema_version: 1, keys}',
    );
  }
  final keys = value['keys'];
  if (keys is! List || keys.length > 1000) {
    throw ModePackageError('bad_index', 'keys must be a list');
  }
  final out = <String, String>{};
  for (final item in keys) {
    if (item is! Map ||
        item.keys.any((k) => !{'key_id', 'reason', 'date'}.contains(k)) ||
        !item.containsKey('key_id')) {
      throw ModePackageError(
        'bad_index',
        'a revoked key is {key_id, reason?, date?}',
      );
    }
    final id = item['key_id'];
    if (id is! String || !modeKeyIdPattern.hasMatch(id)) {
      throw ModePackageError('bad_index', "a revoked key's key_id");
    }
    final reason = item.containsKey('reason') ? item['reason'] : '';
    if (reason is! String || _pyLen(reason) > 500) {
      throw ModePackageError('bad_index', "a revoked key's reason");
    }
    final date = item.containsKey('date') ? item['date'] : '';
    if (date is! String || (date.isNotEmpty && !_date.hasMatch(date))) {
      throw ModePackageError('bad_index', "a revoked key's date is YYYY-MM-DD");
    }
    out[id] = reason;
  }
  return out;
}

// ---- what a box checks, and its report (phase 5 plan phase 13) --------------

/// A box's checks of a release text before it downloads the archive
/// (box_check_release): (release, key id), or a [ModePackageError] at the
/// first failure, in this order: no mode key built in (`no_key`); the text
/// exactly the manifest's lines and a signature, for [wantedId]
/// (`bad_release`); a signature by one of its own mode keys
/// (`bad_signature`); not a scenario (`kind`); its tier (`tier`: a reduced
/// box refuses min_tier=full); not one of its [builtin] ids (`builtin`); the
/// size within [limit] (`too_big`). [tier] is the box's, `reduced` or
/// `full` (an [ArgumentError] otherwise).
Future<(ModeRelease, String)> boxCheckRelease(
  List<int> text,
  String wantedId,
  Iterable<String> keys,
  String tier, {
  Iterable<String> builtin = const [],
  int limit = boxMaxPackageBytes,
}) async {
  if (!modeTiers.contains(tier)) {
    throw ArgumentError.value(tier, 'tier', 'reduced or full');
  }
  final own = [
    for (final k in keys)
      if (publicKeyBytes(k) != null) k,
  ];
  if (own.isEmpty) {
    throw ModePackageError('no_key', 'no mode key is built into this box');
  }
  final ModeRelease release;
  try {
    release = parseReleaseText(text);
  } on ModePackageError catch (e) {
    throw ModePackageError('bad_release', e.detail);
  }
  if (release.id != wantedId) {
    throw ModePackageError(
      'bad_release',
      "the release is ${release.id}'s, not $wantedId's",
    );
  }
  final who = await releaseSigner(own, release);
  if (who == null) {
    throw ModePackageError(
      'bad_signature',
      "none of the box's mode keys signed this manifest",
    );
  }
  if (!boxModeKinds.contains(release.kind)) {
    throw ModePackageError('kind', 'a ${release.kind} never runs on a box');
  }
  if (tier == 'reduced' && release.minTier == 'full') {
    throw ModePackageError('tier', 'the package needs a Full box');
  }
  if (builtin.toSet().contains(release.id)) {
    throw ModePackageError(
      'builtin',
      "the box's firmware has a mode of this id: it is never replaced",
    );
  }
  if (release.size > limit) {
    throw ModePackageError(
      'too_big',
      '${release.size} bytes; a box takes at most $limit',
    );
  }
  return (release, who);
}

/// A box's checks of the archive it downloaded for a release it checked
/// (box_check_archive): the signed size and SHA-256 (`bad_hash`), the
/// canonical form with the id as its root and a node.lua (`bad_archive`).
/// The files a box keeps: node.lua and assets/screens/*.yaml.
Map<String, String> boxCheckArchive(List<int> archive, ModeRelease release) {
  if (archive.length != release.size || sha256Hex(archive) != release.sha256) {
    throw ModePackageError('bad_hash', 'the archive is not the one signed');
  }
  final Map<String, String> files;
  try {
    files = unpackArchive(
      archive,
      modeId: release.id,
      limit: release.size > _block ? release.size : _block,
    ).$2;
  } on ModePackageError catch (e) {
    throw ModePackageError('bad_archive', e.detail);
  }
  if (!files.containsKey('node.lua')) {
    throw ModePackageError('bad_archive', 'the package has no node.lua');
  }
  return {
    for (final e in files.entries)
      if (e.key == 'node.lua' || boxScreenFilePattern.hasMatch(e.key))
        e.key: e.value,
  };
}

/// The text a box posts for each part it fetched (report_body; it signs it
/// with the game key, [reportMac]): the part, the version it read (`-` when
/// [version] is null or empty), the result, and every package it keeps now
/// (`id@version` sorted by id, `-` for none).
Uint8List modeReportBody(
  int game,
  int node,
  String modeId,
  String? version,
  String result,
  Map<String, String> kept,
) {
  final ids = kept.keys.toList()..sort(_compareCodePoints);
  final keptText = ids.isEmpty
      ? '-'
      : ids.map((k) => '$k@${kept[k]}').join(',');
  final v = version == null || version.isEmpty ? '-' : version;
  return ascii.encode(
    '$modeReportHeader\ngame=$game\nnode=$node\nmode=$modeId\nversion=$v\n'
    'result=$result\nkept=$keptText\n',
  );
}

final _reportNumber = RegExp(r'^[1-9][0-9]{0,4}$');
const _reportLines = ['game', 'node', 'mode', 'version', 'result', 'kept'];

/// A box's report (parse_report): exactly the lines of [modeReportBody];
/// `bad_report` otherwise. The map has `game` and `node` (int), `mode`,
/// `version` (null for `-`), `result` and `kept` (id -> version).
Map<String, Object?> parseModeReport(List<int> body) {
  if (body.length > modeReportMax) {
    throw ModePackageError('bad_report', 'too long');
  }
  final text = _asciiOrNull(body);
  if (text == null) throw ModePackageError('bad_report', 'not ASCII');
  final lines = text.split('\n');
  if (lines.length != _reportLines.length + 2 ||
      lines.first != modeReportHeader ||
      lines.last != '') {
    throw ModePackageError('bad_report', 'not a report');
  }
  final raw = <String, String>{};
  for (var i = 0; i < _reportLines.length; i++) {
    final name = _reportLines[i], line = lines[i + 1];
    final eq = line.indexOf('=');
    if (eq < 0 || line.substring(0, eq) != name) {
      throw ModePackageError('bad_report', 'line $name');
    }
    raw[name] = line.substring(eq + 1);
  }
  final numbers = <String, int>{};
  for (final name in ['game', 'node']) {
    final v = raw[name]!;
    if (!_reportNumber.hasMatch(v) || int.parse(v) > 0xFFFE) {
      throw ModePackageError('bad_report', name);
    }
    numbers[name] = int.parse(v);
  }
  final mode = raw['mode']!;
  if (!_isModeId(mode)) throw ModePackageError('bad_report', 'mode');
  String? version = raw['version'];
  if (version == '-') {
    version = null;
  } else if (versionKey(version) == null) {
    throw ModePackageError('bad_report', 'version');
  }
  final result = raw['result']!;
  if (!boxResults.contains(result)) {
    throw ModePackageError('bad_report', 'result');
  }
  final kept = <String, String>{};
  if (raw['kept'] != '-') {
    for (final item in raw['kept']!.split(',')) {
      final at = item.indexOf('@');
      final id = at < 0 ? item : item.substring(0, at);
      final v = at < 0 ? '' : item.substring(at + 1);
      if (at < 0 ||
          !_isModeId(id) ||
          versionKey(v) == null ||
          kept.containsKey(id)) {
        throw ModePackageError('bad_report', 'kept');
      }
      kept[id] = v;
    }
    if (kept.length > boxMaxFetched) {
      throw ModePackageError('bad_report', 'kept');
    }
  }
  final out = <String, Object?>{
    'game': numbers['game'],
    'node': numbers['node'],
    'mode': mode,
    'version': version,
    'result': result,
    'kept': kept,
  };
  final again = modeReportBody(
    numbers['game']!,
    numbers['node']!,
    mode,
    version,
    result,
    kept,
  );
  if (!_bytesEqual(again, body)) {
    throw ModePackageError('bad_report', 'not in its canonical form');
  }
  return out;
}
