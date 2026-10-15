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
#include <stddef.h>   /* ptrdiff_t: not in stdlib.h off MSVC */
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

/* The guest registers (g_eax, g_esp, g_icall_saved_esp, ...) are fields of
 * one thread-local struct, declared once in recomp_cpu.h, which the lifter
 * copies into gen/ beside the code it describes. Take them from there; never
 * redeclare one here. They used to be redeclared by hand, and a declaration
 * without the thread-local storage class linked and silently read other
 * storage, so every read got 0 -- which is why the log below once reported
 * no call site: not because the guest esp was stale, but because this file
 * was not reading the guest esp at all. The names are macros now, so a
 * redeclaration no longer compiles. */
#include "recomp/gen/recomp_cpu.h"

/* Thread-local storage for this file's own state (the call chain below). */
#if defined(_MSC_VER)
#  define RECOMP_MANUAL_TLS __declspec(thread)
#elif defined(__GNUC__) || defined(__clang__)
#  define RECOMP_MANUAL_TLS __thread
#else
#  define RECOMP_MANUAL_TLS _Thread_local
#endif

/* g_eax: recomp_cpu.h. */
/* The guest stack pointer. At the moment an indirect call is refused, the
 * caller has already pushed its guest return address, so the top of the
 * guest stack is the call site -- the one thing the old log did not say. */
/* g_esp: recomp_cpu.h. */
extern ptrdiff_t g_xbox_mem_offset;
/* The lifted code sections, so a value on the guest stack can be told
 * apart from data when naming the callers of a refused call. */
extern uint32_t g_xbox_code_lo;
extern uint32_t g_xbox_code_hi;
/* The esp the dispatch macro captured. Not g_esp, which is stale by the time
 * a refused call is reported. Zero when the title's generated header predates
 * this, and the log then says it has no callers rather than inventing them. */
/* g_icall_saved_esp: recomp_cpu.h. */
/* Which dispatch form was refused: 0 unknown, 1 call, 2 jump. Unknown
 * means this title was lifted before the macros published it. */
/* g_icall_dispatch_form: recomp_cpu.h. */

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
 * The in-game camera is set up in one place, camera_setup(near, far,
 * aspect, fov_degrees). It turns the aspect into the screen's
 * (aspect * width / height), builds the projection from it with
 * build_projection(out, aspect, fovy, near, far), and stores tan(fov/2) at
 * camera+0x31C and aspect * tan(fov/2) -- the horizontal half-width the
 * culling uses -- at camera+0x320. Widening the aspect argument on the
 * way in widens both, so what is drawn and what is kept agree.
 *
 * Only this camera: the other callers of build_projection are the front
 * end's 3D (character select and the like), which is kept at 4:3.
 *
 * Names like camera_setup are the game's functions by what they do. Where
 * each one is depends on the release: each release's
 * config/<region>/overrides.inc wraps its own with the hooks in this file
 * (see the end of it), so nothing in this file is an address.
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

static void ts2_camera_setup(void (*camera_setup)(void))
{
    float widen = ts2_camera_widen();

    if (widen != 1.0f)
        TS2_MEMF(g_esp + 0x0C) *= widen;   /* [esp] is the return address */
    camera_setup();
    g_ts2_frame_camera = 1;                /* see ts2_present below */
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
 *   menus, story level select   in-game camera + front_end_scene
 *   in-engine cutscenes         in-game camera
 *   playing                     in-game camera
 *   loading screens             neither
 *
 * front_end_scene sets up the front end's own 3D scene (it builds a
 * camera of its own). The front end draws its backdrop through the
 * in-game camera as well, hence the pair.
 *
 * present is the game's once-a-frame present (it calls
 * D3DDevice_Swap). After a frame is presented, the next is given the shape
 * the finished one called for: a frame's own draws are not all in yet
 * when it starts, and a screen lasts many frames, so the only cost is one
 * frame at each change, which falls on a fade or a load.
 */
static void ts2_front_end_scene(void (*front_end_scene)(void))
{
    g_ts2_frame_front_end = 1;
    front_end_scene();
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

/*
 * Frame interpolation (xboxrecomp hle_d3d8_interp.c, RECOMP_FRAME_INTERP)
 * blends the matrices in TS2's vertex constants, measured from captures:
 * c60-c63 hold the projection alone, set once or twice a frame; c64-c67
 * the model-view of each object; c68-c75 the second and third matrices of
 * a skinned piece's palette. All affine, rows with (0,0,0,1) last. Said
 * once, at the first present, which is before any level is drawn.
 */
extern void xbox_D3D8SetInterpRegisters(int projection, int affine_first, int affine_count);

static void ts2_present(void (*present)(void))
{
    static int interp_said;

    if (!interp_said) {
        interp_said = 1;
        xbox_D3D8SetInterpRegisters(60, 64, 12);
    }
    present();
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
 * of the game's 2D reaches the GPU through one call, reserve(primitive,
 * format, ?, count), which reserves vertices in the engine's batch for the
 * caller to fill; flush sends the batch to DrawVertices. So:
 *
 *   - the reservation is wrapped, and reads its caller from the guest stack
 *     (a lifted call pushes the real return address first);
 *   - the engine's shared drawing functions above it are wrapped too, so a
 *     piece drawn through one is credited to the UI code that called it --
 *     the *site* is the caller of the outermost wrapped function;
 *   - k_ts2_ui_places says where each known site goes; unknown ones
 *     are left to the renderer (AUTO), exactly as before;
 *   - a reservation whose placement differs from the batch's flushes the
 *     batch first; the renderer is given the batch's placement as soon as
 *     anything is queued (the engine draws the batch by more than one way),
 *     and flush resets it once the batch is drawn, so a draw that
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

/* Where the game draws what: each release's own table, in its
 * config/<region>/overrides.inc. Sites are return addresses in the game's
 * UI code, so they differ between releases. Ends at site 0.
 *
 * Built from the front end, screen by screen: frames captured with
 * RECOMP_TS2_UI_SITES=1, each site drawn alone and each left out with
 * d3d8_replay --each-tag / --each-tag-hidden, and the table tried on the
 * captures with --place before it went in. The rule: whatever covers
 * the screen spans the picture, the side decorations and the header's
 * left and right ends go to the edges of it, and everything a player
 * reads stays in proportion in the middle. A full-screen pass left to the
 * renderer's width guess was sometimes kept at 4:3, and its edge showed
 * as a seam down both old borders on every screen. */
extern const Ts2UiPlace k_ts2_ui_places[];

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
 * the renderer's placement then (ts2_ui_reserve). */
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

static int ts2_ui_table_size(void)
{
    int n = 0;

    while (k_ts2_ui_places[n].site)
        n++;
    return n;
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
                ts2_ui_table_size(),
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
static void ts2_ui_flush(void (*flush)(void))
{
    g_esp -= 4;
    TS2_MEM32(g_esp) = 0;
    flush();
}

static void ts2_ui_reserve(void (*reserve)(void), void (*flush)(void))
{
    if (ts2_ui_mode()) {
        uint32_t leaf = TS2_MEM32(g_esp);
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
            ts2_ui_flush(flush);
            g_ts2_keep_host = 0;
        }
        /* The engine keeps more than one batch (by format, it seems), and
         * flush does not always draw the one that holds the last pieces:
         * the reservation itself draws it, when the next piece does not fit
         * it, by its own way (a function under reserve calls the draw). So the
         * renderer holds the old batch's placement until that has happened,
         * and takes the new one after, for the pieces now queued -- whose
         * batch may be drawn by either way. Setting the new one first put
         * the right hand's ammo bars, the last piece before the next site,
         * under that site's placement and left them in the 4:3 layout. */
        reserve();
        if (change) {
            g_ts2_batch_place = place;
            g_ts2_batch_site = site;
        }
        ts2_ui_host_place(g_ts2_batch_place,
                          g_ts2_ui_mode == 2 ? g_ts2_batch_site : 0);
        return;
    }
    reserve();
}

static void ts2_ui_batch_flush(void (*flush)(void))
{
    if (g_ts2_ui_mode <= 0) {
        flush();
        return;
    }
    ts2_ui_host_place(g_ts2_batch_place, g_ts2_ui_mode == 2 ? g_ts2_batch_site : 0);
    flush();
    /* The batch is empty again: a draw that never went through it (a glow
     * pass, a movie) must not inherit its placement -- unless a reservation
     * is flushing ahead of itself, when another batch may still be drawn
     * under this placement (ts2_ui_reserve). */
    if (!g_ts2_keep_host)
        ts2_ui_host_place(TS2_UI_AUTO, 0);
}

/* The engine's shared drawing functions: the helpers that reserve vertices
 * for many callers (quads, sprites, text), and the ones above them that the
 * menu and HUD code call. Whoever called the outermost of them is the site.
 * Each release wraps its own: ts2_ui_enter(), the lifted body, ts2_ui_leave(). */
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

/* ── TimeSplitters 2: big heads ─────────────────────────────── */

/*
 * RECOMP_TS2_BIG_HEAD / ts2_big_head = <factor>: every human character's
 * head drawn <factor> times its size (2.5 is a good one; 1, or nothing, is
 * the game as it was; below 1 shrinks them).
 *
 * The game has this already, as a cheat: animate(character), once a frame
 * for each character on screen (the front end's previews too), poses the
 * skeleton's bones in their parents' space, then -- when cheat bit 2 is
 * on -- multiplies one bone by a scale matrix of 2 (bit 4 is the small-head
 * cheat, 0.5; bit 8 big hands), and only then builds the type-2 mid-joint
 * bones from their neighbours (blend_joints, the call this wraps), composes
 * every bone with its parent's (compose_bones). The cheat bit is tested nowhere else,
 * so it changes the picture and nothing the game plays by: hits are still
 * judged on the head the game had.
 *
 * This does the same, at the same moment, with any factor: in the wrap of
 * blend_joints, when it is animate calling it. The bone is still
 * parent-relative there, so scaling its basis (its first three rows; the
 * matrices are row-vector, translation in the fourth) grows it about its
 * own joint, and compose_bones carries the scale into the matrix its pieces
 * are drawn with (c64-c75), which is what frame interpolation then blends.
 * Anything placed on the head bone after that (a separate hat) should
 * grow with it, as with the cheat; not seen up close yet.
 *
 * One difference: the cheat scales the bone its skeleton table names
 * ([character+0x70]+0x18), which is bone 3, the neck, so the neck grows as
 * much as the head and the head is lifted on it. This scales bone 4, the
 * head, about the top of the neck: the neck keeps its size and the head
 * stays on it (the joint pieces between them follow whichever bone each
 * vertex names, and the vertices at the joint barely move).
 *
 * Only for a human skeleton: the model's rigid pieces, walked as the game
 * walks them, must give the 19-bone hierarchy every human shares (pelvis 0,
 * spine 1, chest 2, neck 3, head 4; xbr.md on feat/character-models). The
 * Barrel Robot, the bosses, guns and props are left alone. And not when
 * the character's +0x6C record says the cheat must not apply (the cheat
 * tests the same word).
 *
 * The character, as animate reads it: +0x00 the model (its descriptor:
 * +0 piece count, +4 bone count; the 0x9C-byte pieces just below it),
 * +0x04 the bone matrices, 64 bytes each, +0x6C the record the cheat
 * checks (+0xC must be 0). A piece: +0 type (0 rigid, 1-3 joints), +1
 * bone, +3 first child, +4 next sibling.
 */
extern double recomp_config_float(const char *env_name, const char *key, double fallback);

static float ts2_big_head_factor(void)
{
    static float factor = -1.0f;

    if (factor < 0.0f) {
        double f = recomp_config_float("RECOMP_TS2_BIG_HEAD", "ts2_big_head", 1.0);

        if (!(f > 0.0))             /* 0, negative, not a number: off */
            f = 1.0;
        if (f < 0.1) f = 0.1;
        if (f > 6.0) f = 6.0;
        factor = (float)f;
        if (factor != 1.0f)
            fprintf(stderr, "[TS2] big heads: x%g (RECOMP_TS2_BIG_HEAD / ts2_big_head)\n",
                    (double)factor);
    }
    return factor;
}

#define TS2_PIECE_SIZE 0x9C
#define TS2_MEM8S(a) (*(volatile int8_t *)((uintptr_t)(uint32_t)(a) + g_xbox_mem_offset))
#define TS2_MEM8(a)  (*(volatile uint8_t *)((uintptr_t)(uint32_t)(a) + g_xbox_mem_offset))

/* The bone the head's pieces are drawn with, or -1 when the model is not a
 * human. The rigid pieces met walking the tree depth first from piece 0,
 * child before next sibling and never down through a type-3 piece (as
 * compose_bones walks it), are the animation bones in order, and each one's
 * parent is the nearest rigid piece above it. Done for each character each
 * frame, rather than remembered by model address: a level load puts other
 * models at the same addresses, and the walk is a few dozen bytes read. */
static int ts2_human_head_bone(uint32_t model)
{
    static const int8_t k_human[19] = {
        -1, 0, 1, 2, 3, 2, 5, 6, 7, 2, 9, 10, 11, 0, 13, 14, 0, 16, 17
    };
    struct { int piece, rigid_parent; } stack[128];
    int depth = 0, rigid = 0, head = -1, count;
    uint32_t pieces;

    if (!model)
        return -1;
    count = (int)TS2_MEM32(model);
    if (count < 19 || count > 127)
        return -1;
    pieces = model - (uint32_t)count * TS2_PIECE_SIZE;

    stack[depth].piece = 0;
    stack[depth].rigid_parent = -1;
    depth++;
    while (depth > 0) {
        int p, parent;

        depth--;
        p = stack[depth].piece;
        parent = stack[depth].rigid_parent;
        /* A sibling chain is walked in place, its children pushed. */
        while (p >= 0 && p < count) {
            uint32_t piece = pieces + (uint32_t)p * TS2_PIECE_SIZE;
            uint8_t type = TS2_MEM8(piece);
            int8_t child = TS2_MEM8S(piece + 3);
            int below = parent;

            if (type == 0) {
                if (rigid >= 19 || k_human[rigid] != parent)
                    return -1;
                if (rigid == 4)
                    head = TS2_MEM8S(piece + 1);
                below = rigid++;
            }
            if (child >= 0 && type != 3) {
                if (depth >= (int)(sizeof stack / sizeof stack[0]) - 1)
                    return -1;
                /* The sibling waits while the child's subtree is walked. */
                stack[depth].piece = TS2_MEM8S(piece + 4);
                stack[depth].rigid_parent = parent;
                depth++;
                p = child;
                parent = below;
                continue;
            }
            p = TS2_MEM8S(piece + 4);
        }
    }
    return rigid == 19 ? head : -1;
}

static void ts2_big_head(uint32_t character)
{
    float s = ts2_big_head_factor();
    uint32_t model, record, m;
    int bone, i;

    if (s == 1.0f || !character)
        return;
    record = TS2_MEM32(character + 0x6C);
    if (record && TS2_MEM32(record + 0x0C) != 0)
        return;
    model = TS2_MEM32(character);
    bone = ts2_human_head_bone(model);
    {
        /* The first models seen, and whether the cheat's own head bone
         * ([character+0x70]+0x18) agrees with the walk. */
        static uint32_t seen[32];
        static int seen_count;
        uint32_t skel = TS2_MEM32(character + 0x70);
        int k;

        for (k = 0; k < seen_count && seen[k] != model; k++)
            ;
        if (k == seen_count && seen_count < 32) {
            seen[seen_count++] = model;
            fprintf(stderr, "[TS2] big heads: model 0x%08X, %u pieces, %u bones: %s%d "
                    "(the cheat's head bone %d)\n", model, TS2_MEM32(model),
                    TS2_MEM32(model + 4), bone >= 0 ? "human, head bone " : "not human ",
                    bone, skel ? (int)TS2_MEM32(skel + 0x18) : -1);
        }
    }
    if (bone < 0 || bone >= (int)TS2_MEM32(model + 4))
        return;
    m = TS2_MEM32(character + 4) + (uint32_t)bone * 64;
    for (i = 0; i < 12; i++)                /* rows 0-2: the basis */
        TS2_MEMF(m + 4 * i) *= s;
}

/* blend_joints(character, piece, bind) with the return address animate
 * gives it (each release's overrides.inc says which); its other callers are
 * itself and the model loader's bind pose. */
static void ts2_blend_joints(void (*blend_joints)(void), uint32_t from_animate)
{
    if (TS2_MEM32(g_esp) == from_animate)
        ts2_big_head(TS2_MEM32(g_esp + 4));
    blend_joints();
}

/* ── TimeSplitters 2: where this release's functions are ─────── */

/*
 * Everything above is the same in every release of the game; where it
 * attaches is not. config/<region>/overrides.inc, one per release, wraps
 * that release's functions with the hooks above (its camera_setup with
 * ts2_camera_setup, and so on) and holds its k_ts2_ui_places. Which release
 * src/recomp/gen was lifted from is in src/recomp/ts2_region.h, which
 * scripts/build.py writes with the lift.
 *
 * The lifter decides what not to generate by reading this file as text
 * (xboxrecomp tools/recomp/manual_scan.py) and does not follow the #include
 * below, so scripts/build.py hands it this file and the release's
 * overrides.inc as one: each release's functions, and only those, are
 * wrapped. A function goes into a release's overrides.inc only once it has
 * been found in that release by what it does. A release that has not found
 * one leaves its hook unused, and the lifted function runs as it is.
 */
#include "ts2_region.h"

#if defined(TS2_REGION_PAL)
#include "../config/pal/overrides.inc"
#elif defined(TS2_REGION_US)
#include "../config/us/overrides.inc"
#else
#error "src/recomp/ts2_region.h names no release this file knows; lift with scripts/build.py"
#endif
