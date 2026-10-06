/*
 * frame_step.c -- TimeSplitters 2: an experiment in game logic above 60 Hz.
 *
 * TS2 is a tick engine. sub_001AE3C0 runs once a frame and sets the frame's
 * step: the vblanks since the last frame (from sub_001C85C0), clamped to
 * 1..3, as an integer (0x348CE0, 0x348CE4) and as a float (0x348CE8,
 * 0x348CEC). The game clock (0x4AD3E8) adds the integer step, and every
 * per-tick constant in the game is tuned for a tick of one 60 Hz vblank. So
 * a guest vblank at 120 Hz runs the whole game at double speed (measured,
 * 6 Oct 2026: the 120 Hz intro reached the main menu while the 60 Hz one was
 * still on the logo).
 *
 * RECOMP_TS2_TICK_DIVIDE=<n> (or ts2_tick_divide in the settings file)
 * tries the other way round: with the guest vblank at n * 60 Hz
 * (RECOMP_VBLANK_HZ, RECOMP_FPS_CAP to match), each frame's step is divided
 * by n -- the float step exactly, the integer step through a carry, so the
 * clock still advances one tick per 1/60 s. Off by default; an experiment.
 *
 * What to expect, from reading the code: the float step reaches 314
 * functions and the integer one 204, and the per-object update (the list
 * walked by sub_001543E0) recomputes each object's step from the integer
 * clock. Whatever steps by the float frame step can move every frame;
 * whatever steps by whole ticks still moves at 60 Hz, and gets a step of 0
 * on the frames between.
 */
#include "ts2/ts2_guest.h"
#include "ts2/ts2_types.h"

static int ts2_tick_divide(void)
{
    static int n = -1;

    if (n < 0) {
        const char *v = recomp_config_lookup("RECOMP_TS2_TICK_DIVIDE", "ts2_tick_divide");
        n = v ? atoi(v) : 1;
        if (n < 1 || n > 4)
            n = 1;
        if (n > 1)
            fprintf(stderr, "[TS2-TICK] experiment: each frame's step divided by %d "
                            "(run the guest vblank at %d Hz)\n", n, 60 * n);
    }
    return n;
}

extern void sub_001AE3C0_gen(void);
void ts2_give_all_poll(void);   /* give_all.c */

void sub_001AE3C0(void)
{
    static int32_t carry;
    int n = ts2_tick_divide();
    int32_t step, ticks;
    float fstep;

    sub_001AE3C0_gen();
    ts2_give_all_poll();
    if (n == 1)
        return;
    /* Paused (the game zeroes the float step): leave it alone. */
    if (TS2_MEMF(TS2_FRAME_STEP_F) == 0.0f)
        return;
    step = (int32_t)TS2_MEM32(TS2_FRAME_VBLANKS);   /* vblanks at n*60 Hz, 1..3 */
    carry += step;
    ticks = carry / n;
    carry -= ticks * n;
    fstep = (float)step / (float)n;
    TS2_MEM32(TS2_FRAME_VBLANKS) = (uint32_t)ticks;
    TS2_MEM32(TS2_FRAME_STEP) = (uint32_t)ticks;
    TS2_MEMF(TS2_FRAME_VBLANKS_F) = fstep;
    TS2_MEMF(TS2_FRAME_STEP_F) = fstep;
}
