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
/// phone, and says what the answer means.
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

  /// From an answer of 200: checked in, waiting for the card check, or
  /// already there (the scan changed nothing).
  factory TicketOutcome.fromRow(Map<String, Object?> row) {
    final name = row['display_name'] ?? row['player_id'] ?? '';
    final pending = row['status'] == 'pending';
    final args = {'name': name};
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
    setState(() {
      _sending = true;
      _outcome = null;
    });
    TicketOutcome outcome;
    try {
      final row = await _client.ticketCheckin(c.token, c.gameId, text);
      outcome = TicketOutcome.fromRow(row);
      if (typed) _text.clear();
    } on CheckinException catch (e) {
      outcome = TicketOutcome.fromError(e);
    }
    if (!mounted) return;
    setState(() {
      _sending = false;
      _outcome = outcome;
      if (outcome.kind != NoticeKind.error) _taken.insert(0, outcome);
    });
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
