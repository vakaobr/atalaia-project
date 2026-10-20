// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The check-in ticket's text (protocol/checkin.md, ADR-P4-11): the Dart
/// side of controller/atalaia_controller/checkin_ticket.py, checked against
/// the same vectors (the `tickets` part of protocol/vectors/checkin.json).
///
///     atalaia:ticket:<base64url, no padding, of: version (1) | CBOR map>
///
/// A site server gives each registration for a scheduled game a random
/// 32-byte secret and keeps only its SHA-256, which the field controller gets
/// in the roster. The app keeps the secret and sends it with its check-in; a
/// printed ticket (a QR code of this text) is shown to a marshal instead.
/// It only matches an arrival to a registration: it is no game credential.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'cbor.dart';

const int ticketVersion = 1;
const int ticketMaxLength = 128;
const String ticketTextPrefix = 'atalaia:ticket:';

/// Why a ticket is refused: its text, its length, its version or its body.
enum TicketFailure { text, length, version, body }

class TicketException implements Exception {
  TicketException(this.reason, this.message);
  final TicketFailure reason;
  final String message;
  @override
  String toString() => 'TicketException(${reason.name}): $message';
}

final _uuid = RegExp(
  r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
);
final _playerId = RegExp(r'^p-[a-z2-7]{12}$');

final class CheckinTicket {
  CheckinTicket({
    required this.registrationId,
    required this.playerId,
    required this.secret,
  });

  /// The site server's registration (a lowercase UUID).
  final String registrationId;

  /// The player's id at the field (`p-` and 12 of a-z 2-7).
  final String playerId;

  /// The 32-byte ticket secret.
  final Uint8List secret;

  /// The secret as a check-in sends it: base64url without padding.
  String get secretText => base64Url.encode(secret).replaceAll('=', '');

  @override
  String toString() => 'CheckinTicket($registrationId, $playerId)';
}

TicketException _body(String why) => TicketException(TicketFailure.body, why);

CheckinTicket _validate(Object? rid, Object? pid, Object? secret) {
  if (rid == null || pid == null || secret == null) {
    throw _body('missing ticket fields');
  }
  if (rid is! String || !_uuid.hasMatch(rid)) {
    throw _body('registration_id: a lowercase UUID');
  }
  if (pid is! String || !_playerId.hasMatch(pid)) {
    throw _body('player_id: p- and 12 of a-z 2-7');
  }
  if (secret is! Uint8List || secret.length != 32) {
    throw _body('secret: 32 bytes');
  }
  return CheckinTicket(registrationId: rid, playerId: pid, secret: secret);
}

/// The ticket in [data] (version byte and CBOR body). Throws [TicketException].
CheckinTicket decodeTicket(List<int> data) {
  if (data.length < 2 || data.length > ticketMaxLength) {
    throw TicketException(
      TicketFailure.length,
      'a ticket is 2 to $ticketMaxLength bytes, not ${data.length}',
    );
  }
  if (data[0] != ticketVersion) {
    throw TicketException(
      TicketFailure.version,
      'unknown ticket version ${data[0]}',
    );
  }
  final Object? raw;
  try {
    raw = cborDecode(data.sublist(1), allowBytes: true);
  } on CborException catch (e) {
    throw _body('ticket body: ${e.message}');
  }
  if (raw is! Map) throw _body('the ticket body is a map');
  final f = <int, Object?>{};
  for (final e in raw.entries) {
    final k = e.key;
    if (k is! int || k < 0 || k >= 32) {
      throw _body('ticket key $k: keys are integers below 32');
    }
    // 0 and 4-31: kept for later optional fields.
    if (k < 1 || k > 3) continue;
    final v = e.value;
    if (v == null) throw _body('key $k is null');
    if (k == 3 ? v is! Uint8List : v is! String) {
      throw _body('key $k has the wrong type');
    }
    f[k] = v;
  }
  return _validate(f[1], f[2], f[3]);
}

/// The version byte and the body, keys in order, shortest form.
Uint8List encodeTicket(CheckinTicket t) {
  final v = _validate(t.registrationId, t.playerId, t.secret);
  return Uint8List.fromList([
    ticketVersion,
    ...cborEncode(<int, Object?>{
      1: v.registrationId,
      2: v.playerId,
      3: v.secret,
    }),
  ]);
}

String ticketToText(List<int> data) =>
    ticketTextPrefix + base64Url.encode(data).replaceAll('=', '');

/// The payload in a ticket text; spaces and line ends around it are ignored.
Uint8List ticketFromText(String text) {
  final t = text.trim();
  if (!t.startsWith(ticketTextPrefix)) {
    throw TicketException(
      TicketFailure.text,
      'a ticket text starts with $ticketTextPrefix',
    );
  }
  final b64 = t.substring(ticketTextPrefix.length);
  if (b64.isEmpty ||
      b64.length % 4 == 1 ||
      !RegExp(r'^[A-Za-z0-9_-]*$').hasMatch(b64)) {
    throw TicketException(TicketFailure.text, 'not base64url');
  }
  final Uint8List raw;
  try {
    raw = base64Url.decode(b64.padRight((b64.length + 3) ~/ 4 * 4, '='));
  } on FormatException {
    throw TicketException(TicketFailure.text, 'not base64url');
  }
  if (ticketToText(raw) != ticketTextPrefix + b64) {
    throw TicketException(TicketFailure.text, 'not canonical base64url');
  }
  return raw;
}

/// A ticket from its text (a printed QR code), checked.
CheckinTicket parseTicket(String text) => decodeTicket(ticketFromText(text));

/// Whether [text] looks like a check-in ticket (before any check).
bool isTicketText(String text) => text.trim().startsWith(ticketTextPrefix);
