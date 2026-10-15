"""Build new TimeSplitters 2 characters from a recipe: one character's body
with another's head, recoloured, with a character-select preview and a
portrait, laid out as a ts2mod source folder.

A recipe is JSON:

  {"characters": [
    {"name": "Agent Static",
     "slot": "chr71",                 the files it takes over (chr id 70)
     "body": "chr69", "head": "chr133",
     "recolour": {"475": {"hue": 0.48, "sat": 0.85, "light": 1.25},
                  "472": {"tint": [0.72, 0.84, 0.92]}},
     "portrait_colour": [0.1, 0.75, 0.7]}
  ]}

  - body and head name chr.pak models (ob/chrs/<name>.xbr); the head piece,
    its neck joint and bridges come from the head model (ts2gltf graft).
  - recolour maps a texture id the finished model uses to a new texture:
    hue/sat (0..1, replacing the texel's) with light (a multiplier on its
    lightness), or tint (a multiplier per channel). New textures get ids
    from 8000 up (the disc uses 0-5293).
  - The preview (chrinc.pak) is the in-game model with its textures
    embedded, as 149 of the disc's 154 previews are.
  - The portrait (textures/misc/chrimage_<slot>.xbt in data/arcade/
    l_101.pak, 64x64 DXT3) is rendered in Blender by
    tools/blender/ts2_portrait.py.

Only chr.pak, chrinc.pak and l_101.pak are written (the paks/ form), so a
level pak that carries the slot's original keeps it: pick slots no arcade
pak carries (chr71-chr90, the NeoTokyo pedestrians, are only in
l_38_ST.pak). The game-side declaration (name, roster slot, unlock) is
separate.

  python3 -I tools/ts2kitbash.py <recipe.json> game/data <work dir> <mod source>
  python3 -I tools/ts2mod.py build <mod source> game/data <mod>
"""

import argparse
import colorsys
import json
import os
import shutil
import subprocess
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import ts2pak  # noqa: E402
import ts2xbr  # noqa: E402
import ts2xbt  # noqa: E402

FIRST_NEW_TEXTURE = 8000
PORTRAIT_BASE = "textures/misc/chrimage_ped3.xbt"     # header to copy (64x64 DXT3)
PREVIEW_LIMIT = 512000      # the front end loads a preview into a buffer this size
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"


def recolour_pixels(rgba, how):
    """Keep each texel's shading, change its colour."""
    out = bytearray(rgba)
    tint = how.get("tint")
    for i in range(0, len(out), 4):
        r, g, b = out[i] / 255, out[i + 1] / 255, out[i + 2] / 255
        if tint:
            r, g, b = (min(1.0, c * k) for c, k in zip((r, g, b), tint))
        else:
            h, l, s = colorsys.rgb_to_hls(r, g, b)
            l = min(1.0, l * how.get("light", 1.0))
            r, g, b = colorsys.hls_to_rgb(how.get("hue", h), l, how.get("sat", s))
        out[i:i + 3] = bytes(int(c * 255 + 0.5) for c in (r, g, b))
    return bytes(out)


def recolour_xbt(blob, how):
    """A recoloured copy in the same format and size, mip chain rebuilt."""
    x = ts2xbt.Xbt(blob)
    w, h, _ = x.sizes[0]
    return ts2xbt.new_xbt(recolour_pixels(ts2xbt.decode_level(x, 0), how), w, h, x.header.format)


def unpack(pak, out):
    if not os.path.isdir(out):
        data = open(pak, "rb").read()
        _, entries, _ = ts2pak.read_pak(data)
        for e in entries:
            p = os.path.join(out, *e["name"].split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data[e["position"]:e["position"] + e["length"]])
    return out


def run(cmd, quiet=False):
    print("+", " ".join(os.path.basename(c) if os.path.isabs(c) else c for c in cmd[:4]), "...")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL if quiet else None)


def build_character(c, ctx, next_id):
    """Writes one character's files under ctx['out']; returns the next free
    texture id."""
    py, gltf = sys.executable, os.path.join(TOOLS, "ts2gltf.py")
    chr_, work = ctx["chr"], os.path.join(ctx["work"], c["slot"])
    os.makedirs(work, exist_ok=True)
    texdir = ctx["textures"]

    # The in-game model: graft, then point recoloured textures at new ids.
    graft = os.path.join(work, "graft.xbr")
    run([py, "-I", gltf, "graft", os.path.join(chr_, "ob", "chrs", c["body"] + ".xbr"),
         os.path.join(chr_, "ob", "chrs", c["head"] + ".xbr"), graft, "--pieces", "head",
         "--textures", chr_, "--bindpose", ctx["bindpose"]], quiet=True)
    _, xbr = ts2xbr.load(graft)
    used = {m["texture"] for m in xbr["materials"]}
    new_ids = {}
    for old, how in sorted(c.get("recolour", {}).items()):
        old = int(old)
        if old not in used:
            raise SystemExit("%s: texture %d is not one the model uses (%s)"
                             % (c["name"], old, sorted(used)))
        blob = recolour_xbt(open(os.path.join(chr_, "textures", "%04d.xbt" % old), "rb").read(), how)
        new_ids[old] = next_id
        with open(os.path.join(texdir, "%04d.xbt" % next_id), "wb") as f:
            f.write(blob)
        ctx["put"]("paks/chr.pak/textures/%04d.xbt" % next_id, blob)
        next_id += 1
    for m in xbr["materials"]:
        m["texture"] = new_ids.get(m["texture"], m["texture"])
    model = ts2xbr.build(xbr)
    ts2xbr.parse(model)
    final = os.path.join(work, c["slot"] + ".xbr")
    with open(final, "wb") as f:
        f.write(model)
    ctx["put"]("paks/chr.pak/ob/chrs/%s.xbr" % c["slot"], model)

    # The preview: on the disc, 149 of the 154 chrinc.pak previews are their
    # chr.pak model exactly (pieces, geometry, descriptor) with the textures
    # embedded, so the finished model with its textures embedded is one.
    _, prev = ts2xbr.load(final)
    prev["embedded"] = []
    for m in prev["materials"]:
        prev["embedded"].append(open(os.path.join(texdir, "%04d.xbt" % m["texture"]), "rb").read())
        m["texture"] = len(prev["embedded"]) - 1
        m["flags"] |= ts2xbr.EMBEDDED_FLAG
    blob = ts2xbr.build(prev)
    ts2xbr.parse(blob)
    if len(blob) > PREVIEW_LIMIT:
        raise SystemExit("%s: preview is %d bytes, over the front end's %d-byte buffer"
                         % (c["name"], len(blob), PREVIEW_LIMIT))
    ctx["put"]("paks/chrinc.pak/ob/chrincs/%s.xbr" % c["slot"], blob)
    glb = os.path.join(work, c["slot"] + ".glb")
    run([py, "-I", gltf, "gltf", final, glb, "--textures", texdir, "--bindpose", ctx["bindpose"]], quiet=True)

    # The portrait.
    png = os.path.join(work, "portrait.png")
    colour = ",".join(str(v) for v in c.get("portrait_colour", [0.25, 0.45, 0.9]))
    run([ctx["blender"], "-b", "--factory-startup", "--python",
         os.path.join(TOOLS, "blender", "ts2_portrait.py"), "--", glb, png, "--colour", colour], quiet=True)
    portrait, _ = ts2xbt.import_image(ctx["portrait_base"], open(png, "rb").read(), "png")
    ctx["put"]("paks/arcade/l_101.pak/textures/misc/chrimage_%s.xbt" % c["slot"], portrait)
    print("%s: %s (body %s, head %s), textures %s" % (c["name"], c["slot"], c["body"], c["head"],
                                                     sorted(new_ids.values()) or "unchanged"))
    return next_id


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("recipe")
    ap.add_argument("data", help="the disc's data folder (game/data)")
    ap.add_argument("work", help="scratch folder (unpacked paks, intermediates)")
    ap.add_argument("out", help="ts2mod source folder to write")
    ap.add_argument("--blender", default=BLENDER)
    a = ap.parse_args()

    recipe = json.load(open(a.recipe))
    slots = [c["slot"] for c in recipe["characters"]]
    if len(set(slots)) != len(slots):
        raise SystemExit("two characters in one slot")
    ctx = {"work": a.work, "out": a.out, "blender": a.blender,
           "chr": unpack(os.path.join(a.data, "chr.pak"), os.path.join(a.work, "chr"))}
    fe = unpack(os.path.join(a.data, "fe_anim.pak"), os.path.join(a.work, "fe_anim"))
    front = unpack(os.path.join(a.data, "arcade", "l_101.pak"), os.path.join(a.work, "l_101"))
    ctx["bindpose"] = os.path.join(fe, "anim", "data", "ts2")
    ctx["portrait_base"] = ts2xbt.Xbt.load(os.path.join(front, *PORTRAIT_BASE.split("/")))
    # chr.pak's textures plus the new ones, for the exporter and the preview.
    ctx["textures"] = os.path.join(a.work, "textures")
    if os.path.isdir(ctx["textures"]):
        shutil.rmtree(ctx["textures"])
    shutil.copytree(os.path.join(ctx["chr"], "textures"), ctx["textures"])

    def put(rel, blob):
        p = os.path.join(a.out, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(blob)
    ctx["put"] = put

    next_id = FIRST_NEW_TEXTURE
    for c in recipe["characters"]:
        next_id = build_character(c, ctx, next_id)
    with open(os.path.join(a.out, "characters.json"), "w") as f:
        json.dump(recipe, f, indent=1)
    print("%d characters written to %s" % (len(recipe["characters"]), a.out))


if __name__ == "__main__":
    main()
