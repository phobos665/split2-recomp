"""tools.xbr against a synthetic one-mesh model."""
import struct
import unittest

from tools import xbr


def make_xbr():
    """Header, a one-entry texture list, one mesh record, the count block."""
    out = bytearray(struct.pack("<3I", 0xC, 0, 0))
    out += struct.pack("<4I", 5, 0, 0, 0) + struct.pack("<4I", 0xFFFFFFFF, 0, 0, 0)
    mesh_at = len(out)
    out += bytes(0x9C)
    count_at = len(out)
    out += struct.pack("<3I", 1, 1, 1) + bytes(0x28)
    struct.pack_into("<I", out, 4, count_at)
    return bytes(out)


def tri(z):
    n = (0.0, 0.0, -1.0)
    return [(0.0, 0.0, z, 0.0, 0.0, (127,) * 4, n), (1.0, 0.0, z, 1.0, 0.0, (127,) * 4, n),
            (0.0, 1.0, z, 0.0, 1.0, (127,) * 4, n)]


class XbrTest(unittest.TestCase):
    def test_replace_geometry(self):
        data = xbr.replace_geometry(make_xbr(), [9000, 9001], [(0, [tri(0), tri(1)]), (1, [tri(2)])])
        m = xbr.Model(data)
        self.assertEqual([t[0] for t in m.textures], [5, 9000, 9001])     # the model's own entries first
        _, vo, counts, fo = m.mesh(0)
        self.assertEqual(counts, (9, 3))
        # Strips: texture indices count past the model's own; starts on 4.
        strips = [struct.unpack_from("<5H", data, vo[0] + 10 * k) for k in range(3)]
        self.assertEqual([(s[0], s[2], s[3]) for s in strips[:2]], [(1, 0, 6), (2, 8, 3)])
        self.assertEqual(strips[2][4], 0xFFFF)
        self.assertEqual(struct.unpack_from("<H", data, vo[4])[0], 6 | 0x8000)
        # Restart flags on the first two vertices of each triangle.
        words = [struct.unpack_from("<I", data, vo[5] + 16 * k + 12)[0] for k in range(3)]
        self.assertEqual(words, [0x3F808000, 0x3F808000, 0x3F800000])
        # The face table runs parallel to the strips.
        ptr, cnt = struct.unpack_from("<II", data, fo[0] + 8)
        self.assertEqual((cnt, list(struct.unpack_from("<3H", data, ptr))), (3, [8, 9, 10]))
        self.assertEqual(len(m.positions(0)), 11)


if __name__ == "__main__":
    unittest.main()
