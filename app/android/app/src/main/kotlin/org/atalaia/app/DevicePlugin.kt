// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioManager
import android.media.ToneGenerator
import android.net.Uri
import android.nfc.NfcAdapter
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.Settings
import android.view.WindowManager
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * The phone itself (lib/platform/services.dart DeviceServices): the app's
 * private folder, the maker, the hardware a prop can use, vibration and
 * tones for a mode's sounds, the screen (keep on, brightness: ADR-P3-5's
 * screen management), the battery-optimisation exemption, and run-time
 * permissions.
 */
class DevicePlugin(private val activity: Activity, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler {
    private val channel = MethodChannel(messenger, "org.atalaia.app/device")
    private val main = Handler(Looper.getMainLooper())
    private val pendingPermissions = mutableMapOf<Int, MethodChannel.Result>()
    private var nextRequest = 7100

    init {
        channel.setMethodCallHandler(this)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "filesDir" -> result.success(activity.filesDir.absolutePath)
            "manufacturer" -> result.success(Build.MANUFACTURER.lowercase())
            "features" -> result.success(features())
            "vibrate" -> {
                vibrate(call.argument<List<Int>>("pattern") ?: listOf(0, 200))
                result.success(null)
            }
            "tone" -> {
                tone(call.argument<String>("tone") ?: "beep", call.argument<Int>("ms") ?: 150)
                result.success(null)
            }
            "keepScreenOn" -> {
                val on = call.argument<Boolean>("on") ?: false
                activity.runOnUiThread {
                    if (on) {
                        activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    } else {
                        activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    }
                }
                result.success(null)
            }
            "setBrightness" -> {
                val level = call.argument<Double>("level")
                activity.runOnUiThread {
                    val attrs = activity.window.attributes
                    attrs.screenBrightness = level?.toFloat()?.coerceIn(0.01f, 1f)
                        ?: WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
                    activity.window.attributes = attrs
                }
                result.success(null)
            }
            "ignoringBatteryOptimizations" -> {
                val pm = activity.getSystemService(Context.POWER_SERVICE) as PowerManager
                result.success(pm.isIgnoringBatteryOptimizations(activity.packageName))
            }
            "requestIgnoreBatteryOptimizations" -> {
                start(
                    Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                        .setData(Uri.parse("package:${activity.packageName}")),
                )
                result.success(null)
            }
            "openBatterySettings" -> {
                start(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
                result.success(null)
            }
            "requestPermission" -> requestPermission(call.argument<String>("name") ?: "", result)
            else -> result.notImplemented()
        }
    }

    private fun start(intent: Intent) {
        try {
            activity.startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            // Some makers remove these screens; the guide explains the way by hand.
        }
    }

    private fun features(): Map<String, Boolean> {
        val pm = activity.packageManager
        val nfc = NfcAdapter.getDefaultAdapter(activity)
        return mapOf(
            "nfc" to (nfc != null),
            "nfc_enabled" to (nfc?.isEnabled == true),
            "camera" to pm.hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY),
            "location" to pm.hasSystemFeature(PackageManager.FEATURE_LOCATION_GPS),
            "vibrator" to vibrator().hasVibrator(),
            "accelerometer" to pm.hasSystemFeature(PackageManager.FEATURE_SENSOR_ACCELEROMETER),
            "bluetooth_le" to pm.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE),
            "usb_host" to pm.hasSystemFeature(PackageManager.FEATURE_USB_HOST),
            "touchscreen" to pm.hasSystemFeature(PackageManager.FEATURE_TOUCHSCREEN),
        )
    }

    private fun vibrator(): Vibrator =
        if (Build.VERSION.SDK_INT >= 31) {
            (activity.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager)
                .defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            activity.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        }

    private fun vibrate(pattern: List<Int>) {
        val v = vibrator()
        if (!v.hasVibrator() || pattern.isEmpty()) return
        v.vibrate(VibrationEffect.createWaveform(pattern.map { it.toLong() }.toLongArray(), -1))
    }

    private fun tone(name: String, ms: Int) {
        val kind = when (name) {
            "ack" -> ToneGenerator.TONE_PROP_ACK
            "alarm" -> ToneGenerator.TONE_CDMA_EMERGENCY_RINGBACK
            "warning" -> ToneGenerator.TONE_PROP_BEEP2
            "success" -> ToneGenerator.TONE_CDMA_CONFIRM
            else -> ToneGenerator.TONE_PROP_BEEP
        }
        try {
            val gen = ToneGenerator(AudioManager.STREAM_MUSIC, 100)
            gen.startTone(kind, ms)
            main.postDelayed({ gen.release() }, ms.toLong() + 100)
        } catch (e: RuntimeException) {
            // No audio right now (another app holds it): the vibration still tells.
        }
    }

    private fun requestPermission(name: String, result: MethodChannel.Result) {
        // Before Android 12 a Bluetooth scan needs the location permission
        // instead; before 13 notifications need none.
        val permission = when {
            name == "POST_NOTIFICATIONS" && Build.VERSION.SDK_INT < 33 -> null
            (name == "BLUETOOTH_SCAN" || name == "BLUETOOTH_CONNECT") && Build.VERSION.SDK_INT < 31 ->
                if (name == "BLUETOOTH_SCAN") "android.permission.ACCESS_FINE_LOCATION" else null
            else -> "android.permission.$name"
        }
        if (permission == null ||
            activity.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
        ) {
            result.success(true)
            return
        }
        val code = nextRequest++
        pendingPermissions[code] = result
        activity.requestPermissions(arrayOf(permission), code)
    }

    /** MainActivity forwards the answers here. */
    fun onPermissionsResult(requestCode: Int, grantResults: IntArray) {
        val result = pendingPermissions.remove(requestCode) ?: return
        result.success(
            grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED,
        )
    }
}
