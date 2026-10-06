"""
GoldenEye 007 (N64) ROM reader: the files, the textures and the sound bank,
from your own copy of the cartridge. Holds no game data; everything is read
from the ROM you point it at.

    from tools.ge_rom import Rom
    rom = Rom.open("n64/007 - GoldenEye (Europe).n64")
    model = rom.file("Gak47Z")            # unpacked bytes
    w, h, rgba = rom.texture(0x1A)        # RGBA8, top row first

What the ROM holds, and where this finds it (worked out against the PAL
cartridge, 6 Oct 2026, and the public GoldenEye decompilation's notes):

  * Files are compressed with Rare's "1172" wrapper: the bytes 11 72 and
    then a raw deflate stream.
  * The game's data segment is the first large such stream in the first
    2 MB of the ROM. It holds the file table -- 12-byte entries of
    (index, name pointer, ROM offset), index 0 first, ending at
    "ob/ob_end.seg" -- the names themselves, and the texture size table:
    8-byte entries whose low 24 bits of the first word are a texture's
    compressed size, ending at 0xFFFF. The game turns the sizes into
    offsets at start-up (image_entries_load in the decompilation).
  * The textures follow "ob/ob_end.seg" (16 bytes) in the ROM, in texture
    number order, so a texture number from a display list is an index into
    that table.
"""

import struct
import zlib

# Texture formats (the game's own numbering) and compression methods.
RGBA32, RGBA16, RGB24, RGB15, IA16, IA8, IA4, I8, I4, CI8_RGBA16, CI4_RGBA16, CI8_IA16, CI4_IA16 = range(13)
NUM_CHANNELS = [4, 3, 3, 3, 2, 2, 1, 1, 1, 1, 1, 1, 1]
HAS_1BIT_ALPHA = [0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]
CHANNEL_SIZES = [0x100, 0x20, 0x100, 0x20, 0x100, 0x10, 8, 0x100, 0x10, 0x100, 0x10, 0x100, 0x10]
BITS_PER_PIXEL = [0x20, 0x10, 0x18, 0xF, 0x10, 8, 4, 8, 4, 0x10, 0x10, 0x10, 0x10]


def inflate_1172(data):
    """Unpack one Rare 1172 stream."""
    if data[:2] != b"\x11\x72":
        raise ValueError("not a 1172 stream")
    return zlib.decompressobj(-15).decompress(data[2:])


def to_big_endian(rom):
    """Return the ROM in .z64 (big-endian) byte order, whatever it came in."""
    head = rom[:4]
    if head == b"\x80\x37\x12\x40":
        return bytes(rom)
    b = bytearray(rom)
    if head == b"\x37\x80\x40\x12":            # .v64: byte pairs swapped
        b[0::2], b[1::2] = b[1::2], b[0::2]
        return bytes(b)
    if head == b"\x40\x12\x37\x80":            # .n64: words little-endian
        b[0::4], b[1::4], b[2::4], b[3::4] = b[3::4], b[2::4], b[1::4], b[0::4]
        return bytes(b)
    raise ValueError("not an N64 ROM")


class Bits:
    """The game's texture bit reader: most significant bit first."""

    def __init__(self, data, pos=0):
        self.data, self.pos, self.acc, self.count = data, pos, 0, 0

    def read(self, n):
        while self.count < n:
            self.acc = ((self.acc << 8) | self.data[self.pos]) & 0xFFFFFFFFFF
            self.pos += 1
            self.count += 8
        self.count -= n
        return (self.acc >> self.count) & ((1 << n) - 1)


def _huffman(bits, count, chansize):
    """texInflateHuffman: a tree built from 8-bit frequencies, then `count` values."""
    freq = [bits.read(8) for _ in range(chansize)]
    nodes = [[-1, -1] for _ in range(2048)]
    freq += [0] * (2048 - chansize)

    def two_smallest():
        m1 = m2 = 9999
        i1 = i2 = 0
        for i in range(chansize):
            f = freq[i]
            if f < m1:
                if m1 > m2:
                    m1, i1 = f, i
                else:
                    m2, i2 = f, i
            elif f < m2:
                m2, i2 = f, i
        return m1, i1, m2, i2

    # The first search compares the other way round (minfreq2 < minfreq1).
    m1 = m2 = 9999
    i1 = i2 = 0
    for i in range(chansize):
        f = freq[i]
        if f < m1:
            if m2 < m1:
                m1, i1 = f, i
            else:
                m2, i2 = f, i
        elif f < m2:
            m2, i2 = f, i

    leaf = lambda i: nodes[i][0] < 0 and nodes[i][1] < 0
    root = 0
    while True:
        s = freq[i1] + freq[i2] or 1
        freq[i1] = freq[i2] = 9999
        if leaf(i1):
            nodes[i1][0] = i1 + 10000
            root = i1
            freq[i1] = s
            nodes[i1][1] = i2 + 10000 if leaf(i2) else i2
        elif leaf(i2):
            nodes[i2][0] = i2 + 10000
            root = i2
            freq[i2] = s
            nodes[i2][1] = i1 + 10000 if leaf(i1) else i1
        else:
            root = 0
            while nodes[root][0] >= 0 or nodes[root][1] >= 0 or freq[root] < 9999:
                root += 1
            freq[root] = s
            nodes[root][0], nodes[root][1] = i1, i2
        m1, i1, m2, i2 = two_smallest()
        if m1 == 9999 or m2 == 9999:
            break

    out = [0] * count
    for i in range(count):
        v = root
        while v < 10000:
            v = nodes[v][bits.read(1)]
        out[i] = v - 10000
    return out


def _rle(bits, count):
    """texInflateRle: literals and back-references in fixed-size blocks."""
    btsize, rlsize, blocksize = bits.read(3), bits.read(3), bits.read(4)
    cost, fudge = btsize + rlsize + blocksize + 1, 0
    while cost > 0:
        cost -= blocksize + 1
        fudge += 1
    out = []
    while len(out) < count:
        if bits.read(1) == 0:
            out.append(bits.read(blocksize))
        else:
            start = len(out) - bits.read(btsize) - 1
            run = bits.read(rlsize) + fudge
            for i in range(start, start + run):
                out.append(out[i])
            out.append(bits.read(blocksize))
    return out[:count]


def _blur(px, width, height, method, chansize):
    for y in range(height):
        for x in range(width):
            i = y * width + x
            cur = px[i] + chansize * 2
            left = px[i - 1] if x > 0 else 0
            above = px[i - width] if y > 0 else 0
            al = px[i - width - 1] if x > 0 and y > 0 else 0
            add = [left, above, al, left + above - al, int((above - al) / 2) + left,
                   int((left - al) / 2) + above, (left + above) // 2][method]
            px[i] = (cur + add) % chansize


def _to_rgba(fmt, values):
    """One pixel value in the game's format to (r, g, b, a) 8-bit."""
    if fmt == RGBA32:
        v = values
        return (v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255, v & 255
    if fmt == RGB24:
        v = values
        return (v >> 16) & 255, (v >> 8) & 255, v & 255, 255
    if fmt in (RGBA16, RGB15, CI8_RGBA16, CI4_RGBA16):
        v = values
        c = lambda x: (x << 3) | (x >> 2)
        return c((v >> 11) & 31), c((v >> 6) & 31), c((v >> 1) & 31), 255 if v & 1 else 0
    if fmt in (IA16, CI8_IA16, CI4_IA16):
        return values >> 8, values >> 8, values >> 8, values & 255
    if fmt == IA8:
        i, a = (values >> 4) * 17, (values & 15) * 17
        return i, i, i, a
    if fmt == IA4:
        i = ((values >> 1) & 7) * 255 // 7
        return i, i, i, 255 if values & 1 else 0
    if fmt == I8:
        return values, values, values, 255
    if fmt == I4:
        return values * 17, values * 17, values * 17, 255
    raise ValueError(fmt)


def decode_texture(data):
    """The first image of a compressed texture as (width, height, RGBA8 bytes)."""
    head = data[0]
    if head & 0x40:
        return _decode_zlib_texture(data[1:])
    bits = Bits(data, 1)
    fmt, width, height, method = bits.read(4), bits.read(8), bits.read(8), bits.read(4)
    n = width * height
    nch = NUM_CHANNELS[fmt]
    if method in (0, 1):
        pixels = _read_uncompressed(bits, fmt, n)
    elif method == 5:
        lut = _lookup(bits, fmt)
        idx_bits = max(len(lut) - 1, 0).bit_length()
        pixels = [lut[bits.read(idx_bits)] if idx_bits else lut[0] for _ in range(n)]
        pixels = _lut_fixup(fmt, pixels)
    elif method in (6, 7):
        lut = _lookup(bits, fmt)
        idx = _huffman(bits, n, len(lut)) if method == 6 else _rle(bits, n)
        pixels = _lut_fixup(fmt, [lut[i] for i in idx])
    else:
        blur = bits.read(3) if method in (8, 9) else None
        if method == 3:
            chans = []
            for _ in range(nch):
                chans += _huffman(bits, n, CHANNEL_SIZES[fmt])
        elif method in (2, 8):
            chans = _huffman(bits, nch * n, CHANNEL_SIZES[fmt])
        elif method in (4, 9):
            chans = _rle(bits, nch * n)
        else:
            raise ValueError(f"texture compression method {method}")
        if blur is not None:
            _blur(chans, width, nch * height, blur, CHANNEL_SIZES[fmt])
        if HAS_1BIT_ALPHA[fmt]:
            # The game keeps the alpha bits three channels in, whatever
            # the format's channel count (IA4 has one).
            chans = (chans + [0] * (3 * n))[:3 * n] + [bits.read(1) for _ in range(n)]
        pixels = _channels(fmt, chans, n)
    rgba = bytearray()
    for v in pixels:
        rgba += bytes(_to_rgba(fmt, v))
    return width, height, bytes(rgba)


def _lookup(bits, fmt):
    count = bits.read(11)
    bpp = BITS_PER_PIXEL[fmt]
    if bpp <= 24:
        return [bits.read(bpp) for _ in range(count)]
    return [(bits.read(24) << 8) | bits.read(bpp - 24) for _ in range(count)]


def _lut_fixup(fmt, pixels):
    if fmt == RGB15:
        return [(v << 1) | 1 for v in pixels]
    return pixels


def _read_uncompressed(bits, fmt, n):
    if fmt == RGBA32:
        return [(bits.read(16) << 16) | bits.read(16) for _ in range(n)]
    if fmt == RGB24:
        return [bits.read(24) for _ in range(n)]
    if fmt in (RGBA16, IA16):
        return [bits.read(16) for _ in range(n)]
    if fmt == RGB15:
        return [(bits.read(15) << 1) | 1 for _ in range(n)]
    if fmt in (IA8, I8):
        return [bits.read(8) for _ in range(n)]
    if fmt in (IA4, I4):
        return [bits.read(4) for _ in range(n)]
    raise ValueError(fmt)


def _channels(fmt, c, n):
    """texChannelsToPixels, one value per pixel instead of packed rows."""
    if fmt == RGBA32:
        return [c[i] << 24 | c[i + n] << 16 | c[i + 2 * n] << 8 | c[i + 3 * n] for i in range(n)]
    if fmt == RGB24:
        return [c[i] << 16 | c[i + n] << 8 | c[i + 2 * n] for i in range(n)]
    if fmt == RGBA16:
        return [c[i] << 11 | c[i + n] << 6 | c[i + 2 * n] << 1 | c[i + 3 * n] for i in range(n)]
    if fmt == RGB15:
        return [c[i] << 11 | c[i + n] << 6 | c[i + 2 * n] << 1 | 1 for i in range(n)]
    if fmt == IA16:
        return [c[i] << 8 | c[i + n] for i in range(n)]
    if fmt == IA8:
        return [c[i] << 4 | c[i + n] for i in range(n)]
    if fmt == IA4:
        # Three bits of intensity, the 1-bit alpha after the three channels.
        return [c[i] << 1 | c[i + 3 * n] for i in range(n)]
    if fmt in (I8, I4):
        return c[:n]
    raise ValueError(fmt)


def _decode_zlib_texture(data):
    """texInflateZlib: a palette, then each image's palette indices, deflated."""
    fmt, ncol = data[0], data[1] + 1
    pal = [struct.unpack_from(">H", data, 2 + 2 * i)[0] for i in range(ncol)]
    p = 2 + 2 * ncol
    width, height = data[p], data[p + 1]
    raw = inflate_1172(data[p + 2:])
    n = width * height
    if fmt in (CI8_RGBA16, CI8_IA16):
        idx = list(raw[:n])
    else:
        idx = []
        for b in raw[:(n + 1) // 2]:
            idx += [b >> 4, b & 15]
        idx = idx[:n]
    rgba = bytearray()
    for i in idx:
        rgba += bytes(_to_rgba(fmt, pal[i] if i < ncol else 0))
    return width, height, bytes(rgba)


class Rom:
    def __init__(self, data):
        self.data = to_big_endian(data)
        self._find_data_segment()
        self._read_file_table()
        self._read_texture_table()

    @classmethod
    def open(cls, path):
        with open(path, "rb") as f:
            return cls(f.read())

    def _find_data_segment(self):
        d, i = self.data, 0x1000
        while True:
            i = d.find(b"\x11\x72", i, 0x200000)
            if i < 0:
                raise ValueError("no data segment found; is this GoldenEye?")
            try:
                out = inflate_1172(d[i:i + 0x100000])
                if len(out) > 0x20000:
                    self.seg = out
                    return
            except zlib.error:
                pass
            i += 2

    def _read_file_table(self):
        seg = self.seg
        end = seg.find(b"ob/ob_end.seg\0")
        if end < 0:
            raise ValueError("no file table found")
        # The table is the longest run of entries numbered 0, 1, 2, ... with
        # rising ROM offsets whose last entry names "ob/ob_end.seg" (which
        # gives the base the name pointers are relative to) and whose other
        # names all resolve to text.
        best = None
        for o in range(12, len(seg) - 36, 4):
            if struct.unpack_from(">I", seg, o)[0] != 1 or struct.unpack_from(">I", seg, o - 12)[0] != 0:
                continue
            ents = [struct.unpack_from(">III", seg, o - 12)]
            while o + 12 * len(ents) <= len(seg) - 12:
                e = struct.unpack_from(">III", seg, o - 12 + 12 * len(ents))
                if e[0] != len(ents) or e[2] < ents[-1][2] or e[1] < 0x80000000:
                    break
                ents.append(e)
            base = ents[-1][1] - end
            if len(ents) >= 3 and (best is None or len(ents) > len(best[2])) \
                    and all(self._is_name(seg, p - base) for _, p, _ in ents[1:]):
                best = (o - 12, base, ents)
        if best is None:
            raise ValueError("no file table found")
        self.table, self.name_base, ents = best
        self.files = {}
        for k, (_, ptr, off) in enumerate(ents):
            p = ptr - self.name_base
            name = seg[p:seg.index(b"\0", p)].decode("ascii") if ptr else ""
            size = ents[k + 1][2] - off if k + 1 < len(ents) else 16
            if name:
                self.files[name] = (off, size)
        self.images_start = self.files["ob/ob_end.seg"][0] + 16

    @staticmethod
    def _is_name(seg, at):
        if not 0 < at < len(seg):
            return False
        end = seg.find(b"\0", at)
        return 0 < end - at < 64 and all(32 < c < 127 for c in seg[at:end])

    def _read_texture_table(self):
        seg = self.seg
        # 8-byte entries; the sizes of the first textures are all small
        # and the run ends at 0xFFFF. The longest such run is the table.
        best = (0, 0)
        o = 0
        while o < len(seg) - 8:
            n = 0
            while o + 8 * n + 8 <= len(seg):
                v = struct.unpack_from(">I", seg, o + 8 * n)[0] & 0xFFFFFF
                if v == 0xFFFF or not (0 < v < 0x8000):
                    break
                n += 1
            if n > best[1] and o + 8 * n + 4 <= len(seg) and \
                    struct.unpack_from(">I", seg, o + 8 * n)[0] & 0xFFFFFF == 0xFFFF:
                best = (o, n)
            o += 8 * n + 4 if n > 16 else 4
        if best[1] < 1000:
            raise ValueError("no texture table found")
        o, n = best
        self.tex_offsets = []
        at = self.images_start
        for k in range(n):
            self.tex_offsets.append(at)
            at += struct.unpack_from(">I", seg, o + 8 * k)[0] & 0xFFFFFF
        self.tex_offsets.append(at)

    def file(self, name):
        """A file from the ROM, unpacked if it is compressed."""
        off, size = self.files[name]
        raw = self.data[off:off + size]
        return inflate_1172(raw) if raw[:2] == b"\x11\x72" else raw

    def texture(self, num):
        """Texture `num` as (width, height, RGBA8 bytes, top row first)."""
        a, b = self.tex_offsets[num], self.tex_offsets[num + 1]
        return decode_texture(self.data[a:b])

    @property
    def texture_count(self):
        return len(self.tex_offsets) - 1
