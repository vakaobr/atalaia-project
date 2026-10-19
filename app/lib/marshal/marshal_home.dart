// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The marshal's tools: who the marshal is (name, id, the Ed25519 key that
/// signs their chrono records), the chrono check-in, the replica registry,
/// writing players' tags, and erasing a player's readings on request; and
/// (plan phase E) the field's "replicas to chrono" list, once the marshal has
/// checked in at the field and the GM has given them the marshal role.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../app.dart';
import '../checkin/checkin_screen.dart';
import '../chrono/chrono_ui.dart';
import '../chrono/replica_registry_ui.dart';
import '../l10n/strings.dart';
import '../security/bytes.dart';
import '../ui/widgets.dart';
import 'chrono_queue.dart';
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

  @override
  void initState() {
    super.initState();
    final app = AppScope.read(context);
    records =
        widget.records ?? MarshalRecords(app.services.store, app.settings);
    if (widget.records == null) unawaited(records.load());
  }

  @override
  void dispose() {
    if (widget.records == null) records.dispose();
    super.dispose();
  }

  void _go(Widget screen) =>
      Navigator.push(context, MaterialPageRoute<void>(builder: (_) => screen));

  /// The field's list needs a marshal's check-in; without one, check in first.
  Future<void> _queue() async {
    final services = context.services;
    await services.checkins.load();
    final c = services.checkins.checkins.reversed
        .where((x) => x.staff)
        .firstOrNull;
    final field = c == null ? null : await services.trust.known(c.fieldId);
    if (!mounted) return;
    if (c == null || field == null) {
      final s = context.s;
      await showDialog<void>(
        context: context,
        builder: (_) => AlertDialog(
          content: Text(s.t('queue.check_in_first')),
          actions: [
            FilledButton(
              key: const Key('queue-go-checkin'),
              onPressed: () {
                Navigator.pop(context);
                _go(const CheckinScreen());
              },
              child: Text(s.t('player.checkin')),
            ),
          ],
        ),
      );
      return;
    }
    _go(ChronoQueueScreen(checkin: c, field: field, records: records));
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('role.marshal'))),
      body: ListenableBuilder(
        listenable: Listenable.merge([records, context.app]),
        builder: (context, _) {
          final st = context.app.settings;
          final key = records.publicKey;
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (!records.hasIdentity)
                Notice(s.t('marshal.no_identity'), kind: NoticeKind.warning),
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
                  onTap: () => _go(ChronoScreen(records: records)),
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
                fieldKey: 'marshal-name',
                label: s.t('marshal.name'),
                value: st.marshalName,
                onSaved: (v) =>
                    context.app.update((x) => x.marshalName = v.trim()),
              ),
              _Field(
                fieldKey: 'marshal-id',
                label: s.t('marshal.id'),
                value: st.marshalId,
                onSaved: (v) =>
                    context.app.update((x) => x.marshalId = v.trim()),
              ),
              _Field(
                fieldKey: 'marshal-field',
                label: s.t('marshal.field_id'),
                value: st.fieldId,
                onSaved: (v) => context.app.update((x) => x.fieldId = v.trim()),
              ),
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
                    await records.newKey();
                  },
                  child: Text(
                    s.t(key == null ? 'marshal.make_key' : 'marshal.new_key'),
                  ),
                ),
              ),
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
