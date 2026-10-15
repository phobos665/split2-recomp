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
| Widescreen | Done: the in-game camera is widened where it is built (`ts2_camera_setup` in `src/recomp_manual.c`), and the front end and HUD are placed by call site (each release's `k_ts2_ui_places`, in `config/<region>/overrides.inc`). Every screen is laid out for 16:9 |
| Frame rate above 60 | Done by presenting above it: the toolkit's frame interpolation (`frame_interp`) draws the in-between frames while logic stays at 60. TS2 names its matrix registers (c60 projection, c64-c75) at its first present (`ts2_present` in `src/recomp_manual.c`). Leftovers are in `docs/enhancements.md` |
| Online play | TS2 has System Link (LAN) and no Xbox Live. Done on Windows: the toolkit emulates the network card and hosts sessions over a LAN or the internet, and TS2 needed one seed (`0x0009D530`, PAL). macOS waits on the toolkit's card; USA is untried. `docs/multiplayer.md` |
| Mods | Assets are in `data/*.pak`. Naming dumped textures by pak entry is this repo's job; the dump and replace is the toolkit's. Characters a mod adds (PAL): `ts2/characters.ini` in the mod, read by `src/recomp_manual.c`, into 32 spare roster slots that `config/pal/xbe_patches.json` makes; `tools/ts2kitbash.py` builds one from a recipe (`docs/formats/roster.md`, "Adding a character (mods)"). Mods stack (`RECOMP_MODS=a:b`): loose files from inside the paks (`files/`, `paks/<pak>/`) are served at run time from every mod (`ts2_paks_*`, hooked where a pak is mounted and read) and every `characters.ini` is merged; `docs/modding.md` |
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
| Title ID | `4553000A`, the same in every release |
| Releases | PAL: certificate region 0x4, version 2, `default.xbe` SHA-1 `2809eb147385723eaa90c425be89ee4db033fc5a`. USA: certificate region 0x1, version 2, built 2002-10-01, SHA-1 `3ec95fe3ae9e7794d83a5b489ad8583f352e0c18` |
| XDK | 4721, plain D3D8 (not LTCG), every library, in both |
| Entry point | `0x001CF3C9` (PAL), `0x001CEF99` (USA) |
| Saves | `game/UDATA/4553000a/` |
| Settings file | `%APPDATA%\xboxrecomp\titles\4553000A.conf` |

`config/<region>/` (`pal`, `us`) holds the addresses in one exact XBE: its
`seeds.json`, `xdk_symbols.json` and `overrides.inc` (the functions
`src/recomp_manual.c` attaches to). `scripts/build.py` picks the folder by the
XBE's SHA-1 and writes which release it lifted beside the lifted code
(`src/recomp/ts2_region.h`). Another release needs a folder of its own, found
function by function: the USA code is the PAL code moved by a different amount
in each stretch of `.text` (0 to -0x450), so no one shift carries an address over.

The title ID cannot tell the releases apart, and the toolkit's per-title files
are keyed by it: `xboxrecomp/config/seeds/4553000A.json` holds the PAL seeds, and
`recompile.py` and `tools.seed_from_log` fall back to it when `--seeds` is not
given. Always pass `--seeds ../config/<region>/seeds.json`.

State (Sep 2026): the front end and story mode play (Siberia), 5 ms a frame,
60 fps under the adaptive cap. There are no unresolved indirect calls. It has
no XMV movies. The toolkit's history with this game is in
`xboxrecomp/docs/technical/second-title-bringup.md`,
`ts2-performance-plan.md`, `resolution-and-framerate.md` and
`modding-models-textures.md`.

USA (Oct 2026): driven by an input script it goes through the front end, saves
a profile and plays the start of Siberia (picks up a weapon, opens the pause
menu) at 60 fps with no unresolved indirect calls. Every PAL override is ported
(`config/us/overrides.inc`), and widescreen (camera, 71 of the 93 placement
sites seen drawing) and frame interpolation were checked in captures. It has
not been played by hand yet, nor past the start of Siberia, and System Link
has not been opened in it.

macOS (Oct 2026): the PAL release builds natively on Apple Silicon (Vulkan
through MoltenVK) and a scripted run plays to Siberia at 60 fps with no
unresolved indirect calls. System Link is Windows-only: the toolkit's network
card is not built off Windows yet.

One open issue: in one run out of two or three, the game has exited with code
`0xFFFFFFFF` with no fault and no kernel call. `[EXIT]` lines in the log (the
toolkit's exit trace) name the caller if it happens again.

---

## Layout

```text
CMakeLists.txt          the executable and the launcher, on top of xboxrecomp
scripts/build.py        lift (first time or --relift), then configure and build
src/main.c              the host entry point, from xboxrecomp/templates/new-game
src/recomp_manual.c     hand-written overrides of lifted functions, the same for every release
config/<region>/        one release's addresses (pal, us):
  seeds.json            function entry points discovery cannot see
  xdk_symbols.json      XDK function names in that XBE (for the D3D8 replacements)
  overrides.inc         the functions recomp_manual.c wraps, by address, and its UI placement table
  xbe_patches.json      PAL only: changes to the XBE made before the lift (the roster grown)
game/                   the disc, supplied by the user        (ignored)
private/                local mod work that is not ours to publish (ignored; docs/modding.md)
src/recomp/gen/         the lifted C, i.e. game code           (ignored)
src/recomp/ts2_region.h which release was lifted, written by build.py (ignored)
.pipeline/              disasm, func_id and recomp stage output: PAL's, and USA's in .pipeline/us (ignored)
build/                  CMake build; the exe is build/Release/split2_recomp.exe (macOS: build/Release/split2_recomp)
```

**Never commit `game/` or `src/recomp/`, and never paste lifted code into a
committed file.** Lifted C is the game's code. Addresses, names and hand-written
overrides are fine.

---

## Commands

```bash
py -3 scripts/build.py                        # lift if needed, then build
py -3 scripts/build.py --relift               # after changing seeds, symbols, recomp_manual.c or the toolkit
py -3 scripts/build.py --relift --from disasm # new seeds are applied by the disassembler, so start there
                                              # (a changed xbe_patches.json sends it back to parse)
cmake --build build --config Release          # recompile only
```

On macOS (Apple Silicon) use `python3` from a venv with `capstone` (Homebrew's
Python refuses global installs), Homebrew's CMake, Ninja and OpenSSL, and the
LunarG Vulkan SDK; `build.py` configures Ninja in `build/Release/`, so recompile
with `cmake --build build/Release` and the executable is
`build/Release/split2_recomp`, with the launcher beside it
(`split2_recomp_launcher`, SDL3 and CoreText since xboxrecomp #67).

A run for testing. **Always muted** (`RECOMP_MUTE=1`), always time-limited. The
input script walks a fresh save to Siberia:

```bash
cd build/Release
RECOMP_MUTE=1 RECOMP_FPS=5 \
RECOMP_INPUT_SEQ="12000:start,16000:start,20000:start,24000:start,28000:a,34000:a,40000:a,46000:a,52000:a,58000:a,64000:a,70000:a" \
timeout 90 ./split2_recomp.exe 2> run.log      # macOS: ./split2_recomp (timeout from coreutils)
```

An existing save changes the menu path ("overwrite?"), so the script only lands
on a fresh save. Move `game/UDATA/4553000a` aside for a scripted run, and put it
back afterwards: it may be the user's. Or leave it alone and run from a copy of
the game folder without `UDATA` (`RECOMP_GAME_DIR=<copy>`, made with `cp -c` on
macOS, which costs nothing), with `RECOMP_SAVE_DIR=<fresh folder>` and
`RECOMP_WINDOW_BACKGROUND=1` so the run neither touches saves nor takes focus.

`xboxrecomp/scripts/run_and_report.py <exe> --seconds 60` runs and summarises a
run in the same way. See the toolkit's CLAUDE.md for frame dumps
(`RECOMP_HLE_D3D8_DUMP*`), captures (F11, `RECOMP_D3D8_CAPTURE`) and the
watchpoint switches.

---

## Overrides and seeds

- `src/recomp_manual.c` is the one place a lifted function is replaced. The
  lifter reads it (`--exclude-manual`) and does not generate what it defines, so
  a second override file gives duplicate symbols. **Write the reason beside every
  override when you add it.** What is the same in every release is written there,
  as a hook; where it attaches is in each release's `config/<region>/overrides.inc`,
  which it includes. The lifter reads only one file, as text, so `build.py` hands it
  the two as one (`.pipeline/.../manual/src/recomp_manual.c`): lift through
  `build.py`, not `recompile.py` directly.
- `config/<region>/xbe_patches.json`, when the release has one, is applied to
  the XBE before it is disassembled (xboxrecomp
  `docs/technical/xbe-patches.md`); the player's `default.xbe` is only read
  and the runtime patches its copy in memory. `build.py` passes it (USA:
  `--no-xbe-patches`) and stamps its SHA-1 into `src/recomp/ts2_region.h`, so
  a changed file is relifted. PAL's grows the character roster by 32 spare
  slots; it is written by `tools/ts2_roster_patches.py`, and every site has
  its reason in the file (`docs/formats/roster.md`, "Room for more
  characters"). A patch may change operands, never an instruction's length:
  what does not fit is hooked in `recomp_manual.c`. Write the reason beside
  every patch, as beside every override.
- A new unresolved `[ICALL]` target becomes a seed:
  `py -3 -m tools.seed_from_log <log> <xbe> --functions ../.pipeline/disasm/functions.json --seeds ../config/pal/seeds.json`
  (USA: `../.pipeline/us/disasm/functions.json`, `../config/us/seeds.json`),
  run from `xboxrecomp/`. Then rebuild with `--relift --from disasm`.
- `src/main.c` is a copy of the toolkit template with three defines changed
  (entry point, game paths). When the template changes upstream, bring the change
  across by hand and keep those three defines.
