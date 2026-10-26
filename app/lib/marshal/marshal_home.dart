// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The marshal's tools: who the marshal is (the id and name the GM's list
/// gave them, the Ed25519 key that signs their chrono records), the chrono
/// check-in, the replica registry, writing players' tags, and erasing a
/// player's readings on request; and (plan phase E) the field's "replicas to
/// chrono" list, once the marshal has checked in at the field and the GM has
/// given them the marshal role.
///
/// The tools open only once the field controller has confirmed this phone as
/// a marshal on the GM's list (decisions MR-1 to MR-14, marshal_access.dart):
/// asked on every opening, and remembered for two hours when the controller
/// cannot be reached.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../app.dart';
import '../checkin/checkin_client.dart';
import '../checkin/checkin_screen.dart';
import '../checkin/field_trust.dart';
import '../checkin/my_replicas.dart';
import '../chrono/chrono_ui.dart';
import '../chrono/replica_registry_ui.dart';
import '../l10n/strings.dart';
import '../security/bytes.dart';
import '../ui/widgets.dart';
import 'chrono_queue.dart';
import 'marshal_access.dart';
import 'marshal_records.dart';
import 'tag_writer.dart';

class MarshalHomeScreen extends StatefulWidget {
  const MarshalHomeScreen({this.records, super.key});

  /// Records to show (tests); otherwise loaded from the app's storage.
  final MarshalRecords? records;

  @override
  State<MarshalHomeScreen> createState() => _MarshalHomeScreenState();
}

class _MarshalHomeScreenState extends State<MarshalHomeScreen> {
  late final MarshalRecords records;
  late final MarshalAccess access;
  FieldCheckin? _checkin;
  PinnedField? _field;
  Timer? _renew;
  bool _validating = false;

  @override
  void initState() {
    super.initState();
    final app = AppScope.read(context);
    records =
        widget.records ?? MarshalRecords(app.services.store, app.settings);
    access = MarshalAccess(
      settings: app.settings,
      records: records,
      persist: () => app.update((_) {}),
    );
    unawaited(_open());
    _renew = Timer.periodic(
      renewEvery,
      (_) => unawaited(_validate(quiet: true)),
    );
  }

  @override
  void dispose() {
    _renew?.cancel();
    access.dispose();
    if (widget.records == null) records.dispose();
    super.dispose();
  }

  Future<void> _open() async {
    if (widget.records == null) await records.load();
    await _validate();
  }

  /// Asks the field controller whether this phone is a marshal on its list
  /// (MR-2). The check-in is the newest this phone has: its token says who
  /// to ask about, and the controller answers with the player's role now.
  Future<void> _validate({bool quiet = false}) async {
    if (_validating) return;
    _validating = true;
    try {
      await _ask(quiet: quiet);
    } finally {
      _validating = false;
    }
  }

  Future<void> _ask({required bool quiet}) async {
    final services = context.services;
    await services.checkins.load();
    final c = services.checkins.checkins.lastOrNull;
    final field = c == null ? null : await services.trust.known(c.fieldId);
    if (!mounted) return;
    if (c == null || field == null) {
      access.noCheckin();
      return;
    }
    _checkin = c;
    _field = field;
    await access.validate(
      CheckinClient(services.fieldHttp(field)),
      c,
      saveCheckin: () => services.checkins.saveCheckin(c),
      quiet: quiet,
    );
  }

  Future<void> _go(Widget screen) =>
      Navigator.push(context, MaterialPageRoute<void>(builder: (_) => screen));

  /// The field's list, for a confirmed marshal.
  void _queue() {
    final c = _checkin;
    final field = _field;
    if (c == null || field == null || !access.allowed) return;
    _go(ChronoQueueScreen(checkin: c, field: field, records: records));
  }

  /// The chrono screen, asking the field controller which limits it judges
  /// with when this phone knows the field.
  void _chrono() {
    final field = _field;
    final services = context.services;
    _go(
      ChronoScreen(
        records: records,
        fieldInfo: field == null
            ? null
            : () => CheckinClient(services.fieldHttp(field)).info(),
      ),
    );
  }

  String _when(int ms) {
    final d = DateTime.fromMillisecondsSinceEpoch(ms);
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(d.day)}.${two(d.month)} ${two(d.hour)}:${two(d.minute)}';
  }

  /// What the controller's answer means for this marshal, in words; null
  /// when it is a plain yes.
  Widget? _status(Strings s) {
    final v = access.validation;
    switch (access.status) {
      case MarshalStatus.checking:
        return Notice(
          s.t('marshal.checking'),
          key: const Key('marshal-status'),
        );
      case MarshalStatus.validated:
        return null;
      case MarshalStatus.validatedOffline:
        return Notice(
          s.t('marshal.offline_ok', {
            'id': v?.marshalId ?? '',
            'at': _when(v?.validatedAtMs ?? 0),
            'until': _when(v?.validUntilMs ?? 0),
          }),
          key: const Key('marshal-status'),
        );
      case MarshalStatus.notListed:
        return _blocked(s, 'marshal.not_listed');
      case MarshalStatus.revoked:
        return _blocked(
          s,
          'marshal.revoked',
          args: {'n': records.unsentSeries().length},
        );
      case MarshalStatus.offlineNeverValidated:
        return _blocked(s, 'marshal.offline_never');
      case MarshalStatus.offlineExpired:
        return _blocked(
          s,
          'marshal.offline_expired',
          args: {'at': _when(v?.validatedAtMs ?? 0)},
        );
      case MarshalStatus.noCheckin:
        return _blocked(s, 'queue.check_in_first', checkIn: true);
      case MarshalStatus.sessionExpired:
        return _blocked(s, 'checkin.expired', checkIn: true);
      case MarshalStatus.error:
        return _blocked(
          s,
          'checkin.error',
          args: {'error': access.error ?? ''},
        );
    }
  }

  Widget _blocked(
    Strings s,
    String key, {
    Map<String, Object?> args = const {},
    bool checkIn = false,
  }) => Notice(
    s.t(key, args),
    kind: NoticeKind.warning,
    key: const Key('marshal-status'),
    action: Wrap(
      spacing: 8,
      children: [
        TextButton(
          key: const Key('marshal-retry'),
          onPressed: _validate,
          child: Text(s.t('marshal.retry')),
        ),
        if (checkIn)
          TextButton(
            key: const Key('queue-go-checkin'),
            onPressed: () async {
              await _go(const CheckinScreen());
              if (mounted) await _validate();
            },
            child: Text(s.t('player.checkin')),
          ),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('role.marshal'))),
      body: ListenableBuilder(
        listenable: Listenable.merge([records, context.app, access]),
        builder: (context, _) {
          final st = context.app.settings;
          final key = records.publicKey;
          final allowed = access.allowed && records.hasIdentity;
          final status = _status(s);
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              ?status,
              if (allowed)
                Card(
                  child: ListTile(
                    key: const Key('marshal-who'),
                    leading: const Icon(Icons.badge, size: 32),
                    title: Text(
                      s.t('marshal.you_are', {
                        'id': st.marshalId,
                        'name': st.marshalName,
                      }),
                    ),
                    subtitle: Text(s.t('marshal.id_from_gm')),
                  ),
                ),
              if (allowed) ...[
                Card(
                  child: ListTile(
                    key: const Key('marshal-queue'),
                    leading: const Icon(Icons.fact_check, size: 32),
                    title: Text(s.t('queue.title')),
                    subtitle: Text(s.t('queue.hint')),
                    onTap: _queue,
                  ),
                ),
                Card(
                  child: ListTile(
                    key: const Key('marshal-chrono'),
                    leading: const Icon(Icons.speed, size: 32),
                    title: Text(s.t('chrono.title')),
                    subtitle: Text(s.t('chrono.hint')),
                    onTap: _chrono,
                  ),
                ),
                Card(
                  child: ListTile(
                    key: const Key('marshal-replicas'),
                    leading: const Icon(Icons.inventory_2, size: 32),
                    title: Text(s.t('replica.title')),
                    subtitle: Text(
                      s.t('replica.count', {'n': records.replicas.length}),
                    ),
                    onTap: () => _go(ReplicaRegistryScreen(records: records)),
                  ),
                ),
                Card(
                  child: ListTile(
                    key: const Key('marshal-tags'),
                    leading: const Icon(Icons.nfc, size: 32),
                    title: Text(s.t('tags.title')),
                    subtitle: Text(s.t('tags.hint')),
                    onTap: () => _go(const TagWriterScreen()),
                  ),
                ),
                SectionTitle(s.t('marshal.identity')),
                _Field(
                  fieldKey: 'marshal-chrono-id',
                  label: s.t('marshal.chrono_id'),
                  value: st.chronoId,
                  onSaved: (v) =>
                      context.app.update((x) => x.chronoId = v.trim()),
                ),
                ListTile(
                  key: const Key('marshal-key'),
                  leading: const Icon(Icons.key),
                  title: Text(s.t('marshal.key')),
                  subtitle: Text(
                    key == null
                        ? s.t('marshal.no_key')
                        : s.t('marshal.key_id', {
                            'id': hexEncode(key).substring(0, 16),
                          }),
                  ),
                  trailing: TextButton(
                    onPressed: () async {
                      if (key != null &&
                          !await confirm(
                            context,
                            title: s.t('marshal.new_key'),
                            body: s.t('marshal.new_key_body'),
                            yes: s.t('marshal.new_key'),
                          )) {
                        return;
                      }
                      // The controller then holds the old key until it is told this one.
                      await records.newKey();
                      await _validate();
                    },
                    child: Text(s.t('marshal.new_key')),
                  ),
                ),
              ],
              SectionTitle(s.t('marshal.records')),
              Text(s.t('marshal.readings', {'n': records.readings.length})),
              TextButton.icon(
                icon: const Icon(Icons.delete_outline),
                label: Text(s.t('marshal.erase')),
                onPressed: () => _erase(context),
              ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _erase(BuildContext context) async {
    final s = context.s;
    final player = await promptText(
      context,
      title: s.t('marshal.erase'),
      label: s.t('tags.player'),
      actions: [
        (s.t('common.cancel'), (_) => null, false),
        (s.t('marshal.erase_do'), (t) => t.trim(), true),
      ],
    );
    if (player != null && player.isNotEmpty) await records.erasePlayer(player);
  }
}

class _Field extends StatefulWidget {
  const _Field({
    required this.fieldKey,
    required this.label,
    required this.value,
    required this.onSaved,
  });

  final String fieldKey;
  final String label;
  final String value;
  final void Function(String v) onSaved;

  @override
  State<_Field> createState() => _FieldState();
}

class _FieldState extends State<_Field> {
  late final _ctl = TextEditingController(text: widget.value);

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Focus(
      onFocusChange: (f) {
        if (!f && _ctl.text != widget.value) widget.onSaved(_ctl.text);
      },
      child: TextField(
        key: Key(widget.fieldKey),
        controller: _ctl,
        decoration: InputDecoration(labelText: widget.label),
        onSubmitted: widget.onSaved,
      ),
    ),
  );
}
