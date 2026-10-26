/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Frames for the project page's animated game-mode pictures (tools/gen_mode_gifs.py): reads a
 * script of screen updates and draws each on the Field Box's TFT (320x240) and on its OLED
 * (128x64), through the same LVGL 9.2.2 build, the same renderer (screen_renderer.c, with the
 * modes' screen templates built in) and the same OLED view (oled_view.c) as the device and as the
 * screen reference tests (test_screens.c, test_oled_screens.c). Nothing here is a mock-up.
 *
 *   mode_gif_frames <script> <frames.bin>
 *
 * The script is text, one line per frame, fields separated by a tab ("-" is none):
 *
 *   RESET                                   forget the screens shown (a new picture)
 *   lang  mode  tft_template  tft_data  oled_template  oled_data  game_ms  hold_team  hold_ms
 *
 * lang is "en" for English (the box with no language), "pt", "de" or "zh-tw" (the box's language,
 * box_text.h); mode is the "@mode" message ("<mode id> <params JSON>") sent when it changes; the
 * data are JSON as the modes send them; game_ms is the game's clock the OLED's held time counts
 * from; a team and hold_ms put a finger on that team's button (the OLED's hold bar).
 *
 * frames.bin holds, for each frame, the TFT's 320x240 pixels as RGB (3 bytes each) and then the
 * OLED's 128x64 pixels (1 byte each, 255 lit, 0 dark).
 */
#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "box_text.h"
#include "lvgl.h"
#include "oled_view.h"
#include "screen_renderer.h"
#include "screen_template.h"
#include "test_display.h"

#define OW           HAL_OLED_WIDTH
#define OH           HAL_OLED_HEIGHT
#define LINE_MAX_LEN 4096
#define FIELDS       9

_Alignas(64) static uint8_t oled_buffer[OW * OH * 2];
static lv_display_t *oled_display;
static lv_display_t *tft_display;
static uint32_t oled_ms;
static uint32_t game_ms;
static oled_hold_t hold;
static int hold_count;

static uint32_t tick_cb(void)
{
    return oled_ms;
}

static void flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    (void)area;
    (void)px_map;
    lv_display_flush_ready(disp);
}

static uint32_t game_clock(void)
{
    return game_ms;
}

static int hold_reader(oled_hold_t *holds, int max)
{
    if (hold_count > max) return max;
    if (hold_count) holds[0] = hold;
    return hold_count;
}

static int split(char *line, char **fields)
{
    int n = 0;
    char *p = line;
    while (n < FIELDS) {
        fields[n++] = p;
        char *tab = strchr(p, '\t');
        if (!tab) break;
        *tab = '\0';
        p = tab + 1;
    }
    return n;
}

static const char *none(const char *s)
{
    return strcmp(s, "-") == 0 ? NULL : s;
}

/* What the OLED panel shows: lit pixels 255, the rest 0, as test_oled_screens.c. */
static void write_oled(FILE *out, lv_obj_t *scr)
{
    static uint8_t fb[HAL_OLED_FB_SIZE];
    static uint8_t px[OW * OH];
    lv_obj_invalidate(scr);
    lv_refr_now(oled_display);
    oled_pack((const uint16_t *)oled_buffer, fb);
    for (int y = 0; y < OH; y++) {
        for (int x = 0; x < OW; x++)
            px[y * OW + x] = (fb[(y / 8) * OW + x] >> (y % 8)) & 1 ? 255 : 0;
    }
    fwrite(px, 1, sizeof(px), out);
}

int main(int argc, char **argv)
{
    if (argc != 3) {
        fprintf(stderr, "usage: mode_gif_frames <script> <frames.bin>\n");
        return 2;
    }
    FILE *in = fopen(argv[1], "r");
    FILE *out = fopen(argv[2], "wb");
    if (!in || !out) {
        fprintf(stderr, "mode_gif_frames: cannot open %s\n", in ? argv[2] : argv[1]);
        return 2;
    }

    test_display_init(); /* the TFT: 320x240, the default display */
    tft_display = lv_display_get_default();
    lv_tick_set_cb(tick_cb);
    oled_display = lv_display_create(OW, OH);
    lv_display_set_color_format(oled_display, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(oled_display, oled_buffer, NULL, sizeof(oled_buffer),
                           LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(oled_display, flush_cb);
    oled_view_set_game_clock(game_clock);
    oled_view_set_hold_reader(hold_reader);

    static char line[LINE_MAX_LEN];
    static char mode_shown[LINE_MAX_LEN];
    static uint8_t rgb[TEST_DISPLAY_W * TEST_DISPLAY_H * 3];
    int frames = 0, lineno = 0;
    while (fgets(line, sizeof(line), in)) {
        lineno++;
        size_t len = strlen(line);
        while (len && (line[len - 1] == '\n' || line[len - 1] == '\r')) line[--len] = '\0';
        if (!len) continue;
        if (strcmp(line, "RESET") == 0) {
            lv_display_set_default(tft_display);
            screen_renderer_reset();
            mode_shown[0] = '\0';
            continue;
        }
        char *f[FIELDS];
        if (split(line, f) != FIELDS) {
            fprintf(stderr, "mode_gif_frames: line %d has not %d fields\n", lineno, FIELDS);
            return 1;
        }
        box_lang_set_code(strcmp(f[0], "en") == 0 ? "" : f[0]);
        game_ms = (uint32_t)strtoul(f[6], NULL, 10);
        hold_count = none(f[7]) != NULL;
        if (hold_count) {
            snprintf(hold.team, sizeof(hold.team), "%s", f[7]);
            hold.ms = (uint32_t)strtoul(f[8], NULL, 10);
        }
        const char *mode = none(f[1]);

        /* The TFT. */
        lv_display_set_default(tft_display);
        if (mode && strcmp(mode, mode_shown) != 0) {
            screen_render(SCREEN_MODE_MESSAGE, mode);
            snprintf(mode_shown, sizeof(mode_shown), "%s", mode);
        }
        if (none(f[2]) && !screen_render(f[2], f[3])) {
            fprintf(stderr, "mode_gif_frames: line %d: template %s not recognised\n", lineno, f[2]);
            return 1;
        }
        test_display_render();
        test_display_rgb888(rgb);
        fwrite(rgb, 1, sizeof(rgb), out);

        /* The OLED. */
        lv_display_set_default(oled_display);
        lv_obj_t *scr = lv_screen_active();
        oled_ms += 10000;
        if (mode) oled_view_handle(scr, "@mode", mode, oled_ms);
        if (none(f[4])) oled_view_handle(scr, f[4], f[5], oled_ms);
        oled_view_poll(scr, oled_ms);
        write_oled(out, scr);
        frames++;
    }
    fclose(in);
    if (fclose(out) != 0) return 1;
    printf("mode_gif_frames: %d frames\n", frames);
    return 0;
}
