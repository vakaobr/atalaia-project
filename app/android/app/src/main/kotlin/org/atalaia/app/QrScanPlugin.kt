// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * Scans one QR code with [QrScanActivity] (CameraX for the picture, ZXing
 * for the decoding: no Google Play services, decision PD5) and returns its
 * text: a join code (atalaia:join:...) or a scoreboard address.
 */
class QrScanPlugin(private val activity: Activity, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler {
    private val channel = MethodChannel(messenger, "org.atalaia.app/qr")
    private var pending: MethodChannel.Result? = null

    init {
        channel.setMethodCallHandler(this)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "available" -> result.success(
                activity.packageManager.hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY),
            )
            "scan" -> {
                pending?.success(null)
                pending = result
                val intent = Intent(activity, QrScanActivity::class.java)
                    .putExtra(QrScanActivity.EXTRA_HINT, call.argument<String>("hint") ?: "")
                    .putExtra(QrScanActivity.EXTRA_CANCEL, call.argument<String>("cancel") ?: "")
                @Suppress("DEPRECATION")
                activity.startActivityForResult(intent, REQUEST)
            }
            else -> result.notImplemented()
        }
    }

    /** MainActivity forwards the scanner's result here. */
    fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != REQUEST) return
        val result = pending ?: return
        pending = null
        result.success(
            if (resultCode == Activity.RESULT_OK) data?.getStringExtra(QrScanActivity.EXTRA_TEXT) else null,
        )
    }

    companion object {
        private const val REQUEST = 7201
    }
}
