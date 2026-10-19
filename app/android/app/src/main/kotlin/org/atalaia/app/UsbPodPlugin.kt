// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.app.Activity
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.Executors

/**
 * The I/O pod over USB-OTG (protocol/capability-proxy.md): the pod is a USB
 * CDC ACM device; this opens it with Android's UsbManager, sets 921600 baud
 * 8N1 and DTR, reads its bulk-in endpoint on a thread and hands the bytes
 * to Dart (lib/pod/pod_client.dart finds the frames). No pod firmware
 * exists yet (plan phase F): this has not been run against hardware.
 */
class UsbPodPlugin(private val activity: Activity, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler, EventChannel.StreamHandler {
    private val channel = MethodChannel(messenger, "org.atalaia.app/pod/usb")
    private val events = EventChannel(messenger, "org.atalaia.app/pod/usb/bytes")
    private val main = Handler(Looper.getMainLooper())
    private val writer = Executors.newSingleThreadExecutor()
    private val usb = activity.getSystemService(Context.USB_SERVICE) as UsbManager
    private var sink: EventChannel.EventSink? = null
    private var link: Link? = null

    private class Link(
        val connection: UsbDeviceConnection,
        val data: UsbInterface,
        val control: UsbInterface?,
        val input: UsbEndpoint,
        val output: UsbEndpoint,
    ) {
        @Volatile
        var open = true
    }

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
            "find" -> result.success(
                usb.deviceList.values.filter(::isCdc).map {
                    mapOf(
                        "id" to it.deviceName,
                        "name" to (it.productName ?: "USB %04x:%04x".format(it.vendorId, it.productId)),
                    )
                },
            )
            "open" -> {
                val device = usb.deviceList[call.argument<String>("id")]
                if (device == null) {
                    result.success(false)
                } else if (usb.hasPermission(device)) {
                    result.success(open(device))
                } else {
                    askPermission(device) { granted -> result.success(granted && open(device)) }
                }
            }
            "write" -> {
                val bytes = call.argument<ByteArray>("bytes")
                val l = link
                if (bytes != null && l != null) {
                    writer.execute { l.connection.bulkTransfer(l.output, bytes, bytes.size, 500) }
                }
                result.success(null)
            }
            "close" -> {
                close()
                result.success(null)
            }
            else -> result.notImplemented()
        }
    }

    private fun isCdc(d: UsbDevice) = (0 until d.interfaceCount).any {
        d.getInterface(it).interfaceClass == UsbConstants.USB_CLASS_CDC_DATA
    }

    private fun askPermission(device: UsbDevice, done: (Boolean) -> Unit) {
        val action = "${activity.packageName}.USB_PERMISSION"
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                activity.unregisterReceiver(this)
                done(intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false))
            }
        }
        val filter = IntentFilter(action)
        if (Build.VERSION.SDK_INT >= 33) {
            activity.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            activity.registerReceiver(receiver, filter)
        }
        // The system fills in EXTRA_PERMISSION_GRANTED, so the intent is
        // mutable; it is explicit (this package only).
        val intent = Intent(action).setPackage(activity.packageName)
        val flags = if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0
        usb.requestPermission(device, PendingIntent.getBroadcast(activity, 0, intent, flags))
    }

    private fun open(device: UsbDevice): Boolean {
        close()
        var data: UsbInterface? = null
        var control: UsbInterface? = null
        for (i in 0 until device.interfaceCount) {
            val itf = device.getInterface(i)
            when (itf.interfaceClass) {
                UsbConstants.USB_CLASS_CDC_DATA -> data = data ?: itf
                UsbConstants.USB_CLASS_COMM -> control = control ?: itf
            }
        }
        val itf = data ?: return false
        var input: UsbEndpoint? = null
        var output: UsbEndpoint? = null
        for (e in 0 until itf.endpointCount) {
            val ep = itf.getEndpoint(e)
            if (ep.type != UsbConstants.USB_ENDPOINT_XFER_BULK) continue
            if (ep.direction == UsbConstants.USB_DIR_IN) input = ep else output = ep
        }
        if (input == null || output == null) return false
        val connection = usb.openDevice(device) ?: return false
        control?.let { connection.claimInterface(it, true) }
        if (!connection.claimInterface(itf, true)) {
            connection.close()
            return false
        }
        // CDC SET_LINE_CODING: 921600 baud, 1 stop bit, no parity, 8 data bits.
        val baud = 921600
        val coding = byteArrayOf(
            (baud and 0xff).toByte(), (baud shr 8 and 0xff).toByte(),
            (baud shr 16 and 0xff).toByte(), (baud shr 24 and 0xff).toByte(), 0, 0, 8,
        )
        val ctrl = control?.id ?: 0
        connection.controlTransfer(0x21, 0x20, 0, ctrl, coding, coding.size, 500)
        // SET_CONTROL_LINE_STATE: DTR and RTS on (the ESP32-S3 waits for DTR).
        connection.controlTransfer(0x21, 0x22, 0x03, ctrl, null, 0, 500)
        val l = Link(connection, itf, control, input, output)
        link = l
        Thread({ readLoop(l) }, "atalaia-usb-pod").start()
        return true
    }

    private fun readLoop(l: Link) {
        val buf = ByteArray(l.input.maxPacketSize.coerceAtLeast(64) * 4)
        while (l.open) {
            val n = l.connection.bulkTransfer(l.input, buf, buf.size, 200)
            if (n > 0) {
                val chunk = buf.copyOf(n)
                main.post { sink?.success(chunk) }
            }
        }
    }

    fun close() {
        val l = link ?: return
        link = null
        l.open = false
        l.connection.releaseInterface(l.data)
        l.control?.let { l.connection.releaseInterface(it) }
        l.connection.close()
    }
}
