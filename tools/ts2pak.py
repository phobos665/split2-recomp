"""
TimeSplitters 2 .pak archives: list, unpack, repack, verify.

    py -3 -m tools.ts2pak list   game/data/chr.pak
    py -3 -m tools.ts2pak unpack game/data/chr.pak out/chr
    py -3 -m tools.ts2pak pack   game/data/chr.pak out/chr_edited -o mods/data/chr.pak
    py -3 -m tools.ts2pak verify game/data/chr.pak

The game opens whole archives (\\Device\\CdRom0\\data\\chr.pak), so a mod that
changes one file inside one is a rebuilt archive dropped at the same path in
the mods folder (xboxrecomp: RECOMP_MODS_DIR, "mods" beside the executable).
`pack` rebuilds from the original: every file in the folder you give it that
names an entry replaces that entry, and everything else is copied. The layout
is kept -- regions stay in their original order and at their original offsets
until one grows, and what follows moves only as far as it must, to the same
alignment -- so `verify` (a rebuild with nothing replaced) must give back the
original byte for byte. Run it once on a real archive before trusting `pack`.

The two layouts on the Xbox disc (magic in the first four bytes):

  P8CK  chr.pak, gun.pak, sounds.pak
        header   +0 magic  +4 index offset  +8 entry count
                 +C names offset  +10 names length
        entry    12 bytes: name offset (from the names table), length, offset
  P4CK  the rest
        header   +0 magic  +4 index offset  +8 index length  (+C reserved)
        entry    60 bytes: name[48] (NUL-padded), offset, length, unknown

Little-endian, uncompressed. The P8CK header and entry order were checked
against the PAL disc (xboxrecomp docs/technical/modding-models-textures.md);
the P4CK entry follows OpenRadical's tspak, which reads both. Adding a file
that is not already in an archive is not supported: the game looks files up
by name, and nothing here knows whether it would ever ask for a new one.
"""

import argparse
import glob
import hashlib
import os
import struct
import sys
from dataclasses import dataclass, field

P4_ENTRY = struct.Struct("<48sIII")
P8_ENTRY = struct.Struct("<III")
MAX_ALIGN = 2048


class PakError(Exception):
    pass


@dataclass
class Entry:
    name: str           # as stored, separators and case untouched
    offset: int
    length: int
    unknown: int = 0    # P4CK's fourth field, kept as found
    name_offset: int = 0  # P8CK: where the name sits in the names table


@dataclass
class Pak:
    kind: str           # "P4CK" or "P8CK"
    data: bytes         # the whole archive
    entries: list = field(default_factory=list)
    header_len: int = 0
    index_offset: int = 0
    index_len: int = 0
    names_offset: int = 0   # P8CK only
    names_len: int = 0      # P8CK only

    def read(self, entry):
        return self.data[entry.offset:entry.offset + entry.length]


def key(name):
    """How a name is matched: separators and case do not matter (the Xbox
    path layer is case-insensitive and the archives store backslashes)."""
    return name.replace("\\", "/").lstrip("/").lower()


def read_pak(data):
    if len(data) < 16:
        raise PakError("too short to be a .pak")
    magic = data[:4]
    if magic == b"P8CK":
        if len(data) < 20:
            raise PakError("P8CK header truncated")
        index_off, count, names_off, names_len = struct.unpack_from("<IIII", data, 4)
        pak = Pak("P8CK", data, header_len=20, index_offset=index_off,
                  index_len=count * P8_ENTRY.size, names_offset=names_off,
                  names_len=names_len)
        if index_off + pak.index_len > len(data) or names_off + names_len > len(data):
            raise PakError("P8CK index or names table runs past the end")
        for i in range(count):
            name_rel, length, offset = P8_ENTRY.unpack_from(data, index_off + i * P8_ENTRY.size)
            start = names_off + name_rel
            end = data.find(b"\0", start, names_off + names_len)
            if start >= names_off + names_len:
                raise PakError(f"entry {i}: name offset {name_rel:#x} outside the names table")
            if end < 0:
                end = names_off + names_len
            name = data[start:end].decode("latin-1")
            pak.entries.append(Entry(name, offset, length, name_offset=name_rel))
    elif magic == b"P4CK":
        index_off, index_len = struct.unpack_from("<II", data, 4)
        if index_len % P4_ENTRY.size:
            raise PakError(f"P4CK index length {index_len} is not a multiple of "
                           f"{P4_ENTRY.size}")
        if index_off + index_len > len(data):
            raise PakError("P4CK index runs past the end")
        pak = Pak("P4CK", data, header_len=16, index_offset=index_off, index_len=index_len)
        for i in range(index_len // P4_ENTRY.size):
            raw, offset, length, unknown = P4_ENTRY.unpack_from(
                data, index_off + i * P4_ENTRY.size)
            name = raw.split(b"\0", 1)[0].decode("latin-1")
            pak.entries.append(Entry(name, offset, length, unknown))
    else:
        raise PakError(f"unknown magic {magic!r} (expected P4CK or P8CK)")
    for e in pak.entries:
        if e.offset + e.length > len(data):
            raise PakError(f"{e.name}: data runs past the end of the archive")
    return pak


def _align_of(offset):
    """The alignment an original region evidently kept, capped at 2048."""
    if offset == 0:
        return MAX_ALIGN
    a = offset & -offset
    return min(a, MAX_ALIGN)


def _align_up(v, a):
    return (v + a - 1) // a * a


def build_pak(pak, replacements=None):
    """The archive rebuilt with `replacements` ({entry name or key: bytes}).

    Regions (header, index, names table, each distinct piece of file data)
    are written in their original order. Each keeps its original offset
    unless the region before it now ends past that offset; then it moves to
    the next offset with its original alignment, and everything after it
    moves with it. Entries that shared one piece of data keep sharing it
    unless one of them is replaced.
    """
    replacements = replacements or {}
    by_key = {key(k): v for k, v in replacements.items()}
    names = {key(e.name) for e in pak.entries}
    unknown = sorted(k for k in by_key if k not in names)
    if unknown:
        raise PakError("not in this archive (adding files is not supported): "
                       + ", ".join(unknown))

    # Regions: (orig_offset, orig_length, kind, payload-or-None, entries)
    regions = [(0, pak.header_len, "header", None, [])]
    regions.append((pak.index_offset, pak.index_len, "index", None, []))
    if pak.kind == "P8CK":
        regions.append((pak.names_offset, pak.names_len, "names", None, []))
    shared = {}
    appended = []
    for e in pak.entries:
        new = by_key.get(key(e.name))
        if new is None:
            shared.setdefault((e.offset, e.length), []).append(e)
        else:
            appended.append((e, bytes(new)))
    for (off, length), es in shared.items():
        regions.append((off, length, "data", None, es))
    # A replaced entry takes the place of its old data when nothing else
    # shares it; otherwise it gets a region of its own after the rest.
    tail = []
    for e, new in appended:
        if (e.offset, e.length) in shared:
            tail.append((e, new))
        else:
            regions.append((e.offset, e.length, "data", new, [e]))
            shared[(e.offset, e.length)] = [e]
    regions.sort(key=lambda r: (r[0], r[2] != "header", r[1]))

    out = bytearray()
    new_offset = {}          # id(entry) -> (offset, length)
    placed = {}              # region kind -> offset (header/index/names)
    delta = 0
    prev_orig_end = 0
    for orig_off, orig_len, kind, payload, es in regions:
        body = payload if payload is not None else pak.data[orig_off:orig_off + orig_len]
        if not body and kind == "data":
            # An empty entry has nothing to place, so it moves with whatever
            # is around it and never moves anything itself. arcade/l_106.pak
            # has a zero-length pad/data/level106.raw at the offset of the
            # 2 MB level106.xbr; placed as a region of its own, it pushed
            # everything after it along and the rebuild differed.
            for e in es:
                new_offset[id(e)] = (orig_off + delta, 0)
            continue
        at = orig_off + delta
        if at < len(out):
            at = _align_up(len(out), _align_of(orig_off))
            delta = at - orig_off
        if at > len(out):
            # Padding. Where nothing has moved, the original's own bytes
            # between the two regions are kept, so padding that is not zero
            # survives a rebuild; anything else is zero (never a replaced
            # file's old tail).
            fill = bytearray(at - len(out))
            gap = pak.data[prev_orig_end:orig_off] if prev_orig_end <= orig_off else b""
            if delta == 0 and 0 < len(gap) <= len(fill):
                fill[len(fill) - len(gap):] = gap
            out += fill
        out += body
        prev_orig_end = max(prev_orig_end, orig_off + orig_len)
        if kind in ("header", "index", "names"):
            placed[kind] = at
        for e in es:
            new_offset[id(e)] = (at, len(body))
    for e, new in tail:
        at = _align_up(len(out), MAX_ALIGN)
        out += bytes(at - len(out)) + new
        new_offset[id(e)] = (at, len(new))
    # Whatever followed the last region in the original (trailing padding).
    if prev_orig_end < len(pak.data) and delta == 0 and not tail:
        out += pak.data[prev_orig_end:]

    # Rewrite the header and index with the new offsets and lengths.
    struct.pack_into("<I", out, 4, placed["index"])
    if pak.kind == "P8CK":
        struct.pack_into("<I", out, 0x0C, placed["names"])
        for i, e in enumerate(pak.entries):
            off, length = new_offset[id(e)]
            P8_ENTRY.pack_into(out, placed["index"] + i * P8_ENTRY.size,
                               e.name_offset, length, off)
    else:
        for i, e in enumerate(pak.entries):
            off, length = new_offset[id(e)]
            at = pak.index_offset + i * P4_ENTRY.size
            raw = pak.data[at:at + 48]
            P4_ENTRY.pack_into(out, placed["index"] + i * P4_ENTRY.size,
                               raw, off, length, e.unknown)
    return bytes(out)


# ------------------------------------------------------------------ CLI

def _safe_path(root, name):
    rel = name.replace("\\", "/").lstrip("/")
    path = os.path.normpath(os.path.join(root, rel))
    if os.path.commonpath([os.path.abspath(root), os.path.abspath(path)]) != os.path.abspath(root):
        raise PakError(f"{name}: would be written outside {root}")
    return path


def cmd_list(args):
    pak = read_pak(open(args.pak, "rb").read())
    print(f"{pak.kind}, {len(pak.entries)} entries, index at {pak.index_offset:#x}")
    for e in pak.entries:
        print(f"{e.offset:#010x} {e.length:10d}  {e.name}")


def cmd_unpack(args):
    pak = read_pak(open(args.pak, "rb").read())
    for e in pak.entries:
        path = _safe_path(args.out, e.name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(pak.read(e))
    print(f"{len(pak.entries)} files from {args.pak} into {args.out}")


def cmd_pack(args):
    pak = read_pak(open(args.original, "rb").read())
    repl = {}
    for root, _, files in os.walk(args.folder):
        for fn in files:
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, args.folder)
            repl[rel] = open(path, "rb").read()
    if args.only_changed:
        current = {key(e.name): pak.read(e) for e in pak.entries}
        repl = {k: v for k, v in repl.items() if current.get(key(k)) != v}
    out = build_pak(pak, repl)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "wb") as f:
        f.write(out)
    print(f"{args.output}: {len(repl)} file(s) replaced, {len(out)} bytes "
          f"(original {len(pak.data)})")


def _expand(patterns):
    """Globs expanded here too: cmd.exe and PowerShell pass *.pak through."""
    out = []
    for p in patterns:
        hits = sorted(glob.glob(p)) if any(c in p for c in "*?[") else [p]
        if not hits:
            raise PakError(f"no file matches {p}")
        out.extend(hits)
    return out


def cmd_verify(args):
    ok = True
    for p in _expand(args.pak):
        data = open(p, "rb").read()
        try:
            pak = read_pak(data)
            same = build_pak(pak) == data
        except PakError as exc:
            print(f"FAIL {p}: {exc}")
            ok = False
            continue
        sha = hashlib.sha1(data).hexdigest()[:12]
        print(f"{'ok  ' if same else 'FAIL'} {p}: {pak.kind}, {len(pak.entries)} entries, "
              f"sha1 {sha}, rebuild {'identical' if same else 'DIFFERS'}")
        ok &= same
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ts2pak", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="the entries of an archive")
    p.add_argument("pak")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("unpack", help="every entry into a folder")
    p.add_argument("pak")
    p.add_argument("out")
    p.set_defaults(fn=cmd_unpack)
    p = sub.add_parser("pack", help="rebuild an archive with files replaced")
    p.add_argument("original", help="the archive to rebuild")
    p.add_argument("folder", help="replacement files, by their path inside the archive")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--only-changed", action="store_true",
                   help="ignore files identical to the original's (so a whole "
                        "unpacked folder can be given)")
    p.set_defaults(fn=cmd_pack)
    p = sub.add_parser("verify", help="rebuild with nothing replaced and compare")
    p.add_argument("pak", nargs="+")
    p.set_defaults(fn=cmd_verify)
    args = ap.parse_args(argv)
    try:
        return args.fn(args) or 0
    except (PakError, OSError) as exc:
        print(f"ts2pak: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
