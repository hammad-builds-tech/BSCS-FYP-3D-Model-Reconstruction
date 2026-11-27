package com.example.fyp3d

/**
 * Pinhole camera intrinsics for ONE delivered image, plus where they came from.
 *
 * WHY THIS IS A PURE CLASS WITH NO ANDROID TYPES
 * ==============================================
 * The Phase 4B audit found `depth_to_pointcloud.py` back-projecting with
 * **fabricated** values (`fx = fy = 500`, `cx = 40`, `cy = 30`) that belong to
 * no real camera. Replacing invented numbers with *wrongly transformed* real
 * numbers would be no better, and would be harder to notice: a scaling or
 * rotation slip still produces a plausible-looking point cloud.
 *
 * Both transforms below are therefore pure functions over plain numbers, so
 * they run in JVM unit tests with no device -- the same approach that caught
 * the YUV stride bug and the orientation flapping.
 *
 * HONESTY ABOUT PROVENANCE
 * ========================
 * `LENS_INTRINSIC_CALIBRATION` and `LENS_DISTORTION` are OPTIONAL in the
 * Camera2 specification; many devices populate neither. [source] records how
 * the numbers were actually obtained so the backend -- and the FYP report --
 * can distinguish a calibrated matrix from a geometric estimate. Nothing here
 * ever invents a value: when nothing is available the caller sends
 * [SOURCE_UNAVAILABLE] and no intrinsics at all.
 */
data class CameraIntrinsics(
    val fx: Double,
    val fy: Double,
    val cx: Double,
    val cy: Double,
    /** Radial/tangential terms when the device exposes them; null otherwise. */
    val distortion: List<Double>? = null,
    /** One of the SOURCE_* constants. Never guessed. */
    val source: String,
    /** Image these intrinsics describe, in pixels. */
    val width: Int,
    val height: Int,
) {

    companion object {
        /** Device reported a true calibrated matrix (LENS_INTRINSIC_CALIBRATION). */
        const val SOURCE_CALIBRATED = "LENS_INTRINSIC_CALIBRATION"

        /** Derived from focal length + physical sensor size. An estimate. */
        const val SOURCE_DERIVED = "FOCAL_LENGTH+SENSOR_SIZE"

        /** Device exposed neither. Callers must send no intrinsics. */
        const val SOURCE_UNAVAILABLE = "unavailable"

        /**
         * Pinhole estimate from focal length and physical sensor dimensions.
         *
         *     fx = f_mm * image_width_px / sensor_width_mm
         *
         * The principal point is assumed to be the image centre, which is an
         * assumption rather than a measurement -- hence [SOURCE_DERIVED]. It is
         * typically good to a few pixels on a phone, but it is not calibration
         * and must not be reported as though it were.
         */
        fun fromFocalLength(
            focalLengthMm: Double,
            sensorWidthMm: Double,
            sensorHeightMm: Double,
            width: Int,
            height: Int,
        ): CameraIntrinsics? {
            if (focalLengthMm <= 0.0 || sensorWidthMm <= 0.0 || sensorHeightMm <= 0.0) return null
            if (width <= 0 || height <= 0) return null
            return CameraIntrinsics(
                fx = focalLengthMm * width / sensorWidthMm,
                fy = focalLengthMm * height / sensorHeightMm,
                cx = (width - 1) / 2.0,
                cy = (height - 1) / 2.0,
                distortion = null,
                source = SOURCE_DERIVED,
                width = width,
                height = height,
            )
        }
    }

    /**
     * Rescale to a different image size.
     *
     * Camera2 reports intrinsics in ACTIVE SENSOR ARRAY pixels, but the frames
     * we transmit are the ImageAnalysis output (640x480 here). Sending the
     * sensor-array matrix unchanged would overstate the focal length by the
     * downscale factor -- roughly 6x on this device -- and every back-projected
     * depth would be wrong by that factor while still looking like a plausible
     * cloud. This is the single easiest place to be silently wrong.
     */
    fun scaledTo(newWidth: Int, newHeight: Int): CameraIntrinsics {
        require(newWidth > 0 && newHeight > 0) { "bad target size" }
        if (newWidth == width && newHeight == height) return this
        val sx = newWidth.toDouble() / width
        val sy = newHeight.toDouble() / height
        return copy(
            fx = fx * sx,
            fy = fy * sy,
            cx = cx * sx,
            cy = cy * sy,
            width = newWidth,
            height = newHeight,
        )
    }

    /**
     * Apply the same rotation the JPEG receives, so the transmitted matrix
     * describes the image the backend actually decodes.
     *
     * A rotation of 90 or 270 degrees SWAPS the axes: the horizontal focal
     * length of the rotated image is the vertical focal length of the original.
     * Forgetting that leaves fx/fy transposed, which on a non-square sensor
     * skews every reconstruction subtly rather than obviously.
     *
     * Conventions match `Bitmap.createBitmap` with a clockwise `postRotate`,
     * which is what MainActivity.rotateJpeg applies.
     */
    fun rotatedBy(degrees: Int): CameraIntrinsics {
        val d = ((degrees % 360) + 360) % 360
        return when (d) {
            0 -> this
            90 -> copy(
                // (x', y') = (H-1-y, x)
                fx = fy, fy = fx,
                cx = (height - 1) - cy, cy = cx,
                width = height, height = width,
            )
            180 -> copy(
                cx = (width - 1) - cx, cy = (height - 1) - cy,
            )
            270 -> copy(
                // (x', y') = (y, W-1-x)
                fx = fy, fy = fx,
                cx = cy, cy = (width - 1) - cx,
                width = height, height = width,
            )
            else -> throw IllegalArgumentException("rotation must be a multiple of 90, got $degrees")
        }
    }
}
