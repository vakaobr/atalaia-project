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
 * game's clock, how long it has held the zone in the footer. On a zone's
 * screens (neutral, captured) the box draws that bar itself from its own
 * buttons when the mode sends none (decision BN-26).
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
    bool zone;           /* neutral or captured: the box's own hold bar may show (BN-26) */
    char owner[32];      /* captured: the holding team, as the mode named it */
} oled_text_t;

/* A team button held down, and for how long (ms). */
#define OLED_HOLDS_MAX 4
typedef struct {
    char team[24];
    uint32_t ms;
} oled_hold_t;

/* The header for a mode, from the "@mode" screen message's data,
 * "<mode id> <params>": "org.atalaia.bomb {...}" -> "BOMB". */
void oled_mode_title(const char *mode_msg, char *out, size_t out_sz);

/* The time a team holds its button to take a zone, from the same "@mode"
 * data: the params' capture_hold_ms (the built-in modes), else hold_ms;
 * 0 when the mode has neither. */
uint32_t oled_mode_hold_ms(const char *mode_msg);
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

/*
 * The game timer's time left (ADR-P1-3): left_s seconds as a clock in the header's right, when
 * the screen has nothing there (the captured screen's points keep it) and left_s is not
 * negative (-1: no timed game runs). Returns true when it changed the header.
 */
bool oled_text_timer(oled_text_t *t, long left_s);

/*
 * A zone's screen while a team holds its button (BN-26): the bar, filled by
 * how long the team has held it out of hold_ms (in steps of a hold event,
 * 250 ms), and that team's name beside it in the footer. Only on neutral and
 * captured, when the mode sent no bar of its own, never for the team that
 * already holds the zone, and not without a hold time; with several buttons
 * down, the one held longest. Apply it before oled_text_held(). Returns true
 * when it drew the bar.
 */
bool oled_text_hold(oled_text_t *t, const oled_hold_t *holds, int n, uint32_t hold_ms);

/*
 * The firmware's version as the splashes (box and modem) show it, in two lines that fit the
 * OLED (decision FV-8): line1 the version without its commit, line2 the commit.
 * "0.4.0-dev.12+gabc1234" -> "v0.4.0-dev.12" and "abc1234"; ".dirty" (a tree with changes)
 * -> "abc1234*"; a release tree past its tag, "0.3.0+5.gabc1234" -> "v0.3.0+5" and
 * "abc1234"; a release, "0.3.0" -> "v0.3.0" and ""; other build metadata (a bench's
 * --fw-version=0.3.0+bench) goes on line2 as it is. NULL or "" gives two empty lines. Both
 * are cut to their buffers, always terminated.
 */
void oled_version_lines(const char *version, char *line1, size_t n1, char *line2, size_t n2);

/* Packs a 128x64 RGB565 frame into SSD1306 pages: a pixel is lit when its
 * brightness is at least half. */
void oled_pack(const uint16_t *rgb565, uint8_t fb[HAL_OLED_FB_SIZE]);

#if ATALAIA_SCREEN_LVGL
#include "lvgl.h"
#include "oled_logo.h"

/* Shows the boot splash (tower, name, version) on scr: version is the firmware's whole version
 * (esp_app_desc_t), shown as oled_version_lines() splits it. Screens that arrive within
 * hold_ms wait until oled_view_poll() passes that time. */
void oled_view_splash(lv_obj_t *scr, const char *version, uint32_t now_ms, uint32_t hold_ms);

/* The splashes' layout (box and modem): the tower 2 pixels from the left, the text 4 past it. */
#define OLED_SPLASH_LOGO_X 2
#define OLED_SPLASH_TEXT_X (OLED_SPLASH_LOGO_X + OLED_LOGO_W + 4)

/* line1 of oled_version_lines() as it fits max_w pixels in font: as it is, else without its
 * leading "v" (the splash's label ends what still does not fit in "..."). */
const char *oled_version_fit(const char *line1, const lv_font_t *font, int32_t max_w);

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

/* The box's team buttons (read from the display task; NULL: none): fills
 * holds with the buttons held down now, returns how many (at most max).
 * oled_view_poll() draws a zone's hold bar from them (oled_text_hold). */
void oled_view_set_hold_reader(int (*read)(oled_hold_t *holds, int max));

/* The game timer's seconds left for the header's right (read from the display task; NULL: none;
 * the reader returns -1 when no timed game runs): oled_text_timer(), redrawn once a second. */
void oled_view_set_timer_reader(long (*left_s)(void));

/* Draws t on scr (the three-line layout; builds it on first use). */
void oled_view_draw(lv_obj_t *scr, const oled_text_t *t);
#endif

#endif /* ATALAIA_OLED_VIEW_H */
