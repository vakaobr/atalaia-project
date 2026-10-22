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
///     GET  /api/v1/whoami                    which token this is: gm or read
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
///
/// The read token gets games without their gm_only parameters and events
/// without their gm_only data (decision M5-1), as on the Pi.
///
/// [serve] listens on the loopback address unless told otherwise: a phone
/// controller is reachable from the field's network only when the shell
/// opens it there (PE24-7). The stream, check-in, player tokens, joins and
/// the rest of the Pi's endpoints are later slices (PLAN.md, "PE24 slices").
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';

import '../modes/builtin_modes.g.dart';
import 'controller_engine.dart';

/// The app's version (pubspec.yaml), which /healthz and /whoami give.
const controllerApiVersion = '0.2.0';

/// An answer: its status code, JSON body and extra headers.
final class ApiResponse {
  const ApiResponse(this.status, this.body, [this.headers = const {}]);

  final int status;
  final Object? body;
  final Map<String, String> headers;
}

class _HttpError implements Exception {
  _HttpError(this.status, this.detail, [this.headers = const {}]);
  final int status;
  final String detail;
  final Map<String, String> headers;
}

typedef _Handler = ApiResponse Function(_Request r);

final class _Request {
  _Request(this.method, this.uri, this.match, this.token, this.bodyText);

  final String method;
  final Uri uri;
  final RegExpMatch match;
  final String? token;
  final String bodyText;

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

  /// The body as a JSON object ({} when empty).
  Map<String, Object?> get body {
    if (bodyText.trim().isEmpty) return {};
    final Object? v;
    try {
      v = jsonDecode(bodyText);
    } on FormatException {
      throw _HttpError(422, 'the request body is not JSON');
    }
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
      _route('GET', r'/api/v1/whoami', _read(_whoami)),
      _route('GET', r'/api/v1/nodes', _read(_nodes)),
      _route('GET', r'/api/v1/modes', _read(_modes)),
      _route('GET', r'/api/v1/games', _read(_games)),
      _route('POST', r'/api/v1/games', _gm(_createGame)),
      _route('GET', r'/api/v1/games/([^/]+)', _read(_game)),
      _route('POST', r'/api/v1/games/([^/]+)/start', _gm(_start)),
      _route('POST', r'/api/v1/games/([^/]+)/pause', _gm(_pause)),
      _route('POST', r'/api/v1/games/([^/]+)/resume', _gm(_resume)),
      _route('POST', r'/api/v1/games/([^/]+)/end', _gm(_end)),
      _route('GET', r'/api/v1/games/([^/]+)/start-check', _read(_startCheck)),
      _route('GET', r'/api/v1/games/([^/]+)/score', _read(_score)),
      _route('POST', r'/api/v1/games/([^/]+)/score', _gm(_adjust)),
      _route('POST', r'/api/v1/nodes/([^/]+)/cmd', _gm(_nodeCmd)),
      _route('GET', r'/api/v1/games/([^/]+)/log', _read(_log)),
      _route('GET', r'/api/v1/controller', _read(_status)),
    ];
  }

  final ControllerEngine engine;
  final String gmToken;
  final String readToken;
  late final List<(String, RegExp, _Handler)> _routes;

  static (String, RegExp, _Handler) _route(
    String method,
    String path,
    _Handler h,
  ) => (method, RegExp('^$path\$'), h);

  // --- tokens ---------------------------------------------------------------

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

  _Handler _read(ApiResponse Function(_Request r, String role) h) => (r) {
    final who = role(r.token);
    if (who == null) {
      throw _HttpError(401, 'a GM or read token is needed', {
        'WWW-Authenticate': 'Bearer',
      });
    }
    return h(r, who);
  };

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
  /// directly by tests.
  ApiResponse handle(
    String method,
    Uri uri, {
    String? authorization,
    String body = '',
  }) {
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
      try {
        return handler(_Request(method, uri, match, token, body));
      } on _HttpError catch (e) {
        return ApiResponse(e.status, {'detail': e.detail}, e.headers);
      } on ControllerError catch (e) {
        return ApiResponse(e.status, {'detail': e.message, ...e.extra});
      }
    }
    return pathMatched
        ? const ApiResponse(405, {'detail': 'Method Not Allowed'})
        : const ApiResponse(404, {'detail': 'Not Found'});
  }

  /// Serves the API on [address] (default: loopback only) and [port] (0: any
  /// free port). Every request runs on this isolate, the engine's.
  Future<HttpServer> serve({InternetAddress? address, int port = 0}) async {
    final server = await HttpServer.bind(
      address ?? InternetAddress.loopbackIPv4,
      port,
    );
    server.listen((req) => unawaited(_serveOne(req)));
    return server;
  }

  Future<void> _serveOne(HttpRequest req) async {
    final res = req.response;
    try {
      final chunks = <int>[];
      await for (final c in req) {
        chunks.addAll(c);
        if (chunks.length > 1 << 20) {
          throw _HttpError(413, 'the request body is too large');
        }
      }
      final answer = handle(
        req.method,
        req.uri,
        authorization: req.headers.value(HttpHeaders.authorizationHeader),
        body: utf8.decode(chunks, allowMalformed: true),
      );
      _write(res, answer);
    } on _HttpError catch (e) {
      _write(res, ApiResponse(e.status, {'detail': e.detail}));
    } on Object catch (e) {
      _write(res, ApiResponse(500, {'detail': 'internal error: $e'}));
    }
    await res.close();
  }

  static void _write(HttpResponse res, ApiResponse a) {
    res.statusCode = a.status;
    res.headers.contentType = ContentType.json;
    res.headers.set('Cache-Control', 'no-store');
    a.headers.forEach(res.headers.set);
    res.write(jsonEncode(a.body));
  }

  // --- endpoints ------------------------------------------------------------

  ApiResponse _healthz(_Request r) => ApiResponse(200, {
    'ok': true,
    'version': controllerApiVersion,
    'radio': engine.radioState,
  });

  ApiResponse _whoami(_Request r, String who) =>
      ApiResponse(200, {'role': who, 'version': controllerApiVersion});

  ApiResponse _nodes(_Request r, String who) =>
      ApiResponse(200, engine.nodes(r.queryInt('game')));

  ApiResponse _modes(_Request r, String who) => ApiResponse(200, [
    for (final m in engine.modes.modes)
      {
        'id': m.id,
        'kind': m.kind,
        'name': m.name('en'),
        'version': m.version,
        'description': m.description('en'),
        'min_tier': m.manifest['min_tier'],
        'roles': m.manifest['roles'] ?? const {},
        'params': m.manifest['params'] ?? const {},
        'commands': m.manifest['commands'] ?? const {},
        'i18n': m.manifest['i18n'] ?? const {},
        'parts': [m.id],
        'field_script': m.fieldScript != null,
        'builtin': true,
        'files': (builtinModeFiles[m.folder]?.keys.toList() ?? <String>[])
          ..sort(),
      },
  ]);

  Map<String, Object?> _view(Map<String, Object?> game, String who) =>
      who == 'gm' ? game : engine.playersGame(game);

  ApiResponse _games(_Request r, String who) =>
      ApiResponse(200, [for (final g in engine.listGames()) _view(g, who)]);

  ApiResponse _createGame(_Request r) =>
      ApiResponse(201, engine.createGame(r.body));

  ApiResponse _game(_Request r, String who) =>
      ApiResponse(200, _view(engine.getGame(r.pathInt(1)), who));

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
    return ApiResponse(200, engine.startGame(id, force: force));
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

  ApiResponse _score(_Request r, String who) =>
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

  ApiResponse _log(_Request r, String who) {
    final id = r.pathInt(1);
    final out = engine.log(id, sinceMs: r.queryInt('since_ms'));
    return ApiResponse(
      200,
      who == 'gm' ? out : [for (final e in out) publicEvent(e)],
    );
  }

  ApiResponse _status(_Request r, String who) =>
      ApiResponse(200, engine.status());
}
