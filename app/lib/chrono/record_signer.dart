// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Signing and verifying chrono readings with the marshal's Ed25519 key
/// (ADR-P3-7 as changed by decision P3-1; protocol/chrono-record.md).
///
/// ```
/// signature = base64(Ed25519.sign(marshal_key, canonical_json(reading without "signature")))
/// ```
///
/// Ed25519 is RFC 8032's pure variant (no pre-hash, no context), from the
/// `cryptography` package's pure-Dart implementation, so it behaves the same
/// on Android, iOS and the desktop test runner. The controller verifies with
/// `controller/atalaia_controller/chrono.py`; both check
/// protocol/vectors/chrono_record.json.
library;

import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:cryptography/dart.dart';

import '../security/bytes.dart';
import 'reading.dart';

final _ed25519 = DartEd25519();

/// Why a record failed verification; [name] is the protocol's reason string.
enum ChronoFailure { format, unsigned, signature }

class ChronoVerifyException implements Exception {
  ChronoVerifyException(this.reason, this.message);

  final ChronoFailure reason;
  final String message;

  @override
  String toString() => 'ChronoVerifyException(${reason.name}): $message';
}

/// A marshal's Ed25519 key pair. The 32-byte [seed] is the private key
/// (RFC 8032): keep it in the phone's secure storage, never in a record.
class MarshalKey {
  MarshalKey._(this._seed, this.publicKey, this._pair);

  final Uint8List _seed;

  /// The 32-byte public key that verifies this marshal's records.
  final Uint8List publicKey;
  final SimpleKeyPair _pair;

  /// The private key; only for storing it.
  Uint8List get seed => Uint8List.fromList(_seed);

  /// A new key pair from a secure random seed.
  static Future<MarshalKey> generate([math.Random? random]) {
    final r = random ?? math.Random.secure();
    return fromSeed(List<int>.generate(32, (_) => r.nextInt(256)));
  }

  /// The key pair of a stored 32-byte [seed].
  static Future<MarshalKey> fromSeed(List<int> seed) async {
    if (seed.length != 32) {
      throw ArgumentError('an Ed25519 seed is 32 bytes');
    }
    final pair = await _ed25519.newKeyPairFromSeed(seed);
    final public = await pair.extractPublicKey();
    return MarshalKey._(
      Uint8List.fromList(seed),
      Uint8List.fromList(public.bytes),
      pair,
    );
  }
}

/// Raw Ed25519: the 64-byte signature of [message].
Future<Uint8List> ed25519Sign(MarshalKey key, List<int> message) async {
  final sig = await _ed25519.sign(message, keyPair: key._pair);
  return Uint8List.fromList(sig.bytes);
}

/// Raw Ed25519: whether [signature] is [publicKey]'s signature of [message].
/// Non-canonical signatures (S not below the group order) are refused.
Future<bool> ed25519Verify(
  List<int> publicKey,
  List<int> message,
  List<int> signature,
) async {
  if (publicKey.length != 32 || signature.length != 64) return false;
  return _ed25519.verify(
    message,
    signature: Signature(
      signature,
      publicKey: SimplePublicKey(publicKey, type: KeyPairType.ed25519),
    ),
  );
}

/// [reading] signed by [key] (any earlier signature is replaced).
Future<ChronoReading> signReading(ChronoReading reading, MarshalKey key) async {
  final sig = await ed25519Sign(key, reading.canonicalBytes());
  return reading.withSignature(base64.encode(sig));
}

/// Checks that [publicKey] signed [reading]; throws [ChronoVerifyException].
Future<ChronoReading> verifyReading(
  ChronoReading reading,
  List<int> publicKey,
) async {
  final text = reading.signature;
  if (text == null) {
    throw ChronoVerifyException(
      ChronoFailure.unsigned,
      'the record has no signature',
    );
  }
  final sig = text.length == 88 ? base64DecodeCanonical(text) : null;
  if (sig == null || sig.length != 64) {
    throw ChronoVerifyException(
      ChronoFailure.format,
      'the signature is 64 bytes in canonical base64 (88 characters)',
    );
  }
  if (!await ed25519Verify(publicKey, reading.canonicalBytes(), sig)) {
    throw ChronoVerifyException(
      ChronoFailure.signature,
      "the signature does not match the marshal's key",
    );
  }
  return reading;
}

/// A record from its decoded JSON object, checked and verified with the
/// marshal's [publicKey]; throws [ChronoVerifyException]. The checks run in
/// the protocol's order: the fields (format), the signature's presence
/// (unsigned) and form (format), then Ed25519 (signature).
Future<ChronoReading> verifyRecordJson(
  Object? json,
  List<int> publicKey,
) async {
  final ChronoReading reading;
  try {
    reading = ChronoReading.fromJson(json);
  } on ChronoFormatException catch (e) {
    throw ChronoVerifyException(ChronoFailure.format, e.message);
  }
  return verifyReading(reading, publicKey);
}

/// [verifyRecordJson] on a record's JSON text.
Future<ChronoReading> verifyRecordText(String text, List<int> publicKey) async {
  final Object? json;
  try {
    json = jsonDecode(text);
  } on FormatException catch (e) {
    throw ChronoVerifyException(ChronoFailure.format, 'not JSON: ${e.message}');
  }
  return verifyRecordJson(json, publicKey);
}
