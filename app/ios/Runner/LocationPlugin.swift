// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The phone's position for a player who shares it, over CoreLocation: the
// same channels and contract as Android's LocationPlugin.kt (decision iOS-15).
//
//   org.atalaia.app/location (methods)
//     "available" -> Bool: the phone can locate itself (always true on an
//         iPhone; whether Location Services is on is "enabled").
//     "granted"   -> Bool: the app may read the location (when in use).
//     "enabled"   -> Bool: Location Services is on in the phone's settings.
//   org.atalaia.app/location/fixes (events), arguments {interval_ms}
//     a map per fix: lat, lon, accuracy_m, altitude_m, heading_deg,
//     speed_mps (each only when the phone knows it) and t (Unix ms); about
//     one every interval_ms (1 to 60 s) while listened to. Without
//     permission the stream fails at once with the error code "unavailable".
//
// The permission is asked through the device channel, as on Android: Dart
// calls requestPermission("ACCESS_FINE_LOCATION") there, and AppDelegate
// hands it to [LocationPlugin.requestPermission]. WHEN IN USE ONLY: no
// background mode, no "Always" request (decision iOS-5), so updates stop
// when the app leaves the screen and go on when it comes back.
//
// Accuracy: the app wants the precise location. If the person gave the app
// only the approximate one (iOS 14 and later), the app asks once for a
// temporary precise location (the purpose key in Info.plist's
// NSLocationTemporaryUsageDescriptionDictionary); if that is refused the
// fixes carry their real, large accuracy_m, which the controller can see.

import CoreLocation
import Flutter
import Foundation

@MainActor
final class LocationPlugin: NSObject {
  private static var instance: LocationPlugin?

  /// Called once per engine, from AppDelegate.
  static func register(messenger: FlutterBinaryMessenger) {
    instance = LocationPlugin(messenger: messenger)
  }

  /// The Android permission names this plugin answers on the device channel.
  static func handles(permission name: String) -> Bool {
    name == "ACCESS_FINE_LOCATION" || name == "ACCESS_COARSE_LOCATION"
  }

  /// Asks for the location permission (when in use) if it is not decided
  /// yet, and says whether the app may now read the location.
  static func requestPermission(_ done: @escaping (Bool) -> Void) {
    guard let instance = instance else {
      done(false)
      return
    }
    instance.requestWhenInUse(done)
  }

  private static let purposeKey = "AtalaiaPositions"
  private static let lastKnownMaxAge: TimeInterval = 30

  private let methods: FlutterMethodChannel
  private let events: FlutterEventChannel
  private lazy var manager: CLLocationManager = {
    let m = CLLocationManager()
    m.delegate = self
    m.desiredAccuracy = kCLLocationAccuracyBest
    m.distanceFilter = kCLDistanceFilterNone
    m.activityType = .fitness
    m.pausesLocationUpdatesAutomatically = false
    // No background updates: the capability is not declared (iOS-5).
    m.allowsBackgroundLocationUpdates = false
    return m
  }()

  private var sink: FlutterEventSink?
  private var interval: TimeInterval = 10
  private var lastSent: TimeInterval?  // ProcessInfo.systemUptime of the last fix sent
  // CoreLocation reports only when the position changes: a player standing
  // still would stop reporting after the first fix (found in the simulator,
  // 2026-10-26). While listened to, this sends the last known position again
  // once an interval has gone by with nothing sent, with its own `t`, so the
  // controller sees how old it is, as Android's periodic updates keep going.
  private var ticker: Timer?
  // The last position sent: manager.location can lag the one just given to
  // the delegate, and a fix sent again must not go back in time.
  private var lastFix: CLLocation?
  private var waiting: [(Bool) -> Void] = []

  private init(messenger: FlutterBinaryMessenger) {
    methods = FlutterMethodChannel(name: "org.atalaia.app/location", binaryMessenger: messenger)
    events = FlutterEventChannel(
      name: "org.atalaia.app/location/fixes", binaryMessenger: messenger)
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
      result(true)
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

  // MARK: permission

  private func requestWhenInUse(_ done: @escaping (Bool) -> Void) {
    switch manager.authorizationStatus {
    case .authorizedWhenInUse, .authorizedAlways:
      preciseIfReduced(done)
    case .notDetermined:
      waiting.append(done)
      if waiting.count == 1 {
        manager.requestWhenInUseAuthorization()
      }
    default:  // denied, restricted
      done(false)
    }
  }

  /// With only the approximate location (kilometres of error), asks once
  /// for the precise one; the answer does not change "granted".
  private func preciseIfReduced(_ done: @escaping (Bool) -> Void) {
    guard manager.accuracyAuthorization == .reducedAccuracy else {
      done(true)
      return
    }
    manager.requestTemporaryFullAccuracyAuthorization(
      withPurposeKey: LocationPlugin.purposeKey
    ) { _ in
      DispatchQueue.main.async { done(true) }
    }
  }

  fileprivate func authorizationChanged() {
    let status = manager.authorizationStatus
    let allowed = status == .authorizedWhenInUse || status == .authorizedAlways
    if status != .notDetermined, !waiting.isEmpty {
      let all = waiting
      waiting = []
      if allowed {
        preciseIfReduced { ok in all.forEach { $0(ok) } }
      } else {
        all.forEach { $0(false) }
      }
    }
    if sink != nil, !allowed, status != .notDetermined {
      // The person took the permission away while a game was sharing.
      fail()
    }
  }

  // MARK: fixes

  fileprivate func deliver(_ locations: [CLLocation]) {
    guard let sink = sink else { return }
    let now = ProcessInfo.processInfo.systemUptime
    // CoreLocation reports about once a second; send one per interval (a
    // little early is fine: the next report would be a second late).
    if let last = lastSent, now - last < interval - 0.5 { return }
    guard let loc = locations.last(where: { $0.horizontalAccuracy >= 0 }) else { return }
    lastSent = now
    lastFix = loc
    sink(LocationPlugin.fix(loc))
  }

  private func tick() {
    guard sink != nil else { return }
    let now = ProcessInfo.processInfo.systemUptime
    if let last = lastSent, now - last < interval - 0.5 { return }
    let known = manager.location.flatMap { $0.horizontalAccuracy >= 0 ? $0 : nil }
    // The newer of the phone's last known position and the last one sent.
    guard let loc = [known, lastFix].compactMap({ $0 }).max(by: { $0.timestamp < $1.timestamp })
    else { return }
    lastSent = now
    lastFix = loc
    sink?(LocationPlugin.fix(loc))
  }

  private func startTicker() {
    ticker?.invalidate()
    ticker = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
      Task { @MainActor in self?.tick() }
    }
  }

  private func stopTicker() {
    ticker?.invalidate()
    ticker = nil
  }

  private func fail() {
    stopTicker()
    manager.stopUpdatingLocation()
    sink?(
      FlutterError(
        code: "unavailable", message: "no location permission", details: nil))
    sink = nil
  }

  private static func fix(_ loc: CLLocation) -> [String: Any] {
    var m: [String: Any] = [
      "lat": loc.coordinate.latitude,
      "lon": loc.coordinate.longitude,
      "t": Int((loc.timestamp.timeIntervalSince1970 * 1000).rounded()),
    ]
    if loc.horizontalAccuracy >= 0 { m["accuracy_m"] = loc.horizontalAccuracy }
    if loc.verticalAccuracy >= 0 { m["altitude_m"] = loc.altitude }
    if loc.course >= 0 { m["heading_deg"] = loc.course }
    if loc.speed >= 0 { m["speed_mps"] = loc.speed }
    return m
  }
}

extension LocationPlugin: @preconcurrency FlutterStreamHandler {
  func onListen(withArguments arguments: Any?, eventSink events: @escaping FlutterEventSink)
    -> FlutterError?
  {
    sink = events
    let ms = ((arguments as? [String: Any])?["interval_ms"] as? NSNumber)?.doubleValue ?? 10_000
    interval = min(max(ms / 1000, 1), 60)
    lastSent = nil
    guard granted else {
      fail()
      return nil
    }
    // The last position the phone knows, if it is fresh (as Android's
    // getLastKnownLocation), so the first report does not wait a second.
    if let known = manager.location, known.horizontalAccuracy >= 0,
      -known.timestamp.timeIntervalSinceNow <= LocationPlugin.lastKnownMaxAge
    {
      lastSent = ProcessInfo.processInfo.systemUptime
      lastFix = known
      events(LocationPlugin.fix(known))
    }
    manager.startUpdatingLocation()
    startTicker()
    return nil
  }

  func onCancel(withArguments arguments: Any?) -> FlutterError? {
    stopTicker()
    manager.stopUpdatingLocation()
    sink = nil
    lastSent = nil
    lastFix = nil
    return nil
  }
}

extension LocationPlugin: @preconcurrency CLLocationManagerDelegate {
  func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
    authorizationChanged()
  }

  func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
    deliver(locations)
  }

  func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
    // A passing failure (no fix yet: kCLErrorLocationUnknown) is retried by
    // CoreLocation itself; only a refusal ends the stream.
    if (error as? CLError)?.code == .denied { fail() }
  }
}
