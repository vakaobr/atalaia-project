// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A marshal takes a registered player's printed check-in ticket (decisions
/// TKT-1 to TKT-6): the ticket's QR code, scanned with the camera, or its
/// text, typed, goes to the field controller (`POST
/// /api/v1/games/{id}/checkins/ticket`) with the marshal's own token, the
/// same route the GM console's "Printed ticket" card uses. The controller
/// decides everything: whether the registration is on this game's list and
/// the ticket its newest, and whether the player is in at once or waits for
/// the card check under the field's APD rule (the ticket is not the card).
/// This screen only checks that the text is a ticket before it leaves the
/// phone, and says what the answer means. When the controller asks the
/// marshal to decide (TKS-1 to TKS-5) the screen shows what it needs to:
/// a pending app check-in's name and time next to the ticket's name on the
/// list (confirm it, or discard it and check in the ticket holder), or a
/// membership that does not pass (check in anyway, or not). Nothing is
/// confirmed without the marshal's tap.
library;

import 'package:flutter/material.dart';

import '../app.dart';
import '../checkin/checkin_client.dart';
import '../checkin/field_trust.dart';
import '../checkin/my_replicas.dart';
import '../l10n/strings.dart';
import '../protocol/checkin_ticket.dart'
    show TicketException, parseTicket, ticketTextPrefix;
import '../ui/code_kind.dart';
import '../ui/widgets.dart';

/// What the controller's answer to a ticket means for the marshal: the
/// text's [key], its [kind] and its [args] (the player's name).
final class TicketOutcome {
  const TicketOutcome(this.key, this.kind, [this.args = const {}]);

  final String key;
  final NoticeKind kind;
  final Map<String, Object?> args;

  /// From an answer of 200: checked in, a pending self check-in confirmed
  /// (TKT-7), an app check-in discarded for the ticket holder (TKS-3),
  /// waiting for the card check, or already there (the scan changed
  /// nothing). An answer with a `decision` is a [TicketDecision] instead.
  factory TicketOutcome.fromRow(Map<String, Object?> row) {
    final name = row['display_name'] ?? row['player_id'] ?? '';
    final pending = row['status'] == 'pending';
    final args = {'name': name};
    if (row['discarded'] == true) {
      return TicketOutcome(
        pending ? 'ticket.discarded_pending' : 'ticket.discarded',
        pending ? NoticeKind.warning : NoticeKind.ok,
        args,
      );
    }
    if (row['confirmed'] == true) {
      return TicketOutcome('ticket.confirmed', NoticeKind.ok, args);
    }
    if (row['already'] == true) {
      return pending
          ? TicketOutcome('ticket.already_pending', NoticeKind.warning, args)
          : TicketOutcome('ticket.already', NoticeKind.info, args);
    }
    return pending
        ? TicketOutcome('ticket.pending', NoticeKind.warning, args)
        : TicketOutcome('ticket.done', NoticeKind.ok, args);
  }

  /// From a refusal (or no answer: status 0).
  factory TicketOutcome.fromError(CheckinException e) => switch (e.status) {
    0 => const TicketOutcome('ticket.offline', NoticeKind.error),
    400 => const TicketOutcome('ticket.bad', NoticeKind.error),
    401 => const TicketOutcome('ticket.session', NoticeKind.error),
    403 when e.message.startsWith('ticket_not_newest') => const TicketOutcome(
      'ticket.not_newest',
      NoticeKind.error,
    ),
    404 => const TicketOutcome('ticket.not_listed', NoticeKind.error),
    409 => const TicketOutcome('ticket.ended', NoticeKind.error),
    429 => const TicketOutcome('ticket.too_many', NoticeKind.error),
    _ => TicketOutcome('ticket.refused', NoticeKind.error, {
      'error': e.message,
    }),
  };
}

/// What the controller asks the marshal to decide about a scanned ticket
/// (TKS-1 to TKS-5): [kind] `app_checkin` (a pending check-in made in an app,
/// with the app's [appName], when it checked in, [at], and the ticket's
/// [rosterName]; [appBinding] says whether that app proved it is the phone
/// that registered, TKB-5) or `membership` (the stored [verdict] does not
/// pass).
final class TicketDecision {
  const TicketDecision({
    required this.ticket,
    required this.kind,
    this.appName,
    this.at,
    this.rosterName,
    this.verdict,
    this.appCheckin,
    this.appBinding,
  });

  /// The ticket's text, sent again with the marshal's choice.
  final String ticket;
  final String kind;
  final String? appName;
  final DateTime? at;
  final String? rosterName;
  final String? verdict;

  /// `bound` (the registering phone's key signed the check-in) or `unbound`
  /// (a copy of the ticket, an older app or a registration without a key);
  /// null from an older controller.
  final String? appBinding;

  /// The choice already made about the app check-in, kept when a
  /// membership decision follows it.
  final String? appCheckin;

  /// The decision in an answer, or null when there is none.
  static TicketDecision? fromRow(
    Map<String, Object?> row,
    String ticket, {
    String? appCheckin,
  }) {
    final d = row['decision'];
    if (d is! Map) return null;
    final at = d['at'];
    return TicketDecision(
      ticket: ticket,
      kind: '${d['kind']}',
      appName: d['name'] as String?,
      at: at is num
          ? DateTime.fromMillisecondsSinceEpoch((at * 1000).round())
          : null,
      rosterName: d['roster_name'] as String?,
      verdict: d['verdict'] as String?,
      appCheckin: appCheckin,
      appBinding: d['app_binding'] as String?,
    );
  }
}

/// A local time of day as the screen shows it (HH:MM).
String ticketClock(DateTime t) {
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(t.hour)}:${two(t.minute)}';
}

/// A typed ticket as the controller takes it: the spaces and line breaks
/// of a copy from paper dropped, and the `atalaia:ticket:` prefix added when
/// only the code after it was typed.
String normaliseTicketText(String typed) {
  final t = typed.replaceAll(RegExp(r'\s+'), '');
  if (t.isEmpty || t.contains(':')) return t;
  return '$ticketTextPrefix$t';
}

class TicketCheckinScreen extends StatefulWidget {
  const TicketCheckinScreen({
    required this.checkin,
    required this.field,
    super.key,
  });

  /// The marshal's own check-in: its token and game.
  final FieldCheckin checkin;
  final PinnedField field;

  @override
  State<TicketCheckinScreen> createState() => _TicketCheckinScreenState();
}

class _TicketCheckinScreenState extends State<TicketCheckinScreen> {
  late final CheckinClient _client = CheckinClient(
    context.services.fieldHttp(widget.field),
  );
  final _text = TextEditingController();
  bool _sending = false;
  TicketOutcome? _outcome;
  TicketDecision? _decision;
  final _taken = <TicketOutcome>[];

  FieldCheckin get c => widget.checkin;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _scan() async {
    final s = context.s;
    final qr = context.services.qr;
    if (!await qr.available) {
      if (mounted) {
        setState(
          () => _outcome = const TicketOutcome(
            'ticket.no_camera',
            NoticeKind.warning,
          ),
        );
      }
      return;
    }
    final text = await qr.scan(
      hint: s.t('ticket.scan_hint'),
      cancel: s.t('common.cancel'),
    );
    if (text == null || !mounted) return;
    await _send(text.trim(), typed: false);
  }

  Future<void> _submit() => _send(normaliseTicketText(_text.text), typed: true);

  /// Checks [text] is a ticket, then asks the controller.
  Future<void> _send(String text, {required bool typed}) async {
    if (_sending) return;
    setState(() => _decision = null);
    final wrong = wrongCodeMessage(text, CodeKind.ticket);
    if (wrong != null) {
      setState(() => _outcome = TicketOutcome(wrong, NoticeKind.error));
      return;
    }
    try {
      parseTicket(text);
    } on TicketException {
      setState(
        () => _outcome = const TicketOutcome('ticket.bad', NoticeKind.error),
      );
      return;
    }
    await _ask(text);
    final o = _outcome;
    if (typed &&
        mounted &&
        (_decision != null || o?.kind != NoticeKind.error)) {
      _text.clear();
    }
  }

  /// Sends [ticket] with the marshal's choices so far and shows the answer:
  /// an outcome, or a decision to make.
  Future<void> _ask(
    String ticket, {
    String? appCheckin,
    bool override = false,
  }) async {
    setState(() {
      _sending = true;
      _outcome = null;
      _decision = null;
    });
    TicketOutcome? outcome;
    TicketDecision? decision;
    try {
      final row = await _client.ticketCheckin(
        c.token,
        c.gameId,
        ticket,
        appCheckin: appCheckin,
        override: override,
      );
      decision = TicketDecision.fromRow(row, ticket, appCheckin: appCheckin);
      if (decision == null) outcome = TicketOutcome.fromRow(row);
    } on CheckinException catch (e) {
      outcome = TicketOutcome.fromError(e);
    }
    if (!mounted) return;
    setState(() {
      _sending = false;
      _outcome = outcome;
      _decision = decision;
      if (outcome != null && outcome.kind != NoticeKind.error) {
        _taken.insert(0, outcome);
      }
    });
  }

  /// The marshal's choice on a decision: sent with the same ticket.
  void _decide(TicketDecision d, {String? appCheckin, bool override = false}) {
    _ask(d.ticket, appCheckin: appCheckin ?? d.appCheckin, override: override);
  }

  void _cancelDecision() => setState(() {
    _decision = null;
    _outcome = const TicketOutcome(
      'ticket.decision_cancelled',
      NoticeKind.info,
    );
  });

  Widget _decisionCard(Strings s, TicketDecision d) {
    final app = d.kind == 'app_checkin';
    final unknown = s.t('ticket.unknown_name');
    final text = app
        ? s.t('ticket.app_checkin_body', {
            'app_name': d.appName ?? unknown,
            'time': d.at == null ? '?' : ticketClock(d.at!),
            'roster_name': d.rosterName ?? unknown,
          })
        : s.t('ticket.membership_body', {
            'verdict': s.t('apd.status.${d.verdict}'),
          });
    return Card(
      key: Key(app ? 'ticket-decision-app' : 'ticket-decision-membership'),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              s.t(app ? 'ticket.app_checkin_title' : 'ticket.membership_title'),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Text(text),
            if (app && d.appBinding != null) ...[
              const SizedBox(height: 8),
              Row(
                key: Key('ticket-app-${d.appBinding}'),
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    d.appBinding == 'bound'
                        ? Icons.verified_user_outlined
                        : Icons.warning_amber_outlined,
                  ),
                  const SizedBox(width: 8),
                  Expanded(child: Text(s.t('ticket.app_${d.appBinding}'))),
                ],
              ),
            ],
            const SizedBox(height: 12),
            if (app) ...[
              FilledButton(
                key: const Key('ticket-confirm-app'),
                onPressed: () => _decide(d, appCheckin: 'confirm'),
                child: Text(s.t('ticket.app_checkin_confirm')),
              ),
              const SizedBox(height: 8),
              OutlinedButton(
                key: const Key('ticket-discard-app'),
                onPressed: () => _decide(d, appCheckin: 'discard'),
                child: Text(s.t('ticket.app_checkin_discard')),
              ),
            ] else
              FilledButton(
                key: const Key('ticket-override'),
                onPressed: () => _decide(d, override: true),
                child: Text(s.t('ticket.membership_override')),
              ),
            TextButton(
              key: const Key('ticket-decision-cancel'),
              onPressed: _cancelDecision,
              child: Text(s.t('common.cancel')),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final o = _outcome;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('ticket.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(s.t('ticket.intro')),
          const SizedBox(height: 12),
          Notice(s.t('ticket.for_game', {'game': c.gameName})),
          const SizedBox(height: 12),
          if (_sending)
            Notice(s.t('ticket.sending'), key: const Key('ticket-sending'))
          else if (_decision != null)
            _decisionCard(s, _decision!)
          else if (o != null)
            Notice(
              s.t(o.key, o.args),
              kind: o.kind,
              key: const Key('ticket-result'),
            ),
          const SizedBox(height: 12),
          FilledButton.icon(
            key: const Key('ticket-scan'),
            icon: const Icon(Icons.qr_code_scanner),
            label: Text(s.t('ticket.scan')),
            onPressed: _sending ? null : _scan,
          ),
          const SizedBox(height: 16),
          TextField(
            key: const Key('ticket-text'),
            controller: _text,
            autocorrect: false,
            enableSuggestions: false,
            maxLength: 256,
            decoration: InputDecoration(
              labelText: s.t('ticket.text'),
              helperText: s.t('ticket.text_hint'),
              helperMaxLines: 2,
            ),
            onSubmitted: (_) => _submit(),
          ),
          Align(
            alignment: AlignmentDirectional.centerEnd,
            child: OutlinedButton(
              key: const Key('ticket-submit'),
              onPressed: _sending ? null : _submit,
              child: Text(s.t('ticket.submit')),
            ),
          ),
          if (_taken.isNotEmpty) SectionTitle(s.t('ticket.recent')),
          for (final t in _taken)
            ListTile(
              dense: true,
              leading: Icon(
                t.kind == NoticeKind.ok ? Icons.check_circle : Icons.info,
              ),
              title: Text(s.t(t.key, t.args)),
            ),
        ],
      ),
    );
  }
}
