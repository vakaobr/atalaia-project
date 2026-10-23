/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The on-board OLED's status view: a compact mirror of the main screen on
 * the Heltec V4's 128x64 monochrome OLED, so a bare board (no TFT) still
 * shows the PIN, the picker and the game, and a full box has a status line
 * for staff. Every screen update the TFT gets is mapped to three lines: a
 * header bar (mode or menu), one big value (countdown, phase, choice) and
 * a footer (team, hint or message), with a progress bar beside it while
 * a team holds its button (data "progress", or Bomb's "defuse"). The
 * captured screen also shows the team's points in the header and, from the
 * game's clock, how long it has held the zone in the footer.
 *
 * oled_text_for() is the mapping, plain C for the host tests; the LVGL part
 * (ATALAIA_SCREEN_LVGL) draws it on a second LVGL display, packed to one
 * bit per pixel by oled_pack() for the SSD1306.
 */
#ifndef ATALAIA_OLED_VIEW_H
#define ATALAIA_OLED_VIEW_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "hal_oled.h"

typedef struct {
    char head[32];       /* header bar, left: the mode or the menu */
    char head_right[24]; /* header bar, right: a page, a clock or "" */
    char big[48];        /* the big middle line */
    char foot[48];       /* the footer line */
    int bar;             /* 0-100: a hold's progress bar beside the footer; -1 none */
    long since;          /* captured: the game time (s) the team took the zone; -1 none */
} oled_text_t;

/* The header for a mode, from the "@mode" screen message's data,
 * "<mode id> <params>": "org.atalaia.bomb {...}" -> "BOMB". */
void oled_mode_title(const char *mode_msg, char *out, size_t out_sz);

/*
 * Maps one screen update (the TFT's template name and JSON data) to the
 * OLED's lines. mode_title is the running mode's header ("" before a game).
 * Returns false when the message changes nothing on the OLED ("@mode").
 */
bool oled_text_for(const char *mode_title, const char *template_name, const char *data_json,
                   oled_text_t *out);

/*
 * The captured screen's footer from the game time (game_s, seconds): how long
 * the team has held the zone ("held for 2:15"), when t has a capture time and
 * no hold bar. Returns true when the footer changed.
 */
bool oled_text_held(oled_text_t *t, long game_s);

/* Packs a 128x64 RGB565 frame into SSD1306 pages: a pixel is lit when its
 * brightness is at least half. */
void oled_pack(const uint16_t *rgb565, uint8_t fb[HAL_OLED_FB_SIZE]);

#if ATALAIA_SCREEN_LVGL
#include "lvgl.h"

/* Shows the boot splash (tower, name, version) on scr. Screens that
 * arrive within hold_ms wait until oled_view_poll() passes that time. */
void oled_view_splash(lv_obj_t *scr, const char *version, uint32_t now_ms, uint32_t hold_ms);

/* Takes a screen update (every message the TFT gets, "@mode" included). */
void oled_view_handle(lv_obj_t *scr, const char *template_name, const char *data_json,
                      uint32_t now_ms);

/* Shows the latest screen once the splash time is over; ticks the captured
 * screen's held time. */
void oled_view_poll(lv_obj_t *scr, uint32_t now_ms);

/* The game's clock, in milliseconds of game time (read from the display
 * task; NULL: none). While a captured screen with a capture time shows, the
 * footer counts how long the team has held the zone, redrawn once a second
 * by oled_view_poll(). */
void oled_view_set_game_clock(uint32_t (*game_ms)(void));

/* Draws t on scr (the three-line layout; builds it on first use). */
void oled_view_draw(lv_obj_t *scr, const oled_text_t *t);
#endif

#endif /* ATALAIA_OLED_VIEW_H */
