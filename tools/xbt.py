"""
TimeSplitters 2 (Xbox) .xbt textures: inspect, convert to DDS and back.

    py -3 -m tools.xbt info   out/chr/textures/0267.xbt [more.xbt ...]
    py -3 -m tools.xbt to-dds out/chr/textures/0267.xbt 0267.dds
    py -3 -m tools.xbt from-dds 0267_edited.dds out/chr/textures/0267.xbt -o new.xbt
    py -3 -m tools.xbt index  game/data --csv textures.csv

The workflow for a texture mod: unpack the archive (tools.ts2pak), turn the
.xbt into a DDS, paint it in any editor that saves DDS, turn it back with the
original as the template, repack the archive, drop it in the mods folder.

The layout:

  header   0x80 bytes.
           +0x00 width,  +0x04 height     as stored: what the texels are
           +0x08 width,  +0x0C height     as shown: smaller for the 96
                                          textures whose size is not a power
                                          of two (128x192 is stored 128x256)
           +0x10 mip levels - 1
           +0x14 format code
           the other words are not understood and are copied from the
           template unchanged (`info` prints +0x18, +0x1C and +0x20; the last
           two are 0 or small floats -- 2.0, 3.0, 4.0 -- on the same 382
           textures, and +0x18 is 0xFFFFFFFF on the rest)
  texels   from 0x80: level 0 at the stored size, then each smaller level.

  format   0  DXT1                         blocks as D3D stores them
           1  DXT3                         blocks as D3D stores them
           2  A8R8G8B8, swizzled           the Xbox's Morton order, per level
           3  raw 24-bit                   NOT VERIFIED: assumed B,G,R, linear

Checked on the PAL disc (6 Oct 2026): all 19,180 textures in its archives
are exactly 0x80 bytes of header plus the levels the stored size and +0x10
describe -- no texture is a byte long or short. 11,310 are DXT1, 7,138
DXT3, 732 swizzled ARGB; none is format 3. The texel data at +0x80 had
already matched the GPU's own copy of 97 of 98 textures, mips and all
(xboxrecomp docs/technical/modding-models-textures.md). The format codes
come from OpenRadical's Noesis plugin (fmt_xbox.py); code 2 is named a
"packed normal map" there but decodes as swizzled 32-bit colour.

The DDS is the stored texels, every level. For a texture shown smaller than
it is stored, the picture is in the top-left corner and the rest is
whatever the game's tools left there; paint inside it. from-dds is strict
on purpose: the same stored size, format and number of levels as the
template, unless told otherwise.
"""

import argparse
import csv
import glob
import hashlib
import os
import struct
import sys

HEADER = 0x80
FORMATS = {0: "DXT1", 1: "DXT3", 2: "A8R8G8B8 (swizzled)", 3: "R8G8B8 (raw, unverified)"}


class XbtError(Exception):
    pass


# ------------------------------------------------------------------ layout

def level_size(fmt, w, h):
    if fmt in (0, 1):
        bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
        return bw * bh * (8 if fmt == 0 else 16)
    if fmt == 2:
        return w * h * 4
    if fmt == 3:
        return w * h * 3
    raise XbtError(f"unknown format code {fmt}")


def mip_chain(fmt, w, h, count):
    """[(w, h, size)] for `count` levels from w x h, each half the last."""
    levels = []
    for _ in range(count):
        levels.append((w, h, level_size(fmt, w, h)))
        w, h = max(1, w // 2), max(1, h // 2)
    return levels


class Xbt:
    def __init__(self, data):
        if len(data) < HEADER:
            raise XbtError(f"{len(data)} bytes: shorter than the 0x80-byte header")
        self.header = bytearray(data[:HEADER])
        self.texels = data[HEADER:]
        (self.width, self.height, self.shown_width, self.shown_height,
         last_level, self.format) = struct.unpack_from("<6I", data, 0)
        if self.format not in FORMATS:
            raise XbtError(f"unknown format code {self.format}")
        if not (0 < self.width <= 4096 and 0 < self.height <= 4096):
            raise XbtError(f"implausible size {self.width}x{self.height}")
        if last_level > 12:
            raise XbtError(f"implausible mip count {last_level + 1}")
        self.levels = mip_chain(self.format, self.width, self.height, last_level + 1)
        need = sum(size for _, _, size in self.levels)
        if need > len(self.texels):
            raise XbtError(f"the header describes {need} bytes of texels at "
                           f"{self.width}x{self.height}, {last_level + 1} level(s); "
                           f"the file has {len(self.texels)}")
        self.leftover = len(self.texels) - need

    def level_bytes(self):
        out, at = [], 0
        for w, h, size in self.levels:
            out.append((w, h, self.texels[at:at + size]))
            at += size
        return out


# ------------------------------------------------------------------ swizzle

def swizzle_masks(w, h):
    """The Xbox's masks (xboxrecomp src/d3d/d3d8_swizzle.h): x and y bits
    interleave, x first, and the larger dimension keeps the rest."""
    mx = my = 0
    bit = mbit = 1
    while bit < w or bit < h:
        if bit < w:
            mx |= mbit
            mbit <<= 1
        if bit < h:
            my |= mbit
            mbit <<= 1
        bit <<= 1
    return mx, my


def _deposit(v, mask):
    out, bit = 0, 1
    while mask:
        low = mask & -mask
        if v & bit:
            out |= low
        mask &= mask - 1
        bit <<= 1
    return out


def _offsets(w, h):
    mx, my = swizzle_masks(w, h)
    xs = [_deposit(x, mx) for x in range(w)]
    ys = [_deposit(y, my) for y in range(h)]
    return xs, ys


def unswizzle(data, w, h, bpp):
    xs, ys = _offsets(w, h)
    out = bytearray(w * h * bpp)
    for y in range(h):
        row, sy = y * w * bpp, ys[y]
        for x in range(w):
            s = (sy | xs[x]) * bpp
            out[row + x * bpp:row + x * bpp + bpp] = data[s:s + bpp]
    return bytes(out)


def swizzle(data, w, h, bpp):
    xs, ys = _offsets(w, h)
    out = bytearray(w * h * bpp)
    for y in range(h):
        row, sy = y * w * bpp, ys[y]
        for x in range(w):
            d = (sy | xs[x]) * bpp
            out[d:d + bpp] = data[row + x * bpp:row + x * bpp + bpp]
    return bytes(out)


# ------------------------------------------------------------------ DDS

DDSD_CAPS, DDSD_HEIGHT, DDSD_WIDTH, DDSD_PITCH = 0x1, 0x2, 0x4, 0x8
DDSD_PIXELFORMAT, DDSD_MIPMAPCOUNT, DDSD_LINEARSIZE = 0x1000, 0x20000, 0x80000
DDPF_ALPHAPIXELS, DDPF_FOURCC, DDPF_RGB = 0x1, 0x4, 0x40
DDSCAPS_COMPLEX, DDSCAPS_TEXTURE, DDSCAPS_MIPMAP = 0x8, 0x1000, 0x400000


def _pixel_format(fmt):
    """(flags, fourcc, bits, r, g, b, a) for the DDS pixel format."""
    if fmt == 0:
        return DDPF_FOURCC, b"DXT1", 0, 0, 0, 0, 0
    if fmt == 1:
        return DDPF_FOURCC, b"DXT3", 0, 0, 0, 0, 0
    if fmt == 2:
        return DDPF_RGB | DDPF_ALPHAPIXELS, b"\0\0\0\0", 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000
    return DDPF_RGB, b"\0\0\0\0", 24, 0xFF0000, 0xFF00, 0xFF, 0


def to_dds(xbt):
    """The texture as a DDS file: every level, linear, as D3D9 tools read it."""
    w, h, n = xbt.width, xbt.height, len(xbt.levels)
    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    compressed = xbt.format in (0, 1)
    if compressed:
        flags |= DDSD_LINEARSIZE
        pitch = level_size(xbt.format, w, h)
    else:
        flags |= DDSD_PITCH
        pitch = w * (4 if xbt.format == 2 else 3)
    caps = DDSCAPS_TEXTURE
    if n > 1:
        flags |= DDSD_MIPMAPCOUNT
        caps |= DDSCAPS_COMPLEX | DDSCAPS_MIPMAP
    pf = _pixel_format(xbt.format)
    header = struct.pack("<4sIIIIIII44x", b"DDS ", 124, flags, h, w, pitch, 0, n)
    header += struct.pack("<II4sIIIII", 32, pf[0], pf[1], pf[2], pf[3], pf[4], pf[5], pf[6])
    header += struct.pack("<IIII4x", caps, 0, 0, 0)
    body = bytearray()
    for lw, lh, data in xbt.level_bytes():
        body += unswizzle(data, lw, lh, 4) if xbt.format == 2 else data
    return header + bytes(body)


def read_dds(data):
    """(format code, width, height, [level bytes, linear]) from a DDS."""
    if len(data) < 128 or data[:4] != b"DDS " or struct.unpack_from("<I", data, 4)[0] != 124:
        raise XbtError("not a DDS file")
    flags, h, w = struct.unpack_from("<III", data, 8)
    count = struct.unpack_from("<I", data, 28)[0] if flags & DDSD_MIPMAPCOUNT else 1
    pf_flags, fourcc, bits, rm, gm, bm, am = struct.unpack_from("<I4sIIIII", data, 80)
    if pf_flags & DDPF_FOURCC:
        if fourcc == b"DX10":
            raise XbtError("a DX10-header DDS; save it as legacy DXT1/DXT3 or A8R8G8B8")
        fmt = {b"DXT1": 0, b"DXT3": 1}.get(fourcc)
        if fmt is None:
            raise XbtError(f"DDS compression {fourcc!r}: only DXT1 and DXT3 go back into an .xbt")
    elif pf_flags & DDPF_RGB and bits == 32 and (rm, gm, bm) == (0xFF0000, 0xFF00, 0xFF):
        fmt = 2
    elif pf_flags & DDPF_RGB and bits == 24 and (rm, gm, bm) == (0xFF0000, 0xFF00, 0xFF):
        fmt = 3
    else:
        raise XbtError("DDS pixel format is not DXT1, DXT3, A8R8G8B8 or R8G8B8")
    body = data[128:]
    levels, at = [], 0
    lw, lh = w, h
    for _ in range(max(1, count)):
        size = level_size(fmt, lw, lh)
        if at + size > len(body):
            raise XbtError(f"DDS ends inside level {len(levels)}")
        levels.append((lw, lh, body[at:at + size]))
        at += size
        lw, lh = max(1, lw // 2), max(1, lh // 2)
    return fmt, w, h, levels


def from_dds(dds_data, template, allow_resize=False, allow_levels=False):
    """A new .xbt: the template's header, the DDS's texels. A resize sets both
    the stored and the shown size to the DDS's; a different level count
    rewrites +0x10."""
    fmt, w, h, levels = read_dds(dds_data)
    if fmt != template.format:
        raise XbtError(f"the DDS is {FORMATS[fmt]} but the template is "
                       f"{FORMATS[template.format]}; save it in the template's format")
    if (w, h) != (template.width, template.height) and not allow_resize:
        raise XbtError(f"the DDS is {w}x{h} but the template is "
                       f"{template.width}x{template.height} (--allow-resize to insist)")
    if len(levels) != len(template.levels) and not allow_levels:
        raise XbtError(f"the DDS has {len(levels)} mip level(s), the template "
                       f"{len(template.levels)} (--allow-levels to insist)")
    header = bytearray(template.header)
    if (w, h) != (template.width, template.height):
        struct.pack_into("<IIII", header, 0, w, h, w, h)
    struct.pack_into("<I", header, 0x10, len(levels) - 1)
    body = bytearray()
    for lw, lh, data in levels:
        body += swizzle(data, lw, lh, 4) if fmt == 2 else data
    if template.leftover and (w, h) == (template.width, template.height) \
            and len(levels) == len(template.levels):
        body += template.texels[len(template.texels) - template.leftover:]
    return bytes(header) + bytes(body)


# ------------------------------------------------------------------ CLI

def describe(path, x):
    unknown = " ".join(f"{struct.unpack_from('<I', x.header, o)[0]:08X}"
                       for o in (0x18, 0x1C, 0x20))
    shown = ("" if (x.shown_width, x.shown_height) == (x.width, x.height)
             else f" (shown {x.shown_width}x{x.shown_height})")
    tail = f", {x.leftover} byte(s) after the last level" if x.leftover else ""
    return (f"{path}: {x.width}x{x.height}{shown} {FORMATS[x.format]}, "
            f"{len(x.levels)} level(s){tail}; header +18 +1C +20 = {unknown}")


def cmd_info(args):
    rc = 0
    files = []
    for f in args.files:   # cmd.exe and PowerShell pass *.xbt through
        files.extend(sorted(glob.glob(f)) if any(c in f for c in "*?[") else [f])
    for p in files:
        try:
            print(describe(p, Xbt(open(p, "rb").read())))
        except XbtError as exc:
            print(f"{p}: {exc}")
            rc = 1
    return rc


def cmd_to_dds(args):
    x = Xbt(open(args.xbt, "rb").read())
    with open(args.dds, "wb") as f:
        f.write(to_dds(x))
    print(describe(args.xbt, x))
    print(f"-> {args.dds}")


def cmd_from_dds(args):
    template = Xbt(open(args.template, "rb").read())
    out = from_dds(open(args.dds, "rb").read(), template,
                   args.allow_resize, args.allow_levels)
    with open(args.output, "wb") as f:
        f.write(out)
    print(describe(args.output, Xbt(out)))


def cmd_index(args):
    """Every .xbt in every archive under a folder: where it is, what it is,
    and the SHA-1 of its level 0 (to match textures seen at run time)."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from tools.ts2pak import read_pak, PakError
    rows = []
    for root, _, files in os.walk(args.data):
        for fn in sorted(files):
            if not fn.lower().endswith(".pak"):
                continue
            path = os.path.join(root, fn)
            try:
                pak = read_pak(open(path, "rb").read())
            except PakError as exc:
                print(f"{path}: {exc}", file=sys.stderr)
                continue
            for e in pak.entries:
                if not e.name.lower().endswith(".xbt"):
                    continue
                try:
                    x = Xbt(pak.read(e))
                except XbtError as exc:
                    rows.append([os.path.relpath(path, args.data), e.name,
                                 "", "", "", "", "", "", str(exc)])
                    continue
                level0 = x.level_bytes()[0][2]
                rows.append([os.path.relpath(path, args.data), e.name, x.width, x.height,
                             x.shown_width, x.shown_height, FORMATS[x.format],
                             len(x.levels), hashlib.sha1(level0).hexdigest()])
    head = ["pak", "name", "width", "height", "shown_width", "shown_height",
            "format", "levels", "level0_sha1"]
    out = open(args.csv, "w", newline="") if args.csv else sys.stdout
    w = csv.writer(out)
    w.writerow(head)
    w.writerows(rows)
    if args.csv:
        out.close()
        print(f"{len(rows)} textures -> {args.csv}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="xbt", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info", help="size, format, levels and the unknown header words")
    p.add_argument("files", nargs="+")
    p.set_defaults(fn=cmd_info)
    p = sub.add_parser("to-dds", help="an .xbt as a DDS, every level")
    p.add_argument("xbt")
    p.add_argument("dds")
    p.set_defaults(fn=cmd_to_dds)
    p = sub.add_parser("from-dds", help="a DDS back into an .xbt, using the original as template")
    p.add_argument("dds")
    p.add_argument("template")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--allow-resize", action="store_true")
    p.add_argument("--allow-levels", action="store_true")
    p.set_defaults(fn=cmd_from_dds)
    p = sub.add_parser("index", help="every texture in every archive under a folder")
    p.add_argument("data", help="the game's data folder")
    p.add_argument("--csv")
    p.set_defaults(fn=cmd_index)
    args = ap.parse_args(argv)
    try:
        return args.fn(args) or 0
    except (XbtError, OSError) as exc:
        print(f"xbt: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
