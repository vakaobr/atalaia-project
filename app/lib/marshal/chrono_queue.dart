// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The marshal's "replicas to chrono" list (ADR-P3-13): every declared
/// replica of the game by player, the ones not chronographed yet first in
/// check-in order, with counts; a replica's sticker or label scanned jumps
/// to its declaration; a declaration with no registered replica is
/// registered here (the next readings link it); players without the app are
/// checked in by hand. Each judged series is sent to the controller signed
/// with the marshal's key (POST /api/v1/chrono/readings); a series the
/// controller could not take stays on the phone and is sent later.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../app.dart';
import '../checkin/checkin_client.dart';
import '../checkin/checkin_screen.dart'
    show ChronoStateChip, replicaLabel, teamAndSquad;
import '../checkin/field_trust.dart';
import '../checkin/my_replicas.dart';
import '../chrono/chrono_ui.dart';
import '../chrono/limit_template.dart';
import '../chrono/reading.dart';
import '../chrono/replica.dart';
import '../l10n/strings.dart';
import '../ui/code_kind.dart';
import '../ui/widgets.dart';
import 'marshal_records.dart';

/// The marshal's records for a screen that has none of its own.
Future<MarshalRecords> marshalRecordsFor(BuildContext context) async {
  final app = AppScope.read(context);
  final r = MarshalRecords(app.services.store, app.settings);
  await r.load();
  return r;
}

/// Where a judged series goes, and what it links: a declaration that had no
/// registered replica, and that replica's registry record.
class ChronoUpload {
  ChronoUpload({
    required this.client,
    required this.checkin,
    this.declarationId,
    this.replica,
  });

  final CheckinClient client;
  final FieldCheckin checkin;
  final String? declarationId;
  final Replica? replica;

  int get gameId => checkin.gameId;

  Future<Map<String, Object?>> send(
    MarshalRecords records,
    List<ChronoReading> series,
  ) async {
    final rid = series.first.replicaId;
    final link = declarationId ?? records.pendingLinks[rid];
    final rep =
        replica ??
        (link == null
            ? null
            : records.replicas.where((r) => r.replicaId == rid).firstOrNull);
    final out = await client.uploadReadings(
      checkin.token,
      [for (final r in series) r.toJson()],
      declarationId: link,
      replica: rep?.toJson(),
    );
    await records.markUploaded(series.map((r) => r.readingId));
    if (link != null) await records.setPendingLink(rid, null);
    return out;
  }
}

class ChronoQueueScreen extends StatefulWidget {
  const ChronoQueueScreen({
    required this.checkin,
    required this.field,
    this.records,
    this.templates,
    super.key,
  });

  final FieldCheckin checkin;
  final PinnedField field;
  final MarshalRecords? records;

  /// The limit templates (tests give them; the app loads its assets).
  final List<LimitTemplate>? templates;

  @override
  State<ChronoQueueScreen> createState() => _ChronoQueueScreenState();
}

class _ChronoQueueScreenState extends State<ChronoQueueScreen> {
  late final CheckinClient _client = CheckinClient(
    context.services.fieldHttp(widget.field),
  );
  MarshalRecords? _records;
  Map<String, Object?>? _list;
  String? _error;
  String? _highlight;
  bool _sending = false;

  FieldCheckin get c => widget.checkin;

  @override
  void initState() {
    super.initState();
    unawaited(_init());
  }

  Future<void> _init() async {
    _records = widget.records ?? await marshalRecordsFor(context);
    await _load();
  }

  Future<void> _load() async {
    try {
      final list = await _client.chronoList(c.token, c.gameId);
      if (mounted) {
        setState(() {
          _list = list;
          _error = null;
        });
      }
    } on CheckinException catch (e) {
      if (!mounted) return;
      setState(
        () => _error = e.status == 403
            ? context.s.t('queue.not_marshal')
            : (e.offline
                  ? context.s.t('checkin.offline')
                  : context.s.t('checkin.error', {'error': e.message})),
      );
    }
  }

  List<Map<String, Object?>> get _players => [
    for (final p in (_list?['players'] as List?) ?? const [])
      if (p is Map) p.cast<String, Object?>(),
  ];

  Future<void> _chrono(Map<String, Object?> player, Declaration d) async {
    final records = _records!;
    String? link;
    Replica? replica = d.replicaId == null
        ? null
        : records.replicas.where((r) => r.replicaId == d.replicaId).firstOrNull;
    if (replica == null) {
      // Not in this phone's registry: register it now with a label the marshal
      // can stick on it; a declaration without an id is linked by the upload.
      final id = d.replicaId ?? newUuid();
      replica = Replica(
        replicaId: id,
        ownerPlayerId: '${player['player_id']}',
        type: ReplicaTypeWire.parse(d.type) ?? ReplicaType.aeg,
        replicaClass: d.replicaClass,
        makeModel: d.makeModel,
        registeredAt: formatTimestamp(DateTime.now()),
        tagType: TagType.qr,
        tagUid: 'ATL-${id.substring(0, 8).toUpperCase()}',
      );
      await records.addReplica(replica);
      if (d.replicaId == null) {
        link = d.declarationId;
        await records.setPendingLink(id, link);
      }
    }
    if (!mounted) return;
    await Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) => ChronoScreen(
          records: records,
          templates: widget.templates,
          replica: replica,
          upload: ChronoUpload(
            client: _client,
            checkin: c,
            declarationId: link,
            replica: link == null ? null : replica,
          ),
        ),
      ),
    );
    await _load();
  }

  Future<void> _scan() async {
    final s = context.s;
    final qr = context.services.qr;
    if (!await qr.available) return;
    final text = await qr.scan(
      hint: s.t('queue.scan_hint'),
      cancel: s.t('common.cancel'),
    );
    if (text == null || !mounted) return;
    final wrong = classifyCode(text)?.messageKey;
    if (wrong != null) {
      setState(() => _error = s.t(wrong));
      return;
    }
    final replica = _records?.byTag(text.trim());
    final rid = replica?.replicaId;
    final found = _players.any(
      (p) => ((p['declarations'] as List?) ?? const []).any(
        (d) => d is Map && d['replica_id'] == rid,
      ),
    );
    setState(() {
      _highlight = found ? rid : null;
      _error = found ? null : s.t('queue.not_found');
    });
  }

  Future<void> _manual() async {
    final s = context.s;
    final name = await promptText(
      context,
      title: s.t('queue.manual'),
      label: s.t('checkin.name'),
      actions: [
        (s.t('common.cancel'), (_) => null, false),
        (s.t('queue.manual_do'), (t) => t.trim(), true),
      ],
    );
    if (name == null || name.isEmpty) return;
    try {
      final row = await _client.manualCheckin(c.token, c.gameId, {
        'display_name': name,
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(s.t('queue.manual_done', {'id': row['player_id']})),
          ),
        );
      }
      await _load();
    } on CheckinException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _sendPending() async {
    final records = _records!;
    setState(() => _sending = true);
    var failed = 0;
    var held = 0;
    for (final series in records.unsentSeries()) {
      try {
        await ChronoUpload(client: _client, checkin: c).send(records, series);
      } on CheckinException catch (e) {
        // The controller does not have this marshal on its list (or the
        // check-in is no longer a marshal's): the GM may add them again, so
        // the series wait on this phone (MR-8); they are not given up.
        final marshalRefused = e.reasons.any((r) => r['reason'] == 'marshal');
        if (marshalRefused || e.status == 403) {
          held++;
        } else if (e.status == 422) {
          // Refused for good (another field, a signature that does not
          // verify): kept here only.
          await records.markUploaded(series.map((r) => r.readingId));
        }
        failed++;
      }
    }
    // The list first: its own answer (or error) must not wipe what was said
    // about the series that stayed on the phone.
    await _load();
    if (!mounted) return;
    setState(() {
      _sending = false;
      if (held > 0) {
        _error = context.s.t('queue.held', {'n': held});
      } else if (failed > 0) {
        _error = context.s.t('queue.send_failed', {'n': failed});
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final counts = (_list?['counts'] as Map?) ?? const {};
    final unsent = _records?.unsentSeries().length ?? 0;
    return Scaffold(
      appBar: AppBar(
        title: Text(s.t('queue.title')),
        actions: [
          IconButton(
            tooltip: s.t('queue.scan'),
            key: const Key('queue-scan'),
            icon: const Icon(Icons.qr_code_scanner),
            onPressed: _scan,
          ),
          IconButton(
            tooltip: s.t('queue.refresh'),
            key: const Key('queue-refresh'),
            icon: const Icon(Icons.refresh),
            onPressed: _load,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(c.gameName, style: Theme.of(context).textTheme.titleLarge),
            if (_error != null)
              Notice(
                _error!,
                kind: NoticeKind.warning,
                key: const Key('queue-error'),
              ),
            if (_list != null)
              Text(
                s.t('queue.counts', {
                  'pending': counts['pending'] ?? 0,
                  'passed': counts['passed'] ?? 0,
                  'refused': counts['refused'] ?? 0,
                }),
                key: const Key('queue-counts'),
              ),
            if (unsent > 0)
              FilledButton.icon(
                key: const Key('queue-send-pending'),
                icon: const Icon(Icons.cloud_upload),
                label: Text(s.t('queue.send_pending', {'n': unsent})),
                onPressed: _sending ? null : _sendPending,
              ),
            if (_list != null && _players.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(s.t('queue.empty')),
              ),
            for (final p in _players) _player(s, p),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              key: const Key('queue-manual'),
              icon: const Icon(Icons.person_add),
              label: Text(s.t('queue.manual')),
              onPressed: _manual,
            ),
          ],
        ),
      ),
    );
  }

  Widget _player(Strings s, Map<String, Object?> p) {
    final decls = [
      for (final d in (p['declarations'] as List?) ?? const [])
        if (d is Map) Declaration.fromJson(d.cast<String, Object?>()),
    ];
    return Card(
      key: Key('queue-player-${p['player_id']}'),
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${p['display_name'] ?? p['player_id']}'
              '${p['team'] == null ? '' : ' · ${teamAndSquad(s, '${p['team']}', (p['squad'] as int?) ?? 0)}'}',
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
            if (p['status'] == 'pending')
              Text(
                s.t('queue.waiting_confirmation'),
                style: TextStyle(color: Theme.of(context).hintColor),
              ),
            for (final d in decls)
              ListTile(
                key: Key('queue-decl-${d.declarationId}'),
                dense: true,
                selected: d.replicaId != null && d.replicaId == _highlight,
                title: Text(replicaLabel(s, d.type, d.makeModel)),
                subtitle: Text(
                  d.replicaId == null
                      ? '${d.replicaClass} · ${s.t('queue.unregistered')}'
                      : d.replicaClass,
                ),
                trailing: ChronoStateChip(
                  d.state,
                  refusedToday: d.refusedToday,
                ),
                onTap: () => _chrono(p, d),
              ),
          ],
        ),
      ),
    );
  }
}
