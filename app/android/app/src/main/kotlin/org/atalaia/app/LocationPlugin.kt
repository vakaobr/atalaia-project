// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Looper
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * The phone's position for player position reports (ADR-P3-6, plan phase E),
 * from Android's own LocationManager: the fused provider where the system
 * has one (Android 12+), else GPS, else the network. No Google Play services
 * (decision PD5). Fixes stream on `org.atalaia.app/location/fixes` while
 * Dart listens, at the interval it asks for; nothing is kept here.
 */
class LocationPlugin(private val activity: Activity, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler, EventChannel.StreamHandler {
    private val methods = MethodChannel(messenger, "org.atalaia.app/location")
    private val events = EventChannel(messenger, "org.atalaia.app/location/fixes")
    private var sink: EventChannel.EventSink? = null
    private var listener: LocationListener? = null

    init {
        methods.setMethodCallHandler(this)
        events.setStreamHandler(this)
    }

    private val manager: LocationManager?
        get() = activity.getSystemService(Context.LOCATION_SERVICE) as LocationManager?

    private fun granted(): Boolean =
        activity.checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED ||
            activity.checkSelfPermission(android.Manifest.permission.ACCESS_COARSE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED

    private fun provider(): String? {
        val lm = manager ?: return null
        val all = lm.allProviders
        if (Build.VERSION.SDK_INT >= 31 && all.contains(LocationManager.FUSED_PROVIDER)) {
            return LocationManager.FUSED_PROVIDER
        }
        return listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
            .firstOrNull { all.contains(it) && lm.isProviderEnabled(it) }
            ?: all.firstOrNull { it != LocationManager.PASSIVE_PROVIDER }
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "available" -> result.success(provider() != null)
            "granted" -> result.success(granted())
            "enabled" -> result.success(
                manager?.let { lm -> if (Build.VERSION.SDK_INT >= 28) lm.isLocationEnabled else true } ?: false,
            )
            else -> result.notImplemented()
        }
    }

    @SuppressLint("MissingPermission")
    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        sink = events
        val lm = manager
        val p = provider()
        if (lm == null || p == null || !granted()) {
            events?.error("unavailable", "no location provider or no permission", null)
            return
        }
        val interval = ((arguments as? Map<*, *>)?.get("interval_ms") as? Number)?.toLong() ?: 10_000L
        val l = LocationListener { loc -> sink?.success(fix(loc)) }
        listener = l
        lm.requestLocationUpdates(p, interval.coerceIn(1_000L, 60_000L), 0f, l, Looper.getMainLooper())
        lm.getLastKnownLocation(p)?.let { sink?.success(fix(it)) }
    }

    override fun onCancel(arguments: Any?) {
        listener?.let { manager?.removeUpdates(it) }
        listener = null
        sink = null
    }

    private fun fix(loc: Location): Map<String, Any?> = mapOf(
        "lat" to loc.latitude,
        "lon" to loc.longitude,
        "accuracy_m" to if (loc.hasAccuracy()) loc.accuracy.toDouble() else null,
        "altitude_m" to if (loc.hasAltitude()) loc.altitude else null,
        "heading_deg" to if (loc.hasBearing()) loc.bearing.toDouble() else null,
        "speed_mps" to if (loc.hasSpeed()) loc.speed.toDouble() else null,
        "t" to loc.time,
    )
}
