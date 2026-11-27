package com.example.fyp3d

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM tests for [CameraIntrinsics] -- no device, no emulator, no mocks.
 *
 * These exist because a wrong intrinsic matrix fails SILENTLY. Unlike a crash
 * or a corrupt JPEG, a focal length that is 6x too large still back-projects
 * into a perfectly plausible-looking point cloud -- just one at the wrong
 * scale. The two transforms most likely to be wrong are sensor-array ->
 * analysis-resolution scaling and the axis swap under 90/270 rotation, so
 * both are pinned down here against values computed by hand.
 */
class CameraIntrinsicsTest {

    private val eps = 1e-9

    /** A plausible sensor-array matrix: 4080x3072, principal point centred. */
    private fun sensorArray() = CameraIntrinsics(
        fx = 3000.0, fy = 3000.0,
        cx = 2039.5, cy = 1535.5,
        distortion = null,
        source = CameraIntrinsics.SOURCE_CALIBRATED,
        width = 4080, height = 3072,
    )

    // ------------------------------------------------------- scaling

    @Test
    fun `scaling to the analysis resolution scales focal length and centre alike`() {
        // 4080x3072 -> 640x480. Note the aspect ratio differs slightly
        // (1.328 vs 1.333), so sx and sy are NOT equal and must be applied
        // independently -- using one factor for both is a classic slip.
        val s = sensorArray().scaledTo(640, 480)
        val sx = 640.0 / 4080.0
        val sy = 480.0 / 3072.0
        assertEquals(3000.0 * sx, s.fx, eps)
        assertEquals(3000.0 * sy, s.fy, eps)
        assertEquals(2039.5 * sx, s.cx, eps)
        assertEquals(1535.5 * sy, s.cy, eps)
        assertEquals(640, s.width)
        assertEquals(480, s.height)
    }

    @Test
    fun `scaling is what prevents a grossly overstated focal length`() {
        val raw = sensorArray()
        val scaled = raw.scaledTo(640, 480)
        // Guard the actual failure mode: forwarding the sensor-array matrix
        // unchanged would overstate fx by over 6x.
        assertTrue("fx must shrink with the image", scaled.fx < raw.fx / 6.0)
        assertNotEquals(raw.fx, scaled.fx, 1.0)
    }

    @Test
    fun `scaling to the same size is a no-op`() {
        val s = sensorArray()
        assertEquals(s, s.scaledTo(4080, 3072))
    }

    @Test
    fun `provenance survives both transforms`() {
        val s = sensorArray().scaledTo(640, 480).rotatedBy(90)
        assertEquals(CameraIntrinsics.SOURCE_CALIBRATED, s.source)
    }

    // ------------------------------------------------------ rotation

    /** Asymmetric on every axis, so a transposition cannot hide. */
    private fun asym() = CameraIntrinsics(
        fx = 500.0, fy = 400.0,
        cx = 310.0, cy = 230.0,
        distortion = null,
        source = CameraIntrinsics.SOURCE_CALIBRATED,
        width = 640, height = 480,
    )

    @Test
    fun `rotation by zero changes nothing`() {
        assertEquals(asym(), asym().rotatedBy(0))
    }

    @Test
    fun `rotation by 90 swaps the axes and the image dimensions`() {
        val r = asym().rotatedBy(90)
        // (x', y') = (H-1-y, x)
        assertEquals(400.0, r.fx, eps)          // fx' = fy
        assertEquals(500.0, r.fy, eps)          // fy' = fx
        assertEquals(480 - 1 - 230.0, r.cx, eps)
        assertEquals(310.0, r.cy, eps)
        assertEquals(480, r.width)
        assertEquals(640, r.height)
    }

    @Test
    fun `rotation by 270 swaps the axes the other way`() {
        val r = asym().rotatedBy(270)
        // (x', y') = (y, W-1-x)
        assertEquals(400.0, r.fx, eps)
        assertEquals(500.0, r.fy, eps)
        assertEquals(230.0, r.cx, eps)
        assertEquals(640 - 1 - 310.0, r.cy, eps)
        assertEquals(480, r.width)
        assertEquals(640, r.height)
    }

    @Test
    fun `rotation by 180 mirrors the centre but keeps the axes`() {
        val r = asym().rotatedBy(180)
        assertEquals(500.0, r.fx, eps)
        assertEquals(400.0, r.fy, eps)
        assertEquals(640 - 1 - 310.0, r.cx, eps)
        assertEquals(480 - 1 - 230.0, r.cy, eps)
        assertEquals(640, r.width)
        assertEquals(480, r.height)
    }

    @Test
    fun `four 90 degree rotations return to the original`() {
        var r = asym()
        repeat(4) { r = r.rotatedBy(90) }
        val o = asym()
        assertEquals(o.fx, r.fx, 1e-9)
        assertEquals(o.fy, r.fy, 1e-9)
        assertEquals(o.cx, r.cx, 1e-9)
        assertEquals(o.cy, r.cy, 1e-9)
        assertEquals(o.width, r.width)
        assertEquals(o.height, r.height)
    }

    @Test
    fun `90 then 270 is the identity`() {
        val r = asym().rotatedBy(90).rotatedBy(270)
        assertEquals(asym().fx, r.fx, eps)
        assertEquals(asym().cx, r.cx, eps)
        assertEquals(asym().width, r.width)
    }

    @Test
    fun `negative and over-wrapped rotations normalise`() {
        assertEquals(asym().rotatedBy(90), asym().rotatedBy(-270))
        assertEquals(asym().rotatedBy(180), asym().rotatedBy(540))
    }

    @Test(expected = IllegalArgumentException::class)
    fun `a non-right-angle rotation is rejected rather than approximated`() {
        asym().rotatedBy(45)
    }

    @Test
    fun `an axis swap would be caught -- fx and fy must not be interchangeable`() {
        // Anti-vacuous guard: if rotatedBy(90) forgot to swap, fx would stay
        // 500. Assert explicitly that it does not.
        val r = asym().rotatedBy(90)
        assertNotEquals("fx must have become fy", 500.0, r.fx, 1e-6)
    }

    // ---------------------------------------- derived-from-focal-length

    @Test
    fun `focal length derivation matches the hand-computed pinhole formula`() {
        // f = 6.81 mm, sensor 9.8 x 7.3 mm, image 640x480
        val i = CameraIntrinsics.fromFocalLength(6.81, 9.8, 7.3, 640, 480)!!
        assertEquals(6.81 * 640 / 9.8, i.fx, 1e-9)
        assertEquals(6.81 * 480 / 7.3, i.fy, 1e-9)
        assertEquals(319.5, i.cx, eps)
        assertEquals(239.5, i.cy, eps)
        assertEquals(CameraIntrinsics.SOURCE_DERIVED, i.source)
        assertNull("a derived estimate carries no distortion model", i.distortion)
    }

    @Test
    fun `derivation refuses impossible inputs instead of inventing numbers`() {
        assertNull(CameraIntrinsics.fromFocalLength(0.0, 9.8, 7.3, 640, 480))
        assertNull(CameraIntrinsics.fromFocalLength(6.81, 0.0, 7.3, 640, 480))
        assertNull(CameraIntrinsics.fromFocalLength(6.81, 9.8, 0.0, 640, 480))
        assertNull(CameraIntrinsics.fromFocalLength(6.81, 9.8, 7.3, 0, 480))
        assertNull(CameraIntrinsics.fromFocalLength(6.81, 9.8, 7.3, 640, 0))
    }

    @Test
    fun `a derived estimate is never labelled as calibrated`() {
        val i = CameraIntrinsics.fromFocalLength(6.81, 9.8, 7.3, 640, 480)!!
        assertNotEquals(CameraIntrinsics.SOURCE_CALIBRATED, i.source)
    }

    // --------------------------------------------- realistic end-to-end

    @Test
    fun `sensor matrix scaled then rotated gives the delivered image geometry`() {
        // The real path: 4080x3072 sensor matrix -> 640x480 analysis frame ->
        // rotated 90 for an upright portrait JPEG of 480x640.
        val delivered = sensorArray().scaledTo(640, 480).rotatedBy(90)
        assertEquals(480, delivered.width)
        assertEquals(640, delivered.height)
        // fx of the delivered image is the scaled VERTICAL focal length.
        assertEquals(3000.0 * (480.0 / 3072.0), delivered.fx, 1e-9)
        assertEquals(3000.0 * (640.0 / 4080.0), delivered.fy, 1e-9)
        // Principal point must stay inside the image.
        assertTrue(delivered.cx in 0.0..delivered.width.toDouble())
        assertTrue(delivered.cy in 0.0..delivered.height.toDouble())
    }
}
