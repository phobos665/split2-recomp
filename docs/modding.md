# Modding TimeSplitters 2

Three ways to change the game, from least to most work. Use the first one
that can do what you want.

| You want to change | Use | Needs a rebuild |
| --- | --- | --- |
| A file the game loads (a texture, a model, a sound, a level) | the **mods folder** | no |
| A number in one of the game's tables (damage, speed, a timer) | a **patch file** in the mods folder | no |
| What the game does | an **override** in `src/overrides/` | yes |

None of them edit the game you extracted to `game/`. Remove the mods folder and
you have the original game back.

---

## The mods folder

A file at `mods/<path>` replaces the disc file at `game/<path>`. The folder is
`mods` beside the executable (`build/Release/mods/`), or wherever
`RECOMP_MODS_DIR` points; `RECOMP_MODS_DIR=off` switches it off. The log says
which folder it found and every file it answered:

```text
[MODS] overlay C:\...\build\Release\mods (beside the executable)
  [MODS] \Device\CdRom0\data\chr.pak -> C:\...\mods\data\chr.pak
```

Only files the game reads from the disc are overlaid, never saves. A folder in
`mods/` does not replace one on the disc, and a file the game would only find by
listing a folder is not seen. Mods replace files the game opens by name.

TimeSplitters 2 keeps almost everything in archives under `data/` (`chr.pak`,
`gun.pak`, `l_100.pak`, ...) and opens whole archives. So a mod that changes one
texture is a rebuilt archive:

```bash
py -3 -m tools.ts2pak unpack game/data/chr.pak work/chr
py -3 -m tools.xbt to-dds work/chr/textures/0267.xbt work/0267.dds
#   ... edit work/0267.dds in any editor that saves DXT1/DXT3/A8R8G8B8 DDS ...
mkdir -p work/chr_edit/textures
py -3 -m tools.xbt from-dds work/0267.dds work/chr/textures/0267.xbt \
      -o work/chr_edit/textures/0267.xbt
py -3 -m tools.ts2pak pack game/data/chr.pak work/chr_edit -o build/Release/mods/data/chr.pak
```

`pack` takes the original archive and a folder of replacements named by their
path inside the archive. Everything not in the folder is copied. To pack a whole
unpacked folder after editing a few files in place, add `--only-changed`.

To find which archive and file a texture you can see in the game comes from,
`py -3 -m tools.xbt index game/data --csv textures.csv` lists every texture in
every archive with its size, format and a SHA-1 of its first mip level.

### The formats, and how sure we are

- **`.pak`**: `tools/ts2pak.py` describes both layouts. `P8CK` was checked
  against this disc. `P4CK` follows OpenRadical's `tspak`.
  `py -3 -m tools.ts2pak verify game/data/*.pak` rebuilds each archive with
  nothing changed and compares it byte for byte. **Run that once before
  trusting `pack`.**
- **`.xbt`**: `tools/xbt.py` describes it. The header size, the format field
  and where the texels start were checked against this disc. Formats 0-2
  (DXT1, DXT3, swizzled ARGB) come from OpenRadical's Noesis plugin. Format 3
  (raw 24-bit) is a guess. The mip count is worked out from the file size,
  because nobody knows which header word holds it. `from-dds` keeps every
  unknown header word from the original and refuses a different size, format
  or number of mip levels unless told otherwise.
- **`.xbr` models**: no tool yet. Swapping one model file for another works
  through the mods folder. Writing new geometry is unsolved anywhere (see
  `xboxrecomp/docs/technical/modding-models-textures.md`).

---

## Patch files

A file in `mods/patches/` changes values in the game's memory before it starts:

```json
{
  "title": "4553000A",
  "patches": [
    { "address": "0x0025A0F0", "type": "f32", "expect": 1.0, "value": 1.5,
      "note": "what this is, and how it was found" }
  ]
}
```

The types are `u8 u16 u32 i8 i16 i32 f32 f64` and `bytes` (a hex string). An
array writes consecutive values. If `expect` is given and does not match what
is in memory, the patch is skipped and the log says what it found, so a patch
written for another release of the game does nothing instead of corrupting
something. Files apply in name order. `"enabled": false` switches one patch off.

```text
[PATCH] weapons.json: 0x0025A0F0 <- 00 00 C0 3F
[PATCH] 1 applied, 0 skipped, 0 unreadable, from 1 file(s) in ...\mods\patches
```

Patches change **data, not behaviour**. Lifted code is compiled C, so changing
an instruction's bytes does nothing (the log warns if you try). A table the game
builds, or loads from a file, after start-up is not in memory yet when patches
apply; change the file through the mods folder instead. The format is defined
in `xboxrecomp/src/kernel/mod_patches.h`.

**There are no TS2 patches yet.** Finding the tables (weapon stats, character
stats, bot skill) means reading `default.xbe`. That is the next step on this
branch; see the end of this file.

---

## Overrides

An override replaces or wraps one of the game's lifted functions with
hand-written C. They live in `src/overrides/`, one subsystem to a file:

```text
src/overrides/camera_and_present.c   widescreen camera, wide frames, interpolation
src/overrides/ui_placement.c         2D placement by call site
src/overrides/ui_placement_table.c   ... its table
```

A new subsystem gets a new file; CMake picks it up, and the lifter scans the
folder so a function defined there is not generated. Rebuild with
`py -3 scripts/build.py --relift` after adding one.

Write overrides against `src/ts2/ts2_types.h`, which names what is known about
the game's functions and data:

```c
#include "ts2/ts2_guest.h"
#include "ts2/ts2_types.h"

extern void sub_00032DC0_gen(void);
void sub_00032DC0(void)          /* the in-game camera set-up */
{
    ts2_args(Ts2CameraSetupArgs)->aspect *= widen;
    sub_00032DC0_gen();          /* then the game's own body */
}
```

When you work out what a function or a structure field is, add it to
`ts2_types.h` with where you found it. The names are ours, not the game's, and
the file says so. Never paste lifted code (`src/recomp/gen/`) into a committed
file.

---

## Status of this branch (`feat/ts2-disassembly`)

Built and tested without the game, in a Linux container with no Windows
build:

- Toolkit (xboxrecomp `feat/ts2-disassembly`): the override folder in the
  lifter, the mods folder and patch files in the runtime. Each has a test that
  needs no game files, and the C ones pass on Linux and, built with MinGW,
  under Wine.
- Here: the overrides split into `src/overrides/` (the lifter sees the same 33
  functions as before), `ts2_types.h`, and the two format tools (23 tests).

**Not yet done on a real machine.** The first session on the PC:

1. `git submodule update --init` and `py -3 scripts/build.py --relift`. The
   override split changes what the lifter is given, so this is the real test:
   it must build with no duplicate or unresolved `sub_` symbols.
2. Play to Siberia with the usual input script. Widescreen, the HUD
   placement and frame interpolation must look exactly as they did on `main`.
3. `py -3 -m tools.ts2pak verify game/data/*.pak game/data/*/*.pak`: every
   archive must rebuild identically. A `FAIL` means a layout assumption is
   wrong; keep the output.
4. `py -3 -m tools.xbt index game/data --csv textures.csv`, then
   `py -3 -m tools.xbt info` on a few textures. Check that no texture reports
   leftover bytes and that formats 0-2 cover them all. The unknown header words
   it prints are what to compare next.
5. A texture mod end to end, as in the example above, with
   `build/Release/mods/data/chr.pak`. Look for the `[MODS]` line and the
   changed texture in game.
6. In xboxrecomp, `ctest` runs `kernel_path_mods`, `mod_patches` and
   `mod_patches_runtime` with MSVC as well.

Then the work that needs `default.xbe`: find the tuning tables (weapons first)
and name what is found in `ts2_types.h`.
