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
import '../checkin/apd_fields.dart';
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
import '../platform/services.dart' show NfcRead, NfcService, NfcState;
import '../protocol/apd.dart';
import '../ui/code_kind.dart';
import '../ui/replica_label.dart';
import '../ui/widgets.dart';
import 'marshal_records.dart';
import '../checkin/failure_details.dart';

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

  List<ApdEntry> _apds = const [];

  Future<void> _init() async {
    _apds = await loadProjectApds();
    if (!mounted) return;
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
    // The id a replica is registered under is the field's own, or else its
    // declaration's, so a player's label (Replica.labelFor) is known before
    // the marshal registers it, and a second marshal's phone makes the same.
    final known = d.registryId;
    Replica? replica = known == null
        ? null
        : records.replicas.where((r) => r.replicaId == known).firstOrNull;
    if (replica == null) {
      // Not in this phone's registry: register it now with a label the marshal
      // can stick on it; a declaration without an id is linked by the upload.
      final id = known ?? newUuid();
      // An NFC sticker on the replica, when this phone reads them (PKA-3):
      // its UID is the tag; else, or by choice, the printed QR label.
      final sticker = await _askSticker();
      if (sticker == null || !mounted) return;
      replica = Replica(
        replicaId: id,
        ownerPlayerId: '${player['player_id']}',
        type: ReplicaTypeWire.parse(d.type) ?? ReplicaType.aeg,
        replicaClass: d.replicaClass,
        makeModel: d.makeModel,
        registeredAt: formatTimestamp(DateTime.now()),
        tagType: sticker.isEmpty ? TagType.qr : TagType.nfc,
        tagUid: sticker.isEmpty ? Replica.labelFor(id) : sticker,
      );
      await records.addReplica(replica);
    }
    if (d.replicaId == null) {
      link = d.declarationId;
      await records.setPendingLink(replica.replicaId, link);
    }
    if (!mounted) return;
    await Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) => ChronoScreen(
          records: records,
          templates: widget.templates,
          fieldInfo: _client.info,
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

  /// The UID of the NFC sticker the marshal holds to the phone for a replica
  /// registered here, '' for the QR label (no NFC on this phone, or chosen),
  /// null when the marshal gave up.
  Future<String?> _askSticker() async {
    final nfc = context.services.nfc;
    if (await nfc.state() != NfcState.ready || !mounted) return '';
    return showDialog<String>(
      context: context,
      barrierDismissible: false,
      builder: (_) => _StickerDialog(nfc: nfc, records: _records!),
    );
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
    final label = text.trim();
    final rid = _records?.byTag(label)?.replicaId;
    // The replica is the one registered here with this tag, or one declared
    // whose QR label (Replica.labelFor) this is, even before this phone
    // registered it: a player's printed label works on any marshal's phone.
    String? hit;
    for (final p in _players) {
      for (final d in (p['declarations'] as List?) ?? const []) {
        if (d is! Map) continue;
        final id = Declaration.fromJson(d.cast<String, Object?>()).registryId;
        if (id != null && (id == rid || Replica.labelFor(id) == label)) {
          hit = id;
        }
      }
    }
    setState(() {
      _highlight = hit;
      _error = hit != null ? null : s.t('queue.not_found');
    });
  }

  /// A marshal lets a pending player in, whatever the membership verdict
  /// says (the controller logs it when the verdict is not `valid`).
  Future<void> _confirm(String playerId) async {
    try {
      await _client.confirm(c.token, c.gameId, playerId);
      await _load();
    } on CheckinException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
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
            if (_error != null) FailureDetails(routeKey: widget.field.fieldId),
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

  /// The text of the QR label this declared replica is found by: its tag in
  /// this phone's registry, or the one the phone makes for it when it
  /// registers it; null when it has an NFC tag.
  String? _labelOf(Declaration d) {
    final id = d.registryId;
    if (id == null) return null;
    final r = _records?.replicas.where((x) => x.replicaId == id).firstOrNull;
    return r == null ? Replica.labelFor(id) : r.labelText;
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
            if (p['apd_status'] != null ||
                p['apd_id'] != null ||
                p['membership_number'] != null)
              Padding(
                key: Key('queue-apd-${p['player_id']}'),
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Wrap(
                  spacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    ApdBadge(
                      status: p['apd_status'] as String?,
                      overridden: p['apd_override'] == true,
                    ),
                    Text(
                      apdLine(
                        s,
                        _apds,
                        apd: p['apd_id'] as String?,
                        number: p['membership_number'] as String?,
                        expires: p['membership_expires'] as String?,
                      ),
                    ),
                  ],
                ),
              ),
            if (p['status'] == 'pending')
              Align(
                alignment: Alignment.centerLeft,
                child: OutlinedButton(
                  key: Key('queue-confirm-${p['player_id']}'),
                  onPressed: () => _confirm('${p['player_id']}'),
                  child: Text(s.t('queue.confirm')),
                ),
              ),
            for (final d in decls)
              ListTile(
                key: Key('queue-decl-${d.declarationId}'),
                dense: true,
                selected: d.registryId != null && d.registryId == _highlight,
                title: Text(replicaLabel(s, d.type, d.makeModel)),
                subtitle: Text(
                  d.replicaId == null
                      ? '${s.replicaClass(d.replicaClass)} · ${s.t('queue.unregistered')}'
                      : s.replicaClass(d.replicaClass),
                ),
                trailing: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (_labelOf(d) != null)
                      IconButton(
                        key: Key('label-show-${d.declarationId}'),
                        tooltip: s.t('label.show'),
                        icon: const Icon(Icons.qr_code_2),
                        onPressed: () => showLabel(
                          context,
                          _labelOf(d)!,
                          subtitle:
                              '${replicaLabel(s, d.type, d.makeModel)} · ${s.replicaClass(d.replicaClass)}',
                        ),
                      ),
                    ChronoStateChip(d.state, refusedToday: d.refusedToday),
                  ],
                ),
                onTap: () => _chrono(p, d),
              ),
          ],
        ),
      ),
    );
  }
}

/// Waits for an NFC sticker (its UID is the replica's tag) or the marshal's
/// choice of the printed QR label. A sticker already on another replica of
/// this phone is refused: one tag, one replica.
class _StickerDialog extends StatefulWidget {
  const _StickerDialog({required this.nfc, required this.records});

  final NfcService nfc;
  final MarshalRecords records;

  @override
  State<_StickerDialog> createState() => _StickerDialogState();
}

class _StickerDialogState extends State<_StickerDialog> {
  StreamSubscription<NfcRead>? _sub;
  bool _taken = false;

  @override
  void initState() {
    super.initState();
    _sub = widget.nfc.reads.listen(_read);
    unawaited(widget.nfc.startReading());
  }

  void _read(NfcRead r) {
    final uid = Replica.nfcUid(r.uid);
    if (widget.records.byTag(uid) != null) {
      setState(() => _taken = true);
      return;
    }
    Navigator.pop(context, uid);
  }

  @override
  void dispose() {
    unawaited(_sub?.cancel());
    unawaited(widget.nfc.stopReading());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return AlertDialog(
      title: Text(s.t('queue.sticker_title')),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(s.t('queue.sticker_body')),
          if (_taken)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(
                s.t('queue.sticker_taken'),
                key: const Key('queue-sticker-taken'),
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
        ],
      ),
      actions: [
        TextButton(
          key: const Key('queue-sticker-cancel'),
          onPressed: () => Navigator.pop(context),
          child: Text(s.t('common.cancel')),
        ),
        TextButton(
          key: const Key('queue-sticker-qr'),
          onPressed: () => Navigator.pop(context, ''),
          child: Text(s.t('queue.sticker_qr')),
        ),
      ],
    );
  }
}
