/*
 * give_all.c -- TimeSplitters 2: every weapon at once, for testing weapon mods.
 *
 * F8 in a level, or both thumbsticks clicked together on the first pad,
 * gives the player every named weapon with ammunition, so a modded gun can
 * be checked by cycling to it anywhere. The pad is read straight from
 * XInput, so the combination works whatever the input bindings say.
 * RECOMP_TS2_GIVE_ALL_AFTER=<frames> does the same once, that many frames
 * into the run, for scripted runs.
 *
 * What it writes (found 6 Oct 2026 by snapshots either side of the Siberia
 * sniper pickup): the player record's +0x998 + definition * 4 is 1 for a
 * weapon held (the pickup set the sniper rifle's, definition 6, from 0 to
 * 1), and its reserve ammunition is +0xA2C + type * 4 (the sniper's type 4
 * went from 0 to 5). Definitions 18 and 27-33 have no name and are left out;
 * so are the Digital Camera and the Temporal Uplink (34, 35).
 *
 * A level only loads the models of the weapons placed in it, so a weapon
 * given in a level that never had it may draw nothing.
 */
#include "ts2/ts2_guest.h"
#include "ts2/ts2_types.h"
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

/* XInputGetState, loaded on first use: no link-time dependency here. */
typedef struct { DWORD packet; WORD buttons; BYTE lt, rt; SHORT lx, ly, rx, ry; } pad_state;
typedef DWORD (WINAPI *xinput_get_state)(DWORD, pad_state *);
#define PAD_LEFT_THUMB  0x0040
#define PAD_RIGHT_THUMB 0x0080

static int sticks_clicked(void)
{
    static xinput_get_state get;
    static int tried;
    pad_state st;

    if (!tried) {
        HMODULE m;
        tried = 1;
        m = LoadLibraryA("xinput1_4.dll");
        if (!m)
            m = LoadLibraryA("xinput9_1_0.dll");
        if (m)
            get = (xinput_get_state)(void (*)(void))GetProcAddress(m, "XInputGetState");
    }
    static int wait;
    if (!get || wait > 0) {
        wait -= wait > 0;
        return 0;
    }
    /* Asking for a pad that is not there can stall: after a miss, wait
     * about two seconds before asking again. */
    if (get(0, &st) != 0) {
        wait = 120;
        return 0;
    }
    return (st.buttons & (PAD_LEFT_THUMB | PAD_RIGHT_THUMB)) == (PAD_LEFT_THUMB | PAD_RIGHT_THUMB);
}
#endif

#define TS2_PLAYER_HELD   0x998   /* int32[definition]: 1 = held */
#define GIVE_AMMO         99

static void give_all(void)
{
    uint32_t p = TS2_MEM32(TS2_PLAYER_PTR);
    int d, given = 0;

    if (p < 0x80000000u)
        return;                         /* no player: not in a level */
    for (d = 0; d < 34; d++) {
        uint32_t def = TS2_WEAPON_TABLE + (uint32_t)d * TS2_WEAPON_SIZE;
        int32_t types[2], k;

        if (d == 18 || (d >= 27 && d <= 33))
            continue;
        TS2_MEM32(p + TS2_PLAYER_HELD + 4u * (uint32_t)d) = 1;
        types[0] = (int32_t)TS2_MEM32(def + TS2_WEAPON_AMMO_TYPE);
        types[1] = (int32_t)TS2_MEM32(def + TS2_WEAPON_AMMO2_TYPE);
        for (k = 0; k < 2; k++) {
            uint32_t at = p + TS2_PLAYER_RESERVE + 4u * (uint32_t)types[k];
            if (types[k] > 0 && types[k] < 30 && (int32_t)TS2_MEM32(at) < GIVE_AMMO)
                TS2_MEM32(at) = GIVE_AMMO;
        }
        given++;
    }
    fprintf(stderr, "[TS2-GIVE] gave every weapon (%d) with %d rounds of each ammunition\n",
            given, GIVE_AMMO);
}

/* Called once a frame (frame_step.c). */
void ts2_give_all_poll(void)
{
    static long frames, after = -1;
    static int down;
    int now = 0;

    if (after < 0) {
        const char *v = getenv("RECOMP_TS2_GIVE_ALL_AFTER");
        after = v ? atol(v) : 0;
    }
    frames++;
    if (after > 0 && frames == after)
        give_all();
#ifdef _WIN32
    now = (GetAsyncKeyState(VK_F8) & 0x8000) != 0 || sticks_clicked();
#endif
    if (now && !down)
        give_all();
    down = now;
}
