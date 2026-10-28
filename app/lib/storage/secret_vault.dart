// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A vault for the few secrets the app keeps at rest (decisions PD6, PKA-4): the
/// field join key, the marshal's Ed25519 seed, the player's read code, the
/// phone controller's site API key, the player's secret at each field and the
/// site account's refresh token. On
/// Android it is an AES-256-GCM key made inside the AndroidKeyStore
/// (non-exportable; no user-authentication requirement, so the foreground
/// service and a boot-time start still work), reached through the
/// `org.atalaia.app/keystore` channel (KeystorePlugin.kt). Where the plugin
/// does not exist (iOS, tests), [available] is false and the store keeps its
/// earlier behaviour.
library;

import 'dart:typed_data';

/// Why the vault could not give a secret back.
enum VaultFailure {
  /// The key is gone or does not fit the data (app data restored on another
  /// phone, the key invalidated, a damaged file): the data can never be read.
  keyLost,

  /// The Keystore did not answer now (a locked or busy secure element, an
  /// internal error): the data may be readable later.
  unavailable,
}

final class VaultException implements Exception {
  const VaultException(this.failure, [this.detail = '']);

  final VaultFailure failure;
  final String detail;

  @override
  String toString() => 'VaultException(${failure.name}) $detail';
}

abstract interface class SecretVault {
  /// Whether secrets can be sealed on this device. False without the plugin.
  Future<bool> available();

  /// Seals [plain]; the answer is the nonce, the ciphertext and the tag.
  /// Throws [VaultException].
  Future<Uint8List> seal(Uint8List plain);

  /// Opens what [seal] returned. Throws [VaultException].
  Future<Uint8List> open(Uint8List sealed);
}
