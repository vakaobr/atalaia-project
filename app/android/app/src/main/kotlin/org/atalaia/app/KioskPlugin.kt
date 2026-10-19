// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.app.Activity
import android.app.ActivityManager
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * Kiosk mode (ADR-P3-5, ADR-P3-9): Android's lock task. When the app is the
 * device owner (set with `adb shell dpm set-device-owner
 * org.atalaia.app/.AtalaiaAdminReceiver` on a phone kept for props), it may
 * lock itself silently; otherwise Android asks the user to confirm screen
 * pinning. The Dart side polls isActive while a game runs (tamper check).
 */
class KioskPlugin(private val activity: Activity, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler {
    private val channel = MethodChannel(messenger, "org.atalaia.app/kiosk")

    init {
        channel.setMethodCallHandler(this)
    }

    private val dpm: DevicePolicyManager
        get() = activity.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager

    private fun isOwner() = dpm.isDeviceOwnerApp(activity.packageName)

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "start" -> activity.runOnUiThread {
                try {
                    if (isOwner()) {
                        val admin = ComponentName(activity, AtalaiaAdminReceiver::class.java)
                        dpm.setLockTaskPackages(admin, arrayOf(activity.packageName))
                    }
                    activity.startLockTask()
                    result.success(true)
                } catch (e: RuntimeException) {
                    result.success(false)
                }
            }
            "stop" -> activity.runOnUiThread {
                try {
                    activity.stopLockTask()
                } catch (e: RuntimeException) {
                    // Not in lock task mode.
                }
                result.success(null)
            }
            "isActive" -> {
                val am = activity.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
                result.success(am.lockTaskModeState != ActivityManager.LOCK_TASK_MODE_NONE)
            }
            "isDeviceOwner" -> result.success(isOwner())
            else -> result.notImplemented()
        }
    }
}
