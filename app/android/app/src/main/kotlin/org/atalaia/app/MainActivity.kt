// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.content.Context
import android.content.Intent
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.engine.FlutterEngineCache

/**
 * The app's one activity. It registers the app's own Kotlin plugins (plan
 * phase D) on the Flutter engine, each on its own channel (lib/platform/
 * channels.dart, lib/pod/pod_transports.dart), and forwards the activity
 * events they need: resume and pause (NFC reader mode), permission answers
 * and activity results (the QR scanner), and links that open the app
 * (LinkPlugin: the site server's register page, decision S16-13).
 *
 * While the foreground service runs (a prop's game, a player sharing their
 * position, the phone being the field controller), the Flutter engine, and
 * with it every Dart isolate, outlives this activity: Android may destroy
 * the activity (the back button on the first screen, a swipe away), and
 * the game loop or the controller's isolate goes on. The engine is kept in
 * FlutterEngineCache, and the next activity takes it up with its state
 * (slice S6 of PE24, decision PE24-64). Without the service, the engine
 * goes with the activity as before.
 */
class MainActivity : FlutterActivity() {
    private var device: DevicePlugin? = null
    private var nfc: NfcPlugin? = null
    private var qr: QrScanPlugin? = null
    private var usb: UsbPodPlugin? = null
    private var ble: BlePodPlugin? = null
    private var links: LinkPlugin? = null
    private var wifi: FieldWifiPlugin? = null

    /** The engine an earlier activity left running, if any. */
    override fun provideFlutterEngine(context: Context): FlutterEngine? =
        FlutterEngineCache.getInstance().get(ENGINE_ID)

    override fun shouldDestroyEngineWithHost(): Boolean {
        if (AtalaiaForegroundService.running) return false
        FlutterEngineCache.getInstance().remove(ENGINE_ID)
        return true
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        FlutterEngineCache.getInstance().put(ENGINE_ID, flutterEngine)
        val messenger = flutterEngine.dartExecutor.binaryMessenger
        device = DevicePlugin(this, messenger)
        KioskPlugin(this, messenger)
        ForegroundServicePlugin(this, messenger)
        nfc = NfcPlugin(this, messenger)
        qr = QrScanPlugin(this, messenger)
        LocationPlugin(this, messenger)
        KeystorePlugin(messenger)
        links = LinkPlugin(messenger, intent)
        // The pod's links and the local hotspot belong to the engine: an
        // engine an earlier activity left running keeps the ones it has, so
        // a controller's or a prop's pod stays linked (decision PE24-64).
        val kept = engineLinks?.takeIf { it.engine === flutterEngine }
        if (kept != null) {
            usb = kept.usb
            ble = kept.ble
            wifi = kept.wifi
        } else {
            usb = UsbPodPlugin(this, messenger)
            ble = BlePodPlugin(this, messenger)
            wifi = FieldWifiPlugin(this, messenger)
            engineLinks = EngineLinks(flutterEngine, usb!!, ble!!, wifi!!)
        }
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
        // A running service keeps the engine, and the pod's link and the
        // local hotspot the controller uses with it.
        if (!AtalaiaForegroundService.running) {
            usb?.close()
            ble?.close()
            wifi?.close()
            engineLinks = null
        }
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

    private class EngineLinks(
        val engine: FlutterEngine,
        val usb: UsbPodPlugin,
        val ble: BlePodPlugin,
        val wifi: FieldWifiPlugin,
    )

    companion object {
        private const val ENGINE_ID = "atalaia"

        /** The pod and Wi-Fi plugins of the engine in the cache. */
        private var engineLinks: EngineLinks? = null
    }
}
