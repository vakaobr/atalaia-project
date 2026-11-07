// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Proof that a self check-in comes from the phone that registered
/// (decisions TKB-1 to TKB-8; protocol/checkin.md, "The registering phone"):
/// the Dart side of controller/atalaia_controller/checkin_binding.py,
/// checked against the same vectors (the `binding` part of
/// protocol/vectors/checkin.json).
///
/// The app makes an Ed25519 key pair for each registration it keeps a ticket
/// for, keeps the private key sealed (`TicketStore`) and gives the site
/// server the public key; the roster brings it to the controller as
/// `binding_key`. At check-in the app signs the controller's challenge:
///
/// ```
/// atalaia-checkin-binding-v1 LF challenge LF game_id LF registration_id
///   LF player_id LF sha256_hex(player_secret)
/// ```
///
/// and sends `"binding": {"challenge", "signature"}` (base64url without
/// padding). The phone controller issues the challenges ([Challenges]) and
/// verifies the proof ([verifyBinding]) as the Pi does.
library;

import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';
import 'package:cryptography/dart.dart';

import '../security/bytes.dart';

final _ed25519 = DartEd25519();

const String bindingMessagePrefix = 'atalaia-checkin-binding-v1';
const int challengeTtl = 300;
const int _skew = 5;
const List<int> _domain = [
  // "atalaia checkin challenge v1"
  0x61, 0x74, 0x61, 0x6c, 0x61, 0x69, 0x61, 0x20, 0x63, 0x68, 0x65, 0x63, //
  0x6b, 0x69, 0x6e, 0x20, 0x63, 0x68, 0x61, 0x6c, 0x6c, 0x65, 0x6e, 0x67, //
  0x65, 0x20, 0x76, 0x31,
];
final challengeRe = RegExp(r'^[A-Za-z0-9_-]{43}$');
final _signatureRe = RegExp(r'^[A-Za-z0-9_-]{86}$');

/// The detail of a 409 for a challenge the controller did not give or that
/// is too old: the app fetches a new one and sends the check-in again.
const String challengeExpired =
    'binding_challenge_expired: the check-in challenge is unknown or too old '
    '(GET /api/v1/checkin/challenge)';

/// What the registering phone signs.
Uint8List bindingMessage({
  required String challenge,
  required int gameId,
  required String registrationId,
  required String playerId,
  required List<int> playerSecret,
}) => Uint8List.fromList(
  utf8.encode(
    [
      bindingMessagePrefix,
      challenge,
      '$gameId',
      registrationId,
      playerId,
      hexEncode(crypto.sha256.convert(playerSecret).bytes),
    ].join('\n'),
  ),
);

/// A registration's key pair on the phone: [seed] is the private key.
final class BindingKey {
  BindingKey._(this.seed, this.publicKey, this._pair);

  final Uint8List seed;

  /// The 32-byte public key the site server and the roster carry.
  final Uint8List publicKey;
  final SimpleKeyPair _pair;

  /// The public key as the sync sends it: standard base64 with padding.
  String get publicKeyText => base64.encode(publicKey);

  /// The seed as the app keeps it: base64url without padding.
  String get seedText => base64UrlNoPad(seed);

  static Future<BindingKey> generate([Random? random]) {
    final r = random ?? Random.secure();
    return fromSeed(List<int>.generate(32, (_) => r.nextInt(256)));
  }

  static Future<BindingKey> fromSeed(List<int> seed) async {
    if (seed.length != 32) throw ArgumentError('an Ed25519 seed is 32 bytes');
    final pair = await _ed25519.newKeyPairFromSeed(seed);
    final public = await pair.extractPublicKey();
    return BindingKey._(
      Uint8List.fromList(seed),
      Uint8List.fromList(public.bytes),
      pair,
    );
  }

  /// From [seedText], or null when it is not a 32-byte seed.
  static Future<BindingKey?> fromText(String? seedText) async {
    final raw = seedText == null ? null : base64UrlNoPadDecode(seedText);
    if (raw == null || raw.length != 32) return null;
    return fromSeed(raw);
  }

  /// The check-in's `binding` member for [challenge].
  Future<Map<String, String>> prove({
    required String challenge,
    required int gameId,
    required String registrationId,
    required String playerId,
    required List<int> playerSecret,
  }) async {
    final sig = await _ed25519.sign(
      bindingMessage(
        challenge: challenge,
        gameId: gameId,
        registrationId: registrationId,
        playerId: playerId,
        playerSecret: playerSecret,
      ),
      keyPair: _pair,
    );
    return {'challenge': challenge, 'signature': base64UrlNoPad(sig.bytes)};
  }
}

/// A binding key as the roster carries it (32 bytes in canonical standard
/// base64), or null.
Uint8List? bindingPublicKey(Object? text) {
  if (text is! String || text.length != 44) return null;
  final raw = base64DecodeCanonical(text);
  return raw != null && raw.length == 32 ? raw : null;
}

/// `{"challenge", "signature"}`: the challenge's text and the 64-byte
/// signature; throws [FormatException] for another shape.
(String, Uint8List) parseBindingProof(Object? value) {
  if (value is! Map ||
      value.length != 2 ||
      !value.containsKey('challenge') ||
      !value.containsKey('signature')) {
    throw const FormatException('binding: {challenge, signature}');
  }
  final challenge = value['challenge'];
  final signature = value['signature'];
  if (challenge is! String || !challengeRe.hasMatch(challenge)) {
    throw const FormatException(
      "binding.challenge: the controller's challenge (43 characters)",
    );
  }
  final raw = signature is String && _signatureRe.hasMatch(signature)
      ? base64UrlNoPadDecode(signature)
      : null;
  if (raw == null || raw.length != 64 || base64UrlNoPad(raw) != signature) {
    throw const FormatException(
      'binding.signature: 64 bytes in base64url without padding '
      '(86 characters)',
    );
  }
  return (challenge, raw);
}

/// Whether [signature] is the binding key [keyText]'s Ed25519 signature of
/// [message] (false for a bad key).
Future<bool> verifyBinding(
  Object? keyText,
  List<int> message,
  List<int> signature,
) async {
  final key = bindingPublicKey(keyText);
  if (key == null || signature.length != 64) return false;
  try {
    return await _ed25519.verify(
      message,
      signature: Signature(
        signature,
        publicKey: SimplePublicKey(key, type: KeyPairType.ed25519),
      ),
    );
  } on Object {
    return false;
  }
}

/// The controller's check-in challenges, keeping nothing per challenge: 8
/// bytes of its clock's seconds, 8 random bytes and the first 16 bytes of
/// HMAC-SHA256(a key made at start, the domain | those 16 bytes).
class Challenges {
  Challenges({int Function()? clock, List<int>? key, this.ttl = challengeTtl})
    : _clock = clock ?? _monotonic,
      _key = key ?? _randomBytes(32);

  final int Function() _clock;
  final List<int> _key;
  final int ttl;

  static final _watch = Stopwatch()..start();
  static int _monotonic() => _watch.elapsed.inSeconds;

  static List<int> _randomBytes(int n) {
    final r = Random.secure();
    return List<int>.generate(n, (_) => r.nextInt(256));
  }

  List<int> _mac(List<int> head) => crypto.Hmac(
    crypto.sha256,
    _key,
  ).convert([..._domain, ...head]).bytes.sublist(0, 16);

  /// A new challenge, with [nonce] (8 bytes) for tests.
  String issue([List<int>? nonce]) {
    final head = ByteData(8)..setUint64(0, max(0, _clock()));
    final bytes = [...head.buffer.asUint8List(), ...(nonce ?? _randomBytes(8))];
    return base64UrlNoPad([...bytes, ..._mac(bytes)]);
  }

  bool valid(Object? text) {
    if (text is! String || !challengeRe.hasMatch(text)) return false;
    final raw = base64UrlNoPadDecode(text);
    if (raw == null || raw.length != 32) return false;
    final head = raw.sublist(0, 16);
    if (!constantTimeEquals(raw.sublist(16), _mac(head))) return false;
    final at = ByteData.sublistView(Uint8List.fromList(head)).getUint64(0);
    final age = _clock() - at;
    return age >= -_skew && age <= ttl;
  }
}

/// A registered row's app check-in as staff see it: `bound`, `unbound`, or
/// null with no app check-in on a registration (checkin_binding.state).
String? bindingState(Map<String, Object?> row) {
  if (row['registration_id'] == null || row['app_checkin_at'] == null) {
    return null;
  }
  return row['app_bound'] == true ? 'bound' : 'unbound';
}
