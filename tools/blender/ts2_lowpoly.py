"""Build a low-poly (N64-era) character on TimeSplitters 2's human skeleton,
in Blender.

What makes a character read as N64 rather than as blocks: few polygons, but
tapered, chamfered shapes (6-8 sided limbs, a torso that widens to the
shoulders, a head narrower at the jaw than at the brow); smooth (Gouraud)
shading; and soft, blurry textures with gradients rather than crisp pixels.
So each part here is a run of rings along a bone, each ring a rounded
cross-section of its own width and depth, shaded smooth, with one texture
cell wrapped around it (the front of the part is the middle of the cell).
Every vertex is weighted wholly to its bone (TS2 has no blend weights). The
base model's joint pieces are dropped: limbs overlap at the joints, as on the
N64.

  Blender -b --factory-startup --python tools/blender/ts2_lowpoly.py -- \\
      <base.glb> <spec.json> <out.glb> [--preview out.png]

base.glb is a TS2 human exported by `tools/ts2gltf.py gltf` (joints
b00_pelvis ... b18_l_foot; the character faces -Y, its right is -X). Then
`tools/ts2gltf.py fromgltf <base.xbr> out.glb out.xbr --texture-dir <dir>`.

The spec (JSON):

  {"atlas": {"size": 256, "cell": 64, "blur": 1.2,
             "cells": {"<name>": {"colour": [r, g, b], "span": 1, "blur": 1.2,
                                   "gradient": [top, bottom],
                                   "shapes": [{"rect": [x, y, w, h], "colour": [...], "soft": 1.5},
                                              {"ellipse": [cx, cy, rx, ry], "colour": [...]}]}}},
   "parts": [{"bone": "b13_r_thigh", "to": "b14_r_shin", "extend": [0.04, 0.02],
              "sides": 8, "round": 2.5,
              "rings": [[0.0, 0.17, 0.18], [0.5, 0.15, 0.16], [1.0, 0.12, 0.13]],
              "cell": "trousers"}]}

  - A cell is `cell` pixels square (span x span of them with `span`, for a
    face) in a `size` atlas, placed in order where it fits. Its
    base colour is multiplied top to bottom by `gradient`; shapes are painted
    over it in order (x, y, w, h and cx, cy, rx, ry in 0..1 of the cell, y
    down from the top; `soft` feathers the edge, in pixels); then the atlas
    is blurred by `blur` pixels (the atlas's, or the cell's own).
  - A cell wraps around its part: u 0.5 is the part's front (the
    character's front), 0 and 1 its back, 0.25 its right side and 0.75 its
    left; v runs from the part's lowest ring (bottom of the cell) to its
    highest (top).
  - A part runs from its bone's joint to `to` (another joint, or an offset
    [x, y, z] in metres, z up), lengthened by `extend` at each end and moved
    by `offset`. Each ring is [t, width, depth] or [t, width, depth, dx, dy]
    with t from 0 (start) to 1 (end) and dx, dy shifting that ring (dy < 0 is
    forward). `sides` is the number of edges around (default 8), `round` the
    superellipse exponent of the cross-section (2 an ellipse, higher a
    rounder box; default 2.5). `front` (default 1) gives the front half of
    the part that many times its share of the cell, as a face needs. The
    ends are capped.
"""

import argparse
import json
import math
import sys

import bpy
import bmesh
import numpy as np
from mathutils import Vector


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="ts2_lowpoly")
    ap.add_argument("base")
    ap.add_argument("spec")
    ap.add_argument("out")
    ap.add_argument("--preview", help="also render a preview PNG (front three-quarter and back)")
    return ap.parse_args(argv)


# --------------------------------------------------------------------------
# The atlas


def _coverage(cell, shape):
    """0..1 per texel of a cell: how much of it the shape covers."""
    n = cell
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) + 0.5
    soft = max(0.5, float(shape.get("soft", 0.75)))
    if "rect" in shape:
        x, y, w, h = (v * n for v in shape["rect"])
        dx = np.maximum(x - xx, xx - (x + w))
        dy = np.maximum(y - yy, yy - (y + h))
        d = np.maximum(dx, dy)                       # < 0 inside
    else:
        cx, cy, rx, ry = (v * n for v in shape["ellipse"])
        r = np.sqrt(((xx - cx) / max(rx, 1e-3)) ** 2 + ((yy - cy) / max(ry, 1e-3)) ** 2)
        d = (r - 1.0) * min(rx, ry)
    return np.clip(0.5 - d / soft, 0.0, 1.0)


def _blur(px, radius):
    if radius <= 0:
        return px
    k = np.arange(-int(radius * 3) - 1, int(radius * 3) + 2, dtype=np.float32)
    k = np.exp(-(k * k) / (2 * radius * radius))
    k /= k.sum()
    pad = len(k) // 2
    for axis in (0, 1):
        p = np.pad(px, [(pad, pad) if a == axis else (0, 0) for a in range(3)], mode="edge")
        px = sum(w * np.take(p, range(i, i + px.shape[axis]), axis=axis) for i, w in enumerate(k))
    return px


def paint_atlas(spec):
    size, cell = spec.get("size", 256), spec.get("cell", 64)
    grid = size // cell
    used = np.zeros((grid, grid), dtype=bool)
    px = np.zeros((size, size, 3), dtype=np.float32)          # row 0 = top
    where = {}
    for name, c in spec["cells"].items():
        span = int(c.get("span", 1))                           # cells of span x span grid squares
        n = cell * span
        spot = next(((gx, gy) for gy in range(grid - span + 1) for gx in range(grid - span + 1)
                     if not used[gy:gy + span, gx:gx + span].any()), None)
        if spot is None:
            raise SystemExit("the %dx%d atlas has no room for cell %s" % (size, size, name))
        gx, gy = spot
        used[gy:gy + span, gx:gx + span] = True
        cx, cy = gx * cell, gy * cell
        block = np.empty((n, n, 3), dtype=np.float32)
        block[:] = c["colour"]
        top, bottom = c.get("gradient", (1.0, 1.0))
        block *= np.linspace(top, bottom, n, dtype=np.float32)[:, None, None]
        for shape in c.get("shapes", []):
            a = _coverage(n, shape)[..., None]
            block = block * (1 - a) + np.array(shape["colour"], dtype=np.float32) * a
        px[cy:cy + n, cx:cx + n] = np.clip(_blur(block, float(c.get("blur", spec.get("blur", 1.2)))), 0, 1)
        # UV rectangle of the cell, v up from the bottom.
        u0, u1 = (cx + 0.5) / size, (cx + n - 0.5) / size
        v1, v0 = 1 - (cy + 0.5) / size, 1 - (cy + n - 0.5) / size
        where[name] = (u0, v0, u1, v1)
    rgba = np.concatenate([px, np.ones((size, size, 1), dtype=np.float32)], axis=2)
    img = bpy.data.images.new("ts2_lowpoly_atlas", size, size, alpha=False)
    img.pixels = rgba[::-1].ravel().tolist()                   # Blender rows go up
    img.pack()
    return img, where


def atlas_material(img):
    mat = bpy.data.materials.new("lowpoly_atlas")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.9
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Linear"                               # the N64 filtered
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


# --------------------------------------------------------------------------
# The parts


def joint(arm, name):
    for b in arm.data.bones:
        if b.name == name or b.name.split("_", 1)[-1] == name:
            return arm.matrix_world @ b.head_local
    raise SystemExit("no joint %s in the base" % name)


def frame(axis):
    """Unit vectors across a part: x toward the character's left (+X) and y
    toward its back (+Y), as near as the part's direction allows."""
    x = Vector((1, 0, 0))
    if abs(axis.dot(x)) > 0.95:
        x = Vector((0, 0, 1))
    x = (x - axis * x.dot(axis)).normalized()
    y = Vector((0, 1, 0))
    y = y - axis * y.dot(axis) - x * y.dot(x)
    if y.length < 1e-4:                                        # a part along Y (a foot)
        y = Vector((0, 0, -1)) if axis.y < 0 else Vector((0, 0, 1))
        y = (y - axis * y.dot(axis) - x * y.dot(x))
    return x, y.normalized()


def ring_points(centre, x, y, w, d, sides, rnd):
    """Points around a rounded cross-section, starting at the back (+y) and
    going round through the right (-x), the front (-y) and the left (+x), so
    the front is the middle of the run."""
    pts = []
    for i in range(sides):
        th = 2 * math.pi * i / sides
        c, s = math.cos(th), math.sin(th)
        # Superellipse: |x/a|^n + |y/b|^n = 1.
        ex = math.copysign(abs(s) ** (2.0 / rnd), s)
        ey = math.copysign(abs(c) ** (2.0 / rnd), c)
        pts.append(centre - x * (w / 2) * ex + y * (d / 2) * ey)
    return pts


def build_part(bm, uv, part, arm, cells):
    start = joint(arm, part["bone"])
    to = part["to"]
    end = joint(arm, to) if isinstance(to, str) else start + Vector(to)
    off = Vector(part.get("offset", (0, 0, 0)))
    start, end = start + off, end + off
    axis = (end - start).normalized()
    e0, e1 = part.get("extend", (0.0, 0.0))
    start, end = start - axis * e0, end + axis * e1
    x, y = frame(axis)
    sides, rnd = int(part.get("sides", 8)), float(part.get("round", 2.5))
    loops = []
    for r in part["rings"]:
        t, w, d = r[0], r[1], r[2]
        dx, dy = (r[3], r[4]) if len(r) > 4 else (0.0, 0.0)
        c = start + (end - start) * t + Vector((dx, dy, 0))
        loops.append(ring_points(c, x, y, w, d, sides, rnd))

    u0, v0, u1, v1 = cells[part["cell"]]
    zs = [sum((p.z for p in lp), 0.0) / sides for lp in loops]
    zmin, zmax = min(zs), max(zs)

    def vcoord(k):
        f = (zs[k] - zmin) / (zmax - zmin) if zmax > zmin else 0.5
        return v0 + f * (v1 - v0)

    # front > 1 gives the front of the part more of the cell (a face): the
    # wrap's u is warped so the front half (u 0.25-0.75) takes `front` times
    # its share.
    fw = float(part.get("front", 1.0))

    def ucoord(i):
        f = i / sides
        if fw != 1.0:
            back = 0.5 / (1 + fw)                  # width of each back quarter in u
            if f < 0.25:
                f = f / 0.25 * back
            elif f <= 0.75:
                f = back + (f - 0.25) / 0.5 * (1 - 2 * back)
            else:
                f = 1 - back + (f - 0.75) / 0.25 * back
        return u0 + f * (u1 - u0)

    verts = [[bm.verts.new(p) for p in lp] for lp in loops]
    faces = []
    for k in range(len(verts) - 1):
        a, b = verts[k], verts[k + 1]
        for i in range(sides):
            j = (i + 1) % sides
            f = bm.faces.new((a[i], a[j], b[j], b[i]))
            # The seam is at the back: the last column runs to u 1.
            for loop, (col, row) in zip(f.loops, ((i, k), (i + 1, k), (i + 1, k + 1), (i, k + 1))):
                loop[uv].uv = (ucoord(col), vcoord(row))
            faces.append((f, (start + end) / 2))
    for k, out in ((0, -axis), (len(verts) - 1, axis)):
        f = bm.faces.new(verts[k])
        for loop, i in zip(f.loops, range(sides)):
            loop[uv].uv = (ucoord(i + 0.5), vcoord(k))
        faces.append((f, f.calc_center_median() - out))
    for f, inside in faces:                     # outward normals, smooth shading
        f.normal_update()
        if f.normal.dot(f.calc_center_median() - inside) < 0:
            f.normal_flip()
        f.smooth = True
    return 2 * sides * (len(verts) - 1) + 2 * (sides - 2)


def main():
    a = args()
    spec = json.load(open(a.spec))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a.base)
    arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    # Section 0 of each piece (pNNs0_<bone>); other sections (a head's s1)
    # are left out of the export, and so removed.
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
        if part["cell"] not in cells:
            raise SystemExit("part on %s uses cell %s, which the atlas does not have" % (part["bone"], part["cell"]))
        by_piece.setdefault(name, []).append(part)

    keep, total = [], 0
    for name, parts in by_piece.items():
        ob = pieces[name]
        bm = bmesh.new()
        uv = bm.loops.layers.uv.new("UVMap")
        tris = sum(build_part(bm, uv, p, arm, cells) for p in parts)
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
        total += tris
        print("%-14s %d parts, %d triangles" % (name, len(parts), tris))

    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    for ob in keep:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(filepath=a.out, export_format="GLB", use_selection=True, export_yup=True,
                              export_apply=False, export_skins=True, export_animations=False,
                              export_morph=False, export_texcoords=True, export_normals=True)
    print("%d pieces, %d triangles, written to %s" % (len(keep), total, a.out))

    if a.preview:
        preview(a.preview, keep)


def preview(path, keep):
    """Front three-quarter and back, side by side."""
    sc = bpy.context.scene
    for ob in sc.objects:
        if ob.type == "MESH" and ob not in keep:
            ob.hide_render = True
    engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    sc.view_settings.view_transform = "Standard"
    sc.world = bpy.data.worlds.new("w")
    sc.world.color = (0.45, 0.45, 0.5)
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3.0
    sc.collection.objects.link(sun)
    sun.rotation_euler = (0.8, 0.0, -0.5)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 2.0
    sc.render.resolution_x, sc.render.resolution_y = 300, 600
    shots = []
    for k, loc in enumerate(((1.6, -2.6, 1.05), (-1.2, 2.8, 1.05))):
        cam.location = loc
        cam.rotation_euler = (Vector((0, 0, 0.95)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        shot = "%s.%d.png" % (path, k)
        sc.render.filepath = shot
        bpy.ops.render.render(write_still=True)
        shots.append(shot)
    imgs = [np.array(bpy.data.images.load(s).pixels[:], dtype=np.float32).reshape(600, 300, 4) for s in shots]
    out = bpy.data.images.new("preview", 600, 600, alpha=True)
    out.pixels = np.concatenate(imgs, axis=1).ravel().tolist()
    out.filepath_raw = path
    out.file_format = "PNG"
    out.save()


main()
