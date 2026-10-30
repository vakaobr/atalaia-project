// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A stand-in for a field's site server (server/atalaia_server/api/auth.py,
/// api/registrations.py and the app's field listing), for the app's tests:
/// the same paths, bodies, error codes and refresh-token rotation (a spent
/// refresh token that comes back ends the session), with its state in
/// memory.
library;

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/site/site_auth.dart';
import 'package:atalaia_app/site/site_client.dart';

class FakeSite {
  FakeSite({this.totp = false});

  /// Whether the account has TOTP (the login then asks for [code]).
  bool totp;
  final username = 'falcao';
  final password = 'correct horse battery';
  final code = '123456';
  var offline = false;

  /// Access tokens live this many seconds.
  var accessTtl = 900;

  final requests = <String>[];
  final bodies = <String, Object?>{};
  var _n = 0;

  // --- sessions ---------------------------------------------------------------
  final _live = <String>{}; // refresh tokens not yet spent
  final _spent = <String>{};
  final _access = <String>{};
  var sessionEnded = false;
  var refreshes = 0;

  // --- login methods (the site server's LG-* and ACC-*) -------------------------
  /// What `GET /auth/methods` says.
  Map<String, Object?> offers = {
    'password_login': true,
    'passkeys': true,
    'oidc': [
      {'provider': 'google', 'label': 'Google'},
      {'provider': 'microsoft', 'label': 'Microsoft'},
    ],
  };

  /// The account's linked providers, passkeys, password and TOTP.
  final identities = <Map<String, Object?>>[];
  final passkeys = <Map<String, Object?>>[];
  var passwordSet = true;
  var totpEnabled = false;

  /// The account has a second factor or a staff role (the server's SR-1): its
  /// login methods change only after a TOTP or passkey step-up.
  var stepUpGuard = false;
  var _steppedUp = false;
  var totpPending = false;
  var accountPassword = 'correct horse battery';

  /// A proof from the last ten minutes (an account with no password).
  var confirmed = false;

  /// The ticket the next social login completes with, and the passkey the
  /// phone's Credential Manager "uses".
  var goodTicket = 'good-ticket';
  var goodCredential = 'cred-1';

  /// A refusal the next call to this `METHOD /path` gets: its status, code.
  final refusals = <String, (int, String)>{};

  /// The `return_to` of the last `start`, to see that it is the app's own.
  String? lastReturnTo;
  String? lastStartPurpose;
  bool? lastStartNoticeSeen;
  bool? lastStartAge;

  /// What the sign-up's `register` last sent, and the accounts it made
  /// (user name -> password; the login takes them too).
  Map<String, Object?>? lastRegister;
  final registered = <String, String>{};
  // (the notice version it carried: lastNoticeVersion, below)

  /// Ends every access token (as if they had expired).
  void expireAccess() => _access.clear();

  String _newRefresh() {
    final t = 'rt-${++_n}';
    _live.add(t);
    return t;
  }

  SiteResponse _session() {
    final a = 'at-${++_n}';
    _access.add(a);
    return SiteResponse(200, {
      'access_token': a,
      'token_type': 'bearer',
      'expires_in': accessTtl,
      'mfa': totp,
      'user': {'id': 'u1', 'username': username},
    }, refreshToken: _newRefresh());
  }

  // --- the field ----------------------------------------------------------------
  final fieldId = '0192f3a0-0000-7000-8000-00000000f1e1';
  final slug = 'campo-norte';
  final games = <Map<String, Object?>>[
    {
      'id': '0192f3a0-0000-7000-8000-000000000001',
      'title': 'Domingo de manhã',
      'description': 'Domination, 4 horas.',
      'starts_at': '2026-11-08T09:00:00+00:00',
      'ends_at': '2026-11-08T13:00:00+00:00',
      'location': 'Serra da Arrábida',
      'mode_id': 'org.atalaia.domination',
      'teams': ['red', 'blue'],
      'max_players': 60,
      'places_left': 12,
      'registration_opens_at': null,
      'registration_closes_at': '2026-11-07T20:00:00+00:00',
      'registration_state': 'open',
      'registration_open': true,
      'federation': 'required',
      'predeclare_replicas': true,
      'status': 'published',
      'cancelled_reason': null,
    },
    {
      'id': '0192f3a0-0000-7000-8000-000000000002',
      'title': 'Noturno',
      'description': null,
      'starts_at': '2026-11-14T20:00:00+00:00',
      'ends_at': '2026-11-14T23:30:00+00:00',
      'location': null,
      'mode_id': null,
      'teams': <String>[],
      'max_players': null,
      'places_left': null,
      'registration_opens_at': '2026-11-09T09:00:00+00:00',
      'registration_closes_at': null,
      'registration_state': 'not_yet',
      'registration_open': false,
      'federation': 'off',
      'predeclare_replicas': false,
      'status': 'published',
      'cancelled_reason': null,
    },
  ];

  /// `game_history` of `GET /me/data`: two games, the older first.
  final history = <Map<String, Object?>>[
    {
      'game': '0192f3a0-0000-7000-8000-0000000000a1',
      'field': 'Campo Norte',
      'name': 'Sábado de Domination',
      'mode_id': 'org.atalaia.domination',
      'teams': ['red', 'blue'],
      'state': 'ended',
      'started_at': '2026-09-12T09:00:00+00:00',
      'ended_at': '2026-09-12T11:00:00+00:00',
      'player_ids': ['p-sitemade2345'],
      'registered': true,
      'events': [
        {
          't': 65000,
          'type': 'player.checkin',
          'team': 'red',
          'squad': 0,
          'data': {'player': 'p-sitemade2345'},
          'received_at': '2026-09-12T09:01:10+00:00',
        },
        {
          't': 3725000,
          'type': 'score.delta',
          'team': 'red',
          'squad': 0,
          'data': {'player': 'p-sitemade2345', 'amount': 5},
          'received_at': '2026-09-12T10:02:10+00:00',
        },
      ],
      'totals': {'red': 120, 'blue': 90},
    },
    {
      'game': '0192f3a0-0000-7000-8000-0000000000a2',
      'field': 'Campo Norte',
      'name': 'Noturno',
      'mode_id': null,
      'teams': ['red', 'blue'],
      'state': 'ended',
      'started_at': '2026-10-03T20:00:00+00:00',
      'ended_at': '2026-10-03T22:00:00+00:00',
      'player_ids': ['p-sitemade2345'],
      'registered': true,
      'events': <Object?>[],
      'totals': {'red': 40, 'blue': 40},
    },
  ];

  /// The field's APD rule (protocol/apd.md), sent with the field; null: none.
  Map<String, Object?>? apdRule;

  /// The field's country, sent with the field when [sendsCountry] (a site
  /// server from before fields had one sends none: the app takes PT).
  String? country;
  var sendsCountry = false;
  final regs = <String, Map<String, Object?>>{};
  final claims = <Map<String, Object?>>[];
  final linked = <String, String>{};

  Map<String, Object?> _field() => {
    'id': fieldId,
    'slug': slug,
    'name': 'Campo Norte',
    'timezone': 'Europe/Lisbon',
    'federation_label': 'FPA',
    if (apdRule != null) 'apd': apdRule,
    if (sendsCountry) 'country': country,
    'limit_template': 'portugal',
    'classes': ['cqb', 'dmr', 'rifle', 'sniper'],
    'max_replicas': 3,
  };

  Map<String, Object?> _regJson(Map<String, Object?> r) {
    final g = games.firstWhere((x) => x['id'] == r['scheduled_game_id']);
    return {
      ...r,
      'field_id': fieldId,
      'source': 'site',
      'has_ticket': r['status'] == 'registered',
      'game': {
        'title': g['title'],
        'starts_at': g['starts_at'],
        'ends_at': g['ends_at'],
        'status': g['status'],
      },
      'field': {'name': 'Campo Norte', 'slug': slug},
    };
  }

  Map<String, Object?> _withTicket(Map<String, Object?> r) {
    final n = ++_n;
    // Not real tickets (the codec has its own vector tests): only their shape.
    return {
      ..._regJson(r),
      'ticket': 'T${'k' * 41}$n'.substring(0, 43),
      'ticket_text': 'atalaia:ticket:FAKE-${r['id']}-$n',
    };
  }

  // --- the privacy notice and which version the account was shown (api/privacy.py, CONS-*, LEG-*) -----
  /// The notice's current version and its Markdown per language (empty: the
  /// operator has not published one).
  var noticeVersion = '2026-11';
  Map<String, String> noticeTexts = {
    'pt':
        '# Aviso de privacidade\n\nTratamos o teu **nome**.\n\n- guardamos o registo\n- apagamos a pedido',
    'en':
        '# Privacy notice\n\nWe keep your **name**.\n\n- we keep the registration\n- we erase on request',
    'de': '# Datenschutzhinweis\n\nWir speichern deinen Namen.',
  };

  /// What `GET /me` says about the notice: `current`, `outdated` or `missing`
  /// (null: an older server whose /me has no `notice`), the version the
  /// account was last shown, and the languages the app asked the notice in.
  String? noticeStatus = 'current';
  String? noticeShownVersion = '2026-11';
  final noticeLangsAsked = <String>[];

  /// A notice that changes while the person reads: the version the server
  /// has from the next acknowledgement on (the 409 case).
  String? changeNoticeOnAck;

  /// A server that takes `notice_version` on the social sign-up's start.
  var startTakesNoticeVersion = true;
  // A server before APP-4 refuses `app_challenge` (422) and its ticket needs no verifier.
  var startTakesAppChallenge = true;
  String? lastAppChallenge;
  String? lastVerifier;

  /// A 422 for another reason on the start (a field the body got wrong).
  var startValidationError = false;
  String? lastNoticeVersion;

  // --- the chrono link of a hosted hub (api/hub_share.py, SVX-2) -----------------
  /// Hosted mode (otherwise 404 `not_hosted`), whether the account is linked,
  /// and whether sharing is on.
  var hosted = false;
  var hubLinked = false;
  var hubSharing = false;
  var codesMade = 0;

  /// The code another field made, which `link` takes (once).
  var otherFieldCode = 'ABCD-EFGH-JKLM';

  SiteResponse? _noticeAndHub(
    String method,
    String path,
    Map<String, Object?> b,
  ) {
    SiteResponse err(int status, String detail) =>
        SiteResponse(status, {'detail': detail});
    switch ('$method $path') {
      case 'GET /me':
        return SiteResponse(200, {
          'id': 'u1',
          'username': username,
          if (noticeStatus != null)
            'notice': {
              'status': noticeStatus,
              'version': noticeStatus == 'missing' ? null : noticeShownVersion,
              'current_version': noticeVersion,
              'shown_at': noticeStatus == 'missing'
                  ? null
                  : '2026-10-01T10:00:00+00:00',
              'notice_published': noticeTexts.isNotEmpty,
            },
        });
      case 'POST /me/notice':
        if (changeNoticeOnAck != null) {
          noticeVersion = changeNoticeOnAck!;
          changeNoticeOnAck = null;
        }
        if (b['notice_version'] != noticeVersion) {
          return SiteResponse(409, {
            'detail': 'notice_version_changed',
            'current_version': noticeVersion,
          });
        }
        noticeStatus = 'current';
        noticeShownVersion = noticeVersion;
        return SiteResponse(200, {
          'status': 'current',
          'version': noticeVersion,
          'current_version': noticeVersion,
          'shown_at': '2026-10-29T10:00:00+00:00',
        });
      case 'GET /me/hub-share':
        if (!hosted) return err(404, 'not_hosted');
        return SiteResponse(200, _hub());
      case 'POST /me/hub-share/code':
        if (!hosted) return err(404, 'not_hosted');
        hubLinked = true; // a code makes the person if the account had none
        codesMade++;
        return SiteResponse(201, {
          'code': 'WXYZ-2345-QRST',
          'expires_at': '2026-10-29T10:15:00+00:00',
          'expires_in': 900,
        });
      case 'POST /me/hub-share/link':
        if (!hosted) return err(404, 'not_hosted');
        if (b['code'] != otherFieldCode) return err(400, 'invalid_code');
        if (hubLinked) return err(409, 'already_linked');
        hubLinked = true;
        return SiteResponse(200, _hub());
      case 'DELETE /me/hub-share':
        if (!hosted) return err(404, 'not_hosted');
        if (!hubLinked) return err(404, 'not_linked');
        hubLinked = false;
        hubSharing = false;
        return const SiteResponse(204, null);
    }
    return null;
  }

  Map<String, Object?> _hub() => {
    'linked': hubLinked,
    'linked_at': hubLinked ? '2026-10-20T09:00:00+00:00' : null,
    'sharing': hubLinked && hubSharing,
  };

  /// The account's own login methods (api/login_methods.py, api/me.py,
  /// api/auth.py), or null for any other request.
  SiteResponse? _loginMethods(
    String method,
    String path,
    Map<String, Object?> b,
    String? bearer,
  ) {
    SiteResponse err(int status, String detail) =>
        SiteResponse(status, {'detail': detail});
    // A change with a password sends it; without one it needs a proof.
    SiteResponse? checkConfirm() {
      if (passwordSet) {
        return b['password'] == accountPassword
            ? null
            : err(403, 'invalid_password');
      }
      return confirmed ? null : err(403, 'confirmation_required');
    }

    const ok = SiteResponse(204, null);
    final id = RegExp(r'^/me/passkeys/([^/]+)$').firstMatch(path)?.group(1);
    final provider = RegExp(
      r'^/me/identities/([a-z]+)$',
    ).firstMatch(path)?.group(1);
    switch ('$method $path') {
      case 'GET /me/login-methods':
        return SiteResponse(200, {
          'password': {'set': passwordSet, 'login_enabled': true},
          'identities': identities,
          'passkeys': passkeys,
          'totp_enabled': totpEnabled,
          'available_providers': offers['oidc'],
          'mfa': false,
          'step_up_needed': stepUpGuard && !_steppedUp,
        });
      case 'POST /me/passkeys/options':
        if (stepUpGuard && !_steppedUp) return err(403, 'mfa_required');
        return checkConfirm() ??
            const SiteResponse(200, {
              'options': {'challenge': 'chal-new', 'rpId': 'site.test'},
              'challenge_token': 'tok-add',
            });
      case 'POST /me/passkeys':
        final c = b['credential'];
        if (b['challenge_token'] != 'tok-add' || c is! Map) {
          return err(400, 'passkey_invalid');
        }
        passkeys.add({
          'id': 'k${++_n}',
          'name': b['name'] ?? 'Passkey ${passkeys.length + 1}',
          'backed_up': true,
          'created_at': '2026-10-28T10:00:00+00:00',
          'last_used_at': null,
        });
        return SiteResponse(201, passkeys.last);
      case 'POST /auth/stepup/passkey/options':
        return const SiteResponse(200, {
          'options': {'challenge': 'chal-up', 'rpId': 'site.test'},
          'challenge_token': 'tok-up',
        });
      case 'POST /auth/stepup/passkey':
        confirmed = true;
        _steppedUp = true;
        return const SiteResponse(200, {'mfa': true});
      case 'POST /auth/stepup/totp':
        if (b['code'] != code) return err(401, 'invalid_code');
        confirmed = true;
        _steppedUp = true;
        return const SiteResponse(200, {'mfa': true});
      case 'POST /me/password':
        if (passwordSet && b['password'] != accountPassword) {
          return err(403, 'invalid_password');
        }
        if (!passwordSet && !confirmed) {
          return err(403, 'confirmation_required');
        }
        if ('${b['new_password']}'.length < 10) {
          return err(400, 'password_too_short');
        }
        passwordSet = true;
        accountPassword = '${b['new_password']}';
        return ok;
      case 'DELETE /me/password':
        final bad = checkConfirm();
        if (bad != null) return bad;
        if (identities.isEmpty && passkeys.isEmpty) {
          return err(409, 'last_login_method');
        }
        passwordSet = false;
        return ok;
      case 'POST /auth/totp/enrol':
        final bad = checkConfirm();
        if (bad != null) return bad;
        totpPending = true;
        return const SiteResponse(200, {
          'secret': 'JBSWY3DPEHPK3PXP',
          'otpauth_uri':
              'otpauth://totp/Atalaia:falcao?secret=JBSWY3DPEHPK3PXP',
          'digits': 6,
          'period_s': 30,
        });
      case 'POST /auth/totp/confirm':
        if (!totpPending) return err(409, 'totp_not_pending');
        if (b['code'] != code) return err(401, 'invalid_code');
        totpEnabled = true;
        totpPending = false;
        return ok;
      case 'POST /auth/totp/disable':
        final bad = checkConfirm();
        if (bad != null) return bad;
        if (b['code'] != code) return err(401, 'invalid_code');
        totpEnabled = false;
        return ok;
    }
    if (provider != null && method == 'DELETE') {
      final bad = checkConfirm();
      if (bad != null) return bad;
      final i = identities.indexWhere((x) => x['provider'] == provider);
      if (i < 0) return err(404, 'identity_not_found');
      if (!passwordSet && identities.length + passkeys.length < 2) {
        return err(409, 'last_login_method');
      }
      identities.removeAt(i);
      return ok;
    }
    if (id != null) {
      final i = passkeys.indexWhere((x) => x['id'] == id);
      if (i < 0) return err(404, 'passkey_not_found');
      if (method == 'PATCH') {
        passkeys[i] = {...passkeys[i], 'name': b['name']};
        return SiteResponse(200, passkeys[i]);
      }
      if (method == 'DELETE') {
        final bad = checkConfirm();
        if (bad != null) return bad;
        passkeys.removeAt(i);
        return ok;
      }
    }
    return null;
  }

  SiteHttp http(Uri origin) => _FakeSiteHttp(this);

  SiteResponse handle(
    String method,
    String fullPath,
    Object? body,
    String? bearer,
    String? refresh,
  ) {
    final cut = fullPath.indexOf('?');
    final path = cut < 0 ? fullPath : fullPath.substring(0, cut);
    final query = cut < 0
        ? const <String, String>{}
        : Uri.splitQueryString(fullPath.substring(cut + 1));
    requests.add('$method $path');
    bodies['$method $path'] = body;
    final b = body is Map ? body.cast<String, Object?>() : <String, Object?>{};
    SiteResponse err(int status, String detail) =>
        SiteResponse(status, {'detail': detail});
    final refused = refusals.remove('$method $path');
    if (refused != null) return err(refused.$1, refused.$2);
    switch ('$method $path') {
      case 'GET /auth/methods':
        return SiteResponse(200, offers);
      case 'GET /privacy-notice':
        // Public: the operator's text in the language asked for, else in the
        // first one it has (CONS-5).
        if (noticeTexts.isEmpty) {
          return err(404, 'privacy_notice_not_published');
        }
        final asked = query['lang'] ?? 'pt';
        noticeLangsAsked.add(asked);
        final lang = noticeTexts.containsKey(asked)
            ? asked
            : noticeTexts.keys.first;
        return SiteResponse(200, {
          'version': noticeVersion,
          'lang': lang,
          'requested_lang': asked,
          'available': noticeTexts.keys.toList(),
          'markdown': noticeTexts[lang],
          'html': '',
          'url': 'https://campo.example.pt/privacy?lang=$lang',
        });
      case 'POST /auth/oidc/google/start':
      case 'POST /auth/oidc/microsoft/start':
        if (b['purpose'] != 'login' &&
            (bearer == null || !_access.contains(bearer))) {
          return err(401, 'not_authenticated');
        }
        if (b['purpose'] == 'link' &&
            passwordSet &&
            b['password'] != accountPassword) {
          return err(403, 'invalid_password');
        }
        if (startValidationError) {
          return SiteResponse(422, {
            'detail': [
              {
                'loc': ['body', 'return_to'],
                'msg': 'String should have at most 400 characters',
                'type': 'string_too_long',
              },
            ],
          });
        }
        // A server before the notice version (or before APP-4) refuses the
        // field (422), naming every one it does not know, as FastAPI does.
        final unknown = [
          if (b.containsKey('notice_version') && !startTakesNoticeVersion)
            'notice_version',
          if (b.containsKey('app_challenge') && !startTakesAppChallenge)
            'app_challenge',
        ];
        if (unknown.isNotEmpty) {
          return SiteResponse(422, {
            'detail': [
              for (final f in unknown)
                {
                  'loc': ['body', f],
                  'msg': 'Extra inputs are not permitted',
                  'type': 'extra_forbidden',
                },
            ],
          });
        }
        if (b.containsKey('notice_version') &&
            b['notice_version'] != noticeVersion) {
          return err(409, 'notice_version_changed');
        }
        lastAppChallenge = b['app_challenge'] as String?;
        lastNoticeVersion = b['notice_version'] as String?;
        lastReturnTo = '${b['return_to']}';
        lastStartPurpose = '${b['purpose']}';
        lastStartNoticeSeen = b['notice_seen'] == true;
        lastStartAge = b['age_confirmed'] == true;
        final p = path.split('/')[3];
        return SiteResponse(200, {
          'authorization_url': 'https://accounts.example/auth?p=$p',
          'browser_url':
              '${Uri.parse('${b['return_to']}').origin}/api/v1/auth/oidc/$p/browser?x=bind&s=state',
        });
      case 'POST /auth/oidc/complete':
        if (b['ticket'] != goodTicket) return err(401, 'invalid_ticket');
        lastVerifier = b['verifier'] as String?;
        final challenge = lastAppChallenge;
        if (challenge != null &&
            (lastVerifier == null ||
                verifierChallenge(lastVerifier!) != challenge)) {
          return err(401, 'invalid_ticket');
        }
        return _session();
      case 'POST /auth/passkey/login/options':
        return const SiteResponse(200, {
          'options': {'challenge': 'chal', 'rpId': 'site.test'},
          'challenge_token': 'tok-login',
        });
      case 'POST /auth/passkey/login':
        final c = b['credential'];
        if (b['challenge_token'] != 'tok-login' ||
            c is! Map ||
            c['id'] != goodCredential) {
          return err(401, 'invalid_passkey');
        }
        return _session();
      case 'POST /auth/register':
        // api/auth.py (LEG-*): 16 or older and the notice shown, the notice
        // version checked, the name free.
        lastRegister = b;
        if (b['age_confirmed'] != true) {
          return err(400, 'age_confirmation_required');
        }
        if (b['notice_seen'] != true) return err(400, 'notice_required');
        if (b.containsKey('notice_version') &&
            b['notice_version'] != noticeVersion) {
          return SiteResponse(409, {
            'detail': 'notice_version_changed',
            'current_version': noticeVersion,
          });
        }
        if (b['username'] == username ||
            registered.containsKey(b['username'])) {
          return err(409, 'username_or_email_taken');
        }
        registered['${b['username']}'] = '${b['password']}';
        return SiteResponse(201, {'id': 'u2', 'username': b['username']});
      case 'POST /auth/login':
        final isNew = registered[b['username']] == b['password'];
        if (!isNew &&
            (b['username'] != username || b['password'] != password)) {
          return err(401, 'invalid_credentials');
        }
        if (totp) {
          return const SiteResponse(200, {
            'totp_required': true,
            'totp_session': 'totp-step',
          });
        }
        return _session();
      case 'POST /auth/login/totp':
        if (b['totp_session'] != 'totp-step') {
          return err(401, 'invalid_totp_session');
        }
        if (b['code'] != code) return err(401, 'invalid_code');
        return _session();
      case 'POST /auth/refresh':
        refreshes++;
        if (refresh == null) return err(401, 'invalid_refresh_token');
        if (_spent.contains(refresh)) {
          // A replay: the whole session ends (api/auth.py).
          sessionEnded = true;
          _live.clear();
          _access.clear();
          return err(401, 'invalid_refresh_token');
        }
        if (!_live.remove(refresh)) return err(401, 'invalid_refresh_token');
        _spent.add(refresh);
        return _session();
      case 'POST /auth/logout':
        _access.remove(bearer);
        _live.clear();
        return const SiteResponse(204, null);
    }
    if (bearer == null || !_access.contains(bearer)) {
      return err(401, 'not_authenticated');
    }
    final login = _loginMethods(method, path, b, bearer);
    if (login != null) return login;
    final own = _noticeAndHub(method, path, b);
    if (own != null) return own;
    final regPath = RegExp(
      r'^/fields/([0-9a-f-]+)/scheduled-games/([0-9a-f-]+)/registrations$',
    ).firstMatch(path);
    if (method == 'POST' && regPath != null) {
      final gid = regPath.group(2)!;
      final g = games.where((x) => x['id'] == gid).firstOrNull;
      if (g == null) return err(404, 'scheduled_game_not_found');
      if (g['registration_open'] != true) {
        return err(409, 'registration_closed');
      }
      if (regs.values.any(
        (r) => r['scheduled_game_id'] == gid && r['status'] == 'registered',
      )) {
        return err(409, 'already_registered');
      }
      if (g['federation'] == 'required' && b['federation_number'] == null) {
        return err(400, 'federation_number_required');
      }
      final rule = apdRule;
      if (rule != null && rule['register'] == true) {
        final accepted = rule['accepted'] as List?;
        if (b['membership_number'] == null && b['federation_number'] == null) {
          return err(400, 'membership_missing');
        }
        if (accepted != null && !accepted.contains(b['apd_id'])) {
          return err(400, 'apd_not_accepted');
        }
      }
      final id =
          '0192f3a0-0000-7000-8000-0000000a${(++_n).toString().padLeft(4, '0')}';
      final r = <String, Object?>{
        'id': id,
        'scheduled_game_id': gid,
        'player_id': linked[fieldId] ??= 'p-sitemade2345',
        'display_name': b['display_name'],
        'team_preference': b['team_preference'],
        'federation_number': b['membership_number'] ?? b['federation_number'],
        'apd_id': b['apd_id'],
        'membership_expires': b['membership_expires'],
        'status': 'registered',
        'replicas': [
          for (final x in (b['replicas'] as List?) ?? const [])
            {...(x as Map).cast<String, Object?>(), 'state': null},
        ],
      };
      regs[id] = r;
      return SiteResponse(201, _withTicket(r));
    }
    final mine = RegExp(
      r'^/me/registrations/([0-9a-f-]+)(/ticket)?$',
    ).firstMatch(path);
    if (mine != null) {
      final r = regs[mine.group(1)];
      if (r == null) return err(404, 'registration_not_found');
      if (mine.group(2) != null && method == 'POST') {
        return SiteResponse(200, _withTicket(r));
      }
      if (method == 'PATCH') {
        for (final k in [
          'display_name',
          'team_preference',
          'federation_number',
          'apd_id',
          'membership_expires',
        ]) {
          if (b.containsKey(k)) r[k] = b[k];
        }
        if (b['replicas'] is List) {
          r['replicas'] = [
            for (final x in b['replicas']! as List)
              {...(x as Map).cast<String, Object?>(), 'state': null},
          ];
        }
        return SiteResponse(200, _regJson(r));
      }
      if (method == 'DELETE') {
        r['status'] = 'cancelled';
        return const SiteResponse(204, null);
      }
    }
    switch ('$method $path') {
      case 'GET /fields-by-slug/campo-norte':
        return SiteResponse(200, {'field': _field(), 'games': games});
      case 'GET /me/data':
        // Only the part the app reads: the player's own game history
        // (services/history.player_history), oldest first.
        return SiteResponse(200, {'game_history': history});
      case 'GET /me/registrations':
        return SiteResponse(200, [for (final r in regs.values) _regJson(r)]);
      case 'GET /me/player-ids':
        return SiteResponse(200, {
          'player_ids': [
            for (final e in linked.entries)
              {'field_id': e.key, 'player_id': e.value, 'linked_at': 'x'},
          ],
          'claims': claims,
        });
      case 'POST /me/player-ids':
        if (linked.containsKey(b['field_id'])) {
          return err(409, 'player_id_exists');
        }
        final c = {
          'id': 'c${++_n}',
          'field_id': b['field_id'],
          'player_id': b['player_id'],
          'status': 'pending',
        };
        claims.add(c);
        return SiteResponse(202, c);
    }
    return err(404, 'Not Found');
  }
}

class _FakeSiteHttp implements SiteHttp {
  _FakeSiteHttp(this.site);
  final FakeSite site;

  @override
  Future<SiteResponse> send(
    String method,
    String path, {
    Object? body,
    String? bearer,
    String? refreshToken,
  }) async {
    if (site.offline) throw SiteException(0, 'offline');
    return site.handle(method, path, body, bearer, refreshToken);
  }
}

/// [site] over real HTTP on 127.0.0.1 (a free port), for the dart:io client:
/// the refresh token as the `__Secure-atalaia_refresh` cookie, as the site
/// server sets and reads it.
Future<HttpServer> serveFakeSite(FakeSite site) async {
  final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
  server.listen((req) async {
    final text = await utf8.decodeStream(req);
    final auth = req.headers.value('authorization');
    String? refresh;
    if (req.headers.value('x-atalaia-refresh') == '1') {
      for (final c in req.cookies) {
        if (c.name == refreshCookie) refresh = c.value;
      }
    }
    final path =
        req.uri.path.replaceFirst('/api/v1', '') +
        (req.uri.query.isEmpty ? '' : '?${req.uri.query}');
    final r = site.handle(
      req.method,
      path,
      text.isEmpty ? null : jsonDecode(text),
      auth != null && auth.startsWith('Bearer ') ? auth.substring(7) : null,
      refresh,
    );
    req.response.statusCode = r.status;
    if (r.refreshToken != null) {
      req.response.headers.add(
        'set-cookie',
        '$refreshCookie=${r.refreshToken}; HttpOnly; Max-Age=2592000; '
            'Path=/api/v1/auth/refresh; SameSite=strict; Secure',
      );
    }
    if (r.body != null) {
      req.response.headers.contentType = ContentType.json;
      req.response.write(jsonEncode(r.body));
    }
    await req.response.close();
  });
  return server;
}
