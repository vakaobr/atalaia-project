// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A player's account on a field's site server (ADR-P4-2, plan phase 11's
/// auth API; plan phase 16's registration API, decision S16-13).
///
/// **Logging in.** `POST /api/v1/auth/login` with the username and
/// password answers with a session, or with `totp_required` and a short
/// `totp_session` for an account with TOTP: then `POST
/// /api/v1/auth/login/totp` with the six-digit code.
///
/// **Tokens.** A session is a short access token (Bearer) and a refresh
/// token that the site server sets as the `__Secure-atalaia_refresh`
/// cookie. The access token stays in memory only; the refresh token is kept
/// in the app's private storage with the other secrets (decision PD6:
/// Android's app sandbox, backups off), never logged and never shown. Each
/// refresh (`POST /api/v1/auth/refresh`, the cookie and `X-Atalaia-Refresh:
/// 1`) spends the old token and sets a new one; the server ends the session
/// when a spent token comes back (a copy used elsewhere). So refreshes run
/// one at a time ([SiteSession.refresh] shares one in flight), and the new
/// token is saved before the new access token is used. A refused refresh
/// forgets the stored token: the person logs in again.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../storage/app_store.dart';

const refreshCookie = '__Secure-atalaia_refresh';

/// One answer from a site server: status, JSON body, and the refresh
/// cookie it set (if any).
final class SiteResponse {
  const SiteResponse(this.status, this.body, {this.refreshToken});
  final int status;
  final Object? body;
  final String? refreshToken;

  bool get ok => status >= 200 && status < 300;

  Map<String, Object?> get json =>
      body is Map ? (body! as Map).cast<String, Object?>() : const {};

  /// The server's error code (FastAPI's `detail`), e.g. `game_full`.
  String get detail {
    final d = json['detail'];
    return d is String ? d : 'http_$status';
  }

  /// Whether this is a 422 that refuses [field] of the request body as one it
  /// does not know (FastAPI's `extra_forbidden` for `['body', field]`): what a
  /// server older than the field answers. Any other 422 is not this.
  bool refusesUnknownField(String field) {
    if (status != 422) return false;
    final d = json['detail'];
    if (d is! List) return false;
    return d.any((e) {
      if (e is! Map || e['type'] != 'extra_forbidden') return false;
      final loc = e['loc'];
      return loc is List &&
          loc.length == 2 &&
          loc[0] == 'body' &&
          loc[1] == field;
    });
  }
}

/// The HTTP side, replaced in tests by a fake site server.
abstract interface class SiteHttp {
  Future<SiteResponse> send(
    String method,
    String path, {
    Object? body,
    String? bearer,
    String? refreshToken,
  });
}

/// [SiteHttp] over dart:io, to one site's origin, with the system's
/// certificate authorities (a site server has a public certificate).
class IoSiteHttp implements SiteHttp {
  IoSiteHttp(this.origin, [HttpClient? client])
    : _client =
          client ??
          (HttpClient()..connectionTimeout = const Duration(seconds: 10));

  final Uri origin;
  final HttpClient _client;

  @override
  Future<SiteResponse> send(
    String method,
    String path, {
    Object? body,
    String? bearer,
    String? refreshToken,
  }) async {
    try {
      // A path may carry a query (`/privacy-notice?lang=en`).
      final cut = path.indexOf('?');
      final req = await _client.openUrl(
        method,
        origin.replace(
          path: '/api/v1${cut < 0 ? path : path.substring(0, cut)}',
          query: cut < 0 ? null : path.substring(cut + 1),
        ),
      );
      req.followRedirects = false;
      req.headers.set('Accept', 'application/json');
      if (bearer != null) req.headers.set('Authorization', 'Bearer $bearer');
      if (refreshToken != null) {
        req.cookies.add(Cookie(refreshCookie, refreshToken));
        req.headers.set('X-Atalaia-Refresh', '1');
      }
      if (body != null) {
        req.headers.contentType = ContentType.json;
        req.add(utf8.encode(jsonEncode(body)));
      }
      final res = await req.close().timeout(const Duration(seconds: 20));
      final text = await utf8.decodeStream(res);
      String? fresh;
      for (final c in res.cookies) {
        if (c.name == refreshCookie && c.value.isNotEmpty) fresh = c.value;
      }
      Object? json;
      try {
        json = text.isEmpty ? null : jsonDecode(text);
      } on FormatException {
        json = null;
      }
      return SiteResponse(res.statusCode, json, refreshToken: fresh);
    } on Object catch (e) {
      throw SiteException(0, 'offline', '$e');
    }
  }

  void close() => _client.close(force: true);
}

class SiteException implements Exception {
  SiteException(this.status, this.code, [this.message = '']);

  /// The HTTP status, or 0 when the site did not answer.
  final int status;

  /// The server's error code, `offline`, or `login_required` (no session).
  final String code;
  final String message;

  bool get offline => status == 0;
  bool get loginRequired => code == 'login_required';

  @override
  String toString() => 'SiteException($status, $code)';
}

/// The accounts the app is logged in with, one per site origin: the
/// username and the refresh token, in the app's private storage.
class SiteAccounts {
  SiteAccounts(this.store);
  final AppStore store;
  static const _list = 'site_accounts';

  Future<Map<String, Object?>?> _find(String site) async {
    for (final j in await store.loadList(_list)) {
      if (j['site'] == site) return j;
    }
    return null;
  }

  Future<String?> refreshToken(String site) async {
    final t = (await _find(site))?['refresh'];
    return t is String && t.isNotEmpty ? t : null;
  }

  Future<String?> username(String site) async {
    final u = (await _find(site))?['username'];
    return u is String ? u : null;
  }

  /// Whether the person said this site is theirs to log in to (a link from
  /// a web page can name any site, so the first login asks).
  Future<bool> confirmed(String site) async =>
      (await _find(site))?['confirmed'] == true;

  Future<void> confirm(String site) => _put(site, (j) => j['confirmed'] = true);

  Future<void> save(String site, String username, String refresh) =>
      _put(site, (j) {
        j['username'] = username;
        j['refresh'] = refresh;
        j['confirmed'] = true;
      });

  Future<void> setRefresh(String site, String refresh) =>
      _put(site, (j) => j['refresh'] = refresh);

  /// Logged out (or the session ended): the token goes, the site and the
  /// username stay to log in again.
  Future<void> forgetToken(String site) =>
      _put(site, (j) => j.remove('refresh'));

  Future<void> _put(String site, void Function(Map<String, Object?>) f) async {
    final all = await store.loadList(_list);
    final j = <String, Object?>{
      ...?all.where((x) => x['site'] == site).firstOrNull,
      'site': site,
    };
    f(j);
    await store.saveList(_list, [
      for (final x in all)
        if (x['site'] != site) x,
      j,
    ]);
  }
}

/// The result of the password step.
sealed class LoginStep {
  const LoginStep();
}

final class LoggedIn extends LoginStep {
  const LoggedIn(this.username);
  final String username;
}

final class TotpNeeded extends LoginStep {
  const TotpNeeded(this.totpSession, this.username);
  final String totpSession;
  final String username;
}

/// A session on one site server.
class SiteSession {
  SiteSession(this.site, this.http, this.accounts, {DateTime Function()? now})
    : _now = now ?? DateTime.now;

  final Uri site;
  final SiteHttp http;
  final SiteAccounts accounts;
  final DateTime Function() _now;

  String get _key => site.toString();
  String? _access;
  DateTime? _expires;
  Future<void>? _refreshing;
  String? username;

  /// Whether a stored refresh token may still give a session.
  Future<bool> get hasAccount async =>
      await accounts.refreshToken(_key) != null;

  Future<LoginStep> login(String user, String password) async {
    final r = await http.send(
      'POST',
      '/auth/login',
      body: {'username': user, 'password': password},
    );
    if (!r.ok) throw SiteException(r.status, r.detail);
    if (r.json['totp_required'] == true) {
      return TotpNeeded('${r.json['totp_session']}', user);
    }
    return LoggedIn(await _start(r, user));
  }

  Future<String> loginTotp(TotpNeeded step, String code) async {
    final r = await http.send(
      'POST',
      '/auth/login/totp',
      body: {'totp_session': step.totpSession, 'code': code.trim()},
    );
    if (!r.ok) throw SiteException(r.status, r.detail);
    return _start(r, step.username);
  }

  Future<String> _start(SiteResponse r, String user) async {
    final token = r.refreshToken;
    final access = r.json['access_token'];
    if (token == null || access is! String) {
      throw SiteException(r.status, 'bad_answer');
    }
    final name = (r.json['user'] as Map?)?['username'];
    username = name is String ? name : user;
    await accounts.save(_key, username!, token); // before it is used
    _setAccess(access, r.json['expires_in']);
    return username!;
  }

  void _setAccess(String token, Object? expiresIn) {
    _access = token;
    final s = expiresIn is int ? expiresIn : 300;
    // A little early, so a request does not reach the server just expired.
    _expires = _now().add(Duration(seconds: s > 60 ? s - 30 : s));
  }

  /// A session that another way of logging in gave (a social login's ticket
  /// or a passkey, lib/site/site_auth.dart): the same answer as a password
  /// login's. Returns the user name.
  Future<String> adopt(SiteResponse r) => _start(r, username ?? '');

  /// A new access token from the stored refresh token; one at a time.
  Future<void> refresh() =>
      _refreshing ??= _refresh().whenComplete(() => _refreshing = null);

  Future<void> _refresh() async {
    final token = await accounts.refreshToken(_key);
    if (token == null) throw SiteException(401, 'login_required');
    final r = await http.send('POST', '/auth/refresh', refreshToken: token);
    if (r.status == 401 || r.status == 403) {
      // Spent, replayed, expired or revoked: this session is over.
      _access = null;
      await accounts.forgetToken(_key);
      throw SiteException(401, 'login_required');
    }
    if (!r.ok) throw SiteException(r.status, r.detail);
    final fresh = r.refreshToken;
    final access = r.json['access_token'];
    if (fresh == null || access is! String) {
      throw SiteException(r.status, 'bad_answer');
    }
    await accounts.setRefresh(_key, fresh); // saved before it is used
    final name = (r.json['user'] as Map?)?['username'];
    if (name is String) username = name;
    _setAccess(access, r.json['expires_in']);
  }

  /// A request with the access token, refreshed first when it has expired
  /// and once more when the server says it is not valid.
  Future<Map<String, Object?>> call(
    String method,
    String path, {
    Object? body,
  }) async {
    final r = await callRaw(method, path, body: body);
    if (!r.ok) throw SiteException(r.status, r.detail);
    return r.json;
  }

  Future<SiteResponse> callRaw(
    String method,
    String path, {
    Object? body,
  }) async {
    if (_access == null || !_now().isBefore(_expires!)) await refresh();
    var r = await http.send(method, path, body: body, bearer: _access);
    if (r.status == 401) {
      await refresh();
      r = await http.send(method, path, body: body, bearer: _access);
    }
    return r;
  }

  Future<void> logout() async {
    final access = _access;
    _access = null;
    if (access != null) {
      try {
        await http.send('POST', '/auth/logout', bearer: access);
      } on SiteException {
        // offline: the token is forgotten here all the same
      }
    }
    await accounts.forgetToken(_key);
  }
}

/// One [SiteSession] per site for the app's lifetime (the access token
/// lives as long as the app does).
class SiteSessions {
  SiteSessions(AppStore store, this.httpFor) : accounts = SiteAccounts(store);

  final SiteHttp Function(Uri origin) httpFor;
  final SiteAccounts accounts;
  final _sessions = <String, SiteSession>{};

  SiteSession of(Uri origin) => _sessions.putIfAbsent(
    '$origin',
    () => SiteSession(origin, httpFor(origin), accounts),
  );
}
