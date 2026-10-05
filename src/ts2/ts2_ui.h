/*
 * ts2_ui.h -- TimeSplitters 2: 2D placement in widescreen, shared between
 * the logic (src/overrides/ui_placement.c) and its table
 * (src/overrides/ui_placement_table.c).
 */
#ifndef TS2_UI_H
#define TS2_UI_H

#include <stdint.h>

enum { TS2_UI_AUTO = 0, TS2_UI_STRETCH, TS2_UI_CENTRE, TS2_UI_LEFT, TS2_UI_RIGHT,
       TS2_UI_SIDE };

typedef struct Ts2UiPlace { uint32_t site; int placement; } Ts2UiPlace;

/* Where each known call site's 2D goes; ends at site 0. */
extern const Ts2UiPlace k_ts2_ui_places[];
/* Entries in it, not counting the terminator. */
extern const int k_ts2_ui_place_count;

#endif /* TS2_UI_H */
