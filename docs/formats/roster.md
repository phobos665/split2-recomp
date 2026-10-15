# Character roster (TimeSplitters 2, Xbox, PAL)

Where the PAL executable keeps its characters: which `chrNN` model is which
character, which of them are playable, how the game picks a model at run time,
and what adding a character would take. All addresses are PAL virtual
addresses in `game/default.xbe` (SHA-1 `2809eb14...`); functions are
`sub_XXXXXXXX` in the lifted code. USA has not been checked; its addresses
differ.

Each claim is marked:

- **measured**: read from the bytes of `default.xbe` or the `.pak` files on
  the PAL disc (`tools/ts2pak.py list`), or seen in a run.
- **code**: read from the disassembly of the lifted PAL executable
  (`.pipeline/disasm/asm/text.asm`) at the addresses given.
- **inferred**: a reading that fits the data but that neither of the above proves.

The sections up to "What adding a character would take" were written
without a run; the one run-derived fact there (level paks carry their own
character copies, and chr.pak is not used in a story level) is the
coordinator's measurement, quoted in [Which pak a model comes from](#which-pak-a-model-comes-from).
The sections from "Experiment" on come from scripted runs.

## Summary

- A character is identified everywhere by a **chr id**, 0-based: chr id `n`
  uses the files `chr{n+1:02d}` (`chr01` is chr id 0). The player record keeps
  it as a 16-bit word at +4 (code: e.g. `0x000428C0`, `0x00016513`), the
  profile keeps the last one chosen as a dword at +0xD0 (code: `0x0009CCBF`).
- Three fixed tables in `.data` make up the roster:
  1. the **character definition table** at `0x002AA060`: 162 entries of 0x44
     bytes, indexed by chr id: name, sound set, model, LOD model, and stats;
  2. the **per-character flags table** at `0x002ACB78`: 161 entries of 0x14
     bytes, indexed by chr id: flags (hat sizes and others) and four floats;
  3. the **selectable roster** at `0x002BAC60`: 127 entries of 0x20 bytes, in
     select-screen order: chr id, portrait, set background, unlock condition.
     The split2-recomp PAL build moves it (with 32 hidden spare slots) into a
     section of its own before the lift: [Room for more characters](#room-for-more-characters-the-xbe-patch).
- 126 roster entries are selectable (the 127th, entry 126, has unlock kind 0,
  "never"). The character grid is 14 columns by 9 rows = 126 cells, one page.
- Unlocks are not stored per character. Each roster entry carries a
  condition, evaluated against the profile's story-completion and medal bit
  sets every time it is asked (`sub_001AEE50`).
- Models are found by **index** into the game's object list at `0x002D8E14`
  (1324 entries of 0x24 bytes, each with an `ob/...xbr` path), never by
  building an `ob/chrs/chr%d` path. The one `sprintf` is
  `host0:ob/chrincs/chr%02d.xbr`, for the front end's character preview.

## The character definition table (`0x002AA060`)

162 entries (chr id 0 to 161) of 0x44 bytes (measured: the fields below are
consistent for exactly 162 entries; entry 162 onwards is other data).
Indexed as `0x002AA060 + id * 0x44` (code: 77 references in 38 functions, all
of the form `[reg + 0x2AA060 + field]` after `imul reg, id, 0x44`).

| Offset | Type | Field | Evidence |
|---|---|---|---|
| +0x00 | int16 | Name: a text id (below). Upper 16 bits are 0 in every entry | code (`movsx word`, e.g. `0x000999D3`, `0x00098035`); measured |
| +0x04 | ptr | Sound set: a list of up to 18 sound ids (int16) at +0, and up to 6 at +0x24, which `sub_000428C0` requests (`sub_001C6FF0`) when the mode is not story (4). Several characters share one (the pedestrians use three) | code `0x000428D2`-`0x00042939`; sharing measured |
| +0x08 | int32 | Model: index into the object list `0x002D8E14` (e.g. 0 = `ob/chrs/chr01.xbr`) | code `0x000428CC` → `sub_0014A9E0`; measured |
| +0x0C | int32 | LOD model index (`chrNNlod2.xbr`), or -1 for none | code `0x000428DF`; measured |
| +0x10 | int32 | 0 in every entry; no direct reference | measured |
| +0x14 | float | 1.8 in every entry; read with +0x20 in 23 places (player movement and placement) | measured; code `0x0001651A` and others |
| +0x18, +0x1C, +0x24 | float | 1.0, 0.6, 1.0 in every entry; no direct reference | measured |
| +0x20 | float | 0.5 (0.6 for Wood Golem chr35) | measured; code (17 refs) |
| +0x28 | float | 1.092 for chr ids 0-15 except Monkey, 0.6 for Monkey (chr03), 1.0 for the rest; no direct reference. Looks like a size scale | measured; meaning inferred |
| +0x2C | int32 | 0-9: a class index. Indexes 8-byte entries at `0x002B8FA0` (two floats drawn as the **Stamina** bar, text 479) and per-class AI/movement records at `0x002B8FF8` (0x18 bytes) and `0x002B9E58` (0x12C bytes) | code `0x0008F84A`, `0x00071BC7` |
| +0x30, +0x34, +0x38 | int32 | 1-15, decreasing (e.g. 12, 10, 8): one per difficulty; one of the three is copied to the player record +0x1324 | code `0x00044484`-`0x000444A4` |
| +0x3C | int32 | 1-15: copied to player +0x1324 instead of the per-difficulty value when bit 0x80000 of `0x004AD558` is set (the same bit that enables the flags table below); drawn as `15 - value` beside **Agility** (text 480) on the select screen | code `0x0006B2CB`, `0x0008F87E` |
| +0x40 | int32 | 0 in every entry | measured |

Names are text ids into the game's string tables: `0x003362F0` holds five
pointers, one per language (English `0x00336308`, then `0x00338E50`,
`0x0033B998`, `0x0033E4E0`, `0x00341028`), each an array of 2770 string
pointers with id 0 empty; the language index is `[0x00386734]` (code:
`0x000999DA`; table bounds measured). Character names are ids 67 to 222
(English), stored in chr id order.

## The per-character flags table (`0x002ACB78`)

161 entries (chr id 0 to 160) of 0x14 bytes: a flags dword and four floats
(typically 8.0, 4.0, 0.15, 9.0; the first varies 7.0-9.0) (measured).
`sub_00042030` (the hat chooser) reads the flags at `0x002ACB78 + id * 0x14`:
bits 0x1000, 0x800 and 0x400 choose the big, medium or small size of the
generic hats (code `0x00042079`-`0x000420A7`). `sub_0003FD50` returns the
flags when bit 0x80000 of `0x004AD558` is set (code; decomp
`table_2ACB78_flags_if_4AD558_80000.cpp`). The floats' use was not traced.

## The selectable roster (`0x002BAC60`)

127 entries of 0x20 bytes, `0x002BAC60` to `0x002BBC40` (measured).

| Offset | Field | Evidence |
|---|---|---|
| +0x00 | chr id | code: `sub_00087A90`/`sub_00087AD0` search it; `0x000999CB` uses it to index the definition table |
| +0x04 | Portrait: index into the texture list `0x002BF7B8` (548 entries of 0x10: path pointer, 0, 1, 3). 342-469 are the 128 `textures/misc/chrimage_*.raw` | code `sub_00087AD0`, `0x00098E4D`; measured |
| +0x08 | Set background: texture 470-481, `chrblank_<set>.raw` (atom, aztec, circus, gangster, neo, notredame, planetx, robot, siberia, spacestation, ts1, west), drawn in place of the portrait while locked | code `0x00098FC3`; measured |
| +0x0C | Unlock condition, 5 dwords: kind, a, b, c, d. `sub_00087A90(id)` returns a pointer to it | code |

Unlock kinds, as `sub_001AEB10` evaluates them (jump table at `0x001AEC40`;
the profile block is the pointer `sub_00195360` returns):

| Kind | Meaning | Used by |
|---|---|---|
| 0 | Never: `sub_001AEE50` returns 0 and the select screens skip the entry | entry 126 (Consultant) |
| 1 | Always unlocked | 31 entries |
| 2 | Story level `a` finished on difficulty `b`: bit `a` of block +0xBD4 + 4b, else bit `a` of block +0xBC8 + 4(3d + b) | 10 entries, `a` 0-9, `b` 1 |
| 3 | Every item of group `a` (`sub_0003CF50`) has medal `b` | none |
| 4 | Item `a` (arcade league match or challenge) has medal `b`: bit `a & 31` of block +0xBD0 + 16b + 4(a >> 5). `b` = -1 means any medal 1-4 | 85 entries, `b` 2 or 3 |
| 5 | At least `a` of the 7 groups complete at medal `b` | none |
| 6 | Every group in the -1-terminated list at pointer `c` | none |

(code `0x001AEB10`-`0x001AEC3D`, `0x001AEA40`, `0x001AEAC0`.) Before the
condition, `sub_001AEE50` returns 1 if the byte at `0x0035F66F` (override 3 of
the array at `0x0035F66C`, `sub_000A9740(3)`) is set, and `sub_001AEB10`
returns 1 if `[0x0035F668]` is set: two unlock-everything switches (code;
what sets them was not traced).

Story level index `a` follows the set column of the ten kind-2 entries:
0 Siberia, 1 Chicago, 2 Notre Dame, 3 Planet X, 4 NeoTokyo, 5 Wild West,
6 Atom Smasher, 7 Aztec, 8 Robot Factory, 9 Space Station (measured set,
level names inferred). Medal `b` 1-4 is presumably bronze to platinum
(inferred), and the item numbering of `a` was not mapped to named matches.

**Save storage:** there is no per-character unlock bit. The profile keeps
story-completion bits (+0xBC8, +0xBD4) and per-medal bit sets (+0xBE0 to
+0xC1F, 128 items per medal) and the roster is re-derived from them (code).
`sub_000952C0` snapshots every entry's unlocked state into 127 dwords at
`0x0035C2D8` and `sub_000954B0` compares against it to announce new unlocks
(code). Profiles are signed: `XCalculateSignatureBegin` (`0x001CDFAC`) is
called from `sub_0011FAC0`, `sub_0011FC40` (save/load) and `sub_001C2E80`, so
a save edited by hand must be re-signed (code; the signature check itself was
not traced).

### How the screens enumerate it

- **Grid**: `sub_00099960` builds the page and sets 14 columns
  (`[0x0035C80C] = 0xE`, `0x00099C97`) and 9 rows (`[0x0035F4A4] = 9`,
  `0x00099CA1`). `sub_00098F40` draws one cell per entry whose kind is not 0,
  in table order, row = index / 14 (`idiv` at `0x00098FF0`), with the portrait
  if `sub_001AEE50` says unlocked, else the set background. `sub_00099430`
  handles the cursor; it computes `rows * columns - count` (clamped at 0). The
  selected entry index is `[0x0035CB24]`. 14 x 9 = 126 = the selectable
  entries, so there is exactly one full page and no paging (code).
- `sub_00098E00` draws the selected character's portrait; `sub_0008F550`
  draws its name and the Stamina / Agility / Accuracy bars (text 479-481).
- `sub_0008DEE0` and `sub_000A3C60` build menu lists of the unlocked entries
  (a list item's +0x18 holds the chr id), and `sub_0009CC00` finds the
  profile's character (profile +0xD0) in the roster for its icon (code).
- `sub_00087C20(n)`, `sub_00087CA0` count entries and unlocked entries.
- The four dwords after the table, `0x002BBC40` = chr ids 106, 127, 46, 111
  (Cortez, Hart, Ilsa, Gregor), are cycled by `sub_00087D30` (called from
  `sub_00195310`) to give new profiles a default character (code; measured).
- The first 20 entries are always unlocked and come in pairs, one pair per
  story level (Cortez/Hart for Space Station, Ilsa/Gregor for Siberia, ...),
  which fits them being the story mode's player characters (inferred; the
  story player table itself was not found).

## Which pak a model comes from

`sub_000865C0` remounts the archives for each level (code; called from
`sub_000A7230` and `sub_000DD7E0`). With `L = [0x004A492C]` (level number)
and mode `[0x004AD54C]` (4 = story):

| Case | Archives mounted, in order |
|---|---|
| Story mode, a level below 100, bit 0x40 of `0x004AD558` clear | `data/story/l_L_ST.pak` only |
| Level 101 (`frontend`) | `data/arcade/l_101.pak`, `chrinc.pak`, `sounds.pak`, `demos.pak` |
| Level 103 (`loading`) | `data/arcade/l_103.pak` only |
| Any other case (arcade, multiplayer, challenges, level 100 `tileset`, ...) | the level pak (`l_L_AR.pak`, or `l_L.pak` from 100), `sounds.pak`, `gun.pak`, `chr.pak`, `demos.pak` |

Then, in every case, `data/xbt.pak`, `data/xbob.pak` and `data/xbsound.pak`
(paths without `host0:`, at `0x002222A4`, `0x00222294`, `0x00222280`; no such
files are on the disc, so these mounts presumably fail quietly; inferred).
Nothing is remounted when `[0x00358D60]` is non-zero (code `0x0008661D`). A file is looked up first in the archive that
served the previous lookup (`[0x002BABF8]`), then in every mounted archive in
mount order, first match wins (code `0x00086368`-`0x000863B8`). So:

- **chr.pak** supplies characters that a non-story level needs and its own
  pak does not carry: the characters players and bots pick in arcade. A
  level's own copy wins when both have the file (code). In a story level it
  is not mounted at all, which agrees with the coordinator's measurement
  (red textures in chr.pak changed nothing in Siberia; the same in
  `l_35_ST.pak` did). The coordinator's run also saw chr.pak opened twice at
  start-up / front end; `sub_000865C0` does not mount it for level 101, so
  those opens come from another path (open question).
- **chrinc.pak** is mounted only for the front end. `sub_0009E410(id)`
  formats `host0:ob/chrincs/chr%02d.xbr` with `id + 1` and loads it for the
  selecting player into a 0x7D000-byte (512,000) buffer at
  `[0x004AD6D0] + (2 * slot + flip) * 0x7D000` (two per player, four
  players), through `sub_000A0770`, which sets up the preview view (code). So
  chrinc holds the self-contained models of the character-select 3D
  preview. Its largest file, `chr104.xbr`, is 358,760 bytes (measured).
  chrinc has 155 files: every chr id 0-157 except 17 (chr18), 146 and 147
  (chr147, chr148), and it has chr104, which chr.pak lacks (measured).

### Per-level character lists

The set of characters a level loads is a table in the XBE, not the pak:
`0x002CE928`, 41 records of 0x7C bytes, each a count and up to 30 chr ids
(measured). `sub_000DFF60` returns a level's count and `sub_000DFFA0(i)` its
`i`-th chr id (code `0x000DFF89`, `0x000DFFE5`); the record is chosen by +8
of the level's descriptor, which the level table at `0x002D1390` (0x20-byte
entries: name text id, level number at +4, story descriptor at +0x10, arcade
descriptor at +0x14) gives per level (code `sub_000DEEB0`, `sub_000DEF10`;
values measured). Level 100 with record -1 takes its list from the custom
map instead (code `0x000DFF7C`). The paks were built to match (measured):

- Siberia story (level 35, record 4): chr19, 23, 25, 28, 29, 34, 41, 45, 46,
  94, 95 (chr34 listed twice). `l_35_ST.pak` holds exactly these plus chr47
  and chr112 (Ilsa and Gregor, the players).
- Arcade records hold 10 characters; the arcade paks hold the first 9 of
  them plus chr01 (checked for `l_32_AR`, `l_34_AR`, `l_35_AR` (record 15),
  `l_36_AR` (32), `l_11_AR` (37), `l_13_AR` (39)). Why the 10th is missing and
  chr01 present was not traced.

The story descriptors use records 0-12 and the arcade descriptors 15 and
24-39 (measured). Records 13-23 are also read as `0x002CEF74 + k * 0x7C` with
`k` = profile +0x4BC when it is below 11, else from the profile itself, in
`sub_0008CED0` at `0x0008CD26` (code; what that list is for was not traced).

## How a model is picked at run time

1. The chr id comes from the player or AI record (word +4).
2. `sub_000428C0(id)` requests the model `def[id].model` and, if not -1,
   `def[id].lod` through `sub_0014A9E0(object index)`, and the sound set
   (code `0x000428C0`-`0x00042939`).
3. The object list entry `0x002D8E14 + index * 0x24` holds the path
   (`ob/chrs/chr01.xbr`, ...) and flags at +0x10 (0x205 for characters)
   (measured; the flags field is tested in 24 places, e.g. `0x0012A8B0`).
   The path is looked up in the mounted archives as above.
4. Hats: `sub_00042030(id)` returns the hat object for a character: a
   hard-coded `switch` on `id - 5` (0 to 0x8B, byte table `0x000422F0`, jump
   table `0x0004226C`) returning objects 273-304 (`chrNN_hat.xbr`), or, under a
   mode tested via `sub_001AEDF0`, one of the generic hats at object
   `306 + 3 * type + size` (chef, ear, pirate, roman, viking; big, medium,
   small from the flags table) (code).
5. Heads and arms (`chr23/28/34/40/45/46/55/94/136_head/_larm/_rarm`,
   `chr23_lknee/_rknee`, objects 244-272) are separate objects, presumably for
   dismemberment (inferred; not traced).
6. The front-end preview loads `ob/chrincs/chr%02d.xbr` by `sprintf` instead
   (above).

## Playable characters

The 127 roster entries in table order, with their files on the disc
(measured: data and pak listings). "Set" is the background texture group.
`chr.pak` lists the files present for that chr id: main model, `lod2`,
`_hat`, `_head`/`_larm`/`_rarm`.

"Unlock" is the raw condition: story level index and difficulty (kind 2), or
item and medal (kind 4), as in the kinds table above.

| # | Roster entry | chr id | Name (text id) | Set | Portrait | Unlock | chr.pak | chrinc.pak |
|---|---|---|---|---|---|---|---|---|
| 0 | 0x2BAC60 | 106 | Sgt Cortez (175) | spacestation | malesm (402) | from start (kind 1) | chr107.xbr | chr107 |
| 1 | 0x2BAC80 | 127 | Corp Hart (196) | spacestation | femalesm (388) | from start (kind 1) | chr128.xbr | chr128 |
| 2 | 0x2BACA0 | 46 | Ilsa Nadir (113) | siberia | ilsa (427) | from start (kind 1) | chr47.xbr | chr47 |
| 3 | 0x2BACC0 | 111 | Gregor Lenko (180) | siberia | gregor (428) | from start (kind 1) | chr112.xbr | chr112 |
| 4 | 0x2BACE0 | 68 | Jake Fenton (136) | gangster | gangsterlead (390) | from start (kind 1) | chr69.xbr, chr69lod2.xbr, chr69_hat.xbr | chr69 |
| 5 | 0x2BAD00 | 69 | Lady Jane (137) | gangster | ladyjane (397) | from start (kind 1) | chr70.xbr, chr70lod2.xbr | chr70 |
| 6 | 0x2BAD20 | 14 | Viola (81) | notredame | jester (363) | from start (kind 1) | chr15.xbr, chr15lod2.xbr | chr15 |
| 7 | 0x2BAD40 | 133 | Mr Underwood (201) | notredame | notremallead (369) | from start (kind 1) | chr134.xbr, chr134lod2.xbr, chr134_hat.xbr | chr134 |
| 8 | 0x2BAD60 | 107 | Hank Nova (176) | planetx | malelead (401) | from start (kind 1) | chr108.xbr | chr108 |
| 9 | 0x2BAD80 | 125 | Candi Skyler (194) | planetx | candy (382) | from start (kind 1) | chr126.xbr | chr126 |
| 10 | 0x2BADA0 | 100 | Ghost (168) | neo | ghost (347) | from start (kind 1) | chr101.xbr, chr101lod2.xbr | chr101 |
| 11 | 0x2BADC0 | 61 | Chastity (129) | neo | chastity (345) | from start (kind 1) | chr62.xbr, chr62lod2.xbr | chr62 |
| 12 | 0x2BADE0 | 6 | Elijah Jones (73) | west | maincowboy (399) | from start (kind 1) | chr07.xbr, chr07lod2.xbr, chr07_hat.xbr | chr07 |
| 13 | 0x2BAE00 | 5 | Ramona Sosa (72) | west | maincowgirl (400) | from start (kind 1) | chr06.xbr, chr06lod2.xbr, chr06_hat.xbr | chr06 |
| 14 | 0x2BAE20 | 114 | Harry Tipper (183) | atom | harrytipper (360) | from start (kind 1) | chr115.xbr, chr115lod2.xbr | chr115 |
| 15 | 0x2BAE40 | 108 | Kitten Celeste (177) | atom | kitten (366) | from start (kind 1) | chr109.xbr, chr109lod2.xbr | chr109 |
| 16 | 0x2BAE60 | 97 | Captain Ash (165) | aztec | captainash (383) | from start (kind 1) | chr98.xbr, chr98_hat.xbr | chr98 |
| 17 | 0x2BAE80 | 1 | Jungle Queen (68) | aztec | jungqueen (348) | from start (kind 1) | chr02.xbr | chr02 |
| 18 | 0x2BAEA0 | 50 | Gretel Mk II (117) | robot | gretel_b (342) | from start (kind 1) | chr51.xbr, chr51lod2.xbr | chr51 |
| 19 | 0x2BAEC0 | 132 | R-109 (200) | robot | r109 (406) | from start (kind 1) | chr133.xbr | chr133 |
| 20 | 0x2BAEE0 | 2 | Monkey (69) | aztec | monkey (350) | from start (kind 1) | chr03.xbr, chr03lod2.xbr | chr03 |
| 21 | 0x2BAF00 | 45 | Hybrid Mutant (112) | siberia | mutantsoldier (442) | story level 0, difficulty 1 (kind 2) | chr46.xbr, chr46lod2.xbr, chr46_head.xbr, chr46_larm.xbr, chr46_rarm.xbr | chr46 |
| 22 | 0x2BAF20 | 13 | Big Tony (80) | gangster | godfather (392) | story level 1, difficulty 1 (kind 2) | chr14.xbr, chr14lod2.xbr, chr14_hat.xbr | chr14 |
| 23 | 0x2BAF40 | 104 | Jacque de la Morte (173) | notredame | notreboss (368) | story level 2, difficulty 1 (kind 2) | chr105.xbr, chr105_hat.xbr | chr105 |
| 24 | 0x2BAF60 | 123 | Ozor Mox (192) | planetx | alien (374) | story level 3, difficulty 1 (kind 2) | chr124.xbr, chr124lod2.xbr | chr124 |
| 25 | 0x2BAF80 | 99 | Sadako (167) | neo | gangleader (346) | story level 4, difficulty 1 (kind 2) | chr100.xbr, chr100lod2.xbr, chr100_hat.xbr | chr100 |
| 26 | 0x2BAFA0 | 0 | The Colonel (67) | west | evilcowboy (359) | story level 5, difficulty 1 (kind 2) | chr01.xbr, chr01lod2.xbr | chr01 |
| 27 | 0x2BAFC0 | 117 | Khallos (186) | atom | villain (373) | story level 6, difficulty 1 (kind 2) | chr118.xbr, chr118lod2.xbr | chr118 |
| 28 | 0x2BAFE0 | 15 | Stone Golem (70) | aztec | stonegolem (414) | story level 7, difficulty 1 (kind 2) | chr16.xbr | chr16 |
| 29 | 0x2BB000 | 48 | Machinist (115) | robot | kidrobot (396) | story level 8, difficulty 1 (kind 2) | chr49.xbr, chr49lod2.xbr | chr49 |
| 30 | 0x2BB020 | 55 | Reaper Splitter (122) | spacestation | bezerker (377) | story level 9, difficulty 1 (kind 2) | chr56.xbr, chr56lod2.xbr | chr56 |
| 31 | 0x2BB040 | 7 | Hector Baboso (74) | west | mexican (403) | entry 21, medal 2 (kind 4) | chr08.xbr, chr08lod2.xbr, chr08_hat.xbr | chr08 |
| 32 | 0x2BB060 | 11 | Lean Molly (78) | west | skinnyhooer (412) | entry 21, medal 3 (kind 4) | chr12.xbr, chr12lod2.xbr | chr12 |
| 33 | 0x2BB080 | 116 | Dr. Peabody (185) | atom | scientist (371) | entry 22, medal 2 (kind 4) | chr117.xbr, chr117lod2.xbr | chr117 |
| 34 | 0x2BB0A0 | 135 | Crypt Zombie (203) | notredame | cryptzombie (357) | entry 22, medal 3 (kind 4) | chr136.xbr, chr136lod2.xbr, chr136_head.xbr, chr136_larm.xbr, chr136_rarm.xbr | chr136 |
| 35 | 0x2BB0C0 | 49 | ChassisBot (116) | robot | chassisbot (384) | entry 26, medal 3 (kind 4) | chr50.xbr | chr50 |
| 36 | 0x2BB0E0 | 145 | SentryBot (114) | robot | bigrobot (379) | entry 27, medal 3 (kind 4) | chr146.xbr, chr146lod2.xbr | chr146 |
| 37 | 0x2BB100 | 124 | Meezor Mox (193) | planetx | redalien (407) | entry 28, medal 3 (kind 4) | chr125.xbr, chr125lod2.xbr | chr125 |
| 38 | 0x2BB120 | 131 | Male Trooper (199) | spacestation | trooper (449) | entry 29, medal 2 (kind 4) | chr132.xbr | chr132 |
| 39 | 0x2BB140 | 130 | Female Trooper (198) | spacestation | femtrooper (429) | entry 29, medal 3 (kind 4) | chr131.xbr | chr131 |
| 40 | 0x2BB160 | 141 | Crispin (209) | circus | burningman (466) | entry 30, medal 3 (kind 4) | chr142.xbr | chr142 |
| 41 | 0x2BB180 | 51 | Undead Priest (118) | notredame | priestzombie (353) | entry 31, medal 3 (kind 4) | chr52.xbr, chr52lod2.xbr | chr52 |
| 42 | 0x2BB1A0 | 52 | Louie Bignose (119) | gangster | bignose (378) | entry 32, medal 2 (kind 4) | chr53.xbr, chr53lod2.xbr, chr53_hat.xbr | chr53 |
| 43 | 0x2BB1C0 | 65 | Slick Tommy (133) | gangster | suit (416) | entry 33, medal 2 (kind 4) | chr66.xbr, chr66lod2.xbr, chr66_hat.xbr | chr66 |
| 44 | 0x2BB1E0 | 66 | Jimmy Needles (134) | gangster | suitbeige (415) | entry 33, medal 3 (kind 4) | chr67.xbr, chr67lod2.xbr, chr67_hat.xbr | chr67 |
| 45 | 0x2BB200 | 90 | Accountant (158) | gangster | ped1 (467) | entry 35, medal 3 (kind 4) | chr91.xbr | chr91 |
| 46 | 0x2BB220 | 91 | Lawyer (159) | gangster | ped2 (468) | entry 35, medal 3 (kind 4) | chr92.xbr | chr92 |
| 47 | 0x2BB240 | 12 | Braces (79) | gangster | braces (381) | entry 43, medal 2 (kind 4) | chr13.xbr, chr13lod2.xbr, chr13_hat.xbr | chr13 |
| 48 | 0x2BB260 | 56 | Maiden (123) | notredame | virgin_b (344) | entry 60, medal 2 (kind 4) | chr57.xbr, chr57lod2.xbr | chr57 |
| 49 | 0x2BB280 | 62 | Jo-Beth Casey (130) | atom | jobeth (364) | entry 51, medal 2 (kind 4) | chr63.xbr, chr63lod2.xbr | chr63 |
| 50 | 0x2BB2A0 | 102 | Riot Officer (172) | neo | police (370) | entry 37, medal 2 (kind 4) | chr103.xbr, chr103lod2.xbr | chr103 |
| 51 | 0x2BB2C0 | 101 | Barby Gimp (169) | neo | kimono (365) | entry 49, medal 2 (kind 4) | chr102.xbr, chr102lod2.xbr, chr102_hat.xbr | chr102 |
| 52 | 0x2BB2E0 | 9 | Jebediah Crump (76) | west | miner (349) | entry 65, medal 2 (kind 4) | chr10.xbr, chr10lod2.xbr, chr10_hat.xbr | chr10 |
| 53 | 0x2BB300 | 113 | Venus Starr (182) | west | pinupcowgirl (351) | entry 47, medal 2 (kind 4) | chr114.xbr, chr114lod2.xbr, chr114_hat.xbr | chr114 |
| 54 | 0x2BB320 | 112 | Mikey Two-guns (181) | west | jamescowboy (395) | entry 58, medal 2 (kind 4) | chr113.xbr, chr113lod2.xbr | chr113 |
| 55 | 0x2BB340 | 8 | Jared Slim (75) | west | curtains (385) | entry 58, medal 3 (kind 4) | chr09.xbr, chr09lod2.xbr | chr09 |
| 56 | 0x2BB360 | 10 | Ample Sally (77) | west | saloonhooer (409) | entry 9, medal 2 (kind 4) | chr11.xbr, chr11lod2.xbr | chr11 |
| 57 | 0x2BB380 | 115 | Henchman (184) | atom | henchman (361) | entry 61, medal 2 (kind 4) | chr116.xbr, chr116lod2.xbr, chr116_hat.xbr | chr116 |
| 58 | 0x2BB3A0 | 95 | Cyberfairy (163) | robot | cyberfairy (386) | entry 41, medal 3 (kind 4) | chr96.xbr, chr96lod2.xbr | chr96 |
| 59 | 0x2BB3C0 | 121 | Kypriss (190) | circus | sixarms (411) | entry 59, medal 2 (kind 4) | chr122.xbr | chr122 |
| 60 | 0x2BB3E0 | 120 | Mister Giggles (189) | circus | scaryclown (410) | entry 62, medal 2 (kind 4) | chr121.xbr | chr121 |
| 61 | 0x2BB400 | 53 | Marco the Snitch (120) | gangster | snitch (413) | entry 10, medal 2 (kind 4) | chr54.xbr, chr54lod2.xbr | chr54 |
| 62 | 0x2BB420 | 67 | Hatchet Sal (135) | gangster | greysuit (393) | entry 50, medal 2 (kind 4) | chr68.xbr, chr68lod2.xbr | chr68 |
| 63 | 0x2BB440 | 57 | Changeling (124) | notredame | monstervirgin (441) | entry 60, medal 3 (kind 4) | chr58.xbr, chr58lod2.xbr | chr58 |
| 64 | 0x2BB460 | 105 | The Hunchback (174) | notredame | hunchback (362) | entry 2, medal 2 (kind 4) | chr106.xbr | chr106 |
| 65 | 0x2BB480 | 54 | Sewer Zombie (121) | notredame | sewerzombie_b (343) | entry 15, medal 2 (kind 4) | chr55.xbr, chr55lod2.xbr, chr55_head.xbr, chr55_larm.xbr, chr55_rarm.xbr | chr55 |
| 66 | 0x2BB4A0 | 134 | Gargoyle (202) | notredame | gargoyle (356) | entry 41, medal 2 (kind 4) | chr135.xbr | chr135 |
| 67 | 0x2BB4C0 | 129 | The Cropolite (126) | notredame | bigmonster (354) | entry 12, medal 2 (kind 4) | chr130.xbr | chr130 |
| 68 | 0x2BB4E0 | 149 | Beetleman (214) | planetx | beetleman (463) | entry 52, medal 2 (kind 4) | chr150.xbr, chr150lod2.xbr | chr150 |
| 69 | 0x2BB500 | 144 | Dark Henchman (212) | atom | darkhench (358) | entry 61, medal 3 (kind 4) | chr145.xbr, chr145lod2.xbr, chr145_hat.xbr | chr145 |
| 70 | 0x2BB520 | 119 | High Priest (188) | aztec | priest (352) | entry 57, medal 3 (kind 4) | chr120.xbr | chr120 |
| 71 | 0x2BB540 | 34 | Wood Golem (71) | aztec | woodgolem (420) | entry 8, medal 2 (kind 4) | chr35.xbr | chr35 |
| 72 | 0x2BB560 | 118 | Aztec Warrior (187) | aztec | fighter (389) | entry 57, medal 2 (kind 4) | chr119.xbr, chr119lod2.xbr | chr119 |
| 73 | 0x2BB580 | 59 | The Master (127) | neo | monk (367) | entry 37, medal 3 (kind 4) | chr60.xbr, chr60lod2.xbr | chr60 |
| 74 | 0x2BB5A0 | 60 | Krayola (128) | neo | tatnin (372) | entry 36, medal 3 (kind 4) | chr61.xbr, chr61lod2.xbr | chr61 |
| 75 | 0x2BB5C0 | 98 | Milkbaby (166) | neo | bodywarmer (355) | entry 36, medal 2 (kind 4) | chr99.xbr, chr99lod2.xbr, chr99_hat.xbr | chr99 |
| 76 | 0x2BB5E0 | 128 | Drone Splitter (197) | spacestation | helper (394) | entry 64, medal 2 (kind 4) | chr129.xbr, chr129lod2.xbr | chr129 |
| 77 | 0x2BB600 | 142 | Baby Drone (210) | spacestation | babyhelper (375) | entry 55, medal 2 (kind 4) | chr143.xbr, chr143lod2.xbr | chr143 |
| 78 | 0x2BB620 | 126 | Scourge Splitter (195) | spacestation | bosssplitter (380) | entry 49, medal 3 (kind 4) | chr127.xbr | chr127 |
| 79 | 0x2BB640 | 96 | R One-Oh-Seven (164) | robot | r107 (405) | entry 14, medal 2 (kind 4) | chr97.xbr, chr97lod2.xbr | chr97 |
| 80 | 0x2BB660 | 93 | Feeder Zombie (161) | notredame | tshirtzombie (421) | entry 16, medal 2 (kind 4) | chr94.xbr, chr94lod2.xbr, chr94_head.xbr, chr94_larm.xbr, chr94_rarm.xbr | chr94 |
| 81 | 0x2BB680 | 110 | Stumpy (179) | circus | dwarfclown (387) | entry 62, medal 3 (kind 4) | chr111.xbr, chr111_hat.xbr | chr111 |
| 82 | 0x2BB6A0 | 136 | Lola Varuska (204) | circus | trapeze (417) | entry 19, medal 3 (kind 4) | chr137.xbr | chr137 |
| 83 | 0x2BB6C0 | 137 | Nikki (205) | circus | twoface (419) | entry 53, medal 2 (kind 4) | chr138.xbr | chr138 |
| 84 | 0x2BB6E0 | 138 | Jinki (206) | circus | twofacemon (418) | entry 53, medal 3 (kind 4) | chr139.xbr | chr139 |
| 85 | 0x2BB700 | 139 | Ringmistress (207) | circus | ringleader (408) | entry 54, medal 2 (kind 4) | chr140.xbr, chr140_hat.xbr | chr140 |
| 86 | 0x2BB720 | 143 | Calamari (211) | spacestation | octo (404) | entry 46, medal 2 (kind 4) | chr144.xbr | chr144 |
| 87 | 0x2BB740 | 140 | Snowman (208) | siberia | snowman (443) | entry 45, medal 2 (kind 4) | chr141.xbr | chr141 |
| 88 | 0x2BB760 | 109 | Bear (178) | circus | bear (376) | entry 55, medal 3 (kind 4) | chr110.xbr, chr110_hat.xbr | chr110 |
| 89 | 0x2BB780 | 64 | Leo Krupps (132) | circus | lionsuit (398) | entry 40, medal 2 (kind 4) | chr65.xbr | chr65 |
| 90 | 0x2BB7A0 | 148 | Sergio (213) | siberia | strongman (462) | entry 17, medal 2 (kind 4) | chr149.xbr | chr149 |
| 91 | 0x2BB7C0 | 150 | Mischief (215) | circus | girlclown (391) | entry 19, medal 2 (kind 4) | chr151.xbr | chr151 |
| 92 | 0x2BB7E0 | 151 | The Impersonator (216) | ts1 | impersonator (459) | entry 52, medal 3 (kind 4) | chr152.xbr | chr152 |
| 93 | 0x2BB800 | 152 | Badass Cyborg (217) | ts1 | badasscyborg (455) | entry 13, medal 2 (kind 4) | chr153.xbr | chr153 |
| 94 | 0x2BB820 | 153 | Chinese Chef (218) | ts1 | chinesechef (456) | entry 42, medal 3 (kind 4) | chr154.xbr | chr154 |
| 95 | 0x2BB840 | 154 | Duckman Drake (219) | ts1 | duckman (457) | entry 48, medal 2 (kind 4) | chr155.xbr | chr155 |
| 96 | 0x2BB860 | 155 | Gingerbread Man (220) | ts1 | gingerbread (458) | entry 42, medal 2 (kind 4) | chr156.xbr | chr156 |
| 97 | 0x2BB880 | 156 | Insect Mutant (221) | ts1 | insectmutant (460) | entry 18, medal 2 (kind 4) | chr157.xbr | chr157 |
| 98 | 0x2BB8A0 | 157 | Robofish (222) | ts1 | robofish (461) | entry 20, medal 2 (kind 4) | chr158.xbr | chr158 |
| 99 | 0x2BB8C0 | 122 | Dinosaur (191) | aztec | dinosaur (465) | entry 63, medal 2 (kind 4) | chr123.xbr | chr123 |
| 100 | 0x2BB8E0 | 30 | Handyman (97) | ts1 | handman (464) | entry 50, medal 3 (kind 4) | chr31.xbr, chr31lod2.xbr | chr31 |
| 101 | 0x2BB900 | 18 | Nikolai (85) | siberia | articberet (430) | from start (kind 1) | chr19.xbr, chr19lod2.xbr, chr19_hat.xbr | chr19 |
| 102 | 0x2BB920 | 19 | Private Sand (86) | siberia | desertberet (436) | entry 24, medal 3 (kind 4) | chr20.xbr, chr20lod2.xbr, chr20_hat.xbr | chr20 |
| 103 | 0x2BB940 | 20 | Private Grass (87) | siberia | woodberet (450) | from start (kind 1) | chr21.xbr, chr21lod2.xbr, chr21_hat.xbr | chr21 |
| 104 | 0x2BB960 | 21 | Private Coal (88) | siberia | spforceberet (444) | entry 6, medal 2 (kind 4) | chr22.xbr, chr22lod2.xbr, chr22_hat.xbr | chr22 |
| 105 | 0x2BB980 | 22 | Private Poorly (89) | siberia | zombieberet (422) | entry 7, medal 2 (kind 4) | chr23.xbr, chr23lod2.xbr, chr23_hat.xbr, chr23_head.xbr, chr23_larm.xbr, chr23_rarm.xbr | chr23 |
| 106 | 0x2BB9A0 | 23 | Sgt Rock (90) | siberia | deserthelmet (439) | entry 11, medal 2 (kind 4) | chr24.xbr, chr24lod2.xbr | chr24 |
| 107 | 0x2BB9C0 | 24 | Sgt Shivers (91) | siberia | artichelmet (433) | from start (kind 1) | chr25.xbr, chr25lod2.xbr | chr25 |
| 108 | 0x2BB9E0 | 25 | Sgt Wood (92) | siberia | woodhelmet (453) | from start (kind 1) | chr26.xbr, chr26lod2.xbr | chr26 |
| 109 | 0x2BBA00 | 26 | Sgt Shock (93) | siberia | spforcehelmet (447) | entry 23, medal 3 (kind 4) | chr27.xbr, chr27lod2.xbr | chr27 |
| 110 | 0x2BBA20 | 27 | Sgt Slate (94) | siberia | zombiehelmet (425) | entry 24, medal 3 (kind 4) | chr28.xbr, chr28lod2.xbr, chr28_head.xbr, chr28_larm.xbr, chr28_rarm.xbr | chr28 |
| 111 | 0x2BBA40 | 28 | Lt Frost (95) | siberia | articfesold (431) | from start (kind 1) | chr29.xbr, chr29lod2.xbr, chr29_hat.xbr | chr29 |
| 112 | 0x2BBA60 | 29 | Lt Wild (96) | siberia | desertfesold (437) | entry 32, medal 3 (kind 4) | chr30.xbr, chr30lod2.xbr, chr30_hat.xbr | chr30 |
| 113 | 0x2BBA80 | 31 | Lt Shade (98) | siberia | spforcefesold (445) | entry 34, medal 3 (kind 4) | chr32.xbr, chr32lod2.xbr, chr32_hat.xbr | chr32 |
| 114 | 0x2BBAA0 | 32 | Lt Bush (99) | siberia | woodfesold (451) | from start (kind 1) | chr33.xbr, chr33lod2.xbr, chr33_hat.xbr | chr33 |
| 115 | 0x2BBAC0 | 33 | Lt Chill (100) | siberia | zombiefesold (423) | entry 39, medal 3 (kind 4) | chr34.xbr, chr34lod2.xbr, chr34_hat.xbr, chr34_head.xbr, chr34_larm.xbr, chr34_rarm.xbr | chr34 |
| 116 | 0x2BBAE0 | 35 | Trooper White (102) | siberia | articgasmask (432) | from start (kind 1) | chr36.xbr, chr36lod2.xbr | chr36 |
| 117 | 0x2BBB00 | 36 | Trooper Brown (103) | siberia | desertgasmask (438) | entry 43, medal 3 (kind 4) | chr37.xbr, chr37lod2.xbr | chr37 |
| 118 | 0x2BBB20 | 37 | Trooper Black (104) | siberia | spforcegasmask (446) | entry 44, medal 3 (kind 4) | chr38.xbr, chr38lod2.xbr | chr38 |
| 119 | 0x2BBB40 | 38 | Trooper Green (105) | siberia | woodgasmask (452) | from start (kind 1) | chr39.xbr, chr39lod2.xbr | chr39 |
| 120 | 0x2BBB60 | 39 | Trooper Grey (106) | siberia | zombiegasmask (424) | entry 45, medal 3 (kind 4) | chr40.xbr, chr40lod2.xbr, chr40_head.xbr, chr40_larm.xbr, chr40_rarm.xbr | chr40 |
| 121 | 0x2BBB80 | 40 | Capt Snow (107) | siberia | articveil (434) | from start (kind 1) | chr41.xbr, chr41lod2.xbr | chr41 |
| 122 | 0x2BBBA0 | 41 | Capt Sand (108) | siberia | desertveil (440) | entry 47, medal 3 (kind 4) | chr42.xbr, chr42lod2.xbr | chr42 |
| 123 | 0x2BBBC0 | 42 | Capt Night (109) | siberia | spforceveil (448) | entry 48, medal 3 (kind 4) | chr43.xbr, chr43lod2.xbr | chr43 |
| 124 | 0x2BBBE0 | 43 | Capt Forest (110) | siberia | woodveil (454) | from start (kind 1) | chr44.xbr, chr44lod2.xbr | chr44 |
| 125 | 0x2BBC00 | 44 | Capt Pain (111) | siberia | zombieveil (426) | entry 38, medal 3 (kind 4) | chr45.xbr, chr45lod2.xbr, chr45_head.xbr, chr45_larm.xbr, chr45_rarm.xbr | chr45 |
| 126 | 0x2BBC20 | 92 | Consultant (160) | gangster | ped3 (469) | never (kind 0) | chr93.xbr | chr93 |

Notes (measured unless marked):

- The 127 chr ids in the roster are all different; 126 are selectable.
  Entry 126, Consultant (chr93, `ped3` portrait), has kind 0 and is never
  shown: an unused 127th slot.
- Portrait `chrimage_*` textures 342-469 are 128; the roster uses 127 of
  them. The one left over is 435, `chrimage_darkarticgasmask` (no roster
  entry; plausibly meant for Gasmask Special, chr95, which is not
  selectable: inferred).
- Some characters exist twice under different chr ids with the same name
  (Stone Golem 3/15, Wood Golem 4/34, SentryBot 47/145, R One-Oh-Seven 96/103,
  Corp Hart 127/146, Sgt Cortez 106/147); only one of each pair is in the
  roster (Stone Golem 15, Wood Golem 34, SentryBot 145, R107 96, Hart 127,
  Cortez 106).

## Characters that are not playable

chr ids with a definition entry but no roster entry (measured). Models are
object-list indices.

| chr id | File | Name (text id) | Model idx / lod idx | chr.pak | chrinc.pak |
|---|---|---|---|---|---|
| 3 | chr04 | Stone Golem (70) | 5 / - | chr04.xbr | yes |
| 4 | chr05 | Wood Golem (71) | 6 / - | chr05.xbr | yes |
| 16 | chr17 | Barrel Robot (83) | 28 / - | chr17.xbr | yes |
| 17 | chr18 | Railspider Robot (84) | 29 / - | (none) | no |
| 47 | chr48 | SentryBot (114) | 86 / - | chr48.xbr, chr48lod2.xbr | yes |
| 58 | chr59 | Portal Daemon (125) | 107 / - | chr59.xbr | yes |
| 63 | chr64 | X-Ray Skel (131) | 116 / - | chr64.xbr | yes |
| 70 | chr71 | NeoTokyo male pedestrian 1 (138) | 128 / - | chr71.xbr | yes |
| 71 | chr72 | NeoTokyo male pedestrian 2 (139) | 129 / - | chr72.xbr | yes |
| 72 | chr73 | NeoTokyo male pedestrian 3 (140) | 130 / - | chr73.xbr | yes |
| 73 | chr74 | NeoTokyo male pedestrian 4 (141) | 131 / - | chr74.xbr | yes |
| 74 | chr75 | NeoTokyo male pedestrian 5 (142) | 132 / - | chr75.xbr | yes |
| 75 | chr76 | NeoTokyo male pedestrian 6 (143) | 133 / - | chr76.xbr | yes |
| 76 | chr77 | NeoTokyo male pedestrian 7 (144) | 134 / - | chr77.xbr | yes |
| 77 | chr78 | NeoTokyo male pedestrian 8 (145) | 135 / - | chr78.xbr | yes |
| 78 | chr79 | NeoTokyo male pedestrian 9 (146) | 136 / - | chr79.xbr | yes |
| 79 | chr80 | NeoTokyo male pedestrian 10 (147) | 137 / - | chr80.xbr | yes |
| 80 | chr81 | NeoTokyo female pedestrian 1 (148) | 138 / - | chr81.xbr | yes |
| 81 | chr82 | NeoTokyo female pedestrian 2 (149) | 139 / - | chr82.xbr | yes |
| 82 | chr83 | NeoTokyo female pedestrian 3 (150) | 140 / - | chr83.xbr | yes |
| 83 | chr84 | NeoTokyo female pedestrian 4 (151) | 141 / - | chr84.xbr | yes |
| 84 | chr85 | NeoTokyo female pedestrian 5 (152) | 142 / - | chr85.xbr | yes |
| 85 | chr86 | NeoTokyo female pedestrian 6 (153) | 143 / - | chr86.xbr | yes |
| 86 | chr87 | NeoTokyo female pedestrian 7 (154) | 144 / - | chr87.xbr | yes |
| 87 | chr88 | NeoTokyo female pedestrian 8 (155) | 145 / - | chr88.xbr | yes |
| 88 | chr89 | NeoTokyo female pedestrian 9 (156) | 146 / - | chr89.xbr | yes |
| 89 | chr90 | NeoTokyo female pedestrian 10 (157) | 147 / - | chr90.xbr | yes |
| 94 | chr95 | Gasmask Special (162) | 153 / - | chr95.xbr | yes |
| 103 | chr104 | R One-Oh-Seven (164) | 156 / - | (none) | yes |
| 146 | chr147 | Corp Hart (196) | 227 / - | chr147.xbr | no |
| 147 | chr148 | Sgt Cortez (175) | 228 / - | chr148.xbr | no |
| 158 | drillhead.xbr (not a chrNN) | Dark Henchman (212) | 240 / - | (none) | no |
| 159 | nailhead.xbr (not a chrNN) | Dark Henchman (212) | 241 / - | (none) | no |
| 160 | sawarm.xbr (not a chrNN) | Dark Henchman (212) | 242 / - | (none) | no |
| 161 | transfusionsplitter.xbr (not a chrNN) | Dark Henchman (212) | 243 / - | (none) | no |

Also not playable (measured): chr18 (Railspider Robot) has a definition and
an object-list entry but no file in chr.pak or chrinc.pak; chr104 exists only
in chrinc.pak (its definition, chr id 103, uses `chr97.xbr`); chr147 and chr148
(the second Hart and Cortez) are in chr.pak but not chrinc.pak. Every other
chrNN in chr.pak (chr01-chr158 except chr18 and chr104) belongs to a
definition entry, so chr.pak holds no model the definition table does not
name.

## What adding a character would take

All three tables are fixed-size arrays inside `.data`, each followed directly
by other data, and indexed by displacement off a hard-coded base, so none can
grow in place (code; layout measured).

| Table | Size | Followed by | References | Hard-coded counts |
|---|---|---|---|---|
| Roster `0x002BAC60` | 127 x 0x20 | the default-character dwords at `0x002BBC40` | 26 code references in 15 functions (bases `0x2BAC60`, `0x2BAC64`, `0x2BAC6C`) | `0x7F` (127) at `0x00087AA8`, `0x00087AE8`, `0x0008E28C`, `0x0008FB6E`, `0x0009CCD8`; `0xFE0` (127 x 0x20) at `0x00087C32`, `0x00087C62`, `0x00087CC7`, `0x0009531B`, `0x00098F5E`, `0x0009946E`, `0x000A3D1C`; grid 14 x 9 at `0x00099C97`, `0x00099CA1` |
| Unlock snapshot `0x0035C2D8` (BSS) | 127 dwords | `0x0035C4D4`, another global, immediately after | 2 | as the roster (`0xFE0` loop in `sub_000952C0`), and `0x1FC` (127 x 4) at `0x00095504` in `sub_000954B0` |
| Definitions `0x002AA060` | 162 x 0x44 | other data at `0x002ACB68` | 77 references in 38 functions | none found (no loop over all of them) |
| Flags `0x002ACB78` | 161 x 0x14 | other data | 4 | none found |
| Object list `0x002D8E14` | 1324 x 0x24 | other data | 29 (mostly `[idx*4 + 0x2D8E24]` after `lea idx, [i + i*8]`) | `0x52C` (1324) at `0x0001BD0D`, `0x000210D9`, `0x0006A98A` |
| Texture list `0x002BF7B0` (paths at +8) | 548 x 0x10 | another table at `0x002C19F0` | 36 (33 inside, 3 loop ends) | `0x224` at `0x000A9BEB` |
| Strings `0x003362F0` | 5 languages x 2770 | | 1,370 | not checked |

Chr ids themselves are not bounded: the player keeps a 16-bit id, the
profile a 32-bit one, chrinc names are `%02d` of `id + 1` (code). The hat
`switch` (`sub_00042030`) covers ids 5-144 and returns no hat outside it
(code).

Save data: a new character adds no save field, because unlocks are derived
from story and medal bits (code). Its unlock condition can reuse any
existing kind. The profile's +0xD0 stores the chr id, so a profile saved with
a new id needs that id to exist when the profile is loaded by an unmodified
game (inferred). Saves are signed (above), which only matters for editing a
save by hand.

Two routes follow from this:

1. **Re-skin an existing chr id** (no code change). Pick a chr id that is
   not playable and not used by any level you want to keep (for example a
   NeoTokyo pedestrian, chr ids 70-89: they appear only in NeoTokyo's story
   cast and in cast records 13-14) or
   replace a playable one. Replace `chrNN.xbr` (and `lod2`, textures) in
   chr.pak, in chrinc.pak for the preview, and in every level pak that
   carries that chr (each level pak has its own copy, and a level's copy wins
   over chr.pak). Patch the name (its string, or the definition's text id to
   another string), the sound set pointer, and, for a non-playable id, turn
   roster entry 126 (Consultant, kind 0) into it: set its +0 to the new chr
   id, its portrait (+4), and its kind to 1. That 127th entry then fails the
   14 x 9 grid: `sub_00099430`'s `rows * columns - count` clamps at 0 and
   `sub_00098F40` would put it on a 10th row (index 126 / 14), so the row
   count (`0x00099CA1`) or the column count (`0x00099C97`) probably has to
   change too (inferred from code; not tried).
   All of this is data plus two immediates, i.e. a per-game patch in
   `src/recomp_manual.c` or a modified XBE.
2. **A genuinely new chr id.** Move the roster (and the 127-dword snapshot)
   to a larger array and patch the 26 references and 12 count immediates
   above, or override the 15 roster functions in `src/recomp_manual.c` so
   they read a host-side table; extend the definitions and flags tables
   (relocate, or redirect the 38 + 4 functions); add object-list entries for
   the new `.xbr` files (relocate the 1324-entry list and its 3 counts); add
   the portrait to the texture list; and add the files to chr.pak and
   chrinc.pak (`chr{id+1:02d}.xbr`). Overriding the accessor functions in
   `recomp_manual.c` is the more contained of the two: every roster access
   goes through those 15 functions, and the definition table through
   `[id * 0x44 + base]` displacements in 38 (code).

Either way, arcade is where a new character can appear without touching
level paks: arcade levels mount chr.pak behind the level pak. A story level
mounts only its own pak, so a character used in story needs its files added
to that level's pak (code; coordinator's measurement for the story half).

## Experiment: a 127th entry on the grid (15 Oct 2026, not kept)

A hook on `sub_00099960` (PAL) wrote roster entry 126 to chr id 70 with kind
1 before the function ran, and set the row count to 10 after it (the
function's last stores are columns `0x35C80C` = 14 and rows `0x35F4A4` = 9).
Measured in scripted runs (frame dumps):

- `sub_00099960` belongs to the **Gallery** (Options > Player Options > View
  Gallery), reached through a screen record at `0x2BCE48` (five words; it is
  paired with `sub_00099FF0`). Nothing on the way into a 1-player Arcade
  Custom match (difficulty, mode, map, options, Go) runs it.
- With 10 rows the grid kept its cell size and the tenth row ran off the
  bottom of the panel, so the cell size or the panel has to change too.
- The "Player 1 < name >" selector in Player Options switches profiles. The
  names it showed (Big Tony, Ilsa Nadir, Cyberfairy) are the default names
  given to a new profile, not a character choice.

Where a player picks the character they play as is the **Select Character**
screen, below; it is not the 14 x 9 grid.

Menu path for scripted runs from a fresh save (PAL): the story script's first
five steps (`start` x4, `a`) reach the main menu (Story, Arcade, Challenge,
MapMaker, Options); then `down` x4 and `a` open Options, `a` Player Options,
`down` x5 and `a` the Gallery; or `down`, `a`, `down`, `a` for Arcade Custom.

## The Select Character screen (Arcade)

Measured in scripted runs (15 Oct 2026), code read at the addresses given.

- **When it appears:** after **GO!** on the match Options screen, every time.
  The flow from Arcade Custom is difficulty, game type, map, Options
  (rules, Weapon Set, Bot Set, the cursor starting on GO!), then Select
  Character, then the match. GO!'s action is `sub_00090A10`: it sets every
  player's select state (`0x0035CA84`, one byte per player) to 1 and opens
  the screen record at `0x002BBE10` (a single-player challenge, mode 0x12,
  can skip it). The screen lists the profile's last character first and
  `a` confirms it at once, so a script pressing `a` every 4 s passes the
  screen in under a second. Frame dumps 5 s apart then show it in one run and
  not the next: that was the "sometimes". It is always there; dump more
  often after GO!, or press `up` there (the list wraps to its last entry).
- **Code:** `sub_000A2A10` builds the screen per player and moves on once
  every player's state is 5 (chosen); per player it loads the preview
  (`sub_000A0770` → `sub_0009E410`, `ob/chrincs/chr%02d.xbr`) and builds the
  column through the record at `0x002BBDA8`, whose builder is
  `sub_000A3D90`. That makes one header item (draw `sub_0008F550`: the name
  from the definition's text id, the Accuracy/Agility/Stamina bars) and calls
  `sub_000A3C60`, which adds **one item per roster entry whose unlock rule
  passes** (`sub_001AEE50(chr id)`), in table order, each with the chr id at
  item +0x18, draw `sub_0008FAE0` (finds the entry by chr id in the 127
  entries, draws its portrait through `sub_000A9AE0(texture)`) and action
  `0x000A2910`. In modes 6 and 7 the list is one fixed character.
- So an entry turned on in the roster table appears here, in the bot list
  (Options > Bot Set: `sub_0008DEE0` walks the roster the same way, "Available
  Bots") and in the Gallery, with no code change.

## Strings

`0x003362F0` holds one pointer per language (English, French, German,
Italian, Spanish; `[0x00386734]` is the current one), each to an array of
2770 pointers to NUL-terminated Latin-1 strings (`Pr\xe4zision`). Code reads
them as `[table + id * 4]` with the id baked into the instruction, so an id
is renamed by repointing its entry in each table. Ids met here:

| Id | Text |
|---|---|
| 67-222 | Character names, in chr id order (definition +0x00) |
| 625 + chr id | The Gallery's description of that character, ending in `\n` (`sub_00099430` at `0x0009984B`); empty (`\n`) for the unplayed ids |
| 246, 248 | "Select Character", "\x0b2 Select" (`\x0b` + digit is a button glyph) |
| 245, 839, 840 | "Setup Bots", "Current Bot Set", "Available Bots" |
| 390 | "Not available" (Gallery, locked entry) |
| 479-481 | Stamina, Agility, Accuracy |

Text 138 (chr id 70's name, "NeoTokyo male pedestrian 1") is read nowhere
but through the definition: no instruction names it directly.

## Portraits

The roster's +4 indexes the texture list at `0x002BF7B8` (548 entries of
0x10; the dword at +0 is a pointer to the path, +4 the loaded handle that
`sub_000A9AE0` returns). The path is `host0:textures/misc/chrimage_<x>.raw`
and the file read is `textures/misc/chrimage_<x>.xbt` in a mounted pak: a
new name in the same form works (measured). The loader (`sub_000A9BE0` →
`sub_0014A3F0`) keeps the path pointer, so a new path must stay in guest
memory. The `chrimage_*` files are in `data/arcade/l_101.pak` (the front
end), `l_102.pak` and `gun.pak`; a match ran to its end without the new
file in `gun.pak`, but where `gun.pak`'s copies are shown was not traced.

## The Gallery grid

`sub_00099960` builds it and sets 14 columns and 9 rows last;
`sub_00098F40` draws it: cell `i` at row `i / columns`, x =
`rect.x + 5 + ((col + 1) * w + w / 2) * 0.45` with `w` the portrait's size
and 0.45 the float at `0x00222534` (read by six other functions too), y the
same with the row. It draws the first `n` entries, `n` = entries whose kind
is not 0. The cursor (`sub_00099430`) moves by the column count and wraps
by `rows * columns - n`, so a part-filled last row works. 127 entries in 15
columns at 14/15 of the spacing fill 8 rows and 7 cells of a ninth, in the
panel's old width (measured).

## Room for more characters (the XBE patch)

Every PAL lift applies `config/pal/xbe_patches.json` (written by
`tools/ts2_roster_patches.py`; the format is xboxrecomp's
`docs/technical/xbe-patches.md`). It adds a section, `TS2ROSTER` at
`0x004CE000` (0x4000 bytes, after `dsstdfx`, the last one), moves three
tables into it with room for **32 spare roster slots**, and repoints the
code. `scripts/build.py` passes the file with the release (chosen by the
XBE's SHA-1, as the seeds are) and writes its SHA-1 into
`src/recomp/ts2_region.h` (`TS2_XBE_PATCHES_SHA1`); a changed file means a
new lift. USA has no patch file and is lifted with `--no-xbe-patches`.

| Table | Was | Now |
|---|---|---|
| Roster | 127 x 0x20 at `0x002BAC60` | 159 x 0x20 at `0x004CE000`, then a sentinel entry (chr id -1) |
| Unlock snapshot | 127 dwords at `0x0035C2D8` (BSS) | 159 dwords at `0x004CF400` |
| Texture list | 548 x 0x10 at `0x002BF7B0` | 580 x 0x10 at `0x004CF800` |

The texture list's entries are how to load (+0), load flags (+4, which
`sub_000A9B00` tests per level), path (+8) and handle (+0xC): the
"548 entries of 0x10 at `0x002BF7B8`" above is the same table seen from
its +8.

**Why 32.** New characters take chr ids that have files and a definition
but no roster entry (the 162-entry definition table does not grow): there
are 35 of them, and only some are safe (chr71-chr90, the NeoTokyo
pedestrians, are in no arcade pak). 32 covers all of those, keeps the
Gallery legible (158 shown entries make 18 columns of 9 rows) and costs
16 KB of image and nothing at run time. A different count is
`tools/ts2_roster_patches.py --spare N` and a new lift, with the numbers in
`config/pal/overrides.inc` changed to match.

**The spare slots** are copies of the Consultant's entry (slot 126, the
disc's one hidden character: chr id 92, gangster background, unlock kind 0)
with a texture of their own, 548-579. Each spare texture entry names the
Consultant's portrait with load flags 0, which no level loads. Kind 0 hides
an entry everywhere: `sub_001AEE50` returns 0 for it before anything else
(even the unlock-everything switches), and every screen and count below
asks that function or the kind. So without a mod the game shows, counts and
loads exactly what it did.

### The 78 patched sites

All found by scanning the PAL disassembly for operands inside each table or
at its end, and every byte of `.text` for the tables' addresses (two hits
were not operands but bytes across two instructions); then every function
that touches the roster for the counts 0x7F, 0x7E, 0xFE0, 0xFC0, 0x1FC and
0x1F8. No data in the image points into the three tables. The JSON gives
each site's reason.

| Sites | Count | What changes |
|---|---|---|
| Roster base, +4, +0xC (`sub_00087A90`, `87AD0`, `87C20`, `87CA0`, `8CED0`, `8DEE0`, `8FAE0`, `952C0`, `954B0`, `98E00`, `98F40`, `99430`, `99960`, `9CC00`, `A3C60`) | 26 | the new address |
| Snapshot (`sub_000952C0`, `954B0`) | 2 | the new address |
| `0xFE0` (127 x 0x20) loop ends: `0x00087C32`, `0x00087C62`, `0x00087CC7`, `0x0009531B`, `0x00098F5E`, `0x0009946E`, `0x000A3D1C` | 7 | 159 x 0x20 |
| `0x1FC` (127 x 4) at `0x00095504`, the new-unlock announcement's loop over the snapshot (**not in the list above**) | 1 | 159 x 4 |
| `cmp reg, 0x7F` in the chr id searches `0x00087AA8`, `0x00087AE8`, `0x0008E28C`, `0x0009CCD8` | 4 | `cmp dword ptr [ecx], -1`: see below |
| Texture list: `sub_000A9AE0`-`000A9E70`, `000AA3A0`-`000AB2E0` (its fields by index, and the handles of eleven textures read directly) | 33 | the new address |
| Texture list loop ends (`cmp esi, 0x2C19F4` / `0x2C19FC` in `sub_000A9C60`, `A9D20`, `A9D50`) | 3 | the new end |
| `cmp eax, 0x224` (548) in `sub_000A9BE0`, load by index | 1 | 580 |
| `and eax, 0x163` in `sub_000ED6F0`: the front end's menu items, 0x163 + 200 = 555 of 0x8C bytes | 1 | 0x1E3 (four more per spare slot: Select Character makes one item per unlocked character in each player's column, 4 x 127 already) |

**The `0x7F` searches.** Five loops find a roster entry by chr id with the
count as a sign-extended imm8 (`83 F8 7F`), which cannot hold more than
127, and a patch may not change an instruction's length. In four of them
`ecx` has just been moved to the next entry when the count is compared, so
`cmp eax, 0x7F` becomes `cmp dword ptr [ecx], -1` (`83 39 FF`, the same
length and mnemonic): the search stops at the sentinel after the last slot
instead of at 127. The fifth, `sub_0008FAE0` at `0x0008FB6E`, keeps its
pointer in `ebp`, and `[ebp]` needs a disp8 (4 bytes); it is left at 127
and hooked (below). Spare slots carry chr id 92, never -1, and a search
finds the first match, so the Consultant's own entry is found before them,
as before.

### What the hooks do

In `src/recomp_manual.c` (addresses in `config/pal/overrides.inc`); none of
it does anything without a mod's `ts2/characters.ini`:

- **`sub_0008FAE0`** (`ts2_chars_item_draw`) draws one Select Character item
  and looks its chr id up among the first 127 entries for the portrait. For
  a character further on, its entry and entry 126 trade places for the call
  and back. The draw reads that one entry by chr id and keeps nothing.
- **The Gallery** draws the first n entries, n the number whose kind is not
  0 (`sub_00098F40`), so a hidden slot among them would take a shown one's
  cell: with characters in spare slots, the Consultant (126) sits between
  the disc's characters and theirs. Once a mod's characters are in,
  `ts2_chars_compact` moves the hidden entries behind the shown ones, in
  order. Every list walks the table in order and skips hidden entries, so
  no list changes order; nothing outside a screen keeps a roster index (the
  profile, bot sets and players keep chr ids).
- The Gallery's grid gets as many columns as nine rows need
  (`sub_00099960`, `sub_00098F40`; unchanged).

### Checked (scripted, macOS, 15 Oct 2026)

Without a mod, the patched build against the unpatched one on the same
input script: the Select Character list (first entry and its wrapped end,
Capt Forest), Arcade Custom's menus, the Gallery (14 x 9, its cursor's wrap
to the last cell), Player Options' "Complete 0.0%" and medal totals, and the
saved profile (the same files; only the profile's random default name and
its signature differ, as they do between any two runs). Story still reaches
Siberia (`l_35_ST.pak`), with no unresolved indirect calls in any run.

## Adding a character (mods)

What split2-recomp does, PAL only (`src/recomp_manual.c`, "extra playable
characters"; addresses in `config/pal/overrides.inc`). A mod folder for
`RECOMP_MODS` holds:

| File | What |
|---|---|
| `data/chr.pak` | `ob/chrs/chr{id+1:02d}.xbr` replaced, and any new `textures/NNNN.xbt` it uses |
| `data/chrinc.pak` | `ob/chrincs/chr{id+1:02d}.xbr`, the select screen's preview, textures inside |
| `data/arcade/l_101.pak` | the portrait, `textures/misc/chrimage_<name>.xbt` (64x64 DXT3, as `chrimage_ped3.xbt`); `ts2kitbash` also puts it in `l_102.pak` and `gun.pak` |
| `ts2/characters.ini` | the declaration, below |

`tools/ts2kitbash.py` makes all of it from a recipe
(`tools/examples/characters.json`: body, head, colours, and the roster slot,
description, set and unlock), `ts2/characters.ini` included;
`tools/ts2mod.py build` makes the paks from the `paks/<pak>/<path>` source
tree and copies `ts2/` across:

```bash
python3 -I tools/ts2kitbash.py tools/examples/characters.json game/data <work> <source>
python3 -I tools/ts2mod.py build <source> game/data <mod>
RECOMP_MODS=<mod> ./split2_recomp
```

Only the first `RECOMP_MODS` folder with a `ts2/characters.ini` is read
(xboxrecomp `xbox_mods_find`).

```ini
[Agent Static]
slot = next                ; the next free spare slot (127-158); 0-126 replaces that character
chr = 70                   ; chr id: model, definition, files chr71
name = Agent Static        ; every language; name.fr / .de / .it / .es override
bio = ...                  ; the Gallery's description (text 625 + chr); bio.fr ...
portrait = textures/misc/chrimage_chr71.xbt
background = neo           ; chrblank_<set> while locked (atom ... west)
unlock = start             ; start (kind 1), never (0), keep (the slot's rule)
stats = 68                 ; optional: copy definition +0x2C-+0x3C from this chr id
sounds = 68                ; optional: copy the sound set (+0x04)
```

Up to 48 sections. Before the game's `main` (`sub_000D99F0`) runs, each one
writes its roster entry (chr id, kind, background), points its name's text
id and its description's id at new strings in every language, points the
slot's texture-list entry at the new portrait's path (a spare slot's entry
also gets slot 0's portrait's load flags, so the front end loads it), and
copies the stats and sound set if asked. `slot = next` takes the first
spare slot no other section names; numbered slots are kept as given. Then
the hidden entries are moved behind the shown ones (above). A value may not
contain `;` (the reader takes the rest of the line for a comment).

Which chr id: one that no arcade level pak carries, or that level's copy
wins over `chr.pak`'s. chr ids 70-72 (`chr71`-`chr73`, NeoTokyo
pedestrians) are only in `chr.pak` and `data/story/l_38_ST.pak` (NeoTokyo
story, where the pedestrians walk), and `ob/chrincs/chr71`-`73.xbr` only in
`chrinc.pak` (`tools/ts2mod.py where`). Replacing them changes the
NeoTokyo story's pedestrians only if `l_38_ST.pak` is replaced too. The
same chr id in two entries shows the first one's portrait and unlock rule
in both, so use one nobody plays.

Checked in scripted runs (macOS, 15 Oct 2026), with the example recipe's
three characters added in slots 127-129 and every character on the disc
kept: all three at the end of the Select Character list after Capt Forest,
each with its portrait, name, stats and `chrinc` preview; each selected and
played in an Arcade Custom deathmatch, its model on the death camera; the
Gallery at 15 columns with the three in the last row, cursor and name on
them; and Story to Siberia with the mod loaded. Earlier (slot 126, the
same name mechanism): a section's name in "Killed by ..." and "First kill:
...". Not checked: the Available Bots list with added characters (its
search is one of the four sentinel loops), four players at once.
