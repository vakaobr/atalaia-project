// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Whether this phone may act as a marshal (decisions MR-1 to MR-14,
/// ADR-P3-13): the field controller decides. A marshal is someone on the
/// list the GM makes; the controller gives the id and name
/// (`GET /api/v1/checkin/me` says `marshal: {marshal_id, name, public_key,
/// valid_for_s}` to a player with the marshal role) and takes this phone's
/// signing key for that id and no other (`PUT /api/v1/checkin/me/marshal-key`).
/// The marshal never types an id.
///
/// Online, the controller's answer is the rule: a player not on the list is
/// refused and a marshal the GM took off the list loses the confirmation at
/// once (their unsent readings stay on the phone). Offline, a confirmation
/// made earlier on this field, for this key, still holds until `valid_for_s`
/// (2 hours) after it was made; with none, or a run-out one, the phone is
/// not a marshal until it reaches the controller again (MR-4).
library;

import 'package:flutter/foundation.dart';

import '../checkin/checkin_client.dart';
import '../checkin/my_replicas.dart';
import '../storage/app_store.dart';
import 'marshal_records.dart';

enum MarshalStatus {
  /// Asking the controller.
  checking,

  /// The controller confirmed this phone as a marshal just now.
  validated,

  /// The controller could not be reached; an earlier confirmation still holds.
  validatedOffline,

  /// Checked in, but not on the GM's marshal list (or not given the role).
  notListed,

  /// Was a marshal here, and the GM took the marshal off the list.
  revoked,

  /// The controller could not be reached and this phone was never confirmed here.
  offlineNeverValidated,

  /// The controller could not be reached and the earlier confirmation ran out.
  offlineExpired,

  /// No check-in at a field this phone trusts: there is no controller to ask.
  noCheckin,

  /// The check-in's token is no longer valid: check in again.
  sessionExpired,

  /// The controller answered with something else (see [MarshalAccess.error]).
  error,
}

/// How often the open marshal screens ask the controller again (MR-4): well
/// inside the controller's `valid_for_s` (2 hours), so a marshal working on
/// the field's network never runs out, while one away from it does.
const renewEvery = Duration(minutes: 10);

class MarshalAccess extends ChangeNotifier {
  MarshalAccess({
    required this.settings,
    required this.records,
    required this.persist,
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now;

  final AppSettings settings;
  final MarshalRecords records;

  /// Saves [settings] (and tells whoever listens to them).
  final Future<void> Function() persist;
  final DateTime Function() _now;

  MarshalStatus status = MarshalStatus.checking;
  String? error;

  bool get allowed =>
      status == MarshalStatus.validated ||
      status == MarshalStatus.validatedOffline;

  MarshalValidation? get validation => settings.marshalValidation;

  MarshalStatus _set(MarshalStatus s, [String? why]) {
    status = s;
    error = why;
    notifyListeners();
    return s;
  }

  /// Asks the controller about this player's check-in [c] and settles
  /// [status]. [saveCheckin] keeps the check-in when its token or role
  /// changed. [quiet] (the renewal every [renewEvery] while the marshal
  /// screens are open) does not show "checking" first, so the screens do not
  /// flicker while the marshal works.
  Future<MarshalStatus> validate(
    CheckinClient client,
    FieldCheckin c, {
    Future<void> Function()? saveCheckin,
    bool quiet = false,
  }) async {
    if (!quiet) _set(MarshalStatus.checking);
    Map<String, Object?> me;
    try {
      try {
        me = await client.me(c.token);
      } on CheckinException catch (e) {
        if (e.status != 401) rethrow;
        // A token past its time: a new one, once, if the controller still gives it.
        c.update(await client.refresh(c.token));
        await saveCheckin?.call();
        me = await client.me(c.token);
      }
      if (me['stale_token'] == true) {
        // The GM changed the role since the token was made, and the key is
        // taken from a token that says "marshal" (a promotion needs a new one).
        c.update(await client.refresh(c.token));
        await saveCheckin?.call();
        me = await client.me(c.token);
      }
    } on CheckinException catch (e) {
      if (e.offline || e.status >= 500) {
        return _set(offlineStatus(c.fieldId));
      }
      if (e.status == 401) return _set(MarshalStatus.sessionExpired);
      return _set(MarshalStatus.error, e.message);
    }
    final role = '${me['role']}';
    if (role != c.role) {
      c.role = role;
      await saveCheckin?.call();
    }
    return applyMe(client, c, me);
  }

  /// What the controller said in `GET /api/v1/checkin/me` [me]: a marshal
  /// has `marshal` there. Registers this phone's key when the controller
  /// does not hold it, then remembers the confirmation.
  Future<MarshalStatus> applyMe(
    CheckinClient client,
    FieldCheckin c,
    Map<String, Object?> me,
  ) async {
    final m = me['marshal'];
    if (me['role'] != 'marshal' || m is! Map) {
      return _set(await _deny());
    }
    final id = '${m['marshal_id']}';
    final name = '${m['name']}';
    if (!records.hasKey) await records.newKey();
    final key = records.publicKeyBase64!;
    try {
      if (m['public_key'] != key) {
        await client.registerMarshalKey(
          c.token,
          publicKeyBase64: key,
          marshalId: id,
        );
      }
    } on CheckinException catch (e) {
      if (e.offline || e.status >= 500) {
        return _set(offlineStatus(c.fieldId));
      }
      if (e.status == 403 || e.status == 409) return _set(await _deny());
      return _set(MarshalStatus.error, e.message);
    }
    final now = _now().millisecondsSinceEpoch;
    final valid = m['valid_for_s'];
    final seconds = valid is int && valid > 0 ? valid : 2 * 3600;
    settings
      ..marshalId = id
      ..marshalName = name
      ..fieldId = c.fieldId
      ..marshalValidation = MarshalValidation(
        marshalId: id,
        name: name,
        fieldId: c.fieldId,
        publicKey: key,
        validatedAtMs: now,
        validUntilMs: now + seconds * 1000,
      );
    // A marshal needs no join key (the controller signs the tags, TW-1); one
    // stays only for the phone controller (APX-1).
    if (settings.joinKeyUse != AppSettings.joinKeyForController) {
      settings
        ..joinKeyHex = null
        ..joinKeyUse = null;
    }
    await persist();
    return _set(MarshalStatus.validated);
  }

  /// The controller's "no": nothing keeps this phone acting as a marshal. A
  /// phone that had been confirmed here was revoked; the readings it took
  /// stay (they are sent if the GM adds the marshal again).
  Future<MarshalStatus> _deny() async {
    final had = settings.marshalValidation != null;
    settings
      ..marshalValidation = null
      ..marshalId = ''
      ..marshalName = '';
    await persist();
    return had ? MarshalStatus.revoked : MarshalStatus.notListed;
  }

  /// The controller cannot be reached: an earlier confirmation of this key on
  /// this field holds until it runs out (MR-4).
  MarshalStatus offlineStatus(String fieldId) {
    final v = settings.marshalValidation;
    if (v == null ||
        v.fieldId != fieldId ||
        v.publicKey != records.publicKeyBase64 ||
        v.marshalId != settings.marshalId) {
      return MarshalStatus.offlineNeverValidated;
    }
    return records.authorized
        ? MarshalStatus.validatedOffline
        : MarshalStatus.offlineExpired;
  }

  /// No controller to ask: not checked in anywhere this phone trusts.
  void noCheckin() => _set(MarshalStatus.noCheckin);
}
