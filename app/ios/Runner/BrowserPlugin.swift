// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The system browser for a social login: the iOS twin of Android's
// BrowserPlugin.kt (decisions PKA-1 and IOSL-1). Same channel and contract:
//
//   org.atalaia.app/browser
//     "open" {url: String} -> Bool : true when the browser session started;
//         false for anything but an https address with a host, or when the
//         phone cannot do it (see below). Never an error.
//
// It runs an ASWebAuthenticationSession: the person signs in at the provider
// in a system browser sheet (the app sees neither its cookies nor its pages),
// and the site server's redirect to `https://<host>/app/oidc?s=<nonce>` with
// `#oidc=<ticket>` ends the session. On Android that https App Link opens the
// app and LinkPlugin hands it to Dart; here the session's callback URL is
// handed to Dart the same way, through LinkPlugin.deliver on the links
// channel, so Dart's OidcReturn.parse checks it (host, nonce) exactly as for
// Android and nothing in Dart differs.
//
// An https callback (ASWebAuthenticationSession.Callback.https) exists from
// iOS 17.4 and needs the site's host in the app's associated domains
// (webcredentials, Runner.entitlements). Before iOS 17.4 a session can only
// end on a custom URL scheme, which the site's https redirect is not, so
// there "open" answers false and Dart reports `browser_unavailable` ("not
// available", as without the plugin). Closing the sheet sends nothing to
// Dart (as closing a Custom Tab sends nothing): the waiting screen's own
// cancel and its time limit end the wait.

import AuthenticationServices
import Flutter
import UIKit

@MainActor
final class BrowserPlugin: NSObject {
  private static var instance: BrowserPlugin?

  /// Called once per engine, from AppDelegate.
  static func register(messenger: FlutterBinaryMessenger) {
    instance = BrowserPlugin(messenger: messenger)
  }

  /// The address the site's redirect ends on (lib/site/site_auth.dart).
  nonisolated static let returnPath = "/app/oidc"

  /// The address to open, or nil: https only, with a host and no user info.
  nonisolated static func acceptable(_ text: String?) -> URL? {
    guard let text = text, let url = URL(string: text),
      url.scheme == "https", let host = url.host, !host.isEmpty, url.user == nil
    else { return nil }
    return url
  }

  /// The window a system sheet is shown over (also used by PasskeyPlugin).
  static func anchorWindow() -> UIWindow {
    let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
    let scene = scenes.first { $0.activationState == .foregroundActive } ?? scenes.first
    if let window = scene?.windows.first(where: { $0.isKeyWindow }) ?? scene?.windows.first {
      return window
    }
    if let scene = scene { return UIWindow(windowScene: scene) }
    return UIWindow()
  }

  private let channel: FlutterMethodChannel
  private var session: ASWebAuthenticationSession?

  private init(messenger: FlutterBinaryMessenger) {
    channel = FlutterMethodChannel(name: "org.atalaia.app/browser", binaryMessenger: messenger)
    super.init()
    channel.setMethodCallHandler { [weak self] call, result in
      Task { @MainActor in
        guard let self = self else {
          result(false)
          return
        }
        switch call.method {
        case "open":
          let args = call.arguments as? [String: Any]
          result(self.open(args?["url"] as? String))
        default:
          result(FlutterMethodNotImplemented)
        }
      }
    }
  }

  private func open(_ text: String?) -> Bool {
    guard let url = BrowserPlugin.acceptable(text), let host = url.host else { return false }
    guard #available(iOS 17.4, *) else { return false }
    session?.cancel()
    let started = ASWebAuthenticationSession(
      url: url, callback: .https(host: host, path: BrowserPlugin.returnPath)
    ) { callbackURL, _ in
      // A cancelled or failed session has no URL: nothing to hand over.
      guard let callbackURL = callbackURL else { return }
      Task { @MainActor in
        BrowserPlugin.instance?.session = nil
        LinkPlugin.deliver(callbackURL)
      }
    }
    started.presentationContextProvider = self
    started.prefersEphemeralWebBrowserSession = false
    session = started
    if started.start() { return true }
    session = nil
    return false
  }
}

extension BrowserPlugin: @preconcurrency ASWebAuthenticationPresentationContextProviding {
  func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
    BrowserPlugin.anchorWindow()
  }
}
