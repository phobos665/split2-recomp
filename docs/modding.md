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

- **`.pak`**: `tools/ts2pak.py` describes both layouts. All 68 archives on
  the PAL disc (23 `P4CK`, 45 `P8CK`) rebuild byte-identical through
  `py -3 -m tools.ts2pak verify` (6 Oct 2026). Run it again on another
  release before trusting `pack` there.
- **`.xbt`**: `tools/xbt.py` describes it. The header gives the stored size,
  the shown size, the mip count and the format. All 19,180 textures in the
  archives (4,393 distinct) fit that exactly, and every one comes back
  byte-identical through DDS and `from-dds` (6 Oct 2026). Formats 0-2 (DXT1,
  DXT3, swizzled ARGB) are all the disc uses; format 3 never occurs and is a
  guess. 96 textures are shown smaller than they are stored (128x192 stored
  as 128x256); in their DDS the picture is the top-left corner. `from-dds`
  keeps every header word it does not understand from the original, and
  refuses a different stored size, format or number of mip levels unless
  told otherwise.
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

Checked on the PC with the PAL disc, 6 Oct 2026:

1. **Relift and build**: the lifter read `src/recomp_manual.c` and
   `src/overrides/` together, wrapped the same 33 functions as before the
   split, and the build linked with no duplicate or unresolved symbols.
2. **Scripted run to Siberia** (muted, fresh saves, 95 s): reached
   `story\l_35_ST.pak` at a steady 60 fps (58.5 mean including loads), no
   faults, no unresolved indirect calls, the 93-entry 2D placement table
   loaded. **Still to do: look at it.** Widescreen, the HUD and frame
   interpolation have only been checked by the log, not by eye.
3. **Archives**: all 68 rebuild byte-identical. `arcade/l_106.pak` did not
   at first -- a zero-length entry at the same offset as a 2 MB one -- and
   `ts2pak` is fixed for it.
4. **Textures**: all 19,180 parse; the header layout is now known (see "The
   formats" above) and every distinct texture round-trips through DDS.
5. **A texture mod end to end**: button 1 (`xbstdbutton1.xbt`, the B
   prompt) recoloured magenta in `arcade/l_103.pak` and `l_101.pak`, dropped
   in `build/Release/mods/data/arcade/`. The log showed `[MODS]` for both,
   frame captures of the front end held the magenta texture and not the
   original, and a replayed frame showed the Select Profile screen's Back
   prompt in magenta.
6. **Toolkit tests under MSVC**: `kernel_path_mods`, `mod_patches` and
   `mod_patches_runtime` pass.

What the mod test showed about the game:

- **Every level archive carries its own copy of shared textures.** The
  button is in 43 archives; once the run loaded archives the mod had not
  replaced, the original came back. A texture mod by archive has to rebuild
  every archive that holds the texture. The toolkit's planned hashed texture
  replacement (`xboxrecomp/docs/technical/modding-models-textures.md`, T4/T5)
  would need one file.
- **The game looks for `data\xbt.pak`, `data\xbob.pak` and
  `data\xbsound.pak`, which are not on the disc**, and carries on without
  them. If they are override archives the game itself supports (textures,
  objects, sounds), a mod could ship just one of them. Not tested yet.

Next: test whether `data\xbt.pak` overrides textures; then the work that
needs `default.xbe` -- find the tuning tables (weapons first) and name what
is found in `ts2_types.h`.
