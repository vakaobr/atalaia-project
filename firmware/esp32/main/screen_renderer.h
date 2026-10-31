/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Screen template renderer. Maps template names to C functions that
 * build LVGL widget trees (320x240). The device and the host tests build
 * the same trees; every call is also recorded for test inspection.
 *
 * Templates and their data (all fields optional):
 *   standby        {"arm": team}                 the bomb waits to be armed
 *   countdown      {"left": s, "team": team}     time left, red under 10 s
 *   defused        {"team": team}                in the winning team's colour
 *   exploded       {"team": team}                in the winning team's colour
 *   final_score    {"owner": team}               the game is over
 *   paused         {}
 *   status         {"title", "mode", "timer_s", "battery", "version"}
 *   pin_entry      {"digits": n, "error": bool}  admin PIN prompt (shell)
 *   preset_select  {"presets": [label...], "selected": n,  one page of at most nine (shell);
 *                   "page": p, "pages": n}       "page"/"pages" only with more than nine games
 *   timer_adjust   {"timer_s": s}                game length, 0 = no limit (shell)
 *   start_confirm  {"label": text, "timer_s": s} (shell)
 *   wifi_setup     {"ssid": text}                first-time setup (shell)
 */
#ifndef ATALAIA_SCREEN_RENDERER_H
#define ATALAIA_SCREEN_RENDERER_H

#include <stdbool.h>

#include <stdint.h>

#include "oled_view.h"
#include "screen_types.h"

/*
 * Render a screen template by name: builds the template's widgets on
 * the active LVGL screen when the template changes, then patches the
 * data in. Without an LVGL display (or without ATALAIA_SCREEN_LVGL)
 * it only records the call for test inspection.
 *
 * Returns true if the template was recognised.
 */
bool screen_render(const char *template_name, const char *data_json);

/*
 * The game timer's bar (ADR-P1-3): a strip along the bottom edge of the display, drawn over
 * every screen, filled by the share of the game left (red in the last minute). The shell
 * calls it from the display task once a second while a timed stand-alone game runs;
 * total_s <= 0 or left_s < 0 hides it (no timer, no game, game over). A call that changes
 * nothing draws nothing.
 */
void screen_timer_bar(long left_s, long total_s);

/*
 * What the box adds to the mode's screens on the TFT (decision TZ-1 to TZ-5): game_ms is the
 * game's clock in ms (NULL: none), holds fills the team buttons held down now (as for
 * oled_view_set_hold_reader; NULL: none). Read from the display task.
 *  - a zone's screen (neutral, captured) that has no bar of its own shows the capture's hold bar
 *    and the team holding, from the mode's hold time, as the OLED does (oled_text_hold());
 *  - a template's data with "since" gets "held": the game seconds since then, so a captured
 *    screen can show "held {held|clock}" counting up;
 *  - under Domination, each team's points at this box (the last "points" its captured and final
 *    screens carried for it) in the top right, in team colours.
 */
void screen_set_overlay_readers(uint32_t (*game_ms)(void),
                                int (*holds)(oled_hold_t *holds, int max));

/* Called by the display task every loop: steps the hold bar and the held time (a second at a
 * time), changing only the widgets whose text or width changed. */
void screen_overlay_tick(void);

/* Test inspection: 1 and the points when the box has a total for the team at this box. */
int screen_overlay_total(const char *team, long *points);

/* Test inspection: the seconds the bar shows as left, -1 when it is hidden. */
long screen_timer_bar_left(void);

/* Reset the renderer state (for tests). */
void screen_renderer_reset(void);

/* Test inspection: last rendered template and data. */
const char *screen_renderer_last_template(void);
const char *screen_renderer_last_data(void);
int screen_renderer_call_count(void);

#endif /* ATALAIA_SCREEN_RENDERER_H */
