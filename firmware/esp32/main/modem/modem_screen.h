/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The USB radio modem's on-board OLED (128x64): a header bar with the
 * Atalaia tower and "MODEM MODE", then six 16-character lines (LVGL's
 * 8-pixel unscii font) a GM can read at a glance:
 *
 *   LINK         OK     host frames within the link timeout (DOWN, waiting)
 *   GAME       4660     configured for a game (IDLE no game / measuring)
 *   CH  869.525 MHz     the channel the radio is on
 *   TX 1234  fail 0     packets sent, and TX failures
 *   RX 5678  auth 0     packets forwarded, and MIC failures
 *   DUTY 359.9s left    the duty-cycle budget left
 *
 * A radio fault (no SX1262 at boot) replaces the last four lines with
 * "RADIO FAULT" and the reason. A line that needs attention (link down, a
 * fault, no duty-cycle budget left) is drawn inverted.
 *
 * modem_screen_state() and modem_screen_text() are plain C for the host
 * tests; the LVGL part (ATALAIA_SCREEN_LVGL) draws the text and the splash.
 */
#ifndef ATALAIA_MODEM_SCREEN_H
#define ATALAIA_MODEM_SCREEN_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "modem.h"

#define MODEM_SCREEN_LINES 6
#define MODEM_SCREEN_COLS  16

typedef enum {
    MODEM_LINK_WAITING = 0, /* no frame from the host since boot */
    MODEM_LINK_UP,          /* a frame within the link timeout */
    MODEM_LINK_DOWN,        /* frames came, then stopped for longer than the timeout */
} modem_link_t;

/* What the screen shows: a copy, so the display never reads the modem. */
typedef struct {
    modem_link_t link;
    bool configured;
    bool measuring;
    uint16_t game_id;
    uint32_t channel_hz;
    uint32_t rx, rx_auth_fail, tx, tx_fail; /* the STATUS frame's counters */
    bool radio_ok;
    uint32_t duty_ms; /* duty-cycle budget left */
    char fault[40];   /* why the radio is missing ("" when radio_ok) */
} modem_screen_state_t;

typedef struct {
    char line[MODEM_SCREEN_LINES][MODEM_SCREEN_COLS + 1];
    bool inverted[MODEM_SCREEN_LINES];
} modem_screen_text_t;

/*
 * The state of m at now_ms. A link is up while the last host frame is at
 * most link_timeout_ms old. idle_channel_hz is the radio's boot channel,
 * shown until the controller sets one; duty_ms the budget left; fault why
 * the radio is missing (NULL or "" for unknown).
 */
void modem_screen_state(const modem_t *m, uint32_t now_ms, uint32_t link_timeout_ms,
                        uint32_t idle_channel_hz, uint32_t duty_ms, const char *fault,
                        modem_screen_state_t *out);

/* The six lines for s. */
void modem_screen_text(const modem_screen_state_t *s, modem_screen_text_t *out);

/* n in at most width characters: 1234, then 12k, 4M, 4G. */
void modem_screen_count(uint32_t n, int width, char *out, size_t out_sz);

#if ATALAIA_SCREEN_LVGL
#include "lvgl.h"

/* The boot splash: the tower, "ATALAIA", "MODEM MODE" and the version. */
void modem_screen_splash(lv_obj_t *scr, const char *version);

/* Draws t on scr (builds the layout on first use, or after the splash). */
void modem_screen_draw(lv_obj_t *scr, const modem_screen_text_t *t);
#endif

#endif /* ATALAIA_MODEM_SCREEN_H */
