# Making a character in Blender: a beginner's guide

How to change a TimeSplitters 2 character, or make one of your own, in
Blender and play as it. No programming needed; you type a few commands in a
terminal. The full reference (every tool, recipes, low-poly builds) is
[modding.md](modding.md).

You need: the game built from this repository (PAL release) with your own disc
in `game/`, Blender 4.2 or later, and Python 3. Commands are run from the
repository's folder.

## 1. Set up (once)

Unpack the character files and the skeleton somewhere to work in:

```bash
python3 -I tools/ts2pak.py unpack game/data/chr.pak ~/TS2Modding/chr
python3 -I tools/ts2pak.py unpack game/data/fe_anim.pak ~/TS2Modding/fe_anim
python3 -I tools/blender/build_addon.py
```

The last line makes the Blender add-on, `build/ts2_character-1.0.0.zip`.
Install it: in Blender, **Edit > Preferences > Get Extensions**, the **⌄** menu
at the top right, **Install from Disk...**, and pick the zip. Then open the
add-on's preferences (Add-ons > TimeSplitters 2 character) and set:

| Setting | Set it to |
| --- | --- |
| Bind pose folder | `~/TS2Modding/fe_anim/anim/data/ts2` |
| Textures | `~/TS2Modding/chr` |
| Mod folder | a new empty folder, e.g. `~/TS2Modding/mymod` |

## 2. Open a character

**File > Import > TimeSplitters 2 character (.xbr)**, and pick a file in
`~/TS2Modding/chr/ob/chrs/`. Characters are numbered: `chr69.xbr` is Jake
Fenton, `chr07.xbr` Elijah Jones, `chr19.xbr` the grey Siberian soldier. The
table in [formats/roster.md](formats/roster.md) ("Playable characters") lists
who is who. Ignore the `lod2` files for now.

You will see a skeleton (the armature) and the character, split into one
object per body part, named like `p08s0_head`, `p12s0_r_upperarm` and
`p26s0_r_thigh`.

## 3. The rules

TimeSplitters 2 characters are built like action figures: each body part is a
rigid piece that moves with one bone. So:

- **Everything inside a body-part object moves with its bone.** Whatever you
  model inside `p08s0_head` moves with the head, inside `p16s0_r_hand` with
  the right hand. Put each part of your model in the right object.
- **Don't rename or delete the armature, and don't rename objects.** The
  export matches them by name. Deleting a body-part object removes that part
  from the character (the small `joint` and `mid` objects at the elbows and
  knees can go if your model doesn't need them).
- **Keep the pose.** Model around the skeleton as it stands; don't move or
  rotate the armature or pose its bones.
- **Keep it modest.** The game's own characters are a few thousand triangles
  each. Stay in that range.
- **Textures.** Keep the existing materials, or give a part a new material
  with a new image: it becomes a new game texture by itself. Image sides
  should be powers of two (64, 128, 256 or 512 pixels).

## 4. Make your changes

**To change a character:** select a body-part object, press **Tab** for Edit
Mode, and move, scale or reshape it as you like. Paint its texture in Texture
Paint mode, or swap the image for one you painted elsewhere.

**To make your own model on the skeleton:** start from any imported
character. For each body part, go into its object (Tab), delete the old
geometry, and model your own in the same place; or model the part as a
separate object and join it in (select yours, then the body-part object, and
**Ctrl+J**). Do it for every part you want, and delete the body-part objects
you don't.

Save your `.blend` as you go: the game only sees what you export.

## 5. Play it

There are two ways to get your model into the game.

**A. In place of the character you started from.** In the sidebar (press
**N**), open the **TS2** tab and click **Write into mod folder**. The mod
folder now holds your model (and any new textures), and is a mod as it
stands. Run the game with it:

```bash
cd build/Release
RECOMP_MODS=$HOME/TS2Modding/mymod ./split2_recomp
```

The character changes everywhere it appears: story, arcade and as bots. (Its
far-away version, `chrNNlod2.xbr`, is a separate model; edit it the same way
or the character looks unchanged at a distance.)

**B. As a new character of its own.** Export with **File > Export >
TimeSplitters 2 character (.xbr)**, e.g. to `~/TS2Modding/mychar/mychar.xbr`,
with **New textures** set to `~/TS2Modding/mychar/textures`. Then write a
recipe, `~/TS2Modding/mychar/recipe.json`:

```json
{"characters": [
 {"name": "My Hero", "slot": "chr76", "chr_id": 75,
  "model": "mychar.xbr", "model_textures": "textures",
  "portrait_colour": [0.2, 0.5, 0.9],
  "roster": "next", "unlock": "start", "background": "neo",
  "stats": 68, "sounds": 68,
  "bio": "One or two sentences for the Gallery."}
]}
```

and build it into a mod:

```bash
python3 -I tools/ts2kitbash.py ~/TS2Modding/mychar/recipe.json game/data \
    ~/TS2Modding/work ~/TS2Modding/mychar-mod
RECOMP_MODS=$HOME/TS2Modding/mychar-mod ./split2_recomp   # from build/Release
```

`ts2kitbash` makes the character-select preview and a portrait (in Blender,
by itself) and adds the character to the roster. In **Arcade > Arcade
Custom**, press **GO!**, then on **Select Character** press **up**: new
characters are at the end of the list, unlocked. `slot`/`chr_id` pick whose
files the new character takes over: use `chr76`/75 up to `chr90`/89 (unused
NeoTokyo passers-by), a different one for each character.

Mods stack: `RECOMP_MODS=$HOME/TS2Modding/mymod:$HOME/TS2Modding/mychar-mod`
loads both (the first listed wins where they overlap).

## 6. If something looks wrong

| You see | Why, and what to do |
| --- | --- |
| A part sticks out or stays behind when the character moves | It is in the wrong body-part object. Move that geometry to the object of the bone it should follow |
| A part is missing in game | Its object was deleted or renamed. Re-import the original and copy the part back |
| The export says vertices were "snapped" | Some vertices were weighted to a bone their part can't use; they now follow the nearest allowed one. Usually harmless; check the result |
| The character looks unchanged far away | That is the `lod2` model; edit it too (step 5A) |
| The Select Character preview is unchanged (5A) | The preview is a separate file, `chrinc.pak`'s `ob/chrincs/chrNN.xbr`. Unpack `chrinc.pak` and edit it the same way, or use route 5B, which makes the preview for you |
| An accented name shows `?` | Names and bios must use Western European letters only (Latin-1) |
| Nothing changed at all | Check the game's output for `[MODS]` lines; the mod folder path in `RECOMP_MODS` is probably wrong |

A character that recreates someone else's (from another game or a film) is
for your own use only: keep it out of git, in `private/` (see "Keeping a
character private" in [modding.md](modding.md)).
