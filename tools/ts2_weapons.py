"""
TimeSplitters 2 (PAL) weapon definitions, read from your own default.xbe.

    py -3 -m tools.ts2_weapons game/default.xbe            the table
    py -3 -m tools.ts2_weapons game/default.xbe --json w.json

Two tables in the XBE's .data (found 6 Oct 2026; src/ts2/ts2_types.h):

  definitions  0x002C3888, 36 records of 0x240 bytes, indexed by the id in
               the player's current-weapon field (player +0x438). The
               reload reads the clip from here; patching it changes the game.
  types        0x002CA5F0, 42 records of 72 bytes, indexed by the weapon
               type a pickup carries. Word 0 is the name's string number in
               the language's string table (English: 0x00336308), which is
               how the pickup message "Got the <name>" is made.

A definition's first word is its type record's second word minus one (the
mines, TNT and the Brick: the type's third word minus two, or equal), which
is how each definition gets its name here. Fields not listed are not known;
those marked "likely" have the right shape on every weapon but have not been
tested by a patch.
"""

import argparse
import json
import struct
import sys

DEF_TABLE, DEF_COUNT, DEF_SIZE = 0x002C3888, 36, 0x240
TYPE_TABLE, TYPE_COUNT, TYPE_SIZE = 0x002CA5F0, 42, 72
STRINGS_EN = 0x00336308

FIELDS = [  # (offset, type, name, status)
    (0x10, "i32", "ammo_type", "known"),
    (0x14, "i32", "clip", "known"),
    (0x18, "i32", "ammo2_type", "known"),
    (0x1C, "i32", "clip2", "known"),
    (0x54, "f32", "zoom_fov", "likely"),
    (0x58, "f32", "unknown_58", "unknown"),
    (0x5C, "f32", "zoom_fov_max", "likely"),
    (0x78, "f32", "spawn_78", "unknown"),
    (0x7C, "f32", "power", "known"),
    (0x12C, "f32", "power2", "likely"),
]
# Status: "known" -- read by the code that uses it and confirmed by a patch
# (+0x7C, "power": raising the Soviet S47's from 2 to 20 made its hits on
# the player take 4.0 health instead of 0.6, 6 Oct 2026 -- not ten times, so
# the game scales it on the way, and sub_00029DD0 also reads it when it
# spawns the projectile, so it may set speed as well); "likely" --
# the right shape on every weapon, not traced (+0x54/+0x5C: 17/4 on the
# Sniper Rifle, 10/4 on the Vintage Rifle, 60/60 on weapons without a
# scope); "unknown". Two fire-mode blocks of 0xB0 bytes, primary at +0x60
# and secondary at +0x110: +0x78/+0x7C are the primary's +0x18/+0x1C, and
# +0x12C is the secondary's power.


class Xbe:
    def __init__(self, data):
        if data[:4] != b"XBEH":
            raise ValueError("not an XBE")
        self.d = data
        base = struct.unpack_from("<I", data, 0x104)[0]
        count, table = struct.unpack_from("<II", data, 0x11C)
        self.secs = []
        for i in range(count):
            _, va, _, raw, size, _ = struct.unpack_from("<6I", data, table - base + i * 56)
            self.secs.append((va, raw, size))

    def off(self, va):
        for v, raw, size in self.secs:
            if v <= va < v + size:
                return raw + va - v
        raise ValueError(f"0x{va:08X} is not in the file")

    def i32(self, va):
        return struct.unpack_from("<i", self.d, self.off(va))[0]

    def u32(self, va):
        return struct.unpack_from("<I", self.d, self.off(va))[0]

    def f32(self, va):
        return struct.unpack_from("<f", self.d, self.off(va))[0]

    def cstr(self, va):
        o = self.off(va)
        return self.d[o:self.d.index(b"\0", o)].decode("latin-1")


def type_names(x):
    names = {}
    for t in range(TYPE_COUNT):
        r = TYPE_TABLE + t * TYPE_SIZE
        try:
            name = x.cstr(x.u32(STRINGS_EN + 4 * x.i32(r)))
        except ValueError:
            continue
        names[t] = (name, x.i32(r + 4), x.i32(r + 8))
    return names


def read_weapons(x):
    types = type_names(x)
    out = []
    for w in range(DEF_COUNT):
        r = DEF_TABLE + w * DEF_SIZE
        key = x.i32(r)
        match = [n for t, (n, k1, k2) in sorted(types.items())
                 if key != -1 and (k1 == key + 1 or k2 == key + 2 or k2 == key)]
        rec = {"id": w, "address": f"0x{r:08X}", "name": match[0] if match else None}
        for off, kind, name, status in FIELDS:
            v = x.i32(r + off) if kind == "i32" else round(x.f32(r + off), 4)
            rec[name] = {"value": v, "address": f"0x{r + off:08X}", "type": kind,
                         "status": status}
        out.append(rec)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ts2_weapons", description=__doc__.split("\n\n")[0])
    ap.add_argument("xbe", help="the PAL default.xbe")
    ap.add_argument("--json", help="write the table as JSON")
    args = ap.parse_args(argv)
    try:
        x = Xbe(open(args.xbe, "rb").read())
        weapons = read_weapons(x)
    except (OSError, ValueError, struct.error) as exc:
        print(f"ts2_weapons: {exc}", file=sys.stderr)
        return 1
    if args.json:
        json.dump(weapons, open(args.json, "w"), indent=1)
        print(f"{len(weapons)} definitions -> {args.json}")
        return 0
    cols = [f for f in FIELDS]
    print(f"{'id':>2} {'name':22} " + " ".join(f"{n:>12}" for _, _, n, _ in cols))
    for w in weapons:
        vals = " ".join(f"{w[n]['value']:>12}" if isinstance(w[n]['value'], int)
                        else f"{w[n]['value']:>12.4g}" for _, _, n, _ in cols)
        print(f"{w['id']:>2} {(w['name'] or '-')[:22]:22} {vals}")
    print("\nA field's address is the definition's address plus its offset; "
          "--json lists each one. Patch with mods/patches (docs/modding.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
