"""Unpack and repack TimeSplitters 2's .pak archives (Xbox).

Two layouts, both uncompressed:

  P8CK  header: magic, directory offset, entry count, name table offset,
        name table length. Data from 0x20, then the name table (NUL-terminated
        names), then the directory: 12-byte entries of (name offset in the
        table, length, position).
  P4CK  header: magic, directory offset, directory length. Data, then the
        directory: 60-byte entries of name[48], position, length, a zero.

Data alignment is per archive (16 in most, 128 in cs_l_35.pak, 2048 in
chrinc.pak), P8CK pads with the start of "ho ho and and a" rather than zeros, and directory order is not data order, so `unpack` writes a
manifest that keeps both and `pack` rebuilds an unchanged folder byte for
byte. Changed files may be any size; what follows them moves.

  python3 tools/ts2pak.py list   game/data/chr.pak
  python3 tools/ts2pak.py unpack game/data/chr.pak out/chr.pak
  python3 tools/ts2pak.py pack   out/chr.pak mods/chr.pak
  python3 tools/ts2pak.py verify game/data            # round-trips every pak
"""

import argparse
import json
import os
import struct
import sys

MANIFEST = "_pak.json"


def read_pak(data):
    """Returns (magic, entries, layout): entries in directory order as dicts
    of name, position, length; layout what pack needs to rebuild it."""
    magic = data[:4]
    if magic == b"P8CK":
        dir_off, count, names_off, names_len = struct.unpack_from("<4I", data, 4)
        entries = []
        for i in range(count):
            name_off, length, pos = struct.unpack_from("<3I", data, dir_off + 12 * i)
            end = data.index(b"\0", names_off + name_off)
            name = data[names_off + name_off:end].decode("latin-1")
            entries.append({"name": name, "position": pos, "length": length,
                            "name_offset": name_off})
        data_end = names_off
    elif magic == b"P4CK":
        dir_off, dir_len = struct.unpack_from("<2I", data, 4)
        if dir_len % 60:
            raise ValueError("P4CK directory length %d is not a multiple of 60" % dir_len)
        entries = []
        for i in range(dir_len // 60):
            raw, pos, length, zero = struct.unpack_from("<48s3I", data, dir_off + 60 * i)
            if zero:
                raise ValueError("P4CK entry %d: last field is %#x, not 0" % (i, zero))
            entries.append({"name": raw.split(b"\0", 1)[0].decode("latin-1"),
                            "position": pos, "length": length})
        data_end = dir_off
    else:
        raise ValueError("not a TS2 pak (magic %r)" % magic)

    by_pos = sorted(entries, key=lambda e: e["position"])
    first = by_pos[0]["position"] if by_pos else 0x20
    align = 2048
    while align > 1 and any(e["position"] % align for e in by_pos):
        align //= 2
    layout = {"magic": magic.decode(), "align": align, "first": first,
              "data_order": [entries.index(e) for e in by_pos],
              # Empty files keep whatever position they had (l_106.pak's
              # three do not follow the layout); nothing is read from it.
              "empty_positions": {str(i): e["position"] for i, e in enumerate(entries)
                                  if not e["length"]}}
    if magic == b"P8CK":
        # Names are stored in their own order; keep it.
        layout["name_order"] = [i for i, _ in sorted(enumerate(entries),
                                                     key=lambda ie: ie[1]["name_offset"])]
    # The bytes after the last file and before the table that follows it.
    last_end = max((e["position"] + e["length"] for e in entries), default=first)
    layout["tail"] = data_end - last_end
    return magic, entries, layout


# P8CK pads with the start of this string, never with zeros; P4CK with zeros.
P8CK_FILLER = b"ho ho and and a"


def padding(magic, n):
    if magic != b"P8CK":
        return b"\0" * n
    return (P8CK_FILLER * (n // len(P8CK_FILLER) + 1))[:n]


def build_pak(layout, names, blobs):
    """names and blobs in directory order."""
    magic = layout["magic"].encode()
    align = layout["align"]
    head = 20 if magic == b"P8CK" else 12
    out = bytearray(head) + padding(magic, layout["first"] - head)
    positions = [0] * len(names)
    for k, i in enumerate(layout["data_order"]):
        if k:
            out += padding(magic, -len(out) % align)
        positions[i] = len(out)
        out += blobs[i]
    out += padding(magic, layout["tail"])
    for i, pos in layout["empty_positions"].items():
        if not blobs[int(i)]:
            positions[int(i)] = pos

    if magic == b"P8CK":
        names_off = len(out)
        name_offsets = [0] * len(names)
        table = bytearray()
        for i in layout["name_order"]:
            name_offsets[i] = len(table)
            table += names[i].encode("latin-1") + b"\0"
        out += table
        out += padding(magic, -len(out) % 4)
        dir_off = len(out)
        for i, name in enumerate(names):
            out += struct.pack("<3I", name_offsets[i], len(blobs[i]), positions[i])
        struct.pack_into("<4s4I", out, 0, magic, dir_off, len(names), names_off, len(table))
    else:
        dir_off = len(out)
        for i, name in enumerate(names):
            raw = name.encode("latin-1")
            if len(raw) >= 48:
                raise ValueError("P4CK names are at most 47 bytes: %s" % name)
            out += struct.pack("<48s3I", raw, positions[i], len(blobs[i]), 0)
        struct.pack_into("<4s2I", out, 0, magic, dir_off, 60 * len(names))
    return bytes(out)


def safe_path(root, name):
    path = os.path.normpath(os.path.join(root, name))
    if os.path.commonpath([os.path.abspath(root), os.path.abspath(path)]) != os.path.abspath(root):
        raise ValueError("entry escapes the output folder: %s" % name)
    return path


def cmd_list(args):
    data = open(args.pak, "rb").read()
    magic, entries, layout = read_pak(data)
    for e in entries:
        print("%10d %10d  %s" % (e["position"], e["length"], e["name"]))
    print("%s, %d files, aligned to %d" % (magic.decode(), len(entries), layout["align"]),
          file=sys.stderr)


def cmd_unpack(args):
    data = open(args.pak, "rb").read()
    _, entries, layout = read_pak(data)
    for e in entries:
        path = safe_path(args.out, e["name"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data[e["position"]:e["position"] + e["length"]])
    layout["files"] = [e["name"] for e in entries]
    with open(os.path.join(args.out, MANIFEST), "w") as f:
        json.dump(layout, f, indent=1)
    print("%d files to %s" % (len(entries), args.out))


def cmd_pack(args):
    with open(os.path.join(args.folder, MANIFEST)) as f:
        layout = json.load(f)
    names = layout["files"]
    blobs = [open(safe_path(args.folder, n), "rb").read() for n in names]
    out = build_pak(layout, names, blobs)
    with open(args.pak, "wb") as f:
        f.write(out)
    print("%d files, %d bytes to %s" % (len(names), len(out), args.pak))


def cmd_verify(args):
    paks = []
    for root, _, files in os.walk(args.folder):
        paks += [os.path.join(root, f) for f in files if f.lower().endswith(".pak")]
    bad = 0
    for p in sorted(paks):
        data = open(p, "rb").read()
        _, entries, layout = read_pak(data)
        names = [e["name"] for e in entries]
        blobs = [data[e["position"]:e["position"] + e["length"]] for e in entries]
        same = build_pak(layout, names, blobs) == data
        bad += not same
        print("%-4s %s (%d files, align %d)" % ("ok" if same else "DIFF", p, len(entries),
                                                layout["align"]))
    print("%d of %d paks round-trip byte for byte" % (len(paks) - bad, len(paks)))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("pak"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("unpack"); p.add_argument("pak"); p.add_argument("out")
    p.set_defaults(fn=cmd_unpack)
    p = sub.add_parser("pack"); p.add_argument("folder"); p.add_argument("pak")
    p.set_defaults(fn=cmd_pack)
    p = sub.add_parser("verify"); p.add_argument("folder"); p.set_defaults(fn=cmd_verify)
    args = ap.parse_args()
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
