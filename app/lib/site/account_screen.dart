// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The account's login methods on a site server, in the app (decision PKA-1;
/// the staff page's twin, the server's ACC-1 to ACC-8): the social logins
/// (link and unlink), passkeys (add, rename, remove), the password (set,
/// change, remove) and TOTP, and the confirmation a sensitive change asks
/// for.
///
/// The screen holds no rule: it shows what the server says (`GET
/// /me/login-methods`, `GET /auth/methods`) and puts every refusal in words,
/// one text per code (`acct.e.<code>`; a code with no text of its own falls
/// back to the site's general texts). An account with a password sends it with
/// each change (one box at the top); an account with none confirms with a
/// proof from the last ten minutes: a TOTP code, a passkey, or the provider
/// again.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../platform/services.dart';
import '../ui/widgets.dart';
import 'site_auth.dart';
import 'site_client.dart';
import 'site_screens.dart' show siteError, siteMoment;

/// The words for [e]: the account's own text for the code, else the site's.
String accountError(Strings s, Object e) {
  if (e is SiteException) {
    if (e.offline) return s.t('site.err.offline');
    final own = 'acct.e.${e.code}';
    return s.tOr(own, siteError(s, e));
  }
  if (e is PasskeyException) {
    return switch (e.reason) {
      'cancelled' || 'no_credential' => s.t('acct.passkey_cancelled'),
      'unsupported' => s.t('acct.passkey_unsupported'),
      _ => s.t('acct.passkey_failed'),
    };
  }
  if (e is OidcFailure) {
    return s.tOr('acct.oidc.${e.code}', s.t('acct.oidc.other'));
  }
  return s.t('acct.error_generic', {'error': '$e'});
}

class SiteAccountScreen extends StatefulWidget {
  const SiteAccountScreen({required this.session, super.key});

  final SiteSession session;

  @override
  State<SiteAccountScreen> createState() => _SiteAccountScreenState();
}

class _SiteAccountScreenState extends State<SiteAccountScreen> {
  late final SiteAuth _auth = context.services.authOf(widget.session);
  final _confirmPassword = TextEditingController();
  final _confirmCode = TextEditingController();
  final _passkeyName = TextEditingController();
  final _newPassword = TextEditingController();
  final _enrolCode = TextEditingController();
  final _disableCode = TextEditingController();
  AuthMethods _offers = AuthMethods.passwordOnly;
  LoginMethods? _mine;
  bool _passkeys = false;
  bool _busy = false;
  bool _loaded = false;
  TotpEnrolment? _enrolment;
  PendingReturn? _waiting;
  String? _waitingFor;
  String? _error;
  String? _ok;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  @override
  void dispose() {
    _waiting?.cancel();
    for (final c in [
      _confirmPassword,
      _confirmCode,
      _passkeyName,
      _newPassword,
      _enrolCode,
      _disableCode,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final offers = await _auth.methods();
      final mine = await _auth.mine();
      final passkeys = await _auth.passkeysAvailable();
      if (!mounted) return;
      setState(() {
        _offers = offers;
        _mine = mine;
        _passkeys = passkeys && offers.passkeys;
        _loaded = true;
      });
    } on SiteException catch (e) {
      if (mounted) {
        setState(() {
          _error = accountError(context.s, e);
          _loaded = true;
        });
      }
    }
  }

  /// One action at a time: its refusal shown in words; [done] is what to
  /// tell the person when it worked.
  Future<void> _run(Future<void> Function() work, String? done) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _ok = null;
    });
    try {
      await work();
      await _load();
      if (mounted) {
        setState(() => _ok = done == null ? null : context.s.t(done));
      }
    } on Object catch (e) {
      if (mounted) setState(() => _error = accountError(context.s, e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  bool get _hasPassword => _mine?.passwordSet ?? false;

  /// An account with a password sends it with each change.
  bool _needsPassword() {
    if (!_hasPassword || _confirmPassword.text.isNotEmpty) return false;
    setState(() => _error = context.s.t('acct.confirm_password_hint'));
    return true;
  }

  void _clearPassword() => _confirmPassword.clear();

  Future<bool> _sure(String title, String yes) =>
      confirm(context, title: title, yes: yes);

  // --- actions --------------------------------------------------------------

  Future<void> _provider(String provider, String purpose, String done) async {
    if (purpose == 'link' && _needsPassword()) return;
    final label = _offers.oidc
        .followedBy(_mine?.available ?? const [])
        .where((o) => o.provider == provider)
        .map((o) => o.label)
        .firstOrNull;
    await _run(() async {
      try {
        await _auth.oidc(
          provider,
          purpose: purpose,
          password: purpose == 'link' ? _confirmPassword.text : '',
          onOpened: (w) {
            if (!mounted) return;
            setState(() {
              _waiting = w;
              _waitingFor = label ?? provider;
            });
          },
        );
        _clearPassword();
      } finally {
        if (mounted) {
          setState(() {
            _waiting = null;
            _waitingFor = null;
          });
        }
      }
    }, done);
  }

  Future<void> _unlink(LinkedIdentity i) async {
    if (_needsPassword()) return;
    if (!await _sure(
      context.s.t('acct.unlink_confirm', {'provider': i.label}),
      context.s.t('acct.unlink_yes'),
    )) {
      return;
    }
    await _run(() async {
      await _auth.unlink(i.provider, _confirmPassword.text);
      _clearPassword();
    }, 'acct.unlinked');
  }

  Future<void> _addPasskey() async {
    if (_needsPassword()) return;
    await _run(() async {
      await _auth.addPasskey(
        password: _confirmPassword.text,
        name: _passkeyName.text,
      );
      _passkeyName.clear();
      _clearPassword();
    }, 'acct.passkey_added');
  }

  Future<void> _renamePasskey(PasskeyInfo k) async {
    final s = context.s;
    final name = await promptText(
      context,
      title: s.t('acct.rename'),
      label: s.t('acct.passkey_rename_label'),
      maxLength: 64,
      fieldKey: const Key('account-rename-field'),
      actions: [
        (s.t('acct.cancel'), (_) => null, false),
        (s.t('acct.save'), (text) => text.trim(), true),
      ],
    );
    if (name == null || name.isEmpty) return;
    await _run(() => _auth.renamePasskey(k.id, name), 'acct.passkey_renamed');
  }

  Future<void> _removePasskey(PasskeyInfo k) async {
    if (_needsPassword()) return;
    if (!await _sure(
      context.s.t('acct.passkey_remove_confirm', {'name': k.name}),
      context.s.t('acct.remove_confirm_yes'),
    )) {
      return;
    }
    await _run(() async {
      await _auth.removePasskey(k.id, _confirmPassword.text);
      _clearPassword();
    }, 'acct.passkey_removed');
  }

  Future<void> _savePassword() async {
    if (_needsPassword() || _newPassword.text.isEmpty) return;
    await _run(() async {
      await _auth.setPassword(_confirmPassword.text, _newPassword.text);
      _newPassword.clear();
      _clearPassword();
    }, 'acct.pw_changed');
  }

  Future<void> _removePassword() async {
    if (_needsPassword()) return;
    if (!await _sure(
      context.s.t('acct.pw_remove_confirm'),
      context.s.t('acct.pw_remove_yes'),
    )) {
      return;
    }
    await _run(() async {
      await _auth.removePassword(_confirmPassword.text);
      _clearPassword();
    }, 'acct.pw_removed');
  }

  Future<void> _enrolTotp() async {
    if (_needsPassword()) return;
    await _run(() async {
      final e = await _auth.totpEnrol(_confirmPassword.text);
      if (mounted) setState(() => _enrolment = e);
    }, null);
  }

  Future<void> _confirmTotp() async {
    final code = _enrolCode.text.replaceAll(RegExp(r'\s+'), '');
    if (code.isEmpty) return;
    await _run(() async {
      try {
        await _auth.totpConfirm(code);
      } on Object {
        _enrolCode.clear();
        rethrow;
      }
      _enrolCode.clear();
      _clearPassword();
      if (mounted) setState(() => _enrolment = null);
    }, 'acct.totp_enabled');
  }

  Future<void> _disableTotp() async {
    if (_needsPassword()) return;
    final code = _disableCode.text.replaceAll(RegExp(r'\s+'), '');
    if (code.isEmpty) return;
    await _run(() async {
      try {
        await _auth.totpDisable(_confirmPassword.text, code);
      } on Object {
        _disableCode.clear();
        rethrow;
      }
      _disableCode.clear();
      _clearPassword();
    }, 'acct.totp_disabled');
  }

  Future<void> _confirmWithCode() async {
    final code = _confirmCode.text.replaceAll(RegExp(r'\s+'), '');
    if (code.isEmpty) return;
    await _run(() async {
      try {
        await _auth.confirmWithTotp(code);
      } finally {
        _confirmCode.clear();
      }
    }, 'acct.confirmed');
  }

  // --- the page ----------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final mine = _mine;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('acct.title'))),
      body: Column(
        children: [
          // Outside the list: what happened stays in view wherever the
          // person has scrolled to.
          if (_error != null || _ok != null || _waiting != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Column(
                children: [
                  if (_error != null)
                    Notice(
                      _error!,
                      kind: NoticeKind.error,
                      key: const Key('account-error'),
                    ),
                  if (_ok != null)
                    Notice(
                      _ok!,
                      kind: NoticeKind.ok,
                      key: const Key('account-ok'),
                    ),
                  if (_waiting != null) _waitingCard(s),
                ],
              ),
            ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (!_loaded)
                  const Center(child: CircularProgressIndicator())
                else if (mine != null) ...[
                  Text(s.t('acct.intro')),
                  ..._confirm(s, mine),
                  ..._providers(s, mine),
                  ..._passkeySection(s, mine),
                  ..._passwordSection(s, mine),
                  ..._totpSection(s, mine),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _waitingCard(Strings s) => Notice(
    s.t('acct.waiting', {'provider': _waitingFor ?? ''}),
    key: const Key('account-waiting'),
    action: TextButton(
      key: const Key('account-waiting-cancel'),
      onPressed: () => _waiting?.cancel(),
      child: Text(s.t('acct.waiting_cancel')),
    ),
  );

  List<Widget> _confirm(Strings s, LoginMethods m) => [
    SectionTitle(s.t('acct.confirm_title')),
    if (m.passwordSet)
      TextField(
        key: const Key('account-confirm-password'),
        controller: _confirmPassword,
        obscureText: true,
        autofillHints: const [AutofillHints.password],
        decoration: InputDecoration(
          labelText: s.t('acct.confirm_password'),
          helperText: s.t('acct.confirm_password_hint'),
          helperMaxLines: 3,
        ),
      ),
    if (m.stepUpNeeded) ...[
      Text(s.t('acct.stepup_needed'), key: const Key('account-stepup-needed')),
      const SizedBox(height: 8),
    ],
    if (!m.passwordSet || m.stepUpNeeded) ...[
      if (!m.passwordSet) ...[
        Text(s.t('acct.confirm_recent')),
        const SizedBox(height: 8),
      ],
      if (m.totpEnabled) ...[
        TextField(
          key: const Key('account-confirm-code'),
          controller: _confirmCode,
          keyboardType: TextInputType.number,
          maxLength: 8,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          decoration: InputDecoration(labelText: s.t('acct.confirm_code')),
          onSubmitted: (_) => _confirmWithCode(),
        ),
        OutlinedButton(
          key: const Key('account-confirm-code-button'),
          onPressed: _busy ? null : _confirmWithCode,
          child: Text(s.t('acct.confirm_code_button')),
        ),
      ],
      if (_passkeys && m.passkeys.isNotEmpty)
        OutlinedButton(
          key: const Key('account-confirm-passkey'),
          onPressed: _busy
              ? null
              : () => _run(_auth.confirmWithPasskey, 'acct.confirmed'),
          child: Text(s.t('acct.confirm_passkey')),
        ),
      // A provider login confirms, but is not a second factor.
      if (!m.stepUpNeeded)
        for (final i in m.identities)
          if (_offered(m, i.provider))
            OutlinedButton(
              key: Key('account-reauth-${i.provider}'),
              onPressed: _busy
                  ? null
                  : () => _provider(i.provider, 'reauth', 'acct.reauthed'),
              child: Text(s.t('acct.confirm_with', {'provider': i.label})),
            ),
    ],
  ];

  bool _offered(LoginMethods m, String provider) =>
      m.available.any((o) => o.provider == provider) ||
      _offers.oidc.any((o) => o.provider == provider);

  List<Widget> _providers(Strings s, LoginMethods m) {
    final offered = m.available.isNotEmpty ? m.available : _offers.oidc;
    return [
      SectionTitle(s.t('acct.providers_title')),
      if (offered.isEmpty)
        Text(s.t('acct.providers_off'), key: const Key('account-providers-off'))
      else if (m.identities.isEmpty)
        Text(s.t('acct.providers_none')),
      for (final i in m.identities)
        Card(
          key: Key('account-identity-${i.provider}'),
          child: ListTile(
            title: Text(i.label),
            subtitle: Text(
              [
                if (i.linkedAt != null)
                  s.t('acct.provider_linked_at', {
                    'when': siteMoment(i.linkedAt!),
                  }),
                if (i.lastLoginAt != null)
                  s.t('acct.provider_last_login', {
                    'when': siteMoment(i.lastLoginAt!),
                  }),
              ].join(' · '),
            ),
            trailing: TextButton(
              key: Key('account-unlink-${i.provider}'),
              onPressed: _busy ? null : () => _unlink(i),
              child: Text(s.t('acct.unlink')),
            ),
          ),
        ),
      for (final o in offered)
        if (!m.identities.any((i) => i.provider == o.provider))
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton(
              key: Key('account-link-${o.provider}'),
              onPressed: _busy
                  ? null
                  : () => _provider(o.provider, 'link', 'acct.linked'),
              child: Text(s.t('acct.link', {'provider': o.label})),
            ),
          ),
    ];
  }

  List<Widget> _passkeySection(Strings s, LoginMethods m) => [
    SectionTitle(s.t('acct.passkeys_title')),
    Text(s.t('acct.passkeys_intro')),
    if (m.passkeys.isEmpty) Text(s.t('acct.passkeys_none')),
    for (final k in m.passkeys)
      Card(
        key: Key('account-passkey-${k.id}'),
        child: ListTile(
          title: Text(k.name),
          subtitle: Text(
            [
              k.backedUp
                  ? s.t('acct.passkey_synced')
                  : s.t('acct.passkey_device'),
              if (k.createdAt != null)
                s.t('acct.passkey_created', {'when': siteMoment(k.createdAt!)}),
              k.lastUsedAt != null
                  ? s.t('acct.passkey_used', {
                      'when': siteMoment(k.lastUsedAt!),
                    })
                  : s.t('acct.passkey_unused'),
            ].join(' · '),
          ),
          trailing: Wrap(
            children: [
              IconButton(
                key: Key('account-passkey-rename-${k.id}'),
                tooltip: s.t('acct.rename'),
                icon: const Icon(Icons.edit_outlined),
                onPressed: _busy ? null : () => _renamePasskey(k),
              ),
              IconButton(
                key: Key('account-passkey-remove-${k.id}'),
                tooltip: s.t('acct.passkey_remove'),
                icon: const Icon(Icons.delete_outline),
                onPressed: _busy ? null : () => _removePasskey(k),
              ),
            ],
          ),
        ),
      ),
    if (!_passkeys)
      Text(
        s.t('acct.passkey_unsupported'),
        key: const Key('account-passkey-unsupported'),
      )
    else ...[
      TextField(
        key: const Key('account-passkey-name'),
        controller: _passkeyName,
        maxLength: 64,
        decoration: InputDecoration(labelText: s.t('acct.passkey_name_hint')),
      ),
      Align(
        alignment: Alignment.centerLeft,
        child: OutlinedButton(
          key: const Key('account-passkey-add'),
          onPressed: _busy ? null : _addPasskey,
          child: Text(s.t('acct.passkey_add')),
        ),
      ),
    ],
  ];

  List<Widget> _passwordSection(Strings s, LoginMethods m) => [
    SectionTitle(s.t('acct.pw_title')),
    Text(
      m.passwordSet ? s.t('acct.pw_state_set') : s.t('acct.pw_state_none'),
      key: const Key('account-password-state'),
    ),
    if (!_offers.passwordLogin)
      Text(s.t('acct.pw_off'), key: const Key('account-password-off'))
    else ...[
      TextField(
        key: const Key('account-new-password'),
        controller: _newPassword,
        obscureText: true,
        autofillHints: const [AutofillHints.newPassword],
        decoration: InputDecoration(labelText: s.t('acct.pw_new')),
      ),
      Align(
        alignment: Alignment.centerLeft,
        child: OutlinedButton(
          key: const Key('account-password-save'),
          onPressed: _busy ? null : _savePassword,
          child: Text(
            m.passwordSet
                ? s.t('acct.pw_change_button')
                : s.t('acct.pw_set_button'),
          ),
        ),
      ),
    ],
    if (m.passwordSet)
      Align(
        alignment: Alignment.centerLeft,
        child: TextButton(
          key: const Key('account-password-remove'),
          onPressed: _busy ? null : _removePassword,
          child: Text(s.t('acct.pw_remove')),
        ),
      ),
  ];

  List<Widget> _totpSection(Strings s, LoginMethods m) {
    final e = _enrolment;
    return [
      SectionTitle(s.t('acct.totp_title')),
      Text(
        m.totpEnabled ? s.t('acct.totp_on') : s.t('acct.totp_off'),
        key: const Key('account-totp-state'),
      ),
      if (!m.totpEnabled && e == null)
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton(
            key: const Key('account-totp-enable'),
            onPressed: _busy ? null : _enrolTotp,
            child: Text(s.t('acct.totp_enable')),
          ),
        ),
      if (!m.totpEnabled && e != null) ...[
        Text(
          s.t('acct.totp_enrol_intro', {'digits': e.digits, 's': e.periodS}),
        ),
        _copyable(s, s.t('acct.totp_secret'), e.secret, 'secret'),
        _copyable(s, s.t('acct.totp_uri'), e.uri, 'uri'),
        TextField(
          key: const Key('account-totp-enrol-code'),
          controller: _enrolCode,
          keyboardType: TextInputType.number,
          maxLength: 8,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          decoration: InputDecoration(labelText: s.t('acct.code')),
          onSubmitted: (_) => _confirmTotp(),
        ),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton(
            key: const Key('account-totp-confirm'),
            onPressed: _busy ? null : _confirmTotp,
            child: Text(s.t('acct.totp_confirm')),
          ),
        ),
      ],
      if (m.totpEnabled) ...[
        Text(s.t('acct.totp_disable_intro')),
        TextField(
          key: const Key('account-totp-disable-code'),
          controller: _disableCode,
          keyboardType: TextInputType.number,
          maxLength: 8,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          decoration: InputDecoration(labelText: s.t('acct.code')),
        ),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton(
            key: const Key('account-totp-disable'),
            onPressed: _busy ? null : _disableTotp,
            child: Text(s.t('acct.totp_disable')),
          ),
        ),
      ],
    ];
  }

  Widget _copyable(Strings s, String label, String value, String key) =>
      Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, style: Theme.of(context).textTheme.labelMedium),
                  SelectableText(
                    value,
                    key: Key('account-totp-$key'),
                    style: const TextStyle(fontFamily: 'monospace'),
                  ),
                ],
              ),
            ),
            IconButton(
              tooltip: s.t('acct.copy'),
              icon: const Icon(Icons.copy),
              onPressed: () => Clipboard.setData(ClipboardData(text: value)),
            ),
          ],
        ),
      );
}
