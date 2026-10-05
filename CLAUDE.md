# split2-recomp — working context

TimeSplitters 2 (Xbox), statically recompiled on the xboxrecomp toolkit, which
is the submodule in `xboxrecomp/`. This repository exists to make **this one
game** better than it was on the console. The toolkit exists to make every
game work. Most of the judgement in this repo is deciding which of the two a
change belongs in.

Read `xboxrecomp/CLAUDE.md` too. It holds the toolkit's architecture, its debug
table (`stderr shows` → cause) and its switches. This file does not repeat them.

---

## Toolkit or here?

The rule: **if a change contains no fact about TimeSplitters 2, it belongs in
xboxrecomp.** A new D3D8 replacement, a kernel call, a lifter fix, a renderer
feature and a settings option are all toolkit work, even when TS2 is the game
that found them. Here: TS2's overrides, seeds, symbols, per-game patches and
defaults, and tools for its own formats.

`xboxrecomp/docs/technical/xbox-game-enhancements.md` makes this split for each
planned enhancement. TS2's share of it:

| Enhancement | TS2's part |
| --- | --- |
| Widescreen | Done: the in-game camera is widened where it is built (`sub_00032DC0`), and the front end and HUD are placed by call site (`k_ts2_ui_places` in `src/overrides/ui_placement_table.c`). Leftovers are in `docs/enhancements.md` |
| Frame rate above 60 | Done by presenting above it: the toolkit's frame interpolation (`frame_interp`) draws the in-between frames while logic stays at 60. TS2 names its matrix registers (c60 projection, c64-c75) at its first present, `sub_001CC530` in `src/overrides/camera_and_present.c`. Leftovers are in `docs/enhancements.md` |
| Online play | TS2 has system link (LAN) and no Xbox Live. Once the toolkit tunnels system link, little should be left to do here |
| Mods | The toolkit's mods folder overlays disc files and its patch files change table values; this repo has the `.pak` and `.xbt` tools (`tools/`) and `docs/modding.md`. Still to do here: find TS2's tuning tables in `default.xbe` and name them in `src/ts2/ts2_types.h` |
| Cutscene skip | In-engine cutscenes: find where they start and whether the game already has a skip |

**Working on the toolkit from here:** make the change in `xboxrecomp/` on a
branch, commit and push it **there** (`origin` is phobos665/xboxrecomp), then
commit the new submodule pin here. Never leave this repo pinned to a toolkit
commit that exists only on this machine. `main` pins the toolkit's `main`
(which has absorbed `feat/outrun2`'s movie and XGRA work); feature branches here
pin the toolkit branch of the same work.

---

## The title

| | |
| --- | --- |
| Title ID | `4553000A` |
| Release | PAL, certificate region 0x4, version 2. `default.xbe` SHA-1 `2809eb147385723eaa90c425be89ee4db033fc5a` |
| XDK | 4721, plain D3D8 (not LTCG) |
| Entry point | `0x001CF3C9` |
| Saves | `game/UDATA/4553000a/` |
| Settings file | `%APPDATA%\xboxrecomp\titles\4553000A.conf` |

`config/seeds.json` and `config/xdk_symbols.json` are addresses in that exact
XBE. Another region needs its own copies.

State (Sep 2026): the front end and story mode play (Siberia), 5 ms a frame,
60 fps under the adaptive cap. There are no unresolved indirect calls. It has
no XMV movies. The toolkit's history with this game is in
`xboxrecomp/docs/technical/second-title-bringup.md`,
`ts2-performance-plan.md`, `resolution-and-framerate.md` and
`modding-models-textures.md`.

One open issue: in one run out of two or three, the game has exited with code
`0xFFFFFFFF` with no fault and no kernel call. `[EXIT]` lines in the log (the
toolkit's exit trace) name the caller if it happens again.

---

## Layout

```text
CMakeLists.txt          the executable and the launcher, on top of xboxrecomp
scripts/build.py        lift (first time or --relift), then configure and build
src/main.c              the host entry point, from xboxrecomp/templates/new-game
src/recomp_manual.c     recomp_lookup_manual and the ICALL diagnostics (toolkit template)
src/overrides/          the game's overrides of lifted functions, one subsystem a file
src/ts2/                headers the overrides share (guest registers, memory, UI types)
mods/                   a mod folder for testing: files overlay the disc  (ignored)
tools/                  TS2 format tools: .pak archives, .xbt textures
config/seeds.json       function entry points discovery cannot see
config/xdk_symbols.json XDK function names in this XBE (for the D3D8 replacements)
game/                   the disc, supplied by the user        (ignored)
src/recomp/gen/         the lifted C, i.e. game code           (ignored)
.pipeline/              disasm, func_id and recomp stage output (ignored)
build/                  CMake build; the exe is build/Release/split2_recomp.exe
```

**Never commit `game/` or `src/recomp/`, and never paste lifted code into a
committed file.** Lifted C is the game's code. Addresses, names and hand-written
overrides are fine.

---

## Commands

```bash
py -3 scripts/build.py                        # lift if needed, then build
py -3 scripts/build.py --relift               # after changing seeds, symbols, overrides or the toolkit
py -3 scripts/build.py --relift --from disasm # new seeds are applied by the disassembler, so start there
cmake --build build --config Release          # recompile only
```

A run for testing. **Always muted** (`RECOMP_MUTE=1`), always time-limited. The
input script walks a fresh save to Siberia:

```bash
cd build/Release
RECOMP_MUTE=1 RECOMP_FPS=5 \
RECOMP_INPUT_SEQ="12000:start,16000:start,20000:start,24000:start,28000:a,34000:a,40000:a,46000:a,52000:a,58000:a,64000:a,70000:a" \
timeout 90 ./split2_recomp.exe 2> run.log
```

An existing save changes the menu path ("overwrite?"), so the script only lands
on a fresh save. Move `game/UDATA/4553000a` aside for a scripted run, and put it
back afterwards: it may be the user's.

`xboxrecomp/scripts/run_and_report.py <exe> --seconds 60` runs and summarises a
run in the same way. See the toolkit's CLAUDE.md for frame dumps
(`RECOMP_HLE_D3D8_DUMP*`), captures (F11, `RECOMP_D3D8_CAPTURE`) and the
watchpoint switches.

---

## Overrides and seeds

- A lifted function is replaced in `src/overrides/`, in the file for its
  subsystem (a new subsystem gets a new file; CMake globs the folder). The
  lifter scans that folder and `src/recomp_manual.c` together
  (`--exclude-manual`, which `recompile.py` passes for both) and does not
  generate what they define. One definition per function: a second is reported
  by name at lift time and is a duplicate symbol at link. Overrides include
  `ts2/ts2_guest.h` for the guest registers and memory. **Write the reason
  beside every override when you add it.**
- `src/recomp_manual.c` keeps `recomp_lookup_manual` and the ICALL diagnostics
  from the toolkit template; TS2's own code does not go there.
- Tuning that is a number in one of the game's tables is a patch file, not an
  override: `mods/patches/*.json` (xboxrecomp `src/kernel/mod_patches.h`).
  See `docs/modding.md`.
- A new unresolved `[ICALL]` target becomes a seed:
  `py -3 -m tools.seed_from_log <log> <xbe> --functions ../.pipeline/disasm/functions.json --seeds ../config/seeds.json`,
  run from `xboxrecomp/`. Then rebuild with `--relift --from disasm`.
- `src/main.c` is a copy of the toolkit template with three defines changed
  (entry point, game paths). When the template changes upstream, bring the change
  across by hand and keep those three defines.
