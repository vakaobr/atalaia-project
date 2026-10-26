// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Links that open the app: `atalaia://register?...` from a site server's
// register page (decision S16-13), the iOS twin of Android's LinkPlugin.kt
// (decision iOS-14). Same channel and contract:
//
//   org.atalaia.app/links
//     Dart -> native "initial" -> String? : the link that started the app,
//         once (null: none, or already handed over).
//     native -> Dart "link" (String)      : a link that arrives while the
//         app runs.
//
// Only `atalaia:` links of at most 4096 characters are passed on; Dart
// (lib/site/site_link.dart) checks everything else. The scheme is declared
// in Info.plist (CFBundleURLTypes). The app uses UIScene, so the URLs reach
// the plugin as Flutter's scene life-cycle events (FlutterSceneLifeCycle
// Delegate, registered with the plugin registrar; SceneDelegate.swift stays
// Flutter's own): at a cold start in scene(_:willConnectToSession:options:),
// later in scene(_:openURLContexts:). Returning true tells Flutter the link
// is handled, so it is not also sent to Dart's router (Info.plist also sets
// FlutterDeepLinkingEnabled to false, as Android's manifest does).
//
// The scene can connect before or after Dart is listening: until Dart has
// asked for "initial" every link is kept as the initial one (the last
// wins); after that links are sent as "link" events.

import Flutter
import UIKit

@MainActor
final class LinkPlugin: NSObject {
  private static var instance: LinkPlugin?
  private static var initial: String?
  private static var dartAsked = false
  private static var lastLink: (text: String, uptime: TimeInterval)?

  /// Called once per engine, from AppDelegate.
  static func register(registrar: FlutterPluginRegistrar) {
    dartAsked = false  // a new engine's Dart asks again
    let plugin = LinkPlugin(messenger: registrar.messenger())
    instance = plugin
    registrar.addSceneDelegate(plugin)
  }

  /// What the app passes on: an `atalaia:` link of at most 4096 characters.
  nonisolated static func accept(_ text: String) -> String? {
    text.hasPrefix("atalaia:") && text.count <= 4096 ? text : nil
  }

  /// A URL that opened the app; false when it is not one of ours.
  @discardableResult
  static func deliver(_ url: URL) -> Bool {
    guard let text = accept(url.absoluteString) else { return false }
    // The same link announced twice at once.
    let now = ProcessInfo.processInfo.systemUptime
    if let last = lastLink, last.text == text, now - last.uptime < 1 { return true }
    lastLink = (text, now)
    if dartAsked, let instance = instance {
      instance.channel.invokeMethod("link", arguments: text)
    } else {
      initial = text
    }
    return true
  }

  private let channel: FlutterMethodChannel

  private init(messenger: FlutterBinaryMessenger) {
    channel = FlutterMethodChannel(name: "org.atalaia.app/links", binaryMessenger: messenger)
    super.init()
    channel.setMethodCallHandler { call, result in
      switch call.method {
      case "initial":
        LinkPlugin.dartAsked = true
        result(LinkPlugin.initial)
        LinkPlugin.initial = nil
      default:
        result(FlutterMethodNotImplemented)
      }
    }
  }
}

extension LinkPlugin: @preconcurrency FlutterSceneLifeCycleDelegate {
  // The Objective-C selectors are spelled out: they are the protocol's.

  @objc(scene:willConnectToSession:options:)
  func scene(
    _ scene: UIScene,
    willConnectTo session: UISceneSession,
    options connectionOptions: UIScene.ConnectionOptions?
  ) -> Bool {
    var handled = false
    for context in connectionOptions?.urlContexts ?? [] {
      if LinkPlugin.deliver(context.url) { handled = true }
    }
    return handled
  }

  @objc(scene:openURLContexts:)
  func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) -> Bool {
    var handled = false
    for context in URLContexts {
      if LinkPlugin.deliver(context.url) { handled = true }
    }
    return handled
  }
}
