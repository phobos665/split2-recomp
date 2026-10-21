"""Build new TimeSplitters 2 characters from a recipe: one character's body
with another's head, recoloured, with a character-select preview and a
portrait, written as a mod of loose files (a ts2mod source folder, which the
game reads as it is), with the declaration that puts them on the roster
(ts2/characters.ini).

A recipe is JSON:

  {"characters": [
    {"name": "Agent Static",
     "slot": "chr71", "chr_id": 70,   the files it takes over (chr id 70)
     "body": "chr69", "head": "chr133",
     "recolour": {"475": {"hue": 0.48, "sat": 0.85, "light": 1.25},
                  "472": {"tint": [0.72, 0.84, 0.92]}},
     "portrait_colour": [0.1, 0.75, 0.7],
     "roster": "next",                a spare roster slot (127-158 on PAL), or
                                      0-126 to replace the character there
     "bio": "Two sentences.",         the Gallery's description
     "background": "neo",             chrblank_<set>, shown while locked
     "unlock": "start",               start, never, or keep (the slot's rule)
     "stats": 68, "sounds": 68,       optional: this chr id's stats, voice
     "names": {"fr": "..."},          optional: the name in fr, de, it, es
     "bios": {"fr": "..."}}           optional: the description, likewise
  ]}

  - body and head name chr.pak models (ob/chrs/<name>.xbr); the head piece,
    its neck joint and bridges come from the head model (ts2gltf graft).
    Or "model": a finished .xbr (relative to the recipe; made in Blender and
    imported with ts2gltf fromgltf, or by tools/blender/ts2_lowpoly.py), with
    "model_textures" the folder of its new NNNN.xbt (default textures/).
  - recolour maps a texture id the finished model uses to a new texture:
    hue/sat (0..1, replacing the texel's) with light (a multiplier on its
    lightness), or tint (a multiplier per channel). New textures get ids
    in 8000-9999 from a hash of the picture (the disc uses 0-5293).
  - The preview (chrinc.pak) is the in-game model with its textures
    embedded, as 149 of the disc's 154 previews are.
  - The portrait (textures/misc/chrimage_<slot>.xbt in data/arcade/
    l_101.pak, and l_102.pak and gun.pak, 64x64 DXT3) is rendered in Blender by
    tools/blender/ts2_portrait.py.

Only chr.pak, chrinc.pak and the portrait paks are written (the paks/
form), so a level pak that carries the slot's original keeps it: pick slots
no arcade pak carries (chr71-chr90, the NeoTokyo pedestrians, are only in
l_38_ST.pak). ts2/characters.ini, which the game reads at start-up
(docs/formats/roster.md, "Adding a character (mods)"), says which roster
slot each one takes, its name, description, portrait and unlock rule.

The output folder is a mod as it stands (loose files, with mod.json): run
the game with it, alone or with other mods, or make one self-contained
folder of rebuilt paks out of it with ts2mod build.

  python3 -I tools/ts2kitbash.py <recipe.json> game/data <work dir> <mod>
  RECOMP_MODS=<mod>:<another mod> ./split2_recomp
  python3 -I tools/ts2mod.py build <mod> game/data <self-contained mod>   (optional)
"""

import argparse
import colorsys
import json
import os
import shutil
import subprocess
import sys
import zlib

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import ts2mod  # noqa: E402
import ts2pak  # noqa: E402
import ts2xbr  # noqa: E402
import ts2xbt  # noqa: E402

# New texture ids: 8000-9999 (the disc uses 0-5293), picked from a hash of the
# picture as ts2gltf fromgltf does, so two mods' new textures rarely land on
# the same id and a rebuild gives the same ids again.
NEW_TEXTURE_FIRST, NEW_TEXTURE_LAST = 8000, 9999
LANGS = ("fr", "de", "it", "es")
SETS = ("atom", "aztec", "circus", "gangster", "neo", "notredame", "planetx", "robot",
        "siberia", "spacestation", "ts1", "west")
INI_LINE = 500              # the game's reader takes lines of up to 511 bytes
BIO_MAX = 390               # and keeps a description of up to 398
PORTRAIT_BASE = "textures/misc/chrimage_ped3.xbt"     # header to copy (64x64 DXT3)
PORTRAIT_PAKS = ("arcade/l_101.pak", "arcade/l_102.pak", "gun.pak")
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


def allocate_texture(ctx, blob):
    span = NEW_TEXTURE_LAST - NEW_TEXTURE_FIRST + 1
    start = zlib.crc32(blob) % span
    for k in range(span):
        tid = NEW_TEXTURE_FIRST + (start + k) % span
        if ctx["new_textures"].get(tid, blob) == blob:
            ctx["new_textures"][tid] = blob
            return tid
    raise SystemExit("no free texture id left in %d-%d" % (NEW_TEXTURE_FIRST, NEW_TEXTURE_LAST))


def build_character(c, ctx):
    """Writes one character's files under ctx['out']."""
    py, gltf = sys.executable, os.path.join(TOOLS, "ts2gltf.py")
    chr_, work = ctx["chr"], os.path.join(ctx["work"], c["slot"])
    os.makedirs(work, exist_ok=True)
    texdir = ctx["textures"]

    # The in-game model: a finished .xbr (e.g. from Blender: ts2gltf fromgltf,
    # or tools/blender/ts2_lowpoly.py), or a graft; then recoloured textures
    # get new ids.
    if "model" in c:
        _, xbr = ts2xbr.load(os.path.join(ctx["recipe_dir"], c["model"]))
        mtex = os.path.join(ctx["recipe_dir"], c.get("model_textures", "textures"))
        for m in xbr["materials"]:
            if os.path.exists(os.path.join(chr_, "textures", "%04d.xbt" % m["texture"])):
                continue                     # one of the disc's
            p = os.path.join(mtex, "%04d.xbt" % m["texture"])
            if not os.path.exists(p):
                raise SystemExit("%s: texture %04d is neither the disc's nor in %s" % (c["name"], m["texture"], mtex))
            blob = open(p, "rb").read()
            if ctx["new_textures"].setdefault(m["texture"], blob) != blob:
                raise SystemExit("%s: texture id %04d is taken by another character" % (c["name"], m["texture"]))
            with open(os.path.join(texdir, "%04d.xbt" % m["texture"]), "wb") as f:
                f.write(blob)
            ctx["put"]("paks/chr.pak/textures/%04d.xbt" % m["texture"], blob)
    else:
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
        tid = allocate_texture(ctx, blob)
        new_ids[old] = tid
        with open(os.path.join(texdir, "%04d.xbt" % tid), "wb") as f:
            f.write(blob)
        ctx["put"]("paks/chr.pak/textures/%04d.xbt" % tid, blob)
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
    # Every pak that carries the shipped portraits gets the new one: the front
    # end's l_101.pak, and l_102.pak and gun.pak (where those copies are
    # shown is not traced).
    for pak in PORTRAIT_PAKS:
        ctx["put"]("paks/%s/textures/misc/chrimage_%s.xbt" % (pak, c["slot"]), portrait)
    print("%s: %s (%s), new textures %s" % (
        c["name"], c["slot"], c["model"] if "model" in c else "body %s, head %s" % (c["body"], c["head"]),
        sorted(new_ids.values()) or "none"))


def ini_value(c, key, value):
    """One line of characters.ini: characters Latin-1 has (the game's
    strings are Latin-1; the file itself is UTF-8), one
    line, no ';' (the reader takes the rest of the line for a comment)."""
    value = str(value)
    try:
        raw = value.encode("latin-1")
    except UnicodeEncodeError:
        raise SystemExit("%s: %s has characters outside Latin-1" % (c["name"], key))
    if ";" in value or "\n" in value or len(key) + 3 + len(raw) > INI_LINE \
            or (key.startswith("bio") and len(raw) > BIO_MAX):
        raise SystemExit("%s: %s must be one line, without ';', of at most %d bytes"
                         % (c["name"], key, BIO_MAX if key.startswith("bio") else INI_LINE))
    return "%s = %s" % (key, value)


def characters_ini(recipe):
    """ts2/characters.ini for the recipe's characters, as
    src/recomp_manual.c (ts2_chars_read) reads it."""
    out = ["; TimeSplitters 2 (PAL), split2-recomp: the characters this mod adds,",
           "; one [section] each, read at start-up from <mod>/ts2/characters.ini.",
           "; Written by tools/ts2kitbash.py; docs/formats/roster.md has the keys.",
           ";",
           "; slot = next takes the next free spare roster slot (127-158); a",
           "; number 0-126 replaces the character in that slot."]
    for c in recipe["characters"]:
        chr_id = c.get("chr_id", int(c["slot"][3:]) - 1)
        if c["slot"] != "chr%02d" % (chr_id + 1):
            raise SystemExit("%s: slot %s is not chr id %d's files (chr%02d)"
                             % (c["name"], c["slot"], chr_id, chr_id + 1))
        roster = c.get("roster", "next")
        if roster != "next" and (not isinstance(roster, int) or roster < 0):
            raise SystemExit("%s: roster must be \"next\" or a slot number" % c["name"])
        if c.get("background") and c["background"] not in SETS:
            raise SystemExit("%s: background must be one of %s" % (c["name"], ", ".join(SETS)))
        if c.get("unlock", "start") not in ("start", "never", "keep"):
            raise SystemExit("%s: unlock must be start, never or keep" % c["name"])
        out += ["", "[%s]" % c["name"],
                ini_value(c, "slot", roster),
                ini_value(c, "chr", chr_id),
                ini_value(c, "name", c["name"])]
        out += [ini_value(c, "name." + l, c["names"][l]) for l in LANGS if l in c.get("names", {})]
        if c.get("bio"):
            out.append(ini_value(c, "bio", c["bio"]))
        out += [ini_value(c, "bio." + l, c["bios"][l]) for l in LANGS if l in c.get("bios", {})]
        out.append(ini_value(c, "portrait", "textures/misc/chrimage_%s.xbt" % c["slot"]))
        if c.get("background"):
            out.append(ini_value(c, "background", c["background"]))
        out.append(ini_value(c, "unlock", c.get("unlock", "start")))
        for key in ("stats", "sounds"):
            if key in c:
                out.append(ini_value(c, key, int(c[key])))
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("recipe")
    ap.add_argument("data", help="the disc's data folder (game/data)")
    ap.add_argument("work", help="scratch folder (unpacked paks, intermediates)")
    ap.add_argument("out", help="the mod folder to write (loose files: a ts2mod source)")
    ap.add_argument("--blender", default=BLENDER)
    a = ap.parse_args()

    recipe = json.load(open(a.recipe))
    ctx_recipe_dir = os.path.dirname(os.path.abspath(a.recipe))
    slots = [c["slot"] for c in recipe["characters"]]
    if len(set(slots)) != len(slots):
        raise SystemExit("two characters in one slot")
    ini = characters_ini(recipe)          # checked before anything is built
    ctx = {"work": a.work, "out": a.out, "blender": a.blender, "recipe_dir": ctx_recipe_dir,
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

    ctx["new_textures"] = {}
    for c in recipe["characters"]:
        build_character(c, ctx)
    with open(os.path.join(a.out, "characters.json"), "w") as f:
        json.dump(recipe, f, indent=1)
    os.makedirs(os.path.join(a.out, "ts2"), exist_ok=True)
    # UTF-8, which the game's reader turns into its Latin-1 strings
    # (ts2_to_latin1); ini_value has checked every value fits Latin-1.
    with open(os.path.join(a.out, "ts2", "characters.ini"), "w", encoding="utf-8") as f:
        f.write(ini)
    ts2mod.write_manifest(a.out, {"made_by": "ts2kitbash", "characters": [c["name"] for c in recipe["characters"]]})
    print("%d characters written to %s, a mod: RECOMP_MODS=%s" % (len(recipe["characters"]), a.out, a.out))


if __name__ == "__main__":
    main()
