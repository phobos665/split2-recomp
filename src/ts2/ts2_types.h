/*
 * ts2_types.h -- what is known about TimeSplitters 2's own functions and
 * data, as C types, so an override says `args->aspect` instead of
 * `TS2_MEMF(g_esp + 0x0C)`.
 *
 * Every name here is ours, assigned while reverse engineering; none comes
 * from the game's source. Each entry says where it was found and how sure it
 * is. Addresses are in the PAL default.xbe (CLAUDE.md, "The title"); another
 * release needs its own.
 *
 * The guest is 32-bit: a guest pointer is a uint32_t guest address, never a
 * C pointer, so these structs hold only fixed-size integers and floats and
 * have the same layout on the host. Read one through ts2_view() below.
 *
 * Add to this file as things are found, with the evidence beside them. A
 * field that is a guess says so; one nobody has confirmed stays out.
 */
#ifndef TS2_TYPES_H
#define TS2_TYPES_H

#include "ts2/ts2_guest.h"

/* A guest address as a host pointer to T. Volatile, like guest memory: the
 * lifted code and other guest threads change it behind the compiler. */
#define ts2_view(T, guest_addr) \
    ((volatile T *)((uintptr_t)(uint32_t)(guest_addr) + g_xbox_mem_offset))

/* The arguments of a stdcall/cdecl function at its entry, where [esp] is
 * the return address the lifted call pushed. */
#define ts2_args(T) ts2_view(T, g_esp)

/* ── The in-game camera ─────────────────────────────────────────────────
 *
 * sub_00032DC0(near, far, aspect, fov_degrees) sets up the in-game camera:
 * it turns the aspect into the screen's (aspect * width / height), builds
 * the projection through sub_000E6E30(out, aspect, fovy, near, far), and
 * stores the culling half-extents in the camera object. Found while making
 * widescreen (src/overrides/camera_and_present.c), from the disassembly and
 * confirmed in play: widening `aspect` widens what is drawn and what is
 * culled together. */
typedef struct Ts2CameraSetupArgs {
    uint32_t return_address;
    float    near_plane;
    float    far_plane;
    float    aspect;
    float    fov_degrees;
} Ts2CameraSetupArgs;

/* Offsets into the camera object sub_00032DC0 fills. How the object itself
 * is reached is not written down yet, so these are offsets, not a struct. */
#define TS2_CAMERA_TAN_HALF_FOV      0x31C   /* tan(fov / 2) */
#define TS2_CAMERA_HALF_WIDTH        0x320   /* aspect * tan(fov / 2): what culling tests */

/* ── The frame ──────────────────────────────────────────────────────────
 *
 * sub_001CC530   the game's once-a-frame present (it calls D3DDevice_Swap).
 * sub_0009F1C0   sets up the front end's own 3D scene (its camera is built
 *                through sub_00095CE0).
 *
 * Vertex shader constants, measured from frame captures (frame
 * interpolation): c60-c63 the projection, set once or twice a frame;
 * c64-c67 each object's model-view; c68-c75 the second and third matrices
 * of a skinned piece's palette. All affine, rows with (0,0,0,1) last. */
#define TS2_VS_PROJECTION     60
#define TS2_VS_MODELVIEW      64
#define TS2_VS_MATRIX_COUNT   12   /* c64..c75 */

/* ── 2D drawing ─────────────────────────────────────────────────────────
 *
 * sub_001C9265(primitive, format, ?, count) reserves vertices in the
 * engine's 2D batch for its caller to fill; sub_001C9CDF draws the batch
 * (DrawVertices). Every piece of 2D -- menus, HUD, text -- goes through the
 * reservation, positioned in 640x480 pixels on the CPU. The third argument
 * is not understood. (src/overrides/ui_placement.c) */
typedef struct Ts2Reserve2DArgs {
    uint32_t return_address;   /* the call site: what ui_placement keys on */
    uint32_t primitive;
    uint32_t format;
    uint32_t unknown;
    uint32_t count;
} Ts2Reserve2DArgs;

/* ── Archives ──────────────────────────────────────────────────────────
 *
 * sub_00085DB0(name, ?, 1) mounts one .pak (P4CK parsed there, P8CK in
 * sub_00085C50) into the next free slot, or reuses the slot already holding
 * that name; it returns the slot, which no caller keeps. sub_000865C0
 * closes them all and mounts a level's set. sub_000860A0(name) finds a file:
 * it drops a "host0:" prefix and searches the slots from 0, first match
 * wins. Found reading the mount and lookup functions (6 Oct 2026);
 * src/overrides/archives.c reorders the table. */
#define TS2_PAK_COUNT       0x00358A18u   /* int32: slots in use */
#define TS2_PAK_TABLE       0x00358A38u   /* the slots */
#define TS2_PAK_SLOTS       25
#define TS2_PAK_SLOT_SIZE   0x20
#define TS2_PAK_SLOT_NAME   0x1C          /* guest pointer to the mounted name */

/* ── The player ─────────────────────────────────────────────────────────
 *
 * Found by RAM snapshots in Siberia (6 Oct 2026; RECOMP_INPUT_SEQ `snap`
 * steps, one shot between each): the clip of the rifle picked up at the
 * start counts 5, 4, 3, 2 at record +0x44C, and two .data globals point at
 * the record. The record itself is on the heap (0x82B64FF0 in those runs).
 *
 * Measured across the pickup: +0x438 went from 35 to 6 and +0x44C from 0
 * to 5, and +0x9B0 (0 -> 1) and +0xA3C (0 -> 5) changed together. Those
 * last two are 0x8C bytes apart -- 35 dwords, the size of the game's
 * weapon list -- so they read as two arrays with one entry per weapon
 * ("held" and "reserve ammunition", by their values). 35 is the Temporal
 * Uplink (the handheld map the player starts with) if the weapon names
 * table (.data 0x00337BC4 in English) is counted from its blank first
 * entry, which would make the rifle weapon 6 in the game's own numbering;
 * that numbering is not confirmed yet. Not found yet: where a weapon's
 * clip size and other tuning come from (not in the XBE as plain arrays of
 * 35 small integers). */
#define TS2_PLAYER_PTR          0x00356AA8u   /* guest pointer to the player record */
#define TS2_PLAYER_PTR_2        0x004B1C60u   /* the same pointer, held a second time */
#define TS2_PLAYER_WEAPON       0x438         /* int32: current weapon (see above) */
#define TS2_PLAYER_CLIP         0x44C         /* int32: rounds in the current weapon */

/* ── Weapons ────────────────────────────────────────────────────────────
 *
 * The weapon definitions are a table in the XBE's own .data: 36 records of
 * 0x240 bytes at 0x002C3888, indexed by weapon id (player +0x438). Found
 * with a watch on the player's clip (RECOMP_WATCH_WRITE=*0x00356AA8+0x44C,
 * armed by the input script): the reload, sub_000ABA30, computes
 * 0x2C3888 + id * 0x240 and reads the fields below (6 Oct 2026).
 *
 * Weapon 6 is the Sniper Rifle ("Got the Sniper Rifle" on pickup in
 * Siberia). Patching its clip from 5 to 10 through a patch file gave a
 * 10-round clip in game, so these values are read live from this table.
 * Every definition's name is below ("Names").
 *
 * The weapon object (player +0x408) keeps one clip per ammunition type,
 * at +0x34 + type * 4: the rifle's (type 4) is +0x44, which is the
 * player record's +0x44C. Reserve ammunition is per type too, at player
 * +0xA2C + type * 4. Fields not listed are not known yet; the record holds
 * plenty of floats (+0x54, +0x58, +0x5C, +0x78, +0x7C and on) that look
 * like tuning. */
#define TS2_WEAPON_TABLE        0x002C3888u
#define TS2_WEAPON_COUNT        36
#define TS2_WEAPON_SIZE         0x240
#define TS2_WEAPON_AMMO_TYPE    0x10   /* int32: primary ammunition type */
#define TS2_WEAPON_CLIP_SIZE    0x14   /* int32: primary clip; 0 or 1 = no clip */
#define TS2_WEAPON_AMMO2_TYPE   0x18   /* int32: secondary fire's type, 0 = none */
#define TS2_WEAPON_CLIP2_SIZE   0x1C   /* int32: secondary clip */
#define TS2_PLAYER_WEAPON_OBJ   0x408  /* the current weapon's object */
#define TS2_PLAYER_RESERVE      0xA2C  /* int32[type]: reserve ammunition */
#define TS2_WEAPON_SNIPER_RIFLE 6
#define TS2_WEAPON_FIRE         0x60   /* the fire-mode block sub_00029DD0 reads */
#define TS2_WEAPON_PROJ_SPEED   0x7C   /* float: projectile speed (fire block +0x1C) */

/* Names. A pickup carries a weapon *type*, a second table: 42 records of
 * 72 bytes at 0x002CA5F0, whose first word is the name's string number in
 * the language's string table (the table for language L is
 * [0x003362F0 + L * 4]; English 0x00336308). sub_000B5F00 makes "Got the
 * <name>" from it. A definition's first word is its type's second word
 * minus one, which pairs the two tables; tools/ts2_weapons.py prints every
 * definition with its name and fields from the player's own XBE. */
#define TS2_WEAPON_TYPE_TABLE   0x002CA5F0u
#define TS2_WEAPON_TYPE_COUNT   42
#define TS2_WEAPON_TYPE_SIZE    72
#define TS2_STRINGS_BY_LANGUAGE 0x003362F0u   /* guest pointer per language */

/* ── Time ───────────────────────────────────────────────────────────────
 *
 * A tick engine (6 Oct 2026, reading sub_001AE3C0 and sub_001543E0, and two
 * runs at 60 and 120 Hz guest vblank). Once a frame, sub_001AE3C0 sets the
 * frame's step to the vblanks since the last frame (sub_001C85C0, kept at
 * 0x40BE90), clamped to 1..3. The game clock adds it; each object on the
 * update list (sub_001543E0) then steps by the clock minus its own last
 * update (object +0x18), clamped to 5, written to the same step globals
 * while it runs. Per-tick constants assume a 60 Hz tick: a 120 Hz vblank
 * runs the game at double speed. src/overrides/frame_step.c experiments
 * with fractional steps. */
#define TS2_FRAME_VBLANKS       0x00348CE0u   /* int32: vblanks this frame, 1..3 */
#define TS2_FRAME_STEP          0x00348CE4u   /* int32: ticks this step (frame or object) */
#define TS2_FRAME_VBLANKS_F     0x00348CE8u   /* float copy of TS2_FRAME_VBLANKS */
#define TS2_FRAME_STEP_F        0x00348CECu   /* float copy of TS2_FRAME_STEP; 0 = paused */
#define TS2_GAME_CLOCK          0x004AD3E8u   /* int32: ticks */
#define TS2_VBLANK_COUNT        0x0040BE90u   /* int32: vblanks, read each frame */

#endif /* TS2_TYPES_H */
