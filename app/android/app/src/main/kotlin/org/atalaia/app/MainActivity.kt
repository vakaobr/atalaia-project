// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.content.Intent
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine

/**
 * The app's one activity. It registers the app's own Kotlin plugins (plan
 * phase D) on the Flutter engine, each on its own channel (lib/platform/
 * channels.dart, lib/pod/pod_transports.dart), and forwards the activity
 * events they need: resume and pause (NFC reader mode), permission answers
 * and activity results (the QR scanner), and links that open the app
 * (LinkPlugin: the site server's register page, decision S16-13).
 */
class MainActivity : FlutterActivity() {
    private var device: DevicePlugin? = null
    private var nfc: NfcPlugin? = null
    private var qr: QrScanPlugin? = null
    private var usb: UsbPodPlugin? = null
    private var ble: BlePodPlugin? = null
    private var links: LinkPlugin? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val messenger = flutterEngine.dartExecutor.binaryMessenger
        device = DevicePlugin(this, messenger)
        KioskPlugin(this, messenger)
        ForegroundServicePlugin(this, messenger)
        nfc = NfcPlugin(this, messenger)
        qr = QrScanPlugin(this, messenger)
        usb = UsbPodPlugin(this, messenger)
        ble = BlePodPlugin(this, messenger)
        LocationPlugin(this, messenger)
        links = LinkPlugin(messenger, intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        links?.onNewIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        nfc?.onResume()
    }

    override fun onPause() {
        nfc?.onPause()
        super.onPause()
    }

    override fun onDestroy() {
        usb?.close()
        ble?.close()
        super.onDestroy()
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        device?.onPermissionsResult(requestCode, grantResults)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        qr?.onActivityResult(requestCode, resultCode, data)
    }
}
