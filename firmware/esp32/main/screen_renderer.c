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
 */
#include "screen_renderer.h"

#include <stdio.h>
#include <string.h>

static char last_template[SCREEN_TEMPLATE_MAX];
static char last_data[SCREEN_DATA_MAX];
static int call_count;

/* Known templates. Mode templates first, then the shell's own screens. */
static const char *known_templates[] = {
    "standby",      "countdown",     "defused",    "exploded",  "final_score",
    "paused",       "code_entry",    "status",     "pin_entry", "preset_select",
    "timer_adjust", "start_confirm", "wifi_setup", NULL,
};

/* ------------------------------------------------------------------ */
/* LVGL rendering                                                      */
/* ------------------------------------------------------------------ */

#if ATALAIA_SCREEN_LVGL

#include <stdlib.h>

#include "lvgl.h"

/* ---- A small JSON reader for template data ------------------------ */
/*
 * Template data is a flat JSON object written by the core (mode screens)
 * or the shell (system screens). The reader walks one object level and
 * skips nested values, so a key inside a nested object never matches.
 */

static const char *json_ws(const char *p)
{
    while (p && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) p++;
    return p;
}

/* Returns the character after the string that starts at p (p points at '"'). */
static const char *json_skip_string(const char *p)
{
    p++;
    while (*p && *p != '"') {
        if (*p == '\\' && p[1]) p++;
        p++;
    }
    return *p == '"' ? p + 1 : NULL;
}

/* Returns the character after the value that starts at p, or NULL. */
static const char *json_skip_value(const char *p)
{
    p = json_ws(p);
    if (!p || !*p) return NULL;
    if (*p == '"') return json_skip_string(p);
    if (*p == '{' || *p == '[') {
        int depth = 0;
        while (*p) {
            if (*p == '"') {
                p = json_skip_string(p);
                if (!p) return NULL;
                continue;
            }
            if (*p == '{' || *p == '[') depth++;
            if (*p == '}' || *p == ']') {
                depth--;
                if (depth == 0) return p + 1;
            }
            p++;
        }
        return NULL;
    }
    while (*p && *p != ',' && *p != '}' && *p != ']' && *p != ' ' && *p != '\n') p++;
    return p;
}

/* Finds the value of a top-level key in a JSON object. */
static const char *json_find(const char *json, const char *key)
{
    const char *p = json_ws(json);
    if (!p || *p != '{') return NULL;
    p = json_ws(p + 1);
    size_t key_len = strlen(key);
    while (p && *p == '"') {
        const char *name = p + 1;
        const char *after = json_skip_string(p);
        if (!after) return NULL;
        bool match = (size_t)(after - 1 - name) == key_len && memcmp(name, key, key_len) == 0;
        p = json_ws(after);
        if (*p != ':') return NULL;
        p = json_ws(p + 1);
        if (match) return p;
        p = json_ws(json_skip_value(p));
        if (!p || *p != ',') return NULL;
        p = json_ws(p + 1);
    }
    return NULL;
}

/* Copies a JSON string value (p points at '"') into out, decoding escapes. */
static bool json_copy_string(const char *p, char *out, size_t out_sz)
{
    if (!p || *p != '"' || out_sz == 0) return false;
    p++;
    size_t n = 0;
    while (*p && *p != '"') {
        char c = *p++;
        if (c == '\\' && *p) {
            char e = *p++;
            if (e == 'n' || e == 't' || e == 'r') {
                c = ' ';
            } else if (e == 'u') {
                long code = 0;
                for (int i = 0; i < 4 && *p; i++, p++) {
                    char h = *p;
                    int v = (h >= '0' && h <= '9')   ? h - '0'
                            : (h >= 'a' && h <= 'f') ? h - 'a' + 10
                            : (h >= 'A' && h <= 'F') ? h - 'A' + 10
                                                     : 0;
                    code = code * 16 + v;
                }
                c = (code >= 0x20 && code < 0x7f) ? (char)code : '?';
            } else {
                c = e; /* \" \\ \/ */
            }
        }
        if (n + 1 < out_sz) out[n++] = c;
    }
    out[n] = '\0';
    return *p == '"';
}

static bool json_str(const char *json, const char *key, char *out, size_t out_sz)
{
    out[0] = '\0';
    return json_copy_string(json_find(json, key), out, out_sz);
}

static bool json_int(const char *json, const char *key, long *out)
{
    const char *p = json_find(json, key);
    if (!p) return false;
    char *end;
    double v = strtod(p, &end);
    if (end == p) return false;
    *out = (long)v;
    return true;
}

static bool json_true(const char *json, const char *key)
{
    const char *p = json_find(json, key);
    return p && strncmp(p, "true", 4) == 0;
}

/* Reads a JSON array of strings. Returns the number of entries copied. */
#define LIST_MAX      9
#define LIST_ITEM_MAX 40
static int json_str_list(const char *json, const char *key, char out[][LIST_ITEM_MAX], int max)
{
    const char *p = json_find(json, key);
    if (!p || *p != '[') return 0;
    p = json_ws(p + 1);
    int n = 0;
    while (p && *p == '"' && n < max) {
        json_copy_string(p, out[n++], LIST_ITEM_MAX);
        p = json_ws(json_skip_string(p));
        if (!p || *p != ',') break;
        p = json_ws(p + 1);
    }
    return n;
}

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
    lv_obj_set_style_text_font(title, &lv_font_montserrat_20, 0);
    lv_obj_set_style_text_color(title, lv_color_hex(text_on(bg)), 0);
    lv_obj_set_style_text_letter_space(title, 2, 0);
    lv_obj_center(title);
    return title;
}

static lv_obj_t *footer(lv_obj_t *scr, const char *hint)
{
    lv_obj_t *l = lv_label_create(scr);
    lv_obj_set_style_text_font(l, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(COLOR_MUTED), 0);
    lv_obj_align(l, LV_ALIGN_BOTTOM_MID, 0, -10);
    lv_label_set_text(l, hint);
    return l;
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
        snprintf(buf, sz, "No limit");
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
    lv_label_set_text(header(scr, COLOR_PANEL), "STANDBY");
    slot[0] = label(scr, &lv_font_montserrat_20, COLOR_MUTED, -42);
    slot[1] = label(scr, &lv_font_montserrat_48, COLOR_TEXT, 4);
    slot[2] = box(scr, 180, 8, COLOR_PANEL);
    lv_obj_set_style_radius(slot[2], 4, 0);
    lv_obj_align(slot[2], LV_ALIGN_CENTER, 0, 46);
    footer(scr, "The bomb is not armed");
}

static void update_standby(const char *data)
{
    char team[SCREEN_TEMPLATE_MAX];
    bool has_team = json_str(data, "arm", team, sizeof(team)) && team[0];
    lv_label_set_text(slot[0], has_team ? "Hold the button to arm" : "Waiting");
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
    lv_label_set_text(header(scr, COLOR_DANGER), "ARMED");
    slot[0] = label(scr, &lv_font_montserrat_48, COLOR_TEXT, -8);
    slot[1] = label(scr, &lv_font_montserrat_20, COLOR_MUTED, 42);
    lv_label_set_text(slot[1], "until detonation");
    slot[2] = footer(scr, "");
}

static void update_countdown(const char *data)
{
    long left = 0;
    json_int(data, "left", &left);
    char buf[24];
    format_clock(left, buf, sizeof(buf));
    lv_label_set_text(slot[0], buf);
    set_colour(slot[0], left <= 10 ? COLOR_DANGER : COLOR_TEXT);

    char team[SCREEN_TEMPLATE_MAX];
    if (json_str(data, "team", team, sizeof(team)) && team[0]) {
        uint32_t rgb = team_rgb(team);
        upper(team);
        char line[64];
        snprintf(line, sizeof(line), "Armed by %s", team);
        lv_label_set_text(slot[2], line);
        set_colour(slot[2], rgb);
    } else {
        lv_label_set_text(slot[2], "");
    }
}

/* ---- defused / exploded: the round result, in the winner's colour ---- */

static void build_result(lv_obj_t *scr, const char *symbol, const char *title)
{
    slot[0] = label(scr, &lv_font_montserrat_48, COLOR_TEXT, -62);
    lv_label_set_text(slot[0], symbol);
    slot[1] = label(scr, &lv_font_montserrat_48, COLOR_TEXT, 0);
    lv_label_set_text(slot[1], title);
    slot[2] = label(scr, &lv_font_montserrat_28, COLOR_TEXT, 58);
}

static void update_result(const char *data)
{
    char team[SCREEN_TEMPLATE_MAX];
    bool has_team = json_str(data, "team", team, sizeof(team)) && team[0];
    uint32_t bg = has_team ? team_rgb(team) : COLOR_PANEL;
    uint32_t fg = text_on(bg);
    set_bg(lv_screen_active(), bg);
    for (int i = 0; i < 3; i++) set_colour(slot[i], fg);
    if (has_team) {
        upper(team);
        char line[64];
        snprintf(line, sizeof(line), "%s team wins", team);
        lv_label_set_text(slot[2], line);
    }
    show(slot[2], has_team);
}

static void build_defused(lv_obj_t *scr)
{
    build_result(scr, LV_SYMBOL_OK, "DEFUSED");
}

static void build_exploded(lv_obj_t *scr)
{
    build_result(scr, LV_SYMBOL_WARNING, "EXPLODED");
}

/* ---- final_score: the game is over ----------------------------------- */

static void build_final_score(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    lv_label_set_text(header(scr, COLOR_PANEL), "GAME OVER");
    slot[0] = label(scr, &lv_font_montserrat_20, COLOR_MUTED, -36);
    slot[1] = label(scr, &lv_font_montserrat_48, COLOR_TEXT, 10);
    footer(scr, "Scores are final");
}

static void update_final_score(const char *data)
{
    char owner[SCREEN_TEMPLATE_MAX];
    bool has_owner = json_str(data, "owner", owner, sizeof(owner)) && owner[0];
    lv_label_set_text(slot[0], has_owner ? "The zone was held by" : "No team held the zone");
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
    slot[0] = label(scr, &lv_font_montserrat_48, COLOR_ACCENT, -52);
    lv_label_set_text(slot[0], LV_SYMBOL_PAUSE);
    slot[1] = label(scr, &lv_font_montserrat_48, COLOR_TEXT, 8);
    lv_label_set_text(slot[1], "PAUSED");
    slot[2] = label(scr, &lv_font_montserrat_20, COLOR_MUTED, 60);
    lv_label_set_text(slot[2], "Wait for the game master");
}

static void update_paused(const char *data)
{
    (void)data;
}

/* ---- status: node information ------------------------------------------ */

#define STATUS_ROWS 4

static void build_status(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    slot[0] = header(scr, COLOR_PANEL);
    for (int i = 0; i < STATUS_ROWS; i++) {
        lv_obj_t *key = lv_label_create(scr);
        lv_obj_set_style_text_font(key, &lv_font_montserrat_20, 0);
        lv_obj_set_style_text_color(key, lv_color_hex(COLOR_MUTED), 0);
        lv_obj_align(key, LV_ALIGN_TOP_LEFT, 24, HEADER_H + 22 + i * 40);
        lv_obj_t *val = lv_label_create(scr);
        lv_obj_set_style_text_font(val, &lv_font_montserrat_20, 0);
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
    if (!json_str(data, "title", title, sizeof(title)) || !title[0]) {
        snprintf(title, sizeof(title), "STATUS");
    }
    upper(title);
    lv_label_set_text(slot[0], title);

    char rows[STATUS_ROWS][2][LIST_ITEM_MAX];
    int n = 0;
    char buf[LIST_ITEM_MAX];
    long v;
    if (json_str(data, "mode", buf, sizeof(buf)) && buf[0]) {
        snprintf(rows[n][0], LIST_ITEM_MAX, "Game");
        snprintf(rows[n++][1], LIST_ITEM_MAX, "%s", buf);
    }
    if (json_int(data, "timer_s", &v)) {
        snprintf(rows[n][0], LIST_ITEM_MAX, "Timer");
        format_minutes(v, rows[n++][1], LIST_ITEM_MAX);
    }
    if (json_int(data, "battery", &v) && v >= 0) {
        snprintf(rows[n][0], LIST_ITEM_MAX, "Battery");
        snprintf(rows[n++][1], LIST_ITEM_MAX, "%ld%%", v);
    }
    if (n < STATUS_ROWS && json_str(data, "version", buf, sizeof(buf)) && buf[0]) {
        snprintf(rows[n][0], LIST_ITEM_MAX, "Firmware");
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
    lv_label_set_text(header(scr, COLOR_PANEL), "GAME MASTER");
    slot[0] = label(scr, &lv_font_montserrat_20, COLOR_TEXT, -46);
    lv_label_set_text(slot[0], "Enter the admin PIN");
    for (int i = 0; i < PIN_DOTS; i++) {
        lv_obj_t *dot = box(scr, 22, 22, COLOR_BG);
        lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_border_width(dot, 2, 0);
        slot[1 + i] = dot;
    }
    slot[1 + PIN_DOTS] = label(scr, &lv_font_montserrat_20, COLOR_DANGER, 48);
    lv_label_set_text(slot[1 + PIN_DOTS], "Wrong PIN, try again");
    footer(scr, "#  enter        *  delete");
}

static void update_pin_entry(const char *data)
{
    long digits = 0;
    json_int(data, "digits", &digits);
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
    show(slot[1 + PIN_DOTS], json_true(data, "error"));
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
    slot[1] = label(scr, &lv_font_montserrat_28, COLOR_DANGER, -42);
    for (int i = 0; i < CODE_DOTS; i++) {
        lv_obj_t *dot = box(scr, 22, 22, COLOR_BG);
        lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_border_width(dot, 2, 0);
        slot[2 + i] = dot;
    }
    slot[2 + CODE_DOTS] = label(scr, &lv_font_montserrat_20, COLOR_ACCENT, 50);
    one_line(slot[2 + CODE_DOTS], 300);
    footer(scr, "#  enter        *  delete");
}

static void update_code_entry(const char *data)
{
    char text[CODE_TEXT_MAX];
    if (!json_str(data, "title", text, sizeof(text)) || !text[0]) {
        snprintf(text, sizeof(text), "CODE");
    }
    upper(text);
    lv_label_set_text(slot[0], text);

    long left = 0;
    bool has_left = json_int(data, "left", &left);
    if (has_left) {
        format_clock(left, text, sizeof(text));
        lv_label_set_text(slot[1], text);
    }
    show(slot[1], has_left);

    long digits = 0;
    json_int(data, "digits", &digits);
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
    bool has_msg = json_str(data, "message", text, sizeof(text)) && text[0];
    lv_label_set_text(msg, has_msg ? text : "");
    set_colour(msg, json_true(data, "error") ? COLOR_DANGER : COLOR_ACCENT);
    show(msg, has_msg);
}

/* ---- preset_select: the list of stored games -------------------------- */

#define PRESET_ROWS  5
#define PRESET_ROW_H 28
#define PRESET_PITCH 32

static void build_preset_select(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    lv_label_set_text(header(scr, COLOR_PANEL), "CHOOSE A GAME");
    for (int i = 0; i < PRESET_ROWS; i++) {
        lv_obj_t *row = box(scr, SCREEN_W - 24, PRESET_ROW_H, COLOR_BG);
        lv_obj_set_style_radius(row, 6, 0);
        lv_obj_align(row, LV_ALIGN_TOP_MID, 0, HEADER_H + 6 + i * PRESET_PITCH);
        lv_obj_t *num = lv_label_create(row);
        lv_obj_set_style_text_font(num, &lv_font_montserrat_20, 0);
        lv_obj_align(num, LV_ALIGN_LEFT_MID, 12, 0);
        lv_obj_t *name = lv_label_create(row);
        lv_obj_set_style_text_font(name, &lv_font_montserrat_20, 0);
        one_line(name, SCREEN_W - 24 - 56);
        lv_obj_align(name, LV_ALIGN_LEFT_MID, 44, 0);
        slot[3 * i] = row;
        slot[3 * i + 1] = num;
        slot[3 * i + 2] = name;
    }
    slot[3 * PRESET_ROWS] = label(scr, &lv_font_montserrat_20, COLOR_MUTED, 0);
    lv_label_set_text(slot[3 * PRESET_ROWS], "No games stored");
    footer(scr, "1-9  choose      #  next      *  back");
}

static void update_preset_select(const char *data)
{
    char names[LIST_MAX][LIST_ITEM_MAX];
    int count = json_str_list(data, "presets", names, LIST_MAX);
    long selected = 1;
    json_int(data, "selected", &selected);

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
    lv_label_set_text(header(scr, COLOR_PANEL), "GAME TIMER");
    slot[0] = label(scr, &lv_font_montserrat_48, COLOR_TEXT, -12);
    slot[1] = label(scr, &lv_font_montserrat_20, COLOR_MUTED, 40);
    footer(scr, "2  +5 min     8  -5 min     #  next     *  back");
}

static void update_timer_adjust(const char *data)
{
    long s = 0;
    json_int(data, "timer_s", &s);
    char buf[32];
    format_minutes(s, buf, sizeof(buf));
    lv_label_set_text(slot[0], buf);
    lv_label_set_text(slot[1], s > 0 ? "then the game ends" : "the game master ends it");
}

/* ---- start_confirm: last check before the game starts ----------------- */

static void build_start_confirm(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    lv_label_set_text(header(scr, COLOR_ACCENT), "START THE GAME?");
    slot[0] = label(scr, &lv_font_montserrat_28, COLOR_TEXT, -24);
    one_line(slot[0], SCREEN_W - 32);
    slot[1] = label(scr, &lv_font_montserrat_20, COLOR_MUTED, 22);
    footer(scr, "#  start      *  back");
}

static void update_start_confirm(const char *data)
{
    char name[LIST_ITEM_MAX];
    if (!json_str(data, "label", name, sizeof(name)) || !name[0]) {
        snprintf(name, sizeof(name), "Game");
    }
    lv_label_set_text(slot[0], name);
    long s = 0;
    json_int(data, "timer_s", &s);
    char t[32], line[48];
    format_minutes(s, t, sizeof(t));
    snprintf(line, sizeof(line), "Timer: %s", t);
    lv_label_set_text(slot[1], line);
}

/* ---- wifi_setup: first-time configuration ----------------------------- */

static void build_wifi_setup(lv_obj_t *scr)
{
    set_bg(scr, COLOR_BG);
    lv_label_set_text(header(scr, COLOR_ACCENT), "FIRST-TIME SETUP");
    slot[0] = label(scr, &lv_font_montserrat_20, COLOR_MUTED, -50);
    lv_label_set_text(slot[0], "Join the Wi-Fi network");
    slot[1] = label(scr, &lv_font_montserrat_28, COLOR_ACCENT, -12);
    one_line(slot[1], SCREEN_W - 24);
    slot[2] = label(scr, &lv_font_montserrat_20, COLOR_MUTED, 30);
    lv_label_set_text(slot[2], "then open 192.168.4.1");
    footer(scr, "Phones usually open it by themselves");
}

static void update_wifi_setup(const char *data)
{
    char ssid[48];
    if (!json_str(data, "ssid", ssid, sizeof(ssid)) || !ssid[0]) {
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
    {"code_entry", build_code_entry, update_code_entry},
    {"status", build_status, update_status},
    {"pin_entry", build_pin_entry, update_pin_entry},
    {"preset_select", build_preset_select, update_preset_select},
    {"timer_adjust", build_timer_adjust, update_timer_adjust},
    {"start_confirm", build_start_confirm, update_start_confirm},
    {"wifi_setup", build_wifi_setup, update_wifi_setup},
};

static void lvgl_render(const char *template_name, const char *data_json)
{
    if (!lv_is_initialized() || !lv_display_get_default()) return;
    lv_obj_t *scr = lv_screen_active();
    if (!scr) return;
    const char *data = data_json ? data_json : "{}";

    for (size_t i = 0; i < sizeof(templates) / sizeof(templates[0]); i++) {
        if (strcmp(templates[i].name, template_name) != 0) continue;
        if (strcmp(shown_template, template_name) != 0) {
            lv_obj_clean(scr);
            memset(slot, 0, sizeof(slot));
            lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
            lv_obj_set_style_pad_all(scr, 0, 0);
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

#endif /* ATALAIA_SCREEN_LVGL */

/* ------------------------------------------------------------------ */
/* Public API                                                          */
/* ------------------------------------------------------------------ */

bool screen_render(const char *template_name, const char *data_json)
{
    if (!template_name) return false;

    /* Check if this is a known template. */
    bool found = false;
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

void screen_renderer_reset(void)
{
    last_template[0] = '\0';
    last_data[0] = '\0';
    call_count = 0;
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
