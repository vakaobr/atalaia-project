// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.app.Activity
import android.os.Build
import android.os.CancellationSignal
import androidx.credentials.CreatePublicKeyCredentialRequest
import androidx.credentials.CreatePublicKeyCredentialResponse
import androidx.credentials.CredentialManager
import androidx.credentials.CredentialManagerCallback
import androidx.credentials.CreateCredentialResponse
import androidx.credentials.GetCredentialRequest
import androidx.credentials.GetCredentialResponse
import androidx.credentials.GetPublicKeyCredentialOption
import androidx.credentials.PublicKeyCredential
import androidx.credentials.exceptions.CreateCredentialCancellationException
import androidx.credentials.exceptions.CreateCredentialException
import androidx.credentials.exceptions.CreateCredentialProviderConfigurationException
import androidx.credentials.exceptions.CreateCredentialUnsupportedException
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.GetCredentialException
import androidx.credentials.exceptions.GetCredentialProviderConfigurationException
import androidx.credentials.exceptions.GetCredentialUnsupportedException
import androidx.credentials.exceptions.NoCredentialException
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * Passkeys through Android's Credential Manager (decision PKA-1,
 * lib/site/site_auth.dart). The site server's WebAuthn options go in as JSON
 * and the credential comes back as JSON for the server to verify; the app
 * keeps nothing. The relying party is the site's host name, which the site's
 * `/.well-known/assetlinks.json` (get_login_creds) ties to this app, so a
 * passkey made in the browser works here and the other way round. From
 * Android 14 the system's own credential providers serve it; before that it
 * needs Google Play services, which the app does not ask for (decision PD5),
 * so there "available" is false and the account screen says so.
 */
class PasskeyPlugin(private val activity: Activity, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler {
    private val executor = activity.mainExecutor

    init {
        MethodChannel(messenger, "org.atalaia.app/passkeys").setMethodCallHandler(this)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "available" -> result.success(Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
            "create" -> create(call.argument<String>("request"), result)
            "get" -> get(call.argument<String>("request"), result)
            else -> result.notImplemented()
        }
    }

    private fun create(request: String?, result: MethodChannel.Result) {
        if (request == null || Build.VERSION.SDK_INT < Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            result.error("unsupported", "no passkeys here", null)
            return
        }
        val manager = CredentialManager.create(activity)
        manager.createCredentialAsync(
            activity,
            CreatePublicKeyCredentialRequest(request),
            CancellationSignal(),
            executor,
            object : CredentialManagerCallback<CreateCredentialResponse, CreateCredentialException> {
                override fun onResult(response: CreateCredentialResponse) {
                    val json = (response as? CreatePublicKeyCredentialResponse)?.registrationResponseJson
                    if (json != null) result.success(json) else result.error("failed", "no passkey", null)
                }

                override fun onError(e: CreateCredentialException) {
                    result.error(
                        when (e) {
                            is CreateCredentialCancellationException -> "cancelled"
                            is CreateCredentialProviderConfigurationException,
                            is CreateCredentialUnsupportedException -> "unsupported"
                            else -> "failed"
                        },
                        e.type,
                        null,
                    )
                }
            },
        )
    }

    private fun get(request: String?, result: MethodChannel.Result) {
        if (request == null || Build.VERSION.SDK_INT < Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            result.error("unsupported", "no passkeys here", null)
            return
        }
        val manager = CredentialManager.create(activity)
        val credentialRequest = GetCredentialRequest.Builder()
            .addCredentialOption(GetPublicKeyCredentialOption(request))
            .build()
        manager.getCredentialAsync(
            activity,
            credentialRequest,
            CancellationSignal(),
            executor,
            object : CredentialManagerCallback<GetCredentialResponse, GetCredentialException> {
                override fun onResult(response: GetCredentialResponse) {
                    val json = (response.credential as? PublicKeyCredential)?.authenticationResponseJson
                    if (json != null) result.success(json) else result.error("failed", "no passkey", null)
                }

                override fun onError(e: GetCredentialException) {
                    result.error(
                        when (e) {
                            is GetCredentialCancellationException -> "cancelled"
                            is NoCredentialException -> "no_credential"
                            is GetCredentialProviderConfigurationException,
                            is GetCredentialUnsupportedException -> "unsupported"
                            else -> "failed"
                        },
                        e.type,
                        null,
                    )
                }
            },
        )
    }
}
