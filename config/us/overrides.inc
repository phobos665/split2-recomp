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

#include <math.h>

/* camera_setup is sub_00032D90 (PAL 0x00032DC0). It turns its third
 * argument into aspect * width / height, builds the projection with
 * sub_000E6A00 (PAL 0x000E6E30: build_projection), and stores tan(fov/2)
 * at camera+0x31C and aspect * tan(fov/2) at camera+0x320.
 * This matches the description in recomp_manual.c,
 * instruction for instruction. */
extern void sub_00032D90_gen(void);
void sub_00032D90(void) { ts2_camera_setup(sub_00032D90_gen); }

/* The two decal passes build their own depth-biased projection from the
 * viewport aspect. Give it the same aspect multiplier as the world camera. */
extern void sub_000E6A00_gen(void);
void sub_000E6A00(void)
{
    uint32_t caller = TS2_MEM32(g_esp);

    if (caller == 0x00058574u || caller == 0x000593E7u) {
        float widen = ts2_camera_widen();

        if (widen != 1.0f)
            TS2_MEMF(g_esp + 8u) *= widen;
    }
    sub_000E6A00_gen();
}

/* US player aim/raycast update: compensate for the widened camera when
 * converting reticle X/Y into a world ray. */
extern void sub_00144890_gen(void);
void sub_00144890(void) { ts2_aim_projection(sub_00144890_gen); }

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
extern int d3d8_display_wide_now(void);
extern unsigned d3d8_GetGuestWidth(void);
extern unsigned d3d8_GetGuestHeight(void);
extern void recomp_widescreen_aspect(unsigned *width, unsigned *height);

/* The modern sniper draws a moving rounded rectangle. CENTRE squeezes the
 * GPU viewport *after* clipping to the 4:3 picture. At full left aim the
 * reticle consequently stopped at x=80 even though the shade reached x=0.
 * Give this optic its centred X coordinates before guest and GPU clipping,
 * then submit to the full player viewport. Keep the transform local to the
 * draw routine, including its calls to the shared font and cartridge code. */
typedef struct { float centre, scale; } Ts2SniperLayout;
static RECOMP_MANUAL_TLS Ts2SniperLayout g_ts2_sniper;

extern void sub_000C2CB0_gen(void);
void sub_000C2CB0(void)
{
    Ts2SniperLayout saved = g_ts2_sniper;
    g_ts2_sniper.scale = 0.0f;
    if (TS2_MEM32(g_esp + 16u) && d3d8_display_wide_now()) {
        unsigned w = d3d8_GetGuestWidth(), h = d3d8_GetGuestHeight();
        unsigned aw, ah;
        uint32_t vp = TS2_MEM32(0x00483F28u);
        recomp_widescreen_aspect(&aw, &ah);
        if (w && h && aw && ah && vp && TS2_MEM32(vp) == 0 &&
            TS2_MEM32(vp + 4u) == w - 1u) {
            float scale = ((float)w * ah) / ((float)h * aw);
            if (scale != 1.0f) {
                g_ts2_sniper.centre = w * 0.5f;
                g_ts2_sniper.scale = scale;
            }
        }
    }
    sub_000C2CB0_gen();
    g_ts2_sniper = saved;
}

static float ts2_sniper_x(float x)
{
    return g_ts2_sniper.centre + (x - g_ts2_sniper.centre) * g_ts2_sniper.scale;
}

static int ts2_sniper_places_quad(void)
{
    return g_ts2_sniper.scale && g_ts2_depth &&
           ts2_ui_place_for(g_ts2_chain[0]) == TS2_UI_STRETCH;
}

static void ts2_sniper_float_quad(void (*draw)(void))
{
    uint32_t args = g_esp + 4u;
    uint32_t x0 = TS2_MEM32(args), x1 = TS2_MEM32(args + 8u);
    TS2_MEMF(args) = ts2_sniper_x(TS2_MEMF(args));
    TS2_MEMF(args + 8u) = ts2_sniper_x(TS2_MEMF(args + 8u));
    draw();
    TS2_MEM32(args) = x0;
    TS2_MEM32(args + 8u) = x1;
}

extern void sub_001B5E80_gen(void);   /* PAL 0x001B6290, -0x410 */
void sub_001B5E80(void)
{
    ts2_ui_enter();
    /* The scene copy covers the viewport. Glyphs have already been placed
     * at their visibility test in 001AB380. The other textured quads are
     * the authored corners and the cartridge strip. */
    if (ts2_sniper_places_quad() && g_ts2_chain[0] != 0x000C31F3u &&
        TS2_MEM32(g_esp) != 0x001AB3FAu)
        ts2_sniper_float_quad(sub_001B5E80_gen);
    else
        sub_001B5E80_gen();
    ts2_ui_leave();
}
extern void sub_001B6210_gen(void);   /* PAL 0x001B6620, -0x410 */
void sub_001B6210(void) { ts2_ui_enter(); sub_001B6210_gen(); ts2_ui_leave(); }
extern void sub_001C0F18_gen(void);   /* PAL 0x001C1328, -0x410 */
void sub_001C0F18(void) { ts2_ui_enter(); sub_001C0F18_gen(); ts2_ui_leave(); }
extern void sub_001B5A70_gen(void);   /* PAL 0x001B5E80, -0x410 */
void sub_001B5A70(void) { ts2_ui_enter(); sub_001B5A70_gen(); ts2_ui_leave(); }
extern void sub_001B54D0_gen(void);   /* PAL 0x001B58E0, -0x410 */
/* The two scope renderers use this untextured gradient quad for the eight
 * pieces between the lens and the player viewport. The lens uses the
 * renderer's centred 2D transform. Apply that transform to the inner
 * endpoints only, leaving the mask's outer endpoints on the viewport. */
static void ts2_scope_mask_quad(uint32_t site)
{
    uint32_t args = g_esp + 4u;
    uint32_t viewport = TS2_MEM32(0x00483F28u);
    float left = (float)(int32_t)TS2_MEM32(viewport);
    float right = (float)(int32_t)TS2_MEM32(viewport + 4u);
    unsigned guest_w = d3d8_GetGuestWidth();
    unsigned guest_h = d3d8_GetGuestHeight();
    unsigned aspect_w, aspect_h;
    float centre = guest_w * 0.5f;
    uint32_t saved_left = TS2_MEM32(args);
    uint32_t saved_right = TS2_MEM32(args + 8u);

    recomp_widescreen_aspect(&aspect_w, &aspect_h);
    if (guest_w && guest_h && ts2_ui_place_for(site) == TS2_UI_STRETCH) {
        float scale = ((float)guest_w * aspect_h) / ((float)guest_h * aspect_w);
        float x0 = TS2_MEMF(args), x1 = TS2_MEMF(args + 8u);
        int move_x0 = x0 != left && x0 != right;
        int move_x1 = x1 != left && x1 != right;
        if (g_ts2_sniper.scale) {
            /* Only the three left pieces pin x0 and the three right pieces
             * pin x1. A lens edge can equal 0 or 639 at one aim position. */
            move_x0 = site != 0x000C2F37u && site != 0x000C2F88u && site != 0x000C3025u;
            move_x1 = site != 0x000C2F62u && site != 0x000C2FD6u && site != 0x000C3050u;
        }
        if (move_x0)
            TS2_MEMF(args) = centre + (x0 - centre) * scale;
        if (move_x1)
            TS2_MEMF(args + 8u) = centre + (x1 - centre) * scale;
    }
    sub_001B54D0_gen();
    TS2_MEM32(args) = saved_left;
    TS2_MEM32(args + 8u) = saved_right;
}

void sub_001B54D0(void)
{
    uint32_t site = TS2_MEM32(g_esp);
    ts2_ui_enter();
    if (((site >= 0x000C2F37u && site <= 0x000C3050u) ||
         (site >= 0x000C3AFAu && site <= 0x000C3C13u)) &&
        g_ts2_depth == 1 && d3d8_display_wide_now())
        ts2_scope_mask_quad(site);
    else
        sub_001B54D0_gen();
    ts2_ui_leave();
}
extern void sub_001B6610_gen(void);   /* PAL 0x001B6A20, -0x410 */
void sub_001B6610(void) { ts2_ui_enter(); sub_001B6610_gen(); ts2_ui_leave(); }
extern void sub_001B75F0_gen(void);   /* PAL 0x001B7A00, -0x410 */
void sub_001B75F0(void) { ts2_ui_enter(); sub_001B75F0_gen(); ts2_ui_leave(); }
extern void sub_001B52C0_gen(void);   /* PAL 0x001B56D0, -0x410 */
typedef struct { float left, right; } Ts2SniperSpan;
static RECOMP_MANUAL_TLS const Ts2SniperSpan *g_ts2_sniper_span;

void sub_001B52C0(void)
{
    ts2_ui_enter();
    if (g_ts2_sniper_span && TS2_MEM32(g_esp) == 0x001B7501u) {
        /* The integer clipper passed the visible pixel bounds. Intersect
         * them with the subpixel span. This writer adds one to x1 itself. */
        uint32_t args = g_esp + 4u;
        TS2_MEMF(args) = fmaxf(TS2_MEMF(args), g_ts2_sniper_span->left);
        TS2_MEMF(args + 8u) = fminf(TS2_MEMF(args + 8u) + 1.0f,
                                     g_ts2_sniper_span->right) - 1.0f;
    }
    sub_001B52C0_gen();
    ts2_ui_leave();
}
extern void sub_00058300_gen(void);   /* PAL 0x00058360, -0x60 */
void sub_00058300(void) { ts2_ui_enter(); sub_00058300_gen(); ts2_ui_leave(); }
extern void sub_001B5990_gen(void);   /* PAL 0x001B5DA0, -0x410 */
void sub_001B5990(void) { ts2_ui_enter(); sub_001B5990_gen(); ts2_ui_leave(); }
extern void sub_001B3AC0_gen(void);   /* PAL 0x001B3ED0, -0x410 */
void sub_001B3AC0(void) { ts2_ui_enter(); sub_001B3AC0_gen(); ts2_ui_leave(); }
extern void sub_000C4F10_gen(void);   /* PAL 0x000C4F80, -0x70 */
void sub_000C4F10(void) { ts2_ui_enter(); sub_000C4F10_gen(); ts2_ui_leave(); }
extern void sub_001B75A0_gen(void);   /* PAL 0x001B79B0, -0x410 */
void sub_001B75A0(void)
{
    uint32_t site = TS2_MEM32(g_esp);

    /* The vintage scope's four mask quadrants move with the aim. Their outer
     * edges stop at the 4:3 picture, so panning reveals the scene beyond.
     * Push the outer edge far past the screen; the rasteriser clips it back.
     * The left pair's outer edge is its x0 (first argument), the right
     * pair's is its x1 (third argument). */
    if (site == 0x000C2B81u || site == 0x000C2B9Eu ||
        site == 0x000C2BC4u || site == 0x000C2BE1u) {
        int32_t x0 = (int32_t)TS2_MEM32(g_esp + 4u);
        int32_t x1 = (int32_t)TS2_MEM32(g_esp + 12u);
        int32_t y0 = (int32_t)TS2_MEM32(g_esp + 8u);
        int32_t y1 = (int32_t)TS2_MEM32(g_esp + 16u);
        int32_t u0 = (int32_t)TS2_MEM32(g_esp + 20u);
        int32_t u1 = (int32_t)TS2_MEM32(g_esp + 28u);
        unsigned guest_w = d3d8_GetGuestWidth();
        unsigned guest_h = d3d8_GetGuestHeight();
        unsigned aspect_w, aspect_h;
        float scale, fade, centre;

        recomp_widescreen_aspect(&aspect_w, &aspect_h);
        scale = (!guest_w || !guest_h || !aspect_w || !aspect_h) ? 1.0f :
                ((float)guest_w * aspect_h) / ((float)guest_h * aspect_w);
        centre = (float)guest_w * 0.5f;
        if (!guest_w || !guest_h || !aspect_w || !aspect_h || y1 == y0)
            fade = (float)(y1 - y0);
        else
            /* The fade must look as tall as it is wide on the widescreen
             * picture: stretch back the guest X span by the aspect factor. */
            fade = (float)(y1 - y0) * scale;
        if (fade < 1.0f)
            fade = 1.0f;

        if (site == 0x000C2B81u || site == 0x000C2B9Eu) {
            int32_t inner = (int32_t)(centre + ((float)x1 - centre) * scale);
            TS2_MEM32(g_esp + 4u) = (uint32_t)(int32_t)-2000;
            TS2_MEM32(g_esp + 12u) = (uint32_t)inner;
            TS2_MEM32(g_esp + 20u) = (uint32_t)(int32_t)(
                (float)u1 - ((float)inner - -2000.0f) *
                                ((float)(u1 - u0) / fade));
        } else {
            int32_t inner = (int32_t)(centre + ((float)x0 - centre) * scale);
            TS2_MEM32(g_esp + 4u) = (uint32_t)inner;
            TS2_MEM32(g_esp + 12u) = (uint32_t)(int32_t)2000;
            TS2_MEM32(g_esp + 28u) = (uint32_t)(int32_t)(
                (float)u0 + (2000.0f - (float)inner) *
                                ((float)(u1 - u0) / fade));
        }
    }
    ts2_ui_enter();
    sub_001B75A0_gen();
    ts2_ui_leave();
}
extern void sub_001B7450_gen(void);   /* PAL 0x001B7860, -0x410 */
void sub_001B7450(void)
{
    ts2_ui_enter();
    if (ts2_sniper_places_quad()) {
        /* The alpha clear, crosshair and meter go through this inclusive
         * integer rectangle clipper. Give it the bounding pixels in the
         * display coordinate system, preserving the exact edges for its
         * float writer. The guest still sorts/clips Y and rejects empty
         * draws, including rectangles wholly outside the player viewport. */
        uint32_t args = g_esp + 4u;
        int32_t x0 = (int32_t)TS2_MEM32(args), x1 = (int32_t)TS2_MEM32(args + 8u);
        Ts2SniperSpan span = { ts2_sniper_x((float)(x0 < x1 ? x0 : x1)),
                               ts2_sniper_x((float)(x0 < x1 ? x1 : x0) + 1.0f) };
        const Ts2SniperSpan *saved = g_ts2_sniper_span;
        TS2_MEM32(args) = (uint32_t)(int32_t)floorf(span.left);
        TS2_MEM32(args + 8u) = (uint32_t)(int32_t)(ceilf(span.right) - 1.0f);
        g_ts2_sniper_span = &span;
        sub_001B7450_gen();
        g_ts2_sniper_span = saved;
        TS2_MEM32(args) = (uint32_t)x0;
        TS2_MEM32(args + 8u) = (uint32_t)x1;
    } else {
        sub_001B7450_gen();
    }
    ts2_ui_leave();
}
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
void sub_001AB380(void)
{
    ts2_ui_enter();
    /* The glyph helper culls X against 640 before emitting a textured quad. */
    if (ts2_sniper_places_quad())
        ts2_sniper_float_quad(sub_001AB380_gen);
    else
        sub_001AB380_gen();
    ts2_ui_leave();
}
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
/* The sniper scope draws its cartridge strip and ammo number through the
 * same sites as the ordinary HUD, but beside the reticle either group can
 * cross the automatic side-anchor boundary independently. Once the scope
 * renderer has drawn, keep both groups in the centred layout with it. */
static int ts2_ui_scope_marker(uint32_t site)
{
    return site == 0x001C7EFFu || site == 0x000CA58Eu;
}

static int ts2_ui_scope_place(uint32_t site)
{
    /* The sniper's moving primitives have their own pre-clip placement.
     * This includes partial ammo rows reached while a shot is animating. */
    if (g_ts2_sniper.scale)
        return TS2_UI_STRETCH;
    if (g_ts2_scope_active &&
        (site == 0x000BE5CFu || site == 0x000BE5FCu ||
         site == 0x000BEDE7u))
        return TS2_UI_CENTRE;
    return -1;
}

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
    /* Zoom optics: screen shade gradients with prepositioned lens edges,
     * and the two viewport-sized tint passes. */
    { 0x000C2F37, TS2_UI_STRETCH }, { 0x000C2F62, TS2_UI_STRETCH },
    { 0x000C2F88, TS2_UI_STRETCH }, { 0x000C2FAF, TS2_UI_STRETCH },
    { 0x000C2FD6, TS2_UI_STRETCH }, { 0x000C2FFD, TS2_UI_STRETCH },
    { 0x000C3025, TS2_UI_STRETCH }, { 0x000C3050, TS2_UI_STRETCH },
    { 0x000C3AFA, TS2_UI_STRETCH }, { 0x000C3B25, TS2_UI_STRETCH },
    { 0x000C3B4B, TS2_UI_STRETCH }, { 0x000C3B72, TS2_UI_STRETCH },
    { 0x000C3B99, TS2_UI_STRETCH }, { 0x000C3BC0, TS2_UI_STRETCH },
    { 0x000C3BE8, TS2_UI_STRETCH }, { 0x000C3C13, TS2_UI_STRETCH },
    { 0x000C31F3, TS2_UI_STRETCH }, { 0x000C3D32, TS2_UI_STRETCH },
    /* Lens corners, centre markings and the alpha rectangle inside the lens. */
    { 0x000C2F03, TS2_UI_CENTRE },
    { 0x000C3096, TS2_UI_CENTRE }, { 0x000C30BF, TS2_UI_CENTRE },
    { 0x000C30E8, TS2_UI_CENTRE }, { 0x000C312B, TS2_UI_CENTRE },
    { 0x000C3147, TS2_UI_CENTRE }, { 0x000C3166, TS2_UI_CENTRE },
    { 0x000C3182, TS2_UI_CENTRE },
    { 0x000C32D1, TS2_UI_CENTRE }, { 0x000C32EA, TS2_UI_CENTRE },
    { 0x000C3306, TS2_UI_CENTRE }, { 0x000C331F, TS2_UI_CENTRE },
    { 0x000C34B2, TS2_UI_CENTRE }, { 0x000C34D2, TS2_UI_CENTRE },
    { 0x000C34E7, TS2_UI_CENTRE }, { 0x000C3503, TS2_UI_CENTRE },
    { 0x000C3520, TS2_UI_CENTRE }, { 0x000C353B, TS2_UI_CENTRE },
    { 0x000C354E, TS2_UI_CENTRE }, { 0x000C360C, TS2_UI_CENTRE },
    { 0x000C3C4F, TS2_UI_CENTRE }, { 0x000C3C78, TS2_UI_CENTRE },
    { 0x000C3C9E, TS2_UI_CENTRE }, { 0x000C3CC4, TS2_UI_CENTRE },
    { 0x000C3D66, TS2_UI_CENTRE }, { 0x000C3D77, TS2_UI_CENTRE },
    { 0x000C3D8D, TS2_UI_CENTRE }, { 0x000C3D9F, TS2_UI_CENTRE },
    { 0x000C3DF2, TS2_UI_CENTRE }, { 0x000C3E0A, TS2_UI_CENTRE },
    { 0x000C3E1C, TS2_UI_CENTRE }, { 0x000C3E37, TS2_UI_CENTRE },
    { 0x000C3E49, TS2_UI_CENTRE },
    /* Vintage rifle: its scope is a separate renderer drawn as four edge
     * strips, four lens quadrants and a centre cross. The edge strips fill
     * the viewport around the lens; the quadrants and cross stay centred. */
    { 0x000C2B06, TS2_UI_STRETCH }, { 0x000C2B22, TS2_UI_STRETCH },
    { 0x000C2B3B, TS2_UI_STRETCH }, { 0x000C2B5A, TS2_UI_STRETCH },
    { 0x000C2B81, TS2_UI_STRETCH }, { 0x000C2B9E, TS2_UI_STRETCH },
    { 0x000C2BC4, TS2_UI_STRETCH }, { 0x000C2BE1, TS2_UI_STRETCH },
    { 0x000C2C7C, TS2_UI_CENTRE }, { 0x000C2C9D, TS2_UI_STRETCH },
    /* Sniper scope: the in-lens text (ammo count, range) and its small icon
     * were left at 4:3 positions, so they drifted off the centred lens. */
    { 0x001C7EFF, TS2_UI_CENTRE }, { 0x000C37BA, TS2_UI_CENTRE },
    { 0x0014C723, TS2_UI_CENTRE }, { 0x001B0A52, TS2_UI_CENTRE },
    /* Sniper scope: the full-screen shade quad that dims the view outside
     * the lens was unplaced, so the widescreen sides stayed undimmed. */
    { 0x000CA58E, TS2_UI_STRETCH },
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

/* Extra characters from mods: the roster and its screens have not been
 * found in this release yet, so a mod's characters.ini is reported and left
 * alone (roster 0). PAL's are in config/pal/overrides.inc. */
const Ts2Roster k_ts2_roster = { 0 };

/* Loose mod files inside the paks: the pak table and its readers have not
 * been found in this release yet (table 0), so files/ and paks/ in a mod are
 * not served; whole data/*.pak files in a mod still are (the toolkit's
 * RECOMP_MODS). PAL's are in config/pal/overrides.inc. */
const Ts2Paks k_ts2_paks = { 0 };
