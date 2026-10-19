// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.annotation.SuppressLint
import android.app.Activity
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelUuid
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.util.ArrayDeque
import java.util.UUID

/**
 * The I/O pod over Bluetooth LE (protocol/capability-proxy.md): a scan for
 * the pod service, then a GATT link with a 247-byte MTU, notifications on
 * Pod TX (the pod's frames, handed to Dart as bytes) and writes without
 * response to Pod RX (the phone's frames, cut to the MTU and sent one after
 * the other). The run-time permissions are asked from Dart first. The pod
 * firmware (firmware/esp32/main/pod/) asks to pair on connection (Android
 * shows its question) and sends its frames once the link is encrypted. Not
 * run against a real pod yet (plan phase G).
 */
@SuppressLint("MissingPermission")
class BlePodPlugin(private val activity: Activity, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler, EventChannel.StreamHandler {
    private val channel = MethodChannel(messenger, "org.atalaia.app/pod/ble")
    private val events = EventChannel(messenger, "org.atalaia.app/pod/ble/bytes")
    private val main = Handler(Looper.getMainLooper())
    private val manager = activity.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager?
    private var sink: EventChannel.EventSink? = null
    private var gatt: BluetoothGatt? = null
    private var rx: BluetoothGattCharacteristic? = null
    private var mtu = 23
    private val queue = ArrayDeque<ByteArray>()
    private var writing = false
    private var opening: MethodChannel.Result? = null

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
        try {
            when (call.method) {
                "find" -> find(call.argument<Int>("scan_ms") ?: 4000, result)
                "open" -> open(call.argument<String>("id") ?: "", result)
                "write" -> {
                    call.argument<ByteArray>("bytes")?.let(::write)
                    result.success(null)
                }
                "close" -> {
                    close()
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        } catch (e: SecurityException) {
            result.error("permission", e.message, null)
        }
    }

    private fun find(scanMs: Int, result: MethodChannel.Result) {
        val scanner = manager?.adapter?.bluetoothLeScanner
        if (scanner == null) {
            result.success(emptyList<Map<String, String>>())
            return
        }
        val found = linkedMapOf<String, String>()
        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, r: ScanResult) {
                val name = try {
                    r.device.name
                } catch (e: SecurityException) {
                    null
                }
                found[r.device.address] = name ?: r.scanRecord?.deviceName ?: "atalaia-pod"
            }
        }
        val filter = ScanFilter.Builder().setServiceUuid(ParcelUuid(SERVICE)).build()
        val settings = ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build()
        scanner.startScan(listOf(filter), settings, callback)
        main.postDelayed(
            {
                try {
                    scanner.stopScan(callback)
                } catch (e: SecurityException) {
                    // Permission withdrawn meanwhile.
                }
                result.success(found.map { (id, name) -> mapOf("id" to id, "name" to name) })
            },
            scanMs.toLong(),
        )
    }

    private fun open(address: String, result: MethodChannel.Result) {
        close()
        val device: BluetoothDevice? = try {
            manager?.adapter?.getRemoteDevice(address)
        } catch (e: IllegalArgumentException) {
            null
        }
        if (device == null) {
            result.success(false)
            return
        }
        opening = result
        gatt = device.connectGatt(activity, false, callback, BluetoothDevice.TRANSPORT_LE)
    }

    private fun opened(ok: Boolean) {
        main.post {
            opening?.success(ok)
            opening = null
        }
    }

    private val callback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                g.requestMtu(247)
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                opened(false)
                main.post { sink?.endOfStream() }
            }
        }

        override fun onMtuChanged(g: BluetoothGatt, mtu: Int, status: Int) {
            this@BlePodPlugin.mtu = mtu
            g.discoverServices()
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            val service = g.getService(SERVICE)
            val tx = service?.getCharacteristic(POD_TX)
            rx = service?.getCharacteristic(POD_RX)
            val cccd = tx?.getDescriptor(CCCD)
            if (tx == null || rx == null || cccd == null) {
                opened(false)
                return
            }
            g.setCharacteristicNotification(tx, true)
            val enable = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
            if (Build.VERSION.SDK_INT >= 33) {
                g.writeDescriptor(cccd, enable)
            } else {
                legacyWriteDescriptor(g, cccd, enable)
            }
        }

        override fun onDescriptorWrite(g: BluetoothGatt, d: BluetoothGattDescriptor, status: Int) {
            opened(status == BluetoothGatt.GATT_SUCCESS)
        }

        // Android 13 and later.
        override fun onCharacteristicChanged(
            g: BluetoothGatt,
            c: BluetoothGattCharacteristic,
            value: ByteArray,
        ) {
            if (c.uuid == POD_TX) main.post { sink?.success(value) }
        }

        // Before Android 13.
        @Deprecated("Replaced by the overload with the value on Android 13")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION")
            val value = c.value
            if (Build.VERSION.SDK_INT < 33 && c.uuid == POD_TX && value != null) {
                main.post { sink?.success(value.copyOf()) }
            }
        }

        override fun onCharacteristicWrite(
            g: BluetoothGatt,
            c: BluetoothGattCharacteristic,
            status: Int,
        ) {
            main.post {
                writing = false
                sendNext()
            }
        }
    }

    /** Queues [bytes], cut to what one write carries (MTU - 3). */
    private fun write(bytes: ByteArray) {
        val chunk = (mtu - 3).coerceAtLeast(20)
        var i = 0
        while (i < bytes.size) {
            queue.add(bytes.copyOfRange(i, minOf(bytes.size, i + chunk)))
            i += chunk
        }
        sendNext()
    }

    private fun sendNext() {
        if (writing) return
        val g = gatt ?: return
        val c = rx ?: return
        val next = queue.poll() ?: return
        writing = true
        val type = BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
        val ok = if (Build.VERSION.SDK_INT >= 33) {
            g.writeCharacteristic(c, next, type) == BluetoothGatt.GATT_SUCCESS
        } else {
            legacyWrite(g, c, next, type)
        }
        if (!ok) {
            // Busy: try again shortly.
            queue.addFirst(next)
            writing = false
            main.postDelayed(::sendNext, 20)
        }
    }

    /** Before Android 13: the value goes on the descriptor object. */
    @Suppress("DEPRECATION")
    private fun legacyWriteDescriptor(g: BluetoothGatt, d: BluetoothGattDescriptor, value: ByteArray) {
        d.value = value
        g.writeDescriptor(d)
    }

    /** Before Android 13: the value goes on the characteristic object. */
    @Suppress("DEPRECATION")
    private fun legacyWrite(
        g: BluetoothGatt,
        c: BluetoothGattCharacteristic,
        value: ByteArray,
        type: Int,
    ): Boolean {
        c.writeType = type
        c.value = value
        return g.writeCharacteristic(c)
    }

    fun close() {
        queue.clear()
        writing = false
        rx = null
        gatt?.let {
            try {
                it.disconnect()
                it.close()
            } catch (e: SecurityException) {
                // Permission withdrawn: the link is gone anyway.
            }
        }
        gatt = null
    }

    companion object {
        val SERVICE: UUID = UUID.fromString("4174616c-6169-6100-0000-000000000000")
        val POD_TX: UUID = UUID.fromString("4174616c-6169-6100-0000-000000000001")
        val POD_RX: UUID = UUID.fromString("4174616c-6169-6100-0000-000000000002")
        val CCCD: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
    }
}
