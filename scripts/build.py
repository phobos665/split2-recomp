"""Lift TimeSplitters 2 from your own copy of the game, then build it.

    py -3 scripts/build.py              lift (first time only), then build
    py -3 scripts/build.py --relift     lift again, e.g. after new seeds or a toolkit update
    py -3 scripts/build.py --no-build   lift only

The game's files go in game/ at the root of this repository (default.xbe and
the rest of the disc), or pass --game DIR.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLKIT = ROOT / "xboxrecomp"
GEN = ROOT / "src" / "recomp" / "gen"
BUILD = ROOT / "build"

# TimeSplitters 2, PAL (certificate region 0x4, version 2), title 4553000A.
SUPPORTED_XBE_SHA1 = "2809eb147385723eaa90c425be89ee4db033fc5a"


def fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def run(argv) -> bool:
    print("\n> " + " ".join(str(a) for a in argv), flush=True)
    return subprocess.run([str(a) for a in argv]).returncode == 0


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

    # config/ holds addresses inside one particular default.xbe. Another
    # region or revision puts its functions elsewhere, so warn rather than
    # lift it with the wrong seeds and symbols in silence.
    digest = hashlib.sha1(xbe.read_bytes()).hexdigest()
    if digest != SUPPORTED_XBE_SHA1:
        print(f"warning: this default.xbe (SHA-1 {digest}) is not the one this "
              f"repository was made for\n         (the PAL release, SHA-1 "
              f"{SUPPORTED_XBE_SHA1}). config/seeds.json and\n"
              f"         config/xdk_symbols.json are addresses in that file and "
              f"may be wrong for yours.", file=sys.stderr)

    # The toolkit lifts D3D8 replacements only when <xbe>_xdk_symbols.json
    # sits beside the XBE, and says nothing when it does not. This repository
    # carries the file so nobody has to build XbSymbolDatabase to make it.
    symbols = game / "default_xdk_symbols.json"
    if not symbols.is_file():
        shutil.copyfile(ROOT / "config" / "xdk_symbols.json", symbols)
        print(f"copied config/xdk_symbols.json to {symbols}")

    lifted = GEN.is_dir() and any(GEN.glob("*.c"))
    if args.relift or not lifted:
        lift = [sys.executable, TOOLKIT / "scripts" / "recompile.py", xbe,
                "--work-dir", ROOT / ".pipeline",
                "--project", ROOT,
                "--seeds", ROOT / "config" / "seeds.json"]
        if args.start:
            lift += ["--from", args.start]
        if not run(lift):
            return fail("the lift failed; see the output above")
    else:
        print("generated sources exist; skipping the lift (--relift to redo it)")

    if args.no_build:
        return 0

    if not (BUILD / "CMakeCache.txt").is_file():
        configure = ["cmake", "-S", ROOT, "-B", BUILD]
        if not os.environ.get("CMAKE_GENERATOR"):
            configure += ["-A", "x64"]
        if not run(configure):
            return fail("cmake configure failed")
    if not run(["cmake", "--build", BUILD, "--config", args.config]):
        return fail("the build failed")

    exe = BUILD / args.config / "split2_recomp.exe"
    print(f"\nbuilt {exe}")
    print(f"settings window: {exe.with_name('split2_recomp_launcher.exe')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
