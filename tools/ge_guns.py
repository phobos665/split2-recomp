"""
GoldenEye 007 (N64) guns, out of your own cartridge: the models as OBJ with
their textures, the sounds as WAV, and a preview of each. The first step of
the GoldenEye gun mod (docs/goldeneye-guns.md); nothing it writes may be
committed or shared, which is why it writes under extracted/ (ignored).

    py -3 -m tools.ge_guns "n64/007 - GoldenEye (Europe).n64" --list
    py -3 -m tools.ge_guns "n64/007 - GoldenEye (Europe).n64"
    py -3 -m tools.ge_guns ROM --gun kf7 --gun pp7 --hands --preview

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
                return {"ammo_type": ammo, "magazine": mag, "automatic_rate": auto, "single_rate": single,
                        "fire_sound": sound}
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
    a = ap.parse_args(argv)
    try:
        if a.list:
            return list_guns(a.rom)
        return run(a.rom, a.out, a.gun or list(GUNS), a.hands, a.flash, a.preview)
    except (OSError, ValueError, KeyError) as e:
        print(f"ge_guns: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
