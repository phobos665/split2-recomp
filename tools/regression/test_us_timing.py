"""Run the US timing fixtures against a built Linux Ninja Release.

From the repository root, run python tools/regression/test_us_timing.py.
Uses game/default.xbe and the generated objects from scripts/build.py --region us.
"""

import hashlib
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "xboxrecomp"))
from tools.abi_analysis.xbe_min import XbeFile


def run_fixture(scratch):
    build = ROOT / "build/Release"
    xbe = XbeFile(ROOT / "game/default.xbe")
    if hashlib.sha1(xbe.data).hexdigest() != "3ec95fe3ae9e7794d83a5b489ad8583f352e0c18":
        raise ValueError("The fixture requires the supported US default.xbe")

    memory = bytearray(4 << 20)
    for section in xbe.sections:
        start = section.virtual_address
        size = min(section.raw_size, len(memory) - start)
        if size > 0:
            memory[start:start + size] = xbe.data[
                section.raw_address:section.raw_address + size
            ]
    guest_image = scratch / "tables.bin"
    guest_image.write_bytes(memory)

    commands = subprocess.check_output(
        ["ninja", "-t", "commands", "split2_recomp"], cwd=build, text=True
    ).splitlines()
    manual = ROOT / "src/recomp_manual.c"
    compile_args = shlex.split(
        next(line for line in commands if line.endswith(" -c " + str(manual)))
    )
    for flag, count in [("-MD", 1), ("-MT", 2), ("-MF", 2)]:
        if flag in compile_args:
            index = compile_args.index(flag)
            del compile_args[index:index + count]

    source = scratch / "manual.c"
    source.write_text(
        f'#include "{manual}"\n'
        "void fixture_free_step(int on) { g_ts2_us_free_step = on; }\n"
    )
    original_object = compile_args[compile_args.index("-o") + 1]
    test_object = str(scratch / "manual.o")
    compile_args[compile_args.index("-o") + 1] = test_object
    compile_args[compile_args.index("-c") + 1] = str(source)
    subprocess.run(compile_args, cwd=build, check=True)

    fixture = str(scratch / "cases.o")
    subprocess.run(
        [
            compile_args[0],
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I" + str(ROOT / "src/recomp/gen"),
            "-c",
            str(Path(__file__).with_name("us_timing.c")),
            "-o",
            fixture,
        ],
        check=True,
    )
    link = shlex.split(commands[-1])
    if link[:2] != [":", "&&"] or link[-2:] != ["&&", ":"]:
        raise ValueError("Unrecognized CMake Ninja link command")
    link = [arg for arg in link[2:-2] if not arg.startswith("-Wl,--dependency-file=")]
    link[link.index(original_object)] = test_object
    executable = str(scratch / "check")
    link[link.index("-o") + 1] = executable
    link[1:1] = ["-Wl,--wrap=main", fixture]
    subprocess.run(link, cwd=build, check=True)
    subprocess.run([executable, str(guest_image)], cwd=scratch, check=True)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        run_fixture(Path(directory))
