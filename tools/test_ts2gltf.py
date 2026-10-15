"""Tests for tools/ts2gltf.py (not run by any build).

  # (a) every .xbr in a folder: export, import with no edit, compare
  python3 -I tools/test_ts2gltf.py roundtrip <unpacked chr.pak>/ob/chrs --bindpose <unpacked fe_anim.pak>/anim/data/ts2

  # (b) through Blender: import the .glb, export it with Blender's exporter, import that
  python3 -I tools/test_ts2gltf.py blender --blender /Applications/Blender.app/Contents/MacOS/Blender \
      --out <scratch dir> --textures <unpacked chr.pak> --bindpose <...>/anim/data/ts2 \
      <unpacked chr.pak>/ob/chrs/chr01.xbr ...

(a) checks, per file: the default import (sections whose triangles are
unchanged are kept) gives the original file byte for byte; the --regenerate
import (every section rebuilt) parses, rebuilds identically, keeps every
record within the limits, draws the same triangles from its strips as from
its face lists, gives every skinned vertex a bone its piece can use, and has
the original's triangles: the multiset of (piece, section, material,
(position, uv, bone) x3), winding included, compared exactly.

(b) does the same comparison after Blender, with positions and UVs rounded
to 1e-4, and reports what Blender changed between the .glb it was given and
the one it wrote.
"""

import argparse
import os
import struct
import subprocess
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ts2gltf as G  # noqa: E402
import ts2xbr as X  # noqa: E402
import ts2xbt  # noqa: E402


def validate(xbr):
    """Problems with a written model, as strings."""
    out = []
    for i, p in enumerate(xbr["pieces"]):
        own, allowed = G.piece_bone_sets(xbr, i)
        for s, sec in enumerate(p["sections"]):
            if not sec:
                continue
            verts = G.section_vertices(sec)
            starts = X.section_starts(sec)
            strip_tris, list_tris = Counter(), Counter()
            for j, rec in enumerate(sec["records"]):
                if rec["count"] > G.MAX_RECORD_VERTS:
                    out.append("piece %d section %d record %d: %d vertices" % (i, s, j, rec["count"]))
                for a, b, c in X.strip_triangles(rec):
                    strip_tris[(rec["material"],) + tuple(verts[starts[j] + q][:3] for q in (a, b, c))] += 1
                for v in X.vertices(rec):
                    if p["type"] != 0 and int(v[7][3]) not in allowed:
                        out.append("piece %d section %d: vertex on bone %d, allowed %s" % (i, s, v[7][3], allowed))
                        break
            for mat, tri in G.section_triangles(sec):
                list_tris[(mat,) + tuple(verts[q][:3] for q in tri)] += 1

            def canon(c):
                return Counter({(k[0],) + min((k[1:][r:] + k[1:][:r]) for r in range(3)): n for k, n in c.items()})
            if canon(strip_tris) != canon(list_tris):
                out.append("piece %d section %d: strips and face lists differ" % (i, s))
    return out


def diff_count(a, b):
    return sum((a - b).values()), sum((b - a).values())


def cmd_roundtrip(args):
    bps = G.load_bindposes(args.bindpose)
    files = sorted(X.iter_files(args.paths))
    n = ok = identical = 0
    tris = verts_old = verts_new = 0
    fails = []
    for path in files:
        n += 1
        name = os.path.basename(path)
        with open(path, "rb") as f:
            data = f.read()
        base = X.parse(data)
        glb = os.path.join(args.out, name + ".glb")
        with open(glb, "wb") as f:
            f.write(G.export_glb(base, name, None, bps, warn=lambda m: None))
        try:
            kept, _, _ = G.import_glb(base, glb)
            if X.build(kept) == data:
                identical += 1
            else:
                fails.append("%s: default import is not byte-identical" % name)
            new, _, st = G.import_glb(base, glb, regenerate=True)
            out = X.build(new)
            back = X.parse(out)
            problems = []
            if X.build(back) != out:
                problems.append("rebuild differs")
            problems += validate(back)
            a, b = G.model_triangles(base), G.model_triangles(back)
            if a != b:
                problems.append("triangles differ: %d only in the original, %d only in the new" % diff_count(a, b))
            if st["snapped"]:
                problems.append("%d vertices snapped" % st["snapped"])
            tris += sum(a.values())
            verts_old += sum(r["count"] for p in base["pieces"] for sec in p["sections"] if sec for r in sec["records"])
            verts_new += sum(r["count"] for p in back["pieces"] for sec in p["sections"] if sec for r in sec["records"])
            if problems:
                fails.append("%s: %s" % (name, "; ".join(problems[:4])))
            else:
                ok += 1
        except (G.GltfError, X.XbrError) as e:
            fails.append("%s: %s" % (name, e))
        finally:
            if not args.keep:
                os.remove(glb)
    for line in fails:
        print("FAIL " + line)
    print("%d files: %d default imports byte-identical; %d regenerated imports valid with the original's "
          "triangles (%d non-degenerate triangles; %d stored vertices on the disc, %d regenerated)"
          % (n, identical, ok, tris, verts_old, verts_new))
    return 0 if ok == n and identical == n else 1


BLENDER_SCRIPT = r'''
import bpy, sys
src, dst = sys.argv[sys.argv.index("--") + 1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=False,
                          export_skins=True, export_animations=False, export_morph=False,
                          export_yup=True, export_apply=False)
'''


def glb_summary(path):
    """Per mesh node name: vertices, triangles, max |normal - unit|, has colours;
    plus joint names and material names."""
    gl, bufs = G.read_gltf(path)
    out = {}
    for node in gl["nodes"]:
        if "mesh" not in node:
            continue
        nv = nt = 0
        cols = False
        for prim in gl["meshes"][node["mesh"]]["primitives"]:
            nv += gl["accessors"][prim["attributes"]["POSITION"]]["count"]
            nt += gl["accessors"][prim["indices"]]["count"] // 3 if "indices" in prim else 0
            cols = cols or "COLOR_0" in prim["attributes"]
        out[G.strip_suffix(node["name"])] = (nv, nt, cols)
    joints = [gl["nodes"][j]["name"] for sk in gl.get("skins", []) for j in sk["joints"]]
    mats = [m.get("name") for m in gl.get("materials", [])]
    return out, joints, mats


def compare_tolerant(base, new):
    """match_triangles over every piece and section, normals and colours
    not compared: (only in base, only in new, the same ignoring winding,
    largest normal change in degrees)."""
    tot = [0, 0, 0, 0, 0.0]
    for i, p in enumerate(base["pieces"]):
        q = new["pieces"][i]
        for s in range(X.SECTIONS):
            a = G.base_section_corners(p, p["sections"][s]) if p["sections"][s] else []
            b = G.base_section_corners(q, q["sections"][s]) if q["sections"][s] else []
            r = G.match_triangles(a, b, normal_dot=None, col_tol=None)
            for k in range(4):
                tot[k] += r[k]
            tot[4] = max(tot[4], r[4])
    return tot


def cmd_blender(args):
    bps = G.load_bindposes(args.bindpose)
    script = os.path.join(args.out, "blender_roundtrip.py")
    with open(script, "w") as f:
        f.write(BLENDER_SCRIPT)
    status = 0
    for path in args.files:
        name = os.path.splitext(os.path.basename(path))[0]
        with open(path, "rb") as f:
            data = f.read()
        base = X.parse(data)
        glb = os.path.join(args.out, name + ".glb")
        bglb = os.path.join(args.out, name + "_blender.glb")
        with open(glb, "wb") as f:
            f.write(G.export_glb(base, name, args.textures, bps, warn=lambda m: print("  warning: " + m)))
        r = subprocess.run([args.blender, "-b", "--factory-startup", "--python", script, "--", glb, bglb],
                           capture_output=True, text=True)
        if r.returncode or not os.path.exists(bglb):
            print("%s: Blender failed\n%s" % (name, (r.stdout + r.stderr)[-2000:]))
            status = 1
            continue
        s0, j0, m0 = glb_summary(glb)
        s1, j1, m1 = glb_summary(bglb)
        v0, v1 = sum(v[0] for v in s0.values()), sum(v[0] for v in s1.values())
        t0, t1 = sum(v[1] for v in s0.values()), sum(v[1] for v in s1.values())
        missing = sorted(set(s0) - set(s1))
        lost_cols = sorted(k for k in s0 if s0[k][2] and k in s1 and not s1[k][2])
        print("%s: Blender wrote %d meshes (of %d), %d vertices (from %d), %d triangles (from %d), "
              "%d joints (from %d), joint order %s, materials %s%s%s"
              % (name, len(s1), len(s0), v1, v0, t1, t0, len(j1), len(j0),
                 "kept" if j0 == j1 else "changed", "kept" if m0 == m1 else "%s -> %s" % (m0, m1),
                 (", missing " + ", ".join(missing)) if missing else "",
                 (", lost colours on " + ", ".join(lost_cols)) if lost_cols else ""))
        for mode, regen in (("keep", False), ("regen", True)):
            new, report, st = G.import_glb(base, bglb, regenerate=regen)
            out = X.build(new)
            back = X.parse(out)
            problems = validate(back)
            only_a, only_b, wa, wb, angle = compare_tolerant(base, back)
            ntri = sum(G.model_triangles(base).values())
            dst = os.path.join(args.out, "%s_blender_%s.xbr" % (name, mode))
            with open(dst, "wb") as f:
                f.write(out)
            print("  %-5s -> %s: %d bytes%s; sections kept %d, rebuilt %d, removed %d; snapped %d, unweighted %d; "
                  "triangles %d, only in original %d, only in new %d (ignoring winding %d/%d); "
                  "largest normal change %.2f deg%s"
                  % (mode, dst, len(out), " (identical to the original)" if out == data else "",
                     st["sections_kept"], st["sections_rebuilt"], st["sections_removed"], st["snapped"],
                     st["unweighted"], ntri, only_a, only_b, wa, wb, angle,
                     ("; PROBLEMS: " + "; ".join(problems[:3])) if problems else ""))
            if only_a or only_b or problems:
                status = 1
    return status


def model_texture(xbr, mat, folders):
    """(w, h, rgba) of a material's texture, or None."""
    if mat < 0:
        return None
    mt = xbr["materials"][mat]
    if mt["flags"] & X.EMBEDDED_FLAG:
        blob = xbr["embedded"][mt["texture"]]
    else:
        blob = next((b for b in (G.find_xbt(f, mt["texture"]) for f in folders) if b), None)
    if blob is None:
        return None
    try:
        t = ts2xbt.Xbt(blob)
        w, h, _ = t.sizes[0]
        return w, h, ts2xbt.decode_level(t, 0)
    except ts2xbt.XbtError:
        return None


def render(xbr, folders, size=384, views=("front", "side", "back")):
    """Orthographic textured views of the model in its bind pose, side by
    side, as PNG bytes: front (looking at +Z towards -Z), right side, back."""
    tris = []
    for p in xbr["pieces"]:
        for sec in p["sections"]:
            if sec:
                verts = G.section_vertices(sec)
                tris += [(m, [verts[i] for i in t]) for m, t in G.section_triangles(sec)]
    pts = [v for _, t in tris for v in t]
    lo = [min(v[i] for v in pts) for i in range(3)]
    hi = [max(v[i] for v in pts) for i in range(3)]
    span = max(hi[i] - lo[i] for i in range(3)) * 1.05
    cx, cy, cz = [(lo[i] + hi[i]) / 2 for i in range(3)]
    tex = {}
    W = size * len(views)
    img = bytearray([40, 40, 48, 255] * (W * size))
    for vi, view in enumerate(views):
        zbuf = [-1e30] * (size * size)

        def project(v):
            x, y, z = v[0] - cx, v[1] - cy, v[2] - cz
            if view == "side":
                x, z = -z, x
            elif view == "back":
                x, z = -x, -z
            return ((x / span + 0.5) * size, (0.5 - y / span) * size, z)
        light = {"front": (0.3, 0.4, 1.0), "side": (-1.0, 0.4, 0.3), "back": (-0.3, 0.4, -1.0)}[view]
        ln = G.normalize3(light)
        for mat, corners in tris:
            if mat not in tex:
                tex[mat] = model_texture(xbr, mat, folders)
            t = tex[mat]
            P = [project(v) for v in corners]
            (x0, y0, _), (x1, y1, _), (x2, y2, _) = P
            area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
            if abs(area) < 1e-9:
                continue
            nrm = G.normalize3(tuple(sum(c[7][i] for c in corners if c[7]) for i in range(3)))
            shade = 0.35 + 0.65 * max(0.0, sum(a * b for a, b in zip(nrm, ln)))
            minx, maxx = max(0, int(min(x0, x1, x2))), min(size - 1, int(max(x0, x1, x2)) + 1)
            miny, maxy = max(0, int(min(y0, y1, y2))), min(size - 1, int(max(y0, y1, y2)) + 1)
            for py in range(miny, maxy + 1):
                for px in range(minx, maxx + 1):
                    qx, qy = px + 0.5, py + 0.5
                    w0 = ((x1 - qx) * (y2 - qy) - (x2 - qx) * (y1 - qy)) / area
                    w1 = ((x2 - qx) * (y0 - qy) - (x0 - qx) * (y2 - qy)) / area
                    w2 = 1.0 - w0 - w1
                    if w0 < 0 or w1 < 0 or w2 < 0:
                        continue
                    z = w0 * P[0][2] + w1 * P[1][2] + w2 * P[2][2]
                    k = py * size + px
                    if z <= zbuf[k]:
                        continue
                    if t:
                        u = w0 * corners[0][4] + w1 * corners[1][4] + w2 * corners[2][4]
                        v = w0 * corners[0][5] + w1 * corners[1][5] + w2 * corners[2][5]
                        tx, ty = int(u * t[0]) % t[0], int(v * t[1]) % t[1]
                        o = 4 * (ty * t[0] + tx)
                        if t[2][o + 3] < 128:
                            continue
                        rgb = t[2][o:o + 3]
                    else:
                        rgb = (200, 200, 200)
                    zbuf[k] = z
                    o = 4 * (py * W + vi * size + px)
                    img[o:o + 3] = bytes(min(255, int(c * shade)) for c in rgb)
    return ts2xbt.write_png(W, size, bytes(img))


def cmd_render(args):
    _, x = X.load(args.xbr)
    with open(args.png, "wb") as f:
        f.write(render(x, args.textures or [], args.size))
    print("%s: front, side, back" % args.png)
    return 0


def cmd_graft(args):
    """Grafts the given bones of every donor onto every base and checks: the
    output parses and rebuilds, validate() passes, every base piece that was
    not grafted keeps its triangles exactly, the grafted pieces have the
    donor's triangle count, and the .glb export of the result imports back
    over it byte for byte."""
    bps = G.load_bindposes(args.bindpose)
    n = ok = 0
    for bp in args.bases:
        for dp in args.donors:
            if bp == dp:
                continue
            n += 1
            label = "%s <- %s" % (os.path.basename(bp), os.path.basename(dp))
            _, base = X.load(bp)
            _, donor = X.load(dp)
            try:
                bones = G.anim_bones_named(donor, args.pieces)
                mt = G.Materials(base, textures=args.textures)
                new, _, st = G.graft(base, donor, bones, bps, mt)
                out = X.build(new)
                back = X.parse(out)
                problems = []
                if X.build(back) != out:
                    problems.append("rebuild differs")
                problems += validate(back)
                sk_b, sk_d = X.rigid_skeleton(base), X.rigid_skeleton(donor)
                sel_b = {sk_b[k][0] for k in bones}
                sel_d = {sk_d[k][0] for k in bones}
                swapped = sel_b | set(G.connectors(base["pieces"], sel_b))
                a = Counter({k: c for k, c in G.model_triangles(base).items() if k[0] not in swapped})
                b = Counter({k: c for k, c in G.model_triangles(back).items()
                             if k[0] < len(base["pieces"]) and k[0] not in swapped})
                # materials are renumbered when some are dropped: compare by texture
                tex_a = Counter({(k[0], k[1], base["materials"][k[2]]["texture"] if k[2] >= 0 else -1) + k[3:]: c
                                 for k, c in a.items()}) if not G.is_embedded_model(base) else a
                tex_b = Counter({(k[0], k[1], back["materials"][k[2]]["texture"] if k[2] >= 0 else -1) + k[3:]: c
                                 for k, c in b.items()}) if not G.is_embedded_model(base) else b
                if not G.is_embedded_model(base) and tex_a != tex_b:
                    problems.append("untouched pieces changed: %d/%d" % diff_count(tex_a, tex_b))
                donor_tris = sum(c for k, c in G.model_triangles(donor).items()
                                 if k[0] in sel_d | set(G.connectors(donor["pieces"], sel_d)))
                new_tris = sum(c for k, c in G.model_triangles(back).items()
                               if k[0] >= len(base["pieces"]) or k[0] in swapped)
                if donor_tris != new_tris:
                    problems.append("grafted triangles %d, donor's %d" % (new_tris, donor_tris))
                glb = os.path.join(args.out, "graft_test.glb")
                with open(glb, "wb") as f:
                    f.write(G.export_glb(back, "t", args.textures, bps, warn=lambda m: None))
                again, _, _ = G.import_glb(back, glb, materials=G.Materials(back, textures=args.textures))
                os.remove(glb)
                if X.build(again) != out:
                    problems.append("its .glb does not import back byte for byte")
                if problems:
                    print("FAIL %s: %s" % (label, "; ".join(problems[:3])))
                else:
                    ok += 1
                    if args.verbose:
                        print("ok %s: %d bytes, %d pieces, %d triangles grafted, %d snapped"
                              % (label, len(out), len(back["pieces"]), new_tris, st["snapped"]))
                if args.render:
                    path = os.path.join(args.out, "%s_%s.png" % (os.path.splitext(os.path.basename(bp))[0],
                                                                os.path.splitext(os.path.basename(dp))[0]))
                    with open(path, "wb") as f:
                        f.write(render(back, args.textures and [args.textures] or []))
            except (G.GltfError, X.XbrError) as e:
                print("FAIL %s: %s" % (label, e))
    print("%d grafts: %d valid" % (n, ok))
    return 0 if ok == n else 1


MERGE_SCRIPT = r'''
import bpy, sys
base, donor, out, keep = sys.argv[sys.argv.index("--") + 1:][:4]
keep = keep.split(",")
bpy.ops.wm.read_factory_settings(use_empty=True)


def imp(p):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=p)
    return [o for o in bpy.data.objects if o not in before]


def piece(o):
    n = o.name.split(".")[0]
    return n.split("_", 1)[1] if "_" in n else n
b, d = imp(base), imp(donor)
for o in b:
    if o.type == "MESH" and piece(o) in keep:
        bpy.data.objects.remove(o)
for o in d:
    if o.type == "MESH" and piece(o) not in keep:
        bpy.data.objects.remove(o)
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_animations=False)
'''


def cmd_merge(args):
    """The Blender way of combining two models: import both exports, keep the
    donor's objects for the grafted pieces and the base's for the rest,
    export, fromgltf over the base. Compared with `graft` of the same pieces."""
    bps = G.load_bindposes(args.bindpose)
    script = os.path.join(args.out, "blender_merge.py")
    with open(script, "w") as f:
        f.write(MERGE_SCRIPT)
    _, base = X.load(args.base)
    _, donor = X.load(args.donor)
    bones = G.anim_bones_named(donor, args.pieces)
    grafted, _, _ = G.graft(base, donor, bones, bps, G.Materials(base, textures=args.textures))
    sk_d = X.rigid_skeleton(donor)
    sel_d = {sk_d[k][0] for k in bones}
    names = G.piece_names(donor, G.skeleton(donor))
    keep = sorted({names[i] for i in sel_d | set(G.connectors(donor["pieces"], sel_d))})
    paths = []
    for x, path in ((base, args.base), (donor, args.donor)):
        p = os.path.join(args.out, os.path.basename(path) + ".glb")
        with open(p, "wb") as f:
            f.write(G.export_glb(x, "m", args.textures, bps, warn=lambda m: None))
        paths.append(p)
    merged = os.path.join(args.out, "merged.glb")
    r = subprocess.run([args.blender, "-b", "--factory-startup", "--python", script, "--", paths[0], paths[1],
                        merged, ",".join(keep)], capture_output=True, text=True)
    if r.returncode or not os.path.exists(merged):
        print("Blender failed\n" + (r.stdout + r.stderr)[-2000:])
        return 1
    new, report, st = G.import_glb(base, merged, bindposes=bps, materials=G.Materials(base, textures=args.textures))
    back = X.parse(X.build(new))
    diff = compare_tolerant(X.parse(X.build(grafted)), back)
    problems = validate(back)
    for p in paths + [merged, script]:
        os.remove(p)
    print("%s <- %s (%s through Blender): sections rebuilt %d, snapped %d; against graft: %d only in graft, "
          "%d only in the merge, largest normal change %.2f deg%s"
          % (os.path.basename(args.base), os.path.basename(args.donor), ",".join(keep), st["sections_rebuilt"],
             st["snapped"], diff[0], diff[1], diff[4], ("; PROBLEMS " + "; ".join(problems[:3])) if problems else ""))
    return 1 if diff[0] or diff[1] or problems else 0


ADDON_SCRIPT = r'''
import bpy, sys
xbr, textures, bindpose, out, mod = sys.argv[sys.argv.index("--") + 1:][:5]
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
pkg = next(k for k in bpy.context.preferences.addons.keys() if k.endswith("ts2_character"))
bpy.context.preferences.addons[pkg].preferences.bindpose_dir = bindpose
assert bpy.ops.import_scene.ts2_xbr(filepath=xbr, textures=textures) == {"FINISHED"}
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
head = next(o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("p07s0_"))
vs = head.data.vertices
c = [sum(v.co[i] for v in vs) / len(vs) for i in range(3)]
for v in vs:
    v.co = [c[i] + (v.co[i] - c[i]) * 1.6 for i in range(3)]
for o in bpy.data.objects:
    o.select_set(False)
bpy.context.view_layer.objects.active = head
assert bpy.ops.export_scene.ts2_xbr(filepath=out) == {"FINISHED"}
bpy.context.scene.ts2_mod_dir = mod
assert bpy.ops.ts2.write_mod() == {"FINISHED"}
print("TS2TEST", repr((arm.get("ts2_source"), c)))
'''


def cmd_addon(args):
    """Builds the add-on zip, installs it into a throwaway Blender profile
    (BLENDER_USER_RESOURCES, so the real one is untouched), and in Blender
    -b: imports the model with the add-on, scales piece 7's mesh (the head
    of a human) by 1.6 about its centre, exports with the add-on and with
    Write into mod folder. Checks that both files are the same, parse,
    rebuild, pass validate(), and have the original's triangles with piece
    7's scaled."""
    import ast
    import shutil
    import tempfile
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender"))
    import build_addon
    work = tempfile.mkdtemp(prefix="ts2addon_", dir=args.out)
    try:
        zp = build_addon.build(os.path.join(work, "ts2_character.zip"))
        env = dict(os.environ, BLENDER_USER_RESOURCES=os.path.join(work, "profile"))
        r = subprocess.run([args.blender, "--factory-startup", "--command", "extension", "install-file",
                            "-r", "user_default", "-e", zp], capture_output=True, text=True, env=env)
        if r.returncode:
            print("install failed\n" + (r.stdout + r.stderr)[-2000:])
            return 1
        script = os.path.join(work, "addon_test.py")
        with open(script, "w") as f:
            f.write(ADDON_SCRIPT)
        out = os.path.join(work, "out.xbr")
        mod = os.path.join(work, "mod")
        r = subprocess.run([args.blender, "-b", "--python", script, "--", os.path.abspath(args.xbr),
                            os.path.abspath(args.textures or ""), os.path.abspath(args.bindpose), out, mod],
                           capture_output=True, text=True, env=env)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith("TS2TEST")), None)
        if line is None:
            print("Blender run failed\n" + (r.stdout + r.stderr)[-3000:])
            return 1
        source, c = ast.literal_eval(line[len("TS2TEST"):].strip())
        cg = (c[0], c[2], -c[1])                     # Blender Z-up -> glTF Y-up
        sub = "chrincs" if "chrincs" in os.path.abspath(args.xbr).replace("\\", "/").split("/") else "chrs"
        modfile = os.path.join(mod, "files", "ob", sub, os.path.basename(args.xbr))
        with open(out, "rb") as f:
            data = f.read()
        problems = []
        if not os.path.exists(modfile) or open(modfile, "rb").read() != data:
            problems.append("Write into mod folder gave another file (or none)")
        _, base = X.load(args.xbr)
        new = X.parse(data)
        if X.build(new) != data:
            problems.append("rebuild differs")
        problems += validate(new)
        only = [0, 0]
        for i, p in enumerate(base["pieces"]):
            for s in range(X.SECTIONS):
                a = G.base_section_corners(p, p["sections"][s]) if p["sections"][s] else []
                if i == 7:
                    a = [(m, tuple(tuple(cg[k] + (v[k] - cg[k]) * 1.6 for k in range(3)) + v[3:] for v in t))
                         for m, t in a]
                q = new["pieces"][i]["sections"][s]
                b = G.base_section_corners(new["pieces"][i], q) if q else []
                r = G.match_triangles(a, b, pos_tol=2e-4, normal_dot=None, col_tol=None)
                only[0] += r[0]
                only[1] += r[1]
        print("add-on: imported %s, exported %d bytes; against the original with piece 7 scaled 1.6x: %d triangles "
              "only in the original, %d only in the export (of %d)%s"
              % (os.path.basename(source), len(data), only[0], only[1], sum(G.model_triangles(base).values()),
                 ("; PROBLEMS: " + "; ".join(problems[:3])) if problems else ""))
        return 1 if problems or only[0] or only[1] else 0
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("roundtrip")
    p.add_argument("paths", nargs="+")
    p.add_argument("--bindpose", action="append")
    p.add_argument("--out", default=".", help="where the temporary .glb files go")
    p.add_argument("--keep", action="store_true", help="keep the .glb files")
    p.set_defaults(fn=cmd_roundtrip)
    p = sub.add_parser("blender")
    p.add_argument("files", nargs="+")
    p.add_argument("--blender", default="blender")
    p.add_argument("--out", required=True)
    p.add_argument("--textures")
    p.add_argument("--bindpose", action="append")
    p.set_defaults(fn=cmd_blender)
    p = sub.add_parser("graft")
    p.add_argument("--bases", nargs="+", required=True)
    p.add_argument("--donors", nargs="+", required=True)
    p.add_argument("--pieces", default="head")
    p.add_argument("--textures", help="unpacked chr.pak (to embed textures in chrinc bases)")
    p.add_argument("--bindpose", action="append")
    p.add_argument("--out", required=True)
    p.add_argument("--render", action="store_true", help="write a PNG of each result")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_graft)
    p = sub.add_parser("merge")
    p.add_argument("base")
    p.add_argument("donor")
    p.add_argument("--pieces", default="head")
    p.add_argument("--blender", default="blender")
    p.add_argument("--textures")
    p.add_argument("--bindpose", action="append")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_merge)
    p = sub.add_parser("addon", help="the Blender add-on, headless: import, scale the head, export")
    p.add_argument("xbr")
    p.add_argument("--blender", default="blender")
    p.add_argument("--textures")
    p.add_argument("--bindpose", required=True, help="folder with human_19_bindpose.raw (or an unpacked fe_anim.pak)")
    p.add_argument("--out", required=True, help="where the temporary profile and files go")
    p.add_argument("--keep", action="store_true")
    p.set_defaults(fn=cmd_addon)
    p = sub.add_parser("render", help="front, side and back views of a model as PNG")
    p.add_argument("xbr")
    p.add_argument("png")
    p.add_argument("--textures", action="append", help="folders holding NNNN.xbt (or textures/NNNN.xbt)")
    p.add_argument("--size", type=int, default=384)
    p.set_defaults(fn=cmd_render)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
