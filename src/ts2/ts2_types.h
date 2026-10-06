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

#endif /* TS2_TYPES_H */
