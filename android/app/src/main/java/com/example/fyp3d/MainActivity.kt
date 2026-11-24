cat > ~/FYP/MiDaS/mobile/android/app/src/main/java/com/fyp/reconstruction/MainActivity.kt <<'EOF'
package com.fyp.reconstruction

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.FrameLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {

    private var previewView: PreviewView? = null
    private var webSocket: WebSocket? = null

    private val httpClient = OkHttpClient()
    private val cameraExecutor = Executors.newSingleThreadExecutor()

    @Volatile
    private var scanning = false

    private val serverUrl =
        "ws://192.168.2.107:8000/ws/video"

    private val cameraPermission =
        registerForActivityResult(
            ActivityResultContracts.RequestPermission()
        ) { granted ->
            if (granted) {
                startCamera()
            } else {
                Toast.makeText(
                    this,
                    "Camera permission required",
                    Toast.LENGTH_LONG
                ).show()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val root = FrameLayout(this)

        previewView = PreviewView(this)

        root.addView(
            previewView,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        )

        val statusText = TextView(this)
        statusText.text = "Ready to scan"
        statusText.textSize = 20f
        statusText.setTextColor(0xFFFFFFFF.toInt())
        statusText.gravity = Gravity.CENTER

        val statusParams = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT,
            FrameLayout.LayoutParams.WRAP_CONTENT
        )

        statusParams.gravity =
            Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
        statusParams.bottomMargin = 140

        root.addView(statusText, statusParams)

        val scanButton = Button(this)
        scanButton.text = "START 3D SCAN"

        val buttonParams = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT,
            FrameLayout.LayoutParams.WRAP_CONTENT
        )

        buttonParams.gravity =
            Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
        buttonParams.bottomMargin = 50

        root.addView(scanButton, buttonParams)

        scanButton.setOnClickListener {

            scanning = !scanning

            if (scanning) {

                scanButton.text = "STOP SCAN"
                statusText.text = "Scanning..."

                connectWebSocket()

                Toast.makeText(
                    this,
                    "3D Scan Started",
                    Toast.LENGTH_SHORT
                ).show()

            } else {

                scanButton.text = "START 3D SCAN"
                statusText.text = "Ready to scan"

                webSocket?.close(
                    1000,
                    "Scan stopped"
                )

                webSocket = null
            }
        }

        setContentView(root)

        if (
            ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.CAMERA
            ) == PackageManager.PERMISSION_GRANTED
        ) {
            startCamera()
        } else {
            cameraPermission.launch(
                Manifest.permission.CAMERA
            )
        }
    }

    private fun connectWebSocket() {

        if (webSocket != null) return

        val request = Request.Builder()
            .url(serverUrl)
            .build()

        webSocket = httpClient.newWebSocket(
            request,
            object : WebSocketListener() {

                override fun onOpen(
                    webSocket: WebSocket,
                    response: okhttp3.Response
                ) {
                    runOnUiThread {
                        Toast.makeText(
                            this@MainActivity,
                            "Backend Connected",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                }

                override fun onMessage(
                    webSocket: WebSocket,
                    text: String
                ) {
                    println("BACKEND: $text")
                }

                override fun onFailure(
                    webSocket: WebSocket,
                    t: Throwable,
                    response: okhttp3.Response?
                ) {
                    println(
                        "WebSocket ERROR: ${t.message}"
                    )
                    this@MainActivity.webSocket = null
                }

                override fun onClosed(
                    webSocket: WebSocket,
                    code: Int,
                    reason: String
                ) {
                    println(
                        "WebSocket CLOSED: $reason"
                    )
                    this@MainActivity.webSocket = null
                }
            }
        )
    }

    private fun startCamera() {

        val view = previewView ?: return

        val future =
            ProcessCameraProvider.getInstance(this)

        future.addListener(
            Runnable {

                try {

                    val provider = future.get()

                    val preview =
                        Preview.Builder().build()

                    preview.setSurfaceProvider(
                        view.surfaceProvider
                    )

                    val analysis =
                        ImageAnalysis.Builder()
                            .setBackpressureStrategy(
                                ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST
                            )
                            .build()

                    analysis.setAnalyzer(
                        cameraExecutor,
                        object : ImageAnalysis.Analyzer {

                            override fun analyze(
                                imageProxy: ImageProxy
                            ) {
                                if (scanning) {
                                    sendFrame(imageProxy)
                                } else {
                                    imageProxy.close()
                                }
                            }
                        }
                    )

                    provider.unbindAll()

                    provider.bindToLifecycle(
                        this,
                        CameraSelector.DEFAULT_BACK_CAMERA,
                        preview,
                        analysis
                    )

                } catch (e: Exception) {

                    e.printStackTrace()

                    Toast.makeText(
                        this,
                        "Camera ERROR: ${e.message}",
                        Toast.LENGTH_LONG
                    ).show()
                }

            },
            ContextCompat.getMainExecutor(this)
        )
    }

    private fun sendFrame(
        imageProxy: ImageProxy
    ) {

        try {

            val socket = webSocket

            if (socket == null) {
                imageProxy.close()
                return
            }

            val jpeg = imageProxyToJpeg(imageProxy)

            if (jpeg != null) {
                socket.send(
                    ByteString.of(*jpeg)
                )
            }

        } catch (e: Exception) {
            e.printStackTrace()
        } finally {
            imageProxy.close()
        }
    }

    private fun imageProxyToJpeg(
        image: ImageProxy
    ): ByteArray? {

        if (
            image.format !=
            ImageFormat.YUV_420_888
        ) {
            return null
        }

        val yBuffer =
            image.planes[0].buffer
        val uBuffer =
            image.planes[1].buffer
        val vBuffer =
            image.planes[2].buffer

        val ySize = yBuffer.remaining()
        val uSize = uBuffer.remaining()
        val vSize = vBuffer.remaining()

        val nv21 =
            ByteArray(ySize + uSize + vSize)

        yBuffer.get(
            nv21,
            0,
            ySize
        )

        val uBytes = ByteArray(uSize)
        uBuffer.get(uBytes)

        val vBytes = ByteArray(vSize)
        vBuffer.get(vBytes)

        var position = ySize
        var i = 0

        while (i < vSize) {

            nv21[position++] = vBytes[i]

            if (i < uSize) {
                nv21[position++] = uBytes[i]
            }

            i++
        }

        val yuv =
            YuvImage(
                nv21,
                ImageFormat.NV21,
                image.width,
                image.height,
                null
            )

        val output =
            ByteArrayOutputStream()

        yuv.compressToJpeg(
            Rect(
                0,
                0,
                image.width,
                image.height
            ),
            60,
            output
        )

        return output.toByteArray()
    }

    override fun onDestroy() {

        scanning = false

        webSocket?.close(
            1000,
            "Activity destroyed"
        )

        webSocket = null

        cameraExecutor.shutdown()

        super.onDestroy()
    }
}
EOF