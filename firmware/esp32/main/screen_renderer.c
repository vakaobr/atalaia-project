/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Screen renderer implementation (ADR-P1-2): one C function pair per
 * template. build_*() creates the widget tree when the template changes;
 * update_*() patches the data into the existing widgets on every call,
 * so a countdown ticking once a second only changes its label text.
 *
 * Every build records the template name and data for test inspection.
 * With ATALAIA_SCREEN_LVGL (set by main/CMakeLists.txt on the device and
 * by test/CMakeLists.txt on the host) the same code also builds the LVGL
 * widgets, so the host reference images show exactly what the device
 * draws. The LVGL path is skipped until LVGL has a display, which keeps
 * the renderer usable before the display is up.
 *
 * Layout: 320x240 landscape (2.8" ILI9341/ST7789), fonts Montserrat 14,
 * 20, 28 and 48 (lvgl_conf/lv_conf.h).
 *
 * Declarative templates (ADR-P3-4) come first: when the running mode ships
 * a YAML template of the name (screen_template.h), it is drawn instead of
 * the C function here. The C functions stay as the fallback for modes
 * without one and for the shell's own screens.
 */
#include "screen_renderer.h"

#include <stdio.h>
#include <string.h>

#include "box_text.h"
#include "screen_json.h"
#include "screen_template.h"

static char last_template[SCREEN_TEMPLATE_MAX];
static char last_data[SCREEN_DATA_MAX];
static int call_count;
static bool timer_bar_on;
static long timer_bar_left = -1;

/* Known templates. Mode templates first, then the shell's own screens. */
static const char *known_templates[] = {
    "standby",      "countdown",     "defused",    "exploded",   "final_score",
    "paused",       "neutral",       "captured",   "code_entry", "status",
    "pin_entry",    "preset_select", "waiting",    "playing",    "ready",
    "timer_adjust", "start_confirm", "wifi_setup", NULL,
};

/* ------------------------------------------------------------------ */
/* LVGL rendering                                                      */
/* ------------------------------------------------------------------ */

#if ATALAIA_SCREEN_LVGL

#include <stdlib.h>

#include "lvgl.h"

#define LIST_MAX      9
#define LIST_ITEM_MAX 40

/* ---- Colours, fonts and shared pieces ----------------------------- */

#define SCREEN_W 320
#define SCREEN_H 240

#define COLOR_BG     0x101418
#define COLOR_PANEL  0x222B35
#define COLOR_TEXT   0xFFFFFF
#define COLOR_MUTED  0x9AA5B1
#define COLOR_ACCENT 0xFFB300
#define COLOR_DANGER 0xE53935
#define COLOR_DARK   0x101418

#define HEADER_H 44

typedef struct {
    const char *name;
    uint32_t rgb;
} team_colour_t;

static const team_colour_t team_colours[] = {
    {"red", 0xE53935},    {"blue", 0x1E88E5},   {"green", 0x43A047},
    {"yellow", 0xFDD835}, {"orange", 0xFB8C00}, {"purple", 0x8E24AA},
};

static uint32_t team_rgb(const char *team)
{
    for (size_t i = 0; i < sizeof(team_colours) / sizeof(team_colours[0]); i++) {
        const char *a = team_colours[i].name;
        const char *b = team;
        while (*a && (*b | 0x20) == *a) {
            a++;
            b++;
        }
        if (*a == '\0' && *b == '\0') return team_colours[i].rgb;
    }
    return 0x78909C; /* an unknown team: neutral grey */
}

/* Dark text on light backgrounds (yellow), white text on the rest. */
static uint32_t text_on(uint32_t bg)
{
    uint32_t r = (bg >> 16) & 0xFF, g = (bg >> 8) & 0xFF, b = bg & 0xFF;
    return (r * 299 + g * 587 + b * 114) / 1000 > 160 ? COLOR_DARK : COLOR_TEXT;
}

static void upper(char *s)
{
    for (; *s; s++) {
        if (*s >= 'a' && *s <= 'z') *s = (char)(*s - 'a' + 'A');
    }
}

/* Widgets of the template on screen, filled by build_*() and patched by update_*(). */
#define SLOT_MAX 24
static lv_obj_t *slot[SLOT_MAX];
static char shown_template[SCREEN_TEMPLATE_MAX];

static void set_bg(lv_obj_t *obj, uint32_t rgb)
{
    lv_obj_set_style_bg_color(obj, lv_color_hex(rgb), 0);
    lv_obj_set_style_bg_opa(obj, LV_OPA_COVER, 0);
}

static lv_obj_t *label(lv_obj_t *parent, const lv_font_t *font, uint32_t rgb, int y)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(rgb), 0);
    lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(l, LV_ALIGN_CENTER, 0, y);
    lv_label_set_text(l, "");
    return l;
}

/* A plain rectangle without the theme's border, padding or shadow. */
static lv_obj_t *box(lv_obj_t *parent, int w, int h, uint32_t rgb)
{
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    lv_obj_set_size(o, w, h);
    set_bg(o, rgb);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    return o;
}

/* Header bar with a title; returns the title label. */
static lv_obj_t *header(lv_obj_t *scr, uint32_t bg)
{
    lv_obj_t *bar = box(scr, SCREEN_W, HEADER_H, bg);
    lv_obj_align(bar, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_t *title = lv_label_create(bar);
    lv_obj_set_style_text_font(title, &lv_font_atalaia_20, 0);
    lv_obj_set_style_text_color(title, lv_color_hex(text_on(bg)), 0);
    lv_obj_set_style_text_letter_space(title, 2, 0);
    lv_obj_center(title);
    return title;
}

static lv_obj_t *footer(lv_obj_t *scr, const char *hint)
{
    lv_obj_t *l = lv_label_create(scr);
    lv_obj_set_style_text_font(l, &lv_font_atalaia_14, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(COLOR_MUTED), 0);
    lv_obj_align(l, LV_ALIGN_BOTTOM_MID, 0, -10);
    lv_label_set_text(l, hint);
    return l;
}

/* A big label in a smaller font when its text is wider than w (a longer word in Portuguese). */
static void fit(lv_obj_t *l, int w)
{
    const lv_font_t *font = lv_obj_get_style_text_font(l, 0);
    lv_point_t size;
    lv_text_get_size(&size, lv_label_get_text(l), font, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
    if (size.x > w && font == &lv_font_atalaia_48) {
        lv_obj_set_style_text_font(l, &lv_font_atalaia_28, 0);
    }
}

/* A label cut to one line with "..." when the text is wider than w. */
static void one_line(lv_obj_t *l, int w)
{
    lv_obj_set_width(l, w);
    lv_obj_set_height(l, lv_font_get_line_height(lv_obj_get_style_text_font(l, 0)));
    lv_label_set_long_mode(l, LV_LABEL_LONG_DOT);
}

static void show(lv_obj_t *obj, bool visible)
{
    if (visible) {
        lv_obj_remove_flag(obj, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(obj, LV_OBJ_FLAG_HIDDEN);
    }
}

static void set_colour(lv_obj_t *l, uint32_t rgb)
{
    lv_obj_set_style_text_color(l, lv_color_hex(rgb), 0);
}

/* Formats seconds as M:SS, or H:MM:SS from one hour. */
static void format_clock(long s, char *buf, size_t sz)
{
    if (s < 0) s = 0;
    if (s >= 3600) {
        snprintf(buf, sz, "%ld:%02ld:%02ld", s / 3600, (s / 60) % 60, s % 60);
    } else {
        snprintf(buf, sz, "%ld:%02ld", s / 60, s % 60);
    }
}

static void format_minutes(long s, char *buf, size_t sz)
{
    if (s <= 0) {
        snprintf(buf, sz, "%s", box_text(TX_NO_LIMIT));
    } else if (s % 60 == 0) {
        snprintf(buf, sz, "%ld min", s / 60);
    } else {
        snprintf(buf, sz, "%ld min %02ld s", s / 60, s % 60);
    }
}

/* ---- standby: the bomb waits to be armed ----------------------------- */

static void build_standby(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    lv_label_set_text(header(scr, COLOR_PANEL), box_text(TX_READY_UP));
    slot[0] = label(scr, &lv_font_atalaia_20, COLOR_MUTED, -42);
    slot[1] = label(scr, &lv_font_atalaia_48, COLOR_TEXT, 4);
    slot[2] = box(scr, 180, 8, COLOR_PANEL);
    lv_obj_set_style_radius(slot[2], 4, 0);
    lv_obj_align(slot[2], LV_ALIGN_CENTER, 0, 46);
    footer(scr, box_text(TX_BOMB_NOT_ARMED));
}

static void update_standby(const char *data)
{
    char team[SCREEN_TEMPLATE_MAX];
    bool has_team = screen_json_str(data, "arm", team, sizeof(team)) && team[0];
    lv_label_set_text(slot[0], box_text(has_team ? TX_HOLD_TO_ARM : TX_WAITING));
    if (has_team) {
        uint32_t rgb = team_rgb(team);
        upper(team);
        lv_label_set_text(slot[1], team);
        set_colour(slot[1], rgb);
        set_bg(slot[2], rgb);
    }
    show(slot[1], has_team);
    show(slot[2], has_team);
}

/* ---- countdown: seconds left until something happens ---------------- */

static void build_countdown(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    lv_label_set_text(header(scr, COLOR_DANGER), box_text(TX_ARMED_UP));
    slot[0] = label(scr, &lv_font_atalaia_48, COLOR_TEXT, -8);
    slot[1] = label(scr, &lv_font_atalaia_20, COLOR_MUTED, 42);
    lv_label_set_text(slot[1], box_text(TX_UNTIL_DETONATION));
    slot[2] = footer(scr, "");
}

static void update_countdown(const char *data)
{
    long left = 0;
    screen_json_int(data, "left", &left);
    char buf[24];
    format_clock(left, buf, sizeof(buf));
    lv_label_set_text(slot[0], buf);
    set_colour(slot[0], left <= 10 ? COLOR_DANGER : COLOR_TEXT);

    char team[SCREEN_TEMPLATE_MAX];
    if (screen_json_str(data, "team", team, sizeof(team)) && team[0]) {
        uint32_t rgb = team_rgb(team);
        upper(team);
        char line[64];
        snprintf(line, sizeof(line), box_text(TX_ARMED_BY), team);
        lv_label_set_text(slot[2], line);
        set_colour(slot[2], rgb);
    } else {
        lv_label_set_text(slot[2], "");
    }
}

/* ---- defused / exploded: the round result, in the winner's colour ---- */

static void build_result(lv_obj_t *scr, const char *symbol, const char *title)
{
    slot[0] = label(scr, &lv_font_atalaia_48, COLOR_TEXT, -62);
    lv_label_set_text(slot[0], symbol);
    slot[1] = label(scr, &lv_font_atalaia_48, COLOR_TEXT, 0);
    lv_label_set_text(slot[1], title);
    fit(slot[1], SCREEN_W - 16);
    slot[2] = label(scr, &lv_font_atalaia_28, COLOR_TEXT, 58);
}

static void update_result(const char *data)
{
    char team[SCREEN_TEMPLATE_MAX];
    bool has_team = screen_json_str(data, "team", team, sizeof(team)) && team[0];
    uint32_t bg = has_team ? team_rgb(team) : COLOR_PANEL;
    uint32_t fg = text_on(bg);
    set_bg(lv_screen_active(), bg);
    for (int i = 0; i < 3; i++) set_colour(slot[i], fg);
    if (has_team) {
        upper(team);
        char line[64];
        snprintf(line, sizeof(line), box_text(TX_TEAM_WINS), team);
        lv_label_set_text(slot[2], line);
    }
    show(slot[2], has_team);
}

static void build_defused(lv_obj_t *scr)
{
    build_result(scr, LV_SYMBOL_OK, box_text(TX_DEFUSED_UP));
}

static void build_exploded(lv_obj_t *scr)
{
    build_result(scr, LV_SYMBOL_WARNING, box_text(TX_EXPLODED_UP));
}

/* ---- final_score: the game is over ----------------------------------- */

static void build_final_score(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    lv_label_set_text(header(scr, COLOR_PANEL), box_text(TX_GAME_OVER_UP));
    slot[0] = label(scr, &lv_font_atalaia_20, COLOR_MUTED, -36);
    slot[1] = label(scr, &lv_font_atalaia_48, COLOR_TEXT, 10);
    footer(scr, box_text(TX_SCORES_FINAL));
}

static void update_final_score(const char *data)
{
    char owner[SCREEN_TEMPLATE_MAX];
    bool has_owner = screen_json_str(data, "owner", owner, sizeof(owner)) && owner[0];
    lv_label_set_text(slot[0], box_text(has_owner ? TX_ZONE_HELD_BY : TX_NO_TEAM_HELD));
    lv_obj_align(slot[0], LV_ALIGN_CENTER, 0, has_owner ? -36 : 0);
    if (has_owner) {
        set_colour(slot[1], team_rgb(owner));
        upper(owner);
        lv_label_set_text(slot[1], owner);
    }
    show(slot[1], has_owner);
}

/* ---- paused ------------------------------------------------------------ */

static void build_paused(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    slot[0] = label(scr, &lv_font_atalaia_48, COLOR_ACCENT, -52);
    lv_label_set_text(slot[0], LV_SYMBOL_PAUSE);
    slot[1] = label(scr, &lv_font_atalaia_48, COLOR_TEXT, 8);
    lv_label_set_text(slot[1], box_text(TX_PAUSED_UP));
    slot[2] = label(scr, &lv_font_atalaia_20, COLOR_MUTED, 60);
    lv_label_set_text(slot[2], box_text(TX_WAIT_GM));
}

static void update_paused(const char *data)
{
    (void)data;
}

/* ---- neutral, captured: a zone nobody holds, a zone a team holds (decision BN-11) ---- */
/*
 * neutral: data hold_s (optional: the seconds to hold). captured: team, points (optional,
 * the team's on this box), since (optional, game seconds of the capture). The modes'
 * own templates of these names (Domination's) come first; these are for the rest.
 */

static void build_neutral(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    lv_label_set_text(header(scr, COLOR_PANEL), box_text(TX_ZONE_UP));
    slot[0] = label(scr, &lv_font_atalaia_48, COLOR_TEXT, -22);
    lv_label_set_text(slot[0], box_text(TX_NEUTRAL_UP));
    slot[1] = label(scr, &lv_font_atalaia_28, COLOR_ACCENT, 30);
    lv_label_set_text(slot[1], box_text(TX_HOLD_TO_CAPTURE));
    fit(slot[1], SCREEN_W - 16);
    slot[2] = label(scr, &lv_font_atalaia_20, COLOR_MUTED, 64);
    footer(scr, box_text(TX_NOBODY_HOLDS));
}

static void update_neutral(const char *data)
{
    long s = 0;
    char line[64];
    if (screen_json_int(data, "hold_s", &s) && s > 0) {
        snprintf(line, sizeof(line), box_text(TX_HOLD_FOR_S), s);
    } else {
        snprintf(line, sizeof(line), "%s", box_text(TX_TO_CAPTURE));
    }
    lv_label_set_text(slot[2], line);
    show(slot[2], line[0] != 0);
}

static void build_captured(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    slot[0] = box(scr, SCREEN_W, HEADER_H, COLOR_PANEL);
    lv_obj_align(slot[0], LV_ALIGN_TOP_MID, 0, 0);
    slot[1] = lv_label_create(slot[0]);
    lv_obj_set_style_text_font(slot[1], &lv_font_atalaia_20, 0);
    lv_obj_set_style_text_letter_space(slot[1], 2, 0);
    lv_obj_center(slot[1]);
    lv_label_set_text(slot[1], box_text(TX_ZONE_HELD_UP));
    slot[2] = label(scr, &lv_font_atalaia_48, COLOR_TEXT, -18);
    slot[3] = label(scr, &lv_font_atalaia_20, COLOR_MUTED, 34);
    footer(scr, box_text(TX_HOLD_TO_TAKE_OVER));
}

static void update_captured(const char *data)
{
    char team[SCREEN_TEMPLATE_MAX];
    if (!screen_json_str(data, "team", team, sizeof(team))) team[0] = '\0';
    uint32_t rgb = team_rgb(team);
    set_bg(slot[0], rgb);
    set_colour(slot[1], text_on(rgb));
    set_colour(slot[2], rgb);
    upper(team);
    lv_label_set_text(slot[2], team);
    long since = 0;
    bool has_since = screen_json_int(data, "since", &since);
    if (has_since) {
        char t[24], line[48];
        format_clock(since, t, sizeof(t));
        snprintf(line, sizeof(line), box_text(TX_HELD_SINCE), t);
        lv_label_set_text(slot[3], line);
    }
    show(slot[3], has_since);
}

/* ---- waiting: joined (or invited), the game has not started (decision BN-12) ---- */
/* Data: game (the game id), role, invited (true: joined by an invite over the radio). */

static void build_waiting(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    lv_label_set_text(header(scr, COLOR_PANEL), box_text(TX_WAITING_UP));
    slot[0] = label(scr, &lv_font_atalaia_48, COLOR_TEXT, -26);
    slot[1] = label(scr, &lv_font_atalaia_20, COLOR_ACCENT, 28);
    lv_label_set_text(slot[1], box_text(TX_NOT_STARTED));
    slot[2] = footer(scr, "");
}

static void update_waiting(const char *data)
{
    long game = 0;
    screen_json_int(data, "game", &game);
    char line[64];
    snprintf(line, sizeof(line), box_text(TX_GAME_N), (unsigned)game);
    lv_label_set_text(slot[0], line);
    char role[LIST_ITEM_MAX];
    if (screen_json_str(data, "role", role, sizeof(role)) && role[0]) {
        snprintf(line, sizeof(line),
                 box_text(screen_json_true(data, "invited") ? TX_INVITED_AS : TX_JOINED_AS), role);
        lv_label_set_text(slot[2], line);
    } else {
        lv_label_set_text(slot[2], "");
    }
}

/* ---- playing: a game started and the mode has drawn nothing yet (decision BN-13) ---- */
/* Data: game (the game id), role. */

static void build_playing(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    lv_label_set_text(header(scr, COLOR_ACCENT), box_text(TX_GAME_ON_UP));
    slot[0] = label(scr, &lv_font_atalaia_48, COLOR_TEXT, -12);
    slot[1] = footer(scr, "");
}

static void update_playing(const char *data)
{
    long game = 0;
    screen_json_int(data, "game", &game);
    char line[64];
    snprintf(line, sizeof(line), box_text(TX_GAME_N), (unsigned)game);
    lv_label_set_text(slot[0], line);
    char role[LIST_ITEM_MAX];
    if (!screen_json_str(data, "role", role, sizeof(role))) role[0] = '\0';
    lv_label_set_text(slot[1], role);
}

/* ---- ready: a free box, ready for the next game (decision BN-10) ------------ */
/* Data: picker (true: a key brings the game picker on this box). */

static void build_ready(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    lv_label_set_text(header(scr, COLOR_PANEL), box_text(TX_READY_UP));
    slot[0] = label(scr, &lv_font_atalaia_48, COLOR_TEXT, -8);
    lv_label_set_text(slot[0], box_text(TX_NEXT_GAME));
    fit(slot[0], SCREEN_W - 16);
    slot[1] = footer(scr, box_text(TX_KEY_FOR_PICKER));
}

static void update_ready(const char *data)
{
    show(slot[1], screen_json_true(data, "picker"));
}

/* ---- status: node information ------------------------------------------ */

#define STATUS_ROWS 4

static void build_status(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    slot[0] = header(scr, COLOR_PANEL);
    for (int i = 0; i < STATUS_ROWS; i++) {
        lv_obj_t *key = lv_label_create(scr);
        lv_obj_set_style_text_font(key, &lv_font_atalaia_20, 0);
        lv_obj_set_style_text_color(key, lv_color_hex(COLOR_MUTED), 0);
        lv_obj_align(key, LV_ALIGN_TOP_LEFT, 24, HEADER_H + 22 + i * 40);
        lv_obj_t *val = lv_label_create(scr);
        lv_obj_set_style_text_font(val, &lv_font_atalaia_20, 0);
        lv_obj_set_style_text_color(val, lv_color_hex(COLOR_TEXT), 0);
        lv_obj_set_style_text_align(val, LV_TEXT_ALIGN_RIGHT, 0);
        one_line(val, 170);
        lv_obj_align(val, LV_ALIGN_TOP_RIGHT, -24, HEADER_H + 22 + i * 40);
        slot[1 + 2 * i] = key;
        slot[2 + 2 * i] = val;
    }
}

static void update_status(const char *data)
{
    char title[SCREEN_TEMPLATE_MAX];
    if (!screen_json_str(data, "title", title, sizeof(title)) || !title[0]) {
        snprintf(title, sizeof(title), "%s", box_text(TX_STATUS_UP));
    }
    upper(title);
    lv_label_set_text(slot[0], title);

    char rows[STATUS_ROWS][2][LIST_ITEM_MAX];
    int n = 0;
    char buf[LIST_ITEM_MAX];
    long v;
    if (screen_json_str(data, "mode", buf, sizeof(buf)) && buf[0]) {
        snprintf(rows[n][0], LIST_ITEM_MAX, "%s", box_text(TX_ROW_GAME));
        snprintf(rows[n++][1], LIST_ITEM_MAX, "%s", buf);
    }
    /* Pairing (box_pair.c): the code to type in the console. */
    if (n < STATUS_ROWS && screen_json_str(data, "code", buf, sizeof(buf)) && buf[0]) {
        snprintf(rows[n][0], LIST_ITEM_MAX, "%s", box_text(TX_ROW_CODE));
        snprintf(rows[n++][1], LIST_ITEM_MAX, "%s", buf);
    }
    if (n < STATUS_ROWS && screen_json_str(data, "id", buf, sizeof(buf)) && buf[0]) {
        snprintf(rows[n][0], LIST_ITEM_MAX, "%s", box_text(TX_ROW_ID));
        snprintf(rows[n++][1], LIST_ITEM_MAX, "%s", buf);
    }
    if (n < STATUS_ROWS && screen_json_str(data, "pairing", buf, sizeof(buf)) && buf[0]) {
        snprintf(rows[n][0], LIST_ITEM_MAX, "%s", box_text(TX_ROW_PAIRING));
        snprintf(rows[n++][1], LIST_ITEM_MAX, "%s", buf);
    }
    /* Adoption (adoption.c): the field and its key's fingerprint. */
    if (n < STATUS_ROWS && screen_json_str(data, "field", buf, sizeof(buf)) && buf[0]) {
        snprintf(rows[n][0], LIST_ITEM_MAX, "%s", box_text(TX_ROW_FIELD));
        snprintf(rows[n++][1], LIST_ITEM_MAX, "%s", buf);
    }
    if (n < STATUS_ROWS && screen_json_str(data, "fingerprint", buf, sizeof(buf)) && buf[0]) {
        snprintf(rows[n][0], LIST_ITEM_MAX, "%s", box_text(TX_ROW_KEY));
        snprintf(rows[n++][1], LIST_ITEM_MAX, "%s", buf);
    }
    if (n < STATUS_ROWS && screen_json_int(data, "timer_s", &v)) {
        snprintf(rows[n][0], LIST_ITEM_MAX, "%s", box_text(TX_ROW_TIMER));
        format_minutes(v, rows[n++][1], LIST_ITEM_MAX);
    }
    if (n < STATUS_ROWS && screen_json_int(data, "battery", &v) && v >= 0) {
        snprintf(rows[n][0], LIST_ITEM_MAX, "%s", box_text(TX_ROW_BATTERY));
        snprintf(rows[n++][1], LIST_ITEM_MAX, "%ld%%", v);
    }
    if (n < STATUS_ROWS && screen_json_str(data, "version", buf, sizeof(buf)) && buf[0]) {
        snprintf(rows[n][0], LIST_ITEM_MAX, "%s", box_text(TX_ROW_FIRMWARE));
        snprintf(rows[n++][1], LIST_ITEM_MAX, "v%.30s", buf);
    }
    for (int i = 0; i < STATUS_ROWS; i++) {
        lv_label_set_text(slot[1 + 2 * i], i < n ? rows[i][0] : "");
        lv_label_set_text(slot[2 + 2 * i], i < n ? rows[i][1] : "");
    }
}

/* ---- pin_entry: the game master types the admin PIN ------------------ */

#define PIN_DOTS 8

static void build_pin_entry(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    lv_label_set_text(header(scr, COLOR_PANEL), box_text(TX_GAME_MASTER_UP));
    slot[0] = label(scr, &lv_font_atalaia_20, COLOR_TEXT, -46);
    lv_label_set_text(slot[0], box_text(TX_ENTER_ADMIN_PIN));
    for (int i = 0; i < PIN_DOTS; i++) {
        lv_obj_t *dot = box(scr, 22, 22, COLOR_BG);
        lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_border_width(dot, 2, 0);
        slot[1 + i] = dot;
    }
    slot[1 + PIN_DOTS] = label(scr, &lv_font_atalaia_20, COLOR_DANGER, 48);
    lv_label_set_text(slot[1 + PIN_DOTS], box_text(TX_WRONG_PIN_AGAIN));
    footer(scr, box_text(TX_KEYS_ENTER_DELETE));
}

static void update_pin_entry(const char *data)
{
    /* "prompt" replaces the line above the dots (adoption: "PIN to change field"). */
    char prompt[LIST_ITEM_MAX];
    if (!screen_json_str(data, "prompt", prompt, sizeof(prompt)) || !prompt[0]) {
        snprintf(prompt, sizeof(prompt), "%s", box_text(TX_ENTER_ADMIN_PIN));
    }
    lv_label_set_text(slot[0], prompt);
    long digits = 0;
    screen_json_int(data, "digits", &digits);
    if (digits < 0) digits = 0;
    if (digits > PIN_DOTS) digits = PIN_DOTS;
    int shown = digits > 4 ? (int)digits : 4;
    const int pitch = 34;
    int x0 = -(shown - 1) * pitch / 2;
    for (int i = 0; i < PIN_DOTS; i++) {
        lv_obj_t *dot = slot[1 + i];
        show(dot, i < shown);
        lv_obj_align(dot, LV_ALIGN_CENTER, x0 + i * pitch, 2);
        bool filled = i < digits;
        set_bg(dot, filled ? COLOR_ACCENT : COLOR_BG);
        lv_obj_set_style_border_color(dot, lv_color_hex(filled ? COLOR_ACCENT : COLOR_MUTED), 0);
    }
    /* The wait after wrong PINs, or no PIN set (decisions AD-28, AD-29): said in place of the
     * prompt and the error line. */
    long wait_min = 0;
    char line[64];
    if (screen_json_true(data, "no_pin")) {
        lv_label_set_text(slot[0], box_text(TX_NO_ADMIN_PIN));
        lv_label_set_text(slot[1 + PIN_DOTS], box_text(TX_SET_ADMIN_PIN));
        show(slot[1 + PIN_DOTS], true);
    } else if (screen_json_int(data, "locked_min", &wait_min) && wait_min > 0) {
        lv_label_set_text(slot[0], box_text(TX_PIN_LOCKED));
        snprintf(line, sizeof(line), box_text(TX_TRY_IN_MIN), (unsigned long)wait_min);
        lv_label_set_text(slot[1 + PIN_DOTS], line);
        show(slot[1 + PIN_DOTS], true);
    } else {
        lv_label_set_text(slot[1 + PIN_DOTS], box_text(TX_WRONG_PIN_AGAIN));
        show(slot[1 + PIN_DOTS], screen_json_true(data, "error"));
    }
}

/* ---- code_entry: a mode's code typed on the keypad -------------------- */
/*
 * Data: title (the header, e.g. ARM, DEFUSE, CODE), digits (dots shown),
 * left (optional seconds: the fuse while a defuse code is typed), message
 * (optional line under the dots), error (the message in red, else amber).
 * Used by Bomb's team codes and the Codes modifier.
 */

#define CODE_DOTS     8
#define CODE_TEXT_MAX 48

static void build_code_entry(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    slot[0] = header(scr, COLOR_PANEL);
    slot[1] = label(scr, &lv_font_atalaia_28, COLOR_DANGER, -42);
    for (int i = 0; i < CODE_DOTS; i++) {
        lv_obj_t *dot = box(scr, 22, 22, COLOR_BG);
        lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_border_width(dot, 2, 0);
        slot[2 + i] = dot;
    }
    slot[2 + CODE_DOTS] = label(scr, &lv_font_atalaia_20, COLOR_ACCENT, 50);
    one_line(slot[2 + CODE_DOTS], 300);
    footer(scr, box_text(TX_KEYS_ENTER_DELETE));
}

static void update_code_entry(const char *data)
{
    char text[CODE_TEXT_MAX];
    if (!screen_json_str(data, "title", text, sizeof(text)) || !text[0]) {
        snprintf(text, sizeof(text), "%s", box_text(TX_CODE_UP));
    }
    upper(text);
    lv_label_set_text(slot[0], box_text_title(text));

    long left = 0;
    bool has_left = screen_json_int(data, "left", &left);
    if (has_left) {
        format_clock(left, text, sizeof(text));
        lv_label_set_text(slot[1], text);
    }
    show(slot[1], has_left);

    long digits = 0;
    screen_json_int(data, "digits", &digits);
    if (digits < 0) digits = 0;
    if (digits > CODE_DOTS) digits = CODE_DOTS;
    int shown = digits > 4 ? (int)digits : 4;
    const int pitch = 34;
    int x0 = -(shown - 1) * pitch / 2;
    for (int i = 0; i < CODE_DOTS; i++) {
        lv_obj_t *dot = slot[2 + i];
        show(dot, i < shown);
        lv_obj_align(dot, LV_ALIGN_CENTER, x0 + i * pitch, has_left ? 4 : -14);
        bool filled = i < digits;
        set_bg(dot, filled ? COLOR_ACCENT : COLOR_BG);
        lv_obj_set_style_border_color(dot, lv_color_hex(filled ? COLOR_ACCENT : COLOR_MUTED), 0);
    }

    lv_obj_t *msg = slot[2 + CODE_DOTS];
    bool has_msg = screen_json_str(data, "message", text, sizeof(text)) && text[0];
    lv_label_set_text(msg, has_msg ? text : "");
    set_colour(msg, screen_json_true(data, "error") ? COLOR_DANGER : COLOR_ACCENT);
    show(msg, has_msg);
}

/* ---- preset_select: the list of stored games -------------------------- */

#define PRESET_ROWS  5
#define PRESET_ROW_H 28
#define PRESET_PITCH 32

static void build_preset_select(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    slot[3 * PRESET_ROWS + 1] = header(scr, COLOR_PANEL);
    lv_label_set_text(slot[3 * PRESET_ROWS + 1], box_text(TX_CHOOSE_GAME_UP));
    for (int i = 0; i < PRESET_ROWS; i++) {
        lv_obj_t *row = box(scr, SCREEN_W - 24, PRESET_ROW_H, COLOR_BG);
        lv_obj_set_style_radius(row, 6, 0);
        lv_obj_align(row, LV_ALIGN_TOP_MID, 0, HEADER_H + 6 + i * PRESET_PITCH);
        lv_obj_t *num = lv_label_create(row);
        lv_obj_set_style_text_font(num, &lv_font_atalaia_20, 0);
        lv_obj_align(num, LV_ALIGN_LEFT_MID, 12, 0);
        lv_obj_t *name = lv_label_create(row);
        lv_obj_set_style_text_font(name, &lv_font_atalaia_20, 0);
        one_line(name, SCREEN_W - 24 - 56);
        lv_obj_align(name, LV_ALIGN_LEFT_MID, 44, 0);
        slot[3 * i] = row;
        slot[3 * i + 1] = num;
        slot[3 * i + 2] = name;
    }
    slot[3 * PRESET_ROWS] = label(scr, &lv_font_atalaia_20, COLOR_MUTED, 0);
    lv_label_set_text(slot[3 * PRESET_ROWS], box_text(TX_NO_GAMES));
    slot[3 * PRESET_ROWS + 2] = footer(scr, box_text(TX_KEYS_CHOOSE));
}

static void update_preset_select(const char *data)
{
    char names[LIST_MAX][LIST_ITEM_MAX];
    int count = screen_json_str_list(data, "presets", names[0], LIST_ITEM_MAX, LIST_MAX);
    long selected = 1;
    screen_json_int(data, "selected", &selected);

    /* More than nine games: the list is one page of them, numbered 1-9, and 0 turns the page
     * (decision M2-1). Without "pages" the list is the only page. */
    long page = 1;
    long pages = 1;
    screen_json_int(data, "page", &page);
    screen_json_int(data, "pages", &pages);
    if (pages > 1) {
        char title[48];
        snprintf(title, sizeof(title), "%s  %ld/%ld", box_text(TX_CHOOSE_GAME_UP), page, pages);
        lv_label_set_text(slot[3 * PRESET_ROWS + 1], title);
        lv_label_set_text(slot[3 * PRESET_ROWS + 2], box_text(TX_KEYS_CHOOSE_PAGES));
    } else {
        lv_label_set_text(slot[3 * PRESET_ROWS + 1], box_text(TX_CHOOSE_GAME_UP));
        lv_label_set_text(slot[3 * PRESET_ROWS + 2], box_text(TX_KEYS_CHOOSE));
    }

    /* Scroll so the selected row stays visible. */
    int first = 0;
    if (count > PRESET_ROWS) {
        first = (int)selected - 1 - PRESET_ROWS / 2;
        if (first > count - PRESET_ROWS) first = count - PRESET_ROWS;
        if (first < 0) first = 0;
    }
    for (int i = 0; i < PRESET_ROWS; i++) {
        int idx = first + i;
        bool used = idx < count;
        show(slot[3 * i], used);
        if (!used) continue;
        bool sel = idx + 1 == selected;
        char num[12];
        snprintf(num, sizeof(num), "%d", idx + 1);
        lv_label_set_text(slot[3 * i + 1], num);
        lv_label_set_text(slot[3 * i + 2], names[idx]);
        set_bg(slot[3 * i], sel ? COLOR_ACCENT : COLOR_PANEL);
        set_colour(slot[3 * i + 1], sel ? COLOR_DARK : COLOR_ACCENT);
        set_colour(slot[3 * i + 2], sel ? COLOR_DARK : COLOR_TEXT);
    }
    show(slot[3 * PRESET_ROWS], count == 0);
}

/* ---- timer_adjust: the game length ------------------------------------ */

static void build_timer_adjust(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    lv_label_set_text(header(scr, COLOR_PANEL), box_text(TX_GAME_TIMER_UP));
    slot[0] = label(scr, &lv_font_atalaia_48, COLOR_TEXT, -12);
    slot[1] = label(scr, &lv_font_atalaia_20, COLOR_MUTED, 40);
    footer(scr, box_text(TX_KEYS_TIMER));
}

static void update_timer_adjust(const char *data)
{
    long s = 0;
    screen_json_int(data, "timer_s", &s);
    char buf[32];
    format_minutes(s, buf, sizeof(buf));
    lv_label_set_text(slot[0], buf);
    lv_label_set_text(slot[1], box_text(s > 0 ? TX_THEN_GAME_ENDS : TX_GM_ENDS_IT));
}

/* ---- start_confirm: last check before the game starts ----------------- */

static void build_start_confirm(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    slot[2] = header(scr, COLOR_ACCENT);
    lv_label_set_text(slot[2], box_text(TX_START_GAME_UP));
    slot[0] = label(scr, &lv_font_atalaia_28, COLOR_TEXT, -24);
    one_line(slot[0], SCREEN_W - 32);
    slot[1] = label(scr, &lv_font_atalaia_20, COLOR_MUTED, 22);
    slot[3] = footer(scr, box_text(TX_KEYS_START));
}

static void update_start_confirm(const char *data)
{
    /* "setup": the picker's "Wi-Fi setup" entry asks before the box restarts into the setup
     * portal (preset_ui.h): the same screen, with its own words. */
    if (screen_json_true(data, "setup")) {
        lv_label_set_text(slot[2], box_text(TX_SETUP_AGAIN_UP));
        lv_label_set_text(slot[0], box_text(TX_SETUP_ITEM));
        lv_obj_set_width(slot[1], SCREEN_W - 20); /* two lines in Portuguese and German */
        lv_label_set_text(slot[1], box_text(TX_SETUP_WARNING));
        lv_label_set_text(slot[3], box_text(TX_KEYS_SETUP));
        return;
    }
    /* "adopt": the picker's "Adopt to another field" entry asks before the box shows a code. */
    if (screen_json_true(data, "adopt")) {
        lv_label_set_text(slot[2], box_text(TX_ADOPT_AGAIN_UP));
        lv_label_set_text(slot[0], box_text(TX_ADOPT_ITEM));
        lv_obj_set_width(slot[1], SCREEN_W - 20);
        lv_label_set_text(slot[1], box_text(TX_ADOPT_WARNING));
        lv_label_set_text(slot[3], box_text(TX_KEYS_ADOPT));
        return;
    }
    lv_obj_set_width(slot[1], LV_SIZE_CONTENT);
    lv_label_set_text(slot[2], box_text(TX_START_GAME_UP));
    lv_label_set_text(slot[3], box_text(TX_KEYS_START));
    char name[LIST_ITEM_MAX];
    if (!screen_json_str(data, "label", name, sizeof(name)) || !name[0]) {
        snprintf(name, sizeof(name), "%s", box_text(TX_GAME));
    }
    lv_label_set_text(slot[0], name);
    long s = 0;
    screen_json_int(data, "timer_s", &s);
    char t[32], line[64];
    format_minutes(s, t, sizeof(t));
    snprintf(line, sizeof(line), box_text(TX_TIMER_IS), t);
    lv_label_set_text(slot[1], line);
}

/* ---- wifi_setup: first-time configuration ----------------------------- */

static void build_wifi_setup(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    lv_label_set_text(header(scr, COLOR_ACCENT), box_text(TX_FIRST_SETUP_UP));
    slot[0] = label(scr, &lv_font_atalaia_20, COLOR_MUTED, -50);
    lv_label_set_text(slot[0], box_text(TX_JOIN_WIFI));
    slot[1] = label(scr, &lv_font_atalaia_28, COLOR_ACCENT, -12);
    one_line(slot[1], SCREEN_W - 24);
    slot[2] = label(scr, &lv_font_atalaia_20, COLOR_MUTED, 30);
    lv_label_set_text(slot[2], box_text(TX_THEN_OPEN));
    footer(scr, box_text(TX_PHONES_OPEN));
}

static void update_wifi_setup(const char *data)
{
    char ssid[48];
    if (!screen_json_str(data, "ssid", ssid, sizeof(ssid)) || !ssid[0]) {
        snprintf(ssid, sizeof(ssid), "atalaia-....");
    }
    lv_label_set_text(slot[1], ssid);
}

/* ---- dispatch ----------------------------------------------------------- */

typedef struct {
    const char *name;
    void (*build)(lv_obj_t *scr);
    void (*update)(const char *data);
} template_fns_t;

static const template_fns_t templates[] = {
    {"standby", build_standby, update_standby},
    {"countdown", build_countdown, update_countdown},
    {"defused", build_defused, update_result},
    {"exploded", build_exploded, update_result},
    {"final_score", build_final_score, update_final_score},
    {"paused", build_paused, update_paused},
    {"neutral", build_neutral, update_neutral},
    {"captured", build_captured, update_captured},
    {"waiting", build_waiting, update_waiting},
    {"playing", build_playing, update_playing},
    {"ready", build_ready, update_ready},
    {"code_entry", build_code_entry, update_code_entry},
    {"status", build_status, update_status},
    {"pin_entry", build_pin_entry, update_pin_entry},
    {"preset_select", build_preset_select, update_preset_select},
    {"timer_adjust", build_timer_adjust, update_timer_adjust},
    {"start_confirm", build_start_confirm, update_start_confirm},
    {"wifi_setup", build_wifi_setup, update_wifi_setup},
};

/* Clears the screen for a new template. */
static void clean_screen(lv_obj_t *scr)
{
    lv_obj_clean(scr);
    memset(slot, 0, sizeof(slot));
    lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_pad_all(scr, 0, 0);
    shown_template[0] = '\0';
    screen_template_forget();
}

static void lvgl_render(const char *template_name, const char *data_json)
{
    if (!lv_is_initialized() || !lv_display_get_default()) return;
    lv_obj_t *scr = lv_screen_active();
    if (!scr) return;
    const char *data = data_json ? data_json : "{}";
    /* The box's texts are set when a screen is built: another language, another build. */
    static box_lang_t built_lang = BOX_LANG_EN;
    if (box_lang() != built_lang) {
        built_lang = box_lang();
        shown_template[0] = '\0';
    }

    /* The mode's own template first; "~" marks it in shown_template. */
    const builtin_screen_t *yaml = screen_template_find(template_name);
    if (yaml) {
        /* The box's language as "lang", unless the mode gives one (box_text.h). */
        static char with_lang[SCREEN_DATA_MAX + 16];
        char given[8];
        if (box_lang_given() && !screen_json_str(data, "lang", given, sizeof(given))) {
            const char *rest = strchr(data, '{');
            rest = rest != NULL ? rest + 1 : "}";
            while (*rest == ' ') rest++;
            snprintf(with_lang, sizeof(with_lang), "{\"lang\":\"%s\"%s%s",
                     box_lang_code(box_lang()), *rest == '}' ? "" : ",", rest);
            data = with_lang;
        }
        char key[SCREEN_TEMPLATE_MAX];
        snprintf(key, sizeof(key), "~%s", template_name);
        if (strcmp(shown_template, key) == 0) {
            screen_template_update(data);
            return;
        }
        clean_screen(scr);
        set_bg(scr, COLOR_BG);
        if (screen_template_build(scr, yaml, data)) {
            snprintf(shown_template, sizeof(shown_template), "%s", key);
            return;
        }
        /* It did not parse (CI checks every template, so this is a bug): the C screen, if any. */
    }

    for (size_t i = 0; i < sizeof(templates) / sizeof(templates[0]); i++) {
        if (strcmp(templates[i].name, template_name) != 0) continue;
        if (strcmp(shown_template, template_name) != 0) {
            clean_screen(scr);
            templates[i].build(scr);
            snprintf(shown_template, sizeof(shown_template), "%s", template_name);
        }
        templates[i].update(data);
        return;
    }
}

static void lvgl_forget(void)
{
    shown_template[0] = '\0';
}

/* The game timer's bar (ADR-P1-3): a strip along the bottom edge on the display's top layer,
 * so every screen (the C ones, the modes' templates) keeps it and clean_screen() leaves it.
 * It sits below the footers (the lowest text ends at y = 230). */
#define TIMER_BAR_H    6
#define TIMER_BAR_LAST 60 /* the last minute is red */
static lv_obj_t *timer_track, *timer_fill;

static void lvgl_timer_bar(bool visible, long left_s, long total_s)
{
    if (!lv_is_initialized() || !lv_display_get_default()) return;
    if (!timer_track) {
        lv_obj_t *top = lv_display_get_layer_top(lv_display_get_default());
        timer_track = box(top, SCREEN_W, TIMER_BAR_H, COLOR_PANEL);
        lv_obj_align(timer_track, LV_ALIGN_BOTTOM_LEFT, 0, 0);
        timer_fill = box(timer_track, SCREEN_W, TIMER_BAR_H, COLOR_ACCENT);
        lv_obj_align(timer_fill, LV_ALIGN_LEFT_MID, 0, 0);
    }
    show(timer_track, visible);
    if (!visible) return;
    lv_obj_set_width(timer_fill, (int32_t)((int64_t)SCREEN_W * left_s / total_s));
    set_bg(timer_fill, left_s <= TIMER_BAR_LAST ? COLOR_DANGER : COLOR_ACCENT);
}

#endif /* ATALAIA_SCREEN_LVGL */

/* ------------------------------------------------------------------ */
/* Public API                                                          */
/* ------------------------------------------------------------------ */

bool screen_render(const char *template_name, const char *data_json)
{
    if (!template_name) return false;

    /* The running mode, for its own templates (in order with the screens). */
    if (strcmp(template_name, SCREEN_MODE_MESSAGE) == 0) {
        screen_template_set_mode(data_json);
#if ATALAIA_SCREEN_LVGL
        lvgl_forget(); /* the same name may now be another mode's template */
#endif
        return true;
    }

    /* Check if this is a known template: the mode's own, or one of the C ones. */
    bool found = screen_template_find(template_name) != NULL;
    for (int i = 0; known_templates[i]; i++) {
        if (strcmp(template_name, known_templates[i]) == 0) {
            found = true;
            break;
        }
    }
    if (!found) return false;

    /* Record for test inspection (all builds). */
    snprintf(last_template, sizeof(last_template), "%s", template_name);
    if (data_json) {
        snprintf(last_data, sizeof(last_data), "%s", data_json);
    } else {
        last_data[0] = '\0';
    }
    call_count++;

#if ATALAIA_SCREEN_LVGL
    lvgl_render(template_name, data_json);
#endif

    return true;
}

void screen_timer_bar(long left_s, long total_s)
{
    bool visible = total_s > 0 && left_s >= 0;
    if (visible && left_s > total_s) left_s = total_s;
    if (visible == timer_bar_on && (!visible || left_s == timer_bar_left)) return;
    timer_bar_on = visible;
    timer_bar_left = visible ? left_s : -1;
#if ATALAIA_SCREEN_LVGL
    lvgl_timer_bar(visible, left_s, total_s);
#endif
}

long screen_timer_bar_left(void)
{
    return timer_bar_on ? timer_bar_left : -1;
}

void screen_renderer_reset(void)
{
    last_template[0] = '\0';
    last_data[0] = '\0';
    call_count = 0;
    screen_timer_bar(-1, 0);
    screen_template_reset();
#if ATALAIA_SCREEN_LVGL
    lvgl_forget();
#endif
}

const char *screen_renderer_last_template(void)
{
    return last_template;
}

const char *screen_renderer_last_data(void)
{
    return last_data;
}

int screen_renderer_call_count(void)
{
    return call_count;
}
