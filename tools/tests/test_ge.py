"""
tools.ge_rom / ge_model / ge_sound against a synthetic cartridge: a data
segment holding a file table and a texture size table, one model, and
textures. No GoldenEye data is involved.
"""
import json
import os
import struct
import tempfile
import unittest
import wave
import zlib

from tools import ge_guns, ge_model, ge_rom, ge_sound

NAME_BASE = 0x80020000
NUM_TEXTURES = 1024


def rz(data):
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return b"\x11\x72" + c.compress(data) + c.flush()


def rgba16_texture(w, h, value):
    """An uncompressed RGBA16 texture as the game stores it."""
    bits = [(1, 4), (w, 8), (h, 8), (0, 4)] + [(value, 16)] * (w * h)
    acc, n = 0, 0
    for v, k in bits:
        acc, n = (acc << k) | v, n + k
    pad = (-n) % 8
    return b"\x00" + (acc << pad).to_bytes((n + pad) // 8, "big")


def make_model():
    """A root group, a display list on joint 0 with one textured triangle,
    a group on joint 1 (a flash) and a part textured as the hand."""
    m = bytearray(0x400)
    B = ge_model.BASE

    def node(at, op, data, parent=0, nxt=0, child=0):
        struct.pack_into(">HHIIIII", m, at, op, 0, data and B + data, parent and B + parent,
                         nxt and B + nxt, 0, child and B + child)

    node(0x000, 2, 0x100, child=0x018)                   # root group, joint 0
    node(0x018, 4, 0x120, parent=0x000, nxt=0x030)       # gun part
    node(0x030, 2, 0x140, parent=0x000, nxt=0x048, child=0x060)  # group on joint 1
    node(0x060, 4, 0x160, parent=0x030)                  # flash part
    node(0x048, 4, 0x180, parent=0x000)                  # hand part
    struct.pack_into(">fffH", m, 0x100, 0, 0, 0, 0)
    struct.pack_into(">fffH", m, 0x140, 0, 0, 100, 1)
    for rec, gdl, tex in ((0x120, 0x200, 5), (0x160, 0x260, 6), (0x180, 0x2C0, 0x701)):
        struct.pack_into(">IIIIH", m, rec, B + gdl, 0, 0, B + 0x300, 3)
        cmds = [(0xBB000001, 0xFFFFFFFF), (0xC0000000, tex), (0x04200030, B + 0x300),
                (0xBF000000, (0 << 16) | (10 << 8) | 20), (0xB8000000, 0)]
        for k, (w0, w1) in enumerate(cmds):
            struct.pack_into(">II", m, gdl + 8 * k, w0, w1)
    for k, (x, y, z, s, t) in enumerate(((0, 0, 0, 0, 0), (10, 0, 0, 2 * 32, 0), (0, 10, 0, 0, 4 * 32))):
        struct.pack_into(">hhhHhhBBBB", m, 0x300 + 16 * k, x, y, z, 0, s, t, 255, 128, 0, 255)
    return bytes(m)


def make_rom():
    model = rz(make_model())
    rom = bytearray(b"\x80\x37\x12\x40" + bytes(0x3FFC))
    files = [("", b""), ("Gtest1Z", model), ("Ptest1Z", model), ("ob/ob_end.seg", b" " * 15 + b"\n")]
    seg = bytearray(0x22000)
    names_at, table_at, tex_at = 0x1000, 0x2000, 0x4000
    pos = 0x8000
    offsets = []
    blobs = bytearray()
    for name, blob in files:
        offsets.append(pos + len(blobs))
        blobs += blob
        blobs += bytes((-len(blobs)) % 16)
    p = names_at
    for k, (name, _) in enumerate(files):
        ptr = 0
        if name:
            seg[p:p + len(name) + 1] = name.encode() + b"\0"
            ptr = NAME_BASE + p
            p += len(name) + 1 + (-(len(name) + 1)) % 4
        struct.pack_into(">III", seg, table_at + 12 * k, k, ptr, offsets[k])
    textures = [rgba16_texture(2, 2, 0xF801 if k % 2 else 0x07C1) for k in range(NUM_TEXTURES)]
    for k, t in enumerate(textures):
        struct.pack_into(">II", seg, tex_at + 8 * k, len(t), 0)
    struct.pack_into(">II", seg, tex_at + 8 * NUM_TEXTURES, 0xFFFF, 0)
    data = rz(bytes(seg))
    rom[0x1000:0x1000 + len(data)] = data
    rom = rom[:0x8000] + bytes(max(0, 0x8000 - len(rom)))
    rom = bytearray(rom[:0x8000]) + blobs
    rom += b"".join(textures)
    return bytes(rom)


class RomTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = ge_rom.Rom(make_rom())

    def test_files_and_textures(self):
        self.assertEqual(self.rom.name_base, NAME_BASE)
        self.assertIn("Gtest1Z", self.rom.files)
        self.assertEqual(self.rom.file("Gtest1Z"), make_model())
        self.assertEqual(self.rom.texture_count, NUM_TEXTURES)
        w, h, rgba = self.rom.texture(1)
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(rgba[:4], bytes((255, 0, 0, 255)))      # 0xF801: red, opaque
        self.assertEqual(self.rom.texture(0)[2][:4], bytes((0, 255, 0, 255)))

    def test_byte_orders(self):
        z64 = make_rom()[:64]
        v64 = bytearray(z64)
        v64[0::2], v64[1::2] = z64[1::2], z64[0::2]
        n64 = bytearray(z64)
        n64[0::4], n64[1::4], n64[2::4], n64[3::4] = z64[3::4], z64[2::4], z64[1::4], z64[0::4]
        self.assertEqual(ge_rom.to_big_endian(bytes(v64)), z64)
        self.assertEqual(ge_rom.to_big_endian(bytes(n64)), z64)
        with self.assertRaises(ValueError):
            ge_rom.to_big_endian(b"nope")

    def test_zlib_texture(self):
        # Format CI4 over RGBA16: two colours, a 2x2 image of indices.
        body = bytes([ge_rom.CI4_RGBA16, 1]) + struct.pack(">HH", 0xF801, 0x003F) + bytes([2, 2]) + rz(b"\x01\x10")
        w, h, rgba = ge_rom.decode_texture(b"\x40" + body)
        self.assertEqual((w, h), (2, 2))
        # Indices 0, 1, 1, 0: red (0xF801), then blue (0x003F).
        self.assertEqual(rgba[0:4], bytes((255, 0, 0, 255)))
        self.assertEqual(rgba[4:8], bytes((0, 0, 255, 255)))


class ModelTest(unittest.TestCase):
    def test_parts(self):
        m = ge_model.Model(make_model(), texture_size=lambda n: (32, 32))
        kinds = {p.kind: p for p in m.parts}
        self.assertEqual(set(kinds), {"gun", "flash", "hand"})
        gun = kinds["gun"]
        self.assertEqual(len(gun.tris), 1)
        tex, tri = gun.tris[0]
        self.assertEqual(tex, (5, 0, 0))
        self.assertAlmostEqual(tri[1][3], 2 / 32, places=4)       # s = 2 texels
        self.assertAlmostEqual(tri[2][4], 4 / 32, places=4)
        self.assertEqual(kinds["flash"].tris[0][1][0][2], 100)    # the joint-1 group's origin

    def test_obj(self):
        m = ge_model.Model(make_model())
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.obj")
            ge_model.write_obj(path, [p for p in m.parts if p.kind == "gun"])
            obj = open(path).read()
            self.assertEqual(obj.count("\nf "), 1)
            self.assertIn("usemtl tex_005", obj)
            self.assertIn("map_Kd tex_005.png", open(path[:-4] + ".mtl").read())

    def test_mirrored(self):
        w, h, px = ge_model.mirrored(2, 1, bytes([1, 0, 0, 0, 2, 0, 0, 0]), 1, 0)
        self.assertEqual((w, h), (4, 1))
        self.assertEqual(px[::4], bytes([1, 2, 2, 1]))


class SoundTest(unittest.TestCase):
    def test_vadpcm_zero_book(self):
        # With all-zero coefficients a sample is its nibble times the scale.
        frame = bytes([0x10]) + bytes([0x12, 0x3F] + [0] * 6)
        pcm = ge_sound.decode_vadpcm(frame, [0] * 16, 2, 1)
        self.assertEqual(pcm[:4], [2, 4, 6, -2])

    def test_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.wav")
            ge_sound.write_wav(path, 16000, [0, 1000, -1000])
            with wave.open(path) as w:
                self.assertEqual((w.getframerate(), w.getnframes()), (16000, 3))


class GunsTest(unittest.TestCase):
    def test_export(self):
        rom = ge_rom.Rom(make_rom())
        tex = ge_guns.Textures(rom)
        with tempfile.TemporaryDirectory() as tmp:
            model, parts = ge_guns.export_model(rom, tex, "Gtest1Z", tmp, "first_person", {"gun"})
            self.assertEqual(len(parts), 1)
            self.assertTrue(os.path.exists(os.path.join(tmp, "tex_005.png")))
            self.assertFalse(os.path.exists(os.path.join(tmp, "tex_701.png")))


if __name__ == "__main__":
    unittest.main()
