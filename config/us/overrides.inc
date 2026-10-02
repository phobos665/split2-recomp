/*
 * TimeSplitters 2, USA release: where the overrides in src/recomp_manual.c
 * attach. Certificate region 0x1, version 2, built 2002-10-01, default.xbe
 * SHA-1 3ec95fe3ae9e7794d83a5b489ad8583f352e0c18. Every sub_XXXXXXXX here is
 * an address in that exact XBE.
 *
 * src/recomp_manual.c includes this, after the hooks it calls, when
 * src/recomp/ts2_region.h says the USA release was lifted, and
 * scripts/build.py gives the lifter the two together (see the end of
 * recomp_manual.c). The reasons for each override are beside its hook there.
 *
 * Each address was found in the USA XBE by what the PAL function does, not
 * by one shift: the USA code is the PAL code moved by a different amount in
 * each stretch of .text (none around 0x22000, -0x30 at the camera, -0x40 to
 * -0x70 through the front end and the HUD, -0x430 from the handheld's map
 * to the menu panels, -0x450 to -0x410 among the drawing functions, -0x430
 * again from the batch on), so each was checked where it is. How is beside
 * it; "PAL 0x..." is the address in config/pal/overrides.inc.
 */

/* camera_setup is sub_00032D90 (PAL 0x00032DC0). It turns its third
 * argument into aspect * width / height, builds the projection with
 * sub_000E6A00 (PAL 0x000E6E30: build_projection, whose other callers are
 * the front end's cameras), and stores tan(fov/2) at camera+0x31C and
 * aspect * tan(fov/2) at camera+0x320 -- the description in recomp_manual.c,
 * instruction for instruction. */
extern void sub_00032D90_gen(void);
void sub_00032D90(void) { ts2_camera_setup(sub_00032D90_gen); }

/* front_end_scene is sub_0009F180 (PAL 0x0009F1C0): it builds its camera
 * through sub_00095CA0 (PAL 0x00095CE0), which calls build_projection. */
extern void sub_0009F180_gen(void);
void sub_0009F180(void) { ts2_front_end_scene(sub_0009F180_gen); }

/* present is sub_001CC100 (PAL 0x001CC530): the only function in the game's
 * code that calls D3DDevice_Swap. */
extern void sub_001CC100_gen(void);
void sub_001CC100(void) { ts2_present(sub_001CC100_gen); }

/* reserve is sub_001C8E35 (PAL 0x001C9265): 52 callers, a switch on its
 * first argument (the primitive type), and it calls the flush. flush is
 * sub_001C98AF (PAL 0x001C9CDF): it draws through sub_001CC1D0, the game's
 * only call of D3DDevice_DrawVertices, and sub_001CC150 (DrawIndexedVertices);
 * sub_001C924C (PAL 0x001C967C) is the other way that calls the draw. */
extern void sub_001C98AF(void);
extern void sub_001C8E35_gen(void);
void sub_001C8E35(void) { ts2_ui_reserve(sub_001C8E35_gen, sub_001C98AF); }
extern void sub_001C98AF_gen(void);
void sub_001C98AF(void) { ts2_ui_batch_flush(sub_001C98AF_gen); }

/* The engine's shared drawing functions, whose callers are the sites. Each is
 * the PAL one at the shift of its stretch of code: a function start there
 * that reaches reserve through its calls (the text ones, through a jmp), in
 * the same order and spacing as the PAL ones. The sites below call 18 of
 * them; sub_001B7110 is called through the thunk at 001B7430 (jmp), as in
 * PAL, so its sites are the callers of the thunk. */
extern void sub_001B5E80_gen(void);   /* PAL 0x001B6290, -0x410 */
void sub_001B5E80(void) { ts2_ui_enter(); sub_001B5E80_gen(); ts2_ui_leave(); }
extern void sub_001B6210_gen(void);   /* PAL 0x001B6620, -0x410 */
void sub_001B6210(void) { ts2_ui_enter(); sub_001B6210_gen(); ts2_ui_leave(); }
extern void sub_001C0F18_gen(void);   /* PAL 0x001C1328, -0x410 */
void sub_001C0F18(void) { ts2_ui_enter(); sub_001C0F18_gen(); ts2_ui_leave(); }
extern void sub_001B5A70_gen(void);   /* PAL 0x001B5E80, -0x410 */
void sub_001B5A70(void) { ts2_ui_enter(); sub_001B5A70_gen(); ts2_ui_leave(); }
extern void sub_001B54D0_gen(void);   /* PAL 0x001B58E0, -0x410 */
void sub_001B54D0(void) { ts2_ui_enter(); sub_001B54D0_gen(); ts2_ui_leave(); }
extern void sub_001B6610_gen(void);   /* PAL 0x001B6A20, -0x410 */
void sub_001B6610(void) { ts2_ui_enter(); sub_001B6610_gen(); ts2_ui_leave(); }
extern void sub_001B75F0_gen(void);   /* PAL 0x001B7A00, -0x410 */
void sub_001B75F0(void) { ts2_ui_enter(); sub_001B75F0_gen(); ts2_ui_leave(); }
extern void sub_001B52C0_gen(void);   /* PAL 0x001B56D0, -0x410 */
void sub_001B52C0(void) { ts2_ui_enter(); sub_001B52C0_gen(); ts2_ui_leave(); }
extern void sub_00058300_gen(void);   /* PAL 0x00058360, -0x60 */
void sub_00058300(void) { ts2_ui_enter(); sub_00058300_gen(); ts2_ui_leave(); }
extern void sub_001B5990_gen(void);   /* PAL 0x001B5DA0, -0x410 */
void sub_001B5990(void) { ts2_ui_enter(); sub_001B5990_gen(); ts2_ui_leave(); }
extern void sub_001B3AC0_gen(void);   /* PAL 0x001B3ED0, -0x410 */
void sub_001B3AC0(void) { ts2_ui_enter(); sub_001B3AC0_gen(); ts2_ui_leave(); }
extern void sub_000C4F10_gen(void);   /* PAL 0x000C4F80, -0x70 */
void sub_000C4F10(void) { ts2_ui_enter(); sub_000C4F10_gen(); ts2_ui_leave(); }
extern void sub_001B75A0_gen(void);   /* PAL 0x001B79B0, -0x410 */
void sub_001B75A0(void) { ts2_ui_enter(); sub_001B75A0_gen(); ts2_ui_leave(); }
extern void sub_001B7450_gen(void);   /* PAL 0x001B7860, -0x410 */
void sub_001B7450(void) { ts2_ui_enter(); sub_001B7450_gen(); ts2_ui_leave(); }
extern void sub_001B7540_gen(void);   /* PAL 0x001B7950, -0x410 */
void sub_001B7540(void) { ts2_ui_enter(); sub_001B7540_gen(); ts2_ui_leave(); }
extern void sub_000AA5B0_gen(void);   /* PAL 0x000AA5F0, -0x40 */
void sub_000AA5B0(void) { ts2_ui_enter(); sub_000AA5B0_gen(); ts2_ui_leave(); }
extern void sub_000AABB0_gen(void);   /* PAL 0x000AABF0, -0x40 */
void sub_000AABB0(void) { ts2_ui_enter(); sub_000AABB0_gen(); ts2_ui_leave(); }
extern void sub_000AA630_gen(void);   /* PAL 0x000AA670, -0x40 */
void sub_000AA630(void) { ts2_ui_enter(); sub_000AA630_gen(); ts2_ui_leave(); }
extern void sub_00138BA0_gen(void);   /* PAL 0x00138FE0, -0x440 */
void sub_00138BA0(void) { ts2_ui_enter(); sub_00138BA0_gen(); ts2_ui_leave(); }
extern void sub_001AB380_gen(void);   /* PAL 0x001AB7C0, -0x440 */
void sub_001AB380(void) { ts2_ui_enter(); sub_001AB380_gen(); ts2_ui_leave(); }
extern void sub_001AC350_gen(void);   /* PAL 0x001AC790, -0x440 */
void sub_001AC350(void) { ts2_ui_enter(); sub_001AC350_gen(); ts2_ui_leave(); }
extern void sub_001AC910_gen(void);   /* PAL 0x001ACD50, -0x440 */
void sub_001AC910(void) { ts2_ui_enter(); sub_001AC910_gen(); ts2_ui_leave(); }
extern void sub_001AC990_gen(void);   /* PAL 0x001ACDD0, -0x440 */
void sub_001AC990(void) { ts2_ui_enter(); sub_001AC990_gen(); ts2_ui_leave(); }
extern void sub_001AC9F0_gen(void);   /* PAL 0x001ACE30, -0x440 */
void sub_001AC9F0(void) { ts2_ui_enter(); sub_001AC9F0_gen(); ts2_ui_leave(); }
extern void sub_001ACA50_gen(void);   /* PAL 0x001ACE90, -0x440 */
void sub_001ACA50(void) { ts2_ui_enter(); sub_001ACA50_gen(); ts2_ui_leave(); }
extern void sub_001ACD10_gen(void);   /* PAL 0x001AD150, -0x440 */
void sub_001ACD10(void) { ts2_ui_enter(); sub_001ACD10_gen(); ts2_ui_leave(); }
extern void sub_001ACD90_gen(void);   /* PAL 0x001AD1D0, -0x440 */
void sub_001ACD90(void) { ts2_ui_enter(); sub_001ACD90_gen(); ts2_ui_leave(); }
extern void sub_001B7110_gen(void);   /* PAL 0x001B7520, -0x410 */
void sub_001B7110(void) { ts2_ui_enter(); sub_001B7110_gen(); ts2_ui_leave(); }

/* Where TimeSplitters 2 (USA, this XBE) draws what: the PAL table with each
 * site moved to the USA return address of the same call -- the shift of its
 * stretch of code, checked on every entry to follow a call to one of the
 * functions wrapped above. Ends at site 0. */
const Ts2UiPlace k_ts2_ui_places[] = {
    /* Full-screen quads, fades and post passes (the glow over the frame). */
    { 0x000224CA, TS2_UI_STRETCH }, { 0x000224F3, TS2_UI_STRETCH },
    { 0x00022520, TS2_UI_STRETCH }, { 0x00022548, TS2_UI_STRETCH },
    { 0x00022635, TS2_UI_STRETCH }, { 0x00022650, TS2_UI_STRETCH },
    { 0x0002266B, TS2_UI_STRETCH }, { 0x0002268A, TS2_UI_STRETCH },
    { 0x000C9FCA, TS2_UI_STRETCH }, { 0x000CA261, TS2_UI_STRETCH },
    { 0x000CA4CA, TS2_UI_STRETCH },
    /* Backdrop: the tunnel ring, the title screen's nebula, the footer. */
    { 0x00088783, TS2_UI_STRETCH }, { 0x000B8559, TS2_UI_STRETCH },
    { 0x000898AF, TS2_UI_STRETCH },
    /* Header banner and the rules under and below it. */
    { 0x000896B4, TS2_UI_STRETCH }, { 0x0008974E, TS2_UI_STRETCH },
    { 0x000897FF, TS2_UI_STRETCH }, { 0x0008982A, TS2_UI_STRETCH },
    { 0x00089852, TS2_UI_STRETCH }, { 0x000898D7, TS2_UI_STRETCH },
    /* Left edge: the scrolling binary, the logo and the screen's name
     * beneath it, the button hints. */
    { 0x00088565, TS2_UI_LEFT }, { 0x000885BD, TS2_UI_LEFT },
    { 0x000897D6, TS2_UI_LEFT }, { 0x00089965, TS2_UI_LEFT },
    { 0x000EFFE5, TS2_UI_LEFT },
    /* Right edge: the purple glow. */
    { 0x00088972, TS2_UI_RIGHT },
    /* Kept in proportion: panels, their glow and selection bar, menu
     * items, the title logo, the level name, the loading picture. The glow
     * (000EF3F4) is the panel's shadow as well as its rays, so it stays
     * with the panel; on the story screens, where the panel is at the
     * right, its rays end at the old edge. */
    { 0x000EF3F4, TS2_UI_CENTRE }, { 0x000EF00A, TS2_UI_CENTRE },
    { 0x000EEB67, TS2_UI_CENTRE }, { 0x000EFCD6, TS2_UI_CENTRE },
    { 0x000EE359, TS2_UI_CENTRE }, { 0x000EE3D4, TS2_UI_CENTRE },
    { 0x000EE3B8, TS2_UI_CENTRE }, { 0x000EE398, TS2_UI_CENTRE },
    { 0x000EE374, TS2_UI_CENTRE }, { 0x000EE61D, TS2_UI_CENTRE },
    { 0x000F155A, TS2_UI_CENTRE }, { 0x000F15E6, TS2_UI_CENTRE },
    { 0x00088F73, TS2_UI_CENTRE }, { 0x0008905B, TS2_UI_CENTRE },
    { 0x000EFA27, TS2_UI_CENTRE }, { 0x00089CF5, TS2_UI_CENTRE },
    { 0x001A1CEB, TS2_UI_CENTRE }, { 0x000895A6, TS2_UI_CENTRE },

    /* Arcade screens: the hex backdrop, the level list's pictures, the
     * character select (portraits, name, stats, the picture of the one
     * chosen), the panel's corners and scroll arrow, and the row of
     * player figures at the bottom right, opposite the button hints. */
    { 0x000A5045, TS2_UI_STRETCH },
    { 0x0008A3A2, TS2_UI_CENTRE }, { 0x0008F7F7, TS2_UI_CENTRE },
    { 0x0008F975, TS2_UI_CENTRE }, { 0x0008F9E6, TS2_UI_CENTRE },
    { 0x0008FBE3, TS2_UI_CENTRE }, { 0x001B706A, TS2_UI_CENTRE },
    { 0x001B70B3, TS2_UI_CENTRE }, { 0x001B70EF, TS2_UI_CENTRE },
    { 0x000EE3FA, TS2_UI_CENTRE }, { 0x000EE416, TS2_UI_CENTRE },
    { 0x000F022F, TS2_UI_CENTRE },
    { 0x0008E94D, TS2_UI_RIGHT },

    /* In-game HUD, from an Arcade match: the rank badge in the top left
     * corner, the radar in the top right, each hand's ammo at its own
     * bottom corner (one piece of code draws both, hence SIDE), the kill
     * message and the crosshair in the middle. The health and armour arcs
     * are one ellipse framing the view, so it spans the picture. */
    { 0x000BCECE, TS2_UI_LEFT },   { 0x000BCF3E, TS2_UI_LEFT },
    { 0x000BD0B9, TS2_UI_LEFT },
    { 0x000BFD4E, TS2_UI_RIGHT },  { 0x000BFF64, TS2_UI_RIGHT },
    { 0x000BFFC3, TS2_UI_RIGHT },  { 0x000C0204, TS2_UI_RIGHT },
    { 0x000C02B4, TS2_UI_RIGHT },  { 0x000C03CF, TS2_UI_RIGHT },
    { 0x000BE5FC, TS2_UI_SIDE },   { 0x000BEDE7, TS2_UI_SIDE },
    /* The dark backing drawn under each ammo number, from its own call
     * site: left to the width guess it stayed in the 4:3 layout, beside
     * the bars, while the number went to the corner. */
    { 0x000BE5CF, TS2_UI_SIDE },
    { 0x000BC2AC, TS2_UI_CENTRE }, { 0x00058610, TS2_UI_CENTRE },
    { 0x000C92DF, TS2_UI_STRETCH },
    /* Sprites the game places in the world and projects to the screen
     * itself (the brazier's flame, muzzle flashes): they were projected
     * through the widened camera, so they are already where the 3D is and
     * squeezing them would pull them off it. */
    { 0x001BFE0F, TS2_UI_STRETCH }, { 0x001BE7AE, TS2_UI_STRETCH },
    { 0x001BE7E4, TS2_UI_STRETCH }, { 0x001BE947, TS2_UI_STRETCH },
    /* The handheld's map. It is drawn at the start of the frame into a
     * corner of the back buffer (x 128 on, scissored to 128..309 by
     * 0..181), copied out of it with CopyRects into the 128x128 texture the
     * handheld's screen shows, and the screen is then cleared for the
     * level. Whatever is drawn there has to stay at its own pixels, or
     * widescreen's squeeze moves it out of the corner that is copied. */
    { 0x000E6146, TS2_UI_STRETCH }, { 0x000E4C4E, TS2_UI_STRETCH },
    { 0x000E50E7, TS2_UI_STRETCH }, { 0x000E51B5, TS2_UI_STRETCH },
    { 0x000E4458, TS2_UI_STRETCH }, { 0x000E44E1, TS2_UI_STRETCH },
    { 0x000E53C5, TS2_UI_STRETCH }, { 0x000E63EC, TS2_UI_STRETCH },
    /* Pause menu (in-game Start): the ring of health and armour arcs
     * (sub_000D1DD0, every page, through the same arc helper as the HUD's
     * 000C92DF) and the dark cap across its top. Left to the width guess,
     * a piece of the ring the engine's batch cut off at less than 75% of
     * the width -- the cut point moves frame to frame as the batch fills --
     * was squeezed for that frame, and the arc flickered inward. */
    { 0x000D1E8F, TS2_UI_STRETCH },
    { 0x000CDA90, TS2_UI_STRETCH }, { 0x000CDAB6, TS2_UI_STRETCH },
    /* Its backing: the dim, letterbox bars and rules, the blue backdrop.
     * Always full width, so the guess got them right; set so they stay
     * right under RECOMP_WIDESCREEN_2D=centre too. */
    { 0x000CCB1F, TS2_UI_STRETCH }, { 0x000CCB43, TS2_UI_STRETCH },
    { 0x000CCB67, TS2_UI_STRETCH }, { 0x000CCB95, TS2_UI_STRETCH },
    { 0x000CCBC0, TS2_UI_STRETCH }, { 0x000CCA8E, TS2_UI_STRETCH },
    { 0, TS2_UI_AUTO }
};
