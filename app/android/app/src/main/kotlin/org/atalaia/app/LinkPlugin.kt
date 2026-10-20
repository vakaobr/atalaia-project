// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.content.Intent
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * Links that open the app (lib/platform/links.dart): `atalaia://register?...`
 * from a site server's register page (decision S16-13). The link that
 * started the app is kept until Dart asks for it ("initial", once); a link
 * that arrives while the app runs (singleTop: onNewIntent) is sent to Dart
 * as "link". Only `atalaia:` links are passed on; Dart checks the rest.
 */
class LinkPlugin(messenger: BinaryMessenger, intent: Intent?) : MethodChannel.MethodCallHandler {
    private val channel = MethodChannel(messenger, "org.atalaia.app/links")
    private var initial: String? = linkOf(intent)

    init {
        channel.setMethodCallHandler(this)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "initial" -> {
                result.success(initial)
                initial = null
            }
            else -> result.notImplemented()
        }
    }

    fun onNewIntent(intent: Intent) {
        linkOf(intent)?.let { channel.invokeMethod("link", it) }
    }

    private fun linkOf(intent: Intent?): String? {
        if (intent?.action != Intent.ACTION_VIEW) return null
        val data = intent.dataString ?: return null
        return if (data.startsWith("atalaia:") && data.length <= 4096) data else null
    }
}
