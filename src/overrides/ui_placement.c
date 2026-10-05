/*
 * ui_placement.c -- TimeSplitters 2: where each piece of 2D goes in widescreen.
 *
 * Moved unchanged from recomp_manual.c; the table of call sites is now its
 * own file, ui_placement_table.c.
 */
#include "ts2/ts2_guest.h"
#include "ts2/ts2_ui.h"
#include "ts2/ts2_types.h"

/* ── TimeSplitters 2: where each piece of 2D goes in widescreen ── */

/*
 * TimeSplitters 2 has no 16:9 mode. Its 2D -- menus, HUD, text, backdrops --
 * is positioned on the CPU in 640x480 pixels, and in widescreen the renderer
 * squeezes it back to 4:3 so the 16:9 stretch leaves it in proportion. Which
 * pieces should instead span the picture (a backdrop, a fade) or sit at an
 * edge (a HUD corner) the renderer can only guess from the vertices, and the
 * guess changes as things animate: the menu header juddered between the two.
 *
 * The code that drew a piece says what it is, the same way every frame. All
 * of the game's 2D reaches the GPU through one call, sub_001C9265(primitive,
 * format, ?, count), which reserves vertices in the engine's batch for the
 * caller to fill; sub_001C9CDF flushes the batch to DrawVertices. So:
 *
 *   - the reservation is wrapped, and reads its caller from the guest stack
 *     (a lifted call pushes the real return address first);
 *   - the engine's shared drawing functions above it are wrapped too, so a
 *     piece drawn through one is credited to the UI code that called it --
 *     the *site* is the caller of the outermost wrapped function;
 *   - k_ts2_ui_places below says where each known site goes; unknown ones
 *     are left to the renderer (AUTO), exactly as before;
 *   - a reservation whose placement differs from the batch's flushes the
 *     batch first; the renderer is given the batch's placement as soon as
 *     anything is queued (the engine draws the batch by more than one way),
 *     and sub_001C9CDF resets it once the batch is drawn, so a draw that
 *     never went through the batch (the glow passes, a movie) does not
 *     inherit a menu's placement.
 *
 * All wrapping, not replacing (manual_scan.py: extern ..._gen), so the lifted
 * bodies still do the work. Without widescreen nothing here changes a draw.
 *
 *   RECOMP_TS2_UI_SITES=1       flush at every site change and tag each batch
 *                               with its site, and print each site's chain
 *                               the first time it draws; with the renderer's
 *                               RECOMP_D3D8_2D_TAGS=1 that gives each site's
 *                               extent. How the table is built.
 *   RECOMP_TS2_UI_PLACE=<list>  site=placement pairs, comma separated, over
 *                               the table: 0008A0C1=stretch,000AB123=left
 *   RECOMP_TS2_UI_DEFAULT=<p>   placement for sites not in the table (auto)
 */


/* xboxrecomp src/hle/hle_d3d8_record.h: xbox_D3D8SetTwoDPlacement, recorded in
 * frame captures so a capture replays with these placements. Same values
 * as XBOX_D3D8_2D_*. */
extern void host_SetTwoDPlacement(int placement, uint32_t tag);


static Ts2UiPlace g_ts2_ui_extra[64];   /* RECOMP_TS2_UI_PLACE */
static int        g_ts2_ui_extra_count;
static int        g_ts2_ui_default = TS2_UI_AUTO;
static int        g_ts2_ui_mode = -1;   /* 0 off, 1 placing, 2 placing and tagging sites */

/* The batch: what is queued in it came from this site, with this placement. */
static int      g_ts2_batch_place = TS2_UI_AUTO;
static uint32_t g_ts2_batch_site;

/* The placement the renderer has now, so it is only told of changes (each
 * one is a chunk in a frame capture). */
static int      g_ts2_host_place = -1;
static uint32_t g_ts2_host_tag;
/* Set while a reservation flushes ahead of itself: the flush must not reset
 * the renderer's placement then (sub_001C9265). */
static int      g_ts2_keep_host;

static void ts2_ui_host_place(int place, uint32_t tag)
{
    if (place == g_ts2_host_place && tag == g_ts2_host_tag)
        return;
    g_ts2_host_place = place;
    g_ts2_host_tag = tag;
    host_SetTwoDPlacement(place, tag);
}

/* The callers of the wrapped drawing functions now running, outermost first. */
static RECOMP_MANUAL_TLS uint32_t g_ts2_chain[8];
static RECOMP_MANUAL_TLS int      g_ts2_depth;


static int ts2_ui_parse_place(const char *s)
{
    if (!strncmp(s, "stretch", 7)) return TS2_UI_STRETCH;
    if (!strncmp(s, "centre", 6) || !strncmp(s, "center", 6)) return TS2_UI_CENTRE;
    if (!strncmp(s, "left", 4)) return TS2_UI_LEFT;
    if (!strncmp(s, "right", 5)) return TS2_UI_RIGHT;
    if (!strncmp(s, "side", 4)) return TS2_UI_SIDE;
    return TS2_UI_AUTO;
}

static int ts2_ui_mode(void)
{
    const char *v;

    if (g_ts2_ui_mode >= 0)
        return g_ts2_ui_mode;
    g_ts2_ui_mode = recomp_config_bool("RECOMP_WIDESCREEN", "widescreen", 0) ? 1 : 0;
    v = getenv("RECOMP_TS2_UI_SITES");
    if (v && *v && strcmp(v, "0") != 0)
        g_ts2_ui_mode = 2;
    v = getenv("RECOMP_TS2_UI_DEFAULT");
    if (v && *v)
        g_ts2_ui_default = ts2_ui_parse_place(v);
    v = getenv("RECOMP_TS2_UI_PLACE");
    while (v && *v && g_ts2_ui_extra_count < (int)(sizeof g_ts2_ui_extra / sizeof g_ts2_ui_extra[0])) {
        char *end = NULL;
        unsigned long site = strtoul(v, &end, 16);

        if (!end || *end != '=')
            break;
        g_ts2_ui_extra[g_ts2_ui_extra_count].site = (uint32_t)site;
        g_ts2_ui_extra[g_ts2_ui_extra_count].placement = ts2_ui_parse_place(end + 1);
        g_ts2_ui_extra_count++;
        v = strchr(end, ',');
        if (v)
            v++;
    }
    if (g_ts2_ui_mode)
        fprintf(stderr, "[TS2-UI] 2D placement by call site: %d table entries, %d from "
                "RECOMP_TS2_UI_PLACE%s\n",
                k_ts2_ui_place_count,
                g_ts2_ui_extra_count, g_ts2_ui_mode == 2 ? "; tagging sites" : "");
    return g_ts2_ui_mode;
}

static int ts2_ui_place_for(uint32_t site)
{
    int i;

    for (i = 0; i < g_ts2_ui_extra_count; i++)
        if (g_ts2_ui_extra[i].site == site)
            return g_ts2_ui_extra[i].placement;
    for (i = 0; k_ts2_ui_places[i].site; i++)
        if (k_ts2_ui_places[i].site == site)
            return k_ts2_ui_places[i].placement;
    return g_ts2_ui_default;
}

/* Tagging mode: say once which chain a new site came through. */
static void ts2_ui_note_site(uint32_t site, uint32_t leaf)
{
    static uint32_t seen[512];
    static int seen_count;
    int i;

    for (i = 0; i < seen_count; i++)
        if (seen[i] == site)
            return;
    if (seen_count < (int)(sizeof seen / sizeof seen[0]))
        seen[seen_count++] = site;
    RECOMP_DIAG_LOCK();
    fprintf(stderr, "[TS2-UI] site %08X:", site);
    for (i = 0; i < g_ts2_depth && i < 8; i++)
        fprintf(stderr, " %08X ->", g_ts2_chain[i]);
    fprintf(stderr, " %08X -> reserve\n", leaf);
    RECOMP_DIAG_UNLOCK();
    fflush(stderr);
}

/* Run the batch flush from here. A lifted function returns with `ret`, so
 * it needs a return address on the guest stack to pop. */
extern void sub_001C9CDF(void);
static void ts2_ui_flush(void)
{
    g_esp -= 4;
    TS2_MEM32(g_esp) = 0;
    sub_001C9CDF();
}

extern void sub_001C9265_gen(void);
void sub_001C9265(void)
{
    if (ts2_ui_mode()) {
        uint32_t leaf = ts2_args(Ts2Reserve2DArgs)->return_address;
        uint32_t site = g_ts2_depth ? g_ts2_chain[0] : leaf;
        int place = ts2_ui_place_for(site);

        int change = place != g_ts2_batch_place || place == TS2_UI_SIDE ||
                     (g_ts2_ui_mode == 2 && site != g_ts2_batch_site);

        if (g_ts2_ui_mode == 2)
            ts2_ui_note_site(site, leaf);
        if (change) {
            /* The queue holds another site's pieces: draw them under their
             * own placement before this one's join it. A SIDE site's pieces
             * are drawn one by one, since the renderer pins each draw to the
             * edge it is nearer and one draw holding both hands' ammo would
             * be pinned to neither. The renderer keeps the old placement
             * through the reservation below (see there). */
            g_ts2_keep_host = 1;
            ts2_ui_flush();
            g_ts2_keep_host = 0;
        }
        /* The engine keeps more than one batch (by format, it seems), and
         * sub_001C9CDF does not always draw the one that holds the last
         * pieces: the reservation itself draws it, when the next piece does
         * not fit it, by its own way (sub_001C967C calls the draw). So the
         * renderer holds the old batch's placement until that has happened,
         * and takes the new one after, for the pieces now queued -- whose
         * batch may be drawn by either way. Setting the new one first put
         * the right hand's ammo bars, the last piece before the next site,
         * under that site's placement and left them in the 4:3 layout. */
        sub_001C9265_gen();
        if (change) {
            g_ts2_batch_place = place;
            g_ts2_batch_site = site;
        }
        ts2_ui_host_place(g_ts2_batch_place,
                          g_ts2_ui_mode == 2 ? g_ts2_batch_site : 0);
        return;
    }
    sub_001C9265_gen();
}

extern void sub_001C9CDF_gen(void);
void sub_001C9CDF(void)
{
    if (g_ts2_ui_mode <= 0) {
        sub_001C9CDF_gen();
        return;
    }
    ts2_ui_host_place(g_ts2_batch_place, g_ts2_ui_mode == 2 ? g_ts2_batch_site : 0);
    sub_001C9CDF_gen();
    /* The batch is empty again: a draw that never went through it (a glow
     * pass, a movie) must not inherit its placement -- unless a reservation
     * is flushing ahead of itself, when another batch may still be drawn
     * under this placement (sub_001C9265). */
    if (!g_ts2_keep_host)
        ts2_ui_host_place(TS2_UI_AUTO, 0);
}

/* The engine's shared drawing functions: the helpers that reserve vertices
 * for many callers (quads, sprites, text), and the ones above them that the
 * menu and HUD code call. Whoever called the outermost of them is the site. */
static void ts2_ui_enter(void)
{
    if (g_ts2_ui_mode > 0) {
        if (g_ts2_depth < 8)
            g_ts2_chain[g_ts2_depth] = TS2_MEM32(g_esp);
        g_ts2_depth++;
    }
}

static void ts2_ui_leave(void)
{
    if (g_ts2_ui_mode > 0 && g_ts2_depth > 0)
        g_ts2_depth--;
}

extern void sub_001B6290_gen(void);
void sub_001B6290(void) { ts2_ui_enter(); sub_001B6290_gen(); ts2_ui_leave(); }
extern void sub_001B6620_gen(void);
void sub_001B6620(void) { ts2_ui_enter(); sub_001B6620_gen(); ts2_ui_leave(); }
extern void sub_001C1328_gen(void);
void sub_001C1328(void) { ts2_ui_enter(); sub_001C1328_gen(); ts2_ui_leave(); }
extern void sub_001B5E80_gen(void);
void sub_001B5E80(void) { ts2_ui_enter(); sub_001B5E80_gen(); ts2_ui_leave(); }
extern void sub_001B58E0_gen(void);
void sub_001B58E0(void) { ts2_ui_enter(); sub_001B58E0_gen(); ts2_ui_leave(); }
extern void sub_001B6A20_gen(void);
void sub_001B6A20(void) { ts2_ui_enter(); sub_001B6A20_gen(); ts2_ui_leave(); }
extern void sub_001B7A00_gen(void);
void sub_001B7A00(void) { ts2_ui_enter(); sub_001B7A00_gen(); ts2_ui_leave(); }
extern void sub_001B56D0_gen(void);
void sub_001B56D0(void) { ts2_ui_enter(); sub_001B56D0_gen(); ts2_ui_leave(); }
extern void sub_00058360_gen(void);
void sub_00058360(void) { ts2_ui_enter(); sub_00058360_gen(); ts2_ui_leave(); }
extern void sub_001B5DA0_gen(void);
void sub_001B5DA0(void) { ts2_ui_enter(); sub_001B5DA0_gen(); ts2_ui_leave(); }
extern void sub_001B3ED0_gen(void);
void sub_001B3ED0(void) { ts2_ui_enter(); sub_001B3ED0_gen(); ts2_ui_leave(); }
extern void sub_000C4F80_gen(void);
void sub_000C4F80(void) { ts2_ui_enter(); sub_000C4F80_gen(); ts2_ui_leave(); }
extern void sub_001B79B0_gen(void);
void sub_001B79B0(void) { ts2_ui_enter(); sub_001B79B0_gen(); ts2_ui_leave(); }
extern void sub_001B7860_gen(void);
void sub_001B7860(void) { ts2_ui_enter(); sub_001B7860_gen(); ts2_ui_leave(); }
extern void sub_001B7950_gen(void);
void sub_001B7950(void) { ts2_ui_enter(); sub_001B7950_gen(); ts2_ui_leave(); }
extern void sub_000AA5F0_gen(void);
void sub_000AA5F0(void) { ts2_ui_enter(); sub_000AA5F0_gen(); ts2_ui_leave(); }
extern void sub_000AABF0_gen(void);
void sub_000AABF0(void) { ts2_ui_enter(); sub_000AABF0_gen(); ts2_ui_leave(); }
extern void sub_000AA670_gen(void);
void sub_000AA670(void) { ts2_ui_enter(); sub_000AA670_gen(); ts2_ui_leave(); }
extern void sub_00138FE0_gen(void);
void sub_00138FE0(void) { ts2_ui_enter(); sub_00138FE0_gen(); ts2_ui_leave(); }
extern void sub_001AB7C0_gen(void);
void sub_001AB7C0(void) { ts2_ui_enter(); sub_001AB7C0_gen(); ts2_ui_leave(); }
extern void sub_001AC790_gen(void);
void sub_001AC790(void) { ts2_ui_enter(); sub_001AC790_gen(); ts2_ui_leave(); }
extern void sub_001ACD50_gen(void);
void sub_001ACD50(void) { ts2_ui_enter(); sub_001ACD50_gen(); ts2_ui_leave(); }
extern void sub_001ACDD0_gen(void);
void sub_001ACDD0(void) { ts2_ui_enter(); sub_001ACDD0_gen(); ts2_ui_leave(); }
extern void sub_001ACE30_gen(void);
void sub_001ACE30(void) { ts2_ui_enter(); sub_001ACE30_gen(); ts2_ui_leave(); }
extern void sub_001ACE90_gen(void);
void sub_001ACE90(void) { ts2_ui_enter(); sub_001ACE90_gen(); ts2_ui_leave(); }
extern void sub_001AD150_gen(void);
void sub_001AD150(void) { ts2_ui_enter(); sub_001AD150_gen(); ts2_ui_leave(); }
extern void sub_001AD1D0_gen(void);
void sub_001AD1D0(void) { ts2_ui_enter(); sub_001AD1D0_gen(); ts2_ui_leave(); }
extern void sub_001B7520_gen(void);
void sub_001B7520(void) { ts2_ui_enter(); sub_001B7520_gen(); ts2_ui_leave(); }
