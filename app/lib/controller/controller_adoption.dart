// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Adopting boxes (protocol/adoption.md) on the Android field controller
/// (slice S7c of PE24, decisions PE24-93 and PE24-95): the Pi controller's
/// controller/atalaia_controller/adoption.py in Dart, for the GM console's
/// *Adopt* tab (`GET /api/v1/adopt`, `POST /api/v1/adopt/card`).
///
///   - **The NFC field card** ([fieldCard]): the bytes of an NTAG215/216
///     holding the field join key and the field's name, the field's master
///     secret, never cached. The phone can also write it with its own NFC
///     from the controller's screen (controller_screen.dart), which asks
///     here for the card so that it is recorded like the console's.
///   - **The USB cable** is not offered on a phone (decision PE24-95): the
///     answers are those of a Pi with `[adopt] usb = false`.
///   - **The pairing code over the radio** is controller_pairing.dart's; its
///     runs are recorded here too.
///
/// Every card made and every adoption is kept in the store's last 100
/// records (the setting `adoption.log`: method, box, result, never the key
/// or a PIN), the last 20 shown. GM token only.
library;

import 'dart:convert';

import '../protocol/field_card.dart';
import 'controller_engine.dart';

const adoptionLogSetting = 'adoption.log';
const adoptionLogMax = 100;
const previousFingerprintSetting = 'join_key.previous_fingerprint';

class ControllerAdoption {
  ControllerAdoption(this.engine) {
    engine.adoption = this;
  }

  final ControllerEngine engine;

  List<int> _key() {
    final key = engine.joinKey;
    if (key.length != fieldCardKeySize) {
      throw ControllerError.unavailable('no field join key on this controller');
    }
    return key;
  }

  /// The field's name for a card: the branding's `field_name` (the check-in
  /// poster's, decision BR4; controller_branding.dart, slice S7b), made fit
  /// for a card.
  String fieldName() {
    final svc = engine.checkin;
    final name =
        engine.branding?.fieldName() ??
        (svc == null ? 'Atalaia' : '${svc.posterFields()['field_name']}');
    return cleanFieldName(name);
  }

  Map<String, Object?> info() => {
    'fingerprint': fieldFingerprint(_key()),
    'field_name': fieldName(),
    'previous_fingerprint': engine.store.getSetting(previousFingerprintSetting),
    'usb': false,
    'usb_ports': const <String>[],
    'log': records().reversed.take(20).toList(),
  };

  List<Map<String, Object?>> records() {
    final raw = engine.store.getSetting(adoptionLogSetting);
    if (raw == null) return [];
    try {
      final out = jsonDecode(raw);
      return out is List
          ? [
              for (final e in out)
                if (e is Map) e.cast<String, Object?>(),
            ]
          : [];
    } on FormatException {
      return [];
    }
  }

  /// Keeps one adoption record (with its time, UTC, to the second).
  void record(Map<String, Object?> entry) {
    final t = DateTime.fromMillisecondsSinceEpoch(
      (engine.wallSeconds() * 1000).floor(),
      isUtc: true,
    );
    final at = '${t.toIso8601String().substring(0, 19)}Z';
    final all = [
      ...records(),
      {'at': at, ...entry},
    ];
    engine.store.setSetting(
      adoptionLogSetting,
      jsonEncode(
        all
            .skip(all.length > adoptionLogMax ? all.length - adoptionLogMax : 0)
            .toList(),
      ),
    );
  }

  /// The field card's bytes: the field's master secret.
  Map<String, Object?> fieldCard() {
    final key = _key();
    final name = fieldName();
    final payload = encodeFieldCard(key, name);
    final fp = fieldFingerprint(key);
    record({'method': 'card', 'result': 'card_made', 'field': fp});
    return {
      'fingerprint': fp,
      'field_name': name,
      'bytes': payload.length,
      'ndef_tag_hex': [
        for (final b in fieldCardTag(payload))
          b.toRadixString(16).padLeft(2, '0'),
      ].join(),
    };
  }

  /// USB adoption: not on a phone (decision PE24-95).
  Never usbOff() => throw ControllerError.unavailable(
    'USB adoption is off on this controller (a phone controller adopts boxes '
    'by field card or pairing code)',
  );
}
