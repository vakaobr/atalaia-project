/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The on-board OLED's status view (oled_view.h): 128x64, a 16-pixel
 * header bar (Montserrat 14, dark on lit), a 32-pixel middle line
 * (Montserrat 28, smaller when the text does not fit) and a 16-pixel
 * footer (Montserrat 14).
 */
#include "oled_view.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>

#include "screen_json.h"
#include "screen_types.h"

/* ---- Mapping (plain C) ------------------------------------------------- */

#define PIN_MAX_DOTS 8

static void upper(char *s)
{
    for (; *s; s++) {
        *s = *s == '_' ? ' ' : (char)toupper((unsigned char)*s);
    }
}

static void set(char *dst, size_t sz, const char *src)
{
    snprintf(dst, sz, "%s", src ? src : "");
}

/* 299 -> "4:59", 3725 -> "1:02:05". */
static void clock_text(long s, char *out, size_t sz)
{
    if (s < 0) s = 0;
    if (s >= 3600) {
        snprintf(out, sz, "%ld:%02ld:%02ld", s / 3600, (s / 60) % 60, s % 60);
    } else {
        snprintf(out, sz, "%ld:%02ld", s / 60, s % 60);
    }
}

/* n masked digits, "* * * *"; "- - - -" for none. */
static void dots(long n, char *out, size_t sz)
{
    if (n < 0) n = 0;
    if (n > PIN_MAX_DOTS) n = PIN_MAX_DOTS;
    size_t len = 0;
    out[0] = '\0';
    long shown = n ? n : 4;
    for (long i = 0; i < shown && len + 2 < sz; i++) {
        if (i) out[len++] = ' ';
        out[len++] = n ? '*' : '-';
    }
    out[len] = '\0';
}

/* The value of the first of keys that holds a non-empty string. */
static bool first_str(const char *data, const char *const *keys, char *out, size_t sz)
{
    for (; *keys; keys++) {
        if (screen_json_str(data, *keys, out, sz) && out[0]) return true;
    }
    out[0] = '\0';
    return false;
}

void oled_mode_title(const char *mode_msg, char *out, size_t out_sz)
{
    if (!out_sz) return;
    out[0] = '\0';
    if (!mode_msg) return;
    /* The mode id runs to the first space; its last dotted part names it. */
    size_t len = strcspn(mode_msg, " ");
    const char *name = mode_msg;
    for (size_t i = 0; i < len; i++) {
        if (mode_msg[i] == '.') name = mode_msg + i + 1;
    }
    size_t n = (size_t)(mode_msg + len - name);
    if (n >= out_sz) n = out_sz - 1;
    memcpy(out, name, n);
    out[n] = '\0';
    upper(out);
}

/* A 0-1 share in data as 0-100, or -1 when the key is absent or 0. */
static int share_pct(const char *data, const char *key)
{
    double v;
    if (!screen_json_number(data, key, &v) || v <= 0) return -1;
    return v >= 1 ? 100 : (int)(v * 100);
}

bool oled_text_for(const char *mode_title, const char *t, const char *data, oled_text_t *out)
{
    memset(out, 0, sizeof(*out));
    out->bar = -1;
    if (!t || strcmp(t, "@mode") == 0) return false;
    if (!data) data = "{}";
    const char *mode = mode_title && mode_title[0] ? mode_title : "ATALAIA";

    char s[32];
    long v = 0;

    /* ---- the shell's screens ---- */
    if (strcmp(t, "pin_entry") == 0) {
        set(out->head, sizeof(out->head), "ADMIN PIN");
        screen_json_int(data, "digits", &v);
        dots(v, out->big, sizeof(out->big));
        set(out->foot, sizeof(out->foot),
            screen_json_true(data, "error") ? "Wrong PIN" : "# enter  * delete");
        return true;
    }
    if (strcmp(t, "preset_select") == 0) {
        char names[9][32];
        int count = screen_json_str_list(data, "presets", names[0], sizeof(names[0]), 9);
        long selected = 1, page = 1, pages = 1;
        screen_json_int(data, "selected", &selected);
        screen_json_int(data, "page", &page);
        screen_json_int(data, "pages", &pages);
        set(out->head, sizeof(out->head), "GAMES");
        if (pages > 1) snprintf(out->head_right, sizeof(out->head_right), "%ld/%ld", page, pages);
        if (selected >= 1 && selected <= count) {
            snprintf(out->big, sizeof(out->big), "%d %s", (int)selected, names[selected - 1]);
        } else {
            set(out->big, sizeof(out->big), count ? "-" : "No games");
        }
        set(out->foot, sizeof(out->foot), pages > 1 ? "1-9  0 more  # ok" : "1-9 pick  # ok");
        return true;
    }
    if (strcmp(t, "timer_adjust") == 0) {
        set(out->head, sizeof(out->head), "GAME TIME");
        screen_json_int(data, "timer_s", &v);
        clock_text(v, out->big, sizeof(out->big));
        set(out->foot, sizeof(out->foot), "2 +5  8 -5  # ok");
        return true;
    }
    if (strcmp(t, "start_confirm") == 0) {
        set(out->head, sizeof(out->head), "START?");
        if (screen_json_str(data, "label", s, sizeof(s)) && s[0]) {
            set(out->big, sizeof(out->big), s);
        }
        if (screen_json_int(data, "timer_s", &v)) {
            clock_text(v, out->head_right, sizeof(out->head_right));
        }
        set(out->foot, sizeof(out->foot), "# start  * back");
        return true;
    }
    if (strcmp(t, "status") == 0) {
        if (!screen_json_str(data, "title", s, sizeof(s)) || !s[0]) set(s, sizeof(s), "status");
        upper(s);
        set(out->head, sizeof(out->head), s);
        if (screen_json_str(data, "mode", s, sizeof(s)) && s[0]) set(out->big, sizeof(out->big), s);
        if (screen_json_int(data, "timer_s", &v)) clock_text(v, out->foot, sizeof(out->foot));
        return true;
    }
    if (strcmp(t, "wifi_setup") == 0) {
        set(out->head, sizeof(out->head), "WI-FI SETUP");
        if (!screen_json_str(data, "ssid", s, sizeof(s)) || !s[0])
            set(s, sizeof(s), "atalaia-....");
        set(out->big, sizeof(out->big), s);
        set(out->foot, sizeof(out->foot), "open 192.168.4.1");
        return true;
    }

    /* ---- mode screens: the mode in the header ---- */
    set(out->head, sizeof(out->head), mode);
    if (strcmp(t, "standby") == 0) {
        set(out->big, sizeof(out->big), "STANDBY");
        out->bar = share_pct(data, "progress");
        if (out->bar >= 0) {
            set(out->foot, sizeof(out->foot), "ARMING");
        } else if (screen_json_str(data, "arm", s, sizeof(s)) && s[0]) {
            upper(s);
            snprintf(out->foot, sizeof(out->foot), "Hold %s to arm", s);
        } else {
            set(out->foot, sizeof(out->foot), "Waiting");
        }
        return true;
    }
    if (strcmp(t, "paused") == 0) {
        set(out->big, sizeof(out->big), "PAUSED");
        set(out->foot, sizeof(out->foot), "Wait for the GM");
        return true;
    }
    if (strcmp(t, "code_entry") == 0) {
        if (screen_json_str(data, "title", s, sizeof(s)) && s[0]) {
            upper(s);
            set(out->head, sizeof(out->head), s);
        }
        screen_json_int(data, "digits", &v);
        dots(v, out->big, sizeof(out->big));
        if (screen_json_int(data, "left", &v))
            clock_text(v, out->head_right, sizeof(out->head_right));
        static const char *const msg_keys[] = {"message", NULL};
        first_str(data, msg_keys, out->foot, sizeof(out->foot));
        return true;
    }

    /* Everything else, the modes' own templates included: a countdown when
     * there is one, else the screen's name; a team, owner or message below. */
    if (screen_json_int(data, "left", &v)) {
        clock_text(v, out->big, sizeof(out->big));
    } else if (strcmp(t, "final_score") == 0) {
        set(out->big, sizeof(out->big), "GAME OVER");
    } else {
        set(out->big, sizeof(out->big), t);
        upper(out->big);
    }
    out->bar = share_pct(data, strcmp(t, "countdown") == 0 ? "defuse" : "progress");
    if (out->bar >= 0 && strcmp(t, "countdown") == 0) {
        set(out->foot, sizeof(out->foot), "DEFUSE");
        return true;
    }
    static const char *const team_keys[] = {"team", "owner", "winner", NULL};
    static const char *const text_keys[] = {"message", "title", "label", NULL};
    if (first_str(data, team_keys, s, sizeof(s))) {
        upper(s);
        set(out->foot, sizeof(out->foot), s);
    } else if (strcmp(t, "countdown") == 0) {
        set(out->foot, sizeof(out->foot), "until detonation");
    } else {
        first_str(data, text_keys, out->foot, sizeof(out->foot));
    }
    return true;
}

void oled_pack(const uint16_t *rgb565, uint8_t fb[HAL_OLED_FB_SIZE])
{
    memset(fb, 0, HAL_OLED_FB_SIZE);
    for (int y = 0; y < HAL_OLED_HEIGHT; y++) {
        for (int x = 0; x < HAL_OLED_WIDTH; x++) {
            uint16_t c = rgb565[y * HAL_OLED_WIDTH + x];
            /* 5-6-5 bits scaled to 0-63 each, summed: 0-189. */
            unsigned lum = ((c >> 11) & 0x1F) * 2u + ((c >> 5) & 0x3F) + (c & 0x1F) * 2u;
            if (lum >= 95) fb[(y / 8) * HAL_OLED_WIDTH + x] |= (uint8_t)(1u << (y % 8));
        }
    }
}

/* ---- Drawing (LVGL) ---------------------------------------------------- */

#if ATALAIA_SCREEN_LVGL

#include "oled_logo.h"

#define OLED_W   HAL_OLED_WIDTH
#define OLED_H   HAL_OLED_HEIGHT
#define BAR_H    16
#define TEXT_MAX (OLED_W - 4)

#define HOLD_BAR_W 48
#define HOLD_BAR_H 12

static lv_obj_t *bar, *head, *head_right, *big, *foot, *hold_box, *hold_fill;
static bool built;

static char mode_title[32];
static char pending_t[SCREEN_TEMPLATE_MAX];
static char pending_data[SCREEN_DATA_MAX];
static bool pending;
static uint32_t splash_until;
static bool splash_on;

/* One line of text: too long ends in "...", never wraps. */
static lv_obj_t *text(lv_obj_t *parent, const lv_font_t *font, lv_color_t colour)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, colour, 0);
    lv_label_set_long_mode(l, LV_LABEL_LONG_DOT);
    lv_obj_set_height(l, lv_font_get_line_height(font));
    return l;
}

static void clean(lv_obj_t *scr)
{
    lv_obj_clean(scr);
    lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_pad_all(scr, 0, 0);
    lv_obj_set_style_bg_color(scr, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    built = false;
}

static void build(lv_obj_t *scr)
{
    clean(scr);
    bar = lv_obj_create(scr);
    lv_obj_remove_style_all(bar);
    lv_obj_set_size(bar, OLED_W, BAR_H);
    lv_obj_set_style_bg_color(bar, lv_color_white(), 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
    lv_obj_align(bar, LV_ALIGN_TOP_LEFT, 0, 0);

    head_right = text(bar, &lv_font_montserrat_14, lv_color_black());
    lv_label_set_long_mode(head_right, LV_LABEL_LONG_CLIP);
    lv_obj_align(head_right, LV_ALIGN_RIGHT_MID, -2, 0);
    head = text(bar, &lv_font_montserrat_14, lv_color_black());
    lv_obj_align(head, LV_ALIGN_LEFT_MID, 2, 0);

    big = text(scr, &lv_font_montserrat_28, lv_color_white());
    lv_obj_set_width(big, TEXT_MAX);
    lv_obj_set_style_text_align(big, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(big, LV_ALIGN_CENTER, 0, 0);

    foot = text(scr, &lv_font_montserrat_14, lv_color_white());

    /* A hold's progress: an outlined box filling from the left. */
    hold_box = lv_obj_create(scr);
    lv_obj_remove_style_all(hold_box);
    lv_obj_set_size(hold_box, HOLD_BAR_W, HOLD_BAR_H);
    lv_obj_set_style_border_color(hold_box, lv_color_white(), 0);
    lv_obj_set_style_border_width(hold_box, 1, 0);
    lv_obj_set_style_pad_all(hold_box, 2, 0);
    lv_obj_align(hold_box, LV_ALIGN_BOTTOM_RIGHT, -1, -2);
    hold_fill = lv_obj_create(hold_box);
    lv_obj_remove_style_all(hold_fill);
    lv_obj_set_style_bg_color(hold_fill, lv_color_white(), 0);
    lv_obj_set_style_bg_opa(hold_fill, LV_OPA_COVER, 0);
    lv_obj_set_height(hold_fill, HOLD_BAR_H - 6);
    lv_obj_align(hold_fill, LV_ALIGN_LEFT_MID, 0, 0);
    built = true;
}

static int32_t width_of(const char *s, const lv_font_t *font)
{
    return lv_text_get_width(s, (uint32_t)strlen(s), font, 0);
}

void oled_view_draw(lv_obj_t *scr, const oled_text_t *t)
{
    if (!scr) return;
    if (!built) build(scr);

    lv_label_set_text(head_right, t->head_right);
    int32_t right_w = t->head_right[0] ? width_of(t->head_right, &lv_font_montserrat_14) + 6 : 0;
    lv_obj_set_width(head, OLED_W - 4 - right_w);
    lv_label_set_text(head, t->head);

    /* The biggest font the middle line fits in. */
    const lv_font_t *font = &lv_font_montserrat_28;
    if (width_of(t->big, font) > TEXT_MAX) font = &lv_font_montserrat_20;
    if (width_of(t->big, font) > TEXT_MAX) font = &lv_font_montserrat_14;
    lv_obj_set_style_text_font(big, font, 0);
    lv_obj_set_height(big, lv_font_get_line_height(font));
    lv_label_set_text(big, t->big);
    lv_obj_align(big, LV_ALIGN_CENTER, 0, 0);

    /* The footer: centred text, or text on the left and the hold bar. */
    bool with_bar = t->bar >= 0;
    if (with_bar) {
        lv_obj_set_width(foot, OLED_W - HOLD_BAR_W - 6);
        lv_obj_set_style_text_align(foot, LV_TEXT_ALIGN_LEFT, 0);
        lv_obj_align(foot, LV_ALIGN_BOTTOM_LEFT, 2, 0);
        int inner = HOLD_BAR_W - 6;
        int pct = t->bar > 100 ? 100 : t->bar;
        lv_obj_set_width(hold_fill, inner * pct / 100);
        lv_obj_remove_flag(hold_box, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_set_width(foot, TEXT_MAX);
        lv_obj_set_style_text_align(foot, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_align(foot, LV_ALIGN_BOTTOM_MID, 0, 0);
        lv_obj_add_flag(hold_box, LV_OBJ_FLAG_HIDDEN);
    }
    lv_label_set_text(foot, t->foot);
}

void oled_view_splash(lv_obj_t *scr, const char *version, uint32_t now_ms, uint32_t hold_ms)
{
    if (!scr) return;
    clean(scr);

    static lv_image_dsc_t logo;
    logo.header.magic = LV_IMAGE_HEADER_MAGIC;
    logo.header.cf = LV_COLOR_FORMAT_A8;
    logo.header.w = OLED_LOGO_W;
    logo.header.h = OLED_LOGO_H;
    logo.header.stride = OLED_LOGO_W;
    logo.data = oled_logo_a8;
    logo.data_size = sizeof(oled_logo_a8);

    lv_obj_t *img = lv_image_create(scr);
    lv_image_set_src(img, &logo);
    lv_obj_set_style_image_recolor(img, lv_color_white(), 0);
    lv_obj_set_style_image_recolor_opa(img, LV_OPA_COVER, 0);
    lv_obj_align(img, LV_ALIGN_LEFT_MID, 4, 0);

    lv_obj_t *name = text(scr, &lv_font_montserrat_20, lv_color_white());
    lv_label_set_text(name, "ATALAIA");
    lv_obj_align(name, LV_ALIGN_LEFT_MID, OLED_LOGO_W + 10, -8);

    lv_obj_t *ver = text(scr, &lv_font_montserrat_14, lv_color_white());
    lv_label_set_text(ver, version ? version : "");
    lv_obj_align_to(ver, name, LV_ALIGN_OUT_BOTTOM_LEFT, 0, 2);

    splash_on = true;
    splash_until = now_ms + hold_ms;
}

static void show(lv_obj_t *scr, const char *t, const char *data)
{
    oled_text_t txt;
    if (oled_text_for(mode_title, t, data, &txt)) oled_view_draw(scr, &txt);
}

void oled_view_handle(lv_obj_t *scr, const char *t, const char *data, uint32_t now_ms)
{
    if (!t) return;
    if (strcmp(t, "@mode") == 0) {
        oled_mode_title(data, mode_title, sizeof(mode_title));
        return;
    }
    if (splash_on && (int32_t)(now_ms - splash_until) < 0) {
        set(pending_t, sizeof(pending_t), t);
        set(pending_data, sizeof(pending_data), data);
        pending = true;
        return;
    }
    splash_on = false;
    pending = false;
    show(scr, t, data);
}

void oled_view_poll(lv_obj_t *scr, uint32_t now_ms)
{
    if (!splash_on || (int32_t)(now_ms - splash_until) < 0) return;
    splash_on = false;
    if (pending) {
        pending = false;
        show(scr, pending_t, pending_data);
    }
}

#endif /* ATALAIA_SCREEN_LVGL */
