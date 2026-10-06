"""
GoldenEye 007 (N64) models: the node tree, the display lists, and an OBJ of
what they draw. Used by tools.ge_guns; holds no game data.

A model file (unpacked) is, in order: an optional table of switch pointers
(36 of them in a first-person gun), a texture table of 12-byte entries, and
a tree of 24-byte nodes. All pointers are 0x05000000 plus the offset in the
file. A node is

    u8 flags, u8 opcode, u16 pad, data, parent, next, prev, child

and the opcodes that matter here are 2 (a group: its data starts with the
group's origin, three floats, then its joint number), 21 (a simple group:
the origin only), 4 (a display list record: primary list, secondary list,
-, vertices, u16 vertex count) and 22 (a primary-only record: count,
vertices, list). The display lists are Rare's F3D variant:

    04  load vertices: byte 1 = (count-1) << 4 | first slot, w1 = address
    B1  four triangles, 4-bit slot numbers
    BF  one triangle, slot numbers times 10
    C0  use texture: w1 low 12 bits = texture number; w0 bits 22/20 are the
        s/t clamp-mirror modes (bit 0 mirror), bits 14/10 the s/t shifts
    BB  texture scale (16.16 in w1); B6/B7 clear/set geometry mode; B8 end

A vertex is 16 bytes: s16 x, y, z, u16 flag, s16 s, t (texels, 10.5 fixed),
then r, g, b, a -- a colour, or a normal when the list lights the model.

In a first-person gun, joints 1 and 2 carry the muzzle flashes (flat
squares at the barrel's end, switched on when it fires); joint 0 is the gun,
and the other joints its moving parts -- the PP7's slide and trigger
finger, the Magnum's hammer and cylinder. The pistols carry Bond's hand.
Chrome (the Magnum) is environment-mapped: the list sets lighting and
texture generation, and the vertices hold normals instead of texture
coordinates, so the UVs here are made from the normals, as the game does.
"""

import struct

BASE = 0x05000000
G_LIGHTING = 0x00020000
G_TEXTURE_GEN = 0x00040000

# Bond's hand and cuff, which the pistols carry in their own model (the game
# swaps these textures for the costume the level dresses him in).
HAND_TEXTURES = range(0x701, 0x707)
# The joints of the muzzle flashes: flat squares at the barrel's end.
FLASH_JOINTS = (1, 2)

OP_GROUP, OP_DL, OP_GROUPSIMPLE, OP_DLPRIMARY = 2, 4, 21, 22


def _u32(m, o):
    return struct.unpack_from(">I", m, o)[0]


def _u16(m, o):
    return struct.unpack_from(">H", m, o)[0]


def _f32(m, o):
    return struct.unpack_from(">f", m, o)[0]


def _ptr(m, p):
    return p == 0 or BASE <= p < BASE + len(m)


def find_root(m):
    """The first node-shaped record with no parent."""
    for o in range(0, min(len(m) - 24, 0x4000), 4):
        op = _u16(m, o)
        if 1 <= op <= 24 and _u16(m, o + 2) == 0 and _u32(m, o + 8) == 0 and _u32(m, o + 4) \
                and all(_ptr(m, _u32(m, o + k)) for k in (4, 12, 16, 20)):
            return o
    raise ValueError("no root node")


def material_name(tex):
    """tex is None or (texture number, mirror s, mirror t)."""
    if tex is None:
        return "untextured"
    num, ms, mt = tex
    return f"tex_{num:03X}" + ("_ms" if ms else "") + ("_mt" if mt else "")


def mirrored(w, h, rgba, ms, mt):
    """The image with its mirror copies baked in: twice as wide for a
    mirrored s, twice as tall for a mirrored t."""
    rows = [rgba[4 * w * y:4 * w * (y + 1)] for y in range(h)]
    if ms:
        rows = [r + b"".join(r[4 * x:4 * x + 4] for x in range(w - 1, -1, -1)) for r in rows]
        w *= 2
    if mt:
        rows = rows + rows[::-1]
        h *= 2
    return w, h, b"".join(rows)


class Part:
    """One display list: its triangles, each with its texture."""

    def __init__(self, node, joint, origin, secondary):
        self.node, self.joint, self.origin, self.secondary = node, joint, origin, secondary
        self.tris = []          # (tex, [(x, y, z, u, v, r, g, b, a, lit)] * 3)

    @property
    def textures(self):
        return sorted({t[0] for t, _ in self.tris if t is not None})

    @property
    def kind(self):
        """"flash", "hand" or "gun"."""
        if self.joint in FLASH_JOINTS:
            return "flash"
        if self.textures and all(t in HAND_TEXTURES for t in self.textures):
            return "hand"
        return "gun"


class Model:
    def __init__(self, data, texture_size=None):
        """`texture_size(num)` gives (width, height) for the UVs; without
        it they assume 32 by 32."""
        self.m = data
        self.texture_size = texture_size
        self.root = find_root(data)
        self.parts = []
        self._walk(self.root, 0, (0.0, 0.0, 0.0))

    def _walk(self, n, joint, origin):
        m, seen = self.m, set()
        while n is not None and n not in seen:
            seen.add(n)
            op, dp = m[n + 1], _u32(m, n + 4) - BASE
            j, o = joint, origin
            if op in (OP_GROUP, OP_GROUPSIMPLE) and dp >= 0:
                o = tuple(origin[i] + _f32(m, dp + 4 * i) for i in range(3))
                if op == OP_GROUP:
                    j = _u16(m, dp + 12)
            elif op == OP_DL and dp >= 0:
                for k, secondary in ((0, False), (4, True)):
                    gdl = _u32(m, dp + k)
                    if gdl:
                        self._add(n, j, o, secondary, gdl)
            elif op == OP_DLPRIMARY and dp >= 0:
                gdl = _u32(m, dp + 8)
                if gdl:
                    self._add(n, j, o, False, gdl)
            child = _u32(m, n + 20)
            if child:
                self._walk(child - BASE, j, o)
            nxt = _u32(m, n + 12)
            n = nxt - BASE if nxt else None

    def _add(self, node, joint, origin, secondary, gdl):
        part = Part(node, joint, origin, secondary)
        self._run(gdl - BASE, part)
        if part.tris:
            self.parts.append(part)

    def _run(self, q, part):
        m = self.m
        slots = [None] * 16
        tex, tex_wh, scale, shift, geom = None, (32, 32), (1.0, 1.0), (0, 0), 0
        for _ in range(4096):
            if q < 0 or q + 8 > len(m):
                break
            w0, w1 = _u32(m, q), _u32(m, q + 4)
            q += 8
            op = w0 >> 24
            if op == 0xB8:
                break
            if op == 0x04:
                first = (w0 >> 16) & 0xF
                count = (w0 & 0xFFFF) // 16 or (((w0 >> 16) & 0xFF) >> 4) + 1
                va = w1 - BASE
                for i in range(count):
                    if 0 <= va + 16 * i and va + 16 * i + 16 <= len(m) and first + i < 16:
                        x, y, z, _, s, t = struct.unpack_from(">hhhHhh", m, va + 16 * i)
                        r, g, b, a = m[va + 16 * i + 12:va + 16 * i + 16]
                        slots[first + i] = (x, y, z, s, t, r, g, b, a)
            elif op == 0xC0:
                tex = (w1 & 0xFFF, (w0 >> 22) & 1, (w0 >> 20) & 1)
                shift = ((w0 >> 14) & 15, (w0 >> 10) & 15)
                tex_wh = (32, 32)
                if self.texture_size:
                    try:
                        tex_wh = self.texture_size(tex[0])
                    except (IndexError, ValueError):
                        pass
            elif op == 0xBB:
                scale = (((w1 >> 16) & 0xFFFF) / 65536.0, (w1 & 0xFFFF) / 65536.0)
                if not w0 & 0xFF:
                    tex = None
            elif op == 0xB7:
                geom |= w1
            elif op == 0xB6:
                geom &= ~w1
            elif op in (0xB1, 0xBF):
                if op == 0xB1:
                    zs = [(w0 >> (4 * k)) & 15 for k in range(4)]
                    xy = [(w1 >> (4 * k)) & 15 for k in range(8)]
                    tris = [(xy[2 * k], xy[2 * k + 1], zs[k]) for k in range(4)]
                    # An unused triangle of the four names one slot three times.
                    tris = [t for t in tris if len(set(t)) == 3]
                else:
                    tris = [(((w1 >> 16) & 0xFF) // 10, ((w1 >> 8) & 0xFF) // 10, (w1 & 0xFF) // 10)]
                for tri in tris:
                    vs = [slots[i] for i in tri]
                    if None not in vs:
                        part.tris.append((tex, [self._vertex(v, tex, tex_wh, scale, shift, geom, part.origin)
                                                for v in vs]))

    @staticmethod
    def _vertex(v, tex, wh, scale, shift, geom, origin):
        x, y, z, s, t, r, g, b, a = v

        def sh(val, k):
            if k == 0:
                return val
            return val / (1 << k) if k <= 10 else val * (1 << (16 - k))

        if geom & G_TEXTURE_GEN:
            # The normal, as signed bytes, picks the point of the
            # environment map (a sphere map, so x and y only).
            nx, ny = (r - 256 if r > 127 else r) / 128.0, (g - 256 if g > 127 else g) / 128.0
            u, w = 0.5 + nx * 0.5, 0.5 - ny * 0.5
        else:
            u = sh(s / 32.0 * scale[0], shift[0]) / wh[0]
            w = sh(t / 32.0 * scale[1], shift[1]) / wh[1]
        if tex is not None:
            # A mirrored axis is drawn from an image twice as long.
            u /= 2 if tex[1] else 1
            w /= 2 if tex[2] else 1
        lit = bool(geom & G_LIGHTING)
        return (x + origin[0], y + origin[1], z + origin[2], u, w, r, g, b, a, lit)

    def bounds(self, parts=None):
        pts = [v[:3] for p in (self.parts if parts is None else parts) for _, tri in p.tris for v in tri]
        lo = tuple(min(p[i] for p in pts) for i in range(3))
        hi = tuple(max(p[i] for p in pts) for i in range(3))
        return lo, hi


def materials(parts):
    return sorted({t for p in parts for t, _ in p.tris if t is not None})


def write_obj(path, parts, name="model"):
    """An OBJ and an MTL beside it, materials named by material_name() with
    images <material>.png. Vertex colours go on the `v` lines (Blender
    reads them); lit parts carry normals instead and get white."""
    mtl_path = path[:-4] + ".mtl"
    mtl_name = mtl_path.replace("\\", "/").split("/")[-1]
    with open(mtl_path, "w", newline="\n") as f:
        f.write("# Extracted from your own GoldenEye 007 ROM by tools.ge_guns. Do not distribute.\n")
        f.write("newmtl untextured\nKd 1 1 1\nillum 1\n")
        for t in materials(parts):
            mat = material_name(t)
            f.write(f"\nnewmtl {mat}\nKd 1 1 1\nillum 1\nmap_Kd {mat}.png\n")
    with open(path, "w", newline="\n") as f:
        f.write(f"# {name}: extracted from your own GoldenEye 007 ROM by tools.ge_guns. Do not distribute.\n")
        f.write(f"mtllib {mtl_name}\n")
        nv = 0
        for p in parts:
            kind = "secondary" if p.secondary else "primary"
            f.write(f"\no node_{p.node:04X}_joint{p.joint}_{kind}\n")
            cur = None
            for tex, tri in p.tris:
                mat = material_name(tex)
                if mat != cur:
                    f.write(f"usemtl {mat}\n")
                    cur = mat
                for x, y, z, u, v, r, g, b, a, lit in tri:
                    if lit:
                        r = g = b = 255
                    f.write(f"v {x:g} {y:g} {z:g} {r / 255:.3f} {g / 255:.3f} {b / 255:.3f}\n")
                    f.write(f"vt {u:.5f} {1 - v:.5f}\n")
                f.write(f"f {nv + 1}/{nv + 1} {nv + 2}/{nv + 2} {nv + 3}/{nv + 3}\n")
                nv += 3


def render(parts, size=512, image=None, view="side", bounds=None):
    """A z-buffered preview as (width, height, RGB bytes). `image(tex)`
    gives (w, h, rgba) for a material key, or None. view: side (looking
    along x), top, front, or auto (the broad side)."""
    pts = [v[:3] for p in parts for _, tri in p.tris for v in tri]
    lo, hi = bounds or (tuple(min(q[i] for q in pts) for i in range(3)),
                        tuple(max(q[i] for q in pts) for i in range(3)))
    if view == "auto":
        # Across the longest axis, up the next: the model's broad side.
        ax, ay, az = sorted(range(3), key=lambda i: lo[i] - hi[i])
    else:
        ax, ay, az = {"side": (2, 1, 0), "top": (2, 0, 1), "front": (0, 1, 2)}[view]
    k = (size - 16) / (max(hi[ax] - lo[ax], hi[ay] - lo[ay]) or 1)
    oy = (size - 16 - (hi[ay] - lo[ay]) * k) / 2
    px = lambda q: (8 + (q[ax] - lo[ax]) * k, size - 8 - oy - (q[ay] - lo[ay]) * k, q[az])
    img = bytearray([48, 48, 56] * size * size)
    zbuf = [-1e30] * (size * size)
    cache = {}
    for p in parts:
        for tex, tri in p.tris:
            tx = None
            if tex is not None and image:
                if tex not in cache:
                    try:
                        cache[tex] = image(tex)
                    except (IndexError, ValueError):
                        cache[tex] = None
                tx = cache[tex]
            (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = (px(v) for v in tri)
            area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
            if abs(area) < 1e-9:
                continue
            a, b, c = tri
            for yy in range(max(int(min(y0, y1, y2)), 0), min(int(max(y0, y1, y2)) + 1, size)):
                for xx in range(max(int(min(x0, x1, x2)), 0), min(int(max(x0, x1, x2)) + 1, size)):
                    cx, cy = xx + 0.5, yy + 0.5
                    w0 = ((x1 - cx) * (y2 - cy) - (x2 - cx) * (y1 - cy)) / area
                    w1 = ((x2 - cx) * (y0 - cy) - (x0 - cx) * (y2 - cy)) / area
                    w2 = 1 - w0 - w1
                    if w0 < 0 or w1 < 0 or w2 < 0:
                        continue
                    z = w0 * z0 + w1 * z1 + w2 * z2
                    i = yy * size + xx
                    if z <= zbuf[i]:
                        continue
                    col = [255, 255, 255]
                    if not a[9]:
                        col = [w0 * a[n] + w1 * b[n] + w2 * c[n] for n in (5, 6, 7)]
                    if tx:
                        tw, th, rgba = tx
                        u = w0 * a[3] + w1 * b[3] + w2 * c[3]
                        v = w0 * a[4] + w1 * b[4] + w2 * c[4]
                        ti = 4 * ((int(v * th) % th) * tw + int(u * tw) % tw)
                        if rgba[ti + 3] < 128:
                            continue
                        col = [col[n] * rgba[ti + n] / 255 for n in range(3)]
                    zbuf[i] = z
                    img[3 * i:3 * i + 3] = bytes(max(0, min(255, int(cv))) for cv in col)
    return size, size, bytes(img)
