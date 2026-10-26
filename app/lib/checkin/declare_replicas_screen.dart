// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The replicas a player will use in this game (ADR-P3-13, "Declaring
/// replicas"): picked from "my replicas", the list the phone keeps (type,
/// class, make and model as the player describes them), or added there. The
/// declaration goes to the controller, which keeps each replica's chrono
/// state; a replica a marshal has chronographed stays declared (only staff
/// change it then).
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../app.dart';
import '../chrono/reading.dart' show newUuid;
import '../l10n/strings.dart';
import '../ui/widgets.dart';
import 'checkin_client.dart';
import 'checkin_screen.dart';
import 'my_replicas.dart';
import 'failure_details.dart';

class DeclareReplicasScreen extends StatefulWidget {
  const DeclareReplicasScreen({
    required this.checkin,
    required this.client,
    required this.declared,
    super.key,
  });

  final FieldCheckin checkin;
  final CheckinClient client;

  /// The declaration as the controller has it now.
  final List<Declaration> declared;

  @override
  State<DeclareReplicasScreen> createState() => _DeclareReplicasScreenState();
}

class _DeclareReplicasScreenState extends State<DeclareReplicasScreen> {
  late final CheckinStore store = context.services.checkins;
  List<String> _classes = const ['rifle'];
  int _max = 5;
  final _picked = <String>{};
  late List<Declaration> _declared = widget.declared;
  String? _error;
  bool _saved = false;

  FieldCheckin get c => widget.checkin;

  @override
  void initState() {
    super.initState();
    for (final e in c.declarations.entries) {
      if (_declared.any((d) => d.declarationId == e.value)) _picked.add(e.key);
    }
    unawaited(_load());
  }

  Future<void> _load() async {
    await store.load();
    try {
      final info = await widget.client.info();
      if (!mounted) return;
      setState(() {
        if (info.classes.isNotEmpty) _classes = info.classes;
        _max = info.maxReplicas;
      });
    } on CheckinException {
      // Offline: the classes of the last answer are not needed to pick.
    }
  }

  Declaration? _stateOf(String myId) {
    final did = c.declarations[myId];
    return _declared.where((d) => d.declarationId == did).firstOrNull;
  }

  bool _locked(String myId) {
    final st = _stateOf(myId)?.state;
    return st == 'passed' || st == 'refused';
  }

  Future<void> _save() async {
    setState(() => _error = null);
    try {
      final decls = store.declarationsFor(c, _picked.toList());
      _declared = await widget.client.putReplicas(c.token, decls);
      await store.saveCheckin(c);
      if (mounted) setState(() => _saved = true);
    } on CheckinException catch (e) {
      if (mounted) {
        setState(
          () => _error = e.status == 409
              ? context.s.t('declare.locked')
              : (e.offline
                    ? context.s.t('checkin.offline')
                    : context.s.t('checkin.error', {'error': e.message})),
        );
      }
    }
  }

  Future<void> _add() async {
    final r = await showDialog<MyReplica>(
      context: context,
      builder: (_) => NewReplicaDialog(classes: _classes),
    );
    if (r == null) return;
    await store.saveReplica(r);
    if (mounted && _picked.length < _max) setState(() => _picked.add(r.id));
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('declare.title'))),
      body: ListenableBuilder(
        listenable: store,
        builder: (context, _) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(s.t('declare.intro', {'max': _max})),
            const SizedBox(height: 8),
            if (_error != null) Notice(_error!, kind: NoticeKind.error),
            if (_error != null) FailureDetails(routeKey: c.fieldId),
            if (_saved)
              Notice(
                s.t('declare.saved'),
                kind: NoticeKind.ok,
                key: const Key('declare-saved'),
              ),
            if (store.replicas.isEmpty) Text(s.t('declare.none')),
            for (final r in store.replicas)
              CheckboxListTile(
                key: Key('declare-${r.id}'),
                value: _picked.contains(r.id),
                onChanged: _locked(r.id)
                    ? null
                    : (v) => setState(() {
                        _saved = false;
                        if (v == true && _picked.length < _max) {
                          _picked.add(r.id);
                        } else {
                          _picked.remove(r.id);
                        }
                      }),
                title: Text(replicaLabel(s, r.type, r.makeModel)),
                subtitle: Text(r.replicaClass),
                secondary: _stateOf(r.id) == null
                    ? null
                    : ChronoStateChip(
                        _stateOf(r.id)!.state,
                        refusedToday: _stateOf(r.id)!.refusedToday,
                      ),
              ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              key: const Key('declare-add'),
              icon: const Icon(Icons.add),
              label: Text(s.t('declare.add')),
              onPressed: _add,
            ),
            const SizedBox(height: 12),
            FilledButton(
              key: const Key('declare-save'),
              onPressed: _save,
              child: Text(s.t('declare.save')),
            ),
          ],
        ),
      ),
    );
  }
}

/// A new replica for "my replicas": its type, a class of [classes], make
/// and model (also the site server's registration form, lib/site/).
class NewReplicaDialog extends StatefulWidget {
  const NewReplicaDialog({required this.classes, super.key});
  final List<String> classes;

  @override
  State<NewReplicaDialog> createState() => _NewReplicaDialogState();
}

class _NewReplicaDialogState extends State<NewReplicaDialog> {
  String _type = 'aeg';
  late String _class = widget.classes.first;
  final _make = TextEditingController();

  @override
  void dispose() {
    _make.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return AlertDialog(
      title: Text(s.t('declare.add')),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            DropdownButtonFormField<String>(
              key: const Key('replica-type'),
              initialValue: _type,
              decoration: InputDecoration(labelText: s.t('declare.type')),
              items: [
                for (final t in replicaTypes)
                  DropdownMenuItem(
                    value: t,
                    child: Text(s.tOr('replica.type_$t', t)),
                  ),
              ],
              onChanged: (v) => setState(() => _type = v ?? 'aeg'),
            ),
            DropdownButtonFormField<String>(
              key: const Key('replica-class'),
              initialValue: _class,
              decoration: InputDecoration(labelText: s.t('declare.class')),
              items: [
                for (final c in widget.classes)
                  DropdownMenuItem(value: c, child: Text(c)),
              ],
              onChanged: (v) => setState(() => _class = v ?? _class),
            ),
            TextField(
              key: const Key('replica-make'),
              controller: _make,
              maxLength: 64,
              decoration: InputDecoration(labelText: s.t('declare.make')),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(s.t('common.cancel')),
        ),
        FilledButton(
          key: const Key('replica-save'),
          onPressed: () {
            final mm = _make.text.trim();
            Navigator.pop(
              context,
              MyReplica(
                id: newUuid(),
                type: _type,
                replicaClass: _class,
                makeModel: mm.isEmpty ? null : mm,
              ),
            );
          },
          child: Text(s.t('common.save')),
        ),
      ],
    );
  }
}
