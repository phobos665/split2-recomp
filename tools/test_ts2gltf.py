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
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
