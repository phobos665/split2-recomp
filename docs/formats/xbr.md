# `.xbr` character models (TimeSplitters 2, Xbox)

The layout of a character model, `ob/chrs/*.xbr` in `chr.pak` (and the copies in
the level paks) and `ob/chrincs/*.xbr` in `chrinc.pak`, written so that an
importer and an exporter can be built from it. `tools/ts2xbr.py` reads every
such file, writes it back byte for byte, exports OBJ and prints the bind-pose
skeleton.

Each claim is marked:

- **measured**: true of every character file on the PAL disc: the 314 in
  `chr.pak`, the 155 in `chrinc.pak`, and the 1,438 `ob/chrs/*.xbr` entries in
  all 68 paks, which are the `chr.pak` files plus four bosses
  (`transfusionsplitter`, `drillhead`, `nailhead`, `sawarm`). Checked with
  the tool or a one-off script.
- **code**: read from the disassembly of the PAL executable
  (`.pipeline/disasm/asm/text.asm`), at the `sub_XXXXXXXX` given (PAL
  addresses).
- **run**: seen in a run of the recompiled game (vertex shaders dumped with
  `RECOMP_D3D8_VS_DUMP=1`, scripted run to Siberia).
- **inferred**: fits the data, but no code was read and nothing was run to
  prove it.

USA was not checked. Level and prop models (`bg/levelNN/*.xbr`, guns, pickups)
use the same piece and section structures but other fields too; they are not
covered (see [Not explained](#not-explained)).

## Summary

- A model is a tree of **pieces** (at most 127, links are signed bytes). Each
  piece has up to three **sections** (sections 0 and 1 are used), each a list of
  **records**: a run of vertices drawn with one material, as triangle strips,
  plus an optional triangle list over the same vertices.
- Vertices are stored **in model space, in the bind pose**. Positions and
  normals are converted into bone space by the game when the model is first
  instanced (code `sub_0012AC40`). The OBJ export is therefore already posed
  correctly.
- **No blend weights.** Every vertex follows exactly one matrix. A rigid piece
  (type 0) follows its own bone. A skinned piece (types 1-3) stores, per
  vertex, the **palette bone index** of the bone it follows, as an integer in
  the normal's fourth component. That bone is one of three: the parent piece's,
  the child piece's or the piece's own. The game turns it into a choice of
  c64, c68 or c72 at load. Smooth-looking joints come from geometry split
  between neighbouring bones, plus synthesised mid-joint bones (type 2).
- **Skeleton**: the file has no joint positions. The hierarchy is the piece
  tree. The animation bone of each rigid piece is its rank in a depth-first
  walk of that tree. The joint positions come from a bind-pose animation file
  shared by all humans (`fe_anim.pak: anim/data/ts2/human_19_bindpose.raw`),
  scaled per model.
- **All 238 human models (155 characters and 83 `lod2` models) have the same
  19-bone skeleton** (measured). The exceptions are `chr17` (Barrel Robot, 13
  bones), the four bosses in the story paks (`transfusionsplitter` 19 bones;
  `drillhead` 6, `nailhead` 5, `sawarm` 6), and 75 one-bone attachments: hats,
  `monkeyhelmet`, `chrNN_head/_larm/_rarm`. See [Skeleton](#skeleton-and-animation).
- Textures are named by number: material id `N` is `textures/NNNN.xbt`,
  from whichever pak is mounted (code `sub_001B8290`). The `chrinc.pak` copies
  carry their textures inside the file instead.
- `tools/ts2xbr.py check` parses all 469 files of `chr.pak` and `chrinc.pak`,
  with every byte either read or rebuilt as zero padding, and **re-serialises
  every one of them byte-identically** from the parsed structure. The
  structure holds no offsets, padding, counts or derived vertices, so the
  layout rules below are complete for these files. The same holds for all
  1,438 `ob/chrs` entries in all paks, and for 3,279 of the disc's 4,368 files
  with leading `0xC` (props and guns that parse).

## Conventions

Little-endian. Every pointer in the file is an offset from the start of the
file. Zero means none. When the file is loaded, every non-zero offset is
replaced by its address (code `sub_00129510`, which also lists every pointer
field, so it gives the shape of the whole structure). The file is then used
in place: materials, pieces and vertices are rewritten where they lie, and the
D3D vertex buffers are built from it (code `sub_0012AC40`, `sub_001C7940`).

The character file is loaded from the object list at `0x002D8E08`: 0x24-byte
records, path at +0xC, type at +0 (8 for characters), loaded pointer at +4
(code `sub_00152B50` → `sub_0012CC30`; `docs/formats/roster.md` covers the
roster side).

## File layout

| Offset | Size | What | Evidence |
|---|---|---|---|
| 0x00 | 4 | Offset of the material list, always 0xC | code `sub_0012CC30`; measured |
| 0x04 | 4 | Offset of the model descriptor | code `sub_0012CC30` |
| 0x08 | 4 | 0 | measured |
| 0x0C | 16 × (n+1) | Materials, then a terminator record `FFFFFFFF 0 0 0` | code `sub_0012CBD0`; measured |
| ... | | Data of piece 0, piece 1, ... (see [Order and alignment](#order-and-alignment)) | measured |
| M − 0x9C × count | 0x9C × count | Piece table | code `sub_00129510` |
| M | 0x34 | Model descriptor; M is the offset at 0x04 | code |
| ... | | `chrinc.pak` only: embedded textures, each 128-byte aligned | code `sub_0001B790`; measured |

The piece table ends exactly where the model descriptor starts (code: the
table is found as `M - count * 0x9C`). In `chr.pak` files the descriptor ends
the file.

### Materials (16 bytes)

| Offset | What | Evidence |
|---|---|---|
| +0x0 | Texture id: `textures/%04d.xbt`. In a `chrinc.pak` file, the file offset of an embedded texture instead. `0x40000000` means no texture (skipped by the loader) | code `sub_0012CBD0`, `sub_001B8290` (format string `host0:textures/%04d.xbt` at `0x0029F3A4`); measured: the 981 ids used by `chr.pak` models are exactly its 981 textures |
| +0x4, +0x8 | 0. The loader overwrites the record with its texture handle | measured; code `sub_001B8290` |
| +0xC | Flags. Bit 28 (`0x10000000`) means the texture is embedded at +0x0 (set in every `chrinc` material, never in `chr.pak`). The low byte is copied into a per-texture byte table | code `sub_00129870`, `sub_0001B790`, `sub_001B8290`; measured |

A record's material index (below) selects one of these, or −1 for none (47
records).

Texture format: `docs/formats/xbt.md`.

### Model descriptor (0x34 bytes)

| Offset | What | Evidence |
|---|---|---|
| +0x00 | Piece count | code `sub_00129510` |
| +0x04 | Palette bone count: highest piece bone index + 1 (19 to 31 for humans, as the type-2 bones add to the 19 animation bones) | measured; code `sub_0012D130` |
| +0x08 | 1 in every file. When non-zero the renderer makes one extra call per draw (`sub_001C9032`, lighting setup) | measured; code `sub_0012A780` |
| +0x0C | Runtime: pointer to the material list | code `sub_0012CC30` |
| +0x10 to +0x24 | Runtime: per-piece vertex buffer tables built by `sub_001C7940`. 0 in the file | code; measured |
| +0x28 | float, **skeleton scale**: every bind-pose translation is multiplied by it (0 is treated as 1.0). 0.6 to 1.4; 18.0 for `chr59` | code `sub_0012CDC0`; measured |
| +0x2C, +0x30 | 0 | measured |

### Piece (0x9C bytes)

| Offset | Type | What | Evidence |
|---|---|---|---|
| +0x00 | u8 | **Type**: 0 rigid, 1 joint (2 matrices), 2 mid-joint (3 matrices, owns a synthesised bone), 3 bridge (3 matrices, not a tree parent) | code `sub_001BC2A0`, `sub_0012AC40`, `sub_0012ABA0` |
| +0x01 | s8 | **Bone**: palette matrix index. For type 0 and 2 its own bone; −1 for type 1; −1 or an existing bone for type 3 | code |
| +0x02 | s8 | Parent piece (−1 for the root, piece 0). For types 1-3 also the piece whose bone is the first matrix (c64) | code `sub_001BC2A0`, `sub_0012AC40` |
| +0x03 | s8 | First child piece. For types 1-3 also the piece whose bone is the second matrix (c68). A type-3 piece's +0x03 is **not** walked as a child | code `sub_0012A650`, `sub_0012ABA0` |
| +0x04 | s8 | Next sibling | code `sub_0012A650` |
| +0x05 | s8 | Previous sibling (not read by any code found) | measured: consistent with +0x04 |
| +0x06, +0x07 | | 0 | measured |
| +0x08 to +0x10 | 5 × s16 | Counts of the pointer arrays at +0x6C to +0x7C. 0 in every character | code `sub_00129510`; measured |
| +0x12 | u16 | Visibility mask, ANDed with the instance's mask (0 means always drawn). 0 in every character | code `sub_0012A650`; measured |
| +0x14, +0x18, +0x1C | 3 × ptr | Record table of section 0, 1 and 2 (0 = section absent) | code |
| +0x20 | ptr | Relocated by the loader; 0 in every character | code; measured |
| +0x24 + 0x14 × s | 5 × ptr | Section s: draw headers, positions, UVs, colours, normals | code `sub_001BC2A0`, `sub_001C7940` |
| +0x60 | u16 | Number of vertices over all sections (sum of record counts, padding excluded). Statistics only | code `sub_001BC2A0`; measured |
| +0x62 | u16 | Number of triangles in the face lists over all sections. Statistics only | code; measured |
| +0x64 to +0x67 | 4 × u8 | Render state bytes; 0 in the file, set to FF FF 00 at instancing (`sub_00129C70`) | code; measured |
| +0x68 to +0x7C | 6 × ptr | Pointer arrays (counts at +0x08); 0 in every character | code `sub_00129510`; measured |
| +0x80 + 4 × s | ptr | Section s: collision groups (hats only, see [Hat collision](#hat-collision)) | code `sub_00129510`; measured |
| +0x8C | float | Type 2: blend factor of its synthesised bone (0.5 in most, 0.2 to 0.7). 1.0 for every other type | code `sub_000119C0`; measured |
| +0x90 + 4 × s | ptr | Section s: face table | code `sub_00129510`, `sub_001BC2A0` |

Pieces with no geometry (all section pointers 0) are common: they carry a
bone and a place in the tree, nothing else.

### Sections

Section 0 is the main pass. Section 1 is a second pass (58 pieces in
`chr.pak`), whose textures are mostly DXT3, so probably alpha-blended. The
drawing code takes the section as an argument from its caller (`sub_0012A780`)
(inferred). No character has a section 2. Only sections 0 and 1 are converted
to bone space at load (code `sub_0012CD20`), so a writer should not use
section 2.

A section is:

**Record table**: 10-byte records, then a terminator `0 0 0 0 -1`.

| Offset | Type | What | Evidence |
|---|---|---|---|
| +0 | s16 | Material index, −1 for none | code `sub_001BC2A0` |
| +2 | s16 | The record's own index (0, 1, ...) | measured |
| +4 | s16 | First vertex, in the section's arrays | code |
| +6 | s16 | Vertex count | code |
| +8 | s16 | Kind; a negative value ends the table. 2 in rigid pieces, 3 in skinned pieces, 0 in records whose section has vertex colours (25 records). Selects lighting flags | code `sub_001BC2A0` (1 and ≥2 treated differently); values measured |

Records follow each other in the vertex arrays, each **starting on a multiple
of 4**. The gap is filled with **padding vertices**: copies of the record's
last vertex, with the position's flag word set to `0x3F808000` (measured: all
8,858 padding vertices). There is no padding after the last record.

**Draw headers**: 16 bytes per record, always `0x8000 | count, 0x302E4000,
0x00000412, 0` (measured). No code was found that reads them.

**Vertex streams**: one entry per vertex, padding vertices included. The
section has `last.start + last.count` vertices.

| Stream | Stride | Content | Evidence |
|---|---|---|---|
| Position | 16 | x, y, z float (model space, bind pose; +Y up, the character faces +Z), then a flag word: `0x3F800000` (1.0f) with bit 15 = no triangle ends here (strip restart) and bit 0 = winding flip | code `sub_001BC2A0` (bit 15), `sub_001C9F44` (word dropped); measured |
| UV | 12 | u, v, w float. w is 1.0 in every character vertex; the Noesis reader multiplies u and v by it | measured; code `sub_001C9F44` copies all three |
| Colour | 4 | D3DCOLOR, optional (25 sections) | code `sub_001C9F44` |
| Normal | 16 | nx, ny, nz float. Fourth word: **rigid pieces** 1.0f; **skinned pieces** the palette bone index the vertex follows, as an integer (0 to 30) | measured; code `sub_0012AC40` |

Every character section has normals (measured).

### Triangles

Each record is drawn in one of two ways, so a writer must provide both:

1. **Strips** (code `sub_001BC2A0`). Within a record, vertex `b ≥ 2`
   completes triangle `(b−2, b−1, b)` unless its bit 15 is set. Each strip
   starts with two flagged vertices, so a strip starts at a flagged vertex
   whose predecessor is not flagged. Winding (measured over 342,405
   triangles, no exceptions): with `k` the vertex's position in its strip
   (counting the two flagged ones) and `f` its flag bit 0, the triangle is
   `(b−2, b−1, b)` when `k + f` is even and `(b−1, b−2, b)` when odd.
   Every record starts with exactly two flagged vertices, and flagged
   vertices always come in pairs (measured). Degenerate triangles (repeated
   positions) are allowed.
2. **Face lists**. The face table has 8 bytes per record: offset and count
   of `u16` indices (a triangle list), or `0, 0`. Indices are relative to the
   section's first vertex. A list is attached to the **last record of each run
   of consecutive records with the same material** and covers the whole run;
   the other records have `0, 0` (measured: 11,727 lists sit there, 4 sit on
   another record of their run). These index blocks reach the D3D draw unchanged (toolkit
   capture, `xboxrecomp/docs/technical/modding-models-textures.md`).

Compared by position, the strip form and the face lists give the same
triangles in all 11,714 material runs (measured). Compared by position and
UV, 488 runs differ by a few triangles: the list then uses a different copy
of a vertex at the same position. Generating the lists from the strips, with
the winding rule above, is safe.

### Order and alignment

The writer in `tools/ts2xbr.py` (`build`) follows these rules and reproduces
every file. After the materials, for each piece in table order that has a
section:

1. The record table of each present section, in section order, each padded to 4 bytes.
2. For each section, in order: draw headers, colours (if any), positions, UVs, normals.
3. For each section with collision: [hat collision](#hat-collision) data.
4. The face table of each section.
5. Pad to **32 bytes**. Then the index lists, section by section, record by
   record, packed with no gaps.
6. Pad to 4.

Then the piece table and the model descriptor. Nothing else is in the file:
every byte not described here is zero padding (measured).

## Skinning: how a piece is bound to its matrices

At draw time each piece sets up to three matrices of a palette of
model-view matrices (one per palette bone, built per instance) (code
`sub_001BC2A0`, via `sub_001B6EC0` c64, `sub_001B6ED0` c68,
`sub_001B6EE0` c72):

| Type | c64 | c68 | c72 |
|---|---|---|---|
| 0 rigid | own bone | | |
| 1, 2, 3 | bone of piece `+0x02` | bone of piece `+0x03` | own bone, if `+0x01 ≥ 0` |

When the model is first instanced, `sub_0012AC40` (via `sub_0012CD20`, for
sections 0 and 1) rewrites each vertex in place:

- rigid piece: position and normal are taken into the bone's space by the
  inverse of its bind matrix;
- skinned piece: the normal's fourth word, a palette bone index, becomes
  0 if it is the c64 piece's bone, 8 if it is the c68 piece's bone, 16
  otherwise. The position and normal go into that bone's space.

The vertex buffer builder (`sub_001C7940` → `sub_001C9F44`) then writes
`(w >> 1) − 32` as the vertex's first element (−32, −28, −24). The skinned
vertex shaders (hashes `0x04E42637` and `0x3F4DAA0F` in
`RECOMP_D3D8_VS_DUMP`) do `a0 = floor(v0.x)` and transform by
`c[a0 + 96 .. a0 + 99]`, which is c64, c68 or c72 (run). Each vertex therefore
follows one matrix in full. **The format has no weights.**

The mid-joint (type 2) bone is synthesised every frame from its neighbours'
matrices: rotation by quaternion slerp and translation by lerp, with
`+0x8C` as the factor (code `sub_000119C0` → `sub_000E7520`). At bind time
the factor is forced to 1.0, which makes its bind matrix the child's (code
`sub_0012CDC0` calls `sub_000119C0` with flag 1). Which operand is which in
`sub_000E7520` was not worked out.

For an exporter, each skinned vertex must name one of the three bones above
(measured: every skinned vertex in every file does). A weight-painted Blender
mesh has to be split, or each vertex snapped to its strongest bone.

## Skeleton and animation

The `.xbr` file holds the hierarchy but no joint positions.

- **Animation bone order** (code `sub_0012ABA0`): walk the pieces depth first
  from piece 0, child before next sibling, without descending through
  type-3 pieces. The k-th **rigid** piece met is animation bone k. Its
  palette slot (`+0x01`) gets animation bone k's matrix. A type-2 piece met
  on the way gets the matrix of the animation bone that comes next. The
  parent of animation bone k is the nearest rigid ancestor (code
  `sub_00011890`, which builds world matrices).
- **Bind pose**: `sub_00012CD0` loads the bind poses into slots
  (`bindpose_slot_load`, `0x00012C30`): slot 0 `human_19_bindpose.raw` (19
  bones), slot 1 `barrelbindpose2_m0.raw` (13), slot 2 `railspiderbindpose.raw`
  (8), then `drillhed` (6), `nailhed` (5) and `sawarm` (6), all
  `fe_anim.pak: anim/data/ts2/` (code). `sub_0012CDC0` turns the bind pose
  into one matrix per animation bone, with translations scaled by the model's
  `+0x28` (code).
- **Bind pose file** (ANR1, measured on the six bind-pose files): bone count `n`
  at +0x3C, 32 bytes per bone from +0x60, a word, then from `0x64 + 32n` one
  record per bone: a parent-relative translation (3 floats), then a rotation
  quaternion x, y, z, w. The word at +0x30 says how the quaternion is stored:
  1 (`human_19_bindpose`, `railspiderbindpose`, both 19 bones, records from
  +0x2C4) as four `u16` in offset binary, `(v − 0x8000) / 0x7FFF`, 20 bytes a
  record; 0 (`barrelbindpose2_m0` 13 bones, `drillhed`, `nailhed`, `sawarm`)
  as four floats, 28 bytes a record. Every quaternion decodes to unit
  length. Composed parent × child (rotate the child's translation by the
  parent's world rotation), with chr01's scale of 1.04, this puts the pelvis
  at y = 1.20, the neck at 1.66, the head at 1.74, the shoulders at ±0.22, the
  knees at 0.62 and the ankles at 0.09. For chr01 every joint lies 0.03 to
  0.14 from the nearest vertex of its piece (measured). `ts2xbr.py joints` prints them. The rest of
  the ANR format (animation tracks) is not covered here.
- **Animations** (`anim.pak: anim/data/ts2/*.raw`): 172 of its 173 ANR1 files
  have 19 bones, matching the human bind pose (`hldmine.raw` has 100);
  measured from +0x3C. So any model whose depth-first rigid pieces
  match the 19-bone hierarchy plays every human animation.

**The 19-bone hierarchy** (parent of each animation bone): `-1 0 1 2 3 2 5 6
7 2 9 10 11 0 13 14 0 16 17`. Bones: 0 pelvis, 1 spine, 2 chest, 3 neck, 4 head,
5-8 one arm (clavicle, upper arm, forearm, hand; −X side), 9-12 the other
(+X), 13-15 one leg (thigh, shin, foot; −X), 16-18 the other. The names are
inferred from the joint positions.

**Do all playable-looking characters share one skeleton?** Yes. All 155
`chrNN.xbr` models with a body and all 83 `chrNNlod2.xbr` models have exactly
this hierarchy (measured, `ts2xbr.py skeleton`). Their **palette** bone
counts differ (19 to 31) because they have different numbers of type-2
mid-joint pieces. That changes nothing for animation. Exceptions:

| Files | Animation bones | |
|---|---|---|
| `chr17.xbr` (Barrel Robot) | 13: `-1 0 1 0 3 0 5 0 7 8 9 10 11` | matches `barrelbindpose2` (13) |
| `transfusionsplitter.xbr` (`story/l_38_ST.pak`) | 19 | human hierarchy |
| `drillhead`, `nailhead`, `sawarm` (`story/l_41_ST.pak`) | 6, 5, 6 | their own bind poses |
| 75 attachments: `*_hat`, `hat_*`, `monkeyhelmet`, `chrNN_head/_larm/_rarm` | 1 | a single rigid piece, bone 0 |

So a new human character can reuse the shared bind pose and every animation.
Its rigid pieces must come out in the same depth-first order, and its mesh
must be modelled in that bind pose at the model's scale.

## Hat collision

Only hat files have it (48 files, `*_hat`, `hat_*`, `monkeyhelmet`;
measured). There is one group per record of the section, at `+0x80 + 4 × s`.
The pointers are relocated by `sub_00129510`. The code that uses the
collision was not found; the layout is measured.

- **Group** (0x20): bounding box min xyz, max xyz (6 floats), polygon count,
  offset of the polygons (0 when none).
- **Polygon** (0x20): u8 corner count N; three u8 axis indices (a permutation
  of 0, 1, 2, probably the projection axes for point-in-polygon tests,
  inferred); plane nx, ny, nz, d (n·p = d, measured against the vertices);
  offset of N corner bytes; adjacency count; offset of the adjacency records
  (0 when the count is 0).
- **Corner bytes**: vertex indices relative to the record's first vertex
  (measured: the plane holds for them).
- **Adjacency**: 5 bytes each. They look like a shared edge (two corner
  positions), then 0, a group index and a polygon index (inferred).

Layout (measured, reproduced by the writer): after the streams of all
sections come all polygons' corner bytes, packed and padded to 4; then for
each group its adjacency records, packed and padded to 4, followed by its
polygons; then the groups.

`hat_X_big/_med/_small` are byte-identical files (measured). The game scales
them.

## LOD, hats and other variants

- `chrNNlod2.xbr`: the distant model, used in its own slot in the roster
  (`docs/formats/roster.md`). It has the same 19-bone hierarchy as the full
  model. Its textures are the full model's, in any order, in 77 of 83; a
  subset in 4; others in 2 (measured).
- `chrNN_hat.xbr`, `hat_*.xbr`: one rigid piece on bone 0, with collision.
  They are attached to the character as separate objects
  (`docs/formats/roster.md`).
- `chrNN_head/_larm/_rarm.xbr`: one rigid piece each (inferred: detached
  parts).

## `chrinc.pak`

`ob/chrincs/chrNN.xbr` is the front end's character-select preview (code
`sub_0009E410`, which formats `host0:ob/chrincs/chr%02d.xbr` and loads it
asynchronously into a 0x7D000-byte buffer per slot). The layout is the same.
Compared with `chr.pak`'s `chrNN.xbr` (measured):

- for 149 of the 155, all bytes from 0x0C + 16 × (materials + 1) to the end
  of the `chr.pak` file are identical: same geometry and pieces. `chr16`,
  `chr35`, `chr127`, `chr129` and `chr146` hold a different model from the
  `chr.pak` file of that name (same 19-bone skeleton); `chr104` has no
  `ob/chrs` counterpart on the disc;
- each material's +0x0 is the file offset of an embedded texture, and +0xC
  has bit 28 set;
- the textures follow the model descriptor, each 128-byte aligned, in the
  `.xbt` file layout (128-byte header, then the mip chain). The game creates
  them in place (code `sub_0001B790` → `sub_001B8190`);
- they have the same size and format as the `chr.pak` texture, but different
  texels: the same picture with different colours (mean |Δ| 10 to 15 per
  channel for chr01).

The buffer limits a `chrinc` file to 512,000 bytes (inferred from the buffer
size; the largest is `chr104.xbr`, 358,760).

## Constraints for a writer

- Piece links and bone indices are `s8`: at most 127 pieces and 127
  palette bones. Record fields are `s16`: at most 32,767 vertices per
  section. Face indices are `u16`. The draw header count has 15 bits.
- Records start on a multiple of 4 vertices, with padding vertices as above.
- Every skinned vertex names the c64 bone, the c68 bone or (for types 2 and 3)
  the piece's own bone.
- Rigid pieces, in depth-first order, must match the bind pose the
  character's animations use (19 for humans).
- `+0x60`, `+0x62` and the draw headers are derived: the tool recomputes them.
- Material ids must exist in a mounted pak's `textures/` (chr.pak's 981 ids
  are used by chr.pak models only). A new texture needs a new id, a new
  `.xbt` and repacked paks (`tools/ts2pak.py`).
- The game loads the file in place and relocates it, so there is no size
  limit beyond memory for `chr.pak`. Level paks carry their own copies of
  the characters they use (`docs/formats/roster.md`), and those copies must
  be replaced too.

## Not explained

- The draw header's constant words `0x302E4000, 0x412`. No code that reads
  them was found.
- Model `+0x08` (always 1) beyond "non-zero adds a lighting call", and `+0x2C`
  and `+0x30` (always 0).
- Which caller passes which section, so the claim that section 1 is the
  alpha pass is inferred from its textures.
- The kind field's exact render effect (code shows 1 and ≥2 select different
  flags; 0 marks vertex-coloured records).
- The meaning of the hat adjacency records, and where the collision is used.
- Why 488 face-list runs use different UV copies than the strips.
- The operand order of the mid-joint blend (`sub_000E7520`).
- Prop and gun models: the piece fields that are zero in characters
  (+0x08 counts, +0x20, +0x68 to +0x7C arrays) are used there. 1,089 of the
  disc's 4,368 `0xC` files (guns, damaged props, pickups) use them, and the
  tool refuses those files.
- How the game picks a bind pose slot for a model. Humans use the 19-bone
  `human_19_bindpose`; that is inferred from the bone counts.

## Tool

```text
python3 -I tools/ts2xbr.py info     chr01.xbr                 # pieces, bones, sections
python3 -I tools/ts2xbr.py check    DIR...                    # parse + coverage + byte-identical rewrite
python3 -I tools/ts2xbr.py rewrite  in.xbr out.xbr
python3 -I tools/ts2xbr.py skeleton DIR...                    # group files by animation hierarchy
python3 -I tools/ts2xbr.py joints   chr01.xbr human_19_bindpose.raw
python3 -I tools/ts2xbr.py obj      chr01.xbr chr01.obj --textures <unpacked chr.pak>/textures
python3 -I tools/ts2gltf.py gltf    chr01.xbr chr01.glb --textures <unpacked chr.pak> --bindpose <bind pose folder>
python3 -I tools/ts2gltf.py fromgltf chr01.xbr edited.glb new.xbr   # see Editing in Blender
```

`obj` writes one group per piece and section, in bind pose. It writes PNGs of
the DXT1 and DXT3 textures (top mip). Pass `--strips` to build the triangles
from the strip form instead of the face lists.

Round trip (PAL): `chr.pak` 314 of 314, `chrinc.pak` 155 of 155. Every file
parses, every byte is accounted for, and every rewrite is byte-identical.

## Editing in Blender

`tools/ts2gltf.py` converts a model to glTF 2.0 binary (`.glb`) and back.
Blender (tested with 5.2) imports and exports `.glb` with its armature and
skin. The converter itself needs only Python 3.

```text
# 1. unpack the character pak, the bind poses and (for the mod) nothing else
python3 -I tools/ts2pak.py unpack game/data/chr.pak     work/chr
python3 -I tools/ts2pak.py unpack game/data/fe_anim.pak work/fe_anim

# 2. export: armature, meshes, textures as PNG
python3 -I tools/ts2gltf.py gltf work/chr/ob/chrs/chr01.xbr chr01.glb \
    --textures work/chr --bindpose work/fe_anim/anim/data/ts2

# 3. edit chr01.glb in Blender (below), export it as chr01_edited.glb

# 4. import: geometry from the .glb, everything else from the original
python3 -I tools/ts2gltf.py fromgltf work/chr/ob/chrs/chr01.xbr chr01_edited.glb mod/files/ob/chrs/chr01.xbr

# 5. put it in every pak that carries chr01 and run
python3 -I tools/ts2mod.py build mod game/data modout
RECOMP_MODS=modout ./split2_recomp
```

**What the `.glb` holds.** One joint per palette bone: the animation bones,
named by animation index and body part (`b04_head`, `b10_l_upperarm`; the
`-X` side is called right, which is the character's right in Blender; whether
the game draws the model mirrored was not checked), and the mid-joint bones
that type-2 pieces synthesise (`mid_r_upperarm_r_forearm`), placed at their
child's joint as at bind time. `--bindpose` takes the folder of bind poses and
uses the one with the model's bone count (human_19 for humans,
barrelbindpose2 for `chr17`); without one, or for hats, joints sit at the
centre of their vertices. One object per piece and section, named
`pNNsS_name` (`p07s0_head`; section 1 is the second pass), one material
slot per material, named `mN_tTTTT` after the material index and texture id,
with the texture embedded. Triangles are the face lists, which is what the
game draws. Every vertex is weighted 1.0 to the one bone it follows.
Piece types, links, blend factors, record kinds and material flags are in
the `extras` of the nodes and materials, for reading only.

**In Blender.** File > Import > glTF 2.0, defaults. Edit the meshes in edit
mode or weight paint them; keep the object names (a `.001` suffix is fine),
the bone names and the material names; do not join objects (each object is
one piece) and do not apply the armature. Delete an object to remove that
piece's geometry. File > Export > glTF 2.0 with the defaults
does it: format glTF Binary, every object (the importer's `Icosphere` bone
shape is skipped by `fromgltf`), +Y Up, Mesh: UVs, Normals and Vertex Colors
(the default "Material" setting keeps them), Apply Modifiers off, Armature
and Skinning on. Animation can be turned off. Moving an object in object
mode is fine: `fromgltf` places vertices where Blender shows them.

**What `fromgltf` does.** It reads positions, normals, UVs, vertex colours,
triangles and their material from the `.glb`, and everything else from the
base `.xbr`. Objects map to pieces by name (`pNNsS`), joints to palette bones
by name, slots to materials by the `mN` prefix. Vertices are put in model
space by the skin at rest. Each vertex gets one bone: a rigid piece's own; in a
skinned piece the strongest-weighted of the bones that piece can use (the
c64, c68 and own bones of [Skinning](#skinning-how-a-piece-is-bound-to-its-matrices)),
or the nearest of them when none is weighted. It prints how many vertices
were snapped away from their strongest bone overall.

A section whose triangles are the base's (positions and UVs within 1e-4,
normals within 5 degrees, colours within 2) is copied from the base
unchanged, so an untouched piece stays byte-identical, and an unedited model
comes back as the original file. Every other section is rebuilt:

- vertices are deduplicated (Blender splits and reorders them);
- triangles are grouped by material, in the base's material order, and
  turned into strips with plain strip winding: the first two vertices of
  each strip carry the restart bit, and no vertex needs the winding-flip
  bit, so the strip form and the face lists agree under either reading;
- strips are packed into records of at most 72 vertices (the largest
  record on the disc; long strips are cut at even offsets with two vertices
  of overlap), padded to multiples of 4 by the writer;
- each material run gets one face list, on its last record, generated from
  its strips; the record kind is the base's for that material;
- a hat's collision is rebuilt from the triangles: one group per record,
  one polygon per triangle with its plane and projection axes (last the
  normal's largest axis, the other two in cyclic order when that component
  is positive, as on the disc), and no adjacency records, whose meaning is
  unknown. Untouched hats keep theirs.

Colours Blender writes without alpha get the base section's alpha (127 in
every coloured vertex on the disc). `--regenerate` rebuilds every section.
The output is parsed and rebuilt before it is written.

**Limits.** One bone per vertex: smooth weights are snapped, so blend
between bones with geometry (as the originals do with joint and mid-joint
pieces), not with weights. New geometry must go in an existing piece and
can only use that piece's bones. Materials and textures are the base's
(a new texture is a new `.xbt` under an existing id: `tools/ts2xbt.py
import`). `chrNNlod2.xbr` is a separate model with its own pieces: export,
edit and import it too, or the character changes back at a distance. Level
paks carry their own copies of the character, which `ts2mod` replaces.

**Tests** (`tools/test_ts2gltf.py`, not run by any build). `roundtrip` over
all 314 files of `chr.pak` and all 155 of `chrinc.pak`: export and import
without an edit gives the original file byte for byte; with `--regenerate`
every file parses, rebuilds identically, has strips and face lists that
agree, records within the limit, every skinned vertex on an allowed bone,
and exactly the original's triangles (piece, section, material, position, UV
and bone of each corner, winding included): 344,756 triangles in `chr.pak`,
in 562,770 stored vertices against the disc's 519,252. `blender` puts
`chr01`, `chr19`, `chr01lod2`, `chr10_hat`, `chr17` and `chr128` through
Blender's importer and exporter (5.2, defaults): the same triangles come
back in both modes (to 1e-4), no vertex is snapped, and the default import
gives the original files byte for byte. What Blender changes: it reorders
vertices, joints and materials, splits a vertex here and there (under 1%)
where it stores two face-corner normals that differ in the last bits,
moves positions by about 1e-8 and normals by under 0.5 degrees, duplicates a
material it uses both with and without vertex colours (`m0_t0775.001`), and
drops the colour alpha on some meshes.

## Against the community references

- The OpenRadical Noesis plugin (`fmt_xbox.py`) reads positions, UVs and
  normals per record and builds triangles from the flag bytes. Its "wind"
  and "flag" bytes are this page's bit 0 and bit 15 of the position's flag
  word. It ignores the face lists, the piece tree, the bone fields and the
  normal's fourth word, and so has no skeleton or skinning.
- The TS-ReSplit wiki's TS2-Model page describes the PS2 material list. On
  the Xbox, +0x4 and +0x8 are 0 and the embedded flag is bit 28 of +0xC.
