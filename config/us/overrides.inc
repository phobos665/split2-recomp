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

/* US frame timing (001ADF80) clamps the vblank delta to 1..3 and adds it
 * to the running tick count. It tail-calls 00168BF0 to advance the calendar.
 * Rewrite the step before that call consumes it so rollovers stay correct. */
#define TS2_US_REAL_STEP  0x00348898u
#define TS2_US_GAME_STEP  0x0034889Cu
#define TS2_US_REAL_FLOAT 0x003488A0u
#define TS2_US_GAME_FLOAT 0x003488A4u
#define TS2_US_TICK_TOTAL 0x0040BC54u
#define TS2_US_CLOCK_HELD 0x0040BC58u
#define TS2_US_SEQUENCE   0x00356770u

extern int64_t host_time_ns(void);
extern const char *xbox_Nv2aFlipGateModeName(void);
extern void xbox_Nv2aFlipGateHoldVblank(int on);

static int ts2_us_cap_above_vblank(void)
{
    const char *cap = xbox_Nv2aFlipGateModeName();
    return !strcmp(cap, "off") || atoi(cap) > 60;
}

static int ts2_us_free_step_enabled(void)
{
    static int enabled = -1;

    if (enabled < 0)
        enabled = recomp_config_bool("RECOMP_TS2_FREE_STEP", "ts2_free_step", 1);
    return enabled;
}

static int g_ts2_us_gameplay_frame;
static int g_ts2_us_free_step;
static float g_ts2_us_frame_step;
static float g_ts2_us_previous_frame_step;

/* The MapMaker uses a gameplay camera but is not a 60 Hz simulation. Its
 * editor timing remains tied to protected frame presentation. */
static int ts2_us_mapmaker_mode(void)
{
    return g_ts2_us_gameplay_frame && TS2_MEM32(0x004AD6A4u) == 1u;
}

extern void sub_00168BF0_gen(void);
void sub_00168BF0(void)
{
    static int64_t last;
    static int64_t remainder;
    static int reported;
    int64_t now, elapsed;
    uint32_t ticks;
    float step;

    g_ts2_us_free_step = 0;
    if (!g_ts2_us_gameplay_frame || !ts2_us_cap_above_vblank() ||
        !ts2_us_free_step_enabled() || TS2_MEM32(TS2_US_CLOCK_HELD) ||
        TS2_MEM32(TS2_US_SEQUENCE) || ts2_us_mapmaker_mode()) {
        last = remainder = 0;
        g_ts2_us_frame_step = 0.0f;
        sub_00168BF0_gen();
        return;
    }

    now = host_time_ns();
    elapsed = last ? now - last : 16666667;
    last = now;
    if (elapsed < 0)
        elapsed = 0;
    if (elapsed > 50000000)
        elapsed = 50000000; /* native three-tick catch-up limit */
    remainder += elapsed * 60;
    ticks = (uint32_t)(remainder / 1000000000);
    remainder %= 1000000000;
    step = (float)((double)elapsed * 60.0 / 1000000000.0);
    TS2_MEM32(TS2_US_TICK_TOTAL) += ticks - TS2_MEM32(TS2_US_REAL_STEP);
    TS2_MEM32(TS2_US_REAL_STEP) = ticks;
    TS2_MEM32(TS2_US_GAME_STEP) = ticks;
    TS2_MEMF(TS2_US_REAL_FLOAT) = step;
    TS2_MEMF(TS2_US_GAME_FLOAT) = step;
    g_ts2_us_previous_frame_step = g_ts2_us_frame_step;
    g_ts2_us_frame_step = step;
    g_ts2_us_free_step = 1;
    if (!reported) {
        fprintf(stderr, "[TS2-STEP] experimental elapsed-time updates enabled\n");
        reported = 1;
    }
    sub_00168BF0_gen();
}

/* The two object schedulers temporarily publish whole-tick deltas for
 * their callbacks. Both restore the shared float from the saved integer
 * on exit, losing the elapsed-time delta for the next subsystem. Preserve
 * the caller's float without changing the per-object scheduling cadence. */
static void ts2_us_run_object_scheduler(void (*generated)(void))
{
    int preserve_step = g_ts2_us_free_step;
    uint32_t saved_step = TS2_MEM32(TS2_US_GAME_FLOAT);

    generated();
    if (preserve_step)
        TS2_MEM32(TS2_US_GAME_FLOAT) = saved_step;
}

extern void sub_00153F90_gen(void);
void sub_00153F90(void) { ts2_us_run_object_scheduler(sub_00153F90_gen); }

extern void sub_001542A0_gen(void);
void sub_001542A0(void) { ts2_us_run_object_scheduler(sub_001542A0_gen); }

/* The player keeps its explicit frame delta because the object dispatch
 * can call it while an object-specific whole step is in effect. */
extern void sub_001463D0_gen(void);
void sub_001463D0(void)
{
    if (g_ts2_us_free_step) {
        uint32_t saved = TS2_MEM32(TS2_US_GAME_FLOAT);

        TS2_MEMF(TS2_US_GAME_FLOAT) = g_ts2_us_frame_step;
        sub_001463D0_gen();
        TS2_MEM32(TS2_US_GAME_FLOAT) = saved;
        return;
    }
    sub_001463D0_gen();
}

/* 000B72F0 advances the weapon bob after the player update. Its phase and
 * amplitude both divide the last horizontal displacement (+0x1B8) by the
 * last nonzero whole step (+0x190). Movement now uses fractional time,
 * so feed the bob the equivalent displacement for that whole-step divisor. */
extern void sub_000B72F0_gen(void);
void sub_000B72F0(void)
{
    if (g_ts2_us_free_step && g_ts2_us_previous_frame_step > 0.0f) {
        uint32_t player = TS2_MEM32(0x00497100u);
        int32_t divisor = (int32_t)TS2_MEM32(player + 0x190u);

        if (divisor > 0) {
            uint32_t saved_step = TS2_MEM32(TS2_US_GAME_FLOAT);
            uint32_t saved_distance = TS2_MEM32(player + 0x1B8u);

            TS2_MEMF(TS2_US_GAME_FLOAT) = g_ts2_us_frame_step;
            TS2_MEMF(player + 0x1B8u) *= (float)divisor / g_ts2_us_previous_frame_step;
            sub_000B72F0_gen();
            TS2_MEM32(player + 0x1B8u) = saved_distance;
            TS2_MEM32(TS2_US_GAME_FLOAT) = saved_step;
            return;
        }
    }
    sub_000B72F0_gen();
}

/* 000B3E10 advances the held weapon toward its firing pose. The action
 * record's +0x50 pulse is rebuilt only on whole-tick frames, while +0x4C
 * remains set for as long as the trigger is held. At above-60 FPS that
 * makes the pulse absent from most rendered frames; the minigun spin-up
 * then follows its decay path instead of accumulating elapsed time. Keep
 * the pulse visible to this one animation update while the trigger remains
 * held, without changing the action state seen by any other subsystem.
 *
 * The same pulse also drives the type-5 thermal branch at B4288. Applying
 * it on every render frame overheats the minigun, while removing it entirely
 * lets continuous cooling dominate. Preserve shot heat from B35C0, but after
 * this call replace 000B3E10's heat result with its canonical whole-tick
 * map. Zero-tick renders leave heat unchanged; whole-tick renders use the
 * native cool/warm terms once per logical tick. The 60 Hz path is unchanged. */
static float ts2_us_minigun_shot_heat(float heat, uint32_t mode)
{
    double linear = mode == 0u ? 0.016 : 0.012;
    double scale = mode == 0u ? 0.012 : 0.011;

    heat = (float)((double)heat + linear + scale * (double)heat);
    return heat > 1.0f ? 1.0f : heat;
}

static float ts2_us_minigun_tick_heat(float heat, uint32_t mode,
                                      uint32_t shots, int pulse,
                                      uint32_t ticks)
{
    double d = (double)ticks / 60.0;
    double cooled;

    while (shots--)
        heat = ts2_us_minigun_shot_heat(heat, mode);

    cooled = (double)heat - 0.12 * d;
    cooled -= (1.05 - cooled) * 0.15 * d;
    if (cooled < 0.0)
        cooled = 0.0;

    if (cooled < 0.5) {
        if (mode == 1u)
            cooled += 0.9 * (0.5 - cooled) * d;
        else if (pulse)
            cooled += 0.203 * d;
    }
    if (cooled > 1.0)
        cooled = 1.0;
    return (float)cooled;
}

extern void sub_000B3E10_gen(void);
void sub_000B3E10(void)
{
    uint32_t held = TS2_MEM32(g_esp + 4u);
    uint32_t action = g_esi;
    int minigun = held && TS2_MEM32(held + 0x30u) == 5u && action;
    float heat_value_before = minigun ? TS2_MEMF(held + 0xCCu) : 0.0f;
    uint32_t pulse_before = minigun ? TS2_MEM32(action + 0x50u) : 0;
    uint32_t counter_before = minigun ? TS2_MEM32(action + 0xD0u) : 0;
    uint32_t step = TS2_MEM32(TS2_US_GAME_STEP);
    uint32_t mode = minigun ? TS2_MEM32(action + 0x30u) : ~0u;
    int synthetic = minigun && g_ts2_us_free_step && step == 0u &&
                    TS2_MEM32(action + 0x4Cu) != 0u && pulse_before == 0u;
    int split_heat = minigun && g_ts2_us_free_step &&
                     (mode == 0u || mode == 1u);

    if (synthetic) {
        uint32_t saved = pulse_before;

        TS2_MEM32(action + 0x50u) = 1u;
        sub_000B3E10_gen();
        TS2_MEM32(action + 0x50u) = saved;
    } else {
        sub_000B3E10_gen();
    }

    if (split_heat) {
        uint32_t counter_after = TS2_MEM32(action + 0xD0u);
        uint32_t shots = counter_after >= counter_before ?
                         counter_after - counter_before : 0u;
        int pulse = pulse_before != 0u || TS2_MEM32(action + 0x50u) != 0u;

        /* A shot is a whole-tick event. If its count moved by more than
         * this call's logical span, leave the generated result alone rather
         * than guessing across a weapon-lifetime reset. Zero-tick renders
         * have no thermal opportunity at all. */
        if (shots <= step)
            TS2_MEMF(held + 0xCCu) =
                ts2_us_minigun_tick_heat(heat_value_before, mode,
                                         shots, pulse, step);
    }
}

/* Sample the player position and the bob outputs together so a stepped
 * movement input can be distinguished from a discontinuity in the bob. */
extern void sub_00140E10_gen(void);
void sub_00140E10(void)
{
    static int trace = -1;

    sub_00140E10_gen();
    if (trace < 0)
        trace = recomp_config_bool("RECOMP_TS2_BOB_TRACE", NULL, 0);
    if (trace && g_ts2_us_gameplay_frame && !TS2_MEM32(TS2_US_SEQUENCE)) {
        uint32_t player = TS2_MEM32(0x00497100u);

        fprintf(stderr, "[TS2-BOB] %u %u %.5f %08x pos %.6f %.6f %.6f "
                        "dist %.6f phase %.4f %.4f bob %.6f %.6f\n",
                TS2_MEM32(0x0040BC5Cu), TS2_MEM32(TS2_US_GAME_STEP),
                TS2_MEMF(TS2_US_GAME_FLOAT), player,
                TS2_MEMF(player + 0xF0), TS2_MEMF(player + 0xF4), TS2_MEMF(player + 0xF8),
                TS2_MEMF(player + 0x1B4), TS2_MEMF(player + 0x180), TS2_MEMF(player + 0x184),
                TS2_MEMF(player + 0x188), TS2_MEMF(player + 0x18C));
    }
}

/* 001B9E80 samples the pad and writes newly pressed buttons at +0x28.
 * Keep every newly pressed button until a gameplay tick can consume it.
 * The game maps analogue A/B/X/Y, black, white and both triggers into
 * different bits of the same field; preserving only 0xF0 loses the
 * minigun's secondary-fire edge above 60 FPS. */
extern void sub_001B9E80_gen(void);
void sub_001B9E80(void)
{
    static uint32_t pending[8];
    uint32_t port = TS2_MEM32(g_esp + 4u);
    uint32_t pad = TS2_MEM32(g_esp + 8u);
    uint32_t pressed;

    sub_001B9E80_gen();
    if (port >= sizeof pending / sizeof pending[0])
        return;
    if (!g_ts2_us_free_step || TS2_MEM32(pad + 0x14u) != 0x63u) {
        pending[port] = 0;
        return;
    }
    pressed = TS2_MEM32(pad + 0x28u);
    pending[port] |= pressed;
    if (TS2_MEM32(TS2_US_GAME_STEP) == 0u) {
        TS2_MEM32(pad + 0x28u) = 0;
    } else {
        TS2_MEM32(pad + 0x28u) = pressed | pending[port];
        pending[port] = 0;
    }
}

/* Object type 0x1D6 is damfilecabinet.xbr. Its activation plays sound
 * in 0019B960 and registers 001989C0 to animate the drawer. */
static void ts2_us_cabinet_trace(const char *event, uint32_t object)
{
    static int trace = -1;

    if (trace < 0)
        trace = recomp_config_bool("RECOMP_TS2_CABINET_TRACE", NULL, 0);
    if (trace && TS2_MEM32(object + 8u) == 0x1D6u)
        fprintf(stderr, "[TS2-CABINET] %s %08x tick %u step %u/%.5f "
                        "last %u motion %.5f speed %.5f callback %08x\n",
                event, object, TS2_MEM32(0x004AD6A8u), TS2_MEM32(TS2_US_GAME_STEP),
                TS2_MEMF(TS2_US_GAME_FLOAT), TS2_MEM32(object + 0x18u),
                TS2_MEMF(object + 0x120u), TS2_MEMF(object + 0x1FCu),
                TS2_MEM32(object + 0x134u));
}

extern void sub_0019B960_gen(void);
void sub_0019B960(void)
{
    uint32_t object = TS2_MEM32(g_esp + 4u);

    sub_0019B960_gen();
    ts2_us_cabinet_trace("activate", object);
}

extern void sub_001989C0_gen(void);
void sub_001989C0(void)
{
    uint32_t object = TS2_MEM32(g_esp + 4u);
    int cabinet_between_ticks = g_ts2_us_free_step &&
                                TS2_MEM32(TS2_US_GAME_STEP) == 0u &&
                                TS2_MEM32(object + 8u) == 0x1D6u;

    /* With zero ticks the native callback skips displacement, then sees
     * a closed drawer and unregisters itself before the first real tick. */
    if (cabinet_between_ticks && TS2_MEMF(object + 0x120u) == 0.0f) {
        ts2_us_cabinet_trace("defer", object);
        g_esp += 4u; /* cdecl return address */
        return;
    }
    sub_001989C0_gen();
    /* The native callback still builds the drawer matrix at zero ticks,
     * but only flags it for the object's transform pass on tick frames. */
    if (cabinet_between_ticks)
        TS2_MEM32(object + 0x28u) |= 2u;
    ts2_us_cabinet_trace("animate", object);
}

/* The impact effect at 00025AE7 divides by the integer step without
 * checking it. Keep its event (and return value) on a render-only frame.
 * Other object and emitter callbacks guard their own divisions and depend
 * on seeing zero between simulation ticks. */
extern void sub_00025920_gen(void);
void sub_00025920(void)
{
    if (g_ts2_us_free_step && TS2_MEM32(TS2_US_GAME_STEP) == 0u) {
        TS2_MEM32(TS2_US_GAME_STEP) = 1u;
        sub_00025920_gen();
        TS2_MEM32(TS2_US_GAME_STEP) = 0u;
        return;
    }
    sub_00025920_gen();
}

/* Particle aging (000B7E00), tracer motion (00131DC0), and the missile
 * callbacks dispatched by 00023330 use whole ticks to decide when to
 * integrate. Supply the corresponding float for displacement, lifetime
 * and swept collision. Restore the render-frame delta for the caller. */
static void ts2_us_run_tick_update(void (*update)(void))
{
    if (g_ts2_us_free_step) {
        uint32_t saved_step = TS2_MEM32(TS2_US_GAME_FLOAT);

        TS2_MEMF(TS2_US_GAME_FLOAT) = (float)(int32_t)TS2_MEM32(TS2_US_GAME_STEP);
        update();
        TS2_MEM32(TS2_US_GAME_FLOAT) = saved_step;
        return;
    }
    update();
}

extern void sub_000B7E00_gen(void);
void sub_000B7E00(void) { ts2_us_run_tick_update(sub_000B7E00_gen); }
extern void sub_00131DC0_gen(void);
void sub_00131DC0(void) { ts2_us_run_tick_update(sub_00131DC0_gen); }
extern void sub_00023330_gen(void);
void sub_00023330(void) { ts2_us_run_tick_update(sub_00023330_gen); }

/* The HUD text queue skips zero-tick updates. Age its entries by the time
 * those ticks cover, including the initial delay and the fade-out. */
extern void sub_000BC370_gen(void);
void sub_000BC370(void) { ts2_us_run_tick_update(sub_000BC370_gen); }

/* present is sub_001CC100 (PAL 0x001CC530): the only function in the game's
 * code that calls D3DDevice_Swap. */
extern void sub_001CC100_gen(void);
void sub_001CC100(void)
{
    static int g_ts2_us_last_hold = -1;
    static uint32_t g_ts2_us_last_seq = ~0u;
    uint32_t sequence = TS2_MEM32(TS2_US_SEQUENCE);
    int hold;

    /* The menu has per-frame animation and input repeats outside the game
     * clock. Use the existing front-end scene hook to keep it on vblank,
     * including menus with a backdrop drawn through the gameplay camera. */
    g_ts2_us_gameplay_frame = g_ts2_frame_camera && !g_ts2_frame_front_end;
    hold = ts2_us_cap_above_vblank() &&
           (!g_ts2_us_gameplay_frame || !ts2_us_free_step_enabled() ||
            sequence || TS2_MEM32(TS2_US_CLOCK_HELD) ||
            ts2_us_mapmaker_mode());
    if (sequence != g_ts2_us_last_seq) {
        fprintf(stderr, "[TS2-SEQ] sequence %u -> %u (gameplay %d, front end %d, "
                        "cap %s)\n",
                g_ts2_us_last_seq, sequence, g_ts2_us_gameplay_frame,
                g_ts2_frame_front_end, xbox_Nv2aFlipGateModeName());
        g_ts2_us_last_seq = sequence;
    }
    if (hold != g_ts2_us_last_hold) {
        fprintf(stderr, "[TS2-FLIP] hold vblank %d -> %d (sequence %u, "
                        "gameplay %d, cap %s)\n",
                g_ts2_us_last_hold, hold, sequence, g_ts2_us_gameplay_frame,
                xbox_Nv2aFlipGateModeName());
        g_ts2_us_last_hold = hold;
    }
    xbox_Nv2aFlipGateHoldVblank(hold);
    ts2_present(sub_001CC100_gen);
}

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

/* Extra characters from mods: the roster and its screens have not been
 * found in this release yet, so a mod's characters.ini is reported and left
 * alone (roster 0). PAL's are in config/pal/overrides.inc. */
const Ts2Roster k_ts2_roster = { 0 };

/* Loose mod files inside the paks: the pak table and its readers have not
 * been found in this release yet (table 0), so files/ and paks/ in a mod are
 * not served; whole data/*.pak files in a mod still are (the toolkit's
 * RECOMP_MODS). PAL's are in config/pal/overrides.inc. */
const Ts2Paks k_ts2_paks = { 0 };
