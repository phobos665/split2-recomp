"""
tools.ts2pak against archives built here, byte by byte, from the layout the
module documents -- no game files.

Run from the repository root:  py -3 -m pytest tools/tests   (or python3 -m unittest)
"""
import os
import struct
import tempfile
import unittest

from tools import ts2pak


def p8ck(files, align=2048, pad_byte=b"\0"):
    """A P8CK archive: header, file data (aligned), index, names."""
    names = b""
    name_offsets = []
    for n, _ in files:
        name_offsets.append(len(names))
        names += n.encode() + b"\0"
    out = bytearray(20)
    places = []
    for _, data in files:
        while len(out) % align:
            out += pad_byte
        places.append((len(out), len(data)))
        out += data
    while len(out) % 16:
        out += b"\0"
    index_off = len(out)
    for (off, length), noff in zip(places, name_offsets):
        out += struct.pack("<III", noff, length, off)
    names_off = len(out)
    out += names
    struct.pack_into("<4sIIII", out, 0, b"P8CK", index_off, len(files), names_off, len(names))
    return bytes(out)


def p4ck(files, align=2048):
    """A P4CK archive: header, index (60-byte entries), file data."""
    index_len = 60 * len(files)
    out = bytearray(16 + index_len)
    entries = []
    for name, data in files:
        while len(out) % align:
            out += b"\0"
        entries.append((name, len(out), len(data)))
        out += data
    struct.pack_into("<4sII", out, 0, b"P4CK", 16, index_len)
    for i, (name, off, length) in enumerate(entries):
        struct.pack_into("<48sIII", out, 16 + 60 * i, name.encode(), off, length, 7)
    return bytes(out)


FILES = [("textures\\0001.xbt", b"A" * 3000),
         ("ob\\chrs\\chr01.xbr", b"B" * 10),
         ("textures\\0002.xbt", b"C" * 2048)]


class ReadTest(unittest.TestCase):
    def test_p8ck_entries(self):
        pak = ts2pak.read_pak(p8ck(FILES))
        self.assertEqual(pak.kind, "P8CK")
        self.assertEqual([e.name for e in pak.entries], [n for n, _ in FILES])
        self.assertEqual([pak.read(e) for e in pak.entries], [d for _, d in FILES])

    def test_p4ck_entries(self):
        pak = ts2pak.read_pak(p4ck(FILES))
        self.assertEqual(pak.kind, "P4CK")
        self.assertEqual([e.name for e in pak.entries], [n for n, _ in FILES])
        self.assertEqual([pak.read(e) for e in pak.entries], [d for _, d in FILES])
        self.assertEqual({e.unknown for e in pak.entries}, {7})

    def test_rejects_rubbish(self):
        for data in (b"", b"XXXX" + bytes(20), b"P4CK" + struct.pack("<II", 16, 61) + bytes(80)):
            with self.assertRaises(ts2pak.PakError):
                ts2pak.read_pak(data)


class RebuildTest(unittest.TestCase):
    def test_unchanged_rebuild_is_identical(self):
        for build in (p8ck, p4ck):
            data = build(FILES)
            self.assertEqual(ts2pak.build_pak(ts2pak.read_pak(data)), data, build.__name__)

    def test_nonzero_padding_survives(self):
        data = p8ck(FILES, pad_byte=b"\xCD")
        self.assertEqual(ts2pak.build_pak(ts2pak.read_pak(data)), data)

    def test_trailing_bytes_survive(self):
        data = p4ck(FILES) + bytes(4096)
        self.assertEqual(ts2pak.build_pak(ts2pak.read_pak(data)), data)

    def _replace(self, build, name, new):
        old = build(FILES)
        out = ts2pak.build_pak(ts2pak.read_pak(old), {name: new})
        return old, ts2pak.read_pak(out)

    def test_grown_file_moves_what_follows_aligned(self):
        for build in (p8ck, p4ck):
            old, pak = self._replace(build, "textures/0001.xbt", b"Z" * 5000)
            got = {e.name: pak.read(e) for e in pak.entries}
            self.assertEqual(got["textures\\0001.xbt"], b"Z" * 5000)
            self.assertEqual(got["ob\\chrs\\chr01.xbr"], b"B" * 10)
            self.assertEqual(got["textures\\0002.xbt"], b"C" * 2048)
            for e in pak.entries:
                self.assertEqual(e.offset % 2048, 0, (build.__name__, e.name))

    def test_shrunk_file_moves_nothing_and_leaves_no_old_bytes(self):
        old, pak = self._replace(p8ck, "TEXTURES/0001.XBT", b"y" * 100)
        before = ts2pak.read_pak(old)
        self.assertEqual([e.offset for e in pak.entries], [e.offset for e in before.entries])
        first = pak.entries[0]
        gap = pak.data[first.offset + first.length:pak.entries[1].offset]
        self.assertNotIn(b"A", gap, "the old file's tail is still in the padding")

    def test_same_size_replacement_changes_only_that_file(self):
        old, pak = self._replace(p4ck, "ob/chrs/chr01.xbr", b"b" * 10)
        self.assertEqual(len(pak.data), len(old))
        diff = [i for i in range(len(old)) if old[i] != pak.data[i]]
        e = pak.entries[1]
        self.assertTrue(all(e.offset <= i < e.offset + 10 for i in diff))

    def test_unknown_file_is_refused(self):
        with self.assertRaises(ts2pak.PakError):
            ts2pak.build_pak(ts2pak.read_pak(p8ck(FILES)), {"textures/9999.xbt": b"x"})

    def test_shared_data_split_only_when_replaced(self):
        data = bytearray(p8ck(FILES))
        pak = ts2pak.read_pak(bytes(data))
        # Point entry 2 at entry 0's data, as an archive that de-duplicates would.
        idx = pak.index_offset + 2 * 12
        struct.pack_into("<II", data, idx + 4, pak.entries[0].length, pak.entries[0].offset)
        shared = ts2pak.read_pak(bytes(data))
        self.assertEqual(ts2pak.build_pak(shared), bytes(data))
        out = ts2pak.read_pak(ts2pak.build_pak(shared, {"textures/0002.xbt": b"new"}))
        got = {e.name: out.read(e) for e in out.entries}
        self.assertEqual(got["textures\\0002.xbt"], b"new")
        self.assertEqual(got["textures\\0001.xbt"], b"A" * 3000)


class CliTest(unittest.TestCase):
    def test_unpack_pack_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "chr.pak")
            open(src, "wb").write(p8ck(FILES))
            unpacked = os.path.join(tmp, "chr")
            self.assertEqual(ts2pak.main(["unpack", src, unpacked]), 0)
            self.assertEqual(open(os.path.join(unpacked, "ob", "chrs", "chr01.xbr"), "rb").read(),
                             b"B" * 10)
            # Edit one file, pack the whole folder with --only-changed.
            open(os.path.join(unpacked, "textures", "0002.xbt"), "wb").write(b"D" * 4097)
            out = os.path.join(tmp, "mods", "data", "chr.pak")
            self.assertEqual(ts2pak.main(["pack", src, unpacked, "-o", out, "--only-changed"]), 0)
            pak = ts2pak.read_pak(open(out, "rb").read())
            self.assertEqual(pak.read(pak.entries[2]), b"D" * 4097)
            self.assertEqual(ts2pak.main(["verify", src, out]), 0)

    def test_unpack_refuses_escaping_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "bad.pak")
            open(src, "wb").write(p4ck([("..\\..\\evil.txt", b"x")]))
            self.assertEqual(ts2pak.main(["unpack", src, os.path.join(tmp, "out")]), 1)
            self.assertFalse(os.path.exists(os.path.join(tmp, "..", "evil.txt")))


if __name__ == "__main__":
    unittest.main()
