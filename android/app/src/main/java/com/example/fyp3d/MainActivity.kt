package com.example.fyp3d

import android.Manifest
import android.content.Context
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.ImageFormat
import android.graphics.Matrix
import android.graphics.Rect
import android.graphics.YuvImage
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.util.Log
import android.view.Gravity
import android.view.OrientationEventListener
import android.view.Surface
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
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
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/**
 * Phase 4A — minimum viable camera-to-backend uplink.
 *
 * HISTORY OF THIS FILE
 * --------------------
 * The version recovered in commit 1ff73cb could not compile: the whole file
 * was wrapped in a shell heredoc (`cat > ... <<'EOF'` on line 1, `EOF` on
 * line 401) that had been pasted into the editor instead of being run in a
 * terminal, and it declared `package com.fyp.reconstruction` while living in
 * `com/example/fyp3d/`. The forensic timeline in
 * docs/PHASE4_ANDROID_RECOVERY.md shows it was written four days AFTER the
 * module build script was emptied, so it had never been compiled even once.
 *
 * The original implementation's structure and approach are PRESERVED here --
 * View-based UI (FrameLayout + PreviewView + status text + one button),
 * CameraX ImageAnalysis, OkHttp WebSocket, NV21 -> JPEG. What changed is
 * listed in the report; the substantive fixes are the stride-correct YUV
 * conversion, the configurable backend address, the frame-rate limit and the
 * reconnect logic.
 *
 * WIRE PROTOCOL -- read from backend/api/main.py, NOT invented, NOT modified:
 *   - endpoint  WS /ws/video on port 8000
 *   - uplink    ONE BINARY MESSAGE PER FRAME, raw JPEG bytes only.
 *               No JSON envelope. No sequence header. No timestamp.
 *   - downlink  one JSON text message per frame, acknowledging receipt
 *
 * The backend has no field for a sequence number or a capture timestamp --
 * `frame_count` there is a server-side counter incremented on arrival. Adding
 * either would be a coordinated both-side protocol change and is deliberately
 * out of scope (see docs/PHASE4_ANDROID_RECOVERY.md section 7).
 *
 * The ack means RECEIVED, not DEPTH READY: MiDaS runs on a separate backend
 * thread and is latest-frame-wins, so depth appears at the model's own rate
 * (~5.3 fps on the project's Quadro T2000) regardless of uplink rate. That is
 * why the uplink is rate-limited rather than run flat out.
 */
class MainActivity : ComponentActivity() {

    private companion object {
        const val TAG = "FYP3D"

        const val PREFS = "fyp3d_backend"
        const val KEY_HOST = "host"
        const val KEY_PORT = "port"
        const val KEY_FPS = "fps"

        /** Backend default from run_backend.sh (`--port 8000`). */
        const val DEFAULT_PORT = 8000

        /**
         * Default uplink limit. Matched to the measured backend inference rate
         * (~5.3 fps, DPT-Hybrid-384 on a Quadro T2000). Sending faster only
         * wastes phone battery and Wi-Fi: the backend overwrites
         * `pending_frame`, so surplus frames are dropped server-side anyway.
         */
        const val DEFAULT_FPS = 5.0

        const val JPEG_QUALITY = 70

        /**
         * Drop frames rather than queue them when the socket is backed up.
         * OkHttp's send() buffers without bound, so on a slow link an
         * unthrottled producer grows the queue until the process dies. Two
         * frames of slack absorbs jitter; beyond that the newest frame is
         * dropped, which is the same latest-frame-wins policy the backend
         * itself uses.
         */
        const val MAX_QUEUED_BYTES = 2L * 1024 * 1024

        val IPV4 = Regex(
            "^((25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)\\.){3}" +
                "(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)$"
        )
    }

    private var previewView: PreviewView? = null
    private lateinit var hostInput: EditText
    private lateinit var portInput: EditText
    private lateinit var fpsInput: EditText
    private lateinit var statusText: TextView
    private lateinit var countsText: TextView
    private lateinit var scanButton: Button

    private lateinit var prefs: SharedPreferences

    private val httpClient = OkHttpClient.Builder()
        // A silently half-open Wi-Fi socket is the common failure on a phone
        // that walks out of range; pings surface it as onFailure so the
        // reconnect path can run instead of the stream just stopping.
        .pingInterval(5, TimeUnit.SECONDS)
        .build()

    private val cameraExecutor = Executors.newSingleThreadExecutor()
    private val ui = Handler(Looper.getMainLooper())

    @Volatile
    private var webSocket: WebSocket? = null

    @Volatile
    private var scanning = false

    /** Guards against two in-flight connect attempts after a fast retry. */
    @Volatile
    private var connecting = false

    private val framesSent = AtomicInteger(0)
    private val acksReceived = AtomicInteger(0)
    private val framesDropped = AtomicInteger(0)
    private val lastSentAtMs = AtomicLong(0L)

    @Volatile
    private var minIntervalMs = (1000.0 / DEFAULT_FPS).toLong()

    private var reconnectAttempt = 0
    private var reconnectPending = false

    // ---- Milestone 4 diagnostics (measurement only; no behaviour change) ---
    private var imageAnalysis: ImageAnalysis? = null
    private var orientationListener: OrientationEventListener? = null

    /** Last physical-orientation bucket reported by the sensor, in degrees. */
    @Volatile
    private var lastOrientationBucket = -1

    /** Signature of the last diagnostic line, so we log on CHANGE only. */
    @Volatile
    private var lastRotationSignature = ""

    private val cameraPermission =
        registerForActivityResult(
            ActivityResultContracts.RequestPermission()
        ) { granted ->
            if (granted) {
                startCamera()
            } else {
                setStatus("Camera permission denied", Color.RED)
                Toast.makeText(
                    this,
                    "Camera permission required",
                    Toast.LENGTH_LONG
                ).show()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE)

        setContentView(buildUi())
        restoreSettings()

        if (
            ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.CAMERA
            ) == PackageManager.PERMISSION_GRANTED
        ) {
            startCamera()
        } else {
            cameraPermission.launch(Manifest.permission.CAMERA)
        }
    }

    // ------------------------------------------------------------------ UI

    private fun buildUi(): FrameLayout {
        val root = FrameLayout(this)

        previewView = PreviewView(this)
        root.addView(
            previewView,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        )

        // ---- backend address panel (top) --------------------------------
        val panel = LinearLayout(this)
        panel.orientation = LinearLayout.VERTICAL
        panel.setBackgroundColor(0xB0000000.toInt())
        panel.setPadding(24, 24, 24, 24)

        hostInput = EditText(this)
        hostInput.hint = "Backend IPv4 (e.g. 192.168.1.50)"
        hostInput.inputType = InputType.TYPE_CLASS_TEXT
        hostInput.setSingleLine()
        hostInput.setHintTextColor(0xFF999999.toInt())
        hostInput.setTextColor(Color.WHITE)
        panel.addView(hostInput, wide())

        portInput = EditText(this)
        portInput.hint = "Port (default $DEFAULT_PORT)"
        portInput.inputType = InputType.TYPE_CLASS_NUMBER
        portInput.setSingleLine()
        portInput.setHintTextColor(0xFF999999.toInt())
        portInput.setTextColor(Color.WHITE)
        panel.addView(portInput, wide())

        fpsInput = EditText(this)
        fpsInput.hint = "Uplink fps (default $DEFAULT_FPS)"
        fpsInput.inputType =
            InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
        fpsInput.setSingleLine()
        fpsInput.setHintTextColor(0xFF999999.toInt())
        fpsInput.setTextColor(Color.WHITE)
        panel.addView(fpsInput, wide())

        val panelParams = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.WRAP_CONTENT
        )
        panelParams.gravity = Gravity.TOP
        root.addView(panel, panelParams)

        // ---- status + counters + button (bottom) -------------------------
        val bottom = LinearLayout(this)
        bottom.orientation = LinearLayout.VERTICAL
        bottom.gravity = Gravity.CENTER_HORIZONTAL
        bottom.setBackgroundColor(0xB0000000.toInt())
        bottom.setPadding(24, 16, 24, 32)

        statusText = TextView(this)
        statusText.textSize = 16f
        statusText.gravity = Gravity.CENTER
        statusText.setTextColor(Color.WHITE)
        statusText.text = "Idle — enter the backend IP, then START"
        bottom.addView(statusText, wide())

        countsText = TextView(this)
        countsText.textSize = 14f
        countsText.gravity = Gravity.CENTER
        countsText.setTextColor(0xFFCCCCCC.toInt())
        countsText.text = "sent 0 · acked 0 · dropped 0"
        bottom.addView(countsText, wide())

        scanButton = Button(this)
        scanButton.text = "START STREAMING"
        scanButton.setOnClickListener { onScanButton() }
        bottom.addView(scanButton, wide())

        val bottomParams = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.WRAP_CONTENT
        )
        bottomParams.gravity = Gravity.BOTTOM
        root.addView(bottom, bottomParams)

        return root
    }

    private fun wide() = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT
    )

    private fun setStatus(msg: String, colour: Int = Color.WHITE) {
        ui.post {
            statusText.text = msg
            statusText.setTextColor(colour)
        }
    }

    private fun refreshCounts() {
        ui.post {
            countsText.text = "sent ${framesSent.get()} · " +
                "acked ${acksReceived.get()} · " +
                "dropped ${framesDropped.get()}"
        }
    }

    // ------------------------------------------------- settings persistence

    private fun restoreSettings() {
        // Defaults to EMPTY, never to a developer's own LAN address: the
        // recovered source hard-coded ws://192.168.2.107:8000/ws/video, an
        // address on a different /24 from the current laptop and therefore
        // permanently unreachable. A wrong default is worse than none.
        hostInput.setText(prefs.getString(KEY_HOST, "") ?: "")
        portInput.setText(prefs.getInt(KEY_PORT, DEFAULT_PORT).toString())
        fpsInput.setText(prefs.getFloat(KEY_FPS, DEFAULT_FPS.toFloat()).toString())
    }

    private fun saveSettings(host: String, port: Int, fps: Double) {
        prefs.edit()
            .putString(KEY_HOST, host)
            .putInt(KEY_PORT, port)
            .putFloat(KEY_FPS, fps.toFloat())
            .apply()
    }

    // --------------------------------------------------------- stream control

    private fun onScanButton() {
        if (scanning) {
            stopStreaming("Stopped by user")
            return
        }

        val host = hostInput.text.toString().trim()
        if (!IPV4.matches(host)) {
            setStatus("Invalid IPv4 address: \"$host\"", Color.RED)
            return
        }

        val port = portInput.text.toString().trim().toIntOrNull()
        if (port == null || port !in 1..65535) {
            setStatus("Invalid port (expected 1-65535)", Color.RED)
            return
        }

        val fps = fpsInput.text.toString().trim().toDoubleOrNull()
        if (fps == null || fps <= 0.0 || fps > 30.0) {
            setStatus("Invalid fps (expected 0 < fps <= 30)", Color.RED)
            return
        }

        minIntervalMs = (1000.0 / fps).toLong()
        saveSettings(host, port, fps)

        framesSent.set(0)
        acksReceived.set(0)
        framesDropped.set(0)
        lastSentAtMs.set(0L)
        reconnectAttempt = 0
        refreshCounts()

        scanning = true
        scanButton.text = "STOP STREAMING"
        connect(host, port)
    }

    private fun endpointFor(host: String, port: Int) = "ws://$host:$port/ws/video"

    private fun connect(host: String, port: Int) {
        if (connecting || webSocket != null) return
        connecting = true

        val url = endpointFor(host, port)
        setStatus("Connecting to $url …")
        Log.i(TAG, "connecting: $url")

        val request = Request.Builder().url(url).build()

        httpClient.newWebSocket(request, object : WebSocketListener() {

            override fun onOpen(webSocket: WebSocket, response: Response) {
                this@MainActivity.webSocket = webSocket
                connecting = false
                reconnectAttempt = 0
                Log.i(TAG, "connected: $url")
                setStatus("Connected to $host:$port — streaming", Color.GREEN)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                // The backend sends one JSON ack per received frame. It is
                // counted, not parsed: it carries no field this client needs,
                // and "depth_available" refers to the backend's latest depth
                // map, not to this frame.
                acksReceived.incrementAndGet()
                refreshCounts()
            }

            override fun onFailure(
                webSocket: WebSocket,
                t: Throwable,
                response: Response?
            ) {
                this@MainActivity.webSocket = null
                connecting = false
                val why = t.message ?: t.javaClass.simpleName
                Log.w(TAG, "websocket failure: $why", t)
                // Surface the real reason. "ECONNREFUSED" (backend down),
                // "ETIMEDOUT" (wrong subnet / AP isolation) and
                // "CLEARTEXT communication not permitted" are three very
                // different problems and the user cannot tell them apart from
                // a generic message.
                setStatus("Disconnected: $why", Color.RED)
                scheduleReconnect(host, port)
            }

            override fun onClosed(
                webSocket: WebSocket,
                code: Int,
                reason: String
            ) {
                this@MainActivity.webSocket = null
                connecting = false
                Log.i(TAG, "closed: $code $reason")
                if (scanning) {
                    // The backend closes with 1008 when FYP_VIDEO_STREAM_LOCK=1
                    // is set, which otherwise looks like an unexplained drop.
                    setStatus("Closed by server: $code $reason", Color.YELLOW)
                    scheduleReconnect(host, port)
                }
            }
        })
    }

    private fun scheduleReconnect(host: String, port: Int) {
        if (!scanning || reconnectPending) return
        reconnectPending = true
        reconnectAttempt++
        // 1s, 2s, 4s, 8s, capped at 10s. Bounded so a backend that comes back
        // is picked up promptly, without hammering a host that is simply absent.
        val delayMs = minOf(10_000L, 1000L shl minOf(reconnectAttempt - 1, 3))
        setStatus("Reconnecting in ${delayMs / 1000}s (attempt $reconnectAttempt)…", Color.YELLOW)
        ui.postDelayed({
            reconnectPending = false
            if (scanning) connect(host, port)
        }, delayMs)
    }

    private fun stopStreaming(reason: String) {
        scanning = false
        reconnectPending = false
        // Graceful close: code 1000 is a normal closure, which lets the
        // backend log "PHONE DISCONNECTED" instead of a dropped socket.
        webSocket?.close(1000, reason)
        webSocket = null
        ui.post { scanButton.text = "START STREAMING" }
        setStatus("Idle — $reason")
    }

    // ----------------------------------------------------------------- camera

    private fun startCamera() {
        val view = previewView ?: return
        val future = ProcessCameraProvider.getInstance(this)

        future.addListener({
            try {
                val provider = future.get()

                val preview = Preview.Builder().build()
                preview.setSurfaceProvider(view.surfaceProvider)

                // KEEP_ONLY_LATEST: the analyzer receives the newest frame and
                // older ones are discarded by CameraX rather than queued. With
                // a ~5 fps uplink against a 30 fps camera this is what keeps
                // latency flat instead of accumulating a backlog.
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()

                imageAnalysis = analysis

                analysis.setAnalyzer(cameraExecutor) { imageProxy ->
                    handleFrame(imageProxy)
                }

                provider.unbindAll()
                provider.bindToLifecycle(
                    this,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    analysis
                )
                Log.i(TAG, "camera bound")
                startOrientationListener()
            } catch (e: Exception) {
                Log.e(TAG, "camera bind failed", e)
                setStatus("Camera error: ${e.message}", Color.RED)
            }
        }, ContextCompat.getMainExecutor(this))
    }

    /**
     * Called on [cameraExecutor] for every analyzer frame.
     *
     * Every path through this method closes the ImageProxy exactly once. A
     * leaked proxy stalls the whole analyzer after a handful of frames,
     * because CameraX will not deliver another until one is released.
     */
    private fun handleFrame(imageProxy: ImageProxy) {
        try {
            if (!scanning) return

            val socket = webSocket ?: return

            // ---- rate limit -------------------------------------------
            val now = System.currentTimeMillis()
            if (now - lastSentAtMs.get() < minIntervalMs) return

            // ---- backpressure: drop rather than queue ------------------
            if (socket.queueSize() > MAX_QUEUED_BYTES) {
                framesDropped.incrementAndGet()
                refreshCounts()
                return
            }

            val jpeg = imageProxyToJpeg(imageProxy) ?: return

            if (socket.send(ByteString.of(*jpeg))) {
                lastSentAtMs.set(now)
                framesSent.incrementAndGet()
            } else {
                // send() returns false once the socket is closing/closed.
                framesDropped.incrementAndGet()
            }
            refreshCounts()
        } catch (e: Exception) {
            Log.e(TAG, "frame handling failed", e)
        } finally {
            imageProxy.close()
        }
    }

    // ------------------------------------------------- orientation diagnostics

    /**
     * MILESTONE 4, STEP 1 -- MEASUREMENT ONLY. This block changes no
     * behaviour; it exists to test the Milestone 3 hypothesis that
     * `imageInfo.rotationDegrees` tracks the DISPLAY rotation rather than the
     * physical device orientation. It is wired up, measured, and only then is
     * a fix written -- the hypothesis is not assumed.
     */
    private fun currentDisplayRotation(): Int = try {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            display?.rotation ?: Surface.ROTATION_0
        } else {
            @Suppress("DEPRECATION")
            windowManager.defaultDisplay.rotation
        }
    } catch (e: Exception) {
        Log.w(TAG, "display rotation unavailable", e)
        Surface.ROTATION_0
    }

    private fun surfaceRotationName(r: Int) = when (r) {
        Surface.ROTATION_0 -> "ROTATION_0(0deg)"
        Surface.ROTATION_90 -> "ROTATION_90(90deg)"
        Surface.ROTATION_180 -> "ROTATION_180(180deg)"
        Surface.ROTATION_270 -> "ROTATION_270(270deg)"
        else -> "ROTATION_?($r)"
    }

    /**
     * Snap a continuous sensor azimuth to the four Surface rotations.
     *
     * NOTE the inversion: when the device is rotated clockwise, the IMAGE must
     * be rotated counter-clockwise to stay upright, so 90 degrees of device
     * rotation maps to Surface.ROTATION_270. Getting this backwards is the
     * classic way to turn a 90-degree error into a 270-degree one, which is
     * why it is written out explicitly rather than inlined.
     */
    private fun surfaceRotationFor(orientationDegrees: Int): Int = when {
        orientationDegrees >= 315 || orientationDegrees < 45 -> Surface.ROTATION_0
        orientationDegrees < 135 -> Surface.ROTATION_270
        orientationDegrees < 225 -> Surface.ROTATION_180
        else -> Surface.ROTATION_90
    }

    /** Enabled while streaming; disabled when the camera is released. */
    private fun startOrientationListener() {
        if (orientationListener != null) return
        orientationListener = object : OrientationEventListener(this) {
            override fun onOrientationChanged(orientation: Int) {
                // ORIENTATION_UNKNOWN (-1) happens when the device lies flat,
                // which is exactly how it sat for the first Milestone 3 test.
                // Keeping the previous value is the only safe response.
                if (orientation == ORIENTATION_UNKNOWN) return
                val bucket = surfaceRotationFor(orientation)
                if (bucket != lastOrientationBucket) {
                    lastOrientationBucket = bucket
                    onPhysicalRotationChanged(bucket, orientation)
                }
            }
        }.also { if (it.canDetectOrientation()) it.enable() else Log.w(TAG, "no orientation sensor") }
    }

    private fun stopOrientationListener() {
        orientationListener?.disable()
        orientationListener = null
        lastOrientationBucket = -1
    }

    /**
     * THE FIX. Drive ImageAnalysis.targetRotation from the PHYSICAL device
     * orientation instead of leaving it at CameraX's default, which is the
     * display rotation.
     *
     * MEASURED ROOT CAUSE (24 Nov 2026, Pixel 7 Pro, Android 16):
     *
     *   ROTDIAG rotationDegrees=90 display=ROTATION_0 targetRotation=ROTATION_0
     *           physicalBucket=ROTATION_0  raw=640x480 outJpeg=480x640
     *   ORIENTATION physical=303deg -> ROTATION_90 display=ROTATION_0 ...
     *   ROTDIAG rotationDegrees=90 display=ROTATION_0 targetRotation=ROTATION_0
     *           physicalBucket=ROTATION_90 raw=640x480 outJpeg=480x640
     *
     * The device was physically turned to landscape (bucket 0 -> 90) and
     * `rotationDegrees` did NOT change, because auto-rotate was locked to
     * portrait so the display rotation never moved. CameraX was faithfully
     * rotating the frame to match a portrait DISPLAY while the camera was
     * physically pointing at the world sideways -- which is how Milestone 3
     * produced a 480x640 frame whose contents were 90 degrees off.
     *
     * Setting targetRotation makes CameraX recompute `rotationDegrees` for us.
     * We still apply that value exactly ONCE, in pixels, in imageProxyToJpeg.
     * No independent display-based correction is added anywhere -- doing both
     * is what produces a 180-degree error.
     *
     * setTargetRotation is explicitly supported while the use case is bound;
     * it affects subsequent frames only, so a frame already in flight may
     * still carry the previous value. That is harmless at 5 fps.
     */
    private fun onPhysicalRotationChanged(surfaceRotation: Int, rawDegrees: Int) {
        val before = imageAnalysis?.targetRotation ?: -1
        imageAnalysis?.targetRotation = surfaceRotation
        Log.i(
            TAG,
            "ORIENTATION physical=${rawDegrees}deg -> ${surfaceRotationName(surfaceRotation)} | " +
                "display=${surfaceRotationName(currentDisplayRotation())} | " +
                "targetRotation ${surfaceRotationName(before)} -> " +
                surfaceRotationName(imageAnalysis?.targetRotation ?: -1)
        )
    }

    /** Logged only when any value changes, never per frame. */
    private fun logRotationDiagnostics(image: ImageProxy, outW: Int, outH: Int) {
        val deg = image.imageInfo.rotationDegrees
        val disp = currentDisplayRotation()
        val target = imageAnalysis?.targetRotation ?: -1
        val sig = "$deg|$disp|$target|${image.width}x${image.height}|${outW}x$outH|$lastOrientationBucket"
        if (sig == lastRotationSignature) return
        lastRotationSignature = sig
        Log.i(
            TAG,
            "ROTDIAG rotationDegrees=$deg | display=${surfaceRotationName(disp)} | " +
                "targetRotation=${surfaceRotationName(target)} | " +
                "physicalBucket=${surfaceRotationName(lastOrientationBucket)} | " +
                "raw=${image.width}x${image.height} | outJpeg=${outW}x$outH"
        )
    }

    // ------------------------------------------------------- JPEG conversion

    private fun imageProxyToJpeg(image: ImageProxy): ByteArray? {
        if (image.format != ImageFormat.YUV_420_888) {
            Log.w(TAG, "unexpected analyzer format: ${image.format}")
            return null
        }

        val nv21 = yuv420888ToNv21(image) ?: return null

        val out = ByteArrayOutputStream()
        val yuv = YuvImage(nv21, ImageFormat.NV21, image.width, image.height, null)
        if (!yuv.compressToJpeg(Rect(0, 0, image.width, image.height), JPEG_QUALITY, out)) {
            Log.w(TAG, "compressToJpeg failed")
            return null
        }
        val jpeg = out.toByteArray()

        // The analyzer delivers frames in SENSOR orientation. On a phone held
        // upright the back sensor is typically rotated 90 degrees, so an
        // unrotated frame reaches MiDaS on its side. MiDaS would still return
        // a plausible-looking depth map, which is exactly the kind of silent
        // error that is hard to catch later -- and the downstream ROS
        // depth_to_scan geometry assumes an upright image. Rotating here costs
        // a decode/re-encode, which is affordable at ~5 fps.
        val degrees = image.imageInfo.rotationDegrees
        val result = if (degrees == 0) jpeg else rotateJpeg(jpeg, degrees)

        // Measure the ACTUAL delivered geometry rather than inferring it.
        val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        if (result != null) BitmapFactory.decodeByteArray(result, 0, result.size, opts)
        logRotationDiagnostics(image, opts.outWidth, opts.outHeight)

        return result
    }

    private fun rotateJpeg(jpeg: ByteArray, degrees: Int): ByteArray? {
        val src: Bitmap = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size) ?: return jpeg
        return try {
            val matrix = Matrix()
            matrix.postRotate(degrees.toFloat())
            val rotated = Bitmap.createBitmap(src, 0, 0, src.width, src.height, matrix, true)
            val out = ByteArrayOutputStream()
            rotated.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out)
            if (rotated != src) rotated.recycle()
            out.toByteArray()
        } catch (e: Exception) {
            Log.w(TAG, "rotation failed, sending unrotated", e)
            jpeg
        } finally {
            src.recycle()
        }
    }

    /**
     * Bridge from CameraX's [ImageProxy] to the platform-free converter.
     *
     * The conversion itself lives in [YuvConverter] so it can be unit-tested
     * on the JVM without a device; see the comments there for why that
     * matters. This method only unpacks the planes.
     */
    private fun yuv420888ToNv21(image: ImageProxy): ByteArray? {
        if (image.width <= 0 || image.height <= 0) return null
        val y = image.planes[0]
        val u = image.planes[1]
        val v = image.planes[2]
        return YuvConverter.toNv21(
            width = image.width,
            height = image.height,
            yBuffer = y.buffer, yRowStride = y.rowStride, yPixelStride = y.pixelStride,
            uBuffer = u.buffer, uRowStride = u.rowStride, uPixelStride = u.pixelStride,
            vBuffer = v.buffer, vRowStride = v.rowStride, vPixelStride = v.pixelStride,
        )
    }

    // ---------------------------------------------------------------- teardown

    override fun onDestroy() {
        stopOrientationListener()
        scanning = false
        reconnectPending = false
        webSocket?.close(1000, "Activity destroyed")
        webSocket = null
        cameraExecutor.shutdown()
        // Without this the OkHttp dispatcher's threads and connection pool
        // outlive the Activity.
        httpClient.dispatcher.executorService.shutdown()
        httpClient.connectionPool.evictAll()
        super.onDestroy()
    }
}
