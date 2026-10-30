// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Online registration on a field's site server (ADR-P4-11, plan phase 16's
/// app part, decision S16-13): the player opens the field (a link from the
/// site's register page, or its address pasted), confirms the site the
/// first time, logs in with their account (password, then the TOTP code
/// when the account has one), sees the field's published games, registers
/// with the replicas they will use, keeps the check-in ticket on the phone
/// (shown as a QR code and as text, for a marshal at the field), changes
/// or cancels the registration, and can claim the player id this phone
/// already has at the field (the field's controller confirms it, S16-4).
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app.dart';
import '../checkin/apd_fields.dart';
import '../checkin/checkin_screen.dart' show replicaLabel;
import '../checkin/declare_replicas_screen.dart' show NewReplicaDialog;
import '../checkin/field_identity.dart';
import '../checkin/my_replicas.dart';
import '../l10n/strings.dart';
import '../ui/code_kind.dart';
import '../ui/qr_painter.dart';
import '../ui/widgets.dart';
import 'account_screen.dart';
import 'history_screens.dart';
import 'hub_share.dart';
import 'privacy_notice.dart';
import 'privacy_screens.dart';
import 'site_api.dart';
import 'site_auth.dart';
import 'site_client.dart';
import 'site_link.dart';

/// The text for a site server's error [code] (`game_full`), or the generic
/// one with the code.
///
/// A registration's membership errors say "APD" or "association" by the
/// field's [country] (apdKey).
String siteError(Strings s, SiteException e, {String? country = 'PT'}) =>
    e.offline
    ? s.t('site.err.offline')
    : s.tOr(
        apdKey('site.err.${e.code}', country),
        s.t('site.error', {'error': e.code}),
      );

/// A date and time on the phone's clock: `08/11/2026 09:00`.
String siteMoment(DateTime t) {
  final l = t.toLocal();
  String two(int v) => v.toString().padLeft(2, '0');
  return '${two(l.day)}/${two(l.month)}/${l.year} ${two(l.hour)}:${two(l.minute)}';
}

enum _Step { address, confirm, login, signup, totp, busy, waiting, field }

class SiteScreen extends StatefulWidget {
  const SiteScreen({this.link, super.key});

  /// The field (and game) to open; null: the person types its address.
  final SiteGameLink? link;

  @override
  State<SiteScreen> createState() => _SiteScreenState();
}

class _SiteScreenState extends State<SiteScreen> {
  final _address = TextEditingController();
  final _user = TextEditingController();
  final _password = TextEditingController();
  final _signupUser = TextEditingController();
  final _signupEmail = TextEditingController();
  final _signupPassword = TextEditingController();
  final _code = TextEditingController();
  _Step _step = _Step.address;
  SiteGameLink? _link;
  SiteSession? _session;
  TotpNeeded? _totp;
  FieldGames? _games;
  List<Registration> _mine = const [];
  String? _error;
  bool _openedGame = false;

  /// What the site offers besides the password, and whether this phone can
  /// use passkeys (decision PKA-1); read when the login is shown.
  AuthMethods _methods = AuthMethods.passwordOnly;
  bool _passkeys = false;
  PendingReturn? _waiting;

  /// A new account (password or social) rests on the contract, not on consent
  /// (LEG-*): the person opens the privacy notice ([_noticeOpened], which also
  /// gives [_noticeVersion], the version on their screen), says they read it
  /// ([_noticeSeen]) and that they are 16 or older ([_age16]; no date of birth
  /// is asked). Younger players check in at the field without an account.
  bool _noticeSeen = false;
  bool _age16 = false;
  bool _noticeOpened = false;

  /// The version of the privacy notice on offer or shown; null: none published
  /// or unread. [_noticePublished] is whether the server has one.
  String? _noticeVersion;
  bool _noticePublished = false;

  /// Which notice version the signed-in account was last shown (null: not
  /// known), and whether this site is a hosted hub (the chrono link screen is
  /// only then).
  NoticeState? _noticeState;
  bool _hosted = false;

  @override
  void initState() {
    super.initState();
    if (widget.link != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _use(widget.link!));
    }
  }

  @override
  void dispose() {
    _waiting?.cancel();
    _address.dispose();
    _user.dispose();
    _password.dispose();
    _signupUser.dispose();
    _signupEmail.dispose();
    _signupPassword.dispose();
    _code.dispose();
    super.dispose();
  }

  void _fail(SiteException e, _Step back) {
    if (!mounted) return;
    if (e.loginRequired || back == _Step.login) unawaited(_loadMethods());
    setState(() {
      _error = siteError(context.s, e);
      _step = e.loginRequired ? _Step.login : back;
    });
  }

  Future<void> _use(SiteGameLink link) async {
    final services = context.services;
    final session = services.sites.of(link.site);
    final accounts = services.sites.accounts;
    final site = '${link.site}';
    _user.text = await accounts.username(site) ?? _user.text;
    final confirmed = await accounts.confirmed(site);
    if (!mounted) return;
    setState(() {
      _link = link;
      _session = session;
      _error = null;
      _step = confirmed ? _Step.busy : _Step.confirm;
    });
    if (confirmed) await _load();
  }

  Future<void> _confirm() async {
    await context.services.sites.accounts.confirm('${_link!.site}');
    if (!mounted) return;
    setState(() => _step = _Step.busy);
    await _load();
  }

  /// The field's games and the account's registrations; the login when
  /// there is no session.
  Future<void> _load() async {
    final session = _session!;
    if (!await session.hasAccount) {
      await _loadMethods();
      if (mounted) setState(() => _step = _Step.login);
      return;
    }
    try {
      final api = SiteApi(session);
      final games = await api.fieldGames(_link!.fieldSlug);
      final mine = await api.mine();
      if (!mounted) return;
      setState(() {
        _games = games;
        _mine = mine;
        _step = _Step.field;
      });
      unawaited(_loadAccountExtras(session));
      final want = _link!.gameId;
      if (want != null && !_openedGame) {
        _openedGame = true;
        final g = games.games.where((x) => x.id == want).firstOrNull;
        if (g == null) {
          setState(() => _error = context.s.t('site.game_gone'));
        } else {
          await _openGame(g);
        }
      }
    } on SiteException catch (e) {
      _fail(e, _Step.login);
    }
  }

  /// What the signed-in account has beside the games: which version of the
  /// privacy notice it was last shown (shown again when it is not the current
  /// one) and whether this is a hosted hub (the chrono link). Neither holds
  /// the field screen back: an older server or a refusal shows nothing.
  Future<void> _loadAccountExtras(SiteSession session) async {
    NoticeState? notice;
    var hosted = false;
    try {
      notice = await PrivacyApi(session).noticeState();
    } on SiteException {
      // not known: no prompt
    }
    try {
      hosted = await HubShareApi(session).state() != null;
    } on SiteException {
      // not known: no screen
    }
    if (mounted) {
      setState(() {
        _noticeState = notice;
        _hosted = hosted;
      });
    }
  }

  void _openPrivacy({bool asks = false}) {
    final session = _session!;
    final c = _noticeState;
    unawaited(
      Navigator.push(
        context,
        MaterialPageRoute<void>(
          builder: (_) => PrivacyNoticeScreen(
            session: session,
            again: asks && c != null && c.needed ? c : null,
            onAcknowledged: (state) {
              if (mounted) setState(() => _noticeState = state);
            },
          ),
        ),
      ),
    );
  }

  /// The notice's reading from the login or the sign-up: what version the
  /// person was shown. Only once it was open can they say they read it.
  void _openLoginPrivacy() {
    unawaited(
      Navigator.push(
        context,
        MaterialPageRoute<void>(
          builder: (_) => PrivacyNoticeScreen(
            session: _session!,
            onShown: (v) {
              if (!mounted) return;
              setState(() {
                _noticeVersion = v;
                _noticeOpened = true;
              });
            },
          ),
        ),
      ),
    );
  }

  /// What the site offers to log in with; the password alone when it does
  /// not say (an older server, or out of reach).
  Future<void> _loadMethods() async {
    final auth = context.services.authOf(_session!);
    var methods = AuthMethods.passwordOnly;
    try {
      methods = await auth.methods();
    } on SiteException {
      // the password form stays
    }
    final passkeys = methods.passkeys && await auth.passkeysAvailable();
    // A new account (social or password) records the notice shown: which
    // version is on offer now.
    String? version;
    if ((methods.oidc.isNotEmpty || methods.passwordLogin) && mounted) {
      try {
        version = (await PrivacyApi(_session!).notice(context.s.code))?.version;
      } on SiteException {
        // none published, or out of reach: no version is sent
      }
    }
    if (mounted) {
      setState(() {
        _methods = methods;
        _passkeys = passkeys;
        _noticeVersion = version ?? _noticeVersion;
        _noticePublished = version != null;
      });
    }
  }

  /// A social login or a passkey: ends in a session like the password does.
  Future<void> _signInWith(Future<String?> Function(SiteAuth auth) how) async {
    final auth = context.services.authOf(_session!);
    setState(() {
      _step = _Step.busy;
      _error = null;
    });
    try {
      await how(auth);
      await _load();
    } on SiteException catch (e) {
      _fail(e, _Step.login);
    } on Object catch (e) {
      if (!mounted) return;
      setState(() {
        _error = accountError(context.s, e);
        _step = _Step.login;
      });
    } finally {
      _waiting = null;
    }
  }

  Future<void> _signInOidc(String provider) => _signInWith(
    (auth) => auth.oidc(
      provider,
      noticeSeen: _noticeSeen,
      ageConfirmed: _age16,
      noticeVersion: _noticeVersion,
      onOpened: (w) {
        if (!mounted) return;
        setState(() {
          _waiting = w;
          _step = _Step.waiting;
        });
      },
    ),
  );

  Future<void> _signInPasskey() => _signInWith((a) => a.passkeyLogin());

  Future<void> _login() async {
    final user = _user.text.trim();
    if (user.isEmpty || _password.text.isEmpty) {
      setState(() => _error = context.s.t('site.need_login'));
      return;
    }
    setState(() {
      _step = _Step.busy;
      _error = null;
    });
    try {
      final step = await _session!.login(user, _password.text);
      _password.clear();
      if (step is TotpNeeded) {
        if (mounted) setState(() => (_totp = step, _step = _Step.totp));
        return;
      }
      await _load();
    } on SiteException catch (e) {
      _fail(e, _Step.login);
    }
  }

  /// Makes an account with a password after the notice was shown (LEG-*), then
  /// logs in with it.
  Future<void> _signup() async {
    final s = context.s;
    final user = _signupUser.text.trim();
    final password = _signupPassword.text;
    if (user.isEmpty || password.isEmpty) {
      setState(() => _error = s.t('site.need_login'));
      return;
    }
    if (!_noticeOpened || !_noticeSeen) {
      setState(() => _error = s.t('site.err.notice_required'));
      return;
    }
    if (!_age16) {
      setState(() => _error = s.t('site.err.age_confirmation_required'));
      return;
    }
    setState(() {
      _step = _Step.busy;
      _error = null;
    });
    try {
      await _session!.register(
        user,
        password,
        email: _signupEmail.text.trim(),
        noticeVersion: _noticeVersion,
      );
      final step = await _session!.login(user, password);
      _signupPassword.clear();
      if (step is TotpNeeded) {
        if (mounted) setState(() => (_totp = step, _step = _Step.totp));
        return;
      }
      await _load();
    } on SiteException catch (e) {
      if (e.code == 'notice_version_changed') {
        // The notice changed after it was opened: read the new one first.
        if (mounted) {
          setState(() {
            _noticeOpened = false;
            _noticeSeen = false;
            _noticeVersion = null;
          });
        }
        unawaited(_loadMethods());
      }
      if (!mounted) return;
      // The account's own words for the code (the password rules), else the
      // site's (`site.err.username_invalid`, `age_confirmation_required`).
      setState(() {
        _error = accountError(s, e);
        _step = _Step.signup;
      });
    }
  }

  Future<void> _sendCode() async {
    setState(() {
      _step = _Step.busy;
      _error = null;
    });
    try {
      await _session!.loginTotp(_totp!, _code.text);
      _code.clear();
      await _load();
    } on SiteException catch (e) {
      // A spent or expired TOTP step needs the password again.
      _fail(e, e.code == 'invalid_code' ? _Step.totp : _Step.login);
    }
  }

  Future<void> _logout() async {
    await _session!.logout();
    if (mounted) setState(() => _step = _Step.login);
  }

  Future<void> _openGame(SiteGame g) async {
    final reg = _mine
        .where((r) => r.scheduledGameId == g.id && r.status != 'cancelled')
        .firstOrNull;
    await Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) => SiteGameScreen(
          session: _session!,
          field: _games!.field,
          game: g,
          registration: reg,
        ),
      ),
    );
    if (mounted && _step == _Step.field) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return Scaffold(
      appBar: AppBar(
        title: Text(_games?.field.name ?? s.t('site.title')),
        actions: [
          if (_step == _Step.field)
            IconButton(
              key: const Key('site-logout'),
              tooltip: s.t('site.logout'),
              icon: const Icon(Icons.logout),
              onPressed: _logout,
            ),
        ],
      ),
      body: Column(
        children: [
          // Outside the list: a refusal stays in view wherever the person
          // has scrolled to (the login has several buttons).
          if (_error != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Notice(
                _error!,
                kind: NoticeKind.error,
                key: const Key('site-error'),
              ),
            ),
          Expanded(
            child: ListView(
              // Each step starts at its top (the login's scroll is not the
              // field's).
              key: ValueKey(_step),
              padding: const EdgeInsets.all(16),
              children: [
                ...switch (_step) {
                  _Step.address => _addressStep(s),
                  _Step.confirm => _confirmStep(s),
                  _Step.login => _loginStep(s),
                  _Step.signup => _signupStep(s),
                  _Step.totp => _totpStep(s),
                  _Step.busy => [
                    const SizedBox(height: 24),
                    const Center(child: CircularProgressIndicator()),
                  ],
                  _Step.waiting => [
                    const SizedBox(height: 24),
                    Text(
                      s.t('site.login_waiting'),
                      key: const Key('site-waiting'),
                    ),
                    const SizedBox(height: 12),
                    OutlinedButton(
                      key: const Key('site-waiting-cancel'),
                      onPressed: () => _waiting?.cancel(),
                      child: Text(s.t('site.login_waiting_cancel')),
                    ),
                  ],
                  _Step.field => _fieldStep(s),
                },
              ],
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _addressStep(Strings s) => [
    Text(s.t('site.intro')),
    const SizedBox(height: 12),
    AddressField(
      fieldKey: const Key('site-address'),
      clearKey: const Key('site-address-clear'),
      controller: _address,
      label: s.t('site.address'),
      hint: 'https://campo.example.pt/f/campo',
    ),
    const SizedBox(height: 8),
    FilledButton(
      key: const Key('site-open'),
      onPressed: () {
        final link = SiteGameLink.parse(_address.text);
        if (link == null) {
          final wrong = wrongCodeMessage(_address.text, CodeKind.siteLink);
          setState(() => _error = s.t(wrong ?? 'site.bad_address'));
          return;
        }
        unawaited(_use(link));
      },
      child: Text(s.t('site.open')),
    ),
    const SizedBox(height: 12),
    OutlinedButton.icon(
      key: const Key('site-tickets'),
      icon: const Icon(Icons.confirmation_number_outlined),
      label: Text(s.t('site.my_tickets')),
      onPressed: () => Navigator.push(
        context,
        MaterialPageRoute<void>(builder: (_) => const KeptTicketsScreen()),
      ),
    ),
  ];

  List<Widget> _confirmStep(Strings s) => [
    Text(
      _link!.host,
      key: const Key('site-host'),
      style: Theme.of(context).textTheme.headlineSmall,
    ),
    const SizedBox(height: 8),
    Text(s.t('site.confirm_text', {'host': _link!.host})),
    const SizedBox(height: 12),
    FilledButton(
      key: const Key('site-confirm'),
      onPressed: _confirm,
      child: Text(s.t('site.confirm')),
    ),
    TextButton(
      onPressed: () => Navigator.maybePop(context),
      child: Text(s.t('common.cancel')),
    ),
  ];

  List<Widget> _loginStep(Strings s) => [
    Text(
      s.t('site.login_at', {'host': _link!.host}),
      style: Theme.of(context).textTheme.titleMedium,
    ),
    const SizedBox(height: 8),
    if (_methods.passwordLogin) ...[
      Text(s.t('site.login_hint')),
      const SizedBox(height: 8),
      TextField(
        key: const Key('site-user'),
        controller: _user,
        autofillHints: const [AutofillHints.username],
        decoration: InputDecoration(labelText: s.t('site.username')),
      ),
      const SizedBox(height: 8),
      TextField(
        key: const Key('site-password'),
        controller: _password,
        obscureText: true,
        autofillHints: const [AutofillHints.password],
        decoration: InputDecoration(labelText: s.t('site.password')),
        onSubmitted: (_) => _login(),
      ),
      const SizedBox(height: 12),
      FilledButton(
        key: const Key('site-login'),
        onPressed: _login,
        child: Text(s.t('site.login')),
      ),
    ],
    if (_passkeys || _methods.oidc.isNotEmpty) ...[
      if (_methods.passwordLogin) ...[
        const SizedBox(height: 16),
        Center(child: Text(s.t('site.login_or'))),
      ],
      const SizedBox(height: 8),
      if (_passkeys)
        OutlinedButton.icon(
          key: const Key('site-login-passkey'),
          icon: const Icon(Icons.key),
          label: Text(s.t('site.login_passkey')),
          onPressed: _signInPasskey,
        ),
      for (final o in _methods.oidc)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: OutlinedButton(
            key: Key('site-login-${o.provider}'),
            onPressed: () => _signInOidc(o.provider),
            child: Text(s.t('site.login_with', {'provider': o.label})),
          ),
        ),
      if (_methods.oidc.isNotEmpty) ...[
        const SizedBox(height: 8),
        Text(
          s.t('site.new_account_hint'),
          style: Theme.of(context).textTheme.bodySmall,
        ),
        ..._noticeAndAgeBoxes(s),
      ],
    ],
    if (_methods.passwordLogin) ...[
      const SizedBox(height: 16),
      OutlinedButton(
        key: const Key('site-signup-open'),
        onPressed: () => setState(() {
          _error = null;
          _step = _Step.signup;
        }),
        child: Text(s.t('site.signup_open')),
      ),
    ],
  ];

  /// The two boxes a new account needs (LEG-*): the privacy notice read (open
  /// only after the notice was opened, so it was shown first) and 16 or older.
  List<Widget> _noticeAndAgeBoxes(Strings s) => [
    Align(
      alignment: AlignmentDirectional.centerStart,
      child: TextButton.icon(
        key: const Key('site-login-privacy'),
        icon: const Icon(Icons.privacy_tip_outlined),
        label: Text(s.t('privacy.read')),
        onPressed: _openLoginPrivacy,
      ),
    ),
    CheckboxListTile(
      key: const Key('site-login-notice'),
      contentPadding: EdgeInsets.zero,
      controlAffinity: ListTileControlAffinity.leading,
      value: _noticeSeen,
      onChanged: _noticeOpened
          ? (v) => setState(() => _noticeSeen = v ?? false)
          : null,
      title: Text(
        s.t('site.login_notice'),
        style: Theme.of(context).textTheme.bodySmall,
      ),
      subtitle: _noticeOpened
          ? null
          : Text(
              s.t('site.login_notice_first'),
              key: const Key('site-login-notice-first'),
            ),
    ),
    CheckboxListTile(
      key: const Key('site-login-age'),
      contentPadding: EdgeInsets.zero,
      controlAffinity: ListTileControlAffinity.leading,
      value: _age16,
      onChanged: (v) => setState(() => _age16 = v ?? false),
      title: Text(
        s.t('site.login_age'),
        style: Theme.of(context).textTheme.bodySmall,
      ),
    ),
  ];

  List<Widget> _signupStep(Strings s) => [
    Text(
      s.t('site.signup_title', {'host': _link!.host}),
      style: Theme.of(context).textTheme.titleMedium,
    ),
    const SizedBox(height: 8),
    Text(s.t('site.signup_intro')),
    const SizedBox(height: 12),
    if (!_noticePublished)
      Notice(
        s.t('site.signup_no_notice'),
        kind: NoticeKind.warning,
        key: const Key('site-signup-no-notice'),
      ),
    TextField(
      key: const Key('site-signup-user'),
      controller: _signupUser,
      autofillHints: const [AutofillHints.newUsername],
      decoration: InputDecoration(labelText: s.t('site.username')),
    ),
    const SizedBox(height: 8),
    TextField(
      key: const Key('site-signup-email'),
      controller: _signupEmail,
      keyboardType: TextInputType.emailAddress,
      autofillHints: const [AutofillHints.email],
      decoration: InputDecoration(labelText: s.t('site.signup_email')),
    ),
    const SizedBox(height: 8),
    TextField(
      key: const Key('site-signup-password'),
      controller: _signupPassword,
      obscureText: true,
      autofillHints: const [AutofillHints.newPassword],
      decoration: InputDecoration(labelText: s.t('site.password')),
      onSubmitted: (_) => _signup(),
    ),
    const SizedBox(height: 8),
    ..._noticeAndAgeBoxes(s),
    const SizedBox(height: 12),
    FilledButton(
      key: const Key('site-signup-create'),
      onPressed: _noticePublished ? _signup : null,
      child: Text(s.t('site.signup_create')),
    ),
    TextButton(
      key: const Key('site-signup-back'),
      onPressed: () => setState(() {
        _error = null;
        _step = _Step.login;
      }),
      child: Text(s.t('common.cancel')),
    ),
  ];

  List<Widget> _totpStep(Strings s) => [
    Text(s.t('site.totp_text')),
    const SizedBox(height: 16),
    TextField(
      key: const Key('site-code'),
      controller: _code,
      keyboardType: TextInputType.number,
      maxLength: 8,
      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
      autofillHints: const [AutofillHints.oneTimeCode],
      decoration: InputDecoration(labelText: s.t('site.code')),
      onSubmitted: (_) => _sendCode(),
    ),
    const SizedBox(height: 12),
    FilledButton(
      key: const Key('site-send-code'),
      onPressed: _sendCode,
      child: Text(s.t('site.login')),
    ),
  ];

  List<Widget> _fieldStep(Strings s) {
    final fg = _games!;
    return [
      Text(
        s.t('site.logged_in', {
          'user': _session!.username ?? '',
          'host': _link!.host,
        }),
        key: const Key('site-logged-in'),
        style: TextStyle(color: Theme.of(context).hintColor),
      ),
      if (_noticeState != null && _noticeState!.needed)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: NoticeBanner(
            state: _noticeState!,
            onOpen: () => _openPrivacy(asks: true),
          ),
        ),
      SectionTitle(s.t('site.games')),
      if (fg.games.isEmpty)
        Notice(s.t('site.no_games'), key: const Key('site-no-games')),
      for (final g in fg.games) _gameTile(s, g),
      const SizedBox(height: 12),
      OutlinedButton.icon(
        key: const Key('site-claim'),
        icon: const Icon(Icons.phonelink_lock),
        label: Text(s.t('site.claim')),
        onPressed: () => Navigator.push(
          context,
          MaterialPageRoute<void>(
            builder: (_) =>
                ClaimPlayerIdScreen(session: _session!, field: fg.field),
          ),
        ),
      ),
      const SizedBox(height: 8),
      OutlinedButton.icon(
        key: const Key('site-tickets'),
        icon: const Icon(Icons.confirmation_number_outlined),
        label: Text(s.t('site.my_tickets')),
        onPressed: () => Navigator.push(
          context,
          MaterialPageRoute<void>(builder: (_) => const KeptTicketsScreen()),
        ),
      ),
      const SizedBox(height: 8),
      OutlinedButton.icon(
        key: const Key('site-account'),
        icon: const Icon(Icons.manage_accounts_outlined),
        label: Text(s.t('site.account')),
        onPressed: () => Navigator.push(
          context,
          MaterialPageRoute<void>(
            builder: (_) => SiteAccountScreen(session: _session!),
          ),
        ),
      ),
      const SizedBox(height: 8),
      OutlinedButton.icon(
        key: const Key('site-privacy'),
        icon: const Icon(Icons.privacy_tip_outlined),
        label: Text(s.t('privacy.read')),
        onPressed: _openPrivacy,
      ),
      if (_hosted) ...[
        const SizedBox(height: 8),
        OutlinedButton.icon(
          key: const Key('site-hub-share'),
          icon: const Icon(Icons.share_outlined),
          label: Text(s.t('hub.open')),
          onPressed: () => Navigator.push(
            context,
            MaterialPageRoute<void>(
              builder: (_) => HubShareScreen(session: _session!),
            ),
          ),
        ),
      ],
      const SizedBox(height: 8),
      OutlinedButton.icon(
        key: const Key('site-history'),
        icon: const Icon(Icons.history),
        label: Text(s.t('history.title')),
        onPressed: () => Navigator.push(
          context,
          MaterialPageRoute<void>(
            builder: (_) => GameHistoryScreen(session: _session!),
          ),
        ),
      ),
    ];
  }

  Widget _gameTile(Strings s, SiteGame g) {
    final reg = _mine
        .where((r) => r.scheduledGameId == g.id && r.status != 'cancelled')
        .firstOrNull;
    final status = g.status == 'cancelled'
        ? s.t('site.cancelled')
        : reg != null
        ? s.t('site.reg.${reg.status}')
        : gameRegistrationText(s, g);
    return Card(
      child: ListTile(
        key: Key('site-game-${g.id}'),
        title: Text(g.title),
        subtitle: Text('${siteMoment(g.startsAt)}\n$status'),
        isThreeLine: true,
        trailing: reg != null
            ? const Icon(Icons.how_to_reg)
            : const Icon(Icons.chevron_right),
        onTap: () => _openGame(g),
      ),
    );
  }
}

/// "Inscrições abertas até …", "esgotado", "fechadas", as the game is.
String gameRegistrationText(Strings s, SiteGame g) {
  if (g.status == 'cancelled') return s.t('site.cancelled');
  if (g.registrationOpen) {
    final left = g.placesLeft;
    final until = s.t('site.open_until', {
      'when': siteMoment(g.closesAt ?? g.startsAt),
    });
    return left == null ? until : '$until · ${s.t('site.left', {'n': left})}';
  }
  return switch (g.registrationState) {
    'not_yet' => s.t('site.opens', {'when': siteMoment(g.opensAt!)}),
    'open' => s.t('site.full'),
    'closed' => s.t('site.closed'),
    _ => s.t('site.no_online'),
  };
}

/// A game: its details, and the registration form (a new one, or the
/// player's own to change or cancel).
class SiteGameScreen extends StatefulWidget {
  const SiteGameScreen({
    required this.session,
    required this.field,
    required this.game,
    this.registration,
    super.key,
  });

  final SiteSession session;
  final SiteField field;
  final SiteGame game;
  final Registration? registration;

  @override
  State<SiteGameScreen> createState() => _SiteGameScreenState();
}

class _SiteGameScreenState extends State<SiteGameScreen> {
  final _name = TextEditingController();
  final _fed = TextEditingController();
  final _apd = ApdInput();
  String? _team;
  final _picked = <String>{};
  Registration? _reg;
  KeptTicket? _ticket;
  String? _error;
  bool _busy = false;

  SiteGame get g => widget.game;
  SiteField get f => widget.field;
  String get _site => '${widget.session.site}';

  @override
  void initState() {
    super.initState();
    final r = widget.registration;
    _reg = r;
    _name.text =
        r?.displayName ??
        AppScope.read(context).settings.displayName ??
        widget.session.username ??
        '';
    _fed.text = r?.federationNumber ?? '';
    _apd.load(
      apd: r?.apdId,
      number: r?.federationNumber,
      expires: r?.membershipExpires,
    );
    _team = r?.teamPreference;
    final services = context.services;
    unawaited(services.checkins.load().then((_) => _pickDeclared()));
    if (r != null) {
      unawaited(
        services.tickets.forRegistration(r.id).then((t) {
          if (mounted) setState(() => _ticket = t);
        }),
      );
    }
  }

  /// Declared before: the same replicas of mine picked again.
  void _pickDeclared() {
    if (!mounted) return;
    final r = _reg;
    setState(() {
      for (final d in r?.replicas ?? const <RegReplica>[]) {
        for (final m in context.services.checkins.replicas) {
          if (m.type == d.type &&
              m.replicaClass == d.replicaClass &&
              (m.makeModel ?? '') == (d.makeModel ?? '')) {
            _picked.add(m.id);
          }
        }
      }
    });
  }

  @override
  void dispose() {
    _name.dispose();
    _fed.dispose();
    _apd.dispose();
    super.dispose();
  }

  bool _fits(MyReplica r) => f.classes.contains(r.replicaClass);

  RegistrationForm? _form() {
    final s = context.s;
    final name = _name.text.trim();
    final rule = f.apd;
    final withApd = apdAsked(rule);
    final fed = withApd ? (_apd.numberOrNull ?? '') : _fed.text.trim();
    if (name.isEmpty) {
      setState(() => _error = s.t('checkin.need_name'));
      return null;
    }
    if (withApd) {
      final bad = _apd.problem(
        rule,
        needNumber: g.federation == 'required' || rule.register,
      );
      if (bad != null) {
        setState(() => _error = s.t(apdKey(bad, f.country)));
        return null;
      }
    }
    if (g.federation == 'required' && fed.isEmpty) {
      setState(
        () => _error = s.t('checkin.need_federation', {
          'label': f.federationLabel,
        }),
      );
      return null;
    }
    final mine = context.services.checkins.replicas;
    final picked = [
      for (final r in mine)
        if (_picked.contains(r.id) && _fits(r))
          RegReplica(
            type: r.type,
            replicaClass: r.replicaClass,
            makeModel: r.makeModel,
          ),
    ];
    if (picked.length > f.maxReplicas) {
      setState(() => _error = s.t('site.too_many', {'n': f.maxReplicas}));
      return null;
    }
    return RegistrationForm(
      displayName: name,
      teamPreference: _team,
      federationNumber: (g.federation == 'off' && !withApd) || fed.isEmpty
          ? null
          : fed,
      apdId: withApd ? _apd.apd : null,
      membershipExpires: withApd ? _apd.expiresOrNull : null,
      replicas: g.predeclareReplicas ? picked : null,
    );
  }

  Future<void> _run(Future<void> Function(SiteApi api) action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action(SiteApi(widget.session));
    } on SiteException catch (e) {
      if (mounted) {
        setState(() => _error = siteError(context.s, e, country: f.country));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Keeps the ticket an answer carries, before anything else.
  Future<KeptTicket?> _keep(Registration r) async {
    final t = KeptTicket.of(_site, r, fieldName: f.name);
    if (t != null) await context.services.tickets.keep(t);
    return t;
  }

  Future<void> _register() async {
    final form = _form();
    if (form == null) return;
    final app = AppScope.read(context);
    await _run((api) async {
      final r = await api.register(f.id, g.id, form);
      final t = await _keep(r);
      await app.update((x) => x.displayName = form.displayName);
      if (!mounted) return;
      setState(() => (_reg = r, _ticket = t));
      if (t != null) await _showTicket(t);
    });
  }

  Future<void> _change() async {
    final form = _form();
    if (form == null) return;
    await _run((api) async {
      final r = await api.change(_reg!.id, form);
      if (!mounted) return;
      setState(() => _reg = r);
      showMessage(context, context.s.t('site.changed'));
    });
  }

  Future<void> _cancel() async {
    final s = context.s;
    final ok = await confirm(
      context,
      title: s.t('site.cancel_title'),
      body: s.t('site.cancel_text', {'game': g.title}),
      yes: s.t('site.cancel_yes'),
    );
    if (!ok || !mounted) return;
    final tickets = context.services.tickets;
    await _run((api) async {
      await api.cancel(_reg!.id);
      await tickets.remove(_reg!.id);
      if (mounted) Navigator.pop(context);
    });
  }

  Future<void> _newTicket() async {
    await _run((api) async {
      final r = await api.newTicket(_reg!.id);
      final t = await _keep(r);
      if (!mounted) return;
      setState(() => _ticket = t);
      if (t != null) await _showTicket(t);
    });
  }

  Future<void> _showTicket(KeptTicket t) => Navigator.push(
    context,
    MaterialPageRoute<void>(builder: (_) => TicketScreen(ticket: t)),
  );

  Future<void> _addReplica() async {
    final store = context.services.checkins;
    final r = await showDialog<MyReplica>(
      context: context,
      builder: (_) => NewReplicaDialog(classes: f.classes),
    );
    if (r == null) return;
    await store.saveReplica(r);
    if (mounted) setState(() => _picked.add(r.id));
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final reg = _reg;
    final editable =
        g.status == 'published' &&
        (reg == null ? g.registrationOpen : g.registrationState == 'open') &&
        (reg == null || reg.live);
    return Scaffold(
      appBar: AppBar(title: Text(g.title)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            '${siteMoment(g.startsAt)} – ${siteMoment(g.endsAt)}',
            key: const Key('reg-when'),
          ),
          if (g.location != null) Text(g.location!),
          if (g.description != null) ...[
            const SizedBox(height: 8),
            Text(g.description!),
          ],
          const SizedBox(height: 8),
          if (g.status == 'cancelled')
            Notice(
              s.t('site.cancelled_reason', {'reason': g.cancelledReason ?? ''}),
              kind: NoticeKind.warning,
            )
          else
            Text(gameRegistrationText(s, g), key: const Key('reg-state')),
          if (reg != null) ...[
            const SizedBox(height: 8),
            Notice(
              s.t('site.reg.${reg.status}'),
              kind: reg.live ? NoticeKind.ok : NoticeKind.info,
              key: const Key('reg-status'),
            ),
            if (reg.live)
              _ticket != null
                  ? FilledButton.icon(
                      key: const Key('reg-ticket'),
                      icon: const Icon(Icons.qr_code_2),
                      label: Text(s.t('site.show_ticket')),
                      onPressed: () => _showTicket(_ticket!),
                    )
                  : Notice(
                      s.t('site.no_ticket_here'),
                      kind: NoticeKind.warning,
                    ),
            if (reg.live && g.status == 'published')
              TextButton(
                key: const Key('reg-new-ticket'),
                onPressed: _busy ? null : _newTicket,
                child: Text(s.t('site.new_ticket')),
              ),
          ],
          if (editable) ..._formFields(s),
          // Next to the button that made it (the list may be scrolled).
          if (_error != null)
            Notice(
              _error!,
              kind: NoticeKind.error,
              key: const Key('reg-error'),
            ),
          if (_busy) ...[
            const SizedBox(height: 12),
            const Center(child: CircularProgressIndicator()),
          ] else if (editable) ...[
            const SizedBox(height: 12),
            FilledButton(
              key: const Key('reg-submit'),
              onPressed: reg == null ? _register : _change,
              child: Text(s.t(reg == null ? 'site.register' : 'site.save')),
            ),
            if (reg != null)
              TextButton(
                key: const Key('reg-cancel'),
                onPressed: _cancel,
                child: Text(s.t('site.cancel_reg')),
              ),
          ],
          if (reg == null && editable) ...[
            const SizedBox(height: 12),
            Text(
              s.t('site.data_note'),
              style: TextStyle(color: Theme.of(context).hintColor),
            ),
          ],
        ],
      ),
    );
  }

  List<Widget> _formFields(Strings s) {
    final mine = context.services.checkins.replicas;
    return [
      SectionTitle(s.t(_reg == null ? 'site.form' : 'site.form_change')),
      const SizedBox(height: 4),
      TextField(
        key: const Key('reg-name'),
        controller: _name,
        maxLength: 32,
        decoration: InputDecoration(
          labelText: s.t('checkin.name'),
          helperText: s.t('site.name_hint'),
          helperMaxLines: 3,
        ),
      ),
      if (apdAsked(f.apd))
        ApdFields(
          input: _apd,
          rule: f.apd,
          country: f.country,
          numberRequired: g.federation == 'required' || f.apd.register,
          keyPrefix: 'reg-apd',
        )
      else if (g.federation != 'off') ...[
        const SizedBox(height: 16),
        TextField(
          key: const Key('reg-federation'),
          controller: _fed,
          maxLength: 32,
          decoration: InputDecoration(
            labelText: s.t(
              g.federation == 'required'
                  ? 'checkin.federation_required'
                  : 'checkin.federation_optional',
              {'label': f.federationLabel},
            ),
          ),
        ),
      ],
      if (g.teams.isNotEmpty) ...[
        const SizedBox(height: 16),
        DropdownButtonFormField<String?>(
          key: const Key('reg-team'),
          initialValue: g.teams.contains(_team) ? _team : null,
          decoration: InputDecoration(labelText: s.t('checkin.team_pref')),
          items: [
            DropdownMenuItem(value: null, child: Text(s.t('checkin.any_team'))),
            for (final t in g.teams)
              DropdownMenuItem(value: t, child: Text(s.team(t))),
          ],
          onChanged: (v) => setState(() => _team = v),
        ),
      ],
      if (g.predeclareReplicas) ...[
        SectionTitle(s.t('site.replicas', {'n': f.maxReplicas})),
        if (mine.isEmpty) Text(s.t('checkin.no_replicas')),
        for (final r in mine)
          CheckboxListTile(
            key: Key('reg-replica-${r.id}'),
            value: _picked.contains(r.id) && _fits(r),
            onChanged: _fits(r)
                ? (v) => setState(
                    () => v == true ? _picked.add(r.id) : _picked.remove(r.id),
                  )
                : null,
            title: Text(replicaLabel(s, r.type, r.makeModel)),
            subtitle: Text(
              _fits(r)
                  ? r.replicaClass
                  : s.t('site.class_not_here', {'class': r.replicaClass}),
            ),
          ),
        if (f.classes.isNotEmpty)
          TextButton.icon(
            key: const Key('reg-add-replica'),
            icon: const Icon(Icons.add),
            label: Text(s.t('declare.add')),
            onPressed: _addReplica,
          ),
      ],
    ];
  }
}

/// A kept check-in ticket, to show at the field: a QR code for a marshal to
/// scan, and the same text.
class TicketScreen extends StatelessWidget {
  const TicketScreen({required this.ticket, super.key});
  final KeptTicket ticket;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final t = ticket;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('site.ticket'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(t.gameTitle, style: Theme.of(context).textTheme.headlineSmall),
          Text(
            [
              t.fieldName,
              if (t.startsAt != null) siteMoment(t.startsAt!),
            ].join(' · '),
          ),
          const SizedBox(height: 16),
          Center(
            child: Container(
              color: Colors.white,
              padding: const EdgeInsets.all(12),
              child: QrCodeView(
                key: const Key('ticket-qr'),
                data: t.ticketText,
                size: 240,
              ),
            ),
          ),
          const SizedBox(height: 16),
          Text(s.t('site.ticket_text')),
          const SizedBox(height: 8),
          SelectableText(
            t.ticketText,
            key: const Key('ticket-text'),
            style: const TextStyle(fontSize: 13),
          ),
          TextButton.icon(
            key: const Key('ticket-copy'),
            icon: const Icon(Icons.copy),
            label: Text(s.t('site.copy')),
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: t.ticketText));
              if (context.mounted) showMessage(context, s.t('site.copied'));
            },
          ),
          const SizedBox(height: 8),
          Notice(s.t('site.ticket_secret'), kind: NoticeKind.warning),
        ],
      ),
    );
  }
}

/// Every ticket the phone keeps (they work without a connection).
class KeptTicketsScreen extends StatefulWidget {
  const KeptTicketsScreen({super.key});

  @override
  State<KeptTicketsScreen> createState() => _KeptTicketsScreenState();
}

class _KeptTicketsScreenState extends State<KeptTicketsScreen> {
  List<KeptTicket>? _all;

  @override
  void initState() {
    super.initState();
    unawaited(
      context.services.tickets.all().then((v) {
        if (mounted) setState(() => _all = v.reversed.toList());
      }),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final all = _all;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('site.my_tickets'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (all == null)
            const Center(child: CircularProgressIndicator())
          else if (all.isEmpty)
            Notice(s.t('site.no_tickets'), key: const Key('tickets-none'))
          else
            for (final t in all)
              Card(
                child: ListTile(
                  key: Key('kept-${t.registrationId}'),
                  leading: const Icon(Icons.confirmation_number_outlined),
                  title: Text(t.gameTitle),
                  subtitle: Text(
                    [
                      t.fieldName,
                      if (t.startsAt != null) siteMoment(t.startsAt!),
                    ].join(' · '),
                  ),
                  onTap: () => Navigator.push(
                    context,
                    MaterialPageRoute<void>(
                      builder: (_) => TicketScreen(ticket: t),
                    ),
                  ),
                ),
              ),
        ],
      ),
    );
  }
}

/// Claim the player id this phone already has at the field (its check-ins
/// there, its chrono records): the phone's id and secret go to the site
/// server once; the field's controller, which kept the secret's hash at the
/// phone's first check-in, confirms it at its next sync (decision S16-4).
class ClaimPlayerIdScreen extends StatefulWidget {
  const ClaimPlayerIdScreen({
    required this.session,
    required this.field,
    super.key,
  });

  final SiteSession session;
  final SiteField field;

  @override
  State<ClaimPlayerIdScreen> createState() => _ClaimPlayerIdScreenState();
}

class _ClaimPlayerIdScreenState extends State<ClaimPlayerIdScreen> {
  List<FieldIdentity>? _ids;
  PlayerIds? _account;
  String? _picked;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    final ids = await FieldIdentities(context.services.store).all();
    try {
      final account = await SiteApi(widget.session).playerIds();
      if (!mounted) return;
      setState(() => (_ids = ids, _account = account));
    } on SiteException catch (e) {
      if (mounted) {
        setState(() => (_ids = ids, _error = siteError(context.s, e)));
      }
    }
  }

  Future<void> _claim() async {
    final id = _ids!.firstWhere((x) => x.fieldId == _picked);
    setState(() => (_busy = true, _error = null));
    try {
      await SiteApi(
        widget.session,
      ).claim(widget.field.id, id.playerId, id.secret);
      await _load();
    } on SiteException catch (e) {
      if (mounted) setState(() => _error = siteError(context.s, e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final ids = _ids;
    final linked = _account?.linked[widget.field.id];
    final claim = _account?.claimStatus(widget.field.id);
    return Scaffold(
      appBar: AppBar(title: Text(s.t('site.claim'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_error != null)
            Notice(
              _error!,
              kind: NoticeKind.error,
              key: const Key('claim-error'),
            ),
          Text(s.t('site.claim_text', {'field': widget.field.name})),
          const SizedBox(height: 12),
          if (linked != null)
            Notice(
              s.t('site.claim_linked', {'id': linked}),
              kind: NoticeKind.ok,
              key: const Key('claim-linked'),
            )
          else if (claim != null)
            Notice(
              s.t('site.claim.$claim'),
              kind: claim == 'refused' ? NoticeKind.warning : NoticeKind.info,
              key: const Key('claim-status'),
            ),
          if (ids == null)
            const Center(child: CircularProgressIndicator())
          else if (ids.isEmpty)
            Notice(s.t('site.claim_none'), key: const Key('claim-none'))
          else if (linked == null) ...[
            SectionTitle(s.t('site.claim_pick')),
            for (final id in ids)
              ListTile(
                key: Key('claim-id-${id.playerId}'),
                leading: Icon(
                  _picked == id.fieldId
                      ? Icons.radio_button_checked
                      : Icons.radio_button_unchecked,
                ),
                title: Text(id.playerId),
                subtitle: Text(s.t('site.claim_at', {'field': id.fieldId})),
                onTap: () => setState(() => _picked = id.fieldId),
              ),
            const SizedBox(height: 12),
            FilledButton(
              key: const Key('claim-send'),
              onPressed: _picked == null || _busy ? null : _claim,
              child: Text(s.t('site.claim_send')),
            ),
          ],
        ],
      ),
    );
  }
}
