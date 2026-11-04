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
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
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
 * firmware (firmware/esp32/main/pod/) asks to pair on connection and sends
 * its frames once the link is encrypted with a passkey's key: the pod shows
 * a 6-digit passkey on its OLED and Android's own pairing dialog asks for it
 * (decisions PODPK-1 to PODPK-11).
 *
 * How a pairing ended is kept for Dart ("last_error"): "pair_failed" when
 * Android's bond went from bonding to none (a wrong passkey, Cancel),
 * "pair_timeout" when it ended so for the time running out, "repair" when
 * the pod dropped the link with HCI reason 0x05, Authentication Failure: it
 * does not trust this phone's bond (made without a passkey by an older pod
 * firmware, or cleared on the pod), and has forgotten its side. "forget"
 * then removes the phone's side (BluetoothDevice.removeBond, a hidden API
 * reached by reflection; false when Android refuses it, and the person
 * forgets the pod in the Bluetooth settings), and the next open pairs anew.
 * Not run against a real pod yet (plan phase G).
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
    private var openingAddress: String? = null
    private var bondingSince = 0L
    private var lastError: String? = null
    private var bondWatch: BroadcastReceiver? = null

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
                "last_error" -> result.success(lastError)
                "forget" -> result.success(forget(call.argument<String>("id") ?: ""))
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
        openingAddress = address
        lastError = null
        watchBond()
        gatt = device.connectGatt(activity, false, callback, BluetoothDevice.TRANSPORT_LE)
    }

    /** Android's bond with the pod while a link opens: a pairing that failed or ran out. */
    private fun watchBond() {
        if (bondWatch != null) return
        val r = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                @Suppress("DEPRECATION")
                val d = intent.getParcelableExtra<BluetoothDevice>(BluetoothDevice.EXTRA_DEVICE)
                if (d?.address != openingAddress) return
                val state = intent.getIntExtra(BluetoothDevice.EXTRA_BOND_STATE, -1)
                val before = intent.getIntExtra(BluetoothDevice.EXTRA_PREVIOUS_BOND_STATE, -1)
                if (state == BluetoothDevice.BOND_BONDING) {
                    bondingSince = System.currentTimeMillis()
                } else if (state == BluetoothDevice.BOND_NONE &&
                    before == BluetoothDevice.BOND_BONDING
                ) {
                    // EXTRA_REASON is hidden; 6 is UNBOND_REASON_AUTH_TIMEOUT. The Security
                    // Manager's 30 s also count as running out.
                    val reason = intent.getIntExtra(EXTRA_REASON, 0)
                    val took = System.currentTimeMillis() - bondingSince
                    lastError = if (reason == UNBOND_REASON_AUTH_TIMEOUT || took >= SMP_TIMEOUT_MS) {
                        "pair_timeout"
                    } else {
                        "pair_failed"
                    }
                }
            }
        }
        val filter = IntentFilter(BluetoothDevice.ACTION_BOND_STATE_CHANGED)
        // A system broadcast: it reaches a receiver that is not exported.
        if (Build.VERSION.SDK_INT >= 33) {
            activity.registerReceiver(r, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            activity.registerReceiver(r, filter)
        }
        bondWatch = r
    }

    private fun unwatchBond() {
        bondWatch?.let {
            try {
                activity.unregisterReceiver(it)
            } catch (e: IllegalArgumentException) {
                // Not registered.
            }
        }
        bondWatch = null
    }

    /** Removes Android's bond with the pod at [address]; false when Android refuses. */
    private fun forget(address: String): Boolean {
        val device = try {
            manager?.adapter?.getRemoteDevice(address)
        } catch (e: IllegalArgumentException) {
            null
        } ?: return false
        if (device.bondState == BluetoothDevice.BOND_NONE) return true
        return try {
            device.javaClass.getMethod("removeBond").invoke(device) as? Boolean ?: false
        } catch (e: ReflectiveOperationException) {
            false
        } catch (e: SecurityException) {
            false
        }
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
                // The pod's own reason (the HCI code): 0x05, it does not trust this bond.
                if (status == HCI_AUTH_FAILURE && lastError == null) lastError = "repair"
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
        unwatchBond()
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

        /** HCI Authentication Failure: the pod's reason for dropping a bond it does not trust. */
        const val HCI_AUTH_FAILURE = 0x05

        /** BluetoothDevice's hidden EXTRA_REASON and UNBOND_REASON_AUTH_TIMEOUT. */
        const val EXTRA_REASON = "android.bluetooth.device.extra.REASON"
        const val UNBOND_REASON_AUTH_TIMEOUT = 6

        /** The Security Manager's timeout (Bluetooth Core, Vol 3 Part H 3.4), less a margin. */
        const val SMP_TIMEOUT_MS = 29000L
    }
}
