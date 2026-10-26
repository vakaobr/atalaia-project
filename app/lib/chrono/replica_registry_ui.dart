// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The field's replica registry (ADR-P3-7): each replica's owner, type,
/// class (which picks its limit), make and model, and its NFC sticker or QR
/// label, read with the phone so the chrono screen finds it by a tap.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../marshal/marshal_records.dart';
import '../platform/services.dart';
import '../ui/code_kind.dart';
import '../ui/widgets.dart';
import 'chrono_ui.dart';
import 'limit_template.dart';
import 'reading.dart';
import 'replica.dart';

class ReplicaRegistryScreen extends StatelessWidget {
  const ReplicaRegistryScreen({required this.records, super.key});
  final MarshalRecords records;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('replica.title'))),
      floatingActionButton: FloatingActionButton.extended(
        key: const Key('replica-add'),
        icon: const Icon(Icons.add),
        label: Text(s.t('replica.add')),
        onPressed: () => Navigator.push(
          context,
          MaterialPageRoute<void>(
            builder: (_) => ReplicaFormScreen(records: records),
          ),
        ),
      ),
      body: ListenableBuilder(
        listenable: records,
        builder: (context, _) => records.replicas.isEmpty
            ? Center(child: Text(s.t('replica.none')))
            : ListView(
                children: [
                  for (final r in records.replicas)
                    ListTile(
                      leading: Icon(
                        r.tagType == TagType.nfc ? Icons.nfc : Icons.qr_code,
                      ),
                      title: Text(
                        '${r.ownerPlayerId} · ${r.makeModel ?? s.t('replica.type_${r.type.wire}')}',
                      ),
                      subtitle: Text(
                        '${s.t('replica.type_${r.type.wire}')} · ${r.replicaClass} · ${r.tagUid}',
                      ),
                    ),
                ],
              ),
      ),
    );
  }
}

class ReplicaFormScreen extends StatefulWidget {
  const ReplicaFormScreen({required this.records, this.templates, super.key});

  final MarshalRecords records;
  final List<LimitTemplate>? templates;

  @override
  State<ReplicaFormScreen> createState() => _ReplicaFormScreenState();
}

class _ReplicaFormScreenState extends State<ReplicaFormScreen> {
  final _owner = TextEditingController();
  final _model = TextEditingController();
  ReplicaType _type = ReplicaType.aeg;
  String? _class;
  List<String> _classes = const [];
  TagType? _tagType;
  String? _tagUid;
  String? _error;
  StreamSubscription<NfcRead>? _tags;
  late final NfcService _nfc = context.services.nfc;
  bool _nfcOn = false;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    final ts = widget.templates ?? await loadLimitTemplates();
    if (!mounted) return;
    final want = AppScope.read(context).settings.limitTemplate;
    final t = ts.firstWhere((t) => t.id == want, orElse: () => ts.first);
    setState(() {
      _classes = t.classes.keys.toList();
      _class = _classes.isEmpty ? null : _classes.first;
    });
    if (await _nfc.state() == NfcState.ready) {
      _tags = _nfc.reads.listen(
        (r) => setState(() {
          _tagType = TagType.nfc;
          _tagUid = Replica.nfcUid(r.uid);
        }),
      );
      await _nfc.startReading();
      _nfcOn = true;
    }
  }

  @override
  void dispose() {
    unawaited(_tags?.cancel());
    if (_nfcOn) unawaited(_nfc.stopReading());
    _owner.dispose();
    _model.dispose();
    super.dispose();
  }

  Future<void> _scan() async {
    final s = context.s;
    final text = await context.services.qr.scan(
      hint: s.t('replica.scan_hint'),
      cancel: s.t('common.cancel'),
    );
    if (text == null || !mounted) return;
    final wrong = classifyCode(text)?.messageKey;
    if (wrong != null) {
      setState(() => _error = wrong);
      return;
    }
    setState(() {
      _error = null;
      _tagType = TagType.qr;
      _tagUid = text.trim();
    });
  }

  Future<void> _save() async {
    final c = _class;
    final type = _tagType;
    final uid = _tagUid;
    if (c == null || type == null || uid == null) {
      setState(() => _error = 'replica.needs_tag');
      return;
    }
    try {
      final r = Replica(
        replicaId: newUuid(),
        ownerPlayerId: _owner.text.trim(),
        type: _type,
        replicaClass: c,
        makeModel: _model.text.trim().isEmpty ? null : _model.text.trim(),
        registeredAt: formatTimestamp(DateTime.now()),
        tagType: type,
        tagUid: uid,
      );
      await widget.records.addReplica(r);
      if (mounted) Navigator.pop(context);
    } on ChronoFormatException catch (e) {
      setState(() => _error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('replica.add'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_error != null)
            Notice(
              _error!.startsWith('replica.') || _error!.startsWith('code.')
                  ? s.t(_error!)
                  : _error!,
              kind: NoticeKind.error,
            ),
          TextField(
            key: const Key('replica-owner'),
            controller: _owner,
            decoration: InputDecoration(
              labelText: s.t('replica.owner'),
              helperText: s.t('tags.player_hint'),
              helperMaxLines: 3,
            ),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<ReplicaType>(
            initialValue: _type,
            decoration: InputDecoration(labelText: s.t('replica.type')),
            items: [
              for (final t in ReplicaType.values)
                DropdownMenuItem(
                  value: t,
                  child: Text(s.t('replica.type_${t.wire}')),
                ),
            ],
            onChanged: (t) => setState(() => _type = t ?? _type),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _class,
            decoration: InputDecoration(labelText: s.t('replica.class')),
            items: [
              for (final c in _classes)
                DropdownMenuItem(value: c, child: Text(c)),
            ],
            onChanged: (c) => setState(() => _class = c),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _model,
            decoration: InputDecoration(labelText: s.t('replica.model')),
          ),
          SectionTitle(s.t('replica.tag')),
          if (_tagUid != null)
            Notice(
              s.t('replica.tag_read', {'uid': _tagUid}),
              kind: NoticeKind.ok,
            )
          else
            Text(_nfcOn ? s.t('replica.tap_tag') : s.t('nfc.none')),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            key: const Key('replica-scan'),
            icon: const Icon(Icons.qr_code_scanner),
            label: Text(s.t('replica.scan')),
            onPressed: _scan,
          ),
          const SizedBox(height: 20),
          FilledButton(
            key: const Key('replica-save'),
            onPressed: _save,
            child: Text(s.t('common.save')),
          ),
        ],
      ),
    );
  }
}
