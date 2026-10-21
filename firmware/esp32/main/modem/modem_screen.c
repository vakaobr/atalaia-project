/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The USB radio modem's on-board OLED (modem_screen.h): a 16-pixel header
 * bar (the tower icon and "MODEM MODE", Montserrat 14, dark on lit) and six
 * 8-pixel lines of unscii 8, 16 characters each.
 */
#include "modem_screen.h"

#include <stdio.h>
#include <string.h>

/* ---- State and text (plain C) ------------------------------------------- */

void modem_screen_state(const modem_t *m, uint32_t now_ms, uint32_t link_timeout_ms,
                        uint32_t idle_channel_hz, uint32_t duty_ms, const char *fault,
                        modem_screen_state_t *out)
{
    memset(out, 0, sizeof(*out));
    if (!m->host_seen) {
        out->link = MODEM_LINK_WAITING;
    } else {
        out->link = now_ms - m->last_host_ms <= link_timeout_ms ? MODEM_LINK_UP : MODEM_LINK_DOWN;
    }
    out->configured = m->configured;
    out->measuring = m->measuring;
    out->game_id = m->game_id;
    out->channel_hz = m->channel_hz ? m->channel_hz : idle_channel_hz;
    out->rx = m->count.rx_ok;
    out->rx_auth_fail = m->count.rx_auth_fail;
    out->tx = m->count.tx_ok;
    out->tx_fail = m->count.tx_fail;
    out->radio_ok = m->radio_present;
    out->duty_ms = m->radio_present ? duty_ms : 0;
    if (!m->radio_present) {
        snprintf(out->fault, sizeof(out->fault), "%s",
                 fault && fault[0] ? fault : "no SX1262 radio");
    }
}

static int digits(uint32_t n)
{
    int d = 1;
    while (n >= 10) {
        n /= 10;
        d++;
    }
    return d;
}

void modem_screen_count(uint32_t n, int width, char *out, size_t out_sz)
{
    static const char units[] = {'k', 'M', 'G'};
    if (digits(n) <= width) {
        snprintf(out, out_sz, "%lu", (unsigned long)n);
        return;
    }
    uint32_t v = n;
    for (size_t u = 0; u < sizeof(units); u++) {
        v /= 1000u;
        if (digits(v) + 1 <= width || u + 1 == sizeof(units)) {
            snprintf(out, out_sz, "%lu%c", (unsigned long)v, units[u]);
            return;
        }
    }
}

/* left, then right flush with the 16th column; right is cut when both do not fit. */
static void two_col(char *out, const char *left, const char *right)
{
    size_t l = strlen(left);
    if (l > MODEM_SCREEN_COLS) l = MODEM_SCREEN_COLS;
    memset(out, ' ', MODEM_SCREEN_COLS);
    memcpy(out, left, l);
    size_t r = strlen(right);
    size_t room = l < MODEM_SCREEN_COLS ? MODEM_SCREEN_COLS - l - (l ? 1 : 0) : 0;
    if (r > room) r = room;
    memcpy(out + MODEM_SCREEN_COLS - r, right, r);
    /* Trailing spaces off, so the lines compare and test simply. */
    size_t end = MODEM_SCREEN_COLS;
    while (end > 0 && out[end - 1] == ' ') end--;
    out[end] = '\0';
}

/* The first line of s that fits in 16 columns, broken at a space when one
 * is there; returns where the rest starts. */
static const char *wrap(const char *s, char *out)
{
    while (*s == ' ') s++;
    size_t len = strlen(s);
    size_t n = len;
    if (len > MODEM_SCREEN_COLS) {
        n = MODEM_SCREEN_COLS;
        for (size_t i = MODEM_SCREEN_COLS; i > 0; i--) {
            if (s[i] == ' ') {
                n = i;
                break;
            }
        }
    }
    memcpy(out, s, n);
    out[n] = '\0';
    return s + n;
}

/* 869525000 -> "869.525 MHz". */
static void mhz(uint32_t hz, char *out, size_t sz)
{
    snprintf(out, sz, "%lu.%03lu MHz", (unsigned long)(hz / 1000000u),
             (unsigned long)((hz / 1000u) % 1000u));
}

/* 359900 -> "359.9s", 3600000 -> "3600s". */
static void seconds(uint32_t ms, char *out, size_t sz)
{
    if (ms < 1000000u) {
        snprintf(out, sz, "%lu.%lus", (unsigned long)(ms / 1000u),
                 (unsigned long)((ms / 100u) % 10u));
    } else {
        snprintf(out, sz, "%lus", (unsigned long)(ms / 1000u));
    }
}

/* "TX 1234" and "fail 0": the count in 4 characters, the failures in 3. */
static void counts(char *out, const char *label, uint32_t n, const char *bad_label, uint32_t bad)
{
    char a[8], b[8], left[16], right[16];
    modem_screen_count(n, 4, a, sizeof(a));
    modem_screen_count(bad, 3, b, sizeof(b));
    snprintf(left, sizeof(left), "%s %s", label, a);
    snprintf(right, sizeof(right), "%s %s", bad_label, b);
    two_col(out, left, right);
}

void modem_screen_text(const modem_screen_state_t *s, modem_screen_text_t *out)
{
    memset(out, 0, sizeof(*out));
    char v[24];

    switch (s->link) {
    case MODEM_LINK_UP: two_col(out->line[0], "LINK", "OK"); break;
    case MODEM_LINK_DOWN:
        two_col(out->line[0], "LINK", "DOWN");
        out->inverted[0] = true;
        break;
    default: two_col(out->line[0], "LINK", "waiting"); break;
    }

    if (s->configured) {
        snprintf(v, sizeof(v), "%u", (unsigned)s->game_id);
        two_col(out->line[1], "GAME", v);
    } else {
        two_col(out->line[1], "IDLE", s->measuring ? "measuring" : "no game");
    }

    if (!s->radio_ok) {
        two_col(out->line[2], "RADIO FAULT", "");
        out->inverted[2] = true;
        const char *rest = wrap(s->fault, out->line[3]);
        wrap(rest, out->line[4]);
        two_col(out->line[5], "no TX, no RX", "");
        return;
    }

    mhz(s->channel_hz, v, sizeof(v));
    two_col(out->line[2], "CH", v);
    counts(out->line[3], "TX", s->tx, "fail", s->tx_fail);
    counts(out->line[4], "RX", s->rx, "auth", s->rx_auth_fail);
    char left[12];
    seconds(s->duty_ms, left, sizeof(left));
    snprintf(v, sizeof(v), "%s left", left);
    two_col(out->line[5], "DUTY", v);
    out->inverted[5] = s->duty_ms == 0;
}

/* ---- Drawing (LVGL) ------------------------------------------------------ */

#if ATALAIA_SCREEN_LVGL

#include "hal_oled.h"
#include "oled_logo.h"

#define OLED_W HAL_OLED_WIDTH
#define BAR_H  16
#define LINE_H 8

static lv_obj_t *lines[MODEM_SCREEN_LINES];
static bool built;

static void clean(lv_obj_t *scr)
{
    lv_obj_clean(scr);
    lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_pad_all(scr, 0, 0);
    lv_obj_set_style_bg_color(scr, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    built = false;
}

static lv_obj_t *image(lv_obj_t *parent, lv_image_dsc_t *dsc, const uint8_t *data, int w, int h,
                       lv_color_t colour)
{
    dsc->header.magic = LV_IMAGE_HEADER_MAGIC;
    dsc->header.cf = LV_COLOR_FORMAT_A8;
    dsc->header.w = (uint32_t)w;
    dsc->header.h = (uint32_t)h;
    dsc->header.stride = (uint32_t)w;
    dsc->data = data;
    dsc->data_size = (uint32_t)(w * h);
    lv_obj_t *img = lv_image_create(parent);
    lv_image_set_src(img, dsc);
    lv_obj_set_style_image_recolor(img, colour, 0);
    lv_obj_set_style_image_recolor_opa(img, LV_OPA_COVER, 0);
    return img;
}

static lv_obj_t *label(lv_obj_t *parent, const lv_font_t *font, const char *s)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, lv_color_white(), 0);
    lv_label_set_long_mode(l, LV_LABEL_LONG_CLIP);
    lv_label_set_text(l, s);
    return l;
}

static void build(lv_obj_t *scr)
{
    clean(scr);
    lv_obj_t *bar = lv_obj_create(scr);
    lv_obj_remove_style_all(bar);
    lv_obj_set_size(bar, OLED_W, BAR_H);
    lv_obj_set_style_bg_color(bar, lv_color_white(), 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
    lv_obj_align(bar, LV_ALIGN_TOP_LEFT, 0, 0);

    static lv_image_dsc_t icon;
    lv_obj_t *img = image(bar, &icon, oled_icon_a8, OLED_ICON_W, OLED_ICON_H, lv_color_black());
    lv_obj_align(img, LV_ALIGN_LEFT_MID, 2, 0);
    lv_obj_t *title = label(bar, &lv_font_montserrat_14, "MODEM MODE");
    lv_obj_set_style_text_color(title, lv_color_black(), 0);
    lv_obj_align(title, LV_ALIGN_LEFT_MID, OLED_ICON_W + 5, 0);

    for (int i = 0; i < MODEM_SCREEN_LINES; i++) {
        lines[i] = label(scr, &lv_font_unscii_8, "");
        lv_obj_set_size(lines[i], OLED_W, LINE_H);
        lv_obj_set_style_bg_color(lines[i], lv_color_white(), 0);
        lv_obj_align(lines[i], LV_ALIGN_TOP_LEFT, 0, BAR_H + i * LINE_H);
    }
    built = true;
}

void modem_screen_draw(lv_obj_t *scr, const modem_screen_text_t *t)
{
    if (!scr) return;
    if (!built) build(scr);
    for (int i = 0; i < MODEM_SCREEN_LINES; i++) {
        lv_label_set_text(lines[i], t->line[i]);
        lv_obj_set_style_bg_opa(lines[i], t->inverted[i] ? LV_OPA_COVER : LV_OPA_TRANSP, 0);
        lv_obj_set_style_text_color(lines[i], t->inverted[i] ? lv_color_black() : lv_color_white(),
                                    0);
    }
}

void modem_screen_splash(lv_obj_t *scr, const char *version)
{
    if (!scr) return;
    clean(scr);

    static lv_image_dsc_t logo;
    lv_obj_t *img = image(scr, &logo, oled_logo_a8, OLED_LOGO_W, OLED_LOGO_H, lv_color_white());
    lv_obj_align(img, LV_ALIGN_LEFT_MID, 4, 0);

    const int32_t x = OLED_LOGO_W + 10;
    lv_obj_t *name = label(scr, &lv_font_montserrat_20, "ATALAIA");
    lv_obj_align(name, LV_ALIGN_TOP_LEFT, x, 8);
    lv_obj_t *mode = label(scr, &lv_font_unscii_8, "MODEM MODE");
    lv_obj_align_to(mode, name, LV_ALIGN_OUT_BOTTOM_LEFT, 0, 4);
    lv_obj_t *ver = label(scr, &lv_font_unscii_8, version ? version : "");
    lv_obj_align_to(ver, mode, LV_ALIGN_OUT_BOTTOM_LEFT, 0, 6);
}

#endif /* ATALAIA_SCREEN_LVGL */
