// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Passkeys on iOS: the twin of Android's PasskeyPlugin.kt (decisions PKA-1 and
// IOSL-2). Same channel and contract:
//
//   org.atalaia.app/passkeys
//     "available"                 -> Bool   : iOS 16 or later (passkeys).
//     "create" {request: String}  -> String : the registration response JSON.
//     "get"    {request: String}  -> String : the authentication response JSON.
//   Errors (FlutterError code): "cancelled" (the person closed the sheet),
//   "unsupported" (before iOS 16, or the system does not handle the request),
//   "failed" (anything else, a bad request included). Android's
//   "no_credential" has no iOS twin: with no passkey for the site the system
//   sheet offers another phone or a security key, and closing it is
//   "cancelled".
//
// `request` is the WebAuthn options JSON the site server made (py-webauthn's
// options_to_json: every binary field base64url), the answer the credential
// JSON the site server verifies (`id`, `rawId`, `type`, `response` with
// base64url fields): the shapes `navigator.credentials.create/get` give a
// browser, which Android's Credential Manager also returns. The app keeps no
// key. The relying party is the options' own `rp.id` / `rpId` (the site's
// host), which the app must be associated with: the site's
// /.well-known/apple-app-site-association (webcredentials, the server's
// ATALAIA_APP_IOS_APP_IDS) and `webcredentials:<host>` in the app's
// associated domains (Runner.entitlements). The system writes
// `https://<rp id>` as the origin in clientDataJSON, as a browser would.

import AuthenticationServices
import Flutter
import UIKit

@MainActor
final class PasskeyPlugin: NSObject {
  private static var instance: PasskeyPlugin?

  /// Called once per engine, from AppDelegate.
  static func register(messenger: FlutterBinaryMessenger) {
    instance = PasskeyPlugin(messenger: messenger)
  }

  /// Passkeys need iOS 16 (the platform provider exists on 15, without them).
  nonisolated static var supported: Bool {
    if #available(iOS 16.0, *) { return true }
    return false
  }

  // MARK: base64url and the options

  nonisolated static func base64url(_ data: Data) -> String {
    data.base64EncodedString()
      .replacingOccurrences(of: "+", with: "-")
      .replacingOccurrences(of: "/", with: "_")
      .replacingOccurrences(of: "=", with: "")
  }

  nonisolated static func data(fromBase64url text: String) -> Data? {
    var s = text.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
    while s.count % 4 != 0 { s += "=" }
    return Data(base64Encoded: s)
  }

  nonisolated static func jsonObject(_ text: String) -> [String: Any]? {
    guard let raw = text.data(using: .utf8) else { return nil }
    return (try? JSONSerialization.jsonObject(with: raw)) as? [String: Any]
  }

  nonisolated static func jsonText(_ object: [String: Any]) -> String? {
    guard JSONSerialization.isValidJSONObject(object),
      let raw = try? JSONSerialization.data(withJSONObject: object)
    else { return nil }
    return String(data: raw, encoding: .utf8)
  }

  /// The Dart-facing error code for a failed authorization.
  nonisolated static func code(for error: Error) -> String {
    guard let failure = error as? ASAuthorizationError else { return "failed" }
    switch failure.code {
    case .canceled:
      return "cancelled"
    case .notHandled:
      return "unsupported"
    default:
      return "failed"
    }
  }

  // MARK: the channel

  private let channel: FlutterMethodChannel
  private var pending: FlutterResult?
  private var controller: ASAuthorizationController?

  private init(messenger: FlutterBinaryMessenger) {
    channel = FlutterMethodChannel(name: "org.atalaia.app/passkeys", binaryMessenger: messenger)
    super.init()
    channel.setMethodCallHandler { [weak self] call, result in
      Task { @MainActor in
        guard let self = self else {
          result(FlutterError(code: "failed", message: "no plugin", details: nil))
          return
        }
        let args = call.arguments as? [String: Any]
        let request = args?["request"] as? String
        switch call.method {
        case "available":
          result(PasskeyPlugin.supported)
        case "create":
          self.run(request, registering: true, result: result)
        case "get":
          self.run(request, registering: false, result: result)
        default:
          result(FlutterMethodNotImplemented)
        }
      }
    }
  }

  private func fail(_ code: String, _ message: String, _ result: FlutterResult) {
    result(FlutterError(code: code, message: message, details: nil))
  }

  private func run(_ request: String?, registering: Bool, result: @escaping FlutterResult) {
    guard PasskeyPlugin.supported else {
      fail("unsupported", "no passkeys here", result)
      return
    }
    guard pending == nil else {
      fail("failed", "a passkey sheet is already open", result)
      return
    }
    guard let request = request, let options = PasskeyPlugin.jsonObject(request),
      let challengeText = options["challenge"] as? String,
      let challenge = PasskeyPlugin.data(fromBase64url: challengeText)
    else {
      fail("failed", "bad request", result)
      return
    }
    let built =
      registering
      ? registrationRequest(options, challenge: challenge)
      : assertionRequest(options, challenge: challenge)
    guard let authorizationRequest = built else {
      fail("failed", "bad request", result)
      return
    }
    let started = ASAuthorizationController(authorizationRequests: [authorizationRequest])
    started.delegate = self
    started.presentationContextProvider = self
    pending = result
    controller = started
    started.performRequests()
  }

  private func preference(_ options: [String: Any])
    -> ASAuthorizationPublicKeyCredentialUserVerificationPreference
  {
    var wanted = options["userVerification"] as? String
    if wanted == nil {
      wanted = (options["authenticatorSelection"] as? [String: Any])?["userVerification"] as? String
    }
    switch wanted {
    case "discouraged": return .discouraged
    case "preferred": return .preferred
    default: return .required
    }
  }

  /// `navigator.credentials.create`'s options: rp.id, user.{id, name}, challenge.
  private func registrationRequest(_ options: [String: Any], challenge: Data)
    -> ASAuthorizationRequest?
  {
    guard let rp = options["rp"] as? [String: Any], let rpId = rp["id"] as? String, !rpId.isEmpty,
      let user = options["user"] as? [String: Any], let name = user["name"] as? String,
      let idText = user["id"] as? String, let userId = PasskeyPlugin.data(fromBase64url: idText)
    else { return nil }
    let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(relyingPartyIdentifier: rpId)
    let request = provider.createCredentialRegistrationRequest(
      challenge: challenge, name: name, userID: userId)
    request.userVerificationPreference = preference(options)
    return request
  }

  /// `navigator.credentials.get`'s options: rpId, challenge, allowCredentials.
  private func assertionRequest(_ options: [String: Any], challenge: Data)
    -> ASAuthorizationRequest?
  {
    guard let rpId = options["rpId"] as? String, !rpId.isEmpty else { return nil }
    let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(relyingPartyIdentifier: rpId)
    let request = provider.createCredentialAssertionRequest(challenge: challenge)
    request.userVerificationPreference = preference(options)
    var allowed: [ASAuthorizationPlatformPublicKeyCredentialDescriptor] = []
    for entry in (options["allowCredentials"] as? [[String: Any]]) ?? [] {
      if let idText = entry["id"] as? String, let id = PasskeyPlugin.data(fromBase64url: idText) {
        allowed.append(ASAuthorizationPlatformPublicKeyCredentialDescriptor(credentialID: id))
      }
    }
    if !allowed.isEmpty { request.allowedCredentials = allowed }
    return request
  }

  private func finish(_ answer: Any?) {
    let result = pending
    pending = nil
    controller = nil
    result?(answer)
  }

  private func finish(failure code: String, _ message: String) {
    finish(FlutterError(code: code, message: message, details: nil))
  }
}

extension PasskeyPlugin: @preconcurrency ASAuthorizationControllerDelegate {
  func authorizationController(
    controller: ASAuthorizationController,
    didCompleteWithAuthorization authorization: ASAuthorization
  ) {
    let b64 = PasskeyPlugin.base64url
    if let made = authorization.credential
      as? ASAuthorizationPlatformPublicKeyCredentialRegistration
    {
      // Optional on purpose: the SDK's own optionality does not matter here.
      let maybeAttestation: Data? = made.rawAttestationObject
      let maybeClientData: Data? = made.rawClientDataJSON
      let maybeId: Data? = made.credentialID
      guard let attestation = maybeAttestation, let clientData = maybeClientData,
        let id = maybeId
      else {
        finish(failure: "failed", "no passkey")
        return
      }
      let body: [String: Any] = [
        "id": b64(id),
        "rawId": b64(id),
        "type": "public-key",
        "response": [
          "clientDataJSON": b64(clientData),
          "attestationObject": b64(attestation),
          "transports": ["internal"],
        ] as [String: Any],
        "clientExtensionResults": [String: Any](),
      ]
      if let text = PasskeyPlugin.jsonText(body) {
        finish(text)
      } else {
        finish(failure: "failed", "no passkey")
      }
      return
    }
    if let used = authorization.credential
      as? ASAuthorizationPlatformPublicKeyCredentialAssertion
    {
      let maybeAuthenticatorData: Data? = used.rawAuthenticatorData
      let maybeClientData: Data? = used.rawClientDataJSON
      let maybeSignature: Data? = used.signature
      let maybeId: Data? = used.credentialID
      let user: Data? = used.userID
      guard let authenticatorData = maybeAuthenticatorData, let clientData = maybeClientData,
        let signature = maybeSignature, let id = maybeId
      else {
        finish(failure: "failed", "no passkey")
        return
      }
      var response: [String: Any] = [
        "clientDataJSON": b64(clientData),
        "authenticatorData": b64(authenticatorData),
        "signature": b64(signature),
      ]
      if let user = user, !user.isEmpty { response["userHandle"] = b64(user) }
      let body: [String: Any] = [
        "id": b64(id),
        "rawId": b64(id),
        "type": "public-key",
        "response": response,
        "clientExtensionResults": [String: Any](),
      ]
      if let text = PasskeyPlugin.jsonText(body) {
        finish(text)
      } else {
        finish(failure: "failed", "no passkey")
      }
      return
    }
    finish(failure: "failed", "no passkey")
  }

  func authorizationController(
    controller: ASAuthorizationController, didCompleteWithError error: Error
  ) {
    finish(failure: PasskeyPlugin.code(for: error), "ASAuthorizationError")
  }
}

extension PasskeyPlugin: @preconcurrency ASAuthorizationControllerPresentationContextProviding {
  func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
    BrowserPlugin.anchorWindow()
  }
}
