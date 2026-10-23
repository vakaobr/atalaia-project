// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Missing modes sent to boxes from a phone controller (slice S7b of
/// PE24): the Dart counterpart of the Pi controller's
/// controller/atalaia_controller/mode_fetch.py (phase 5 plan phase 13a,
/// decisions P5B-8 to P5B-17 and P5D-*; protocol/mode-packages.md,
/// "Fetching missing modes").
///
/// A box that lacks a part of the game's mode is joined again with **join
/// key 16** (`fetch_modes`): it joins the field's Wi-Fi and, over HTTPS
/// pinned to the field CA (join keys 13 and 14), fetches each part it lacks
/// from this controller, checks it with the mode keys built into its own
/// firmware (the settings' box keys, so the controller offers only what
/// boxes will take), keeps it, reports, and only then says HELLO. Only
/// between games: the packages are served only while the live game is
/// ready, and the start guard waits while fetches are on their way.
///
/// A HELLO ends a fetch only when the controller holds HTTPS reports that
/// the box keeps every part it was offered (P5D-14 to P5D-18): a HELLO
/// without them leaves the fetch on its way (`hello_seen`) until the
/// missing report, the box's `node.modes_failed` or the timeout (reason
/// `report_lost`); `node.modes_failed` is taken even after a fetch ended in
/// its HELLO.
///
/// Served without a token, for the boxes: the release text and the archive
/// of a part of the live game's mode the controller offers, and the box's
/// report (an HMAC-SHA256 with the game key in `X-Atalaia-Mac`). **Join key
/// 17** (`forget_modes`): a box marked by the GM forgets every package it
/// fetched at its next join.
///
/// The fetches live in memory, as on the Pi; what each box keeps (from its
/// last report) and the boxes marked to forget are in the store's settings.
/// The invites that send these joins over the radio (controller_boxes.dart,
/// slice S7c) take `fetch_modes`, and a box marked to forget gets key 17;
/// [onInvites] and [inviteView] follow them, as the Pi's reinvite.py does.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import 'controller_engine.dart';
import 'mode_package.dart';

/// A fetch on its way: the start guard waits.
const fetchActive = ['sent', 'fetching', 'installed'];

/// A box's failure said over LoRa.
const modesFailedEvent = 'node.modes_failed';

/// A HELLO, then neither the missing reports nor node.modes_failed.
const reportLost = 'report_lost';

/// Boxes whose fetched modes the store remembers.
const boxesKept = 64;

final _reason = RegExp(r'^[a-z][a-z_]{0,23}$');
final _device = RegExp(r'^[0-9a-f]{16}$');
final _macHex = RegExp(r'^[0-9a-f]{64}$');
const _good = ['offered', 'builtin'];

class ControllerModeFetch {
  ControllerModeFetch(
    this.engine,
    this.boxKeys, {
    this.timeoutS = 300,
    double Function()? clock,
  }) : clock = clock ?? engine.wallSeconds {
    engine
      ..modeFetch = this
      ..startGuards.add(busy)
      ..addListener(onMessage);
  }

  final ControllerEngine engine;

  /// The mode keys built into the boxes' firmware (base64).
  final List<String> boxKeys;
  final double timeoutS;
  final double Function() clock;

  /// Node id to the live game's fetch for it.
  final attempts = <int, Map<String, Object?>>{};

  // ---- the boxes' keys and the offer ------------------------------------

  List<String> boxKeyIds() => [
    for (final k in boxKeys)
      if (_keyIdOrNull(k) != null) _keyIdOrNull(k)!,
  ];

  static String? _keyIdOrNull(String k) {
    try {
      return keyId(k);
    } on FormatException {
      return null;
    }
  }

  bool https() => engine.caSha256 != null && engine.linkUrls.isNotEmpty;

  /// One part of a game's mode, and whether a box can be sent it.
  Map<String, Object?> part(String modeId) {
    final pkg = engine.modes.package(modeId);
    final out = <String, Object?>{
      'id': modeId,
      'name': null,
      'version': null,
      'kind': null,
      'min_tier': null,
      'size': null,
      'key_id': null,
      'verified': null,
    };
    if (pkg == null) return {...out, 'state': 'missing'};
    out
      ..['name'] = pkg.mode.name
      ..['version'] = pkg.mode.version
      ..['kind'] = pkg.kind;
    if (pkg.builtin) return {...out, 'state': 'builtin'};
    final signed = pkg.signed;
    if (signed == null || signed.isEmpty) return {...out, 'state': 'unsigned'};
    out
      ..['min_tier'] = signed['min_tier']
      ..['size'] = signed['size']
      ..['key_id'] = signed['key_id']
      ..['verified'] = signed['verified'];
    final sm = engine.signedModes;
    final trust = sm != null ? sm.trust(signed['key_id']) : 'untrusted';
    final String state;
    final size = signed['size'];
    if (trust != 'trusted') {
      state = trust;
    } else if (!boxModeKinds.contains(signed['kind'])) {
      state = 'kind';
    } else if (!boxKeyIds().contains(signed['key_id'])) {
      state = 'no_box_key';
    } else if (size is! int || size > boxMaxPackageBytes) {
      state = 'too_big';
    } else if (engine.modes.archive(modeId) == null) {
      state = 'unsigned';
    } else {
      state = 'offered';
    }
    return {...out, 'state': state};
  }

  /// What a box running [nodeModeId] can be sent: its parts, and `why` a
  /// fetch cannot help (null: it can). [tier]: the box's (0 full, 1 reduced).
  Map<String, Object?> offer(String nodeModeId, [int? tier]) {
    final parts = [for (final p in nodeModeId.split('+')) part(p)];
    String? why;
    if (boxKeys.isEmpty) {
      why = 'no_box_keys';
    } else if (!https()) {
      why = 'no_https';
    } else if (parts.any((p) => !_good.contains(p['state']))) {
      why =
          parts.firstWhere((p) => !_good.contains(p['state']))['state']
              as String;
    } else if (parts.every((p) => p['state'] == 'builtin')) {
      why = 'firmware';
    } else if (tier == 1 &&
        parts.any((p) => p['state'] == 'offered' && p['min_tier'] == 'full')) {
      why = 'tier';
    }
    return {
      'mode_id': nodeModeId,
      'parts': parts,
      'ok': why == null,
      'why': why,
    };
  }

  /// Why a join with key 16 for this mode would not help, or null.
  String? refusal(String nodeModeId, [int? tier]) {
    final o = offer(nodeModeId, tier);
    if (o['ok'] == true) return null;
    return switch (o['why']) {
      'no_box_keys' =>
        'no box mode keys are set ([modes] box_keys): the boxes would take nothing',
      'no_https' =>
        'this controller does not serve HTTPS: boxes fetch modes only over '
            'HTTPS pinned to the field CA',
      'firmware' =>
        'every part of this mode is built into the firmware: a box without it '
            'needs a firmware update, not a fetch',
      'tier' => 'a Reduced box cannot run a part that needs a Full box',
      final why =>
        'a part of $nodeModeId cannot be sent to boxes ($why): upload it as a '
            "package signed with a key built into the boxes' firmware",
    };
  }

  /// The live game's roles and what a box of each runs, with the offer.
  Map<String, Object?> roles() {
    final game = engine.liveGame;
    if (game == null) return {};
    final mode = engine.modes.modeOf(game['mode_id']);
    if (mode == null) return {};
    final names = mode.roles.keys.toList()..sort();
    return {for (final r in names) r: offer(mode.nodeModeId(r))};
  }

  // ---- what boxes fetch (no token) ---------------------------------------

  (Map<String, Object?>, Uint8List) _served(String modeId) {
    final game = engine.liveGame;
    if (game == null || game['state'] != 'ready') {
      throw ControllerError.conflict(
        'modes are sent to boxes only between games, while a live game is ready',
      );
    }
    if (!'${game['mode_id']}'.split('+').contains(modeId)) {
      throw ControllerError.notFound("not a part of the live game's mode");
    }
    final p = part(modeId);
    final archive = engine.modes.archive(modeId);
    final pkg = engine.modes.package(modeId);
    final signed = pkg?.signed;
    if (p['state'] != 'offered' ||
        archive == null ||
        signed == null ||
        signed.isEmpty) {
      throw ControllerError.notFound(
        '$modeId is not offered to boxes (${p['state']})',
      );
    }
    return (signed, archive);
  }

  Uint8List releaseText(String modeId) {
    final (s, _) = _served(modeId);
    return ModeRelease(
      s['id']! as String,
      s['version']! as String,
      s['kind']! as String,
      s['min_tier']! as String,
      s['size']! as int,
      s['sha256']! as String,
      s['signature']! as String,
    ).text();
  }

  Uint8List archive(String modeId) => _served(modeId).$2;

  // ---- the fetches -------------------------------------------------------

  int? _live() => engine.liveGame?['id'] as int?;

  /// A join with key 16 (or 17) was made for this node, or a plain one
  /// (which ends a fetch made for it before, P5D-18).
  void track(
    int gameId,
    int nodeId,
    String role,
    String modeId,
    String? device, {
    required bool fetch,
    required bool forget,
  }) {
    if (!fetch && !forget) {
      if (attempts.remove(nodeId) != null) _emit();
      return;
    }
    final parts = fetch
        ? [
            for (final p
                in (offer(modeId)['parts']! as List)
                    .cast<Map<String, Object?>>())
              if (p['state'] == 'offered') p['id'],
          ]
        : <Object?>[];
    final now = clock();
    attempts[nodeId] = {
      'node_id': nodeId,
      'game': gameId,
      'device_id': device,
      'role': role,
      'mode_id': modeId,
      'fetch': fetch,
      'forget': forget,
      'state': fetch ? 'sent' : 'forget',
      'reason': null,
      'mode': null,
      'installed': <Object?>[],
      'parts': parts,
      'kept': null,
      'hello_seen': false,
      'sent_at': now,
      'updated_at': now,
    };
    _emit();
  }

  void _refresh() {
    final now = clock();
    for (final a in attempts.values) {
      if (fetchActive.contains(a['state']) &&
          now - (a['updated_at']! as num) > timeoutS) {
        a
          ..['state'] = 'timeout'
          ..['reason'] = a['hello_seen'] == true ? reportLost : null
          ..['updated_at'] = now;
      }
    }
  }

  bool _covered(Map<String, Object?> a, [Map<String, Object?>? stored]) {
    final have = {
      ...(a['installed']! as List),
      ...((a['kept'] as Map?)?.keys ?? const []),
      ...(stored?.keys ?? const []),
    };
    return (a['parts'] as List? ?? const []).every(have.contains);
  }

  Map<String, Object?>? _storedKept(String? device) {
    if (device == null) return null;
    final box = (_load('mode_fetch.boxes', const {}) as Map)[device];
    final kept = box is Map ? box['kept'] : null;
    return kept is Map ? kept.cast<String, Object?>() : null;
  }

  /// The live game's fetches (and forgets), by node id.
  List<Map<String, Object?>> fetches() {
    _refresh();
    final live = _live();
    final ids = attempts.keys.toList()..sort();
    return [
      for (final n in ids)
        if (attempts[n]!['game'] == live) _copy(attempts[n]!),
    ];
  }

  static Map<String, Object?> _copy(Map<String, Object?> a) => {
    ...a,
    'installed': List.of(a['installed']! as List),
    'parts': List.of(a['parts']! as List),
    'kept': a['kept'] == null ? null : Map.of(a['kept']! as Map),
  };

  /// Why the live game may not start now: boxes still fetching its modes.
  String? busy() {
    _refresh();
    final live = _live();
    final nodes = [
      for (final e in attempts.entries)
        if (e.value['game'] == live && fetchActive.contains(e.value['state']))
          e.key,
    ]..sort();
    if (nodes.isEmpty) return null;
    return "boxes are fetching this game's modes: node(s) ${nodes.join(', ')}; "
        'wait for them, or stop waiting (DELETE /api/v1/mode-fetch) before '
        'the game starts';
  }

  /// A node of the live game whose fetch has not ended in its HELLO: not
  /// joined yet, even if the controller heard it.
  bool holds(int nodeId) {
    final a = attempts[nodeId];
    return a != null &&
        a['game'] == _live() &&
        a['fetch'] == true &&
        a['state'] != 'done';
  }

  /// An invite as the GM sees it (the re-invites, slice S7c): a box whose
  /// fetch has not ended in its HELLO has not joined (P5D-17).
  Map<String, Object?> inviteView(Map<String, Object?> inv) {
    if (inv['status'] != 'joined') return inv;
    final a = attempts[inv['node_id']];
    if (a == null ||
        a['game'] != inv['game'] ||
        a['fetch'] != true ||
        a['state'] == 'done' ||
        (a['device_id'] != null && a['device_id'] != inv['device_id'])) {
      return inv;
    }
    if (fetchActive.contains(a['state'])) {
      return {...inv, 'status': 'accepted', 'detail': null};
    }
    final reason = a['reason'];
    return {
      ...inv,
      'status': 'failed',
      'detail': 'mode fetch ${a['state']}${reason != null ? ': $reason' : ''}',
    };
  }

  /// The GM stops waiting for the fetches on their way.
  List<int> cancel() {
    final now = clock(), live = _live();
    final nodes = [
      for (final e in attempts.entries)
        if (e.value['game'] == live && fetchActive.contains(e.value['state']))
          e.key,
    ];
    for (final n in nodes) {
      attempts[n]!
        ..['state'] = 'cancelled'
        ..['updated_at'] = now;
    }
    if (nodes.isNotEmpty) _emit();
    return nodes;
  }

  /// The invites' progress (the re-invites, slice S7c).
  void onInvites(List<Map<String, Object?>> invites) {
    var changed = false;
    final now = clock();
    for (final inv in invites) {
      final a = attempts[inv['node_id']];
      if (a == null ||
          a['game'] != inv['game'] ||
          a['device_id'] != inv['device_id']) {
        continue;
      }
      if (inv['status'] == 'accepted' && a['state'] == 'sent') {
        a
          ..['state'] = 'fetching'
          ..['updated_at'] = now;
        changed = true;
      } else if ((inv['status'] == 'refused' || inv['status'] == 'failed') &&
          fetchActive.contains(a['state'])) {
        final reason = inv['status'] == 'refused' ? inv['detail'] : 'no_answer';
        a
          ..['state'] = 'failed'
          ..['reason'] = reason is String && _reason.hasMatch(reason)
              ? reason
              : 'no_answer'
          ..['updated_at'] = now;
        changed = true;
      }
    }
    if (changed) _emit();
  }

  /// A box's report on a part it fetched, authenticated with the live
  /// game's key.
  Map<String, Object?> report(Uint8List body, String? mac) {
    Map<String, Object?> r;
    try {
      r = parseModeReport(body);
    } on ModePackageError {
      throw ControllerError('not a mode fetch report');
    } on ArgumentError {
      throw ControllerError('not a mode fetch report');
    }
    final gameId = r['game']! as int, nodeId = r['node']! as int;
    final key = engine.gameKey;
    if (engine.liveGame?['id'] != gameId || engine.keyLost || key.isEmpty) {
      throw ControllerError.conflict("not this controller's live game");
    }
    if (mac == null ||
        !_macHex.hasMatch(mac) ||
        !_sameText(reportMac(key, body), mac)) {
      throw ControllerError("the report's MAC does not verify");
    }
    final kept = (r['kept']! as Map).cast<String, Object?>();
    final a = attempts[nodeId];
    final now = clock();
    final accepted =
        a != null &&
        a['game'] == gameId &&
        a['fetch'] == true &&
        [...fetchActive, 'timeout'].contains(a['state']);
    var joined = false;
    if (accepted) {
      a['kept'] = Map.of(kept);
      if (r['result'] == 'installed') {
        final installed = a['installed']! as List;
        if (!installed.contains(r['mode'])) installed.add(r['mode']);
        a
          ..['state'] = 'installed'
          ..['reason'] = null
          ..['mode'] = r['mode']
          ..['updated_at'] = now;
        if (a['hello_seen'] == true && _covered(a)) {
          a
            ..['state'] = 'done'
            ..['updated_at'] = now;
          joined = true;
        }
      } else {
        a
          ..['state'] = 'failed'
          ..['reason'] = r['result']
          ..['mode'] = r['mode']
          ..['updated_at'] = now;
      }
    }
    final device = (a?['device_id'] as String?) ?? _deviceOf(nodeId);
    _kept(device, nodeId, gameId, kept);
    _emit();
    if (joined) _joinedChanged();
    return {'accepted': accepted};
  }

  static bool _sameText(String a, String b) {
    final x = sha256.convert(utf8.encode(a)).bytes;
    final y = sha256.convert(utf8.encode(b)).bytes;
    var diff = 0;
    for (var i = 0; i < x.length; i++) {
      diff |= x[i] ^ y[i];
    }
    return diff == 0;
  }

  /// node.modes_failed: a box says over LoRa that its fetch failed where it
  /// could not report over HTTPS (P5E-8, P5E-10, P5D-15).
  void onFailedOverRadio(Map<String, Object?> ev) {
    final data = (ev['data'] as Map?) ?? const {};
    final nodeId = ev['node'], modeId = data['mode'], reason = data['reason'];
    if (nodeId is! int || reason is! String || !_reason.hasMatch(reason)) {
      return;
    }
    final a = attempts[nodeId];
    if (a == null ||
        a['game'] != _live() ||
        a['fetch'] != true ||
        a['state'] == 'failed') {
      return;
    }
    final heard = a['hello_seen'] == true || a['state'] == 'done';
    a
      ..['state'] = 'failed'
      ..['reason'] = reason
      ..['mode'] = modeId is String ? modeId : null
      ..['updated_at'] = clock();
    _emit();
    if (heard) _joinedChanged();
  }

  /// A HELLO ends a forget, and a fetch whose HTTPS reports say the box
  /// keeps every part it was offered (P5D-14); node.modes_failed fails one.
  void onMessage(Map<String, Object?> msg) {
    final ev = msg['event'];
    if (msg['type'] == 'event' && ev is Map && ev['type'] == modesFailedEvent) {
      onFailedOverRadio(ev.cast<String, Object?>());
      return;
    }
    final node = msg['node'];
    if (msg['type'] != 'node' || msg['kind'] != 'hello' || node is! Map) {
      return;
    }
    final nodeId = node['node_id'];
    if (nodeId is! int) return;
    var a = attempts[nodeId];
    // What it kept before this join; not with key 17, which made it forget.
    final device = a != null && a['forget'] != true
        ? a['device_id'] as String?
        : null;
    final stored = _storedKept(device);
    a = attempts[nodeId];
    if (a == null ||
        a['game'] != msg['game'] ||
        a['state'] == 'done' ||
        a['state'] == 'failed' ||
        (a['fetch'] == true && a['hello_seen'] == true)) {
      return;
    }
    final forgot = a['forget'] == true ? a['device_id'] as String? : null;
    final done = a['fetch'] != true || _covered(a, stored);
    if (done) {
      a
        ..['state'] = 'done'
        ..['reason'] = null
        ..['updated_at'] = clock();
    } else {
      a
        ..['hello_seen'] = true
        ..['updated_at'] = clock()
        ..['state'] = fetchActive.contains(a['state'])
            ? 'fetching'
            : a['state'];
    }
    if (forgot != null) setForget(forgot, false);
    _emit();
  }

  void _joinedChanged() {
    engine.boxes?.refreshInvites();
    final game = engine.liveGame;
    if (game != null && game['state'] == 'ready') {
      engine.emit({'type': 'game', 'game': engine.publicGame(game)});
    }
  }

  // ---- what boxes keep, and forgetting ------------------------------------

  String? _deviceOf(int nodeId) {
    for (final n in engine.nodes()) {
      if (n['node_id'] == nodeId) return n['device_id'] as String?;
    }
    return null;
  }

  Object? _load(String name, Object? fallback) {
    final raw = engine.store.getSetting(name);
    if (raw == null || raw.isEmpty) return fallback;
    try {
      return jsonDecode(raw);
    } on FormatException {
      return fallback;
    }
  }

  void _kept(
    String? device,
    int nodeId,
    int gameId,
    Map<String, Object?> kept,
  ) {
    final key = device ?? 'node-$nodeId';
    final loaded = _load('mode_fetch.boxes', const {});
    final boxes = Map<String, Object?>.of(
      loaded is Map ? loaded.cast<String, Object?>() : const {},
    )..remove(key);
    boxes[key] = {
      'device_id': device,
      'node_id': nodeId,
      'game': gameId,
      'kept': kept,
      'reported_at': (clock() * 1000).round() / 1000,
    };
    while (boxes.length > boxesKept) {
      boxes.remove(boxes.keys.first);
    }
    engine.store.setSetting('mode_fetch.boxes', jsonEncode(boxes));
  }

  List<String> forgetMarked() {
    final v = _load('mode_fetch.forget', const []);
    return [for (final d in v is List ? v : const []) '$d']..sort();
  }

  /// Marks a box (its device id) to forget its fetched modes at its next
  /// join (key 17).
  Map<String, Object?> setForget(Object? device, Object? on) {
    if (device is! String || !_device.hasMatch(device)) {
      throw ControllerError('device_id: 16 lower-case hex digits');
    }
    if (on is! bool) throw ControllerError('forget: true or false');
    final marked = forgetMarked().toSet();
    if (on) {
      marked.add(device);
    } else {
      marked.remove(device);
    }
    engine.store.setSetting(
      'mode_fetch.forget',
      jsonEncode(marked.toList()..sort()),
    );
    _emit();
    return {'device_id': device, 'forget': on};
  }

  /// Each box's fetched modes from its last report, and whether it is
  /// marked to forget them.
  List<Map<String, Object?>> boxes() {
    final marked = forgetMarked().toSet();
    final loaded = _load('mode_fetch.boxes', const {});
    final out = <Map<String, Object?>>[
      for (final b in (loaded is Map ? loaded.values : const []))
        if (b is Map)
          {
            ...b.cast<String, Object?>(),
            'forget': marked.contains(b['device_id']),
          },
    ];
    final listed = {for (final b in out) b['device_id']};
    for (final d in marked.difference(listed).toList()..sort()) {
      out.add({
        'device_id': d,
        'node_id': null,
        'game': null,
        'kept': null,
        'reported_at': null,
        'forget': true,
      });
    }
    out.sort((a, b) {
      final ad = a['device_id'] as String?, bd = b['device_id'] as String?;
      if ((ad == null) != (bd == null)) return ad == null ? 1 : -1;
      final c = (ad ?? '').compareTo(bd ?? '');
      if (c != 0) return c;
      return ((a['node_id'] as int?) ?? 0).compareTo(
        (b['node_id'] as int?) ?? 0,
      );
    });
    return out;
  }

  // ---- what the console shows ---------------------------------------------

  Map<String, Object?> status() => {
    'box_keys': boxKeyIds(),
    'https': https(),
    'timeout_s': timeoutS,
    'max_package_bytes': boxMaxPackageBytes,
    'game': _live(),
    'roles': roles(),
    'fetches': fetches(),
    'boxes': boxes(),
  };

  void _emit() => engine.emit({
    'type': 'mode_fetch',
    'game': _live(),
    'fetches': fetches(),
    'boxes': boxes(),
  });
}
