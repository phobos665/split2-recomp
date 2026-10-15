"""TimeSplitters 2 character models (.xbr) to and from glTF 2.0 binary (.glb).

The round trip for editing a character in Blender (docs/formats/xbr.md,
"Editing in Blender"):

  python3 -I tools/ts2gltf.py gltf     chr01.xbr chr01.glb --textures <unpacked chr.pak> \
                                       --bindpose <unpacked fe_anim.pak>/anim/data/ts2
  python3 -I tools/ts2gltf.py fromgltf chr01.xbr chr01_edited.glb chr01_new.xbr
  python3 -I tools/ts2gltf.py graft    chr19.xbr chr01.xbr chr19_new.xbr --pieces head \
                                       --textures <unpacked chr.pak> --bindpose <...>/anim/data/ts2

Export: one armature joint per palette bone (the animation bones, named by
their animation index and body part, plus the mid-joint bones that type-2
pieces synthesise), placed from the bind pose; one mesh per piece and
section (node "pNNsS_name"), one primitive per material, triangles from the
face lists the game draws, every vertex skinned to the one bone it follows
(weight 1.0). Textures are embedded as PNG. What glTF cannot express goes in
`extras`, for reading only.

Import: the base .xbr is the source of truth for everything but geometry
and materials. Positions, normals, UVs, colours, triangles and their material
come from the glTF, mapped back to pieces by node (or mesh) name ("pNNsS_name";
by the name when piece NN of the base is another), to bones by joint name.
A material named "mN_tTTTT" uses texture TTTT; one without an id gets its
picture encoded as a new .xbt (DXT1, DXT3 with alpha) under a new id in
8000-9999, or embedded in a chrinc.pak preview. Vertices are snapped to the strongest
bone the piece can use. A section whose triangles are the base's (within
float tolerance) is kept as it is in the base, byte for byte, unless
--regenerate; the others are rebuilt: vertices deduplicated, triangle strips
(restart flags, no winding flips), records of at most 72 vertices split by
material, face lists on the last record of each material run, padding
vertices and draw headers (by ts2xbr.build).

Graft: the pieces of some animation bones (and the joint and bridge pieces
bound to them) from a donor model onto a base with the same skeleton, each
donor vertex moved by its bone's bind offset between the two models.

Python 3, standard library only.
"""

import argparse
import base64
import json
import math
import os
import re
import struct
import sys
import zlib
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ts2xbr as X  # noqa: E402
import ts2xbt  # noqa: E402

MAX_RECORD_VERTS = 72          # largest record on the disc (PS2-style batches); kept as the limit
MAX_SECTION_VERTS = 32767      # record start/count are s16
FLAG_W = 0x3F800000            # position W: 1.0f
RESTART = 0x8000               # position W bit 15: no triangle ends at this vertex
ONE_F = 0x3F800000

# The 19-bone human skeleton (parents per animation bone). The bones on the
# -X side are called right: in glTF (+Y up, facing +Z) and in Blender that
# is the character's right. Whether the game itself is mirrored was not
# checked.
HUMAN19_PARENTS = [-1, 0, 1, 2, 3, 2, 5, 6, 7, 2, 9, 10, 11, 0, 13, 14, 0, 16, 17]
HUMAN19_NAMES = ["pelvis", "spine", "chest", "neck", "head",
                 "r_clavicle", "r_upperarm", "r_forearm", "r_hand",
                 "l_clavicle", "l_upperarm", "l_forearm", "l_hand",
                 "r_thigh", "r_shin", "r_foot", "l_thigh", "l_shin", "l_foot"]


class GltfError(Exception):
    pass


def f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def float_of(bits):
    return struct.unpack("<f", struct.pack("<I", bits))[0]


# --------------------------------------------------------------------------
# Math (4x4 row-major nested lists; quaternions x, y, z, w)


def qnorm(q):
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / n for c in q)


def qconj(q):
    return (-q[0], -q[1], -q[2], q[3])


def qmat3(q):
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def trs_mat(t=(0, 0, 0), q=(0, 0, 0, 1), s=(1, 1, 1)):
    r = qmat3(qnorm(q))
    return [[r[0][0] * s[0], r[0][1] * s[1], r[0][2] * s[2], t[0]],
            [r[1][0] * s[0], r[1][1] * s[1], r[1][2] * s[2], t[1]],
            [r[2][0] * s[0], r[2][1] * s[1], r[2][2] * s[2], t[2]],
            [0.0, 0.0, 0.0, 1.0]]


def mmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def ident():
    return [[float(i == j) for j in range(4)] for i in range(4)]


def from_colmajor(m):
    return [[m[c * 4 + r] for c in range(4)] for r in range(4)]


def to_colmajor(m):
    return [m[r][c] for c in range(4) for r in range(4)]


def rigid_inverse(t, q):
    """Inverse of translate(t) * rotate(q)."""
    r = qmat3(qnorm(q))
    rt = [[r[j][i] for j in range(3)] for i in range(3)]
    ti = [-sum(rt[i][k] * t[k] for k in range(3)) for i in range(3)]
    return [rt[0] + [ti[0]], rt[1] + [ti[1]], rt[2] + [ti[2]], [0.0, 0.0, 0.0, 1.0]]


def xform(m, p, w=1.0):
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] * w for i in range(3))


def near_identity(m, tol=1e-5):
    return all(abs(m[i][j] - (i == j)) <= tol for i in range(4) for j in range(4))


def normalize3(n):
    l2 = n[0] * n[0] + n[1] * n[1] + n[2] * n[2]
    if l2 <= 1e-20:
        return (0.0, 1.0, 0.0)
    l = math.sqrt(l2)
    return (n[0] / l, n[1] / l, n[2] / l)


# --------------------------------------------------------------------------
# Skeleton: palette bones, names, bind transforms


def piece_bone_sets(xbr, i):
    """(own bone or None, allowed palette bones) for piece i."""
    P = xbr["pieces"]
    p = P[i]
    if p["type"] == 0:
        return p["bone"], [p["bone"]]
    allowed = []
    for link in (p["parent"], p["child"]):
        if 0 <= link < len(P) and P[link]["bone"] >= 0 and P[link]["bone"] not in allowed:
            allowed.append(P[link]["bone"])
    own = p["bone"] if p["bone"] >= 0 else None
    if own is not None and own not in allowed:
        allowed.append(own)
    return own, allowed


def skeleton(xbr):
    """Palette bones: list (index = palette bone) of dicts with name, short
    name, owning piece, kind ('anim' or 'mid'), anim index, parent palette bone."""
    P = xbr["pieces"]
    sk = X.rigid_skeleton(xbr)
    parents = [pa for _, pa in sk]
    human = parents == HUMAN19_PARENTS
    nb = xbr["model"]["bone_count"]
    bones = [None] * nb
    anim_of_piece = {}
    for k, (pi, pa) in enumerate(sk):
        anim_of_piece[pi] = k
        if human:
            short = HUMAN19_NAMES[k]
        elif len(sk) == 1:
            short = "root"
        else:
            short = ""
        name = "b%02d_%s" % (k, short) if short else "b%02d" % k
        b = P[pi]["bone"]
        if not 0 <= b < nb:
            raise GltfError("rigid piece %d has palette bone %d (model has %d)" % (pi, b, nb))
        bones[b] = {"name": name, "short": short or name, "piece": pi, "kind": "anim", "anim": k,
                    "parent_anim": pa}
    for i, p in enumerate(P):
        if p["type"] == 2 and p["bone"] >= 0 and bones[p["bone"]] is None:
            bones[p["bone"]] = {"piece": i, "kind": "mid"}
    for b, info in enumerate(bones):
        if info is None:
            raise GltfError("palette bone %d belongs to no rigid or mid-joint piece" % b)
    # names of mid bones from the bones of their c64 and c68 pieces
    used = {b["name"] for b in bones if b["kind"] == "anim"}
    for b, info in enumerate(bones):
        if info["kind"] != "mid":
            continue
        p = P[info["piece"]]
        parts = []
        for link in (p["parent"], p["child"]):
            lb = P[link]["bone"] if 0 <= link < len(P) else -1
            parts.append(bones[lb]["short"] if lb >= 0 and bones[lb]["kind"] == "anim" else "x")
        name = "mid_%s_%s" % tuple(parts)
        k = 2
        while name in used:
            name = "mid_%s_%s_%d" % (parts[0], parts[1], k)
            k += 1
        used.add(name)
        info["name"] = info["short"] = name
    # parent palette bone of each bone in the joint tree
    for b, info in enumerate(bones):
        if info["kind"] == "anim":
            pa = info["parent_anim"]
            info["parent"] = P[sk[pa][0]]["bone"] if pa >= 0 else -1
        else:
            q = P[info["piece"]]["parent"]
            while q >= 0 and not (P[q]["type"] in (0, 2) and P[q]["bone"] >= 0):
                q = P[q]["parent"]
            info["parent"] = P[q]["bone"] if q >= 0 else -1
    return bones


def section_vertices(sec):
    """The section's vertices, padding included (face lists are section-relative)."""
    out = []
    recs = sec["records"]
    for j, rec in enumerate(recs):
        vs = list(X.vertices(rec))
        out += vs
        if j + 1 < len(recs):
            out += [vs[-1]] * (X.align(rec["count"], 4) - rec["count"])
    return out


def section_triangles(sec):
    """[(material, (a, b, c))] in section indices: the face lists, which is
    what the game draws; the strips of a material run that has no list."""
    recs = sec["records"]
    starts = X.section_starts(sec)
    out = []
    j = 0
    while j < len(recs):
        k = j
        while k + 1 < len(recs) and recs[k + 1]["material"] == recs[j]["material"]:
            k += 1
        mat = recs[j]["material"]
        lists = [recs[q]["faces"] for q in range(j, k + 1) if recs[q]["faces"]]
        if lists:
            for fc in lists:
                out += [(mat, tuple(fc[t:t + 3])) for t in range(0, len(fc) - 2, 3)]
        else:
            for q in range(j, k + 1):
                out += [(mat, tuple(starts[q] + v for v in tri)) for tri in X.strip_triangles(recs[q])]
        j = k + 1
    return out


def vertex_bone(piece, v):
    """Palette bone a stored vertex follows."""
    if piece["type"] == 0:
        return piece["bone"]
    return int(v[7][3])


def bind_transforms(xbr, bones, bindposes, warn):
    """World (t, q) of every palette bone at bind time."""
    sk = X.rigid_skeleton(xbr)
    P = xbr["pieces"]
    world = [None] * len(bones)
    chosen = None
    for name, bp in bindposes:
        if len(bp) == len(sk):
            chosen = (name, bp)
            break
    if chosen:
        for piece, parent, t, q in X.bind_joints(xbr, chosen[1]):
            world[P[piece]["bone"]] = (tuple(t), qnorm(q))
    else:
        if bindposes:
            warn("no bind pose has %d bones; joints placed at their vertices' centroid" % len(sk))
        else:
            warn("no --bindpose; joints placed at their vertices' centroid, unrotated")
        acc = defaultdict(lambda: [0.0, 0.0, 0.0, 0])
        for i, p in enumerate(P):
            for sec in p["sections"]:
                if not sec:
                    continue
                for rec in sec["records"]:
                    for v in X.vertices(rec):
                        a = acc[vertex_bone(p, v)]
                        a[0] += v[0]; a[1] += v[1]; a[2] += v[2]; a[3] += 1
        for b, info in enumerate(bones):
            if info["kind"] == "anim":
                a = acc.get(b)
                world[b] = ((a[0] / a[3], a[1] / a[3], a[2] / a[3]) if a and a[3] else None, (0.0, 0.0, 0.0, 1.0))
        for b in sorted(range(len(bones)), key=lambda b: bones[b].get("anim", 99)):
            if bones[b]["kind"] == "anim" and world[b][0] is None:
                pa = bones[b]["parent"]
                world[b] = (world[pa][0] if pa >= 0 and world[pa][0] else (0.0, 0.0, 0.0), world[b][1])
    # mid bones: bound with the blend forced to 1.0, i.e. at their c68 piece's bone
    for _ in range(len(bones)):
        for b, info in enumerate(bones):
            if world[b] is None:
                c = P[info["piece"]]["child"]
                cb = P[c]["bone"] if 0 <= c < len(P) else -1
                if cb >= 0 and world[cb] is not None:
                    world[b] = world[cb]
    for b in range(len(bones)):
        if world[b] is None:
            world[b] = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
    return world, (chosen[0] if chosen else None)


def piece_names(xbr, bones):
    P = xbr["pieces"]
    out = []

    def bshort(link):
        if 0 <= link < len(P) and P[link]["bone"] >= 0:
            return bones[P[link]["bone"]]["short"]
        return "p%02d" % link
    for i, p in enumerate(P):
        if p["type"] == 0:
            out.append(bones[p["bone"]]["short"])
        elif p["type"] == 2 and p["bone"] >= 0:
            out.append(bones[p["bone"]]["name"])
        else:
            out.append("%s_%s_%s" % ("joint" if p["type"] == 1 else "bridge", bshort(p["parent"]), bshort(p["child"])))
    return out


def node_name(i, s, pname):
    return "p%02ds%d_%s" % (i, s, pname)


def material_name(k, mt):
    if mt["flags"] & X.EMBEDDED_FLAG:
        return "m%d_emb%d" % (k, mt["texture"])
    if mt["texture"] == X.NO_TEXTURE:
        return "m%d_none" % k
    return "m%d_t%04d" % (k, mt["texture"])


# --------------------------------------------------------------------------
# GLB writing


class GlbBuilder:
    def __init__(self):
        self.bin = bytearray()
        self.views = []
        self.accessors = []

    def view(self, data, target=None):
        self.bin += b"\0" * (-len(self.bin) % 4)
        v = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target:
            v["target"] = target
        self.bin += data
        self.views.append(v)
        return len(self.views) - 1

    def accessor(self, fmt, rows, gtype, ctype, normalized=False, minmax=False, target=34962):
        flat = [c for r in rows for c in r] if gtype != "SCALAR" else list(rows)
        data = struct.pack("<%d%s" % (len(flat), fmt), *flat)
        a = {"bufferView": self.view(data, target), "componentType": ctype,
             "count": len(rows), "type": gtype}
        if normalized:
            a["normalized"] = True
        if minmax:
            n = len(rows[0])
            a["min"] = [min(r[i] for r in rows) for i in range(n)]
            a["max"] = [max(r[i] for r in rows) for i in range(n)]
        self.accessors.append(a)
        return len(self.accessors) - 1


def glb_bytes(gl, binary):
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    binary = bytes(binary) + b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js +
            struct.pack("<I4s", len(binary), b"BIN\0") + binary)


def texture_png(xbr, mt, textures, extra=None):
    """(png bytes, alpha used, format) or None. extra: {id: .xbt bytes} looked at first."""
    blob = None
    if mt["flags"] & X.EMBEDDED_FLAG:
        blob = xbr["embedded"][mt["texture"]]
    elif extra and mt["texture"] in extra:
        blob = extra[mt["texture"]]
    elif textures and mt["texture"] != X.NO_TEXTURE:
        for p in (os.path.join(textures, "textures", "%04d.xbt" % mt["texture"]),
                  os.path.join(textures, "%04d.xbt" % mt["texture"])):
            if os.path.exists(p):
                with open(p, "rb") as f:
                    blob = f.read()
                break
    if blob is None:
        return None
    try:
        t = ts2xbt.Xbt(blob)
        rgba = ts2xbt.decode_level(t, 0)
    except ts2xbt.XbtError:
        return None
    w, h, _ = t.sizes[0]
    alpha = min(rgba[3::4]) < 255
    return ts2xbt.write_png(w, h, rgba), alpha, t.header.format


def load_bindposes(paths):
    """[(file name, bind pose)], human_19 first: railspiderbindpose also has 19 bones."""
    out = []
    for p in paths or []:
        files = [p]
        if os.path.isdir(p):
            files = sorted(os.path.join(p, f) for f in os.listdir(p)
                           if "bindpose" in f.lower() and f.lower().endswith(".raw"))
        for f in files:
            with open(f, "rb") as fh:
                try:
                    out.append((os.path.basename(f), X.read_bindpose(fh.read())))
                except X.XbrError:
                    pass
    return sorted(out, key=lambda nb: "human" not in nb[0].lower())


def export_glb(xbr, name="model", textures=None, bindposes=(), warn=print, extra_textures=None):
    bones = skeleton(xbr)
    world, bp_name = bind_transforms(xbr, bones, list(bindposes), warn)
    pnames = piece_names(xbr, bones)
    P = xbr["pieces"]
    g = GlbBuilder()
    nodes, meshes, materials, images, gtextures = [], [], [], [], []

    # materials
    sec1_mats = {r["material"] for p in P for s, sec in enumerate(p["sections"]) if sec and s == 1
                 for r in sec["records"]}
    for k, mt in enumerate(xbr["materials"]):
        m = {"name": material_name(k, mt),
             "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0},
             "extras": {"ts2xbr_material": k, "texture": mt["texture"], "flags": mt["flags"],
                        "embedded": bool(mt["flags"] & X.EMBEDDED_FLAG)}}
        tex = texture_png(xbr, mt, textures, extra_textures or xbr.get("new_textures"))
        if tex:
            png, alpha, _ = tex
            images.append({"name": m["name"], "mimeType": "image/png", "bufferView": g.view(png)})
            gtextures.append({"source": len(images) - 1, "sampler": 0})
            m["pbrMetallicRoughness"]["baseColorTexture"] = {"index": len(gtextures) - 1}
            if alpha:
                m["alphaMode"] = "BLEND" if k in sec1_mats else "MASK"
                if m["alphaMode"] == "MASK":
                    m["alphaCutoff"] = 0.5
        materials.append(m)

    # joints: nodes 0 .. nb-1 are the palette bones
    nb = len(bones)
    for b, info in enumerate(bones):
        t, q = world[b]
        pa = info["parent"]
        if pa >= 0:
            pt, pq = world[pa]
            lq = qnorm(X._qmul(qconj(pq), q))
            lt = X._qrot(qconj(pq), tuple(a - c for a, c in zip(t, pt)))
        else:
            lt, lq = t, q
        n = {"name": info["name"], "translation": [float(c) for c in lt], "rotation": [float(c) for c in lq],
             "extras": {"ts2xbr_bone": b, "piece": info["piece"], "kind": info["kind"]}}
        if info["kind"] == "anim":
            n["extras"]["anim_bone"] = info["anim"]
        nodes.append(n)
    roots = []
    for b, info in enumerate(bones):
        if info["parent"] >= 0:
            nodes[info["parent"]].setdefault("children", []).append(b)
        else:
            roots.append(b)
    ibm = [c for b in range(nb) for c in to_colmajor(rigid_inverse(*world[b]))]
    ibm_acc = g.accessor("f", [ibm[i:i + 16] for i in range(0, len(ibm), 16)], "MAT4", 5126, target=None)
    skin = {"name": name + "_skin", "joints": list(range(nb)), "inverseBindMatrices": ibm_acc,
            "skeleton": roots[0]}

    mesh_nodes = []
    for i, p in enumerate(P):
        own, allowed = piece_bone_sets(xbr, i)
        for s, sec in enumerate(p["sections"]):
            if not sec:
                continue
            verts = section_vertices(sec)
            by_mat = defaultdict(list)
            for mat, tri in section_triangles(sec):
                by_mat[mat].append(tri)
            prims = []
            for mat in sorted(by_mat, key=lambda m: (m < 0, m)):
                local = {}
                idx = []
                for tri in by_mat[mat]:
                    for v in tri:
                        if v not in local:
                            local[v] = len(local)
                        idx.append(local[v])
                order = sorted(local, key=local.get)
                vs = [verts[v] for v in order]
                pos = [(v[0], v[1], v[2]) for v in vs]
                nrm = [normalize3(v[7][:3]) if v[7] else (0.0, 1.0, 0.0) for v in vs]
                uv = [(v[4], v[5]) for v in vs]
                jb = [vertex_bone(p, v) for v in vs]
                attrs = {"POSITION": g.accessor("f", pos, "VEC3", 5126, minmax=True),
                         "NORMAL": g.accessor("f", nrm, "VEC3", 5126),
                         "TEXCOORD_0": g.accessor("f", uv, "VEC2", 5126)}
                if sec["has_col"]:
                    cols = [((c >> 16) & 255, (c >> 8) & 255, c & 255, (c >> 24) & 255) for c in (v[8] for v in vs)]
                    attrs["COLOR_0"] = g.accessor("B", cols, "VEC4", 5121, normalized=True)
                big = nb > 255
                attrs["JOINTS_0"] = g.accessor("H" if big else "B", [(b, 0, 0, 0) for b in jb], "VEC4",
                                               5123 if big else 5121)
                attrs["WEIGHTS_0"] = g.accessor("f", [(1.0, 0.0, 0.0, 0.0)] * len(vs), "VEC4", 5126)
                wide = len(vs) > 65535
                prim = {"attributes": attrs, "mode": 4,
                        "indices": g.accessor("I" if wide else "H", idx, "SCALAR", 5125 if wide else 5123,
                                              target=34963)}
                if mat >= 0:
                    prim["material"] = mat
                prims.append(prim)
            nm = node_name(i, s, pnames[i])
            recs = sec["records"]
            meshes.append({"name": nm, "primitives": prims})
            ex = {"ts2xbr_piece": i, "section": s, "type": p["type"], "type_name": X.TYPE_NAMES.get(p["type"]),
                  "bone": p["bone"], "parent": p["parent"], "child": p["child"], "sibling": p["sibling"],
                  "prev": p["prev"], "mask": p["mask"], "blend": float_of(p["blend_bits"]),
                  "allowed_bones": [bones[b]["name"] for b in allowed],
                  "records": [{"material": r["material"], "kind": r["kind"], "count": r["count"]} for r in recs],
                  "has_colours": sec["has_col"], "hat_collision": "collision" in sec}
            nodes.append({"name": nm, "mesh": len(meshes) - 1, "skin": 0, "extras": ex})
            mesh_nodes.append(len(nodes) - 1)

    m = xbr["model"]
    root = {"name": name, "children": roots + mesh_nodes,
            "extras": {"ts2xbr": {"version": 1, "pieces": len(P), "palette_bones": m["bone_count"],
                                  "flag8": m["flag8"], "scale": float_of(m["scale_bits"]),
                                  "word2c": m["word2c"], "word30": m["word30"], "bindpose": bp_name,
                                  "materials": len(xbr["materials"]), "embedded_textures": len(xbr["embedded"]),
                                  "pieces_without_geometry": [i for i, p in enumerate(P) if not any(p["sections"])],
                                  "note": "fromgltf takes everything but geometry from the base .xbr"}}}
    nodes.append(root)
    gl = {"asset": {"version": "2.0", "generator": "split2-recomp tools/ts2gltf.py"},
          "scene": 0, "scenes": [{"name": name, "nodes": [len(nodes) - 1]}],
          "nodes": nodes, "meshes": meshes, "materials": materials, "skins": [skin],
          "accessors": g.accessors, "bufferViews": g.views, "buffers": [{"byteLength": 0}]}
    if images:
        gl["images"] = images
        gl["textures"] = gtextures
        gl["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
    g.bin += b"\0" * (-len(g.bin) % 4)
    gl["buffers"][0]["byteLength"] = len(g.bin)
    return glb_bytes(gl, g.bin)


# --------------------------------------------------------------------------
# glTF reading

COMP = {5120: ("b", 1, 127.0), 5121: ("B", 1, 255.0), 5122: ("h", 2, 32767.0),
        5123: ("H", 2, 65535.0), 5125: ("I", 4, None), 5126: ("f", 4, None)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}


def read_gltf(path):
    with open(path, "rb") as f:
        data = f.read()
    buffers = []
    if data[:4] == b"glTF":
        _, ver, total = struct.unpack_from("<4sII", data, 0)
        if ver != 2:
            raise GltfError("glTF version %d, expected 2" % ver)
        pos, gl, binc = 12, None, b""
        while pos < min(total, len(data)):
            n, kind = struct.unpack_from("<I4s", data, pos)
            chunk = data[pos + 8:pos + 8 + n]
            if kind == b"JSON":
                gl = json.loads(chunk.decode("utf-8"))
            elif kind == b"BIN\0":
                binc = chunk
            pos += 8 + n + (-n % 4)
        if gl is None:
            raise GltfError("no JSON chunk")
    else:
        gl = json.loads(data.decode("utf-8"))
        binc = None
    for k, b in enumerate(gl.get("buffers", [])):
        uri = b.get("uri")
        if uri is None:
            buffers.append(binc or b"")
        elif uri.startswith("data:"):
            buffers.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            with open(os.path.join(os.path.dirname(os.path.abspath(path)), uri), "rb") as f:
                buffers.append(f.read())
    return gl, buffers


def read_accessor(gl, buffers, i):
    a = gl["accessors"][i]
    fmt, size, norm = COMP[a["componentType"]]
    n = NCOMP[a["type"]]
    count = a["count"]
    if "sparse" in a:
        raise GltfError("sparse accessor %d is not supported" % i)
    if "bufferView" not in a:
        return [tuple([0] * n)] * count
    bv = gl["bufferViews"][a["bufferView"]]
    buf = buffers[bv["buffer"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    elem = size * n
    stride = bv.get("byteStride") or elem
    if stride == elem:
        flat = struct.unpack_from("<%d%s" % (count * n, fmt), buf, base)
        rows = [flat[k * n:(k + 1) * n] for k in range(count)]
    else:
        rows = [struct.unpack_from("<%d%s" % (n, fmt), buf, base + k * stride) for k in range(count)]
    if a.get("normalized") and norm:
        rows = [tuple(max(c / norm, -1.0) for c in r) for r in rows]
    return rows


def node_worlds(gl):
    nodes = gl.get("nodes", [])
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i
    local = []
    for n in nodes:
        if "matrix" in n:
            local.append(from_colmajor(n["matrix"]))
        else:
            local.append(trs_mat(n.get("translation", (0, 0, 0)), n.get("rotation", (0, 0, 0, 1)),
                                 n.get("scale", (1, 1, 1))))
    world = [None] * len(nodes)

    def get(i):
        if world[i] is None:
            world[i] = mmul(get(parent[i]), local[i]) if i in parent else local[i]
        return world[i]
    for i in range(len(nodes)):
        get(i)
    return world


NAME_RE = re.compile(r"^p(\d+)s(\d+)(?:_|$|\.)")


def strip_suffix(name):
    return re.sub(r"\.\d{3}$", "", name or "")


# --------------------------------------------------------------------------
# Building sections


def stripify(tris):
    """Strips (lists of vertex ids) covering tris (oriented (a, b, c), distinct
    ids). Within a strip the triangle completed at position k is (k-2, k-1, k)
    for even k and (k-1, k-2, k) for odd k: plain strip winding, so no
    vertex needs the winding-flip bit."""
    edges = defaultdict(list)
    for t, (a, b, c) in enumerate(tris):
        edges[(a, b)].append(t)
        edges[(b, c)].append(t)
        edges[(c, a)].append(t)
    used = [False] * len(tris)

    def find(u, v, taken):
        for t in edges.get((u, v), ()):
            if not used[t] and t not in taken:
                a, b, c = tris[t]
                return t, (c if (a, b) == (u, v) else a if (b, c) == (u, v) else b)
        return None

    def grow(t, rot):
        a, b, c = tris[t]
        seq = [(a, b, c), (b, c, a), (c, a, b)][rot]
        strip = list(seq)
        taken = {t}
        while True:
            x, y = strip[-2], strip[-1]
            r = find(x, y, taken) if len(strip) % 2 == 0 else find(y, x, taken)
            if r is None:
                return strip, taken
            taken.add(r[0])
            strip.append(r[1])

    # start with triangles that have few neighbours
    nbr = [sum(1 for e in ((a, b), (b, c), (c, a)) if edges.get((e[1], e[0]))) for a, b, c in tris]
    order = sorted(range(len(tris)), key=lambda t: (nbr[t], t))
    strips = []
    for t in order:
        if used[t]:
            continue
        best = max((grow(t, r) for r in range(3)), key=lambda st: len(st[0]))
        for q in best[1]:
            used[q] = True
        strips.append(best[0])
    return strips


def split_strip(strip, limit=MAX_RECORD_VERTS):
    """Pieces of at most `limit` vertices, overlapping by two, cut at even
    offsets so every triangle keeps its winding."""
    if len(strip) <= limit:
        return [strip]
    out, s = [], 0
    step = limit - 2 - (limit % 2)
    while s + 2 < len(strip):
        out.append(strip[s:s + step + 2])
        s += step
    return out


def collision_from_records(records):
    """Hat collision rebuilt from geometry: one group per record, one
    triangle per polygon, plane from its corners, projection axes as the
    disc has them (last = the normal's largest axis, the other two in
    cyclic order when that component is positive), and no adjacency."""
    groups = []
    for rec in records:
        vs = [v[:3] for v in X.vertices(rec)]
        bb = [min(v[i] for v in vs) for i in range(3)] + [max(v[i] for v in vs) for i in range(3)]
        polys = []
        for a, b, c in X.strip_triangles(rec):
            A, B, C = vs[a], vs[b], vs[c]
            e1 = [B[i] - A[i] for i in range(3)]
            e2 = [C[i] - A[i] for i in range(3)]
            n = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
            if n[0] * n[0] + n[1] * n[1] + n[2] * n[2] < 1e-20:
                continue
            n = normalize3(n)
            dom = max(range(3), key=lambda i: abs(n[i]))
            ax = [(1, 2, 0), (2, 0, 1), (0, 1, 2)][dom]
            if n[dom] < 0:
                ax = (ax[1], ax[0], ax[2])
            d = sum(n[i] * A[i] for i in range(3))
            polys.append({"corners": [a, b, c], "axes": list(ax), "plane": struct.pack("<4f", *n, d),
                          "adjacency": b""})
        groups.append({"bbox": struct.pack("<6f", *bb), "polys": polys})
    return groups


def build_section(tris, vdata, base_sec, piece, report):
    """tris: [(material, (a, b, c))] over vdata ids; vdata: id -> vertex tuple
    (px, py, pz, nx, ny, nz, u, v, colour, bone). Returns a section dict."""
    base_kind = {}
    base_order = []
    kinds = Counter()
    if base_sec:
        for r in base_sec["records"]:
            base_kind.setdefault(r["material"], r["kind"])
            kinds[r["kind"]] += 1
            if r["material"] not in base_order:
                base_order.append(r["material"])
    default_kind = kinds.most_common(1)[0][0] if kinds else (2 if piece["type"] == 0 else 3)
    has_col = bool(base_sec and base_sec["has_col"])
    skinned = piece["type"] != 0
    by_mat = defaultdict(list)
    for mat, tri in tris:
        if len(set(tri)) == 3:
            by_mat[mat].append(tri)
    mats = [m for m in base_order if m in by_mat] + sorted(m for m in by_mat if m not in base_order)
    records = []
    for mat in mats:
        strips = []
        for st in stripify(by_mat[mat]):
            strips += split_strip(st)
        groups, cur = [], []
        for st in strips:
            if cur and len(cur) + len(st) > MAX_RECORD_VERTS:
                groups.append(cur)
                cur = []
            cur += [(v, k < 2) for k, v in enumerate(st)]
        if cur:
            groups.append(cur)
        run = []
        for grp in groups:
            pos, uv, col, nrm = bytearray(), bytearray(), bytearray(), bytearray()
            for vid, flagged in grp:
                d = vdata[vid]
                pos += struct.pack("<3fI", d[0], d[1], d[2], FLAG_W | (RESTART if flagged else 0))
                uv += struct.pack("<3f", d[6], d[7], 1.0)
                col += struct.pack("<I", d[8] if d[8] is not None else 0xFFFFFFFF)
                nrm += struct.pack("<3fI", d[3], d[4], d[5], d[9] if skinned else ONE_F)
            rec = {"material": mat, "kind": base_kind.get(mat, default_kind), "count": len(grp),
                   "pos": bytes(pos), "uv": bytes(uv), "col": bytes(col) if has_col else None,
                   "nrm": bytes(nrm), "faces": None}
            records.append(rec)
            run.append(rec)
        run_records_start = len(records) - len(run)
        # face list of the run on its last record, section-relative indices
        starts = X.section_starts({"records": records})
        faces = []
        for q, rec in enumerate(run):
            st = starts[run_records_start + q]
            faces += [st + v for tri in X.strip_triangles(rec) for v in tri]
        run[-1]["faces"] = faces
    if not records:
        return None
    sec = {"records": records, "has_col": has_col, "has_nrm": True}
    total = X.section_starts(sec)[-1] + records[-1]["count"]
    if total > MAX_SECTION_VERTS:
        raise GltfError("a section has %d vertices with padding; the format allows %d" % (total, MAX_SECTION_VERTS))
    if base_sec and "collision" in base_sec:
        sec["collision"] = collision_from_records(records)
        report.append("    hat collision rebuilt from the triangles (no adjacency records)")
    return sec


# --------------------------------------------------------------------------
# Triangle keys (comparison of sections)


def base_section_corners(piece, sec):
    """[(material, (vertex tuple x3))] of a stored section, vertex tuples as
    build_section takes them."""
    verts = section_vertices(sec)
    out = []
    conv = {}
    for mat, tri in section_triangles(sec):
        corners = []
        for i in tri:
            if i not in conv:
                v = verts[i]
                n = normalize3(v[7][:3]) if v[7] else (0.0, 1.0, 0.0)
                conv[i] = (v[0], v[1], v[2], n[0], n[1], n[2], v[4], v[5], v[8], vertex_bone(piece, v))
            corners.append(conv[i])
        out.append((mat, tuple(corners)))
    return out


def match_triangles(base_corners, got, pos_tol=1e-4, uv_tol=1e-4, normal_dot=0.996, col_tol=2):
    """Matches the corners of `got` ([(material, (vertex x3))]) to the base's
    vertices within tolerance (position, UV, bone; normal and colour unless
    normal_dot / col_tol is None) and compares the triangles as multisets,
    winding kept, vertex order and sharing free. Returns (triangles only in
    the base, only in got, the same two ignoring winding, largest angle in
    degrees between a matched corner's normal and the base's)."""
    cell = 1e-3
    ids, grid, verts = {}, {}, []

    def cellof(v):
        return (int(math.floor(v[0] / cell)), int(math.floor(v[1] / cell)), int(math.floor(v[2] / cell)))
    for _, tri in base_corners:
        for v in tri:
            if v not in ids:
                ids[v] = len(ids)
                verts.append(v)
                grid.setdefault(cellof(v), []).append(v)

    def close(a, b):
        if a[9] != b[9] or any(abs(a[q] - b[q]) > pos_tol for q in range(3)):
            return False
        if abs(a[6] - b[6]) > uv_tol or abs(a[7] - b[7]) > uv_tol:
            return False
        if normal_dot is not None and a[3] * b[3] + a[4] * b[4] + a[5] * b[5] < normal_dot:
            return False
        if col_tol is not None and a[8] is not None and b[8] is not None and \
                any(abs(((a[8] >> s) & 255) - ((b[8] >> s) & 255)) > col_tol for s in (0, 8, 16, 24)):
            return False
        return True
    memo = {}
    worst = [1.0]

    def match(v):
        """The closest base vertex within tolerance, or None."""
        if v in memo:
            return memo[v]
        c = cellof(v)
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for b in grid.get((c[0] + dx, c[1] + dy, c[2] + dz), ()):
                        if close(v, b):
                            err = (sum(abs(v[q] - b[q]) for q in (0, 1, 2, 6, 7)) +
                                   (1.0 - (v[3] * b[3] + v[4] * b[4] + v[5] * b[5])))
                            if best is None or err < best[0]:
                                best = (err, ids[b])
        memo[v] = best[1] if best else None
        if best:
            b = verts[best[1]]
            worst[0] = min(worst[0], v[3] * b[3] + v[4] * b[4] + v[5] * b[5])
        return memo[v]

    def canon(mat, t):
        r = min(range(3), key=lambda i: t[i])
        return (mat, t[r], t[(r + 1) % 3], t[(r + 2) % 3])
    a = Counter(canon(m, tuple(ids[v] for v in tri)) for m, tri in base_corners)
    b = Counter()
    unmatched = 0
    for m, tri in got:
        t = tuple(match(v) for v in tri)
        if None in t:
            unmatched += 1
        else:
            b[canon(m, t)] += 1
    ua = Counter({(k[0],) + tuple(sorted(k[1:])): n for k, n in a.items()})
    ub = Counter({(k[0],) + tuple(sorted(k[1:])): n for k, n in b.items()})
    angle = math.degrees(math.acos(max(-1.0, min(1.0, worst[0]))))
    return (sum((a - b).values()), sum((b - a).values()) + unmatched,
            sum((ua - ub).values()), sum((ub - ua).values()) + unmatched, angle)


def same_triangles(base_corners, got):
    """True when `got` is the base's triangles again, within tolerance."""
    if len(base_corners) != len(got):
        return False
    r = match_triangles(base_corners, got)
    return r[0] == 0 and r[1] == 0


def corner_key(v, full, nd=4):
    k = (round(v[0], nd), round(v[1], nd), round(v[2], nd), round(v[6], nd), round(v[7], nd), v[9])
    if full:
        k += (round(v[3], 2), round(v[4], 2), round(v[5], 2), v[8])
    return k


def tri_key(mat, corners, full=False, nd=4):
    ks = [corner_key(v, full, nd) for v in corners]
    r = min(range(3), key=lambda i: ks[i])
    return (mat, ks[r], ks[(r + 1) % 3], ks[(r + 2) % 3])


def model_triangles(xbr, nd=None):
    """Counter of (piece, section, material, corner, corner, corner), each
    corner (x, y, z, u, v, bone), rotated to start at its smallest corner
    (winding kept). nd rounds positions and UVs; None keeps them exact."""
    out = Counter()
    for i, p in enumerate(xbr["pieces"]):
        for s, sec in enumerate(p["sections"]):
            if not sec:
                continue
            for mat, corners in base_section_corners(p, sec):
                if len({c[:3] for c in corners}) < 3:
                    continue           # degenerate
                if nd is None:
                    ks = [(c[0], c[1], c[2], c[6], c[7], c[9]) for c in corners]
                    r = min(range(3), key=lambda q: ks[q])
                    out[(i, s, mat, ks[r], ks[(r + 1) % 3], ks[(r + 2) % 3])] += 1
                else:
                    out[(i, s) + tri_key(mat, corners, False, nd)] += 1
    return out


# --------------------------------------------------------------------------
# Materials and textures of a written model

# Texture ids for new textures. The PAL disc uses ids 0 to 5293 (4,113 ids
# in the 68 paks, and every id an .xbr material names is among them), so
# 8000-9999 is free and keeps the four-digit names. The loader looks a
# texture up by id in a list it searches, with no table indexed by id
# (code sub_001B8290), so any id below 0x40000000 would load.
NEW_TEXTURE_FIRST, NEW_TEXTURE_LAST = 8000, 9999
CHRINC_LIMIT = 512000          # the front end's per-slot buffer (0x7D000)
TEX_NAME_RE = re.compile(r"^m(\d+)_t(\d+)$")
EMB_NAME_RE = re.compile(r"^m(\d+)_emb(\d+)$")
NONE_NAME_RE = re.compile(r"^m(\d+)_none$")
INDEX_NAME_RE = re.compile(r"^m(\d+)$")


def is_embedded_model(xbr):
    """A chrinc.pak preview: its materials carry their textures."""
    return bool(xbr["materials"]) and all(m["flags"] & X.EMBEDDED_FLAG for m in xbr["materials"])


def find_xbt(folder, tid):
    if not folder:
        return None
    for p in (os.path.join(folder, "textures", "%04d.xbt" % tid), os.path.join(folder, "%04d.xbt" % tid)):
        if os.path.exists(p):
            with open(p, "rb") as f:
                return f.read()
    return None


def texture_dir_for(output):
    """Where new textures go: <mod>/files/textures when the output is under a
    ts2mod files/ folder, else a textures/ folder beside the output."""
    d = os.path.dirname(os.path.abspath(output))
    probe = d
    while True:
        if os.path.basename(probe).lower() == "files":
            return os.path.join(probe, "textures")
        up = os.path.dirname(probe)
        if up == probe:
            return os.path.join(d, "textures")
        probe = up


class Materials:
    """The material list of the model being written. Starts as the base's;
    materials the new geometry needs are added (a texture id, an embedded
    .xbt or a new picture), and finish() drops the base's materials that no
    record uses any more.

    textures: folder of NNNN.xbt (an unpacked chr.pak), for ids that must
    be embedded (chrinc base) or compared (retexture). counterpart: the
    chr.pak model of a chrinc base (same material order, measured for all
    154 pairs), to tell which embedded material a texture id stands for.
    texture_dir: where new .xbt files would go (to keep ids already used
    there for other pictures)."""

    def __init__(self, base, textures=None, texture_dir=None, counterpart=None, retexture=False):
        self.base = base
        self.embed = is_embedded_model(base)
        self.mats = [dict(m) for m in base["materials"]]
        self.embedded = list(base["embedded"])
        self.base_count = len(self.mats)
        self.textures = textures
        self.texture_dir = texture_dir
        self.counterpart = counterpart
        self.retexture = retexture
        self.new_textures = {}           # id -> .xbt bytes, to be written
        self.notes = []
        self._gl_cache = {}

    # -- adding
    def _append(self, mat):
        for k, m in enumerate(self.mats):
            if m["texture"] == mat["texture"] and m["flags"] == mat["flags"]:
                return k
        self.mats.append(dict(mat, word4=0, word8=0))
        return len(self.mats) - 1

    def by_blob(self, blob):
        """An embedded texture (chrinc base)."""
        for k, m in enumerate(self.mats):
            if m["flags"] & X.EMBEDDED_FLAG and self.embedded[m["texture"]] == blob:
                return k
        self.embedded.append(blob)
        return self._append({"texture": len(self.embedded) - 1, "flags": X.EMBEDDED_FLAG})

    def by_id(self, tid, flags=0):
        if self.embed:
            blob = find_xbt(self.textures, tid) or self.new_textures.get(tid)
            if blob is None:
                raise GltfError("texture %04d has to be embedded in this chrinc model: pass --textures "
                                "<unpacked chr.pak> (or the folder holding %04d.xbt)" % (tid, tid))
            return self.by_blob(blob)
        for k, m in enumerate(self.mats):
            if not m["flags"] & X.EMBEDDED_FLAG and m["texture"] == tid:
                return k            # keeps that material's flags
        return self._append({"texture": tid, "flags": flags & ~X.EMBEDDED_FLAG})

    def untextured(self):
        return self._append({"texture": X.NO_TEXTURE, "flags": X.EMBEDDED_FLAG if self.embed else 0})

    def allocate(self, xbt):
        """A free id for a new texture: from the picture's CRC within the free
        range, so the same picture gets the same id again, skipping ids
        that hold another picture (in texture_dir or --textures)."""
        span = NEW_TEXTURE_LAST - NEW_TEXTURE_FIRST + 1
        start = zlib.crc32(xbt) % span
        for k in range(span):
            tid = NEW_TEXTURE_FIRST + (start + k) % span
            if tid in self.new_textures:
                if self.new_textures[tid] == xbt:
                    return tid
                continue
            have = find_xbt(self.textures, tid)
            if have is None and self.texture_dir:
                p = os.path.join(self.texture_dir, "%04d.xbt" % tid)
                if os.path.exists(p):
                    with open(p, "rb") as f:
                        have = f.read()
            if have is None or have == xbt:
                self.new_textures[tid] = xbt
                return tid
        raise GltfError("no free texture id left in %d-%d" % (NEW_TEXTURE_FIRST, NEW_TEXTURE_LAST))

    def by_xbt(self, xbt):
        """A new texture: embedded in a chrinc base, else under a new id."""
        if self.embed:
            return self.by_blob(xbt)
        tid = self.allocate(xbt)
        self.notes.append("new texture %04d.xbt (%d bytes)" % (tid, len(xbt)))
        return self.by_id(tid)

    def from_model(self, other, k):
        """Material k of another model (a graft donor)."""
        if k < 0:
            return k
        m = other["materials"][k]
        if m["flags"] & X.EMBEDDED_FLAG:
            blob = other["embedded"][m["texture"]]
            return self.by_blob(blob) if self.embed else self.by_xbt(blob)
        if m["texture"] == X.NO_TEXTURE:
            return self.untextured()
        return self.by_id(m["texture"], m["flags"])

    # -- glTF materials
    def _image(self, gl, buffers, gm, path):
        """(width, height, rgba) of a glTF material's base colour image, or None."""
        ti = (gm.get("pbrMetallicRoughness") or {}).get("baseColorTexture", {}).get("index")
        if ti is None:
            return None
        src = gl["textures"][ti].get("source")
        if src is None:
            return None
        img = gl["images"][src]
        if "bufferView" in img:
            bv = gl["bufferViews"][img["bufferView"]]
            data = buffers[bv["buffer"]][bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]]
        elif img.get("uri", "").startswith("data:"):
            data = base64.b64decode(img["uri"].split(",", 1)[1])
        else:
            with open(os.path.join(os.path.dirname(os.path.abspath(path)), img["uri"]), "rb") as f:
                data = f.read()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise GltfError("material '%s': its image is not a PNG (export the .glb with images as PNG)"
                            % gm.get("name"))
        return ts2xbt.read_png(bytes(data))

    def _same_picture(self, img, xbt):
        try:
            t = ts2xbt.Xbt(xbt)
        except ts2xbt.XbtError:
            return False
        w, h, _ = t.sizes[0]
        if (w, h) != img[:2]:
            return False
        a = ts2xbt.decode_level(t, 0)
        b = img[2]
        return max(abs(a[i] - b[i]) for i in range(len(a))) <= 2

    def _changed(self, img, tid=None, blob=None):
        """--retexture: the glTF's picture is not the texture's."""
        if not self.retexture or img is None:
            return False
        if blob is None:
            blob = find_xbt(self.textures, tid)
        return blob is None or not self._same_picture(img, blob)

    def resolve(self, gl, buffers, gi, path):
        """Output material index of glTF material gi."""
        if gi in self._gl_cache:
            return self._gl_cache[gi]
        gm = gl["materials"][gi]
        name = strip_suffix(gm.get("name", ""))
        img = self._image(gl, buffers, gm, path)
        nb = self.base_count
        bm = self.base["materials"]
        k = None
        m = TEX_NAME_RE.match(name)
        if m:
            n, tid = int(m.group(1)), int(m.group(2))
            if self.embed:
                k = self._embedded_for(n, tid, img)
            elif n < nb and bm[n]["texture"] == tid and not bm[n]["flags"] & X.EMBEDDED_FLAG \
                    and not self._changed(img, tid):
                k = n
            elif not self._changed(img, tid):
                k = self.by_id(tid)
        m = EMB_NAME_RE.match(name)
        if m and k is None:
            n, e = int(m.group(1)), int(m.group(2))
            if self.embed and n < nb and bm[n]["texture"] == e and not self._changed(img, blob=self.embedded[e]):
                k = n
        m = NONE_NAME_RE.match(name)
        if m and k is None:
            n = int(m.group(1))
            k = n if n < nb and bm[n]["texture"] == X.NO_TEXTURE else self.untextured()
        m = INDEX_NAME_RE.match(name)
        if m and k is None and int(m.group(1)) < nb:
            k = int(m.group(1))
        if k is None:
            if img is None:
                self.notes.append("material '%s' has no texture id in its name (mN_tNNNN) and no image: "
                                  "drawn untextured" % gm.get("name"))
                k = self.untextured()
            else:
                k = self.by_xbt(ts2xbt.new_xbt(img[2], img[0], img[1]))
                self.notes.append("material '%s': its %dx%d image became material %d" % (gm.get("name"), img[0], img[1], k))
        self._gl_cache[gi] = k
        return k

    def _embedded_for(self, n, tid, img):
        """Material for 'mN_tTTTT' over a chrinc base."""
        bm = self.base["materials"]
        if self.counterpart is not None:
            cm = self.counterpart["materials"]
            same = [q for q in range(min(len(cm), len(bm))) if cm[q]["texture"] == tid]
            if same and not self._changed(img, blob=self.embedded[bm[same[0]]["texture"]]):
                return same[0]
            if self._changed(img, tid):
                return None
            return self.by_id(tid)
        if n < len(bm) and not self.retexture:
            self.notes.append("material m%d_t%04d mapped to the chrinc model's material %d by index (no chr.pak "
                              "counterpart found; pass --textures <unpacked chr.pak>)" % (n, tid, n))
            return n
        return None if self._changed(img, tid) else self.by_id(tid)

    # -- the final list
    def finish(self, pieces):
        """Drops base materials no record uses any more (and their embedded
        textures), keeps the rest in order; returns (materials, embedded,
        pieces with records renumbered)."""
        used = {r["material"] for p in pieces for sec in p["sections"] if sec for r in sec["records"]}
        base_used = {r["material"] for p in self.base["pieces"] for sec in p["sections"] if sec
                     for r in sec["records"]}
        keep = [k for k in range(len(self.mats)) if k in used or (k < self.base_count and k not in base_used)]
        if len(keep) == len(self.mats):
            remap = None
        else:
            remap = {k: q for q, k in enumerate(keep)}
            remap[-1] = -1
            dropped = [k for k in range(self.base_count) if k not in remap]
            if dropped:
                self.notes.append("base materials no longer used, dropped: %s" % ", ".join(
                    material_name(k, self.base["materials"][k]) for k in dropped))
        mats = [dict(self.mats[k]) for k in keep]
        emb_used = sorted({m["texture"] for m in mats if m["flags"] & X.EMBEDDED_FLAG})
        embedded = [self.embedded[e] for e in emb_used]
        emap = {e: q for q, e in enumerate(emb_used)}
        for m in mats:
            if m["flags"] & X.EMBEDDED_FLAG:
                m["texture"] = emap[m["texture"]]
        if remap:
            out = []
            for p in pieces:
                np_ = dict(p)
                np_["sections"] = [dict(sec, records=[dict(r, material=remap[r["material"]]) for r in sec["records"]])
                                   if sec else None for sec in p["sections"]]
                out.append(np_)
            pieces = out
        return mats, embedded, pieces


def write_textures(new_textures, texture_dir):
    """Writes the new .xbt files; returns their paths."""
    out = []
    if new_textures:
        os.makedirs(texture_dir, exist_ok=True)
    for tid, blob in sorted(new_textures.items()):
        p = os.path.join(texture_dir, "%04d.xbt" % tid)
        with open(p, "wb") as f:
            f.write(blob)
        out.append(p)
    return out


def finish_model(base, pieces, model, mt):
    """The new model dict, with materials pruned and the chrinc size checked."""
    mats, embedded, pieces = mt.finish(pieces)
    new = {"materials": mats, "model": model, "embedded": embedded, "pieces": pieces,
           "new_textures": dict(mt.new_textures)}
    return new


def check_size(data, xbr):
    if is_embedded_model(xbr) and len(data) > CHRINC_LIMIT:
        sizes = ", ".join("%d" % len(b) for b in xbr["embedded"])
        raise GltfError("the chrinc model is %d bytes, over the front end's %d-byte buffer (embedded "
                        "textures: %s bytes); use smaller pictures or fewer materials"
                        % (len(data), CHRINC_LIMIT, sizes))


# --------------------------------------------------------------------------
# Import


def piece_lookup(base, bones):
    """Maps a glTF object name to (piece, section) of the base: by pNN when
    the base's piece NN has the name after pNNsS_, else by that name (so
    objects from another model's export land on the matching piece)."""
    pnames = piece_names(base, bones)

    def lookup(name, report):
        nm = strip_suffix(name)
        m = NAME_RE.match(nm)
        if not m:
            return None
        pi, s = int(m.group(1)), int(m.group(2))
        suffix = nm[m.end():] if nm[m.end() - 1:m.end()] == "_" else ""
        if not suffix or (pi < len(pnames) and pnames[pi] == suffix):
            return pi, s
        if suffix in pnames:
            k = pnames.index(suffix)
            report.append("object '%s': piece %d of the base is '%s'; placed on piece %d ('%s')"
                          % (name, pi, pnames[pi] if pi < len(pnames) else "-", k, suffix))
            return k, s
        if suffix in HUMAN19_NAMES or any(suffix.startswith(a) for a in ("joint_", "bridge_", "mid_")):
            raise GltfError("object '%s': the base model has no piece '%s' (use `ts2gltf.py graft`, which "
                            "adds the joint pieces a donor brings)" % (name, suffix))
        return pi, s
    return lookup


def import_glb(base, path, regenerate=False, bindposes=(), materials=None):
    """Returns (new xbr dict, report lines, stats dict). The new model's
    "new_textures" holds {id: .xbt bytes} for pictures that need a new id.
    bindposes: when given, every skinned vertex is placed by its bone's bind
    transform in the base (so pieces exported from another model of another
    scale land at this model's joints)."""
    gl, buffers = read_gltf(path)
    P = base["pieces"]
    bones = skeleton(base)
    world_bind, bp_name = bind_transforms(base, bones, list(bindposes), lambda m: None)
    bind_mats = [trs_mat(t, q) for t, q in world_bind] if bp_name else None
    name_to_bone = {b["name"]: k for k, b in enumerate(bones)}
    nodes = gl.get("nodes", [])
    worlds = node_worlds(gl)
    report = []
    stats = Counter()
    mt = materials or Materials(base)
    lookup = piece_lookup(base, bones)

    def joint_palette(node_index):
        nm = nodes[node_index].get("name", "")
        for cand in (nm, strip_suffix(nm)):
            if cand in name_to_bone:
                return name_to_bone[cand]
        ex = nodes[node_index].get("extras") or {}
        if isinstance(ex.get("ts2xbr_bone"), int) and 0 <= ex["ts2xbr_bone"] < len(bones):
            return ex["ts2xbr_bone"]
        return None     # a bone the base lacks (another model's mid-joint): only an error if a vertex uses it

    skins = []
    for sk in gl.get("skins", []):
        joints = sk["joints"]
        ibm = (read_accessor(gl, buffers, sk["inverseBindMatrices"]) if "inverseBindMatrices" in sk
               else [to_colmajor(ident())] * len(joints))
        palette = [joint_palette(j) for j in joints]
        # with a bind pose: the bone's bind in the base, not the joint's place
        # in the glTF, so a piece from another model's skeleton lands at this
        # model's joint
        mats = [mmul(bind_mats[b] if bind_mats and b is not None else worlds[j], from_colmajor(m))
                for b, j, m in zip(palette, joints, ibm)]
        skins.append({"palette": palette, "mats": mats, "ident": [near_identity(m) for m in mats],
                      "names": [nodes[j].get("name", "") for j in joints],
                      "at": {b: tuple(worlds[j][r][3] for r in range(3)) for b, j in zip(palette, joints)
                             if b is not None}})
    if not bind_mats and len(skins) > 1:
        far = max((max(abs(a - c) for a, c in zip(sa["at"][b], sb["at"][b]))
                   for sa in skins for sb in skins for b in sa["at"] if b in sb["at"]), default=0.0)
        if far > 1e-3:
            report.append("warning: the glTF's armatures put the same bone up to %.3f apart; pass --bindpose so "
                          "pieces from another model are placed at this model's joints" % far)

    collected = defaultdict(list)    # (piece, section) -> [(material, (v, v, v))]
    for ni, node in enumerate(nodes):
        if "mesh" not in node:
            continue
        mesh = gl["meshes"][node["mesh"]]
        found = lookup(node.get("name", ""), report) or lookup(mesh.get("name", ""), report)
        if not found:
            report.append("skipped object '%s': its name does not start with pNNsS" % node.get("name"))
            continue
        pi, s = found
        if pi >= len(P) or s > 1:
            raise GltfError("object '%s' names piece %d section %d; the base has %d pieces and sections 0-1"
                            % (node.get("name"), pi, s, len(P)))
        piece = P[pi]
        own, allowed = piece_bone_sets(base, pi)
        skin = skins[node["skin"]] if "skin" in node else None
        # alpha for colours written without one (Blender writes RGB only on
        # some meshes): the base section's (127 in every coloured vertex on the disc)
        bsec0 = piece["sections"][s]
        base_alpha = 255
        if bsec0 and bsec0["has_col"]:
            base_alpha = Counter(v[8] >> 24 for r in bsec0["records"] for v in X.vertices(r)).most_common(1)[0][0]
        nworld = worlds[ni]
        nident = near_identity(nworld)
        for prim in mesh["primitives"]:
            mode = prim.get("mode", 4)
            if mode != 4:
                raise GltfError("object '%s': primitive mode %d, only triangles (4) are supported" % (node.get("name"), mode))
            at = prim["attributes"]
            if "POSITION" not in at:
                continue
            pos = read_accessor(gl, buffers, at["POSITION"])
            nv = len(pos)
            nrm = read_accessor(gl, buffers, at["NORMAL"]) if "NORMAL" in at else None
            uvs = read_accessor(gl, buffers, at["TEXCOORD_0"]) if "TEXCOORD_0" in at else None
            cols = read_accessor(gl, buffers, at["COLOR_0"]) if "COLOR_0" in at else None
            if uvs is None:
                stats["no_uv"] += nv
            sets = []
            q = 0
            while "JOINTS_%d" % q in at and "WEIGHTS_%d" % q in at:
                sets.append((read_accessor(gl, buffers, at["JOINTS_%d" % q]),
                             read_accessor(gl, buffers, at["WEIGHTS_%d" % q])))
                q += 1
            mat = mt.resolve(gl, buffers, prim["material"], path) if "material" in prim else -1
            idx = read_accessor(gl, buffers, prim["indices"]) if "indices" in prim else [(k,) for k in range(nv)]
            idx = [r[0] for r in idx]
            verts = []
            for k in range(nv):
                weights = defaultdict(float)
                mats = []
                if skin:
                    for js, ws in sets:
                        for j, w in zip(js[k], ws[k]):
                            if w > 0:
                                if skin["palette"][int(j)] is None:
                                    raise GltfError("object '%s' is weighted to joint '%s', which is not a bone of "
                                                    "the base model" % (node.get("name"), skin["names"][int(j)]))
                                weights[skin["palette"][int(j)]] += w
                                mats.append((w, int(j)))
                p = pos[k]
                n = nrm[k] if nrm else (0.0, 1.0, 0.0)
                tw = sum(w for w, _ in mats)
                if mats and tw > 0:
                    if not all(skin["ident"][j] for _, j in mats):
                        # rest pose differs from the bind: skin it (a pure bind gives the stored positions)
                        acc = [[sum(w * skin["mats"][j][r][c] for w, j in mats) / tw for c in range(4)] for r in range(4)]
                        p = xform(acc, p)
                        n = xform(acc, n, 0.0)
                else:
                    if skin:
                        stats["unweighted"] += 1
                    if not nident:
                        p = xform(nworld, p)
                        n = xform(nworld, n, 0.0)
                # bone
                if piece["type"] == 0:
                    bone = own
                    if weights and max(weights, key=weights.get) != own:
                        stats["snapped"] += 1
                else:
                    cand = [(weights.get(b, 0.0), b) for b in allowed]
                    best = max(cand)
                    if best[0] > 0:
                        bone = best[1]
                    else:
                        bone = min(allowed, key=lambda b: sum((p[i] - world_bind[b][0][i]) ** 2 for i in range(3)))
                    if weights and max(weights, key=weights.get) != bone:
                        stats["snapped"] += 1
                n = normalize3(n)
                if cols:
                    c = cols[k]
                    c4 = [min(255, max(0, int(round(x * 255.0)))) for x in c[:4]]
                    c4 += [255] * (3 - len(c4)) + ([base_alpha] if len(c4) < 4 else [])
                    colour = (c4[3] << 24) | (c4[0] << 16) | (c4[1] << 8) | c4[2]
                else:
                    colour = None
                u, v = (uvs[k][0], uvs[k][1]) if uvs else (0.0, 0.0)
                verts.append((f32(p[0]), f32(p[1]), f32(p[2]), f32(n[0]), f32(n[1]), f32(n[2]),
                              f32(u), f32(v), colour, bone))
            for t in range(0, len(idx) - 2, 3):
                collected[(pi, s)].append((mat, (verts[idx[t]], verts[idx[t + 1]], verts[idx[t + 2]])))
            stats["vertices_in"] += nv

    pieces = []
    for i, p in enumerate(P):
        np_ = dict(p)
        np_["sections"] = list(p["sections"])
        for s in range(X.SECTIONS):
            bsec = p["sections"][s]
            got = collected.get((i, s))
            label = "piece %d section %d" % (i, s)
            if not got:
                if bsec:
                    report.append("%s: not in the glTF, removed" % label)
                    stats["sections_removed"] += 1
                np_["sections"][s] = None
                continue
            # colours the base has but the glTF lost: nearest base vertex
            if bsec and bsec["has_col"] and any(v[8] is None for _, tri in got for v in tri):
                bverts = [(v[:3], v[8]) for v in section_vertices(bsec)]
                cache = {}

                def nearest(v):
                    if v[:3] not in cache:
                        cache[v[:3]] = min(bverts, key=lambda b: sum((b[0][q] - v[q]) ** 2 for q in range(3)))[1]
                    return cache[v[:3]]
                got = [(m, tuple(v if v[8] is not None else v[:8] + (nearest(v), v[9]) for v in tri)) for m, tri in got]
                report.append("%s: no vertex colours in the glTF; took the nearest base vertex's" % label)
            if bsec and not regenerate:
                if same_triangles(base_section_corners(p, bsec), got):
                    stats["sections_kept"] += 1
                    continue
            vid = {}
            vdata = []
            tris = []
            for m, tri in got:
                ids = []
                for v in tri:
                    if v not in vid:
                        vid[v] = len(vdata)
                        vdata.append(v)
                    ids.append(vid[v])
                tris.append((m, tuple(ids)))
            lines = []
            sec = build_section(tris, vdata, bsec, p, lines)
            np_["sections"][s] = sec
            if sec:
                nverts = sum(r["count"] for r in sec["records"])
                ntris = sum(len(r["faces"]) // 3 for r in sec["records"] if r["faces"])
                bv = sum(r["count"] for r in bsec["records"]) if bsec else 0
                report.append("%s: rebuilt, %d triangles, %d unique vertices -> %d strip vertices in %d records (base %d)"
                              % (label, ntris, len(vdata), nverts, len(sec["records"]), bv))
                report += lines
                stats["sections_rebuilt"] += 1
        pieces.append(np_)
    new = finish_model(base, pieces, base["model"], mt)
    report += mt.notes
    return new, report, stats


# --------------------------------------------------------------------------
# Graft: pieces of one model onto another


def anim_bones_named(xbr, spec):
    """Animation bones from a comma-separated list: 'head', 'b04_head' or '4'."""
    bones = [b for b in skeleton(xbr) if b["kind"] == "anim"]
    out = []
    for tok in (t.strip() for t in spec.split(",")):
        if not tok:
            continue
        k = int(tok) if tok.isdigit() else next((b["anim"] for b in bones if tok in (b["name"], b["short"])), None)
        if k is None or not 0 <= k < len(bones):
            raise GltfError("'%s' is not an animation bone of the model (%s)"
                            % (tok, ", ".join(b["short"] for b in sorted(bones, key=lambda b: b["anim"]))))
        if k not in out:
            out.append(k)
    return out


def connectors(pieces, rigid):
    """Pieces of types 1-3 bound to one of the given pieces (as c64 or c68)."""
    return [i for i, p in enumerate(pieces) if p["type"] != 0 and (p["parent"] in rigid or p["child"] in rigid)]


def _new_piece(ptype, parent, child, blend_bits):
    return {"type": ptype, "bone": -1, "parent": parent, "child": child, "sibling": -1, "prev": -1,
            "pad": [0, 0], "mask": 0, "state": [0, 0, 0, 0], "blend_bits": blend_bits,
            "stat_verts": 0, "stat_tris": 0, "sections": [None] * X.SECTIONS}


def insert_between(P, a, b, ptype, blend_bits):
    """A joint piece between piece a and its tree child b: it takes b's place
    in a's child list and b becomes its child. Returns its index."""
    j = len(P)
    q = _new_piece(ptype, a, b, blend_bits)
    q["sibling"], q["prev"] = P[b]["sibling"], P[b]["prev"]
    P.append(q)
    if P[a]["child"] == b:
        P[a]["child"] = j
    elif q["prev"] >= 0:
        P[q["prev"]]["sibling"] = j
    if q["sibling"] >= 0:
        P[q["sibling"]]["prev"] = j
    P[b]["parent"], P[b]["sibling"], P[b]["prev"] = j, -1, -1
    return j


def append_bridge(P, a, b):
    """A bridge piece (type 3) from a to b, last in a's child list."""
    j = len(P)
    q = _new_piece(3, a, b, ONE_F)
    P.append(q)
    if P[a]["child"] < 0:
        P[a]["child"] = j
    else:
        last = P[a]["child"]
        while P[last]["sibling"] >= 0:
            last = P[last]["sibling"]
        P[last]["sibling"] = j
        q["prev"] = last
    return j


def graft(base, donor, anim_bones, bindposes=(), materials=None):
    """The base model with the pieces of the given animation bones, and the
    joint and bridge pieces bound to them, taken from the donor. The two
    must share their animation skeleton. Joint pieces the base lacks are
    added to its tree (a mid-joint gets a new palette bone). With a bind
    pose, each donor vertex keeps its place relative to its bone and is
    moved to that bone's bind in the base (the models have different
    skeleton scales). Returns (new xbr dict, report lines, stats)."""
    sk_b, sk_d = X.rigid_skeleton(base), X.rigid_skeleton(donor)
    if [pa for _, pa in sk_b] != [pa for _, pa in sk_d]:
        raise GltfError("the models have different skeletons (%d and %d animation bones)" % (len(sk_b), len(sk_d)))
    report, stats = [], Counter()
    mt = materials or Materials(base)
    bones_b, bones_d = skeleton(base), skeleton(donor)
    names_d = piece_names(donor, bones_d)
    D = donor["pieces"]
    P = [dict(p, sections=list(p["sections"])) for p in base["pieces"]]
    model = dict(base["model"])
    anim_d = {pi: k for k, (pi, _) in enumerate(sk_d)}
    sel_d = {sk_d[k][0] for k in anim_bones}
    sel_b = {sk_b[k][0] for k in anim_bones}
    clear = sel_b | set(connectors(base["pieces"], sel_b))
    target = {sk_d[k][0]: sk_b[k][0] for k in anim_bones}
    linked = {}

    def base_piece(di):
        if di < 0:
            return None
        if di in target:
            return target[di]
        if di in linked:
            return linked[di]
        p = D[di]
        if p["type"] == 0:
            return sk_b[anim_d[di]][0]
        if p["type"] == 2:      # a mid-joint at the end of a bridge: the base's, made one if need be
            a, b = base_piece(p["parent"]), base_piece(p["child"])
            if a is None or b is None:
                return None
            j = between(a, b, p, names_d[di])
            if j is not None:
                linked[di] = j       # its bone and place only; its geometry stays the base's
            return j
        return None

    def between(a, b, c, label):
        """The base's joint piece from a to its child b for donor piece c
        (type 1 or 2): found, made a mid-joint, or added. None if b is not a's child."""
        j = next((j for j, q in enumerate(P) if q["type"] in (1, 2) and (q["parent"], q["child"]) == (a, b)), None)
        if j is None:
            if P[b]["parent"] != a:
                return None
            j = insert_between(P, a, b, c["type"], c["blend_bits"] if c["type"] == 2 else ONE_F)
            if c["type"] == 2:
                P[j]["bone"] = new_bone()
            report.append("added piece %d (%s) between pieces %d and %d" % (j, label, a, b))
        elif c["type"] == 2 and P[j]["type"] == 1:
            P[j].update(type=2, bone=new_bone(), blend_bits=c["blend_bits"])
            report.append("piece %d made a mid-joint (%s), with new palette bone %d" % (j, label, P[j]["bone"]))
        return j

    def new_bone():
        model["bone_count"] += 1
        if model["bone_count"] > 127:
            raise GltfError("more than 127 palette bones")
        return model["bone_count"] - 1

    taken = set()
    for di in sorted(connectors(D, sel_d), key=lambda i: D[i]["type"] == 3):
        c = D[di]
        a, b = base_piece(c["parent"]), base_piece(c["child"])
        if a is None or b is None:
            report.append("donor piece %d (%s): the base has no piece at one of its ends; left out" % (di, names_d[di]))
            continue
        if c["type"] in (1, 2):
            j = between(a, b, c, names_d[di])
            if j is None:
                report.append("donor piece %d (%s): no place for it in the base's tree; left out" % (di, names_d[di]))
                continue
        else:
            j = next((j for j, q in enumerate(P) if q["type"] == 3 and (q["parent"], q["child"]) == (a, b)
                      and j not in taken), None)
            if j is None:
                j = append_bridge(P, a, b)
                report.append("added piece %d (%s)" % (j, names_d[di]))
        taken.add(j)
        target[di] = j
    if len(P) > 127:
        raise GltfError("more than 127 pieces")

    def map_bone(bd):
        j = base_piece(bones_d[bd]["piece"])
        return P[j]["bone"] if j is not None and P[j]["bone"] >= 0 else None
    for di, j in target.items():          # a bridge's own bone
        if D[di]["type"] == 3:
            P[j]["bone"] = map_bone(D[di]["bone"]) if D[di]["bone"] >= 0 else -1
            if P[j]["bone"] is None:
                P[j]["bone"] = -1
    nb_old = base["model"]["bone_count"]

    # bind transforms: donor bone -> base bone
    wb, bpb = bind_transforms(base, bones_b, list(bindposes), lambda m: None)
    wd, bpd = bind_transforms(donor, bones_d, list(bindposes), lambda m: None)
    sb, sd = float_of(base["model"]["scale_bits"]) or 1.0, float_of(donor["model"]["scale_bits"]) or 1.0
    if not (bpb and bpd) and abs(sb - sd) > 1e-6:
        report.append("warning: skeleton scales differ (base %.3g, donor %.3g) and there is no --bindpose: the "
                      "donor's pieces stay where they were in the donor" % (sb, sd))

    def bind_b(bb):
        if bb < nb_old:
            return wb[bb]
        j = next(i for i, q in enumerate(P) if q["bone"] == bb and q["type"] == 2)
        return wb[P[P[j]["child"]]["bone"]]       # a mid bone binds at its c68 bone
    xf_cache = {}

    def xf(bd, bb):
        if not (bpb and bpd):
            return None
        if (bd, bb) not in xf_cache:
            m = mmul(trs_mat(*bind_b(bb)), rigid_inverse(*wd[bd]))
            xf_cache[(bd, bb)] = None if near_identity(m) else m
        return xf_cache[(bd, bb)]

    for i in clear:
        P[i]["sections"] = [None] * X.SECTIONS
    view = {"pieces": P}
    for di, j in sorted(target.items(), key=lambda t: t[1]):
        own, allowed = piece_bone_sets(view, j)
        for s in range(X.SECTIONS):
            dsec = D[di]["sections"][s]
            if not dsec:
                P[j]["sections"][s] = None
                continue
            vid, vdata, tris = {}, [], []
            for mat, tri in base_section_corners(D[di], dsec):
                ids = []
                for v in tri:
                    bd = v[9]
                    bb = map_bone(bd)
                    if P[j]["type"] == 0:
                        bb2 = own
                    elif bb in allowed:
                        bb2 = bb
                    else:
                        bb2 = min(allowed, key=lambda q: sum((v[r] - bind_b(q)[0][r]) ** 2 for r in range(3)))
                        stats["snapped"] += 1
                    m = xf(bd, bb if bb is not None else bb2)
                    p, n = (v[:3], v[3:6]) if m is None else (xform(m, v[:3]), normalize3(xform(m, v[3:6], 0.0)))
                    w = (f32(p[0]), f32(p[1]), f32(p[2]), f32(n[0]), f32(n[1]), f32(n[2]), v[6], v[7], v[8], bb2)
                    if w not in vid:
                        vid[w] = len(vdata)
                        vdata.append(w)
                    ids.append(vid[w])
                tris.append((mt.from_model(donor, mat), tuple(ids)))
            template = {"has_col": dsec["has_col"],
                        "records": [{"material": mt.from_model(donor, r["material"]), "kind": r["kind"]}
                                    for r in dsec["records"]]}
            lines = []
            sec = build_section(tris, vdata, template, P[j], lines)
            P[j]["sections"][s] = sec
            if sec:
                report.append("piece %d section %d (%s) from donor piece %d: %d triangles"
                              % (j, s, names_d[di], di, sum(len(r["faces"]) // 3 for r in sec["records"] if r["faces"])))
    cleared = sorted(i for i in clear if i not in target.values() and any(base["pieces"][i]["sections"]))
    if cleared:
        report.append("base pieces emptied (the donor has none there): %s" % ", ".join(map(str, cleared)))
    new = finish_model(base, P, model, mt)
    report += mt.notes
    return new, report, stats


# --------------------------------------------------------------------------
# Commands


def cmd_gltf(args):
    _, x = X.load(args.input)
    name = os.path.splitext(os.path.basename(args.input))[0]
    bps = load_bindposes(args.bindpose)
    out = export_glb(x, name, args.textures, bps, warn=lambda m: print("warning: " + m))
    with open(args.output, "wb") as f:
        f.write(out)
    print("%s -> %s: %d bytes" % (args.input, args.output, len(out)))


def materials_for(args, base_path, base, output):
    tex_dir = args.texture_dir or texture_dir_for(output)
    counterpart = None
    if is_embedded_model(base) and args.textures:
        for p in (os.path.join(args.textures, "ob", "chrs", os.path.basename(base_path)),
                  os.path.join(args.textures, os.path.basename(base_path))):
            if os.path.exists(p) and os.path.abspath(p) != os.path.abspath(base_path):
                _, cp = X.load(p)
                if not is_embedded_model(cp):
                    counterpart = cp
                    break
    return Materials(base, textures=args.textures, texture_dir=tex_dir, counterpart=counterpart,
                     retexture=getattr(args, "retexture", False)), tex_dir


def write_model(new, output, tex_dir):
    """Builds, checks (parse, rebuild, chrinc size) and writes the model and
    its new textures. Returns (bytes, texture paths)."""
    out = X.build(new)
    if X.build(X.parse(out)) != out:
        raise GltfError("the written file does not rebuild identically")
    check_size(out, new)
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "wb") as f:
        f.write(out)
    return out, write_textures(new.get("new_textures", {}), tex_dir)


def cmd_fromgltf(args):
    data, base = X.load(args.base)
    mt, tex_dir = materials_for(args, args.base, base, args.output)
    new, report, stats = import_glb(base, args.gltf, regenerate=args.regenerate,
                                    bindposes=load_bindposes(args.bindpose), materials=mt)
    out, written = write_model(new, args.output, tex_dir)
    for line in report:
        print(line)
    for p in written:
        print("wrote " + p)
    print("%s: %d bytes, %d materials; %d sections kept from the base, %d rebuilt, %d removed; %d vertices read, "
          "%d snapped to a bone other than their strongest, %d unweighted%s"
          % (args.output, len(out), len(new["materials"]), stats["sections_kept"], stats["sections_rebuilt"],
             stats["sections_removed"], stats["vertices_in"], stats["snapped"], stats["unweighted"],
             ", identical to the base" if out == data else ""))


def cmd_graft(args):
    _, base = X.load(args.base)
    _, donor = X.load(args.donor)
    glb = args.output.lower().endswith(".glb")
    xbr_out = os.path.splitext(args.output)[0] + ".xbr" if glb else args.output
    mt, tex_dir = materials_for(args, args.base, base, xbr_out)
    bps = load_bindposes(args.bindpose)
    new, report, stats = graft(base, donor, anim_bones_named(donor, args.pieces), bps, mt)
    out, written = write_model(new, xbr_out, tex_dir)
    for line in report:
        print(line)
    for p in written:
        print("wrote " + p)
    print("%s: %d bytes, %d pieces, %d palette bones, %d materials; %d donor vertices moved to another bone"
          % (xbr_out, len(out), len(new["pieces"]), new["model"]["bone_count"], len(new["materials"]),
             stats["snapped"]))
    if glb:
        g = export_glb(X.parse(out), os.path.splitext(os.path.basename(args.output))[0], args.textures, bps,
                       warn=lambda m: print("warning: " + m), extra_textures=new["new_textures"])
        with open(args.output, "wb") as f:
            f.write(g)
        print("%s: %d bytes (import edits of it with fromgltf over %s)" % (args.output, len(g), xbr_out))


def texture_args(p):
    p.add_argument("--textures", help="folder with textures/NNNN.xbt (an unpacked chr.pak): textures to embed in a "
                   "chrinc model, pictures to compare, and the chr.pak counterpart of a chrinc model")
    p.add_argument("--texture-dir", help="where new NNNN.xbt files go (default: <mod>/files/textures when the "
                   "output is under a files/ folder, else textures/ beside the output)")
    p.add_argument("--bindpose", action="append",
                   help="bind poses (as for gltf): place pieces from another model's skeleton at this model's joints")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("gltf", help="export an .xbr to .glb")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--textures", help="folder with textures/NNNN.xbt (an unpacked pak) or the textures folder itself")
    p.add_argument("--bindpose", action="append",
                   help="ANR1 bind pose (human_19_bindpose.raw) or a folder of them; the one whose bone count matches is used")
    p.set_defaults(fn=cmd_gltf)
    p = sub.add_parser("fromgltf", help="geometry from a .glb/.gltf, everything else from the base .xbr")
    p.add_argument("base")
    p.add_argument("gltf")
    p.add_argument("output")
    p.add_argument("--regenerate", action="store_true",
                   help="rebuild every section, even those whose triangles are the base's")
    p.add_argument("--retexture", action="store_true",
                   help="a material named after a texture id whose image differs from that texture gets a new texture")
    texture_args(p)
    p.set_defaults(fn=cmd_fromgltf)
    p = sub.add_parser("graft", help="the pieces of some bones (and their joints) from a donor model onto a base")
    p.add_argument("base")
    p.add_argument("donor")
    p.add_argument("output", help=".xbr, or .glb (then the .xbr is written beside it)")
    p.add_argument("--pieces", required=True, help="animation bones, comma-separated: head, b04_head or 4")
    texture_args(p)
    p.set_defaults(fn=cmd_graft)
    args = ap.parse_args()
    try:
        return args.fn(args) or 0
    except (GltfError, X.XbrError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
