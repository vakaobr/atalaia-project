// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The marshal's chrono check-in (ADR-P3-7, plan phase D): pick the replica
/// (from the registry, or by its NFC sticker), check in or spot check, type
/// each shot's velocity on a big keypad (m/s or fps), and see the energy and
/// PASS, WARN or FAIL against the field's limit template. Each shot is a
/// record, signed with the marshal's key as it is taken. The limit
/// templates are unverified research figures and say so (decision P3-5).
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../marshal/chrono_queue.dart' show ChronoUpload;
import '../marshal/marshal_records.dart';
import '../platform/services.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'energy.dart';
import 'limit_template.dart';
import 'reading.dart';
import 'replica.dart';
import 'spot_check.dart';

/// The built-in limit templates (lib/chrono/limit_templates/).
Future<List<LimitTemplate>> loadLimitTemplates([AssetBundle? bundle]) async {
  final b = bundle ?? rootBundle;
  return [
    for (final path in builtinLimitTemplates)
      LimitTemplate.parse(await b.loadString(path)),
  ];
}

/// What the marshal types on the keypad: digits and one decimal point.
class VelocityEntry {
  String text = '';

  void key(String k) {
    if (k == '.') {
      if (text.contains('.')) return;
      text = text.isEmpty ? '0.' : '$text.';
      return;
    }
    if (!RegExp(r'^\d$').hasMatch(k)) return;
    final dot = text.indexOf('.');
    if (dot >= 0 && text.length - dot > 2) return; // two decimals at most
    if (dot < 0 && text.replaceFirst(RegExp('^0+'), '').length >= 4) return;
    text = text == '0' ? k : text + k;
  }

  void back() {
    if (text.isNotEmpty) text = text.substring(0, text.length - 1);
  }

  void clear() => text = '';

  double? get value {
    final v = double.tryParse(text);
    return v == null || v <= 0 ? null : v;
  }
}

const bbWeights = [0.20, 0.23, 0.25, 0.28, 0.30, 0.32, 0.36, 0.40, 0.43, 0.45];

class ChronoScreen extends StatefulWidget {
  const ChronoScreen({
    required this.records,
    this.templates,
    this.replica,
    this.upload,
    super.key,
  });

  final MarshalRecords records;

  /// The replica to start with (from the "replicas to chrono" list).
  final Replica? replica;

  /// Where a judged series goes: the field controller (plan phase E).
  final ChronoUpload? upload;

  /// The limit templates (tests give them; the app loads its assets).
  final List<LimitTemplate>? templates;

  @override
  State<ChronoScreen> createState() => _ChronoScreenState();
}

class _ChronoScreenState extends State<ChronoScreen> {
  List<LimitTemplate> _templates = const [];
  LimitTemplate? _template;
  late Replica? _replica = widget.replica;
  ReadingType _type = ReadingType.checkin;
  String? _sent;
  bool _sending = false;
  bool _fps = false;
  double _weight = 0.20;
  final _entry = VelocityEntry();
  final _series = <ChronoReading>[];
  StreamSubscription<NfcRead>? _tags;
  late final NfcService _nfc = context.services.nfc;
  bool _nfcOn = false;
  String? _error;

  MarshalRecords get records => widget.records;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    final ts = widget.templates ?? await loadLimitTemplates();
    if (!mounted) return;
    final want = AppScope.read(context).settings.limitTemplate;
    setState(() {
      _templates = ts;
      _template = ts.firstWhere((t) => t.id == want, orElse: () => ts.first);
    });
    if (await _nfc.state() == NfcState.ready) {
      _tags = _nfc.reads.listen(_onTag);
      await _nfc.startReading();
      _nfcOn = true;
    }
  }

  void _onTag(NfcRead r) {
    final found = records.byTag(Replica.nfcUid(r.uid));
    setState(() {
      if (found == null) {
        _error = 'chrono.unknown_tag';
      } else {
        _replica = found;
        _series.clear();
        _error = null;
      }
    });
  }

  @override
  void dispose() {
    unawaited(_tags?.cancel());
    if (_nfcOn) unawaited(_nfc.stopReading());
    super.dispose();
  }

  ClassLimit? get _limit =>
      _replica == null ? null : _template?.limitFor(_replica!.replicaClass);

  Future<void> _shoot() async {
    final v = _entry.value;
    final replica = _replica;
    if (v == null || replica == null || _limit == null) return;
    final mps = _fps ? fpsToMps(v) : v;
    try {
      final r = await records.record(
        replica: replica,
        type: _type,
        velocityMps: mps,
        bbWeightG: _weight,
        gameId: widget.upload == null ? null : '${widget.upload!.gameId}',
      );
      setState(() {
        _sent = null;
        _series.add(r);
        _entry.clear();
        _error = null;
      });
    } on ChronoFormatException catch (e) {
      setState(() => _error = e.message);
    } on MarshalNotAuthorised {
      // The controller's confirmation ran out while the screen was open.
      setState(() => _error = 'marshal.expired_now');
    }
  }

  Future<void> _send() async {
    final up = widget.upload;
    if (up == null || _series.isEmpty) return;
    setState(() => _sending = true);
    final s = context.s;
    try {
      final out = await up.send(records, List.of(_series));
      if (!mounted) return;
      setState(() => _sent = s.t('chrono.sent_${out['outcome']}'));
    } on Object catch (e) {
      if (mounted) {
        setState(() => _sent = s.t('chrono.send_failed', {'error': '$e'}));
      }
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final template = _template;
    final limit = _limit;
    final outcome = _series.isEmpty || limit == null
        ? null
        : records.judge(_series, _type, limit);
    final v = _entry.value;
    final previewJ = v == null
        ? null
        : energyJoules(bbWeightG: _weight, velocityMps: _fps ? fpsToMps(v) : v);
    return Scaffold(
      appBar: AppBar(title: Text(s.t('chrono.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (!records.hasIdentity)
            Notice(s.t('marshal.no_identity'), kind: NoticeKind.warning),
          if (template != null && !template.verified)
            Notice(
              s.t('chrono.unverified', {'name': template.name}),
              kind: NoticeKind.warning,
              key: const Key('chrono-unverified'),
            ),
          if (_error != null)
            Notice(
              _error!.startsWith('chrono.') || _error!.startsWith('marshal.')
                  ? s.t(_error!)
                  : _error!,
              kind: NoticeKind.error,
            ),
          DropdownButtonFormField<LimitTemplate>(
            initialValue: template,
            decoration: InputDecoration(labelText: s.t('chrono.template')),
            items: [
              for (final t in _templates)
                DropdownMenuItem(value: t, child: Text(t.name)),
            ],
            onChanged: (t) {
              setState(() => _template = t);
              if (t != null) {
                unawaited(
                  AppScope.read(context).update((x) => x.limitTemplate = t.id),
                );
              }
            },
          ),
          const SizedBox(height: 12),
          SegmentedButton<ReadingType>(
            segments: [
              ButtonSegment(
                value: ReadingType.checkin,
                label: Text(s.t('chrono.checkin')),
              ),
              ButtonSegment(
                value: ReadingType.spotcheck,
                label: Text(s.t('chrono.spotcheck')),
              ),
            ],
            selected: {_type},
            onSelectionChanged: (v) => setState(() {
              _type = v.single;
              _series.clear();
            }),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<Replica>(
            key: const Key('chrono-replica'),
            initialValue: _replica,
            isExpanded: true,
            decoration: InputDecoration(
              labelText: s.t('chrono.replica'),
              helperText: _nfcOn ? s.t('chrono.replica_nfc') : null,
              helperMaxLines: 3,
            ),
            items: [
              for (final r in records.replicas)
                DropdownMenuItem(
                  value: r,
                  child: Text(
                    '${r.ownerPlayerId} · ${r.makeModel ?? s.t('replica.type_${r.type.wire}')} · ${r.replicaClass}',
                  ),
                ),
            ],
            onChanged: (r) => setState(() {
              _replica = r;
              _series.clear();
            }),
          ),
          if (_replica != null && limit == null)
            Notice(
              s.t('chrono.no_class', {'class': _replica!.replicaClass}),
              kind: NoticeKind.error,
            ),
          if (limit != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                s.t('chrono.limit', {
                  'j': s.number(limit.maxEnergyJ, 2),
                  'fps': limit.maxFps020,
                }),
                key: const Key('chrono-limit'),
              ),
            ),
          SectionTitle(s.t('chrono.bb')),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final w in bbWeights)
                ChoiceChip(
                  label: Text('${s.number(w, 2)} g'),
                  selected: _weight == w,
                  onSelected: (_) => setState(() => _weight = w),
                ),
            ],
          ),
          SectionTitle(s.t('chrono.velocity')),
          Row(
            children: [
              Expanded(
                child: Text(
                  _entry.text.isEmpty ? '–' : _entry.text,
                  key: const Key('chrono-entry'),
                  style: const TextStyle(
                    fontSize: 44,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(value: false, label: Text('m/s')),
                  ButtonSegment(value: true, label: Text('fps')),
                ],
                selected: {_fps},
                onSelectionChanged: (v) => setState(() => _fps = v.single),
              ),
            ],
          ),
          if (previewJ != null)
            Text(
              s.t('chrono.energy', {'j': s.number(previewJ, 2)}),
              style: TextStyle(
                color: limit != null && previewJ > limit.maxEnergyJ
                    ? AtalaiaColors.danger
                    : null,
              ),
            ),
          const SizedBox(height: 8),
          _ChronoKeypad(
            onKey: (k) => setState(() => _entry.key(k)),
            onBack: () => setState(_entry.back),
          ),
          const SizedBox(height: 8),
          FilledButton.icon(
            key: const Key('chrono-record'),
            icon: const Icon(Icons.check),
            label: Text(s.t('chrono.record')),
            onPressed:
                v == null ||
                    _replica == null ||
                    limit == null ||
                    !records.hasIdentity
                ? null
                : _shoot,
          ),
          if (outcome != null) ...[
            const SizedBox(height: 16),
            ResultBadge(outcome: outcome),
            for (final r in _series.reversed)
              ListTile(
                dense: true,
                title: Text(
                  '${s.number(r.velocityMps, 2)} m/s · '
                  '${s.number(mpsToFps(r.velocityMps), 0)} fps · '
                  '${s.number(r.bbWeightG, 2)} g',
                ),
                trailing: Text('${s.number(r.energyJ, 3)} J'),
              ),
            if (widget.upload != null)
              FilledButton.icon(
                key: const Key('chrono-send'),
                icon: const Icon(Icons.send),
                label: Text(s.t('chrono.send')),
                onPressed:
                    _sending ||
                        _series.every(
                          (r) => records.uploaded.contains(r.readingId),
                        )
                    ? null
                    : _send,
              ),
            if (_sent != null) Notice(_sent!, key: const Key('chrono-sent')),
            TextButton(
              onPressed: () => setState(() {
                _series.clear();
                _sent = null;
              }),
              child: Text(s.t('chrono.new_series')),
            ),
          ],
        ],
      ),
    );
  }
}

/// PASS, WARN or FAIL, big, with the figures behind it.
class ResultBadge extends StatelessWidget {
  const ResultBadge({required this.outcome, super.key});
  final CheckOutcome outcome;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final (color, word) = switch (outcome.result) {
      CheckResult.pass => (AtalaiaColors.ok, s.t('chrono.pass')),
      CheckResult.warn => (AtalaiaColors.warn, s.t('chrono.warn')),
      CheckResult.fail => (AtalaiaColors.danger, s.t('chrono.fail')),
    };
    return Container(
      key: Key('chrono-result-${outcome.result.name}'),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        children: [
          Text(
            word,
            style: TextStyle(
              color: AtalaiaColors.on(color),
              fontSize: 40,
              fontWeight: FontWeight.w800,
            ),
          ),
          Text(
            s.t('chrono.highest', {
              'j': s.number(outcome.highestEnergyJ, 3),
              'limit': s.number(outcome.limitJ, 2),
            }),
            style: TextStyle(color: AtalaiaColors.on(color)),
          ),
          if (outcome.checkinEnergyJ != null)
            Text(
              s.t('chrono.vs_checkin', {
                'j': s.number(outcome.checkinEnergyJ!, 3),
                'pct': s.number(outcome.tolerancePct!, 0),
              }),
              style: TextStyle(color: AtalaiaColors.on(color)),
            ),
        ],
      ),
    );
  }
}

class _ChronoKeypad extends StatelessWidget {
  const _ChronoKeypad({required this.onKey, required this.onBack});
  final void Function(String k) onKey;
  final VoidCallback onBack;

  @override
  Widget build(BuildContext context) {
    const keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '.', '0', '<'];
    return GridView.count(
      crossAxisCount: 3,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      childAspectRatio: 2.2,
      mainAxisSpacing: 6,
      crossAxisSpacing: 6,
      children: [
        for (final k in keys)
          FilledButton.tonal(
            key: Key('chrono-key-$k'),
            onPressed: k == '<' ? onBack : () => onKey(k),
            child: k == '<'
                ? const Icon(Icons.backspace_outlined)
                : Text(k, style: const TextStyle(fontSize: 28)),
          ),
      ],
    );
  }
}
