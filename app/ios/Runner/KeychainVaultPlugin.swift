// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The secrets at rest on an iPhone (lib/storage/secret_vault.dart, decisions
// PD6, PKA-4, IOSK-1 to IOSK-6): the same channel, methods, errors and sealed
// format as Android's KeystorePlugin.kt, so the Dart side is one code.
//
//   org.atalaia.app/keystore
//     "available" -> Bool: a key can be had and a round trip works.
//     "seal" {data: bytes} -> bytes: the 12-byte nonce, the ciphertext and
//         the 16-byte tag (AES-256-GCM, CryptoKit's `combined`).
//     "open" {data: bytes} -> bytes: the reverse.
//   Errors: "key_lost" (no key, or the data does not fit it: it can never be
//   read, and the app asks to join again) and "unavailable" (the Keychain
//   failed now, for example before the first unlock after a restart).
//
// The AES-256 key is one item in the app's Keychain (a generic password,
// service `org.atalaia.app.secrets`, account `v1`), with
// kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly: readable from the first
// unlock after a restart until the next restart, so a save that lands just as
// the screen locks still works (the app has no background modes today; a
// stricter class would fail there and drop the secrets); never copied into a
// backup, to iCloud Keychain or to another phone. No Face ID or passcode prompt, as
// Android's key asks for no user authentication. The sealed file stays in the
// app's private folder (secrets.enc, AppDelegate's filesDir); without this
// phone's Keychain item it opens to nothing. `open` never makes a key; only
// `seal` (and `available`) do, so a lost key is never replaced silently by
// one that cannot read the old data. The work runs on its own queue, off the
// main thread; the answers go back on the main thread.

import CryptoKit
import Flutter
import Foundation
import Security

final class KeychainVaultPlugin: NSObject {
  private static var instance: KeychainVaultPlugin?

  /// Called once per engine, from AppDelegate.
  static func register(messenger: FlutterBinaryMessenger) {
    instance = KeychainVaultPlugin(messenger: messenger)
  }

  private static let service = "org.atalaia.app.secrets"
  private static let account = "v1"
  private static let aad = Data("atalaia-secrets-v1".utf8)
  private static let nonceBytes = 12
  private static let tagBytes = 16

  private let channel: FlutterMethodChannel
  private let worker = DispatchQueue(label: "org.atalaia.app.keychain-vault")

  private init(messenger: FlutterBinaryMessenger) {
    channel = FlutterMethodChannel(
      name: "org.atalaia.app/keystore", binaryMessenger: messenger)
    super.init()
    channel.setMethodCallHandler { [weak self] call, result in
      guard let self = self else {
        result(FlutterMethodNotImplemented)
        return
      }
      self.handle(call, result)
    }
  }

  private enum VaultError: Error {
    case keyLost(String)
    case unavailable(String)
  }

  private func handle(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    let method = call.method
    guard ["available", "seal", "open"].contains(method) else {
      result(FlutterMethodNotImplemented)
      return
    }
    let data = ((call.arguments as? [String: Any])?["data"] as? FlutterStandardTypedData)?.data
    worker.async {
      let answer: Any?
      do {
        switch method {
        case "available":
          answer = try Self.available()
        case "seal":
          guard let data = data else { throw VaultError.unavailable("no data") }
          answer = FlutterStandardTypedData(bytes: try Self.seal(data))
        default:
          guard let data = data else { throw VaultError.unavailable("no data") }
          answer = FlutterStandardTypedData(bytes: try Self.open(data))
        }
      } catch VaultError.keyLost(let why) {
        answer = FlutterError(code: "key_lost", message: why, details: nil)
      } catch VaultError.unavailable(let why) {
        answer = FlutterError(code: "unavailable", message: why, details: nil)
      } catch {
        answer = FlutterError(code: "unavailable", message: "\(type(of: error))", details: nil)
      }
      DispatchQueue.main.async { result(answer) }
    }
  }

  private static func baseQuery() -> [String: Any] {
    [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrAccount as String: account,
    ]
  }

  /// The key, or nil when there is none. A Keychain that does not answer
  /// (locked since the restart) is "unavailable", not "no key".
  private static func existingKey() throws -> SymmetricKey? {
    var query = baseQuery()
    query[kSecReturnData as String] = true
    query[kSecMatchLimit as String] = kSecMatchLimitOne
    var item: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &item)
    switch status {
    case errSecSuccess:
      guard let bytes = item as? Data, bytes.count == 32 else {
        throw VaultError.keyLost("bad key item")
      }
      return SymmetricKey(data: bytes)
    case errSecItemNotFound:
      return nil
    default:
      throw VaultError.unavailable("keychain \(status)")
    }
  }

  private static func makeKey() throws -> SymmetricKey {
    let key = SymmetricKey(size: .bits256)
    var add = baseQuery()
    add[kSecValueData as String] = key.withUnsafeBytes { Data($0) }
    add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
    let status = SecItemAdd(add as CFDictionary, nil)
    if status == errSecDuplicateItem, let other = try existingKey() {
      return other  // made meanwhile: keep the one that is stored
    }
    guard status == errSecSuccess else { throw VaultError.unavailable("keychain \(status)") }
    return key
  }

  private static func available() throws -> Bool {
    // A real round trip: a Keychain that hands out a key it cannot use is not
    // available.
    let key = try existingKey() ?? makeKey()
    let probe = Data([1, 2, 3])
    do {
      return try open(seal(probe, key: key), key: key) == probe
    } catch VaultError.keyLost {
      return false
    }
  }

  private static func seal(_ plain: Data, key: SymmetricKey? = nil) throws -> Data {
    let k = try key ?? existingKey() ?? makeKey()
    let box = try AES.GCM.seal(plain, using: k, authenticating: aad)
    guard let combined = box.combined else { throw VaultError.unavailable("no nonce") }
    return combined
  }

  private static func open(_ sealed: Data, key: SymmetricKey? = nil) throws -> Data {
    if sealed.count < nonceBytes + tagBytes { throw VaultError.keyLost("short") }
    guard let k = try key ?? existingKey() else { throw VaultError.keyLost("no key") }
    do {
      let box = try AES.GCM.SealedBox(combined: sealed)
      return try AES.GCM.open(box, using: k, authenticating: aad)
    } catch {
      // The key is there but did not seal this, or the file was changed.
      throw VaultError.keyLost("bad tag")
    }
  }
}
