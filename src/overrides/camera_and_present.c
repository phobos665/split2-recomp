/*
 * camera_and_present.c -- TimeSplitters 2: the widescreen camera, which
 *
 * frames are drawn wide, and frame interpolation's matrix registers.
 *
 * Moved unchanged from recomp_manual.c. Overrides here are found by the
 * lifter the same way (manual_scan.py scans src/overrides/).
 */
#include "ts2/ts2_guest.h"

/* ── TimeSplitters 2: the widescreen camera ───────────────── */

/*
 * TimeSplitters 2 has no 16:9 mode. The toolkit's Hor+ (RECOMP_HOR_PLUS)
 * widens it by scaling the projection register as it is uploaded, but the
 * game culls against its own numbers: past the old 4:3 edges, and through
 * doorways, whole pieces of the level were missing and the sky showed
 * through the walls.
 *
 * The in-game camera is set up in one place, sub_00032DC0(near, far,
 * aspect, fov_degrees). It turns the aspect into the screen's
 * (aspect * width / height), builds the projection from it with
 * sub_000E6E30(out, aspect, fovy, near, far), and stores tan(fov/2) at
 * camera+0x31C and aspect * tan(fov/2) -- the horizontal half-width the
 * culling uses -- at camera+0x320. Widening the aspect argument on the
 * way in widens both, so what is drawn and what is kept agree.
 *
 * Only this camera: the other callers of sub_000E6E30 are the front end's
 * 3D (character select and the like), which is kept at 4:3.
 */
/* xboxrecomp src/d3d/d3d8_xbox.h */
extern float xbox_D3D8ClaimHorPlus(void);
extern void  xbox_D3D8SetWideFrames(int wide);


/* The factor to multiply the camera's aspect by: 1 when no wider view is
 * wanted, 4/3 for the usual Hor+ 0.75. Claiming it stops the toolkit
 * scaling the register as well, which would widen the view twice. */
static float ts2_camera_widen(void)
{
    static float widen;

    if (widen == 0.0f) {
        float factor = xbox_D3D8ClaimHorPlus();

        widen = (factor > 0.0f && factor != 1.0f) ? 1.0f / factor : 1.0f;
    }
    return widen;
}

/* What the frame now being drawn has run, for the choice below. */
static int g_ts2_frame_camera, g_ts2_frame_front_end;

extern void sub_00032DC0_gen(void);
void sub_00032DC0(void)
{
    float widen = ts2_camera_widen();

    if (widen != 1.0f)
        TS2_MEMF(g_esp + 0x0C) *= widen;   /* [esp] is the return address */
    sub_00032DC0_gen();
    g_ts2_frame_camera = 1;                /* see sub_001CC530 below */
}

/*
 * The front end at 4:3, if asked (RECOMP_TS2_MENUS=43 below). It is laid
 * out for 4:3 and mixes 3D backdrops with 2D panels; left to the
 * renderer's width guess its pieces juddered between stretched and
 * squeezed as they animated. The placement table below fixes that, and
 * this is the fallback: the front end shown at 4:3 between bars, as the
 * console drew it, and the levels and their cutscenes at 16:9.
 *
 * Which screen a frame belongs to, traced frame by frame through a run:
 *
 *   menus, story level select   in-game camera + sub_0009F1C0
 *   in-engine cutscenes         in-game camera
 *   playing                     in-game camera
 *   loading screens             neither
 *
 * sub_0009F1C0 sets up the front end's own 3D scene (it builds its camera
 * through sub_00095CE0). The front end draws its backdrop through the
 * in-game camera as well, hence the pair.
 *
 * sub_001CC530 is the game's once-a-frame present (it calls
 * D3DDevice_Swap). After a frame is presented, the next is given the shape
 * the finished one called for: a frame's own draws are not all in yet
 * when it starts, and a screen lasts many frames, so the only cost is one
 * frame at each change, which falls on a fade or a load.
 */
extern void sub_0009F1C0_gen(void);
void sub_0009F1C0(void)
{
    g_ts2_frame_front_end = 1;
    sub_0009F1C0_gen();
}

/*
 * RECOMP_TS2_MENUS / ts2_menus = wide (the default) lays the front end out
 * for 16:9 with the placement table below, so every screen is widescreen;
 * 43 keeps the front end and the loading screens at 4:3 between bars, as
 * above.
 */

static int ts2_menus_wide(void)
{
    static int wide = -1;

    if (wide < 0) {
        const char *v = recomp_config_lookup("RECOMP_TS2_MENUS", "ts2_menus");

        wide = !(v && (!strcmp(v, "43") || !strcmp(v, "4:3")));
        fprintf(stderr, "[TS2-UI] menus %s (RECOMP_TS2_MENUS=wide|43)\n",
                wide ? "laid out for 16:9" : "at 4:3");
    }
    return wide;
}

/*
 * Frame interpolation (xboxrecomp hle_d3d8_interp.c, RECOMP_FRAME_INTERP)
 * blends the matrices in TS2's vertex constants, measured from captures:
 * c60-c63 hold the projection alone, set once or twice a frame; c64-c67
 * the model-view of each object; c68-c75 the second and third matrices of
 * a skinned piece's palette. All affine, rows with (0,0,0,1) last. Said
 * once, at the first present, which is before any level is drawn.
 */
extern void xbox_D3D8SetInterpRegisters(int projection, int affine_first, int affine_count);

extern void sub_001CC530_gen(void);
void sub_001CC530(void)
{
    static int interp_said;

    if (!interp_said) {
        interp_said = 1;
        xbox_D3D8SetInterpRegisters(60, 64, 12);
    }
    sub_001CC530_gen();
    xbox_D3D8SetWideFrames(ts2_menus_wide() ||
                           (g_ts2_frame_camera && !g_ts2_frame_front_end));
    g_ts2_frame_camera = g_ts2_frame_front_end = 0;
}
