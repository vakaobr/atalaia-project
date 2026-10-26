// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Joining a game with a join payload (protocol/join.md, decision P3-10):
/// the GM console's QR code scanned with the camera, a join card held to
/// the phone's NFC reader, or the text form `atalaia:join:...` pasted. The
/// payload is checked with the field join key from the settings before
/// anything in it is used. The QR code pushes nothing: the phone reads and
/// acts (decision E3).
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../platform/services.dart';
import '../protocol/join_payload.dart';
import '../security/ndef.dart';
import '../ui/code_kind.dart';
import '../ui/settings_screen.dart';
import '../ui/widgets.dart';

/// The join payload in [text] or card [ndef], checked with [joinKey]; the
/// message key of what is wrong otherwise.
(JoinPayload?, String?) readJoin({
  String? text,
  List<int>? ndef,
  required List<int>? joinKey,
}) {
  if (joinKey == null) return (null, 'join.no_key');
  final List<int>? raw;
  try {
    raw = text != null
        ? joinFromText(text)
        : (ndef == null ? null : payloadFromNdefMessage(ndef, joinNdefType));
  } on JoinException {
    return (null, 'join.bad_text');
  }
  if (raw == null) return (null, 'join.not_a_card');
  try {
    final j = decodeJoin(raw, joinKey);
    if (j.kind != JoinKind.node) return (null, 'join.for_controller');
    return (j, null);
  } on JoinException catch (e) {
    return (
      null,
      switch (e.reason) {
        JoinFailure.mac => 'join.other_field',
        JoinFailure.length || JoinFailure.version => 'join.bad_text',
        JoinFailure.body => 'join.bad_body',
      },
    );
  }
}

class JoinScreen extends StatefulWidget {
  const JoinScreen({required this.title, super.key});

  final String title;

  @override
  State<JoinScreen> createState() => _JoinScreenState();
}

class _JoinScreenState extends State<JoinScreen> {
  final _text = TextEditingController();
  StreamSubscription<NfcRead>? _nfc;
  late final NfcService _nfcService = context.services.nfc;
  NfcState _nfcState = NfcState.unavailable;
  String? _error;

  @override
  void initState() {
    super.initState();
    _listen();
  }

  Future<void> _listen() async {
    final nfc = _nfcService;
    final state = await nfc.state();
    if (!mounted) return;
    setState(() => _nfcState = state);
    if (state != NfcState.ready) return;
    _nfc = nfc.reads.listen((r) => _try(ndef: r.ndef ?? const []));
    await nfc.startReading();
  }

  @override
  void dispose() {
    unawaited(_nfc?.cancel());
    if (_nfc != null) unawaited(_nfcService.stopReading());
    _text.dispose();
    super.dispose();
  }

  void _try({String? text, List<int>? ndef}) {
    final wrong = text == null
        ? null
        : wrongCodeMessage(text, CodeKind.joinCard);
    if (wrong != null) {
      setState(() => _error = wrong);
      return;
    }
    final key = AppScope.read(context).settings.joinKey;
    final (j, err) = readJoin(text: text, ndef: ndef, joinKey: key);
    if (j != null) {
      Navigator.pop(context, j);
    } else {
      setState(() => _error = err);
    }
  }

  Future<void> _scan() async {
    final s = context.s;
    final qr = context.services.qr;
    if (!await qr.available) {
      if (mounted) setState(() => _error = 'join.no_camera');
      return;
    }
    final text = await qr.scan(
      hint: s.t('join.scan_hint'),
      cancel: s.t('common.cancel'),
    );
    if (text != null && mounted) _try(text: text);
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final hasKey = context.app.settings.joinKey != null;
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(s.t('join.intro')),
          const SizedBox(height: 12),
          if (!hasKey)
            Notice(
              s.t('join.no_key'),
              kind: NoticeKind.warning,
              action: OutlinedButton(
                onPressed: () => Navigator.push(
                  context,
                  MaterialPageRoute<void>(
                    builder: (_) => const SettingsScreen(),
                  ),
                ),
                child: Text(s.t('settings.title')),
              ),
            ),
          if (_error != null && (_error != 'join.no_key' || hasKey))
            Notice(
              s.t(_error!),
              kind: NoticeKind.error,
              key: const Key('join-error'),
            ),
          const SizedBox(height: 8),
          FilledButton.icon(
            key: const Key('join-scan'),
            icon: const Icon(Icons.qr_code_scanner),
            label: Text(s.t('join.scan')),
            onPressed: _scan,
          ),
          const SizedBox(height: 16),
          ListTile(
            leading: Icon(
              Icons.nfc,
              color: _nfcState == NfcState.ready
                  ? Theme.of(context).colorScheme.primary
                  : Theme.of(context).disabledColor,
            ),
            title: Text(s.t('join.card')),
            subtitle: Text(switch (_nfcState) {
              NfcState.ready => s.t('join.card_ready'),
              NfcState.off => s.t('nfc.off'),
              NfcState.unavailable => s.t('nfc.none'),
            }),
          ),
          const SizedBox(height: 16),
          TextField(
            key: const Key('join-text'),
            controller: _text,
            maxLines: 3,
            decoration: InputDecoration(
              labelText: s.t('join.text'),
              hintText: 'atalaia:join:...',
            ),
          ),
          const SizedBox(height: 8),
          OutlinedButton(
            key: const Key('join-use-text'),
            onPressed: () => _try(text: _text.text),
            child: Text(s.t('join.use_text')),
          ),
          const SizedBox(height: 16),
          Text(
            s.t('join.warning'),
            style: TextStyle(color: Theme.of(context).hintColor),
          ),
        ],
      ),
    );
  }
}
