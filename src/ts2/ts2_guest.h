/*
 * ts2_guest.h -- what every hand-written TimeSplitters 2 source needs from
 * the runtime: the guest registers, guest memory, the settings lookups and
 * the diagnostic lock.
 *
 * Shared by recomp_manual.c and everything in src/overrides/. The lifter
 * scans those .c files (manual_scan.py) for the functions they define by
 * hand; this header defines none, so it is safe to include anywhere.
 */
#ifndef TS2_GUEST_H
#define TS2_GUEST_H

#include <stddef.h>   /* ptrdiff_t */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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

/* Guest memory at a guest address. */
#define TS2_MEM32(a) (*(volatile uint32_t *)((uintptr_t)(uint32_t)(a) + g_xbox_mem_offset))
#define TS2_MEM8(a) (*(volatile uint8_t *)((uintptr_t)(uint32_t)(a) + g_xbox_mem_offset))
#define TS2_MEMF(a) (*(volatile float *)((uintptr_t)(uint32_t)(a) + g_xbox_mem_offset))

/* The settings a player chooses (xboxrecomp src/config/recomp_config.h):
 * the environment variable, else the title's settings file. */
extern const char *recomp_config_lookup(const char *env_name, const char *key);
extern int  recomp_config_bool(const char *env_name, const char *key, int fallback);

#endif /* TS2_GUEST_H */
