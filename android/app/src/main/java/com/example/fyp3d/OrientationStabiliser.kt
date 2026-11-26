package com.example.fyp3d

/**
 * Debounces physical-orientation samples so that sensor noise at a bucket
 * boundary cannot flip the camera's target rotation.
 *
 * WHY THIS EXISTS
 * ===============
 * Milestone 4 measured the Pixel 7 Pro alternating between `ROTATION_0` and
 * `ROTATION_270` while held at **physical 43-46 degrees** -- astride the 45
 * degree boundary. The previous gate only suppressed *repeats*:
 *
 *     if (bucket != lastOrientationBucket) { ...apply... }
 *
 * An A->B->A->B alternation passes that test every single time, so every
 * sample rewrote `ImageAnalysis.targetRotation`. That is not cosmetic: the
 * target rotation decides `rotationDegrees`, which decides whether the
 * delivered JPEG is 480x640 or 640x480. Consecutive frames in one stream
 * could therefore differ in aspect ratio, and MiDaS (and later
 * `depth_to_scan`, which assumes a stable geometry) inherits the flip.
 *
 * A preserved capture of the fault is
 * `FYP-data/phase4_evidence/milestone4_final_20261124/03_ROTATION_270_at_45deg_boundary_tilted.jpg`.
 *
 * WHY IT IS A PURE CLASS WITH NO ANDROID TYPES
 * ============================================
 * The decision is a small state machine, and state machines are exactly the
 * thing that is cheap to get subtly wrong and cheap to test. Keeping it free
 * of `android.view.Surface` and `OrientationEventListener` means the whole of
 * it runs in a plain JVM unit test -- no device, no emulator, no mocking --
 * the same approach that caught the YUV stride bug in Milestone 2.
 *
 * NO TIMERS. The machine counts *samples*, not milliseconds. Sample counting
 * is deterministic and therefore testable; a wall-clock delay would make the
 * tests timing-dependent and would silently change behaviour if the sensor
 * delivery rate ever changed.
 *
 * EXPECTED TRANSITION DELAY
 * =========================
 * `OrientationEventListener`'s single-argument constructor uses
 * `SENSOR_DELAY_NORMAL`, roughly 5 Hz (~200 ms per sample). The change is
 * committed ON the Nth agreeing sample, so with the default N = 3 a genuine
 * turn costs two extra sample intervals, about **400 ms**, and under jitter
 * comfortably below one second. The actual measured interval on the device is
 * recorded in docs/PHASE4_ANDROID_RECOVERY.md.
 */
class OrientationStabiliser(
    private val samplesToChange: Int = DEFAULT_SAMPLES_TO_CHANGE,
) {

    companion object {
        /** No orientation decided yet, or the sensor reported it cannot tell. */
        const val UNKNOWN = -1

        // These deliberately equal android.view.Surface.ROTATION_* (0..3) so
        // the caller can assign the result straight to targetRotation without
        // a lookup table. They are redeclared here only to keep this file free
        // of Android imports; the values must not drift.
        const val ROTATION_0 = 0
        const val ROTATION_90 = 1
        const val ROTATION_180 = 2
        const val ROTATION_270 = 3

        /**
         * Consecutive agreeing samples required to leave the current bucket.
         *
         * Three is the smallest value that defeats a strict A/B alternation
         * (which never produces two agreeing samples in a row) while costing
         * only ~400 ms at 5 Hz. Raising it buys more noise immunity at
         * proportionally more lag on a real turn.
         */
        const val DEFAULT_SAMPLES_TO_CHANGE = 3

        /**
         * The project's four-orientation mapping, unchanged from the version
         * verified on hardware in Milestone 4 -- all four buckets were
         * confirmed against real camera JPEGs, so the boundaries are not
         * adjusted here. Only the *debouncing* is new.
         *
         * The inversion is deliberate: a device rotated clockwise needs the
         * image rotated counter-clockwise, so 45..134 maps to ROTATION_270.
         *
         * The 315/0 wraparound is handled by the first branch, which is why it
         * tests two ranges at once rather than reading as a simple ladder.
         */
        fun bucketFor(orientationDegrees: Int): Int {
            if (orientationDegrees < 0) return UNKNOWN      // ORIENTATION_UNKNOWN
            val d = orientationDegrees % 360                // defensive; sensor gives 0..359
            return when {
                d >= 315 || d < 45 -> ROTATION_0
                d < 135 -> ROTATION_270
                d < 225 -> ROTATION_180
                else -> ROTATION_90
            }
        }
    }

    init {
        require(samplesToChange >= 1) { "samplesToChange must be >= 1" }
    }

    /** The orientation currently in force; [UNKNOWN] until the first valid sample. */
    var current: Int = UNKNOWN
        private set

    private var candidate: Int = UNKNOWN
    private var candidateCount: Int = 0

    /** Visible for tests and diagnostics: how far the pending candidate has got. */
    val pendingCandidate: Int get() = candidate
    val pendingCount: Int get() = candidateCount

    /**
     * Feed one sensor sample.
     *
     * @return the new orientation **only when it changes**, otherwise `null`.
     *         A caller can therefore treat a non-null result as "apply this",
     *         and will never be handed the same value twice in a row.
     */
    fun onSample(orientationDegrees: Int): Int? {
        val bucket = bucketFor(orientationDegrees)

        // Rule: ignore ORIENTATION_UNKNOWN. It is what the sensor reports with
        // the device lying flat -- exactly how it sat at the start of the
        // Milestone 3 test -- so it must never disturb the current value or
        // the candidate being accumulated.
        if (bucket == UNKNOWN) return null

        // Rule: accept the first valid orientation immediately. Waiting here
        // would leave the camera on CameraX's display-derived default, which
        // is the Milestone 3 defect this whole mechanism exists to avoid.
        if (current == UNKNOWN) {
            current = bucket
            resetCandidate()
            return bucket
        }

        // Rule: a sample agreeing with the current orientation cancels any
        // pending change. This is what makes an A/B alternation stable: every
        // other sample resets the counter, so it never reaches the threshold.
        if (bucket == current) {
            resetCandidate()
            return null
        }

        if (bucket == candidate) {
            candidateCount++
        } else {
            candidate = bucket
            candidateCount = 1
        }

        if (candidateCount >= samplesToChange) {
            current = bucket
            resetCandidate()
            return bucket          // never a duplicate: bucket != current above
        }
        return null
    }

    /** Forget all state, e.g. when the camera is unbound. */
    fun reset() {
        current = UNKNOWN
        resetCandidate()
    }

    private fun resetCandidate() {
        candidate = UNKNOWN
        candidateCount = 0
    }
}
