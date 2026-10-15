"""Build a low-poly character on TimeSplitters 2's human skeleton, in Blender.

Every body part is a tapered box along a bone, weighted wholly to that bone
(TS2 has no blend weights, so this is exactly what the format holds), and
textured from one small atlas painted from the spec: each cell is a base
colour, a little noise, and rectangles (a face is a skin cell with hair,
eyes, brows and a mouth as rectangles). The joint pieces of the base model
are dropped, as N64-era characters had none: limbs overlap at the joints.

  Blender -b --factory-startup --python tools/blender/ts2_lowpoly.py -- \\
      <base.glb> <spec.json> <out.glb> [--preview out.png]

base.glb is a TS2 human exported by `tools/ts2gltf.py gltf` (its joints are
b00_pelvis ... b18_l_foot; the character faces -Y, its right is -X). Then:

  python3 -I tools/ts2gltf.py fromgltf <base.xbr> out.glb out.xbr --texture-dir <dir>

The spec (JSON):

  {"atlas": {"size": 128, "cell": 32,
             "cells": {"cloth": {"colour": [0.08, 0.08, 0.1], "noise": 0.03},
                       "face": {"colour": [0.85, 0.65, 0.5],
                                "rects": [[0, 0, 1, 0.3, [0.1, 0.07, 0.05]], ...]}}},
   "parts": [{"bone": "b13_r_thigh", "to": "b14_r_shin",
              "size": [0.15, 0.16, 0.12, 0.13],
              "extend": [0.03, 0.02],
              "faces": {"default": "cloth", "front": "cloth"}}, ...]}

  - A cell is `cell` pixels square in a `size` atlas, filled in order. Its
    rects are [x, y, w, h, colour] in 0..1 of the cell, y measured down from
    the top, painted in order over the base colour.
  - A part runs from its bone's joint to `to`: another joint, or an offset
    [x, y, z] in metres (z up). size is [width, depth] at the start and at
    the end; extend lengthens it past each end. `offset` [x, y, z] moves it.
    faces maps front, back, left, right, top, bottom (the character's own
    sides) to cells, falling back to default.
"""

import argparse
import json
import sys

import bpy
import bmesh
import numpy as np
from mathutils import Vector

SIDES = ("front", "back", "left", "right", "top", "bottom")


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="ts2_lowpoly")
    ap.add_argument("base")
    ap.add_argument("spec")
    ap.add_argument("out")
    ap.add_argument("--preview", help="also render a front/side preview PNG")
    return ap.parse_args(argv)


def paint_atlas(spec):
    size, cell = spec.get("size", 128), spec.get("cell", 32)
    per_row = size // cell
    px = np.zeros((size, size, 4), dtype=np.float32)        # row 0 = top here
    px[..., 3] = 1.0
    rng = np.random.default_rng(7)
    where = {}
    for k, (name, c) in enumerate(spec["cells"].items()):
        cx, cy = (k % per_row) * cell, (k // per_row) * cell
        if cy + cell > size:
            raise SystemExit("too many atlas cells for a %d atlas of %d-pixel cells" % (size, cell))
        block = np.empty((cell, cell, 3), dtype=np.float32)
        block[:] = c["colour"]
        for x, y, w, h, col in c.get("rects", []):
            x0, y0 = int(round(x * cell)), int(round(y * cell))
            x1, y1 = int(round((x + w) * cell)), int(round((y + h) * cell))
            block[y0:y1, x0:x1] = col
        # One noise value per texel, the same in each channel: grain, not speckle.
        block += rng.normal(0.0, c.get("noise", 0.0), (cell, cell, 1)).astype(np.float32)
        px[cy:cy + cell, cx:cx + cell, :3] = np.clip(block, 0.0, 1.0)
        # UV rectangle of the cell, inset half a pixel, v up from the bottom.
        u0, u1 = (cx + 0.5) / size, (cx + cell - 0.5) / size
        v1, v0 = 1 - (cy + 0.5) / size, 1 - (cy + cell - 0.5) / size
        where[name] = (u0, v0, u1, v1)
    img = bpy.data.images.new("ts2_lowpoly_atlas", size, size, alpha=False)
    img.pixels = px[::-1].ravel().tolist()                   # Blender rows go up
    img.pack()
    return img, where


def atlas_material(img):
    mat = bpy.data.materials.new("lowpoly_atlas")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Closest"
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def joint(arm, name):
    for b in arm.data.bones:
        if b.name == name or b.name.split("_", 1)[-1] == name:
            return arm.matrix_world @ b.head_local
    raise SystemExit("no joint %s in the base" % name)


def side_of(normal):
    """The character's own side a face normal points to (it faces -Y, its
    right is -X)."""
    ax = max(range(3), key=lambda i: abs(normal[i]))
    if ax == 0:
        return "left" if normal[0] > 0 else "right"
    if ax == 1:
        return "back" if normal[1] > 0 else "front"
    return "top" if normal[2] > 0 else "bottom"


def box(bm, uv, part, arm, cells):
    start = joint(arm, part["bone"])
    to = part["to"]
    end = joint(arm, to) if isinstance(to, str) else start + Vector(to)
    off = Vector(part.get("offset", (0, 0, 0)))
    start, end = start + off, end + off
    axis = (end - start).normalized()
    e0, e1 = part.get("extend", (0.0, 0.0))
    start, end = start - axis * e0, end + axis * e1
    x = Vector((1, 0, 0))
    x = (x - axis * x.dot(axis)).normalized() if abs(axis.x) < 0.95 else Vector((0, 1, 0))
    y = Vector((0, 1, 0))
    y = (y - axis * y.dot(axis) - x * y.dot(x))
    y = y.normalized() if y.length > 1e-6 else axis.cross(x).normalized()
    w0, d0, w1, d1 = part["size"]
    corners = []
    for p, w, d in ((start, w0, d0), (end, w1, d1)):
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            corners.append(bm.verts.new(p + x * (sx * w / 2) + y * (sy * d / 2)))
    centre = (start + end) / 2
    quads = ((0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0))
    faces = part.get("faces", {})
    for q in quads:
        vs = [corners[i] for i in q]
        f = bm.faces.new(vs)
        f.normal_update()
        fc = sum((v.co for v in vs), Vector()) / 4
        if f.normal.dot(fc - centre) < 0:
            f.normal_flip()
        cell = cells[faces.get(side_of(f.normal), faces.get("default", next(iter(cells))))]
        # Project the face onto the plane it faces, as the viewer sees it,
        # and stretch that over the cell.
        side = side_of(f.normal)
        if side in ("front", "back"):
            pu, pv = (lambda c: c.x if side == "front" else -c.x), (lambda c: c.z)
        elif side in ("left", "right"):
            pu, pv = (lambda c: -c.y if side == "left" else c.y), (lambda c: c.z)
        else:
            pu, pv = (lambda c: c.x), (lambda c: -c.y if side == "top" else c.y)
        us = [pu(l.vert.co) for l in f.loops]
        vv = [pv(l.vert.co) for l in f.loops]
        umin, umax, vmin, vmax = min(us), max(us), min(vv), max(vv)
        u0, v0, u1, v1 = cell
        for l, a, b in zip(f.loops, us, vv):
            fu = (a - umin) / (umax - umin) if umax > umin else 0.5
            fv = (b - vmin) / (vmax - vmin) if vmax > vmin else 0.5
            l[uv].uv = (u0 + fu * (u1 - u0), v0 + fv * (v1 - v0))
    return corners


def main():
    a = args()
    spec = json.load(open(a.spec))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a.base)
    arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    # Section 0 of each piece (pNNs0_<bone>); other sections (a head's s1)
    # are left out, and so removed.
    pieces = {o.name.split("_", 1)[1]: o for o in bpy.context.scene.objects
              if o.type == "MESH" and o.name[:1] == "p" and o.name.split("_", 1)[0].endswith("s0")}
    img, cells = paint_atlas(spec["atlas"])
    mat = atlas_material(img)

    by_piece = {}
    for part in spec["parts"]:
        name = part["bone"].split("_", 1)[1]
        if name not in pieces:
            raise SystemExit("the base has no piece for bone %s (pieces: %s)"
                             % (part["bone"], ", ".join(sorted(pieces))))
        by_piece.setdefault(name, []).append(part)

    keep = []
    for name, parts in by_piece.items():
        ob = pieces[name]
        bm = bmesh.new()
        uv = bm.loops.layers.uv.new("UVMap")
        verts = []
        for part in parts:
            verts += box(bm, uv, part, arm, cells)
        inv = ob.matrix_world.inverted()
        for v in bm.verts:
            v.co = inv @ v.co
        me = bpy.data.meshes.new(ob.name)
        bm.to_mesh(me)
        bm.free()
        me.materials.append(mat)
        ob.data = me
        bone = next(b.name for b in arm.data.bones if b.name.split("_", 1)[-1] == name)
        group = ob.vertex_groups.get(bone) or ob.vertex_groups.new(name=bone)
        group.add(range(len(me.vertices)), 1.0, "REPLACE")
        keep.append(ob)
        print("%-14s %d boxes, %d triangles" % (name, len(parts), 12 * len(parts)))

    # Everything the spec does not build is left out of the export, and so
    # removed from the model by fromgltf: the joint pieces, and any piece
    # the spec gives no box.
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    for ob in keep:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(filepath=a.out, export_format="GLB", use_selection=True, export_yup=True,
                              export_apply=False, export_skins=True, export_animations=False,
                              export_morph=False, export_texcoords=True, export_normals=True)
    print("%d pieces, %d triangles, written to %s" % (len(keep), 12 * len(spec["parts"]), a.out))

    if a.preview:
        for ob in bpy.context.scene.objects:
            if ob.type == "MESH" and ob not in keep:
                ob.hide_render = True
        sc = bpy.context.scene
        cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
        sc.collection.objects.link(cam)
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = 2.1
        cam.location = (0.9, -3.0, 1.0)
        cam.rotation_euler = (Vector((0, 0, 0.95)) - cam.location).to_track_quat("-Z", "Y").to_euler()
        sc.camera = cam
        sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
        sc.collection.objects.link(sun)
        sun.rotation_euler = (0.7, 0.2, 0.4)
        sc.world = bpy.data.worlds.new("w")
        sc.world.color = (0.5, 0.5, 0.55)
        sc.render.resolution_x, sc.render.resolution_y = 400, 600
        sc.render.filepath = a.preview
        bpy.ops.render.render(write_still=True)


main()
