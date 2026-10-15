"""Render a TimeSplitters 2 character-select portrait from a character .glb.

The game's portraits (textures/misc/chrimage_*.xbt in data/arcade/l_101.pak)
are 64x64 DXT3: a head-and-shoulders render, three-quarter view, on a dark
backdrop tinted with one colour, with rounded corners cut out in alpha. This
renders the same from a model exported by tools/ts2gltf.py (its joints are
named b04_head and so on) and writes a 64x64 PNG; tools/ts2xbt.py import
turns that into the .xbt.

  Blender -b --factory-startup --python tools/blender/ts2_portrait.py -- \\
      <model.glb> <out.png> [--colour 0.25,0.45,0.9] [--yaw 25] [--size 64]

Runs inside Blender (bpy, and the numpy Blender ships with).
"""

import argparse
import math
import sys

import bpy
import numpy as np
from mathutils import Vector


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="ts2_portrait")
    ap.add_argument("glb")
    ap.add_argument("out")
    ap.add_argument("--colour", default="0.25,0.45,0.9",
                    help="backdrop tint, r,g,b in 0..1")
    ap.add_argument("--yaw", type=float, default=25.0,
                    help="degrees the camera turns from straight on")
    ap.add_argument("--pitch", type=float, default=4.0)
    ap.add_argument("--size", type=int, default=64)
    ap.add_argument("--render", type=int, default=256,
                    help="render size before the downsample")
    ap.add_argument("--zoom", type=float, default=1.0,
                    help=">1 frames closer")
    return ap.parse_args(argv)


def head_frame(arm):
    """(head joint, chest joint, model forward) in world space."""
    bones = {b.name.split("_", 1)[0]: b for b in arm.data.bones}
    head = arm.matrix_world @ bones["b04"].head_local
    chest = arm.matrix_world @ bones["b02"].head_local
    # The character faces the side its toes point to: foot joint (b15 /
    # b18) to the toe end of the foot meshes is unreliable, so use the
    # head mesh instead: the face sticks out further than the back of the
    # head does.
    return head, chest


def face_direction(meshes, head):
    best, score = Vector((0, -1, 0)), -1.0
    pts = []
    for ob in meshes:
        if "head" not in ob.name and "b04" not in ob.name:
            continue
        m = ob.matrix_world
        pts += [m @ v.co for v in ob.data.vertices]
    if not pts:
        return best
    for d in (Vector((0, -1, 0)), Vector((0, 1, 0)), Vector((1, 0, 0)), Vector((-1, 0, 0))):
        reach = max((p - head).dot(d) for p in pts)
        if reach > score:
            best, score = d, reach
    return best


def main():
    a = args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a.glb)
    arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    bpy.context.view_layer.update()

    head, chest = head_frame(arm)
    fwd = face_direction(meshes, head)
    up = Vector((0, 0, 1))
    neck_len = (head - chest).length or 0.3
    # Framed as the shipped portraits: the head fills the upper two thirds,
    # the shoulders the bottom edge.
    target = head + up * neck_len * 0.12
    dist = neck_len * 3.2 / a.zoom

    yaw, pitch = math.radians(a.yaw), math.radians(a.pitch)
    side = fwd.cross(up).normalized()
    view = (fwd * math.cos(yaw) + side * math.sin(yaw)) * math.cos(pitch) + up * math.sin(pitch)
    cam_data = bpy.data.cameras.new("portrait")
    cam_data.lens = 85
    cam = bpy.data.objects.new("portrait", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = target + view.normalized() * dist
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam

    # Key light from the camera's side and above, a soft fill: the shipped
    # portraits are lit from the front with a dark falloff.
    for name, energy, offset in (("key", 4.0, side * 1.5 + up * 1.5), ("fill", 1.2, -side * 2 + up * 0.3)):
        ld = bpy.data.lights.new(name, "SUN")
        ld.energy = energy
        lo = bpy.data.objects.new(name, ld)
        bpy.context.scene.collection.objects.link(lo)
        lo.location = cam.location + offset
        lo.rotation_euler = (target - lo.location).to_track_quat("-Z", "Y").to_euler()

    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [
        e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
    sc.render.resolution_x = sc.render.resolution_y = a.render
    sc.render.film_transparent = True
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.view_settings.view_transform = "Standard"
    world = bpy.data.worlds.new("w")
    world.color = (0.35, 0.35, 0.35)
    sc.world = world
    tmp = a.out + ".render.png"
    sc.render.filepath = tmp
    bpy.ops.render.render(write_still=True)

    img = bpy.data.images.load(tmp)
    n = a.render
    px = np.array(img.pixels[:], dtype=np.float32).reshape(n, n, 4)   # bottom-up
    tint = np.array([float(c) for c in a.colour.split(",")], dtype=np.float32)

    # Backdrop: the tint, brightest behind the head, falling to near black.
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) / (n - 1)
    r = np.sqrt((xx - 0.5) ** 2 + (yy - 0.6) ** 2)
    glow = np.clip(1.0 - r * 1.6, 0.0, 1.0) ** 1.5
    back = (0.06 + 0.5 * glow)[..., None] * tint[None, None, :]
    rgb = px[..., :3] * px[..., 3:4] + back * (1.0 - px[..., 3:4])

    # Rounded corners: radius 12/64 of the side, as the shipped portraits.
    rad = 12.0 / 64.0
    cx = np.clip(np.maximum(rad - xx, xx - (1 - rad)), 0, None)
    cy = np.clip(np.maximum(rad - yy, yy - (1 - rad)), 0, None)
    alpha = np.clip((rad - np.sqrt(cx ** 2 + cy ** 2)) * n, 0.0, 1.0)

    out = np.concatenate([rgb, alpha[..., None]], axis=2)
    f = n // a.size
    out = out[:a.size * f, :a.size * f].reshape(a.size, f, a.size, f, 4).mean(axis=(1, 3))
    res = bpy.data.images.new("portrait", a.size, a.size, alpha=True)
    res.pixels = out.astype(np.float32).ravel().tolist()
    res.filepath_raw = a.out
    res.file_format = "PNG"
    res.save()
    print("portrait written to", a.out)


main()
