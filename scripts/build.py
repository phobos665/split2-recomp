"""Lift TimeSplitters 2 from your own copy of the game, then build it.

    py -3 scripts/build.py              lift (first time only), then build
    py -3 scripts/build.py --relift     lift again, e.g. after new seeds or a toolkit update
    py -3 scripts/build.py --no-build   lift only

The game's files go in game/ at the root of this repository (default.xbe and
the rest of the disc), or pass --game DIR.

Which release the disc is -- PAL or USA -- is read from default.xbe's SHA-1,
and the addresses for it come from config/<region>/. A release whose folder
has an xbe_patches.json (PAL: the roster with room for added characters) is
lifted from its default.xbe with those patches applied; the file on disc is
only read (xboxrecomp docs/technical/xbe-patches.md).
"""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLKIT = ROOT / "xboxrecomp"
GEN = ROOT / "src" / "recomp" / "gen"
BUILD = ROOT / "build"
# Which release src/recomp/gen was lifted from, for the C side
# (src/main.c, src/recomp_manual.c). Written by every lift, beside it.
REGION_HEADER = ROOT / "src" / "recomp" / "ts2_region.h"

# The releases this repository has addresses for, by the SHA-1 of their
# default.xbe. All of them are title 4553000A, XDK 4721, so the title ID
# cannot tell them apart; the hash can.
#
#   region    the folder under config/ with that release's seeds.json,
#             xdk_symbols.json and overrides.inc (the addresses of the
#             functions src/recomp_manual.c overrides), and xbe_patches.json
#             when that release's XBE is patched before it is lifted
#   work_dir  the pipeline's stage output, one per release, because it keeps
#             per-address state between lifts (recomp/icall_sites.json)
#
# Another release (JP, another revision) is another entry and another folder
# under config/; see README.md, "Other versions".
Release = namedtuple("Release", "region name work_dir")
RELEASES = {
    # PAL, certificate region 0x4, version 2: the release this repository
    # began with. Its stage output stays where it always was.
    "2809eb147385723eaa90c425be89ee4db033fc5a":
        Release("pal", "PAL", ROOT / ".pipeline"),
    # USA, certificate region 0x1, version 2, built 2002-10-01.
    "3ec95fe3ae9e7794d83a5b489ad8583f352e0c18":
        Release("us", "USA", ROOT / ".pipeline" / "us"),
}


def fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def run(argv) -> bool:
    print("\n> " + " ".join(str(a) for a in argv), flush=True)
    return subprocess.run([str(a) for a in argv]).returncode == 0


def xbe_entry_point(data: bytes) -> int:
    """The entry point, decoded with whichever XOR key puts it in the image
    (retail or debug), as tools.xbe_parser does."""
    base = int.from_bytes(data[0x104:0x108], "little")
    size = int.from_bytes(data[0x10C:0x110], "little")
    raw = int.from_bytes(data[0x128:0x12C], "little")
    for key in (0xA8FC57AB, 0x94859D4B):
        if base <= (raw ^ key) < base + size:
            return raw ^ key
    return raw ^ 0xA8FC57AB


def lifted_stamp(name: str):
    """A SHA-1 the last lift wrote into src/recomp/ts2_region.h, or None:
    TS2_XBE_SHA1, the default.xbe src/recomp/gen was lifted from (None when
    the lift predates releases, which was the PAL one, or there is none), or
    TS2_XBE_PATCHES_SHA1, the patch file it was lifted with (None: none)."""
    if not REGION_HEADER.is_file():
        return None
    m = re.search(r'#define %s\s+"([0-9a-f]{40})"' % name, REGION_HEADER.read_text())
    return m.group(1) if m else None


def write_region_header(release: Release, digest: str, entry: int, patches) -> None:
    REGION_HEADER.parent.mkdir(parents=True, exist_ok=True)
    REGION_HEADER.write_text(
        "/* Written by scripts/build.py when it lifted src/recomp/gen from the\n"
        " * default.xbe below: which release that was, for src/main.c and\n"
        " * src/recomp_manual.c. The two go together, so lift again to change it. */\n"
        "#ifndef TS2_REGION_H\n"
        "#define TS2_REGION_H\n"
        f"#define TS2_REGION_{release.region.upper()} 1\n"
        f'#define TS2_REGION_NAME "{release.name}"\n'
        f'#define TS2_XBE_SHA1 "{digest}"\n'
        f"#define TS2_ENTRY_POINT 0x{entry:08X}u\n"
        + (f"/* lifted with config/{release.region}/xbe_patches.json, this SHA-1 */\n"
           f'#define TS2_XBE_PATCHES_SHA1 "{patches}"\n' if patches else "")
        + "#endif\n")


def write_manual_scan(release: Release) -> Path:
    """What the lifter reads to learn which functions are written by hand.

    The toolkit scans one file, <project>/src/recomp_manual.c, as text: a
    function it defines is not generated, and one it wraps is generated as
    sub_X_gen (xboxrecomp tools/recomp/manual_scan.py). TimeSplitters 2's
    overrides are src/recomp_manual.c, which is the same for every release,
    plus config/<region>/overrides.inc, which names this release's functions
    and which src/recomp_manual.c includes. So the scan is given the two as
    one file, in a project folder of its own; the other releases' functions
    are never seen, so none of them can be excluded or wrapped by mistake.
    """
    parts = [ROOT / "src" / "recomp_manual.c",
             ROOT / "config" / release.region / "overrides.inc"]
    project = release.work_dir / "manual"
    out = project / "src" / "recomp_manual.c"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(
        f"/* ---- {p.relative_to(ROOT).as_posix()} ---- */\n"
        + p.read_text(encoding="utf-8") + "\n" for p in parts), encoding="utf-8")
    return project


def symbols_of(path: Path):
    import json
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("symbols")
    except (OSError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", default=str(ROOT / "game"),
                    help="folder holding default.xbe (default: game/)")
    ap.add_argument("--relift", action="store_true",
                    help="lift again even if generated sources exist")
    ap.add_argument("--from", dest="start", metavar="STAGE",
                    help="with --relift: start the pipeline at this stage "
                         "(parse, disasm, identify, lift)")
    ap.add_argument("--region", choices=sorted({r.region for r in RELEASES.values()}),
                    help="use this release's addresses for a default.xbe this "
                         "repository does not know (expect it to fail)")
    ap.add_argument("--no-build", action="store_true", help="lift only")
    ap.add_argument("--config", default="Release", help="build configuration")
    args = ap.parse_args()

    game = Path(args.game).resolve()
    xbe = game / "default.xbe"

    if not (TOOLKIT / "scripts" / "recompile.py").is_file():
        return fail("the xboxrecomp submodule is missing. Run: git submodule update --init")
    if not xbe.is_file():
        return fail(f"no default.xbe in {game}. Copy the extracted disc there "
                    f"(see README.md).")
    try:
        import capstone  # noqa: F401  (the toolkit's disassembler needs it)
    except ImportError:
        return fail("Python package 'capstone' is missing. Run: py -3 -m pip install capstone")
    if not shutil.which("cmake") and not args.no_build:
        return fail("cmake is not on PATH")
    # Linux distributions do not package DXC, the HLSL compiler the renderer
    # needs, and without it the build quietly has no renderer: a black
    # window. The toolkit fetches Microsoft's Linux release beside itself.
    if sys.platform.startswith("linux") and not args.no_build:
        sdk = os.environ.get("VULKAN_SDK", "")
        dxc_found = ((TOOLKIT / "third_party" / "dxc" / "include" / "dxc" / "dxcapi.h").is_file()
                     or (sdk and (Path(sdk) / "include" / "dxc" / "dxcapi.h").is_file()))
        if not dxc_found:
            return fail("DXC (the shader compiler) is missing, and without it the game "
                        "has no picture.\n       Run: bash xboxrecomp/tools/linux/fetch_dxc.sh")

    # config/<region>/ holds addresses inside one particular default.xbe.
    # Another release puts its functions elsewhere, and lifting it with the
    # wrong release's seeds, symbols and overrides replaces the wrong
    # functions in silence, so an unknown file is refused unless asked for.
    data = xbe.read_bytes()
    digest = hashlib.sha1(data).hexdigest()
    release = RELEASES.get(digest)
    if release is None:
        known = "\n".join(f"           {r.name:4s} {h}" for h, r in RELEASES.items())
        if not args.region:
            return fail(f"this default.xbe (SHA-1 {digest}) is not a release this\n"
                        f"       repository has addresses for:\n{known}\n"
                        f"       Please open an issue with the SHA-1. --region pal|us "
                        f"lifts it with one\n       of those releases' addresses "
                        f"anyway, which will most likely not work.")
        release = next(r for r in RELEASES.values() if r.region == args.region)
        print(f"warning: this default.xbe (SHA-1 {digest}) is not one this repository\n"
              f"         was made for; lifting it with the {release.name} addresses "
              f"(--region {release.region}).", file=sys.stderr)
    else:
        print(f"TimeSplitters 2, {release.name} release (default.xbe SHA-1 {digest})")
    config = ROOT / "config" / release.region
    # The release's XBE patches, if it has any (PAL: the roster grown for
    # added characters). They change the image that is lifted, so the lift
    # records the file's SHA-1, and a changed file means lifting again.
    patch_file = config / "xbe_patches.json"
    patches = (hashlib.sha1(patch_file.read_bytes()).hexdigest()
               if patch_file.is_file() else None)

    # The toolkit lifts D3D8 replacements only when <xbe>_xdk_symbols.json
    # sits beside the XBE, and says nothing when it does not. This repository
    # carries the file so nobody has to build XbSymbolDatabase to make it.
    # One left there for another release would place the replacements at
    # that release's addresses, so it is replaced when its symbols differ.
    symbols = game / "default_xdk_symbols.json"
    wanted = config / "xdk_symbols.json"
    if not symbols.is_file():
        shutil.copyfile(wanted, symbols)
        print(f"copied {wanted.relative_to(ROOT).as_posix()} to {symbols}")
    elif symbols_of(symbols) != symbols_of(wanted):
        shutil.copyfile(wanted, symbols)
        print(f"replaced {symbols}: it was not the {release.name} release's "
              f"(now {wanted.relative_to(ROOT).as_posix()})")

    # The generated sources belong to the default.xbe they were lifted from.
    # A lift from before releases were told apart was of the PAL one.
    lifted = GEN.is_dir() and any(GEN.glob("*.c"))
    relift = args.relift or not lifted
    before = lifted_stamp("TS2_XBE_SHA1")
    if lifted and not relift:
        if before is None and release.region == "pal" and not patches:
            write_region_header(release, digest, xbe_entry_point(data), None)
        elif before != digest:
            print(f"the generated sources were lifted from another default.xbe; "
                  f"lifting the {release.name} one")
            relift = True
            args.start = None
        elif lifted_stamp("TS2_XBE_PATCHES_SHA1") != patches:
            # The toolkit sees the changed image and starts again from parse.
            print(f"config/{release.region}/xbe_patches.json is not what the "
                  f"generated sources were lifted with; lifting again")
            relift = True

    if relift:
        REGION_HEADER.unlink(missing_ok=True)
        lift = [sys.executable, TOOLKIT / "scripts" / "recompile.py", xbe,
                "--work-dir", release.work_dir,
                "--project", write_manual_scan(release),
                "--gen-dir", GEN,
                "--seeds", config / "seeds.json"]
        # Always one or the other: without either, recompile.py would look
        # for config/xbe_patches/4553000A.json, which cannot say which
        # release it is for.
        lift += (["--xbe-patches", patch_file] if patches else ["--no-xbe-patches"])
        if args.start:
            lift += ["--from", args.start]
        if not run(lift):
            return fail("the lift failed; see the output above")
        write_region_header(release, digest, xbe_entry_point(data), patches)
    else:
        print("generated sources exist; skipping the lift (--relift to redo it)")

    if args.no_build:
        return 0

    if os.name == "nt":
        build = BUILD
        exe = BUILD / args.config / "split2_recomp.exe"
    else:
        # Ninja is single-configuration, so each configuration gets a folder
        # of its own: the executable lands in build/<config>/ as Visual
        # Studio's does, and the game paths in src/main.c hold on both.
        build = BUILD / args.config
        exe = build / "split2_recomp"

    if not (build / "CMakeCache.txt").is_file():
        configure = ["cmake", "-S", ROOT, "-B", build]
        if os.name != "nt":
            if not os.environ.get("CMAKE_GENERATOR"):
                configure += ["-G", "Ninja"]
            configure += [f"-DCMAKE_BUILD_TYPE={args.config}"]
        elif not os.environ.get("CMAKE_GENERATOR"):
            configure += ["-A", "x64"]
        if not run(configure):
            return fail("cmake configure failed")
    if not run(["cmake", "--build", build, "--config", args.config]):
        return fail("the build failed")

    print(f"\nbuilt {exe}")
    launcher = exe.with_name("split2_recomp_launcher" + (".exe" if os.name == "nt" else ""))
    if launcher.is_file():
        print(f"settings window: {launcher}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
