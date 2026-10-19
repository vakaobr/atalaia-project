// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package org.atalaia.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.util.TypedValue
import android.view.Gravity
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.ReaderException
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * A full-screen camera that reads one QR code. The picture comes from
 * CameraX (AndroidX, open source), the decoding from ZXing's core library
 * (Apache-2.0, pure Java): neither needs Google Play services, unlike ML
 * Kit (decision PD5). The texts come from the app's language.
 */
class QrScanActivity : ComponentActivity() {
    private lateinit var preview: PreviewView
    private val analysis: ExecutorService = Executors.newSingleThreadExecutor()
    private val done = AtomicBoolean(false)
    private val askCamera =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) startCamera() else finishWith(null)
        }
    private val reader = QRCodeReader()
    private val hints = mapOf(
        DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE),
        DecodeHintType.TRY_HARDER to true,
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        preview = PreviewView(this)
        val hint = TextView(this).apply {
            text = intent.getStringExtra(EXTRA_HINT) ?: ""
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 20f)
            gravity = Gravity.CENTER
            setBackgroundColor(0xB0101418.toInt())
            setPadding(32, 24, 32, 24)
        }
        val cancel = Button(this).apply {
            text = intent.getStringExtra(EXTRA_CANCEL)?.ifEmpty { null } ?: "×"
            setOnClickListener { finishWith(null) }
        }
        val bottom = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(hint)
            addView(cancel)
        }
        setContentView(
            FrameLayout(this).apply {
                setBackgroundColor(Color.BLACK)
                addView(preview)
                addView(
                    bottom,
                    FrameLayout.LayoutParams(
                        FrameLayout.LayoutParams.MATCH_PARENT,
                        FrameLayout.LayoutParams.WRAP_CONTENT,
                        Gravity.BOTTOM,
                    ),
                )
            },
        )
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            startCamera()
        } else {
            askCamera.launch(Manifest.permission.CAMERA)
        }
    }

    private fun startCamera() {
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener(
            {
                val provider = future.get()
                val picture = Preview.Builder().build().also {
                    it.setSurfaceProvider(preview.surfaceProvider)
                }
                val frames = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                    .also { it.setAnalyzer(analysis, ::decode) }
                provider.unbindAll()
                provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, picture, frames)
            },
            mainExecutor,
        )
    }

    /** The luminance plane through ZXing's QR reader. */
    private fun decode(image: ImageProxy) {
        try {
            if (done.get()) return
            val plane = image.planes[0]
            val buffer = plane.buffer
            // The last row may come without its padding: room for whole rows.
            val size = buffer.remaining()
            val bytes = ByteArray(maxOf(size, plane.rowStride * image.height))
            buffer.get(bytes, 0, size)
            val source = PlanarYUVLuminanceSource(
                bytes,
                plane.rowStride,
                image.height,
                0,
                0,
                image.width,
                image.height,
                false,
            )
            val text = reader.decode(BinaryBitmap(HybridBinarizer(source)), hints).text
            if (done.compareAndSet(false, true)) runOnUiThread { finishWith(text) }
        } catch (e: ReaderException) {
            // No code in this frame.
        } catch (e: IllegalArgumentException) {
            // A frame of an unexpected size.
        } finally {
            reader.reset()
            image.close()
        }
    }

    private fun finishWith(text: String?) {
        if (text == null) {
            setResult(RESULT_CANCELED)
        } else {
            setResult(RESULT_OK, Intent().putExtra(EXTRA_TEXT, text))
        }
        finish()
    }

    override fun onDestroy() {
        analysis.shutdown()
        super.onDestroy()
    }

    companion object {
        const val EXTRA_HINT = "hint"
        const val EXTRA_CANCEL = "cancel"
        const val EXTRA_TEXT = "text"
    }
}
