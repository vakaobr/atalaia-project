// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The player's own chrono records at every field, and the consent, per
/// field, to share them with other fields (plan phase 14, ADR-P4-5,
/// decisions S14-5, LEG-20 and APPS-1 to APPS-8).
///
/// [MyChronoScreen] lists the fields where the account holds a player id
/// (`GET /me/chrono`), the field the person came from and any field with a
/// live consent; each has a switch for its consent. Consent is opt-in: the
/// switch is off until the person turns it on and confirms the consent text
/// (`PUT /me/consents/chrono-sharing/{field}`); turning it off withdraws it
/// after a confirmation (`DELETE`). What is shared also needs the other
/// field's consent and both fields' own switch; the screen says so and holds
/// no rule of its own. [MyChronoFieldScreen] shows one field's records as
/// the marshal signed them: replicas, readings, violations. The app keeps
/// nothing: it asks the site each time.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../ui/widgets.dart';
import 'account_screen.dart' show accountError;
import 'privacy_screens.dart' show PrivacyNoticeScreen;
import 'site_api.dart';
import 'site_client.dart';
import 'site_screens.dart' show siteMoment;

/// The words for a refusal of the chrono calls: `mychrono.e.<code>`, else
/// the account's and the site's general texts.
String chronoError(Strings s, Object e) {
  if (e is SiteException && !e.offline) {
    final own = 'mychrono.e.${e.code}';
    if (s.tOr(own, '') != '') return s.t(own);
  }
  return accountError(s, e);
}

/// One row of [MyChronoScreen]: a field, and its records when the account
/// holds a player id there.
final class _FieldRow {
  _FieldRow(this.id, this.name, this.history);
  final String id;
  final String name;
  final MyChronoField? history;
}

class MyChronoScreen extends StatefulWidget {
  const MyChronoScreen({required this.session, this.field, super.key});

  final SiteSession session;

  /// The field the person came from: listed even with no records there, so
  /// the consent can be given before a first chrono check.
  final SiteField? field;

  @override
  State<MyChronoScreen> createState() => _MyChronoScreenState();
}

class _MyChronoScreenState extends State<MyChronoScreen> {
  late final SiteApi _api = SiteApi(widget.session);
  List<MyChronoField>? _history;
  Set<String> _consents = const {};
  String? _error;
  String? _ok;
  String? _busy; // the field whose consent is being changed

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    setState(() {
      _history = null;
      _error = null;
    });
    try {
      final results = await Future.wait<Object>([
        _api.myChrono(),
        _api.chronoSharingConsents(),
      ]);
      if (!mounted) return;
      setState(() {
        _history = results[0] as List<MyChronoField>;
        _consents = results[1] as Set<String>;
      });
    } on SiteException catch (e) {
      if (mounted) setState(() => _error = chronoError(context.s, e));
    }
  }

  List<_FieldRow> _rows(Strings s) {
    final out = <_FieldRow>[
      for (final h in _history ?? const <MyChronoField>[])
        _FieldRow(h.fieldId, h.field, h),
    ];
    final here = widget.field;
    if (here != null && !out.any((r) => r.id == here.id)) {
      out.insert(0, _FieldRow(here.id, here.name, null));
    }
    for (final id in _consents) {
      if (!out.any((r) => r.id == id)) {
        out.add(_FieldRow(id, s.t('mychrono.field_unknown'), null));
      }
    }
    return out;
  }

  Future<void> _switch(_FieldRow row, bool on) async {
    if (_busy != null) return;
    final s = context.s;
    final yes = on
        ? await confirm(
            context,
            title: s.t('mychrono.give_title', {'field': row.name}),
            body: s.t('mychrono.give_body'),
            yes: s.t('mychrono.give_yes'),
          )
        : await confirm(
            context,
            title: s.t('mychrono.withdraw_title', {'field': row.name}),
            body: s.t('mychrono.withdraw_body'),
            yes: s.t('mychrono.withdraw_yes'),
          );
    if (!yes || !mounted) return;
    setState(() {
      _busy = row.id;
      _error = null;
      _ok = null;
    });
    try {
      if (on) {
        await _api.giveChronoSharing(row.id);
      } else {
        await _api.withdrawChronoSharing(row.id);
      }
      // What the server holds now, not what was asked for.
      final consents = await _api.chronoSharingConsents();
      if (!mounted) return;
      setState(() {
        _consents = consents;
        _ok = s.t(on ? 'mychrono.given_ok' : 'mychrono.withdrawn_ok');
      });
    } on SiteException catch (e) {
      if (mounted) setState(() => _error = chronoError(s, e));
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final loaded = _history != null;
    return Scaffold(
      appBar: AppBar(
        title: Text(s.t('mychrono.title')),
        actions: [
          IconButton(
            key: const Key('mychrono-reload'),
            tooltip: s.t('history.reload'),
            icon: const Icon(Icons.refresh),
            onPressed: _busy == null ? _load : null,
          ),
        ],
      ),
      body: Column(
        children: [
          // Outside the list: a refusal stays in view wherever the person
          // has scrolled to.
          if (_error != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Notice(
                _error!,
                kind: NoticeKind.error,
                key: const Key('mychrono-error'),
              ),
            ),
          if (_ok != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Notice(
                _ok!,
                kind: NoticeKind.ok,
                key: const Key('mychrono-ok'),
              ),
            ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(s.t('mychrono.intro')),
                const SizedBox(height: 12),
                if (!loaded && _error == null)
                  const Center(child: CircularProgressIndicator())
                else if (loaded) ...[
                  SectionTitle(s.t('mychrono.sharing_title')),
                  Text(s.t('mychrono.sharing_text')),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: TextButton(
                      key: const Key('mychrono-notice'),
                      onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute<void>(
                          builder: (_) =>
                              PrivacyNoticeScreen(session: widget.session),
                        ),
                      ),
                      child: Text(s.t('privacy.read')),
                    ),
                  ),
                  SectionTitle(s.t('mychrono.fields_title')),
                  if (_rows(s).isEmpty)
                    Notice(
                      s.t('mychrono.none'),
                      key: const Key('mychrono-none'),
                    )
                  else
                    for (final r in _rows(s)) _card(s, r),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _card(Strings s, _FieldRow r) {
    final h = r.history;
    final given = _consents.contains(r.id);
    return Card(
      key: Key('mychrono-field-${r.id}'),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ListTile(
              title: Text(r.name),
              subtitle: Text(
                h == null
                    ? s.t('mychrono.no_player_id')
                    : [
                        s.t('mychrono.player_id', {'id': h.playerId}),
                        s.t('mychrono.readings_n', {'n': h.readings.length}),
                        s.t('mychrono.replicas_n', {'n': h.replicas.length}),
                      ].join(' · '),
              ),
              trailing: h == null ? null : const Icon(Icons.chevron_right),
              onTap: h == null
                  ? null
                  : () => Navigator.push(
                      context,
                      MaterialPageRoute<void>(
                        builder: (_) => MyChronoFieldScreen(h),
                      ),
                    ),
            ),
            SwitchListTile(
              key: Key('mychrono-consent-${r.id}'),
              value: given,
              onChanged: _busy != null ? null : (v) => _switch(r, v),
              title: Text(s.t('mychrono.consent_switch')),
              subtitle: Text(
                s.t(given ? 'mychrono.consent_on' : 'mychrono.consent_off'),
                key: Key('mychrono-consent-state-${r.id}'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// One field's records of the player, newest first.
class MyChronoFieldScreen extends StatelessWidget {
  const MyChronoFieldScreen(this.field, {super.key});
  final MyChronoField field;

  String _replica(Strings s, MyChronoReplica? r) {
    if (r == null) return s.t('mychrono.replica_unknown');
    return [
      s.tOr('replica.type_${r.type}', r.type),
      if (r.replicaClass.isNotEmpty) s.replicaClass(r.replicaClass),
      if (r.makeModel != null && r.makeModel!.isNotEmpty) r.makeModel!,
    ].join(' · ');
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final f = field;
    final readings = f.readings.reversed.toList();
    final violations = f.violations.reversed.toList();
    final refused = f.refused.fold<int>(0, (n, r) => n + r.times);
    return Scaffold(
      appBar: AppBar(title: Text(f.field)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            s.t('mychrono.player_id', {'id': f.playerId}),
            key: const Key('mychrono-head'),
          ),
          const SizedBox(height: 8),
          Text(s.t('mychrono.field_intro')),
          SectionTitle(s.t('mychrono.replicas')),
          if (f.replicas.isEmpty)
            Text(s.t('mychrono.no_replicas'))
          else
            for (final r in f.replicas)
              ListTile(
                key: Key('mychrono-replica-${r.replicaId}'),
                dense: true,
                leading: const Icon(Icons.inventory_2_outlined),
                title: Text(_replica(s, r)),
              ),
          SectionTitle(s.t('mychrono.readings')),
          if (readings.isEmpty)
            Notice(
              s.t('mychrono.no_readings'),
              key: const Key('mychrono-no-readings'),
            )
          else
            for (final r in readings)
              ListTile(
                key: Key('mychrono-reading-${r.readingId}'),
                dense: true,
                title: Text(
                  s.t('mychrono.reading', {
                    'j': s.number(r.energyJ, 2),
                    'mps': s.number(r.velocityMps, 1),
                    'g': s.number(r.bbWeightG, 2),
                  }),
                ),
                subtitle: Text(
                  [
                    s.tOr('mychrono.type.${r.type}', r.type),
                    if (r.timestamp != null) siteMoment(r.timestamp!),
                    _replica(s, f.replica(r.replicaId)),
                  ].join(' · '),
                ),
                trailing: Text(
                  s.tOr('mychrono.outcome.${r.outcome}', r.outcome ?? ''),
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: switch (r.outcome) {
                      'fail' => Theme.of(context).colorScheme.error,
                      _ => null,
                    },
                  ),
                ),
              ),
          SectionTitle(s.t('mychrono.violations')),
          if (violations.isEmpty)
            Text(
              s.t('mychrono.no_violations'),
              key: const Key('mychrono-no-violations'),
            )
          else
            for (final v in violations)
              ListTile(
                key: Key('mychrono-violation-${v.id}'),
                dense: true,
                leading: const Icon(Icons.warning_amber_outlined),
                title: Text(
                  s.tOr(
                    'mychrono.violation.${v.violationType}',
                    v.violationType,
                    {
                      'j': s.number(v.energyJ, 2),
                      'limit': s.number(v.limitJ, 2),
                    },
                  ),
                ),
                subtitle: Text(
                  [
                    if (v.createdAt != null) siteMoment(v.createdAt!),
                    v.outcome == null
                        ? s.t('mychrono.staff.none')
                        : s.tOr('mychrono.staff.${v.outcome}', v.outcome!),
                    if (v.banActive)
                      v.banExpiresAt == null
                          ? s.t('mychrono.ban_active')
                          : s.t('mychrono.ban_until', {
                              'when': siteMoment(v.banExpiresAt!),
                            }),
                  ].join(' · '),
                ),
              ),
          if (refused > 0) ...[
            const SizedBox(height: 12),
            Notice(
              s.t('mychrono.refused', {'n': refused}),
              key: const Key('mychrono-refused'),
            ),
          ],
        ],
      ),
    );
  }
}
