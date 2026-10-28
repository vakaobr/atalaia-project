// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The remote GM on the Android field controller (PE24 slice S7; plan phase
/// 19, P4R12): the Pi's controller/atalaia_controller/remote_gm.py in Dart.
///
/// Off by default. Only with the sync's `remote_gm` on (or the ATAK
/// relay's `remote`) does the phone open `WS /api/v1/sync/stream` to its
/// site server and keep it open: the phone opens the connection (it sits
/// behind 4G and carrier-grade NAT), and the site server never holds its GM
/// token. On the socket (protocol/sync.md):
///
/// - `hello` once (`remote_gm`, and `atak: true` only with the relay on),
///   then `live`: the live game as the console sees it, at most every 2 s
///   when something changed and every 30 s anyway; never a position, a
///   token, a key or a check-in; sent only with `remote_gm` on;
/// - `command` from the site server (start, pause, resume, end, a GM
///   message, a declared mode command; nothing else), each checked with the
///   shared format, refused for another game, one sent more than 60 s ago
///   by the site server's clock, one already had (by its id) and any while
///   `remote_gm` is off, else carried out through the engine as the
///   console's GM token would; `start` takes an optional `force` (the
///   console's *Start anyway*, decision RG-1);
/// - `command.result` back (a start refused for roles with no joined node is
///   `conflict` with those roles in `missing`, so the site server's page can
///   ask *Start anyway?* and send it again with `force`); `cot` for the ATAK relay once the site
///   server's `hello.ack` says `atak_relay: true` (controller_atak.dart's
///   events, at most 100 a message, 500 waiting);
/// - with `[sync] branding = "site"` the socket opens even with both of
///   those off (BR24): only `hello` (`remote_gm: false`) and pings leave,
///   and the site server's `field.changed` note (the field's branding, saved
///   teams or check-in settings changed) makes the sync pull them at once.
///
/// Every command, carried out or refused, is logged in the store (one
/// document, "remote_commands", kept 365 days) and shown to the GM by
/// `GET /api/v1/remote-gm`. The client reconnects after a failure: 5 s,
/// doubling up to 5 min (5 min at once when the key is refused).
library;

import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart';

import 'controller_engine.dart';
import 'controller_positions.dart' show ControllerPositions;
import 'controller_sync.dart';
import 'controller_sync_format.dart';

const streamPath = '/api/v1/sync/stream';
const _liveMinS = 2.0;
const _liveEveryS = 30.0;
const _pingS = 30.0;
const _positionsMinS = 5.0; // changed positions go at most this often (PKD-5)
const _positionsEveryS = 30.0; // and, while there are any, at least this often
const _backoffMinS = 5.0;
const _backoffMaxS = 300.0;
const _authRefused = 4401;
const _broadcast = 0xffff;
const cotQueueMax = 500;
const remoteLogDays = 365;
const _logMax = 5000;
const _wsGuid = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

/// The site server did not open the stream: its HTTP status (0: a bad
/// handshake).
class RemoteRefused implements Exception {
  const RemoteRefused(this.status);
  final int status;
  @override
  String toString() => status == 0
      ? 'not a WebSocket handshake'
      : 'the site server answered $status';
}

/// The stream's address from the sync's: https to wss, http (this machine
/// only) to ws.
String streamUrl(String syncUrl) {
  final u = Uri.parse(syncUrl);
  final path = u.path.replaceAll(RegExp(r'/+$'), '') + streamPath;
  return Uri(
    scheme: u.scheme == 'https' ? 'wss' : 'ws',
    host: u.host,
    port: u.hasPort ? u.port : null,
    path: path,
  ).toString();
}

/// One open stream: what [RemoteGm] reads and writes (a WebSocket, or a
/// test's).
abstract interface class RemoteSocket {
  Stream<Object?> get messages;
  void send(String text);
  int? get closeCode;
  Future<void> close();
}

class _IoSocket implements RemoteSocket {
  _IoSocket(this.ws);
  final WebSocket ws;
  @override
  Stream<Object?> get messages => ws;
  @override
  void send(String text) => ws.add(text);
  @override
  int? get closeCode => ws.closeCode;
  @override
  Future<void> close() => ws.close();
}

class RemoteGm {
  RemoteGm(
    this.engine,
    this.sync, {
    this.remoteGm = true,
    this.atakRemote = false,
    Future<RemoteSocket> Function()? connect,
    double Function()? wall,
  }) : _wall = wall ?? engine.wallSeconds {
    _connect = connect ?? _open;
    sync.remoteStatus = status;
    engine
      ..addListener(_onEngine)
      ..remoteGmView = (limit) => {
        'enabled': remoteGm,
        'stream': status(),
        'log': remoteCommands(limit),
      };
  }

  final ControllerEngine engine;
  final ControllerSync sync;

  /// Take commands and send the live view (`[sync] remote_gm`).
  final bool remoteGm;

  /// Push CoT for the remote ATAK relay (`[atak] remote`).
  final bool atakRemote;
  late final Future<RemoteSocket> Function() _connect;
  final double Function() _wall;

  bool connected = false;
  double? connectedAt;
  String? lastError;
  int commands = 0, lives = 0, cotSent = 0;
  bool atakRelay = false;

  /// Called when the site server says it relays CoT (the emitter sends its
  /// whole picture again) and with false when the socket goes.
  void Function(bool ready)? onRelay;

  /// Called on the site server's `field.changed` note (BR24, PKD-1) with its
  /// `what` (null: the branding and settings): the sync pulls it now.
  void Function(List<Object?>? what)? onFieldChanged;

  final _cot = Queue<String>();
  RemoteSocket? _socket;
  bool _stopped = true, _dirty = true, _posDirty = true;
  String?
  _posDigest; // what the site server has of the positions (never logged)
  int positionsSent = 0;
  Timer? _tick, _retry;
  double _lastLive = -1e9, _lastPing = 0, _lastPositions = -1e9;
  double _delay = _backoffMinS;
  DateTime? _began;

  // --- the store's log --------------------------------------------------------

  static const _doc = 'remote_commands';

  List<Map<String, Object?>> _log() => [
    for (final e in (engine.store.document(_doc) as List?) ?? const [])
      if (e is Map) e.cast<String, Object?>(),
  ];

  Map<String, Object?>? remoteCommand(String id) {
    for (final e in _log()) {
      if (e['command_id'] == id) return e;
    }
    return null;
  }

  /// Logs one command and what came of it; drops entries older than
  /// [remoteLogDays] (store.py `add_remote_command`).
  Map<String, Object?> addRemoteCommand(Map<String, Object?> entry) {
    final now = _wall();
    final log = _log()
      ..removeWhere(
        (e) => (e['received_at']! as num) < now - remoteLogDays * 86400,
      );
    final cid = entry['command_id'];
    if (cid != null) {
      final found = log.where((e) => e['command_id'] == cid).firstOrNull;
      if (found != null) return found;
    }
    final next = log.fold<int>(0, (m, e) => max(m, e['id']! as int)) + 1;
    final row = <String, Object?>{
      'id': next,
      'command_id': cid,
      'received_at': entry['received_at'] ?? now,
      'user_id': entry['user_id'],
      'username': entry['username'],
      'command': entry['command'],
      'params': entry['params'] ?? <String, Object?>{},
      'game_id': entry['game_id'],
      'game_seed': entry['game_seed'],
      'result': entry['result'],
      'detail': entry['detail'],
    };
    log.add(row);
    if (log.length > _logMax) log.removeRange(0, log.length - _logMax);
    engine.store.putDocument(_doc, log);
    return row;
  }

  /// The newest first (store.py `remote_commands`).
  List<Map<String, Object?>> remoteCommands([int limit = 200]) =>
      _log().reversed.take(limit).toList();

  // --- the connection -----------------------------------------------------------

  /// The opening handshake by hand (RFC 6455 section 4), so a refusal's
  /// status (401, 403) is known; then dart:io's WebSocket on the socket.
  Future<RemoteSocket> _open() async {
    final timeout = Duration(
      milliseconds: (sync.config.timeoutS * 1000).round(),
    );
    final pem = sync.config.caPem;
    final client = HttpClient(
      context: pem == null || pem.trim().isEmpty
          ? null
          : (SecurityContext(withTrustedRoots: false)
              ..setTrustedCertificatesBytes(utf8.encode(pem))),
    )..connectionTimeout = timeout;
    try {
      final base = Uri.parse(sync.config.url);
      final uri = base.replace(
        path: base.path.replaceAll(RegExp(r'/+$'), '') + streamPath,
      );
      final nonce = base64.encode(
        List.generate(16, (_) => Random.secure().nextInt(256)),
      );
      final req = await client.getUrl(uri).timeout(timeout);
      req
        ..followRedirects = false
        ..headers.set('Connection', 'Upgrade')
        ..headers.set('Upgrade', 'websocket')
        ..headers.set('Sec-WebSocket-Version', '13')
        ..headers.set('Sec-WebSocket-Key', nonce)
        ..headers.set('Authorization', 'Bearer ${sync.config.apiKey}')
        ..headers.set(
          'User-Agent',
          'atalaia-controller/$syncAppVersion (android)',
        );
      final resp = await req.close().timeout(timeout);
      if (resp.statusCode != 101) {
        throw RemoteRefused(resp.statusCode);
      }
      final want = base64.encode(
        sha1.convert(utf8.encode('$nonce$_wsGuid')).bytes,
      );
      if (resp.headers.value('sec-websocket-accept') != want) {
        throw const RemoteRefused(0);
      }
      final socket = await resp.detachSocket();
      return _IoSocket(WebSocket.fromUpgradedSocket(socket, serverSide: false));
    } finally {
      client.close();
    }
  }

  void start() {
    _stopped = false;
    _run();
  }

  Future<void> stop() async {
    _stopped = true;
    _retry?.cancel();
    _tick?.cancel();
    engine.removeListener(_onEngine);
    await _socket?.close();
  }

  void _onEngine(Map<String, Object?> msg) {
    // (a projected-score tick, decision BSC-2, is not in the site's live view)
    if (msg['tick'] != true &&
        const [
          'game',
          'event',
          'nodes',
          'node',
          'score',
        ].contains(msg['type'])) {
      _dirty = true;
    }
    if (const ['player_position', 'positions', 'game'].contains(msg['type'])) {
      _posDirty = true;
    }
  }

  Future<void> _run() async {
    if (_stopped) return;
    _began = DateTime.now();
    var refused = false;
    try {
      final ws = await _connect();
      _socket = ws;
      connected = true;
      connectedAt = _wall();
      lastError = null;
      await _session(ws);
      if (ws.closeCode == _authRefused) {
        refused = true;
        lastError = 'the site server refused the API key';
      }
    } on RemoteRefused catch (e) {
      refused = e.status == 401 || e.status == 403;
      lastError = refused ? 'the site server refused the API key' : '$e';
    } on Object catch (e) {
      lastError = '$e';
    } finally {
      connected = false;
      _setRelay(false);
      _tick?.cancel();
      _socket = null;
    }
    if (_stopped) return;
    if (refused) {
      _delay = _backoffMaxS;
    } else if (DateTime.now().difference(_began!).inSeconds > 60) {
      _delay = _backoffMinS;
    }
    final wait = _delay;
    _delay = min(_delay * 2, _backoffMaxS);
    _retry = Timer(Duration(milliseconds: (wait * 1000).round()), _run);
  }

  void _send(RemoteSocket ws, String kind, Map<String, Object?> body) =>
      ws.send(jsonEncode({'type': kind, ...body}));

  Future<void> _session(RemoteSocket ws) async {
    final hello = <String, Object?>{...sync.envelope(), 'remote_gm': remoteGm};
    if (atakRemote) hello['atak'] = true;
    _send(ws, 'hello', hello);
    _setRelay(false);
    _cot.clear();
    _lastLive = -1e9;
    _lastPositions = -1e9;
    _lastPing = _monotonic();
    _dirty = true;
    _posDirty = true;
    _posDigest = null;
    _tick = Timer.periodic(const Duration(milliseconds: 500), (_) => _pump(ws));
    _pump(ws);
    await for (final raw in ws.messages) {
      if (raw is String) _onMessage(ws, raw);
      if (_stopped) break;
    }
  }

  double _monotonic() => DateTime.now().millisecondsSinceEpoch / 1000;

  void _pump(RemoteSocket ws) {
    _sendCot(ws);
    final now = _monotonic();
    final due =
        (_dirty && now - _lastLive >= _liveMinS) ||
        now - _lastLive >= _liveEveryS;
    if (due && remoteGm) {
      // No live view leaves the field without the remote GM.
      _dirty = false;
      final body = liveBody();
      if (body != null) {
        _send(ws, 'live', body);
        lives++;
      }
      _lastLive = now;
    }
    if (remoteGm) _pumpPositions(ws, now);
    if (now - _lastPing >= _pingS) {
      _send(ws, 'ping', {});
      _lastPing = now;
    }
  }

  /// The live game's player positions for the remote GM (PKD-5), when they
  /// changed (at most every 5 s) or, while there are any, every 30 s so their
  /// ages stay fresh; an empty list once when the last one is gone or the
  /// game ends. Never logged.
  void _pumpPositions(RemoteSocket ws, double now) {
    final due =
        (_posDirty && now - _lastPositions >= _positionsMinS) ||
        now - _lastPositions >= _positionsEveryS;
    if (!due) return;
    _posDirty = false;
    final body = positionsBody();
    if (body == null) {
      _lastPositions = now;
      return;
    }
    final digest = _positionsDigest(body);
    final same = _posDigest == digest;
    if (same && (body['positions']! as List).isEmpty) {
      _lastPositions = now;
      return;
    }
    if (same && now - _lastPositions < _positionsEveryS) return;
    _posDigest = digest;
    _send(ws, 'positions', body);
    positionsSent++;
    _lastPositions = now;
  }

  String _positionsDigest(Map<String, Object?> body) => jsonEncode([
    body['game'],
    for (final p in (body['positions']! as List))
      {
        for (final e in (p as Map).entries)
          if (e.key != 'age_s') e.key: e.value,
      },
  ]);

  /// The `positions` message, checked; null when it does not pass.
  Map<String, Object?>? positionsBody() {
    final body = {...sync.envelope(), ...positions()};
    try {
      return checkPositions(jsonDecode(jsonEncode(body)));
    } on SyncFormatError {
      return null;
    }
  }

  /// `{game, positions}`: the live game's positions the GM sees (a GM sees
  /// everyone's), the latest of each player, none older than three reporting
  /// intervals; `game` null when none is live.
  Map<String, Object?> positions() {
    final game = engine.liveGame;
    final state = game?['state'];
    if (game == null || (state != 'running' && state != 'paused')) {
      return {'game': null, 'positions': <Object?>[]};
    }
    final gid = game['id']! as int;
    final now = _wall();
    final teams = (game['teams'] as List?)?.cast<String>() ?? const <String>[];
    final stale = 3 * ControllerPositions.interval(game);
    final items = <Map<String, Object?>>[];
    final all = engine.positions?.playerPositions(gid) ?? const {};
    for (final pid in all.keys.toList()..sort()) {
      final pos = all[pid]!;
      final received = pos['received_at'];
      final age = max(0.0, now - (received is num ? received.toDouble() : now));
      if (age > stale) continue;
      final item = <String, Object?>{
        'player_id': pid,
        'source': pos['source'],
        'age_s': (age * 10).round() / 10,
      };
      final teamId = pos['team'];
      if (teamId is int && teamId >= 1 && teamId <= teams.length) {
        item['team'] = teams[teamId - 1];
      }
      final squad = pos['squad'];
      if (squad is int && squad > 0) item['squad'] = squad;
      final role = engine.checkin?.checkinRow(gid, pid)?['role'];
      if (role is String && role.isNotEmpty) item['role'] = role;
      if (pos['level'] is int) item['level'] = pos['level'];
      if (pos['source'] == 'gps') {
        for (final k in const ['lat', 'lon', 'accuracy_m']) {
          if (pos[k] != null) item[k] = pos[k];
        }
      } else {
        for (final k in const ['room', 'zone', 'x', 'y']) {
          if (pos[k] != null) item[k] = pos[k];
        }
      }
      items.add(item);
    }
    return {
      'game': {'game_id': gid, 'game_seed': game['game_seed']},
      'positions': items,
    };
  }

  void _setRelay(bool on) {
    if (on == atakRelay) return;
    atakRelay = on;
    onRelay?.call(on);
  }

  void _onMessage(RemoteSocket ws, String raw) {
    Object? msg;
    try {
      msg = jsonDecode(raw);
    } on FormatException {
      return;
    }
    if (msg is! Map<String, Object?>) return;
    final kind = msg.remove('type');
    if (kind == 'hello.ack') {
      _setRelay(atakRemote && msg['atak_relay'] == true);
    } else if (kind == 'field.changed') {
      try {
        checkFieldChanged(msg);
      } on SyncFormatError {
        return; // not in a form this controller knows: ignored
      }
      onFieldChanged?.call(msg['what'] as List<Object?>?);
    } else if (kind == 'command') {
      final result = handleCommand(msg);
      _send(ws, 'command.result', {...sync.envelope(), ...result});
      _dirty = true;
    }
  }

  // --- the remote ATAK relay ------------------------------------------------------

  /// The emitter's events for the relay: queued while the site server takes
  /// them, else dropped (its next full cycle sends everything again).
  /// Returns how many were queued.
  int pushCot(List<String> events) {
    if (!connected || !atakRelay) return 0;
    for (final e in events) {
      _cot.add(e);
      if (_cot.length > cotQueueMax) _cot.removeFirst(); // older ones go
    }
    final ws = _socket;
    if (ws != null) _sendCot(ws);
    return events.length;
  }

  void _sendCot(RemoteSocket ws) {
    while (_cot.isNotEmpty && atakRelay) {
      final batch = <String>[];
      while (_cot.isNotEmpty && batch.length < maxCotEvents) {
        batch.add(_cot.removeFirst());
      }
      _send(ws, 'cot', {...sync.envelope(), 'events': batch});
      cotSent += batch.length;
    }
  }

  // --- commands ---------------------------------------------------------------------

  /// Checks and carries out one command; logs it whatever came of it.
  /// Returns `{id, code, detail}` for `command.result`.
  Map<String, Object?> handleCommand(Object? body) {
    commands++;
    final received = _wall();
    final cid = body is Map ? body['id'] : null;
    final Map<String, Object?> cmd;
    try {
      cmd = checkCommand(jsonDecode(jsonEncode(body)));
    } on SyncFormatError catch (e) {
      final detail = _cap('$e');
      addRemoteCommand({
        'command_id': null,
        'result': 'invalid',
        'detail': detail,
        'received_at': received,
        if (body is Map && body['command'] is String)
          'command': body['command'],
      });
      return {
        'id': cid is String && cid.length == 36
            ? cid
            : '00000000-0000-0000-0000-000000000000',
        'code': 'invalid',
        'detail': detail,
      };
    }
    final id = cmd['id']! as String;
    final prior = remoteCommand(id);
    if (prior != null) {
      return {'id': id, 'code': prior['result'], 'detail': prior['detail']};
    }
    final game = cmd['game']! as Map;
    final user = cmd['user']! as Map;
    final entry = <String, Object?>{
      'command_id': id,
      'received_at': received,
      'user_id': user['id'],
      'username': user['username'],
      'command': cmd['command'],
      'params': cmd['params'],
      'game_id': game['game_id'],
      'game_seed': game['game_seed'],
    };
    final String code;
    final String? detail;
    List<String>? missing;
    final sentAt = cmd['sent_at']! as num;
    if (!remoteGm) {
      (code, detail) = ('remote_gm_off', 'remote GM is off on this controller');
    } else if ((received - sentAt).abs() > commandStaleS) {
      (code, detail) = (
        'stale',
        'sent ${(received - sentAt).round()} s ago by the site server\'s clock',
      );
    } else {
      (code, detail, missing) = _carryOut(cmd);
    }
    final row = addRemoteCommand({...entry, 'result': code, 'detail': detail});
    return {
      'id': id,
      'code': row['result'],
      'detail': row['detail'],
      if (missing != null && missing.isNotEmpty) 'missing': missing,
    };
  }

  static String _cap(String s) => s.length > 200 ? s.substring(0, 200) : s;

  /// `(code, detail, missing)`: `missing` names the roles without a joined
  /// node when a start was refused for that (the console's `start_check`).
  (String, String?, List<String>?) _carryOut(Map<String, Object?> cmd) {
    final g = cmd['game']! as Map;
    final gid = g['game_id']! as int, seed = g['game_seed']! as int;
    final live = engine.liveGame;
    if (live == null || live['id'] != gid || live['game_seed'] != seed) {
      return (
        'not_live',
        "game $gid (seed $seed) is not this controller's live game",
        null,
      );
    }
    final params = (cmd['params']! as Map).cast<String, Object?>();
    var forced = <String>[];
    try {
      final Map<String, Object?> out;
      switch (cmd['command']) {
        case 'start':
          final force = params['force'] == true;
          if (force) {
            forced = (engine.startCheck()['missing']! as List).cast<String>();
          }
          out = engine.startGame(gid, force: force);
        case 'pause':
          out = engine.pauseGame(gid, '${params['reason'] ?? ''}');
        case 'resume':
          out = engine.resumeGame(gid);
        case 'end':
          out = engine.endGame(gid, '${params['reason'] ?? ''}');
        case 'message':
          final sent = engine.sendNodeCmd(_broadcast, 'message', {
            'text': params['text'],
          });
          return ('done', 'sent to every node (seq ${sent['seq']})', null);
        default:
          final sent = engine.sendNodeCmd(params['node'], 'mode', {
            'name': params['name'],
          });
          return (
            'done',
            'sent to node ${sent['node']} (seq ${sent['seq']})',
            null,
          );
      }
      if (forced.isNotEmpty) {
        // The console's "Start anyway", by a remote GM: also in the log.
        return (
          'done',
          _cap(
            'game $gid is ${out['state']}, started anyway without nodes '
            'for: ${forced.join(', ')}',
          ),
          null,
        );
      }
      return ('done', 'game $gid is ${out['state']}', null);
    } on ControllerError catch (e) {
      final code = switch (e.status) {
        404 => 'not_found',
        409 => 'conflict',
        503 => 'unavailable',
        _ => 'invalid',
      };
      final check = e.extra['start_check'];
      final missing = code == 'conflict' && check is Map
          ? [
              for (final r in (check['missing'] as List? ?? const []))
                '$r'.length > roleMax ? '$r'.substring(0, roleMax) : '$r',
            ].take(missingMax).toList()
          : null;
      return (code, _cap(e.message), missing);
    } on Object {
      return ('failed', 'the controller could not carry it out', null);
    }
  }

  // --- the live view --------------------------------------------------------------

  /// The `live` message, checked; null when it does not pass.
  Map<String, Object?>? liveBody() {
    final body = {...sync.envelope(), 'live': live()};
    try {
      return checkLive(jsonDecode(jsonEncode(body)));
    } on SyncFormatError {
      return null;
    }
  }

  Map<String, Object?>? live() {
    final game = engine.liveGame;
    if (game == null) return null;
    final gid = game['id']! as int;
    final Map<String, Object?> pub;
    final Map<String, Object?> totals;
    final List<Map<String, Object?>> nodes;
    try {
      pub = engine.getGame(gid);
      totals = (engine.score(gid)['teams']! as Map).cast<String, Object?>();
      nodes = engine.nodes(gid);
    } on ControllerError {
      return null;
    }
    final now = _wall();
    final env = {
      ...sync.envelope(),
      'game': {'game_id': gid, 'game_seed': game['game_seed']},
    };
    final outNodes = <Map<String, Object?>>[];
    for (final node in nodes) {
      var seen = node['last_seen'];
      if (seen == null) {
        final ago = node['seen_ms_ago'];
        seen = ago is num ? now - ago / 1000 : now;
      }
      final info = <String, Object?>{
        for (final k in nodeInfoKinds.keys)
          if (node[k] != null) k: node[k],
      };
      final caps = info['capabilities'];
      if (caps is List) info['capabilities'] = [for (final c in caps) '$c'];
      final entry = <String, Object?>{
        'node_id': node['node_id'],
        'name': node['name'] ?? 'node-${node['node_id']}',
        'role': (node['role'] as String?)?.isNotEmpty == true
            ? node['role']
            : '-',
        'last_seen': seen,
        'info': info,
      };
      try {
        checkNodes(
          jsonDecode(
            jsonEncode({
              ...env,
              'nodes': [entry],
            }),
          ),
        );
      } on SyncFormatError {
        continue;
      }
      outNodes.add(entry);
    }
    final log = engine.store.eventLog(gid);
    final events = <Map<String, Object?>>[];
    for (var i = max(0, log.length - maxLiveEvents); i < log.length; i++) {
      final e = log[i];
      try {
        events.add(
          checkEvent(
            jsonDecode(
              jsonEncode({
                'id': i + 1,
                for (final k in const [
                  'node',
                  'seq',
                  't',
                  'type',
                  'team',
                  'squad',
                  'prio',
                  'data',
                  'epoch',
                  'pkt_seq',
                ])
                  k: e[k],
              }),
            ),
            'event',
          ),
        );
      } on SyncFormatError {
        continue;
      }
    }
    final commands = engine.modes.modeOf(game['mode_id'])?.commands ?? const {};
    final names = commands.keys.toList()..sort();
    final teams = (pub['teams']! as List).cast<String>();
    return {
      'game': env['game'],
      'name': pub['name'],
      'mode_id': pub['mode_id'],
      'teams': teams,
      'state': pub['state'],
      'in_charge': engine.inCharge,
      'totals': {for (final t in teams) t: (totals[t] as int?) ?? 0},
      'game_time_ms': pub['game_time_ms'],
      'duration_ms': (pub['duration_ms'] as int?) ?? 0,
      'nodes': outNodes,
      'events': events,
      'mode_commands': [
        for (final n in names)
          {
            'name': n,
            'roles': [
              ...?((commands[n] as Map?)?['roles'] as List?)?.cast<Object?>(),
            ],
          },
      ],
    };
  }

  Map<String, Object?> status() => {
    'enabled': remoteGm,
    'connected': connected,
    'connected_at': connectedAt,
    'last_error': lastError,
    'commands': commands,
    'atak': {'enabled': atakRemote, 'relay': atakRelay, 'sent': cotSent},
  };
}
