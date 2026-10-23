// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The boxes' parts of the phone controller's screen (slice S7c of PE24):
/// the field card and the firmware release keys.
///
/// The NFC field card is written by the phone's own NFC (decision PE24-93):
/// on the controller's screen, after the
/// warning that the card is the field's master secret, the screen asks the
/// running controller for the card (`POST /api/v1/adopt/card` on the
/// loopback address with the GM token, so that it is recorded with the
/// other adoptions, controller_adoption.dart) and writes its one NDEF record
/// (application/vnd.atalaia.field, protocol/adoption.md section 4) to the
/// next NTAG215/216 held to the phone. The GM console shows the same bytes
/// for any other writer. The release keys ([FirmwareKeysTile], decision
/// PE24-96) are kept in the app's settings and given to the controller at
/// its start.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../platform/services.dart';
import '../protocol/field_card.dart';
import '../protocol/firmware_release.dart' show releasePublicKey;
import '../security/bytes.dart';
import '../security/ndef.dart';
import '../ui/widgets.dart';

/// The NDEF message to write, from the controller's answer to
/// `POST /api/v1/adopt/card` (its tag memory, `ndef_tag_hex`), checked to
/// be a field card.
Uint8List fieldCardMessageFrom(Map<String, Object?> card) {
  final mem = hexDecode(card['ndef_tag_hex']! as String);
  final payload = payloadFromType2Memory(mem, fieldCardNdefType);
  if (payload == null) throw const FormatException('not a field card');
  decodeFieldCard(payload); // its check holds
  return fieldCardNdefMessage(payload);
}

/// Asks this phone's running controller for the field card.
Future<Map<String, Object?>> requestFieldCard(int port, String gmToken) async {
  final client = HttpClient();
  try {
    final req = await client.post('127.0.0.1', port, '/api/v1/adopt/card');
    req.headers.set(HttpHeaders.authorizationHeader, 'Bearer $gmToken');
    final res = await req.close();
    final text = await utf8.decodeStream(res);
    if (res.statusCode != 200) {
      throw HttpException('${res.statusCode}: $text');
    }
    return (jsonDecode(text) as Map).cast<String, Object?>();
  } finally {
    client.close(force: true);
  }
}

class FieldCardTile extends StatefulWidget {
  const FieldCardTile({required this.makeCard, super.key});

  /// The controller's answer to `POST /api/v1/adopt/card`.
  final Future<Map<String, Object?>> Function() makeCard;

  @override
  State<FieldCardTile> createState() => _FieldCardTileState();
}

class _FieldCardTileState extends State<FieldCardTile> {
  var _writing = false;
  String? _error;
  String? _done;

  Future<void> _write() async {
    final s = context.s;
    final nfc = context.services.nfc;
    final go = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(s.t('ctl.card_warn_title')),
        content: Text(s.t('ctl.card_warn')),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(s.t('common.cancel')),
          ),
          FilledButton(
            key: const Key('ctl-card-go'),
            onPressed: () => Navigator.pop(context, true),
            child: Text(s.t('ctl.card_write_go')),
          ),
        ],
      ),
    );
    if (go != true || !mounted) return;
    final state = await nfc.state();
    if (state != NfcState.ready) {
      setState(() {
        _error = state == NfcState.off ? 'nfc.off' : 'nfc.none';
        _done = null;
      });
      return;
    }
    setState(() {
      _writing = true;
      _error = null;
      _done = null;
    });
    try {
      final card = await widget.makeCard();
      await nfc.writeNext(fieldCardMessageFrom(card));
      if (mounted) setState(() => _done = '${card['fingerprint']}');
    } on NfcWriteException catch (e) {
      if (mounted && e.reason != 'cancelled') {
        setState(() => _error = 'tags.write_${e.reason}');
      }
    } on Object {
      if (mounted) setState(() => _error = 'ctl.card_failed');
    } finally {
      if (mounted) setState(() => _writing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(s.t('ctl.card_hint')),
        const SizedBox(height: 8),
        if (_error != null) Notice(s.t(_error!), kind: NoticeKind.error),
        if (_done != null)
          Notice(
            s.t('ctl.card_done', {'fingerprint': _done}),
            kind: NoticeKind.ok,
          ),
        if (_writing) ...[
          Text(s.t('tags.hold')),
          const LinearProgressIndicator(),
          TextButton(
            key: const Key('ctl-card-cancel'),
            onPressed: context.services.nfc.cancelWrite,
            child: Text(s.t('common.cancel')),
          ),
        ] else
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              key: const Key('ctl-card-write'),
              icon: const Icon(Icons.nfc),
              label: Text(s.t('ctl.card_write')),
              onPressed: _write,
            ),
          ),
      ],
    );
  }
}

/// The firmware release keys a phone controller trusts (slice S7c, decision
/// PE24-96; the Pi's `[firmware] release_keys`): kept in the app's settings,
/// given to the controller at its start ([onChanged] restarts a running
/// one).
class FirmwareKeysTile extends StatelessWidget {
  const FirmwareKeysTile({required this.onChanged, super.key});

  final Future<void> Function(List<String> keys) onChanged;

  Future<void> _edit(BuildContext context) async {
    final s = context.s;
    final app = AppScope.read(context);
    final result = await promptText(
      context,
      title: s.t('ctl.fw_keys'),
      body: s.t('ctl.fw_keys_hint'),
      fieldKey: const Key('ctl-fw-keys-field'),
      monospace: true,
      maxLines: 4,
      actions: [
        (s.t('settings.join_key_clear'), (_) => '', false),
        (s.t('common.cancel'), (_) => null, false),
        (s.t('common.save'), (t) => t, true),
      ],
    );
    if (result == null || !context.mounted) return;
    final keys = [
      for (final w in result.split(RegExp(r'[\s,]+')))
        if (w.isNotEmpty) w,
    ];
    if (keys.length > 8 || keys.any((k) => releasePublicKey(k) == null)) {
      showMessage(context, s.t('ctl.fw_keys_bad'));
      return;
    }
    await app.update((x) => x.firmwareKeys = keys);
    await onChanged(keys);
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final keys = AppScope.of(context).settings.firmwareKeys;
    return ListTile(
      key: const Key('ctl-fw-keys'),
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.verified),
      title: Text(s.t('ctl.fw_keys')),
      subtitle: Text(
        keys.isEmpty
            ? s.t('ctl.fw_keys_none')
            : s.t('ctl.fw_keys_set', {'n': keys.length}),
      ),
      trailing: const Icon(Icons.edit),
      onTap: () => _edit(context),
    );
  }
}
