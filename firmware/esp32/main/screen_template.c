/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The LVGL renderer for declarative screen templates (screen_template.h).
 *
 * Layout on the 320x240 screen: the template's widgets stack in a column,
 * centred both ways, 4 px apart; rows and columns are flex containers
 * (6 px and 4 px gaps) with their children centred. "fill" takes the room
 * left along the parent's direction (flex grow) and the whole parent across
 * it. Fonts: Montserrat 14, 20, 28 and 48 (font_size picks the nearest,
 * 20 by default). A progress bar is a track with a filled part, 200x12 by
 * default. Colours not set: white text on the dark background, accent bars.
 */
#include "screen_template.h"

#include <stdio.h>
#include <string.h>

#include "atalaia/screen_template.h"
#include "screen_types.h"

#define MODE_ID_MAX 64

static char mode_id[MODE_ID_MAX];
static char mode_params[SCREEN_DATA_MAX] = "{}";

void screen_template_set_mode(const char *data)
{
    mode_id[0] = '\0';
    snprintf(mode_params, sizeof(mode_params), "{}");
    if (!data) return;
    const char *sp = strchr(data, ' ');
    size_t n = sp ? (size_t)(sp - data) : strlen(data);
    if (n < sizeof(mode_id)) {
        memcpy(mode_id, data, n);
        mode_id[n] = '\0';
    }
    if (sp && sp[1] == '{') snprintf(mode_params, sizeof(mode_params), "%s", sp + 1);
}

const char *screen_template_mode(void)
{
    return mode_id;
}

const char *screen_template_params(void)
{
    return mode_params;
}

const builtin_screen_t *screen_template_find(const char *name)
{
    if (!name || !mode_id[0]) return NULL;
    /* A main mode and its modifiers: "main+modifier", main mode first. */
    const char *part = mode_id;
    while (*part) {
        const char *end = strchr(part, '+');
        size_t n = end ? (size_t)(end - part) : strlen(part);
        for (int i = 0; i < builtin_screen_count; i++) {
            const builtin_screen_t *s = &builtin_screens[i];
            if (s->mode_id && strlen(s->mode_id) == n && strncmp(s->mode_id, part, n) == 0 &&
                strcmp(s->name, name) == 0) {
                return s;
            }
        }
        if (!end) break;
        part = end + 1;
    }
    return NULL;
}

#if ATALAIA_SCREEN_LVGL

#define W_MAX ATALAIA_TPL_WIDGETS_MAX

#define COLOR_BG      0x101418
#define COLOR_TEXT    0xFFFFFF
#define COLOR_DARK    0x101418
#define COLOR_TRACK   0x222B35
#define COLOR_BAR     0xFFB300
#define COLOR_UNKNOWN 0x78909C /* a team without a colour */

#define BAR_W   200
#define BAR_H   12
#define QR_SIZE 120
#define NOT_SET 0xFFFFFFFFu

static atalaia_tpl_t tpl; /* the template on screen */
static char tpl_error[96];
static lv_obj_t *root;
static lv_obj_t *obj[W_MAX];
static lv_obj_t *fill_part[W_MAX]; /* a progress bar's filled part */
static uint32_t fg_now[W_MAX], bg_now[W_MAX], root_bg_now;
static int16_t percent_now[W_MAX];
static uint32_t qr_hash[W_MAX];
static int changed;

static const struct {
    const char *name;
    const char *symbol;
} icons[] = {
    {"ok", LV_SYMBOL_OK},
    {"close", LV_SYMBOL_CLOSE},
    {"warning", LV_SYMBOL_WARNING},
    {"pause", LV_SYMBOL_PAUSE},
    {"play", LV_SYMBOL_PLAY},
    {"stop", LV_SYMBOL_STOP},
    {"bell", LV_SYMBOL_BELL},
    {"home", LV_SYMBOL_HOME},
    {"refresh", LV_SYMBOL_REFRESH},
    {"gps", LV_SYMBOL_GPS},
    {"wifi", LV_SYMBOL_WIFI},
    {"battery", LV_SYMBOL_BATTERY_FULL},
    {"power", LV_SYMBOL_POWER},
    {"bluetooth", LV_SYMBOL_BLUETOOTH},
    {"settings", LV_SYMBOL_SETTINGS},
    {"eye", LV_SYMBOL_EYE_OPEN},
    {"plus", LV_SYMBOL_PLUS},
    {"minus", LV_SYMBOL_MINUS},
    {"left", LV_SYMBOL_LEFT},
    {"right", LV_SYMBOL_RIGHT},
    {"up", LV_SYMBOL_UP},
    {"down", LV_SYMBOL_DOWN},
    {"audio", LV_SYMBOL_AUDIO},
    {"mute", LV_SYMBOL_MUTE},
    {"bars", LV_SYMBOL_BARS},
    {"loop", LV_SYMBOL_LOOP},
    {"charge", LV_SYMBOL_CHARGE},
};

static const char *icon_symbol(const char *name)
{
    for (size_t i = 0; i < sizeof(icons) / sizeof(icons[0]); i++) {
        if (name && strcmp(icons[i].name, name) == 0) return icons[i].symbol;
    }
    return "?";
}

static const lv_font_t *font_for(int size)
{
    if (size <= 0) size = 20;
    if (size <= 16) return &lv_font_montserrat_14;
    if (size <= 24) return &lv_font_montserrat_20;
    if (size <= 38) return &lv_font_montserrat_28;
    return &lv_font_montserrat_48;
}

/* Dark text on light backgrounds (yellow), white text on the rest. */
static uint32_t contrast_on(uint32_t bg)
{
    uint32_t r = (bg >> 16) & 0xFF, g = (bg >> 8) & 0xFF, b = bg & 0xFF;
    return (r * 299 + g * 587 + b * 114) / 1000 > 160 ? COLOR_DARK : COLOR_TEXT;
}

/* A colour property: NOT_SET when absent or empty, otherwise the colour. */
static uint32_t resolve(const char *v, const atalaia_tpl_scope_t *sc, uint32_t under)
{
    if (!v) return NOT_SET;
    if (strcmp(v, "contrast") == 0) return contrast_on(under);
    char name[48];
    if (strcmp(v, "team") == 0) {
        atalaia_tpl_text("{team}", sc, name, sizeof(name));
    } else if (v[0] == '{') {
        atalaia_tpl_text(v, sc, name, sizeof(name));
    } else {
        snprintf(name, sizeof(name), "%s", v);
    }
    if (!name[0]) return NOT_SET;
    if (strcmp(name, "contrast") == 0) return contrast_on(under);
    uint32_t rgb;
    return atalaia_tpl_color(name, &rgb) ? rgb : COLOR_UNKNOWN;
}

static void set_bg(lv_obj_t *o, uint32_t rgb)
{
    if (rgb == NOT_SET) {
        lv_obj_set_style_bg_opa(o, LV_OPA_TRANSP, 0);
    } else {
        lv_obj_set_style_bg_color(o, lv_color_hex(rgb), 0);
        lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
    }
}

static lv_obj_t *plain(lv_obj_t *parent)
{
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    return o;
}

static bool in_row(const atalaia_tpl_widget_t *w)
{
    return w->parent >= 0 && tpl.w[w->parent].type == ATALAIA_TPL_ROW;
}

static void apply_size(lv_obj_t *o, const atalaia_tpl_widget_t *w, int32_t def_w, int32_t def_h)
{
    bool row = in_row(w);
    if (w->width == ATALAIA_TPL_FILL) {
        if (row) {
            lv_obj_set_width(o, 1);
            lv_obj_set_flex_grow(o, 1);
        } else {
            lv_obj_set_width(o, lv_pct(100));
        }
    } else {
        lv_obj_set_width(o, w->width >= 0 ? w->width : def_w);
    }
    if (w->height == ATALAIA_TPL_FILL) {
        if (row) {
            lv_obj_set_height(o, lv_pct(100));
        } else {
            lv_obj_set_height(o, 1);
            lv_obj_set_flex_grow(o, 1);
        }
    } else {
        lv_obj_set_height(o, w->height >= 0 ? w->height : def_h);
    }
}

static void apply_padding(lv_obj_t *o, const atalaia_tpl_widget_t *w)
{
    lv_obj_set_style_pad_top(o, w->pad[0], 0);
    lv_obj_set_style_pad_right(o, w->pad[1], 0);
    lv_obj_set_style_pad_bottom(o, w->pad[2], 0);
    lv_obj_set_style_pad_left(o, w->pad[3], 0);
}

static lv_text_align_t text_align(uint8_t a)
{
    switch (a) {
    case ATALAIA_TPL_ALIGN_LEFT: return LV_TEXT_ALIGN_LEFT;
    case ATALAIA_TPL_ALIGN_RIGHT: return LV_TEXT_ALIGN_RIGHT;
    default: return LV_TEXT_ALIGN_CENTER;
    }
}

static lv_obj_t *create(int i, lv_obj_t *parent)
{
    const atalaia_tpl_widget_t *w = &tpl.w[i];
    lv_obj_t *o = NULL;
    fill_part[i] = NULL;
    switch (w->type) {
    case ATALAIA_TPL_LABEL:
    case ATALAIA_TPL_ICON:
        o = lv_label_create(parent);
        lv_obj_set_style_text_font(o, font_for(w->font_size), 0);
        lv_obj_set_style_text_align(o, text_align(w->align), 0);
        lv_label_set_text(
            o, w->type == ATALAIA_TPL_ICON ? icon_symbol(atalaia_tpl_str(&tpl, w->content)) : "");
        apply_size(o, w, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
        break;
    case ATALAIA_TPL_PROGRESS_BAR: {
        o = plain(parent);
        apply_size(o, w, BAR_W, BAR_H);
        int32_t h = w->height > 0 ? w->height : BAR_H;
        lv_obj_set_style_radius(o, h / 2, 0);
        set_bg(o, COLOR_TRACK);
        lv_obj_t *f = plain(o);
        lv_obj_set_size(f, 0, lv_pct(100));
        lv_obj_set_style_radius(f, h / 2, 0);
        fill_part[i] = f;
        break;
    }
    case ATALAIA_TPL_QR_CODE:
#if LV_USE_QRCODE
        o = lv_qrcode_create(parent);
        lv_qrcode_set_size(o, w->width > 0 ? w->width : (w->height > 0 ? w->height : QR_SIZE));
        lv_qrcode_set_light_color(o, lv_color_hex(COLOR_TEXT));
#else
        /* QR codes are compiled out (LV_USE_QRCODE, flash): the data is shown as text. */
        o = lv_label_create(parent);
        lv_obj_set_style_text_font(o, font_for(w->font_size ? w->font_size : 14), 0);
        lv_label_set_text(o, "");
        apply_size(o, w, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
#endif
        break;
    case ATALAIA_TPL_SPACER:
        o = plain(parent);
        apply_size(o, w, 1, 1);
        break;
    default: /* row, column */
        o = plain(parent);
        lv_obj_set_flex_flow(o,
                             w->type == ATALAIA_TPL_ROW ? LV_FLEX_FLOW_ROW : LV_FLEX_FLOW_COLUMN);
        lv_obj_set_flex_align(o, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        lv_obj_set_style_pad_column(o, 6, 0);
        lv_obj_set_style_pad_row(o, 4, 0);
        apply_size(o, w, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
        break;
    }
    apply_padding(o, w);
    return o;
}

void screen_template_forget(void)
{
    root = NULL;
    memset(obj, 0, sizeof(obj));
    memset(fill_part, 0, sizeof(fill_part));
    changed = 0;
}

void screen_template_reset(void)
{
    screen_template_set_mode(NULL);
    screen_template_forget();
    tpl.count = 0;
    tpl_error[0] = '\0';
}

static uint32_t fnv(const char *s)
{
    uint32_t h = 2166136261u;
    for (; *s; s++) h = (h ^ (uint8_t)*s) * 16777619u;
    return h;
}

void screen_template_update(const char *data_json)
{
    if (!root) return;
    atalaia_tpl_scope_t sc = {data_json ? data_json : "{}", mode_params};
    changed = 0;

    uint32_t screen_bg = resolve(atalaia_tpl_str(&tpl, tpl.background), &sc, COLOR_BG);
    if (screen_bg == NOT_SET) screen_bg = COLOR_BG;
    if (screen_bg != root_bg_now) {
        set_bg(root, screen_bg);
        root_bg_now = screen_bg;
        changed++;
    }

    uint32_t under[W_MAX]; /* the colour each widget is drawn on */
    char text[ATALAIA_TPL_TEXT_MAX];
    for (int i = 0; i < tpl.count; i++) {
        const atalaia_tpl_widget_t *w = &tpl.w[i];
        lv_obj_t *o = obj[i];
        bool dirty = false;
        uint32_t parent_bg = w->parent >= 0 ? under[w->parent] : screen_bg;

        bool show = atalaia_tpl_truthy(atalaia_tpl_str(&tpl, w->visible), &sc);
        if (show == lv_obj_has_flag(o, LV_OBJ_FLAG_HIDDEN)) {
            if (show) {
                lv_obj_remove_flag(o, LV_OBJ_FLAG_HIDDEN);
            } else {
                lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
            }
            dirty = true;
        }

        uint32_t bg = resolve(atalaia_tpl_str(&tpl, w->background), &sc, parent_bg);
        under[i] = bg == NOT_SET ? parent_bg : bg;
        if (w->type != ATALAIA_TPL_PROGRESS_BAR && bg != bg_now[i]) {
            set_bg(o, bg);
            bg_now[i] = bg;
            dirty = true;
        }

        uint32_t fg = resolve(atalaia_tpl_str(&tpl, w->color), &sc, under[i]);
        switch (w->type) {
        case ATALAIA_TPL_LABEL:
        case ATALAIA_TPL_ICON:
            if (fg == NOT_SET) fg = COLOR_TEXT;
            if (fg != fg_now[i]) {
                lv_obj_set_style_text_color(o, lv_color_hex(fg), 0);
                fg_now[i] = fg;
                dirty = true;
            }
            if (w->type == ATALAIA_TPL_LABEL) {
                atalaia_tpl_text(atalaia_tpl_str(&tpl, w->content), &sc, text, sizeof(text));
                if (strcmp(lv_label_get_text(o), text) != 0) {
                    lv_label_set_text(o, text);
                    dirty = true;
                }
            }
            break;
        case ATALAIA_TPL_PROGRESS_BAR: {
            if (fg == NOT_SET) fg = COLOR_BAR;
            if (fg != fg_now[i]) {
                set_bg(fill_part[i], fg);
                fg_now[i] = fg;
                dirty = true;
            }
            double f = atalaia_tpl_fraction(atalaia_tpl_str(&tpl, w->content), &sc);
            int16_t pct = (int16_t)(f * 100.0 + 0.5);
            if (pct != percent_now[i]) {
                lv_obj_set_width(fill_part[i], lv_pct(pct));
                percent_now[i] = pct;
                dirty = true;
            }
            break;
        }
        case ATALAIA_TPL_QR_CODE: {
            atalaia_tpl_text(atalaia_tpl_str(&tpl, w->content), &sc, text, sizeof(text));
            uint32_t h = fnv(text) ^ (fg == NOT_SET ? 0 : fg);
            if (h != qr_hash[i]) {
#if LV_USE_QRCODE
                lv_qrcode_set_dark_color(o, lv_color_hex(fg == NOT_SET ? COLOR_DARK : fg));
                lv_qrcode_update(o, text, (uint32_t)strlen(text));
#else
                lv_obj_set_style_text_color(o, lv_color_hex(fg == NOT_SET ? COLOR_TEXT : fg), 0);
                lv_label_set_text(o, text);
#endif
                qr_hash[i] = h;
                dirty = true;
            }
            break;
        }
        default: break;
        }
        changed += dirty ? 1 : 0;
    }
}

bool screen_template_build(lv_obj_t *scr, const builtin_screen_t *s, const char *data_json)
{
    screen_template_forget();
    if (!atalaia_tpl_parse(&tpl, s->yaml, s->len, tpl_error, sizeof(tpl_error))) {
        tpl.count = 0;
        return false;
    }
    root = plain(scr);
    lv_obj_set_size(root, lv_pct(100), lv_pct(100));
    lv_obj_set_flex_flow(root, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(root, 4, 0);
    root_bg_now = NOT_SET;
    for (int i = 0; i < tpl.count; i++) {
        int p = tpl.w[i].parent;
        obj[i] = create(i, p >= 0 ? obj[p] : root);
        fg_now[i] = bg_now[i] = NOT_SET; /* labels and plain objects start transparent */
        percent_now[i] = -1;
        qr_hash[i] = 0;
    }
    screen_template_update(data_json);
    return true;
}

int screen_template_widget_count(void)
{
    return root ? tpl.count : 0;
}

int screen_template_changed(void)
{
    return changed;
}

lv_obj_t *screen_template_widget(const char *id)
{
    if (!root || !id) return NULL;
    for (int i = 0; i < tpl.count; i++) {
        const char *wid = atalaia_tpl_str(&tpl, tpl.w[i].id);
        if (wid && strcmp(wid, id) == 0) return obj[i];
    }
    return NULL;
}

const char *screen_template_last_error(void)
{
    return tpl_error;
}

#else

void screen_template_reset(void)
{
    screen_template_set_mode(NULL);
}

#endif /* ATALAIA_SCREEN_LVGL */
