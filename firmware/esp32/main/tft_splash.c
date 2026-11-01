/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "tft_splash.h"

#include <stdio.h>

static bool before(uint32_t now, uint32_t until)
{
    return (int32_t)(now - until) < 0;
}

void tft_splash_begin(tft_splash_t *s, uint32_t now_ms, uint32_t hold_ms)
{
    s->pending = false;
    s->on = hold_ms > 0;
    s->until = now_ms + hold_ms;
}

bool tft_splash_offer(tft_splash_t *s, const char *tmpl, const char *data_json, uint32_t now_ms)
{
    if (s->on && before(now_ms, s->until)) {
        snprintf(s->screen.template_name, sizeof(s->screen.template_name), "%s", tmpl ? tmpl : "");
        snprintf(s->screen.data_json, sizeof(s->screen.data_json), "%s",
                 data_json ? data_json : "");
        s->pending = true;
        return true;
    }
    s->on = false;
    s->pending = false;
    return false;
}

bool tft_splash_due(tft_splash_t *s, uint32_t now_ms, screen_update_t *out)
{
    if (!s->on || before(now_ms, s->until)) return false;
    if (!s->pending) return false; /* nothing to show yet: the splash stays */
    s->on = false;
    s->pending = false;
    *out = s->screen;
    return true;
}

bool tft_splash_active(const tft_splash_t *s)
{
    return s->on;
}
