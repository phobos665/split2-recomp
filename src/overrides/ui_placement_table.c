/*
 * ui_placement_table.c -- TimeSplitters 2: where each piece of 2D goes in
 * widescreen, by the call site that drew it. Data only; the logic that reads
 * it is ui_placement.c, and RECOMP_TS2_UI_PLACE overrides any entry without
 * a rebuild.
 */
#include "ts2/ts2_ui.h"

/* Where TimeSplitters 2 (PAL, this XBE) draws what. Sites are return
 * addresses in the game's UI code. Ends at site 0.
 *
 * Built from the front end, screen by screen: frames captured with
 * RECOMP_TS2_UI_SITES=1, each site drawn alone and each left out with
 * d3d8_replay --each-tag / --each-tag-hidden, and the table tried on the
 * captures with --place before it went in here. The rule: whatever covers
 * the screen spans the picture, the side decorations and the header's
 * left and right ends go to the edges of it, and everything a player
 * reads stays in proportion in the middle. A full-screen pass left to the
 * renderer's width guess was sometimes kept at 4:3, and its edge showed
 * as a seam down both old borders on every screen. */
const Ts2UiPlace k_ts2_ui_places[] = {
    /* Full-screen quads, fades and post passes (the glow over the frame). */
    { 0x000224CA, TS2_UI_STRETCH }, { 0x000224F3, TS2_UI_STRETCH },
    { 0x00022520, TS2_UI_STRETCH }, { 0x00022548, TS2_UI_STRETCH },
    { 0x00022635, TS2_UI_STRETCH }, { 0x00022650, TS2_UI_STRETCH },
    { 0x0002266B, TS2_UI_STRETCH }, { 0x0002268A, TS2_UI_STRETCH },
    { 0x000CA02A, TS2_UI_STRETCH }, { 0x000CA2C1, TS2_UI_STRETCH },
    { 0x000CA52A, TS2_UI_STRETCH },
    /* Backdrop: the tunnel ring, the title screen's nebula, the footer. */
    { 0x000887E3, TS2_UI_STRETCH }, { 0x000B85C9, TS2_UI_STRETCH },
    { 0x0008990F, TS2_UI_STRETCH },
    /* Header banner and the rules under and below it. */
    { 0x00089714, TS2_UI_STRETCH }, { 0x000897AE, TS2_UI_STRETCH },
    { 0x0008985F, TS2_UI_STRETCH }, { 0x0008988A, TS2_UI_STRETCH },
    { 0x000898B2, TS2_UI_STRETCH }, { 0x00089937, TS2_UI_STRETCH },
    /* Left edge: the scrolling binary, the logo and the screen's name
     * beneath it, the button hints. */
    { 0x000885C5, TS2_UI_LEFT }, { 0x0008861D, TS2_UI_LEFT },
    { 0x00089836, TS2_UI_LEFT }, { 0x000899C5, TS2_UI_LEFT },
    { 0x000F0415, TS2_UI_LEFT },
    /* Right edge: the purple glow. */
    { 0x000889D2, TS2_UI_RIGHT },
    /* Kept in proportion: panels, their glow and selection bar, menu
     * items, the title logo, the level name, the loading picture. The glow
     * (000EF824) is the panel's shadow as well as its rays, so it stays
     * with the panel; on the story screens, where the panel is at the
     * right, its rays end at the old edge. */
    { 0x000EF824, TS2_UI_CENTRE }, { 0x000EF43A, TS2_UI_CENTRE },
    { 0x000EEF97, TS2_UI_CENTRE }, { 0x000F0106, TS2_UI_CENTRE },
    { 0x000EE789, TS2_UI_CENTRE }, { 0x000EE804, TS2_UI_CENTRE },
    { 0x000EE7E8, TS2_UI_CENTRE }, { 0x000EE7C8, TS2_UI_CENTRE },
    { 0x000EE7A4, TS2_UI_CENTRE }, { 0x000EEA4D, TS2_UI_CENTRE },
    { 0x000F198A, TS2_UI_CENTRE }, { 0x000F1A16, TS2_UI_CENTRE },
    { 0x00088FD3, TS2_UI_CENTRE }, { 0x000890BB, TS2_UI_CENTRE },
    { 0x000EFE57, TS2_UI_CENTRE }, { 0x00089D55, TS2_UI_CENTRE },
    { 0x001A213B, TS2_UI_CENTRE }, { 0x00089606, TS2_UI_CENTRE },

    /* Arcade screens: the hex backdrop, the level list's pictures, the
     * character select (portraits, name, stats, the picture of the one
     * chosen), the panel's corners and scroll arrow, and the row of
     * player figures at the bottom right, opposite the button hints. */
    { 0x000A5085, TS2_UI_STRETCH },
    { 0x0008A402, TS2_UI_CENTRE }, { 0x0008F837, TS2_UI_CENTRE },
    { 0x0008F9B5, TS2_UI_CENTRE }, { 0x0008FA26, TS2_UI_CENTRE },
    { 0x0008FC23, TS2_UI_CENTRE }, { 0x001B747A, TS2_UI_CENTRE },
    { 0x001B74C3, TS2_UI_CENTRE }, { 0x001B74FF, TS2_UI_CENTRE },
    { 0x000EE82A, TS2_UI_CENTRE }, { 0x000EE846, TS2_UI_CENTRE },
    { 0x000F065F, TS2_UI_CENTRE },
    { 0x0008E98D, TS2_UI_RIGHT },

    /* In-game HUD, from an Arcade match: the rank badge in the top left
     * corner, the radar in the top right, each hand's ammo at its own
     * bottom corner (one piece of code draws both, hence SIDE), the kill
     * message and the crosshair in the middle. The health and armour arcs
     * are one ellipse framing the view, so it spans the picture. */
    { 0x000BCF3E, TS2_UI_LEFT },   { 0x000BCFAE, TS2_UI_LEFT },
    { 0x000BD129, TS2_UI_LEFT },
    { 0x000BFDBE, TS2_UI_RIGHT },  { 0x000BFFD4, TS2_UI_RIGHT },
    { 0x000C0033, TS2_UI_RIGHT },  { 0x000C0274, TS2_UI_RIGHT },
    { 0x000C0324, TS2_UI_RIGHT },  { 0x000C043F, TS2_UI_RIGHT },
    { 0x000BE66C, TS2_UI_SIDE },   { 0x000BEE57, TS2_UI_SIDE },
    /* The dark backing drawn under each ammo number, from its own call
     * site: left to the width guess it stayed in the 4:3 layout, beside
     * the bars, while the number went to the corner. */
    { 0x000BE63F, TS2_UI_SIDE },
    { 0x000BC31C, TS2_UI_CENTRE }, { 0x00058670, TS2_UI_CENTRE },
    { 0x000C933F, TS2_UI_STRETCH },
    /* Sprites the game places in the world and projects to the screen
     * itself (the brazier's flame, muzzle flashes): they were projected
     * through the widened camera, so they are already where the 3D is and
     * squeezing them would pull them off it. */
    { 0x001C021F, TS2_UI_STRETCH }, { 0x001BEBBE, TS2_UI_STRETCH },
    { 0x001BEBF4, TS2_UI_STRETCH }, { 0x001BED57, TS2_UI_STRETCH },
    /* The handheld's map. It is drawn at the start of the frame into a
     * corner of the back buffer (x 128 on, scissored to 128..309 by
     * 0..181), copied out of it with CopyRects into the 128x128 texture the
     * handheld's screen shows, and the screen is then cleared for the
     * level. Whatever is drawn there has to stay at its own pixels, or
     * widescreen's squeeze moves it out of the corner that is copied. */
    { 0x000E6576, TS2_UI_STRETCH }, { 0x000E507E, TS2_UI_STRETCH },
    { 0x000E5517, TS2_UI_STRETCH }, { 0x000E55E5, TS2_UI_STRETCH },
    { 0x000E4888, TS2_UI_STRETCH }, { 0x000E4911, TS2_UI_STRETCH },
    { 0x000E57F5, TS2_UI_STRETCH }, { 0x000E681C, TS2_UI_STRETCH },
    /* Pause menu (in-game Start): the ring of health and armour arcs
     * (sub_000D1E30, every page, through the same arc helper as the HUD's
     * 000C933F) and the dark cap across its top. Left to the width guess,
     * a piece of the ring the engine's batch cut off at less than 75% of
     * the width -- the cut point moves frame to frame as the batch fills --
     * was squeezed for that frame, and the arc flickered inward. */
    { 0x000D1EEF, TS2_UI_STRETCH },
    { 0x000CDAF0, TS2_UI_STRETCH }, { 0x000CDB16, TS2_UI_STRETCH },
    /* Its backing: the dim, letterbox bars and rules, the blue backdrop.
     * Always full width, so the guess got them right; set so they stay
     * right under RECOMP_WIDESCREEN_2D=centre too. */
    { 0x000CCB7F, TS2_UI_STRETCH }, { 0x000CCBA3, TS2_UI_STRETCH },
    { 0x000CCBC7, TS2_UI_STRETCH }, { 0x000CCBF5, TS2_UI_STRETCH },
    { 0x000CCC20, TS2_UI_STRETCH }, { 0x000CCAEE, TS2_UI_STRETCH },
    { 0, TS2_UI_AUTO }
};

const int k_ts2_ui_place_count =
    (int)(sizeof k_ts2_ui_places / sizeof k_ts2_ui_places[0]) - 1;
