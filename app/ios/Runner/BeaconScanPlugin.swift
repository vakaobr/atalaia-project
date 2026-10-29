// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The iBeacons the phone hears, for the indoor position reports (ADR-P3-6,
// decisions BLE-1 to BLE-9 and IOSB-1 to IOSB-8): the same channels and
// message shapes as Android's BeaconScanPlugin.kt, over CoreLocation.
//
//   org.atalaia.app/beacons (methods)
//     "available" -> Bool: the phone can range beacons.
//     "granted"   -> Bool: the app may read the location (when in use),
//         which is the permission ranging needs.
//     "enabled"   -> Bool: Location Services is on. iOS says nothing about
//         Bluetooth without a Bluetooth permission of its own (which the app
//         does not ask for), so with Bluetooth off the stream simply hears
//         nothing and the position stays GPS.
//   org.atalaia.app/beacons/sightings (events), arguments
//     {uuids: [String], window_ms: Int}
//     one map per window: {t: Unix ms, beacons: [{uuid, major, minor, rssi,
//     count}]}, one entry per beacon heard, rssi the average over the
//     window. Without the permission the stream fails at once with the error
//     code "unavailable".
//
// iOS ranges iBeacons through CoreLocation only (there is no raw scan for
// another company's advertisement), one constraint per registered UUID, so
// a beacon of any other UUID never reaches this code. CoreLocation reports
// each constraint about once a second, with the signal strength already
// averaged over that second (0: unknown, dropped); here those are grouped
// into the window Dart asks for, as on Android, so the Dart code is shared.
// Proximity and accuracy are ignored: only the signal strength is sent, and
// Dart applies the same -95 dBm floor.
//
// WHEN IN USE ONLY: no background mode, no "Always" request (decision
// iOS-5). Ranging stops with the app on the screen, so a locked phone sends
// no beacon windows and the position falls back to GPS and the last floor
// (decision IOSB-3). Nothing heard is kept after a window is sent.

import CoreLocation
import Flutter
import Foundation

@MainActor
final class BeaconScanPlugin: NSObject {
  private static var instance: BeaconScanPlugin?

  /// Called once per engine, from AppDelegate.
  static func register(messenger: FlutterBinaryMessenger) {
    instance = BeaconScanPlugin(messenger: messenger)
  }

  /// iOS allows about twenty regions and ranging constraints per app.
  private static let maxUuids = 20

  private let methods: FlutterMethodChannel
  private let events: FlutterEventChannel
  private lazy var manager: CLLocationManager = {
    let m = CLLocationManager()
    m.delegate = self
    return m
  }()

  private var sink: FlutterEventSink?
  private var constraints: [CLBeaconIdentityConstraint] = []
  private var window: TimeInterval = 5
  private var ticker: Timer?
  private var heard: [String: Heard] = [:]

  private struct Heard {
    let uuid: String
    let major: Int
    let minor: Int
    var sum = 0
    var count = 0
  }

  private init(messenger: FlutterBinaryMessenger) {
    methods = FlutterMethodChannel(name: "org.atalaia.app/beacons", binaryMessenger: messenger)
    events = FlutterEventChannel(
      name: "org.atalaia.app/beacons/sightings", binaryMessenger: messenger)
    super.init()
    methods.setMethodCallHandler { [weak self] call, result in
      guard let self = self else {
        result(FlutterMethodNotImplemented)
        return
      }
      self.handle(call, result)
    }
    events.setStreamHandler(self)
  }

  private var granted: Bool {
    switch manager.authorizationStatus {
    case .authorizedWhenInUse, .authorizedAlways: return true
    default: return false
    }
  }

  private func handle(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    switch call.method {
    case "available":
      result(CLLocationManager.isRangingAvailable())
    case "granted":
      result(granted)
    case "enabled":
      // locationServicesEnabled() can block: not on the main thread.
      DispatchQueue.global(qos: .userInitiated).async {
        let on = CLLocationManager.locationServicesEnabled()
        DispatchQueue.main.async { result(on) }
      }
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  private func startTicker() {
    ticker?.invalidate()
    ticker = Timer.scheduledTimer(withTimeInterval: window, repeats: true) { [weak self] _ in
      Task { @MainActor in self?.flush() }
    }
  }

  /// One window's beacons, once, then forgotten.
  private func flush() {
    guard let sink = sink else { return }
    let list: [[String: Any]] = heard.values.filter { $0.count > 0 }.map {
      [
        "uuid": $0.uuid,
        "major": $0.major,
        "minor": $0.minor,
        "rssi": Int((Double($0.sum) / Double($0.count)).rounded()),
        "count": $0.count,
      ]
    }
    heard.removeAll()
    sink([
      "t": Int((Date().timeIntervalSince1970 * 1000).rounded()),
      "beacons": list,
    ])
  }

  private func stopRanging() {
    ticker?.invalidate()
    ticker = nil
    for c in constraints { manager.stopRangingBeacons(satisfying: c) }
    constraints = []
    heard.removeAll()  // nothing heard is kept
  }

  private func fail(_ code: String, _ message: String) {
    let out = sink
    stopRanging()
    sink = nil
    out?(FlutterError(code: code, message: message, details: nil))
  }

  fileprivate func authorizationChanged() {
    let status = manager.authorizationStatus
    if sink != nil, status == .denied || status == .restricted {
      // The person took the permission away while a game was sharing.
      fail("unavailable", "no location permission")
    }
  }

  fileprivate func ranged(_ beacons: [CLBeacon]) {
    guard sink != nil else { return }
    for b in beacons where b.rssi < 0 {  // 0: iOS could not measure it
      let uuid = b.uuid.uuidString.uppercased()
      let major = b.major.intValue
      let minor = b.minor.intValue
      let key = "\(uuid)/\(major)/\(minor)"
      var h = heard[key] ?? Heard(uuid: uuid, major: major, minor: minor)
      h.sum += b.rssi
      h.count += 1
      heard[key] = h
    }
  }
}

extension BeaconScanPlugin: @preconcurrency FlutterStreamHandler {
  func onListen(withArguments arguments: Any?, eventSink events: @escaping FlutterEventSink)
    -> FlutterError?
  {
    guard granted, CLLocationManager.isRangingAvailable() else {
      return FlutterError(
        code: "unavailable", message: "no location permission or ranging", details: nil)
    }
    let args = arguments as? [String: Any]
    let uuids = ((args?["uuids"] as? [Any]) ?? []).compactMap {
      ($0 as? String).flatMap { UUID(uuidString: $0) }
    }
    if uuids.isEmpty {
      return FlutterError(
        code: "no_beacons", message: "no beacon UUIDs to listen for", details: nil)
    }
    let ms = (args?["window_ms"] as? NSNumber)?.doubleValue ?? 5_000
    window = min(max(ms / 1000, 3), 30)
    sink = events
    heard.removeAll()
    constraints = Array(uuids.prefix(BeaconScanPlugin.maxUuids)).map {
      CLBeaconIdentityConstraint(uuid: $0)
    }
    for c in constraints { manager.startRangingBeacons(satisfying: c) }
    startTicker()
    return nil
  }

  func onCancel(withArguments arguments: Any?) -> FlutterError? {
    stopRanging()
    sink = nil
    return nil
  }
}

extension BeaconScanPlugin: @preconcurrency CLLocationManagerDelegate {
  func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
    authorizationChanged()
  }

  func locationManager(
    _ manager: CLLocationManager, didRange beacons: [CLBeacon],
    satisfying constraint: CLBeaconIdentityConstraint
  ) {
    ranged(beacons)
  }

  func locationManager(
    _ manager: CLLocationManager, didFailRangingFor constraint: CLBeaconIdentityConstraint,
    error: Error
  ) {
    fail("scan_failed", "ranging failed: \(error.localizedDescription)")
  }
}
