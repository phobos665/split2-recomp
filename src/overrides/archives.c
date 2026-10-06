/*
 * archives.c -- TimeSplitters 2: the game's own override archives come first.
 *
 * The game keeps its data in .pak archives and opens files inside them by
 * name. sub_000865C0 mounts a level's set: it closes every archive, clears
 * the table, then mounts the level's archive and the shared ones (chrinc,
 * sounds, demos), and last of all data/xbt.pak, data/xbob.pak and
 * data/xbsound.pak. The disc has none of those three, so their mounts fail
 * and nothing is added; they are named for textures, objects and sounds.
 *
 * File lookup, sub_000860A0, walks the table from slot 0 and takes the
 * first archive that has the name. Mounted last, the three can only supply
 * files no other archive has: a mod in data/xbt.pak was opened and indexed
 * (6 Oct 2026) and never drawn, because every level archive carries its own
 * copy of the shared textures.
 *
 * So once the set is mounted, any of the three that did mount moves to the
 * front, keeping the order of the rest. With the mods folder, one small
 * mods/data/xbt.pak then replaces a texture in every level, instead of a
 * rebuilt copy of each of the 43 archives that hold it. On a disc with no
 * such archive nothing moves and nothing changes.
 *
 * Safe to move: no caller of the mount function (sub_00085DB0) keeps the
 * slot it returns, and nothing has been read from the set when it returns.
 * The table, from sub_00085DB0 and sub_000865C0:
 *
 *   0x00358A18   archives mounted (at most 25)
 *   0x00358A38   25 slots of 0x20 bytes; +0x1C is the mounted name
 */
#include "ts2/ts2_guest.h"
#include "ts2/ts2_types.h"

#include <ctype.h>

static int ts2_pak_is_override(uint32_t name_va)
{
    static const char *const overrides[] = { "xbt.pak", "xbob.pak", "xbsound.pak" };
    char name[64];
    const char *base;
    size_t i, n;

    if (!name_va)
        return 0;
    for (n = 0; n + 1 < sizeof name; n++) {
        name[n] = (char)TS2_MEM8(name_va + n);
        if (!name[n])
            break;
    }
    name[n] = '\0';
    base = strrchr(name, '/');
    base = base ? base + 1 : name;
    for (i = 0; i < sizeof overrides / sizeof overrides[0]; i++) {
        const char *a = base, *b = overrides[i];
        while (*a && tolower((unsigned char)*a) == *b)
            a++, b++;
        if (!*a && !*b)
            return 1;
    }
    return 0;
}

static void ts2_paks_overrides_first(void)
{
    uint8_t moved[TS2_PAK_SLOTS * TS2_PAK_SLOT_SIZE];
    uint8_t *table = (uint8_t *)ts2_view(uint8_t, TS2_PAK_TABLE);
    int32_t count = (int32_t)TS2_MEM32(TS2_PAK_COUNT);
    int pass, i, out = 0, front = 0;

    if (count <= 1 || count > TS2_PAK_SLOTS)
        return;
    /* Two passes over the slots: the override archives, then the rest. */
    for (pass = 0; pass < 2; pass++)
        for (i = 0; i < count; i++) {
            uint8_t *slot = table + i * TS2_PAK_SLOT_SIZE;
            uint32_t name_va;

            memcpy(&name_va, slot + TS2_PAK_SLOT_NAME, sizeof name_va);
            if (ts2_pak_is_override(name_va) != (pass == 0))
                continue;
            if (pass == 0 && i != out)
                front++;
            memcpy(moved + out * TS2_PAK_SLOT_SIZE, slot, TS2_PAK_SLOT_SIZE);
            out++;
        }
    if (!front)
        return;   /* none mounted, or already first */
    memcpy(table, moved, (size_t)count * TS2_PAK_SLOT_SIZE);
    {
        static int said;
        if (!said) {
            said = 1;
            fprintf(stderr, "[TS2-PAK] an override archive (data/xbt.pak, xbob.pak or "
                            "xbsound.pak) is mounted; it now comes before the level's "
                            "archives, so its files win\n");
            fflush(stderr);
        }
    }
}

extern void sub_000865C0_gen(void);
void sub_000865C0(void)
{
    sub_000865C0_gen();
    ts2_paks_overrides_first();
}
