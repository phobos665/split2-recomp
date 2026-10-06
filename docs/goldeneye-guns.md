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

Sound numbers, as the game's weapon stats give them: PP7 and sniper 46 (both
silenced), KF7 109, D5K 117, shotgun 121, Magnum 111, rocket launch 1;
reload 50, empty click 89. On the PAL cartridge the game's number n is bank
entry n - 1: the first extraction took them literally, and the pistol and
sniper rifle played a punch (entry 46) until the silenced shot was picked
out by ear as entry 45 (6 Oct 2026).

## Step 2a: the sounds (done, 6 Oct 2026)

```
py -3 -m tools.ge_guns "n64/007 - GoldenEye (Europe).n64" --ts2-sounds game --mods build/Release/mods
```

writes `mods/data/xbsound.pak` with each gun's GoldenEye shot in place of the
TimeSplitters 2 sample its weapon fires. One file covers every level: the
level archives carry their own copies of the sounds under the same names
(`sfx/gun_silenced22.xbs` is in 13 of them), and the game searches
`xbsound.pak` first since `src/overrides/archives.c`.

**Checked in the game**, with the toolkit's `RECOMP_AUDIO_RECORD`, which
writes everything the game plays to WAV: in the scripted Siberia run the
player's three sniper shots and the guards' 14 silenced-pistol shots were
the GoldenEye sounds, sample for sample, and none of them the originals. The
other five go the same way but are not fired in that level. **Not yet
listened to.**

| TS2 weapon | its fire sound (definition `+0x98`) | sample replaced | GoldenEye sound |
|---|---|---|---|
| Silenced Pistol (and Silenced Luger) | `SFX_GUN_SILENCED_PISTOL` | `sfx/gun_silenced22.xbs` | 46, PP7 |
| Soviet S47 (and the Tactical 12-Gauge) | `SFX_GUN18` | `sfx/gun_m16_04_withbullet22.xbs` | 109, KF7 |
| SBP90 | `SFX_GUN_UZI` | `sfx/gun_uzi_withbullet22_01d.xbs` | 117, D5K |
| Shotgun | `SFX_DRGUN3` | `sfx/gun_dr08c_22.xbs` | 121 + 90, shotgun and shell |
| Sniper Rifle | `SFX_GUNSNIPERRIFLE2` | `sfx/gun_sniperrifle_nu44_03b.xbs` (44.1 kHz) | 46, silenced |
| Garrett Revolver | `SFX_GUNCOLT` | `sfx/gun_walther_colt22_02.xbs` | 111, Magnum |
| Rocket Launcher (and Homing Launcher) | `SFX_GUNROCKET03` | `sfx/gun_rocketlauncher22.xbs` | 1, rocket launch |

How it was found: `sound/sounddata` in `sounds.pak` lists the 1,824 sample
files, then 2,004 named sound definitions (`SFX_...`), each starting with
its sample's number and holding the rate it plays at (`0x0759` for 22,050 Hz,
`0x0EAA` for 44,100, `0x0556` for 16,000). A weapon definition names its
primary fire sound at `+0x98` and the secondary's at `+0x148` (numbers into
that definition list). Because the definition fixes the rate, a replacement
is written at the rate of the file it replaces, not its own.

The `.xbs` format and codec are `tools/xbs.py` (`decode` / `encode`):
re-encoding the disc's own sounds gives back their header byte for byte and
the sound at 115-125 dB SNR. The reload, empty-click and shell sounds are
not replaced yet; their TS2 samples are `SFX_RELOAD` (`reload22_01`, shared
with weapon changes), `SFX_GUN_DRYFIRE01` and the shotgun's
`SFX_SHOTGUN_COCK`.

## Step 2b: the models (not started)

* A `.xbr` writer, for static models only: a gun has no
  skeleton, just parts. Each TS2 gun has three models (`_cl`, `_ph`,
  `_promo`; probably first-person, pickup, and the menu's picture). The
  GoldenEye models are small (156-388 triangles first-person, 46-65 pickup),
  which suits that.
* The first-person position (how the gun sits on screen) will need tuning per
  gun; GoldenEye's weapon stats hold its own position, which is a start.
