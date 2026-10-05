"""
tools.xbt against textures built here -- no game files.

The swizzle is checked against an independent statement of the rule (bit
interleave written out by hand for the sizes used), not against the module's
own function run backwards.
"""
import os
import struct
import tempfile
import unittest

from tools import xbt


def make_xbt(fmt, w, h, levels_data, extra=b"", magic=0x11, word4=0x22):
    header = bytearray(0x80)
    struct.pack_into("<IIII", header, 0, magic, word4, w, h)
    struct.pack_into("<I", header, 0x14, fmt)
    header[0x40] = 0x99    # an unknown byte that must survive a round trip
    return bytes(header) + b"".join(levels_data) + extra


class SwizzleTest(unittest.TestCase):
    def test_square_4x4_is_morton_x_first(self):
        # morton(x, y) = ... y1 x1 y0 x0
        def morton(x, y):
            return (x & 1) | ((y & 1) << 1) | ((x & 2) << 1) | ((y & 2) << 2)
        mx, my = xbt.swizzle_masks(4, 4)
        self.assertEqual((mx, my), (0b0101, 0b1010))
        linear = bytes(range(16))
        swz = xbt.swizzle(linear, 4, 4, 1)
        for y in range(4):
            for x in range(4):
                self.assertEqual(swz[morton(x, y)], linear[y * 4 + x])

    def test_wide_8x2_keeps_x_bits_past_y(self):
        # 8x2: y has one bit. Bits: x0 y0 x1 x2.
        def off(x, y):
            return (x & 1) | ((y & 1) << 1) | ((x >> 1) << 2)
        linear = bytes(range(16))
        swz = xbt.swizzle(linear, 8, 2, 1)
        for y in range(2):
            for x in range(8):
                self.assertEqual(swz[off(x, y)], linear[y * 8 + x])

    def test_round_trip(self):
        data = os.urandom(16 * 4 * 4)
        self.assertEqual(xbt.unswizzle(xbt.swizzle(data, 16, 4, 4), 16, 4, 4), data)


class LayoutTest(unittest.TestCase):
    def test_mip_chain_from_size(self):
        # DXT1 8x8: 32 + 8 + 8 + 8 bytes (8x8, 4x4, 2x2, 1x1 -- min one block).
        x = xbt.Xbt(make_xbt(0, 8, 8, [b"a" * 32, b"b" * 8, b"c" * 8, b"d" * 8]))
        self.assertEqual([(w, h) for w, h, _ in x.levels], [(8, 8), (4, 4), (2, 2), (1, 1)])
        self.assertEqual(x.leftover, 0)

    def test_leftover_is_reported(self):
        x = xbt.Xbt(make_xbt(1, 4, 4, [b"a" * 16], extra=b"zz"))
        self.assertEqual(len(x.levels), 1)
        self.assertEqual(x.leftover, 2)

    def test_rejects(self):
        for data in (b"short", make_xbt(9, 4, 4, [b"x" * 64]), make_xbt(0, 0, 4, [])):
            with self.assertRaises(xbt.XbtError):
                xbt.Xbt(data)


class DdsTest(unittest.TestCase):
    def test_dxt1_blocks_copied_and_back(self):
        levels = [os.urandom(32), os.urandom(8), os.urandom(8), os.urandom(8)]
        orig = make_xbt(0, 8, 8, levels)
        dds = xbt.to_dds(xbt.Xbt(orig))
        self.assertEqual(dds[:4], b"DDS ")
        self.assertEqual(dds[84:88], b"DXT1")
        self.assertEqual(struct.unpack_from("<I", dds, 28)[0], 4)    # mip count
        self.assertEqual(dds[128:], b"".join(levels))
        self.assertEqual(xbt.from_dds(dds, xbt.Xbt(orig)), orig)

    def test_argb_unswizzled_per_level_and_back(self):
        lin0 = bytes(range(256))[:4 * 8 * 4] * 1          # 8x4 texels, 4 bytes each
        lin1 = bytes(range(32))                           # 4x2
        lin2 = bytes(range(100, 108))                     # 2x1
        lin3 = bytes(range(200, 204))                     # 1x1
        sw = [xbt.swizzle(lin0, 8, 4, 4), xbt.swizzle(lin1, 4, 2, 4),
              xbt.swizzle(lin2, 2, 1, 4), xbt.swizzle(lin3, 1, 1, 4)]
        orig = make_xbt(2, 8, 4, sw)
        dds = xbt.to_dds(xbt.Xbt(orig))
        self.assertEqual(struct.unpack_from("<I", dds, 88)[0], 32)  # bits per pixel
        self.assertEqual(dds[128:], lin0 + lin1 + lin2 + lin3)
        back = xbt.from_dds(dds, xbt.Xbt(orig))
        self.assertEqual(back, orig, "header (unknown words too) and texels survive")

    def test_from_dds_is_strict(self):
        tmpl = xbt.Xbt(make_xbt(0, 8, 8, [b"a" * 32, b"b" * 8, b"c" * 8, b"d" * 8]))
        other = xbt.to_dds(xbt.Xbt(make_xbt(1, 8, 8, [b"a" * 64, b"b" * 16, b"c" * 16, b"d" * 16])))
        with self.assertRaises(xbt.XbtError):
            xbt.from_dds(other, tmpl)                                  # format
        bigger = xbt.to_dds(xbt.Xbt(make_xbt(0, 16, 8, [b"a" * 64])))
        with self.assertRaises(xbt.XbtError):
            xbt.from_dds(bigger, tmpl)                                 # size
        one_level = xbt.to_dds(xbt.Xbt(make_xbt(0, 8, 8, [b"a" * 32])))
        with self.assertRaises(xbt.XbtError):
            xbt.from_dds(one_level, tmpl)                              # levels
        new = xbt.Xbt(xbt.from_dds(one_level, tmpl, allow_levels=True))
        self.assertEqual(len(new.levels), 1)

    def test_cli_and_index(self):
        from tools.tests.test_ts2pak import p8ck
        with tempfile.TemporaryDirectory() as tmp:
            tex = make_xbt(0, 4, 4, [b"q" * 8])
            data = os.path.join(tmp, "data")
            os.makedirs(data)
            open(os.path.join(data, "chr.pak"), "wb").write(
                p8ck([("textures\\0001.xbt", tex), ("ob\\x.xbr", b"m")]))
            csv_path = os.path.join(tmp, "t.csv")
            self.assertEqual(xbt.main(["index", data, "--csv", csv_path]), 0)
            rows = open(csv_path).read().splitlines()
            self.assertEqual(len(rows), 2)
            self.assertIn("textures\\0001.xbt,4,4,DXT1,1,", rows[1])
            p = os.path.join(tmp, "a.xbt")
            open(p, "wb").write(tex)
            d = os.path.join(tmp, "a.dds")
            self.assertEqual(xbt.main(["to-dds", p, d]), 0)
            self.assertEqual(xbt.main(["from-dds", d, p, "-o", os.path.join(tmp, "b.xbt")]), 0)
            self.assertEqual(open(os.path.join(tmp, "b.xbt"), "rb").read(), tex)


if __name__ == "__main__":
    unittest.main()
