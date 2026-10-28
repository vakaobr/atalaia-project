// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Logging in to a site server without a password, and the account's login
/// methods (decision PKA-1; the site server's LG-* and ACC-* decisions).
///
/// **Social login** (Google, Microsoft, Apple through OpenID Connect) is a
/// redirect dance, so it runs in the system browser (a Custom Tab, the
/// provider never sees the app). The app asks the site `POST
/// /api/v1/auth/oidc/{provider}/start` with a `return_to` that is the site's
/// own `https://<host>/app/oidc?s=<nonce>` (an Android App Link the site's
/// `/.well-known/assetlinks.json` ties to this app) and opens the
/// `browser_url` it answers with: the site sets its binding cookie in that
/// browser and sends it on to the provider. The redirect back opens the app
/// with `#oidc=<ticket>` (a one-minute, single-use ticket, never sent to a
/// server), which `POST /auth/oidc/complete` turns into a session. The
/// nonce `s` is the app's own: a return that does not carry the nonce of
/// the attempt the app is waiting for is ignored, so a link someone else
/// made cannot give this phone their session.
///
/// **Passkeys** go through Android's Credential Manager
/// ([PasskeyService]) against `/auth/passkey/*` and `/me/passkeys*`; the
/// site's relying party is its host name.
///
/// **The account** ([SiteAuth]): `GET /me/login-methods` and what the server
/// offers (`GET /auth/methods`), linking and unlinking a provider, passkeys,
/// the password, TOTP, and the confirmation a sensitive change asks for. The
/// app holds no rule: it shows what the server says and puts every refusal
/// in words (lib/site/account_screen.dart).
library;

import 'dart:async';
import 'dart:convert';
import 'dart:math';

import '../platform/services.dart';
import 'site_client.dart';

/// A provider the server offers (`google`, `microsoft`, `apple`).
final class OidcOffer {
  const OidcOffer(this.provider, this.label);
  final String provider;
  final String label;

  static List<OidcOffer> list(Object? raw) => [
    for (final o in (raw as List?) ?? const [])
      if (o is Map && o['provider'] is String)
        OidcOffer('${o['provider']}', '${o['label'] ?? o['provider']}'),
  ];
}

/// What the server offers to log in with (`GET /api/v1/auth/methods`).
final class AuthMethods {
  const AuthMethods({
    required this.passwordLogin,
    required this.passkeys,
    required this.oidc,
  });

  /// What an older server that has none of this offers: the password.
  static const passwordOnly = AuthMethods(
    passwordLogin: true,
    passkeys: false,
    oidc: [],
  );

  final bool passwordLogin;
  final bool passkeys;
  final List<OidcOffer> oidc;

  static AuthMethods fromJson(Map<String, Object?> j) => AuthMethods(
    passwordLogin: j['password_login'] != false,
    passkeys: j['passkeys'] == true,
    oidc: OidcOffer.list(j['oidc']),
  );
}

final class LinkedIdentity {
  LinkedIdentity(Map<String, Object?> j)
    : provider = '${j['provider']}',
      label = '${j['label'] ?? j['provider']}',
      linkedAt = _time(j['linked_at']),
      lastLoginAt = _time(j['last_login_at']);

  final String provider;
  final String label;
  final DateTime? linkedAt;
  final DateTime? lastLoginAt;
}

final class PasskeyInfo {
  PasskeyInfo(Map<String, Object?> j)
    : id = '${j['id']}',
      name = '${j['name']}',
      backedUp = j['backed_up'] == true,
      createdAt = _time(j['created_at']),
      lastUsedAt = _time(j['last_used_at']);

  final String id;
  final String name;
  final bool backedUp;
  final DateTime? createdAt;
  final DateTime? lastUsedAt;
}

DateTime? _time(Object? v) => v is String ? DateTime.tryParse(v) : null;

/// The account's login methods (`GET /api/v1/me/login-methods`).
final class LoginMethods {
  LoginMethods(Map<String, Object?> j)
    : passwordSet = (j['password'] as Map?)?['set'] == true,
      passwordLoginEnabled = (j['password'] as Map?)?['login_enabled'] != false,
      identities = [
        for (final i in (j['identities'] as List?) ?? const [])
          if (i is Map) LinkedIdentity(i.cast<String, Object?>()),
      ],
      passkeys = [
        for (final k in (j['passkeys'] as List?) ?? const [])
          if (k is Map) PasskeyInfo(k.cast<String, Object?>()),
      ],
      totpEnabled = j['totp_enabled'] == true,
      available = OidcOffer.list(j['available_providers']),
      mfa = j['mfa'] == true;

  final bool passwordSet;
  final bool passwordLoginEnabled;
  final List<LinkedIdentity> identities;
  final List<PasskeyInfo> passkeys;
  final bool totpEnabled;

  /// The providers this server has configured.
  final List<OidcOffer> available;
  final bool mfa;
}

/// TOTP enrolment's answer: the secret and its `otpauth` address, shown as
/// text (the server's ACC-6: no QR library).
final class TotpEnrolment {
  TotpEnrolment(Map<String, Object?> j)
    : secret = '${j['secret']}',
      uri = '${j['otpauth_uri']}',
      digits = j['digits'] is int ? j['digits']! as int : 6,
      periodS = j['period_s'] is int ? j['period_s']! as int : 30;

  final String secret;
  final String uri;
  final int digits;
  final int periodS;
}

/// The answer of `POST /auth/oidc/{provider}/start`.
final class OidcStart {
  const OidcStart(this.browserUrl);

  /// The address to open in the browser (null: the server did not give one,
  /// which an older server does not).
  final Uri? browserUrl;
}

/// Where the site's `/app/oidc` link brought a social login back to the app:
/// `https://<site>/app/oidc?s=<nonce>[&oidc=linked|reauth][&oidc_error=<code>]`
/// with `#oidc=<ticket>` for a login.
final class OidcReturn {
  const OidcReturn({
    required this.site,
    required this.nonce,
    this.ticket,
    this.ok,
    this.error,
  });

  /// The site's origin.
  final Uri site;
  final String nonce;

  /// A finished login's one-time ticket.
  final String? ticket;

  /// `linked` or `reauth` for a finished link or confirmation.
  final String? ok;

  /// The server's error code (`denied`, `consent_required`, ...).
  final String? error;

  static final _nonce = RegExp(r'^[A-Za-z0-9_-]{16,64}$');
  static final _code = RegExp(r'^[a-z_]{1,64}$');

  /// Reads a link; null for anything that is not a return from a social
  /// login (any other path, host or scheme, or no nonce). The host is
  /// checked against the attempt by the one waiting ([AuthReturns]).
  static OidcReturn? parse(String text) {
    final u = Uri.tryParse(text.trim());
    if (u == null || u.scheme != 'https' || u.host.isEmpty) return null;
    if (u.userInfo.isNotEmpty || u.path != '/app/oidc') return null;
    final nonce = u.queryParameters['s'];
    if (nonce == null || !_nonce.hasMatch(nonce)) return null;
    String? code(String? v) => v != null && _code.hasMatch(v) ? v : null;
    String? ticket;
    if (u.fragment.startsWith('oidc=')) {
      final t = u.fragment.substring(5);
      if (t.isNotEmpty && t.length <= 2048 && !t.contains('&')) ticket = t;
    }
    return OidcReturn(
      site: Uri(
        scheme: 'https',
        host: u.host,
        port: u.hasPort && u.port != 443 ? u.port : null,
      ),
      nonce: nonce,
      ticket: ticket,
      ok: code(u.queryParameters['oidc']),
      error: code(u.queryParameters['oidc_error']),
    );
  }
}

/// Where returns from the browser are handed to whoever waits for one (the
/// app's link handler gives them, lib/app.dart).
class AuthReturns {
  final _out = StreamController<OidcReturn>.broadcast();

  void add(OidcReturn r) => _out.add(r);

  /// Waits for the return of the attempt with [nonce] at [site], at most
  /// [timeout]; any other return is ignored. [PendingReturn.cancel] gives up.
  PendingReturn wait(
    Uri site,
    String nonce, {
    Duration timeout = const Duration(minutes: 10),
  }) => PendingReturn._(
    _out.stream.where((r) => r.nonce == nonce && r.site == site),
    timeout,
  );
}

class PendingReturn {
  PendingReturn._(Stream<OidcReturn> returns, Duration timeout) {
    _sub = returns.listen((r) => _done(r));
    _timer = Timer(timeout, () => _done(null));
  }

  late final StreamSubscription<OidcReturn> _sub;
  late final Timer _timer;
  final _result = Completer<OidcReturn?>();

  /// The return, or null when it timed out or was cancelled.
  Future<OidcReturn?> get result => _result.future;

  void _done(OidcReturn? r) {
    if (_result.isCompleted) return;
    _timer.cancel();
    unawaited(_sub.cancel());
    _result.complete(r);
  }

  void cancel() => _done(null);
}

/// A social login that did not finish: the server's error code
/// (`consent_required`, `denied`, `state_invalid`, ...), or `cancelled`,
/// `timeout` or `browser_unavailable` from the phone.
class OidcFailure implements Exception {
  OidcFailure(this.code);
  final String code;

  @override
  String toString() => 'OidcFailure($code)';
}

String newNonce([Random? random]) {
  final r = random ?? Random.secure();
  return base64Url
      .encode(List<int>.generate(18, (_) => r.nextInt(256)))
      .replaceAll('=', '');
}

/// The site's login methods for one [SiteSession]: the calls before a
/// session exists (what the server offers, a social login, a passkey login)
/// and after it (the account's own methods).
class SiteAuth {
  SiteAuth(this.session, {this.browser, this.passkeys, this.returns});

  final SiteSession session;
  final AuthBrowser? browser;
  final PasskeyService? passkeys;
  final AuthReturns? returns;

  SiteHttp get _http => session.http;

  Future<Map<String, Object?>> _ok(SiteResponse r) async {
    if (!r.ok) throw SiteException(r.status, r.detail);
    return r.json;
  }

  /// What the server offers; an older server (404) offers the password only.
  Future<AuthMethods> methods() async {
    final r = await _http.send('GET', '/auth/methods');
    if (r.status == 404) return AuthMethods.passwordOnly;
    return AuthMethods.fromJson(await _ok(r));
  }

  Future<LoginMethods> mine() async =>
      LoginMethods(await session.call('GET', '/me/login-methods'));

  // --- social login ---------------------------------------------------------

  /// Asks the site to begin a social login, with the app's own return link.
  /// [purpose] is `login`, `link` or `reauth` (the last two need a session);
  /// [consent] is the box the server asks for the first sign-in of a new
  /// account; [password] confirms a `link` for an account that has one.
  Future<OidcStart> oidcStart(
    String provider, {
    required String purpose,
    required String nonce,
    bool consent = false,
    String password = '',
  }) async {
    final body = {
      'purpose': purpose,
      'consent': consent,
      'return_to': '${session.site}/app/oidc?s=$nonce',
      if (password.isNotEmpty) 'password': password,
    };
    final path = '/auth/oidc/${Uri.encodeComponent(provider)}/start';
    final r = purpose == 'login'
        ? await _http.send('POST', path, body: body)
        : await session.callRaw('POST', path, body: body);
    final json = await _ok(r);
    final url = Uri.tryParse('${json['browser_url'] ?? ''}');
    final ok = url != null && url.scheme == 'https' && url.host.isNotEmpty;
    // Only the site's own address: nothing else is a place for the browser.
    return OidcStart(ok && url.host == session.site.host ? url : null);
  }

  /// Runs a whole social login in the system browser: asks the site, opens
  /// its address, waits for the return and finishes it. A `login` ends in a
  /// session (the user name is returned); `link` and `reauth` return null
  /// when done. [onOpened] is told when the browser is open (the screen
  /// shows "waiting", with a way to give up through [PendingReturn.cancel]
  /// of the one it is given). Throws [OidcFailure] or [SiteException].
  Future<String?> oidc(
    String provider, {
    String purpose = 'login',
    bool consent = false,
    String password = '',
    void Function(PendingReturn waiting)? onOpened,
  }) async {
    final b = browser, rs = returns;
    if (b == null || rs == null) throw OidcFailure('browser_unavailable');
    final nonce = newNonce();
    final start = await oidcStart(
      provider,
      purpose: purpose,
      nonce: nonce,
      consent: consent,
      password: password,
    );
    final url = start.browserUrl;
    if (url == null) throw OidcFailure('browser_unavailable');
    final waiting = rs.wait(session.site, nonce);
    if (!await b.open(url)) {
      waiting.cancel();
      throw OidcFailure('browser_unavailable');
    }
    onOpened?.call(waiting);
    final back = await waiting.result;
    if (back == null) throw OidcFailure('cancelled');
    if (back.error != null) throw OidcFailure(back.error!);
    if (purpose != 'login') return null;
    final ticket = back.ticket;
    if (ticket == null) throw OidcFailure('state_invalid');
    final done = await _http.send(
      'POST',
      '/auth/oidc/complete',
      body: {'ticket': ticket},
    );
    if (!done.ok) throw SiteException(done.status, done.detail);
    return session.adopt(done);
  }

  Future<void> unlink(String provider, String password) async {
    await _ok(
      await session.callRaw(
        'DELETE',
        '/me/identities/${Uri.encodeComponent(provider)}',
        body: {'password': password},
      ),
    );
  }

  // --- passkeys ---------------------------------------------------------------

  Future<bool> passkeysAvailable() async {
    final p = passkeys;
    return p != null && await p.available();
  }

  PasskeyService get _passkeys =>
      passkeys ?? (throw PasskeyException('unsupported'));

  /// A login with a passkey: no user name. Throws [PasskeyException] when the
  /// phone could not do it, [SiteException] when the server refused.
  Future<String> passkeyLogin() async {
    final first = await _ok(
      await _http.send('POST', '/auth/passkey/login/options'),
    );
    final credential = await _passkeys.get(jsonEncode(first['options']));
    final r = await _http.send(
      'POST',
      '/auth/passkey/login',
      body: {
        'challenge_token': first['challenge_token'],
        'credential': jsonDecode(credential),
      },
    );
    if (!r.ok) throw SiteException(r.status, r.detail);
    return session.adopt(r);
  }

  /// Adds a passkey to the account ([password] confirms, when it has one).
  Future<void> addPasskey({String password = '', String name = ''}) async {
    final first = await session.call(
      'POST',
      '/me/passkeys/options',
      body: {'password': password},
    );
    final credential = await _passkeys.create(jsonEncode(first['options']));
    await session.call(
      'POST',
      '/me/passkeys',
      body: {
        'challenge_token': first['challenge_token'],
        'credential': jsonDecode(credential),
        if (name.trim().isNotEmpty) 'name': name.trim(),
      },
    );
  }

  Future<void> renamePasskey(String id, String name) => session.call(
    'PATCH',
    '/me/passkeys/${Uri.encodeComponent(id)}',
    body: {'name': name},
  );

  Future<void> removePasskey(String id, String password) async {
    await _ok(
      await session.callRaw(
        'DELETE',
        '/me/passkeys/${Uri.encodeComponent(id)}',
        body: {'password': password},
      ),
    );
  }

  /// The confirmation of an account with no password, with a passkey.
  Future<void> confirmWithPasskey() async {
    final first = await session.call('POST', '/auth/stepup/passkey/options');
    final credential = await _passkeys.get(jsonEncode(first['options']));
    await session.call(
      'POST',
      '/auth/stepup/passkey',
      body: {
        'challenge_token': first['challenge_token'],
        'credential': jsonDecode(credential),
      },
    );
  }

  // --- the password and TOTP ---------------------------------------------------

  Future<void> setPassword(String current, String next) => session.call(
    'POST',
    '/me/password',
    body: {'password': current, 'new_password': next},
  );

  Future<void> removePassword(String current) async {
    await _ok(
      await session.callRaw(
        'DELETE',
        '/me/password',
        body: {'password': current},
      ),
    );
  }

  Future<TotpEnrolment> totpEnrol(String password) async => TotpEnrolment(
    await session.call(
      'POST',
      '/auth/totp/enrol',
      body: {'password': password},
    ),
  );

  Future<void> totpConfirm(String code) =>
      session.call('POST', '/auth/totp/confirm', body: {'code': code});

  Future<void> totpDisable(String password, String code) => session.call(
    'POST',
    '/auth/totp/disable',
    body: {'password': password, 'code': code},
  );

  /// The confirmation of an account with no password, with a TOTP code.
  Future<void> confirmWithTotp(String code) =>
      session.call('POST', '/auth/stepup/totp', body: {'code': code});
}
