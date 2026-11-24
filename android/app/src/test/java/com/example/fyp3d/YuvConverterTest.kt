package com.example.fyp3d

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test
import java.nio.ByteBuffer

/**
 * JVM unit tests for [YuvConverter] — no device, no emulator, no mocks.
 *
 * WHY THESE EXIST
 * ===============
 * A YUV stride bug does not throw and does not corrupt the JPEG container: it
 * produces a sheared or wrongly-coloured image that still decodes, so MiDaS
 * returns a plausible depth map and nothing anywhere reports a problem. The
 * only ways to catch it are to look at an uploaded frame by eye, or to test
 * the conversion against input whose correct output is known by construction.
 *
 * These tests do the latter, and they cover precisely the two assumptions the
 * recovered implementation made and that real devices violate:
 *
 *   1. rowStride == width            (false when hardware pads rows)
 *   2. chroma pixelStride == 1       (false on semi-planar devices, == 2)
 *
 * They run on the host with `./gradlew testDebugUnitTest`, which means the
 * conversion is verified even while no phone is connected.
 */
class YuvConverterTest {

    /**
     * Build a Y plane where pixel (x, y) has the value `y * width + x`
     * (mod 256), laid out with `rowStride` bytes per row so that any bytes
     * past the image width are PADDING deliberately filled with a poison
     * value. If the converter reads padding, the output will contain it and
     * the assertion fails.
     */
    private fun yPlane(width: Int, height: Int, rowStride: Int, poison: Byte): ByteBuffer {
        val buf = ByteArray(rowStride * height) { poison }
        for (r in 0 until height) {
            for (c in 0 until width) {
                buf[r * rowStride + c] = ((r * width + c) % 256).toByte()
            }
        }
        return ByteBuffer.wrap(buf)
    }

    private fun expectedY(width: Int, height: Int) =
        ByteArray(width * height) { i -> (i % 256).toByte() }

    @Test
    fun `packed planes round-trip exactly`() {
        val w = 8
        val h = 4
        val y = yPlane(w, h, rowStride = w, poison = 0x7F)

        // Fully planar chroma: separate U and V, pixelStride 1, no padding.
        val cw = w / 2
        val ch = h / 2
        val u = ByteBuffer.wrap(ByteArray(cw * ch) { (0x10 + it).toByte() })
        val v = ByteBuffer.wrap(ByteArray(cw * ch) { (0x80 + it).toByte() })

        val nv21 = YuvConverter.toNv21(
            w, h,
            y, w, 1,
            u, cw, 1,
            v, cw, 1,
        )

        assertEquals("NV21 is 12 bits per pixel", w * h + w * h / 2, nv21.size)
        assertArrayEquals(
            "luma must be the image, in order",
            expectedY(w, h),
            nv21.copyOfRange(0, w * h)
        )

        // Chroma must be interleaved V first, then U.
        val chroma = nv21.copyOfRange(w * h, nv21.size)
        for (i in 0 until cw * ch) {
            assertEquals("V at pair $i", (0x80 + i).toByte(), chroma[i * 2])
            assertEquals("U at pair $i", (0x10 + i).toByte(), chroma[i * 2 + 1])
        }
    }

    @Test
    fun `row padding in the luma plane is not copied into the image`() {
        val w = 6
        val h = 4
        // Hardware-aligned rows: 10 bytes of storage for 6 pixels of image.
        val rowStride = 10
        val poison = 0xEE.toByte()
        val y = yPlane(w, h, rowStride, poison)

        val cw = w / 2
        val ch = h / 2
        val u = ByteBuffer.wrap(ByteArray(cw * ch) { 0x11 })
        val v = ByteBuffer.wrap(ByteArray(cw * ch) { 0x22 })

        val nv21 = YuvConverter.toNv21(
            w, h,
            y, rowStride, 1,
            u, cw, 1,
            v, cw, 1,
        )

        val luma = nv21.copyOfRange(0, w * h)
        assertArrayEquals(
            "a flat bulk copy would shear the image by pulling in padding",
            expectedY(w, h),
            luma
        )
        // Belt and braces: the poison byte must appear nowhere in the luma.
        assertEquals(
            "padding byte leaked into the image",
            -1,
            luma.indexOfFirst { it == poison }
        )
    }

    @Test
    fun `semi-planar chroma with pixelStride 2 is de-interleaved correctly`() {
        val w = 4
        val h = 4
        val y = yPlane(w, h, rowStride = w, poison = 0x7F)

        val cw = w / 2   // 2
        val ch = h / 2   // 2

        // Semi-planar: ONE allocation holding U,V,U,V... Both planes are views
        // into it with pixelStride 2; the V plane simply starts one byte later.
        // This is the layout the recovered implementation mishandled.
        val chromaRowStride = cw * 2          // 4 bytes per chroma row
        val shared = ByteArray(chromaRowStride * ch)
        for (r in 0 until ch) {
            for (c in 0 until cw) {
                shared[r * chromaRowStride + c * 2] = (0x30 + r * cw + c).toByte()      // U
                shared[r * chromaRowStride + c * 2 + 1] = (0x90 + r * cw + c).toByte()  // V
            }
        }
        val u = ByteBuffer.wrap(shared)
        val v = ByteBuffer.wrap(shared.copyOfRange(1, shared.size))

        val nv21 = YuvConverter.toNv21(
            w, h,
            y, w, 1,
            u, chromaRowStride, 2,
            v, chromaRowStride, 2,
        )

        val chroma = nv21.copyOfRange(w * h, nv21.size)
        for (r in 0 until ch) {
            for (c in 0 until cw) {
                val i = r * cw + c
                assertEquals("V at ($r,$c)", (0x90 + i).toByte(), chroma[i * 2])
                assertEquals("U at ($r,$c)", (0x30 + i).toByte(), chroma[i * 2 + 1])
            }
        }
    }

    @Test
    fun `luma pixelStride greater than one is honoured`() {
        // Rare but legal: interleaved luma. Included because the fast path is
        // only valid when pixelStride == 1, and this proves the slow path.
        val w = 4
        val h = 2
        val pixelStride = 2
        val rowStride = w * pixelStride
        val buf = ByteArray(rowStride * h) { 0xCC.toByte() }
        for (r in 0 until h) {
            for (c in 0 until w) {
                buf[r * rowStride + c * pixelStride] = ((r * w + c) % 256).toByte()
            }
        }

        val cw = w / 2
        val ch = h / 2
        val u = ByteBuffer.wrap(ByteArray(cw * ch) { 0x01 })
        val v = ByteBuffer.wrap(ByteArray(cw * ch) { 0x02 })

        val nv21 = YuvConverter.toNv21(
            w, h,
            ByteBuffer.wrap(buf), rowStride, pixelStride,
            u, cw, 1,
            v, cw, 1,
        )

        assertArrayEquals(expectedY(w, h), nv21.copyOfRange(0, w * h))
    }

    @Test
    fun `output size is always 12 bits per pixel`() {
        for ((w, h) in listOf(2 to 2, 16 to 16, 640 to 480, 1280 to 720)) {
            val y = yPlane(w, h, rowStride = w, poison = 0)
            val cw = w / 2
            val ch = h / 2
            val nv21 = YuvConverter.toNv21(
                w, h,
                y, w, 1,
                ByteBuffer.wrap(ByteArray(cw * ch)), cw, 1,
                ByteBuffer.wrap(ByteArray(cw * ch)), cw, 1,
            )
            assertEquals("${w}x$h", w * h * 3 / 2, nv21.size)
        }
    }

    /**
     * Guard against a vacuous test suite.
     *
     * A test that cannot fail proves nothing, so this reproduces the RECOVERED
     * (buggy) algorithm verbatim and asserts that it disagrees with the fixed
     * converter on exactly the inputs above. If someone later "simplifies"
     * [YuvConverter] back to a flat buffer copy, the tests above will fail --
     * and this test documents why they are the right tests.
     *
     * The recovered implementation was, in effect:
     *     yBuffer.get(nv21, 0, ySize)        // ignores rowStride
     *     ... interleave uBytes / vBytes ... // ignores pixelStride
     */
    @Test
    fun `the recovered naive algorithm is provably wrong on padded rows`() {
        val w = 6
        val h = 4
        val rowStride = 10          // padded, as real hardware does
        val poison = 0xEE.toByte()

        // --- naive: one bulk copy of w*h bytes, ignoring rowStride --------
        val naive = ByteArray(w * h)
        yPlane(w, h, rowStride, poison).also { it.position(0) }.get(naive, 0, w * h)

        // --- correct ------------------------------------------------------
        val cw = w / 2
        val ch = h / 2
        val fixed = YuvConverter.toNv21(
            w, h,
            yPlane(w, h, rowStride, poison), rowStride, 1,
            ByteBuffer.wrap(ByteArray(cw * ch)), cw, 1,
            ByteBuffer.wrap(ByteArray(cw * ch)), cw, 1,
        ).copyOfRange(0, w * h)

        assertArrayEquals("the fixed converter must match the true image",
            expectedY(w, h), fixed)

        assertNotEquals(
            "if these matched, the padding tests would be vacuous",
            fixed.toList(), naive.toList()
        )
        // The naive copy drags padding into the image; the fixed one never does.
        assertNotEquals("naive copy should contain padding", -1,
            naive.indexOfFirst { it == poison })
        assertEquals("fixed copy must not contain padding", -1,
            fixed.indexOfFirst { it == poison })
    }
}
