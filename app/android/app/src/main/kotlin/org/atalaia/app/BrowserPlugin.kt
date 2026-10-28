// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.app.Activity
import android.content.ActivityNotFoundException
import android.net.Uri
import androidx.browser.customtabs.CustomTabsIntent
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * The system browser in a Custom Tab, for a social login (decision PKA-1,
 * lib/site/site_auth.dart): the site server's address that starts the login
 * opens here, the person signs in at the provider, and the server's redirect
 * to the app's own https link (`/app/oidc`, an Android App Link) comes back
 * to [LinkPlugin]. Only https addresses open; the app is not given the
 * browser's cookies or pages.
 */
class BrowserPlugin(private val activity: Activity, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler {
    init {
        MethodChannel(messenger, "org.atalaia.app/browser").setMethodCallHandler(this)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        if (call.method != "open") {
            result.notImplemented()
            return
        }
        val uri = call.argument<String>("url")?.let { Uri.parse(it) }
        if (uri == null || uri.scheme != "https" || uri.host.isNullOrEmpty()) {
            result.success(false)
            return
        }
        try {
            CustomTabsIntent.Builder().setShowTitle(true).build().launchUrl(activity, uri)
            result.success(true)
        } catch (e: ActivityNotFoundException) {
            result.success(false)
        }
    }
}
