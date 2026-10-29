// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Linking a person's accounts at the fields of a hosted hub, for chrono
/// sharing across fields (the site server's SVX-2, api/hub_share.py).
///
/// Only in hosted mode: a single-field server answers 404 `not_hosted` and the
/// app hides the screen ([HubShareApi.state] returns null). `GET
/// /me/hub-share` says whether this account is linked and whether sharing is
/// on; `POST /me/hub-share/code` makes a one-time code (shown once, 15
/// minutes, used once) for another field; `POST /me/hub-share/link` takes
/// the code another field made; `DELETE /me/hub-share` unlinks, and this
/// field's records leave the hub's view. What is shared still needs the
/// person's consent at each field and the field's own switch: the screen
/// says so, and holds no rule of its own.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../l10n/strings.dart';
import '../ui/widgets.dart';
import 'account_screen.dart' show accountError;
import 'site_client.dart';
import 'site_screens.dart' show siteMoment;

/// Where the account's link stands (`GET /me/hub-share`).
final class HubShareState {
  HubShareState(Map<String, Object?> j)
    : linked = j['linked'] == true,
      linkedAt = j['linked_at'] is String
          ? DateTime.tryParse('${j['linked_at']}')
          : null,
      sharing = j['sharing'] == true;

  final bool linked;
  final DateTime? linkedAt;

  /// The records are being shared (linked, consented, the field's switch on).
  final bool sharing;
}

/// A link code (`POST /me/hub-share/code`): shown once.
final class HubShareCode {
  HubShareCode(Map<String, Object?> j)
    : code = '${j['code']}',
      expiresIn = j['expires_in'] is int ? j['expires_in']! as int : 900;

  final String code;
  final int expiresIn;
}

class HubShareApi {
  HubShareApi(this.session);
  final SiteSession session;

  /// The link's state, or null when this is not a hosted hub (404
  /// `not_hosted`, also an older server without the call): then the app
  /// shows nothing.
  Future<HubShareState?> state() async {
    final r = await session.callRaw('GET', '/me/hub-share');
    if (r.status == 404) return null;
    if (!r.ok) throw SiteException(r.status, r.detail);
    return HubShareState(r.json);
  }

  Future<HubShareCode> makeCode() async =>
      HubShareCode(await session.call('POST', '/me/hub-share/code'));

  Future<HubShareState> link(String code) async => HubShareState(
    await session.call('POST', '/me/hub-share/link', body: {'code': code}),
  );

  Future<void> unlink() async {
    final r = await session.callRaw('DELETE', '/me/hub-share');
    if (!r.ok) throw SiteException(r.status, r.detail);
  }
}

/// The words for a refusal of the hub's calls: `hub.e.<code>`, else the
/// account's and the site's general texts.
String hubError(Strings s, Object e) {
  if (e is SiteException && !e.offline) {
    final own = 'hub.e.${e.code}';
    if (s.tOr(own, '') != '') return s.t(own);
  }
  return accountError(s, e);
}

class HubShareScreen extends StatefulWidget {
  const HubShareScreen({required this.session, super.key});

  final SiteSession session;

  @override
  State<HubShareScreen> createState() => _HubShareScreenState();
}

class _HubShareScreenState extends State<HubShareScreen> {
  late final HubShareApi _api = HubShareApi(widget.session);
  final _code = TextEditingController();
  HubShareState? _state;
  HubShareCode? _made;
  bool _loaded = false;
  bool _busy = false;
  String? _error;
  String? _ok;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final st = await _api.state();
      if (!mounted) return;
      setState(() {
        _state = st;
        _loaded = true;
      });
    } on SiteException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = hubError(context.s, e);
        _loaded = true;
      });
    }
  }

  Future<void> _run(Future<void> Function() work, String? done) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _ok = null;
    });
    try {
      await work();
      if (!mounted) return;
      setState(() => _ok = done == null ? null : context.s.t(done));
    } on SiteException catch (e) {
      if (mounted) setState(() => _error = hubError(context.s, e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _makeCode() => _run(() async {
    final c = await _api.makeCode();
    final st = await _api.state();
    if (mounted) {
      setState(() {
        _made = c;
        _state = st;
      });
    }
  }, null);

  Future<void> _link() async {
    final code = _code.text.trim();
    if (code.isEmpty) {
      setState(() => _error = context.s.t('hub.code_needed'));
      return;
    }
    await _run(() async {
      final st = await _api.link(code);
      _code.clear();
      if (mounted) {
        setState(() {
          _state = st;
          _made = null;
        });
      }
    }, 'hub.linked_ok');
  }

  Future<void> _unlink() async {
    final s = context.s;
    if (!await confirm(
      context,
      title: s.t('hub.unlink_confirm'),
      body: s.t('hub.unlink_body'),
      yes: s.t('hub.unlink_yes'),
    )) {
      return;
    }
    await _run(() async {
      await _api.unlink();
      final st = await _api.state();
      if (mounted) {
        setState(() {
          _state = st;
          _made = null;
        });
      }
    }, 'hub.unlinked_ok');
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final st = _state;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('hub.title'))),
      body: !_loaded
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                // Outside the list: a refusal stays in view wherever the
                // person has scrolled to.
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                    child: Notice(
                      _error!,
                      kind: NoticeKind.error,
                      key: const Key('hub-error'),
                    ),
                  ),
                if (_ok != null)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                    child: Notice(
                      _ok!,
                      kind: NoticeKind.ok,
                      key: const Key('hub-ok'),
                    ),
                  ),
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      if (st == null)
                        Notice(
                          s.t('hub.not_hosted'),
                          key: const Key('hub-none'),
                        )
                      else ...[
                        Text(s.t('hub.intro')),
                        const SizedBox(height: 12),
                        Text(
                          st.linked
                              ? s.t('hub.linked', {
                                  'when': st.linkedAt == null
                                      ? ''
                                      : siteMoment(st.linkedAt!),
                                })
                              : s.t('hub.unlinked'),
                          key: const Key('hub-state'),
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        if (st.linked)
                          Text(
                            s.t(
                              st.sharing ? 'hub.sharing_on' : 'hub.sharing_off',
                            ),
                            key: const Key('hub-sharing'),
                          ),
                        const SizedBox(height: 4),
                        Text(
                          s.t('hub.consent_hint'),
                          style: TextStyle(color: Theme.of(context).hintColor),
                        ),
                        SectionTitle(s.t('hub.make_title')),
                        Text(s.t('hub.make_text')),
                        const SizedBox(height: 8),
                        FilledButton(
                          key: const Key('hub-make'),
                          onPressed: _busy ? null : _makeCode,
                          child: Text(s.t('hub.make')),
                        ),
                        if (_made != null) ...[
                          const SizedBox(height: 12),
                          Card(
                            child: Padding(
                              padding: const EdgeInsets.all(12),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  SelectableText(
                                    _made!.code,
                                    key: const Key('hub-code'),
                                    style: Theme.of(context)
                                        .textTheme
                                        .headlineSmall
                                        ?.copyWith(
                                          letterSpacing: 2,
                                          fontWeight: FontWeight.w600,
                                        ),
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    s.t('hub.code_note', {
                                      'minutes': (_made!.expiresIn / 60).ceil(),
                                    }),
                                  ),
                                  TextButton.icon(
                                    key: const Key('hub-copy'),
                                    icon: const Icon(Icons.copy),
                                    label: Text(s.t('hub.copy')),
                                    onPressed: () => unawaited(
                                      Clipboard.setData(
                                        ClipboardData(text: _made!.code),
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ],
                        SectionTitle(s.t('hub.enter_title')),
                        Text(s.t('hub.enter_text')),
                        const SizedBox(height: 8),
                        TextField(
                          key: const Key('hub-enter'),
                          controller: _code,
                          maxLength: 64,
                          autocorrect: false,
                          textCapitalization: TextCapitalization.characters,
                          decoration: InputDecoration(
                            labelText: s.t('hub.enter_label'),
                          ),
                          onSubmitted: (_) => _link(),
                        ),
                        FilledButton(
                          key: const Key('hub-link'),
                          onPressed: _busy ? null : _link,
                          child: Text(s.t('hub.link')),
                        ),
                        if (st.linked) ...[
                          SectionTitle(s.t('hub.unlink_title')),
                          Text(s.t('hub.unlink_text')),
                          const SizedBox(height: 8),
                          OutlinedButton(
                            key: const Key('hub-unlink'),
                            onPressed: _busy ? null : _unlink,
                            child: Text(s.t('hub.unlink')),
                          ),
                        ],
                      ],
                    ],
                  ),
                ),
              ],
            ),
    );
  }
}
