"""Convert TimeSplitters 2's .xbt textures (Xbox) to and from DDS and PNG.

An .xbt is a 128-byte header and then the texel data, whole mip chain, in the
Xbox's own packing: the game hands the bytes after the header to D3D as they
are. docs/formats/xbt.md describes the header and says which parts were
measured on the disc and which were read from the game's loader.

  format 0  DXT1                      D3D 0x0C   (on the disc)
  format 1  DXT3                      D3D 0x0E   (on the disc)
  format 2  A8R8G8B8, swizzled        D3D 0x06   (on the disc)
  format 3  R5G6B5, swizzled          D3D 0x05   (the loader knows it; no file uses it)

  python3 -I tools/ts2xbt.py info   tex.xbt
  python3 -I tools/ts2xbt.py export tex.xbt tex.dds         # every mip level, unswizzled
  python3 -I tools/ts2xbt.py export tex.xbt tex.png         # level 0 as RGBA (--level N)
  python3 -I tools/ts2xbt.py import tex.xbt edited.png new.xbt
  python3 -I tools/ts2xbt.py verify unpacked/chr.pak        # xbt -> dds -> xbt, byte for byte

`import` keeps the original header and format. A DDS already in that format
(DXT1, DXT3, A8R8G8B8, R5G6B5) is taken as it is, with its own mip levels; any
other DDS, and every PNG, is decoded to RGBA and encoded again, and missing mip
levels are made by a 2x2 box filter. Sizes must be powers of two.
"""

import argparse
import os
import struct
import sys
import zlib
from array import array

HEADER_SIZE = 0x80

FMT_DXT1, FMT_DXT3, FMT_ARGB, FMT_RGB565 = 0, 1, 2, 3
FORMATS = {
    # code: (name, D3D format the loader asks for, block or texel bytes, compressed)
    FMT_DXT1: ("DXT1", 0x0C, 8, True),
    FMT_DXT3: ("DXT3", 0x0E, 16, True),
    FMT_ARGB: ("A8R8G8B8 swizzled", 0x06, 4, False),
    FMT_RGB565: ("R5G6B5 swizzled", 0x05, 2, False),
}

# The executable lists 21 detail textures (strings at 0x211892.. in the PAL
# default.xbe). Header field 0x18 is read here as an index into that list
# (-1 for none; 0-19 on the disc, and 0x1C/0x20 are zero exactly when it is
# -1). Inferred from the data, not read from code: see docs/formats/xbt.md.
DETAIL_TEXTURES = [
    "xbnullchar", "ashphalt_det_xb_dtl", "plaster_det_xb_dtl",
    "stone_floor_detail_xb_dtl", "chic_metal_xb_dtl", "scrap_del_xb_dtl",
    "yrdmet_xb_dtl", "rope_det_xb_dtl", "mex_yucdet_xb_dtl", "mex_wood_de_xb_dtl",
    "mex_mulch_dtl", "sandtest1_xb_dtl", "mex_rock_xb_dtl", "wfall1_xb_dtl",
    "bedrock_detail_xb_dtl", "ground_detail_xb_dtl", "moss1_xb_dtl",
    "tg_cbrd_det_xb_dtl", "grass2_det_xb_dtl", "tg_rock1_xb_dtl", "brickdl",
]


class XbtError(Exception):
    pass


def is_pow2(n):
    return n > 0 and n & (n - 1) == 0


# ---------------------------------------------------------------- header

class Header:
    """The fields of the 128-byte header that are understood. `raw` keeps the
    whole header so that import can write back what it does not change."""

    def __init__(self, raw):
        if len(raw) < HEADER_SIZE:
            raise XbtError("file is %d bytes, shorter than the %d-byte header" % (len(raw), HEADER_SIZE))
        self.raw = bytes(raw[:HEADER_SIZE])
        (self.width, self.height, self.used_width, self.used_height,
         self.last_level, self.format) = struct.unpack_from("<6I", raw, 0)
        self.detail_index, = struct.unpack_from("<i", raw, 0x18)
        self.detail_scale_u, self.detail_scale_v = struct.unpack_from("<2f", raw, 0x1C)

    @property
    def levels(self):
        return self.last_level + 1

    def rebuilt(self, width, height, levels):
        """The original header with the size and level fields replaced. The
        used size keeps its fraction of the texture when the size changes."""
        h = bytearray(self.raw)
        uw, uh = self.used_width, self.used_height
        if width != self.width:
            uw = max(1, (uw * width + self.width // 2) // self.width)
        if height != self.height:
            uh = max(1, (uh * height + self.height // 2) // self.height)
        struct.pack_into("<5I", h, 0, width, height, uw, uh, levels - 1)
        return bytes(h)


def level_sizes(fmt, width, height, levels):
    """(width, height, bytes) of each level, as the chain is packed."""
    name, _, unit, compressed = FORMATS[fmt]
    out = []
    w, h = width, height
    for _ in range(levels):
        if compressed:
            n = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * unit
        else:
            n = w * h * unit
        out.append((w, h, n))
        w, h = max(1, w // 2), max(1, h // 2)
    return out


def full_levels(width, height):
    return max(width, height).bit_length()


class Xbt:
    def __init__(self, data):
        self.header = Header(data)
        hd = self.header
        if hd.format not in FORMATS:
            raise XbtError("format %d is not one the loader knows (0-3)" % hd.format)
        if not (is_pow2(hd.width) and is_pow2(hd.height)):
            raise XbtError("size %dx%d is not a power of two" % (hd.width, hd.height))
        self.sizes = level_sizes(hd.format, hd.width, hd.height, hd.levels)
        need = sum(n for _, _, n in self.sizes)
        body = data[HEADER_SIZE:]
        if len(body) < need:
            raise XbtError("data is %d bytes, the %d-level chain needs %d" % (len(body), hd.levels, need))
        self.trailing = bytes(body[need:])
        self.levels = []  # bytes of each level, in the file's packing (swizzled where it is)
        pos = 0
        for _, _, n in self.sizes:
            self.levels.append(bytes(body[pos:pos + n]))
            pos += n

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            return cls(f.read())

    def linear_levels(self):
        """Each level in row order (unswizzled), still in the file's format."""
        fmt = self.header.format
        if FORMATS[fmt][3]:
            return list(self.levels)
        return [unswizzle(lv, w, h, FORMATS[fmt][2]) for lv, (w, h, _) in zip(self.levels, self.sizes)]


# ---------------------------------------------------------------- swizzle
# The Xbox swizzle interleaves the bits of x and y, x first, and once the
# smaller side has run out of bits the larger one takes the rest.

_swizzle_cache = {}


def swizzle_table(width, height):
    """table[y * width + x] = index of texel (x, y) in the swizzled level."""
    key = (width, height)
    t = _swizzle_cache.get(key)
    if t is not None:
        return t
    mask_x = mask_y = 0
    bit = out = 1
    while bit < width or bit < height:
        if bit < width:
            mask_x |= out
            out <<= 1
        if bit < height:
            mask_y |= out
            out <<= 1
        bit <<= 1

    def offsets(n, mask):
        res, v = [], 0
        for _ in range(n):
            res.append(v)
            v = (v - mask) & mask  # the next value that uses only mask's bits
        return res

    ox, oy = offsets(width, mask_x), offsets(height, mask_y)
    t = [yo | xo for yo in oy for xo in ox]
    if len(_swizzle_cache) > 64:
        _swizzle_cache.clear()
    _swizzle_cache[key] = t
    return t


def _texels(data, unit):
    a = array("I" if unit == 4 else "H")
    a.frombytes(bytes(data))
    if sys.byteorder != "little":
        a.byteswap()
    return a


def _texel_bytes(a):
    if sys.byteorder != "little":
        a = array(a.typecode, a)
        a.byteswap()
    return a.tobytes()


def unswizzle(data, width, height, unit):
    src = _texels(data, unit)
    t = swizzle_table(width, height)
    return _texel_bytes(array(src.typecode, [src[s] for s in t]))


def swizzle(data, width, height, unit):
    src = _texels(data, unit)
    t = swizzle_table(width, height)
    dst = array(src.typecode, bytes(len(data)))
    for i, s in enumerate(t):
        dst[s] = src[i]
    return _texel_bytes(dst)


# ---------------------------------------------------------------- pixels
# RGBA images are (width, height, bytearray of r,g,b,a per texel, rows top down).

def _565(c):
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def _dxt_colours(c0, c1, four):
    a, b = _565(c0), _565(c1)
    if four:
        return [a + (255,), b + (255,),
                tuple((2 * x + y + 1) // 3 for x, y in zip(a, b)) + (255,),
                tuple((x + 2 * y + 1) // 3 for x, y in zip(a, b)) + (255,)]
    return [a + (255,), b + (255,), tuple((x + y) // 2 for x, y in zip(a, b)) + (255,), (0, 0, 0, 0)]


def decode_dxt(data, width, height, fmt):
    """DXT1 (fmt 0), DXT3 (1) or DXT5 ('dxt5') to RGBA."""
    out = bytearray(width * height * 4)
    step = 8 if fmt == FMT_DXT1 else 16
    bw, bh = max(1, (width + 3) // 4), max(1, (height + 3) // 4)
    pos = 0
    for by in range(bh):
        for bx in range(bw):
            alpha = None
            if fmt == FMT_DXT3:
                bits = int.from_bytes(data[pos:pos + 8], "little")
                alpha = [((bits >> (4 * i)) & 15) * 17 for i in range(16)]
            elif fmt == "dxt5":
                a0, a1 = data[pos], data[pos + 1]
                bits = int.from_bytes(data[pos + 2:pos + 8], "little")
                if a0 > a1:
                    pal = [a0, a1] + [((7 - i) * a0 + i * a1 + 3) // 7 for i in range(1, 7)]
                else:
                    pal = [a0, a1] + [((5 - i) * a0 + i * a1 + 2) // 5 for i in range(1, 5)] + [0, 255]
                alpha = [pal[(bits >> (3 * i)) & 7] for i in range(16)]
            cpos = pos + step - 8
            c0, c1, idx = struct.unpack_from("<HHI", data, cpos)
            # DXT3/5 colour blocks are always four-colour.
            pal = _dxt_colours(c0, c1, c0 > c1 or fmt != FMT_DXT1)
            for i in range(16):
                x, y = bx * 4 + (i & 3), by * 4 + (i >> 2)
                if x >= width or y >= height:
                    continue
                r, g, b, a = pal[(idx >> (2 * i)) & 3]
                if alpha is not None:
                    a = alpha[i]
                o = (y * width + x) * 4
                out[o:o + 4] = bytes((r, g, b, a))
            pos += step
    return out


def decode_linear(data, width, height, fmt):
    """A level in row order, format 2 or 3, to RGBA."""
    if fmt == FMT_ARGB:
        out = bytearray(data[:width * height * 4])
        out[0::4], out[2::4] = data[2::4], data[0::4]  # b,g,r,a -> r,g,b,a
        return out
    out = bytearray(width * height * 4)
    for i, c in enumerate(_texels(data, 2)):
        out[i * 4:i * 4 + 4] = bytes(_565(c) + (255,))
    return out


def decode_level(xbt, level):
    hd = xbt.header
    w, h, _ = xbt.sizes[level]
    lin = xbt.linear_levels()[level]
    if FORMATS[hd.format][3]:
        return decode_dxt(lin, w, h, hd.format)
    return decode_linear(lin, w, h, hd.format)


def downsample(rgba, width, height):
    """2x2 box filter; a side of 1 stays 1."""
    nw, nh = max(1, width // 2), max(1, height // 2)
    out = bytearray(nw * nh * 4)
    sx, sy = (2 if width > 1 else 1), (2 if height > 1 else 1)
    n = sx * sy
    for y in range(nh):
        for x in range(nw):
            for c in range(4):
                t = 0
                for dy in range(sy):
                    row = (y * sy + dy) * width
                    for dx in range(sx):
                        t += rgba[(row + x * sx + dx) * 4 + c]
                out[(y * nw + x) * 4 + c] = (t + n // 2) // n
    return out


# ---------------------------------------------------------------- DXT encode
# A simple encoder: endpoints are the block's extremes along its principal
# colour axis, each texel takes the nearest palette entry. DXT1 blocks with a
# texel under alpha 128 use the three-colour mode with index 3 transparent.

def _to565(r, g, b):
    return ((min(255, max(0, int(r + 0.5))) * 31 + 127) // 255) << 11 | \
           ((min(255, max(0, int(g + 0.5))) * 63 + 127) // 255) << 5 | \
           ((min(255, max(0, int(b + 0.5))) * 31 + 127) // 255)


def _endpoints(px):
    n = len(px)
    mr = sum(p[0] for p in px) / n
    mg = sum(p[1] for p in px) / n
    mb = sum(p[2] for p in px) / n
    cov = [0.0] * 6
    for r, g, b in px:
        r, g, b = r - mr, g - mg, b - mb
        cov[0] += r * r; cov[1] += r * g; cov[2] += r * b
        cov[3] += g * g; cov[4] += g * b; cov[5] += b * b
    v = (1.0, 1.0, 1.0)
    for _ in range(4):
        v = (cov[0] * v[0] + cov[1] * v[1] + cov[2] * v[2],
             cov[1] * v[0] + cov[3] * v[1] + cov[4] * v[2],
             cov[2] * v[0] + cov[4] * v[1] + cov[5] * v[2])
        m = max(abs(v[0]), abs(v[1]), abs(v[2]))
        if m == 0:
            break
        v = (v[0] / m, v[1] / m, v[2] / m)
    proj = [(p[0] - mr) * v[0] + (p[1] - mg) * v[1] + (p[2] - mb) * v[2] for p in px]
    lo, hi = px[proj.index(min(proj))], px[proj.index(max(proj))]
    return _to565(*hi), _to565(*lo)


def _encode_colour(block, three_colour):
    """block: 16 (r,g,b,a). Returns 8 bytes."""
    opaque = [p[:3] for p in block if not (three_colour and p[3] < 128)]
    if not opaque:
        return struct.pack("<HHI", 0, 0xFFFF, 0xFFFFFFFF)
    c0, c1 = _endpoints(opaque)
    if three_colour:
        if c0 > c1:
            c0, c1 = c1, c0
    elif c0 < c1:
        c0, c1 = c1, c0
    if c0 == c1 and not three_colour:
        return struct.pack("<HHI", c0, c1, 0)
    pal = _dxt_colours(c0, c1, not three_colour)
    choices = pal[:3] if three_colour else pal
    idx = 0
    for i, (r, g, b, a) in enumerate(block):
        if three_colour and a < 128:
            k = 3
        else:
            best = None
            for j, (pr, pg, pb, _) in enumerate(choices):
                d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                if best is None or d < best:
                    best, k = d, j
        idx |= k << (2 * i)
    return struct.pack("<HHI", c0, c1, idx)


def encode_dxt(rgba, width, height, fmt):
    out = bytearray()
    bw, bh = max(1, (width + 3) // 4), max(1, (height + 3) // 4)
    for by in range(bh):
        for bx in range(bw):
            block = []
            for i in range(16):
                x = min(bx * 4 + (i & 3), width - 1)
                y = min(by * 4 + (i >> 2), height - 1)
                o = (y * width + x) * 4
                block.append(tuple(rgba[o:o + 4]))
            if fmt == FMT_DXT3:
                bits = 0
                for i, p in enumerate(block):
                    bits |= ((p[3] * 15 + 127) // 255) << (4 * i)
                out += bits.to_bytes(8, "little") + _encode_colour(block, False)
            else:
                out += _encode_colour(block, any(p[3] < 128 for p in block))
    return bytes(out)


def encode_linear(rgba, width, height, fmt):
    """RGBA to a level in row order, format 2 or 3."""
    if fmt == FMT_ARGB:
        out = bytearray(rgba)
        out[0::4], out[2::4] = rgba[2::4], rgba[0::4]
        return bytes(out)
    a = array("H", (_to565(rgba[i], rgba[i + 1], rgba[i + 2]) for i in range(0, len(rgba), 4)))
    return _texel_bytes(a)


def encode_level(rgba, width, height, fmt):
    """RGBA to a level in the file's packing (swizzled where the format is)."""
    if FORMATS[fmt][3]:
        return encode_dxt(rgba, width, height, fmt)
    return swizzle(encode_linear(rgba, width, height, fmt), width, height, FORMATS[fmt][2])


# ---------------------------------------------------------------- DDS

DDSD_CAPS, DDSD_HEIGHT, DDSD_WIDTH, DDSD_PITCH = 0x1, 0x2, 0x4, 0x8
DDSD_PIXELFORMAT, DDSD_MIPMAPCOUNT, DDSD_LINEARSIZE = 0x1000, 0x20000, 0x80000
DDPF_ALPHAPIXELS, DDPF_FOURCC, DDPF_RGB, DDPF_LUMINANCE = 0x1, 0x4, 0x40, 0x20000
DDSCAPS_COMPLEX, DDSCAPS_TEXTURE, DDSCAPS_MIPMAP = 0x8, 0x1000, 0x400000

# Uncompressed pixel formats: (bits, r, g, b, a masks).
DDS_MASKS = {
    FMT_ARGB: (32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000),
    FMT_RGB565: (16, 0xF800, 0x07E0, 0x001F, 0),
}
DDS_FOURCC = {FMT_DXT1: b"DXT1", FMT_DXT3: b"DXT3"}


def write_dds(fmt, width, height, levels):
    """levels: each mip level in row order, in fmt's own bytes."""
    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    caps = DDSCAPS_TEXTURE
    if len(levels) > 1:
        flags |= DDSD_MIPMAPCOUNT
        caps |= DDSCAPS_COMPLEX | DDSCAPS_MIPMAP
    if fmt in DDS_FOURCC:
        flags |= DDSD_LINEARSIZE
        pitch = len(levels[0])
        pf = struct.pack("<II4s5I", 32, DDPF_FOURCC, DDS_FOURCC[fmt], 0, 0, 0, 0, 0)
    else:
        bits, r, g, b, a = DDS_MASKS[fmt]
        flags |= DDSD_PITCH
        pitch = width * bits // 8
        pf = struct.pack("<II4s5I", 32, DDPF_RGB | (DDPF_ALPHAPIXELS if a else 0), b"\0" * 4, bits, r, g, b, a)
    hdr = struct.pack("<7I44x", 124, flags, height, width, pitch, 0, len(levels)) + pf + \
        struct.pack("<5I", caps, 0, 0, 0, 0)
    return b"DDS " + hdr + b"".join(levels)


class Dds:
    """A 2D DDS: width, height, kind and the bytes of each level. kind is a
    format code (0-3) when the DDS holds exactly what an .xbt of that format
    holds, else 'dxt5' or ('mask', bits, r, g, b, a) or 'rgba', which are decoded."""

    DXGI = {71: FMT_DXT1, 72: FMT_DXT1, 74: FMT_DXT3, 75: FMT_DXT3, 77: "dxt5", 78: "dxt5",
            87: FMT_ARGB, 91: FMT_ARGB, 28: "rgba", 29: "rgba",
            88: ("mask", 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0)}

    def __init__(self, data):
        if data[:4] != b"DDS " or len(data) < 128:
            raise XbtError("not a DDS file")
        size, flags, self.height, self.width, _, depth, mips = struct.unpack_from("<7I", data, 4)
        pf_flags, fourcc, bits, rm, gm, bm, am = struct.unpack_from("<I4s5I", data, 80)
        caps2, = struct.unpack_from("<I", data, 112)
        if caps2 & 0x200 or caps2 & 0x200000:
            raise XbtError("a cube or volume DDS cannot become an .xbt")
        pos = 128
        if pf_flags & DDPF_FOURCC and fourcc == b"DX10":
            dxgi, dim, _, array_size = struct.unpack_from("<4I", data, 128)
            pos += 20
            if dxgi not in self.DXGI:
                raise XbtError("DXGI format %d is not supported" % dxgi)
            self.kind = self.DXGI[dxgi]
        elif pf_flags & DDPF_FOURCC:
            k = {b"DXT1": FMT_DXT1, b"DXT2": FMT_DXT3, b"DXT3": FMT_DXT3,
                 b"DXT4": "dxt5", b"DXT5": "dxt5"}.get(fourcc)
            if k is None:
                raise XbtError("DDS FourCC %r is not supported" % fourcc)
            self.kind = k
        elif pf_flags & (DDPF_RGB | DDPF_LUMINANCE):
            if not pf_flags & DDPF_ALPHAPIXELS:
                am = 0
            if pf_flags & DDPF_LUMINANCE:
                gm = bm = rm
            masks = (bits, rm, gm, bm, am)
            if masks == DDS_MASKS[FMT_ARGB]:
                self.kind = FMT_ARGB
            elif masks == DDS_MASKS[FMT_RGB565]:
                self.kind = FMT_RGB565
            elif bits in (8, 16, 24, 32):
                self.kind = ("mask",) + masks
            else:
                raise XbtError("%d-bit DDS is not supported" % bits)
        else:
            raise XbtError("DDS pixel format flags %#x are not supported" % pf_flags)
        count = mips if (flags & DDSD_MIPMAPCOUNT and mips) else 1
        self.levels = []
        w, h = self.width, self.height
        for _ in range(count):
            n = self.level_bytes(w, h)
            if pos + n > len(data):
                if not self.levels:
                    raise XbtError("DDS is shorter than its first level")
                break  # keep the levels that are there
            self.levels.append(data[pos:pos + n])
            pos += n
            w, h = max(1, w // 2), max(1, h // 2)

    def level_bytes(self, w, h):
        k = self.kind
        if k in (FMT_DXT1, FMT_DXT3, "dxt5"):
            return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * (8 if k == FMT_DXT1 else 16)
        if k == FMT_ARGB or k == "rgba":
            return w * h * 4
        if k == FMT_RGB565:
            return w * h * 2
        return w * h * (k[1] // 8)

    def rgba(self, level):
        w, h = max(1, self.width >> level), max(1, self.height >> level)
        k, data = self.kind, self.levels[level]
        if k in (FMT_DXT1, FMT_DXT3, "dxt5"):
            return decode_dxt(data, w, h, k)
        if k in (FMT_ARGB, FMT_RGB565):
            return decode_linear(data, w, h, k)
        if k == "rgba":
            return bytearray(data)
        _, bits, *masks = k
        nb = bits // 8
        out = bytearray(w * h * 4)
        for i in range(w * h):
            v = int.from_bytes(data[i * nb:i * nb + nb], "little")
            for c, m in enumerate(masks):
                if not m:
                    out[i * 4 + c] = 255
                    continue
                shift = (m & -m).bit_length() - 1
                top = m >> shift
                out[i * 4 + c] = ((v & m) >> shift) * 255 // top
        return out


# ---------------------------------------------------------------- PNG

def write_png(width, height, rgba):
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def read_png(data):
    """Returns (width, height, rgba). Non-interlaced; any colour type; bit
    depth 8, 16, or 1/2/4 for grey and palette images."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise XbtError("not a PNG file")
    pos, idat, plte, trns = 8, bytearray(), None, None
    while pos < len(data):
        n, tag = struct.unpack_from(">I4s", data, pos)
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if tag == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif tag == b"PLTE":
            plte = body
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
    if interlace:
        raise XbtError("interlaced PNG is not supported; save it without interlacing")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    bits = channels * depth
    bpp = max(1, bits // 8)
    stride = (width * bits + 7) // 8
    raw = zlib.decompress(bytes(idat))
    rows, prev, p = [], bytearray(stride), 0
    for _ in range(height):
        ft = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ft == 1:
                line[i] = (line[i] + a) & 255
            elif ft == 2:
                line[i] = (line[i] + b) & 255
            elif ft == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif ft == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    out = bytearray(width * height * 4)
    for y, line in enumerate(rows):
        if depth < 8:
            per = 8 // depth
            vals = [(line[x // per] >> (8 - depth * (x % per + 1))) & ((1 << depth) - 1) for x in range(width)]
        elif depth == 16:
            vals = line[0::2]
        else:
            vals = line
        for x in range(width):
            o = (y * width + x) * 4
            if ctype == 3:
                i = vals[x]
                px = tuple(plte[i * 3:i * 3 + 3]) + ((trns[i] if trns and i < len(trns) else 255),)
            elif ctype in (0, 4):
                g = vals[x * channels]
                if depth < 8:
                    g = g * 255 // ((1 << depth) - 1)
                px = (g, g, g, vals[x * 2 + 1] if ctype == 4 else 255)
            else:
                px = tuple(vals[x * channels:x * channels + 3]) + ((vals[x * 4 + 3],) if ctype == 6 else (255,))
            out[o:o + 4] = bytes(px)
    return width, height, out


# ---------------------------------------------------------------- conversions

def export_dds(xbt):
    hd = xbt.header
    return write_dds(hd.format, hd.width, hd.height, xbt.linear_levels())


def import_image(orig, src_bytes, kind):
    """Builds a new .xbt from the original's header and an edited image.
    kind: 'dds' or 'png'. Returns (bytes, notes)."""
    hd = orig.header
    fmt = hd.format
    notes = []
    native = []      # levels already in the file's packing
    rgba_last = None
    if kind == "dds":
        dds = Dds(src_bytes)
        w, h = dds.width, dds.height
        if dds.kind == fmt:
            for i, lv in enumerate(dds.levels):
                if FORMATS[fmt][3]:
                    native.append(bytes(lv))
                else:
                    native.append(swizzle(lv, max(1, w >> i), max(1, h >> i), FORMATS[fmt][2]))
            if len(native) < full_levels(w, h):
                rgba_last = dds.rgba(len(native) - 1)
        else:
            notes.append("DDS format is not the .xbt's %s: re-encoded" % FORMATS[fmt][0])
            rgba_last = dds.rgba(0)
            native.append(encode_level(rgba_last, w, h, fmt))
    else:
        w, h, rgba_last = read_png(src_bytes)
        native.append(encode_level(rgba_last, w, h, fmt))
    if not (is_pow2(w) and is_pow2(h)):
        raise XbtError("%dx%d: an .xbt's sides must be powers of two" % (w, h))
    if (w, h) != (hd.width, hd.height):
        notes.append("size changed from %dx%d to %dx%d" % (hd.width, hd.height, w, h))
    # The same number of levels as the original: a full chain stays a full
    # chain at a new size, and a texture without mips (some have one level) stays so.
    if hd.levels >= full_levels(hd.width, hd.height):
        total = full_levels(w, h)
    else:
        total = min(hd.levels, full_levels(w, h))
    if len(native) < total:
        notes.append("mip levels %d-%d made with a box filter" % (len(native), total - 1))
        lw, lh = max(1, w >> (len(native) - 1)), max(1, h >> (len(native) - 1))
        while len(native) < total:
            rgba_last = downsample(rgba_last, lw, lh)
            lw, lh = max(1, lw // 2), max(1, lh // 2)
            native.append(encode_level(rgba_last, lw, lh, fmt))
    native = native[:total]
    if orig.trailing:
        notes.append("%d bytes after the original chain were dropped" % len(orig.trailing))
    return hd.rebuilt(w, h, total) + b"".join(native), notes


def new_xbt(rgba, width, height, fmt=None):
    """A new .xbt from an RGBA picture, with no original to copy: DXT1, or
    DXT3 when any texel's alpha is under 255; the whole mip chain (box
    filter); no detail texture; display size = texture size. These are the
    commonest header values on the disc (docs/formats/xbt.md)."""
    if not (is_pow2(width) and is_pow2(height)):
        raise XbtError("%dx%d: an .xbt's sides must be powers of two" % (width, height))
    if fmt is None:
        fmt = FMT_DXT3 if min(rgba[3::4]) < 255 else FMT_DXT1
    total = full_levels(width, height)
    hdr = bytearray(HEADER_SIZE)
    struct.pack_into("<6Ii2f", hdr, 0, width, height, width, height, total - 1, fmt, -1, 0.0, 0.0)
    out = [bytes(hdr), encode_level(rgba, width, height, fmt)]
    w, h = width, height
    for _ in range(total - 1):
        rgba = downsample(rgba, w, h)
        w, h = max(1, w // 2), max(1, h // 2)
        out.append(encode_level(rgba, w, h, fmt))
    return b"".join(out)


def kind_of(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".dds", ".png"):
        raise XbtError("%s: expected a .dds or .png" % path)
    return ext[1:]


# ---------------------------------------------------------------- commands

def cmd_info(args):
    data = open(args.xbt, "rb").read()
    hd = Header(data)
    print("%s: %d bytes" % (args.xbt, len(data)))
    print("  0x00 width          %d" % hd.width)
    print("  0x04 height         %d" % hd.height)
    used = "" if (hd.used_width, hd.used_height) == (hd.width, hd.height) else "  (image fills part of the texture)"
    print("  0x08 used width     %d%s" % (hd.used_width, used))
    print("  0x0C used height    %d" % hd.used_height)
    print("  0x10 last mip level %d  (%d levels)" % (hd.last_level, hd.levels))
    name = FORMATS.get(hd.format, ("unknown", None))[0]
    d3d = FORMATS[hd.format][1] if hd.format in FORMATS else None
    print("  0x14 format         %d  %s%s" % (hd.format, name, "  (D3D 0x%02X)" % d3d if d3d is not None else ""))
    if hd.detail_index < 0:
        print("  0x18 detail texture none (-1)")
    else:
        dn = DETAIL_TEXTURES[hd.detail_index] if hd.detail_index < len(DETAIL_TEXTURES) else "?"
        print("  0x18 detail texture %d  (%s)" % (hd.detail_index, dn))
    print("  0x1C detail scale u %g" % hd.detail_scale_u)
    print("  0x20 detail scale v %g" % hd.detail_scale_v)
    rest = data[0x24:HEADER_SIZE]
    print("  0x24-0x7F           %s" % ("zero" if not any(rest) else "NOT ZERO: " + rest.hex()))
    try:
        xbt = Xbt(data)
    except XbtError as e:
        print("  data: %s" % e)
        return 1
    pos = HEADER_SIZE
    for i, (w, h, n) in enumerate(xbt.sizes):
        print("  level %2d  %4dx%-4d  %7d bytes at 0x%X" % (i, w, h, n, pos))
        pos += n
    if xbt.trailing:
        print("  %d bytes after the chain" % len(xbt.trailing))
    return 0


def cmd_export(args):
    xbt = Xbt.load(args.xbt)
    kind = kind_of(args.out)
    if kind == "dds":
        out = export_dds(xbt)
    else:
        if not 0 <= args.level < len(xbt.levels):
            raise XbtError("level %d: the file has levels 0-%d" % (args.level, len(xbt.levels) - 1))
        w, h, _ = xbt.sizes[args.level]
        out = write_png(w, h, decode_level(xbt, args.level))
    with open(args.out, "wb") as f:
        f.write(out)
    return 0


def cmd_import(args):
    orig = Xbt.load(args.original)
    out, notes = import_image(orig, open(args.edited, "rb").read(), kind_of(args.edited))
    with open(args.out, "wb") as f:
        f.write(out)
    for n in notes:
        print("%s: %s" % (args.out, n))
    return 0


def verify_one(path):
    """Returns None when xbt -> dds -> xbt gives the same bytes, else a reason."""
    data = open(path, "rb").read()
    try:
        xbt = Xbt(data)
        out, _ = import_image(xbt, export_dds(xbt), "dds")
    except XbtError as e:
        return str(e)
    if out == data:
        return None
    if len(out) != len(data):
        return "round trip is %d bytes, the file %d" % (len(out), len(data))
    first = next(i for i in range(len(out)) if out[i] != data[i])
    return "round trip differs first at 0x%X" % first


def cmd_verify(args):
    paths = []
    for root, _, files in os.walk(args.folder):
        paths += [os.path.join(root, f) for f in files if f.lower().endswith(".xbt")]
    paths.sort()
    per_format, failed = {}, []
    for p in paths:
        with open(p, "rb") as f:
            fmt = Header(f.read(HEADER_SIZE)).format
        why = verify_one(p)
        ok, bad = per_format.get(fmt, (0, 0))
        per_format[fmt] = (ok + (why is None), bad + (why is not None))
        if why:
            failed.append((p, why))
            print("FAIL %s: %s" % (os.path.relpath(p, args.folder), why))
    for fmt in sorted(per_format):
        ok, bad = per_format[fmt]
        print("format %d %-18s %6d identical, %d failed" % (fmt, FORMATS.get(fmt, ("?",))[0], ok, bad))
    print("%d .xbt, %d identical, %d failed" % (len(paths), len(paths) - len(failed), len(failed)))
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info", help="print the header and the mip chain")
    p.add_argument("xbt"); p.set_defaults(fn=cmd_info)
    p = sub.add_parser("export", help="write a .dds (every level) or a .png (one level)")
    p.add_argument("xbt"); p.add_argument("out")
    p.add_argument("--level", type=int, default=0, help="the mip level a PNG gets (default 0)")
    p.set_defaults(fn=cmd_export)
    p = sub.add_parser("import", help="build an .xbt from the original and an edited .dds or .png")
    p.add_argument("original"); p.add_argument("edited"); p.add_argument("out")
    p.set_defaults(fn=cmd_import)
    p = sub.add_parser("verify", help="round-trip every .xbt in a folder through DDS")
    p.add_argument("folder"); p.set_defaults(fn=cmd_verify)
    args = ap.parse_args()
    try:
        return args.fn(args)
    except (XbtError, OSError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
