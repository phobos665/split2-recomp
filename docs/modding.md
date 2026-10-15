# Modding TimeSplitters 2's characters

How to change a character, make a new one and add it to the game. Everything
here starts from your own disc (`game/`), and every tool is in `tools/`. The
file formats are in `docs/formats/` (`xbr.md` models, `xbt.md` textures,
`roster.md` the roster and the game-side hooks).

PAL only so far. macOS is tested; Windows has not been built with these
changes yet.

## How a mod reaches the game

A mod is a folder of loose files. Run the game with one or several, earlier
ones first in priority (`;` between them on Windows):

```bash
cd build/Release
RECOMP_MODS=/path/to/modA:/path/to/modB:/path/to/modC ./split2_recomp
```

Every file the game reads is inside a `.pak`, so a mod holds files from
inside paks, by where they go:

```text
files/<path in a pak>              that file in every pak that holds it
paks/<pak>/<path in a pak>         that file in that one pak (added if the pak lacks it)
ts2/characters.ini                 characters the mod adds to the roster
data/<pak>                         optional: a whole pak, as on the disc
```

`paks/chr.pak/ob/chrs/chr71.xbr` is a model in `chr.pak`;
`paks/arcade/l_101.pak/textures/misc/chrimage_chr71.xbt` a portrait in the
front end's pak; `files/textures/0267.xbt` a texture everywhere it is used.
Every story and arcade level pak carries its own copy of the characters in
it, which is why `files/` exists: one file reaches all of them.

**Mods stack.** The game serves these files while it runs (PAL;
`ts2_paks_*` in `src/recomp_manual.c`): as it opens a pak it puts each mod's
files into that pak's directory, with their own sizes, and reads them from
the mod. For one name in one pak the first mod in `RECOMP_MODS` that has it
wins (a mod's `paks/<pak>/` before its `files/`), then the pak's own copy.
A name a pak does not have is added to it (`files/`: to every level, `chr`,
`gun` and `sounds` pak, so a new texture is found in any level). Every mod's
`ts2/characters.ini` is read, in order, and their characters are added
together (below). Mod folders are indexed once at start-up, and the log says
what each one gave each pak (`[TS2-MODS] data/chr.pak: 7 files from mods`;
`RECOMP_TS2_MODS_TRACE=1` lists them).

Conflicts are settled by order and reported, never fatal:

- Two mods with the same file for the same pak: the earlier one's is used,
  and if they differ the log names both (`[TS2-MODS] textures/8691.xbt: mod 0
  (...) and mod 3 (...) both supply it ...`). New texture ids are picked from
  a hash of the picture (8000-9999), so two mods' textures rarely meet; when
  they do, rebuild one of them.
- Two characters with the same chr id, or the same numbered `slot`: the
  earlier mod's is added and the later one skipped (`[TS2-CHR] ... chr id 70
  is already [Agent Static]'s (mod 0, ...); skipped`). `slot = next` takes
  the next free spare slot across all mods, up to the 32 there are.
- A whole `data/<pak>` is the toolkit's: the first mod that has one wins it
  entirely. Loose files from every mod still go on top of it.
- `textures/0478.xbt` is a different picture in `story/l_20_ST.pak` and
  `arcade/l_43_AR.pak` than in `chr.pak` (the one name on the disc with two
  contents). A `files/` entry replaces a pak's copy only where it is as long
  as `chr.pak`'s, so those two levels keep theirs; to change a clashing name
  there, use `paks/<that pak>/`.

`tools/ts2mod.py check modA modB modC` reports all of this before a run.

A mod made by the tools below is such a folder already. For a player who
wants one self-contained folder of rebuilt paks instead (no stacking:
whole paks), `ts2mod build` makes it:

```bash
python3 -I tools/ts2mod.py loose <source> <mod> --data game/data   # copy as it is, with mod.json
python3 -I tools/ts2mod.py build <source> game/data <mod>          # rebuilt data/*.pak
python3 -I tools/ts2mod.py check <mod> [<mod> ...]                 # overlaps between mods
```

`loose --data` also copies in the disc's textures that a model in the mod
names and a pak it goes into lacks (a body and a head from two characters,
in a level that carries only one of them). The USA release reads only whole
paks and the first `characters.ini` so far: its pak code has not been found.

## The tools

| Tool | What it does |
| --- | --- |
| `ts2pak.py` | list, unpack and repack `.pak` archives (byte-identical round trip) |
| `ts2xbt.py` | textures to and from PNG/DDS |
| `ts2xbr.py` | character models: parse, check, rewrite |
| `ts2gltf.py` | models to and from glTF (`gltf`, `fromgltf`), and `graft` pieces between characters |
| `ts2kitbash.py` | build whole characters from a recipe: model, preview, portrait, roster entry |
| `ts2mod.py` | `loose`: a mod folder of loose files (stacks); `build`: rebuilt paks in one folder; `check`: overlaps between mods; `where`: which paks hold a file |
| `blender/ts2_character` | Blender add-on: File > Import/Export > TimeSplitters 2 character |
| `blender/ts2_lowpoly.py` | build a low-poly character from boxes, on TS2's skeleton |
| `blender/ts2_portrait.py` | render a character-select portrait |

One-time setup: unpack the character pak and the bind pose (the skeleton's
joint positions) somewhere to work in:

```bash
python3 -I tools/ts2pak.py unpack game/data/chr.pak ~/TS2Modding/chr
python3 -I tools/ts2pak.py unpack game/data/fe_anim.pak ~/TS2Modding/fe_anim
python3 -I tools/blender/build_addon.py     # build/ts2_character-1.0.0.zip
```

Install the zip in Blender (Preferences > Get Extensions > the menu at the top
right > Install from Disk) and set its preferences: the bind pose folder
(`~/TS2Modding/fe_anim/anim/data/ts2`), textures (`~/TS2Modding/chr`) and a mod
source folder.

## Editing a character

1. File > Import > TimeSplitters 2 character, pick `ob/chrs/chrNN.xbr`.
2. Edit the meshes. Each object is one piece of the body and follows one
   bone; TS2 has no blend weights, so a vertex follows exactly one bone (a
   weight-painted mesh is snapped to its strongest allowed bone).
3. Sidebar > TS2 > Write into mod folder.
4. Run with `RECOMP_MODS=<mod folder>`: the add-on writes `files/`, which the
   game reads as it is (or `ts2mod loose --data game/data` first, when the
   model takes pieces from another character).

`chrNNlod2.xbr` is the same character far away, a separate model: edit it too
or the change disappears at a distance. The character-select preview is
`chrinc.pak`'s `ob/chrincs/chrNN.xbr`.

## Making a new character

New characters take the files of a character id nobody plays (the NeoTokyo
pedestrians, `chr71`-`chr90`, are in no arcade pak) and a spare roster slot
(the build adds 32). There are three ways to make the model.

**From two existing characters.** One's body, the other's head, recoloured: a
recipe entry for `ts2kitbash.py`. `tools/examples/characters.json` builds
three (Agent Static, The Bone Ranger, Monkey Business):

```json
{"name": "Agent Static", "slot": "chr71", "chr_id": 70,
 "body": "chr69", "head": "chr133",
 "recolour": {"475": {"hue": 0.48, "sat": 0.85, "light": 1.25}},
 "portrait_colour": [0.1, 0.75, 0.7],
 "roster": "next", "unlock": "start", "background": "neo",
 "bio": "A signal nobody sent. ..."}
```

**In Blender, from an existing body.** Import a character, reshape or replace
its meshes piece by piece, export over the same base, and give the recipe the
finished file: `"model": "mine.xbr"` (with `"model_textures"`, the folder of
any new textures) in place of `body`/`head`.

**From scratch, low-poly.** `tools/blender/ts2_lowpoly.py` builds a character
from boxes, one or more per bone, textured from a small atlas painted from a
spec. It suits an N64-era look, for example a character recreated from
screenshots of an older game:

1. Collect reference images; note the proportions (head, torso, limb
   thicknesses) and the colours of each part.
2. Write a spec: atlas cells (a base colour, grain, and rectangles: a face is
   a skin cell with hair, eyes, brows and a mouth as rectangles) and one box
   per bone, `[width, depth]` at each end, with a cell per side. The script's
   docstring has the format.
3. Export any TS2 human as the base (it supplies the skeleton), build, look
   at the preview, adjust the spec, repeat:

   ```bash
   python3 -I tools/ts2gltf.py gltf ~/TS2Modding/chr/ob/chrs/chr69.xbr base.glb \
       --textures ~/TS2Modding/chr --bindpose ~/TS2Modding/fe_anim/anim/data/ts2
   Blender -b --factory-startup --python tools/blender/ts2_lowpoly.py -- \
       base.glb spec.json mine.glb --preview preview.png
   python3 -I tools/ts2gltf.py fromgltf ~/TS2Modding/chr/ob/chrs/chr69.xbr mine.glb mine.xbr \
       --texture-dir textures --textures ~/TS2Modding/chr
   ```

   A 16-box character is 192 triangles and one 128x128 texture. The result
   can be opened in Blender with the add-on and refined by hand.
4. Add it to a recipe with `"model": "mine.xbr"`.

Then, for any of the three:

```bash
python3 -I tools/ts2kitbash.py <recipe.json> game/data <work> <mod>
RECOMP_MODS=<mod> ./split2_recomp            # or <mod>:<another mod>
```

`ts2kitbash` writes a mod folder (loose files and `mod.json`), which stacks
with any other: the model into `paks/chr.pak/`, the select-screen preview
into `paks/chrinc.pak/`, a portrait rendered in Blender into the front end's
paks, and `ts2/characters.ini`. Two recipes built separately (say Agent
Static and The Bone Ranger in one, Monkey Business in another) give two mods
whose characters all appear together.

In Arcade Custom the new characters are at the end of the Select Character
list (press up from the start), unlocked from the start; they are in the
Gallery too. New texture ids are picked from 8000-9999 by a hash of the
picture, so two characters' textures, even from two mods, rarely collide.

## Keeping a character private

A character that recreates someone else's work (another game's character, a
film character, a real person) is for your own use: it must not be committed,
published or shared, like the game's own files. Keep its spec, recipe and
output under `private/` in this repo, which git ignores, and build the mod
outside the repo. Only tools and guides that contain no such content are
committed.
