// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// What the field controller's confirmation of a marshal looks like on the
// phone (decisions MR-2 to MR-5), for the tests that need readings recorded:
// the app records nothing for a phone the controller has not confirmed.

import 'package:atalaia_app/marshal/marshal_records.dart';
import 'package:atalaia_app/storage/app_store.dart';

/// Marks [records]' phone as confirmed by the controller of [fieldId] at [at]
/// (now by default) for [validFor], with the id and name already in its
/// settings and the key it holds now.
void trustMarshal(
  MarshalRecords records, {
  DateTime? at,
  Duration validFor = const Duration(hours: 2),
  String? fieldId,
}) {
  final s = records.settings;
  final t = (at ?? DateTime.now()).millisecondsSinceEpoch;
  s.marshalValidation = MarshalValidation(
    marshalId: s.marshalId,
    name: s.marshalName,
    fieldId: fieldId ?? s.fieldId,
    publicKey: records.publicKeyBase64!,
    validatedAtMs: t,
    validUntilMs: t + validFor.inMilliseconds,
  );
}
