// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.app.Activity
import android.nfc.FormatException
import android.nfc.NdefMessage
import android.nfc.NfcAdapter
import android.nfc.Tag
import android.nfc.TagLostException
import android.nfc.tech.Ndef
import android.nfc.tech.NdefFormatable
import android.os.Handler
import android.os.Looper
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.IOException

/**
 * NFC in reader mode while a screen wants tags (ADR-P3-10: foreground
 * only): each tag's UID and NDEF message go to Dart on an event channel
 * (players' tags, join cards, replica stickers: lib/security/ndef.dart reads
 * the records). Writing puts an NDEF message on the next tag held to the
 * phone (players' tags: lib/marshal/tag_writer.dart). The Dart code checks
 * every signature; nothing here trusts a tag.
 */
class NfcPlugin(private val activity: Activity, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler, EventChannel.StreamHandler {
    private val channel = MethodChannel(messenger, "org.atalaia.app/nfc")
    private val events = EventChannel(messenger, "org.atalaia.app/nfc/reads")
    private val main = Handler(Looper.getMainLooper())
    private val adapter: NfcAdapter? = NfcAdapter.getDefaultAdapter(activity)
    private var sink: EventChannel.EventSink? = null
    private var reading = false
    private var resumed = true
    @Volatile
    private var pendingWrite: Pair<ByteArray, MethodChannel.Result>? = null

    init {
        channel.setMethodCallHandler(this)
        events.setStreamHandler(this)
    }

    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        sink = events
    }

    override fun onCancel(arguments: Any?) {
        sink = null
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "state" -> result.success(
                when {
                    adapter == null -> "unavailable"
                    !adapter.isEnabled -> "off"
                    else -> "ready"
                },
            )
            "startReading" -> {
                reading = true
                update()
                result.success(null)
            }
            "stopReading" -> {
                reading = false
                update()
                result.success(null)
            }
            "writeNext" -> {
                val bytes = call.argument<ByteArray>("ndef")
                if (adapter == null || bytes == null) {
                    result.error("unavailable", "no NFC", null)
                    return
                }
                pendingWrite?.second?.error("cancelled", "another write", null)
                pendingWrite = bytes to result
                update()
            }
            "cancelWrite" -> {
                pendingWrite?.second?.error("cancelled", "cancelled", null)
                pendingWrite = null
                update()
                result.success(null)
            }
            else -> result.notImplemented()
        }
    }

    fun onResume() {
        resumed = true
        update()
    }

    fun onPause() {
        resumed = false
        try {
            adapter?.disableReaderMode(activity)
        } catch (e: IllegalStateException) {
            // Already off.
        }
    }

    /** Reader mode is on while someone listens or waits to write, and the app is in front. */
    private fun update() {
        val nfc = adapter ?: return
        try {
            if (resumed && (reading || pendingWrite != null)) {
                nfc.enableReaderMode(activity, ::onTag, FLAGS, null)
            } else {
                nfc.disableReaderMode(activity)
            }
        } catch (e: IllegalStateException) {
            // The activity is not in the foreground; onResume tries again.
        }
    }

    /** On a binder thread. */
    private fun onTag(tag: Tag) {
        val write = pendingWrite
        if (write != null) {
            pendingWrite = null
            val error = write(tag, write.first)
            main.post {
                if (error == null) write.second.success(tag.id) else write.second.error(error, error, null)
                update()
            }
            return
        }
        var message: ByteArray? = null
        var writable = false
        Ndef.get(tag)?.let { ndef ->
            try {
                ndef.connect()
                message = (ndef.ndefMessage ?: ndef.cachedNdefMessage)?.toByteArray()
                writable = ndef.isWritable
            } catch (e: IOException) {
                message = ndef.cachedNdefMessage?.toByteArray()
            } catch (e: FormatException) {
                message = null
            } finally {
                try {
                    ndef.close()
                } catch (e: IOException) {
                    // Gone.
                }
            }
        }
        val read = mapOf("uid" to tag.id, "ndef" to message, "writable" to writable)
        main.post { sink?.success(read) }
    }

    /** Writes [bytes] (an NDEF message) to [tag]; null, or why not. */
    private fun write(tag: Tag, bytes: ByteArray): String? {
        val message = try {
            NdefMessage(bytes)
        } catch (e: FormatException) {
            return "io"
        }
        Ndef.get(tag)?.let { ndef ->
            return try {
                ndef.connect()
                when {
                    !ndef.isWritable -> "read_only"
                    ndef.maxSize < bytes.size -> "too_small"
                    else -> {
                        ndef.writeNdefMessage(message)
                        null
                    }
                }
            } catch (e: TagLostException) {
                "io"
            } catch (e: IOException) {
                "io"
            } catch (e: FormatException) {
                "io"
            } finally {
                try {
                    ndef.close()
                } catch (e: IOException) {
                    // Gone.
                }
            }
        }
        NdefFormatable.get(tag)?.let { blank ->
            return try {
                blank.connect()
                blank.format(message)
                null
            } catch (e: IOException) {
                "io"
            } catch (e: FormatException) {
                "io"
            } finally {
                try {
                    blank.close()
                } catch (e: IOException) {
                    // Gone.
                }
            }
        }
        return "not_ndef"
    }

    companion object {
        private const val FLAGS = NfcAdapter.FLAG_READER_NFC_A or NfcAdapter.FLAG_READER_NFC_B or
            NfcAdapter.FLAG_READER_NFC_F or NfcAdapter.FLAG_READER_NFC_V
    }
}
