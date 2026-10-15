# `.xbt` textures (TimeSplitters 2, Xbox)

`tools/ts2xbt.py` reads and writes them. This page is what it relies on.

Each claim is marked:

- **measured**: counted over every `.xbt` on the PAL disc (19,180 files in the
  68 `.pak` archives under `game/data`, 981 of them in `chr.pak`), or seen by
  decoding the texels and looking at the picture.
- **code**: read from the game's loader in the lifted PAL executable,
  `sub_001B7E60` (PAL address `0x001B7E60`). It takes a pointer to the file in
  memory, fills a 0x34-byte texture record and calls the XDK's
  `XGSetTextureHeader` (`0x001EC886`) and `D3DResource_Register` (`0x001DC270`).
- **inferred**: a reading that fits the data but that neither of the above proves.

USA has not been checked: its paks were not surveyed and its loader was not read.

## Layout

A 128-byte header, then the texel data from byte 128 (0x80) to the end of the
file, mip level 0 first. All fields are little-endian 32-bit.

| Offset | Field | What it is | Evidence |
|---|---|---|---|
| 0x00 | width | Texture width in texels, a power of two (8 to 512 on the disc). Passed to `XGSetTextureHeader` as Width, and as Pitch | code; powers of two measured |
| 0x04 | height | Texture height, a power of two | code; measured |
| 0x08 | display width | Copied to the texture record (16 bits at +0x26); the game's use of it was not traced. Equal to the width in all but 96 files | code (copy); measured |
| 0x0C | display height | Same, record +0x2A | code (copy); measured |
| 0x10 | last mip level | The number of mip levels minus one: the loader passes `this + 1` as Levels | code; sizes measured |
| 0x14 | format | 0-3, below. The loader turns it into a D3D format | code |
| 0x18 | detail texture | -1 for none, else 0-19. The loader keeps its low byte (record +0x23) | code (copy); values measured; meaning inferred |
| 0x1C | detail scale u | float. Zero when 0x18 is -1. Loaded as a float into record +0x2C | code (copy); values measured; meaning inferred |
| 0x20 | detail scale v | float, equal to 0x1C in all but one texture (`2562`, in two paks). Record +0x30 | code (copy); values measured; meaning inferred |
| 0x24-0x7F | | Zero in every file | measured |

The bytes from 0x80 go to `D3DResource_Register` as the texture's data, so
the game uses the disc's bytes as they are (code). The toolkit's own
measurement agrees: a captured texture's level 0 is the file's bytes from +128
(`xboxrecomp/docs/technical/modding-models-textures.md`).

There is no magic number and no size field. The loader refuses only a negative
width or height (code).

### The mip chain

Levels follow each other with no padding. Each level is half the size of the
one before, down to 1 texel on a side; a DXT level is never smaller than one
4x4 block (8 or 16 bytes). In every one of the 19,180 files the data after the
header is exactly the chain that the size, format and level count describe:
no file is short and none has bytes left over (measured).

Most files have the whole chain, down to 1x1 (17,983 files). The rest stop
early: 89 have one level, 1,099 have two and 9 have three (measured). An
imported texture keeps the original's choice: a whole chain stays whole at a
new size, a short one keeps its length.

### Display size (0x08, 0x0C)

Different from the texture size in 96 files, always smaller: `xbnullchar`
(32x32, 17x32), `booklight` (128x256, 128x192), `ts2loading` (512x512,
512x384), `mm_edge` and eight `mm_cursor*` (32x32, 32x24) (measured). In the
ones looked at (`ts2loading`, `mm_cursor55`) the picture fills the whole
texture, so the field is not a crop of padding: `ts2loading` is a 4:3 picture
squeezed into a square, which suggests these are the size the picture is meant
to be shown at (inferred). When `import` changes a texture's size it scales
these by the same factor.

### Detail texture (0x18-0x20)

The PAL `default.xbe` lists 21 detail textures, at file offset 0x211892 on:
`xbnullchar`, `ashphalt_det_xb_dtl`, `plaster_det_xb_dtl`,
`stone_floor_detail_xb_dtl`, `chic_metal_xb_dtl`, `scrap_del_xb_dtl`,
`yrdmet_xb_dtl`, `rope_det_xb_dtl`, `mex_yucdet_xb_dtl`, `mex_wood_de_xb_dtl`,
`mex_mulch_dtl`, `sandtest1_xb_dtl`, `mex_rock_xb_dtl`, `wfall1_xb_dtl`,
`bedrock_detail_xb_dtl`, `ground_detail_xb_dtl`, `moss1_xb_dtl`,
`tg_cbrd_det_xb_dtl`, `grass2_det_xb_dtl`, `tg_rock1_xb_dtl`, `brickdl`. Every
level pak carries the `.xbt` of each.

Reading 0x18 as an index into that list fits what is on the disc: 382 files
set it, all to 0-19; 0x1C and 0x20 are zero exactly when it is -1, and
otherwise hold tiling-like values (4.0 in most, also 1, 2, 3, 6, 16, and once
3.14 and 5.98). Indices 9, 10 and 13 occur only in `l_42_AR.pak`, and 8 and
12 (also `mex_*`) mostly there. This is an inference: the code that reads record +0x23
was not traced. `info` prints the name it implies.

## Formats

| 0x14 | Format | D3D format the loader asks for | Bytes | Files |
|---|---|---|---|---|
| 0 | DXT1 | 0x0C (`D3DFMT_DXT1`) | 8 per 4x4 block | 11,310 |
| 1 | DXT3 | 0x0E (`D3DFMT_DXT2`/`DXT3`) | 16 per 4x4 block | 7,138 |
| 2 | A8R8G8B8, swizzled | 0x06 (`D3DFMT_A8R8G8B8`) | 4 per texel | 732 |
| 3 | R5G6B5, swizzled | 0x05 (`D3DFMT_R5G6B5`) | 2 per texel | 0 |

The mapping is code; the counts are measured.

- **0, DXT1.** Standard DXT1 blocks in row order. The Xbox does not swizzle
  compressed textures. Both colour modes occur (measured: of the level-0
  blocks, 95% have colour0 > colour1, four-colour; the rest are three-colour
  or solid), and three-colour blocks give one-bit alpha.
- **1, DXT3.** Standard DXT3 (4-bit explicit alpha, then a DXT1 colour block
  that is always read in four-colour mode).
- **2, A8R8G8B8.** Each texel is 4 bytes, B, G, R, A in memory, and each mip
  level is swizzled on its own. Decoding `ts2glow` (512x256), `1870`
  (64x32) and others with the swizzle below gives clean pictures (measured).
- **3, R5G6B5.** The loader knows it; no file on the PAL disc uses it. The
  tool reads and writes it the same way as format 2, 2 bytes per texel; that
  path has been tested on made-up data only.

A value above 3 leaves the loader's D3D format unset. None is on the disc.

### Swizzle

The Xbox swizzle for a power-of-two `w x h` level: the texel at (x, y) is
stored at an index whose bits interleave those of x and y, starting with x in
bit 0. Once the shorter side has run out of bits, the longer side's remaining
bits fill the top. This is the toolkit's `xbox_swizzle_masks` in
`xboxrecomp/src/d3d/d3d8_swizzle.h` (xemu's algorithm).

### Against the community references

The Noesis plugin (OpenRadical/noesis `plugins/python/fmt_xbox.py`) reads the
format at 0x14 and the data at 0x80 as here, but:

- it reads the size from 0x08 and 0x0C, the display size. That is the same as
  the texture size in all but 96 files;
- it calls format 2 "DXT1 packed normal map", but decodes it as 32-bit BGRA in
  a swizzle, which is right. On this disc format 2 holds ordinary pictures
  (the title logo, menu art), not normal maps;
- it reads format 3 as raw RGB24. The loader maps 3 to R5G6B5 (2 bytes a
  texel), and no file uses it;
- it reads level 0 only.

The TS-ReSplit wiki's texture page covers the PS2 format only.

### `explosionanim8.xbt`

The toolkit doc found this file's bytes at +1728 instead of +128 when matching
a captured texture against the disc. The file is an ordinary 64x64 DXT1
texture with its whole chain (measured: same header layout, size and round
trip as the others). Level 0 from about byte 1600 is one solid-colour block
(`1ff8 0000 5555 5555`) repeated, a nearly empty animation frame. A captured
texture made of that same block, or starting with it, matches there, so the
+1728 match was a coincidence of repeated bytes, not a second layout.

## What `ts2xbt.py verify` checked

Every `.xbt` exported to DDS and imported back gives the identical file, for
all 19,180 on the PAL disc (11,310 DXT1, 7,138 DXT3, 732 A8R8G8B8), the 981 in
`chr.pak` among them. That proves the header rebuild, the chain sizes and that
swizzle and unswizzle undo each other. It does not prove the swizzle is the
Xbox's: the decoded pictures show that.
