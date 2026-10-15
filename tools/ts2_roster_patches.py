"""Write config/pal/xbe_patches.json: TimeSplitters 2 (PAL) with a roster
that has room for characters a mod adds, instead of characters it replaces.

    python3 tools/ts2_roster_patches.py game/default.xbe config/pal/xbe_patches.json [--spare 32]

(with capstone, as scripts/build.py needs), then scripts/build.py --relift.

The roster (127 entries of 0x20 at 0x002BAC60), the unlock snapshot beside
it (127 dwords at 0x0035C2D8, BSS) and the texture list that holds the
portraits (548 entries of 0x10 at 0x002BF7B0) are fixed-size tables in
.data with their counts written into the code. This moves the three into a
section added after the image, with SPARE more entries in each, and repoints
every instruction that names them (xboxrecomp docs/technical/xbe-patches.md,
the file format; docs/formats/roster.md, "Room for more characters", the
sites and why each one changes).

Every site below was found by scanning the PAL disassembly for operands
inside each table (and at its end), and every byte of .text for the tables'
addresses; each one's old bytes are checked here against the XBE given, and
again by tools.xbe_patch when the file is applied.

The spare entries are hidden: unlock kind 0, which every screen that lists
characters skips (sub_001AEE50 returns 0 before anything else), and each
one's texture list entry has load flags 0, which no level loads. So without
a mod the game shows, counts and loads what it did before.
"""

import argparse
import hashlib
import json
import os
import struct
import sys

import capstone
from capstone import x86

PAL_SHA1 = "2809eb147385723eaa90c425be89ee4db033fc5a"

ROSTER, ROSTER_N, ENTRY = 0x002BAC60, 127, 0x20
SNAP = 0x0035C2D8
TEX, TEX_N, TEX_ENTRY = 0x002BF7B0, 548, 0x10
TEX_END = TEX + TEX_N * TEX_ENTRY                       # 0x002C19F0, another table
SECTION_VA = 0x004CE000                                 # page after dsstdfx, the last section
CONSULTANT = 126                                        # the disc's one hidden entry
PED3_PATH = 0x00223260                                  # "host0:textures/misc/chrimage_ped3.raw"

# Instructions naming the roster: (instruction, function, what it does there).
ROSTER_SITES = [
    (0x00087A96, "sub_00087A90", "unlock rule by chr id: where its search starts"),
    (0x00087AB8, "sub_00087A90", "unlock rule by chr id: the entry it found"),
    (0x00087AD6, "sub_00087AD0", "portrait by chr id (HUD, scoreboard, 18 callers): search start"),
    (0x00087AF4, "sub_00087AD0", "portrait by chr id: the found entry's +4"),
    (0x00087C24, "sub_00087C20", "n-th unlocked character: counts the shown entries (+0xC)"),
    (0x00087C49, "sub_00087C20", "n-th unlocked character: walks the entries"),
    (0x00087C54, "sub_00087C20", "n-th unlocked character: counts the shown entries again"),
    (0x00087C8D, "sub_00087C20", "n-th unlocked character: the chr id it returns"),
    (0x00087CB0, "sub_00087CA0", "count of unlocked characters"),
    (0x0008D078, "sub_0008CED0", "bot set: a chosen bot's chr id, by the list item's roster index"),
    (0x0008E1FC, "sub_0008DEE0", "the Available Bots list: walks the entries"),
    (0x0008FB5C, "sub_0008FAE0", "Select Character item: finds its portrait by chr id"),
    (0x0008FC31, "sub_0008FAE0", "Select Character item: the entry it found"),
    (0x00095304, "sub_000952C0", "unlock snapshot: each entry's chr id"),
    (0x000954BD, "sub_000954B0", "new-unlock announcement: walks the entries"),
    (0x00098E24, "sub_00098E00", "Gallery: the selected character's chr id"),
    (0x00098E4D, "sub_00098E00", "Gallery: the selected character's portrait"),
    (0x00098F50, "sub_00098F40", "Gallery grid: counts the shown entries"),
    (0x00098F80, "sub_00098F40", "Gallery grid: each cell's portrait (+4)"),
    (0x00099460, "sub_00099430", "Gallery cursor: counts the shown entries"),
    (0x00099712, "sub_00099430", "Gallery cursor: the selected chr id"),
    (0x0009984B, "sub_00099430", "Gallery cursor: the description's text id (625 + chr id)"),
    (0x000999CB, "sub_00099960", "Gallery build: entry 0's name"),
    (0x0009CCCB, "sub_0009CC00", "profile icon: finds the profile's character by chr id"),
    (0x0009CD26, "sub_0009CC00", "profile icon: the entry it found"),
    (0x000A3CB0, "sub_000A3C60", "the Select Character list: walks the entries"),
]
SNAP_SITES = [
    (0x000952FD, "sub_000952C0", "unlock snapshot: where it writes"),
    (0x000954CC, "sub_000954B0", "new-unlock announcement: the snapshot it compares with"),
]
# 127 * 0x20 as the end of a byte-offset loop over the entries (imm32).
ROSTER_BYTES_SITES = [
    (0x00087C32, "sub_00087C20", "n-th unlocked character: shown-entry count loop"),
    (0x00087C62, "sub_00087C20", "n-th unlocked character: the same count, again"),
    (0x00087CC7, "sub_00087CA0", "count of unlocked characters"),
    (0x0009531B, "sub_000952C0", "unlock snapshot: one dword per entry"),
    (0x00098F5E, "sub_00098F40", "Gallery grid: shown-entry count"),
    (0x0009946E, "sub_00099430", "Gallery cursor: shown-entry count"),
    (0x000A3D1C, "sub_000A3C60", "the Select Character list"),
]
SNAP_BYTES_SITES = [
    (0x00095504, "sub_000954B0", "new-unlock announcement: 127 * 4, the snapshot's size; "
                                 "not in roster.md's first list"),
]
# `cmp reg, 0x7F` / `jb`: a search by chr id, bounded by the count as a
# sign-extended imm8, which cannot hold more than 127. Each of these loops
# has just advanced a pointer to the next entry in ecx, so the bound becomes
# `cmp dword ptr [ecx], -1` (same length, same mnemonic): the search stops
# at an entry whose chr id is -1, the sentinel written after the last slot.
SENTINEL_SITES = [
    (0x00087AA8, "sub_00087A90", "unlock rule by chr id"),
    (0x00087AE8, "sub_00087AD0", "portrait by chr id"),
    (0x0008E28C, "sub_0008DEE0", "the Available Bots list"),
    (0x0009CCD8, "sub_0009CC00", "profile icon"),
]
# The fifth, sub_0008FAE0's at 0x0008FB6E, keeps its pointer in ebp, and
# `cmp dword ptr [ebp], -1` needs a disp8 (4 bytes, not 3), so it stays at
# 127 and src/recomp_manual.c (ts2_chars_item_draw) covers what it misses.

# The texture list: instructions inside it, and the two loop ends just past it.
TEX_SITES = [
    (0x000A9AE7, "sub_000A9AE0", "a texture's handle, by index (+0xC)"),
    (0x000A9AF7, "sub_000A9AE0", "a texture's path, by index (+8)"),
    (0x000A9C06, "sub_000A9BE0", "load by index: not loaded yet (+0xC == -2)"),
    (0x000A9C1F, "sub_000A9BE0", "load by index: how (+0)"),
    (0x000A9C27, "sub_000A9BE0", "load by index: handle"),
    (0x000A9C2F, "sub_000A9BE0", "load by index: path"),
    (0x000A9C44, "sub_000A9BE0", "load by index: path"),
    (0x000A9C64, "sub_000A9C60", "load a level's textures: walks the flags (+4)"),
    (0x000A9D29, "sub_000A9D20", "load the textures with given flags: walks the flags"),
    (0x000A9D5C, "sub_000A9D50", "look every handle up again: walks the handles"),
    (0x000A9D89, "sub_000A9D50", "a fixed texture's handle"),
    (0x000A9D8F, "sub_000A9D50", "a fixed texture's handle"),
    (0x000A9D94, "sub_000A9D50", "a fixed texture's handle"),
    (0x000A9DA0, "sub_000A9D50", "a fixed texture's handle"),
    (0x000A9DAB, "sub_000A9D50", "a fixed texture's handle"),
    (0x000A9DB6, "sub_000A9D50", "a fixed texture's handle"),
    (0x000A9E79, "sub_000A9E70", "a fixed texture's handle"),
    (0x000AA3A0, "sub_000AA3A0", "a fixed texture's handle"),
    (0x000AA480, "sub_000AA480", "a fixed texture's handle"),
    (0x000AA4D0, "sub_000AA4D0", "a fixed texture's handle"),
    (0x000AA520, "sub_000AA520", "a fixed texture's handle"),
    (0x000AA570, "sub_000AA570", "a fixed texture's handle"),
    (0x000AA9DA, "sub_000AA970", "a fixed texture's handle"),
    (0x000AAB2C, "sub_000AA970", "a fixed texture's handle"),
    (0x000AAB9D, "sub_000AA970", "a fixed texture's handle"),
    (0x000AAC9D, "sub_000AABF0", "a fixed texture's handle"),
    (0x000AAEFA, "sub_000AABF0", "a fixed texture's handle"),
    (0x000AAF9F, "sub_000AABF0", "a fixed texture's handle"),
    (0x000AB056, "sub_000AB000", "a fixed texture's handle"),
    (0x000AB2E0, "sub_000AB2E0", "a fixed texture's handle"),
    (0x000AB32E, "sub_000AB2E0", "a fixed texture's handle"),
    (0x000AB36A, "sub_000AB2E0", "a fixed texture's handle"),
    (0x000AB3AA, "sub_000AB2E0", "a fixed texture's handle"),
]
TEX_END_SITES = [
    (0x000A9C93, "sub_000A9C60", "load a level's textures: the end of the flags walk"),
    (0x000A9D41, "sub_000A9D20", "load the textures with given flags: the end"),
    (0x000A9D81, "sub_000A9D50", "look every handle up again: the end"),
]
TEX_COUNT_SITE = (0x000A9BEB, "sub_000A9BE0", "load by index refuses an index from 548 (0x224) up")
# The front end's menu items: 555 of 0x8C bytes (0x163 + 200), from a pool
# sub_000ED6F0 allocates per level. The Select Character screen makes a
# column per player, one item per unlocked character, so four players with
# every character unlocked take 4 * 127 of them already.
ITEM_POOL_SITE = (0x000ED737, "sub_000ED6F0", "front-end menu items: 0x163 + 200 (and eax, 0x163 "
                                              "after eax = -1 when the level is 101)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("xbe")
    ap.add_argument("out")
    ap.add_argument("--spare", type=int, default=32, help="roster slots to add (default 32)")
    a = ap.parse_args()

    data = open(a.xbe, "rb").read()
    if hashlib.sha1(data).hexdigest() != PAL_SHA1:
        sys.exit("not the PAL default.xbe these addresses are for")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xboxrecomp"))
    from tools.xbe_patch.patcher import Image
    img = Image(data)

    S = a.spare
    N = ROSTER_N + S
    T = TEX_N + S
    # The added section: roster (and the sentinel), snapshot, texture list.
    roster_new = SECTION_VA
    snap_new = SECTION_VA + ((N + 1) * ENTRY + 0x3FF & ~0x3FF)
    tex_new = snap_new + (N * 4 + 0x3FF & ~0x3FF)
    size = (tex_new + T * TEX_ENTRY - SECTION_VA + 0xFFF) & ~0xFFF
    off = lambda va: "TS2ROSTER+0x%X" % (va - SECTION_VA)

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True

    def insn_at(va):
        code = img.read(va, 16, "insn")
        i = next(md.disasm(code, va), None)
        if i is None:
            sys.exit("0x%08X: does not decode" % va)
        return i

    def field(i, old):
        """(va of the 4-byte field in instruction i holding old) -- its
        displacement or its imm32."""
        raw = bytes(i.bytes)
        k = raw.find(struct.pack("<I", old))
        if k < 0 or raw.find(struct.pack("<I", old), k + 1) >= 0:
            sys.exit("0x%08X %s %s: 0x%08X is not in it exactly once" % (i.address, i.mnemonic, i.op_str, old))
        return i.address + k

    ops = []

    def repoint(sites, lo, hi, new_of, what, entry=None):
        for va, fn, why in sites:
            i = insn_at(va)
            vals = [o.mem.disp & 0xFFFFFFFF for o in i.operands if o.type == x86.X86_OP_MEM] + \
                   [o.imm & 0xFFFFFFFF for o in i.operands if o.type == x86.X86_OP_IMM]
            hits = [v for v in vals if lo <= v < hi]
            if len(hits) != 1:
                sys.exit("0x%08X %s %s: expected one operand in %s" % (va, i.mnemonic, i.op_str, what))
            old = hits[0]
            new = new_of(old)
            if entry:
                why = "%s (entry %d +0x%X)" % (why, (old - lo) // entry, (old - lo) % entry)
            ops.append({"op": "patch", "va": "0x%08X" % field(i, old), "insn": "0x%08X" % va,
                        "old": struct.pack("<I", old).hex().upper(),
                        "new": struct.pack("<I", new).hex().upper(),
                        "why": "%s %s, %s: %s (0x%08X -> 0x%08X)" % (fn, i.mnemonic, i.op_str, why, old, new)})

    def immediate(site, old, new, why_more=""):
        va, fn, why = site
        i = insn_at(va)
        ops.append({"op": "patch", "va": "0x%08X" % field(i, old), "insn": "0x%08X" % va,
                    "old": struct.pack("<I", old).hex().upper(),
                    "new": struct.pack("<I", new).hex().upper(),
                    "why": "%s %s, %s: %s (0x%X -> 0x%X)%s" % (fn, i.mnemonic, i.op_str, why, old, new, why_more)})

    ops.append({"op": "add_section", "name": "TS2ROSTER", "size": "0x%X" % size, "va": "0x%08X" % SECTION_VA,
                "why": "the roster with %d spare slots (%d entries and a sentinel) at +0, its unlock "
                       "snapshot at +0x%X, the texture list with %d more entries at +0x%X"
                       % (S, N, snap_new - SECTION_VA, S, tex_new - SECTION_VA)})
    ops.append({"op": "copy", "from": "0x%08X" % ROSTER, "to": off(roster_new), "size": "0x%X" % (ROSTER_N * ENTRY),
                "why": "the disc's 127 roster entries, in their order"})
    consultant = img.read(ROSTER + CONSULTANT * ENTRY, ENTRY, "roster")
    spare = b""
    for j in range(S):
        e = bytearray(consultant)
        struct.pack_into("<I", e, 4, TEX_N + j)
        spare += bytes(e)
    ops.append({"op": "write", "va": off(roster_new + ROSTER_N * ENTRY),
                "bytes": " ".join(spare[k:k + ENTRY].hex().upper() for k in range(0, len(spare), ENTRY)),
                "why": "spare slots %d-%d: the Consultant's entry (chr id 92, gangster background, unlock "
                       "kind 0 'never', so hidden everywhere), each with a portrait of its own, texture "
                       "%d-%d" % (ROSTER_N, N - 1, TEX_N, T - 1)})
    ops.append({"op": "write", "va": off(roster_new + N * ENTRY), "bytes": "FFFFFFFF",
                "why": "the sentinel after the last slot: chr id -1, where the four chr id searches "
                       "below now stop"})
    ops.append({"op": "copy", "from": "0x%08X" % TEX, "to": off(tex_new), "size": "0x%X" % (TEX_N * TEX_ENTRY),
                "why": "the disc's 548 texture list entries: how to load (+0), load flags (+4), path (+8), "
                       "handle (+0xC)"})
    spare_tex = struct.pack("<4I", 1, 0, PED3_PATH, 0)
    ops.append({"op": "write", "va": off(tex_new + TEX_N * TEX_ENTRY),
                "bytes": " ".join(spare_tex.hex().upper() for _ in range(S)),
                "why": "the spare slots' portraits, texture %d-%d: the Consultant's path (ped3) with load "
                       "flags 0, which no level loads; a mod's ts2/characters.ini gives each its own file "
                       "and the Consultant's flags" % (TEX_N, T - 1)})

    repoint(ROSTER_SITES, ROSTER, ROSTER + ROSTER_N * ENTRY, lambda v: v - ROSTER + roster_new, "the roster")
    repoint(SNAP_SITES, SNAP, SNAP + 1, lambda v: snap_new, "the snapshot")
    for site in ROSTER_BYTES_SITES:
        immediate(site, ROSTER_N * ENTRY, N * ENTRY, "; spare slots are kind 0, so the count of shown "
                                                     "or unlocked entries does not change")
    for site in SNAP_BYTES_SITES:
        immediate(site, ROSTER_N * 4, N * 4)
    for va, fn, why in SENTINEL_SITES:
        i = insn_at(va)
        if bytes(i.bytes)[2] != 0x7F or i.mnemonic != "cmp":
            sys.exit("0x%08X: not cmp reg, 0x7F" % va)
        ops.append({"op": "patch", "va": "0x%08X" % va, "old": bytes(i.bytes).hex().upper(), "new": "8339FF",
                    "why": "%s %s, %s -> cmp dword ptr [ecx], -1: %s; a search by chr id bounded by 127 as "
                           "an imm8, which cannot be raised, so it stops at the sentinel instead (ecx has "
                           "just moved to the next entry)" % (fn, i.mnemonic, i.op_str, why)})
    repoint(TEX_SITES, TEX, TEX_END, lambda v: v - TEX + tex_new, "the texture list",
            TEX_ENTRY)
    repoint(TEX_END_SITES, TEX_END, TEX_END + TEX_ENTRY, lambda v: v - TEX_END + tex_new + T * TEX_ENTRY,
            "the texture list's end")
    immediate(TEX_COUNT_SITE, TEX_N, T)
    immediate(ITEM_POOL_SITE, 0x163, 0x163 + 4 * S, "; 4 more per spare slot, one per player's column")

    spec = {
        "format": 1,
        "xbe_sha1": PAL_SHA1,
        "comment": "TimeSplitters 2 PAL: the character roster with %d spare slots (127-%d), for characters "
                   "a mod adds (ts2/characters.ini). Written by tools/ts2_roster_patches.py; "
                   "docs/formats/roster.md, 'Room for more characters', says why each site changes. "
                   "sub_0008FAE0's search (0x0008FB6E) keeps its 127: recomp_manual.c covers it."
                   % (S, N - 1),
        "operations": ops,
    }
    with open(a.out, "w") as f:
        json.dump(spec, f, indent=1)
        f.write("\n")
    print("%s: %d operations, %d spare slots, section 0x%08X + 0x%X (roster 0x%08X, snapshot 0x%08X, "
          "textures 0x%08X)" % (a.out, len(ops), S, SECTION_VA, size, roster_new, snap_new, tex_new))


if __name__ == "__main__":
    main()
