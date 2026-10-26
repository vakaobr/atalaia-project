// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.os.Handler
import android.os.Looper
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyPermanentlyInvalidatedException
import android.security.keystore.KeyProperties
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.security.GeneralSecurityException
import java.security.KeyStore
import java.security.UnrecoverableKeyException
import java.util.concurrent.Executors
import javax.crypto.AEADBadTagException
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Seals the app's few secrets at rest (lib/storage/secret_vault.dart, decision
 * PD6): the field join key, the marshal's seed and the read code. One AES-256
 * key lives in the AndroidKeyStore under [ALIAS]: it cannot be exported, and
 * it asks for no user authentication and no unlocked screen, so the
 * foreground service and a start after a reboot can still read the secrets.
 *
 * Methods: `available` (can a key be had and used), `seal` (bytes in, the
 * 12-byte nonce then the ciphertext and tag out), `open` (the reverse).
 * Errors: `key_lost` (no key, or the data does not fit it: the data can never
 * be read, which the app treats as "missing, join again") and `unavailable`
 * (the Keystore failed now). `open` never makes a key: a lost key stays lost
 * and is not silently replaced by one that cannot read the old data; only
 * `seal` makes one. Work runs on its own thread, off the UI thread.
 */
class KeystorePlugin(messenger: BinaryMessenger) : MethodChannel.MethodCallHandler {
    private val channel = MethodChannel(messenger, "org.atalaia.app/keystore")
    private val main = Handler(Looper.getMainLooper())
    private val worker = WORKER

    init {
        channel.setMethodCallHandler(this)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        val data = call.argument<ByteArray>("data")
        worker.execute {
            try {
                val out: Any? = when (call.method) {
                    "available" -> available()
                    "seal" -> seal(data ?: throw IllegalArgumentException("no data"))
                    "open" -> open(data ?: throw IllegalArgumentException("no data"))
                    else -> {
                        main.post { result.notImplemented() }
                        return@execute
                    }
                }
                main.post { result.success(out) }
            } catch (e: KeyLostException) {
                main.post { result.error("key_lost", e.message, null) }
            } catch (e: Exception) {
                main.post { result.error("unavailable", e.javaClass.simpleName, null) }
            }
        }
    }

    private class KeyLostException(message: String) : Exception(message)

    private fun store(): KeyStore = KeyStore.getInstance(PROVIDER).apply { load(null) }

    private fun existingKey(): SecretKey? =
        try {
            store().getKey(ALIAS, null) as? SecretKey
        } catch (e: UnrecoverableKeyException) {
            throw KeyLostException("unrecoverable")
        } catch (e: KeyPermanentlyInvalidatedException) {
            throw KeyLostException("invalidated")
        }

    private fun makeKey(): SecretKey {
        val spec = KeyGenParameterSpec.Builder(
            ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .setRandomizedEncryptionRequired(true)
            .build()
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, PROVIDER)
        generator.init(spec)
        return generator.generateKey()
    }

    private fun available(): Boolean {
        // A real round trip: a Keystore that lists keys but cannot use them is
        // not available.
        val key = existingKey() ?: makeKey()
        val probe = byteArrayOf(1, 2, 3)
        return try {
            open(seal(probe, key), key).contentEquals(probe)
        } catch (e: GeneralSecurityException) {
            false
        }
    }

    private fun seal(plain: ByteArray, key: SecretKey = existingKey() ?: makeKey()): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(Cipher.ENCRYPT_MODE, key)
        cipher.updateAAD(AAD)
        return cipher.iv + cipher.doFinal(plain)
    }

    private fun open(sealed: ByteArray, key: SecretKey? = null): ByteArray {
        if (sealed.size < NONCE_BYTES + TAG_BYTES) throw KeyLostException("short")
        val k = key ?: existingKey() ?: throw KeyLostException("no key")
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(
            Cipher.DECRYPT_MODE,
            k,
            GCMParameterSpec(TAG_BYTES * 8, sealed, 0, NONCE_BYTES),
        )
        cipher.updateAAD(AAD)
        try {
            return cipher.doFinal(sealed, NONCE_BYTES, sealed.size - NONCE_BYTES)
        } catch (e: AEADBadTagException) {
            // The key is there but is not the one that sealed this (data
            // restored from another phone), or the file was changed.
            throw KeyLostException("bad tag")
        }
    }

    companion object {
        /** One thread for the process, so an activity's second life adds none. */
        private val WORKER = Executors.newSingleThreadExecutor()
        private const val PROVIDER = "AndroidKeyStore"
        private const val ALIAS = "org.atalaia.app.secrets.v1"
        private const val TRANSFORM = "AES/GCM/NoPadding"
        private const val NONCE_BYTES = 12
        private const val TAG_BYTES = 16
        private val AAD = "atalaia-secrets-v1".toByteArray(Charsets.UTF_8)
    }
}
