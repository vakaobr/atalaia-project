// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * Lets the user pick one file with Android's own chooser
 * (ACTION_OPEN_DOCUMENT: no storage permission is asked, the app only sees
 * the file the user picked) and hands its name and bytes to Dart
 * (lib/platform/channels.dart, ChannelFilePicker). Used by the phone
 * controller's registration import (decision PIM-1). At most `max_bytes` + 1
 * bytes are read, so a file over the limit is told apart without reading it
 * whole; the read runs off the main thread.
 */
class FilePickerPlugin(private val activity: Activity, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler {
    private val channel = MethodChannel(messenger, "org.atalaia.app/files")
    private var pending: MethodChannel.Result? = null
    private var maxBytes = 0

    init {
        channel.setMethodCallHandler(this)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "available" -> result.success(true)
            "pick" -> {
                pending?.success(null)
                pending = result
                maxBytes = (call.argument<Int>("max_bytes") ?: 0).coerceIn(0, MAX_READ)
                val mimes = call.argument<List<String>>("mimes").orEmpty()
                val intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
                    .addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("*/*")
                if (mimes.isNotEmpty()) {
                    intent.putExtra(Intent.EXTRA_MIME_TYPES, mimes.toTypedArray())
                }
                try {
                    @Suppress("DEPRECATION")
                    activity.startActivityForResult(intent, REQUEST)
                } catch (e: Exception) {
                    pending = null
                    result.success(null)
                }
            }
            else -> result.notImplemented()
        }
    }

    /** MainActivity forwards the chooser's result here. */
    fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != REQUEST) return
        val result = pending ?: return
        pending = null
        val uri = data?.data
        if (resultCode != Activity.RESULT_OK || uri == null) {
            result.success(null)
            return
        }
        val limit = maxBytes
        Thread {
            val answer = read(uri, limit)
            activity.runOnUiThread { result.success(answer) }
        }.start()
    }

    private fun read(uri: Uri, limit: Int): Map<String, Any>? {
        return try {
            val name = activity.contentResolver
                .query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                ?.use { if (it.moveToFirst()) it.getString(0) else null }
                ?: uri.lastPathSegment
                ?: ""
            val bytes = activity.contentResolver.openInputStream(uri)?.use { input ->
                val out = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                var left = limit + 1
                while (left > 0) {
                    val n = input.read(buffer, 0, minOf(buffer.size, left))
                    if (n < 0) break
                    out.write(buffer, 0, n)
                    left -= n
                }
                out.toByteArray()
            } ?: return null
            // Only a plain file name: nothing of the path goes to Dart.
            mapOf("name" to java.io.File(name).name, "bytes" to bytes)
        } catch (e: Exception) {
            null
        }
    }

    companion object {
        private const val REQUEST = 7202
        private const val MAX_READ = 16 * 1024 * 1024
    }
}
