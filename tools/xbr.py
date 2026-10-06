"""
TimeSplitters 2 (Xbox) models, .xbr: read the parts a writer needs, and give
an existing model new geometry.

    from tools.xbr import Model, replace_geometry
    new = replace_geometry(original_bytes, texture_numbers, triangles)

What is known (6 Oct 2026, from all 93 models in gun.pak, a loaded model in
guest RAM, and the game's mesh draw routine sub_001BC2A0):

  header     u32 texture list offset (0xC on the disc), u32 the count block
             offset, u32 0.
  textures   16-byte entries, the texture's number first (textures/<n>.xbt,
             decimal), ending at 0xFFFFFFFF. The loader turns each number
             into a handle in place.
  meshes     0x9C-byte records that end where the count block starts; the
             count block's first word is how many.
               +0x00  u8 mode (0 rigid; 1-3 blend two matrices), u8 matrix,
                      u8, u8 (the two matrices of a blend)
               +0x14  u32 x19: per section s (0..2), [s] the strip table;
                      [4+5s] the strip records, [5+5s] positions,
                      [6+5s] UVs, [7+5s] colours or 0, [8+5s] normals
               +0x60  u16 vertices in strips, u16 triangles in the index lists
               +0x90  u32 x3: per section, the face table
  strips     10 bytes: u16 texture (index into the list), u16 number, u16
             first vertex (a multiple of 4), u16 vertex count, u16 2; the
             table ends with an entry whose last word is 0xFFFF.
  records    16 bytes per strip: u16 count | 0x8000, then 00 00 00 40 2e 30
             12 04 and six zero bytes -- the same in all 2,291 on the disc.
  vertices   position: 3 floats and a word that is the float 1.0 with flag
             bits in its low half: 0x8000 marks the first two vertices of a
             strip run, bit 0 the winding. UV: u, v, 1.0. Colour: 4 bytes
             (7F7F7F7F, mid grey, on the disc's guns). Normal: x, y, z, 1.0.
  faces      the face table runs parallel to the strip table: entry k is
             (u32 offset of u16 indices, u32 count) for strip k, drawn with
             strip k's texture, the indices counting from the section's
             first vertex. When the game draws from index lists -- its guns
             are drawn that way, culling off -- a strip with no list is not
             drawn at all.

Every offset is from the start of the file; the loader turns them into
pointers. In a gun, _ph is the first-person model and _cl the one in the
world (on the ground, and in other characters' hands).

replace_geometry() does not move anything TS2 wrote: it appends a new
texture list and the new section 0 to the end of the file, points the header
and mesh 0 at them, and clears mesh 0's other sections. The other meshes (the
muzzle flashes) stay as they were.
"""

import struct

FLAG_RESTART = 0x8000
ONE = 0x3F800000
RECORD_TAIL = bytes.fromhex("000000402e301204000000000000")


def _u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


class Model:
    def __init__(self, data):
        self.data = data
        self.tex_at, self.count_at = _u32(data, 0), _u32(data, 4)
        self.textures = []
        o = self.tex_at
        while _u32(data, o) != 0xFFFFFFFF:
            self.textures.append(struct.unpack_from("<4I", data, o))
            o += 16
        self.mesh_count = _u32(data, self.count_at)
        self.mesh_at = self.count_at - 0x9C * self.mesh_count

    def mesh(self, i):
        m = self.mesh_at + 0x9C * i
        vo = struct.unpack_from("<19I", self.data, m + 0x14)
        c0, c1 = struct.unpack_from("<HH", self.data, m + 0x60)
        fo = struct.unpack_from("<3I", self.data, m + 0x90)
        return m, list(vo), (c0, c1), list(fo)

    def positions(self, i, section=0):
        _, vo, _, _ = self.mesh(i)
        if not vo[5 + 5 * section]:
            return []
        n = (vo[6 + 5 * section] - vo[5 + 5 * section]) // 16
        return [struct.unpack_from("<3f", self.data, vo[5 + 5 * section] + 16 * k) for k in range(n)]

    def bounds(self, i=0):
        p = self.positions(i)
        return (tuple(min(v[k] for v in p) for k in range(3)),
                tuple(max(v[k] for v in p) for k in range(3)))


def _align(buf, n):
    buf += bytes((-len(buf)) % n)


def build_section(base, groups):
    """Section 0's arrays, to be placed at file offset `base`.

    groups: [(texture index, [triangle, ...])], a triangle being three
    (x, y, z, u, v, (r, g, b, a), (nx, ny, nz)). Each group is one strip of
    independent triangles (every triangle a three-vertex run) and one index
    list. Returns (bytes, vo, fo, counts)."""
    verts, strips = [], []
    for tex, tris in groups:
        while len(verts) % 4:
            verts.append(verts[-1][:7] + (FLAG_RESTART,))
        start = len(verts)
        for tri in tris:
            for k, (x, y, z, u, v, col, nrm) in enumerate(tri):
                verts.append((x, y, z, u, v, col, nrm, FLAG_RESTART if k < 2 else 0))
        strips.append((tex, len(strips), start, len(verts) - start))
    out = bytearray()
    vo = [0] * 19

    def here():
        return base + len(out)

    vo[0] = here()
    for tex, num, start, count in strips:
        out += struct.pack("<5H", tex, num, start, count, 2)
    out += struct.pack("<5H", 0, 0, 0, 0, 0xFFFF) + bytes(2)
    _align(out, 4)
    vo[4] = here()
    for _, _, _, count in strips:
        out += struct.pack("<H", count | 0x8000) + RECORD_TAIL
    vo[7] = here()
    for v in verts:
        r, g, b, a = v[5]
        out += bytes((b, g, r, a))
    _align(out, 16)
    vo[5] = here()
    for v in verts:
        out += struct.pack("<3fI", v[0], v[1], v[2], ONE | v[7])
    vo[6] = here()
    for v in verts:
        out += struct.pack("<3f", v[3], v[4], 1.0)
    vo[8] = here()
    for v in verts:
        out += struct.pack("<4f", v[6][0], v[6][1], v[6][2], 1.0)
    fo = [here(), 0, 0]
    table = len(out)
    out += bytes(8 * len(strips) + 8)
    tris = 0
    for k, (_, _, start, count) in enumerate(strips):
        _align(out, 4)
        at = here()
        idx = list(range(start, start + count))
        out += struct.pack(f"<{len(idx)}H", *idx)
        struct.pack_into("<II", out, table + 8 * k, at, len(idx))
        tris += count // 3
    _align(out, 16)
    return bytes(out), vo, fo, (sum(s[3] for s in strips), tris)


def replace_geometry(data, texture_numbers, groups):
    """`data` with mesh 0 drawing `groups` (see build_section). The new
    texture list is the model's own entries followed by `texture_numbers`,
    so the other meshes keep their indices; a group's texture index counts
    into `texture_numbers`."""
    old = Model(data)
    first = len(old.textures)
    out = bytearray(data)
    _align(out, 16)
    tex_at = len(out)
    for e in old.textures:
        out += struct.pack("<4I", *e)
    for n in texture_numbers:
        out += struct.pack("<4I", n, 0, 0, 0)
    out += struct.pack("<4I", 0xFFFFFFFF, 0, 0, 0)
    _align(out, 16)
    groups = [(first + tex, tris) for tex, tris in groups]
    section, vo, fo, counts = build_section(len(out), groups)
    out += section
    struct.pack_into("<I", out, 0, tex_at)
    m, _, _, _ = old.mesh(0)
    struct.pack_into("<19I", out, m + 0x14, *vo)
    struct.pack_into("<HH", out, m + 0x60, *counts)
    struct.pack_into("<3I", out, m + 0x90, *fo)
    return bytes(out)
