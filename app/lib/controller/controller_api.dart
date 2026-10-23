// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The Android field controller's REST API v1 (ADR-P3-12, decision PE24):
/// the Pi controller's endpoints (controller/atalaia_controller/api.py) for
/// games, scores, the event log, nodes and the controller's state, with the
/// same paths, tokens, bodies and status codes, so the GM console, the
/// scoreboard and the apps talk to either controller alike. The shared
/// contract cases (protocol/vectors/controller_api.json) are run against
/// both: test/controller/api_contract_test.dart here,
/// controller/tests/test_api_contract.py there.
///
/// Reading needs the read token or the GM token; anything that changes a
/// game or a node needs the GM token. Tokens go in
/// `Authorization: Bearer <token>`, compared in constant time.
///
///     GET  /healthz                          liveness, no token
///     GET  /api/v1/whoami                    which token this is: gm, read or player,
///                                            and the console's areas served
///                                            (`features`, [controllerFeatures])
///     GET  /api/v1/nodes                     nodes of the live game, or ?game=
///     GET  /api/v1/modes                     the modes this controller runs
///     GET  /api/v1/games                     every game
///     POST /api/v1/games                     GM: create a game from a mode
///     GET  /api/v1/games/{id}                one game
///     POST /api/v1/games/{id}/start|pause|resume|end   GM
///     GET  /api/v1/games/{id}/start-check    the roles the game needs, joined, missing
///     GET  /api/v1/games/{id}/score          current totals
///     POST /api/v1/games/{id}/score          GM adjustment, logged as score.delta
///     POST /api/v1/nodes/{id}/cmd            GM: a command to one node (65535: all)
///     GET  /api/v1/games/{id}/log            the merged event log (?since_ms=)
///     GET  /api/v1/controller                the controller's state
///     WS   /api/v1/stream                    live games, events, scores, nodes
///                                            (controller_stream.dart; the token
///                                            also as ?token=)
///     POST /api/v1/join                      GM: a join payload (slice S4)
///     POST /api/v1/nodes/{id}/join           GM: a join payload for that node id
///     GET|PUT /api/v1/settings/box-language  the boxes' screen language
///     WS   /api/v1/prop                      Android props on Wi-Fi
///                                            (controller_props.dart, slice S4)
///
/// Slice S7b (controller_api_s7b.dart): presets, mode uploads and signed
/// mode packages, the modes sent to boxes, scenarios and team branding.
///
/// Field check-in, player tokens, the chrono list and positions (slice S5;
/// controller_checkin.dart, controller_positions.dart):
///
///     GET  /api/v1/checkin                   field, notice, settings, open games (no token)
///     POST /api/v1/checkin                   check in with a field identity: a player token
///     POST /api/v1/checkin/token             a new player token (player token)
///     GET|DELETE /api/v1/checkin/me          the player's own check-in / leave the game
///     PUT  /api/v1/checkin/me/replicas       the player's declaration (replicas for this game)
///     PUT  /api/v1/checkin/me/marshal-key    a marshal registers the Ed25519 key that signs readings
///     GET|POST /api/v1/games/{id}/checkins   staff: the list with names / a manual check-in
///     GET  /api/v1/games/{id}/checkins.csv   GM: the list as CSV
///     PATCH|DELETE /api/v1/games/{id}/checkins/{player}  staff changes / GM removal
///     POST /api/v1/games/{id}/checkins/ticket  staff: a registered player's ticket, scanned
///     GET  /api/v1/games/{id}/chrono-list    staff: the "replicas to chrono" list
///     POST /api/v1/games/{id}/checkin/open|close  GM
///     POST /api/v1/chrono/readings           a marshal's signed series of readings
///     GET|POST /api/v1/marshals              GM: marshals' public keys
///     GET|PUT /api/v1/checkin/settings       GM: confirm, federation, limits
///     GET|PUT /api/v1/checkin/poster         GM: the check-in poster's text and fields
///     GET|DELETE /api/v1/players/{player}/chrono  the GM or the player: their readings
///     DELETE /api/v1/players/{player}        GM: erase a player (?chrono=1: readings too)
///     GET|POST /api/v1/positions             positions the caller may see / report (player token)
///
/// Player tokens read what the read token reads about games, and their own
/// check-in; their role, team and squad are checked against the check-in on
/// every request. They cannot read modes, the controller's state or the
/// start check. Players and the read token get games without their gm_only
/// parameters and events without their gm_only data (decision M5-1), staff
/// (the GM token, a marshal's or gm's token of the game) everything, as on
/// the Pi.
///
/// Slice S6 (controller_host.dart): the GM console and the scoreboard
/// (`/`, `/console/...`, `/scoreboard`; console_files.dart) and the field
/// CA (`GET /api/v1/controller/ca`, no token), as the Pi serves them.
///
/// [serve] listens on the loopback address unless told otherwise: a phone
/// controller is reachable from the field's network only when the shell
/// opens it there, over HTTPS ([serveRequest] on the shell's own servers;
/// PE24-7, PE24-62). The rest of the Pi's endpoints are later slices
/// (PLAN.md, "PE24 slices").
///
/// Slice S7c (controller_boxes_api.dart): the free boxes and invites over
/// the radio, adoption (field cards, pairing by code) and firmware updates,
/// with the Pi's paths, tokens and answers.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import '../modes/mode_catalog.dart';
import 'controller_branding.dart';
import 'controller_channel.dart';
import 'controller_checkin.dart';
import 'controller_engine.dart';
import 'controller_field.dart';
import 'controller_images.dart';
import 'controller_mode_fetch.dart';
import 'controller_modes.dart';
import 'controller_positions.dart';
import 'controller_props.dart';
import 'controller_scenarios.dart';
import 'controller_signed_modes.dart';
import 'controller_stream.dart';
import 'console_files.dart';
import 'controller_adoption.dart' show ControllerAdoption;
import 'controller_boxes.dart' show ControllerBoxes;
import 'controller_firmware.dart' show ControllerFirmware, reportMax, slotSize;
import 'controller_pairing.dart' show ControllerPairing;
import 'mode_package.dart';

part 'controller_api_s7b.dart';

part 'controller_boxes_api.dart';

part 'controller_field_api.dart';

/// The app's version (pubspec.yaml), which /healthz and /whoami give.
const controllerApiVersion = '0.2.0';

/// The GM console's areas this controller serves, in /whoami's `features`
/// (decision PE24-70): the console hides the tabs and panels of the rest.
/// The Pi's api.py `FEATURES` has every area; this one leaves out ATAK, the
/// schedule and failover (PLAN.md, "PE24 slices"). An area served later is
/// added here: slice S7a added the radio channel and the field plan
/// (controller_field_api.dart), slice S7b presets (and saved teams),
/// branding, scenarios and mode packages (controller_api_s7b.dart,
/// PE24-89), slice S7c boxes (free boxes, discover, invites), adoption and
/// firmware (controller_boxes_api.dart).
const controllerFeatures = [
  'checkin',
  'join',
  'box_language',
  'positions',
  'radio',
  'field',
  'boxes',
  'adoption',
  'firmware',
  'presets',
  'branding',
  'scenarios',
  'mode_packages',
];

/// An answer: its status code, JSON body and extra headers.
final class ApiResponse {
  const ApiResponse(this.status, this.body, [this.headers = const {}])
    : text = null,
      data = null,
      contentType = null;

  /// An answer that is not JSON: [text] as [contentType].
  const ApiResponse.text(
    this.status,
    String this.text,
    String this.contentType, [
    this.headers = const {},
  ]) : body = null,
       data = null;

  /// A file's bytes as [contentType] (the GM console's files, slice S6).
  const ApiResponse.bytes(
    this.status,
    Uint8List this.data,
    String this.contentType, [
    this.headers = const {},
  ]) : body = null,
       text = null;

  final int status;
  final Object? body;
  final String? text;
  final Uint8List? data;
  final String? contentType;
  final Map<String, String> headers;
}

class _HttpError implements Exception {
  _HttpError(this.status, this.detail, [this.headers = const {}]);
  final int status;
  final String detail;
  final Map<String, String> headers;
}

typedef _Handler = FutureOr<ApiResponse> Function(_Request r);

final class _Request {
  _Request(
    this.method,
    this.uri,
    this.match,
    this.token,
    this.bodyText,
    this.client, [
    Uint8List? bytes,
    this.contentType,
    this.headers = const {},
  ]) : bytes = bytes ?? Uint8List.fromList(utf8.encode(bodyText));

  final String method;
  final Uri uri;
  final RegExpMatch match;
  final String? token;
  final String bodyText;

  /// The caller's address (the check-in's rate limit).
  final String client;

  /// The body's bytes and its Content-Type (an uploaded image, slice S7a;
  /// a firmware image or a box's report, slice S7c; a mode package, a
  /// crest or a branding image, slice S7b).
  final Uint8List bytes;
  final String? contentType;

  /// The request's headers, names in lower case (slice S7c).
  final Map<String, String> headers;

  String pathText(int group) => Uri.decodeComponent(match.group(group)!);

  /// A query parameter as FastAPI reads a bool (false when absent).
  bool queryBool(String name) {
    final v = uri.queryParameters[name]?.toLowerCase();
    if (v == null) return false;
    if (const ['1', 'true', 'on', 'yes', 't', 'y'].contains(v)) return true;
    if (const ['0', 'false', 'off', 'no', 'f', 'n'].contains(v)) return false;
    throw _HttpError(422, '$name: a boolean');
  }

  int pathInt(int group) {
    final v = int.tryParse(match.group(group)!);
    if (v == null) throw _HttpError(422, 'the path needs an integer');
    return v;
  }

  int? queryInt(String name) {
    final v = uri.queryParameters[name];
    if (v == null) return null;
    final n = int.tryParse(v);
    if (n == null) throw _HttpError(422, '$name: an integer');
    return n;
  }

  /// The body as JSON (null when empty).
  Object? get json {
    if (bodyText.trim().isEmpty) return null;
    try {
      return jsonDecode(bodyText);
    } on FormatException {
      throw _HttpError(422, 'the request body is not JSON');
    }
  }

  /// The body as a JSON object ({} when empty).
  Map<String, Object?> get body {
    final v = json;
    if (v == null) return {};
    if (v is! Map<String, Object?>) {
      throw ControllerError('the request body must be a JSON object');
    }
    return v;
  }
}

class ControllerApi {
  ControllerApi(this.engine, {required this.gmToken, required this.readToken}) {
    if (gmToken.isEmpty || readToken.isEmpty) {
      throw ArgumentError('both tokens must be set');
    }
    _routes = [
      _route('GET', r'/healthz', _healthz),
      _route('GET', r'/api/v1/whoami', _viewer(_whoami)),
      _route('GET', r'/api/v1/nodes', _viewer(_nodes)),
      _route('GET', r'/api/v1/games', _viewer(_games)),
      _route('POST', r'/api/v1/games', _gm(_createGame)),
      _route('GET', r'/api/v1/games/([^/]+)', _viewer(_game)),
      _route('POST', r'/api/v1/games/([^/]+)/start', _gm(_start)),
      _route('POST', r'/api/v1/games/([^/]+)/pause', _gm(_pause)),
      _route('POST', r'/api/v1/games/([^/]+)/resume', _gm(_resume)),
      _route('POST', r'/api/v1/games/([^/]+)/end', _gm(_end)),
      _route('GET', r'/api/v1/games/([^/]+)/start-check', _read(_startCheck)),
      _route('GET', r'/api/v1/games/([^/]+)/score', _viewer(_score)),
      _route('POST', r'/api/v1/games/([^/]+)/score', _gm(_adjust)),
      _route('POST', r'/api/v1/nodes/([^/]+)/cmd', _gm(_nodeCmd)),
      _route('GET', r'/api/v1/games/([^/]+)/log', _viewer(_log)),
      _route('GET', r'/api/v1/controller', _read(_status)),
      // Slice S6: the field CA (no token), as the Pi's api.py `field_ca`.
      _route('GET', r'/api/v1/controller/ca', _fieldCa),
      // Slice S4: joins and the boxes' language.
      _route('POST', r'/api/v1/join', _gm(_join)),
      _route('POST', r'/api/v1/nodes/([^/]+)/join', _gm(_joinNode)),
      _route(
        'GET',
        r'/api/v1/settings/box-language',
        _read((r, who) => ApiResponse(200, engine.boxLanguage())),
      ),
      _route(
        'PUT',
        r'/api/v1/settings/box-language',
        _gm(
          (r) =>
              ApiResponse(200, engine.setBoxLanguage(r.body['box_language'])),
        ),
      ),
      ..._checkinRoutes(),
      ..._fieldRoutes(),
      ..._boxesRoutes(),
      ...s7bRoutes(),
    ];
    // Slice S7a: the field plan and the radio channel, on every controller
    // (the shell gives the field plan its folder first; else in memory).
    if (engine.field == null) ControllerField(engine);
    if (engine.channel == null) ControllerChannel(engine);
    hub = StreamHub(engine);
    engine.addListener(hub.publish);
    props = PropLinks(engine);
  }

  final ControllerEngine engine;

  /// The live feed of WS /api/v1/stream.
  late final StreamHub hub;

  /// Android props on Wi-Fi: WS /api/v1/prop (slice S4).
  late final PropLinks props;
  final String gmToken;
  final String readToken;
  late final List<(String, RegExp, _Handler)> _routes;

  /// The GM console and the scoreboard (console_files.dart; slice S6): the
  /// controller/console/src files the app carries. Empty: none served, as a
  /// Pi without the console's folder.
  ConsoleFiles console = ConsoleFiles(const {});

  /// The field CA's certificate (PEM) and SHA-256 when the phone serves
  /// HTTPS (field_tls.dart; slice S6); null: `GET /api/v1/controller/ca`
  /// is 404, as on a Pi with `tls_port = 0`.
  String? caPem;
  String? caSha256Hex;

  static (String, RegExp, _Handler) _route(
    String method,
    String path,
    _Handler h,
  ) => (method, RegExp('^$path\$'), h);

  // --- tokens ---------------------------------------------------------------

  /// Who [token] is: the GM or read token, or a valid player token (null:
  /// refused; api.py `Auth.viewer`).
  ApiViewer? viewerOf(String? token) {
    switch (role(token)) {
      case 'gm':
        return ApiViewer.gm;
      case 'read':
        return ApiViewer.read;
    }
    final svc = engine.checkin;
    if (token != null && token.startsWith('apt') && svc != null) {
      try {
        return svc.resolve(token);
      } on ControllerError {
        return null;
      }
    }
    return null;
  }

  /// "gm", "read" or null.
  String? role(String? token) {
    if (token == null || token.isEmpty) return null;
    if (_same(token, gmToken)) return 'gm';
    if (_same(token, readToken)) return 'read';
    return null;
  }

  static bool _same(String a, String b) {
    final x = sha256.convert(utf8.encode(a)).bytes;
    final y = sha256.convert(utf8.encode(b)).bytes;
    var diff = 0;
    for (var i = 0; i < x.length; i++) {
      diff |= x[i] ^ y[i];
    }
    return diff == 0;
  }

  /// The GM or read token (the console's views of the controller itself).
  _Handler _read(ApiResponse Function(_Request r, String role) h) => (r) {
    final who = role(r.token);
    if (who == null) {
      throw _HttpError(401, 'a GM or read token is needed', {
        'WWW-Authenticate': 'Bearer',
      });
    }
    return h(r, who);
  };

  /// The GM, read or a player token: the game's public data.
  _Handler _viewer(FutureOr<ApiResponse> Function(_Request r, ApiViewer v) h) =>
      (r) {
        final v = viewerOf(r.token);
        if (v == null) {
          throw _HttpError(401, 'a GM, read or player token is needed', {
            'WWW-Authenticate': 'Bearer',
          });
        }
        return h(r, v);
      };

  /// A player token only.
  _Handler _player(ApiResponse Function(_Request r, ApiViewer v) h) =>
      _viewer((r, v) {
        if (v.kind != 'player') {
          throw _HttpError(403, 'this needs a player token (check in first)');
        }
        return h(r, v);
      });

  _Handler _gm(ApiResponse Function(_Request r) h) => (r) {
    final who = role(r.token);
    if (who == null) {
      throw _HttpError(401, 'the GM token is needed', {
        'WWW-Authenticate': 'Bearer',
      });
    }
    if (who != 'gm') {
      throw _HttpError(
        403,
        'the read token cannot change the game; use the GM token',
      );
    }
    return h(r);
  };

  // --- dispatch -------------------------------------------------------------

  /// Answers one request: what [serve] does for each HTTP request, callable
  /// directly by tests. Every endpoint answers at once except POST
  /// /api/v1/chrono/readings, whose signatures are checked asynchronously:
  /// [handleAsync] answers that one too.
  ApiResponse handle(
    String method,
    Uri uri, {
    String? authorization,
    String body = '',
    String client = 'local',
    Uint8List? bytes,
    String? contentType,
    Map<String, String> headers = const {},
  }) {
    final out = _dispatch(
      method,
      uri,
      authorization,
      body,
      client,
      bytes,
      contentType,
      headers,
    );
    if (out is ApiResponse) return out;
    throw StateError('$method ${uri.path} answers asynchronously');
  }

  /// [handle] for every endpoint.
  Future<ApiResponse> handleAsync(
    String method,
    Uri uri, {
    String? authorization,
    String body = '',
    String client = 'local',
    Uint8List? bytes,
    String? contentType,
    Map<String, String> headers = const {},
  }) async => _dispatch(
    method,
    uri,
    authorization,
    body,
    client,
    bytes,
    contentType,
    headers,
  );

  FutureOr<ApiResponse> _dispatch(
    String method,
    Uri uri,
    String? authorization,
    String body,
    String client, [
    Uint8List? bytes,
    String? contentType,
    Map<String, String> headers = const {},
  ]) {
    if (method == 'GET' || method == 'HEAD') {
      final file = _consoleAnswer(uri.path);
      if (file != null) return file;
    }
    String? token;
    if (authorization != null &&
        authorization.toLowerCase().startsWith('bearer ')) {
      token = authorization.substring(7).trim();
    }
    var pathMatched = false;
    for (final (m, re, handler) in _routes) {
      final match = re.firstMatch(uri.path);
      if (match == null) continue;
      pathMatched = true;
      if (m != method) continue;
      final request = _Request(
        method,
        uri,
        match,
        token,
        body,
        client,
        bytes,
        contentType,
        headers,
      );
      try {
        final out = handler(request);
        if (out is ApiResponse) return out;
        return out.catchError(_errorAnswer);
      } on Object catch (e) {
        return _errorAnswer(e);
      }
    }
    return pathMatched
        ? const ApiResponse(405, {'detail': 'Method Not Allowed'})
        : const ApiResponse(404, {'detail': 'Not Found'});
  }

  /// The console's file or redirect for [path], with the Pi's security
  /// headers on /console answers; null when [path] is the API's.
  ApiResponse? _consoleAnswer(String path) {
    final a = console.answer(path);
    if (a == null) return null;
    final headers = {
      if (path.startsWith('/console')) ...consoleSecurityHeaders,
      if (a.location != null) 'Location': a.location!,
    };
    return switch (a.status) {
      200 => ApiResponse.bytes(200, a.bytes!, a.contentType!, headers),
      404 => ApiResponse(404, const {'detail': 'Not Found'}, headers),
      _ => ApiResponse(a.status, null, headers),
    };
  }

  static ApiResponse _errorAnswer(Object e) => switch (e) {
    _HttpError() => ApiResponse(e.status, {'detail': e.detail}, e.headers),
    ControllerError() => ApiResponse(e.status, {
      'detail': e.message,
      ...e.extra,
    }),
    // Slice S7b: a mode package or a scenario refused (api.py's handlers).
    ModeException() => ApiResponse(400, {'detail': e.message}),
    ScenarioRefused() => ApiResponse(400, e.toJson()),
    _ => throw e,
  };

  /// Serves the API on [address] (default: loopback only) and [port] (0: any
  /// free port). Every request runs on this isolate, the engine's.
  Future<HttpServer> serve({InternetAddress? address, int port = 0}) async {
    final server = await HttpServer.bind(
      address ?? InternetAddress.loopbackIPv4,
      port,
    );
    server.listen((req) => unawaited(serveRequest(req)));
    return server;
  }

  /// Answers one request of a server the caller bound (the phone's shell
  /// binds HTTP on the loopback address and HTTPS for the field's Wi-Fi,
  /// controller_host.dart).
  Future<void> serveRequest(HttpRequest req) async {
    if (req.uri.path == '/api/v1/stream' &&
        WebSocketTransformer.isUpgradeRequest(req)) {
      await _stream(req);
      return;
    }
    if (req.uri.path == '/api/v1/prop' &&
        WebSocketTransformer.isUpgradeRequest(req)) {
      try {
        await props.serve(await WebSocketTransformer.upgrade(req));
      } on WebSocketException {
        // The handshake failed: nothing to serve.
      }
      return;
    }
    final res = req.response;
    try {
      final chunks = BytesBuilder(copy: false);
      final limit = _bodyLimit(req.uri.path);
      await for (final c in req) {
        chunks.add(c);
        if (chunks.length > limit) {
          throw _HttpError(413, 'the request body is too large');
        }
      }
      final bytes = chunks.takeBytes();
      final headers = <String, String>{};
      req.headers.forEach((name, values) {
        if (values.isNotEmpty) headers[name.toLowerCase()] = values.first;
      });
      final answer = await handleAsync(
        req.method,
        req.uri,
        authorization: req.headers.value(HttpHeaders.authorizationHeader),
        body: utf8.decode(bytes, allowMalformed: true),
        client: req.connectionInfo?.remoteAddress.address ?? '?',
        bytes: bytes,
        contentType: req.headers.value(HttpHeaders.contentTypeHeader),
        headers: headers,
      );
      _write(res, answer, head: req.method == 'HEAD');
    } on _HttpError catch (e) {
      _write(res, ApiResponse(e.status, {'detail': e.detail}));
    } on Object catch (e) {
      _write(res, ApiResponse(500, {'detail': 'internal error: $e'}));
    }
    await res.close();
  }

  /// WS /api/v1/stream: a token in ?token= (browsers cannot set headers on a
  /// WebSocket) or Authorization; an unknown token is closed with 4401.
  Future<void> _stream(HttpRequest req) async {
    var token = req.uri.queryParameters['token'];
    final header = req.headers.value(HttpHeaders.authorizationHeader) ?? '';
    if ((token == null || token.isEmpty) &&
        header.toLowerCase().startsWith('bearer ')) {
      token = header.substring(7).trim();
    }
    final WebSocket socket;
    try {
      socket = await WebSocketTransformer.upgrade(req);
    } on WebSocketException {
      return;
    }
    final who = viewerOf(token);
    if (who == null) {
      await socket.close(4401);
      return;
    }
    hub.connect(socket, who);
  }

  static void _write(HttpResponse res, ApiResponse a, {bool head = false}) {
    res.statusCode = a.status;
    res.headers.set('Cache-Control', 'no-store');
    final data = a.data;
    if (data != null) {
      res.headers.contentType = ContentType.parse(a.contentType!);
      a.headers.forEach(res.headers.set);
      res.contentLength = data.length;
      if (!head) res.add(data);
      return;
    }
    if (a.status >= 300 && a.status < 400 && a.body == null) {
      a.headers.forEach(res.headers.set);
      return;
    }
    final text = a.text;
    if (text != null) {
      res.headers.contentType = ContentType.parse(a.contentType!);
      a.headers.forEach(res.headers.set);
      res.add(utf8.encode(text));
      return;
    }
    res.headers.contentType = ContentType.json;
    a.headers.forEach(res.headers.set);
    res.write(jsonEncode(a.body));
  }

  // --- endpoints ------------------------------------------------------------

  ApiResponse _fieldCa(_Request r) {
    final pem = caPem;
    if (pem == null) {
      throw _HttpError(404, 'HTTPS is off on this phone controller');
    }
    return ApiResponse.text(200, pem, 'application/x-pem-file', {
      'X-Atalaia-CA-SHA256': caSha256Hex ?? '',
      'Cache-Control': 'no-cache',
    });
  }

  ApiResponse _healthz(_Request r) => ApiResponse(200, {
    'ok': true,
    'version': controllerApiVersion,
    'radio': engine.radioState,
  });

  ApiResponse _whoami(_Request r, ApiViewer v) => ApiResponse(200, {
    'role': v.kind,
    'version': controllerApiVersion,
    'features': controllerFeatures,
    if (v.kind == 'player') ...{
      'player_role': v.role,
      'player_id': v.playerId,
      'game_id': v.gameId,
      'team': v.team,
      'squad': v.squad,
      'stale': v.stale,
    },
  });

  ApiResponse _nodes(_Request r, ApiViewer v) =>
      ApiResponse(200, engine.nodes(r.queryInt('game')));

  Map<String, Object?> _view(Map<String, Object?> game, ApiViewer v) =>
      v.isStaffOf(game['id'] as int?) ? game : engine.playersGame(game, v);

  ApiResponse _games(_Request r, ApiViewer v) =>
      ApiResponse(200, [for (final g in engine.listGames()) _view(g, v)]);

  ApiResponse _createGame(_Request r) =>
      ApiResponse(201, engine.createGame(r.body));

  ApiResponse _game(_Request r, ApiViewer v) =>
      ApiResponse(200, _view(engine.getGame(r.pathInt(1)), v));

  static String _reason(Map<String, Object?> body) {
    final reason = body['reason'] ?? '';
    if (reason is! String || reason.length > 64) {
      throw ControllerError('reason: text up to 64 characters');
    }
    return reason;
  }

  ApiResponse _start(_Request r) {
    final id = r.pathInt(1);
    final force = r.body['force'] ?? false;
    if (force is! bool) throw ControllerError('force: true or false');
    final out = engine.startGame(id, force: force);
    final svc = engine.checkin;
    // ADR-P3-13: a warning, not a block; the console asks before it starts.
    if (svc != null) out['pending_declarations'] = svc.pendingCount(id);
    return ApiResponse(200, out);
  }

  ApiResponse _pause(_Request r) {
    final id = r.pathInt(1);
    return ApiResponse(200, engine.pauseGame(id, _reason(r.body)));
  }

  ApiResponse _resume(_Request r) =>
      ApiResponse(200, engine.resumeGame(r.pathInt(1)));

  ApiResponse _end(_Request r) {
    final id = r.pathInt(1);
    return ApiResponse(200, engine.endGame(id, _reason(r.body)));
  }

  ApiResponse _startCheck(_Request r, String who) {
    final id = r.pathInt(1);
    final live = engine.liveGame;
    if (live == null || live['id'] != id) {
      throw ControllerError('game $id is not the live game');
    }
    return ApiResponse(200, engine.startCheck());
  }

  ApiResponse _score(_Request r, ApiViewer v) =>
      ApiResponse(200, engine.score(r.pathInt(1)));

  ApiResponse _adjust(_Request r) {
    final id = r.pathInt(1);
    final b = r.body;
    return ApiResponse(
      200,
      engine.adjustScore(id, b['team'], b['amount'], b['reason'] ?? ''),
    );
  }

  ApiResponse _nodeCmd(_Request r) {
    final id = r.pathInt(1);
    final b = r.body;
    return ApiResponse(202, engine.sendNodeCmd(id, b['cmd'], b['params']));
  }

  ApiResponse _log(_Request r, ApiViewer v) {
    final id = r.pathInt(1);
    final out = engine.log(id, sinceMs: r.queryInt('since_ms'));
    return ApiResponse(
      200,
      v.isStaffOf(id) ? out : [for (final e in out) engine.eventFor(v, id, e)],
    );
  }

  ApiResponse _status(_Request r, String who) =>
      ApiResponse(200, engine.status());

  // A join holds the game key; every answer is sent with no-store (_write).
  ApiResponse _join(_Request r) => ApiResponse(200, engine.issueJoin(r.body));

  ApiResponse _joinNode(_Request r) =>
      ApiResponse(200, engine.issueJoin(r.body, nodeIdValue: r.pathInt(1)));

  // --- field check-in, the chrono list and positions (slice S5) -------------

  ControllerCheckin _svc() {
    final svc = engine.checkin;
    if (svc == null) {
      throw ControllerError.unavailable(
        'field check-in is not set up on this controller',
      );
    }
    return svc;
  }

  ControllerPositions _positions() {
    final pos = engine.positions;
    if (pos == null) {
      throw ControllerError.unavailable(
        'positions are not set up on this controller',
      );
    }
    return pos;
  }

  static const _noStore = {'Cache-Control': 'no-store'};

  List<(String, RegExp, _Handler)> _checkinRoutes() => [
    _route('GET', r'/api/v1/checkin', (r) {
      final svc = _svc();
      if (!svc.infoRate.allow(r.client)) {
        throw _HttpError(
          429,
          'too many requests from this address; wait a minute',
        );
      }
      return ApiResponse(200, svc.info(), _noStore);
    }),
    _route('POST', r'/api/v1/checkin', (r) {
      final (out, created) = _svc().checkIn(r.body, r.client);
      return ApiResponse(created ? 201 : 200, out, _noStore);
    }),
    _route(
      'POST',
      r'/api/v1/checkin/token',
      _player((r, v) => ApiResponse(200, _svc().refreshToken(v), _noStore)),
    ),
    _route(
      'GET',
      r'/api/v1/checkin/me',
      _player((r, v) => ApiResponse(200, _svc().me(v)!, _noStore)),
    ),
    _route(
      'DELETE',
      r'/api/v1/checkin/me',
      _player((r, v) => ApiResponse(200, _svc().leave(v))),
    ),
    _route(
      'PUT',
      r'/api/v1/checkin/me/replicas',
      _player((r, v) => ApiResponse(200, _svc().putMyReplicas(v, r.body))),
    ),
    _route(
      'PUT',
      r'/api/v1/checkin/me/marshal-key',
      _player((r, v) {
        if (v.role != 'marshal') {
          throw _HttpError(
            403,
            'only a marshal registers a signing key (the GM gives the role)',
          );
        }
        return ApiResponse(
          200,
          _svc().registerMarshal(r.body, playerId: v.playerId),
        );
      }),
    ),
    _route(
      'GET',
      r'/api/v1/games/([^/]+)/checkins',
      _viewer(
        (r, v) =>
            ApiResponse(200, _svc().listCheckins(v, r.pathInt(1)), _noStore),
      ),
    ),
    _route(
      'GET',
      r'/api/v1/games/([^/]+)/checkins\.csv',
      _gm((r) {
        final id = r.pathInt(1);
        final text = _svc().csvExport(id);
        return ApiResponse.text(200, '﻿$text', 'text/csv; charset=utf-8', {
          'Content-Disposition': 'attachment; filename="checkins-$id.csv"',
        });
      }),
    ),
    _route(
      'POST',
      r'/api/v1/games/([^/]+)/checkins',
      _viewer(
        (r, v) =>
            ApiResponse(201, _svc().manualCheckin(v, r.pathInt(1), r.body)),
      ),
    ),
    _route(
      'POST',
      r'/api/v1/games/([^/]+)/checkins/ticket',
      _viewer(
        (r, v) =>
            ApiResponse(200, _svc().ticketCheckin(v, r.pathInt(1), r.body)),
      ),
    ),
    _route(
      'PATCH',
      r'/api/v1/games/([^/]+)/checkins/([^/]+)',
      _viewer(
        (r, v) => ApiResponse(
          200,
          _svc().patchCheckin(v, r.pathInt(1), r.pathText(2), r.body),
        ),
      ),
    ),
    _route(
      'DELETE',
      r'/api/v1/games/([^/]+)/checkins/([^/]+)',
      _viewer(
        (r, v) => ApiResponse(
          200,
          _svc().removeCheckin(v, r.pathInt(1), r.pathText(2)),
        ),
      ),
    ),
    _route(
      'GET',
      r'/api/v1/games/([^/]+)/chrono-list',
      _viewer(
        (r, v) =>
            ApiResponse(200, _svc().chronoList(v, r.pathInt(1)), _noStore),
      ),
    ),
    _route(
      'POST',
      r'/api/v1/games/([^/]+)/checkin/open',
      _gm((r) => ApiResponse(200, _svc().setOpen(r.pathInt(1), true))),
    ),
    _route(
      'POST',
      r'/api/v1/games/([^/]+)/checkin/close',
      _gm((r) => ApiResponse(200, _svc().setOpen(r.pathInt(1), false))),
    ),
    _route(
      'POST',
      r'/api/v1/chrono/readings',
      _viewer((r, v) async {
        final svc = _svc();
        final body = r.body;
        return ApiResponse(200, await svc.uploadReadings(v, body));
      }),
    ),
    _route(
      'GET',
      r'/api/v1/marshals',
      _gm((r) => ApiResponse(200, _svc().marshals())),
    ),
    _route(
      'POST',
      r'/api/v1/marshals',
      _gm((r) => ApiResponse(201, _svc().registerMarshal(r.body))),
    ),
    _route(
      'GET',
      r'/api/v1/checkin/settings',
      _gm((r) => ApiResponse(200, _svc().settings())),
    ),
    _route(
      'PUT',
      r'/api/v1/checkin/settings',
      _gm((r) => ApiResponse(200, _svc().setSettings(r.body))),
    ),
    _route(
      'GET',
      r'/api/v1/checkin/poster',
      _gm((r) => ApiResponse(200, _svc().poster())),
    ),
    _route(
      'PUT',
      r'/api/v1/checkin/poster',
      _gm((r) => ApiResponse(200, _svc().setPoster(r.body))),
    ),
    _route(
      'GET',
      r'/api/v1/players/([^/]+)/chrono',
      _viewer((r, v) {
        final pid = r.pathText(1);
        _ownOrGm(v, pid);
        return ApiResponse(200, {
          'player_id': pid,
          'readings': _svc().playerReadings(pid),
        }, _noStore);
      }),
    ),
    _route(
      'DELETE',
      r'/api/v1/players/([^/]+)/chrono',
      _viewer((r, v) {
        final pid = r.pathText(1);
        _ownOrGm(v, pid);
        return ApiResponse(200, {
          'player_id': pid,
          'readings_deleted': _svc().deletePlayerReadings(pid),
        });
      }),
    ),
    _route(
      'DELETE',
      r'/api/v1/players/([^/]+)',
      _gm((r) {
        final chrono = r.queryBool('chrono');
        return ApiResponse(
          200,
          _svc().erasePlayer(r.pathText(1), chronoToo: chrono),
        );
      }),
    ),
    _route(
      'POST',
      r'/api/v1/positions',
      _player((r, v) => ApiResponse(200, _positions().report(v, r.json))),
    ),
    _route(
      'GET',
      r'/api/v1/positions',
      _viewer(
        (r, v) =>
            ApiResponse(200, {'positions': _positions().visible(v)}, _noStore),
      ),
    ),
  ];

  static void _ownOrGm(ApiViewer v, String pid) {
    if (!(v.isGmToken || (v.kind == 'player' && v.playerId == pid))) {
      throw _HttpError(403, "the GM token, or the player's own token");
    }
  }
}
