// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The QR scanner of the iOS app: the same channel and contract as Android's
// QrScanPlugin.kt and QrScanActivity.kt (decision iOS-13).
//
//   org.atalaia.app/qr
//     "available" -> Bool: the phone has a camera (false on the simulator).
//     "scan" {hint: String, cancel: String} -> String? : the text of the
//         first QR code read; null when the person cancels, when the camera
//         permission is refused (or restricted), or when there is no camera.
//         Never an error: the Dart side reads null as "nothing scanned" and
//         offers the typed way.
//
// The picture comes from AVFoundation (AVCaptureSession), the decoding from
// AVCaptureMetadataOutput with the .qr type: no third-party library. The
// scanner is a full-screen view controller presented over the Flutter view,
// with the hint under the picture and a cancel button, as Android's activity.

import AVFoundation
import Flutter
import UIKit

@MainActor
final class QrScanPlugin: NSObject {
  private static var instance: QrScanPlugin?

  /// Called once per engine, from AppDelegate.
  static func register(messenger: FlutterBinaryMessenger) {
    instance = QrScanPlugin(messenger: messenger)
  }

  private let channel: FlutterMethodChannel
  private var pending: FlutterResult?
  private var scanner: QrScanViewController?

  private init(messenger: FlutterBinaryMessenger) {
    channel = FlutterMethodChannel(name: "org.atalaia.app/qr", binaryMessenger: messenger)
    super.init()
    channel.setMethodCallHandler { [weak self] call, result in
      guard let self = self else {
        result(FlutterMethodNotImplemented)
        return
      }
      self.handle(call, result)
    }
  }

  private func handle(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    switch call.method {
    case "available":
      result(AVCaptureDevice.default(for: .video) != nil)
    case "scan":
      let args = call.arguments as? [String: Any]
      scan(
        hint: (args?["hint"] as? String) ?? "",
        cancel: (args?["cancel"] as? String) ?? "",
        result: result)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  private func scan(hint: String, cancel: String, result: @escaping FlutterResult) {
    // A second scan replaces the first, which ends as cancelled (as Android).
    finish(nil)
    pending = result
    guard AVCaptureDevice.default(for: .video) != nil else {
      finish(nil)
      return
    }
    switch AVCaptureDevice.authorizationStatus(for: .video) {
    case .authorized:
      present(hint: hint, cancel: cancel)
    case .notDetermined:
      AVCaptureDevice.requestAccess(for: .video) { granted in
        DispatchQueue.main.async { [weak self] in
          guard let self = self, self.pending != nil else { return }
          if granted {
            self.present(hint: hint, cancel: cancel)
          } else {
            self.finish(nil)
          }
        }
      }
    default:  // denied, restricted
      finish(nil)
    }
  }

  private func present(hint: String, cancel: String) {
    guard pending != nil else { return }
    guard let top = QrScanPlugin.topViewController() else {
      finish(nil)
      return
    }
    let controller = QrScanViewController(hint: hint, cancel: cancel) { [weak self] text in
      self?.finish(text)
    }
    controller.modalPresentationStyle = .fullScreen
    scanner = controller
    top.present(controller, animated: true)
  }

  /// Answers the waiting call once and closes the scanner.
  private func finish(_ text: String?) {
    let result = pending
    pending = nil
    let controller = scanner
    scanner = nil
    controller?.close()
    result?(text)
  }

  private static func topViewController() -> UIViewController? {
    let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
    let scene = scenes.first { $0.activationState == .foregroundActive } ?? scenes.first
    let window = scene?.windows.first { $0.isKeyWindow } ?? scene?.windows.first
    var top = window?.rootViewController
    while let presented = top?.presentedViewController {
      top = presented
    }
    return top
  }
}

/// AVCaptureSession is not Sendable; it is only started and stopped on the
/// scanner's own queue.
private final class SessionBox: @unchecked Sendable {
  let session = AVCaptureSession()
}

final class QrScanViewController: UIViewController {
  private let hint: String
  private let cancel: String
  private let onDone: (String?) -> Void
  private let box = SessionBox()
  private let queue = DispatchQueue(label: "org.atalaia.app.qr")
  private lazy var previewLayer = AVCaptureVideoPreviewLayer(session: box.session)
  private var done = false
  private var configured = false

  init(hint: String, cancel: String, onDone: @escaping (String?) -> Void) {
    self.hint = hint
    self.cancel = cancel
    self.onDone = onDone
    super.init(nibName: nil, bundle: nil)
  }

  required init?(coder: NSCoder) {
    fatalError("init(coder:) is not used")
  }

  override func viewDidLoad() {
    super.viewDidLoad()
    view.backgroundColor = .black
    previewLayer.videoGravity = .resizeAspectFill
    view.layer.addSublayer(previewLayer)
    buildBar()
    configured = configureSession()
  }

  override func viewDidAppear(_ animated: Bool) {
    super.viewDidAppear(animated)
    guard configured else {
      // No usable camera: end as cancelled; Dart offers the typed way.
      finish(nil)
      return
    }
    let box = self.box
    queue.async { box.session.startRunning() }
  }

  override func viewDidLayoutSubviews() {
    super.viewDidLayoutSubviews()
    previewLayer.frame = view.bounds
    updateOrientation()
  }

  override var prefersStatusBarHidden: Bool { true }

  override var supportedInterfaceOrientations: UIInterfaceOrientationMask { .all }

  /// Stops the camera and takes the scanner off the screen (idempotent).
  func close() {
    done = true
    let box = self.box
    queue.async {
      if box.session.isRunning { box.session.stopRunning() }
    }
    if presentingViewController != nil {
      dismiss(animated: true)
    }
  }

  private func finish(_ text: String?) {
    if done { return }
    done = true
    onDone(text)
  }

  // MARK: camera

  private func configureSession() -> Bool {
    guard
      let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back)
        ?? AVCaptureDevice.default(for: .video),
      let input = try? AVCaptureDeviceInput(device: device)
    else { return false }
    let session = box.session
    let output = AVCaptureMetadataOutput()
    session.beginConfiguration()
    guard session.canAddInput(input), session.canAddOutput(output) else {
      session.commitConfiguration()
      return false
    }
    session.addInput(input)
    session.addOutput(output)
    session.commitConfiguration()
    // The type can only be set once the output is in the session.
    output.setMetadataObjectsDelegate(self, queue: .main)
    if output.availableMetadataObjectTypes.contains(.qr) {
      output.metadataObjectTypes = [.qr]
    } else {
      return false
    }
    do {
      try device.lockForConfiguration()
      if device.isFocusModeSupported(.continuousAutoFocus) {
        device.focusMode = .continuousAutoFocus
      }
      device.unlockForConfiguration()
    } catch {
      // The default focus is good enough.
    }
    return true
  }

  private func updateOrientation() {
    guard let connection = previewLayer.connection else { return }
    let orientation = view.window?.windowScene?.interfaceOrientation ?? .portrait
    if #available(iOS 17.0, *) {
      let angle: CGFloat
      switch orientation {
      case .landscapeLeft: angle = 180
      case .landscapeRight: angle = 0
      case .portraitUpsideDown: angle = 270
      default: angle = 90
      }
      if connection.isVideoRotationAngleSupported(angle) {
        connection.videoRotationAngle = angle
      }
    } else if connection.isVideoOrientationSupported,
      let video = AVCaptureVideoOrientation(rawValue: orientation.rawValue)
    {
      connection.videoOrientation = video
    }
  }

  // MARK: the hint and the cancel button

  private func buildBar() {
    let bar = UIView()
    bar.translatesAutoresizingMaskIntoConstraints = false
    bar.backgroundColor = UIColor(red: 16 / 255, green: 20 / 255, blue: 24 / 255, alpha: 0xB0 / 255)

    let label = UILabel()
    label.text = hint
    label.textColor = .white
    label.font = UIFont.preferredFont(forTextStyle: .title3)
    label.adjustsFontForContentSizeCategory = true
    label.textAlignment = .center
    label.numberOfLines = 0
    label.isHidden = hint.isEmpty

    let button = UIButton(type: .system)
    button.setTitle(cancel.isEmpty ? "×" : cancel, for: .normal)
    button.setTitleColor(.white, for: .normal)
    button.titleLabel?.font = UIFont.preferredFont(forTextStyle: .headline)
    button.titleLabel?.adjustsFontForContentSizeCategory = true
    button.accessibilityIdentifier = "qr-cancel"
    button.heightAnchor.constraint(greaterThanOrEqualToConstant: 48).isActive = true
    button.addAction(
      UIAction { [weak self] _ in self?.finish(nil) },
      for: .touchUpInside)

    let stack = UIStackView(arrangedSubviews: [label, button])
    stack.axis = .vertical
    stack.spacing = 8
    stack.translatesAutoresizingMaskIntoConstraints = false
    bar.addSubview(stack)
    view.addSubview(bar)
    NSLayoutConstraint.activate([
      bar.leadingAnchor.constraint(equalTo: view.leadingAnchor),
      bar.trailingAnchor.constraint(equalTo: view.trailingAnchor),
      bar.bottomAnchor.constraint(equalTo: view.bottomAnchor),
      stack.topAnchor.constraint(equalTo: bar.topAnchor, constant: 16),
      stack.leadingAnchor.constraint(equalTo: bar.safeAreaLayoutGuide.leadingAnchor, constant: 16),
      stack.trailingAnchor.constraint(
        equalTo: bar.safeAreaLayoutGuide.trailingAnchor, constant: -16),
      stack.bottomAnchor.constraint(equalTo: bar.safeAreaLayoutGuide.bottomAnchor, constant: -8),
    ])
  }
}

extension QrScanViewController: @preconcurrency AVCaptureMetadataOutputObjectsDelegate {
  func metadataOutput(
    _ output: AVCaptureMetadataOutput,
    didOutput metadataObjects: [AVMetadataObject],
    from connection: AVCaptureConnection
  ) {
    guard !done else { return }
    for object in metadataObjects {
      guard let code = object as? AVMetadataMachineReadableCodeObject,
        code.type == .qr,
        let text = code.stringValue, !text.isEmpty
      else { continue }
      finish(text)
      return
    }
  }
}
