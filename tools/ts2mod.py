"""Make, build and check TimeSplitters 2 mods for RECOMP_MODS.

A mod is a folder. The game (split2-recomp, PAL) reads loose files from it
at run time and stacks every mod in RECOMP_MODS (docs/modding.md):

  files/<path in a pak>                  that file in every pak that holds it,
                                         and found in any level if no pak does
  paks/<pak under data>/<path in a pak>  that file in that one pak
  ts2/characters.ini                     characters the mod adds to the roster
  data/<pak>                             a whole pak, as on the disc (optional)

So the source folder below is already a mod. Three commands:

  loose  copy a source to a mod folder as it is, with mod.json saying what is
         in it, and (given the disc's data folder) the disc textures its models
         need where the paks they go into lack them. No pak is rebuilt; mods
         made this way stack. ts2kitbash's output is one already.
  build  rebuild the paks a source changes, into data/<pak>: one folder that
         works on its own, for a player who wants that. Whole paks do not
         stack: the first mod with data/chr.pak wins it (loose files from
         other mods still apply on top).
  check  report what two or more mods both supply (and which one wins), their
         characters.ini claims, and texture ids picked by two mods.

A level does not load its characters from chr.pak: every story and arcade
level pak carries its own copies (byte-identical, textures under the same
global textures/NNNN.xbt numbers), so a changed character file has to go
into every pak that holds it. files/ does that.

The source folder:

  files/<path in a pak>                  replaces that file in every pak that
                                         has it (ob/chrs/chr19.xbr,
                                         textures/0267.xbt)
  paks/<pak under data>/<path in a pak>  replaces or adds a file in that one
                                         pak (paks/story/l_35_ST.pak/ob/chrs/chr200.xbr)
  ts2/<file>                             copied as it is: the game reads these
                                         itself (ts2/characters.ini declares an
                                         added character; docs/formats/roster.md)

A character model (.xbr) put into a pak brings the textures it names that
the pak lacks: files/textures/NNNN.xbt from the mod (new textures, numbered
from 8000 by ts2gltf.py), else the disc's copy (chr.pak's), so a character
built from two characters' pieces finds both sets of textures in a level.

For build, the output folder gets data/<pak> for each pak that changed,
laid out as RECOMP_MODS expects, and mod.json saying what went where.

  python3 tools/ts2mod.py loose <source> <mod> [--data game/data]
  python3 tools/ts2mod.py build <source> game/data <mod>
  python3 tools/ts2mod.py check <mod> [<mod> ...]
  RECOMP_MODS=<mod>:<another mod> ./split2_recomp      (';' on Windows)

At run time a name in files/ replaces a pak's copy only where that copy is
as long as chr.pak's (textures/0478.xbt is another picture in
story/l_20_ST.pak and arcade/l_43_AR.pak): use paks/<pak>/ for those.
"""

import argparse
import json
import os
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ts2pak  # noqa: E402


def walk_files(root):
    """{path relative to root, with '/'}: host path."""
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            if f.startswith(".") or f == ts2pak.MANIFEST:
                continue
            full = os.path.join(d, f)
            out[os.path.relpath(full, root).replace(os.sep, "/")] = full
    return out


def disc_paks(data_dir):
    """{pak path relative to data, with '/'}: host path."""
    return {rel: full for rel, full in walk_files(data_dir).items()
            if rel.lower().endswith(".pak")}


def pak_specific(source):
    """{pak rel: {path in pak: host path}} from source/paks."""
    out = {}
    root = os.path.join(source, "paks")
    for rel, full in walk_files(root).items():
        parts = rel.split("/")
        for i, part in enumerate(parts[:-1]):
            if part.lower().endswith(".pak"):
                out.setdefault("/".join(parts[:i + 1]), {})["/".join(parts[i + 1:])] = full
                break
        else:
            raise SystemExit("%s: not under a <name>.pak folder" % os.path.join(root, rel))
    return out


def rebuild(data, replace, add):
    """data: the pak's bytes; replace/add: {name: bytes}. Returns new bytes.

    Every P8CK directory on the disc is sorted by name (byte order), which
    reads as a binary search in the loader, so an added file is inserted in
    order there; P4CK directories are not sorted and it goes at the end.
    """
    magic, entries, layout = ts2pak.read_pak(data)
    names = [e["name"] for e in entries]
    blobs = [data[e["position"]:e["position"] + e["length"]] for e in entries]
    lower = {n.lower(): i for i, n in enumerate(names)}
    for name, blob in replace.items():
        blobs[lower[name.lower()]] = blob
    for name, blob in add.items():
        i = len(names)
        names.append(name)
        blobs.append(blob)
        layout["data_order"].append(i)
        if "name_order" in layout:
            layout["name_order"].append(i)
    if magic == b"P8CK" and add:
        order = sorted(range(len(names)), key=lambda i: names[i].encode("latin-1"))
        new_index = {old: new for new, old in enumerate(order)}
        names = [names[i] for i in order]
        blobs = [blobs[i] for i in order]
        layout["data_order"] = [new_index[i] for i in layout["data_order"]]
        layout["name_order"] = [new_index[i] for i in layout["name_order"]]
        layout["empty_positions"] = {str(new_index[int(i)]): pos
                                     for i, pos in layout["empty_positions"].items()}
    return ts2pak.build_pak(layout, names, blobs)


def reference_copies(paks, names):
    """{name: bytes of the copy a files/ entry stands for}: chr.pak's where
    it has one, else the commonest copy. Texture numbers are global, with
    exceptions: textures/0478.xbt is another texture in l_20_ST.pak and
    l_43_AR.pak, so a copy that differs from the reference is left alone."""
    copies = {n.lower(): {} for n in names}
    for rel in sorted(paks, key=lambda r: r.lower() != "chr.pak"):
        data = open(paks[rel], "rb").read()
        _, entries, _ = ts2pak.read_pak(data)
        for e in entries:
            c = copies.get(e["name"].lower())
            if c is not None:
                blob = data[e["position"]:e["position"] + e["length"]]
                c.setdefault(blob, []).append(rel)
    ref = {}
    for n, c in copies.items():
        if c:
            in_chr = [b for b, where in c.items() if "chr.pak" in (w.lower() for w in where)]
            ref[n] = in_chr[0] if in_chr else max(c, key=lambda b: len(c[b]))
    return ref


def xbr_texture_ids(blob):
    """Texture ids a character model names (materials that are not embedded):
    the material list at 0xC, 16 bytes each, up to an id of 0xFFFFFFFF
    (docs/formats/xbr.md)."""
    ids = []
    if len(blob) < 16 or struct.unpack_from("<I", blob, 0)[0] != 0xC:
        return ids
    o = 0xC
    while o + 16 <= len(blob):
        tid, _, _, flags = struct.unpack_from("<4I", blob, o)
        o += 16
        if tid == 0xFFFFFFFF:
            break
        if not flags & 0x10000000 and tid != 0x40000000:
            ids.append(tid)
    return ids


class DiscTextures:
    """textures/NNNN.xbt from the disc, chr.pak's copy first (the paks are
    only read when a texture is asked for)."""

    def __init__(self, paks):
        self.paks = sorted(paks.items(), key=lambda kv: kv[0].lower() != "chr.pak")
        self.index = None

    def get(self, name):
        if self.index is None:
            self.index = {}
            for rel, path in self.paks:
                _, entries, _ = ts2pak.read_pak(open(path, "rb").read())
                for e in entries:
                    if e["name"].lower().startswith("textures/"):
                        self.index.setdefault(e["name"].lower(), (path, e["position"], e["length"]))
        hit = self.index.get(name.lower())
        if hit is None:
            return None
        with open(hit[0], "rb") as f:
            f.seek(hit[1])
            return f.read(hit[2])


def textures_needed(blobs, have, files, disc):
    """{textures/NNNN.xbt: bytes} that the .xbr files among blobs name and the
    pak lacks: from the mod's files/textures/ first, else the disc's copy
    (another character's texture, for a model built from two)."""
    out = {}
    for name, blob in blobs.items():
        if not name.lower().endswith(".xbr"):
            continue
        for tid in xbr_texture_ids(blob):
            tn = "textures/%04d.xbt" % tid
            if tn in have or tn in out:
                continue
            src = next((k for k in files if k.lower() == tn), None)
            data = open(files[src], "rb").read() if src else disc.get(tn)
            if data is None:
                print("warning: %s names %s, which is neither in the mod nor on the disc" % (name, tn),
                      file=sys.stderr)
                continue
            out[src or tn] = data
    return out


def cmd_build(args):
    files = walk_files(os.path.join(args.source, "files"))
    specific = pak_specific(args.source)
    paks = disc_paks(args.data)
    by_lower = {rel.lower(): rel for rel in paks}
    for rel in specific:
        if rel.lower() not in by_lower:
            raise SystemExit("paks/%s: no such pak under %s" % (rel, args.data))

    report = {"paks": {}, "unused": [], "skipped": {}, "textures_added": {}}
    used = set()
    ref = reference_copies(paks, files)
    disc_textures = DiscTextures(paks)
    for rel in sorted(paks):
        data = open(paks[rel], "rb").read()
        _, entries, _ = ts2pak.read_pak(data)
        have = {e["name"].lower() for e in entries}
        replace = {}
        for e in entries:
            n = e["name"]
            src = next((k for k in files if k.lower() == n.lower()), None) if n.lower() in ref else None
            if src is None:
                continue
            if data[e["position"]:e["position"] + e["length"]] == ref[n.lower()]:
                replace[src] = open(files[src], "rb").read()
            else:
                report["skipped"].setdefault(src, []).append(rel)
        add = {}
        for spec_rel, spec in specific.items():
            if spec_rel.lower() != rel.lower():
                continue
            for n, p in spec.items():
                (replace if n.lower() in have else add)[n] = open(p, "rb").read()
        for n, blob in textures_needed(dict(replace, **add), have | {a.lower() for a in add}, files,
                                       disc_textures).items():
            add[n] = blob
            report["textures_added"].setdefault(n, []).append(rel)
            used.add(n)
        if not replace and not add:
            continue
        used.update(n for n in replace if n in files)
        out_path = os.path.join(args.out, "data", *rel.split("/"))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(rebuild(data, replace, add))
        report["paks"][rel] = {"replaced": sorted(replace), "added": sorted(add)}
        print("data/%s: %d replaced, %d added" % (rel, len(replace), len(add)))

    own = walk_files(os.path.join(args.source, "ts2"))
    for rel, full in sorted(own.items()):
        dest = os.path.join(args.out, "ts2", *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(full, dest)
        print("ts2/%s: copied" % rel)
    report["ts2"] = sorted(own)

    report["unused"] = sorted(set(files) - used)
    for n, where in sorted(report["skipped"].items()):
        print("warning: files/%s left alone in %s, where that name is a different file "
              "(use paks/<pak>/%s to replace it there)" % (n, ", ".join(where), n), file=sys.stderr)
    for n in report["unused"]:
        print("warning: files/%s is in no pak on the disc" % n, file=sys.stderr)
    with open(os.path.join(args.out, "mod.json"), "w") as f:
        json.dump(report, f, indent=1)
    print("%d paks written to %s" % (len(report["paks"]), args.out))


LOOSE_TREES = ("files", "paks", "ts2")
NAME_MAX = 47          # a P4CK name's room; the game compares no further
SPARE_SLOTS = (127, 158)


def loose_index(mod):
    """What a mod folder holds: {"files": {name: path}, "paks": {pak: {name:
    path}}, "ts2": {rel: path}, "data": {pak: path}}, names as spelled."""
    return {"files": walk_files(os.path.join(mod, "files")),
            "paks": pak_specific(mod) if os.path.isdir(os.path.join(mod, "paks")) else {},
            "ts2": walk_files(os.path.join(mod, "ts2")),
            "data": disc_paks(os.path.join(mod, "data"))}


def write_manifest(mod, extra=None):
    """mod.json: what a loose mod holds, for people and for ts2mod check. The
    game does not read it."""
    idx = loose_index(mod)
    manifest = {"format": "split2-recomp loose mod",
                "files": sorted(idx["files"]),
                "paks": {p: sorted(names) for p, names in sorted(idx["paks"].items())},
                "ts2": sorted(idx["ts2"]),
                "data": sorted(idx["data"])}
    manifest.update(extra or {})
    with open(os.path.join(mod, "mod.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    return manifest


def check_names(idx, where):
    bad = 0
    names = [("files/" + n, n) for n in idx["files"]]
    names += [("paks/%s/%s" % (p, n), n) for p, ns in idx["paks"].items() for n in ns]
    for shown, n in names:
        if len(n.encode("latin-1", "replace")) > NAME_MAX:
            print("warning: %s/%s: a name in a pak is at most %d characters; the game leaves it out"
                  % (where, shown, NAME_MAX), file=sys.stderr)
            bad += 1
        if n != n.lower():
            print("warning: %s/%s: the disc's names are lower case, and an added file is "
                  "looked up as the game spells it" % (where, shown), file=sys.stderr)
    return bad


def cmd_loose(args):
    """Copy a source to a mod folder as it is (or, given the same folder,
    leave it in place) and write mod.json; with --data, add the disc's copy
    of each texture a model names where the pak it goes into lacks it."""
    src, out = os.path.abspath(args.source), os.path.abspath(args.out)
    if src != out:
        for tree in LOOSE_TREES:
            for rel, full in walk_files(os.path.join(src, tree)).items():
                dest = os.path.join(out, tree, *rel.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copyfile(full, dest)
    idx = loose_index(out)
    check_names(idx, out)
    added = {}
    if args.data:
        paks = disc_paks(args.data)
        by_lower = {rel.lower(): rel for rel in paks}
        for p in idx["paks"]:
            if p.lower() not in by_lower:
                print("warning: paks/%s: no such pak under %s" % (p, args.data), file=sys.stderr)
        disc = DiscTextures(paks)
        dirs = {}

        def names_in(rel):
            if rel not in dirs:
                _, entries, _ = ts2pak.read_pak(open(paks[rel], "rb").read())
                dirs[rel] = {e["name"].lower() for e in entries}
            return dirs[rel]

        mod_tex = {n.lower() for n in idx["files"]}
        # A model in paks/<pak>: that pak. In files/: every pak holding it.
        jobs = [(p, n, path) for p, ns in idx["paks"].items() for n, path in ns.items()]
        jobs += [(None, n, path) for n, path in idx["files"].items()]
        for pak, name, path in jobs:
            if not name.lower().endswith(".xbr"):
                continue
            if not pak:
                targets = [rel for rel in paks if name.lower() in names_in(rel)]
            elif pak.lower() in by_lower:
                targets = [by_lower[pak.lower()]]
            else:
                targets = []
            have_mod = mod_tex | ({n.lower() for n in idx["paks"].get(pak, {})} if pak else set())
            for tid in xbr_texture_ids(open(path, "rb").read()):
                tn = "textures/%04d.xbt" % tid
                if tn in have_mod:
                    continue
                lacking = [rel for rel in targets if tn not in names_in(rel)]
                if not lacking:
                    continue
                blob = disc.get(tn)
                if blob is None:
                    print("warning: %s names %s, which is neither in the mod nor on the disc"
                          % (name, tn), file=sys.stderr)
                    continue
                rel_out = ("paks/%s/%s" % (pak, tn)) if pak else ("files/" + tn)
                dest = os.path.join(out, *rel_out.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(blob)
                added.setdefault(rel_out, sorted(lacking))
                (idx["paks"].setdefault(pak, {}) if pak else idx["files"])[tn] = dest
                have_mod.add(tn)
        for rel_out, where in sorted(added.items()):
            print("%s: the disc's copy, for %s" % (rel_out, ", ".join(where)))
    m = write_manifest(out, {"textures_from_disc": added} if added else None)
    print("%s: %d files/, %d paks/ files in %d paks, %d ts2/ files%s" % (
        out, len(m["files"]), sum(len(v) for v in m["paks"].values()), len(m["paks"]),
        len(m["ts2"]), ", %d whole paks" % len(m["data"]) if m["data"] else ""))


def read_ini_claims(path):
    """[(section, chr id, slot)] from a characters.ini, slot "next" or an int."""
    out, cur = [], None
    for line in open(path, encoding="utf-8", errors="replace"):
        s = line.strip()
        if not s or s[0] in ";#":
            continue
        if s.startswith("["):
            cur = {"title": s[1:].split("]")[0].strip(), "chr": None, "slot": None}
            out.append(cur)
            continue
        if cur is None or "=" not in s:
            continue
        key, val = s.split("=", 1)
        val = val.split(";")[0].strip()
        key = key.strip()
        try:
            if key == "chr":
                cur["chr"] = int(val, 0)
            elif key == "slot":
                cur["slot"] = "next" if val == "next" else int(val, 0)
        except ValueError:
            cur["bad"] = "%s = %s is not a number" % (key, val)
    return out


def file_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def cmd_check(args):
    """What the mods would do together, in RECOMP_MODS order (first wins)."""
    mods = [(m, loose_index(m)) for m in args.mods]
    problems = 0
    for m, idx in mods:
        problems += check_names(idx, m)

    # The same name for the same pak from two mods.
    claims = {}
    for k, (m, idx) in enumerate(mods):
        for n, path in idx["files"].items():
            claims.setdefault(n.lower(), []).append((k, None, path))
        for p, ns in idx["paks"].items():
            for n, path in ns.items():
                claims.setdefault(n.lower(), []).append((k, p.lower(), path))
    for name, who in sorted(claims.items()):
        for i, (ka, pa, a) in enumerate(who):
            for kb, pb, b in who[i + 1:]:
                if ka == kb or (pa and pb and pa != pb):
                    continue
                scope = pa or pb or "every pak"
                if os.path.getsize(a) == os.path.getsize(b) and file_bytes(a) == file_bytes(b):
                    print("same: %s in %s, from %s and %s (identical)" % (name, scope, args.mods[ka],
                                                                         args.mods[kb]))
                    continue
                problems += 1
                note = ""
                tid = name[len("textures/"):-len(".xbt")] if name.startswith("textures/") else ""
                if tid.isdigit() and 8000 <= int(tid) <= 9999:
                    note = " (a new texture id both picked by hash: rebuild one of them)"
                print("CONFLICT: %s in %s: %s and %s differ; %s's is used%s"
                      % (name, scope, args.mods[ka], args.mods[kb], args.mods[ka], note))

    # Whole paks: the first mod that has one wins it.
    whole = {}
    for k, (m, idx) in enumerate(mods):
        for p in idx["data"]:
            whole.setdefault(p.lower(), []).append(k)
    for p, ks in sorted(whole.items()):
        if len(ks) > 1:
            problems += 1
            print("CONFLICT: data/%s is a whole pak in %s; only %s's is read"
                  % (p, ", ".join(args.mods[k] for k in ks), args.mods[ks[0]]))

    # characters.ini: chr ids and numbered slots, and the spare slots.
    taken_chr, taken_slot, nexts = {}, {}, 0
    for k, (m, idx) in enumerate(mods):
        ini = idx["ts2"].get("characters.ini")
        if not ini:
            continue
        for c in read_ini_claims(ini):
            where = "[%s] in %s" % (c["title"], args.mods[k])
            if c.get("bad") or c["chr"] is None or c["chr"] < 0:
                problems += 1
                print("CONFLICT: %s: %s; the game skips it"
                      % (where, c.get("bad") or "it has no chr id"))
                continue
            if c["chr"] in taken_chr:
                problems += 1
                print("CONFLICT: %s: chr id %s is already %s's; the game skips it"
                      % (where, c["chr"], taken_chr[c["chr"]]))
                continue
            if isinstance(c["slot"], int) and c["slot"] in taken_slot:
                problems += 1
                print("CONFLICT: %s: roster slot %d is already %s's; the game skips it"
                      % (where, c["slot"], taken_slot[c["slot"]]))
                continue
            taken_chr[c["chr"]] = where
            if c["slot"] == "next":
                nexts += 1
            elif c["slot"] is not None:
                taken_slot[c["slot"]] = where
    spare = SPARE_SLOTS[1] - SPARE_SLOTS[0] + 1 - sum(SPARE_SLOTS[0] <= s <= SPARE_SLOTS[1]
                                                       for s in taken_slot)
    if taken_chr:
        print("characters: %d, %d of them in the next free spare slot (%d free)"
              % (len(taken_chr), nexts, spare))
    if nexts > spare:
        problems += 1
        print("CONFLICT: %d characters want a spare slot and %d are free; the last %d are skipped"
              % (nexts, spare, nexts - spare))
    print("%d conflicts" % problems if problems else "no conflicts")
    return 1 if problems else 0


def cmd_where(args):
    """Which paks hold a file (or every file under a prefix)."""
    for rel, full in sorted(disc_paks(args.data).items()):
        _, entries, _ = ts2pak.read_pak(open(full, "rb").read())
        hits = [e["name"] for e in entries if e["name"].lower().startswith(args.name.lower())]
        if hits:
            print("data/%s: %s" % (rel, " ".join(hits)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("loose", help="a mod of loose files, which stacks with others (the default)")
    p.add_argument("source"); p.add_argument("out")
    p.add_argument("--data", help="the disc's data folder: add disc textures the models need")
    p.set_defaults(fn=cmd_loose)
    p = sub.add_parser("build", help="write the changed paks of a mod: one self-contained folder")
    p.add_argument("source"); p.add_argument("data"); p.add_argument("out")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("check", help="what two or more mods both supply, in RECOMP_MODS order")
    p.add_argument("mods", nargs="+")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("where", help="list the paks that hold a file")
    p.add_argument("data"); p.add_argument("name")
    p.set_defaults(fn=cmd_where)
    args = ap.parse_args()
    sys.exit(args.fn(args) or 0)


if __name__ == "__main__":
    main()
