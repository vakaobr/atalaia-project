// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.annotation.SuppressLint
import android.app.Activity
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.util.Locale
import java.util.UUID

/**
 * The iBeacons the phone hears, for the indoor position reports (ADR-P3-6,
 * decisions BLE-1 to BLE-9). Android's own Bluetooth LE scanner, no Google
 * Play services.
 *
 * Battery and privacy, the way the scan is made:
 *  - it runs only while Dart listens on `org.atalaia.app/beacons/sightings`
 *    (a player sharing their position in a running game) and stops when Dart
 *    cancels; nothing is kept here after a window is sent;
 *  - SCAN_MODE_LOW_POWER (about 0.5 s of listening in every 5 s), enough for
 *    beacons that advertise several times a second, and no wake lock;
 *  - one hardware scan filter per UUID of the field's registry (the iBeacon
 *    prefix: Apple's company id 0x004C, the type 0x02, the length 0x15, the
 *    UUID), so the radio drops every other advertisement before the app is
 *    woken; a beacon of any other UUID never reaches this code;
 *  - what is heard is grouped into windows of the length Dart asks for (the
 *    game's beacon interval, 3 to 30 s) and sent once per window, one entry
 *    per beacon with its average signal strength, so the app wakes once a
 *    window, not once per advertisement.
 *
 * The permissions are asked from Dart first (DevicePlugin: BLUETOOTH_SCAN, and
 * with it the location that a scan needs here: the manifest does not declare
 * neverForLocation, which would hide beacons from the scanner). The sightings
 * event is a map {t, beacons: [{uuid, major, minor, rssi, count}]}.
 */
@SuppressLint("MissingPermission")
class BeaconScanPlugin(private val activity: Activity, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler, EventChannel.StreamHandler {
    private val methods = MethodChannel(messenger, "org.atalaia.app/beacons")
    private val events = EventChannel(messenger, "org.atalaia.app/beacons/sightings")
    private val handler = Handler(Looper.getMainLooper())
    private var sink: EventChannel.EventSink? = null
    private var callback: ScanCallback? = null
    private var windowMs = 5_000L
    private val heard = HashMap<String, Heard>()

    private class Heard(val uuid: String, val major: Int, val minor: Int) {
        var sum = 0L
        var count = 0
    }

    init {
        methods.setMethodCallHandler(this)
        events.setStreamHandler(this)
    }

    private val adapter
        get() = (activity.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager?)?.adapter

    private fun has(permission: String): Boolean =
        activity.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

    /** Before Android 12 a scan needs the location; from 12 the scan permission and, as the manifest does not
     * say the scan is never for location, the location too. */
    private fun granted(): Boolean =
        has(android.Manifest.permission.ACCESS_FINE_LOCATION) &&
            (Build.VERSION.SDK_INT < 31 || has(android.Manifest.permission.BLUETOOTH_SCAN))

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "available" -> result.success(
                activity.packageManager.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE) && adapter != null,
            )
            "granted" -> result.success(granted())
            "enabled" -> result.success(adapter?.isEnabled == true)
            else -> result.notImplemented()
        }
    }

    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        val scanner = adapter?.takeIf { it.isEnabled }?.bluetoothLeScanner
        if (events == null) return
        if (scanner == null || !granted()) {
            events.error("unavailable", "Bluetooth is off or the permission is missing", null)
            return
        }
        val args = arguments as? Map<*, *>
        val uuids = (args?.get("uuids") as? List<*>)?.mapNotNull { parseUuid(it as? String) } ?: emptyList()
        if (uuids.isEmpty()) {
            events.error("no_beacons", "no beacon UUIDs to listen for", null)
            return
        }
        windowMs = ((args?.get("window_ms") as? Number)?.toLong() ?: 5_000L).coerceIn(3_000L, 30_000L)
        sink = events
        heard.clear()
        val filters = uuids.map { uuid ->
            val data = ByteArray(18)
            data[0] = 0x02
            data[1] = 0x15
            for (i in 0 until 8) {
                data[2 + i] = (uuid.mostSignificantBits ushr (56 - 8 * i)).toByte()
                data[10 + i] = (uuid.leastSignificantBits ushr (56 - 8 * i)).toByte()
            }
            ScanFilter.Builder().setManufacturerData(APPLE_ID, data, ByteArray(18) { 0xFF.toByte() }).build()
        }
        val settings = ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_POWER).build()
        val cb = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) = record(result)
            override fun onBatchScanResults(results: MutableList<ScanResult>) = results.forEach { record(it) }
            override fun onScanFailed(errorCode: Int) {
                sink?.error("scan_failed", "the Bluetooth scan failed: $errorCode", null)
            }
        }
        callback = cb
        try {
            scanner.startScan(filters, settings, cb)
        } catch (e: SecurityException) {
            callback = null
            sink = null
            events.error("permission", e.message, null)
            return
        }
        handler.postDelayed(flush, windowMs)
    }

    override fun onCancel(arguments: Any?) {
        handler.removeCallbacks(flush)
        callback?.let { adapter?.bluetoothLeScanner?.stopScan(it) }
        callback = null
        sink = null
        heard.clear() // nothing heard is kept
    }

    private val flush = object : Runnable {
        override fun run() {
            val out = sink ?: return
            val list = heard.values.map {
                mapOf(
                    "uuid" to it.uuid,
                    "major" to it.major,
                    "minor" to it.minor,
                    "rssi" to Math.round(it.sum.toDouble() / it.count).toInt(),
                    "count" to it.count,
                )
            }
            heard.clear()
            out.success(mapOf("t" to System.currentTimeMillis(), "beacons" to list))
            handler.postDelayed(this, windowMs)
        }
    }

    /** One advertisement: an iBeacon's manufacturer data is the type 0x02, the length 0x15, the UUID (16 bytes),
     * major and minor (big endian) and the calibrated power. Anything else is dropped. */
    private fun record(result: ScanResult) {
        val d = result.scanRecord?.getManufacturerSpecificData(APPLE_ID) ?: return
        if (d.size < 23 || d[0] != 0x02.toByte() || d[1] != 0x15.toByte()) return
        var msb = 0L
        var lsb = 0L
        for (i in 0 until 8) {
            msb = (msb shl 8) or (d[2 + i].toLong() and 0xFF)
            lsb = (lsb shl 8) or (d[10 + i].toLong() and 0xFF)
        }
        val uuid = UUID(msb, lsb).toString().uppercase(Locale.ROOT)
        val major = ((d[18].toInt() and 0xFF) shl 8) or (d[19].toInt() and 0xFF)
        val minor = ((d[20].toInt() and 0xFF) shl 8) or (d[21].toInt() and 0xFF)
        val h = heard.getOrPut("$uuid/$major/$minor") { Heard(uuid, major, minor) }
        h.sum += result.rssi
        h.count += 1
    }

    private fun parseUuid(text: String?): UUID? = try {
        text?.let { UUID.fromString(it) }
    } catch (e: IllegalArgumentException) {
        null
    }

    companion object {
        /** Apple's Bluetooth company id: iBeacon advertisements carry it. */
        private const val APPLE_ID = 0x004C
    }
}
