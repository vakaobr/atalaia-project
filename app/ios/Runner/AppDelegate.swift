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
      AudioServicesPlaySystemSound(kSystemSoundID_Vibrate)
      result(nil)
    default:
      result(FlutterMethodNotImplemented)
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
