"""Build a TimeSplitters 2 mod folder for RECOMP_MODS from loose files.

A level does not load its characters from chr.pak: every story and arcade
level pak carries its own copies (byte-identical, textures under the same
global textures/NNNN.xbt numbers), so a changed character file has to go
into every pak that holds it. This does that.

The source folder:

  files/<path in a pak>                  replaces that file in every pak that
                                         has it (ob/chrs/chr19.xbr,
                                         textures/0267.xbt)
  paks/<pak under data>/<path in a pak>  replaces or adds a file in that one
                                         pak (paks/story/l_35_ST.pak/ob/chrs/chr200.xbr)

The output folder gets data/<pak> for each pak that changed, laid out as
RECOMP_MODS expects, and mod.json saying what went where.

  python3 tools/ts2mod.py build <source> game/data <out>
  RECOMP_MODS=<out> ./split2_recomp
"""

import argparse
import json
import os
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


def cmd_build(args):
    files = walk_files(os.path.join(args.source, "files"))
    specific = pak_specific(args.source)
    paks = disc_paks(args.data)
    by_lower = {rel.lower(): rel for rel in paks}
    for rel in specific:
        if rel.lower() not in by_lower:
            raise SystemExit("paks/%s: no such pak under %s" % (rel, args.data))

    report = {"paks": {}, "unused": [], "skipped": {}}
    used = set()
    ref = reference_copies(paks, files)
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
        if not replace and not add:
            continue
        used.update(n for n in replace if n in files)
        out_path = os.path.join(args.out, "data", *rel.split("/"))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(rebuild(data, replace, add))
        report["paks"][rel] = {"replaced": sorted(replace), "added": sorted(add)}
        print("data/%s: %d replaced, %d added" % (rel, len(replace), len(add)))

    report["unused"] = sorted(set(files) - used)
    for n, where in sorted(report["skipped"].items()):
        print("warning: files/%s left alone in %s, where that name is a different file "
              "(use paks/<pak>/%s to replace it there)" % (n, ", ".join(where), n), file=sys.stderr)
    for n in report["unused"]:
        print("warning: files/%s is in no pak on the disc" % n, file=sys.stderr)
    with open(os.path.join(args.out, "mod.json"), "w") as f:
        json.dump(report, f, indent=1)
    print("%d paks written to %s" % (len(report["paks"]), args.out))


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
    p = sub.add_parser("build", help="write the changed paks of a mod")
    p.add_argument("source"); p.add_argument("data"); p.add_argument("out")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("where", help="list the paks that hold a file")
    p.add_argument("data"); p.add_argument("name")
    p.set_defaults(fn=cmd_where)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
