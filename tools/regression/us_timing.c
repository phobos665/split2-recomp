#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "recomp_cpu.h"

extern void fixture_free_step(int);
typedef void (*GuestFn)(void);
extern GuestFn recomp_lookup(uint32_t);
extern ptrdiff_t g_xbox_mem_offset;
extern int recomp_dispatch_init(void);
extern void sub_0019EF80(void), sub_000B7E00(void), sub_00131DC0(void), sub_00023330(void);
extern void sub_000BB650(void), sub_000BC370(void);

static _Alignas(16) uint8_t ram[8 << 20];
#define U(addr) (*(uint32_t *)(ram + (addr)))
#define F(addr) (*(float *)(ram + (addr)))

enum {
    stack = 0x700000,
    object = 0x500000,
    particle = 0x510000,
    pool = 0x3602E0,
    step = 0x34889C,
    elapsed = 0x3488A4,
    rng_calls = 0x3ef8d0
};

static int failed;

static void guest_call(void (*routine)(void))
{
    g_esp = stack;
    U(stack + 4) = object;
    routine();
    if (g_esp != stack + 4 || g_fp_top) {
        printf("Guest stack mismatch, ESP %x, FP top %u\n", g_esp, g_fp_top);
        failed = 1;
    }
}

static void advance(int ticks, float dt)
{
    U(step) = ticks;
    F(elapsed) = dt;
    guest_call(sub_000B7E00);
    if (U(step) != (unsigned)ticks || F(elapsed) != dt)
        failed = 1;
}

static void check_hud_message(int hz)
{
    enum {
        player = 0x540000,
        text = 0x541000,
        queue = 0x4a8d20,
        message = queue + 0x38
    };

    memset(ram + queue, 0, 0x1254);
    U(0x497100) = player;
    U(player + 4) = 0;
    U(0x364318) = 1;
    memcpy(ram + text, "Test message", sizeof("Test message"));
    g_esp = stack;
    U(stack + 4) = 0;
    U(stack + 8) = 1;
    U(stack + 12) = text;
    F(stack + 16) = 0.25f;
    sub_000BB650();
    if (g_esp != stack + 4 || g_fp_top || U(message) != 1 ||
        F(message + 0x108) != -0.25f) {
        puts("HUD message enqueue failed");
        failed = 1;
        return;
    }

    float lifetime = F(message + 0x114);
    int expired = 0;
    float age = 0.0f;
    fixture_free_step(hz > 60);
    for (int frame = 1; frame <= hz * 6 && !expired; ++frame) {
        int ticks = frame * 60 / hz - (frame - 1) * 60 / hz;
        U(step) = ticks;
        F(elapsed) = 60.0f / hz;
        guest_call(sub_000BC370);
        failed |= U(step) != (unsigned)ticks || F(elapsed) != 60.0f / hz;
        if (frame == hz)
            age = F(message + 0x108);
        if (!U(message))
            expired = frame * 60 / hz;
    }
    printf("%3d FPS  HUD message age at one second %.5f, expired at tick %d\n",
           hz, age, expired);
    failed |= fabsf(age - 0.75f) > 0.0001f || !expired ||
              fabsf(expired - (lifetime + 0.25f) * 60.0f) > 2.0f;
}

int __wrap_main(int argc, char **argv)
{
    if (argc != 2)
        return 2;
    FILE *image = fopen(argv[1], "rb");
    if (!image || fread(ram, 1, 0x400000, image) != 0x400000)
        return 2;
    fclose(image);
    g_xbox_mem_offset = (ptrdiff_t)(uintptr_t)ram;
    if (!recomp_dispatch_init())
        return 2;

    /* A zero-tick emitter must not draw random numbers between logic ticks. */
    fixture_free_step(1);
    U(object + 0x16c) = 0x520000;
    U(step) = 0;
    F(elapsed) = 0.25f;
    U(0x2e6450) = 1;
    U(0x2e6454) = 0;
    unsigned before = U(rng_calls);
    guest_call(sub_0019EF80);
    printf("zero-tick emitter random draws %u\n", U(rng_calls) - before);
    failed |= U(rng_calls) != before || U(step) != 0;

    int rates[] = {30, 60, 120, 144, 317, 719};
    for (unsigned i = 0; i < sizeof(rates) / sizeof(rates[0]); ++i) {
        int hz = rates[i];
        check_hud_message(hz);
        fixture_free_step(hz > 60);
        memset(ram + pool, 0, 17 * 4);
        memset(ram + particle, 0, 0x68);
        U(pool + 4) = particle;
        U(particle + 0x14) = 1;
        U(particle + 0x18) = 0;
        F(particle + 0x24) = 1.125f;
        F(particle + 0x28) = 6.0f;
        for (int frame = 1; frame <= hz; ++frame) {
            int ticks = frame * 60 / hz - (frame - 1) * 60 / hz;
            advance(ticks, 60.0f / hz);
        }
        printf("%3d FPS  age %.6f s, travel %.6f", hz,
               F(particle + 0x20), F(particle));
        failed |= fabsf(F(particle + 0x20) - 1.0f) > 0.0001f ||
                  fabsf(F(particle) - 6.0f) > 0.0001f;
        for (int frame = hz + 1; frame <= hz + hz / 5; ++frame) {
            int ticks = frame * 60 / hz - (frame - 1) * 60 / hz;
            advance(ticks, 60.0f / hz);
        }
        printf(", expired %s\n", U(pool + 4) ? "no" : "yes");
        failed |= U(pool + 4) != 0;
    }

    enum { streak = 0x570000, rocket = 0x580000 };
    for (unsigned k = 0; k < sizeof(rates) / sizeof(rates[0]); ++k) {
        int hz = rates[k];
        fixture_free_step(hz > 60);
        memset(ram + streak, 0, 0x100);
        F(streak + 16) = 0.25f;
        U(object + 0x18) = streak;
        F(object + 0xc) = 0.2f;
        memset(ram + rocket, 0, 70 * 0x1a4);
        for (int i = 0; i < 70; ++i)
            U(rocket + 0x1a4 * i) = 0xffffffff;
        U(0x353538) = rocket;
        U(rocket) = 39;
        F(rocket + 0x40) = 0.125f;
        for (int i = 1; i <= hz; ++i) {
            U(step) = i * 60 / hz - (i - 1) * 60 / hz;
            F(elapsed) = 60.0f / hz;
            guest_call(sub_00131DC0);
            if (i <= (2 * hz + 4) / 5)
                guest_call(sub_00023330);
            if (F(elapsed) != 60.0f / hz)
                failed = 1;
        }
        printf("%3d FPS  tracer %.5f, missile pos %.5f age %.5f sweep sum %.5f\n",
               hz, F(streak + 4), F(rocket + 0x1c), F(rocket + 0x5c),
               F(rocket + 0xac));
        failed |= fabsf(F(streak + 4) - 15.0f) > 0.0001f ||
                  fabsf(F(rocket + 0x1c) - 3.0f) > 0.0001f ||
                  fabsf(F(rocket + 0x5c) - 0.4f) > 0.0001f;
    }

    fixture_free_step(1);
    const int ticks[] = {0, 1, 0, 3, 0, 2};
    const float dt[] = {.25f, .9f, .3f, 2.8f, .5f, 1.25f};
    memset(ram + pool, 0, 17 * 4);
    memset(ram + particle, 0, 0x68);
    U(pool + 4) = particle;
    U(particle + 0x14) = 1;
    F(particle + 0x24) = 2;
    F(particle + 0x28) = 6;
    for (unsigned i = 0; i < sizeof(ticks) / sizeof(ticks[0]); ++i)
        advance(ticks[i], dt[i]);
    failed |= fabsf(F(particle + 0x20) - .1f) > .0001f ||
              fabsf(F(particle) - .6f) > .0001f;
    return failed;
}
