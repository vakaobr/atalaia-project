// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.app.Activity
import android.content.Intent
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/** Starts, updates and stops [AtalaiaForegroundService] (ADR-P3-5). */
class ForegroundServicePlugin(private val activity: Activity, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler {
    private val channel = MethodChannel(messenger, "org.atalaia.app/foreground")

    init {
        channel.setMethodCallHandler(this)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        // The application's context: the activity may be gone while the
        // service and the engine run on (MainActivity).
        val context = activity.applicationContext
        val intent = Intent(context, AtalaiaForegroundService::class.java)
            .putExtra(AtalaiaForegroundService.EXTRA_TITLE, call.argument<String>("title") ?: "")
            .putExtra(AtalaiaForegroundService.EXTRA_TEXT, call.argument<String>("text") ?: "")
            .putExtra(AtalaiaForegroundService.EXTRA_LOCATION, call.argument<Boolean>("location") ?: false)
        when (call.method) {
            "start" -> try {
                context.startForegroundService(intent)
                result.success(true)
            } catch (e: RuntimeException) {
                // Android 12+ refuses a start from the background; the game runs on.
                result.success(false)
            }
            "update" -> {
                if (AtalaiaForegroundService.running) {
                    try {
                        context.startService(intent)
                    } catch (e: RuntimeException) {
                        // Not allowed now; the next update tries again.
                    }
                }
                result.success(null)
            }
            "stop" -> {
                context.stopService(Intent(context, AtalaiaForegroundService::class.java))
                result.success(null)
            }
            else -> result.notImplemented()
        }
    }
}
