/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The TFT's boot splash (decision TS-1 to TS-4): the "splash" screen (screen_renderer.c) is drawn
 * as soon as the display is up, and the screens that arrive meanwhile wait, the latest of them
 * alone, until the splash has been up for its time. A screen that comes later than that finds the
 * splash still there and replaces it at once. So the splash stays for the longer of its time and
 * the wait for the first screen. Nothing blocks: the display task offers every screen here and
 * asks tft_splash_due() each loop. The millisecond clock may wrap.
 */
#ifndef ATALAIA_TFT_SPLASH_H
#define ATALAIA_TFT_SPLASH_H

#include <stdbool.h>
#include <stdint.h>

#include "screen_types.h"

#ifndef CONFIG_ATALAIA_TFT_SPLASH_MS
#define CONFIG_ATALAIA_TFT_SPLASH_MS 2500
#endif

typedef struct {
    bool on;        /* the splash is on the screen */
    uint32_t until; /* when its time is over */
    bool pending;   /* a screen waits */
    screen_update_t screen;
} tft_splash_t;

/* The splash was drawn at now_ms. hold_ms 0: none (every screen goes straight through). */
void tft_splash_begin(tft_splash_t *s, uint32_t now_ms, uint32_t hold_ms);

/* A screen arrived. True: the splash holds it (the latest is kept); false: draw it now (the
 * splash is over, or there never was one). */
bool tft_splash_offer(tft_splash_t *s, const char *tmpl, const char *data_json, uint32_t now_ms);

/* Each loop: true once, when the splash's time is over and a screen waits: out is to be drawn. */
bool tft_splash_due(tft_splash_t *s, uint32_t now_ms, screen_update_t *out);

/* True while the splash is on the screen. */
bool tft_splash_active(const tft_splash_t *s);

#endif
