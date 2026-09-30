/**
 * Manual function overrides and ICALL diagnostics
 *
 * This file provides:
 *   - recomp_lookup_manual()  : intercept specific Xbox VAs with hand-written code
 *   - recomp_icall_fail_log() : log when an indirect call target can't be resolved
 *   - ICALL trace ring buffer  : globals used by the RECOMP_ICALL macro
 *
 * The recomp pipeline generates an auto-dispatch table (recomp_lookup) that
 * resolves most function addresses. recomp_lookup_manual() is called FIRST,
 * giving you a chance to override any function with a custom implementation.
 *
 * Common reasons to add manual overrides:
 *   - Trace a function to understand call flow (wrap the generated version)
 *   - Fix a function the lifter translated incorrectly
 *   - Stub out a function that crashes (return early, set eax to a safe value)
 *   - Redirect a function to a native implementation (e.g., skip CRT init)
 *   - Intercept D3D/audio calls for custom rendering or sound
 */

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>   /* getenv, exit: the spin verdict below */
#include <string.h>   /* strcmp: RECOMP_ICALL_FATAL */

/* One diagnostic report, one piece.
 *
 * Each report below is a dozen fprintf calls and the CRT takes its lock per
 * call, so with more than one guest thread running the lines interleave in
 * the middle of a report. Dino Crisis 3 runs six workers once it is past its
 * menus, and its log came out like this:
 *
 *   callers: 0x004DB424 <- 0x002705B4 <- 0x002705B4[ICALL] unresolved jump
 *   target 0x41B0B870 -- 1 time(s) (total calls: 6930990)
 *
 * -- two threads' reports spliced together, with a caller list that stops
 * mid-sentence and an address that belongs to neither line as read. These
 * diagnostics exist to be read during exactly the multi-threaded bring-up
 * that breaks them.
 *
 * The CRT exposes the lock these calls were already taking one at a time, so
 * hold it across the whole report instead. */
#if defined(_MSC_VER)
#  define RECOMP_DIAG_LOCK()   _lock_file(stderr)
#  define RECOMP_DIAG_UNLOCK() _unlock_file(stderr)
#elif defined(__unix__) || defined(__APPLE__)
#  define RECOMP_DIAG_LOCK()   flockfile(stderr)
#  define RECOMP_DIAG_UNLOCK() funlockfile(stderr)
#else
#  define RECOMP_DIAG_LOCK()   ((void)0)
#  define RECOMP_DIAG_UNLOCK() ((void)0)
#endif

/* ── ICALL trace ring buffer ───────────────────────────────── */

/*
 * These globals are written by the RECOMP_ICALL macro (defined in
 * recomp_types.h) every time an indirect call is dispatched. When a
 * crash occurs, the VEH handler or recomp_icall_fail_log() can dump
 * the last 16 call targets to help you trace what happened.
 *
 * The runtime owns them: xbox_kernel defines all three in
 * src/kernel/xbox_memory_layout.c, and recomp_types.h declares them extern.
 * Declare, do not define -- a definition here as well is a duplicate symbol,
 * and a project copied from this template failed to link on all three:
 *
 *   xbox_memory_layout.obj : error LNK2005: g_icall_count already defined
 *                            in recomp_manual.obj
 */
extern volatile uint32_t g_icall_trace[16];
extern volatile uint32_t g_icall_trace_idx;
extern volatile uint64_t g_icall_count;

typedef void (*recomp_func_t)(void);

/* ── Register state (defined in xbox_memory_layout.c) ──────── */

/* These are defined thread-local in xbox_memory_layout.c. Declaring them
 * without the same storage class here does not fail to link -- it silently
 * resolves to different storage, so every read gets 0. That is why the log
 * below reported no call site: not because the guest esp was stale, but
 * because this file was not reading the guest esp at all. */
#if defined(_MSC_VER)
#  define RECOMP_MANUAL_TLS __declspec(thread)
#elif defined(__GNUC__) || defined(__clang__)
#  define RECOMP_MANUAL_TLS __thread
#else
#  define RECOMP_MANUAL_TLS _Thread_local
#endif

extern RECOMP_MANUAL_TLS uint32_t g_eax;
/* The guest stack pointer. At the moment an indirect call is refused, the
 * caller has already pushed its guest return address, so the top of the
 * guest stack is the call site -- the one thing the old log did not say. */
extern RECOMP_MANUAL_TLS uint32_t g_esp;
extern ptrdiff_t g_xbox_mem_offset;
/* The lifted code sections, so a value on the guest stack can be told
 * apart from data when naming the callers of a refused call. */
extern uint32_t g_xbox_code_lo;
extern uint32_t g_xbox_code_hi;
/* The esp the dispatch macro captured. Not g_esp, which is stale by the time
 * a refused call is reported. Zero when the title's generated header predates
 * this, and the log then says it has no callers rather than inventing them. */
extern RECOMP_MANUAL_TLS uint32_t g_icall_saved_esp;
/* Which dispatch form was refused: 0 unknown, 1 call, 2 jump. Unknown
 * means this title was lifted before the macros published it. */
extern RECOMP_MANUAL_TLS uint32_t g_icall_dispatch_form;

/* ── Manual function overrides ─────────────────────────────── */

/*
 * Return a function pointer to override the given Xbox VA, or NULL
 * to fall through to the auto-generated dispatch table.
 *
 * This is called on every indirect call (RECOMP_ICALL) and every
 * direct call through the dispatch table, so keep it fast. A chain
 * of if-statements on uint32_t compiles to a simple comparison
 * sequence; for large override tables, consider a sorted array
 * with binary search.
 *
 * Examples of common override patterns:
 *
 *   // Trace wrapper: log entry/exit around the generated function
 *   extern void sub_00012345(void);
 *   static void traced_sub_00012345(void) {
 *       fprintf(stderr, "[TRACE] sub_00012345 entered, eax=0x%08X\n", g_eax);
 *       sub_00012345();
 *       fprintf(stderr, "[TRACE] sub_00012345 returned, eax=0x%08X\n", g_eax);
 *   }
 *
 *   // Stub: skip a function entirely (return 0 in eax)
 *   static void stub_00067890(void) {
 *       g_eax = 0;
 *   }
 *
 *   // Fix: replace a broken lifted function with correct C
 *   static void fixed_sub_000ABCDE(void) {
 *       // Read arguments from stack/registers per calling convention
 *       uint32_t arg1 = g_ecx;
 *       uint32_t arg2 = MEM32(g_esp + 4);
 *       // ... correct implementation ...
 *       g_eax = result;
 *   }
 */
recomp_func_t recomp_lookup_manual(uint32_t xbox_va)
{
    /*
     * TODO: Add your overrides here. Examples:
     *
     * if (xbox_va == 0x00012345) return traced_sub_00012345;
     * if (xbox_va == 0x00067890) return stub_00067890;
     * if (xbox_va == 0x000ABCDE) return fixed_sub_000ABCDE;
     */

    (void)xbox_va;
    return (recomp_func_t)0;
}

/* ── ICALL failure logging ─────────────────────────────────── */

/*
 * Called when RECOMP_ICALL cannot resolve a target address.
 * This usually means one of:
 *   - A vtable dispatch to an address not in the dispatch table
 *   - A function pointer loaded from uninitialized or corrupt memory
 *   - A kernel thunk address that the bridge doesn't handle
 *
 * During early bring-up you will see many of these. Most are harmless
 * (the ICALL macro pops the dummy return address and continues).
 * Focus on the ones that cause crashes or incorrect behavior.
 */
void recomp_icall_fail_log(uint32_t va)
{
    /*
     * Rate-limited per target, reporting at 1, 10, 100 ...
     *
     * An unresolved target inside a loop is the normal case, not the rare
     * one: Mortal Kombat: Deadly Alliance produced 46843 of these for a
     * single address in one 30-second run, seventeen lines each. That buries
     * every other diagnostic in the log and says nothing the first report did
     * not. The progression is the useful part -- one line says a target was
     * never identified, a run of them says the title is stuck on it.
     */
    enum { SLOTS = 16 };
    static uint32_t seen[SLOTS];
    static uint64_t hits[SLOTS];
    static int count;
    int i;

    for (i = 0; i < count; i++)
        if (seen[i] == va)
            break;
    if (i == count) {
        if (count == SLOTS)
            return;
        seen[count] = va;
        hits[count] = 0;
        count++;
    }
    hits[i]++;
    {
        uint64_t n = hits[i];
        while (n >= 10 && n % 10 == 0)
            n /= 10;
        if (n != 1)
            return;
    }

    RECOMP_DIAG_LOCK();
    fprintf(stderr, "[ICALL] unresolved %starget 0x%08X -- %llu time(s) "
                    "(total calls: %llu)\n",
            g_icall_dispatch_form == 1 ? "call " :
            g_icall_dispatch_form == 2 ? "jump " : "",
            va, (unsigned long long)hits[i],
            (unsigned long long)g_icall_count);
    if (g_icall_dispatch_form == 2 && hits[i] == 1)
        fprintf(stderr, "  a jump, not a call: if this address is inside a "
                        "function rather than at its start, the guest is doing "
                        "its own control flow (a coroutine, a longjmp, or a "
                        "switch arm) and seeding it as a function will not "
                        "help\n");

    /*
     * Who called it. The lifted caller pushed its return address on the guest
     * stack, so code-range values above esp name the chain -- the same scan
     * the memory watchpoints use. It is a heuristic: stale return addresses
     * from earlier frames show up too, and the first entry is the reliable
     * one. It is still the difference between an address with no context and
     * a function to open, which is what an unresolved target needs.
     */
    {
        const uint8_t *stack = (const uint8_t *)g_xbox_mem_offset
                             + g_icall_saved_esp;
        int shown = 0;
        fprintf(stderr, "  callers:");
        for (i = 0; g_xbox_mem_offset && g_icall_saved_esp
                    && i < 160 && shown < 6; i++) {
            uint32_t v;
            memcpy(&v, stack + (size_t)i * 4, sizeof v);
            if (v >= g_xbox_code_lo && v < g_xbox_code_hi) {
                fprintf(stderr, "%s 0x%08X", shown ? " <-" : "", v);
                shown++;
            }
        }
        if (!shown)
            fprintf(stderr, " (none on the stack)");
        fprintf(stderr, "\n");
    }

    /* The recent-target ring buffer, once per address. What ran just before
     * an unresolved call is context for the first report and noise after. */
    if (hits[i] == 1) {
        fprintf(stderr, "  Recent ICALL targets:\n");
        for (i = 0; i < 16; i++) {
            int idx = (g_icall_trace_idx - 16 + i) & 15;
            if (g_icall_trace[idx])
                fprintf(stderr, "    [%2d] 0x%08X\n", i, g_icall_trace[idx]);
        }
    }
    RECOMP_DIAG_UNLOCK();
    fflush(stderr);
}
/* An indirect call whose target is not code: a null or wild function pointer.
 *
 * Skipping these is right -- calling a data address is worse -- but skipping
 * them *silently* is not. They almost always arrive inside a loop, so the
 * symptom is a hang with no output rather than a diagnosable null vtable call.
 *
 * Rate-limited per address: a spin can produce millions of these, and the
 * useful information is which addresses occur, not how often.
 */
void recomp_icall_not_code_log(uint32_t va, uint32_t saved_esp)
{
    /* A power of ten, because the rate limiter above only reaches this
     * function body at 1, 10, 100 ... and the verdict has to land on one of
     * those. A hundred thousand skips of one target is unambiguous: no title
     * makes progress through that. */
    enum { SLOTS = 16, SPIN_VERDICT = 100000 };
    static uint32_t seen[SLOTS];
    static uint64_t hits[SLOTS];
    static int count;
    static int said_it;   /* the verdict below is said once, not once per target */
    int i;

    for (i = 0; i < count; i++)
        if (seen[i] == va)
            break;
    if (i == count) {
        if (count == SLOTS)
            return;
        seen[count] = va;
        hits[count] = 0;
        count++;
    }
    hits[i]++;
    /* Report at 1, 10, 100, 1000 ... rather than once. A single line says a
     * wild pointer was skipped; the progression says it is being skipped in a
     * loop, which is the difference between a curiosity and the reason the
     * title is hung. */
    {
        uint64_t n = hits[i];
        while (n >= 10 && n % 10 == 0)
            n /= 10;
        if (n != 1)
            return;
    }
    {
        /* The call site, read off the guest stack. Without it the log
         * says a wild pointer was skipped but not by whom, and the
         * caller is the only thing that leads anywhere.
         *
         * It comes from the esp the dispatch macro captured, not from
         * g_esp. The lifted call site pushes its return address onto the
         * *local* esp and only syncs g_esp at certain points, so g_esp is
         * stale here -- it read 0 exactly when a null target most needed
         * explaining, which sent three rounds of Jet Set Radio Future
         * chasing inferences instead of a call site. saved_esp is the value
         * before that push, so the return address is the dword below it.
         *
         * Only for the call form. A tail jump pushes no return address, so
         * that dword is whatever the frame happened to leave there: Tony
         * Hawk's Pro Skater 2X reported "from 0x00000008" and then "from
         * 0x00000004" for the same million skipped calls, and both are
         * plainly not code. Printing a number that cannot be an address as
         * though it were the caller is worse than printing nothing, because
         * it is the one field a reader goes to next.
         *
         * So: name the form, and where the top of the stack cannot answer,
         * scan for code-range values the way the unresolved-target logger
         * above does. Stale return addresses from earlier frames come back
         * too and the first is the reliable one, but a list of real code
         * addresses is a place to start and 0x00000008 is not. */
        uint32_t caller = 0;
        if (g_icall_dispatch_form != 2 && saved_esp >= 4 && g_xbox_mem_offset)
            caller = *(const uint32_t *)((const uint8_t *)g_xbox_mem_offset
                                         + (saved_esp - 4));
        if (caller < g_xbox_code_lo || caller >= g_xbox_code_hi)
            caller = 0;
        RECOMP_DIAG_LOCK();
    fprintf(stderr, "[ICALL] target 0x%08X is not code -- skipped "
                        "%llu time(s) via a %s",
                va, (unsigned long long)hits[i],
                g_icall_dispatch_form == 2 ? "jump" : "call");
        if (caller)
            fprintf(stderr, " from 0x%08X", caller);
        fprintf(stderr, " (null or wild function pointer, at call #%llu)\n",
                (unsigned long long)g_icall_count);

        /* The stack scan, once per address: the same heuristic the
         * unresolved-target logger uses, and the only thing that names a
         * caller when the return address is not where it should be. */
        if (hits[i] == 1) {
            const uint8_t *stack = (const uint8_t *)g_xbox_mem_offset
                                 + saved_esp;
            int shown = 0, k;
            fprintf(stderr, "  callers:");
            for (k = 0; g_xbox_mem_offset && saved_esp
                        && k < 160 && shown < 6; k++) {
                uint32_t v;
                memcpy(&v, stack + (size_t)k * 4, sizeof v);
                if (v >= g_xbox_code_lo && v < g_xbox_code_hi) {
                    fprintf(stderr, "%s 0x%08X", shown ? " <-" : "", v);
                    shown++;
                }
            }
            if (!shown)
                fprintf(stderr, " (none on the stack)");
            fprintf(stderr, "\n");
        }

        /* RECOMP_ICALL_FATAL=1: fault here instead of skipping, so the crash
         * handler prints the guest call stack that reached this call.
         *
         * The caller printed above is read from the top of the guest stack,
         * which is right only when the lifted call site pushed a return
         * address there and nothing has since moved esp. When it reads 0 --
         * exactly the case where a null target most needs explaining -- the
         * line says a wild pointer was skipped and nothing about by whom. A
         * deliberate fault costs the run and buys the backtrace. */
        {
            static int fatal = -1;
            if (fatal < 0) {
                const char *v = getenv("RECOMP_ICALL_FATAL");
                fatal = v && *v && strcmp(v, "0") != 0;
            }
            if (fatal) {
                fprintf(stderr, "[ICALL] RECOMP_ICALL_FATAL: faulting here for "
                                "a backtrace\n");
                fflush(stderr);
                *(volatile int *)0 = 1;
            }
        }
    }

    /* Past a certain count this stops being a warning and becomes a verdict.
     *
     * A skipped call sets eax to 0 and returns. Zero is a fine answer for a
     * null function pointer in most code -- it reads as NULL, false, or
     * nothing -- but it is also S_OK, so in COM-shaped code a loop that
     * repeats while the result is non-negative can never leave. Panzer
     * Dragoon Orta hung exactly there, three billion skips in forty seconds,
     * with no frame ever presented.
     *
     * The value is deliberately left alone: there is no return value that is
     * right for both conventions, and guessing failure would break the
     * callers for which zero is correct. What can be fixed is the silence.
     * Say plainly that the title is hung, once, and say what to do about it.
     */
    if (hits[i] == SPIN_VERDICT && !said_it) {
        said_it = 1;
        fprintf(stderr,
            "[ICALL] ^^ this is a hang, not slow progress. One target has been\n"
            "        skipped %d times. The skip returns eax = 0, which is also\n"
            "        S_OK, so a loop testing for a non-negative result will\n"
            "        never exit. Try `py -3 -m tools.seed_from_log <log>` to\n"
            "        recover the target as a function, and read\n"
            "        docs/technical/memory-watchpoints.md for who wrote the\n"
            "        pointer. Set RECOMP_ICALL_SPIN_FATAL=1 to stop here\n"
            "        instead of spinning.\n", SPIN_VERDICT);
        fflush(stderr);
        if (getenv("RECOMP_ICALL_SPIN_FATAL")) {
            fprintf(stderr, "[ICALL] RECOMP_ICALL_SPIN_FATAL is set; exiting.\n");
            fflush(stderr);
            exit(3);
        }
    }
    RECOMP_DIAG_UNLOCK();
    fflush(stderr);
}


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

#define TS2_MEMF(a) (*(volatile float *)((uintptr_t)(uint32_t)(a) + g_xbox_mem_offset))

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
extern const char *recomp_config_lookup(const char *env_name, const char *key);

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

extern void sub_001CC530_gen(void);
void sub_001CC530(void)
{
    sub_001CC530_gen();
    xbox_D3D8SetWideFrames(ts2_menus_wide() ||
                           (g_ts2_frame_camera && !g_ts2_frame_front_end));
    g_ts2_frame_camera = g_ts2_frame_front_end = 0;
}

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

enum { TS2_UI_AUTO = 0, TS2_UI_STRETCH, TS2_UI_CENTRE, TS2_UI_LEFT, TS2_UI_RIGHT,
       TS2_UI_SIDE };

/* xboxrecomp src/hle/hle_d3d8_record.h: xbox_D3D8SetTwoDPlacement, recorded in
 * frame captures so a capture replays with these placements. Same values
 * as XBOX_D3D8_2D_*. */
extern void host_SetTwoDPlacement(int placement, uint32_t tag);
extern int  recomp_config_bool(const char *env_name, const char *key, int fallback);

typedef struct Ts2UiPlace { uint32_t site; int placement; } Ts2UiPlace;

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
static const Ts2UiPlace k_ts2_ui_places[] = {
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
    { 0, TS2_UI_AUTO }
};

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

#define TS2_MEM32(a) (*(volatile uint32_t *)((uintptr_t)(uint32_t)(a) + g_xbox_mem_offset))

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
                (int)(sizeof k_ts2_ui_places / sizeof k_ts2_ui_places[0]) - 1,
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
        uint32_t leaf = TS2_MEM32(g_esp);
        uint32_t site = g_ts2_depth ? g_ts2_chain[0] : leaf;
        int place = ts2_ui_place_for(site);

        if (g_ts2_ui_mode == 2)
            ts2_ui_note_site(site, leaf);
        if (place != g_ts2_batch_place || place == TS2_UI_SIDE ||
            (g_ts2_ui_mode == 2 && site != g_ts2_batch_site)) {
            /* The queue holds another site's pieces: draw them under their
             * own placement before this one's join it. A SIDE site's pieces
             * are drawn one by one, since the renderer pins each draw to the
             * edge it is nearer and one draw holding both hands' ammo would
             * be pinned to neither. */
            ts2_ui_flush();
            g_ts2_batch_place = place;
            g_ts2_batch_site = site;
        }
        /* The renderer holds the batch's placement from the moment anything
         * is queued in it, not only around sub_001C9CDF: the engine also
         * draws the batch by other ways (sub_001C967C calls the draw
         * itself), and a batch drawn that way came out under AUTO -- the
         * ammo's bars and dark backing stayed in the 4:3 layout while the
         * numbers went to the corners. */
        ts2_ui_host_place(g_ts2_batch_place,
                          g_ts2_ui_mode == 2 ? g_ts2_batch_site : 0);
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
     * pass, a movie) must not inherit its placement. */
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
