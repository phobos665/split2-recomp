# GoldenEye guns in TimeSplitters 2

A mod that gives TimeSplitters 2 the look and sound of seven GoldenEye 007
guns -- low-poly as they were. Everything it uses comes from **your own
GoldenEye cartridge** and **your own TimeSplitters 2 disc**: the tools here
hold no data from either game, and nothing they write may be committed or
shared. They write under `extracted/` and `mods/`, both ignored by git.

| GoldenEye | first-person / pickup file | replaces in TS2 | TS2 model (likely) |
|---|---|---|---|
| PP7 (silenced) | `GwppksilZ` / `PchrwppksilZ` | Silenced Pistol | `silencedpistol` |
| KF7 Soviet | `Gak47Z` / `PchrkalashZ` | Soviet S47 | `ak47` |
| D5K Deutsche | `Gmp5kZ` / `Pchrmp5kZ` | SBP90 | `uzi` |
| Shotgun | `GshotgunZ` / `PchrshotgunZ` | Shotgun | `doublebarrelshotgun` |
| Sniper Rifle | `GsniperrifleZ` / `PchrsniperrifleZ` | Sniper Rifle | `sniperrifle` |
| Cougar Magnum | `GrugerZ` / `PchrrugerZ` | Garrett Revolver | `magnum` |
| Rocket Launcher | `GrocketlaunchZ` / `PchrrocketlaunchZ` | Rocket Launcher | `rocketlauncher` |

The TS2 column is the `ob/guns/<name>_*.xbr` set in `gun.pak` that looks
like the weapon; which file each TS2 weapon draws is not confirmed yet.

## Step 1: out of the cartridge (done, 6 Oct 2026)

```
py -3 -m tools.ge_guns "n64/007 - GoldenEye (Europe).n64" --list
py -3 -m tools.ge_guns "n64/007 - GoldenEye (Europe).n64" --preview
```

Any byte order (`.z64`, `.v64`, `.n64`). For each gun, `extracted/goldeneye/<gun>/`
gets `first_person.obj` and `pickup.obj` with their materials and textures
(PNG), `fire.wav`, previews, and `gun.json` (magazine, sound numbers, the
model's parts). `sounds/` gets the shared reload, empty click, shell case and
rocket launch. The OBJs open in Blender with vertex colours. Seven guns take
about two seconds.

The pistols carry Bond's hand in their own model; it is left out unless
`--hands`. The muzzle flash squares are left out unless `--flash`.

Checked against the PAL cartridge: all 2,698 textures decode, the file
table matches the GoldenEye decompilation's PAL file list entry for entry,
the weapon stats give each gun's real magazine (PP7 7, KF7 30, D5K 30,
shotgun 5, sniper 8, Magnum 6, rocket 1), and the previews look like the
guns. The sounds decode to clean audio at the rate the game plays them; they
have not been listened to yet.

### What the tools read, and how

`tools/ge_rom.py` finds everything from the ROM's own tables, so nothing is
an address:

* Files are Rare's "1172" streams (`11 72`, then raw deflate). The game's data
  segment is the first large one; it holds the **file table** (12-byte
  entries: index, name pointer, ROM offset, ending at `ob/ob_end.seg`) and the
  **texture size table** (8-byte entries, low 24 bits a size, ending at
  `0xFFFF`; the game adds them up into offsets at start-up).
* Textures follow `ob/ob_end.seg` in number order. The decoder is a port of
  the game's own (the decompilation's `image.c`): zlib-paletted, and nine
  non-zlib methods -- Huffman, RLE, lookup tables, and "blur" prediction.

`tools/ge_model.py` walks a model's node tree and runs its display lists
(Rare's F3D variant: `04` vertices, `B1` four triangles, `BF` one, `C0`
texture), giving triangles with UVs and vertex colours. Two things the game
does that an OBJ cannot: mirrored texture repeat (baked into the PNG) and
chrome (the Magnum: the UVs come from the normals, a sphere map; baked to
UVs here).

`tools/ge_sound.py` reads the effects bank (standard libaudio, 261 VADPCM
sounds) and decodes it. The rate a sound is written at is the one the game
plays it at: 22050 Hz times `2 ** ((keyBase*100 + detune - 6000) / 1200)`.
Some sounds start another (the shotgun's shot starts the shell case); the
WAV mixes the chain. A gun's firing sound is in its weapon stats, found
through the gun's own record in the data segment.

Sound numbers: PP7 and sniper 46 (both silenced), KF7 109, D5K 117, shotgun
121 (then 90, the shell), Magnum 111, rocket launch 1; reload 50, empty
click 89.

## Step 2: into TimeSplitters 2 (not started)

* **Sounds first.** TS2's sounds are `.xbs` files in `sounds.pak`: a WAV header
  with Xbox ADPCM audio. They need an encoder (the toolkit decodes this ADPCM
  already) and the list of which `.xbs` each weapon fires. Replacing them uses
  the mods folder the same way the `xbt.pak` texture override does.
* **Then the models.** A `.xbr` writer, for static models only: a gun has no
  skeleton, just parts. Each TS2 gun has three models (`_cl`, `_ph`,
  `_promo`; probably first-person, pickup, and the menu's picture). The
  GoldenEye models are small (156-388 triangles first-person, 46-65 pickup),
  which suits that.
* The first-person position (how the gun sits on screen) will need tuning per
  gun; GoldenEye's weapon stats hold its own position, which is a start.
