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

/* Reset the renderer state (for tests). */
void screen_renderer_reset(void);

/* Test inspection: last rendered template and data. */
const char *screen_renderer_last_template(void);
const char *screen_renderer_last_data(void);
int screen_renderer_call_count(void);

#endif /* ATALAIA_SCREEN_RENDERER_H */
