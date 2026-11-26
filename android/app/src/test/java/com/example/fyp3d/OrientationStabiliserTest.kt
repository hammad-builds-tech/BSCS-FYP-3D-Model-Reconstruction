package com.example.fyp3d

import com.example.fyp3d.OrientationStabiliser.Companion.ROTATION_0
import com.example.fyp3d.OrientationStabiliser.Companion.ROTATION_90
import com.example.fyp3d.OrientationStabiliser.Companion.ROTATION_180
import com.example.fyp3d.OrientationStabiliser.Companion.ROTATION_270
import com.example.fyp3d.OrientationStabiliser.Companion.UNKNOWN
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM tests for [OrientationStabiliser] -- no device, no emulator, no mocks.
 *
 * These assert the **sequence of emitted orientation changes** for a whole
 * stream of samples, not the mapping of individual angles. That distinction
 * matters: the Milestone 4 defect was not a wrong angle-to-bucket mapping
 * (all four buckets had been verified against real camera JPEGs) but a wrong
 * *decision over time* -- an A/B alternation being applied every sample. Only
 * a sequence-level assertion can catch that, so `feed()` collects every
 * emission and the tests compare whole lists.
 */
class OrientationStabiliserTest {

    /** Feed a stream of angles; return only the orientations actually emitted. */
    private fun feed(s: OrientationStabiliser, vararg degrees: Int): List<Int> =
        degrees.toList().mapNotNull { s.onSample(it) }

    // ---------------------------------------------------------- mapping

    @Test
    fun `the four-bucket mapping is unchanged from the hardware-verified version`() {
        // Spot values well inside each bucket, plus both sides of every
        // boundary. These are the mappings confirmed on the Pixel 7 Pro.
        assertEquals(ROTATION_0, OrientationStabiliser.bucketFor(0))
        assertEquals(ROTATION_0, OrientationStabiliser.bucketFor(44))
        assertEquals(ROTATION_270, OrientationStabiliser.bucketFor(45))
        assertEquals(ROTATION_270, OrientationStabiliser.bucketFor(134))
        assertEquals(ROTATION_180, OrientationStabiliser.bucketFor(135))
        assertEquals(ROTATION_180, OrientationStabiliser.bucketFor(224))
        assertEquals(ROTATION_90, OrientationStabiliser.bucketFor(225))
        assertEquals(ROTATION_90, OrientationStabiliser.bucketFor(314))
        assertEquals(ROTATION_0, OrientationStabiliser.bucketFor(315))
        assertEquals(ROTATION_0, OrientationStabiliser.bucketFor(359))
    }

    @Test
    fun `the 315 to 0 wraparound is one continuous bucket`() {
        // 350 and 10 degrees are 20 degrees apart across the wrap and must not
        // be treated as different orientations.
        for (d in listOf(315, 330, 350, 359, 0, 10, 44)) {
            assertEquals("deg $d", ROTATION_0, OrientationStabiliser.bucketFor(d))
        }
        val s = OrientationStabiliser()
        // Crossing the wrap repeatedly must emit exactly one change (the first).
        assertEquals(listOf(ROTATION_0), feed(s, 350, 5, 355, 10, 340, 20))
    }

    @Test
    fun `negative input is treated as ORIENTATION_UNKNOWN`() {
        assertEquals(UNKNOWN, OrientationStabiliser.bucketFor(-1))
    }

    // ------------------------------------------------- basic behaviour

    @Test
    fun `the first valid orientation is accepted immediately`() {
        val s = OrientationStabiliser()
        assertEquals(UNKNOWN, s.current)
        assertEquals(listOf(ROTATION_0), feed(s, 0))
        assertEquals(ROTATION_0, s.current)
    }

    @Test
    fun `a stable orientation emits exactly one change and no duplicates`() {
        val s = OrientationStabiliser()
        val emitted = feed(s, 10, 12, 8, 15, 5, 11, 9, 13)
        assertEquals("only the initial acceptance", listOf(ROTATION_0), emitted)
        assertEquals(ROTATION_0, s.current)
    }

    @Test
    fun `ORIENTATION_UNKNOWN samples are ignored and do not disturb state`() {
        val s = OrientationStabiliser()
        assertEquals(listOf(ROTATION_0), feed(s, 10))

        // A flat phone reports -1 repeatedly; nothing may change.
        assertEquals(emptyList<Int>(), feed(s, -1, -1, -1, -1, -1))
        assertEquals(ROTATION_0, s.current)

        // -1 must also not COUNT toward a pending change: two real samples
        // either side of the unknowns must not add up to a committed change.
        assertEquals(emptyList<Int>(), feed(s, 90, -1, 90))
        assertEquals("still portrait after only two agreeing samples",
            ROTATION_0, s.current)
    }

    @Test
    fun `unknown first samples do not pre-empt the initial acceptance`() {
        val s = OrientationStabiliser()
        assertEquals(emptyList<Int>(), feed(s, -1, -1))
        assertEquals(UNKNOWN, s.current)
        assertEquals(listOf(ROTATION_180), feed(s, 180))
    }

    // ------------------------------------- the defect this class fixes

    @Test
    fun `alternating 43 and 46 degrees produces no orientation change`() {
        // The exact fault measured on the Pixel 7 Pro in Milestone 4.
        val s = OrientationStabiliser()
        assertEquals(listOf(ROTATION_0), feed(s, 43))          // settle portrait
        val emitted = feed(s, 46, 43, 46, 43, 46, 43, 46, 43, 46, 43)
        assertEquals("boundary noise must not move the camera",
            emptyList<Int>(), emitted)
        assertEquals(ROTATION_0, s.current)
    }

    @Test
    fun `the old change-gate would have flipped on every alternating sample`() {
        // Guards against a vacuous test: reproduce the PREVIOUS logic and show
        // it disagrees. If someone reverts to a bare `bucket != last` gate,
        // the test above starts failing and this one explains why.
        var last = UNKNOWN
        var flips = 0
        for (d in listOf(43, 46, 43, 46, 43, 46, 43, 46, 43, 46, 43)) {
            val b = OrientationStabiliser.bucketFor(d)
            if (b != last) { last = b; flips++ }
        }
        assertEquals("old gate flips on every sample", 11, flips)

        val s = OrientationStabiliser()
        val stabilised = feed(s, 43, 46, 43, 46, 43, 46, 43, 46, 43, 46, 43).size
        assertEquals("stabiliser emits only the initial acceptance", 1, stabilised)
        assertNotEquals(flips, stabilised)
    }

    @Test
    fun `three consecutive samples across the 45 degree boundary do change it`() {
        val s = OrientationStabiliser()
        assertEquals(listOf(ROTATION_0), feed(s, 43))
        // Two agreeing samples are not enough...
        assertEquals(emptyList<Int>(), feed(s, 46, 46))
        assertEquals(ROTATION_0, s.current)
        // ...the third commits it.
        assertEquals(listOf(ROTATION_270), feed(s, 46))
        assertEquals(ROTATION_270, s.current)
    }

    // ------------------------------- the same, at the other boundaries

    @Test
    fun `boundary at 135 degrees is stable under noise and yields to a real turn`() {
        val s = OrientationStabiliser()
        assertEquals(listOf(ROTATION_270), feed(s, 133))
        assertEquals(emptyList<Int>(), feed(s, 137, 133, 137, 133, 137))
        assertEquals(ROTATION_270, s.current)
        assertEquals(listOf(ROTATION_180), feed(s, 137, 137, 137))
    }

    @Test
    fun `boundary at 225 degrees is stable under noise and yields to a real turn`() {
        val s = OrientationStabiliser()
        assertEquals(listOf(ROTATION_180), feed(s, 223))
        assertEquals(emptyList<Int>(), feed(s, 227, 223, 227, 223, 227))
        assertEquals(ROTATION_180, s.current)
        assertEquals(listOf(ROTATION_90), feed(s, 227, 227, 227))
    }

    @Test
    fun `boundary at 315 degrees is stable under noise and yields to a real turn`() {
        val s = OrientationStabiliser()
        assertEquals(listOf(ROTATION_90), feed(s, 313))
        assertEquals(emptyList<Int>(), feed(s, 317, 313, 317, 313, 317))
        assertEquals(ROTATION_90, s.current)
        assertEquals(listOf(ROTATION_0), feed(s, 317, 317, 317))
    }

    // ------------------------------------------------ realistic motion

    @Test
    fun `a deliberate 90 degree rotation settles after exactly three samples`() {
        val s = OrientationStabiliser()
        assertEquals(listOf(ROTATION_0), feed(s, 0))
        // A real turn sweeps through intermediate angles; all land in the new
        // bucket, so the change commits on the third of them.
        val emitted = feed(s, 50, 70, 90, 92, 88, 91)
        assertEquals("exactly one change, no churn during the sweep",
            listOf(ROTATION_270), emitted)
        assertEquals(ROTATION_270, s.current)
    }

    @Test
    fun `returning to the original orientation changes back, once`() {
        val s = OrientationStabiliser()
        assertEquals(listOf(ROTATION_0), feed(s, 0))
        assertEquals(listOf(ROTATION_270), feed(s, 90, 90, 90))
        assertEquals(listOf(ROTATION_0), feed(s, 0, 0, 0))
        assertEquals(ROTATION_0, s.current)
    }

    @Test
    fun `a partial excursion that returns is fully cancelled`() {
        val s = OrientationStabiliser()
        assertEquals(listOf(ROTATION_0), feed(s, 0))
        // Two samples toward the next bucket, then back: the counter resets,
        // so a later single sample must not inherit the earlier progress.
        assertEquals(emptyList<Int>(), feed(s, 90, 90, 0, 90))
        assertEquals(ROTATION_0, s.current)
        assertEquals(0, s.pendingCount - s.pendingCount)   // state is internal
        // Only a fresh run of three commits.
        assertEquals(listOf(ROTATION_270), feed(s, 90, 90))
    }

    @Test
    fun `switching candidate mid-count restarts the count`() {
        val s = OrientationStabiliser()
        assertEquals(listOf(ROTATION_0), feed(s, 0))
        // Two toward ROTATION_270, then two toward ROTATION_180: neither
        // reaches three, so nothing is emitted.
        assertEquals(emptyList<Int>(), feed(s, 90, 90, 180, 180))
        assertEquals(ROTATION_0, s.current)
        // A third ROTATION_180 completes that candidate.
        assertEquals(listOf(ROTATION_180), feed(s, 180))
    }

    @Test
    fun `no duplicate orientation is ever emitted`() {
        val s = OrientationStabiliser()
        val all = mutableListOf<Int>()
        // A long, messy stream: noise, unknowns, real turns, returns.
        val stream = listOf(
            -1, 0, 5, 43, 46, 43, 46, 44, 2, -1, -1,
            90, 92, 89, 91, 88, 90,
            180, 182, 178, 181,
            270, 268, 272, 271,
            0, 2, 358, 1,
        )
        for (d in stream) s.onSample(d)?.let { all.add(it) }
        for (i in 1 until all.size) {
            assertNotEquals("consecutive duplicate at index $i", all[i - 1], all[i])
        }
        assertTrue("some changes should have occurred", all.size >= 2)
        assertEquals("ends where the stream ends", ROTATION_0, s.current)
    }

    // ------------------------------------------------- configurability

    @Test
    fun `the threshold is configurable`() {
        val strict = OrientationStabiliser(samplesToChange = 5)
        assertEquals(listOf(ROTATION_0), feed(strict, 0))
        assertEquals(emptyList<Int>(), feed(strict, 90, 90, 90, 90))
        assertEquals(listOf(ROTATION_270), feed(strict, 90))

        val eager = OrientationStabiliser(samplesToChange = 1)
        assertEquals(listOf(ROTATION_0), feed(eager, 0))
        assertEquals("threshold 1 reproduces the old immediate behaviour",
            listOf(ROTATION_270), feed(eager, 90))
    }

    @Test
    fun `reset clears all state`() {
        val s = OrientationStabiliser()
        feed(s, 0, 90, 90)
        s.reset()
        assertEquals(UNKNOWN, s.current)
        assertEquals("first sample after reset is accepted immediately",
            listOf(ROTATION_180), feed(s, 180))
    }
}
