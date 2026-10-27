// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.File

/**
 * Hands files the app made (a replica's QR label, as a PNG) to Android's
 * share sheet (lib/platform/channels.dart, ChannelFileSharer), which also
 * lists the system's print service. The bytes come from Dart, are written
 * under the app's cache (`labels/`, emptied at every call) and shared as
 * content:// links of the [FileProvider] named in the manifest, so no
 * storage permission is needed and nothing stays public.
 */
class ShareFilePlugin(private val context: Context, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler {
    private val channel = MethodChannel(messenger, "org.atalaia.app/share")

    init {
        channel.setMethodCallHandler(this)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "available" -> result.success(true)
            "share" -> {
                val files = call.argument<List<Map<String, Any?>>>("files")
                val mime = call.argument<String>("mime") ?: "image/png"
                val title = call.argument<String>("title") ?: ""
                if (files.isNullOrEmpty() || files.size > MAX_FILES) {
                    result.success(false)
                    return
                }
                result.success(share(files, mime, title))
            }
            else -> result.notImplemented()
        }
    }

    private fun share(files: List<Map<String, Any?>>, mime: String, title: String): Boolean {
        return try {
            val dir = File(context.cacheDir, "labels")
            dir.deleteRecursively()
            dir.mkdirs()
            val uris = ArrayList<Uri>()
            for (f in files) {
                // Only a plain file name: nothing from Dart picks a folder.
                val name = File(f["name"] as? String ?: continue).name
                val bytes = f["bytes"] as? ByteArray ?: continue
                if (name.isEmpty() || !name.endsWith(".png")) continue
                val file = File(dir, name)
                file.writeBytes(bytes)
                uris.add(FileProvider.getUriForFile(context, "${context.packageName}.labels", file))
            }
            if (uris.isEmpty()) return false
            val send = Intent(if (uris.size == 1) Intent.ACTION_SEND else Intent.ACTION_SEND_MULTIPLE)
                .setType(mime)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            if (uris.size == 1) {
                send.putExtra(Intent.EXTRA_STREAM, uris[0])
            } else {
                send.putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
            }
            if (title.isNotEmpty()) send.putExtra(Intent.EXTRA_TITLE, title)
            val clip = ClipData.newRawUri("", uris[0])
            for (u in uris.drop(1)) clip.addItem(ClipData.Item(u))
            send.clipData = clip
            val chooser = Intent.createChooser(send, title.ifEmpty { null })
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(chooser)
            true
        } catch (e: Exception) {
            false
        }
    }

    private companion object {
        const val MAX_FILES = 20
    }
}
