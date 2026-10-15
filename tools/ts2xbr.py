"""Read, check and rewrite TimeSplitters 2 (Xbox) character models (.xbr).

The layout is documented in docs/formats/xbr.md. In short: a 12-byte header
(material list offset, model descriptor offset, 0), the material list, then
the data of each piece in piece order, then the piece table (0x9C bytes per
piece) and the model descriptor (0x34 bytes). Front-end copies (chrinc.pak)
append the textures they use, 128-byte aligned.

A parsed file holds no offsets: every pointer, padding byte, padding vertex,
count and draw header is derived again when it is written. `rewrite` writes
the parsed structure back and compares it with the original, which is the
check that the layout rules below are the whole story.

  python3 -I tools/ts2xbr.py info    ob/chrs/chr01.xbr
  python3 -I tools/ts2xbr.py check   DIR_OR_FILES...   # parse + byte coverage + rewrite
  python3 -I tools/ts2xbr.py rewrite IN.xbr OUT.xbr
  python3 -I tools/ts2xbr.py obj     IN.xbr OUT.obj [--textures DIR] [--section N]
  python3 -I tools/ts2xbr.py skeleton DIR_OR_FILES...  # group files by bone hierarchy
  python3 -I tools/ts2xbr.py joints  chr01.xbr human_19_bindpose.raw  # bind pose joints

Python 3, standard library only.
"""

import argparse
import os
import struct
import sys
import zlib

PIECE_SIZE = 0x9C
MODEL_SIZE = 0x34
SECTIONS = 3

TYPE_NAMES = {0: "rigid", 1: "joint2", 2: "joint3", 3: "bridge"}

# Draw header written for every vertex record (16 bytes). Only the count in
# the low 15 bits of the first word varies.
DRAW_HDR_1, DRAW_HDR_2, DRAW_HDR_3 = 0x302E4000, 0x00000412, 0
EMBEDDED_FLAG = 0x10000000          # material +0xC: texture is inside this file
NO_TEXTURE = 0x40000000             # material id the loader skips
PAD_W = 0x3F808000                  # position W of a padding vertex


class XbrError(Exception):
    pass


def align(n, a):
    return (n + a - 1) // a * a


class Reader:
    """Bounds-checked little-endian reads that remember which bytes were used."""

    def __init__(self, data):
        self.data = data
        self.used = bytearray(len(data))

    def take(self, off, n, what):
        if off < 0 or off + n > len(self.data):
            raise XbrError("%s at %#x+%d is outside the file (%d bytes)" % (what, off, n, len(self.data)))
        for i in range(off, off + n):
            self.used[i] = 1
        return self.data[off:off + n]

    def u32(self, off, what="u32"):
        return struct.unpack("<I", self.take(off, 4, what))[0]

    def unpack(self, fmt, off, what):
        return struct.unpack(fmt, self.take(off, struct.calcsize(fmt), what))


# --------------------------------------------------------------------------
# Parsing


def parse(data):
    """Returns a dict describing the file. Raises XbrError on anything the
    format description does not allow."""
    r = Reader(data)
    mat_off, model_off, zero = r.unpack("<3I", 0, "header")
    if mat_off != 0xC or zero != 0:
        raise XbrError("header is %#x %#x %#x, expected 0xC, offset, 0" % (mat_off, model_off, zero))

    # Materials: 16-byte records until one whose first word is 0xFFFFFFFF.
    materials = []
    o = mat_off
    while True:
        rec = r.unpack("<4I", o, "material")
        o += 16
        if rec[0] == 0xFFFFFFFF:
            if rec[1:] != (0, 0, 0):
                raise XbrError("material terminator has %r" % (rec[1:],))
            break
        materials.append({"texture": rec[0], "word4": rec[1], "word8": rec[2], "flags": rec[3]})

    (count, bone_count, flag8) = r.unpack("<3I", model_off, "model")
    model_rest = r.unpack("<7I", model_off + 0xC, "model runtime words")
    (scale_bits, w2c, w30) = r.unpack("<3I", model_off + 0x28, "model tail")
    if any(model_rest):
        raise XbrError("model descriptor runtime words are not zero: %r" % (model_rest,))
    model = {"bone_count": bone_count, "flag8": flag8, "scale_bits": scale_bits,
             "word2c": w2c, "word30": w30}
    table = model_off - count * PIECE_SIZE
    if table < 0:
        raise XbrError("piece table would start before the file")

    pieces = []
    for i in range(count):
        pieces.append(parse_piece(r, table + i * PIECE_SIZE, i))

    # Embedded textures (front-end copies): from each offset to the next one
    # (or the end of the file), in offset order.
    embedded = []
    emb = sorted({m["texture"] for m in materials if m["flags"] & EMBEDDED_FLAG})
    end_of_model = model_off + MODEL_SIZE
    for k, off in enumerate(emb):
        nxt = emb[k + 1] if k + 1 < len(emb) else len(data)
        if off < end_of_model:
            raise XbrError("embedded texture at %#x is inside the model" % off)
        blob = r.take(off, nxt - off, "embedded texture")
        embedded.append(blob)
    for m in materials:
        if m["flags"] & EMBEDDED_FLAG:
            m["texture"] = emb.index(m["texture"])      # index into embedded

    xbr = {"materials": materials, "pieces": pieces, "model": model, "embedded": embedded}
    xbr["_used"] = r.used
    xbr["_size"] = len(data)
    return xbr


def parse_piece(r, p, index):
    d = r.data
    r.take(p, PIECE_SIZE, "piece")
    ptype, bone, parent, child, sibling, prev, b6, b7 = struct.unpack_from("<B5b2B", d, p)
    counts = struct.unpack_from("<5h", d, p + 8)
    mask = struct.unpack_from("<H", d, p + 0x12)[0]
    rec_ptrs = struct.unpack_from("<3I", d, p + 0x14)
    extra20 = struct.unpack_from("<I", d, p + 0x20)[0]
    streams = [struct.unpack_from("<5I", d, p + 0x24 + 0x14 * s) for s in range(SECTIONS)]
    stat_verts, stat_tris = struct.unpack_from("<2H", d, p + 0x60)
    state = d[p + 0x64:p + 0x68]
    runtime = struct.unpack_from("<5I", d, p + 0x68)
    coll_ptrs = struct.unpack_from("<3I", d, p + 0x80)
    blend_bits = struct.unpack_from("<I", d, p + 0x8C)[0]
    face_ptrs = struct.unpack_from("<3I", d, p + 0x90)
    if any(counts) or extra20 or any(runtime):
        raise XbrError("piece %d: runtime fields are not zero" % index)
    piece = {"type": ptype, "bone": bone, "parent": parent, "child": child,
             "sibling": sibling, "prev": prev, "pad": [b6, b7], "mask": mask,
             "state": list(state), "blend_bits": blend_bits,
             "stat_verts": stat_verts, "stat_tris": stat_tris, "sections": []}
    for s in range(SECTIONS):
        if not rec_ptrs[s]:
            if any(streams[s]) or face_ptrs[s] or coll_ptrs[s]:
                raise XbrError("piece %d section %d has streams but no records" % (index, s))
            piece["sections"].append(None)
            continue
        piece["sections"].append(parse_section(r, index, s, rec_ptrs[s], streams[s],
                                               face_ptrs[s], coll_ptrs[s]))
    return piece


def parse_section(r, index, s, rec_ptr, streams, face_ptr, coll_ptr):
    d = r.data
    where = "piece %d section %d" % (index, s)
    raw = []
    o = rec_ptr
    while True:
        rec = r.unpack("<5h", o, where + " record")
        o += 10
        if rec[4] < 0:
            if rec != (0, 0, 0, 0, -1):
                raise XbrError("%s: record terminator is %r" % (where, rec))
            break
        raw.append(rec)
    hdr_ptr, pos_ptr, uv_ptr, col_ptr, nrm_ptr = streams
    if not raw:
        raise XbrError("%s: no records" % where)
    nv = raw[-1][2] + raw[-1][3]
    if not pos_ptr or not uv_ptr or not hdr_ptr:
        raise XbrError("%s: missing a stream" % where)

    def stream(ptr, size):
        return r.take(ptr, size * nv, where + " stream")

    pos = stream(pos_ptr, 16)
    uv = stream(uv_ptr, 12)
    col = stream(col_ptr, 4) if col_ptr else None
    nrm = stream(nrm_ptr, 16) if nrm_ptr else None
    records = []
    expect = 0
    for j, (mat, ridx, start, cnt, kind) in enumerate(raw):
        if start != expect:
            raise XbrError("%s record %d starts at %d, expected %d" % (where, j, start, expect))
        hdr = r.unpack("<4I", hdr_ptr + 16 * j, where + " draw header")
        if hdr != (0x8000 | cnt, DRAW_HDR_1, DRAW_HDR_2, DRAW_HDR_3):
            raise XbrError("%s record %d: draw header %r" % (where, j, hdr))
        rec = {"material": mat, "kind": kind, "count": cnt,
               "pos": pos[16 * start:16 * (start + cnt)],
               "uv": uv[12 * start:12 * (start + cnt)],
               "col": col[4 * start:4 * (start + cnt)] if col else None,
               "nrm": nrm[16 * start:16 * (start + cnt)] if nrm else None}
        if ridx != j:
            rec["index"] = ridx
        # Padding vertices up to the next multiple of 4 must be copies of the
        # last vertex with the restart flag set (checked again by rewrite).
        end = start + cnt
        nxt = align(end, 4) if j + 1 < len(raw) else end
        records.append(rec)
        expect = nxt
        # face list
        q, c = r.unpack("<2I", face_ptr + 8 * j, where + " face table")
        rec["faces"] = list(struct.unpack_from("<%dH" % c, r.take(q, 2 * c, where + " faces"))) if q else None
        if not q and c:
            raise XbrError("%s record %d: %d indices but no pointer" % (where, j, c))
    sec = {"records": records, "has_col": col is not None, "has_nrm": nrm is not None}
    if coll_ptr:
        sec["collision"] = parse_collision(r, where, coll_ptr, len(records))
    return sec


def parse_collision(r, where, ptr, nrec):
    """Hat collision: one group per record, each a bounding box and a list of
    convex polygons with a plane, their corner indices (into the record's
    vertices) and 5-byte adjacency records."""
    groups = []
    for j in range(nrec):
        g = ptr + 0x20 * j
        bbox = r.take(g, 24, where + " collision group")
        cnt, pp = r.unpack("<2I", g + 0x18, where + " collision group")
        polys = []
        for k in range(cnt):
            it = pp + 0x20 * k
            n = r.data[it]
            axes = r.take(it, 4, where + " polygon")[1:]
            plane = r.take(it + 4, 16, where + " polygon plane")
            p1, c1, p2 = r.unpack("<3I", it + 0x14, where + " polygon")
            polys.append({"corners": list(r.take(p1, n, where + " polygon corners")),
                          "axes": list(axes), "plane": plane,
                          "adjacency": r.take(p2, 5 * c1, where + " polygon adjacency")})
        if not cnt and pp:
            raise XbrError("%s: empty collision group with a pointer" % where)
        groups.append({"bbox": bbox, "polys": polys})
    return groups


# --------------------------------------------------------------------------
# Writing


class Writer:
    def __init__(self):
        self.out = bytearray()

    def pos(self):
        return len(self.out)

    def pad(self, a):
        self.out += b"\0" * (-len(self.out) % a)

    def put(self, b):
        off = len(self.out)
        self.out += b
        return off


def padded_vertices(rec, last_record):
    """The record's vertex streams with padding vertices appended."""
    cnt = rec["count"]
    extra = 0 if last_record else (-cnt % 4)
    pos, uv, col, nrm = rec["pos"], rec["uv"], rec["col"], rec["nrm"]
    if extra:
        if not cnt:
            raise XbrError("empty record needs padding")
        lp = pos[-16:]
        w = struct.unpack_from("<I", lp, 12)[0]
        pad_pos = lp[:12] + struct.pack("<I", (w | 0x8000) & ~1)
        pos = pos + pad_pos * extra
        uv = uv + uv[-12:] * extra
        col = col + col[-4:] * extra if col is not None else None
        nrm = nrm + nrm[-16:] * extra if nrm is not None else None
    return pos, uv, col, nrm


def build(xbr):
    w = Writer()
    w.put(b"\0" * 12)
    mats = xbr["materials"]
    mat_at = w.pos()
    w.put(b"\0" * (16 * len(mats)))
    w.put(struct.pack("<4I", 0xFFFFFFFF, 0, 0, 0))

    piece_fields = []   # per piece: dict of pointers to patch into the table
    for piece in xbr["pieces"]:
        ptrs = {"rec": [0] * 3, "streams": [[0] * 5 for _ in range(3)], "face": [0] * 3, "coll": [0] * 3}
        secs = piece["sections"]
        present = [s for s in range(SECTIONS) if secs[s]]
        for s in present:
            ptrs["rec"][s] = w.pos()
            start = 0
            recs = secs[s]["records"]
            for j, rec in enumerate(recs):
                w.put(struct.pack("<5h", rec["material"], rec.get("index", j), start,
                                  rec["count"], rec["kind"]))
                start = start + rec["count"] if j + 1 == len(recs) else align(start + rec["count"], 4)
            w.put(struct.pack("<5h", 0, 0, 0, 0, -1))
            w.pad(4)
        for s in present:
            sec = secs[s]
            recs = sec["records"]
            st = ptrs["streams"][s]
            st[0] = w.pos()
            for rec in recs:
                w.put(struct.pack("<4I", 0x8000 | rec["count"], DRAW_HDR_1, DRAW_HDR_2, DRAW_HDR_3))
            parts = [padded_vertices(rec, j + 1 == len(recs)) for j, rec in enumerate(recs)]
            if sec["has_col"]:
                st[3] = w.put(b"".join(p[2] for p in parts))
            st[1] = w.put(b"".join(p[0] for p in parts))
            st[2] = w.put(b"".join(p[1] for p in parts))
            if sec["has_nrm"]:
                st[4] = w.put(b"".join(p[3] for p in parts))
        for s in present:
            if "collision" in secs[s]:
                ptrs["coll"][s] = write_collision(w, secs[s]["collision"])
        face_tabs = {}
        for s in present:
            ptrs["face"][s] = w.pos()
            face_tabs[s] = w.pos()
            w.put(b"\0" * (8 * len(secs[s]["records"])))
        if present:
            w.pad(32)
        for s in present:
            for j, rec in enumerate(secs[s]["records"]):
                if rec["faces"] is not None:
                    q = w.put(struct.pack("<%dH" % len(rec["faces"]), *rec["faces"]))
                    struct.pack_into("<2I", w.out, face_tabs[s] + 8 * j, q, len(rec["faces"]))
        w.pad(4)
        piece_fields.append(ptrs)

    table = w.pos()
    for piece, ptrs in zip(xbr["pieces"], piece_fields):
        e = bytearray(PIECE_SIZE)
        struct.pack_into("<B5b2B", e, 0, piece["type"], piece["bone"], piece["parent"], piece["child"],
                         piece["sibling"], piece["prev"], *piece["pad"])
        struct.pack_into("<H", e, 0x12, piece["mask"])
        struct.pack_into("<3I", e, 0x14, *ptrs["rec"])
        for s in range(SECTIONS):
            struct.pack_into("<5I", e, 0x24 + 0x14 * s, *ptrs["streams"][s])
        verts = sum(rec["count"] for sec in piece["sections"] if sec for rec in sec["records"])
        tris = sum(len(rec["faces"]) // 3 for sec in piece["sections"] if sec
                   for rec in sec["records"] if rec["faces"])
        struct.pack_into("<2H", e, 0x60, verts, tris)
        e[0x64:0x68] = bytes(piece["state"])
        struct.pack_into("<3I", e, 0x80, *ptrs["coll"])
        struct.pack_into("<I", e, 0x8C, piece["blend_bits"])
        struct.pack_into("<3I", e, 0x90, *ptrs["face"])
        w.put(bytes(e))
    model_at = w.pos()
    m = xbr["model"]
    w.put(struct.pack("<3I", len(xbr["pieces"]), m["bone_count"], m["flag8"]) + b"\0" * 28 +
          struct.pack("<3I", m["scale_bits"], m["word2c"], m["word30"]))

    emb_at = []
    for blob in xbr["embedded"]:
        w.pad(128)
        emb_at.append(w.put(blob))

    for k, mt in enumerate(mats):
        tex = emb_at[mt["texture"]] if mt["flags"] & EMBEDDED_FLAG else mt["texture"]
        struct.pack_into("<4I", w.out, mat_at + 16 * k, tex, mt["word4"], mt["word8"], mt["flags"])
    struct.pack_into("<3I", w.out, 0, mat_at, model_at, 0)
    return bytes(w.out)


def write_collision(w, groups):
    """Corner bytes of every polygon, then per group its adjacency records and
    its polygons, then the group records; returns the group array offset."""
    corner_at = []
    for g in groups:
        corner_at.append([w.put(bytes(p["corners"])) for p in g["polys"]])
    w.pad(4)
    poly_at = []
    for gi, g in enumerate(groups):
        adj = [w.put(p["adjacency"]) if p["adjacency"] else 0 for p in g["polys"]]
        w.pad(4)
        at = w.pos() if g["polys"] else 0
        for k, p in enumerate(g["polys"]):
            w.put(bytes([len(p["corners"])] + p["axes"]) + p["plane"] +
                  struct.pack("<3I", corner_at[gi][k], len(p["adjacency"]) // 5, adj[k]))
        poly_at.append(at)
    base = w.pos()
    for gi, g in enumerate(groups):
        w.put(g["bbox"] + struct.pack("<2I", len(g["polys"]), poly_at[gi]))
    return base


# --------------------------------------------------------------------------
# Decoding helpers


def vertices(rec):
    """Yields (x, y, z, flags, u, v, w, normal4 or None, colour or None) per vertex.
    flags: bit 15 strip restart, bit 0 winding flip. normal4[3] is the bone
    index (int) on skinned pieces, 1.0 on rigid ones."""
    for k in range(rec["count"]):
        x, y, z, fl = struct.unpack_from("<3fI", rec["pos"], 16 * k)
        u, v, ww = struct.unpack_from("<3f", rec["uv"], 12 * k)
        n = None
        if rec["nrm"] is not None:
            nx, ny, nz = struct.unpack_from("<3f", rec["nrm"], 16 * k)
            nwb = struct.unpack_from("<I", rec["nrm"], 16 * k + 12)[0]
            n = (nx, ny, nz, nwb if nwb < 0x10000 else struct.unpack_from("<f", rec["nrm"], 16 * k + 12)[0])
        c = struct.unpack_from("<I", rec["col"], 4 * k)[0] if rec["col"] is not None else None
        yield (x, y, z, fl & 0xFFFF, u, v, ww, n, c)


def strip_triangles(rec):
    """Triangles from the strip form (record-local indices), skipping
    degenerate ones. Winding: forward when (position in strip + flag bit 0) is even."""
    flags = [struct.unpack_from("<I", rec["pos"], 16 * k + 12)[0] for k in range(rec["count"])]
    start = 0
    out = []
    for b in range(rec["count"]):
        if flags[b] & 0x8000 and (b == 0 or not flags[b - 1] & 0x8000):
            start = b
        if b < 2 or flags[b] & 0x8000:
            continue
        if ((b - start) + (flags[b] & 1)) % 2 == 0:
            out.append((b - 2, b - 1, b))
        else:
            out.append((b - 1, b - 2, b))
    return out


def section_starts(sec):
    starts, s = [], 0
    for j, rec in enumerate(sec["records"]):
        starts.append(s)
        s = align(s + rec["count"], 4)
    return starts


def rigid_skeleton(xbr):
    """Animation bones in the order the game binds them: depth-first over the
    piece tree (child before sibling, children of type 3 not followed), one
    bone per rigid (type 0) piece. Returns [(piece, parent_anim_bone)]."""
    P = xbr["pieces"]
    out = []

    def walk(i, parent):
        while i >= 0:
            p = P[i]
            here = parent
            if p["type"] == 0:
                out.append((i, parent))
                here = len(out) - 1
            if p["child"] >= 0 and p["type"] != 3:
                walk(p["child"], here)
            i = p["sibling"]
    if P:
        walk(0, -1)
    return out


# --------------------------------------------------------------------------
# Commands


def load(path):
    with open(path, "rb") as f:
        data = f.read()
    return data, parse(data)


def cmd_info(args):
    data, x = load(args.file)
    m = x["model"]
    scale = struct.unpack("<f", struct.pack("<I", m["scale_bits"]))[0]
    print("%s: %d bytes, %d materials, %d pieces, %d palette bones, scale %.4g, %d embedded textures"
          % (args.file, len(data), len(x["materials"]), len(x["pieces"]), m["bone_count"], scale,
             len(x["embedded"])))
    for k, mt in enumerate(x["materials"]):
        src = ("embedded #%d" % mt["texture"]) if mt["flags"] & EMBEDDED_FLAG else ("textures/%04d.xbt" % mt["texture"])
        print("  material %d: %s flags %#x" % (k, src, mt["flags"]))
    sk = rigid_skeleton(x)
    anim_of = {p: a for a, (p, _) in enumerate(sk)}
    print("  %d animation bones (rigid pieces, depth-first): parents %s" % (len(sk), [pa for _, pa in sk]))
    for i, p in enumerate(x["pieces"]):
        blend = struct.unpack("<f", struct.pack("<I", p["blend_bits"]))[0]
        desc = []
        for s, sec in enumerate(p["sections"]):
            if not sec:
                continue
            nv = sum(r["count"] for r in sec["records"])
            nt = sum(len(r["faces"]) // 3 for r in sec["records"] if r["faces"])
            extra = []
            if sec["has_col"]:
                extra.append("colours")
            if "collision" in sec:
                extra.append("collision %d polys" % sum(len(g["polys"]) for g in sec["collision"]))
            desc.append("s%d: %d rec %d verts %d tris%s" % (s, len(sec["records"]), nv, nt,
                                                          (" " + ", ".join(extra)) if extra else ""))
        bones = ""
        if p["type"] in (1, 2, 3):
            bones = " palette c64=bone of piece %d, c68=bone of piece %d%s" % (
                p["parent"], p["child"], ", c72=own" if p["bone"] >= 0 else "")
        print("  piece %2d %-6s bone %3d%s parent %3d child %3d sib %3d%s%s | %s" % (
            i, TYPE_NAMES.get(p["type"], p["type"]), p["bone"],
            (" anim %2d" % anim_of[i]) if i in anim_of else "        ",
            p["parent"], p["child"], p["sibling"],
            (" blend %.2f" % blend) if p["type"] == 2 else "", bones, "; ".join(desc) or "no geometry"))


def iter_files(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in sorted(files):
                    if f.lower().endswith(".xbr"):
                        yield os.path.join(root, f)
        else:
            yield p


def cmd_check(args):
    total = parsed = covered = identical = 0
    for path in iter_files(args.paths):
        total += 1
        with open(path, "rb") as f:
            data = f.read()
        try:
            x = parse(data)
        except XbrError as e:
            print("PARSE FAIL %s: %s" % (path, e))
            continue
        parsed += 1
        out = build(x)
        unused = [i for i, u in enumerate(x["_used"]) if not u]
        unexplained = [i for i in unused if i >= len(out) or out[i] != data[i] or data[i] != 0]
        if not unexplained:
            covered += 1
        if out == data:
            identical += 1
        elif args.verbose or total - identical <= 5:
            diff = next((i for i in range(min(len(out), len(data))) if out[i] != data[i]), min(len(out), len(data)))
            print("REWRITE DIFF %s: first difference at %#x (sizes %d / %d)" % (path, diff, len(out), len(data)))
        if unexplained and args.verbose:
            print("UNEXPLAINED %s: %d bytes, first at %#x" % (path, len(unexplained), unexplained[0]))
    print("%d files: %d parse, %d with every byte read or reproduced padding, %d rewrite byte-identical"
          % (total, parsed, covered, identical))
    return 0 if identical == total else 1


def cmd_rewrite(args):
    data, x = load(args.input)
    out = build(x)
    with open(args.output, "wb") as f:
        f.write(out)
    print("%s -> %s: %d bytes, %s" % (args.input, args.output, len(out),
                                     "identical" if out == data else "DIFFERENT"))


def cmd_skeleton(args):
    groups = {}
    for path in iter_files(args.paths):
        _, x = load(path)
        sk = tuple(pa for _, pa in rigid_skeleton(x))
        groups.setdefault(sk, []).append(os.path.basename(path))
    for sk, names in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print("%2d bones, %3d files, parents %s" % (len(sk), len(names), list(sk)))
        print("    " + " ".join(sorted(names)))


# -- Bind pose (ANR1 .raw from fe_anim.pak, e.g. anim/data/ts2/human_19_bindpose.raw)


def read_bindpose(data):
    """Local bind transforms [(translation, quaternion xyzw)] from a bind pose
    ANR1 file: bone count at +0x3C, then from +0x2C4 one 20-byte record per
    bone: 3 floats and 4 offset-binary u16 ((v - 0x8000) / 0x7FFF)."""
    if data[:4] != b"ANR1":
        raise XbrError("not an ANR1 file")
    n = struct.unpack_from("<I", data, 0x3C)[0]
    if 0x2C4 + 20 * n != len(data):
        raise XbrError("bind pose: %d bones do not fill the file" % n)
    out = []
    for k in range(n):
        t = struct.unpack_from("<3f", data, 0x2C4 + 20 * k)
        q = tuple((v - 0x8000) / 0x7FFF for v in struct.unpack_from("<4H", data, 0x2C4 + 20 * k + 12))
        out.append((t, q))
    return out


def _qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def _qrot(q, v):
    r = _qmul(_qmul(q, (v[0], v[1], v[2], 0.0)), (-q[0], -q[1], -q[2], q[3]))
    return r[:3]


def bind_joints(xbr, bindpose):
    """World (model-space) bind transforms of the animation bones: local
    transforms from the bind pose, translations times the model's scale,
    parents from the piece tree."""
    sk = rigid_skeleton(xbr)
    if len(sk) != len(bindpose):
        raise XbrError("model has %d animation bones, bind pose %d" % (len(sk), len(bindpose)))
    scale = struct.unpack("<f", struct.pack("<I", xbr["model"]["scale_bits"]))[0] or 1.0
    world = []
    for k, ((piece, parent), (t, q)) in enumerate(zip(sk, bindpose)):
        t = tuple(c * scale for c in t)
        if parent < 0:
            world.append((t, q))
        else:
            pt, pq = world[parent]
            world.append((tuple(a + b for a, b in zip(pt, _qrot(pq, t))), _qmul(pq, q)))
    return [(piece, parent, wt, wq) for (piece, parent), (wt, wq) in zip(sk, world)]


def cmd_joints(args):
    _, x = load(args.file)
    with open(args.bindpose, "rb") as f:
        bp = read_bindpose(f.read())
    for k, (piece, parent, t, q) in enumerate(bind_joints(x, bp)):
        print("anim bone %2d piece %2d palette %2d parent %2d  at (%.4f, %.4f, %.4f)  rot (%.4f, %.4f, %.4f, %.4f)"
              % (k, piece, x["pieces"][piece]["bone"], parent, t[0], t[1], t[2], *q))


# -- OBJ export (with optional PNG textures, top mip, DXT1/DXT3)


def _rgb565(c):
    return ((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31


def decode_xbt(blob):
    """Top mip of a DXT1 or DXT3 .xbt as (w, h, rgba bytes), or None for the
    other formats (docs/formats/xbt.md: width +0, height +4, format +0x14,
    0 DXT1, 1 DXT3, data from +0x80)."""
    w, h = struct.unpack_from("<2I", blob, 0)
    fmt = struct.unpack_from("<I", blob, 0x14)[0]
    bpb = {0: 8, 1: 16}.get(fmt)
    if bpb is None or not (0 < w <= 4096 and 0 < h <= 4096) or len(blob) < 128 + max(1, w // 4) * max(1, h // 4) * bpb:
        return None
    px = bytearray(w * h * 4)
    o = 128
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            alpha = None
            if bpb == 16:
                alpha = struct.unpack_from("<Q", blob, o)[0]
                o += 8
            c0, c1, bits = struct.unpack_from("<2HI", blob, o)
            o += 8
            p0, p1 = _rgb565(c0), _rgb565(c1)
            if c0 > c1 or bpb == 16:
                pal = [p0, p1, tuple((2 * a + b) // 3 for a, b in zip(p0, p1)),
                       tuple((a + 2 * b) // 3 for a, b in zip(p0, p1))]
                pa = [255] * 4
            else:
                pal = [p0, p1, tuple((a + b) // 2 for a, b in zip(p0, p1)), (0, 0, 0)]
                pa = [255, 255, 255, 0]
            for k in range(16):
                x, y = bx + (k & 3), by + (k >> 2)
                if x >= w or y >= h:
                    continue
                ci = (bits >> (2 * k)) & 3
                a = ((alpha >> (4 * k)) & 15) * 17 if alpha is not None else pa[ci]
                i = 4 * (y * w + x)
                px[i:i + 4] = bytes(pal[ci]) + bytes([a])
    return w, h, bytes(px)


def write_png(path, w, h, rgba):
    raw = b"".join(b"\0" + rgba[4 * w * y:4 * w * (y + 1)] for y in range(h))

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", w, h, 8, 6, 0, 0, 0)) +
                chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def cmd_obj(args):
    _, x = load(args.input)
    base = os.path.splitext(args.output)[0]
    mtl_name = os.path.basename(base) + ".mtl"
    out_dir = os.path.dirname(os.path.abspath(args.output))
    lines = ["# %s, model space (bind pose); one group per piece" % os.path.basename(args.input),
             "mtllib " + mtl_name]
    mtl = []
    for k, mt in enumerate(x["materials"]):
        blob = None
        if mt["flags"] & EMBEDDED_FLAG:
            blob = x["embedded"][mt["texture"]]
        elif args.textures:
            p = os.path.join(args.textures, "%04d.xbt" % mt["texture"])
            if os.path.exists(p):
                with open(p, "rb") as f:
                    blob = f.read()
        mtl.append("newmtl m%d" % k)
        mtl.append("Kd 1 1 1")
        if blob:
            img = decode_xbt(blob)
            if img:
                png = "%s_m%d.png" % (os.path.basename(base), k)
                write_png(os.path.join(out_dir, png), *img)
                mtl.append("map_Kd " + png)
    nverts = 0
    for i, p in enumerate(x["pieces"]):
        for s, sec in enumerate(p["sections"]):
            if not sec or (args.section is not None and s != args.section):
                continue
            lines.append("g piece%02d_s%d_bone%d" % (i, s, p["bone"]))
            starts = section_starts(sec)
            base_v = nverts
            # Vertices of the whole section, padding included, so face list
            # indices (section-relative) can be used directly.
            for j, rec in enumerate(sec["records"]):
                pos, uv, _, nrm = padded_vertices(rec, j + 1 == len(sec["records"]))
                for k in range(len(pos) // 16):
                    xx, yy, zz = struct.unpack_from("<3f", pos, 16 * k)
                    u, v, ww = struct.unpack_from("<3f", uv, 12 * k)
                    lines.append("v %.6f %.6f %.6f" % (xx, yy, zz))
                    lines.append("vt %.6f %.6f" % (u * ww, 1.0 - v * ww))
                    if nrm is not None:
                        lines.append("vn %.6f %.6f %.6f" % struct.unpack_from("<3f", nrm, 16 * k))
                    else:
                        lines.append("vn 0 1 0")
                    nverts += 1
                # pad to the next record's start
            for j, rec in enumerate(sec["records"]):
                lines.append("usemtl m%d" % rec["material"] if rec["material"] >= 0 else "usemtl none")
                if rec["faces"] is not None and not args.strips:
                    tris = [tuple(rec["faces"][q:q + 3]) for q in range(0, len(rec["faces"]), 3)]
                elif args.strips:
                    tris = [tuple(starts[j] + t for t in tri) for tri in strip_triangles(rec)]
                else:
                    continue
                for a, b, c in tris:
                    a, b, c = a + base_v + 1, b + base_v + 1, c + base_v + 1
                    lines.append("f %d/%d/%d %d/%d/%d %d/%d/%d" % (a, a, a, b, b, b, c, c, c))
    with open(args.output, "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(out_dir, mtl_name), "w") as f:
        f.write("\n".join(mtl) + "\n")
    print("%s: %d vertices" % (args.output, nverts))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info"); p.add_argument("file"); p.set_defaults(fn=cmd_info)
    p = sub.add_parser("check"); p.add_argument("paths", nargs="+"); p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("rewrite"); p.add_argument("input"); p.add_argument("output"); p.set_defaults(fn=cmd_rewrite)
    p = sub.add_parser("skeleton"); p.add_argument("paths", nargs="+"); p.set_defaults(fn=cmd_skeleton)
    p = sub.add_parser("joints"); p.add_argument("file"); p.add_argument("bindpose", help="ANR1 bind pose, e.g. human_19_bindpose.raw")
    p.set_defaults(fn=cmd_joints)
    p = sub.add_parser("obj"); p.add_argument("input"); p.add_argument("output")
    p.add_argument("--textures", help="folder holding NNNN.xbt (e.g. an unpacked chr.pak's textures/)")
    p.add_argument("--section", type=int, help="only this section (0 opaque, 1 second pass)")
    p.add_argument("--strips", action="store_true", help="triangles from the strip form instead of the face lists")
    p.set_defaults(fn=cmd_obj)
    args = ap.parse_args()
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
