# Modding TimeSplitters 2's characters

How to change a character, make a new one and add it to the game. Everything
here starts from your own disc (`game/`), and every tool is in `tools/`. The
file formats are in `docs/formats/` (`xbr.md` models, `xbt.md` textures,
`roster.md` the roster and the game-side hooks).

PAL only so far. macOS is tested; Windows has not been built with these
changes yet.

## How a mod reaches the game

A mod is a folder laid out like the disc (`data/chr.pak`, ...). Run the game
with it:

```bash
cd build/Release
RECOMP_MODS=/path/to/mod ./split2_recomp
```

A file the game opens from the disc is read from the mod instead when the mod
has it (`[MODS] ... from ...` in the log). Mods replace whole paks, so a mod
is built with `tools/ts2mod.py`, which rewrites the paks it needs from a
*source folder*:

```text
files/<path in a pak>              replaces that file in every pak that holds it
paks/<pak>/<path in a pak>         replaces or adds a file in that one pak
ts2/characters.ini                 characters the mod adds to the roster
```

```bash
python3 -I tools/ts2mod.py build <source> game/data <mod>
```

Every story and arcade level pak carries its own copy of the characters in
it, which is why `files/` writes into all of them. Two mods do not stack yet:
the first one that has a pak wins, and only the first `characters.ini` is
read, so put everything in one source.

## The tools

| Tool | What it does |
| --- | --- |
| `ts2pak.py` | list, unpack and repack `.pak` archives (byte-identical round trip) |
| `ts2xbt.py` | textures to and from PNG/DDS |
| `ts2xbr.py` | character models: parse, check, rewrite |
| `ts2gltf.py` | models to and from glTF (`gltf`, `fromgltf`), and `graft` pieces between characters |
| `ts2kitbash.py` | build whole characters from a recipe: model, preview, portrait, roster entry |
| `ts2mod.py` | build a mod from a source folder |
| `blender/ts2_character` | Blender add-on: File > Import/Export > TimeSplitters 2 character |
| `blender/ts2_lowpoly.py` | build a low-poly (N64-era) character on TS2's skeleton from a spec |
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
4. `ts2mod build`, run with `RECOMP_MODS`.

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

**From scratch, low-poly.** `tools/blender/ts2_lowpoly.py` builds an
N64-era character from a spec, for example one recreated from screenshots of
an older game. What reads as N64 rather than as blocks: few polygons but
tapered, chamfered shapes, smooth shading and soft textures. So each part is
a run of rings along a bone (each ring a rounded cross-section of its own
width and depth), shaded smooth, with a texture cell wrapped round it (the
part's front is the middle of the cell):

1. Collect reference images; note the proportions (head, torso, limb
   thicknesses) and the colours of each part.
2. Write a spec: atlas cells (a base colour, a top-to-bottom gradient, and
   soft rectangles and ellipses: a face is a skin cell with hair, brows,
   eyes, nose and mouth as shapes; give it `"span": 2` for a 128-pixel cell)
   and parts (rings `[t, width, depth]` along a bone, `sides`, `round`, and
   `"front": 2` on the head so the face gets most of its cell). The script's
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

   A 16-part character with 8-sided parts is about 650 triangles and one
   256x256 texture. Pure boxes (4 sides, flat colours, no blur) look like
   Minecraft rather than N64. The result can be opened in Blender with the
   add-on and refined by hand.
4. Add it to a recipe with `"model": "mine.xbr"`.

Then, for any of the three:

```bash
python3 -I tools/ts2kitbash.py <recipe.json> game/data <work> <source>
python3 -I tools/ts2mod.py build <source> game/data <mod>
```

`ts2kitbash` writes the model into `chr.pak`, the select-screen preview into
`chrinc.pak`, a portrait rendered in Blender into the front end's paks, and
`ts2/characters.ini`. In Arcade Custom the new characters are at the end of
the Select Character list (press up from the start), unlocked from the start;
they are in the Gallery too. New texture ids are picked from 8000-9999 by a
hash of the picture, so two characters' textures rarely collide.

## Keeping a character private

A character that recreates someone else's work (another game's character, a
film character, a real person) is for your own use: it must not be committed,
published or shared, like the game's own files. Keep its spec, recipe and
output under `private/` in this repo, which git ignores, and build the mod
outside the repo. Only tools and guides that contain no such content are
committed.
