// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Firmware updates for the Field Boxes (protocol/firmware-update.md,
/// decisions FU3-*, OT-8, OT-9) on the Android field controller (slice S7c
/// of PE24, decision PE24-96): the Pi controller's
/// controller/atalaia_controller/firmware_updates.py in Dart.
///
/// The GM uploads a signed release (the image and the fields of its
/// `.release.json`); the phone keeps it only if one of its release keys
/// signed exactly that platform, version, size and SHA-256 and the image's
/// own descriptors agree (an Atalaia Field Box image of that version and a
/// variant it takes). At most [maxReleases] are kept, in the controller's
/// folder of the app's private storage.
///
/// Then the GM updates one box or all, only while the live game has not
/// started (`ready`) and only when the phone serves HTTPS on the field's
/// Wi-Fi (its joins carry the field CA and its addresses, keys 13 and 14):
/// CMD update (opcode 9) over the radio with the release's id and version.
/// The box fetches the release text and the image from the phone over
/// HTTPS pinned to the field CA (S6's), checks everything again with the
/// keys in its own firmware, installs it and reports (an HMAC with the game
/// key); its next HELLO shows what it runs. A failure the box could not
/// report over HTTPS comes over LoRa (node.update_failed). The live game
/// cannot start while an update is on its way (a start guard), unless the
/// GM stops waiting. The updates live in memory.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import '../protocol/firmware_release.dart';
import '../security/bytes.dart';
import 'controller_engine.dart';

const maxReleases = 4;

/// Bytes of a Field Box's OTA slot (firmware/esp32/partitions.csv).
const slotSize = 0x200000;
const boxPlatforms = ['esp32', 'esp32s3'];
const boxTiers = [0, 1];
const reportMax = 512;
const _active = ['sent', 'installed'];
final _reason = RegExp(r'^[a-z][a-z_]{0,23}$');

class ControllerFirmware {
  ControllerFirmware(
    this.engine,
    String directory, {
    List<String> keys = const [],
    this.timeoutS = 600,
    this.variants = const ['box'],
  }) : dir = Directory(directory),
       keys = List.unmodifiable(keys) {
    dir.createSync(recursive: true);
    engine
      ..firmware = this
      ..startGuards.add(busy)
      ..addListener(onMessage);
  }

  final ControllerEngine engine;
  final Directory dir;

  /// The release keys' public halves (standard base64 of 32 bytes).
  final List<String> keys;
  final double timeoutS;
  final List<String> variants;

  /// Node id -> the latest update sent to it.
  final attempts = <int, Map<String, Object?>>{};

  /// The signer of each kept release, by its SHA-256 (checked once).
  final _signers = <String, String?>{};

  double _now() => engine.wallSeconds();

  // --- releases ----------------------------------------------------------------

  List<Map<String, Object?>> _entries() {
    final out = <Map<String, Object?>>[];
    final metas =
        dir
            .listSync()
            .whereType<File>()
            .where((f) => f.path.endsWith('.json'))
            .toList()
          ..sort((a, b) => a.path.compareTo(b.path));
    for (final meta in metas) {
      try {
        final e = jsonDecode(meta.readAsStringSync());
        if (e is Map<String, Object?> &&
            File('${dir.path}/${e['sha256']}.bin').existsSync()) {
          out.add(e);
        }
      } on Object {
        continue;
      }
    }
    out.sort((a, b) {
      final p = '${b['platform']}'.compareTo('${a['platform']}');
      if (p != 0) return p;
      return compareVersions('${b['version']}', '${a['version']}');
    });
    return out;
  }

  Future<String?> _signer(Map<String, Object?> e) async {
    final sha = e['sha256']! as String;
    if (_signers.containsKey(sha)) return _signers[sha];
    final s = await releaseSigner(
      keys,
      e['platform']! as String,
      e['version']! as String,
      e['size']! as int,
      sha,
      e['signature']! as String,
    );
    _signers[sha] = s;
    return s;
  }

  Future<Map<String, Object?>> _public(Map<String, Object?> e) async {
    final key = await _signer(e);
    final sha = e['sha256']! as String;
    return {
      'id': sha.substring(0, 16),
      'platform': e['platform'],
      'version': e['version'],
      'size': e['size'],
      'sha256': sha,
      'signature': e['signature'],
      'variant': e['variant'],
      'board': e['board'],
      'uploaded_at': e['uploaded_at'],
      'key_id': key,
      'verified': key != null,
    };
  }

  Future<List<Map<String, Object?>>> releases() async => [
    for (final e in _entries()) await _public(e),
  ];

  Map<String, Object?> _find(String releaseId) {
    if (!releaseIdPattern.hasMatch(releaseId)) {
      throw ControllerError.notFound('no such firmware release');
    }
    for (final e in _entries()) {
      if ((e['sha256']! as String).startsWith(releaseId)) return e;
    }
    throw ControllerError.notFound('no such firmware release');
  }

  /// Keeps a release the GM uploaded, after every check.
  Future<Map<String, Object?>> add(
    Uint8List image,
    String platform,
    String version,
    String signature,
  ) async {
    if (keys.isEmpty) {
      throw ControllerError.conflict(
        'no release key is set on this phone: no release is accepted',
      );
    }
    if (!boxPlatforms.contains(platform)) {
      throw ControllerError(
        "platform: one of ${boxPlatforms.join(', ')} (a Field Box's)",
      );
    }
    if (firmwareVersionKey(version) == null || version.length > 31) {
      throw ControllerError(
        'version: MAJOR.MINOR.PATCH with an optional -pre-release, at most '
        '31 characters',
      );
    }
    if (releaseSignatureBytes(signature) == null) {
      throw ControllerError(
        'signature: 64 bytes in standard base64 (88 characters)',
      );
    }
    if (image.isEmpty || image.length > slotSize) {
      throw ControllerError(
        "the image must be 1 to $slotSize bytes (a Field Box's OTA slot)",
      );
    }
    final sha = sha256.convert(image).toString();
    final signer = await releaseSigner(
      keys,
      platform,
      version,
      image.length,
      sha,
      signature,
    );
    if (signer == null) {
      throw ControllerError(
        'the signature does not verify with a release key of this '
        'controller (another image, version or platform than the one '
        'signed, or another key)',
      );
    }
    final ImageInfo info;
    try {
      info = imageInfo(
        image.sublist(0, image.length < imageHead ? image.length : imageHead),
      );
    } on ReleaseException catch (e) {
      throw ControllerError('not a Field Box image: ${e.detail}');
    }
    if (info.project != imageProject || info.version != version) {
      throw ControllerError(
        'the image says ${info.project} ${info.version}, the release $version',
      );
    }
    if (!variants.contains(info.variant)) {
      throw ControllerError(
        "the image is a '${info.variant}' build; this controller takes "
        "${variants.map((v) => "'$v'").join(', ')} images",
      );
    }
    final entries = _entries();
    if (entries.any((e) => e['sha256'] == sha)) {
      throw ControllerError.conflict('this release is already here');
    }
    if (entries.length >= maxReleases) {
      throw ControllerError.conflict(
        'at most $maxReleases releases are kept: delete one first',
      );
    }
    final entry = <String, Object?>{
      'board': info.board,
      'platform': platform,
      'sha256': sha,
      'signature': signature,
      'size': image.length,
      'uploaded_at': (_now() * 1000).round() / 1000,
      'variant': info.variant,
      'version': version,
    };
    _write('$sha.bin', image);
    _write('$sha.json', utf8.encode(jsonEncode(entry)));
    _signers[sha] = signer;
    return _public(entry);
  }

  void _write(String name, List<int> data) {
    final tmp = File('${dir.path}/$name.tmp');
    tmp.writeAsBytesSync(data, flush: true);
    tmp.renameSync('${dir.path}/$name');
  }

  void remove(String releaseId) {
    final e = _find(releaseId);
    for (final suffix in ['.bin', '.json']) {
      final f = File('${dir.path}/${e['sha256']}$suffix');
      if (f.existsSync()) f.deleteSync();
    }
  }

  Future<Map<String, Object?>> _verified(String releaseId) async {
    final e = _find(releaseId);
    if (await _signer(e) == null) {
      // Its key was withdrawn: not offered any more.
      throw ControllerError.notFound('no such firmware release');
    }
    return e;
  }

  /// What a box fetches before the image: the manifest and the signature.
  Future<Uint8List> releaseTextOf(String releaseId) async {
    final e = await _verified(releaseId);
    return releaseText(
      e['platform']! as String,
      e['version']! as String,
      e['size']! as int,
      e['sha256']! as String,
      e['signature']! as String,
    );
  }

  Future<Uint8List> image(String releaseId) async {
    final e = await _verified(releaseId);
    return File('${dir.path}/${e['sha256']}.bin').readAsBytesSync();
  }

  // --- updates -------------------------------------------------------------------

  void _refresh() {
    final now = _now();
    for (final a in attempts.values) {
      if (_active.contains(a['state']) &&
          now - (a['updated_at']! as num) > timeoutS) {
        a
          ..['state'] = 'timeout'
          ..['updated_at'] = now;
      }
    }
  }

  List<Map<String, Object?>> updates() {
    _refresh();
    final ids = attempts.keys.toList()..sort();
    return [for (final id in ids) Map.of(attempts[id]!)];
  }

  /// Why the live game may not start now: an update on its way to a box.
  String? busy() {
    _refresh();
    final nodes = [
      for (final e in attempts.entries)
        if (_active.contains(e.value['state'])) e.key,
    ]..sort();
    if (nodes.isEmpty) return null;
    return 'firmware updates are on their way to box(es) ${nodes.join(', ')}: '
        'wait for them, or cancel them (DELETE /api/v1/firmware/updates) '
        'before the game starts';
  }

  /// Stops tracking the updates on their way.
  List<int> cancel() {
    final now = _now();
    final nodes = [
      for (final e in attempts.entries)
        if (_active.contains(e.value['state'])) e.key,
    ];
    for (final n in nodes) {
      attempts[n]!
        ..['state'] = 'cancelled'
        ..['updated_at'] = now;
    }
    return nodes;
  }

  /// Why this box cannot take this release now, from its HELLO; null: it can.
  String? eligibility(
    Map<String, Object?> release,
    Map<String, Object?> node, {
    bool retry = false,
  }) {
    final fw = node['fw_version'];
    if (node['platform'] == null || fw == null || '$fw'.isEmpty) {
      return 'unknown';
    }
    if (platformName(node['platform']) != release['platform']) {
      return 'wrong_platform';
    }
    if (!boxTiers.contains(node['tier'])) return 'wrong_tier';
    if (firmwareVersionKey('$fw') == null) return 'unknown_version';
    if (compareVersions(release['version']! as String, '$fw') <= 0) {
      return 'not_newer';
    }
    final current = attempts[node['node_id']! as int];
    if (current != null &&
        _active.contains(current['state']) &&
        !(retry && current['state'] == 'sent')) {
      return 'in_progress';
    }
    return null;
  }

  /// Sends CMD update to the given boxes (node ids, or "all") of the live game.
  Future<Map<String, Object?>> install(String releaseId, Object? nodes) async {
    final g = engine.liveGame;
    if (g == null) {
      throw ControllerError.conflict(
        'no live game: join the boxes to a game first (updates go only '
        'before it starts)',
      );
    }
    if (g['state'] != 'ready') {
      throw ControllerError.conflict(
        "game ${g['id']} is ${g['state']}: firmware updates only before a "
        'game starts, never during one',
      );
    }
    if (engine.caSha256 == null || engine.linkUrls.isEmpty) {
      throw ControllerError.conflict(
        'this phone does not serve HTTPS on the field Wi-Fi: boxes fetch '
        'updates only over HTTPS pinned to the field CA',
      );
    }
    final e = await _verified(releaseId);
    _refresh();
    final known = <int, Map<String, Object?>>{
      for (final n in engine.nodes())
        if (n['node_id'] is int) n['node_id']! as int: n,
    };
    final List<int> targets;
    if (nodes == 'all') {
      targets = known.keys.toList()..sort();
    } else if (nodes is List &&
        nodes.isNotEmpty &&
        nodes.every((n) => n is int)) {
      targets = nodes.cast<int>().toSet().toList()..sort();
    } else {
      throw ControllerError('nodes: a list of node ids, or "all"');
    }
    final sha = e['sha256']! as String;
    final params = <String, Object?>{
      'id': sha.substring(0, 16),
      'version': e['version'],
    };
    final results = <Map<String, Object?>>[];
    for (final nodeId in targets) {
      final node = known[nodeId];
      var why = node == null
          ? 'not_in_game'
          : eligibility(e, node, retry: nodes != 'all');
      if (why == null) {
        try {
          final seq = engine.sendUpdate(nodeId, params);
          final now = _now();
          attempts[nodeId] = {
            'node_id': nodeId,
            'game': g['id'],
            'release': params['id'],
            'version': e['version'],
            'from_version': '${node!['fw_version']}',
            'state': 'sent',
            'reason': null,
            'seq': seq,
            'sent_at': now,
            'updated_at': now,
          };
        } on ControllerError catch (err) {
          if (err.status != 503) rethrow;
          why = 'radio';
        }
      }
      results.add({'node_id': nodeId, 'result': why ?? 'sent'});
    }
    if (nodes != 'all' &&
        targets.length == 1 &&
        results.first['result'] != 'sent') {
      throw ControllerError.conflict(
        'box ${targets.first}: ${results.first['result']}',
      );
    }
    _emit();
    return {'release': await _public(e), 'results': results};
  }

  /// A box's report on its update, authenticated with the live game's key.
  Map<String, Object?> report(Uint8List body, String? mac) {
    final ({int game, int node, String release, String result, String version})
    r;
    try {
      r = parseReport(body);
    } on ReleaseException {
      throw ControllerError('not a firmware report');
    }
    final g = engine.liveGame;
    final key = engine.gameKey;
    if (g == null || g['id'] != r.game || key.isEmpty) {
      throw ControllerError.conflict("not this controller's live game");
    }
    if (mac == null ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(mac) ||
        !constantTimeEquals(
          utf8.encode(reportMac(key, body)),
          utf8.encode(mac),
        )) {
      throw ControllerError("the report's MAC does not verify");
    }
    final a = attempts[r.node];
    if (a == null ||
        a['release'] != r.release ||
        !(_active.contains(a['state']) || a['state'] == 'timeout')) {
      return {'accepted': false};
    }
    a
      ..['state'] = r.result == 'installed' ? 'installed' : 'failed'
      ..['reason'] = r.result == 'installed' ? null : r.result
      ..['updated_at'] = _now();
    _emit();
    return {'accepted': true};
  }

  /// A box's HELLO shows what it runs; its node.update_failed says why an
  /// update failed where it could not report over HTTPS (decision OT-8).
  void onMessage(Map<String, Object?> msg) {
    final ev = msg['event'];
    if (msg['type'] == 'event' &&
        ev is Map &&
        ev['type'] == 'node.update_failed') {
      _failedOverRadio(ev.cast<String, Object?>());
      return;
    }
    final node = msg['node'];
    if (msg['type'] != 'node' || node is! Map) return;
    final fw = node['fw_version'];
    final id = node['node_id'];
    if (fw is! String || id is! int) return;
    final a = attempts[id];
    if (a == null ||
        !(_active.contains(a['state']) || a['state'] == 'timeout')) {
      return;
    }
    if (fw == a['version']) {
      a
        ..['state'] = 'done'
        ..['reason'] = null
        ..['updated_at'] = _now();
      _emit();
    } else if (a['state'] == 'installed' &&
        msg['kind'] == 'hello' &&
        fw == a['from_version']) {
      a
        ..['state'] = 'rolled_back'
        ..['reason'] = 'self_test'
        ..['updated_at'] = _now();
      _emit();
    }
  }

  void _failedOverRadio(Map<String, Object?> ev) {
    final data = (ev['data'] as Map?) ?? const {};
    final nodeId = ev['node'];
    final release = data['release'];
    final reason = data['reason'];
    if (nodeId is! int || reason is! String || !_reason.hasMatch(reason)) {
      return;
    }
    final a = attempts[nodeId];
    if (a == null ||
        a['release'] != release ||
        !(a['state'] == 'sent' || a['state'] == 'timeout')) {
      return;
    }
    a
      ..['state'] = 'failed'
      ..['reason'] = reason
      ..['updated_at'] = _now();
    _emit();
  }

  Future<Map<String, Object?>> status() async => {
    'keys': [for (final k in keys) releaseKeyId(k)],
    'https': engine.caSha256 != null && engine.linkUrls.isNotEmpty,
    'slot_size': slotSize,
    'max_releases': maxReleases,
    'releases': await releases(),
    'updates': updates(),
  };

  void _emit() => engine.emit({'type': 'firmware', 'updates': updates()});
}

/// The release keys given to a phone controller: standard base64 of 32
/// bytes each, at most 8 (the Pi's `[firmware] release_keys`).
List<String> validReleaseKeys(Iterable<String> keys) => [
  for (final k in keys.map((k) => k.trim()))
    if (releasePublicKey(k) != null) k,
].take(8).toList();

/// The firmware folder in the controller's folder.
String firmwareDir(String controllerDir) => '$controllerDir/firmware';
