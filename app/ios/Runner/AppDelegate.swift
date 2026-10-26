// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// iOS side of the app's platform channels (lib/platform/channels.dart).
// Only the "device" channel is answered here, and only what the app needs to
// run: the private folder for the settings (filesDir), the maker, the screen
// kept on and a buzz. Every other method, and every other channel (QR, NFC,
// location, kiosk, foreground service, the field's Wi-Fi, the I/O pod, app
// links), is left out on purpose: Flutter then raises MissingPluginException,
// which the Dart side reads as "not available" (decision iOS-3).

import AudioToolbox
import Flutter
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    if let registrar = engineBridge.pluginRegistry.registrar(forPlugin: "AtalaiaDevice") {
      let channel = FlutterMethodChannel(
        name: "org.atalaia.app/device", binaryMessenger: registrar.messenger())
      channel.setMethodCallHandler(AppDelegate.handleDevice)
    }
  }

  private static func handleDevice(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    switch call.method {
    case "filesDir":
      result(privateFolder())
    case "manufacturer":
      result("Apple")
    case "keepScreenOn":
      let args = call.arguments as? [String: Any]
      UIApplication.shared.isIdleTimerDisabled = (args?["on"] as? Bool) ?? false
      result(nil)
    case "vibrate":
      let args = call.arguments as? [String: Any]
      let pattern = (args?["pattern"] as? [NSNumber])?.map { $0.intValue } ?? [0, 200]
      vibrate(pattern)
      result(nil)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  /// Plays an Android-style pattern (wait, buzz, pause, buzz... in
  /// milliseconds; decision VB-6): each "on" part starts at its time. iOS
  /// cannot shape a buzz's length: a part of 400 ms or more is the system
  /// vibration (which follows the phone's Vibrate on Ring/Silent settings),
  /// a shorter one is a tap of the haptic engine (light under 150 ms, medium
  /// under 300, heavy above), so a double stays a double.
  private static func vibrate(_ pattern: [Int]) {
    var at = 0
    for (index, ms) in pattern.enumerated() {
      let length = max(ms, 0)
      if index % 2 == 1 && length > 0 {
        DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(at)) {
          if length >= 400 {
            AudioServicesPlaySystemSound(kSystemSoundID_Vibrate)
          } else {
            let style: UIImpactFeedbackGenerator.FeedbackStyle =
              length < 150 ? .light : (length < 300 ? .medium : .heavy)
            UIImpactFeedbackGenerator(style: style).impactOccurred()
          }
        }
      }
      at += length
    }
  }

  /// The app's private folder for the settings (the field join key, the
  /// marshal's key): Application Support, which the app owns, kept out of
  /// iCloud and iTunes backups as Android's allowBackup="false" does (PD6).
  private static func privateFolder() -> String? {
    guard
      var url = FileManager.default.urls(
        for: .applicationSupportDirectory, in: .userDomainMask
      ).first
    else { return nil }
    do {
      try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
      var values = URLResourceValues()
      values.isExcludedFromBackup = true
      try url.setResourceValues(values)
    } catch {
      return nil
    }
    return url.path
  }
}
