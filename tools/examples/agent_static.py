"""Build "Agent Static", an extra playable character, as a mod source folder.

A worked example of the character tools, from the disc's files only:

  - the model is Jake Fenton's body (chr69) with R-109's head (chr133),
    grafted with ts2gltf (the neck joint and bridges come with the head);
  - his brown vest is recoloured electric teal and his shirt a cool grey,
    as new textures (ids 8000 and 8001; the disc uses 0-5293);
  - the character-select preview (chrinc.pak) is grafted the same way and
    its embedded textures recoloured to match;
  - the 64x64 portrait is rendered in Blender (tools/blender/ts2_portrait.py).

He takes chr id 70's files (chr71, a NeoTokyo pedestrian) in chr.pak and
chrinc.pak only, through the paks/ form, so the level paks that carry the
pedestrian keep him. The output is a ts2mod source folder:

  python3 -I tools/examples/agent_static.py game/data <work dir> <mod source> \\
      [--blender /Applications/Blender.app/Contents/MacOS/Blender]
  python3 -I tools/ts2mod.py build <mod source> game/data <mod>
"""

import argparse
import colorsys
import os
import shutil
import subprocess
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
import ts2gltf  # noqa: E402
import ts2pak  # noqa: E402
import ts2xbr  # noqa: E402
import ts2xbt  # noqa: E402

BODY, HEAD, SLOT = "chr69", "chr133", "chr71"
# Jake Fenton's textures, in chr.pak: 0475 the vest, 0472 the shirt.
RECOLOUR = {475: (8000, "teal"), 472: (8001, "cool")}
PORTRAIT = "textures/misc/chrimage_agentstatic.xbt"
PORTRAIT_BASE = "textures/misc/chrimage_ped3.xbt"     # header to copy (64x64 DXT3)


def recolour(rgba, how):
    """Keep each texel's shading, change its colour."""
    out = bytearray(rgba)
    for i in range(0, len(out), 4):
        r, g, b = out[i] / 255, out[i + 1] / 255, out[i + 2] / 255
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        if how == "teal":
            # Brown leather to an electric teal: hue 0.48, saturated, a
            # little brighter so it reads at a distance.
            r, g, b = colorsys.hls_to_rgb(0.48, min(1.0, l * 1.25 + 0.04), 0.85)
        else:
            r, g, b = (min(1.0, c * k) for c, k in zip((r, g, b), (0.72, 0.84, 0.92)))
        out[i:i + 3] = bytes(int(c * 255 + 0.5) for c in (r, g, b))
    return bytes(out)


def recolour_xbt(blob, how):
    """A recoloured copy in the same format and size, mip chain rebuilt."""
    x = ts2xbt.Xbt(blob) if not isinstance(blob, ts2xbt.Xbt) else blob
    w, h, _ = x.sizes[0]
    rgba = recolour(ts2xbt.decode_level(x, 0), how)
    return ts2xbt.new_xbt(rgba, w, h, x.header.format)


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


def run(cmd):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("data", help="the disc's data folder (game/data)")
    ap.add_argument("work", help="scratch folder (unpacked paks, intermediates)")
    ap.add_argument("out", help="ts2mod source folder to write")
    ap.add_argument("--blender", default="/Applications/Blender.app/Contents/MacOS/Blender")
    a = ap.parse_args()

    chr_ = unpack(os.path.join(a.data, "chr.pak"), os.path.join(a.work, "chr"))
    inc = unpack(os.path.join(a.data, "chrinc.pak"), os.path.join(a.work, "chrinc"))
    fe = unpack(os.path.join(a.data, "fe_anim.pak"), os.path.join(a.work, "fe_anim"))
    front = unpack(os.path.join(a.data, "arcade", "l_101.pak"), os.path.join(a.work, "l_101"))
    bindpose = os.path.join(fe, "anim", "data", "ts2")
    py = sys.executable

    # 1. The in-game model: graft, then point the vest and shirt at new ids.
    graft = os.path.join(a.work, "graft.xbr")
    run([py, "-I", os.path.join(TOOLS, "ts2gltf.py"), "graft",
         os.path.join(chr_, "ob", "chrs", BODY + ".xbr"), os.path.join(chr_, "ob", "chrs", HEAD + ".xbr"),
         graft, "--pieces", "head", "--textures", chr_, "--bindpose", bindpose])
    data, xbr = ts2xbr.load(graft)
    texdir = os.path.join(a.work, "textures")          # chr.pak's textures plus the new ones
    if os.path.isdir(texdir):
        shutil.rmtree(texdir)
    shutil.copytree(os.path.join(chr_, "textures"), texdir)
    new_tex = {}
    for old, (new, how) in RECOLOUR.items():
        blob = recolour_xbt(open(os.path.join(chr_, "textures", "%04d.xbt" % old), "rb").read(), how)
        new_tex[new] = blob
        with open(os.path.join(texdir, "%04d.xbt" % new), "wb") as f:
            f.write(blob)
    for m in xbr["materials"]:
        if m["texture"] in RECOLOUR:
            m["texture"] = RECOLOUR[m["texture"]][0]
    model = ts2xbr.build(xbr)
    ts2xbr.parse(model)

    # 2. The character-select preview: the same graft over the chrinc files,
    # then its embedded copies of the vest and shirt recoloured. A chrinc
    # file's materials are in the same order as the chr.pak model's.
    graft_inc = os.path.join(a.work, "graft_inc.xbr")
    run([py, "-I", os.path.join(TOOLS, "ts2gltf.py"), "graft",
         os.path.join(inc, "ob", "chrincs", BODY + ".xbr"), os.path.join(inc, "ob", "chrincs", HEAD + ".xbr"),
         graft_inc, "--pieces", "head", "--textures", chr_, "--bindpose", bindpose])
    _, gx = ts2xbr.load(graft)
    _, ix = ts2xbr.load(graft_inc)
    for gm, im in zip(gx["materials"], ix["materials"]):
        if gm["texture"] in RECOLOUR and im["flags"] & ts2xbr.EMBEDDED_FLAG:
            k = im["texture"]
            ix["embedded"][k] = recolour_xbt(ix["embedded"][k], RECOLOUR[gm["texture"]][1])
    preview = ts2xbr.build(ix)
    ts2xbr.parse(preview)

    # 3. The portrait, from the in-game model.
    glb = os.path.join(a.work, "agentstatic.glb")
    final = os.path.join(a.work, "agentstatic.xbr")
    with open(final, "wb") as f:
        f.write(model)
    run([py, "-I", os.path.join(TOOLS, "ts2gltf.py"), "gltf", final, glb,
         "--textures", texdir, "--bindpose", bindpose])
    png = os.path.join(a.work, "portrait.png")
    run([a.blender, "-b", "--factory-startup", "--python",
         os.path.join(TOOLS, "blender", "ts2_portrait.py"), "--", glb, png, "--colour", "0.1,0.75,0.7"])
    base = ts2xbt.Xbt.load(os.path.join(front, *PORTRAIT_BASE.split("/")))
    portrait, _ = ts2xbt.import_image(base, open(png, "rb").read(), "png")

    # 4. The mod source: chr.pak and chrinc.pak only, and the front end's pak.
    def put(rel, blob):
        p = os.path.join(a.out, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(blob)
    put("paks/chr.pak/ob/chrs/%s.xbr" % SLOT, model)
    for new, blob in new_tex.items():
        put("paks/chr.pak/textures/%04d.xbt" % new, blob)
    put("paks/chrinc.pak/ob/chrincs/%s.xbr" % SLOT, preview)
    put("paks/arcade/l_101.pak/" + PORTRAIT, portrait)
    print("mod source written to", a.out)


if __name__ == "__main__":
    main()
