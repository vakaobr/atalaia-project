/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Screen template renderer. Maps template names to C functions that
 * build LVGL widget trees. On ESP32 these render to LVGL; in tests
 * they record calls without any LVGL dependency.
 */
#ifndef ATALAIA_SCREEN_RENDERER_H
#define ATALAIA_SCREEN_RENDERER_H

#include <stdbool.h>

#include "screen_types.h"

/*
 * Render a screen template by name. On ESP32 this creates/updates
 * LVGL widgets on the active screen. In stub builds it records
 * the call for test inspection.
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
