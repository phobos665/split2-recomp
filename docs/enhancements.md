# Enhancements: what is done and what is next

Tracking list for TimeSplitters 2. Each candidate has an estimate and a
split: **toolkit** work goes in xboxrecomp and every title gets it;
**TS2** work is this repository. The general list, and the reasoning behind
the split, is in `xboxrecomp/docs/technical/xbox-game-enhancements.md`.

Estimates are working time; calendar time will be longer. They date from
30 September 2026.

## Done

| Enhancement | Where | Notes |
| --- | --- | --- |
| Widescreen (16:9) | Both | Camera widened where the game builds it, so culling agrees; front end, HUD and every other screen laid out for 16:9 by call site. `RECOMP_TS2_MENUS=43` brings back the 4:3 front end. |
| Internal resolution | Toolkit | `RECOMP_RES_SCALE=1..8` |
| Vulkan renderer | Toolkit | The renderer on macOS. On Windows `RECOMP_D3D8_BACKEND=vulkan`, which needs `third_party/dxc` (the DXC GitHub release) for the build |
| Launcher mouse input | Toolkit | Arrow hit boxes match what is drawn (xboxrecomp #24) |
| Variable refresh rate | Toolkit | Borderless fullscreen (Alt+Enter), VRR presents on both renderers; launcher rows Fullscreen and Variable refresh rate (xboxrecomp #29) |
| Frame interpolation | Both | `frame_interp = 2..4` (launcher row): 120+ frames a second shown while the game runs at 60. TS2 names its matrix registers (c60 projection, c64-c75 model-view and bones) in `src/recomp_manual.c`. See below |
| macOS (Apple Silicon) | Both | The toolkit's port; here, `src/main.c` from the portable template, the CMake project and `scripts/build.py` (Ninja). PAL plays to Siberia at 60 fps in a scripted run (13 Oct 2026) |
| System Link | Both | Windows only. The toolkit emulates the network card and hosts sessions over a LAN or the internet; TS2 needed one seed. See below and [multiplayer.md](multiplayer.md) |

### Frame interpolation leftovers

- Snow and other particles the CPU positions step at 60 among 120.
- A 144 Hz display needs VRR for even pacing; a render thread would serve
  fixed refresh rates (toolkit, 3-4 weeks).
- Not yet checked: the first-person weapon and muzzle flashes while
  firing, guards animating (the bone matrices), the pause menu, a death.
- Measurements and how it works:
  `xboxrecomp/docs/technical/frame-interpolation.md`.

### System Link leftovers

- macOS: the toolkit's network card is Windows-only (toolkit work).
- The USA release: System Link not opened yet; it probably needs its own
  counterpart of PAL's seed `0x0009D530`.
- Playing against xemu or a console (needs the player's `XboxLANKey`), and
  XLink Kai: untested.
- Split screen over System Link: untested.

### Checking a screen's widescreen layout

How to survey a screen: F11 with `RECOMP_TS2_UI_SITES=1` set, then
`d3d8_replay --each-tag` / `--each-tag-hidden` on the capture and
`--place <site>=<placement>` to try a placement before it goes into
`src/recomp_manual.c`.

## Candidates

| Enhancement | Toolkit | TS2 | Total | Confidence |
| --- | --- | --- | --- | --- |
| [Modern controller icons](#modern-controller-icons) | 2–3 weeks | ~1 week | 3–4 weeks (first milestone 1.5–2) | High to medium |
| [Native mouselook](#native-mouselook) | 1–2 weeks | 2–4 weeks | 3–6 weeks (+2–3 for mouse menus) | Medium to low |
| [Playable character models](#playable-character-models) | 1–2 days (+2–3 for new characters) | 4.5–7 weeks | 4.5–7 weeks to edit; +3–5 weeks to add characters | Medium to low |

The controller icons need texture replacement by content hash, which is
also the first step for texture mods.

---

### Modern controller icons

Replace the game's Xbox button icons with the matching modern set for the
pad in use: Xbox Series, PlayStation, Switch.

How TS2 draws them: each button is its own 32x32 texture (B, A, Y, X in
`textures/misc/xbstdbutton1-4.xbt`), plus a 128x64 atlas with Start, Back
and arrows. Every menu and dialog prompt is text with an inline icon code,
so about 560 strings in five languages go through those four textures. The
textures are byte-identical in every level pak, so one content hash
identifies each.

Approach: toolkit texture replacement by content hash, one replacement set
per pad family, following the pad used last (SDL3 gives its type). TS2
supplies a small manifest (hash → button, atlas layout).

| Scope | Toolkit | TS2 |
| --- | --- | --- |
| **First milestone:** Xbox Series and PlayStation, chosen by a setting | 4–6 days | 2–3 days |
| Full: live switching, Switch, the atlas, launcher text, follows bindings | 10.5–16 days | 3.5–6 days |
| Optional: per-player icons in split screen | 2–4 days | 1–2 days |
| Optional: controller-picture screens; button names written in text | – | 4–7 days (low confidence) |

To decide: the art (Kenney's Input Prompts are CC0 and cover all three;
CC0 waives copyright, not trademark, so whether glyph art ships in the repo
is a maintainer's call). Icons must follow the button's position and the
player's bindings, not the letter printed on it: a Switch pad's bottom button
reads "B" and acts as the game's A.

### Native mouselook

The toolkit has no mouse input today.

| Step | Where | Estimate |
| --- | --- | --- |
| Mouse input: raw input, cursor lock in game and release in menus and on alt-tab, sensitivity and invert, mouse buttons and wheel as bindable controls, launcher UI | Toolkit | 1–2 weeks |
| Find TS2's view angles and where stick input becomes turn rate (the in-game camera, `sub_00032DC0` / `0x4B2CA0` in PAL and `sub_00032D90` / `0x4B2F60` in USA, is the starting point) | TS2 | 1–2 weeks |
| Apply the mouse to the view angles directly: pitch limits; auto-aim, look-spring and aim smoothing off for the mouse | TS2 | 3–5 days |
| Edge cases: aim mode, scope zoom, turrets, cutscenes and pause, respawn, split screen (player 1 only) | TS2 | 1–2 weeks |
| Optional: clicking TS2's menus with the mouse | TS2 | 2–3 weeks |

A cheaper option, the mouse as a virtual right stick (1–2 weeks, toolkit
only), does not feel like mouselook: the game's stick acceleration, dead
zone and top turn speed still apply.

### Playable character models

Edit the playable characters in Blender and put them back into the game,
then add new ones to the roster. Estimated 15 October 2026. The format
research behind it is in
`xboxrecomp/docs/technical/modding-models-textures.md`.

What makes it feasible:

- `.pak` files are uncompressed and community tools already read them;
  `.xbt` textures are plain DXT1/DXT3 behind a 128-byte header.
- A character piece is drawn with at most three matrices (c64-c75, as
  measured for frame interpolation): no large bone palette.
- The XBE names three skeletons: `anim/data/ts2/human_19_bindpose.raw`,
  the rail spider's and the barrel's. Neither of the last two is playable,
  so every playable character probably shares the 19-bone human skeleton
  and every animation (inferred from the strings, not yet checked against
  the models). The decomp names the loader (`bindpose_slot_load`,
  `sub_00012C30`).
- Nobody has written an `.xbr` before; the decomp's model loader is the
  specification.

| Step | Where | Estimate |
| --- | --- | --- |
| A `mods/` folder read before the disc's `.pak` files | Toolkit | **Done:** `RECOMP_MODS` (xboxrecomp `feat/mods-overlay`; macOS checked, Windows not built yet) |
| `.pak` unpack and repack (or `tspak`) | TS2 | **Done:** `tools/ts2pak.py`, all 68 paks round-trip byte for byte |
| Write a character's files into every pak that holds them (see below) | TS2 | **Done:** `tools/ts2mod.py build`, checked in Siberia |
| `.xbt` to and from DDS/PNG | TS2 | **Done:** `tools/ts2xbt.py`, all 19,180 textures round-trip |
| The whole `.xbr` format from the game's loader: geometry sections, piece-to-bone binding, the 2–3 matrix blend, materials, LODs | TS2 | **Done:** `tools/ts2xbr.py`, `docs/formats/xbr.md`; every character file on the disc rewrites byte for byte |
| Blender add-on: import `.xbr` and the human skeleton, export back, triangle strips | TS2 | 10–15 days |
| Low-detail models (`chrNNlod2.xbr`) and hat and head attachment points | TS2 | 3–5 days |
| Checking in game: animation, hit detection, split screen | TS2 | ~5 days |
| **To add characters:** grow the roster tables in the XBE (model paths, heads, hats, voices, unlocks, bot profiles), character select slots and portraits, unlocks in the save without breaking old saves | TS2 | 3–5 weeks |
| **To add characters:** System Link refuses players whose mods differ | Toolkit | 2–3 days |

First milestone (about 2.5 weeks): the first four steps, ending in a
hand-edited `.xbr` that still loads and animates. It settles the format
risk before the Blender work. **Reached 15 October 2026:** every human
model in `l_35_ST.pak` with its head piece scaled 5x, written by
`ts2xbr`'s writer and installed with `ts2mod`, drew in Siberia with the
big head and kept animating (scripted run, macOS, frame dumps).

What the format work changed in the plan:

- All 238 human models (155 characters, 83 lod2) share one 19-bone
  skeleton; its joint positions are `fe_anim.pak`
  `human_19_bindpose.raw`, scaled per model. Exceptions: the Barrel Robot
  (13 bones), three story bosses, and one-bone hats and detachable parts.
- No blend weights: a skinned vertex names one of three bones (its
  piece's, the parent's or the child's), so a mesh weight-painted in
  Blender is snapped to one bone per vertex on export.
- `chrinc.pak` holds the character-select previews: the same model with
  its textures inside the file.

Known limits:

- Story enemies are drawn with the same models, so editing a character
  changes it in story mode too. Only a new slot avoids that.
- A level does not draw its characters from `chr.pak`. Every story and
  arcade level pak carries copies of the characters in it (byte-identical
  to `chr.pak`'s, textures under the same global `textures/NNNN.xbt`
  numbers; `chr01.xbr` is in 22 paks, one file is in 24), so a character
  edit is written into each of them. Checked: red textures in `chr.pak`
  alone changed nothing in Siberia; in `l_35_ST.pak` the guards drew red.
- Cutscenes are in-engine but use their own models, skeletons and
  animations (`cs_l_*.pak`, e.g. `anim/data/cs/l_35/spacemarine.xbr` with
  `spacemarine_m0_bind.raw`), so edits do not show in them.

The roster (`docs/formats/roster.md`, PAL): 127 entries of 0x20 bytes at
`0x002BAC60` (chr id, portrait, unlock rule), shown as one 14 x 9 grid of
126 cells; 162 character definitions at `0x002AA060`; which characters a
level loads is a table in the XBE (`0x002CE928`), and a level's pak must
hold their files. Unlocks are worked out from story and medal bits, not
stored per character, so a new character needs no save change. Two ways
to add one:

- Reuse one of the 35 non-playable ids (pedestrians, robots, spare
  copies): give it new files and a roster entry. The roster count 127 is
  hard-coded at 12 sites and the grid is full, so the grid and count change
  too. The cheapest route; not tried yet.
- A new id beyond 162: every table is a fixed array with other data after
  it, so either the tables move or the 15 functions that read the roster
  are overridden.

Afterwards:

- [ ] **Cutscenes:** carry an edited character into the cutscene versions:
  export onto each cutscene model's own skeleton, check it in every
  cutscene it appears in. Same `.xbr` tools. About 1–2 weeks for the first
  cutscene, less for each after. Only `cs_l_35.pak` has been looked at.

## Not estimated yet

- **Cutscene skip:** find where in-engine cutscenes start and whether the
  game already has a skip.
- **Texture mods:** naming dumped textures by pak entry; shares the
  replacement work with the controller icons.
- **MSAA and filters:** toolkit work; TS2 only needs exceptions for passes
  that break.
