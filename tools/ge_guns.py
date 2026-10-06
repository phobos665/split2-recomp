"""
GoldenEye 007 (N64) guns, out of your own cartridge: the models as OBJ with
their textures, the sounds as WAV, and a preview of each. The first step of
the GoldenEye gun mod (docs/goldeneye-guns.md); nothing it writes may be
committed or shared, which is why it writes under extracted/ (ignored).

    py -3 -m tools.ge_guns "n64/007 - GoldenEye (Europe).n64" --list
    py -3 -m tools.ge_guns "n64/007 - GoldenEye (Europe).n64"
    py -3 -m tools.ge_guns ROM --gun kf7 --gun pp7 --hands --preview
    py -3 -m tools.ge_guns ROM --ts2-sounds game --mods build/Release/mods

Each gun gets a folder:

    first_person.obj/.mtl   the model the player holds (no hand by default:
                            the pistols carry Bond's; --hands keeps it)
    pickup.obj/.mtl         the model lying in the world
    *.png                   their textures, mirrored ones baked in
    fire.wav                the firing sound (and any sound it chains to)
    preview_*.png           with --preview: both models, from the side
    gun.json                magazine, sound numbers, the parts and their joints

and the shared sounds (reload, empty click, shell) go in sounds/. Works on
the PAL cartridge (checked 6 Oct 2026); the other releases should work, as
nothing here is an address, but have not been tried.
"""

import argparse
import json
import os
import struct
import sys

from tools import xbs, xbr
from tools.ts2pak import create_p8ck, read_pak
from tools.xbt import swizzle

from tools.ge_model import Model, materials, material_name, mirrored, render, write_obj
from tools.ge_rom import Rom
from tools.ge_sound import Bank, mix_chain, write_wav
from tools.png import write_png

# The guns this mod brings over, by a short name, with the first-person and
# pickup files and the TimeSplitters 2 weapon each is meant to replace.
GUNS = {
    "pp7": ("GwppksilZ", "PchrwppksilZ", "Silenced Pistol"),
    "kf7": ("Gak47Z", "PchrkalashZ", "Soviet S47"),
    "d5k": ("Gmp5kZ", "Pchrmp5kZ", "SBP90"),
    "shotgun": ("GshotgunZ", "PchrshotgunZ", "Shotgun"),
    "sniper": ("GsniperrifleZ", "PchrsniperrifleZ", "Sniper Rifle"),
    "magnum": ("GrugerZ", "PchrrugerZ", "Garrett Revolver"),
    "rocket": ("GrocketlaunchZ", "PchrrocketlaunchZ", "Rocket Launcher"),
}

# The TimeSplitters 2 sound each gun's shot replaces: the sample its
# weapon's fire sound plays (definition +0x98 names an SFX_ entry in
# sound/sounddata, whose first word is the sample's number; 6 Oct 2026).
# Two are shared, so their other users change too: the S47's sample is
# also the Tactical 12-Gauge's, the rocket's also the Homing Launcher's.
TS2_FIRE_SOUNDS = {
    "pp7": "sfx/gun_silenced22.xbs",               # SFX_GUN_SILENCED_PISTOL (and the Silenced Luger)
    "kf7": "sfx/gun_m16_04_withbullet22.xbs",      # SFX_GUN18 (and SFX_GUNASSAULT)
    "d5k": "sfx/gun_uzi_withbullet22_01d.xbs",     # SFX_GUN_UZI
    "shotgun": "sfx/gun_dr08c_22.xbs",             # SFX_DRGUN3
    "sniper": "sfx/gun_sniperrifle_nu44_03b.xbs",  # SFX_GUNSNIPERRIFLE2, 44.1 kHz
    "magnum": "sfx/gun_walther_colt22_02.xbs",     # SFX_GUNCOLT
    "rocket": "sfx/gun_rocketlauncher22.xbs",      # SFX_GUNROCKET03 (and the Homing Launcher)
}

# The TimeSplitters 2 models each gun replaces: ob/guns/<name>_ph.xbr is the
# first-person model, <name>_cl.xbr the one in the world (on the ground and
# in other characters' hands) -- found by swapping them, 6 Oct 2026. Only the
# sniper rifle's and the silenced pistol's are confirmed in the game; the
# others are the gun.pak models that look like the weapon.
TS2_MODELS = {
    "pp7": "silencedpistol",
    "kf7": "ak47",
    "d5k": "uzi",
    "shotgun": "doublebarrelshotgun",
    "sniper": "sniperrifle",
    "magnum": "magnum",
    "rocket": "rocketlauncher",
}
# New texture numbers for the GoldenEye textures, past any the disc uses.
FIRST_TEXTURE = 9000

# Sounds every gun shares, by the game's sound number.
SHARED_SOUNDS = {"reload_rifle_cock": 50, "empty_click": 89, "shell_case": 90, "rocket_launch": 1}


def weapon_stats(rom, gun_file):
    """The game's weapon stats for a first-person gun file, found through
    the gun's own record: (header, file name, no-model flag, stats, ...)
    -- the stats' fields are named in the decompilation's gun.h."""
    seg, base = rom.seg, rom.name_base
    at = 0
    while True:
        at = seg.find(gun_file.encode() + b"\0", at)
        if at < 0:
            return None
        if seg[at - 1] == 0:
            break
        at += 1
    want = struct.pack(">I", base + at)
    o = seg.find(want)
    while o >= 0:
        if o % 4 == 0 and o >= 4:
            stats = struct.unpack_from(">I", seg, o + 8)[0] - base
            if 0 <= stats < len(seg) - 0x70:
                ammo, mag, auto, single, through, trigger, sound = struct.unpack_from(">ihBbBBH", seg, stats + 0x1C)
                pos = struct.unpack_from(">3f", seg, stats + 4)
                return {"ammo_type": ammo, "magazine": mag, "automatic_rate": auto, "single_rate": single,
                        "fire_sound": sound, "position": [round(v, 3) for v in pos]}
        o = seg.find(want, o + 1)
    return None


class Textures:
    def __init__(self, rom):
        self.rom, self.cache = rom, {}

    def get(self, num):
        if num not in self.cache:
            self.cache[num] = self.rom.texture(num)
        return self.cache[num]

    def size(self, num):
        return self.get(num)[:2]

    def image(self, tex):
        num, ms, mt = tex
        return mirrored(*self.get(num), ms, mt)


def export_model(rom, tex, file_name, out_dir, stem, kinds):
    model = Model(rom.file(file_name), texture_size=tex.size)
    parts = [p for p in model.parts if p.kind in kinds]
    write_obj(os.path.join(out_dir, stem + ".obj"), parts, name=file_name)
    for t in materials(parts):
        w, h, rgba = tex.image(t)
        write_png(os.path.join(out_dir, material_name(t) + ".png"), w, h, rgba)
    return model, parts


def run(rom_path, out, names, hands=False, flash=False, preview=False, log=print):
    rom = Rom.open(rom_path)
    bank = Bank.find(rom)
    tex = Textures(rom)
    kinds = {"gun"} | ({"hand"} if hands else set()) | ({"flash"} if flash else set())
    os.makedirs(out, exist_ok=True)
    rate = bank.rate
    for key in names:
        fp, pickup, ts2 = GUNS[key]
        d = os.path.join(out, key)
        os.makedirs(d, exist_ok=True)
        fpm, fparts = export_model(rom, tex, fp, d, "first_person", kinds)
        pkm, pparts = export_model(rom, tex, pickup, d, "pickup", {"gun", "hand", "flash"})
        stats = weapon_stats(rom, fp) or {}
        snd = stats.get("fire_sound") or (SHARED_SOUNDS["rocket_launch"] if key == "rocket" else 0)
        chain = bank.chain(snd)
        if chain:
            write_wav(os.path.join(d, "fire.wav"), rate, mix_chain(chain, rate))
        if preview:
            for stem, parts in (("first_person", fparts), ("pickup", pparts)):
                w, h, px = render(parts, 512, image=tex.image, view="auto")
                write_png(os.path.join(d, f"preview_{stem}.png"), w, h, px, 3)
        info = {
            "goldeneye_files": {"first_person": fp, "pickup": pickup},
            "replaces": ts2,
            "weapon_stats": stats,
            "fire_sound_chain": [{"sound": s.num, "start_ms": at, "rate": s.rate} for s, at in chain],
            "first_person_parts": [{"node": f"0x{p.node:04X}", "joint": p.joint, "kind": p.kind,
                                    "secondary": p.secondary, "triangles": len(p.tris),
                                    "textures": [f"0x{t:03X}" for t in p.textures]} for p in fpm.parts],
            "triangles": {"first_person": sum(len(p.tris) for p in fparts),
                          "pickup": sum(len(p.tris) for p in pparts)},
        }
        with open(os.path.join(d, "gun.json"), "w", newline="\n") as f:
            json.dump(info, f, indent=1)
        log(f"{key:8} {fp:15} {info['triangles']['first_person']:4} + {pickup:18} {info['triangles']['pickup']:3} "
            f"triangles, magazine {stats.get('magazine')}, fire sound {[c['sound'] for c in info['fire_sound_chain']]} "
            f"-> {ts2}")
    sd = os.path.join(out, "sounds")
    os.makedirs(sd, exist_ok=True)
    for name, num in SHARED_SOUNDS.items():
        write_wav(os.path.join(sd, name + ".wav"), rate, mix_chain(bank.chain(num), rate))
    with open(os.path.join(out, "README.txt"), "w", newline="\n") as f:
        f.write("Extracted from your own GoldenEye 007 cartridge by tools.ge_guns.\n"
                "These files are the game's: keep them on this machine; do not commit or share them.\n")
    return 0


def build_ts2_sounds(rom_path, game_dir, mods_dir, names, log=print):
    """mods/data/xbsound.pak: each gun's GoldenEye shot in place of the
    TimeSplitters 2 sample its weapon fires, at that sample's own rate (the
    game plays a sample at the rate its definition says, not the file's).
    One file replaces the sound in every level: the game searches
    xbsound.pak first (src/overrides/archives.c), and the level archives
    carry their own copies under the same names."""
    rom = Rom.open(rom_path)
    bank = Bank.find(rom)
    disc = read_pak(open(os.path.join(game_dir, "data", "sounds.pak"), "rb").read())
    by_name = {e.name: e for e in disc.entries}
    files = []
    for key in names:
        target = TS2_FIRE_SOUNDS[key]
        rate, _ = xbs.parse(disc.read(by_name[target]))
        fp = GUNS[key][0]
        snd = (weapon_stats(rom, fp) or {}).get("fire_sound") or (SHARED_SOUNDS["rocket_launch"] if key == "rocket" else 0)
        pcm = mix_chain(bank.chain(snd), bank.rate)
        data = xbs.encode(xbs.resample(pcm, bank.rate, rate), rate)
        files.append((target, data))
        log(f"{key:8} GoldenEye sound {snd:3} -> {target} ({rate} Hz, {len(pcm) / bank.rate:.2f} s)")
    out = os.path.join(mods_dir, "data")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "xbsound.pak")
    with open(path, "wb") as f:
        f.write(create_p8ck(files))
    log(f"wrote {path} ({len(files)} sounds)")
    return 0


def xbt_argb(w, h, rgba, template):
    """A one-level A8R8G8B8 (format 2, swizzled) .xbt; the header words
    nobody understands are the template's."""
    head = bytearray(template[:0x80])
    struct.pack_into("<6I", head, 0, w, h, w, h, 0, 2)
    bgra = bytearray(len(rgba))
    bgra[0::4], bgra[1::4], bgra[2::4], bgra[3::4] = rgba[2::4], rgba[1::4], rgba[0::4], rgba[3::4]
    return bytes(head) + swizzle(bytes(bgra), w, h, 4)


# Which way the barrels point. GoldenEye's first-person guns along +z (the
# muzzle flashes sit there), its pickups along -x (every one of the seven);
# TimeSplitters 2's along +z, away from the camera in first person.
GE_BARREL = {"_ph": (2, 1), "_cl": (0, -1)}
TS2_BARREL = (2, 1)

# First person: one transform for every gun, as GoldenEye has. GoldenEye
# draws all its first-person models at one scale and moves each by the
# position in its weapon stats (x is about 11 on all seven, y and z vary:
# the sniper rifle is held further back than the KF7). Here a model vertex
# v goes to FP_SCALE * v + FP_POS_SCALE * (0, pos.y, pos.z) + FP_OFFSET.
# Measured on 6 Oct 2026 from the two placements that looked right in the
# game -- the KF7 fitted to the S47's box, and the sniper rifle 0.35 behind
# its box -- which the two constants reproduce to within 0.015.
FP_SCALE = 1.85e-3
FP_POS_SCALE = 3.26e-3
FP_OFFSET = (-0.034, 0.1465, -0.0047)


def _first_person(stats):
    py, pz = stats["position"][1], stats["position"][2]

    def apply(x, y, z):
        return (FP_SCALE * x + FP_OFFSET[0],
                FP_SCALE * y + FP_POS_SCALE * py + FP_OFFSET[1],
                FP_SCALE * z + FP_POS_SCALE * pz + FP_OFFSET[2])
    return apply


def _fit(src_points, dst_points, src_barrel, dst_barrel, mirror_x):
    """A rotation about y, a scale and an offset that lay the source gun on
    the destination: barrels along the same axis and the same way, the same
    length, centred on all three axes. No mirroring unless asked."""
    def box(pts):
        return ([min(p[k] for p in pts) for k in range(3)], [max(p[k] for p in pts) for k in range(3)])
    slo, shi = box(src_points)
    dlo, dhi = box(dst_points)
    (sl, ss), (dl, ds) = src_barrel, dst_barrel
    s = (dhi[dl] - dlo[dl]) / ((shi[sl] - slo[sl]) or 1)
    sign = ss * ds
    sc = [(slo[k] + shi[k]) / 2 for k in range(3)]
    dc = [(dlo[k] + dhi[k]) / 2 for k in range(3)]
    st, dt = 2 - sl, 2 - dl                     # the other horizontal axes
    # Across the barrel, the sign that keeps it a rotation (y stays up).
    cross = sign if sl == dl else -sign
    if mirror_x:
        cross = -cross

    def apply(x, y, z):
        v = (x - sc[0], y - sc[1], z - sc[2])
        out = [0.0, 0.0, 0.0]
        out[dl] = v[sl] * s * sign
        out[dt] = v[st] * s * cross
        out[1] = v[1] * s
        return (dc[0] + out[0], dc[1] + out[1], dc[2] + out[2])
    return apply


# Every vertex gets the same normal. GoldenEye never lit its guns -- the
# shading is in the vertex colours, now in the textures -- and lighting the
# low-poly models by face normals left patches and inward-facing triangles
# dark. One normal lights the whole gun evenly, as GoldenEye showed it.
GUN_NORMAL = (0.0, 1.0, 0.0)


def _tint_key(tri):
    """The colour a triangle's vertex colours give its texture: their
    average, rounded to steps of 8 so near-equal ones share a texture;
    white for lit (chrome) parts, whose bytes are normals, not colour."""
    if tri[0][9]:
        return (255, 255, 255)
    return tuple(min(255, int(round(sum(v[k] for v in tri) / 3 / 8)) * 8) for k in (5, 6, 7))


def tinted(w, h, rgba, tint):
    """The texture multiplied by a colour, as the N64 does with vertex colour."""
    if tint == (255, 255, 255):
        return w, h, rgba
    out = bytearray(rgba)
    for k in range(3):
        out[k::4] = bytes(c * tint[k] // 255 for c in rgba[k::4])
    return w, h, bytes(out)


def _groups(parts, place):
    """GoldenEye triangles in TS2's space, grouped by (material, tint): TS2
    draws its guns without vertex colour (position, normal and UV only), so
    each colour a GoldenEye material is painted with becomes its own tinted
    copy of the texture. Returns {(material, tint): [triangle, ...]}."""
    groups = {}
    for p in parts:
        for tex, tri in p.tris:
            if tex is None:
                continue                        # untextured: none on these guns
            pts = [place(*v[:3]) for v in tri]
            vs = [(x, y, z, v[3], v[4], (127, 127, 127, 127), GUN_NORMAL) for (x, y, z), v in zip(pts, tri)]
            groups.setdefault((tex, _tint_key(tri)), []).append(vs)
    return groups


def build_ts2_models(rom_path, game_dir, mods_dir, names, mirror_x=False, log=print):
    """mods/data/xbob.pak with each gun's GoldenEye models in place of its
    TimeSplitters 2 ones (_ph first person, _cl in the world), and
    mods/data/xbt.pak with their textures as new texture numbers. Each
    GoldenEye model is scaled to the length of the TS2 model it replaces
    and centred on it."""
    rom = Rom.open(rom_path)
    tex = Textures(rom)
    guns = read_pak(open(os.path.join(game_dir, "data", "gun.pak"), "rb").read())
    by_name = {e.name: e for e in guns.entries}
    template = next(guns.read(e) for e in guns.entries
                    if e.name.endswith(".xbt") and struct.unpack_from("<I", guns.read(e), 0x14)[0] == 2)
    numbers, textures, models = {}, [], []
    for key in names:
        fp, pickup, _ = GUNS[key]
        for ge_file, kinds, suffix in ((fp, {"gun"}, "_ph"), (pickup, {"gun", "hand", "flash"}, "_cl")):
            target = f"ob/guns/{TS2_MODELS[key]}{suffix}.xbr"
            original = guns.read(by_name[target])
            ts2 = xbr.Model(original)
            model = Model(rom.file(ge_file), texture_size=tex.size)
            parts = [p for p in model.parts if p.kind in kinds]
            if suffix == "_ph":
                place = _first_person(weapon_stats(rom, fp))
            else:
                place = _fit([v[:3] for p in parts for _, t in p.tris for v in t], ts2.positions(0),
                             GE_BARREL[suffix], TS2_BARREL, mirror_x)
            by_key = _groups(parts, place)
            used = sorted(by_key)
            for k in used:
                if k not in numbers:
                    numbers[k] = FIRST_TEXTURE + len(numbers)
                    w, h, rgba = tinted(*tex.image(k[0]), k[1])
                    textures.append((f"textures/{numbers[k]:04d}.xbt", xbt_argb(w, h, rgba, template)))
            groups = [(i, by_key[k]) for i, k in enumerate(used)]
            data = xbr.replace_geometry(original, [numbers[k] for k in used], groups)
            models.append((target, data))
            log(f"{key:8} {ge_file:18} -> {target:34} {sum(len(t) for t in by_key.values()):4} triangles, "
                f"{len(used)} textures (with their vertex colours)")
    out = os.path.join(mods_dir, "data")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "xbob.pak"), "wb") as f:
        f.write(create_p8ck(models))
    with open(os.path.join(out, "xbt.pak"), "wb") as f:
        f.write(create_p8ck(textures))
    log(f"wrote {out}\\xbob.pak ({len(models)} models) and xbt.pak ({len(textures)} textures)")
    return 0


def list_guns(rom_path, log=print):
    rom = Rom.open(rom_path)
    for key, (fp, pickup, ts2) in GUNS.items():
        s = weapon_stats(rom, fp) or {}
        log(f"{key:8} {fp:15} {pickup:18} magazine {s.get('magazine')!s:3} fire sound {s.get('fire_sound')!s:4} -> {ts2}")
    others = sorted(n for n, (off, size) in rom.files.items() if n.startswith("G") and n.endswith("Z") and size > 1000
                    and n not in {g[0] for g in GUNS.values()})
    log(f"\nother first-person models in the ROM ({len(others)}): " + " ".join(others))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("rom", help="your GoldenEye 007 ROM (.z64, .v64 or .n64)")
    ap.add_argument("--out", default=os.path.join("extracted", "goldeneye"))
    ap.add_argument("--gun", action="append", choices=sorted(GUNS), help="one gun (repeatable); default all")
    ap.add_argument("--hands", action="store_true", help="keep Bond's hand on the pistols")
    ap.add_argument("--flash", action="store_true", help="keep the muzzle flash squares")
    ap.add_argument("--preview", action="store_true", help="also draw each model to a PNG")
    ap.add_argument("--list", action="store_true", help="list the guns and stop")
    ap.add_argument("--ts2-sounds", metavar="GAME_DIR",
                    help="instead: write the guns' shots into MODS/data/xbsound.pak, replacing TS2's (GAME_DIR holds data/sounds.pak)")
    ap.add_argument("--ts2-models", metavar="GAME_DIR",
                    help="instead: write the guns' models into MODS/data/xbob.pak and their textures into xbt.pak")
    ap.add_argument("--mirror-x", action="store_true", help="with --ts2-models: mirror left and right")
    ap.add_argument("--mods", default="mods", help="the mods folder for --ts2-sounds/--ts2-models (default: mods)")
    a = ap.parse_args(argv)
    try:
        if a.list:
            return list_guns(a.rom)
        if a.ts2_models:
            return build_ts2_models(a.rom, a.ts2_models, a.mods, a.gun or list(GUNS), a.mirror_x)
        if a.ts2_sounds:
            return build_ts2_sounds(a.rom, a.ts2_sounds, a.mods, a.gun or list(GUNS))
        return run(a.rom, a.out, a.gun or list(GUNS), a.hands, a.flash, a.preview)
    except (OSError, ValueError, KeyError) as e:
        print(f"ge_guns: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
