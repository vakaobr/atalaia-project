// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * The field's Wi-Fi for a phone that is the field controller (slice S6 of
 * PE24; lib/platform/services.dart FieldWifiService):
 *
 * - `info`: Wi-Fi on or off, the network's name when Android tells it (it
 *   needs the location permission), the hotspot's state from the sticky
 *   `android.net.wifi.WIFI_AP_STATE_CHANGED` broadcast (13 = on, 11 = off;
 *   not a public API, so "unknown" when a maker leaves it out), and the
 *   local-only hotspot the app holds;
 * - `openHotspotSettings`, `openWifiSettings`: Android's own screens (an app
 *   cannot turn tethering on itself);
 * - `startLocalHotspot`, `stopLocalHotspot`: WifiManager's local-only
 *   hotspot, a network of the app's own (Android chooses its name and
 *   password; no internet), held while the app keeps the reservation. It
 *   needs NEARBY_WIFI_DEVICES from Android 13, location before, and Wi-Fi
 *   on; some phones cannot run it beside a Wi-Fi connection
 *   (`incompatible_mode`).
 *
 * Not run on a phone yet (plan phase G).
 */
class FieldWifiPlugin(private val activity: Activity, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler {
    private val channel = MethodChannel(messenger, "org.atalaia.app/wifi")
    private val main = Handler(Looper.getMainLooper())

    init {
        channel.setMethodCallHandler(this)
    }

    private val wifi: WifiManager
        get() = activity.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "info" -> result.success(info())
            "openHotspotSettings" -> result.success(openHotspotSettings())
            "openWifiSettings" -> result.success(open(Intent(Settings.ACTION_WIFI_SETTINGS)))
            "startLocalHotspot" -> startLocalHotspot(result)
            "stopLocalHotspot" -> {
                stopLocalHotspot()
                result.success(null)
            }
            else -> result.notImplemented()
        }
    }

    private fun info(): Map<String, Any?> {
        val wm = wifi
        return mapOf(
            "wifi_enabled" to wm.isWifiEnabled,
            "ssid" to ssid(wm),
            "hotspot" to hotspotState(),
            "local" to localHotspot(),
        )
    }

    private fun localHotspot(): Map<String, Any?>? =
        if (reservation == null) null else mapOf("ssid" to localSsid, "passphrase" to localPassphrase)

    @Suppress("DEPRECATION")
    private fun ssid(wm: WifiManager): String? {
        if (activity.checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return null
        }
        val raw = wm.connectionInfo?.ssid ?: return null
        if (raw == WifiManager.UNKNOWN_SSID || raw.isEmpty()) return null
        return raw.removeSurrounding("\"")
    }

    private fun hotspotState(): String {
        val filter = IntentFilter("android.net.wifi.WIFI_AP_STATE_CHANGED")
        val sticky = try {
            if (Build.VERSION.SDK_INT >= 33) {
                activity.registerReceiver(null, filter, Context.RECEIVER_NOT_EXPORTED)
            } else {
                activity.registerReceiver(null, filter)
            }
        } catch (e: RuntimeException) {
            null
        } ?: return "unknown"
        return when (sticky.getIntExtra("wifi_state", -1)) {
            12, 13 -> "on" // enabling, enabled
            10, 11 -> "off" // disabling, disabled
            else -> "unknown"
        }
    }

    private fun open(intent: Intent): Boolean = try {
        activity.startActivity(intent)
        true
    } catch (e: ActivityNotFoundException) {
        false
    } catch (e: SecurityException) {
        false
    }

    private fun openHotspotSettings(): Boolean {
        // The tethering screen has no public action; Settings' own class
        // works on most phones, else the wireless settings that hold it.
        val tether = Intent().setClassName("com.android.settings", "com.android.settings.TetherSettings")
        return open(tether) || open(Intent(Settings.ACTION_WIRELESS_SETTINGS))
    }

    private fun startLocalHotspot(result: MethodChannel.Result) {
        if (reservation != null) {
            result.success(localHotspot())
            return
        }
        val needed = if (Build.VERSION.SDK_INT >= 33) {
            "android.permission.NEARBY_WIFI_DEVICES"
        } else {
            android.Manifest.permission.ACCESS_FINE_LOCATION
        }
        if (activity.checkSelfPermission(needed) != PackageManager.PERMISSION_GRANTED) {
            result.success(mapOf("error" to "permission"))
            return
        }
        var answered = false
        fun answer(value: Map<String, Any?>) {
            if (answered) return
            answered = true
            result.success(value)
        }
        try {
            wifi.startLocalOnlyHotspot(
                object : WifiManager.LocalOnlyHotspotCallback() {
                    override fun onStarted(r: WifiManager.LocalOnlyHotspotReservation) {
                        reservation = r
                        readConfig(r)
                        answer(mapOf("ssid" to localSsid, "passphrase" to localPassphrase))
                    }

                    override fun onStopped() {
                        reservation = null
                        localSsid = null
                        localPassphrase = null
                    }

                    override fun onFailed(reason: Int) {
                        answer(
                            mapOf(
                                "error" to when (reason) {
                                    ERROR_NO_CHANNEL -> "no_channel"
                                    ERROR_INCOMPATIBLE_MODE -> "incompatible_mode"
                                    ERROR_TETHERING_DISALLOWED -> "tethering_disallowed"
                                    else -> "generic"
                                },
                            ),
                        )
                    }
                },
                main,
            )
        } catch (e: SecurityException) {
            answer(mapOf("error" to "permission"))
        } catch (e: IllegalStateException) {
            // Location off (below Android 13), or a request already running.
            answer(mapOf("error" to "location_off"))
        }
    }

    @Suppress("DEPRECATION")
    private fun readConfig(r: WifiManager.LocalOnlyHotspotReservation) {
        if (Build.VERSION.SDK_INT >= 30) {
            val c = r.softApConfiguration
            localSsid = if (Build.VERSION.SDK_INT >= 33) {
                c.wifiSsid?.toString()?.removeSurrounding("\"")
            } else {
                c.ssid
            }
            localPassphrase = c.passphrase
        } else {
            val c = r.wifiConfiguration
            localSsid = c?.SSID?.removeSurrounding("\"")
            localPassphrase = c?.preSharedKey?.removeSurrounding("\"")
        }
    }

    private fun stopLocalHotspot() {
        reservation?.close()
        reservation = null
        localSsid = null
        localPassphrase = null
    }

    /** The activity is going: the hotspot goes with the app. */
    fun close() = stopLocalHotspot()

    // The hotspot outlives this plugin when the engine outlives the
    // activity (MainActivity): the next activity's plugin finds it here.
    companion object {
        private var reservation: WifiManager.LocalOnlyHotspotReservation? = null
        private var localSsid: String? = null
        private var localPassphrase: String? = null
    }
}
